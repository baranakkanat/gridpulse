"""Calibrated-detection pilot, step 1: the C2-ref size grid on the development half.

EXPLORATORY and unregistered, step 1 of the four-step pilot of
`docs/proposal_calibrated_detection.md` s. 10. **Zero power flows**: no `vm` array and no
artefact voltage is read. The day axis, the per-day daylight/night step counts and the
per-day masks come from the SimBench profiles through
`analysis/phase9_followup/calibration.py`. Nothing outside
`analysis/calibrated_detection_pilot/` is written, and no Phase 9 or follow-up file is
modified: `phase9_analysis`, `q1_voltage_residual`, `calibration` and `common_mode` are
*imported* and reused unchanged.

The question is H1a's size clause for **C2-ref**, the busbar-referenced, day-level
studentised contrast of the proposal s. 3, measured with **independent trials**: one fresh
noise realisation per (rule, replicate), never shared across rules. The unreferenced **C2**
of `calibration.py` runs in the same cells as the comparator, so the *referencing size
penalty* is a difference measured on matched cells rather than across two runs.

Run from the repository root (one part per network and sigma, then the merge):

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/calibrated_detection_pilot/size_grid.py \
        part --network 1-LV-semiurb4--2-sw --sigma 0.01
    ...
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/calibrated_detection_pilot/size_grid.py merge
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/calibrated_detection_pilot/size_grid.py summary

`part` and `merge` write their files once and refuse to overwrite them. `probe` runs a part
at a reduced replicate count and writes nothing, for timing only.

Judgement calls (numbered, and repeated in the output JSON)
-----------------------------------------------------------
J1  The 36 primary cells do **not** include the network. Both sweep networks carry the whole
    grid and the H1a and K2 verdicts are reported per network; the overall verdict requires
    the criterion to hold in **both**, which is `calibration.py`'s J10 convention. The
    pooled-over-networks rate is reported as well, descriptively.
J2  sigma_b is the per-reading meter noise sd. N1 at sigma = 0.01 is the frozen `realistic`
    condition and at sigma = 0.005 the frozen `sigma_0.005` condition (both carry
    sigma_bias_remote = 0, a 0.05 whole-day missing probability and a 1-day delay), so no
    noise parameter is retyped. N2 is `calibration.draw_ar1_within_day` on
    `calibration.ar1_day_night_spec` at the same marginal sigma, missingness and delay.
J3  The busbar draw is `common_mode.draw_busbar` scaled by sigma_bb / common_mode.SIGMA_SUB.
    `draw_busbar` is exactly linear in that constant, so this is the same sensor model at a
    different accuracy and not a reimplementation; a test pins the equality at
    sigma_bb = SIGMA_SUB. The busbar has no missingness and no delay, and its noise is i.i.d.
    across steps under both N1 and N2, as the task fixes.
J4  One replicate's K meters are drawn as K columns of a single `draw_replicate` /
    `draw_ar1_within_day` call whose `meters` argument is `block * K`: those draws are i.i.d.
    per (day, column) by construction, so a [days, block, K] reshape is `block` independent
    replicates of K independent meters. This is a vectorisation of the frozen samplers, not a
    change to them.
J5  Under truth = nominal with zero flows the bus identity of a configuration carries no
    information: the noise is i.i.d. per meter. A rule therefore contributes its K meters
    only, and the 25 rules differ by their independent noise streams. The frozen Phase 6
    placement rules are still read and their configurations still formed, so a rule with
    fewer than K buses would fail loudly.
J6  A meter with fewer than two kept days has no C2 or C2-ref statistic and raises no alarm
    (Phase 9 reading R-j, `calibration.py` J7).
J7  Clopper-Pearson intervals are two-sided 95 % (Beta quantiles, the s = 0 and s = n atoms
    at 0 and 1), checked against `scipy.stats.binomtest(...).proportion_ci(method="exact")`.
    The Wilson record of `phase9_analysis.rate_record` is carried beside the pooled CP
    interval for comparability with the follow-up, and is never used in a verdict.
J8  H1a's acceptance and its falsification are not complements: a cell may violate exactly
    one of clauses (ii) and (iii) and then neither accept nor falsify. The verdict is
    therefore three-valued, ACCEPTED / INDETERMINATE / FALSIFIED, and K2 is TRIPPED only on
    FALSIFIED, with `not_accepted` reported beside it.
J9  The referencing size penalty is reported as C2-ref minus C2 on the same cell's
    pooled-over-rules point estimates, per the pre-stated reading.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PHASE9 = REPO / "analysis" / "phase9"
FOLLOWUP = REPO / "analysis" / "phase9_followup"
for _path in (PHASE9, FOLLOWUP):  # imported, never copied or edited
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import calibration as cal  # noqa: E402  (phase9_followup task 1, AKK-39)
import common_mode as cm  # noqa: E402  (phase9_followup task 3)
import numpy as np  # noqa: E402
import phase9_analysis as pa  # noqa: E402
import q1_voltage_residual as q1  # noqa: E402
from scipy import stats  # noqa: E402

RESULTS = HERE / "results"
OUTPUT = RESULTS / "size_grid.json"
PARTS = RESULTS / "parts"

STATUS = ("EXPLORATORY pilot step 1; zero power flows; development-half SimBench day axis; "
          "unregistered")  # fmt: skip

NETWORKS = pa.SWEEP_NETWORKS
K_GRID = pa.K_GRID  # (1, 2, 4)
SIGMAS = ("0.01", "0.005")
N1_CONDITION = {"0.01": "realistic", "0.005": "sigma_0.005"}
NOISE_MODELS = ("N1", "N2_rho_0.5", "N2_rho_0.9")
N2_RHO = {"N2_rho_0.5": 0.5, "N2_rho_0.9": 0.9}
BB_RATIOS = ("0.2", "1")
ARMS = ("C2_ref", "C2")

REPLICATES = 2000
BLOCK = 500  # replicates per seeded block; REPLICATES must be a multiple of it
SEED_ROOT = 20261024  # the pilot's seed root, 2026-10-24
ALPHA = q1.ALPHA  # 0.05 family-wise, two-sided Bonferroni over the K meters
CP_CONFIDENCE = 0.95

# --- H1a and K2, pre-stated -----------------------------------------------------------------

H1A_RULE = {
    "source": "docs/proposal_calibrated_detection.md s. 2 H1a",
    "clause_1": "the rate pooled over rules and over cells has a 95 % Clopper-Pearson lower "
                "bound <= 0.05, and the per-cell pooled CP lower bound is <= 0.05 in at least "
                "33 of the 36 primary cells",
    "clause_2": "per cell, at most 2 of 25 rules have a per-rule CP lower bound > 0.05",
    "clause_3": "per cell, no per-rule point estimate exceeds 0.08",
    "accepted": "clause 1 and clause 2 and clause 3 all hold",
    "falsified": "clause 1's pooled bound fails, or more than 3 cells fail the per-cell "
                 "lower-bound clause, or any cell violates clauses 2 and 3 together",
    "indeterminate": "neither, which J8 records can happen when one cell violates exactly one "
                     "of clauses 2 and 3",
    "cells": 36,
    "cell_tolerance": 33,
    "pooled_lower_bound_limit": 0.05,
    "rules_over_limit": 2,
    "rule_rate_limit": 0.08,
}  # fmt: skip

K2_RULE = {
    "source": "docs/proposal_calibrated_detection.md s. 9 K2",
    "statement": "C2-ref fails H1a on the development half under N1",
    "scope": "the same three-part rule restricted to the 12 N1 cells",
    "cells": 12,
    "cell_tolerance": 11,
    "cell_tolerance_note": "an exactly calibrated detector fails 2 or more of 12 with "
                           "probability 0.035",
    "tripped_when": "the restricted criterion is FALSIFIED (J8)",
}  # fmt: skip

PRE_STATED_READINGS = [
    "K2 not tripped means the primary hypothesis survives to the ENWL stage.",
    "The referencing size penalty is the difference between C2-ref and C2 rates in the same "
    "cell.",
]

JUDGEMENT_CALLS = {
    "J1": "the 36 cells exclude the network; verdicts are per network and the overall verdict "
          "requires both, as calibration.py's J10 does",
    "J2": "N1 is the frozen `realistic` / `sigma_0.005` condition at that sigma; N2 is "
          "calibration.py's exact within-day AR(1) at the same marginal sigma",
    "J3": "the busbar draw is common_mode.draw_busbar scaled by sigma_bb / SIGMA_SUB, which is "
          "exact because draw_busbar is linear in that constant",
    "J4": "a block of replicates is drawn as `block * K` columns of one frozen sampler call "
          "and reshaped; the columns are i.i.d. by construction",
    "J5": "with zero flows and truth = nominal the configuration's bus identity is "
          "uninformative, so a rule contributes K meters with its own independent stream",
    "J6": "a meter with fewer than two kept days has no statistic and raises no alarm",
    "J7": "Clopper-Pearson 95 % two-sided; the Wilson record is carried descriptively only",
    "J8": "the H1a verdict is three-valued; K2 trips only on FALSIFIED",
    "J9": "the referencing size penalty is C2-ref minus C2 on matched cells' pooled point "
          "estimates",
}  # fmt: skip

LIMITATIONS = [
    "This is a size measurement only. The development half carries no fault signal, so no "
    "power, coverage or H1b quantity is produced here.",
    "The t reference is asymptotic, not exact: the per-day referenced contrasts are "
    "independent and mean-zero but heteroskedastic through the unequal n_d and m_d, so the "
    "measured rate is empirical evidence at |S| = 144, not a proof (proposal s. 3.2).",
    "No MV swing, no meter-specific diurnal error and no across-day dependence is simulated. "
    "H1a makes no claim in those cells and neither does this step.",
    "Two SimBench networks with German-convention LV topologies; the ENWL transfer test is "
    "steps 2-4 and the main study, not this.",
]


# --- the cell grid -----------------------------------------------------------------------


def cell_id(sigma: str, k: int, noise: str, bb_ratio: str) -> str:
    return f"sigma{sigma}_K{int(k)}_{noise}_bb{bb_ratio}"


def cells(sigma: str | None = None) -> list[dict]:
    """The 36 primary cells of proposal s. 6, in a fixed order."""
    out = []
    for s in SIGMAS:
        if sigma is not None and s != sigma:
            continue
        for k in K_GRID:
            for noise in NOISE_MODELS:
                for ratio in BB_RATIOS:
                    out.append({
                        "cell_id": cell_id(s, k, noise, ratio),
                        "sigma": float(s),
                        "sigma_key": s,
                        "K": int(k),
                        "noise": noise,
                        "rho": N2_RHO.get(noise),
                        "sigma_bb_over_sigma_b": float(ratio),
                        "sigma_bb": float(ratio) * float(s),
                        "condition": N1_CONDITION[s] if noise == "N1" else None,
                        "mv_swing": False,
                        "diurnal_amplitude": 0.0,
                    })  # fmt: skip
    return out


CELL_IDS = [cell["cell_id"] for cell in cells()]
N1_CELL_IDS = [cell["cell_id"] for cell in cells() if cell["noise"] == "N1"]


def design(replicates: int = REPLICATES) -> dict:
    """The design block, written into every artefact before any rate is computed."""
    return {
        "networks": list(NETWORKS),
        "axis": "development half of calibration.development_axis: "
                "grid_study.period_days('development'), the s. 7 retention rule and the 1-day "
                "delay; profiles only, no vm array and no power flow",
        "placements": "the 25 frozen Phase 6 rules of phase9_analysis.placements",
        "primary_cells": len(CELL_IDS),
        "cell_axes": {
            "sigma": list(SIGMAS),
            "K": list(K_GRID),
            "noise": list(NOISE_MODELS),
            "sigma_bb_over_sigma_b": list(BB_RATIOS),
        },
        "cells": cells(),
        "detector_C2_ref": {
            "contrast": "c_d^ref(b) = c_d(b) - c_d(busbar) on the meter's kept days",
            "statistic": "T = mean / (sd / sqrt(|S|)), sd with ddof = 1",
            "critical_value": "two-sided t_{|S|-1} at 1 - 0.025/K",
            "family": "a configuration alarms if any of its K meters alarms",
        },
        "comparator_C2": "the unreferenced day-level studentised contrast of calibration.py, "
                         "in the same cells, to measure the referencing size penalty",
        "noise": {
            "N1": "the frozen realistic-type condition at that sigma: i.i.d. per reading, "
                  "5 % whole-day missingness, 1-day delay",
            "N2": "calibration.ar1_day_night_spec / draw_ar1_within_day: exact within-day "
                  "AR(1) day and night means, same missingness and delay",
            "busbar": "sigma_bb per reading at every step, no missingness, no delay, i.i.d. "
                      "under both N1 and N2 (common_mode.draw_busbar, scaled; J3)",
            "mv_swing": "off in every primary cell",
            "diurnal_bias": "A = 0 in every primary cell",
        },
        "replicates_per_rule": int(replicates),
        "block": int(BLOCK),
        "independence": "one fresh noise realisation per (rule, replicate); never shared "
                        "across rules",
        "seed": "default_rng(SeedSequence([20261024, stable_int(network), stable_int(cell_id), "
                "stable_int(rule), replicate_block]))",
        "seed_root": SEED_ROOT,
        "intervals": "Clopper-Pearson 95 %, per rule and pooled",
        "alpha": ALPHA,
        "power_flows_run": 0,
        "vm_arrays_loaded": 0,
    }


# --- seeds ---------------------------------------------------------------------------------


def block_rng(network: str, cell: str, rule: str, block: int):
    """The pilot's seed scheme, in the Phase 9 `SeedSequence` idiom with a new root."""
    from gridpulse import sensing as sn

    return np.random.default_rng(np.random.SeedSequence([
        SEED_ROOT, sn._stable_int(str(network)), sn._stable_int(str(cell)),
        sn._stable_int(str(rule)), int(block),
    ]))  # fmt: skip


