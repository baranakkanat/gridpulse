"""Phase 8 study (docs/phase8_protocol.md): separate voltage and loading reserves against the
Phase 7 shared margin and strong baselines, under realistic injection-data and substation
conditions and three stress truths. An exploratory mechanism study on examined SimBench
data; not confirmatory.

Every run of one (network, truth) shares the days, the true states and the noise identity
(`sensing.NoiseBank`); conditions change only what the operator records or reads.
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import margin_study as ms
from gridpulse import margins as mg
from gridpulse import noise_study as ns
from gridpulse import reserves as rs
from gridpulse import sensing as sn
from gridpulse import stress as st
from gridpulse.grid_study import STEPS
from gridpulse.uncertainty import block_bootstrap_mean

PROTOCOL = "docs/phase8_protocol.md"
CACHE = Path("outputs/robust_study/fullstate_cache")
PRIMARY = ("nominal", *ns.MISMATCH)
TRUTHS = (*PRIMARY, *st.TRUTHS)
INJECTION = ("I0", *st.METERED, "I5_delay")
DELAY_DAYS = 2  # I5 and S3
OUTAGE_P = 0.2  # S4: days without substation data
REALISTIC = ns.CONDITIONS["realistic"]
SUBSTATION = {
    "S0": REALISTIC,
    **{f"S1{b:+.3f}": ms.CONDITIONS[f"busbar_bias_{b:+.3f}"] for b in ms.BUSBAR_BIASES},
    "S2_noisy": replace(REALISTIC, sigma_v_substation=0.005, sigma_loading=0.02),
    "S3_delay": REALISTIC,
    "S4_missing": REALISTIC,
}
POLICIES = ("static", "B2", "B3", "C1", "C1s0", "C1f", "C5", "C5L", "C6", "oracle")
CORRECTED = ("C1", "C1s0", "C1f", "C5", "C5L", "C6")
REPLICATIONS = (1, 2, 3, 4)
PAIRS = (("C5", "C1"), ("C6", "C1"), ("C5", "B3"))
BLOCK_DAYS = (7, 14, 28)
TYPES = ("over_v", "under_v", "line", "trafo", "failed")  # "failed": no converged flow


def run_key(policy: str, injection: str = "I0", substation: str = "S0", rep: int = 0) -> str:
    return f"{policy}|{injection}|{substation}|{rep}"


def plan(truth: str) -> list[tuple[str, str, str, int]]:
    """The registered runs of one truth (protocol s. 7)."""
    rows = [(p, "I0", "S0", 0) for p in POLICIES]
    if truth not in PRIMARY:
        return rows
    rows += [(p, "I0", "S0", r) for p in ("B2", "C1", "C5", "C6") for r in REPLICATIONS]
    rows += [(p, i, "S0", 0) for i in INJECTION[1:] for p in ("B2", "B3", "C1", "C5", "C6")]
    for s in SUBSTATION:
        if s == "S0":
            continue
        policies = ("C1", "C5", "C6") + (("B2",) if s.startswith(("S1", "S2")) else ())
        rows += [(p, "I0", s, 0) for p in policies]
    return rows


def outage_days(code: str, days) -> frozenset:
    """S4: days without substation data, identity-seeded (the same for every truth)."""
    bank = sn.NoiseBank(code, "S4_substation_outage", 0)
    return frozenset(d for d in days if bank.uniform("substation_outage", [0], d)[0] < OUTAGE_P)


def _load_fields(code: str, condition: str, fields, days) -> dict:
    """Selected arrays of a Phase 8 cache folder (memory: metered runs need no bus voltages)."""
    st.load(CACHE, code, condition, days[:1])  # manifest check
    folder = CACHE / code / condition
    out = {}
    for day in days:
        with np.load(folder / f"day_{day:03d}.npz") as data:
            out[day] = {key: data[key] for key in fields}
    return out


def folder_stats(code: str, condition: str) -> dict:
    """Share of failed flows (any NaN in a day x quarter-hour x cap-level margin row) and a
    digest of the cached files, for the physics record and the non-convergence rule."""
    import hashlib

    from gridpulse.runguard import sha256

    folder = CACHE / code / condition
    failed = rows = 0
    digest = hashlib.sha256()
    for path in sorted(folder.glob("day_*.npz")):
        digest.update(f"{path.name}:{sha256(path)};".encode())
        with np.load(path) as data:
            margins = data["margins"]
        failed += int(np.isnan(margins).any(axis=-1).sum())
        rows += int(np.prod(margins.shape[:-1]))
    digest.update(f"manifest:{sha256(folder / 'manifest.json')}".encode())
    return {"failed_share": failed / rows if rows else float("nan"), "rows": rows,
            "files": len(list(folder.glob("day_*.npz"))), "digest": digest.hexdigest()}  # fmt: skip


def truth_context(code: str, truth: str, stage: str, phase4_cache, fullstate_cache):
    """The decision context of one truth; stress truths take their true states and margins
    from the Phase 8 cache (scoring and readings only)."""
    if truth in PRIMARY:
        contexts, layout, facts = sn.build_contexts(
            code, phase4_cache, fullstate_cache, stage, truths=(truth,)
        )
        return contexts[truth], layout, facts
    contexts, layout, facts = sn.build_contexts(
        code, phase4_cache, fullstate_cache, stage, truths=("nominal",)
    )
    base = contexts["nominal"]
    decision = sorted(base.nominal_states)
    states = st.load(CACHE, code, truth, decision)
    truth_norm = {d: ds.normalised(np.asarray(states[d]["margins"], dtype=float)) for d in decision}
    return replace(base, states=states, truth_norm=truth_norm), layout, facts


def metered(ctx, raw: dict, code: str, injection: str) -> tuple:
    """The operator's planning data under one injection condition: the context (plan and
    residual reference replaced) and the corrector's raw plan."""
    if injection in ("I0", "I5_delay"):
        return ctx, raw
    states = _load_fields(code, injection, ("trafo", "line", "margins"), st.days_of(injection))
    raw_m = {d: np.asarray(s["margins"], dtype=float)[None] for d, s in states.items()}
    plan_norm = {}
    for d, arr in ctx.plan_norm.items():
        arr = np.array(arr, copy=True)
        arr[ds.REALISED] = ds.normalised(raw_m[d][0])
        plan_norm[d] = arr
    nominal = {d: states[d] for d in ctx.nominal_states}
    return replace(ctx, plan_norm=plan_norm, nominal_states=nominal), raw_m


