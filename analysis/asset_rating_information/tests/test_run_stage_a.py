"""Tests for the Mission 12 Stage A runner (`run_stage_a.py`), protocol revision 2.1.

**No power flow runs here.** An autouse fixture replaces `pandapower.runpp` with a function
that raises, so any accidental solve fails the test rather than passing quietly. Building a
pandapower network runs no flow, which is what lets the topology tests use a real (if tiny)
network instead of a hand-written parent-pointer array.

The table builder is exercised against a **synthetic cache** written to `tmp_path` in round
numbers, so the export formula, the `volt_ok` conjunction, the NaN carry-through and the 70 %
table-line selection are checked against values computed by hand, not against the Phase 5
cache (which the tests never read).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

HERE = Path(__file__).resolve().parents[1]
for _path in (HERE, HERE.parents[1] / "src"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import ratings_core as rc  # noqa: E402
import run_stage_a as rs  # noqa: E402

# --- the no-power-flow guard ---------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_power_flow(monkeypatch):
    """Protocol s. 10: new AC solves live in `control-d` alone, so no test may run one."""
    import pandapower as pp

    def refuse(*args, **kwargs):
        raise AssertionError("a test in test_run_stage_a.py tried to run a power flow")

    monkeypatch.setattr(pp, "runpp", refuse)
    return refuse


def test_the_guard_really_bites():
    import pandapower as pp

    with pytest.raises(AssertionError, match="tried to run a power flow"):
        pp.runpp(None)


# --- A. a synthetic network (built, never solved) ------------------------------------------

#: feeder A: busbar -> b0 -> b1 -> b2 (std types A, A, B); feeder B: busbar -> b3 -> b4 (A, A).
SYNTHETIC_LINES = ((0, 1, "A"), (1, 2, "A"), (2, 3, "B"), (0, 4, "A"), (4, 5, "A"))
SYNTHETIC_PARENT = (-1, 0, 1, -1, 3)
SYNTHETIC_FEEDER = (0, 0, 0, 3, 3)
SYNTHETIC_DEPTH = (1, 2, 3, 1, 2)
SYNTHETIC_ROUTES = (0, 0, 1, 2, 2)


def synthetic_net(extra_line: tuple[int, int] | None = None):
    """A 1-transformer, 6-bus, radial LV network with round parameters. Building it runs no
    flow. `extra_line` adds one more line, which the tree assertion must reject."""
    import pandapower as pp

    net = pp.create_empty_network()
    mv = pp.create_bus(net, vn_kv=20.0, name="mv")
    lv = [pp.create_bus(net, vn_kv=0.4, name=f"lv{i}") for i in range(6)]
    pp.create_ext_grid(net, mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net,
        hv_bus=mv,
        lv_bus=lv[0],
        sn_mva=1.0,
        vn_hv_kv=20.0,
        vn_lv_kv=0.4,
        vkr_percent=1.0,
        vk_percent=4.0,
        pfe_kw=0.0,
        i0_percent=0.0,
    )
    edges = list(SYNTHETIC_LINES)
    if extra_line is not None:
        edges.append((extra_line[0], extra_line[1], "A"))
    for from_bus, to_bus, std in edges:
        index = pp.create_line_from_parameters(
            net,
            from_bus=lv[from_bus],
            to_bus=lv[to_bus],
            length_km=0.1,
            r_ohm_per_km=0.2,
            x_ohm_per_km=0.1,
            c_nf_per_km=0.0,
            max_i_ka=0.2,
        )
        net.line.at[index, "std_type"] = std
    for bus in (lv[3], lv[5]):
        pp.create_sgen(net, bus=bus, p_mw=0.0, sn_mva=1.0)
    return net, lv


def test_line_topology_is_a_tree_with_the_expected_parents_feeders_and_depths():
    net, lv = synthetic_net()
    topology = rs.line_topology(net)
    assert topology.lv_busbar == lv[0]
    assert topology.parent_line.tolist() == list(SYNTHETIC_PARENT)
    assert topology.feeder_of.tolist() == list(SYNTHETIC_FEEDER)
    assert topology.depth.tolist() == list(SYNTHETIC_DEPTH)
    assert topology.std_type.tolist() == ["A", "A", "B", "A", "A"]
    assert topology.checks["is_tree"] is True
    assert topology.checks["cycles"] == 0
    assert topology.checks["n_lines"] == topology.checks["n_lines_in_tree"] == 5
    assert topology.checks["n_buses_in_tree"] == 6
    assert topology.checks["n_feeders"] == 2
    assert topology.checks["lines_out_of_tree"] == []
    assert topology.checks["df_all_one"] and topology.checks["parallel_all_one"]
    assert topology.checks["all_in_service"]


def test_routes_group_series_segments_of_one_std_type_within_one_feeder():
    net, _ = synthetic_net()
    topology = rs.line_topology(net)
    assert topology.route_of.tolist() == list(SYNTHETIC_ROUTES)
    assert topology.checks["n_routes"] == 3
    # the same grouping the core computes from the parent description alone (protocol s. 5, U4)
    assert rc.routes(SYNTHETIC_PARENT, ["A", "A", "B", "A", "A"], SYNTHETIC_FEEDER).tolist() == (
        list(SYNTHETIC_ROUTES)
    )


def test_root_paths_of_the_synthetic_tree():
    net, _ = synthetic_net()
    topology = rs.line_topology(net)
    assert rc.root_path(topology.parent_line, 2).tolist() == [2, 1, 0]
    assert rc.root_path(topology.parent_line, 4).tolist() == [4, 3]
    assert rc.root_path(topology.parent_line, 0).tolist() == [0]


def test_line_topology_rejects_a_cycle():
    net, _ = synthetic_net(extra_line=(3, 5))  # closes a loop between the two feeders
    with pytest.raises(ValueError, match="not a tree"):
        rs.line_topology(net)


def test_line_topology_rejects_parallel_lines():
    net, _ = synthetic_net(extra_line=(0, 1))  # a second line on the same bus pair
    with pytest.raises(ValueError, match="parallel lines"):
        rs.line_topology(net)


def test_downstream_buses_walks_the_subtree():
    net, lv = synthetic_net()
    topology = rs.line_topology(net)
    assert rs.downstream_buses(topology, 0).tolist() == sorted([lv[1], lv[2], lv[3]])
    assert rs.downstream_buses(topology, 2).tolist() == [lv[3]]
    assert rs.downstream_buses(topology, 3).tolist() == sorted([lv[4], lv[5]])


# --- B. the P/E split ----------------------------------------------------------------------


def test_period_of_alternates_in_seven_day_blocks_from_day_35():
    assert [rs.period_of(d) for d in range(35, 42)] == ["P"] * 7
    assert [rs.period_of(d) for d in range(42, 49)] == ["E"] * 7
    assert [rs.period_of(d) for d in range(49, 56)] == ["P"] * 7
    assert rs.period_of(364) == rs.PERIODS[((364 - 35) // 7) % 2]


def test_the_p_e_split_partitions_every_study_day_into_whole_blocks():
    labels = {day: rs.period_of(day) for day in rs.DAYS}
    assert set(labels.values()) == {"P", "E"}
    blocks = {}
    for day, label in labels.items():
        blocks.setdefault((day - rs.DAYS[0]) // rs.PERIOD_BLOCK, set()).add(label)
    assert all(len(value) == 1 for value in blocks.values())  # no block straddles the split
    # 330 days = 47 whole blocks plus day 364 alone in block 47 (odd, so E)
    assert sum(label == "P" for label in labels.values()) == 168
    assert sum(label == "E" for label in labels.values()) == 162
    assert len(labels) == len(rs.DAYS) == 330


# --- C. the table builder on a synthetic cache ---------------------------------------------

FAKE_CODE = "1-LV-rural1--2-sw"
FAKE_NAME = "rural1"
FAKE_DAYS = (35, 36, 42, 43)  # two P days then two E days
FAKE_RATING = np.array([1.0, 2.0])
#: 4 quarter-hours a day; the first is dark, so three daylight steps remain per day.
FAKE_AVAILABLE_DAY = np.array([[0.0, 0.0], [0.4, 0.8], [1.0, 3.0], [0.2, 0.4]])
#: per line, the loading in % of the record in P and in E. Table lines need P-or-E max > 70 %.
FAKE_LOADING = {0: (90.0, 20.0), 1: (60.0, 60.0), 2: (10.0, 85.0), 3: (30.0, 30.0), 4: (85.0, 85.0)}
FAKE_TABLE_LINES = [0, 2, 4]
#: where the fake cache is poked, in **npz** step indices (step 0 is dark and dropped).
NAN_DAY, NAN_STEP, NAN_LEVEL, NAN_LINE = 35, 2, 5, 0
VOLT_DAY, VOLT_STEP, VOLT_LEVEL = 36, 1, 3


def fake_available() -> np.ndarray:
    available = np.zeros((max(FAKE_DAYS) + 1, 4, 2))
    for day in FAKE_DAYS:
        available[day] = FAKE_AVAILABLE_DAY
    return available


def write_fake_cache(root: Path) -> Path:
    """A Phase-5-shaped cache in round numbers: `line`, `trafo`, `margins`, `vm`."""
    folder = root / FAKE_CODE / "nominal"
    folder.mkdir(parents=True, exist_ok=True)
    for day in FAKE_DAYS:
        period = 0 if rs.period_of(day) == "P" else 1
        line = np.zeros((4, rc.N_LEVELS, 5), dtype=np.float32)
        for index, values in FAKE_LOADING.items():
            line[:, :, index] = values[period]
        trafo = np.zeros((4, rc.N_LEVELS, 4), dtype=np.float32)
        trafo[:, :, 2] = 50.0
        margins = np.full((4, rc.N_LEVELS, 4), -1.0, dtype=np.float32)
        if day == NAN_DAY:
            line[NAN_STEP, NAN_LEVEL, NAN_LINE] = np.nan
        if day == VOLT_DAY:
            margins[VOLT_STEP, VOLT_LEVEL, 1] = 0.5  # undervoltage margin > 0, overvoltage <= 0
        np.savez_compressed(
            folder / f"day_{day:03d}.npz",
            line=line,
            trafo=trafo,
            margins=margins,
            vm=np.ones((4, rc.N_LEVELS, 6), dtype=np.float32),
        )
    return folder


@pytest.fixture
def fake_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "SENSE_CACHE", tmp_path / "cache")
    monkeypatch.setattr(rs, "DAYS", FAKE_DAYS)
    write_fake_cache(tmp_path / "cache")
    return tmp_path


def test_step_export_is_the_protocol_formula():
    export = rs.step_export(FAKE_AVAILABLE_DAY, FAKE_RATING)
    assert export.shape == (4, rc.N_LEVELS)
    assert export[0].tolist() == [0.0] * rc.N_LEVELS  # the dark step exports nothing
    # by hand: available (1.0, 3.0), rating (1.0, 2.0), cap 0.5 -> min(1, 0.5) + min(3, 1) = 1.5
    assert export[2, 5] == pytest.approx(1.5 * 0.25)
    assert export[2, 0] == pytest.approx((1.0 + 2.0) * 0.25)  # cap 1.0 clips unit 1 at its rating
    assert export[1, 0] == pytest.approx((0.4 + 0.8) * 0.25)  # below the rating: nothing clipped
    assert export[3, -1] == 0.0  # cap 0


def test_build_tables_selects_table_lines_at_the_70_percent_threshold(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    assert built.tables["P"].line_ids.tolist() == FAKE_TABLE_LINES
    assert built.tables["E"].line_ids.tolist() == FAKE_TABLE_LINES
    assert built.diagnostics["n_lines"] == 5
    # the dropped lines are exactly those whose P-or-E maximum is at or below 70 %
    dropped = [i for i in FAKE_LOADING if i not in FAKE_TABLE_LINES]
    assert dropped == [1, 3]
    assert all(max(FAKE_LOADING[i]) <= rc.TABLE_LOADING_PCT for i in dropped)
    assert all(max(FAKE_LOADING[i]) > rc.TABLE_LOADING_PCT for i in FAKE_TABLE_LINES)


def test_build_tables_counts_daylight_steps_per_period(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    assert built.diagnostics["P"]["daylight_steps"] == 6  # two P days x three lit steps
    assert built.diagnostics["E"]["daylight_steps"] == 6
    assert built.diagnostics["daylight_steps_total"] == 12
    assert built.tables["P"].n_steps == 6
    assert built.index["P"]["day"].tolist() == [35, 35, 35, 36, 36, 36]
    assert built.index["P"]["step_of_day"].tolist() == [1, 2, 3, 1, 2, 3]
    assert built.index["E"]["day"].tolist() == [42, 42, 42, 43, 43, 43]
    # the step index is the position in the year's daylight sequence, P and E interleaved
    assert built.index["P"]["step_index"].tolist() == [0, 1, 2, 3, 4, 5]
    assert built.index["E"]["step_index"].tolist() == [6, 7, 8, 9, 10, 11]


def test_build_tables_carries_the_export_and_the_loadings_through(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    table = built.tables["P"]
    expected = rs.step_export(FAKE_AVAILABLE_DAY, FAKE_RATING)[1:]
    assert table.export[:3] == pytest.approx(expected)
    assert table.export[3:] == pytest.approx(expected)
    finite = table.load[0]  # step 0 of P carries no NaN
    assert finite[:, 0].tolist() == [90.0] * rc.N_LEVELS  # line 0 in P
    assert finite[:, 1].tolist() == [10.0] * rc.N_LEVELS  # line 2 in P
    assert finite[:, 2].tolist() == [85.0] * rc.N_LEVELS  # line 4 in P
    assert built.tables["E"].load[0][:, 1].tolist() == [85.0] * rc.N_LEVELS  # line 2 in E


def test_build_tables_volt_ok_needs_both_margins_at_or_below_zero(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    table = built.tables["P"]
    # day 36 is the second P day, so its npz step 1 is table step 3
    assert table.volt_ok[3, VOLT_LEVEL] is np.False_ or not table.volt_ok[3, VOLT_LEVEL]
    others = np.delete(table.volt_ok.reshape(-1), 3 * rc.N_LEVELS + VOLT_LEVEL)
    assert others.all()  # every other (step, level) has both margins <= 0
    assert built.diagnostics["P"]["overvoltage_ok_but_undervoltage_not"] == 1
    assert built.diagnostics["E"]["overvoltage_ok_but_undervoltage_not"] == 0


def test_build_tables_carries_nans_through_and_the_core_rejects_that_level(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    table = built.tables["P"]
    # day 35 is the first P day, so its npz step 2 is table step 1; line 0 is column 0
    assert np.isnan(table.load[1, NAN_LEVEL, 0])
    assert not table.finite[1, NAN_LEVEL]
    assert table.finite.sum() == table.finite.size - 1
    assert built.diagnostics["P"]["nan_step_levels"] == 1
    assert built.diagnostics["E"]["nan_step_levels"] == 0
    # the NaN rule (protocol s. 10): that level is inadmissible, so the decision steps past it
    level = rc.decide(table, 100.0, 100.0).level
    assert level[1] != NAN_LEVEL


def test_build_tables_reports_both_daylight_thresholds(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    assert (
        built.diagnostics["daylight_steps_total"]
        == built.diagnostics["daylight_steps_total_above_1e-9"]
    )


def test_candidate_pools_split_between_the_periods(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    pools = rs._pools(built.tables, built.tables["P"].line_ids, 0.2)
    assert pools["threshold_pct"] == pytest.approx(80.0)
    assert pools["P"] == [0, 4]  # 90 % and 85 % in P
    assert pools["E"] == [2, 4]  # 85 % in E
    assert pools["P_union_E"] == [0, 2, 4]
    assert pools["E_only"] == [2]
    assert (pools["n_P"], pools["n_E"], pools["n_E_only"]) == (2, 2, 1)


def test_concat_tables_stacks_the_periods(fake_cache):
    built = rs.build_tables(FAKE_CODE, fake_available(), FAKE_RATING)
    certificate = rs.concat_tables(built.tables)
    assert certificate.n_steps == built.tables["P"].n_steps + built.tables["E"].n_steps
    assert certificate.line_ids.tolist() == FAKE_TABLE_LINES


# --- D. the write discipline and the protocol hash -----------------------------------------


@pytest.fixture
def runner_paths(tmp_path, monkeypatch):
    results, runs = tmp_path / "results", tmp_path / "runs"
    monkeypatch.setattr(rs, "RESULTS", results)
    monkeypatch.setattr(rs, "RUNS", runs)
    return results, runs


def test_cmd_tables_is_write_once(fake_cache, runner_paths, monkeypatch):
    """The full `tables` glue on the synthetic network and cache, run twice."""
    results, runs = runner_paths
    net, _ = synthetic_net()
    monkeypatch.setattr(rs.ds, "variant_network", lambda *a, **k: net)
    monkeypatch.setattr(rs, "availability", lambda _net: (fake_available(), FAKE_RATING))
    monkeypatch.setattr(
        rs, "nominal_provenance", lambda code: {"folder": "synthetic", "manifest": {}}
    )
    monkeypatch.setattr(
        rs,
        "AUDIT_EXPORT_MWH",
        {FAKE_NAME: {"nocap": 0.0, "recorded": 0.0, "robust_w0.2": 0.0, "robust_w0.3": 0.0}},
    )

    class Args:
        network = FAKE_NAME

    record = rs.cmd_tables(Args())
    assert record["counts"]["n_table_lines"] == 3
    assert record["counts"]["table_lines"] == FAKE_TABLE_LINES
    assert record["new_ac_solves"] == 0
    assert record["topology"]["is_tree"] is True
    assert record["routes"]["n_routes"] == 3
    assert record["code_sha256"]["run_stage_a.py"] == rc.sha256_of(HERE / "run_stage_a.py")
    assert (results / f"tables_{FAKE_NAME}.json").exists()
    assert (runs / f"tables_{FAKE_NAME}.npz").exists()
    # the audit cross-check must record the mismatch against the stub table, not hide it
    assert record["audit_cross_check"]["pass"] is False
    assert record["audit_cross_check"]["max_abs_difference_MWh"] > 0.0

    with pytest.raises(FileExistsError, match="written once"):
        rs.cmd_tables(Args())


def test_load_tables_round_trips_what_cmd_tables_wrote(fake_cache, runner_paths, monkeypatch):
    results, runs = runner_paths
    net, _ = synthetic_net()
    monkeypatch.setattr(rs.ds, "variant_network", lambda *a, **k: net)
    monkeypatch.setattr(rs, "availability", lambda _net: (fake_available(), FAKE_RATING))
    monkeypatch.setattr(rs, "nominal_provenance", lambda code: {"folder": "synthetic"})
    monkeypatch.setattr(
        rs,
        "AUDIT_EXPORT_MWH",
        {FAKE_NAME: {"nocap": 0.0, "recorded": 0.0, "robust_w0.2": 0.0, "robust_w0.3": 0.0}},
    )

    class Args:
        network = FAKE_NAME

    rs.cmd_tables(Args())
    loaded = rs.load_tables(FAKE_NAME)
    assert loaded.tables["P"].line_ids.tolist() == FAKE_TABLE_LINES
    assert loaded.parent_line.tolist() == list(SYNTHETIC_PARENT)
    assert loaded.route_of_line.tolist() == list(SYNTHETIC_ROUTES)
    assert loaded.result["pools"]["w0.2"]["P"] == [0, 4]


def test_load_tables_refuses_a_table_written_by_another_core(runner_paths):
    results, runs = runner_paths
    results.mkdir(parents=True)
    runs.mkdir(parents=True)
    (runs / "tables_rural1.npz").write_bytes(b"")
    (results / "tables_rural1.json").write_text(
        json.dumps({"code_sha256": {"ratings_core.py": "0" * 64, "run_stage_a.py": "0" * 64}})
    )
    with pytest.raises(ValueError, match="different ratings_core.py"):
        rs.load_tables("rural1")


def test_load_tables_refuses_a_missing_table(runner_paths):
    with pytest.raises(FileNotFoundError, match="run `tables --network rural1` first"):
        rs.load_tables("rural1")


def test_free_path_never_overwrites(runner_paths):
    results, _ = runner_paths
    results.mkdir(parents=True)
    assert rs._free_path("control_d") == results / "control_d.json"
    (results / "control_d.json").write_text("{}")
    assert rs._free_path("control_d") == results / "control_d_1.json"
    (results / "control_d_1.json").write_text("{}")
    assert rs._free_path("control_d") == results / "control_d_2.json"


def test_every_command_checks_the_protocol_before_it_writes(runner_paths, monkeypatch):
    """Protocol s. 10: no result can be produced under an edited protocol."""
    results, runs = runner_paths

    def refuse(*args, **kwargs):
        raise ValueError("protocol sha256 deadbeef != expected cafe")

    monkeypatch.setattr(rc, "check_protocol", refuse)

    class Args:
        network = FAKE_NAME

    for command in (rs.cmd_tables, rs.cmd_control_d, rs.cmd_control_e, rs.cmd_pilot):
        with pytest.raises(ValueError, match="protocol sha256"):
            command(Args())
    assert not results.exists() and not runs.exists()


def test_the_runner_pins_the_registered_protocol_revision():
    """The check pins the as-executed text; the artefacts record the whole file."""
    assert rc.executed_text_sha() == rc.PROTOCOL_SHA256_EXECUTED
    assert rc.check_protocol() == rc.sha256_of(rc.PROTOCOL)
    assert rs._stamp("probe")["protocol_sha256"] == rc.sha256_of(rc.PROTOCOL)
    assert set(rs._stamp("probe")["code_sha256"]) == {"ratings_core.py", "run_stage_a.py"}


# --- E. small helpers ----------------------------------------------------------------------


def test_networks_maps_short_names_onto_the_six_simbench_codes():
    table = rs.networks()
    assert sorted(table) == ["rural1", "rural2", "rural3", "semiurb4", "semiurb5", "urban6"]
    assert table["urban6"] == "1-LV-urban6--2-sw"
    assert rs.code_of("semiurb5") == "1-LV-semiurb5--2-sw"
    with pytest.raises(ValueError, match="is not one of"):
        rs.code_of("urban7")
    assert sorted(rs.AUDIT_EXPORT_MWH) == sorted(table)
    assert sorted(rs.TRANSFORMER_LIMITED + rs.CABLE_LIMITED) == sorted(table)


def test_compare_reports_the_absolute_and_relative_difference():
    identical = rs._compare("x", np.array([1.0, 2.0]), np.array([1.0, 2.0]), 1e-9)
    assert identical["max_abs_diff"] == 0.0 and identical["max_rel_diff"] == 0.0
    assert identical["within_tolerance"] is True
    off = rs._compare("x", np.array([1.0, 100.0]), np.array([1.0, 80.0]), 1e-9)
    assert off["max_abs_diff"] == pytest.approx(20.0)
    assert off["max_rel_diff"] == pytest.approx(0.2)
    assert off["within_tolerance"] is False
    assert off["argmax_abs"] == 1
    with pytest.raises(ValueError, match="shapes"):
        rs._compare("x", np.zeros(2), np.zeros(3), 1e-9)


def test_distribution_is_exact_and_releases_its_chunks():
    chunks = [np.array([1.0, 2.0], dtype=np.float32), np.array([3.0, np.nan], dtype=np.float32)]
    summary = rs._distribution(chunks, "p.u.")
    assert chunks == []  # the caller's list is released, not kept alive twice
    assert summary["n"] == 3 and summary["n_non_finite"] == 1
    assert summary["median"] == pytest.approx(2.0)
    assert summary["max"] == pytest.approx(3.0)
    assert rs._distribution([], "MW")["n"] == 0


def test_cache_provenance_asserts_the_manifest_and_records_the_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "DAYS", (35, 36))
    folder = tmp_path / "cache"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"fingerprint": "abc", "pv_scale": 2.0}))
    for day in (35, 36):
        np.savez_compressed(folder / f"day_{day:03d}.npz", line=np.zeros(1))
    out = rs.cache_provenance(folder, {"pv_scale": 2.0}, lambda: "abc")
    assert out["fingerprint_matches"] is True and out["covers_days_35_364"] is True
    out = rs.cache_provenance(folder, {"pv_scale": 2.0}, None)
    assert (
        out["fingerprint_matches"] is None and "no fingerprint function" in out["fingerprint_note"]
    )  # noqa: E501
    with pytest.raises(ValueError, match="does not match the network build"):
        rs.cache_provenance(folder, {"pv_scale": 3.0}, None)
    (folder / "day_036.npz").unlink()
    with pytest.raises(FileNotFoundError, match="missing 1 of 2 days"):
        rs.cache_provenance(folder, {"pv_scale": 2.0}, None)


# --- F. B9's round loop (protocol s. 6, step 3; amendment A1) ------------------------------

#: a co-blocking trunk in round numbers, in % of the record at cap 1.0 and per P-step.
#: column 0 = network line 0 (the feeder head), column 1 = line 1 (its child), column 2 =
#: line 3 (the other feeder's head). Lines 2 and 4 stay below the 70 % table threshold.
B9_BASE = {0: (120.0, 120.0, 120.0, 60.0, 60.0, 60.0), 1: (115.0,) * 6, 2: (95.0,) * 6}
B9_LINE_IDS = (0, 1, 3)
B9_LB = 1.0 - rs.W_PRIMARY  # 0.8, the believed lower bound of U2 at the primary width


def b9_table(n_steps: int = 6) -> rc.DecisionTable:
    """The co-blocking table the B9 tests plan on.

    Loadings fall linearly with the cap, so the hand calculation is exact. Under B2
    (threshold 80 %) every step sits at cap 0.6 and the level just above it, cap 0.7, is
    blocked by column 1 (80.5 %) at all six steps and by column 0 (84 %) at the first three.
    Column 1 is therefore the top blocker, column 0 co-blocks on half of its blocking steps,
    and both lie on one root path: round 1 verifies a **two-segment path**. With both revealed
    at rho = 1 the decision moves to cap 0.8, where cap 0.9 is blocked by column 2 (85.5 %
    against the believed 80 %), so a third line blocks and round 2 must take it.
    """
    load = np.zeros((n_steps, rc.N_LEVELS, 3), dtype=np.float32)
    for column, bases in B9_BASE.items():
        for step in range(n_steps):
            load[step, :, column] = bases[step % len(bases)] * rc.CAP_LEVELS
    return rc.DecisionTable(
        load=load,
        trafo=np.full((n_steps, rc.N_LEVELS), 50.0),
        volt_ok=np.ones((n_steps, rc.N_LEVELS), dtype=bool),
        export=np.broadcast_to(rc.CAP_LEVELS, (n_steps, rc.N_LEVELS)).copy(),
        line_ids=np.array(B9_LINE_IDS),
    )


def test_the_b9_table_has_the_co_blocking_structure_the_tests_assume():
    table = b9_table()
    assert rc.candidate_pool(table, B9_LB).tolist() == [0, 1, 2]
    blocking = rc.blocking_counts(table, 100.0 * B9_LB)
    assert blocking.level.tolist() == [4] * 6  # cap 0.6 everywhere
    assert blocking.counts.tolist() == [3, 6, 0]  # column 1 blocks most, column 0 co-blocks


def test_b9_asks_for_one_more_than_it_realised_and_takes_the_third_line():
    """Amendment A1: round 1 realises a two-segment path, so round 2 must ask for 3, not 2."""
    table = b9_table()
    rho_true = np.ones(3)
    seen: list[tuple[tuple[int, ...], tuple[int, ...]]] = []

    def probe(verified, revealed):
        # the reveal boundary: the rule is handed rho at the verified columns and NaN elsewhere
        finite = tuple(int(c) for c in np.flatnonzero(np.isfinite(revealed)))
        assert finite == tuple(sorted(int(c) for c in verified))
        seen.append((tuple(sorted(int(c) for c in verified)), finite))

    states, terminated = rs.route_rule_revealed(
        table, B9_LB, SYNTHETIC_PARENT, 4, rho_true, probe=probe
    )
    assert [s[0] for s in states] == [0, 2, 3]  # units: the path, then the third line
    assert [s[1] for s in states] == [0, 2, 3]  # segments, one per unit under U2
    assert states[1][2] == (0, 1) and states[2][2] == (0, 1, 2)
    assert terminated is True  # round 3 found nothing new; the budget was never reached
    assert [v for v, _ in seen] == [(), (0, 1), (0, 1, 2)]


def test_b9_overshooting_its_budget_is_not_termination():
    states, terminated = rs.route_rule_revealed(b9_table(), B9_LB, SYNTHETIC_PARENT, 2, np.ones(3))
    assert [s[0] for s in states] == [0, 2]
    assert terminated is False  # it stopped at the budget, which is not the rule's own stop


def test_b9_static_takes_the_third_line_too():
    """B9-static believes a verified asset at its upper bound and reads no truth at all."""
    table = b9_table()
    states, terminated = rs.route_rule_static(table, B9_LB, SYNTHETIC_PARENT, 4, ub=1.2)
    assert [s[0] for s in states] == [0, 2, 3]
    assert states[-1][2] == (0, 1, 2)
    assert terminated is True
    at_two, stopped = rs.route_rule_static(table, B9_LB, SYNTHETIC_PARENT, 2, ub=1.2)
    assert [s[0] for s in at_two] == [0, 2] and stopped is False


def test_b9_still_flags_a_true_termination():
    """A pool of one: after its single unit nothing unverified blocks, well below the budget."""
    table = b9_table()
    states, terminated = rs.route_rule_revealed(
        table, B9_LB, SYNTHETIC_PARENT, 4, np.ones(3), pool=np.array([1])
    )
    assert [s[0] for s in states] == [0, 1] and states[-1][2] == (1,)
    assert terminated is True
    static_states, static_terminated = rs.route_rule_static(
        table, B9_LB, SYNTHETIC_PARENT, 4, pool=np.array([1]), ub=1.2
    )
    assert [s[0] for s in static_states] == [0, 1] and static_terminated is True


def test_b9_under_u4_counts_a_route_as_one_unit():
    """The route units of U4 are the other budgeted wrapper: one unit, several segments."""
    table = b9_table()
    groups = [np.array([0, 1]), np.array([2])]  # columns 0 and 1 are one route
    states, terminated = rs.route_rule_revealed(
        table, B9_LB, SYNTHETIC_PARENT, 4, np.ones(3), unit_groups=groups
    )
    assert [s[0] for s in states] == [0, 1, 2]  # units: the route, then the third line
    assert [s[1] for s in states] == [0, 2, 3]  # segments overshoot the unit count
    assert states[-1][2] == (0, 1, 2) and terminated is True


def test_a_b8p_pair_overshoot_is_a_step_boundary_not_a_stop():
    """The other budgeted wrapper (protocol s. 6, "Budgets"): B8P may add a pair atomically.

    `_greedy_states` keeps the greedy's **step** boundaries, so the pair is one state of two
    realised units, and `_state_at` then matches a budget by taking the last state at or
    below it -- the empty set at k = 1. Overshooting is never read as the greedy stopping.
    """
    units = [np.array([0]), np.array([1]), np.array([2])]
    expected_export = {(): 0.0, (0, 1): 2.0, (0, 1, 2): 3.0}
    result = rc.GreedyResult(
        units=(0, 1, 2),
        segments=np.array([0, 1, 2]),
        expected=np.array([0.0, 2.0, 3.0]),  # after 0 steps, the pair, then the single
        gains=np.array([2.0, 1.0]),
        n_units=3,
        n_segments=3,
        evaluated=4,
        pairs=1,
    )
    states = rs._greedy_states(result, units, lambda cols: expected_export.get(tuple(cols), -1.0))
    assert states == [(0, 0, ()), (2, 2, (0, 1)), (3, 3, (0, 1, 2))]
    assert rs._state_at(states, 1) == (0, 0, ())  # the pair overshoots k = 1
    assert rs._state_at(states, 2) == (2, 2, (0, 1))
    assert rs._state_at(states, 8) == (3, 3, (0, 1, 2))  # and never more than it realised
    assert rc.match_budget([0, 2, 3], 1) == 0


# --- G. the scored evaluation on the synthetic table pair -----------------------------------

#: the same co-blocking bases as `b9_table`, as a **cache** in network line indices. The
#: first day of each period loads the feeder head at 120 %, the second at 60 %; lines 2 and 4
#: stay below the 70 % table threshold and never enter a table.
EVAL_BASES_FIRST_DAY = {0: 120.0, 1: 115.0, 2: 50.0, 3: 95.0, 4: 40.0}
EVAL_BASES_SECOND_DAY = {**EVAL_BASES_FIRST_DAY, 0: 60.0}
EVAL_FIRST_DAYS = (35, 42)  # day 35 opens the P period, day 42 the E period


def write_eval_cache(root: Path) -> Path:
    """`write_fake_cache`'s structure, but with loadings that fall with the cap, so the
    decision rule has somewhere to move and the co-blocking pair is real."""
    folder = root / FAKE_CODE / "nominal"
    folder.mkdir(parents=True, exist_ok=True)
    for day in FAKE_DAYS:
        bases = EVAL_BASES_FIRST_DAY if day in EVAL_FIRST_DAYS else EVAL_BASES_SECOND_DAY
        line = np.zeros((4, rc.N_LEVELS, 5), dtype=np.float32)
        for index, base in bases.items():
            line[:, :, index] = base * rc.CAP_LEVELS[None, :]
        trafo = np.zeros((4, rc.N_LEVELS, 4), dtype=np.float32)
        trafo[:, :, 2] = 50.0
        np.savez_compressed(
            folder / f"day_{day:03d}.npz",
            line=line,
            trafo=trafo,
            margins=np.full((4, rc.N_LEVELS, 4), -1.0, dtype=np.float32),
            vm=np.ones((4, rc.N_LEVELS, 6), dtype=np.float32),
        )
    return folder


@pytest.fixture
def eval_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "SENSE_CACHE", tmp_path / "cache")
    monkeypatch.setattr(rs, "DAYS", FAKE_DAYS)
    write_eval_cache(tmp_path / "cache")
    return tmp_path


def eval_period_arrays():
    """The E-period table as the test derives it by hand: per-step export and loadings."""
    step_export = rs.step_export(FAKE_AVAILABLE_DAY, FAKE_RATING)[1:]  # the three lit steps
    export = np.concatenate([step_export, step_export])  # two days in the period
    bases = np.array(
        [[EVAL_BASES_FIRST_DAY[i] for i in B9_LINE_IDS]] * 3
        + [[EVAL_BASES_SECOND_DAY[i] for i in B9_LINE_IDS]] * 3
    )
    load = bases[:, None, :] * rc.CAP_LEVELS[None, :, None]  # (steps, levels, table lines)
    return export, load


def eval_export_at(thr_per_column: np.ndarray) -> float:
    """The export of the decision taken under one believed threshold vector, by hand: at every
    step the first cap whose loadings all sit at or below the threshold."""
    export, load = eval_period_arrays()
    ok = (load <= np.asarray(thr_per_column, float)[None, None, :]).all(axis=2)
    levels = np.argmax(ok, axis=1)
    assert ok[np.arange(ok.shape[0]), levels].all()  # cap 0 is always admissible here
    return float(export[np.arange(export.shape[0]), levels].sum())


@pytest.fixture
def evaluated(eval_cache, runner_paths, monkeypatch):
    """`tables` then `evaluate` on the synthetic pair, under U2 and a small draw count."""
    results, runs = runner_paths
    net, _ = synthetic_net()
    monkeypatch.setattr(rs.ds, "variant_network", lambda *a, **k: net)
    monkeypatch.setattr(rs, "availability", lambda _net: (fake_available(), FAKE_RATING))
    monkeypatch.setattr(rs, "nominal_provenance", lambda code: {"folder": "synthetic"})
    monkeypatch.setattr(
        rs,
        "AUDIT_EXPORT_MWH",
        {FAKE_NAME: {"nocap": 0.0, "recorded": 0.0, "robust_w0.2": 0.0, "robust_w0.3": 0.0}},
    )
    monkeypatch.setattr(rs, "N_TRUTH", 20)
    monkeypatch.setattr(rs, "N_PRIOR", 10)
    monkeypatch.setattr(rs, "N_ORDERS", 3)

    class Args:
        network = FAKE_NAME
        model = "U2"

    rs.cmd_tables(Args())
    record = rs.cmd_evaluate(Args())
    with np.load(runs / f"eval_{FAKE_NAME}_U2.npz", allow_pickle=False) as data:
        arrays = {key: np.asarray(data[key]) for key in data.files}
    return record, arrays


def test_cmd_evaluate_reproduces_b2_and_the_oracle_on_the_synthetic_pair(evaluated):
    record, arrays = evaluated
    assert record["new_ac_solves"] == 0
    assert record["sizes"]["n_table_lines"] == 3 and record["sizes"]["steps_E"] == 6
    assert record["pool"]["unit_kind"] == "segment" and record["pool"]["n_units"] == 3
    assert record["pool"]["line_ids"] == list(B9_LINE_IDS)
    assert record["sizes"]["budgets"] == [1, 2, 3, "all"]  # three units, so k = 4, 6, 8 drop

    # B2 believes 0.8 everywhere: every E step sits at cap 0.6, worth 1.8 MWh in the period
    b2 = eval_export_at(np.full(3, 100.0 * B9_LB))
    assert b2 == pytest.approx(1.8)
    assert arrays["B2__na__export"] == pytest.approx(np.full(20, 1.8))
    assert record["policies"]["B2"]["na"]["export_MWh"]["mean"] == pytest.approx(1.8)
    assert record["policies"]["B2"]["na"]["unsafe"]["max_steps"] == 0  # H5a on this table

    # the oracle, re-derived step by step from the truth draws the npz records
    rho = arrays["rho_truth"]
    assert rho.shape == (20, 3)
    expected = np.array([eval_export_at(100.0 * rho[draw]) for draw in range(20)])
    assert arrays["B4__na__export"] == pytest.approx(expected)
    assert np.all(expected >= b2 - 1e-12)
    assert record["policies"]["B4"]["na"]["export_MWh"]["mean"] == pytest.approx(expected.mean())
    # verifying the whole pool reproduces the oracle's decisions (Control F)
    assert record["control_f"]["verify_all_equals_B4_decisions"] is True
    assert arrays["VERIFYALL__na__export"] == pytest.approx(expected)


def test_cmd_evaluate_recovery_is_the_protocol_ratio_and_excludes_the_degenerate_draws(evaluated):
    record, arrays = evaluated
    rho = arrays["rho_truth"]
    oracle = np.array([eval_export_at(100.0 * rho[draw]) for draw in range(rho.shape[0])])
    degenerate = int(np.count_nonzero(oracle == 1.8))
    for policy in ("B4", "VERIFYALL"):
        entry = record["policies"][policy]["na"]["recovery"]
        assert entry["mean"] == pytest.approx(1.0)  # both land on the oracle
        assert entry["nan_excluded"] == degenerate
        assert entry["n"] == rho.shape[0] - degenerate
    # the ratio itself, on the policy that verifies one segment at k = 1
    at_one = record["policies"]["B7"]["1"]
    r = (arrays["B7__1__export"] - 1.8) / np.where(oracle == 1.8, np.nan, oracle - 1.8)
    assert at_one["recovery"]["mean"] == pytest.approx(np.nanmean(r))
    assert 0.0 <= at_one["recovery"]["mean"] <= 1.0


def test_cmd_evaluate_matches_budgets_to_realised_units(evaluated):
    """Protocol s. 7: a policy whose realised count overshoots k scores its last state at or
    below k, and B9's two-segment first round means it has nothing to show at k = 1."""
    record, _ = evaluated
    b9 = record["policies"]["B9"]
    assert b9["1"]["realised_units"]["mean"] == 0.0  # the path of 2 overshoots k = 1
    assert b9["1"]["recovery"]["mean"] == pytest.approx(0.0)  # so it is B2 at k = 1
    assert b9["2"]["realised_units"]["mean"] == 2.0
    assert b9["2"]["realised_units"]["p5"] == 2.0 and b9["2"]["realised_units"]["p95"] == 2.0
    assert 2.0 <= b9["3"]["realised_units"]["mean"] <= 3.0  # 3 unless a draw terminates at 2
    assert b9["3"]["realised_units"]["p95"] == 3.0
    static = record["policies"]["B9static"]
    assert [static[str(k)]["realised_units"]["mean"] for k in (1, 2, 3)] == [0.0, 2.0, 3.0]
    assert static["3"]["recovery"]["mean"] == pytest.approx(1.0)  # the whole pool, so the oracle
    assert record["b9"]["terminated_by_kmax_share"] is not None
    # every budgeted policy respects its budget in realised units
    for policy in rs.BUDGETED_POLICIES:
        for k in (1, 2, 3):
            entry = record["policies"][policy].get(str(k))
            if entry is not None:
                assert entry["realised_units"]["p95"] <= k


