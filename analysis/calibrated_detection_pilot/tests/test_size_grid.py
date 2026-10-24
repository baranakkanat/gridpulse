"""Synthetic tests for the calibrated-detection pilot's step-1 size grid.

Nothing here runs a power flow, reads a `vm` array or writes outside `tmp_path`. The only
repository file touched is the frozen Phase 6 placement file, read through
`phase9_analysis.placements`.
"""

from __future__ import annotations

import json

import calibration as cal
import common_mode as cm
import numpy as np
import phase9_analysis as pa
import pytest
import q1_voltage_residual as q1
import size_grid as sg
from scipy import stats

STEPS = pa.STEPS  # 96


# --- helpers --------------------------------------------------------------------------------


def synthetic_axis(days: int = 12, seed: int = 7) -> dict:
    """A small development-half-shaped axis: unequal daylight counts and per-day masks."""
    rng = np.random.default_rng(seed)
    counts = [int(c) for c in rng.integers(30, 60, size=days + 1)]
    day_numbers = list(range(100, 100 + days + 1))
    axis = cal.axis_from_counts(day_numbers, counts, delay=True)
    masks = {}
    for day, count in zip(axis["days"], axis["n_daylight"], strict=True):
        mask = np.zeros(STEPS, dtype=bool)
        mask[: int(count)] = True
        masks[int(day)] = mask
    axis["masks"] = masks
    axis["source"] = "synthetic test axis"
    axis["candidate_days"] = len(day_numbers)
    return axis


def cell_block(successes: int, trials: int, rules_over: int, max_rate: float) -> dict:
    """One cell's arm block, in the shape `criterion` consumes."""
    return {
        "pooled_over_rules": sg.clopper_pearson(successes, trials),
        "rules_with_lower_bound_over_0.05": int(rules_over),
        "max_rule_rate": float(max_rate),
    }


def smallest_successes_above_bound(trials: int, bound: float = 0.05) -> int:
    """The smallest success count whose Clopper-Pearson lower bound exceeds `bound`."""
    for successes in range(trials + 1):
        if sg.clopper_pearson(successes, trials)["low"] > bound:
            return successes
    raise AssertionError("no success count clears the bound")


# --- the grid itself ------------------------------------------------------------------------


def test_the_primary_grid_is_the_36_cells_of_the_proposal():
    grid = sg.cells()
    assert len(grid) == 36
    assert len({cell["cell_id"] for cell in grid}) == 36
    assert {cell["sigma"] for cell in grid} == {0.01, 0.005}
    assert {cell["K"] for cell in grid} == {1, 2, 4}
    assert {cell["noise"] for cell in grid} == {"N1", "N2_rho_0.5", "N2_rho_0.9"}
    assert {cell["sigma_bb_over_sigma_b"] for cell in grid} == {0.2, 1.0}
    assert all(cell["mv_swing"] is False and cell["diurnal_amplitude"] == 0.0 for cell in grid)
    assert len(sg.N1_CELL_IDS) == 12
    # the registered substation accuracy is the sigma_bb/sigma_b = 0.2 cell at sigma = 0.01
    registered = next(c for c in grid if c["cell_id"] == "sigma0.01_K2_N1_bb0.2")
    assert registered["sigma_bb"] == pytest.approx(cm.SIGMA_SUB)


# --- deliverable: the referenced contrast cancels a common per-day shift ----------------------


def test_the_referenced_contrast_cancels_a_common_per_day_shift_exactly():
    rng = np.random.default_rng(11)
    days, replicates, k = 9, 4, 3
    # dyadic values, so the addition and the subtraction below are exact in binary64
    meter = rng.integers(-1000, 1000, size=(days, replicates, k)) / 1024.0
    busbar = rng.integers(-1000, 1000, size=(days, replicates)) / 1024.0
    shift = rng.integers(-5000, 5000, size=days) / 1024.0

    plain = meter - busbar[:, :, None]
    shifted = (meter + shift[:, None, None]) - (busbar + shift[:, None])[:, :, None]
    assert np.array_equal(plain, shifted)

    # and the shift is not harmless to the unreferenced arm
    survives = np.ones((days, replicates, k), dtype=bool)
    assert np.array_equal(
        sg.studentised(plain, survives)[0], sg.studentised(shifted, survives)[0])
    unreferenced = sg.studentised(meter + shift[:, None, None], survives)[0]
    assert not np.allclose(unreferenced, sg.studentised(meter, survives)[0])


