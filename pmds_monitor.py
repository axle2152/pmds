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
PMDS data monitor: what the decoder really sees, block by block.

Opened from the PMDS tuner (press I, or click the RDS detail line in the Advanced window).
  top line   station, format and bit rate of the framer the receiver is showing
  counts     blocks since tuning and over the last minute: clean / fixed (one bit repaired) / lost
  strip      the last 150 blocks, oldest left: green clean, amber fixed, red lost,
             blue tick = sync found, grey tick = sync lost
  strict     turns error correction off in every decoder, so the counts show the raw channel
             (a block that needed a repair counts as lost, and its data is not used)
  log        every group as it decodes
"""
import tkinter as tk
from collections import deque

from pmds.codec import pi_to_callsign

BG, FG, DIM = '#111111', '#cfeee8', '#8fbfb6'
COL = {'clean': '#2e9e62', 'fixed': '#d9a520', 'lost': '#c03a3a', 'sync': '#4a78d0', 'nosync': '#777777',
       'slip': '#a066d8'}
CELLS, CELL_W = 150, 5


class PmdsMonitor:
    def __init__(self, root, get_tb):
        self.root, self.get_tb = root, get_tb
        self.win = None
        self.lines = deque(maxlen=500)            # filled from the GNU Radio thread, drained here
        self._hooked = None

    # ---- window ----
    def toggle(self):
        if self.win is not None and self.win.winfo_exists():
            self.close()
        else:
            self.open()

    def open(self):
        w = self.win = tk.Toplevel(self.root)
        w.title('PMDS data monitor')
        w.configure(bg=BG)
        w.protocol('WM_DELETE_WINDOW', self.close)
        self.head, self.cnt = tk.StringVar(value='waiting for the AM receiver'), tk.StringVar(value='')
        tk.Label(w, textvariable=self.head, font=('Courier', 11, 'bold'), fg=FG, bg=BG,
                 anchor='w').pack(fill=tk.X, padx=10, pady=(10, 2))
        tk.Label(w, textvariable=self.cnt, font=('Courier', 9), fg=DIM, bg=BG, anchor='w',
                 justify=tk.LEFT).pack(fill=tk.X, padx=10)
        self.cv = tk.Canvas(w, width=CELLS * CELL_W + 4, height=34, bg='#000000', highlightthickness=0)
        self.cv.pack(padx=10, pady=(6, 2), anchor='w')
        row = tk.Frame(w, bg=BG)
        row.pack(fill=tk.X, padx=10)
        for name, label in (('clean', 'clean'), ('fixed', 'fixed (1 bit)'), ('lost', 'lost'),
                            ('sync', 'sync found'), ('nosync', 'sync lost'), ('slip', 'slip followed')):
            tk.Label(row, text='\u25a0', fg=COL[name], bg=BG, font=('Courier', 10)).pack(side=tk.LEFT)
            tk.Label(row, text=label + '   ', fg=DIM, bg=BG, font=('Courier', 8)).pack(side=tk.LEFT)
        self.strict = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text='Strict: no error correction', variable=self.strict, command=self._set_strict,
                       fg=FG, bg=BG, selectcolor='#222222', activebackground=BG, activeforeground=FG,
                       font=('Courier', 9)).pack(side=tk.RIGHT)
        self.txt = tk.Text(w, width=112, height=20, bg='#000000', fg='#9fd8cf', font=('Courier', 9),
                           insertbackground='#9fd8cf', relief=tk.FLAT)
        self.txt.pack(padx=10, pady=(6, 10), fill=tk.BOTH, expand=True)
        self._tick()

    def close(self):
        self._unhook()
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
        self.win = None

    # ---- receiver ----
    def _set_strict(self):
        tb = self.get_tb()
        if tb is not None and hasattr(tb, 'set_pmds_strict'):
            tb.set_pmds_strict(self.strict.get())

    def _hook(self, tb):
        if self._hooked is tb:
            return
        self._unhook()
        for d in tb.pmds:
            d.log = self._log
        self._hooked = tb
        tb.set_pmds_strict(self.strict.get())
        self.lines.append('--- receiver started ---')

    def _unhook(self):
        if self._hooked is not None:
            for d in self._hooked.pmds:
                if d.log == self._log:
                    d.log = None
        self._hooked = None

    def _log(self, fr, kind, f):                  # GNU Radio thread: build the line, queue it
        t = '%7.1f s  %-7s %-6g' % (fr.now(), fr.fmt, fr.bit_rate)
        fix = '  (1 bit fixed)' if f.get('fixed') else ''
        grp = f.get('group', '')
        if kind == 'core':
            call = pi_to_callsign(f['pi']) or '----'
            line = '%s %-3s PI %04X %-4s PTY %2d TP %d TA %d%s  PS[%d] "%s"%s' % (
                t, grp or 'ps', f['pi'], call, f['pty'], f['tp'], f['ta'],
                '  ALERT' if f.get('alert') else '', f['seg'], f['half'], fix)
        elif kind == 'rt':
            line = '%s %-3s RT[%d] %s "%s"%s' % (t, grp or 'rt', f['seg'], 'AB'[f['ab']],
                                                 f['text'].replace('\r', '|'), fix)
        elif kind == 'ext':
            line = '%s ext %s%s' % (t, f.get('info', ''), fix)
        else:
            line = '%s %s%s' % (t, kind, fix)
        self.lines.append(line)

    # ---- refresh ----
    def _tick(self):
        if self.win is None:
            return
        tb = self.get_tb()
        if tb is not None and hasattr(tb, 'pmds_framers'):
            self._hook(tb)
            fr = tb.pmds_best()
            if fr.pi is not None or fr.synced:
                pi = '%04X %s' % (fr.pi, pi_to_callsign(fr.pi) or '') if fr.pi is not None else 'no PI yet'
                self.head.set('%-16s "%s"   %s %g bit/s   %s' % (pi, fr.ps or '', fr.fmt, fr.bit_rate,
                                                               'IN SYNC' if fr.synced else 'no sync'))
            else:
                self.head.set('searching: 23.4 to 187.5 bit/s, compact and RBDS')
            c, r = fr.counts, fr.recent(60.0)
            tot, rt = max(1, sum(c.values())), max(1, sum(r.values()))
            pct = lambda d, k, n: 100.0 * d[k] / n
            self.cnt.set('since tune  %5d blocks   clean %5.1f%%   fixed %5.1f%%   lost %5.1f%%\n'
                         'last 60 s   %5d blocks   clean %5.1f%%   fixed %5.1f%%   lost %5.1f%%\n'
                         'groups %d (%.2f/s)   data %4.1f deg   SNR %4.1f dB   C/N in-band %s   slips %d   strict %s'
                         % (sum(c.values()), pct(c, 'clean', tot), pct(c, 'fixed', tot), pct(c, 'lost', tot),
                            sum(r.values()), pct(r, 'clean', rt), pct(r, 'fixed', rt), pct(r, 'lost', rt),
                            fr.groups, fr.rate(), fr.dev_deg(), fr.snr_db(),
                            '--' if fr.cn_db() is None else '%.1f dB' % fr.cn_db(), fr.slips_found,
                            'ON' if self.strict.get() else 'off'))
            self._strip(list(fr.block_log)[-CELLS:])
        drained = 0
        while self.lines and drained < 200:
            self.txt.insert(tk.END, self.lines.popleft() + '\n')
            drained += 1
        if drained:
            n = int(self.txt.index('end-1c').split('.')[0])
            if n > 1200:
                self.txt.delete('1.0', '%d.0' % (n - 1000))
            self.txt.see(tk.END)
        self.win.after(250, self._tick)

    def _strip(self, entries):
        cv = self.cv
        cv.delete('all')
        x = 2
        for _, s in entries:
            if s in ('sync', 'nosync', 'slip'):
                cv.create_rectangle(x, 1, x + 1, 33, fill=COL[s], outline='')
                x += 2
            else:
                cv.create_rectangle(x, 6, x + CELL_W - 2, 28, fill=COL[s], outline='')
                x += CELL_W
