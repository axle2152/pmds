# PMDS Draft Specification, version 0.2

Michael Foley, KK4EKN · last revised Nov 10, 2026

## 1. Scope and status

This draft defines PMDS (Phase Modulation Data Service, working name): station identity, text, program type and an alert flag carried as slow phase modulation of a mono AM broadcast carrier, at 93.75 bit/s with 8.6 degrees (0.15 rad) peak deviation. It is a discussion draft; nothing in it is final or endorsed by any body.

- **Stations:** mono AM (amplitude modulation, A3E) stations in the US AM band. Stations broadcasting C-QUAM AM stereo are excluded, since stereo uses the same carrier phase. HD Radio hybrid stations are out of scope until tested.
- **Normative and informative:** sections 2 to 8 are normative; SHALL and SHOULD carry their usual meaning there. Sections 9 onward and the appendices are informative.
- **Reference implementation:** the `pmds` package (encoder, decoder and framing in Python and numpy, no GNU Radio needed) under the Apache License 2.0, with GNU Radio blocks and bench tools around it (`pmds_encoder.py`, `pmds_addon.py`, `pmds_channel_test.py`, `pmds_check.py`) under GPL 3.0 or later. Where this text and the code disagree, this text is the intent and the code is a bug.

## 2. References

PMDS takes its field meanings from RBDS and defines only how they are carried; these documents are referenced, not reproduced.

