"""Track 1 forecasting experiments C1-C3, as registered in docs/research_protocol.md (s. 2).

C1 compares two boosting caps on 2018, C2 adds known-ahead holiday flags, C3 evaluates
rolling split-conformal day-ahead intervals. 2018 is the only period used for choices.
"""

from __future__ import annotations

from time import perf_counter

import numpy as np
import pandas as pd

from gridpulse import model
from gridpulse.baseline import (
    DAILY_NAIVE,
    SEASONAL_NAIVE_BASELINES,
    WEEKLY_NAIVE,
    daily_origins,
    seasonal_naive_forecast,
)
from gridpulse.calendar_analysis import HOLIDAY_CATEGORIES, annotate_calendar, calendar_breakdown
from gridpulse.data import SPLITS
from gridpulse.evaluation import (
    COMMON_VALID,
    align_pairs,
    attach_actuals,
    compare_with_baselines,
    summarize,
)
from gridpulse.features import FEATURES, HOLIDAY_FEATURES, feature_table, with_holiday_flags
from gridpulse.uncertainty import block_bootstrap_mean, rolling_conformal_halfwidths

C1_CAPS = (500, 3000)
C1_MIN_RELATIVE_GAIN = 0.01
ARM_A, ARM_B = "lightgbm_a", "lightgbm_b"
C2_FEATURES = {ARM_A: FEATURES, ARM_B: FEATURES + HOLIDAY_FEATURES}
C3_WINDOW_DAYS = 56
C3_ALPHA = 0.10
# Evaluated origin ranges [start, end): 2018 starts once a full 56-day window of
# out-of-sample residuals exists.
C3_PERIODS = {
    "validation": (pd.Timestamp("2018-02-26", tz="UTC"), pd.Timestamp("2019-01-01", tz="UTC")),
    "test": (pd.Timestamp("2019-01-01", tz="UTC"), pd.Timestamp("2020-01-01", tz="UTC")),
}
EVALUATED = ("validation", "test")
KEYS = ["forecast_origin_utc", "target_timestamp_utc", "lead_hours"]


def run_forecast_study(load: pd.Series) -> dict:
    """Run C1-C3 on the validated hourly load (2020 already removed)."""
    TIMINGS.clear()
    origins = {split: daily_origins(*SPLITS[split]) for split in ("train", *EVALUATED)}
    tables = {
        split: with_holiday_flags(feature_table(load, days)) for split, days in origins.items()
    }

    c1, boosters = _boosting_cap(tables, load)
    cap = c1["chosen_cap"]
    boosters = {ARM_A: boosters[cap]}
    boosters[ARM_B], info_b = _fit(tables, C2_FEATURES[ARM_B], cap)

    c2 = {"cap": cap, "training": {ARM_B: info_b}, "periods": {}}
    annotated, breakdowns = {}, []
    for split in EVALUATED:
        pairs = {
            name: attach_actuals(
                seasonal_naive_forecast(load, origins[split], SEASONAL_NAIVE_BASELINES[name]),
                load,
            )
            for name in (WEEKLY_NAIVE, DAILY_NAIVE)
        }
        for arm, booster in boosters.items():
            pairs[arm] = attach_actuals(_forecasts(booster, tables[split]), load)
        annotated[split] = annotate_calendar(align_pairs(pairs))
        c2["periods"][split] = {
            "comparison": compare_with_baselines(
                annotated[split], ARM_B, [WEEKLY_NAIVE, DAILY_NAIVE, ARM_A]
            ),
            "daily_mae_difference_b_minus_a_mw": block_bootstrap_mean(
                _daily_mae_difference(annotated[split], ARM_B, ARM_A)
            ),
        }
        breakdowns.append(
            calendar_breakdown(
                annotated[split], (WEEKLY_NAIVE, DAILY_NAIVE, ARM_A, ARM_B), (ARM_B, ARM_A)
            ).assign(period=split)
        )
    validation_mae = {
        arm: c2["periods"]["validation"]["comparison"]["common_sample"][arm]["mae_mw"]
        for arm in boosters
    }
    selected = ARM_B if validation_mae[ARM_B] < validation_mae[ARM_A] else ARM_A
    c2["selected_for_c3"] = selected
    c2["selection_rule"] = "lightgbm_b if its 2018 common-sample MAE < lightgbm_a's"

    intervals = _rolling_intervals(annotated, selected, tables)
    c3 = {
        "model": selected,
        "window_days": C3_WINDOW_DAYS,
        "alpha": C3_ALPHA,
        "periods": {
            split: _interval_summary(intervals[intervals["period"] == split]) for split in EVALUATED
        },
    }
    return {
        "training_seconds": dict(TIMINGS),
        "c1": c1,
        "c2": c2,
        "c2_calendar": pd.concat(breakdowns, ignore_index=True),
        "c3": c3,
        "c3_breakdown": _interval_breakdown(intervals),
        "c3_intervals": intervals,
    }


TIMINGS: dict[str, float] = {}  # wall-clock training times, reported in run metadata only


def _fit(tables: dict, features: tuple[str, ...], cap: int):
    start = perf_counter()
    booster, info = model.train(tables["train"], tables["validation"], features, cap)
    TIMINGS[f"{'+'.join(features[5:]) or 'base'} features, cap {cap}"] = round(
        perf_counter() - start, 2
    )
    return booster, info


