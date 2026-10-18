"""Track 2: day-ahead PV-cap decisions on a SimBench LV grid (docs/research_protocol.md, s. 3).

Two stages:

1. Physics: for every day, AC power flows for the realised injections, the point forecast
   and 28 residual scenarios, each under every cap level. Results are cached per day.
2. Decisions: every policy is a rule over those cached results, so all policies see the
   same physics, the same information and the same action set.

Information timing: the forecast and the scenarios for day d use only days before d. The
realised set of day d is used for the oracle and for scoring, never for a decision.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import math
import os
from concurrent.futures import ProcessPoolExecutor
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

from gridpulse import grid
from gridpulse.grid import (
    MARGINS,
    NETWORK_CODE,
    STEP_HOURS,
    GridSolver,
    absolute_profiles,
    cap_pv,
    is_violation,
    load_network,
)
from gridpulse.uncertainty import block_bootstrap, block_bootstrap_mean

STEPS = 96
CAP_LEVELS = np.round(np.linspace(1.0, 0.0, 11), 2)  # index 0 = no cap
STATIC_CAP = 0.7
FORECAST_DAYS = 7
WINDOW_DAYS = 28
ALPHA = 0.05
EXPLORATORY_ALPHAS = (0.01, 0.10)
REALISED, FORECAST = 0, 1  # injection sets; 2 onward are the scenarios
FIRST_DAY = pd.Timestamp("2016-01-01", tz="UTC")  # first complete UTC day of the profiles
FIRST_DECISION_DAY = FORECAST_DAYS + WINDOW_DAYS  # first day with a full residual window
# [start, end) in UTC days. The profiles end at 2016-12-31 22:45 UTC, so the last complete
# UTC day is 2016-12-30.
PERIODS = {
    "development": (pd.Timestamp("2016-02-05", tz="UTC"), pd.Timestamp("2016-07-01", tz="UTC")),
    "evaluation": (pd.Timestamp("2016-07-01", tz="UTC"), pd.Timestamp("2016-12-31", tz="UTC")),
}
FALLBACKS = ("robust", "static_70", "no_action")
RELIABILITY_BINS = (0.0, 0.1, 0.3, 0.6, 1.0)  # plus a separate bin for exactly 0
PROFILE_KEYS = ("load_p_mw", "load_q_mvar", "sgen_p_mw")  # storage is held at 0 MW


# --- Data, forecast and scenarios ----------------------------------------------------


def daily_arrays(profiles: dict[str, pd.DataFrame]) -> dict[str, np.ndarray]:
    """Complete UTC days (2016-01-01 .. 2016-12-30) as arrays of days x 96 x elements."""
    index = profiles["sgen_p_mw"].index
    start = index.get_loc(FIRST_DAY)
    n_days = (len(index) - start) // STEPS
    return {
        name: profiles[name].to_numpy()[start : start + n_days * STEPS].reshape(n_days, STEPS, -1)
        for name in PROFILE_KEYS
    }


def forecast(values: np.ndarray, day: int) -> np.ndarray:
    """Mean of the same UTC quarter-hour over the previous FORECAST_DAYS days."""
    if day < FORECAST_DAYS:
        raise ValueError(f"day {day} has fewer than {FORECAST_DAYS} previous days")
    return values[day - FORECAST_DAYS : day].mean(axis=0)


def scenarios(values: np.ndarray, day: int) -> np.ndarray:
    """Forecast for `day` plus the forecaster's residual on each of the previous
    WINDOW_DAYS days (whole days, all elements jointly). Uses only days before `day`."""
    if day < FIRST_DECISION_DAY:
        raise ValueError(f"day {day} has no full {WINDOW_DAYS}-day residual window")
    residuals = np.stack([values[j] - forecast(values, j) for j in range(day - WINDOW_DAYS, day)])
    return forecast(values, day) + residuals


def injection_sets(arrays: dict[str, np.ndarray], day: int, pv_rating: np.ndarray) -> dict:
    """Realised, forecast and scenario injections of one day, each sets x 96 x elements."""
    sets = {}
    for name in PROFILE_KEYS:
        predicted = np.concatenate(
            [forecast(arrays[name], day)[None], scenarios(arrays[name], day)]
        )
        if name == "load_p_mw":
            predicted = np.maximum(predicted, 0.0)
        elif name == "sgen_p_mw":
            predicted = np.clip(predicted, 0.0, pv_rating)
        sets[name] = np.concatenate([arrays[name][day][None], predicted])
    return sets


# --- Physics stage -----------------------------------------------------------------


def day_physics(solver: GridSolver, sets: dict, storage_mw: np.ndarray) -> np.ndarray:
    """Margins (sets x 96 x cap levels x MARGINS) of every injection set under every cap.

    The solver restarts from scratch for each day, so results do not depend on the order
    in which days are computed. A cap that does not bind reproduces the uncapped flow.
    """
    solver.reset()
    rating = solver.pv_rating_mw
    n_sets = sets["sgen_p_mw"].shape[0]
    margins = np.empty((n_sets, STEPS, len(CAP_LEVELS), len(MARGINS)), dtype=np.float32)
    for s in range(n_sets):
        for t in range(STEPS):
            load_p, load_q = sets["load_p_mw"][s, t], sets["load_q_mvar"][s, t]
            available = sets["sgen_p_mw"][s, t]
            margins[s, t, 0] = solver.solve(load_p, load_q, available, storage_mw)
            for level, cap in enumerate(CAP_LEVELS[1:], start=1):
                if np.all(available <= cap * rating):
                    margins[s, t, level] = margins[s, t, 0]
                else:
                    capped = cap_pv(available, rating, cap)
                    margins[s, t, level] = solver.solve(load_p, load_q, capped, storage_mw)
    return margins


_WORKER: dict = {}


def _init_worker() -> None:
    net = load_network()
    _WORKER["solver"] = GridSolver(net)
    _WORKER["arrays"] = daily_arrays(absolute_profiles(net))
    _WORKER["storage"] = np.zeros(len(net.storage))  # held at 0 MW (protocol s. 3.1)


def _compute_day(day: int) -> tuple[int, np.ndarray]:
    sets = injection_sets(_WORKER["arrays"], day, _WORKER["solver"].pv_rating_mw)
    return day, day_physics(_WORKER["solver"], sets, _WORKER["storage"])


def physics_fingerprint() -> str:
    """Hash of everything that determines the cached physics: the source of the physics
    functions, the relevant constants and the solver/data package versions."""
    sources = [
        inspect.getsource(obj)
        for obj in (
            grid.load_network,
            grid.absolute_profiles,
            grid.cap_pv,
            grid.GridSolver,
            daily_arrays,
            forecast,
            scenarios,
            injection_sets,
            day_physics,
            _init_worker,
        )
    ]
    settings = [repr(CAP_LEVELS.tolist()), STEPS, FORECAST_DAYS, WINDOW_DAYS, NETWORK_CODE]
    versions = [version(name) for name in ("numpy", "pandas", "pandapower", "simbench")]
    return hashlib.sha256(repr((sources, settings, versions)).encode()).hexdigest()


def physics_for(
    days: list[int], cache_dir: Path, workers: int
) -> tuple[dict[int, np.ndarray], dict]:
    """Physics of each day, read from the per-day cache or computed in parallel.

    The cache carries a manifest with the physics fingerprint and is refused if the code,
    settings or package versions differ. Files are written atomically.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = cache_dir / "manifest.json"
    fingerprint = physics_fingerprint()
    path = {day: cache_dir / f"day_{day:03d}.npy" for day in days}
    if manifest.exists():
        if json.loads(manifest.read_text())["fingerprint"] != fingerprint:
            raise ValueError(f"{cache_dir} was produced by different physics code; delete it")
    elif any(cache_dir.glob("day_*.npy")):
        raise ValueError(f"{cache_dir} has cached days but no manifest; delete it")
    else:
        manifest.write_text(json.dumps({"fingerprint": fingerprint}) + "\n")
    missing = [day for day in days if not path[day].exists()]
    if missing:
        with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
            for day, margins in pool.map(_compute_day, missing):
                temporary = path[day].with_name(path[day].stem + ".partial.npy")
                np.save(temporary, margins)
                temporary.replace(path[day])
    provenance = {
        "fingerprint": fingerprint,
        "days_computed": len(missing),
        "days_from_cache": len(days) - len(missing),
    }
    return {day: np.load(path[day]) for day in days}, provenance


