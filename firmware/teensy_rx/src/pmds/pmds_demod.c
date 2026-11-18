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
 * pmds_demod.c - bits from the carrier's phase: a sample-by-sample port of
 * pmds.demod.Demodulator (compact framing, 93.75 bit/s, 6000 Hz). Python works on blocks of
 * samples with running sums made fresh each block; here the same sums are kept running and
 * remade from their buffers now and then, so rounding can't build up.
 *
 * Per sample, in order:
 *   1. the phase against a local carrier, the mean of the last 4 bits, centred on the sample
 *   2. the program's leak taken out: the phase fitted to the envelope and its slope over the
 *      last 8 bits and the fit subtracted, when it explains enough (spec section 9, item 3)
 *   3. a matched filter one bit long (one sine cycle)
 * Per bit period: the bit at the timing phase with the most matched-filter energy.
 */
#include <math.h>
#include <string.h>
#include "pmds.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define E_ALPHA      (1.0 / 16.0)
#define SWITCH       1.15
#define LEVEL_A      0.05
#define CANCEL_RIDGE 1e-4
#define CANCEL_FLOOR 0.05
#define RESUM_EVERY  4096

static double demod_now(void *ctx) { return pmds_demod_now((const pmds_demod *)ctx); }

void pmds_demod_init(pmds_demod *d)
{
    pmds_event_fn on_event = d->fr.on_event;
    void *ev_ctx = d->fr.ev_ctx;
    pmds_bit_fn on_bit = d->on_bit;
    void *bit_ctx = d->bit_ctx;
    int strict = d->fr.strict;
    int i;
    memset(d, 0, sizeof *d);
    d->on_bit = on_bit;
    d->bit_ctx = bit_ctx;
    d->fr.on_event = on_event;
    d->fr.ev_ctx = ev_ctx;
    d->fr.strict = strict;
    d->fr.now = demod_now;
    d->fr.now_ctx = d;
    pmds_framer_init(&d->fr);
    d->cancel = 1;
    for (i = 0; i < PMDS_SPB; i++)                       /* a clean bit reads +/- its peak phase */
        d->tmpl[i] = (pmds_real)(sin(2.0 * M_PI * i / PMDS_SPB) / (PMDS_SPB / 2.0));
    for (i = 0; i < PMDS_CANCEL; i++)
        d->er[i] = 1.0;                                  /* the envelope's history starts at 1 */
    d->eprev = 1.0;
    d->se = d->see = PMDS_CANCEL;
    d->last = -1000000000L;
    d->var = 1.0;
}

double pmds_demod_now(const pmds_demod *d)
{
    return d->t_set ? d->t : (double)d->n / PMDS_FS;
}

double pmds_demod_dev_deg(const pmds_demod *d) { return d->amp * 180.0 / M_PI; }

double pmds_demod_snr_db(const pmds_demod *d)
{
    double a2 = d->amp * d->amp, v = d->var;
    return 10.0 * log10((a2 > 1e-12 ? a2 : 1e-12) / (v > 1e-12 ? v : 1e-12));
}

double pmds_demod_cn_db(const pmds_demod *d)
{
    double dev = d->amp;
    if (dev < 0.5 * M_PI / 180.0)
        return -999.0;
    return pmds_demod_snr_db(d) - 20.0 * log10(dev) - 10.0 * log10(1e4 / PMDS_BIT_RATE);
}

static void bit_(pmds_demod *d, double v)
{
    double a = fabs(v);
    int bit = v > 0;
    d->amp += LEVEL_A * (a - d->amp);
    d->var += LEVEL_A * ((a - d->amp) * (a - d->amp) - d->var);
    if (d->on_bit)
        d->on_bit(d->bit_ctx, d->t, v, bit);
    pmds_framer_push(&d->fr, bit);
    pmds_framer_tick(&d->fr);
}

static void row_(pmds_demod *d)
{
    const int spb = PMDS_SPB, half = PMDS_SPB / 2;
    long n0 = d->n;
    int b = d->best, j, k;
    if (n0 + b - d->last >= half) {                      /* never two bits closer than half a bit */
        d->last = n0 + b;
        d->t = (double)(n0 + b) / PMDS_FS;
        d->t_set = 1;
        bit_(d, d->row[b]);
    }
    for (j = 0; j < spb; j++)
        d->E[j] += (pmds_real)(E_ALPHA * (d->row[j] * d->row[j] - d->E[j]));
    k = 0;
    for (j = 1; j < spb; j++)
        if (d->E[j] > d->E[k])
            k = j;
    if (d->E[k] > SWITCH * d->E[b]) {
        d->best = k;
        if (n0 + k - d->last >= spb - half / 2) {
            /* the timing moved back across the wrap (a transmitter clock a little fast): the
               new phase is a whole bit past the last decision and that bit ends in this row */
            d->last = n0 + k;
            d->t = (double)(n0 + k) / PMDS_FS;
            d->t_set = 1;
            bit_(d, d->row[k]);
        }
    }
    d->t_set = 0;
    d->n += spb;
}

