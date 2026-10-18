import numpy as np
import pytest

pytest.importorskip("pandapower")

from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import sensing as sn  # noqa: E402
from gridpulse.grid_study import CAP_LEVELS, STEPS  # noqa: E402

LEVELS = len(CAP_LEVELS)
LAYOUT = sn.Layout(
    buses=(1, 2, 3),
    max_vm=(1.1, 1.1, 1.1),
    customer_buses=(2, 3),
    lv_busbar=1,
    feeder_heads=(0,),
    feeder_of={2: 0, 3: 0},
    distance={1: 0.0, 2: 0.1, 3: 0.2},
)


def _state(vm3=1.0, line1=50.0, trafo_loading=50.0):
    """A day whose state does not depend on the cap level unless arrays are edited."""
    vm = np.full((STEPS, LEVELS, 3), 1.0, dtype=np.float32)
    vm[:, :, 2] = vm3
    line = np.full((STEPS, LEVELS, 2), 50.0, dtype=np.float32)
    line[:, :, 1] = line1
    trafo = np.zeros((STEPS, LEVELS, 4), dtype=np.float32)
    trafo[:, :, 2] = trafo_loading
    trafo[:, :, 3] = 1.0
    return {"vm": vm, "line": line, "trafo": trafo}


def test_readings_come_only_from_configured_sensors_at_the_applied_level():
    state = _state()
    state["vm"][10, 3, 2] = 1.2  # bus 3 is high only at cap level 3
    levels = np.full(STEPS, 3)
    config = sn.Config("one", transformer=True, voltages=(3,))
    readings = sn.measure(
        state, levels, config, LAYOUT, sn.MeasurementModel(), np.random.default_rng(0)
    )
    assert set(readings) == {
        "trafo_loading",
        "busbar_vm",
        "trafo_p",
        "trafo_q",
        "remote_vm",
        "remote_available",
    }
    assert readings["remote_vm"][10, 0] == pytest.approx(1.2)  # bus 3, applied level 3, p.u.
    assert readings["trafo_loading"].shape == (STEPS, 1)  # %, one device
    readings0 = sn.measure(
        state, np.zeros(STEPS, int), config, LAYOUT, sn.MeasurementModel(), np.random.default_rng(0)
    )
    assert readings0["remote_vm"][10, 0] == pytest.approx(1.0)
    sub, remote = sn.flagged_steps(readings, config, LAYOUT)
    assert remote[10] and remote.sum() == 1 and not sub.any()
    no_sensor = sn.measure(
        state,
        levels,
        sn.Config("t", transformer=True),
        LAYOUT,
        sn.MeasurementModel(),
        np.random.default_rng(0),
    )
    assert "remote_vm" not in no_sensor
    assert not any(sn.flagged_steps(no_sensor, sn.Config("t", transformer=True), LAYOUT)[0])


def test_noise_and_missingness_follow_the_measurement_model():
    state = _state()
    config = sn.Config("v", voltages=(2, 3))
    model = sn.MeasurementModel(sigma_v_remote=0.005, remote_missing=0.25)
    rng = np.random.default_rng(1)
    values, masks = [], []
    for _ in range(400):
        r = sn.measure(state, np.zeros(STEPS, int), config, LAYOUT, model, rng)
        values.append(r["remote_vm"] - 1.0)
        masks.append(r["remote_available"])
    values = np.concatenate(values)
    assert abs(values.mean()) < 5e-4 and values.std() == pytest.approx(0.005, rel=0.05)
    assert np.mean(masks) == pytest.approx(0.75, abs=0.05)
    state["vm"][:, :, 1:] = 1.2  # every remote reading violates ...
    r = sn.measure(
        state, np.zeros(STEPS, int), config, LAYOUT, sn.MeasurementModel(remote_missing=1.0), rng
    )
    assert not sn.flagged_steps(r, config, LAYOUT)[1].any()  # ... but none is delivered


