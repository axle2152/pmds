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
 * pmds_framer.c - block sync, single-bit correction and group parsing for compact framing,
 * with one station at a time. A line-for-line port of CompactFramer in pmds/framer.py; the
 * comments there explain the rules. The specification is docs/PMDS_Draft_Specification
 * sections 4, 5, 8 and 9.
 */
#include <string.h>
#include "pmds.h"

#define POLY      0x8CFu
#define K_BITS    11
#define LOSE_BAD  7
#define LOSE_OF   10
#define SLIP_AFTER 2
#define ALERT_HOLD 20.0
#define ALERT_WINDOW 5
#define GROUP_BITS 94
#define END_CODE  0x0D

#define M(k)       (1u << (k))
#define BLOCK1     (M(PMDS_CORE1) | M(PMDS_RT1) | M(PMDS_EXT1))
#define BLOCK2     (M(PMDS_CORE2) | M(PMDS_RT2) | M(PMDS_EXT2))
#define ALL_KINDS  (BLOCK1 | BLOCK2)

static const uint16_t OFFSET[7] = {0, 0x185, 0x3CB, 0x066, 0x1BF, 0x03D, 0x007};
static int8_t single_[2048];                   /* syndrome of a 1-bit error -> its bit, or -1 */
static int single_ready = 0;

static uint16_t syndrome(uint64_t v)
{
    int i;
    for (i = 46; i >= K_BITS; i--)
        if ((v >> i) & 1u)
            v ^= (uint64_t)POLY << (i - K_BITS);
    return (uint16_t)v;
}

static void build_single(void)
{
    int j;
    memset(single_, -1, sizeof single_);
    for (j = 0; j < PMDS_N; j++)
        single_[syndrome((uint64_t)1 << j)] = (int8_t)j;
    single_ready = 1;
}

static int kind_of(uint16_t s)
{
    int k;
    for (k = 1; k <= 6; k++)
        if (OFFSET[k] == s)
            return k;
    return 0;
}

static unsigned after(int kind)
{
    return (kind & 1) ? M(kind + 1) : BLOCK1;
}

static double now(pmds_framer *f) { return f->now ? f->now(f->now_ctx) : 0.0; }

static void emit(pmds_framer *f, pmds_event *ev)
{
    if (f->on_event) {
        ev->t = now(f);
        f->on_event(f->ev_ctx, ev);
    }
}

static void emit_simple(pmds_framer *f, int kind)
{
    pmds_event ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = kind;
    emit(f, &ev);
}

/* G0 codes the table leaves undefined show as a space; compare and show them that way */
static uint8_t norm(uint8_t c) { return pmds_g0_utf8(c)[0] ? c : 0x20; }

/* ---- state ----------------------------------------------------------------------------- */
static void clear_station(pmds_framer *f)
{
    pmds_station *s = &f->st;
    int has_pi = s->has_pi;
    uint16_t pi = s->pi;
    memset(s, 0, sizeof *s);
    s->has_pi = has_pi;
    s->pi = pi;
    s->pty = s->tp = s->ta = s->af_flag = -1;
    memset(f->ps_part_ok, 0, sizeof f->ps_part_ok);
    memset(f->ps_cand_ok, 0, sizeof f->ps_cand_ok);
    memset(f->rt_seg_ok, 0, sizeof f->rt_seg_ok);
    f->has_ab = 0;
    f->rt_wait_n = 0;
    memset(f->ext_cand_ok, 0, sizeof f->ext_cand_ok);
    f->alert_cand = 0;
    f->alert_cand_core = 0;
    f->alert_cand_t = -1e9;
    f->alert_off = 0;
    f->alert_last = -1e9;
}

static void cands_clear(pmds_cand *c)
{
    int i;
    for (i = 0; i <= PMDS_N; i++)
        c[i].nb = -1;
}

void pmds_framer_init(pmds_framer *f)
{
    double (*nowf)(void *) = f->now;
    void *now_ctx = f->now_ctx, *ev_ctx = f->ev_ctx;
    pmds_event_fn on_event = f->on_event;
    int strict = f->strict;
    if (!single_ready)
        build_single();
    memset(f, 0, sizeof *f);
    f->now = nowf; f->now_ctx = now_ctx; f->on_event = on_event; f->ev_ctx = ev_ctx;
    f->strict = strict;
    f->last_group_t = -1.0;
    cands_clear(f->cands);
    cands_clear(f->slips);
    clear_station(f);
    f->st.has_pi = 0;
}

