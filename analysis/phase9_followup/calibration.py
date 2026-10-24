"""Phase 9 follow-up, task 1: R7 diagnosis and calibrated detection floors.

EXPLORATORY and post-hoc. This module runs **zero power flows**, loads **no `vm` array**,
touches **no held-out network** and writes **nothing** outside `analysis/phase9_followup/`.
It does not re-run, re-read for modification, or change any Phase 9 result; the frozen Phase 9
simulator of `analysis/phase9/phase9_analysis.py` is *imported* and reused unmodified.

Two questions:

1. **Why R7 failed.** Phase 9 (commit `19d94ce`) measured family-wise false-alarm rates of
   0.064-0.078 against the registered contrast floor
   `F_C,real = sigma * sqrt(1/n_day_med + 1/n_night_med) / sqrt(0.95 * D)`, with truth =
   nominal. The floor is a *plug-in* of three quantities it does not actually have: the per-day
   step counts (it uses the medians, while the variance of the day mean is convex in 1/n), the
   number of averaged days (the 1-day delay removes one) and the number of *surviving* days
   (0.95 * D is the expectation, not the realisation). Section `decomposition` turns each into
   an sd-inflation factor against the floor, predicts the resulting rate, and confirms it with
   the Phase 9 simulator by switching one nuisance at a time.

2. **What a calibrated floor would be.** Four per-meter statistics and thresholds (C0 the
   registered floor, C1 an exact plug-in at known sigma, C2 a day-level Student t, C3 a
   Newey-West studentised t) are run on the *development*-half day axis under ten noise
   scenarios, and judged against a validity rule that is written into the output JSON before
   any rate is computed.

Power is deliberately absent: this task measures false alarms only.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/calibration.py run
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/calibration.py summary

`run` writes `results/calibration.json` once and refuses to overwrite it.

Judgement calls (numbered, and repeated in the output JSON)
-----------------------------------------------------------
J1  The evaluation-half simulator axis is rebuilt from `results/phase9_inputs.json`
    (`days.retention_primary.retained` and `days.daylight_per_day`) rather than from the W6
    artefacts, and cross-checked against the day list Phase 9 recorded in
    `controls.control_1[code].day_axis`. Phase 9 recorded `all_daylight_steps_valid: true` and
    `dropped_not_usable: []` for both sweep networks, so the valid counts of reading R-o equal
    the step counts and the rebuild is exact. This keeps the task clear of the artefacts.
J2  An sd-inflation factor is "the sd of k-hat with only this nuisance active, divided by the
    registered floor F_C,real". The registered 0.95 therefore stays in the denominator at every
    stage, which is what reproduces the board's 1.0600 for heterogeneity alone.
J3  The missing-day expectation is taken exactly, not by simulation:
    E[sum_{d in S} v_d / |S|^2] = v_bar * E[1/|S|] with |S| ~ Binomial(D_axis, 0.95), because
    conditional on |S| = s the kept set is a uniform s-subset. The s = 0 atom is dropped and
    its probability reported.
J4  The predicted rate uses one inflation factor, p1 = 2 * Phi(-z_K / lambda) and
    1 - (1 - p1)^K. k-hat is really a scale mixture over the kept-day set, and the K meters are
    independent because their noise and their missingness are drawn independently. The Monte
    Carlo column is the check on this approximation.
J5  D in C0's `D_eff = 0.95 * D` is the number of *retained* development-half days, while the
    simulated axis is that set minus the last day (the 1-day delay). This mirrors Phase 9
    exactly (D_ret = 170, 169 simulated days).
J6  `sigma` in C0 and C1 is the condition's `sigma_tot` under the Phase 9 key of reading R-n
    (`realistic` and `biased_meters_matched` -> 0.01, `sigma_0.005` -> 0.005,
    `sigma_0.02` -> 0.02), and 0.01 for N2 and N3. C1 is "sigma known" in the sense of knowing
    the *registered total*, not the realised per-day noise sd, so under
    `biased_meters_matched` (sigma_v = 0.002) it stays as conservative as C0.
J7  A meter with fewer than two kept days has no C2 and no C3 statistic and raises no alarm; a
    meter with no kept day has no statistic at all (Phase 9 reading R-j). Counts are reported.
J8  A non-positive Newey-West variance yields no C3 alarm. The occurrences are counted and
    reported per scenario; no clipping or flooring is applied.
J9  "Kept days in calendar order" is read as the *observed* series: the Bartlett lag j pairs
    the j-th and the (j+k)-th kept day, ignoring the calendar gap left by a missing day. The
    bandwidth L = floor(4 * (|S|/100)^(2/9)) is computed per meter from that meter's |S|.
J10 A calibration is valid in a scenario iff the rule holds at every K **and in both sweep
    networks**; the rule as stated fixes K but not the network, and both networks are reported
    separately as well.
J11 N3's AR(1) contrast error runs across the consecutive days of the simulated axis and is
    added to the daylight leg before missingness is applied, so a missing day consumes its draw
    rather than shifting the series.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PHASE9 = REPO / "analysis" / "phase9"
if str(PHASE9) not in sys.path:  # the frozen Phase 9 modules are imported, never copied
    sys.path.insert(0, str(PHASE9))

import numpy as np  # noqa: E402
import phase9_analysis as pa  # noqa: E402
import phase9_sweep as ps  # noqa: E402
import q1_voltage_residual as q1  # noqa: E402
from scipy import stats  # noqa: E402

RESULTS = HERE / "results"
OUTPUT = RESULTS / "calibration.json"

STATUS = "EXPLORATORY, post-hoc; not registered; Phase 9 results unchanged"

PHASE9_INPUTS = PHASE9 / "results" / "phase9_inputs.json"
PHASE9_RESULTS = PHASE9 / "results" / "phase9_results.json"

NETWORKS = pa.SWEEP_NETWORKS
K_GRID = pa.K_GRID
STEPS = pa.STEPS
ALPHA = q1.ALPHA
MISSING = pa.REMOTE_MISSING  # 0.05
REPLICATES = 2000  # s. 10 control 1's count, kept for comparability

CONTROL = "followup_calibration"  # the `control` string of `pa.control_rng`
DECOMPOSITION_CONTROL = "followup_decomposition"

CALIBRATIONS = ("C0", "C1", "C2", "C3")
N1_SCENARIOS = ("realistic", "sigma_0.005", "sigma_0.02", "biased_meters_matched")
N2_RHO = (0.5, 0.9)
N3_RHO = (0.5, 0.9)
N3_R = (0.25, 0.5)

VALIDITY_RULE = {
    "pre_stated": True,
    "written_before_any_rate_was_computed": True,
    "valid": "at every K the pooled-over-rules rate is <= 0.055 and its Wilson 95 % lower "
             "bound is <= 0.05",
    "conservative": "at every K the Wilson 95 % upper bound is < 0.03",
    "network_scope": "a calibration is valid in a scenario iff the rule holds at every K in "
                     "both sweep networks (judgement call J10)",
    "simplest_justified_correction": "the first of C1, C2, C3, in that order of complexity, "
                                     "that is valid in every N1 scenario",
    "rate_limit": 0.055,
    "lower_bound_limit": 0.05,
    "conservative_limit": 0.03,
}  # fmt: skip

JUDGEMENT_CALLS = {
    "J1": "the evaluation-half axis is rebuilt from phase9_inputs.json and cross-checked "
          "against the day list Phase 9 recorded; no W6 artefact is read",
    "J2": "an sd-inflation factor is the sd of k-hat with only that nuisance active divided "
          "by the registered F_C,real, so the registered 0.95 stays in the denominator",
    "J3": "E[sum_S v_d / |S|^2] = v_bar * E[1/|S|] exactly, with |S| ~ Binomial(D, 0.95); the "
          "|S| = 0 atom is dropped and its probability reported",
    "J4": "the predicted rate uses one inflation factor and independent meters; the Monte "
          "Carlo column is the check on that approximation",
    "J5": "D in C0's D_eff = 0.95 * D is the retained development-half day count, while the "
          "simulated axis is that set minus the delayed last day, as in Phase 9",
    "J6": "sigma in C0 and C1 is the condition's registered sigma_tot key (reading R-n), 0.01 "
          "for N2 and N3; C1 knows the registered total, not the realised noise sd",
    "J7": "a meter with fewer than two kept days has no C2 or C3 statistic and raises no alarm",
    "J8": "a non-positive Newey-West variance yields no C3 alarm; occurrences are counted",
    "J9": "Bartlett lags pair kept days by observation index, not calendar gap; the bandwidth "
          "L = floor(4 (|S|/100)^(2/9)) is per meter",
    "J10": "validity requires the rule at every K in both sweep networks",
    "J11": "N3's AR(1) error runs across the simulated axis and is added to the daylight leg "
           "before missingness, so a missing day consumes its draw",
}  # fmt: skip


# --- day axes ------------------------------------------------------------------------------


def axis_from_counts(days, daylight_counts, *, delay: bool = True) -> dict:
    """One simulator day axis: the retained days of s. 7 (>= 1 daylight and >= 1 night step),
    with the last one removed by the s. 10 1-day delay when `delay` is set.

    Returns the day list, the per-day daylight and night step counts, the medians the
    registered floor plugs in, D (the retained count) and v_d = 1/n_d + 1/m_d.
    """
    days = [int(d) for d in days]
    counts = [int(c) for c in daylight_counts]
    if len(days) != len(counts):
        raise ValueError("one daylight count per day is required")
    retained = [(d, c) for d, c in zip(days, counts, strict=True) if 0 < c < STEPS]
    if not retained:
        raise RuntimeError("no day is retained")
    kept = retained[:-1] if delay else list(retained)
    if not kept:
        raise RuntimeError("the 1-day delay leaves no simulated day")
    n_day = np.array([c for _, c in kept], dtype=float)
    n_night = STEPS - n_day
    all_day = np.array([c for _, c in retained], dtype=float)
    return {
        "days": [d for d, _ in kept],
        "n_daylight": n_day,
        "n_night": n_night,
        "n_daylight_retained": all_day,
        "n_night_retained": STEPS - all_day,
        "D_retained": len(retained),
        "D_simulated": len(kept),
        "delay_applied": bool(delay),
        "dropped_no_daylight_or_night": [d for d, c in zip(days, counts, strict=True)
                                         if not 0 < c < STEPS],  # fmt: skip
        "n_day_median": float(np.median(all_day)),
        "n_night_median": float(np.median(STEPS - all_day)),
        "v_days": 1.0 / n_day + 1.0 / n_night,
        "v_days_retained": 1.0 / all_day + 1.0 / (STEPS - all_day),
    }


def evaluation_axis(code: str, inputs: dict) -> dict:
    """The Phase 9 evaluation-half simulator axis, rebuilt from Stage 1's inputs (J1)."""
    days = inputs["networks"][code]["days"]
    axis = axis_from_counts(days["scored"], days["daylight_per_day"], delay=True)
    axis["source"] = "phase9_inputs.json days.scored / days.daylight_per_day"
    return axis


