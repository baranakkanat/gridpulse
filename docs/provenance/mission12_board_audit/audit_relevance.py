"""Mission 12 board audit, ZERO new solves: thermal decision relevance from the Phase 5 nominal
full-state cache (outputs/sense_study/fullstate_cache/<net>/nominal/day_DDD.npz)."""
import sys, json, collections
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np
from gridpulse import dual_study as ds, grid, grid_study
from gridpulse.grid_study import CAP_LEVELS
ROOT = str(__import__("pathlib").Path(__file__).resolve().parents[3] / "outputs" / "sense_study" / "fullstate_cache")  # edited
out = {}
for code in ds.HOSTING_CAPACITY:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    sn = net.sgen.sn_mva.to_numpy(float); L = len(net.line)
    stats = collections.Counter(); block_line = collections.Counter(); block_line_rb = {0.2: collections.Counter(), 0.3: collections.Counter()}
    export = collections.defaultdict(float); maxload_line = np.zeros(L)
    for day in range(35, 365):
        d = np.load(f"{ROOT}/{code}/nominal/day_{day:03d}.npz")
        line, trafo, margins = d["line"], d["trafo"], d["margins"]          # (96,11,L), (96,11,4), (96,11,4)
        avail = arrays["sgen_p_mw"][day]                                     # (96, N)
        for t in range(96):
            if avail[t].sum() <= 1e-9: continue
            stats["daylight"] += 1
            exp_lv = np.array([np.minimum(avail[t], c * sn).sum() for c in CAP_LEVELS]) * 0.25
            v_ok = margins[t, :, 0] <= 0
            tr_ok = trafo[t, :, 2] <= 100.0
            maxload_line = np.maximum(maxload_line, np.nan_to_num(line[t, 0]))
            def choose(line_lim, tr_lim=100.0):
                ok = v_ok & (trafo[t, :, 2] <= tr_lim) & np.all(line[t] <= line_lim, axis=1)
                idx = np.flatnonzero(ok)
                return (int(idx.min()) if idx.size else 10), ok
            lvl, ok = choose(100.0)
            export["recorded"] += exp_lv[lvl]; export["nocap"] += exp_lv[0]
            if lvl > 0:
                stats["curtail_recorded"] += 1
                j = lvl - 1   # next higher cap level: what blocks it?
                kinds = []
                if not v_ok[j]: kinds.append("V")
                if trafo[t, j, 2] > 100: kinds.append("T")
                bl = np.flatnonzero(line[t, j] > 100.0)
                if bl.size: kinds.append("L"); block_line.update(bl.tolist())
                stats["block_" + "+".join(kinds)] += 1
            for w in (0.2, 0.3):
                lv2, _ = choose(100.0 * (1 - w))
                export[f"robust_lines_w{w}"] += exp_lv[lv2]
                if lv2 > lvl: stats[f"robust_w{w}_more_curtail"] += 1
                if lv2 > 0:
                    j = lv2 - 1; bl = np.flatnonzero(line[t, j] > 100.0 * (1 - w))
                    if bl.size and v_ok[j] and trafo[t, j, 2] <= 100: block_line_rb[w].update(bl.tolist())
                lv3, _ = choose(100.0 * (1 - w), 100.0 * (1 - w))
                export[f"robust_all_w{w}"] += exp_lv[lv3]
    out[code] = {
        "lines": L, "pv_units": len(sn), "daylight_steps": stats["daylight"],
        "curtail_steps_recorded": stats["curtail_recorded"],
        "block_types_recorded": {k[6:]: v for k, v in stats.items() if k.startswith("block_")},
        "distinct_blocking_lines_recorded": len(block_line), "top_blocking_lines_recorded": block_line.most_common(4),
        "lines_ever_over_100_noaction": int((maxload_line > 100).sum()), "lines_ever_over_70_noaction": int((maxload_line > 70).sum()),
        "robust_more_curtail_steps": {w: stats[f"robust_w{w}_more_curtail"] for w in (0.2, 0.3)},
        "distinct_blocking_lines_robust": {w: len(block_line_rb[w]) for w in (0.2, 0.3)},
        "export_MWh": {k: round(v, 3) for k, v in export.items()},
    }
    print(code, json.dumps(out[code]))
json.dump(out, open("audit_relevance.json", "w"), indent=1)  # edited: was a local scratch path