def test_a_common_shift_of_any_size_leaves_the_referenced_alarms_unchanged():
    rng = np.random.default_rng(12)
    days, replicates, k = 30, 50, 2
    meter = rng.standard_normal((days, replicates, k)) * 1e-3
    busbar = rng.standard_normal((days, replicates)) * 2e-4
    survives = rng.random((days, replicates, k)) >= 0.05
    shift = np.full(days, 5e-3)  # a large common-mode per-day swing

    base = sg.family_alarms(meter - busbar[:, :, None], survives, k)
    swung = sg.family_alarms(
        (meter + shift[:, None, None]) - (busbar + shift[:, None])[:, :, None], survives, k)
    assert np.array_equal(base, swung)
    # the unreferenced arm alarms on essentially every replicate under the same swing
    assert sg.family_alarms(meter + shift[:, None, None], survives, k).mean() > 0.9


# --- deliverable: the statistic is scipy's one-sample t --------------------------------------


def test_C2_ref_statistic_equals_scipy_one_sample_t_on_the_referenced_contrasts():
    rng = np.random.default_rng(13)
    days, replicates, k = 40, 6, 3
    meter = rng.standard_normal((days, replicates, k)) * 1e-3 + 4e-5
    busbar = rng.standard_normal((days, replicates)) * 2e-4
    survives = rng.random((days, replicates, k)) >= 0.1
    referenced = meter - busbar[:, :, None]

    t_stat, counts = sg.studentised(referenced, survives)
    for r in range(replicates):
        for m in range(k):
            kept = referenced[survives[:, r, m], r, m]
            assert counts[r, m] == kept.size
            assert t_stat[r, m] == pytest.approx(stats.ttest_1samp(kept, 0.0).statistic,
                                                 rel=1e-10)  # fmt: skip


def test_the_critical_value_is_the_two_sided_bonferroni_t_and_K_meters_form_the_family():
    for k in sg.K_GRID:
        assert cal.t_critical(143, k) == pytest.approx(stats.t.ppf(1.0 - 0.025 / k, 143))
    rng = np.random.default_rng(14)
    days, replicates, k = 25, 7, 4
    contrast = rng.standard_normal((days, replicates, k))
    survives = np.ones((days, replicates, k), dtype=bool)
    per_meter = sg.meter_alarms(contrast, survives, k)
    assert np.array_equal(sg.family_alarms(contrast, survives, k), per_meter.any(axis=-1))


def test_a_meter_with_fewer_than_two_kept_days_raises_no_alarm():
    contrast = np.full((5, 1, 2), 1e3)
    survives = np.zeros((5, 1, 2), dtype=bool)
    survives[0, 0, 0] = True  # one kept day: no sd, no statistic
    t_stat, counts = sg.studentised(contrast, survives)
    assert list(counts[0]) == [1, 0]
    assert np.isnan(t_stat).all()
    assert not sg.family_alarms(contrast, survives, 2).any()


# --- deliverable: independent replicates per rule ---------------------------------------------


