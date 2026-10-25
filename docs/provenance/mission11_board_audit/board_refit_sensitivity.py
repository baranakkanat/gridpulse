"""Board check (zero solves): learned vs true PV-export sensitivity on rural3 (read-only)."""
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "analysis" / "export_envelope_shift"))  # edited: was an absolute local path
import numpy as np
import envelope_core as ec
import stage_a as sa
built = sa.build("rural3")
S_true = (built.path * built.rho) @ (built.path.T @ built.U)  # K x N true dv/de
for regime in ["P1", "P2", "P3", "L0"]:
    phys = np.load(sa.OUT / f"physics_rural3_{regime}.npz")
    steps = phys["steps"]; P = phys["P_bus"]; Q = phys["Q_bus"]; vm = phys["vm"].astype(float) if "vm" in phys else None
    keys = list(phys.keys())
    vm = phys[[k for k in keys if k.startswith("vm")][0]].astype(float)
    n_year = 365 * 96
    z = ec.rng_for("rural3", regime, "noise", 0).standard_normal((n_year, built.U.shape[0]))
    day = steps // 96
    tr = (day >= 152) & (day <= 155)
    V = vm + 0.002 * z[steps]
    X, Y = P[tr], V[tr]
    lam, _ = ec.cv_lambda(X, Y, day[tr])
    rf = ec.fit_ridge(X, Y, lam); of = ec.fit_ols(X, Y)
    for name, B in [("ridge", rf.slopes), ("ols", of.slopes)]:
        S_hat = B.T @ built.U
        # worst bus row (max true sensitivity) and aggregate along availability direction
        k = np.argmax(S_true.sum(axis=1))
        ratio_row = S_hat[k].sum() / S_true[k].sum()
        rel_err = np.linalg.norm(S_hat - S_true) / np.linalg.norm(S_true)
        neg = int((S_hat < 0).sum())
        print(f"{regime} {name:5s} lam {lam:7.1f}  remote-bus aggregate ratio {ratio_row:.3f}  rel Frobenius err {rel_err:.3f}  negative entries {neg}/{S_hat.size}")
