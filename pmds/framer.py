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
PMDS framers: block sync, single-bit correction and group parsing, for one framing each.

A demodulator (pmds.demod) recovers bits and feeds each one to two framers at once: the compact
PMDS format and RBDS-native groups. Whichever framer holds block sync is the one a receiver
shows; the other one just never finds sync.
"""
from collections import deque

from .codec import G0, END, OFFSET, syndrome, RDS_OFFSET, rds_syndrome, af_freq, isrc_unpack


def _bytes(v, n):
    return [(v >> (8 * (n - 1 - i))) & 0xFF for i in range(n)]


def _text(codes):
    return ''.join(G0[c] or ' ' for c in codes)


class Framer:
    """Block sync, single-bit correction and group parsing for one framing. Read the public
    fields from any thread; the stats copy their deques before reading them."""
    LOSE_SYNC = (7, 10)       # 7 bad blocks out of the last 10: start looking again
    ALERT_HOLD = 20.0         # an alert nobody has confirmed for this long times out (seconds)
    fmt, N = '', 0

    def __init__(self, dec):
        self.dec = dec
        self.strict = False   # True: no correction at all, every damaged block counts as lost
        self.reset()

    # ---- state ----
    def reset(self):
        self.mask = (1 << self.N) - 1
        self.reg, self.nb = 0, 0
        self.synced, self.cands, self.next_nb, self.held = False, {}, 0, None
        self.results = deque(maxlen=50)          # recent blocks in sync: 0 clean, 1 fixed, 2 lost
        self.block_log = deque(maxlen=600)       # (time, 'clean' | 'fixed' | 'lost' | 'sync' | 'nosync')
        self.counts = {'clean': 0, 'fixed': 0, 'lost': 0}
        self.group_t = deque(maxlen=64)
        self.groups, self.last_group_t = 0, -1.0
        self.pi = self.ps = self.pty = self.tp = self.ta = self.af = None
        self.alert, self.alert_t = 0, None        # 0 none, 1 test (PTY 30), 2 emergency (PTY 31)
        self.alert_tier = None
        self._alert_cand, self._alert_off, self._alert_last = False, 0, -1e9
        self.facility_id, self.af_list, self.clock, self.isrc = None, [], None, None
        self.rtplus, self.artist, self.title = None, None, None
        self._ext_cand = {}
        self.rt = ''
        self._pi_cand = None
        self._ps_part, self._ps_cand = {}, {}
        self._rt_segs, self._ab = {}, None
        self._expect = None
        self._group = {}

    # ---- shared with the decoder ----
    @property
    def bit_rate(self):
        return self.dec.bit_rate

    def now(self):
        return self.dec.now()

    def dev_deg(self):
        return self.dec.dev_deg()

    def snr_db(self):
        return self.dec.snr_db()

    def rate(self):
        now = self.now()
        return sum(1 for g in list(self.group_t) if g > now - 20.0) / 20.0

    def bler(self):
        r = list(self.results)
        return 100.0 * sum(1 for x in r if x == 2) / len(r) if r else 0.0

    def fixed(self):
        r = list(self.results)
        return 100.0 * sum(1 for x in r if x == 1) / len(r) if r else 0.0

    def recent(self, secs=60.0):
        """Counts of clean / fixed / lost blocks over the last secs."""
        t0 = self.now() - secs
        c = {'clean': 0, 'fixed': 0, 'lost': 0}
        for t, s in list(self.block_log):
            if t >= t0 and s in c:
                c[s] += 1
        return c

    def _mark(self, status):
        self.results.append({'clean': 0, 'fixed': 1, 'lost': 2}[status])
        self.counts[status] += 1
        self.block_log.append((self.now(), status))

    def _sync(self, on):
        if on != self.synced:
            self.block_log.append((self.now(), 'sync' if on else 'nosync'))
        self.synced = on

    def _log(self, kind, fields):
        if self.dec.log:
            self.dec.log(self, kind, fields)

    # ---- blocks ----
    def push(self, bit):
        self.reg = ((self.reg << 1) | bit) & self.mask
        self.nb += 1
        if self.nb >= self.N:
            self._block()

    def _block(self):
        nb, reg = self.nb, self.reg
        s = self.syndrome(reg)
        kind = self.KIND.get(s)
        if not self.synced:
            if kind:
                prev = self.cands.get(nb - self.N)
                if prev and kind in self.after(prev[0]):          # two in a row: probably sync,
                    self.next_nb = nb + self.N                       # held until the next block checks out
                    self.results.clear()
                    self.held = [prev, (kind, reg >> self.K)]
                    self._expect = self.after(kind)
                    self.cands.clear()
                    self._sync(True)
                    return
                self.cands[nb] = (kind, reg >> self.K)
            for k in [k for k in self.cands if k < nb - self.N]:
                del self.cands[k]
            return
        if nb < self.next_nb:
            return
        self.next_nb = nb + self.N
        want = self._expect or tuple(self.KIND.values())
        if self.held is not None:                    # the block after acquiring sync must be clean
            held, self.held = self.held, None
            if kind not in want:
                self._sync(False)
                return
            for k, data in held:
                self._mark('clean')
                self._take(k, data, False)
        if kind in want:
            self._mark('clean')
            self._take(kind, reg >> self.K, False)
        else:
            hits = [] if self.strict else [(k, self.SINGLE[s ^ self.OFFSET[k]]) for k in want
                                              if (s ^ self.OFFSET[k]) in self.SINGLE]
            if len(hits) == 1:
                k, j = hits[0]
                self._mark('fixed')
                self._take(k, (reg ^ (1 << j)) >> self.K, True)
            else:
                self._mark('lost')
                self._miss()
        bad, of = self.LOSE_SYNC
        recent = list(self.results)[-of:]
        if len(recent) >= of and sum(1 for x in recent if x == 2) >= bad:
            self._sync(False)
            self.held, self.cands, self._expect, self._group = None, {}, None, {}

    # ---- groups: the parts both framings share ----
    def _station(self, pi, fixed):
        """PI handling: a corrected group has to agree with the previous one."""
        if not fixed or pi == self._pi_cand:
            if self.pi is not None and pi != self.pi:       # another station: drop what we had
                self.ps, self.rt, self._rt_segs, self._ab = None, '', {}, None
                self._ps_part, self._ps_cand = {}, {}
            self.pi = pi
        self._pi_cand = pi
        return pi == self.pi

    def _ps(self, seg, text, nparts, fixed):
        if fixed and text != self._ps_cand.get(seg):
            self._ps_cand[seg] = text
            return False
        self._ps_cand[seg] = text
        self._ps_part[seg] = text
        if all(i in self._ps_part for i in range(nparts)):
            self.ps = ''.join(self._ps_part[i] for i in range(nparts))
        return True

    def _rt(self, seg, ab, codes, nsegs):
        if ab != self._ab:                            # new RadioText: start over
            self._rt_segs, self._ab = {}, ab
            self.rtplus = None                        # old RT+ tags pointed into the old text;
                                                      # artist and title stay until new tags come
        self._rt_segs[seg] = codes
        text = []
        for s in range(nsegs):                         # in order, up to the first gap or the end mark
            c = self._rt_segs.get(s)
            if c is None:
                break
            if END in c:
                text += c[:c.index(END)]
                break
            text += c
        self.rt = _text(text).rstrip()

    def _alert_seen(self, on, level, fixed):
        """Alert on: one clean group (or two repaired ones) with the flag and PTY 30/31.
        Off: two groups in a row without it, so one bad block can't end an alert."""
        if on:
            if not fixed or self._alert_cand:
                if not self.alert:
                    self.alert_t = self.now()
                self.alert = level
                self._alert_last = self.now()
            self._alert_cand, self._alert_off = True, 0
        else:
            self._alert_cand = False
            if self.alert:
                self._alert_off += 1
                if self._alert_off >= 2:
                    self.alert, self._alert_off = 0, 0

    def alert_tick(self):
        """Called every bit: an alert that hasn't been confirmed for ALERT_HOLD ends on its own."""
        if self.alert and self.now() - self._alert_last > self.ALERT_HOLD:
            self.alert, self._alert_off = 0, 0

    def _counted(self):
        self.groups += 1
        self.last_group_t = self.now()
        self.group_t.append(self.last_group_t)


