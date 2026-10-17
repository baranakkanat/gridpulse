import numpy as np
import pandas as pd
import pytest

from gridpulse.data import (
    RESERVED_FROM,
    SPLITS,
    TARGET_COLUMN,
    TIMESTAMP_COLUMN,
    hourly_load,
    quality_report,
    read_source,
)


def utc(text: str) -> pd.Timestamp:
    return pd.Timestamp(text, tz="UTC")


# --- Reading and schema --------------------------------------------------------------


def test_reads_target_with_utc_timestamps_and_ignores_other_columns(write_opsd_csv):
    path = write_opsd_csv(["2014-12-31T23:00:00Z", "2015-01-01T00:00:00Z"], ["41000.5", "40000"])
    source = read_source(path)

    assert str(source.index.tz) == "UTC"
    # 23:00 UTC is midnight in Germany; it must not be reinterpreted as local time.
    assert source.index[0] == utc("2014-12-31 23:00")
    assert source.tolist() == [41000.5, 40000.0]
    assert source.dtype == np.float64


@pytest.mark.parametrize("dropped", [TIMESTAMP_COLUMN, TARGET_COLUMN])
def test_missing_required_column_raises(tmp_path, dropped):
    path = tmp_path / "bad.csv"
    frame = pd.DataFrame({TIMESTAMP_COLUMN: ["2015-01-01T00:00:00Z"], TARGET_COLUMN: [1.0]})
    frame.drop(columns=dropped).to_csv(path, index=False)

    with pytest.raises(ValueError, match=dropped):
        read_source(path)


@pytest.mark.parametrize("timestamp", ["2015-01-01T00:00:00", "2015-01-01T01:00:00+01:00"])
def test_timestamps_must_be_explicit_utc(write_opsd_csv, timestamp):
    with pytest.raises(ValueError, match="UTC"):
        read_source(write_opsd_csv([timestamp], ["1.0"]))


@pytest.mark.parametrize("text", ["n/a MW", "NULL", "NA", "#N/A", "nan"])
def test_non_numeric_target_text_raises_instead_of_becoming_missing(write_opsd_csv, text):
    path = write_opsd_csv(["2015-01-01T00:00:00Z", "2015-01-01T01:00:00Z"], ["1.0", text])
    with pytest.raises(ValueError, match="not numeric"):
        read_source(path)


# --- Time index validation -----------------------------------------------------------


def test_duplicate_timestamps_are_reported_and_block_preparation(write_opsd_csv):
    path = write_opsd_csv(
        ["2015-01-01T00:00:00Z", "2015-01-01T01:00:00Z", "2015-01-01T01:00:00Z"],
        ["1", "2", "3"],
    )
    source = read_source(path)

    report = quality_report(source)
    assert report["time_index_problems"] == ["1 duplicated timestamp(s), e.g. 2015-01-01T01:00:00Z"]
    # Coverage counts are not well defined for such an index, so they are not reported.
    assert "coverage_by_period" not in report
    assert report["target"]["available"] == 3
    with pytest.raises(ValueError, match="duplicated"):
        hourly_load(source)


def test_unsorted_timestamps_are_reported_and_block_preparation(write_opsd_csv):
    timestamps = ["2015-01-01T00:00:00Z", "2015-01-01T02:00:00Z", "2015-01-01T01:00:00Z"]
    source = read_source(write_opsd_csv(timestamps, ["1", "3", "2"]))

    assert quality_report(source)["time_index_problems"] == [
        "timestamps are not in increasing order"
    ]
    with pytest.raises(ValueError, match="increasing order"):
        hourly_load(source)


def test_off_hour_timestamp_blocks_preparation(write_opsd_csv):
    source = read_source(
        write_opsd_csv(["2015-01-01T00:00:00Z", "2015-01-01T00:30:00Z"], ["1", "2"])
    )
    with pytest.raises(ValueError, match="start of an hour"):
        hourly_load(source)


def test_gap_is_reported_and_absent_hours_become_unavailable(write_opsd_csv):
    timestamps = ["2015-01-01T00:00:00Z", "2015-01-01T01:00:00Z", "2015-01-01T05:00:00Z"]
    source = read_source(write_opsd_csv(timestamps, ["10", "11", "15"]))

    report = quality_report(source)
    assert report["gaps"] == [
        {
            "last_before_utc": "2015-01-01T01:00:00Z",
            "first_after_utc": "2015-01-01T05:00:00Z",
            "missing_hours": 3,
        }
    ]
    assert report["interval_hours_counts"] == {"1": 1, "4": 1}
    assert report["timestamps_absent_from_source"] == 3
    # Absent timestamps are not source rows with missing values.
    assert report["target"]["missing_in_source_rows"] == 0

    load = hourly_load(source)
    assert load.index.equals(pd.date_range("2015-01-01", periods=6, freq="h", tz="UTC"))
    assert load.isna().tolist() == [False, False, True, True, True, False]
    assert load.iloc[-1] == 15.0


def test_missing_and_invalid_values_are_counted_not_modified(write_opsd_csv):
    timestamps = [f"2015-01-01T0{h}:00:00Z" for h in range(5)]
    source = read_source(write_opsd_csv(timestamps, ["50000", "", "inf", "-20", "0"]))

    target = quality_report(source)["target"]
    assert target["available"] == 3
    assert target["missing_in_source_rows"] == 1
    assert target["infinite_in_source_rows"] == 1
    assert target["negative"] == 1
    assert target["zero"] == 1

    load = hourly_load(source)
    # Missing stays missing (never zero), infinite becomes unavailable,
    # and suspicious values are kept as observed.
    assert np.isnan(load.iloc[1]) and np.isnan(load.iloc[2])
    assert load.iloc[3] == -20.0
    assert load.iloc[4] == 0.0


def test_coverage_is_split_by_utc_year(write_opsd_csv):
    index = pd.date_range("2015-12-31 22:00", periods=4, freq="h", tz="UTC")
    timestamps = index.strftime("%Y-%m-%dT%H:%M:%SZ").tolist()
    source = read_source(write_opsd_csv(timestamps, ["1", "", "3", "4"]))

    coverage = quality_report(source)["coverage_by_year"]
    assert coverage["2015"] == {
        "hours_in_grid": 2,
        "source_rows": 2,
        "available": 1,
        "unavailable_in_source_rows": 1,
        "timestamps_absent_from_source": 0,
    }
    assert coverage["2016"]["available"] == 2


# --- Chronological splits ------------------------------------------------------------


def test_splits_are_chronological_contiguous_and_end_before_reserved_period():
    periods = [SPLITS["train"], SPLITS["validation"], SPLITS["test"]]
    assert periods[0][0] == utc("2015-01-01")
    for (_, end), (next_start, _) in zip(periods, periods[1:], strict=False):
        assert end == next_start  # half-open intervals: contiguous and non-overlapping
    for start, end in periods:
        assert start < end
    assert SPLITS["validation"] == (utc("2018-01-01"), utc("2019-01-01"))
    assert SPLITS["test"] == (utc("2019-01-01"), utc("2020-01-01"))
    assert periods[-1][1] == RESERVED_FROM == utc("2020-01-01")
