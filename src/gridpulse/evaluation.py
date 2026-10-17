"""Alignment of forecasts with observations, error metrics and result summaries."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd

from gridpulse.data import check_time_index

VALID = "valid"
EXCLUSION_REASONS = (
    "reference_unavailable",
    "target_unavailable",
    "reference_and_target_unavailable",
)
COMMON_VALID = "common_valid"


def _checked_pairs(y_true, y_pred) -> tuple[np.ndarray, np.ndarray]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if y_true.ndim != 1 or y_true.shape != y_pred.shape:
        raise ValueError(
            f"expected two 1-D arrays of equal length, got {y_true.shape} and {y_pred.shape}"
        )
    if y_true.size == 0:
        raise ValueError("cannot compute an error metric on zero pairs")
    if not (np.isfinite(y_true).all() and np.isfinite(y_pred).all()):
        raise ValueError("non-finite values present; exclude invalid pairs before scoring")
    return y_true, y_pred


def mae(y_true, y_pred) -> float:
    """Mean absolute error, in the unit of the inputs."""
    y_true, y_pred = _checked_pairs(y_true, y_pred)
    return float(np.mean(np.abs(y_true - y_pred)))


def rmse(y_true, y_pred) -> float:
    """Root mean squared error, in the unit of the inputs."""
    y_true, y_pred = _checked_pairs(y_true, y_pred)
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def wape(y_true, y_pred) -> float:
    """Weighted absolute percentage error: 100 * sum|y - y_hat| / sum|y|.

    Undefined (ValueError) when sum|y| is zero.
    """
    y_true, y_pred = _checked_pairs(y_true, y_pred)
    denominator = np.sum(np.abs(y_true))
    if denominator == 0:
        raise ValueError("WAPE is undefined when the sum of absolute actual values is zero")
    return float(100 * np.sum(np.abs(y_true - y_pred)) / denominator)


def attach_actuals(forecasts: pd.DataFrame, load: pd.Series) -> pd.DataFrame:
    """Add the observed load for each target timestamp and classify each pair.

    Observations are matched by timestamp label, never by position. `status` is
    "valid" when both the prediction and the observation are finite, otherwise the
    reason the pair is excluded from scoring.
    """
    problems = check_time_index(load.index)
    if problems:
        raise ValueError("load index is not a valid hourly UTC index: " + "; ".join(problems))
    targets = pd.DatetimeIndex(forecasts["target_timestamp_utc"])
    if str(targets.tz) != "UTC":
        raise ValueError(f"target timestamps must be UTC, got tz={targets.tz}")
    actual = load.reindex(targets).to_numpy()
    has_prediction = np.isfinite(forecasts["predicted_load_mw"].to_numpy())
    has_actual = np.isfinite(actual)
    status = np.select(
        [has_prediction & has_actual, has_actual, has_prediction],
        [VALID, "reference_unavailable", "target_unavailable"],
        default="reference_and_target_unavailable",
    )
    return forecasts.assign(
        actual_load_mw=np.where(has_actual, actual, np.nan),
        status=status,
    )


def _scores(y_true: pd.Series, y_pred: pd.Series) -> dict:
    if len(y_true) == 0:
        return {"n_pairs": 0, "mae_mw": None, "rmse_mw": None, "wape_percent": None}
    return {
        "n_pairs": len(y_true),
        "mae_mw": mae(y_true, y_pred),
        "rmse_mw": rmse(y_true, y_pred),
        "wape_percent": wape(y_true, y_pred),
    }


def _pair_scores(pairs: pd.DataFrame) -> dict:
    return _scores(pairs["actual_load_mw"], pairs["predicted_load_mw"])


def summarize(pairs: pd.DataFrame) -> dict:
    """Counts of possible, available and excluded comparisons plus metrics on valid pairs."""
    is_valid = pairs["status"] == VALID
    valid = pairs[is_valid]
    excluded_counts = pairs.loc[~is_valid, "status"].value_counts()
    all_leads_valid = is_valid.groupby(pairs["forecast_origin_utc"]).all()
    return {
        "n_forecast_origins": int(pairs["forecast_origin_utc"].nunique()),
        "n_forecast_targets": len(pairs),
        "n_targets_available": int(np.isfinite(pairs["actual_load_mw"]).sum()),
        "n_references_available": int(np.isfinite(pairs["predicted_load_mw"]).sum()),
        "n_valid_pairs": int(is_valid.sum()),
        "n_excluded_pairs": int((~is_valid).sum()),
        "excluded_by_reason": {
            reason: int(excluded_counts.get(reason, 0)) for reason in EXCLUSION_REASONS
        },
        "n_origins_with_all_leads_valid": int(all_leads_valid.sum()),
        "overall": _pair_scores(valid),
        "by_lead_hour": [
            {"lead_hours": int(lead), **_pair_scores(valid[valid["lead_hours"] == lead])}
            for lead in sorted(pairs["lead_hours"].unique())
        ],
    }


def _several_unavailable(n_models: int) -> str:
    return "both_references_unavailable" if n_models == 2 else "several_references_unavailable"


def align_pairs(pairs_by_model: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Place several models' evaluated pairs side by side, one row per forecast target.

    Raises ValueError unless all models were evaluated on exactly the same
    (origin, target, lead) rows with the same observed load. `comparison_status` is
    "common_valid" when the target and every model's prediction are available, which is
    the only sample on which models are compared; otherwise it states why the row is
    excluded. An unavailable target takes precedence over unavailable predictions.
    """
    if len(pairs_by_model) < 2:
        raise ValueError(f"expected at least two models, got {list(pairs_by_model)}")
    keys = ["forecast_origin_utc", "target_timestamp_utc", "lead_hours"]
    shared = None
    model_columns = {}
    has_prediction = {}
    for name, pairs in pairs_by_model.items():
        pairs = pairs.sort_values(["forecast_origin_utc", "lead_hours"], ignore_index=True)
        if shared is None:
            shared = pairs[[*keys, "actual_load_mw"]]
        elif not pairs[[*keys, "actual_load_mw"]].equals(shared):
            raise ValueError(f"{name} was not evaluated on the same forecast targets")
        if "reference_timestamp_utc" in pairs:
            model_columns[f"{name}_reference_timestamp_utc"] = pairs["reference_timestamp_utc"]
        model_columns[f"{name}_predicted_load_mw"] = pairs["predicted_load_mw"]
        has_prediction[name] = np.isfinite(pairs["predicted_load_mw"].to_numpy())

    missing = ~np.column_stack(list(has_prediction.values()))
    n_missing = missing.sum(axis=1)
    status = np.full(len(shared), COMMON_VALID, dtype=object)
    for column, name in enumerate(has_prediction):
        status[missing[:, column] & (n_missing == 1)] = f"{name}_reference_unavailable"
    status[n_missing > 1] = _several_unavailable(len(has_prediction))
    status[~np.isfinite(shared["actual_load_mw"].to_numpy())] = "target_unavailable"
    return shared.assign(**model_columns, comparison_status=status)


