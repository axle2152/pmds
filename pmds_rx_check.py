#!/usr/bin/env python3
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
pmds_rx_check.py: is the AM receiver's signal chain moving? No window, no tuner.

    python3 pmds_rx_check.py                 # 1080 kHz
    python3 pmds_rx_check.py --freq 750e3

Runs the AM receiver (pmds_receiver.PMDSReceiver) twice, 10 s each:
  1. as the tuner runs it, with sound
  2. with the sound output swapped for a silent sink
and prints every second how many samples each stage has moved, then a verdict in plain
words. Each run is its own process with a time limit, so a stuck run can't hang this.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SECS = 10
STAGES = ('from dongle', 'carrier PLL', 'into PMDS', 'to sound')
RATES = (2_400_000, 48_000, 6_000, 48_000)          # samples per second when all is well


# ---------------------------------------------------------------------------- child
def child(mode, freq, secs):
    import numpy as np
    from gnuradio import gr, blocks
    import pmds_receiver as R

    print('INFO GNU Radio', gr.version(), '| numpy', np.__version__,
          '| Python', sys.version.split()[0], flush=True)
    cls = R.PMDSReceiver
    if mode == 'silent':
        class Silent(R.PMDSReceiver):
            def _make_audio_sink(self, device):
                return blocks.null_sink(gr.sizeof_float)
        cls = Silent
    tb = cls(freq=freq)
    probes = (lambda: tb.xlate.nitems_read(0), lambda: tb.pll.nitems_written(0),
              lambda: tb.pmds_lp.nitems_written(0), lambda: tb.audio_sink.nitems_read(0))
    tb.start()
    print('STARTED', flush=True)
    t0 = time.monotonic()
    for i in range(1, secs + 1):
        time.sleep(max(0.0, t0 + i - time.monotonic()))
        vals = []
        for p in probes:
            try:
                vals.append(str(int(p())))
            except Exception:
                vals.append('-1')
        print('DATA', i, *vals, flush=True)
    try:
        x = np.asarray(tb.snap_wb.level())
        if len(x):
            print('SIGNAL', len(np.unique(np.round(x, 6))), f'{float(np.mean(np.abs(x))):.4f}',
                  flush=True)
    except Exception as e:
        print('INFO signal snapshot failed:', e, flush=True)
    tb.stop()
    tb.wait()
    print('STOPPED', flush=True)


# ---------------------------------------------------------------------------- parent
def run(mode, freq):
    cmd = [sys.executable, os.path.abspath(__file__), '--child', mode, '--freq', str(freq)]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         cwd=HERE)
    hung = False
    try:
        out, _ = p.communicate(timeout=SECS + 25)
    except subprocess.TimeoutExpired:
        hung = True
        p.kill()
        out, _ = p.communicate()
    rows, signal, msgs, started, stopped = [], None, [], False, False
    for line in out.splitlines():
        w = line.split()
        if w[:1] == ['DATA'] and len(w) == 6:
            rows.append([int(v) for v in w[1:]])
        elif w[:1] == ['SIGNAL'] and len(w) == 3:
            signal = (int(w[1]), float(w[2]))
        elif w[:1] == ['STARTED']:
            started = True
        elif w[:1] == ['STOPPED']:
            stopped = True
        elif w[:1] == ['INFO']:
            print('  ' + line[5:])
        elif line.strip():
            msgs.append(line)
    if msgs:
        print('  Messages from GNU Radio and the dongle:')
        for m in msgs[-25:]:
            print('    | ' + m)
    if rows:
        print('  %6s' % 'second' + ''.join('%14s' % s for s in STAGES))
        for r in rows:
            print('  %6d' % r[0] + ''.join('%14s' % (f'{v:,}' if v >= 0 else 'n/a') for v in r[1:]))
    return dict(rows=rows, signal=signal, started=started, stopped=stopped, hung=hung,
                code=p.returncode)


def moving(res):
    """Per stage: still moving over the last 3 s?"""
    rows = res['rows']
    if len(rows) < 4:
        return None
    a, b = rows[-4], rows[-1]
    return [b[k] > a[k] for k in range(1, 5)]


def first_stopped(res):
    """The stage that stopped first, by the second its count last changed."""
    rows, last = res['rows'], {}
    for k in range(1, 5):
        last[k] = 0
        for i in range(1, len(rows)):
            if rows[i][k] > rows[i - 1][k]:
                last[k] = rows[i][0]
    k = min(last, key=lambda j: (last[j], j))
    return STAGES[k - 1], last[k]


def verdict(snd, sil):
    print('\n=== Verdict ===')
    ms, mq = moving(snd), moving(sil)
    if not snd['started'] and not sil['started']:
        print('The receiver did not start at all; the messages above say why.')
        return
    if snd['signal'] and snd['signal'][0] <= 3:
        print('Note: the dongle\'s samples are all (nearly) the same value, so no signal is reaching\n'
              'it in direct-sampling mode. Check the antenna is connected to the dongle.')
    if ms and all(ms) and not snd['hung']:
        print('The receiver runs fine on its own, with sound, for %d s.\n'
              'So the dongle, GNU Radio and the sound card all work: the problem is in how the\n'
              'tuner window drives the receiver.' % SECS)
        return
    if mq and all(mq) and not (ms and all(ms)):
        print('Without sound the receiver runs fine; with sound it stops.\n'
              'So the sound output is what stalls it.')
        return
    if mq is None and ms is None:
        print('Neither run got far enough to measure; the messages above say why.')
        return
    res = sil if mq is not None else snd
    st, t = first_stopped(res)
    print('The receiver stops even without sound. The first stage to stop was "%s", after %d s.'
          % (st, t))
    if snd['hung'] or sil['hung']:
        print('A run also failed to shut down, so a block was stuck rather than just waiting.')


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument('--freq', type=float, default=1080e3)
    ap.add_argument('--child', choices=('sound', 'silent'), help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.child:
        child(a.child, a.freq, SECS)
        return
    print('Expected per second when all is well: ' +
          ', '.join(f'{s} about {r:,}' for s, r in zip(STAGES, RATES)))
    print('\n=== Run 1 of 2: with sound, as the tuner runs it (%d s) ===' % SECS)
    snd = run('sound', a.freq)
    time.sleep(2)                                    # let the dongle go before the next run
    print('\n=== Run 2 of 2: sound output swapped for a silent one (%d s) ===' % SECS)
    sil = run('silent', a.freq)
    verdict(snd, sil)
    print('\nPlease paste everything above into the chat.')


if __name__ == '__main__':
    main()