# --- G.1 amendment A2: the reduction is sized from table columns, not from units -----------

#: One feeder, one `std_type`, eight series segments, so U4 has a **single route that spans
#: every table column** -- the shape protocol amendment A2 was written for.
WIDE_ROUTE_N_LINES = 8
#: the loading at cap 1.0 per line: two above the 80 % candidate-pool threshold, six only
#: above the 70 % table threshold. So the pool holds 2 columns and 1 route unit, while B5-all's
#: route (drawn from the whole table, protocol s. 6) reveals all 8 columns at k = 1. The A2
#: defect sized the reduction as min(pool columns + 2, n_table) = 4 entries and the exactness
#: guard refused the 8-column set.
WIDE_ROUTE_BASES = (120.0, 115.0, 75.0, 75.0, 75.0, 75.0, 75.0, 75.0)


def wide_route_net():
    """A radial chain of `WIDE_ROUTE_N_LINES` same-type lines on one feeder. Building it runs
    no flow, exactly as `synthetic_net` does."""
    import pandapower as pp

    net = pp.create_empty_network()
    mv = pp.create_bus(net, vn_kv=20.0, name="mv")
    lv = [pp.create_bus(net, vn_kv=0.4, name=f"lv{i}") for i in range(WIDE_ROUTE_N_LINES + 1)]
    pp.create_ext_grid(net, mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net,
        hv_bus=mv,
        lv_bus=lv[0],
        sn_mva=1.0,
        vn_hv_kv=20.0,
        vn_lv_kv=0.4,
        vkr_percent=1.0,
        vk_percent=4.0,
        pfe_kw=0.0,
        i0_percent=0.0,
    )
    for segment in range(WIDE_ROUTE_N_LINES):
        index = pp.create_line_from_parameters(
            net,
            from_bus=lv[segment],
            to_bus=lv[segment + 1],
            length_km=0.1,
            r_ohm_per_km=0.2,
            x_ohm_per_km=0.1,
            c_nf_per_km=0.0,
            max_i_ka=0.2,
        )
        net.line.at[index, "std_type"] = "A"
    pp.create_sgen(net, bus=lv[-1], p_mw=0.0, sn_mva=1.0)
    return net


