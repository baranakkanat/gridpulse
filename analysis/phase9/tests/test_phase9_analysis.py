"""Unit tests of the Phase 9 analysis core (`phase9_analysis.py`).

Every test here runs on synthetic data, with one exception. No power flow is solved, no
network is loaded and no real `vm` array is read, so the whole file is cheap and computes no
Phase 9 statistic. The exception is the two Stage 0/Stage 4 integration tests. They hash the
frozen, git-ignored research outputs under `outputs/` (`FROZEN_CACHE`). They are skipped only
when that whole cache is absent, as in a fresh clone; a partial or corrupted cache runs them
and fails. The four held-out networks of registration s. 2 are never loaded; the
only place their names appear is the constant tuple the module already carries.

The pieces that need the grid (`network_topology`, `stage1`, `stage3`, `w5_network`) assert
their own registered invariants; they are covered here only through their refusals, which is
all that can be checked while the registration is uncommitted.
"""

from __future__ import annotations

import json
import math
import types

import numpy as np
import pandas as pd
import phase9_analysis as pa
import phase9_sweep as ps
import pytest
import q1_voltage_residual as q1

# --- injected `git` results (s. 12 Stage 0) ------------------------------------------------


def git_untracked(args):
    """`git log` returns no commit: the registration is not tracked in any commit."""
    return (0, "") if args[0] == "log" else (0, "")


def git_modified(args):
    """Tracked, but `git diff --quiet HEAD` exits non-zero: modified against HEAD."""
    return (0, "a" * 40) if args[0] == "log" else (1, "")


def git_clean(args):
    return (0, "b" * 40) if args[0] == "log" else (0, "")


# --- the frozen, git-ignored research cache that Stage 0 hashes (s. 12) ---------------------

# Every file Stage 0 reads that is not tracked in git: Q1's frozen Phase 8 outputs and the
# frozen Phase 6 placements. Derived from the modules' own constants, not retyped.
FROZEN_CACHE = tuple(
    sorted(
        {
            *q1.FROZEN_OUTPUTS,
            q1.FREEZE_FILE,
            *(name for name in pa.PHASE9_HASHES if name.startswith("outputs/")),
        }
    )
)


def frozen_cache_absent(root) -> bool:
    """True only when no file of the frozen cache exists. A partial cache is not absent."""
    return not any((root / name).exists() for name in FROZEN_CACHE)


requires_frozen_cache = pytest.mark.skipif(
    frozen_cache_absent(pa.REPO),
    reason=(
        "the frozen, git-ignored research cache is absent ("
        + ", ".join(FROZEN_CACHE)
        + "): Stage 0/4's integrity checks need these locally generated Phase 6/8 outputs, "
        "which are not part of the public repository"
    ),
)


# --- the registered constants, pinned to the registration's own literals -------------------


def test_registered_constants_match_the_registration():
    """Every s. 8, s. 9 and s. 10 number the module carries, against the literal written in
    `docs/provenance/phase9/phase9_registration.md`.

    The right-hand sides are transcribed from the registration, not read from `pa`, so a
    change to a registered constant fails here instead of propagating silently into the
    statistics. The section and the registration's own wording are quoted per group.
    """
    # s. 8 sigma_tot: "Co-primary: 0.01 and 0.005", "Sensitivity: 0.003 and 0.02"
    assert pa.SIGMA_GRID == (0.003, 0.005, 0.01, 0.02)
    assert pa.SIGMA_CO_PRIMARY == (0.01, 0.005)
    # s. 8 meter configurations: "the first K buses of a rule, K in {1, 2, 4}"
    assert pa.K_GRID == (1, 2, 4)
    # s. 8: "The 25 frozen Phase 6 rules ...: 5 named rules plus random_0...random_19"
    assert pa.EXPECTED_RULES == 25
    # s. 7 sensitivity: "retention at 8 or more daylight steps"
    assert pa.SENSITIVITY_MIN_DAYLIGHT == 8

    # s. 7 failed flows: "0.1 % of all sweep solves, or 1 % of any single run's solves"
    assert pa.FAILED_TOTAL_FRACTION == 0.001
    assert pa.FAILED_RUN_FRACTION == 0.01
    # s. 9 W8: "f*: the smallest f in {1.1, 1.25, 1.5, 2.0}"
    assert pa.W8_FACTORS == (1.1, 1.25, 1.5, 2.0)

    # s. 10 control 2: "A / sigma_tot in {0, 0.003, 0.006, 0.01, 0.02, 0.03, 0.06, 0.1,
    # 0.2, 0.3}"
    assert pa.A_OVER_SIGMA == (0.0, 0.003, 0.006, 0.01, 0.02, 0.03, 0.06, 0.1, 0.2, 0.3)
    # s. 10 control 1: "2,000 replicates per network x condition"
    assert pa.CONTROL1_REPLICATES == 2000
    # s. 10 A*_fa: "2,000 replicates per grid point"; A*_cov: "400 replicates per grid point"
    assert pa.A_STAR_FA_REPLICATES == 2000
    assert pa.A_STAR_COV_REPLICATES == 400
    # s. 10 control 3: "200 permutations"
    assert pa.PERMUTATIONS == 200

    # s. 9 rule thresholds: R1 "at least 0.90", R2 "Jaccard ... >= 0.8", R3 "at least 0.9",
    # R4 "CV ... at most 0.2"
    assert pa.R1_SHARE == 0.90
    assert pa.R2_JACCARD == 0.8
    assert pa.R3_SPEARMAN == 0.9
    assert pa.R4_CV == 0.2
    # s. 7 "D_eff = 0.95 * D_ret" / s. 10 "loses the whole day with probability 0.05"
    assert pa.REMOTE_MISSING == 0.05


def test_the_registration_file_is_the_one_the_constants_were_read_from():
    """The constants above are literals of one file; this pins that file's sha256, so they
    cannot be read against a different revision of the registration."""
    assert pa.REGISTRATION_SHA256 == (
        "737a252dab231b9c5303d4b5e8ad1af0adb93051f0de621d41a38f82af5bc4e1"
    )
    assert pa.REGISTRATION == "docs/provenance/phase9/phase9_registration.md"


# --- toy networks --------------------------------------------------------------------------


def toy_net(edges, parallel=None, in_service=None, switch=None):
    """A minimal stand-in for a pandapower net: only `line` (and optionally `switch`).

    `edges` maps a line index to its (from_bus, to_bus) pair, so two lines may share a pair.
    """
    index = sorted(edges)
    frame = pd.DataFrame(
        {
            "from_bus": [edges[i][0] for i in index],
            "to_bus": [edges[i][1] for i in index],
            "parallel": [1] * len(index) if parallel is None else parallel,
            "in_service": [True] * len(index) if in_service is None else in_service,
        },
        index=index,
    )
    net = types.SimpleNamespace(line=frame)
    if switch is not None:
        net.switch = switch
    return net


TREE = {0: (0, 1), 1: (1, 2), 2: (1, 3)}  # bus 0 is the LV busbar
DUPLICATE = {0: (0, 1), 1: (1, 2), 2: (1, 2)}  # lines 1 and 2 share the bus pair (1, 2)


# --- s. 3: the MultiGraph downstream set and its independent cross-check -------------------


