# Step 3: the radio front end

The front end turns the antenna's signal into two audio-frequency signals, I and Q, that the
Teensy Audio Adaptor can sample. It's a direct-conversion receiver of the classic Softrock
kind, built from through-hole parts on a breadboard and powered from the Teensy's USB cable.

The design has been checked in a circuit simulator (`hardware/simulate.py`, ngspice) but not
yet built. Treat the first build as a test of the design, and expect to adjust values.

## How it works

1. **Low-pass filter (2.2 MHz):** lets the AM band through and stops shortwave stations. The
   mixer would otherwise hear them at three times its oscillator frequency.
2. **Transformer T1:** couples the 50 Ω input to the mixer and sits the signal at 2.5 V, the
   middle of the 5 V supply.
3. **Mixer (U1, 74HC4052):** four switches connect the signal to four capacitors in turn, each
   for a quarter of the oscillator's cycle. Each capacitor ends up holding the signal as it
   looked at one quarter: 0°, 90°, 180° and 270°.
4. **Its clock (Si5351 and U2, 74HCT74):** the Si5351 runs at four times the oscillator
   frequency, and U2 divides that into the two switch-select lines. The oscillator sits 12 kHz
   below the station, so the station comes out at 12 kHz.
5. **Amplifiers (U3, U4, U5, MCP6022):** four buffers amplify each capacitor about 11 times.
   Two difference amplifiers then make I = X0 − X3 and Q = X2 − X1, about 4.7 times more.
6. **The Audio Adaptor** samples I and Q at 44.1 kHz for the Teensy. The decoder from step 2
   finds the station 12 kHz up, as it does on the SD-card test files.

### What the simulation shows

20 mV from a 50 Ω source gives about 1.4 V peak at the line input:

