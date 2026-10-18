"""Phase 7: continuous model-residual correction versus binary alarm feedback
(docs/phase7_protocol.md).

Reuses the Phase 5/6 decision contexts, placements, noise bank, alarm rules and feedback
policy. The candidate methods replace the replay planner by `margins.ResidualCorrector`,
which corrects the nominal model from substation (and optionally meter) residuals. All runs
of one (network, truth) share the same days, timing, actions and noise realisations.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import margins as mg
from gridpulse import noise_study as ns
from gridpulse import sensing as sn
from gridpulse.uncertainty import block_bootstrap_mean

PROTOCOL = "docs/phase7_protocol.md"
BUSBAR_BIASES = (-0.005, -0.002, 0.002, 0.005)  # p.u.; IEC class 0.2 / 0.5 limits (7A)
CONDITIONS = {
    **ns.CONDITIONS,
    **{f"busbar_bias_{b:+.3f}": replace(ns.CONDITIONS["realistic"], bias_v_substation=b)
       for b in BUSBAR_BIASES},
}  # fmt: skip
MISMATCH = ns.MISMATCH
T2 = "substation+2:topology"
REPLICATIONS = (1, 2, 3, 4)

# (name, kind, configuration, condition, rule or meters, replication)
# kind: "binary" (Phase 5/6 replay_aci with an alarm rule), "corrected" (residual-corrected
# replay with the development-tuned margin), "reference" (the same planner, no correction),
# "hybrid" (corrected replay plus the Phase 6 count feedback).
PLAN = [
    ("B2", "binary", "substation", "realistic", "unfiltered", 0),
    ("B2x", "binary", "substation", "exact", "unfiltered", 0),
    ("B3", "binary", T2, "exact", "unfiltered", 0),
    ("B4", "binary", T2, "realistic", "unfiltered", 0),
    ("B5", "binary", T2, "realistic", "persist3_meters", 0),
    ("B6", "binary", T2, "realistic", "guard2", 0),
    ("B7", "binary", "full", "exact", "unfiltered", 0),
    ("R0", "reference", "substation", "exact", "none", 0),
    ("Rdev", "reference", "substation", "exact", "none", 0),
    ("C1", "corrected", "substation", "realistic", "none", 0),
    ("C1x", "corrected", "substation", "exact", "none", 0),
    ("C3", "corrected", T2, "realistic", "checked", 0),
    ("C3x", "corrected", T2, "exact", "checked", 0),
    ("C3_1", "corrected", "substation+1:topology", "realistic", "checked", 0),
    ("C3_4", "corrected", "substation+4:topology", "realistic", "checked", 0),
    ("C3full", "corrected", "full", "realistic", "checked", 0),
    ("C4", "hybrid", T2, "realistic", "persist3_meters", 0),
]
PLAN += [("C1", "corrected", "substation", "realistic", "none", r) for r in REPLICATIONS]
PLAN += [("B2", "binary", "substation", "realistic", "unfiltered", r) for r in REPLICATIONS]
# amendment 7A sensitivities (reported, no decision rule)
PLAN += [
    (f"{name}bb{b:+.3f}", "corrected", config, f"busbar_bias_{b:+.3f}", meters, 0)
    for b in BUSBAR_BIASES
    for name, config, meters in (("C1", "substation", "none"), ("C3", T2, "checked"))
]
PLAN += [
    ("C1s0", "corrected", "substation", "realistic", "none", 0),  # no safety margin
    ("C1lag", "corrected", "substation", "realistic", "none", 0),  # residuals one day later
]
NO_MARGIN = ("R0", "C4", "C1s0")
PLAN += [
    (name, "corrected", T2, "biased_meters_matched", meters, r)
    for name, meters in (("C3b", "checked"), ("C3nb", "naive"))
    for r in (0, *REPLICATIONS)
]
PAIRS = (("C1", "B3"), ("C1", "B2"), ("C1", "Rdev"), ("C1", "C1x"), ("C3", "C1"), ("C1", "B5"))
BLOCK_DAYS = (7, 14, 28)
LABELS = (
    "EVIDENCE_SUFFICIENT_FOR_DEFINED_ANALYSIS", "PHYSICAL_MODEL_UNCERTAINTY",
    "MEASUREMENT_MODEL_INCONSISTENCY", "INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS",
    "NO_VERIFIED_FEASIBLE_ACTION",
)  # fmt: skip


def run_key(name: str, replication: int = 0) -> str:
    return f"{name}/{replication}"


def plan_raw(code: str, phase4_cache) -> dict:
    """The operator's nominal model: Phase 4 exceedances of the realised injection set."""
    tasks = ds.physics_tasks()["nominal"]
    raw = ds.load_margins(
        phase4_cache, code, "nominal", [d for d, _ in tasks], ds.pv_scale(code), ds.NOMINAL
    )
    return {d: m[ds.REALISED : ds.REALISED + 1] for d, m in raw.items()}