def development_axis(code: str) -> dict:
    """The development-half day axis: `period_days("development")` intersected with the
    decision days, the s. 7 retention rule, and the per-day daylight masks of
    `phase9_sweep.daylight_masks` on the nominal variant network. Profiles only: no `vm`, no
    power flow (`daylight_masks` reads `grid.absolute_profiles` and never `net.line`)."""
    from gridpulse import dual_study as ds
    from gridpulse import grid_study

    days = [int(d) for d in grid_study.period_days("development")
            if grid_study.FIRST_DECISION_DAY <= int(d) <= ds.LAST_DAY]  # fmt: skip
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    masks = ps.daylight_masks(net, days)
    counts = [int(masks[d].sum()) for d in days]
    axis = axis_from_counts(days, counts, delay=True)
    axis["source"] = ("grid_study.period_days('development') ∩ [FIRST_DECISION_DAY, LAST_DAY], "
                      "phase9_sweep.daylight_masks on ds.variant_network(code, NOMINAL)")
    axis["candidate_days"] = len(days)
    axis["masks"] = {int(d): np.asarray(masks[d], dtype=bool) for d in axis["days"]}
    return axis


def count_distribution(axis: dict) -> dict:
    """The per-day daylight-step count distribution of one axis, for the report."""
    n_day = axis["n_daylight"]
    quantiles = [float(np.quantile(n_day, q)) for q in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)]
    return {
        "D_retained": axis["D_retained"],
        "D_simulated": axis["D_simulated"],
        "n_day_median_all_retained": axis["n_day_median"],
        "n_night_median_all_retained": axis["n_night_median"],
        "quantiles_0_10_25_50_75_90_100": quantiles,
        "mean_n_daylight": float(n_day.mean()),
        "mean_inverse_v": float(axis["v_days"].mean()),
        "v_at_medians": float(1.0 / axis["n_day_median"] + 1.0 / axis["n_night_median"]),
        "histogram_bin10_counts": [int(c) for c in np.histogram(
            n_day, bins=np.arange(0, STEPS + 10, 10))[0]],
    }


