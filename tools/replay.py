"""Replay model.py over the recorded data and score it. See tools/tank_replay/ and `--help`.

    python tools/replay.py --site cr
    python tools/replay.py --baseline-ref v0.2.0 --from 2026-11-01 --to 2026-11-02 --chart compare.svg
"""
import sys

from tank_replay.cli import main     # tools/ is on sys.path when this file is run as a script

if __name__ == "__main__":
    sys.exit(main())