def write_wide_route_cache(root: Path) -> Path:
    """`write_eval_cache`'s structure on `WIDE_ROUTE_N_LINES` lines: every loading falls with
    the cap level, and P and E carry the same bases."""
    folder = root / FAKE_CODE / "nominal"
    folder.mkdir(parents=True, exist_ok=True)
    bases = np.asarray(WIDE_ROUTE_BASES, dtype=np.float32)
    line = np.repeat(
        (bases[None, :] * np.asarray(rc.CAP_LEVELS, dtype=np.float32)[:, None])[None], 4, axis=0
    )
    trafo = np.zeros((4, rc.N_LEVELS, 4), dtype=np.float32)
    trafo[:, :, 2] = 50.0
    for day in FAKE_DAYS:
        np.savez_compressed(
            folder / f"day_{day:03d}.npz",
            line=np.ascontiguousarray(line),
            trafo=trafo,
            margins=np.full((4, rc.N_LEVELS, 4), -1.0, dtype=np.float32),
            vm=np.ones((4, rc.N_LEVELS, WIDE_ROUTE_N_LINES + 1), dtype=np.float32),
        )
    return folder


def exactness_spy(monkeypatch) -> list[int]:
    """Wrap `decide_reduced` so that **every** set the evaluation scores through the reduction
    is also decided by the full rule and the two are asserted equal. Returns the list of set
    sizes seen, so a test can check that the widest set really was scored."""
    reduced_rule, full_rule = rc.decide_reduced, rc.decide
    sizes: list[int] = []

    def checked(table, red, verified, thr_verified, thr_unverified, thr_trafo, *, n_draws=None):
        out = reduced_rule(
            table, red, verified, thr_verified, thr_unverified, thr_trafo, n_draws=n_draws
        )
        sel = np.asarray(verified, dtype=int).reshape(-1)
        thr_v = np.atleast_2d(np.asarray(thr_verified, dtype=float))
        thr_t = np.atleast_1d(np.asarray(thr_trafo, dtype=float))
        n = int(n_draws) if n_draws is not None else max(thr_v.shape[0], thr_t.shape[0])
        thr = np.full((n, table.n_table), float(thr_unverified))
        if sel.size:
            thr[:, sel] = np.broadcast_to(thr_v, (n, sel.size))
        full = full_rule(table, thr, np.broadcast_to(thr_t, (n,)))
        assert np.array_equal(np.atleast_2d(full.level), np.atleast_2d(out.level))
        assert np.array_equal(np.atleast_2d(full.infeasible), np.atleast_2d(out.infeasible))
        sizes.append(int(sel.size))
        return out

    monkeypatch.setattr(rc, "decide_reduced", checked)
    return sizes


