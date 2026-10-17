import numpy as np
import pandas as pd
import pytest
from conftest import hourly_index, hours_since_epoch

from gridpulse.baseline import (
    DAILY_SEASON,
    WEEKLY_SEASON,
    daily_origins,
    seasonal_naive_forecast,
)
from gridpulse.data import SPLITS

HOUR = pd.Timedelta(hours=1)


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


@pytest.fixture
def load() -> pd.Series:
    """Hourly series from 2017-12-01 to 2019-12-31 whose value encodes its own timestamp."""
    index = hourly_index("2017-12-01", periods=(utc("2020-01-01") - utc("2017-12-01")) // HOUR)
    return pd.Series(hours_since_epoch(index), index=index)


def source_timestamp(value: float) -> pd.Timestamp:
    return utc("1970-01-01") + value * HOUR


# --- Forecast origins ----------------------------------------------------------------


@pytest.mark.parametrize("split", ["validation", "test"])
def test_one_midnight_origin_per_day_of_split(split):
    start, end = SPLITS[split]
    origins = daily_origins(start, end)

    assert len(origins) == 365
    assert origins[0] == start
    assert origins[-1] == end - pd.Timedelta(days=1)
    assert (origins == origins.normalize()).all()
    assert str(origins.tz) == "UTC"


def test_targets_stay_inside_their_split_and_splits_do_not_overlap(load):
    targets = {}
    for split in ("validation", "test"):
        start, end = SPLITS[split]
        forecasts = seasonal_naive_forecast(load, daily_origins(start, end))
        targets[split] = pd.DatetimeIndex(forecasts["target_timestamp_utc"])
        assert targets[split].min() == start
        assert targets[split].max() == end - HOUR
        assert targets[split].is_unique
        assert len(targets[split]) == (end - start) // HOUR

    assert targets["validation"].intersection(targets["test"]).empty


def test_non_midnight_origin_is_rejected(load):
    with pytest.raises(ValueError, match="00:00 UTC"):
        seasonal_naive_forecast(load, pd.DatetimeIndex([utc("2018-03-01 06:00")]))


@pytest.mark.parametrize("tz", [None, "Europe/Berlin"])
def test_non_utc_load_index_is_rejected(load, tz):
    index = load.index.tz_localize(None) if tz is None else load.index.tz_convert(tz)
    with pytest.raises(ValueError, match="UTC"):
        seasonal_naive_forecast(load.set_axis(index), daily_origins(*SPLITS["validation"]))


# --- Seasonal naive construction -----------------------------------------------------


def test_24_leads_with_weekly_reference_alignment(load):
    origin = utc("2018-03-14")
    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin]))

    assert len(forecast) == 24
    assert (forecast["forecast_origin_utc"] == origin).all()
    assert forecast["lead_hours"].tolist() == list(range(1, 25))
    expected_targets = pd.date_range(origin, periods=24, freq="h")
    assert forecast["target_timestamp_utc"].tolist() == expected_targets.tolist()
    lag = forecast["target_timestamp_utc"] - forecast["reference_timestamp_utc"]
    assert (lag == pd.Timedelta(hours=168)).all()
    # The predicted value is exactly the observation at the reference timestamp.
    produced_by = forecast["predicted_load_mw"].map(source_timestamp)
    assert (produced_by == forecast["reference_timestamp_utc"]).all()


def test_monday_target_uses_previous_monday_same_hour(load):
    origin = utc("2018-01-08")  # a Monday
    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin])).set_index("lead_hours")

    row = forecast.loc[15]  # lead 15 -> interval starting 14:00 UTC
    assert row["target_timestamp_utc"] == utc("2018-01-08 14:00")
    assert row["reference_timestamp_utc"] == utc("2018-01-01 14:00")
    assert row["reference_timestamp_utc"].day_name() == "Monday"
    assert row["predicted_load_mw"] == load[utc("2018-01-01 14:00")]


@pytest.mark.parametrize("season", [WEEKLY_SEASON, DAILY_SEASON])
def test_references_are_found_by_timestamp_not_row_position(load, season):
    """With an hour absent from the index, a positional row shift would be off by one hour.

    Weekly: the gap lies between the reference window and the origin. Daily: it removes
    the reference of lead 13, which must become a missing prediction, not a shifted one.
    """
    origin = utc("2018-06-15")
    gapped = load.drop(origin - season / 2)
    forecast = seasonal_naive_forecast(gapped, pd.DatetimeIndex([origin]), season)

    expected = gapped.reindex(pd.DatetimeIndex(forecast["reference_timestamp_utc"]))
    np.testing.assert_array_equal(forecast["predicted_load_mw"], expected)
    assert forecast["predicted_load_mw"].isna().sum() == (1 if season == DAILY_SEASON else 0)


