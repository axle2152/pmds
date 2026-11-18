#!/usr/bin/env python3
# Copyright 2026 Michael Foley
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
# except in compliance with the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the
# License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific language governing permissions
# and limitations under the License.
"""
draw_schematic.py - the prototype radio's step 3 front end, drawn as three SVG sheets.

    pip install schemdraw
    python firmware/hardware/draw_schematic.py

  1_rf_mixer.svg     antenna input, low-pass filter, transformer, the 74HC4052 mixer, its clock
                     (Si5351 and the 74HCT74 divider)
  2_amplifiers.svg   the four buffers, the two difference amplifiers, the bias, to the line input
  3_teensy.svg       the Teensy 4.1 and what connects to it: Audio Adaptor, Si5351, display,
                     encoder, power

The circuit is the one simulated in front_end.cir (ngspice). FRONT_END.md explains it and
lists every connection pin by pin.
"""
import os

import schemdraw
import schemdraw.elements as elm

schemdraw.use('svg')
HERE = os.path.dirname(os.path.abspath(__file__))
FONT = 11


def sheet(name):
    d = schemdraw.Drawing(file=os.path.join(HERE, name), show=False)
    d.config(fontsize=FONT, unit=2.5, lw=1.1)
    return d


# ---- sheet 1: RF input to the mixer -------------------------------------------------------------
def ic(name, pins, size, label):
    return elm.Ic(pins=pins, size=size, pinspacing=0.9, edgepadW=0.6, lblsize=10, pinlblsize=9,
                  label=label, lblofst=0).theta(0)


def note(d, xy, text, size=9):
    d += elm.Label().at(xy).label(text, fontsize=size, halign='left', valign='top')


def net(d, at, text, loc='right'):
    d += elm.Label().at(at).label(text, loc=loc, fontsize=10, halign='left' if loc == 'right' else 'right')


