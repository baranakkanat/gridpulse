"""Make the frozen Phase 9 modules, the AKK-39 follow-up and this pilot importable without
installing anything."""

import sys
from pathlib import Path

PILOT = Path(__file__).resolve().parents[1]
ANALYSIS = PILOT.parent
PHASE9 = ANALYSIS / "phase9"
FOLLOWUP = ANALYSIS / "phase9_followup"

for path in (PHASE9, FOLLOWUP, PILOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
