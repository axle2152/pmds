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
r"""
PMDS encoder: the group schedule and the phase waveform, with no GNU Radio dependency.

PMDS (Phase Modulation Data Service, working name) carries RDS-style station data on the phase
of a mono AM carrier. Encoder.modulate(x) takes complex baseband from the AM modulator (mono AM:
a real, positive envelope) and returns y = x * e^(j*theta): the envelope is untouched, so
envelope detectors see nothing. The GNU Radio block in pmds_encoder.py is a thin wrapper.

Physical layer
  biphase, one sine cycle per bit: a 1 swings the phase + then -, a 0 swings it - then +.
  Phase is zero at every bit boundary and there is no energy at DC.
  bit_rate  : 23.4375, 46.875, 93.75 or 187.5 bit/s
  samp_rate : a whole multiple of the bit rate (192 kHz, 96 kHz and 48 kHz are; 44.1 kHz and
              2 Msps are not). A bit is a whole number of samples, so any other rate puts the
              bit rate off; past the specification's 50 ppm the encoder refuses to run
              (ValueError). Set strict_rate = False to get a warning instead, as the GNU Radio
              block does.
  deviation : peak phase in degrees

Chosen operating point: compact framing, 93.75 bit/s, 8.6 deg (the defaults). 8.6 deg keeps
the synchronous-detector tone 45 dB below 100% modulation. The other rates
and the RBDS-native framing ('rbds') stay available for comparison on the bench. Group
layouts are in pmds.codec.

Alerts: alert = 1 (test, PTY 30) or 2 (emergency, PTY 31) sets the alert flag; RadioText then
carries the alert text (64-character pages, each sent twice) and extended groups pause.

Text sources (checked once a second while started)
  ps_file    : if set and readable, its first 8 characters replace ps (show names, etc.)
  rt_file    : if set and readable, its text replaces rt (RadioDJ's Now_Playing.txt, or a
               .json now-playing file giving artist and title)
  rt_program : a file holding a rotation line in Stereo Tool's RDS-text style (it overrides
               rt and rt_file); the format is described in pmds.sources
  alert_file : if set and readable, its text replaces alert_text
"""
import os
import threading
import time

import numpy as np

from .codec import (RT_MAX, AF_MAX, callsign_to_pi, text_to_codes, codes_to_text, core_group,
                    rt_segments, rt_group, ext_station, af_code, ext_af, ext_clock, ext_rtplus,
                    rtplus_tags, blocks_to_bits, rbds_0a, rbds_rt_segments, rbds_2a)
from .sources import parse_rt_program, now_playing_json, read_text