# --- the R7 decomposition ------------------------------------------------------------------


def expected_inverse_kept(n_days: int, p_keep: float = 1.0 - MISSING) -> dict:
    """E[1/|S|] with |S| ~ Binomial(`n_days`, `p_keep`), the |S| = 0 atom dropped (J3)."""
    s = np.arange(0, int(n_days) + 1)
    pmf = stats.binom.pmf(s, int(n_days), float(p_keep))
    zero = float(pmf[0])
    tail = pmf[1:] / max(1.0 - zero, np.finfo(float).tiny)
    return {"expected_inverse": float((tail / s[1:]).sum()),
            "probability_no_kept_day": zero}  # fmt: skip


def registered_floor(sigma: float, axis: dict) -> float:
    """F_C,real = sigma * sqrt(1/n_day_med + 1/n_night_med) / sqrt(0.95 * D_retained) (s. 8)."""
    return float(q1.floors(sigma, axis["n_day_median"], axis["n_night_median"],
                           (1.0 - MISSING) * axis["D_retained"], "mean")["F_C_realistic"])  # fmt: skip


def inflation(axis: dict, *, heterogeneity: bool, delay: bool, missing: bool) -> dict:
    """The sd of k-hat under a chosen subset of the three nuisances, as a factor on the
    registered floor (J2, J3).

    `heterogeneity`: the real per-day counts rather than their medians.
    `delay`: the axis is the retained days minus the last one.
    `missing`: each meter-day survives with probability 0.95, independently.

    Two factors are returned, because the floor's three plug-ins are not separable without a
    convention:

    - `sd_inflation` is the *realised* one, sd(k-hat under exactly these nuisances) /
      F_C,real. With `missing` off every day really is averaged, so 1/|S| is 1/D_axis and the
      registered 0.95 makes the floor conservative by sqrt(0.95) on its own.
    - `sd_inflation_board_convention` keeps 0.95 * D_axis in the denominator while `missing`
      is off, i.e. it credits the floor with the kept-day count it assumes. This is the board's
      decomposition: it isolates the whole 0.95 plug-in error into the missing-day row and is
      what reproduces 1.0600 / 1.0629 / 1.0631 (semiurb4). The two coincide once `missing` is
      on, which is the only row that carries a predicted rate against the observed one.
    """
    n_retained = axis["D_retained"]
    used = axis["D_simulated"] if delay else n_retained
    if heterogeneity:
        v = axis["v_days"] if delay else axis["v_days_retained"]
        v_bar = float(np.asarray(v, dtype=float).mean())
    else:
        v_bar = 1.0 / axis["n_day_median"] + 1.0 / axis["n_night_median"]
    if missing:
        kept = expected_inverse_kept(used)
        realised, zero = kept["expected_inverse"], kept["probability_no_kept_day"]
        nominal = realised
    else:
        realised, zero = 1.0 / used, 0.0
        nominal = 1.0 / ((1.0 - MISSING) * used)
    floor_ratio = (1.0 / axis["n_day_median"] + 1.0 / axis["n_night_median"]) / (
        (1.0 - MISSING) * n_retained)  # F_C,real^2 / sigma^2
    return {
        "heterogeneity": bool(heterogeneity), "delay": bool(delay), "missing": bool(missing),
        "days_on_the_axis": int(used),
        "mean_v": float(v_bar),
        "v_at_the_medians": float(1.0 / axis["n_day_median"] + 1.0 / axis["n_night_median"]),
        "expected_inverse_kept_days": float(realised),
        "sd_inflation": float(math.sqrt(v_bar * realised / floor_ratio)),
        "sd_inflation_board_convention": float(math.sqrt(v_bar * nominal / floor_ratio)),
        "probability_no_kept_day": float(zero),
    }  # fmt: skip


def predicted_rate(sd_inflation: float, k: int, alpha: float = ALPHA) -> float:
    """1 - (1 - p1)^K with p1 = 2 * Phi(-z_K / lambda): the family-wise false-alarm rate of
    K independent meters whose k-hat sd is `sd_inflation` times the threshold's floor (J4)."""
    z = q1.z_bonferroni(int(k), alpha)
    p1 = 2.0 * stats.norm.sf(z / float(sd_inflation))
    return float(1.0 - (1.0 - p1) ** int(k))


