from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pandapower")

from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import margins as mg  # noqa: E402
from gridpulse import reserves as rs  # noqa: E402
from gridpulse import robust_study as rb  # noqa: E402
from gridpulse import sensing as sn  # noqa: E402
from gridpulse import stress as st  # noqa: E402
from gridpulse.__main__ import main  # noqa: E402
from gridpulse.grid_study import CAP_LEVELS, STEPS  # noqa: E402

LEVELS = len(CAP_LEVELS)
LAYOUT = sn.Layout(
    buses=(1, 2, 3), max_vm=(1.1, 1.1, 1.1), customer_buses=(2, 3), lv_busbar=1,
    feeder_heads=(0,), feeder_of={2: 0, 3: 0}, distance={1: 0.0, 2: 0.1, 3: 0.2},
)  # fmt: skip
SUB = sn.Config("substation", transformer=True, heads=(0,))
DAYLIGHT = np.zeros(STEPS, dtype=bool)
DAYLIGHT[30:70] = True


def _raw(over=-0.04, under=-0.1, line=-50.0, trafo=-50.0, slope=0.0):
    """One day's nominal exceedances (1 set x steps x levels x 4); `slope` makes deeper caps
    reduce overvoltage and loading linearly (per level, in each unit)."""
    raw = np.empty((1, STEPS, LEVELS, 4))
    depth = np.arange(LEVELS)[None, :]
    raw[..., 0] = over - slope * 0.001 * depth
    raw[..., 1] = under
    raw[..., 2] = line - slope * depth
    raw[..., 3] = trafo - slope * depth
    return raw


def _state(vm=1.04, loading=60.0, head=50.0):
    state = {
        "vm": np.full((STEPS, LEVELS, 3), vm), "line": np.full((STEPS, LEVELS, 1), head),
        "trafo": np.zeros((STEPS, LEVELS, 4)),
    }  # fmt: skip
    state["trafo"][:, :, 2], state["trafo"][:, :, 3] = loading, vm
    return state


def _available(days=80):
    available = np.zeros((days, STEPS, 1))
    available[:, 30:70, 0] = 1.0
    return available


def _corrector(plan=None, **kw):
    plan = plan or {d: _raw() for d in range(80)}
    nominal = {d: _state() for d in range(80)}
    settings = mg.CorrectorSettings(safety_margin=kw.pop("margin", 0.0), lag_days=kw.pop("lag", 0))
    return rs.ReserveCorrector(plan, nominal, LAYOUT, SUB, sn.MeasurementModel(), settings, **kw)


def _readings(offset=0.0):
    return {
        "busbar_vm": np.full((STEPS, 1), 1.04 + offset), "trafo_loading": np.full((STEPS, 1), 60.0),
        "trafo_p": np.zeros((STEPS, 1)), "trafo_q": np.zeros((STEPS, 1)),
        "head_loading": np.full((STEPS, 1), 50.0),
    }  # fmt: skip


def test_reserves_are_added_in_their_own_units_and_never_mixed():
    vector = rs.reserve_vector(0.002, 3.0)
    assert np.allclose(vector, [0.002, 0.002, 3.0, 3.0])  # p.u., p.u., %, %
    raw = np.array([-0.001, -0.2, -2.0, -50.0])  # overvoltage binds at 0.001 p.u. from limit
    assert rs.type_norm(raw, rs.VOLTAGE) == pytest.approx(-0.01)  # 0.001 p.u. / 0.1
    assert rs.type_norm(raw, rs.LOADING) == pytest.approx(-0.02)  # 2 % / 100
    shifted = ds.normalised(raw + vector)
    assert shifted == pytest.approx(max((-0.001 + 0.002) / 0.1, (-2.0 + 3.0) / 100))
    failed = raw.copy()
    failed[2] = np.nan  # a failed flow is infeasible for every type
    assert rs.type_norm(failed, rs.VOLTAGE) == np.inf and ds.normalised(failed) == np.inf


