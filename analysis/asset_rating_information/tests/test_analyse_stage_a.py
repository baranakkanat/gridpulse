"""Tests for the Mission 12 Stage A read-out (`analyse_stage_a.py`).

**No real data and no solves.** Every test builds a synthetic artefact tree in `tmp_path` in
round numbers, with the field names and the nesting copied from one real evaluation record
(`results/eval_semiurb4_U2.json`), and points the module's `RESULTS`, `RUNS` and `FIGURES` at
it. The study's own `results/` and `runs/` are never read, so each expected number below is
arithmetic a reader can redo by hand from the fixture.

The fixture carries two networks: `netT`, transformer-limited, and `netC`, cable-limited, so
that the per-class branches (the companion model, the cable-limited-only blocks) are both
exercised on a tree small enough to check by eye.
"""

from __future__ import annotations

import ast
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import analyse_stage_a as an  # noqa: E402
import svgplot  # noqa: E402

SVG_NS = "{http://www.w3.org/2000/svg}"

NET_T = "netT"
NET_C = "netC"
N_TRUTH = 200
POOL_UNITS = 5
BUDGETS = ("1", "2", "3", "4", "all")

#: The seven evaluations `build_tree` writes, which `verdicts.json` must record as scored: the
#: completeness guard compares the two sets and refuses any difference.
FIXTURE_COMBINATIONS = (
    f"{NET_T}/{an.U2}",
    f"{NET_T}/{an.TRAFO_MODEL}",
    f"{NET_C}/{an.U2}",
    f"{NET_C}/{an.U2_W3}",
    f"{NET_C}/U3",
    f"{NET_C}/U4",
    f"{NET_C}/{an.U2_PRIME}",
)

#: netC under U2: the oracle, B2 and the policies, in round numbers. The loss is
#: 200 - 160 = 40 MWh, i.e. 20 % of the oracle.
ORACLE_C = 200.0
B2_C = 160.0
B3_C = 164.0
#: B6's recovery curve under U2. 0.27 at k = 1 is H3a's maximum, which amendment A4 flags.
B6_R = {"1": 0.27, "2": 0.5, "3": 0.75, "4": 0.9, "all": 1.0}
B6_SE = 0.02
#: B6's **mean exports**, deliberately not B2 + R x (oracle - B2): amendment A5's
#: energy-weighted recovery is a ratio of means, so it must come out different from the mean
#: of the per-draw ratios above. (192.8 - 160) / 40 = 0.82 at k = 4, against R = 0.9.
B6_EXPORT = {"1": 164.0, "2": 176.0, "3": 190.0, "4": 192.8, "all": 200.0}
B6_ENERGY_WEIGHTED = {"1": 0.1, "2": 0.4, "3": 0.75, "4": 0.82, "all": 1.0}
B5_R = {"1": 0.1, "2": 0.2, "3": 0.3, "4": 0.4, "all": 1.0}
B9_R = {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.9, "all": 1.0}
B9_UNITS = {"1": 0.0, "2": 0.0, "3": 0.0, "4": 4.0, "all": 5.0}
OB_R = {"1": 0.27, "2": 0.5, "3": 0.75, "4": 0.75, "all": 1.0}
OB_SEARCHED_KMAX = 3
#: The single-unit VoI of the pool under U2: only the last unit is worth anything alone.
VOI_SINGLE = (0.0, 0.0, 0.0, 0.0, 8.0)

#: netC under U2': the oracle and B2 collapse towards each other, and B2 becomes unsafe.
ORACLE_C_U2P = 100.0
B2_C_U2P = 90.0
U2P_K4_EXPORT = {"B5": 91.0, "B6": 95.0, "B8P": 92.0, "B9": 90.0}
#: Per draw: 3 draws with oracle - B2 <= 0, and 2 with 0 < oracle - B2 < 1 % of the oracle.
U2P_B2_PER_DRAW = (100.0, 101.0, 102.0, 99.5, 99.6, 90.0, 80.0, 70.0, 60.0, 50.0)

#: netT: U2 is decision-irrelevant (no loss); U-T loses 6 of 120 MWh, i.e. 5 %.
ORACLE_T_U2 = 100.0
ORACLE_T_UT = 120.0
B2_T_UT = 114.0

#: Control E, per network. Round numbers, and |dvm| far from any rating value.
CONTROL_E = {
    NET_T: {"share_invisible": 0.01, "share_true": 0.2, "p95": 0.001, "max": 0.004},
    NET_C: {"share_invisible": 0.05, "share_true": 0.6, "p95": 0.002, "max": 0.008},
}
#: The forbidden rating values the fixture plants, chosen so that they cannot appear as an
#: axis tick, a coordinate or a recovery level in any figure.
I_KA_MODIFIED = 0.1234
I_KA_RECORD = 0.4321
STD_TYPE = "SYNTH 4x999 0.0/0kV"

H3A_MAX = 0.27
H3A_SE = 0.02

#: Amendment A5's fixture. The U2 per-draw arrays below are the only place the paired standard
#: errors come from, so they are written out draw by draw.
#:
#: Twelve draws. The last two have oracle = B2, so their per-draw recovery is NaN and both are
#: excluded; ten remain. B8P at k = 2 is 0.6 on five draws and 0.4 on five, against B6's flat
#: 0.5, so the paired difference has mean 0 and SE sqrt(0.1 / 9) / sqrt(10) = 1 / 30. H3c's
#: arms differ by a constant 0.5, so its paired SE is exactly 0.
U2_ORACLE_PER_DRAW = (200.0,) * 12
U2_B2_PER_DRAW = (160.0,) * 10 + (200.0, 200.0)
U2_DRAW_EXPORTS = {
    "B6__2__export": (180.0,) * 12,
    "B8P__2__export": (184.0,) * 5 + (176.0,) * 5 + (180.0, 180.0),
    "B6__4__export": (196.0,) * 12,
    "B5__4__export": (176.0,) * 12,
}
U2_DRAWS_USED = 10
U2_DRAWS_EXCLUDED = 2
H3B_PAIRED_SE = 1.0 / 30.0
H3B_BUDGET = "2"
H3B_GAP = 0.0
H3C_GAP = 0.5
#: H5(c) on netC: B6's k = 4 cell, margin 0.9 - 0.5 = 0.4 against 2 x 0.02.
H5C_SE = B6_SE
#: H4 on netC: 0.96 against the 0.95 criterion is a margin of 0.01, below
#: 2 x sqrt(0.96 x 0.04 / 200) = 0.0277, so U2 is fragile; U4's share of 1.0 has SE 0.
H4_DRAW_SHARE_U2 = 0.96
H4_DRAW_SHARE_U4 = 1.0
H4_SUBSETS_SCORED_U2 = 851
#: Control G: one non-pool table column plus two non-table lines is `CONTROL_G_LINES = 3`.
CONTROL_G_EVALUATED = 3
CONTROL_G_ZERO_VALUE_CANDIDATES = 2

VERDICT_H1 = "DESCRIPTIVE (protocol s. 7: already visible in the audit)"
VERDICT_H2 = "ANALYTIC (protocol s. 7: not an empirical hypothesis)"
VERDICT_H3A = "REJECTED"
VERDICT_H3B = "REJECTED"
VERDICT_H3C = "SUPPORTED"
VERDICT_H5 = "SUPPORTED"
VERDICT_H4_C = "SUPPORTED"
VERDICT_H4_T = "NOT EVALUABLE (no candidate pool)"


# --- the synthetic artefact tree -------------------------------------------------------------


def _dist(mean: float, p5: float | None = None, p95: float | None = None) -> dict:
    return {
        "mean": mean,
        "n": N_TRUTH,
        "p5": mean if p5 is None else p5,
        "p95": mean if p95 is None else p95,
    }


def _unsafe(draw_share: float = 0.0, step_share: float = 0.0) -> dict:
    return {
        "max_steps": 0 if not step_share else 100,
        "mean_steps": 0.0 if not step_share else 10.0,
        "share_draws_ge1": draw_share,
        "unsafe_step_share": step_share,
    }


def _severity(p95: float = -1.0, top: float = -0.5) -> dict:
    return {"max": top, "p95": p95}


def _direct(export: float, draw_share: float = 0.0, step_share: float = 0.0) -> dict:
    """A reference policy of protocol s. 7: one decision, no recovery, keyed by "na"."""
    return {
        "na": {
            "export_MWh": _dist(export),
            "severity_pct": _severity(),
            "unsafe": _unsafe(draw_share, step_share),
        }
    }


def _budgeted(
    policy: str,
    recovery: dict[str, float],
    *,
    se: float = 0.01,
    units: dict[str, float] | None = None,
    export: dict[str, float] | None = None,
) -> dict:
    """A budgeted policy: one entry per budget, with the recovery and realised counts."""
    entry = {}
    for budget, value in recovery.items():
        realised = (
            float(POOL_UNITS)
            if budget == an.BUDGET_ALL
            else float(budget)
            if units is None
            else units[budget]
        )
        exported = B2_C + value * (ORACLE_C - B2_C) if export is None else export.get(budget, B2_C)
        entry[budget] = {
            "export_MWh": _dist(exported),
            "export_per_draw_key": f"{policy}__{budget}__export",
            "realised_segments": _dist(realised),
            "realised_units": _dist(realised),
            "recovery": {
                "mean": value,
                "n": N_TRUTH,
                "nan_excluded": 0,
                "p5": value,
                "p95": value,
                "se": se,
            },
            "severity_pct": _severity(),
            "unsafe": _unsafe(),
        }
    return entry


def _b3_vs_b2(gap: float, draw_share: float = 0.0, step_share: float = 0.0) -> dict:
    return {
        "B3_more_conservative_than_B2_steps": 0,
        "believed_lower_bound_pct": 80.0,
        "export_gap_MWh": _dist(gap),
        "B3_unsafe": _unsafe(draw_share, step_share),
        "fault": False,
    }


def _h4(size: int | None) -> dict:
    if size is None:
        return {"available": False}
    columns = list(range(size))
    return {
        "available": True,
        "criterion": {"draw_share": 0.95, "step_share": 0.95},
        "kmax": 6,
        "named_candidates": [
            {
                "columns": [0, 1, 2, 3],
                "draw_share": 1.0,
                "qualifies": True,
                "size": 4,
                "source": "B8P",
            }
        ],
        "rejected": False,
        "smallest": {
            "columns": columns,
            "draw_share": 0.96,
            "size": size,
            "source": "exhaustive",
        },
        "supported": True,
    }


