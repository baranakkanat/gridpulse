from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from gridpulse.calendar_analysis import (
    CALENDAR_COVERAGE,
    NATIONAL_HOLIDAYS,
    annotate_calendar,
    calendar_breakdown,
    is_national_holiday,
    local_dates,
)

MODELS = ("daily_naive", "weekly_naive")


def utc(*texts: str) -> pd.Series:
    return pd.Series(pd.DatetimeIndex(texts, tz="UTC"))


def easter_sunday(year: int) -> date:
    """Anonymous Gregorian computus (Meeus/Jones/Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


def test_holiday_table_matches_an_independent_derivation():
    """Fixed-date holidays plus Easter-dependent ones, restricted to the covered dates."""
    expected = set()
    for year in (2017, 2018, 2019, 2020):
        easter = easter_sunday(year)
        expected |= {date(year, 1, 1), date(year, 5, 1), date(year, 10, 3)}
        expected |= {date(year, 12, 25), date(year, 12, 26)}
        expected |= {easter + timedelta(days=offset) for offset in (-2, 1, 39, 50)}
    first, last = (d.date() for d in CALENDAR_COVERAGE)
    expected = {d for d in expected if first <= d <= last}

    assert {d.date() for d in NATIONAL_HOLIDAYS} == expected
    assert easter_sunday(2018) == date(2018, 4, 1)
    assert easter_sunday(2019) == date(2019, 4, 21)


# --- UTC to German local dates -------------------------------------------------------


def test_winter_holiday_starts_at_23_utc_on_the_previous_utc_day():
    # CET is UTC+1: Christmas Day 2018 in Germany is 2018-12-24T23:00Z to 2018-12-25T22:59Z.
    flags = is_national_holiday(
        utc("2018-12-24 22:00", "2018-12-24 23:00", "2018-12-25 22:00", "2018-12-26 23:00")
    )
    assert flags.tolist() == [False, True, True, False]


def test_summer_holiday_uses_cest_offset():
    # CEST is UTC+2: Whit Monday 2018 is 2018-05-20T22:00Z to 2018-05-21T21:59Z.
    flags = is_national_holiday(
        utc("2018-05-20 21:00", "2018-05-20 22:00", "2018-05-21 21:00", "2018-05-21 22:00")
    )
    assert flags.tolist() == [False, True, True, False]


def test_last_utc_hour_of_2019_is_new_years_day_2020_in_germany():
    timestamps = utc("2019-12-31 22:00", "2019-12-31 23:00")
    assert local_dates(timestamps).strftime("%Y-%m-%d").tolist() == ["2019-12-31", "2020-01-01"]
    assert is_national_holiday(timestamps).tolist() == [False, True]


def test_local_calendar_days_have_23_and_25_hours_at_dst_transitions():
    hours = pd.Series(pd.date_range("2018-03-24", "2018-10-30", freq="h", tz="UTC"))
    hours_per_local_date = pd.Series(local_dates(hours)).value_counts()

    assert hours_per_local_date[pd.Timestamp("2018-03-25")] == 23
    assert hours_per_local_date[pd.Timestamp("2018-10-28")] == 25
    assert hours_per_local_date[pd.Timestamp("2018-10-03")] == 24
    holiday_hours = hours[is_national_holiday(hours)]
    # Day of German Unity (CEST): 24 hours from 2018-10-02T22:00Z.
    unity = holiday_hours[holiday_hours.dt.month == 10]
    assert unity.min() == pd.Timestamp("2018-10-02 22:00", tz="UTC")
    assert len(unity) == 24


@pytest.mark.parametrize(
    "local_day",
    [
        "2018-01-06",  # Epiphany: BW, BY, ST only
        "2018-05-31",  # Corpus Christi: some states only
        "2018-10-31",  # Reformation Day: some states only (nationwide only in 2017)
        "2018-11-01",  # All Saints' Day: some states only
        "2018-12-24",  # Christmas Eve: not a statutory holiday
        "2018-12-31",  # New Year's Eve: not a statutory holiday
        "2019-03-08",  # International Women's Day: Berlin only
    ],
)
def test_regional_and_unofficial_days_are_not_national_holidays(local_day):
    noon_utc = pd.Timestamp(local_day, tz="Europe/Berlin").tz_convert("UTC") + pd.Timedelta(
        hours=12
    )
    assert not is_national_holiday(pd.Series([noon_utc])).any()


def test_forecast_origins_and_local_dates_are_counted_separately():
    # 2018-06-04T22:00Z and 2018-06-05T10:00Z: two UTC origins, one local date (5 June).
    targets = utc("2018-06-04 22:00", "2018-06-05 10:00")
    annotated = annotate_calendar(aligned_rows(targets, targets - pd.Timedelta(hours=168)))
    breakdown = calendar_breakdown(annotated, MODELS, MODELS).set_index("group")

    assert breakdown.loc["neither_holiday", "n_forecast_origins"] == 2
    assert breakdown.loc["neither_holiday", "n_local_target_dates"] == 1


def test_missing_timestamps_are_rejected_not_assumed_ordinary():
    with pytest.raises(ValueError, match="missing"):
        is_national_holiday(pd.Series(pd.DatetimeIndex(["2018-06-01 12:00", None], tz="UTC")))


def test_dates_outside_the_holiday_table_are_rejected_not_assumed_ordinary():
    with pytest.raises(ValueError, match="coverage"):
        is_national_holiday(utc("2017-12-23 12:00"))
    with pytest.raises(ValueError, match="coverage"):
        is_national_holiday(utc("2020-01-01 23:00"))  # local 2020-01-02


def test_non_utc_timestamps_are_rejected():
    with pytest.raises(ValueError, match="UTC"):
        local_dates(pd.Series(pd.DatetimeIndex(["2018-06-01 12:00"])))


# --- Categories and breakdown --------------------------------------------------------


def aligned_rows(targets: pd.Series, weekly_refs: pd.Series, statuses=None) -> pd.DataFrame:
    """Minimal `align_pairs`-like table; daily references are target - 24 h."""
    n = len(targets)
    return pd.DataFrame(
        {
            "forecast_origin_utc": targets.dt.floor("D"),
            "target_timestamp_utc": targets,
            "lead_hours": targets.dt.hour + 1,
            "actual_load_mw": 100.0,
            "daily_naive_reference_timestamp_utc": targets - pd.Timedelta(hours=24),
            "daily_naive_predicted_load_mw": 110.0,
            "weekly_naive_reference_timestamp_utc": weekly_refs,
            "weekly_naive_predicted_load_mw": 95.0,
            "comparison_status": statuses or ["common_valid"] * n,
        }
    )


def test_categories_combine_target_and_weekly_reference_exclusively():
    targets = utc("2018-06-05 10:00", "2018-05-21 10:00", "2018-05-28 10:00", "2019-01-01 10:00")
    weekly = targets - pd.Timedelta(hours=168)
    annotated = annotate_calendar(aligned_rows(targets, weekly))

    assert annotated["holiday_category"].tolist() == [
        "neither_holiday",
        "target_holiday_only",  # Whit Monday
        "weekly_reference_holiday_only",  # one week after Whit Monday
        "both_holidays",  # New Year's Day, one week after Christmas Day
    ]
    assert annotated["target_is_holiday"].tolist() == [False, True, False, True]
    assert annotated["weekly_reference_is_holiday"].tolist() == [False, False, True, True]
    assert annotated["daily_reference_is_holiday"].tolist() == [False, False, False, False]
    assert annotated["target_local_weekday"].tolist() == [
        "Tuesday",
        "Monday",
        "Monday",
        "Tuesday",
    ]


def test_weekly_reference_holiday_is_judged_in_local_time_hour_by_hour():
    # Origin 2018-04-06 (CEST): weekly references are 2018-03-30T00..23Z. Good Friday ends
    # at 2018-03-30T22:00Z (local midnight), so only the first 22 references are holidays.
    targets = pd.Series(pd.date_range("2018-04-06", periods=24, freq="h", tz="UTC"))
    annotated = annotate_calendar(aligned_rows(targets, targets - pd.Timedelta(hours=168)))

    assert annotated["holiday_category"].value_counts().to_dict() == {
        "weekly_reference_holiday_only": 22,
        "neither_holiday": 2,
    }


def test_breakdown_counts_and_empty_categories():
    targets = utc("2018-06-05 10:00", "2018-06-05 11:00", "2018-06-06 10:00", "2018-05-21 10:00")
    annotated = annotate_calendar(
        aligned_rows(
            targets,
            targets - pd.Timedelta(hours=168),
            statuses=["common_valid"] * 3 + ["weekly_naive_reference_unavailable"],
        )
    )
    breakdown = calendar_breakdown(annotated, MODELS, MODELS).set_index(["grouping", "group"])

    neither = breakdown.loc[("holiday_category", "neither_holiday")]
    assert neither["n_pairs"] == 3
    assert neither["n_forecast_origins"] == 2
    assert neither["n_local_target_dates"] == 2
    assert neither["daily_naive_mae_mw"] == pytest.approx(10.0)
    assert neither["weekly_naive_mae_mw"] == pytest.approx(5.0)
    assert neither["daily_naive_minus_weekly_naive_mae_mw"] == pytest.approx(5.0)
    # The Whit Monday row is not common-valid, so the holiday category is empty.
    for category in ("target_holiday_only", "weekly_reference_holiday_only", "both_holidays"):
        empty = breakdown.loc[("holiday_category", category)]
        assert empty["n_pairs"] == 0
        assert np.isnan(empty["daily_naive_mae_mw"])
    weekdays = breakdown.loc["target_local_weekday"]
    assert weekdays.index.tolist() == [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    assert weekdays["n_pairs"].tolist() == [0, 2, 1, 0, 0, 0, 0]
