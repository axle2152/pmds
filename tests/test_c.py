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
test_c.py - the C decoder (c/) against the Python one. Needs a C compiler; no GNU Radio.

    python tests/test_c.py

  same bits     the same 6000 Hz signal through pmds.Demodulator and the C decoder gives the
                same bit decisions at the same moments, the same groups and the same station:
                clean, noisy, dropped samples, a 100 ppm clock, a second station taking over
  front end     I/Q at 44100 Hz with the station 12 kHz up and a tuning error: the C front end
                finds the carrier and decodes the station
  tables        the C copies of the character set and the call-letter rules match pmds.codec
  sketch        the Teensy sketch's copy of the decoder is current
"""
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TOP = os.path.dirname(HERE)
C = os.path.join(TOP, 'c')
sys.path.insert(0, TOP)
sys.path.insert(0, C)
from pmds import Encoder, Demodulator, codec  # noqa: E402
import make_test_iq  # noqa: E402

FS = 6000
SRC = ['pmds_framer.c', 'pmds_demod.c', 'pmds_front.c', 'pmds_text.c']
STATION = dict(call='WAMD', ps='AM 1650', rt='Queen - Bohemian Rhapsody (Remastered 2011 Extended Version)',
               facility_id=73977, af='95.5,750')
failed = 0


def check(name, ok, detail=''):
    global failed
    failed += not ok
    print('%s  %-44s %s' % ('ok  ' if ok else 'FAIL', name, detail), flush=True)


def compiler():
    for cc in (os.environ.get('CC'), 'cc', 'gcc', 'clang'):
        if cc and shutil.which(cc):
            return cc
    return None


def build(cc, tmp):
    exe = os.path.join(tmp, 'pmds_decode')
    subprocess.run([cc, '-std=c99', '-O2', '-Wall', '-Wextra', '-pedantic', '-Werror', '-o', exe,
                    os.path.join(C, 'tools', 'pmds_decode.c')] + [os.path.join(C, s) for s in SRC] + ['-lm'],
                   check=True)
    return exe


def station(secs, seed, cn_db=None, **kw):
    rng = np.random.default_rng(seed)
    e = Encoder(samp_rate=FS, rt_file='', **dict(STATION, **kw))
    e.quiet = True
    n = int(secs * FS)
    w = np.fft.rfft(rng.standard_normal(n))
    w[np.fft.rfftfreq(n, 1 / FS) > 2500] = 0
    prog = np.fft.irfft(w, n)
    env = np.clip(1 + 0.25 * prog / prog.std(), 0.02, 2.25)
    z = e.modulate(env.astype(np.complex64)).astype(np.complex128)
    if cn_db is not None:
        sd = np.sqrt(FS / (10 ** (cn_db / 10) * 1e4) / 2)
        z += sd * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    return z


def py_decode(z):
    d = Demodulator(FS, 93.75)
    bits, groups = [], []
    orig = d._bit

    def hook(v):
        bits.append((round(d._t * FS), 1 if v > 0 else 0))
        orig(v)
    d._bit = hook
    d.log = lambda fr, kind, f: groups.append((kind, round(fr.now() * FS))) if fr.fmt == 'compact' else None
    for k in range(0, len(z), 1000):
        d.process(z[k:k + 1000])
    return d.compact, bits, groups


def c_decode(exe, tmp, path, args):
    out = subprocess.run([exe] + args + [path], capture_output=True, text=True, check=True).stdout
    bits, groups, s = [], [], {}
    for line in out.splitlines():
        p = line.split()
        if p[0] == 'B':
            bits.append((round(float(p[1]) * FS), int(p[3])))
        elif p[0] == 'G':
            groups.append((p[1], round(float(p[2][2:]) * FS)))
        elif p[0] == 'S':
            k, _, v = line[2:].partition('=')
            s[k] = v
    return bits, groups, s


def same_bits(exe, tmp, name, z):
    path = os.path.join(tmp, 'in.cf64')
    np.column_stack((z.real, z.imag)).astype(np.float64).tofile(path)
    fr, pb, pg = py_decode(z)
    cb, cg, s = c_decode(exe, tmp, path, ['--demod', '--bits', '--groups'])
    shown = (s.get('ps'), s.get('rt'), s.get('pi')) == (fr.ps, fr.rt, '%04X' % fr.pi if fr.pi is not None else None)
    check('same bits: ' + name, pb == cb and pg == cg and shown,
          '%d bits, %d groups%s' % (len(cb), len(cg), '' if shown else ', shown differs'))


def test_same_bits(exe, tmp):
    same_bits(exe, tmp, 'clean', station(40, 1))
    same_bits(exe, tmp, '4 dB C/N, many repairs', station(60, 4, cn_db=4))
    z = station(60, 6, cn_db=15)
    rng = np.random.default_rng(3)
    parts, i = [], 0
    while i < len(z):                                   # drop 5 to 300 samples every 4 to 8 s
        j = min(len(z), i + int(rng.uniform(4, 8) * FS))
        parts.append(z[i:j])
        i = j + int(rng.integers(5, 300))
    same_bits(exe, tmp, 'dropped samples', np.concatenate(parts))
    z = station(240, 7, cn_db=12)
    t = np.arange(int(len(z) / 1.0001) - 1) * 1.0001   # transmitter clock 100 ppm fast
    k = t.astype(int)
    same_bits(exe, tmp, 'clock 100 ppm fast', z[k] * (1 - (t - k)) + z[k + 1] * (t - k))
    a = station(90, 8, cn_db=15)
    b = station(90, 9, cn_db=15, call='KZZZ', ps='OTHER', rt='The other station', facility_id=12345, af='101.1')
    same_bits(exe, tmp, 'second station visits, then takes over',
              np.concatenate((a[:30 * FS], b[1234:1234 + 3 * FS], a[33 * FS:50 * FS], b[50 * FS + 777:])))


def test_front_end(exe, tmp):
    for name, args in (('44100 Hz, strong', dict()), ('44100 Hz, 37 Hz off, 12 dB C/N', dict(offset_hz=37, cn_db=12)),
                       ('44100 Hz, 420 Hz off, 8 dB C/N', dict(offset_hz=-420, cn_db=8))):
        path = os.path.join(tmp, 'in.wav')
        make_test_iq.write_wav(path, make_test_iq.make(60, seed=5, **dict(STATION, **args)))
        _, _, s = c_decode(exe, tmp, path, ['--if', '12000'])
        groups = int(s['groups'])
        ok = s.get('ps') == 'AM 1650 ' and s.get('rt') == STATION['rt'] and groups >= 55
        check('front end: ' + name, ok, '%d of 60 groups, carrier at %s' % (groups, s.get('if_hz', '').split()[0]))


def test_tables(cc, tmp):
    prog = os.path.join(tmp, 'tables.c')
    open(prog, 'w').write('''#include <stdio.h>
#include "pmds.h"
int main(void) { char c[5]; int i; const char *calls[] = {"WAMD","KAAA","KACR","KEOE","WEHS","WSB","KZZZ","KDKA",0};
  for (i = 0x20; i < 0x100; i++) printf("%02X %s\\n", i, pmds_g0_utf8((uint8_t)i));
  for (i = 0; calls[i]; i++) { unsigned pi = pmds_call_to_pi(calls[i]); printf("C %s %04X %s\\n", calls[i], pi, pmds_pi_to_call((uint16_t)pi, c) ? c : "-"); }
  return 0; }''')
    exe = os.path.join(tmp, 'tables')
    subprocess.run([cc, '-std=c99', '-I', C, '-o', exe, prog, os.path.join(C, 'pmds_text.c')], check=True)
    out = subprocess.run([exe], capture_output=True, check=True).stdout.decode('utf-8').splitlines()
    g0_ok = all(line[3:] == (codec.G0[int(line[:2], 16)] or '') for line in out if not line.startswith('C '))
    check('tables: G0 character set', g0_ok)
    calls_ok = True
    for line in out:
        if line.startswith('C '):
            _, call, pi, back = line.split()
            calls_ok &= int(pi, 16) == codec.callsign_to_pi(call) and back == call
    check('tables: call letters to PI and back', calls_ok)


def test_sketch_copy():
    sys.path.insert(0, C)
    import sync_firmware
    stale = sync_firmware.stale()
    check('sketch: firmware/teensy_rx has the current decoder', not stale,
          'run python c/sync_firmware.py' if stale else '')


def main():
    test_sketch_copy()
    cc = compiler()
    if not cc:
        print('No C compiler here (cc, gcc or clang), so the C decoder was not tested.')
        return 1 if failed else 0
    tmp = tempfile.mkdtemp(prefix='pmds_c_')
    try:
        exe = build(cc, tmp)
        test_tables(cc, tmp)
        test_same_bits(exe, tmp)
        test_front_end(exe, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print('\nAll passed.' if not failed else '\n%d failed.' % failed)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
