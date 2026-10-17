"""Command-line entry point: `python -m gridpulse {validate,baseline,compare,train-lightgbm}`."""

from __future__ import annotations

import argparse
import json
import platform
import sys
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
    path.write_text(json.dumps(content, indent=2) + "\n")


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

    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return run_validate(args.input)
        if args.command == "baseline":
            return run_baseline(args.input, args.output_dir)
        if args.command == "compare":
            return run_compare(args.input, args.output_dir)
        return run_train_lightgbm(args.input, args.output_dir)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
