"""Tests for the Mission 11 Stage A decision LPs (`envelope_lp.py`).

**Zero power flows.** Neither pandapower nor simbench is imported, directly or indirectly;
one test asserts that. Every fixture is a genuinely synthetic radial toy with round
parameter values chosen here (protocol s. 16):

* a 5-bus radial tree: a source busbar and 4 customer buses, joined by 4 branches, branch 0
  being the transformer;
* r = 0.1 ohm and x = 0.05 ohm on every branch, on a 0.4 kV base, so rho = r/V_nom^2 = 0.625
  pu per MW and chi = 0.3125 pu per Mvar;
* 3 PV units, on customer buses 1, 2 and 3;
* one load per customer bus, at round MW values, and Q at a power factor of tan(phi) = 0.3.

No SimBench or IEEE parameter value appears here. Every expected answer is a closed form, a
brute-force enumeration or a bisection computed inside the test.
"""

from __future__ import annotations

import ast
import hashlib
import itertools
import math
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import envelope_core as ec  # noqa: E402
import envelope_lp as lp  # noqa: E402

# --- the synthetic feeder ------------------------------------------------------------------

R_OHM = 0.1  # per branch, a round value chosen here
X_OHM = 0.05
V_BASE_KV = 0.4
RHO = R_OHM / V_BASE_KV**2  # 0.625 pu per MW
CHI = X_OHM / V_BASE_KV**2  # 0.3125 pu per Mvar

PARENT = np.array([-1, 0, 1, 0])  # 0 = transformer; 1 and 3 hang off it; 2 hangs off 1
CHILD_BUS = np.array([0, 1, 2, 3])  # every branch ends on a customer bus
N_BRANCHES = 4
K_BUSES = 4
N_UNITS = 3

PV_BUS = np.array([1, 2, 3])  # PV unit i sits on customer bus PV_BUS[i]
LOAD_MW = np.array([0.010, 0.020, 0.015, 0.015])
TAN_PHI = 0.3
V_SOURCE = 1.0  # the busbar intercept of the structured model
V_MAX = 1.10  # the synthetic upper limit, uniform over the toy's buses

RATING = np.array([0.030, 0.040, 0.050])


def feeder():
    """(path, down, U, P_fix, Q_fix) for the toy, all as float arrays."""
    path, down = ec.tree_matrices(PARENT, CHILD_BUS, N_BRANCHES)
    U = np.zeros((K_BUSES, N_UNITS))
    U[PV_BUS, np.arange(N_UNITS)] = 1.0
    P_fix = -LOAD_MW.copy()  # P_bus = U.e - W.l, one load per customer bus so W = I
    Q_fix = -TAN_PHI * LOAD_MW
    return path.astype(float), down.astype(float), U, P_fix, Q_fix


def sensitivities():
    """(S_P, S_Q) of the toy, and S = S_P.U in envelope space."""
    path, _, U, _, _ = feeder()
    S_P, S_Q = ec.lindistflow(path, np.full(N_BRANCHES, RHO), np.full(N_BRANCHES, CHI))
    return S_P, S_Q, S_P @ U


def structured_affine(c=V_SOURCE):
    """The toy's exact structured corner model, via the builder under test's reference path."""
    path, _, U, P_fix, Q_fix = feeder()
    return lp.affine_from_structured(
        c, path, np.full(N_BRANCHES, RHO), np.full(N_BRANCHES, CHI), U, P_fix, Q_fix
    )


def corner_injection(e):
    """P_bus at the all-at-limit corner of [0, e]."""
    _, _, U, P_fix, _ = feeder()
    return U @ np.asarray(e, dtype=float) + P_fix


# --- A. the affine corner builders ---------------------------------------------------------


def test_affine_from_structured_matches_envelope_core_structured_predict():
    """The builder is `structured_predict` evaluated at the corner, for every random e."""
    path, _, U, P_fix, Q_fix = feeder()
    rho = np.full(N_BRANCHES, RHO)
    chi = np.full(N_BRANCHES, CHI)
    c = V_SOURCE + np.array([0.0, 0.001, -0.002, 0.003])  # a per-bus intercept
    alpha, S = lp.affine_from_structured(c, path, rho, chi, U, P_fix, Q_fix)
    assert alpha.shape == (K_BUSES,)
    assert S.shape == (K_BUSES, N_UNITS)

    rng = np.random.default_rng(11)
    for _ in range(8):
        e = rng.uniform(0.0, RATING)
        expected = ec.structured_predict(c, path, rho, chi, corner_injection(e), Q_fix)
        np.testing.assert_allclose(alpha + S @ e, expected, rtol=0, atol=1e-13)


def test_affine_from_structured_slope_block_is_the_lindistflow_sensitivity():
    """S = path.diag(rho).down.U is exactly S_P.U, the dense LinDistFlow route."""
    _, S = structured_affine()
    _, _, S_expected = sensitivities()
    np.testing.assert_allclose(S, S_expected, rtol=0, atol=1e-14)
    assert np.all(S >= 0.0)  # radial feeder: every corner sensitivity is non-negative


def test_affine_from_slopes_matches_direct_slope_prediction():
    """alpha + S.e equals c + B'.P_bus(e) for a regression-shaped B (p x K)."""
    _, _, U, P_fix, _ = feeder()
    S_P, _, _ = sensitivities()
    B = S_P  # symmetric, so the p x K convention is unambiguous here
    c = np.array([1.000, 0.999, 0.998, 1.001])
    alpha, S = lp.affine_from_slopes(c, B, U, P_fix)

    rng = np.random.default_rng(12)
    for _ in range(8):
        e = rng.uniform(0.0, RATING)
        np.testing.assert_allclose(alpha + S @ e, c + B.T @ corner_injection(e), rtol=0, atol=1e-13)


