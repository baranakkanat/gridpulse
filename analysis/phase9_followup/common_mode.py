"""Phase 9 follow-up, task 3: does referencing to the substation busbar cancel common-mode
diurnal error?

EXPLORATORY. It runs **zero power flows**, reads only cached Phase 8 `mv_daily` states and
cached Phase 5 `nominal` states, loads **no held-out network**, re-runs **no frozen
evaluation**, touches **no Phase 9 file** and writes nothing outside
`analysis/phase9_followup/`. Nothing here is registered and nothing here reinterprets a
registered Phase 9 failure.

Phase 9 s. 8 found that a diurnal systematic error of 0.01 sigma_tot doubles the false-alarm
rate. One physically realistic, *common-mode* diurnal error is already cached: Phase 8's
`mv_daily` truth, whose MV slack voltage rises with the network's PV output
(`src/gridpulse/stress.py` `mv_profile`, +0.03 p.u. x PV share). The operator's nominal model
assumes a fixed MV voltage, so Delta_mv = vm(mv_daily) - vm(nominal) is a pure model error
with no cable fault, and every alarm it raises is a false alarm.

The candidate remedy is the **busbar-referenced contrast**

    k_ref(b) = mean over the meter's kept days of [ y_d(b) - y_d(busbar) ],

with y the measured daylight-minus-night per-day contrast. The LV busbar voltage is measured
at the substation (`noise_study.CONDITIONS[...].sigma_v_substation` = 0.002 p.u. per reading,
every quarter-hour, no missingness and no delay), so a common-mode shift cancels while a
downstream cable fault leaves the busbar nearly unchanged.

Three questions, on the two sweep networks, sigma_tot in {0.01, 0.005}, K in {1, 2, 4} and the
25 frozen placement rules:

1. **Delta_mv as a false-alarm source, noise-free.** The raw k_mv and the referenced
   k_mv - k_mv(busbar) per bus (max and median |.|) against the C1 threshold, and the fraction
   of the 25 configurations that alarm, raw against referenced.
2. **With noise.** `realistic` / `sigma_0.005` meter noise plus substation noise on top of
   Delta_mv, 400 replicates: family-wise false-alarm rates for raw and referenced C1 and C2.
   The referenced floor is derived explicitly as F_ref^2 = F_meter^2 + F_busbar^2 over the
   shared kept days.
3. **Signal retention.** On the 89 W6 artefacts, the noise-free K = 2 coverage of the
   referenced contrast against the raw C1 coverage, with the busbar |k| per cable beside it.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/common_mode.py check
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/common_mode.py run
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9_followup/common_mode.py summary

`run` writes `results/common_mode.json` once and refuses to overwrite it. `check` prints the
noise-free and retention blocks and writes nothing.

Judgement calls (numbered, and repeated in the output JSON)
-----------------------------------------------------------
J1  Referencing is **day-matched**: the busbar contrast of the *same* day is subtracted before
    averaging, not the busbar's own all-day mean. That is what makes F_ref^2 = F_meter^2 +
    F_busbar^2 exact over one shared kept-day set, and it cancels a common-mode shift even when
    the shift varies from day to day. Noise-free and without missingness the two forms
    coincide, so deliverable 1's `k_mv - k_mv(busbar)` is unaffected.
J2  The busbar signal is read from the `vm` column of the LV busbar bus, not from the
    `trafo` `vm_lv_pu` field that `sensing.observe` samples. The reduction checks the two agree
    to 1e-6 p.u. on every loaded step and reports the worst difference
    (`busbar_vm_vs_trafo_max_abs_diff`).
J3  The day axes follow task 2: the noise-free blocks average over the **usable** retained days
    (retained, a valid daylight and night step, finite means), and the noise block uses
    `pa.meter_days`, which additionally drops the last retained day for the 1-day remote delay.
    The busbar has no delay, but the statistic it is subtracted from does, so the referenced
    contrast inherits the meter's axis.
J4  Substation noise is drawn as two independent per-day leg means,
    sigma_sub / sqrt(n_d) and sigma_sub / sqrt(m_d), on the *same* valid-step counts the meter
    averages over, after `pa.draw_replicate`'s four draws. One busbar series is shared by every
    meter of a replicate, which is the physical situation and is what makes the referenced
    noise correlated across meters.
J5  The referenced contrast is read against its **own** C1 floor,
    sqrt(sigma_tot^2 + sigma_sub^2) x sqrt(sum_{d in S} v_d) / |S|, because that is the valid
    floor for the statistic actually formed. The referenced statistic against the *raw* floor
    is reported beside it as a diagnostic, since the task words deliverable 1 that way.
J6  C2 is computed here with a small local helper rather than `cal.calibration_ratios`, which
    also builds the Newey-West C3 arm this task does not use. The helper is the same sum of
    squared centred kept-day deviations; `tests/test_common_mode.py` asserts the two agree to
    1e-12 on a toy array. C0 and C3 are not computed at all.
J7  Deliverable 1's alarm fraction is the s. 8 family event (max |k| over the configuration's
    buses >= z_K x F) on the 25 rules of each network, counted per network and pooled over the
    two, exactly as Phase 9's noise-free coverage counts a configuration.
J8  The retention block reuses task 2's noise-free machinery unchanged
    (`td.load_w6`, `td.network_block`, `td.c1_floors`, `td.pair_table`); only the contrast and
    the floor change. The raw arm is therefore bit-identical to task 2's noise-free C1 at
    K = 2, which the run asserts.
J9  The Delta_mv reduction is cast to the frozen s. 7 artefact shape with `ps.build_arrays`,
    so its per-day means are float32 exactly as the W6 artefacts are. The quantisation of a
    6e-3 p.u. mean is about 5e-10 p.u., three orders below the referenced residual being
    measured, and it keeps the two legs of deliverable 3 on one precision.
J10 A **paired zero-truth control** is run beside the Delta_mv arm in deliverable 2: the same
    replicate's draws are re-read against a zero truth. Without it a referenced rate cannot be
    attributed, because part of it is the calibration's own size and part is the residual,
    non-common-mode piece of Delta_mv. It is a diagnostic, not a deliverable; being paired, it
    is not an independent estimate of the same quantity.
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
for _path in (PHASE9, HERE):  # the frozen Phase 9 modules and tasks 1-2 are imported, not copied
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import calibration as cal  # noqa: E402  (task 1, this follow-up)
import numpy as np  # noqa: E402
import phase9_analysis as pa  # noqa: E402
import phase9_sweep as ps  # noqa: E402
import q1_voltage_residual as q1  # noqa: E402
import tradeoff as td  # noqa: E402  (task 2, this follow-up)

RESULTS = HERE / "results"
OUTPUT = RESULTS / "common_mode.json"

STATUS = "EXPLORATORY; zero new flows; cached Phase 8 mv_daily states; not registered"

PHASE9_INPUTS = PHASE9 / "results" / "phase9_inputs.json"

NETWORKS = pa.SWEEP_NETWORKS
K_GRID = pa.K_GRID
SIGMA_KEYS = td.SIGMA_KEYS
CONDITION = dict(td.CONDITION)
REPLICATES = 400
RETENTION_K = 2
LEVEL = 0  # CAP_LEVELS[0] = 1.0, no cap, as in Q1

TRUTH = "mv_daily"
TRUTH_CACHE = REPO / "outputs" / "robust_study" / "fullstate_cache"
NOMINAL_CACHE = REPO / "outputs" / "sense_study" / "fullstate_cache"
BUSBAR_TOLERANCE_PU = 1e-6  # J2: vm at the busbar bus against the trafo's vm_lv_pu

CONTROL_FALSE_ALARM = "followup_common_mode_false_alarm"

PRE_STATED_READINGS = [
    "Delta_mv is a model error, not a fault, so every alarm it raises is a false alarm. The "
    "question is only whether referencing removes them without removing the fault signal.",
    "Referencing can only cancel what the busbar sees. A meter-specific diurnal error is not "
    "common-mode and is not cancelled; it is still the error Phase 9 s. 8 measured.",
    "The referenced floor is wider than the raw one by sqrt(1 + (sigma_sub / sigma_tot)^2), so "
    "referencing costs power even when it cancels the error exactly.",
]

LIMITATIONS = [
    "A cable fault and an MV swing are never simulated together. Both legs here carry one "
    "truth at a time: Delta_mv with no fault (deliverables 1 and 2) or a W6 fault with no MV "
    "swing (deliverable 3). That the two superpose in the referenced contrast is a HYPOTHESIS; "
    "testing it would need new power flows, which this task does not run.",
    "Meter-specific, non-common diurnal errors are not cancelled by referencing. The busbar "
    "carries no information about an error that lives in one meter, so the Phase 9 s. 8 result "
    "(0.01 sigma_tot of diurnal systematic error doubles false alarms) stands unchanged for "
    "that error class.",
    "Delta_mv is one MV profile of one shape (+0.03 p.u. x PV share) on two networks. Its "
    "near-perfect common-mode structure is a property of a stiff LV feeder behind a fixed-tap "
    "transformer and is not established for a general MV disturbance.",
    "The referenced contrast is a statistic, not a decision rule. Nothing here re-runs the "
    "Phase 9 evaluation, so no registered coverage or false-alarm number changes.",
]

JUDGEMENT_CALLS = {
    "J1": "referencing is day-matched (the same day's busbar contrast is subtracted before "
          "averaging), which makes F_ref^2 = F_meter^2 + F_busbar^2 exact on one kept-day set",
    "J2": "the busbar signal is the vm column of the LV busbar bus, checked against the trafo "
          "vm_lv_pu field sensing.observe samples to 1e-6 p.u. on every loaded step",
    "J3": "the noise-free blocks use the usable retained days; the noise block uses "
          "pa.meter_days, so the referenced contrast inherits the meter's 1-day delay",
    "J4": "substation noise is two independent per-day leg means on the meter's valid-step "
          "counts, drawn after pa.draw_replicate, and one busbar series is shared by every "
          "meter of a replicate",
    "J5": "the referenced contrast is read against its own floor sqrt(sigma^2 + sigma_sub^2) "
          "x sqrt(sum v_d) / |S|; the raw-floor reading is a diagnostic beside it",
    "J6": "C2 is computed by a local helper asserted equal to cal.calibration_ratios in the "
          "tests; the Newey-West C3 arm and C0 are not computed",
    "J7": "the alarm fraction is the s. 8 family event on the 25 rules, per network and pooled",
    "J8": "the retention block reuses task 2's noise-free machinery unchanged and asserts its "
          "raw arm reproduces task 2's noise-free C1 at K = 2",
    "J9": "the Delta_mv reduction is cast to the frozen s. 7 artefact shape (float32 means), "
          "as every W6 artefact is; the 5e-10 p.u. quantisation is far below the residual",
    "J10": "a paired zero-truth control is run on the same draws, so a referenced rate can be "
           "split into the calibration's own size and Delta_mv's residual; it is a diagnostic",
}  # fmt: skip


def sigma_substation() -> float:
    """sigma_v_substation, read from the frozen Phase 6 measurement model, never retyped."""
    from gridpulse import noise_study as nst

    values = {float(nst.CONDITIONS[key].sigma_v_substation) for key in CONDITION.values()}
    if len(values) != 1:
        raise RuntimeError(f"the two conditions disagree on sigma_v_substation: {values}")
    sigma = values.pop()
    if not sigma > 0.0:
        raise RuntimeError("sigma_v_substation is not positive; the busbar arm is undefined")
    return sigma


SIGMA_SUB = sigma_substation()


def referenced_sigma(sigma: float) -> float:
    """The total per-reading sigma of the day-matched referenced contrast (J1)."""
    return math.sqrt(float(sigma) ** 2 + SIGMA_SUB**2)


# --- the Delta_mv reduction (no power flow: two cached vm legs) -------------------------------


def busbar_column(facts: dict) -> int:
    """The position of the LV busbar in the network's `lv_buses` order."""
    buses = [int(b) for b in facts["lv_buses"]]
    busbar = int(facts["lv_busbar"])
    if busbar not in buses:
        raise RuntimeError(f"the LV busbar {busbar} is not an LV bus of this network")
    return buses.index(busbar)


