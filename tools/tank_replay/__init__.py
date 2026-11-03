"""Replay model.py over the recorded data in data/<site> and score it against the truth.

Modules:
    models      load model.py (working tree or a git tag), build TankParameters
    recordings  read the daily CSVs and the owner's truth spans
    scoring     replay, score against the truth, compare two versions
    report      the JSON summary and the per-tick CSV
    chart       the PREV vs NEXT chart (dark mode, colour-blind safe)
    cli         command-line entry point (tools/replay.py)
"""
