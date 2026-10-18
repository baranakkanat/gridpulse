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


@pytest.mark.xfail(
    strict=True,
    reason="known defect (docs/phase5_results.md s. 11): seed_of sums bytes, so distinct "
    "run identities share seeds; kept unfixed so that the evaluation stays reproducible",
)
def test_seed_of_is_unique_across_run_identities():
    names = [f"substation+{k}:random_{s}" for k in sn.BUDGETS for s in sn.RANDOM_SEEDS]
    assert len({sn.seed_of("nominal", "realistic", n) for n in names}) == len(names)
