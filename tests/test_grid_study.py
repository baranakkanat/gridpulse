import numpy as np
import pytest

pytest.importorskip("pandapower", reason="grid extra not installed (uv sync --all-extras)")

from gridpulse.grid import MARGINS, GridSolver, load_network  # noqa: E402
from gridpulse.grid_study import (  # noqa: E402
    CAP_LEVELS,
    FIRST_DECISION_DAY,
    FORECAST,
    REALISED,
    STEPS,
    WINDOW_DAYS,
    calibration,
    day_physics,
    deferral_reasons,
    first_level,
    forecast,
    injection_sets,
    outcome,
    physics_for,
    poisson_upper_quantile,
    run_decisions,
    scenarios,
    schedules,
    static_dev_level,
    summarise,
)

N_LEVELS = len(CAP_LEVELS)
TRAFO = MARGINS.index("trafo_overload_pct")


def coded_days(n_days: int = 60, n_elements: int = 3, seed: int = 0) -> np.ndarray:
    return np.random.default_rng(seed).uniform(0, 1, (n_days, STEPS, n_elements))


# --- Forecast and scenarios ----------------------------------------------------------


def test_forecast_is_the_mean_of_the_previous_seven_days():
    values = coded_days()
    np.testing.assert_allclose(forecast(values, 20), values[13:20].mean(axis=0))


def test_scenarios_are_forecast_plus_past_residual_days_only():
    values = coded_days()
    day = 50
    result = scenarios(values, day)

    assert result.shape == (WINDOW_DAYS, STEPS, 3)
    first = day - WINDOW_DAYS
    np.testing.assert_allclose(
        result[0], forecast(values, day) + values[first] - forecast(values, first)
    )
    future = values.copy()
    future[day:] = 99.0  # the decision day and everything after it
    np.testing.assert_array_equal(scenarios(future, day), result)
    with pytest.raises(ValueError):
        scenarios(values, FIRST_DECISION_DAY - 1)


def test_injection_sets_put_the_realised_day_first_and_clip_predictions():
    rng = np.random.default_rng(1)
    arrays = {
        "load_p_mw": rng.normal(0.0, 1.0, (60, STEPS, 2)),
        "load_q_mvar": rng.normal(0.0, 1.0, (60, STEPS, 2)),
        "sgen_p_mw": rng.normal(0.5, 1.0, (60, STEPS, 2)),
    }
    rating = np.array([0.8, 1.2])
    sets = injection_sets(arrays, 45, rating)

    assert sets["sgen_p_mw"].shape == (2 + WINDOW_DAYS, STEPS, 2)
    np.testing.assert_array_equal(sets["sgen_p_mw"][REALISED], arrays["sgen_p_mw"][45])
    predicted_pv = sets["sgen_p_mw"][FORECAST:]
    assert (predicted_pv >= 0).all() and (predicted_pv <= rating).all()
    assert (sets["load_p_mw"][FORECAST:] >= 0).all()
    assert (sets["load_q_mvar"][FORECAST:] < 0).any()  # reactive power is not clipped


# --- Policies ------------------------------------------------------------------------


def test_first_level_takes_the_least_curtailment_that_is_acceptable():
    acceptable = np.zeros((STEPS, N_LEVELS), dtype=bool)
    acceptable[0, 0] = True  # no cap is fine
    acceptable[1, 3:] = True  # needs k <= 0.7
    # step 2: nothing acceptable -> deepest cap
    levels = first_level(acceptable)
    assert levels[:3].tolist() == [0, 3, N_LEVELS - 1]


def synthetic_violations(n_scenarios: int = WINDOW_DAYS) -> np.ndarray:
    """No violations anywhere, except where a test sets them."""
    return np.zeros((2 + n_scenarios, STEPS, N_LEVELS), dtype=bool)