def test_daily_naive_uses_previous_day_same_utc_hour(load):
    origin = utc("2018-03-14")
    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin]), DAILY_SEASON)

    assert (forecast["forecast_origin_utc"] == origin).all()
    assert forecast["lead_hours"].tolist() == list(range(1, 25))
    assert forecast["target_timestamp_utc"].tolist() == (
        pd.date_range(origin, periods=24, freq="h").tolist()
    )
    # References are the 24 hours O-24h, ..., O-1h: the previous UTC day.
    assert forecast["reference_timestamp_utc"].tolist() == (
        pd.date_range(origin - pd.Timedelta(hours=24), periods=24, freq="h").tolist()
    )
    produced_by = forecast["predicted_load_mw"].map(source_timestamp)
    assert (produced_by == forecast["reference_timestamp_utc"]).all()


def test_daily_naive_missing_reference_gives_missing_prediction(load):
    origin = utc("2018-06-15")
    load = load.copy()
    load[origin - pd.Timedelta(hours=24) + 4 * HOUR] = np.nan  # reference of lead 5
    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin]), DAILY_SEASON)

    assert forecast.loc[forecast["predicted_load_mw"].isna(), "lead_hours"].tolist() == [5]


def test_default_season_is_weekly(load):
    origins = daily_origins(*SPLITS["validation"])
    pd.testing.assert_frame_equal(
        seasonal_naive_forecast(load, origins),
        seasonal_naive_forecast(load, origins, WEEKLY_SEASON),
    )


@pytest.mark.parametrize(
    ("season", "message"),
    [
        (pd.Timedelta(hours=23), "at or after the forecast origin"),
        (pd.Timedelta(hours=12), "at or after the forecast origin"),
        (pd.Timedelta(minutes=90), "whole number of hours"),
        (pd.Timedelta(0), "whole number of hours"),
    ],
)
def test_season_lengths_that_would_leak_or_misalign_are_rejected(load, season, message):
    with pytest.raises(ValueError, match=message):
        seasonal_naive_forecast(load, pd.DatetimeIndex([utc("2018-06-15")]), season)


def test_duplicate_origins_are_rejected(load):
    origin = utc("2018-06-15")
    with pytest.raises(ValueError, match="unique"):
        seasonal_naive_forecast(load, pd.DatetimeIndex([origin, origin]))


def test_unavailable_reference_gives_missing_prediction_not_a_fill(load):
    origin = utc("2018-06-15")
    load = load.copy()
    load[origin - pd.Timedelta(hours=168) + 4 * HOUR] = np.nan  # reference of lead 5
    load[origin - pd.Timedelta(hours=168) + 9 * HOUR] = np.inf  # reference of lead 10

    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin]))

    missing_leads = forecast.loc[forecast["predicted_load_mw"].isna(), "lead_hours"].tolist()
    assert missing_leads == [5, 10]


def test_reference_before_series_start_gives_missing_prediction(load):
    origin = load.index[0].normalize() + pd.Timedelta(days=3)
    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin]))
    assert forecast["predicted_load_mw"].isna().all()


def test_first_origin_of_a_split_may_use_history_from_previous_split(load):
    origin = SPLITS["test"][0]
    forecast = seasonal_naive_forecast(load, pd.DatetimeIndex([origin]))

    assert forecast["predicted_load_mw"].notna().all()
    references = pd.DatetimeIndex(forecast["reference_timestamp_utc"])
    assert references.min() == utc("2018-12-25 00:00")
    assert references.max() == utc("2018-12-25 23:00")


# --- Leakage -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("season", "closest_reference"),
    [(WEEKLY_SEASON, pd.Timedelta(hours=145)), (DAILY_SEASON, pd.Timedelta(hours=1))],
)
def test_every_reference_is_strictly_before_its_origin(load, season, closest_reference):
    forecast = seasonal_naive_forecast(load, daily_origins(*SPLITS["validation"]), season)
    assert (forecast["reference_timestamp_utc"] < forecast["forecast_origin_utc"]).all()
    latest = (forecast["forecast_origin_utc"] - forecast["reference_timestamp_utc"]).min()
    assert latest == closest_reference  # lead 24: season length minus 23 h


@pytest.mark.parametrize("season", [WEEKLY_SEASON, DAILY_SEASON])
def test_forecast_does_not_change_when_observations_from_origin_onward_are_corrupted(load, season):
    """Regression guard: any use of information at or after the origin changes the output."""
    for origin in pd.date_range("2018-12-24", "2019-01-07", freq="D", tz="UTC"):
        origins = pd.DatetimeIndex([origin])
        honest = seasonal_naive_forecast(load, origins, season)

        corrupted = load.copy()
        corrupted[corrupted.index >= origin] = -1e9
        pd.testing.assert_frame_equal(honest, seasonal_naive_forecast(corrupted, origins, season))