# --- Decision stage ----------------------------------------------------------------


def first_level(acceptable: np.ndarray) -> np.ndarray:
    """Per step, the least curtailment (lowest level index) that is acceptable; if no level
    is acceptable, the deepest cap (k = 0)."""
    return np.where(acceptable.any(axis=1), acceptable.argmax(axis=1), len(CAP_LEVELS) - 1)


def day_risk(violations: np.ndarray) -> np.ndarray:
    """Share of scenarios violating any limit, per step and cap level (96 x levels)."""
    return violations[FORECAST + 1 :].mean(axis=0)


def schedules(violations: np.ndarray, alpha: float) -> dict[str, np.ndarray]:
    """Cap-level index per step for every non-selective policy."""
    risk = day_risk(violations)
    static = int(np.flatnonzero(np.isclose(CAP_LEVELS, STATIC_CAP))[0])
    return {
        "no_action": np.zeros(STEPS, dtype=int),
        "static_70": np.full(STEPS, static),
        "point": first_level(~violations[FORECAST]),
        "risk": first_level(risk <= alpha),
        "robust": first_level(risk == 0),
        "oracle": first_level(~violations[REALISED]),
    }


def poisson_upper_quantile(mean: float, level: float = 0.95) -> int:
    """Smallest q with P(Poisson(mean) <= q) >= level (computed in log space)."""
    if mean < 0:
        raise ValueError("mean must be non-negative")
    if mean == 0:
        return 0
    log_term = log_cumulative = -mean
    q = 0
    while log_cumulative < math.log(level):
        q += 1
        log_term += math.log(mean) - math.log(q)
        log_cumulative = np.logaddexp(log_cumulative, log_term)
    return q