def summary(records: list[dict], online) -> dict:
    out = ns.summary(records, online)
    if "v_hat" in records[0]:
        labels = Counter(mg.evidence_label(r) for r in records)
        out["labels"] = {name: labels.get(name, 0) for name in LABELS}
        out["mean_v_hat"] = float(np.mean([r["v_hat"] for r in records]))
        out["mean_rho_line"] = float(np.mean([r["rho_line"] for r in records]))
        out["mean_rho_trafo"] = float(np.mean([r["rho_trafo"] for r in records]))
        out["mean_meters_inconsistent"] = float(
            np.mean([r["meters_inconsistent"] for r in records])
        )
    return out


def observability(ctx, layout, placement: list[int]) -> dict:
    """Avoidable violation steps at no action on scored daylight steps, by what can see
    them: the substation (transformer, a feeder-head line or the busbar voltage), the + 2
    meters (overvoltage at a metered bus), nothing (overvoltage only at unmetered buses, or
    only lines that are not feeder heads), or none of these (e.g. undervoltage).
    Evaluator-side; never used by a decision."""
    limits = np.array(layout.max_vm)
    busbar = layout.buses.index(layout.lv_busbar)
    metered = [layout.buses.index(b) for b in placement[:2]]
    heads = list(layout.feeder_heads)
    counts = Counter()
    for day in ctx.days:
        state, daylight = ctx.states[day], ctx.available[day].sum(axis=1) > 0
        events = sn.true_events(ctx.truth_norm[day], state, 0, layout)
        for t in np.flatnonzero(events["any"] & daylight):
            over = state["vm"][t, 0] > limits
            if events["trafo"][t] or (state["line"][t, 0][heads] > 100.0).any() or over[busbar]:
                counts["substation_observable"] += 1
            elif over[metered].any():
                counts["at_metered_bus"] += 1
            elif over.any():
                counts["unmetered_voltage_only"] += 1
            elif events["line"][t]:
                counts["unmeasured_line_only"] += 1
            else:
                counts["other"] += 1
    return dict(counts)


def coverage(code: str, truth: str, days, placement: list[int]) -> dict:
    """Empirical coverage of reading +/- 2u (single readings) and of daily mean +/- 2u/sqrt(n)
    for the + 2 meters' errors, under independent noise and under matched per-meter bias."""
    out = {}
    for condition in ("realistic", "biased_meters_matched"):
        model = ns.CONDITIONS[condition]
        u = float(np.hypot(model.sigma_v_remote, model.sigma_bias_remote))
        single, daily = [], []
        for rep in (0, *REPLICATIONS):
            bank = sn.NoiseBank(code, truth, rep)
            for b in placement[:2]:
                bias = bank.bias("meter_voltage", (b,))[0] * model.sigma_bias_remote
                for day in days:
                    errors = bank.normal("meter_voltage", (b,), day)[:, 0] * model.sigma_v_remote
                    errors = errors + bias
                    single.append(mg.interval_coverage(errors, 2 * u))
                    daily.append(abs(errors[40:60].mean()) <= 2 * u / np.sqrt(20))
        out[condition] = {
            "single_reading": float(np.mean(single)),
            "daily_mean": float(np.mean(daily)),
        }
    return out


