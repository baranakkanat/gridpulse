import lightgbm as lgb
import numpy as np
import pandas as pd
import pytest
from conftest import hourly_index

from gridpulse.evaluation import mae
from gridpulse.features import FEATURES, TARGET, feature_table, is_usable
from gridpulse.model import (
    NUM_BOOST_ROUND,
    PARAMS,
    feature_matrix,
    predict,
    save_and_verify,
    train,
)

WEEKS = {"train": (0, 8), "validation": (8, 10), "test": (10, 12)}


@pytest.fixture(scope="module")
def tables() -> dict[str, pd.DataFrame]:
    """Twelve weeks of synthetic load with daily and weekly structure plus noise."""
    index = hourly_index("2018-01-01", periods=12 * 7 * 24)
    hours = np.arange(len(index))
    noise = np.random.default_rng(0).normal(0, 500, len(index))
    values = 50_000 + 8_000 * np.sin(2 * np.pi * hours / 24) - 6_000 * (index.dayofweek >= 5)
    load = pd.Series(values + noise, index=index)
    days = pd.date_range("2018-01-01", periods=12 * 7, freq="D", tz="UTC")
    return {
        split: feature_table(load, days[first * 7 : last * 7])
        for split, (first, last) in WEEKS.items()
    }


@pytest.fixture(scope="module")
def fitted(tables):
    return train(tables["train"], tables["validation"])


def test_model_uses_exactly_the_documented_features_in_order(tables, fitted):
    booster, info = fitted
    assert booster.feature_name() == list(FEATURES)
    assert info["features"] == list(FEATURES)
    assert list(feature_matrix(tables["test"]).columns) == list(FEATURES)
    assert TARGET not in feature_matrix(tables["test"]).columns


def test_training_rows_exclude_missing_history_and_come_from_the_training_table(fitted):
    _, info = fitted
    # The first training week has no 168-hour lag and is excluded, not filled.
    assert info["training_rows"]["n_rows"] == 8 * 7 * 24
    assert info["training_rows"]["n_usable"] == 7 * 7 * 24
    assert info["training_rows"]["excluded_because"]["lag_168h_unavailable"] == 7 * 24
    assert info["training_rows"]["first_target_utc"] == "2018-01-08T00:00:00Z"
    assert info["training_rows"]["last_target_utc"] == "2018-02-25T23:00:00Z"
    assert info["early_stopping_rows"]["n_usable"] == 2 * 7 * 24
    assert info["early_stopping_rows"]["first_target_utc"] == "2018-02-26T00:00:00Z"


def test_model_equals_one_fitted_without_any_validation_data(tables, fitted):
    """Validation rows may only choose the number of rounds: no gradients, no feature bins."""
    booster, info = fitted
    rows = tables["train"][is_usable(tables["train"])]
    plain = lgb.train(
        PARAMS,
        lgb.Dataset(feature_matrix(rows), label=rows[TARGET]),
        num_boost_round=info["best_iteration"],
    )

    assert info["best_iteration"] < NUM_BOOST_ROUND  # early stopping is exercised here
    features = feature_matrix(tables["test"])
    np.testing.assert_array_equal(booster.predict(features), plain.predict(features))


def test_early_stopping_score_is_the_validation_mae_at_the_kept_iteration(tables, fitted):
    booster, info = fitted
    rows = tables["validation"]
    assert 1 <= info["best_iteration"] <= NUM_BOOST_ROUND
    assert info["num_trees"] == info["best_iteration"]
    # LightGBM scores against float32 copies of the labels, hence the small tolerance.
    assert info["best_validation_l1_mw"] == pytest.approx(
        mae(rows[TARGET], predict(booster, rows)), rel=1e-6
    )


def test_predictions_follow_rows_and_are_missing_when_a_feature_is_missing(tables, fitted):
    booster, _ = fitted
    rows = tables["test"].copy()
    rows.loc[5, "lag_24h_mw"] = np.nan
    predictions = predict(booster, rows)

    assert predictions.shape == (len(rows),)
    assert np.isnan(predictions).tolist() == [i == 5 for i in range(len(rows))]
    shuffled = rows.sample(frac=1, random_state=1)
    np.testing.assert_array_equal(predict(booster, shuffled), predictions[shuffled.index])


def test_saved_model_reloads_with_identical_predictions(tables, fitted, tmp_path):
    booster, _ = fitted
    check = save_and_verify(booster, tmp_path / "model.txt", tables["test"])

    assert check["max_abs_difference_mw"] == 0.0
    assert check["rows_checked"] == len(tables["test"])
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model.txt"]
    reloaded = lgb.Booster(model_file=tmp_path / "model.txt")
    np.testing.assert_array_equal(
        predict(reloaded, tables["test"]), predict(booster, tables["test"])
    )


def test_repeated_training_gives_an_identical_model(tables, fitted):
    booster, _ = fitted
    again, _ = train(tables["train"], tables["validation"])
    assert again.model_to_string() == booster.model_to_string()