@pytest.fixture
def evaluated_u4(tmp_path, runner_paths, monkeypatch):
    """`tables` then `evaluate --model U4` on the wide-route pair, every reduced decision
    cross-checked against the full rule."""
    monkeypatch.setattr(rs, "SENSE_CACHE", tmp_path / "cache")
    monkeypatch.setattr(rs, "DAYS", FAKE_DAYS)
    write_wide_route_cache(tmp_path / "cache")
    monkeypatch.setattr(rs.ds, "variant_network", lambda *a, **k: wide_route_net())
    monkeypatch.setattr(rs, "availability", lambda _net: (fake_available(), FAKE_RATING))
    monkeypatch.setattr(rs, "nominal_provenance", lambda code: {"folder": "synthetic"})
    monkeypatch.setattr(
        rs,
        "AUDIT_EXPORT_MWH",
        {FAKE_NAME: {"nocap": 0.0, "recorded": 0.0, "robust_w0.2": 0.0, "robust_w0.3": 0.0}},
    )
    monkeypatch.setattr(rs, "N_TRUTH", 6)
    monkeypatch.setattr(rs, "N_PRIOR", 4)
    monkeypatch.setattr(rs, "N_ORDERS", 2)

    class Args:
        network = FAKE_NAME
        model = "U4"

    rs.cmd_tables(Args())
    sizes = exactness_spy(monkeypatch)
    return rs.cmd_evaluate(Args()), sizes


