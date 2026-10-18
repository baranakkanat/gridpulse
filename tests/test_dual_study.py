import json

import numpy as np
import pytest

pytest.importorskip("pandapower")

from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import grid_study as gs  # noqa: E402
from gridpulse.grid import GridSolver, absolute_profiles, load_network  # noqa: E402


@pytest.fixture(scope="module")
def nominal():
    net = load_network()
    return net, gs.daily_arrays(absolute_profiles(net))


def test_pv_reactive_power_follows_the_cosphi_characteristic():
    rating = np.array([1.0, 1.0, 1.0, 2.0])
    p = np.array([0.0, 0.5, 1.0, 1.5])
    q = ds.pv_reactive_power(p, rating, "cosphi_p", 0.9)
    assert q[0] == 0 and q[1] == 0  # cos phi = 1 up to half the rating
    assert q[2] == pytest.approx(-np.tan(np.arccos(0.9)))  # underexcited at full rating
    assert q[3] == pytest.approx(-1.5 * np.tan(np.arccos(0.95)))  # 75 % of rating: cos phi 0.95
    assert np.all(ds.pv_reactive_power(p, rating, "none", 1.0) == 0)
    fixed = ds.pv_reactive_power(p, rating, "fixed", 0.95)
    assert fixed == pytest.approx(-p * np.tan(np.arccos(0.95)))


def test_nominal_variant_reproduces_phase3_physics_bit_for_bit(nominal):
    net, arrays = nominal
    day = 172
    sets = gs.injection_sets(arrays, day, net.sgen["sn_mva"].to_numpy(dtype=float))
    sets = {name: values[:2] for name, values in sets.items()}  # realised and forecast
    phase3 = gs.day_physics(GridSolver(net), sets, np.zeros(len(net.storage)))
    solver = ds.VariantSolver(ds.variant_network(gs.NETWORK_CODE, ds.NOMINAL), ds.NOMINAL)
    phase4 = ds.day_margins(solver, sets, np.zeros((2, gs.STEPS, len(net.storage))))
    assert np.array_equal(phase3, phase4, equal_nan=True)


def test_tap_variant_shifts_lv_voltage_by_one_step_and_rejects_out_of_range():
    import pandapower as pp

    voltages = {}
    for steps in (0, -1):
        net = ds.variant_network(gs.NETWORK_CODE, ds.ModelVariant(tap_steps=steps))
        net.load["p_mw"] = net.load["q_mvar"] = net.sgen["p_mw"] = net.storage["p_mw"] = 0.0
        pp.runpp(net, numba=False)
        lv = ~net.bus.index.isin(net.ext_grid["bus"])
        voltages[steps] = net.res_bus.loc[lv, "vm_pu"].mean()
    assert voltages[-1] - voltages[0] == pytest.approx(1.025 * 0.025, abs=2e-3)
    with pytest.raises(ValueError, match="tap range"):
        ds.variant_network(gs.NETWORK_CODE, ds.ModelVariant(tap_steps=100))


def test_profile_charging_storage_respects_energy_capacity(nominal):
    net, _ = nominal
    schedule = ds.storage_schedule(net, ds.ModelVariant(storage="profile_charging"), 30)
    assert schedule.shape == (30, gs.STEPS, len(net.storage))
    assert (schedule >= 0).all() and schedule.max() > 0
    energy = schedule.sum(axis=1) * 0.25 * ds.STORAGE_EFFICIENCY  # per day, reset daily
    assert (energy <= net.storage["max_e_mwh"].to_numpy() + 1e-12).all()
    assert not ds.storage_schedule(net, ds.NOMINAL, 30).any()


def test_greedy_storage_sits_at_pv_buses_and_stays_within_limits():
    variant = ds.ModelVariant(storage="greedy")
    net = ds.variant_network(gs.NETWORK_CODE, variant)
    assert list(net.storage["bus"]) == list(net.sgen["bus"])
    benchmark = load_network()
    assert net.storage["max_e_mwh"].sum() == pytest.approx(benchmark.storage["max_e_mwh"].sum())
    schedule = ds.storage_schedule(net, variant, 60)
    limit = net.storage["sn_mva"].to_numpy()
    assert (np.abs(schedule) <= limit + 1e-12).all()
    eta, dt = ds.STORAGE_EFFICIENCY, 0.25
    flows = np.where(schedule > 0, schedule * eta, schedule / eta) * dt
    content = np.cumsum(flows.reshape(-1, len(limit)), axis=0)
    assert (content >= -1e-12).all()
    assert (content <= net.storage["max_e_mwh"].to_numpy() + 1e-12).all()
    assert (schedule > 0).any() and (schedule < 0).any()