# --- draws ---------------------------------------------------------------------------------


def busbar_contrast(rng, axis: dict, replicates: int, sigma_bb: float) -> np.ndarray:
    """[days, replicates] substation contrast noise at `sigma_bb` (J3).

    `common_mode.draw_busbar` draws two independent leg means at SIGMA_SUB / sqrt(n_d) and
    SIGMA_SUB / sqrt(m_d) with no missingness and no delay; it is exactly linear in
    SIGMA_SUB, so the scale factor below is the same sensor at a different accuracy.
    """
    replicates = int(replicates)
    days = int(np.asarray(axis["n_daylight"]).size)
    counts = {
        "n_daylight_valid": np.tile(np.asarray(axis["n_daylight"], dtype=float), replicates),
        "n_night_valid": np.tile(np.asarray(axis["n_night"], dtype=float), replicates),
    }
    flat = cm.draw_busbar(rng, counts) * (float(sigma_bb) / cm.SIGMA_SUB)
    return flat.reshape(replicates, days).T


def meter_draws(rng, cell: dict, axis: dict, replicates: int, cache: dict) -> dict:
    """One block's meter noise: contrast [days, replicates, K] and survives, same shape (J4)."""
    k = int(cell["K"])
    columns = int(replicates) * k
    if cell["noise"] == "N1":
        spec = cache[("N1", cell["sigma_key"])]
        draws = pa.draw_replicate(rng, spec, axis["n_daylight"], axis["n_night"], columns,
                                  False)  # fmt: skip
    else:
        moments = cache[("N2", cell["sigma_key"], cell["noise"])]
        draws = cal.draw_ar1_within_day(rng, moments, columns)
    days = int(draws["days"])
    contrast = (draws["day"] - draws["night"]).reshape(days, int(replicates), k)
    survives = np.asarray(draws["survives"], dtype=bool).reshape(days, int(replicates), k)
    return {"contrast": contrast, "survives": survives}


