"""Synthetic tests of `analysis/phase9_followup/common_mode.py`.

Nothing here reads a network, a cached state, a W6 artefact, a Phase 9 result or `outputs/`;
every input is a toy array. The whole file is meant to stay well under 30 s.
"""

from __future__ import annotations

import json

import calibration as cal
import common_mode as cm
import numpy as np
import pytest

STEPS = 96


# --- toy fixtures ------------------------------------------------------------------------------


def toy_v_days(days: int = 12, n_daylight: int = 40) -> np.ndarray:
    n_day = np.full(days, float(n_daylight))
    n_night = np.full(days, float(STEPS - n_daylight))
    return 1.0 / n_day + 1.0 / n_night


def toy_counts(days: int = 12, n_daylight: int = 40) -> dict:
    return {"n_daylight_valid": np.full(days, n_daylight, dtype=int),
            "n_night_valid": np.full(days, STEPS - n_daylight, dtype=int),
            "simulated_days": days}  # fmt: skip


# --- 1. a common-mode shift cancels exactly in the referenced contrast --------------------------


def test_a_common_mode_shift_cancels_in_the_referenced_contrast():
    """Adding any per-day quantity to every bus of a day leaves `cm.reference` unchanged (to
    double rounding), and the busbar's own referenced value is exactly zero."""
    rng = np.random.default_rng(11)
    base = rng.standard_normal((9, 5))
    shift = rng.standard_normal((9, 1)) * 0.02  # one common-mode value per day, every bus
    for column in range(5):
        plain = cm.reference(base, column)
        shifted = cm.reference(base + shift, column)
        assert np.allclose(plain, shifted, rtol=0, atol=1e-15)
        assert np.all(shifted[:, column] == 0.0)  # the busbar column cancels bit-exactly


def test_a_pure_common_mode_truth_is_annihilated_whatever_the_bus_count():
    """A truth that is *only* common-mode (identical at every bus) referenced to any bus is
    identically zero, so no threshold can be crossed."""
    per_day = np.linspace(-0.01, 0.02, 7)[:, None]
    truth = np.repeat(per_day, 4, axis=1)
    assert np.all(cm.reference(truth, 2) == 0.0)
    assert np.all(cm.reference(truth.mean(axis=0), 0) == 0.0)


def test_day_matched_referencing_cancels_a_shift_that_varies_across_days():
    """The day-matched form (J1) cancels a day-varying common-mode shift; subtracting the
    busbar's all-day mean instead does not, once the meter's kept days differ."""
    days, meters = 10, 3
    shift = np.zeros((days, 1))
    shift[::2] = 0.01  # the common-mode error is present on alternate days only
    truth = np.tile(shift, (1, meters))
    survives = np.ones((days, meters), dtype=bool)
    survives[1, 0] = False  # one meter misses one quiet day
    matched = cm.reference(truth, 0)
    assert np.all(matched == 0.0)
    k_matched = np.asarray(cm.reference(truth, 0))
    assert np.abs(np.where(survives, k_matched, 0.0)).max() == 0.0
    unmatched = truth - truth[:, 0].mean()  # the all-day-mean form, for contrast
    assert np.abs(unmatched).max() == pytest.approx(0.005, abs=1e-12)


# --- 2. the F_ref formula against Monte Carlo ---------------------------------------------------


def test_the_referenced_floor_is_the_quadrature_sum_of_the_two_sensor_floors():
    """F_ref^2 = F_meter^2 + F_busbar^2 exactly, as an identity of `cal.c1_floor`."""
    v_days = toy_v_days(days=15)
    survives = np.ones((15, 4), dtype=bool)
    survives[:3, 1] = False  # a meter with fewer kept days still satisfies the identity
    band = cm.floors(0.01, v_days, survives)
    assert band["quadrature_residual"] < 1e-20
    assert np.allclose(band["referenced"] ** 2, band["meter"] ** 2 + band["busbar"] ** 2,
                       rtol=0, atol=1e-20)  # fmt: skip


def test_the_referenced_floor_matches_the_monte_carlo_standard_deviation():
    """The sd of the day-matched referenced contrast over replicates must equal F_ref.

    Meter noise is drawn exactly as `pa.draw_replicate` does and substation noise exactly as
    `cm.draw_busbar` does, with no missingness, so the kept-day set is the whole axis.
    """
    days, meters, sigma = 20, 6, 0.01
    counts = toy_counts(days=days)
    v_days = toy_v_days(days=days)
    survives = np.ones((days, meters), dtype=bool)
    band = cm.floors(sigma, v_days, survives)
    expected = float(band["referenced"][0])
    assert expected == pytest.approx(
        float(cal.c1_floor(cm.referenced_sigma(sigma), v_days, survives)[0]), rel=1e-12)

    rng = np.random.default_rng(404)
    scale_day = sigma / np.sqrt(counts["n_daylight_valid"].astype(float))
    scale_night = sigma / np.sqrt(counts["n_night_valid"].astype(float))
    trials = 20000
    values = np.empty((trials, meters))
    for trial in range(trials):
        meter = (rng.standard_normal((days, meters)) * scale_day[:, None]
                 - rng.standard_normal((days, meters)) * scale_night[:, None])  # fmt: skip
        busbar = cm.draw_busbar(rng, counts)
        values[trial] = (meter - busbar[:, None]).mean(axis=0)
    observed = values.std(axis=0, ddof=1)
    assert np.allclose(observed, expected, rtol=0.04)
    # the raw floor alone would understate the spread by the inflation factor
    assert float(band["meter"][0]) < expected
    assert expected / float(band["meter"][0]) == pytest.approx(
        np.sqrt(1.0 + (cm.SIGMA_SUB / sigma) ** 2), rel=1e-12)


