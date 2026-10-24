"""Unit tests of the Phase 9 s. 10 controls (`phase9_analysis.py`, controls 1-5 and A*).

Every test here runs on synthetic data: synthetic per-day counts, synthetic placements,
synthetic per-day means and synthetic truth. No power flow is solved, no cache is opened, no
sweep artefact is read and no real `vm` array is loaded. The four held-out networks of
registration s. 2 are never loaded.

Two things do come from the real tree, and neither is data: `gridpulse.noise_study.CONDITIONS`
supplies the registered noise values (s. 10 names that module, and the issue forbids retyping
them) and `gridpulse.sensing._stable_int` is part of the registered seed. Control 3's cache
loader (`control3_network`) is therefore covered only through its pure core,
`permute_labels` and `permuted_contrast`.
"""

from __future__ import annotations

import math

import numpy as np
import phase9_analysis as pa
import pytest

# --- synthetic fixtures --------------------------------------------------------------------


def spec(sigma_v: float = 0.01, sigma_bias: float = 0.0, missing: float = 0.0) -> dict:
    """A synthetic `noise_spec` result, so most tests need no `gridpulse` import."""
    return {
        "condition": "synthetic",
        "sigma_v": sigma_v,
        "sigma_bias": sigma_bias,
        "remote_missing": missing,
        "remote_delay_days": 1,
        "sigma_tot": math.sqrt(sigma_v**2 + sigma_bias**2),
        "threshold_sigma_key": "0.01",
        "source": "synthetic",
    }


def toy_arrays(days: int = 5, buses: int = 3, daylight: int = 40) -> dict:
    """A synthetic s. 7 artefact array mapping with known, constant per-day counts."""
    return {
        "day_index": np.arange(days, dtype=np.int32),
        "bus_index": np.arange(buses, dtype=np.int32),
        "n_daylight_valid": np.full(days, daylight, dtype=np.int16),
        "n_night_valid": np.full(days, pa.STEPS - daylight, dtype=np.int16),
        "n_daylight_steps": np.full(days, daylight, dtype=np.int16),
        "n_night_steps": np.full(days, pa.STEPS - daylight, dtype=np.int16),
        "dmean_daylight": np.zeros((days, buses), dtype=np.float32),
        "dmean_night": np.zeros((days, buses), dtype=np.float32),
        "failed_truth": np.zeros(days, dtype=np.int16),
        "nan_nominal": np.zeros(days, dtype=np.int16),
    }


COUNTS_DAY = np.array([16, 64, 40], dtype=int)
COUNTS_NIGHT = np.array([80, 32, 56], dtype=int)

NAMED_TWO = pa.NAMED_RULES[:2]
RANDOM_TWO = pa.RANDOM_RULES[:2]
TOY_RULES = {
    NAMED_TWO[0]: [0, 1, 2, 3],
    NAMED_TWO[1]: [4, 5, 6, 7],
    RANDOM_TWO[0]: [0, 2, 4, 6],
    RANDOM_TWO[1]: [7, 5, 3, 1],
}
TOY_DOWNSTREAM = {0: [0, 1, 2, 3], 1: [4, 5, 6, 7]}


@pytest.fixture(scope="module")
def selftest_setup():
    """`selftest_inputs` plus its `meter_days` axis, built once for the slower tests."""
    setup = pa.selftest_inputs()
    return setup, pa.meter_days([setup["arrays"]], setup["retained"])


# --- s. 10: the noise simulator ------------------------------------------------------------


def test_the_per_day_noise_variance_is_sigma_squared_over_the_valid_step_count():
    rng = np.random.default_rng(7)
    draws = pa.draw_replicate(rng, spec(sigma_v=0.01), COUNTS_DAY, COUNTS_NIGHT, 20_000)

    for row, n in enumerate(COUNTS_DAY):
        assert draws["day"][row].var() == pytest.approx(0.01**2 / n, rel=0.05)
    for row, n in enumerate(COUNTS_NIGHT):
        assert draws["night"][row].var() == pytest.approx(0.01**2 / n, rel=0.05)
    assert draws["day"].mean() == pytest.approx(0.0, abs=1e-4)


def test_the_sqrt_2_variant_doubles_the_per_day_variance_on_both_legs():
    rng = np.random.default_rng(7)
    draws = pa.draw_replicate(
        rng, spec(sigma_v=0.01), COUNTS_DAY, COUNTS_NIGHT, 20_000, both_legs=True
    )

    assert draws["both_legs"] is True
    for row, n in enumerate(COUNTS_DAY):
        assert draws["day"][row].var() == pytest.approx(2.0 * 0.01**2 / n, rel=0.05)
    for row, n in enumerate(COUNTS_NIGHT):
        assert draws["night"][row].var() == pytest.approx(2.0 * 0.01**2 / n, rel=0.05)


