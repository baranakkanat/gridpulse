"""Tests for the IEEE European LV pilot (steps 2-4).

Synthetic and tiny: **zero power flows**. Every network built here is a 6-bus toy tree; the
shipped 907-bus feeder is never loaded and `pp.runpp_3ph` is never called.
"""

from __future__ import annotations

import math

import eulv_pilot as ep
import numpy as np
import pytest

LINE_KWARGS = {
    "length_km": 0.01,
    "r_ohm_per_km": 0.2,
    "x_ohm_per_km": 0.07,
    "c_nf_per_km": 0.0,
    "r0_ohm_per_km": 0.8,
    "x0_ohm_per_km": 0.3,
    "c0_nf_per_km": 0.0,
    "max_i_ka": 0.1,
}


def toy_tree():
    """A 6-bus tree whose bus 2 sits mid-chain and carries a load.

        0 --L0-- 1 --L1-- 2 --L2-- 3 --L3-- 4
                       (load)        \\--L4-- 5

    Bus 1 has degree 2 and no load, so it is internal. Bus 2 has degree 2 but a load, so it
    is a boundary node and splits the chain 0-3 into two sections.
    """
    import pandapower as pp

    net = pp.create_empty_network()
    for bus in range(6):
        pp.create_bus(net, vn_kv=0.416, index=bus, name=f"bus_{bus}")
    pp.create_ext_grid(net, bus=0)
    for index, (from_bus, to_bus) in enumerate([(0, 1), (1, 2), (2, 3), (3, 4), (3, 5)]):
        pp.create_line_from_parameters(net, from_bus=from_bus, to_bus=to_bus, index=index,
                                       name=f"L{index}", **LINE_KWARGS)  # fmt: skip
    for bus, phase in ((2, "a"), (4, "b"), (5, "c")):
        kwargs = {f"p_{phase}_mw": 0.001, f"q_{phase}_mvar": 0.0003}
        pp.create_asymmetric_load(net, bus=bus, name=f"load_at_{bus}", **kwargs)
    return net


# --- section extraction --------------------------------------------------------------------


def test_sections_split_at_a_mid_chain_load():
    net = toy_tree()
    custs = ep.customers(net)
    secs = ep.sections(net, {c["bus"] for c in custs}, root=0)
    by_segments = {tuple(s["segments"]): s for s in secs}
    assert sorted(by_segments) == [(0, 1), (2,), (3,), (4,)]
    # the mid-chain load at bus 2 ends a section; without that rule it would be (0, 1, 2)
    head = by_segments[(0, 1)]
    assert (head["near_bus"], head["far_bus"], head["internal_buses"]) == (0, 2, [1])
    assert head["incident_to_busbar"] is True
    assert head["depth_segments"] == 0
    # J1: the chain's internal node plus the whole subtree below the far endpoint
    assert head["downstream_buses"] == [1, 2, 3, 4, 5]
    middle = by_segments[(2,)]
    assert middle["incident_to_busbar"] is False
    assert middle["depth_segments"] == 2  # J2: segments strictly upstream of the section
    assert middle["downstream_buses"] == [3, 4, 5]
    assert by_segments[(3,)]["downstream_buses"] == [4]
    assert sum(s["n_segments"] for s in secs) == len(net.line.index)


def test_section_series_sums_and_customers():
    net = toy_tree()
    custs = ep.customers(net)
    secs = ep.annotate_sections(ep.sections(net, {c["bus"] for c in custs}, root=0), custs)
    head = next(s for s in secs if s["segments"] == [0, 1])
    assert head["length_km"] == pytest.approx(2 * LINE_KWARGS["length_km"])
    assert head["r_ohm"] == pytest.approx(2 * 0.2 * 0.01)
    assert head["r0_ohm"] == pytest.approx(2 * 0.8 * 0.01)
    assert head["n_downstream_customers"] == 3
    assert head["downstream_customer_phases"] == {"a": 1, "b": 1, "c": 1}
    leaf = next(s for s in secs if s["segments"] == [3])
    assert leaf["n_downstream_customers"] == 1
    # positions 0, 2, 4, ... carry PV; the three customers are at buses 2, 4, 5
    assert [c["position"] for c in custs if c["has_pv"]] == [0, 2]
    assert leaf["n_downstream_pv"] == 0  # bus 4 is position 1
    assert leaf["downstream_peak_load_kw"] == ep.CUSTOMER_PEAK_KW