def test_downstream_multigraph_on_a_toy_tree():
    net = toy_net(TREE)
    graph = pa.line_multigraph(net)

    assert pa.downstream_multigraph(graph, 0, 0) == {1, 2, 3}
    assert pa.downstream_multigraph(graph, 0, 1) == {2}
    assert pa.downstream_multigraph(graph, 0, 2) == {3}


def test_downstream_sets_agree_with_the_shortest_path_cross_check_on_a_tree():
    net = toy_net(TREE)

    assert pa.downstream_sets(net, 0, [0, 1, 2]) == {0: {1, 2, 3}, 1: {2}, 2: {3}}
    assert pa.downstream_shortest_path(net, 0, 1) == {2}


def test_multigraph_keys_every_line_so_a_duplicate_bus_pair_stays_two_edges():
    net = toy_net(DUPLICATE)
    graph = pa.line_multigraph(net)

    assert graph.number_of_edges() == 3  # a plain Graph would collapse (1, 2) to one edge
    # removing one of the two parallel edges disconnects nothing
    assert pa.downstream_multigraph(graph, 0, 1) == set()
    assert pa.downstream_multigraph(graph, 0, 2) == set()
    assert pa.downstream_multigraph(graph, 0, 0) == {1, 2}


def test_a_cross_check_disagreement_stops_stage1():
    net = toy_net(DUPLICATE)

    # the plain-Graph derivation still puts bus 2 below line 1 (reading R-a), the MultiGraph
    # one does not, so the two derivations disagree and s. 3 invariant 2 stops Stage 1
    assert pa.downstream_shortest_path(net, 0, 1) == {2}
    with pytest.raises(RuntimeError, match="differs from the independent shortest-path"):
        pa.downstream_sets(net, 0, [1])


def test_downstream_multigraph_rejects_an_unknown_line_or_busbar():
    graph = pa.line_multigraph(toy_net(TREE))
    with pytest.raises(ValueError, match="not an edge"):
        pa.downstream_multigraph(graph, 0, 9)
    with pytest.raises(ValueError, match="not a node"):
        pa.downstream_multigraph(graph, 99, 0)


# --- s. 3 invariant 1 ----------------------------------------------------------------------


def layout_for(buses, busbar=0):
    return types.SimpleNamespace(buses=tuple(buses), lv_busbar=busbar)


def test_structural_invariants_pass_on_a_toy_tree():
    switch = pd.DataFrame({"et": ["l", "b"], "closed": [True, True]}, index=[0, 1])
    out = pa.structural_invariants(toy_net(TREE, switch=switch), layout_for([0, 1, 2, 3]))

    assert out["ok"]
    assert out["lv_buses"] == 4 and out["lines"] == 3
    assert out["line_switches"] == 1 and out["open_line_switches"] == []


def test_structural_invariants_fail_on_a_duplicate_pair_an_open_switch_and_parallel():
    duplicate = pa.structural_invariants(toy_net(DUPLICATE), layout_for([0, 1, 2]))
    assert not duplicate["ok"]
    assert not duplicate["lv_buses_equal_lines_plus_one"]
    assert not duplicate["line_graph_acyclic"]

    switch = pd.DataFrame({"et": ["l"], "closed": [False]}, index=[0])
    opened = pa.structural_invariants(toy_net(TREE, switch=switch), layout_for([0, 1, 2, 3]))
    assert not opened["ok"] and opened["open_line_switches"] == [0]

    parallel = pa.structural_invariants(
        toy_net(TREE, parallel=[1, 2, 1]), layout_for([0, 1, 2, 3])
    )
    assert not parallel["ok"] and not parallel["every_line_parallel_is_one"]

    out_of_service = pa.structural_invariants(
        toy_net(TREE, in_service=[True, False, True]), layout_for([0, 1, 2, 3])
    )
    assert not out_of_service["ok"] and not out_of_service["every_line_in_service"]


# --- s. 7: day retention -------------------------------------------------------------------


def test_retention_keeps_days_with_daylight_and_night_steps():
    out = pa.retention([10, 11, 12], [0, 5, 40], steps=96)

    assert out["retained"] == [11, 12] and out["dropped"] == [10]
    assert out["D_ret"] == 2
    assert out["D_eff"] == pytest.approx(1.9)
    assert out["n_day_median"] == pytest.approx(22.5)
    assert out["n_night_median"] == pytest.approx(73.5)
    assert out["daylight_per_day_min"] == 5 and out["daylight_per_day_max"] == 40


def test_retention_sensitivity_set_needs_eight_daylight_steps():
    out = pa.retention([10, 11, 12], [0, 5, 40], steps=96,
                       min_daylight=pa.SENSITIVITY_MIN_DAYLIGHT)  # fmt: skip

    assert out["retained"] == [12] and out["dropped"] == [10, 11]
    assert out["min_daylight_steps"] == 8


def test_a_scored_day_with_zero_night_steps_is_a_hard_error():
    with pytest.raises(RuntimeError, match="without a night step"):
        pa.retention([10, 11], [40, 96], steps=96)

    # the hard error holds whatever the daylight retention threshold is (s. 7)
    with pytest.raises(RuntimeError, match="without a night step"):
        pa.retention([10, 11], [40, 96], steps=96, min_daylight=8)


def test_retention_refuses_when_no_day_survives():
    with pytest.raises(RuntimeError, match="no scored day is retained"):
        pa.retention([10, 11], [0, 0], steps=96)


# --- s. 8: the Bonferroni z, the bands and the thresholds ---------------------------------


def test_bonferroni_z_at_the_registered_k():
    assert q1.z_bonferroni(1) == pytest.approx(1.9599639845400545, abs=1e-12)
    assert q1.z_bonferroni(2) == pytest.approx(2.241402727604947, abs=1e-12)
    assert q1.z_bonferroni(4) == pytest.approx(2.4977054744123737, abs=1e-12)
    assert pa.Z_95 == pytest.approx(q1.z_bonferroni(1), abs=1e-12)


def test_band_boundaries_are_closed_below_and_open_above():
    low, high = 2.0, 5.0

    assert q1.band(low - 1e-12, low, high) == "A"
    assert q1.band(low, low, high) == "B"
    assert q1.band(high - 1e-12, low, high) == "B"
    assert q1.band(high, low, high) == "C"


def test_thresholds_against_hand_computed_values():
    sigma, n_day, n_night, d_eff, z = 0.01, 40.0, 56.0, 100.0, 2.0

    mean = q1.thresholds(sigma, n_day, n_night, d_eff, z, "mean")

    root = math.sqrt(1.0 / 40.0 + 1.0 / 56.0) / 10.0  # sqrt(d_eff) = 10
    assert mean["F_ind"] == pytest.approx(0.01 / math.sqrt(4000.0))
    assert mean["F_ind"] == pytest.approx(1.5811388300841899e-04)
    assert mean["F_bias"] == pytest.approx(0.0098)
    assert mean["F_C_matched"] == pytest.approx(0.2 * 0.01 * root)
    assert mean["F_C_matched"] == pytest.approx(4.1403933560541256e-05)
    assert mean["F_C_realistic"] == pytest.approx(2.0701966780270628e-04)
    assert mean["level"] == {"low": pytest.approx(3.1622776601683795e-04),
                             "high": pytest.approx(0.0196)}  # fmt: skip
    assert mean["contrast"] == {"low": pytest.approx(8.280786712108251e-05),
                                "high": pytest.approx(4.1403933560541256e-04)}  # fmt: skip

    median = q1.thresholds(sigma, n_day, n_night, d_eff, z, "median_averaging_floors")
    factor = math.sqrt(math.pi / 2.0)
    assert median["F_ind"] == pytest.approx(mean["F_ind"] * factor)
    assert median["F_C_realistic"] == pytest.approx(mean["F_C_realistic"] * factor)
    assert median["F_bias"] == pytest.approx(mean["F_bias"])  # the offset floor is unscaled


