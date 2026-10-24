"""Make the frozen Phase 9 modules and this follow-up's `calibration` importable without
installing anything."""

import sys
from pathlib import Path

FOLLOWUP = Path(__file__).resolve().parents[1]
PHASE9 = FOLLOWUP.parents[0] / "phase9"

for path in (PHASE9, FOLLOWUP):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
