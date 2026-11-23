# Parts for the PMDS prototype radio

Everything for steps 2 to 4 of the prototype (see `README.md` in this folder), plus the tools.
The step 3 schematic and its exact values are in `FRONT_END.md`. The assortments below cover
every one of those values, so there's no second order.

Prices are rough guesses from memory, not checked against any shop. Treat them as a guide to
the total, not a quote.

## Power

**Steps 2 to 4 need no power supply.** Everything runs from the PC's USB port: the Teensy,
the audio board, the clock chip, the mixer, the display and a small speaker amplifier. That
is an estimated 200 to 300 mA at most, inside what a USB port gives. A USB port also limits
its own current, so a slip on the breadboard browns out the Teensy rather than melting
anything. Plug in the USB power meter below to see the real draw.

**Keep high-current supplies away from the breadboard.** A short on a breadboard draws
whatever the supply will give: a 12 V supply or battery that can deliver tens of amps heats
a jumper wire red in seconds. If something later needs 12 V (a transmitter kit, for example),
put an inline fuse holder with a 1 A fast fuse right at the supply's terminals, before
anything else.

A current-limited bench supply (adjustable, 0 to 30 V, up to 3 or 5 A, about $50 to $100) is
the right tool for that later work. Set its current limit to a little above what the circuit
needs, and a mistake costs nothing. It's not needed for the radio itself.

One more power note: power the Teensy from one USB cable only. A Teensy fed from USB and from
a second 5 V source at the same time can back-feed the PC unless a pad on the board is cut.

## Step 2: the decoder on the Teensy

| Item | Qty | For | About |
|---|---|---|---|
| Teensy 4.1, with pins | 1 | The decoder. Buy from PJRC or an authorized dealer (SparkFun, Adafruit, DigiKey) to avoid clones | $35 |
| microSD card, 8 to 32 GB | 1 | Test recordings | $8 |
| Micro-USB cable that carries data (not a charge-only cable) | 1 | Programming and power | $5 |

## Step 3: the front end on a breadboard

### Boards and modules

| Item | Qty | For | About |
|---|---|---|---|
| Teensy Audio Adaptor, Rev D (for Teensy 4.x), with pins | 1 | I/Q into the Teensy through its line input; headphone output | $15 |
| Si5351A clock generator breakout (Adafruit 2045, or a clone) | 1 | Tunes the radio: makes 4 times the station's frequency | $8 |
| 1.3-inch 128×64 OLED, I2C (SH1106 or SSD1306) | 1 | Call letters, name, text, ALERT. Works with the U8g2 library, which can draw accented letters | $8 |
| Rotary encoder module with push button (KY-040 type) | 2 | Tuning, menus | $3 |

### Chips (through-hole, so they fit a breadboard)

| Item | Qty | For | About |
|---|---|---|---|
| 74HC4052, dual 4-to-1 analog switch (DIP-16) | 3 | The mixer (quadrature sampling detector). Spares included | $3 |
| 74HCT74, dual D flip-flop (DIP-14) | 3 | Divides the clock by 4 into the mixer's quadrature switching. HCT, because it reads the Si5351's 3.3 V clock correctly on 5 V | $3 |
| MCP6022, dual rail-to-rail op-amp (DIP-8) | 5 | Amplifies I and Q for the audio board, on a single 5 V supply | $10 |

### RF parts

| Item | Qty | For | About |
|---|---|---|---|
| FT37-43 ferrite toroids | 5 | The input transformer | $5 |
| T50-2 iron-powder toroids | 5 | Inductors for the input low-pass filter, if the kit values don't suit | $5 |
| Enamelled magnet wire, 26 or 28 AWG, small spool | 1 | Winding the toroids | $8 |
| SMA female jack on a breadboard-friendly breakout (or an SMA pigtail with bare ends) | 2 | Bringing the HackRF's signal onto the breadboard | $8 |
| SMA attenuators, 10 dB and 20 dB | 1 each | Keeps the HackRF's signal at a sensible level for the mixer | $15 |
| SMA male-to-male cable, about 30 cm | 1 | HackRF to the board | $6 |

