"""Tests for the Mission 11 Stage A core (`envelope_core.py`).

**Zero power flows.** Neither pandapower nor simbench is imported, directly or indirectly;
one test asserts that. Every fixture is a genuinely synthetic radial toy whose answer is
known in closed form or by hand:

* a 5-bus feeder (a source busbar and 4 customer buses) with 4 branches, branch 0 being the
  transformer;
* r = 0.1 ohm and x = 0.05 ohm on every branch, on a 0.4 kV base, so that
  rho = r/V_nom^2 = 0.625 and chi = 0.3125 pu per MW, both round numbers of our own
  choosing;
* PV and load "profiles" are a half-sine daylight bump.

No SimBench or IEEE parameter value appears here (protocol s. 16).
"""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import envelope_core as ec  # noqa: E402

# --- the synthetic feeder ------------------------------------------------------------------

R_OHM = 0.1  # per branch, a round value chosen here
X_OHM = 0.05
V_BASE_KV = 0.4
RHO = R_OHM / V_BASE_KV**2  # 0.625 pu per MW
CHI = X_OHM / V_BASE_KV**2  # 0.3125 pu per Mvar

PARENT = np.array([-1, 0, 1, 0])  # 0 = transformer; 1 and 3 hang off it; 2 hangs off 1
CHILD_BUS = np.array([0, 1, 2, 3])  # every branch ends on a customer bus
N_BRANCHES = 4
N_BUSES = 4

EXPECTED_PATH = np.array(
    [
        [True, False, False, False],  # bus 0: the transformer only
        [True, True, False, False],  # bus 1
        [True, True, True, False],  # bus 2
        [True, False, False, True],  # bus 3
    ]
)
#  |path_i intersect path_j| by hand, used for S_P and S_Q
OVERLAP = np.array([[1, 1, 1, 1], [1, 2, 2, 1], [1, 2, 3, 1], [1, 1, 1, 2]], dtype=float)

NET = "toy5"  # a seed label, not a real network


def toy_path():
    return ec.tree_matrices(PARENT, CHILD_BUS, N_BRANCHES)[0]


def daylight_bump(n_days: int = 2, peak: float = 0.6) -> np.ndarray:
    """A positive half-sine daylight bump, one column, `n_days` x 96 steps."""
    t = np.arange(n_days * ec.STEPS_PER_DAY)
    phase = (t % ec.STEPS_PER_DAY) / ec.STEPS_PER_DAY
    bump = np.sin(np.pi * (phase - 0.25) / 0.5)
    return peak * np.where((phase > 0.25) & (phase < 0.75), bump, 0.0)


def excited_design(n_steps: int = 240, sigma: float = 1e-5, with_q: bool = False, seed: int = 7):
    """Voltages generated *exactly* from known LinDistFlow coefficients plus i.i.d. noise.

    The injections are independent and well excited, so the design is far from collinear.
    """
    path = toy_path()
    rho = np.full(N_BRANCHES, RHO)
    chi = np.full(N_BRANCHES, CHI)
    rng = np.random.default_rng(seed)
    p_bus = rng.normal(0.0, 0.01, size=(n_steps, N_BUSES))  # MW, export-positive
    q_bus = rng.normal(0.0, 0.004, size=(n_steps, N_BUSES)) if with_q else np.zeros_like(p_bus)
    truth = ec.structured_predict(1.0, path, rho, chi, p_bus, q_bus)
    noisy = truth + rng.normal(0.0, sigma, size=truth.shape)
    return path, rho, chi, p_bus, q_bus, noisy, truth


# --- the zero-flow rule --------------------------------------------------------------------


def test_no_power_flow_package_is_imported():
    """The core must not pull in a solver at all (protocol: zero flows here).

    The check parses the module's own source, so it is independent of collection order: a
    session-wide `sys.modules` assertion would pass or fail depending on whether some other
    test file had already imported pandapower to build its fixture.
    """
    tree = ast.parse(Path(ec.__file__).read_text())
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
            assert root not in forbidden, f"{Path(ec.__file__).name} imports {name}"


# --- A. seeds ------------------------------------------------------------------------------


def test_rng_for_is_deterministic_and_purpose_specific():
    first = ec.rng_for(NET, "P1", "pv_cloud").standard_normal(5)
    again = ec.rng_for(NET, "P1", "pv_cloud").standard_normal(5)
    other_purpose = ec.rng_for(NET, "P1", "load").standard_normal(5)
    other_regime = ec.rng_for(NET, "P2", "pv_cloud").standard_normal(5)
    other_replicate = ec.rng_for(NET, "P1", "pv_cloud", replicate=1).standard_normal(5)
    assert np.array_equal(first, again)
    for stream in (other_purpose, other_regime, other_replicate):
        assert not np.allclose(first, stream)


