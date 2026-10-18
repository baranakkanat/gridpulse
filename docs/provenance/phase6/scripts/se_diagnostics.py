"""Phase 6, development days only: can a chi-square test on the WLS objective detect the
gross state-estimation errors seen in Phase 5? Exploratory diagnostics run before the
Phase 6 protocol was registered; they read no evaluation day.

Sample as in Phase 5 (every third development day, 11:00-14:00 UTC, no action),
realistic readings with identity-based noise. Per step: estimator success, the weighted
residual sum J and its degrees of freedom, the estimate's largest voltage and line-loading
errors against the true state, true events and both detectors' flags. Usage:

    python docs/provenance/phase6/scripts/se_diagnostics.py [workers]
"""

import copy
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import estimation as es
from gridpulse import fullstate, grid_study
from gridpulse import sensing as sn
from gridpulse.grid import absolute_profiles

OUT = Path("outputs/noise_study/exploratory")
P4 = Path("outputs/dual_study/physics_cache")
FS = Path("outputs/sense_study/fullstate_cache")
_W: dict = {}


def init(code: str) -> None:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    arrays = grid_study.daily_arrays(absolute_profiles(net))
    _W.clear()
    _W.update(net=net, series=es.bus_series(net, arrays), layout=sn.network_layout(net),
              available=arrays["sgen_p_mw"], cache={})  # fmt: skip


def task(args) -> list[dict]:
    code, truth, day, configs, truth_norm = args
    net, layout, series = _W["net"], _W["layout"], _W["series"]
    state = fullstate.load_states(FS, code, truth, [day])[day]
    events = sn.true_events(truth_norm, state, 0, layout)
    daylight = _W["available"][day].sum(axis=1) > 0
    limits = np.array(layout.max_vm)
    model = sn.CONDITIONS["realistic"]
    bank = sn.NoiseBank(code, truth, 0)
    work = copy.deepcopy(net)
    rows = []
    for name, config in configs.items():
        readings = sn.measure(state, np.zeros(96, int), config, layout, model, None, noise=bank,
                              day=day)  # fmt: skip
        sub, remote = sn.flagged_steps(readings, config, layout)
        inputs = es.estimator_inputs(config)
        for t in es.SE_STEPS:
            if not daylight[t]:
                continue
            pseudo = es.pseudo_measurements(series, day, t)
            m = es.add_measurements(work, readings, t, inputs, layout, model, pseudo, inplace=True)
            result = es.estimate(m, _W["cache"])
            row = {"network": code, "truth": truth, "config": name, "day": day, "step": t,
                   "success": result["success"], "event": bool(events["any"][t]),
                   "event_voltage": bool(events["voltage"][t]),
                   "direct_flag": bool(sub[t] or remote[t])}  # fmt: skip
            if result["success"]:
                estimated = np.array([result["vm"][b] for b in layout.buses])
                row.update(
                    objective=result["objective"], dof=result["dof"],
                    max_error_vm=float(np.max(np.abs(estimated - state["vm"][t, 0]))),
                    max_error_loading=float(np.max(np.abs(result["line_loading"]
                                                          - state["line"][t, 0]))),
                    se_flag=bool((estimated > limits).any()
                                 or (result["line_loading"] > 100.0).any()
                                 or readings["trafo_loading"][t, 0] > 100.0),
                )  # fmt: skip
            rows.append(row)
    return rows


if __name__ == "__main__":
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    dev = json.loads(Path("outputs/sense_study/development_results.json").read_text())
    days = [d for d in grid_study.period_days("development")
            if d >= ds.FIRST_DECISION_DAY and d % es.SE_DAY_STRIDE == 0]  # fmt: skip
    rows: list[dict] = []
    for code in ds.HOSTING_CAPACITY:
        contexts, layout, _ = sn.build_contexts(code, P4, FS, "development")
        base = sn.Config("substation", transformer=True, heads=layout.feeder_heads)
        configs = {"substation": base, "substation+2:topology": sn.with_remote(
            base, dev[code]["placements"]["topology"][:2], "substation+2:topology")}  # fmt: skip
        tasks = [(code, truth, day, configs, contexts[truth].truth_norm[day])
                 for truth in fullstate.TRUTHS for day in days]  # fmt: skip
        del contexts
        with ProcessPoolExecutor(workers, initializer=init, initargs=(code,)) as pool:
            for part in pool.map(task, tasks, chunksize=2):
                rows += part
        print(code, len(rows), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "se_diagnostics.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows))
    tmp.replace(target)
    print(f"wrote {target}: {len(rows)} steps")
