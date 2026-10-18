"""Cross-fitted selection test on rural1 (development network)."""
import numpy as np
from pathlib import Path
from gridpulse.grid import is_violation
cache = Path("outputs/grid_study/physics_cache")
days = list(range(63, 365))
V = {d: is_violation(np.load(cache / f"day_{d:03d}.npy")) for d in range(35, 365)}
obs = np.stack([V[d][0] for d in days]).astype(float)
S = np.stack([V[d][2:] for d in days])          # days x 28 x 96 x 11
R = np.stack([np.stack([V[j][0] for j in range(d-28, d)]) for d in days])  # replay members
def chosen(count, c):
    acc = count <= c
    return np.where(acc.any(-1), acc.argmax(-1), 10)
def take(x, lvl): return np.take_along_axis(x, lvl[..., None], -1)[..., 0]
for name, M in (("scenario", S), ("replay", R)):
    A, B = M[:, 0::2], M[:, 1::2]       # interleaved halves (14 each)
    for c in (0, 1):
        for sel, est, tag in ((A, B, "A->B"), (B, A, "B->A")):
            lvl = chosen(sel.sum(1), c)
            act = M[:, :, :, 0].mean(1) > 0
            ins = take(sel.mean(1), lvl)[act].sum(); outs = take(est.mean(1), lvl)[act].sum()
            real = take(obs, lvl)[act].sum()
            print(f"{name:8s} c={c} {tag}: active {act.sum()} realised {real:.0f}  in-sample pred {ins:.1f}  held-out pred {outs:.1f}  ratio real/held-out {real/max(outs,1e-9):.2f}")
