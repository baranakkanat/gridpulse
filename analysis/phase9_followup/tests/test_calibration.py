"""Synthetic tests of `analysis/phase9_followup/calibration.py`.

Nothing here reads a network, an artefact, a Phase 9 result or `outputs/`; every input is a
toy array. The whole file is meant to stay well under 30 s.
"""

from __future__ import annotations

import math

import calibration as cal
import numpy as np
import pytest
from scipy import stats


# --- C1, the exact plug-in floor ------------------------------------------------------------


def test_c1_floor_matches_the_hand_formula_on_a_toy_day_set():
    """F^2 = sigma^2 * sum_{d in S} (1/n_d + 1/m_d) / |S|^2, by hand on four days."""
    sigma = 0.01
    n_day = np.array([10.0, 20.0, 40.0, 50.0])
    n_night = 96.0 - n_day
    v = 1.0 / n_day + 1.0 / n_night
    survives = np.array([[True, True], [False, True], [True, False], [True, True]])

    floor = cal.c1_floor(sigma, v, survives)

    first = sigma * math.sqrt(v[0] + v[2] + v[3]) / 3.0
    second = sigma * math.sqrt(v[0] + v[1] + v[3]) / 3.0
    assert floor == pytest.approx([first, second], rel=1e-12)


def test_c1_floor_with_every_day_kept_and_equal_counts_is_the_registered_form():
    """With n_d == n and m_d == m on all D days, F reduces to sigma sqrt(1/n + 1/m) / sqrt(D)."""
    sigma, days = 0.02, 16
    v = np.full(days, 1.0 / 30.0 + 1.0 / 66.0)
    floor = cal.c1_floor(sigma, v, np.ones((days, 3), dtype=bool))
    assert floor == pytest.approx(sigma * math.sqrt(v[0]) / math.sqrt(days), rel=1e-12)


def test_c1_floor_is_nan_for_a_meter_with_no_kept_day():
    floor = cal.c1_floor(0.01, np.full(5, 0.05), np.zeros((5, 1), dtype=bool))
    assert np.isnan(floor).all()


# --- C2, the day-level Student t -------------------------------------------------------------


def test_c2_statistic_and_critical_value_against_scipy():
    rng = np.random.default_rng(7)
    contrast = rng.normal(0.0, 0.001, size=(12, 1))
    survives = np.ones((12, 1), dtype=bool)
    k_hat = contrast.mean(axis=0)

    parts = cal.calibration_ratios(contrast, survives, k_hat, 0.01, np.full(12, 0.05))
    expected = stats.ttest_1samp(contrast[:, 0], 0.0)
    assert parts["t_stat"][0] == pytest.approx(abs(expected.statistic), rel=1e-12)

    for k in (1, 2, 4):
        assert cal.t_critical(11, k) == pytest.approx(
            stats.t.ppf(1.0 - 0.025 / k, 11), rel=1e-12)
        ratio = cal.ratios_for_k(parts, k, 1.0)["C2"][0]
        assert ratio == pytest.approx(abs(expected.statistic) / cal.t_critical(11, k), rel=1e-12)


def test_c2_ignores_the_days_a_meter_lost():
    """The t statistic is taken on the kept days only."""
    contrast = np.array([[1.0], [99.0], [2.0], [3.0], [-50.0]])
    survives = np.array([[True], [False], [True], [True], [False]])
    k_hat = np.array([2.0])
    parts = cal.calibration_ratios(contrast, survives, k_hat, 0.01, np.full(5, 0.05))
    expected = stats.ttest_1samp(np.array([1.0, 2.0, 3.0]), 0.0)
    assert parts["t_stat"][0] == pytest.approx(abs(expected.statistic), rel=1e-12)


def test_c2_and_c3_have_no_statistic_below_two_kept_days():
    contrast = np.array([[1.0], [2.0], [3.0]])
    survives = np.array([[True], [False], [False]])
    parts = cal.calibration_ratios(contrast, survives, np.array([1.0]), 0.01, np.full(3, 0.05))
    assert np.isnan(parts["t_stat"]).all() and np.isnan(parts["hac_stat"]).all()
    assert parts["too_few_days"] == 1
    ratios = cal.ratios_for_k(parts, 1, 1.0)
    assert np.isnan(ratios["C2"]).all() and np.isnan(ratios["C3"]).all()


# --- C3, the Newey-West variance ---------------------------------------------------------------


def test_newey_west_at_lag_zero_is_the_plain_sample_variance():
    rng = np.random.default_rng(11)
    series = rng.normal(size=(9, 4))
    centred = series - series.mean(axis=0)
    counts = np.full(4, 9.0)
    omega = cal.newey_west_variance(centred, counts, np.zeros(4, dtype=int))
    assert omega == pytest.approx(series.var(axis=0), rel=1e-12)