def mv_reduction(code: str, facts: dict) -> dict:
    """Delta_mv = vm(mv_daily) - vm(nominal) at level 0, reduced day by day with the frozen
    `ps.reduce_day`, in the s. 7 artefact array shape.

    The two legs are cached states; this function solves nothing. The daylight mask comes from
    `ps.daylight_masks` on the nominal network, which reads the SimBench profiles only.
    """
    from gridpulse import dual_study as ds
    from gridpulse import fullstate, stress

    days = [int(d) for d in facts["days"]["retention_primary"]["retained"]]
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    buses = [int(b) for b in fullstate.lv_buses(net)]
    if buses != [int(b) for b in facts["lv_buses"]]:
        raise RuntimeError(f"{code}: the cached bus order differs from Stage 1's lv_buses")
    masks = ps.daylight_masks(net, days)

    truth = stress.load(TRUTH_CACHE, code, TRUTH, days)
    nominal = fullstate.load_states(NOMINAL_CACHE, code, "nominal", days)
    column = busbar_column(facts)
    rows, worst_busbar = [], 0.0
    for day in days:
        vm_truth = np.asarray(truth[day]["vm"], dtype=float)[:, LEVEL, :]
        vm_nominal = np.asarray(nominal[day]["vm"], dtype=float)[:, LEVEL, :]
        for vm, state in ((vm_truth, truth[day]), (vm_nominal, nominal[day])):  # J2
            trafo = np.asarray(state["trafo"], dtype=float)[:, LEVEL, 3]
            finite = np.isfinite(vm[:, column]) & np.isfinite(trafo)
            if finite.any():
                worst_busbar = max(
                    worst_busbar, float(np.abs(vm[finite, column] - trafo[finite]).max())
                )
        rows.append(ps.reduce_day(vm_truth, vm_nominal, masks[day]))
    if worst_busbar > BUSBAR_TOLERANCE_PU:
        raise RuntimeError(f"{code}: the busbar vm column differs from the trafo vm_lv_pu by "
                           f"{worst_busbar:.3g} p.u., above {BUSBAR_TOLERANCE_PU}")  # fmt: skip

    arrays = ps.build_arrays(rows, days, buses)
    return {
        "code": code,
        "buses": buses,
        "busbar": int(facts["lv_busbar"]),
        "busbar_column": column,
        "arrays": arrays,
        "retained_days": days,
        "usable_rows": td.usable_rows(arrays, days),
        "diagnostics": {
            "retained_days": len(days),
            "days_usable": int(td.usable_rows(arrays, days).sum()),
            "failed_truth_steps": int(np.asarray(arrays["failed_truth"], dtype=int).sum()),
            "nan_nominal_entries": int(np.asarray(arrays["nan_nominal"], dtype=int).sum()),
            "all_daylight_steps_valid": bool(
                (np.asarray(arrays["n_daylight_valid"], dtype=int)
                 == np.asarray(arrays["n_daylight_steps"], dtype=int)).all()),  # fmt: skip
            "all_night_steps_valid": bool(
                (np.asarray(arrays["n_night_valid"], dtype=int)
                 == np.asarray(arrays["n_night_steps"], dtype=int)).all()),  # fmt: skip
            "busbar_vm_vs_trafo_max_abs_diff": worst_busbar,
            "power_flows_run": 0,
        },
    }