static void sync_(pmds_framer *f, int on)
{
    if (on != f->synced) {
        emit_simple(f, on ? PMDS_EV_SYNC : PMDS_EV_NOSYNC);
        if (on)
            f->syncs++;
        f->rt_wait_n = 0;
        f->ours = 0;
    }
    f->synced = on;
}

static void mark(pmds_framer *f, int status)
{
    f->results[f->res_pos] = (uint8_t)status;
    f->res_pos = (f->res_pos + 1) % 50;
    if (f->res_n < 50)
        f->res_n++;
    if (status == 0) f->clean++;
    else if (status == 1) f->fixed++;
    else f->lost++;
}

static int result_back(const pmds_framer *f, int i)   /* i = 0: the newest */
{
    return f->results[(f->res_pos - 1 - i + 100) % 50];
}

static int lost_run(const pmds_framer *f)
{
    int i, n = 0;
    for (i = 0; i < f->res_n; i++) {
        if (result_back(f, i) != 2)
            break;
        n++;
    }
    return n;
}

static void counted(pmds_framer *f)
{
    f->groups++;
    f->last_group_t = now(f);
    f->group_t[f->gt_pos] = f->last_group_t;
    f->gt_pos = (f->gt_pos + 1) % 64;
    if (f->gt_n < 64)
        f->gt_n++;
}

double pmds_framer_rate(const pmds_framer *f)
{
    double t = f->now ? f->now(f->now_ctx) : 0.0;
    int i, c = 0;
    for (i = 0; i < f->gt_n; i++)
        if (f->group_t[i] > t - 20.0)
            c++;
    return c / 20.0;
}

static double share(const pmds_framer *f, int status)
{
    int i, c = 0;
    if (!f->res_n)
        return 0.0;
    for (i = 0; i < f->res_n; i++)
        if (result_back(f, i) == status)
            c++;
    return 100.0 * c / f->res_n;
}
double pmds_framer_bler(const pmds_framer *f) { return share(f, 2); }
double pmds_framer_fixed(const pmds_framer *f) { return share(f, 1); }

/* ---- alerts ---------------------------------------------------------------------------- */
static void alert_seen(pmds_framer *f, int on, int level, int core)
{
    double t = now(f);
    if (on) {
        if (f->alert_cand == level && (core || f->alert_cand_core) &&
                t - f->alert_cand_t <= ALERT_WINDOW * (double)GROUP_BITS / PMDS_BIT_RATE) {
            if (!f->st.alert)
                f->st.alert_t = t;
            f->st.alert = level;
            f->alert_last = t;
        }
        f->alert_cand = level;
        f->alert_cand_core = core;
        f->alert_cand_t = t;
        f->alert_off = 0;
    } else {
        f->alert_cand = 0;
        f->alert_cand_core = 0;
        if (f->st.alert) {
            f->alert_off++;
            if (f->alert_off >= 2) {
                f->st.alert = 0;
                f->alert_off = 0;
            }
        }
    }
}

void pmds_framer_tick(pmds_framer *f)
{
    if (f->st.alert && now(f) - f->alert_last > ALERT_HOLD) {
        f->st.alert = 0;
        f->alert_off = 0;
    }
}

/* ---- the station's fields --------------------------------------------------------------- */
static int ps_(pmds_framer *f, int seg, const uint8_t half[4], int fixed)
{
    if (fixed && !(f->ps_cand_ok[seg] && !memcmp(f->ps_cand[seg], half, 4))) {
        memcpy(f->ps_cand[seg], half, 4);
        f->ps_cand_ok[seg] = 1;
        return 0;
    }
    memcpy(f->ps_cand[seg], half, 4);
    f->ps_cand_ok[seg] = 1;
    memcpy(f->ps_part[seg], half, 4);
    f->ps_part_ok[seg] = 1;
    if (f->ps_part_ok[0] && f->ps_part_ok[1]) {
        memcpy(f->st.ps, f->ps_part[0], 4);
        memcpy(f->st.ps + 4, f->ps_part[1], 4);
        f->st.has_ps = 1;
    }
    return 1;
}

static void tags(pmds_framer *f)
{
    pmds_station *s = &f->st;
    int i;
    if (!s->has_rtplus || !s->rt_len)
        return;
    for (i = 0; i < 2; i++) {
        int ct = s->rtplus[i][0], st = s->rtplus[i][1], ln = s->rtplus[i][2];
        int a = st, b = st + ln;
        if (!ct)
            continue;
        if (b > s->rt_len) b = s->rt_len;
        while (a < b && s->rt[a] == 0x20) a++;           /* .strip() */
        while (b > a && s->rt[b - 1] == 0x20) b--;
        if (b <= a)
            continue;
        if (ct == 4) {
            memcpy(s->artist, s->rt + a, (size_t)(b - a));
            s->artist_len = b - a;
        } else if (ct == 1) {
            memcpy(s->title, s->rt + a, (size_t)(b - a));
            s->title_len = b - a;
        }
    }
}

