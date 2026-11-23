# PMDS: station data for AM radio

PMDS (Phase Modulation Data Service, a working name) lets an AM station send the kind of
information FM stations already send with RDS: the station's name, what's playing, and
emergency alerts. It works on ordinary mono AM stations, and ordinary AM radios don't hear it.
It can't share a station with AM stereo or HD Radio, which use the same part of the signal.

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
| Song tags | Artist and title marked inside the RadioText (RT+) |

**Speed.** About 94 bits per second, which is slow, but it adds up: the station name shows in
about 5 seconds, a full 64-character text in about 18, and an alert in about 2.

**Errors.** Every block of data carries a check code. The radio can fix a single wrong bit, and
it throws away anything that doesn't check out, so what shows is nearly always right instead of
garbage. For the things that matter most it asks twice: a station has to name itself in two
groups in a row before anything shows, and an alert has to come in two groups in a row before
the radio acts on it.

**One station at a time.** At night a radio can hear two stations on one frequency, fading in
and out over each other. If both send PMDS, the radio must not show one station's name over
the other's text or switch to the other's FM translator. So the station's code rides in the
identity groups and in the slower groups (translator, clock, song tags), and a line of text
counts only when it arrives next to a group that names the station on show. In simulation the
radio then showed one station's data at a time, never a mixture. One case is still open: two
stations whose data blocks happen to run exactly in step.

**Effect on the audio.** Ordinary radios hear nothing on a clean signal, by design. Radios with a
synchronous detector (some HD Radio sets and DSP car radios) can hear a faint, steady low tone at
187.5 Hz. The draft keeps the nudges small enough that the tone stays 45 dB below full
modulation. On the bench, on a strong signal, it could just be heard under the hiss with no
program playing, and not at all under music. At night, sky-wave echoes turn a little of the data
into a faint low rumble that any radio can pick up, more the worse the conditions.

**Range.** Against noise, the data keeps decoding until the station's audio is mostly static.
Another station on the same frequency, the usual trouble at night, is harder on it. In
simulation the data holds while the other station is 10 dB weaker; by 6 dB it is lost when the
programs are heavy with bass, and holds when they are not.

**What a station would need.** A way to phase-modulate the transmitter's RF drive: a small
exciter box for an older transmitter, the way AM stereo (C-QUAM) exciters worked, or a feature
in a modern digital exciter. No change to the audio chain.

**What a radio would need.** First, a way to see the carrier's phase. An ordinary AM radio's
detector looks only at strength, so it throws away exactly what PMDS changes, and no software
update can bring that back. But many newer radios work differently inside. DSP radio chips, car
tuners, HD Radio receivers and SDRs turn the signal into numbers that keep the phase, and older
radios with a synchronous detector or C-QUAM stereo already measured phase in hardware. In those,
PMDS is a software job, and a light one: the decoder handles 94 bits a second, where an FM RDS
decoder handles about 1,200.

Whether a given radio could get PMDS through a firmware update depends on where that phase
information is:

- **Car radios with a separate HD Radio or DAB chip** look like the easiest case. The tuner
  already sends the signal, phase included, to a processor that runs updatable software.
- **Single-chip radios** have the phase inside the chip, where only the chip's maker can add a
  new mode. There is a precedent: a patch that adds single-sideband reception to a popular radio
  chip is loaded into it at start-up.
- **Radios with a synchronous detector or C-QUAM stereo** have the phase on a circuit board
  trace, so a small add-on chip could decode it.

[Receiver design notes](docs/PMDS_Receiver_Design_Notes.md) has the details: which radio types
can do it, what the decoder needs, and what in a radio can spoil the phase.

## Status

- Draft specification, version 0.2 (November 2026)
- Tested on the bench: a HackRF transmitter, RTL-SDR receivers, an AM radio with a synchronous
  detector, and a medium-wave propagation simulator
- A longer bench run decoded about 20,000 blocks with under 0.1% lost, with program processed
  to −95% and +125% peaks
- Not yet tested on a licensed AM station, in a car, or against real night-time recordings
- Prior-art and patent search done in November 2026; attorney review still to come

## What's in this folder

| File | What it is |
|---|---|
| `pmds/` | The core: encoder, decoder, framing and character set, in plain Python and numpy |
| `c/` | The decoder in plain C, for microcontrollers, with a PC test program |
| `firmware/` | The prototype radio's Teensy 4.1 program (see `firmware/README.md`) |
| `tests/test_pmds.py` | Self-test: check code, the specification's test vectors, encode-decode loopback, alerts, two stations on one channel |
| `tests/test_c.py` | The C decoder against the Python one: the same bits from the same signal (needs a C compiler) |
| `tests/test_addon.py` | End to end in GNU Radio: a simulated PMDS station through the all-mode-receiver tuner's AM receiver |
| `tests/false_displays.py` | A long simulation of fading at the level of bits: how often a radio would show a false alert or the wrong station, and how fast real alerts show |
| `pmds_encoder.py` | The encoder as a GNU Radio block |
| `pmds_addon.py` | PMDS for the all-mode-receiver tuner: the decoder in GNU Radio, and what the tuner shows |
| `pmds_monitor.py` | A window showing every block and group as it's decoded (key I in the tuner) |
| `pmds_channel_test.py` | Offline test: encoder, simulated propagation and noise, decoder |
| `pmds_check.py` | Decodes a recording of the transmitter |
| `skywave_channel.py` | The medium-wave propagation simulator |
| `am_data_tx.grc` | The bench transmitter (GNU Radio Companion flowgraph) |
| `docs/` | The draft specification (`PMDS_Draft_Specification_version_0.2.md`), receiver design notes (`PMDS_Receiver_Design_Notes.md`) and logos |