def contrast_matrix(arrays: dict) -> np.ndarray:
    """The per-day daylight-minus-night contrast, [days, buses]."""
    return (np.asarray(arrays["dmean_daylight"], dtype=float)
            - np.asarray(arrays["dmean_night"], dtype=float))  # fmt: skip


def day_variance_factor(arrays: dict) -> np.ndarray:
    """v_d = 1 / n_d + 1 / m_d, the per-day variance factor of one reading's contrast."""
    n_day = np.asarray(arrays["n_daylight_valid"], dtype=float)
    n_night = np.asarray(arrays["n_night_valid"], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return 1.0 / n_day + 1.0 / n_night


# --- the referenced contrast -------------------------------------------------------------------


def reference(values, column: int) -> np.ndarray:
    """The day-matched busbar-referenced contrast: subtract the busbar's own column (J1).

    `values` is [..., buses]; the busbar's column becomes exactly 0.
    """
    values = np.asarray(values, dtype=float)
    return values - values[..., int(column)][..., None]


def floors(sigma: float, v_days, survives) -> dict:
    """The raw and referenced C1 floors over one kept-day set, with the derivation (J5).

    F_meter = sigma x sqrt(sum_{d in S} v_d) / |S| is task 1's `cal.c1_floor`; F_busbar is the
    same expression at sigma_sub on the same days, so

        F_ref^2 = F_meter^2 + F_busbar^2 = (sigma^2 + sigma_sub^2) sum_{d in S} v_d / |S|^2,

    which is `cal.c1_floor(sqrt(sigma^2 + sigma_sub^2), ...)`. The two independent sensors make
    the cross term zero.
    """
    meter = cal.c1_floor(float(sigma), v_days, survives)
    busbar = cal.c1_floor(SIGMA_SUB, v_days, survives)
    combined = cal.c1_floor(referenced_sigma(sigma), v_days, survives)
    return {"meter": meter, "busbar": busbar, "referenced": combined,
            "quadrature_residual": float(np.nanmax(
                np.abs(combined**2 - (meter**2 + busbar**2))))}  # fmt: skip


def alarm_fraction(entry_k, buses, rules: dict, k: int, high) -> dict:
    """The s. 8 family event over the 25 rules at one K (J7). `high` is a scalar or per-bus."""
    names = sorted(rules)
    alarms = []
    for name in names:
        config = pa.configuration(rules[name], k)
        columns = [buses.index(int(b)) for b in config]
        peak = np.abs(np.asarray(entry_k, dtype=float)[columns])
        limit = np.broadcast_to(np.asarray(high, dtype=float), peak.shape)
        alarms.append(bool((peak >= limit).any()))
    return {"rules": len(names), "alarming": int(sum(alarms)),
            "fraction": float(sum(alarms)) / len(names),
            "alarming_rules": [n for n, a in zip(names, alarms, strict=True) if a]}  # fmt: skip


# --- deliverable 1: Delta_mv noise-free -------------------------------------------------------


def noise_free_network(reduction: dict, facts: dict) -> dict:
    """Raw against referenced k_mv on the usable retained days, at both sigma and every K."""
    arrays = reduction["arrays"]
    usable = np.asarray(reduction["usable_rows"], dtype=bool)
    x = contrast_matrix(arrays)[usable]
    v_days = day_variance_factor(arrays)
    buses = reduction["buses"]
    column = reduction["busbar_column"]
    rules = {name: [int(b) for b in bs]
             for name, bs in facts["placement_rules"]["buses"].items()}  # fmt: skip

    k_raw = x.mean(axis=0)
    k_ref = reference(k_raw, column)
    out = {
        "network": reduction["code"],
        "days_used": int(usable.sum()),
        "buses": len(buses),
        "busbar": reduction["busbar"],
        "k_mv_raw_pu": {"max_abs": float(np.abs(k_raw).max()),
                        "median_abs": float(np.median(np.abs(k_raw))),
                        "min_abs": float(np.abs(k_raw).min()),
                        "at_busbar": float(k_raw[column]),
                        "spread_across_buses": float(k_raw.max() - k_raw.min())},  # fmt: skip
        "k_mv_referenced_pu": {"max_abs": float(np.abs(k_ref).max()),
                               "median_abs": float(np.median(np.abs(k_ref))),
                               "at_busbar": float(k_ref[column])},  # fmt: skip
        "common_mode_share": float(1.0 - np.abs(k_ref).max() / np.abs(k_raw).max()),
        "per_sigma": {},
    }
    survives = np.broadcast_to(usable[:, None], (usable.size, len(buses)))
    for sigma_key in SIGMA_KEYS:
        sigma = float(sigma_key)
        band = floors(sigma, v_days, survives)
        f_meter = float(band["meter"][0])
        f_ref = float(band["referenced"][0])
        per_k = {}
        for k in K_GRID:
            z = q1.z_bonferroni(k)
            per_k[f"K_{k}"] = {
                "z": z,
                "threshold_raw_pu": z * f_meter,
                "threshold_referenced_pu": z * f_ref,
                "raw": alarm_fraction(k_raw, buses, rules, k, z * f_meter),
                "referenced": alarm_fraction(k_ref, buses, rules, k, z * f_ref),
                "referenced_against_the_raw_threshold": alarm_fraction(
                    k_ref, buses, rules, k, z * f_meter),  # J5 diagnostic
                "raw_peak_over_threshold": float(np.abs(k_raw).max() / (z * f_meter)),
                "referenced_peak_over_threshold": float(np.abs(k_ref).max() / (z * f_ref)),
            }
        out["per_sigma"][sigma_key] = {
            "sigma_tot": sigma,
            "sigma_substation": SIGMA_SUB,
            "F_meter_pu": f_meter,
            "F_busbar_pu": float(band["busbar"][0]),
            "F_referenced_pu": f_ref,
            "F_referenced_over_F_meter": f_ref / f_meter,
            "per_K": per_k,
        }
    return out


# --- deliverable 2: Delta_mv with meter and busbar noise --------------------------------------


def c1_c2_ratios(y, survives, sigma: float, v_days, k_grid=K_GRID) -> dict:
    """The C1 and C2 statistic / critical-value ratios of one arm (J6).

    `y` is the measured per-day contrast [days, meters] of that arm and `sigma` its own
    per-reading sigma (sigma_tot raw, sqrt(sigma_tot^2 + sigma_sub^2) referenced). A ratio of
    at least 1 is that calibration's alarm; NaN raises no alarm (`pa.family_alarm`'s rule).
    """
    survives = np.asarray(survives, dtype=bool)
    counts = survives.sum(axis=0)
    k_hat = pa.survival_mean(y, survives)
    k_abs = np.abs(k_hat)
    centred = cal.compact(np.asarray(y, dtype=float) - k_hat, survives)
    floor = cal.c1_floor(float(sigma), v_days, survives)
    with np.errstate(divide="ignore", invalid="ignore"):
        variance = (centred**2).sum(axis=0) / np.maximum(counts - 1, 1)
        variance = np.where(counts >= 2, variance, np.nan)
        standard_error = np.sqrt(variance / np.maximum(counts, 1))
        t_stat = np.where(standard_error > 0, k_abs / standard_error, np.nan)
        out = {}
        for k in k_grid:
            z = q1.z_bonferroni(int(k))
            out[k] = {"C1": k_abs / (z * floor),
                      "C2": t_stat / cal.t_critical_vector(counts - 1, int(k))}  # fmt: skip
    return out


def draw_busbar(rng, counts: dict) -> np.ndarray:
    """One replicate's substation contrast noise per day (J4): two independent leg means at
    sigma_sub / sqrt(n_d) and sigma_sub / sqrt(m_d), no missingness and no delay."""
    n_day = np.asarray(counts["n_daylight_valid"], dtype=float)
    n_night = np.asarray(counts["n_night_valid"], dtype=float)
    day = rng.standard_normal(n_day.size) * (SIGMA_SUB / np.sqrt(n_day))
    night = rng.standard_normal(n_night.size) * (SIGMA_SUB / np.sqrt(n_night))
    return day - night


ARMS = ("raw", "referenced")
NOISE_CALIBRATIONS = ("C1", "C2")
TRUTHS = ("Delta_mv", "zero")  # the second is the paired no-model-error control (J10)


def false_alarm_network(reduction: dict, facts: dict, *, replicates: int = REPLICATES) -> dict:
    """Family-wise false-alarm rates under Delta_mv plus noise, raw against referenced."""
    arrays = reduction["arrays"]
    buses = reduction["buses"]
    column = reduction["busbar_column"]
    rules = {name: [int(b) for b in bs]
             for name, bs in facts["placement_rules"]["buses"].items()}  # fmt: skip
    counts = pa.meter_days([arrays], reduction["retained_days"])
    rows = counts["rows"]
    truth = contrast_matrix(arrays)[rows]  # [days, buses], the Delta_mv model error
    v_days = day_variance_factor(arrays)[rows]
    matrices = {k: pa.config_matrix(rules, buses, k)[0] for k in K_GRID}
    names = sorted(rules)
    meters = len(buses)

    out = {
        "network": reduction["code"],
        "replicates": int(replicates),
        "rules": len(names),
        "day_axis": {name: counts[name] for name in
                     ("simulated_days", "retained_days", "delay_removed_day",
                      "dropped_not_usable", "all_daylight_steps_valid")},  # fmt: skip
        "truths": list(TRUTHS),
        "per_sigma": {},
    }
    for sigma_key in SIGMA_KEYS:
        sigma = float(sigma_key)
        condition = CONDITION[sigma_key]
        spec = pa.noise_spec(condition)
        if abs(spec["sigma_tot"] - sigma) > 1e-12:
            raise RuntimeError(f"{condition} carries sigma_tot {spec['sigma_tot']}, not {sigma}")
        sigmas = {"raw": sigma, "referenced": referenced_sigma(sigma)}
        truths = {"Delta_mv": truth, "zero": np.zeros_like(truth)}
        tally = {(label, arm, name, k): np.zeros(len(names), dtype=np.int64)
                 for label in TRUTHS for arm in ARMS for name in NOISE_CALIBRATIONS
                 for k in K_GRID}  # fmt: skip
        diagnostics = {"meter_days_without_a_reading": 0,
                       "meters_with_fewer_than_two_kept_days": 0}  # fmt: skip
        peak_t = {arm: 0.0 for arm in ARMS}
        rng = pa.control_rng(reduction["code"], condition, CONTROL_FALSE_ALARM, 0)
        for _ in range(int(replicates)):
            draws = pa.draw_replicate(rng, spec, counts["n_daylight_valid"],
                                      counts["n_night_valid"], meters, False)  # fmt: skip
            busbar_noise = draw_busbar(rng, counts)
            survives = draws["survives"]
            kept = survives.sum(axis=0)
            diagnostics["meter_days_without_a_reading"] += int((kept == 0).sum())
            diagnostics["meters_with_fewer_than_two_kept_days"] += int((kept < 2).sum())
            for label in TRUTHS:
                base = truths[label]
                measured = base + (draws["day"] - draws["night"])
                busbar = base[:, column] + busbar_noise
                series = {"raw": measured, "referenced": measured - busbar[:, None]}
                for arm in ARMS:
                    ratios = c1_c2_ratios(series[arm], survives, sigmas[arm], v_days)
                    if label == "Delta_mv" and np.isfinite(ratios[1]["C2"]).any():
                        peak_t[arm] = max(peak_t[arm],
                                          float(np.nanmax(np.abs(ratios[1]["C2"]))))
                    for k in K_GRID:
                        for name in NOISE_CALIBRATIONS:
                            peaks = td.rule_peaks(ratios[k][name], matrices[k])
                            tally[(label, arm, name, k)] += (peaks >= 1.0)
        per_k = {}
        for k in K_GRID:
            trials = len(names) * int(replicates)
            entry = {"z": q1.z_bonferroni(k), "trials": trials}
            for arm in ARMS:
                entry[arm] = {
                    name: pa.rate_record(int(tally[("Delta_mv", arm, name, k)].sum()), trials)
                    for name in NOISE_CALIBRATIONS
                }
                entry[f"{arm}_zero_truth_control"] = {
                    name: pa.rate_record(int(tally[("zero", arm, name, k)].sum()), trials)
                    for name in NOISE_CALIBRATIONS
                }
            per_k[f"K_{k}"] = entry
        out["per_sigma"][sigma_key] = {
            "sigma_tot": sigma,
            "condition": condition,
            "sigma_per_reading": sigmas,
            "floor_derivation": floor_derivation(sigma, v_days, counts),
            "per_K": per_k,
            "largest_C2_ratio_seen": peak_t,
            "diagnostics": diagnostics,
        }
    return out


def floor_derivation(sigma: float, v_days, counts: dict) -> dict:
    """F_ref^2 = F_meter^2 + F_busbar^2 over the shared kept days, recorded as a reading."""
    days = int(counts["simulated_days"])
    full = np.ones((days, 1), dtype=bool)  # no missingness: the whole shared axis
    band = floors(sigma, v_days, full)
    meter, busbar, combined = (float(band[name][0]) for name in ("meter", "busbar", "referenced"))
    return {
        "reading": "F_ref^2 = F_meter^2 + F_busbar^2. The meter and the substation sensor are "
                   "independent, so the day-matched referenced contrast of one kept-day set S "
                   "has variance (sigma_tot^2 + sigma_sub^2) x sum_{d in S} v_d / |S|^2, with "
                   "v_d = 1/n_d + 1/m_d. The referenced floor is therefore the raw floor at "
                   "sigma = sqrt(sigma_tot^2 + sigma_sub^2), i.e. wider by "
                   "sqrt(1 + (sigma_sub/sigma_tot)^2) and never narrower.",  # fmt: skip
        "evaluated_on": "the shared kept-day axis with no day missing",
        "shared_kept_days": days,
        "sum_v_days": float(np.asarray(v_days, dtype=float).sum()),
        "F_meter_pu": meter,
        "F_busbar_pu": busbar,
        "F_referenced_pu": combined,
        "F_meter_squared_plus_F_busbar_squared": meter**2 + busbar**2,
        "F_referenced_squared": combined**2,
        "max_abs_quadrature_residual": band["quadrature_residual"],
        "inflation_factor": combined / meter,
        "inflation_factor_closed_form": math.sqrt(1.0 + (SIGMA_SUB / float(sigma)) ** 2),
    }


# --- deliverable 3: signal retention on the 89 W6 artefacts -----------------------------------


def referenced_pairs(net: dict, k: int, high_by_line: dict, column: int):
    """`td.detection_pairs` on the busbar-referenced contrast (J8)."""
    out = []
    for line in net["lines"]:
        entry = net["entries"][line]
        below = set(entry["downstream"])
        high = float(high_by_line[line])
        k_ref = reference(entry["k"], column)
        for name in net["rule_names"]:
            config = pa.configuration(net["rules"][name], k)
            value = pa.c_meter(k_ref, entry["buses"], config)
            out.append((abs(value) >= high, bool(set(config) & below)))
    return out


def retention_network(code: str, net: dict, loaded: dict, facts: dict,
                      k: int = RETENTION_K) -> dict:  # fmt: skip
    """Noise-free W6 coverage at K: raw C1 against the referenced contrast, both sigma."""
    column = busbar_column(facts)
    z = q1.z_bonferroni(k)
    busbar_k = {int(line): float(abs(net["entries"][line]["k"][column]))
                for line in net["lines"]}  # fmt: skip
    peak_k = {int(line): float(np.abs(net["entries"][line]["k"]).max())
              for line in net["lines"]}  # fmt: skip
    out = {
        "network": code,
        "K": int(k),
        "z": z,
        "cables": len(net["lines"]),
        "rules": len(net["rule_names"]),
        "busbar": int(facts["lv_busbar"]),
        "busbar_abs_k_pu": {"max": max(busbar_k.values()),
                            "median": float(np.median(list(busbar_k.values()))),
                            "per_cable": {str(line): v
                                          for line, v in sorted(busbar_k.items())}},
        "network_peak_abs_k_pu": {"max": max(peak_k.values()),
                                  "median": float(np.median(list(peak_k.values())))},
        "busbar_over_network_peak_max": max(busbar_k[c] / peak_k[c] for c in busbar_k),
        "per_sigma": {},
    }
    for sigma_key in SIGMA_KEYS:
        sigma = float(sigma_key)
        raw_floors = td.c1_floors(net, loaded, sigma)
        ref_floors = td.c1_floors(net, loaded, referenced_sigma(sigma))
        raw = td.pair_table(td.detection_pairs(
            net, k, {c: z * f for c, f in raw_floors.items()}))
        ref = td.pair_table(referenced_pairs(
            net, k, {c: z * f for c, f in ref_floors.items()}, column))
        out["per_sigma"][sigma_key] = {
            "sigma_tot": sigma,
            "threshold_raw_pu_range": [z * min(raw_floors.values()), z * max(raw_floors.values())],
            "threshold_referenced_pu_range": [z * min(ref_floors.values()),
                                              z * max(ref_floors.values())],  # fmt: skip
            "raw_C1": raw,
            "referenced_C1": ref,
            "detected_delta": int(ref["detected"]) - int(raw["detected"]),
            "retention": (float(ref["detected"]) / float(raw["detected"])
                          if raw["detected"] else None),  # fmt: skip
        }
    return out


# --- the run -----------------------------------------------------------------------------------


def _plain(value):
    """numpy scalars and arrays to plain JSON types."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_plain(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def blocks(*, replicates: int = REPLICATES, networks=NETWORKS, with_noise: bool = True) -> dict:
    """Every computed block, without writing anything."""
    inputs = json.loads(PHASE9_INPUTS.read_text())
    loaded, artefacts = td.load_w6(inputs)
    out = {"artefacts": artefacts, "reductions": {}, "noise_free": {}, "retention": {},
           "false_alarm": {}}  # fmt: skip
    for code in networks:
        facts = inputs["networks"][code]
        reduction = mv_reduction(code, facts)
        net = td.network_block(code, inputs, loaded)
        out["reductions"][code] = reduction["diagnostics"]
        out["noise_free"][code] = noise_free_network(reduction, facts)
        out["retention"][code] = retention_network(code, net, loaded, facts)
        if with_noise:
            out["false_alarm"][code] = false_alarm_network(
                reduction, facts, replicates=replicates)
    out["retention_reproduces_task2"] = retention_reproduction(out["retention"])
    return out


def retention_reproduction(retention: dict) -> dict:
    """J8: the raw arm must be task 2's noise-free C1 pair table at K = 2."""
    reference_file = RESULTS / "tradeoff.json"
    if not reference_file.exists():
        return {"checked": False, "reason": f"{reference_file.name} is absent"}
    payload = json.loads(reference_file.read_text())
    rows, ok = {}, True
    for code, block in retention.items():
        rows[code] = {}
        for sigma_key, entry in block["per_sigma"].items():
            theirs = (payload["noise_free_reference"][code]["per_sigma"][sigma_key]
                      ["per_K"][f"K_{RETENTION_K}"]["C1"])  # fmt: skip
            match = (int(theirs["detected"]) == int(entry["raw_C1"]["detected"])
                     and int(theirs["pairs"]) == int(entry["raw_C1"]["pairs"]))  # fmt: skip
            rows[code][sigma_key] = {"task2": {"detected": int(theirs["detected"]),
                                               "pairs": int(theirs["pairs"])},
                                     "here": {"detected": int(entry["raw_C1"]["detected"]),
                                              "pairs": int(entry["raw_C1"]["pairs"])},
                                     "reproduces": bool(match)}  # fmt: skip
            ok = ok and match
    return {"checked": True, "K": RETENTION_K, "per_network": rows, "reproduces": bool(ok)}


def run(output: Path = OUTPUT, *, replicates: int = REPLICATES, networks=NETWORKS) -> dict:
    """Everything, into one write-once JSON."""
    output = Path(output)
    if output.exists():  # refuse before any cached state is read, not after the Monte Carlo
        raise RuntimeError(f"refusing to overwrite {output}")
    payload: dict = {
        "task": "Phase 9 follow-up 3: busbar-referenced contrast against common-mode diurnal "
                "error",
        "status": STATUS,
        "pre_stated_readings": list(PRE_STATED_READINGS),  # written before anything is computed
        "limitations": list(LIMITATIONS),
        "judgement_calls": JUDGEMENT_CALLS,
        "grids": {
            "networks": list(networks),
            "truth": TRUTH,
            "sigma_tot": [float(s) for s in SIGMA_KEYS],
            "conditions": dict(CONDITION),
            "sigma_substation": SIGMA_SUB,
            "K_grid": list(K_GRID),
            "calibrations": list(NOISE_CALIBRATIONS),
            "replicates": int(replicates),
            "retention_K": RETENTION_K,
            "cap_level_index": LEVEL,
        },
        "interval_label": "descriptive Wilson 95 % (Phase 9 reading R-l). One replicate is one "
                          "measurement realisation shared by every rule, so the pooled trials "
                          "are not independent and the interval is narrower than a true "
                          "sampling interval.",
        "provenance": {
            "phase9_registration": pa.REGISTRATION,
            "phase9_registration_sha256": pa.REGISTRATION_SHA256,
            "phase9_inputs": str(PHASE9_INPUTS.relative_to(REPO)),
            "task1_calibration": "analysis/phase9_followup/results/calibration.json",
            "task2_tradeoff": "analysis/phase9_followup/results/tradeoff.json",
            "truth_leg": f"stress.load({TRUTH_CACHE.relative_to(REPO)}, {TRUTH}), level 0",
            "nominal_leg": f"fullstate.load_states({NOMINAL_CACHE.relative_to(REPO)}, nominal), "
                           "level 0",  # fmt: skip
            "sigma_substation_source": "gridpulse.noise_study.CONDITIONS[...]"
                                       ".sigma_v_substation (noise_study.py:31), frozen Phase 6",
            "reused_phase9_functions": [
                "ps.reduce_day", "ps.daylight_masks", "ps.build_arrays", "pa.meter_days",
                "pa.draw_replicate", "pa.survival_mean", "pa.config_matrix",
                "pa.configuration", "pa.c_meter", "pa.control_rng", "pa.noise_spec",
                "pa.rate_record", "q1.z_bonferroni", "q1.write_new_json",
            ],
            "reused_followup_functions": [
                "cal.c1_floor", "cal.compact", "cal.t_critical_vector", "td.load_w6",
                "td.network_block", "td.usable_rows", "td.c1_floors", "td.detection_pairs",
                "td.pair_table", "td.rule_peaks",
            ],
            "power_flows_run": 0,
            "held_out_networks_touched": 0,
            "phase9_files_written": 0,
            "frozen_evaluations_rerun": 0,
        },
    }
    computed = blocks(replicates=replicates, networks=networks)
    payload["provenance"]["artefacts"] = computed["artefacts"]
    payload["delta_mv_reduction"] = computed["reductions"]
    payload["noise_free"] = computed["noise_free"]
    payload["with_noise"] = computed["false_alarm"]
    payload["signal_retention"] = computed["retention"]
    payload["signal_retention_reproduces_task2"] = computed["retention_reproduces_task2"]
    payload["verdict"] = verdict(payload)
    sha = q1.write_new_json(output, _plain(payload))
    payload["written"] = {"path": _reported(output), "sha256": sha}
    return payload


def _reported(path: Path) -> str:
    """A repository-relative path when the file is inside the repository, else the full one."""
    path = Path(path)
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path)