static void rt_(pmds_framer *f, int seg, int ab, const uint8_t codes[8])
{
    pmds_station *s = &f->st;
    int i, j, n = 0;
    if (!f->has_ab || ab != f->ab) {                     /* new RadioText: start over */
        memset(f->rt_seg_ok, 0, sizeof f->rt_seg_ok);
        f->ab = ab;
        f->has_ab = 1;
        s->has_rtplus = 0;
    }
    memcpy(f->rt_seg[seg], codes, 8);
    f->rt_seg_ok[seg] = 1;
    for (i = 0; i < 8; i++) {                            /* in order, to the first gap or end */
        int end = -1;
        if (!f->rt_seg_ok[i])
            break;
        for (j = 0; j < 8; j++)
            if (f->rt_seg[i][j] == END_CODE) { end = j; break; }
        for (j = 0; j < (end < 0 ? 8 : end); j++)
            s->rt[n++] = norm(f->rt_seg[i][j]);
        if (end >= 0)
            break;
    }
    while (n > 0 && s->rt[n - 1] == 0x20)                /* .rstrip() */
        n--;
    s->rt_len = n;
}

static void show_core(pmds_framer *f, const pmds_coreshow *c)
{
    if (ps_(f, c->seg, c->half, c->fixed)) {
        f->st.pty = c->pty;
        f->st.tp = c->tp;
        f->st.ta = c->ta;
        f->st.af_flag = c->af;
    }
    alert_seen(f, c->flag && (c->pty == 30 || c->pty == 31), c->pty == 31 ? 2 : 1, 1);
}

/* Is this group from the station on show? A PI is taken once two groups in a row carry it,
 * and everything shown for the previous station goes then. */
static int station(pmds_framer *f, uint16_t pi, const pmds_coreshow *later)
{
    if (f->st.has_pi && pi == f->st.pi) {
        f->has_cand = 1;
        f->pi_cand = pi;
        f->pi_held.valid = 0;
        f->ours = 1;
        return 1;
    }
    if (f->has_cand && pi == f->pi_cand) {
        pmds_rtgroup wait[PMDS_RT_WAIT];
        int wait_n = f->rt_wait_n;
        pmds_coreshow held = f->pi_held;
        memcpy(wait, f->rt_wait, sizeof wait);
        clear_station(f);
        f->st.has_pi = 1;
        f->st.pi = pi;
        memcpy(f->rt_wait, wait, sizeof wait);
        f->rt_wait_n = wait_n;
        f->ours = 1;
        f->pi_held.valid = 0;
        if (held.valid)
            show_core(f, &held);
        return 1;
    }
    f->has_cand = 1;
    f->pi_cand = pi;
    if (later)
        f->pi_held = *later;
    else
        f->pi_held.valid = 0;
    if (f->st.has_pi) {
        f->rt_wait_n = 0;
        f->ours = 0;
    }
    return 0;
}

static void release(pmds_framer *f)
{
    int i, n = f->rt_wait_n;
    pmds_rtgroup wait[PMDS_RT_WAIT];
    memcpy(wait, f->rt_wait, sizeof wait);
    f->rt_wait_n = 0;
    for (i = 0; i < n; i++) {
        rt_(f, wait[i].seg, wait[i].ab, wait[i].codes);
        alert_seen(f, wait[i].level == 1 || wait[i].level == 2, wait[i].level, 0);
    }
    if (n)
        tags(f);
}