def rf_mixer():
    d = sheet('1_rf_mixer.svg')
    note(d, (-3.0, 5.0), 'PMDS prototype radio, step 3, sheet 1: RF input, low-pass filter, mixer and its clock', 14)
    # ---- row 1: input, low-pass, transformer, mixer
    d += (j1 := elm.CoaxConnect().at((0, 0)).theta(0))
    note(d, (-3.0, 1.6), 'J1 SMA: the HackRF\nthrough 30 dB, or the\nantenna\'s link winding', 9)
    d += elm.Line().right(0.8).at(j1.center)
    d += (a := elm.Dot())
    d += elm.Capacitor().down().at(a.center).label('C1\n888 pF', loc='bottom', fontsize=10)
    d += elm.Ground()
    d += elm.Inductor2(loops=3).right().at(a.center).label('L1 5.6 µH', fontsize=10)
    d += (b := elm.Dot())
    d += elm.Capacitor().down().at(b.center).label('C2\n2.92 nF', loc='bottom', fontsize=10)
    d += elm.Ground()
    d += elm.Inductor2(loops=3).right().at(b.center).label('L2 5.6 µH', fontsize=10)
    d += (c := elm.Dot())
    d += elm.Capacitor().down().at(c.center).label('C3\n888 pF', loc='bottom', fontsize=10)
    d += elm.Ground()
    note(d, (-3.0, -5.6), 'Low-pass filter, 2.2 MHz, 50 Ω (5-pole Butterworth). Use C0G capacitors:\n'
                         'C1 and C3 = 820 pF + 68 pF in parallel, C2 = 2.7 nF + 220 pF in parallel')
    d += elm.Line().right(1.5).at(c.center)
    d += (t1 := elm.Transformer(t1=5, t2=5, core=True).theta(0).anchor('p1'))
    note(d, (t1.p1[0] - 0.4, t1.p1[1] + 1.6), 'T1  FT37-43\n15 turns bifilar, 1:1')
    d += elm.Ground().at(t1.p2)
    # the transformer's cold end: AC ground at the bias
    d += elm.Line().down(1.3).at(t1.s2)
    d += (vb := elm.Dot())
    d += elm.Capacitor(polar=True).down().at(vb.center).label('C4\n10 µF', loc='bottom', fontsize=10)
    d += elm.Ground()
    d += elm.Line().right(1.6).at(vb.center)
    d += (vb2 := elm.Dot())
    d += elm.Capacitor().down().at(vb2.center).label('C5\n100 nF', loc='bottom', fontsize=10)
    d += elm.Ground()
    d += elm.Resistor().right().at(vb2.center).label('R1 100 Ω', fontsize=10)
    net(d, (vb2.center[0] + 2.5, vb2.center[1]), 'VBIAS (2.5 V, sheet 2)')
    # the mixer
    u1 = ic('U1', [elm.IcPin(name='X COM', pin='13', side='left'),
                   elm.IcPin(name='X0', pin='12', side='right', slot='1/4'),
                   elm.IcPin(name='X1', pin='14', side='right', slot='2/4'),
                   elm.IcPin(name='X2', pin='15', side='right', slot='3/4'),
                   elm.IcPin(name='X3', pin='11', side='right', slot='4/4'),
                   elm.IcPin(name='S0', pin='10', side='bottom', slot='1/2'),
                   elm.IcPin(name='S1', pin='9', side='bottom', slot='2/2'),
                   elm.IcPin(name='VCC', pin='16', side='top')],
            (5.0, 4.4), 'U1\n74HC4052')
    d += elm.Line().right(1.4).at(t1.s1)
    d += (u1 := u1.anchor('X COM'))
    d += elm.Vdd().at(u1.VCC).label('+5VA', fontsize=10)
    note(d, (u1.X0[0] + 0.8, u1.X0[1] - 5.6), 'U1 also: pin 6 (E) and pins 7, 8 to GND;\n'
                                               'pin 3 (Y COM) to GND, Y0-Y3 unused;\n100 nF from pin 16 to GND')
    for k, (pin, to) in enumerate((('X0', 'U3A pin 3'), ('X1', 'U3B pin 5'), ('X2', 'U4A pin 3'), ('X3', 'U4B pin 5'))):
        p = getattr(u1, pin)
        d += elm.Line().right(1.2 + 1.5 * k).at(p)
        d += (dt := elm.Dot())
        d += elm.Line().right(6.0 - 1.5 * k)
        net(d, d.here, 'to ' + to)
        d += elm.Capacitor().down().at(dt.center).toy(u1.X0[1] - 2.6).label('C%d\n22 nF' % (6 + k), loc='bottom',
                                                                              fontsize=9)
        d += elm.Ground()
    note(d, (u1.X3[0] + 1.0, u1.X3[1] + 1.4), 'C6-C9: sampling capacitors, film, 22 nF')
    # ---- row 2: the clock. Si5351 -> R2 -> 74HCT74 Johnson counter -> U1 S0, S1
    u2 = ic('U2', [elm.IcPin(name='CLK1', pin='3', side='left', slot='1/4'),
                   elm.IcPin(name='CLK2', pin='11', side='left', slot='2/4'),
                   elm.IcPin(name='D1', pin='2', side='left', slot='3/4'),
                   elm.IcPin(name='D2', pin='12', side='left', slot='4/4'),
                   elm.IcPin(name='Q1', pin='5', side='right', slot='1/3'),
                   elm.IcPin(name='Q2', pin='9', side='right', slot='2/3'),
                   elm.IcPin(name='Q̅2', pin='8', side='right', slot='3/3'),
                   elm.IcPin(name='VCC', pin='14', side='top')],
            (3.2, 4.4), 'U2\n74HCT74')
    d += (u2 := u2.at((u1.S0[0] - 6.5, u1.S0[1] - 9.0)).anchor('Q1'))
    d += elm.Vdd().at(u2.VCC).label('+5VA', fontsize=10)
    # Q1 -> S0, Q2 -> S1
    d += elm.Line().right(2.0).at(u2.Q1)
    d += (q1d := elm.Dot())
    d += elm.Wire('-|').at(q1d.center).to(u1.S0)
    d += elm.Wire('-|').at(u2.Q2).to(u1.S1)
    net(d, (q1d.center[0] + 0.2, q1d.center[1] - 0.45), 'Q1')
    # the counter's feedback, by net name: D1 <- Q2-bar, D2 <- Q1
    d += elm.Line().right(1.0).at(getattr(u2, 'Q̅2'))
    net(d, d.here, 'to D1')
    d += elm.Line().left(1.0).at(u2.D1)
    net(d, d.here, 'from Q̅2 (pin 8)', loc='left')
    d += elm.Line().left(1.0).at(u2.D2)
    net(d, d.here, 'from Q1 (pin 5)', loc='left')
    note(d, (u2.CLK1[0] - 1.0, u2.Q2[1] - 3.0), 'U2 also: pins 1, 4, 10, 13 (CLR, PRE) to +5VA;\n'
                                                 'pin 7 to GND; 100 nF from pin 14 to GND.\n'
                                                 'Q1 Q2 step 00, 10, 11, 01 on each clock, so X0, X1, X3, X2\n'
                                                 'each get a quarter of every oscillator cycle')
    # Si5351 to both clock inputs through R2
    d += elm.Line().left(1.2).at(u2.CLK1)
    d += (ck := elm.Dot())
    d += elm.Wire('|-').at(ck.center).to(u2.CLK2)
    d += elm.Resistor().left().at(ck.center).label('R2 33 Ω', fontsize=10)
    si = ic('Si5351', [elm.IcPin(name='CLK0', side='right'),
                       elm.IcPin(name='VIN', side='left', slot='1/4'), elm.IcPin(name='GND', side='left', slot='2/4'),
                       elm.IcPin(name='SDA', side='left', slot='3/4'), elm.IcPin(name='SCL', side='left', slot='4/4')],
            (3.6, 3.6), 'Si5351A\nbreakout')
    d += elm.Line().left(0.6)
    d += (s5 := si.anchor('CLK0'))
    for pin, txt in (('VIN', '+3V3 (Teensy 3.3V)'), ('GND', 'GND'), ('SDA', 'Teensy pin 18'), ('SCL', 'Teensy pin 19')):
        d += elm.Line().left(0.6).at(getattr(s5, pin))
        net(d, d.here, txt, loc='left')
    note(d, (s5.CLK0[0] - 3.6, s5.VIN[1] - 1.2), 'CLK0 = 4 x (station - 12 kHz):\n2.072 to 6.792 MHz')
    d.save(os.path.join(HERE, '1_rf_mixer.svg'))