def _forecasts(booster, rows: pd.DataFrame) -> pd.DataFrame:
    return rows[KEYS].assign(predicted_load_mw=model.predict(booster, rows))


def _boosting_cap(tables: dict, load: pd.Series) -> tuple[dict, dict]:
    arms, boosters = {}, {}
    for cap in C1_CAPS:
        boosters[cap], info = _fit(tables, FEATURES, cap)
        validation = attach_actuals(_forecasts(boosters[cap], tables["validation"]), load)
        arms[str(cap)] = {"training": info, "validation_2018": summarize(validation)["overall"]}
    low, high = (arms[str(cap)]["validation_2018"]["mae_mw"] for cap in C1_CAPS)
    gain = 1 - high / low
    return {
        "arms": arms,
        "relative_2018_mae_gain_of_higher_cap": gain,
        "decision_rule": f"adopt cap {C1_CAPS[1]} only if its 2018 MAE is at least "
        f"{C1_MIN_RELATIVE_GAIN:.0%} lower than cap {C1_CAPS[0]}",
        "chosen_cap": C1_CAPS[1] if gain >= C1_MIN_RELATIVE_GAIN else C1_CAPS[0],
    }, boosters


def _daily_mae_difference(annotated: pd.DataFrame, model_a: str, model_b: str) -> np.ndarray:
    common = annotated[annotated["comparison_status"] == COMMON_VALID]
    errors = {
        name: (common["actual_load_mw"] - common[f"{name}_predicted_load_mw"]).abs()
        for name in (model_a, model_b)
    }
    days = common["forecast_origin_utc"]
    return (errors[model_a].groupby(days).mean() - errors[model_b].groupby(days).mean()).to_numpy()


def _rolling_intervals(annotated: dict, selected: str, tables: dict) -> pd.DataFrame:
    """Out-of-sample rows (2018-2019) with rolling-conformal intervals and coverage flags."""
    rows = pd.concat(
        [annotated[split].assign(period=split) for split in EVALUATED], ignore_index=True
    )
    prediction = rows[f"{selected}_predicted_load_mw"]
    rows = rows[KEYS + ["period", "actual_load_mw", "holiday_category"]].assign(
        predicted_load_mw=prediction,
        abs_error=(rows["actual_load_mw"] - prediction).abs(),
    )
    halfwidths = rolling_conformal_halfwidths(
        rows[["forecast_origin_utc", "lead_hours", "abs_error"]], C3_WINDOW_DAYS, C3_ALPHA
    )
    rows = rows.merge(halfwidths, on=["forecast_origin_utc", "lead_hours"], validate="1:1")
    local_months = pd.concat(
        [tables[split][KEYS + ["target_local_month"]] for split in EVALUATED], ignore_index=True
    )
    rows = rows.merge(local_months, on=KEYS, validate="1:1")
    in_period = pd.Series(False, index=rows.index)
    for split, (start, end) in C3_PERIODS.items():
        origin = rows["forecast_origin_utc"]
        in_period |= (rows["period"] == split) & (origin >= start) & (origin < end)
    rows = rows[in_period].reset_index(drop=True)
    evaluable = (
        np.isfinite(rows["abs_error"])
        & np.isfinite(rows["halfwidth_mw"])
        & (rows["n_calibration"] == C3_WINDOW_DAYS)
    )
    return rows.assign(
        lower_mw=rows["predicted_load_mw"] - rows["halfwidth_mw"],
        upper_mw=rows["predicted_load_mw"] + rows["halfwidth_mw"],
        evaluable=evaluable,
        covered=evaluable & (rows["abs_error"] <= rows["halfwidth_mw"]),
    )


def _interval_summary(rows: pd.DataFrame) -> dict:
    used = rows[rows["evaluable"]]
    by_day = used.groupby("forecast_origin_utc")
    return {
        "n_rows": len(rows),
        "n_evaluable": len(used),
        "nominal_coverage": 1 - C3_ALPHA,
        "coverage": block_bootstrap_mean(by_day["covered"].mean().to_numpy()),
        "mean_width_mw": block_bootstrap_mean(2 * by_day["halfwidth_mw"].mean().to_numpy()),
        "share_of_days_all_hours_covered": float(by_day["covered"].all().mean()),
    }


def _interval_breakdown(intervals: pd.DataFrame) -> pd.DataFrame:
    used = intervals[intervals["evaluable"]]
    groupings = {
        "lead_hours": None,
        "holiday_category": HOLIDAY_CATEGORIES,
        "target_local_month": None,
    }
    rows = []
    for period in EVALUATED:
        subset = used[used["period"] == period]
        for grouping, groups in groupings.items():
            for group in groups or sorted(subset[grouping].unique()):
                cell = subset[subset[grouping] == group]
                rows.append(
                    {
                        "period": period,
                        "grouping": grouping,
                        "group": group,
                        "n_rows": len(cell),
                        "n_origins": cell["forecast_origin_utc"].nunique(),
                        "coverage": cell["covered"].mean() if len(cell) else None,
                        "mean_width_mw": 2 * cell["halfwidth_mw"].mean() if len(cell) else None,
                    }
                )
    return pd.DataFrame(rows)