def _record(
    network: str,
    model: str,
    *,
    policies: dict,
    gap: float,
    n_units: int,
    unit_kind: str = "segment",
    voi: tuple[float, ...] = (),
    ob_kmax: int | None = None,
    h4_size: int | None = None,
    b3_draw_share: float = 0.0,
    b3_step_share: float = 0.0,
    code: dict | None = None,
) -> dict:
    """One evaluation record, with the field names of `results/eval_semiurb4_U2.json`."""
    return {
        "array_keys": sorted(
            f"{policy}__{budget}__{kind}"
            for policy, entry in policies.items()
            for budget in entry
            for kind in ("export", "severity", "unsafe")
        ),
        "arrays_written": f"runs/eval_{network}_{model}.npz",
        "b3_vs_b2": _b3_vs_b2(gap, b3_draw_share, b3_step_share),
        "b9": {
            "note": "the per-round reveal wrapper (amendment A1)",
            "terminated_by_kmax_share": 0.0,
        },
        "code_sha256": dict(an.FROZEN_CODE_SHA256) if code is None else code,
        "command": "evaluate",
        # Control G reports `CONTROL_G_LINES = 3` non-pool columns per combination: here one
        # table column plus two lines that are not table lines at all (amendment A5's
        # disclosure (b)).
        "control_g": {
            "non_pool_table_columns": [
                {"VoI_E": 0.0, "VoI_P": 0.0, "column": 0, "line_id": 7},
            ],
            "non_table_lines": [
                {"VoI_E": 0.0, "VoI_P": 0.0, "line_id": 8, "reason": "not a table line"},
                {"VoI_E": 0.0, "VoI_P": 0.0, "line_id": 9, "reason": "not a table line"},
            ],
            "zero_value_candidates": CONTROL_G_ZERO_VALUE_CANDIDATES,
        },
        "h4": _h4(h4_size),
        "model": model,
        "network": network,
        "new_ac_solves": 0,
        "ob": (
            {"available": False}
            if ob_kmax is None
            else {"available": True, "kmax": ob_kmax, "searched_kmax": ob_kmax, "modal_set": [3, 4]}
        ),
        "policies": policies,
        "pool": {
            "columns": list(range(n_units)),
            "n_units": n_units,
            "n_units_all_reference": n_units,
            "unit_kind": unit_kind,
            "units": [[index] for index in range(n_units)],
        },
        "protocol_sha256": "0" * 64,
        "rc_model": model,
        "sizes": {
            "budgets": [1, 2, 3, 4, "all"],
            "n_prior": 100,
            "n_truth": N_TRUTH,
            "steps_E": 1000,
            "steps_P": 1000,
        },
        "situation": {"E": {"n_steps": 1000, "share_situation_1": 0.8}},
        "status": "synthetic fixture",
        "tables_code_sha256": {"ratings_core.py": "a" * 64, "run_stage_a.py": "b" * 64},
        "voi": [
            {
                # A unit worth something in expectation also has a positive 100-sample
                # minimum here, which is what amendment A5's disclosure (a) counts.
                "VoI_E": {
                    "expected_MWh": value,
                    "best_MWh": value,
                    "worst_MWh": value / 2.0,
                    "n_prior": 100,
                },
                "VoI_P": {"expected_MWh": 0.0, "best_MWh": 0.0, "worst_MWh": 0.0, "n_prior": 100},
                "columns": [index],
                "kind": unit_kind,
                "line_ids": [index],
                "unit": index,
            }
            for index, value in enumerate(voi)
        ],
        "w_believed": 0.2,
        "w_truth": 0.2,
    }


def _netc_u2(code: dict | None = None, b9_units: dict[str, float] | None = None) -> dict:
    policies = {
        "B0": _direct(250.0, draw_share=0.9, step_share=0.1),
        "B1": _direct(180.0, draw_share=0.6, step_share=0.05),
        "B2": _direct(B2_C),
        "B3": _direct(B3_C, draw_share=0.02, step_share=0.001),
        "B4": _direct(ORACLE_C),
        "B5": _budgeted("B5", B5_R),
        "B6": _budgeted("B6", B6_R, se=B6_SE, export=B6_EXPORT),
        "B7": _budgeted("B7", B6_R, se=B6_SE),
        "B8P": _budgeted("B8P", B6_R, se=B6_SE),
        "B9": _budgeted("B9", B9_R, units=B9_UNITS if b9_units is None else b9_units),
        "OB": _budgeted("OB", OB_R),
    }
    return _record(
        NET_C,
        an.U2,
        policies=policies,
        gap=B3_C - B2_C,
        n_units=POOL_UNITS,
        voi=VOI_SINGLE,
        ob_kmax=OB_SEARCHED_KMAX,
        h4_size=3,
        b3_draw_share=0.02,
        b3_step_share=0.001,
        code=code,
    )


def _netc_other(model: str, curve: dict[str, float]) -> dict:
    policies = {
        "B0": _direct(250.0, draw_share=0.8, step_share=0.1),
        "B1": _direct(180.0, draw_share=0.5, step_share=0.04),
        "B2": _direct(B2_C),
        "B3": _direct(B3_C),
        "B4": _direct(ORACLE_C),
        "B6": _budgeted("B6", curve),
    }
    return _record(
        NET_C, model, policies=policies, gap=B3_C - B2_C, n_units=POOL_UNITS, voi=VOI_SINGLE
    )


def _netc_u4() -> dict:
    """Under U4 the whole pool is one route unit, so B6 resolves it at k = 1."""
    policies = {
        "B0": _direct(250.0, draw_share=0.8, step_share=0.1),
        "B1": _direct(180.0),
        "B2": _direct(B2_C),
        "B3": _direct(B3_C),
        "B4": _direct(ORACLE_C),
        "B6": {
            budget: {
                "export_MWh": _dist(ORACLE_C),
                "export_per_draw_key": f"B6__{budget}__export",
                "realised_segments": _dist(float(POOL_UNITS)),
                "realised_units": _dist(1.0),
                "recovery": {
                    "mean": 1.0,
                    "n": N_TRUTH,
                    "nan_excluded": 0,
                    "p5": 1.0,
                    "p95": 1.0,
                    "se": 0.0,
                },
                "severity_pct": _severity(),
                "unsafe": _unsafe(),
            }
            for budget in ("1", an.BUDGET_ALL)
        },
    }
    return _record(
        NET_C,
        "U4",
        policies=policies,
        gap=B3_C - B2_C,
        n_units=1,
        unit_kind="route",
        voi=(8.0,),
    )


def _netc_u2p() -> dict:
    gap = ORACLE_C_U2P - B2_C_U2P
    policies = {
        "B0": _direct(130.0, draw_share=1.0, step_share=0.2),
        "B1": _direct(110.0, draw_share=0.7, step_share=0.1),
        "B2": _direct(B2_C_U2P, draw_share=0.4, step_share=0.006),
        "B3": _direct(91.0, draw_share=0.5, step_share=0.009),
        "B4": _direct(ORACLE_C_U2P),
    }
    # OB is in the record at every budget, but searched to k <= 3 only (amendment A3), so its
    # k = 4 cell is a repeat of k = 3 and the read-out must leave it out.
    for policy, export in {**U2P_K4_EXPORT, "OB": 99.0}.items():
        recovery = {budget: (export - B2_C_U2P) / gap for budget in BUDGETS}
        exports = dict.fromkeys(BUDGETS, export)
        policies[policy] = _budgeted(policy, recovery, export=exports)
        for budget in BUDGETS:
            policies[policy][budget]["unsafe"] = _unsafe(0.3, 0.004)
    return _record(
        NET_C,
        an.U2_PRIME,
        policies=policies,
        gap=1.0,
        n_units=POOL_UNITS,
        voi=VOI_SINGLE,
        ob_kmax=OB_SEARCHED_KMAX,
        b3_draw_share=0.5,
        b3_step_share=0.009,
    )


def _nett(model: str, oracle: float, base: float) -> dict:
    policies = {
        "B0": _direct(oracle),
        "B1": _direct(base),
        "B2": _direct(base),
        "B3": _direct(base),
        "B4": _direct(oracle),
    }
    return _record(NET_T, model, policies=policies, gap=0.0, n_units=0)


def _h3b_per_network() -> dict:
    """H3b's per-budget cells on netC: the structural arm equals the single arm at every
    budget, so every gap is 0.0 and H3b is rejected at each k on its own."""
    return {
        "budget_with_smallest_gap": int(H3B_BUDGET),
        "fragile": False,
        "gap": H3B_GAP,
        "per_budget": {
            budget: {
                "gap": 0.0,
                "single": "B6",
                "single_R": B6_R[budget],
                "single_se": B6_SE,
                "structural": "B8P",
                "structural_R": B6_R[budget],
                "structural_se": B6_SE,
            }
            for budget in ("2", "3", "4")
        },
    }


def _h4_per_model(draw_share: float, size: int, subsets_scored: int) -> dict:
    return {
        "available": True,
        "criterion": {"draw_share": 0.95, "step_share": 0.95},
        "kmax": 6,
        "named_candidates": [
            {"columns": [0, 1, 2, 3], "draw_share": 1.0, "qualifies": True, "size": 4, "source": s}
            for s in ("B8P", "B9-static", "B9")
        ],
        "rejected": False,
        "smallest": {
            "columns": list(range(size)),
            "draw_share": draw_share,
            "size": size,
            "source": "exhaustive",
        },
        "subsets_scored": subsets_scored,
        "supported": True,
    }