def test_threshold_grid_covers_every_registered_sigma_k_and_estimator():
    days = pa.retention([10, 11, 12], [10, 20, 30], steps=96)

    grid = pa.threshold_grid(days, k_all=43)

    assert sorted(grid) == sorted(pa.ESTIMATORS)
    assert sorted(grid["mean"]) == sorted(f"{s:g}" for s in pa.SIGMA_GRID)
    entry = grid["mean"]["0.01"]
    assert entry["co_primary"] and entry["K_all"] == 43
    for k in (1, 2, 4, 43):
        assert entry[f"K_{k}"]["z"] == pytest.approx(q1.z_bonferroni(k))
    assert grid["mean"]["0.005"]["matched_arm_is_band_arithmetic_only"]
    assert not grid["mean"]["0.01"]["matched_arm_is_band_arithmetic_only"]


# --- s. 7, s. 8: the precision floor and the valid-day handling ----------------------------


def test_precision_floor_label():
    assert pa.at_precision_floor(9.9e-7)
    assert not pa.at_precision_floor(1e-6)
    assert not pa.at_precision_floor(-2e-6)
    assert pa.at_precision_floor(-5e-7)
    assert pa.floor_label(5e-7) == {"value": 5e-7, "at_cache_precision_floor": True}


def artefact_arrays(days, daylight, night, n_day, n_night):
    rows = []
    for i in range(len(days)):
        rows.append({
            "dmean_daylight": np.full(2, daylight[i], dtype=np.float64),
            "dmean_night": np.full(2, night[i], dtype=np.float64),
            "n_daylight_valid": n_day[i],
            "n_night_valid": n_night[i],
            "n_daylight_steps": 40,
            "n_night_steps": 56,
            "failed_truth": 0 if n_day[i] else 40,
            "nan_nominal": 0,
        })
    return ps.build_arrays(rows, days, [7, 8])


def test_run_statistics_drops_a_retained_day_without_a_valid_step_and_counts_it():
    arrays = artefact_arrays(
        days=[1, 2, 3, 4],
        daylight=[2e-3, 9e-3, 4e-3, 50.0],
        night=[-1e-3, -9e-3, -3e-3, -50.0],
        n_day=[40, 0, 40, 40],  # day 2 has no valid daylight step
        n_night=[56, 56, 56, 56],
    )

    out = pa.run_statistics(arrays, retained_days=[1, 2, 3])

    assert out["days_retained"] == 3
    assert out["days_used"] == 2  # day 2 dropped, day 4 never retained
    assert out["days_dropped_no_valid_step"] == [2]
    assert out["m"]["mean"] == pytest.approx(np.full(2, 3e-3), rel=1e-6)
    assert out["night"]["mean"] == pytest.approx(np.full(2, -2e-3), rel=1e-6)
    assert out["k"]["mean"] == pytest.approx(np.full(2, 5e-3), rel=1e-6)
    assert out["failed_truth_retained"] == 40  # day 2 only; day 4 is outside retention
    assert out["failed_truth_total"] == 40


def test_run_statistics_also_drops_a_day_without_a_valid_night_step():
    arrays = artefact_arrays([1, 2], [4e-3, 8e-3], [-1e-3, -2e-3], [40, 40], [56, 0])

    out = pa.run_statistics(arrays, retained_days=[1, 2])

    assert out["days_used"] == 1 and out["days_dropped_no_valid_step"] == [2]
    assert out["m"]["mean"] == pytest.approx(np.full(2, 4e-3), rel=1e-6)


def test_run_statistics_refuses_when_no_retained_day_is_usable():
    arrays = artefact_arrays([1], [4e-3], [-1e-3], [0], [56])

    with pytest.raises(RuntimeError, match="no retained day of this run"):
        pa.run_statistics(arrays, retained_days=[1])


# --- s. 8: coverage counting and the Wilson intervals -------------------------------------


def test_wilson_interval_against_hand_computed_values():
    zero = pa.wilson(0, 10)
    assert zero["rate"] == 0.0
    assert zero["low"] == pytest.approx(0.0, abs=1e-12)
    assert zero["high"] == pytest.approx(0.27753, abs=5e-5)

    three = pa.wilson(3, 5)
    assert three["rate"] == pytest.approx(0.6)
    assert three["low"] == pytest.approx(0.23075, abs=5e-5)
    assert three["high"] == pytest.approx(0.88236, abs=5e-5)

    assert pa.wilson(0, 0)["interval"] == "undefined, n = 0"
    assert pa.wilson(0, 0)["rate"] is None
    with pytest.raises(ValueError):
        pa.wilson(3, 2)


def test_coverage_table_counts_bands_and_the_conditional_rates():
    pairs = [("C", True), ("C", True), ("A", True), ("B", False), ("C", False)]

    out = pa.coverage_table(pairs)

    assert out["pairs"] == 5
    assert out["band_counts"] == {"A": 1, "B": 1, "C": 3}
    assert out["coverage"]["successes"] == 3 and out["coverage"]["rate"] == pytest.approx(0.6)
    assert out["coverage_given_intersects"]["rate"] == pytest.approx(2 / 3)
    assert out["coverage_given_not_intersects"]["rate"] == pytest.approx(0.5)
    assert out["intersection_coverage"]["rate"] == pytest.approx(0.6)


def test_coverage_table_is_defined_on_an_empty_conditional_arm():
    out = pa.coverage_table([("C", True), ("A", True)])

    assert out["coverage_given_not_intersects"]["trials"] == 0
    assert out["coverage_given_not_intersects"]["rate"] is None


def test_c_meter_is_the_maximum_over_the_configuration():
    buses = [10, 11, 12, 13]
    k = np.array([1e-3, -5e-3, 2e-3, 0.0])

    assert pa.configuration([11, 13, 10, 12], 2) == [11, 13]
    assert pa.c_meter(k, buses, [11, 13]) == pytest.approx(5e-3)
    assert pa.c_meter(k, buses, [10]) == pytest.approx(1e-3)
    with pytest.raises(ValueError, match="no configuration"):
        pa.configuration([1, 2], 4)


# --- s. 9: R1 ------------------------------------------------------------------------------


def test_r1_pools_the_share_over_the_networks_pairs_and_lists_failing_cables():
    cables = [
        {"line": 1, "m": np.array([2.0, -2.0, 0.5]), "night": np.array([-1.0, 1.0, 5.0])},
        {"line": 2, "m": np.array([3.0, 4.0]), "night": np.array([-1.0, 2.0])},
    ]

    out = pa.r1_network(cables, level_low=1.0)

    assert out["pairs"] == 4 and out["opposite_sign"] == 3
    assert out["share"] == pytest.approx(0.75)
    assert out["holds"] is False
    assert out["failing_cables"] == [{"line": 2, "pairs": 2, "same_or_zero_sign": 1}]