TOGGLES = (
    ("none", False, False, False),
    ("heterogeneity", True, False, False),
    ("heterogeneity_delay", True, True, False),
    ("heterogeneity_delay_missing", True, True, True),
    ("delay_only", False, True, False),
    ("missing_only", False, False, True),
)


def toggle_counts(axis: dict, heterogeneity: bool, delay: bool):
    """The per-day (n_day, n_night) the simulator is handed under one toggle."""
    size = axis["D_simulated"] if delay else axis["D_retained"]
    if heterogeneity:
        if delay:
            return axis["n_daylight"], axis["n_night"]
        return axis["n_daylight_retained"], axis["n_night_retained"]
    return (np.full(size, axis["n_day_median"]), np.full(size, axis["n_night_median"]))


def decomposition_network(code: str, axis: dict, rules: dict, buses, *,
                          replicates: int = REPLICATES) -> dict:  # fmt: skip
    """The R7 decomposition for one network: the analytic factors and predicted rates of each
    toggle, and a Monte Carlo confirmation with the frozen Phase 9 simulator."""
    spec = pa.noise_spec("realistic")
    sigma = float(spec["sigma_v"])
    floor = registered_floor(sigma, axis)
    matrices = {k: pa.config_matrix(rules, buses, k) for k in K_GRID}
    names = matrices[K_GRID[0]][1]
    out = {}
    for name, heterogeneity, delay, missing in TOGGLES:
        analytic = inflation(axis, heterogeneity=heterogeneity, delay=delay, missing=missing)
        n_day, n_night = toggle_counts(axis, heterogeneity, delay)
        draw_spec = dict(spec)
        draw_spec["remote_missing"] = MISSING if missing else 0.0
        rng = pa.control_rng(code, name, DECOMPOSITION_CONTROL, 0)
        tally = {k: np.zeros(len(names), dtype=int) for k in K_GRID}
        for _ in range(int(replicates)):
            draws = pa.draw_replicate(rng, draw_spec, n_day, n_night, len(buses), False)
            k_hat = pa.replicate_statistics(draws)["k"]
            for k in K_GRID:
                tally[k] += pa.family_alarm(k_hat, matrices[k][0], q1.z_bonferroni(k) * floor)
        out[name] = {
            "analytic": analytic,
            "per_K": {
                f"K_{k}": {
                    "z": q1.z_bonferroni(k),
                    "predicted_rate": predicted_rate(analytic["sd_inflation"], k),
                    "monte_carlo": pa.rate_record(int(tally[k].sum()),
                                                  int(replicates) * len(names)),  # fmt: skip
                }
                for k in K_GRID
            },
        }
    return {
        "network": code, "threshold": "z_K * F_C,real", "F_C_real_pu": floor,
        "sigma_v": sigma, "truth": "nominal", "replicates": int(replicates),
        "rules": len(names), "toggles": out,
    }  # fmt: skip


# --- the four calibrations -------------------------------------------------------------


def c1_floor(sigma: float, v_days, survives) -> np.ndarray:
    """C1, the exact plug-in at known sigma:
    F^2 = sigma^2 * sum_{d in S} (1/n_d + 1/m_d) / |S|^2, per meter."""
    survives = np.asarray(survives, dtype=bool)
    v = np.asarray(v_days, dtype=float)
    counts = survives.sum(axis=0)
    total = np.where(survives, v[:, None], 0.0).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(counts > 0, float(sigma) * np.sqrt(total) / counts, np.nan)


def bartlett_lag(counts) -> np.ndarray:
    """L = floor(4 * (|S| / 100)^(2/9)), the Newey-West bandwidth, per meter (J9)."""
    counts = np.asarray(counts, dtype=float)
    with np.errstate(invalid="ignore"):
        return np.floor(4.0 * np.power(np.maximum(counts, 0.0) / 100.0, 2.0 / 9.0)).astype(int)


def newey_west_variance(centred, counts, lags) -> np.ndarray:
    """The Newey-West (Bartlett) long-run variance omega^2 of a per-meter kept-day series.

    `centred` is [observations, meters], zero-padded past each meter's |S| and already centred
    on that meter's mean; `counts` is |S| per meter and `lags` the per-meter bandwidth. With
    lag 0 this is gamma_0 = sum e^2 / |S|, the plain (1/n) sample variance.
    """
    centred = np.asarray(centred, dtype=float)
    counts = np.asarray(counts, dtype=float)
    lags = np.asarray(lags, dtype=int)
    with np.errstate(divide="ignore", invalid="ignore"):
        omega = (centred**2).sum(axis=0) / counts
        for j in range(1, int(lags.max(initial=0)) + 1):
            if j >= centred.shape[0]:
                break
            gamma = (centred[:-j] * centred[j:]).sum(axis=0) / counts
            weight = np.maximum(0.0, 1.0 - j / (lags + 1.0))
            omega = omega + 2.0 * weight * gamma
    return np.where(counts > 0, omega, np.nan)


_T_CACHE: dict[tuple[int, int], float] = {}


def t_critical(df: int, k: int, alpha: float = ALPHA) -> float:
    """The two-sided Bonferroni Student critical value t_{df}(1 - (alpha/2)/K)."""
    key = (int(df), int(k))
    if key not in _T_CACHE:
        _T_CACHE[key] = float(stats.t.ppf(1.0 - (alpha / 2.0) / int(k), int(df)))
    return _T_CACHE[key]


def t_critical_vector(dfs, k: int) -> np.ndarray:
    """`t_critical` over a per-meter degrees-of-freedom array; df < 1 gives NaN (J7)."""
    dfs = np.asarray(dfs, dtype=int)
    out = np.full(dfs.shape, np.nan, dtype=float)
    for value in np.unique(dfs):
        if int(value) >= 1:
            out[dfs == value] = t_critical(int(value), int(k))
    return out