def test_affine_from_centred_matches_the_centred_form_and_the_slope_builder():
    """ybar + beta'(P_bus - mu) is the same affine model as c = ybar - mu'B."""
    _, _, U, P_fix, _ = feeder()
    S_P, _, _ = sensitivities()
    B = S_P
    mu = -0.8 * LOAD_MW  # a plausible training-mean injection
    ybar = np.array([1.000, 0.996, 0.994, 0.997])
    alpha, S = lp.affine_from_centred(ybar, B, mu, U, P_fix)

    alpha_slopes, S_slopes = lp.affine_from_slopes(ybar - mu @ B, B, U, P_fix)
    np.testing.assert_allclose(alpha, alpha_slopes, rtol=0, atol=1e-13)
    np.testing.assert_allclose(S, S_slopes, rtol=0, atol=1e-14)

    rng = np.random.default_rng(13)
    for _ in range(8):
        e = rng.uniform(0.0, RATING)
        expected = ybar + B.T @ (corner_injection(e) - mu)
        np.testing.assert_allclose(alpha + S @ e, expected, rtol=0, atol=1e-13)


def test_affine_at_state_reproduces_the_state_it_was_built_at():
    """The oracle's re-linearisation is exact at its own state and keeps the true slopes."""
    _, _, S_true = sensitivities()
    e_state = np.array([0.010, 0.020, 0.030])
    v_state = np.array([1.050, 1.060, 1.075, 1.055])
    alpha, S = lp.affine_at_state(v_state, S_true, e_state)
    np.testing.assert_allclose(alpha + S @ e_state, v_state, rtol=0, atol=1e-14)
    np.testing.assert_allclose(S, S_true, rtol=0, atol=1e-14)


# --- B. the primary decision LP ------------------------------------------------------------


def test_voltage_envelope_optimum_matches_a_brute_force_grid_on_two_units():
    """On a 2-unit case the stage-1 optimum equals the best point of a fine grid.

    The LP optimum can only be at least the grid's best (the grid is a subset of the
    feasible set) and at most one grid step above it, which brackets it exactly.
    """
    alpha, S = structured_affine()
    S2 = S[:, :2]
    a2 = np.array([0.030, 0.040])
    vmax = np.full(K_BUSES, V_MAX)
    out = lp.voltage_envelope(alpha, S2, vmax, 0.0, a2)
    assert out["status"] == lp.OK

    n_grid = 201
    g1 = np.linspace(0.0, a2[0], n_grid)
    g2 = np.linspace(0.0, a2[1], n_grid)
    E1, E2 = np.meshgrid(g1, g2, indexing="ij")
    grid = np.stack([E1.ravel(), E2.ravel()], axis=1)
    v = alpha[None, :] + grid @ S2.T
    feasible = np.all(v <= vmax[None, :] + 1e-12, axis=1)
    assert feasible.any()
    best = float(grid[feasible].sum(axis=1).max())
    step = float(max(a2[0] / (n_grid - 1), a2[1] / (n_grid - 1)))

    assert out["total"] >= best - 1e-12
    assert out["total"] <= best + 2.0 * step
    np.testing.assert_array_less(alpha + S2 @ out["e"], vmax + 1e-9)


def test_voltage_envelope_optimum_matches_a_plain_linprog_without_stage_two():
    """Stage 2 never changes sum(e): it only reallocates it."""
    from scipy import optimize

    alpha, S = structured_affine()
    a = RATING.copy()
    vmax = np.full(K_BUSES, V_MAX)
    out = lp.voltage_envelope(alpha, S, vmax, 0.0, a)

    reference = optimize.linprog(
        -np.ones(N_UNITS),
        A_ub=S,
        b_ub=vmax - alpha,
        bounds=[(0.0, float(x)) for x in a],
        method="highs",
    )
    assert reference.success
    assert out["total"] == pytest.approx(float(np.sum(reference.x)), abs=1e-9)


def test_voltage_envelope_stage_two_returns_the_proportional_allocation_in_a_tie():
    """One aggregate row on sum(e) leaves every optimum tied; stage 2 picks e = theta_bar.a.

    This is a pure-LP fixture (a single synthetic row), not a voltage model.
    """
    a = np.array([0.020, 0.010, 0.030])
    S = np.ones((1, N_UNITS))
    headroom = 0.030
    out = lp.voltage_envelope(np.zeros(1), S, np.array([headroom]), 0.0, a)

    assert out["status"] == lp.OK
    assert out["total"] == pytest.approx(headroom, abs=1e-9)
    theta_bar = headroom / float(a.sum())
    assert theta_bar == pytest.approx(0.5, abs=1e-12)
    np.testing.assert_allclose(out["e"], theta_bar * a, rtol=0, atol=1e-9)
    assert out["active_v"].tolist() == [0]


def test_voltage_envelope_flags_the_infeasible_case_instead_of_returning_zero():
    """alpha above the limit at e = 0 with S >= 0 cannot be fixed by curtailment."""
    alpha, S = structured_affine()
    alpha = alpha.copy()
    alpha[2] = V_MAX + 0.01
    out = lp.voltage_envelope(alpha, S, np.full(K_BUSES, V_MAX), 0.0, RATING)

    assert out["status"] == lp.INFEASIBLE
    np.testing.assert_allclose(out["e"], np.zeros(N_UNITS), rtol=0, atol=0)
    assert out["total"] == 0.0
    assert out["active_v"].size == 0
    assert out["active_extra"].size == 0


def test_voltage_envelope_active_v_names_the_binding_bus():
    """With every other bus given an unreachable limit, only bus 2 can bind."""
    alpha, S = structured_affine()
    vmax = np.array([10.0, 10.0, V_MAX, 10.0])
    a = np.full(N_UNITS, 0.050)
    out = lp.voltage_envelope(alpha, S, vmax, 0.0, a)

    assert out["status"] == lp.OK
    assert out["active_v"].tolist() == [2]
    slack = (vmax - alpha) - S @ out["e"]
    assert slack[2] == pytest.approx(0.0, abs=1e-9)
    assert np.all(slack[[0, 1, 3]] > 1.0)
    assert out["total"] < float(a.sum())  # the row, not the box, is what limits the export