def test_r1_holds_at_the_registered_share_and_is_typed_when_no_pair_is_selected():
    cables = [{"line": 1, "m": np.ones(10), "night": np.array([-1.0] * 9 + [1.0])}]
    assert pa.r1_network(cables, level_low=1.0)["share"] == pytest.approx(0.9)
    assert pa.r1_network(cables, level_low=1.0)["holds"] is True

    empty = pa.r1_network([{"line": 1, "m": np.zeros(3), "night": np.zeros(3)}], level_low=1.0)
    assert empty["pairs"] == 0 and empty["holds"] is None
    assert "undefined, n = 0" in empty["record"]


def test_a_zero_night_value_is_not_an_opposite_sign():
    assert pa.opposite_sign(1.0, -1.0)
    assert not pa.opposite_sign(1.0, 0.0)
    assert not pa.opposite_sign(0.0, 0.0)
    assert not pa.opposite_sign(1.0, 2.0)


# --- s. 9: R2 ------------------------------------------------------------------------------


BUSES = [1, 2, 3, 4]
DOWN = [3, 4]


def r2(m, night, k):
    return pa.r2_cable(np.array(m), np.array(night), np.array(k), BUSES, DOWN, 1.0, 1.0)


def test_r2_holds_when_s_detect_is_inside_downstream_and_matches_ref():
    out = r2([0, 0, 2, 2], [0, 0, -1, -1], [0, 0, 2, 2])

    assert out["S_detect"] == [3, 4] and out["ref"] == [3, 4]
    assert out["subset_of_downstream"] and out["jaccard"] == pytest.approx(1.0)
    assert out["holds"] is True


def test_r2_fails_when_s_detect_leaves_downstream():
    out = r2([2, 0, 2, 2], [-1, 0, -1, -1], [2, 0, 2, 2])

    assert out["S_detect"] == [1, 3, 4]
    assert not out["subset_of_downstream"]
    assert out["holds"] is False


def test_r2_fails_on_a_jaccard_below_the_registered_threshold():
    out = r2([0, 0, 2, 2], [0, 0, -1, -1], [0, 0, 2, 0])

    assert out["S_detect"] == [3] and out["ref"] == [3, 4]
    assert out["jaccard"] == pytest.approx(0.5)
    assert out["holds"] is False


def test_r2_is_not_evaluable_when_ref_and_s_detect_are_both_empty():
    out = r2([0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0])

    assert not out["evaluable"] and out["holds"] is None
    assert math.isnan(out["jaccard"])
    assert "not evaluable" in out["record"]
    assert math.isnan(pa.jaccard(set(), set()))
    assert pa.jaccard({1}, set()) == pytest.approx(0.0)


def test_r2_network_holds_only_when_every_evaluable_cable_holds():
    good = r2([0, 0, 2, 2], [0, 0, -1, -1], [0, 0, 2, 2])
    bad = r2([0, 0, 2, 2], [0, 0, -1, -1], [0, 0, 2, 0])
    skipped = r2([0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0])

    assert pa.r2_network({1: good, 2: skipped})["holds"] is True
    network = pa.r2_network({1: good, 2: bad, 3: skipped})
    assert network["holds"] is False
    assert network["evaluable_cables"] == 2 and network["failing_cables"] == [2]
    assert pa.r2_network({1: skipped})["holds"] is None


# --- s. 9: R3 and R3s ----------------------------------------------------------------------


def test_r3_is_the_per_cable_spearman_against_the_registered_threshold():
    rising = pa.r3_network([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0])
    assert rising["spearman"] == pytest.approx(1.0)
    assert rising["holds"] is True

    falling = pa.r3_network([1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0])
    assert falling["spearman"] == pytest.approx(-1.0)
    assert falling["holds"] is False

    flat = pa.r3_network([1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 3.0, 4.0])
    assert math.isnan(flat["spearman"]) and flat["holds"] is None


def test_r3s_is_a_typed_record_below_three_downstream_buses():
    distance = {1: 0.0, 2: 0.1, 3: 0.2, 4: 0.3}
    m = np.array([1.0, 2.0, 9.0, 4.0])

    out = pa.r3s_cable(m, BUSES, [3, 4], distance)

    assert out["spearman"] is None
    assert out["record"] == "undefined, n = 2 (G2 typed record)"
    assert out["n_downstream"] == 2
    assert out["argmax_bus"] == 3 and out["argmax_in_downstream"]


def test_r3s_reports_the_within_downstream_spearman_and_the_argmax_clause():
    distance = {1: 0.0, 2: 0.1, 3: 0.2, 4: 0.3}
    m = np.array([9.0, 1.0, 2.0, 3.0])

    out = pa.r3s_cable(m, BUSES, [2, 3, 4], distance)

    assert out["spearman"] == pytest.approx(1.0)
    assert out["record"] is None
    assert out["argmax_bus"] == 1 and not out["argmax_in_downstream"]


# --- s. 9: R4 ------------------------------------------------------------------------------


def test_r4_cable_cv_and_evaluability():
    flat = pa.r4_cable(np.array([0.0, 0.0, 1e-3, 1e-3]), BUSES, DOWN, 1e-4)
    assert flat["evaluable"] and flat["cv"] == pytest.approx(0.0)
    assert flat["holds"] is True

    spread = pa.r4_cable(np.array([0.0, 0.0, 1e-3, 3e-3]), BUSES, DOWN, 1e-4)
    assert spread["cv"] == pytest.approx(0.5)
    assert spread["holds"] is False

    quiet = pa.r4_cable(np.array([0.0, 0.0, 1e-9, 1e-9]), BUSES, DOWN, 1e-4)
    assert not quiet["evaluable"] and quiet["holds"] is None

    single = pa.r4_cable(np.array([0.0, 0.0, 1e-3, 0.0]), BUSES, [3], 1e-4)
    assert not single["evaluable"]  # |downstream(l)| < 2


def test_r4_network_aggregates_over_every_evaluable_cable():
    good = pa.r4_cable(np.array([0.0, 0.0, 1e-3, 1e-3]), BUSES, DOWN, 1e-4)
    bad = pa.r4_cable(np.array([0.0, 0.0, 1e-3, 3e-3]), BUSES, DOWN, 1e-4)
    quiet = pa.r4_cable(np.array([0.0, 0.0, 1e-9, 1e-9]), BUSES, DOWN, 1e-4)

    assert pa.r4_network({1: good, 2: quiet})["holds"] is True
    network = pa.r4_network({1: good, 2: bad, 3: quiet})
    assert network["holds"] is False
    assert network["failing_cables"] == [2] and network["evaluable_cables"] == 2
    assert pa.r4_network({1: quiet})["holds"] is None


def test_population_cv_uses_the_population_sd():
    assert pa.population_cv([1.0, 3.0]) == pytest.approx(0.5)
    assert math.isnan(pa.population_cv([]))
    assert math.isnan(pa.population_cv([1.0, -1.0]))  # a zero mean


# --- s. 9: R5, the held-out statistic -----------------------------------------------------


def test_r5_ratio_is_signed_so_a_sign_flip_falls_outside_the_interval():
    flipped = pa.r5_ratio(np.array([-5e-4, 1e-4]), [1, 2], m_pred=1e-3)

    assert flipped["b_star"] == 1
    assert flipped["ratio"] == pytest.approx(-0.5)
    assert flipped["holds"] is False


