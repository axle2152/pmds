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
simulate.py - the step 3 front end in ngspice: does it give I and Q at +12 kHz?

    python firmware/hardware/simulate.py          # needs ngspice and numpy

Each case puts a station on the input, runs the circuit on the schematic (the low-pass filter,
T1, the 74HC4052 switching in the 74HCT74's Gray-code order, the 22 nF sampling capacitors,
the MCP6022 buffers and difference amplifiers) and fits the I and Q outputs at 12 kHz. A
station above the oscillator must come out with Q 90 degrees behind I: that is +12 kHz for
I + jQ, where the decoder looks for it. The op-amps are modelled simply (100 dB, 10 MHz, rail
to rail on 5 V) and the switch as 80 ohm on, so this checks the design, not the parts.
"""
import os
import subprocess
import sys
import tempfile

import numpy as np

CASES = [   # what, oscillator Hz, station Hz
    ('1012 kHz, oscillator 12 kHz below', 1.000e6, 1.012e6),
    ('1710 kHz, top of the band', 1.698e6, 1.710e6),
    ('542 kHz, bottom of the band', 0.530e6, 0.542e6),
    ('1602 kHz with the oscillator at 530: the third-harmonic response', 0.530e6, 1.602e6),
    ('5106 kHz shortwave, oscillator at 1698: third harmonic, filtered', 1.698e6, 5.106e6),
]


def deck(flo, frf, amp, out):
    T = 1 / flo
    tr = 2e-9
    deck = f"""* PMDS prototype front end, LO {flo:g} Hz, RF {frf:g} Hz
    .param T={T}
    * op-amp: 100 dB, 10 MHz GBW, rail to rail on 0..5 V (MCP6022-like)
    .subckt oa inp inn out
    Bg n1 0 V = 1e5*(V(inp)-V(inn))
    R1 n1 n2 1k
    C1 n2 0 1.59u
    Bo out 0 V = max(min(V(n2), 4.97), 0.03)
    .ends
    Vcc vcc 0 5
    Vb vbias 0 2.5
    * RF source, 50 ohm
    Vrf rfs 0 SIN(0 {amp} {frf})
    Rs rfs n_in 50
    * 5-pole Butterworth low-pass, 2.2 MHz, 50 ohm
    C1 n_in 0 888p
    L2 n_in n_l 5.6u
    C3 n_l 0 2.92n
    L4 n_l n_t 5.6u
    C5 n_t 0 888p
    * T1: FT37-43, 15 turns bifilar, 1:1
    Lp n_t 0 85u
    Ls n_mx vbias_t 85u
    K1 Lp Ls 0.98
    Cvb vbias_t 0 10u
    Rvb vbias_t vbias 10
    * select lines: S0 = Q1, S1 = Q2 of the Johnson counter (S1 S0 = 00, 01, 11, 10)
    Vs0 s0 0 PULSE(0 1 {T/4} {tr} {tr} {T/2-tr} {T})
    Vs1 s1 0 PULSE(0 1 {T/2} {tr} {tr} {T/2-tr} {T})
    Bc0 c0 0 V = (1-V(s1))*(1-V(s0))
    Bc1 c1 0 V = (1-V(s1))*V(s0)
    Bc2 c2 0 V = V(s1)*(1-V(s0))
    Bc3 c3 0 V = V(s1)*V(s0)
    .model swm sw vt=0.5 vh=0.01 ron=80 roff=1e9
    S0 n_mx x0 c0 0 swm
    S1 n_mx x1 c1 0 swm
    S2 n_mx x2 c2 0 swm
    S3 n_mx x3 c3 0 swm
    * sampling capacitors 22 nF
    Cx0 x0 0 22n
    Cx1 x1 0 22n
    Cx2 x2 0 22n
    Cx3 x3 0 22n
    * stage 1: non-inverting x11, DC gain 1
    """
    for k in range(4):
        deck += f"""Xb{k} x{k} f{k} o{k} oa
    Rf{k} o{k} f{k} 10k
    Cf{k} o{k} f{k} 470p
    Rg{k} f{k} g{k} 1k
    Cg{k} g{k} 0 10u
    """
    deck += """* stage 2: difference amps x4.7 about the bias. I = X0 - X3 (0 and 180 deg), Q = X1 - X2 (90 and 270)
    XdI pI mI outI oa
    R1a o0 pI 10k
    R2a pI vbias 47k
    R1b o3 mI 10k
    R2b mI outI 47k
    C2b mI outI 100p
    XdQ pQ mQ outQ oa
    R1c o2 pQ 10k
    R2c pQ vbias 47k
    R1d o1 mQ 10k
    R2d mQ outQ 47k
    C2d mQ outQ 100p
    * to the Audio Adaptor's line input: 10 uF in series, about 10k load
    CoI outI lI 10u
    RlI lI 0 10k
    CoQ outQ lQ 10u
    RlQ lQ 0 10k
    .ic V(x0)=2.5 V(x1)=2.5 V(x2)=2.5 V(x3)=2.5 V(g0)=2.5 V(g1)=2.5 V(g2)=2.5 V(g3)=2.5 V(o0)=2.5 V(o1)=2.5 V(o2)=2.5 V(o3)=2.5 V(f0)=2.5 V(f1)=2.5 V(f2)=2.5 V(f3)=2.5 V(outI)=2.5 V(outQ)=2.5 V(pI)=2.5 V(mI)=2.5 V(pQ)=2.5 V(mQ)=2.5 V(vbias_t)=2.5 V(n_mx)=2.5 V(lI)=0 V(lQ)=0
    .options method=gear reltol=1e-4
    .control
    tran 5n 2.5m 0.5m uic
    wrdata """ + out + """ v(outI) v(outQ) v(x0) v(n_mx)
    quit
    .endc
    .end
    """
    return '\n'.join(line.strip() for line in deck.split('\n'))


def fit(path, f=12000.0, t0=1.0e-3):
    d = np.loadtxt(path)
    t = d[:, 0]
    m = t >= t0
    tu = np.arange(t[m][0], t[m][-1], 1e-7)
    i = np.interp(tu, t[m], d[m, 1])
    q = np.interp(tu, t[m], d[m, 3])
    a = np.column_stack((np.cos(2 * np.pi * f * tu), np.sin(2 * np.pi * f * tu), np.ones_like(tu)))
    ci = np.linalg.lstsq(a, i, rcond=None)[0]
    cq = np.linalg.lstsq(a, q, rcond=None)[0]
    zi, zq = ci[0] - 1j * ci[1], cq[0] - 1j * cq[1]
    return abs(zi), abs(zq), np.degrees(np.angle(zq / zi)), ci[2]


def main():
    amp = 0.02                                          # 20 mV from a 50 ohm source
    tmp = tempfile.mkdtemp(prefix='pmds_spice_')
    print('Station: %g mV from 50 ohm. Output at the line input, after 1 uF into 10k.' % (amp * 1e3))
    ref = None
    for what, flo, frf in CASES:
        out = os.path.join(tmp, 'out.txt')
        cir = os.path.join(tmp, 'deck.cir')
        open(cir, 'w').write(deck(flo, frf, amp, out))
        subprocess.run(['ngspice', '-b', cir], capture_output=True, check=True)
        ai, aq, ph, dc = fit(out)
        ref = ref or ai
        side = '+12 kHz' if ph < 0 else '-12 kHz'
        print('%-66s I %.3f V, Q %.3f V peak, Q %+.0f deg from I (%s), %+.1f dB' % (
            what, ai, aq, ph, side, 20 * np.log10(ai / ref)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
