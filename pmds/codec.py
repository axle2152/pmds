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
PMDS codec: the character set, check code, blocks and groups, with no signal processing.

PMDS (Phase Modulation Data Service, working name) carries RDS-style station data on the
phase of a mono AM carrier. This module turns fields into blocks and back; pmds.encoder and
pmds.demod handle the waveform.

Compact blocks and groups
  block  = 36 data bits + 11 check bits, MSB first. check = CRC(g = 0x8CF) XOR offset word;
           the offset says which block it is, which also gives the receiver block sync.
  group  = 2 blocks = 94 bits (1.0 s at 93.75 bit/s, 2.0 s at 46.875, 4.0 s at 23.4375)

  core   b1 [0x185]: PI 16 | PTY 5 | TP 1 | TA 1 | AF 1 | SEG 1 | ALERT 1 | spare 10
         b2 [0x3CB]: PS chars 4*SEG .. 4*SEG+3 (4 x 8 bits) | spare 4
  RT     b1 [0x066]: SEG 3 | A/B 1 | 4 chars
         b2 [0x1BF]: 4 chars | spare 2 | ALERT 2   (8 chars per segment, 8 segments = 64 chars;
                     ALERT 0 none, 1 test, 2 emergency, 3 reserved)
  ext    b1 [0x03D]: TYPE 4 | 32 payload bits
         b2 [0x007]: 36 payload bits          (68 payload bits per group)
           0 station ID  facility ID 24 | ECC 8 (0xA0 = USA)
           1 AF list     count 3 | up to 6 entries of 9 bits: band 1 (0 FM, 1 AM) | code 8
                         FM code = RDS AF code ((MHz - 87.5) x 10); AM code = (kHz - 530) / 10 + 1
           2 clock       MJD 17 | hour 5 | minute 6 (UTC) | offset sign 1 | half-hours 5 (RDS 4A layout)
           3 RT+         toggle 1 | running 1 | tag1 type 6, start 6, length-1 6 | tag2 type 6, start 6,
                         length-1 5 (the RT+ tag layout; 1 = title, 4 = artist)
           4 content ID  ISRC 52: country 2 x 5 | registrant 3 x 6 | year 7 | designation 17
           5-15 reserved
  Spare bits are sent as 0.
  ALERT: core groups carry a flag, 1 while an alert is on the air, with PTY 31 (RBDS Emergency)
  or 30 (Emergency Test); RadioText groups carry the level itself. Extended groups pause during
  an alert, so every group on the air then says so.

RBDS-native framing (kept for bench comparison): real RBDS groups, bit for bit: 26-bit blocks
(16 data + 10 check, the RDS code and offset words A, B, C, D), 104-bit groups. Group 0A (PI,
PTY, TP, TA, M/S, 2 PS characters) and 2A (RadioText, 4 characters).

Characters: the RDS/RBDS basic character set (IEC 62106, the G0 code table; the same table
RBDS uses), 8 bits each. 0x0D ends a RadioText shorter than 64 characters. Characters outside
the table lose their accent if the plain letter is in it, otherwise become a space.

