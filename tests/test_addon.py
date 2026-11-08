#!/usr/bin/env python3
# Copyright 2026 Michael Foley
# SPDX-License-Identifier: GPL-3.0-or-later
"""
test_addon.py - does PMDS decode through the all-mode-receiver tuner's AM receiver?

    python tests/test_addon.py
    python tests/test_addon.py --radio /path/to/all-mode-receiver

End to end, in GNU Radio: a simulated AM station (a carrier with a 1 kHz tone at 50%, PMDS
from pmds.Encoder at 8.6 degrees, noise for 40 dB C/N) goes in where the dongle would, at the
receiver's 960 ksps, into all-mode-receiver's own AMReceiver with the PMDS add-on attached the
way the tuner attaches it. Then the station data the tuner shows must be right: call letters,
name, RadioText, the alert, and the receiver must not mistake the data for a C-QUAM stereo
pilot. Runs 93.75 bit/s (with and without an alert) and the slow 23.4375 bit/s, where the
add-on's own 1 Hz carrier lock matters. Runs faster than real time.

Needs GNU Radio and a copy of all-mode-receiver: --radio, or the ALL_MODE_RECEIVER
environment variable, or a folder named all-mode-receiver beside this repository. Without
either, it says so and stops.
"""
import argparse
import math
import os
import sys
import threading
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
sys.path.insert(0, TOP)
failed = 0
ALERT_TEXT = 'This is a test of the AM data alert flag.'      # replaces the RadioText while on


def check(name, ok, detail):
    global failed
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {name:44s} {detail}")


def station(secs, bit_rate, alert, fs=48000):
    """The station at 48 kHz complex baseband: 1 + 0.5 sin(1 kHz), with PMDS on its phase."""
    from pmds.encoder import Encoder
    e = Encoder(samp_rate=fs, deviation=8.6, bit_rate=bit_rate, call='WAMD', ps='AM 1650',
                rt='Hello, AM radio', rt_file='', alert=alert, alert_text=ALERT_TEXT,
                facility_id=73977)
    e.quiet = True
    t = np.arange(int(secs * fs)) / fs
    carrier = (1.0 + 0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.complex64)
    return e.modulate(carrier)


