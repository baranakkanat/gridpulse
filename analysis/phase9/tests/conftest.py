"""Make `q1_voltage_residual` importable without installing anything."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
