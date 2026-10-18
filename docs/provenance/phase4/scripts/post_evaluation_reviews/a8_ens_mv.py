import numpy as np, pickle, os
from pathlib import Path
from gridpulse import dual_study as ds
CACHE = Path("outputs/dual_study/physics_cache")
avail = pickle.load(open(Path(os.path.dirname(__file__))/"avail.pkl","rb"))
ENS = ("tap_raise_lv","tap_lower_lv","pv_cosphi_p","pv_fixed_095","storage_greedy","storage_profile")
for code in ["1-LV-rural2--2-sw","1-LV-rural3--2-sw","1-LV-urban6--2-sw","1-LV-semiurb4--2-sw"]:
    pv, rating, _ = avail[code]
    for truth in ["mv_high","joint_loading"]:
        n_viol=0; types=np.zeros(4,int); vmax=0; lmax=0; exceed=[]
        for d in range(182,365):
            nom = ds.normalised(np.load(CACHE/code/"nominal"/f"day_{d:03d}.npy"))
            point = nom[1]; scen = nom[2:].max(0)
            shift = np.max([ds.normalised(np.load(CACHE/code/v/f"day_{d:03d}.npy"))[1]-point for v in ENS], axis=0)
            lv = ds.first_safe(scen + np.maximum(shift,0))
            tr = np.load(CACHE/code/truth/f"day_{d:03d}.npy")[0][np.arange(96), lv]  # 96 x 4
            dl = pv[d].sum(-1)>0
            v = (tr>0)&dl[:,None]
            n_viol += v.any(1).sum(); types += v.sum(0)
            if v[:,0].any(): exceed += list(tr[v[:,0],0])
            if dl.any(): vmax=max(vmax, tr[dl,0].max()); lmax=max(lmax, tr[dl,2:].max())
        ex = np.array(exceed) if exceed else np.array([0.0])
        print(code[5:-5], truth, "ensemble viol", n_viol, "by type OV/UV/line/trafo", types.tolist(), f"maxV {1.1+vmax:.4f} max loading {100+lmax:.1f}% | OV exceedance median {np.median(ex)*1000:.1f} mV-pu(x1e-3) p90 {np.percentile(ex,90)*1000:.1f}")