| Reference | Used for |
| --- | --- |
| IEC 62106 series (RDS), basic character set G0 | The 8-bit character table (section 6) |
| IEC 62106-9, RBDS (successor to NRSC-4-B) | Program type codes, PI derivation from US call letters, RT+ content types, AF code meaning for FM |
| ISO 3901 | ISRC format |
| [47 CFR 73.127](https://www.law.cornell.edu/cfr/text/47/73.127) | AM multiplex transmissions; the audibility and no-degradation conditions |
| [47 CFR 11.45](https://www.law.cornell.edu/cfr/text/47/11.45) | No EAS codes or attention signal outside real alerts and tests |
| [ETSI TS 102 386](https://www.etsi.org/deliver/etsi_ts/102300_102399/102386/01.01.01_60/ts_102386v010101p.pdf) (AMSS) | Prior art for the physical layer and block size; not a dependency |
| [ITU-R BS.706-1](https://itu.int/dms_pubrec/itu-r/rec/bs/R-REC-BS.706-1-199203-S!!MSW-E.doc) (AMDS, 1992) | Prior art: data by phase modulation of the main carrier on LF and MF, up to 200 bit/s, with example systems at 25 bit/s biphase ±22.5°, 40 bit/s ±28.5° and 200 bit/s ±15°; revised as BS.706-2 in 1998; not a dependency |
| [BBC RD 1984/19](https://downloads.bbc.co.uk/rd/pubs/reports/1984-19.pdf), L.F. radio-data | Prior art in long service: biphase phase modulation of BBC Radio 4's 198 kHz carrier at 25 bit/s, ±22.5°, from 1985 until the 198 kHz transmitters closed on 30 June 2026 ([history](https://en.wikipedia.org/wiki/Radio_teleswitch)) |
| [US 3,714,375](https://patents.google.com/patent/US3714375A/en) (Collins Radio, 1970) | Prior art for the core principle: a secondary phase-modulated communications service carried by AM broadcast stations; expired |
| [US 4,688,255](https://patents.google.com/patent/US4688255A/en) (L. R. Kahn, 1984) | Prior art for the core principle: a compatible AM broadcast and data transmission system; expired |
| [US 4,117,405](https://patents.google.com/patent/US4117405A/en) and related patents (Martinez, 1976 to 1982) | Prior art: narrow-band phase modulation of an AM broadcast carrier for data, paging, utility load control and public alerts, with the bit clock divided down from the carrier; expired |
| [EP 0347541](https://patents.google.com/patent/EP0347541A1/en) and [EP 0367897](https://patents.google.com/patent/EP0367897A2/en) (Licentia, 1988) | Prior art, the closest single precedent: "AM-RDS", biphase-coded, digitally shaped data phase-modulated onto long-, medium- and shortwave broadcast carriers within ±30°, at about 97.6 to 195 bit/s, carrying programme identity and name, programme type, AF lists, traffic, alarms and time. The second application traces audibility to PM-to-AM conversion on receiver IF filter skirts. Never granted |
| [US 5,444,720](https://patents.google.com/patent/US5444720A/en) (Telefunken, 1990) | Prior art: RDS-style fields (PI, PS, AF, TP, TA, RadioText) in repeating groups on an AM carrier's phase; expired |
| CCIR Report 1061, *Recommendations and Reports of the CCIR*, Dubrovnik 1986, Vol. X Part 1 | Prior art in an ITU publication: the BBC system (25 bit/s biphase, ±22.5°, 50-bit blocks with a 13-bit CRC, on air from October 1981 with no listener complaints) and an East German system at up to 100 bit/s on a high-power broadcast transmitter |
| [EP 1079557](https://patents.google.com/patent/EP1079557A2/en) (Deutsche Telekom, 1999) | States as known art that the RDS protocol was carried on long wave as phase modulation of a carrier; never granted |

PMDS is a new format, not a profile of AMDS or AMSS; those systems are cited only for comparison. The BBC service is the strongest precedent: a phase-modulated data signal on a national broadcast carrier for four decades, with its parameters [chosen](https://www.sigidwiki.com/images/2/29/1984-19.pdf) so that domestic receivers were not disturbed. The closest design precedent is Licentia's 1988 AM-RDS: the same kinds of fields, biphase data and a bit rate near PMDS's, on the carrier phase of AM broadcast transmitters. What PMDS adds is a complete, open specification for US medium-wave stations, with RBDS field meanings, a measured deviation limit and a tested reference receiver.

## 3. Physical layer

Data SHALL be carried only on the carrier's phase, as one sine cycle of phase per bit, leaving the envelope exactly as the station's AM modulator made it. In complex baseband, with A(t) the station's envelope (1 + m(t)):

```math
s(t) = A(t)\, e^{\,j\theta(t)}, \qquad \theta(t) = \Delta\,(2b_k - 1)\,\sin\!\left(\frac{2\pi\,(t - kT)}{T}\right), \quad kT \le t < (k+1)T
```

A 1 bit swings the phase forward (a phase advance) for the first half of the bit and back for the second; a 0 bit does the reverse. The phase is zero at every bit boundary, so the waveform is continuous and has no energy at DC.

| Parameter | Value |
| --- | --- |
| Bit rate 1/T | 93.75 bit/s (T = 10.667 ms) |
| Bit rate accuracy | Within 50 ppm; it SHOULD be derived from the transmitter's frequency reference |
| Peak deviation Δ | 8.6 degrees (0.15 rad) nominal and maximum, held constant. Lower values down to 5 degrees are permitted, at a cost at night (section 11). The maximum keeps the synchronous-detector tone 45 dB below 100% modulation (section 10) |
| Envelope | Unchanged by the data, to the precision of the encoder's arithmetic |
| Transmission | Continuous, group after group, while the service is on |
| Occupied spectrum | About 99% of the data's power within ±200 Hz of the carrier |
| Carrier frequency | Unaffected: the mean phase is zero |

The phase modulation SHALL be applied ahead of the transmitter's final stage (in the exciter, or between the frequency source and the RF input) so that the audio chain is untouched. The transmitter's own incidental phase modulation SHOULD be below 3 degrees peak at 95% modulation.

## 4. Blocks and check code

Every block is 47 bits: 36 data bits followed by an 11-bit check word, sent most significant bit first. Two blocks make a group; the check word's offset says which kind of block it is, which also gives the receiver block sync.

```math
c(x) = \left[\, d(x)\, x^{11} \bmod g(x) \,\right] \oplus o(x), \qquad g(x) = x^{11} + x^{7} + x^{6} + x^{3} + x^{2} + x + 1 \;\;(\text{0x8CF})
```

Here d(x) is the 36 data bits and o(x) the offset word. A received block is valid when the remainder of all 47 bits divided by g(x) equals one of the offset words. At this length g(x) has minimum distance 4: it detects every error of 1 to 3 bits and every burst up to 11 bits, and allows single-bit correction with double errors still detected. It was chosen by exhaustive search as the 11-bit polynomial with the fewest undetectable 4-bit errors at 47 bits.

| Block | Offset word | Group type |
| --- | --- | --- |
| core1 | 0x185 | Core, block 1 |
| core2 | 0x3CB | Core, block 2 |
| rt1 | 0x066 | RadioText, block 1 |
| rt2 | 0x1BF | RadioText, block 2 |
| ext1 | 0x03D | Extended, block 1 |
| ext2 | 0x007 | Extended, block 2 |

The offsets were chosen so that no 1-bit or 2-bit error can turn one block type into another, and so that neither an all-zeros nor an all-ones block looks valid. A group's block 2 SHALL carry the offset matching its block 1.

## 5. Groups

There are three group types: core (station identity and half the name), RadioText (8 characters of text), and extended (one of several slower fields, chosen by a 4-bit type). Bit numbers count down from 35, the first bit sent in each block's data. Reserved bits SHALL be sent as 0 and ignored on receipt.

**Core group**

| Block | Bits | Field |
| --- | --- | --- |
| 1 | 35 to 20 | PI, 16 bits |
| 1 | 19 to 15 | PTY, 5 bits |
| 1 | 14 | TP |
| 1 | 13 | TA |
| 1 | 12 | AF list exists |
| 1 | 11 | PS segment: 0 = characters 1 to 4, 1 = characters 5 to 8 |
| 1 | 10 | Alert flag |
| 1 | 9 to 0 | Reserved |
| 2 | 35 to 4 | 4 PS characters, 8 bits each |
| 2 | 3 to 0 | Reserved |

**RadioText group**

| Block | Bits | Field |
| --- | --- | --- |
| 1 | 35 to 33 | Segment address, 0 to 7 (8 characters each, 64 in all) |
| 1 | 32 | Text A/B flag: changes whenever the text changes |
| 1 | 31 to 0 | Characters 1 to 4 of the segment |
| 2 | 35 to 4 | Characters 5 to 8 of the segment |
| 2 | 3 to 2 | Reserved |
| 2 | 1 to 0 | Alert level: 0 none, 1 test, 2 emergency, 3 reserved (section 8) |

**Extended group**

Block 1 bits 35 to 32 give the type; the remaining 32 bits of block 1 and all 36 of block 2 form a 68-bit payload, numbered 67 (first sent) down to 0.

| Type | Field | Payload bits |
| --- | --- | --- |
| 0 | Station ID | 67 to 44 FCC facility ID (24) · 43 to 36 extended country code (0xA0 = USA) |
| 1 | AF list | 67 to 65 count, 0 to 6 · then up to 6 entries of 9 bits from bit 64 down: band bit (0 = FM, 1 = AM) and an 8-bit code. FM code = (MHz − 87.5) × 10, the RDS AF code; AM code = (kHz − 530) / 10 + 1 |
| 2 | Clock | 67 to 51 Modified Julian Day (17) · 50 to 46 hour, UTC · 45 to 40 minute · 39 offset sign (1 = west of UTC) · 38 to 34 local offset in half hours (the RDS clock-time layout) |
| 3 | RT+ | 67 item toggle · 66 item running · 65 to 60 tag 1 type · 59 to 54 tag 1 start · 53 to 48 tag 1 length minus 1 · 47 to 42 tag 2 type · 41 to 36 tag 2 start · 35 to 31 tag 2 length minus 1 (types: 1 = ITEM.TITLE, 4 = ITEM.ARTIST) |
| 4 | Content ID | 67 to 16 ISRC, 52 bits: country 2 × 5 bits (A = 0), registrant 3 × 6 bits (0 to 9, then A to Z = 10 to 35), year 7 bits, designation 17 bits |
| 5 to 15 | Reserved | Receivers SHALL ignore them |

## 6. Characters and text

All text SHALL use the RDS basic character set G0 of IEC 62106, 8 bits a character, the same table RBDS uses, so accented letters (á, Ñ, ü and others) are available.

- **PS:** 8 characters, sent as two 4-character segments. It SHOULD be upper case and SHOULD stay fixed; song titles belong in RadioText, and a scrolling PS would update only every 4 seconds.
- **RadioText:** up to 64 characters. A text shorter than 64 SHALL end with 0x0D, the rest of that segment padded with spaces (0x20). The A/B flag SHALL change whenever the text changes, and transmission of the new text SHALL start at segment 0.
- **Characters outside G0:** an encoder SHOULD send an accented letter G0 lacks as its plain letter, and anything else as a space.
- **RT+:** tags SHALL point inside the RadioText currently on the air. The item toggle changes with each new item.

Two positions in published copies of the G0 table are ambiguous (0x8D, and 0x9D with 0xA4); the reference code reads them as ß and the Turkish ğ / Ğ. That reading is to be confirmed against IEC 62106 itself.

## 7. Transmission schedule

Core and RadioText groups alternate, and every 8th group is an extended group; at 94 bits a group lasts 1.003 s. The extended slots alternate between news (the clock when a new minute has begun, then RT+ and ISRC, each sent twice after it changes) and a rotation (station ID, AF list, ISRC, RT+ in turn), so a song change cannot hold up the station ID for long.

| Field | Requirement | Reference encoder |
| --- | --- | --- |
| Core group | At least 1 in every 3 groups | Every other group, not counting extended slots |
| Whole PS (both halves) | At least every 6 s | Every 4 s |
| Whole RadioText (64 characters) | No requirement | About 18 s |
| Station ID | At least every 60 s when a facility ID is set | About every 32 s; first after about 16 s |
| AF list | At least every 60 s when one exists | About every 32 s |
| Clock | Within 20 s after each minute begins, from a GPS or NTP disciplined clock | First news slot of each minute |
| RT+, ISRC | Twice within 30 s of a change | Twice, in the next news slots |

During an alert the extended groups pause (section 8).

## 8. Alerts

While an emergency alert is on the air, every core group SHALL carry the alert flag and PTY 31 (RBDS Emergency), or PTY 30 (Emergency Test) for a test, and RadioText SHALL carry the alert's text.

1. **Start:** when the station's EAS equipment begins relaying an alert, set the flag and the PTY in core groups and the alert level in RadioText groups, so every group on the air signals the alert.
2. **Text:** break the alert text into pages of up to 64 characters, between words. Send each page completely twice, then the next; each new page changes the A/B flag.
3. **Extended groups** pause for the alert, so the text gets their time.
4. **End:** clear the flag and the RadioText alert level, and restore the station's normal PTY and RadioText.

No field SHALL carry an EAS header, SAME codes or the attention signal, in any form. The alert is a flag and a program-type code in this format only.

**Receiver behavior (informative).** A receiver SHOULD treat an alert as on after one clean group that signals it (a core group with the flag set and PTY 30 or 31, or a RadioText group with alert level 1 or 2), or two repaired ones in a row. It SHOULD treat it as off after two groups in a row that don't signal it, and SHOULD let it time out after 20 s with no confirming group. What it then does is for receiver makers and regulators; a reasonable default:

| Alert | Suggested behavior |
| --- | --- |
| PTY 31 with flag | Break in over other sources, raise the volume, show the text; the driver can turn break-in off |
| PTY 30 with flag | Show a message only |

There is no location targeting. A receiver SHOULD NOT assume an alert applies to it because it can hear the station: a large AM station covers several states at night.

## 9. Receiver guidance (informative)

The reference receiver's choices below were each settled by testing; a different design is fine if it does as well.

1. **Carrier reference.** Lock a slow PLL (about 1 Hz) to the carrier, then measure the phase against a local carrier estimate averaged over the last 4 bits. A 4 Hz PLL was found to follow and cancel part of the data. The local estimate fixed most losses in fast flutter with bass-heavy program (46% to 98% of groups decoded).
2. **What to measure.** Use the quadrature component divided by the local carrier's power, not the raw phase angle (which spins in a modulation trough) and not the quadrature divided by the instantaneous envelope (which multiplies noise in troughs).
3. **Bit recovery.** Low-pass to about ±500 Hz, apply a matched filter one bit long (one sine cycle), and sample at the bit phase with the most matched-filter energy. This tracked a transmitter clock 80 ppm off.
4. **Data SNR and C/N.** The matched-filter SNR is C/N in 10 kHz + 20 log10(Δ in rad) + 10 log10(10 kHz × T), that is C/N + 3.8 dB at 8.6 degrees and 93.75 bit/s, within about 0.5 dB in simulation from 6 to 20 dB C/N. A receiver can show C/N worked back from the data SNR: it counts noise and interference in the data's own band, which a wideband noise-floor estimate can miss.
5. **Block sync.** Sync on two valid blocks 47 bits apart in a legal order, and confirm it only when the next block is also valid. Drop sync when 7 of the last 10 blocks fail.
6. **Slips.** While in sync, keep checking the bit positions between block boundaries. When samples are dropped or the bit timing jumps in a fade, blocks at the old boundaries fail while clean ones appear at a new position. After 2 lost blocks in a row, 2 clean blocks one block apart in a legal order move sync there, still confirmed by the next block. It costs a few more syndrome checks per bit, well within any RDS-class decoder, and cut each dropped-sample glitch from about 3.5 s of lost blocks to about 1.2 s.
7. **Correction.** Repair at most 1 bit per block, and only against the block type expected at that position. A strict mode with no repair is useful for diagnostics.
8. **Confirmation.** Accept PI, PS halves and extended fields from a repaired group only when the next copy agrees.
9. **Display.** Show PS once both halves are in. Show RadioText progressively, in segment order up to the first gap or the end mark; clear it on an A/B change, and clear everything on a PI change. Call letters come from the PI by the RBDS method; the facility ID is for online lookups.
10. **AF.** Handing off to the listed FM translator as the AM signal fades at night is the receiver's choice.

This version defines one bit rate. The reference receiver also listens at 23.4375, 46.875 and 187.5 bit/s, for comparison on the bench. 23.4375 bit/s is not a candidate for the air: one sine cycle per bit puts its energy at 23.4 Hz, beside the 25 Hz C-QUAM stereo pilot (section 10).

## 10. Compatibility and limits (informative)

Envelope-detector radios hear nothing on a clean signal by construction. Synchronous detectors hear a steady tone at twice the bit rate, and that tone, not the night rumble, sets the deviation limit.

| Case | Effect | Basis |
| --- | --- | --- |
| Envelope-detector radios, clean signal | None: the envelope is unchanged | By construction; bench |
| Envelope-detector radios, night multipath | Multipath turns some phase into AM: a low rumble, mostly masked by program. At 8.6 degrees, simulated two-path night with bass-heavy program: median −28 dB and worst second −18 dB relative to 100% modulation, 60 to 400 Hz (the program sits near −10 dB there), about 5 dB below the 15-degree figures. A C.Crane CC Pocket barely showed it up to 30 degrees. On the bench at 8.6 degrees, through the sky-wave simulator, the bleed-through was heard in some sky-wave conditions, more the worse the conditions, and alike on the CC Pocket, the HDR-16 and the all-mode-receiver tuner; on groundwave the CC Pocket played nothing | Simulation; listening |
| Synchronous detectors, clean signal | Output follows envelope × cos(phase): a steady 187.5 Hz tone (twice the bit rate), the same for every bit, at −35 dB relative to 100% modulation at 15 degrees, −42 dB at 10, −45 dB at 8.6, −49 dB at 7 and −54 dB at 5. On a Sangean HDR-16 with no program it was audible at 15 degrees, near the noise floor at 7 and lost in it at 5. At 8.6 degrees, on a strong signal (full strength on the radio's meter, an estimated 40 dB C/N or better), it can just be heard, largely masked by the hiss; with program or music it cannot be heard at all. The all-mode-receiver tuner played a fainter tone and the CC Pocket none (see the note below the table) | Calculated; listening |
| C-QUAM stereo stations | Not possible: stereo uses the same phase | By design |
| C-QUAM stereo radios | Their L−R path carries the data. They stay mono unless the data passes for the 25 Hz pilot. In the all-mode-receiver tuner's C-QUAM decoder, 23.4375 bit/s trips the pilot detector at once (a 15% reading, 59 dB over its neighbourhood, against 1.5% and 10 dB). At 93.75 bit/s the readings sit at the detector's 10 dB threshold: at 30 dB C/N it never latched in 60 s on the steady, mush, night1, night2 or flutter presets, and latched once on the disturbed preset. The tuner's PMDS decoder holds it in mono once PMDS decodes | Simulation; hardware C-QUAM radios untested |
| HD Radio hybrid stations | Unknown | Untested |
| DSP tuners whose AM noise reduction uses the quadrature channel as its noise reference | Unknown. Such noise reduction assumes the quadrature channel holds only noise; on a PMDS station it holds the data, so the radio may take the data for noise and remove a little low-frequency program with it. C-QUAM stations raise the same issue | Published receiver designs (receiver design notes, section 5); untested |
| Audio watermarks (Nielsen PPM) | None: the audio is not touched | By construction |
| Transmitter IPM | Up to 6 degrees peak made no measurable difference at 8.6 degrees of data, by day or on two-path nights | Simulation |
| Adjacent channels ±10 kHz | No overlap: the data stays within about ±200 Hz of its own carrier | Simulation, earlier format |
| Bass-heavy program, strong night multipath | The largest decoding loss: multipath turns the program's bass into phase on top of the data | Simulation (section 11) |

**A tone from an envelope detector.** The all-mode-receiver tuner's AM audio is the envelope, so a clean PMDS signal should give it no tone, yet the bench showed a faint one. The likely source is the bench transmitter, not the tuner: its carrier sits on the HackRF's own centre frequency, where the transmitter's LO leakage and I/Q imbalance turn some phase into amplitude. Leakage 30 dB below the carrier, at the worst angle, adds an envelope term of the leakage's level times θ(t): a peak of −46 dB, as loud as the synchronous-detector tone, though centred near the bit rate rather than at twice it. Clipping in the RTL-SDR, which it does often on medium wave, is a less likely source, and the transmitter's phase noise and incidental phase modulation change only the phase, which an envelope detector ignores. Untested: repeating the listening with the carrier offset from the HackRF's centre frequency will show it, and until then the HDR-16's tone may include some of the same.

**The synchronous-detector tone.** With θ(t) = ±Δ sin(2πt/T), a synchronous detector's output is

```math
A(t)\cos\theta(t) \approx A(t)\left[\,1 - \frac{\Delta^2}{4} + \frac{\Delta^2}{4}\cos\!\left(\frac{4\pi t}{T}\right)\right]
```

A 1 and a 0 give the same θ², so the tone does not depend on the data: it is a pure line at 2/T, present in every pause in the program, which is why it is heard where the multipath rumble is not. Its level is 20 log10(Δ²/4) with Δ in radians, so halving the deviation lowers the tone 12 dB and costs the data 6 dB.

**Why it sets the limit.** [47 CFR 73.127](https://www.law.cornell.edu/cfr/text/47/73.127) allows signals that are not audible on ordinary consumer receivers and do not degrade the station's programs; it names no detector type. Car radios are now the ordinary consumer receiver, and DSP tuners can detect coherently, so this version sets the deviation by the synchronous-detector tone. The −45 dB limit is provisional until car radios are tested (section 12).

## 11. Measured performance (informative)

At 8.6 degrees, on the medium-wave presets, the station name arrives within 7 s and the text within 28 s in every simulated condition, with ordinary or bass-heavy program. At weaker signals fading sets the limit, not the program. In simulation the data decodes down to a C/N of about 6 dB in 10 kHz, well below where the audio is usable.

| Condition | Flat program: groups / PS / RT | Bass-heavy program: groups / PS / RT |
| --- | --- | --- |
| Daytime groundwave | 99% / 5 s / 18 s | 99% / 5 s / 18 s |
| Mush zone, sky wave 6 dB down | 99% / 5 s / 18 s | 97% / 7 s / 18 s |
| Night, one sky hop | 99% / 5 s / 18 s | 99% / 5 s / 18 s |
| Night, one and two hops | 99% / 5 s / 18 s | 96% / 5 s / 22 s |
| Disturbed night | 98% / 5 s / 18 s | 92% / 5 s / 28 s |
| Sunrise and sunset flutter | 97% / 5 s / 18 s | 97% / 5 s / 18 s |

Compact framing, 93.75 bit/s, 8.6 degrees, mean C/N 30 dB in 10 kHz, the reference receiver with slip recovery (section 9), 3 runs of 180 s per cell. Groups = share of groups sent that decoded; PS and RT = mean seconds until the whole name and the whole 64-character text first appeared. Medium-wave presets (level / delay / Doppler spread): mush zone, ground wave plus a sky wave at −6 dB / 0.33 ms / 0.1 Hz; one hop, 0 dB / 0 ms / 0.1 Hz; one and two hops, that plus −3 dB / 0.2 ms / 0.1 Hz; disturbed, two equal paths 0.3 ms apart fading at 0.3 Hz; flutter, one path at 0.5 Hz. The delays follow from reflection off the E layer about 100 km up: the sky wave's extra path is 2√((d/2)² + h²) − d, 0.33 ms at 150 km, and one hop against two at 1000 km differs by about 0.2 ms. The fading rates are estimates still to be calibrated against night recordings, which will also bring the band's real noise and co-channel stations.

**Weaker signals and the mush zone.** With bass-heavy program, the night presets decoded 84 to 90% of groups at 15 dB C/N and 64 to 77% at 10 dB: Rayleigh fades push the signal under the threshold, and the program plays little part. In the mush zone, groups decoded stayed at 94 to 99% from a sky wave 20 dB below the ground wave to one 5 dB above it.

**Deviation on medium wave.** With bass-heavy program, the disturbed night decoded 96% of groups at 15 degrees, 92% at 8.6 and 86% at 5; every other condition stayed at 93% or better even at 5 degrees.

**Shortwave-style presets.** Draft 0.1 used much harsher presets borrowed from shortwave practice, kept in the simulator as hf\_mush, hf\_night2 and so on: delays of 0.7 to 2 ms and fading at 0.6 to 2 Hz. Under those, every step down in deviation shows with bass-heavy program at night. Share of groups decoded, flat / bass-heavy program, measured before slip recovery was added:

| Condition | 15° | 10° | 8.6° | 7° | 5° |
| --- | --- | --- | --- | --- | --- |
| Daytime groundwave | 99 / 99% | 99 / 99% | 99 / 99% | 99 / 99% | 99 / 99% |
| Mush zone | 94 / 78% | 93 / 69% | 92 / 64% | 92 / 57% | 89 / 38% |
| Night, two sky paths | 89 / 58% | 86 / 35% | 84 / 29% | 82 / 24% | 75 / 10% |
| Disturbed night | 74 / 27% | 72 / 9% | 69 / 5% | 67 / 4% | 56 / 1% |
| Twilight flutter | 99 / 99% | 99 / 97% | 97 / 95% | 95 / 92% | 90 / 86% |

- **Noise, steady signal:** at 8.6 degrees, 98% of groups at 6 dB C/N and 64% at 3 dB (blocks 48% clean, 33% repaired, 19% lost; decoder SNR readout 7.4 dB); none at 0 dB. At 15 degrees, 94% at 0 dB.
- **Bench, 8.6 degrees:** decoding held down to a displayed 12 dB C/N, with the decoder's SNR readout near 10 dB and about half the blocks clean, 30% repaired and 20% lost. PI and PS were always right and RadioText usually completed. Compact framing showed far fewer wrong characters than RBDS framing: text arrives whole or not at all. The tuner of the time read C/N 4.5 dB high (it took the 30th percentile of the noise spectrum as its mean), so the true C/N was about 7.5 dB, and the decoder's SNR readout agrees: 10 dB less the 3.8 dB of section 9, item 4, is about 6 dB. The simulator shows that block mix at 3 dB C/N, so the bench is about 4.5 dB short of it, not the 9 dB first thought (section 12).
- **Bench, longer run, 8.6 degrees:** HackRF transmitter to the all-mode-receiver tuner, program processed to −95% negative and +125% positive peaks: about 20,000 blocks with under 0.1% lost. C/N and path (wired or off air) still to be recorded.
- **Alerts, 8.6 degrees, medium-wave presets:** with the alert level in every group, all 72 test alerts showed (flat and bass-heavy program, groundwave to disturbed night), median 1 s from the start of the alert and worst 4 s, and each cleared 2 s after it ended. No wrong station identity was displayed in any run.

## 12. Open issues

These items stand between this draft and something a station could run.

- [ ] Measure the synchronous-detector tone by FFT (the 187.5 Hz line) on the HDR-16, an SDR's synchronous AM mode and car radios, to confirm the square law and the provisional −45 dB limit (section 10). Move the bench transmitter's carrier off the HackRF's centre frequency first, so the transmitter adds no tone of its own
- [ ] Repeat the 8.6-degree bench test wired (HackRF to RTL-SDR through 40 to 60 dB of attenuation, C/N set by the simulator). Off air the bench needed about 4.5 dB more C/N than the simulator for the same block mix (section 11). That was first put at 9 dB, before the tuner's C/N reading was found to be 4.5 dB high (corrected in November 2026). Likely causes of the rest: common-mode noise and strong stations clipping the RTL-SDR, which it does often on medium wave; the HackRF's own phase noise and incidental phase modulation (the bench readings show the deviation about a degree off); dropped samples, which cost about 3.5 s of blocks each before slip recovery and about 1.2 s with it; and noise near the carrier that a floor measured across the whole capture misses
- [ ] Calibrate the simulator against real night medium-wave recordings, and find where decoding stops at the fringe: PMDS puts about 14 dB less energy into each bit than the BBC's 25 bit/s at ±22.5°
- [ ] Listening tests on a range of consumer radios, car radios above all, written up the way the BBC reported its own (BBC RD 1982/15, LF/MF radio data: compatibility tests), since 47 CFR 73.127 asks for signals not audible on ordinary consumer receivers
- [ ] Test HD Radio hybrid compatibility, or keep it out of scope
- [ ] Check DSP car tuners whose AM noise reduction treats the quadrature channel as noise (section 10)
- [ ] A supervised trial on a licensed AM station under 47 CFR 73.127
- [ ] Define how the encoder takes text and alerts from the connections stations already use for RDS encoders and EAS equipment
- [ ] Confirm the two ambiguous G0 code points against IEC 62106. Also decide on alert spoofing: like PTY 31 on FM's RDS, the alert flag is unauthenticated, and a later version could sign alerts
- [ ] Decide whether a later version adds 46.875 bit/s as a second profile (Appendix B)
- [ ] Check a hardware C-QUAM radio's stereo pilot detector on a PMDS station at 93.75 bit/s, clean and through disturbed night conditions (section 10)
- [ ] Settle the name
- [ ] Decide on the two remaining proposals: a version field in the core group's reserved bits, and confirming an AF by a matching PI on the FM translator (the alert level now rides in every RadioText group)
- [ ] Done: the reference decoder now times PS, RT and alerts per bit, not per processing block
- [ ] Attorney review of prior art and licensing before the repository goes public. A patent search in November 2026 (18 queries, forward citations of the key patents, and the claims of the closest live US families read) found no live US patent claiming the physical layer or the framing; the prior art it found is in section 2
- [ ] When the repository goes public, tag a dated release and deposit it with a public archive (Software Heritage or Zenodo, for example), so its publication date is fixed as prior art

## Appendix A. Test vectors

These blocks come from the reference encoder for a station with call letters WAMD (PI 0x55E3), PS "AM 1650", PTY 4 (Talk) and an AF list. Each 47-bit block is the 36 data bits followed by the 11-bit check word, written in hex; in every one the remainder of the whole block divided by g(x) equals its offset word.

| Group | Block | Data (36 bits) | Check (11 bits) | Whole block (47 bits) |
| --- | --- | --- | --- | --- |
| Core, PS characters 1 to 4 "AM 1" | 1 | 55E321000 | 406 | 2AF190800406 |
| Core, PS characters 1 to 4 "AM 1" | 2 | 414D20310 | 702 | 20A690188702 |
| Core, PS characters 5 to 8 "650 " | 1 | 55E321800 | 3B5 | 2AF190C003B5 |
| Core, PS characters 5 to 8 "650 " | 2 | 363530200 | 588 | 1B1A98100588 |
| Core during an alert (PTY 31, flag set) | 1 | 55E3F9400 | 7D7 | 2AF1FCA007D7 |
| RadioText segment 0 "Hello, A" | 1 | 048656C6C | 0CA | 02432B6360CA |
| RadioText segment 0 "Hello, A" | 2 | 6F2C20410 | 309 | 379610208309 |
| The same, during an emergency alert | 2 | 6F2C20412 | 297 | 379610209297 |
| RadioText segment 1 "M radio" + 0x0D | 1 | 24D207261 | 0ED | 1269039308ED |
| RadioText segment 1 "M radio" + 0x0D | 2 | 64696F0D0 | 111 | 3234B7868111 |
| Station ID, facility 73977 | 1 | 00120F9A0 | 177 | 000907CD0177 |
| Station ID, facility 73977 | 2 | 000000000 | 007 | 000000000007 |
| AF list: 95.5 MHz, 750 kHz | 1 | 14508B800 | 268 | 0A2845C00268 |
| AF list: 95.5 MHz, 750 kHz | 2 | 000000000 | 007 | 000000000007 |
| ISRC USRC17607839 | 1 | 4A49B3019 | 6FE | 2524D980CEFE |
| ISRC USRC17607839 | 2 | 81E9F0000 | 547 | 40F4F8000547 |

The alert core group's block 2 is the same as the first core group's, since only block 1 carries the flag and PTY.

## Appendix B. Alternatives tested

Compact framing at 93.75 bit/s was chosen because it was the only option that was both fast and robust at night; real RBDS groups were tested and kept only for their field meanings.

| Option | Night, two sky paths: groups / PS / RT | Disturbed night: groups / PS / RT | Night leak, median | Verdict |
| --- | --- | --- | --- | --- |
| Compact, 93.75 bit/s | 91% / 4 s / 25 s | 75% / 13 s / 36 s | −23 dB | Adopted |
| Compact, 46.875 bit/s | 62% / 8 s / 74 s | 66% / 22 s / 52 s | −33 dB | Possible second, quieter profile |
| Compact, 187.5 bit/s | 58% / 4 s / 32 s | 21% / 10 s / not complete | −19 dB | Fragile and audible at night; excellent by day |
| RBDS groups, 93.75 bit/s | 90% / 9 s / 57 s | 76% / 19 s / 57 s | −23 dB | Names and text take twice as long |
| RBDS groups, 187.5 bit/s | 69% / 8 s / 43 s | 31% / 52 s / not complete | −19 dB | Matches compact 93.75 by day, loses at night |

Flat program, 15 degrees (the version 0.1 setting), mean C/N 30 dB. The leak column is the envelope change the data causes, 60 to 400 Hz, relative to 100% modulation, with bass-heavy program on the two-path night channel; it depends on the bit rate, not the framing.

RBDS groups are slower because every group repeats the PI and a basic group carries only 2 name characters. On FM the PI repeat lets a radio check an alternate frequency within one block; PMDS's alternate frequency is an FM translator with its own RDS, so the repeat buys nothing here. A 23.4 bit/s option was also tried and dropped: it lost most groups in fast flutter.

The bit rate also sets where the synchronous-detector tone lands, at twice the rate: 93.75 Hz at 46.875 bit/s, 187.5 Hz at the adopted rate, 375 Hz at 187.5 bit/s. Ears and small speakers are much less sensitive at the low end, which is a point for a 46.875 bit/s profile; the BBC's 25 bit/s system put its tone at 50 Hz.

## Revision history

| Version | Date | Changes |
| --- | --- | --- |
| 0.2 | Nov 6, 2026 | Deviation 8.6 degrees nominal and maximum (was 15); synchronous-detector analysis and HDR-16 results (section 10); performance at 8.6 degrees, a deviation sweep and bench results (section 11); ITU-R BS.706 (AMDS), BBC LF radio-data and two expired US patents cited as prior art; reference code renamed PMDS, its core under Apache 2.0; the alert level in every RadioText group; medium-wave simulator presets |
| 0.2 | Nov 8, 2026 | C-QUAM stereo radios (section 10): 23.4375 bit/s passes for the 25 Hz pilot and is not a candidate for the air; 93.75 bit/s is close to the pilot detector's threshold on disturbed nights |
| 0.2 | Nov 9, 2026 | Prior art from the patent search (section 2): Martinez, Licentia AM-RDS, Telefunken, CCIR Report 1061 and Deutsche Telekom; BS.706-2 noted. Noise-reducing DSP tuners and later listening (section 10); a longer bench run (section 11); open issues updated, including an archived public release |
| 0.2 | Nov 10, 2026 | Section 1 names the decoder's current home, `pmds_addon.py`; this Markdown file is now the only copy of the specification. Later listening on the HDR-16, the CC Pocket and the tuner, and a tone the bench transmitter may add itself (section 10); the bench gap is about 4.5 dB, not 9, once the tuner's C/N reading is corrected (sections 11 and 12) |
| 0.1 | Nov 5, 2026 | First draft |