def delayed(ctx, days: int):
    """I5 for the binary planners: at day j the replay sees the realised plan of day j - D
    (clamped at the first day with data, which a maximum over days makes the same as
    truncating the window; amendment 8A). Every other set is kept."""
    first = min(ctx.plan_norm)
    shifted = {}
    for d, arr in ctx.plan_norm.items():
        arr = np.array(arr, copy=True)
        arr[ds.REALISED] = ctx.plan_norm[max(first, d - days)][ds.REALISED]
        shifted[d] = arr
    return replace(ctx, plan_norm=shifted)


def tuning(raw: dict, ctx, delay: int = 0) -> dict:
    """Design-time settings from development days and the operator's data only; under an
    injection delay each tuning simulates the delayed replay (amendment 8A)."""
    dev, beta = list(ctx.development), ds.OnlineSettings().beta
    fine = rs.tuned_shared(raw, ctx.available, dev, beta, rs.GRID_SHARED_FINE, delay)
    shared = (
        mg.tuned_safety_margin(raw, ctx.available, dev, beta) if not delay
        else rs.tuned_shared(raw, ctx.available, dev, beta, mg.MARGIN_GRID, delay)["s"]
    )  # fmt: skip
    fixed = rs.tuned_fixed_reserves(raw, ctx.available, dev, beta, delay)
    return {"C1": shared, "C1f": fine["s"], "C1f_curve": fine["curve"],
            **{f"C5_{k}": v for k, v in fixed.items()}}  # fmt: skip


