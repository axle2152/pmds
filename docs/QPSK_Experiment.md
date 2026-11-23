# Experiment: two streams (QPSK) on the carrier's phase

*Branch `experimental-qpsk` only. Not part of the draft specification; main stays BPSK at
93.75 bit/s and 8.6 degrees. November 2026.*

## The idea

Today's PMDS sends one bit as one sine cycle of phase. Seen another way, that is a 93.75 Hz
"subcarrier" on the phase whose sign is the bit, and its two sidebands carry the same
information. QPSK adds a second, independent stream on the same subcarrier at a right angle
(a cosine instead of a sine), so both sidebands carry something different: two bits per
symbol, **187.5 bit/s in about the same band**.

To keep the phase smooth, each symbol is shaped with a root-raised-cosine pulse (roll-off 0.5)
instead of being cut off at the end of its slot. Shaped symbols overlap their neighbours, and
the receiver's matched filter separates them again. The subcarrier is locked to the symbol
clock, so the receiver finds the symbol timing from the fourth power of what its matched
filters read, which peaks where the four QPSK points line up. The details are in
`pmds/qpsk.py`.

The comparison is made three ways:

- **8.6 degrees, the same power.** The data adds the same power to the phase as BPSK does
  today. Each bit then gets half the energy, the price of twice the rate.
- **12.2 degrees, the same energy per bit.** That is 3 dB more power than today.
- **10.2 degrees, in between.** That is 1.5 dB more power than today.

## What changed on this branch

- `pmds/qpsk.py`: the pulse and the two streams.
- `pmds/encoder.py`, `pmds/demod.py`: `modulation='qpsk'` (BPSK is unchanged and stays the
  default). The decoder's local carrier reference is taken three times over for QPSK: once
  wasn't smooth enough and left a 25 dB floor in a clean signal. Its timing is averaged over
  64 symbols instead of 16, which gained 2 to 3 dB on weak signals.
- `pmds_encoder.py` and its copy in `am_data_tx.grc`: a `modulation` setting. The flowgraph's
  bit-rate buttons gain "187.5 QPSK (experimental)", which sets both the rate and QPSK.
- `pmds_addon.py`: the tuner runs one more decoder, QPSK at 187.5 bit/s, beside the others.
  The tuner's window shows "187.5 QPSK bit/s" when it is the one in sync.
- `pmds_channel_test.py --qpsk`, `tests/false_displays.py --rate 187.5`,
  `tests/qpsk_measures.py` (new), and QPSK cases in `tests/test_pmds.py` and
  `tests/test_addon.py`.
- Not changed: the C decoder and the Teensy sketch (still BPSK only; porting waits until the
  waveform is settled), and the specification.

## Results

All in simulation. Nothing here has been on the air or heard on a real radio yet.

### Speed

From the channel test at 30 dB C/N, mean of 3 runs of 180 s per preset.

| | BPSK, today | QPSK |
|---|---|---|
| Bit rate | 93.75 bit/s | 187.5 bit/s |
| Station name shown | 4 to 5 s | 3 s |
| Full 64-character RadioText | 18 to 24 s | 9 to 10 s |
| Alert shown (median) | 2.1 s | 1.2 s |

### Reception

Share of groups decoded, mean of 3 runs of 180 s per preset. Where the RadioText time
differs a lot, it is given as well.

| Case | BPSK 8.6° | QPSK 8.6° | QPSK 10.2° | QPSK 12.2° |
|---|---|---|---|---|
| 30 dB C/N, every preset (steady to disturbed night) | 97 to 99% | 95 to 99% | | 96 to 99% |
| Bass-heavy program, the same presets | 96 to 99% | 93 to 99% | | |
| Night (two paths, night2), 14 dB C/N | 89%, RT 25 s | 83%, RT 13 s | | 90%, RT 10 s |
| Night, 10 dB C/N | 82%, RT 25 s | 67%, RT 29 s | 74%, RT 19 s | 80%, RT 15 s |
| Disturbed night, 10 dB C/N | 71%, RT 50 s | 58%, RT 27 s | 66%, RT 27 s | 75%, RT 14 s |
| Another station 10 dB down on the channel, night1 | 78%, RT 43 s | 78%, RT 15 s | | |
| ... with bass-heavy program, steady | 90% | **22%** | 61% | 81% (2 runs of 120 s) |
| Another PMDS station 6 dB down, night1 | 64%, RT 54 s | 57%, RT 34 s | | |
| Dropped samples, 5 to 300 every 4 to 8 s | 81% | 83% | | |

The weak-signal limit, from `tests/qpsk_measures.py`, groups decoded in 2 minutes of steady
noise:

| C/N in 10 kHz | 2 dB | 3 dB | 4 dB | 5 dB | 6 dB | 7 dB | 8 dB |
|---|---|---|---|---|---|---|---|
| BPSK 8.6° | 39% | 64% | 90% | 98% | 99% | 99% | 99% |
| QPSK 8.6° | 0% | 0% | 1% | 35% | 69% | 89% | 98% |
| QPSK 10.2° | 0% | 9% | 55% | 79% | 94% | 97% | 99% |
| QPSK 12.2° | 18% | 70% | 91% | 98% | 99% | 99% | 99% |

