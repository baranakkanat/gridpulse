from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gridpulse.data import TARGET_COLUMN, TIMESTAMP_COLUMN


def hourly_index(start: str, periods: int) -> pd.DatetimeIndex:
    return pd.date_range(start, periods=periods, freq="h", tz="UTC", name=TIMESTAMP_COLUMN)


def hours_since_epoch(index: pd.DatetimeIndex) -> np.ndarray:
    """A value that identifies its own timestamp, so a prediction reveals its source hour."""
    return ((index - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(hours=1)).to_numpy()


@pytest.fixture
def write_opsd_csv(tmp_path: Path):
    """Write an OPSD-like singleindex CSV with string timestamps and target values."""

    def write(timestamps: list[str], values: list[str], name: str = "opsd.csv") -> Path:
        path = tmp_path / name
        frame = pd.DataFrame(
            {
                TIMESTAMP_COLUMN: timestamps,
                "cet_cest_timestamp": ["unused"] * len(timestamps),
                "AT_load_actual_entsoe_transparency": ["1.0"] * len(timestamps),
                TARGET_COLUMN: values,
            }
        )
        frame.to_csv(path, index=False)
        return path

    return write