The check polynomial, offset words, character table, PI derivation from US call letters and
field layouts follow the published RDS/RBDS standards (IEC 62106, NRSC-4) or are defined by
the PMDS draft specification.
"""
import time
import unicodedata

import numpy as np

POLY = 0x8CF                                  # x^11 + x^7 + x^6 + x^3 + x^2 + x + 1, dmin 4 at 47 bits
OFFSET = {'core1': 0x185, 'core2': 0x3CB, 'rt1': 0x066, 'rt2': 0x1BF, 'ext1': 0x03D, 'ext2': 0x007}
END = 0x0D                                    # RDS: carriage return ends a RadioText
RT_MAX = 64

# RDS/RBDS basic character set (G0), codes 0x20..0xFF. '\x00' marks an unused code.
# 0x8D and 0x9D/0xA4 are read as the German sharp s and the Turkish g-breve.
_G0_ROWS = (
    ' !"#\u00a4%&\'()*+,-./',
    '0123456789:;<=>?',
    '@ABCDEFGHIJKLMNO',
    'PQRSTUVWXYZ[\\]\u2015_',
    '\u2016abcdefghijklmno',
    'pqrstuvwxyz{|}\u00af\x00',
    '\u00e1\u00e0\u00e9\u00e8\u00ed\u00ec\u00f3\u00f2\u00fa\u00f9\u00d1\u00c7\u015e\u00df\u00a1\u0132',
    '\u00e2\u00e4\u00ea\u00eb\u00ee\u00ef\u00f4\u00f6\u00fb\u00fc\u00f1\u00e7\u015f\u011f\u0131\u0133',
    '\u00aa\u03b1\u00a9\u2030\u011e\u011b\u0148\u0151\u03c0\u20ac\u00a3$\u2190\u2191\u2192\u2193',
    '\u00ba\u00b9\u00b2\u00b3\u00b1\u0130\u0144\u0171\u00b5\u00bf\u00f7\u00b0\u00bc\u00bd\u00be\u00a7',
    '\u00c1\u00c0\u00c9\u00c8\u00cd\u00cc\u00d3\u00d2\u00da\u00d9\u0158\u010c\u0160\u017d\u00d0\u013f',
    '\u00c2\u00c4\u00ca\u00cb\u00ce\u00cf\u00d4\u00d6\u00db\u00dc\u0159\u010d\u0161\u017e\u0111\u0140',
    '\u00c3\u00c5\u00c6\u0152\u0177\u00dd\u00d5\u00d8\u00de\u014a\u0154\u0106\u015a\u0179\u0166\u00f0',
    '\u00e3\u00e5\u00e6\u0153\u0175\u00fd\u00f5\u00f8\u00fe\u014b\u0155\u0107\u015b\u017a\u0167\x00',
)
G0 = [None] * 256
for _r, _row in enumerate(_G0_ROWS):
    assert len(_row) == 16, _r
    for _c, _ch in enumerate(_row):
        if _ch != '\x00':
            G0[0x20 + 16 * _r + _c] = _ch
_ENC = {}
for _code, _ch in enumerate(G0):
    if _ch is not None and _ch not in _ENC:
        _ENC[_ch] = _code
_ENC.update({'\u03b2': 0x8D, '`': 0x27})          # look-alikes people type
_TYPO = {'\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-',
         '\u2026': '...', '\u00d7': 'x', '\t': ' ', '\r': ' ', '\n': ' '}

# RBDS PI code <-> US call letters (NRSC-4 Annex D), the same table as the all-mode-receiver
# tuner's RDS decoder
_RBDS_3LETTER = {
    0x99A5: 'KBW', 0x99A6: 'KCY', 0x9990: 'KDB', 0x99A7: 'KDF', 0x9950: 'KEX', 0x9951: 'KFH',
    0x9952: 'KFI', 0x9953: 'KGA', 0x9991: 'KGB', 0x9954: 'KGO', 0x9955: 'KGU', 0x9956: 'KGW',
    0x9957: 'KGY', 0x99AA: 'KHQ', 0x9958: 'KID', 0x9959: 'KIT', 0x995A: 'KJR', 0x995B: 'KLO',
    0x995C: 'KLZ', 0x995D: 'KMA', 0x995E: 'KMJ', 0x995F: 'KNX', 0x9960: 'KOA', 0x99AB: 'KOB',
    0x9992: 'KOY', 0x9993: 'KPQ', 0x9964: 'KQV', 0x9994: 'KSD', 0x9965: 'KSL', 0x9966: 'KUJ',
    0x9995: 'KUT', 0x9967: 'KVI', 0x9968: 'KWG', 0x9996: 'KXL', 0x9997: 'KXO', 0x996B: 'KYW',
    0x9999: 'WBT', 0x996D: 'WBZ', 0x996E: 'WDZ', 0x996F: 'WEW', 0x999A: 'WGH', 0x9971: 'WGL',
    0x9972: 'WGN', 0x9973: 'WGR', 0x999B: 'WGY', 0x9975: 'WHA', 0x9976: 'WHB', 0x9977: 'WHK',
    0x9978: 'WHO', 0x999C: 'WHP', 0x999D: 'WIL', 0x997A: 'WIP', 0x99B3: 'WIS', 0x997B: 'WJR',
    0x99B4: 'WJW', 0x99B5: 'WJZ', 0x997C: 'WKY', 0x997D: 'WLS', 0x997E: 'WLW', 0x999E: 'WMC',
    0x999F: 'WMT', 0x9981: 'WOC', 0x99A0: 'WOI', 0x9983: 'WOL', 0x9984: 'WOR', 0x99A1: 'WOW',
    0x99B9: 'WRC', 0x99A2: 'WRR', 0x99A3: 'WSB', 0x99A4: 'WSM', 0x9988: 'WWJ', 0x9989: 'WWL',
}
_CALL_3LETTER = {v: k for k, v in _RBDS_3LETTER.items()}


def callsign_to_pi(call):
    """RBDS PI from US call letters (WSB, KDKA, WAMD...), or None."""
    call = (call or '').strip().upper().split('-')[0]
    if call in _CALL_3LETTER:
        return _CALL_3LETTER[call]
    if len(call) != 4 or call[0] not in 'KW' or not call[1:].isalpha():
        return None
    a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    n = 676 * a.index(call[1]) + 26 * a.index(call[2]) + a.index(call[3])
    return (4096 if call[0] == 'K' else 21672) + n


def pi_to_callsign(pi):
    """US call letters from an RBDS PI code, or None."""
    if pi in _RBDS_3LETTER:
        return _RBDS_3LETTER[pi]
    if 0x1000 <= pi <= 0x54A7:
        first, n = 'K', pi - 4096
    elif 0x54A8 <= pi <= 0x994F:
        first, n = 'W', pi - 21672
    else:
        return None
    a = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    return first + a[n // 676] + a[(n // 26) % 26] + a[n % 26]


def text_to_codes(s, upper=False):
    """Text to G0 codes. Accents kept where the table has the letter, dropped where it doesn't."""
    s = ''.join(_TYPO.get(c, c) for c in str(s))
    s = unicodedata.normalize('NFC', s.upper() if upper else s)
    out = []
    for c in s:
        code = _ENC.get(c)
        if code is None:
            base = unicodedata.normalize('NFKD', c)[:1]
            code = _ENC.get(base, 0x20) if base and not unicodedata.combining(base) else 0x20
        if code == 0x20 and (not out or out[-1] == 0x20):
            continue                                           # no leading spaces or runs of them
        out.append(code)
    while out and out[-1] == 0x20:
        out.pop()
    return out


