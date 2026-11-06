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
Skywave channel simulator for the PMDS tests (Watterson-style, like HF channel simulators).

Input/output: complex baseband, carrier = 1.0 (put it right after the PMDS encoder, before
any transmit gain). Works at any sample rate (192 kHz in the transmitter, 48 kHz offline).

Each propagation path is (level dB, delay ms, Doppler spread Hz):
  spread 0   : a steady path (groundwave)
  spread > 0 : a fading path, complex Gaussian (Rayleigh) with a Gaussian Doppler spectrum;
               the spread is the two-sided width 2*sigma, as in Watterson / ITU-R F.1487
Path levels are relative; the total is normalised so the mean received carrier power is 1,
which is what cn_db (carrier to noise in 10 kHz) is measured against.

Presets (starting points borrowed from HF practice until real MW recordings calibrate them):
  steady     daytime groundwave                   0 dB / 0 ms / 0 Hz
  mush       groundwave + skywave, equal          0/0/0  +  0 dB / 0.7 ms / 0.6 Hz
  night1     one sky mode, slow fades             0 dB / 0 ms / 0.2 Hz
  night2     two sky modes                        0/0/0.6  +  -2 dB / 1.5 ms / 0.6 Hz
  disturbed  two equal modes, faster              0/0/1.0  +   0 dB / 2.0 ms / 1.0 Hz
  flutter    one mode, twilight flutter           0 dB / 0 ms / 2.0 Hz
  custom     path_db / path_ms / path_spread lists

Transmitter IPM (ipm_deg > 0): incidental phase modulation that follows the program, applied
before propagation as phase = ipm_deg * (envelope - 1) / 0.95, so ipm_deg is the peak phase at
95% modulation (the way transmitter specs quote it). Memoryless: a first approximation of a
transmitter whose tuning turns amplitude into phase. 1 deg is a modern solid-state transmitter,
3 deg a fair older one, 6-10 deg one that badly needs neutralizing.

Noise: cn_db < 99 adds white noise.  enable = 0 passes the signal through untouched.
(For other stations on or near the channel, add real IQ recordings to the flowgraph instead.)
"""
import math

import numpy as np
from gnuradio import gr

PRESETS = {
    'steady':    [(0.0, 0.0, 0.0)],
    'mush':      [(0.0, 0.0, 0.0), (0.0, 0.7, 0.6)],
    'night1':    [(0.0, 0.0, 0.2)],
    'night2':    [(0.0, 0.0, 0.6), (-2.0, 1.5, 0.6)],
    'disturbed': [(0.0, 0.0, 1.0), (0.0, 2.0, 1.0)],
    'flutter':   [(0.0, 0.0, 2.0)],
}


class _Slow:
    """A slowly varying process made at a low rate and linearly interpolated to the
    signal rate. Fixed-size chunks, so the result doesn't depend on work() sizes."""
    CHUNK = 256

    def __init__(self, rate, taps, rng, complex_=True, scale=1.0):
        self.rate, self.taps, self.rng, self.cplx, self.scale = rate, taps, rng, complex_, scale
        self.hist = self._white(len(taps) - 1)
        self.buf = np.zeros(0, np.complex128 if complex_ else np.float64)
        self.base = 0

    def _white(self, m):
        if self.cplx:
            return (self.rng.standard_normal(m) + 1j * self.rng.standard_normal(m)) / math.sqrt(2)
        return self.rng.standard_normal(m)

    def _more(self):
        ext = np.concatenate((self.hist, self._white(self.CHUNK)))
        out = np.convolve(ext, self.taps, 'valid') * self.scale
        self.hist = ext[len(ext) - (len(self.taps) - 1):]
        self.buf = np.concatenate((self.buf, out))

    def at(self, p):
        """Values at low-rate positions p (increasing floats)."""
        need = int(p[-1]) + 2 - self.base
        while len(self.buf) < need:
            self._more()
        i0 = np.floor(p)
        f = p - i0
        i = i0.astype(np.int64) - self.base
        v = self.buf[i] * (1 - f) + self.buf[i + 1] * f
        drop = int(p[0]) - self.base - 1
        if drop > 0:
            self.buf, self.base = self.buf[drop:], self.base + drop
        return v


