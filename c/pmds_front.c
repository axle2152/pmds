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
 * pmds_front.c - from I/Q at the radio's own sample rate to the decoder's 6000 Hz, with the
 * carrier locked on the real axis. Written for this project, not taken from GNU Radio, so
 * it stays under the Apache licence like the rest of the decoder.
 *
 *   mixer       moves the station from its offset (the low IF) to 0 Hz
 *   resampler   polyphase, by the exact ratio 6000 / fs_in (20/147 from 44100 Hz), its
 *               filter flat to 800 Hz and closed from 5200 Hz, so nothing folds into the
 *               data's band
 *   acquire     three half-second looks at the average phase step between samples; each
 *               moves the mixer onto the carrier (covers about +/-800 Hz of tuning error)
 *   carrier PLL second order, about 1 Hz, like the reference receiver's (spec section 9,
 *               item 1): slow enough not to follow the data. Frequency it builds up is
 *               handed back to the mixer now and then, so it never runs out of range
 *   low-pass    500 Hz, 49 taps, then the decoder
 */
#include <math.h>
#include <string.h>
#include "pmds.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define PASS_HZ     800.0
#define STOP_HZ     5200.0
#define ACQ_N       3000           /* half a second at 6000 Hz */
#define ACQ_ROUNDS  3
#define PLL_HZ      1.0
#define PLL_MAX_HZ  60.0
#define HANDOFF_HZ  5.0            /* PLL frequency moved into the mixer past this */

static long gcd_(long a, long b)
{
    while (b) {
        long t = a % b;
        a = b;
        b = t;
    }
    return a;
}

static double sinc_(double x) { return x == 0.0 ? 1.0 : sin(M_PI * x) / (M_PI * x); }

static void design(pmds_front *f)
{
    /* the resampler's prototype, at fs_in * up, Blackman window (about 74 dB down) */
    double F = (double)f->fs_in * f->up, fc = 0.5 * (PASS_HZ + STOP_HZ) / F, sum = 0.0;
    int N, k, p, j;
    f->tpp = (int)ceil(5.5 * F / (STOP_HZ - PASS_HZ) / f->up);
    if (f->tpp < 1)
        f->tpp = 1;
    N = f->tpp * f->up;
    for (k = 0; k < N; k++) {
        double m = k - 0.5 * (N - 1), w = 0.42 - 0.5 * cos(2 * M_PI * k / (N - 1 > 0 ? N - 1 : 1))
                                           + 0.08 * cos(4 * M_PI * k / (N - 1 > 0 ? N - 1 : 1));
        double v = 2 * fc * sinc_(2 * fc * m) * (N > 1 ? w : 1.0);
        sum += v;
        /* stored by phase: h[p * tpp + j] is tap p + j * up */
        f->h[(k % f->up) * f->tpp + k / f->up] = (pmds_real)v;
    }
    for (p = 0; p < f->up; p++)                          /* DC gain up, for the zeros stuffed in */
        for (j = 0; j < f->tpp; j++)
            f->h[p * f->tpp + j] = (pmds_real)(f->h[p * f->tpp + j] * f->up / sum);
    /* the 500 Hz low-pass at 6000 Hz, Hamming window, unity gain */
    sum = 0.0;
    for (k = 0; k < PMDS_LP_TAPS; k++) {
        double m = k - 0.5 * (PMDS_LP_TAPS - 1), w = 0.54 - 0.46 * cos(2 * M_PI * k / (PMDS_LP_TAPS - 1));
        f->lp[k] = (pmds_real)(2 * 500.0 / PMDS_FS * sinc_(2 * 500.0 / PMDS_FS * m) * w);
        sum += f->lp[k];
    }
    for (k = 0; k < PMDS_LP_TAPS; k++)
        f->lp[k] = (pmds_real)(f->lp[k] / sum);
}

static void pll_reset(pmds_front *f)
{
    double w = 2 * M_PI * PLL_HZ / PMDS_FS, z = sqrt(0.5), den = 1 + 2 * z * w + w * w;
    f->pll_ph = 0.0;
    f->pll_w = 0.0;
    f->pll_a = 4 * z * w / den;                          /* critically damped second-order loop */
    f->pll_b = 4 * w * w / den;
    f->pll_wmax = 2 * M_PI * PLL_MAX_HZ / PMDS_FS;
}

static void acquire_reset(pmds_front *f)
{
    f->state = 0;
    f->acq_round = 0;
    f->acq_n = 0;
    f->acq_re = f->acq_im = f->acq_pw = 0;
    f->acq_prev.re = f->acq_prev.im = 0;
}

int pmds_front_init(pmds_front *f, long fs_in, double if_hz)
{
    pmds_event_fn on_event = f->dm.fr.on_event;
    void *ev_ctx = f->dm.fr.ev_ctx;
    pmds_bit_fn on_bit = f->dm.on_bit;
    void *bit_ctx = f->dm.bit_ctx;
    int strict = f->dm.fr.strict;
    long g;
    memset(f, 0, sizeof *f);
    f->dm.fr.on_event = on_event;
    f->dm.fr.ev_ctx = ev_ctx;
    f->dm.on_bit = on_bit;
    f->dm.bit_ctx = bit_ctx;
    f->dm.fr.strict = strict;
    if (fs_in <= 0)
        return -1;
    g = gcd_(PMDS_FS, fs_in);
    f->fs_in = fs_in;
    f->up = (int)(PMDS_FS / g);
    f->down = (int)(fs_in / g);
    if (f->up > PMDS_RS_MAX_TAPS)
        return -1;
    design(f);
    if (f->tpp > PMDS_RS_MAX_TPP || f->tpp * f->up > PMDS_RS_MAX_TAPS)
        return -1;
    f->if_hz = if_hz;
    f->carrier_db = -999.0;
    pll_reset(f);
    acquire_reset(f);
    pmds_demod_init(&f->dm);
    return 0;
}

