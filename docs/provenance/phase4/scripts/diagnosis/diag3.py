"""Exploratory: online (ACI-style) margin calibration on rural1, full year (development network)."""
import numpy as np
from pathlib import Path
from gridpulse.grid import load_network, absolute_profiles, cap_pv
from gridpulse.grid_study import daily_arrays, CAP_LEVELS
cache = Path("outputs/grid_study/physics_cache")
SCALE = np.array([0.1, 0.1, 100.0, 100.0], dtype=np.float32)
def norm(m):
    x = (m / SCALE).max(-1)
    return np.where(np.isnan(m).any(-1), np.inf, x)
days = list(range(63, 365))
N = {d: norm(np.load(cache / f"day_{d:03d}.npy")) for d in range(35, 365)}  # sets x 96 x 11
net = load_network(); arrays = daily_arrays(absolute_profiles(net)); rating = net.sgen["sn_mva"].to_numpy()
def curtailed(day, lvl):
    a = arrays["sgen_p_mw"][day]
    return sum((a[t] - cap_pv(a[t], rating, CAP_LEVELS[lvl[t]])).sum() for t in range(96)) * 0.25
def run(ensemble, q, gamma, beta, tau0=0.0, fixed=False):
    tau = tau0; V = E = 0.0; taus = []
    for d in days:
        M = N[d][2:] if ensemble == "scen" else np.stack([N[j][0] for j in range(d-28, d)])
        qth = -np.sort(-M, axis=0)[q-1]          # q-th largest margin per step x level
        acc = qth <= -tau
        lvl = np.where(acc.any(1), acc.argmax(1), 10)
        cnt = int((N[d][0][np.arange(96), lvl] > 0).sum())
        V += cnt; E += curtailed(d, lvl); taus.append(tau)
        if not fixed: tau += gamma * (cnt - beta)
    return V, E, np.min(taus), np.max(taus)
print("days", len(days))
for k in (6, 7):
    lv = np.full(96, k); print(f"static cap {CAP_LEVELS[k]}: V={sum(int((N[d][0][np.arange(96), lv] > 0).sum()) for d in days)}, E={sum(curtailed(d, lv) for d in days):.2f}")
lv = None
V = sum(int((N[d][0].min(1) > 0).sum()) for d in days); print("oracle-ish unavoidable", V)
olv = lambda d: np.where((N[d][0] <= 0).any(1), (N[d][0] <= 0).argmax(1), 10)
print(f"oracle: E={sum(curtailed(d, olv(d)) for d in days):.2f}")
for ens in ("scen", "replay"):
    for q in (1, 2):
        V, E, lo, hi = run(ens, q, 0, 0, fixed=True); print(f"{ens} q={q} fixed tau=0: V={V:.0f} E={E:.2f}")
    for beta in (0.1, 0.3):
        for gamma in (0.002, 0.01):
            V, E, lo, hi = run(ens, 1, gamma, beta)
            print(f"{ens} q=1 ACI beta={beta} gamma={gamma}: V={V:.0f} (target {beta*len(days):.0f}) E={E:.2f} tau range [{lo:.3f},{hi:.3f}]")
