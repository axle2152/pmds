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
 * pmds.h - the PMDS receiver in portable C, for microcontrollers and PCs.
 *
 * A port of the reference decoder in pmds/demod.py and pmds/framer.py: compact framing at
 * 93.75 bit/s only. Plain C99, no allocation, no operating system, no GNU Radio code.
 *
 * Two ways in:
 *   pmds_front  complex I/Q at any whole-number sample rate (44100 on a Teensy), with the
 *               station a known offset from 0 Hz (the low IF, 12 kHz in the prototype). It
 *               moves the station to 0 Hz, resamples to exactly 6000 Hz, finds the carrier's
 *               frequency, locks a slow (about 1 Hz) carrier PLL and feeds the decoder.
 *   pmds_demod  the decoder alone: complex samples at exactly 6000 Hz with the carrier
 *               already locked onto the real axis (what pmds.Demodulator takes).
 *
 * What the radio shows is in pmds_station (demod.fr.st). Text fields are RDS G0 codes;
 * pmds_g0_utf8() turns a code into UTF-8 for a display.
 */
#ifndef PMDS_H
#define PMDS_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* double by default: the Teensy 4's Cortex-M7 does double precision in hardware. Build with
 * -DPMDS_REAL=float for a chip that only has single precision. */
#ifndef PMDS_REAL
#define PMDS_REAL double
#endif
typedef PMDS_REAL pmds_real;
typedef struct { pmds_real re, im; } pmds_cplx;

#define PMDS_FS        6000          /* the decoder's own sample rate, Hz */
#define PMDS_BIT_RATE  93.75
#define PMDS_SPB       64            /* samples per bit at PMDS_FS */
#define PMDS_N         47            /* bits per block */
#define PMDS_LOCAL     (4 * PMDS_SPB)  /* local carrier reference: 4 bits */
#define PMDS_CANCEL    (8 * PMDS_SPB)  /* leak canceller window: 8 bits */
#define PMDS_RT_MAX    64
#define PMDS_AF_MAX    5
#define PMDS_RT_WAIT   8             /* RadioText groups kept waiting for a core group */

/* block kinds */
enum { PMDS_K_NONE = 0, PMDS_CORE1, PMDS_CORE2, PMDS_RT1, PMDS_RT2, PMDS_EXT1, PMDS_EXT2 };

/* ---- what a radio shows ----------------------------------------------------------------- */
typedef struct {
    int      has_pi;   uint16_t pi;
    int      has_ps;   uint8_t  ps[8];          /* G0 codes */
    uint8_t  rt[PMDS_RT_MAX]; int rt_len;       /* G0 codes, in order up to the first gap or
                                                   the end mark, trailing spaces removed */
    int      pty, tp, ta, af_flag;              /* -1 until a core group has set them */
    int      alert;                             /* 0 none, 1 test, 2 emergency */
    double   alert_t;                           /* when it began, seconds of signal */
    int      has_facility; uint32_t facility_id;
    int      af_count; uint16_t af[PMDS_AF_MAX]; /* band bit | code: pmds_af_text() */
    int      has_clock; uint32_t mjd; int hour, minute, offset_half;  /* local offset, half hours */
    int      has_rtplus; uint8_t rtplus[2][3];  /* (content type, start, length) x 2 */
    uint8_t  artist[PMDS_RT_MAX]; int artist_len;
    uint8_t  title[PMDS_RT_MAX];  int title_len;
} pmds_station;

/* ---- what the framer reports as it goes (optional, for logs and monitors) ---------------- */
enum { PMDS_EV_CORE = 1, PMDS_EV_RT, PMDS_EV_EXT, PMDS_EV_SYNC, PMDS_EV_NOSYNC, PMDS_EV_SLIP };
typedef struct {
    int      kind;          /* PMDS_EV_* */
    double   t;             /* seconds of signal */
    int      fixed;         /* a bit was repaired in this group */
    uint16_t pi;            /* core and extended groups */
    int      seg, ab;       /* PS half (core) or RadioText segment and A/B flag (rt) */
    int      pty, tp, ta, flag, level;   /* core: PTY, TP, TA, alert flag; rt: alert level */
    uint8_t  text[8]; int text_len;      /* core: 4 PS characters; rt: 8 characters (raw codes) */
    int      ext_type;      /* extended: the type */
    uint64_t ext_v;         /* extended: the 52-bit payload */
    int      ours;          /* extended: its PI is the station on show */
} pmds_event;

typedef void (*pmds_event_fn)(void *ctx, const pmds_event *ev);
typedef void (*pmds_bit_fn)(void *ctx, double t, double v, int bit);

/* ---- the framer: block sync, correction, groups, one station at a time ------------------- */
typedef struct { int kind; long nb; uint64_t data; } pmds_cand;
typedef struct { int seg, ab, level; uint8_t codes[8]; } pmds_rtgroup;
typedef struct { int valid, seg, pty, tp, ta, af, flag, fixed; uint8_t half[4]; } pmds_coreshow;