def test_newey_west_lag_one_by_hand():
    """L = 1 gives omega^2 = gamma_0 + 2 * (1 - 1/2) * gamma_1 = gamma_0 + gamma_1."""
    series = np.array([1.0, 2.0, 4.0, 5.0])
    centred = (series - series.mean())[:, None]
    gamma0 = float((centred[:, 0] ** 2).sum() / 4.0)
    gamma1 = float((centred[:-1, 0] * centred[1:, 0]).sum() / 4.0)
    omega = cal.newey_west_variance(centred, np.array([4.0]), np.array([1]))
    assert omega[0] == pytest.approx(gamma0 + gamma1, rel=1e-12)
    # centred is (-2, -1, 1, 2): gamma_0 = (4 + 1 + 1 + 4)/4, gamma_1 = (2 - 1 + 2)/4
    assert gamma0 == pytest.approx(2.5, rel=1e-12)
    assert gamma1 == pytest.approx(0.75, rel=1e-12)
    assert omega[0] == pytest.approx(3.25, rel=1e-12)


def test_bartlett_lag_matches_the_stated_bandwidth():
    counts = np.array([10, 100, 137, 144, 1000])
    expected = [int(math.floor(4.0 * (c / 100.0) ** (2.0 / 9.0))) for c in counts]
    assert list(cal.bartlett_lag(counts)) == expected
    assert cal.bartlett_lag(np.array([144]))[0] == 4


def test_newey_west_uses_each_meter_s_own_bandwidth():
    """Two meters, identical series, different bandwidths: lag 0 drops the gamma_1 term."""
    series = np.array([1.0, 2.0, 4.0, 5.0])
    centred = np.column_stack([series - series.mean()] * 2)
    omega = cal.newey_west_variance(centred, np.array([4.0, 4.0]), np.array([0, 1]))
    gamma0 = float(((series - series.mean()) ** 2).sum() / 4.0)
    assert omega[0] == pytest.approx(gamma0, rel=1e-12)
    assert omega[1] > omega[0]


def test_compact_moves_the_kept_days_forward_in_calendar_order():
    values = np.array([[1.0], [2.0], [3.0], [4.0]])
    survives = np.array([[False], [True], [False], [True]])
    assert list(cal.compact(values, survives)[:, 0]) == [2.0, 4.0, 0.0, 0.0]


def test_c3_statistic_equals_the_hand_built_hac_t():
    rng = np.random.default_rng(3)
    contrast = rng.normal(0.0005, 0.001, size=(20, 1))
    survives = np.ones((20, 1), dtype=bool)
    k_hat = contrast.mean(axis=0)
    parts = cal.calibration_ratios(contrast, survives, k_hat, 0.01, np.full(20, 0.05))

    centred = contrast[:, 0] - k_hat[0]
    lag = int(cal.bartlett_lag(np.array([20]))[0])
    omega = float((centred**2).sum() / 20.0)
    for j in range(1, lag + 1):
        omega += 2.0 * (1.0 - j / (lag + 1.0)) * float((centred[:-j] * centred[j:]).sum() / 20.0)
    assert parts["hac_stat"][0] == pytest.approx(abs(k_hat[0]) / math.sqrt(omega / 20.0),
                                                 rel=1e-12)  # fmt: skip
    assert cal.ratios_for_k(parts, 2, 1.0)["C3"][0] == pytest.approx(
        parts["hac_stat"][0] / stats.norm.ppf(1.0 - 0.0125), rel=1e-12)


# --- the within-day AR(1) day/night covariance ---------------------------------------------------


def _mask(n_steps: int, daylight: slice) -> np.ndarray:
    mask = np.zeros(n_steps, dtype=bool)
    mask[daylight] = True
    return mask


def test_ar1_moments_reduce_to_sigma_squared_over_n_at_rho_zero():
    mask = _mask(24, slice(8, 18))
    var_a, var_b, cov = cal.ar1_moments(mask, 0.01, 0.0)
    assert var_a == pytest.approx(0.01**2 / 10, rel=1e-12)
    assert var_b == pytest.approx(0.01**2 / 14, rel=1e-12)
    assert cov == pytest.approx(0.0, abs=1e-18)


def test_ar1_moments_against_a_brute_force_simulation():
    """Simulate the AR(1) step series itself and compare the day/night mean moments."""
    mask = _mask(32, slice(10, 22))
    sigma, rho = 1.0, 0.7
    var_a, var_b, cov = cal.ar1_moments(mask, sigma, rho)

    rng = np.random.default_rng(101)
    draws = 200_000
    series = np.empty((draws, 32))
    series[:, 0] = rng.standard_normal(draws) * sigma
    step = sigma * math.sqrt(1.0 - rho**2)
    for t in range(1, 32):
        series[:, t] = rho * series[:, t - 1] + step * rng.standard_normal(draws)
    day = series[:, mask].mean(axis=1)
    night = series[:, ~mask].mean(axis=1)

    assert day.var() == pytest.approx(var_a, rel=0.02)
    assert night.var() == pytest.approx(var_b, rel=0.02)
    assert float(np.cov(day, night)[0, 1]) == pytest.approx(cov, rel=0.05)


