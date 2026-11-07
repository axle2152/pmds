#!/usr/bin/env python3
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
pmds_receiver.py - mono AM receiver with the PMDS (Phase Modulation Data Service) decoder
=========================================================================================
am_receiver.py with C-QUAM, Kahn, the stereo pilot and the 10 kHz notch taken
out, and a decoder for RDS-lite station data on the carrier's phase. Same
interface as AMReceiver / FMStereoReceiver, so the tuner UI drives it as is.

Signal chain (2.4 Msps from the RTL -> 48 kHz complex channel)
  source        Q-branch direct sampling, native HF tuning (V4) or an upconverter
  channel       two-stage decimating filter, station 20 kHz below the LO
  carrier       coarse frequency correction from the channel spectrum, then a
                slow PLL (about 1 Hz), below where the data has its energy
  IF filter     adaptive bandwidth, as before (auto / wide / narrow)
  audio         envelope detection, 60 Hz high-pass, the IF low-pass, then
                tone, volume and mute; mono on both channels
  PMDS          the PLL's output (carrier on the real axis) low-passed and
                decimated to 6000 Hz; its quadrature goes to four decoders, one per
                bit rate (23.4375, 46.875, 93.75, 187.5 bit/s), each framing the bits
                both ways (compact and RBDS-native); whichever holds block sync
                fills in rds_pi / rds_ps / rds_rt for the display