def codes_to_text(codes):
    return ''.join(G0[c] or ' ' for c in codes)


def crc11(info36):
    v = info36 << 11
    for i in range(46, 10, -1):
        if v >> i & 1:
            v ^= POLY << (i - 11)
    return v


def syndrome(block47):
    v = block47
    for i in range(46, 10, -1):
        if v >> i & 1:
            v ^= POLY << (i - 11)
    return v


def make_block(info36, offset):
    return (info36 << 11) | (crc11(info36) ^ offset)


def pack_bytes(codes):
    v = 0
    for c in codes:
        v = (v << 8) | (c & 0xFF)
    return v


def core_group(pi, pty, tp, ta, af, seg, ps_codes, alert=0):
    """Half of the PS (4 characters) per group, seg 0 or 1."""
    ps = (list(ps_codes) + [0x20] * 8)[:8]
    b1 = ((pi & 0xFFFF) << 20) | ((pty & 31) << 15) | ((tp & 1) << 14) | ((ta & 1) << 13) \
        | ((af & 1) << 12) | ((seg & 1) << 11) | ((alert & 1) << 10)
    b2 = pack_bytes(ps[4 * (seg & 1):4 * (seg & 1) + 4]) << 4
    return [make_block(b1, OFFSET['core1']), make_block(b2, OFFSET['core2'])]