def _verdicts(h3a_se: float = H3A_SE, h5c_se: float = H5C_SE) -> dict:
    h3a_entry = {"mean": H3A_MAX, "se": h3a_se, "nan_excluded": 0, "missing": False}
    return {
        "H1": {
            "networks": {
                NET_T: {
                    "B2_export_MWh": ORACLE_T_U2,
                    "B2_loss_share_of_oracle": 0.0,
                    "class": "transformer-limited",
                    "oracle_export_MWh": ORACLE_T_U2,
                    "relevant_by_H1_rule": False,
                },
                NET_C: {
                    "B2_export_MWh": B2_C,
                    "B2_loss_share_of_oracle": 0.2,
                    "class": an.CABLE_LIMITED,
                    "oracle_export_MWh": ORACLE_C,
                    "relevant_by_H1_rule": True,
                },
            },
            "verdict": VERDICT_H1,
        },
        "H2": {"checked_by": ["Control D", "Control E"], "verdict": VERDICT_H2},
        "H3": {
            "H3a": {
                "max_R1_over_policies_and_networks": H3A_MAX,
                "networks_scored": [NET_C],
                "verdict": VERDICT_H3A,
            },
            "H3b": {
                "fragile_networks": [],
                "gap_per_network": {NET_C: H3B_GAP},
                "incomplete": False,
                "verdict": VERDICT_H3B,
            },
            "H3c": {
                "fragile_networks": [],
                "gap_per_network": {NET_C: H3C_GAP},
                "incomplete": False,
                "verdict": VERDICT_H3C,
            },
            "H5": {"incomplete": False, "verdict": VERDICT_H5},
            "model": an.U2,
            "note": "revision 2.2: the H3 verdicts are evaluated under U2 only",
            "per_network": {
                NET_C: {
                    "H3a": {
                        "B6": dict(h3a_entry),
                        "B7": dict(h3a_entry),
                        "B8": {"mean": 0.2, "se": 0.01, "nan_excluded": 0, "missing": False},
                        "max_R1": H3A_MAX,
                    },
                    "H3b": _h3b_per_network(),
                    "H3c": {
                        "B5_R": B5_R["4"],
                        "best_targeted": "B6",
                        "fragile": False,
                        "gap": H3C_GAP,
                        "targeted_R": B6_R["4"],
                    },
                    "H5c": {
                        "R": B6_R["4"],
                        "budget": 4,
                        "fragile": False,
                        "holds": True,
                        "policy": "B6",
                        "realised_segments": 4.0,
                        "realised_units": 4.0,
                        "se": h5c_se,
                        "threshold": 0.5,
                    },
                }
            },
        },
        "H4": {
            "descriptive_model": "U4",
            "per_network": {
                NET_C: {
                    "U2": _h4_per_model(H4_DRAW_SHARE_U2, 3, H4_SUBSETS_SCORED_U2),
                    "U4": _h4_per_model(H4_DRAW_SHARE_U4, 1, 848),
                    "verdict": VERDICT_H4_C,
                },
                NET_T: {"verdict": VERDICT_H4_T},
            },
            "verdict_model": an.U2,
        },
        "H5": {"incomplete": False, "verdict": VERDICT_H5},
        "code_sha256": dict(an.FROZEN_CODE_SHA256),
        "combinations_missing": [],
        "combinations_scored": list(FIXTURE_COMBINATIONS),
        "command": "verdicts",
        "control_pass": {"A": True, "B3_vs_B2": True, "C": True, "D": None, "F": True, "J": True},
        "controls": {"D": {"pass": None, "source": "results/control_d.json", "summary": None}},
        "effect_sizes": {
            "H3a_reject": 0.25,
            "H3a_upper": 0.1,
            "H3b_reject": 0.05,
            "H3b_support": 0.2,
            "H3c_reject": 0.05,
            "H3c_support": 0.2,
            "H4_cable_fraction": 0.25,
            "H5c_budget_segments": 4,
            "H5c_recovery": 0.5,
            "control_I_close": 0.05,
        },
        "protocol_sha256": "0" * 64,
        "status": "synthetic fixture",
        "stop_conditions": {
            "cable_limited_B2_loss_below_1pct": {NET_C: 0.2},
            "control_C_D_F_or_B3_fails": False,
            "deployable_policy_read_rho_true": False,
        },
        "u2_prime": {NET_C: {}},
    }


def _control_d() -> dict:
    return {
        "cap_level": 1.0,
        "cap_level_index": 0,
        "code_sha256": {"ratings_core.py": "a" * 64, "run_stage_a.py": "b" * 64},
        "command": "control-d",
        "day": 144,
        "line": 33,
        "max_i_ka": {"modified": I_KA_MODIFIED, "nominal": I_KA_RECORD},
        "network": NET_C,
        "protocol_sha256": "0" * 64,
        "rating_factor": 0.8,
        "rating_only_change": {
            "comparisons": [
                {
                    "argmax_abs": 0,
                    "max_abs_diff": 0.0,
                    "max_rel_diff": 0.0,
                    "n": 59,
                    "quantity": "res_bus.vm_pu",
                    "tolerance_rel": 1e-9,
                    "within_tolerance": True,
                },
                {
                    "argmax_abs": 0,
                    "max_abs_diff": 0.0,
                    "max_rel_diff": 0.0,
                    "n": 57,
                    "quantity": "res_line.i_ka",
                    "tolerance_rel": 1e-9,
                    "within_tolerance": True,
                },
            ],
            "loading_percent_changes_as_expected": {
                "argmax_abs": 33,
                "max_abs_diff": 32.0,
                "max_rel_diff": 0.2,
                "n": 57,
                "quantity": "res_line.loading_percent (the only quantity that must change)",
                "within_tolerance": True,
            },
            "pass": True,
        },
        "solves_attempted": 2,
        "status": "synthetic fixture",
    }


def _control_e(network: str) -> dict:
    numbers = CONTROL_E[network]
    return {
        "alignment": {
            "availability_identical": True,
            "line_rating_factor": 0.8,
            "modified_line": 3,
            "modified_line_std_type": STD_TYPE,
            "pass": True,
        },
        "code_sha256": {"ratings_core.py": "a" * 64, "run_stage_a.py": "b" * 64},
        "command": "control-e",
        "counts": {"daylight_steps": 14000, "step_levels": 100000},
        "distributions": {
            "vm_abs_delta_all_buses": {
                "max": numbers["max"],
                "mean": numbers["p95"] / 2.0,
                "median": numbers["p95"] / 4.0,
                "n": 1000,
                "n_non_finite": 0,
                "p95": numbers["p95"],
                "unit": "p.u.",
            }
        },
        "invisible_overload": {
            "definition": "true utilisation above 100.5 % while the nominal model sees <= 100 %",
            "n_invisible": 1000,
            "n_step_levels": 100000,
            "share_invisible": numbers["share_invisible"],
            "share_of_true_over_that_is_invisible": numbers["share_true"],
        },
        "modified_cable": {
            "line": 3,
            "max_i_ka_modified": I_KA_MODIFIED,
            "max_i_ka_record": I_KA_RECORD,
            "std_type": STD_TYPE,
        },
        "network": network,
        "protocol_sha256": "0" * 64,
        "status": "synthetic fixture",
    }


