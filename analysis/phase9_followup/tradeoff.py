"""Phase 9 follow-up, task 2: the calibrated detection trade-off and where the limits come from.

EXPLORATORY and post-hoc on the Phase 9 evaluation-half artefacts, which Phase 9 already
examined. It runs **zero power flows**, loads **no held-out network**, re-runs **no frozen
evaluation** and writes **nothing** outside `analysis/phase9_followup/`. The registered Phase 9
failures (R3, R5, R7) stand as they are; nothing here reinterprets the task 1 validity rule.

Four questions, on the two sweep networks, sigma_tot in {0.01, 0.005}, K in {1, 2, 4} and the
25 frozen placement rules:

1. **Noise-free reference.** Phase 9's noise-free band-C coverage is reproduced with C0 (the
   registered floor) and recomputed with the C1 floor. The run refuses if C0 does not
   reproduce the registered counts.
2. **Detection with noise.** The truth per-day means are each W6 artefact's stored daylight and
   night means; `realistic` / `sigma_0.005` measurement noise (missingness and the 1-day delay)
   is added with the frozen Phase 9 simulator over 400 replicates. Detection probability is
   reported per (cable, rule), as coverage over pairs, and conditioned on whether a meter sits
   downstream of the cable.
3. **Trade-off curve.** Every calibration's critical value is multiplied by c in
   {0.5 ... 5}; false alarms (truth = nominal) are read against coverage at each c, and the
   **coverage at a calibrated 5 % false-alarm rate** is interpolated in c. The N2 stress
   scenario (within-day AR(1), rho = 0.9) repeats the curve for C1 and C2.
4. **Limitation decomposition.** Noise-free, with the C1 threshold at K = 2, every (cable,
   rule) pair is classified into exactly one of placement / asset-physics / signal-strength /
   detected, with cable-level ceilings beside it.

C3 (the Newey-West studentised t of task 1) is **left out of the power analysis**: task 1
measured it at 0.06-0.08 under every N1 condition, i.e. anti-conservative, so its coverage
would be inflated by a floor that does not hold its own size. Only C0, C1 and C2 are run.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/tradeoff.py check
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/tradeoff.py run
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/tradeoff.py summary

`run` writes `results/tradeoff.json` once and refuses to overwrite it. `check` prints the
cheap blocks (the noise-free reference and the decomposition) and writes nothing.

Judgement calls (numbered, and repeated in the output JSON)
-----------------------------------------------------------
J1  The W6 artefacts are loaded directly with `phase9_sweep.artefact_path` and reduced with the
    frozen `phase9_analysis.run_statistics`, not through `stage3_context`: Stage 3's context
    demands a committed registration and the 99-run barrier, which are Phase 9 gates and are
    not this task's to re-run. The bus order of every artefact is still checked against
    Stage 1's `lv_buses`, and the 89 W6 specifications come from `ps.expected_specs()`.
J2  The per-meter alarm statistics are task 1's: C0 and C1 are read off `cal.c1_floor` and the
    registered floor, C2's critical value off `cal.t_critical_vector`. C2's day-level variance
    is evaluated **batched over cables** here, because `cal.calibration_ratios` is written for
    one [days, meters] contrast and this task needs 89 of them per replicate. The batched form
    is the same sum of squared centred kept-day deviations (a sum does not depend on the order
    `cal.compact` imposes); `tests/test_tradeoff.py` asserts the two agree to 1e-12 on a toy
    array. C3 is not computed at all.
J3  An alarm at multiplier c is `peak ratio >= c`, where the ratio is the statistic over its own
    critical value. Multiplying a critical value by c is therefore exactly one comparison of the
    c = 1 ratio, so one pass over the replicates yields the whole trade-off curve. Non-finite
    ratios (a meter with no reading, or with fewer than two kept days for C2) raise no alarm,
    which is `pa.family_alarm`'s rule and Phase 9's reading R-j.
J4  The false-alarm pass uses the same day axis, the same per-day counts, the same 400
    replicates and the same sampler as the detection pass, but a **distinct** `control_rng`
    control string, so the two are independent rather than paired. Under truth = nominal the
    contrast does not depend on the cable, so the false-alarm rate is pooled over the 25 rules
    only (25 * 400 trials), as in Phase 9's control 1.
J5  C1's noise-free floor is sigma * sqrt(sum_{d in U} v_d) / |U| over that cable's **used**
    retained days U (the `run_statistics` rule: retained, with a valid daylight and night step
    and finite means), with no missing-day factor, because the noise-free statistic really does
    average over all of them. C0 keeps its registered 0.95 * D_ret, which is what makes C1 the
    tighter floor.
J6  The noise-free C1 coverage is reported as a detected count and a Wilson rate only; no
    B/C "low" boundary is invented for C1, so no band_counts are given for it. C0's band counts
    come from the frozen `pa.coverage_block` unchanged.
J7  The decomposition's non-reversing test is read at the cable's **downstream argmax of |k|**:
    the downstream bus with the largest absolute mean contrast. A cable is non-reversing iff its
    downstream installed PV is 0 or sign(night) = sign(m) at that bus.
J8  The decomposition's categories are applied in the stated order, so (b) asset/physics takes
    precedence over the signal test. A pair can therefore be classified (b) although its
    downstream peak clears the threshold; those pairs are counted and reported
    (`asset_physics_pairs_above_threshold`) rather than moved.
J9  Category (c) and the detected category use the **downstream-restricted** peak
    max_{b in config and downstream(l)} |k|, as the task words it. The registered band-C
    statistic is the max over **all** of the configuration's buses, so the two can differ when a
    non-downstream meter carries the larger contrast; the registered count and the number of
    disagreeing pairs are reported beside the decomposition.
J10 "Signal-capable" and the oracle single-meter coverage use z_1 (K = 1, the most generous
    Bonferroni threshold) on the C1 floor. The oracle is given twice: over all LV buses, as the
    task words it, and restricted to downstream(l), which is the ceiling a correctly placed
    meter could reach.
J11 The N2 stress scenario rebuilds the per-day daylight masks of the evaluation-half axis with
    `phase9_sweep.daylight_masks` on the nominal variant network (profiles only, no `vm` and no
    power flow) and refuses unless every mask's daylight count equals the artefact's
    `n_daylight_valid`. The AR(1) day/night means are then drawn by task 1's
    `cal.ar1_day_night_spec` and `cal.draw_ar1_within_day`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PHASE9 = REPO / "analysis" / "phase9"
for _path in (PHASE9, HERE):  # the frozen Phase 9 modules and task 1 are imported, never copied
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import calibration as cal  # noqa: E402  (task 1, this follow-up)
import numpy as np  # noqa: E402
import phase9_analysis as pa  # noqa: E402
import phase9_sweep as ps  # noqa: E402
import q1_voltage_residual as q1  # noqa: E402

RESULTS = HERE / "results"
OUTPUT = RESULTS / "tradeoff.json"

STATUS = ("EXPLORATORY, post-hoc on examined evaluation-half data; not registered; "
          "Phase 9 results unchanged")  # fmt: skip

PHASE9_INPUTS = PHASE9 / "results" / "phase9_inputs.json"
PHASE9_RESULTS = PHASE9 / "results" / "phase9_results.json"

NETWORKS = pa.SWEEP_NETWORKS
K_GRID = pa.K_GRID
SIGMA_KEYS = ("0.01", "0.005")
CONDITION = {"0.01": "realistic", "0.005": "sigma_0.005"}
CALIBRATIONS = ("C0", "C1", "C2")
C_GRID = (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0, 3.0, 4.0, 5.0)
C_ONE = C_GRID.index(1.0)
REPLICATES = 400
FALSE_ALARM_TARGET = 0.05
DECOMPOSITION_K = 2
N2_RHO = 0.9
N2_SIGMA_KEY = "0.01"
N2_CALIBRATIONS = ("C1", "C2")

CONTROL_DETECTION = "followup_tradeoff_detection"
CONTROL_FALSE_ALARM = "followup_tradeoff_false_alarm"
CONTROL_N2_DETECTION = "followup_tradeoff_n2_detection"
CONTROL_N2_FALSE_ALARM = "followup_tradeoff_n2_false_alarm"

# The registered Phase 9 noise-free band-C counts at K = 2, family "all" (s. 8 coverage,
# `phase9_results.json` networks[code].coverage.mean[sigma].per_K.K_2.families.all).
REGISTERED_BAND_C = {
    "1-LV-semiurb4--2-sw": {"0.01": (46, 975), "0.005": (94, 975)},
    "1-LV-urban6--2-sw": {"0.01": (57, 1250), "0.005": (67, 1250)},
}

PRE_STATED_READINGS = [
    "A calibration's useful power is its coverage at a calibrated 5 % false-alarm rate. A "
    "floor that is valid but conservative loses power; one that is invalid inflates coverage.",
    "The decomposition is noise-free and threshold-relative. It attributes non-detection, not "
    "causation.",
]

C3_EXCLUDED = (
    "C3 (the Newey-West studentised t) is left out of the power analysis. Task 1 measured its "
    "family-wise false-alarm rate at 0.06-0.08 under every N1 condition, i.e. above the "
    "nominal 0.05 and above C0's own 0.058-0.066, so it is anti-conservative. Coverage at a "
    "floor that does not hold its size is inflated by construction and is not comparable with "
    "C0, C1 or C2, so no C3 power number is reported."
)

CATEGORIES = ("placement", "asset_physics", "signal_strength", "detected")

JUDGEMENT_CALLS = {
    "J1": "the W6 artefacts are loaded directly and reduced with the frozen run_statistics, "
          "not through stage3_context, whose registration and 99-run barrier are Phase 9 gates",
    "J2": "the per-meter statistics are task 1's; C2's day-level variance is batched over "
          "cables and asserted equal to cal.calibration_ratios in the tests; C3 is not computed",
    "J3": "an alarm at multiplier c is `peak ratio >= c`, so one pass gives the whole curve; a "
          "non-finite ratio raises no alarm (pa.family_alarm, reading R-j)",
    "J4": "the false-alarm pass shares the day axis, counts, replicate count and sampler with "
          "the detection pass but uses a distinct control string, and pools over the 25 rules",
    "J5": "C1's noise-free floor averages over that cable's used retained days with no "
          "missing-day factor, while C0 keeps its registered 0.95 * D_ret",
    "J6": "no B/C low boundary is invented for C1: its noise-free result is a detected count "
          "and a Wilson rate only",
    "J7": "the non-reversing test is read at the downstream argmax of |k|: PV = 0 or "
          "sign(night) = sign(m) there",
    "J8": "the categories are applied in the stated order, so asset/physics precedes the "
          "signal test; the pairs it absorbs that clear the threshold are counted, not moved",
    "J9": "category (c) and detected use the downstream-restricted peak as worded; the "
          "registered band-C statistic (max over all configuration buses) is reported beside it",
    "J10": "signal-capable and the oracle use z_1 on the C1 floor; the oracle is given over all "
           "buses, as worded, and restricted to downstream(l)",
    "J11": "N2 rebuilds the evaluation-half daylight masks with ps.daylight_masks (profiles "
           "only) and refuses unless every mask matches the artefact's n_daylight_valid",
}  # fmt: skip


# --- the W6 artefacts ------------------------------------------------------------------------


def w6_specs() -> list:
    """The 89 registered W6 run specifications (s. 7), from the frozen sweep module."""
    return [spec for spec in ps.expected_specs() if spec.work_item == "W6"]


def usable_rows(arrays: dict, retained_days) -> np.ndarray:
    """The rows `run_statistics` averages over: retained, a valid daylight and night step, and
    finite stored means (reading R-b)."""
    day_index = np.asarray(arrays["day_index"], dtype=int)
    wanted = {int(d) for d in retained_days}
    keep = np.array([int(d) in wanted for d in day_index], dtype=bool)
    keep &= np.asarray(arrays["n_daylight_valid"], dtype=int) > 0
    keep &= np.asarray(arrays["n_night_valid"], dtype=int) > 0
    keep &= np.isfinite(np.asarray(arrays["dmean_daylight"], dtype=float)).all(axis=1)
    keep &= np.isfinite(np.asarray(arrays["dmean_night"], dtype=float)).all(axis=1)
    return keep


def load_w6(inputs: dict, root: Path = ps.SWEEP) -> tuple[dict, dict]:
    """Every W6 artefact of the two sweep networks, in `stage3_context`'s `loaded` shape (J1)."""
    key = ps.physics_key()
    loaded, paths = {}, []
    for spec in w6_specs():
        facts = inputs["networks"][spec.network]
        path = ps.artefact_path(spec, key, root)
        with np.load(path) as data:
            arrays = {name: np.array(data[name]) for name in ps.ARRAY_SPEC}
        if [int(b) for b in arrays["bus_index"]] != [int(b) for b in facts["lv_buses"]]:
            raise RuntimeError(f"{path}: the artefact's bus order differs from Stage 1's")
        retained = [int(d) for d in facts["days"]["retention_primary"]["retained"]]
        loaded[(spec.network, spec.work_item, spec.error, spec.factor, spec.line)] = {
            "spec": spec,
            "stats": pa.run_statistics(arrays, retained),
            "arrays": arrays,
            "usable_rows": usable_rows(arrays, retained),
        }
        paths.append(ps._reported_path(path))
    return loaded, {
        "physics_key": key,
        "W6_artefacts_read": len(loaded),
        "W6_artefacts_expected": ps.EXPECTED_RUNS["W6"],
        "read_only": True,
        "artefact_root": ps._reported_path(root / key),
        "first_artefact": paths[0] if paths else None,
    }