typedef struct pmds_framer {
    pmds_station st;
    /* public counters */
    int      synced;
    long     clean, fixed, lost, groups, slips_found, syncs;
    double   last_group_t;
    int      strict;                           /* no correction: every damaged block is lost */
    /* bits and blocks */
    uint64_t reg; long nb, next_nb;
    pmds_cand cands[PMDS_N + 1], slips[PMDS_N + 1];
    pmds_cand held[2]; int held_n;
    unsigned expect;                           /* mask of block kinds, 0 = any */
    int      group_valid, group_kind, group_fixed; uint64_t group_d1;
    uint8_t  results[50]; int res_n, res_pos;  /* recent blocks: 0 clean, 1 fixed, 2 lost */
    double   group_t[64]; int gt_n, gt_pos;
    /* the station on show */
    int      has_cand; uint16_t pi_cand; pmds_coreshow pi_held; int ours;
    int      ps_part_ok[2], ps_cand_ok[2]; uint8_t ps_part[2][4], ps_cand[2][4];
    int      rt_seg_ok[8]; uint8_t rt_seg[8][8]; int ab, has_ab;
    pmds_rtgroup rt_wait[PMDS_RT_WAIT]; int rt_wait_n;
    int      ext_cand_ok[16]; uint64_t ext_cand[16];
    int      alert_cand, alert_cand_core, alert_off; double alert_cand_t, alert_last;
    /* hooks */
    double  (*now)(void *ctx); void *now_ctx;
    pmds_event_fn on_event; void *ev_ctx;
} pmds_framer;

void pmds_framer_init(pmds_framer *f);
void pmds_framer_push(pmds_framer *f, int bit);
void pmds_framer_tick(pmds_framer *f);        /* once a bit, after push: alert timeout */
double pmds_framer_rate(const pmds_framer *f); /* groups a second over the last 20 s */
double pmds_framer_bler(const pmds_framer *f); /* % of the last 50 blocks lost */
double pmds_framer_fixed(const pmds_framer *f);/* % of the last 50 blocks repaired */

/* ---- the decoder: 6000 Hz, carrier on the real axis -------------------------------------- */
typedef struct pmds_demod {
    pmds_framer fr;
    int      cancel;                           /* leak canceller on (default) */
    /* slow carrier, for the floor only */
    pmds_cplx c; int c_init;
    /* local carrier reference over PMDS_LOCAL samples */
    pmds_cplx zring[PMDS_LOCAL]; int zpos; pmds_real zs_re, zs_im; long zcount;
    /* leak canceller over PMDS_CANCEL samples */
    pmds_real er[PMDS_CANCEL], dr[PMDS_CANCEL], tr[PMDS_CANCEL]; int cpos; pmds_real eprev;
    pmds_real se, sd, st_, see, sdd, sed, set_, sdt, stt; long ccount;
    /* matched filter and bit timing */
    pmds_real tmpl[PMDS_SPB], thring[PMDS_SPB]; int thpos;
    pmds_real row[PMDS_SPB]; int rown;
    pmds_real E[PMDS_SPB]; int best; long n, last;
    double   t; int t_set;
    pmds_real amp, var;
    pmds_bit_fn on_bit; void *bit_ctx;
} pmds_demod;

void pmds_demod_init(pmds_demod *d);
void pmds_demod_process(pmds_demod *d, const pmds_cplx *z, int n);
double pmds_demod_now(const pmds_demod *d);  /* seconds of signal */
double pmds_demod_dev_deg(const pmds_demod *d);
double pmds_demod_snr_db(const pmds_demod *d);
double pmds_demod_cn_db(const pmds_demod *d); /* C/N in 10 kHz as the data sees it; < -900 = unknown */

/* ---- the front end: any whole-number rate, station at a known offset ---------------------- */
#define PMDS_RS_MAX_TAPS 4096                  /* resampler prototype, all phases */
#define PMDS_RS_MAX_TPP  320                   /* taps per phase */
#define PMDS_LP_TAPS     49                    /* 500 Hz low-pass at 6000 Hz */

typedef struct pmds_front {
    pmds_demod dm;
    long     fs_in; int up, down;
    double   if_hz;                            /* where the station sits now, after corrections */
    double   nco_ph;                           /* low-IF mixer phase, cycles */
    pmds_real h[PMDS_RS_MAX_TAPS]; int tpp;    /* resampler prototype, tpp taps per phase */
    pmds_cplx rhist[PMDS_RS_MAX_TPP]; int rpos; int rt_acc;
    pmds_real lp[PMDS_LP_TAPS]; pmds_cplx lhist[PMDS_LP_TAPS]; int lpos;
    /* frequency acquisition, then the carrier PLL */
    int      state;                            /* 0 finding the carrier, 1 locked */
    int      acq_round; long acq_n; pmds_real acq_re, acq_im, acq_pw; pmds_cplx acq_prev;
    double   pll_ph, pll_w, pll_a, pll_b, pll_wmax;
    double   carrier_db;                       /* carrier level, dB relative to full scale 1.0 */
    pmds_cplx out[64]; int out_n;
} pmds_front;

/* fs_in: the input rate in Hz; if_hz: where the station's carrier sits in the input (for
 * example +12000). Returns 0, or -1 if fs_in can't be resampled to 6000 Hz within the
 * filter's limits. */
int  pmds_front_init(pmds_front *f, long fs_in, double if_hz);
void pmds_front_process(pmds_front *f, const pmds_cplx *x, int n);
void pmds_front_process_i16(pmds_front *f, const int16_t *i, const int16_t *q, int n);
void pmds_front_retune(pmds_front *f, double if_hz); /* forget the station, look again */

/* ---- text ---------------------------------------------------------------------------------- */
const char *pmds_g0_utf8(uint8_t code);       /* "" for a code G0 doesn't define */
int  pmds_text_utf8(const uint8_t *codes, int n, char *out, int outsize); /* returns length */
int  pmds_pi_to_call(uint16_t pi, char out[5]);  /* 1 and the call letters, or 0 */
uint16_t pmds_call_to_pi(const char *call);      /* 0 if it isn't a US call */
int  pmds_af_text(uint16_t entry, char *out, int outsize);       /* "95.5 MHz" / "750 kHz" */
void pmds_mjd_to_date(uint32_t mjd, int *year, int *month, int *day);

#ifdef __cplusplus
}
#endif
#endif
