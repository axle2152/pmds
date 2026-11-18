// Copyright 2026 Michael Foley
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
// except in compliance with the License. You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software distributed under the
// License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
// either express or implied. See the License for the specific language governing permissions
// and limitations under the License.
/*
  teensy_rx - the PMDS decoder on a Teensy 4.1

  Step 2 of the prototype radio: decode I/Q recordings from the SD card, with no radio
  hardware yet. Every .WAV file in the card's top folder is decoded in turn, as fast as the
  Teensy can go, and what a radio would show is printed to the Serial Monitor, with how much
  of the processor the decoder needed.

  The files: 2-channel 16-bit WAV, I on the left and Q on the right, the station's carrier
  IF_HZ above 0 Hz. c/make_test_iq.py makes a set (see firmware/README.md).

  The decoder itself is the C port in src/pmds, a copy of the repository's c/ folder
  (c/sync_firmware.py refreshes it; tests/test_pmds.py checks the copy is current).
*/
#include <SD.h>
#include "src/pmds/pmds.h"

#define IF_HZ        12000.0     // where the carrier sits in the recordings
#define SHOW_GROUPS  1           // 1: print every group as it decodes; 0: only the status lines
#define STATUS_SECS  10.0        // a status line every this many seconds of signal

static pmds_front front;         // the whole receiver, about 63 KB
static int16_t frames[2 * 512];  // interleaved I/Q from the card
static int16_t iv[512], qv[512];
static double next_status;

// ---- printing ------------------------------------------------------------------------------
static void printCodes(const uint8_t *codes, int n)
{
  char buf[400];
  pmds_text_utf8(codes, n, buf, sizeof buf);
  Serial.print(buf);
}

static void printTime(double t)
{
  char buf[16];
  snprintf(buf, sizeof buf, "%7.1f s  ", t);
  Serial.print(buf);
}

static void printStation()
{
  const pmds_station *s = &front.dm.fr.st;
  char call[5], buf[96];
  printTime(pmds_demod_now(&front.dm));
  Serial.print(front.dm.fr.synced ? "IN SYNC  " : "no sync  ");
  if (s->has_pi) {
    snprintf(buf, sizeof buf, "%04X %s  ", s->pi, pmds_pi_to_call(s->pi, call) ? call : "----");
    Serial.print(buf);
  }
  if (s->has_ps) {
    Serial.print("\"");
    printCodes(s->ps, 8);
    Serial.print("\"  ");
  }
  if (s->alert)
    Serial.print(s->alert == 2 ? "*** ALERT ***  " : "*** TEST ***  ");
  snprintf(buf, sizeof buf, "data %.1f deg  SNR %.1f dB  %.0f%% fixed  %.0f%% lost",
           pmds_demod_dev_deg(&front.dm), pmds_demod_snr_db(&front.dm),
           pmds_framer_fixed(&front.dm.fr), pmds_framer_bler(&front.dm.fr));
  Serial.println(buf);
  if (s->rt_len) {
    Serial.print("            Text: ");
    printCodes(s->rt, s->rt_len);
    Serial.println();
  }
}

static void onEvent(void *ctx, const pmds_event *e)
{
  (void)ctx;
  char buf[96], call[5];
  if (!SHOW_GROUPS && e->kind != PMDS_EV_SYNC && e->kind != PMDS_EV_NOSYNC)
    return;
  printTime(e->t);
  switch (e->kind) {
  case PMDS_EV_CORE:
    snprintf(buf, sizeof buf, "core  PI %04X %-4s  PTY %2d  PS[%d] \"", e->pi,
             pmds_pi_to_call(e->pi, call) ? call : "----", e->pty, e->seg);
    Serial.print(buf);
    printCodes(e->text, 4);
    Serial.print("\"");
    if (e->flag) Serial.print("  ALERT FLAG");
    break;
  case PMDS_EV_RT:
    snprintf(buf, sizeof buf, "text  seg %d %c  \"", e->seg, e->ab ? 'B' : 'A');
    Serial.print(buf);
    printCodes(e->text, 8);
    Serial.print("\"");
    if (e->level) Serial.print(e->level == 2 ? "  alert: emergency" : "  alert: test");
    break;
  case PMDS_EV_EXT:
    if (!e->ours) {
      snprintf(buf, sizeof buf, "ext   type %d for PI %04X: not the station on show", e->ext_type, e->pi);
      Serial.print(buf);
    } else if (e->ext_type == 0) {
      snprintf(buf, sizeof buf, "ext   facility ID %lu", (unsigned long)front.dm.fr.st.facility_id);
      Serial.print(buf);
    } else if (e->ext_type == 1) {
      Serial.print("ext   FM/AM translator:");
      for (int i = 0; i < front.dm.fr.st.af_count; i++) {
        pmds_af_text(front.dm.fr.st.af[i], buf, sizeof buf);
        Serial.print(" ");
        Serial.print(buf);
      }
    } else if (e->ext_type == 2) {
      const pmds_station *s = &front.dm.fr.st;
      int y, m, d;
      pmds_mjd_to_date(s->mjd, &y, &m, &d);
      snprintf(buf, sizeof buf, "ext   clock %04d-%02d-%02d %02d:%02d UTC", y, m, d, s->hour, s->minute);
      Serial.print(buf);
    } else if (e->ext_type == 3) {
      const pmds_station *s = &front.dm.fr.st;
      Serial.print("ext   song: ");
      printCodes(s->artist, s->artist_len);
      Serial.print(" / ");
      printCodes(s->title, s->title_len);
    } else {
      snprintf(buf, sizeof buf, "ext   type %d", e->ext_type);
      Serial.print(buf);
    }
    break;
  case PMDS_EV_SYNC: Serial.print("sync found"); break;
  case PMDS_EV_NOSYNC: Serial.print("sync lost"); break;
  case PMDS_EV_SLIP: Serial.print("slip followed"); break;
  }
  if (e->fixed) Serial.print("  (1 bit fixed)");
  Serial.println();
}