def test_ar1_moments_grow_with_rho_and_stay_a_valid_covariance():
    mask = _mask(40, slice(12, 26))
    low = cal.ar1_moments(mask, 0.01, 0.3)
    high = cal.ar1_moments(mask, 0.01, 0.9)
    assert high[0] > low[0] and high[1] > low[1] and high[2] > low[2]
    for var_a, var_b, cov in (low, high):
        assert abs(cov) < math.sqrt(var_a * var_b)


def test_ar1_moments_refuse_a_day_without_both_legs():
    with pytest.raises(ValueError):
        cal.ar1_moments(np.ones(10, dtype=bool), 0.01, 0.5)


# --- the pre-stated validity rule ----------------------------------------------------------------


def _per_k(rates):
    """A K grid of pooled records with chosen rate / low / high triples."""
    return {f"K_{k}": {"pooled_over_rules": dict(zip(("rate", "low", "high"), triple,
                                                     strict=True))}
            for k, triple in zip(cal.K_GRID, rates, strict=True)}  # fmt: skip


def test_validity_boundaries():
    assert cal.VALIDITY_RULE["rate_limit"] == 0.055
    assert cal.VALIDITY_RULE["lower_bound_limit"] == 0.05
    assert cal.VALIDITY_RULE["conservative_limit"] == 0.03

    on_the_line = _per_k([(0.055, 0.05, 0.06)] * 3)
    assert cal.verdict(on_the_line)["valid"] is True

    rate_just_over = _per_k([(0.0551, 0.05, 0.06)] + [(0.04, 0.03, 0.05)] * 2)
    assert cal.verdict(rate_just_over)["valid"] is False

    bound_just_over = _per_k([(0.054, 0.0501, 0.06)] + [(0.04, 0.03, 0.05)] * 2)
    assert cal.verdict(bound_just_over)["valid"] is False

    one_bad_k = _per_k([(0.02, 0.01, 0.03)] * 2 + [(0.09, 0.08, 0.10)])
    assert cal.verdict(one_bad_k)["valid"] is False
    assert cal.verdict(one_bad_k)["max_pooled_rate"] == 0.09


def test_conservative_boundary_is_strict():
    assert cal.verdict(_per_k([(0.01, 0.005, 0.0299)] * 3))["conservative"] is True
    assert cal.verdict(_per_k([(0.01, 0.005, 0.03)] * 3))["conservative"] is False


def test_validity_requires_both_networks():
    good = {"valid": True, "conservative": True, "max_pooled_rate": 0.04}
    bad = {"valid": False, "conservative": False, "max_pooled_rate": 0.08}
    assert cal.combine({"a": good, "b": good})["valid"] is True
    assert cal.combine({"a": good, "b": bad})["valid"] is False
    assert cal.combine({"a": good, "b": bad})["max_pooled_rate"] == 0.08


def test_simplest_correction_takes_the_first_valid_of_c1_c2_c3():
    def block(family, flags):
        return {"family": family,
                "calibrations": {name: {"valid": flag} for name, flag in flags.items()}}

    flags = {"C0": False, "C1": False, "C2": True, "C3": True}
    matrix = {"realistic": block("N1", flags), "sigma_0.02": block("N1", flags),
              "ar1_within_day_rho_0.9": block("N2", {k: False for k in cal.CALIBRATIONS})}
    assert cal.simplest_correction(matrix)["calibration"] == "C2"

    none_valid = {"realistic": block("N1", {k: False for k in cal.CALIBRATIONS})}
    assert cal.simplest_correction(none_valid)["calibration"] is None


# --- the analytic decomposition ---------------------------------------------------------------


def _toy_axis(counts, delay=True):
    return cal.axis_from_counts(list(range(len(counts))), counts, delay=delay)


def test_inflation_is_one_when_every_plug_in_is_exact():
    """Homogeneous counts, no delay and the registered 0.95 realised exactly: lambda = 1
    once the missing-day expectation is used."""
    axis = _toy_axis([40] * 100, delay=False)
    none = cal.inflation(axis, heterogeneity=False, delay=False, missing=False)
    assert none["sd_inflation"] == pytest.approx(math.sqrt(0.95), rel=1e-12)
    with_missing = cal.inflation(axis, heterogeneity=False, delay=False, missing=True)
    assert with_missing["sd_inflation"] == pytest.approx(1.0, rel=2e-3)
    assert with_missing["sd_inflation"] > none["sd_inflation"]