def test_the_wide_route_table_pair_has_the_shape_the_a2_regression_needs(evaluated_u4):
    record, _ = evaluated_u4
    assert record["new_ac_solves"] == 0
    assert record["sizes"]["n_table_lines"] == WIDE_ROUTE_N_LINES
    assert record["pool"]["unit_kind"] == "route"
    assert record["pool"]["n_units"] == 1  # one route unit
    assert record["pool"]["columns"] == [0, 1]  # holding 2 of the 8 table columns
    assert record["pool"]["n_units_all_reference"] == 1  # B5-all's route spans the whole table
    # the A2 defect's width, in this record's own numbers: 4 entries for an 8-column set
    assert min(len(record["pool"]["columns"]) + 2, WIDE_ROUTE_N_LINES) == 4


def test_cmd_evaluate_sizes_the_reduction_from_the_revealed_columns(evaluated_u4):
    """The regression itself: `evaluate --model U4` completes, and the reduction is sized from
    the widest scored set's **columns**, which is the whole table here."""
    record, sizes = evaluated_u4
    assert record["sizes"]["reduction_columns_P"] == 2  # the pool's columns bound every P set
    assert record["sizes"]["reduction_k_P"] == 3
    assert record["sizes"]["reduction_columns_E"] == WIDE_ROUTE_N_LINES
    assert record["sizes"]["reduction_k_E"] == WIDE_ROUTE_N_LINES  # k = n_table, the escape
    # B5-all verified the whole route at k = 1, so the 8-column set really was scored on E
    assert record["policies"]["B5all"]["1"]["realised_segments"]["mean"] == pytest.approx(
        float(WIDE_ROUTE_N_LINES)
    )
    assert record["policies"]["B5all"]["1"]["realised_units"]["mean"] == pytest.approx(1.0)
    # and `exactness_spy` compared every one of those decisions against the full rule
    assert max(sizes) == WIDE_ROUTE_N_LINES
    assert len(sizes) > 1