// ---- WAV files ---------------------------------------------------------------------------------
static uint32_t le32(const uint8_t *p) { return p[0] | p[1] << 8 | p[2] << 16 | (uint32_t)p[3] << 24; }
static uint16_t le16(const uint8_t *p) { return p[0] | p[1] << 8; }

// Finds the format and the start of the data. Returns the sample rate, or 0 if the file
// isn't 2-channel 16-bit PCM.
static long openWav(File &f, uint32_t *dataBytes)
{
  uint8_t hdr[12], ck[8], fmt[16];
  long rate = 0;
  if (f.read(hdr, 12) != 12 || memcmp(hdr, "RIFF", 4) || memcmp(hdr + 8, "WAVE", 4))
    return 0;
  while (f.read(ck, 8) == 8) {
    uint32_t len = le32(ck + 4);
    if (!memcmp(ck, "fmt ", 4)) {
      if (f.read(fmt, 16) != 16) return 0;
      if (le16(fmt) != 1 || le16(fmt + 2) != 2 || le16(fmt + 14) != 16) return 0;
      rate = le32(fmt + 4);
      f.seek(f.position() + len - 16 + (len & 1));
    } else if (!memcmp(ck, "data", 4)) {
      *dataBytes = len;
      return rate;
    } else {
      f.seek(f.position() + len + (len & 1));
    }
  }
  return 0;
}

static void decodeFile(File &f)
{
  uint32_t bytes = 0, done = 0;
  uint32_t busy = 0;                        // microseconds spent in the decoder
  long rate = openWav(f, &bytes);
  Serial.println();
  Serial.print("==== ");
  Serial.println(f.name());
  if (!rate) {
    Serial.println("not a 2-channel 16-bit WAV file: skipped");
    return;
  }
  if (pmds_front_init(&front, rate, IF_HZ)) {
    Serial.println("this sample rate can't be resampled to 6000 Hz: skipped");
    return;
  }
  front.dm.fr.on_event = onEvent;
  next_status = STATUS_SECS;
  while (done < bytes) {
    int want = sizeof frames, got;
    if (bytes - done < (uint32_t)want) want = bytes - done;
    got = f.read((uint8_t *)frames, want);
    if (got <= 0) break;
    done += got;
    int n = got / 4;
    for (int k = 0; k < n; k++) {
      iv[k] = frames[2 * k];
      qv[k] = frames[2 * k + 1];
    }
    uint32_t t0 = micros();
    pmds_front_process_i16(&front, iv, qv, n);
    busy += micros() - t0;
    if (pmds_demod_now(&front.dm) >= next_status) {
      printStation();
      next_status += STATUS_SECS;
    }
  }
  double secs = done / 4.0 / rate;
  char buf[160];
  Serial.println("---- at the end");
  printStation();
  snprintf(buf, sizeof buf, "Blocks: %ld clean, %ld fixed, %ld lost. Groups: %ld of about %.0f sent.",
           front.dm.fr.clean, front.dm.fr.fixed, front.dm.fr.lost, front.dm.fr.groups, secs * 93.75 / 94);
  Serial.println(buf);
  snprintf(buf, sizeof buf, "Carrier found %.1f Hz from where it was expected. %.1f s of signal decoded in "
           "%.2f s: the decoder needs %.1f%% of the processor.", front.if_hz - IF_HZ, secs, busy / 1e6,
           100.0 * busy / 1e6 / secs);
  Serial.println(buf);
}

// ---- Arduino -----------------------------------------------------------------------------------
void setup()
{
  Serial.begin(115200);
  while (!Serial && millis() < 4000) {
  }
  Serial.println("PMDS decoder on a Teensy 4.1: decoding the WAV files on the SD card");
  if (!SD.begin(BUILTIN_SDCARD)) {
    Serial.println("No SD card found. Put the test files on a microSD card, insert it, and press the "
                   "Teensy's button to load the program again.");
    return;
  }
  File root = SD.open("/");
  int files = 0;
  for (File f = root.openNextFile(); f; f = root.openNextFile()) {
    const char *name = f.name();
    size_t len = strlen(name);
    if (!f.isDirectory() && len > 4 && !strcasecmp(name + len - 4, ".wav")) {
      decodeFile(f);
      files++;
    }
    f.close();
  }
  Serial.println();
  Serial.println(files ? "All files decoded." : "No .WAV files in the card's top folder.");
}

void loop()
{
}