def compact(values, survives) -> np.ndarray:
    """A meter's kept-day values moved to the front of the array in calendar order, the rest
    zero-filled (J9). `values` and `survives` are [days, meters]."""
    survives = np.asarray(survives, dtype=bool)
    order = np.argsort(~survives, axis=0, kind="stable")
    return np.take_along_axis(np.where(survives, np.asarray(values, dtype=float), 0.0),
                              order, axis=0)  # fmt: skip


def calibration_ratios(contrast, survives, k_hat, sigma: float, v_days) -> dict:
    """The statistic / critical-value ratio of C0, C1, C2 and C3 for every meter and K.

    A ratio of at least 1 is an alarm, so `pa.family_alarm(ratio, mask, 1.0)` is the s. 10
    family event unchanged; NaN (no statistic) raises no alarm, as in Phase 9's reading R-j.
    `c0_floor` is added by the caller because it does not depend on the replicate.
    """
    survives = np.asarray(survives, dtype=bool)
    counts = survives.sum(axis=0)
    k_abs = np.abs(np.asarray(k_hat, dtype=float))
    centred = compact(np.asarray(contrast, dtype=float) - np.asarray(k_hat, dtype=float),
                      survives)  # fmt: skip
    with np.errstate(divide="ignore", invalid="ignore"):
        variance = (centred**2).sum(axis=0) / np.maximum(counts - 1, 1)
        variance = np.where(counts >= 2, variance, np.nan)
        se_t = np.sqrt(variance / np.maximum(counts, 1))
        omega = newey_west_variance(centred, counts, bartlett_lag(counts))
        omega = np.where(counts >= 2, omega, np.nan)
        se_hac = np.sqrt(np.where(omega > 0, omega, np.nan) / np.maximum(counts, 1))
        t_stat = np.where(se_t > 0, k_abs / se_t, np.nan)
        hac_stat = np.where(se_hac > 0, k_abs / se_hac, np.nan)
    return {
        "k_abs": k_abs,
        "kept_days": counts,
        "C1_floor": c1_floor(sigma, v_days, survives),
        "t_stat": t_stat,
        "hac_stat": hac_stat,
        "omega_non_positive": int(((counts >= 2) & ~(omega > 0)).sum()),
        "no_reading": int((counts == 0).sum()),
        "too_few_days": int(((counts >= 1) & (counts < 2)).sum()),
    }


def ratios_for_k(parts: dict, k: int, c0_floor: float) -> dict:
    """The per-meter alarm ratios of the four calibrations at one K."""
    z = q1.z_bonferroni(int(k))
    with np.errstate(divide="ignore", invalid="ignore"):
        return {
            "C0": parts["k_abs"] / (z * c0_floor),
            "C1": parts["k_abs"] / (z * parts["C1_floor"]),
            "C2": parts["t_stat"] / t_critical_vector(parts["kept_days"] - 1, k),
            "C3": parts["hac_stat"] / z,
        }


# --- the noise scenarios --------------------------------------------------------------------


def ar1_moments(mask, sigma: float, rho: float) -> tuple[float, float, float]:
    """The (daylight mean, night mean) covariance of one day under within-day AR(1) reading
    noise: Var_A = sigma^2 a'Ra, Var_B = sigma^2 b'Rb, Cov = sigma^2 a'Rb with
    R_ij = rho^|i-j|, a the daylight indicator / n_day and b the night indicator / n_night."""
    mask = np.asarray(mask, dtype=bool)
    steps = mask.size
    n_day, n_night = int(mask.sum()), int((~mask).sum())
    if n_day < 1 or n_night < 1:
        raise ValueError("a day needs at least one daylight and one night step")
    index = np.arange(steps)
    corr = float(rho) ** np.abs(index[:, None] - index[None, :])
    a = mask / n_day
    b = (~mask) / n_night
    scale = float(sigma) ** 2
    return (scale * float(a @ corr @ a), scale * float(b @ corr @ b),
            scale * float(a @ corr @ b))  # fmt: skip


def ar1_day_night_spec(axis: dict, sigma: float, rho: float) -> dict:
    """The per-day AR(1) (sd_day, sd_night, correlation) of a whole axis."""
    rows = [ar1_moments(axis["masks"][d], sigma, rho) for d in axis["days"]]
    var_a = np.array([r[0] for r in rows])
    var_b = np.array([r[1] for r in rows])
    cov = np.array([r[2] for r in rows])
    return {"sd_day": np.sqrt(var_a), "sd_night": np.sqrt(var_b),
            "correlation": cov / np.sqrt(var_a * var_b)}  # fmt: skip


def draw_ar1_within_day(rng, moments: dict, meters: int, missing: float = MISSING) -> dict:
    """One N2 replicate: the day and night means drawn exactly as a bivariate normal with the
    AR(1) covariance, then the same missingness as `realistic`."""
    days = moments["sd_day"].size
    z1 = rng.standard_normal((days, meters))
    z2 = rng.standard_normal((days, meters))
    rho = moments["correlation"][:, None]
    day = moments["sd_day"][:, None] * z1
    night = moments["sd_night"][:, None] * (rho * z1 + np.sqrt(1.0 - rho**2) * z2)
    survives = rng.random((days, meters)) >= float(missing)
    return {"day": day, "night": night, "bias": np.zeros(meters), "survives": survives,
            "both_legs": False, "days": days, "meters": meters}  # fmt: skip


def ar1_across_days(rng, days: int, meters: int, rho: float, tau: float) -> np.ndarray:
    """A per-meter, zero-mean AR(1) series across consecutive days with stationary sd `tau`."""
    noise = rng.standard_normal((int(days), int(meters)))
    out = np.empty_like(noise)
    out[0] = float(tau) * noise[0]
    step = float(tau) * math.sqrt(1.0 - float(rho) ** 2)
    for d in range(1, int(days)):
        out[d] = float(rho) * out[d - 1] + step * noise[d]
    return out


