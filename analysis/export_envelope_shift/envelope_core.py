"""Mission 11 Stage A: the data-generation, estimation and statistics core.

EXPLORATORY and unregistered. The protocol is `stage_a_protocol.md` revision 2.2 plus the
dated amendments A1-A2: the file hashes to `PROTOCOL_SHA256` and its as-executed text (the
amendments replaced by "(none)", see `executed_text_sha`) still hashes to revision 2.2's
`PROTOCOL_SHA256_EXECUTED`. `check_protocol` verifies both, and every solve-running stage of
the later tasks is expected to call it before it starts.

This module runs **zero power flows**. It imports neither pandapower nor simbench, and it
knows nothing about any particular network: every network fact (incidences, path matrices,
ratings, profiles) arrives as an array argument. Task 1b adds the decision LPs, task 2 the
runner that holds the pandapower solves, and task 3 the analysis.

Conventions (protocol s. 4 to s. 9):

* time is in 15-minute steps, so 4 steps to the hour;
* arrays are `steps x units` (PV), `steps x loads` or `steps x buses`;
* power is in MW and Mvar and is **export-positive at a bus**; voltage is in pu;
* K customer buses, N PV units, L branches; the transformer is branch 0, lines are 1..L-1;
* `U` is the K x N incidence of PV unit to customer bus, `W` the K x n_loads incidence of
  load to customer bus, so P_bus = U.pv - W.l and Q_bus = -W.q (PV at unity power factor).

The estimators work in **centred slope space**: mu = mean(X), X_c = X - mu, and the
intercept is recovered as c_k = ybar_k - mu @ beta_k. The protocol writes the design as
X~ = [1, P] with an unpenalised intercept; the two are the same fit, and the ellipsoid
metric M = X_c'X_c + Lambda_s is then the slope-space block of X~'X~ + Lambda.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import ndimage, optimize, stats

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (REPO / "src", HERE):  # imported, never copied or edited
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from gridpulse.sensing import _stable_int  # noqa: E402

# --- A. constants and seeds ----------------------------------------------------------------

STATUS = ("EXPLORATORY Mission 11 Stage A: export-envelope safety under correlated PV; "
          "at most 8,000 new AC power flows; unregistered")  # fmt: skip

PROTOCOL = HERE / "stage_a_protocol.md"
#: the protocol file as the board has registered it: revision 2.2 plus the dated amendments.
PROTOCOL_SHA256 = "610d144dc3dbcb9835387f31ff5cdbd3a87d35d61db4dec832d10d8618b1f7fd"
#: the **as-executed** text: the amendments section's body replaced by "(none)". It is still
#: revision 2.2 byte for byte, which is what keeps the amendments from rewriting the protocol
#: the earlier stages were run under.
PROTOCOL_SHA256_EXECUTED = "1848a27963fc67e134eb6dbe97bd96f1bc29e0e7ce4a8d76a68dc8134aa122b4"
#: the heading whose body the as-executed text replaces (protocol, "Amendments").
AMENDMENTS_HEADING = "## Amendments (after the first scored solve)"

SEED_ROOT = 20261025

STEPS_PER_HOUR = 4
STEPS_PER_DAY = 96

#: regime -> (Delta in hours, sigma_c), protocol s. 4. P0 (native) is not a scored regime.
REGIMES: dict[str, tuple[float, float]] = {
    "P1": (0.0, 0.05),
    "P2": (0.5, 0.15),
    "P3": (1.0, 0.30),
}
PHI_CLOUD = 0.8  # AR(1) of the per-unit cloud factor, per 15 minutes
PHI_LOAD = 0.7  # AR(1) of the per-load multiplicative noise
SIGMA_L = 0.3  # log-scale sd of the load noise
SIGMA_S = 0.2  # log-scale sd of the per-load mean scale s_j
TAU_LOAD_MIN = 30.0  # load time shift, U(-30, +30) minutes

#: the load process is shared by every PV regime, so its seed uses this regime label.
LOAD_REGIME = "common"

#: protocol s. 13. Any other purpose is a bug, not a new stream.
PURPOSES = (
    "pv_orientation",
    "pv_cloud",
    "load",
    "noise",
    "bootstrap",
    "radius_refit",
    "ambiguity_refit",
    "rand_fallback",
    "shuffle",
    "interior_point",
)

EIG_TOL = 1e-10  # relative rank and eigenvalue tolerance, protocol s. 13


def rng_for(network: str, regime: str, purpose: str, replicate: int = 0) -> np.random.Generator:
    """The one seeding rule (protocol s. 13).

    `_stable_int` is `gridpulse.sensing`'s: a 64-bit integer from the sha256 of the text, so
    the stream does not depend on Python's salted `hash`.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown purpose {purpose!r}; allowed: {', '.join(PURPOSES)}")
    entropy = [
        SEED_ROOT,
        _stable_int(str(network)),
        _stable_int(str(regime)),
        _stable_int(str(purpose)),
        int(replicate),
    ]
    return np.random.default_rng(np.random.SeedSequence(entropy))


# --- B. regime generators (protocol s. 4) --------------------------------------------------


def ar1(rng: np.random.Generator, n_steps: int, n_series: int, phi: float) -> np.ndarray:
    """A stationary unit-variance AR(1): eta_0 ~ N(0, 1), then
    eta_t = phi.eta_{t-1} + sqrt(1-phi^2).eps_t.

    One standard normal is drawn per (step, series), the first row seeding eta_0, so the
    stream consumption is exactly `n_steps x n_series` normals in C order.
    """
    if not -1.0 < phi < 1.0:
        raise ValueError(f"phi must lie in (-1, 1), got {phi}")
    eps = rng.standard_normal((int(n_steps), int(n_series)))
    eta = np.empty_like(eps)
    eta[0] = eps[0]
    scale = math.sqrt(1.0 - phi**2)
    for t in range(1, eta.shape[0]):
        eta[t] = phi * eta[t - 1] + scale * eps[t]
    return eta


