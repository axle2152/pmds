# PMDS: station data for AM radio

PMDS (Phase Modulation Data Service, a working name) lets an AM station send the kind of
information FM stations already send with RDS: the station's name, what's playing, and
emergency alerts. It works on ordinary mono AM stations, and ordinary AM radios don't hear it.

This is an experimental project and a draft specification, not an adopted standard.

## Why

FM has had RDS for decades, so an FM car radio can show the station name, the song and a
traffic or emergency flag. AM in the US has never had anything like it. Congress and the FCC
have been pushing to keep AM in every car, largely because AM reaches people when other systems
fail. An AM radio that can show an alert, not just play one, makes that case stronger.

## How it works, in plain terms

An AM station's sound rides on the **strength** of its carrier: the carrier gets stronger and
weaker with the audio. An ordinary AM radio only pays attention to that strength.

PMDS leaves the strength alone and instead nudges the carrier's **timing** (its phase) a tiny
bit ahead and then behind, about 94 times a second. One nudge pattern means a 1, the opposite
pattern means a 0. The nudges are small, at most 8.6 degrees of a carrier cycle. A radio that
only listens to strength can't tell anything changed; a PMDS radio reads the nudges as data.

What it carries, using the same fields as RDS wherever it can:

| Field | What it's for |
|---|---|
| PI code | The station's identity, worked out from its call letters the same way RBDS does it |
| Station name | 8 characters, like "WSB 750 " |
| RadioText | Up to 64 characters: the song, the show, a short message |
| Program type | News, talk, country and so on (the RBDS list) |
| Alert | An on/off flag with test and emergency levels; the alert's text replaces the RadioText |
| FM translator | The frequency of the station's FM translator, so a radio can switch over at night |
| Station ID | The FCC facility ID, which is unique even when call letters are shared |
| Clock | Date and time, the same way RDS sends it |
| Song tags | Artist and title marked inside the RadioText (RT+), and the recording's ISRC code |

**Speed.** About 94 bits per second, which is slow, but it adds up: the station name shows in
about 5 seconds, a full 64-character text in about 18, and an alert in about 1.

**Errors.** Every block of data carries a check code. The radio can fix a single wrong bit, and
it throws away anything that doesn't check out, so text arrives whole or not at all instead of
showing garbage.

**Effect on the audio.** Ordinary radios hear nothing, by design. Radios with a synchronous
detector (some HD Radio sets and DSP car radios) can hear a faint, steady low tone at 187.5 Hz.
The draft keeps the nudges small enough that the tone stays 45 dB below full modulation.

**Range.** In tests the data keeps decoding until the station's audio is mostly static, so
anywhere people are still listening, the data gets through.

**What a station would need.** A way to phase-modulate the transmitter's RF drive: a small
exciter box for an older transmitter, the way AM stereo (C-QUAM) exciters worked, or a feature
in a modern digital exciter. No change to the audio chain.

**What a radio would need.** Decoding software in the tuner, a lighter job than the FM RDS
decoding those tuners already do.

## Status

- Draft specification, version 0.2 (November 2026)
- Tested on the bench: a HackRF transmitter, RTL-SDR receivers, an AM radio with a synchronous
  detector, and a medium-wave propagation simulator
- Not yet tested on a licensed AM station, in a car, or against real night-time recordings

## What's in this repository

| File | What it is |
|---|---|
| `pmds/` | The core: encoder, decoder, framing and character set, in plain Python and numpy |
| `tests/test_pmds.py` | Self-test: check code, the specification's test vectors, encode-decode loopback |
| `docs/` | The draft specification (PDF) and logos |
| `examples/pmds_encoder.py` | The encoder as a GNU Radio block |
| `examples/pmds_receiver.py` | A mono AM receiver with the PMDS decoder, for an RTL-SDR |
| `examples/pmds_monitor.py` | A window showing every block and group as it's decoded |
| `examples/pmds_tuner_ui.py` | A tuner window that shows PMDS data the way an RDS radio does (needs `fm_stereo.py`, not in this repository, for FM) |
| `examples/pmds_channel_test.py` | Offline test: encoder, simulated propagation and noise, decoder |
| `examples/pmds_check.py` | Decodes a recording of the transmitter |
| `examples/skywave_channel.py` | The medium-wave propagation simulator |
| `examples/am_data_tx.grc` | The bench transmitter (GNU Radio Companion flowgraph) |

## Two licenses

| Where | What | License |
|---|---|---|
| `pmds/` | The encoder, decoder, framing and character set. No GNU Radio needed. | Apache 2.0 (`pmds/LICENSE`, `pmds/NOTICE`) |
| everything else | The GNU Radio blocks, receiver, bench tools and flowgraph | GPL 3.0 or later (`COPYING`) |

Anyone building a radio or an exciter can take `pmds/` on its own and use it in a commercial
product. Nothing in it imports GNU Radio or copies from GPL code, and it should stay that way.

## Setup

Install the `pmds` package once. Point pip at the **top folder of this repository** (the one
that holds `pyproject.toml`), not at the `pmds/` folder inside it.

Windows, from the radioconda prompt (or whichever Python runs your GNU Radio):

    pip install -e <path to this repository>

With MSYS2's Python, add `--no-deps --break-system-packages`.

Linux (don't use `sudo`):

    git clone https://github.com/axle2152/pmds.git
    cd pmds
    pip install --user -e .

The `-e` makes it an editable install: pip leaves a pointer to this folder instead of copying
the code, so updates to the files here (for example after a `git pull`) take effect the next
time a program starts. Run it again only if you move the folder.

Without installing, keep the `pmds` folder beside the flowgraph and start GNU Radio Companion
from this folder.

## Checks

    python tests/test_pmds.py                    # self-test, no GNU Radio needed
    python examples/pmds_channel_test.py         # every propagation preset, 8.6 degrees
    python examples/pmds_channel_test.py --program bass  # the same with bass-heavy program
    python examples/pmds_channel_test.py --alert  # how fast alerts show and clear
    python examples/pmds_check.py pmds_tx.cfile  # decode a recording of the transmitter

The simulator's presets model medium wave: daytime groundwave, the mush zone (set how strong
the sky wave is with `--sky-db`), one and two sky hops at night, a disturbed night, and
sunrise or sunset flutter. The older shortwave-style presets are still there as `hf_mush`,
`hf_night2` and so on.

## Prior art and related systems

PMDS is a new format, but the idea of carrying data on an AM carrier's phase is old and
public: Collins Radio filed for a patent on a phase-modulated secondary service on AM stations in 1970
(US 3,714,375, long expired), Leonard Kahn on a compatible AM data system in 1984 (US 4,688,255),
the BBC ran phase-modulated data on its 198 kHz long-wave carrier from 1985 until June 2026,
the ITU described AM data systems (AMDS) in Recommendation BS.706, and the DRM consortium
defined AMSS. PMDS borrows its fields and its call-letter method from RDS and RBDS.

## Credits

Designed and tested on the bench by Michael Foley, KK4EKN. The code and analysis were written
with Claude (Anthropic).
