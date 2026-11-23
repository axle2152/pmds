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
EXPERIMENTAL (branch experimental-qpsk): the two-stream physical layer, QPSK on the phase.

Today's PMDS is BPSK on a subcarrier of the phase: one sine cycle per bit is a 93.75 Hz
subcarrier whose sign is the bit. Its two sidebands carry the same thing. QPSK puts a second,
independent stream on the same subcarrier in quadrature (cosine), which fills both sidebands:
two bits per symbol, 187.5 bit/s at 93.75 symbols per second, in about the same band.

The symbols are shaped by a root-raised-cosine pulse (roll-off ALPHA) instead of being cut to
one bit each, so the phase stays smooth across symbol boundaries without needing every pulse
to start and end at zero. The shaped symbols overlap their neighbours (SPAN symbols either
side), and the matched filter in the receiver takes the overlap out again.

    phase(t) = deviation x (1/sqrt 2) x [ A(t) sin(2 pi 93.75 t) + B(t) cos(2 pi 93.75 t) ]
    A(t) = sum a_k g(t - t_k),  B(t) = sum b_k g(t - t_k),  a_k, b_k = +/-1 (bits 2k and 2k+1)

g is scaled so that the mean square of A is 1. With the 1/sqrt 2, the data power (mean square
phase) at a given deviation setting is the same as BPSK's at the same setting: each bit then
gets half BPSK's energy, the price of twice the rate. The peak phase is higher than the
setting (about 1.37 times at ALPHA 0.5), because the shaped symbols add up now and then.

The subcarrier is locked to the symbol clock, so a timing error in the receiver also rotates
the subcarrier's phase and mixes the two streams (a quarter symbol swaps them). The receiver
therefore times symbols by the fourth power of the matched filter's output, which peaks
sharply where the four QPSK points line up (see pmds.demod).
"""
from functools import lru_cache

import numpy as np

ALPHA = 0.5        # root-raised-cosine roll-off: 0.5 keeps 99% of the energy in 30 to 150 Hz
SPAN = 4           # pulse length: this many symbols either side of the centre


def rrc(spb, alpha=ALPHA, span=SPAN):
    """Root-raised-cosine pulse, spb samples per symbol, 2 * span * spb + 1 taps, scaled so
    that its energy is one symbol's worth (sum of squares = spb)."""
    x = np.arange(-span * spb, span * spb + 1) / float(spb)
    h = np.empty_like(x)
    for i, t in enumerate(x):
        if abs(t) < 1e-12:
            h[i] = 1 - alpha + 4 * alpha / np.pi
        elif alpha > 0 and abs(abs(t) - 1 / (4 * alpha)) < 1e-12:
            h[i] = alpha / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                                         + (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
        else:
            h[i] = ((np.sin(np.pi * t * (1 - alpha)) + 4 * alpha * t * np.cos(np.pi * t * (1 + alpha)))
                    / (np.pi * t * (1 - (4 * alpha * t) ** 2)))
    return h * np.sqrt(spb / np.sum(h * h))


@lru_cache(maxsize=8)
def templates(spb):
    """The unit phase of one symbol on each stream, centred: (TI, TQ), each 2 * SPAN * spb + 1
    samples, for a symbol centred half a symbol into its slot (where BPSK's sine bit would have
    its middle). TI has the same sense as BPSK's sine bit (a 1 swings the phase + then -).
    Cached: don't write into the arrays."""
    g = rrc(spb)
    m = np.arange(-SPAN * spb, SPAN * spb + 1)
    w = 2 * np.pi * m / spb
    ti, tq = -g * np.sin(w) / np.sqrt(2), -g * np.cos(w) / np.sqrt(2)
    ti.flags.writeable = tq.flags.writeable = False
    return ti, tq