def test_variant_cache_refuses_other_physics(tmp_path):
    folder = tmp_path / "net" / "nominal"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"fingerprint": "other"}))
    with pytest.raises(ValueError, match="different physics"):
        ds.compute_physics("net", 1.0, "nominal", ds.NOMINAL, [], tmp_path, workers=1)


def test_forecast_set_storage_uses_only_previous_days():
    schedule = np.arange(10 * gs.STEPS * 2, dtype=float).reshape(10, gs.STEPS, 2)
    storage = ds.day_storage(schedule, 8, 2)
    assert np.array_equal(storage[0], schedule[8])
    assert np.array_equal(storage[1], schedule[1:8].mean(axis=0))
    with pytest.raises(ValueError, match="nominal"):
        ds.day_storage(schedule, 8, 3)


def _synthetic(seed=0, days=range(7, 45), variants=("hot",)):
    """Normalised margins: 30 sets on decision days (realised, forecast, 28 scenarios),
    the realised set only before; each variant has its realised and forecast sets."""
    rng = np.random.default_rng(seed)
    norm, norm_v = {}, {v: {} for v in variants}
    for day in days:
        n_sets = 30 if day >= gs.FIRST_DECISION_DAY else 1
        margin = rng.normal(-0.05, 0.2, size=(n_sets, gs.STEPS, len(gs.CAP_LEVELS)))
        margin -= np.arange(len(gs.CAP_LEVELS)) * 0.04  # deeper caps are safer here
        norm[day] = margin
        if day >= gs.FIRST_DECISION_DAY:
            for i, v in enumerate(variants):
                norm_v[v][day] = margin[:2] + 0.03 * (i + 1)
    return norm, norm_v


def _available(days=45, night=()):
    available = np.ones((days, gs.STEPS, 2))
    available[:, list(night)] = 0.0
    return available


TUNED = {"static_dev_level": 7, "static_beta_level": 6, "point_margin_tau": 0.1}


def test_forecast_decisions_ignore_same_day_realised_and_future_data():
    norm, norm_v = _synthetic()
    tau = dict.fromkeys(ds.MARGIN_ONLINE, 0.02)
    args = ("forecast", ("hot",), tau, 2.4, TUNED)
    before = ds.decision_plans(norm, norm_v, 38, *args)
    norm[38][ds.REALISED] = 9.0  # the day's own realised outcome ...
    norm_v["hot"][38][ds.REALISED] = 9.0
    for day in range(39, 45):  # ... and everything after it
        norm[day][:] = 9.0
        norm_v["hot"][day][:] = 9.0
    after = ds.decision_plans(norm, norm_v, 38, *args)
    assert before.keys() == after.keys()
    for name in before:
        assert np.array_equal(before[name], after[name]), name


def test_run_cell_uses_no_later_data_and_tunes_on_development_only():
    norm, norm_v = _synthetic(seed=2, days=range(7, 60))
    available = _available(60, night=range(0, 20))
    development, days = list(range(35, 45)), list(range(45, 60))
    args = ("nominal", ("hot",), "forecast", available, np.ones(2), development, days)
    records, tuned = ds.run_cell(norm, norm_v, *args, ds.OnlineSettings())
    changed = {d: m.copy() for d, m in norm.items()}
    changed_v = {"hot": {d: m.copy() for d, m in norm_v["hot"].items()}}
    for day in range(52, 60):  # evaluation days after day 51 are altered
        changed[day][:] = 5.0
        changed_v["hot"][day][:] = 5.0
    altered, tuned_altered = ds.run_cell(changed, changed_v, *args, ds.OnlineSettings())
    assert tuned_altered == tuned
    for a, b in zip(records, altered, strict=True):
        if a["day"] <= 51:
            assert a == b
    assert any(a != b for a, b in zip(records, altered, strict=True))


