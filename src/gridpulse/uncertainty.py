"""Rolling empirical prediction intervals and dependence-aware bootstrap intervals.

Neither gives a finite-sample guarantee here: residuals are temporally dependent and their
distribution shifts. Both are used descriptively and their behaviour is measured.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def rolling_conformal_halfwidths(
    residuals: pd.DataFrame, window_days: int = 56, alpha: float = 0.10
) -> pd.DataFrame:
    """Interval half-width for every (origin, lead) from past absolute residuals.

    `residuals` has one row per (forecast_origin_utc, lead_hours) with `abs_error` (NaN when
    unavailable). For origin d and lead h the half-width is the ceil((n + 1)(1 - alpha))-th
    smallest of the n finite absolute errors of lead h from origins d - window_days ...
    d - 1, all of whose targets end by origin d. It is infinite when that rank exceeds n.
    """
    if residuals.duplicated(["forecast_origin_utc", "lead_hours"]).any():
        raise ValueError("residuals contain duplicate (origin, lead) rows")
    origins = pd.DatetimeIndex(residuals["forecast_origin_utc"])
    days = pd.date_range(origins.min(), origins.max(), freq="D")
    day_index = days.get_indexer(origins)
    if (day_index < 0).any():
        raise ValueError("forecast origins must lie on a daily grid")
    leads = residuals["lead_hours"].to_numpy()
    errors = np.full((len(days), int(leads.max())), np.nan)
    errors[day_index, leads - 1] = residuals["abs_error"].to_numpy()
    halfwidths = np.full(errors.shape, np.inf)
    counts = np.zeros(errors.shape, dtype=int)
    for day in range(len(days)):
        window = errors[max(0, day - window_days) : day]
        for lead in range(errors.shape[1]):
            values = np.sort(window[np.isfinite(window[:, lead]), lead])
            n = len(values)
            rank = math.ceil((n + 1) * (1 - alpha))
            counts[day, lead] = n
            if 1 <= rank <= n:
                halfwidths[day, lead] = values[rank - 1]
    leads = np.arange(1, errors.shape[1] + 1)
    return pd.DataFrame(
        {
            "forecast_origin_utc": np.repeat(days, len(leads)),
            "lead_hours": np.tile(leads, len(days)),
            "halfwidth_mw": halfwidths.ravel(),
            "n_calibration": counts.ravel(),
        }
    )


def block_bootstrap(
    daily: np.ndarray,
    statistic,
    block_days: int = 7,
    n_resamples: int = 2000,
    seed: int = 42,
    level: float = 0.95,
) -> dict:
    """A statistic of a daily table (rows = consecutive days) with a circular block
    bootstrap percentile interval.

    Days are resampled in blocks of consecutive days to respect serial dependence; hours
    within a day are never treated as independent draws.
    """
    values = np.asarray(daily, dtype=float)
    if len(values) == 0 or not np.isfinite(values).all():
        raise ValueError("expected a non-empty table of finite daily values")
    n = len(values)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(n_resamples, math.ceil(n / block_days)))
    index = ((starts[:, :, None] + np.arange(block_days)) % n).reshape(n_resamples, -1)[:, :n]
    replicates = np.array([statistic(values[rows]) for rows in index])
    low, high = np.quantile(replicates, [(1 - level) / 2, 1 - (1 - level) / 2])
    return {
        "estimate": float(statistic(values)),
        "ci_low": float(low),
        "ci_high": float(high),
        "level": level,
        "n_days": n,
        "block_days": block_days,
        "n_resamples": n_resamples,
        "seed": seed,
    }


def block_bootstrap_mean(daily_values: np.ndarray, **settings) -> dict:
    """Mean of a 1-D daily series with a circular block bootstrap interval."""
    values = np.asarray(daily_values, dtype=float)
    if values.ndim != 1:
        raise ValueError("expected a 1-D daily series")
    return block_bootstrap(values, np.mean, **settings)