def mae_difference_key(model_a: str, model_b: str) -> str:
    return f"{model_a}_minus_{model_b}_mae_mw"


def common_sample_scores(rows: pd.DataFrame, models: Sequence[str]) -> dict:
    """Each model's metrics on the same rows, which must all be common-valid."""
    if not (rows["comparison_status"] == COMMON_VALID).all():
        raise ValueError("paired scores require rows that are valid for all compared models")
    actual = rows["actual_load_mw"]
    return {name: _scores(actual, rows[f"{name}_predicted_load_mw"]) for name in models}


def paired_scores(rows: pd.DataFrame, model_a: str, model_b: str) -> dict:
    """Both models' metrics on the same rows, their MAE difference (a - b) and win counts.

    `rows` must contain only common-valid rows of an `align_pairs` table, so that both
    models are scored on an identical sample.
    """
    scores = common_sample_scores(rows, (model_a, model_b))
    result = {"n_pairs": len(rows), **scores}
    difference_key = mae_difference_key(model_a, model_b)
    if rows.empty:
        return {**result, difference_key: None, "lower_absolute_error": None}

    actual = rows["actual_load_mw"]
    error_a = np.abs(actual - rows[f"{model_a}_predicted_load_mw"]).to_numpy()
    error_b = np.abs(actual - rows[f"{model_b}_predicted_load_mw"]).to_numpy()
    counts = {
        model_a: int((error_a < error_b).sum()),
        model_b: int((error_b < error_a).sum()),
        "tie": int((error_a == error_b).sum()),
    }
    return {
        **result,
        difference_key: scores[model_a]["mae_mw"] - scores[model_b]["mae_mw"],
        "lower_absolute_error": {
            "counts": counts,
            "shares": {key: count / len(rows) for key, count in counts.items()},
        },
    }