def test_r5_holds_inside_the_registered_interval_and_at_its_boundaries():
    inside = pa.r5_ratio(np.array([7e-4, 1e-4]), [1, 2], m_pred=1e-3)
    assert inside["ratio"] == pytest.approx(0.7) and inside["holds"] is True

    assert pa.r5_ratio(np.array([5e-4]), [1], m_pred=1e-3)["holds"] is True
    assert pa.r5_ratio(np.array([9e-4]), [1], m_pred=1e-3)["holds"] is True
    assert pa.r5_ratio(np.array([9.1e-4]), [1], m_pred=1e-3)["holds"] is False
    assert pa.r5_ratio(np.array([4.9e-4]), [1], m_pred=1e-3)["holds"] is False


def test_r5_b_star_is_the_argmax_of_abs_m_over_all_buses():
    out = pa.r5_ratio(np.array([1e-4, -8e-4, 6e-4]), [10, 11, 12], m_pred=-1e-3)

    assert out["b_star"] == 11
    assert out["m_at_b_star_pu"] == pytest.approx(-8e-4)
    assert out["ratio"] == pytest.approx(0.8) and out["holds"] is True


def test_r5_is_undefined_when_the_prediction_is_zero():
    out = pa.r5_ratio(np.array([1e-4]), [1], m_pred=0.0)

    assert math.isnan(out["ratio"]) and out["holds"] is False


# --- s. 7: the failed-flow limits ---------------------------------------------------------


def run_record(path, failed_total, failed_retained, solves_retained=16320):
    return {"path": path, "failed_total": failed_total,
            "failed_retained": failed_retained, "solves_retained": solves_retained}  # fmt: skip


def test_failed_flow_check_passes_below_the_registered_limits():
    out = pa.failed_flow_check([run_record("a", 10, 10), run_record("b", 0, 0)], 1_000_000)

    assert out["within_limits"]
    assert out["failed_truth_total"] == 10
    assert out["runs_with_failed_flows"][0]["path"] == "a"
    assert out["runs_over_the_per_run_limit"] == []


def test_failed_flow_check_stops_above_the_total_limit():
    with pytest.raises(RuntimeError, match="Stage 3 stops"):
        pa.failed_flow_check([run_record("a", 2000, 10)], 1_000_000)


def test_failed_flow_check_stops_above_the_per_run_limit():
    with pytest.raises(RuntimeError, match="Stage 3 stops"):
        pa.failed_flow_check([run_record("a", 200, 200, solves_retained=1000)], 10_000_000)


# --- Stage 3's barriers -------------------------------------------------------------------


def test_stage3_refuses_without_stage1s_file(tmp_path):
    with pytest.raises(RuntimeError, match="Stage 1 must run"):
        pa.load_stage1(tmp_path / "phase9_inputs.json")


def test_load_stage1_records_the_hash(tmp_path):
    path = tmp_path / "phase9_inputs.json"
    payload = {"stage": "1"}
    sha = q1.write_new_json(path, payload)

    out = pa.load_stage1(path)

    assert out["sha256"] == sha
    assert out["inputs"] == payload


def test_stage3_refuses_until_the_completeness_barrier_holds(tmp_path):
    specs = [ps.RunSpec("net-a", 7, "E-R", 1.5, 0.8, "W6")]

    with pytest.raises(RuntimeError, match="completeness barrier requires all 99"):
        pa.sweep_barrier(tmp_path, key="0" * 64, specs=specs, days=[1, 2, 3])


# --- s. 12 Stage 0: Stages 1 and 3 refuse while the registration is uncommitted ----------


def test_require_committed_registration_accepts_a_clean_injected_git():
    state = pa.require_committed_registration(git=git_clean)

    assert state["ok"] and state["commit"] == "b" * 40


def test_stage1_refuses_while_the_registration_is_uncommitted(tmp_path):
    with pytest.raises(RuntimeError, match="not tracked in any commit"):
        pa.stage1(inputs_path=tmp_path / "phase9_inputs.json", git=git_untracked)

    assert not (tmp_path / "phase9_inputs.json").exists()


def test_stage1_refuses_while_the_registration_is_modified(tmp_path):
    with pytest.raises(RuntimeError, match="differs from HEAD"):
        pa.stage1(inputs_path=tmp_path / "phase9_inputs.json", git=git_modified)


def test_stage3_refuses_while_the_registration_is_uncommitted(tmp_path):
    with pytest.raises(RuntimeError, match="no --allow-uncommitted flag"):
        pa.stage3(
            inputs_path=tmp_path / "phase9_inputs.json",
            results_path=tmp_path / "phase9_results.json",
            root=tmp_path / "sweep",
            git=git_untracked,
        )

    assert not (tmp_path / "phase9_results.json").exists()


@requires_frozen_cache
def test_stage0_reports_the_commit_state_without_refusing_on_it():
    report = pa.stage0(git=git_untracked)

    assert report["passed"]
    assert report["registration"]["stages_1_to_3_allowed"] is False
    assert report["registration"]["sha256_ok"]
    assert "no --allow-uncommitted" in report["registration"]["note"]


@requires_frozen_cache
def test_stage4_repeats_stage0():
    report = pa.stage0(git=git_clean, label="4")

    assert report["stage"].startswith("4 ")
    assert report["passed"]


# --- the same Stage 0/4 logic without the cache: a self-contained temporary repository ------


def passing_q1_hash_checks():
    return {"outputs": {}, "code": {}, "mismatches": [], "counts_ok": True, "passed": True}


def temporary_repository(tmp_path, monkeypatch, cache: dict[str, bytes]):
    """A throwaway repository root holding the committed registration and `cache` files, with
    the registered Phase 9 hashes taken from those files. Q1's frozen-output check is stubbed
    as passing; only its own tests and the real-cache integration tests exercise it."""
    registration = tmp_path / pa.REGISTRATION
    registration.parent.mkdir(parents=True)
    registration.write_bytes((pa.REPO / pa.REGISTRATION).read_bytes())
    expected = {}
    for name, content in cache.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        expected[name] = q1.sha256_text(content.decode())
    monkeypatch.setattr(pa, "REPO", tmp_path)
    monkeypatch.setattr(pa, "PHASE9_HASHES", expected)
    monkeypatch.setattr(pa.q1, "hash_checks", passing_q1_hash_checks)
    return expected


def test_stage0_and_stage4_report_the_commit_state_on_a_temporary_cache(tmp_path, monkeypatch):
    temporary_repository(tmp_path, monkeypatch, {"outputs/cache.json": b'{"ok": true}'})

    report = pa.stage0(git=git_untracked)
    assert report["passed"]
    assert report["stage"].startswith("0 ")
    assert report["registration"]["stages_1_to_3_allowed"] is False
    assert report["registration"]["sha256_ok"]
    assert "no --allow-uncommitted" in report["registration"]["note"]

    report = pa.stage0(git=git_clean, label="4")
    assert report["stage"].startswith("4 ")
    assert report["registration"]["stages_1_to_3_allowed"] is True
    assert report["passed"]


def test_stage0_fails_on_a_corrupted_or_missing_cache_file(tmp_path, monkeypatch):
    temporary_repository(tmp_path, monkeypatch, {"outputs/cache.json": b'{"ok": true}'})
    cached = tmp_path / "outputs/cache.json"

    cached.write_bytes(b'{"ok": false}')  # corrupted: the content no longer hashes as registered
    with pytest.raises(RuntimeError, match="hash mismatches"):
        pa.stage0(git=git_clean)

    cached.unlink()  # incomplete: a registered file is missing
    with pytest.raises(FileNotFoundError):
        pa.stage0(git=git_clean)


