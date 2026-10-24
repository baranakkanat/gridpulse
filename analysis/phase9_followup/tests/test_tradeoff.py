"""Synthetic tests of `analysis/phase9_followup/tradeoff.py`.

Nothing here reads a network, a W6 artefact, a Phase 9 result or `outputs/`; every input is a
toy array. The whole file is meant to stay well under 30 s.
"""

from __future__ import annotations

import calibration as cal
import numpy as np
import pytest
import tradeoff as td

STEPS = 96


# --- toy fixtures ------------------------------------------------------------------------------


def toy_counts(days: int = 8, n_daylight: int = 40) -> dict:
    """A `pa.meter_days`-shaped day axis with constant per-day counts."""
    return {
        "days": list(range(days)),
        "n_daylight_valid": np.full(days, n_daylight, dtype=int),
        "n_night_valid": np.full(days, STEPS - n_daylight, dtype=int),
        "n_daylight_steps": np.full(days, n_daylight, dtype=int),
        "simulated_days": days,
        "retained_days": days + 1,
        "delay_removed_day": days,
        "dropped_not_usable": [],
    }


def toy_net(lines, downstream: dict, rules: dict, truth_contrast, buses=(1, 2, 3),
            days: int = 8) -> dict:  # fmt: skip
    """The subset of `network_block`'s result the Monte Carlo pass and the blocks below read."""
    return {
        "code": "toy",
        "buses": [int(b) for b in buses],
        "lines": [int(line) for line in lines],
        "downstream": {int(line): [int(b) for b in below] for line, below in downstream.items()},
        "rules": rules,
        "rule_names": sorted(rules),
        "counts": toy_counts(days),
        "truth_contrast": np.asarray(truth_contrast, dtype=float),
    }


def toy_spec(sigma_v: float = 1e-6, missing: float = 0.0) -> dict:
    return {"condition": "toy", "sigma_v": float(sigma_v), "sigma_bias": 0.0,
            "remote_missing": float(missing)}  # fmt: skip


# --- 1. detection probability on a toy artefact with a known signal -----------------------------


def test_detection_probability_on_a_toy_artefact_with_a_known_signal():
    """One cable carries a constant 1 p.u. contrast at its one downstream bus; the noise is
    1e-6 against a 1e-4 floor. Every calibration must detect that pair in every replicate, and
    C0 and C1 must detect nothing else."""
    buses, days = (1, 2, 3), 8
    rules = {"a": [2, 1], "b": [1, 3]}  # at K = 1 the configurations are [2] and [1]
    truth = np.zeros((2, days, len(buses)))
    truth[0, :, 1] = 1.0  # cable 0, bus 2, every day
    net = toy_net([0, 1], {0: [2], 1: [3]}, rules, truth, buses=buses, days=days)

    result = td.alarm_pass("toy", net, truth="artefact",
                           sampler=td.iid_sampler(toy_spec(), net["counts"]),
                           sigma=0.01, c0_floor=1e-4, condition="toy", control="toy_detection",
                           k_grid=(1,), replicates=20)  # fmt: skip
    block = td.detection_block(net, result)["K_1"]["calibrations"]

    # the (cable 0, rule a) pair is the only one with a meter downstream at K = 1
    for name in td.CALIBRATIONS:
        successes = np.asarray(block[name]["per_pair_successes"])
        assert successes.shape == (2, 2)
        assert successes[0, 0] == 20
        assert block[name]["pairs_with_a_meter_downstream"] == 1
        assert block[name]["detect_given_meter_downstream"]["rate"] == pytest.approx(1.0)
    for name in ("C0", "C1"):  # C2's t statistic is scale-free, so noise alone can alarm
        successes = np.asarray(block[name]["per_pair_successes"])
        assert successes[0, 1] == 0 and successes[1, 0] == 0 and successes[1, 1] == 0
        assert block[name]["coverage"]["rate"] == pytest.approx(0.25)
        assert block[name]["detect_given_no_meter_downstream"]["rate"] == pytest.approx(0.0)