def build_tree(
    root: Path,
    *,
    h3a_se: float = H3A_SE,
    h5c_se: float = H5C_SE,
    eval_code: dict | None = None,
) -> Path:
    """Write the synthetic `results/` and `runs/` under `root` and return `root`."""
    results = root / "results"
    runs = root / "runs"
    results.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)
    records = [
        _nett(an.U2, ORACLE_T_U2, ORACLE_T_U2),
        _nett(an.TRAFO_MODEL, ORACLE_T_UT, B2_T_UT),
        _netc_u2(code=eval_code),
        _netc_other(an.U2_W3, {"1": 0.3, "2": 0.4, "3": 0.5, "4": 0.6, "all": 1.0}),
        _netc_other("U3", {"1": 0.2, "2": 0.3, "3": 0.4, "4": 0.5, "all": 1.0}),
        _netc_u4(),
        _netc_u2p(),
    ]
    for record in records:
        path = results / f"eval_{record['network']}_{record['model']}.json"
        path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    (results / "verdicts.json").write_text(
        json.dumps(_verdicts(h3a_se, h5c_se), indent=2, sort_keys=True) + "\n"
    )
    (results / "control_d.json").write_text(json.dumps(_control_d(), indent=2, sort_keys=True))
    for network in (NET_T, NET_C):
        (results / f"control_e_{network}.json").write_text(
            json.dumps(_control_e(network), indent=2, sort_keys=True)
        )
    np.savez_compressed(
        runs / f"eval_{NET_C}_{an.U2_PRIME}.npz",
        **{
            "B4__na__export": np.full(len(U2P_B2_PER_DRAW), ORACLE_C_U2P),
            "B2__na__export": np.asarray(U2P_B2_PER_DRAW, dtype=float),
        },
    )
    # Amendment A5's paired standard errors read the U2 arrays of the compared cells.
    np.savez_compressed(
        runs / f"eval_{NET_C}_{an.U2}.npz",
        **{
            "B4__na__export": np.asarray(U2_ORACLE_PER_DRAW, dtype=float),
            "B2__na__export": np.asarray(U2_B2_PER_DRAW, dtype=float),
            **{key: np.asarray(values, dtype=float) for key, values in U2_DRAW_EXPORTS.items()},
        },
    )
    return root


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A synthetic tree, with the module pointed at it for the length of one test."""
    root = build_tree(tmp_path)
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    monkeypatch.setattr(an, "FIGURES", root / "figures")
    return root


@pytest.fixture
def summary(tree):
    return an.build_summary().summary


# --- hygiene --------------------------------------------------------------------------------


def test_the_read_out_imports_no_power_flow_package():
    """The read-out is physics-free: an imported `pandapower` would be a protocol breach."""
    source = (HERE / "analyse_stage_a.py").read_text()
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"pandapower", "simbench"}


def test_svgplot_is_imported_from_mission_11_and_not_copied():
    assert not (HERE / "svgplot.py").exists()
    assert Path(svgplot.__file__).resolve().parent.name == "export_envelope_shift"


def test_the_notice_names_mission_12s_attribution_file():
    assert an.ATTRIBUTION_NOTICE.endswith(
        "See analysis/asset_rating_information/DATA_ATTRIBUTION.md."
    )
    assert "SimBench" in an.ATTRIBUTION_NOTICE and "ODbL 1.0" in an.ATTRIBUTION_NOTICE


def test_importing_this_module_leaves_mission_11s_notice_alone():
    """Amendment A5: the override belongs to `build_figures`, not to the import.

    Before A5 this module assigned `svgplot.ATTRIBUTION_NOTICE` at import, which rewrote
    Mission 11's notice for every later figure in the same process.
    """
    assert svgplot.ATTRIBUTION_NOTICE != an.ATTRIBUTION_NOTICE
    assert "export_envelope_shift" in svgplot.ATTRIBUTION_NOTICE


# --- (a) the numbers in each summary block --------------------------------------------------


def test_provenance_records_the_four_code_files_and_every_input(summary):
    provenance = summary["provenance"]
    assert set(provenance["frozen_code_sha256"]) == {"ratings_core.py", "run_stage_a.py"}
    assert provenance["frozen_code_sha256"] == an.FROZEN_CODE_SHA256
    assert set(provenance["read_out_code_sha256"]) == {"analyse_stage_a.py", "svgplot.py"}
    assert all(len(digest) == 64 for digest in provenance["read_out_code_sha256"].values())
    assert (
        provenance["protocol"]["as_executed_sha256"]
        == provenance["protocol"]["as_executed_expected"]
    )
    assert len(provenance["protocol"]["sha256"]) == 64
    # 7 evaluations, verdicts.json, control_d.json, two control_e files and two npz.
    assert len(provenance["inputs_sha256"]) == 13
    assert f"results/eval_{NET_C}_{an.U2}.json" in provenance["inputs_sha256"]
    assert f"runs/eval_{NET_C}_{an.U2_PRIME}.npz" in provenance["inputs_sha256"]
    assert f"runs/eval_{NET_C}_{an.U2}.npz" in provenance["inputs_sha256"]
    assert provenance["inputs_counted"] == {
        "evaluations": 7,
        "per_draw_npz": 1,
        "u2_per_draw_npz": 1,
        "control_e": 2,
    }
    assert provenance["frozen_code_check"]["all_match"] is True
    assert provenance["frozen_code_check"]["evaluations_checked"] == 7


def test_decision_relevance_is_the_loss_the_fixture_was_built_with(summary):
    cable = summary["decision_relevance"][NET_C]
    assert cable["class"] == an.CABLE_LIMITED
    assert cable["companion_model"] == an.U2_W3
    u2 = cable["per_model"][an.U2]
    assert u2["oracle_export_MWh"] == ORACLE_C
    assert u2["B2_export_MWh"] == B2_C
    assert u2["B2_loss_MWh"] == 40.0
    assert u2["B2_loss_pct_of_oracle"] == 20.0
    assert u2["B0_unsafe_draw_share"] == 0.9
    assert u2["B3_minus_B2_MWh"] == 4.0
    assert u2["B3_unsafe_draw_share"] == 0.02

    trafo = summary["decision_relevance"][NET_T]
    assert trafo["class"] == "transformer-limited"
    assert trafo["companion_model"] == an.TRAFO_MODEL
    assert trafo["per_model"][an.U2]["B2_loss_MWh"] == 0.0
    assert trafo["per_model"][an.U2]["B2_loss_pct_of_oracle"] == 0.0
    # U-T: (120 - 114) / 120 = 5 %.
    assert trafo["per_model"][an.TRAFO_MODEL]["B2_loss_MWh"] == 6.0
    assert trafo["per_model"][an.TRAFO_MODEL]["B2_loss_pct_of_oracle"] == 5.0


def test_decision_relevance_covers_every_network_and_model(summary):
    relevance = summary["decision_relevance"]
    # The networks keep `verdicts.json`'s own order, which the fixture writes sorted.
    assert list(relevance) == [NET_C, NET_T]
    assert list(relevance[NET_T]["per_model"]) == [an.U2, an.TRAFO_MODEL]
    # MODEL_ORDER, not the directory listing: U2, U2w3, U3, U4, U2'.
    assert list(relevance[NET_C]["per_model"]) == [an.U2, an.U2_W3, "U3", "U4", an.U2_PRIME]


def test_verification_is_cable_limited_only_and_carries_R_SE_and_counts(summary):
    verification = summary["verification"]
    assert list(verification) == [NET_C]
    curves = verification[NET_C][an.U2]["R"]
    assert set(curves) == {"B5", "B6", "B7", "B8P", "B9", "OB"}
    b6 = curves["B6"]
    assert [b6[key]["R_mean"] for key in an.budget_order(b6)] == [
        B6_R[key] for key in ("1", "2", "3", "4", "all")
    ]
    assert b6["4"]["R_se"] == B6_SE
    assert b6["4"]["realised_units"] == 4.0
    assert b6["4"]["realised_segments"] == 4.0
    assert b6[an.BUDGET_ALL]["realised_units"] == float(POOL_UNITS)
    assert b6["4"]["n"] == N_TRUTH and b6["4"]["nan_excluded"] == 0
    # B9's matched state is the empty set below the route's size: 0 units and R = 0.
    assert curves["B9"]["3"]["realised_units"] == 0.0
    assert curves["B9"]["3"]["R_mean"] == 0.0


def test_B6s_smallest_sufficient_budgets(summary):
    reaching = summary["verification"][NET_C][an.U2]["B6_smallest_budget_reaching"]
    # 0.27, 0.5, 0.75, 0.9: the first at or above 0.5 is k = 2, and above 0.9 is k = 4.
    assert reaching["R_ge_0.5"] == "2"
    assert reaching["R_ge_0.9"] == "4"
    # U3's curve is 0.2, 0.3, 0.4, 0.5, 1.0: 0.5 is first reached at k = 4 and 0.9 at "all".
    u3 = summary["verification"][NET_C]["U3"]["B6_smallest_budget_reaching"]
    assert u3["R_ge_0.5"] == "4"
    assert u3["R_ge_0.9"] == an.BUDGET_ALL


def test_h4s_smallest_set_and_named_candidates(summary):
    h4 = summary["verification"][NET_C][an.U2]["h4"]
    assert h4["available"] is True
    assert h4["smallest"] == {
        "size": 3,
        "columns": [0, 1, 2],
        "draw_share": 0.96,
        "source": "exhaustive",
    }
    assert [candidate["source"] for candidate in h4["named_candidates"]] == ["B8P"]
    assert h4["named_candidates"][0]["size"] == 4
    assert h4["named_candidates"][0]["draw_share"] == 1.0
    assert h4["named_candidates"][0]["qualifies"] is True
    # A model without a pool records the absence rather than an empty set.
    assert summary["verification"][NET_C]["U3"]["h4"] == {"available": False}


def test_complementarity_is_the_single_unit_sum_against_the_joint_value(summary):
    block = summary["complementarity"][NET_C]
    assert list(summary["complementarity"]) == [NET_C]
    assert block["model"] == an.U2
    assert block["n_pool_units"] == POOL_UNITS
    assert block["sum_single_unit_VoI_E_MWh"] == 8.0
    assert block["joint_value_MWh"] == 40.0
    assert block["ratio_sum_over_joint"] == pytest.approx(0.2)


def test_b9_granularity_reads_the_budget_matching_rule(summary):
    block = summary["b9_granularity"][NET_C]
    assert block["realised_units_per_budget"] == {
        "1": 0.0,
        "2": 0.0,
        "3": 0.0,
        "4": 4.0,
        "all": 5.0,
    }
    assert block["smallest_budget_with_a_realised_unit"] == "4"
    # The matching rule never picks a state above its budget, so this is null by construction.
    assert block["smallest_budget_where_units_exceed_the_budget"] is None
    assert "budget-matching rule at work, not a termination" in block["note"]


def test_b9_granularity_would_name_a_budget_a_state_overshot(tree, monkeypatch):
    """The field is null on the real shape; this checks it is computed, not hard-coded."""
    root = build_tree(tree / "overshoot")
    overshot = dict(B9_UNITS) | {"2": 3.0}
    record = _netc_u2(b9_units=overshot)
    (root / "results" / f"eval_{NET_C}_{an.U2}.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n"
    )
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    block = an.build_summary().summary["b9_granularity"][NET_C]
    assert block["smallest_budget_where_units_exceed_the_budget"] == "2"


def test_controls_D_and_E_are_read_at_their_own_key_paths(summary):
    block = summary["controls_D_E"]
    assert block["D"]["network"] == NET_C
    assert block["D"]["max_abs_diff"] == {"res_bus.vm_pu": 0.0, "res_line.i_ka": 0.0}
    changes = block["D"]["loading_percent_changes_as_expected"]
    assert changes["max_abs_diff"] == 32.0
    assert changes["max_rel_diff"] == 0.2
    assert changes["within_tolerance"] is True
    assert list(block["E"]) == [NET_C, NET_T]
    cable = block["E"][NET_C]
    assert cable["share_invisible"] == 0.05
    assert cable["share_of_true_over_that_is_invisible"] == 0.6
    assert cable["vm_abs_delta_all_buses"]["p95"] == 0.002
    assert cable["vm_abs_delta_all_buses"]["max"] == 0.008
    assert cable["vm_abs_delta_all_buses"]["unit"] == "p.u."
    assert cable["alignment_pass"] is True


def test_the_summary_reports_no_simbench_parameter_value(summary):
    text = json.dumps(summary, sort_keys=True)
    an.assert_no_simbench_parameters(text, [I_KA_MODIFIED, I_KA_RECORD], "the summary")
    assert STD_TYPE not in text
    assert "std_type" not in text
    # The quantity *name* is reported; its value is not.
    assert "res_line.i_ka" in text


# --- (b) write-once ---------------------------------------------------------------------------


def test_the_summary_and_the_figures_are_written_once(tree):
    assert an.command_summarise(dry_run=False) == 0
    path = an.summary_path()
    assert path.exists()
    written = sorted(p.name for p in (tree / "figures").glob("*.svg"))
    assert len(written) == 6
    with pytest.raises(FileExistsError, match="written once"):
        an.command_summarise(dry_run=False)
    # The second attempt changed nothing.
    assert sorted(p.name for p in (tree / "figures").glob("*.svg")) == written


def test_the_written_artefacts_are_the_eleven_summary_blocks_and_six_figures(tree):
    assert an.main(["summarise"]) == 0
    written = json.loads(an.summary_path().read_text())
    assert set(written) == {
        "command",
        "status",
        "provenance",
        "decision_relevance",
        "verification",
        "u2_prime",
        "complementarity",
        "verdicts",
        "a4_corrections",
        "fragility_a5",
        "b9_granularity",
        "controls_D_E",
        "disclosure",
    }
    for path in sorted((tree / "figures").glob("*.svg")):
        text = path.read_text()
        ET.fromstring(text)
        assert an.ATTRIBUTION_NOTICE in _drawn_text(text), path.name


def test_a_dry_run_writes_nothing(tree, capsys):
    assert an.command_summarise(dry_run=True) == 0
    assert not an.summary_path().exists()
    assert not (tree / "figures").exists()
    assert "decision_relevance" in capsys.readouterr().out


def test_a_figure_is_never_rewritten(tree):
    figures = tree / "figures"
    figures.mkdir()
    (figures / "fig_a_decision_relevance.svg").write_text("<svg/>")
    with pytest.raises(FileExistsError, match="written once"):
        an.command_summarise(dry_run=False)


# --- (c) the code-hash mismatch --------------------------------------------------------------


def test_an_evaluation_from_other_code_fails_loudly(tmp_path, monkeypatch):
    wrong = {"ratings_core.py": "0" * 64, "run_stage_a.py": "1" * 64}
    root = build_tree(tmp_path, eval_code=wrong)
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    with pytest.raises(ValueError, match="do not record the frozen evaluation code"):
        an.build_summary()


def test_the_mismatch_message_names_the_offending_artefact(tmp_path, monkeypatch):
    wrong = {"ratings_core.py": "0" * 64, "run_stage_a.py": "1" * 64}
    root = build_tree(tmp_path, eval_code=wrong)
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    with pytest.raises(ValueError) as caught:
        an.build_summary()
    assert f"results/eval_{NET_C}_{an.U2}.json" in str(caught.value)


def test_a_record_naming_another_combination_is_refused(tree):
    path = tree / "results" / f"eval_{NET_C}_{an.U2}.json"
    record = json.loads(path.read_text())
    record["network"] = "somewhere-else"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="but the record says"):
        an.load_study()


# --- (d) U2', the misspecification check ------------------------------------------------------


def test_u2_prime_counts_the_draws_whose_denominator_collapses(summary):
    block = summary["u2_prime"][NET_C]
    counts = block["per_draw_denominator"]
    assert counts["n_draws"] == len(U2P_B2_PER_DRAW)
    # oracle - B2 per draw: 0, -1, -2, 0.5, 0.4, 10, 20, 30, 40, 50.
    assert counts["oracle_minus_B2_le_0"] == 3
    assert counts["oracle_minus_B2_under_1pct_of_oracle"] == 2
    assert counts["small_gap_share_of_oracle"] == 0.01
    assert f"runs/eval_{NET_C}_{an.U2_PRIME}.npz" in counts["source"]


def test_u2_prime_reports_B2s_and_B3s_unsafe_statistics(summary):
    block = summary["u2_prime"][NET_C]
    assert block["model"] == an.U2_PRIME
    assert block["B2_unsafe"]["share_draws_ge1"] == 0.4
    assert block["B2_unsafe"]["unsafe_step_share"] == 0.006
    assert block["B3_unsafe"]["share_draws_ge1"] == 0.5
    assert block["B2_severity_pct"]["p95"] == -1.0


def test_u2_prime_is_read_at_k4_per_policy(summary):
    at_k4 = summary["u2_prime"][NET_C]["at_k4"]
    assert at_k4["B6"]["budget"] == "4"
    assert at_k4["B6"]["export_MWh_mean"] == 95.0
    assert at_k4["B6"]["unsafe_draw_share"] == 0.3
    # A reference policy has no budget, so it enters at "na".
    assert at_k4["B2"]["budget"] == "na"
    assert at_k4["B2"]["export_MWh_mean"] == B2_C_U2P
    assert at_k4["B2"]["unsafe_draw_share"] == 0.4


def test_u2_prime_ratio_of_means_is_labelled_as_descriptive(summary):
    block = summary["u2_prime"][NET_C]
    assert block["ratio_of_means_label"] == "descriptive; not the protocol's per-draw R"
    ratio = block["ratio_of_means_recovery"]
    # (mean export - 90) / (100 - 90).
    assert ratio["B6"] == pytest.approx(0.5)
    assert ratio["B8P"] == pytest.approx(0.2)
    assert ratio["B9"] == pytest.approx(0.0)
    assert ratio["B2"] == pytest.approx(0.0)
    assert ratio["B4"] == pytest.approx(1.0)
    assert "unstable" in block["note"]
    assert "w = 0.3" in block["note"] and "w = 0.2" in block["note"]


# --- (e) the verdicts, verbatim ---------------------------------------------------------------


def test_every_verdict_string_is_copied_verbatim_with_its_key_path(summary):
    verdicts = summary["verdicts"]
    assert verdicts["H1.verdict"] == VERDICT_H1
    assert verdicts["H2.verdict"] == VERDICT_H2
    assert verdicts["H3.H3a.verdict"] == VERDICT_H3A
    assert verdicts["H3.H3b.verdict"] == VERDICT_H3B
    assert verdicts["H3.H3c.verdict"] == VERDICT_H3C
    assert verdicts["H3.H5.verdict"] == VERDICT_H5
    assert verdicts["H5.verdict"] == VERDICT_H5
    assert verdicts[f"H4.per_network.{NET_C}.verdict"] == VERDICT_H4_C
    assert verdicts[f"H4.per_network.{NET_T}.verdict"] == VERDICT_H4_T


def test_the_control_pass_stop_conditions_and_missing_combinations_are_copied(summary, tree):
    written = json.loads((tree / "results" / "verdicts.json").read_text())
    verdicts = summary["verdicts"]
    assert verdicts["control_pass"] == written["control_pass"]
    assert verdicts["control_pass"]["D"] is None
    assert verdicts["stop_conditions"] == written["stop_conditions"]
    assert verdicts["combinations_missing"] == []


# --- (f) the figures --------------------------------------------------------------------------


def _drawn_text(svg_text: str) -> str:
    root = ET.fromstring(svg_text)
    return " ".join(node.text or "" for node in root.findall(f".//{SVG_NS}text"))


@pytest.fixture
def figures(tree):
    return an.build_figures(an.build_summary())


def test_six_figures_are_built_with_the_protocols_names(figures):
    assert [name for name, _ in figures] == [
        "fig_a_decision_relevance.svg",
        "fig_b_verification_curves.svg",
        "fig_c_safety_utilisation.svg",
        "fig_d_complementarity.svg",
        "fig_e_model_sensitivity.svg",
        "fig_f_controls_d_e.svg",
    ]


def test_every_figure_parses_as_xml_and_has_a_title_and_a_description(figures):
    for name, text in figures:
        root = ET.fromstring(text)  # raises on malformed XML
        title = root.find(f"{SVG_NS}title")
        desc = root.find(f"{SVG_NS}desc")
        assert title is not None and title.text, name
        assert desc is not None and desc.text, name
        # One sentence at least, and the source named, as svgplot's `desc` convention wants.
        assert "Source:" in desc.text, name
        assert "n = " in desc.text, name


def test_every_figure_carries_the_mission_12_notice(figures):
    for name, text in figures:
        desc = ET.fromstring(text).find(f"{SVG_NS}desc")
        assert desc.text.endswith(an.ATTRIBUTION_NOTICE), name
        assert desc.text != an.ATTRIBUTION_NOTICE, name  # appended, not substituted
        assert an.ATTRIBUTION_NOTICE in _drawn_text(text), name


def test_no_figure_carries_a_simbench_parameter_value(figures):
    for name, text in figures:
        assert STD_TYPE not in text, name
        assert "std_type" not in text, name
        an.assert_no_simbench_parameters(text, [I_KA_MODIFIED, I_KA_RECORD], name)


def test_the_parameter_guard_catches_a_planted_value_and_a_planted_name():
    with pytest.raises(ValueError, match="forbidden rating value"):
        an.assert_no_simbench_parameters("the rating is 0.1234 kA", [I_KA_MODIFIED], "test")
    with pytest.raises(ValueError, match="forbidden token"):
        an.assert_no_simbench_parameters(f"std_type {STD_TYPE}", [], "test")
    # A longer number that merely starts with the value is not a match.
    an.assert_no_simbench_parameters("0.12345678", [I_KA_MODIFIED], "test")
    an.assert_no_simbench_parameters("res_line.i_ka moved by 0.0", [I_KA_MODIFIED], "test")
    # A value past six significant digits is caught by its full repr, not only by "%g".
    with pytest.raises(ValueError, match="forbidden rating value"):
        an.assert_no_simbench_parameters("rating 0.12345678", [0.12345678], "test")


def test_figure_b_notes_that_B7_and_B8_coincide_with_B6(figures):
    text = dict(figures)["fig_b_verification_curves.svg"]
    desc = ET.fromstring(text).find(f"{SVG_NS}desc").text
    assert "B7 and B8" in desc and "coincide with B6" in desc
    drawn = _drawn_text(text)
    assert "B6 (loading rank; B7 and B8 identical)" in drawn
    assert "B7 (" not in drawn and "B8 (" not in drawn


def test_figure_e_draws_U4s_single_route_unit(figures):
    drawn = _drawn_text(dict(figures)["fig_e_model_sensitivity.svg"])
    assert "U4 (one route unit, at its realised count)" in drawn
    assert f"{POOL_UNITS} segments" in drawn


def test_figure_f_draws_control_Ds_zero_against_control_Es_change(figures):
    drawn = _drawn_text(dict(figures)["fig_f_controls_d_e.svg"])
    assert "Control D, max |dvm| and |dI| (exactly 0)" in drawn
    assert "Control E, |dvm| p95" in drawn


# --- (g) OB beyond its searched budget ---------------------------------------------------------


def test_OB_is_reported_at_k_le_3_only(summary):
    curves = summary["verification"][NET_C][an.U2]["R"]
    assert an.budget_order(curves["OB"]) == ["1", "2", "3"]
    assert summary["verification"][NET_C][an.U2]["OB_searched_kmax"] == OB_SEARCHED_KMAX
    # Every other budgeted policy keeps its full budget list, "all" included.
    assert an.budget_order(curves["B6"]) == ["1", "2", "3", "4", "all"]


def test_OB_is_omitted_where_it_was_not_searched(summary):
    # U2w3, U3 and U4 carry `ob.available = false` and no OB policy in the fixture.
    for model in (an.U2_W3, "U3", "U4"):
        block = summary["verification"][NET_C][model]
        assert "OB" not in block["R"]
        assert block["OB_searched_kmax"] is None
        assert block["omitted_policies"] == {}


def test_a_policy_dropped_for_want_of_a_searched_budget_is_disclosed(tree, monkeypatch):
    """A cap on the read-out is recorded, never silent."""
    root = build_tree(tree / "unsearched")
    path = root / "results" / f"eval_{NET_C}_{an.U2}.json"
    record = json.loads(path.read_text())
    record["ob"] = {"available": False}
    path.write_text(json.dumps(record, indent=2, sort_keys=True))
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    block = an.build_summary().summary["verification"][NET_C][an.U2]
    assert "OB" not in block["R"]
    assert "no searched budget" in block["omitted_policies"]["OB"]


def test_OBs_k4_cell_is_left_out_of_the_u2_prime_read_out(summary):
    """Amendment A3: above k = 3 OB carries its k = 3 set, so k = 4 is not its own result."""
    at_k4 = summary["u2_prime"][NET_C]["at_k4"]
    assert "OB" not in at_k4
    assert "OB" not in summary["u2_prime"][NET_C]["ratio_of_means_recovery"]
    assert set(at_k4) == {"B0", "B1", "B2", "B3", "B4", "B5", "B6", "B8P", "B9"}


def test_figure_b_stops_OBs_curve_at_its_searched_budget(figures):
    text = dict(figures)["fig_b_verification_curves.svg"]
    assert "OB (ex-post best, k <= 3)" in _drawn_text(text)
    assert "amendment A3" in ET.fromstring(text).find(f"{SVG_NS}desc").text


# --- (h) amendment A4 ------------------------------------------------------------------------


def test_control_D_is_read_from_rating_only_change(summary):
    block = summary["a4_corrections"]["control_D"]
    assert block["read_at"] == "rating_only_change.pass"
    assert block["pass"] is True
    assert block["verdicts_json_controls_D_pass"] is None
    assert "a key that does not exist" in block["why_null"]
    assert "amendment A4" in block["cites"]
    assert [comparison["quantity"] for comparison in block["comparisons"]] == [
        "res_bus.vm_pu",
        "res_line.i_ka",
    ]
    assert all(comparison["max_abs_diff"] == 0.0 for comparison in block["comparisons"])
    assert all(comparison["within_tolerance"] for comparison in block["comparisons"])


def test_h3a_fragility_is_computed_at_its_boundary(summary):
    block = summary["a4_corrections"]["H3a_fragility"]
    assert block["network"] == NET_C
    assert block["policies_at_the_maximum"] == ["B6", "B7"]
    assert block["max_R1"] == H3A_MAX
    assert block["threshold"] == 0.25
    assert block["margin"] == pytest.approx(0.02)
    assert block["se"] == H3A_SE
    assert block["two_se"] == pytest.approx(0.04)
    # 0.02 < 2 x 0.02, so the REJECTED verdict is fragile (protocol s. 9).
    assert block["fragile"] is True
    assert block["verdict_in_verdicts_json"] == VERDICT_H3A
    assert block["flagged_fragile_in_verdicts_json"] is False
    assert block["matches_verdicts_max_R1"] is True
    assert block["eval_record_cross_check"]["R_mean"] == H3A_MAX
    assert block["eval_record_cross_check"]["R_se"] == H3A_SE
    assert "amendment A4" in block["cites"]


@pytest.mark.parametrize(
    ("se", "expected"),
    [
        (0.0101, True),  # 2 x SE = 0.0202, just above the 0.0200 margin
        (0.0099, False),  # 2 x SE = 0.0198, just below it
    ],
)
def test_the_fragile_flag_turns_over_at_two_standard_errors(tmp_path, monkeypatch, se, expected):
    root = build_tree(tmp_path, h3a_se=se)
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    block = an.build_summary().summary["a4_corrections"]["H3a_fragility"]
    assert block["se"] == se
    assert block["two_se"] == pytest.approx(2.0 * se)
    assert block["fragile"] is expected


# --- (i) amendment A5: the energy-weighted recovery -------------------------------------------


def test_the_energy_weighted_recovery_is_a_ratio_of_means_not_a_mean_of_ratios(summary):
    b6 = summary["verification"][NET_C][an.U2]["R"]["B6"]
    for budget, expected in B6_ENERGY_WEIGHTED.items():
        assert b6[budget]["recovery_energy_weighted"] == pytest.approx(expected), budget
        assert b6[budget]["export_MWh_mean"] == B6_EXPORT[budget], budget
    # The two statistics genuinely differ on this cell: 0.82 against R = 0.9 at k = 4.
    assert b6["4"]["recovery_energy_weighted"] == pytest.approx(0.82)
    assert b6["4"]["R_mean"] == B6_R["4"] == 0.9


def test_B6s_smallest_sufficient_budgets_are_reported_for_both_statistics(summary):
    block = summary["verification"][NET_C][an.U2]
    assert block["B6_smallest_budget_reaching"] == {"R_ge_0.5": "2", "R_ge_0.9": "4"}
    # 0.1, 0.4, 0.75, 0.82, 1.0: the first at or above 0.5 is k = 3 and above 0.9 is "all".
    assert block["B6_smallest_budget_reaching_energy_weighted"] == {
        "energy_weighted_ge_0.5": "3",
        "energy_weighted_ge_0.9": an.BUDGET_ALL,
    }


def test_the_energy_weighted_recovery_is_labelled_as_secondary(summary):
    verification = summary["verification"][NET_C]
    assert verification[an.U2]["recovery_energy_weighted_label"] == (
        "secondary descriptive statistic (A5); the s. 7 verdict statistic is the mean of "
        "per-draw ratios"
    )
    # Under U2' the per-draw denominator can collapse, so the caveat is carried as well.
    u2p = verification[an.U2_PRIME]["recovery_energy_weighted_label"]
    assert u2p.endswith("descriptive; the denominator can be <= 0 per draw")


# --- (j) amendment A5: the fragility block -----------------------------------------------------


def test_the_fragility_block_states_that_no_verdict_changes(summary):
    block = summary["fragility_a5"]
    assert block["no_verdict_changes"] == "no verdict changes"
    assert "amendment A5" in block["amendment"] and "AKK-87" in block["amendment"]
    assert "post-verdict" in block["post_verdict"]
    assert "2 x the Monte-Carlo standard error" in block["rule"]


def test_h5c_fragility_takes_the_margin_over_the_half_recovery_threshold(summary):
    block = summary["fragility_a5"]["H5c"]
    cable = block["per_network"][NET_C]
    assert cable["R"] == B6_R["4"] and cable["se"] == H5C_SE
    assert cable["threshold"] == 0.5
    assert cable["margin"] == pytest.approx(0.4)
    assert cable["two_se"] == pytest.approx(0.04)
    assert cable["fragile"] is False
    assert cable["fragile_in_verdicts_json"] is False
    assert block["fragile_networks"] == []
    assert list(block["per_network"]) == [NET_C]


@pytest.mark.parametrize(
    ("se", "expected"),
    [
        (0.21, True),  # 2 x SE = 0.42, just above the 0.40 margin
        (0.19, False),  # 2 x SE = 0.38, just below it
    ],
)
def test_h5c_fragility_turns_over_at_two_standard_errors(tmp_path, monkeypatch, se, expected):
    root = build_tree(tmp_path, h5c_se=se)
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    block = an.build_summary().summary["fragility_a5"]["H5c"]
    assert block["per_network"][NET_C]["fragile"] is expected
    assert block["fragile_networks"] == ([NET_C] if expected else [])


def test_h4_fragility_uses_the_binomial_standard_error_of_the_draw_share(summary):
    block = summary["fragility_a5"]["H4"]
    assert block["models"] == [an.U2, "U4"]
    u2 = block["per_network"][NET_C][an.U2]
    assert u2["draw_share"] == H4_DRAW_SHARE_U2
    assert u2["threshold"] == 0.95
    assert u2["n_draws"] == N_TRUTH
    # sqrt(0.96 x 0.04 / 200) = 0.0138564..., so 2 x SE = 0.0277 against a margin of 0.01.
    assert u2["se"] == pytest.approx((0.96 * 0.04 / 200) ** 0.5)
    assert u2["margin"] == pytest.approx(0.01)
    assert u2["fragile"] is True
    # A share of exactly 1.0 has no sampling variation, so a 0.05 margin cannot be fragile.
    u4 = block["per_network"][NET_C]["U4"]
    assert u4["draw_share"] == 1.0 and u4["se"] == 0.0
    assert u4["margin"] == pytest.approx(0.05)
    assert u4["fragile"] is False
    assert block["fragile_network_models"] == [f"{NET_C}/{an.U2}"]
    assert "sqrt(p (1 - p) / n)" in block["se_definition"]


def test_h4_fragility_records_a_model_with_no_sufficient_set(tree, monkeypatch):
    """A rejected H4 has no draw share, so the absence is stated rather than dropped."""
    root = build_tree(tree / "no_set")
    path = root / "results" / "verdicts.json"
    verdicts = json.loads(path.read_text())
    verdicts["H4"]["per_network"][NET_C]["U4"]["smallest"] = None
    verdicts["H4"]["per_network"][NET_C]["U4"]["rejected"] = True
    path.write_text(json.dumps(verdicts, indent=2, sort_keys=True))
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    u4 = an.build_summary().summary["fragility_a5"]["H4"]["per_network"][NET_C]["U4"]
    assert u4["smallest_exists"] is False
    assert u4["rejected"] is True
    assert "no sufficient set of size <= 6" in u4["why"]


def test_h3b_fragility_pairs_the_per_draw_recoveries(summary):
    block = summary["fragility_a5"]["H3b"]
    cable = block["per_network"][NET_C]
    assert cable["compared"] == {
        "higher_arm": {"policy": "B8P", "budget": H3B_BUDGET},
        "lower_arm": {"policy": "B6", "budget": H3B_BUDGET},
    }
    assert cable["n_draws_used"] == U2_DRAWS_USED
    assert cable["n_draws_excluded_zero_denominator"] == U2_DRAWS_EXCLUDED
    assert cable["paired_mean"] == pytest.approx(H3B_GAP)
    assert cable["gap_in_verdicts_json"] == H3B_GAP
    assert cable["gap_matches_paired_mean"] is True
    # std(ddof=1) = sqrt(0.1 / 9), so SE = sqrt(0.1 / 9) / sqrt(10) = 1 / 30.
    assert cable["paired_se"] == pytest.approx(H3B_PAIRED_SE)
    assert cable["two_paired_se"] == pytest.approx(2.0 / 30.0)
    # REJECTED, so the margin is the rejection threshold minus the gap: 0.05 - 0.0.
    assert cable["threshold"] == 0.05
    assert cable["margin"] == pytest.approx(0.05)
    assert cable["margin_definition"] == "rejection threshold - gap"
    assert cable["fragile_paired"] is True
    assert block["fragile_networks_paired"] == [NET_C]


def test_h3b_keeps_the_verdicts_json_flags_and_labels_them_conservative(summary):
    block = summary["fragility_a5"]["H3b"]
    assert block["verdict_in_verdicts_json"] == VERDICT_H3B
    assert block["per_network"][NET_C]["fragile_in_verdicts_json"] is False
    assert block["fragile_networks_in_verdicts_json"] == []
    assert block["verdicts_json_se_label"] == "conservative: summed marginal SEs"


def test_h3c_fragility_is_not_fragile_where_the_arms_differ_by_a_constant(summary):
    block = summary["fragility_a5"]["H3c"]
    cable = block["per_network"][NET_C]
    assert cable["compared"]["higher_arm"] == {"policy": "B6", "budget": an.K_FOUR}
    assert cable["compared"]["lower_arm"] == {"policy": "B5", "budget": an.K_FOUR}
    assert cable["paired_mean"] == pytest.approx(H3C_GAP)
    assert cable["paired_se"] == 0.0
    # SUPPORTED, so the margin is the gap minus the support threshold: 0.5 - 0.2.
    assert cable["threshold"] == 0.2
    assert cable["margin"] == pytest.approx(0.3)
    assert cable["margin_definition"] == "gap - support threshold"
    assert cable["fragile_paired"] is False
    assert block["fragile_networks_paired"] == []


def test_the_per_draw_recovery_excludes_a_zero_denominator_draw(tree):
    study = an.load_study()
    recovery = an.per_draw_recovery(study.u2_draws[NET_C], "B6", H3B_BUDGET)
    assert recovery.size == len(U2_B2_PER_DRAW)
    assert int(np.count_nonzero(~np.isfinite(recovery))) == U2_DRAWS_EXCLUDED
    assert recovery[0] == pytest.approx(0.5)


def test_a_missing_u2_npz_fails_loudly(tree):
    (tree / "runs" / f"eval_{NET_C}_{an.U2}.npz").unlink()
    with pytest.raises(FileNotFoundError, match="paired standard errors"):
        an.load_study()


# --- (k) amendment A5: the disclosures ---------------------------------------------------------


def test_disclosure_a_counts_the_positive_worst_case_VoI_records(summary):
    block = summary["disclosure"]["a_VoI_worst_case"]
    # One pool unit per cable-limited evaluation carries a positive single-unit VoI_E, so its
    # 100-sample minimum is positive too. netT's models have no pool and no voi records.
    assert block["per_model"][an.U2] == {
        "evaluations": 2,
        "unit_records": POOL_UNITS,
        "unit_records_with_a_positive_worst_case": 1,
        "unit_period_records": 2 * POOL_UNITS,
        "unit_period_records_with_a_positive_worst_case": 1,
    }
    assert block["per_model"][an.TRAFO_MODEL]["unit_records"] == 0
    assert block["totals"] == {
        "evaluations": 7,
        "unit_records": 21,
        "unit_records_with_a_positive_worst_case": 5,
        "unit_period_records": 42,
        "unit_period_records_with_a_positive_worst_case": 5,
    }
    assert "minimum over 100 prior samples" in block["text"]
    assert "not the infimum over Theta" in block["text"]


def test_disclosure_b_counts_control_Gs_three_non_pool_columns(summary):
    block = summary["disclosure"]["b_control_G_coverage"]
    assert block["evaluated_counts_observed"] == [CONTROL_G_EVALUATED]
    entry = block["per_combination"][f"{NET_C}/{an.U2}"]
    assert entry["non_pool_table_columns_evaluated"] == 1
    assert entry["non_table_lines_evaluated"] == 2
    assert entry["evaluated"] == CONTROL_G_EVALUATED
    assert entry["zero_value_candidates"] == CONTROL_G_ZERO_VALUE_CANDIDATES
    assert "CONTROL_G_LINES = 3" in block["text"]
    assert "covered by the pool certificate" in block["text"]


def test_disclosure_c_recomputes_s_10s_847_enumerated_subsets(summary):
    block = summary["disclosure"]["c_H4_scored_counts"]
    assert block["enumerated_subsets_in_s_10"] == 847
    assert block["largest_subsets_scored"] == H4_SUBSETS_SCORED_U2
    assert block["per_combination"][f"{NET_C}/{an.U2}"]["named_candidate_sources"] == [
        "B8P",
        "B9-static",
        "B9",
    ]
    assert "the empty set and the named B8P / B9-static / B9 candidates" in block["text"]
    assert "847" in block["text"] and str(H4_SUBSETS_SCORED_U2) in block["text"]


def test_disclosure_d_names_control_Ds_cap_level(summary):
    block = summary["disclosure"]["d_control_D_cap_level"]
    assert block["cap_level_index"] == 0
    assert block["cap_level"] == 1.0
    assert "cap level index 0 (c = 1.0, uncapped)" in block["text"]


def test_disclosures_e_f_and_h_are_stated(summary):
    disclosure = summary["disclosure"]
    assert "temporal transfer only" in disclosure["e_P_E_split"]
    assert "one rho per draw applies to both" in disclosure["e_P_E_split"]
    assert (
        "no multiple-comparison adjustment is made or claimed"
        in disclosure["f_multiple_comparisons"]
    )
    assert (
        "A1-A3 were made before results/verdicts.json existed" in disclosure["h_amendment_timing"]
    )
    assert "A4 and A5 are post-verdict and disclosure only" in disclosure["h_amendment_timing"]
    assert "no SimBench parameter value" in disclosure["no_simbench_parameter_value"]


def test_disclosure_g_verifies_H3bs_per_budget_gaps_from_verdicts_json(summary):
    block = summary["disclosure"]["g_H3b_min_over_k"]
    assert block["rejection_threshold"] == 0.05
    assert block["largest_gap_over_networks_and_budgets"] == 0.0
    assert block["never_exceeds_zero"] is True
    cable = block["per_network"][NET_C]
    assert cable["gap_per_budget"] == {"2": 0.0, "3": 0.0, "4": 0.0}
    assert cable["largest_gap"] == 0.0
    assert cable["rejected_at_every_budget"] is True
    assert "REJECTED at every budget individually" in block["text"]


def test_disclosure_g_would_name_a_budget_whose_gap_is_positive(tree, monkeypatch):
    """The claim is computed from `verdicts.json`, not asserted."""
    root = build_tree(tree / "positive_gap")
    path = root / "results" / "verdicts.json"
    verdicts = json.loads(path.read_text())
    verdicts["H3"]["per_network"][NET_C]["H3b"]["per_budget"]["4"]["gap"] = 0.3
    path.write_text(json.dumps(verdicts, indent=2, sort_keys=True))
    monkeypatch.setattr(an, "RESULTS", root / "results")
    monkeypatch.setattr(an, "RUNS", root / "runs")
    block = an.build_summary().summary["disclosure"]["g_H3b_min_over_k"]
    assert block["largest_gap_over_networks_and_budgets"] == 0.3
    assert block["never_exceeds_zero"] is False
    assert block["per_network"][NET_C]["rejected_at_every_budget"] is False


# --- (l) amendment A5: the notice override and the figure corrections -------------------------


def test_the_notice_global_is_restored_after_summarise(tree):
    before = svgplot.ATTRIBUTION_NOTICE
    assert an.command_summarise(dry_run=False) == 0
    assert svgplot.ATTRIBUTION_NOTICE == before
    written = sorted((tree / "figures").glob("*.svg"))
    assert len(written) == 6
    for path in written:
        assert an.ATTRIBUTION_NOTICE in _drawn_text(path.read_text()), path.name


def test_the_notice_global_is_restored_even_when_a_figure_raises(tree, monkeypatch):
    before = svgplot.ATTRIBUTION_NOTICE
    monkeypatch.setattr(an, "FIGURE_BUILDERS", (_exploding_figure,))
    with pytest.raises(RuntimeError, match="planted"):
        an.build_figures(an.build_summary())
    assert svgplot.ATTRIBUTION_NOTICE == before


def _exploding_figure(study):
    raise RuntimeError("planted failure inside the figure writer")


def _polyline_point_counts(svg_text: str) -> list[int]:
    root = ET.fromstring(svg_text)
    return sorted(len(node.get("points").split()) for node in root.findall(f".//{SVG_NS}polyline"))


def test_figure_b_draws_the_full_pool_as_an_isolated_marker(figures, tree):
    text = dict(figures)["fig_b_verification_curves.svg"]
    # Per panel: B5, B6, B8P and B9 over the four numeric budgets, and OB over three. The
    # "all" cell is never a fifth point on any polyline.
    assert _polyline_point_counts(text) == [3, 3, 4, 4, 4, 4, 4, 4, 4, 4]
    _, figure = an.figure_b(an.build_summary())
    isolated = [
        series
        for panel in figure.panels
        for series in panel.series
        if series.kind == "marker" and not series.label
    ]
    assert len(isolated) == 8  # four policies with an "all" cell, in each of the two rows
    assert all(len(series.x) == 1 for series in isolated)
    assert {series.x[0] for series in isolated} == {float(POOL_UNITS)}
    desc = ET.fromstring(text).find(f"{SVG_NS}desc").text
    assert "The marker at the full pool is not connected" in desc
    assert "no budget between the last k and the full pool was scored" in desc


def test_figure_b_carries_the_corrected_policy_labels(figures):
    drawn = _drawn_text(dict(figures)["fig_b_verification_curves.svg"])
    for label in (
        "B6 (loading rank; B7 and B8 identical)",
        "B8P (VoI greedy, pair look-ahead)",
        "B9 (route rule)",
        "B5 (random)",
        "OB (ex-post best, k <= 3)",
    ):
        assert label in drawn, label


def test_figure_b_has_a_second_row_of_energy_weighted_panels(figures):
    _, figure = an.figure_b(an.build_summary())
    titles = [panel.title for panel in figure.panels]
    assert titles == [f"{NET_C} (U2): per-draw recovery", f"{NET_C} (U2): energy-weighted recovery"]
    assert figure.nrows == 2
    drawn = _drawn_text(dict(figures)["fig_b_verification_curves.svg"])
    assert "energy-weighted recovered share" in drawn
    desc = ET.fromstring(dict(figures)["fig_b_verification_curves.svg"]).find(f"{SVG_NS}desc").text
    assert "Top row: s. 7's per-draw recovery (the verdict statistic)" in desc
    assert "Bottom row: the energy-weighted recovery (A5, descriptive)" in desc


def test_figure_b_never_clips_a_recovery_value(figures):
    _, figure = an.figure_b(an.build_summary())
    for panel in figure.panels:
        low, high = panel.limits("y")
        for series in panel.series:
            for value in series.y:
                if value == value:
                    assert low <= value <= high


def test_figure_d_is_a_log_axis_with_the_ratio_printed(figures):
    text = dict(figures)["fig_d_complementarity.svg"]
    _, figure = an.figure_d(an.build_summary())
    panel = figure.panels[0]
    assert panel.ylog is True
    assert panel.ylabel == "MWh (logarithmic)"
    assert [series.label for series in panel.series] == [
        "sum of the single-unit VoI_E",
        "joint value: oracle - B2 on E",
    ]
    # The fixture's sum is 8.0 against a joint value of 40.0, i.e. a ratio of 0.2.
    drawn = _drawn_text(text)
    assert "sum / joint = 0.2" in drawn
    assert NET_C in drawn
    # No y = x reference line survives the correction.
    assert panel.hlines == []
    assert "logarithmic" in ET.fromstring(text).find(f"{SVG_NS}desc").text


# --- the loader's loud failures ---------------------------------------------------------------


def test_a_missing_verdicts_file_fails_loudly(tree):
    (tree / "results" / "verdicts.json").unlink()
    with pytest.raises(FileNotFoundError, match="verdicts.json"):
        an.load_study()


def test_a_missing_u2_prime_npz_fails_loudly(tree):
    (tree / "runs" / f"eval_{NET_C}_{an.U2_PRIME}.npz").unlink()
    with pytest.raises(FileNotFoundError, match="per-draw arrays"):
        an.load_study()


def test_an_empty_results_directory_fails_loudly(tmp_path, monkeypatch):
    monkeypatch.setattr(an, "RESULTS", tmp_path)
    with pytest.raises(FileNotFoundError, match="no eval_"):
        an.load_study()


# --- figure D's wording, computed from the ratios --------------------------------------------


def test_figure_ds_description_states_the_multiple_from_the_fixtures_ratio(tree):
    """The fixture's one cable-limited network has sum = 8.0 and joint = 40.0, i.e. a ratio of
    0.2 and a multiple of 5. Both the sentence and the docstring are checked, since the old
    claim lived in both."""
    _, figure = an.figure_d(an.build_summary())
    assert "worth about 5 times less than verifying the pool" in figure.desc
    assert f"(sum / joint = 0.2 for {NET_C})" in figure.desc
    assert "orders of magnitude" not in figure.desc
    assert "orders of magnitude" not in an.figure_d.__doc__


def test_the_complementarity_sentence_spans_the_recorded_ratios():
    """The study's three recorded ratios: 1 / 0.074 = 13, 1 / 0.0036 = 280, 1 / 0.0047 = 210,
    each to two significant figures, so the span is 13 to 280."""
    block = {
        "semiurb4": {"ratio_sum_over_joint": 0.07442577228970454},
        "semiurb5": {"ratio_sum_over_joint": 0.0036253695720539283},
        "urban6": {"ratio_sum_over_joint": 0.004736507042088765},
    }
    assert an._complementarity_sentence(block) == (
        "verifying one cable at a time is worth between about 13 and 280 times less than "
        "verifying the pool (sum / joint = 0.074, 0.0036 and 0.0047 for semiurb4, semiurb5 "
        "and urban6)"
    )


def test_a_network_without_a_ratio_is_left_out_of_the_sentence():
    block = {
        "a": {"ratio_sum_over_joint": None},
        "b": {"ratio_sum_over_joint": 0.0},
        "c": {"ratio_sum_over_joint": 0.25},
    }
    sentence = an._complementarity_sentence(block)
    assert sentence == (
        "verifying one cable at a time is worth about 4 times less than verifying the pool "
        "(sum / joint = 0.25 for c)"
    )
    assert an._complementarity_sentence({"a": {"ratio_sum_over_joint": None}}) == (
        "no network here carries a usable sum / joint ratio, so the gap is not sized"
    )


# --- the completeness guard -------------------------------------------------------------------


def test_a_removed_evaluation_is_refused(tree):
    """The board's probe: with one evaluation gone the read-out used to return a smaller
    summary and still report `frozen_code_check.all_match = true`."""
    (tree / "results" / f"eval_{NET_C}_U3.json").unlink()
    with pytest.raises(ValueError, match=f"no evaluation for the scored combination.*{NET_C}/U3"):
        an.load_study()


def test_an_extra_evaluation_is_refused(tree):
    record = json.loads((tree / "results" / f"eval_{NET_C}_U3.json").read_text())
    record["model"] = "U9"
    (tree / "results" / f"eval_{NET_C}_U9.json").write_text(json.dumps(record, sort_keys=True))
    with pytest.raises(ValueError, match=f"{NET_C}/U9 is not in verdicts.json"):
        an.load_study()


def test_a_missing_control_e_is_refused(tree):
    (tree / "results" / f"control_e_{NET_T}.json").unlink()
    with pytest.raises(ValueError, match=f"no control_e_.*json for the network.*{NET_T}"):
        an.load_study()


def test_a_recorded_missing_combination_is_refused(tree):
    path = tree / "results" / "verdicts.json"
    verdicts = json.loads(path.read_text())
    verdicts["combinations_missing"] = [f"{NET_T}/U4"]
    path.write_text(json.dumps(verdicts, indent=2, sort_keys=True))
    with pytest.raises(ValueError, match="combinations_missing"):
        an.load_study()


# --- `verify`: the read-out's own artefact pin ------------------------------------------------


def _write_summary() -> Path:
    """The synthetic tree's summary, written where `summarise` would write it."""
    payload = an.build_summary().summary
    path = an.summary_path()
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=an._json_default) + "\n")
    return path


