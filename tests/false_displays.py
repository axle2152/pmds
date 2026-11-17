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
How often does a PMDS receiver show something false, and how fast does a real alert show?

    python tests/false_displays.py                    # 20 hours per channel, a few minutes
    python tests/false_displays.py --hours 600 --alert-hours 40     # the specification's run

A long simulation at the level of bits, no GNU Radio needed and not part of the self-test.
The reference encoder's bits go through a channel with two states, and the reference framer
(pmds.framer) reads them:
  between fades   a low bit error rate
  in a fade       the bits are coin flips, which is what gets garbage past an 11-bit check word
Three channels: night fading (15% of the time in fades about 1 s long), heavy fading (30% in
2 s fades, 1% bit errors between them) and a steady weak signal (1.4% bit errors, the block
mix of about 3 dB C/N).

First with no alert on the air, counting each time the framer comes to show
  a false alert, a PI that isn't the station's, a wrong name, RadioText that isn't the
  station's text, a wrong facility ID or AF list.
Then with an emergency alert on for 30 groups in every 80: how long until it shows, how many
are missed altogether, and whether any is still showing 25 groups after it ended.
"""
import argparse
import multiprocessing as mp
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pmds import codec  # noqa: E402
from pmds.encoder import Encoder  # noqa: E402
from pmds.framer import CompactFramer  # noqa: E402

RATE = 93.75
PS, RT = 'AM 1650 ', 'Now playing: Fleetwood Mac - Go Your Own Way on AM 1650 WAMD ...'
ALERT_ON, ALERT_PERIOD = 30, 80
CHANNELS = (('night fading, 15% of the time in 1 s fades', 0.001, 0.15, 1.0),
            ('heavy fading, 30% of the time in 2 s fades', 0.01, 0.30, 2.0),
            ('steady weak signal, 1.4% bit errors', 0.0143, 0.0, 1.0))


class _Clock:
    """What a framer needs from its demodulator."""
    bit_rate, log = RATE, None

    def __init__(self):
        self.n = 0

    def now(self):
        return self.n / RATE


def run(args):
    seed, hours, ber, share, fade_secs, alerts = args
    rng = np.random.default_rng(seed)
    e = Encoder(samp_rate=6000, call='WAMD', ps=PS, rt=RT, rt_file='', facility_id=73977, af='95.5')
    e.quiet = True
    clock = _Clock()
    f = CompactFramer(clock)
    pi = codec.callsign_to_pi('WAMD')
    st = dict(alert=0, emergency=0, pi=0, ps=0, rt=0, fac=0, af=0, sent=0, missed=0, stuck=0, delays=[])
    last = (None, None, 0, '', None, [])
    enter = (1 / RATE) / (fade_secs * (1 - share) / share) if share else 0.0
    leave = (1 / RATE) / fade_secs
    faded, t_on, seen = False, None, False
    for g in range(int(hours * 3600 * RATE / 94)):
        if alerts:
            k = g % ALERT_PERIOD
            if k == 10:
                e.alert, t_on, seen = 2, clock.now(), False
                st['sent'] += 1
            elif k == 10 + ALERT_ON:
                e.alert = 0
                st['missed'] += not seen
                t_on = None
            elif k == 10 + ALERT_ON + 25:
                st['stuck'] += bool(f.alert)
        for b in codec.blocks_to_bits(e.next_group()[1]):
            if faded:
                faded = rng.random() >= leave
            else:
                faded = rng.random() < enter
            if faded:
                b = int(rng.integers(0, 2))
            elif rng.random() < ber:
                b ^= 1
            clock.n += 1
            f.push(int(b))
            f.alert_tick()
        if alerts:
            if t_on is not None and not seen and f.alert:
                seen = True
                st['delays'].append(clock.now() - t_on)
            continue
        now = (f.pi, f.ps, f.alert, f.rt, f.facility_id, list(f.af_list))
        st['alert'] += bool(f.alert and not last[2])
        st['emergency'] += f.alert == 2 and not last[2]
        st['pi'] += f.pi not in (None, pi, last[0])
        st['ps'] += f.ps not in (None, PS, last[1])
        st['rt'] += f.rt != last[3] and not RT.startswith(f.rt)
        st['fac'] += f.facility_id not in (None, 73977, last[4])
        st['af'] += bool(f.af_list) and f.af_list != ['95.5 MHz'] and f.af_list != last[5]
        last = now
    return st


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--hours', type=float, default=20, help='simulated hours per channel with no alert on the air')
    ap.add_argument('--alert-hours', type=float, default=4, help='simulated hours per channel with alerts')
    ap.add_argument('--procs', type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()

    def each(k):
        if not k:
            return '0'
        h = a.hours / k
        return '%d (one per %.0f h)' % (k, h) if h >= 1.5 else '%d (one per %.0f min)' % (k, 60 * h)
    with mp.Pool(a.procs) as pool:
        print('No alert on the air, %g h per channel:' % a.hours)
        for name, ber, share, secs in CHANNELS:
            rs = pool.map(run, [(100 + i, a.hours / a.procs, ber, share, secs, False) for i in range(a.procs)])
            t = {k: sum(r[k] for r in rs) for k in ('alert', 'emergency', 'pi', 'ps', 'rt', 'fac', 'af')}
            print('  %-44s false alert %s, emergency %d | wrong PI %s | wrong name %s\n  %-44s wrong RadioText %s '
                  '| wrong facility ID %d | wrong AF list %d'
                  % (name, each(t['alert']), t['emergency'], each(t['pi']), each(t['ps']), '', each(t['rt']),
                     t['fac'], t['af']), flush=True)
        print('Emergency alerts, %d s long, %g h per channel:' % (round(ALERT_ON * 94 / RATE), a.alert_hours))
        for name, ber, share, secs in CHANNELS:
            rs = pool.map(run, [(200 + i, a.alert_hours / a.procs, ber, share, secs, True) for i in range(a.procs)])
            d = np.array(sum((r['delays'] for r in rs), []))
            sent, missed, stuck = (sum(r[k] for r in rs) for k in ('sent', 'missed', 'stuck'))
            print('  %-44s %d alerts, %d missed, %d stuck; shown after a median %.1f s, 95%% within %.1f s'
                  % (name, sent, missed, stuck, np.median(d), np.percentile(d, 95)), flush=True)


if __name__ == '__main__':
    main()