def test_a_signal_below_the_floor_is_not_detected():
    """The same toy cable with a 1e-6 p.u. contrast against a 1e-4 floor detects nothing."""
    buses, days = (1, 2, 3), 8
    truth = np.zeros((1, days, len(buses)))
    truth[0, :, 1] = 1e-6
    net = toy_net([0], {0: [2]}, {"a": [2, 1]}, truth, buses=buses, days=days)
    result = td.alarm_pass("toy", net, truth="artefact",
                           sampler=td.iid_sampler(toy_spec(), net["counts"]),
                           sigma=0.01, c0_floor=1e-4, condition="toy", control="toy_small",
                           calibrations=("C0", "C1"), k_grid=(1,), replicates=10)  # fmt: skip
    block = td.detection_block(net, result)["K_1"]["calibrations"]
    assert block["C0"]["coverage"]["successes"] == 0
    assert block["C1"]["coverage"]["successes"] == 0


def test_an_alarm_at_multiplier_c_is_the_ratio_against_c():
    """The c grid is monotone: the alarm count can only fall as c grows (J3)."""
    buses, days = (1, 2, 3), 8
    truth = np.zeros((1, days, len(buses)))
    truth[0, :, 1] = 3.0e-4
    net = toy_net([0], {0: [2]}, {"a": [2, 1]}, truth, buses=buses, days=days)
    result = td.alarm_pass("toy", net, truth="artefact",
                           sampler=td.iid_sampler(toy_spec(1e-5), net["counts"]),
                           sigma=0.01, c0_floor=1e-4, condition="toy", control="toy_curve",
                           calibrations=("C0",), k_grid=(1,), replicates=10)  # fmt: skip
    counts = result["tally"][("C0", 1)].sum(axis=(1, 2))
    assert list(counts) == sorted(counts, reverse=True)
    assert counts[td.C_GRID.index(0.5)] == 10  # 3e-4 clears 0.5 * z_1 * 1e-4
    assert counts[td.C_GRID.index(5.0)] == 0  # and not 5 * z_1 * 1e-4


# --- 2. the batched statistic is task 1's --------------------------------------------------------


def test_batched_C2_and_C1_agree_with_task_1_on_one_cable():
    """`per_meter_ratios` is `cal.calibration_ratios` batched over cables (J2)."""
    rng = np.random.default_rng(11)
    days, meters = 14, 3
    contrast = rng.normal(0.0, 0.001, size=(days, meters))
    survives = rng.random((days, meters)) >= 0.1
    survives[:, 0] = True
    v_days = np.full(days, 1.0 / 40.0 + 1.0 / 56.0)
    k_hat = cal.pa.survival_mean(contrast, survives)

    parts = cal.calibration_ratios(contrast, survives, k_hat, 0.01, v_days)
    expected = cal.ratios_for_k(parts, 2, 1e-4)
    got = td.per_meter_ratios(contrast[None, :, :], survives, k_hat[None, :], 0.01, v_days,
                              1e-4, (2,), ("C0", "C1", "C2"))[2]  # fmt: skip

    for name in ("C0", "C1", "C2"):
        assert got[name][0] == pytest.approx(expected[name], rel=1e-12, nan_ok=True)


# --- 3. coverage at a calibrated 5 % false-alarm rate --------------------------------------------


def _rates(values) -> list[float]:
    assert len(values) == len(td.C_GRID)
    return [float(v) for v in values]


