# Designing a PMDS-capable AM radio

Discussion notes alongside the draft specification (version 0.2). Informative only: they reason
from the specification, the reference receiver and public chip documentation. Apart from the
SDR reference receiver, none of the routes below has been tried in hardware.

## 1. The one hard requirement: see the carrier's phase

PMDS changes only the carrier's phase and leaves its envelope exactly as it was (spec section 3).
An envelope detector, the diode or its equivalent in every classic AM radio, outputs the
envelope and nothing else, so its output carries no trace of the data. No firmware can recover
what the detector has already thrown away. A radio whose only path is an envelope detector
cannot decode PMDS without new hardware.

What a radio needs instead is the channel as I and Q (the signal's in-phase and quadrature
parts), or a phase detector locked to the carrier. Many newer radios already have one of these,
even when the audio comes out of an envelope detector:

- **DSP radio chips** (low-IF or zero-IF digital receivers) turn the channel into I/Q numbers
  internally; envelope detection is just one calculation on them.
- **Car radio tuners built for HD Radio or DAB** send the channel as digital I/Q to a separate
  baseband processor.
- **HD Radio receivers** have to demodulate relative to the analog carrier, because the AM
  hybrid's digital carriers are placed in quadrature with it.
- **Older radios with a synchronous detector** lock an oscillator to the carrier, and their
  phase detector sees the carrier's phase.
- **C-QUAM AM stereo radios** decode L−R from the carrier's phase.
- **SDRs** have I/Q by definition; the reference receiver is one.

## 2. Radio types and their route to PMDS

| Radio type | Phase available? | Route to PMDS | Who has to act |
|---|---|---|---|
| Analog superhet, envelope detector (classic transistor radio) | No | None without new hardware | — |
| Single-chip DSP radio (portable or table radio) | Inside the chip | A firmware patch for the chip's DSP; decoded blocks handed to the radio's microcontroller, for example through the registers the chip already uses for FM RDS | The chip maker, then the radio maker |
| Car tuner with digital I/Q output for an HD Radio or DAB processor | Yes, on a digital bus | Decoder software on the processor that already receives the I/Q; no tuner change | The radio maker (and the baseband vendor if that processor is closed) |
| HD Radio receiver, on AM | Yes, coherent by design | Decoder software in the HD Radio baseband | The baseband vendor and licensor |
| Radio with an analog synchronous detector | Yes, at the PLL's phase detector | Tap the phase-error signal into a small microcontroller (see section 3, item 1) | A hardware change, small |
| C-QUAM AM stereo radio | Yes, in the L−R path | Tap L−R before the stereo switch into a small microcontroller | A hardware change, small |
| SDR | Yes | Software only (this repository) | — |