def rt_segments(rt_codes, max_len=RT_MAX):
    """RadioText cut to max_len, ended with 0x0D if shorter than 64, padded to whole 8-char segments."""
    codes = list(rt_codes)[:max(0, min(int(max_len), RT_MAX))]
    if not codes:
        return []
    if len(codes) < RT_MAX:
        codes.append(END)
    codes += [0x20] * (-len(codes) % 8)
    return [codes[i:i + 8] for i in range(0, len(codes), 8)]


def rt_group(seg, ab, chars8, alert=0):
    """One 8-character RadioText segment; alert = 0 none, 1 test, 2 emergency."""
    b1 = ((seg & 7) << 33) | ((ab & 1) << 32) | pack_bytes(chars8[:4])
    b2 = (pack_bytes(chars8[4:8]) << 4) | (max(0, min(2, int(alert))) & 3)
    return [make_block(b1, OFFSET['rt1']), make_block(b2, OFFSET['rt2'])]


# ---- extended groups -----------------------------------------------------------------------
EXT_STATION, EXT_AF, EXT_CLOCK, EXT_RTPLUS, EXT_ISRC = 0, 1, 2, 3, 4
_ISRC_ALNUM = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def ext_group(typ, payload68):
    b1 = ((typ & 15) << 32) | ((payload68 >> 36) & 0xFFFFFFFF)
    return [make_block(b1, OFFSET['ext1']), make_block(payload68 & ((1 << 36) - 1), OFFSET['ext2'])]


def ext_station(facility_id, ecc=0xA0):
    return ext_group(EXT_STATION, ((facility_id & 0xFFFFFF) << 44) | ((ecc & 0xFF) << 36))


def af_code(freq):
    """A frequency (95.5 = MHz, 750 = kHz) to a 9-bit entry: band bit | code, or None."""
    f = float(freq)
    if 87.6 <= f <= 107.9:
        return (0 << 8) | int(round((f - 87.5) * 10))
    if 530 <= f <= 1710:
        return (1 << 8) | (int(round((f - 530) / 10.0)) + 1)
    return None


def af_freq(entry):
    band, code = entry >> 8, entry & 0xFF
    return ('%.1f MHz' % (87.5 + code / 10.0)) if band == 0 else ('%d kHz' % (530 + 10 * (code - 1)))


def ext_af(entries):
    e = list(entries)[:6]
    v = len(e) << 65
    for i, x in enumerate(e):
        v |= (x & 0x1FF) << (56 - 9 * i)
    return ext_group(EXT_AF, v)


def ext_clock(t=None):
    """RDS clock-time layout: MJD, UTC hour and minute, local offset in half hours."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc) if t is None else t
    mjd = (now.date() - _dt.date(1858, 11, 17)).days
    off = time.localtime().tm_gmtoff // 1800 if t is None else 0
    v = ((mjd & 0x1FFFF) << 51) | ((now.hour & 31) << 46) | ((now.minute & 63) << 40) \
        | ((1 if off < 0 else 0) << 39) | ((abs(off) & 31) << 34)
    return ext_group(EXT_CLOCK, v)


def ext_rtplus(toggle, running, tag1, tag2):
    """tag = (content type, start, length) or None. RT+ types: 1 = ITEM.TITLE, 4 = ITEM.ARTIST."""
    def t(tag, lbits):
        if not tag:
            return 0, 0, 0
        ct, st, ln = tag
        return ct & 63, st & 63, max(0, ln - 1) & ((1 << lbits) - 1)
    c1, s1, l1 = t(tag1, 6)
    c2, s2, l2 = t(tag2, 5)
    v = ((toggle & 1) << 67) | ((running & 1) << 66) | (c1 << 60) | (s1 << 54) | (l1 << 48) \
        | (c2 << 42) | (s2 << 36) | (l2 << 31)
    return ext_group(EXT_RTPLUS, v)


def isrc_pack(isrc):
    """'US-RC1-76-07839' or 'USRC17607839' to 52 bits, or None if it isn't an ISRC."""
    s = ''.join(c for c in str(isrc or '').upper() if c.isalnum())
    if len(s) != 12 or not s[:2].isalpha() or not s[5:].isdigit() or any(c not in _ISRC_ALNUM for c in s[2:5]):
        return None
    v = 0
    for c in s[:2]:
        v = (v << 5) | (ord(c) - 65)
    for c in s[2:5]:
        v = (v << 6) | _ISRC_ALNUM.index(c)
    return (v << 24) | (int(s[5:7]) << 17) | int(s[7:])