def test_coverage_at_5pc_false_alarm_is_interpolated_in_c():
    """The crossing sits between c = 1.0 and c = 1.1; both the rate and coverage are linear
    in c, so the share is (0.07 - 0.05) / (0.07 - 0.03) = 0.5."""
    false_alarms = _rates([0.90, 0.50, 0.20, 0.07, 0.03, 0.02, 0.01, 0.0, 0.0, 0.0, 0.0])
    coverage = _rates([0.95, 0.80, 0.60, 0.40, 0.20, 0.15, 0.10, 0.05, 0.02, 0.01, 0.0])

    record = td.coverage_at_rate(false_alarms, coverage)

    assert record["record"] == "interpolated"
    assert record["c_star"] == pytest.approx(1.05)
    assert record["coverage"] == pytest.approx(0.30)
    assert record["bracket"]["c_low"] == 1.0 and record["bracket"]["c_high"] == 1.1
    assert record["target_false_alarm"] == pytest.approx(0.05)


def test_coverage_at_5pc_false_alarm_is_typed_when_the_crossing_is_not_bracketed_below():
    """A calibration already at or below 5 % at the smallest c gets no number."""
    record = td.coverage_at_rate(_rates([0.04] * 11), _rates([0.3] * 11))
    assert record["record"] == "not_bracketed_below"
    assert record["c_star"] is None and record["coverage"] is None
    assert record["c_star_at_most"] == pytest.approx(td.C_GRID[0])
    assert record["coverage_at_c_grid_minimum"] == pytest.approx(0.3)


def test_coverage_at_5pc_false_alarm_is_typed_when_the_crossing_is_not_bracketed_above():
    """A calibration still above 5 % at the largest c gets no number either."""
    record = td.coverage_at_rate(_rates([0.9] * 11), _rates([0.5] * 11))
    assert record["record"] == "not_bracketed_above"
    assert record["c_star"] is None and record["coverage"] is None


def test_coverage_at_5pc_false_alarm_refuses_a_grid_of_the_wrong_length():
    with pytest.raises(ValueError):
        td.coverage_at_rate([0.1, 0.01], [0.5, 0.2])


def test_the_tradeoff_curve_carries_one_row_per_c_and_its_crossing():
    buses, days = (1, 2, 3), 8
    truth = np.zeros((1, days, len(buses)))
    truth[0, :, 1] = 5.0e-4
    net = toy_net([0], {0: [2]}, {"a": [2, 1]}, truth, buses=buses, days=days)
    shared = {"sigma": 0.01, "c0_floor": 1e-4, "condition": "toy",
              "calibrations": ("C0",), "k_grid": (1,), "replicates": 40}  # fmt: skip
    sampler = td.iid_sampler(toy_spec(1e-4), net["counts"])
    hit = td.alarm_pass("toy", net, truth="artefact", sampler=sampler, control="toy_hit",
                        **shared)  # fmt: skip
    miss = td.alarm_pass("toy", net, truth="nominal", sampler=sampler, control="toy_miss",
                         **shared)  # fmt: skip

    block = td.tradeoff_block(net, hit, miss)["K_1"]["calibrations"]["C0"]
    assert [row["c"] for row in block["per_c"]] == list(td.C_GRID)
    assert block["false_alarm_trials"] == 40 and block["coverage_trials"] == 40
    assert block["coverage_at_calibrated_5pc_false_alarm"]["record"] in (
        "interpolated", "not_bracketed_below", "not_bracketed_above")
    assert miss["truth_rows"] == 1  # truth = nominal does not depend on the cable (J4)


# --- 4. the decomposition is exhaustive and exclusive --------------------------------------------