def test_online_updates_count_daylight_only_and_clip():
    norm, norm_v = _synthetic(seed=1)
    available = _available(45, night=range(0, 30))
    online = ds.OnlineSettings()
    days = list(range(35, 45))
    records, _ = ds.run_cell(
        norm, norm_v, "nominal", ("hot",), "perfect", available, np.ones(2), days, days, online
    )
    for a, b in zip(records, records[1:], strict=False):
        for name in ("replay_aci", "point_aci"):
            step = a[f"{name}__tau"] + online.gamma * (
                a[f"{name}__daylight_violation_steps"] - online.beta
            )
            clipped = np.clip(step, online.tau_min, online.tau_max)
            assert b[f"{name}__tau"] == pytest.approx(clipped)
            assert a[f"{name}__clip"] == pytest.approx(clipped - step)
        level = a["static_aci__level_index"] + online.gamma_level * (
            a["static_aci__daylight_violation_steps"] - online.beta
        )
        assert b["static_aci__level_index"] == pytest.approx(np.clip(level, 0, 10))
    for r in records:
        assert r["no_action__daylight_violation_steps"] <= r["no_action__violation_steps"]
        # perfect information on a true nominal grid: `point` is the oracle
        assert r["point__violation_steps"] == r["oracle__violation_steps"] == r["unavoidable_steps"]
    hot, _ = ds.run_cell(
        norm, norm_v, "hot", ("hot",), "perfect", available, np.ones(2), days, days, online
    )
    # the ensemble contains the true variant, so with perfect information it is safe
    assert all(r["ensemble__violation_steps"] == r["unavoidable_steps"] for r in hot)


def test_static_level_and_point_margin_tuning():
    def levels(*head):  # 11 cap levels; the deeper ones are safe
        return np.array([list(head) + [-0.5] * (len(gs.CAP_LEVELS) - len(head))] * gs.STEPS)

    realised = [levels(1.0, 0.5, -0.1, -0.2)]
    daylight = [np.ones(gs.STEPS, dtype=bool)]
    assert ds.static_level(realised, daylight, 0.0) == 2
    assert ds.static_level([np.ones((gs.STEPS, 11))], daylight, 0.0) == 0  # fewest
    night = [np.zeros(gs.STEPS, dtype=bool)]
    assert ds.static_level(realised, night, 0.0) == 0  # night violations do not count
    point = [levels(-0.05, -0.2, -0.3, -0.4)]
    assert ds.tuned_point_margin(point, realised) == pytest.approx(0.21)  # 0.2 admits level 1
    assert np.array_equal(ds.first_safe(point[0], 0.25), np.full(gs.STEPS, 2))
    never = [np.ones((gs.STEPS, 11))]
    assert ds.tuned_point_margin(point, never) == 0.0  # fallback: fewest, then smallest tau


def test_better_follows_the_amended_definition_in_both_pair_orders():
    def cell(meets_a, meets_b, violations, curtailment):
        interval = {
            "avoidable_violation_steps": dict(zip(("ci_low", "ci_high"), violations, strict=True)),
            "curtailed_mwh": dict(zip(("ci_low", "ci_high"), curtailment, strict=True)),
        }
        return {
            "totals": {"a": {"meets_beta": meets_a}, "b": {"meets_beta": meets_b}},
            "paired_per_day": {"a_minus_b": interval},
        }

    assert ds.better(cell(True, False, (-2, -1), (1, 2)), "a", "b")
    assert not ds.better(cell(True, False, (-2, 0.5), (-2, -1)), "a", "b")  # not significant
    assert not ds.better(cell(False, False, (-2, -1), (-2, -1)), "a", "b")
    assert ds.better(cell(True, True, (0, 1), (-2, -1)), "a", "b")  # both meet, a curtails less
    assert not ds.better(cell(True, True, (0, 1), (-2, 0.5)), "a", "b")
    assert ds.better(cell(True, True, (0, 1), (1, 2)), "b", "a")  # reversed: b - a < 0
    assert ds.better(cell(False, True, (1, 2), (0, 1)), "b", "a")


def test_summarise_cell_feeds_better_with_the_right_sign():
    rng = np.random.default_rng(0)
    records = []
    for day in range(30):
        record = {"day": day, "unavoidable_steps": 0, "unavoidable_daylight_steps": 0}
        for name, curtailed in (("replay_aci", 1.0), ("static_aci", 2.0), ("oracle", 0.5)):
            record.update(
                {f"{name}__{m}": 0 for m in ds.METRICS if m != "curtailed_mwh"}
                | {
                    f"{name}__curtailed_mwh": curtailed + rng.normal(0, 0.01),
                    f"{name}__longest_violation_run": 0,
                    f"{name}__peak_margin": -0.1,
                }
            )
        records.append(record)
    summary = ds.summarise_cell(records, ds.OnlineSettings())
    pair = summary["paired_per_day"]["replay_aci_minus_static_aci"]
    assert pair["curtailed_mwh"]["ci_high"] < 0
    assert ds.better(summary, "replay_aci", "static_aci")
    assert not ds.better(summary, "static_aci", "replay_aci")