# --- the three selection rules -------------------------------------------------------------


def fake_section(section: int, *, first_segment: int, r_ohm: float, depth: int,
                 customers: int, pv: int, busbar: bool = False) -> dict:  # fmt: skip
    return {
        "section": section,
        "first_segment": first_segment,
        "segments": [first_segment],
        "n_segments": 1,
        "near_bus": 100 + section,
        "far_bus": 200 + section,
        "depth_segments": depth,
        "length_km": 0.01,
        "r_ohm": r_ohm,
        "r0_ohm": 4 * r_ohm,
        "downstream_buses": list(range(customers)),
        "incident_to_busbar": busbar,
        "downstream_customers": list(range(customers)),
        "n_downstream_customers": customers,
        "downstream_customer_phases": {"a": customers, "b": 0, "c": 0},
        "n_downstream_pv": pv,
        "downstream_pv_kwp": ep.PV_KWP * pv,
        "downstream_peak_load_kw": ep.CUSTOMER_PEAK_KW * customers,
        "pv_kwp_times_r": ep.PV_KWP * pv * r_ohm,
        "peak_load_kw_times_r": ep.CUSTOMER_PEAK_KW * customers * r_ohm,
    }


def test_selection_rules_on_a_toy_example():
    secs = [
        # the busbar-incident section wins rule (a) on the number, and must be excluded (J3)
        fake_section(0, first_segment=0, r_ohm=1.0, depth=0, customers=20, pv=20, busbar=True),
        fake_section(1, first_segment=1, r_ohm=0.5, depth=2, customers=10, pv=8),   # rule (a)
        fake_section(2, first_segment=2, r_ohm=0.1, depth=4, customers=4, pv=1),
        fake_section(3, first_segment=3, r_ohm=0.1, depth=6, customers=3, pv=1),
        fake_section(4, first_segment=4, r_ohm=0.1, depth=9, customers=2, pv=1),  # < 3 custs
        fake_section(5, first_segment=5, r_ohm=0.9, depth=7, customers=5, pv=0),   # rule (c)
        fake_section(6, first_segment=6, r_ohm=0.2, depth=8, customers=9, pv=0),
    ]
    picked = ep.select_sections(secs)

    assert picked["a"]["section"] == 1  # 8 x 4 kWp x 0.5 ohm = 16, the largest among candidates
    assert picked["a"]["pool_size"] == 6

    # rule (b) pool: downstream PV > 0 and >= 3 customers -> sections 1, 2, 3; depths 2, 4, 6
    assert picked["b"]["pool_size"] == 3
    assert picked["b"]["median_depth_of_pool"] == 4.0
    assert picked["b"]["section"] == 2

    # rule (c) pool: zero downstream PV and >= 1 customer -> sections 5, 6
    assert picked["c"]["pool_size"] == 2
    assert picked["c"]["section"] == 5  # 5 x 4 kW x 0.9 = 18 beats 9 x 4 kW x 0.2 = 7.2


def test_rule_b_breaks_a_depth_tie_on_the_lowest_first_segment():
    secs = [
        fake_section(0, first_segment=9, r_ohm=0.1, depth=2, customers=3, pv=1),
        fake_section(1, first_segment=4, r_ohm=0.1, depth=6, customers=3, pv=1),
        fake_section(2, first_segment=7, r_ohm=0.1, depth=2, customers=3, pv=1),
        fake_section(3, first_segment=5, r_ohm=0.1, depth=6, customers=3, pv=1),
        fake_section(4, first_segment=8, r_ohm=0.1, depth=3, customers=1, pv=0),  # rule (c)
    ]
    picked = ep.select_sections(secs)
    assert picked["b"]["median_depth_of_pool"] == 4.0  # every section is 2 away from it
    assert picked["b"]["section"] == 1  # first_segment 4 is the lowest of 9, 4, 7, 5


