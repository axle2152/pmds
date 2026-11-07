# Copyright 2026 Michael Foley
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
# except in compliance with the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the
# License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific language governing permissions
# and limitations under the License.
"""
PMDS demodulator: bits from the carrier's phase, then both framers, with no GNU Radio dependency.

Input: complex baseband with the carrier locked onto the real axis (a slow, about 1 Hz carrier
PLL ahead of this, then low-passed to about +/-500 Hz and decimated to fs). One Demodulator
per bit rate.

The carrier's phase is measured against a local carrier reference (averaged over the last 4
bits, so fading faster than the 1 Hz PLL can follow is taken out, and the program's own AM
doesn't multiply what's left), then a matched filter for the one-sine-per-bit biphase, bit
timing from the phase with the most matched-filter energy (tracks clock drift between the
transmitter and the receiver), then block sync on the offset words (following bit slips from
dropped samples or timing jumps), single-bit correction where the block type is known, and
the group fields, for both framings (pmds.framer). cn_db() gives the C/N the data sees.
set_strict(True) turns the correction off.
"""
import math

import numpy as np

from .framer import CompactFramer, RbdsFramer


class Demodulator:
    """Station data from the carrier-locked channel at fs (complex, carrier on the real axis),
    one bit rate per instance, both framings at once. The matched filter's template is
    zero-mean, so a slow phase error left by the carrier PLL barely registers."""

    E_ALPHA   = 1 / 16.0      # timing energy average, per bit
    SWITCH    = 1.15          # another timing phase must beat the current one by this much
    LEVEL_A   = 0.05          # data level / SNR average, per bit
    ENV_FLOOR = None          # normalize by the envelope, not below this share of the carrier (None: by the carrier)
    LOCAL_BITS = 4            # carrier reference averaged over this many bits (0: the slow 1 s average)

    def __init__(self, fs=6000, bit_rate=46.875):
        self.fs, self.bit_rate = float(fs), float(bit_rate)
        self.spb = int(round(self.fs / self.bit_rate))
        n = self.spb
        self._tmpl = np.sin(2 * np.pi * np.arange(n) / n) / (n / 2.0)   # a clean bit reads +/- its peak phase
        self._reset_req = False
        self.log = None                           # optional log(framer, kind, fields) per group
        self.compact = CompactFramer(self)
        self.rbds = RbdsFramer(self)
        self.framers = (self.compact, self.rbds)
        self._clear()

    def reset(self):
        """Forget everything (retune). Safe from any thread: done at the next work()."""
        self._reset_req = True

    def set_strict(self, on):
        for f in self.framers:
            f.strict = bool(on)

    def _clear(self):
        self._reset_req = False
        self._hist = np.zeros(self.spb - 1)
        self._rows = np.zeros(0)
        self._c = None                            # slow carrier phasor (what the PLL leaves)
        self._L = max(2, int(self.LOCAL_BITS or 1) * self.spb)
        self._zh = np.zeros(self._L, np.complex128)
        self._E = np.zeros(self.spb)              # matched-filter energy at each timing phase
        self._best, self._n, self._last = 0, 0, -10 ** 9
        self._t = None                                # time of the bit being decided, if any
        self._amp, self._var = 0.0, 1.0
        for f in self.framers:
            f.reset()

    # ---- the framer currently worth showing, and its fields ----
    def best(self):
        return max(self.framers, key=lambda f: (f.synced, f.last_group_t))

    # the best framer's fields, so a decoder reads like one framer
    synced = property(lambda self: self.best().synced)
    pi = property(lambda self: self.best().pi)
    ps = property(lambda self: self.best().ps)
    rt = property(lambda self: self.best().rt)
    pty = property(lambda self: self.best().pty)
    tp = property(lambda self: self.best().tp)
    ta = property(lambda self: self.best().ta)
    alert = property(lambda self: self.best().alert)
    alert_tier = property(lambda self: self.best().alert_tier)
    groups = property(lambda self: self.best().groups)
    last_group_t = property(lambda self: self.best().last_group_t)
    fmt = property(lambda self: self.best().fmt)

    def rate(self):
        return self.best().rate()

    def bler(self):
        return self.best().bler()

    def fixed(self):
        return self.best().fixed()

    def now(self):
        """Seconds of signal so far; while bits are being decided, the time of the bit itself."""
        t = self._t
        return t if t is not None else self._n / self.fs

    def dev_deg(self):
        return math.degrees(self._amp)

    def snr_db(self):
        return 10 * math.log10(max(self._amp ** 2, 1e-12) / max(self._var, 1e-12))

    def cn_db(self):
        """Carrier-to-noise in 10 kHz as the data sees it, worked back from the data SNR:
        noise inside the data's own band counts, a quiet band elsewhere doesn't. The data SNR
        is C/N (10 kHz) + 20 log10(deviation in rad) + 10 log10(10 kHz x bit time), within
        about 0.5 dB in simulation from 6 to 20 dB C/N. None while the deviation is unknown."""
        dev = math.radians(self.dev_deg())
        if dev < math.radians(0.5):
            return None
        return self.snr_db() - 20 * math.log10(dev) - 10 * math.log10(1e4 / self.bit_rate)

    # ---- signal ----
    def process(self, z):
        """Feed the next samples (complex, carrier on the real axis, at fs). Returns how
        many were taken, which is all of them."""
        if self._reset_req:
            self._clear()
        z = np.asarray(z).astype(np.complex128)
        m = len(z)
        if m == 0:
            return 0
        mean = complex(np.mean(z))
        if self._c is None:
            self._c = mean if abs(mean) > 0 else 1.0 + 0j
        self._c += (1 - math.exp(-m / self.fs)) * (mean - self._c)        # about 1 s
        zc = z * np.conj(self._c)
        if self.LOCAL_BITS:
            # the carrier measured locally, over a few whole bits (a bit's phase swing averages
            # out), so fast fading phase the 1 Hz PLL can't follow is taken out here
            L = self._L
            zz = np.concatenate((self._zh, z))
            cs = np.concatenate(([0j], np.cumsum(zz)))
            ref = (cs[L:L + m] - cs[:m]) / L                     # mean of the L samples before ...
            zd = zz[L // 2:L // 2 + m]                           # ... centred on this one
            self._zh = zz[len(zz) - L:]
            th = (zd * np.conj(ref)).imag / np.maximum(np.abs(ref) ** 2, 1e-6 * abs(self._c) ** 2)
        elif self.ENV_FLOOR:
            # the quadrature over the envelope: sin(phase). The program's own AM no longer
            # multiplies whatever phase error the PLL leaves; in a trough the floor keeps it
            # from spinning the way the bare phase angle would.
            ac = abs(self._c)
            th = zc.imag / (np.maximum(np.abs(z), self.ENV_FLOOR * ac) * max(ac, 1e-10))
        else:
            # the quadrature over the carrier: envelope x sin(phase)
            th = zc.imag / max(abs(self._c) ** 2, 1e-20)
        buf = np.concatenate((self._hist, th))
        self._hist = buf[len(buf) - (self.spb - 1):]
        mf = np.correlate(buf, self._tmpl, 'valid')                          # bit ending at each sample
        rows = np.concatenate((self._rows, mf))
        spb, half, E = self.spb, self.spb // 2, self._E
        nrows = len(rows) // spb
        for r in range(nrows):                        # one bit period at a time
            row = rows[r * spb:(r + 1) * spb]
            n0 = self._n + r * spb
            b = self._best
            if n0 + b - self._last >= half:           # never two bits closer than half a bit, so a
                self._last = n0 + b                   # timing change across the wrap can't add one
                self._t = (n0 + b) / self.fs
                self._bit(row[b])
            E += self.E_ALPHA * (row * row - E)
            k = int(np.argmax(E))
            if E[k] > self.SWITCH * E[b]:
                self._best = k
        self._t = None
        self._n += nrows * spb
        self._rows = rows[nrows * spb:]
        return m

    def _bit(self, v):
        a = abs(v)
        self._amp += self.LEVEL_A * (a - self._amp)
        self._var += self.LEVEL_A * ((a - self._amp) ** 2 - self._var)
        bit = 1 if v > 0 else 0
        for f in self.framers:
            f.push(bit)
            f.alert_tick()