def verdict(payload: dict) -> dict:
    """The one-line answer, read off the computed blocks."""
    raw, ref = [], []
    for block in payload["noise_free"].values():
        for entry in block["per_sigma"].values():
            for per_k in entry["per_K"].values():
                raw.append(per_k["raw"]["fraction"])
                ref.append(per_k["referenced"]["fraction"])
    rates = {arm: [] for arm in ARMS}
    for block in payload["with_noise"].values():
        for entry in block["per_sigma"].values():
            for per_k in entry["per_K"].values():
                for arm in ARMS:
                    rates[arm].append(per_k[arm]["C1"]["rate"])
    retained = []
    for block in payload["signal_retention"].values():
        for entry in block["per_sigma"].values():
            retained.append(entry["retention"])
    return {
        "noise_free_alarm_fraction_raw": [min(raw), max(raw)],
        "noise_free_alarm_fraction_referenced": [min(ref), max(ref)],
        "C1_false_alarm_rate_raw": [min(rates["raw"]), max(rates["raw"])],
        "C1_false_alarm_rate_referenced": [min(rates["referenced"]), max(rates["referenced"])],
        "W6_coverage_retention": [min(retained), max(retained)],
        "reading": "EXPLORATORY. The entries above are the range over the two networks, both "
                   "sigma_tot and every K. They answer the question only for the one cached "
                   "common-mode error Delta_mv; see `limitations`.",
    }