## Two licenses

| Where | What | License |
|---|---|---|
| `pmds/` | The encoder, decoder, framing and character set. No GNU Radio needed. | Apache 2.0 (`pmds/LICENSE`, `pmds/NOTICE`) |
| `c/`, `firmware/` | The decoder in C and the Teensy program | Apache 2.0 |
| everything else | The GNU Radio blocks, the tuner add-on, bench tools and flowgraph | GPL 3.0 or later (`COPYING`) |

Anyone building a radio or an exciter can take `pmds/` or `c/` on its own and use it in a
commercial product. Nothing in them imports GNU Radio or copies from GPL code, and it should
stay that way.

## Setup

Install the `pmds` package once. Point pip at the **top folder of this repository** (the one
that holds `pyproject.toml`), not at the `pmds/` folder inside it.

Windows, from the radioconda prompt (or whichever Python runs your GNU Radio):

    pip install -e <path to this repository>

With MSYS2's Python, add `--no-deps --break-system-packages`.

Linux (don't use `sudo`):

    git clone https://github.com/axle2152/pmds.git
    cd pmds
    pip install --user --no-build-isolation -e .

The `--no-build-isolation` works around a bug in the older pip that Ubuntu 22.04 ships:
without it, the install stops with "Permission denied" on a system folder.

The `-e` makes it an editable install: pip leaves a pointer to this folder instead of copying
the code, so updates to the files here (for example after a `git pull`) take effect the next
time a program starts. Run it again if you move the folder, or when an update changes
`pyproject.toml` (that file tells the tuner where to find the PMDS add-on).

Without installing, keep the `pmds` folder beside the flowgraph and start GNU Radio Companion
from this folder.

## Listening to PMDS

PMDS shows up in the [all-mode-receiver](https://github.com/axle2152/all-mode-receiver)
tuner. Installing this folder (above) also installs the PMDS add-on for it, and the tuner finds
it by itself: on AM it shows the station's call letters, name, RadioText and program type the
way it shows RDS on FM, blinks ALERT or TEST over the name during an alert, and has a PMDS
lamp and meters in its Advanced window. Press I (or click the station detail line in the
Advanced window) for the PMDS data monitor. Without this folder installed, the tuner is a
plain AM radio.

After a `git pull` that changes `pyproject.toml`, run the install command once more so the
tuner keeps finding the add-on.

## Checks

    python tests/test_pmds.py                    # self-test, no GNU Radio needed
    python tests/test_addon.py                   # PMDS through the tuner's AM receiver (needs
                                                 # GNU Radio and all-mode-receiver beside this folder)
    python pmds_channel_test.py                  # every propagation preset, 8.6 degrees
    python pmds_channel_test.py --program bass   # the same with bass-heavy program
    python pmds_channel_test.py --alert          # how fast alerts show and clear
    python pmds_channel_test.py --co -10         # with another station on the channel, 10 dB down
    python pmds_channel_test.py --co -6 --co-pmds --presets night1   # ... one that sends PMDS too
    python pmds_check.py pmds_tx.cfile           # decode a recording of the transmitter

The simulator's presets model medium wave: daytime groundwave, the mush zone (set how strong
the sky wave is with `--sky-db`), one and two sky hops at night, a disturbed night, and
sunrise or sunset flutter. The older shortwave-style presets are still there as `hf_mush`,
`hf_night2` and so on.

## Prior art and related systems

PMDS is a new format, but the idea of carrying data on an AM carrier's phase is old and
public, which is part of why PMDS can be free for anyone to use.

- **1970s:** Collins Radio filed for a patent on a phase-modulated secondary service on AM
  stations in 1970 (US 3,714,375), and from 1976 Martinez patented paging, utility control and
  public alerts on an AM station's carrier phase.
- **1980s:** the BBC put phase-modulated data on its 198 kHz long-wave carrier from 1981, in full
  service from 1985 until June 2026. East Germany ran a similar system on a high-power
  broadcaster, and the ITU's CCIR described both in 1986 (Report 1061). Leonard Kahn patented a
  compatible AM data system in 1984 (US 4,688,255). In 1988 Licentia (Telefunken) described
  "AM-RDS": RDS-style station data on the carrier phase of long-, medium- and shortwave
  broadcasters, at about 100 to 195 bits per second, the closest precedent to PMDS.
- **Later:** the ITU's Recommendation BS.706 described AM data systems (AMDS), and the DRM
  consortium defined AMSS.

Those patents have long expired, and the Licentia applications were never granted. The draft
specification lists the prior art in section 2. PMDS borrows its fields and its call-letter
method from RDS and RBDS.

## Credits

Designed and tested on the bench by Michael Foley, KK4EKN. The code and analysis were written
with Claude (Anthropic).