def test_rng_for_refuses_an_unknown_purpose():
    with pytest.raises(ValueError, match="unknown purpose"):
        ec.rng_for(NET, "P1", "whatever")


def test_load_seed_label_is_shared_across_regimes():
    """Protocol s. 13: the load process is identical in P1-P3 because it uses "common"."""
    assert ec.LOAD_REGIME == "common"
    a = ec.rng_for(NET, ec.LOAD_REGIME, "load").standard_normal(4)
    b = ec.rng_for(NET, ec.LOAD_REGIME, "load").standard_normal(4)
    assert np.array_equal(a, b)


# --- B. regime generators ------------------------------------------------------------------


def test_ar1_has_unit_variance_and_lag_one_autocorrelation_phi():
    """50,000 steps x 4 series; tolerances 0.05 on the variance and 0.03 on the lag-1 acf,
    both well above the Monte Carlo error of this length (about 0.01 and 0.006)."""
    eta = ec.ar1(ec.rng_for(NET, "P1", "pv_cloud"), 50_000, 4, ec.PHI_CLOUD)
    assert eta.shape == (50_000, 4)
    assert abs(eta.var() - 1.0) < 0.05
    acf = np.mean([np.corrcoef(eta[:-1, j], eta[1:, j])[0, 1] for j in range(4)])
    assert abs(acf - ec.PHI_CLOUD) < 0.03


def test_ar1_rejects_a_non_stationary_phi():
    with pytest.raises(ValueError, match="phi"):
        ec.ar1(ec.rng_for(NET, "P1", "pv_cloud"), 10, 1, 1.0)


def test_smooth_residual_is_an_exact_split():
    g = np.column_stack([daylight_bump(), daylight_bump(peak=0.3)])
    s, w = ec.smooth_residual(g)
    assert np.allclose(s + w, g, atol=0.0, rtol=0.0)
    assert np.std(s) < np.std(g) + 1e-12  # it is a smoother, not an amplifier


def test_shift_series_integer_shift_matches_roll_and_fractional_interpolates():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(20, 2))
    shifted = ec.shift_series(x, 2.0)
    assert np.allclose(shifted[:18], np.roll(x, -2, axis=0)[:18])
    half = ec.shift_series(x, 0.5)
    assert np.allclose(half[:19], 0.5 * (x[:19] + x[1:20]))
    assert np.allclose(ec.shift_series(x, 0.0), x)


def test_shift_series_clamps_the_ends():
    x = np.arange(5.0).reshape(5, 1)
    assert ec.shift_series(x, 3.0)[-1, 0] == 4.0  # clamped at the final value
    assert ec.shift_series(x, -3.0)[0, 0] == 0.0


def test_pv_regime_with_no_orientation_and_no_cloud_returns_the_native_profile():
    g = np.column_stack([daylight_bump(), daylight_bump(peak=0.5)])
    ratings = np.array([0.01, 0.02])
    native = ratings * np.minimum(1.0, g)
    train = np.arange(ec.STEPS_PER_DAY)
    a, info = ec.pv_regime(
        g,
        ratings,
        0.0,
        0.0,
        ec.rng_for(NET, "P1", "pv_orientation"),
        ec.rng_for(NET, "P1", "pv_cloud"),
        train,
        native,
    )
    assert np.allclose(info["delta_steps"], 0.0)
    assert np.allclose(info["k"], 1.0, atol=1e-12)
    assert np.allclose(a, native, atol=1e-12)


def test_pv_regime_leaves_the_weather_residual_at_wall_clock_time():
    """A dip in w must stay at its own step even when the smooth component is shifted."""
    base = daylight_bump()
    t0 = 60
    g = base.copy()
    g[t0] -= 0.2  # a one-step cloud
    g = g[:, None]
    ratings = np.array([0.01])
    native = ratings * np.minimum(1.0, g)
    train = np.arange(ec.STEPS_PER_DAY)
    a, info = ec.pv_regime(
        g,
        ratings,
        1.0,
        0.0,
        ec.rng_for(NET, "P3", "pv_orientation"),
        ec.rng_for(NET, "P3", "pv_cloud"),
        train,
        native,
    )
    delta = info["delta_steps"]
    assert abs(delta[0]) > 0.1  # the test is only meaningful for a real shift
    s, _ = ec.smooth_residual(g)
    residual = a[:, 0] / (info["k"][0] * ratings[0]) - ec.shift_series(s, delta)[:, 0]
    assert int(np.argmin(residual)) == t0