def task(args: tuple) -> dict:
    code, truth, stage, placements, phase4_cache, fullstate_cache = args
    contexts, layout, facts = sn.build_contexts(
        code, phase4_cache, fullstate_cache, stage, truths=(truth,)
    )
    ctx = contexts[truth]
    raw = plan_raw(code, phase4_cache)
    configs = ns.configurations(layout, ctx.states[ctx.days[0]]["line"].shape[2], placements)
    online = ds.OnlineSettings()
    margin = mg.tuned_safety_margin(raw, ctx.available, list(ctx.development), online.beta)
    runs, kept = {}, {}
    for name, kind, config, condition, rule, rep in PLAN:
        model, bank = CONDITIONS[condition], sn.NoiseBank(code, truth, rep)
        if kind == "binary":
            records = sn.run_feedback_policy(
                ctx, "replay_aci", configs[config], model, 0, online, noise=bank,
                alarm=ns.RULES[rule],
            )  # fmt: skip
        else:
            settings = mg.CorrectorSettings(
                meters="none" if rule in ("none", "persist3_meters") else rule,
                safety_margin=0.0 if name in NO_MARGIN else margin,
                correct=kind != "reference",
                lag_days=1 if name == "C1lag" else 0,
            )
            corrector = mg.ResidualCorrector(raw, ctx.nominal_states, layout, configs[config],
                                             model, settings)  # fmt: skip
            policy = "replay_aci" if kind == "hybrid" else "replay_robust"
            alarm = ns.RULES[rule if kind == "hybrid" else "unfiltered"]
            records = sn.run_feedback_policy(
                ctx, policy, configs[config], model, 0, online, noise=bank, alarm=alarm,
                corrector=corrector,
            )  # fmt: skip
        runs[run_key(name, rep)] = summary(records, online)
        if rep == 0:
            kept[name] = records
    for policy in ("static_dev", "oracle"):
        records = sn.run_feedback_policy(
            ctx, policy, configs["substation"], ns.CONDITIONS["exact"], 0, online
        )
        runs[policy] = summary(records, online)
    paired = {}
    for a, b in PAIRS:
        entry = {}
        for metric in ("avoidable_violation_steps", "curtailed_mwh"):
            diff = np.array([x[metric] - y[metric] for x, y in zip(kept[a], kept[b], strict=True)])
            for block in BLOCK_DAYS:
                entry[metric if block == 7 else f"{metric}_block{block}"] = block_bootstrap_mean(
                    diff, block_days=block
                )
        paired[f"{a} - {b}"] = entry
    return {
        "network": code,
        "truth": truth,
        "facts": facts,
        "safety_margin": margin,
        "runs": runs,
        "paired": paired,
        "observability": observability(ctx, layout, placements["topology"]),
        "coverage": coverage(code, truth, list(ctx.days), placements["topology"]),
    }


def _new(results: dict) -> list[str]:
    return [c for c in results if c != ds.DEVELOPMENT_NETWORK]


def cells(results: dict, key: str, truths=MISMATCH) -> int:
    return int(sum(results[c][t]["runs"][key]["meets_beta"] for c in _new(results) for t in truths))


def total(results: dict, key: str, metric: str, truths=("nominal",)) -> float:
    return float(sum(results[c][t]["runs"][key][metric] for c in _new(results) for t in truths))


def evaluate_hypotheses(results: dict) -> dict:
    """The registered decision rules (protocol s. 7), five new networks."""
    k, v, mwh = run_key, "avoidable_violation_steps", "curtailed_mwh"
    h1 = {
        "C1_mismatch_violations": total(results, k("C1"), v, MISMATCH),
        "B3_mismatch_violations": total(results, k("B3"), v, MISMATCH),
        "C1_nominal_mwh": total(results, k("C1"), mwh),
        "B2_nominal_mwh": total(results, k("B2"), mwh),
    }
    h1["a_fewer_violations_than_two_exact_meters"] = (
        h1["C1_mismatch_violations"] < h1["B3_mismatch_violations"]
    )
    h1["b_cost_within_10pct_of_substation_feedback"] = (
        h1["C1_nominal_mwh"] <= 1.1 * h1["B2_nominal_mwh"]
    )
    h1["met"] = bool(h1["a_fewer_violations_than_two_exact_meters"]
                     and h1["b_cost_within_10pct_of_substation_feedback"])  # fmt: skip
    vr, vx = total(results, k("C1"), v, MISMATCH), total(results, k("C1x"), v, MISMATCH)
    cr, cx = total(results, k("C1"), mwh), total(results, k("C1x"), mwh)
    h2 = {"realistic_violations": vr, "exact_violations": vx, "realistic_mwh": cr, "exact_mwh": cx,
          "met": bool(abs(vr - vx) <= 0.1 * vx + 10 and abs(cr - cx) <= 0.05 * cx)}  # fmt: skip
    base = total(results, k("C1"), mwh)
    checked = [total(results, k("C3b", r), mwh) for r in (0, *REPLICATIONS)]
    naive = [total(results, k("C3nb", r), mwh) for r in (0, *REPLICATIONS)]
    h3 = {"C1_nominal_mwh": base, "checked_nominal_mwh": checked, "naive_nominal_mwh": naive,
          "a_checked_within_10pct_in_all_draws": all(c <= 1.1 * base for c in checked),
          "b_naive_exceeds_10pct_in_some_draw": any(c > 1.1 * base for c in naive)}  # fmt: skip
    h3["met"] = bool(h3["a_checked_within_10pct_in_all_draws"]
                     and h3["b_naive_exceeds_10pct_in_some_draw"])  # fmt: skip
    rdev = total(results, k("Rdev"), v, MISMATCH)
    h4 = {"C1_mismatch_violations": vr, "Rdev_mismatch_violations": rdev,
          "met": bool(vr <= 0.2 * rdev)}  # fmt: skip
    rates = {}
    for c in _new(results):
        for t in ("nominal", *MISMATCH):
            run = results[c][t]["runs"][k("C1")]
            flagged = run["labels"]["PHYSICAL_MODEL_UNCERTAINTY"]
            rates[f"{c}/{t}"] = flagged / run["days"]
    voltage_offset = [rates[f"{c}/{t}"] for c in _new(results) for t in ("tap_raise_lv", "mv_high")]
    nominal = [rates[f"{c}/nominal"] for c in _new(results)]
    h5 = {"flag_rates": rates, "met": bool(min(voltage_offset) >= 0.9 and max(nominal) <= 0.05)}
    return {
        "H1_primary": h1,
        "H2_noise_invariance": h2,
        "H3_bias_check": h3,
        "H4_correction_is_active": h4,
        "H5_model_uncertainty_label": h5,
        "sensitivity": sensitivity(results, h1),
        "cells": {
            name: cells(results, k(name))
            for name in ("B2", "B3", "B4", "B5", "B7", "Rdev", "C1", "C1x", "C3", "C4")
        },  # fmt: skip
        "replications_C1": [
            {
                "violations": total(results, k("C1", r), v, MISMATCH),
                "nominal_mwh": total(results, k("C1", r), mwh),
                "h1_met": bool(
                    total(results, k("C1", r), v, MISMATCH) < h1["B3_mismatch_violations"]
                    and total(results, k("C1", r), mwh) <= 1.1 * total(results, k("B2", r), mwh)
                ),
            }
            for r in (0, *REPLICATIONS)
        ],  # fmt: skip
    }