**Single-chip radios.** In these the demodulator runs on the chip's own DSP from the maker's
firmware, so only the chip maker can add a mode. There is a precedent: the SSB patch for the
Si4735-D60 and Si4732-A10, which the radio's microcontroller downloads into the chip at start-up
and which adds a demodulation mode the chip's ROM doesn't have
([PU2CLR Si4735 library](https://pu2clr.github.io/SI4735/extras/apidoc/html/patch__full_8h_source.html)).
Whether a given family can take a PMDS patch, and whether its maker would write one, is a
question for each vendor.

**Car radios with a separate baseband processor** look like the easiest route. Several
automotive tuners send baseband I/Q over a digital interface to an external HD Radio decoder:
the odd-numbered Si476x parts
([Silicon Labs Si476x datasheet](https://www.mouser.com/datasheet/2/472/Si476x_short-2507984.pdf)),
ST's TDA7706 ([ST](https://www.st.com/en/automotive-infotainment-and-telematics/tda7706.html))
and TDA7786 ([ST](https://st.com/en/automotive-infotainment-and-telematics/tda7786.html)), and
ST's STA709 SDR front end, which streams complex baseband to an application processor
([ST](https://st.com/en/automotive-infotainment-and-telematics/sta709.html)). In those designs
the phase is already on a bus going to a processor that runs updatable software. One thing to
check per design: whether that I/Q still flows when the radio is tuned to an AM station with no
HD Radio signal.

**HD Radio.** The AM hybrid places its complementary digital carriers so that their sum has no
component in phase with the analog carrier
([US 6,292,511](https://patents.google.com/patent/US6292511),
[US 5,859,876](https://patents.google.com/patent/US5859876)), so an HD Radio receiver has to
demodulate relative to the carrier's phase. That is the reference PMDS needs. Hybrid stations
themselves remain out of scope (spec section 1) until tested.

**C-QUAM radios.** A C-QUAM decoder (for example Motorola's MC13028A
([datasheet](https://www.amstzone.org/MC13028.pdf))) recovers L−R from the carrier's phase, so
on a PMDS station its L−R path carries the data. A C-QUAM radio switches to stereo only when it
detects the 25 Hz pilot, which PMDS doesn't send, so it stays in mono and the listener hears
nothing of it. Not yet tried on the bench.

## 3. What the decoder needs

These follow spec section 9 and the reference receiver.

1. **A slow carrier reference.** Coarse frequency acquisition, then a phase-locked loop of about
   1 Hz. The acquisition range has to cover the station's tolerance, ±20 Hz
   ([47 CFR 73.1545](https://federal-regs.com/title/47/part-73/73.1545/)), plus the radio's own
   crystal error: ±50 ppm is ±85 Hz at 1700 kHz. The reference receiver finds the carrier in an
   FFT, then tracks it within ±60 Hz. A faster loop follows part of the data and cancels it;
   4 Hz was already too fast. Synchronous detectors built for audio use much faster loops, often
   tens of Hz, to ride through fades, so they can't be reused as they are. Above its loop
   bandwidth, though, a PLL's phase-error signal *is* the phase modulation. A sync detector with
   a loop well below 47 Hz would deliver the data at its phase detector output.
2. **The right measurement.** The quadrature component divided by the local carrier's power,
   not the raw phase angle and not the quadrature divided by the instantaneous envelope
   (spec section 9, item 2).
3. **A modest sample rate.** The data stays within about ±200 Hz of the carrier, so complex
   samples at about 1.5 kHz (16 per bit) after a ±500 Hz low-pass are enough. The reference
   uses 6 kHz.
4. **The same kind of framing as RDS.** Syndrome check, block sync, slip recovery, at most one
   corrected bit per block (spec sections 4 and 9). A tuner with an RDS decoder already has
   this logic, with a different polynomial, offsets and block length.
5. **Little computing power.** One bit rate at the reference's 6 kHz takes roughly a million
   simple operations a second, and a few kilobytes of memory. That fits a small microcontroller
   or a corner of a tuner DSP. RDS, by comparison, demodulates a 57 kHz subcarrier at
   1187.5 bit/s, more than twelve times PMDS's 93.75 bit/s.

## 4. What in a radio can spoil the phase

- **Asymmetric filtering.** If the IF or channel filter isn't centred on the carrier, or isn't
  symmetric, the upper and lower sidebands are treated differently, and the program's AM turns
  partly into phase on top of the data. Digital channel filters are symmetric by construction.
  Analog IF filters (ceramic, LC) have to be centred, and radios that shift the IF away from an
  adjacent station make it worse. This is probably the main thing to test in existing radios.
- **Oscillator phase noise** between about 1 Hz and 200 Hz from the carrier adds straight to the
  data's noise. Crystal-referenced synthesizers at medium-wave frequencies are normally far
  below what matters at 8.6 degrees; free-running analog oscillators may not be.
- **Fast frequency control.** Automatic frequency control or carrier-locking features have to be
  much slower than the data, for the same reason as the PLL in section 3.
- **AGC.** Gain changes are harmless as long as they don't shift phase. Analog front ends whose
  tuning shifts with AGC (varactor-tuned stages) are worth checking.
- **Night multipath** is unavoidable. The decoder is designed for it (spec section 11).

## 5. The audio side

Plain synchronous detectors hear a faint steady tone at twice the bit rate (spec section 10). A
PMDS radio has no reason to: it knows the phase modulation it has just decoded, so it can remove
it before synchronous detection, or use envelope detection for audio on strong signals.

## 6. Display and alerts

PMDS fields keep their RBDS meanings: PI (with the same call-letter derivation), PS, RadioText,
PTY, clock, RT+ (spec section 5). A radio can translate decoded PMDS groups into the RBDS group
types its display software already handles, so it can reuse its RDS screens. Alert handling
follows spec section 8.

## 7. Open questions for radio makers

- Which consumer AM radio chips could take a PMDS firmware patch, and which already expose I/Q?
- In car radios with digital I/Q output, does the I/Q flow on AM stations without HD Radio?
- Does an HD Radio receiver's coherent AM path give a usable reference on a station with no
  digital carriers?
- How much phase does program audio leak into the data through typical analog IF filters, and
  through a typical car radio's narrowing AM filter?
- Can the L−R output of a C-QUAM radio decode PMDS on the bench?