def test_pv_regime_matches_the_native_training_mean_and_respects_the_rating():
    g = np.column_stack([daylight_bump(), daylight_bump(peak=0.45), daylight_bump(peak=0.7)])
    ratings = np.array([0.01, 0.02, 0.005])
    native = ratings * np.minimum(1.0, g)
    train = np.arange(ec.STEPS_PER_DAY)
    a, info = ec.pv_regime(
        g,
        ratings,
        1.0,
        0.30,
        ec.rng_for(NET, "P3", "pv_orientation"),
        ec.rng_for(NET, "P3", "pv_cloud"),
        train,
        native,
    )
    assert np.allclose(info["train_mean_scaled"], info["train_mean_native"], rtol=1e-9, atol=0.0)
    assert np.all(a <= ratings + 1e-15)
    assert np.all(a >= 0.0)


def test_pv_regime_is_deterministic_for_fixed_seeds():
    g = np.column_stack([daylight_bump(), daylight_bump(peak=0.45)])
    ratings = np.array([0.01, 0.02])
    native = ratings * np.minimum(1.0, g)
    train = np.arange(ec.STEPS_PER_DAY)
    runs = [
        ec.pv_regime(
            g,
            ratings,
            *ec.REGIMES["P2"],
            ec.rng_for(NET, "P2", "pv_orientation"),
            ec.rng_for(NET, "P2", "pv_cloud"),
            train,
            native,
        )[0]
        for _ in range(2)
    ]
    assert np.array_equal(runs[0], runs[1])


def test_load_process_keeps_the_feeder_mean_and_the_power_factor():
    rng_base = np.random.default_rng(3)
    native_p = 0.002 + 0.001 * rng_base.random((480, 5))
    tan_phi_true = 0.3
    native_q = tan_phi_true * native_p
    ell, q, info = ec.load_process(native_p, native_q, ec.rng_for(NET, ec.LOAD_REGIME, "load"))

    # the renormalisation is exact by construction
    mean_p = native_p.mean(axis=0)
    assert np.isclose(np.sum(info["s"] * mean_p), np.sum(mean_p), rtol=1e-12)
    # the realised feeder mean is preserved in expectation only: 480 steps, sigma_L = 0.3
    assert np.isclose(ell.sum(axis=1).mean(), native_p.sum(axis=1).mean(), rtol=0.05)
    assert np.allclose(info["tan_phi"], tan_phi_true)
    assert np.allclose(q, ell * tan_phi_true)


def test_load_process_is_deterministic_and_handles_an_all_zero_load():
    native_p = np.column_stack([daylight_bump(), np.zeros(192)])
    native_q = 0.25 * native_p
    runs = [
        ec.load_process(native_p, native_q, ec.rng_for(NET, ec.LOAD_REGIME, "load"))
        for _ in range(2)
    ]
    assert np.array_equal(runs[0][0], runs[1][0])
    assert np.array_equal(runs[0][1], runs[1][1])
    assert runs[0][2]["tan_phi"][1] == 0.0  # 0/0 reads as a unity power factor


# --- C. network linear structure -----------------------------------------------------------


def test_tree_matrices_matches_the_hand_computed_paths():
    path, down = ec.tree_matrices(PARENT, CHILD_BUS, N_BRANCHES)
    assert np.array_equal(path, EXPECTED_PATH)
    assert np.array_equal(down, EXPECTED_PATH.T)
    assert np.all(path[:, 0])  # the transformer is on every path


def test_tree_matrices_rejects_a_broken_description():
    with pytest.raises(ValueError, match="root"):
        ec.tree_matrices(np.array([0, 0, 1, 0]), CHILD_BUS, N_BRANCHES)
    with pytest.raises(ValueError, match="exactly once"):
        ec.tree_matrices(PARENT, np.array([0, 1, 1, 3]), N_BRANCHES)
    with pytest.raises(ValueError, match="length n_branches"):
        ec.tree_matrices(PARENT, CHILD_BUS, 3)