def test_rule_pools_raise_when_empty():
    with pytest.raises(RuntimeError, match="rule \\(b\\) has an empty pool"):
        ep.select_sections([fake_section(0, first_segment=0, r_ohm=0.1, depth=1,
                                        customers=1, pv=1)])  # fmt: skip
    with pytest.raises(RuntimeError, match="rule \\(c\\) has an empty pool"):
        ep.select_sections([fake_section(0, first_segment=0, r_ohm=0.1, depth=1,
                                        customers=3, pv=3)])  # fmt: skip


# --- the error -----------------------------------------------------------------------------


def test_error_touches_only_the_intended_segments_and_columns():
    net = toy_tree()
    before = net.line.copy(deep=True)
    ep.apply_section_error(net, [1, 2])
    touched, untouched = [1, 2], [0, 3, 4]
    for segment in touched:
        assert net.line.at[segment, "r_ohm_per_km"] == pytest.approx(
            before.at[segment, "r_ohm_per_km"] * ep.R_FACTOR)
        assert net.line.at[segment, "r0_ohm_per_km"] == pytest.approx(
            before.at[segment, "r0_ohm_per_km"] * ep.R_FACTOR)
        assert net.line.at[segment, "max_i_ka"] == pytest.approx(
            before.at[segment, "max_i_ka"] * ep.RATING_FACTOR)
    for column in net.line.columns:
        if column in ep.ERROR_FIELDS:
            assert net.line.loc[untouched, column].equals(before.loc[untouched, column])
        else:
            assert net.line[column].equals(before[column]), column


def test_error_rejects_a_segment_outside_the_line_table():
    net = toy_tree()
    with pytest.raises(ValueError, match="not in the line table"):
        ep.apply_section_error(net, [99])


# --- own-phase voltage extraction ----------------------------------------------------------


def test_own_phase_voltages_pick_the_customer_phase_and_the_busbar():
    vm = np.array([
        [1.000, 1.001, 1.002],   # row 0, the busbar
        [0.990, 0.991, 0.992],   # row 1
        [0.980, 0.981, 0.982],   # row 2
    ])
    out = ep.own_phase_voltages(vm, customer_rows=[1, 2, 1], customer_phases=[0, 2, 1],
                                busbar_row=0)  # fmt: skip
    assert out.tolist() == [0.990, 0.982, 0.991, 1.000, 1.001, 1.002]


def test_own_phase_voltages_reject_a_wrong_shape():
    with pytest.raises(ValueError, match=r"\[buses, 3\]"):
        ep.own_phase_voltages(np.zeros((3, 2)), [0], [0], 0)


# --- the referenced contrast ---------------------------------------------------------------


def synthetic_legs(common_shift: float, signal=(3e-4, -1e-4, 0.0)):
    """Two legs over 2 days x 8 steps, 3 customers on phases a, b, c plus the 3 busbar columns.

    The error leg carries a per-customer daylight-only offset (so c_d = signal) plus
    `common_shift` added to **every** column in daylight, which is exactly what the busbar
    reference is there to remove.
    """
    n_days, n_steps, n_customers = 2, 8, len(signal)
    custs = [{"position": i, "bus": 10 + i, "phase": ph, "phase_index": i, "has_pv": i % 2 == 0}
             for i, ph in enumerate(ep.PHASES[:n_customers])]  # fmt: skip
    daylight = np.zeros((n_days, n_steps), dtype=bool)
    daylight[:, :5] = True
    rng = np.random.default_rng(20261024)
    nominal = 1.0 + rng.normal(0.0, 0.01, size=(n_days, n_steps, n_customers + 3))
    error = nominal.copy()
    for i, value in enumerate(signal):
        error[:, :, i] += value * daylight
    error += common_shift * daylight[:, :, None]
    return custs, daylight, nominal, error


def test_referenced_contrast_cancels_a_common_daylight_shift():
    signal = (3e-4, -1e-4, 0.0)
    out = {}
    for shift in (0.0, 0.01):
        custs, daylight, nominal, error = synthetic_legs(shift, signal)
        out[shift] = ep.reduce_leg(error, nominal, daylight, custs)
    # the unreferenced contrast moves with the shift; the referenced one does not
    assert out[0.0]["k_ref"] == pytest.approx(np.asarray(signal), abs=1e-12)
    assert out[0.01]["k_ref"] == pytest.approx(np.asarray(signal), abs=1e-12)
    assert out[0.01]["k"] == pytest.approx(np.asarray(signal) + 0.01, abs=1e-12)
    assert out[0.01]["k_busbar"] == pytest.approx(np.full(3, 0.01), abs=1e-12)
    assert out[0.0]["usable_days"] == [0, 1]
    assert out[0.0]["n_daylight_valid"] == [5, 5] and out[0.0]["n_night_valid"] == [3, 3]