def test_different_rules_draw_different_noise_at_the_same_replicate_index():
    axis = synthetic_axis()
    cache = sg.noise_cache(axis)
    cell = next(c for c in sg.cells() if c["cell_id"] == "sigma0.01_K2_N1_bb1")
    code = sg.NETWORKS[0]

    def draw(rule: str, block: int = 0):
        rng = sg.block_rng(code, cell["cell_id"], rule, block)
        meters = sg.meter_draws(rng, cell, axis, 3, cache)
        return meters["contrast"], sg.busbar_contrast(rng, axis, 3, cell["sigma_bb"])

    a_contrast, a_busbar = draw("random_0")
    b_contrast, b_busbar = draw("random_1")
    again_contrast, again_busbar = draw("random_0")

    assert np.array_equal(a_contrast, again_contrast)  # reproducible
    assert np.array_equal(a_busbar, again_busbar)
    assert not np.array_equal(a_contrast, b_contrast)  # never shared across rules
    assert not np.array_equal(a_busbar, b_busbar)
    assert not np.array_equal(a_contrast, draw("random_0", 1)[0])  # blocks differ


def test_different_cells_and_networks_draw_different_noise():
    axis = synthetic_axis()
    cache = sg.noise_cache(axis)
    cell = next(c for c in sg.cells() if c["cell_id"] == "sigma0.01_K1_N1_bb1")
    other = next(c for c in sg.cells() if c["cell_id"] == "sigma0.005_K1_N1_bb1")
    first = sg.meter_draws(sg.block_rng(sg.NETWORKS[0], cell["cell_id"], "unfiltered", 0),
                           cell, axis, 2, cache)["contrast"]  # fmt: skip
    second = sg.meter_draws(sg.block_rng(sg.NETWORKS[1], cell["cell_id"], "unfiltered", 0),
                            cell, axis, 2, cache)["contrast"]  # fmt: skip
    third = sg.meter_draws(sg.block_rng(sg.NETWORKS[0], other["cell_id"], "unfiltered", 0),
                           other, axis, 2, cache)["contrast"]  # fmt: skip
    assert not np.array_equal(first, second)
    assert not np.array_equal(first, third)


@pytest.mark.parametrize("cell_name", ["sigma0.01_K4_N1_bb0.2", "sigma0.01_K4_N2_rho_0.9_bb1"])
def test_a_block_reshape_keeps_the_replicate_and_meter_columns_independent(cell_name):
    """Across columns the draws must be uncorrelated: the sample correlations of 240
    independent day series of length 200 have mean 0 and sd 1/sqrt(199), and nothing else."""
    days = 200
    axis = synthetic_axis(days=days)
    cache = sg.noise_cache(axis)
    cell = next(c for c in sg.cells() if c["cell_id"] == cell_name)
    rng = sg.block_rng(sg.NETWORKS[0], cell["cell_id"], "unfiltered", 0)
    draws = sg.meter_draws(rng, cell, axis, 60, cache)
    # standardise away the per-day heteroskedasticity before correlating
    flat = draws["contrast"].reshape(draws["contrast"].shape[0], -1)
    flat = flat / flat.std(axis=1, keepdims=True)
    correlations = np.corrcoef(flat.T)
    off = correlations[~np.eye(correlations.shape[0], dtype=bool)]
    expected_sd = 1.0 / np.sqrt(days - 1)
    assert abs(off.mean()) < 3.0 * expected_sd / np.sqrt(off.size)
    assert off.std() == pytest.approx(expected_sd, rel=0.1)


# --- the busbar sensor -------------------------------------------------------------------------


def test_the_busbar_draw_is_common_modes_draw_busbar_at_the_registered_accuracy():
    axis = synthetic_axis(days=8)
    counts = {"n_daylight_valid": axis["n_daylight"], "n_night_valid": axis["n_night"]}
    frozen = cm.draw_busbar(np.random.default_rng(3), counts)
    scaled = sg.busbar_contrast(np.random.default_rng(3), axis, 1, cm.SIGMA_SUB)
    assert np.allclose(scaled[:, 0], frozen, rtol=1e-12, atol=0.0)


def test_the_busbar_noise_scales_linearly_and_has_no_missingness():
    axis = synthetic_axis(days=8)
    one = sg.busbar_contrast(np.random.default_rng(5), axis, 4, 0.002)
    five = sg.busbar_contrast(np.random.default_rng(5), axis, 4, 0.010)
    assert np.allclose(five, 5.0 * one, rtol=1e-12, atol=0.0)
    assert np.isfinite(one).all() and (one != 0.0).all()  # every day is read
    assert one.shape == (axis["n_daylight"].size, 4)