def test_lindistflow_matches_the_hand_computed_path_sums():
    path = toy_path()
    s_p, s_q = ec.lindistflow(path, np.full(N_BRANCHES, RHO), np.full(N_BRANCHES, CHI))
    assert np.allclose(s_p, RHO * OVERLAP)
    assert np.allclose(s_q, CHI * OVERLAP)
    # a non-uniform feeder: buses 2 and 3 share only the transformer
    rho = np.array([0.4, 0.3, 0.2, 0.1])
    s_p2, _ = ec.lindistflow(path, rho, rho)
    assert np.isclose(s_p2[2, 3], rho[0])
    assert np.isclose(s_p2[2, 2], rho[0] + rho[1] + rho[2])


def test_structured_predict_agrees_with_the_sensitivity_matrices():
    path = toy_path()
    rho = np.array([0.4, 0.3, 0.2, 0.1])
    chi = 0.5 * rho
    s_p, s_q = ec.lindistflow(path, rho, chi)
    rng = np.random.default_rng(11)
    p_bus = rng.normal(0.0, 0.01, size=(7, N_BUSES))
    q_bus = rng.normal(0.0, 0.01, size=(7, N_BUSES))
    c = np.array([1.0, 1.01, 1.02, 1.03])
    expected = c + p_bus @ s_p.T + q_bus @ s_q.T
    assert np.allclose(ec.structured_predict(c, path, rho, chi, p_bus, q_bus), expected)
    # a scalar intercept and a single state both work
    single = ec.structured_predict(1.0, path, rho, chi, p_bus[0], q_bus[0])
    assert single.shape == (N_BUSES,)
    assert np.allclose(single, 1.0 + s_p @ p_bus[0] + s_q @ q_bus[0])


def test_tree_matrices_on_a_long_synthetic_chain():
    """A 30-branch chain: path must be lower triangular and `lindistflow` cumulative."""
    n = 30
    parent = np.arange(-1, n - 1)
    path, _ = ec.tree_matrices(parent, np.arange(n), n)
    assert np.array_equal(path, np.tril(np.ones((n, n), dtype=bool)))
    rho = np.full(n, RHO)
    s_p, _ = ec.lindistflow(path, rho, rho)
    assert np.isclose(s_p[n - 1, n - 1], n * RHO)
    assert np.isclose(s_p[0, n - 1], RHO)


def test_fit_structured_nnls_on_a_chain_recovers_per_branch_parameters():
    """A 20-bus chain and 150 steps: 3,000 stacked rows and 41 unknowns, the same shape of
    problem as the runner's (rural3 is about 45,000 x 257, which is NOT checked here)."""
    n = 20
    path, _ = ec.tree_matrices(np.arange(-1, n - 1), np.arange(n), n)
    rho = np.linspace(0.5, 0.9, n)
    chi = 0.5 * rho
    rng = np.random.default_rng(23)
    p_bus = rng.normal(0.0, 0.01, size=(150, n))
    q_bus = rng.normal(0.0, 0.004, size=(150, n))
    noisy = ec.structured_predict(1.0, path, rho, chi, p_bus, q_bus) + rng.normal(
        0.0, 1e-9, size=(150, n)
    )
    c_hat, rho_hat, chi_hat, _ = ec.fit_structured_nnls(path, p_bus, q_bus, noisy)
    assert c_hat == pytest.approx(1.0, abs=1e-6)
    assert np.allclose(rho_hat, rho, rtol=1e-3)
    assert np.allclose(chi_hat, chi, rtol=1e-3)


# --- D. estimators -------------------------------------------------------------------------


def test_ols_and_small_lambda_ridge_recover_the_known_slopes():
    path, rho, chi, p_bus, _, noisy, _ = excited_design()
    s_p, _ = ec.lindistflow(path, rho, chi)
    ols = ec.fit_ols(p_bus, noisy)
    ridge = ec.fit_ridge(p_bus, noisy, 1e-9)
    assert ols.rank == N_BUSES
    assert np.allclose(ols.slopes, s_p.T, rtol=1e-3)
    assert np.allclose(ridge.slopes, s_p.T, rtol=1e-3)
    assert np.allclose(ols.intercepts, 1.0, atol=1e-5)
    assert np.all(ols.sigma2 > 0.0)
    assert ridge.df == pytest.approx(N_BUSES, abs=1e-6)


def test_fit_structured_nnls_recovers_rho_and_chi():
    path, rho, chi, p_bus, q_bus, noisy, _ = excited_design(with_q=True, sigma=1e-8)
    c_hat, rho_hat, chi_hat, residual = ec.fit_structured_nnls(path, p_bus, q_bus, noisy)
    assert c_hat == pytest.approx(1.0, abs=1e-6)
    assert np.allclose(rho_hat, rho, rtol=1e-3)
    assert np.allclose(chi_hat, chi, rtol=1e-3)
    assert np.all(rho_hat >= 0.0) and np.all(chi_hat >= 0.0)
    assert residual < 1e-4


