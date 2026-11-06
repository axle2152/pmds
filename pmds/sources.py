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
PMDS text sources: the RadioText rotation line and now-playing files.

rt_program style rotation (Stereo Tool's RDS-text style), for example
    2t:\r"C:\np.txt"/6s:\r"C:\temp.txt"/4s:Tomorrow's Forecast/2t:<\r"C:\hi.txt"
'/' separates parts; 'Nt:' sends a part N whole times, 'Ns:' shows it for at least N seconds;
every part goes out whole at least twice, so a long text simply stays up longer at AM's speed.
\r"file" and \f"file" insert a file's text as it is, \R and \F in capitals (a .json file gives
'artist - title'). Scroll marks (<) and word breaks (||) are ignored: RadioText doesn't scroll.
"""
def parse_rt_program(line):
    """A Stereo Tool style RDS text line into parts: [(mode, n, pieces)], mode 's' (seconds)
    or 't' (times), pieces = [('text', str) | ('file', (letter, path))]."""
    import re
    parts, cur, i, quote = [], '', 0, False
    while i < len(line):                                   # split on '/', but not inside \r"..."
        c = line[i]
        if not quote and c == '\\' and i + 2 < len(line) and line[i + 1] in 'rRfF' and line[i + 2] == '"':
            cur += line[i:i + 3]
            i += 3
            quote = True
            continue
        if quote and c == '"':
            quote = False
        elif not quote and c == '/':
            parts.append(cur)
            cur = ''
            i += 1
            continue
        cur += c
        i += 1
    parts.append(cur)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        mode, n = 's', 1.0                                 # Stereo Tool's default: 1 second
        m = re.match(r'(\d+(?:\.\d+)?)([st]):', p)
        if m:
            mode, n, p = m.group(2), float(m.group(1)), p[m.end():]
        else:
            m = re.match(r'[\d.,=\-st]+:', p)               # per-word timings: not used on RadioText
            if m:
                p = p[m.end():]
        p = p.replace('||', ' ').replace('\\<', '').lstrip('<')
        pieces, pos = [], 0
        for f in re.finditer(r'\\([rRfF])"([^"]*)"', p):
            if f.start() > pos:
                pieces.append(('text', p[pos:f.start()]))
            pieces.append(('file', (f.group(1), f.group(2))))
            pos = f.end()
        if pos < len(p):
            pieces.append(('text', p[pos:]))
        out.append((mode, n, pieces))
    return out


def now_playing_json(raw):
    """powerfm_metadata.py's nowplaying.json: artist, title and (if present) isrc."""
    import json
    try:
        d = json.loads(raw)
    except ValueError:
        return raw, (None, None, None)
    artist, title = str(d.get('artist') or '').strip(), str(d.get('title') or '').strip()
    text = '%s - %s' % (artist, title) if artist and title else (title or artist)
    return text, (artist or None, title or None, str(d.get('isrc') or '').strip() or None)


def read_text(path):
    with open(path, 'rb') as f:
        raw = f.read(4096)
    for enc in ('utf-8-sig', 'cp1252'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode('latin-1')