def test_schedules_use_scenarios_for_risk_forecast_for_point_and_realised_only_for_oracle():
    violations = synthetic_violations()
    violations[2:4, 10, :2] = True  # 2 of 28 scenarios violate at k = 1.0, 0.9
    violations[2:5, 11, :5] = True  # 3 of 28 scenarios violate down to k = 0.6
    violations[FORECAST, 12, :4] = True
    violations[REALISED, 13, :6] = True
    plan = schedules(violations, alpha=0.05)

    assert plan["risk"][10] == 2  # risk 2/28 = 0.071 > 0.05 at k = 1.0 and 0.9
    assert plan["risk"][11] == 5  # risk 3/28 down to k = 0.6
    assert plan["risk"][12] == 0 and plan["risk"][13] == 0  # forecast/realised ignored
    assert plan["robust"][10] == 2 and plan["robust"][11] == 5
    assert plan["point"][12] == 4 and plan["point"][10] == 0
    assert plan["oracle"][13] == 6 and plan["oracle"][12] == 0
    assert set(plan["static_70"]) == {3} and CAP_LEVELS[3] == 0.7
    assert set(plan["no_action"]) == {0}


def test_poisson_upper_quantile_matches_known_values():
    assert poisson_upper_quantile(0.0) == 0
    assert poisson_upper_quantile(1.0) == 3  # P(X<=2)=0.920, P(X<=3)=0.981
    assert poisson_upper_quantile(5.0) == 9  # P(X<=8)=0.932, P(X<=9)=0.968
    # Large means stay finite (exp(-mean) underflows above ~745): normal approx ~ mean+1.645 sd
    assert abs(poisson_upper_quantile(2000.0) - (2000 + 1.645 * 2000**0.5)) < 3


def test_each_deferral_criterion_fires_on_its_own():
    risk = np.zeros((STEPS, N_LEVELS))
    assert deferral_reasons(risk, False, (0, 0.0), 0.05) == []
    infeasible = risk.copy()
    infeasible[30, :] = 0.2
    assert deferral_reasons(infeasible, False, (0, 0.0), 0.05) == ["D1_no_feasible_cap"]
    assert deferral_reasons(risk, False, (4, 1.0), 0.05) == [
        "D2_recent_violations_exceed_predicted"
    ]
    assert deferral_reasons(risk, False, (3, 1.0), 0.05) == []  # 3 is within Poisson(1)
    assert deferral_reasons(risk, True, (0, 0.0), 0.05) == ["D3_scenario_power_flow_failed"]


def test_outcome_counts_realised_violations_and_curtailed_energy():
    realised = np.full((STEPS, N_LEVELS, len(MARGINS)), -1.0)
    realised[40, :3, TRAFO] = 5.0  # overloaded unless k <= 0.7
    realised[41, :, 0] = np.nan  # a non-converged flow
    available = np.zeros((STEPS, 2))
    available[40] = [0.9, 0.5]
    rating = np.array([1.0, 1.0])
    levels = np.zeros(STEPS, dtype=int)
    levels[40] = 3  # k = 0.7

    result = outcome(realised, levels, available, rating)
    assert result["violation_steps"] == 1  # only the non-converged step
    assert result["nonconverged_steps"] == 1
    assert result["curtailed_mwh"] == pytest.approx((0.9 - 0.7) * 0.25)
    no_cap = outcome(realised, np.zeros(STEPS, dtype=int), available, rating)
    assert no_cap["violation_steps"] == 2 and no_cap["trafo_severity_pct_steps"] == 5.0


def synthetic_physics(days: list[int], deferral_day: int) -> dict[int, np.ndarray]:
    """Margins where the risk policy is reliable except on `deferral_day`."""
    physics = {}
    for day in days:
        margins = np.full((2 + WINDOW_DAYS, STEPS, N_LEVELS, len(MARGINS)), -1.0, np.float32)
        margins[REALISED, 50, :2, TRAFO] = 3.0  # realised overload unless k <= 0.8
        margins[2:, 50, :2, TRAFO] = 3.0  # every scenario agrees
        if day == deferral_day:
            margins[2:, 60, :, TRAFO] = 3.0  # infeasible step -> D1
        physics[day] = margins
    return physics


