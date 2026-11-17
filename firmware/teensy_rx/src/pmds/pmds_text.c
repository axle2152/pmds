/*
 * Copyright 2026 Michael Foley
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
 * except in compliance with the License. You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the
 * License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
 * either express or implied. See the License for the specific language governing permissions
 * and limitations under the License.
 */
/*
 * pmds_text.c - the RDS character set (G0) as UTF-8, US call letters from PI codes, AF
 * frequencies and dates: the parts of pmds/codec.py a radio needs to show the station.
 * The tables are generated from pmds/codec.py; tests/test_c.py checks they still match.
 */
#include <stdio.h>
#include <string.h>
#include "pmds.h"

/* G0 codes 0x20 to 0xFF as UTF-8; "" where the table defines nothing. 0x8D and 0x9D/0xA4
 * are read as the German sharp s and the Turkish g-breve, as in pmds/codec.py. */
static const char *const G0_UTF8[224] = {
    " ", "!", "\x22", "#", "\xC2\xA4", "%", "&", "'",
    "(", ")", "*", "+", ",", "-", ".", "/",
    "0", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", ":", ";", "<", "=", ">", "?",
    "@", "A", "B", "C", "D", "E", "F", "G",
    "H", "I", "J", "K", "L", "M", "N", "O",
    "P", "Q", "R", "S", "T", "U", "V", "W",
    "X", "Y", "Z", "[", "\x5C", "]", "\xE2\x80\x95", "_",
    "\xE2\x80\x96", "a", "b", "c", "d", "e", "f", "g",
    "h", "i", "j", "k", "l", "m", "n", "o",
    "p", "q", "r", "s", "t", "u", "v", "w",
    "x", "y", "z", "{", "|", "}", "\xC2\xAF", "",
    "\xC3\xA1", "\xC3\xA0", "\xC3\xA9", "\xC3\xA8", "\xC3\xAD", "\xC3\xAC", "\xC3\xB3", "\xC3\xB2",
    "\xC3\xBA", "\xC3\xB9", "\xC3\x91", "\xC3\x87", "\xC5\x9E", "\xC3\x9F", "\xC2\xA1", "\xC4\xB2",
    "\xC3\xA2", "\xC3\xA4", "\xC3\xAA", "\xC3\xAB", "\xC3\xAE", "\xC3\xAF", "\xC3\xB4", "\xC3\xB6",
    "\xC3\xBB", "\xC3\xBC", "\xC3\xB1", "\xC3\xA7", "\xC5\x9F", "\xC4\x9F", "\xC4\xB1", "\xC4\xB3",
    "\xC2\xAA", "\xCE\xB1", "\xC2\xA9", "\xE2\x80\xB0", "\xC4\x9E", "\xC4\x9B", "\xC5\x88", "\xC5\x91",
    "\xCF\x80", "\xE2\x82\xAC", "\xC2\xA3", "$", "\xE2\x86\x90", "\xE2\x86\x91", "\xE2\x86\x92", "\xE2\x86\x93",
    "\xC2\xBA", "\xC2\xB9", "\xC2\xB2", "\xC2\xB3", "\xC2\xB1", "\xC4\xB0", "\xC5\x84", "\xC5\xB1",
    "\xC2\xB5", "\xC2\xBF", "\xC3\xB7", "\xC2\xB0", "\xC2\xBC", "\xC2\xBD", "\xC2\xBE", "\xC2\xA7",
    "\xC3\x81", "\xC3\x80", "\xC3\x89", "\xC3\x88", "\xC3\x8D", "\xC3\x8C", "\xC3\x93", "\xC3\x92",
    "\xC3\x9A", "\xC3\x99", "\xC5\x98", "\xC4\x8C", "\xC5\xA0", "\xC5\xBD", "\xC3\x90", "\xC4\xBF",
    "\xC3\x82", "\xC3\x84", "\xC3\x8A", "\xC3\x8B", "\xC3\x8E", "\xC3\x8F", "\xC3\x94", "\xC3\x96",
    "\xC3\x9B", "\xC3\x9C", "\xC5\x99", "\xC4\x8D", "\xC5\xA1", "\xC5\xBE", "\xC4\x91", "\xC5\x80",
    "\xC3\x83", "\xC3\x85", "\xC3\x86", "\xC5\x92", "\xC5\xB7", "\xC3\x9D", "\xC3\x95", "\xC3\x98",
    "\xC3\x9E", "\xC5\x8A", "\xC5\x94", "\xC4\x86", "\xC5\x9A", "\xC5\xB9", "\xC5\xA6", "\xC3\xB0",
    "\xC3\xA3", "\xC3\xA5", "\xC3\xA6", "\xC5\x93", "\xC5\xB5", "\xC3\xBD", "\xC3\xB5", "\xC3\xB8",
    "\xC3\xBE", "\xC5\x8B", "\xC5\x95", "\xC4\x87", "\xC5\x9B", "\xC5\xBA", "\xC5\xA7", "",
};