class CompactFramer(Framer):
    """Our compact format: 36 + 11 bit blocks, two blocks to a group."""
    fmt, N, K = 'compact', 47, 11
    OFFSET = OFFSET
    KIND = {v: k for k, v in OFFSET.items()}
    SINGLE = {syndrome(1 << j): j for j in range(47)}

    @staticmethod
    def syndrome(v):
        return syndrome(v)

    @staticmethod
    def after(kind):
        if kind.endswith('1'):
            return (kind[:-1] + '2',)
        return ('core1', 'rt1', 'ext1')

    def _miss(self):
        self._group = {}
        if self._expect is not None:                  # the position still moves on
            self._expect = ('core2', 'rt2', 'ext2') if self._expect[0].endswith('1') else ('core1', 'rt1', 'ext1')

    def _take(self, kind, data, fixed):
        self._expect = self.after(kind)
        if kind.endswith('1'):
            self._group = {'kind': kind[:-1], 'd1': data, 'fixed': fixed}
            return
        g, self._group = self._group, {}
        if g.get('kind') == kind[:-1]:
            self._parse(g['kind'], g['d1'], data, g['fixed'] or fixed)

    def _parse(self, kind, d1, d2, fixed):
        self._counted()
        if kind == 'core':
            pi, seg = d1 >> 20, (d1 >> 11) & 1
            half = _text(_bytes(d2 >> 4, 4))
            pty, flag = (d1 >> 15) & 31, (d1 >> 10) & 1
            if self._station(pi, fixed):
                if self._ps(seg, half, 2, fixed):
                    self.pty, self.tp, self.ta, self.af = pty, (d1 >> 14) & 1, (d1 >> 13) & 1, (d1 >> 12) & 1
                self._alert_seen(flag and pty in (30, 31), 2 if pty == 31 else 1, fixed)
            self._log('core', dict(pi=pi, seg=seg, half=half, fixed=fixed, ps=self.ps, pty=pty,
                                   tp=(d1 >> 14) & 1, ta=(d1 >> 13) & 1, alert=flag, tier=0))
        elif kind == 'rt':
            seg, ab = (d1 >> 33) & 7, (d1 >> 32) & 1
            codes = _bytes(d1, 4) + _bytes(d2 >> 4, 4)
            self._rt(seg, ab, codes, 8)
            self._tags()
            self._log('rt', dict(seg=seg, ab=ab, fixed=fixed, text=_text(codes), rt=self.rt))
        elif kind == 'ext':
            self._ext((d1 >> 32) & 15, ((d1 & 0xFFFFFFFF) << 36) | d2, fixed)
        else:
            self._log(kind, dict(d1=d1, d2=d2, fixed=fixed))

    def _ext(self, typ, v, fixed):
        if fixed and self._ext_cand.get(typ) != v:          # a repaired group has to repeat first
            self._ext_cand[typ] = v
            return
        self._ext_cand[typ] = v
        if typ == 0:
            self.facility_id = (v >> 44) & 0xFFFFFF
            info = 'facility ID %d' % self.facility_id
        elif typ == 1:
            cnt = min(6, (v >> 65) & 7)
            self.af_list = [af_freq((v >> (56 - 9 * i)) & 0x1FF) for i in range(cnt)]
            info = 'AF ' + ', '.join(self.af_list)
        elif typ == 2:
            import datetime as _dt
            mjd, hh, mm = (v >> 51) & 0x1FFFF, (v >> 46) & 31, (v >> 40) & 63
            off = ((v >> 34) & 31) * (-1 if (v >> 39) & 1 else 1)
            try:
                day = _dt.date(1858, 11, 17) + _dt.timedelta(days=mjd)
                self.clock = '%s %02d:%02d UTC (local %+g h)' % (day.isoformat(), hh, mm, off / 2.0)
            except (OverflowError, ValueError):
                self.clock = None
            info = 'clock %s' % self.clock
        elif typ == 3:
            l2 = (v >> 31) & 31
            self.rtplus = [((v >> 60) & 63, (v >> 54) & 63, ((v >> 48) & 63) + 1),
                           ((v >> 42) & 63, (v >> 36) & 63, l2 + 1)]
            self._tags()
            info = 'RT+ artist "%s" title "%s"' % (self.artist or '', self.title or '')
        elif typ == 4:
            self.isrc = isrc_unpack(v >> 16)
            info = 'ISRC %s' % self.isrc
        else:
            info = 'type %d' % typ
        self._log('ext', dict(type=typ, info=info, fixed=fixed))

    def _tags(self):
        """Artist and title from the RT+ tags into the current RadioText."""
        if not self.rtplus or not self.rt:
            return
        for ct, st, ln in self.rtplus:
            part = self.rt[st:st + ln].strip() if ct else ''
            if ct == 4 and part:
                self.artist = part
            elif ct == 1 and part:
                self.title = part