def test_collinear_injections_drop_the_ols_rank_and_blow_up_the_condition_number():
    path, rho, chi, p_bus, _, noisy, _ = excited_design()
    p_bus = p_bus.copy()
    p_bus[:, 2] = p_bus[:, 1]  # perfectly collinear columns
    del path, rho, chi
    ols = ec.fit_ols(p_bus, noisy)
    assert ols.rank == N_BUSES - 1
    _, cond = ec.ols_box_sd(p_bus, ols.sigma2)
    assert cond > 1e10


def test_estimators_refuse_a_misshaped_target_and_accept_a_single_bus():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=96)
    del path, rho, chi
    with pytest.raises(ValueError, match="96 x n_buses"):
        ec.fit_ols(p_bus, noisy.T)
    single = ec.fit_ridge(p_bus, noisy[:, 0], 1e-9)
    assert single.slopes.shape == (N_BUSES, 1)


def test_ridge_penalty_zeroes_a_constant_column():
    x = np.column_stack([np.linspace(0.0, 1.0, 20), np.full(20, 0.5)])
    penalty, zero_var = ec.ridge_penalty(x, 2.0)
    assert np.array_equal(zero_var, [False, True])
    assert penalty[0, 0] == pytest.approx(2.0 * x[:, 0].std() ** 2)
    assert penalty[1, 1] == 1.0  # the unit anchor that forces the slope to 0
    fit = ec.fit_ridge(x, np.linspace(1.0, 1.1, 20)[:, None], 2.0)
    assert fit.slopes[1, 0] == 0.0


def test_cv_lambda_is_deterministic_and_breaks_ties_towards_the_larger_lambda():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=192)
    del path, rho, chi
    block = np.repeat([0, 1], 96)  # two "training days"
    grid = np.array([1e-6, 1e-3, 1.0])
    first, table = ec.cv_lambda(p_bus, noisy, block, grid)
    second, _ = ec.cv_lambda(p_bus, noisy, block, grid)
    assert first == second
    assert first in set(grid)
    assert table.shape == (3, 2)
    # an exactly tied score table: Y is constant, so every lambda predicts it perfectly
    tied, tied_table = ec.cv_lambda(p_bus, np.zeros((192, 2)), block, grid)
    assert np.all(tied_table[:, 1] == 0.0)
    assert tied == grid[-1]


def test_cv_lambda_default_grid_scales_with_the_sample_size():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=96)
    del path, rho, chi
    block = np.repeat([0, 1, 2], 32)
    _, table = ec.cv_lambda(p_bus, noisy, block)
    assert table.shape == (33, 2)
    assert table[0, 0] == pytest.approx(96 * 1e-6)
    assert table[-1, 0] == pytest.approx(96 * 1e2)


def test_conformal_margin_follows_the_index_rule():
    residuals = np.arange(1.0, 97.0)[:, None]  # 96 held-out steps, |residual| = 1..96
    assert ec.conformal_margin(residuals)[0] == 93.0  # ceil(97 x 0.95) = 93
    small = np.arange(1.0, 11.0)[:, None]
    assert ec.conformal_margin(small, alpha=0.2)[0] == 9.0  # ceil(11 x 0.8) = 9
    with pytest.raises(ValueError, match="exceeds n"):
        ec.conformal_margin(small, alpha=0.05)  # ceil(11 x 0.95) = 11 > 10


def test_ridge_box_sd_tends_to_the_ols_box_as_lambda_goes_to_zero():
    path, rho, chi, p_bus, _, noisy, _ = excited_design()
    del path, rho, chi
    ols = ec.fit_ols(p_bus, noisy)
    ridge = ec.fit_ridge(p_bus, noisy, 1e-12)
    ridge_sd = ec.ridge_box_sd(p_bus, ridge.M, ols.sigma2)
    ols_sd, cond = ec.ols_box_sd(p_bus, ols.sigma2)
    assert np.allclose(ridge_sd, ols_sd, rtol=1e-5)
    assert math.isfinite(cond)


