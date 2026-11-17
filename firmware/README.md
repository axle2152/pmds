# The PMDS prototype radio: Teensy firmware

The goal is a small radio that decodes PMDS on a microcontroller rather than a PC. It's
built in steps:

1. **The decoder in C** (`c/`): checked against the Python decoder bit for bit. Done.
2. **The decoder on a Teensy 4.1**, decoding recordings from its SD card: `teensy_rx`, here.
3. **A radio front end** on a breadboard: an Si5351 clock, a quadrature sampling mixer and the
   Teensy Audio Adaptor's line input, receiving the HackRF by cable, with a display.
4. **A real radio**: antenna, AM audio, a tuning knob.
5. **A printed circuit board.**

## What you need for step 2

The full parts list for every step, with tools and power advice, is in `PARTS.md`. For this
step:

- A Teensy 4.1 (the version with pins is easiest)
- A microSD card, any size, formatted FAT32 or exFAT
- A micro-USB cable that carries data, not just power
- Arduino IDE 2 with Teensy support (below)
- Python with numpy, to make the test recordings

## Setting up the Arduino IDE (once)

1. Install Arduino IDE 2 from arduino.cc.
2. In **File > Preferences**, add this to **Additional boards manager URLs**:
   `https://www.pjrc.com/teensy/package_teensy_index.json`
3. Open **Tools > Board > Boards Manager**, search for **Teensy**, and install it.

## Making the test recordings

From the top folder of this repository:

    python c/make_test_iq.py --out E:/

Put your SD card's drive letter in place of `E:/`. It writes five one-minute recordings of
a simulated station:

| File | What it is |
|---|---|
| PMDS01.WAV | Clean, strong signal |
| PMDS02.WAV | Tuned 37 Hz off, weak (15 dB carrier-to-noise), bass-heavy program |
| PMDS03.WAV | Night-time fading |
| PMDS04.WAV | Very weak (8 dB) and tuned 420 Hz off |
| PMDS05.WAV | An emergency alert on the air |

Each holds what the radio's front end will hand the Teensy: I on the left channel and Q on
the right, 16 bits at 44,100 samples a second, with the station's carrier 12 kHz above
0 Hz. Leave `--out` off to put them in `c/testfiles/` instead.

## Running it

1. Put the SD card in the Teensy's card slot.
2. Open `firmware/teensy_rx/teensy_rx.ino` in the Arduino IDE.
3. **Tools > Board**: Teensy 4.1. **Tools > USB Type**: Serial. **Tools > CPU Speed**:
   600 MHz.
4. Press **Upload**. The Teensy Loader opens; if it asks, press the button on the Teensy.
5. Open **Tools > Serial Monitor**.

The Teensy decodes each file in turn and prints what a radio would show: the call letters,
the station name, the text, any alert. It ends each file with a summary, including how much
of the processor the decoder needed. Please send that line back; it's the first real
measurement of the decoder on a microcontroller.

Set `SHOW_GROUPS` to 0 near the top of the sketch to print only the status lines.

## How the code fits together

- `teensy_rx.ino`: the sketch. It reads the SD card and prints the results.
- `src/pmds/`: the decoder, a copy of the repository's `c/` folder. The Arduino IDE builds
  a sketch only from its own folder, hence the copy. Don't edit these files. Edit the ones
  in `c/`, then run `python c/sync_firmware.py`. The self-test (`tests/test_pmds.py`)
  fails if the copy falls behind.

The decoder and this sketch are under the Apache 2.0 licence, like `pmds/`.