def noise_cache(axis: dict) -> dict:
    """The frozen N1 specs and the per-cell N2 AR(1) day/night moments, built once per axis."""
    cache: dict = {}
    for sigma_key in SIGMAS:
        cache[("N1", sigma_key)] = pa.noise_spec(N1_CONDITION[sigma_key])
        for noise, rho in N2_RHO.items():
            cache[("N2", sigma_key, noise)] = cal.ar1_day_night_spec(
                axis, float(sigma_key), float(rho))
    return cache


# --- the statistic ---------------------------------------------------------------------------


def studentised(contrast, survives) -> tuple[np.ndarray, np.ndarray]:
    """T = mean / (sd / sqrt(|S|)) per meter over its kept days, and |S|.

    `contrast` and `survives` share a shape whose **first** axis is the day axis. A meter with
    fewer than two kept days gets NaN and therefore never alarms (J6).
    """
    survives = np.asarray(survives, dtype=bool)
    contrast = np.asarray(contrast, dtype=float)
    counts = survives.sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        total = np.where(survives, contrast, 0.0).sum(axis=0)
        mean = np.where(counts > 0, total / np.maximum(counts, 1), np.nan)
        centred = np.where(survives, contrast - mean, 0.0)
        variance = (centred**2).sum(axis=0) / np.maximum(counts - 1, 1)
        variance = np.where(counts >= 2, variance, np.nan)
        standard_error = np.sqrt(variance / np.maximum(counts, 1))
        t_stat = np.where(standard_error > 0, mean / standard_error, np.nan)
    return t_stat, counts


