"""Command-line entry point.

`python -m gridpulse {validate,baseline,compare,train-lightgbm,forecast-study,grid-study,
dual-study,sense-study,noise-study,margin-study,demonstrate}`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import pandas as pd

from gridpulse.baseline import (
    DAILY_NAIVE,
    HORIZON_HOURS,
    SEASONAL_NAIVE_BASELINES,
    WEEKLY_NAIVE,
    WEEKLY_SEASON,
    daily_origins,
    seasonal_naive_forecast,
)
from gridpulse.calendar_analysis import (
    CALENDAR_COVERAGE,
    HOLIDAY_SOURCE,
    LOCAL_TIMEZONE,
    NATIONAL_HOLIDAYS,
    annotate_calendar,
    calendar_breakdown,
)
from gridpulse.data import (
    DATASET,
    HOUR,
    RESERVED_FROM,
    SPLITS,
    TARGET_COLUMN,
    TARGET_UNIT,
    TIMESTAMP_COLUMN,
    hourly_load,
    quality_report,
    read_source,
    sha256_of_file,
    utc_iso,
)
from gridpulse.evaluation import (
    align_pairs,
    attach_actuals,
    compare,
    compare_with_baselines,
    mae_difference_key,
    summarize,
)
from gridpulse.features import FEATURE_DEFINITIONS, feature_table

EVALUATED_SPLITS = ("validation", "test")
CSV_DATE_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# Paired differences are reported as daily minus weekly.
MODEL_A, MODEL_B = DAILY_NAIVE, WEEKLY_NAIVE
LIGHTGBM = "lightgbm"
BASELINE_MODELS = (WEEKLY_NAIVE, DAILY_NAIVE)
MISSING_DATA_POLICY = (
    "A pair is scored only if both the {reference} observation and the target "
    "observation are available; other pairs are excluded and counted by reason."
)
METRIC_DEFINITIONS = {
    "mae_mw": "mean(|y - y_hat|)",
    "rmse_mw": "sqrt(mean((y - y_hat)^2))",
    "wape_percent": "100 * sum(|y - y_hat|) / sum(|y|); undefined if sum(|y|) = 0",
}


def _checked_provenance(path: Path) -> dict:
    """File name, size and SHA-256, warning if the checksum differs from the official one."""
    sha256 = sha256_of_file(path)
    matches = sha256 == DATASET["sha256"]
    if not matches:
        print(
            f"warning: {path.name} does not match the official SHA-256 of "
            f"{DATASET['filename']} (OPSD {DATASET['version']})",
            file=sys.stderr,
        )
    return {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256,
        "sha256_matches_official": matches,
    }


def _write_json(path: Path, content: dict) -> None:
    from gridpulse.runguard import atomic_write_text

    atomic_write_text(path, json.dumps(content, indent=2) + "\n")


def run_validate(input_path: Path) -> int:
    provenance = _checked_provenance(input_path)
    report = {
        "file": provenance,
        "scope": "all rows in the file, including the reserved period",
        **quality_report(read_source(input_path)),
    }
    print(json.dumps(report, indent=2))
    return 1 if report["time_index_problems"] else 0


def _experiment_load(input_path: Path) -> tuple[pd.Series, dict]:
    """Read the file once and return the validated hourly load before the reserved period."""
    provenance = _checked_provenance(input_path)
    source = read_source(input_path)
    # The reserved period is removed before any check or statistic of the experiment.
    source = source[source.index < RESERVED_FROM]
    if source.empty:
        raise ValueError(f"no observations before {utc_iso(RESERVED_FROM)}")
    report = {
        "file": provenance,
        "scope": f"rows before {utc_iso(RESERVED_FROM)} (reserved period excluded)",
        **quality_report(source),
    }
    if report["time_index_problems"]:
        raise ValueError("; ".join(report["time_index_problems"]))
    return hourly_load(source), report


def _baseline_description(season: pd.Timedelta) -> dict:
    hours = int(season / HOUR)
    return {
        "name": "seasonal_naive",
        "season_length_hours": hours,
        "rule": f"prediction(t) = load(t - {hours} h)",
    }


def run_baseline(input_path: Path, output_dir: Path) -> int:
    started = datetime.now(UTC)
    load, report = _experiment_load(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "data_quality.json", report)

    metrics = {}
    for split in EVALUATED_SPLITS:
        origins = daily_origins(*SPLITS[split])
        pairs = attach_actuals(seasonal_naive_forecast(load, origins), load)
        pairs.to_csv(
            output_dir / f"{split}_predictions.csv", index=False, date_format=CSV_DATE_FORMAT
        )
        metrics[split] = summarize(pairs)
    _write_json(output_dir / "metrics.json", metrics)
    metadata = _run_metadata(
        started,
        report,
        models={"baseline": _baseline_description(WEEKLY_SEASON)},
        evaluation={
            "missing_data_policy": MISSING_DATA_POLICY.format(reference="weekly reference"),
            "metrics": METRIC_DEFINITIONS,
            "n_valid_pairs": {split: metrics[split]["n_valid_pairs"] for split in metrics},
        },
    )
    _write_json(output_dir / "run_metadata.json", metadata)

    for split in EVALUATED_SPLITS:
        overall = metrics[split]["overall"]
        print(
            f"{split:>10}: n={overall['n_pairs']} valid pairs, "
            f"MAE={_fmt(overall['mae_mw'])} MW, RMSE={_fmt(overall['rmse_mw'])} MW, "
            f"WAPE={_fmt(overall['wape_percent'], 2)} %"
        )
    print(f"outputs written to {output_dir}")
    return 0


def run_compare(input_path: Path, output_dir: Path) -> int:
    started = datetime.now(UTC)
    load, report = _experiment_load(input_path)

    metrics, predictions, breakdowns = {}, [], []
    for split in EVALUATED_SPLITS:
        origins = daily_origins(*SPLITS[split])
        pairs = {
            name: attach_actuals(seasonal_naive_forecast(load, origins, season), load)
            for name, season in SEASONAL_NAIVE_BASELINES.items()
        }
        annotated = annotate_calendar(align_pairs(pairs))
        metrics[split] = {
            "comparison": compare(annotated, MODEL_A, MODEL_B),
            "standalone": {name: summarize(model_pairs) for name, model_pairs in pairs.items()},
        }
        predictions.append(annotated.assign(period=split))
        breakdowns.append(
            calendar_breakdown(annotated, (MODEL_A, MODEL_B), (MODEL_A, MODEL_B)).assign(
                period=split
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "data_quality.json", report)
    _write_json(output_dir / "comparison_metrics.json", metrics)
    _first_column(pd.concat(predictions, ignore_index=True), "period").to_csv(
        output_dir / "comparison_predictions.csv", index=False, date_format=CSV_DATE_FORMAT
    )
    _first_column(pd.concat(breakdowns, ignore_index=True), "period").to_csv(
        output_dir / "calendar_analysis.csv", index=False
    )
    metadata = _run_metadata(
        started,
        report,
        models={
            "baselines": {
                name: _baseline_description(season)
                for name, season in SEASONAL_NAIVE_BASELINES.items()
            }
        },
        evaluation={
            "missing_data_policy": MISSING_DATA_POLICY.format(reference="model's reference"),
            "comparison_sample": (
                "Primary comparison on common-valid pairs only: target and both models' "
                "references available. Standalone metrics use each model's own valid pairs."
            ),
            "paired_statistics": {
                mae_difference_key(MODEL_A, MODEL_B): f"MAE({MODEL_A}) - MAE({MODEL_B})",
                "lower_absolute_error": "pairs where a model's absolute error is strictly "
                "lower than the other's; equal absolute errors are ties",
            },
            "metrics": METRIC_DEFINITIONS,
            "calendar": _calendar_metadata("both models"),
            "n_common_valid_pairs": {
                split: metrics[split]["comparison"]["n_common_valid_pairs"] for split in metrics
            },
        },
    )
    _write_json(output_dir / "run_metadata.json", metadata)

    for split in EVALUATED_SPLITS:
        paired = metrics[split]["comparison"]["paired"]
        print(
            f"{split:>10}: n={paired['n_pairs']} common pairs, MAE daily="
            f"{_fmt(paired[MODEL_A]['mae_mw'])} MW, weekly={_fmt(paired[MODEL_B]['mae_mw'])} MW, "
            f"daily - weekly={_fmt(paired[mae_difference_key(MODEL_A, MODEL_B)])} MW"
        )
    print(f"outputs written to {output_dir}")
    return 0


def run_train_lightgbm(input_path: Path, output_dir: Path) -> int:
    from gridpulse import model  # deferred: only this command needs LightGBM

    started = datetime.now(UTC)
    load, report = _experiment_load(input_path)
    origins = {split: daily_origins(*SPLITS[split]) for split in ("train", *EVALUATED_SPLITS)}
    features = {split: feature_table(load, days) for split, days in origins.items()}
    # Gradients come from train targets (2015-2017) only; 2018 only selects the iteration.
    booster, training = model.train(features["train"], features["validation"])

    metrics, predictions, breakdowns = {}, [], []
    for split in EVALUATED_SPLITS:
        rows = features[split]
        pairs = {
            name: attach_actuals(
                seasonal_naive_forecast(load, origins[split], SEASONAL_NAIVE_BASELINES[name]), load
            )
            for name in BASELINE_MODELS
        }
        lightgbm_forecasts = rows[["forecast_origin_utc", "target_timestamp_utc", "lead_hours"]]
        pairs[LIGHTGBM] = attach_actuals(
            lightgbm_forecasts.assign(predicted_load_mw=model.predict(booster, rows)), load
        )
        annotated = annotate_calendar(align_pairs(pairs))
        metrics[split] = {
            "comparison": compare_with_baselines(annotated, LIGHTGBM, BASELINE_MODELS),
            "standalone": {name: summarize(model_pairs) for name, model_pairs in pairs.items()},
        }
        predictions.append(annotated.assign(period=split))
        breakdowns.append(
            calendar_breakdown(
                annotated, (*BASELINE_MODELS, LIGHTGBM), (LIGHTGBM, WEEKLY_NAIVE)
            ).assign(period=split)
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    reload_check = model.save_and_verify(
        booster,
        output_dir / "model.txt",
        pd.concat([features[split] for split in EVALUATED_SPLITS], ignore_index=True),
    )
    _write_json(output_dir / "data_quality.json", report)
    _write_json(output_dir / "metrics.json", metrics)
    _first_column(pd.concat(predictions, ignore_index=True), "period").to_csv(
        output_dir / "predictions.csv", index=False, date_format=CSV_DATE_FORMAT
    )
    _first_column(pd.concat(breakdowns, ignore_index=True), "period").to_csv(
        output_dir / "calendar_analysis.csv", index=False
    )
    metadata = _run_metadata(
        started,
        report,
        models={
            "baselines": {
                name: _baseline_description(SEASONAL_NAIVE_BASELINES[name])
                for name in BASELINE_MODELS
            },
            LIGHTGBM: {
                "description": "one pooled LightGBM regressor for all 24 leads",
                "feature_definitions": FEATURE_DEFINITIONS,
                "feature_availability": (
                    "Lag features are looked up by UTC timestamp and both sources start before "
                    "the origin for every lead; calendar features use only the target timestamp. "
                    "No observation from the forecast horizon, no holiday label and no external "
                    "data is used. Rows with an unavailable feature get no prediction."
                ),
                "training": training,
                "fit_period": "train",
                "early_stopping_period": "validation",
                "held_out_period": "test",
                "note": (
                    "Validation (2018) metrics are reported but 2018 is the early-stopping "
                    "selection period; only test (2019) is held out from all model choices."
                ),
                "model_file_check": reload_check,
            },
        },
        evaluation={
            "missing_data_policy": (
                "Rows with an unavailable feature or target are excluded from fitting and early "
                "stopping, never filled. In evaluation a pair is scored only if the target and "
                "every model's prediction are available; other pairs are excluded and counted "
                "by reason."
            ),
            "comparison_sample": (
                "Primary comparison on common-valid pairs only: target and all three models' "
                "predictions available. Standalone metrics use each model's own valid pairs."
            ),
            "improvement_statistics": {
                "absolute_mae_improvement_mw": "MAE(baseline) - MAE(lightgbm); positive means "
                "lightgbm has lower MAE",
                "relative_mae_improvement_percent": "100 * absolute improvement / MAE(baseline); "
                "undefined (null) if MAE(baseline) = 0",
                "absolute_rmse_improvement_mw": "RMSE(baseline) - RMSE(lightgbm)",
                "lower_absolute_error": "pairs where a model's absolute error is strictly "
                "lower than the other's; equal absolute errors are ties",
            },
            "metrics": METRIC_DEFINITIONS,
            "calendar": _calendar_metadata("all models"),
            "n_common_valid_pairs": {
                split: metrics[split]["comparison"]["n_common_valid_pairs"] for split in metrics
            },
            "limitations": [
                "Single fixed configuration chosen before training; not tuned, not optimal.",
                "2019 was inspected in earlier baseline and holiday analyses, so it is not an "
                "untouched confirmatory period, although this model was never evaluated on it "
                "before being frozen.",
                "Forecasts assume all load up to the origin is known: no publication delay or "
                "data revision, unlike operational day-ahead forecasting.",
                "No uncertainty estimates, significance tests or explanations are produced.",
                "Bitwise reproducibility is expected only for the same platform and library "
                "versions.",
            ],
        },
    )
    _write_json(output_dir / "run_metadata.json", metadata)

    print(
        f"best iteration {training['best_iteration']} of {training['num_boost_round']}, "
        f"{training['training_rows']['n_usable']} training rows"
    )
    for split in EVALUATED_SPLITS:
        comparison = metrics[split]["comparison"]
        scores = comparison["common_sample"]
        improvement = comparison[f"{LIGHTGBM}_improvement_over"][WEEKLY_NAIVE]
        print(
            f"{split:>10}: n={scores['n_pairs']} common pairs, MAE weekly="
            f"{_fmt(scores[WEEKLY_NAIVE]['mae_mw'])} daily={_fmt(scores[DAILY_NAIVE]['mae_mw'])} "
            f"lightgbm={_fmt(scores[LIGHTGBM]['mae_mw'])} MW, improvement over weekly="
            f"{_fmt(improvement and improvement['absolute_mae_improvement_mw'])} MW"
        )
    print(f"outputs written to {output_dir}")
    return 0


def run_forecast_study(input_path: Path, output_dir: Path) -> int:
    from gridpulse import forecast_study as study

    started = datetime.now(UTC)
    load, report = _experiment_load(input_path)
    results = study.run_forecast_study(load)

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "data_quality.json", report)
    _write_json(output_dir / "c1_boosting_cap.json", results["c1"])
    _write_json(output_dir / "c2_holiday_ablation.json", results["c2"])
    _first_column(results["c2_calendar"], "period").to_csv(
        output_dir / "c2_calendar_analysis.csv", index=False
    )
    _write_json(output_dir / "c3_intervals.json", results["c3"])
    results["c3_breakdown"].to_csv(output_dir / "c3_coverage_breakdown.csv", index=False)
    results["c3_intervals"].to_csv(
        output_dir / "c3_intervals.csv", index=False, date_format=CSV_DATE_FORMAT
    )
    metadata = _run_metadata(
        started,
        report,
        models={
            "lightgbm_version": version("lightgbm"),
            "c1_caps": list(study.C1_CAPS),
            "c2_arms": {arm: list(features) for arm, features in study.C2_FEATURES.items()},
            "c3": {
                "method": "rolling split conformal on absolute residuals, per lead",
                "window_days": study.C3_WINDOW_DAYS,
                "alpha": study.C3_ALPHA,
                "evaluated_origins": {
                    split: [utc_iso(start), utc_iso(end)]
                    for split, (start, end) in study.C3_PERIODS.items()
                },
            },
        },
        evaluation={
            "protocol": "docs/research_protocol.md section 2 (registered before running)",
            "selection_period": "validation (2018); test (2019) was inspected in earlier phases",
            "metrics": METRIC_DEFINITIONS,
            "calendar": _calendar_metadata("all models"),
            "bootstrap": (
                "circular block bootstrap over days, 7-day blocks, 2000 resamples, seed 42"
            ),
            "training_seconds": results["training_seconds"],
            "source_sha256": _source_hashes(),
        },
    )
    _write_json(output_dir / "run_metadata.json", metadata)

    c1 = results["c1"]
    print(
        f"C1: 2018 MAE gain of cap {study.C1_CAPS[1]}: "
        f"{c1['relative_2018_mae_gain_of_higher_cap']:.2%} -> cap {c1['chosen_cap']}"
    )
    for split, period in results["c2"]["periods"].items():
        scores = period["comparison"]["common_sample"]
        diff = period["daily_mae_difference_b_minus_a_mw"]
        print(
            f"C2 {split:>10}: MAE A={_fmt(scores['lightgbm_a']['mae_mw'])} "
            f"B={_fmt(scores['lightgbm_b']['mae_mw'])} MW, B-A={_fmt(diff['estimate'])} "
            f"[{_fmt(diff['ci_low'])}, {_fmt(diff['ci_high'])}]"
        )
    for split, summary in results["c3"]["periods"].items():
        coverage = summary["coverage"]
        print(
            f"C3 {split:>10}: coverage {coverage['estimate']:.3f} "
            f"[{coverage['ci_low']:.3f}, {coverage['ci_high']:.3f}], mean width "
            f"{_fmt(summary['mean_width_mw']['estimate'])} MW"
        )
    print(f"outputs written to {output_dir}")
    return 0


def run_grid_study(period: str, output_dir: Path, workers: int | None) -> int:
    try:
        from gridpulse import grid_study as study
        from gridpulse.grid import NETWORK_CODE
    except ImportError as error:
        raise RuntimeError(f"{error}; install the grid extra: uv sync --all-extras") from error

    started = datetime.now(UTC)
    results = study.run_grid_study(period, output_dir / "physics_cache", workers)
    output_dir.mkdir(parents=True, exist_ok=True)
    results["outcomes"].to_csv(output_dir / f"{period}_daily_outcomes.csv", index=False)
    _write_json(output_dir / f"{period}_summary.json", results["summary"])
    _write_json(output_dir / f"{period}_calibration.json", results["calibration"])
    if results["storage_sensitivity"] is not None:
        _write_json(
            output_dir / f"{period}_storage_sensitivity.json", results["storage_sensitivity"]
        )
    with open(output_dir / f"{period}_passports.jsonl", "w") as file:
        for passport in results["passports"]:
            file.write(json.dumps(passport) + "\n")
    start, end = study.PERIODS[period]
    metadata = {
        "gridpulse_version": version("gridpulse"),
        "run_started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "docs/research_protocol.md section 3 (registered before evaluation runs)",
        "period": period,
        "days_utc": {"start": utc_iso(start), "end_exclusive": utc_iso(end)},
        "source_sha256": _source_hashes(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{name: version(name) for name in ("numpy", "pandas", "pandapower", "simbench")},
        },
        "network": {
            "simbench_code": NETWORK_CODE,
            "modification": (
                "all storage units held at 0 MW, i.e. PV and load without battery dispatch "
                "(protocol s. 3.1, 3.6b); benchmark transformer tap made effective (s. 3.6b)"
            ),
            "limits": "benchmark bus min/max_vm_pu; line and trafo max_loading_percent",
            "solver": "pandapower AC Newton-Raphson, recycle of PQ injections, reset per day",
            "data_license": "SimBench data: ODbL 1.0 / DbCL; not redistributed",
        },
        "settings": {
            "cap_levels": study.CAP_LEVELS.tolist(),
            "static_cap": study.STATIC_CAP,
            "forecast": f"mean of previous {study.FORECAST_DAYS} days, same UTC quarter-hour",
            "scenario_window_days": study.WINDOW_DAYS,
            "alpha": study.ALPHA,
            "exploratory_alphas": list(study.EXPLORATORY_ALPHAS),
            "fallbacks": list(study.FALLBACKS),
            "bootstrap": (
                "circular block bootstrap over days, 7-day blocks, 2000 resamples, seed 42"
            ),
        },
    }
    metadata["physics_cache"] = results["physics_cache"]
    _write_json(output_dir / f"{period}_run_metadata.json", metadata)

    summary, calibration = results["summary"], results["calibration"]
    for policy in ("no_action", "static_70", "point", "risk", "selective_robust", "oracle"):
        totals = summary["totals"][policy]
        print(
            f"{period} {policy:<17} violation steps {totals['violation_steps']:6.0f}  "
            f"curtailed {totals['curtailed_mwh']:7.3f} MWh"
        )
    skill = calibration["brier_skill_score"]
    print(
        f"{period} BSS {skill['estimate']:.3f} [{skill['ci_low']:.3f}, {skill['ci_high']:.3f}], "
        f"deferred days {summary['h4_selective']['deferred_days']} of {summary['days']}"
    )
    print(f"outputs written to {output_dir}")
    return 0


def _json_safe(value):
    """Replace non-finite floats (an inf peak margin after a failed flow) by strings, so
    the output stays valid JSON."""
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item") and not hasattr(value, "__len__"):  # numpy scalar
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def run_dual_study(stage: str, output_dir: Path, workers: int | None, networks) -> int:
    try:
        from gridpulse import dual_study as study
    except ImportError as error:
        raise RuntimeError(f"{error}; install the grid extra: uv sync --all-extras") from error

    networks = list(networks or study.HOSTING_CAPACITY)
    unknown = sorted(set(networks) - set(study.HOSTING_CAPACITY))
    if unknown:
        raise ValueError(f"unregistered networks: {unknown}")
    started = datetime.now(UTC)
    cache_dir = output_dir / "physics_cache"
    if stage == "physics":
        provenance = study.compute_all_physics(cache_dir, networks, workers)
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(output_dir / "physics_provenance.json", provenance)
        print(f"physics cached in {cache_dir}")
        return 0
    if any(output_dir.glob("*_manifest.json")):
        raise RuntimeError(f"{output_dir} holds a guarded (Phase 6) study; use its own command")
    if stage == "evaluation" and any(output_dir.glob("evaluation_*")):
        raise RuntimeError(
            "evaluation outputs already exist; the protocol (s. 4.6) allows one evaluation run"
        )
    online = study.OnlineSettings()
    results = study.run_dual_study(stage, cache_dir, networks, online)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("summaries", "diagnostics", "materiality", "hypotheses"):
        if results[name] is not None:
            _write_json(output_dir / f"{stage}_{name}.json", _json_safe(results[name]))
    rows = pd.DataFrame(results["rows"])
    rows.insert(1, "date", (study.grid_study.FIRST_DAY + pd.to_timedelta(rows["day"], "D")).dt.date)
    rows.to_csv(output_dir / f"{stage}_daily_outcomes.csv", index=False)
    days = study.grid_study.period_days(stage)
    days = [d for d in days if study.FIRST_DECISION_DAY <= d <= study.LAST_DAY]
    first_day = study.grid_study.FIRST_DAY
    metadata = {
        "gridpulse_version": version("gridpulse"),
        "run_started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "docs/research_protocol.md section 4 with amendment 4A",
        "period": stage,
        "scored_days_utc": {
            "first": utc_iso(first_day + pd.Timedelta(days=days[0])),
            "last": utc_iso(first_day + pd.Timedelta(days=days[-1])),
            "count": len(days),
        },
        "development_tuning_days": "2016-02-05 .. 2016-06-30 (UTC days 35..181)",
        "confirmatory_networks": [c for c in networks if c != study.DEVELOPMENT_NETWORK],
        "development_network": study.DEVELOPMENT_NETWORK,
        "source_sha256": _source_hashes(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{name: version(name) for name in ("numpy", "pandas", "pandapower", "simbench")},
        },
        "networks": {
            code: {
                "pv_scale": study.pv_scale(code),
                "hosting_capacity": study.HOSTING_CAPACITY[code],
            }
            for code in networks
        },
        "physics_fingerprint": study.physics_fingerprint(),
        "model_variants": {name: asdict(v) for name, v in study.VARIANTS.items()},
        "ensemble": list(study.ENSEMBLE),
        "online_settings": asdict(online),
        "decision_settings": {
            "margin_scale": study.MARGIN_SCALE.tolist(),
            "replay_days": study.REPLAY_DAYS,
            "risk_max_count": study.RISK_MAX_COUNT,
            "point_margin_tau_grid": [float(study.TAU_GRID[0]), float(study.TAU_GRID[-1]), 0.01],
            "severe_margin": study.SEVERE_MARGIN,
            "long_run_steps": study.LONG_RUN_STEPS,
            "exploratory_betas": list(study.EXPLORATORY_BETAS),
            "material_change": study.MATERIAL_CHANGE,
            "pairs": [f"{a} - {b}" for a, b in study.PAIRS],
            "bootstrap": "circular block bootstrap over days, 7-day blocks, 2000 resamples, "
            "seed 42",
        },
        "data_license": "SimBench data: ODbL 1.0 / DbCL; not redistributed",
    }
    _write_json(output_dir / f"{stage}_run_metadata.json", metadata)
    for code in networks:
        totals = results["summaries"][code]["cells"]["forecast/nominal"]["totals"]
        print(
            code,
            " ".join(
                f"{p}={totals[p]['avoidable_violation_steps']:.0f}/{totals[p]['curtailed_mwh']:.2f}"
                for p in ("no_action", "static_dev", "scenario_robust", "replay_aci", "oracle")
            ),
        )
    print(f"outputs written to {output_dir}")
    return 0


def run_sense_study(stage: str, output_dir: Path, workers: int | None, networks) -> int:
    try:
        from gridpulse import dual_study, fullstate, sensing
    except ImportError as error:
        raise RuntimeError(f"{error}; install the grid extra: uv sync --all-extras") from error

    networks = list(networks or dual_study.HOSTING_CAPACITY)
    unknown = sorted(set(networks) - set(dual_study.HOSTING_CAPACITY))
    if unknown:
        raise ValueError(f"unregistered networks: {unknown}")
    workers = workers or 8
    cache_dir = output_dir / "fullstate_cache"
    if stage == "physics":
        days = list(range(dual_study.FIRST_DECISION_DAY, dual_study.LAST_DAY + 1))
        provenance = {
            f"{code}/{truth}": fullstate.compute_states(code, truth, days, cache_dir, workers)
            for code in networks
            for truth in fullstate.TRUTHS
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        _write_json(output_dir / "fullstate_provenance.json", provenance)
        print(f"full states cached in {cache_dir}")
        return 0
    if any(output_dir.glob("*_manifest.json")):
        raise RuntimeError(f"{output_dir} holds a guarded (Phase 6) study; use its own command")
    if stage == "evaluation" and any(output_dir.glob("evaluation_*")):
        raise RuntimeError(
            "evaluation outputs already exist; the protocol allows one evaluation run"
        )
    gate = None
    if stage == "evaluation":
        gate_file = output_dir / "development_se_gate.json"
        if not gate_file.exists():
            raise RuntimeError("run the development stage first (it fixes the SE gate)")
        gate = json.loads(gate_file.read_text())
    started = datetime.now(UTC)
    phase4_cache = Path("outputs/dual_study/physics_cache")
    output = sensing.run_study(stage, phase4_cache, cache_dir, networks, workers, gate)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / f"{stage}_results.json", _json_safe(output["results"]))
    _write_json(output_dir / f"{stage}_hypotheses.json", _json_safe(output["hypotheses"]))
    if "se_gate" in output:
        _write_json(output_dir / f"{stage}_se_gate.json", _json_safe(output["se_gate"]))
    metadata = {
        "gridpulse_version": version("gridpulse"),
        "run_started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "docs/phase5_protocol.md",
        "stage": stage,
        "networks": networks,
        "source_sha256": _source_hashes(),
        "phase5_protocol_sha256": hashlib.sha256(
            (Path(__file__).resolve().parents[2] / "docs" / "phase5_protocol.md").read_bytes()
        ).hexdigest(),
        "fullstate_fingerprint": fullstate.fingerprint(),
        "phase4_physics_fingerprint": dual_study.physics_fingerprint(),
        "conditions": {name: asdict(model) for name, model in sensing.CONDITIONS.items()},
        "primary_condition": sensing.PRIMARY,
        "budgets": list(sensing.BUDGETS),
        "rules": list(sensing.RULES),
        "random_seeds": len(sensing.RANDOM_SEEDS),
        "design_truths": list(sensing.DESIGN_TRUTHS),
        "coverage_min": sensing.COVERAGE_MIN,
        "consistency_thresholds": {
            "v_pu": sensing.CONSISTENCY_V,
            "q_fraction": sensing.CONSISTENCY_Q,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{name: version(name) for name in ("numpy", "pandas", "pandapower", "simbench")},
        },
        "data_license": "SimBench data: ODbL 1.0 / DbCL; not redistributed",
    }
    _write_json(output_dir / f"{stage}_run_metadata.json", metadata)
    print(json.dumps(_json_safe(output["hypotheses"]["P"]), indent=1))
    print(f"outputs written to {output_dir}")
    return 0


def run_noise_study(stage: str, output_dir: Path, workers: int | None, networks) -> int:
    """Phase 6 (docs/phase6_protocol.md): development, then freeze, then one evaluation.
    Each stage is guarded by `runguard`: no rerun, no stale or partial outputs, and the
    evaluation runs only with the code and protocol frozen after development."""
    try:
        from gridpulse import dual_study, noise_study, runguard
    except ImportError as error:
        raise RuntimeError(f"{error}; install the grid extra: uv sync --all-extras") from error

    networks = list(networks or dual_study.HOSTING_CAPACITY)
    unknown = sorted(set(networks) - set(dual_study.HOSTING_CAPACITY))
    if unknown:
        raise ValueError(f"unregistered networks: {unknown}")
    protocol = noise_study.PROTOCOL
    if stage == "freeze":
        record = runguard.freeze(output_dir, protocol)
        print(f"frozen at {record['frozen_utc']}: {len(record['code_sha256'])} hashes")
        return 0
    placements = None
    if stage == "evaluation":
        runguard.require_freeze(output_dir, protocol)
        development = json.loads((output_dir / "development_results.json").read_text())
        placements = development["placements"]
        if set(networks) != set(placements):
            raise ValueError("the evaluation must use the networks of the development stage")
    identity = {
        "study": "phase6-noise-study",
        "experiment": "CORRECTED (identity-based noise); exploratory replication on "
        "previously examined SimBench networks and 2016 profiles",
        "stage": stage,
        "networks": networks,
    }
    runguard.begin(output_dir, stage, identity, protocol)
    started = datetime.now(UTC)
    output = noise_study.run_study(
        stage, Path("outputs/dual_study/physics_cache"),
        Path("outputs/sense_study/fullstate_cache"), networks, workers or 3, placements,
    )  # fmt: skip
    written = [output_dir / f"{stage}_results.json", output_dir / f"{stage}_hypotheses.json"]
    _write_json(written[0], _json_safe(
        {"placements": output["placements"], "results": output["results"]}
    ))  # fmt: skip
    _write_json(written[1], _json_safe(output["hypotheses"]))
    metadata = {
        "gridpulse_version": version("gridpulse"),
        "run_started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": identity,
        "conditions": {name: asdict(m) for name, m in noise_study.CONDITIONS.items()},
        "primary_condition": noise_study.PRIMARY_CONDITION,
        "rules": {name: asdict(r) for name, r in noise_study.RULES.items()},
        "primary_rule": noise_study.PRIMARY_RULE,
        "chi2_alpha": noise_study.CHI2_ALPHA,
        "gross_error": {"vm_pu": noise_study.GROSS_VM, "loading": noise_study.GROSS_LOADING},
        "replications": [0, *noise_study.REPLICATIONS],
        "phase4_physics_fingerprint": dual_study.physics_fingerprint(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{
                name: version(name)
                for name in ("numpy", "pandas", "pandapower", "simbench", "scipy")
            },
        },
        "data_license": "SimBench data: ODbL 1.0 / DbCL; not redistributed",
    }
    path = output_dir / f"{stage}_run_metadata.json"
    _write_json(path, metadata)
    written.append(path)
    runguard.complete(output_dir, stage, written)
    print(json.dumps(_json_safe(output["hypotheses"]), indent=1)[:4000])
    print(f"outputs written to {output_dir}")
    return 0


def run_demonstrator(network: str, truth: str, output_dir: Path) -> int:
    """Phase 7 exploratory demonstrator (docs/phase7_results.md s. 12): a static HTML page."""
    try:
        from gridpulse import demonstrator, dual_study, noise_study
    except ImportError as error:
        raise RuntimeError(f"{error}; install the grid extra: uv sync --all-extras") from error

    if network not in dual_study.HOSTING_CAPACITY:
        raise ValueError(f"unregistered network: {network}")
    truths = ("nominal", *noise_study.MISMATCH)
    if truth not in truths:
        raise ValueError(f"truth {truth} not in the Phase 7 study; one of {list(truths)}")
    if not demonstrator.FROZEN.exists():
        raise RuntimeError(f"{demonstrator.FROZEN} missing: run the Phase 7 evaluation first")
    path = demonstrator.write(network, truth, output_dir)
    print(f"demonstrator page written to {path} (exploratory; synthetic benchmark data)")
    return 0


def run_margin_study(stage: str, output_dir: Path, workers: int | None, networks) -> int:
    """Phase 7 (docs/phase7_protocol.md): development, freeze, then one evaluation, guarded
    by `runguard` as Phase 6. Placements are the frozen Phase 6 development design."""
    try:
        from gridpulse import dual_study, margin_study, runguard
    except ImportError as error:
        raise RuntimeError(f"{error}; install the grid extra: uv sync --all-extras") from error

    networks = list(networks or dual_study.HOSTING_CAPACITY)
    unknown = sorted(set(networks) - set(dual_study.HOSTING_CAPACITY))
    if unknown:
        raise ValueError(f"unregistered networks: {unknown}")
    if stage != "freeze" and not set(networks) - {dual_study.DEVELOPMENT_NETWORK}:
        raise ValueError("the hypotheses need at least one network besides the development one")
    protocol = margin_study.PROTOCOL
    if stage == "freeze":
        record = runguard.freeze(output_dir, protocol)
        print(f"frozen at {record['frozen_utc']}: {len(record['code_sha256'])} hashes")
        return 0
    if stage == "evaluation":
        runguard.require_freeze(output_dir, protocol)
    design = Path("outputs/noise_study/development_results.json")
    placements = json.loads(design.read_text())["placements"]
    identity = {
        "study": "phase7-margin-study",
        "experiment": "continuous model-residual correction vs binary alarms; exploratory "
        "replication on previously examined SimBench networks and 2016 profiles",
        "stage": stage,
        "networks": networks,
        "placements_source": str(design),
        "placements_sha256": runguard.sha256(design),
    }
    runguard.begin(output_dir, stage, identity, protocol)
    started = datetime.now(UTC)
    output = margin_study.run_study(
        stage, Path("outputs/dual_study/physics_cache"),
        Path("outputs/sense_study/fullstate_cache"), networks, workers or 3, placements,
    )  # fmt: skip
    written = [output_dir / f"{stage}_results.json", output_dir / f"{stage}_hypotheses.json"]
    _write_json(written[0], _json_safe(output["results"]))
    _write_json(written[1], _json_safe(output["hypotheses"]))
    metadata = {
        "gridpulse_version": version("gridpulse"),
        "run_started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "identity": identity,
        "plan": [list(row) for row in margin_study.PLAN],
        "corrector_defaults": asdict(margin_study.mg.CorrectorSettings()),
        "conditions": {name: asdict(m) for name, m in margin_study.CONDITIONS.items()},
        "phase4_physics_fingerprint": dual_study.physics_fingerprint(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            **{
                name: version(name)
                for name in ("numpy", "pandas", "pandapower", "simbench", "scipy")
            },
        },
        "data_license": "SimBench data: ODbL 1.0 / DbCL; not redistributed",
    }
    path = output_dir / f"{stage}_run_metadata.json"
    _write_json(path, metadata)
    written.append(path)
    runguard.complete(output_dir, stage, written)
    print(json.dumps(_json_safe(output["hypotheses"]), indent=1)[:3000])
    print(f"outputs written to {output_dir}")
    return 0


def _calendar_metadata(models: str) -> dict:
    return {
        "timezone": LOCAL_TIMEZONE,
        "holiday_definition": "nationwide statutory public holidays in Germany",
        "holiday_source": HOLIDAY_SOURCE,
        "holiday_dates": {
            date.strftime("%Y-%m-%d"): name for date, name in NATIONAL_HOLIDAYS.items()
        },
        "coverage_local_dates": [d.strftime("%Y-%m-%d") for d in CALENDAR_COVERAGE],
        "classification": (
            "A UTC timestamp is a holiday if its Europe/Berlin local calendar date is "
            "in holiday_dates. Categories combine the target and the weekly reference "
            f"and are shared by {models}. Labels are used for analysis only."
        ),
    }


def _source_hashes() -> dict:
    """SHA-256 of the registered protocol (if present) and of every package source file,
    so a run can be tied to the exact code and protocol text it used."""
    import hashlib

    files = sorted(Path(__file__).parent.glob("*.py"))
    protocol = Path(__file__).resolve().parents[2] / "docs" / "research_protocol.md"
    if protocol.exists():
        files.append(protocol)
    return {
        (file.name if file != protocol else "docs/research_protocol.md"): hashlib.sha256(
            file.read_bytes()
        ).hexdigest()
        for file in files
    }


def _first_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    return frame[[column, *frame.columns.drop(column)]]


def _fmt(value: float | None, decimals: int = 1) -> str:
    return "n/a" if value is None else f"{value:.{decimals}f}"


def _run_metadata(started: datetime, report: dict, *, models: dict, evaluation: dict) -> dict:
    return {
        "gridpulse_version": version("gridpulse"),
        "run_started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
            "numpy": version("numpy"),
            "pandas": version("pandas"),
        },
        "dataset": {
            "official": DATASET,
            "local_file": report["file"],
            "timestamp_column": TIMESTAMP_COLUMN,
            "target_column": TARGET_COLUMN,
            "target_unit": TARGET_UNIT,
        },
        "time_convention": (
            "Timezone-aware UTC throughout; each timestamp is the start of its hourly interval."
        ),
        "processing": [
            "Read only the timestamp and target columns.",
            f"Dropped observations from {utc_iso(RESERVED_FROM)} onward (reserved period) "
            "before any check, statistic or forecast.",
            "Placed source rows on a complete hourly UTC grid; absent timestamps and "
            "non-finite values are unavailable (NaN). No filling, clipping or interpolation.",
        ],
        "task": {
            "forecast_origin": "00:00 UTC, once per day",
            "horizon_hours": HORIZON_HOURS,
            "lead_definition": "lead h predicts the interval starting at origin + (h - 1) hours",
            "information_rule": "only observations whose interval starts before the origin",
        },
        **models,
        "splits": {
            name: {"start_utc": utc_iso(start), "end_exclusive_utc": utc_iso(end)}
            for name, (start, end) in SPLITS.items()
        },
        "reserved_from_utc": utc_iso(RESERVED_FROM),
        "evaluated_splits": list(EVALUATED_SPLITS),
        **evaluation,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gridpulse", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser(
        "validate", help="validate a local OPSD 60-minute CSV and print a data-quality report"
    )
    validate.add_argument("--input", type=Path, required=True, help="path to the CSV file")

    baseline = commands.add_parser(
        "baseline", help="evaluate the weekly seasonal naive baseline on validation and test"
    )
    baseline.add_argument("--input", type=Path, required=True, help="path to the CSV file")
    baseline.add_argument(
        "--output-dir", type=Path, required=True, help="directory for reports and predictions"
    )

    comparison = commands.add_parser(
        "compare",
        help="compare daily and weekly seasonal naive on identical pairs, with calendar analysis",
    )
    comparison.add_argument("--input", type=Path, required=True, help="path to the CSV file")
    comparison.add_argument(
        "--output-dir", type=Path, required=True, help="directory for comparison outputs"
    )

    lightgbm = commands.add_parser(
        "train-lightgbm",
        help="train LightGBM on 2015-2017 (early stopping on 2018) and compare it with both "
        "baselines on identical pairs",
    )
    lightgbm.add_argument("--input", type=Path, required=True, help="path to the CSV file")
    lightgbm.add_argument(
        "--output-dir", type=Path, required=True, help="directory for model and outputs"
    )

    study = commands.add_parser(
        "forecast-study",
        help="Track 1 experiments C1-C3: boosting cap, holiday flags, rolling intervals",
    )
    study.add_argument("--input", type=Path, required=True, help="path to the CSV file")
    study.add_argument("--output-dir", type=Path, required=True, help="directory for outputs")

    grid = commands.add_parser(
        "grid-study",
        help="Track 2: PV-cap decisions on a SimBench LV grid (development or evaluation period)",
    )
    grid.add_argument("--period", choices=("development", "evaluation"), required=True)
    grid.add_argument("--output-dir", type=Path, required=True, help="directory for outputs")
    grid.add_argument("--workers", type=int, default=None, help="parallel power-flow workers")

    dual = commands.add_parser(
        "dual-study",
        help="Phase 4: PV-cap decisions under forecast and physical-model uncertainty "
        "(physics cache, then development or evaluation decisions)",
    )
    dual.add_argument("--stage", choices=("physics", "development", "evaluation"), required=True)
    dual.add_argument("--output-dir", type=Path, required=True, help="directory for outputs")
    dual.add_argument("--workers", type=int, default=None, help="parallel power-flow workers")
    dual.add_argument("--networks", nargs="*", default=None, help="subset of registered networks")

    sense = commands.add_parser(
        "sense-study",
        help="Phase 5: decisions under limited measurement availability "
        "(full-state physics, then development or evaluation)",
    )
    sense.add_argument("--stage", choices=("physics", "development", "evaluation"), required=True)
    sense.add_argument("--output-dir", type=Path, required=True, help="directory for outputs")
    sense.add_argument("--workers", type=int, default=None, help="parallel power-flow workers")
    sense.add_argument("--networks", nargs="*", default=None, help="subset of registered networks")

    noise = commands.add_parser(
        "noise-study",
        help="Phase 6: noise-aware feedback, measurement integrity and sensor value "
        "(development, freeze, then one evaluation; reuses the Phase 4/5 physics caches)",
    )
    noise.add_argument("--stage", choices=("development", "freeze", "evaluation"), required=True)
    noise.add_argument("--output-dir", type=Path, required=True, help="directory for outputs")
    noise.add_argument("--workers", type=int, default=None, help="parallel workers (default 3)")
    noise.add_argument("--networks", nargs="*", default=None, help="subset of registered networks")

    margin = commands.add_parser(
        "margin-study",
        help="Phase 7: continuous model-residual correction vs binary alarm feedback "
        "(development, freeze, then one evaluation; reuses the Phase 4/5 physics caches)",
    )
    margin.add_argument("--stage", choices=("development", "freeze", "evaluation"), required=True)
    margin.add_argument("--output-dir", type=Path, required=True, help="directory for outputs")
    margin.add_argument("--workers", type=int, default=None, help="parallel workers (default 3)")
    margin.add_argument("--networks", nargs="*", default=None, help="subset of registered networks")

    demo = commands.add_parser(
        "demonstrate",
        help="Phase 7 exploratory demonstrator: one static HTML page per network and truth, "
        "re-running three frozen policies (needs the frozen Phase 7 evaluation outputs)",
    )
    demo.add_argument("--network", default="1-LV-semiurb4--2-sw", help="registered network")
    demo.add_argument("--truth", default="tap_raise_lv", help="true model (nominal or mismatch)")
    demo.add_argument("--output-dir", type=Path, required=True, help="directory for the page")

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return run_validate(args.input)
        if args.command == "baseline":
            return run_baseline(args.input, args.output_dir)
        if args.command == "compare":
            return run_compare(args.input, args.output_dir)
        if args.command == "forecast-study":
            return run_forecast_study(args.input, args.output_dir)
        if args.command == "grid-study":
            return run_grid_study(args.period, args.output_dir, args.workers)
        if args.command == "dual-study":
            return run_dual_study(args.stage, args.output_dir, args.workers, args.networks)
        if args.command == "sense-study":
            return run_sense_study(args.stage, args.output_dir, args.workers, args.networks)
        if args.command == "noise-study":
            return run_noise_study(args.stage, args.output_dir, args.workers, args.networks)
        if args.command == "margin-study":
            return run_margin_study(args.stage, args.output_dir, args.workers, args.networks)
        if args.command == "demonstrate":
            return run_demonstrator(args.network, args.truth, args.output_dir)
        return run_train_lightgbm(args.input, args.output_dir)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
