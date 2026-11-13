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
               1 or 2 bit errors; all-ones is not a valid block; PI codes from call letters
  vectors      the blocks in Appendix A of the draft specification
  loopback     Encoder -> Demodulator on a clean carrier gives back PI, PS, RadioText and
               the extended fields, a long RT+ title included
  slips        with samples dropped now and then, the framer follows the slip and keeps decoding
  clocks       a transmitter bit clock 100 ppm fast or slow costs no blocks
  alerts       an emergency alert shows, with its text, and clears when it ends; one group
               that signals an alert doesn't raise it, nor do RadioText groups alone; two in
               a row with a core group among them do
  one station  a PI is taken after two core groups in a row, and everything shown for the
               station before goes; another station's groups on the channel (a short visit,
               an extended group, RadioText) never show under this station's name
  sample rate  the encoder refuses a sample rate that puts the bit rate out of tolerance
"""
import datetime
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
        ('RT seg 0, emergency', codec.rt_group(0, 0, rt[0], 2), ('02432B6360CA', '379610209297')),
        ('station ID', codec.ext_station(pi, 73977), ('2AF1800902EB', '7CD000000160')),
        ('AF list', codec.ext_af(pi, [codec.af_code(95.5), codec.af_code(750)]),
         ('2AF18A2842EC', '5C00000006C9')),
        ('clock', codec.ext_clock(pi, datetime.datetime(2026, 11, 13, 15, 27, tzinfo=datetime.timezone.utc)),
         ('2AF193BEB104', '5ED800000714')),
        ('RT+', codec.ext_rtplus(pi, 1, 1, (1, 8, 17), (4, 0, 5)), ('2AF19E0909B4', '0080100007A1')),
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
    # NRSC-4-B D.7: x0yz is sent as Axyz, xy00 as AFxy, and x000 goes through both
    for call, pi in (('KACR', 0xA145), ('KEOE', 0xAF1C), ('KAAA', 0xAFA1), ('WSB', 0x99A3), ('KZZZ', 0x54A7)):
        assert codec.callsign_to_pi(call) == pi, (call, '%04X' % codec.callsign_to_pi(call))
        assert codec.pi_to_callsign(pi) == call, (call, codec.pi_to_callsign(pi))


def test_vectors():
    for name, blocks, want in _vectors():
        got = tuple('%012X' % b for b in blocks)
        assert got == want, (name, got, want)
        assert all(codec.syndrome(b) in codec.OFFSET.values() for b in blocks), name


def test_loopback():
    fs = 6000
    rt = 'Queen - Bohemian Rhapsody (Remastered 2011 Extended Version)'
    e = Encoder(samp_rate=fs, deviation=15.0, bit_rate=93.75, call='WAMD', ps='AM 1650',
                rt=rt, rt_file='', facility_id=73977, af='95.5,750')
    e.quiet = True
    d = Demodulator(fs, 93.75)
    carrier = np.ones(fs, np.complex64)
    for _ in range(45):                                  # 45 seconds
        d.process(e.modulate(carrier))
    assert d.pi == 0x55E3, d.pi
    assert d.ps == 'AM 1650 ', repr(d.ps)
    assert d.rt == rt, repr(d.rt)
    assert d.compact.facility_id == 73977
    assert d.compact.af_list == ['95.5 MHz', '750 kHz'], d.compact.af_list
    assert d.compact.clock and d.compact.clock.endswith('h)'), d.compact.clock
    # the title is 52 characters: it has to travel in RT+ tag 1, which holds 64 (tag 2 holds 32)
    assert (d.compact.artist, d.compact.title) == ('Queen', rt[8:]), (d.compact.artist, d.compact.title)
    assert d.compact.counts['lost'] == 0 and d.compact.counts['fixed'] == 0, d.compact.counts


def test_slips():
    fs = 6000
    e = Encoder(samp_rate=fs, deviation=8.6, call='WAMD', ps='AM 1650', rt='Slip test', rt_file='')
    e.quiet = True
    y = e.modulate(np.ones(120 * fs, np.complex64))       # 2 minutes
    rng = np.random.default_rng(3)
    parts, i = [], 0
    while i < len(y):                                     # drop 5 to 300 samples every 4 to 8 s
        j = min(len(y), i + int(rng.uniform(4, 8) * fs))
        parts.append(y[i:j])
        i = j + int(rng.integers(5, 300))
    z = np.concatenate(parts)
    got = {}
    for slip in (False, True):
        d = Demodulator(fs, 93.75)
        d.compact.SLIP_SEARCH = d.rbds.SLIP_SEARCH = slip
        for k in range(0, len(z), 3000):
            d.process(z[k:k + 3000])
        got[slip] = (d.compact.groups, d.compact.slips_found)
        assert d.ps == 'AM 1650 ' and d.rt == 'Slip test', (slip, d.ps, d.rt)
    assert got[True][1] > 0 and got[False][1] == 0, got
    assert got[True][0] > 1.3 * got[False][0], got     # following slips keeps far more groups


def test_alert_in_rt():
    # three core groups, then one RadioText group, and so on
    fs = 6000
    e = Encoder(samp_rate=fs, call='WAMD', ps='AM 1650', rt='x', rt_file='', rt_every=3, alert=2,
                alert_text='Tornado warning for Fulton County until 9 PM.')
    e.quiet = True
    d = Demodulator(fs, 93.75)
    seen = []
    d.log = lambda fr, kind, f: seen.append((kind, f.get('alert'))) if fr.fmt == 'compact' else None
    for _ in range(20):
        d.process(e.modulate(np.ones(fs, np.complex64)))
    assert d.compact.alert == 2, d.compact.alert
    assert ('rt', 2) in seen, seen[:6]
    assert d.rt.startswith('Tornado warning'), d.rt
    e.alert = 0
    for _ in range(10):
        d.process(e.modulate(np.ones(fs, np.complex64)))
    assert d.compact.alert == 0


def test_clock_offset():
    # the transmitter's bit clock against the receiver's sample clock, 100 ppm either way
    fs = 6000
    e = Encoder(samp_rate=fs, call='WAMD', ps='AM 1650', rt='Clock test', rt_file='')
    e.quiet = True
    y = e.modulate(np.ones(300 * fs, np.complex64))       # 5 minutes: the timing wraps 2 or 3 times
    for ppm in (+100, -100):
        t = np.arange(int(len(y) / (1 + ppm * 1e-6)) - 1) * (1 + ppm * 1e-6)
        i = t.astype(int)
        z = y[i] * (1 - (t - i)) + y[i + 1] * (t - i)
        d = Demodulator(fs, 93.75)
        for k in range(0, len(z), 3000):
            d.process(z[k:k + 3000])
        c = d.compact
        assert c.counts['lost'] == 0 and c.slips_found == 0, (ppm, c.counts, c.slips_found)
        assert c.counts['clean'] > 590, (ppm, c.counts)       # every block of the 5 minutes


# ---- the framer alone, fed bits ----
class _Bits:
    """What a framer needs from its demodulator, for tests that feed it bits."""
    bit_rate, log = 93.75, None

    def __init__(self):
        self.n = 0
        self.fr = None

    def now(self):
        return self.n / self.bit_rate

    def feed(self, bits):
        for b in bits:
            self.n += 1
            self.fr.push(int(b))
            self.fr.alert_tick()


def _framer():
    from pmds.framer import CompactFramer
    dec = _Bits()
    dec.fr = CompactFramer(dec)
    return dec, dec.fr


def _station(call, ps, rt, **kw):
    e = Encoder(samp_rate=6000, call=call, ps=ps, rt=rt, rt_file='', **kw)
    e.quiet = True
    return e


def _groups(e, n=1, kinds=None):
    """The bits of the next n groups; with kinds, skip ahead to the next group of one of them."""
    out = []
    while len(out) < n:
        kind, blocks, nbits = e.next_group()
        if kinds is None or kind.rstrip('0123456789') in kinds:
            out.append(codec.blocks_to_bits(blocks, nbits))
    return np.concatenate(out)


def test_alert_needs_two():
    a = _station('WAMD', 'AM 1650', 'Ordinary text')
    dec, fr = _framer()
    dec.feed(_groups(a, 12))
    assert fr.pi == 0x55E3 and fr.alert == 0
    pi, ps = 0x55E3, (codec.text_to_codes('AM 1650', True) + [0x20] * 8)[:8]
    one = codec.blocks_to_bits(codec.core_group(pi, 31, 0, 0, 0, 0, ps, 1))
    dec.feed(one)                                         # one group says emergency: not enough
    dec.feed(_groups(a, 6))
    assert fr.alert == 0, fr.alert
    text = codec.blocks_to_bits(codec.rt_group(0, 0, codec.text_to_codes('Ordinary'), 2))
    dec.feed(np.concatenate((text, text, text)))          # RadioText groups alone: not enough either
    assert fr.alert == 0, fr.alert
    dec.feed(_groups(a, 6))
    dec.feed(np.concatenate((text, one)))                 # two in a row, one of them a core group
    assert fr.alert == 2, fr.alert
    dec.feed(_groups(a, 4))                               # and it ends
    assert fr.alert == 0, fr.alert
    dec.feed(np.concatenate((one, one)))                  # two core groups
    assert fr.alert == 2, fr.alert


def test_one_station():
    a = _station('WAMD', 'AM 1650', 'Elvis Presley - Suspicious Minds', facility_id=73977, af='95.5')
    b = _station('KZZZ', 'OTHER', 'The other station, with other text', facility_id=12345, af='101.1')
    a_rt, b_ps = 'Elvis Presley - Suspicious Minds', 'OTHER   '
    dec, fr = _framer()
    shown = []
    dec.log = lambda f, kind, fields: shown.append((f.pi, f.ps, f.rt, f.facility_id, tuple(f.af_list)))

    def ours_only():
        for pi, ps, rt, fac, af in shown:
            assert pi in (None, 0x55E3), '%04X' % pi
            assert ps in (None, 'AM 1650 '), ps
            assert a_rt.startswith(rt), rt
            assert fac in (None, 73977) and af in ((), ('95.5 MHz',)), (fac, af)

    dec.feed(_groups(a, 1))
    assert fr.pi is None                                  # one core group is not yet a station
    dec.feed(_groups(a, 70))
    assert (fr.pi, fr.ps, fr.rt) == (0x55E3, 'AM 1650 ', a_rt), (fr.pi, fr.ps, fr.rt)
    assert (fr.facility_id, fr.af_list, fr.artist) == (73977, ['95.5 MHz'], 'Elvis Presley')
    ours_only()

    # the other station's groups exactly in step with ours, so nothing slips: an extended group
    # and a core group. Each names its station, so neither is ours to show. (A RadioText group
    # carries no PI; exactly in step, and clean on both sides, is the one way it could pass.)
    for kinds in (('station', 'af'), ('core',)):
        dec.feed(_groups(b, 1, kinds))
        dec.feed(_groups(a, 3))
    ours_only()
    assert (fr.pi, fr.rt, fr.facility_id, fr.af_list) == (0x55E3, a_rt, 73977, ['95.5 MHz'])

    # a short visit out of step, as when the other station fades up for a few seconds: three
    # of its groups over ours, 13 bits off our block boundaries, then ours again where they were
    bits, visit = _groups(a, 24), _groups(b, 3)
    bits[94 + 13:94 + 13 + len(visit)] = visit
    dec.feed(bits)
    ours_only()
    assert fr.slips_found >= 1 and (fr.pi, fr.rt) == (0x55E3, a_rt), (fr.slips_found, fr.pi, fr.rt)

    # the other station takes over: two of its core groups in a row, and everything of ours goes
    shown.clear()
    dec.feed(_groups(b, 2, ('core',)))
    assert (fr.pi, fr.rt, fr.facility_id, fr.af_list, fr.artist, fr.clock) == (0x54A7, '', None, [], None, None)
    dec.feed(_groups(b, 70))
    assert (fr.ps, fr.rt, fr.facility_id, fr.af_list) == (b_ps, 'The other station, with other text',
                                                          12345, ['101.1 MHz'])


def test_sample_rate():
    def run(rate, strict=True):
        e = Encoder(samp_rate=rate, rt_file='')
        e.quiet, e.strict_rate = True, strict
        e.modulate(np.ones(4, np.complex64))
    for rate in (192000, 96000, 48000, 6000):
        run(rate)
    for rate in (44100, 250000):                          # 851 ppm and 125 ppm off
        try:
            run(rate)
        except ValueError:
            pass
        else:
            raise AssertionError('%d Hz was accepted' % rate)
    run(44100, strict=False)                              # the GNU Radio block's choice: a warning


if __name__ == '__main__':
    for t in (test_check_code, test_vectors, test_loopback, test_slips, test_clock_offset, test_alert_in_rt,
              test_alert_needs_two, test_one_station, test_sample_rate):
        t()
        print('ok  ', t.__name__)
