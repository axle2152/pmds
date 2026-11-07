#!/usr/bin/env python3
# Copyright 2026 Michael Foley
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
PMDS offline checker: decodes the station data from a recording of the transmitter's
complex baseband (GRC File Sink, complex), with no radio in the loop.

    python pmds_check.py pmds_tx.cfile [--rate 192000]

It runs the receiver's own data path (1 Hz carrier PLL, 6 kHz data channel, the PmdsDecoders
from pmds_receiver.py at every rate, each trying both the compact and the RBDS framing),
prints every group as it decodes, then a summary with the block counts.
Needs pmds_receiver.py and the pmds package beside it (or pmds installed).
"""
import argparse
import math
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault('osmosdr', types.ModuleType('osmosdr'))   # not needed offline
from gnuradio import gr, blocks, analog, filter
from gnuradio.filter import firdes

from pmds.codec import pi_to_callsign
from pmds_receiver import PmdsDecoder, PMDSReceiver


def show(fr, kind, f):
    t = '%7.1f s  %-7s %-6g' % (fr.now(), fr.fmt, fr.bit_rate)
    fix = ' (1 bit fixed)' if f.get('fixed') else ''
    if kind == 'core':
        print('%s %-4s PI %04X %-4s PTY %2d TP %d TA %d alert %d  PS[%d] "%s"%s'
              % (t, f.get('group', 'core'), f['pi'], pi_to_callsign(f['pi']) or '----', f['pty'], f['tp'],
                 f['ta'], f['alert'], f['seg'], f['half'], fix))
    elif kind == 'rt':
        print('%s %-4s seg %d %s  "%s"%s' % (t, f.get('group', 'rt'), f['seg'], 'AB'[f['ab']],
                                             f['text'].replace('\r', '|'), fix))
    elif kind == 'ext':
        print('%s ext  %s%s' % (t, f['info'], fix))
    else:
        print('%s %s  %09X %09X%s' % (t, kind, f['d1'], f['d2'], fix))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--rate', type=float, default=192000, help='sample rate of the recording')
    a = ap.parse_args()
    fs_in, ch = int(a.rate), 48000
    if fs_in % ch:
        sys.exit('the recording rate must be a multiple of 48 kHz')
    tb = gr.top_block()
    src = blocks.file_source(gr.sizeof_gr_complex, a.file, False)
    chan = filter.fir_filter_ccf(fs_in // ch, firdes.low_pass(1.0, fs_in, 10000, 4000))
    pll = analog.pll_carriertracking_cc(2 * math.pi * PMDSReceiver.PLL_HZ / ch,
                                        2 * math.pi * 60 / ch, -2 * math.pi * 60 / ch)
    dlp = filter.fir_filter_ccf(ch // PMDSReceiver.PMDS_FS, firdes.low_pass(1.0, ch, 500.0, 300.0))
    decs = [PmdsDecoder(PMDSReceiver.PMDS_FS, r) for r in PMDSReceiver.PMDS_RATES]
    tb.connect(src, chan, pll, dlp)
    for d in decs:
        d.log = show
        tb.connect(dlp, d)
    tb.run()
    print()
    for d in decs:
        for fr in d.framers:
            if not (fr.groups or fr.synced):
                continue
            c = fr.counts
            n = max(1, sum(c.values()))
            print('%-7s %-6g groups %4d  %-7s  blocks %d: clean %.1f%%  fixed %.1f%%  lost %.1f%%  '
                  'data %4.1f deg  PS "%s"  RT "%s"'
                  % (fr.fmt, fr.bit_rate, fr.groups, 'synced' if fr.synced else 'no sync', sum(c.values()),
                     100.0 * c['clean'] / n, 100.0 * c['fixed'] / n, 100.0 * c['lost'] / n,
                     fr.dev_deg(), fr.ps or '', fr.rt))


if __name__ == '__main__':
    main()