def run_one(policy, ctx, raw, tuned, configs, code, truth, injection, substation, rep,
            layout) -> tuple[list[dict], dict]:  # fmt: skip
    """One registered run: its records and its applied caps per day."""
    online, trace = ds.OnlineSettings(), {}
    model = SUBSTATION[substation]
    bank = sn.NoiseBank(code, truth, rep)
    if policy in ("static", "oracle"):
        name = "static_dev" if policy == "static" else "oracle"
        records = sn.run_feedback_policy(ctx, name, configs["substation"], ns.CONDITIONS["exact"],
                                         0, online, trace=trace)  # fmt: skip
        return records, trace
    if policy in ("B2", "B3"):
        config, readings = (configs["substation"], model) if policy == "B2" else (
            configs[ms.T2], ns.CONDITIONS["exact"])  # fmt: skip
        plan_ctx = delayed(ctx, DELAY_DAYS) if injection == "I5_delay" else ctx
        records = sn.run_feedback_policy(
            plan_ctx, "replay_aci", config, readings, 0, online, noise=bank,
            alarm=ns.RULES["unfiltered"], trace=trace,
        )  # fmt: skip
        return records, trace
    delay = DELAY_DAYS if injection == "I5_delay" else 0
    if delay and substation == "S3_delay":
        raise ValueError("I5 and S3 are not combined in the registered plan")
    lag = DELAY_DAYS if substation == "S3_delay" else delay
    margin = {"C1": tuned["C1"], "C1f": tuned["C1f"]}.get(policy, 0.0)
    reserves = {"C5": (tuned["C5_r_v"], tuned["C5_r_l"]), "C5L": (0.0, tuned["C5_r_l"]),
                "C6": "rolling"}.get(policy)  # fmt: skip
    missing = outage_days(code, ctx.plan_norm) if substation == "S4_missing" else frozenset()
    corrector = rs.ReserveCorrector(
        raw, ctx.nominal_states, layout, configs["substation"], model,
        mg.CorrectorSettings(safety_margin=margin, lag_days=lag), reserves=reserves,
        available=ctx.available, beta=online.beta, delay_days=delay, missing_days=missing,
    )  # fmt: skip
    records = sn.run_feedback_policy(ctx, "replay_robust", configs["substation"], model, 0,
                                     online, noise=bank, alarm=ns.RULES["unfiltered"],
                                     corrector=corrector, trace=trace)  # fmt: skip
    return records, trace


def violation_type(scaled: np.ndarray) -> str:
    """The dominant constraint type of one violated step (normalised exceedances), or
    "failed" when no flow converged (amendment 8A)."""
    if np.isnan(scaled).all():
        return "failed"
    return TYPES[int(np.nanargmax(scaled))]


def run_summary(records: list[dict], trace: dict, ctx) -> dict:
    """Phase 7 summary plus violations by constraint type, the largest single-step
    exceedance (normalised) and the reserves in force. Evaluator-side."""
    out = ms.summary(records, ds.OnlineSettings())
    types, largest = Counter(), 0.0
    for r in records:
        day = r["day"]
        levels = np.asarray(trace[day], dtype=int)
        norm = ctx.truth_norm[day]
        daylight = ctx.available[day].sum(axis=1) > 0
        hit = (norm[np.arange(STEPS), levels] > 0) & (norm <= 0).any(axis=1) & daylight
        if hit.any():
            raw = np.asarray(ctx.states[day]["margins"], dtype=float)[np.arange(STEPS), levels]
            scaled = raw / ds.MARGIN_SCALE
            for t in np.flatnonzero(hit):
                types[violation_type(scaled[t])] += 1
            largest = max(largest, float(norm[np.arange(STEPS), levels][hit].max()))
    out["violations_by_type"] = {name: types.get(name, 0) for name in TYPES}
    out["largest_exceedance"] = largest
    if records and records[0].get("r_v") is not None:
        for key in ("r_v", "r_l"):
            values = [r[key] for r in records]
            out[f"mean_{key}"] = float(np.mean(values))
            out[f"range_{key}"] = [float(np.min(values)), float(np.max(values))]
    return out


def no_action(ctx) -> dict:
    """Avoidable daylight no-action violation quarter-hours under the truth and under the
    nominal model on the scored days, and those present under only one of them (a stress
    case "creates" the former; amendment 8A). Evaluator-side."""
    out = Counter()
    for d in ctx.days:
        daylight = ctx.available[d].sum(axis=1) > 0
        truth, nominal = ctx.truth_norm[d], ctx.plan_norm[d][ds.REALISED]
        vt = (truth[:, 0] > 0) & (truth <= 0).any(axis=1) & daylight
        vn = (nominal[:, 0] > 0) & (nominal <= 0).any(axis=1) & daylight
        out["truth"] += int(vt.sum())
        out["nominal"] += int(vn.sum())
        out["created"] += int((vt & ~vn).sum())
        out["removed"] += int((vn & ~vt).sum())
    return dict(out)