def test_voltage_envelope_respects_a_zero_availability_unit():
    """A unit with a_i <= 1e-12 is pinned at 0 and left out of stage 2's objective."""
    alpha, S = structured_affine()
    a = np.array([0.030, 0.0, 0.050])
    out = lp.voltage_envelope(alpha, S, np.full(K_BUSES, V_MAX), 0.0, a)
    assert out["status"] == lp.OK
    assert out["e"][1] == 0.0
    assert 0.0 <= out["stage2_l1_move"] < 10.0


def test_voltage_envelope_extra_rows_can_bind_and_are_reported_separately():
    """Control T's thermal rows enter as A_extra and show up in `active_extra`."""
    alpha, S = structured_affine()
    _, down, U, P_fix, _ = feeder()
    caps = np.array([0.040, 1.0, 1.0, 1.0])  # a tight transformer, slack lines
    A_extra, b_extra = lp.thermal_rows(down, U, P_fix, caps)
    out = lp.voltage_envelope(
        alpha, S, np.full(K_BUSES, V_MAX), 0.0, RATING, A_extra=A_extra, b_extra=b_extra
    )
    assert out["status"] == lp.OK
    assert out["active_extra"].size >= 1
    flow = down @ (U @ out["e"] + P_fix)
    np.testing.assert_array_less(np.abs(flow), lp.KAPPA_T * caps + 1e-9)


# --- C. the proportional-fair closed form --------------------------------------------------


def test_proportional_envelope_matches_the_closed_form():
    alpha, S = structured_affine()
    a = np.full(N_UNITS, 0.050)
    vmax = np.full(K_BUSES, V_MAX)
    out = lp.proportional_envelope(alpha, S, vmax, 0.0, a)

    headroom = vmax - alpha
    load = S @ a
    ratios = headroom[load > 0.0] / load[load > 0.0]
    theta_expected = min(1.0, float(ratios.min()))
    assert out["theta"] == pytest.approx(theta_expected, abs=1e-12)
    assert out["binding"] == int(np.argmin(headroom / load))
    np.testing.assert_allclose(out["e"], out["theta"] * a, rtol=0, atol=1e-15)
    assert out["total"] == pytest.approx(out["theta"] * float(a.sum()), abs=1e-15)
    assert out["status"] == lp.OK


def test_proportional_envelope_clips_at_one_when_nothing_binds():
    alpha, S = structured_affine()
    out = lp.proportional_envelope(alpha, S, np.full(K_BUSES, 10.0), 0.0, RATING)
    assert out["theta"] == 1.0
    assert out["binding"] == -1
    np.testing.assert_allclose(out["e"], RATING, rtol=0, atol=0)


def test_proportional_envelope_flags_a_bus_that_curtailment_cannot_fix():
    """A bus already above its limit with (S.a)_k <= 0 forces theta = 0, flagged."""
    alpha = np.array([V_MAX + 0.01, 1.0])
    S = np.array([[0.0, 0.0, 0.0], [RHO, RHO, RHO]])
    out = lp.proportional_envelope(alpha, S, np.full(2, V_MAX), 0.0, RATING)
    assert out["status"] == lp.INFEASIBLE
    assert out["theta"] == 0.0
    assert out["binding"] == 0
    assert out["negative_headroom"].tolist() == [0]
    np.testing.assert_allclose(out["e"], np.zeros(N_UNITS), rtol=0, atol=0)


def test_proportional_envelope_flags_a_negative_headroom_even_when_the_row_is_sensitive():
    """theta = 0 is forced either way, so e = 0 must never come back as `ok`: at a bus
    already above its limit, e = 0 does not satisfy the row."""
    alpha = np.array([V_MAX + 0.01, 1.0])
    S = np.array([[RHO, RHO, RHO], [RHO, RHO, RHO]])  # (S.a)_0 > 0, unlike the case above
    out = lp.proportional_envelope(alpha, S, np.full(2, V_MAX), 0.0, RATING)
    assert out["theta"] == 0.0
    assert out["status"] == lp.INFEASIBLE
    assert out["negative_headroom"].tolist() == [0]
    assert out["binding"] == 0


# --- D. the thermal module -----------------------------------------------------------------


def test_thermal_rows_single_branch_both_directions():
    """One branch, a known cap: the export row and the import row are exactly kappa.cap."""
    _, _, U, P_fix, _ = feeder()
    down = np.ones((1, K_BUSES))  # the transformer: everything is downstream of it
    cap = 0.200
    A, b = lp.thermal_rows(down, U, P_fix, np.array([cap]))

    base = float(P_fix.sum())  # -0.060 MW: the feeder's load at e = 0
    assert base == pytest.approx(-0.060, abs=1e-15)
    np.testing.assert_allclose(A, np.array([[1.0, 1.0, 1.0], [-1.0, -1.0, -1.0]]), atol=1e-15)
    np.testing.assert_allclose(b, [lp.KAPPA_T * cap - base, lp.KAPPA_T * cap + base], atol=1e-15)

    # export direction: the row is tight exactly where the flow reaches +kappa.cap.
    e_export = np.full(N_UNITS, b[0] / N_UNITS)
    flow = float((down @ (U @ e_export + P_fix))[0])
    assert flow == pytest.approx(lp.KAPPA_T * cap, abs=1e-12)
    assert float(A[0] @ e_export) == pytest.approx(b[0], abs=1e-12)

    # import direction: at e = 0 the flow is -0.060 MW, inside the cap, with the slack below.
    flow0 = float((down @ (U @ np.zeros(N_UNITS) + P_fix))[0])
    assert flow0 == pytest.approx(base, abs=1e-15)
    assert float(b[1] - A[1] @ np.zeros(N_UNITS)) == pytest.approx(
        lp.KAPPA_T * cap - abs(base), abs=1e-15
    )

    # and the import row does bind once the cap is below the load.
    _, b_tight = lp.thermal_rows(down, U, P_fix, np.array([abs(base) / lp.KAPPA_T]))
    assert b_tight[1] == pytest.approx(0.0, abs=1e-15)


