"""Seasonal naive baselines for the daily 24-hour-ahead UTC forecasting task.

Task: at each forecast origin (00:00 UTC), predict the 24 hourly load values whose
intervals start at origin + 0 h, ..., origin + 23 h. Lead h (1..24) is the interval
starting at origin + (h - 1) hours. Only observations from intervals starting before
the origin may be used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from gridpulse.data import HOUR, check_time_index

HORIZON_HOURS = 24
WEEKLY_SEASON = pd.Timedelta(hours=168)
DAILY_SEASON = pd.Timedelta(hours=24)
DAILY_NAIVE, WEEKLY_NAIVE = "daily_naive", "weekly_naive"
# The reference baselines, keyed by the name used in outputs.
SEASONAL_NAIVE_BASELINES = {DAILY_NAIVE: DAILY_SEASON, WEEKLY_NAIVE: WEEKLY_SEASON}


def daily_origins(start: pd.Timestamp, end: pd.Timestamp) -> pd.DatetimeIndex:
    """Daily 00:00 UTC origins whose 24 target intervals all lie within [start, end)."""
    if str(start.tz) != "UTC" or str(end.tz) != "UTC":
        raise ValueError("period boundaries must be UTC timestamps")
    if start != start.normalize() or end != end.normalize():
        raise ValueError("period boundaries must be at 00:00 UTC")
    return pd.date_range(start, end - HORIZON_HOURS * HOUR, freq="D", name="forecast_origin_utc")


def seasonal_naive_forecast(
    load: pd.Series, origins: pd.DatetimeIndex, season_length: pd.Timedelta = WEEKLY_SEASON
) -> pd.DataFrame:
    """Predict each target interval with the load observed exactly `season_length` earlier.

    `load` is an hourly series indexed by UTC interval-start timestamps, with NaN marking
    unavailable observations. Returns one row per (origin, lead hour) including the
    reference timestamp that produced the prediction. The prediction is NaN when the
    reference observation is unavailable or outside the series.
    """
    problems = check_time_index(load.index)
    if problems:
        raise ValueError("load index is not a valid hourly UTC index: " + "; ".join(problems))
    if str(origins.tz) != "UTC" or (origins != origins.normalize()).any():
        raise ValueError("forecast origins must be 00:00 UTC timestamps")
    if not origins.is_unique:
        raise ValueError("forecast origins must be unique")
    if season_length <= pd.Timedelta(0) or season_length % HOUR != pd.Timedelta(0):
        raise ValueError(
            f"season length must be a positive whole number of hours, got {season_length}"
        )

    lead_hours = np.tile(np.arange(1, HORIZON_HOURS + 1), len(origins))
    origin = origins.repeat(HORIZON_HOURS)
    target = origin + pd.to_timedelta(lead_hours - 1, unit="h")
    reference = target - season_length
    if not (reference < origin).all():
        raise ValueError(
            f"season length {season_length} would use observations at or after the forecast origin"
        )

    predicted = load.reindex(reference).to_numpy()
    return pd.DataFrame(
        {
            "forecast_origin_utc": origin,
            "target_timestamp_utc": target,
            "lead_hours": lead_hours,
            "reference_timestamp_utc": reference,
            "predicted_load_mw": np.where(np.isfinite(predicted), predicted, np.nan),
        }
    )