def deferral_reasons(
    risk: np.ndarray, scenario_failed: bool, monitor: tuple[int, float], alpha: float
) -> list[str]:
    """Explicit day-level deferral criteria D1-D3 (protocol s. 3.4); empty = recommend."""
    reasons = []
    if (risk > alpha).all(axis=1).any():
        reasons.append("D1_no_feasible_cap")
    observed, expected = monitor
    if observed > poisson_upper_quantile(expected):
        reasons.append("D2_recent_violations_exceed_predicted")
    if scenario_failed:
        reasons.append("D3_scenario_power_flow_failed")
    return reasons


def outcome(realised: np.ndarray, levels: np.ndarray, available: np.ndarray, rating) -> dict:
    """Realised physics and curtailed energy of one day under a cap schedule."""
    margins = realised[np.arange(STEPS), levels]
    capped = np.stack([cap_pv(available[t], rating, CAP_LEVELS[levels[t]]) for t in range(STEPS)])
    violated = is_violation(margins)
    with np.errstate(invalid="ignore"):
        by_type = {name: int((margins[:, i] > 0).sum()) for i, name in enumerate(MARGINS)}
    return {
        "violation_steps": int(violated.sum()),
        "nonconverged_steps": int(np.isnan(margins).any(axis=1).sum()),
        **{f"{name}_steps": count for name, count in by_type.items()},
        "trafo_severity_pct_steps": float(np.nansum(np.maximum(margins[:, 3], 0))),
        "curtailed_mwh": float((available - capped).sum() * STEP_HOURS),
    }


def static_dev_level(physics: dict[int, np.ndarray], development_days: list[int]) -> int:
    """Amendment A1 baseline: the least curtailment whose realised violations over the
    development days are zero (else the fewest). Uses development data only."""
    counts = sum(is_violation(physics[day][REALISED]).sum(axis=0) for day in development_days)
    return int(np.flatnonzero(counts == 0)[0]) if (counts == 0).any() else int(counts.argmin())


def run_decisions(
    physics: dict[int, np.ndarray],
    arrays: dict,
    rating: np.ndarray,
    days: list[int],
    alpha: float,
    static_dev: int | None = None,
) -> tuple[pd.DataFrame, list[dict]]:
    """Apply every policy day by day in time order; returns per-day outcomes and the
    decision records (passports) of the selective policy. `static_dev` adds the
    exploratory amendment-A1 fixed cap."""
    history: dict[int, tuple[int, float]] = {}  # day -> (realised, predicted) on active steps
    rows, passports = [], []
    for day in sorted(physics):
        margins = physics[day]
        violations = is_violation(margins)
        risk = day_risk(violations)
        plan = schedules(violations, alpha)
        if static_dev is not None:
            plan["static_dev"] = np.full(STEPS, static_dev)
        window = [history[j] for j in range(day - WINDOW_DAYS, day) if j in history]
        monitor = (sum(v for v, _ in window), float(sum(e for _, e in window)))
        failed = bool(np.isnan(margins[FORECAST + 1 :]).any())
        reasons = deferral_reasons(risk, failed, monitor, alpha)

        active = risk[:, 0] > 0
        chosen = plan["risk"]
        realised_risk = violations[REALISED, np.arange(STEPS), chosen]
        history[day] = (
            int(realised_risk[active].sum()),
            float(risk[np.arange(STEPS), chosen][active].sum()),
        )
        if day not in days:
            continue
        available = arrays["sgen_p_mw"][day]
        record = {"day": day, "deferred": bool(reasons), "reasons": ";".join(reasons)}
        for name, levels in plan.items():
            for key, value in outcome(margins[REALISED], levels, available, rating).items():
                record[f"{name}__{key}"] = value
        for fallback in FALLBACKS:
            levels = plan[fallback] if reasons else chosen
            for key, value in outcome(margins[REALISED], levels, available, rating).items():
                record[f"selective_{fallback}__{key}"] = value
        record["risk__active_steps"] = int(active.sum())
        record["risk__active_violations"] = history[day][0]
        record["risk__active_expected"] = history[day][1]
        rows.append(record)
        passports.append(_passport(day, risk, plan, reasons, monitor, failed, alpha))
    return pd.DataFrame(rows), passports