def test_method_a_offset_and_a_prime_intercept():
    path, rho, chi, p_bus, q_bus, noisy, truth = excited_design(with_q=True)
    state_v = truth[0] + 0.004  # an AC state whose offset is 0.004 above the linear model
    offset = ec.offset_from_state(state_v, 0.0, path, rho, chi, p_bus[0], q_bus[0])
    assert np.allclose(offset, 1.0 + 0.004)
    intercept = ec.training_intercept(noisy, path, rho, chi, p_bus, q_bus)
    assert np.allclose(intercept, 1.0, atol=1e-5)
    # predicting with the offset as the whole intercept reproduces the state
    assert np.allclose(ec.structured_predict(offset, path, rho, chi, p_bus[0], q_bus[0]), state_v)


# --- E. bootstrap and alternatives ---------------------------------------------------------


def test_moving_block_indices_shape_and_circularity():
    idx = ec.moving_block_indices(ec.rng_for(NET, "P1", "bootstrap"), 50, block=16)
    assert idx.shape == (50,)
    assert idx.min() >= 0 and idx.max() < 50
    assert np.array_equal(idx[:16], (idx[0] + np.arange(16)) % 50)


def test_bootstrap_radius_is_deterministic_with_positive_radii():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=96)
    del path, rho, chi
    first = ec.bootstrap_radius(p_bus, noisy, 1.0, ec.rng_for(NET, "P1", "radius_refit"), n_boot=25)
    second = ec.bootstrap_radius(
        p_bus, noisy, 1.0, ec.rng_for(NET, "P1", "radius_refit"), n_boot=25
    )
    assert np.array_equal(first.d, second.d)
    assert first.c == second.c
    assert np.all(first.r2 > 0.0)
    assert first.d.shape == (N_BUSES, 25)
    assert np.all(np.isfinite(first.f_radius))  # T - 1 - p = 91 > 0 here


def test_bootstrap_radius_f_diagnostic_is_nan_without_degrees_of_freedom():
    rng = np.random.default_rng(5)
    x = rng.normal(size=(5, 5))  # T = 5, p = 5, so T - 1 - p = -1
    y = rng.normal(size=(5, 2))
    result = ec.bootstrap_radius(x, y, 1.0, ec.rng_for(NET, "P1", "radius_refit"), n_boot=5)
    assert np.all(np.isnan(result.f_radius))


def test_fit_nn_ridge_is_non_negative_and_matches_the_ridge_when_the_ridge_already_is():
    path, rho, chi, p_bus, _, noisy, _ = excited_design()
    del path, rho, chi
    lam = 1e-6
    ridge = ec.fit_ridge(p_bus, noisy, lam)
    assert np.all(ridge.slopes > 0.0)  # the LinDistFlow truth is positive
    nn = ec.fit_nn_ridge(p_bus, noisy, lam)
    assert np.all(nn.slopes >= 0.0)
    assert np.allclose(nn.slopes, ridge.slopes, rtol=1e-5)
    assert np.allclose(nn.intercepts, ridge.intercepts, rtol=1e-9)
    # a sign-flipped target forces the constraint to bind
    flipped = ec.fit_nn_ridge(p_bus, -noisy, lam)
    assert np.all(flipped.slopes >= 0.0)
    assert np.any(flipped.slopes == 0.0)


def test_random_alternatives_are_admissible_and_report_their_rmse_ratio():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=96)
    del path, rho, chi
    penalty, _ = ec.ridge_penalty(p_bus, 1e-9)  # the reference is then the in-sample optimum
    alts, ratios = ec.random_alternatives(
        p_bus, noisy, penalty, ec.rng_for(NET, "P1", "ambiguity_refit")
    )
    assert len(alts) == 4 and ratios.shape == (4,)
    assert all(np.all(a.slopes >= 0.0) for a in alts)
    assert np.all(ratios >= 1.0 - 1e-9)  # no resample fits the full sample better
    again, ratios_again = ec.random_alternatives(
        p_bus, noisy, penalty, ec.rng_for(NET, "P1", "ambiguity_refit")
    )
    assert np.array_equal(alts[0].slopes, again[0].slopes)
    assert np.allclose(ratios, ratios_again)