def test_the_sqrt_2_variant_reuses_the_measured_leg_draws_before_adding_the_second_leg():
    one = pa.draw_replicate(np.random.default_rng(3), spec(), COUNTS_DAY, COUNTS_NIGHT, 4)
    both = pa.draw_replicate(
        np.random.default_rng(3), spec(), COUNTS_DAY, COUNTS_NIGHT, 4, both_legs=True
    )

    # reading R-m: the second leg is subtracted from the first, so the two differ everywhere
    assert not np.allclose(one["day"], both["day"])
    assert np.abs(both["day"]).sum() > 0.0


def test_a_day_is_lost_with_the_registered_probability():
    rng = np.random.default_rng(11)
    draws = pa.draw_replicate(
        rng, spec(missing=pa.REMOTE_MISSING), np.full(20, 40), np.full(20, 56), 5_000
    )

    assert draws["survives"].shape == (20, 5_000)
    assert 1.0 - draws["survives"].mean() == pytest.approx(pa.REMOTE_MISSING, abs=0.004)


def test_the_static_bias_cancels_in_k_and_does_not_cancel_in_m():
    rng = np.random.default_rng(5)
    draws = pa.draw_replicate(
        rng, spec(sigma_v=0.0, sigma_bias=0.01), COUNTS_DAY, COUNTS_NIGHT, 400
    )
    stats = pa.replicate_statistics(draws)

    assert np.allclose(stats["k"], 0.0)  # the bias adds equally to both means (s. 10)
    assert np.allclose(stats["m"], draws["bias"])
    assert np.allclose(stats["night"], draws["bias"])
    assert np.abs(stats["m"]).max() > 0.0
    assert draws["bias"].std() == pytest.approx(0.01, rel=0.1)


def test_a_meter_that_loses_every_day_has_no_reading_and_raises_no_alarm():
    rng = np.random.default_rng(2)
    draws = pa.draw_replicate(rng, spec(missing=1.0), COUNTS_DAY, COUNTS_NIGHT, 3)
    stats = pa.replicate_statistics(draws)

    assert not np.isfinite(stats["k"]).any()
    assert stats["days_used"].tolist() == [0, 0, 0]
    mask, _ = pa.config_matrix({"r": [0, 1, 2]}, [0, 1, 2], 2)
    assert pa.family_alarm(stats["k"], mask, 1e-9).tolist() == [False]


def test_the_simulator_refuses_a_day_without_a_valid_daylight_or_night_step():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError, match="valid daylight and a valid night step"):
        pa.draw_replicate(rng, spec(), np.array([0, 40]), np.array([56, 56]), 2)
    with pytest.raises(ValueError, match="differ in shape"):
        pa.draw_replicate(rng, spec(), np.array([40]), np.array([56, 56]), 2)


# --- s. 10: the day axis, the 1-day delay and reading R-b ----------------------------------


def test_the_one_day_delay_removes_the_last_retained_day():
    counts = pa.meter_days([toy_arrays(days=5)], [0, 1, 2, 3, 4])

    assert counts["days"] == [0, 1, 2, 3]
    assert counts["delay_removed_day"] == 4
    assert counts["simulated_days"] == 4
    assert counts["retained_days"] == 5
    assert counts["all_daylight_steps_valid"] is True


def test_the_delay_removes_the_last_retained_day_and_not_the_last_scored_day():
    counts = pa.meter_days([toy_arrays(days=5)], [0, 2, 3])

    assert counts["days"] == [0, 2]
    assert counts["delay_removed_day"] == 3


def test_a_day_without_a_valid_step_is_dropped_before_the_delay():
    arrays = toy_arrays(days=6)
    arrays["n_daylight_valid"][2] = 0
    arrays["dmean_night"][4, 1] = np.nan

    counts = pa.meter_days([arrays], list(range(6)))

    assert counts["days"] == [0, 1, 3]
    assert counts["dropped_not_usable"] == [2, 4]
    assert counts["delay_removed_day"] == 5


def test_the_day_axis_is_the_intersection_over_the_artefacts_and_keeps_the_first_s_counts():
    left, right = toy_arrays(days=5), toy_arrays(days=5, daylight=20)
    right["n_night_valid"][1] = 0

    counts = pa.meter_days([left, right], list(range(5)))

    assert counts["days"] == [0, 2, 3]
    assert counts["artefacts_intersected"] == 2
    assert counts["n_daylight_valid"].tolist() == [40, 40, 40]  # the first artefact's (R-o)


def test_the_day_axis_refuses_artefacts_on_different_scored_day_axes():
    other = toy_arrays(days=5)
    other["day_index"] = np.arange(10, 15, dtype=np.int32)

    with pytest.raises(RuntimeError, match="do not share one scored-day axis"):
        pa.meter_days([toy_arrays(days=5), other], list(range(5)))


