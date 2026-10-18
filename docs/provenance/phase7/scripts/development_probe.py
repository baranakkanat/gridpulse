"""Phase 7, development days only, before registration: does a continuous model-residual
correction from substation telemetry work mechanically? Exploratory; disclosed in the
protocol. Reads no evaluation day. Usage, from the repository root:

    python docs/provenance/phase7/scripts/development_probe.py [workers]
"""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from gridpulse import dual_study as ds
from gridpulse import fullstate
from gridpulse import margins as mg
from gridpulse import noise_study as ns
from gridpulse import sensing as sn

P4 = Path("outputs/dual_study/physics_cache")
FS = Path("outputs/sense_study/fullstate_cache")
OUT = Path("outputs/margin_study/exploratory")


def plan_raw(code: str) -> dict:
    tasks = ds.physics_tasks()["nominal"]
    raw = ds.load_margins(P4, code, "nominal", [d for d, _ in tasks], ds.pv_scale(code), ds.NOMINAL)
    return {d: m[ds.REALISED : ds.REALISED + 1] for d, m in raw.items()}  # keep the set axis


def task(args):
    code, truth, placements = args
    contexts, layout, _ = sn.build_contexts(code, P4, FS, "development", truths=(truth,))
    ctx = contexts[truth]
    raw = plan_raw(code)
    configs = ns.configurations(layout, ctx.states[ctx.days[0]]["line"].shape[2], placements)
    online = ds.OnlineSettings()
    bank = sn.NoiseBank(code, truth, 0)
    runs = {}

    def binary(name, cond, rule, policy="replay_aci"):
        r = sn.run_feedback_policy(ctx, policy, configs[name], ns.CONDITIONS[cond], 0, online,
                                   noise=bank, alarm=ns.RULES[rule])  # fmt: skip
        return ns.summary(r, online)

    margin = mg.tuned_safety_margin(raw, ctx.available, list(ctx.development), online.beta)

    def corrected(name, cond, meters="none", policy="replay_robust", rule="unfiltered",
                  correct=True, safety=margin):  # fmt: skip
        model = ns.CONDITIONS[cond]
        settings = mg.CorrectorSettings(meters=meters, safety_margin=safety, correct=correct)
        corr = mg.ResidualCorrector(raw, ctx.nominal_states, layout, configs[name], model, settings)
        r = sn.run_feedback_policy(ctx, policy, configs[name], model, 0, online,
                                   noise=bank, alarm=ns.RULES[rule], corrector=corr)  # fmt: skip
        out = ns.summary(r, online)
        out["v_hat_last"] = r[-1]["v_hat"]
        out["rho_line_last"], out["rho_trafo_last"] = r[-1]["rho_line"], r[-1]["rho_trafo"]
        out["safety_margin"] = safety
        return out

    T2 = "substation+2:topology"
    runs["B2 substation binary realistic"] = binary("substation", "realistic", "unfiltered")
    runs["B3 +2 binary exact"] = binary(T2, "exact", "unfiltered")
    runs["B4 +2 binary realistic"] = binary(T2, "realistic", "unfiltered")
    runs["B5 +2 persist3_meters realistic"] = binary(T2, "realistic", "persist3_meters")
    runs["B7 full binary exact"] = binary("full", "exact", "unfiltered")
    runs["R0 open-loop replay (tau 0)"] = corrected("substation", "exact", correct=False, safety=0.0)
    runs["Rdev open-loop replay (tuned margin)"] = corrected("substation", "exact", correct=False)
    runs["C1 corrected, substation, realistic"] = corrected("substation", "realistic")
    runs["C1 corrected, substation, exact"] = corrected("substation", "exact")
    runs["C1 corrected, tau 0, realistic"] = corrected("substation", "realistic", safety=0.0)
    runs["C3 corrected, +2 checked, realistic"] = corrected(T2, "realistic", "checked")
    runs["C3 corrected, +2 checked, bias"] = corrected(T2, "biased_meters_matched", "checked")
    runs["C3n corrected, +2 naive, bias"] = corrected(T2, "biased_meters_matched", "naive")
    runs["C4 corrected + persist3 ACI, +2 realistic"] = corrected(
        T2, "realistic", policy="replay_aci", rule="persist3_meters", safety=0.0)
    for policy in ("static_dev", "oracle"):
        r = sn.run_feedback_policy(ctx, policy, configs["substation"], ns.CONDITIONS["exact"], 0,
                                   online)  # fmt: skip
        runs[policy] = ns.summary(r, online)
    return {"network": code, "truth": truth, "runs": runs}


def table(results) -> None:
    new = [r for r in results if "rural1" not in r["network"]]
    print(f"{'policy':44s} mis-cells mis-viol mis-MWh nom-viol nom-MWh nom-cells")
    for name in results[0]["runs"]:
        mis = [r["runs"][name] for r in new if r["truth"] != "nominal"]
        nom = [r["runs"][name] for r in new if r["truth"] == "nominal"]
        print(f"{name:44s} {sum(x['meets_beta'] for x in mis):5d} "
              f"{sum(x['avoidable_violation_steps'] for x in mis):8.0f} "
              f"{sum(x['curtailed_mwh'] for x in mis):8.1f} "
              f"{sum(x['avoidable_violation_steps'] for x in nom):7.0f} "
              f"{sum(x['curtailed_mwh'] for x in nom):7.1f} {sum(x['meets_beta'] for x in nom):3d}")


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    dev = json.loads(Path("outputs/noise_study/development_results.json").read_text())
    tasks = [(c, t, dev["placements"][c]) for c in ds.HOSTING_CAPACITY for t in fullstate.TRUTHS]
    with ProcessPoolExecutor(workers) as pool:
        results = list(pool.map(task, tasks, chunksize=1))
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "development_probe.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, indent=1))
    tmp.replace(target)
    table(results)