class Encoder:
    """PMDS encoder. Same parameters as the GNU Radio block. start() begins polling the text
    files, modulate(x) adds the data to each run of samples, stop() ends the polling."""

    RATE_PPM = 50.0           # the specification's limit on the bit rate
    strict_rate = True        # a sample rate that breaks it: ValueError (False: a warning)

    def __init__(self, samp_rate=192000, data_on=1, deviation=8.6, bit_rate=93.75, fmt='compact',
                 call='WAMD', pi='', pty=4, tp=0, ta=0, ps='AM 1710', ps_upper=1, ps_file='',
                 rt='', rt_file='C:/RadioDJv2/Now_Playing.txt', rt_len=64, rt_every=1,
                 facility_id=0, af='', ext_every=8,
                 alert=0, alert_text='This is a test of the AM data alert flag. This is only a test.',
                 alert_file='', rt_program=''):
        self.samp_rate = samp_rate
        self.data_on = data_on
        self.deviation = deviation
        self.bit_rate = bit_rate
        self.fmt = fmt
        self.call = call
        self.pi = pi
        self.pty = pty
        self.tp = tp
        self.ta = ta
        self.ps = ps
        self.ps_upper = ps_upper
        self.ps_file = ps_file
        self.rt = rt
        self.rt_file = rt_file
        self.rt_len = rt_len
        self.rt_every = rt_every
        self.facility_id = facility_id
        self.af = af
        self.ext_every = ext_every
        self.alert = alert                       # 0 off, 1 test (PTY 30), 2 emergency (PTY 31)
        self.alert_text = alert_text
        self.alert_file = alert_file
        self._file_alert = None
        self.rt_program = rt_program
        self._file_prog = None                    # the rotation line read from rt_program
        self._prog_key, self._prog_parts, self._prog_i, self._prog_t0 = None, [], 0, 0.0
        self._inc_cache = {}                      # included file -> (stamp, text, meta)
        self._rtp_key = None                      # (artist, title) the RT+ item toggle follows
        self._rt_meta = (None, None)             # artist, title from a JSON now-playing file
        self._rtp_toggle, self._rtp_pending = 0, 0
        self._clock_min, self._ext_i = None, 0
        self._rate_warned = None
        self._page, self._passes, self._alert_on = 0, 0, False

        self._lock = threading.Lock()
        self._file_ps = None                     # text read from ps_file / rt_file, None = not in use
        self._file_rt = None
        self._rt_key, self._ab = None, 0         # A/B flips whenever the RadioText changes
        self._seq, self._seg, self._ps_seg, self._slot = 0, 0, 0, 0
        self._wave = np.zeros(0, np.float32)     # unit phase waveform of the current group
        self._pos = 0
        self._stop = threading.Event()
        self._thread = None
        self.quiet = False                       # True: no console messages (simulator use)
        self.last_group = None                   # (kind, blocks) of the group on the air
        self._ext_turn = False                   # extended slots: news and rotation take turns

    # ---- station fields ----------------------------------------------------------------
    def station_pi(self):
        p = str(self.pi).strip()
        if p:
            try:
                return int(p, 16) & 0xFFFF
            except ValueError:
                pass
        return callsign_to_pi(self.call) or 0

    def _ps_codes(self):
        with self._lock:
            src = self._file_ps if self._file_ps is not None else self.ps
        return (text_to_codes(src, bool(int(self.ps_upper))) + [0x20] * 8)[:8]

    def _alert_level(self):
        try:
            return max(0, min(2, int(self.alert)))
        except (TypeError, ValueError):
            return 0

    def _alert_pages(self):
        with self._lock:
            src = self._file_alert if self._file_alert is not None else self.alert_text
        words, pages, cur = ' '.join(str(src).split()).split(' '), [], ''
        for w in words:                                  # 64-character pages, broken between words
            if cur and len(text_to_codes(cur + ' ' + w)) > RT_MAX:
                pages.append(cur)
                cur = w
            else:
                cur = (cur + ' ' + w).strip()
        if cur:
            pages.append(cur)
        return pages or ['']

    def _rt_text(self):
        """The RadioText now: the alert's current page during an alert, else the current part of
        the rotation, else the program text."""
        if self._alert_level():
            pages = self._alert_pages()
            return pages[self._page % len(pages)]
        parts = self._program()
        if parts:
            return self._part_text(parts, self._prog_i)[0]
        with self._lock:
            return self._file_rt if self._file_rt is not None else self.rt

    # ---- the rotation (Stereo Tool style) ----
    def _program(self):
        with self._lock:
            line = self._file_prog
        line = (line or '').strip()
        if line != self._prog_key:                    # a new or edited rotation: start at its top
            self._prog_key, self._prog_parts = line, parse_rt_program(line) if line else []
            self._prog_i, self._prog_t0 = 0, self._gtime()
        return self._prog_parts

    def _include(self, path):
        try:
            st = os.stat(path)
        except OSError:
            return '', (None, None)
        stamp = (st.st_mtime_ns, st.st_size)
        hit = self._inc_cache.get(path)
        if hit and hit[0] == stamp:
            return hit[1], hit[2]
        try:
            text = read_text(path)
        except OSError:
            return '', (None, None)
        meta = (None, None)
        if path.lower().endswith('.json'):
            text, meta = now_playing_json(text)
        text = ' '.join(text.split())
        self._inc_cache[path] = (stamp, text, meta)
        return text, meta

    def _part_text(self, parts, i):
        """The text of part i with its files read in, and any artist/title a .json gave."""
        mode, n, pieces = parts[i % len(parts)]
        out, meta = [], (None, None)
        for kind, val in pieces:
            if kind == 'text':
                out.append(val)
            else:
                text, m = self._include(val[1])
                if m != (None, None):
                    meta = m
                out.append(text.upper() if val[0] in 'RF' else text)
        return ' '.join(''.join(out).split()), meta

    def _gtime(self):
        return self._seq * 94.0 / max(float(self.bit_rate), 1e-6)

    def _part_done(self):
        """After a whole transmission of the current part: has it had its time or its count?"""
        parts = self._prog_parts
        if not parts:
            return False
        mode, n, _ = parts[self._prog_i % len(parts)]
        if mode == 't':
            return self._passes >= max(1, int(n))
        return self._passes >= 2 and self._gtime() - self._prog_t0 >= n

    def _next_part(self):
        parts = self._prog_parts
        for step in range(1, len(parts) + 1):        # skip parts whose files are empty
            j = (self._prog_i + step) % len(parts)
            if self._part_text(parts, j)[0] or step == len(parts):
                self._prog_i, self._prog_t0 = j, self._gtime()
                return

    def _rt_codes(self):
        src = self._rt_text()
        codes = text_to_codes(src)[:max(0, min(int(self.rt_len), RT_MAX))]
        key = tuple(codes)
        if key != self._rt_key:
            if self._rt_key is not None:
                self._ab ^= 1
            self._rt_key, self._seg, self._passes = key, 0, 0
            self._rtp_pending = 2                          # RT+ for the new text, twice
            if not self.quiet:
                print('PMDS: RT %s "%s"' % ('AB'[self._ab], codes_to_text(codes)), flush=True)
        return codes

    def _af_entries(self):
        out = []
        for part in str(self.af or '').replace(';', ',').split(','):
            try:
                e = af_code(part.strip()) if part.strip() else None
            except ValueError:
                e = None
            if e is not None:
                out.append(e)
        return out[:AF_MAX]

    def _next_ext(self):
        """The next extended group, or None. Slots alternate between news (the clock on each new
        minute, new RT+) and the rotation (station ID, AF, RT+), so a song change can't hold
        up the station ID for long. Every one carries the station's PI."""
        pi = self.station_pi()
        rt = codes_to_text(self._rt_codes())
        with self._lock:
            artist, title = self._rt_meta
        if self._prog_parts:                               # the rotation's current part, if a .json
            artist, title = self._part_text(self._prog_parts, self._prog_i)[1]
        tags = rtplus_tags(rt, artist, title)
        item = tuple(sorted(rt[st:st + ln] for _, st, ln in tags)) if tags else None
        if item and item != self._rtp_key:                 # a new song: the item toggle flips
            self._rtp_key = item
            self._rtp_toggle ^= 1

        def rtplus():
            return ext_rtplus(pi, self._rtp_toggle, 1, *(tags + [None, None])[:2])

        def news():
            minute = time.gmtime().tm_min
            if minute != self._clock_min:
                self._clock_min = minute
                return 'clock', ext_clock(pi)
            if self._rtp_pending and tags:
                self._rtp_pending -= 1
                return 'rt+', rtplus()
            return None

        def rotation():
            rota = []
            if int(self.facility_id or 0):
                rota.append(('station', lambda: ext_station(pi, int(self.facility_id))))
            if self._af_entries():
                rota.append(('af', lambda: ext_af(pi, self._af_entries())))
            if tags:
                rota.append(('rt+', rtplus))
            if not rota:
                return None
            name, make = rota[self._ext_i % len(rota)]
            self._ext_i += 1
            return name, make()

        self._ext_turn = not getattr(self, '_ext_turn', False)
        first, second = (news, rotation) if self._ext_turn else (rotation, news)
        return first() or second()

    def next_group(self):
        """The next group: N core groups (PS parts in turn), then one RT segment.
        Returns (kind, blocks, bits per block)."""
        if str(self.fmt).lower().startswith('rbds'):
            return self._next_rbds()
        level = self._alert_level()
        if bool(level) != self._alert_on:                  # alert starts or ends: text starts over
            self._alert_on, self._page, self._passes = bool(level), 0, 0
        self._seq += 1
        every = int(self.ext_every or 0)
        if not level and every > 0 and self._seq % every == 0:
            ext = self._next_ext()
            if ext:
                return ext[0], ext[1], 47
        segs = rt_segments(self._rt_codes(), self.rt_len)
        if segs and int(self.rt_every) > 0 and self._slot % (int(self.rt_every) + 1) == int(self.rt_every):
            self._seg %= len(segs)
            kind, blocks = 'rt%d' % self._seg, rt_group(self._seg, self._ab, segs[self._seg], level)
            self._seg += 1
            if self._seg >= len(segs):                     # a whole pass of the text
                self._passes += 1
                if level and self._passes >= 2:            # alert pages: each sent twice, then the next
                    self._page += 1
                    self._passes = 0
                elif not level and self._part_done():      # the rotation moves on
                    self._next_part()
        else:
            s = self._ps_seg
            pty = (30 if level == 1 else 31) if level else int(self.pty)
            kind, blocks = 'core%d' % s, core_group(
                self.station_pi(), pty, int(self.tp), int(self.ta), 1 if self._af_entries() else 0, s,
                self._ps_codes(), 1 if level else 0)
            self._ps_seg ^= 1
        self._slot += 1
        return kind, blocks, 47

    def _next_rbds(self):
        codes = self._rt_codes()
        segs = rbds_rt_segments(codes, self.rt_len)
        every = int(self.rt_every)
        pi, tp = self.station_pi(), int(self.tp)
        level = self._alert_level()
        pty = (30 if level == 1 else 31) if level else int(self.pty)   # RBDS: 31 Emergency, 30 Test
        if segs and every > 0 and self._seq % (every + 1) == every:
            self._seg %= len(segs)
            kind, blocks = '2A/%d' % self._seg, rbds_2a(pi, pty, tp, self._ab, self._seg, segs[self._seg])
            self._seg += 1
        else:
            s = self._ps_seg % 4
            kind, blocks = '0A/%d' % s, rbds_0a(pi, pty, tp, int(self.ta), 1, s, self._ps_codes())
            self._ps_seg = (s + 1) % 4
        self._seq += 1
        return kind, blocks, 26

    # ---- waveform ----------------------------------------------------------------------
    def _spb(self):
        """Samples per bit. A bit is a whole number of samples, so a sample rate that is not a
        whole multiple of the bit rate puts the bit rate off: 44.1 kHz by 851 ppm."""
        exact = float(self.samp_rate) / max(float(self.bit_rate), 1e-6)
        spb = max(16, int(round(exact)))
        ppm = (exact / spb - 1.0) * 1e6
        if abs(ppm) > self.RATE_PPM:
            msg = ('PMDS: at %g samples/s the bit rate would be %.5g bit/s, %+.0f ppm off %g (the '
                   'specification allows %g ppm). Use a whole multiple of the bit rate: 192000, '
                   '96000 or 48000.' % (float(self.samp_rate), float(self.samp_rate) / spb, ppm,
                                        float(self.bit_rate), self.RATE_PPM))
            if self.strict_rate:
                raise ValueError(msg)
            if self._rate_warned != (self.samp_rate, self.bit_rate):
                self._rate_warned = (self.samp_rate, self.bit_rate)
                print('WARNING ' + msg, flush=True)
        return spb

    def _build(self):
        kind, blocks, nbits = self.next_group()
        self.last_group = (kind, blocks)
        spb = self._spb()
        tmpl = np.sin(2 * np.pi * np.arange(spb) / spb).astype(np.float32)
        sign = (2 * blocks_to_bits(blocks, nbits) - 1).astype(np.float32)
        self._wave, self._pos = (sign[:, None] * tmpl[None, :]).ravel(), 0

    def _take(self, n):
        out = np.empty(n, np.float32)
        i = 0
        while i < n:
            if self._pos >= len(self._wave):
                self._build()
            k = min(n - i, len(self._wave) - self._pos)
            out[i:i + k] = self._wave[self._pos:self._pos + k]
            self._pos += k
            i += k
        return out

    def phase(self, n):
        """The next n samples of the unit phase waveform (+/-1 at the peaks), float32."""
        return self._take(n)

    def modulate(self, x, out=None):
        """The next len(x) samples: x (complex baseband from the AM modulator) with the data
        added as phase, x * e^(j * deviation * phase). Writes into out if given."""
        x = np.asarray(x)
        n = len(x)
        theta = self._take(n)
        dev = np.deg2rad(float(self.deviation)) if int(self.data_on) else 0.0
        y = out if out is not None else np.empty(n, np.complex64)
        if dev == 0.0:
            y[:] = x
        else:
            y[:] = x * np.exp(1j * dev * theta).astype(np.complex64)
        return y

    # ---- text files --------------------------------------------------------------------
    def _poll_once(self, stamps):
        for attr, path in (('_file_ps', self.ps_file), ('_file_rt', self.rt_file),
                           ('_file_alert', self.alert_file), ('_file_prog', self.rt_program)):
            path = str(path or '').strip()
            try:
                st = os.stat(path) if path else None
            except OSError:
                st = None
            if st is None:
                with self._lock:
                    setattr(self, attr, None)
                stamps.pop(attr, None)
                continue
            stamp = (path, st.st_mtime_ns, st.st_size)
            if stamps.get(attr) == stamp:
                continue
            if stamps:
                time.sleep(0.2)                      # a change: let RadioDJ finish writing
            try:
                text = read_text(path)
            except OSError:
                continue
            stamps[attr] = stamp
            meta = (None, None)
            if attr == '_file_rt' and path.lower().endswith('.json'):
                text, meta = now_playing_json(text)
            with self._lock:
                setattr(self, attr, text)
                if attr == '_file_rt':
                    self._rt_meta = meta

    def _poll_files(self, stamps):
        while not self._stop.wait(1.0):
            self._poll_once(stamps)

    def start(self):
        self._spb()                                  # a sample rate that can't work: say so now
        if not self.quiet:
            print('PMDS: %s, PI %04X (%s), PTY %d, %.5g bit/s, +/-%g deg'
                  % (self.fmt, self.station_pi(), self.call, int(self.pty), float(self.bit_rate),
                     float(self.deviation)), flush=True)
        self._stop.clear()
        stamps = {}
        self._poll_once(stamps)                      # files read before the first group
        self._thread = threading.Thread(target=self._poll_files, args=(stamps,), daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        return True