def test_one_busbar_series_is_shared_by_every_meter_of_a_replicate():
    """J4: `cm.draw_busbar` returns one per-day series, so the referenced contrasts of two
    meters share their busbar term and are correlated even when the meters are independent."""
    counts = toy_counts(days=8)
    rng = np.random.default_rng(7)
    series = cm.draw_busbar(rng, counts)
    assert series.shape == (8,)
    assert np.isfinite(series).all()


# --- 3. the C1/C2 helper against task 1's `cal.calibration_ratios` -----------------------------


def test_the_local_c1_c2_helper_agrees_with_task_1s_calibration_ratios():
    """J6: the helper's C1 and C2 ratios must be task 1's on the same toy array."""
    rng = np.random.default_rng(99)
    days, meters, sigma = 14, 5, 0.01
    v_days = toy_v_days(days=days)
    y = rng.standard_normal((days, meters)) * 2e-4
    survives = rng.random((days, meters)) >= 0.1
    survives[:, 0] = True
    import phase9_analysis as pa

    k_hat = pa.survival_mean(y, survives)
    parts = cal.calibration_ratios(y, survives, k_hat, sigma, v_days)
    mine = cm.c1_c2_ratios(y, survives, sigma, v_days)
    for k in cm.K_GRID:
        theirs = cal.ratios_for_k(parts, k, 1.0)
        for name in ("C1", "C2"):
            left, right = mine[k][name], theirs[name]
            both = np.isfinite(left) & np.isfinite(right)
            assert np.array_equal(np.isfinite(left), np.isfinite(right))
            assert np.allclose(left[both], right[both], rtol=1e-12, atol=0)


def test_a_constant_contrast_makes_c2_unbounded_and_referencing_removes_it():
    """A truth that is constant across days has no within-day spread, so C2's t explodes on the
    raw contrast; the referenced contrast of a common-mode truth leaves only the noise."""
    days, meters, sigma = 12, 3, 0.01
    v_days = toy_v_days(days=days)
    survives = np.ones((days, meters), dtype=bool)
    rng = np.random.default_rng(5)
    noise = rng.standard_normal((days, meters)) * 1e-5
    truth = np.full((days, meters), 5e-3)
    raw = cm.c1_c2_ratios(truth + noise, survives, sigma, v_days)
    referenced = cm.c1_c2_ratios(cm.reference(truth, 0) + noise, survives,
                                 cm.referenced_sigma(sigma), v_days)  # fmt: skip
    assert raw[1]["C1"].min() > 3.0  # the fixed floor is crossed several times over
    assert raw[1]["C2"].min() > 50.0  # a constant truth has no day-to-day spread at all
    assert referenced[1]["C1"].max() < 1.0
    assert referenced[1]["C2"].max() < 5.0


# --- 4. the family event -----------------------------------------------------------------------


def test_the_alarm_fraction_is_the_family_event_over_the_configurations():
    """One rule's first K buses decide it; a bus outside every configuration cannot alarm."""
    buses = [10, 11, 12, 13]
    rules = {"a": [10, 11, 12], "b": [13, 12, 11]}
    k_values = np.array([0.0, 0.0, 0.0, 1.0])  # only bus 13 is high
    assert cm.alarm_fraction(k_values, buses, rules, 1, 0.5)["alarming_rules"] == ["b"]
    assert cm.alarm_fraction(k_values, buses, rules, 1, 0.5)["fraction"] == 0.5
    assert cm.alarm_fraction(k_values, buses, rules, 3, 0.5)["alarming"] == 1
    assert cm.alarm_fraction(k_values, buses, rules, 3, 2.0)["alarming"] == 0


# --- 5. refuse to overwrite --------------------------------------------------------------------


def test_run_refuses_to_overwrite_an_existing_results_file(tmp_path):
    """The guard fires before anything is read, so no cached state is touched."""
    target = tmp_path / "common_mode.json"
    target.write_text(json.dumps({"already": "here"}) + "\n")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        cm.run(output=target, replicates=1)
    assert json.loads(target.read_text()) == {"already": "here"}


def test_the_status_string_is_the_one_the_task_fixes():
    assert cm.STATUS == ("EXPLORATORY; zero new flows; cached Phase 8 mv_daily states; "
                         "not registered")  # fmt: skip
