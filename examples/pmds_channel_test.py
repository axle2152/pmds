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
Offline PMDS channel test: encoder -> skywave simulator -> the receiver's data path,
no hardware, as fast as the PC runs. Same blocks as the real chain: pmds_encoder.blk,
skywave_channel.blk, the 1 Hz carrier PLL and PmdsDecoder from pmds_receiver.

    python pmds_channel_test.py                       # every preset, compact 93.75 at 15 deg, 3 seeds
    python pmds_channel_test.py --alert               # how long an alert takes to show, per preset
    python pmds_channel_test.py --formats rbds --rates 187.5 --presets night2 --program bass --dev 15
    python pmds_channel_test.py --presets night2,flutter --rates 46.875,93.75 --secs 300
    python pmds_channel_test.py --presets night2 --audibility
    python pmds_channel_test.py --presets steady,night2 --rates 93.75 --dev 10 --ipm 3 --program bass

Per run it reports:
  groups   share of the groups sent that decoded
  PS, RT   seconds until the whole name / the whole 64-character RadioText first appeared
  wrong    shown/passed: groups with another station's PI that the decoder took / that
           passed their check at all (a corrected one has to be confirmed before it's taken)
--audibility also runs each case twice more, data on and off with identical fading and no
noise, and measures the envelope difference a plain AM radio would hear, 60 to 400 Hz, per
second, in dB relative to 100% modulation (median / worst 10% / worst second), next to the
program audio's own level in that band.
"""
import argparse
import math
import os
import sys
import types

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.modules.setdefault('osmosdr', types.ModuleType('osmosdr'))   # not needed offline
from gnuradio import gr, blocks, analog, filter
from gnuradio.filter import firdes

import pmds_encoder as enc_gr
from pmds import codec as enc
import skywave_channel as sky
from pmds_receiver import PmdsDecoder, PMDSReceiver

FS = 48000                      # the receiver's channel rate
PS = 'AM 1710'
RT = 'Beyoncé - Halo (Live) · ¿Qué tal, Atlanta? 72°F and clear tonight'[:64]


DEV = 15.0                      # data deviation, degrees peak (--dev)
IPM = 0.0                       # transmitter IPM, degrees at 95% modulation (--ipm)
FLOOR = None                    # envelope normalization floor (--env-floor), None = the decoder's own
NORM = 'local'                  # decoder reference: 'local' (default), 'carrier' or 'envelope' (--norm)
PROGRAM = 'flat'                # 'flat': noise to 4.5 kHz; 'bass': plus heavy low end (--program)


def run(preset, rate, seed, secs, cn, data_on=True, keep_env=False, fmt='compact', alert=False):
    tb = gr.top_block()
    # program: noise below 4.5 kHz at 25% rms on a carrier of 1.0
    taps = firdes.low_pass(1.0, FS, 4500, 1000, filter.window.WIN_HAMMING)
    prog = analog.noise_source_f(analog.GR_GAUSSIAN, 0.25 / math.sqrt(sum(t * t for t in taps)), 1000 + seed)
    lp = filter.fir_filter_fff(1, taps)
    one = blocks.add_const_ff(1.0)
    rail = analog.rail_ff(0.02, 2.25)                 # -98% .. +125%, as a processor would hold it
    f2c = blocks.float_to_complex()
    head = blocks.head(gr.sizeof_gr_complex, int(secs * FS))
    E = AlertCycler if alert else enc_gr.blk
    e = E(samp_rate=FS, data_on=1 if data_on else 0, deviation=DEV, bit_rate=rate, fmt=fmt,
          call='WAMD', ps=PS, rt=RT, rt_file='', facility_id=73977, af='95.5', isrc='USMC17300123')
    e.quiet = True
    ch = sky.blk(samp_rate=FS, preset=preset, cn_db=cn, ipm_deg=IPM, seed=seed)
    ch.quiet = True
    if PROGRAM == 'bass':                             # dense, bass-heavy program: what drives IPM
        bt = firdes.low_pass(1.0, FS, 250, 150, filter.window.WIN_HAMMING)
        bass = analog.noise_source_f(analog.GR_GAUSSIAN, 0.30 / math.sqrt(sum(t * t for t in bt)), 2000 + seed)
        blp, mix = filter.fir_filter_fff(1, bt), blocks.add_ff()
        tb.connect(prog, lp, (mix, 0))
        tb.connect(bass, blp, (mix, 1))
        tb.connect(mix, one, rail, f2c, head, e, ch)
    else:
        tb.connect(prog, lp, one, rail, f2c, head, e, ch)
    # the receiver's data path
    pll = analog.pll_carriertracking_cc(2 * math.pi * PMDSReceiver.PLL_HZ / FS,
                                        2 * math.pi * 60 / FS, -2 * math.pi * 60 / FS)
    ta = firdes.low_pass(1.0, FS, 500.0, 300.0, filter.window.WIN_HAMMING)
    dlp = filter.fir_filter_ccf(FS // PMDSReceiver.PMDS_FS, ta)
    d = PmdsDecoder(PMDSReceiver.PMDS_FS, rate)
    d.LOCAL_BITS, d.ENV_FLOOR = {'local': (4, None), 'carrier': (0, None),
                                 'envelope': (0, FLOOR or 0.25)}[NORM]
    d._clear()
    stats = {'ps_t': None, 'rt_t': None, 'wrong': 0, 'shown': 0, 'alerts': []}
    gsec = (104.0 if fmt == 'rbds' else 94.0) / rate
    want_pi = enc.callsign_to_pi('WAMD')
    want_ps = enc.codes_to_text(enc.text_to_codes(PS, True)).ljust(8)[:8]
    want_rt = enc.codes_to_text(enc.text_to_codes(RT))

    def log(dec, kind, f):
        if dec.fmt != fmt:                                # the other framing found "sync": a false group
            stats['wrong'] += 1
            stats['shown'] += 1 if dec.pi is not None else 0
            return
        if kind == 'core' and f['pi'] != want_pi:
            stats['wrong'] += 1                           # passed its check with another PI
            if f['fixed']:
                stats['wrong_fixed'] = stats.get('wrong_fixed', 0) + 1
        if dec.pi is not None and dec.pi != want_pi:
            stats['shown'] += 1                           # ...and the decoder actually took it
        if alert:
            stats['alerts'].append((dec.now(), dec.alert))
        if stats['ps_t'] is None and dec.ps == want_ps:
            stats['ps_t'] = dec.now()
        if stats['rt_t'] is None and dec.rt == want_rt:
            stats['rt_t'] = dec.now()
    d.log = log
    tb.connect(ch, pll, dlp, d)
    env = None
    if keep_env:
        mag = blocks.complex_to_mag()
        env = blocks.vector_sink_f()
        tb.connect(ch, mag, env)
    tb.run()
    fr = d.rbds if fmt == 'rbds' else d.compact
    sent = secs * rate / (104.0 if fmt == 'rbds' else 94.0)
    if alert:
        return alert_score(stats['alerts'], gsec, secs)
    return {'groups': 100.0 * fr.groups / sent, 'ps_t': stats['ps_t'], 'rt_t': stats['rt_t'],
            'wrong': stats['wrong'], 'shown': stats['shown'], 'wrong_fixed': stats.get('wrong_fixed', 0),
            'env': np.array(env.data()) if env is not None else None}


ALERT_FIRST, ALERT_ON, ALERT_PERIOD = 20, 30, 80   # in groups: start, length, repeat


class AlertCycler(enc_gr.blk):
    """The encoder with the alert switched on and off on a schedule (PTY 31 + flag)."""
    def next_group(self):
        k = self._seq - ALERT_FIRST
        self.alert = 2 if k >= 0 and k % ALERT_PERIOD < ALERT_ON else 0
        return enc_gr.blk.next_group(self)


def alert_score(trace, gsec, secs):
    """From (time, alert level) samples at each decoded group: per alert, the delay until it was
    shown and until it cleared; alerts never shown; groups still showing an alert 15 groups after
    it ended (stuck)."""
    on_delays, off_delays, missed, false = [], [], 0, 0
    k = 0
    while (ALERT_FIRST + k * ALERT_PERIOD + ALERT_ON) * gsec < secs - 5:
        t_on = (ALERT_FIRST + k * ALERT_PERIOD) * gsec
        t_off = t_on + ALERT_ON * gsec
        t_next = t_on + ALERT_PERIOD * gsec
        shown = [t for t, a in trace if t_on <= t < t_off + 4 * gsec and a]
        cleared = [t for t, a in trace if t >= t_off and t < t_next and not a]
        if shown:
            on_delays.append(shown[0] - t_on)
        else:
            missed += 1
        if cleared:
            off_delays.append(cleared[0] - t_off)
        false += sum(1 for t, a in trace if a and (t_off + 15 * gsec) < t < t_next)
        k += 1
    return {'alerts': k, 'on': on_delays, 'off': off_delays, 'missed': missed, 'false': false}


def audibility(env_on, env_off):
    """Envelope difference per 1 s window, 60-400 Hz, relative to that second's carrier."""
    n = min(len(env_on), len(env_off)) // FS * FS
    out = []
    for i in range(1, n // FS):                       # skip the first second (start-up)
        a = env_on[i * FS:(i + 1) * FS]
        b = env_off[i * FS:(i + 1) * FS]
        car = np.mean(b)
        if car < 1e-3:
            continue
        D = np.fft.rfft((a - b) / car)
        f = np.fft.rfftfreq(FS, 1 / FS)
        band = (f >= 60) & (f <= 400)
        rms = math.sqrt(2 * np.sum(np.abs(D[band]) ** 2)) / FS
        out.append(20 * math.log10(max(rms * math.sqrt(2), 1e-9)))   # re 100% sine modulation
    out = np.array(out)
    return np.median(out), np.percentile(out, 90), np.max(out)


def program_level(env_off):
    """The program audio itself in the same band, for comparison (median over seconds)."""
    n = len(env_off) // FS * FS
    lv = []
    for i in range(1, n // FS):
        b = env_off[i * FS:(i + 1) * FS]
        car = np.mean(b)
        D = np.fft.rfft(b / car - 1)
        f = np.fft.rfftfreq(FS, 1 / FS)
        band = (f >= 60) & (f <= 400)
        lv.append(20 * math.log10(max(math.sqrt(2 * np.sum(np.abs(D[band]) ** 2)) / FS * math.sqrt(2), 1e-9)))
    return float(np.median(lv))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--presets', default=','.join(sky.PRESETS))
    ap.add_argument('--rates', default='93.75', help='comma list; 93.75 is the chosen rate')
    ap.add_argument('--formats', default='compact', help='compact, rbds or both')
    ap.add_argument('--seeds', type=int, default=3)
    ap.add_argument('--secs', type=float, default=180)
    ap.add_argument('--cn', type=float, default=30.0, help='mean C/N in 10 kHz, dB')
    ap.add_argument('--dev', type=float, default=15.0, help='data deviation, degrees peak')
    ap.add_argument('--ipm', type=float, default=0.0, help='transmitter IPM, degrees at 95%% modulation')
    ap.add_argument('--program', choices=('flat', 'bass'), default='flat',
                    help="test program: flat noise, or with heavy bass (what drives IPM)")
    ap.add_argument('--norm', choices=('local', 'carrier', 'envelope'), default='local',
                    help='decoder phase reference: local carrier over 4 bits (default), the slow carrier, '
                         'or the slow carrier over the envelope')
    ap.add_argument('--env-floor', type=float, default=None, help='envelope normalization floor (0..1)')
    ap.add_argument('--audibility', action='store_true')
    ap.add_argument('--alert', action='store_true',
                    help='alert timing: PTY 31 + flag on for 30 groups every 80; how long until it shows')
    a = ap.parse_args()
    global DEV, IPM, PROGRAM, NORM, FLOOR
    DEV, IPM, PROGRAM, NORM, FLOOR = a.dev, a.ipm, a.program, a.norm, a.env_floor
    rates = [float(r) for r in a.rates.split(',')]
    fmt = lambda v: '  -- ' if v is None else '%5.0f' % v
    print('C/N %g dB, data +/-%g deg, IPM %g deg, %s program, %d s per run, %d seeds' % (
        a.cn, a.dev, a.ipm, a.program, a.secs, a.seeds))
    if a.alert:
        print('%-10s %-8s %8s  %9s  %-22s %-14s %s' % ('preset', 'format', 'bit/s', 'shown',
                                                     'until shown: med / worst', 'cleared: med', 'stuck'))
        for preset in a.presets.split(','):
            for framing in a.formats.split(','):
                for rate in rates:
                    rs = [run(preset, rate, s + 1, a.secs, a.cn, fmt=framing, alert=True) for s in range(a.seeds)]
                    on = sum((r['on'] for r in rs), [])
                    off = sum((r['off'] for r in rs), [])
                    n = sum(r['alerts'] for r in rs)
                    med = lambda v: '%5.1f s' % float(np.median(v)) if v else '   --'
                    print('%-10s %-8s %8g  %4d/%-4d  %s / %-12s %-14s %d' % (
                        preset, framing, rate, len(on), n, med(on), ('%5.1f s' % max(on)) if on else '--',
                        med(off), sum(r['false'] for r in rs)), flush=True)
        return
    print('%-10s %-8s %8s  %7s %6s %6s %8s%s' % ('preset', 'format', 'bit/s', 'groups', 'PS s', 'RT s', 'wrong',
                                         '   data AM: median / worst 10% / worst s' if a.audibility else ''))
    cases = [(f, r) for f in a.formats.split(',') for r in rates]
    for preset in a.presets.split(','):
        for framing, rate in cases:
            rs = [run(preset, rate, s + 1, a.secs, a.cn, fmt=framing) for s in range(a.seeds)]
            g = np.mean([r['groups'] for r in rs])
            ps = [r['ps_t'] for r in rs if r['ps_t'] is not None]
            rt = [r['rt_t'] for r in rs if r['rt_t'] is not None]
            line = '%-10s %-8s %8g  %6.0f%% %6s %6s %4d/%-3d' % (
                preset, framing, rate, g, fmt(np.mean(ps) if len(ps) == len(rs) else None),
                fmt(np.mean(rt) if len(rt) == len(rs) else None), sum(r['shown'] for r in rs),
                sum(r['wrong'] for r in rs))
            if a.audibility:
                aud, prog = [], []
                for s in range(a.seeds):             # noise off: it would only show the noise turning
                    on = run(preset, rate, s + 1, a.secs, 99.0, keep_env=True, fmt=framing)
                    off = run(preset, rate, s + 1, a.secs, 99.0, data_on=False, keep_env=True, fmt=framing)
                    aud.append(audibility(on['env'], off['env']))
                    prog.append(program_level(off['env']))
                m = np.mean(aud, axis=0)
                line += '   %6.1f / %6.1f / %6.1f dB   (program %5.1f dB)' % (tuple(m) + (np.mean(prog),))
            print(line, flush=True)
    print('PS / RT "--" means at least one run never showed the whole thing.')


if __name__ == '__main__':
    main()