def test_the_referenced_contrast_variance_matches_the_proposals_sigma_sum():
    """Var(c^ref) = (sigma_b^2 + sigma_bb^2)(1/n_d + 1/m_d), proposal s. 3.2."""
    axis = synthetic_axis(days=3)
    cache = sg.noise_cache(axis)
    cell = next(c for c in sg.cells() if c["cell_id"] == "sigma0.01_K1_N1_bb1")
    rng = sg.block_rng("test", cell["cell_id"], "unfiltered", 0)
    draws = sg.meter_draws(rng, cell, axis, 40000, cache)
    busbar = sg.busbar_contrast(rng, axis, 40000, cell["sigma_bb"])
    referenced = (draws["contrast"] - busbar[:, :, None])[:, :, 0]
    expected = (cell["sigma"] ** 2 + cell["sigma_bb"] ** 2) * axis["v_days"]
    assert np.allclose(referenced.var(axis=1), expected, rtol=0.05)
    assert cm.referenced_sigma(0.002) == pytest.approx(0.002 * np.sqrt(2.0))


# --- Clopper-Pearson ------------------------------------------------------------------------------


@pytest.mark.parametrize(("successes", "trials"),
                         [(0, 20), (1, 20), (7, 20), (20, 20), (100, 2000), (2500, 50000)])
def test_the_clopper_pearson_interval_matches_scipy_binomtest(successes, trials):
    expected = stats.binomtest(successes, trials).proportion_ci(confidence_level=0.95,
                                                                method="exact")  # fmt: skip
    record = sg.clopper_pearson(successes, trials)
    assert record["low"] == pytest.approx(expected.low, abs=1e-12)
    assert record["high"] == pytest.approx(expected.high, abs=1e-12)
    assert record["rate"] == pytest.approx(successes / trials)


def test_the_pooled_record_carries_the_descriptive_wilson_interval():
    record = sg.pooled_record(2500, 50000)
    assert record["wilson_descriptive"] == pa.rate_record(2500, 50000)
    assert record["low"] <= record["rate"] <= record["high"]


# --- the H1a three-part rule and K2 ----------------------------------------------------------------


def _grid(ids, successes, trials=50000, rules_over=0, max_rate=0.05):
    return {c: cell_block(successes, trials, rules_over, max_rate) for c in ids}


