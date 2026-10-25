"""Board audit, zero power flows: SimBench LV network sizes, PV units, profile types, correlation."""
import sys
from pathlib import Path
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np
from gridpulse import dual_study as ds, grid, grid_study
for code in ds.HOSTING_CAPACITY:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    s = net.sgen
    prof = s["profile"].value_counts().to_dict() if "profile" in s.columns else "n/a"
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    pv = np.asarray(arrays["sgen_p_mw"])  # [days, steps, sgen]
    day = pv.reshape(-1, pv.shape[-1]); day = day[day.sum(axis=1) > 0]
    c = np.corrcoef(day.T) if day.shape[1] > 1 else np.array([[1.0]])
    off = c[~np.eye(len(c), dtype=bool)]
    sv = np.linalg.svd((day - day.mean(0)) / (day.std(0) + 1e-12), compute_uv=False)
    erank = float(np.exp(-np.sum((sv**2 / np.sum(sv**2)) * np.log(sv**2 / np.sum(sv**2) + 1e-300))))
    loads = net.load
    print(f"{code}: buses {len(net.bus)} lines {len(net.line)} loads {len(loads)} sgens {len(s)} "
          f"pv_MW {s.sn_mva.sum():.3f} pv_scale {ds.pv_scale(code):.3f} profiles {prof} "
          f"| daylight steps {day.shape[0]} mean pair corr {off.mean():.4f} min {off.min():.4f} eff.rank {erank:.2f} "
          f"cond {sv[0]/max(sv[-1],1e-12):.3g} | sgen buses unique {s.bus.nunique()} loads w/ sgen bus {loads.bus.isin(s.bus).sum()}")
    print("   max_vm", sorted(set(net.bus.max_vm_pu.round(3))), "line max_loading", sorted(set(net.line.max_loading_percent.round(1)))[:3], "trafo", net.trafo[["sn_mva","tap_pos"]].to_dict("records"))