def scenarios(axis: dict) -> list[dict]:
    """The ten N1/N2/N3 scenarios, each with its sigma for C0 and C1 (J6)."""
    out = []
    for condition in N1_SCENARIOS:
        spec = pa.noise_spec(condition)
        out.append({"family": "N1", "name": condition, "spec": spec,
                    "sigma_threshold": float(spec["threshold_sigma_key"]),
                    "description": "registered i.i.d. condition"})  # fmt: skip
    for rho in N2_RHO:
        out.append({"family": "N2", "name": f"ar1_within_day_rho_{rho:g}", "rho": float(rho),
                    "sigma_v": 0.01, "sigma_threshold": 0.01,
                    "description": "within-day AR(1) reading noise, marginal sigma_v = 0.01, "
                                   "exact bivariate day/night means"})  # fmt: skip
    tau_base = math.sqrt(1.0 / axis["n_day_median"] + 1.0 / axis["n_night_median"]) * 0.01
    for rho in N3_RHO:
        for ratio in N3_R:
            out.append({"family": "N3", "name": f"ar1_across_days_rho_{rho:g}_r_{ratio:g}",
                        "rho_day": float(rho), "r": float(ratio),
                        "tau": float(ratio) * tau_base, "sigma_threshold": 0.01,
                        "description": "realistic plus a per-meter AR(1) diurnal contrast "
                                       "error on the daylight leg"})  # fmt: skip
    return out


def draw_scenario(rng, scenario: dict, axis: dict, meters: int, cache: dict) -> dict:
    """One replicate of one scenario, in the Phase 9 `draw_replicate` shape."""
    family = scenario["family"]
    if family == "N1":
        return pa.draw_replicate(rng, scenario["spec"], axis["n_daylight"], axis["n_night"],
                                 meters, False)  # fmt: skip
    if family == "N2":
        return draw_ar1_within_day(rng, cache[scenario["name"]], meters)
    draws = pa.draw_replicate(rng, cache["realistic_spec"], axis["n_daylight"],
                              axis["n_night"], meters, False)  # fmt: skip
    draws["day"] = draws["day"] + ar1_across_days(
        rng, draws["days"], meters, scenario["rho_day"], scenario["tau"])
    return draws


# --- the false-alarm matrix -----------------------------------------------------------------


def wilson_record(successes: int, trials: int) -> dict:
    return pa.rate_record(int(successes), int(trials))


def scenario_network(code: str, axis: dict, rules: dict, buses, scenario: dict, cache: dict, *,
                     replicates: int = REPLICATES) -> dict:  # fmt: skip
    """One scenario on one network: the family-wise false-alarm rate of every calibration and
    K, pooled over the 25 frozen rules, with the worst rule."""
    matrices = {k: pa.config_matrix(rules, buses, k) for k in K_GRID}
    names = matrices[K_GRID[0]][1]
    sigma = float(scenario["sigma_threshold"])
    c0_floor = registered_floor(sigma, axis)
    rng = pa.control_rng(code, scenario["name"], CONTROL, 0)
    tally = {name: {k: np.zeros(len(names), dtype=int) for k in K_GRID} for name in CALIBRATIONS}
    diagnostics = {"no_reading": 0, "too_few_days": 0, "omega_non_positive": 0}
    for _ in range(int(replicates)):
        draws = draw_scenario(rng, scenario, axis, len(buses), cache)
        contrast = draws["day"] - draws["night"]
        k_hat = pa.replicate_statistics(draws)["k"]
        parts = calibration_ratios(contrast, draws["survives"], k_hat, sigma, axis["v_days"])
        for key in diagnostics:
            diagnostics[key] += int(parts[key])
        for k in K_GRID:
            ratios = ratios_for_k(parts, k, c0_floor)
            for name in CALIBRATIONS:
                tally[name][k] += pa.family_alarm(ratios[name], matrices[k][0], 1.0)
    trials = int(replicates) * len(names)
    out = {}
    for name in CALIBRATIONS:
        per_k = {}
        for k in K_GRID:
            counts = tally[name][k]
            per_k[f"K_{k}"] = {
                "pooled_over_rules": wilson_record(int(counts.sum()), trials),
                "worst_rule": max(
                    ({"rule": rule, **wilson_record(int(counts[i]), int(replicates))}
                     for i, rule in enumerate(names)),
                    key=lambda record: record["low"],
                ),
                "per_rule_successes": [int(c) for c in counts],
            }  # fmt: skip
        out[name] = {"per_K": per_k, **verdict(per_k)}
    return {
        "network": code, "scenario": scenario["name"], "family": scenario["family"],
        "sigma_threshold": sigma, "F_C_real_pu": c0_floor, "replicates": int(replicates),
        "rules": len(names), "trials_per_cell": trials,
        "meter_days_diagnostics": diagnostics,
        "calibrations": out,
    }  # fmt: skip


def verdict(per_k: dict) -> dict:
    """The pre-stated rule applied to one calibration's K grid."""
    rates = [per_k[f"K_{k}"]["pooled_over_rules"] for k in K_GRID]
    return {
        "valid": all(r["rate"] <= VALIDITY_RULE["rate_limit"]
                     and r["low"] <= VALIDITY_RULE["lower_bound_limit"] for r in rates),
        "conservative": all(r["high"] < VALIDITY_RULE["conservative_limit"] for r in rates),
        "max_pooled_rate": max(r["rate"] for r in rates),
    }  # fmt: skip


