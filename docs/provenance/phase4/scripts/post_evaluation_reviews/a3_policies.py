"""Ensemble member dominance, point_margin degeneracy, rural3 replay_aci vs static."""
import numpy as np, pickle, os, csv
from pathlib import Path
from gridpulse import dual_study as ds, grid_study
CACHE = Path("outputs/dual_study/physics_cache")
OUT = Path(os.path.dirname(__file__))
avail = pickle.load(open(OUT/"avail.pkl","rb"))
EVAL = list(range(182, 365))
ENS = ("tap_raise_lv","tap_lower_lv","pv_cosphi_p","pv_fixed_095","storage_greedy","storage_profile")
CAP = grid_study.CAP_LEVELS
def nrm(a): return ds.normalised(a)
rows = list(csv.DictReader(open("outputs/dual_study/evaluation_daily_outcomes.csv")))
tau_tbl = {(r['network'], r['information'], r['truth'], int(r['day'])): r for r in rows}
PMT = {"1-LV-rural1--2-sw":0.70,"1-LV-rural2--2-sw":0.41,"1-LV-rural3--2-sw":0.34,"1-LV-semiurb4--2-sw":0.75,"1-LV-semiurb5--2-sw":0.58,"1-LV-urban6--2-sw":0.53}
for code in ds.HOSTING_CAPACITY:
    pv, rating, load = avail[code]
    lv_static = 7 if "rural1" in code else 6
    raw = {d: np.load(CACHE/code/"nominal"/f"day_{d:03d}.npy") for d in range(EVAL[0]-28, 365)}
    norm = {d: nrm(a) for d, a in raw.items()}
    normv = {v: {d: nrm(np.load(CACHE/code/v/f"day_{d:03d}.npy")) for d in EVAL} for v in ENS}
    tot_av = pv[182:365].sum()*0.25
    # --- ensemble F1 and leave-one-member-out
    def ens_curt(members):
        c = 0.0; dom = {v:0 for v in members}; deep=0
        for d in EVAL:
            point = norm[d][1]; scen = norm[d][2:].max(0)
            shifts = np.stack([np.where(np.isnan(normv[v][d][1]-point), np.inf, normv[v][d][1]-point) for v in members])
            shift = shifts.max(0)
            lv = ds.first_safe(scen + np.maximum(shift, 0))
            c += ds.curtailed_mwh(pv[d], rating, lv)
            # dominant member at the static level for daylight steps where shift>0
            dl = pv[d].sum(-1) > 0
            am = shifts[:, :, lv_static].argmax(0)
            for i, v in enumerate(members):
                dom[v] += int(((am == i) & dl & (shift[:, lv_static] > 0)).sum())
        return c, dom
    full, dom = ens_curt(ENS)
    print(f"\n=== {code} available {tot_av:.1f} MWh | ensemble F1 curtail {full:.1f} | dominant member (daylight steps, at static level): {dom}")
    for v in ENS:
        c, _ = ens_curt(tuple(m for m in ENS if m != v))
        print(f"   without {v:15s}: {c:6.1f} MWh")
    # mean shift (normalised) of each member at static level at midday daylight
    for v in ENS:
        sh = np.concatenate([(normv[v][d][1]-norm[d][1])[:, lv_static][pv[d].sum(-1)>0] for d in EVAL])
        print(f"   shift {v:15s} median {np.nanmedian(sh):+.3f} p95 {np.nanpercentile(sh,95):+.3f}")
    # --- point_margin degeneracy
    tau = PMT[code]; c=0; cap0=0; nday=0
    for d in EVAL:
        lv = ds.first_safe(norm[d][1], tau); dl = pv[d].sum(-1)>0
        c += ds.curtailed_mwh(pv[d], rating, lv); cap0 += int(((lv==10)&dl).sum()); nday += int(dl.sum())
    print(f"   point_margin tau {tau}: curtail {c:.1f} MWh = {100*c/tot_av:.0f}% of available; daylight steps at cap 0: {100*cap0/nday:.0f}%")
    # zero-PV normalised voltage margin (cap 0) on forecast set
    z = np.concatenate([raw[d][1][:, 10, 0][pv[d].sum(-1)>0] for d in EVAL])/0.1
    print(f"   forecast-set normalised OV margin at cap 0, daylight: median {np.median(z):.3f} max {z.max():.3f}")
    # --- replay_aci vs static (F1 nominal), reconstruct with applied tau
    c_r = 0; c_s = 0; deeper=0; shallower=0; bind={0:0,1:0,2:0,3:0}; month_extra = {}
    for d in EVAL:
        r = tau_tbl[(code, "forecast", "nominal", d)]
        t = float(r["replay_aci__tau"])
        rep_raw = np.stack([raw[j][0] for j in range(d-28, d)])  # 28 x 96 x 11 x 4
        rep = nrm(rep_raw).max(0)
        lv = ds.first_safe(rep, t); dl = pv[d].sum(-1)>0
        cr = ds.curtailed_mwh(pv[d], rating, lv); cs = ds.curtailed_mwh(pv[d], rating, np.full(96, lv_static))
        c_r += cr; c_s += cs
        mth = (np.datetime64('2016-01-01') + np.timedelta64(d,'D')).astype('datetime64[M]')
        month_extra[str(mth)] = month_extra.get(str(mth), 0) + cr - cs
        deep_steps = dl & (lv > lv_static)
        deeper += int(deep_steps.sum()); shallower += int((dl & (lv < lv_static)).sum())
        # binding type at static level in replay worst-case for deeper steps
        worst = (rep_raw[:, :, lv_static, :] / ds.MARGIN_SCALE)  # 28 x 96 x 4
        typ = worst.max(0).argmax(-1)
        for i in range(4): bind[i] += int((deep_steps & (typ == i)).sum())
    print(f"   replay_aci recon curtail {c_r:.1f} vs static {c_s:.1f}; daylight steps deeper than static {deeper}, shallower {shallower}; binding type at static level on deeper steps (OV,UV,line,trafo) {bind}")
    print("   extra MWh by month:", {k: round(v,1) for k, v in month_extra.items()})
