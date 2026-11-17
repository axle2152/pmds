# The PMDS decoder in C

A port of the Python reference decoder (`pmds/demod.py`, `pmds/framer.py`) to plain C99, for
microcontrollers. It decodes compact framing at 93.75 bit/s only, with no memory allocation,
no operating system and no GNU Radio code. Apache 2.0, like `pmds/`.

| File | What it is |
|---|---|
| `pmds.h` | Everything a program needs: the structures and the functions |
| `pmds_front.c` | From I/Q at the radio's own sample rate to the decoder: moves the station to 0 Hz, resamples to 6,000 samples a second, finds the carrier and locks onto it |
| `pmds_demod.c` | Bits from the carrier's phase, including the leak canceller |
| `pmds_framer.c` | Block sync, one-bit repair, the groups, one station at a time, alerts |
| `pmds_text.c` | The RDS character set as UTF-8, call letters from the PI code, AF frequencies, dates |
| `tools/pmds_decode.c` | A PC program that decodes a recording and prints what a radio would show |
| `make_test_iq.py` | Makes simulated recordings for the decoder and the Teensy |
| `sync_firmware.py` | Copies these files into the Teensy sketch |

The decoder core gives exactly the same bits, groups and station as the Python decoder on the
same signal; `tests/test_c.py` checks that. Compiled for the Teensy 4.1's Cortex-M7 it is
about 14 KB of code and 63 KB of memory. On a PC it decodes about 300 times faster than real
time. How much of the Teensy it needs is still to be measured.

## Building and testing on a PC

With a C compiler (Linux, or MSYS2 on Windows):

    cd c
    make
    python3 ../tests/test_c.py

To decode a recording:

    tools/pmds_decode --if 12000 --groups testfiles/PMDS01.WAV

Options: `--rate` for a raw `.cf32` or `.cf64` file, `--if` for where the carrier sits,
`--groups` to print every group, `--bits` for every bit, `--strict` to turn off repairs, and
`--demod` for a file that is already 6,000 Hz with the carrier locked.