def combine(per_network: dict) -> dict:
    """Validity across both sweep networks (J10)."""
    return {
        "valid": all(block["valid"] for block in per_network.values()),
        "conservative": all(block["conservative"] for block in per_network.values()),
        "max_pooled_rate": max(block["max_pooled_rate"] for block in per_network.values()),
        "per_network": {code: {key: block[key] for key in
                               ("valid", "conservative", "max_pooled_rate")}
                        for code, block in per_network.items()},  # fmt: skip
    }


def simplest_correction(by_scenario: dict) -> dict:
    """The first of C1, C2, C3 valid in every N1 scenario."""
    n1 = [name for name in by_scenario if by_scenario[name]["family"] == "N1"]
    for name in ("C1", "C2", "C3"):
        if all(by_scenario[s]["calibrations"][name]["valid"] for s in n1):
            return {"calibration": name, "scenarios_required": sorted(n1)}
    return {"calibration": None, "scenarios_required": sorted(n1),
            "note": "no calibration of C1, C2, C3 is valid in every N1 scenario"}  # fmt: skip


# --- the run ---------------------------------------------------------------------------------


def run(output: Path = OUTPUT, *, replicates: int = REPLICATES) -> dict:
    """Everything, into one write-once JSON. The validity rule is placed in the payload
    before any rate is computed and is never rewritten."""
    payload: dict = {
        "task": "Phase 9 follow-up 1: R7 diagnosis and calibrated detection floors",
        "status": STATUS,
        "validity_rule": VALIDITY_RULE,  # pre-stated, before any rate below exists
        "judgement_calls": JUDGEMENT_CALLS,
        "provenance": {
            "phase9_registration": pa.REGISTRATION,
            "phase9_registration_sha256": pa.REGISTRATION_SHA256,
            "phase9_inputs": str(PHASE9_INPUTS.relative_to(REPO)),
            "phase9_results": str(PHASE9_RESULTS.relative_to(REPO)),
            "placements": q1.PLACEMENTS,
            "reused_phase9_functions": [
                "noise_spec", "draw_replicate", "replicate_statistics", "survival_mean",
                "config_matrix", "family_alarm", "rate_record", "control_rng", "placements",
                "q1.floors", "q1.z_bonferroni", "ps.daylight_masks",
            ],
            "power_flows_run": 0,
            "vm_arrays_loaded": 0,
            "held_out_networks_touched": 0,
            "phase9_files_written": 0,
        },
        "replicates": int(replicates),
        "K_grid": list(K_GRID),
        "interval_label": "descriptive Wilson 95 % (Phase 9 reading R-l). One replicate is "
                          "one measurement realisation shared by all 25 rules, so the pooled "
                          "cell's 25 * replicates trials are not independent and the interval "
                          "is narrower than a true sampling interval. It is reported because "
                          "the pre-stated rule names it, not as a coverage claim.",
    }  # fmt: skip

    inputs = json.loads(PHASE9_INPUTS.read_text())
    phase9 = json.loads(PHASE9_RESULTS.read_text())

    # 1. the R7 decomposition, on the evaluation half
    decomposition: dict = {}
    for code in NETWORKS:
        axis = evaluation_axis(code, inputs)
        recorded = phase9["controls"]["control_1"][code]["day_axis"]
        if [int(d) for d in recorded["days"]] != axis["days"]:
            raise RuntimeError(f"{code}: the rebuilt evaluation axis differs from Phase 9's")
        rules = pa.placements(code)
        buses = [int(b) for b in inputs["networks"][code]["lv_buses"]]
        block = decomposition_network(code, axis, rules, buses, replicates=replicates)
        block["axis_cross_check"] = {
            "matches_phase9_day_axis": True,
            "simulated_days": axis["D_simulated"],
            "retained_days": axis["D_retained"],
            "phase9_all_daylight_steps_valid": bool(recorded["all_daylight_steps_valid"]),
            "phase9_dropped_not_usable": list(recorded["dropped_not_usable"]),
        }
        block["observed_phase9"] = {
            condition: {
                k_text: phase9["controls"]["control_1"][code]["per_condition"][condition][
                    "variants"]["measured_leg"]["arms"]["F_C_real"][k_text][
                    "pooled_over_rules"]["rate"]
                for k_text in (f"K_{k}" for k in K_GRID)
            }
            for condition in N1_SCENARIOS
        }
        block["count_distribution"] = count_distribution(axis)
        decomposition[code] = block
    payload["R7_decomposition"] = decomposition

    # 2. the development-half day axis
    axes = {code: development_axis(code) for code in NETWORKS}
    payload["development_axis"] = {
        code: {key: axes[code][key] for key in
               ("days", "D_retained", "D_simulated", "delay_applied", "candidate_days",
                "dropped_no_daylight_or_night", "n_day_median", "n_night_median", "source")}
        | {"count_distribution": count_distribution(axes[code])}
        for code in NETWORKS
    }  # fmt: skip

    # 3-4. the calibrations under the ten scenarios
    matrix: dict = {}
    for code in NETWORKS:
        axis = axes[code]
        rules = pa.placements(code)
        buses = [int(b) for b in inputs["networks"][code]["lv_buses"]]
        cache = {"realistic_spec": pa.noise_spec("realistic")}
        for scenario in scenarios(axis):
            if scenario["family"] == "N2":
                cache[scenario["name"]] = ar1_day_night_spec(
                    axis, scenario["sigma_v"], scenario["rho"])
            block = scenario_network(code, axis, rules, buses, scenario, cache,
                                     replicates=replicates)  # fmt: skip
            matrix.setdefault(scenario["name"], {"family": scenario["family"],
                                                 "description": scenario["description"],
                                                 "per_network": {}})["per_network"][code] = block  # fmt: skip
    for name, block in matrix.items():
        block["calibrations"] = {
            cal: combine({code: entry["calibrations"][cal]
                          for code, entry in block["per_network"].items()})
            for cal in CALIBRATIONS
        }
    payload["false_alarm_matrix"] = matrix
    payload["simplest_justified_correction"] = simplest_correction(matrix)
    payload["also_valid_under"] = {
        cal: {
            "N2": sorted(n for n, b in matrix.items()
                         if b["family"] == "N2" and b["calibrations"][cal]["valid"]),
            "N3": sorted(n for n, b in matrix.items()
                         if b["family"] == "N3" and b["calibrations"][cal]["valid"]),
        }
        for cal in CALIBRATIONS
    }  # fmt: skip

    payload = q1._plain(payload)  # numpy scalars and arrays to plain JSON, as Phase 9 does
    sha = q1.write_new_json(Path(output), payload)
    payload["_sha256"] = sha
    payload["_path"] = str(Path(output))
    return payload