def test_the_day_axis_refuses_when_nothing_survives_the_delay():
    with pytest.raises(RuntimeError, match="1-day-delay"):
        pa.meter_days([toy_arrays(days=5)], [3])


# --- s. 10: the registered seed ------------------------------------------------------------


def test_the_control_seed_is_exactly_the_registered_seed_sequence():
    from gridpulse import sensing as sn

    expected = np.random.default_rng(np.random.SeedSequence([
        20261023, sn._stable_int("1-LV-semiurb4--2-sw"), sn._stable_int("realistic"),
        sn._stable_int("control_2_fa"), 3,
    ]))  # fmt: skip
    got = pa.control_rng("1-LV-semiurb4--2-sw", "realistic", "control_2_fa", 3)

    assert pa.SEED_ROOT == 20261023
    assert got.standard_normal(8).tolist() == expected.standard_normal(8).tolist()


def test_the_seed_is_deterministic_and_separates_every_registered_coordinate():
    def stream(network="n", condition="realistic", control=pa.CONTROL1, index=0):
        return pa.control_rng(network, condition, control, index).standard_normal(6).tolist()

    assert stream() == stream()
    assert stream() != stream(network="m")
    assert stream() != stream(condition="sigma_0.02")
    assert stream() != stream(control=pa.CONTROL1_SQRT2)
    assert stream() != stream(index=1)


# --- s. 10: the conditions, read from `noise_study` ----------------------------------------


def test_the_conditions_are_read_from_noise_study_and_never_retyped():
    from gridpulse import noise_study as nst

    assert pa.CONTROL_CONDITIONS == (
        "realistic", "sigma_0.005", "sigma_0.02", "biased_meters_matched",
    )  # fmt: skip
    for condition in pa.CONTROL_CONDITIONS:
        model = nst.CONDITIONS[condition]
        got = pa.noise_spec(condition)
        assert got["sigma_v"] == float(model.sigma_v_remote)
        assert got["sigma_bias"] == float(model.sigma_bias_remote)
        assert got["remote_missing"] == pa.REMOTE_MISSING
        assert got["remote_delay_days"] == 1
        assert got["sigma_tot"] == pytest.approx(
            math.hypot(model.sigma_v_remote, model.sigma_bias_remote)
        )

    assert pa.noise_spec("realistic")["sigma_tot"] == 0.01
    assert pa.noise_spec("sigma_0.005")["sigma_v"] == 0.005
    assert pa.noise_spec("sigma_0.02")["sigma_v"] == 0.02
    matched = pa.noise_spec("biased_meters_matched")
    assert (matched["sigma_v"], matched["sigma_bias"]) == (0.002, 0.0098)
    assert matched["threshold_sigma_key"] == "0.01"  # reading R-n
    assert matched["sigma_tot"] == pytest.approx(0.0100020, abs=1e-7)


def test_an_unregistered_condition_is_refused():
    with pytest.raises(KeyError, match="noise_study"):
        pa.noise_spec("not_a_condition")


# --- s. 8/s. 10: the configuration matrix and the family-wise alarm ------------------------


def test_the_configuration_matrix_is_the_first_k_buses_of_each_rule():
    mask, names = pa.config_matrix(TOY_RULES, list(range(8)), 2)

    assert names == sorted(TOY_RULES)
    row = names.index(RANDOM_TWO[1])
    assert mask[row].tolist() == [False] * 5 + [True, False, True]  # buses 7 and 5
    assert mask.sum(axis=1).tolist() == [2, 2, 2, 2]


def test_the_configuration_matrix_refuses_a_meter_off_the_lv_buses():
    with pytest.raises(RuntimeError, match="not an LV bus"):
        pa.config_matrix({"r": [99]}, [0, 1], 1)


def test_the_family_alarm_is_the_maximum_over_the_configuration():
    mask, names = pa.config_matrix({"a": [0, 1], "b": [2, 3]}, [0, 1, 2, 3], 2)
    k_hat = np.array([0.0, 2.0, 0.5, 0.5])

    assert names == ["a", "b"]
    assert pa.family_alarm(k_hat, mask, 1.0).tolist() == [True, False]
    assert pa.family_alarm(np.stack([k_hat, -k_hat]), mask, 1.0).tolist() == [
        [True, False], [True, False],
    ]  # fmt: skip
    assert pa.family_alarm(k_hat, mask, 2.0).tolist() == [True, False]  # ">=" is inclusive


# --- s. 10 control 1 and s. 9 R7 -----------------------------------------------------------


