"""Loading, validation and preparation of the OPSD hourly German load series."""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

TIMESTAMP_COLUMN = "utc_timestamp"
TARGET_COLUMN = "DE_load_actual_entsoe_transparency"
TARGET_UNIT = "MW"
HOUR = pd.Timedelta(hours=1)

DATASET = {
    "name": "Open Power System Data: Time series",
    "version": "2020-10-06",
    "doi": "https://doi.org/10.25832/time_series/2020-10-06",
    "source_url": (
        "https://data.open-power-system-data.org/time_series/2020-10-06/"
        "time_series_60min_singleindex.csv"
    ),
    "filename": "time_series_60min_singleindex.csv",
    "bytes": 130339665,
    # `hash` field of this resource in the official datapackage.json.
    "sha256": "6a7f2bc571314cbf9c321cc03437691cd4be95c3a6f075e60ff99e8035c704c8",
}

# Chronological periods as half-open UTC intervals [start, end).
SPLITS = {
    "train": (pd.Timestamp("2015-01-01", tz="UTC"), pd.Timestamp("2018-01-01", tz="UTC")),
    "validation": (pd.Timestamp("2018-01-01", tz="UTC"), pd.Timestamp("2019-01-01", tz="UTC")),
    "test": (pd.Timestamp("2019-01-01", tz="UTC"), pd.Timestamp("2020-01-01", tz="UTC")),
}
# Observations from here on are reserved for future research and never used by experiments.
RESERVED_FROM = pd.Timestamp("2020-01-01", tz="UTC")

_LARGEST_CHANGES_REPORTED = 10
_GAPS_REPORTED = 50


def utc_iso(timestamp: pd.Timestamp) -> str:
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_time_index(index: pd.DatetimeIndex) -> list[str]:
    """Return the reasons why `index` is not a usable hourly UTC time index (empty if usable)."""
    if index.tz is None or str(index.tz) != "UTC":
        return [f"timestamps must be timezone-aware UTC, got tz={index.tz}"]
    problems = []
    duplicated = index[index.duplicated()].unique()
    if len(duplicated):
        problems.append(f"{len(duplicated)} duplicated timestamp(s), e.g. {_examples(duplicated)}")
    elif not index.is_monotonic_increasing:
        problems.append("timestamps are not in increasing order")
    off_hour = index[index != index.floor("h")]
    if len(off_hour):
        problems.append(
            f"{len(off_hour)} timestamp(s) not at the start of an hour, e.g. {_examples(off_hour)}"
        )
    return problems


def _examples(timestamps: pd.DatetimeIndex, n: int = 3) -> str:
    return ", ".join(utc_iso(t) for t in timestamps[:n])


def read_source(path: str | Path) -> pd.Series:
    """Read the UTC timestamps and target values from an OPSD singleindex CSV.

    Only the two required columns are parsed. Timestamps must carry an explicit UTC
    designator. Rows are returned exactly as in the file: not sorted, deduplicated or
    regularized. Only empty fields count as missing (NaN); any other text that is not a
    number, including "NA" or "null", raises ValueError.
    """
    header = pd.read_csv(path, nrows=0).columns
    missing = [c for c in (TIMESTAMP_COLUMN, TARGET_COLUMN) if c not in header]
    if missing:
        raise ValueError(f"{path}: required column(s) missing: {missing}")

    try:
        frame = pd.read_csv(
            path,
            usecols=[TIMESTAMP_COLUMN, TARGET_COLUMN],
            dtype={TIMESTAMP_COLUMN: "str", TARGET_COLUMN: "float64"},
            keep_default_na=False,
            na_values={TIMESTAMP_COLUMN: [""], TARGET_COLUMN: [""]},
        )
    except ValueError as error:
        raise ValueError(f"{path}: column {TARGET_COLUMN} is not numeric: {error}") from error
    if frame.empty:
        raise ValueError(f"{path}: no data rows")
    n_empty_timestamps = int(frame[TIMESTAMP_COLUMN].isna().sum())
    if n_empty_timestamps:
        raise ValueError(f"{path}: {n_empty_timestamps} empty {TIMESTAMP_COLUMN} value(s)")

    timestamps = pd.DatetimeIndex(
        pd.to_datetime(frame[TIMESTAMP_COLUMN], format="ISO8601"), name=TIMESTAMP_COLUMN
    )
    if timestamps.tz is None or str(timestamps.tz) != "UTC":
        raise ValueError(
            f"{path}: {TIMESTAMP_COLUMN} must be UTC with an explicit designator "
            f"(e.g. 2015-01-01T00:00:00Z), got tz={timestamps.tz}"
        )
    return pd.Series(frame[TARGET_COLUMN].to_numpy(), index=timestamps, name="load_mw")


def hourly_load(source: pd.Series) -> pd.Series:
    """Place the source observations on a complete hourly UTC grid.

    Timestamps absent from the source and non-finite source values become NaN, i.e.
    unavailable. Values are otherwise unchanged: no filling, clipping or interpolation.
    """
    problems = check_time_index(source.index)
    if problems:
        raise ValueError("cannot build an hourly series: " + "; ".join(problems))
    grid = pd.date_range(source.index[0], source.index[-1], freq="h", name=TIMESTAMP_COLUMN)
    return source.where(np.isfinite(source)).reindex(grid)


