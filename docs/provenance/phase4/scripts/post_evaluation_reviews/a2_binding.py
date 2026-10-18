"""Which constraint binds for static_dev under variant truths (evaluation days, realised set)."""
import numpy as np, pickle, os
from pathlib import Path
from gridpulse import dual_study as ds, grid_study
from gridpulse.grid import absolute_profiles
CACHE = Path("outputs/dual_study/physics_cache")
OUT = Path(os.path.dirname(__file__))
EVAL = range(182, 365)
TRUTHS = ["nominal","tap_raise_lv","tap_lower_lv","pv_fixed_095","mv_high","joint_realistic","joint_loading","storage_profile"]
avail = {}
for code in ds.HOSTING_CAPACITY:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    arr = grid_study.daily_arrays(absolute_profiles(net))
    avail[code] = (arr["sgen_p_mw"], net.sgen.sn_mva.to_numpy(float), arr["load_p_mw"])
pickle.dump(avail, open(OUT/"avail.pkl","wb"))
names = ["OV","UV","line","trafo"]
for code in ds.HOSTING_CAPACITY:
    pv, rating, load = avail[code]
    lvl = 7 if "rural1" in code else 6
    print(f"\n=== {code}  static level {lvl} (cap {grid_study.CAP_LEVELS[lvl]})  PV avail eval MWh {pv[182:365].sum()*0.25:.1f}")
    for truth in TRUTHS:
        m = np.stack([np.load(CACHE/code/truth/f"day_{d:03d}.npy")[0] for d in EVAL])  # days x 96 x 11 x 4
        day = pv[182:365].sum(-1) > 0
        at = m[:, :, lvl, :]  # days x 96 x 4
        viol = (at > 0) & day[..., None]
        anyv = viol.any(-1)
        norm = (at / ds.MARGIN_SCALE).max(-1)
        sev = (norm > 0.2)
        # which type is argmax of normalised margin at violating steps
        arg = (at / ds.MARGIN_SCALE).argmax(-1)
        night = ~(pv[182:365].sum(-1) > 0)
        vmax_night = 1.10 + m[:, :, 0, 0][night]
        # zero-PV voltage: noon-ish steps at cap 0 (level 10)
        v_cap0 = 1.10 + m[:, :, 10, 0][day]
        print(f"{truth:16s} viol {anyv.sum():5d} | by type " + " ".join(f"{n}:{viol[...,i].sum():5d}" for i,n in enumerate(names))
              + f" | argmax " + " ".join(f"{n}:{((arg==i)&anyv).sum()}" for i,n in enumerate(names))
              + f" | severe {(sev & day).sum():4d} (OV-driven {((arg==0)&sev&day).sum()})"
              + f" | peak norm {norm[day].max():.3f} type {names[np.unravel_index(np.argmax(np.where(day,norm,-9)), norm.shape) and arg[np.unravel_index(np.argmax(np.where(day,norm,-9)), norm.shape)]]}"
              + f" | maxV night {vmax_night.max():.3f} med {np.median(vmax_night):.3f} | maxV cap0 daylight {v_cap0.max():.3f} med {np.median(v_cap0):.3f}"
              + f" | maxV@static {1.10+at[...,0][day].max():.3f} max line% {100+at[...,2][day].max():.0f} max trafo% {100+at[...,3][day].max():.0f}")
