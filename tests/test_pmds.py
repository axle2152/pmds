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
PMDS self-test, no GNU Radio needed:  python tests/test_pmds.py   (or pytest)

  check code   no undetectable 1 to 3 bit errors at 47 bits; offsets can't be confused by
               1 or 2 bit errors; all-ones is not a valid block
  vectors      the blocks in Appendix A of the draft specification
  loopback     Encoder -> Demodulator on a clean carrier gives back PI, PS and RadioText
"""
import itertools
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pmds import codec, Encoder, Demodulator  # noqa: E402

# Appendix A: (blocks as built here, expected 47-bit blocks in hex)
WAMD_PS = (codec.text_to_codes('AM 1650', True) + [0x20] * 8)[:8]


def _vectors():
    pi = codec.callsign_to_pi('WAMD')
    rt = codec.rt_segments(codec.text_to_codes('Hello, AM radio'))
    return [
        ('core PS 1-4', codec.core_group(pi, 4, 0, 0, 1, 0, WAMD_PS), ('2AF190800406', '20A690188702')),
        ('core PS 5-8', codec.core_group(pi, 4, 0, 0, 1, 1, WAMD_PS), ('2AF190C003B5', '1B1A98100588')),
        ('core alert', codec.core_group(pi, 31, 0, 0, 1, 0, WAMD_PS, 1), ('2AF1FCA007D7', '20A690188702')),
        ('RT seg 0', codec.rt_group(0, 0, rt[0]), ('02432B6360CA', '379610208309')),
        ('RT seg 1', codec.rt_group(1, 0, rt[1]), ('1269039308ED', '3234B7868111')),
        ('station ID', codec.ext_station(73977), ('000907CD0177', '000000000007')),
        ('AF list', codec.ext_af([codec.af_code(95.5), codec.af_code(750)]), ('0A2845C00268', '000000000007')),
        ('ISRC', codec.ext_isrc('USRC17607839'), ('2524D980CEFE', '40F4F8000547')),
    ]


def test_check_code():
    syn = [codec.syndrome(1 << i) for i in range(47)]
    assert all(syn)
    assert not any(syn[i] == syn[j] for i, j in itertools.combinations(range(47), 2))
    assert not any(syn[i] ^ syn[j] ^ syn[k] == 0 for i, j, k in itertools.combinations(range(47), 3))
    one_two = set(syn) | {syn[i] ^ syn[j] for i, j in itertools.combinations(range(47), 2)}
    offs = list(codec.OFFSET.values())
    assert not any(a ^ b in one_two for a, b in itertools.combinations(offs, 2))
    assert codec.syndrome((1 << 47) - 1) not in offs
    assert codec.callsign_to_pi('WAMD') == 0x55E3


def test_vectors():
    for name, blocks, want in _vectors():
        got = tuple('%012X' % b for b in blocks)
        assert got == want, (name, got, want)
        assert all(codec.syndrome(b) in codec.OFFSET.values() for b in blocks), name


def test_loopback():
    fs = 6000
    e = Encoder(samp_rate=fs, deviation=15.0, bit_rate=93.75, call='WAMD', ps='AM 1650',
                rt='Hello, AM radio', rt_file='', facility_id=73977, af='95.5,750')
    e.quiet = True
    d = Demodulator(fs, 93.75)
    carrier = np.ones(fs, np.complex64)
    for _ in range(30):                                  # 30 seconds
        d.process(e.modulate(carrier))
    assert d.pi == 0x55E3, d.pi
    assert d.ps == 'AM 1650 ', repr(d.ps)
    assert d.rt == 'Hello, AM radio', repr(d.rt)
    assert d.compact.facility_id == 73977
    assert d.compact.af_list == ['95.5 MHz', '750 kHz'], d.compact.af_list
    assert d.compact.counts['lost'] == 0 and d.compact.counts['fixed'] == 0, d.compact.counts


if __name__ == '__main__':
    for t in (test_check_code, test_vectors, test_loopback):
        t()
        print('ok  ', t.__name__)