@pytest.fixture(scope="module")
def control1_realistic(selftest_setup):
    setup, counts = selftest_setup
    return pa.control1_network(
        setup["network"], setup["buses"], setup["rules"], counts, setup["thresholds"],
        replicates=1_200, conditions=("realistic",),
    )  # fmt: skip


def test_control_1_recovers_the_nominal_family_wise_alpha_at_exact_counts(control1_realistic):
    arms = control1_realistic["per_condition"]["realistic"]["variants"]["measured_leg"]["arms"]

    assert set(arms) == {"F_C_real"}  # the matched arm is for `biased_meters_matched` only
    for k in pa.K_GRID:
        pooled = arms["F_C_real"][f"K_{k}"]["pooled_over_rules"]
        assert pooled["rate"] == pytest.approx(pa.FAMILY_ALPHA, abs=0.02)
        assert pooled["trials"] == 1_200 * len(control1_realistic["rule_names"])


def test_the_sqrt_2_variant_inflates_the_control_1_rate(control1_realistic):
    variants = control1_realistic["per_condition"]["realistic"]["variants"]

    for k in pa.K_GRID:
        measured = variants["measured_leg"]["arms"]["F_C_real"][f"K_{k}"]
        inflated = variants["sqrt2"]["arms"]["F_C_real"][f"K_{k}"]
        assert inflated["threshold_pu"] == measured["threshold_pu"]
        assert (
            inflated["pooled_over_rules"]["rate"]
            > measured["pooled_over_rules"]["rate"] + 0.05
        )
    assert variants["sqrt2"]["control_seed_string"] == pa.CONTROL1_SQRT2
    assert variants["measured_leg"]["control_seed_string"] == pa.CONTROL1


def test_control_1_adds_the_matched_floor_arm_for_the_matched_condition_only(selftest_setup):
    setup, counts = selftest_setup
    report = pa.control1_network(
        setup["network"], setup["buses"], setup["rules"], counts, setup["thresholds"],
        replicates=200, conditions=("sigma_0.02", pa.MATCHED_CONDITION),
    )  # fmt: skip

    assert set(report["per_condition"]["sigma_0.02"]["variants"]["measured_leg"]["arms"]) == {
        "F_C_real"
    }
    matched = report["per_condition"][pa.MATCHED_CONDITION]["variants"]["measured_leg"]
    assert set(matched["arms"]) == {"F_C_real", "F_C_matched"}
    # the bias cancels in k, so the F_C,real arm is far below the F_C,matched arm (s. 14)
    assert (
        matched["arms"]["F_C_real"]["K_1"]["pooled_over_rules"]["rate"]
        < matched["arms"]["F_C_matched"]["K_1"]["pooled_over_rules"]["rate"]
    )
    assert report["per_condition"]["sigma_0.02"]["threshold_sigma_key"] == "0.02"


def r7_block(successes: int, trials: int = 2_000) -> dict:
    """A minimal control-1-shaped block carrying one rate in every R7 cell."""
    record = pa.rate_record(successes, trials)
    per_k = {f"K_{k}": {"per_rule": {"rule_a": record}} for k in pa.K_GRID}
    return {
        "net": {
            "per_condition": {
                "realistic": {"variants": {"measured_leg": {"arms": {"F_C_real": per_k}}}}
            }
        }
    }


def test_r7_holds_exactly_when_every_wilson_lower_bound_is_at_most_the_limit():
    low_rate = pa.wilson(100, 2_000)["low"]  # a 0.05 rate: the bound sits below 0.05
    high_rate = pa.wilson(160, 2_000)["low"]  # a 0.08 rate: the bound sits above 0.05
    assert low_rate <= pa.R7_LIMIT < high_rate

    holding = pa.r7_verdict(r7_block(100))
    failing = pa.r7_verdict(r7_block(160))

    assert holding["holds"] is True
    assert holding["cells"] == len(pa.K_GRID)
    assert holding["failing_cells"] == []
    assert failing["holds"] is False
    assert len(failing["failing_cells"]) == len(pa.K_GRID)
    assert failing["failing_cells"][0]["rule"] == "rule_a"
    assert failing["limit"] == 0.05


def test_r7_is_undefined_without_a_single_cell():
    assert pa.r7_verdict({})["holds"] is None


# --- s. 10 control 2: the shapes, the signs and the crossing rule --------------------------


def test_the_square_shape_has_a_per_day_daylight_mean_of_one():
    assert pa.shape_day_means("square", [40, 20, 1]).tolist() == [1.0, 1.0, 1.0]