def test_a_failed_step_drops_from_the_day_and_an_unusable_day_drops_from_k():
    custs, daylight, nominal, error = synthetic_legs(0.0)
    error[0, 0, :] = np.nan  # one failed daylight flow on day 0
    out = ep.reduce_leg(error, nominal, daylight, custs)
    assert out["n_daylight_valid"] == [4, 5]
    assert out["failed_steps"] == 1
    error[1, daylight[1], :] = np.nan  # day 1 loses every daylight step
    out = ep.reduce_leg(error, nominal, daylight, custs)
    assert out["usable_days"] == [0]
    with pytest.raises(RuntimeError, match="no day has a valid daylight"):
        ep.reduce_leg(np.full_like(error, np.nan), nominal, daylight, custs)


def test_illustrative_c1_matches_its_definition():
    out = ep.illustrative_c1(np.array([2e-4, 0.0]), [48, 48], [48, 48],
                             np.array([True, False]))  # fmt: skip
    expected = (out["z_K"] * ep.SIGMA_ILLUSTRATIVE
                * math.sqrt(2 * (1 / 48 + 1 / 48)) / 2)  # fmt: skip
    assert out["floor_pu"] == pytest.approx(expected)
    assert out["label"] == "ILLUSTRATIVE"
    assert out["ratio"]["downstream"]["max"] == pytest.approx(2e-4 / expected)


# --- the write discipline ------------------------------------------------------------------


def test_write_leg_refuses_to_overwrite(tmp_path):
    path = tmp_path / "leg.npz"
    arrays = {"vm": np.zeros((1, 2, 3))}
    first = ep.write_leg(path, arrays, {"leg": "nominal"})
    assert path.exists() and path.with_suffix(".json").exists()
    assert first["npz"]["sha256"] and first["sidecar"]["sha256"]
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        ep.write_leg(path, arrays, {"leg": "nominal"})
    assert not list(tmp_path.glob("*.partial.*"))


def test_write_leg_is_atomic_when_the_npz_write_raises(tmp_path, monkeypatch):
    path = tmp_path / "leg.npz"

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ep.np, "savez_compressed", explode)
    with pytest.raises(OSError, match="disk full"):
        ep.write_leg(path, {"vm": np.zeros(3)}, {"leg": "a"})
    assert not path.exists() and not path.with_suffix(".json").exists()
    assert not list(tmp_path.glob("*.partial.*"))


def test_write_json_once_refuses_to_overwrite_and_leaves_no_partial(tmp_path):
    path = tmp_path / "out.json"
    ep.write_json_once(path, {"a": 1})
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        ep.write_json_once(path, {"a": 2})
    assert path.read_text().strip().endswith("}")
    with pytest.raises(ValueError):  # allow_nan=False; nothing is published
        ep.write_json_once(tmp_path / "nan.json", {"a": float("nan")})
    assert not (tmp_path / "nan.json").exists()
    assert not list(tmp_path.glob("*.partial.*"))


# --- the recorded spec ---------------------------------------------------------------------


def test_the_scenario_and_the_judgement_calls_are_recorded_verbatim():
    assert ep.SCENARIO["days"]["start_date"] == "2016-06-01"
    assert ep.SCENARIO["days"]["n_days"] == 10
    assert ep.SCENARIO["loads"]["peak_kw"] == 4.0
    assert ep.SCENARIO["pv"]["rating_kwp"] == 4.0
    assert "SimBench" in ep.SCENARIO["independence"]
    assert sorted(ep.JUDGEMENT_CALLS) == [f"J{n}" for n in (1, 10, 2, 3, 4, 5, 6, 7, 8, 9)]
    assert sorted(ep.SELECTION_RULES) == ["a", "b", "c"]
    assert ep.STATUS.startswith("EXPLORATORY pilot steps 2-4")