def test_the_pool_sized_reduction_the_a2_defect_built_is_refused(evaluated_u4):
    """The counterpart: the old width is still rejected rather than silently truncated, so the
    exactness guard remains the backstop it was in amendment A2."""
    record, _ = evaluated_u4
    table = rs.load_tables(FAKE_NAME).tables["E"]
    narrow = rc.top_reduction(table, min(len(record["pool"]["columns"]) + 2, table.n_table))
    assert narrow.k == 4
    route = np.arange(table.n_table)
    with pytest.raises(ValueError, match="too few"):
        rc.decide_reduced(table, narrow, route, np.full(route.size, 100.0), 80.0, 100.0)
    # and the same set goes through the reduction `cmd_evaluate` now builds
    wide = rc.reduction_for(table, record["sizes"]["reduction_columns_E"])
    assert wide.k == table.n_table
    thr = np.full((1, table.n_table), 100.0)
    assert np.array_equal(
        np.atleast_2d(rc.decide_reduced(table, wide, route, thr, 80.0, 100.0).level),
        np.atleast_2d(rc.decide(table, thr, np.array([100.0])).level),
    )


# --- G.2 amendment A3: OB is scored at every budget k <= 3 ---------------------------------

#: The table the A3 regression is built on, in % of the record at cap 1.0, per step and per
#: table column. At the first step the cap above 0.9 is blocked by columns 0, 1 **and** 2 at
#: once, so only revealing all three moves it; at the second step column 3 alone blocks, so a
#: single unit already moves it. The first step's export is worth ten times the second's, so
#: the best 3-set is strictly better than any 2-set while one unit still gains -- exactly the
#: shape on which the A3 defect scored k = 1 and 2 as the empty set.
OB_BASES = ((85.0, 85.0, 85.0, 50.0), (50.0, 50.0, 50.0, 85.0))
OB_STEP_WORTH = (10.0, 1.0)