def test_thermal_rows_rejects_a_mismatched_cap_vector():
    _, down, U, P_fix, _ = feeder()
    with pytest.raises(ValueError, match="caps"):
        lp.thermal_rows(down, U, P_fix, np.array([1.0]))


# --- E. the robust box (B4box) -------------------------------------------------------------


def box_inputs():
    """(ybar, B, mu, U, P_fix, vmax) whose centred model is the toy's exact structured one."""
    _, _, U, P_fix, _ = feeder()
    S_P, _, _ = sensitivities()
    B = S_P
    mu = -0.8 * LOAD_MW
    ybar = V_SOURCE + S_P @ mu
    return ybar, B, mu, U, P_fix, np.full(K_BUSES, V_MAX)


def test_box_worst_case_equals_brute_force_subset_enumeration():
    """Gamma = 2 of 4 coefficients, against every admissible subset."""
    rng = np.random.default_rng(21)
    for _ in range(20):
        x = rng.normal(0.0, 0.05, size=4)
        sd_k = rng.uniform(0.0, 0.5, size=4)
        terms = 3.0 * sd_k * np.abs(x)
        brute = max(
            sum(terms[list(subset)])
            for size in range(3)
            for subset in itertools.combinations(range(4), size)
        )
        assert lp.box_worst_case(x, sd_k, 2, k_sigma=3.0) == pytest.approx(brute, abs=1e-14)

    # the degenerate budgets, for completeness
    x = np.array([0.01, -0.02, 0.03, -0.04])
    sd_k = np.full(4, 0.1)
    assert lp.box_worst_case(x, sd_k, 0) == 0.0
    assert lp.box_worst_case(x, sd_k, 9) == pytest.approx(
        float(np.sum(3.0 * sd_k * np.abs(x))), abs=1e-14
    )


def test_box_envelope_robust_row_holds_and_is_tight_at_the_binding_bus():
    ybar, B, mu, U, P_fix, vmax = box_inputs()
    sd = np.full((K_BUSES, K_BUSES), 0.02)
    a = np.full(N_UNITS, 0.050)
    out = lp.box_envelope(ybar, B, sd, mu, U, P_fix, vmax, a, gamma=2, k_sigma=3.0)

    assert out["status"] == lp.OK
    x = U @ out["e"] + P_fix - mu
    nominal = ybar + B.T @ x
    worst = np.array([lp.box_worst_case(x, sd[k], 2, 3.0) for k in range(K_BUSES)])
    np.testing.assert_allclose(worst, out["worst_case"], rtol=0, atol=1e-14)
    np.testing.assert_array_less(nominal + worst, vmax + 1e-7)  # the robust row holds

    gap = nominal + worst - vmax
    assert float(gap.max()) == pytest.approx(0.0, abs=1e-7)  # tight at the binding bus
    assert out["active_v"].size >= 1
    assert int(np.argmax(gap)) in out["active_v"].tolist()

    # robustness costs export: the nominal envelope is strictly larger.
    alpha_nom, S_nom = lp.affine_from_centred(ybar, B, mu, U, P_fix)
    nominal_out = lp.voltage_envelope(alpha_nom, S_nom, vmax, 0.0, a)
    assert out["total"] < nominal_out["total"]


def chain_feeder(n_buses, n_units):
    """A synthetic radial chain of `n_buses` customer buses, with PV on the last `n_units`.

    This is a scale fixture, not a network: it only has to be a valid radial tree with
    non-negative sensitivities and an export-dominated condition, so the sparse robust
    programs can be exercised at the protocol's K = 118. Its branches carry r = 0.01 ohm on
    the same 0.4 kV base (rho = 0.0625), another round value chosen here, because a chain of
    118 branches at 0.1 ohm would be far too stiff for the upper limit ever to bind.
    """
    parent = np.array([-1] + list(range(n_buses - 1)))
    child = np.arange(n_buses)
    path, down = ec.tree_matrices(parent, child, n_buses)
    path_f = path.astype(float)
    rho = np.full(n_buses, 0.01 / V_BASE_KV**2)
    S_P, _ = ec.lindistflow(path_f, rho, np.full(n_buses, 0.005 / V_BASE_KV**2))
    U = np.zeros((n_buses, n_units))
    U[np.arange(n_buses - n_units, n_buses), np.arange(n_units)] = 1.0
    load = np.full(n_buses, 0.0002)
    return path_f, down.astype(float), U, -load, S_P


def test_box_envelope_is_sparse_enough_for_the_protocol_scale():
    """K = 118 gives about 14,000 p-variables (protocol s. 7); the sparse dual must solve."""
    n_buses, n_units = 118, 27
    _, _, U, P_fix, S_P = chain_feeder(n_buses, n_units)
    B = S_P
    mu = 0.8 * P_fix
    ybar = V_SOURCE + S_P @ mu
    vmax = np.full(n_buses, V_MAX)
    a = np.full(n_units, 0.004)
    gamma = math.ceil(math.sqrt(n_buses))
    sd = np.full((n_buses, n_buses), 0.01)

    out = lp.box_envelope(ybar, B, sd, mu, U, P_fix, vmax, a, gamma=gamma, k_sigma=3.0)
    assert out["status"] == lp.OK
    x = U @ out["e"] + P_fix - mu
    worst = np.array([lp.box_worst_case(x, sd[k], gamma, 3.0) for k in range(n_buses)])
    np.testing.assert_array_less(ybar + B.T @ x + worst, vmax + 1e-6)