static void ext_(pmds_framer *f, uint16_t pi, int typ, uint64_t v, int fixed)
{
    pmds_station *s = &f->st;
    pmds_event ev;
    memset(&ev, 0, sizeof ev);
    ev.kind = PMDS_EV_EXT;
    ev.pi = pi;
    ev.ext_type = typ;
    ev.ext_v = v;
    ev.fixed = fixed;
    if (!s->has_pi || pi != s->pi) {                     /* another station's, or none yet */
        emit(f, &ev);
        return;
    }
    if (fixed && !(f->ext_cand_ok[typ] && f->ext_cand[typ] == v)) {
        f->ext_cand[typ] = v;                            /* a repaired group has to repeat */
        f->ext_cand_ok[typ] = 1;
        return;
    }
    f->ext_cand[typ] = v;
    f->ext_cand_ok[typ] = 1;
    ev.ours = 1;
    if (typ == 0) {
        s->facility_id = (uint32_t)((v >> 28) & 0xFFFFFFu);
        s->has_facility = 1;
    } else if (typ == 1) {
        int i, cnt = (int)((v >> 49) & 7u);
        if (cnt > PMDS_AF_MAX)
            cnt = PMDS_AF_MAX;
        for (i = 0; i < cnt; i++)
            s->af[i] = (uint16_t)((v >> (40 - 9 * i)) & 0x1FFu);
        s->af_count = cnt;
    } else if (typ == 2) {
        int off = (int)((v >> 18) & 31u);
        s->mjd = (uint32_t)((v >> 35) & 0x1FFFFu);
        s->hour = (int)((v >> 30) & 31u);
        s->minute = (int)((v >> 24) & 63u);
        s->offset_half = ((v >> 23) & 1u) ? -off : off;
        s->has_clock = 1;
    } else if (typ == 3) {
        s->rtplus[0][0] = (uint8_t)((v >> 44) & 63u);
        s->rtplus[0][1] = (uint8_t)((v >> 38) & 63u);
        s->rtplus[0][2] = (uint8_t)(((v >> 32) & 63u) + 1);
        s->rtplus[1][0] = (uint8_t)((v >> 26) & 63u);
        s->rtplus[1][1] = (uint8_t)((v >> 20) & 63u);
        s->rtplus[1][2] = (uint8_t)(((v >> 15) & 31u) + 1);
        s->has_rtplus = 1;
        tags(f);
    }
    emit(f, &ev);
}

static void bytes_(uint64_t v, int n, uint8_t *out)
{
    int i;
    for (i = 0; i < n; i++)
        out[i] = (uint8_t)((v >> (8 * (n - 1 - i))) & 0xFFu);
}

static void parse(pmds_framer *f, int type, uint64_t d1, uint64_t d2, int fixed)
{
    pmds_event ev;
    memset(&ev, 0, sizeof ev);
    counted(f);
    if (type == 1) {                                     /* core */
        pmds_coreshow c;
        uint8_t raw[4];
        int i;
        memset(&c, 0, sizeof c);
        c.valid = 1;
        c.seg = (int)((d1 >> 11) & 1u);
        c.pty = (int)((d1 >> 15) & 31u);
        c.tp = (int)((d1 >> 14) & 1u);
        c.ta = (int)((d1 >> 13) & 1u);
        c.af = (int)((d1 >> 12) & 1u);
        c.flag = (int)((d1 >> 10) & 1u);
        c.fixed = fixed;
        bytes_(d2 >> 4, 4, raw);
        for (i = 0; i < 4; i++)
            c.half[i] = norm(raw[i]);
        if (station(f, (uint16_t)(d1 >> 20), &c)) {
            release(f);                                  /* the text heard since the last core */
            show_core(f, &c);
        }
        ev.kind = PMDS_EV_CORE;
        ev.pi = (uint16_t)(d1 >> 20);
        ev.seg = c.seg; ev.pty = c.pty; ev.tp = c.tp; ev.ta = c.ta; ev.flag = c.flag;
        memcpy(ev.text, raw, 4);
        ev.text_len = 4;
        ev.fixed = fixed;
        emit(f, &ev);
    } else if (type == 2) {                              /* RadioText */
        pmds_rtgroup g;
        g.seg = (int)((d1 >> 33) & 7u);
        g.ab = (int)((d1 >> 32) & 1u);
        g.level = (int)(d2 & 3u);
        bytes_(d1, 4, g.codes);
        bytes_(d2 >> 4, 4, g.codes + 4);
        if (f->rt_wait_n == PMDS_RT_WAIT) {              /* keep the newest PMDS_RT_WAIT */
            memmove(f->rt_wait, f->rt_wait + 1, sizeof(pmds_rtgroup) * (PMDS_RT_WAIT - 1));
            f->rt_wait_n--;
        }
        f->rt_wait[f->rt_wait_n++] = g;                  /* no PI in it: a core group vouches */
        if (f->ours)
            release(f);
        ev.kind = PMDS_EV_RT;
        ev.seg = g.seg; ev.ab = g.ab; ev.level = g.level;
        memcpy(ev.text, g.codes, 8);
        ev.text_len = 8;
        ev.fixed = fixed;
        emit(f, &ev);
    } else {                                             /* extended */
        ext_(f, (uint16_t)(d1 >> 20), (int)((d1 >> 16) & 15u),
             ((d1 & 0xFFFFu) << 36) | d2, fixed);
    }
}