def smooth_residual(g: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Split a profile into a smooth component and a weather residual: s + w = g exactly.

    s is the centred 2-hour (8-step) rolling mean along time, edges held at the edge value.
    """
    g = np.asarray(g, dtype=float)
    s = ndimage.uniform_filter1d(g, size=8, axis=0, mode="nearest")
    return s, g - s


def shift_series(x: np.ndarray, shift_steps: np.ndarray | float) -> np.ndarray:
    """Per column, x evaluated at t + shift_steps by linear interpolation on the integer index.

    Fractional shifts are allowed; the ends are clamped to the edge values (`np.interp`'s
    default). A positive shift moves a feature at index t0 to the output index t0 - shift.
    """
    x = np.atleast_2d(np.asarray(x, dtype=float))
    n_steps, n_series = x.shape
    shift = np.broadcast_to(np.atleast_1d(np.asarray(shift_steps, dtype=float)), (n_series,))
    idx = np.arange(n_steps, dtype=float)
    out = np.empty_like(x)
    for j in range(n_series):
        out[:, j] = x[:, j] if shift[j] == 0.0 else np.interp(idx + shift[j], idx, x[:, j])
    return out


def pv_regime(
    g: np.ndarray,
    ratings: np.ndarray,
    delta_h: float,
    sigma_c: float,
    rng_orient: np.random.Generator,
    rng_cloud: np.random.Generator,
    train_steps: np.ndarray,
    native: np.ndarray,
) -> tuple[np.ndarray, dict]:
    """The PV availability of one regime (protocol s. 4).

    a_i(t) = r_i . min(1, max(0, s_i(t + delta_i) + w_i(t)) . c_i(t)), rescaled so that each
    unit's training-day mean equals its native (P0) mean, then re-clipped at the rating.

    Parameters
    ----------
    g : steps x N normalised native PV (the runner passes the absolute native series divided
        by the rating), so that `smooth_residual` splits the unit's own profile type.
    ratings : (N,) r_i in MW.
    delta_h, sigma_c : the regime's orientation spread in hours and cloud log-sd.
    rng_orient, rng_cloud : separate streams (`pv_orientation`, `pv_cloud`).
    train_steps : the step indices whose mean is matched to `native`.
    native : steps x N P0 availability r_i.min(1, g_i).

    Returns
    -------
    (a, info) with info holding `delta_h`, `delta_steps`, `k`, the share of (step, unit)
    entries at the inverter clip before and after the rescale, and the pre-re-clip training
    means used to check the rescale (`train_mean_scaled` against `train_mean_native`).
    """
    g = np.asarray(g, dtype=float)
    ratings = np.asarray(ratings, dtype=float)
    native = np.asarray(native, dtype=float)
    n_steps, n_units = g.shape
    train = np.asarray(train_steps, dtype=int)

    # 1. orientation (one vector, drawn once per unit), then the cloud factor.
    delta_h_i = rng_orient.uniform(-delta_h, delta_h, size=n_units)
    delta_steps = delta_h_i * STEPS_PER_HOUR
    s, w = smooth_residual(g)
    shaped = np.maximum(0.0, shift_series(s, delta_steps) + w)
    eta = ar1(rng_cloud, n_steps, n_units, PHI_CLOUD)
    cloud = np.exp(sigma_c * eta - 0.5 * sigma_c**2)
    unclipped = shaped * cloud
    clip_share = float(np.mean(unclipped > 1.0))
    a = ratings * np.minimum(1.0, unclipped)

    # 2. energy-preserving rescale on the training days.
    mean_native = native[train].mean(axis=0)
    mean_a = a[train].mean(axis=0)
    k = np.where(mean_a > 0.0, mean_native / np.where(mean_a > 0.0, mean_a, 1.0), 1.0)
    scaled = a * k

    # 3. re-clip at the rating (the floor is already 0 by construction).
    out = np.clip(scaled, 0.0, ratings)
    info = {
        "delta_h": delta_h_i,
        "delta_steps": delta_steps,
        "k": k,
        "clip_share": clip_share,
        "clip_share_after_rescale": float(np.mean(scaled > ratings + 0.0)),
        "train_mean_native": mean_native,
        "train_mean_scaled": scaled[train].mean(axis=0),
        "train_mean_final": out[train].mean(axis=0),
    }
    return out, info


def load_process(
    native_p: np.ndarray, native_q: np.ndarray, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Household heterogeneity on the native load profiles (protocol s. 4).

    l_j(t) = L_j(t + tau_j) . s_j . exp(sigma_L.zeta_j(t) - sigma_L^2/2), with Q scaled to
    keep each load's native power factor.

    Everything comes from the single `rng`, in this fixed order:

    1. tau_j ~ U(-30, +30) minutes (one vector);
    2. s_j = exp(N(0, 0.2^2)) (one vector), then renormalised so that
       sum_j s_j.mean(L_j) = sum_j mean(L_j) exactly;
    3. zeta = `ar1(rng, steps, loads, PHI_LOAD)`.

    Returns (l, q, info); info holds tau in minutes and steps, s before and after the
    renormalisation, the renormalisation factor and tan(phi_j).
    """
    native_p = np.asarray(native_p, dtype=float)
    native_q = np.asarray(native_q, dtype=float)
    n_steps, n_loads = native_p.shape

    tau_min = rng.uniform(-TAU_LOAD_MIN, TAU_LOAD_MIN, size=n_loads)
    tau_steps = tau_min / 15.0
    s_raw = np.exp(rng.normal(0.0, SIGMA_S, size=n_loads))
    mean_p = native_p.mean(axis=0)
    denom = float(np.sum(s_raw * mean_p))
    renorm = float(np.sum(mean_p) / denom) if denom != 0.0 else 1.0
    s = s_raw * renorm
    zeta = ar1(rng, n_steps, n_loads, PHI_LOAD)

    ell = shift_series(native_p, tau_steps) * s * np.exp(SIGMA_L * zeta - 0.5 * SIGMA_L**2)
    total_p = native_p.sum(axis=0)
    safe_p = np.where(total_p != 0.0, total_p, 1.0)
    tan_phi = np.where(total_p != 0.0, native_q.sum(axis=0) / safe_p, 0.0)
    q = ell * tan_phi
    info = {
        "tau_min": tau_min,
        "tau_steps": tau_steps,
        "s_raw": s_raw,
        "s": s,
        "renorm": renorm,
        "tan_phi": tan_phi,
    }
    return ell, q, info


# --- C. network linear structure (arrays only) ---------------------------------------------


def tree_matrices(
    parent_branch: np.ndarray, bus_of_branch_child: np.ndarray, n_branches: int
) -> tuple[np.ndarray, np.ndarray]:
    """The path and downstream matrices of a radial feeder, from a parent-pointer description.

    Parameters
    ----------
    parent_branch : (L,) int. `parent_branch[l]` is the branch immediately upstream of branch
        l, or -1 for the root branch (the transformer, branch 0).
    bus_of_branch_child : (L,) int. The customer-bus index 0..K-1 at branch l's downstream
        end, or -1 if that bus carries no load. Every customer bus must appear exactly once.
    n_branches : L, checked against the arrays.

    Returns
    -------
    (path, down) with `path` the K x L boolean "branch l is on bus k's path to the source"
    (branch 0 on every path) and `down = path.T`.
    """
    parent = np.asarray(parent_branch, dtype=int)
    child_bus = np.asarray(bus_of_branch_child, dtype=int)
    if parent.shape != (n_branches,) or child_bus.shape != (n_branches,):
        raise ValueError("parent_branch and bus_of_branch_child must both have length n_branches")
    if parent[0] != -1 or np.any(parent[1:] < 0):
        raise ValueError("branch 0 is the root (parent -1); every other branch needs a parent")
    customers = child_bus[child_bus >= 0]
    n_buses = customers.size
    if sorted(customers.tolist()) != list(range(n_buses)):
        raise ValueError("bus_of_branch_child must list each customer bus 0..K-1 exactly once")

    path = np.zeros((n_buses, n_branches), dtype=bool)
    for branch, bus in enumerate(child_bus):
        if bus < 0:
            continue
        walk, hops = branch, 0
        while walk >= 0:
            path[bus, walk] = True
            walk = parent[walk]
            hops += 1
            if hops > n_branches:
                raise ValueError("parent_branch is not a tree: the walk to the root cycles")
    return path, path.T


def lindistflow(
    path: np.ndarray, rho: np.ndarray, chi: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The K x K LinDistFlow sensitivity matrices S_P = path.diag(rho).path' and S_Q likewise.

    With (rho_l, chi_l) = (r_l, x_l)/V_nom^2, the voltage deviation of a bus-injection
    vector is dv = S_P.P_bus + S_Q.Q_bus (both export-positive, so dv rises with export).
    """
    path = np.asarray(path, dtype=float)
    rho = np.asarray(rho, dtype=float)
    chi = np.asarray(chi, dtype=float)
    return (path * rho) @ path.T, (path * chi) @ path.T


def structured_predict(
    c: np.ndarray | float,
    path: np.ndarray,
    rho: np.ndarray,
    chi: np.ndarray,
    P_bus: np.ndarray,
    Q_bus: np.ndarray,
) -> np.ndarray:
    """v = c + path.(rho o F + chi o G), with F = down.P_bus and G = down.Q_bus.

    `c` is a scalar or a per-bus (K,) vector. `P_bus`/`Q_bus` are `steps x K` or a single
    (K,) state, in which case a (K,) prediction is returned. This is the same model as
    `lindistflow` but in O(K.L) per step instead of O(K^2).
    """
    path_f = np.asarray(path, dtype=float)
    p_arr = np.asarray(P_bus, dtype=float)
    q_arr = np.asarray(Q_bus, dtype=float)
    flat = p_arr.ndim == 1
    p_mat = np.atleast_2d(p_arr)
    q_mat = np.atleast_2d(q_arr)
    flow_p = p_mat @ path_f  # steps x L, the downstream net P of every branch
    flow_q = q_mat @ path_f
    v = (flow_p * np.asarray(rho, float) + flow_q * np.asarray(chi, float)) @ path_f.T
    v = v + np.asarray(c, dtype=float)
    return v[0] if flat else v


# --- D. estimators (protocol s. 7, "common regression set-up") -----------------------------


@dataclass(frozen=True)
class OLSFit:
    """A minimum-norm least-squares fit in centred slope space."""

    slopes: np.ndarray  # p x K_buses
    intercepts: np.ndarray  # (K_buses,)
    rank: int
    sigma2: np.ndarray  # (K_buses,), RSS/(T - 1 - rank)
    mu: np.ndarray
    ybar: np.ndarray


@dataclass(frozen=True)
class RidgeFit:
    """A ridge fit on standardised regressors with an unpenalised intercept."""

    slopes: np.ndarray  # p x K_buses
    intercepts: np.ndarray  # (K_buses,)
    M: np.ndarray  # p x p, X_c'X_c + Lambda_s
    df: float
    sigma2: np.ndarray  # (K_buses,), RSS/(T - 1 - df)
    Lambda_s: np.ndarray
    zero_var: np.ndarray  # bool (p,), columns held at slope 0
    lam: float | None
    mu: np.ndarray
    ybar: np.ndarray


@dataclass(frozen=True)
class NNRidgeFit:
    """A ridge fit with every slope constrained to be non-negative (protocol s. 8)."""

    slopes: np.ndarray  # p x K_buses
    intercepts: np.ndarray  # (K_buses,)
    mu: np.ndarray
    ybar: np.ndarray


def _as_targets(n_steps: int, Y: np.ndarray) -> np.ndarray:
    """Y as a `steps x buses` float array. A 1-D Y is one bus; a wrong row count raises
    rather than being silently transposed, which a square T = K case would get wrong."""
    arr = np.asarray(Y, dtype=float)
    if arr.ndim == 1:
        arr = arr[:, None]
    if arr.ndim != 2 or arr.shape[0] != n_steps:
        raise ValueError(f"Y must be {n_steps} x n_buses, got {arr.shape}")
    return arr


def _centre(X: np.ndarray, Y: np.ndarray):
    X = np.asarray(X, dtype=float)
    Y = _as_targets(X.shape[0], Y)
    mu = X.mean(axis=0)
    ybar = Y.mean(axis=0)
    return X - mu, Y - ybar, mu, ybar, X, Y


def fit_ols(X: np.ndarray, Y: np.ndarray) -> OLSFit:
    """Least squares of the noisy voltages on the bus injections, minimum-norm if rank-deficient."""
    Xc, Yc, mu, ybar, _, Y = _centre(X, Y)
    slopes, _, rank, _ = np.linalg.lstsq(Xc, Yc, rcond=None)
    resid = Yc - Xc @ slopes
    rss = np.sum(resid**2, axis=0)
    dof = Xc.shape[0] - 1 - int(rank)
    sigma2 = rss / dof if dof > 0 else np.full(rss.shape, np.nan)
    return OLSFit(slopes, ybar - mu @ slopes, int(rank), sigma2, mu, ybar)


def ridge_penalty(X: np.ndarray, lam: float) -> tuple[np.ndarray, np.ndarray]:
    """Lambda_s = lam.diag(sd_b^2): ridge on standardised regressors, in the slopes' own units.

    sd_b is the training standard deviation of column b (ddof 0). A column with sd = 0
    carries no information, and its penalty would be 0, leaving M singular. Such a column is
    instead given the diagonal entry 1: because its centred column is exactly zero, the
    normal equations then return a slope of exactly 0 for it and leave every other slope
    unchanged. The mask of those columns is returned alongside.
    """
    X = np.asarray(X, dtype=float)
    sd = X.std(axis=0, ddof=0)
    zero_var = sd == 0.0
    diag = float(lam) * sd**2
    diag[zero_var] = 1.0
    return np.diag(diag), zero_var


def _ridge_from_penalty(
    X: np.ndarray,
    Y: np.ndarray,
    Lambda_s: np.ndarray,
    zero_var: np.ndarray | None = None,
    lam: float | None = None,
) -> RidgeFit:
    Xc, Yc, mu, ybar, _, _ = _centre(X, Y)
    xtx = Xc.T @ Xc
    M = xtx + np.asarray(Lambda_s, dtype=float)
    slopes = np.linalg.solve(M, Xc.T @ Yc)
    if zero_var is None:
        zero_var = X.std(axis=0, ddof=0) == 0.0
    slopes[zero_var, :] = 0.0
    df = float(np.trace(np.linalg.solve(M, xtx)))
    resid = Yc - Xc @ slopes
    rss = np.sum(resid**2, axis=0)
    dof = Xc.shape[0] - 1 - df
    sigma2 = rss / dof if dof > 0 else np.full(rss.shape, np.nan)
    return RidgeFit(
        slopes, ybar - mu @ slopes, M, df, sigma2, np.asarray(Lambda_s, float), zero_var, lam,
        mu, ybar,
    )  # fmt: skip


def fit_ridge(X: np.ndarray, Y: np.ndarray, lam: float) -> RidgeFit:
    """Ridge with penalty `ridge_penalty(X, lam)`; `df` is tr(X_c M^-1 X_c') and sigma2 uses it."""
    Lambda_s, zero_var = ridge_penalty(X, lam)
    return _ridge_from_penalty(X, Y, Lambda_s, zero_var, float(lam))


def cv_lambda(
    X: np.ndarray, Y: np.ndarray, block_id: np.ndarray, grid: np.ndarray | None = None
) -> tuple[float, np.ndarray]:
    """Time-blocked cross-validation for lambda, one fold per distinct `block_id` (training day).

    The default grid is T x `np.logspace(-6, 2, 33)`, so lambda scales with the sample size;
    the value is then held fixed across folds (each fold's own standard deviations enter
    through `ridge_penalty`). The score is the mean squared prediction error over every bus
    and held-out step. Ties go to the larger lambda.

    Returns (lambda, table) with `table` the (n_grid, 2) array of (lambda, score).
    """
    Xa = np.asarray(X, dtype=float)
    Ya = _as_targets(Xa.shape[0], Y)
    n_steps = Xa.shape[0]
    blocks = np.asarray(block_id)
    if blocks.shape[0] != n_steps:
        raise ValueError("block_id must have one entry per training step")
    if grid is None:
        lam_grid = n_steps * np.logspace(-6, 2, 33)
    else:
        lam_grid = np.asarray(grid, dtype=float)
    folds = [blocks == b for b in np.unique(blocks)]

    scores = np.empty(lam_grid.size)
    for i, lam in enumerate(lam_grid):
        sq, count = 0.0, 0
        for held in folds:
            keep = ~held
            fit = fit_ridge(Xa[keep], Ya[keep], lam)
            pred = fit.intercepts + Xa[held] @ fit.slopes
            sq += float(np.sum((Ya[held] - pred) ** 2))
            count += int(held.sum()) * Ya.shape[1]
        scores[i] = sq / count
    best = int(np.flatnonzero(scores == scores.min())[-1])  # ties -> the larger lambda
    return float(lam_grid[best]), np.column_stack([lam_grid, scores])


def conformal_margin(residuals: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    """Per bus, the ceil((n+1)(1-alpha))-th smallest |residual| of the held-out day.

    With n = 96 held-out steps and alpha = 0.05 that is the 93rd. The index is raised on,
    not clipped, when it exceeds n: too few held-out steps for the requested level.
    """
    r = np.atleast_2d(np.asarray(residuals, dtype=float))
    n = r.shape[0]
    index = math.ceil((n + 1) * (1.0 - alpha))
    if index > n:
        raise ValueError(f"conformal index {index} exceeds n = {n} held-out steps")
    return np.sort(np.abs(r), axis=0)[index - 1]


def ridge_box_sd(X: np.ndarray, M: np.ndarray, sigma2: np.ndarray) -> np.ndarray:
    """The Gupta-style per-coefficient sd: sqrt(sigma2_k . diag(M^-1 X_c'X_c M^-1)_j).

    Returns a (K_buses, p) array; the off-diagonal covariance is dropped, as in the
    precedent (protocol s. 7, B4box).
    """
    Xc = np.asarray(X, dtype=float) - np.asarray(X, dtype=float).mean(axis=0)
    xtx = Xc.T @ Xc
    m_inv = np.linalg.inv(np.asarray(M, dtype=float))
    var = np.diag(m_inv @ xtx @ m_inv)
    return np.sqrt(np.outer(np.asarray(sigma2, dtype=float), var))


def ols_box_sd(X: np.ndarray, sigma2: np.ndarray) -> tuple[np.ndarray, float]:
    """The same box on the OLS fit, with the pseudo-inverse of X_c'X_c (protocol s. 7, B4box-OLS).

    Also returns the relative condition number lambda_max/lambda_min of X_c'X_c; a
    non-positive smallest eigenvalue gives inf, which the runner records as
    `robust-degenerate`.
    """
    Xc = np.asarray(X, dtype=float) - np.asarray(X, dtype=float).mean(axis=0)
    xtx = Xc.T @ Xc
    var = np.diag(np.linalg.pinv(xtx))
    eig = np.linalg.eigvalsh(xtx)
    cond = float(eig.max() / eig.min()) if eig.min() > 0.0 else math.inf
    return np.sqrt(np.outer(np.asarray(sigma2, dtype=float), np.maximum(var, 0.0))), cond


def fit_structured_nnls(
    path: np.ndarray, P_bus: np.ndarray, Q_bus: np.ndarray, V: np.ndarray
) -> tuple[float, np.ndarray, np.ndarray, float]:
    """B3: the topology-structured LinDistFlow fit by one joint non-negative least squares.

    The unknowns are [c, rho_0..rho_{L-1}, chi_0..chi_{L-1}], all >= 0, and row (k, t) is
    c + sum_{l in path(k)} (rho_l.F_l(t) + chi_l.G_l(t)) = V[t, k]. Rows are stacked bus-major
    (k outer, t inner). The design is built blockwise in float64: rural3 is about
    45,000 x 257, which is a 93 MB dense matrix.

    Returns (c, rho, chi, residual_norm).
    """
    path_f = np.asarray(path, dtype=float)
    n_buses, n_branches = path_f.shape
    p_mat = np.atleast_2d(np.asarray(P_bus, dtype=float))
    q_mat = np.atleast_2d(np.asarray(Q_bus, dtype=float))
    v_mat = np.atleast_2d(np.asarray(V, dtype=float))
    n_steps = p_mat.shape[0]
    flow_p = p_mat @ path_f  # steps x L
    flow_q = q_mat @ path_f

    design = np.empty((n_buses * n_steps, 1 + 2 * n_branches), dtype=float)
    design[:, 0] = 1.0
    for k in range(n_buses):
        rows = slice(k * n_steps, (k + 1) * n_steps)
        on_path = path_f[k]
        design[rows, 1 : 1 + n_branches] = flow_p * on_path
        design[rows, 1 + n_branches :] = flow_q * on_path
    target = np.ascontiguousarray(v_mat.T).ravel()  # bus-major, matching the row order

    solution, residual = optimize.nnls(design, target)
    return (
        float(solution[0]),
        solution[1 : 1 + n_branches],
        solution[1 + n_branches :],
        float(residual),
    )


def offset_from_state(
    v_state: np.ndarray,
    c: np.ndarray | float,
    path: np.ndarray,
    rho: np.ndarray,
    chi: np.ndarray,
    P_state: np.ndarray,
    Q_state: np.ndarray,
) -> np.ndarray:
    """Method A's per-bus offset: o_k = v_state,k - structured_predict(c = 0, ...)_k.

    The offset is taken at the condition's no-action AC state, so it is the **complete**
    per-bus intercept of Method A: the caller predicts with `structured_predict(o, ...)`,
    not with c + o. `c` is accepted for signature symmetry with `structured_predict` and is
    deliberately not used, as the brief fixes the offset at c = 0.
    """
    del c  # by construction; see the docstring
    return np.asarray(v_state, dtype=float) - structured_predict(
        0.0, path, rho, chi, P_state, Q_state
    )


def training_intercept(
    V: np.ndarray,
    path: np.ndarray,
    rho: np.ndarray,
    chi: np.ndarray,
    P_bus: np.ndarray,
    Q_bus: np.ndarray,
) -> np.ndarray:
    """Method A-prime's per-bus intercept: the training-step mean of
    V - structured_predict(c = 0, ...)."""
    resid = np.atleast_2d(np.asarray(V, dtype=float)) - structured_predict(
        0.0, path, rho, chi, P_bus, Q_bus
    )
    return resid.mean(axis=0)


# --- E. bootstrap, radius and data-consistent alternatives (s. 7 B4, s. 8) -----------------


@dataclass(frozen=True)
class RadiusResult:
    """B4's data-consistent ellipsoid radius from a moving-block bootstrap."""

    d: np.ndarray  # K_buses x n_boot, (beta* - beta)' M (beta* - beta)
    c: float  # the simultaneous-over-buses scale factor
    r2: np.ndarray  # (K_buses,), c . median_b d_kb
    f_radius: np.ndarray  # (K_buses,), the F-quantile diagnostic (NaN if T-1-p <= 0)
    fit: RidgeFit = field(repr=False, default=None)


def moving_block_indices(rng: np.random.Generator, T: int, block: int = 16) -> np.ndarray:
    """ceil(T/block) circular blocks of `block` steps, starts uniform in [0, T), truncated to T."""
    T = int(T)
    block = int(block)
    n_blocks = math.ceil(T / block)
    starts = rng.integers(0, T, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]) % T
    return idx.ravel()[:T]


def bootstrap_radius(
    X: np.ndarray,
    Y: np.ndarray,
    lam: float,
    rng: np.random.Generator,
    n_boot: int = 400,
    block: int = 16,
    q: float = 0.95,
) -> RadiusResult:
    """B4's radius rule (protocol s. 7).

    The ridge is refitted on `n_boot` moving-block resamples with lambda and Lambda_s held at
    the full sample's, each resample centred on its own means. d_kb is the Mahalanobis
    distance of the refit from the full-sample estimate in the metric M = X_c'X_c + Lambda_s,
    c is the q-quantile over b of max_k (d_kb / median_b d_kb) and r_k^2 = c . median_b d_kb.

    The F-quantile radius p.sigma2_k.F_{p, T-1-p}(0.95) is a diagnostic only, with p the
    number of slopes. (The protocol writes F_{p, T-p} with p = N_b + 1 parameters including
    the intercept; in centred slope space that is the same denominator.)
    """
    Xa = np.asarray(X, dtype=float)
    Ya = _as_targets(Xa.shape[0], Y)
    n_steps, n_slopes = Xa.shape
    full = fit_ridge(Xa, Ya, lam)
    beta = full.slopes
    M = full.M

    d = np.empty((Ya.shape[1], int(n_boot)))
    for b in range(int(n_boot)):
        idx = moving_block_indices(rng, n_steps, block)
        refit = _ridge_from_penalty(Xa[idx], Ya[idx], full.Lambda_s, full.zero_var, full.lam)
        diff = refit.slopes - beta
        d[:, b] = np.sum(diff * (M @ diff), axis=0)

    median = np.median(d, axis=1)
    safe = np.where(median > 0.0, median, 1.0)
    c = float(np.quantile(np.max(d / safe[:, None], axis=0), q))
    r2 = c * median

    dfd = n_steps - 1 - n_slopes
    if dfd > 0:
        f_radius = n_slopes * full.sigma2 * stats.f.ppf(0.95, n_slopes, dfd)
    else:
        f_radius = np.full(Ya.shape[1], np.nan)
    return RadiusResult(d, c, r2, np.asarray(f_radius, dtype=float), full)


def _penalty_matrix(X: np.ndarray, lam_penalty) -> tuple[np.ndarray, np.ndarray]:
    """Accept either a scalar lambda or a ready p x p Lambda_s (which must be diagonal)."""
    arr = np.asarray(lam_penalty, dtype=float)
    if arr.ndim == 0:
        return ridge_penalty(X, float(arr))
    if arr.ndim != 2 or not np.allclose(arr, np.diag(np.diag(arr))):
        raise ValueError("Lambda_s must be a diagonal matrix")
    sd = np.asarray(X, dtype=float).std(axis=0, ddof=0)
    return arr, sd == 0.0


def fit_nn_ridge(X: np.ndarray, Y: np.ndarray, lam_penalty) -> NNRidgeFit:
    """The non-negative ridge of protocol s. 8: per bus, `nnls` on [X_c; sqrt(Lambda_s)].

    `lam_penalty` is a scalar lambda or a diagonal Lambda_s. Every slope is >= 0 (admissible
    on a radial feeder) and the intercept is ybar_k - mu' beta_k.
    """
    Xa = np.asarray(X, dtype=float)
    Lambda_s, _ = _penalty_matrix(Xa, lam_penalty)
    Xc, Yc, mu, ybar, _, _ = _centre(Xa, Y)
    augmented = np.vstack([Xc, np.diag(np.sqrt(np.diag(Lambda_s)))])
    pad = np.zeros(Lambda_s.shape[0])
    slopes = np.empty((Xa.shape[1], Yc.shape[1]))
    for k in range(Yc.shape[1]):
        slopes[:, k], _ = optimize.nnls(augmented, np.concatenate([Yc[:, k], pad]))
    return NNRidgeFit(slopes, ybar - mu @ slopes, mu, ybar)


def _full_training_rmse(X: np.ndarray, Y: np.ndarray, slopes, intercepts) -> float:
    pred = intercepts + np.asarray(X, dtype=float) @ slopes
    return float(np.sqrt(np.mean((np.asarray(Y, dtype=float) - pred) ** 2)))


def random_alternatives(
    X: np.ndarray,
    Y: np.ndarray,
    Lambda_s: np.ndarray,
    rng: np.random.Generator,
    n: int = 4,
    block: int = 16,
) -> tuple[list[NNRidgeFit], np.ndarray]:
    """The 4 random data-consistent alternatives: moving-block refits of the non-negative ridge.

    Returns (alternatives, rmse_ratio), the ratio being each alternative's full-training RMSE
    divided by that of the B2 ridge implied by the same `Lambda_s` (the unconstrained fit on
    the full sample, which is B2 exactly).
    """
    Xa = np.asarray(X, dtype=float)
    Ya = _as_targets(Xa.shape[0], Y)
    reference = _ridge_from_penalty(Xa, Ya, Lambda_s)
    ref_rmse = _full_training_rmse(Xa, Ya, reference.slopes, reference.intercepts)

    alternatives, ratios = [], np.empty(int(n))
    for i in range(int(n)):
        idx = moving_block_indices(rng, Xa.shape[0], block)
        alt = fit_nn_ridge(Xa[idx], Ya[idx], Lambda_s)
        alternatives.append(alt)
        rmse = _full_training_rmse(Xa, Ya, alt.slopes, alt.intercepts)
        ratios[i] = rmse / ref_rmse if ref_rmse > 0.0 else np.inf
    return alternatives, ratios


def extreme_alternatives(
    X: np.ndarray, Y: np.ndarray, Lambda_s: np.ndarray, r2: np.ndarray, M: np.ndarray
) -> tuple[list[NNRidgeFit], np.ndarray]:
    """The 4 extreme alternatives: +/- along M's two weakest eigen-directions to E_k's boundary.

    The centre is the full-sample non-negative ridge. For each direction v with eigenvalue
    lambda_v and each bus k, t_k = sqrt(r2_k / lambda_v) puts beta = centre_k + sign.t_k.v
    exactly on the boundary of E_k. A point with a negative slope is shrunk to the largest
    t' <= t_k that keeps every slope >= 0, and the intercept is recomputed as
    ybar_k - mu' beta_k.

    Returns (alternatives, shrink) with `shrink` the (4, K_buses) array of t'/t_k. By
    construction these maximise disagreement inside the set: they are an upper bound and
    carry no verdict (protocol s. 8).
    """
    Xa = np.asarray(X, dtype=float)
    Ya = _as_targets(Xa.shape[0], Y)
    centre = fit_nn_ridge(Xa, Ya, Lambda_s)
    mu, ybar = centre.mu, centre.ybar
    eigvals, eigvecs = np.linalg.eigh(np.asarray(M, dtype=float))
    directions = [
        (eigvecs[:, 0], eigvals[0], 1.0),
        (eigvecs[:, 0], eigvals[0], -1.0),
        (eigvecs[:, 1], eigvals[1], 1.0),
        (eigvecs[:, 1], eigvals[1], -1.0),
    ]
    r2_arr = np.asarray(r2, dtype=float)
    n_buses = Ya.shape[1]
    shrink = np.ones((4, n_buses))
    alternatives = []
    for i, (v, lam_v, sign) in enumerate(directions):
        step = sign * v
        slopes = np.empty_like(centre.slopes)
        for k in range(n_buses):
            t_full = math.sqrt(max(r2_arr[k], 0.0) / lam_v) if lam_v > 0.0 else 0.0
            beta = centre.slopes[:, k] + t_full * step
            if np.any(beta < 0.0) and t_full > 0.0:
                binding = step < 0.0
                t_cap = np.min(centre.slopes[binding, k] / -step[binding])
                t_used = float(np.clip(t_cap, 0.0, t_full))
                beta = centre.slopes[:, k] + t_used * step
                shrink[i, k] = t_used / t_full
            slopes[:, k] = np.maximum(beta, 0.0)
        alternatives.append(NNRidgeFit(slopes, ybar - mu @ slopes, mu, ybar))
    return alternatives, shrink


# --- F. diagnostics (protocol s. 4, controls C and K) --------------------------------------


def _standardise(X: np.ndarray) -> np.ndarray:
    X = np.asarray(X, dtype=float)
    sd = X.std(axis=0, ddof=0)
    out = X - X.mean(axis=0)
    good = sd > 0.0
    out[:, good] /= sd[good]
    return out


def excitation_diagnostics(pv: np.ndarray, Xbus: np.ndarray, daylight: np.ndarray) -> dict:
    """The excitation read-out of protocol s. 4 (control B's measurement, zero solves).

    `pv` is steps x N, `Xbus` the steps x K net-injection design matrix (the training steps),
    and `daylight` a boolean mask or index array over `pv`'s steps used for the correlations.
    """
    pv_day = np.asarray(pv, dtype=float)[daylight]
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(pv_day, rowvar=False)
    corr = np.atleast_2d(corr)
    off = ~np.eye(corr.shape[0], dtype=bool)
    pair = corr[off]
    svals = np.linalg.svd(_standardise(Xbus), compute_uv=False)
    total = svals.sum()
    share = svals[svals > 0.0] / total if total > 0.0 else np.array([1.0])
    eff_rank = float(np.exp(-np.sum(share * np.log(share))))
    tol = EIG_TOL * (svals.max() if svals.size else 0.0)
    kept = svals.copy()
    kept[kept < tol] = 0.0
    cond = math.inf if np.any(kept == 0.0) else float(kept.max() / kept.min())

    Xa = np.asarray(Xbus, dtype=float)
    centred = Xa - Xa.mean(axis=0)
    independent = np.empty(Xa.shape[1])
    for b in range(Xa.shape[1]):
        others = np.delete(centred, b, axis=1)
        if others.shape[1] == 0:
            independent[b] = float(np.mean(centred[:, b] ** 2))
            continue
        coef, *_ = np.linalg.lstsq(others, centred[:, b], rcond=None)
        independent[b] = float(np.mean((centred[:, b] - others @ coef) ** 2))
    return {
        "pv_corr_mean": float(np.nanmean(pair)) if pair.size else float("nan"),
        "pv_corr_min": float(np.nanmin(pair)) if pair.size else float("nan"),
        "singular_values": svals,
        "effective_rank": eff_rank,
        "condition_number": cond,
        "independent_variance": independent,
    }


def corner_distance(X_train: np.ndarray, x_corner: np.ndarray) -> dict:
    """How far the deployment corner lies outside the training support (protocol s. 4).

    The residual norm is what is left of x - mean after projecting onto the leading training
    principal components that explain 99 % of the variance; the Mahalanobis distance uses the
    training covariance with eigenvalues floored at 1e-10 x the largest.
    """
    Xa = np.asarray(X_train, dtype=float)
    mu = Xa.mean(axis=0)
    centred = Xa - mu
    d = np.asarray(x_corner, dtype=float) - mu
    _, svals, vt = np.linalg.svd(centred, full_matrices=False)
    var = svals**2
    if var.sum() > 0.0:
        cumulative = np.cumsum(var) / var.sum()
        n_comp = int(np.searchsorted(cumulative, 0.99) + 1)
    else:
        n_comp = 0
    basis = vt[:n_comp]
    residual = d - basis.T @ (basis @ d) if n_comp else d
    cov = np.cov(Xa, rowvar=False)
    cov = np.atleast_2d(cov)
    eigvals, eigvecs = np.linalg.eigh(cov)
    floor = EIG_TOL * max(eigvals.max(), 0.0)
    eigvals = np.maximum(eigvals, floor)
    proj = eigvecs.T @ d
    mahalanobis = float(np.sqrt(np.sum(proj**2 / eigvals))) if np.all(eigvals > 0.0) else math.inf
    return {
        "residual_norm": float(np.linalg.norm(residual)),
        "mahalanobis": mahalanobis,
        "n_components": n_comp,
    }


def marginal_check(
    a_by_regime: dict[str, np.ndarray], train_steps: np.ndarray, daylight: np.ndarray
) -> dict:
    """Control C, matched marginals (protocol s. 10).

    Per unit and regime: the training-day mean, the training-day daylight 95th percentile and
    maximum, and the KS statistic against P1 over the training-day daylight steps.

    **Pass** = for each of P2 and P3 against P1, every unit's training mean is within 1 % and
    the median over units of |P95 ratio - 1| is at most 0.10. KS, maxima and the corner
    distance are reported only (finding M11 of the drafting record).
    """
    train = np.asarray(train_steps, dtype=int)
    day_mask = np.zeros(next(iter(a_by_regime.values())).shape[0], dtype=bool)
    day_mask[np.asarray(daylight)] = True
    train_day = train[day_mask[train]]

    stats_by_regime = {}
    for regime, a in a_by_regime.items():
        arr = np.asarray(a, dtype=float)
        stats_by_regime[regime] = {
            "train_mean": arr[train].mean(axis=0),
            "daylight_p95": np.percentile(arr[train_day], 95, axis=0),
            "train_max": arr[train].max(axis=0),
        }
    ref = np.asarray(a_by_regime["P1"], dtype=float)
    ref_stats = stats_by_regime["P1"]

    comparisons, passed = {}, True
    for regime in a_by_regime:
        if regime == "P1":
            continue
        arr = np.asarray(a_by_regime[regime], dtype=float)
        mean_ratio = _ratio(stats_by_regime[regime]["train_mean"], ref_stats["train_mean"])
        p95_ratio = _ratio(stats_by_regime[regime]["daylight_p95"], ref_stats["daylight_p95"])
        ks = np.array(
            [
                float(stats.ks_2samp(arr[train_day, i], ref[train_day, i]).statistic)
                for i in range(arr.shape[1])
            ]
        )
        mean_ok = bool(np.all(np.abs(mean_ratio - 1.0) <= 0.01))
        p95_ok = bool(np.median(np.abs(p95_ratio - 1.0)) <= 0.10)
        comparisons[regime] = {
            "mean_ratio": mean_ratio,
            "p95_ratio": p95_ratio,
            "ks": ks,
            "mean_within_1pct": mean_ok,
            "median_p95_within_10pct": p95_ok,
            "passed": mean_ok and p95_ok,
        }
        if regime in ("P2", "P3"):
            passed = passed and mean_ok and p95_ok
    return {"per_regime": stats_by_regime, "against_P1": comparisons, "passed": passed}


def _ratio(value: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """value/reference, with 0/0 read as 1 (both regimes are dark) and x/0 as inf."""
    value = np.asarray(value, dtype=float)
    reference = np.asarray(reference, dtype=float)
    out = np.where(reference != 0.0, value / np.where(reference != 0.0, reference, 1.0), np.inf)
    return np.where((reference == 0.0) & (value == 0.0), 1.0, out)


def shuffled_fit(X: np.ndarray, Y: np.ndarray, lam: float, rng: np.random.Generator) -> RidgeFit:
    """Control K (NC4): the ridge refitted with V permuted across training time against P."""
    Xa = np.asarray(X, dtype=float)
    Ya = _as_targets(Xa.shape[0], Y)
    return fit_ridge(Xa, Ya[rng.permutation(Xa.shape[0])], lam)


# --- G. statistics (protocol s. 9) ---------------------------------------------------------


@dataclass(frozen=True)
class PairedBootstrap:
    """A percentile bootstrap over conditions, paired by construction."""

    mean: float
    lo: float
    hi: float
    p: float
    n: int


def paired_bootstrap(
    d: np.ndarray, rng: np.random.Generator, n_boot: int = 2000, level: float = 0.95
) -> PairedBootstrap:
    """Resample conditions with replacement; the bootstrap p is
    2.min(frac(mean* <= 0), frac(mean* >= 0)), capped at 1."""
    d = np.asarray(d, dtype=float).ravel()
    n = d.size
    if n == 0:
        raise ValueError("paired_bootstrap needs at least one condition")
    draws = d[rng.integers(0, n, size=(int(n_boot), n))].mean(axis=1)
    tail = (1.0 - level) / 2.0
    lo, hi = np.quantile(draws, [tail, 1.0 - tail])
    p = 2.0 * min(float(np.mean(draws <= 0.0)), float(np.mean(draws >= 0.0)))
    return PairedBootstrap(float(d.mean()), float(lo), float(hi), min(p, 1.0), n)


def clopper_pearson(k: int, n: int, alpha: float = 0.05) -> tuple[float, float]:
    """The two-sided exact binomial interval. 0 of 10 gives an upper bound of 0.3085."""
    k, n = int(k), int(n)
    if not 0 <= k <= n or n <= 0:
        raise ValueError(f"need 0 <= k <= n with n > 0, got k = {k}, n = {n}")
    lo = 0.0 if k == 0 else float(stats.beta.ppf(alpha / 2.0, k, n - k + 1))
    hi = 1.0 if k == n else float(stats.beta.ppf(1.0 - alpha / 2.0, k + 1, n - k))
    return lo, hi


def holm(pvalues: np.ndarray, alpha: float = 0.05) -> tuple[np.ndarray, np.ndarray]:
    """Holm's step-down correction: (rejected, adjusted p), both in the input's order."""
    p = np.asarray(pvalues, dtype=float).ravel()
    m = p.size
    order = np.argsort(p, kind="stable")
    ladder = np.minimum(1.0, (m - np.arange(m)) * p[order])
    adjusted_sorted = np.maximum.accumulate(ladder)
    adjusted = np.empty(m)
    adjusted[order] = adjusted_sorted
    return adjusted <= alpha, adjusted


def spearman(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """Spearman's rank correlation and its p-value (H2's 9 model x regime cells)."""
    result = stats.spearmanr(np.asarray(x, dtype=float), np.asarray(y, dtype=float))
    return float(result.statistic), float(result.pvalue)


# --- H. the ledger and write discipline (protocol s. 12) -----------------------------------


class SolveLedger:
    """Every AC solve this study runs, counted against the owner's ceiling of 8,000.

    The count starts at the 106 solves of the board design audits. `charge` raises *before*
    charging, so a stage that would exceed the ceiling runs no solve at all.
    """

    def __init__(self, start: int = 106, ceiling: int = 8000) -> None:
        self.start = int(start)
        self.ceiling = int(ceiling)
        self.items: dict[str, int] = {}

    @property
    def total(self) -> int:
        return self.start + sum(self.items.values())

    def charge(self, item: str, n: int) -> int:
        n = int(n)
        if n < 0:
            raise ValueError(f"cannot charge a negative count ({n}) to {item!r}")
        if self.total + n > self.ceiling:
            raise RuntimeError(
                f"solve ceiling {self.ceiling} would be exceeded: {self.total} charged, "
                f"{item!r} asks for {n}"
            )
        self.items[item] = self.items.get(item, 0) + n
        return self.total

    def remaining(self) -> int:
        return self.ceiling - self.total

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "ceiling": self.ceiling,
            "items": dict(self.items),
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> SolveLedger:
        ledger = cls(start=int(payload["start"]), ceiling=int(payload["ceiling"]))
        ledger.items = {str(key): int(value) for key, value in payload.get("items", {}).items()}
        return ledger


def _json_default(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.generic):
        return obj.item()
    raise TypeError(f"{type(obj).__name__} is not JSON-serialisable")


def write_json_once(path: str | Path, obj) -> Path:
    """Write JSON, refusing to overwrite: every artefact of this study is written once."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} exists; artefacts are written once and never rewritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, indent=2, sort_keys=True, default=_json_default) + "\n")
    return target


def write_npz_once(path: str | Path, **arrays: np.ndarray) -> Path:
    """Write a compressed npz, refusing to overwrite."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} exists; artefacts are written once and never rewritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target, **arrays)
    return target


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def executed_text_sha(path: str | Path = PROTOCOL) -> str:
    """The sha256 of the protocol's **as-executed** text: amendments replaced by "(none)".

    Everything after the line `AMENDMENTS_HEADING` is replaced by `"(none)\\n"`, exactly as
    the amendments section itself states. The amendments may therefore record dated board
    decisions without changing the text the already-counted solves were run under: that text
    must still hash to `PROTOCOL_SHA256_EXECUTED`.

    The heading must appear exactly once, at the start of a line; anything else means the
    file is not the registered protocol and no as-executed text can be recovered from it.
    """
    text = Path(path).read_text()
    marker = "\n" + AMENDMENTS_HEADING
    found = text.count(marker)
    if found != 1:
        raise ValueError(
            f"{path}: {AMENDMENTS_HEADING!r} starts {found} lines, expected exactly 1; "
            "the as-executed text cannot be recovered"
        )
    head = text[: text.index(marker) + len(marker)]
    return hashlib.sha256((head + "\n(none)\n").encode("utf-8")).hexdigest()


def check_protocol(
    path: str | Path = PROTOCOL,
    expected: str = PROTOCOL_SHA256,
    expected_executed: str | None = None,
) -> str:
    """Raise unless the protocol file hashes to `expected` **and** its as-executed text to
    `expected_executed`. With no arguments both are required, which is how the runner calls it.

    `expected` defaults to the registered file: revision 2.2 plus the dated amendments A1-A2.
    `expected_executed` defaults to `PROTOCOL_SHA256_EXECUTED` whenever `expected` is this
    module's registered hash, and to "no second check" otherwise, because the as-executed
    hash of some *other* revision is not this module's to know: a caller verifying one states
    it, and a caller verifying a stand-in file with no amendments section asks for neither.
    """
    digest = sha256_of(path)
    if digest != expected:
        raise ValueError(f"protocol sha256 {digest} != expected {expected} ({path})")
    if expected_executed is None and expected == PROTOCOL_SHA256:
        expected_executed = PROTOCOL_SHA256_EXECUTED
    if expected_executed is not None:
        executed = executed_text_sha(path)
        if executed != expected_executed:
            raise ValueError(
                f"as-executed protocol sha256 {executed} != expected {expected_executed} "
                f"({path}): the text above {AMENDMENTS_HEADING!r} has changed"
            )
    return digest