def test_extreme_alternatives_sit_on_the_ellipsoid_and_stay_admissible():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=96)
    del path, rho, chi
    penalty, _ = ec.ridge_penalty(p_bus, 1.0)
    fit = ec.fit_ridge(p_bus, noisy, 1.0)
    centre = ec.fit_nn_ridge(p_bus, noisy, penalty)

    tiny = np.full(N_BUSES, 1e-8)
    alts, shrink = ec.extreme_alternatives(p_bus, noisy, penalty, tiny, fit.M)
    assert len(alts) == 4 and shrink.shape == (4, N_BUSES)
    assert np.all(shrink == 1.0)  # no shrink needed this close to the centre
    for alt in alts:
        assert np.all(alt.slopes >= 0.0)
        for k in range(N_BUSES):
            diff = alt.slopes[:, k] - centre.slopes[:, k]
            assert diff @ fit.M @ diff == pytest.approx(tiny[k], rel=1e-6)

    huge = np.full(N_BUSES, 1e4)
    alts_big, shrink_big = ec.extreme_alternatives(p_bus, noisy, penalty, huge, fit.M)
    assert np.all(shrink_big > 0.0) and np.all(shrink_big <= 1.0)
    assert np.any(shrink_big < 1.0)
    for alt in alts_big:
        assert np.all(alt.slopes >= 0.0)
        pred = alt.intercepts + p_bus @ alt.slopes
        assert np.all(np.isfinite(pred))


# --- F. diagnostics ------------------------------------------------------------------------


def test_excitation_diagnostics_separates_independent_from_duplicated_injections():
    path, rho, chi, p_bus, _, _, _ = excited_design(n_steps=96)
    del path, rho, chi
    daylight = np.ones(96, dtype=bool)
    good = ec.excitation_diagnostics(p_bus, p_bus, daylight)
    assert good["effective_rank"] > 3.5
    assert math.isfinite(good["condition_number"])
    assert np.all(good["independent_variance"] > 0.0)
    assert abs(good["pv_corr_mean"]) < 0.5

    duplicated = p_bus.copy()
    duplicated[:, 1] = duplicated[:, 0]
    bad = ec.excitation_diagnostics(duplicated, duplicated, daylight)
    assert bad["condition_number"] == math.inf
    assert bad["effective_rank"] < good["effective_rank"]
    assert bad["pv_corr_mean"] > good["pv_corr_mean"]
    assert bad["independent_variance"][0] < 1e-20

    # the degenerate case the board audit found in the native profiles: identical units
    identical = np.tile(p_bus[:, :1], (1, 4))
    same = ec.excitation_diagnostics(identical, identical, daylight)
    assert same["pv_corr_mean"] == pytest.approx(1.0)
    assert same["pv_corr_min"] == pytest.approx(1.0)
    assert same["effective_rank"] == pytest.approx(1.0)


def test_corner_distance_is_zero_at_the_training_mean():
    path, rho, chi, p_bus, _, _, _ = excited_design(n_steps=96)
    del path, rho, chi
    at_mean = ec.corner_distance(p_bus, p_bus.mean(axis=0))
    assert at_mean["residual_norm"] == pytest.approx(0.0, abs=1e-12)
    assert at_mean["mahalanobis"] == pytest.approx(0.0, abs=1e-12)
    far = ec.corner_distance(p_bus, p_bus.mean(axis=0) + 1.0)
    assert far["mahalanobis"] > 10.0


def test_marginal_check_passes_a_matched_regime_and_fails_a_shifted_one():
    bump = daylight_bump()
    ratings = np.array([0.01, 0.02, 0.005])
    p1 = bump[:, None] * ratings
    train = np.arange(ec.STEPS_PER_DAY)
    daylight = bump > 0.0

    matched = ec.marginal_check({"P1": p1, "P2": p1 * 1.005, "P3": p1 * 1.004}, train, daylight)
    assert matched["passed"]
    assert matched["against_P1"]["P2"]["mean_within_1pct"]

    shifted = ec.marginal_check({"P1": p1, "P2": p1 * 1.005, "P3": p1 * 1.02}, train, daylight)
    assert not shifted["passed"]
    assert not shifted["against_P1"]["P3"]["mean_within_1pct"]
    assert shifted["against_P1"]["P2"]["passed"]
    assert np.all(shifted["against_P1"]["P3"]["ks"] >= 0.0)


def test_shuffled_fit_destroys_the_relationship():
    path, rho, chi, p_bus, _, noisy, _ = excited_design(n_steps=192)
    del path, rho, chi
    fit = ec.fit_ridge(p_bus, noisy, 1.0)
    shuffled = ec.shuffled_fit(p_bus, noisy, 1.0, ec.rng_for(NET, "P1", "shuffle"))
    again = ec.shuffled_fit(p_bus, noisy, 1.0, ec.rng_for(NET, "P1", "shuffle"))
    assert np.array_equal(shuffled.slopes, again.slopes)
    assert np.linalg.norm(shuffled.slopes) < np.linalg.norm(fit.slopes)


# --- G. statistics -------------------------------------------------------------------------


