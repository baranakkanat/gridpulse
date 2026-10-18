"""Development-half survey of SimBench LV networks (no action and PV cap 0, storage idle)."""
import json, sys, time
from multiprocessing import Pool
import numpy as np

DEV_DAYS = range(0, 182)
import json as _j
_R = _j.load(open("/private/tmp/claude-501/-Users-baranakkanat-Developer-gridpulse/694472ba-46d0-4918-a7a3-5fa8e72fce5c/scratchpad/survey/hosting_capacity_dev.json"))
_h1 = [r for r in _R if "rural1" in r["network"]][0]["hosting_capacity_scale"]
SCALES = {r["network"]: r["hosting_capacity_scale"] / _h1 for r in _R}
SCALES["1-LV-rural1--2-sw"] = 1.0  # 2016-01-01 .. 2016-06-30 UTC

def survey(code):
    import simbench
    from gridpulse.grid import GridSolver, MARGINS, is_violation, load_network, absolute_profiles
    from gridpulse.grid_study import daily_arrays
    raw = simbench.get_simbench_net(code)
    from gridpulse.dual_study import variant_network, NOMINAL
    net = variant_network(code, NOMINAL, SCALES[code])
    t = net.trafo
    info = {
        "code": code, "buses": len(net.bus), "lines": len(net.line), "loads": len(net.load),
        "sgens": len(net.sgen), "storage": len(net.storage), "trafos": len(t),
        "trafo_sn_mva": t["sn_mva"].tolist(), "tap_pos": t["tap_pos"].tolist(),
        "tap_neutral": t["tap_neutral"].tolist(), "tap_side": t["tap_side"].tolist(),
        "tap_step_percent": t["tap_step_percent"].tolist(),
        "tap_min": t["tap_min"].tolist(), "tap_max": t["tap_max"].tolist(),
        "tap_changer_type_raw": raw.trafo["tap_changer_type"].astype(str).tolist(),
        "ext_grid_vm_pu": net.ext_grid["vm_pu"].tolist(),
        "lv_vm_limits": sorted(set(zip(net.bus["min_vm_pu"], net.bus["max_vm_pu"]))),
        "line_max_loading": sorted(set(net.line["max_loading_percent"])),
        "trafo_max_loading": sorted(set(t["max_loading_percent"])),
        "pv_sn_mva_total": float(net.sgen["sn_mva"].sum()),
        "pv_p_mw_total": float(net.sgen["p_mw"].sum()),
        "sgen_types": sorted(set(net.sgen["type"].astype(str))),
        "sgen_profiles": sorted(set(net.sgen["profile"].astype(str))),
        "storage_p_mw_total": float(net.storage["p_mw"].abs().sum()) if len(net.storage) else 0.0,
        "storage_max_e_mwh_total": float(net.storage["max_e_mwh"].sum()) if len(net.storage) else 0.0,
        "load_p_mw_total": float(net.load["p_mw"].sum()),
    }
    arrays = daily_arrays(absolute_profiles(net))
    solver = GridSolver(net)
    storage = np.zeros(len(net.storage))
    rating = solver.pv_rating_mw
    n = len(DEV_DAYS) * 96
    m_none = np.empty((n, 4)); m_cap0 = np.empty((n, 4)); i = 0
    peak_ratio = 0.0
    t0 = time.perf_counter()
    for day in DEV_DAYS:
        solver.reset()
        for s in range(96):
            lp, lq, pv = (arrays[k][day, s] for k in ("load_p_mw", "load_q_mvar", "sgen_p_mw"))
            peak_ratio = max(peak_ratio, float(np.max(pv / rating)))
            m_none[i] = solver.solve(lp, lq, pv, storage)
            m_cap0[i] = solver.solve(lp, lq, np.zeros_like(pv), storage)
            i += 1
    seconds = time.perf_counter() - t0
    v_none, v_cap0 = is_violation(m_none), is_violation(m_cap0)
    with np.errstate(invalid="ignore"):
        info.update({
            "ms_per_flow": 1000 * seconds / (2 * n),
            "dev_steps": n,
            "nonconverged_no_action": int(np.isnan(m_none).any(1).sum()),
            "nonconverged_cap0": int(np.isnan(m_cap0).any(1).sum()),
            "viol_no_action": int(v_none.sum()),
            "viol_cap0": int(v_cap0.sum()),
            "pv_driven": int((v_none & ~v_cap0).sum()),
            "persist_at_cap0": int((v_none & v_cap0).sum()),
            "only_at_cap0": int((~v_none & v_cap0).sum()),
            "by_type_no_action": {k: int((m_none[:, j] > 0).sum()) for j, k in enumerate(MARGINS)},
            "by_type_cap0": {k: int((m_cap0[:, j] > 0).sum()) for j, k in enumerate(MARGINS)},
            "max_vm_pu_excess": float(np.nanmax(m_none[:, 0])),
            "min_vm_pu_deficit": float(np.nanmax(m_none[:, 1])),
            "max_line_margin_pct": float(np.nanmax(m_none[:, 2])),
            "max_trafo_margin_pct": float(np.nanmax(m_none[:, 3])),
            "pv_peak_over_rating": peak_ratio,
            "violation_days": int(v_none.reshape(-1, 96).any(1).sum()),
        })
    return info

if __name__ == "__main__":
    codes = [f"1-LV-{n}--2-sw" for n in ("rural2", "rural3", "semiurb4", "semiurb5", "urban6")]
    with Pool(5) as pool:
        results = pool.map(survey, codes, chunksize=1)
    json.dump(results, open(sys.argv[1], "w"), indent=1, default=str)
    print("done")