def ob_table() -> rc.DecisionTable:
    """`OB_BASES` as a decision table, loadings falling linearly with the cap."""
    steps = len(OB_BASES)
    load = np.zeros((steps, rc.N_LEVELS, 4), dtype=np.float32)
    export = np.zeros((steps, rc.N_LEVELS))
    for step, bases in enumerate(OB_BASES):
        load[step] = np.asarray(bases)[None, :] * rc.CAP_LEVELS[:, None]
        export[step] = OB_STEP_WORTH[step] * rc.CAP_LEVELS
    return rc.DecisionTable(
        load=load,
        trafo=np.full((steps, rc.N_LEVELS), 50.0),
        volt_ok=np.ones((steps, rc.N_LEVELS), dtype=bool),
        export=export,
        line_ids=np.arange(4),
    )


def ob_engine(n_draws: int = 2):
    """`ob_table` as a subset engine whose whole table is the candidate pool, with the truth
    at rho = 1 on every draw. Returns the engine and B2's export per draw."""
    table = ob_table()
    rho = np.ones((n_draws, 4))
    b2_level = rc.decide(table, 100.0 * B9_LB, 100.0 * B9_LB).level
    oracle_level = rc.decide(table, 100.0 * rho, np.full(n_draws, 100.0 * B9_LB)).level
    engine = rs.SubsetEngine(
        table, np.arange(4), rho, B9_LB, B9_LB, b2_level, oracle_level, restrict=False
    )
    return engine, np.full(n_draws, rc.export_total(table, b2_level))


def test_the_ob_regression_table_has_the_three_against_one_shape_a3_needs():
    engine, b2_export = ob_engine()
    assert engine.check_squeeze() is True
    assert b2_export == pytest.approx(np.full(2, 9.9))  # cap 0.9 at both steps: 9.0 + 0.9
    # the oracle reaches cap 1.0 at both steps, and only the whole trio unlocks the first one
    table = ob_table()
    assert rc.export_total(table, rc.decide(table, 100.0, 80.0).level) == pytest.approx(11.0)


def test_ob_scores_a_single_unit_at_k_1_even_when_the_best_3_set_needs_three():
    """A3's regression: the best size-<= 3 set holds three units, so the old single-best OB
    had nothing at or below k = 1 and s. 7 scored it as the empty set (= B2, R = 0). Scored
    per budget, k = 1 takes the one unit that already gains."""
    engine, b2_export = ob_engine()
    cols_per_k, export_per_k, n_subsets = rs._ob_best(engine, 3, b2_export)
    assert n_subsets == 14  # 4 + 6 + 4 non-empty subsets of the four candidates
    assert cols_per_k[0] == [(3,), (3,)]  # k = 1: the single unit that gains, not ()
    assert cols_per_k[1] == [(3,), (3,)]  # k = 2: no pair beats it, so the tie rule keeps it
    assert cols_per_k[2] == [(0, 1, 2), (0, 1, 2)]  # k = 3: strictly better than any 2-set
    assert export_per_k[0] == pytest.approx(np.full(2, 10.0))  # 9.0 + 1.0
    assert export_per_k[1] == pytest.approx(np.full(2, 10.0))
    assert export_per_k[2] == pytest.approx(np.full(2, 10.9))  # 10.0 + 0.9
    # and the budget-matching rule of s. 7 now finds a set at every k, the k = 3 one above it
    states = [(0, 0, ()), *((len(c), len(c), c) for c in (cols_per_k[k][0] for k in range(3)))]
    assert rs._state_at(states, 1) == (1, 1, (3,))
    assert rs._state_at(states, 2) == (1, 1, (3,))
    assert rs._state_at(states, 3) == (3, 3, (0, 1, 2))
    assert rs._state_at(states, 8) == (3, 3, (0, 1, 2))  # k > 3 carries the k = 3 set


def test_ob_export_is_non_decreasing_in_the_budget(evaluated):
    """A3's first stated check, on `cmd_evaluate`'s own per-draw arrays."""
    record, arrays = evaluated
    at = [arrays[f"OB__{k}__export"] for k in (1, 2, 3)]
    assert np.all(at[1] >= at[0] - 1e-12)
    assert np.all(at[2] >= at[1] - 1e-12)
    assert np.any(at[2] > at[0] + 1e-12)  # and the budget really binds on this table
    assert record["ob"]["searched_kmax"] == 3
    assert sorted(record["ob"]["modal_set_per_k"]) == ["1", "2", "3"]
    assert record["ob"]["modal_set_per_k"]["3"] == record["ob"]["modal_set"]
    for k in (1, 2, 3):
        assert len(record["ob"]["modal_set_per_k"][str(k)]) <= k
        assert record["policies"]["OB"][str(k)]["realised_units"]["p95"] <= k


def test_ob_is_at_least_the_deployable_policies_at_every_budget(evaluated):
    """A3's second stated check: the synthetic pool lies inside OB's top-m search set, so the
    ex-post best set cannot lose to a deployable policy at the same budget."""
    record, _ = evaluated
    assert record["ob"]["available"] is True
    assert record["pool"]["n_units"] == 3 and rs.TOP_M >= 3  # the whole pool is searched
    for k in ("1", "2", "3"):
        ob = record["policies"]["OB"][k]["recovery"]["mean"]
        for policy in ("B6", "B8"):
            assert ob >= record["policies"][policy][k]["recovery"]["mean"] - 1e-12
        assert ob > 0.0  # the A3 defect left OB at exactly B2 (R = 0) for k = 1 and 2


# --- H. the verdict mechanics at their boundaries (protocol s. 7, s. 8) --------------------

#: the budgets the synthetic verdict artefacts carry; H3b reads k = 2, 3, 4 and H5c k <= 4.
VERDICT_BUDGETS = (1, 2, 3, 4)


def _budget_entry(k: int, mean: float, se: float = 0.0, segments=None) -> dict:
    """One (policy, budget) read-out of the shape `_policy_record` writes."""
    return {
        "recovery": {
            "mean": mean,
            "se": se,
            "p5": None,
            "p95": None,
            "n": 100,
            "nan_excluded": 0,
        },
        "realised_units": {"mean": float(k), "p5": float(k), "p95": float(k), "n": 100},
        "realised_segments": {"mean": float(k if segments is None else segments)},
    }


def policy_spec(**overrides) -> dict:
    """Recovery means per policy and budget, with a flat default and per-policy overrides."""
    spec = {
        policy: {k: {"mean": 0.20} for k in VERDICT_BUDGETS}
        for policy in ("B5", "B6", "B7", "B8", "B8P", "B9")
    }
    for policy, per_budget in overrides.items():
        for k, values in per_budget.items():
            spec.setdefault(policy, {}).setdefault(k, {}).update(values)
    return spec


