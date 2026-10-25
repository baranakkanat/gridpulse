"""Mission 11 Stage A: the decision LPs, the robust envelopes and the reliability rule.

EXPLORATORY and unregistered. The protocol is `stage_a_protocol.md` revision 2.2, whose
sha256 is `envelope_core.PROTOCOL_SHA256`; every solve-running stage of the runner is
expected to call `envelope_core.check_protocol` before it starts.

This module runs **zero power flows**. It imports neither pandapower nor simbench, and it
knows nothing about any particular network: every network fact arrives as an array
argument. `envelope_core` is imported and never edited.

The affine corner model (protocol s. 6)
---------------------------------------
Every method's predicted voltage at the all-at-limit corner of the box [0, e] is affine in
the envelope,

    v_hat(e) = alpha + S . e,          alpha in R^K, S in R^{K x N},

because the corner bus injections are themselves affine: P_bus(e) = U . e + P_fix with
P_fix = -W . l at the condition, and the corner reactive injection is the constant
Q_fix = -W . q (PV at unity power factor, protocol s. 3). The four builders below turn each
method's fitted object into (alpha, S); every decision function then sees only (alpha, S),
so the LPs are method-blind.

Conventions are `envelope_core`'s: power in MW, export-positive at a bus, voltage in pu,
K customer buses, N PV units, L branches (the transformer is branch 0). A regressor matrix
`B` is **p x K** (regressors by buses), as `RidgeFit.slopes` is.

Solver: `scipy.optimize.linprog(method="highs")` throughout. The robust box uses
`scipy.sparse`, because at K = 118 its dual has about 14,000 p-variables.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import optimize, sparse

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import envelope_core as ec  # noqa: E402  (the frozen task-1a core: imported, never edited)

# --- tolerances (protocol s. 13) -----------------------------------------------------------

#: the protocol revision this module was written against, taken from the frozen core so the
#: two can never drift apart. The runner checks it with `envelope_core.check_protocol`.
PROTOCOL_SHA256 = ec.PROTOCOL_SHA256

TOTAL_TOL = 1e-6  #: stage 2 holds sum(e) within 1e-6 MW of stage 1's optimum
ACTIVE_TOL = 1e-8  #: a row counts as active when its slack is at most this
ZERO_AVAIL = 1e-12  #: a unit with a_i at or below this has no decision to make
DEGENERATE_SHARE = 0.02  #: sum(e) <= 0.02 . sum(a) is `robust-degenerate` (s. 7)
CUT_TOL = 1e-6  #: Kelley cutting-plane tolerance in pu
MAX_ROUNDS = 60  #: B4's cut budget in **rounds** (revision 2.2); a round is one stage-1 solve
RESTORE_STEPS = 50  #: bisection steps of the uniform restoration after the budget (s. 7, B4)
GAP_FLAG_TOL = 0.01  #: a restored envelope with a larger optimality gap is flagged
KAPPA_T = 0.95  #: control T's thermal de-rating, fixed by the protocol

OK = "ok"
INFEASIBLE = "infeasible"
STAGE2_FAILED = "stage2_failed"
ROBUST_DEGENERATE = "robust-degenerate"


# --- A. the affine corner model (protocol s. 6) --------------------------------------------


def _corner_injection(U: np.ndarray, P_fix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(U, P_fix) as float arrays of shapes (K, N) and (K,)."""
    U_arr = np.asarray(U, dtype=float)
    p_fix = np.asarray(P_fix, dtype=float).ravel()
    if U_arr.ndim != 2 or U_arr.shape[0] != p_fix.size:
        raise ValueError(f"U must be K x N with K = {p_fix.size}, got {U_arr.shape}")
    return U_arr, p_fix