def test_the_sinusoid_per_day_mean_uses_the_step_order_within_the_day():
    assert pa.sinusoid_day_mean(1) == pytest.approx(1.0)
    assert pa.sinusoid_day_mean(2) == pytest.approx(math.sin(math.pi / 4))
    expected = float(np.sin(np.pi * (np.arange(5) + 0.5) / 5).mean())
    assert pa.shape_day_means("sinusoid", [5])[0] == pytest.approx(expected)
    # the midpoint rule for the mean of sin over [0, pi], which is 2 / pi
    assert pa.sinusoid_day_mean(96) == pytest.approx(2.0 / math.pi, rel=1e-4)
    assert pa.sinusoid_day_mean(40) < 1.0


def test_an_unknown_shape_and_an_empty_day_are_refused():
    with pytest.raises(ValueError, match="not an s. 10 bias shape"):
        pa.shape_day_means("triangle", [40])
    with pytest.raises(ValueError, match="at least one daylight step"):
        pa.sinusoid_day_mean(0)


def test_the_adverse_sign_is_minus_the_sign_of_k_and_leaves_a_zero_meter_unbiased():
    truth_k = np.array([[1e-4, -2e-4, 0.0]])

    assert pa.adverse_signs(truth_k).tolist() == [[-1.0, 1.0, 0.0]]


def test_the_crossing_is_interpolated_log_linearly_between_the_bracketing_points():
    got = pa.interpolate_crossing([0.0, 1.0, 2.0, 4.0], [0.01, 0.02, 0.04, 0.08],
                                  0.03, "above", 1.0)  # fmt: skip

    assert got["record"] == "interpolated"
    assert got["not_reached"] is False
    assert got["A_star_pu"] == pytest.approx(math.sqrt(2.0))
    assert got["A_star_over_sigma_tot"] == pytest.approx(math.sqrt(2.0))
    assert got["bracket"] == {"A_low_pu": 1.0, "A_high_pu": 2.0,
                              "rate_low": 0.02, "rate_high": 0.04}  # fmt: skip


def test_a_crossing_that_is_not_bracketed_at_the_bottom_is_the_typed_low_record():
    already = pa.interpolate_crossing([0.0, 1.0], [0.06, 0.07], 0.05, "above", 1.0)
    first_positive = pa.interpolate_crossing([0.0, 1.0, 2.0], [0.01, 0.06, 0.07],
                                             0.05, "above", 1.0)  # fmt: skip

    assert already["record"] == "<= 0.003 sigma"
    assert already["A_star_pu"] is None
    assert "already holds at A = 0" in already["note"]
    assert first_positive["record"] == "<= 0.003 sigma"
    assert first_positive["crossed_at_grid_point_pu"] == 1.0
    assert "log A cannot interpolate" in first_positive["note"]


def test_a_crossing_reached_at_no_grid_point_is_the_typed_not_reached_record():
    got = pa.interpolate_crossing([0.0, 1.0, 2.0], [0.01, 0.02, 0.03], 0.05, "above", 1.0)

    assert got["record"] == "> 0.3 sigma"
    assert got["not_reached"] is True
    assert got["A_star_pu"] is None
    assert "not reached" in got["note"]


def test_the_below_direction_is_the_a_star_cov_rule():
    got = pa.interpolate_crossing([0.0, 1.0, 10.0], [1.0, 1.0, 0.4], 0.5, "below", 0.01)

    assert got["record"] == "interpolated"
    assert 1.0 < got["A_star_pu"] < 10.0
    assert got["A_star_over_sigma_tot"] == pytest.approx(got["A_star_pu"] / 0.01)


def test_the_crossing_refuses_a_bad_grid_or_direction():
    with pytest.raises(ValueError, match="one rate per amplitude"):
        pa.interpolate_crossing([0.0, 1.0], [0.1], 0.05, "above", 1.0)
    with pytest.raises(ValueError, match="not a crossing direction"):
        pa.interpolate_crossing([0.0, 1.0], [0.1, 0.2], 0.05, "sideways", 1.0)


def test_a_star_fa_rises_with_the_amplitude_and_reports_a_typed_crossing(selftest_setup):
    setup, counts = selftest_setup
    report = pa.control2_fa_network(
        setup["network"], setup["buses"], setup["rules"], counts, setup["thresholds"],
        replicates=150, conditions={"0.01": "realistic"},
    )  # fmt: skip

    block = report["per_sigma_tot"]["0.01"]["per_shape"]["square"]["per_K"]["K_1"]
    rates = [point["rate"] for point in block["per_grid_point"].values()]
    assert rates[0] == pytest.approx(pa.FAMILY_ALPHA, abs=0.04)  # A = 0 is control 1
    assert rates[-1] > rates[0]  # 0.3 sigma_tot swamps the z_1 * F_C,real floor
    assert block["A_star_fa"]["record"] in ("interpolated", "<= 0.003 sigma", "> 0.3 sigma")
    assert report["sign"].startswith("random only")
    assert list(report["grid_A_over_sigma_tot"]) == list(pa.A_OVER_SIGMA)
    assert set(report["per_sigma_tot"]["0.01"]["per_shape"]) == {"square", "sinusoid"}