@pytest.fixture
def pinned(tree, monkeypatch):
    """A synthetic tree with its summary written and the pin pointed at it."""
    path = _write_summary()
    monkeypatch.setattr(an, "PINNED_SUMMARY_SHA256", an.rc.sha256_of(path))
    return path


def _listed(path: Path) -> dict:
    return json.loads(path.read_text())["provenance"]["inputs_sha256"]


def test_verify_passes_on_a_pinned_tree_and_writes_nothing(pinned, tree, capsys):
    before = sorted(str(p) for p in tree.rglob("*"))
    code = an.command_verify()
    out = capsys.readouterr().out
    assert code == 0, out
    count = len(_listed(pinned)) + 1
    assert f"verify: OK ({count} files)" in out
    assert out.count("ok   ") == count  # one line per check
    assert sorted(str(p) for p in tree.rglob("*")) == before


def test_verify_fails_on_a_missing_input(pinned, capsys):
    (an.RESULTS / f"eval_{NET_C}_U3.json").unlink()
    assert an.command_verify() == 1
    assert f"FAIL results/eval_{NET_C}_U3.json: missing" in capsys.readouterr().out


def test_verify_fails_on_a_changed_byte_in_an_input(pinned, capsys):
    """Valid JSON with one number changed: the gap the board's probe found."""
    path = an.RESULTS / f"control_e_{NET_C}.json"
    payload = json.loads(path.read_text())
    payload["invisible_overload"]["share_invisible"] = 0.0501
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    assert an.command_verify() == 1
    assert f"FAIL results/control_e_{NET_C}.json: sha256" in capsys.readouterr().out