# ---- sheet 2: the amplifiers ------------------------------------------------------------------
def buffer(d, x, y, unit, pins, xin, name):
    """A non-inverting stage, x11 at 12 kHz, DC gain 1: + from the sampling capacitor, the
    output named for the difference amplifiers."""
    pin_p, pin_m, pin_o = pins
    op = elm.Opamp(leads=True).flip().at((x, y)).anchor('in2')
    d += op
    d += elm.Label().at((op.center[0] + 0.2, op.center[1] + 1.55)).label(unit + '  MCP6022', fontsize=10)
    d += elm.Label().at((op.in2[0] + 0.25, op.in2[1] + 0.3)).label(pin_p, fontsize=8)
    d += elm.Label().at((op.in1[0] + 0.25, op.in1[1] - 0.3)).label(pin_m, fontsize=8)
    d += elm.Label().at((op.out[0] - 0.25, op.out[1] + 0.3)).label(pin_o, fontsize=8)
    d += elm.Line().left(0.8).at(op.in2)
    net(d, d.here, xin, loc='left')
    # feedback: Rf with Cf across it, from the output back to the - input
    d += elm.Line().down(0.8).at(op.in1)
    d += (f := elm.Dot())
    d += elm.Resistor().right().at(f.center).tox(op.out[0] - 0.4).label('10k', fontsize=9)
    d += elm.Line().right(0.4)
    d += elm.Line().toy(op.out[1])
    d += elm.Line().down(1.0).at(f.center)
    d += (f2 := elm.Dot())
    d += elm.Capacitor().right().at((f.center[0], f.center[1] - 1.0)).tox(op.out[0]).label('470 pF', loc='bottom', fontsize=9)
    d += elm.Line().toy(f.center[1])
    d += elm.Resistor().left().at(f2.center).label('1k', fontsize=9)
    d += elm.Capacitor(polar=True).down().label('10 µF', loc='bottom', fontsize=9)
    d += elm.Ground()
    d += elm.Line().right(0.8).at(op.out)
    d += (o := elm.Dot())
    net(d, o.center, name)
    return op