def decomposition_fixture():
    """Three toy cables, one per non-detected category plus one detected, and two rules."""
    buses, days = [1, 2, 3], 8
    rules = {"down": [2, 3], "up": [1, 1]}  # at K = 2 the configurations are [2, 3] and [1, 1]
    lines = [0, 1, 2]
    downstream = {0: [2], 1: [3], 2: [2]}
    k_by_line = {  # bus 1, 2, 3
        0: [0.0, 1.0, 0.0],  # detected: a huge contrast at its downstream bus
        1: [0.0, 0.0, 1.0],  # a huge contrast too, but the cable has no PV below it
        2: [0.0, 1e-9, 0.0],  # reverses, but the contrast is below the floor
    }
    entries, facts, arrays, usable = {}, {}, {}, {}
    for line in lines:
        entries[line] = {
            "m": np.array([1e-3, 1e-3, 1e-3]),
            "night": np.array([-1e-3, -1e-3, -1e-3]),  # opposite signs: the cable reverses
            "k": np.array(k_by_line[line], dtype=float),
            "buses": list(buses),
            "downstream": list(downstream[line]),
        }
        facts[str(line)] = {"installed_pv_sn_mva": 0.0 if line == 1 else 0.5,
                            "S_l": 0.0 if line == 1 else 1e-4}  # fmt: skip
        arrays[line] = {"n_daylight_valid": np.full(days, 40, dtype=int),
                        "n_night_valid": np.full(days, STEPS - 40, dtype=int)}  # fmt: skip
        usable[line] = np.ones(days, dtype=bool)
    net = toy_net(lines, downstream, rules, np.zeros((len(lines), days, len(buses))),
                  buses=buses, days=days)  # fmt: skip
    net["entries"] = entries
    net["facts"] = {"cable_facts": facts}
    net["usable_rows"] = usable
    loaded = {("toy", "W6", "E-R", 1.5, line): {"arrays": arrays[line]} for line in lines}
    return net, loaded


def test_the_decomposition_categories_are_exhaustive_and_exclusive():
    net, loaded = decomposition_fixture()

    block = td.decomposition_network("toy", net, loaded, "0.01", k=2)

    assert block["pairs"] == 6
    assert sum(block["categories"].values()) == block["pairs"]
    assert set(block["categories"]) == set(td.CATEGORIES)
    # cable 0 -> detected, cable 1 -> asset/physics, cable 2 -> signal strength, rule `up` ->
    # placement for all three cables
    assert block["categories"] == {"placement": 3, "asset_physics": 1, "signal_strength": 1,
                                   "detected": 1}  # fmt: skip
    for line, record in block["per_cable"].items():
        assert sum(record["categories"].values()) == len(net["rule_names"]), line
        assert sum(1 for name in td.CATEGORIES if record["categories"][name]) >= 1
    assert block["non_reversing_cables"] == 1  # only the PV-free cable
    assert block["cables_with_S_l_zero"] == 1
    assert block["signal_capable_cables"] == 2  # cables 0 and 1, by their peak |k|
    assert block["categories_sum_to_the_pairs"] is True


def test_the_decomposition_counts_every_pair_of_every_cable():
    net, loaded = decomposition_fixture()
    block = td.decomposition_network("toy", net, loaded, "0.005", k=2)
    totals = {name: sum(record["categories"][name] for record in block["per_cable"].values())
              for name in td.CATEGORIES}  # fmt: skip
    assert totals == block["categories"]
    assert len(block["per_cable"]) == len(net["lines"])


def test_the_decomposition_refuses_a_cable_whose_downstream_set_is_empty():
    net, loaded = decomposition_fixture()
    net["entries"][0]["downstream"] = []
    with pytest.raises(RuntimeError, match="no downstream bus"):
        td.decomposition_network("toy", net, loaded, "0.01", k=2)


# --- 5. the output file is written once ----------------------------------------------------------


def test_run_refuses_to_overwrite_an_existing_output(tmp_path):
    """The refusal comes before any artefact is read, so nothing is computed."""
    target = tmp_path / "tradeoff.json"
    target.write_text('{"kept": true}')

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        td.run(target)

    assert target.read_text() == '{"kept": true}'


def test_write_new_json_refuses_to_overwrite_as_well(tmp_path):
    """The atomic guard behind `run`: `q1.write_new_json` is exclusive-create."""
    target = tmp_path / "payload.json"
    assert td.q1.write_new_json(target, {"a": 1})
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        td.q1.write_new_json(target, {"a": 2})