def test_selective_fallbacks_and_passports():
    days = list(range(40, 46))
    physics = synthetic_physics(days, deferral_day=43)
    arrays = {"sgen_p_mw": np.zeros((50, STEPS, 2))}
    outcomes, passports = run_decisions(physics, arrays, np.ones(2), days, 0.05)

    deferred = outcomes.set_index("day")["deferred"]
    assert deferred.tolist() == [False, False, False, True, False, False]
    row = outcomes.set_index("day").loc[43]
    assert row["reasons"] == "D1_no_feasible_cap"
    # On the deferred day, no_action fallback leaves the realised overload in place.
    assert row["selective_no_action__violation_steps"] == 1
    assert row["selective_robust__violation_steps"] == 0
    assert row["risk__violation_steps"] == 0

    # Passports hold origin information only: changing the realised day leaves them unchanged.
    altered = {day: margins.copy() for day, margins in physics.items()}
    altered[43][REALISED] = 50.0
    _, altered_passports = run_decisions(altered, arrays, np.ones(2), [43], 0.05)
    assert altered_passports[0] == next(p for p in passports if p["decision_id"].endswith("02-13"))
    assert passports[3]["decision"] == "defer"
    assert passports[3]["deferral_reasons"] == ["D1_no_feasible_cap"]


def test_calibration_scores_against_the_rolling_reference():
    days = [40]
    physics = {40: np.full((2 + WINDOW_DAYS, STEPS, N_LEVELS, len(MARGINS)), -1.0)}
    physics[40][2:16, 0, 0, TRAFO] = 1.0  # predicted risk 0.5 at step 0
    physics[40][REALISED, 0, 0, TRAFO] = 1.0  # and it happens
    reference = {d: np.zeros(STEPS) for d in range(40 - WINDOW_DAYS, 40)}
    result = calibration(physics, reference, days)

    assert result["brier"] == pytest.approx(0.25 / STEPS)
    assert result["brier_reference"] == pytest.approx(1.0 / STEPS)
    assert result["brier_skill_score"]["estimate"] == pytest.approx(0.75)
    assert result["ece"] == pytest.approx(0.5 / STEPS)


# --- Physics stage on the real network ------------------------------------------------


def test_day_physics_reuses_unbinding_caps_and_transformer_loading_is_not_monotone():
    from gridpulse.grid import absolute_profiles
    from gridpulse.grid_study import daily_arrays

    net = load_network()
    arrays = daily_arrays(absolute_profiles(net))
    day = 150  # 30 May 2016 (development period)
    sets = {name: arrays[name][day][None] for name in arrays}
    margins = day_physics(GridSolver(net), sets, np.zeros(len(net.storage)))[0]

    night, noon = 0, 11 * 4  # 00:00 and 11:00 UTC
    np.testing.assert_array_equal(margins[night], np.repeat(margins[night, :1], N_LEVELS, axis=0))
    trafo_noon = margins[noon, :, TRAFO]
    # Capping cuts reverse power flow until PV roughly balances local load; with k = 0
    # the transformer feeds the load again, so loading rises: the effect is not monotone.
    deepest_relief = int(trafo_noon.argmin())
    assert trafo_noon[deepest_relief] < trafo_noon[0]
    assert 0 < deepest_relief < N_LEVELS - 1
    assert trafo_noon[-1] > trafo_noon[deepest_relief]


