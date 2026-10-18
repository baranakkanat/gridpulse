"""Phase 6, development days only: why does noisy feedback over-curtail, and how do simple
alarm rules change that? Exploratory diagnostics run before the Phase 6 protocol was
registered; they read no evaluation day.

For every network and truth, `replay_aci` runs on development days with identity-based
noise (`sensing.NoiseBank`, common random numbers) for three telemetry configurations,
several measurement conditions and a small grid of alarm rules. It also records how far
true violations exceed their limits at no action. Usage, from the repository root:

    python docs/provenance/phase6/scripts/development_diagnostics.py [workers]
"""

import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import fullstate, grid_study
from gridpulse import sensing as sn

OUT = Path("outputs/noise_study/exploratory")
P4 = Path("outputs/dual_study/physics_cache")
FS = Path("outputs/sense_study/fullstate_cache")
NOISY = {"sigma_v_substation": 0.002, "sigma_loading": 0.01}
CONDITIONS = {
    "exact": sn.MeasurementModel(),
    "noisy_0.005": sn.MeasurementModel(sigma_v_remote=0.005, **NOISY),
    "noisy_0.01": sn.MeasurementModel(sigma_v_remote=0.01, **NOISY),
    "noisy_0.02": sn.MeasurementModel(sigma_v_remote=0.02, **NOISY),
    "bias_0.005": sn.MeasurementModel(sigma_v_remote=0.002, sigma_bias_remote=0.005, **NOISY),
    "realistic": sn.CONDITIONS["realistic"],
}
RULES = [sn.AlarmRule("unfiltered"), sn.AlarmRule("guard1", 1.0), sn.AlarmRule("guard2", 2.0),
         sn.AlarmRule("persist2", 0.0, 2), sn.AlarmRule("persist3", 0.0, 3),
         sn.AlarmRule("guard2_persist2", 2.0, 2)]  # fmt: skip
EXTRA = ("flagged_steps", "false_alarm_steps", "missed_steps", "intervention_steps")


def magnitudes(ctx) -> dict:
    """How far avoidable true violations at no action exceed their limit (development)."""
    limits = np.array(ctx.layout.max_vm)
    volt, line = [], []
    for day in ctx.development:
        state, daylight = ctx.states[day], ctx.available[day].sum(axis=1) > 0
        events = sn.true_events(ctx.truth_norm[day], state, 0, ctx.layout)
        for t in np.flatnonzero(events["voltage"] & daylight):
            volt.append(float((state["vm"][t, 0] - limits).max()))
        for t in np.flatnonzero(events["line"] & daylight):
            line.append(float(state["line"][t, 0].max() - 100.0))

    def summary(values, cuts):
        if not values:
            return {"n": 0}
        v = np.array(values)
        return {"n": len(v), "median": float(np.median(v)), "p90": float(np.quantile(v, 0.9)),
                **{f"share_below_{c}": float((v < c).mean()) for c in cuts}}  # fmt: skip

    return {"voltage_pu": summary(volt, (0.005, 0.01, 0.02)),
            "line_percent": summary(line, (1.0, 2.0, 5.0))}  # fmt: skip


def task(args):
    code, truth, placements = args
    contexts, layout, _ = sn.build_contexts(code, P4, FS, "development", truths=(truth,))
    ctx = contexts[truth]
    base = sn.Config("substation", transformer=True, heads=layout.feeder_heads)
    configs = {
        "substation": base,
        "substation+2:topology": sn.with_remote(base, placements["topology"][:2], "t2"),
        "full": sn.standard_configs(layout, ctx.states[ctx.days[0]]["line"].shape[2])["full"],
    }
    online = ds.OnlineSettings()
    rows = []
    for cname, config in configs.items():
        for condition, model in CONDITIONS.items():
            for rule in RULES:
                if condition == "exact" and rule.guard and rule.persistence == 1:
                    continue  # a guard has no effect on exact readings
                bank = sn.NoiseBank(code, truth, 0)
                records = sn.run_feedback_policy(
                    ctx, "replay_aci", config, model, 0, online, noise=bank, alarm=rule
                )
                summary = sn.summarise_decisions(records, online)
                summary.update({k: float(sum(r[k] for r in records)) for k in EXTRA})
                summary["mean_tau"] = float(np.mean([r["tau"] for r in records]))
                rows.append({"network": code, "truth": truth, "config": cname,
                             "condition": condition, "rule": rule.name, **summary})  # fmt: skip
    static = sn.run_feedback_policy(ctx, "static_dev", configs["substation"], CONDITIONS["exact"],
                                    0, online)  # fmt: skip
    oracle = sn.run_feedback_policy(ctx, "oracle", configs["substation"], CONDITIONS["exact"], 0,
                                    online)  # fmt: skip
    refs = {name: sn.summarise_decisions(r, online) for name, r in
            (("static_dev", static), ("oracle", oracle))}  # fmt: skip
    return {"network": code, "truth": truth, "rows": rows, "references": refs,
            "magnitudes": magnitudes(ctx)}  # fmt: skip


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    dev = json.loads(Path("outputs/sense_study/development_results.json").read_text())
    tasks = [(code, truth, dev[code]["placements"]) for code in ds.HOSTING_CAPACITY
             for truth in fullstate.TRUTHS]  # fmt: skip
    assert all(d < min(grid_study.period_days("evaluation")) for d in
               grid_study.period_days("development"))  # fmt: skip
    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(task, tasks, chunksize=1))
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "development_diagnostics.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(results, indent=1))
    tmp.replace(target)
    print(f"wrote {target}: {sum(len(r['rows']) for r in results)} runs")