def test_shared_mode_is_phase7_and_equal_reserves_give_the_same_plan():
    plan = {d: _raw(over=-0.002 - 0.0001 * (d % 5), line=-1.5, slope=1.0) for d in range(80)}
    nominal = {d: _state() for d in range(80)}
    settings = mg.CorrectorSettings(safety_margin=0.02)
    phase7 = mg.ResidualCorrector(plan, nominal, LAYOUT, SUB, sn.MeasurementModel(), settings)
    shared = rs.ReserveCorrector(plan, nominal, LAYOUT, SUB, sn.MeasurementModel(), settings)
    assert np.array_equal(phase7.replay(60), shared.replay(60))  # the Phase 7 code path
    equal = rs.ReserveCorrector(plan, nominal, LAYOUT, SUB, sn.MeasurementModel(),
                                mg.CorrectorSettings(), reserves=(0.002, 2.0))  # fmt: skip
    assert np.allclose(equal.replay(60), phase7.replay(60))
    assert np.array_equal(ds.first_safe(equal.replay(60)), ds.first_safe(phase7.replay(60)))


def test_generalised_tuning_reproduces_the_phase7_margin_and_records_the_curve():
    rng = np.random.default_rng(3)
    plan = {d: _raw(over=-0.03, line=-4.0 + rng.normal(0, 1.5), slope=1.0) for d in range(80)}
    available, days = _available(), list(range(40, 80))
    phase7 = mg.tuned_safety_margin(plan, available, days, 0.1)
    ours = rs.tuned_shared(plan, available, days, 0.1)
    assert ours["s"] == phase7 and len(ours["curve"]) == len(mg.MARGIN_GRID)
    assert all(
        a >= b for a, b in zip(ours["curve"], ours["curve"][1:], strict=False)
    )  # weakly falling here


def test_fixed_reserves_are_tuned_per_type_and_voltage_uses_the_tap_step():
    rng = np.random.default_rng(5)
    # voltage 0.026 p.u. below the limit: binds only after the 0.025 p.u. tap-step shift
    plan = {d: _raw(over=-0.026 + rng.normal(0, 0.0007), line=-30.0, slope=1.0) for d in range(80)}
    available, days = _available(), list(range(40, 80))
    tuned = rs.tuned_fixed_reserves(plan, available, days, 0.1)
    assert tuned["r_v"] > 0.0 and tuned["r_l"] == 0.0  # loading never binds
    # loading rising day by day (as PV in spring): the replay under-predicts tomorrow
    loud = {d: _raw(over=-0.2, line=-6.0 + 0.09 * d, slope=1.0) for d in range(80)}
    other = rs.tuned_fixed_reserves(loud, available, days, 0.1)
    assert other["r_v"] == 0.0 and other["r_l"] > 0.0  # and the other way round
    assert len(tuned["curve_v"]) == len(rs.GRID_V) and len(tuned["curve_l"]) == len(rs.GRID_L)


def test_the_least_acceptable_curtailment_is_taken_even_when_deeper_caps_are_worse():
    # transformer loading can rise again under deep curtailment (reverse flow -> import)
    acceptable = np.array([[False, True, False, False], [False, False, False, False]])
    assert rs.first_level(acceptable).tolist() == [1, ds.LAST_LEVEL]
    stacked = np.stack([acceptable, acceptable])
    assert rs.first_level(stacked).tolist() == [[1, ds.LAST_LEVEL]] * 2


class _Guarded(dict):
    limit = -1

    def __getitem__(self, day):
        if day > self.limit:
            raise AssertionError(f"read day {day}; only days <= {self.limit} are available")
        return super().__getitem__(day)


@pytest.mark.parametrize("reserves", [None, (0.001, 1.0), "rolling"])
def test_delayed_injections_are_never_read_early(reserves):
    plan = _Guarded({d: _raw(slope=1.0) for d in range(80)})
    c = _corrector(plan, reserves=reserves, available=_available(), delay_days=2, lag=2)
    for day in range(50, 70):
        plan.limit = day - 3  # injections of day j arrive after day j + 2
        c.replay(day)


def test_rolling_reserve_starts_conservative_and_learns_from_the_operators_model_only():
    available = _available()
    flat = {d: _raw(over=-0.0005, line=-30.0, slope=1.0) for d in range(80)}
    c = _corrector(flat, reserves="rolling", available=available)
    assert c.rolling(36) == (rs.GRID_V[-1], rs.GRID_L[-1])  # < 7 window days
    assert c.rolling(70) == (0.0, 0.0)  # replay never under-predicts: no reserve needed
    rising = {d: _raw(over=-0.004 + 0.0002 * d, line=-30.0, slope=1.0) for d in range(80)}
    c = _corrector(rising, reserves="rolling", available=available)
    r_v, r_l = c.rolling(70)
    assert r_v > 0.0 and r_l == 0.0  # voltage rises day by day: the replay under-predicts


