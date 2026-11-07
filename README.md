# PMDS reference implementation

PMDS (Phase Modulation Data Service, working name) carries RDS-style station data on the
phase of a mono AM carrier. This folder holds the reference encoder and decoder and the
bench tools used to test them.

## Two licenses

| Where | What | License |
|---|---|---|
| `pmds/` | The encoder, decoder, framing and character set, in plain Python and numpy. No GNU Radio needed. | Apache 2.0 (`pmds/LICENSE`, `pmds/NOTICE`) |
| everything else | GNU Radio blocks and tools: `pmds_encoder.py`, `pmds_receiver.py`, `pmds_channel_test.py`, `pmds_check.py`, `pmds_monitor.py`, `skywave_channel.py`, `am_data_tx.grc` | GPL 3.0 or later (`COPYING`) |

Anyone building a radio or an encoder can take `pmds/` on its own. Nothing in it imports
GNU Radio or copies from GPL code, and it should stay that way.

## Setup

Install the `pmds` package once, pointing pip at the **top folder of this repository** (the one
that holds `pyproject.toml`), not at the inner `pmds/` folder.

Windows (radioconda prompt or MSYS2):

    pip install -e <path to this repository>

Linux (no `sudo`):

    git clone https://github.com/axle2152/pmds.git
    cd pmds
    pip install --user -e .

That makes `pmds` importable everywhere, including inside GNU Radio Companion. Without it,
keep the `pmds` folder beside the flowgraph and start GNU Radio Companion from this folder.

## Checks

    python tests/test_pmds.py               # check code, Appendix A test vectors, loopback (no GNU Radio)
    python examples/pmds_channel_test.py    # encoder -> skywave simulator -> decoder, every preset
    python examples/pmds_check.py pmds_tx.cfile  # decode a recording of the transmitter
