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
doesn't multiply what's left). Then the program's leak is taken out: multipath, or another
station's carrier on the channel, turns some of the program's bass into phase, right in the
data's band. The receiver has the program (the envelope), so over a few bits at a time it
finds how much of the envelope and of its slope shows in the phase, and subtracts that. Then
a matched filter for the one-sine-per-bit biphase, bit timing from the phase with the most
matched-filter energy (tracks clock drift between the transmitter and the receiver, either
way), then block sync on the offset words (following bit slips from dropped samples or timing
jumps), single-bit correction where the block type is known, and the group fields, for both
framings (pmds.framer). cn_db() gives the C/N the data sees. set_strict(True) turns the
correction off.

EXPERIMENTAL (branch experimental-qpsk): modulation='qpsk' decodes the two-stream form of
pmds.qpsk instead: two matched filters (the sine and cosine streams of the shaped symbols),
two bits per symbol, bit_rate 187.5 at 93.75 symbols per second. A timing error rotates the
subcarrier and mixes the streams, so the symbol timing comes from the fourth power of the
matched filters' output (z = sine + j cosine stream), which is largest where the four QPSK
points line up: per timing phase, the average of Re(-z^4) / |z|^2. modulation='qpsk-low'
(93.75 bit/s, 46.875 symbols/s, subcarrier 62.5 Hz) is decoded the same way, except that the
subcarrier's phase at a symbol's centre steps by 120 degrees from symbol to symbol: the timing
search then also tries which of the 3 symbols in that cycle it is looking at (a wrong guess
turns the points by 120 degrees, so the z^4 measure rejects it). A wrong place in the cycle
together with a timing error of only a sixteenth of a symbol turns them by exactly 90 degrees,
which z^4 can't see. When the decoder moves between such guesses it works out the turn and undoes
it. After a jump it can't (dropped samples, a deep fade), so three more framer pairs watch the
other three quarter turns: when the main pair has lost sync and one of them finds it, the main
pair is turned to match and finds sync again with its station data kept. Only the main pair is
shown and reported (framers, compact, rbds). modulation='dqpsk-low' is the same waveform
with the bits on the change of phase between symbols: the phase is demodulated against the
subcarrier at absolute time, so every symbol comes out turned by the same unknown amount, which
the change from one symbol to the next cancels. No place in the cycle, no turn, no probes; the
timing comes from the size of the averaged z^4 alone.
"""
import math

import numpy as np

from .framer import CompactFramer, RbdsFramer
from . import qpsk as _qpsk


class Demodulator:
    """Station data from the carrier-locked channel at fs (complex, carrier on the real axis),
    one bit rate per instance, both framings at once. The matched filter's template is
    zero-mean, so a slow phase error left by the carrier PLL barely registers."""

    E_ALPHA   = 1 / 16.0      # timing energy average, per bit
    SWITCH    = 1.15          # another timing phase must beat the current one by this much
    LEVEL_A   = 0.05          # data level / SNR average, per bit
    ENV_FLOOR = None          # normalize by the envelope, not below this share of the carrier (None: by the carrier)
    LOCAL_BITS = 4            # carrier reference averaged over this many bits (0: the slow 1 s average)
    LOCAL_PASSES = 1          # ... that average taken this many times over (QPSK: see __init__)
    CANCEL_BITS = 8           # the program's leak is fitted and removed over this many bits (0: not at all)
    CANCEL_RIDGE = 1e-4       # keeps the fit quiet when there is no program to fit
    CANCEL_FLOOR = 0.05       # a fit that explains less of the phase's power than this share is noise

    def __init__(self, fs=6000, bit_rate=46.875, modulation='bpsk'):
        self.fs, self.bit_rate = float(fs), float(bit_rate)
        self.modulation = str(modulation).lower()
        self.qpsk = _qpsk.is_qpsk(self.modulation)   # experimental: two bits per symbol
        self.sym_rate = _qpsk.symbol_rate(self.modulation, self.bit_rate) if self.qpsk else self.bit_rate
        self._cyc = _qpsk.cycle(self.modulation) if self.qpsk else 1
        self._diff = self.qpsk and _qpsk.is_differential(self.modulation)
        self.spb = int(round(self.fs / self.sym_rate))
        n = self.spb
        self._tmpl = np.sin(2 * np.pi * np.arange(n) / n) / (n / 2.0)   # a clean bit reads +/- its peak phase
        if self._diff:                            # one real matched filter after the subcarrier is taken off
            g = _qpsk.rrc(n)
            self._ti = g / (np.sum(g * g) / (2 * np.sqrt(2)))     # a clean symbol reads +/- the deviation per stream
            self._w = 2 * np.pi * _qpsk.sub_cycles(self.modulation) / n
        elif self.qpsk and self._cyc == 1:        # a clean symbol reads +/- the deviation setting on each stream
            ti, tq = _qpsk.templates(n)
            self._ti, self._tq = ti / np.sum(ti * ti), tq / np.sum(tq * tq)
        elif self.qpsk:
            # One complex matched filter, h = g e^(j w m); the subcarrier's phase at the symbol's
            # centre is applied afterwards (self._rot), per place in the cycle.
            g = _qpsk.rrc(n)
            m = np.arange(-_qpsk.SPAN * n, _qpsk.SPAN * n + 1)
            r = _qpsk.sub_cycles(self.modulation)
            h = g * np.exp(2j * np.pi * r * m / n)
            self._ti = np.conj(h) / (np.sqrt(2) * np.sum(g * g) / 4.0)   # np.correlate conjugates it
            self._rot = np.exp(2j * np.pi * r * (np.arange(self._cyc) + 0.5))
        self._ntap = len(self._ti) - 1 if self.qpsk else n - 1
        if self.qpsk:
            # One 4-symbol average ripples by up to 20% across the data's band, which smears the
            # shaped symbols into each other (a clean signal read only 25.6 dB SNR). Taken three
            # times over, the ripple is below 1% and the reference still follows fading at a few Hz.
            self.LOCAL_PASSES = 3
            # The z^4 timing measure is noisier than BPSK's energy: averaged over 64 symbols
            # instead of 16 it holds on 2 to 3 dB weaker signals, and still follows a 100 ppm clock.
            # 'qpsk-low' symbols are twice as long: 32 of them, the same time.
            self.E_ALPHA = 1 / 64.0 if self._cyc == 1 else 1 / 32.0
        self._reset_req = False
        self.log = None                           # optional log(framer, kind, fields) per group
        nrot = 4 if (self._cyc > 1 and not self._diff) else 1    # 'qpsk-low': the main pair and three probes
        self._compacts = [CompactFramer(self) for _ in range(nrot)]
        self._rbdses = [RbdsFramer(self) for _ in range(nrot)]
        self._all = tuple(self._compacts + self._rbdses)
        self.framers = (self._compacts[0], self._rbdses[0])
        self._clear()

    def reset(self):
        """Forget everything (retune). Safe from any thread: done at the next work()."""
        self._reset_req = True

    def set_strict(self, on):
        for f in self._all:
            f.strict = bool(on)

    def _clear(self):
        self._reset_req = False
        self._hist = np.zeros(self._ntap)
        self._rows = np.zeros(0, np.complex128 if self.qpsk else np.float64)
        self._c = None                            # slow carrier phasor (what the PLL leaves)
        self._L = max(2, int(self.LOCAL_BITS or 1) * self.spb)
        self._zh = np.zeros(self._L, np.complex128)
        box = np.ones(self._L) / self._L                     # the average, taken LOCAL_PASSES times over
        self._kern = box
        for _ in range(max(1, int(self.LOCAL_PASSES)) - 1):
            self._kern = np.convolve(self._kern, box)
        if len(self._kern) > self._L:
            self._zh = np.zeros(len(self._kern), np.complex128)
        self._W = max(2, int(self.CANCEL_BITS or 1) * self.spb)
        self._eh = np.ones(self._W + 1)           # envelope and phase, the last W samples
        self._th_h = np.zeros(self._W)
        self._E = np.zeros(self.spb)              # matched-filter energy at each timing phase (QPSK: the z^4 measure)
        self._best, self._n, self._last = 0, 0, -10 ** 9
        if self._diff:                            # 'dqpsk-low': complex timing measure, the symbol before
            self._E, self._best, self._zprev, self._thn = np.zeros(self.spb, np.complex128), 0, None, 0
            self._hu = np.zeros(self._ntap, np.complex128)        # the phase with the subcarrier off
        elif self._cyc > 1:                       # 'qpsk-low': per place in the cycle, per timing phase
            self._E, self._best = np.zeros((self._cyc, self.spb)), (0, 0)
            self._turn = 0                        # quarter turns undone before the framers
        self._t = None                                # time of the bit being decided, if any
        self._amp, self._var = 0.0, 1.0
        for f in self._all:
            f.reset()

    # ---- the framer currently worth showing, and its fields ----
    def best(self):
        return max(self.framers, key=lambda f: (f.synced, f.last_group_t))

    compact = property(lambda self: self._compacts[0])             # the compact framer
    rbds = property(lambda self: self._rbdses[0])                  # the RBDS-native framer

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
            if len(self._kern) > L:                              # several passes: one longer filter
                K = len(self._kern)
                ref = np.convolve(zz, self._kern, 'valid')[:m]   # the K samples before ...
                zd = zz[K // 2:K // 2 + m]                       # ... centred on this one
                self._zh = zz[len(zz) - K:]
            else:
                cs = np.concatenate(([0j], np.cumsum(zz)))
                ref = (cs[L:L + m] - cs[:m]) / L                 # mean of the L samples before ...
                zd = zz[L // 2:L // 2 + m]                       # ... centred on this one
                self._zh = zz[len(zz) - L:]
            u = zd * np.conj(ref) / np.maximum(np.abs(ref) ** 2, 1e-6 * abs(self._c) ** 2)
            th = u.imag                                          # the phase; u.real is the envelope
            if self.CANCEL_BITS:
                th = self._cancel(u.real, th)
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
        self._hist = buf[len(buf) - self._ntap:]
        if self._diff:                                # 'dqpsk-low': the subcarrier off at absolute time
            nn = self._thn + np.arange(len(th))
            self._thn += len(th)
            buf = np.concatenate((self._hu, th * np.exp(1j * self._w * nn)))
            self._hu = buf[len(buf) - self._ntap:]
            rows = np.concatenate((self._rows, np.correlate(buf, self._ti, 'valid')))
            nrows = len(rows) // self.spb
            self._diff_rows(rows, nrows)
            self._t = None
            self._n += nrows * self.spb
            self._rows = rows[nrows * self.spb:]
            return m
        if self.qpsk and self._cyc > 1:               # 'qpsk-low': the complex matched filter
            mf = np.correlate(buf, self._ti, 'valid')
            rows = np.concatenate((self._rows, mf))
            nrows = len(rows) // self.spb
            self._cycle_rows(rows, nrows)
            self._t = None
            self._n += nrows * self.spb
            self._rows = rows[nrows * self.spb:]
            return m
        if self.qpsk:                                 # symbol ending SPAN symbols after each sample
            mf = np.correlate(buf, self._ti, 'valid') + 1j * np.correlate(buf, self._tq, 'valid')
            take = self._sym
        else:
            mf = np.correlate(buf, self._tmpl, 'valid')                      # bit ending at each sample
            take = self._bit
        rows = np.concatenate((self._rows, mf))
        spb, half, E = self.spb, self.spb // 2, self._E
        nrows = len(rows) // spb
        for r in range(nrows):                        # one bit (QPSK: symbol) period at a time
            row = rows[r * spb:(r + 1) * spb]
            n0 = self._n + r * spb
            b = self._best
            if n0 + b - self._last >= half:           # never two bits closer than half a bit, so a
                self._last = n0 + b                   # timing change across the wrap can't add one
                self._t = (n0 + b) / self.fs
                take(row[b])
            if self.qpsk:
                z2 = row * row                        # where the four points line up, -z^4 is real
                E += self.E_ALPHA * (np.real(-z2 * z2) / (np.abs(z2) + 1e-30) - E)
            else:
                E += self.E_ALPHA * (row * row - E)
            k = int(np.argmax(E))
            if E[k] > self.SWITCH * E[b]:
                self._best = k
                if n0 + k - self._last >= spb - half // 2:
                    # the timing moved back across the wrap (a transmitter clock a little fast):
                    # the new phase is a whole bit past the last decision, and that bit ends in
                    # this row. Take it now, or it would be dropped and the blocks would slip.
                    self._last = n0 + k
                    self._t = (n0 + k) / self.fs
                    take(row[k])
        self._t = None
        self._n += nrows * spb
        self._rows = rows[nrows * spb:]
        return m

    def _cancel(self, env, th):
        """Take the program's leak out of the phase. Over a window of CANCEL_BITS bits centred
        on each sample, fit the phase by least squares to the envelope and to the envelope's
        slope (a leak that depends on frequency, as two paths make it, shows as slope), and
        subtract the fit. With no leak the fit still explains a few percent of the phase's
        power, by chance, and subtracting that only adds noise (it cost 4% of groups at 3 dB
        C/N). So a fit that explains less than CANCEL_FLOOR of the power is not used at all,
        and one that explains twice that or more is used in full.
        Costs CANCEL_BITS / 2 bits of delay."""
        W, m = self._W, len(th)
        e = np.concatenate((self._eh, env))
        t = np.concatenate((self._th_h, th))
        self._eh, self._th_h = e[len(e) - (W + 1):], t[len(t) - W:]
        d = np.diff(e) * (self.fs / 600.0)                # the slope, scaled to match e near 100 Hz
        e = e[1:]

        def mean(x):                                      # window i covers samples i .. i + W - 1
            cs = np.concatenate(([0.0], np.cumsum(x)))
            return (cs[W:W + m] - cs[:m]) / W
        me, md, mt = mean(e), mean(d), mean(t)
        see = mean(e * e) - me * me + self.CANCEL_RIDGE
        sdd = mean(d * d) - md * md + self.CANCEL_RIDGE
        sed = mean(e * d) - me * md
        set_, sdt = mean(e * t) - me * mt, mean(d * t) - md * mt
        det = see * sdd - sed * sed
        k1, k2 = (set_ * sdd - sdt * sed) / det, (sdt * see - set_ * sed) / det
        told = k1 * set_ + k2 * sdt                       # how much of the phase's power the fit explains
        share = told / np.maximum(mean(t * t) - mt * mt, 1e-30)
        keep = np.clip(share / self.CANCEL_FLOOR - 1.0, 0.0, 1.0)   # none below the floor, all from twice it
        c = W // 2                                        # the sample in the middle of each window
        return t[c:c + m] - keep * (k1 * (e[c:c + m] - me) + k2 * (d[c:c + m] - md))

    def _bit(self, v):
        a = abs(v)
        self._amp += self.LEVEL_A * (a - self._amp)
        self._var += self.LEVEL_A * ((a - self._amp) ** 2 - self._var)
        bit = 1 if v > 0 else 0
        for f in self.framers:
            f.push(bit)
            f.alert_tick()

    def _sym(self, z):
        """QPSK: one symbol, the sine stream's bit first, then the cosine stream's."""
        for v in (z.real, z.imag):
            self._bit(v)

    def _cycle_rows(self, rows, nrows):
        """'qpsk-low': the timing loop of process(), with the place in the 3-symbol cycle as a
        second unknown. Row R (samples R*spb ..) holds, for the guess (c, t), a symbol centred
        at sample t whose place in the cycle is (R - c) mod 3."""
        spb, half, E, L = self.spb, self.spb // 2, self._E, self._cyc
        cs = np.arange(L)

        r_sub = _qpsk.sub_cycles(self.modulation)

        def sym(row, R, c, t):                    # mf turned by the subcarrier's phase: I + jQ
            return 1j * np.conj(row[t] * self._rot[(R - c) % L]) * self._TURNS[self._turn]

        def rho(n, c):
            # how far guess (c, n mod spb) turns the points; the same at every symbol it decides
            return 2 * np.pi * (((r_sub * n / spb) % 1.0) - r_sub * ((((n // spb) - c) % L) + 0.5))
        for r in range(nrows):
            row = rows[r * spb:(r + 1) * spb]
            n0 = self._n + r * spb
            R = n0 // spb
            c, t = self._best
            if n0 + t - self._last >= half:
                self._last = n0 + t
                self._t = (n0 + t) / self.fs
                self._sym4(sym(row, R, c, t))
            zc = row[None, :] * self._rot[(R - cs) % L][:, None]
            z2 = zc * zc                          # Re(-z^4) is the same for z and j conj(z)
            E += self.E_ALPHA * (np.real(-z2 * z2) / (np.abs(z2) + 1e-30) - E)
            kc, kt = (int(i) for i in np.unravel_index(int(np.argmax(E)), E.shape))
            if E[kc, kt] > self.SWITCH * E[c, t]:
                # Another guess may see the same points turned by a quarter turn or more: undo it,
                # so the framers keep a continuous stream instead of having to find sync again.
                d = rho(n0 + kt, kc) - rho(n0 + t, c)
                q = int(round(np.angle(np.exp(1j * d)) / (np.pi / 2))) % 4
                self._turn = (self._turn - q) % 4
                self._best = (kc, kt)
                if n0 + kt - self._last >= spb - half // 2:
                    self._last = n0 + kt          # across the wrap, as in process()
                    self._t = (n0 + kt) / self.fs
                    self._sym4(sym(row, R, kc, kt))

    _TURNS = (1, 1j, -1, -1j)

    def _sym4(self, z):
        """'qpsk-low': one symbol (already turned by self._turn) to the main framer pair, and
        turned by a further 90, 180 and 270 degrees to the three probe pairs. When a probe holds
        sync and has decoded a group more recently than the main pair (or the main pair has lost
        sync), the main pair takes that probe's turn from now on."""
        for v in (z.real, z.imag):
            a = abs(v)
            self._amp += self.LEVEL_A * (a - self._amp)
            self._var += self.LEVEL_A * ((a - self._amp) ** 2 - self._var)
        for q, turn in enumerate(self._TURNS):
            w = z * turn
            for bit in (1 if w.real > 0 else 0, 1 if w.imag > 0 else 0):
                for f in (self._compacts[q], self._rbdses[q]):
                    f.push(bit)
                    f.alert_tick()
        main = max(self._compacts[0].last_group_t, self._rbdses[0].last_group_t)
        lost = not (self._compacts[0].synced or self._rbdses[0].synced)
        for q in (1, 2, 3):
            probe = (self._compacts[q], self._rbdses[q])
            if any(f.synced for f in probe) and (lost or max(f.last_group_t for f in probe) > main):
                self._turn = (self._turn + q) % 4         # a probe hears groups the main pair doesn't
                for f in self._compacts[1:] + self._rbdses[1:]:
                    f.reset()
                break

    def _diff_rows(self, rows, nrows):
        """'dqpsk-low': the timing loop of process() on the complex matched-filter output. Every
        symbol is turned by the same unknown amount, so the timing measure is the size of the
        averaged z^4 (large where the four points line up, whatever their turn)."""
        spb, half, E = self.spb, self.spb // 2, self._E
        for r in range(nrows):
            row = rows[r * spb:(r + 1) * spb]
            n0 = self._n + r * spb
            b = self._best
            if n0 + b - self._last >= half:
                self._last = n0 + b
                self._t = (n0 + b) / self.fs
                self._dsym(row[b], E[b])
            z2 = row * row
            E += self.E_ALPHA * (z2 * z2 / (np.abs(z2) + 1e-30) - E)
            mag = np.abs(E)
            k = int(np.argmax(mag))
            if mag[k] > self.SWITCH * mag[b]:
                self._best = k
                if n0 + k - self._last >= spb - half // 2:
                    self._last = n0 + k           # across the wrap, as in process()
                    self._t = (n0 + k) / self.fs
                    self._dsym(row[k], E[k])

    def _dsym(self, z, e4):
        """'dqpsk-low': one symbol. The averaged z^4 (e4) gives the turn all symbols share, to
        a quarter turn: the symbol is decided against that, and its two bits are the change in
        quarter turns from the symbol before (so the unknown quarter turn cancels). Deciding each
        symbol against the steady average, not against the noisy symbol before, keeps the cost of
        the differential coding to about one bad symbol spoiling two decisions."""
        a = abs(z) / np.sqrt(2)
        self._amp += self.LEVEL_A * (a - self._amp)
        self._var += self.LEVEL_A * ((a - self._amp) ** 2 - self._var)
        theta = (np.angle(e4) - np.pi) / 4                # where the points sit, to a quarter turn
        q = int(np.floor(np.angle(z * np.exp(-1j * theta)) / (np.pi / 2))) % 4
        if self._zprev is not None:
            for bit in _qpsk.UNGRAY[(self._zprev - q) % 4]:
                for f in self.framers:
                    f.push(bit)
                    f.alert_tick()
        self._zprev = q