# --- the compact summary -----------------------------------------------------------------------


def _short(code: str) -> str:
    return code.replace("1-LV-", "").replace("--2-sw", "")


def print_noise_free(payload: dict) -> None:
    print("\n1. Delta_mv noise-free: raw against busbar-referenced (false alarms, no fault)")
    for code, block in payload["noise_free"].items():
        print(f"  {_short(code)}: {block['days_used']} usable days, {block['buses']} buses, "
              f"busbar {block['busbar']}")  # fmt: skip
        raw, ref = block["k_mv_raw_pu"], block["k_mv_referenced_pu"]
        print(f"    |k_mv| raw        max {raw['max_abs']:.3e}  median {raw['median_abs']:.3e}"
              f"  at busbar {raw['at_busbar']:+.3e}")  # fmt: skip
        print(f"    |k_mv| referenced max {ref['max_abs']:.3e}  median {ref['median_abs']:.3e}"
              f"  ({100 * block['common_mode_share']:.3f} % of the raw peak cancels)")
        for sigma_key, entry in block["per_sigma"].items():
            print(f"    sigma {sigma_key}: F_meter {entry['F_meter_pu']:.3e}  F_busbar "
                  f"{entry['F_busbar_pu']:.3e}  F_ref {entry['F_referenced_pu']:.3e}  "
                  f"(x{entry['F_referenced_over_F_meter']:.4f})")  # fmt: skip
            for k_key, per_k in entry["per_K"].items():
                print(f"      {k_key}: alarming rules raw {per_k['raw']['alarming']}/"
                      f"{per_k['raw']['rules']}  referenced "
                      f"{per_k['referenced']['alarming']}/{per_k['referenced']['rules']}"
                      f"  (peak/threshold raw {per_k['raw_peak_over_threshold']:.1f}, "
                      f"ref {per_k['referenced_peak_over_threshold']:.4f})")  # fmt: skip