def test_a_star_cov_counts_the_intersecting_pairs_and_reports_both_sign_variants(
    selftest_setup,
):
    setup, counts = selftest_setup
    lines = sorted(TOY_DOWNSTREAM)
    truth = np.zeros((len(lines), counts["simulated_days"], len(setup["buses"])))
    for row, line in enumerate(lines):
        truth[row][:, TOY_DOWNSTREAM[line]] = 1e-3
    report = pa.control2_cov_network(
        setup["network"], setup["buses"], setup["rules"], counts, setup["thresholds"],
        truth, truth.mean(axis=1), lines, TOY_DOWNSTREAM,
        replicates=20, conditions={"0.01": "realistic"},
    )  # fmt: skip

    per_sign = report["per_sigma_tot"]["0.01"]["per_shape"]["square"]["per_sign"]
    assert set(per_sign) == {"random", "adverse"}
    assert per_sign["random"]["primary"] is True
    block = per_sign["adverse"]["per_K"]["K_1"]
    assert block["pairs_in_population"] == 4  # two cables, two intersecting rules each
    assert block["per_grid_point"]["0"]["trials"] == 4 * 20
    assert block["coverage_at_A_0"] == pytest.approx(1.0)  # 1e-3 is far above the floor
    assert block["target_coverage"] == pytest.approx(0.5)
    # the adverse sign cancels k near A ~ |k|, so the halving is reached inside the grid
    assert block["A_star_cov"]["record"] == "interpolated"
    assert block["A_star_cov"]["direction"] == "below"


def test_a_star_cov_refuses_a_truth_array_of_the_wrong_shape(selftest_setup):
    setup, counts = selftest_setup
    with pytest.raises(ValueError, match="the truth contrast is"):
        pa.control2_cov_network(
            setup["network"], setup["buses"], setup["rules"], counts, setup["thresholds"],
            np.zeros((1, counts["simulated_days"], 3)), np.zeros((1, 3)), [0],
            {0: [0]}, replicates=1, conditions={"0.01": "realistic"},
        )  # fmt: skip


# --- s. 10 control 3: permuted day/night labels --------------------------------------------


def test_permuting_the_labels_preserves_the_day_s_daylight_count():
    rng = np.random.default_rng(1)
    daylight = np.array([True] * 40 + [False] * 56)

    for _ in range(20):
        permuted = pa.permute_labels(daylight, rng)
        assert permuted.sum() == 40
        assert permuted.size == 96
    assert not np.array_equal(pa.permute_labels(daylight, rng), daylight)


def test_the_permuted_contrast_preserves_the_counts_and_vanishes_on_a_flat_day():
    days, steps, buses = 3, 96, 2
    delta = np.tile(np.array([[1.0, -2.0]]), (days, steps, 1))
    daylight = np.zeros((days, steps), dtype=bool)
    daylight[:, :40] = True
    rng = np.random.default_rng(4)

    out = pa.permuted_contrast(delta, daylight, np.ones((days, steps), bool), rng, 25)

    assert out["k_perm"].shape == (25, buses)
    assert out["counts_preserved"] is True
    assert out["daylight_labels_observed"] == days * 40
    assert set(out["daylight_labels_per_permutation"]) == {days * 40}
    assert np.allclose(out["k_perm"], 0.0)  # a flat Delta cancels under any labelling
    assert out["days_dropped_per_permutation"] == [0] * 25


def test_a_day_with_a_single_valid_step_drops_from_every_permutation():
    days, steps = 2, 96
    delta = np.zeros((days, steps, 1))
    daylight = np.zeros((days, steps), dtype=bool)
    daylight[:, :40] = True
    valid = np.ones((days, steps), dtype=bool)
    valid[1, 1:] = False  # day 1 keeps one valid step: it can never have both labels

    out = pa.permuted_contrast(delta, daylight, valid, np.random.default_rng(6), 10)

    assert out["days_dropped_per_permutation"] == [1] * 10


def test_the_permuted_contrast_recovers_a_zero_mean_and_reports_its_distribution():
    days, steps, buses = 12, 96, 3
    rng = np.random.default_rng(8)
    delta = rng.normal(0.0, 1e-4, size=(days, steps, buses))
    daylight = np.zeros((days, steps), dtype=bool)
    daylight[:, :40] = True
    out = pa.permuted_contrast(
        delta, daylight, np.ones((days, steps), bool), np.random.default_rng(9), 40
    )
    setup = pa.selftest_inputs()
    distribution = pa.control3_distribution(
        out["k_perm"], list(range(buses)), setup["thresholds"], len(pa.SELFTEST_BUSES)
    )

    assert distribution["permutations"] == 40
    assert distribution["max_abs_mean_k_perm_pu"]["max"]["value"] < 1e-4
    assert distribution["max_abs_mean_k_perm_pu"]["argmax_bus"] in range(buses)
    for sigma in pa.SIGMA_CO_PRIMARY:
        per_sigma = distribution["per_sigma_tot"][f"{sigma:g}"]
        assert per_sigma["K_all"] == len(pa.SELFTEST_BUSES)
        assert per_sigma["exceeding_permutations"]["trials"] == 40