def scale_ellipsoid(r2_value, **kwargs):
    """The K = 118 chain with a common radius, for the budget tests below."""
    n_buses, n_units = 118, 27
    _, _, U, P_fix, S_P = chain_feeder(n_buses, n_units)
    mu = 0.8 * P_fix
    M = np.eye(n_buses) * 0.004 + np.full((n_buses, n_buses), 0.001)
    return lp.ellipsoid_envelope(
        V_SOURCE + S_P @ mu,
        S_P,
        np.linalg.inv(M),
        np.full(n_buses, r2_value),
        mu,
        U,
        P_fix,
        np.full(n_buses, V_MAX),
        np.full(n_units, 0.004),
        **kwargs,
    )


def test_ellipsoid_envelope_is_sparse_enough_for_the_protocol_scale():
    """At K = 118 a small radius converges inside the 60-round budget (revision 2.2)."""
    out = scale_ellipsoid(1e-6)
    assert out["status"] == lp.OK
    assert out["restored"] is False
    assert 0 < out["n_cuts"]
    assert 0 < out["n_rounds"] <= lp.MAX_ROUNDS
    assert out["max_g"] <= lp.CUT_TOL + 1e-12
    assert out["total"] > 0.0


def test_ellipsoid_budget_restores_instead_of_declaring_degenerate_at_the_protocol_scale():
    """Revision 2.2: at K = 118 with r^2 = 1e-3 the cuts do not converge inside 60 rounds.

    Revision 2's row-counting budget returned `robust-degenerate` here on the budget alone,
    which would have fed H3's rejection branch on a numerical artefact (drafting record,
    revision 2.2). The budget now ends in a uniform restoration: a usable, robust-feasible
    envelope with a reported optimality gap.
    """
    out = scale_ellipsoid(1e-3)
    assert out["status"] == lp.OK
    assert out["restored"] is True
    assert out["reason"] == "max_rounds"
    assert out["n_rounds"] == lp.MAX_ROUNDS
    assert out["max_g"] <= lp.CUT_TOL  # robust-feasible after restoration
    assert out["gap"] <= lp.GAP_FLAG_TOL
    assert out["gap_flag"] is False
    assert out["total"] > lp.DEGENERATE_SHARE * 27 * 0.004
    assert out["stage2_l1_move"] == 0.0  # stage 2 is skipped for a restored envelope


def test_ellipsoid_a_small_round_cap_triggers_restoration():
    """A forced cap of 1 round stops before convergence, so the envelope is restored."""
    out = scale_ellipsoid(1e-6, max_rounds=1)
    assert out["n_rounds"] == 1
    assert out["restored"] is True
    assert out["reason"] == "max_rounds"
    assert out["status"] == lp.OK
    assert out["max_g"] <= lp.CUT_TOL
    assert out["gap"] > 0.0  # one round cannot reach the cut LP's upper bound


def test_ellipsoid_envelope_is_degenerate_when_e_zero_is_not_robust_feasible():
    """g(0) > tol: even no export is outside the data-consistent set's safe region."""
    ybar, B, Minv, r2, mu, U, P_fix, vmax = ellipsoid_inputs()
    tight = ybar - 0.5 * (vmax - ybar)  # pull vmax below the robust value already at e = 0
    out = lp.ellipsoid_envelope(ybar, B, Minv, r2, mu, U, P_fix, tight, np.full(N_UNITS, 0.050))
    assert out["status"] == lp.ROBUST_DEGENERATE
    assert out["reason"] == "g_zero"
    assert out["n_rounds"] == 0 and out["n_cuts"] == 0
    assert out["max_g"] > lp.CUT_TOL
    assert out["restored"] is False


def test_box_envelope_with_gamma_zero_equals_the_nominal_envelope():
    ybar, B, mu, U, P_fix, vmax = box_inputs()
    sd = np.full((K_BUSES, K_BUSES), 0.02)
    a = np.full(N_UNITS, 0.050)
    out = lp.box_envelope(ybar, B, sd, mu, U, P_fix, vmax, a, gamma=0, k_sigma=3.0)

    alpha_nom, S_nom = lp.affine_from_centred(ybar, B, mu, U, P_fix)
    nominal = lp.voltage_envelope(alpha_nom, S_nom, vmax, 0.0, a)
    assert out["status"] == lp.OK
    assert out["total"] == pytest.approx(nominal["total"], abs=1e-9)
    np.testing.assert_allclose(out["e"], nominal["e"], rtol=0, atol=1e-7)


def test_box_envelope_with_a_huge_sd_is_robust_degenerate():
    ybar, B, mu, U, P_fix, vmax = box_inputs()
    sd = np.full((K_BUSES, K_BUSES), 50.0)  # a coefficient sd far above the coefficients
    out = lp.box_envelope(
        ybar, B, sd, mu, U, P_fix, vmax, np.full(N_UNITS, 0.050), gamma=2, k_sigma=3.0
    )
    assert out["status"] == lp.ROBUST_DEGENERATE
    assert out["total"] <= lp.DEGENERATE_SHARE * 3 * 0.050 + 1e-12


def test_box_envelope_rejects_a_mis_shaped_sd():
    ybar, B, mu, U, P_fix, vmax = box_inputs()
    with pytest.raises(ValueError, match="sd must be"):
        lp.box_envelope(ybar, B, np.full((K_BUSES, 2), 0.01), mu, U, P_fix, vmax, RATING, gamma=1)


# --- F. the robust ellipsoid (B4) ----------------------------------------------------------


def scalar_ellipsoid_case():
    """A 1-bus, 1-regressor, 1-PV-unit case whose robust envelope has a closed form.

    g(e) = ybar + beta.x + r.|x|.sqrt(Minv) - vmax with x = e + 0.010, so the root is found by
    bisection inside the test.
    """
    ybar = np.array([1.000])
    B = np.array([[RHO]])
    Minv = np.array([[4.0]])
    r2 = np.array([0.010])
    mu = np.array([-0.020])
    U = np.array([[1.0]])
    P_fix = np.array([-0.010])
    vmax = np.array([1.050])
    a = np.array([0.200])
    return ybar, B, Minv, r2, mu, U, P_fix, vmax, a