void pmds_front_retune(pmds_front *f, double if_hz)
{
    f->if_hz = if_hz;
    memset(f->rhist, 0, sizeof f->rhist);
    memset(f->lhist, 0, sizeof f->lhist);
    f->out_n = 0;
    f->carrier_db = -999.0;
    pll_reset(f);
    acquire_reset(f);
    pmds_demod_init(&f->dm);
}

/* one sample at 6000 Hz, on its way from the resampler */
static void at_6k(pmds_front *f, pmds_cplx y)
{
    pmds_cplx v, o;
    double err, c, s;
    int k, p;
    if (f->state == 0) {                                 /* finding the carrier */
        f->acq_re += y.re * f->acq_prev.re + y.im * f->acq_prev.im;   /* y * conj(prev) */
        f->acq_im += y.im * f->acq_prev.re - y.re * f->acq_prev.im;
        f->acq_pw += y.re * y.re + y.im * y.im;
        f->acq_prev = y;
        if (++f->acq_n >= ACQ_N) {
            double step = atan2(f->acq_im, f->acq_re);   /* radians a sample */
            f->if_hz += step * PMDS_FS / (2 * M_PI);
            f->carrier_db = 10 * log10(f->acq_pw / ACQ_N + 1e-30);
            f->acq_n = 0;
            f->acq_re = f->acq_im = f->acq_pw = 0;
            if (++f->acq_round >= ACQ_ROUNDS) {
                f->state = 1;
                pll_reset(f);
            }
        }
        return;
    }
    /* the carrier PLL */
    c = cos(f->pll_ph);
    s = sin(f->pll_ph);
    v.re = (pmds_real)(y.re * c + y.im * s);             /* y * e^(-j phase) */
    v.im = (pmds_real)(y.im * c - y.re * s);
    err = atan2(v.im, v.re);
    f->pll_w += f->pll_b * err;
    if (f->pll_w > f->pll_wmax) f->pll_w = f->pll_wmax;
    if (f->pll_w < -f->pll_wmax) f->pll_w = -f->pll_wmax;
    f->pll_ph += f->pll_w + f->pll_a * err;
    if (f->pll_ph > M_PI) f->pll_ph -= 2 * M_PI;
    if (f->pll_ph < -M_PI) f->pll_ph += 2 * M_PI;
    /* the low-pass, then the decoder */
    f->lhist[f->lpos] = v;
    f->lpos = (f->lpos + 1) % PMDS_LP_TAPS;
    o.re = o.im = 0;
    for (k = 0, p = f->lpos; k < PMDS_LP_TAPS; k++, p = (p + 1) % PMDS_LP_TAPS) {
        o.re += f->lp[k] * f->lhist[p].re;
        o.im += f->lp[k] * f->lhist[p].im;
    }
    f->out[f->out_n++] = o;
    if (f->out_n == (int)(sizeof f->out / sizeof f->out[0])) {
        pmds_demod_process(&f->dm, f->out, f->out_n);
        f->out_n = 0;
        /* frequency the PLL has had to build up goes to the mixer, where there's no limit */
        if (fabs(f->pll_w) > 2 * M_PI * HANDOFF_HZ / PMDS_FS) {
            f->if_hz += f->pll_w * PMDS_FS / (2 * M_PI);
            f->pll_w = 0.0;
        }
    }
}

void pmds_front_process(pmds_front *f, const pmds_cplx *x, int n)
{
    int i, j, p;
    double inc = f->if_hz / (double)f->fs_in;
    for (i = 0; i < n; i++) {
        pmds_cplx m;
        double c, s;
        /* the mixer: x * e^(-j 2 pi if t), its phase kept in cycles */
        c = cos(2 * M_PI * f->nco_ph);
        s = sin(2 * M_PI * f->nco_ph);
        m.re = (pmds_real)(x[i].re * c + x[i].im * s);
        m.im = (pmds_real)(x[i].im * c - x[i].re * s);
        f->nco_ph += inc;
        f->nco_ph -= floor(f->nco_ph);
        /* the resampler */
        f->rhist[f->rpos] = m;
        while (f->rt_acc < f->up) {
            const pmds_real *h = f->h + f->rt_acc * f->tpp;
            pmds_cplx y;
            y.re = y.im = 0;
            for (j = 0, p = f->rpos; j < f->tpp; j++) {  /* newest first */
                y.re += h[j] * f->rhist[p].re;
                y.im += h[j] * f->rhist[p].im;
                p = p ? p - 1 : f->tpp - 1;
            }
            at_6k(f, y);
            inc = f->if_hz / (double)f->fs_in;          /* acquisition or the PLL may move it */
            f->rt_acc += f->down;
        }
        f->rt_acc -= f->up;
        f->rpos = (f->rpos + 1) % f->tpp;
    }
}

void pmds_front_process_i16(pmds_front *f, const int16_t *iv, const int16_t *qv, int n)
{
    pmds_cplx buf[128];
    while (n > 0) {
        int k, m = n < 128 ? n : 128;
        for (k = 0; k < m; k++) {
            buf[k].re = (pmds_real)(iv[k] / 32768.0);
            buf[k].im = (pmds_real)(qv[k] / 32768.0);
        }
        pmds_front_process(f, buf, m);
        iv += m;
        qv += m;
        n -= m;
    }
}