def test_the_permuted_contrast_refuses_mismatched_shapes():
    with pytest.raises(ValueError, match="shapes do not match"):
        pa.permuted_contrast(
            np.zeros((2, 96, 1)), np.zeros((3, 96), bool), np.ones((2, 96), bool),
            np.random.default_rng(0), 2,
        )  # fmt: skip


# --- s. 10 controls 4 and 5 ----------------------------------------------------------------


def toy_entries(k_values: dict, buses) -> dict:
    """Entries in `_rule_inputs` form: m and night are opposite in sign, so S_detect is the
    set of buses whose |k| clears the threshold."""
    return {
        line: {
            "m": np.asarray(values, dtype=float),
            "night": -np.asarray(values, dtype=float),
            "k": np.asarray(values, dtype=float),
            "buses": [int(b) for b in buses],
            "downstream": sorted(TOY_DOWNSTREAM[line]),
        }
        for line, values in k_values.items()
    }


def test_control_4_scores_the_own_downstream_set_against_every_other_candidate():
    buses = list(range(8))
    entries = toy_entries(
        {0: [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0],
         1: [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]},
        buses,
    )  # fmt: skip

    got = pa.control4_network(entries, TOY_DOWNSTREAM, 0.5, 0.5)

    assert got["cables"] == 2
    assert got["per_cable"]["0"]["S_detect"] == [0, 1, 2, 3]
    assert got["per_cable"]["0"]["jaccard_own_downstream"] == pytest.approx(1.0)
    assert got["per_cable"]["0"]["jaccard_other_max"] == pytest.approx(0.0)
    assert got["per_cable"]["0"]["own_is_the_best_match"] is True
    assert got["per_cable"]["0"]["others_at_or_above_0.8"] == []
    assert got["cables_whose_own_downstream_is_the_best_match"] == 2
    assert got["pooled_other_pairs_at_or_above_0.8"]["successes"] == 0
    assert got["pooled_other_pairs_at_or_above_0.8"]["trials"] == 2


def test_control_4_reports_a_cable_whose_detection_set_matches_another_cable():
    buses = list(range(8))
    # cable 0's detections all sit on downstream(1): topology luck, not localisation
    entries = toy_entries({0: [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]}, buses)

    got = pa.control4_network(entries, TOY_DOWNSTREAM, 0.5, 0.5)

    assert got["per_cable"]["0"]["jaccard_own_downstream"] == pytest.approx(0.0)
    assert got["per_cable"]["0"]["jaccard_other_max"] == pytest.approx(1.0)
    assert got["per_cable"]["0"]["others_at_or_above_0.8"] == [1]
    assert got["per_cable"]["0"]["own_is_the_best_match"] is False


def test_control_5_compares_the_random_rules_with_the_named_rules():
    buses = list(range(8))
    setup = pa.selftest_inputs()
    # only the named rules' first bus carries a detectable contrast
    entries = toy_entries({0: [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]}, buses)
    entries[1] = dict(entries[0], downstream=sorted(TOY_DOWNSTREAM[1]))
    thresholds = setup["thresholds"]["0.01"]

    got = pa.control5_network(entries, TOY_RULES, thresholds)

    block = got["per_K"]["K_1"]
    assert set(block["families"]) == {"named", "random"}
    assert block["families"]["named"]["rules"] == 2
    assert block["families"]["random"]["rules"] == 2
    assert block["families"]["named"]["coverage"]["rate"] == pytest.approx(1.0)
    assert block["random_minus_named"] is not None
    assert block["families"]["named"]["pairs"] == 4  # two cables x two named rules


# --- s. 10: the wiring, and the `controls-selftest` subcommand -----------------------------


def toy_inputs(code: str, days: int = 40) -> dict:
    """A synthetic Stage 1 `inputs` mapping for one network with two candidate cables."""
    buses = list(range(8))
    retention = {
        "D_ret": days,
        "D_eff": (1.0 - pa.REMOTE_MISSING) * days,
        "n_day_median": 40.0,
        "n_night_median": float(pa.STEPS - 40),
        "retained": list(range(days)),
    }
    return {
        "networks": {
            code: {
                "network": code,
                "role": "sweep (W6, W8, W9)",
                "lv_buses": buses,
                "K_all": len(buses),
                "local_line": 0,
                "placement_rules": {"buses": {n: list(b) for n, b in TOY_RULES.items()}},
                "downstream": {str(line): below for line, below in TOY_DOWNSTREAM.items()},
                "days": {"retention_primary": retention},
                "thresholds": pa.threshold_grid(retention, len(buses)),
            }
        }
    }