def quality_report(source: pd.Series) -> dict:
    """Summarize schema, temporal coverage and numerical validity of the source rows.

    Temporal sections (intervals, gaps, hourly changes, coverage) are only included when
    the time index has no blocking problems, because they are not well defined otherwise.
    """
    timestamps = source.index
    values = source.to_numpy()
    available = np.isfinite(values)
    problems = check_time_index(timestamps)

    finite_values = values[available]
    distribution = None
    if finite_values.size:
        quantiles = np.quantile(finite_values, [0.01, 0.25, 0.5, 0.75, 0.99])
        distribution = {
            "min": finite_values.min(),
            "p01": quantiles[0],
            "p25": quantiles[1],
            "median": quantiles[2],
            "mean": finite_values.mean(),
            "p75": quantiles[3],
            "p99": quantiles[4],
            "max": finite_values.max(),
            "std": finite_values.std(ddof=1) if finite_values.size > 1 else None,
        }

    report = {
        "target_column": TARGET_COLUMN,
        "unit": TARGET_UNIT,
        "n_source_rows": len(source),
        "first_timestamp_utc": utc_iso(timestamps.min()),
        "last_timestamp_utc": utc_iso(timestamps.max()),
        "time_index_problems": problems,
        "target": {
            "available": int(available.sum()),
            "missing_in_source_rows": int(np.isnan(values).sum()),
            "infinite_in_source_rows": int(np.isinf(values).sum()),
            "negative": int((finite_values < 0).sum()),
            "zero": int((finite_values == 0).sum()),
            "first_available_utc": utc_iso(timestamps[available].min())
            if available.any()
            else None,
            "last_available_utc": utc_iso(timestamps[available].max()) if available.any() else None,
            "distribution_mw": distribution,
        },
    }
    if not problems:
        report.update(_temporal_summary(timestamps, values, available))
    return _to_builtin(report)


def _temporal_summary(
    timestamps: pd.DatetimeIndex, values: np.ndarray, available: np.ndarray
) -> dict:
    """Intervals, gaps, hourly changes and coverage of a sorted, unique, on-the-hour index."""
    grid = pd.date_range(timestamps[0], timestamps[-1], freq="h")
    absent = grid.difference(timestamps)

    steps = timestamps[1:] - timestamps[:-1]
    step_hours = pd.Series(steps / HOUR).value_counts().sort_index()
    gap_positions = np.flatnonzero(steps > HOUR)
    gaps = [
        {
            "last_before_utc": utc_iso(timestamps[i]),
            "first_after_utc": utc_iso(timestamps[i + 1]),
            "missing_hours": int(steps[i] / HOUR) - 1,
        }
        for i in gap_positions[:_GAPS_REPORTED]
    ]

    changes = np.diff(values)
    candidates = np.flatnonzero((steps == HOUR) & available[1:] & available[:-1])
    largest = candidates[np.argsort(-np.abs(changes[candidates]), kind="stable")]
    largest_changes = [
        {"timestamp_utc": utc_iso(timestamps[i + 1]), "change_from_previous_hour_mw": changes[i]}
        for i in largest[:_LARGEST_CHANGES_REPORTED]
    ]

    def per_year(index: pd.DatetimeIndex) -> pd.Series:
        return pd.Series(index.year).value_counts()

    grid_by_year = per_year(grid)
    rows_by_year = per_year(timestamps)
    available_by_year = per_year(timestamps[available])
    absent_by_year = per_year(absent)
    coverage_by_year = {}
    for year in sorted(grid_by_year.index):
        rows = int(rows_by_year.get(year, 0))
        n_available = int(available_by_year.get(year, 0))
        coverage_by_year[str(year)] = {
            "hours_in_grid": int(grid_by_year[year]),
            "source_rows": rows,
            "available": n_available,
            "unavailable_in_source_rows": rows - n_available,
            "timestamps_absent_from_source": int(absent_by_year.get(year, 0)),
        }

    periods = dict(SPLITS)
    if grid[-1] >= RESERVED_FROM:
        periods["reserved"] = (RESERVED_FROM, grid[-1] + HOUR)
    coverage_by_period = {}
    for name, (start, end) in periods.items():
        n_available = int(((timestamps >= start) & (timestamps < end) & available).sum())
        expected = int((end - start) / HOUR)
        coverage_by_period[name] = {
            "start_utc": utc_iso(start),
            "end_exclusive_utc": utc_iso(end),
            "expected_hours": expected,
            "available": n_available,
            "unavailable": expected - n_available,
        }

    return {
        "interval_hours_counts": {f"{h:g}": n for h, n in step_hours.items()},
        "hours_in_grid": len(grid),
        "timestamps_absent_from_source": len(absent),
        "n_gaps": len(gap_positions),
        "gaps": gaps,
        "largest_hourly_changes": largest_changes,
        "coverage_by_year": coverage_by_year,
        "coverage_by_period": coverage_by_period,
    }


def _to_builtin(value):
    """Convert NumPy scalars inside nested dicts/lists to JSON-serializable Python types."""
    if isinstance(value, dict):
        return {key: _to_builtin(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_builtin(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    return value
