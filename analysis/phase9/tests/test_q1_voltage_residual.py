"""Unit tests of the Q1-L1 addendum statistics, on synthetic arrays only.

No network, cache or state file is opened here, so these tests are fast and independent of
the Phase 8 outputs. They cover what the issue lists: band assignment at the boundaries, the
z_K values, the mean versus median estimators, the cancellation of a constant per-bus offset
in the day-night contrast, and the two file guards.
"""

from __future__ import annotations

import json
import math
import statistics

import numpy as np
import pytest
import q1_voltage_residual as q1

# --- bands at the boundaries ---------------------------------------------------------------


def test_band_boundaries_are_half_open():
    assert q1.band(0.0, 1.0, 2.0) == "A"
    assert q1.band(0.999, 1.0, 2.0) == "A"
    assert q1.band(1.0, 1.0, 2.0) == "B"  # the A/B boundary belongs to B
    assert q1.band(1.999, 1.0, 2.0) == "B"
    assert q1.band(2.0, 1.0, 2.0) == "C"  # the B/C boundary belongs to C
    assert q1.band(20.0, 1.0, 2.0) == "C"


def test_band_at_equal_thresholds_skips_b():
    assert q1.band(0.9, 1.0, 1.0) == "A"
    assert q1.band(1.0, 1.0, 1.0) == "C"


def test_band_rejects_thresholds_out_of_order():
    with pytest.raises(ValueError):
        q1.band(1.0, 2.0, 1.0)


# --- z_K -----------------------------------------------------------------------------------


def test_z_bonferroni_matches_its_definition():
    for k in (1, 2, 5, 43, 58):
        z = q1.z_bonferroni(k)
        assert statistics.NormalDist().cdf(z) == pytest.approx(1.0 - 0.025 / k, abs=1e-12)


def test_z_bonferroni_known_values():
    assert q1.z_bonferroni(1) == pytest.approx(1.959963985, abs=1e-8)  # unadjusted
    assert q1.z_bonferroni(2) == pytest.approx(2.241402728, abs=1e-8)  # z_2, the meter test
    assert q1.z_bonferroni(43) < q1.z_bonferroni(58)  # more buses, a higher bar


def test_z_bonferroni_rejects_k_below_one():
    with pytest.raises(ValueError):
        q1.z_bonferroni(0)


# --- floors and thresholds -----------------------------------------------------------------


def test_floors_match_the_registered_formulas():
    sigma, n_day, n_night, d_eff = 0.01, 40.0, 56.0, 173.85
    f = q1.floors(sigma, n_day, n_night, d_eff, "mean")
    root = math.sqrt(1 / n_day + 1 / n_night) / math.sqrt(d_eff)
    assert f["F_bias"] == pytest.approx(0.98 * sigma)
    assert f["F_ind"] == pytest.approx(sigma / math.sqrt(n_day * d_eff))
    assert f["F_C_matched"] == pytest.approx(0.2 * sigma * root)
    assert f["F_C_realistic"] == pytest.approx(sigma * root)


def test_illustrative_thresholds_reproduce_the_registration():
    """Registration s. 5 illustration: n_day 40, n_night 56, D 183, D_eff about 174."""
    d_eff = 0.95 * 183
    t = q1.thresholds(0.01, 40.0, 56.0, d_eff, q1.z_bonferroni(2), "mean")
    assert t["level"]["low"] == pytest.approx(2.7e-4, rel=0.05)
    assert t["level"]["high"] == pytest.approx(0.0220, rel=0.01)
    assert t["contrast"]["low"] == pytest.approx(7.0e-5, rel=0.05)
    assert t["contrast"]["high"] == pytest.approx(3.5e-4, rel=0.05)


def test_median_factor_scales_the_averaging_floors_only():
    args = (0.01, 40.0, 56.0, 173.85)
    mean = q1.floors(*args, "mean")
    averaging = q1.floors(*args, "median_averaging_floors")
    every = q1.floors(*args, "median_all_floors")
    assert q1.MEDIAN_FACTOR == pytest.approx(1.2533, abs=1e-4)
    for key in ("F_ind", "F_C_matched", "F_C_realistic"):
        assert averaging[key] == pytest.approx(q1.MEDIAN_FACTOR * mean[key])
        assert every[key] == pytest.approx(q1.MEDIAN_FACTOR * mean[key])
    assert averaging["F_bias"] == pytest.approx(mean["F_bias"])
    assert every["F_bias"] == pytest.approx(q1.MEDIAN_FACTOR * mean["F_bias"])