def monitored_physics(days: list[int], failing_days: set[int]) -> dict[int, np.ndarray]:
    """The risk policy accepts k = 0.9 at step 50 (1 of 28 scenarios still violates);
    on `failing_days` the realised state violates anyway."""
    physics = {}
    for day in days:
        margins = np.full((2 + WINDOW_DAYS, STEPS, N_LEVELS, len(MARGINS)), -1.0, np.float32)
        margins[2:4, 50, 0, TRAFO] = 3.0  # risk 2/28 at k = 1.0
        margins[2, 50, 1, TRAFO] = 3.0  # risk 1/28 at k = 0.9 -> accepted
        if day in failing_days:
            margins[REALISED, 50, :2, TRAFO] = 3.0
        physics[day] = margins
    return physics


def test_calibration_monitor_defers_after_unpredicted_realised_violations():
    days = list(range(40, 46))
    physics = monitored_physics(days, failing_days={40, 41})
    arrays = {"sgen_p_mw": np.zeros((50, STEPS, 2))}
    outcomes, passports = run_decisions(physics, arrays, np.ones(2), days, 0.05)
    deferred = outcomes.set_index("day")["deferred"]

    # Day 40 has no history. P(Poisson(1/28) = 0) = 0.965 >= 0.95, so the 95 % quantile is 0
    # and the single unpredicted violation of day 40 already defers day 41 (amendment A1.4).
    assert not deferred.loc[40]
    assert deferred.loc[41:].all()
    assert set(outcomes.loc[outcomes["deferred"], "reasons"]) == {
        "D2_recent_violations_exceed_predicted"
    }
    monitor = passports[2]["calibration_monitor"]
    assert monitor["observed_violations_on_active_steps"] == 2
    assert monitor["predicted_violations_on_active_steps"] == pytest.approx(2 / 28)


def test_summary_signs_and_hypothesis_fields():
    days = list(range(40, 50))
    physics = monitored_physics(days, failing_days=set(days))
    arrays = {"sgen_p_mw": np.zeros((50, STEPS, 2))}
    outcomes, _ = run_decisions(physics, arrays, np.ones(2), days, 0.05, static_dev=5)
    summary = summarise(outcomes, {0.1: outcomes})

    totals = summary["totals"]
    assert totals["no_action"]["violation_steps"] == 10
    assert totals["static_dev"]["violation_steps"] == 0
    assert totals["oracle"]["excess_curtailment_vs_oracle_mwh"] == 0
    # risk accepted k = 0.9 and fails every day; point (no forecast violation) also fails
    h2 = summary["h2_risk_minus_point_violation_steps_per_day"]
    assert h2["estimate"] == pytest.approx(0.0)
    h3 = summary["h3_risk_active_steps"]
    assert (h3["active_steps"], h3["realised_violations"]) == (10, 10)
    assert summary["h4_selective"]["testable"] is True
    by_type = summary["h4_selective"]["by_day_type"]
    assert set(by_type) == {"deferred", "recommended"}


def test_static_dev_level_is_the_least_curtailment_without_development_violations():
    physics = {day: np.full((2, STEPS, N_LEVELS, len(MARGINS)), -1.0, np.float32) for day in (1, 2)}
    physics[1][REALISED, 10, :4, TRAFO] = 2.0  # violates unless k <= 0.6
    physics[2][REALISED, 20, :2, TRAFO] = 2.0
    assert static_dev_level(physics, [1, 2]) == 4
    physics[2][REALISED, 30, :, TRAFO] = 2.0  # no level is violation-free: fewest wins
    assert static_dev_level(physics, [1, 2]) == 4


def test_physics_cache_is_refused_when_it_was_made_by_other_code(tmp_path):
    (tmp_path / "manifest.json").write_text('{"fingerprint": "something-else"}')
    with pytest.raises(ValueError, match="different physics code"):
        physics_for([], tmp_path, workers=1)
    unmanaged = tmp_path / "old"
    unmanaged.mkdir()
    np.save(unmanaged / "day_040.npy", np.zeros(1))
    with pytest.raises(ValueError, match="no manifest"):
        physics_for([], unmanaged, workers=1)