def toy_stats(buses: int = 8) -> dict:
    """A `run_statistics`-shaped bundle of zeros: truth = nominal at every bus."""
    zeros = np.zeros(buses)
    return {which: {"mean": zeros, "median": zeros} for which in ("m", "night", "k")}


def test_controls_fills_every_registered_section_and_the_r7_verdict(monkeypatch):
    code = "synthetic-network"
    monkeypatch.setattr(pa, "SWEEP_NETWORKS", (code,))
    inputs = toy_inputs(code)
    arrays = toy_arrays(days=40, buses=8)
    loaded = {
        (code, "W6", "E-R", 1.5, line): {"stats": toy_stats(), "arrays": arrays}
        for line in TOY_DOWNSTREAM
    }

    got = pa.controls(
        inputs["networks"] and inputs, loaded, control1_replicates=20, fa_replicates=5,
        cov_replicates=5, include_control3=False,
    )  # fmt: skip

    assert set(got) >= {"control_1", "control_2_A_star_fa", "control_2_A_star_cov",
                        "control_3", "control_4", "control_5", "R7", "readings",
                        "noise_model"}  # fmt: skip
    assert got["control_3"] is None  # not computed in this call: it would read the caches
    assert set(got["control_1"]) == {code}
    assert set(got["noise_model"]["conditions"]) == set(pa.CONTROL_CONDITIONS)
    assert sorted(got["readings"]) == [f"R-{letter}" for letter in "ijklmnopqr"]
    assert got["R7"]["rule"] == "R7"
    assert got["R7"]["cells"] == len(pa.CONTROL_CONDITIONS) * len(pa.K_GRID) * len(TOY_RULES)
    assert set(got["control_4"][code]) == {f"{s:g}" for s in pa.SIGMA_CO_PRIMARY}
    assert got["per_network"][code] == {"cables": 2, "day_axis": 39}


def test_controls_refuses_a_network_without_its_registered_cable_s_artefact(monkeypatch):
    code = "synthetic-network"
    monkeypatch.setattr(pa, "SWEEP_NETWORKS", (code,))
    loaded = {
        (code, "W6", "E-R", 1.5, 1): {"stats": toy_stats(),
                                      "arrays": toy_arrays(days=40, buses=8)}  # fmt: skip
    }

    with pytest.raises(RuntimeError, match="registered cable 0 has no W6 artefact"):
        pa.controls(toy_inputs(code), loaded, include_control3=False)


def test_the_selftest_inputs_are_synthetic_and_carry_the_known_counts():
    setup = pa.selftest_inputs()

    assert setup["network"] == "synthetic-selftest"
    assert setup["retention"]["D_ret"] == pa.SELFTEST_DAYS
    assert setup["arrays"]["n_daylight_valid"].tolist() == [pa.SELFTEST_DAYLIGHT] * 120
    assert setup["arrays"]["n_night_valid"].tolist() == [pa.SELFTEST_NIGHT] * 120
    assert not np.asarray(setup["arrays"]["dmean_daylight"]).any()  # truth = nominal
    assert not np.asarray(setup["arrays"]["dmean_night"]).any()


def test_the_controls_selftest_holds_and_touches_no_real_data():
    got = pa.controls_selftest(replicates=600)

    assert got["holds"] is True
    assert got["failures"] == []
    assert got["touches_real_data"] is False
    assert got["simulated_days"] == pa.SELFTEST_DAYS - 1  # the 1-day delay
    assert len(got["checks"]) == len(pa.CONTROL_CONDITIONS) * len(pa.K_GRID)
    assert got["expected_inflation_from_the_1_day_delay"] == pytest.approx(
        math.sqrt(120 / 119)
    )
    for check in got["checks"]:
        assert check["sqrt2_inflates"] is True
        if check["condition"] == pa.MATCHED_CONDITION:
            assert check["arm"] == "F_C_matched"
            assert check["bias_cancellation_keeps_F_C_real_at_or_below_alpha"] is True
        else:
            assert check["arm"] == "F_C_real"


def test_the_controls_selftest_subcommand_exits_zero(capsys):
    assert pa.main(["controls-selftest", "--replicates", "400"]) == 0
    captured = capsys.readouterr()
    assert "controls-selftest PASS" in captured.err
    assert '"selftest"' in captured.out