def diffamp(d, x, y, unit, pins, plus, minus, outname):
    """(+ minus -) x 4.7 about VBIAS, then 1 uF and 100 ohm to the Audio Adaptor's line input."""
    pin_p, pin_m, pin_o = pins
    op = elm.Opamp(leads=True).at((x, y)).anchor('in2')
    d += op
    d += elm.Label().at((op.center[0] + 0.3, op.center[1] - 1.6)).label(unit + '  MCP6022', fontsize=10)
    d += elm.Label().at((op.in2[0] + 0.25, op.in2[1] - 0.3)).label(pin_p, fontsize=8)
    d += elm.Label().at((op.in1[0] + 0.25, op.in1[1] + 0.3)).label(pin_m, fontsize=8)
    d += elm.Label().at((op.out[0] - 0.25, op.out[1] + 0.3)).label(pin_o, fontsize=8)
    # + input: 10k from the buffer, 47k to VBIAS
    d += elm.Line().left(0.6).at(op.in2)
    d += (pp := elm.Dot())
    d += elm.Resistor().left().label('10k', fontsize=9)
    net(d, d.here, plus, loc='left')
    d += elm.Resistor().down().at(pp.center).label('47k', loc='bottom', fontsize=9)
    d += elm.Label().label('VBIAS', loc='bottom', fontsize=9)
    # - input: 10k from the other buffer, 47k with 100 pF across it back from the output
    d += elm.Line().left(0.6).at(op.in1)
    d += (mm := elm.Dot())
    d += elm.Resistor().left().label('10k', fontsize=9)
    net(d, d.here, minus, loc='left')
    d += elm.Line().up(1.2).at(mm.center)
    d += (m2 := elm.Dot())
    d += elm.Resistor().right().tox(op.out[0] + 0.6).label('47k', fontsize=9)
    d += elm.Line().toy(op.out[1])
    d += elm.Line().up(1.1).at(m2.center)
    d += elm.Capacitor().right().tox(op.out[0] + 0.6).label('100 pF', fontsize=9)
    d += elm.Line().toy(m2.center[1])
    d += elm.Line().right(0.6).at(op.out)
    d += elm.Dot()
    d += elm.Capacitor().right().label('1 µF film', fontsize=9)
    d += elm.Resistor().right().label('100 Ω', fontsize=9)
    net(d, d.here, outname)
    return op


def amplifiers():
    d = sheet('2_amplifiers.svg')
    note(d, (-4.0, 4.0), 'PMDS prototype radio, step 3, sheet 2: the amplifiers, from the sampling capacitors to the Audio Adaptor', 14)
    note(d, (-4.0, 2.9), 'Each buffer: x11 at 12 kHz, x1 at DC, so every output sits at the 2.5 V bias. U3, U4, U5: MCP6022, pin 8 to +5VA, pin 4 to GND, 100 nF across.')
    for k, (unit, pins, xin, name) in enumerate((
            ('U3A', ('3', '2', '1'), 'X0 (C6, U1 pin 12)', 'A0'),
            ('U3B', ('5', '6', '7'), 'X1 (C7, U1 pin 14)', 'A1'),
            ('U4A', ('3', '2', '1'), 'X2 (C8, U1 pin 15)', 'A2'),
            ('U4B', ('5', '6', '7'), 'X3 (C9, U1 pin 11)', 'A3'))):
        buffer(d, 0, -7.0 * k, unit, pins, xin, name)
    diffamp(d, 17.5, -4.0, 'U5A', ('3', '2', '1'), 'A0 (U3A pin 1)', 'A3 (U4B pin 7)', 'I: LINE IN L')
    diffamp(d, 17.5, -15.0, 'U5B', ('5', '6', '7'), 'A2 (U4A pin 1)', 'A1 (U3B pin 7)', 'Q: LINE IN R')
    note(d, (12.5, 2.0), 'I = 4.7 x (X0 - X3)   Q = 4.7 x (X2 - X1)\nA station above the oscillator comes out at +12 kHz.\n'
                          'If the decoder never finds it, swap the two line-input wires.')
    # bias and the analog supply
    x0, y0 = 13.0, -23.0
    d += elm.Vdd().at((x0, y0)).label('+5VA', fontsize=10)
    d += elm.Resistor().down().at((x0, y0)).label('R3 10k', loc='bottom', fontsize=9)
    d += (bias := elm.Dot())
    d += elm.Resistor().down().label('R4 10k', loc='bottom', fontsize=9)
    d += elm.Ground()
    d += elm.Line().right(1.5).at(bias.center)
    d += (b2 := elm.Dot())
    d += elm.Capacitor(polar=True).down().label('47 µF', loc='bottom', fontsize=9)
    d += elm.Ground()
    d += elm.Line().right(1.5).at(b2.center)
    d += (b3 := elm.Dot())
    d += elm.Capacitor().down().label('100 nF', loc='bottom', fontsize=9)
    d += elm.Ground()
    d += elm.Line().right(1.0).at(b3.center)
    net(d, d.here, 'VBIAS, 2.5 V (also R1 on sheet 1)')
    x1 = 23.0
    note(d, (x1, y0 + 0.8), 'The analog supply:')
    d += elm.Line().right(0.8).at((x1, y0 - 0.6))
    d += elm.Label().at((x1, y0 - 0.6)).label('+5V (Teensy VIN)', loc='left', fontsize=10, halign='right')
    d += elm.RBox(width=0.9, height=0.4).right().label('FB1 ferrite\nbead', fontsize=9)
    d += (s1 := elm.Dot())
    d += elm.Capacitor(polar=True).down().at(s1.center).label('100 µF', loc='bottom', fontsize=9)
    d += elm.Ground()
    d += elm.Line().right(1.5).at(s1.center)
    d += (s2 := elm.Dot())
    d += elm.Capacitor().down().label('100 nF', loc='bottom', fontsize=9)
    d += elm.Ground()
    d += elm.Line().right(1.0).at(s2.center)
    net(d, d.here, '+5VA')
    note(d, (x1 + 2.0, y0 - 5.4), '+5VA feeds U1 to U5 and R3')
    d.save(os.path.join(HERE, '2_amplifiers.svg'))