def task(args: tuple) -> dict:
    """Every registered run of one (network, truth) in one period."""
    code, truth, stage, placements, phase4_cache, fullstate_cache, dropped = args
    ctx, layout, facts = truth_context(code, truth, stage, phase4_cache, fullstate_cache)
    raw0 = ms.plan_raw(code, phase4_cache)
    configs = ns.configurations(layout, ctx.states[ctx.days[0]]["line"].shape[2], placements)
    runs, kept, tunings = {}, {}, {}
    rows = [row for row in plan(truth) if row[1] not in dropped]
    for injection in INJECTION:
        wanted = [row for row in rows if row[1] == injection]
        if not wanted:
            continue
        ictx, raw = metered(ctx, raw0, code, injection)
        tuned = tuning(raw, ictx, DELAY_DAYS if injection == "I5_delay" else 0)
        tunings[injection] = tuned
        for policy, _, substation, rep in wanted:
            records, trace = run_one(policy, ictx, raw, tuned, configs, code, truth, injection,
                                     substation, rep, layout)  # fmt: skip
            key = run_key(policy, injection, substation, rep)
            runs[key] = run_summary(records, trace, ctx)
            if injection == "I0" and substation == "S0" and rep == 0:
                kept[policy] = records
        del ictx, raw
    paired = {}
    for a, b in PAIRS:
        entry = {}
        for metric in ("avoidable_violation_steps", "curtailed_mwh"):
            pairs = list(zip(kept[a], kept[b], strict=True))
            if any(x["day"] != y["day"] for x, y in pairs):
                raise RuntimeError(f"{a} and {b} were scored on different days")
            diff = np.array([x[metric] - y[metric] for x, y in pairs])
            for block in BLOCK_DAYS:
                entry[f"{metric}_block{block}"] = block_bootstrap_mean(diff, block_days=block)
        paired[f"{a} - {b}"] = entry
    return {
        "network": code, "truth": truth, "facts": facts, "tuning": tunings, "runs": runs,
        "paired": paired, "observability": ms.observability(ctx, layout, placements["topology"]),
        "no_action": no_action(ctx),
    }  # fmt: skip


# --- checks (protocol s. 11) and hypotheses (s. 9) ------------------------------------


def development_checks(results: dict, phase7_development: dict, phase4_cache) -> dict:
    """C1 reproduces the frozen Phase 7 development C1; tap_lower_lv margins equal the
    Phase 4 cache; every stress truth creates avoidable violations at no action."""
    reproduced = {}
    for code, by_truth in results.items():
        for truth in PRIMARY:
            ours = by_truth[truth]["runs"][run_key("C1")]
            frozen = phase7_development[code][truth]["runs"]["C1/0"]
            reproduced[f"{code} {truth}"] = all(ours[k] == v for k, v in frozen.items())
    tap_equal = {}
    for code in results:
        days = st.days_of("tap_lower_lv")
        variant = ds.VARIANTS["tap_lower_lv"]
        phase4 = ds.load_margins(
            phase4_cache, code, "tap_lower_lv", days, ds.pv_scale(code), variant
        )
        states = st.load(CACHE, code, "tap_lower_lv", days)
        tap_equal[code] = all(
            np.array_equal(states[d]["margins"], phase4[d][ds.REALISED], equal_nan=True)
            for d in days
        )
    stress = {
        truth: {code: results[code][truth]["no_action"]["created"] for code in results}
        for truth in st.TRUTHS
        if truth in next(iter(results.values()))
    }
    return {
        "c1_reproduces_phase7": reproduced,
        "tap_lower_equals_phase4": tap_equal,
        "stress_created_violations": stress,
        "passed": all(reproduced.values())
        and all(tap_equal.values())
        and all(any(v > 0 for v in by.values()) for by in stress.values()),
    }


def _new(results: dict) -> list[str]:
    return [c for c in results if c != ds.DEVELOPMENT_NETWORK]


def total(results, key, metric, truths) -> float:
    return float(sum(results[c][t]["runs"][key][metric] for c in _new(results) for t in truths))


def cells(results, key, truths) -> int:
    return int(sum(results[c][t]["runs"][key]["meets_beta"] for c in _new(results) for t in truths))


def non_inferior(results, x: str, y: str) -> dict:
    """Strict non-inferiority NI(x vs y) (protocol s. 9)."""
    mis, nom = ns.MISMATCH, ("nominal",)
    checks = {
        "mismatch_violations": total(results, x, "avoidable_violation_steps", mis)
        <= total(results, y, "avoidable_violation_steps", mis) + 15,
        "mismatch_long_runs": total(results, x, "long_runs", mis)
        <= total(results, y, "long_runs", mis) + 1,
        "mismatch_cells": cells(results, x, mis) >= cells(results, y, mis),
        "nominal_violations": total(results, x, "avoidable_violation_steps", nom)
        <= total(results, y, "avoidable_violation_steps", nom) + 5,
    }
    return {"met": all(checks.values()), **checks}


def _cost(results, x, y, truths, factor) -> dict:
    a, b = (total(results, k, "curtailed_mwh", truths) for k in (x, y))
    return {"x_mwh": a, "y_mwh": b, "ratio": a / b if b else float("nan"), "met": a <= factor * b}