def meter_alarms(contrast, survives, k: int) -> np.ndarray:
    """|T| >= t_{|S|-1}(1 - 0.025/K), per meter. NaN never alarms."""
    t_stat, counts = studentised(contrast, survives)
    critical = cal.t_critical_vector(counts - 1, int(k))
    with np.errstate(invalid="ignore"):
        return np.abs(t_stat) >= critical


def family_alarms(contrast, survives, k: int) -> np.ndarray:
    """The configuration alarm per replicate: any of the K meters alarms."""
    return meter_alarms(contrast, survives, k).any(axis=-1)


# --- intervals --------------------------------------------------------------------------------


def clopper_pearson(successes: int, trials: int, confidence: float = CP_CONFIDENCE) -> dict:
    """The two-sided Clopper-Pearson interval of a binomial rate (J7)."""
    successes, trials = int(successes), int(trials)
    if trials <= 0:
        raise ValueError("a Clopper-Pearson interval needs at least one trial")
    if not 0 <= successes <= trials:
        raise ValueError(f"{successes} successes out of {trials} trials is impossible")
    tail = (1.0 - float(confidence)) / 2.0
    low = 0.0 if successes == 0 else float(stats.beta.ppf(tail, successes,
                                                          trials - successes + 1))  # fmt: skip
    high = 1.0 if successes == trials else float(
        stats.beta.isf(tail, successes + 1, trials - successes))
    return {"successes": successes, "trials": trials, "rate": successes / trials,
            "low": low, "high": high}  # fmt: skip


def pooled_record(successes: int, trials: int) -> dict:
    """A Clopper-Pearson record with the follow-up's Wilson record carried beside it (J7)."""
    record = clopper_pearson(successes, trials)
    record["wilson_descriptive"] = pa.rate_record(int(successes), int(trials))
    return record


# --- one cell on one network --------------------------------------------------------------------


