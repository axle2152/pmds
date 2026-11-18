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
make_test_iq.py - simulated PMDS stations as I/Q WAV files, for the C decoder and the Teensy.

    python c/make_test_iq.py                       # the standard set, into c/testfiles/
    python c/make_test_iq.py --out D:/ --secs 120  # straight onto a microSD card

Each file is what the prototype radio's front end would hand the Teensy: I on the left
channel, Q on the right, 16 bits at 44100 Hz, the station's carrier 12 kHz above 0 Hz (the
low IF). Numpy only, no GNU Radio.

The bits come from pmds.Encoder's own group schedule; the phase is drawn with a running bit
clock (bit k covers k/93.75 to (k+1)/93.75 seconds wherever the samples fall), so any sample
rate gives the exact bit rate. The station: program noise to 4.5 kHz at 25% rms (bass-heavy
if asked), held to -98% and +125%, the data at 8.6 degrees, then a tuning error, noise and,
if asked, slow fading.
"""
import argparse
import math
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from pmds import codec  # noqa: E402
from pmds.encoder import Encoder  # noqa: E402

RATE, IF_HZ = 44100, 12000.0


def bits_for(enc, nbits):
    out = []
    while len(out) < nbits:
        _, blocks, n = enc.next_group()
        out.extend(codec.blocks_to_bits(blocks, n).tolist())
    return np.array(out[:nbits], dtype=np.int8)


def lowpass_noise(rng, n, fs, cutoff):
    w = np.fft.rfft(rng.standard_normal(n))
    w[np.fft.rfftfreq(n, 1 / fs) > cutoff] = 0
    x = np.fft.irfft(w, n)
    return x / x.std()


def make(secs=60.0, fs=RATE, if_hz=IF_HZ, offset_hz=0.0, cn_db=40.0, deviation=8.6, bass=False,
         fade_hz=0.0, clock_ppm=0.0, seed=1, alert=0, **station):
    """Complex I/Q of one station. offset_hz: tuning error; fade_hz: Rayleigh-like fading on a
    sky path with this Doppler spread (0: steady); clock_ppm: the transmitter's bit clock
    against the receiver's sample clock."""
    rng = np.random.default_rng(seed)
    station.setdefault('rt_file', '')
    enc = Encoder(samp_rate=6000, alert=alert, **station)
    enc.quiet = True
    n = int(secs * fs)
    t = np.arange(n) / fs
    pos = t * 93.75 * (1 + clock_ppm * 1e-6)
    k = np.floor(pos).astype(np.int64)
    bits = bits_for(enc, int(k[-1]) + 1)
    theta = math.radians(deviation) * (2.0 * bits[k] - 1) * np.sin(2 * np.pi * (pos - k))
    prog = 0.25 * lowpass_noise(rng, n, fs, 4500)
    if bass:
        prog += 0.30 * lowpass_noise(rng, n, fs, 250)
    env = np.clip(1 + prog, 0.02, 2.25)
    z = env * np.exp(1j * theta)
    if fade_hz:                                          # one fading sky path, Gaussian Doppler
        m = int(secs * 50) + 8
        g = rng.standard_normal(m) + 1j * rng.standard_normal(m)
        G = np.fft.fft(g)
        f = np.fft.fftfreq(m, 1 / 50.0)
        G *= np.exp(-0.5 * (f / (fade_hz / 2)) ** 2)
        g = np.fft.ifft(G)
        g /= np.sqrt(np.mean(np.abs(g) ** 2))
        tg = np.arange(m) / 50.0
        z = z * (np.interp(t, tg, g.real) + 1j * np.interp(t, tg, g.imag))
    z = z * np.exp(2j * np.pi * (if_hz + offset_hz) * t)
    sd = math.sqrt(fs / (10 ** (cn_db / 10) * 1e4) / 2)
    z = z + sd * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
    return z


def write_wav(path, z, fs=RATE, peak=0.45):
    """16-bit stereo, I left and Q right, scaled so the strongest moment sits at `peak` of full
    scale (a front end with headroom)."""
    s = peak / max(np.max(np.abs(z.real)), np.max(np.abs(z.imag)), 1e-9)
    pcm = np.empty(2 * len(z), np.int16)
    pcm[0::2] = np.clip(np.round(z.real * s * 32767), -32768, 32767)
    pcm[1::2] = np.clip(np.round(z.imag * s * 32767), -32768, 32767)
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(pcm.tobytes())


STATION = dict(call='WAMD', ps='AM 1650', rt='Queen - Bohemian Rhapsody (Remastered 2011 Extended Version)',
               facility_id=73977, af='95.5,750')
SET = [   # file name, what it is, make() arguments
    ('PMDS01.WAV', 'clean, strong signal', dict()),
    ('PMDS02.WAV', 'tuned 37 Hz off, 15 dB C/N, bass-heavy program', dict(offset_hz=37, cn_db=15, bass=True)),
    ('PMDS03.WAV', 'night fading (0.1 Hz), 20 dB C/N', dict(fade_hz=0.1, cn_db=20)),
    ('PMDS04.WAV', 'weak: 8 dB C/N, tuned 420 Hz off', dict(offset_hz=-420, cn_db=8)),
    ('PMDS05.WAV', 'emergency alert on air', dict(alert=2, alert_text='Tornado warning for Fulton County '
                                                 'until 9 PM. Take shelter now.')),
]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'testfiles'))
    ap.add_argument('--secs', type=float, default=60.0)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for i, (name, what, args) in enumerate(SET):
        write_wav(os.path.join(a.out, name), make(a.secs, seed=i + 1, **dict(STATION, **args)))
        print('%s  %s' % (name, what), flush=True)


if __name__ == '__main__':
    main()