| Station | I and Q at the line input | Comes out at |
|---|---|---|
| 1012 kHz | 1.44 V, Q 90° behind I | +12 kHz, as the decoder expects |
| 1710 kHz (top of the band) | 1.36 V | +12 kHz |
| 542 kHz (bottom of the band) | 1.30 V | +12 kHz |
| 1602 kHz with the oscillator at 530 kHz | 12 dB down | −12 kHz (the mixer's third-harmonic response) |
| 5106 kHz shortwave with the oscillator at 1698 kHz | 49 dB down | −12 kHz, mostly removed by the filter |

**The third-harmonic response near the bottom of the band** is the one weak spot. With the
oscillator near 530 kHz, a station near three times that (around 1600 kHz) still comes
through, only 12 dB down. On the bench, with the HackRF as the only station, it doesn't
matter. On the air it's why step 4 uses a tuned ferrite rod: its tuning removes stations that
far away.

**Signal level:** keep the carrier at J1 below about 10 mV (about −36 dBm into 50 Ω), which
leaves room for 125% modulation peaks. With the HackRF, start with 30 dB of attenuators and
its lowest transmit gain.

## The schematic

![Sheet 1: RF input, low-pass filter, mixer and clock](hardware/1_rf_mixer.svg)

![Sheet 2: amplifiers, bias and analog supply](hardware/2_amplifiers.svg)

![Sheet 3: the Teensy and what connects to it](hardware/3_teensy.svg)

`hardware/draw_schematic.py` draws these sheets: `pip install schemdraw`, then run it.

## Parts with values

| Part | Value | Qty | Notes |
|---|---|---|---|
| U1 | 74HC4052 | 1 | Mixer |
| U2 | 74HCT74 | 1 | Clock divider (HCT, for the 3.3 V clock) |
| U3, U4, U5 | MCP6022 | 3 | Op-amps |
| Si5351A breakout | Adafruit 2045 or a clone | 1 | Powered from 3.3 V |
| T1 | FT37-43, 15 turns bifilar | 1 | Winding instructions below |
| L1, L2 | 5.6 µH | 2 | 4.7 or 6.8 µH also work |
| C1, C3 | 820 pF + 68 pF in parallel, C0G | 2 each | 888 pF |
| C2 | 2.7 nF + 220 pF in parallel, C0G | 1 each | 2.92 nF |
| C6 to C9 | 22 nF film | 4 | Sampling capacitors; use the same type for all four |
| Buffer feedback | 10 kΩ with 470 pF across it | 4 each | One pair per buffer |
| Buffer gain resistor | 1 kΩ | 4 | |
| Buffer DC blocks, C4 | 10 µF electrolytic | 5 | |
| Difference amplifier inputs | 10 kΩ | 4 | |
| Difference amplifier feedback and bias | 47 kΩ | 4 | |
| Difference amplifier feedback | 100 pF | 2 | |
| Output coupling | 1 µF film | 2 | |
| Output series resistors | 100 Ω | 2 | |
| R1 | 100 Ω | 1 | |
| R2 | 33 Ω | 1 | Clock line |
| R3, R4 | 10 kΩ | 2 | Bias divider |
| Bias capacitor | 47 µF electrolytic | 1 | |
| FB1 | Ferrite bead | 1 | Analog supply filter |
| Supply capacitor | 100 µF electrolytic | 1 | |
| C5, bias, supply and chip decoupling | 100 nF ceramic | 8 | One at each chip's power pin |
| J1 | SMA jack | 1 | |

Every value is in the assortments in `PARTS.md`.

## Connections, pin by pin

Pin 1 of a chip is next to the notch or dot; the numbers run down that side and back up the
other. "+5VA" is the filtered 5 V rail, "+3V3" the Teensy's 3.3 V pin, "VBIAS" the 2.5 V bias.

### U1, 74HC4052

| Pin | Name | Connect to |
|---|---|---|
| 1, 2, 4, 5 | Y0, Y2, Y3, Y1 | Nothing |
| 3 | Y COM | GND |
| 6 | E (enable, active low) | GND |
| 7 | VEE | GND |
| 8 | GND | GND |
| 9 | S1 | U2 pin 9 |
| 10 | S0 | U2 pin 5 |
| 11 | X3 | C9 to GND, and U4 pin 5 |
| 12 | X0 | C6 to GND, and U3 pin 3 |
| 13 | X COM | T1 secondary, hot end |
| 14 | X1 | C7 to GND, and U3 pin 5 |
| 15 | X2 | C8 to GND, and U4 pin 3 |
| 16 | VCC | +5VA, 100 nF to GND |

### U2, 74HCT74

| Pin | Name | Connect to |
|---|---|---|
| 1, 4, 10, 13 | CLR1, PRE1, PRE2, CLR2 | +5VA |
| 2 | D1 | U2 pin 8 |
| 3, 11 | CLK1, CLK2 | Both to R2 (33 Ω), whose other end goes to Si5351 CLK0 |
| 5 | Q1 | U1 pin 10, and U2 pin 12 |
| 6 | Q1 inverted | Nothing |
| 7 | GND | GND |
| 8 | Q2 inverted | U2 pin 2 |
| 9 | Q2 | U1 pin 9 |
| 12 | D2 | U2 pin 5 |
| 14 | VCC | +5VA, 100 nF to GND |

### U3 and U4, the buffers (MCP6022)

Each half is the same: the + input from a sampling capacitor, 10 kΩ with 470 pF across it
from the output back to the − input, and 1 kΩ from the − input to a 10 µF capacitor (+ side
to the resistor, − side to GND).

| Chip | Pin | Connect to |
|---|---|---|
| U3 | 3 (+A) | U1 pin 12 (X0) |
| U3 | 2 (−A) | Feedback from pin 1; 1 kΩ to 10 µF to GND |
| U3 | 1 (out A, "A0") | 10 kΩ to U5 pin 3 |
| U3 | 5 (+B) | U1 pin 14 (X1) |
| U3 | 6 (−B) | Feedback from pin 7; 1 kΩ to 10 µF to GND |
| U3 | 7 (out B, "A1") | 10 kΩ to U5 pin 6 |
| U4 | 3 (+A) | U1 pin 15 (X2) |
| U4 | 2 (−A) | Feedback from pin 1; 1 kΩ to 10 µF to GND |
| U4 | 1 (out A, "A2") | 10 kΩ to U5 pin 5 |
| U4 | 5 (+B) | U1 pin 11 (X3) |
| U4 | 6 (−B) | Feedback from pin 7; 1 kΩ to 10 µF to GND |
| U4 | 7 (out B, "A3") | 10 kΩ to U5 pin 2 |
| U3, U4 | 4 | GND |
| U3, U4 | 8 | +5VA, 100 nF to GND |

### U5, the difference amplifiers (MCP6022)

| Pin | Connect to |
|---|---|
| 3 (+A) | 10 kΩ from U3 pin 1; 47 kΩ to VBIAS |
| 2 (−A) | 10 kΩ from U4 pin 7; 47 kΩ with 100 pF across it from pin 1 |
| 1 (out A, I) | 1 µF film, then 100 Ω, to the Audio Adaptor's LINE IN L |
| 5 (+B) | 10 kΩ from U4 pin 1; 47 kΩ to VBIAS |
| 6 (−B) | 10 kΩ from U3 pin 7; 47 kΩ with 100 pF across it from pin 7 |
| 7 (out B, Q) | 1 µF film, then 100 Ω, to the Audio Adaptor's LINE IN R |
| 4 | GND |
| 8 | +5VA, 100 nF to GND |

### Input, transformer and bias

- **The input:** J1 centre to C1 (to GND), then L1, C2 (to GND), L2 and C3 (to GND), then T1's
  primary. The other end of the primary and J1's shell go to GND.
- **T1's secondary:** the hot end to U1 pin 13. The cold end goes to its own node, with C4
  (10 µF, + side to the node) and C5 (100 nF) to GND, and R1 (100 Ω) to VBIAS.
- **VBIAS:** R3 (10 kΩ) from +5VA, R4 (10 kΩ) to GND, with 47 µF (+ side up) and 100 nF to
  GND. It feeds R1 and the two 47 kΩ resistors on U5 pins 3 and 5.

### Power

- **+5VA:** from the Teensy's VIN pin (USB 5 V) through FB1, with 100 µF (+ side up) and 100 nF
  to GND. It feeds U1 to U5 and R3.
- **+3V3:** from the Teensy's 3.3V pin, to the Si5351 board's VIN, the Audio Adaptor's 3.3V,
  the display and the encoder.
- **GND:** the Teensy's GND to the breadboard's ground rails. Join the rails on both sides.

### The modules

| Module | Pin | Connect to |
|---|---|---|
| Si5351A breakout | VIN | +3V3 (never 5 V: its pull-ups would then put 5 V on the Teensy) |
| | GND | GND |
| | SDA, SCL | Teensy 18, 19 |
| | CLK0 | R2 (33 Ω) to U2 pins 3 and 11 |
| Audio Adaptor Rev D | 7, 8, 18, 19, 20, 21, 23 | The Teensy pins with the same numbers |
| | 3.3V, GND | +3V3, GND |
| | LINE IN L, LINE IN R | I (via U5 pin 1's 1 µF and 100 Ω), Q (via U5 pin 7's) |
| | LINE IN GND | GND |
| OLED display | VCC, GND | +3V3, GND |
| | SDA, SCL | Teensy 18, 19 |
| Rotary encoder | +, GND | +3V3, GND |
| | CLK, DT, SW | Teensy 2, 3, 4 |

## Winding T1

1. Cut two 40 cm lengths of magnet wire and twist them together loosely, about three twists
   per inch.
2. Pass the pair through the FT37-43 toroid 15 times. Each pass through the middle is one
   turn. Spread the turns evenly around the ring.
3. Scrape or burn the enamel off the four ends, and tin them.
4. Use the meter's continuity test to find which ends belong to the same wire. One wire is
   the primary and the other the secondary; which is which doesn't matter here.

## Building and testing, one stage at a time

1. **Power and bias, no chips yet.** Plug in the USB cable. Measure about 5 V on +5VA, 3.3 V on
   +3V3 and 2.5 V on VBIAS. The USB power meter should show well under 100 mA.
2. **The clock.** Fit U2 and wire the Si5351 board. A short test program (it will come with the
   step 3 software) sets CLK0 to 4 MHz.
   Your meter on U2 pins 5 and 9 should then read about 2.5 V each: a 1 MHz square wave
   averaged.
3. **The mixer and amplifiers.** Fit U1, U3, U4 and U5. With nothing on the input, every
   op-amp output (pins 1 and 7) should read about 2.5 V. One stuck near 0 V or 5 V points to a
   wiring mistake around that op-amp.
4. **Signal.** Connect the HackRF through 30 dB of attenuators, sending PMDS at, say, 1000 kHz,
   and tune the radio to it. The step 3 program shows the station on the display.

The program these tests need (tuning the Si5351, reading the Audio Adaptor, decoding, the
display) is the next piece of software, written to this schematic.

## Breadboard tips

- **Keep the RF part compact.** Mount J1, the filter, T1 and U1 close together, with short
  wires.
- **Fit the 100 nF decoupling capacitors right at each chip's power pin.** Use the shortest
  possible leads.
- **Check the power rails.** Many long breadboards split their rails in the middle; bridge
  them.
- **Keep the display and its wires away from the mixer,** and later from the ferrite rod.
- **Check electrolytic capacitors:** the stripe marks the − side.