class RbdsFramer(Framer):
    """Real RBDS: 16 + 10 bit blocks A, B, C (or C'), D; groups 0A/0B and 2A parsed."""
    fmt, N, K = 'rbds', 26, 10
    OFFSET = RDS_OFFSET
    KIND = {v: k for k, v in RDS_OFFSET.items()}
    SINGLE = {rds_syndrome(1 << j): j for j in range(26)}
    _NEXT = {'A': ('B',), 'B': ('C', 'Cp'), 'C': ('D',), 'Cp': ('D',), 'D': ('A',)}

    @staticmethod
    def syndrome(v):
        return rds_syndrome(v)

    @classmethod
    def after(cls, kind):
        return cls._NEXT[kind]

    def _miss(self):
        # a lost block still moves the position on, so the rest of the group lines up
        if not self._expect:
            return
        x = self._expect[0]
        self._expect = self.after(x)
        if x == 'D':
            self._finish()

    def _take(self, kind, data, fixed):
        self._expect = self.after(kind)
        if kind == 'A':
            self._group = {}
        g = self._group
        g[kind] = data
        g['fixed'] = g.get('fixed', False) or fixed
        if kind == 'D':
            self._finish()

    def _finish(self):
        g, self._group = self._group, {}
        b = g.get('B')
        pi = g.get('A', g.get('Cp'))
        if b is None or pi is None:
            return
        fixed = g.get('fixed', False)
        gt, ver, tp, pty, low = (b >> 12) & 15, (b >> 11) & 1, (b >> 10) & 1, (b >> 5) & 31, b & 31
        name = '%d%s' % (gt, 'AB'[ver])
        if gt == 0:                                   # counted only when it carries usable data,
            seg = low & 3                             # the same rule as a compact group
            d = g.get('D')
            if d is None:
                return
            self._counted()
            part = _text(_bytes(d, 2))
            if self._station(pi, fixed):
                if self._ps(seg, part, 4, fixed):
                    self.pty, self.tp, self.ta = pty, tp, (low >> 4) & 1
                self._alert_seen(pty in (30, 31), 2 if pty == 31 else 1, fixed)
            self._log('core', dict(pi=pi, seg=seg, half=part, fixed=fixed, ps=self.ps, pty=pty, tp=tp,
                                   ta=(low >> 4) & 1, alert=1 if pty in (30, 31) else 0, tier=0, group=name))
        elif gt == 2 and ver == 0 and 'C' in g and 'D' in g:
            self._counted()
            seg, ab = low & 15, (low >> 4) & 1
            codes = _bytes(g['C'], 2) + _bytes(g['D'], 2)
            self._station(pi, fixed)
            self._rt(seg, ab, codes, 16)
            self._log('rt', dict(seg=seg, ab=ab, fixed=fixed, text=_text(codes), rt=self.rt, group=name))
        elif 'D' in g:
            self._counted()
            self._log(name, dict(d1=b, d2=g['D'], fixed=fixed))