def test_the_board_convention_credits_the_floor_with_0_95_until_the_missing_row():
    axis = _toy_axis([8] * 20 + [48] * 60 + [50] * 20, delay=True)
    for delay in (False, True):
        dry = cal.inflation(axis, heterogeneity=True, delay=delay, missing=False)
        assert dry["sd_inflation_board_convention"] == pytest.approx(
            dry["sd_inflation"] / math.sqrt(0.95), rel=1e-12)
    wet = cal.inflation(axis, heterogeneity=True, delay=True, missing=True)
    assert wet["sd_inflation_board_convention"] == pytest.approx(wet["sd_inflation"], rel=1e-12)


def test_heterogeneity_raises_the_inflation_because_the_mean_of_1_over_n_exceeds_its_median():
    axis = _toy_axis([8] * 20 + [48] * 60 + [50] * 20, delay=False)
    flat = cal.inflation(axis, heterogeneity=False, delay=False, missing=False)
    rough = cal.inflation(axis, heterogeneity=True, delay=False, missing=False)
    assert rough["mean_v"] > flat["mean_v"]
    assert rough["sd_inflation"] > flat["sd_inflation"]


def test_expected_inverse_kept_days():
    """E[1/|S|] sits just above 1/E[|S|] by Jensen, and the |S| = 0 atom is reported."""
    record = cal.expected_inverse_kept(100, 0.95)
    assert record["expected_inverse"] > 1.0 / 95.0
    assert record["expected_inverse"] == pytest.approx(1.0 / 95.0, rel=5e-3)
    assert record["probability_no_kept_day"] < 1e-100


def test_predicted_rate_is_the_nominal_alpha_at_inflation_one():
    for k in cal.K_GRID:
        assert cal.predicted_rate(1.0, k) == pytest.approx(1.0 - (1.0 - 0.05 / k) ** k, rel=1e-9)
    assert cal.predicted_rate(1.07, 1) > 0.05


def test_axis_from_counts_applies_retention_and_the_one_day_delay():
    axis = _toy_axis([0, 10, 96, 20, 30])
    assert axis["days"] == [1, 3]  # day 4 is removed by the delay, 0 and 2 by retention
    assert axis["D_retained"] == 3 and axis["D_simulated"] == 2
    assert axis["dropped_no_daylight_or_night"] == [0, 2]
    assert axis["v_days"] == pytest.approx([1 / 10 + 1 / 86, 1 / 20 + 1 / 76], rel=1e-12)


# --- the scenario draws ------------------------------------------------------------------------


def test_ar1_across_days_is_stationary_at_tau_and_carries_the_right_lag_one_correlation():
    rng = np.random.default_rng(5)
    series = cal.ar1_across_days(rng, 400, 400, 0.9, 0.004)
    assert series.std() == pytest.approx(0.004, rel=0.05)
    lag1 = float(np.corrcoef(series[:-1].ravel(), series[1:].ravel())[0, 1])
    assert lag1 == pytest.approx(0.9, abs=0.02)


def test_draw_ar1_within_day_reproduces_the_requested_moments():
    axis = _toy_axis([12] * 6, delay=False)
    axis["masks"] = {d: _mask(96, slice(30, 42)) for d in axis["days"]}
    moments = cal.ar1_day_night_spec(axis, 0.01, 0.5)
    rng = np.random.default_rng(13)
    draws = cal.draw_ar1_within_day(rng, moments, 4000, missing=0.0)
    assert draws["day"].std() == pytest.approx(moments["sd_day"][0], rel=0.05)
    assert draws["night"].std() == pytest.approx(moments["sd_night"][0], rel=0.05)
    observed = float(np.corrcoef(draws["day"].ravel(), draws["night"].ravel())[0, 1])
    assert observed == pytest.approx(moments["correlation"][0], abs=0.03)
    assert draws["survives"].all()


# --- the output file ------------------------------------------------------------------------------


def test_results_json_refuses_to_overwrite(tmp_path):
    import q1_voltage_residual as q1

    target = tmp_path / "calibration.json"
    q1.write_new_json(target, {"status": cal.STATUS})
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        q1.write_new_json(target, {"status": cal.STATUS})


@pytest.mark.skipif(
    not cal.PHASE9_INPUTS.exists(),
    reason=(
        "needs the held, untracked analysis/phase9/results/phase9_inputs.json, which is not "
        "part of the public repository"
    ),
)
def test_the_run_refuses_to_overwrite_its_results_json(tmp_path):
    import q1_voltage_residual as q1

    target = tmp_path / "calibration.json"
    q1.write_new_json(target, {"status": cal.STATUS})
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        cal.run(target, replicates=1)


def test_the_status_string_is_the_one_the_task_fixes():
    assert cal.STATUS == ("EXPLORATORY, post-hoc; not registered; Phase 9 results unchanged")