def test_missing_substation_days_teach_nothing():
    c = _corrector(missing_days={40})
    c.observe(40, _readings(offset=0.03), np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["v_hat"] == 0.0
    c.observe(41, _readings(offset=0.03), np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["v_hat"] == pytest.approx(0.03)


def test_metered_injection_conditions_change_only_what_they_name():
    rng = np.random.default_rng(0)
    arrays = {n: rng.uniform(0.1, 1.0, (30, STEPS, 4)) for n in st.PROFILE_NAMES}
    sets = {n: arrays[n][20][None].copy() for n in st.PROFILE_NAMES}
    q = st.metered_sets(sets, arrays, "net", "I2_load_q", 20)
    assert np.allclose(q["load_q_mvar"], sets["load_p_mw"] * np.tan(np.arccos(0.95)))
    assert np.array_equal(q["sgen_p_mw"], sets["sgen_p_mw"])
    pv = st.metered_sets(sets, arrays, "net", "I3_pv_over", 20)
    assert np.allclose(pv["sgen_p_mw"], 1.05 * sets["sgen_p_mw"])
    assert np.array_equal(pv["load_p_mw"], sets["load_p_mw"])
    a = st.metered_sets(sets, arrays, "net", "I1_meter_noise", 20)
    b = st.metered_sets(sets, arrays, "net", "I1_meter_noise", 20)
    c = st.metered_sets(sets, arrays, "net", "I1_meter_noise", 21)
    assert np.array_equal(a["load_p_mw"], b["load_p_mw"])  # identity-seeded
    assert not np.array_equal(a["load_p_mw"], c["load_p_mw"])
    assert abs(np.std(a["load_p_mw"] / sets["load_p_mw"] - 1) - 0.02) < 0.006
    m = st.metered_sets(sets, arrays, "net", "I4_missing", 20)
    filled = ~np.isclose(m["load_p_mw"][0], sets["load_p_mw"][0]).all(axis=0)
    assert np.allclose(m["load_p_mw"][0][:, filled], arrays["load_p_mw"][13][:, filled])
    assert np.allclose(m["load_q_mvar"][0][:, filled], arrays["load_q_mvar"][13][:, filled])
    early = st.metered_sets(sets, arrays, "net", "I4_missing", 10)  # no week-old data yet
    assert np.array_equal(early["load_p_mw"], sets["load_p_mw"])
    with pytest.raises(ValueError):
        st.metered_sets(sets, arrays, "net", "nope", 20)


def test_mv_profile_follows_the_pv_share_up_to_the_study_case_value():
    available = np.array([[0.0, 0.0], [0.5, 0.5], [1.0, 1.0], [2.0, 2.0]])
    profile = st.mv_profile(available, np.array([1.0, 1.0]), 1.025)
    assert np.allclose(profile, [1.025, 1.04, 1.055, 1.055])


def test_constant_slack_reproduces_the_phase5_states():
    from gridpulse import fullstate, grid, grid_study

    code = "1-LV-rural1--2-sw"
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    solver = ds.VariantSolver(net, ds.NOMINAL)
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    sets = ds.day_sets(arrays, 170, solver.pv_rating_mw, 1)
    storage = ds.day_storage(ds.storage_schedule(net, ds.NOMINAL, 366), 170, 1)
    buses = fullstate.lv_buses(net)
    a = fullstate.day_states(solver, sets, storage, buses)
    b = st.day_states(solver, sets, storage, buses, slack=np.full(STEPS, 1.025))
    assert float(net.ext_grid["vm_pu"].iloc[0]) == 1.025
    assert np.nanmax(np.abs(a["vm"] - b["vm"])) < 1e-6  # restart vs recycle: solver tolerance
    assert np.nanmax(np.abs(a["margins"] - b["margins"])) < 1e-4


def test_local_line_is_a_mid_feeder_cable_with_the_largest_pv_driven_rise():
    code = "1-LV-semiurb4--2-sw"
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    layout = sn.network_layout(net)
    line = st.local_line(net, layout)
    assert line not in layout.feeder_heads
    stressed = st.stress_network(code, "line_local")
    assert stressed.line.at[line, "r_ohm_per_km"] == pytest.approx(
        1.5 * net.line.at[line, "r_ohm_per_km"]
    )
    assert stressed.line.at[line, "max_i_ka"] == pytest.approx(0.8 * net.line.at[line, "max_i_ka"])
    others = stressed.line.drop(index=line)
    assert others["r_ohm_per_km"].equals(net.line.drop(index=line)["r_ohm_per_km"])


def test_plan_runs_every_policy_on_identical_days_and_only_valid_condition_pairs():
    primary, stress = rb.plan("nominal"), rb.plan("mv_daily")
    assert {row[0] for row in stress} == set(rb.POLICIES)
    assert all(row[1:] == ("I0", "S0", 0) for row in stress)
    keys = [rb.run_key(*row) for row in primary]
    assert len(keys) == len(set(keys))
    assert ("B2", "I0", "S3_delay", 0) not in primary and (
        "B2",
        "I0",
        "S4_missing",
        0,
    ) not in primary
    assert all(p in rb.POLICIES for p, *_ in primary)
    days = list(range(35, 365))
    assert rb.outage_days("net", days) == rb.outage_days("net", days)  # identity-seeded
    assert 0.1 < len(rb.outage_days("net", days)) / len(days) < 0.3


def _results(c5=(1.0, 900.0, 66.0), c1=(1.0, 1027.0, 66.2), c1f=(1.0, 1027.0, 66.2)):
    out = {}
    for net in ("1-LV-rural1--2-sw", "n1", "n2", "n3", "n4", "n5"):
        out[net] = {}
        for truth in rb.TRUTHS:
            nominal = truth == "nominal"
            runs = {}
            for policy, (viol, mis_mwh, nom_mwh) in (("C5", c5), ("C1", c1), ("C1f", c1f),
                                                      ("C6", c1)):  # fmt: skip
                runs[rb.run_key(policy)] = {
                    "avoidable_violation_steps": viol / 15 if not nominal else 0.0,
                    "curtailed_mwh": (nom_mwh if nominal else mis_mwh / 3) / 5,
                    "long_runs": 0.0, "meets_beta": True,
                }  # fmt: skip
            out[net][truth] = {"runs": runs, "observability": {}}
    return out


def test_h1_needs_non_inferiority_and_both_costs_and_credits_separation_only_alone():
    assert rb.primary(_results())["attribution"] == "separation"
    both = rb.primary(_results(c1f=(1.0, 900.0, 66.0)))  # the fine shared grid does as well
    assert both["met"] and both["attribution"] == "resolution"
    worse = rb.primary(_results(c5=(40.0, 800.0, 60.0)))  # cheaper, but 39 more violations
    assert not worse["met"] and not worse["ni"]["mismatch_violations"]
    dearer = rb.primary(_results(c5=(1.0, 900.0, 70.0)))  # costs more under the correct model
    assert not dearer["met"] and not dearer["nominal_cost"]["met"]
    assert rb.primary(_results())["mismatch_cost"]["ratio"] == pytest.approx(900 / 1027)


def test_cli_refuses_phase8_stages_out_of_order(tmp_path, capsys):
    assert main(["robust-study", "--stage", "evaluation", "--output-dir", str(tmp_path)]) == 1
    assert "freeze" in capsys.readouterr().err
    assert main(["robust-study", "--stage", "development", "--output-dir", str(tmp_path)]) == 1
    assert "physics" in capsys.readouterr().err
    assert not [p for p in Path(tmp_path).iterdir() if p.name.startswith("development")]


def _real_layout_plan():
    """Plan keys as in the operator's plan (`margin_study.plan_raw`): from day 7, one
    realised set per day."""
    return {d: _raw(slope=1.0) for d in range(7, 120)}


@pytest.mark.parametrize("reserves", [None, (0.001, 1.0), "rolling"])
def test_delayed_replay_starts_with_the_first_day_with_data(reserves):
    plan = _real_layout_plan()
    nominal = {d: _state() for d in range(35, 120)}
    settings = mg.CorrectorSettings(safety_margin=0.02, lag_days=2)
    c = rs.ReserveCorrector(plan, nominal, LAYOUT, SUB, sn.MeasurementModel(), settings,
                            reserves=reserves, available=_available(120), delay_days=2)  # fmt: skip
    first = c.replay(35)  # days 7..32 (truncated), not 5..32
    assert first.shape == (STEPS, LEVELS)
    assert list(rs.replay_days(35, 2, 7)) == list(range(7, 33))
    assert list(rs.replay_days(80, 2, 7)) == list(range(50, 78))
    assert list(rs.replay_days(80, 0, 7)) == list(range(52, 80))


def test_delayed_binary_plan_keeps_every_day_and_set_and_shifts_only_the_realised_one():
    plan_norm = {d: np.full((1 if d < 35 else 3, STEPS, LEVELS), float(d)) for d in range(7, 60)}
    ctx = sn.DecisionContext(plan_norm=plan_norm, truth_norm={}, states={}, available=None,
                             rating=None, layout=LAYOUT, development=(), days=())  # fmt: skip
    shifted = rb.delayed(ctx, 2).plan_norm
    assert sorted(shifted) == sorted(plan_norm)
    assert all(shifted[d].shape == plan_norm[d].shape for d in plan_norm)
    assert shifted[40][ds.REALISED][0, 0] == 38 and shifted[40][1][0, 0] == 40
    assert shifted[8][ds.REALISED][0, 0] == 7  # clamped at the first day with data
    replay = np.stack([shifted[j][ds.REALISED] for j in range(35 - 28, 35)]).max(axis=0)
    assert replay[0, 0] == 32  # the same as replaying days 7..32


def test_delayed_tuning_simulates_the_delayed_replay():
    plan = {d: _raw(over=-0.2, line=-30.0 + 0.4 * d, slope=1.0) for d in range(7, 100)}
    available, days = _available(100), list(range(40, 100))
    now = rs.tuned_fixed_reserves(plan, available, days, 0.1)["r_l"]
    late = rs.tuned_fixed_reserves(plan, available, days, 0.1, delay=2)["r_l"]
    assert late > now  # a staler replay under-predicts a rising load more


def test_failed_flows_are_their_own_violation_type():
    assert rb.violation_type(np.array([np.nan] * 4)) == "failed"
    assert rb.violation_type(np.array([0.1, -1.0, 0.3, np.nan])) == "line"


def test_a_stress_truth_equal_to_nominal_creates_no_violations():
    days = (40, 41)
    available = _available()
    nominal = np.full((STEPS, LEVELS), -0.5)
    nominal[50, 0] = 0.2  # one avoidable no-action violation under the nominal model too
    plan_norm = {d: nominal[None] for d in days}
    same = sn.DecisionContext(plan_norm=plan_norm, truth_norm={d: nominal for d in days},
                              states={}, available=available, rating=None, layout=LAYOUT,
                              development=(), days=days)  # fmt: skip
    assert rb.no_action(same)["created"] == 0 and rb.no_action(same)["truth"] == 2
    worse = nominal.copy()
    worse[40:44, 0] = 0.1
    stressed = sn.DecisionContext(plan_norm=plan_norm, truth_norm={d: worse for d in days},
                                  states={}, available=available, rating=None, layout=LAYOUT,
                                  development=(), days=days)  # fmt: skip
    assert rb.no_action(stressed)["created"] == 8 and rb.no_action(stressed)["removed"] == 0


def test_non_inferiority_and_cost_rules_at_their_boundaries():
    mis = ("tap_raise_lv", "mv_high", "pv_fixed_095")
    ok = _results(c5=(16.0, 924.3, 66.2))  # C1 + 15 violations; 0.90 x 1027 MWh; equal nominal
    h1 = rb.primary(ok)
    assert h1["ni"]["mismatch_violations"] and h1["met"]
    assert h1["mismatch_cost"]["ratio"] == pytest.approx(0.9)
    over = rb.non_inferior(_results(c5=(16.5, 900.0, 66.0)), rb.run_key("C5"), rb.run_key("C1"))
    assert not over["mismatch_violations"]
    dear = rb._cost(_results(c5=(1.0, 925.0, 66.0)), rb.run_key("C5"), rb.run_key("C1"), mis, 0.9)
    assert not dear["met"]