def test_H1a_accepts_an_exactly_calibrated_grid():
    grid = _grid(sg.CELL_IDS, 2500)  # 0.05 in every cell
    block = sg.criterion(grid, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")
    assert block["verdict"] == "ACCEPTED"
    assert block["clause_1"] and block["clause_2"] and block["clause_3"]
    assert block["cells_failing_per_cell_lower_bound"] == []


def test_H1a_cell_tolerance_at_its_boundary():
    bad = smallest_successes_above_bound(50000)
    assert sg.clopper_pearson(bad, 50000)["low"] > 0.05
    for failures, verdict in ((3, "ACCEPTED"), (4, "FALSIFIED")):
        grid = _grid(sg.CELL_IDS, 2500)
        for cell in sg.CELL_IDS[:failures]:
            grid[cell] = cell_block(bad, 50000, 0, 0.05)
        block = sg.criterion(grid, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")
        assert block["verdict"] == verdict, (failures, block)
        assert len(block["cells_failing_per_cell_lower_bound"]) == failures


def test_H1a_pooled_clause_falsifies_on_its_own():
    # every cell passes its own clause, but the pooled rate over all 36 is too high
    rate = sg.clopper_pearson(2520, 50000)
    assert rate["low"] <= 0.05  # per cell this is tolerated at 50 000 trials
    grid = _grid(sg.CELL_IDS, 2520)
    block = sg.criterion(grid, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")
    assert not block["clause_1_pooled_lower_bound_at_most_0.05"]
    assert block["verdict"] == "FALSIFIED"


def test_H1a_clauses_2_and_3_falsify_only_together():
    base = _grid(sg.CELL_IDS, 2500)

    only_two = dict(base)
    only_two[sg.CELL_IDS[0]] = cell_block(2500, 50000, rules_over=3, max_rate=0.05)
    block = sg.criterion(only_two, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")
    assert block["verdict"] == "INDETERMINATE" and not block["accepted"]

    only_three = dict(base)
    only_three[sg.CELL_IDS[0]] = cell_block(2500, 50000, rules_over=2, max_rate=0.081)
    block = sg.criterion(only_three, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")
    assert block["verdict"] == "INDETERMINATE"

    both = dict(base)
    both[sg.CELL_IDS[0]] = cell_block(2500, 50000, rules_over=3, max_rate=0.081)
    block = sg.criterion(both, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")
    assert block["verdict"] == "FALSIFIED"
    assert block["cells_violating_clauses_2_and_3_together"] == [sg.CELL_IDS[0]]

    # the boundaries themselves are inside the tolerance
    edge = dict(base)
    edge[sg.CELL_IDS[0]] = cell_block(2500, 50000, rules_over=2, max_rate=0.08)
    assert sg.criterion(edge, cell_ids=sg.CELL_IDS, cell_tolerance=33,
                        label="t")["verdict"] == "ACCEPTED"  # fmt: skip


def test_K2_trips_at_two_failing_N1_cells_and_not_at_one():
    bad = smallest_successes_above_bound(50000)
    for failures, state in ((0, "NOT TRIPPED"), (1, "NOT TRIPPED"), (2, "TRIPPED")):
        grid = _grid(sg.N1_CELL_IDS, 2500)
        for cell in sg.N1_CELL_IDS[:failures]:
            grid[cell] = cell_block(bad, 50000, 0, 0.05)
        block = sg.k2_verdict(grid, "t")
        assert block["K2"] == state, (failures, block)
        assert block["cells"] == 12 and block["cell_tolerance"] == 11


def test_K2_uses_only_the_N1_cells():
    grid = _grid(sg.CELL_IDS, 2500)
    for cell in sg.CELL_IDS:
        if cell not in sg.N1_CELL_IDS:
            grid[cell] = cell_block(50000, 50000, 25, 1.0)  # every N2 cell is catastrophic
    assert sg.k2_verdict(grid, "t")["K2"] == "NOT TRIPPED"
    assert sg.criterion(grid, cell_ids=sg.CELL_IDS, cell_tolerance=33,
                        label="t")["verdict"] == "FALSIFIED"  # fmt: skip


def test_the_criterion_refuses_a_missing_cell():
    grid = _grid(sg.CELL_IDS[:-1], 2500)
    with pytest.raises(RuntimeError, match="no result"):
        sg.criterion(grid, cell_ids=sg.CELL_IDS, cell_tolerance=33, label="t")


def test_the_referencing_penalty_is_the_matched_cell_difference():
    ref = _grid(sg.CELL_IDS, 2600)
    raw = _grid(sg.CELL_IDS, 2500)
    block = sg.penalty(ref, raw)
    assert block["min"] == pytest.approx(0.002)
    assert block["max"] == pytest.approx(0.002)
    assert block["median"] == pytest.approx(0.002)


# --- end to end, on a synthetic axis, including refuse-to-overwrite ---------------------------------


def use_synthetic_rules_if_absent(monkeypatch) -> None:
    """Without the git-ignored frozen Phase 6 placements (a public clone), use 25 synthetic rules.

    They carry the frozen rule names and K buses each. Under J5 a rule's bus identity is
    uninformative, so the pipeline is the same; with the file present the real rules are read.
    """
    if (pa.REPO / q1.PLACEMENTS).exists():
        return
    rules = {name: list(range(max(sg.K_GRID))) for name in (*pa.NAMED_RULES, *pa.RANDOM_RULES)}
    monkeypatch.setattr(sg.pa, "placements", lambda code: rules)


@pytest.fixture
def tiny_run(tmp_path, monkeypatch):
    """Four parts and the merge, on a 12-day synthetic axis at 4 replicates per rule."""
    axis = synthetic_axis(days=12)
    monkeypatch.setattr(sg.cal, "development_axis", lambda code: axis)
    use_synthetic_rules_if_absent(monkeypatch)
    parts = tmp_path / "parts"
    for network in sg.NETWORKS:
        for sigma in sg.SIGMAS:
            sg.run_part(network, sigma, replicates=4, block=2, write=True,
                        output=parts / sg.part_path(network, sigma).name)  # fmt: skip
    return {"parts": parts, "output": tmp_path / "size_grid.json"}


def test_the_part_and_merge_pipeline_produces_the_full_grid(tiny_run):
    payload = sg.merge(tiny_run["output"], tiny_run["parts"])
    assert payload["status"] == sg.STATUS
    assert payload["pre_stated_readings"] == sg.PRE_STATED_READINGS
    assert payload["design"]["primary_cells"] == 36
    assert payload["design"]["power_flows_run"] == 0
    for network in sg.NETWORKS:
        assert sorted(payload["results"][network]) == sorted(sg.CELL_IDS)
        for cell in sg.CELL_IDS:
            block = payload["results"][network][cell]
            assert block["rules"] == 25
            assert block["trials_pooled"] == 4 * 25
            assert set(block["arms"]) == set(sg.ARMS)
    assert set(payload["overall"]["H1a"]) == set(sg.ARMS)
    assert payload["overall"]["K2"]["verdict"] in ("TRIPPED", "NOT TRIPPED")
    on_disk = json.loads(tiny_run["output"].read_text())
    assert on_disk["design"] == payload["design"]


def test_the_result_file_is_written_once_and_refuses_to_overwrite(tiny_run):
    sg.merge(tiny_run["output"], tiny_run["parts"])
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        sg.merge(tiny_run["output"], tiny_run["parts"])


def test_a_part_file_refuses_to_overwrite(tmp_path, monkeypatch):
    axis = synthetic_axis(days=8)
    monkeypatch.setattr(sg.cal, "development_axis", lambda code: axis)
    use_synthetic_rules_if_absent(monkeypatch)
    target = tmp_path / "part.json"
    sg.run_part(sg.NETWORKS[0], "0.01", replicates=2, block=2, write=True, output=target)
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        sg.run_part(sg.NETWORKS[0], "0.01", replicates=2, block=2, write=True, output=target)


def test_the_merge_refuses_a_missing_part(tmp_path):
    with pytest.raises(RuntimeError, match="is missing"):
        sg.merge(tmp_path / "out.json", tmp_path / "no_parts")


def test_the_merge_refuses_parts_that_disagree_on_the_design(tiny_run):
    victim = tiny_run["parts"] / sg.part_path(sg.NETWORKS[1], "0.005").name
    payload = json.loads(victim.read_text())
    payload["design"]["replicates_per_rule"] = 999
    victim.unlink()
    q1.write_new_json(victim, payload)
    with pytest.raises(RuntimeError, match="different `design` block"):
        sg.merge(tiny_run["output"], tiny_run["parts"])


def test_the_run_refuses_an_unknown_network_or_sigma():
    with pytest.raises(ValueError, match="not a sweep network"):
        sg.run_part("1-LV-rural2--2-sw", "0.01", write=False)
    with pytest.raises(ValueError, match="not a primary sigma"):
        sg.run_part(sg.NETWORKS[0], "0.02", write=False)


def test_the_replicate_count_must_be_a_multiple_of_the_block():
    axis = synthetic_axis(days=6)
    rules = {name: list(range(10)) for name in (f"r{i}" for i in range(25))}
    with pytest.raises(ValueError, match="not a multiple"):
        sg.cell_network(sg.NETWORKS[0], sg.cells()[0], axis, rules, sg.noise_cache(axis),
                        replicates=5, block=2)  # fmt: skip