def test_ellipsoid_envelope_matches_the_analytical_single_unit_solution():
    ybar, B, Minv, r2, mu, U, P_fix, vmax, a = scalar_ellipsoid_case()
    out = lp.ellipsoid_envelope(ybar, B, Minv, r2, mu, U, P_fix, vmax, a)
    assert out["status"] == lp.OK

    r = math.sqrt(float(r2[0]))

    def g(e):
        x = float(U[0, 0] * e + P_fix[0] - mu[0])
        return (
            float(ybar[0])
            + float(B[0, 0]) * x
            + r * abs(x) * math.sqrt(float(Minv[0, 0]))
            - (float(vmax[0]))
        )

    assert g(0.0) < 0.0 and g(float(a[0])) > 0.0
    lo, hi = 0.0, float(a[0])
    for _ in range(200):
        mid = lp.bisection_backoff(lo, hi)
        if g(mid) <= 0.0:
            lo = mid
        else:
            hi = mid
    assert out["total"] == pytest.approx(lo, abs=1e-8)
    assert out["max_g"] <= lp.CUT_TOL + 1e-12
    assert out["n_cuts"] >= 1


def ellipsoid_inputs(r2_scale=1.0):
    """The 4-bus toy with a positive-definite metric of our own choosing."""
    ybar, B, mu, U, P_fix, vmax = box_inputs()
    M = np.eye(K_BUSES) * 0.004 + np.full((K_BUSES, K_BUSES), 0.001)
    Minv = np.linalg.inv(M)
    r2 = np.full(K_BUSES, 1.5e-4) * r2_scale
    return ybar, B, Minv, r2, mu, U, P_fix, vmax


def test_ellipsoid_envelope_converges_below_the_cut_tolerance():
    ybar, B, Minv, r2, mu, U, P_fix, vmax = ellipsoid_inputs()
    a = np.full(N_UNITS, 0.050)
    out = lp.ellipsoid_envelope(ybar, B, Minv, r2, mu, U, P_fix, vmax, a)

    assert out["status"] == lp.OK
    assert out["max_g"] <= lp.CUT_TOL + 1e-12
    assert 0 < out["n_cuts"]
    assert 0 < out["n_rounds"] <= lp.MAX_ROUNDS
    assert out["restored"] is False and out["gap"] == 0.0

    # the robust constraint really holds at the returned envelope
    x = U @ out["e"] + P_fix - mu
    norm = math.sqrt(float(x @ (Minv @ x)))
    g = ybar + B.T @ x + np.sqrt(r2) * norm - vmax
    assert float(g.max()) <= lp.CUT_TOL + 1e-12

    alpha_nom, S_nom = lp.affine_from_centred(ybar, B, mu, U, P_fix)
    assert out["total"] < lp.voltage_envelope(alpha_nom, S_nom, vmax, 0.0, a)["total"]


def test_ellipsoid_envelope_with_zero_radius_reproduces_the_nominal_envelope():
    ybar, B, Minv, _, mu, U, P_fix, vmax = ellipsoid_inputs()
    a = np.full(N_UNITS, 0.050)
    out = lp.ellipsoid_envelope(ybar, B, Minv, np.zeros(K_BUSES), mu, U, P_fix, vmax, a)

    alpha_nom, S_nom = lp.affine_from_centred(ybar, B, mu, U, P_fix)
    nominal = lp.voltage_envelope(alpha_nom, S_nom, vmax, 0.0, a)
    assert out["status"] == lp.OK
    assert out["n_cuts"] == 0
    assert out["total"] == pytest.approx(nominal["total"], abs=1e-9)
    np.testing.assert_allclose(out["e"], nominal["e"], rtol=0, atol=1e-8)


def test_ellipsoid_envelope_with_a_huge_radius_is_robust_degenerate():
    ybar, B, Minv, _, mu, U, P_fix, vmax = ellipsoid_inputs()
    a = np.full(N_UNITS, 0.050)
    out = lp.ellipsoid_envelope(ybar, B, Minv, np.full(K_BUSES, 1.0e4), mu, U, P_fix, vmax, a)
    assert out["status"] == lp.ROBUST_DEGENERATE
    assert out["total"] <= lp.DEGENERATE_SHARE * float(a.sum()) + 1e-12
    assert out["reason"] in {"low_total", "g_zero", lp.INFEASIBLE}


# --- G. monotonicity over the box (protocol s. 6) ------------------------------------------


def test_linear_voltage_at_interior_points_never_exceeds_the_corner():
    """With S >= 0 the corner is the worst point of [0, e] in the linear model."""
    alpha, S = structured_affine()
    assert np.all(S >= 0.0)
    out = lp.voltage_envelope(alpha, S, np.full(K_BUSES, V_MAX), 0.0, np.full(N_UNITS, 0.050))
    e = out["e"]
    v_corner = alpha + S @ e

    rng = ec.rng_for("toy5", "P1", "interior_point", 0)
    for _ in range(50):
        e_in = lp.interior_point(rng, e)
        assert np.all(e_in >= -1e-15) and np.all(e_in <= e + 1e-15)
        np.testing.assert_array_less(alpha + S @ e_in, v_corner + 1e-15)


# --- H. the reliability rule and its controls ----------------------------------------------


def test_cert_choice_acts_when_the_alternatives_agree():
    e_b2 = np.array([0.010, 0.020, 0.030])
    alts = np.array(
        [
            [0.0101, 0.0199, 0.0300],
            [0.0100, 0.0202, 0.0298],
            [0.0099, 0.0200, 0.0301],
            [0.0102, 0.0198, 0.0300],
        ]
    )
    out = lp.cert_choice(e_b2, alts)
    assert out["act"] is True
    totals = alts.sum(axis=1)
    assert out["spread"] == pytest.approx(
        float(totals.max() - totals.min()) / float(e_b2.sum()), abs=1e-15
    )
    np.testing.assert_allclose(
        out["l1"], np.abs(alts - e_b2).sum(axis=1) / float(e_b2.sum()), rtol=0, atol=1e-15
    )
    assert out["l1"].max() <= 0.10