def network_block(code: str, inputs: dict, loaded: dict) -> dict:
    """`pa.control_network_inputs` with the per-cable usable-day masks added."""
    net = pa.control_network_inputs(code, inputs, loaded)
    net["usable_rows"] = {
        line: loaded[(code, "W6", "E-R", ps.W6_R_FACTOR, line)]["usable_rows"]
        for line in net["lines"]
    }
    net["rule_names"] = sorted(net["rules"])
    return net


# --- the noise-free reference ----------------------------------------------------------------


def c1_noise_free_floor(arrays: dict, usable: np.ndarray, sigma: float) -> float:
    """C1's floor on the noise-free day axis of one cable (J5), through task 1's `c1_floor`."""
    n_day = np.asarray(arrays["n_daylight_valid"], dtype=float)
    n_night = np.asarray(arrays["n_night_valid"], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        v = 1.0 / n_day + 1.0 / n_night
    v = np.where(np.asarray(usable, dtype=bool), v, 0.0)  # masked out by `survives` anyway
    return float(cal.c1_floor(sigma, v, np.asarray(usable, dtype=bool)[:, None])[0])


def c1_floors(net: dict, loaded: dict, sigma: float) -> dict:
    """The per-cable C1 noise-free floor of one network at one sigma_tot."""
    return {
        line: c1_noise_free_floor(
            loaded[(net["code"], "W6", "E-R", ps.W6_R_FACTOR, line)]["arrays"],
            net["usable_rows"][line], sigma,
        )
        for line in net["lines"]
    }  # fmt: skip


def detection_pairs(net: dict, k: int, high_by_line: dict):
    """The noise-free (detected, intersects) pairs at one K and a per-cable threshold, on the
    registered C_meter (the max of |k| over all of the configuration's buses)."""
    out = []
    for line in net["lines"]:
        entry = net["entries"][line]
        below = set(entry["downstream"])
        high = float(high_by_line[line])
        for name in net["rule_names"]:
            config = pa.configuration(net["rules"][name], k)
            value = pa.c_meter(entry["k"], entry["buses"], config)
            out.append((abs(value) >= high, bool(set(config) & below)))
    return out


def pair_table(pairs) -> dict:
    """Coverage over (detected, intersects) pairs, split by the W3 topological fact."""
    crossing = [p for p in pairs if p[1]]
    other = [p for p in pairs if not p[1]]
    return {
        "pairs": len(pairs),
        "detected": sum(1 for p in pairs if p[0]),
        "coverage": pa.wilson(sum(1 for p in pairs if p[0]), len(pairs)),
        "coverage_given_intersects": pa.wilson(sum(1 for p in crossing if p[0]), len(crossing)),
        "coverage_given_not_intersects": pa.wilson(sum(1 for p in other if p[0]), len(other)),
    }


def noise_free_network(code: str, net: dict, loaded: dict) -> dict:
    """Phase 9's noise-free band-C coverage with C0, and the same coverage with C1 (s. 8)."""
    out = {"network": code, "cables": len(net["lines"]), "rules": len(net["rule_names"]),
           "per_sigma": {}}  # fmt: skip
    for sigma_key in SIGMA_KEYS:
        sigma = float(sigma_key)
        bundle = net["thresholds"][sigma_key]
        c0 = pa.coverage_block(net["entries"], net["rules"], bundle, "mean")
        floors = c1_floors(net, loaded, sigma)
        per_k = {}
        for k in K_GRID:
            z = float(bundle[f"K_{k}"]["z"])
            c0_high = float(bundle[f"K_{k}"]["contrast"]["high"])
            c1_table = pair_table(detection_pairs(net, k, {l: z * f for l, f in floors.items()}))
            family = c0["per_K"][f"K_{k}"]["families"]["all"]
            per_k[f"K_{k}"] = {
                "z": z,
                "C0": {"threshold_pu": c0_high, "pairs": family["pairs"],
                       "band_counts": family["band_counts"],
                       "detected": family["band_counts"]["C"],
                       "coverage": family["coverage"],
                       "coverage_given_intersects": family["coverage_given_intersects"],
                       "coverage_given_not_intersects": family["coverage_given_not_intersects"],
                       "intersection_coverage": family["intersection_coverage"]},
                "C1": {"threshold_pu_min": z * min(floors.values()),
                       "threshold_pu_max": z * max(floors.values()),
                       "band_counts_not_reported": "J6", **c1_table},
            }  # fmt: skip
        out["per_sigma"][sigma_key] = {
            "sigma_tot": sigma,
            "C0_floor_pu": float(bundle["K_1"]["F_C_realistic"]),
            "C1_floor_pu_min": min(floors.values()),
            "C1_floor_pu_max": max(floors.values()),
            "C1_over_C0": float(np.mean(list(floors.values())) / bundle["K_1"]["F_C_realistic"]),
            "days_used_per_cable": sorted({int(net["usable_rows"][l].sum())
                                           for l in net["lines"]}),  # fmt: skip
            "per_K": per_k,
        }
    return out


def c0_reproduction(noise_free: dict) -> dict:
    """The registered noise-free band-C counts against the recomputed ones (K = 2, family all)."""
    rows, ok = {}, True
    for code, block in noise_free.items():
        rows[code] = {}
        for sigma_key, expected in REGISTERED_BAND_C[code].items():
            got = block["per_sigma"][sigma_key]["per_K"][f"K_{DECOMPOSITION_K}"]["C0"]
            match = (int(got["detected"]), int(got["pairs"])) == tuple(int(v) for v in expected)
            rows[code][sigma_key] = {
                "registered": {"detected": int(expected[0]), "pairs": int(expected[1])},
                "recomputed": {"detected": int(got["detected"]), "pairs": int(got["pairs"])},
                "reproduces": bool(match),
            }
            ok = ok and match
    return {"K": DECOMPOSITION_K, "family": "all", "per_network": rows, "reproduces": bool(ok)}


# --- the Monte Carlo passes -------------------------------------------------------------------


def population(net: dict, k: int) -> np.ndarray:
    """[cables, rules]: does the K-bus configuration intersect downstream(l)? (W3)"""
    out = np.zeros((len(net["lines"]), len(net["rule_names"])), dtype=bool)
    for row, line in enumerate(net["lines"]):
        below = {int(b) for b in net["downstream"][int(line)]}
        for column, name in enumerate(net["rule_names"]):
            out[row, column] = bool(set(pa.configuration(net["rules"][name], k)) & below)
    return out


def per_meter_ratios(x, survives, k_hat, sigma: float, v_days, c0_floor: float,
                     k_grid, calibrations) -> dict:  # fmt: skip
    """The statistic / critical-value ratio of C0, C1 and C2, batched over cables (J2).

    `x` is [cables, days, meters] (the per-day contrast of truth plus noise), `survives`
    [days, meters] and `k_hat` [cables, meters]. A ratio of at least 1 is the calibration's own
    alarm; NaN means "no statistic", which raises no alarm.
    """
    survives = np.asarray(survives, dtype=bool)
    counts = survives.sum(axis=0)
    k_abs = np.abs(np.asarray(k_hat, dtype=float))
    floor_c1 = cal.c1_floor(sigma, v_days, survives)
    centred = np.where(
        survives,
        np.asarray(x, dtype=float) - np.asarray(k_hat, dtype=float)[..., None, :],
        0.0,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        variance = (centred**2).sum(axis=-2) / np.maximum(counts - 1, 1)
        variance = np.where(counts >= 2, variance, np.nan)
        standard_error = np.sqrt(variance / np.maximum(counts, 1))
        t_stat = np.where(standard_error > 0, k_abs / standard_error, np.nan)
    out = {}
    for k in k_grid:
        z = q1.z_bonferroni(int(k))
        with np.errstate(divide="ignore", invalid="ignore"):
            ratios = {
                "C0": k_abs / (z * float(c0_floor)),
                "C1": k_abs / (z * floor_c1),
                "C2": t_stat / cal.t_critical_vector(counts - 1, int(k)),
            }
        out[k] = {name: ratios[name] for name in calibrations}
    return out


def rule_peaks(ratio, mask) -> np.ndarray:
    """The per-rule peak ratio over a configuration's meters, with `pa.family_alarm`'s rule that
    a non-finite statistic raises no alarm (J3). `ratio` is [..., meters]."""
    values = np.asarray(ratio, dtype=float)
    values = np.where(np.isfinite(values), values, 0.0)
    return np.where(np.asarray(mask, dtype=bool), values[..., None, :], -np.inf).max(axis=-1)


def iid_sampler(spec: dict, counts: dict):
    """The registered s. 10 sampler: `pa.draw_replicate` on the artefact's per-day counts."""

    def draw(rng, meters: int) -> dict:
        return pa.draw_replicate(rng, spec, counts["n_daylight_valid"],
                                 counts["n_night_valid"], meters, False)  # fmt: skip

    return draw


def n2_sampler(masks: dict, counts: dict, sigma: float, rho: float):
    """The N2 stress sampler: task 1's exact within-day AR(1) day/night means (J11)."""
    moments = cal.ar1_day_night_spec({"masks": masks, "days": counts["days"]}, sigma, rho)

    def draw(rng, meters: int) -> dict:
        return cal.draw_ar1_within_day(rng, moments, meters)

    return draw


def alarm_pass(code: str, net: dict, *, truth: str, sampler, sigma: float, c0_floor: float,
               condition: str, control: str, calibrations=CALIBRATIONS, k_grid=K_GRID,
               replicates: int = REPLICATES) -> dict:  # fmt: skip
    """One Monte Carlo pass: the alarm count of every (calibration, K, c, cable, rule).

    `truth` is "artefact" (the stored per-day contrast of every W6 cable) or "nominal" (zero,
    in which case the contrast does not depend on the cable and one truth row is run, J4).
    """
    counts = net["counts"]
    meters = len(net["buses"])
    with np.errstate(divide="ignore", invalid="ignore"):
        v_days = (1.0 / counts["n_daylight_valid"].astype(float)
                  + 1.0 / counts["n_night_valid"].astype(float))  # fmt: skip
    matrices = {k: pa.config_matrix(net["rules"], net["buses"], k) for k in k_grid}
    if truth == "nominal":
        truth_contrast = np.zeros((1, counts["simulated_days"], meters))
    elif truth == "artefact":
        truth_contrast = np.asarray(net["truth_contrast"], dtype=float)
    else:
        raise ValueError(f"{truth} is not a truth mode")
    rows = truth_contrast.shape[0]
    names = net["rule_names"]
    tally = {(name, k): np.zeros((len(C_GRID), rows, len(names)), dtype=np.int32)
             for name in calibrations for k in k_grid}  # fmt: skip
    diagnostics = {"meter_days_without_a_reading": 0, "meters_with_fewer_than_two_kept_days": 0}
    grid = np.asarray(C_GRID, dtype=float)[:, None, None]
    rng = pa.control_rng(code, condition, control, 0)
    for _ in range(int(replicates)):
        draws = sampler(rng, meters)
        survives = draws["survives"]
        kept = survives.sum(axis=0)
        diagnostics["meter_days_without_a_reading"] += int((kept == 0).sum())
        diagnostics["meters_with_fewer_than_two_kept_days"] += int((kept < 2).sum())
        x = truth_contrast + (draws["day"] - draws["night"])
        k_hat = pa.survival_mean(x, survives)
        ratios = per_meter_ratios(x, survives, k_hat, sigma, v_days, c0_floor, k_grid,
                                  calibrations)  # fmt: skip
        for k in k_grid:
            mask = matrices[k][0]
            for name in calibrations:
                peaks = rule_peaks(ratios[k][name], mask)
                tally[(name, k)] += (peaks[None, :, :] >= grid)
    return {"tally": tally, "rule_names": names, "replicates": int(replicates),
            "truth": truth, "truth_rows": rows, "diagnostics": diagnostics,
            "calibrations": tuple(calibrations), "k_grid": tuple(k_grid)}  # fmt: skip


def detection_block(net: dict, result: dict) -> dict:
    """Deliverable 2: detection probability per pair, coverage, and the two conditionals."""
    replicates = result["replicates"]
    out = {}
    for k in result["k_grid"]:
        crossing = population(net, k)
        per_cal = {}
        for name in result["calibrations"]:
            successes = result["tally"][(name, k)][C_ONE]  # [cables, rules]
            total = int(successes.sum())
            pairs = successes.size
            per_cal[name] = {
                "coverage": pa.rate_record(total, pairs * replicates),
                "detect_given_meter_downstream": pa.rate_record(
                    int(successes[crossing].sum()), int(crossing.sum()) * replicates),
                "detect_given_no_meter_downstream": pa.rate_record(
                    int(successes[~crossing].sum()), int((~crossing).sum()) * replicates),
                "pairs": pairs,
                "pairs_with_a_meter_downstream": int(crossing.sum()),
                "per_pair_successes": [[int(v) for v in row] for row in successes],
            }
        out[f"K_{k}"] = {"z": q1.z_bonferroni(k), "replicates": replicates,
                         "cables": len(net["lines"]), "rules": len(net["rule_names"]),
                         "per_pair_successes_row_order": [int(l) for l in net["lines"]],
                         "per_pair_successes_column_order": list(net["rule_names"]),
                         "calibrations": per_cal}  # fmt: skip
    return out


def coverage_at_rate(rates, coverages, target: float = FALSE_ALARM_TARGET) -> dict:
    """Coverage where the false-alarm rate crosses `target`, interpolated linearly in c.

    The false-alarm rate falls with c, so the crossing is the first grid point at or below
    `target`. Both not-bracketed cases get a typed record and no number.
    """
    rates = [float(r) for r in rates]
    coverages = [float(c) for c in coverages]
    if len(rates) != len(C_GRID) or len(coverages) != len(C_GRID):
        raise ValueError("one false-alarm rate and one coverage per c grid point is required")
    out = {"target_false_alarm": float(target), "c_star": None, "coverage": None,
           "bracket": None}  # fmt: skip
    crossed = [i for i, r in enumerate(rates) if r <= float(target)]
    if not crossed:
        return {**out, "record": "not_bracketed_above",
                "note": f"the false-alarm rate exceeds the target at every c; the largest c "
                        f"on the grid ({C_GRID[-1]:g}) still gives {rates[-1]:.4f}"}  # fmt: skip
    first = crossed[0]
    if first == 0:
        return {**out, "record": "not_bracketed_below", "c_star_at_most": float(C_GRID[0]),
                "coverage_at_c_grid_minimum": coverages[0],
                "note": f"the rate is already at or below the target at the smallest c "
                        f"({C_GRID[0]:g}), so the crossing is not bracketed from below"}  # fmt: skip
    low, high = float(C_GRID[first - 1]), float(C_GRID[first])
    rate_low, rate_high = rates[first - 1], rates[first]
    share = (rate_low - float(target)) / (rate_low - rate_high)
    c_star = low + share * (high - low)
    coverage = coverages[first - 1] + share * (coverages[first] - coverages[first - 1])
    return {
        **out,
        "record": "interpolated",
        "c_star": float(c_star),
        "coverage": float(coverage),
        "bracket": {"c_low": low, "c_high": high, "false_alarm_low": rate_low,
                    "false_alarm_high": rate_high, "coverage_low": coverages[first - 1],
                    "coverage_high": coverages[first]},  # fmt: skip
        "note": "linear in c between the bracketing grid points, for both the rate and coverage",
    }


def tradeoff_block(net: dict, detection: dict, false_alarm: dict) -> dict:
    """Deliverable 3: the curve, and coverage at a calibrated 5 % false-alarm rate."""
    replicates = detection["replicates"]
    out = {}
    for k in detection["k_grid"]:
        per_cal = {}
        for name in detection["calibrations"]:
            cov = detection["tally"][(name, k)]  # [c, cables, rules]
            fa = false_alarm["tally"][(name, k)]  # [c, 1, rules]
            pair_trials = cov.shape[1] * cov.shape[2] * replicates
            fa_trials = fa.shape[2] * false_alarm["replicates"]
            curve = []
            for index, c in enumerate(C_GRID):
                curve.append({
                    "c": float(c),
                    "false_alarm": pa.rate_record(int(fa[index].sum()), fa_trials),
                    "coverage": pa.rate_record(int(cov[index].sum()), pair_trials),
                })
            per_cal[name] = {
                "per_c": curve,
                "coverage_at_calibrated_5pc_false_alarm": coverage_at_rate(
                    [row["false_alarm"]["rate"] for row in curve],
                    [row["coverage"]["rate"] for row in curve]),
                "false_alarm_trials": fa_trials,
                "coverage_trials": pair_trials,
            }
        out[f"K_{k}"] = {"z": q1.z_bonferroni(k), "calibrations": per_cal}
    return out


# --- the limitation decomposition --------------------------------------------------------------


def decomposition_network(code: str, net: dict, loaded: dict, sigma_key: str,
                          k: int = DECOMPOSITION_K) -> dict:  # fmt: skip
    """Deliverable 4: every (cable, rule) pair in exactly one category, noise-free, at the C1
    threshold, plus the cable-level ceilings (J7-J10)."""
    sigma = float(sigma_key)
    floors = c1_floors(net, loaded, sigma)
    z_k, z_1 = q1.z_bonferroni(int(k)), q1.z_bonferroni(1)
    facts = net["facts"]["cable_facts"]
    counts = {name: 0 for name in CATEGORIES}
    absorbed, registered_detected, disagree = 0, 0, 0
    signal_capable, oracle_downstream, s_zero, non_reversing_cables = 0, 0, 0, 0
    per_cable = {}
    for line in net["lines"]:
        entry = net["entries"][line]
        buses, below = entry["buses"], set(entry["downstream"])
        high = z_k * floors[line]
        columns = [buses.index(b) for b in sorted(below) if b in buses]
        if not columns:
            raise RuntimeError(f"{code} line {line}: no downstream bus is an LV bus")
        best = columns[int(np.argmax(np.abs(entry["k"][columns])))]
        cable = facts[str(line)]
        installed_pv = float(cable["installed_pv_sn_mva"])
        non_reversing = bool(
            installed_pv == 0.0
            or np.sign(entry["night"][best]) == np.sign(entry["m"][best])
        )  # fmt: skip
        peak_all = float(np.abs(entry["k"]).max())
        peak_downstream = float(np.abs(entry["k"][columns]).max())
        capable = bool(peak_all >= z_1 * floors[line])
        signal_capable += int(capable)
        oracle_downstream += int(peak_downstream >= z_1 * floors[line])
        s_zero += int(float(cable["S_l"]) == 0.0)
        non_reversing_cables += int(non_reversing)
        per_line = {name: 0 for name in CATEGORIES}
        for name in net["rule_names"]:
            config = pa.configuration(net["rules"][name], int(k))
            inside = [b for b in config if b in below]
            pair_peak = pa.c_meter(entry["k"], buses, inside) if inside else 0.0
            registered = pa.c_meter(entry["k"], buses, config)
            detected_registered = abs(registered) >= high
            registered_detected += int(detected_registered)
            if not inside:
                category = "placement"
            elif non_reversing:
                category = "asset_physics"
                absorbed += int(abs(pair_peak) >= high)
            elif abs(pair_peak) >= high:
                category = "detected"
            else:
                category = "signal_strength"
            disagree += int((category == "detected") != detected_registered)
            counts[category] += 1
            per_line[category] += 1
        per_cable[str(line)] = {
            "C1_floor_pu": floors[line],
            "threshold_pu": high,
            "max_abs_k_all_buses_pu": peak_all,
            "max_abs_k_downstream_pu": peak_downstream,
            "downstream_argmax_bus": int(buses[best]),
            "sign_m_at_argmax": int(np.sign(entry["m"][best])),
            "sign_night_at_argmax": int(np.sign(entry["night"][best])),
            "installed_pv_sn_mva": installed_pv,
            "S_l": float(cable["S_l"]),
            "non_reversing": non_reversing,
            "signal_capable": capable,
            "categories": per_line,
        }
    total = len(net["lines"]) * len(net["rule_names"])
    if sum(counts.values()) != total:
        raise RuntimeError(f"{code}: the categories count {sum(counts.values())} of {total} pairs")
    cables = len(net["lines"])
    return {
        "network": code, "sigma_tot": sigma, "K": int(k), "threshold": "z_K * F_C1",
        "pairs": total, "cables": cables, "rules": len(net["rule_names"]),
        "categories": counts,
        "category_shares": {name: counts[name] / total for name in CATEGORIES},
        "categories_sum_to_the_pairs": True,
        "asset_physics_pairs_above_threshold": absorbed,
        "registered_C_meter_detected_pairs": registered_detected,
        "pairs_where_the_two_statistics_disagree": disagree,
        "signal_capable_cables": signal_capable,
        "cables_with_S_l_zero": s_zero,
        "non_reversing_cables": non_reversing_cables,
        "oracle_single_meter_coverage_all_buses": pa.wilson(signal_capable, cables),
        "oracle_single_meter_coverage_downstream_only": pa.wilson(oracle_downstream, cables),
        "oracle_threshold": "z_1 * F_C1, the most generous Bonferroni threshold (J10)",
        "per_cable": per_cable,
    }  # fmt: skip


# --- the run -----------------------------------------------------------------------------------


def evaluation_masks(code: str, net: dict) -> dict:
    """The per-day daylight masks of the evaluation-half simulator axis (J11)."""
    from gridpulse import dual_study as ds

    days = [int(d) for d in net["counts"]["days"]]
    network = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    masks = {int(d): np.asarray(m, dtype=bool) for d, m in ps.daylight_masks(network, days).items()}
    expected = np.asarray(net["counts"]["n_daylight_valid"], dtype=int)
    got = np.array([int(masks[d].sum()) for d in days], dtype=int)
    if not np.array_equal(got, expected):
        raise RuntimeError(f"{code}: the rebuilt daylight masks differ from the artefact's "
                           "n_daylight_valid")  # fmt: skip
    return masks


def run(output: Path = OUTPUT, *, replicates: int = REPLICATES, networks=NETWORKS) -> dict:
    """Everything, into one write-once JSON. The pre-stated readings are placed in the payload
    before any number below exists and are never rewritten."""
    output = Path(output)
    if output.exists():  # refuse before any artefact is read, not after the Monte Carlo
        raise RuntimeError(f"refusing to overwrite {output}")
    payload: dict = {
        "task": "Phase 9 follow-up 2: calibrated detection trade-off and limitation "
                "decomposition",
        "status": STATUS,
        "pre_stated_readings": list(PRE_STATED_READINGS),  # written before anything is computed
        "C3_excluded_from_the_power_analysis": C3_EXCLUDED,
        "judgement_calls": JUDGEMENT_CALLS,
        "grids": {
            "networks": list(networks),
            "sigma_tot": [float(s) for s in SIGMA_KEYS],
            "conditions": dict(CONDITION),
            "K_grid": list(K_GRID),
            "c_grid": list(C_GRID),
            "calibrations": list(CALIBRATIONS),
            "replicates": int(replicates),
            "false_alarm_target": FALSE_ALARM_TARGET,
            "decomposition_K": DECOMPOSITION_K,
            "N2": {"rho": N2_RHO, "sigma_tot": float(N2_SIGMA_KEY),
                   "K": DECOMPOSITION_K, "calibrations": list(N2_CALIBRATIONS)},  # fmt: skip
        },
        "interval_label": "descriptive Wilson 95 % (Phase 9 reading R-l). One replicate is one "
                          "measurement realisation shared by every (cable, rule) pair, so the "
                          "pooled trials are not independent and the interval is narrower than "
                          "a true sampling interval.",
        "provenance": {
            "phase9_registration": pa.REGISTRATION,
            "phase9_registration_sha256": pa.REGISTRATION_SHA256,
            "phase9_inputs": str(PHASE9_INPUTS.relative_to(REPO)),
            "phase9_results": str(PHASE9_RESULTS.relative_to(REPO)),
            "task1_calibration": "analysis/phase9_followup/results/calibration.json",
            "reused_phase9_functions": [
                "run_statistics", "coverage_block", "c_meter", "configuration", "wilson",
                "rate_record", "control_network_inputs", "meter_days", "draw_replicate",
                "survival_mean", "config_matrix", "family_alarm (its rule, via rule_peaks)",
                "control_rng", "noise_spec", "ps.expected_specs", "ps.artefact_path",
                "ps.daylight_masks", "q1.z_bonferroni", "q1.write_new_json",
            ],
            "reused_task1_functions": [
                "cal.c1_floor", "cal.t_critical_vector", "cal.ar1_day_night_spec",
                "cal.draw_ar1_within_day", "cal.registered_floor", "cal.evaluation_axis",
                "cal.axis_from_counts (through cal.evaluation_axis)",
            ],
            "power_flows_run": 0,
            "vm_arrays_loaded": 0,
            "held_out_networks_touched": 0,
            "phase9_files_written": 0,
            "frozen_evaluations_rerun": 0,
        },
    }

    inputs = json.loads(PHASE9_INPUTS.read_text())
    loaded, artefacts = load_w6(inputs)
    payload["provenance"]["artefacts"] = artefacts

    nets = {code: network_block(code, inputs, loaded) for code in networks}

    # 1. the noise-free reference; the run refuses if C0 does not reproduce
    payload["noise_free_reference"] = {code: noise_free_network(code, nets[code], loaded)
                                       for code in networks}  # fmt: skip
    payload["C0_reproduction"] = c0_reproduction(payload["noise_free_reference"])
    if not payload["C0_reproduction"]["reproduces"]:
        raise RuntimeError("C0 does not reproduce Phase 9's noise-free band-C counts: "
                           f"{json.dumps(payload['C0_reproduction'], indent=1)}")  # fmt: skip

    # the registered floor, cross-checked against task 1's rebuilt evaluation axis
    cross_check, floors = {}, {}
    for code in networks:
        axis = cal.evaluation_axis(code, inputs)
        cross_check[code] = {}
        for sigma_key in SIGMA_KEYS:
            registered = float(nets[code]["thresholds"][sigma_key]["K_1"]["F_C_realistic"])
            rebuilt = cal.registered_floor(float(sigma_key), axis)
            cross_check[code][sigma_key] = {
                "registered_inputs_pu": registered, "rebuilt_from_task1_axis_pu": rebuilt,
                "agree": bool(abs(registered - rebuilt) <= 1e-12 * max(registered, rebuilt)),
            }  # fmt: skip
            floors[(code, sigma_key)] = registered
    payload["C0_floor_cross_check"] = cross_check

    # 2-3. detection, false alarms and the trade-off curve
    detection, tradeoff = {}, {}
    for code in networks:
        net = nets[code]
        detection[code], tradeoff[code] = {}, {}
        for sigma_key in SIGMA_KEYS:
            condition = CONDITION[sigma_key]
            spec = pa.noise_spec(condition)
            sampler = iid_sampler(spec, net["counts"])
            shared = {"sigma": float(sigma_key), "c0_floor": floors[(code, sigma_key)],
                      "condition": condition, "replicates": replicates}  # fmt: skip
            hit = alarm_pass(code, net, truth="artefact", sampler=sampler,
                             control=CONTROL_DETECTION, **shared)  # fmt: skip
            miss = alarm_pass(code, net, truth="nominal", sampler=sampler,
                              control=CONTROL_FALSE_ALARM, **shared)  # fmt: skip
            detection[code][sigma_key] = {
                "condition": condition, "spec": spec,
                "day_axis": {"simulated_days": net["counts"]["simulated_days"],
                             "retained_days": net["counts"]["retained_days"],
                             "delay_removed_day": net["counts"]["delay_removed_day"],
                             "dropped_not_usable": net["counts"]["dropped_not_usable"]},
                "diagnostics": {"detection": hit["diagnostics"],
                                "false_alarm": miss["diagnostics"]},
                "per_K": detection_block(net, hit),
            }  # fmt: skip
            tradeoff[code][sigma_key] = {"condition": condition,
                                         "per_K": tradeoff_block(net, hit, miss)}  # fmt: skip
    payload["detection_with_noise"] = detection
    payload["tradeoff"] = tradeoff

    # 3b. the N2 stress scenario, C1 and C2 only, at sigma 0.01 and K = 2
    stress = {}
    for code in networks:
        net = nets[code]
        masks = evaluation_masks(code, net)
        sampler = n2_sampler(masks, net["counts"], float(N2_SIGMA_KEY), N2_RHO)
        shared = {"sigma": float(N2_SIGMA_KEY), "c0_floor": floors[(code, N2_SIGMA_KEY)],
                  "condition": f"ar1_within_day_rho_{N2_RHO:g}", "replicates": replicates,
                  "calibrations": N2_CALIBRATIONS, "k_grid": (DECOMPOSITION_K,)}  # fmt: skip
        hit = alarm_pass(code, net, truth="artefact", sampler=sampler,
                         control=CONTROL_N2_DETECTION, **shared)  # fmt: skip
        miss = alarm_pass(code, net, truth="nominal", sampler=sampler,
                          control=CONTROL_N2_FALSE_ALARM, **shared)  # fmt: skip
        stress[code] = {
            "scenario": "N2, within-day AR(1) reading noise, exact bivariate day/night means",
            "rho": N2_RHO, "sigma_tot": float(N2_SIGMA_KEY), "K": DECOMPOSITION_K,
            "calibrations": list(N2_CALIBRATIONS),
            "per_K": tradeoff_block(net, hit, miss),
            "detection_per_K": detection_block(net, hit),
        }  # fmt: skip
    payload["stress_N2"] = stress

    # 4. the limitation decomposition
    payload["limitation_decomposition"] = {
        code: {sigma_key: decomposition_network(code, nets[code], loaded, sigma_key)
               for sigma_key in SIGMA_KEYS}
        for code in networks
    }  # fmt: skip

    payload = q1._plain(payload)  # numpy scalars and arrays to plain JSON, as Phase 9 does
    sha = q1.write_new_json(Path(output), payload)
    payload["_sha256"] = sha
    payload["_path"] = str(Path(output))
    return payload


def check(networks=NETWORKS) -> dict:
    """The cheap blocks only: the noise-free reference, the C0 reproduction and the
    decomposition. Nothing is written."""
    inputs = json.loads(PHASE9_INPUTS.read_text())
    loaded, artefacts = load_w6(inputs)
    nets = {code: network_block(code, inputs, loaded) for code in networks}
    noise_free = {code: noise_free_network(code, nets[code], loaded) for code in networks}
    return q1._plain({
        "status": STATUS, "pre_stated_readings": list(PRE_STATED_READINGS),
        "C3_excluded_from_the_power_analysis": C3_EXCLUDED,
        "provenance": {"artefacts": artefacts},
        "grids": {"networks": list(networks), "K_grid": list(K_GRID),
                  "sigma_tot": [float(s) for s in SIGMA_KEYS],
                  "decomposition_K": DECOMPOSITION_K},  # fmt: skip
        "noise_free_reference": noise_free,
        "C0_reproduction": c0_reproduction(noise_free),
        "limitation_decomposition": {
            code: {sigma_key: decomposition_network(code, nets[code], loaded, sigma_key)
                   for sigma_key in SIGMA_KEYS}
            for code in networks
        },
    })


# --- the compact summary ------------------------------------------------------------------------


def _short(code: str) -> str:
    return code.split("-")[2]


def print_inputs(payload: dict) -> None:
    artefacts = payload["provenance"]["artefacts"]
    print(f"\n== 0. inputs ==\n  W6 artefacts read {artefacts['W6_artefacts_read']} of "
          f"{artefacts['W6_artefacts_expected']} (read-only) under {artefacts['artefact_root']}")
    print(f"  power flows {payload['provenance']['power_flows_run']}, vm arrays "
          f"{payload['provenance']['vm_arrays_loaded']}, held-out networks "
          f"{payload['provenance']['held_out_networks_touched']}, Phase 9 files written "
          f"{payload['provenance']['phase9_files_written']}, frozen evaluations re-run "
          f"{payload['provenance']['frozen_evaluations_rerun']}")
    for code, rows in payload.get("C0_floor_cross_check", {}).items():
        for sigma_key, row in rows.items():
            print(f"  C0 floor {_short(code):<9} sigma={sigma_key:<6} registered "
                  f"{row['registered_inputs_pu']:.6e} rebuilt {row['rebuilt_from_task1_axis_pu']:.6e}"
                  f"  agree={row['agree']}")
    for code, by_sigma in payload.get("detection_with_noise", {}).items():
        for sigma_key, block in by_sigma.items():
            axis = block["day_axis"]
            print(f"  axis {_short(code):<9} sigma={sigma_key:<6} simulated "
                  f"{axis['simulated_days']} of {axis['retained_days']} retained "
                  f"(delay drops day {axis['delay_removed_day']}, not usable "
                  f"{axis['dropped_not_usable']})  diagnostics {block['diagnostics']}")


def print_noise_free(payload: dict) -> None:
    print("\n== 1. noise-free band-C coverage (W6 cables x 25 rules) ==")
    repro = payload["C0_reproduction"]
    for code, rows in repro["per_network"].items():
        for sigma_key, row in rows.items():
            print(f"  C0 reproduction {_short(code):<9} sigma={sigma_key:<6} "
                  f"registered {row['registered']['detected']}/{row['registered']['pairs']}  "
                  f"recomputed {row['recomputed']['detected']}/{row['recomputed']['pairs']}  "
                  f"{'ok' if row['reproduces'] else 'MISMATCH'}")
    print(f"  reproduces: {repro['reproduces']}")
    print(f"\n  {'network':<10}{'sigma':>7}{'cal':>5}" + "".join(
        f"{'K=' + str(k):>26}" for k in payload["grids"]["K_grid"]))
    for code, block in payload["noise_free_reference"].items():
        for sigma_key, per_sigma in block["per_sigma"].items():
            for cal_name in ("C0", "C1"):
                cells = []
                for k in payload["grids"]["K_grid"]:
                    entry = per_sigma["per_K"][f"K_{k}"][cal_name]
                    cells.append(f"{entry['detected']:>4}/{entry['pairs']}"
                                 f" ({entry['coverage']['rate']:.4f})".rjust(26))
                print(f"  {_short(code):<10}{sigma_key:>7}{cal_name:>5}" + "".join(cells))
            print(f"  {'':<10}{'':>7}{'':>5}  C1/C0 floor ratio "
                  f"{per_sigma['C1_over_C0']:.4f}  C0 floor {per_sigma['C0_floor_pu']:.3e} "
                  f"C1 floor {per_sigma['C1_floor_pu_min']:.3e}"
                  f"-{per_sigma['C1_floor_pu_max']:.3e} p.u.")


def print_detection(payload: dict) -> None:
    print("\n== 2. detection with noise (truth = the W6 artefact, 400 replicates) ==")
    print(f"  {'network':<10}{'sigma':>7}{'cal':>5}" + "".join(
        f"{'K=' + str(k) + ' cov | down | not':>28}" for k in payload["grids"]["K_grid"]))
    for code, by_sigma in payload["detection_with_noise"].items():
        for sigma_key, block in by_sigma.items():
            for cal_name in payload["grids"]["calibrations"]:
                cells = []
                for k in payload["grids"]["K_grid"]:
                    entry = block["per_K"][f"K_{k}"]["calibrations"][cal_name]
                    cells.append(f"{entry['coverage']['rate']:.4f} | "
                                 f"{entry['detect_given_meter_downstream']['rate']:.4f} | "
                                 f"{entry['detect_given_no_meter_downstream']['rate']:.4f}"
                                 .rjust(28))
                print(f"  {_short(code):<10}{sigma_key:>7}{cal_name:>5}" + "".join(cells))


def print_tradeoff(payload: dict) -> None:
    print("\n== 3. trade-off: false alarm / coverage at each c, worst network per cell ==")
    for code, by_sigma in payload["tradeoff"].items():
        for sigma_key, block in by_sigma.items():
            for k in payload["grids"]["K_grid"]:
                for cal_name in payload["grids"]["calibrations"]:
                    entry = block["per_K"][f"K_{k}"]["calibrations"][cal_name]
                    curve = "  ".join(
                        f"{row['c']:g}:{row['false_alarm']['rate']:.3f}/"
                        f"{row['coverage']['rate']:.3f}" for row in entry["per_c"])
                    print(f"  {_short(code):<9} sigma={sigma_key:<6} K={k} {cal_name}  {curve}")
    first = next(iter(payload["tradeoff"].values()))
    cell = next(iter(first.values()))["per_K"]["K_2"]["calibrations"][
        payload["grids"]["calibrations"][0]]
    print(f"\n  trials per cell: coverage {cell['coverage_trials']} (pairs x replicates), "
          f"false alarms {cell['false_alarm_trials']} (25 rules x replicates, pooled: under "
          "truth = nominal the contrast does not depend on the cable, J4)")
    print("\n== 3b. coverage at a calibrated 5 % false-alarm rate ==")
    print(f"  {'network':<10}{'sigma':>7}{'cal':>5}" + "".join(
        f"{'K=' + str(k) + ' c*/coverage':>24}" for k in payload["grids"]["K_grid"]))
    for code, by_sigma in payload["tradeoff"].items():
        for sigma_key, block in by_sigma.items():
            for cal_name in payload["grids"]["calibrations"]:
                cells = []
                for k in payload["grids"]["K_grid"]:
                    record = (block["per_K"][f"K_{k}"]["calibrations"][cal_name]
                              ["coverage_at_calibrated_5pc_false_alarm"])
                    if record["record"] == "interpolated":
                        text = f"{record['c_star']:.3f} / {record['coverage']:.4f}"
                    elif record["record"] == "not_bracketed_below":
                        text = f"<={record['c_star_at_most']:g} / " \
                               f">={record['coverage_at_c_grid_minimum']:.4f}"
                    else:
                        text = "not bracketed above"
                    cells.append(text.rjust(24))
                print(f"  {_short(code):<10}{sigma_key:>7}{cal_name:>5}" + "".join(cells))
    print("\n== 3c. N2 stress (within-day AR(1), rho = 0.9), sigma 0.01, K = 2 ==")
    for code, block in payload["stress_N2"].items():
        for cal_name in block["calibrations"]:
            entry = block["per_K"][f"K_{block['K']}"]["calibrations"][cal_name]
            curve = "  ".join(f"{row['c']:g}:{row['false_alarm']['rate']:.3f}/"
                              f"{row['coverage']['rate']:.3f}" for row in entry["per_c"])
            record = entry["coverage_at_calibrated_5pc_false_alarm"]
            print(f"  {_short(code):<9} {cal_name}  {curve}")
            print(f"  {'':<9} {'':<2} at 5 % false alarms: {record['record']} "
                  + (f"c*={record['c_star']:.3f} coverage={record['coverage']:.4f}"
                     if record["record"] == "interpolated" else ""))


def print_decomposition(payload: dict) -> None:
    print("\n== 4. limitation decomposition (noise-free, C1 threshold, K = 2) ==")
    print(f"  {'network':<10}{'sigma':>7}{'pairs':>7}" + "".join(
        f"{name:>18}" for name in CATEGORIES))
    for code, by_sigma in payload["limitation_decomposition"].items():
        for sigma_key, block in by_sigma.items():
            cells = "".join(
                f"{block['categories'][name]} ({block['category_shares'][name]:.3f})".rjust(18)
                for name in CATEGORIES)
            print(f"  {_short(code):<10}{sigma_key:>7}{block['pairs']:>7}" + cells)
    print("\n  cable-level ceilings and cross-checks")
    for code, by_sigma in payload["limitation_decomposition"].items():
        for sigma_key, block in by_sigma.items():
            print(f"  {_short(code):<9} sigma={sigma_key:<6} cables={block['cables']}  "
                  f"signal-capable={block['signal_capable_cables']}  "
                  f"S_l=0: {block['cables_with_S_l_zero']}  "
                  f"non-reversing={block['non_reversing_cables']}")
            print(f"  {'':<9} oracle single meter: all buses "
                  f"{block['oracle_single_meter_coverage_all_buses']['rate']:.4f}, "
                  f"downstream only "
                  f"{block['oracle_single_meter_coverage_downstream_only']['rate']:.4f}; "
                  f"(b) pairs above the threshold {block['asset_physics_pairs_above_threshold']}; "
                  f"registered C_meter detects {block['registered_C_meter_detected_pairs']} "
                  f"(disagrees on {block['pairs_where_the_two_statistics_disagree']})")


def print_summary(payload: dict) -> None:
    """The report tables, printed from the payload: no ad-hoc JSON parsing downstream."""
    print(f"status: {payload['status']}")
    for reading in payload["pre_stated_readings"]:
        print(f"  pre-stated: {reading}")
    print(f"  C3: {payload['C3_excluded_from_the_power_analysis']}")
    print_inputs(payload)
    print_noise_free(payload)
    if "detection_with_noise" in payload:
        print_detection(payload)
        print_tradeoff(payload)
    print_decomposition(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("run", "summary", "check"))
    parser.add_argument("--out", default=str(OUTPUT))
    parser.add_argument("--replicates", type=int, default=REPLICATES)
    parser.add_argument("--networks", nargs="*", default=list(NETWORKS))
    args = parser.parse_args(argv)
    if args.command == "run":
        payload = run(Path(args.out), replicates=args.replicates, networks=tuple(args.networks))
        print(f"wrote {args.out} sha256={payload['_sha256']}\n")
    elif args.command == "check":
        payload = check(networks=tuple(args.networks))
    else:
        payload = json.loads(Path(args.out).read_text())
    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