def test_placement_rules_respect_budget_uniqueness_and_determinism():
    assert sn.place_topology(LAYOUT, 1) == (3,)
    assert sn.place_topology(LAYOUT, 2) == (3, 2)
    assert sn.place_random(LAYOUT, 2, 7) == sn.place_random(LAYOUT, 2, 7)
    assert len(set(sn.place_random(LAYOUT, 2, 3))) == 2
    calls = []

    def objective(chosen):
        calls.append(chosen)
        return 0.0  # all tied: the first candidate wins

    assert sn.greedy((5, 4, 6), 2, objective) == (5, 4)
    assert all(len(set(c)) == len(c) for c in calls)
    assert sn.greedy((5, 4, 6), 2, lambda c: -sum(c)) == (6, 5)


def _context(remote_violation_day=None, line_violation_day=None, days=range(7, 50)):
    """Nominal plan always safe at no action; the true grid violates where stated."""
    plan = {}
    for d in days:
        n_sets = 30 if d >= ds.FIRST_DECISION_DAY else 1
        plan[d] = np.full((n_sets, STEPS, LEVELS), -0.5)
    truth, states = {}, {}
    for d in days:
        if d < ds.FIRST_DECISION_DAY:
            continue
        truth[d] = np.full((STEPS, LEVELS), -0.5)
        states[d] = _state()
        if d == remote_violation_day:
            truth[d][40:44, :3] = 0.1  # caps 1.0-0.8 violate, deeper caps are safe
            states[d]["vm"][40:44, :3, 2] = 1.12
        if d == line_violation_day:
            truth[d][40:44, :3] = 0.1
            states[d]["line"][40:44, :3, 1] = 120.0  # mid-feeder line, not a head
    available = np.ones((max(days) + 1, STEPS, 2))
    return sn.DecisionContext(
        plan_norm=plan, truth_norm=truth, states=states, available=available,
        rating=np.ones(2), layout=LAYOUT, development=tuple(range(35, 42)),
        days=tuple(range(42, 50)),
    )  # fmt: skip


def _taus(ctx, config, model):
    records = sn.run_feedback_policy(ctx, "replay_aci", config, model, 0, ds.OnlineSettings())
    return {r["day"]: r["tau"] for r in records}, records


def test_unmeasured_violations_never_reach_the_controller():
    sub = sn.Config("substation", transformer=True, heads=(0,))
    ctx = _context(line_violation_day=43)  # line 1 is not a feeder head
    taus, records = _taus(ctx, sub, sn.MeasurementModel())
    assert sum(r["violation_steps"] for r in records) == 4  # it happened on the true grid
    assert all(r["observed_feedback"] == 0 for r in records)  # but was never observed
    full = sn.Config("full", transformer=True, lines=(0, 1))
    taus_full, _ = _taus(ctx, full, sn.MeasurementModel())
    assert taus_full[44] > taus[44]


def test_feedback_respects_causality_and_remote_delay():
    remote = sn.Config("r", transformer=True, voltages=(3,))
    ctx = _context(remote_violation_day=43)
    taus, _ = _taus(ctx, remote, sn.MeasurementModel())
    assert taus[43] == taus[42] - 0.001  # the violation day itself is decided without it
    assert taus[44] > taus[43]  # it reaches the next decision
    delayed, _ = _taus(ctx, remote, sn.MeasurementModel(remote_delay_days=2))
    assert delayed[44] < taus[44] and delayed[45] < delayed[44]  # not yet arrived
    assert delayed[46] > delayed[45]  # arrives two days later
    later = _context(remote_violation_day=47)
    early, _ = _taus(later, remote, sn.MeasurementModel())
    assert all(early[d] == taus[d] for d in range(42, 43))  # future data change nothing


def test_decision_timing_uses_only_past_measurements():
    record = sn.decision_timing(100, sn.MeasurementModel(remote_delay_days=1))
    assert record["latest_substation_measurement"] < record["decision_timestamp"]
    assert record["latest_remote_measurement"] < record["latest_substation_measurement"]
    assert record["remote_measurement_age_hours"] == pytest.approx(24.25)
    assert record["first_action_effective"] == record["decision_timestamp"]


