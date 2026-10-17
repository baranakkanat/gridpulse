import numpy as np
import pandas as pd
import pytest
from conftest import hourly_index, hours_since_epoch

from gridpulse.features import FEATURES, TARGET, availability_counts, feature_table

HOUR = pd.Timedelta(hours=1)


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


@pytest.fixture
def load() -> pd.Series:
    """Hourly series, 2017-12-01 to 2019-01-31, whose value encodes its own timestamp."""
    index = hourly_index("2017-12-01", periods=(utc("2019-02-01") - utc("2017-12-01")) // HOUR)
    return pd.Series(hours_since_epoch(index), index=index)


def source_of(value: float) -> pd.Timestamp:
    return utc("1970-01-01") + value * HOUR


def one_day(load: pd.Series, origin: str) -> pd.DataFrame:
    return feature_table(load, pd.DatetimeIndex([utc(origin)]))


# --- Historical load ----------------------------------------------------------------


def test_lags_come_from_24_and_168_hours_before_each_target(load):
    rows = one_day(load, "2018-06-15")

    assert (rows["forecast_origin_utc"] == utc("2018-06-15")).all()
    assert rows["lead_hours"].tolist() == list(range(1, 25))
    assert rows["target_timestamp_utc"].tolist() == (
        pd.date_range("2018-06-15", periods=24, freq="h", tz="UTC").tolist()
    )
    assert (rows["target_timestamp_utc"] - rows["lag_24h_source_utc"] == 24 * HOUR).all()
    assert (rows["target_timestamp_utc"] - rows["lag_168h_source_utc"] == 168 * HOUR).all()
    # Each value is the observation at its recorded source timestamp.
    assert (rows["lag_24h_mw"].map(source_of) == rows["lag_24h_source_utc"]).all()
    assert (rows["lag_168h_mw"].map(source_of) == rows["lag_168h_source_utc"]).all()
    assert (rows[TARGET].map(source_of) == rows["target_timestamp_utc"]).all()


def test_every_lag_source_precedes_its_origin(load):
    rows = feature_table(load, pd.date_range("2018-01-01", "2018-12-31", freq="D", tz="UTC"))
    for source in ("lag_24h_source_utc", "lag_168h_source_utc"):
        assert (rows[source] < rows["forecast_origin_utc"]).all()
    # The latest source used by any row is the hour just before the origin.
    assert (rows["forecast_origin_utc"] - rows["lag_24h_source_utc"]).min() == HOUR


def test_features_do_not_change_when_observations_from_origin_onward_change(load):
    """Regression guard against leakage from the forecast horizon or later."""
    for origin in pd.date_range("2018-12-24", "2019-01-07", freq="D", tz="UTC"):
        origins = pd.DatetimeIndex([origin])
        honest = feature_table(load, origins).drop(columns=TARGET)

        corrupted = load.copy()
        corrupted[corrupted.index >= origin] = -1e9
        pd.testing.assert_frame_equal(
            honest, feature_table(corrupted, origins).drop(columns=TARGET)
        )


def test_missing_hour_gives_missing_lag_not_a_shifted_one(load):
    origin = utc("2018-06-15")
    gapped = load.drop(origin - 12 * HOUR)  # source of lead 13's 24-hour lag
    rows = feature_table(gapped, pd.DatetimeIndex([origin]))

    expected = gapped.reindex(pd.DatetimeIndex(rows["lag_24h_source_utc"])).to_numpy()
    np.testing.assert_array_equal(rows["lag_24h_mw"], expected)
    assert rows.loc[rows["lag_24h_mw"].isna(), "lead_hours"].tolist() == [13]
    assert rows["lag_168h_mw"].notna().all()


def test_unavailable_sources_and_targets_are_counted_not_filled(load):
    load = load.copy()
    origin = utc("2018-06-15")
    load[origin - 24 * HOUR] = np.nan  # 24-hour lag of lead 1
    load[origin + 2 * HOUR - 168 * HOUR] = np.nan  # 168-hour lag of lead 3
    load[origin + 5 * HOUR] = np.nan  # target of lead 6
    rows = feature_table(load, pd.DatetimeIndex([origin]))

    assert availability_counts(rows) == {
        "n_rows": 24,
        "n_usable": 21,
        "n_excluded": 3,
        "excluded_because": {
            "lag_24h_unavailable": 1,
            "lag_168h_unavailable": 1,
            "target_unavailable": 1,
        },
    }


def test_first_week_of_data_has_no_weekly_lag(load):
    rows = feature_table(load, pd.date_range("2017-12-01", periods=10, freq="D", tz="UTC"))
    counts = availability_counts(rows)

    assert counts["excluded_because"]["lag_168h_unavailable"] == 7 * 24
    assert counts["excluded_because"]["lag_24h_unavailable"] == 24
    assert counts["n_usable"] == 3 * 24


# --- Calendar features ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "hour", "weekday", "month"),
    [
        ("2018-01-15 23:00", 0, 1, 1),  # CET: Tuesday 16 January 00:00 local
        ("2018-07-01 22:00", 0, 0, 7),  # CEST: Monday 2 July 00:00 local
        ("2018-07-01 21:00", 23, 6, 7),  # CEST: Sunday 1 July 23:00 local
        ("2018-12-31 23:00", 0, 1, 1),  # New Year: Tuesday 1 January 2019 local
        ("2018-12-31 22:00", 23, 0, 12),  # Monday 31 December 23:00 local
    ],
)
def test_calendar_features_use_german_local_time(load, target, hour, weekday, month):
    target = utc(target)
    rows = one_day(load, target.normalize().strftime("%Y-%m-%d"))
    row = rows[rows["target_timestamp_utc"] == target].iloc[0]

    assert (row["target_local_hour"], row["target_local_weekday"]) == (hour, weekday)
    assert row["target_local_month"] == month


def test_local_hours_skip_and_repeat_at_dst_transitions_while_utc_targets_stay_unique(load):
    spring = one_day(load, "2018-03-25")  # 02:00 local does not exist
    autumn = one_day(load, "2018-10-28")  # 02:00 local occurs twice

    assert spring["target_local_hour"].tolist()[:3] == [1, 3, 4]
    assert 2 not in spring["target_local_hour"].tolist()
    assert autumn["target_local_hour"].tolist()[:3] == [2, 2, 3]
    for rows in (spring, autumn):
        assert rows["target_timestamp_utc"].is_unique
        assert len(rows) == 24


def test_feature_columns_are_the_documented_model_inputs(load):
    rows = one_day(load, "2018-06-15")

    assert FEATURES == (
        "lag_24h_mw",
        "lag_168h_mw",
        "target_local_hour",
        "target_local_weekday",
        "target_local_month",
    )
    assert TARGET not in FEATURES
    assert set(FEATURES) <= set(rows.columns)