def run(bit_rate, secs, alert=0):
    from gnuradio import gr, blocks, analog, filter
    from radio.am import AMReceiver
    import radio.addons
    import pmds_addon
    from pmds.codec import callsign_to_pi

    class EntryPoint:                    # what the installed entry point would hand the tuner
        name = 'pmds'

        def load(self):
            return pmds_addon.Addon
    radio.addons._entry_points = lambda: [EntryPoint()]
    x = station(secs, bit_rate, alert)

    class Dongle(gr.hier_block2):
        """The station where the dongle would be: 960 ksps, 20 kHz below the tuned LO, noise."""
        def __init__(self, rate, ch_rate=48000):
            gr.hier_block2.__init__(self, 'pmds_station', gr.io_signature(0, 0, 0),
                                    gr.io_signature(1, 1, gr.sizeof_gr_complex))
            src = blocks.vector_source_c(x.tolist(), False)
            up = filter.rational_resampler_ccc(rate // ch_rate, 1)
            self.lo = analog.sig_source_c(rate, analog.GR_COS_WAVE, 0.0, 0.1)
            mix, add = blocks.multiply_cc(), blocks.add_cc()
            n0 = 0.1 ** 2 * 1e-4 / 1e4 * rate                  # 40 dB C/N in 10 kHz
            noise = analog.noise_source_c(analog.GR_GAUSSIAN, math.sqrt(n0), 11)
            self.connect(src, up, (mix, 0))
            self.connect(self.lo, (mix, 1))
            self.connect(mix, (add, 0))
            self.connect(noise, (add, 1))
            self.connect(add, self)
            self.station_hz = self.centre = 1650e3

        def set_center_freq(self, f, *a):
            self.centre = f
            self.lo.set_frequency(self.station_hz - self.centre)
            return f

        def get_gain_range(self, *a):
            raise RuntimeError('none')

        def __getattr__(self, name):
            if name.startswith('__'):
                raise AttributeError(name)
            return lambda *a, **k: 0

    class Rx(AMReceiver):
        def _make_source(self, args):
            return Dongle(self.samp_rate)

        def _make_audio_sink(self, rate, device):
            return blocks.null_sink(gr.sizeof_float)

    rx = Rx(freq=1650e3)
    rx.set_auto_ceiling(8000)
    rx.set_if_mode('auto')
    rx.set_wide(False)
    done = threading.Event()
    rx.start()
    threading.Thread(target=lambda: (rx.wait(), done.set()), daemon=True).start()
    t0, synced_at, stereo_last = time.monotonic(), None, None
    while not done.is_set():
        try:
            rx.update_blend()
        except RuntimeError:
            pass                                          # the watchdog, once the station ends
        now = time.monotonic()                            # the receiver's own clock: its stereo
        if rx.rds_synced and synced_at is None:           # blend fades in wall-clock time
            synced_at = now
        if rx.pilot_on or rx.current_blend > 0:
            stereo_last = now
        time.sleep(0.02)
    rx._update_addons(time.monotonic())
    a = rx.addons[0] if rx.addons else None
    print(f"PMDS at {bit_rate:g} bit/s{', alert on' if alert else ''}: {secs:.0f} s of station "
          f"in {time.monotonic() - t0:.0f} s")
    check('the add-on attached to the AM receiver', a is not None and a.alive,
          'PMDS' if a is not None else 'not attached')
    if a is None:
        return
    check('in sync, at the right rate', rx.rds_synced and rx.station.get('bit_rate') == bit_rate,
          f"synced {rx.rds_synced}, {rx.station.get('bit_rate')} bit/s")
    check('call letters', (rx.rds_pi, rx.rds_call) == (callsign_to_pi('WAMD'), 'WAMD'),
          f"PI {rx.rds_pi if rx.rds_pi is None else format(rx.rds_pi, '04X')} {rx.rds_call}")
    check('station name', rx.rds_ps == 'AM 1650 ', repr(rx.rds_ps))
    want_rt = ALERT_TEXT if alert else 'Hello, AM radio'
    check('RadioText (the alert text, during an alert)', rx.rds_rt == want_rt, repr(rx.rds_rt))
    check('the alert', rx.station.get('alert', 0) == alert, f"alert {rx.station.get('alert')}")
    check('blocks lost', rx.rds_bler < 5, f"{rx.rds_bler:.0f}%")
    # the data can pass for a C-QUAM pilot (at 23.4375 bit/s it does) until PMDS syncs and the
    # add-on tells the receiver the station is mono; then the stereo blend fades out (0.5 s)
    late = stereo_last is not None and (synced_at is None or stereo_last > synced_at + 1.0)
    check('mono once PMDS is decoding (no stereo from the data)', not late,
          'never stereo' if stereo_last is None else
          f"stereo ended {stereo_last - synced_at:+.2f} s after PMDS synced" if synced_at else 'never synced')
    check("the add-on's line and meter for the window",
          f"{bit_rate:g} bit/s" in a.readout() and a.meter()[0] == 'PMDS data', a.readout()[:60])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('--radio', default=os.environ.get('ALL_MODE_RECEIVER',
                                                       os.path.join(os.path.dirname(TOP), 'all-mode-receiver')))
    a = ap.parse_args()
    try:
        from gnuradio import gr
    except ImportError:
        print('GNU Radio is not installed here, so there is nothing to test.')
        return 0
    if not os.path.isfile(os.path.join(a.radio, 'radio', 'am.py')):
        print(f'all-mode-receiver not found at {a.radio}: give its folder with --radio.')
        return 0
    sys.path.insert(0, os.path.abspath(a.radio))
    print('GNU Radio', gr.version(), '| all-mode-receiver at', os.path.abspath(a.radio))
    run(93.75, 30)
    run(93.75, 30, alert=2)
    run(23.4375, 90)
    print('\nAll passed.' if not failed else f'\n{failed} failed.')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