def test_cert_choice_falls_back_on_a_disagreeing_alternative():
    e_b2 = np.array([0.010, 0.020, 0.030])
    alts = np.array(
        [
            [0.010, 0.020, 0.030],
            [0.010, 0.020, 0.030],
            [0.010, 0.020, 0.030],
            [0.030, 0.000, 0.045],  # a 50 % larger total and a quite different allocation
        ]
    )
    out = lp.cert_choice(e_b2, alts)
    assert out["act"] is False
    assert out["spread"] > 0.10
    assert out["l1"].max() > 0.10


def test_cert_choice_falls_back_on_an_allocation_only_disagreement():
    """Equal totals, different allocation: the L1 test alone must trigger the fallback."""
    e_b2 = np.array([0.010, 0.020, 0.030])
    alts = np.tile(e_b2, (4, 1))
    alts[0] = np.array([0.030, 0.020, 0.010])
    out = lp.cert_choice(e_b2, alts)
    assert out["spread"] == pytest.approx(0.0, abs=1e-15)
    assert out["l1"].max() > 0.10
    assert out["act"] is False


def test_cert_choice_cannot_act_on_a_zero_envelope_or_an_empty_set():
    zero = lp.cert_choice(np.zeros(3), np.zeros((4, 3)))
    assert zero["act"] is False
    assert math.isinf(zero["spread"])
    empty = lp.cert_choice(np.array([0.01, 0.02, 0.03]), np.zeros((0, 3)))
    assert empty["act"] is False
    assert empty["l1"].size == 0


def test_rand_fallback_draws_exactly_k_of_n_and_is_deterministic():
    for k in (0, 1, 4, 10):
        mask = lp.rand_fallback(np.random.default_rng(7), 10, k)
        assert mask.dtype == bool
        assert mask.shape == (10,)
        assert int(mask.sum()) == k

    first = lp.rand_fallback(ec.rng_for("toy5", "P1", "rand_fallback", 0), 10, 4)
    second = lp.rand_fallback(ec.rng_for("toy5", "P1", "rand_fallback", 0), 10, 4)
    np.testing.assert_array_equal(first, second)
    other = lp.rand_fallback(ec.rng_for("toy5", "P3", "rand_fallback", 0), 10, 4)
    assert other.shape == first.shape  # a different stream, same exact count
    assert int(other.sum()) == 4

    with pytest.raises(ValueError, match="0 <= k <= n"):
        lp.rand_fallback(np.random.default_rng(0), 5, 6)


def test_ambiguity_measures_reports_spread_allocation_and_disagreement():
    alts = np.array([[0.010, 0.020, 0.030], [0.020, 0.010, 0.030], [0.005, 0.005, 0.005]])
    totals = alts.sum(axis=1)
    out = lp.ambiguity_measures(totals, alts, oracle_total=0.060, alt_safe=[True, False, True])
    assert out["export_spread"] == pytest.approx((0.060 - 0.015) / 0.060, abs=1e-15)
    pairwise = max(
        float(np.abs(alts[i] - alts[j]).sum()) for i, j in itertools.combinations(range(3), 2)
    )
    assert out["allocation_spread"] == pytest.approx(pairwise, abs=1e-15)
    assert out["safety_disagreement"] is True

    agree = lp.ambiguity_measures(totals, alts, 0.060, [True, True, True])
    assert agree["safety_disagreement"] is False
    assert math.isinf(lp.ambiguity_measures(totals, alts, 0.0, [True, False])["export_spread"])


def test_interior_point_lies_in_the_box_and_is_seeded():
    e = np.array([0.010, 0.0, 0.030])
    first = lp.interior_point(ec.rng_for("toy5", "P1", "interior_point", 0), e)
    second = lp.interior_point(ec.rng_for("toy5", "P1", "interior_point", 0), e)
    np.testing.assert_array_equal(first, second)
    assert np.all(first >= 0.0) and np.all(first <= e)
    assert first[1] == 0.0


def test_bisection_backoff_is_the_midpoint():
    assert lp.bisection_backoff(0.0, 1.0) == 0.5
    assert lp.bisection_backoff(0.5, 1.0) == 0.75


# --- I. the oracle state machine -----------------------------------------------------------


def test_oracle_state_stops_when_feasible_and_the_total_has_settled():
    state = lp.OracleState()
    assert state.budget == 14
    assert state.next_action() == {"kind": "relinearise"}

    state.submit(np.array([0.010, 0.020, 0.030]), -0.002)
    assert not state.done  # one solve cannot show that sum(e) has settled
    assert state.next_action() == {"kind": "relinearise"}

    state.submit(np.array([0.010, 0.020, 0.0301]), -0.001)  # +0.17 %, inside 0.5 %
    assert state.done
    assert state.status == lp.OK
    assert state.solves == 2
    assert float(state.best_e.sum()) == pytest.approx(0.0601, abs=1e-12)
    assert state.next_action() == {"kind": "stop"}
    with pytest.raises(RuntimeError, match="stopped"):
        state.submit(np.zeros(3), -1.0)


def test_oracle_state_does_not_stop_on_a_feasible_but_still_moving_total():
    state = lp.OracleState()
    state.submit(np.array([0.010, 0.020, 0.030]), -0.002)
    state.submit(np.array([0.020, 0.020, 0.030]), -0.002)  # +17 %, far outside 0.5 %
    assert not state.done
    assert state.solves == 2