def isrc_unpack(v):
    a = v >> 24
    reg = ''.join(_ISRC_ALNUM[(a >> (6 * (2 - i))) & 63] for i in range(3))
    cc = chr(65 + ((a >> 23) & 31)) + chr(65 + ((a >> 18) & 31))
    return '%s%s%02d%05d' % (cc, reg, (v >> 17) & 127, v & 0x1FFFF)


def ext_isrc(isrc):
    p = isrc_pack(isrc)
    return None if p is None else ext_group(EXT_ISRC, p << 16)


def rtplus_tags(text, artist=None, title=None):
    """RT+ tags for 'Artist - Title' (or given artist/title) inside the RadioText text."""
    tags = []
    if artist is None and title is None and ' - ' in text:
        artist, title = text.split(' - ', 1)
    for ct, part in ((4, artist), (1, title)):
        if part:
            i = text.find(part)
            if 0 <= i < 64 and part:
                tags.append((ct, i, min(len(part), 64 - i)))
    return tags[:2]


def blocks_to_bits(blocks, nbits=47):
    return np.array([(b >> (nbits - 1 - i)) & 1 for b in blocks for i in range(nbits)], dtype=np.int8)


# ---- RBDS (IEC 62106 / NRSC-4) block coding and groups -----------------------------------
RDS_POLY = 0x5B9                               # x^10 + x^8 + x^7 + x^5 + x^4 + x^3 + 1
RDS_OFFSET = {'A': 0x0FC, 'B': 0x198, 'C': 0x168, 'Cp': 0x350, 'D': 0x1B4}


def rds_crc(info16):
    v = info16 << 10
    for i in range(25, 9, -1):
        if v >> i & 1:
            v ^= RDS_POLY << (i - 10)
    return v


def rds_syndrome(block26):
    v = block26
    for i in range(25, 9, -1):
        if v >> i & 1:
            v ^= RDS_POLY << (i - 10)
    return v


def rds_block(info16, offset):
    return ((info16 & 0xFFFF) << 10) | (rds_crc(info16 & 0xFFFF) ^ RDS_OFFSET[offset])


def rbds_0a(pi, pty, tp, ta, ms, seg, ps_codes, di=0):
    """Group 0A: PI, PTY, TP, TA, M/S, decoder ID bit, 2 PS characters; no AF list (224/205)."""
    ps = (list(ps_codes) + [0x20] * 8)[:8]
    b = (0 << 12) | (0 << 11) | ((tp & 1) << 10) | ((pty & 31) << 5) | ((ta & 1) << 4) | ((ms & 1) << 3) \
        | ((di & 1) << 2) | (seg & 3)
    return [rds_block(pi, 'A'), rds_block(b, 'B'), rds_block((224 << 8) | 205, 'C'),
            rds_block((ps[2 * seg] << 8) | ps[2 * seg + 1], 'D')]


def rbds_rt_segments(rt_codes, max_len=RT_MAX):
    codes = list(rt_codes)[:max(0, min(int(max_len), RT_MAX))]
    if not codes:
        return []
    if len(codes) < RT_MAX:
        codes.append(END)
    codes += [0x20] * (-len(codes) % 4)
    return [codes[i:i + 4] for i in range(0, len(codes), 4)]


def rbds_2a(pi, pty, tp, ab, seg, chars4):
    """Group 2A: 4 RadioText characters, segment 0-15, text A/B flag."""
    c = (list(chars4) + [0x20] * 4)[:4]
    b = (2 << 12) | (0 << 11) | ((tp & 1) << 10) | ((pty & 31) << 5) | ((ab & 1) << 4) | (seg & 15)
    return [rds_block(pi, 'A'), rds_block(b, 'B'), rds_block((c[0] << 8) | c[1], 'C'),
            rds_block((c[2] << 8) | c[3], 'D')]
