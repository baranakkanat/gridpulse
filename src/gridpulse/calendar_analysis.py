"""Retrospective calendar diagnostics of forecast errors in German local time.

Holiday labels are used only to group already-made forecasts for error analysis. They
never influence a forecast.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from gridpulse.baseline import DAILY_NAIVE, WEEKLY_NAIVE
from gridpulse.evaluation import COMMON_VALID, common_sample_scores, mae_difference_key

LOCAL_TIMEZONE = "Europe/Berlin"
HOLIDAY_SOURCE = (
    "timeanddate.com, 'Holidays and Observances in Germany' for 2017-2020, rows of type "
    "'National Holiday' (checked 2026-10-17); Easter-dependent dates cross-checked with the "
    "Gregorian computus in the test suite"
)
# Nationwide statutory public holidays on the local dates that evaluated targets and their
# daily or weekly references can fall on. Regional holidays (e.g. Epiphany, Corpus
# Christi, Reformation Day from 2018), Christmas Eve and New Year's Eve are not included.
NATIONAL_HOLIDAYS = {
    pd.Timestamp("2017-12-25"): "Christmas Day",
    pd.Timestamp("2017-12-26"): "Second Day of Christmas",
    pd.Timestamp("2018-01-01"): "New Year's Day",
    pd.Timestamp("2018-03-30"): "Good Friday",
    pd.Timestamp("2018-04-02"): "Easter Monday",
    pd.Timestamp("2018-05-01"): "Labour Day",
    pd.Timestamp("2018-05-10"): "Ascension Day",
    pd.Timestamp("2018-05-21"): "Whit Monday",
    pd.Timestamp("2018-10-03"): "Day of German Unity",
    pd.Timestamp("2018-12-25"): "Christmas Day",
    pd.Timestamp("2018-12-26"): "Second Day of Christmas",
    pd.Timestamp("2019-01-01"): "New Year's Day",
    pd.Timestamp("2019-04-19"): "Good Friday",
    pd.Timestamp("2019-04-22"): "Easter Monday",
    pd.Timestamp("2019-05-01"): "Labour Day",
    pd.Timestamp("2019-05-30"): "Ascension Day",
    pd.Timestamp("2019-06-10"): "Whit Monday",
    pd.Timestamp("2019-10-03"): "Day of German Unity",
    pd.Timestamp("2019-12-25"): "Christmas Day",
    pd.Timestamp("2019-12-26"): "Second Day of Christmas",
    pd.Timestamp("2020-01-01"): "New Year's Day",
}
# Local dates for which the table above is complete.
CALENDAR_COVERAGE = (pd.Timestamp("2017-12-25"), pd.Timestamp("2020-01-01"))

HOLIDAY_CATEGORIES = (
    "neither_holiday",
    "target_holiday_only",
    "weekly_reference_holiday_only",
    "both_holidays",
)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def local_times(timestamps: pd.Series) -> pd.DatetimeIndex:
    """German local time (Europe/Berlin, DST-aware) of each UTC timestamp."""
    index = pd.DatetimeIndex(timestamps)
    if str(index.tz) != "UTC":
        raise ValueError(f"timestamps must be UTC, got tz={index.tz}")
    if index.hasnans:
        raise ValueError("timestamps contain missing values")
    return index.tz_convert(LOCAL_TIMEZONE)


def local_dates(timestamps: pd.Series) -> pd.DatetimeIndex:
    """German local calendar date (naive midnight) of each UTC timestamp."""
    return local_times(timestamps).normalize().tz_localize(None)


def is_national_holiday(timestamps: pd.Series) -> np.ndarray:
    """Whether each UTC timestamp falls on a nationwide public holiday in German local time."""
    dates = local_dates(timestamps)
    first, last = CALENDAR_COVERAGE
    if dates.min() < first or dates.max() > last:
        raise ValueError(
            f"local dates {dates.min().date()}..{dates.max().date()} exceed the holiday "
            f"calendar coverage {first.date()}..{last.date()}"
        )
    return dates.isin(list(NATIONAL_HOLIDAYS))


def annotate_calendar(aligned: pd.DataFrame) -> pd.DataFrame:
    """Add German local calendar labels to an `align_pairs` table of daily and weekly naive.

    The holiday category combines the target and the weekly reference, and is shared by
    both models so they are always compared on the same subsets.
    """
    target_is_holiday = is_national_holiday(aligned["target_timestamp_utc"])
    weekly_is_holiday = is_national_holiday(aligned[f"{WEEKLY_NAIVE}_reference_timestamp_utc"])
    target_dates = local_dates(aligned["target_timestamp_utc"])
    category = np.select(
        [target_is_holiday & weekly_is_holiday, target_is_holiday, weekly_is_holiday],
        ["both_holidays", "target_holiday_only", "weekly_reference_holiday_only"],
        default="neither_holiday",
    )
    return aligned.assign(
        target_local_date=target_dates.strftime("%Y-%m-%d"),
        target_local_weekday=target_dates.day_name(),
        target_is_holiday=target_is_holiday,
        weekly_reference_is_holiday=weekly_is_holiday,
        daily_reference_is_holiday=is_national_holiday(
            aligned[f"{DAILY_NAIVE}_reference_timestamp_utc"]
        ),
        holiday_category=category,
    )


def calendar_breakdown(
    annotated: pd.DataFrame, models: Sequence[str], difference: tuple[str, str]
) -> pd.DataFrame:
    """Metrics of `models` per holiday category and per target local weekday.

    Only common-valid rows are used, so all models are scored on the same rows in every
    group. `difference` = (a, b) adds MAE(a) - MAE(b). Every category and weekday is
    listed, with empty metrics when it has no valid pairs.
    """
    common = annotated[annotated["comparison_status"] == COMMON_VALID]
    model_a, model_b = difference
    difference_key = mae_difference_key(model_a, model_b)
    rows = []
    for grouping, groups in (
        ("holiday_category", HOLIDAY_CATEGORIES),
        ("target_local_weekday", WEEKDAYS),
    ):
        for group in groups:
            subset = common[common[grouping] == group]
            scores = common_sample_scores(subset, models)
            rows.append(
                {
                    "grouping": grouping,
                    "group": group,
                    "n_pairs": len(subset),
                    "n_forecast_origins": subset["forecast_origin_utc"].nunique(),
                    "n_local_target_dates": subset["target_local_date"].nunique(),
                    **{f"{name}_mae_mw": scores[name]["mae_mw"] for name in models},
                    **{f"{name}_rmse_mw": scores[name]["rmse_mw"] for name in models},
                    difference_key: scores[model_a]["mae_mw"] - scores[model_b]["mae_mw"]
                    if len(subset)
                    else None,
                }
            )
    return pd.DataFrame(rows)