# --- the compact summary ----------------------------------------------------------------------


def print_summary(payload: dict) -> None:
    """The report tables, printed from the payload: no ad-hoc JSON parsing downstream."""
    print(f"status: {payload['status']}")
    print(f"replicates: {payload['replicates']}  K grid: {payload['K_grid']}")

    print("\n== R7 decomposition (truth = nominal, `realistic`, evaluation half) ==")
    for code, block in payload["R7_decomposition"].items():
        observed = block["observed_phase9"]["realistic"]
        print(f"\n{code}  D_ret={block['axis_cross_check']['retained_days']} "
              f"D_sim={block['axis_cross_check']['simulated_days']} "
              f"F_C,real={block['F_C_real_pu']:.6g} p.u.")
        print(f"  {'toggle':<30}{'board':>7}{'real':>8}  " + "  ".join(
            f"K={k}: {'pred':>6}/{'mc':>6}/{'obs':>6}" for k in K_GRID))
        for name, entry in block["toggles"].items():
            cells = []
            for k in K_GRID:
                per = entry["per_K"][f"K_{k}"]
                obs = observed[f"K_{k}"] if name == "heterogeneity_delay_missing" else None
                cells.append(f"K={k}: {per['predicted_rate']:.4f}/"
                             f"{per['monte_carlo']['rate']:.4f}/"
                             f"{'     -' if obs is None else format(obs, '.4f')}")
            print(f"  {name:<30}{entry['analytic']['sd_inflation_board_convention']:>7.4f}"
                  f"{entry['analytic']['sd_inflation']:>8.4f}  " + "  ".join(cells))
        print("  (board = the 0.95 credited to the floor until the missing-day row; "
              "real = the sd the simulator actually has, which `mc` checks)")

    print("\n== development-half day axis ==")
    for code, block in payload["development_axis"].items():
        dist = block["count_distribution"]
        print(f"{code}  candidates={block['candidate_days']} D_dev={block['D_retained']} "
              f"simulated={block['D_simulated']} "
              f"n_day_med={block['n_day_median']:g} n_night_med={block['n_night_median']:g}")
        print(f"   daylight-step quantiles 0/10/25/50/75/90/100: "
              f"{['%g' % q for q in dist['quantiles_0_10_25_50_75_90_100']]}  "
              f"mean v={dist['mean_inverse_v']:.5f} vs v(median)={dist['v_at_medians']:.5f}")

    print("\n== false-alarm matrix: pooled-over-rules rate [Wilson 95 %], worst network ==")
    header = f"{'scenario':<34}{'cal':<5}" + "".join(f"{'K=' + str(k):>22}" for k in K_GRID)
    print(header + "  valid  cons")
    for name, block in payload["false_alarm_matrix"].items():
        for cal in CALIBRATIONS:
            cells = []
            for k in K_GRID:
                worst = max((entry["calibrations"][cal]["per_K"][f"K_{k}"]["pooled_over_rules"]
                             for entry in block["per_network"].values()),
                            key=lambda record: record["rate"])
                cells.append(f"{worst['rate']:.4f}[{worst['low']:.3f},{worst['high']:.3f}]".rjust(22))
            flags = block["calibrations"][cal]
            print(f"{name:<34}{cal:<5}" + "".join(cells)
                  + f"  {'yes' if flags['valid'] else 'NO':>5}"
                  + f"  {'yes' if flags['conservative'] else 'no':>4}")
    print("\n== which clause of the pre-stated rule each N1 cell breaks ==")
    for name, block in payload["false_alarm_matrix"].items():
        if block["family"] != "N1":
            continue
        for cal in CALIBRATIONS:
            broken = []
            for code, entry in block["per_network"].items():
                for k in K_GRID:
                    record = entry["calibrations"][cal]["per_K"][f"K_{k}"]["pooled_over_rules"]
                    clauses = []
                    if record["rate"] > VALIDITY_RULE["rate_limit"]:
                        clauses.append(f"rate {record['rate']:.4f} > 0.055")
                    if record["low"] > VALIDITY_RULE["lower_bound_limit"]:
                        clauses.append(f"low {record['low']:.4f} > 0.05")
                    if clauses:
                        broken.append(f"{code.split('-')[2]} K={k}: " + ", ".join(clauses))
            if broken:
                print(f"  {name:<24}{cal}: " + "; ".join(broken))
    print("\nsimplest justified correction (valid in every N1 scenario): "
          f"{payload['simplest_justified_correction']['calibration']}")
    for cal, extra in payload["also_valid_under"].items():
        print(f"  {cal}: also valid under N2 {extra['N2']}  N3 {extra['N3']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("run", "summary"))
    parser.add_argument("--out", default=str(OUTPUT))
    parser.add_argument("--replicates", type=int, default=REPLICATES)
    args = parser.parse_args(argv)
    if args.command == "run":
        payload = run(Path(args.out), replicates=args.replicates)
        print(f"wrote {args.out} sha256={payload['_sha256']}\n")
    else:
        payload = json.loads(Path(args.out).read_text())
    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