def test_verify_fails_on_a_changed_summary(pinned, capsys):
    pinned.write_text(pinned.read_text() + "\n")
    assert an.command_verify() == 1
    assert "is not the pin" in capsys.readouterr().out


def test_verify_fails_on_an_unexpected_extra_evaluation(pinned, capsys):
    record = json.loads((an.RESULTS / f"eval_{NET_C}_U3.json").read_text())
    record["model"] = "U9"
    (an.RESULTS / f"eval_{NET_C}_U9.json").write_text(json.dumps(record, sort_keys=True))
    assert an.command_verify() == 1
    assert "unexpected extra" in capsys.readouterr().out


def test_verify_fails_on_an_unexpected_extra_npz(pinned, capsys):
    """An npz is held to its combination, not to the provenance list: the read-out opens only
    the arrays amendment A5 needs, so most of `runs/` is legitimately unlisted."""
    np.savez_compressed(an.RUNS / f"eval_{NET_C}_U9.npz", **{"B2__na__export": np.zeros(2)})
    assert an.command_verify() == 1
    assert f"runs/eval_{NET_C}_U9.npz has no evaluation" in capsys.readouterr().out


def test_verify_fails_on_a_missing_summary(tree, capsys):
    assert an.command_verify() == 1
    assert "missing" in capsys.readouterr().out


