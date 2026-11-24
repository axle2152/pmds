#!/usr/bin/env python3
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
EXPERIMENTAL (branch experimental-qpsk): today's BPSK against the two-stream QPSK form,
measured from the reference encoder's own output, no GNU Radio needed.

    python tests/qpsk_measures.py              # about a minute
    python tests/qpsk_measures.py --quick      # the waveform table only

1. The waveform: today's BPSK at 8.6 degrees and at 6.8 (a synchronous detector hears about
   4 dB less of it), QPSK at 187.5 bit/s at 8.6 (the same data power) and 12.2 degrees (the same
   energy per bit as BPSK at 8.6), and half-rate QPSK at 93.75 bit/s at 8.6 degrees:
     where the data's energy sits (the C-QUAM pilot zone is 20 to 30 Hz), the peak phase,
     a synchronous detector perfectly locked (the steady line BPSK makes at 187.5 Hz, and all
     it hears from 60 to 400 Hz, both relative to 100% modulation; all it hears A-weighted,
     relative to BPSK at 8.6), and a mistuned envelope radio, which hears the frequency swing
     (A-weighted, relative to BPSK at 8.6).
2. The weak-signal limit: groups decoded in 2 minutes of steady noise at each C/N.
3. Dropped samples (5 to 300 every 4 to 8 s, as a USB receiver drops them): groups kept.
"""
import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pmds import Encoder, Demodulator  # noqa: E402

FS = 6000
CASES = (('BPSK 93.75 bit/s, 8.6 deg', 'bpsk', 93.75, 8.6),
         ('BPSK 93.75 bit/s, 6.8 deg', 'bpsk', 93.75, 6.8),
         ('QPSK 187.5 bit/s, 8.6 deg', 'qpsk', 187.5, 8.6),
         ('QPSK 187.5 bit/s, 12.2 deg', 'qpsk', 187.5, 12.2),
         ('QPSK low 93.75 bit/s, 8.6', 'qpsk-low', 93.75, 8.6))


def station(mod, rate, dev, secs, fs=FS, rt='Measurement text'):
    e = Encoder(samp_rate=fs, deviation=dev, bit_rate=rate, modulation=mod, call='WAMD', ps='AM 1650',
                rt=rt, rt_file='')
    e.quiet = True
    return e.modulate(np.ones(int(secs * fs), np.complex64))


def psd(x, fs=FS, seg=8192):
    w = np.hanning(seg)
    acc, k = 0, 0
    for i in range(0, len(x) - seg, seg // 2):
        acc = acc + np.abs(np.fft.rfft(w * x[i:i + seg])) ** 2
        k += 1
    return np.fft.rfftfreq(seg, 1 / fs), acc / k


def a_weight(f):
    f2 = np.maximum(f, 1e-3) ** 2
    ra = (12194.0 ** 2 * f2 ** 2 / ((f2 + 20.6 ** 2) * np.sqrt((f2 + 107.7 ** 2) * (f2 + 737.9 ** 2))
                                    * (f2 + 12194.0 ** 2)))
    return ra * 10 ** (2.0 / 20)


def band_power(x, lo, hi, weight=None):
    f, p = psd(x)
    m = (f >= lo) & (f <= hi)
    w = np.ones_like(f) if weight is None else weight(f) ** 2
    return np.sum(p[m] * w[m]) * np.mean(x ** 2) / np.sum(p)


def waveforms():
    print('1. The waveform (90 s of each)')
    print('%-27s %6s %6s %6s %6s %6s  %7s %9s %9s %9s %8s' % (
        '', '<20Hz', '20-30', '30-150', '>150', '>200', 'peak', 'sync line', 'sync AC', 'sync A', 'mistuned'))
    ref = sref = None
    for name, mod, rate, dev in CASES:
        phi = np.angle(station(mod, rate, dev, 90)).astype(np.float64)
        f, p = psd(phi)
        share = lambda lo, hi: 100 * p[(f >= lo) & (f < hi)].sum() / p.sum()
        s = np.cos(phi)
        s -= s.mean()                                   # a synchronous detector, perfectly locked
        f2, p2 = psd(s)
        line = 10 * np.log10(p2.max() / p2.sum() * np.mean(s ** 2) * 2)
        sync = 10 * np.log10(band_power(s, 60, 400) * 2)
        sa = 10 * np.log10(band_power(s, 20, 3000, a_weight) * 2)
        fi = np.gradient(phi) * FS / (2 * np.pi)        # the frequency swing, Hz
        mis = 10 * np.log10(band_power(fi, 20, 3000, a_weight))
        ref = mis if ref is None else ref
        sref = sa if sref is None else sref
        print('%-27s %5.1f%% %5.1f%% %5.1f%% %5.1f%% %5.1f%%  %5.1f°  %6.1f dB  %6.1f dB  %+6.1f dB  %+5.1f dB' % (
            name, share(0, 20), share(20, 30), share(30, 150), share(150, 3000), share(200, 3000),
            np.degrees(np.max(np.abs(phi))), line, sync, sa - sref, mis - ref))
    print('sync line: the strongest single line a synchronous detector hears (BPSK: 187.5 Hz); sync AC: all of it,\n'
          '60 to 400 Hz; sync A: all of it, A-weighted, against BPSK at 8.6; mistuned: what an envelope radio on its\n'
          'filter skirt hears, A-weighted, against BPSK at 8.6.')


def decode(z, mod, rate):
    d = Demodulator(FS, rate, modulation=mod)
    for k in range(0, len(z), 3000):
        d.process(z[k:k + 3000])
    return d


def weak_signal():
    print('\n2. The weak-signal limit: groups decoded in 120 s of steady noise (C/N in 10 kHz)')
    cns = (2, 3, 4, 5, 6, 7, 8, 9, 10)
    print('%-27s %s' % ('', '  '.join('%5d dB' % c for c in cns)))
    for name, mod, rate, dev in CASES:
        y = station(mod, rate, dev, 120)
        sent = 120 * rate / 94
        out = []
        for cn in cns:
            rng = np.random.default_rng(1000 + cn)
            sd = np.sqrt(FS / (10 ** (cn / 10) * 1e4) / 2)
            d = decode(y + sd * (rng.standard_normal(len(y)) + 1j * rng.standard_normal(len(y))), mod, rate)
            out.append(100 * d.compact.groups / sent)
        print('%-27s %s' % (name, '  '.join('%6.0f%%' % v for v in out)))


def dropped_samples():
    print('\n3. Dropped samples, 5 to 300 every 4 to 8 s: groups kept of those sent (300 s)')
    for name, mod, rate, dev in (CASES[0], CASES[2], CASES[4]):
        y = station(mod, rate, dev, 300)
        rng = np.random.default_rng(3)
        parts, i, drops = [], 0, 0
        while i < len(y):
            j = min(len(y), i + int(rng.uniform(4, 8) * FS))
            parts.append(y[i:j])
            i = j + int(rng.integers(5, 300))
            drops += 1
        d = decode(np.concatenate(parts), mod, rate)
        sent = 300 * rate / 94
        print('%-27s %5.1f%%   about %.1f s of groups lost per drop' % (
            name, 100 * d.compact.groups / sent, (sent - d.compact.groups) * 94 / rate / drops))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--quick', action='store_true', help='the waveform table only')
    a = ap.parse_args()
    waveforms()
    if not a.quick:
        weak_signal()
        dropped_samples()


if __name__ == '__main__':
    main()