const char *pmds_g0_utf8(uint8_t code)
{
    return code < 0x20 ? "" : G0_UTF8[code - 0x20];
}

int pmds_text_utf8(const uint8_t *codes, int n, char *out, int outsize)
{
    int i, len = 0;
    if (outsize <= 0)
        return 0;
    for (i = 0; i < n; i++) {
        const char *s = pmds_g0_utf8(codes[i]);
        int k = (int)strlen(s);
        if (!k) {                                        /* undefined: a space */
            s = " ";
            k = 1;
        }
        if (len + k >= outsize)
            break;
        memcpy(out + len, s, (size_t)k);
        len += k;
    }
    out[len] = 0;
    return len;
}

/* RBDS PI codes of the three-letter calls (NRSC-4-B Annex D) */
static const struct { uint16_t pi; const char *call; } THREE[] = {
    {0x9950, "KEX"}, {0x9951, "KFH"}, {0x9952, "KFI"}, {0x9953, "KGA"}, {0x9954, "KGO"}, {0x9955, "KGU"},
    {0x9956, "KGW"}, {0x9957, "KGY"}, {0x9958, "KID"}, {0x9959, "KIT"}, {0x995A, "KJR"}, {0x995B, "KLO"},
    {0x995C, "KLZ"}, {0x995D, "KMA"}, {0x995E, "KMJ"}, {0x995F, "KNX"}, {0x9960, "KOA"}, {0x9964, "KQV"},
    {0x9965, "KSL"}, {0x9966, "KUJ"}, {0x9967, "KVI"}, {0x9968, "KWG"}, {0x996B, "KYW"}, {0x996D, "WBZ"},
    {0x996E, "WDZ"}, {0x996F, "WEW"}, {0x9971, "WGL"}, {0x9972, "WGN"}, {0x9973, "WGR"}, {0x9975, "WHA"},
    {0x9976, "WHB"}, {0x9977, "WHK"}, {0x9978, "WHO"}, {0x997A, "WIP"}, {0x997B, "WJR"}, {0x997C, "WKY"},
    {0x997D, "WLS"}, {0x997E, "WLW"}, {0x9981, "WOC"}, {0x9983, "WOL"}, {0x9984, "WOR"}, {0x9988, "WWJ"},
    {0x9989, "WWL"}, {0x9990, "KDB"}, {0x9991, "KGB"}, {0x9992, "KOY"}, {0x9993, "KPQ"}, {0x9994, "KSD"},
    {0x9995, "KUT"}, {0x9996, "KXL"}, {0x9997, "KXO"}, {0x9999, "WBT"}, {0x999A, "WGH"}, {0x999B, "WGY"},
    {0x999C, "WHP"}, {0x999D, "WIL"}, {0x999E, "WMC"}, {0x999F, "WMT"}, {0x99A0, "WOI"}, {0x99A1, "WOW"},
    {0x99A2, "WRR"}, {0x99A3, "WSB"}, {0x99A4, "WSM"}, {0x99A5, "KBW"}, {0x99A6, "KCY"}, {0x99A7, "KDF"},
    {0x99AA, "KHQ"}, {0x99AB, "KOB"}, {0x99B3, "WIS"}, {0x99B4, "WJW"}, {0x99B5, "WJZ"}, {0x99B9, "WRC"},
};