def _coverage(aligned: pd.DataFrame, models: Sequence[str]) -> dict:
    status_counts = aligned["comparison_status"].value_counts()
    has_target = np.isfinite(aligned["actual_load_mw"])
    n_common = int((aligned["comparison_status"] == COMMON_VALID).sum())
    return {
        "n_forecast_origins": int(aligned["forecast_origin_utc"].nunique()),
        "n_forecast_targets": len(aligned),
        "n_targets_available": int(has_target.sum()),
        "n_valid_pairs": {
            name: int((has_target & np.isfinite(aligned[f"{name}_predicted_load_mw"])).sum())
            for name in models
        },
        "n_common_valid_pairs": n_common,
        "n_excluded_from_comparison": len(aligned) - n_common,
        "excluded_by_reason": {
            reason: int(status_counts.get(reason, 0))
            for reason in (
                "target_unavailable",
                *(f"{name}_reference_unavailable" for name in models),
                _several_unavailable(len(models)),
            )
        },
    }


def compare(aligned: pd.DataFrame, model_a: str, model_b: str) -> dict:
    """Coverage of an `align_pairs` table and the paired comparison on its common sample."""
    common = aligned[aligned["comparison_status"] == COMMON_VALID]
    return {
        **_coverage(aligned, (model_a, model_b)),
        "paired": paired_scores(common, model_a, model_b),
    }


def compare_with_baselines(aligned: pd.DataFrame, candidate: str, baselines: Sequence[str]) -> dict:
    """Coverage, every model's metrics on the common sample, and the candidate's improvement.

    Improvement over a baseline is baseline MAE minus candidate MAE (positive: the candidate
    has lower MAE), also relative to the baseline MAE; the relative value is undefined
    (None) when the baseline MAE is zero.
    """
    models = [*baselines, candidate]
    common = aligned[aligned["comparison_status"] == COMMON_VALID]
    improvement = {}
    for baseline in baselines:
        paired = paired_scores(common, candidate, baseline)
        if common.empty:
            improvement[baseline] = None
            continue
        baseline_mae = paired[baseline]["mae_mw"]
        absolute = baseline_mae - paired[candidate]["mae_mw"]
        improvement[baseline] = {
            "absolute_mae_improvement_mw": absolute,
            "relative_mae_improvement_percent": 100 * absolute / baseline_mae
            if baseline_mae > 0
            else None,
            "absolute_rmse_improvement_mw": paired[baseline]["rmse_mw"]
            - paired[candidate]["rmse_mw"],
            "lower_absolute_error": paired["lower_absolute_error"],
        }
    return {
        **_coverage(aligned, models),
        "common_sample": {"n_pairs": len(common), **common_sample_scores(common, models)},
        f"{candidate}_improvement_over": improvement,
    }