def verdict_artefact(spec: dict) -> dict:
    """A synthetic `eval_<network>_<model>.json` carrying only what `cmd_verdicts` reads."""
    direct = {
        "export_MWh": {"mean": 10.0, "p5": 10.0, "p95": 10.0, "n": 100},
        "unsafe": {
            "max_steps": 0,
            "share_draws_ge1": 0.6,
            "unsafe_step_share": 0.01,
            "mean_steps": 0.0,
        },
        "severity_pct": {"max": 1.0, "p95": 0.5},
    }
    policies: dict = {}
    for policy, per_budget in spec.items():
        policies[policy] = {str(k): _budget_entry(k, **values) for k, values in per_budget.items()}
    for policy in rs.DIRECT_POLICIES:
        entry = {"na": json.loads(json.dumps(direct))}
        if policy in ("B4", "VERIFYALL"):
            entry["na"]["export_MWh"]["mean"] = 12.0
            entry["na"]["recovery"] = {"mean": 1.0, "se": 0.0, "nan_excluded": 0, "n": 100}
        if policy == "CAP0":
            entry["na"]["export_MWh"]["mean"] = 0.0
        policies.setdefault(policy, {}).update(entry)
    return {
        "policies": policies,
        "situation": {p: {"n_steps": 6, "share_situation_1": 0.5} for p in rs.PERIODS},
        "sizes": {"n_table_lines": 3, "n_network_lines": 5},
        "pool": {"n_units": 3, "certificate_columns": [0, 1, 2]},
        "voi": [],
        "h4": {"available": False},
        "control_c": {
            "model_is_U0": False,
            "B0_equals_B4_decisions": True,
            "B0_unsafe_steps_total": 0,
        },
        "control_f": {"verify_all_equals_B4_decisions": True, "max_abs_export_difference_MWh": 0.0},
        "control_g": {"zero_value_candidates": 0},
        "control_h": {"synthetic": True},
        "control_j": {"export_MWh": {"mean": 0.0}, "unsafe": {"max_steps": 0}},
        "b3_vs_b2": {"fault": False},
    }


def run_verdicts(results: Path, spec, per_network=None) -> dict:
    """Write one U2 artefact per cable-limited network and read the verdicts off them."""
    results.mkdir(parents=True, exist_ok=True)
    for network in rs.CABLE_LIMITED:
        this = (per_network or {}).get(network, spec)
        (results / f"eval_{network}_U2.json").write_text(json.dumps(verdict_artefact(this)))
    return rs.cmd_verdicts(None)


@pytest.mark.parametrize(
    ("max_r1", "expected"),
    [(0.10, "SUPPORTED"), (0.15, "INCONCLUSIVE"), (0.25, "REJECTED")],
)
def test_h3a_bands_sit_at_0_10_and_0_25(runner_paths, max_r1, expected):
    """Protocol s. 7: R1 <= 0.10 supports, >= 0.25 rejects, and the open interval is open."""
    results, _ = runner_paths
    spec = policy_spec(
        B6={1: {"mean": max_r1}}, B7={1: {"mean": max_r1 - 0.05}}, B8={1: {"mean": 0.0}}
    )
    record = run_verdicts(results, spec)
    assert record["H3"]["H3a"]["max_R1_over_policies_and_networks"] == pytest.approx(max_r1)
    assert record["H3"]["H3a"]["verdict"].startswith(expected)
    assert record["H3"]["per_network"]["urban6"]["H3a"]["max_R1"] == pytest.approx(max_r1)


def test_h3b_takes_the_smallest_gap_over_k_2_to_4_and_supports_at_0_20(runner_paths):
    results, _ = runner_paths
    # gaps structural - single: 0.30 at k = 2, 0.20 at k = 3, 0.25 at k = 4
    spec = policy_spec(
        B9={2: {"mean": 0.60}, 3: {"mean": 0.50}, 4: {"mean": 0.55}},
        B8P={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B6={k: {"mean": 0.30} for k in VERDICT_BUDGETS},
        B7={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B8={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
    )
    record = run_verdicts(results, spec)
    entry = record["H3"]["per_network"]["urban6"]["H3b"]
    assert entry["budget_with_smallest_gap"] == 3
    assert entry["gap"] == pytest.approx(0.20)
    assert entry["per_budget"]["2"]["gap"] == pytest.approx(0.30)
    assert entry["per_budget"]["3"]["structural"] == "B9"
    assert entry["per_budget"]["3"]["single"] == "B6"
    assert record["H3"]["H3b"]["n_networks_at_or_above_0.20"] == 3
    assert record["H3"]["H3b"]["verdict"] == "SUPPORTED"
    assert record["H3"]["H3b"]["incomplete"] is False


def test_h3b_rejects_when_every_gap_is_at_or_below_0_05(runner_paths):
    results, _ = runner_paths
    spec = policy_spec(
        B9={k: {"mean": 0.25} for k in VERDICT_BUDGETS},
        B8P={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B6={k: {"mean": 0.20} for k in VERDICT_BUDGETS},
    )
    record = run_verdicts(results, spec)
    assert record["H3"]["per_network"]["urban6"]["H3b"]["gap"] == pytest.approx(0.05)
    assert record["H3"]["H3b"]["verdict"] == "REJECTED"


@pytest.mark.parametrize(("se_each", "fragile"), [(0.06, True), (0.05, False)])
def test_the_fragile_flag_is_a_margin_below_twice_the_se(runner_paths, se_each, fragile):
    """Protocol s. 9: a gap of 0.20 against a combined SE of 0.10 is exactly 2 SE, not below."""
    results, _ = runner_paths
    spec = policy_spec(
        B9={k: {"mean": 0.40, "se": se_each} for k in VERDICT_BUDGETS},
        B8P={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B6={k: {"mean": 0.20, "se": se_each} for k in VERDICT_BUDGETS},
        B7={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B8={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
    )
    record = run_verdicts(results, spec)
    entry = record["H3"]["per_network"]["urban6"]["H3b"]
    assert entry["gap"] == pytest.approx(0.20)
    assert entry["fragile"] is fragile
    assert rc.fragile(0.20, 2 * se_each) is fragile
    assert ("urban6" in record["H3"]["H3b"]["fragile_networks"]) is fragile


@pytest.mark.parametrize(("best", "holds"), [(0.50, True), (0.49, False)])
def test_h5c_needs_half_the_recovery_within_four_segments(runner_paths, best, holds):
    """Protocol s. 7 H5(c): the best policy with at most four **segments** at k <= 4."""
    results, _ = runner_paths
    spec = policy_spec(
        B6={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B7={4: {"mean": best}},
        B8={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B8P={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        # a richer set that overshoots the segment budget must not be counted
        B9={4: {"mean": 0.95, "segments": 5}},
    )
    record = run_verdicts(results, spec)
    entry = record["H3"]["per_network"]["urban6"]["H5c"]
    assert entry["policy"] == "B7" and entry["budget"] == 4
    assert entry["R"] == pytest.approx(best)
    assert entry["realised_segments"] == 4.0
    assert entry["threshold"] == 0.50 and entry["holds"] is holds
    assert record["H3"]["H5"]["verdict"] == ("SUPPORTED" if holds else "REJECTED")


@pytest.mark.parametrize(("gap", "close"), [(0.05, True), (0.06, False)])
def test_control_i_calls_a_policy_close_at_0_05(runner_paths, gap, close):
    """Protocol s. 8, Control I: within 0.05 of the best VoI greedy at **every** budget."""
    results, _ = runner_paths
    spec = policy_spec(
        B8={k: {"mean": 0.50} for k in VERDICT_BUDGETS},
        B8P={k: {"mean": 0.0} for k in VERDICT_BUDGETS},
        B6={k: {"mean": 0.50 - gap} for k in VERDICT_BUDGETS},
        B7={k: {"mean": 0.50 - 0.5 * gap} for k in VERDICT_BUDGETS},
        B9={k: {"mean": 0.50} for k in VERDICT_BUDGETS},
    )
    record = run_verdicts(results, spec)
    control_i = record["H3"]["per_network"]["urban6"]["control_I"]
    b6 = next(c for c in control_i["simple_heuristics"] if c["policy"] == "B6")
    assert b6["largest_gap_to_best_VoI"] == pytest.approx(gap)
    assert b6["within_0.05_at_every_budget"] is close
    # B8P is below B9 at every budget, so the structural rule loses nothing
    assert control_i["B9_vs_B8P"]["largest_gap"] == pytest.approx(-0.50)
    assert control_i["B9_vs_B8P"]["structural_rule_suffices"] is True
    # B7 is half a gap away, so it is always close; B6 only at 0.05
    assert control_i["verdict"][0].startswith("a simple heuristic suffices")
    assert ("B6" in control_i["verdict"][0]) is close
    assert "B7" in control_i["verdict"][0]
    assert record["controls"]["I"]["urban6"] == control_i
