import json

import numpy as np
import pandas as pd
import pytest

from gridpulse.__main__ import main

INDEX = pd.date_range("2017-12-01", "2020-01-31 23:00", freq="h", tz="UTC")
TIMESTAMPS = INDEX.strftime("%Y-%m-%dT%H:%M:%SZ").tolist()
# Rising 10 MW every hour: the weekly seasonal naive error is exactly 168 * 10 = 1680 MW.
TREND_VALUES = [f"{50000 + 10 * i}" for i in range(len(INDEX))]


def run_baseline(csv, output_dir, command="baseline") -> int:
    return main([command, "--input", str(csv), "--output-dir", str(output_dir)])


EXPERIMENT_OUTPUTS = {
    "baseline": ("validation_predictions.csv", "test_predictions.csv", "metrics.json"),
    "compare": ("comparison_predictions.csv", "calendar_analysis.csv", "comparison_metrics.json"),
}


@pytest.fixture
def trend_csv(write_opsd_csv):
    return write_opsd_csv(TIMESTAMPS, TREND_VALUES)


def test_validate_command_succeeds_on_clean_data(trend_csv, capsys):
    assert main(["validate", "--input", str(trend_csv)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["time_index_problems"] == []
    assert report["file"]["sha256_matches_official"] is False
    assert report["coverage_by_period"]["reserved"]["available"] == 31 * 24


def test_baseline_command_writes_auditable_outputs(trend_csv, tmp_path):
    output_dir = tmp_path / "out"
    assert run_baseline(trend_csv, output_dir) == 0

    metrics = json.loads((output_dir / "metrics.json").read_text())
    for split in ("validation", "test"):
        overall = metrics[split]["overall"]
        assert metrics[split]["n_valid_pairs"] == 365 * 24
        assert overall["mae_mw"] == pytest.approx(1680.0)
        assert overall["rmse_mw"] == pytest.approx(1680.0)

    test_rows = pd.read_csv(output_dir / "test_predictions.csv")
    assert list(test_rows.columns) == [
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_hours",
        "reference_timestamp_utc",
        "predicted_load_mw",
        "actual_load_mw",
        "status",
    ]
    assert test_rows["target_timestamp_utc"].iloc[0] == "2019-01-01T00:00:00Z"
    assert test_rows["target_timestamp_utc"].iloc[-1] == "2019-12-31T23:00:00Z"
    assert test_rows["reference_timestamp_utc"].iloc[0] == "2018-12-25T00:00:00Z"

    metadata = json.loads((output_dir / "run_metadata.json").read_text())
    assert metadata["baseline"]["season_length_hours"] == 168
    assert metadata["n_valid_pairs"] == {"validation": 8760, "test": 8760}
    quality = json.loads((output_dir / "data_quality.json").read_text())
    assert quality["last_timestamp_utc"] == "2019-12-31T23:00:00Z"
    assert "reserved" not in quality["coverage_by_period"]


@pytest.mark.parametrize("command", ["baseline", "compare"])
def test_reserved_period_cannot_influence_the_experiment(
    write_opsd_csv, trend_csv, tmp_path, command
):
    in_2020 = INDEX >= pd.Timestamp("2020-01-01", tz="UTC")
    corrupted_values = [
        "-1e9" if reserved else v for v, reserved in zip(TREND_VALUES, in_2020, strict=True)
    ]
    duplicated_2020_row = (TIMESTAMPS[-1], "123")
    corrupted_csv = write_opsd_csv(
        [*TIMESTAMPS, duplicated_2020_row[0]],
        [*corrupted_values, duplicated_2020_row[1]],
        name="corrupted_2020.csv",
    )

    assert run_baseline(trend_csv, tmp_path / "clean", command) == 0
    assert run_baseline(corrupted_csv, tmp_path / "corrupted", command) == 0
    for name in (*EXPERIMENT_OUTPUTS[command], "data_quality.json"):
        clean = (tmp_path / "clean" / name).read_text()
        corrupted = (tmp_path / "corrupted" / name).read_text()
        if name == "data_quality.json":  # identical apart from the file checksum
            clean, corrupted = (json.loads(c) for c in (clean, corrupted))
            del clean["file"], corrupted["file"]
        assert clean == corrupted, name


def test_blocking_time_index_problem_fails_all_commands(write_opsd_csv, tmp_path, capsys):
    csv = write_opsd_csv([*TIMESTAMPS[:100], TIMESTAMPS[99]], [*TREND_VALUES[:100], "1"])

    assert main(["validate", "--input", str(csv)]) == 1
    assert run_baseline(csv, tmp_path / "out") == 1
    assert run_baseline(csv, tmp_path / "out", "compare") == 1
    assert "duplicated" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_compare_command_writes_aligned_paired_outputs(trend_csv, tmp_path):
    assert run_baseline(trend_csv, tmp_path / "compare", "compare") == 0
    assert run_baseline(trend_csv, tmp_path / "baseline") == 0

    metrics = json.loads((tmp_path / "compare" / "comparison_metrics.json").read_text())
    baseline_metrics = json.loads((tmp_path / "baseline" / "metrics.json").read_text())
    for split in ("validation", "test"):
        # The comparison reuses the weekly baseline pipeline unchanged.
        assert metrics[split]["standalone"]["weekly_naive"] == baseline_metrics[split]
        comparison = metrics[split]["comparison"]
        assert comparison["n_common_valid_pairs"] == 8760
        paired = comparison["paired"]
        # Rising 10 MW per hour: daily error 240 MW, weekly error 1680 MW on every pair.
        assert paired["daily_naive"]["mae_mw"] == pytest.approx(240.0)
        assert paired["weekly_naive"]["mae_mw"] == pytest.approx(1680.0)
        assert paired["daily_naive_minus_weekly_naive_mae_mw"] == pytest.approx(-1440.0)
        assert paired["lower_absolute_error"]["counts"]["daily_naive"] == 8760

    rows = pd.read_csv(tmp_path / "compare" / "comparison_predictions.csv")
    assert len(rows) == 2 * 8760
    assert rows.columns[:4].tolist() == [
        "period",
        "forecast_origin_utc",
        "target_timestamp_utc",
        "lead_hours",
    ]
    first_test = rows[rows["period"] == "test"].iloc[0]
    assert first_test["daily_naive_reference_timestamp_utc"] == "2018-12-31T00:00:00Z"
    assert first_test["weekly_naive_reference_timestamp_utc"] == "2018-12-25T00:00:00Z"
    assert first_test["holiday_category"] == "both_holidays"
    assert rows["target_timestamp_utc"].max() == "2019-12-31T23:00:00Z"

    calendar = pd.read_csv(tmp_path / "compare" / "calendar_analysis.csv")
    assert len(calendar) == 2 * (4 + 7)
    categories = calendar[calendar["grouping"] == "holiday_category"]
    assert categories.groupby("period")["n_pairs"].sum().to_dict() == {
        "test": 8760,
        "validation": 8760,
    }
    metadata = json.loads((tmp_path / "compare" / "run_metadata.json").read_text())
    assert metadata["calendar"]["timezone"] == "Europe/Berlin"
    assert metadata["baselines"]["daily_naive"]["season_length_hours"] == 24


def test_invalid_input_is_reported_without_traceback(write_opsd_csv, tmp_path, capsys):
    csv = write_opsd_csv(TIMESTAMPS[:3], ["1", "NULL", "3"])

    assert main(["validate", "--input", str(csv)]) == 1
    assert "error:" in capsys.readouterr().err
    assert main(["validate", "--input", str(tmp_path / "missing.csv")]) == 1


# --- LightGBM experiment --------------------------------------------------------------

LONG_INDEX = pd.date_range("2014-12-31 23:00", "2020-01-31 23:00", freq="h", tz="UTC")


def long_values(index: pd.DatetimeIndex) -> list[str]:
    """Daily and weekly structure plus deterministic noise; the first value is missing."""
    hours = np.arange(len(index))
    noise = np.random.default_rng(0).normal(0, 300, len(index))
    values = 50_000 + 8_000 * np.sin(2 * np.pi * hours / 24) - 6_000 * (index.dayofweek >= 5)
    return ["", *(f"{v:.0f}" for v in (values + noise)[1:])]


@pytest.fixture(scope="module")
def lightgbm_run(tmp_path_factory):
    directory = tmp_path_factory.mktemp("lightgbm")
    csv = directory / "opsd.csv"
    pd.DataFrame(
        {
            "utc_timestamp": LONG_INDEX.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "DE_load_actual_entsoe_transparency": long_values(LONG_INDEX),
        }
    ).to_csv(csv, index=False)
    assert run_baseline(csv, directory / "lightgbm", "train-lightgbm") == 0
    assert run_baseline(csv, directory / "compare", "compare") == 0
    return directory, csv


def test_lightgbm_trains_on_2015_2017_and_stops_early_on_2018_only(lightgbm_run):
    directory, _ = lightgbm_run
    metadata = json.loads((directory / "lightgbm" / "run_metadata.json").read_text())
    training = metadata["lightgbm"]["training"]

    assert training["training_rows"]["first_target_utc"] == "2015-01-08T00:00:00Z"
    assert training["training_rows"]["last_target_utc"] == "2017-12-31T23:00:00Z"
    # The first week has no 168-hour lag (and the first day no 24-hour lag): excluded.
    assert training["training_rows"]["n_rows"] == 1096 * 24
    assert training["training_rows"]["n_excluded"] == 7 * 24
    assert training["early_stopping_rows"]["first_target_utc"] == "2018-01-01T00:00:00Z"
    assert training["early_stopping_rows"]["last_target_utc"] == "2018-12-31T23:00:00Z"
    assert training["early_stopping_rows"]["n_usable"] == 365 * 24
    assert training["features"] == [
        "lag_24h_mw",
        "lag_168h_mw",
        "target_local_hour",
        "target_local_weekday",
        "target_local_month",
    ]
    assert metadata["lightgbm"]["model_file_check"]["max_abs_difference_mw"] == 0.0


def test_lightgbm_outputs_compare_three_models_on_identical_pairs(lightgbm_run):
    directory, _ = lightgbm_run
    metrics = json.loads((directory / "lightgbm" / "metrics.json").read_text())
    compare_metrics = json.loads((directory / "compare" / "comparison_metrics.json").read_text())

    for split in ("validation", "test"):
        comparison = metrics[split]["comparison"]
        assert comparison["n_common_valid_pairs"] == 8760
        assert set(comparison["common_sample"]) == {
            "n_pairs",
            "weekly_naive",
            "daily_naive",
            "lightgbm",
        }
        # Baselines inside the LightGBM experiment are exactly those of `compare`.
        for baseline in ("weekly_naive", "daily_naive"):
            assert (
                metrics[split]["standalone"][baseline]
                == (compare_metrics[split]["standalone"][baseline])
            )

    rows = pd.read_csv(directory / "lightgbm" / "predictions.csv")
    assert not rows.duplicated(["forecast_origin_utc", "target_timestamp_utc", "lead_hours"]).any()
    by_period = rows.groupby("period")["target_timestamp_utc"].agg(["min", "max"])
    assert by_period.loc["validation"].tolist() == ["2018-01-01T00:00:00Z", "2018-12-31T23:00:00Z"]
    assert by_period.loc["test"].tolist() == ["2019-01-01T00:00:00Z", "2019-12-31T23:00:00Z"]
    assert rows["lightgbm_predicted_load_mw"].notna().all()

    calendar = pd.read_csv(directory / "lightgbm" / "calendar_analysis.csv")
    assert len(calendar) == 2 * (4 + 7)
    assert {"lightgbm_mae_mw", "lightgbm_minus_weekly_naive_mae_mw"} <= set(calendar.columns)


def test_reserved_period_cannot_influence_the_lightgbm_experiment(
    lightgbm_run, write_opsd_csv, tmp_path
):
    directory, _ = lightgbm_run
    values = long_values(LONG_INDEX)
    corrupted = [
        "-1e9" if t >= pd.Timestamp("2020-01-01", tz="UTC") else v
        for t, v in zip(LONG_INDEX, values, strict=True)
    ]
    csv = write_opsd_csv(LONG_INDEX.strftime("%Y-%m-%dT%H:%M:%SZ").tolist(), corrupted)

    assert run_baseline(csv, tmp_path / "corrupted", "train-lightgbm") == 0
    for name in ("predictions.csv", "metrics.json", "calendar_analysis.csv", "model.txt"):
        clean = (directory / "lightgbm" / name).read_text()
        assert (tmp_path / "corrupted" / name).read_text() == clean, name


def test_test_period_data_cannot_influence_the_fitted_model(lightgbm_run, write_opsd_csv, tmp_path):
    directory, _ = lightgbm_run
    in_2019 = (LONG_INDEX >= pd.Timestamp("2019-01-01", tz="UTC")) & (
        LONG_INDEX < pd.Timestamp("2020-01-01", tz="UTC")
    )
    shifted = [
        f"{float(v) + 7_000:.0f}" if test else v
        for v, test in zip(long_values(LONG_INDEX), in_2019, strict=True)
    ]
    csv = write_opsd_csv(LONG_INDEX.strftime("%Y-%m-%dT%H:%M:%SZ").tolist(), shifted)

    assert run_baseline(csv, tmp_path / "shifted", "train-lightgbm") == 0
    clean = directory / "lightgbm"
    assert (tmp_path / "shifted" / "model.txt").read_text() == (clean / "model.txt").read_text()
    metrics = {
        d: json.loads((d / "metrics.json").read_text()) for d in (clean, tmp_path / "shifted")
    }
    assert metrics[clean]["validation"] == metrics[tmp_path / "shifted"]["validation"]
    assert metrics[clean]["test"] != metrics[tmp_path / "shifted"]["test"]


def test_forecast_study_follows_the_registered_rules(lightgbm_run, tmp_path):
    _, csv = lightgbm_run
    assert run_baseline(csv, tmp_path / "study", "forecast-study") == 0
    read = lambda name: json.loads((tmp_path / "study" / name).read_text())  # noqa: E731
    c1, c2, c3 = (
        read("c1_boosting_cap.json"),
        read("c2_holiday_ablation.json"),
        read("c3_intervals.json"),
    )

    gain = c1["relative_2018_mae_gain_of_higher_cap"]
    assert c1["chosen_cap"] == (3000 if gain >= 0.01 else 500)
    assert c1["arms"]["500"]["training"]["num_boost_round"] == 500
    mae = {
        arm: c2["periods"]["validation"]["comparison"]["common_sample"][arm]["mae_mw"]
        for arm in ("lightgbm_a", "lightgbm_b")
    }
    assert c2["selected_for_c3"] == min(mae, key=mae.get)
    assert c2["training"]["lightgbm_b"]["features"][-3:] == [
        "target_is_holiday",
        "lag_24h_source_is_holiday",
        "lag_168h_source_is_holiday",
    ]
    # 2018 is evaluated from 26 February (first full 56-day window), 2019 entirely.
    assert c3["periods"]["validation"]["n_evaluable"] == 309 * 24
    assert c3["periods"]["test"]["n_evaluable"] == 365 * 24
    intervals = pd.read_csv(tmp_path / "study" / "c3_intervals.csv")
    assert intervals["forecast_origin_utc"].min() == "2018-02-26T00:00:00Z"
    assert (intervals["n_calibration"] == 56).all()
