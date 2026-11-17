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
 * pmds_decode - the C decoder on a PC, for testing it against the Python one.
 *
 *   pmds_decode [options] FILE
 *
 * FILE is I/Q: a WAV file (16-bit or 32-bit float, I left, Q right), or raw interleaved
 * complex (.cf32 float32, .cf64 float64, as GNU Radio's File Sink writes them).
 *
 *   --rate HZ    sample rate of a raw file (a WAV file says its own)
 *   --if HZ      where the station's carrier sits in the file (default 0)
 *   --demod      the file is already 6000 Hz with the carrier locked: straight to the decoder
 *   --groups     print every group as it decodes
 *   --bits       print every bit decision: time, matched-filter value, bit
 *   --strict     no single-bit correction
 *   --no-cancel  leak canceller off
 *
 * At the end it prints what a radio would show, one "S key=value" line per field.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../pmds.h"

static int show_groups = 0, show_bits = 0;

static void hex_(const uint8_t *b, int n)
{
    int i;
    for (i = 0; i < n; i++)
        printf("%02X", b[i]);
}

static void on_event(void *ctx, const pmds_event *e)
{
    (void)ctx;
    if (!show_groups)
        return;
    switch (e->kind) {
    case PMDS_EV_CORE:
        printf("G core t=%.6f pi=%04X seg=%d fixed=%d pty=%d tp=%d ta=%d flag=%d text=",
               e->t, e->pi, e->seg, e->fixed, e->pty, e->tp, e->ta, e->flag);
        hex_(e->text, 4);
        printf("\n");
        break;
    case PMDS_EV_RT:
        printf("G rt t=%.6f seg=%d ab=%d level=%d fixed=%d text=", e->t, e->seg, e->ab, e->level, e->fixed);
        hex_(e->text, 8);
        printf("\n");
        break;
    case PMDS_EV_EXT:
        printf("G ext t=%.6f pi=%04X type=%d v=%013llX fixed=%d ours=%d\n", e->t, e->pi, e->ext_type,
               (unsigned long long)e->ext_v, e->fixed, e->ours);
        break;
    case PMDS_EV_SYNC: printf("E sync t=%.6f\n", e->t); break;
    case PMDS_EV_NOSYNC: printf("E nosync t=%.6f\n", e->t); break;
    case PMDS_EV_SLIP: printf("E slip t=%.6f\n", e->t); break;
    }
}

static void on_bit(void *ctx, double t, double v, int bit)
{
    (void)ctx;
    if (show_bits)
        printf("B %.6f %.9e %d\n", t, v, bit);
}

static void text_line(const char *key, const uint8_t *codes, int n)
{
    char buf[512];
    pmds_text_utf8(codes, n, buf, sizeof buf);
    printf("S %s=%s\n", key, buf);
}

static void summary(pmds_demod *d, double secs)
{
    const pmds_framer *f = &d->fr;
    const pmds_station *s = &f->st;
    char call[5], buf[32];
    int i;
    printf("S seconds=%.3f\n", secs);
    printf("S synced=%d\n", f->synced);
    printf("S blocks clean=%ld fixed=%ld lost=%ld\n", f->clean, f->fixed, f->lost);
    printf("S groups=%ld\n", f->groups);
    printf("S slips=%ld\n", f->slips_found);
    printf("S dev_deg=%.2f snr_db=%.2f cn_db=%.2f\n", pmds_demod_dev_deg(d), pmds_demod_snr_db(d),
           pmds_demod_cn_db(d));
    if (s->has_pi) {
        printf("S pi=%04X\n", s->pi);
        if (pmds_pi_to_call(s->pi, call))
            printf("S call=%s\n", call);
    }
    if (s->has_ps)
        text_line("ps", s->ps, 8);
    text_line("rt", s->rt, s->rt_len);
    printf("S pty=%d tp=%d ta=%d af_flag=%d\n", s->pty, s->tp, s->ta, s->af_flag);
    printf("S alert=%d\n", s->alert);
    if (s->has_facility)
        printf("S facility=%lu\n", (unsigned long)s->facility_id);
    printf("S af=");
    for (i = 0; i < s->af_count; i++) {
        pmds_af_text(s->af[i], buf, sizeof buf);
        printf("%s%s", i ? ", " : "", buf);
    }
    printf("\n");
    if (s->has_clock) {
        int y, m, dd;
        pmds_mjd_to_date(s->mjd, &y, &m, &dd);
        printf("S clock=%04d-%02d-%02d %02d:%02d UTC (local %+g h)\n", y, m, dd, s->hour, s->minute,
               s->offset_half / 2.0);
    }
    if (s->artist_len)
        text_line("artist", s->artist, s->artist_len);
    if (s->title_len)
        text_line("title", s->title, s->title_len);
}

static uint32_t le32(const unsigned char *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t le16(const unsigned char *p) { return (uint16_t)(p[0] | p[1] << 8); }

int main(int argc, char **argv)
{
    const char *path = NULL, *ext;
    long rate = 0;
    double if_hz = 0.0;
    int demod_only = 0, strict = 0, cancel = 1, fmt = 0, bits = 0, chans = 2, i;  /* fmt 0 cf32, 1 cf64, 2 wav */
    static pmds_front front;
    pmds_demod *d;
    FILE *fp;
    long total = 0;
    unsigned char hdr[12];

    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--rate") && i + 1 < argc) rate = atol(argv[++i]);
        else if (!strcmp(argv[i], "--if") && i + 1 < argc) if_hz = atof(argv[++i]);
        else if (!strcmp(argv[i], "--demod")) demod_only = 1;
        else if (!strcmp(argv[i], "--groups")) show_groups = 1;
        else if (!strcmp(argv[i], "--bits")) show_bits = 1;
        else if (!strcmp(argv[i], "--strict")) strict = 1;
        else if (!strcmp(argv[i], "--no-cancel")) cancel = 0;
        else if (argv[i][0] == '-') { fprintf(stderr, "unknown option %s\n", argv[i]); return 2; }
        else path = argv[i];
    }
    if (!path) {
        fprintf(stderr, "usage: pmds_decode [--rate HZ] [--if HZ] [--demod] [--groups] [--bits] "
                        "[--strict] [--no-cancel] FILE\n");
        return 2;
    }
    fp = fopen(path, "rb");
    if (!fp) {
        perror(path);
        return 1;
    }
    ext = strrchr(path, '.');
    if (ext && !strcmp(ext, ".cf64")) fmt = 1;
    if (ext && !strcmp(ext, ".wav")) fmt = 2;
    if (fmt == 2) {                                      /* RIFF: find fmt and data */
        unsigned char ck[8], fmtb[16];
        int found = 0;
        if (fread(hdr, 1, 12, fp) != 12 || memcmp(hdr, "RIFF", 4) || memcmp(hdr + 8, "WAVE", 4)) {
            fprintf(stderr, "%s: not a WAV file\n", path);
            return 1;
        }
        while (fread(ck, 1, 8, fp) == 8) {
            uint32_t len = le32(ck + 4);
            if (!memcmp(ck, "fmt ", 4)) {
                if (fread(fmtb, 1, 16, fp) != 16) return 1;
                chans = le16(fmtb + 2);
                rate = (long)le32(fmtb + 4);
                bits = le16(fmtb + 14);
                if (le16(fmtb) == 3) bits = -32;         /* float */
                if (len > 16) fseek(fp, (long)(len - 16 + (len & 1)), SEEK_CUR);
            } else if (!memcmp(ck, "data", 4)) {
                found = 1;
                break;
            } else {
                fseek(fp, (long)(len + (len & 1)), SEEK_CUR);
            }
        }
        if (!found || chans != 2 || (bits != 16 && bits != -32)) {
            fprintf(stderr, "%s: need a 2-channel 16-bit or float WAV\n", path);
            return 1;
        }
    }
    if (demod_only)
        rate = PMDS_FS;
    if (rate <= 0) {
        fprintf(stderr, "give the sample rate with --rate\n");
        return 2;
    }
    front.dm.fr.on_event = on_event;
    front.dm.on_bit = on_bit;
    front.dm.fr.strict = strict;
    if (demod_only) {
        d = &front.dm;
        pmds_demod_init(d);
    } else {
        if (pmds_front_init(&front, rate, if_hz)) {
            fprintf(stderr, "can't resample %ld Hz to %d Hz\n", rate, PMDS_FS);
            return 1;
        }
        d = &front.dm;
    }
    d->cancel = cancel;

    for (;;) {
        pmds_cplx buf[1024];
        int n = 0, k;
        if (fmt == 0) {
            float raw[2048];
            n = (int)fread(raw, 8, 1024, fp);
            for (k = 0; k < n; k++) { buf[k].re = raw[2 * k]; buf[k].im = raw[2 * k + 1]; }
        } else if (fmt == 1) {
            double raw[2048];
            n = (int)fread(raw, 16, 1024, fp);
            for (k = 0; k < n; k++) { buf[k].re = (pmds_real)raw[2 * k]; buf[k].im = (pmds_real)raw[2 * k + 1]; }
        } else if (bits == 16) {
            int16_t raw[2048];
            n = (int)fread(raw, 4, 1024, fp);
            for (k = 0; k < n; k++) { buf[k].re = raw[2 * k] / 32768.0; buf[k].im = raw[2 * k + 1] / 32768.0; }
        } else {
            float raw[2048];
            n = (int)fread(raw, 8, 1024, fp);
            for (k = 0; k < n; k++) { buf[k].re = raw[2 * k]; buf[k].im = raw[2 * k + 1]; }
        }
        if (n <= 0)
            break;
        if (demod_only)
            pmds_demod_process(d, buf, n);
        else
            pmds_front_process(&front, buf, n);
        total += n;
    }
    fclose(fp);
    if (!demod_only)
        printf("S if_hz=%.3f carrier_db=%.1f locked=%d\n", front.if_hz, front.carrier_db, front.state);
    summary(d, (double)total / rate);
    return 0;
}
