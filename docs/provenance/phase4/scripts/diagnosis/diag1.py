"""Exploratory diagnosis on rural1 (now a development network): why does scenario risk
underperform the historical-frequency reference? Uses the cached physics only."""
import numpy as np, pandas as pd
from pathlib import Path
from gridpulse.grid import is_violation
from gridpulse import grid_study as gs

cache = Path("outputs/grid_study/physics_cache")
days = list(range(35, 365))
V = {d: is_violation(np.load(cache / f"day_{d:03d}.npy")) for d in days}  # sets x 96 x 11
first = 63  # replay window complete (d-28 >= 35)
D = [d for d in days if d >= first]
scen = np.stack([V[d][2:].mean(0) for d in D])            # days x 96 x 11
replay = np.stack([np.mean([V[j][0] for j in range(d-28, d)], 0) for d in D])
obs = np.stack([V[d][0] for d in D]).astype(float)
month = np.array([(gs.FIRST_DAY + pd.Timedelta(days=d)).month for d in D])

def murphy(p, y):
    vals = np.unique(p); n = len(p); ybar = y.mean(); rel = res = 0.0
    for v in vals:
        m = p == v; nk = m.sum(); ok = y[m].mean()
        rel += nk * (v - ok) ** 2; res += nk * (ok - ybar) ** 2
    return dict(brier=float(((p-y)**2).mean()), reliability=rel/n, resolution=res/n, uncertainty=ybar*(1-ybar))

def auc(p, y):
    from scipy.stats import rankdata
    r = rankdata(p); n1 = y.sum(); n0 = len(y) - n1
    return float((r[y == 1].sum() - n1*(n1+1)/2) / (n1*n0))

print(f"days {D[0]}..{D[-1]} n={len(D)}")
for k in (0,):
    p_s, p_r, y = scen[:,:,k].ravel(), replay[:,:,k].ravel(), obs[:,:,k].ravel()
    print("cap level", k, "obs rate", y.mean().round(4), "mean scen", p_s.mean().round(4), "mean replay", p_r.mean().round(4))
    print(" scen  ", {a: round(b, 5) for a, b in murphy(p_s, y).items()}, "AUC", round(auc(p_s, y), 4))
    print(" replay", {a: round(b, 5) for a, b in murphy(p_r, y).items()}, "AUC", round(auc(p_r, y), 4))
    clim = np.full_like(y, y.mean())
    print(" by month: month obs scen replay")
    for m in sorted(set(month)):
        sel = np.repeat(month == m, 96)
        print("  ", m, round(y[sel].mean(),4), round(p_s[sel].mean(),4), round(p_r[sel].mean(),4))

print("\nFixed-level calibration (no selection), totals over all steps: level cap obs scen replay")
for k in range(11):
    print(f"  {k:2d} {gs.CAP_LEVELS[k]:.1f} {obs[:,:,k].sum():6.0f} {scen[:,:,k].sum():8.1f} {replay[:,:,k].sum():8.1f}")

print("\nChosen-level (rule: largest cap with risk <= 0.05), over all steps with risk_at_nocap > 0:")
for name, R in (("scen", scen), ("replay", replay)):
    acc = R <= 0.05
    lvl = np.where(acc.any(2), acc.argmax(2), 10)
    active = R[:,:,0] > 0
    pred = np.take_along_axis(R, lvl[...,None], 2)[...,0]
    real = np.take_along_axis(obs, lvl[...,None], 2)[...,0]
    print(f"  {name}: active steps {active.sum()}, realised {real[active].sum():.0f}, predicted {pred[active].sum():.1f}, "
          f"all-step realised {real.sum():.0f}; inactive-step violations {real[~active].sum():.0f}")
    # selection effect: at chosen level vs same level without selection
