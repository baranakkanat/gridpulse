"""Leak-free feature table for the daily 24-hour-ahead forecasting task.

One row per (forecast origin, lead). Historical load features are looked up by UTC
timestamp label through the seasonal naive baseline, which guarantees that every source
observation starts strictly before the forecast origin. Calendar features depend only on
the target timestamp, which is known when the forecast is issued.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gridpulse.baseline import DAILY_SEASON, WEEKLY_SEASON, seasonal_naive_forecast
from gridpulse.calendar_analysis import is_national_holiday, local_times

# Model features in model order, with the reason each is available at the forecast origin.
FEATURE_DEFINITIONS = {
    "lag_24h_mw": "load(target - 24 h); its interval starts 1-24 h before the origin",
    "lag_168h_mw": "load(target - 168 h); its interval starts 145-168 h before the origin",
    "target_local_hour": "Europe/Berlin hour of the target (0-23), from the timestamp only",
    "target_local_weekday": "Europe/Berlin weekday of the target (Monday = 0), from the timestamp",
    "target_local_month": "Europe/Berlin month of the target (1-12), from the timestamp only",
}
FEATURES = tuple(FEATURE_DEFINITIONS)
TARGET = "actual_load_mw"
# Optional known-ahead holiday flags (Track 1 experiment C2), 1 if the Europe/Berlin local
# date is a nationwide public holiday. They depend only on calendar dates.
HOLIDAY_FEATURE_DEFINITIONS = {
    "target_is_holiday": "the target's local date is a nationwide public holiday",
    "lag_24h_source_is_holiday": "the 24-hour lag source's local date is a holiday",
    "lag_168h_source_is_holiday": "the 168-hour lag source's local date is a holiday",
}
HOLIDAY_FEATURES = tuple(HOLIDAY_FEATURE_DEFINITIONS)


def feature_table(load: pd.Series, origins: pd.DatetimeIndex) -> pd.DataFrame:
    """Features, the source timestamp of each lag feature and the observed target.

    `lag_24h_mw` = load(target - 24 h) and `lag_168h_mw` = load(target - 168 h); for every
    lead both sources precede the origin. Unavailable sources give NaN, never a filled
    value. Calendar features are the target's Europe/Berlin hour (0-23), weekday
    (Monday = 0) and month (1-12).
    """
    daily = seasonal_naive_forecast(load, origins, DAILY_SEASON)
    weekly = seasonal_naive_forecast(load, origins, WEEKLY_SEASON)
    targets = pd.DatetimeIndex(daily["target_timestamp_utc"])
    local = local_times(daily["target_timestamp_utc"])
    actual = load.reindex(targets).to_numpy()
    return pd.DataFrame(
        {
            "forecast_origin_utc": daily["forecast_origin_utc"],
            "target_timestamp_utc": daily["target_timestamp_utc"],
            "lead_hours": daily["lead_hours"],
            "lag_24h_source_utc": daily["reference_timestamp_utc"],
            "lag_168h_source_utc": weekly["reference_timestamp_utc"],
            "lag_24h_mw": daily["predicted_load_mw"],
            "lag_168h_mw": weekly["predicted_load_mw"],
            "target_local_hour": local.hour,
            "target_local_weekday": local.dayofweek,
            "target_local_month": local.month,
            TARGET: np.where(np.isfinite(actual), actual, np.nan),
        }
    )


def with_holiday_flags(rows: pd.DataFrame) -> pd.DataFrame:
    """Add the holiday flags for the target and both lag sources (0/1 integers)."""
    sources = {
        "target_is_holiday": "target_timestamp_utc",
        "lag_24h_source_is_holiday": "lag_24h_source_utc",
        "lag_168h_source_is_holiday": "lag_168h_source_utc",
    }
    return rows.assign(
        **{
            flag: is_national_holiday(rows[column]).astype(np.int8)
            for flag, column in sources.items()
        }
    )


def has_features(rows: pd.DataFrame, features: tuple[str, ...] = FEATURES) -> np.ndarray:
    """Whether every listed feature of each row is available (finite)."""
    return np.isfinite(rows[list(features)].to_numpy(dtype=float)).all(axis=1)


def is_usable(rows: pd.DataFrame, features: tuple[str, ...] = FEATURES) -> np.ndarray:
    """Whether each row has all features and an observed target, i.e. can be fitted on."""
    return has_features(rows, features) & np.isfinite(rows[TARGET].to_numpy())


def availability_counts(rows: pd.DataFrame, features: tuple[str, ...] = FEATURES) -> dict:
    """Rows, complete rows and the (overlapping) reasons why other rows cannot be used."""
    usable = is_usable(rows, features)
    return {
        "n_rows": len(rows),
        "n_usable": int(usable.sum()),
        "n_excluded": int((~usable).sum()),
        "excluded_because": {
            "lag_24h_unavailable": int(rows["lag_24h_mw"].isna().sum()),
            "lag_168h_unavailable": int(rows["lag_168h_mw"].isna().sum()),
            "target_unavailable": int(rows[TARGET].isna().sum()),
        },
    }