Toroids and magnet wire are easiest from ham suppliers such as Kits and Parts.

### Assortments (these cover the schematic's values)

| Item | About |
|---|---|
| Resistor kit, 1/4 W 1% metal film, 10 Ω to 1 MΩ, about 30 values | $12 |
| Ceramic capacitor kit, 10 pF to 100 nF (includes plenty of 100 nF for decoupling) | $10 |
| C0G/NP0 ceramic capacitor kit, 10 pF to 10 nF (the RF filter needs stable ones) | $12 |
| Film capacitor kit, 1 nF to 1 µF (the mixer's sampling capacitors) | $12 |
| Electrolytic capacitor kit, 1 µF to 1000 µF, 16 V or higher | $12 |
| Axial inductor kit, 1 µH to 1 mH | $10 |
| Ferrite bead assortment (through-hole) | $6 |
| Small-signal transistor kit (2N3904, 2N3906 and others) | $8 |
| Tactile push-button assortment | $5 |

### Wiring

| Item | Qty | About |
|---|---|---|
| Full-size solderless breadboards (830 holes) | 3 | $15 |
| Pre-cut, pre-bent jumper wire kit (lies flat, keeps RF wiring short) | 1 | $8 |
| Flexible Dupont jumpers, male-male, male-female, female-female | 1 set | $7 |
| 22 AWG solid hook-up wire, several colours | 1 kit | $15 |
| Male header strips, 2.54 mm, breakaway | 10 | $6 |

## Step 4: a real radio

| Item | Qty | For | About |
|---|---|---|---|
| Medium-wave ferrite rod antenna with coil, 10 mm × 140 to 200 mm | 1 | The antenna | $8 |
| Tuning capacitor, 2 × 270 pF polyvaricon (or a 365 pF air variable) | 1 | Tunes the ferrite rod to the station | $4 |
| LM386 audio amplifier module | 1 | Drives the speaker | $3 |
| Speaker, 8 Ω, 2 to 3 inch, 2 to 3 W | 1 | Sound | $5 |
| Any wired 3.5 mm headphones | 1 | Listening without the speaker | — |

Two choices here protect the reception:

- **The LM386 is a plain linear amplifier.** Cheap class-D modules such as the PAM8403
  switch at a few hundred kHz, right where they'd be heard in the AM band.
- **The OLED's power circuit can make some RF noise.** Mount the display away from the
  ferrite rod.

**An easier antenna, if you'd rather:** a ready-made active loop (the MLA-30+ type, about
$40 to $60) plugs into the SMA input and needs no tuning. It also picks up shortwave, which
the input filter has to keep out.

## Tools

| Item | About | Notes |
|---|---|---|
| Temperature-controlled soldering iron | $30 to $100 | A Pinecil (USB-C powered) or a Hakko FX-888D |
| Solder, 0.8 mm rosin core | $10 | 63/37 tin-lead flows easiest; lead-free is fine too |
| Flux pen and desoldering wick | $10 | |
| Flush cutters, wire strippers (20 to 30 AWG), needle-nose pliers, tweezers | $30 | |
| Helping hands or a small board holder | $15 | |
| Multimeter | $25 to $40 | Any auto-ranging one |
| USB power meter, inline | $12 | Shows what the prototype draws |
| Safety glasses | $8 | Clipped leads fly |
| Small parts organizer box | $10 | |
| USB logic analyzer, 8 channels | $12 | Optional: shows what's on the I2C and clock lines when something won't talk |

An oscilloscope isn't needed. An SDR receiver such as an RTL-SDR can show the RF side, and
the Teensy can report the audio levels it sees.

## Software (free)

- **Arduino IDE 2 with Teensy support:** the steps are in `README.md`.
- **The U8g2 library** (for the display), from the Arduino IDE's Library Manager, in step 3.
- **KiCad,** for the circuit board, in step 5.

## Rough totals

| Part | About |
|---|---|
| Step 2 | $50 |
| Step 3, assortments included | $250 |
| Step 4 | $20 (the active loop instead: $60) |
| Tools you don't already have | Up to $200 |

The assortments are most of step 3's cost, and they will cover later projects too.