# ---- sheet 3: the Teensy and what connects to it -------------------------------------------------
def teensy():
    d = sheet('3_teensy.svg')
    note(d, (-12.0, 8.6), 'PMDS prototype radio, step 3, sheet 3: the Teensy 4.1 and what connects to it', 14)
    note(d, (-12.0, 7.5), 'The Teensy 4.1\'s pins take 3.3 V only. Power the Si5351 board, the display and the encoder from '
                           'the Teensy\'s 3.3V pin, never 5 V, so their pull-up\nresistors stay at 3.3 V. Everything runs '
                           'from the one USB cable. Audio Adaptor pins are joined to the Teensy pins with the same numbers.')
    right = ['7 (I2S out)', '8 (I2S in)', '20 (LRCLK)', '21 (BCLK)', '23 (MCLK)', '18 (SDA)', '19 (SCL)']
    t = ic('Teensy', [elm.IcPin(name='2', side='left', slot='1/6'),
                      elm.IcPin(name='3', side='left', slot='2/6'),
                      elm.IcPin(name='4', side='left', slot='3/6'),
                      elm.IcPin(name='GND', side='left', slot='4/6'),
                      elm.IcPin(name='3.3V', side='left', slot='5/6'),
                      elm.IcPin(name='VIN', side='left', slot='6/6')] +
           [elm.IcPin(name=n, side='right', slot='%d/7' % (i + 1)) for i, n in enumerate(right)],
           (7.0, 8.0), 'Teensy 4.1')
    d += (t := t.at((0, 0)).anchor('GND'))
    note(d, (t.GND[0] + 2.6, t.GND[1] - 2.2), '(USB to the PC)')
    aa = ic('AA', [elm.IcPin(name=n.split()[0], side='left', slot='%d/7' % (i + 1)) for i, n in enumerate(right)] +
            [elm.IcPin(name='3.3V', side='top', pos=1.5), elm.IcPin(name='GND', side='top', pos=5.0),
             elm.IcPin(name='LINE IN L', side='right', slot='4/4'), elm.IcPin(name='LINE IN R', side='right', slot='3/4'),
             elm.IcPin(name='LINE IN GND', side='right', slot='2/4'), elm.IcPin(name='LINE OUT L', side='right', slot='1/4')],
            (7.0, 8.0), 'Audio Adaptor\nRev D')
    p7 = getattr(t, '7 (I2S out)')
    d += (au := aa.at((p7[0] + 6.0, p7[1])).anchor('7'))
    note(d, (au.LINE_OUT_L[0] - 5.0, au.LINE_OUT_L[1] - 1.4) if hasattr(au, 'LINE_OUT_L') else (p7[0] + 8.0, p7[1] - 1.4),
         '(headphone jack on the board)')
    for n in right:
        q = n.split()[0]
        d += elm.Line().at(getattr(t, n)).tox(getattr(au, q)[0])
    p19 = getattr(t, '19 (SCL)')
    note(d, (p19[0] + 0.3, p19[1] + 1.5), 'Pins 18 (SDA) and 19 (SCL) also go to\nthe Si5351 (sheet 1) and the display')
    for pin in ('3.3V', 'GND'):
        d += elm.Line().up(0.6).at(getattr(au, pin))
        d += elm.Label().label('+3V3' if pin == '3.3V' else 'GND', loc='top', fontsize=9)
    for pin, txt in (('LINE IN L', 'I, from U5A pin 1 via 1 µF + 100 Ω (sheet 2)'),
                     ('LINE IN R', 'Q, from U5B pin 7 via 1 µF + 100 Ω (sheet 2)'),
                     ('LINE IN GND', 'GND'), ('LINE OUT L', 'to the LM386 amplifier (step 4)')):
        d += elm.Line().right(0.8).at(getattr(au, pin))
        net(d, d.here, txt)
    for pin, txt in (('VIN', '+5V from USB: to FB1 (sheet 2)'), ('3.3V', '+3V3: Audio Adaptor, Si5351, display, encoder'),
                     ('GND', 'GND')):
        d += elm.Line().left(0.8).at(getattr(t, pin))
        net(d, d.here, txt, loc='left')
    # the encoder: CLK, DT, SW to Teensy pins 2, 3, 4
    enc = ic('ENC', [elm.IcPin(name='CLK', side='right', slot='1/3'), elm.IcPin(name='DT', side='right', slot='2/3'),
                     elm.IcPin(name='SW', side='right', slot='3/3'),
                     elm.IcPin(name='+', side='left', slot='2/2'), elm.IcPin(name='GND', side='left', slot='1/2')],
             (3.6, 3.0), 'Rotary encoder\nKY-040')
    d += (en := enc.at((getattr(t, '2')[0] - 9.0, getattr(t, '2')[1] - 5.0)).anchor('CLK'))
    for ep, tp, run in (('CLK', '2', 3.4), ('DT', '3', 2.6), ('SW', '4', 1.8)):
        d += elm.Line().at(getattr(en, ep)).right(run)
        d += elm.Line().toy(getattr(t, tp)[1])
        d += elm.Line().tox(getattr(t, tp)[0])
    d += elm.Line().left(0.6).at(getattr(en, '+'))
    net(d, d.here, '+3V3', loc='left')
    d += elm.Line().left(0.6).at(en.GND)
    net(d, d.here, 'GND', loc='left')
    # the display
    oled = ic('OLED', [elm.IcPin(name='VCC', side='left', slot='4/4'), elm.IcPin(name='GND', side='left', slot='3/4'),
                       elm.IcPin(name='SDA', side='left', slot='2/4'), elm.IcPin(name='SCL', side='left', slot='1/4')],
              (4.4, 3.4), '1.3" OLED\nI2C, 128x64')
    d += (ol := oled.at((au.LINE_IN_L[0] + 3.0, au.GND[1] + 4.5) if hasattr(au, 'LINE_IN_L') else (p7[0] + 22.0, 9.0)).anchor('SDA'))
    for pin, txt in (('VCC', '+3V3'), ('GND', 'GND'), ('SDA', 'Teensy 18 (SDA)'), ('SCL', 'Teensy 19 (SCL)')):
        d += elm.Line().left(0.6).at(getattr(ol, pin))
        net(d, d.here, txt, loc='left')
    note(d, (ol.SCL[0] - 4.2, ol.SCL[1] - 1.2), 'I2C addresses: Audio Adaptor (SGTL5000) 0x0A,\n'
                                                 'Si5351 0x60, display 0x3C. All share one bus.\n'
                                                 'The Si5351 board is on sheet 1.')
    d.save(os.path.join(HERE, '3_teensy.svg'))


if __name__ == '__main__':
    rf_mixer()
    amplifiers()
    teensy()
    print('drew 1_rf_mixer.svg, 2_amplifiers.svg, 3_teensy.svg')