def test_detection_summary_counts_and_rates():
    rows = np.array(
        [[2, 1, 2, 10, 2, 3, 0, 0, 0, 1], [0, 0, 1, 12, 0, 1, 0, 0, 0, 0]], dtype=float
    )  # per day: TP FP FN TN, then (hits, positives) for voltage, line, trafo
    out = sn.summarise_detection(rows)
    assert (out["tp"], out["fp"], out["fn"], out["tn"]) == (2, 1, 3, 22)
    assert out["recall"] == pytest.approx(2 / 5) and out["precision"] == pytest.approx(2 / 3)
    assert out["false_alarm_rate"] == pytest.approx(1 / 23)
    assert out["recall_voltage"] == pytest.approx(2 / 4) and out["recall_line"] is None
    assert out["violation_days"] == 2


def test_block_bootstrap_ratio_brackets_the_estimate():
    num = np.array([1, 0, 2, 1, 0, 3, 1] * 5, dtype=float)
    den = num + 1
    ci = sn.block_bootstrap_ratio(num, den)
    assert ci["estimate"] == pytest.approx(num.sum() / den.sum())
    assert ci["ci_low"] <= ci["estimate"] <= ci["ci_high"]


def test_se_gate_follows_the_registered_rule():
    def rows(se_hits, direct_hits, events=20, negatives=50, se_false=0):
        out = []
        for i in range(events):
            out.append(
                {
                    "config": "substation",
                    "event": True,
                    "event_voltage": True,
                    "se_flag": i < se_hits,
                    "direct_flag": i < direct_hits,
                }
            )
        for i in range(negatives):
            out.append(
                {
                    "config": "substation",
                    "event": False,
                    "event_voltage": False,
                    "se_flag": i < se_false,
                    "direct_flag": False,
                }
            )
        return out  # fmt: skip

    networks = {
        "a": rows(15, 5), "b": rows(15, 5), "c": rows(15, 5),  # +0.5 recall: pass
        "d": rows(15, 5, se_false=10),  # far +0.2: fail
        "e": rows(15, 5, events=5),  # too few events: not informative
    }  # fmt: skip
    gate = sn.se_gate(networks)
    assert gate["per_network"]["a"]["passed"] and not gate["per_network"]["d"]["passed"]
    assert gate["per_network"]["e"]["informative"] is False
    assert gate["networks_passed"] == 3 and gate["open"]
    networks.pop("c")
    assert not sn.se_gate(networks)["open"]


def test_cells_meeting_counts_new_networks_and_mismatch_truths_only():
    def run(meets):
        return {"replay_aci/x/realistic": {"meets_beta": meets}}

    results = {
        ds.DEVELOPMENT_NETWORK: {"decisions": {t: run(True) for t in sn.MISMATCH}},
        "n1": {"decisions": {"nominal": run(True), **{t: run(True) for t in sn.MISMATCH}}},
        "n2": {"decisions": {t: run(t == "mv_high") for t in sn.MISMATCH}},
    }
    assert sn.cells_meeting(results, "replay_aci/x/realistic") == 4


LAYOUT6 = sn.Layout(
    buses=(1, 2, 3, 4, 5, 6),
    max_vm=(1.1,) * 6,
    customer_buses=(2, 3, 4, 5, 6),
    lv_busbar=1,
    feeder_heads=(0, 1),
    feeder_of={2: 0, 3: 0, 4: 0, 5: 1, 6: 1},
    distance={1: 0.0, 2: 0.1, 3: 0.2, 4: 0.3, 5: 0.15, 6: 0.25},
)