def test_only_a_wholly_absent_frozen_cache_is_skipped(tmp_path):
    assert len(FROZEN_CACHE) == 3
    assert all(name.startswith("outputs/") for name in FROZEN_CACHE)
    assert frozen_cache_absent(tmp_path)

    partial = tmp_path / FROZEN_CACHE[0]  # one file present: the tests run, and fail
    partial.parent.mkdir(parents=True)
    partial.write_text("{}")
    assert not frozen_cache_absent(tmp_path)


def test_there_is_no_allow_uncommitted_flag():
    for stage in ("stage0", "stage1", "stage3", "stage4"):
        with pytest.raises(SystemExit):
            pa.main([stage, "--allow-uncommitted"])


# --- s. 12: refusing to overwrite a results file ------------------------------------------


def test_stage_outputs_refuse_to_overwrite(tmp_path):
    path = tmp_path / "phase9_inputs.json"
    q1.write_new_json(path, {"stage": "1"})

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        q1.write_new_json(path, {"stage": "1"})
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        q1.write_new_json(path, {"stage": "1", "changed": True})

    assert json.loads(path.read_text()) == {"stage": "1"}


# --- W2: the registered hit counts ---------------------------------------------------------


def test_w2_hits_report_a_mismatch_as_a_mismatch():
    rules = {"mandatory": [3, 1, 2, 9], "topology": [1, 2, 9, 8], "risk": [9, 8, 7, 3]}

    out = pa.w2_hits("synthetic-network", [3, 4], rules)

    assert out["per_K"]["K_1"]["hits"] == 1
    assert out["per_K"]["K_1"]["expected"] is None  # no registered count for a toy network
    assert out["per_K"]["K_4"]["hits"] == 2
    assert out["per_K"]["K_4"]["hitting_rules"] == ["mandatory", "risk"]
    assert out["mismatches"] == []


def test_the_controls_extension_point_is_filled():
    """The s. 10 controls are implemented in `test_phase9_controls.py`; this only records
    that Stage 3 no longer writes `"controls": null`."""
    assert callable(pa.controls)
    assert pa.CONTROL_CONDITIONS == (
        "realistic", "sigma_0.005", "sigma_0.02", "biased_meters_matched",
    )  # fmt: skip


# --- W3: cable facts, S_l, m_pred and intersection coverage -------------------------------


def toy_topology():
    """A toy stand-in for `network_topology`'s return value: three lines, two PV units."""
    frame = pd.DataFrame(
        {
            "from_bus": [0, 1, 1],
            "to_bus": [1, 2, 3],
            "r_ohm_per_km": [0.1, 0.2, 0.3],
            "x_ohm_per_km": [0.05, 0.08, 0.09],
            "length_km": [1.0, 2.0, 0.5],
            "max_i_ka": [0.2, 0.2, 0.2],
            "parallel": [1, 1, 1],
            "in_service": [True, True, True],
        },
        index=[0, 1, 2],
    )
    net = types.SimpleNamespace(
        line=frame,
        sgen=pd.DataFrame({"bus": [2, 3], "sn_mva": [0.01, 0.02]}, index=[0, 1]),
    )
    rows = np.array([[0.0, 0.0], [1.0, 2.0], [3.0, 4.0], [0.0, 0.0]])
    return {
        "network": net,
        "available": {1: rows, 2: np.zeros((4, 2))},
        "downstream": {0: {1, 2, 3}, 1: {2}, 2: {3}},
        "local_line": 1,
    }


def test_cable_facts_compute_r_x_installed_pv_p_l_s_l_and_m_pred():
    out = pa.cable_facts(toy_topology(), 1, days=[1, 2], retained=[1])

    assert out["R_ohm"] == pytest.approx(0.4)  # 0.2 ohm/km x 2 km
    assert out["X_ohm"] == pytest.approx(0.16)
    assert out["installed_pv_sn_mva"] == pytest.approx(0.01)
    assert out["P_l_mw"] == pytest.approx(2.0)  # mean of 1.0 and 3.0 over the daylight steps
    assert out["S_l"] == pytest.approx(0.8)
    assert out["m_pred_pu"] == pytest.approx(0.5 * 0.4 * 2.0 / 0.4**2)
    assert out["m_pred_pu"] == pytest.approx(2.5)
    assert out["downstream_buses"] == [2] and out["downstream_size"] == 1
    assert out["is_local_line"]


def test_cable_facts_are_defined_for_a_cable_with_no_downstream_pv():
    topology = toy_topology()
    topology["downstream"][0] = {1}  # bus 1 carries no PV

    out = pa.cable_facts(topology, 0, days=[1, 2], retained=[1])

    assert out["installed_pv_sn_mva"] == 0.0
    assert out["P_l_mw"] == 0.0
    assert out["S_l"] == 0.0 and out["m_pred_pu"] == 0.0
    assert not out["is_local_line"]


def test_intersection_coverage_is_the_w3_ceiling_per_rule_and_k():
    rules = {"mandatory": [2, 3, 9, 8], "random_0": [9, 8, 7, 2]}
    downstream = {1: [2], 2: [3]}

    out = pa.intersection_coverage(rules, downstream)

    assert out["per_rule"]["K_1"]["mandatory"]["intersecting"] == 1
    assert out["per_rule"]["K_1"]["mandatory"]["fraction"] == pytest.approx(0.5)
    assert out["per_rule"]["K_2"]["mandatory"]["intersecting"] == 2
    assert out["per_rule"]["K_1"]["random_0"]["intersecting"] == 0
    assert out["pooled_over_pairs"]["K_2"]["successes"] == 2
    assert out["pooled_over_pairs"]["K_2"]["trials"] == 4


# --- the Stage 3 composition blocks, on synthetic per-bus statistics ----------------------


SYNTH_BUSES = [1, 2, 3, 4]
SYNTH_DOWN = {1: [3, 4]}
SYNTH_RULES = {"mandatory": [3, 1, 2, 4], "random_0": [1, 2, 3, 4]}


def synthetic_stats(daylight, night):
    daylight = np.asarray(daylight, dtype=float)
    night = np.asarray(night, dtype=float)
    return {
        "m": {"mean": daylight, "median": daylight},
        "night": {"mean": night, "median": night},
        "k": {"mean": daylight - night, "median": daylight - night},
        "days_used": 170,
        "days_dropped_no_valid_step": [],
    }


def synthetic_thresholds(k_all=4):
    days = pa.retention([1, 2, 3], [40, 41, 42], steps=96)
    return pa.threshold_grid(days, k_all=k_all)