def test_floors_reject_an_unknown_estimator():
    with pytest.raises(ValueError):
        q1.floors(0.01, 40.0, 56.0, 100.0, "trimmed")


# --- day statistics, mean versus median, offset cancellation -------------------------------


def _synthetic(n_days=5, steps=8, buses=3, seed=0):
    rng = np.random.default_rng(seed)
    daylight = np.zeros(steps, dtype=bool)
    daylight[: steps // 2] = True
    deltas = [rng.normal(size=(steps, buses)) for _ in range(n_days)]
    return deltas, daylight


def test_partition_days_keeps_only_the_days_the_statistics_are_defined_on():
    days = [10, 11, 12, 13]
    defined, zero = q1.partition_days(days, [35, 0, 12, 0], steps=96)
    assert defined == [10, 12]
    assert zero == [11, 13]


def test_partition_days_refuses_a_day_without_a_night_step():
    with pytest.raises(RuntimeError, match="without a night step"):
        q1.partition_days([1, 2], [96, 35], steps=96)


def test_partition_days_requires_one_count_per_day():
    with pytest.raises(ValueError):
        q1.partition_days([1, 2, 3], [35, 35])


def test_day_statistics_splits_daylight_and_night():
    delta = np.array([[1.0, 2.0], [3.0, 4.0], [10.0, 20.0], [30.0, 40.0]])
    daylight = np.array([True, True, False, False])
    day, night, contrast = q1.day_statistics(delta, daylight)
    assert day == pytest.approx([2.0, 3.0])
    assert night == pytest.approx([20.0, 30.0])
    assert contrast == pytest.approx([-18.0, -27.0])


def test_day_statistics_rejects_a_day_without_night_or_daylight():
    delta = np.zeros((4, 2))
    with pytest.raises(ValueError):
        q1.day_statistics(delta, np.ones(4, dtype=bool))
    with pytest.raises(ValueError):
        q1.day_statistics(delta, np.zeros(4, dtype=bool))


def test_day_statistics_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        q1.day_statistics(np.zeros((4, 2)), np.array([True, False]))


def test_constant_per_bus_offset_cancels_in_the_contrast():
    """A fixed per-meter calibration offset has no day or step index (sensing.py:242-243), so
    it shifts the level statistic and leaves the day-night contrast unchanged."""
    deltas, daylight = _synthetic()
    offset = np.array([0.05, -0.02, 0.1])
    plain = [q1.day_statistics(d, daylight) for d in deltas]
    shifted = [q1.day_statistics(d + offset, daylight) for d in deltas]
    for (day, _, contrast), (day_b, _, contrast_b) in zip(plain, shifted, strict=True):
        assert contrast_b == pytest.approx(contrast)
        assert day_b == pytest.approx(day + offset)
    m = q1.aggregate(np.stack([row[0] for row in plain]))
    m_shifted = q1.aggregate(np.stack([row[0] for row in shifted]))
    k = q1.aggregate(np.stack([row[2] for row in plain]))
    k_shifted = q1.aggregate(np.stack([row[2] for row in shifted]))
    assert k_shifted["mean"] == pytest.approx(k["mean"])
    assert k_shifted["median"] == pytest.approx(k["median"])
    assert m_shifted["mean"] == pytest.approx(m["mean"] + offset)


def test_aggregate_mean_and_median_differ_under_one_outlier_day():
    per_day = np.array([[1.0], [1.0], [1.0], [1.0], [101.0]])
    out = q1.aggregate(per_day)
    assert out["mean"] == pytest.approx([21.0])
    assert out["median"] == pytest.approx([1.0])


def test_aggregate_matches_numpy_on_random_input():
    deltas, daylight = _synthetic(n_days=7, buses=4, seed=3)
    per_day = np.stack([q1.day_statistics(d, daylight)[0] for d in deltas])
    out = q1.aggregate(per_day)
    assert out["mean"] == pytest.approx(per_day.mean(axis=0))
    assert out["median"] == pytest.approx(np.median(per_day, axis=0))


def test_rank_correlation_is_monotone_invariant():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    assert q1.rank_correlation(x, 2 * x + 1) == pytest.approx(1.0)
    assert q1.rank_correlation(x, -x) == pytest.approx(-1.0)
    assert math.isnan(q1.rank_correlation(x, np.ones(4)))
    assert math.isnan(q1.rank_correlation([1.0, 2.0], [1.0, 2.0]))


# --- the file guards -----------------------------------------------------------------------


def test_write_new_json_refuses_to_overwrite(tmp_path):
    path = tmp_path / "q1_results.json"
    digest = q1.write_new_json(path, {"a": 1})
    assert json.loads(path.read_text()) == {"a": 1}
    assert digest == q1.sha256_text(path.read_text())
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        q1.write_new_json(path, {"a": 2})
    assert json.loads(path.read_text()) == {"a": 1}


def test_write_inputs_json_is_idempotent_but_immutable(tmp_path):
    path = tmp_path / "registration_inputs.json"
    first = q1.write_inputs_json(path, {"sigma": 0.01})
    assert q1.write_inputs_json(path, {"sigma": 0.01}) == first  # same inputs, same file
    with pytest.raises(RuntimeError, match="are fixed and are not rewritten"):
        q1.write_inputs_json(path, {"sigma": 0.02})
    assert json.loads(path.read_text()) == {"sigma": 0.01}


def test_load_stage1_refuses_when_the_inputs_file_is_missing(tmp_path):
    with pytest.raises(RuntimeError, match="must run and write the registered inputs"):
        q1.load_stage1(tmp_path / "registration_inputs.json")


def test_stage2_refuses_to_start_without_stage1(tmp_path):
    with pytest.raises(RuntimeError, match="must run and write the registered inputs"):
        q1.stage2(tmp_path / "registration_inputs.json", tmp_path / "q1_results.json")


def test_stage2_refuses_to_overwrite_an_existing_results_file(tmp_path):
    inputs, results = tmp_path / "registration_inputs.json", tmp_path / "q1_results.json"
    inputs.write_text("{}")
    results.write_text("{}")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        q1.stage2(inputs, results)


# --- verdicts and the interpretation map ---------------------------------------------------


def _inputs(n_day=40.0, n_night=56.0, d_eff=173.85, k_all=43):
    z_meter, z_all = q1.z_bonferroni(2), q1.z_bonferroni(k_all)
    return {
        "thresholds": {
            estimator: {
                f"{sigma:g}": {
                    "sigma_tot": sigma,
                    "primary": sigma == q1.SIGMA_PRIMARY,
                    "meter": q1.thresholds(sigma, n_day, n_night, d_eff, z_meter, estimator),
                    "all": q1.thresholds(sigma, n_day, n_night, d_eff, z_all, estimator),
                }
                for sigma in q1.SIGMA_GRID
            }
            for estimator in ("mean", "median_averaging_floors", "median_all_floors")
        }
    }


def test_verdicts_cover_every_registered_sigma():
    out = q1.verdicts(1e-9, _inputs(), "mean", "level", "meter")
    assert sorted(out) == sorted(f"{s:g}" for s in q1.SIGMA_GRID)
    assert [e["band"] for e in out.values()] == ["A"] * 4
    assert out["0.01"]["primary"] is True


def test_verdicts_use_the_absolute_value_and_the_band_rule():
    inputs = _inputs()
    low = inputs["thresholds"]["mean"]["0.01"]["meter"]["level"]["low"]
    high = inputs["thresholds"]["mean"]["0.01"]["meter"]["level"]["high"]
    assert q1.verdicts(-low, inputs, "mean", "level", "meter")["0.01"]["band"] == "B"
    assert q1.verdicts(-high, inputs, "mean", "level", "meter")["0.01"]["band"] == "C"
    assert q1.verdicts(low / 2, inputs, "mean", "level", "meter")["0.01"]["band"] == "A"


def test_interpretation_follows_the_registered_map():
    assert "do not pursue" in q1.interpretation({"level_meter": "A", "contrast_meter": "A"})
    assert "do not pursue" in q1.interpretation({"level_meter": "B", "contrast_meter": "B"})
    assert "residual-pattern screening" in q1.interpretation(
        {"level_meter": "B", "contrast_meter": "C"}
    )
    assert "needs amending" in q1.interpretation({"level_meter": "C", "contrast_meter": "A"})
    assert "needs amending" in q1.interpretation({"level_meter": "C", "contrast_meter": "C"})