# --- `figure --name`: one redraw on the frozen numbers ----------------------------------------


def test_figure_refuses_when_the_stored_summary_differs(tree):
    path = _write_summary()
    payload = json.loads(path.read_text())
    payload["complementarity"][NET_C]["ratio_sum_over_joint"] = 0.5
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    with pytest.raises(ValueError, match="recomputed summary differs"):
        an.command_figure("fig_d_complementarity.svg")
    assert not (tree / "figures").exists()


def test_figure_writes_exactly_one_file_and_restores_the_notice(tree, capsys):
    """The read-out's own hash is the one field allowed to differ, since editing the read-out
    is what makes a redraw necessary."""
    path = _write_summary()
    payload = json.loads(path.read_text())
    payload["provenance"]["read_out_code_sha256"] = {an.READ_OUT_NAME: "0" * 64}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    notice = svgplot.ATTRIBUTION_NOTICE
    assert an.command_figure("fig_d_complementarity.svg") == 0
    written_names = ["fig_d_complementarity.svg"]
    written = sorted((tree / "figures").iterdir())
    assert [one.name for one in written] == written_names
    assert svgplot.ATTRIBUTION_NOTICE == notice
    text = written[0].read_text()
    assert an.ATTRIBUTION_NOTICE in _drawn_text(text)
    assert "orders of magnitude" not in text
    assert "sha256" in capsys.readouterr().out
    with pytest.raises(FileExistsError, match="written once"):
        an.command_figure("fig_d_complementarity.svg")
    assert [one.name for one in sorted((tree / "figures").iterdir())] == written_names