static void resum(pmds_demod *d)
{
    int i;
    double zr = 0, zi = 0, se = 0, sd = 0, st = 0, see = 0, sdd = 0, sed = 0, set = 0, sdt = 0, stt = 0;
    for (i = 0; i < PMDS_LOCAL; i++) {
        zr += d->zring[i].re;
        zi += d->zring[i].im;
    }
    for (i = 0; i < PMDS_CANCEL; i++) {
        double e = d->er[i], dd = d->dr[i], t = d->tr[i];
        se += e; sd += dd; st += t;
        see += e * e; sdd += dd * dd; sed += e * dd;
        set += e * t; sdt += dd * t; stt += t * t;
    }
    d->zs_re = zr; d->zs_im = zi;
    d->se = se; d->sd = sd; d->st_ = st; d->see = see; d->sdd = sdd; d->sed = sed;
    d->set_ = set; d->sdt = sdt; d->stt = stt;
}

/* one sample of phase (th) and envelope (env), centred 2 bits back; returns the phase with
 * the leak taken out, centred 4 bits further back */
static pmds_real cancel_(pmds_demod *d, pmds_real env, pmds_real th)
{
    const double W = PMDS_CANCEL;
    int p = d->cpos, c = (d->cpos + PMDS_CANCEL / 2) % PMDS_CANCEL;
    pmds_real dn = (pmds_real)((env - d->eprev) * (PMDS_FS / 600.0));
    double me = d->se / W, md = d->sd / W, mt = d->st_ / W;
    double see = d->see / W - me * me + CANCEL_RIDGE;
    double sdd = d->sdd / W - md * md + CANCEL_RIDGE;
    double sed = d->sed / W - me * md;
    double set = d->set_ / W - me * mt, sdt = d->sdt / W - md * mt;
    double det = see * sdd - sed * sed;
    double k1 = (set * sdd - sdt * sed) / det, k2 = (sdt * see - set * sed) / det;
    double told = k1 * set + k2 * sdt, tvar = d->stt / W - mt * mt;
    double share = told / (tvar > 1e-30 ? tvar : 1e-30);
    double keep = share / CANCEL_FLOOR - 1.0;
    double out;
    if (keep < 0) keep = 0;
    if (keep > 1) keep = 1;
    out = d->tr[c] - keep * (k1 * (d->er[c] - me) + k2 * (d->dr[c] - md));
    /* the window moves on: the oldest sample out, this one in */
    d->se += env - d->er[p];
    d->sd += dn - d->dr[p];
    d->st_ += th - d->tr[p];
    d->see += env * env - d->er[p] * d->er[p];
    d->sdd += dn * dn - d->dr[p] * d->dr[p];
    d->sed += env * dn - d->er[p] * d->dr[p];
    d->set_ += env * th - d->er[p] * d->tr[p];
    d->sdt += dn * th - d->dr[p] * d->tr[p];
    d->stt += th * th - d->tr[p] * d->tr[p];
    d->er[p] = env;
    d->dr[p] = dn;
    d->tr[p] = th;
    d->eprev = env;
    d->cpos = (p + 1) % PMDS_CANCEL;
    return (pmds_real)out;
}

void pmds_demod_process(pmds_demod *d, const pmds_cplx *z, int n)
{
    const double L = PMDS_LOCAL, a = 1.0 - exp(-1.0 / PMDS_FS);
    int i, j;
    for (i = 0; i < n; i++) {
        pmds_cplx x = z[i], zd, ref;
        double r2, floor_, th, env, mf = 0.0;
        int p;
        if (!d->c_init) {                                /* the slow carrier: only for the floor */
            d->c = x;
            if (x.re == 0 && x.im == 0)
                d->c.re = 1.0;
            d->c_init = 1;
        } else {
            d->c.re += (pmds_real)(a * (x.re - d->c.re));
            d->c.im += (pmds_real)(a * (x.im - d->c.im));
        }
        /* 1: the carrier over the last 4 bits, the sample 2 bits back measured against it */
        ref.re = (pmds_real)(d->zs_re / L);
        ref.im = (pmds_real)(d->zs_im / L);
        zd = d->zring[(d->zpos + PMDS_LOCAL / 2) % PMDS_LOCAL];
        r2 = (double)ref.re * ref.re + (double)ref.im * ref.im;
        floor_ = 1e-6 * ((double)d->c.re * d->c.re + (double)d->c.im * d->c.im);
        if (r2 < floor_)
            r2 = floor_;
        env = ((double)zd.re * ref.re + (double)zd.im * ref.im) / r2;   /* zd * conj(ref) */
        th = ((double)zd.im * ref.re - (double)zd.re * ref.im) / r2;
        d->zs_re += x.re - d->zring[d->zpos].re;
        d->zs_im += x.im - d->zring[d->zpos].im;
        d->zring[d->zpos] = x;
        d->zpos = (d->zpos + 1) % PMDS_LOCAL;
        /* 2: the leak */
        if (d->cancel)
            th = cancel_(d, (pmds_real)env, (pmds_real)th);
        if (++d->ccount >= RESUM_EVERY) {
            d->ccount = 0;
            resum(d);
        }
        /* 3: the matched filter, the bit ending at this sample */
        d->thring[d->thpos] = (pmds_real)th;
        d->thpos = (d->thpos + 1) % PMDS_SPB;
        for (j = 0, p = d->thpos; j < PMDS_SPB; j++, p = (p + 1) % PMDS_SPB)
            mf += (double)d->thring[p] * d->tmpl[j];
        d->row[d->rown++] = (pmds_real)mf;
        if (d->rown == PMDS_SPB) {
            d->rown = 0;
            row_(d);
        }
    }
}