PMDS decoder: the carrier's phase measured against a local carrier reference
(averaged over the last 4 bits, so fading faster than the 1 Hz PLL can follow is
taken out, and the program's own AM doesn't multiply what's left), a matched
filter for the one-sine-per-bit biphase, bit timing from the phase with the most
matched-filter energy (tracks clock drift between the transmitter and the dongle),
then block sync on the offset words, single-bit correction where the block type
is known, and the group fields, for both framings. Character set, CRC and offsets
come from the pmds package, so the encoder and decoder can't drift apart. set_pmds_strict(True)
turns the correction off; pmds_framers() gives every framer's block counts.
"""

import math
import threading
import time

import numpy as np
from gnuradio import gr, blocks, filter, analog, audio
from gnuradio.filter import firdes
import osmosdr

from pmds.codec import pi_to_callsign
from pmds.demod import Demodulator
try:                                     # optional read-only meters for the monitor UI
    import rx_meters
    if rx_meters.AudioMeterBlock is None:
        rx_meters = None
except ImportError:
    rx_meters = None

W = filter.window.WIN_HAMMING


class PMDSReceiver(gr.top_block):
    # ---- source ----
    AM_SOURCE        = 'direct_q'   # 'direct_q' | 'native' | 'upconverter'
    UPCONVERTER_HZ   = 125e6        # Ham It Up and similar
    LO_OFFSET        = 20e3         # tune this far above the station (keeps it off DC)
    SAMP_RATE        = 2_400_000
    CH_RATE          = 48_000

    # ---- bandwidth (one-sided audio bandwidth, Hz) ----
    AM_WIDE_HZ       = 10000.0      # NRSC full bandwidth
    AM_NARROW_HZ     = 4000.0       # the manual "narrow" setting
    AM_XWIDE_HZ      = 10200.0      # set_wide(True): everything an NRSC-1 station sends
    AM_MIN_HZ        = 2500.0
    # carrier-to-noise (dB in 10 kHz) -> bandwidth, interpolated
    BW_TABLE         = [(15, 2500), (22, 3500), (28, 4500), (34, 6000), (40, 8000), (46, 10000)]
    # a carrier 10 kHz away this strong (dB re ours) limits the bandwidth to...
    ADJ_TABLE        = [(-35, 7000), (-25, 5000), (-15, 4000), (-8, 3000)]
    BW_SLEW_IN       = 2000.0       # Hz per second, narrowing
    BW_SLEW_OUT      = 4000.0       # Hz per second, widening
    BW_STEP          = 200.0        # redesign the filters when it has moved this far

    # ---- PMDS ----
    PMDS_FS          = 6000         # data path sample rate: 32 samples per bit at 187.5 bit/s
    PMDS_RATES       = (23.4375, 46.875, 93.75, 187.5)
    PLL_HZ           = 1.0          # carrier PLL; am_receiver.py's 4 Hz follows (and eats) the slow rate's data

    # ---- level / UI ----
    AM_AUDIO_GAIN    = 1.4          # 100% modulation -> about the FM side's level
    SEEK_MIN_DB      = 22.0         # seek stops on a carrier this far above the noise
    TUNE_SETTLE_S    = 0.25
    STALL_S          = 2.0
    TONE_BASS_HZ, TONE_TREBLE_HZ, TONE_RANGE_DB = 120.0, 4000.0, 12.0
    TONE_SAFETY_DB   = 1.0
    IF_TAPS          = 97           # IF and audio filters: fixed length, fixed delay
    MPX_FULL         = 1.0          # ADV audio spectrum: 1.0 = 100% modulation

    def __init__(self, freq=1080e3, rf_gain=0.0, agc=False, audio_device="",
                 device_args="numchan=1 rtl=0", am_source=None, upconverter_hz=None, **_):
        gr.top_block.__init__(self, "PMDS Receiver")
        self._lock = threading.RLock()
        self.am_source = am_source or self.AM_SOURCE
        if upconverter_hz:
            self.UPCONVERTER_HZ = float(upconverter_hz)
        self.freq = freq
        self.samp_rate, self.ch_rate = self.SAMP_RATE, self.CH_RATE
        self.audio_rate = self.CH_RATE
        self.mpx_rate = self.CH_RATE
        self.gain_db, self.agc_enabled = float(rf_gain), bool(agc)   # kept for the GUI
        c = self.connect

        # ---------------- source ----------------
        args = device_args
        if self.am_source == 'direct_q':
            args = f"{device_args},direct_samp=2"
        self.src = self._make_source(args)
        self.src.set_sample_rate(self.samp_rate)
        self.src.set_center_freq(self._lo(freq), 0)
        self.src.set_freq_corr(0, 0)
        self.src.set_dc_offset_mode(0, 0)
        self.src.set_iq_balance_mode(0, 0)
        if self.am_source == 'direct_q':
            self.src.set_gain_mode(False, 0)          # no tuner in the path
        elif agc:
            self.src.set_gain_mode(True, 0)
        else:
            self.src.set_gain_mode(False, 0)
            self.src.set_gain(self.gain_db, 0)

        # ---------------- channel ----------------
        t1 = firdes.low_pass(1.0, self.samp_rate, 30e3, 70e3, W)
        self.xlate = filter.freq_xlating_fir_filter_ccf(10, t1, -self.LO_OFFSET, self.samp_rate)
        t2 = firdes.low_pass(1.0, 240e3, 14e3, 8e3, W)
        self.dec2 = filter.fir_filter_ccf(5, t2)
        self.rot = blocks.rotator_cc(0.0)               # coarse carrier correction
        self.bw = self.AM_WIDE_HZ
        self.if_filter = filter.fir_filter_ccf(1, self._lp_taps(self.bw))
        self.pll = analog.pll_carriertracking_cc(2 * math.pi * self.PLL_HZ / self.ch_rate,
                                                  2 * math.pi * 60.0 / self.ch_rate,
                                                  -2 * math.pi * 60.0 / self.ch_rate)
        c(self.src, self.xlate, self.dec2, self.rot, self.if_filter, self.pll)

        # ---------------- demod ----------------
        self.mag = blocks.complex_to_mag(1)
        self.car = filter.single_pole_iir_filter_ff(1 - math.exp(-1 / (0.25 * self.ch_rate)))
        self.norm = blocks.divide_ff(1)                 # envelope / carrier = 1 + L + R
        self.car_floor = blocks.add_const_ff(1e-9)      # never 0/0: one NaN would poison every filter after it
        self.sum0 = blocks.add_const_ff(-1.0)           # L + R
        c(self.pll, self.mag)
        c(self.mag, self.car)
        c(self.mag, (self.norm, 0))
        c(self.car, self.car_floor, (self.norm, 1))
        c(self.norm, self.sum0)
        # L+R gets exactly the same high-pass as L-R (two first-order at 60 Hz),
        # so the two paths stay in phase and the stereo separation holds
        self.sum_lp = filter.single_pole_iir_filter_ff(self._a(60.0))
        self.sum_hp1 = blocks.sub_ff(1)
        self.sum_lp2 = filter.single_pole_iir_filter_ff(self._a(60.0))
        self.sum_hp = blocks.sub_ff(1)
        c(self.sum0, (self.sum_hp1, 0))
        c(self.sum0, self.sum_lp, (self.sum_hp1, 1))
        c(self.sum_hp1, (self.sum_hp, 0))
        c(self.sum_hp1, self.sum_lp2, (self.sum_hp, 1))

        # ---------------- PMDS ----------------
        # The PLL leaves the carrier on the real axis, so the data is its phase.
        # Low-pass to 500 Hz (187.5 bit/s data is within about +/-400 Hz) and decimate by 8.
        ta = firdes.low_pass(1.0, self.ch_rate, 500.0, 300.0, W)
        self.pmds_lp = filter.fir_filter_ccf(self.ch_rate // self.PMDS_FS, ta)
        self.pmds = [PmdsDecoder(self.PMDS_FS, r) for r in self.PMDS_RATES]
        c(self.pll, self.pmds_lp)
        for d in self.pmds:
            c(self.pmds_lp, d)

        # ---------------- audio back end ----------------
        self._out_gain, self._muted = (1.0, 1.0), False
        ab = self._a(self.TONE_BASS_HZ)
        at = self._a(self.TONE_TREBLE_HZ)
        hr = 10 ** (-self._tone_atten_db(0, 0) / 20)
        self.audio_sink = self._make_audio_sink(audio_device)
        for idx, (ch, src) in enumerate((("l", self.sum_hp), ("r", self.sum_hp))):
            lp = filter.fir_filter_fff(1, self._lp_taps(self.bw))
            vol = blocks.multiply_const_ff(0.5 * self.AM_AUDIO_GAIN)
            nrsc = filter.iir_filter_ffd([1.0, 0.0], [1.0, 0.0], False)   # NRSC de-emphasis, off until set
            setattr(self, f"alp_{ch}", lp)
            setattr(self, f"nrsc_{ch}", nrsc)
            setattr(self, f"vol_{ch}", vol)
            setattr(self, f"tone_bass_lp_{ch}", filter.single_pole_iir_filter_ff(ab))
            setattr(self, f"tone_bass_k_{ch}", blocks.multiply_const_ff(0.0))
            setattr(self, f"tone_tre_lp_{ch}", filter.single_pole_iir_filter_ff(at))
            setattr(self, f"tone_tre_hp_{ch}", blocks.sub_ff(1))
            setattr(self, f"tone_tre_k_{ch}", blocks.multiply_const_ff(0.0))
            setattr(self, f"tone_sum_{ch}", blocks.add_ff(1))
            setattr(self, f"headroom_{ch}", blocks.multiply_const_ff(hr))
            g = lambda n: getattr(self, f"{n}_{ch}")
            c(src, lp, nrsc, vol)
            c(vol, (g("tone_sum"), 0))
            c(vol, g("tone_bass_lp"), g("tone_bass_k"), (g("tone_sum"), 1))
            c(vol, (g("tone_tre_hp"), 0))
            c(vol, g("tone_tre_lp"), (g("tone_tre_hp"), 1))
            c(g("tone_tre_hp"), g("tone_tre_k"), (g("tone_sum"), 2))
            c(g("tone_sum"), g("headroom"), (self.audio_sink, idx))

        # ---------------- measurements ----------------
        self._win = self.ch_rate // 50                    # 20 ms
        self.car_int = blocks.integrate_cc(self._win)     # coherent carrier
        self.car_mag = blocks.complex_to_mag_squared(1)
        self.car_probe = blocks.probe_signal_f()
        c(self.rot, self.car_int, self.car_mag, self.car_probe)
        self.CH_N = 4096
        self.snap_ch_vec = blocks.stream_to_vector(gr.sizeof_gr_complex, self.CH_N)
        self.snap_ch = blocks.probe_signal_vc(self.CH_N)
        c(self.rot, self.snap_ch_vec, self.snap_ch)
        self.snap_pll_vec = blocks.stream_to_vector(gr.sizeof_gr_complex, 2048)
        self.snap_pll_keep = blocks.keep_one_in_n(gr.sizeof_gr_complex * 2048, 2)
        self.snap_pll = blocks.probe_signal_vc(2048)
        c(self.pll, self.snap_pll_vec, self.snap_pll_keep, self.snap_pll)
        self.snap_aud_vec = blocks.stream_to_vector(gr.sizeof_float, 4096)
        self.snap_aud = blocks.probe_signal_vf(4096)
        c(self.sum_hp, self.snap_aud_vec, self.snap_aud)
        self.WB_N = 4096
        self.snap_wb_vec = blocks.stream_to_vector(gr.sizeof_gr_complex, self.WB_N)
        self.snap_wb_keep = blocks.keep_one_in_n(gr.sizeof_gr_complex * self.WB_N,
                                                 max(1, int(self.samp_rate / self.WB_N / 4)))
        self.snap_wb = blocks.probe_signal_vc(self.WB_N)
        c(self.src, self.snap_wb_vec, self.snap_wb_keep, self.snap_wb)

        # ---------------- monitoring taps (read only, see rx_meters.py) ----------------
        # Audio ahead of volume / tone (0 dBFS = 100% modulation, mono), and the
        # envelope over the carrier minus 1 (x100 = percent modulation).
        self.audio_meter = self.mod_meter = None
        if rx_meters is not None:
            kb1, ka1, kb2, ka2 = rx_meters.k_weighting(self.audio_rate)
            self.audio_meter = rx_meters.AudioMeterBlock(self.audio_rate, ref=1.0)
            for idx, ch in enumerate(("l", "r")):
                k1 = filter.iir_filter_ffd(kb1, ka1, False)
                k2 = filter.iir_filter_ffd(kb2, ka2, False)
                setattr(self, f"kw1_{ch}", k1)
                setattr(self, f"kw2_{ch}", k2)
                lp = getattr(self, f"nrsc_{ch}")              # after de-emphasis: what you hear
                c(lp, (self.audio_meter, idx))
                c(lp, k1, k2, (self.audio_meter, idx + 2))
            self.mod_meter = rx_meters.ModMeterBlock(scale=100.0, over_pos=125.0, over_neg=100.0)
            c(self.sum0, self.mod_meter)

        # ---------------- state ----------------
        self.if_mode = 'auto'
        self.IF_WIDE_KHZ = self.AM_WIDE_HZ / 1e3
        self.if_khz = self.bw / 1e3
        self.cnr_db = self.raw_cnr_db = self.pre_cnr_db = 0.0
        self.spec_snr_db, self.if_snr_db, self.occupied_khz = None, None, None
        self.adj_db = -60.0
        self.carrier_hz = 0.0
        self.channel_dbfs, self.composite_dbfs, self.clip_pct = -100.0, -100.0, 0.0
        self.pilot_level, self.pilot_ratio_db = 0.0, -99.0
        self.pilot_on, self.stereo_indicator = False, False
        self.wide, self.force_mono = False, False
        self.stereo_mode, self.stereo_system, self.pilot_hz = 'mono', 'none', 0   # no AM stereo here
        self.auto_ceiling = self.AM_WIDE_HZ           # auto never opens wider than this
        self.current_blend, self.current_treble = 0.0, 1.0
        self.locked = False
        # FM-only things the GUI asks about
        self.rds_ps, self.rds_rt, self.rds_pi, self.rds_call, self.rds_pty = '', '', None, None, None
        self.rds_synced = False
        self.rds_tp = self.rds_ta = self.rds_ms = self.rds_ct = self.rds_ptyn = None
        self.rds_af = []
        self.rds_rate, self.rds_bler = 0.0, 0.0
        self.pmds_bit_rate, self.pmds_dev_deg, self.pmds_snr_db, self.pmds_fixed = None, 0.0, 0.0, 0.0
        self.pmds_cn_db = None                 # C/N as the data sees it (in-band), from the data SNR
        self.pmds_format = None
        self.pmds_alert, self.pmds_alert_t, self.pmds_facility_id, self.pmds_isrc = 0, None, None, None
        self.pmds_artist = self.pmds_title = None
        self.rds_af, self.rds_ct = [], None
        self.pmds_alert, self.pmds_alert_tier = 0, 0
        self.eq_mode, self.eq_active, self.eq_cnr_db, self.eq_gain_db = 'off', False, 0.0, 0.0
        self.eq_gate, self.mp_excess_db = False, 0.0
        self._rot_hz = 0.0
        self._n0_hz = None
        self._psd = None
        self._last_car = None
        self._last_wb = None
        self._last_ch = None
        self._cnr_slow = None
        self._tune_cnr = []
        self._blank_until = time.monotonic() + self.TUNE_SETTLE_S
        self._wb_seen = time.monotonic()
        self._t_last = time.monotonic()
        self._bw_cur = self.bw
        fr = np.fft.fftshift(np.fft.fftfreq(self.CH_N, 1 / self.ch_rate))
        self._fr = fr
        self._hann = np.hanning(self.CH_N)
        self._hann_wp = float(np.sum(self._hann ** 2))
        self._wbw = np.hanning(self.WB_N)
        self._wbw_wp = float(np.sum(self._wbw ** 2))
        self._apply_gain()

    # ------------------------------------------------------------------ helpers
    def _a(self, hz):
        return 1 - math.exp(-2 * math.pi * hz / self.ch_rate)

    def _lo(self, f):
        lo = f + self.LO_OFFSET
        return lo + self.UPCONVERTER_HZ if self.am_source == 'upconverter' else lo

    def _lp_taps(self, hz):
        """Windowed-sinc low-pass, fixed length (fixed delay) so it can slide."""
        n, m = self.IF_TAPS, (self.IF_TAPS - 1) // 2
        fc = min(hz + 300.0, 0.45 * self.ch_rate) / self.ch_rate
        h = 2 * fc * np.sinc(2 * fc * (np.arange(n) - m)) * np.kaiser(n, 6.0)
        return [float(v) for v in h / np.sum(h)]

    def _tone_atten_db(self, bass_db, treble_db):
        r = self.TONE_RANGE_DB
        return max(0.0, min(bass_db, r), min(treble_db, r)) + self.TONE_SAFETY_DB

    def _apply_gain(self):
        gl, gr_ = (0.0, 0.0) if self._muted else self._out_gain
        k = 0.5 * self.AM_AUDIO_GAIN
        self.vol_l.set_k(k * gl)
        self.vol_r.set_k(k * gr_)

    def _apply_bw(self, hz):
        self.bw = hz
        self.if_khz = hz / 1e3
        self.current_treble = hz / self.AM_WIDE_HZ
        self.if_filter.set_taps(self._lp_taps(hz))
        taps = self._lp_taps(hz)
        self.alp_l.set_taps(taps)
        self.alp_r.set_taps(taps)

    # --------------------------------------------------------------- controls
    def set_freq(self, freq):
        with self._lock:
            self.freq = freq
            self.src.set_center_freq(self._lo(freq), 0)
            self._rot_hz = 0.0
            self.rot.set_phase_inc(0.0)
            self._psd, self._cnr_slow = None, None
            self._tune_cnr = []
            for d in self.pmds:
                d.reset()
            self._pmds_clear()
            self._blank_until = time.monotonic() + self.TUNE_SETTLE_S

    def set_output_gain(self, left, right):
        with self._lock:
            self._out_gain = (max(0.0, float(left)), max(0.0, float(right)))
            self._apply_gain()

    def set_mute(self, muted):
        with self._lock:
            self._muted = bool(muted)
            self._apply_gain()

    def set_tone(self, bass_db, treble_db):
        r = self.TONE_RANGE_DB
        gb = 10 ** (min(max(bass_db, -r), r) / 20)
        gt = 10 ** (min(max(treble_db, -r), r) / 20)
        fb = self.TONE_BASS_HZ / (gb if gb < 1 else 1.0)
        ft = self.TONE_TREBLE_HZ * (gt if gt < 1 else 1.0)
        hr = 10 ** (-self._tone_atten_db(bass_db, treble_db) / 20)
        for ch in ("l", "r"):
            getattr(self, f"tone_bass_lp_{ch}").set_taps(self._a(fb))
            getattr(self, f"tone_bass_k_{ch}").set_k(gb - 1)
            getattr(self, f"tone_tre_lp_{ch}").set_taps(self._a(ft))
            getattr(self, f"tone_tre_k_{ch}").set_k(gt - 1)
            getattr(self, f"headroom_{ch}").set_k(hr)

    def set_wide(self, on):
        """Wide: the filter fixed at 10.2 kHz, everything an NRSC-1 station sends.
        Off: back to the chosen IF mode (auto narrows on noise and neighbours)."""
        with self._lock:
            self.wide = bool(on)
            if self.wide:
                self._bw_cur = self.AM_XWIDE_HZ
                self._apply_bw(self.AM_XWIDE_HZ)
            else:
                hz = {'wide': self.AM_WIDE_HZ, 'narrow': self.AM_NARROW_HZ}.get(
                    self.if_mode, min(self._bw_cur, self.auto_ceiling))
                self._bw_cur = hz
                self._apply_bw(hz)

    def set_auto_ceiling(self, hz):
        """The widest the auto filter will open (normal width)."""
        with self._lock:
            self.auto_ceiling = float(min(max(hz, self.AM_MIN_HZ), self.AM_WIDE_HZ))
            if not self.wide and self.if_mode == 'auto' and self._bw_cur > self.auto_ceiling:
                self._bw_cur = self.auto_ceiling
                self._apply_bw(self.auto_ceiling)

    # AM stereo controls: accepted, nothing to do (mono receiver)
    def set_stereo_system(self, mode):
        pass

    def set_force_mono(self, on):
        self.force_mono = bool(on)

    def set_if_mode(self, mode):
        if mode in ('auto', 'wide', 'narrow'):
            with self._lock:
                self.if_mode = mode
                if self.wide:                           # Wide overrides until it's switched off
                    return
                if mode == 'wide':
                    self._bw_cur = self.AM_WIDE_HZ
                    self._apply_bw(self.AM_WIDE_HZ)
                elif mode == 'narrow':
                    self._bw_cur = self.AM_NARROW_HZ
                    self._apply_bw(self.AM_NARROW_HZ)

    def set_manual_gain(self, db):
        self.gain_db = float(db)
        if self.am_source != 'direct_q':
            self.src.set_gain_mode(False, 0)
            self.src.set_gain(self.gain_db, 0)

    def set_agc(self, on):
        self.agc_enabled = bool(on)
        if self.am_source != 'direct_q':
            self.src.set_gain_mode(bool(on), 0)

    # FM-only controls: accepted, nothing to do on AM
    def set_enhancements(self, blend=None, hicut=None):
        pass

    def set_eq_mode(self, mode):
        pass

    def set_noise_blanker(self, on):
        pass

    def set_dip_hicut(self, on):
        pass

    def set_noise_reduction(self, on):
        pass

    def eq_reset(self):
        pass

    def cnr_since_tune(self):
        with self._lock:
            return list(self._tune_cnr)

    NRSC_POLE_HZ, NRSC_ZERO_HZ = 2122.0, 8700.0      # NRSC-1-C receiver de-emphasis

    def set_nrsc_deemphasis(self, on):
        """NRSC-1 modified 75 us de-emphasis: a pole at 2122 Hz and a zero at
        8700 Hz, the complement of the AM pre-emphasis most US stations transmit
        (-10 dB at 10 kHz). Matched-z at the audio rate, which lands within
        0.04 dB of NRSC-1-C Table 2 from 50 Hz to 10 kHz. Off = flat."""
        self.nrsc_on = bool(on)
        if self.nrsc_on:
            fs = float(self.audio_rate)
            p = math.exp(-2 * math.pi * self.NRSC_POLE_HZ / fs)
            z = math.exp(-2 * math.pi * self.NRSC_ZERO_HZ / fs)
            g = (1 - p) / (1 - z)                        # unity at low frequencies
            b, a = [g, -g * z], [1.0, -p]
        else:
            b, a = [1.0, 0.0], [1.0, 0.0]
        for ch in ("l", "r"):
            getattr(self, f"nrsc_{ch}").set_taps(b, a)

    def audio_lag(self):
        """How far the sound card trails what this receiver measures, in seconds:
        (meters, front end), from the samples queued between the audio low-pass
        (the meter tap) or the channel translator and the audio sink."""
        try:
            played = self.audio_sink.nitems_read(0)
            tap = self.nrsc_l.nitems_written(0) * self.audio_rate / self.ch_rate
            front = self.xlate.nitems_written(0) * self.audio_rate / (self.samp_rate / 10.0)
        except Exception:
            return None
        r = float(self.audio_rate)
        return max(0.0, tap - played) / r, max(0.0, front - played) / r

    def monitor(self):
        """Meter readings since the last call (mod in percent), or None."""
        if self.audio_meter is None:
            return None
        return dict(audio=self.audio_meter.read(), mod=self.mod_meter.read())

    def snapshot(self, kind):
        if kind == 'iq':
            return np.asarray(self.snap_ch.level(), dtype=np.complex64)
        if kind in ('pre', 'post'):
            return np.asarray(self.snap_pll.level(), dtype=np.complex64)
        if kind == 'mpx':
            return np.asarray(self.snap_aud.level(), dtype=np.float32)
        return np.zeros(0, np.complex64)

    def readout(self):
        """ADV text for AM with PMDS."""
        bw = 'wide' if self.bw >= self.AM_WIDE_HZ else f'{self.bw / 1e3:4.1f} kHz'
        src = {'direct_q': 'Q-branch direct sampling', 'native': 'native HF tuning',
               'upconverter': f'upconverter +{self.UPCONVERTER_HZ / 1e6:.0f} MHz'}[self.am_source]
        if self.pmds_bit_rate:
            pi = f"PI {self.rds_pi:04X} {self.rds_call or ''}" if self.rds_pi is not None else 'no PI yet'
            data = (f"PMDS     {'synced' if self.rds_synced else 'lost  '} {self.pmds_format} {self.pmds_bit_rate:g} bit/s  {pi}   "
                    f"data {self.pmds_dev_deg:4.1f} deg  SNR {self.pmds_snr_db:4.1f} dB"
                    f" (C/N {self._fmt_db(self.pmds_cn_db)} in-band)   "
                    f"{self.rds_bler:3.0f}% lost  {self.pmds_fixed:3.0f}% fixed"
                    + ('   ALERT: ' + ('EMERGENCY (PTY 31)' if self.pmds_alert == 2 else 'TEST (PTY 30)')
                       if self.pmds_alert else ''))
        else:
            data = "PMDS     searching (23.4 to 187.5 bit/s, compact and RBDS)"
        return (f"C/N      {self.cnr_db:5.1f} dB in 10 kHz   carrier {self.channel_dbfs:6.1f} dBFS"
                f"{'  (PLL locked)' if self.locked else ''}\n"
                f"IF       {bw:9s} {self.if_mode:6s}  adjacent carriers {self.adj_db:+6.1f} dB"
                f"   carrier offset {self.carrier_hz:+6.1f} Hz\n"
                f"{data}\n"
                f"Clip     {self.clip_pct:6.3f} %   source: {src}")

    # ---------------------------------------------------------------- update
    def update_blend(self):
        """Called every ~20 ms by the GUI: measurements, IF bandwidth, stereo."""
        now = time.monotonic()
        with self._lock:
            dt = min(now - self._t_last, 0.2)
            self._t_last = now

            # stall watchdog (the GUI reconnects on repeated errors)
            wb = self.snap_wb.level()
            if len(wb) == self.WB_N and np.any(np.asarray(wb)):
                if self._last_wb is None or wb[0] != self._last_wb:
                    self._last_wb = wb[0]
                    self._wb_seen = now
                    x = np.asarray(wb)
                    P = np.abs(np.fft.fftshift(np.fft.fft(x * self._wbw))) ** 2 / self._wbw_wp
                    k = self.WB_N // 10
                    # (with |FFT(x w)|^2 / sum(w^2), white noise shows its total power in
                    # every bin: per Hz is that over the whole sample rate)
                    n0 = float(np.percentile(P[k:-k], 30)) / self.samp_rate
                    if n0 > 0 and math.isfinite(n0):
                        self._n0_hz = n0 if self._n0_hz is None else 0.8 * self._n0_hz + 0.2 * n0
                    self.composite_dbfs = 10 * math.log10(max(float(np.mean(np.abs(x) ** 2)), 1e-12))
                    self.clip_pct = 100.0 * float(np.mean((np.abs(x.real) > 0.98) | (np.abs(x.imag) > 0.98)))
            if now - self._wb_seen > self.STALL_S:
                raise RuntimeError(f"no samples from the dongle for {now - self._wb_seen:.1f} s")

            try:
                self._measure(now)
            except Exception as e:                       # never a reason to stop
                if not getattr(self, '_said', False):
                    self._said = True
                    print(f"AM measurement: {type(e).__name__}: {e}")

    def _measure(self, now):
        # carrier-to-noise, 20 ms windows
        cp = self.car_probe.level()
        if cp != self._last_car:
            self._last_car = cp
            C = cp / (self._win * self._win)
            self.channel_dbfs = 10 * math.log10(max(C, 1e-15))
            if self._n0_hz and now >= self._blank_until:
                q = 10 * math.log10(max(C, 1e-20) / (self._n0_hz * 1e4))
                q = min(max(q, -10.0), 80.0)
                self._tune_cnr.append(q)
                if len(self._tune_cnr) > 200:
                    del self._tune_cnr[:100]
                self._cnr_slow = q if self._cnr_slow is None else self._cnr_slow + 0.1 * (q - self._cnr_slow)
                self.cnr_db = self.raw_cnr_db = self.pre_cnr_db = self.spec_snr_db = self._cnr_slow

        # channel spectrum: carrier offset, adjacent carriers
        ch = self.snap_ch.level()
        if len(ch) == self.CH_N and (self._last_ch is None or ch[0] != self._last_ch) \
                and np.any(np.asarray(ch)):
            self._last_ch = ch[0]
            X = np.abs(np.fft.fftshift(np.fft.fft(np.asarray(ch) * self._hann))) ** 2 / self._hann_wp
            self._psd = X if self._psd is None else 0.7 * self._psd + 0.3 * X
            fr, P = self._fr, self._psd
            near = np.where(np.abs(fr) < 400)[0]
            i = near[np.argmax(P[near])]
            if 0 < i < len(P) - 1:                       # parabolic peak
                a, b, c = np.log(P[i - 1] + 1e-30), np.log(P[i] + 1e-30), np.log(P[i + 1] + 1e-30)
                d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
                off = fr[i] + d * (fr[1] - fr[0])
            else:
                off = fr[i]
            self.carrier_hz = off
            own = P[i]
            if now >= self._blank_until and abs(off) > 0.5:  # steer the coarse correction
                self._rot_hz += 0.5 * off
                self.rot.set_phase_inc(-2 * math.pi * self._rot_hz / self.ch_rate)
            adj = []
            for side in (-10e3, 10e3):
                m = np.where(np.abs(fr - side) < 300)[0]
                adj.append(float(np.max(P[m])))
            self.adj_db = 10 * math.log10(max(max(adj), 1e-30) / max(own, 1e-30))
            self.locked = bool(self.pll.lock_detector()) if hasattr(self.pll, 'lock_detector') else True

        # IF bandwidth
        if not self.wide and self.if_mode == 'auto' and self._cnr_slow is not None and now >= self._blank_until:
            tgt = np.interp(self._cnr_slow, [t[0] for t in self.BW_TABLE], [t[1] for t in self.BW_TABLE])
            for lvl, lim in self.ADJ_TABLE:
                if self.adj_db >= lvl:
                    tgt = min(tgt, lim)
            tgt = float(min(max(tgt, self.AM_MIN_HZ), self.auto_ceiling))
            dt = 0.02
            rate = self.BW_SLEW_IN if tgt < self._bw_cur else self.BW_SLEW_OUT
            self._bw_cur += max(-rate * dt, min(rate * dt, tgt - self._bw_cur))
            if abs(self._bw_cur - self.bw) >= self.BW_STEP or \
                    (self._bw_cur >= self.AM_WIDE_HZ) != (self.bw >= self.AM_WIDE_HZ):
                self._apply_bw(self._bw_cur)

        self._pmds_publish()

    # ------------------------------------------------------------------- PMDS
    @staticmethod
    def _fmt_db(v):
        return '  -- dB' if v is None else f"{v:4.1f} dB"

    def _pmds_clear(self):
        self.rds_ps, self.rds_rt, self.rds_pi, self.rds_call, self.rds_pty = '', '', None, None, None
        self.rds_synced, self.rds_tp, self.rds_ta = False, None, None
        self.rds_rate, self.rds_bler = 0.0, 0.0
        self.pmds_bit_rate, self.pmds_dev_deg, self.pmds_snr_db, self.pmds_fixed = None, 0.0, 0.0, 0.0
        self.pmds_cn_db = None                 # C/N as the data sees it (in-band), from the data SNR
        self.pmds_format = None
        self.pmds_alert, self.pmds_alert_t, self.pmds_facility_id, self.pmds_isrc = 0, None, None, None
        self.pmds_artist = self.pmds_title = None
        self.rds_af, self.rds_ct = [], None
        self.pmds_alert, self.pmds_alert_tier = 0, 0

    def pmds_framers(self):
        return [f for d in self.pmds for f in d.framers]

    def set_pmds_strict(self, on):
        """Strict: no error correction, so the block counts show the raw channel."""
        for d in self.pmds:
            d.set_strict(on)

    def pmds_best(self):
        return max(self.pmds_framers(), key=lambda f: (f.synced, f.last_group_t))

    def _pmds_publish(self):
        """The framer that holds sync (or heard a group last) fills in the RDS fields."""
        best = self.pmds_best()
        if best.last_group_t < 0 and not best.synced:
            return
        self.pmds_bit_rate, self.pmds_format = best.bit_rate, best.fmt
        self.rds_synced = best.synced
        self.rds_rate, self.rds_bler, self.pmds_fixed = best.rate(), best.bler(), best.fixed()
        self.pmds_dev_deg, self.pmds_snr_db, self.pmds_cn_db = best.dev_deg(), best.snr_db(), best.cn_db()
        if best.pi is not None:
            if best.pi != self.rds_pi:
                self.rds_pi, self.rds_call = best.pi, pi_to_callsign(best.pi)
            self.rds_ps = best.ps or ''
            self.rds_rt = best.rt or ''
            self.rds_pty, self.rds_tp, self.rds_ta = best.pty, best.tp, best.ta
            self.pmds_alert, self.pmds_alert_t = best.alert or 0, best.alert_t
            self.pmds_facility_id, self.pmds_isrc = best.facility_id, best.isrc
            self.pmds_artist, self.pmds_title = best.artist, best.title
            self.rds_af, self.rds_ct = list(best.af_list), best.clock

    # -------------------------------------------------- hardware (tests replace these)
    def _make_source(self, args):
        return osmosdr.source(args=args)

    def _make_audio_sink(self, device):
        return audio.sink(self.audio_rate, device, True)


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


AMReceiver = PMDSReceiver          # drop-in name for the tuner UI
