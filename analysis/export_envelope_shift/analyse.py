"""Mission 11 Stage A: the analysis. Zero AC solves, zero LP solves.

This module reads the artefacts that `stage_a.py` wrote and computes the protocol's verdict
mechanics: the hypothesis tests of s. 9, the negative controls of s. 10, the s. 15 stop
labels, the excitation table, the ledger reconstruction and the provenance record. It never
imports `pandapower` or `simbench`, never runs a solve, and never rewrites an artefact.

**Amendment A2 is load-bearing.** semiurb5 kept only 2 of 40 near candidates, so H1-H3 are
NOT EVALUABLE there and nothing that needs "both networks" can be Supported. Verdicts are
computed on **rural3 as single-network results**; semiurb5's identical computations are
carried in the same structure under the label `descriptive (A2)`. Each hypothesis block also
records `formal_two_network = "Supported not attainable (A2)"`.

Commands:

* `summary` -- write `results/stage_a_summary.json` (write-once);
* `figures` -- write `figures/fig_{a..f}_*.svg` (write-once).

Both verify the protocol's sha256, and its as-executed text, before reading anything.
`--dry-run` computes and prints without writing, so the write-once artefacts are produced
exactly once.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:  # imported, never copied or edited
    sys.path.insert(0, str(HERE))

import envelope_core as ec  # noqa: E402
import svgplot  # noqa: E402

RESULTS = HERE / "results"
RUNS = HERE / "runs"
FIGURES = HERE / "figures"
SUMMARY_PATH = RESULTS / "stage_a_summary.json"

FROZEN_CODE = ("stage_a.py", "envelope_core.py", "envelope_lp.py")

NETWORKS = ("rural3", "semiurb5")
EVALUATION_NETWORK = "rural3"
A2_LABEL = "descriptive (A2)"

REGIMES = ("P1", "P2", "P3", "L0")
TRAINING_REGIMES = ("P1", "P2", "P3")
DATA_DRIVEN = ("B1", "B2", "B2m", "B2p", "B3", "B4box", "B4")
SIMPLE_POLICIES = ("B2m", "B2p", "B0")
ROBUST_METHODS = ("B4", "B4box")
REFERENCES = ("B0", "A", "Aprime")
#: The three distinct voltage models of s. 9's H2, and the method each one is read from.
VOLTAGE_MODELS = (("OLS", "B1"), ("ridge", "B2"), ("NNLS", "B3"))
#: Every method's voltage model, for the descriptive 21-cell table.
MODEL_OF_METHOD = {
    "B1": "OLS",
    "B2": "ridge",
    "B2m": "ridge",
    "B2p": "ridge",
    "B3": "NNLS",
    "B4box": "ridge",
    "B4": "ridge",
}
NO_REGIME = "-"
NO_REPLICATE = -1

DEGENERATE = "robust-degenerate"
LEDGER_START = 106
LEDGER_CEILING = 8000
PLANNED_TOTAL = 7630

#: s. 9's Holm family, in the order fixed by the protocol.
HOLM_FAMILY = (
    ("H1", "rural3"),
    ("H1", "semiurb5"),
    ("H3", "rural3"),
    ("H3", "semiurb5"),
)
ALPHA = 0.05

#: s. 9 and s. 13 thresholds, named so that no magic number appears in a verdict.
H1_SUPPORT_DIFFERENCE = 0.20
H1_NULL_BAND = 0.10
H1_CONTROL_H_BAND = 0.10
H1_CONTROL_I_BAND = 0.10
H2_MAE_LIMIT = 0.001
H2_UNSAFE_FLOOR = 0.30
H2_SPEARMAN_SUPPORT = 0.5
H2_SPEARMAN_REJECT = 0.8
H3_UTILISATION_MARGIN = 0.10
H3_REJECT_MARGIN = 0.05
H3_MIN_JOINT = 7
H3_DEGENERATE_COUNT = 5
H4_MATERIAL_SPREAD = 0.10
H4_MATERIAL_DISAGREEMENT = 0.30
H4_EQUIVALENCE_SPREAD = 0.05
BINDING_MIN = 7
APRIME_STOP = 5
APRIME_SENSITIVE = 3
STAGE2_MOVE_LIMIT = 0.01
THERMAL_UNSAFE_PERCENT = 100.5
CONTROL_T_APPROXIMATION_LIMIT = 0.05
FLOAT_MAX_CONDITION = float(np.finfo(np.float64).max)

NOT_EVALUABLE = "NOT EVALUABLE"


# --- A. loading the artefacts -----------------------------------------------------------


def _artefact_paths(network: str) -> dict[str, Path]:
    paths = {
        "envelopes": RESULTS / f"envelopes_{network}.json",
        "oracle": RESULTS / f"oracle_{network}.json",
        "controls": RESULTS / f"controls_{network}.json",
        "ambiguity": RESULTS / f"ambiguity_{network}.json",
        "monotonicity": RESULTS / f"monotonicity_{network}.json",
        "marginals": RESULTS / f"marginals_{network}.json",
        "selection": RESULTS / f"selection_{network}.json",
        "oracle_npz": RUNS / f"oracle_{network}.npz",
    }
    for regime in REGIMES:
        paths[f"physics_{regime}"] = RESULTS / f"physics_{network}_{regime}.json"
    return paths


def artefacts_present(network: str) -> tuple[list[str], list[str]]:
    """The present and the missing artefact keys for one network."""
    paths = _artefact_paths(network)
    present = sorted(key for key, path in paths.items() if path.exists())
    missing = sorted(key for key, path in paths.items() if not path.exists())
    return present, missing


@dataclass
class Network:
    """One network's artefacts, with the per-condition index resolved."""

    name: str
    payloads: dict[str, dict]
    paths: dict[str, Path]
    best_e: np.ndarray
    near_rows: tuple[int, ...]
    far_rows: tuple[int, ...]
    oracle_total: dict[int, float] = field(default_factory=dict)

    @property
    def envelopes(self) -> dict:
        return self.payloads["envelopes"]

    @property
    def records(self) -> list[dict]:
        return self.envelopes["records"]

    @property
    def n_near(self) -> int:
        return len(self.near_rows)

    @property
    def evaluable(self) -> bool:
        return self.name == EVALUATION_NETWORK

    @property
    def label(self) -> str:
        return "scored" if self.evaluable else A2_LABEL


