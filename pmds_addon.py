# Copyright 2026 Michael Foley
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under the terms of
# the GNU General Public License as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details: <https://www.gnu.org/licenses/>.
"""
pmds_addon.py - PMDS for the all-mode-receiver tuner
====================================================
Install this repository once (pip install -e <this folder>) and the all-mode-receiver tuner
finds PMDS by itself: on AM it decodes PMDS station data and shows it the way it shows RDS on
FM (call letters, name, RadioText, program type, the alert), with a PMDS lamp and meters in
the Advanced window, and the PMDS data monitor on key I. Without it the tuner is a plain AM
radio. The tuner finds it through the all_mode_receiver.addons entry point in pyproject.toml.

The data path, on the AM receiver's channel (48 kHz, before its own carrier lock):
  carrier PLL   about 1 Hz, below where the data has its energy. The AM receiver's own
                4 Hz lock (set for C-QUAM) would follow and cancel part of the slow rates' data.
  data channel  low-pass to 500 Hz (187.5 bit/s data is within about +/-400 Hz), decimated
                by 8 to 6000 Hz
  decoders      one PmdsDecoder per bit rate (23.4375, 46.875, 93.75, 187.5 bit/s), each
                framing the bits both ways (compact and RBDS-native); whichever holds block
                sync reports the station

PmdsDecoder, data_path() and the constants are also what pmds_check.py and
pmds_channel_test.py use, so the bench tools decode exactly as the tuner does.
"""
import math

import numpy as np
from gnuradio import gr, filter, analog
from gnuradio.filter import firdes

from pmds.codec import pi_to_callsign
from pmds.demod import Demodulator

PMDS_FS    = 6000                             # data path sample rate: 32 samples per bit at 187.5 bit/s
PMDS_RATES = (23.4375, 46.875, 93.75, 187.5)
PLL_HZ     = 1.0                              # carrier PLL; a 4 Hz one follows (and eats) the slow rate's data
PLL_PULL_HZ = 60.0                            # how far off frequency the PLL will pull in


# ---------------------------------------------------------------------------
# PMDS decoder block
# ---------------------------------------------------------------------------
# One PmdsDecoder per bit rate. The signal processing and both framers are pmds.Demodulator
# (pmds/demod.py, pmds/framer.py); this is the GNU Radio block around it.

class PmdsDecoder(Demodulator, gr.sync_block):
    """pmds.Demodulator as a GNU Radio sink: complex in at fs, carrier on the real axis."""

    def __init__(self, fs=6000, bit_rate=46.875):
        gr.sync_block.__init__(self, name='PMDS decoder %g' % bit_rate,
                               in_sig=[np.complex64], out_sig=None)
        Demodulator.__init__(self, fs, bit_rate)

    def work(self, input_items, output_items):
        return self.process(input_items[0])


def data_path(tb, src, ch_rate, rates=PMDS_RATES):
    """Build the PMDS data path on a channel at ch_rate (a multiple of 6000 Hz, carrier near
    0 Hz) and connect it: tb.connect(src, PLL, data channel, decoders). Returns
    (pll, data_lp, decoders)."""
    pll = analog.pll_carriertracking_cc(2 * math.pi * PLL_HZ / ch_rate,
                                        2 * math.pi * PLL_PULL_HZ / ch_rate,
                                        -2 * math.pi * PLL_PULL_HZ / ch_rate)
    taps = firdes.low_pass(1.0, ch_rate, 500.0, 300.0, filter.window.WIN_HAMMING)
    lp = filter.fir_filter_ccf(int(ch_rate) // PMDS_FS, taps)
    decs = [PmdsDecoder(PMDS_FS, r) for r in rates]
    tb.connect(src, pll, lp)
    for d in decs:
        tb.connect(lp, d)
    return pll, lp, decs


# ---------------------------------------------------------------------------
# The add-on (the interface is all-mode-receiver's docs/ADDONS.md)
# ---------------------------------------------------------------------------

class Addon:
    """PMDS on the all-mode-receiver AM receiver."""
    BANDS = ('AM',)
    NAME = 'PMDS'

    def __init__(self, rx):
        self.pll, self.lp, self.pmds = data_path(rx, rx.addon_tap(), rx.ch_rate)
        self._pi, self._call = None, None

    # ---- what the PMDS data monitor (pmds_monitor.py) uses ----
    def pmds_framers(self):
        return [f for d in self.pmds for f in d.framers]

    def set_pmds_strict(self, on):
        """Strict: no error correction, so the block counts show the raw channel."""
        for d in self.pmds:
            d.set_strict(on)

    def pmds_best(self):
        """The framer that holds sync, or heard a group last."""
        return max(self.pmds_framers(), key=lambda f: (f.synced, f.last_group_t))

    # ---- the add-on interface ----
    def reset(self):
        for d in self.pmds:
            d.reset()

    def update(self, now):
        best = self.pmds_best()
        if best.last_group_t < 0 and not best.synced:
            return None                                  # nothing heard yet
        # No 'mono' report: the tuner decides stereo by its own pilot test (a steady tone at
        # exactly 25 Hz, standing well clear of its surroundings), which PMDS data doesn't pass,
        # and a pilot it hears always wins. That way a false PMDS sync on a real C-QUAM station,
        # whose L-R sits on the same phase (bass panned to one side puts plenty in PMDS's band),
        # can't cost the station its stereo.
        out = dict(synced=best.synced, rate=best.rate(), bler=best.bler(),
                   bit_rate=best.bit_rate, format=best.fmt, fixed=best.fixed(),
                   dev_deg=best.dev_deg(), snr_db=best.snr_db(), cn_db=best.cn_db())
        if best.pi is not None:
            if best.pi != self._pi:
                self._pi, self._call = best.pi, pi_to_callsign(best.pi)
            out.update(pi=best.pi, call=self._call, ps=best.ps or '', rt=best.rt or '',
                       pty=best.pty, tp=best.tp, ta=best.ta, alert=best.alert or 0,
                       af=list(best.af_list), ct=best.clock, facility_id=best.facility_id,
                       isrc=best.isrc, artist=best.artist, title=best.title)
        return out

    def readout(self):
        best = self.pmds_best()
        if best.last_group_t < 0 and not best.synced:
            return 'PMDS: searching (23.4 to 187.5 bit/s, compact and RBDS)'
        cn = best.cn_db()
        song = ' / '.join(x for x in (best.artist, best.title) if x)
        extra = '   '.join(x for x in (
            f"facility {best.facility_id}" if best.facility_id else '',
            f"ISRC {best.isrc}" if best.isrc else '',
            f"RT+ {song}" if song else '') if x)
        return (f"PMDS {'synced' if best.synced else 'lost'} {best.fmt} {best.bit_rate:g} bit/s   "
                f"data {best.dev_deg():4.1f} deg  SNR {best.snr_db():4.1f} dB  "
                f"C/N {'--' if cn is None else f'{cn:.1f} dB'} in-band   {best.fixed():3.0f}% fixed"
                + (f"   {extra}" if extra else ''))

    def meter(self):
        best = self.pmds_best()
        heard = best.last_group_t >= 0 or best.synced
        if best.synced:
            return ('PMDS data', min(best.snr_db(), 40.0) / 40.0, f"{best.dev_deg():4.1f} deg")
        return ('PMDS data', 0.0, 'lost' if heard else 'none')

    @classmethod
    def make_window(cls, parent, current):
        """The PMDS data monitor: every block and group as the decoders see them."""
        from pmds_monitor import PmdsMonitor
        return PmdsMonitor(parent, current)