def test_figure_refuses_an_unknown_name_and_a_path(pinned, tree):
    with pytest.raises(ValueError, match="no figure is named"):
        an.command_figure("fig_z_nothing.svg")
    with pytest.raises(ValueError, match="file name, not a path"):
        an.command_figure("figures/fig_d_complementarity.svg")
    assert not (tree / "figures").exists()


# --- the local artefacts, if this checkout carries any ----------------------------------------


def test_the_local_artefacts_match_the_frozen_summary(capsys):
    """The one test that reads the study's own `results/` and `runs/` rather than a fixture.

    It skips **only** on a clean public checkout, i.e. when none of the summary, the
    evaluations, `verdicts.json` and the controls is present. If any of them is, the full
    `verify` check runs and a partial or corrupt set fails here.
    """
    results = HERE / "results"
    present = [
        (results / an.SUMMARY_NAME).exists(),
        bool(list(results.glob("eval_*.json"))),
        (results / "verdicts.json").exists(),
        bool(list(results.glob("control_*.json"))),
    ]
    if not any(present):
        pytest.skip("clean public checkout: results/ holds no Stage A artefacts to pin")
    assert an.RESULTS == results  # the live globals, not a synthetic tree
    code = an.command_verify()
    captured = capsys.readouterr()
    assert code == 0, captured.out + captured.err