def _design_contexts(development_bus=3, evaluation_bus=None):
    """Contexts of every design truth: overvoltage at `development_bus` on development days
    (35-41); on evaluation days (42-49) quiet, or violating at `evaluation_bus` with a
    changed planning model too."""
    contexts = {}
    for truth in sn.DESIGN_TRUTHS:
        plan, truth_norm, states = {}, {}, {}
        for d in range(7, 50):
            n_sets = 30 if d >= ds.FIRST_DECISION_DAY else 1
            plan[d] = np.full((n_sets, STEPS, LEVELS), -0.5)
            if d < ds.FIRST_DECISION_DAY:
                continue
            truth_norm[d] = np.full((STEPS, LEVELS), -0.5)
            vm = np.full((STEPS, LEVELS, 6), 1.0, dtype=np.float32)
            bus = development_bus if d <= 41 else evaluation_bus
            if bus is not None:
                truth_norm[d][40:48, :3] = 0.1
                vm[40:48, :3, LAYOUT6.buses.index(bus)] = 1.12
            if d > 41 and bus is not None:
                plan[d][:, 40:48, :] = 0.3
            trafo = np.zeros((STEPS, LEVELS, 4), dtype=np.float32)
            trafo[:, :, 2], trafo[:, :, 3] = 50.0, 1.0
            line = np.full((STEPS, LEVELS, 3), 50.0, dtype=np.float32)
            states[d] = {"vm": vm, "line": line, "trafo": trafo}
        contexts[truth] = sn.DecisionContext(
            plan_norm=plan, truth_norm=truth_norm, states=states,
            available=np.ones((50, STEPS, 2)), rating=np.ones(2), layout=LAYOUT6,
            development=tuple(range(35, 42)), days=tuple(range(35, 42)),
            pv_by_bus={2: 0.01, 6: 0.03},
        )  # fmt: skip
    return contexts


def test_sensor_design_uses_development_days_only():
    online = ds.OnlineSettings()
    quiet = sn.design_placements(_design_contexts(), LAYOUT6, online)
    assert quiet["risk"][0] == 3 and quiet["greedy_detect"][0] == 3  # it reads development
    loud = sn.design_placements(_design_contexts(evaluation_bus=5), LAYOUT6, online)
    assert loud == quiet  # evaluation-day truth, states and plans change nothing
    moved = sn.design_placements(_design_contexts(development_bus=5), LAYOUT6, online)
    assert moved["risk"][0] == 5 and moved["greedy_detect"][0] == 5


# --- Phase 6: noise tied to the observation identity ---------------------------------
# The Phase 5 defect (docs/phase5_results.md s. 11): `seed_of` summed bytes, so run
# identities collided, and one random stream per run gave identical sensors different noise
# in different configurations. `seed_of` stays for reproducing Phase 5; `NoiseBank` fixes it.

NOISY = sn.MeasurementModel(
    sigma_v_substation=0.002, sigma_v_remote=0.01, sigma_loading=0.01, remote_missing=0.3
)
SUB_HEADS = sn.Config("substation", transformer=True, heads=(0,))


def _read(config, bank, day=50, levels=None, model=NOISY):
    levels = np.zeros(STEPS, int) if levels is None else levels
    return sn.measure(_state(), levels, config, LAYOUT, model, None, noise=bank, day=day)


def test_phase5_seed_derivation_collides_but_noise_identity_does_not():
    names = [f"substation+{k}:random_{s}" for k in sn.BUDGETS for s in sn.RANDOM_SEEDS]
    assert len({sn.seed_of("nominal", "realistic", n) for n in names}) < len(names)  # defect
    bank = sn.NoiseBank("net", "nominal")
    streams = [bank.normal(q, (e,), 50)[:, 0] for q in ("meter_voltage", "line_current")
               for e in range(30)]  # fmt: skip
    assert len({tuple(z) for z in streams}) == len(streams)
    assert max(abs(np.corrcoef(streams)[np.triu_indices(len(streams), 1)])) < 0.5