def test_coverage_block_bands_every_rule_family_and_carries_the_ceiling():
    stats = synthetic_stats([1e-7, 1e-7, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    entries = {1: pa._rule_inputs(SYNTH_BUSES, SYNTH_DOWN[1], stats, "mean")}

    out = pa.coverage_block(entries, SYNTH_RULES, synthetic_thresholds()["mean"]["0.01"], "mean")

    assert sorted(out["per_K"]) == ["K_1", "K_2", "K_4"]
    families = out["per_K"]["K_1"]["families"]
    assert sorted(families) == ["all", "named", "random"]
    # mandatory's first bus is 3 (downstream, |k| = 0.01); random_0's is 1 (off-downstream)
    assert families["all"]["pairs"] == 2
    assert families["all"]["band_counts"]["C"] == 1
    assert families["named"]["coverage"]["rate"] == pytest.approx(1.0)
    assert families["random"]["coverage"]["rate"] == pytest.approx(0.0)
    assert families["all"]["intersection_coverage"]["rate"] == pytest.approx(0.5)
    assert out["per_K"]["K_1"]["z"] == pytest.approx(q1.z_bonferroni(1))


def test_rule_block_reports_every_rule_and_the_reversal_of_each_failing_cable():
    good = synthetic_stats([1e-7, 1e-7, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    bad = synthetic_stats([5e-3, 1e-7, 5e-3, 5e-3], [-5e-3, 0.0, -5e-3, 5e-3])
    entries = {
        1: pa._rule_inputs(SYNTH_BUSES, [3, 4], good, "mean"),
        2: pa._rule_inputs(SYNTH_BUSES, [3, 4], bad, "mean"),
    }
    facts = {
        "1": {"S_l": 1.0, "P_l_mw": 0.02, "installed_pv_sn_mva": 0.03},
        "2": {"S_l": 2.0, "P_l_mw": 0.0, "installed_pv_sn_mva": 0.0},
    }
    distance = {1: 0.0, 2: 0.1, 3: 0.2, 4: 0.3}
    bundle = synthetic_thresholds()["mean"]["0.01"]["K_4"]

    out = pa.rule_block(entries, facts, distance, bundle, "synthetic")

    assert out["z"] == pytest.approx(q1.z_bonferroni(4))
    assert out["R1"]["holds"] is False  # cable 2's bus 4 has the same sign at night
    assert out["R2"]["failing_cables"] == [2]  # S_detect leaves downstream(2)
    assert out["R3"]["cables"] == 2
    assert set(out["R3s"]) == {"1", "2"}
    assert out["R3s"]["1"]["record"] == "undefined, n = 2 (G2 typed record)"
    assert "2" in out["failing_cables"]
    reversal = out["failing_cables"]["2"]
    assert reversal["P_l_mw"] == 0.0
    assert reversal["sign_daylight"] == 1
    assert reversal["downstream_flow_reverses"] is False  # both downstream means are positive
    assert reversal["hypothesis"] == pa.HYPOTHESES["R1_R2"]


def test_reversal_record_detects_a_reversing_downstream_flow():
    stats = synthetic_stats([0.0, 0.0, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    entry = pa._rule_inputs(SYNTH_BUSES, [3, 4], stats, "mean")

    out = pa.reversal_record(entry, {"P_l_mw": 0.5, "installed_pv_sn_mva": 1.0})

    assert out["sign_daylight"] == 1 and out["sign_night"] == -1
    assert out["downstream_flow_reverses"] is True
    assert out["P_l_mw"] == pytest.approx(0.5)


def test_r6_identity_reports_agreement_over_sigma_k_and_estimator():
    stats = synthetic_stats([0.0, 0.0, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    entry = {
        "buses": SYNTH_BUSES,
        "downstream": [3, 4],
        "mean": np.asarray(stats["k"]["mean"], dtype=float),
        "median": np.asarray(stats["k"]["median"], dtype=float),
    }

    out = pa.r6_identity(entry, SYNTH_RULES, synthetic_thresholds())

    assert out["rule"] == "R6" and "identity" in out["status"]
    assert out["identity_holds_everywhere"] is True
    assert out["per_estimator"]["mean"]["0.01"]["K_1"]["agree"] == 2
    assert out["per_estimator"]["mean"]["0.01"]["K_1"]["disagree"] == []
    assert sorted(out["per_estimator"]) == sorted(pa.ESTIMATORS)


def test_r6_identity_lists_a_disagreement_rather_than_hiding_it():
    # bus 3 is downstream but silent, so an intersecting configuration is not band C
    stats = synthetic_stats([0.0, 0.0, 0.0, 5e-3], [0.0, 0.0, 0.0, -5e-3])
    entry = {
        "buses": SYNTH_BUSES,
        "downstream": [3, 4],
        "mean": np.asarray(stats["k"]["mean"], dtype=float),
        "median": np.asarray(stats["k"]["median"], dtype=float),
    }

    out = pa.r6_identity(entry, {"mandatory": [3, 1, 2, 4]}, synthetic_thresholds())

    k1 = out["per_estimator"]["mean"]["0.01"]["K_1"]
    assert k1["identity_holds"] is False
    assert k1["disagree"] == [{"rule": "mandatory", "band": "A", "intersects": True}]
    assert out["identity_holds_everywhere"] is False


# --- W1 (s. 12.5): R1/R3s/R4 on both sets of arrays, reading R-s ---------------------------


W1_DISTANCE = {1: 0.0, 2: 0.1, 3: 0.2, 4: 0.3}
W1_ENTRY = {"buses": SYNTH_BUSES, "downstream": [3, 4]}
W1_RULE_KEYS = ["R1", "R3s", "R4", "z", "z_F_C_real", "z_F_ind"]


def write_q1_results(monkeypatch, tmp_path, code, stats):
    """A synthetic stand-in for the committed `results/q1_results.json`, so the W1 tests read
    no real Q1 artefact and depend on no repository data."""
    path = tmp_path / "q1_results.json"
    path.write_text(json.dumps({"networks": {code: {
        "buses": SYNTH_BUSES,
        "per_bus": {name: {which: [float(v) for v in stats[name][which]]
                           for which in ("mean", "median")}  # fmt: skip
                    for name in ("m", "k", "night")},  # fmt: skip
    }}}))
    monkeypatch.setattr(pa, "Q1_RESULTS", path)


def w1_thresholds():
    """One z_{K_all} bundle per co-primary sigma_tot, the shape the Stage 3 call site builds."""
    grid = synthetic_thresholds()["mean"]
    return {f"{sigma:g}": grid[f"{sigma:g}"]["K_4"] for sigma in pa.SIGMA_CO_PRIMARY}


def test_w1_evaluates_the_rules_on_both_the_sweep_and_the_q1_arrays(monkeypatch, tmp_path):
    """s. 12.5 reads "R1/R3s/R4 ... from Q1's committed per-bus arrays, checked against the
    sweep artefacts", so each co-primary sigma_tot carries a full rule block per side."""
    stats = synthetic_stats([1e-7, 1e-7, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    write_q1_results(monkeypatch, tmp_path, "synthetic", stats)

    out = pa.w1_comparison("synthetic", W1_ENTRY, stats, line=1, distance=W1_DISTANCE,
                           thresholds=w1_thresholds())  # fmt: skip

    fidelity = out["rule_fidelity"]
    assert sorted(fidelity["per_sigma_tot"]) == ["0.005", "0.01"]
    for sigma in ("0.005", "0.01"):
        side = fidelity["per_sigma_tot"][sigma]
        for which in ("from_sweep_artefacts", "from_q1_committed_arrays"):
            assert sorted(side[which]) == W1_RULE_KEYS
            assert sorted(side["verdicts"][which]) == ["R1", "R3s", "R3s_argmax_in_downstream",
                                                       "R4"]  # fmt: skip
            assert side[which]["R1"]["holds"] is True
        assert side["verdicts_agree"] is True
    assert fidelity["verdicts_agree_everywhere"] is True
    assert fidelity["max_abs_difference_pu"] == 0.0
    assert out["max_abs_difference_pu"] == 0.0 and out["meets_expectation"] is True


def test_w1_reports_a_disagreement_between_the_two_sets_of_arrays(monkeypatch, tmp_path):
    """The pin on the dual evaluation: Q1's committed arrays carry a night-sign reversal at
    bus 4 that the sweep's do not, so R1 holds on one side and fails on the other. Evaluating
    one set of arrays twice could not produce this, and the gap is reported, not reconciled.
    """
    sweep = synthetic_stats([1e-7, 1e-7, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    committed = synthetic_stats([1e-7, 1e-7, 5e-3, 5e-3], [0.0, 0.0, -5e-3, 5e-3])
    write_q1_results(monkeypatch, tmp_path, "synthetic", committed)

    out = pa.w1_comparison("synthetic", W1_ENTRY, sweep, line=1, distance=W1_DISTANCE,
                           thresholds=w1_thresholds())  # fmt: skip

    fidelity = out["rule_fidelity"]
    for sigma in ("0.005", "0.01"):
        side = fidelity["per_sigma_tot"][sigma]
        assert side["from_sweep_artefacts"]["R1"]["holds"] is True
        assert side["from_q1_committed_arrays"]["R1"]["holds"] is False
        assert side["verdicts"]["from_sweep_artefacts"]["R1"] is True
        assert side["verdicts"]["from_q1_committed_arrays"]["R1"] is False
        assert side["verdicts_agree"] is False
    assert fidelity["verdicts_agree_everywhere"] is False
    assert fidelity["max_abs_difference_pu"] == pytest.approx(1e-2)  # the night reversal
    assert out["meets_expectation"] is False  # the difference is reported, not reconciled
    assert out["per_statistic"]["night_mean"]["argmax_bus"] == 4
    assert out["per_statistic"]["m_mean"]["max_abs_difference_pu"] == 0.0


def test_w1_refuses_a_q1_bus_order_that_differs_from_the_sweeps(monkeypatch, tmp_path):
    stats = synthetic_stats([1e-7, 1e-7, 5e-3, 5e-3], [0.0, 0.0, -5e-3, -5e-3])
    write_q1_results(monkeypatch, tmp_path, "synthetic", stats)

    with pytest.raises(RuntimeError, match="Q1's bus order differs"):
        pa.w1_comparison("synthetic", {"buses": [4, 3, 2, 1], "downstream": [3, 4]}, stats,
                         line=1, distance=W1_DISTANCE, thresholds=w1_thresholds())  # fmt: skip


def test_w8_block_reports_f_star_and_the_slope_ratios():
    # |k| = 2 x the per-bus value here, and it is exactly linear in (f - 1)
    by_factor = {
        1.1: synthetic_stats([0, 0, 2e-3, 2e-3], [0, 0, -2e-3, -2e-3]),
        1.25: synthetic_stats([0, 0, 5e-3, 5e-3], [0, 0, -5e-3, -5e-3]),
        1.5: synthetic_stats([0, 0, 1e-2, 1e-2], [0, 0, -1e-2, -1e-2]),
        2.0: synthetic_stats([0, 0, 2e-2, 2e-2], [0, 0, -2e-2, -2e-2]),
    }

    out = pa.w8_block(by_factor, [3, 4], SYNTH_BUSES, synthetic_thresholds()["mean"])

    assert out["factors"] == ["1.1", "1.25", "1.5", "2"]
    assert out["max_abs_k_downstream_pu"]["1.5"]["value"] == pytest.approx(2e-2)
    assert out["slopes_per_unit_r_increment"] == {
        "1.1": pytest.approx(0.04), "1.25": pytest.approx(0.04),
        "1.5": pytest.approx(0.04), "2": pytest.approx(0.04),
    }  # fmt: skip
    assert out["slope_ratio_to_f_1.5"]["2"] == pytest.approx(1.0)  # exact linearity
    assert out["max_abs_k_ratio_to_f_1.5"]["2"] == pytest.approx(2.0)
    assert out["per_sigma"]["0.01"]["f_star"] == 1.1  # every factor clears the toy threshold
    assert out["per_sigma"]["0.01"]["band_C_factors"] == [1.1, 1.25, 1.5, 2.0]
    assert out["hypothesis"] == pa.HYPOTHESES["W8"]


def test_w8_f_star_is_the_smallest_factor_that_reaches_band_c():
    by_factor = {
        1.1: synthetic_stats([0, 0, 2e-4, 2e-4], [0, 0, -2e-4, -2e-4]),
        1.5: synthetic_stats([0, 0, 1e-3, 1e-3], [0, 0, -1e-3, -1e-3]),
        2.0: synthetic_stats([0, 0, 2e-3, 2e-3], [0, 0, -2e-3, -2e-3]),
    }

    out = pa.w8_block(by_factor, [3, 4], SYNTH_BUSES, synthetic_thresholds()["mean"])

    assert out["per_sigma"]["0.01"]["f_star"] == 2.0
    assert out["per_sigma"]["0.01"]["band_C_factors"] == [2.0]


def test_w8_block_records_f_star_as_not_reached_when_no_factor_clears_the_band():
    by_factor = {f: synthetic_stats([0, 0, 1e-9, 1e-9], [0, 0, 0, 0]) for f in (1.1, 1.5)}

    out = pa.w8_block(by_factor, [3, 4], SYNTH_BUSES, synthetic_thresholds()["mean"])

    assert out["per_sigma"]["0.01"]["f_star"] is None
    assert "not reached" in out["per_sigma"]["0.01"]["f_star_record"]


def test_w9_block_compares_the_sign_split_and_the_r_only_prediction():
    reference = synthetic_stats([0, 0, 1e-3, 1e-3], [0, 0, -1e-3, -1e-3])
    by_factor = {
        1.25: synthetic_stats([0, 0, 1e-3, 1e-3], [0, 0, -1e-3, -1e-3]),  # ratio 1.0
        1.5: synthetic_stats([0, 0, 2e-3, 2e-3], [0, 0, -2e-3, -2e-3]),  # ratio 2.0
    }

    out = pa.w9_block(by_factor, reference, [3, 4], SYNTH_BUSES)

    quarter = out["per_factor"]["1.25"]
    assert quarter["r_only_prediction"] == pytest.approx(0.5)
    assert quarter["max_abs_k_downstream_ratio_to_E_R_1.5"] == pytest.approx(1.0)
    assert quarter["relative_deviation_from_prediction"] == pytest.approx(1.0)
    assert quarter["deviation_exceeds_10_percent"] is True
    assert quarter["sign_split_vs_E_R_1.5"]["unchanged"] is True

    half = out["per_factor"]["1.5"]
    assert half["r_only_prediction"] == pytest.approx(1.0)
    assert half["deviation_exceeds_10_percent"] is True
    assert out["hypothesis"] == pa.HYPOTHESES["W9"]


def test_w9_block_detects_a_changed_sign_split():
    reference = synthetic_stats([0, 0, 1e-3, 1e-3], [0, 0, -1e-3, -1e-3])
    flipped = {1.5: synthetic_stats([0, 0, -2e-3, 2e-3], [0, 0, 2e-3, -2e-3])}

    out = pa.w9_block(flipped, reference, [3, 4], SYNTH_BUSES)

    split = out["per_factor"]["1.5"]["sign_split_vs_E_R_1.5"]
    assert split["downstream_signs_unchanged"] == 1 and split["downstream_buses"] == 2
    assert split["unchanged"] is False
