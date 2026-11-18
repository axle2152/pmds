# The PMDS decoder in C, built and checked on a PC (Linux, or MSYS2 on Windows):
#     make            builds tools/pmds_decode
#     make test       runs tests/test_c.py, which checks it against the Python decoder
# The Teensy program (firmware/teensy_rx) builds from its own copy of these files in Arduino.
CC      ?= cc
CFLAGS  ?= -std=c99 -O2 -Wall -Wextra -pedantic
SRC      = pmds_framer.c pmds_demod.c pmds_front.c pmds_text.c

tools/pmds_decode: tools/pmds_decode.c $(SRC) pmds.h
	$(CC) $(CFLAGS) -o $@ tools/pmds_decode.c $(SRC) -lm

test: tools/pmds_decode
	python3 ../tests/test_c.py

clean:
	rm -f tools/pmds_decode tools/pmds_decode.exe

.PHONY: test clean
