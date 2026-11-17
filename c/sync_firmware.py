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
sync_firmware.py - copy the C decoder into the Teensy sketch.

    python c/sync_firmware.py           # copy
    python c/sync_firmware.py --check   # say whether the sketch's copy is current

The Arduino IDE builds a sketch only from its own folder, so firmware/teensy_rx/src/pmds holds
a copy of the decoder's files from c/. Edit them in c/, then run this.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, '..', 'firmware', 'teensy_rx', 'src', 'pmds')
FILES = ('pmds.h', 'pmds_framer.c', 'pmds_demod.c', 'pmds_front.c', 'pmds_text.c')


def stale():
    out = []
    for name in FILES:
        src = open(os.path.join(HERE, name), 'rb').read()
        dst_path = os.path.join(DEST, name)
        if not os.path.exists(dst_path) or open(dst_path, 'rb').read() != src:
            out.append(name)
    return out


def main():
    if '--check' in sys.argv:
        s = stale()
        print('the sketch has an old copy of: ' + ', '.join(s) if s else 'the sketch\'s copy is current')
        return 1 if s else 0
    os.makedirs(DEST, exist_ok=True)
    for name in FILES:
        with open(os.path.join(HERE, name), 'rb') as a, open(os.path.join(DEST, name), 'wb') as b:
            b.write(a.read())
    print('copied %d files to %s' % (len(FILES), os.path.normpath(DEST)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
