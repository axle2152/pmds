# Copyright 2026 Michael Foley
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software: you can redistribute it and/or modify it under the terms of
# the GNU General Public License as published by the Free Software Foundation, either version 3
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
# without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# See the GNU General Public License for more details: <https://www.gnu.org/licenses/>.
"""
PMDS encoder block for GNU Radio: a thin wrapper around pmds.Encoder.

Input  : complex baseband from the AM modulator (mono AM: a real, positive envelope).
Output : the same signal with the data added as slow phase modulation, y = x * e^(j*theta).
         The envelope is untouched, so envelope detectors see nothing.

The parameters, the group schedule and the text sources are described in pmds.encoder.
The sample rate has to be a whole multiple of the bit rate: 192000, 96000 or 48000. At any
other rate the bit rate comes out wrong, and this block prints a warning.
The pmds package has to be importable: install it once from the radioconda prompt with
    pip install -e <the folder that holds pmds>
or keep the pmds folder beside the flowgraph and start GNU Radio Companion from there.
"""
import os
import sys

import numpy as np
from gnuradio import gr

try:
    from pmds.encoder import Encoder
except ImportError:                                  # not installed: look in the working folder
    sys.path.insert(0, os.getcwd())
    try:
        from pmds.encoder import Encoder
    except ImportError:
        raise ImportError('PMDS: the pmds package was not found. Install it once with '
                          '"pip install -e <folder that holds pmds>", or start GNU Radio '
                          'Companion from that folder.') from None


class blk(Encoder, gr.sync_block):
    """PMDS encoder: RDS-style station data on the carrier's phase. Parameters and text
    sources are described in pmds.encoder."""

    strict_rate = False       # a sample rate the bit rate doesn't divide: warn, don't stop

    def __init__(self, samp_rate=192000, data_on=1, deviation=8.6, bit_rate=93.75, fmt='compact',
                 call='WAMD', pi='', pty=4, tp=0, ta=0, ps='AM 1710', ps_upper=1, ps_file='',
                 rt='', rt_file='C:/RadioDJv2/Now_Playing.txt', rt_len=64, rt_every=1,
                 facility_id=0, af='', ext_every=8,
                 alert=0, alert_text='This is a test of the AM data alert flag. This is only a test.',
                 alert_file='', rt_program=''):
        gr.sync_block.__init__(self, name='PMDS Encoder',
                               in_sig=[np.complex64], out_sig=[np.complex64])
        Encoder.__init__(self, samp_rate=samp_rate, data_on=data_on, deviation=deviation,
                         bit_rate=bit_rate, fmt=fmt, call=call, pi=pi, pty=pty, tp=tp, ta=ta, ps=ps,
                         ps_upper=ps_upper, ps_file=ps_file, rt=rt, rt_file=rt_file, rt_len=rt_len,
                         rt_every=rt_every, facility_id=facility_id, af=af,
                         ext_every=ext_every, alert=alert, alert_text=alert_text,
                         alert_file=alert_file, rt_program=rt_program)

    def work(self, input_items, output_items):
        self.modulate(input_items[0], output_items[0])
        return len(input_items[0])