def test_oracle_state_switches_to_bisection_and_keeps_the_largest_feasible_factor():
    state = lp.OracleState()
    e_lp = np.array([0.010, 0.020, 0.030])
    for _ in range(6):
        assert state.next_action()["kind"] == "relinearise"
        state.submit(e_lp, +0.004)  # every sequential-LP step stays AC-infeasible
    assert state.phase == "bisect"
    assert state.solves == 6
    np.testing.assert_allclose(state.reference, e_lp, rtol=0, atol=0)

    action = state.next_action()
    assert action == {"kind": "scale", "factor": 0.5}
    state.submit(0.5 * e_lp, -0.001)  # 0.5 is AC-feasible
    assert state.lo == 0.5
    action = state.next_action()
    assert action["factor"] == pytest.approx(0.75, abs=1e-15)
    state.submit(0.75 * e_lp, +0.002)  # 0.75 is not
    assert state.hi == 0.75
    assert state.next_action()["factor"] == pytest.approx(0.625, abs=1e-15)
    np.testing.assert_allclose(state.best_e, 0.5 * e_lp, rtol=0, atol=1e-15)


def test_oracle_state_never_exceeds_the_budget_of_fourteen():
    """Every AC result infeasible: the machine must stop at 14 solves, not loop."""
    state = lp.OracleState()
    e_lp = np.array([0.010, 0.020, 0.030])
    guard = 0
    while not state.done and guard < 100:
        guard += 1
        action = state.next_action()
        if action["kind"] == "stop":
            break
        e = e_lp if action["kind"] == "relinearise" else action["factor"] * e_lp
        state.submit(e, +0.010)
    assert state.done
    assert state.solves == 14
    assert state.lp_steps == 6 and state.bisect_steps == 8
    assert state.status == "infeasible"
    assert float(np.asarray(state.best_e).sum()) == 0.0
    assert len(state.history) == 14


def test_oracle_state_with_no_lp_budget_falls_straight_through_to_bisection():
    state = lp.OracleState(max_lp=1, max_bisect=2)
    assert state.budget == 3
    state.submit(np.array([0.010, 0.020, 0.030]), +0.005)
    assert state.phase == "bisect"
    state.submit(np.array([0.005, 0.010, 0.015]), -0.001)
    state.submit(np.array([0.0075, 0.015, 0.0225]), -0.001)
    assert state.done
    assert state.solves == 3 <= state.budget
    assert state.status == lp.OK
    assert state.lo == pytest.approx(0.75, abs=1e-15)


# --- J. hygiene ----------------------------------------------------------------------------


@pytest.mark.parametrize("module", [ec, lp])
def test_no_power_flow_dependency_is_imported(module):
    """Protocol: these two modules run zero power flows.

    The check parses each module's own source, so it is independent of collection order: a
    session-wide `sys.modules` assertion would pass or fail depending on whether some other
    test file had already imported pandapower to build its fixture.
    """
    tree = ast.parse(Path(module.__file__).read_text())
    forbidden = ("pandapower", "simbench")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            assert root not in forbidden, f"{Path(module.__file__).name} imports {name}"


def test_protocol_hash_constants_pin_the_file_and_its_as_executed_text():
    """Task 2e re-pinned `PROTOCOL_SHA256` to the file as the board registered it: revision
    2.2 plus the dated amendments A1-A3. The as-executed text - the amendments replaced by
    "(none)" - must still hash to revision 2.2's own hash, which is what shows that nothing
    above the amendments changed. `check_protocol()` requires both."""
    assert ec.PROTOCOL_SHA256 == (
        "610d144dc3dbcb9835387f31ff5cdbd3a87d35d61db4dec832d10d8618b1f7fd"
    )
    assert ec.PROTOCOL_SHA256_EXECUTED == (
        "1848a27963fc67e134eb6dbe97bd96f1bc29e0e7ce4a8d76a68dc8134aa122b4"
    )
    assert lp.PROTOCOL_SHA256 == ec.PROTOCOL_SHA256
    assert ec.check_protocol() == ec.PROTOCOL_SHA256
    assert ec.executed_text_sha() == ec.PROTOCOL_SHA256_EXECUTED

    # the second check is the one that bites: the file hash alone would not notice an edit
    # above the amendments that is compensated for by one below them.
    with pytest.raises(ValueError, match="as-executed protocol sha256"):
        ec.check_protocol(expected_executed="0" * 64)


def test_executed_text_sha_replaces_the_amendment_body_on_a_synthetic_file(tmp_path):
    """`executed_text_sha` keeps the text up to and including the heading, then "(none)".

    Checked against the digest computed here from first principles, and shown to be blind to
    the amendments' body but not to a single character above it.
    """
    head = "# toy protocol\n\nrule one\n"
    path = tmp_path / "toy.md"
    path.write_text(head + ec.AMENDMENTS_HEADING + "\n\nA1 (dated) - something happened.\n")
    expected = hashlib.sha256(
        (head + ec.AMENDMENTS_HEADING + "\n(none)\n").encode("utf-8")
    ).hexdigest()
    assert ec.executed_text_sha(path) == expected

    longer = tmp_path / "toy_more_amendments.md"
    longer.write_text(head + ec.AMENDMENTS_HEADING + "\n\nA1, A2 and A3, at length.\n")
    assert ec.executed_text_sha(longer) == expected

    changed = tmp_path / "toy_changed_above.md"
    changed.write_text("# toy protocol\n\nrule two\n" + ec.AMENDMENTS_HEADING + "\n(none)\n")
    assert ec.executed_text_sha(changed) != expected

    missing = tmp_path / "no_amendments.md"
    missing.write_text(head)
    with pytest.raises(ValueError, match="starts 0 lines"):
        ec.executed_text_sha(missing)

    twice = tmp_path / "twice.md"
    twice.write_text(head + ec.AMENDMENTS_HEADING + "\n\n" + ec.AMENDMENTS_HEADING + "\n")
    with pytest.raises(ValueError, match="starts 2 lines"):
        ec.executed_text_sha(twice)