int pmds_pi_to_call(uint16_t pi, char out[5])
{
    static const char *A = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    unsigned i, p = pi, n;
    for (i = 0; i < sizeof THREE / sizeof THREE[0]; i++)
        if (THREE[i].pi == pi) {
            strcpy(out, THREE[i].call);
            return 1;
        }
    if ((p >> 8) == 0xAF)                                /* AFxy was xy00 */
        p = (p & 0xFF) << 8;
    if ((p >> 12) == 0xA && ((p >> 8) & 0xF) >= 1 && ((p >> 8) & 0xF) <= 9)
        p = (((p >> 8) & 0xF) << 12) | (p & 0xFF);       /* Axyz was x0yz */
    if (p >= 0x1000 && p <= 0x54A7) {
        out[0] = 'K';
        n = p - 4096;
    } else if (p >= 0x54A8 && p <= 0x994F) {
        out[0] = 'W';
        n = p - 21672;
    } else {
        out[0] = 0;
        return 0;
    }
    out[1] = A[n / 676];
    out[2] = A[(n / 26) % 26];
    out[3] = A[n % 26];
    out[4] = 0;
    return 1;
}

uint16_t pmds_call_to_pi(const char *call)
{
    unsigned i, n, pi;
    char c[5];
    for (i = 0; i < 4 && call[i] && call[i] != '-'; i++)
        c[i] = (char)(call[i] >= 'a' && call[i] <= 'z' ? call[i] - 32 : call[i]);
    c[i] = 0;
    for (n = 0; n < sizeof THREE / sizeof THREE[0]; n++)
        if (!strcmp(THREE[n].call, c))
            return THREE[n].pi;
    if (i != 4 || (call[4] && call[4] != '-') || (c[0] != 'K' && c[0] != 'W'))
        return 0;
    for (i = 1; i < 4; i++)
        if (c[i] < 'A' || c[i] > 'Z')
            return 0;
    n = 676u * (unsigned)(c[1] - 'A') + 26u * (unsigned)(c[2] - 'A') + (unsigned)(c[3] - 'A');
    pi = (c[0] == 'K' ? 4096u : 21672u) + n;
    if (((pi >> 8) & 0xF) == 0)
        pi = 0xA000 | ((pi >> 12) << 8) | (pi & 0xFF);
    if ((pi & 0xFF) == 0)
        pi = 0xAF00 | (pi >> 8);
    return (uint16_t)pi;
}

int pmds_af_text(uint16_t entry, char *out, int outsize)
{
    int code = entry & 0xFF;
    if ((entry >> 8) == 0)
        return snprintf(out, (size_t)outsize, "%.1f MHz", 87.5 + code / 10.0);
    return snprintf(out, (size_t)outsize, "%d kHz", 530 + 10 * (code - 1));
}

void pmds_mjd_to_date(uint32_t mjd, int *year, int *month, int *day)
{
    /* Fliegel and Van Flandern: the Julian day number at noon to the Gregorian date */
    long l = (long)mjd + 2400001L + 68569L, n, i, j;
    n = 4 * l / 146097;
    l = l - (146097 * n + 3) / 4;
    i = 4000 * (l + 1) / 1461001;
    l = l - 1461 * i / 4 + 31;
    j = 80 * l / 2447;
    *day = (int)(l - 2447 * j / 80);
    l = j / 11;
    *month = (int)(j + 2 - 12 * l);
    *year = (int)(100 * (n - 49) + i + l);
}