def _fading(spread_hz, rng, rate=100.0):
    """Unit-power complex fading with a Gaussian Doppler spectrum of width 2*sigma = spread."""
    sig_f = spread_hz / 2.0
    sig_t = 1.0 / (2 * math.sqrt(2) * math.pi * sig_f)     # filter for that power spectrum
    L = max(2, int(4 * sig_t * rate))
    t = np.arange(-L, L + 1) / rate
    h = np.exp(-0.5 * (t / sig_t) ** 2)
    return _Slow(rate, h / math.sqrt(np.sum(h * h)), rng, True)


class blk(gr.sync_block):
    def __init__(self, samp_rate=192000, enable=1, preset='night2',
                 path_db=[0.0], path_ms=[0.0], path_spread=[0.0], cn_db=40.0, ipm_deg=0.0, seed=1):
        gr.sync_block.__init__(self, name='Skywave Channel',
                               in_sig=[np.complex64], out_sig=[np.complex64])
        self.samp_rate = samp_rate
        self.enable = enable
        self.preset = preset
        self.path_db = path_db
        self.path_ms = path_ms
        self.path_spread = path_spread
        self.cn_db = cn_db
        self.ipm_deg = ipm_deg
        self.seed = seed
        self.quiet = False
        self._key = None
        self._n = 0

    # ---- configuration ----
    def paths(self):
        if self.preset in PRESETS:
            return PRESETS[self.preset]
        return [(float(d), float(m), float(s)) for d, m, s in
                zip(self.path_db, self.path_ms, self.path_spread)] or PRESETS['steady']

    def _build(self):
        fs, seed = float(self.samp_rate), int(self.seed)
        paths = self.paths()
        lin = [10 ** (d / 10) for d, _, _ in paths]
        tot = sum(lin)
        self._paths = []
        for i, ((db, ms, spread), p) in enumerate(zip(paths, lin)):
            D = int(round(ms * 1e-3 * fs))
            fad = _fading(spread, np.random.default_rng([seed, i])) if spread > 0 else None
            self._paths.append((math.sqrt(p / tot), D, fad))
        self._maxd = max(D for _, D, _ in self._paths)
        self._hist = np.zeros(self._maxd, np.complex64)
        self._noise = np.random.default_rng([seed, 100])
        self._key = self._config_key()
        if not self.quiet:
            print('Skywave: %s, %s' % (self.preset, ', '.join(
                '%+g dB / %g ms / %g Hz' % p for p in paths)), flush=True)

    def _config_key(self):
        return (self.preset, tuple(self.path_db), tuple(self.path_ms), tuple(self.path_spread),
                int(self.seed), float(self.samp_rate))

    # ---- signal ----
    def work(self, input_items, output_items):
        x, out = input_items[0], output_items[0]
        n = len(x)
        if not int(self.enable):
            out[:] = x
            self._n += n
            return n
        if self._key != self._config_key():
            self._build()
        fs = float(self.samp_rate)
        idx = self._n + np.arange(n)
        ipm = float(self.ipm_deg)
        if ipm:                                        # transmitter: amplitude turned into phase
            x = x * np.exp(1j * math.radians(ipm) / 0.95 * (np.abs(x) - 1.0)).astype(np.complex64)
        ext = np.concatenate((self._hist, x)) if self._maxd else x
        y = np.zeros(n, np.complex128)
        for amp, D, fad in self._paths:
            seg = ext[self._maxd - D:self._maxd - D + n]
            y += amp * seg if fad is None else amp * fad.at(idx * (fad.rate / fs)) * seg
        if self._maxd:
            self._hist = ext[len(ext) - self._maxd:]

        cn = float(self.cn_db)
        if cn < 99:
            sd = math.sqrt(fs / (10 ** (cn / 10) * 1e4) / 2)
            w = self._noise.standard_normal(2 * n)        # one draw per call: same noise for any work() size
            y += sd * (w[0::2] + 1j * w[1::2])
        out[:] = y.astype(np.complex64)
        self._n += n
        return n