def _passport(day, risk, plan, reasons, monitor, failed, alpha) -> dict:
    """Machine-readable evidence for the selective decision, built only from information
    available at the origin (no realised outcome of the day)."""
    chosen = plan["risk"]
    steps = np.arange(STEPS)
    return {
        "decision_id": f"{NETWORK_CODE}:{(FIRST_DAY + pd.Timedelta(days=day)).date()}",
        "forecast_origin_utc": (FIRST_DAY + pd.Timedelta(days=day)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "network": NETWORK_CODE,
        "network_modification": (
            "storage held at 0 MW (PV and load without battery dispatch, protocol s. 3.1/3.6b); "
            "benchmark transformer tap made effective (s. 3.6b)"
        ),
        "forecast_model": f"mean of previous {FORECAST_DAYS} days, same UTC quarter-hour",
        "uncertainty": f"{WINDOW_DAYS} whole-day residual scenarios from days d-28..d-1",
        "horizon_steps": STEPS,
        "constraints_checked": "bus min/max_vm_pu, line and trafo max_loading_percent",
        "risk_threshold_alpha": alpha,
        "max_step_risk_no_action": float(risk[:, 0].max()),
        "expected_violation_steps_no_action": float(risk[:, 0].sum()),
        "expected_violation_steps_recommended": float(risk[steps, chosen].sum()),
        "capped_steps_recommended": int((chosen > 0).sum()),
        "deepest_cap_recommended": float(CAP_LEVELS[chosen.max()]),
        "calibration_monitor": {
            "window_days": WINDOW_DAYS,
            "observed_violations_on_active_steps": monitor[0],
            "predicted_violations_on_active_steps": monitor[1],
            "poisson_95_upper": poisson_upper_quantile(monitor[1]),
        },
        "scenario_power_flow_failed": failed,
        "decision": "defer" if reasons else "recommend",
        "deferral_reasons": reasons,
        "fallback_if_deferred": "robust (primary); static_70 and no_action also evaluated",
        "limitations": [
            "simulation of a benchmark grid, not a measured feeder",
            "risk is the share of residual scenarios, not a certified probability",
            "deferral is a workflow outcome; physical safety depends on the fallback",
        ],
    }


# --- Calibration and statistics ----------------------------------------------------


def calibration(physics: dict[int, np.ndarray], reference: dict[int, np.ndarray], days) -> dict:
    """Brier score of the no-action risk against realised no-action violations, its skill
    against the rolling 28-day frequency reference, a reliability table and the ECE."""
    risk, observed, ref, day_of = [], [], [], []
    for day in days:
        violations = is_violation(physics[day][:, :, 0])
        risk.append(violations[FORECAST + 1 :].mean(axis=0))
        observed.append(violations[REALISED].astype(float))
        previous = [reference[j] for j in range(day - WINDOW_DAYS, day)]
        ref.append(np.mean(previous, axis=0))
        day_of.append(np.full(STEPS, day))
    risk, observed, ref = (np.concatenate(x) for x in (risk, observed, ref))
    per_day = np.stack(
        [
            ((risk - observed) ** 2).reshape(-1, STEPS).sum(axis=1),
            ((ref - observed) ** 2).reshape(-1, STEPS).sum(axis=1),
        ],
        axis=1,
    )
    skill = block_bootstrap(per_day, lambda x: 1 - x[:, 0].sum() / x[:, 1].sum())
    bins = []
    edges = RELIABILITY_BINS
    groups = [("0", risk == 0)] + [
        (f"({lo}, {hi}]", (risk > lo) & (risk <= hi))
        for lo, hi in zip(edges, edges[1:], strict=False)
    ]
    ece = 0.0
    for label, mask in groups:
        n = int(mask.sum())
        mean_risk = float(risk[mask].mean()) if n else None
        frequency = float(observed[mask].mean()) if n else None
        if n:
            ece += n / len(risk) * abs(mean_risk - frequency)
        bins.append(
            {"bin": label, "n_steps": n, "mean_risk": mean_risk, "observed_frequency": frequency}
        )
    return {
        "n_steps": len(risk),
        "observed_violation_rate": float(observed.mean()),
        "mean_predicted_risk": float(risk.mean()),
        "brier": float(((risk - observed) ** 2).mean()),
        "brier_reference": float(((ref - observed) ** 2).mean()),
        "brier_skill_score": skill,
        "ece": ece,
        "reliability": bins,
    }


def realised_no_action(arrays: dict, days: list[int]) -> dict[int, np.ndarray]:
    """Realised no-action violation indicator per step, for the calibration reference."""
    net = load_network()
    solver = GridSolver(net)
    storage = np.zeros(len(net.storage))
    result = {}
    for day in days:
        solver.reset()
        margins = np.array(
            [
                solver.solve(*(arrays[name][day, t] for name in PROFILE_KEYS), storage)
                for t in range(STEPS)
            ]
        )
        result[day] = is_violation(margins).astype(float)
    return result


def storage_sensitivity(days: list[int]) -> dict:
    """Exploratory (amendment A2.3): realised no-action violation steps over `days` with the
    SimBench storage series held at 0 MW (study scenario), as published in pandapower's load
    convention, and sign-reversed (read as charging). Bounds how much the storage modelling
    choice drives the stress that is studied."""
    net = load_network()
    profiles = absolute_profiles(net)
    arrays = daily_arrays(profiles)
    start = profiles["storage_p_mw"].index.get_loc(FIRST_DAY)
    storage = profiles["storage_p_mw"].to_numpy()[start : start + len(arrays["sgen_p_mw"]) * STEPS]
    arrays["storage_p_mw"] = storage.reshape(len(arrays["sgen_p_mw"]), STEPS, -1)
    solver = GridSolver(net)
    result = {}
    for treatment, factor in (("zero", 0.0), ("as_published", 1.0), ("sign_reversed", -1.0)):
        violation_steps, worst = 0, -np.inf
        for day in days:
            solver.reset()
            for t in range(STEPS):
                margins = solver.solve(
                    *(arrays[name][day, t] for name in PROFILE_KEYS),
                    factor * arrays["storage_p_mw"][day, t],
                )
                violation_steps += int(is_violation(margins))
                worst = max(worst, float(np.nan_to_num(margins[3], nan=np.inf)))
        result[treatment] = {
            "violation_steps": violation_steps,
            "max_trafo_loading_pct": 100 + worst,
        }
    return {"days": len(days), **result}


def summarise(outcomes: pd.DataFrame, alpha_runs: dict[float, pd.DataFrame]) -> dict:
    """Totals per policy, paired per-day differences with block-bootstrap intervals, and the
    registered hypothesis checks H2-H4 (H1 is in the calibration section)."""
    policies = ["no_action", "static_70", "point", "risk", "robust", "oracle"] + [
        f"selective_{f}" for f in FALLBACKS
    ]
    if "static_dev__violation_steps" in outcomes:
        policies.append("static_dev")
    metrics = [
        "violation_steps",
        "nonconverged_steps",
        *(f"{name}_steps" for name in MARGINS),
        "trafo_severity_pct_steps",
        "curtailed_mwh",
    ]
    totals = {
        policy: {m: float(outcomes[f"{policy}__{m}"].sum()) for m in metrics} for policy in policies
    }
    oracle_curtailment = totals["oracle"]["curtailed_mwh"]
    for policy in policies:
        totals[policy]["excess_curtailment_vs_oracle_mwh"] = (
            totals[policy]["curtailed_mwh"] - oracle_curtailment
        )

    def paired(a: str, b: str, metric: str) -> dict:
        return block_bootstrap_mean(
            (outcomes[f"{a}__{metric}"] - outcomes[f"{b}__{metric}"]).to_numpy(dtype=float)
        )

    deferred = outcomes["deferred"].to_numpy()
    active_steps = outcomes["risk__active_steps"].to_numpy()
    active_violations = outcomes["risk__active_violations"].to_numpy()

    def rate(mask: np.ndarray) -> float | None:
        steps = active_steps[mask].sum()
        return float(active_violations[mask].sum() / steps) if steps else None

    h4 = {
        "testable": bool(deferred.any()),
        "deferred_days": int(deferred.sum()),
        "days": len(deferred),
        "reasons": outcomes.loc[deferred, "reasons"].value_counts().to_dict(),
        "risk_active_violation_rate_on_deferred_days": rate(deferred),
        "risk_active_violation_rate_on_recommended_days": rate(~deferred),
        "by_day_type": {
            day_type: {
                policy: {
                    m: float(outcomes.loc[mask, f"{policy}__{m}"].sum())
                    for m in ("violation_steps", "curtailed_mwh")
                }
                for policy in ["risk"] + [f"selective_{f}" for f in FALLBACKS]
            }
            for day_type, mask in (("deferred", deferred), ("recommended", ~deferred))
        },
    }
    if deferred.any():
        h4["selective_robust_minus_risk_violation_steps"] = paired(
            "selective_robust", "risk", "violation_steps"
        )
        h4["selective_no_action_minus_risk_violation_steps"] = paired(
            "selective_no_action", "risk", "violation_steps"
        )
    return {
        "days": len(outcomes),
        "totals": totals,
        "h2_risk_minus_point_violation_steps_per_day": paired("risk", "point", "violation_steps"),
        "h2_risk_minus_static70_curtailed_mwh_per_day": paired(
            "risk", "static_70", "curtailed_mwh"
        ),
        "h3_risk_active_steps": {
            "active_steps": int(active_steps.sum()),
            "realised_violations": int(active_violations.sum()),
            "realised_rate": rate(np.ones_like(deferred, dtype=bool)),
            "predicted_violations": float(outcomes["risk__active_expected"].sum()),
            "nominal_alpha": ALPHA,
        },
        "h4_selective": h4,
        "exploratory_alpha": {
            str(a): {
                "risk_violation_steps": int(frame["risk__violation_steps"].sum()),
                "risk_curtailed_mwh": float(frame["risk__curtailed_mwh"].sum()),
                "deferred_days": int(frame["deferred"].sum()),
                "selective_robust_violation_steps": int(
                    frame["selective_robust__violation_steps"].sum()
                ),
                "selective_robust_curtailed_mwh": float(
                    frame["selective_robust__curtailed_mwh"].sum()
                ),
            }
            for a, frame in alpha_runs.items()
        },
    }


def period_days(period: str) -> list[int]:
    start, end = PERIODS[period]
    return list(range((start - FIRST_DAY).days, (end - FIRST_DAY).days))


def run_grid_study(period: str, cache_dir: Path, workers: int | None = None) -> dict:
    """Physics (cached), decisions, calibration and summary for one registered period."""
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    net = load_network()
    rating = net.sgen["sn_mva"].to_numpy(dtype=float)
    arrays = daily_arrays(absolute_profiles(net))
    days = period_days(period)
    warmup = [d for d in range(days[0] - WINDOW_DAYS, days[0]) if d >= FIRST_DECISION_DAY]
    development = period_days("development")
    physics, provenance = physics_for(sorted(set(warmup + days + development)), cache_dir, workers)
    static_dev = static_dev_level(physics, development)

    reference_days = [d for d in range(days[0] - WINDOW_DAYS, days[-1]) if d not in physics]
    reference = realised_no_action(arrays, reference_days)
    reference.update({d: is_violation(m[REALISED, :, 0]).astype(float) for d, m in physics.items()})

    decision_physics = {d: physics[d] for d in sorted(set(warmup + days))}
    outcomes, passports = run_decisions(decision_physics, arrays, rating, days, ALPHA, static_dev)
    alpha_runs = {
        alpha: run_decisions(decision_physics, arrays, rating, days, alpha)[0]
        for alpha in EXPLORATORY_ALPHAS
    }
    dates = [(FIRST_DAY + pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in outcomes["day"]]
    return {
        "outcomes": outcomes.assign(date=dates),
        "passports": passports,
        "calibration": calibration(physics, reference, days),
        "summary": {
            **summarise(outcomes, alpha_runs),
            "amendment_a1_static_dev_cap": float(CAP_LEVELS[static_dev]),
        },
        "physics_cache": provenance,
        "storage_sensitivity": storage_sensitivity(days) if period == "development" else None,
    }