def test_paired_bootstrap_p_value_on_the_protocol_hand_examples():
    """Protocol s. 9: 4 of 10 discordant conditions must beat Holm's tightest lower tail."""
    rng = ec.rng_for(NET, "P1", "bootstrap")
    four = ec.paired_bootstrap(np.array([1.0] * 4 + [0.0] * 6), rng, n_boot=20_000)
    assert four.mean == pytest.approx(0.4)
    assert four.p == pytest.approx(2.0 * 0.6**10, abs=0.004)
    assert four.p < 0.0125
    assert four.lo > 0.0
    three = ec.paired_bootstrap(np.array([1.0] * 3 + [0.0] * 7), rng, n_boot=20_000)
    assert three.p > 0.0125


def test_paired_bootstrap_is_two_sided_and_capped():
    rng = ec.rng_for(NET, "P1", "bootstrap")
    result = ec.paired_bootstrap(np.array([-1.0, 1.0, -1.0, 1.0]), rng, n_boot=2000)
    assert result.p <= 1.0
    assert result.lo < 0.0 < result.hi


def test_clopper_pearson_zero_of_ten():
    lo, hi = ec.clopper_pearson(0, 10)
    assert lo == 0.0
    assert hi == pytest.approx(0.3085, abs=1e-4)
    assert ec.clopper_pearson(10, 10)[1] == 1.0
    with pytest.raises(ValueError):
        ec.clopper_pearson(11, 10)


def test_holm_matches_a_hand_example():
    rejected, adjusted = ec.holm([0.01, 0.02, 0.03, 0.04])
    assert np.allclose(adjusted, [0.04, 0.06, 0.06, 0.06])
    assert list(rejected) == [True, False, False, False]
    # the order of the input is preserved
    rejected2, adjusted2 = ec.holm([0.04, 0.03, 0.02, 0.01])
    assert np.allclose(adjusted2, [0.06, 0.06, 0.06, 0.04])
    assert list(rejected2) == [False, False, False, True]


def test_spearman_is_monotone_invariant():
    r, p = ec.spearman([1.0, 2.0, 3.0, 4.0], [10.0, 20.0, 30.0, 40.0])
    assert r == pytest.approx(1.0)
    assert p < 0.05
    assert ec.spearman([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0])[0] == pytest.approx(-1.0)


# --- H. the ledger and write discipline ----------------------------------------------------


def test_solve_ledger_raises_before_charging_over_the_ceiling():
    ledger = ec.SolveLedger(start=106, ceiling=110)
    assert ledger.remaining() == 4
    assert ledger.charge("selection", 4) == 110
    assert ledger.remaining() == 0
    with pytest.raises(RuntimeError, match="ceiling"):
        ledger.charge("envelopes", 1)
    assert ledger.total == 110  # nothing was charged
    assert ledger.items == {"selection": 4}


def test_solve_ledger_round_trips_and_defaults_to_the_protocol_numbers():
    ledger = ec.SolveLedger()
    assert (ledger.start, ledger.ceiling) == (106, 8000)
    ledger.charge("training", 3840)
    restored = ec.SolveLedger.from_dict(ledger.to_dict())
    assert restored.to_dict() == ledger.to_dict()
    assert restored.total == 106 + 3840
    with pytest.raises(ValueError):
        ledger.charge("bad", -1)


def test_write_json_once_and_write_npz_once_refuse_to_overwrite(tmp_path):
    json_path = tmp_path / "nested" / "record.json"
    ec.write_json_once(json_path, {"solves": 106, "array": np.arange(3)})
    assert json_path.exists()
    with pytest.raises(FileExistsError):
        ec.write_json_once(json_path, {"solves": 0})

    npz_path = tmp_path / "state.npz"
    ec.write_npz_once(npz_path, v=np.zeros(3))
    with pytest.raises(FileExistsError):
        ec.write_npz_once(npz_path, v=np.ones(3))


def test_check_protocol_refuses_a_wrong_hash_and_accepts_the_declared_one(tmp_path):
    """The expected digest defaults to revision 2's; the live file is not read here, because
    the board may register a later revision (see the report's protocol note)."""
    stand_in = tmp_path / "not_the_protocol.md"
    stand_in.write_text("a synthetic stand-in, not the protocol\n")
    with pytest.raises(ValueError, match="sha256"):
        ec.check_protocol(stand_in)
    digest = ec.sha256_of(stand_in)
    assert ec.check_protocol(stand_in, expected=digest) == digest
    assert len(ec.PROTOCOL_SHA256) == 64