### Audibility

From `tests/qpsk_measures.py` and `pmds_channel_test.py --audibility`.

| | BPSK 8.6° | QPSK 8.6° | QPSK 10.2° | QPSK 12.2° |
|---|---|---|---|---|
| Energy in the C-QUAM pilot zone, 20 to 30 Hz | 2.4% | 0.1% | 0.1% | 0.1% |
| Energy above 150 Hz | 2.5% | 0.7% | 0.7% | 0.7% |
| Peak phase | 8.6° | 11.4° | 13.5° | 16.2° |
| Synchronous detector, steady line (BPSK's 187.5 Hz tone) | −46.8 dB | −58.5 dB | −55.6 dB | −52.5 dB |
| Synchronous detector, everything from 60 to 400 Hz | −45.0 dB | −43.7 dB | −40.8 dB | −37.7 dB |
| Mistuned envelope radio, A-weighted, against BPSK | 0 dB | −4.0 dB | −2.5 dB | −1.0 dB |
| Plain AM radio in night fading, 60 to 400 Hz (median, 3 to 4 presets) | −46.9 to −41.7 dB | 0.3 to 0.6 dB more | 1.6 to 2.0 dB more | about 3 dB more |

The synchronous-detector levels are relative to 100% modulation. The tuner's C-QUAM pilot
test never took QPSK for a pilot (`tests/test_addon.py`).

### False displays

From `tests/false_displays.py`: 200 hours per channel with no alert on the air, then 20 hours
per channel with emergency alerts.

This simulation works at the level of bits: both rates get the same bit errors, so it shows
what twice as many groups an hour does to the framer, not QPSK's 3 dB. The channels are night
fading, heavy fading and a steady weak signal.

| | BPSK, 93.75 bit/s | QPSK, 187.5 bit/s |
|---|---|---|
| False alerts, wrong PI (600 hours) | none | none |
| Wrong half of the name | one per 67 h, one per 67 h, none | one per 20 h, one per 40 h, none |
| Wrong RadioText characters, until the next pass | one per 19, 26 and 86 min | one per 18, 20 and 46 min |
| Wrong facility ID or AF list | none | one facility ID (heavy fading) |
| Emergency alerts shown, night fading: median, 95% | 2.0 s, 7.0 s | 1.0 s, 4.0 s |
| Heavy fading | 4.0 s, 21.1 s, 22 of 898 missed | still running |
| Steady weak signal | 2.0 s, 6.0 s | still running |

A name or RadioText that is wrong for a moment comes about more often per hour at the higher
rate, because more groups go by. The rules that keep false alerts and wrong stations away
hold at both rates.

## What it means

At the same power, QPSK does what was hoped. It doubles the rate, halves the RadioText time,
and shows alerts sooner. Where the signal is decent it holds as many groups as BPSK. Its
spectrum is also cleaner:

- the synchronous detectors' steady 187.5 Hz tone becomes faint noise, 12 dB lower as a line;
- almost nothing falls near the C-QUAM pilot;
- less falls above 150 Hz, where ears and speakers are more sensitive.

The cost is the expected one: each bit has half the energy, so QPSK needs about 3 dB more
signal. Where PMDS is already weakest it decodes fewer groups, at night on a weak signal and
above all with another station on the channel turning the program's bass into phase (22%
against 90%). Even so, in most of the weak cases the RadioText still arrives sooner, because
twice as many groups are sent.

At 12.2 degrees, QPSK is about as robust as BPSK and still twice as fast. But a plain radio in
fading hears 3 dB more of it, and a synchronous detector hears noise 7 dB above today's tone,
though no tone.

So there is no free lunch, as theory says: the gain can go to speed or to margin, not both.
The real question is the ear. Is faint noise on a synchronous detector less noticeable than
today's steady tone, and by how much? Only listening on the bench can answer that.

## Open questions and next steps

1. **Listening on the bench.** Send BPSK and QPSK at 8.6° from the HackRF (the flowgraph's new
   button) and listen on the HDR-16 and the CC Pocket, with talk and quiet music. Then try
   QPSK at 10° and 12.2°.
2. **The second-station-with-bass case.** It is QPSK's weak spot. The leak canceller might be
   tuned for QPSK (a longer window, or fitting after the matched filter).
3. **A middle setting.** 10.2° (half the extra power) lands in between on every measure: about
   1.5 dB short of BPSK on weak signals and 61% in the second-station-with-bass case, for about
   2 dB more sound on a plain radio in fading and 4 dB more noise on a synchronous detector.
   Where to settle, if anywhere, is for the listening tests to decide.
4. If QPSK is kept: port it to the C decoder, write it into the specification, and give the
   changed physical layer its own prior-art check.

## Running it

    python tests/test_pmds.py                         # includes the QPSK cases
    python tests/qpsk_measures.py                     # waveform, weak signal, dropped samples
    python pmds_channel_test.py --qpsk                # every preset; add --dev 12.2, --cn 10, --co -10 ...
    python tests/false_displays.py --rate 187.5
    python tests/test_addon.py                        # includes QPSK through the tuner