def print_with_noise(payload: dict) -> None:
    print("\n2. Delta_mv plus meter and busbar noise: family-wise false-alarm rate")
    for code, block in payload.get("with_noise", {}).items():
        print(f"  {_short(code)}: {block['day_axis']['simulated_days']} kept days, "
              f"{block['rules']} rules, {block['replicates']} replicates")  # fmt: skip
        for sigma_key, entry in block["per_sigma"].items():
            derivation = entry["floor_derivation"]
            print(f"    sigma {sigma_key} ({entry['condition']}): F_meter "
                  f"{derivation['F_meter_pu']:.3e}  F_busbar {derivation['F_busbar_pu']:.3e}  "
                  f"F_ref {derivation['F_referenced_pu']:.3e}  "
                  f"residual {derivation['max_abs_quadrature_residual']:.1e}")  # fmt: skip
            for k_key, per_k in entry["per_K"].items():
                parts = "  ".join(
                    f"{arm[:3]}-{name} {per_k[arm][name]['rate']:.3f}"
                    f" [0-truth {per_k[f'{arm}_zero_truth_control'][name]['rate']:.3f}]"
                    for arm in ARMS for name in NOISE_CALIBRATIONS
                )
                print(f"      {k_key}: {parts}")


def print_retention(payload: dict) -> None:
    print("\n3. Signal retention on the 89 W6 artefacts (noise-free, K = 2)")
    for code, block in payload["signal_retention"].items():
        busbar = block["busbar_abs_k_pu"]
        print(f"  {_short(code)}: {block['cables']} cables x {block['rules']} rules; busbar "
              f"|k| max {busbar['max']:.2e} median {busbar['median']:.2e} "
              f"(network peak |k| median {block['network_peak_abs_k_pu']['median']:.2e})")
        for sigma_key, entry in block["per_sigma"].items():
            raw, ref = entry["raw_C1"], entry["referenced_C1"]
            print(f"    sigma {sigma_key}: raw {raw['detected']}/{raw['pairs']} "
                  f"({raw['coverage']['rate']:.3f})  referenced {ref['detected']}/"
                  f"{ref['pairs']} ({ref['coverage']['rate']:.3f})  "
                  f"delta {entry['detected_delta']:+d}")  # fmt: skip
    check = payload.get("signal_retention_reproduces_task2", {})
    print(f"  raw arm reproduces task 2's noise-free C1: {check.get('reproduces')} "
          f"(checked={check.get('checked')})")  # fmt: skip


def print_summary(payload: dict) -> None:
    print(f"status: {payload['status']}")
    print_noise_free(payload)
    print_with_noise(payload)
    print_retention(payload)
    if "verdict" in payload:
        print("\nverdict")
        for name, value in payload["verdict"].items():
            if name != "reading":
                print(f"  {name}: {value}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("check", "run", "summary"))
    parser.add_argument("--replicates", type=int, default=REPLICATES)
    args = parser.parse_args(argv)
    if args.command == "check":
        computed = blocks(replicates=args.replicates, with_noise=False)
        print_summary({"status": STATUS, "noise_free": computed["noise_free"],
                       "signal_retention": computed["retention"],
                       "signal_retention_reproduces_task2":
                           computed["retention_reproduces_task2"]})  # fmt: skip
        return 0
    if args.command == "run":
        payload = run(replicates=args.replicates)
        print_summary(payload)
        print(f"\nwritten: {payload['written']['path']}  sha256 "
              f"{payload['written']['sha256']}")  # fmt: skip
        return 0
    if not OUTPUT.exists():
        raise SystemExit(f"{OUTPUT} is missing; run `run` first")
    print_summary(json.loads(OUTPUT.read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
