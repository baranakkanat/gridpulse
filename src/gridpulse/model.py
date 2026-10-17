"""One pooled LightGBM regressor for all 24 leads, with a fixed, predefined configuration.

The configuration is an experimental setting chosen before training, not a tuned optimum.
Validation rows are used only to choose the boosting iteration (early stopping); they never
contribute gradients.
"""

from __future__ import annotations

from importlib.metadata import version
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from gridpulse.data import utc_iso
from gridpulse.features import FEATURES, TARGET, availability_counts, has_features, is_usable

PARAMS = {
    "objective": "regression_l1",
    "metric": "l1",
    "learning_rate": 0.05,
    "num_leaves": 15,
    "min_data_in_leaf": 100,
    "seed": 42,
    "device_type": "cpu",
    "deterministic": True,
    "force_col_wise": True,
    "num_threads": 1,
    "verbosity": -1,  # logging only
}
NUM_BOOST_ROUND = 500
EARLY_STOPPING_ROUNDS = 50


def feature_matrix(rows: pd.DataFrame) -> pd.DataFrame:
    return rows[list(FEATURES)]


def train(train_rows: pd.DataFrame, validation_rows: pd.DataFrame) -> tuple[lgb.Booster, dict]:
    """Fit on complete training rows; stop early on the validation L1 (MAE).

    Rows with an unavailable feature or target are excluded, not filled. Feature bins are
    built from the training rows only. Returns the booster, truncated to its best
    iteration, and a description of the fit.
    """
    fit_rows, stop_rows = (
        train_rows[is_usable(train_rows)],
        validation_rows[is_usable(validation_rows)],
    )
    train_set = lgb.Dataset(
        feature_matrix(fit_rows), label=fit_rows[TARGET], feature_name=list(FEATURES)
    )
    validation_set = lgb.Dataset(
        feature_matrix(stop_rows), label=stop_rows[TARGET], reference=train_set
    )
    booster = lgb.train(
        PARAMS,
        train_set,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[validation_set],
        valid_names=["validation"],
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )
    info = {
        "lightgbm_version": version("lightgbm"),
        "features": list(FEATURES),
        "params": PARAMS,
        "num_boost_round": NUM_BOOST_ROUND,
        "early_stopping_rounds": EARLY_STOPPING_ROUNDS,
        "best_iteration": booster.best_iteration,
        "num_trees": booster.num_trees(),
        "best_validation_l1_mw": float(booster.best_score["validation"]["l1"]),
        "training_rows": _row_summary(train_rows, fit_rows),
        "early_stopping_rows": _row_summary(validation_rows, stop_rows),
    }
    return booster, info


def _row_summary(rows: pd.DataFrame, used: pd.DataFrame) -> dict:
    targets = used["target_timestamp_utc"]
    return {
        **availability_counts(rows),
        "first_target_utc": utc_iso(targets.min()) if len(used) else None,
        "last_target_utc": utc_iso(targets.max()) if len(used) else None,
    }


def save_and_verify(
    booster: lgb.Booster, path: Path, rows: pd.DataFrame, tolerance_mw: float = 1e-6
) -> dict:
    """Save the booster in LightGBM's text format and check that the reloaded file
    reproduces its predictions on `rows`.

    The file is written under a temporary name and only renamed to `path` after the check
    passes; otherwise it is removed and RuntimeError is raised.
    """
    candidate = path.with_name(path.name + ".unverified")
    booster.save_model(candidate)
    reloaded = lgb.Booster(model_file=candidate)
    original, restored = predict(booster, rows), predict(reloaded, rows)
    max_difference = float(np.nanmax(np.abs(original - restored), initial=0.0))
    if not np.array_equal(np.isnan(original), np.isnan(restored)) or max_difference > tolerance_mw:
        candidate.unlink()
        raise RuntimeError(
            f"reloaded model does not reproduce its predictions ({max_difference} MW)"
        )
    candidate.replace(path)
    return {
        "file": path.name,
        "rows_checked": int(np.isfinite(original).sum()),
        "max_abs_difference_mw": max_difference,
        "tolerance_mw": tolerance_mw,
    }


def predict(booster: lgb.Booster, rows: pd.DataFrame) -> np.ndarray:
    """Predictions in MW for rows whose features are all available; NaN for the others."""
    complete = has_features(rows)
    predictions = np.full(len(rows), np.nan)
    if complete.any():
        predictions[complete] = booster.predict(feature_matrix(rows[complete]))
    return predictions