def test_identical_sensors_share_noise_whatever_the_configuration_or_its_name():
    bank = sn.NoiseBank("net", "nominal")
    one = _read(sn.with_remote(SUB_HEADS, (3,), "substation+1:topology"), bank)
    two = _read(sn.with_remote(SUB_HEADS, (2, 3), "renamed and larger"), bank)
    assert np.array_equal(one["remote_vm"][:, 0], two["remote_vm"][:, 1])  # bus 3
    assert one["remote_available"][0] == two["remote_available"][1]
    for key in ("trafo_loading", "busbar_vm", "trafo_p", "trafo_q", "head_loading"):
        assert np.array_equal(one[key], two[key])  # substation noise unaffected
    full = _read(sn.Config("full", transformer=True, voltages=(1, 2, 3), lines=(0, 1)), bank)
    assert np.array_equal(full["line_loading"][:, 0], one["head_loading"][:, 0])  # same line
    assert np.array_equal(full["remote_vm"][:, 2], one["remote_vm"][:, 0])


def test_noise_differs_across_observation_identities_and_ignores_the_applied_cap():
    bank = sn.NoiseBank("net", "nominal")
    base = bank.normal("meter_voltage", (3,), 50)
    for other in (
        bank.normal("meter_voltage", (2,), 50),
        bank.normal("meter_voltage", (3,), 51),
        bank.normal("line_current", (3,), 50),
        sn.NoiseBank("net", "mv_high").normal("meter_voltage", (3,), 50),
        sn.NoiseBank("other", "nominal").normal("meter_voltage", (3,), 50),
        sn.NoiseBank("net", "nominal", replication=1).normal("meter_voltage", (3,), 50),
    ):
        assert not np.array_equal(base, other)
    config = sn.with_remote(SUB_HEADS, (3,), "r")
    deep = _read(config, bank, levels=np.full(STEPS, 5))
    shallow = _read(config, bank)
    assert np.array_equal(deep["remote_vm"], shallow["remote_vm"])  # state is flat here
    biased = sn.MeasurementModel(sigma_v_remote=0.01, sigma_bias_remote=0.005)
    offsets = [_read(config, sn.NoiseBank("net", t), day=d, model=biased)["remote_vm"]
               - _read(config, sn.NoiseBank("net", t), day=d, model=sn.MeasurementModel(
                   sigma_v_remote=0.01))["remote_vm"] for t in ("nominal", "mv_high")
               for d in (40, 41)]  # fmt: skip
    assert all(np.allclose(o, offsets[0]) for o in offsets)  # one bias per device


def test_noise_is_reproducible_across_processes_and_simulated_days():
    import subprocess
    import sys

    code = (
        "from gridpulse import sensing as sn;"
        "print(repr(float(sn.NoiseBank('net', 'nominal').normal('meter_voltage', (3,), 50)[7, 0])))"
    )
    other = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    here = sn.NoiseBank("net", "nominal").normal("meter_voltage", (3,), 50)[7, 0]
    assert float(other.stdout) == here
    fresh, used = sn.NoiseBank("net", "nominal"), sn.NoiseBank("net", "nominal")
    for day in range(40, 60):
        used.normal("meter_voltage", (3,), day)
    assert np.array_equal(
        fresh.normal("meter_voltage", (3,), 50), used.normal("meter_voltage", (3,), 50)
    )


def test_budget_changes_keep_the_noise_and_missingness_of_existing_sensors():
    bank = sn.NoiseBank("net", "nominal")
    small = _read(sn.with_remote(SUB_HEADS, (3,), "k1"), bank, day=60)
    large = _read(sn.with_remote(SUB_HEADS, (3, 2), "k2"), bank, day=60)
    assert np.array_equal(small["remote_vm"][:, 0], large["remote_vm"][:, 0])
    assert small["remote_available"][0] == large["remote_available"][0]
    rates = [_read(sn.with_remote(SUB_HEADS, (3,), "r"), bank, day=d,
                   model=sn.MeasurementModel(remote_missing=p))["remote_available"][0]
             for p in (0.05, 0.5) for d in range(36, 136)]  # fmt: skip
    low, high = np.array(rates[:100]), np.array(rates[100:])
    assert np.all(high <= low)  # nested: a day missing at 5 % is also missing at 50 %


