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
PMDS (Phase Modulation Data Service, working name): RDS-style station data on the phase of a
mono AM carrier. Reference encoder and decoder, pure Python and numpy, no GNU Radio needed.

    pmds.codec     character set, check code, blocks and groups
    pmds.sources   RadioText rotation line and now-playing files
    pmds.encoder   Encoder: group schedule and phase waveform
    pmds.framer    block sync, correction and group parsing
    pmds.demod     Demodulator: bits from the carrier's phase, then the framers
"""
from .codec import callsign_to_pi, pi_to_callsign, text_to_codes, codes_to_text
from .encoder import Encoder
from .demod import Demodulator

__version__ = '0.1.1'
__all__ = ['Encoder', 'Demodulator', 'callsign_to_pi', 'pi_to_callsign', 'text_to_codes',
           'codes_to_text']