static void take(pmds_framer *f, int kind, uint64_t data, int fixed)
{
    f->expect = after(kind);
    if (kind & 1) {                                      /* block 1: wait for block 2 */
        f->group_valid = 1;
        f->group_kind = (kind + 1) / 2;
        f->group_d1 = data;
        f->group_fixed = fixed;
        return;
    }
    if (f->group_valid && f->group_kind == kind / 2) {
        f->group_valid = 0;
        parse(f, kind / 2, f->group_d1, data, f->group_fixed || fixed);
        return;
    }
    f->group_valid = 0;
}

static void miss(pmds_framer *f)
{
    f->group_valid = 0;
    if (f->expect)                                       /* the position still moves on */
        f->expect = (f->expect & BLOCK1) ? BLOCK2 : BLOCK1;
}

static pmds_cand *slot(pmds_cand *ring, long nb) { return &ring[nb % (PMDS_N + 1)]; }

static void slip_hunt(pmds_framer *f, long nb, int kind, uint64_t data)
{
    if (kind) {
        pmds_cand *prev = slot(f->slips, nb - PMDS_N);
        if (prev->nb == nb - PMDS_N && (after(prev->kind) & M(kind)) &&
                lost_run(f) >= SLIP_AFTER) {
            f->next_nb = nb + PMDS_N;
            f->held[0] = *prev;
            f->held[1].kind = kind;
            f->held[1].data = data;
            f->held_n = 2;
            f->expect = after(kind);
            f->group_valid = 0;
            f->rt_wait_n = 0;
            f->ours = 0;
            cands_clear(f->slips);
            f->slips_found++;
            emit_simple(f, PMDS_EV_SLIP);
            return;
        }
        slot(f->slips, nb)->kind = kind;
        slot(f->slips, nb)->data = data;
        slot(f->slips, nb)->nb = nb;
    }
}

static void block(pmds_framer *f)
{
    long nb = f->nb;
    uint64_t reg = f->reg;
    uint16_t s = syndrome(reg);
    int kind = kind_of(s);
    uint64_t data = reg >> K_BITS;
    unsigned want;
    int i;

    if (!f->synced) {
        if (kind) {
            pmds_cand *prev = slot(f->cands, nb - PMDS_N);
            if (prev->nb == nb - PMDS_N && (after(prev->kind) & M(kind))) {
                f->next_nb = nb + PMDS_N;                 /* two in a row: probably sync */
                f->res_n = 0;
                f->res_pos = 0;
                f->held[0] = *prev;
                f->held[1].kind = kind;
                f->held[1].data = data;
                f->held_n = 2;
                f->expect = after(kind);
                cands_clear(f->cands);
                sync_(f, 1);
                return;
            }
            slot(f->cands, nb)->kind = kind;
            slot(f->cands, nb)->data = data;
            slot(f->cands, nb)->nb = nb;
        }
        return;
    }
    if (nb < f->next_nb) {
        if (!f->held_n)
            slip_hunt(f, nb, kind, data);
        return;
    }
    f->next_nb = nb + PMDS_N;
    want = f->expect ? f->expect : ALL_KINDS;
    if (f->held_n) {                                     /* the block after sync must be clean */
        pmds_cand held[2];
        int n = f->held_n;
        memcpy(held, f->held, sizeof held);
        f->held_n = 0;
        if (!(kind && (want & M(kind)))) {
            sync_(f, 0);
            return;
        }
        for (i = 0; i < n; i++) {
            mark(f, 0);
            take(f, held[i].kind, held[i].data, 0);
        }
    }
    if (kind && (want & M(kind))) {
        mark(f, 0);
        take(f, kind, data, 0);
    } else {
        int hits = 0, hk = 0, hj = 0, k;
        if (!f->strict)
            for (k = 1; k <= 6; k++)
                if (want & M(k)) {
                    int j = single_[s ^ OFFSET[k]];
                    if (j >= 0) {
                        hits++;
                        hk = k;
                        hj = j;
                    }
                }
        if (hits == 1) {
            mark(f, 1);
            take(f, hk, (reg ^ ((uint64_t)1 << hj)) >> K_BITS, 1);
        } else {
            mark(f, 2);
            miss(f);
        }
    }
    if (f->res_n >= LOSE_OF) {
        int bad = 0;
        for (i = 0; i < LOSE_OF; i++)
            if (result_back(f, i) == 2)
                bad++;
        if (bad >= LOSE_BAD) {
            sync_(f, 0);
            f->held_n = 0;
            cands_clear(f->cands);
            f->expect = 0;
            f->group_valid = 0;
        }
    }
}

void pmds_framer_push(pmds_framer *f, int bit)
{
    f->reg = ((f->reg << 1) | (uint64_t)(bit & 1)) & (((uint64_t)1 << PMDS_N) - 1);
    f->nb++;
    if (f->nb >= PMDS_N)
        block(f);
}