def test_identity_noise_feedback_stays_causal():
    remote = sn.Config("r", transformer=True, voltages=(3,))
    model = sn.MeasurementModel(sigma_v_remote=0.01, remote_delay_days=1)
    bank = sn.NoiseBank("toy", "nominal")

    def taus(ctx):
        records = sn.run_feedback_policy(
            ctx, "replay_aci", remote, model, 0, ds.OnlineSettings(), noise=bank
        )
        return {r["day"]: r["tau"] for r in records}

    quiet, late = taus(_context()), taus(_context(remote_violation_day=47))
    assert all(quiet[d] == late[d] for d in range(42, 49))  # day 47 reaches day 49 only
    assert late[49] > quiet[49]


def test_guard_and_persistence_rules_follow_their_definitions():
    config = sn.Config("r", voltages=(3,))
    model = sn.MeasurementModel(sigma_v_remote=0.01)
    readings = {"remote_vm": np.full((STEPS, 1), 1.0), "remote_available": np.array([True])}
    readings["remote_vm"][10, 0] = 1.105  # single step just over the limit
    readings["remote_vm"][20:23, 0] = 1.125  # three steps clearly over
    plain = sn.flagged_steps(readings, config, LAYOUT, alarm=sn.AlarmRule("unfiltered"))[1]
    assert plain[10] and plain[20:23].all() and plain.sum() == 4
    guard = sn.flagged_steps(readings, config, LAYOUT, alarm=sn.AlarmRule("g", guard=2.0),
                             model=model)[1]  # fmt: skip
    assert not guard[10] and guard[20:23].all()  # 1.105 < 1.10 + 2 x 0.01
    persist = sn.flagged_steps(readings, config, LAYOUT, alarm=sn.AlarmRule("p", persistence=2),
                               model=model)[1]  # fmt: skip
    assert not persist[10] and persist[20:23].all()
    assert np.array_equal(plain, sn.flagged_steps(readings, config, LAYOUT)[1])  # Phase 5


def test_meter_scope_leaves_substation_readings_unfiltered():
    config = sn.Config("s", transformer=True, voltages=(3,))
    model = sn.MeasurementModel(sigma_v_remote=0.01, sigma_loading=0.01)
    readings = {
        "trafo_loading": np.full((STEPS, 1), 50.0), "busbar_vm": np.full((STEPS, 1), 1.0),
        "trafo_p": np.zeros((STEPS, 1)), "trafo_q": np.zeros((STEPS, 1)),
        "remote_vm": np.full((STEPS, 1), 1.0), "remote_available": np.array([True]),
    }  # fmt: skip
    readings["trafo_loading"][30, 0] = 101.0  # one short overload at the transformer
    readings["remote_vm"][60, 0] = 1.105  # one short meter exceedance
    meters = sn.AlarmRule("m", persistence=3, scope="meters")
    every = sn.AlarmRule("a", persistence=3)
    sub_m, remote_m = sn.flagged_steps(readings, config, LAYOUT, alarm=meters, model=model)
    sub_a, remote_a = sn.flagged_steps(readings, config, LAYOUT, alarm=every, model=model)
    assert sub_m[30] and not remote_m.any()  # substation unfiltered, meter filtered
    assert not sub_a.any() and not remote_a.any()
    with pytest.raises(ValueError):
        sn.flagged_steps(readings, config, LAYOUT, alarm=sn.AlarmRule("x", 0, 2, "nowhere"),
                         model=model)  # fmt: skip


def test_persistence_keeps_runs_at_the_edges_and_of_exact_length():
    over = np.zeros((STEPS, 3), dtype=bool)
    over[:3, 0] = True  # starts at the first step, length 3
    over[STEPS - 3 :, 1] = True  # ends at the last step, length 3
    over[40:42, 2] = True  # length 2: dropped
    kept = sn._persistent(over, 3)
    assert kept[:3, 0].all() and kept[STEPS - 3 :, 1].all() and not kept[:, 2].any()
    assert kept.sum() == 6