def sensitivity(results: dict, h1: dict) -> dict:
    """Amendment 7A, reported without decision rules: busbar voltage-transformer bias, no
    safety margin (comparison at matched curtailment), residuals one day later, and the
    clean cost of the correction (C1 against the same planner without it)."""
    k, v, mwh = run_key, "avoidable_violation_steps", "curtailed_mwh"

    def row(name):
        nominal_flags = [
            results[c]["nominal"]["runs"][k(name)]["labels"]["PHYSICAL_MODEL_UNCERTAINTY"]
            / results[c]["nominal"]["runs"][k(name)]["days"]
            for c in _new(results)
        ]
        return {
            "mismatch_violations": total(results, k(name), v, MISMATCH),
            "mismatch_mwh": total(results, k(name), mwh, MISMATCH),
            "nominal_violations": total(results, k(name), v),
            "nominal_mwh": total(results, k(name), mwh),
            "mismatch_cells": cells(results, k(name)),
            "no_feasible_days": total(results, k(name), "no_feasible_action_days", MISMATCH)
            + total(results, k(name), "no_feasible_action_days"),
            "nominal_flag_rate_max": max(nominal_flags),
            "h1a": total(results, k(name), v, MISMATCH) < h1["B3_mismatch_violations"],
            "h1b": total(results, k(name), mwh) <= 1.1 * h1["B2_nominal_mwh"],
        }

    out = {name: row(name) for name in ("C1", "C1s0", "C1lag")}
    out.update({f"{n}bb{b:+.3f}": row(f"{n}bb{b:+.3f}") for n in ("C1", "C3")
                for b in BUSBAR_BIASES})  # fmt: skip
    for name in ("B3", "Rdev"):
        out[name] = {"mismatch_violations": total(results, k(name), v, MISMATCH),
                     "mismatch_mwh": total(results, k(name), mwh, MISMATCH),
                     "nominal_mwh": total(results, k(name), mwh)}  # fmt: skip
    return out


def run_study(stage: str, phase4_cache, fullstate_cache, networks, workers: int,
              placements: dict) -> dict:  # fmt: skip
    """Every analysis of one stage. Placements are the frozen Phase 6 development design."""
    from concurrent.futures import ProcessPoolExecutor

    from gridpulse import fullstate

    tasks = [
        (code, truth, stage, placements[code], phase4_cache, fullstate_cache)
        for code in networks
        for truth in fullstate.TRUTHS
    ]
    results: dict = {code: {} for code in networks}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(task, tasks, chunksize=1):
            results[part["network"]][part["truth"]] = part
    return {"results": results, "hypotheses": evaluate_hypotheses(results)}