def test_leave_one_out_risk_has_a_known_answer():
    # three replay members of interest at one step: each violates at cap level 0 only;
    # all other members never violate. At most 1 violating member allowed at level 0 is
    # not met (3 > 1), so the rule picks level 1 where no member violates. Leave one out:
    # 2 others violate at level 0, still > 1, so level 1 again; the risk is 0.
    days = range(0, 40)
    norm = {d: np.full((30, gs.STEPS, len(gs.CAP_LEVELS)), -1.0) for d in days}
    for d in (10, 11, 12):  # inside the replay window of day 35 (days 7..34)
        norm[d][ds.REALISED, 10, 0] = 1.0
    truth = {d: np.full((gs.STEPS, len(gs.CAP_LEVELS)), -1.0) for d in days}
    truth[35][10, 1] = 1.0  # the chosen level 1 violates on day 35
    result = ds.risk_diagnostics(norm, truth, [35])
    replay = result["replay"]
    assert replay["active_steps"] == 1 and replay["realised_violations"] == 1
    assert replay["in_sample_predicted"] == 0 and replay["leave_one_out_predicted"] == 0
    assert replay["realised_over_leave_one_out"]["estimate"] == ds.UNBOUNDED_RATIO
    norm[13][ds.REALISED, 10, 1] = 1.0  # a fourth member violates at level 1 only
    replay = ds.risk_diagnostics(norm, truth, [35])["replay"]
    # rule on all 28: level 0 has 3 violators, level 1 has 1 -> level 1, in-sample 1/28;
    # leaving out member 13 the rule still picks level 1 and member 13 violates there: 1/28
    assert replay["in_sample_predicted"] == pytest.approx(1 / 28)
    assert replay["leave_one_out_predicted"] == pytest.approx(1 / 28)


def test_analyse_network_runs_every_cell_on_synthetic_data():
    norm, norm_v = _synthetic(seed=3, days=range(7, 365), variants=tuple(ds.VARIANTS))
    available = _available(365, night=range(0, 24))
    result = ds.analyse_network(
        norm, norm_v, available, np.ones(2), "evaluation", ds.OnlineSettings()
    )
    assert len(result["cells"]) == 2 * len(ds.TRUTHS)
    cell = result["cells"]["forecast/nominal"]
    assert cell["days"] == 183
    for policy, identity in cell["online_identity"].items():
        assert identity["identity_mean_feedback"] == pytest.approx(
            identity["mean_feedback_per_day"]
        ), policy
    assert set(result["materiality"]) == set(ds.VARIANTS)
    assert "leave_one_out_predicted" in result["diagnostics"]["nominal"]["replay"]


def test_load_margins_refuses_mismatched_physics(tmp_path):
    folder = tmp_path / "net" / "nominal"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(json.dumps({"fingerprint": "other"}))
    with pytest.raises(ValueError, match="does not match"):
        ds.load_margins(tmp_path, "net", "nominal", [35], 1.0, ds.NOMINAL)


def test_json_safe_output_handles_numpy_scalars_and_infinity():
    from gridpulse.__main__ import _json_safe

    value = {"a": np.bool_(True), "b": np.float64("inf"), "c": [np.int64(3)], "d": (1.5,)}
    assert json.loads(json.dumps(_json_safe(value))) == {
        "a": True,
        "b": "inf",
        "c": [3],
        "d": [1.5],
    }


def test_dual_study_cli_refuses_a_second_evaluation(tmp_path):
    from gridpulse.__main__ import main

    (tmp_path / "evaluation_summaries.json").write_text("{}")
    networks = ["1-LV-rural1--2-sw"]
    args = ["dual-study", "--stage", "evaluation", "--output-dir", str(tmp_path), "--networks"]
    assert main(args + networks) == 1  # refused before any computation
    assert (tmp_path / "evaluation_summaries.json").read_text() == "{}"