def affine_from_slopes(
    c: np.ndarray | float, B: np.ndarray, U: np.ndarray, P_fix: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The corner model of a slope-and-intercept fit: v_hat = c + B' . P_bus(e).

    `B` is p x K as in `envelope_core` (regressors by buses), `c` a scalar or (K,). With
    P_bus(e) = U.e + P_fix, alpha = c + B'.P_fix and S = B'.U.
    """
    U_arr, p_fix = _corner_injection(U, P_fix)
    B_arr = np.asarray(B, dtype=float)
    alpha = np.asarray(c, dtype=float) + B_arr.T @ p_fix
    return np.broadcast_to(alpha, (B_arr.shape[1],)).astype(float, copy=True), B_arr.T @ U_arr


def affine_from_centred(
    ybar: np.ndarray, B: np.ndarray, mu: np.ndarray, U: np.ndarray, P_fix: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The same model in the centred form the estimators return:

    v_hat_k = ybar_k + beta_k' . (P_bus(e) - mu), so alpha = ybar + B'.(P_fix - mu) and
    S = B'.U. Algebraically identical to `affine_from_slopes(ybar - mu'B, B, U, P_fix)`; it
    is offered separately so the caller never has to re-derive the intercept.
    """
    U_arr, p_fix = _corner_injection(U, P_fix)
    B_arr = np.asarray(B, dtype=float)
    mu_arr = np.asarray(mu, dtype=float).ravel()
    alpha = np.asarray(ybar, dtype=float).ravel() + B_arr.T @ (p_fix - mu_arr)
    return alpha, B_arr.T @ U_arr


def affine_from_structured(
    c: np.ndarray | float,
    path: np.ndarray,
    rho: np.ndarray,
    chi: np.ndarray,
    U: np.ndarray,
    P_fix: np.ndarray,
    Q_fix: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """The corner model of the LinDistFlow structure (B3, and Methods A and A-prime).

    With down = path', alpha = c + path.(rho o (down.P_fix) + chi o (down.Q_fix)) and
    S = path.diag(rho).down.U. The reactive term is constant at a condition, because PV runs
    at unity power factor, so it enters alpha only.

    `c` is a scalar or (K,): Method A passes its per-bus AC offset, A-prime its training
    intercept and B3 its jointly fitted busbar intercept.
    """
    U_arr, p_fix = _corner_injection(U, P_fix)
    path_f = np.asarray(path, dtype=float)
    rho_arr = np.asarray(rho, dtype=float).ravel()
    chi_arr = np.asarray(chi, dtype=float).ravel()
    q_fix = np.asarray(Q_fix, dtype=float).ravel()
    down = path_f.T
    alpha = np.asarray(c, dtype=float) + path_f @ (
        rho_arr * (down @ p_fix) + chi_arr * (down @ q_fix)
    )
    S = (path_f * rho_arr) @ (down @ U_arr)
    return np.broadcast_to(alpha, (path_f.shape[0],)).astype(float, copy=True), S


def affine_at_state(
    v_state: np.ndarray, S_true: np.ndarray, e_state: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """The oracle's re-linearisation (B5, protocol s. 7).

    Given an AC state with envelope `e_state` and bus voltages `v_state`, and the true
    sensitivities `S_true` in envelope space, the offset-corrected affine model that
    reproduces the AC state exactly is alpha = v_state - S_true.e_state.
    """
    S = np.asarray(S_true, dtype=float)
    v = np.asarray(v_state, dtype=float).ravel()
    e = np.asarray(e_state, dtype=float).ravel()
    return v - S @ e, S


# --- B. the primary decision LP (protocol s. 6) --------------------------------------------


def _availability(a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(a, movable): the availability vector and the mask of units with a_i > ZERO_AVAIL."""
    a_arr = np.asarray(a, dtype=float).ravel()
    if np.any(a_arr < 0.0):
        raise ValueError("availability a must be non-negative")
    return a_arr, a_arr > ZERO_AVAIL


def _voltage_rows(
    alpha: np.ndarray, S: np.ndarray, vmax: np.ndarray, margin: np.ndarray | float
) -> tuple[np.ndarray, np.ndarray]:
    """The (V) rows of protocol s. 6: S.e <= vmax - margin - alpha."""
    S_arr = np.asarray(S, dtype=float)
    alpha_arr = np.asarray(alpha, dtype=float).ravel()
    headroom = np.asarray(vmax, dtype=float).ravel() - np.asarray(margin, dtype=float) - alpha_arr
    if S_arr.shape[0] != alpha_arr.size:
        raise ValueError(f"S must be K x N with K = {alpha_arr.size}, got {S_arr.shape}")
    return S_arr, np.broadcast_to(headroom, (alpha_arr.size,)).astype(float, copy=True)


def _stack_extra(
    A: np.ndarray, b: np.ndarray, A_extra: np.ndarray | None, b_extra: np.ndarray | None
) -> tuple[np.ndarray, np.ndarray, int]:
    """Append the optional extra rows (control T's thermal module) and report their count."""
    if A_extra is None:
        return A, b, 0
    A_x = np.atleast_2d(np.asarray(A_extra, dtype=float))
    b_x = np.asarray(b_extra, dtype=float).ravel()
    if A_x.shape[0] != b_x.size or A_x.shape[1] != A.shape[1]:
        raise ValueError("A_extra/b_extra must be n_extra x N and (n_extra,)")
    return np.vstack([A, A_x]), np.concatenate([b, b_x]), int(b_x.size)


def _stage1(
    A: np.ndarray | sparse.spmatrix,
    b: np.ndarray,
    bounds: list[tuple[float, float]],
    n_free: int,
    n_vars: int,
) -> optimize.OptimizeResult:
    """Maximise the sum of the first `n_free` variables subject to A.x <= b."""
    cost = np.zeros(n_vars)
    cost[:n_free] = -1.0
    return optimize.linprog(cost, A_ub=A, b_ub=b, bounds=bounds, method="highs")


def _stage2_blocks(
    a: np.ndarray, movable: np.ndarray, total_star: float, n_vars: int, e_offset: int = 0
) -> tuple[sparse.csr_matrix, np.ndarray, np.ndarray, list[tuple[float, float]]]:
    """The stage-2 proportionality block of protocol s. 6.

    With theta_bar = sum(e*)/sum(a), one auxiliary t_i per movable unit carries
    t_i >= |e_i/a_i - theta_bar|, and the objective minimises sum_i t_i. Units with
    a_i <= ZERO_AVAIL are fixed at e_i = 0 and carry no auxiliary (they have no share to be
    proportional in). A row -sum(e) <= -(sum(e*) - 1e-6) holds the stage-1 optimum.

    Returns (A_block, b_block, cost, extra_bounds) in the variable order [x, t], where `x`
    is the stage-1 variable vector of length `n_vars` whose envelope block starts at
    `e_offset`.
    """
    n_units = a.size
    idx = np.flatnonzero(movable)
    n_t = idx.size
    total_a = float(a.sum())
    theta_bar = total_star / total_a if total_a > 0.0 else 0.0

    rows, cols, data, rhs = [], [], [], []

    def add(row: int, col: int, value: float) -> None:
        rows.append(row)
        cols.append(col)
        data.append(value)

    # 1. hold the stage-1 total.
    for i in range(n_units):
        add(0, e_offset + i, -1.0)
    rhs.append(-(total_star - TOTAL_TOL))

    # 2. +/- deviation rows, one pair per movable unit.
    for j, i in enumerate(idx):
        up = 1 + 2 * j
        lo = 2 + 2 * j
        add(up, e_offset + i, 1.0 / a[i])
        add(up, n_vars + j, -1.0)
        rhs.append(theta_bar)
        add(lo, e_offset + i, -1.0 / a[i])
        add(lo, n_vars + j, -1.0)
        rhs.append(-theta_bar)

    A_block = sparse.csr_matrix((data, (rows, cols)), shape=(1 + 2 * n_t, n_vars + n_t))
    cost = np.zeros(n_vars + n_t)
    cost[n_vars:] = 1.0
    return A_block, np.asarray(rhs, dtype=float), cost, [(0.0, None)] * n_t


def _two_stage(
    A: np.ndarray | sparse.spmatrix,
    b: np.ndarray,
    bounds: list[tuple[float, float]],
    a: np.ndarray,
    movable: np.ndarray,
    n_vars: int,
    e_offset: int = 0,
) -> dict:
    """The common two-stage solve of protocol s. 6, on a generic variable vector.

    The envelope occupies `n_units` entries starting at `e_offset`; every other variable is
    an auxiliary of the caller's robust formulation and is carried through both stages
    untouched. Returns a dict with `e`, `total`, `status`, `stage2_l1_move` and `slack`
    (the stage-A row slacks at the returned point), which the callers turn into their own
    active-set read-outs.
    """
    if e_offset != 0:  # not used by this module, but the offset must not be silently ignored
        raise NotImplementedError("the envelope block must start at index 0")
    n_units = a.size
    A_s = sparse.csr_matrix(A) if sparse.issparse(A) else np.asarray(A, dtype=float)
    res1 = _stage1(A_s, b, bounds, n_units, n_vars)
    if not res1.success:
        zero = np.zeros(n_units)
        return {
            "e": zero,
            "total": 0.0,
            "status": INFEASIBLE,
            "stage2_l1_move": 0.0,
            "slack": None,
            "message": str(res1.message),
        }

    x1 = np.asarray(res1.x, dtype=float)
    e1 = x1[:n_units]
    total_star = float(e1.sum())

    A_block, b_block, cost2, t_bounds = _stage2_blocks(a, movable, total_star, n_vars)
    A2 = sparse.vstack(
        [
            sparse.hstack([sparse.csr_matrix(A_s), sparse.csr_matrix((b.size, len(t_bounds)))]),
            A_block,
        ],
        format="csr",
    )
    res2 = optimize.linprog(
        cost2,
        A_ub=A2,
        b_ub=np.concatenate([b, b_block]),
        bounds=bounds + t_bounds,
        method="highs",
    )
    if res2.success:
        x = np.asarray(res2.x, dtype=float)[:n_vars]
        e = x[:n_units]
        status = OK
    else:
        x, e, status = x1, e1, STAGE2_FAILED

    denom = max(float(np.abs(e1).sum()), 1e-12)
    move = float(np.abs(e - e1).sum()) / denom
    slack = b - (A_s @ x)
    return {
        "e": e,
        "total": float(e.sum()),
        "status": status,
        "stage2_l1_move": move,
        "slack": np.asarray(slack, dtype=float).ravel(),
        "message": str(res2.message),
    }


def voltage_envelope(
    alpha: np.ndarray,
    S: np.ndarray,
    vmax: np.ndarray,
    margin: np.ndarray | float,
    a: np.ndarray,
    A_extra: np.ndarray | None = None,
    b_extra: np.ndarray | None = None,
) -> dict:
    """The primary decision of protocol s. 6: maximise sum(e) under the predicted corner.

    Variables 0 <= e <= a; rows S.e <= vmax - margin - alpha plus the optional `A_extra.e <=
    b_extra` (control T's thermal module, from `thermal_rows`). Stage 1 maximises sum(e);
    stage 2 holds sum(e) within 1e-6 MW and minimises the L1 distance of the shares e_i/a_i
    from theta_bar = sum(e*)/sum(a), which selects the most proportional optimum.

    An infeasible stage 1 returns e = 0 with `status = "infeasible"`: e = 0 is *never*
    returned as a solution without that flag. A failed stage 2 keeps stage 1's e and flags
    `stage2_failed`.

    Returns a dict with `e`, `total`, `status`, `stage2_l1_move` (the L1 move of stage 2
    relative to stage 1), `active_v` (the voltage rows with slack <= 1e-8) and
    `active_extra`.
    """
    a_arr, movable = _availability(a)
    S_arr, headroom = _voltage_rows(alpha, S, vmax, margin)
    if S_arr.shape[1] != a_arr.size:
        raise ValueError(f"S must be K x N with N = {a_arr.size}, got {S_arr.shape}")
    A, b, n_extra = _stack_extra(S_arr, headroom, A_extra, b_extra)
    bounds = [(0.0, float(a_arr[i])) if movable[i] else (0.0, 0.0) for i in range(a_arr.size)]

    out = _two_stage(A, b, bounds, a_arr, movable, a_arr.size)
    n_v = headroom.size
    if out["slack"] is None:
        out["active_v"] = np.zeros(0, dtype=int)
        out["active_extra"] = np.zeros(0, dtype=int)
    else:
        slack = out["slack"]
        out["active_v"] = np.flatnonzero(slack[:n_v] <= ACTIVE_TOL)
        out["active_extra"] = np.flatnonzero(slack[n_v : n_v + n_extra] <= ACTIVE_TOL)
    out.pop("slack")
    return out


def proportional_envelope(
    alpha: np.ndarray,
    S: np.ndarray,
    vmax: np.ndarray,
    margin: np.ndarray | float,
    a: np.ndarray,
) -> dict:
    """The proportional-fair decision (B2p, control J, protocol s. 6): e = theta.a, one scalar.

    theta = min(1, min over the buses with (S.a)_k > 0 of (vmax_k - margin_k - alpha_k)/(S.a)_k),
    clipped at 0.

    **The flag covers every bus already above its limit at e = 0**, not only those with
    (S.a)_k <= 0. A negative headroom forces theta = 0 either way - with (S.a)_k > 0 the
    ratio is negative and the clip at 0 does it - and e = 0 does *not* satisfy such a row,
    so returning `ok` there would present an infeasible envelope as a solution. The
    dispatching brief flags only the (S.a)_k <= 0 case; this is the strict superset, so the
    brief's case is still flagged (reported as a disagreement).

    Returns a dict with `theta`, `e`, `total`, `binding` (the bus index that sets theta, or -1
    when no row binds), `status` and `negative_headroom` (the buses above their limit at
    e = 0).
    """
    a_arr, _ = _availability(a)
    S_arr, headroom = _voltage_rows(alpha, S, vmax, margin)
    load = S_arr @ a_arr

    positive = load > 0.0
    negative_headroom = np.flatnonzero(headroom < 0.0)
    theta, binding = 1.0, -1
    if np.any(positive):
        ratios = headroom[positive] / load[positive]
        where = int(np.argmin(ratios))
        if float(ratios[where]) < theta:
            theta = float(ratios[where])
            binding = int(np.flatnonzero(positive)[where])
    if negative_headroom.size:
        # theta is 0 regardless; name the most-violated of those buses as the binding one.
        theta = 0.0
        binding = int(negative_headroom[np.argmin(headroom[negative_headroom])])
    theta = float(np.clip(theta, 0.0, 1.0))
    e = theta * a_arr
    return {
        "theta": theta,
        "e": e,
        "total": float(e.sum()),
        "binding": binding,
        "status": INFEASIBLE if negative_headroom.size else OK,
        "negative_headroom": negative_headroom,
    }


def thermal_rows(
    down: np.ndarray,
    U: np.ndarray,
    P_fix: np.ndarray,
    caps: np.ndarray,
    kappa: float = KAPPA_T,
) -> tuple[np.ndarray, np.ndarray]:
    """Control T's common thermal module (protocol s. 6), as rows in e.

    The lossless P-only flow on branch l is f_l(e) = down_l . (U.e + P_fix), i.e. the net
    downstream export, and both f_l <= kappa.cap_l and -f_l <= kappa.cap_l are imposed. The
    returned (A, b) go straight into `voltage_envelope`'s `A_extra`/`b_extra`, export rows
    first and import rows second.

    `caps` is in MW-equivalent: the runner passes I_max . sqrt(3) . V_nom for a line and S_n
    for the transformer. No method is scored on a learned thermal model, so this module
    depends only on topology, ratings, e and the condition's loads.
    """
    U_arr = np.asarray(U, dtype=float)
    down_arr = np.atleast_2d(np.asarray(down, dtype=float))
    p_fix = np.asarray(P_fix, dtype=float).ravel()
    caps_arr = np.asarray(caps, dtype=float).ravel()
    if down_arr.shape[1] != p_fix.size or down_arr.shape[0] != caps_arr.size:
        raise ValueError("down must be L x K and caps (L,)")
    if np.any(caps_arr < 0.0):
        raise ValueError("caps must be non-negative")

    coef = down_arr @ U_arr  # L x N
    base = down_arr @ p_fix  # L, the flow at e = 0
    limit = float(kappa) * caps_arr
    A = np.vstack([coef, -coef])
    b = np.concatenate([limit - base, limit + base])
    return A, b


# --- C. the robust box, B4box (protocol s. 7) ----------------------------------------------


def box_worst_case(x: np.ndarray, sd_k: np.ndarray, gamma: int, k_sigma: float = 3.0) -> float:
    """The Bertsimas-Sim worst case of bus k: the sum of the Gamma largest k_sigma.sd_kj.|x_j|.

    Gamma is the protocol's integer budget (ceil(sqrt(p)) coefficients per bus). This is the
    primal value the LP dual of `box_envelope` reproduces, and the tests check them against
    brute-force subset enumeration.
    """
    terms = (
        float(k_sigma)
        * np.abs(np.asarray(sd_k, dtype=float).ravel())
        * np.abs(np.asarray(x, dtype=float).ravel())
    )
    g = int(gamma)
    if g <= 0:
        return 0.0
    if g >= terms.size:
        return float(terms.sum())
    return float(np.sort(terms)[-g:].sum())


def _box_program(
    ybar: np.ndarray,
    B: np.ndarray,
    sd: np.ndarray,
    mu: np.ndarray,
    U: np.ndarray,
    P_fix: np.ndarray,
    vmax: np.ndarray,
    gamma: float,
    k_sigma: float,
) -> tuple[sparse.csr_matrix, np.ndarray, int, int]:
    """The sparse Bertsimas-Sim dual of protocol s. 7's robust rows.

    Variables, in order: e (N), u (p), z (K), p (K.p), with

        u_j >= +x_j(e),  u_j >= -x_j(e),  z_k + p_kj >= k_sigma.sd_kj.u_j,

    so that bus k's robust row is ybar_k + beta_k'x(e) + Gamma.z_k + sum_j p_kj <= vmax_k.
    x(e) = U.e + P_fix - mu. Returns (A, b, n_vars, n_robust_rows); the robust rows are the
    **last** K rows, which is what the caller reads its active set and tightness from.
    """
    U_arr, p_fix = _corner_injection(U, P_fix)
    B_arr = np.asarray(B, dtype=float)
    mu_arr = np.asarray(mu, dtype=float).ravel()
    sd_arr = np.atleast_2d(np.asarray(sd, dtype=float))
    ybar_arr = np.asarray(ybar, dtype=float).ravel()
    vmax_arr = np.asarray(vmax, dtype=float).ravel()
    n_units = U_arr.shape[1]
    n_reg, n_bus = B_arr.shape
    if sd_arr.shape != (n_bus, n_reg):
        raise ValueError(f"sd must be K x p = {(n_bus, n_reg)}, got {sd_arr.shape}")
    if mu_arr.size != n_reg or p_fix.size != n_reg:
        raise ValueError("mu and P_fix must both have one entry per regressor")

    x0 = p_fix - mu_arr  # x(e) = U.e + x0
    n_vars = n_units + n_reg + n_bus + n_bus * n_reg
    off_u = n_units
    off_z = off_u + n_reg
    off_p = off_z + n_bus

    U_s = sparse.csr_matrix(U_arr)
    eye_p = sparse.identity(n_reg, format="csr")
    zero = sparse.csr_matrix

    # 1. u_j >= x_j(e) and u_j >= -x_j(e).
    abs_rows = sparse.vstack(
        [
            sparse.hstack([U_s, -eye_p, zero((n_reg, n_bus)), zero((n_reg, n_bus * n_reg))]),
            sparse.hstack([-U_s, -eye_p, zero((n_reg, n_bus)), zero((n_reg, n_bus * n_reg))]),
        ]
    )
    abs_b = np.concatenate([-x0, x0])

    # 2. k_sigma.sd_kj.u_j - z_k - p_kj <= 0, one row per (k, j).
    rows = np.arange(n_bus * n_reg)
    k_of = rows // n_reg
    j_of = rows % n_reg
    bs_rows = sparse.coo_matrix(
        (
            np.concatenate(
                [float(k_sigma) * sd_arr.ravel(), -np.ones(rows.size), -np.ones(rows.size)]
            ),
            (
                np.concatenate([rows, rows, rows]),
                np.concatenate([off_u + j_of, off_z + k_of, off_p + rows]),
            ),
        ),
        shape=(n_bus * n_reg, n_vars),
    ).tocsr()
    bs_b = np.zeros(n_bus * n_reg)

    # 3. the robust rows themselves.
    robust = sparse.hstack(
        [
            sparse.csr_matrix(B_arr.T @ U_arr),
            zero((n_bus, n_reg)),
            float(gamma) * sparse.identity(n_bus, format="csr"),
            sparse.kron(sparse.identity(n_bus, format="csr"), np.ones((1, n_reg))),
        ]
    )
    robust_b = vmax_arr - ybar_arr - B_arr.T @ x0

    A = sparse.vstack([abs_rows, bs_rows, robust], format="csr")
    b = np.concatenate([abs_b, bs_b, robust_b])
    return A, b, n_vars, n_bus


def box_envelope(
    ybar: np.ndarray,
    B: np.ndarray,
    sd: np.ndarray,
    mu: np.ndarray,
    U: np.ndarray,
    P_fix: np.ndarray,
    vmax: np.ndarray,
    a: np.ndarray,
    gamma: float,
    k_sigma: float = 3.0,
) -> dict:
    """B4box and B4box-OLS: the Gupta-style robust box (protocol s. 7).

    The robust constraint at bus k is

        ybar_k + beta_k'x(e) + max_{|J| <= Gamma} sum_{j in J} k_sigma.sd_kj.|x_j(e)| <= vmax_k,

    with x(e) = U.e + P_fix - mu. It is imposed in its Bertsimas-Sim LP dual form (see
    `_box_program`), sparsely: at K = 118 there are about 14,000 p-variables. The two stages
    of `voltage_envelope` then run on e inside that polytope.

    **Degenerate rule.** An infeasible LP, or sum(e) <= 0.02.sum(a), returns
    `status = "robust-degenerate"`: such a condition is never recorded as a safe envelope.

    Returns a dict with `e`, `total`, `status`, `stage2_l1_move`, `active_v` (the robust rows
    that are active) and `worst_case` (the realised per-bus worst-case term at the solution).
    """
    a_arr, movable = _availability(a)
    A, b, n_vars, n_robust = _box_program(ybar, B, sd, mu, U, P_fix, vmax, gamma, k_sigma)
    bounds: list[tuple[float, float | None]] = [
        (0.0, float(a_arr[i])) if movable[i] else (0.0, 0.0) for i in range(a_arr.size)
    ]
    bounds += [(0.0, None)] * (n_vars - a_arr.size)  # u, z and p are all non-negative

    out = _two_stage(A, b, bounds, a_arr, movable, n_vars)
    total_a = float(a_arr.sum())
    degenerate = out["status"] == INFEASIBLE or out["total"] <= DEGENERATE_SHARE * total_a
    if out["slack"] is None:
        out["active_v"] = np.zeros(0, dtype=int)
    else:
        out["active_v"] = np.flatnonzero(out["slack"][-n_robust:] <= ACTIVE_TOL)
    out.pop("slack")

    U_arr, p_fix = _corner_injection(U, P_fix)
    x = U_arr @ out["e"] + p_fix - np.asarray(mu, dtype=float).ravel()
    sd_arr = np.atleast_2d(np.asarray(sd, dtype=float))
    out["worst_case"] = np.array(
        [box_worst_case(x, sd_arr[k], int(gamma), k_sigma) for k in range(sd_arr.shape[0])]
    )
    if degenerate:
        out["status"] = ROBUST_DEGENERATE
    return out


# --- D. the robust ellipsoid, B4 (protocol s. 7) -------------------------------------------


def ellipsoid_envelope(
    ybar: np.ndarray,
    B: np.ndarray,
    Minv: np.ndarray,
    r2: np.ndarray,
    mu: np.ndarray,
    U: np.ndarray,
    P_fix: np.ndarray,
    vmax: np.ndarray,
    a: np.ndarray,
    tol: float = CUT_TOL,
    max_rounds: int = MAX_ROUNDS,
) -> dict:
    """B4: the robust ellipsoid over the data-consistent set (protocol s. 7, revision 2.2).

    The robust constraint at bus k is

        g_k(e) = ybar_k + beta_k'x + r_k.sqrt(x'M^-1 x) - vmax_k <= 0,   x = U.e + P_fix - mu,

    with r_k = sqrt(r2_k). It is solved by **Kelley cutting planes**: start from the nominal
    rows, solve stage 1, and at its solution add, for every bus with g_k > tol, the
    supporting cut

        (beta_k + r_k.M^-1 x / sqrt(x'M^-1 x))' x(e) <= vmax_k - ybar_k

    (skipped when x'M^-1 x <= 0, where the norm term vanishes and the nominal row is already
    exact). Iterate until max_k g_k <= tol, then run stage 2 inside the cut polytope and
    re-check g there; a violation at the stage-2 point adds cuts and returns to stage 1.

    **The budget is `max_rounds` = 60 rounds** (revision 2.2), where a round is one stage-1
    solve together with the cuts taken at its solution; revision 2's row-counting budget was
    exhausted in two rounds at K = 118. If the cuts have not converged within the budget, the
    last stage-1 envelope e1 is **uniformly restored**: `RESTORE_STEPS` bisection steps find
    the largest theta in [0, 1] with max_k g_k(theta.e1) <= 0, and e = theta.e1 is returned
    with `status = "ok"` and `restored = True`. Since e1's total is the cut LP's upper bound,
    the optimality gap is `gap` = 1 - theta, flagged when it exceeds `GAP_FLAG_TOL`.
    **Stage 2 is skipped for a restored envelope** (it is proportional in e1 already, and the
    cut polytope it would search is the one the budget failed to tighten), so
    `stage2_l1_move` is 0.

    **Degenerate rule.** Only three cases return `status = "robust-degenerate"`: an infeasible
    LP; g(0) > tol, where even e = 0 is not robust-feasible; and a final sum(e) <=
    0.02.sum(a). **A budget limit alone is never `robust-degenerate`.**

    Returns a dict with `e`, `total`, `status`, `stage2_l1_move`, `active_v`, `n_rounds`,
    `n_cuts` (the rows added beyond the nominal ones), `restored`, `gap`, `gap_flag` and
    `max_g` (max_k g_k at the returned envelope).
    """
    a_arr, movable = _availability(a)
    U_arr, p_fix = _corner_injection(U, P_fix)
    B_arr = np.asarray(B, dtype=float)
    mu_arr = np.asarray(mu, dtype=float).ravel()
    ybar_arr = np.asarray(ybar, dtype=float).ravel()
    vmax_arr = np.asarray(vmax, dtype=float).ravel()
    Minv_arr = np.asarray(Minv, dtype=float)
    r = np.sqrt(np.maximum(np.asarray(r2, dtype=float).ravel(), 0.0))
    x0 = p_fix - mu_arr
    n_bus = B_arr.shape[1]
    bounds = [(0.0, float(a_arr[i])) if movable[i] else (0.0, 0.0) for i in range(a_arr.size)]
    total_a = float(a_arr.sum())

    def g_of(e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = U_arr @ e + x0
        quad = float(x @ (Minv_arr @ x))
        norm = math.sqrt(max(quad, 0.0))
        g = ybar_arr + B_arr.T @ x + r * norm - vmax_arr
        return g, x

    def cuts_at(e: np.ndarray, violated: np.ndarray, x: np.ndarray):
        quad = float(x @ (Minv_arr @ x))
        if quad <= 0.0:  # the nominal row is already the exact constraint at x = 0
            return None, None
        grad = (Minv_arr @ x) / math.sqrt(quad)
        A_new = np.empty((violated.size, a_arr.size))
        b_new = np.empty(violated.size)
        for row, k in enumerate(violated):
            coef = B_arr[:, k] + r[k] * grad
            A_new[row] = coef @ U_arr
            b_new[row] = vmax_arr[k] - ybar_arr[k] - coef @ x0
        return A_new, b_new

    def degenerate(reason: str, n_rounds: int, n_cuts: int, max_g: float) -> dict:
        return {
            "e": np.zeros(a_arr.size),
            "total": 0.0,
            "status": ROBUST_DEGENERATE,
            "stage2_l1_move": 0.0,
            "active_v": np.zeros(0, dtype=int),
            "n_rounds": n_rounds,
            "n_cuts": n_cuts,
            "restored": False,
            "gap": math.nan,
            "gap_flag": False,
            "max_g": max_g,
            "reason": reason,
        }

    # e = 0 must itself be robust-feasible, or no envelope is (s. 7's degenerate rule).
    g_zero, _ = g_of(np.zeros(a_arr.size))
    if float(g_zero.max()) > tol:
        return degenerate("g_zero", 0, 0, float(g_zero.max()))

    # the nominal rows (beta-hat only).
    A = B_arr.T @ U_arr
    b = vmax_arr - ybar_arr - B_arr.T @ x0
    n_cuts = 0
    n_rounds = 0
    out: dict | None = None
    e1_last = np.zeros(a_arr.size)
    while n_rounds < int(max_rounds):
        res1 = _stage1(A, b, bounds, a_arr.size, a_arr.size)
        n_rounds += 1
        if not res1.success:
            return degenerate(INFEASIBLE, n_rounds, n_cuts, math.nan)
        e1 = np.asarray(res1.x, dtype=float)
        e1_last = e1
        g1, x1 = g_of(e1)
        violated = np.flatnonzero(g1 > tol)
        if violated.size:
            A_new, b_new = cuts_at(e1, violated, x1)
            if A_new is None:
                violated = np.zeros(0, dtype=int)
            else:
                A = np.vstack([A, A_new])
                b = np.concatenate([b, b_new])
                n_cuts += int(A_new.shape[0])
                continue

        # stage 1 is robust-feasible: run stage 2 inside the current cut polytope.
        stage = _two_stage(A, b, bounds, a_arr, movable, a_arr.size)
        g2, x2 = g_of(stage["e"])
        viol2 = np.flatnonzero(g2 > tol)
        if viol2.size:
            A_new, b_new = cuts_at(stage["e"], viol2, x2)
            if A_new is not None:
                A = np.vstack([A, A_new])
                b = np.concatenate([b, b_new])
                n_cuts += int(A_new.shape[0])
                continue
        slack = stage.pop("slack")
        stage["active_v"] = (
            np.zeros(0, dtype=int) if slack is None else np.flatnonzero(slack[:n_bus] <= ACTIVE_TOL)
        )
        stage["n_rounds"] = n_rounds
        stage["n_cuts"] = n_cuts
        stage["restored"] = False
        stage["gap"] = 0.0
        stage["gap_flag"] = False
        stage["max_g"] = float(g2.max())
        out = stage
        break

    if out is None:  # the round budget ran out: uniformly restore the last stage-1 envelope
        lo, hi = 0.0, 1.0
        for _ in range(RESTORE_STEPS):
            mid = bisection_backoff(lo, hi)
            if float(g_of(mid * e1_last)[0].max()) <= 0.0:
                lo = mid
            else:
                hi = mid
        e = lo * e1_last
        g_final, _ = g_of(e)
        slack = b[:n_bus] - (A[:n_bus] @ e)
        out = {
            "e": e,
            "total": float(e.sum()),
            "status": OK,
            "stage2_l1_move": 0.0,  # stage 2 is skipped for a restored envelope
            "active_v": np.flatnonzero(slack <= ACTIVE_TOL),
            "n_rounds": n_rounds,
            "n_cuts": n_cuts,
            "restored": True,
            "gap": 1.0 - lo,  # e1_last's total is the cut LP's upper bound
            "gap_flag": (1.0 - lo) > GAP_FLAG_TOL,
            "max_g": float(g_final.max()),
            "reason": "max_rounds",
        }

    if out["total"] <= DEGENERATE_SHARE * total_a:
        out["status"] = ROBUST_DEGENERATE
        out["reason"] = "low_total"
    return out


# --- E. the reliability rule and its controls (protocol s. 7, s. 8) ------------------------


def cert_choice(
    e_b2: np.ndarray,
    alt_envelopes: np.ndarray,
    tol_total: float = 0.10,
    tol_l1: float = 0.10,
) -> dict:
    """CERT's act-or-fall-back rule (protocol s. 7).

    CERT acts on B2's envelope when the four random data-consistent alternatives agree with
    it: their total-export spread must be below `tol_total` of B2's total, and every
    alternative must lie within `tol_l1` of B2's envelope in relative L1. Otherwise CERT
    falls back to B2p.

    `alt_envelopes` is M x N. Returns a dict with `act`, `spread`, `l1` (the per-alternative
    relative L1 distances) and `total_b2`. A B2 total at or below 1e-12 MW carries no
    allocation to certify, so `act` is False; so does an empty alternative set.
    """
    e = np.asarray(e_b2, dtype=float).ravel()
    alts = np.atleast_2d(np.asarray(alt_envelopes, dtype=float))
    total_b2 = float(e.sum())
    if alts.size == 0 or alts.shape[0] == 0:
        return {"act": False, "spread": 0.0, "l1": np.zeros(0), "total_b2": total_b2}
    if alts.shape[1] != e.size:
        raise ValueError(f"alt_envelopes must be M x {e.size}, got {alts.shape}")

    totals = alts.sum(axis=1)
    if total_b2 <= 1e-12:
        spread = math.inf
        l1 = np.full(alts.shape[0], math.inf)
        return {"act": False, "spread": spread, "l1": l1, "total_b2": total_b2}
    spread = float(totals.max() - totals.min()) / total_b2
    l1 = np.abs(alts - e).sum(axis=1) / float(np.abs(e).sum())
    act = bool(spread < tol_total and float(l1.max()) <= tol_l1)
    return {"act": act, "spread": spread, "l1": l1, "total_b2": total_b2}


def rand_fallback(rng: np.random.Generator, n: int, k: int) -> np.ndarray:
    """Control RAND: exactly `k` of `n` conditions fall back, drawn uniformly without
    replacement, so RAND matches CERT's realised fallback count exactly (protocol s. 7).

    Returns a boolean mask of length n; True means "fall back to B2p on this condition".
    """
    n, k = int(n), int(k)
    if not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n, got k = {k}, n = {n}")
    mask = np.zeros(n, dtype=bool)
    if k:
        mask[rng.choice(n, size=k, replace=False)] = True
    return mask


def ambiguity_measures(
    alt_totals: np.ndarray,
    alt_envelopes: np.ndarray,
    oracle_total: float,
    alt_safe: np.ndarray,
) -> dict:
    """H4's decision-ambiguity measures at one condition (protocol s. 8).

    * `export_spread` = (max - min) of sum(e) over the alternatives, divided by the oracle's
      sum(e) (inf if that is zero);
    * `allocation_spread` = the maximum pairwise L1 distance between the alternatives'
      envelopes;
    * `safety_disagreement` = True when at least one alternative is voltage-safe and at least
      one is voltage-unsafe.
    """
    totals = np.asarray(alt_totals, dtype=float).ravel()
    alts = np.atleast_2d(np.asarray(alt_envelopes, dtype=float))
    safe = np.asarray(alt_safe, dtype=bool).ravel()
    oracle = float(oracle_total)
    spread = float(totals.max() - totals.min()) if totals.size else 0.0
    pair = 0.0
    for i in range(alts.shape[0]):
        for j in range(i + 1, alts.shape[0]):
            pair = max(pair, float(np.abs(alts[i] - alts[j]).sum()))
    return {
        "export_spread": spread / oracle if oracle > 0.0 else math.inf,
        "allocation_spread": pair,
        "safety_disagreement": bool(safe.any() and (~safe).any()),
    }


def interior_point(rng: np.random.Generator, e: np.ndarray) -> np.ndarray:
    """A uniform interior point of the box [0, e] (protocol s. 15's monotonicity check):
    one U(0, 1) draw per unit, times e."""
    e_arr = np.asarray(e, dtype=float).ravel()
    return rng.uniform(0.0, 1.0, size=e_arr.size) * e_arr


def bisection_backoff(lo: float, hi: float) -> float:
    """The midpoint of the oracle's back-off bracket (protocol s. 7, B5)."""
    return 0.5 * (float(lo) + float(hi))


@dataclass
class OracleState:
    """B5's oracle protocol as a pure state machine (protocol s. 7).

    The oracle re-linearises the true sensitivities at the current AC state, re-solves the
    LP, and AC-scores the result: **at most 6 such sequential-LP steps**, stopping when the
    AC power flow is feasible (maximum upper-voltage exceedance <= 0) *and* sum(e) has
    changed by less than 0.5 %. If the last LP step is still infeasible, it backs off by
    bisection on a uniform factor applied to that step's envelope: **at most 8 solves**,
    keeping the largest AC-feasible factor. The total budget is 14 solves.

    **This object never solves anything.** The runner asks `next_action()` what to compute,
    performs the one AC solve it names, and reports the outcome with `submit`. That keeps
    every power flow in the runner, where the ledger is, and leaves this module at zero
    flows.

    Usage::

        state = OracleState()
        while not state.done:
            action = state.next_action()
            if action["kind"] == "relinearise":
                e = ...   # LP on sensitivities re-linearised at state.last_state
            else:
                e = action["factor"] * state.reference
            exceedance = ...  # one AC solve
            state.submit(e, exceedance)

    After `done`, `best_e` is the largest AC-feasible envelope seen (zeros if none was) and
    `status` is one of `ok`, `budget` or `infeasible`.
    """

    max_lp: int = 6
    max_bisect: int = 8
    rel_tol: float = 0.005
    phase: str = "lp"
    lp_steps: int = 0
    bisect_steps: int = 0
    lo: float = 0.0
    hi: float = 1.0
    status: str = "running"
    reference: np.ndarray | None = field(default=None, repr=False)
    best_e: np.ndarray | None = field(default=None, repr=False)
    last_total: float | None = None
    history: list[dict] = field(default_factory=list, repr=False)

    @property
    def budget(self) -> int:
        """The protocol's solve ceiling for one oracle run: 6 sequential LPs plus 8 bisections."""
        return int(self.max_lp) + int(self.max_bisect)

    @property
    def solves(self) -> int:
        """AC solves consumed so far; never more than `budget`."""
        return int(self.lp_steps) + int(self.bisect_steps)

    @property
    def done(self) -> bool:
        return self.phase == "done"

    def next_action(self) -> dict:
        """What the runner should AC-score next.

        * `{"kind": "relinearise"}` - re-solve the LP at the last AC state and score it;
        * `{"kind": "scale", "factor": f}` - score `f` times `self.reference`;
        * `{"kind": "stop"}` - the run is over.
        """
        if self.phase == "done":
            return {"kind": "stop"}
        if self.solves >= self.budget:
            self._finish("budget")
            return {"kind": "stop"}
        if self.phase == "lp":
            return {"kind": "relinearise"}
        return {"kind": "scale", "factor": bisection_backoff(self.lo, self.hi)}

    def submit(self, e: np.ndarray, max_exceedance: float) -> dict:
        """Record one AC-scored envelope and advance the state machine.

        `max_exceedance` is the maximum upper-voltage exceedance in pu at the corner: a
        value at or below 0 means AC-feasible.
        """
        if self.phase == "done":
            raise RuntimeError("the oracle has stopped; no further result can be submitted")
        e_arr = np.asarray(e, dtype=float).ravel().copy()
        total = float(e_arr.sum())
        feasible = float(max_exceedance) <= 0.0
        phase = self.phase
        if phase == "lp":
            self.lp_steps += 1
        else:
            self.bisect_steps += 1
        self.history.append(
            {
                "phase": phase,
                "total": total,
                "max_exceedance": float(max_exceedance),
                "feasible": feasible,
            }
        )
        if feasible and (self.best_e is None or total > float(self.best_e.sum())):
            self.best_e = e_arr

        if phase == "lp":
            converged = (
                feasible
                and self.last_total is not None
                and abs(total - self.last_total) < self.rel_tol * max(abs(self.last_total), 1e-12)
            )
            self.last_total = total
            self.reference = e_arr
            if converged:
                self._finish(OK)
            elif self.lp_steps >= self.max_lp:
                if feasible:
                    self._finish(OK)
                else:
                    self.phase = "bisect"  # a uniform back-off on the last LP envelope
                    self.lo, self.hi = 0.0, 1.0
                    self.best_e = self.best_e if self.best_e is not None else np.zeros_like(e_arr)
            if self.solves >= self.budget and not self.done:
                self._finish("budget")
            return self.history[-1]

        factor = bisection_backoff(self.lo, self.hi)
        if feasible:
            self.lo = factor
        else:
            self.hi = factor
        if self.bisect_steps >= self.max_bisect or self.solves >= self.budget:
            self._finish(OK if self.lo > 0.0 else "infeasible")
        return self.history[-1]

    def _finish(self, status: str) -> None:
        self.phase = "done"
        self.status = status
        if self.best_e is None:
            self.best_e = np.zeros(0)