def load_network(network: str) -> Network:
    """Read one network's artefacts, failing loudly on a partial or inconsistent set."""
    paths = _artefact_paths(network)
    present, missing = artefacts_present(network)
    if missing:
        raise FileNotFoundError(
            f"{network}: {len(missing)} of {len(paths)} artefacts are missing "
            f"({', '.join(missing)}); {len(present)} are present. The analysis needs the "
            "complete set, and a partial set is an inconsistency, not a skip."
        )
    payloads = {
        key: json.loads(path.read_text()) for key, path in paths.items() if key != "oracle_npz"
    }
    with np.load(paths["oracle_npz"]) as bundle:
        best_e = np.asarray(bundle["best_e"], dtype=float)
        oracle_rows = np.asarray(bundle["row"], dtype=int)

    near_rows = tuple(
        sorted({int(r["row"]) for r in payloads["envelopes"]["records"] if r["kind"] == "near"})
    )
    far_rows = tuple(
        sorted({int(r["row"]) for r in payloads["envelopes"]["records"] if r["kind"] == "far"})
    )
    if tuple(oracle_rows.tolist()) != near_rows:
        raise ValueError(
            f"{network}: oracle rows {oracle_rows.tolist()} do not match the envelope near "
            f"rows {list(near_rows)}; the artefacts are inconsistent"
        )
    if len(near_rows) != int(payloads["envelopes"]["n_near"]):
        raise ValueError(
            f"{network}: {len(near_rows)} near rows in the records against "
            f"n_near = {payloads['envelopes']['n_near']}"
        )

    net = Network(
        name=network,
        payloads=payloads,
        paths=paths,
        best_e=best_e,
        near_rows=near_rows,
        far_rows=far_rows,
    )
    totals = best_e.sum(axis=1)
    net.oracle_total = {
        int(row): float(total) for row, total in zip(oracle_rows, totals, strict=True)
    }
    json_totals = {int(r["row"]): float(r["total_e"]) for r in payloads["oracle"]["records"]}
    for row, total in net.oracle_total.items():
        if not math.isclose(total, json_totals[row], rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError(
                f"{network} row {row}: oracle best_e total {total} != the artefact's "
                f"total_e {json_totals[row]}"
            )
    return net


# --- B. record conventions (s. 9, s. 12) ------------------------------------------------


def is_unsafe(record: dict) -> bool:
    """s. 12: a failed power flow counts as unsafe, never as safe."""
    return bool(record.get("unsafe")) or not bool(record.get("converged", True))


def is_degenerate(record: dict) -> bool:
    return str(record.get("status", "")) == DEGENERATE


def pick(
    records: list[dict],
    method: str | None = None,
    regime: str | None = None,
    kind: str | None = None,
    replicate: int | None = None,
    control: str | None = None,
) -> list[dict]:
    """Every record matching the given fields, in artefact order."""
    out = []
    for record in records:
        if method is not None and record.get("method") != method:
            continue
        if regime is not None and record.get("regime") != regime:
            continue
        if kind is not None and record.get("kind") != kind:
            continue
        if replicate is not None and int(record.get("replicate", NO_REPLICATE)) != replicate:
            continue
        if control is not None and record.get("control") != control:
            continue
        out.append(record)
    return out


def by_row(records: list[dict], rows: tuple[int, ...]) -> dict[int, list[dict]]:
    grouped: dict[int, list[dict]] = {row: [] for row in rows}
    for record in records:
        row = int(record["row"])
        if row in grouped:
            grouped[row].append(record)
    return grouped


def condition_rates(records: list[dict], rows: tuple[int, ...]) -> np.ndarray:
    """u_i: the mean over the replicates present of unsafe(r, i). NaN where no record is."""
    grouped = by_row(records, rows)
    out = np.full(len(rows), np.nan)
    for index, row in enumerate(rows):
        group = grouped[row]
        if group:
            out[index] = float(np.mean([is_unsafe(r) for r in group]))
    return out


def unsafe_conditions(records: list[dict], rows: tuple[int, ...]) -> int:
    """The number of conditions with an unsafe record in **any** replicate (s. 9)."""
    grouped = by_row(records, rows)
    return sum(1 for row in rows if any(is_unsafe(r) for r in grouped[row]))


def degenerate_conditions(records: list[dict], rows: tuple[int, ...]) -> int:
    grouped = by_row(records, rows)
    return sum(1 for row in rows if any(is_degenerate(r) for r in grouped[row]))


def safe_in_every_replicate(records: list[dict], rows: tuple[int, ...]) -> dict[int, bool]:
    grouped = by_row(records, rows)
    return {
        row: bool(grouped[row]) and not any(is_unsafe(r) or is_degenerate(r) for r in grouped[row])
        for row in rows
    }


def condition_utilisation(
    records: list[dict],
    rows: tuple[int, ...],
    denominator: dict[int, float],
    unsafe_as_zero: bool,
) -> np.ndarray:
    """U_i = Sum(e)/Sum(e_B5(i)), averaged over replicates.

    `unsafe_as_zero=False` keeps the s. 9 definition (utilisation exists only for a
    voltage-safe envelope) and returns NaN for a condition with no safe replicate.
    `unsafe_as_zero=True` is the companion comparison's convention: an unsafe or degenerate
    record scores 0.
    """
    grouped = by_row(records, rows)
    out = np.full(len(rows), np.nan)
    for index, row in enumerate(rows):
        values = []
        for record in grouped[row]:
            bad = is_unsafe(record) or is_degenerate(record)
            if bad and not unsafe_as_zero:
                continue
            values.append(0.0 if bad else float(record["total_e"]) / denominator[row])
        if values:
            out[index] = float(np.mean(values))
    return out


def _finite(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    return values[np.isfinite(values)]


def _median(values) -> float:
    finite = _finite(np.asarray(values, dtype=float))
    return float(np.median(finite)) if finite.size else float("nan")


def _nan_to_none(value):
    if isinstance(value, (float, np.floating)):
        value = float(value)
        return None if not math.isfinite(value) else value
    return value


def bootstrap_block(differences: np.ndarray, network: str, test_name: str) -> dict:
    """`ec.paired_bootstrap` over the conditions, with the protocol's seed."""
    finite = _finite(differences)
    if finite.size == 0:
        return {
            "n": 0,
            "mean": None,
            "interval_95": [None, None],
            "p": None,
            "status": NOT_EVALUABLE,
            "reason": "no condition carries a finite difference",
        }
    rng = ec.rng_for(network, test_name, "bootstrap", 0)
    result = ec.paired_bootstrap(finite, rng)
    return {
        "n": int(result.n),
        "mean": float(result.mean),
        "interval_95": [float(result.lo), float(result.hi)],
        "p": float(result.p),
        "seed_test_name": test_name,
        "status": "computed",
    }


def clopper_pearson_block(k: int, n: int) -> dict:
    lo, hi = ec.clopper_pearson(int(k), int(n))
    return {"k": int(k), "n": int(n), "rate": k / n, "interval_95": [lo, hi]}


# --- C. H1 (s. 9) -----------------------------------------------------------------------


def _control_h_block(net: Network) -> dict:
    """Control H: B2's P1 near unsafe rate at T = 768 (r = 0) against P3's at T = 384."""
    controls = net.payloads["controls"]["records"]
    arms = {}
    for arm, train_steps in (("H192", 192), ("H768", 768)):
        records = pick(controls, method=arm, kind="near")
        if not records:
            arms[arm] = {"status": NOT_EVALUABLE, "reason": "no record", "train_steps": train_steps}
            continue
        rates = condition_rates(records, net.near_rows)
        arms[arm] = {
            "train_steps": train_steps,
            "replicates": sorted({int(r["replicate"]) for r in records}),
            "regime": sorted({r["regime"] for r in records}),
            "near_unsafe_rate": float(np.nanmean(rates)),
            "unsafe_conditions": unsafe_conditions(records, net.near_rows),
            "n_conditions": net.n_near,
            "lam": sorted({float(r["lam"]) for r in records}),
        }
    baseline = condition_rates(
        pick(net.records, method="B2", regime="P3", kind="near"), net.near_rows
    )
    reference_rate = float(np.nanmean(baseline))
    block = {
        "definition": (
            "B2 at T = 192 and T = 768 (P1, replicate 0, rural3) against B2's P3 near unsafe "
            "rate at T = 384 over both replicates"
        ),
        "arms": arms,
        "b2_p3_t384_near_unsafe_rate": reference_rate,
        "lam_t384": sorted({float(f["lam"]) for f in net.envelopes["fits"] if f["regime"] == "P1"}),
    }
    long_run = arms.get("H768")
    if long_run and "near_unsafe_rate" in long_run:
        difference = long_run["near_unsafe_rate"] - reference_rate
        block["t768_minus_p3_t384"] = float(difference)
        block["small_data_effect_fires"] = bool(abs(difference) <= H1_CONTROL_H_BAND)
        block["reading"] = (
            "s. 9's rejection row asks whether B2's rate at T = 768 'falls to within 0.10 of "
            "P3's at T = 384'; the flag uses |difference| <= 0.10 and the signed difference "
            "is reported beside it"
        )
    else:
        block["small_data_effect_fires"] = None
        block["status"] = NOT_EVALUABLE
    return block


def _control_i_block(net: Network) -> dict:
    """Control I: the P1 - P3 near unsafe-rate difference at each sigma_v (r = 0)."""
    controls = net.payloads["controls"]["records"]
    out: dict = {
        "definition": (
            "B2's near unsafe rate, P1 minus P3, at each sigma_v, replicate 0; the registered "
            "cell sigma_v = 0.002 is the envelope stage over both replicates"
        ),
        "arms": {},
    }
    for arm, sigma in (("I0.0005", 0.0005), ("I0.005", 0.005)):
        entry: dict = {"sigma_v": sigma}
        rates = {}
        for regime in ("P1", "P3"):
            records = pick(controls, method=arm, regime=regime, kind="near")
            if not records:
                entry.setdefault("missing", []).append(regime)
                continue
            rates[regime] = float(np.nanmean(condition_rates(records, net.near_rows)))
            entry[f"{regime}_unsafe_conditions"] = unsafe_conditions(records, net.near_rows)
            entry[f"{regime}_lam"] = sorted({float(r["lam"]) for r in records})
        entry["near_unsafe_rate"] = rates
        if len(rates) == 2:
            entry["p1_minus_p3"] = rates["P1"] - rates["P3"]
        out["arms"][arm] = entry
    registered = {}
    for regime in ("P1", "P3"):
        registered[regime] = float(
            np.nanmean(
                condition_rates(
                    pick(net.records, method="B2", regime=regime, kind="near"), net.near_rows
                )
            )
        )
    out["arms"]["registered_0.002"] = {
        "sigma_v": float(net.envelopes["sigma_v"]),
        "near_unsafe_rate": registered,
        "p1_minus_p3": registered["P1"] - registered["P3"],
        "replicates": [0, 1],
    }
    low = out["arms"].get("I0.0005", {}).get("p1_minus_p3")
    out["noise_only_effect_fires"] = None if low is None else bool(low < H1_CONTROL_I_BAND)
    out["b2_lambda_per_arm"] = {
        "T384_sigma0.002": sorted({float(f["lam"]) for f in net.envelopes["fits"]}),
        "H192": sorted(
            {float(a["lam"]) for a in net.payloads["controls"]["control_h"] if a["arm"] == "H192"}
        ),
        "H768": sorted(
            {float(a["lam"]) for a in net.payloads["controls"]["control_h"] if a["arm"] == "H768"}
        ),
        "I0.0005": sorted(
            {
                float(a["lam"])
                for a in net.payloads["controls"]["control_i"]
                if a["arm"] == "I0.0005"
            }
        ),
        "I0.005": sorted(
            {float(a["lam"]) for a in net.payloads["controls"]["control_i"] if a["arm"] == "I0.005"}
        ),
    }
    return out


def h1_network(net: Network) -> dict:
    """H1's contrast, controls and single-network verdict inputs for one network."""
    rows = net.near_rows
    rates = {
        regime: condition_rates(pick(net.records, "B2", regime, "near"), rows)
        for regime in TRAINING_REGIMES
    }
    d_p1_p3 = rates["P1"] - rates["P3"]
    d_p1_p2 = rates["P1"] - rates["P2"]
    primary = bootstrap_block(d_p1_p3, net.name, "H1")
    descriptive = bootstrap_block(d_p1_p2, net.name, "desc_H1_P1_minus_P2")

    control_c = net.payloads["marginals"]["control_c"]
    control_h = (
        _control_h_block(net)
        if net.evaluable
        else {
            "status": NOT_EVALUABLE,
            "reason": "control H's T = 768 arm is rural3 only (s. 10)",
            "arms": {
                arm: {
                    "near_unsafe_rate": float(
                        np.nanmean(
                            condition_rates(
                                pick(net.payloads["controls"]["records"], method=arm, kind="near"),
                                rows,
                            )
                        )
                    )
                    if pick(net.payloads["controls"]["records"], method=arm, kind="near")
                    else None
                }
                for arm in ("H192", "H768")
            },
        }
    )
    control_i = _control_i_block(net)

    per_method = {}
    for method in DATA_DRIVEN:
        method_rates = {
            regime: condition_rates(pick(net.records, method, regime, "near"), rows)
            for regime in ("P1", "P3")
        }
        difference = method_rates["P1"] - method_rates["P3"]
        per_method[method] = {
            "near_unsafe_rate": {
                regime: float(np.nanmean(values)) for regime, values in method_rates.items()
            },
            "unsafe_conditions": {
                regime: unsafe_conditions(pick(net.records, method, regime, "near"), rows)
                for regime in ("P1", "P3")
            },
            "p1_minus_p3": bootstrap_block(difference, net.name, f"desc_p1p3_{method}"),
            "label": "descriptive; only B2 is H1's registered contrast",
        }

    return {
        "network": net.name,
        "label": net.label,
        "n_conditions": net.n_near,
        "registered_contrast": "B2, near set, primary decision, P1 minus P3, paired",
        "per_condition_unsafe_rate": {
            regime: [_nan_to_none(v) for v in values] for regime, values in rates.items()
        },
        "near_unsafe_rate": {regime: float(np.nanmean(values)) for regime, values in rates.items()},
        "p1_minus_p3": primary,
        "p1_minus_p2_descriptive": descriptive,
        "control_c": {
            "passed": bool(control_c["passed"]),
            "per_regime_pass": {
                regime: bool(entry["passed"]) for regime, entry in control_c["against_P1"].items()
            },
            "criterion": (
                "every PV unit's training-day mean within 1 % of P1, and the median relative "
                "daylight-P95 difference within 10 % (s. 10, M11)"
            ),
        },
        "control_h": control_h,
        "control_i": control_i,
        "per_method_p1_minus_p3_descriptive": per_method,
    }


def h1_verdict(block: dict, holm: dict) -> dict:
    """s. 9's H1 table, with 'both networks' read as 'rural3' (A2)."""
    primary = block["p1_minus_p3"]
    mean = primary.get("mean")
    low, high = primary.get("interval_95", [None, None])
    small_data = block["control_h"].get("small_data_effect_fires")
    noise_only = block["control_i"].get("noise_only_effect_fires")
    control_c = bool(block["control_c"]["passed"])
    holm_rejected = bool(holm["rejected"])

    branch_null_band = None if low is None else bool(low >= -H1_NULL_BAND and high <= H1_NULL_BAND)
    branches = {
        "interval_within_null_band": branch_null_band,
        "small_data_effect_T768": small_data,
        "noise_only_effect_sigma_0.0005": noise_only,
    }
    rejected = any(value is True for value in branches.values())
    supported = bool(
        mean is not None
        and mean >= H1_SUPPORT_DIFFERENCE
        and holm_rejected
        and mean > 0
        and control_c
        and small_data is False
        and noise_only is False
    )
    verdict = "Supported" if supported else ("Rejected" if rejected else "Inconclusive")
    return {
        "verdict": verdict,
        "rejection_branches": branches,
        "rejection_branches_fired": [k for k, v in branches.items() if v is True],
        "support_requirements": {
            "mean_difference_at_least_0.20": None
            if mean is None
            else bool(mean >= H1_SUPPORT_DIFFERENCE),
            "lower_bound_positive_after_holm": bool(holm_rejected and (mean or 0.0) > 0),
            "control_c_passes": control_c,
            "survives_control_h": small_data is False,
            "survives_control_i": noise_only is False,
        },
        "holm": holm,
    }


# --- D. H2 (s. 9) -----------------------------------------------------------------------


def _mean_test_mae(net: Network, regime: str, model: str) -> float:
    values = [
        float(fit["test_mae"][model]) for fit in net.envelopes["fits"] if fit["regime"] == regime
    ]
    return float(np.mean(values)) if values else float("nan")


def h2_network(net: Network) -> dict:
    rows = net.near_rows
    cells = []
    for model, method in VOLTAGE_MODELS:
        for regime in TRAINING_REGIMES:
            records = pick(net.records, method, regime, "near")
            rates = condition_rates(records, rows)
            cells.append(
                {
                    "model": model,
                    "method": method,
                    "regime": regime,
                    "test_mae_pu": _mean_test_mae(net, regime, model),
                    "near_unsafe_rate": float(np.nanmean(rates)),
                    "unsafe_records": sum(1 for r in records if is_unsafe(r)),
                    "n_records": len(records),
                    "unsafe_conditions": unsafe_conditions(records, rows),
                }
            )
    mae = np.array([cell["test_mae_pu"] for cell in cells])
    unsafe = np.array([cell["near_unsafe_rate"] for cell in cells])
    rho, p_value = ec.spearman(mae, unsafe)

    qualifying = [
        cell
        for cell in cells
        if cell["regime"] == "P1"
        and cell["test_mae_pu"] <= H2_MAE_LIMIT
        and cell["near_unsafe_rate"] >= H2_UNSAFE_FLOOR
    ]
    table_21 = []
    for method in DATA_DRIVEN:
        for regime in TRAINING_REGIMES:
            records = pick(net.records, method, regime, "near")
            table_21.append(
                {
                    "method": method,
                    "model": MODEL_OF_METHOD[method],
                    "regime": regime,
                    "test_mae_pu": _mean_test_mae(net, regime, MODEL_OF_METHOD[method]),
                    "near_unsafe_rate": float(np.nanmean(condition_rates(records, rows))),
                    "unsafe_conditions": unsafe_conditions(records, rows),
                    "n_conditions": net.n_near,
                }
            )
    return {
        "network": net.name,
        "label": net.label,
        "n_conditions": net.n_near,
        "cells_9": cells,
        "spearman": {"rho": rho, "p": p_value, "n_cells": len(cells)},
        "p1_cells_meeting_accuracy_and_risk": [
            f"{cell['model']}/{cell['regime']}" for cell in qualifying
        ],
        "table_21_method_by_regime_descriptive": table_21,
        "mae_definition": (
            "the mean over replicates of the noise-free predicted voltage's MAE against the AC "
            "truth on test day 156 (96 steps), per voltage model"
        ),
    }


def h2_verdict(block: dict) -> dict:
    rho = block["spearman"]["rho"]
    has_cell = bool(block["p1_cells_meeting_accuracy_and_risk"])
    supported = bool(has_cell and rho is not None and rho < H2_SPEARMAN_SUPPORT)
    rejected = bool((not has_cell) or (rho is not None and rho >= H2_SPEARMAN_REJECT))
    verdict = "Supported" if supported else ("Rejected" if rejected else "Inconclusive")
    return {
        "verdict": verdict,
        "requirements": {
            "p1_cell_with_mae_le_0.001_and_unsafe_ge_0.30": has_cell,
            "spearman_below_0.5": None if rho is None else bool(rho < H2_SPEARMAN_SUPPORT),
            "spearman_at_least_0.8": None if rho is None else bool(rho >= H2_SPEARMAN_REJECT),
        },
    }


# --- E. H3 (s. 9) -----------------------------------------------------------------------


def _pair_block(net: Network, robust: str, simple: str, regime: str) -> dict:
    rows = net.near_rows
    robust_records = pick(net.records, robust, regime, "near")
    simple_regime = NO_REGIME if simple == "B0" else regime
    simple_records = pick(net.records, simple, simple_regime, "near")

    robust_safe = safe_in_every_replicate(robust_records, rows)
    simple_safe = safe_in_every_replicate(simple_records, rows)
    joint = tuple(row for row in rows if robust_safe[row] and simple_safe[row])

    u_robust = condition_utilisation(robust_records, rows, net.oracle_total, False)
    u_simple = condition_utilisation(simple_records, rows, net.oracle_total, False)
    index = {row: position for position, row in enumerate(rows)}
    joint_index = [index[row] for row in joint]
    paired = (u_robust[joint_index] - u_simple[joint_index]) if joint_index else np.array([])

    block = {
        "robust": robust,
        "simple": simple,
        "regime": regime,
        "joint_conditions": list(joint),
        "n_joint": len(joint),
        "n_conditions": net.n_near,
        "evaluable": bool(len(joint) >= H3_MIN_JOINT),
        "median_utilisation": {
            robust: _nan_to_none(_median(u_robust[joint_index]) if joint_index else float("nan")),
            simple: _nan_to_none(_median(u_simple[joint_index]) if joint_index else float("nan")),
        },
        "median_difference": None,
        "median_of_paired_differences": None,
        "paired_bootstrap": bootstrap_block(paired, net.name, f"H3_{robust}")
        if joint_index
        else {"status": NOT_EVALUABLE, "reason": "no joint condition"},
    }
    if joint_index:
        block["median_difference"] = float(
            _median(u_robust[joint_index]) - _median(u_simple[joint_index])
        )
        block["median_of_paired_differences"] = _nan_to_none(_median(paired))
    if not block["evaluable"]:
        block["status"] = NOT_EVALUABLE
        block["reason"] = (
            f"{len(joint)} of {net.n_near} joint conditions remain, fewer than "
            f"{H3_MIN_JOINT} (s. 9)"
        )

    companion_robust = condition_utilisation(robust_records, rows, net.oracle_total, True)
    companion_simple = condition_utilisation(simple_records, rows, net.oracle_total, True)
    companion_difference = companion_robust - companion_simple
    block["companion_all_conditions"] = {
        "convention": "utilisation 0 for an unsafe or degenerate record",
        "median_utilisation": {
            robust: _nan_to_none(_median(companion_robust)),
            simple: _nan_to_none(_median(companion_simple)),
        },
        "median_difference": _nan_to_none(_median(companion_robust) - _median(companion_simple)),
        "paired_bootstrap": bootstrap_block(
            companion_difference, net.name, f"desc_companion_{robust}_{simple}_{regime}"
        ),
    }
    joint_sign = np.sign(block["median_difference"]) if block["median_difference"] else 0.0
    companion_sign = np.sign(block["companion_all_conditions"]["median_difference"] or 0.0)
    block["sign_agreement"] = bool(joint_sign == companion_sign)
    return block


def h3_network(net: Network, regime: str = "P1") -> dict:
    rows = net.near_rows
    robust_blocks = {}
    for robust in ROBUST_METHODS:
        records = pick(net.records, robust, regime, "near")
        k_unsafe = unsafe_conditions(records, rows)
        n_degenerate = degenerate_conditions(records, rows)
        restored = [r for r in records if r.get("restored")]
        gaps = [float(r["gap"]) for r in restored if r.get("gap") is not None]
        robust_blocks[robust] = {
            "zero_observed_unsafe": bool(k_unsafe == 0),
            "clopper_pearson": clopper_pearson_block(k_unsafe, net.n_near),
            "unsafe_records": sum(1 for r in records if is_unsafe(r)),
            "n_records": len(records),
            "degenerate_conditions": n_degenerate,
            "degenerate_branch_fires": bool(n_degenerate >= H3_DEGENERATE_COUNT),
            "restored": {
                "n": len(restored),
                "n_records": len(records),
                "gap_min": min(gaps) if gaps else None,
                "gap_median": _nan_to_none(_median(gaps)) if gaps else None,
                "gap_max": max(gaps) if gaps else None,
                "gap_flagged_over_1pct": sum(1 for r in restored if r.get("gap_flag")),
            },
        }

    qualifying = [r for r in ROBUST_METHODS if robust_blocks[r]["zero_observed_unsafe"]]
    pairs = {
        robust: {simple: _pair_block(net, robust, simple, regime) for simple in SIMPLE_POLICIES}
        for robust in ROBUST_METHODS
    }

    def best_simple(robust: str) -> tuple[str | None, dict | None]:
        candidates = [
            (simple, block)
            for simple, block in pairs[robust].items()
            if block["evaluable"] and block["median_utilisation"][simple] is not None
        ]
        if not candidates:
            return None, None
        simple, block = max(candidates, key=lambda item: item[1]["median_utilisation"][item[0]])
        return simple, block

    selections = {}
    for robust in ROBUST_METHODS:
        simple, block = best_simple(robust)
        selections[robust] = {
            "best_simple_policy": simple,
            "rule": (
                "the policy among B2m, B2p and B0 with the highest median utilisation over its "
                "joint set with the robust method"
            ),
            "pair": block,
            "not_evaluable_pairs": {
                name: candidate.get("reason")
                for name, candidate in pairs[robust].items()
                if not candidate["evaluable"]
            },
        }

    better = None
    if len(qualifying) == 1:
        better = qualifying[0]
    elif len(qualifying) > 1:
        scored = [
            (robust, selections[robust]["pair"]["median_difference"])
            for robust in qualifying
            if selections[robust]["pair"] is not None
            and selections[robust]["pair"]["median_difference"] is not None
        ]
        if scored:
            better = max(scored, key=lambda item: item[1])[0]
        else:
            better = qualifying[0]

    simple_safety = {}
    for simple in SIMPLE_POLICIES:
        simple_regime = NO_REGIME if simple == "B0" else regime
        records = pick(net.records, simple, simple_regime, "near")
        simple_safety[simple] = {
            "near_unsafe_rate": float(np.nanmean(condition_rates(records, rows))),
            "unsafe_conditions": unsafe_conditions(records, rows),
            "n_conditions": net.n_near,
        }

    cert = _cert_block(net, regime)
    bracket = _b4_bracket(net, regime)
    control_f = _control_f_block(net)

    return {
        "network": net.name,
        "label": net.label,
        "regime": regime,
        "n_conditions": net.n_near,
        "robust_methods": robust_blocks,
        "qualifying_robust_methods": qualifying,
        "better_robust_method": better,
        "better_robust_method_rule": (
            "the robust method with zero observed unsafe envelopes; if both qualify, the one "
            "with the larger median utilisation difference against its best simple policy"
        ),
        "pairs": pairs,
        "selected": selections,
        "simple_policy_safety": simple_safety,
        "cert_against_rand": cert,
        "b4_utilisation_bracket": bracket,
        "control_f_b3": control_f,
    }


def h3_verdict(block: dict, holm: dict) -> dict:
    better = block["better_robust_method"]
    if better is None:
        zero_unsafe = False
        pair = None
    else:
        zero_unsafe = bool(block["robust_methods"][better]["zero_observed_unsafe"])
        pair = block["selected"][better]["pair"]

    if pair is None or not pair["evaluable"]:
        requirements = {
            "zero_observed_unsafe": zero_unsafe,
            "joint_pairing_evaluable": False,
            "median_difference_at_least_0.10": None,
            "lower_bound_positive_after_holm": None,
            "sign_agreement": None,
        }
        supported = False
    else:
        margin = pair["median_difference"]
        requirements = {
            "zero_observed_unsafe": zero_unsafe,
            "joint_pairing_evaluable": True,
            "median_difference_at_least_0.10": bool(
                margin is not None and margin >= H3_UTILISATION_MARGIN
            ),
            "lower_bound_positive_after_holm": bool(
                holm["rejected"] and (pair["paired_bootstrap"].get("mean") or 0.0) > 0
            ),
            "sign_agreement": bool(pair["sign_agreement"]),
        }
        supported = bool(
            zero_unsafe
            and requirements["median_difference_at_least_0.10"]
            and requirements["lower_bound_positive_after_holm"]
            and requirements["sign_agreement"]
        )

    branches: dict[str, object] = {}
    robust_reference = (
        block["selected"][better]["pair"]["companion_all_conditions"]["median_utilisation"][better]
        if better is not None and block["selected"][better]["pair"] is not None
        else None
    )
    branch_detail = {}
    for simple in SIMPLE_POLICIES:
        if better is None:
            branches[f"simple_suffices_{simple}"] = None
            continue
        pair_block = block["pairs"][better][simple]
        companion = pair_block["companion_all_conditions"]["median_utilisation"][simple]
        # "at least as safe" is counted in conditions, s. 9's unit for a safety claim.
        simple_unsafe = block["simple_policy_safety"][simple]["unsafe_conditions"]
        robust_unsafe = block["robust_methods"][better]["clopper_pearson"]["k"]
        at_least_as_safe = bool(simple_unsafe <= robust_unsafe)
        within = (
            None
            if companion is None or robust_reference is None
            else bool(companion >= robust_reference - H3_REJECT_MARGIN)
        )
        branches[f"simple_suffices_{simple}"] = bool(at_least_as_safe and within)
        branch_detail[simple] = {
            "unsafe_conditions_simple": simple_unsafe,
            "unsafe_conditions_robust": robust_unsafe,
            "at_least_as_safe": at_least_as_safe,
            "companion_median_utilisation_simple": companion,
            "companion_median_utilisation_robust": robust_reference,
            "within_0.05_of_robust": within,
        }
    branches["robust_degenerate_on_at_least_5_of_10"] = (
        None if better is None else bool(block["robust_methods"][better]["degenerate_branch_fires"])
    )

    rejected = any(value is True for value in branches.values())
    if supported:
        verdict = "Supported"
    elif pair is not None and pair["evaluable"] and requirements["sign_agreement"] is False:
        verdict = "Inconclusive"
    elif rejected:
        verdict = "Rejected"
    elif pair is None or not pair["evaluable"]:
        verdict = NOT_EVALUABLE
    else:
        verdict = "Inconclusive"
    return {
        "verdict": verdict,
        "support_requirements": requirements,
        "rejection_branches": branches,
        "rejection_branches_fired": [k for k, v in branches.items() if v is True],
        "rejection_branch_detail": branch_detail,
        "holm": holm,
        "limitation": (
            "B4's point utilisation is a lower bound: every B4 envelope is `restored`, so its "
            "true optimum lies inside the reported bracket, whose upper end is not AC-scored"
        ),
    }


def _cert_block(net: Network, regime: str) -> dict:
    policies = [p for p in net.payloads["ambiguity"]["policies"] if p["regime"] == regime]
    if not policies:
        return {"status": NOT_EVALUABLE, "reason": f"no policy record for {regime}"}
    policy = policies[0]
    k, n = int(policy["k"]), int(policy["n"])
    evaluable = k not in (0, n)
    return {
        "regime": regime,
        "replicate": int(policy["replicate"]),
        "fallback_count_k": k,
        "n": n,
        "fallback_rate": float(policy["fallback_rate"]),
        "cert_unsafe": int(policy["cert_unsafe"]),
        "rand_unsafe": int(policy["rand_unsafe"]),
        "always_unsafe": int(policy["always_unsafe"]),
        "b2_unsafe": int(policy["b2_unsafe"]),
        "evaluable": evaluable,
        "verdict": (
            "credited"
            if evaluable and policy["cert_unsafe"] < policy["rand_unsafe"]
            else ("not credited" if evaluable else NOT_EVALUABLE)
        ),
        "reason": None
        if evaluable
        else (
            f"the realised fallback rate gives k = {k} of n = {n}; RAND is then identical to "
            "CERT (s. 7)"
        ),
        "artefact_verdict": policy["verdict"],
        "protocol_note": (
            "s. 7 runs the reliability-aware rule only if H1 is not rejected; the artefact ran "
            "it regardless, and its read-out is reported as descriptive"
        ),
    }


def _b4_bracket(net: Network, regime: str) -> dict:
    """[restored Sum(e), cut-LP upper bound Sum(e)/(1 - gap)] / Sum(e_B5), per condition."""
    rows = net.near_rows
    records = pick(net.records, "B4", regime, "near")
    grouped = by_row(records, rows)
    per_condition = []
    for row in rows:
        lows, highs = [], []
        for record in grouped[row]:
            if is_unsafe(record) or is_degenerate(record):
                continue
            total = float(record["total_e"])
            gap = record.get("gap")
            denominator = net.oracle_total[row]
            lows.append(total / denominator)
            highs.append(
                total / (1.0 - float(gap)) / denominator if gap is not None else total / denominator
            )
        per_condition.append(
            {
                "row": row,
                "lower": _nan_to_none(float(np.mean(lows))) if lows else None,
                "upper": _nan_to_none(float(np.mean(highs))) if highs else None,
            }
        )
    lowers = [c["lower"] for c in per_condition if c["lower"] is not None]
    uppers = [c["upper"] for c in per_condition if c["upper"] is not None]
    return {
        "regime": regime,
        "definition": (
            "[restored Sum(e), cut-LP upper bound Sum(e)/(1 - gap)] / Sum(e_B5), averaged over "
            "replicates per condition"
        ),
        "per_condition": per_condition,
        "median_lower": _nan_to_none(_median(lowers)) if lowers else None,
        "median_upper": _nan_to_none(_median(uppers)) if uppers else None,
        "upper_end_ac_scored": False,
        "note": "the bracket's upper end is an LP bound and carries no AC safety claim",
    }


def _control_f_block(net: Network) -> dict:
    """Control F: B3's unsafe counts and utilisation in every regime ('B3 suffices')."""
    rows = net.near_rows
    out = {}
    for regime in REGIMES:
        near = pick(net.records, "B3", regime, "near")
        far = pick(net.records, "B3", regime, "far")
        if not near and not far:
            continue
        utilisation = condition_utilisation(near, rows, net.oracle_total, False)
        out[regime] = {
            "near_unsafe_conditions": unsafe_conditions(near, rows),
            "near_unsafe_records": sum(1 for r in near if is_unsafe(r)),
            "near_n_records": len(near),
            "far_unsafe_records": sum(1 for r in far if is_unsafe(r)),
            "far_n_records": len(far),
            "median_utilisation": _nan_to_none(_median(utilisation)),
            "clopper_pearson_near": clopper_pearson_block(
                unsafe_conditions(near, rows), net.n_near
            ),
        }
    return {
        "read_out": "the established structured method's safety and utilisation (s. 10 F)",
        "per_regime": out,
    }


# --- F. H4 (s. 8, s. 9) ------------------------------------------------------------------


def _h4_family(net: Network, family: str, regime: str, objective: str) -> dict:
    measures = [
        m
        for m in net.payloads["ambiguity"]["measures"]
        if m["family"] == family and m["regime"] == regime
    ]
    spreads = [float(m[objective]["export_spread"]) for m in measures]
    disagreements = [m[objective]["safety_disagreement"] for m in measures]
    measured = [bool(d) for d in disagreements if d is not None]
    allocation = [float(m[objective]["allocation_spread"]) for m in measures]
    block = {
        "family": family,
        "regime": regime,
        "objective": objective,
        "n_conditions": len(measures),
        "median_export_spread": _nan_to_none(_median(spreads)),
        "max_export_spread": max(spreads) if spreads else None,
        "median_allocation_spread": _nan_to_none(_median(allocation)),
        "safety_disagreement_rate": (float(np.mean(measured)) if measured else None),
        "safety_disagreement_measured": len(measured),
    }
    return block


def _classify_h4(block: dict) -> dict:
    spread = block["median_export_spread"]
    disagreement = block["safety_disagreement_rate"]
    if spread is None:
        return {"classification": NOT_EVALUABLE, "reason": "no measure"}
    material = spread >= H4_MATERIAL_SPREAD or (
        disagreement is not None and disagreement >= H4_MATERIAL_DISAGREEMENT
    )
    if disagreement is None:
        # The proportional-fair envelopes are not AC-scored (s. 8), so only the spread rows of
        # s. 9's table can be read; the label says so rather than defaulting to Mixed.
        classification = (
            "Material ambiguity (spread only)"
            if material
            else (
                "Decision equivalence (spread only)"
                if spread < H4_EQUIVALENCE_SPREAD
                else "Mixed (spread only)"
            )
        )
    else:
        equivalence = spread < H4_EQUIVALENCE_SPREAD and disagreement == 0.0
        classification = (
            "Material ambiguity"
            if material
            else ("Decision equivalence" if equivalence else "Mixed")
        )
    return {
        "classification": classification,
        "tests": {
            "median_spread_at_least_0.10": bool(spread >= H4_MATERIAL_SPREAD),
            "disagreement_at_least_0.30": None
            if disagreement is None
            else bool(disagreement >= H4_MATERIAL_DISAGREEMENT),
            "median_spread_below_0.05": bool(spread < H4_EQUIVALENCE_SPREAD),
            "disagreement_zero": None if disagreement is None else bool(disagreement == 0.0),
        },
    }


def h4_network(net: Network) -> dict:
    primary_p1 = _h4_family(net, "random", "P1", "primary")
    out = {
        "network": net.name,
        "label": net.label,
        "registered": {**primary_p1, **_classify_h4(primary_p1)},
        "secondary": {},
        "extremes_upper_bound": {},
    }
    for regime in ("P1", "P3"):
        block = _h4_family(net, "random", regime, "primary")
        out["secondary"][f"random_{regime}_primary"] = {**block, **_classify_h4(block)}
        fair = _h4_family(net, "random", regime, "fair")
        fair["note"] = (
            "the proportional-fair envelopes are compared by Sum(e) and allocation only, "
            "without AC, so no safety disagreement is measured (s. 8)"
        )
        out["secondary"][f"random_{regime}_fair"] = {**fair, **_classify_h4(fair)}
        extreme = _h4_family(net, "extreme", regime, "primary")
        records = [
            r
            for r in net.payloads["ambiguity"]["records"]
            if r["family"] == "extreme" and r["regime"] == regime
        ]
        shrink = sorted({_nan_to_none(r.get("shrink_min")) for r in records})
        extreme["shrink_min_values"] = shrink
        extreme["collapsed"] = bool(shrink == [0.0])
        extreme["note"] = (
            "the extreme alternatives carry no verdict (s. 8); here every realised shrink "
            "factor is 0, so they collapse onto the centre fit and their spread is an upper "
            "bound of 0 rather than a measured disagreement"
        )
        extreme["unsafe_records"] = sum(1 for r in records if is_unsafe(r))
        extreme["n_records"] = len(records)
        out["extremes_upper_bound"][regime] = extreme
    return out


# --- G. the negative controls (s. 10, s. 15) --------------------------------------------


def _aprime_attribution(net: Network) -> dict:
    rows = net.near_rows
    aprime = pick(net.records, "Aprime", NO_REGIME, "near")
    method_a = pick(net.records, "A", NO_REGIME, "near")
    aprime_rates = condition_rates(aprime, rows)
    aprime_unsafe = unsafe_conditions(aprime, rows)
    per_method = {}
    for method in DATA_DRIVEN:
        per_regime = {}
        for regime in TRAINING_REGIMES:
            records = pick(net.records, method, regime, "near")
            rates = condition_rates(records, rows)
            excess = rates - aprime_rates
            per_regime[regime] = {
                "unsafe_conditions_method": unsafe_conditions(records, rows),
                "unsafe_conditions_aprime": aprime_unsafe,
                "expected_unsafe_count_method": float(np.nansum(rates)),
                "expected_unsafe_count_aprime": float(np.nansum(aprime_rates)),
                "excess_count_over_aprime": float(np.nansum(excess)),
                "paired_bootstrap": bootstrap_block(
                    excess, net.name, f"desc_aprime_{method}_{regime}"
                ),
            }
        per_method[method] = per_regime
    label = (
        "stop: linear modelling with a learned offset is inadequate for this decision"
        if aprime_unsafe > APRIME_STOP
        else (
            "linearisation-sensitive"
            if aprime_unsafe >= APRIME_SENSITIVE
            else "no s. 15 stop condition; the attribution rule applies as written"
        )
    )
    return {
        "rule": (
            "a data-driven method's unsafe outcomes are attributed to identification only in "
            "excess of A-prime's on the same conditions, paired (s. 10 A/A-prime)"
        ),
        "aprime": {
            "near_unsafe_conditions": aprime_unsafe,
            "near_unsafe_rate": float(np.nanmean(aprime_rates)),
            "far_unsafe_records": sum(
                1 for r in pick(net.records, "Aprime", NO_REGIME, "far") if is_unsafe(r)
            ),
            "clopper_pearson_near": clopper_pearson_block(aprime_unsafe, net.n_near),
        },
        "method_a": {
            "near_unsafe_conditions": unsafe_conditions(method_a, rows),
            "near_unsafe_rate": float(np.nanmean(condition_rates(method_a, rows))),
            "far_unsafe_records": sum(
                1 for r in pick(net.records, "A", NO_REGIME, "far") if is_unsafe(r)
            ),
            "clopper_pearson_near": clopper_pearson_block(
                unsafe_conditions(method_a, rows), net.n_near
            ),
            "note": "A carries a condition-exact AC offset that no deployable method has",
        },
        "s15_stop_label": label,
        "s15_thresholds": {
            "stop_above": APRIME_STOP,
            "linearisation_sensitive_from": APRIME_SENSITIVE,
            "of_n_near": net.n_near,
        },
        "per_method": per_method,
    }


def _control_t_block(net: Network) -> dict:
    controls = net.payloads["controls"]
    rows = net.near_rows
    full, primary, thermal = {}, {}, {}
    for regime in ("P1", "P3"):
        records = pick(controls["records"], method="T", regime=regime, kind="near")
        full[regime] = float(np.nanmean(condition_rates(records, rows))) if records else None
        thermal[regime] = sum(
            1
            for r in records
            if max(float(r["line_loading"]), float(r["trafo_loading"])) > THERMAL_UNSAFE_PERCENT
        )
        primary_records = pick(net.records, "B2", regime, "near")
        primary[regime] = float(np.nanmean(condition_rates(primary_records, rows)))
    meta = controls["control_t"]
    p95 = float(meta["approximation_error_p95"])
    return {
        "definition": "control T: B2 under the full decision (V) and (T), kappa = 0.95",
        "full_decision_near_unsafe_rate": full,
        "primary_decision_near_unsafe_rate": primary,
        "p1_minus_p3_full": None if None in full.values() else full["P1"] - full["P3"],
        "p1_minus_p3_primary": primary["P1"] - primary["P3"],
        "thermal_unsafe_records": thermal,
        "approximation_error_p95": p95,
        "approximation_error_max": float(meta["approximation_error_max"]),
        "approximation_limited": bool(meta["approximation_limited"]),
        "approximation_label": (
            "approximation-limited"
            if p95 > CONTROL_T_APPROXIMATION_LIMIT
            else "within the 5 % limit"
        ),
        "kappa": float(meta["kappa"]),
        "n_branch_samples": int(meta["n_branch_samples"]),
        "f0_expectation": (
            "the board's written HYPOTHESIS was that the full decision would mask most of any "
            "voltage-component effect; the measured difference is stated whichever way it falls"
        ),
    }


def controls_block(net: Network) -> dict:
    rows, far = net.near_rows, net.far_rows
    far_unsafe = {}
    for method in DATA_DRIVEN:
        far_unsafe[method] = {
            regime: sum(1 for r in pick(net.records, method, regime, "far") if is_unsafe(r))
            for regime in REGIMES
        }
    for method in REFERENCES:
        far_unsafe[method] = {
            NO_REGIME: sum(1 for r in pick(net.records, method, NO_REGIME, "far") if is_unsafe(r))
        }

    l0 = {}
    for method in DATA_DRIVEN:
        l0_records = pick(net.records, method, "L0", "near")
        p1_records = pick(net.records, method, "P1", "near")
        l0[method] = {
            "l0_near_unsafe_conditions": unsafe_conditions(l0_records, rows),
            "l0_near_unsafe_rate": float(np.nanmean(condition_rates(l0_records, rows))),
            "p1_near_unsafe_rate": float(np.nanmean(condition_rates(p1_records, rows))),
            "l0_replicates": sorted({int(r["replicate"]) for r in l0_records}),
            "l0_median_utilisation": _nan_to_none(
                _median(condition_utilisation(l0_records, rows, net.oracle_total, False))
            ),
            "l0_statuses": sorted({str(r["status"]) for r in l0_records}),
        }

    shuffled = []
    for fit in net.envelopes["fits"]:
        shuffled.append(
            {
                "regime": fit["regime"],
                "replicate": int(fit["replicate"]),
                "shuffled_test_mae_pu": float(fit["control_k"]["test_mae"]),
                "b2_test_mae_pu": float(fit["test_mae"]["ridge"]),
                "ratio": float(fit["control_k"]["test_mae"]) / float(fit["test_mae"]["ridge"]),
                "slope_norm_ratio": float(fit["control_k"]["slope_norm_ratio"]),
            }
        )

    stage2 = {}
    for method in DATA_DRIVEN:
        records = [r for r in net.records if r.get("method") == method]
        moved = sum(1 for r in records if float(r.get("stage2_l1_move", 0.0)) > STAGE2_MOVE_LIMIT)
        stage2[method] = {
            "moved_over_1pct": moved,
            "n_records": len(records),
            "share": moved / len(records) if records else None,
        }

    zero_vertex = net.payloads["selection"]["zero_vertex"]
    zero_e_records = {}
    for method in DATA_DRIVEN:
        hits = [
            {
                "regime": r["regime"],
                "kind": r["kind"],
                "row": int(r["row"]),
                "replicate": int(r["replicate"]),
                "status": r["status"],
            }
            for r in net.records
            if r.get("method") == method and float(r["total_e"]) == 0.0
        ]
        if hits:
            zero_e_records[method] = {"n": len(hits), "records": hits}

    oracle = net.payloads["oracle"]
    monotonicity = net.payloads["monotonicity"]
    return {
        "control_a_aprime_attribution": _aprime_attribution(net),
        "control_c_matched_marginals": {
            "passed": bool(net.payloads["marginals"]["control_c"]["passed"]),
            "per_regime": {
                regime: {
                    "mean_within_1pct": bool(entry["mean_within_1pct"]),
                    "median_p95_within_10pct": bool(entry["median_p95_within_10pct"]),
                    "max_abs_mean_ratio_deviation": max(
                        abs(value - 1.0) for value in entry["mean_ratio"]
                    ),
                    "median_p95_ratio": _median(entry["p95_ratio"]),
                    "max_ks": max(entry["ks"]),
                }
                for regime, entry in net.payloads["marginals"]["control_c"]["against_P1"].items()
            },
        },
        "control_d_far_set_unsafe": {
            "expectation": "every method is voltage-safe on the far set; any unsafe outcome is "
            "a methodology fault",
            "per_method": far_unsafe,
            "total_unsafe": sum(sum(v.values()) for v in far_unsafe.values()),
            "n_far_conditions": len(far),
        },
        "control_f_structure": _control_f_block(net),
        "control_h_sample_size": _control_h_block(net)
        if net.evaluable
        else {
            "status": NOT_EVALUABLE,
            "reason": "the T = 768 arm is rural3 only (s. 10)",
        },
        "control_i_measurement_noise": _control_i_block(net),
        "control_k_shuffled_training": {
            "expectation": "a shuffled model predicting as well as B2 would mean leakage or a "
            "degenerate target",
            "per_fit": shuffled,
            "min_ratio": min(entry["ratio"] for entry in shuffled),
        },
        "control_l0_load_excitation": {
            "expectation": "P1 safe because of load excitation would show as L0 unsafe while "
            "P1 is safe",
            "per_method": l0,
        },
        "control_t_full_decision": _control_t_block(net),
        "b5_binding_diagnostic": {
            "n_voltage_binding": int(oracle["n_voltage_binding"]),
            "n_near": int(oracle["n_near"]),
            "binding_share": float(oracle["binding_share"]),
            "threshold": BINDING_MIN,
            "passes": bool(int(oracle["n_voltage_binding"]) >= BINDING_MIN),
            "note": (
                f"s. 9 and s. 15: fewer than {BINDING_MIN} of 10 would make H1-H3 NOT "
                "EVALUABLE on this network"
            ),
        },
        "monotonicity": {
            "stop_condition_triggered": bool(monotonicity["stop_condition_triggered"]),
            "flagged_rows": list(monotonicity["flagged_rows"]),
            "n_conditions": int(monotonicity["n_conditions"]),
            "n_failures_flagged": int(monotonicity["n_failures_flagged"]),
            "verdict": monotonicity["verdict"],
        },
        "failure_shares": {
            key: {
                "failures": int(payload["failures"]),
                "failure_share": float(payload["failure_share"]),
                "limit": 0.02,
                "evaluable": bool(payload.get("evaluable", True)),
            }
            for key, payload in net.payloads.items()
            if "failure_share" in payload and "failures" in payload
        },
        "zero_vertex_method_independent": {
            "n_conditions": len(zero_vertex),
            "unsafe_voltage": sum(1 for z in zero_vertex if z["unsafe_voltage"]),
            "unsafe_thermal": sum(1 for z in zero_vertex if z["unsafe_thermal"]),
            "excluded_conditions": [
                int(index)
                for index, z in enumerate(zero_vertex)
                if z["unsafe_voltage"] or z["unsafe_thermal"]
            ],
            "min_vm_margin_pu": min(float(z["min_vm_margin_pu"]) for z in zero_vertex),
        },
        "zero_export_envelopes": {
            "definition": "records whose decision returned Sum(e) = 0",
            "per_method": zero_e_records,
        },
        "stage2_move_shares": {
            "definition": "the share of records whose stage-2 L1 move exceeds 1 % (s. 6)",
            "per_method": stage2,
        },
        "b4box_ols_secondary_arm": {
            "near_unsafe_records": {
                regime: sum(
                    1
                    for r in pick(
                        net.payloads["controls"]["records"],
                        method="B4boxOLS",
                        regime=regime,
                        kind="near",
                    )
                    if is_unsafe(r)
                )
                for regime in ("P1", "P3")
            },
            "conditioning": net.payloads["controls"]["b4box_ols"],
        },
    }


# --- H. the excitation table (s. 4, s. 10 C) ---------------------------------------------


def excitation_block(net: Network) -> dict:
    rows = net.near_rows
    per_regime = {}
    for regime in REGIMES:
        payload = net.payloads[f"physics_{regime}"]
        excitation = payload["excitation"]
        condition = float(excitation["condition_number"])
        rank_deficient = condition >= FLOAT_MAX_CONDITION
        per_regime[regime] = {
            "pv_correlation_mean": float(excitation["pv_corr_mean"]),
            "pv_correlation_min": float(excitation["pv_corr_min"]),
            "effective_rank": float(excitation["effective_rank"]),
            "condition_number": None if rank_deficient else condition,
            "condition_number_reported": (
                "inf (rank-deficient)" if rank_deficient else f"{condition:.6g}"
            ),
            "independent_variance_median": _median(excitation["independent_variance"]),
            "independent_variance_min": float(np.min(excitation["independent_variance"])),
            "n_singular_values": len(excitation["singular_values"]),
            "daylight_train_steps": int(payload["daylight_train_steps"]),
            "train_steps": int(payload["train_steps"]),
        }
    corner = {}
    for regime in TRAINING_REGIMES:
        residuals, mahalanobis = [], []
        for fit in net.envelopes["fits"]:
            if fit["regime"] != regime:
                continue
            for entry in fit["corner_distance"]:
                residuals.append(float(entry["residual_norm"]))
                mahalanobis.append(float(entry["mahalanobis"]))
        corner[regime] = {
            "median_residual_norm": _nan_to_none(_median(residuals)),
            "median_mahalanobis": _nan_to_none(_median(mahalanobis)),
            "n_entries": len(residuals),
        }
    return {
        "per_regime": per_regime,
        "corner_distance": {
            "definition": "the deployment corner's distance from the training design (s. 4)",
            "per_regime": corner,
        },
        "n_near_conditions": len(rows),
        "note": (
            "L0's condition number is stored as the float maximum "
            f"({FLOAT_MAX_CONDITION:.6g}); it is reported as 'inf (rank-deficient)'"
        ),
    }


# --- I. the ledger (s. 12) ---------------------------------------------------------------


def ledger_block() -> dict:
    """106 plus the `solves` of every `results/*.json`, abort records included."""
    ledger = ec.SolveLedger(start=LEDGER_START, ceiling=LEDGER_CEILING)
    lines = []
    for path in sorted(RESULTS.glob("*.json")):
        if path.name == SUMMARY_PATH.name:
            continue
        payload = json.loads(path.read_text())
        if "solves" not in payload:
            continue
        ledger.charge(path.stem, int(payload["solves"]))
        lines.append(
            {
                "artefact": path.stem,
                "stage": payload.get("stage"),
                "network": payload.get("network"),
                "regime": payload.get("regime"),
                "solves": int(payload["solves"]),
                "label": payload.get("label"),
            }
        )
    per_stage: dict[str, int] = {}
    per_network: dict[str, int] = {}
    for line in lines:
        per_stage[str(line["stage"])] = per_stage.get(str(line["stage"]), 0) + line["solves"]
        per_network[str(line["network"])] = (
            per_network.get(str(line["network"]), 0) + line["solves"]
        )
    double_charged = [
        line["artefact"]
        for line in lines
        if line["artefact"] in ("abort_physics_rural3_L0_sigterm", "physics_rural3_L0")
    ]
    return {
        "rule": (
            "106 board design-audit solves plus the `solves` field of every results/*.json, "
            "abort records included; marginals carry 0 solves of their own"
        ),
        "start": LEDGER_START,
        "ceiling": LEDGER_CEILING,
        "planned_total": PLANNED_TOTAL,
        "lines": lines,
        "per_stage": per_stage,
        "per_network": per_network,
        "total": int(ledger.total),
        "remaining": int(ledger.remaining()),
        "double_charged_L0": {
            "artefacts": double_charged,
            "note": (
                "A3: rural3's L0 is charged twice. The SIGTERM upper bound of 480 was charged "
                "by the board because no abort record was written, and the resumed run solved "
                "L0 again from the start (480). About 240 of the first 480 had probably run."
            ),
        },
        "marginals_stage_solves_note": (
            "marginals_*.json carry `stage_solves`, the attempt count of the physics process "
            "that produced them (rural3 480 after A3's L0-only resume, semiurb5 1,920 for four "
            "regimes in one process). Those solves are already charged through the physics "
            "artefacts and are not a ledger line of their own."
        ),
    }


# --- J. provenance (s. 12, s. 16) --------------------------------------------------------


def provenance_block(networks: dict[str, Network]) -> dict:
    inputs = {}
    for net in networks.values():
        for path in net.paths.values():
            inputs[str(path.relative_to(HERE))] = ec.sha256_of(path)
    code = {name: ec.sha256_of(HERE / name) for name in FROZEN_CODE}
    code["analyse.py"] = ec.sha256_of(HERE / "analyse.py")
    code["svgplot.py"] = ec.sha256_of(HERE / "svgplot.py")
    versions = {}
    for package in ("numpy", "scipy", "pandapower", "simbench"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    artefact_protocol_hashes: dict[str, list[str]] = {}
    for net in networks.values():
        for key, payload in net.payloads.items():
            digest = payload.get("protocol_sha256")
            if digest:
                artefact_protocol_hashes.setdefault(digest, []).append(f"{net.name}/{key}")
    return {
        "inputs_sha256": dict(sorted(inputs.items())),
        "frozen_code_sha256": {name: code[name] for name in FROZEN_CODE},
        "analysis_code_sha256": {
            "analyse.py": code["analyse.py"],
            "svgplot.py": code["svgplot.py"],
        },
        "protocol": {
            "path": PROTOCOL_RELATIVE,
            "sha256": ec.sha256_of(ec.PROTOCOL),
            "sha256_expected": ec.PROTOCOL_SHA256,
            "as_executed_sha256": ec.executed_text_sha(ec.PROTOCOL),
            "as_executed_expected": ec.PROTOCOL_SHA256_EXECUTED,
        },
        "artefact_protocol_sha256": {
            digest: sorted(keys) for digest, keys in sorted(artefact_protocol_hashes.items())
        },
        "artefact_protocol_sha256_interpretation": {
            ec.PROTOCOL_SHA256: (
                "the registered file as it stands now: revision 2.2 plus the dated amendments A1-A3"
            ),
            ec.PROTOCOL_SHA256_EXECUTED: (
                "the as-executed text, i.e. revision 2.2 with the amendments section replaced "
                "by '(none)'; the artefacts carrying it ran before A1 was written"
            ),
            "7fa20b54c4b63761c5be0a5182a6f58b4dbb2961b8ec30b4f49e0950fab26202": (
                "revision 2.2 plus amendments A1-A2, i.e. the registered file before A3 was "
                "added; rural3's P1-P3 physics ran under it"
            ),
            "note": (
                "each stage records the hash of the protocol file at the moment it ran. The "
                "amendments are dated board decisions appended after a stage, so the file hash "
                "advances while the as-executed text above the amendments does not. "
                "`ec.check_protocol()` verifies both before this analysis reads anything."
            ),
        },
        "versions": versions,
        "versions_source": (
            "importlib.metadata of the installed distributions; pandapower is not imported by "
            "this module"
        ),
        "status": ec.STATUS,
    }


PROTOCOL_RELATIVE = "analysis/export_envelope_shift/stage_a_protocol.md"


# --- K. the Holm family (s. 9) -----------------------------------------------------------


def holm_family(h1: dict[str, dict], h3: dict[str, dict]) -> dict:
    entries = []
    for test, network in HOLM_FAMILY:
        if test == "H1":
            block = h1[network]
            raw = block["p1_minus_p3"].get("p")
            source = "H1's P1 - P3 paired voltage-unsafe-rate difference"
        else:
            block = h3[network]
            better = block["better_robust_method"]
            pair = block["selected"].get(better, {}).get("pair") if better else None
            raw = pair["paired_bootstrap"].get("p") if pair and pair["evaluable"] else None
            source = "H3's paired utilisation difference (better robust minus best simple)"
        evaluable = network == EVALUATION_NETWORK and raw is not None
        entries.append(
            {
                "test": test,
                "network": network,
                "source": source,
                "raw_p": None if raw is None else float(raw),
                "p_used": float(raw) if evaluable else 1.0,
                "evaluable": bool(evaluable),
                "reason": None
                if evaluable
                else (
                    "NOT EVALUABLE (A2: semiurb5 kept 2 of 40 near candidates); enters the "
                    "family at p = 1, conservatively, with the family size held at 4"
                    if network != EVALUATION_NETWORK
                    else "no paired statistic is defined; enters at p = 1"
                ),
            }
        )
    rejected, adjusted = ec.holm(np.array([entry["p_used"] for entry in entries]), alpha=ALPHA)
    for entry, flag, value in zip(entries, rejected, adjusted, strict=False):
        entry["adjusted_p"] = float(value)
        entry["rejected_at_0.05"] = bool(flag)
    return {
        "alpha": ALPHA,
        "family_size": len(entries),
        "rule": (
            "Holm step-down over exactly the 4 tests fixed in s. 9; nothing else enters, and "
            "every other interval in this summary is descriptive"
        ),
        "tests": entries,
    }


def _holm_for(family: dict, test: str, network: str) -> dict:
    for entry in family["tests"]:
        if entry["test"] == test and entry["network"] == network:
            return {
                "raw_p": entry["raw_p"],
                "p_used": entry["p_used"],
                "adjusted_p": entry["adjusted_p"],
                "rejected": entry["rejected_at_0.05"],
                "evaluable": entry["evaluable"],
            }
    raise KeyError(f"{test}/{network} is not in the Holm family")


# --- L. the whole summary ----------------------------------------------------------------


@dataclass
class Study:
    networks: dict[str, Network]
    summary: dict


def build_summary() -> Study:
    networks = {name: load_network(name) for name in NETWORKS}
    h1_blocks = {name: h1_network(net) for name, net in networks.items()}
    h2_blocks = {name: h2_network(net) for name, net in networks.items()}
    h3_blocks = {name: h3_network(net) for name, net in networks.items()}
    h4_blocks = {name: h4_network(net) for name, net in networks.items()}
    family = holm_family(h1_blocks, h3_blocks)

    for name, block in h1_blocks.items():
        verdict = h1_verdict(block, _holm_for(family, "H1", name))
        if name == EVALUATION_NETWORK:
            block["single_network_verdict"] = verdict
        else:
            block["single_network_verdict"] = {
                "verdict": NOT_EVALUABLE,
                "reason": "A2: 2 of 40 near candidates; H1-H3 are NOT EVALUABLE on semiurb5",
                "descriptive_mechanics": verdict,
            }
        block["formal_two_network"] = "Supported not attainable (A2)"

    for name, block in h2_blocks.items():
        verdict = h2_verdict(block)
        if name == EVALUATION_NETWORK:
            block["single_network_verdict"] = verdict
        else:
            block["single_network_verdict"] = {
                "verdict": NOT_EVALUABLE,
                "reason": "A2: 2 of 40 near candidates; H1-H3 are NOT EVALUABLE on semiurb5",
                "descriptive_mechanics": verdict,
            }
        block["formal_two_network"] = "Supported not attainable (A2)"

    for name, block in h3_blocks.items():
        verdict = h3_verdict(block, _holm_for(family, "H3", name))
        if name == EVALUATION_NETWORK:
            block["single_network_verdict"] = verdict
        else:
            block["single_network_verdict"] = {
                "verdict": NOT_EVALUABLE,
                "reason": "A2: 2 of 40 near candidates; H1-H3 are NOT EVALUABLE on semiurb5",
                "descriptive_mechanics": verdict,
            }
        block["formal_two_network"] = "Supported not attainable (A2)"

    for name, block in h4_blocks.items():
        if name != EVALUATION_NETWORK:
            block["registered"]["label"] = A2_LABEL
        block["formal_two_network"] = "Material/Equivalence on both networks not attainable (A2)"

    networks[EVALUATION_NETWORK]
    summary = {
        "stage": "analysis",
        "status": ec.STATUS,
        "amendment_a2": {
            "statement": (
                "semiurb5 kept only 2 of 40 near candidates (day 172 +0.00418 pu, day 182 "
                "+0.00409 pu), so s. 15 makes H1-H3 NOT EVALUABLE there. Verdicts are "
                "single-network results on rural3; nothing that requires 'both networks' can "
                "be Supported."
            ),
            "evaluation_network": EVALUATION_NETWORK,
            "descriptive_network": "semiurb5",
            "formal_two_network": "Supported not attainable (A2)",
        },
        "conventions": {
            "unsafe": "s. 12: a failed power flow counts as unsafe, never as safe",
            "per_condition_rate": (
                "u_i(method, regime) is the mean over replicates r in {0, 1} of unsafe(r, i)"
            ),
            "zero_observed_unsafe": "no unsafe record in either replicate at any condition",
            "utilisation": (
                "U_i = Sum(e)/Sum(e_B5(i)) from the oracle's best_e total, averaged over "
                "replicates; defined only for voltage-safe records"
            ),
            "clopper_pearson_n": "the number of conditions, because replicates are nested (s. 9)",
            "bootstrap": "2,000 percentile resamples over conditions, paired for differences",
            "bootstrap_seed": 'ec.rng_for(network, test_name, "bootstrap", 0)',
            "primary_cell": "sigma_v = 0.002, T = 384, near set, primary decision",
        },
        "networks": {
            name: {
                "code": net.envelopes["code"],
                "role": "evaluation" if net.evaluable else "descriptive development pilot (A2)",
                "label": net.label,
                "n_near": net.n_near,
                "n_far": len(net.far_rows),
                "near_evaluable": bool(net.envelopes["near_evaluable"]),
                "near_survivors": int(net.payloads["selection"]["n_near_survivors"]),
                "far_candidates": int(net.payloads["selection"]["n_far_candidates"]),
                "skipped_far_days_a1": list(net.payloads["selection"]["skipped_far_days"]),
                "sigma_v": float(net.envelopes["sigma_v"]),
            }
            for name, net in networks.items()
        },
        "holm_family": family,
        "h1_correlation_dependent_reliability": h1_blocks,
        "h2_prediction_against_decision": h2_blocks,
        "h3_information_aware_and_robust": h3_blocks,
        "h4_decision_relevance_of_non_identifiability": h4_blocks,
        "controls": {name: controls_block(net) for name, net in networks.items()},
        "excitation": {name: excitation_block(net) for name, net in networks.items()},
        "ledger": ledger_block(),
        "provenance": provenance_block(networks),
        "board_read_outs": {
            "b4_utilisation_bracket": {
                name: h3_blocks[name]["b4_utilisation_bracket"] for name in networks
            },
            "per_method_p1_minus_p3": {
                name: h1_blocks[name]["per_method_p1_minus_p3_descriptive"] for name in networks
            },
            "control_i_sigma_arms": {name: h1_blocks[name]["control_i"] for name in networks},
            "control_f_b3_suffices": {name: h3_blocks[name]["control_f_b3"] for name in networks},
            "ledger_double_charge": ledger_block()["double_charged_L0"],
        },
        "attainable_rejection_branches_rural3": {
            "H1": [
                "interval_within_null_band (s. 9's 'on both networks' read as 'rural3')",
                "small_data_effect_T768 (rural3 only by construction)",
                "noise_only_effect_sigma_0.0005 (s. 9's 'on both networks' read as 'rural3')",
            ],
            "H3": [
                "simple_suffices_B2m / _B2p / _B0 (s. 9's 'on both networks' read as 'rural3')",
                "robust_degenerate_on_at_least_5_of_10 (same reading)",
            ],
            "note": (
                "Supported is unattainable on either hypothesis because s. 9 requires both "
                "networks; the rejection branches remain attainable under A2's single-network "
                "reading, which is what s. 15 provides"
            ),
        },
        "disagreements": [
            {
                "where": "brief vs artefacts",
                "item": "the oracle's total",
                "note": (
                    "the brief names the oracle's `best_e` total; the JSON artefact's field is "
                    "`total_e` and the npz array is `best_e`. Both were read and asserted "
                    "equal to 1e-9 relative per condition."
                ),
            },
            {
                "where": "brief vs protocol s. 9 (resolved)",
                "item": "figure B's Clopper-Pearson n",
                "note": (
                    "s. 9 fixes the Clopper-Pearson n at the number of conditions because "
                    "replicates are nested; the brief had asked figure B to draw n = conditions "
                    "x replicates. The board withdrew that instruction, so figure B now draws "
                    "s. 9's n with unsafe = an unsafe record in at least one replicate, the same "
                    "n as every interval in this summary. No disagreement remains."
                ),
            },
            {
                "where": "protocol s. 7 vs artefacts",
                "item": "the reliability-aware rule",
                "note": (
                    "s. 7 runs CERT only if H1 is not rejected. H1 is Rejected on rural3, and "
                    "the artefact had already run CERT; its read-out is reported as descriptive "
                    "and it is NOT EVALUABLE anyway at k = 0."
                ),
            },
        ],
        "judgement_calls": [
            "'both networks' in s. 9's verdict tables is read as 'rural3' under A2; every block "
            "also records formal_two_network.",
            "'lower bound > 0 after Holm' is implemented as the Holm-adjusted p <= 0.05 with a "
            "positive mean difference; the nominal 95 % percentile interval is reported beside "
            "it.",
            "s. 9's H3 sentence 'Separately, CERT is credited only if...' is treated as a "
            "separate credit read-out, not as a gate on the Supported row.",
            "H3's 'a simple policy is at least as safe' is counted in unsafe conditions, s. 9's "
            "unit for a safety claim, not in the per-record rate; both are reported.",
            "s. 9's sign-disagreement sentence ('the verdict is Inconclusive') is given "
            "precedence over the Rejected row when the joint and companion comparisons "
            "disagree. On rural3 they agree, so the precedence does not change any verdict.",
            "H4's thresholds are applied to the median export spread for both the Material and "
            "the Equivalence rows, because s. 9 names the median for the first and 'the export "
            "spread' for the second.",
            "control H's 'falls to within 0.10' is flagged on the absolute difference, with the "
            "signed difference reported beside it.",
            "a failed power flow is detected as `converged = false`; an infeasible LP that "
            "returns Sum(e) = 0 is a safe empty envelope, not a failed flow.",
        ],
    }
    return Study(networks=networks, summary=summary)


# --- M. the figures ----------------------------------------------------------------------


def _cp_bars(counts: list[tuple[int, int]]) -> tuple[list[float], list[float]]:
    lows, highs = [], []
    for k, n in counts:
        lo, hi = ec.clopper_pearson(int(k), int(n))
        lows.append(lo)
        highs.append(hi)
    return lows, highs


def figure_a(study: Study) -> tuple[str, svgplot.Figure]:
    floor = 1e-16
    panels = []
    for name, net in study.networks.items():
        series = []
        for index, regime in enumerate(REGIMES):
            excitation = net.payloads[f"physics_{regime}"]["excitation"]
            values = np.sort(np.asarray(excitation["singular_values"], dtype=float))[::-1]
            normalised = np.clip(values / values.max(), floor, None)
            series.append(
                svgplot.Series(
                    x=list(range(1, len(normalised) + 1)),
                    y=[float(v) for v in normalised],
                    label=f"{regime} (PV corr mean {excitation['pv_corr_mean']:.3f})",
                    kind="line",
                    colour=svgplot.PALETTE[index % len(svgplot.PALETTE)],
                )
            )
        panels.append(
            svgplot.Panel(
                series=series,
                title=f"{name} ({net.label})",
                xlabel="singular-value index (1 = largest, dimensionless)",
                ylabel="singular value / largest (dimensionless)",
                ylog=True,
                ylim=(floor / 2, 2.0),
                note=f"values below {floor:.0e} are clipped to {floor:.0e} for the log axis",
            )
        )
    desc = (
        "Normalised singular-value spectra of the standardised training design [1, P] for "
        "regimes P1, P2, P3 and L0, per network. n = 1 design per regime over the 384 training "
        "steps (L0 shares P1's PV seeds and differs only in its training loads). No "
        "uncertainty is shown: these are the realised spectra of one design each. Source: "
        "results/physics_<network>_<regime>.json, field excitation.singular_values and "
        "excitation.pv_corr_mean. Values are clipped at 1e-16 of the largest so that L0's "
        "rank-deficient tail fits a logarithmic axis; L0's stored condition number is the "
        "float maximum and is reported as inf (rank-deficient)."
    )
    return "fig_a_excitation_structure.svg", svgplot.Figure(
        title="A - Excitation structure of the training design",
        desc=desc,
        panels=panels,
        ncols=2,
        panel_width=470.0,
        panel_height=330.0,
        legend_width=200.0,
    )


def figure_b(study: Study) -> tuple[str, svgplot.Figure]:
    series = []
    for index, (model, method) in enumerate(VOLTAGE_MODELS):
        colour = svgplot.PALETTE[index + 1]
        for name, net in study.networks.items():
            xs, ys, counts, labels = [], [], [], []
            for regime in TRAINING_REGIMES:
                records = pick(net.records, method, regime, "near")
                k = unsafe_conditions(records, net.near_rows)
                n = net.n_near
                xs.append(_mean_test_mae(net, regime, model))
                ys.append(k / n if n else float("nan"))
                counts.append((k, n))
                labels.append(regime)
            lows, highs = _cp_bars(counts)
            evaluation = name == EVALUATION_NETWORK
            series.append(
                svgplot.Series(
                    x=xs,
                    y=ys,
                    ylo=lows,
                    yhi=highs,
                    label=f"{model} ({method}), {name}"
                    + ("" if evaluation else " - descriptive (A2)"),
                    marker="circle" if evaluation else "square",
                    filled=evaluation,
                    colour=colour,
                    point_labels=labels,
                )
            )
    panel = svgplot.Panel(
        series=series,
        title="rural3 verdict cells (filled); semiurb5 descriptive (A2, hollow)",
        xlabel="test-day MAE against AC truth (pu)",
        ylabel="near-set unsafe conditions / conditions",
        ylim=(-0.05, 1.08),
        hlines=[(H2_UNSAFE_FLOOR, "H2's 0.30 risk floor")],
    )
    desc = (
        "H2's 9 voltage-model x regime cells. x = the mean over replicates of the test-day MAE "
        "of the noise-free predicted voltage against the AC truth on day 156 (96 steps). "
        "y = the share of near conditions with an unsafe record in at least one replicate. "
        "Bars are Clopper-Pearson 95 % intervals with n = the number of near conditions, the "
        "protocol's n (s. 9: replicates are nested), i.e. n = 10 on rural3 and n = 2 on "
        "semiurb5; this matches every interval in results/stage_a_summary.json. semiurb5 is "
        "drawn hollow and is descriptive (A2). Source: results/envelopes_<network>.json, "
        "fields fits[].test_mae and records[].unsafe."
    )
    return "fig_b_prediction_against_decision.svg", svgplot.Figure(
        title="B - Prediction accuracy against decision safety",
        desc=desc,
        panels=[panel],
        panel_width=600.0,
        panel_height=380.0,
        legend_width=230.0,
    )


def _policy_points(net: Network, regime: str) -> list[dict]:
    rows = net.near_rows
    points = []
    for method in ("B0", "B1", "B2", "B2m", "B2p", "B3", "B4box", "B4", "A", "Aprime"):
        method_regime = NO_REGIME if method in REFERENCES else regime
        records = pick(net.records, method, method_regime, "near")
        if not records:
            continue
        companion = condition_utilisation(records, rows, net.oracle_total, True)
        points.append(
            {
                "policy": "A'" if method == "Aprime" else method,
                "median_companion_utilisation": _median(companion),
                "unsafe_conditions": unsafe_conditions(records, rows),
                "n_conditions": net.n_near,
            }
        )
    policies = [p for p in net.payloads["ambiguity"]["policies"] if p["regime"] == regime]
    if policies:
        policy = policies[0]
        act = [bool(flag) for flag in policy["act"]]
        fallback = [bool(flag) for flag in policy["rand_fallback"]]
        b2 = pick(net.records, "B2", regime, "near", replicate=0)
        b2p = pick(net.records, "B2p", regime, "near", replicate=0)
        b2_util = condition_utilisation(b2, rows, net.oracle_total, True)
        b2p_util = condition_utilisation(b2p, rows, net.oracle_total, True)
        cert_util = [b2_util[i] if act[i] else b2p_util[i] for i in range(len(rows))]
        rand_util = [b2p_util[i] if fallback[i] else b2_util[i] for i in range(len(rows))]
        points.append(
            {
                "policy": "CERT",
                "median_companion_utilisation": _median(cert_util),
                "unsafe_conditions": int(policy["cert_unsafe"]),
                "n_conditions": int(policy["n"]),
            }
        )
        points.append(
            {
                "policy": "ALWAYS",
                "median_companion_utilisation": _median(b2p_util),
                "unsafe_conditions": int(policy["always_unsafe"]),
                "n_conditions": int(policy["n"]),
            }
        )
        points.append(
            {
                "policy": "RAND",
                "median_companion_utilisation": _median(rand_util),
                "unsafe_conditions": int(policy["rand_unsafe"]),
                "n_conditions": int(policy["n"]),
            }
        )
    return points


def figure_c(study: Study) -> tuple[str, svgplot.Figure]:
    net = study.networks[EVALUATION_NETWORK]
    panels = []
    for regime in ("P1", "P3"):
        points = _policy_points(net, regime)
        counts = [(p["unsafe_conditions"], p["n_conditions"]) for p in points]
        lows, highs = _cp_bars(counts)
        panels.append(
            svgplot.Panel(
                series=[
                    svgplot.Series(
                        x=[p["median_companion_utilisation"] for p in points],
                        y=[p["unsafe_conditions"] / p["n_conditions"] for p in points],
                        ylo=lows,
                        yhi=highs,
                        point_labels=[p["policy"] for p in points],
                        marker="diamond",
                        filled=False,
                        colour=svgplot.PALETTE[0],
                        label="policy",
                    )
                ],
                title=f"{regime}, near set",
                xlabel="median companion utilisation Sum(e)/Sum(e_B5) (dimensionless)",
                ylabel="near-set unsafe conditions / conditions",
                ylim=(-0.06, 1.1),
                xlim=(-0.05, 1.05),
            )
        )
    desc = (
        "rural3, P1 and P3. x = the median over the 10 near conditions of the companion "
        "utilisation Sum(e)/Sum(e_B5), with utilisation 0 for an unsafe or degenerate record "
        "and a mean over replicates otherwise. y = the share of near conditions with an unsafe "
        "record in either replicate. Bars are Clopper-Pearson 95 % intervals with n = 10 "
        "conditions, the protocol's n (s. 9: replicates are nested). A and A' are "
        "regime-independent references and so repeat across both panels; CERT, ALWAYS and RAND "
        "are replicate-0 policies over B2 and B2p. Source: results/envelopes_rural3.json, "
        "results/oracle_rural3.json, runs/oracle_rural3.npz and "
        "results/ambiguity_rural3.json (policies)."
    )
    return "fig_c_safety_against_utilisation.svg", svgplot.Figure(
        title="C - Safety against utilisation, every policy",
        desc=desc,
        panels=panels,
        ncols=2,
        panel_width=470.0,
        panel_height=360.0,
        legend_width=120.0,
    )


def figure_d(study: Study) -> tuple[str, svgplot.Figure]:
    net = study.networks[EVALUATION_NETWORK]
    rows = net.near_rows
    correlations = {
        regime: float(net.payloads[f"physics_{regime}"]["excitation"]["pv_corr_mean"])
        for regime in REGIMES
    }
    ordered = ["P3", "P2", "P1"]
    series = []
    for index, method in enumerate(("B1", "B2", "B3", "B4box", "B4")):
        xs = [correlations[regime] for regime in ordered]
        ys = [
            float(np.nanmean(condition_rates(pick(net.records, method, regime, "near"), rows)))
            for regime in ordered
        ]
        series.append(
            svgplot.Series(
                x=xs,
                y=ys,
                label=method,
                kind="line+marker",
                marker=("circle", "square", "triangle", "diamond", "cross")[index],
                colour=svgplot.PALETTE[index % len(svgplot.PALETTE)],
            )
        )
    for index, method in enumerate(("B1", "B2", "B3", "B4box", "B4")):
        series.append(
            svgplot.Series(
                x=[correlations["L0"]],
                y=[
                    float(
                        np.nanmean(condition_rates(pick(net.records, method, "L0", "near"), rows))
                    )
                ],
                label=f"{method}, L0 (R = 1)",
                marker=("circle", "square", "triangle", "diamond", "cross")[index],
                filled=False,
                colour=svgplot.PALETTE[index % len(svgplot.PALETTE)],
            )
        )
    panel = svgplot.Panel(
        series=series,
        title="rural3, near set, primary decision",
        xlabel="measured mean PV correlation of the training regime (dimensionless)",
        ylabel="near-set voltage-unsafe rate u (mean over conditions and replicates)",
        ylim=(-0.06, 1.1),
    )
    desc = (
        "rural3. x = the regime's measured mean pairwise PV correlation, so P3, P2 and P1 "
        "appear from low to high; L0 is drawn hollow because it shares P1's PV seeds and "
        "differs only in its training loads, and it carries R = 1. y = the mean over the 10 "
        "near conditions of u_i, itself the mean over replicates of unsafe(r, i). n = 10 "
        "conditions x 2 replicates per filled point, 10 x 1 per hollow point. No uncertainty "
        "band is drawn: the per-cell Clopper-Pearson intervals are in figures B and C and in "
        "results/stage_a_summary.json. Source: results/envelopes_rural3.json and "
        "results/physics_rural3_<regime>.json."
    )
    return "fig_d_correlation_strength.svg", svgplot.Figure(
        title="D - Unsafe rate against measured PV correlation",
        desc=desc,
        panels=[panel],
        panel_width=600.0,
        panel_height=380.0,
        legend_width=200.0,
    )


def figure_e(study: Study) -> tuple[str, svgplot.Figure]:
    net = study.networks[EVALUATION_NETWORK]
    rows = net.near_rows
    panels = []
    for regime in ("P1", "P3"):
        b2 = pick(net.records, "B2", regime, "near", replicate=0)
        grouped = by_row(b2, rows)
        b2_ratio = [
            float(grouped[row][0]["total_e"]) / net.oracle_total[row]
            if grouped[row]
            else float("nan")
            for row in rows
        ]
        series = [
            svgplot.Series(
                x=list(range(len(rows))),
                y=b2_ratio,
                label="B2 (replicate 0)",
                marker="square",
                colour=svgplot.PALETTE[0],
            )
        ]
        safe_x, safe_y, unsafe_x, unsafe_y = [], [], [], []
        for alternative in range(4):
            records = [
                r
                for r in net.payloads["ambiguity"]["records"]
                if r["method"] == f"random{alternative}" and r["regime"] == regime
            ]
            for record in records:
                position = rows.index(int(record["row"]))
                ratio = float(record["total_e"]) / net.oracle_total[int(record["row"])]
                if is_unsafe(record):
                    unsafe_x.append(position)
                    unsafe_y.append(ratio)
                else:
                    safe_x.append(position)
                    safe_y.append(ratio)
        series.append(
            svgplot.Series(
                x=safe_x,
                y=safe_y,
                label="random alternative, voltage-safe",
                marker="circle",
                filled=False,
                colour=svgplot.PALETTE[3],
                size=2.8,
            )
        )
        series.append(
            svgplot.Series(
                x=unsafe_x,
                y=unsafe_y,
                label="random alternative, voltage-unsafe",
                marker="cross",
                colour=svgplot.PALETTE[6],
                size=2.8,
            )
        )
        panels.append(
            svgplot.Panel(
                series=series,
                title=f"{regime}, near set, replicate 0",
                xlabel="near condition (ordered as in the selection record)",
                ylabel="Sum(e) / Sum(e_B5) (dimensionless)",
                xticks=[(float(i), str(row)) for i, row in enumerate(rows)],
            )
        )
    net_extremes = {
        regime: sorted(
            {
                _nan_to_none(r.get("shrink_min"))
                for r in net.payloads["ambiguity"]["records"]
                if r["family"] == "extreme" and r["regime"] == regime
            }
        )
        for regime in ("P1", "P3")
    }
    desc = (
        "rural3, P1 and P3, per near condition, replicate 0. y = Sum(e)/Sum(e_B5) of B2 and of "
        "its 4 random data-consistent alternatives (moving-block bootstrap refits of the "
        "non-negative ridge, s. 8); voltage-unsafe alternatives are drawn as crosses. n = 10 "
        "conditions x 4 alternatives per panel. No uncertainty is shown: every point is one "
        "AC-scored envelope. The 4 extreme alternatives are not drawn because they collapse "
        f"onto the centre fit: every realised shrink factor is 0 (P1 {net_extremes['P1']}, "
        f"P3 {net_extremes['P3']}), so their export spread is 0 and is an upper bound, not a "
        "measured disagreement. Source: results/ambiguity_rural3.json, "
        "results/envelopes_rural3.json and runs/oracle_rural3.npz."
    )
    return "fig_e_model_disagreement.svg", svgplot.Figure(
        title="E - Decision disagreement across data-consistent models",
        desc=desc,
        panels=panels,
        ncols=2,
        panel_width=470.0,
        panel_height=350.0,
        legend_width=185.0,
    )


def figure_f(study: Study) -> tuple[str, svgplot.Figure]:
    net = study.networks[EVALUATION_NETWORK]
    rows = net.near_rows
    controls = net.payloads["controls"]["records"]
    entries: list[tuple[str, int, int]] = []

    def near(records: list[dict]) -> tuple[int, int]:
        return unsafe_conditions(records, rows), net.n_near

    entries.append(("B2 P1 primary", *near(pick(net.records, "B2", "P1", "near"))))
    entries.append(("B2 P3 primary", *near(pick(net.records, "B2", "P3", "near"))))
    far_records = pick(net.records, "B2", "P1", "far")
    entries.append(("D: B2 P1 far", sum(1 for r in far_records if is_unsafe(r)), len(net.far_rows)))
    entries.append(("H: T=192 P1", *near(pick(controls, method="H192", kind="near"))))
    entries.append(("H: T=384 P1", *near(pick(net.records, "B2", "P1", "near"))))
    entries.append(("H: T=768 P1", *near(pick(controls, method="H768", kind="near"))))
    for arm, label in (("I0.0005", "I: s=0.0005"), ("I0.005", "I: s=0.005")):
        for regime in ("P1", "P3"):
            entries.append(
                (f"{label} {regime}", *near(pick(controls, method=arm, regime=regime, kind="near")))
            )
    entries.append(("I: s=0.002 P1", *near(pick(net.records, "B2", "P1", "near"))))
    entries.append(("I: s=0.002 P3", *near(pick(net.records, "B2", "P3", "near"))))
    entries.append(("L0: B2 L0", *near(pick(net.records, "B2", "L0", "near"))))
    entries.append(("T: full P1", *near(pick(controls, method="T", regime="P1", kind="near"))))
    entries.append(("T: full P3", *near(pick(controls, method="T", regime="P3", kind="near"))))
    entries.append(("A (AC offset)", *near(pick(net.records, "A", NO_REGIME, "near"))))
    entries.append(("A' (train offset)", *near(pick(net.records, "Aprime", NO_REGIME, "near"))))

    lows, highs = _cp_bars([(k, n) for _, k, n in entries])
    panel = svgplot.Panel(
        series=[
            svgplot.Series(
                x=list(range(len(entries))),
                y=[k / n for _, k, n in entries],
                ylo=lows,
                yhi=highs,
                label="unsafe conditions / conditions",
                marker="circle",
                colour=svgplot.PALETTE[0],
                point_labels=[f"{k}/{n}" for _, k, n in entries],
            )
        ],
        title="rural3, near set unless the label says far",
        xlabel="control arm",
        ylabel="unsafe conditions / conditions",
        ylim=(-0.08, 1.12),
        xticks=[(float(i), label) for i, (label, _, _) in enumerate(entries)],
        xtick_rotate=45.0,
        note="x labels are the control arms in the order listed in the <desc>",
    )
    desc = (
        "rural3. B2's unsafe-condition share under each negative control, beside the primary "
        "cell, and Method A against Method A'. Arms, left to right: "
        + "; ".join(label for label, _, _ in entries)
        + ". y = the share of conditions with an unsafe record in any replicate. Bars are "
        "Clopper-Pearson 95 % intervals with n = the number of conditions (10 near, 10 far), "
        "the protocol's n. Control arms H and I carry replicate 0 only; the primary and "
        "control T arms carry both. The 17 arm labels are rotated 45 degrees, with the plot "
        "shortened to make room, so that none of them overlap. Source: "
        "results/envelopes_rural3.json and results/controls_rural3.json."
    )
    return "fig_f_negative_controls.svg", svgplot.Figure(
        title="F - Negative controls",
        desc=desc,
        panels=[panel],
        panel_width=720.0,
        panel_height=480.0,
        legend_width=200.0,
    )


FIGURE_BUILDERS = (figure_a, figure_b, figure_c, figure_d, figure_e, figure_f)


def build_figures(study: Study) -> list[tuple[str, str]]:
    """Every figure as (filename, svg text). Nothing is written here."""
    return [(name, figure.to_svg()) for name, figure in (build(study) for build in FIGURE_BUILDERS)]


# --- N. the command line ------------------------------------------------------------------


def _write_once_svg(path: Path, text: str) -> Path:
    if path.exists():
        raise FileExistsError(f"{path} exists; figures are written once and never rewritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def command_summary(dry_run: bool) -> int:
    study = build_summary()
    payload = study.summary
    if dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True, default=_json_default))
        print(f"\n[dry run] {SUMMARY_PATH} not written", file=sys.stderr)
        return 0
    path = ec.write_json_once(SUMMARY_PATH, payload)
    print(f"wrote {path} ({path.stat().st_size} bytes)")
    print(f"sha256 {ec.sha256_of(path)}")
    return 0


def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    raise TypeError(f"{type(obj).__name__} is not JSON-serialisable")


def command_figures(dry_run: bool) -> int:
    study = build_summary()
    for name, text in build_figures(study):
        if dry_run:
            print(f"[dry run] {name}: {len(text)} bytes")
            continue
        path = _write_once_svg(FIGURES / name, text)
        print(f"wrote {path} ({path.stat().st_size} bytes) sha256 {ec.sha256_of(path)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("summary", "figures"))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="compute and print without writing, so each write-once artefact is written once",
    )
    args = parser.parse_args(argv)
    ec.check_protocol()
    if args.command == "summary":
        return command_summary(args.dry_run)
    return command_figures(args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