def test_persistence_with_delay_stays_causal():
    remote = sn.Config("r", transformer=True, voltages=(3,))
    model = sn.MeasurementModel(sigma_v_remote=0.0, remote_delay_days=1)
    rule = sn.AlarmRule("persist3", persistence=3)

    def taus(ctx):
        records = sn.run_feedback_policy(
            ctx, "replay_aci", remote, model, 0, ds.OnlineSettings(),
            noise=sn.NoiseBank("toy", "nominal"), alarm=rule,
        )  # fmt: skip
        return {r["day"]: r["tau"] for r in records}

    quiet, late = taus(_context()), taus(_context(remote_violation_day=46))
    assert all(quiet[d] == late[d] for d in range(42, 48))  # day 46 reaches day 48 only
    assert late[48] > quiet[48]  # a 4-step violation passes the 3-step rule


def test_substation_quantities_and_meter_biases_draw_distinct_noise():
    bank = sn.NoiseBank("net", "nominal")
    streams = [bank.normal(q, (0,), 50)[:, 0]
               for q in ("busbar_voltage", "trafo_loading", "trafo_p", "trafo_q")]  # fmt: skip
    assert len({tuple(z) for z in streams}) == 4
    biases = bank.bias("meter_voltage", tuple(range(20)))
    assert len(set(biases)) == 20 and abs(biases.mean()) < 1.0


def test_phase5_legacy_path_is_pinned():
    """Phase 5 behaviour (one random stream, `noise=None`, no alarm rule) must not change:
    the frozen Phase 5 results depend on it. Values from the committed Phase 5 code."""
    ctx = _context(remote_violation_day=43)
    config = sn.Config("legacy", transformer=True, heads=(0,), voltages=(3,))
    model = sn.MeasurementModel(
        sigma_v_substation=0.002, sigma_v_remote=0.03, sigma_loading=0.01, remote_missing=0.2,
        remote_delay_days=1,
    )  # fmt: skip
    records = sn.run_feedback_policy(ctx, "replay_aci", config, model, 7, ds.OnlineSettings())
    assert [round(r["tau"], 12) for r in records] == [
        -0.007,
        -0.008,
        -0.009,
        0.01,
        0.009,
        0.008,
        0.007,
        0.006,
    ]
    assert [r["observed_feedback"] for r in records] == [0, 0, 2, 0, 0, 0, 0, 0]


def test_exact_readings_through_the_noise_bank_equal_the_true_state():
    state = _state(vm3=1.07, line1=80.0, trafo_loading=60.0)
    config = sn.Config("f", transformer=True, heads=(0,), voltages=(2, 3), lines=(0, 1))
    readings = sn.measure(state, np.zeros(STEPS, int), config, LAYOUT, sn.MeasurementModel(),
                          None, noise=sn.NoiseBank("net", "nominal"), day=50)  # fmt: skip
    assert np.array_equal(readings["remote_vm"][:, 1], state["vm"][:, 0, 2])
    assert np.array_equal(readings["line_loading"], state["line"][:, 0, :])
    assert readings["remote_available"].all()


def test_substation_runs_do_not_depend_on_remote_meter_noise():
    sub = sn.Config("substation", transformer=True, heads=(0,))
    base = {"sigma_v_substation": 0.002, "sigma_loading": 0.01}
    runs = [
        sn.run_feedback_policy(
            _context(line_violation_day=44), "replay_aci", sub,
            sn.MeasurementModel(sigma_v_remote=sigma, sigma_bias_remote=bias, **base), 0,
            ds.OnlineSettings(), noise=sn.NoiseBank("toy", "nominal"),
        )
        for sigma, bias in ((0.005, 0.0), (0.02, 0.0), (0.002, 0.0098))
    ]  # fmt: skip
    assert runs[0] == runs[1] == runs[2]
