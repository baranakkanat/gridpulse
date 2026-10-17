import math

import numpy as np
import pandas as pd
import pytest
from conftest import hourly_index

from gridpulse.baseline import DAILY_SEASON, WEEKLY_SEASON, seasonal_naive_forecast
from gridpulse.data import HOUR
from gridpulse.evaluation import (
    align_pairs,
    attach_actuals,
    compare,
    compare_with_baselines,
    mae,
    paired_scores,
    rmse,
    summarize,
    wape,
)

# --- Metrics against hand-calculated values -------------------------------------------

Y_TRUE = [100.0, 200.0, 300.0, 400.0]
Y_PRED = [110.0, 190.0, 330.0, 400.0]  # errors: -10, +10, -30, 0


def test_mae_hand_calculated():
    assert mae(Y_TRUE, Y_PRED) == pytest.approx((10 + 10 + 30 + 0) / 4)  # 12.5


def test_rmse_hand_calculated():
    assert rmse(Y_TRUE, Y_PRED) == pytest.approx(math.sqrt((100 + 100 + 900 + 0) / 4))  # 16.583


def test_wape_hand_calculated_and_differs_from_mape():
    assert wape(Y_TRUE, Y_PRED) == pytest.approx(100 * 50 / 1000)  # 5.0 %
    mape = 100 * np.mean(np.abs(np.subtract(Y_TRUE, Y_PRED)) / np.abs(Y_TRUE))
    assert wape(Y_TRUE, Y_PRED) != pytest.approx(mape)


def test_wape_zero_denominator_is_undefined():
    with pytest.raises(ValueError, match="undefined"):
        wape([0.0, 0.0], [1.0, 2.0])