def cell_network(code: str, cell: dict, axis: dict, rules: dict, cache: dict, *,
                 replicates: int = REPLICATES, block: int = BLOCK) -> dict:  # fmt: skip
    """Both arms of one primary cell on one network, with independent trials per rule."""
    replicates, block = int(replicates), int(block)
    if replicates % block:
        raise ValueError(f"{replicates} replicates is not a multiple of the block {block}")
    k = int(cell["K"])
    names = sorted(rules)
    for name in names:  # J5: the frozen configuration is still formed, so a short rule fails
        pa.configuration(rules[name], k)
    successes = {arm: np.zeros(len(names), dtype=np.int64) for arm in ARMS}
    kept_days = {"min": None, "sum": 0, "meters": 0, "too_few_days": 0}
    for index, name in enumerate(names):
        for order in range(replicates // block):
            rng = block_rng(code, cell["cell_id"], name, order)
            draws = meter_draws(rng, cell, axis, block, cache)
            busbar = busbar_contrast(rng, axis, block, cell["sigma_bb"])
            series = {"C2": draws["contrast"],
                      "C2_ref": draws["contrast"] - busbar[:, :, None]}  # fmt: skip
            for arm in ARMS:
                successes[arm][index] += int(family_alarms(series[arm], draws["survives"],
                                                           k).sum())  # fmt: skip
            counts = draws["survives"].sum(axis=0)
            kept_days["min"] = int(counts.min()) if kept_days["min"] is None else min(
                kept_days["min"], int(counts.min()))
            kept_days["sum"] += int(counts.sum())
            kept_days["meters"] += int(counts.size)
            kept_days["too_few_days"] += int((counts < 2).sum())
    out = {
        "network": code, **{key: cell[key] for key in
                            ("cell_id", "sigma", "K", "noise", "rho", "sigma_bb_over_sigma_b",
                             "sigma_bb", "condition")},  # fmt: skip
        "rules": len(names),
        "replicates_per_rule": replicates,
        "trials_pooled": replicates * len(names),
        "kept_days": {"min": kept_days["min"],
                      "mean": kept_days["sum"] / max(kept_days["meters"], 1),
                      "meters_with_fewer_than_two_kept_days": kept_days["too_few_days"]},
        "arms": {},
    }  # fmt: skip
    for arm in ARMS:
        counts = successes[arm]
        per_rule = [clopper_pearson(int(counts[i]), replicates) for i in range(len(names))]
        out["arms"][arm] = {
            "rule_names": names,
            "per_rule": per_rule,
            "pooled_over_rules": pooled_record(int(counts.sum()), replicates * len(names)),
            "rules_with_lower_bound_over_0.05": int(
                sum(1 for record in per_rule if record["low"] > 0.05)),
            "max_rule_rate": max(record["rate"] for record in per_rule),
            "worst_rule_by_lower_bound": names[int(np.argmax([r["low"] for r in per_rule]))],
        }
    return out


# --- H1a and K2 ----------------------------------------------------------------------------------


def criterion(per_cell: dict, *, cell_ids: list[str], cell_tolerance: int, label: str) -> dict:
    """The pre-stated three-part rule over a named set of cells (J8).

    `per_cell` maps a cell id to that cell's arm block. The verdict is three-valued because
    acceptance and falsification are not complements.
    """
    missing = [c for c in cell_ids if c not in per_cell]
    if missing:
        raise RuntimeError(f"{label}: these cells have no result: {missing}")
    successes = sum(per_cell[c]["pooled_over_rules"]["successes"] for c in cell_ids)
    trials = sum(per_cell[c]["pooled_over_rules"]["trials"] for c in cell_ids)
    pooled = pooled_record(successes, trials)
    failing = [c for c in cell_ids if per_cell[c]["pooled_over_rules"]["low"] > 0.05]
    over_two = [c for c in cell_ids if per_cell[c]["rules_with_lower_bound_over_0.05"] > 2]
    over_rate = [c for c in cell_ids if per_cell[c]["max_rule_rate"] > 0.08]
    both = sorted(set(over_two) & set(over_rate))
    allowed = len(cell_ids) - int(cell_tolerance)
    clause_1 = pooled["low"] <= 0.05 and len(failing) <= allowed
    accepted = clause_1 and not over_two and not over_rate
    falsified = (pooled["low"] > 0.05) or (len(failing) > allowed) or bool(both)
    return {
        "label": label,
        "cells": len(cell_ids),
        "cell_tolerance": int(cell_tolerance),
        "cells_allowed_to_fail": allowed,
        "pooled_over_rules_and_cells": pooled,
        "clause_1_pooled_lower_bound_at_most_0.05": pooled["low"] <= 0.05,
        "cells_failing_per_cell_lower_bound": failing,
        "clause_1": bool(clause_1),
        "cells_with_more_than_2_rules_over_0.05": over_two,
        "clause_2": not over_two,
        "cells_with_a_rule_rate_over_0.08": over_rate,
        "clause_3": not over_rate,
        "cells_violating_clauses_2_and_3_together": both,
        "accepted": bool(accepted),
        "falsified": bool(falsified),
        "verdict": "FALSIFIED" if falsified else ("ACCEPTED" if accepted else "INDETERMINATE"),
    }  # fmt: skip


def k2_verdict(per_cell: dict, label: str) -> dict:
    """K2 on the 12 N1 cells, at the 11-of-12 tolerance."""
    block = criterion(per_cell, cell_ids=N1_CELL_IDS, cell_tolerance=K2_RULE["cell_tolerance"],
                      label=label)  # fmt: skip
    block["K2"] = "TRIPPED" if block["falsified"] else "NOT TRIPPED"
    block["not_accepted"] = not block["accepted"]
    return block


def penalty(per_cell_ref: dict, per_cell_raw: dict) -> dict:
    """The referencing size penalty: C2-ref minus C2 on matched cells (J9)."""
    rows = {c: per_cell_ref[c]["pooled_over_rules"]["rate"]
            - per_cell_raw[c]["pooled_over_rules"]["rate"] for c in per_cell_ref}  # fmt: skip
    values = np.array(list(rows.values()), dtype=float)
    worst = max(rows, key=lambda c: rows[c])
    return {
        "definition": "C2-ref minus C2, pooled-over-rules point estimates, same cell",
        "per_cell": {c: float(v) for c, v in rows.items()},
        "min": float(values.min()), "median": float(np.median(values)),
        "mean": float(values.mean()), "max": float(values.max()),
        "largest_cell": worst,
    }  # fmt: skip


# --- parts and the merge --------------------------------------------------------------------------


def axis_record(axis: dict) -> dict:
    return {key: axis[key] for key in
            ("D_retained", "D_simulated", "delay_applied", "candidate_days",
             "dropped_no_daylight_or_night", "n_day_median", "n_night_median", "source")
            } | {"first_day": axis["days"][0], "last_day": axis["days"][-1],
                 "count_distribution": cal.count_distribution(axis)}  # fmt: skip


def _reported(path: Path) -> str:
    """A repository-relative path where that is possible, and the plain path otherwise."""
    path = Path(path)
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def part_path(network: str, sigma: str) -> Path:
    return PARTS / f"size_grid_{network.replace('--', '_').replace('-', '_')}_{sigma}.json"


def run_part(network: str, sigma: str, *, replicates: int = REPLICATES, block: int = BLOCK,
             write: bool = True, output: Path | None = None) -> dict:  # fmt: skip
    """One (network, sigma) part of the grid: 18 cells, both arms."""
    if network not in NETWORKS:
        raise ValueError(f"{network} is not a sweep network {list(NETWORKS)}")
    if sigma not in SIGMAS:
        raise ValueError(f"{sigma} is not a primary sigma {list(SIGMAS)}")
    payload: dict = {
        "task": "Calibrated-detection pilot step 1: the C2-ref size grid, independent trials",
        "part": {"network": network, "sigma": sigma},
        "status": STATUS,
        "pre_stated_readings": PRE_STATED_READINGS,  # written before any rate below exists
        "design": design(replicates),
        "H1a_rule": H1A_RULE,
        "K2_rule": K2_RULE,
        "judgement_calls": JUDGEMENT_CALLS,
        "limitations": LIMITATIONS,
        "provenance": {
            "phase9_registration": pa.REGISTRATION,
            "phase9_registration_sha256": pa.REGISTRATION_SHA256,
            "placements": q1.PLACEMENTS,
            "imported_unmodified": [
                "phase9_analysis.noise_spec", "phase9_analysis.draw_replicate",
                "phase9_analysis.placements", "phase9_analysis.configuration",
                "phase9_analysis.rate_record", "q1_voltage_residual.write_new_json",
                "calibration.development_axis", "calibration.ar1_day_night_spec",
                "calibration.draw_ar1_within_day", "calibration.t_critical_vector",
                "calibration.count_distribution", "common_mode.draw_busbar",
                "common_mode.SIGMA_SUB", "common_mode.referenced_sigma",
            ],
            "sigma_v_substation_registered": cm.SIGMA_SUB,
            "power_flows_run": 0,
            "vm_arrays_loaded": 0,
            "phase9_files_written": 0,
        },
    }
    started = time.perf_counter()
    axis = cal.development_axis(network)
    rules = pa.placements(network)
    cache = noise_cache(axis)
    payload["development_axis"] = axis_record(axis)
    payload["cells"] = {}
    for cell in cells(sigma):
        payload["cells"][cell["cell_id"]] = cell_network(
            network, cell, axis, rules, cache, replicates=replicates, block=block)
    payload["elapsed_seconds"] = time.perf_counter() - started
    payload = q1._plain(payload)
    if write:
        path = Path(output) if output is not None else part_path(network, sigma)
        payload["_sha256"] = q1.write_new_json(path, payload)
        payload["_path"] = str(path)
    return payload


def merge(output: Path = OUTPUT, parts_dir: Path = PARTS) -> dict:
    """Join the four parts into the single write-once result and apply H1a and K2."""
    blocks = {}
    for network in NETWORKS:
        for sigma in SIGMAS:
            path = Path(parts_dir) / part_path(network, sigma).name
            if not path.exists():
                raise RuntimeError(f"{path} is missing; run its `part` command first")
            blocks[(network, sigma)] = json.loads(path.read_text())
    reference = blocks[(NETWORKS[0], SIGMAS[0])]
    for key, block in blocks.items():
        for field in ("design", "H1a_rule", "K2_rule", "pre_stated_readings", "status"):
            if block[field] != reference[field]:
                raise RuntimeError(f"part {key} carries a different `{field}` block")

    payload: dict = {
        "task": "Calibrated-detection pilot step 1: the C2-ref size grid, independent trials",
        "status": reference["status"],
        "pre_stated_readings": reference["pre_stated_readings"],
        "design": reference["design"],
        "H1a_rule": reference["H1a_rule"],
        "K2_rule": reference["K2_rule"],
        "judgement_calls": reference["judgement_calls"],
        "limitations": reference["limitations"],
        "provenance": reference["provenance"] | {
            "parts": {f"{network}|{sigma}": _reported(
                Path(parts_dir) / part_path(network, sigma).name)
                for network, sigma in blocks},
            "part_elapsed_seconds": {f"{network}|{sigma}": block["elapsed_seconds"]
                                     for (network, sigma), block in blocks.items()},
        },  # fmt: skip
        "development_axis": {network: blocks[(network, SIGMAS[0])]["development_axis"]
                             for network in NETWORKS},  # fmt: skip
    }
    per_network: dict = {}
    for network in NETWORKS:
        merged: dict = {}
        for sigma in SIGMAS:
            merged.update(blocks[(network, sigma)]["cells"])
        if sorted(merged) != sorted(CELL_IDS):
            raise RuntimeError(f"{network}: {len(merged)} cells, not the {len(CELL_IDS)} "
                               "primary cells")  # fmt: skip
        per_network[network] = merged
    payload["results"] = per_network

    verdicts: dict = {}
    for network in NETWORKS:
        arms = {arm: {c: per_network[network][c]["arms"][arm] for c in CELL_IDS}
                for arm in ARMS}  # fmt: skip
        verdicts[network] = {
            "H1a": {arm: criterion(arms[arm], cell_ids=CELL_IDS,
                                   cell_tolerance=H1A_RULE["cell_tolerance"],
                                   label=f"{network} {arm} H1a") for arm in ARMS},  # fmt: skip
            "K2": k2_verdict(arms["C2_ref"], f"{network} C2-ref K2"),
            "K2_comparator_C2": k2_verdict(arms["C2"], f"{network} C2 K2"),
            "referencing_size_penalty": penalty(arms["C2_ref"], arms["C2"]),
        }
    payload["per_network"] = verdicts
    payload["overall"] = {
        "convention": "the criterion must hold in both sweep networks (J1)",
        "H1a": {arm: {
            "verdict": "FALSIFIED" if any(
                verdicts[n]["H1a"][arm]["falsified"] for n in NETWORKS) else (
                "ACCEPTED" if all(verdicts[n]["H1a"][arm]["accepted"] for n in NETWORKS)
                else "INDETERMINATE"),
            "per_network": {n: verdicts[n]["H1a"][arm]["verdict"] for n in NETWORKS},
        } for arm in ARMS},  # fmt: skip
        "K2": {
            "verdict": "TRIPPED" if any(verdicts[n]["K2"]["falsified"] for n in NETWORKS)
                       else "NOT TRIPPED",  # fmt: skip
            "per_network": {n: verdicts[n]["K2"]["K2"] for n in NETWORKS},
            "reading": PRE_STATED_READINGS[0],
        },
        "pooled_over_networks": {arm: pooled_record(
            sum(per_network[n][c]["arms"][arm]["pooled_over_rules"]["successes"]
                for n in NETWORKS for c in CELL_IDS),
            sum(per_network[n][c]["arms"][arm]["pooled_over_rules"]["trials"]
                for n in NETWORKS for c in CELL_IDS)) for arm in ARMS},  # fmt: skip
        "referencing_size_penalty": {n: {key: verdicts[n]["referencing_size_penalty"][key]
                                         for key in ("min", "median", "mean", "max",
                                                     "largest_cell")}
                                     for n in NETWORKS},  # fmt: skip
    }
    payload = q1._plain(payload)
    payload["_sha256"] = q1.write_new_json(Path(output), payload)
    payload["_path"] = str(Path(output))
    return payload


# --- the compact summary ------------------------------------------------------------------------


def _short(code: str) -> str:
    return code.split("-")[2]


def print_summary(payload: dict) -> None:
    print(f"status: {payload['status']}")
    for reading in payload["pre_stated_readings"]:
        print(f"  pre-stated: {reading}")
    design_block = payload["design"]
    print(f"cells: {design_block['primary_cells']}  rules: 25  "
          f"replicates per rule: {design_block['replicates_per_rule']}  "
          f"power flows: {design_block['power_flows_run']}")
    for network, axis in payload["development_axis"].items():
        print(f"  {_short(network)}: D_retained={axis['D_retained']} "
              f"D_simulated={axis['D_simulated']} "
              f"n_day_med={axis['n_day_median']:g} n_night_med={axis['n_night_median']:g}")

    print("\n== the 36 primary cells, pooled over 25 rules [Clopper-Pearson 95 %] ==")
    print(f"{'cell':<30}{'net':<10}"
          f"{'C2-ref rate [CP95]':>28}{'cell':>6}{'>.05':>5}{'maxr':>7}"
          f"{'C2 rate [CP95]':>28}{'cell':>6}{'>.05':>5}{'maxr':>7}{'pen':>8}")
    for network in payload["results"]:
        for cell in payload["results"][network]:
            block = payload["results"][network][cell]
            line = f"{cell:<30}{_short(network):<10}"
            for arm in ARMS:
                arm_block = block["arms"][arm]
                record = arm_block["pooled_over_rules"]
                line += (f"{record['rate']:.4f}[{record['low']:.4f},"
                         f"{record['high']:.4f}]".rjust(28))
                line += f"{'ok' if record['low'] <= 0.05 else 'FAIL':>6}"
                line += f"{arm_block['rules_with_lower_bound_over_0.05']:>5}"
                line += f"{arm_block['max_rule_rate']:>7.3f}"
            ref = block["arms"]["C2_ref"]["pooled_over_rules"]["rate"]
            raw = block["arms"]["C2"]["pooled_over_rules"]["rate"]
            line += f"{ref - raw:>+8.4f}"
            print(line)

    print("\n== H1a (36 cells, tolerance 33) ==")
    for network, block in payload["per_network"].items():
        for arm in ARMS:
            entry = block["H1a"][arm]
            pooled = entry["pooled_over_rules_and_cells"]
            print(f"  {_short(network):<10}{arm:<8}{entry['verdict']:<14}"
                  f"pooled {pooled['rate']:.4f}[{pooled['low']:.4f},{pooled['high']:.4f}]  "
                  f"cells failing {len(entry['cells_failing_per_cell_lower_bound'])}"
                  f"/{entry['cells_allowed_to_fail']} allowed  "
                  f"clause2 {'ok' if entry['clause_2'] else 'NO'}  "
                  f"clause3 {'ok' if entry['clause_3'] else 'NO'}")
    for arm in ARMS:
        print(f"  overall {arm}: {payload['overall']['H1a'][arm]['verdict']}")

    print("\n== K2 (12 N1 cells, tolerance 11) ==")
    for network, block in payload["per_network"].items():
        entry = block["K2"]
        pooled = entry["pooled_over_rules_and_cells"]
        print(f"  {_short(network):<10}C2-ref {entry['K2']:<12}"
              f"pooled {pooled['rate']:.4f}[{pooled['low']:.4f},{pooled['high']:.4f}]  "
              f"cells failing {len(entry['cells_failing_per_cell_lower_bound'])}"
              f"/{entry['cells_allowed_to_fail']}  verdict {entry['verdict']}")
        comparator = block["K2_comparator_C2"]
        print(f"  {'':<10}C2     {comparator['K2']:<12}"
              f"pooled {comparator['pooled_over_rules_and_cells']['rate']:.4f}")
    print(f"  overall K2: {payload['overall']['K2']['verdict']}")
    print(f"  {payload['overall']['K2']['reading']}")

    print("\n== referencing size penalty (C2-ref minus C2, pooled per cell) ==")
    for network, block in payload["overall"]["referencing_size_penalty"].items():
        print(f"  {_short(network):<10}min {block['min']:+.4f}  median {block['median']:+.4f}  "
              f"mean {block['mean']:+.4f}  max {block['max']:+.4f} at {block['largest_cell']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("part", "probe", "merge", "summary"))
    parser.add_argument("--network", default=None)
    parser.add_argument("--sigma", default=None)
    parser.add_argument("--replicates", type=int, default=REPLICATES)
    parser.add_argument("--block", type=int, default=BLOCK)
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args(argv)
    if args.command in ("part", "probe"):
        if args.network is None or args.sigma is None:
            parser.error("`part` and `probe` need --network and --sigma")
        payload = run_part(args.network, args.sigma, replicates=args.replicates,
                           block=args.block, write=args.command == "part")  # fmt: skip
        if args.command == "part":
            print(f"wrote {payload['_path']} sha256={payload['_sha256']}")
        print(f"{args.command} {args.network} sigma={args.sigma} "
              f"replicates={args.replicates} cells={len(payload['cells'])} "
              f"elapsed={payload['elapsed_seconds']:.1f}s")
        for name, block in payload["cells"].items():
            print(f"  {name:<30}"
                  + "  ".join(f"{arm} {block['arms'][arm]['pooled_over_rules']['rate']:.4f}"
                              for arm in ARMS))
        return 0
    if args.command == "merge":
        payload = merge(Path(args.out))
        print(f"wrote {payload['_path']} sha256={payload['_sha256']}\n")
    else:
        payload = json.loads(Path(args.out).read_text())
    print_summary(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