def _rule(results, x: str, y: str, nominal_factor: float) -> dict:
    mis, nom = ns.MISMATCH, ("nominal",)
    out = {"ni": non_inferior(results, x, y), "mismatch_cost": _cost(results, x, y, mis, 0.9),
           "nominal_cost": _cost(results, x, y, nom, nominal_factor)}  # fmt: skip
    out["met"] = out["ni"]["met"] and out["mismatch_cost"]["met"] and out["nominal_cost"]["met"]
    return out


def primary(results: dict) -> dict:
    """H1: C5 against C1, with the attribution to separation or to resolution (C1f)."""
    h1 = _rule(results, run_key("C5"), run_key("C1"), 1.0)
    fine = _rule(results, run_key("C1f"), run_key("C1"), 1.0)
    h1["attribution"] = (
        "separation" if h1["met"] and not fine["met"] else "resolution" if h1["met"] else "none"
    )
    h1["C1f_same_rule"] = fine
    return h1


def evaluate_hypotheses(results: dict, development: dict | None = None) -> dict:
    """H1-H5 (protocol s. 9). `development`: development-half results, for H2's condition."""
    mis, nom = ns.MISMATCH, ("nominal",)
    c1, c6 = run_key("C1"), run_key("C6")
    h1 = primary(results)
    h2 = _rule(results, c6, c1, 0.9)
    h2["ni_development"] = non_inferior(development, c6, c1) if development else None
    h2["met"] = h2["met"] and bool(h2["ni_development"] and h2["ni_development"]["met"])

    def robust(x: str, injection: str, substation: str) -> dict:
        key, ref = run_key(x, injection, substation), run_key(x)
        a, b = total(results, key, "curtailed_mwh", nom), total(results, ref, "curtailed_mwh", nom)
        out = {
            "mismatch_cells": cells(results, key, mis),
            "nominal_cells": cells(results, key, nom),
            "nominal_mwh_ratio": a / b if b else float("nan"),
            "mismatch_violations": total(results, key, "avoidable_violation_steps", mis),
            "mismatch_mwh": total(results, key, "curtailed_mwh", mis),
        }
        out["met"] = out["mismatch_cells"] >= 14 and out["nominal_cells"] == 5 and a <= 1.1 * b
        return out

    h3 = {}
    present = next(iter(results.values()))["nominal"]["runs"]
    for injection in INJECTION[1:]:
        if run_key("C1", injection) not in present:  # condition dropped (protocol s. 11)
            continue
        entry = {x: robust(x, injection, "S0") for x in ("C1", "C5", "C6", "B3")}
        if h1["met"]:
            a, b = run_key("C5", injection), run_key("C1", injection)
            entry["benefit_survives"] = (
                non_inferior(results, a, b)["met"] and _cost(results, a, b, mis, 0.9)["met"]
            )
        h3[injection] = entry
    h4 = {s: {x: robust(x, "I0", s) for x in ("C1", "C5", "C6")} for s in SUBSTATION if s != "S0"}
    h5 = {}
    for truth in st.TRUTHS:
        if truth not in next(iter(results.values())):  # truth dropped (protocol s. 11)
            continue
        h5[truth] = {
            p: {
                "cells": int(
                    sum(results[c][truth]["runs"][run_key(p)]["meets_beta"] for c in _new(results))
                ),  # fmt: skip
                "violations": float(
                    sum(
                        results[c][truth]["runs"][run_key(p)]["avoidable_violation_steps"]
                        for c in _new(results)
                    )
                ),  # fmt: skip
                "mwh": float(
                    sum(
                        results[c][truth]["runs"][run_key(p)]["curtailed_mwh"]
                        for c in _new(results)
                    )
                ),  # fmt: skip
            }
            for p in POLICIES
        }
        for p in POLICIES:
            h5[truth][p]["covers"] = h5[truth][p]["cells"] >= 4
        h5[truth]["no_action"] = {c: results[c][truth]["no_action"] for c in _new(results)}
    return {"H1": h1, "H2": h2, "H3": h3, "H4": h4, "H5": h5}


def run_study(stage, phase4_cache, fullstate_cache, networks, workers, placements,
              dropped=frozenset()) -> dict:  # fmt: skip
    """All (network, truth) tasks of one stage, bounded parallelism. `dropped`: conditions
    removed under the non-convergence rule (protocol s. 11)."""
    tasks = [(c, t, stage, placements[c], phase4_cache, fullstate_cache, frozenset(dropped))
             for c in networks for t in TRUTHS if t not in dropped]  # fmt: skip
    results: dict = {}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for out in pool.map(task, tasks, chunksize=1):
            results.setdefault(out["network"], {})[out["truth"]] = out
    return results


def load_json(path: Path) -> dict:
    return json.loads(Path(path).read_text())