@pytest.mark.parametrize("metric", [mae, rmse, wape])
def test_metrics_reject_empty_mismatched_and_non_finite_inputs(metric):
    with pytest.raises(ValueError, match="zero pairs"):
        metric([], [])
    with pytest.raises(ValueError, match="equal length"):
        metric([1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="non-finite"):
        metric([1.0, np.nan], [1.0, 2.0])


# --- Alignment and exclusion accounting ----------------------------------------------


@pytest.fixture
def load() -> pd.Series:
    """Two weeks of hourly load: 1000 MW in week one, 1100 MW in week two."""
    index = hourly_index("2018-01-01", periods=336)
    return pd.Series(np.where(np.arange(336) < 168, 1000.0, 1100.0), index=index)


def test_actuals_are_matched_by_timestamp_not_row_position(load):
    load = load.copy()
    load.iloc[168:192] = 1100.0 + np.arange(24)  # distinct values on the target day
    forecasts = seasonal_naive_forecast(load, pd.DatetimeIndex([load.index[168]]))
    shuffled = forecasts.sample(frac=1, random_state=0)

    pairs = attach_actuals(shuffled, load)

    np.testing.assert_array_equal(pairs["actual_load_mw"], 1100.0 + pairs["lead_hours"] - 1)


def test_invalid_pairs_are_classified_and_excluded_from_metrics(load):
    load = load.copy()
    origin = load.index[168]
    load[origin - pd.Timedelta(hours=168)] = np.nan  # reference of lead 1
    load[origin + pd.Timedelta(hours=1)] = np.nan  # target of lead 2
    load[origin + pd.Timedelta(hours=2)] = np.nan  # target of lead 3 ...
    load[origin + pd.Timedelta(hours=2 - 168)] = np.nan  # ... and its reference

    pairs = attach_actuals(seasonal_naive_forecast(load, pd.DatetimeIndex([origin])), load)
    summary = summarize(pairs)

    assert pairs["status"].iloc[:4].tolist() == [
        "reference_unavailable",
        "target_unavailable",
        "reference_and_target_unavailable",
        "valid",
    ]
    assert summary["n_forecast_origins"] == 1
    assert summary["n_forecast_targets"] == 24
    assert summary["n_targets_available"] == 22
    assert summary["n_references_available"] == 22
    assert summary["n_valid_pairs"] == 21
    assert summary["n_excluded_pairs"] == 3
    assert summary["excluded_by_reason"] == {
        "reference_unavailable": 1,
        "target_unavailable": 1,
        "reference_and_target_unavailable": 1,
    }
    assert summary["n_origins_with_all_leads_valid"] == 0
    # Every valid pair has error 1100 - 1000 = 100 MW.
    assert summary["overall"] == {
        "n_pairs": 21,
        "mae_mw": pytest.approx(100.0),
        "rmse_mw": pytest.approx(100.0),
        "wape_percent": pytest.approx(100 * 100 / 1100),
    }
    by_lead = {row["lead_hours"]: row for row in summary["by_lead_hour"]}
    assert sorted(by_lead) == list(range(1, 25))
    assert by_lead[1]["n_pairs"] == 0 and by_lead[1]["mae_mw"] is None
    assert by_lead[4]["n_pairs"] == 1 and by_lead[4]["mae_mw"] == pytest.approx(100.0)


def test_no_valid_pairs_yields_counts_without_metrics(load):
    origin = load.index[0]  # every weekly reference lies before the series starts
    pairs = attach_actuals(seasonal_naive_forecast(load, pd.DatetimeIndex([origin])), load)
    summary = summarize(pairs)

    assert summary["n_valid_pairs"] == 0
    assert summary["excluded_by_reason"]["reference_unavailable"] == 24
    assert summary["overall"] == {
        "n_pairs": 0,
        "mae_mw": None,
        "rmse_mw": None,
        "wape_percent": None,
    }


# --- Paired comparison of two baselines ----------------------------------------------


def evaluate_both(load: pd.Series, origins: pd.DatetimeIndex) -> dict[str, pd.DataFrame]:
    return {
        name: attach_actuals(seasonal_naive_forecast(load, origins, season), load)
        for name, season in (("daily_naive", DAILY_SEASON), ("weekly_naive", WEEKLY_SEASON))
    }


@pytest.fixture
def three_weeks() -> pd.Series:
    """Load 1000 + hour index, so every error is known: daily 24 MW, weekly 168 MW."""
    index = hourly_index("2018-01-01", periods=21 * 24)
    return pd.Series(1000.0 + np.arange(len(index)), index=index)


def test_models_are_aligned_on_identical_origins_and_targets(three_weeks):
    origins = pd.DatetimeIndex(three_weeks.index[[14 * 24, 15 * 24]])
    pairs = evaluate_both(three_weeks, origins)
    pairs["weekly_naive"] = pairs["weekly_naive"].iloc[::-1]  # row order must not matter

    aligned = align_pairs(pairs)

    assert len(aligned) == 48
    assert set(aligned["forecast_origin_utc"]) == set(origins)
    lag = aligned["target_timestamp_utc"] - aligned["daily_naive_reference_timestamp_utc"]
    assert (lag == DAILY_SEASON).all()
    lag = aligned["target_timestamp_utc"] - aligned["weekly_naive_reference_timestamp_utc"]
    assert (lag == WEEKLY_SEASON).all()


def test_models_evaluated_on_different_targets_cannot_be_aligned(three_weeks):
    day_15, day_16 = three_weeks.index[[14 * 24, 15 * 24]]
    pairs = {
        "daily_naive": evaluate_both(three_weeks, pd.DatetimeIndex([day_15]))["daily_naive"],
        "weekly_naive": evaluate_both(three_weeks, pd.DatetimeIndex([day_16]))["weekly_naive"],
    }
    with pytest.raises(ValueError, match="same forecast targets"):
        align_pairs(pairs)


def test_comparison_uses_only_pairs_valid_for_both_models(three_weeks):
    load = three_weeks.copy()
    origin = load.index[14 * 24]
    load[origin - pd.Timedelta(hours=24)] = np.nan  # daily reference of lead 1
    load[origin + HOUR - pd.Timedelta(hours=168)] = np.nan  # weekly reference of lead 2
    load[origin + 2 * HOUR] = np.nan  # target of lead 3
    load[origin + 3 * HOUR - pd.Timedelta(hours=24)] = np.nan  # lead 4: both references
    load[origin + 3 * HOUR - pd.Timedelta(hours=168)] = np.nan
    pairs = evaluate_both(load, pd.DatetimeIndex([origin]))

    aligned = align_pairs(pairs)
    result = compare(aligned, "daily_naive", "weekly_naive")

    assert aligned["comparison_status"].iloc[:5].tolist() == [
        "daily_naive_reference_unavailable",
        "weekly_naive_reference_unavailable",
        "target_unavailable",
        "both_references_unavailable",
        "common_valid",
    ]
    assert result["n_forecast_targets"] == 24
    assert result["n_targets_available"] == 23
    assert result["n_valid_pairs"] == {"daily_naive": 21, "weekly_naive": 21}
    assert result["n_common_valid_pairs"] == 20
    assert result["n_excluded_from_comparison"] == 4
    assert result["excluded_by_reason"] == {
        "target_unavailable": 1,
        "daily_naive_reference_unavailable": 1,
        "weekly_naive_reference_unavailable": 1,
        "both_references_unavailable": 1,
    }
    # Standalone counts differ from the common sample; paired metrics use only the 20 rows.
    assert summarize(pairs["weekly_naive"])["n_valid_pairs"] == 21
    paired = result["paired"]
    assert paired["n_pairs"] == 20
    assert paired["daily_naive"]["n_pairs"] == paired["weekly_naive"]["n_pairs"] == 20


def test_paired_metrics_differ_from_standalone_when_samples_differ():
    """A model must not be scored on rows where the other model has no prediction."""
    index = hourly_index("2018-01-15", periods=3)
    rows = pd.DataFrame(
        {
            "forecast_origin_utc": index[0],
            "target_timestamp_utc": index,
            "lead_hours": [1, 2, 3],
            "actual_load_mw": [100.0, 100.0, 100.0],
            "daily_naive_predicted_load_mw": [np.nan, 110.0, 120.0],
            "weekly_naive_predicted_load_mw": [500.0, 104.0, 108.0],
            "comparison_status": ["daily_naive_reference_unavailable"] + ["common_valid"] * 2,
        }
    )
    result = compare(rows, "daily_naive", "weekly_naive")["paired"]

    # The 400 MW weekly error on the first row is excluded from the paired comparison.
    assert result["weekly_naive"]["mae_mw"] == pytest.approx((4 + 8) / 2)
    assert result["daily_naive"]["mae_mw"] == pytest.approx((10 + 20) / 2)
    assert result["daily_naive_minus_weekly_naive_mae_mw"] == pytest.approx(15 - 6)


def test_paired_mae_difference_and_win_loss_tie_counts():
    rows = pd.DataFrame(
        {
            "actual_load_mw": [100.0, 100.0, 100.0, 100.0],
            "daily_naive_predicted_load_mw": [110.0, 95.0, 100.0, 120.0],  # |e| 10, 5, 0, 20
            "weekly_naive_predicted_load_mw": [105.0, 90.0, 100.0, 100.0],  # |e| 5, 10, 0, 0
            "comparison_status": "common_valid",
        }
    )
    result = paired_scores(rows, "daily_naive", "weekly_naive")

    assert result["daily_naive"]["mae_mw"] == pytest.approx(35 / 4)
    assert result["weekly_naive"]["mae_mw"] == pytest.approx(15 / 4)
    assert result["daily_naive"]["rmse_mw"] == pytest.approx(math.sqrt((100 + 25 + 0 + 400) / 4))
    assert result["daily_naive_minus_weekly_naive_mae_mw"] == pytest.approx(5.0)
    assert result["lower_absolute_error"] == {
        "counts": {"daily_naive": 1, "weekly_naive": 2, "tie": 1},
        "shares": {"daily_naive": 0.25, "weekly_naive": 0.5, "tie": 0.25},
    }


def test_paired_scores_reject_rows_not_valid_for_both_models():
    rows = pd.DataFrame(
        {
            "actual_load_mw": [100.0],
            "daily_naive_predicted_load_mw": [np.nan],
            "weekly_naive_predicted_load_mw": [100.0],
            "comparison_status": ["daily_naive_reference_unavailable"],
        }
    )
    with pytest.raises(ValueError, match="valid for all compared models"):
        paired_scores(rows, "daily_naive", "weekly_naive")


def test_empty_common_sample_reports_no_metrics(three_weeks):
    origin = three_weeks.index[0]  # no history: every reference is unavailable
    result = compare(
        align_pairs(evaluate_both(three_weeks, pd.DatetimeIndex([origin]))),
        "daily_naive",
        "weekly_naive",
    )

    assert result["n_common_valid_pairs"] == 0
    assert result["paired"]["daily_naive_minus_weekly_naive_mae_mw"] is None
    assert result["paired"]["lower_absolute_error"] is None
    assert result["paired"]["daily_naive"]["mae_mw"] is None


def test_paired_errors_match_known_seasonal_lags(three_weeks):
    origins = pd.DatetimeIndex(three_weeks.index[[14 * 24, 20 * 24]])
    result = compare(
        align_pairs(evaluate_both(three_weeks, origins)), "daily_naive", "weekly_naive"
    )

    paired = result["paired"]
    assert paired["daily_naive"]["mae_mw"] == pytest.approx(24.0)
    assert paired["weekly_naive"]["mae_mw"] == pytest.approx(168.0)
    assert paired["daily_naive_minus_weekly_naive_mae_mw"] == pytest.approx(-144.0)
    assert paired["lower_absolute_error"]["counts"] == {
        "daily_naive": 48,
        "weekly_naive": 0,
        "tie": 0,
    }


# --- Three-model comparison (LightGBM against both baselines) ------------------------


def model_pairs(predictions: list[float], actual: list[float]) -> pd.DataFrame:
    index = hourly_index("2018-03-01", periods=len(actual))
    return pd.DataFrame(
        {
            "forecast_origin_utc": index[0],
            "target_timestamp_utc": index,
            "lead_hours": np.arange(1, len(actual) + 1),
            "predicted_load_mw": predictions,
            "actual_load_mw": actual,
        }
    )


def three_models(weekly, daily, lightgbm, actual) -> pd.DataFrame:
    return align_pairs(
        {
            "weekly_naive": model_pairs(weekly, actual),
            "daily_naive": model_pairs(daily, actual),
            "lightgbm": model_pairs(lightgbm, actual),
        }
    )


def test_three_model_common_sample_and_coverage():
    nan = np.nan
    aligned = three_models(
        weekly=[110.0, 110.0, nan, nan, 110.0, 110.0],
        daily=[120.0, 120.0, 120.0, nan, 120.0, 120.0],
        lightgbm=[105.0, nan, 105.0, nan, 105.0, 105.0],
        actual=[100.0, 100.0, 100.0, 100.0, nan, 100.0],
    )
    result = compare_with_baselines(aligned, "lightgbm", ["weekly_naive", "daily_naive"])

    assert aligned["comparison_status"].tolist() == [
        "common_valid",
        "lightgbm_reference_unavailable",
        "weekly_naive_reference_unavailable",
        "several_references_unavailable",
        "target_unavailable",
        "common_valid",
    ]
    assert result["n_valid_pairs"] == {"weekly_naive": 3, "daily_naive": 4, "lightgbm": 3}
    assert result["n_common_valid_pairs"] == 2
    assert result["excluded_by_reason"] == {
        "target_unavailable": 1,
        "weekly_naive_reference_unavailable": 1,
        "daily_naive_reference_unavailable": 0,
        "lightgbm_reference_unavailable": 1,
        "several_references_unavailable": 1,
    }
    # All three models are scored on the same two rows, not on their own valid rows.
    common = result["common_sample"]
    assert common["n_pairs"] == 2
    assert [common[m]["n_pairs"] for m in ("weekly_naive", "daily_naive", "lightgbm")] == [2, 2, 2]
    assert common["daily_naive"]["mae_mw"] == pytest.approx(20.0)


def test_improvement_is_baseline_minus_candidate_mae_with_sign_and_relative_value():
    aligned = three_models(
        weekly=[110.0, 90.0, 110.0, 90.0],  # |e| = 10
        daily=[120.0, 80.0, 120.0, 80.0],  # |e| = 20
        lightgbm=[112.0, 88.0, 105.0, 100.0],  # |e| = 12, 12, 5, 0 -> MAE 7.25
        actual=[100.0, 100.0, 100.0, 100.0],
    )
    improvement = compare_with_baselines(aligned, "lightgbm", ["weekly_naive", "daily_naive"])[
        "lightgbm_improvement_over"
    ]

    weekly = improvement["weekly_naive"]
    assert weekly["absolute_mae_improvement_mw"] == pytest.approx(10 - 7.25)
    assert weekly["relative_mae_improvement_percent"] == pytest.approx(100 * 2.75 / 10)
    # RMSE: weekly 10, LightGBM sqrt((144 + 144 + 25 + 0) / 4)
    assert weekly["absolute_rmse_improvement_mw"] == pytest.approx(10 - math.sqrt(78.25))
    assert weekly["lower_absolute_error"]["counts"] == {
        "lightgbm": 2,
        "weekly_naive": 2,
        "tie": 0,
    }
    assert improvement["daily_naive"]["absolute_mae_improvement_mw"] == pytest.approx(20 - 7.25)


def test_worse_candidate_gets_a_negative_improvement():
    aligned = three_models(
        weekly=[105.0, 95.0],  # MAE 5
        daily=[110.0, 90.0],  # MAE 10
        lightgbm=[115.0, 85.0],  # MAE 15
        actual=[100.0, 100.0],
    )
    improvement = compare_with_baselines(aligned, "lightgbm", ["weekly_naive", "daily_naive"])[
        "lightgbm_improvement_over"
    ]

    assert improvement["weekly_naive"]["absolute_mae_improvement_mw"] == pytest.approx(-10.0)
    assert improvement["weekly_naive"]["relative_mae_improvement_percent"] == pytest.approx(-200.0)
    assert improvement["daily_naive"]["relative_mae_improvement_percent"] == pytest.approx(-50.0)


def test_relative_improvement_is_undefined_for_a_perfect_baseline():
    aligned = three_models(
        weekly=[100.0, 100.0],
        daily=[110.0, 90.0],
        lightgbm=[101.0, 99.0],
        actual=[100.0, 100.0],
    )
    weekly = compare_with_baselines(aligned, "lightgbm", ["weekly_naive", "daily_naive"])[
        "lightgbm_improvement_over"
    ]["weekly_naive"]

    assert weekly["absolute_mae_improvement_mw"] == pytest.approx(-1.0)
    assert weekly["relative_mae_improvement_percent"] is None
