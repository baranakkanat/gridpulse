from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("pandapower")

from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import margin_study as ms  # noqa: E402
from gridpulse import margins as mg  # noqa: E402
from gridpulse import sensing as sn  # noqa: E402
from gridpulse.__main__ import main  # noqa: E402
from gridpulse.grid_study import CAP_LEVELS, STEPS  # noqa: E402

LEVELS = len(CAP_LEVELS)
LAYOUT = sn.Layout(
    buses=(1, 2, 3), max_vm=(1.1, 1.1, 1.1), customer_buses=(2, 3), lv_busbar=1,
    feeder_heads=(0,), feeder_of={2: 0, 3: 0}, distance={1: 0.0, 2: 0.1, 3: 0.2},
)  # fmt: skip
SUB = sn.Config("substation", transformer=True, heads=(0,))
METERS = sn.Config("m", transformer=True, heads=(0,), voltages=(3,))


def test_signed_margins_have_the_right_sign_units_and_boundaries():
    vm = np.array([1.05, 1.10, 1.12, 0.88, np.nan])
    m = mg.voltage_margin(vm, 0.9, 1.1)
    assert np.allclose(m[:4], [0.05, 0.0, -0.02, -0.02]) and np.isnan(m[4])  # p.u.
    assert np.allclose(mg.loading_margin([80.0, 100.0, 105.0]), [20.0, 0.0, -5.0])  # % points
    assert np.allclose(mg.violation_magnitude(m[:4]), [0.0, 0.0, 0.02, 0.02])
    assert np.isnan(mg.violation_magnitude(m)[4])
    assert mg.violation_runs([0, 1, 1, 0, 1, 1, 1]) == [2, 3] and mg.violation_runs([0, 0]) == []


def _nominal_state(vm=1.04, trafo_loading=60.0, head=50.0):
    state = {
        "vm": np.full((STEPS, LEVELS, 3), vm), "line": np.full((STEPS, LEVELS, 1), head),
        "trafo": np.zeros((STEPS, LEVELS, 4)),
    }  # fmt: skip
    state["trafo"][:, :, 2], state["trafo"][:, :, 3] = trafo_loading, vm
    return state


def _plan():
    """Nominal exceedances: overvoltage -0.04 p.u., undervoltage -0.1 p.u., line and
    transformer 50 % below their limits (normalised: -0.4, -1.0, -0.5, -0.5)."""
    raw = np.empty((1, STEPS, LEVELS, 4))
    raw[..., 0], raw[..., 1], raw[..., 2], raw[..., 3] = -0.04, -0.1, -50.0, -50.0
    return raw


def _corrector(config=SUB, model=None, **settings):
    plan = {d: _plan() for d in range(0, 60)}
    plan_states = {d: _nominal_state() for d in range(0, 60)}
    model = model or sn.MeasurementModel()
    return mg.ResidualCorrector(plan, plan_states, LAYOUT, config, model,
                                mg.CorrectorSettings(**settings))  # fmt: skip


def _readings(offset=0.0, ratio=1.0, meter_offset=None):
    r = {
        "busbar_vm": np.full((STEPS, 1), 1.04 + offset),
        "trafo_loading": np.full((STEPS, 1), 60.0 * ratio),
        "trafo_p": np.zeros((STEPS, 1)), "trafo_q": np.zeros((STEPS, 1)),
        "head_loading": np.full((STEPS, 1), 50.0 * ratio),
    }  # fmt: skip
    if meter_offset is not None:
        r["remote_vm"] = np.full((STEPS, 1), 1.04 + meter_offset)
        r["remote_available"] = np.array([True])
    return r


DAYLIGHT = np.zeros(STEPS, dtype=bool)
DAYLIGHT[30:70] = True


def test_corrector_recovers_offset_and_ratio_and_shifts_the_plan_only_afterwards():
    c = _corrector()
    before = c.replay(40)
    c.observe(40, _readings(offset=0.03, ratio=1.1), np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["v_hat"] == pytest.approx(0.03)
    assert c.estimate["rho_trafo"] == pytest.approx(0.1) and c.estimate[
        "rho_line"
    ] == pytest.approx(0.1)
    after = c.replay(41)
    # overvoltage -0.04 + 0.03 = -0.01 p.u. -> -0.1; loading 50 % x 1.1 = 55 % -> -0.45
    assert np.allclose(before, -0.4) and np.allclose(after, -0.1)
    corrected = c.corrected(_plan()[0])
    assert np.allclose(corrected[..., 1], -0.13) and np.allclose(corrected[..., 2:], -45.0)
    assert np.array_equal(c.replay(40), after)  # replay(d) uses what is known now, by design


def test_meter_residuals_respect_the_reporting_delay_and_the_bias_check():
    model = sn.MeasurementModel(remote_delay_days=1)
    checked = _corrector(METERS, model, meters="checked")
    naive = _corrector(METERS, model, meters="naive")
    for c in (checked, naive):
        c.observe(40, _readings(meter_offset=0.02), np.zeros(STEPS, int), DAYLIGHT)
        assert c.estimate["v_hat"] == 0.0  # day 40's meter data not delivered yet
        c.observe(41, _readings(meter_offset=0.02), np.zeros(STEPS, int), DAYLIGHT)
    assert naive.estimate["v_hat"] == pytest.approx(0.02)  # a biased meter steers the plan
    assert checked.estimate["v_hat"] == 0.0 and checked.flags["meters_inconsistent"] == 1


def test_evidence_labels_follow_their_definitions():
    label = mg.evidence_label
    assert label({"no_feasible_action": True}) == "NO_VERIFIED_FEASIBLE_ACTION"
    assert label({"meters_inconsistent": 1, "physical_model_uncertainty": True}) == (
        "INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS"
    )
    assert label({"meters_inconsistent": 1}) == "MEASUREMENT_MODEL_INCONSISTENCY"
    assert label({"physical_model_uncertainty": True}) == "PHYSICAL_MODEL_UNCERTAINTY"
    assert label({}) == "EVIDENCE_SUFFICIENT_FOR_DEFINED_ANALYSIS"


def test_safety_margin_is_tuned_on_the_nominal_model_only():
    plan = {}
    for d in range(0, 60):
        raw = np.empty((1, STEPS, LEVELS, 4))  # far from every limit (normalised -1) ...
        raw[..., :2], raw[..., 2:] = -0.1, -100.0
        raw[0, :, 0, 0] = -0.003  # ... except uncapped: 0.003 p.u. below (normalised -0.03)
        if d >= 40:  # each development day violates (+0.002 p.u.) at a step not seen before
            raw[0, 30 + d - 40, 0, 0] = 0.002
        plan[d] = raw
    available = np.ones((60, STEPS, 1))
    days = list(range(40, 60))
    assert mg.tuned_safety_margin(plan, available, days, beta=0.1) == 0.04  # > 0.03 needed
    assert mg.tuned_safety_margin(plan, available, days, beta=1.0) == 0.0  # 20 <= 20 allowed


def test_first_safe_handles_a_non_monotonic_response():
    worst = np.zeros((STEPS, LEVELS))
    worst[:, :] = [0.3, -0.2, 0.1, -0.4] + [-0.5] * (LEVELS - 4)  # deeper is not always safer
    assert (ds.first_safe(worst, 0.0) == 1).all() and (ds.first_safe(worst, 0.3) == 3).all()


def test_corrected_policy_is_causal():
    from test_sensing import _context  # noqa: PLC0415

    def run(ctx):
        plan = {d: m[ds.REALISED : ds.REALISED + 1][..., None].repeat(4, -1) * 0 - 0.5
                for d, m in ctx.plan_norm.items()}  # fmt: skip
        nominal = {d: _nominal_state(vm=1.0, trafo_loading=50.0) for d in ctx.states}
        settings = mg.CorrectorSettings(meters="naive", window_days=1)
        model = sn.MeasurementModel(remote_delay_days=1)
        corr = mg.ResidualCorrector(plan, nominal, ctx.layout, METERS, model, settings)
        records = sn.run_feedback_policy(
            ctx, "replay_robust", METERS, sn.MeasurementModel(remote_delay_days=1), 0,
            ds.OnlineSettings(), noise=sn.NoiseBank("toy", "nominal"), corrector=corr,
        )  # fmt: skip
        return {r["day"]: r["v_hat"] for r in records}

    quiet, late = run(_context()), run(_context(remote_violation_day=46))
    assert all(quiet[d] == late[d] for d in range(42, 48))  # day 46 reaches day 48 only
    assert late[48] > quiet[48]


def test_primary_hypothesis_rule():
    def results(c1_violations, b3_violations, c1_mwh, b2_mwh):
        runs = {}
        for name, v, mwh in (("C1", c1_violations, c1_mwh), ("B3", b3_violations, 0.0),
                             ("B2", 0.0, b2_mwh)):  # fmt: skip
            runs[ms.run_key(name)] = {"avoidable_violation_steps": v, "curtailed_mwh": mwh}
        return runs

    def evaluate(**kw):
        runs = results(**kw)
        res = {"n": {t: {"runs": {k: dict(v) for k, v in runs.items()}}
                     for t in ("nominal", *ms.MISMATCH)}}  # fmt: skip
        k = ms.run_key
        h1 = {
            "a": ms.total(res, k("C1"), "avoidable_violation_steps", ms.MISMATCH)
            < ms.total(res, k("B3"), "avoidable_violation_steps", ms.MISMATCH),
            "b": ms.total(res, k("C1"), "curtailed_mwh")
            <= 1.1 * ms.total(res, k("B2"), "curtailed_mwh"),
        }
        return h1

    assert evaluate(c1_violations=10, b3_violations=11, c1_mwh=10.9, b2_mwh=10.0) == {
        "a": True,
        "b": True,
    }
    assert evaluate(c1_violations=11, b3_violations=11, c1_mwh=11.1, b2_mwh=10.0) == {
        "a": False,
        "b": False,
    }


def test_cli_refuses_a_margin_study_evaluation_without_freeze(tmp_path, capsys):
    code = main(["margin-study", "--stage", "evaluation", "--output-dir", str(tmp_path)])
    assert code == 1 and "no freeze.json" in capsys.readouterr().err


def test_full_metering_line_currents_feed_the_loading_ratio():
    full = sn.Config("full", transformer=True, voltages=(1, 2, 3), lines=(0,))
    c = _corrector(full)
    readings = _readings(ratio=1.2)
    readings["line_loading"] = readings.pop("head_loading")  # full metering reports lines
    c.observe(40, readings, np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["rho_line"] == pytest.approx(0.2)


def test_checked_meters_can_raise_but_never_lower_the_offset_and_estimates_are_clipped():
    c = _corrector(sn.Config("m2", transformer=True, heads=(0,), voltages=(2, 3)), meters="checked")
    readings = _readings(offset=0.03)
    readings["remote_vm"] = np.column_stack(
        [np.full(STEPS, 1.04 + 0.034), np.full(STEPS, 1.04 + 0.02)]
    )
    readings["remote_available"] = np.array([True, True])
    c.observe(40, readings, np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["v_hat"] == pytest.approx(0.034)  # consistent and higher: raises
    assert c.flags == {"meters_used": 1, "meters_inconsistent": 1}  # 0.02 is 0.01 below: excluded
    wild = _corrector()
    wild.observe(40, _readings(offset=0.2, ratio=2.0), np.zeros(STEPS, int), DAYLIGHT)
    assert wild.estimate == {"v_hat": 0.05, "rho_line": 0.3, "rho_trafo": 0.3}


def test_failed_flows_do_not_poison_the_estimates():
    c = _corrector()
    readings = _readings(offset=0.02, ratio=1.1)
    readings["busbar_vm"][35, 0] = np.nan
    readings["trafo_loading"][36, 0] = np.nan
    c.observe(40, readings, np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["v_hat"] == pytest.approx(0.02) and c.estimate["rho_trafo"] == pytest.approx(
        0.1
    )


def test_uncorrected_planner_reproduces_plain_replay_and_substation_path_is_causal():
    from test_sensing import _context  # noqa: PLC0415

    def plan_of(ctx):
        return {
            d: np.stack([m[ds.REALISED] * 0.1] * 2 + [m[ds.REALISED] * 100.0] * 2, axis=-1)[None]
            for d, m in ctx.plan_norm.items()
        }  # fmt: skip  (normalises back to plan_norm)

    ctx = _context(line_violation_day=44)
    plain = sn.run_feedback_policy(ctx, "replay_robust", SUB, sn.MeasurementModel(), 0,
                                   ds.OnlineSettings())  # fmt: skip
    nominal = {d: _nominal_state(vm=1.0, trafo_loading=50.0, head=50.0) for d in ctx.states}
    reference = mg.ResidualCorrector(plan_of(ctx), nominal, ctx.layout, SUB, sn.MeasurementModel(),
                                     mg.CorrectorSettings(correct=False))  # fmt: skip
    same = sn.run_feedback_policy(ctx, "replay_robust", SUB, sn.MeasurementModel(), 0,
                                  ds.OnlineSettings(), corrector=reference)  # fmt: skip
    keys = ("curtailed_mwh", "avoidable_violation_steps", "intervention_steps")
    assert [[r[k] for k in keys] for r in plain] == [[r[k] for k in keys] for r in same]

    def rho(ctx):
        corr = mg.ResidualCorrector(plan_of(ctx), nominal, ctx.layout, SUB, sn.MeasurementModel(),
                                    mg.CorrectorSettings(window_days=1))  # fmt: skip
        records = sn.run_feedback_policy(ctx, "replay_robust", SUB, sn.MeasurementModel(), 0,
                                         ds.OnlineSettings(), corrector=corr)  # fmt: skip
        return {r["day"]: r["rho_line"] for r in records}

    quiet = rho(_context())
    loaded = rho(_context(line_violation_day=44))  # the measured line is not a head here ...
    assert quiet == loaded  # ... so the substation never sees it: nothing changes

    def persistent(ctx):  # the head line carries 20 % more than the model from day 44 on
        for d, state in ctx.states.items():
            if d >= 44:
                state["line"][:, :, 0] = 60.0
        return ctx

    before, after = rho(_context()), rho(persistent(_context()))
    assert all(before[d] == after[d] for d in range(42, 45))  # day 44's reading acts from 45
    assert after[45] == pytest.approx(0.2) and before[45] == 0.0


def _hypothesis_results(c1=100.0, b3=200.0, c1_mwh=10.0, b2_mwh=10.0, rdev=1000.0,
                        naive=(12.0, 10.0, 10.0, 10.0, 10.0), flags=1.0):  # fmt: skip
    nets = ("1-LV-rural1--2-sw", "n1", "n2", "n3", "n4", "n5")
    out = {}
    for net in nets:
        out[net] = {}
        for t in ("nominal", *ms.MISMATCH):
            nominal = t == "nominal"
            runs = {}

            def put(key, violations, mwh, label_days=0.0, runs=runs, nominal=nominal):
                runs[key] = {
                    "avoidable_violation_steps": 0.0 if nominal else violations,
                    "curtailed_mwh": mwh if nominal else 0.0, "meets_beta": False, "days": 100,
                    "labels": {"PHYSICAL_MODEL_UNCERTAINTY": label_days},
                    "no_feasible_action_days": 0,
                }  # fmt: skip

            flag = 0.0 if nominal else (100.0 * flags if t != "pv_fixed_095" else 0.0)
            for r in range(5):
                put(ms.run_key("C1", r), c1, c1_mwh, flag)
                put(ms.run_key("B2", r), 0.0, b2_mwh)
                put(ms.run_key("C3b", r), 0.0, c1_mwh)
                put(ms.run_key("C3nb", r), 0.0, naive[r])
            put(ms.run_key("B3"), b3, 0.0)
            put(ms.run_key("C1x"), c1, c1_mwh)
            put(ms.run_key("Rdev"), rdev, 0.0)
            for name in ("B4", "B5", "B7", "C3", "C4"):
                put(ms.run_key(name), 0.0, 0.0)
            sensitivities = ["C1s0", "C1lag"] + [f"{n}bb{b:+.3f}" for n in ("C1", "C3")
                                                 for b in ms.BUSBAR_BIASES]  # fmt: skip
            for name in sensitivities:
                put(ms.run_key(name), c1, c1_mwh)
            out[net][t] = {"runs": runs}
    return out


def test_registered_hypothesis_rules_on_synthetic_results():
    h = ms.evaluate_hypotheses(_hypothesis_results())
    assert h["H1_primary"]["met"] and h["H2_noise_invariance"]["met"]
    assert h["H3_bias_check"]["met"] and h["H4_correction_is_active"]["met"]
    assert h["H5_model_uncertainty_label"]["met"]
    assert h["H1_primary"]["C1_mismatch_violations"] == 5 * 3 * 100  # rural1 excluded
    assert not ms.evaluate_hypotheses(_hypothesis_results(c1=200.0))["H1_primary"]["met"]
    assert not ms.evaluate_hypotheses(_hypothesis_results(c1_mwh=11.1))["H1_primary"]["met"]
    assert not ms.evaluate_hypotheses(_hypothesis_results(naive=(10.0,) * 5))["H3_bias_check"][
        "met"
    ]
    assert not ms.evaluate_hypotheses(_hypothesis_results(rdev=400.0))["H4_correction_is_active"][
        "met"
    ]
    assert not ms.evaluate_hypotheses(_hypothesis_results(flags=0.85))[
        "H5_model_uncertainty_label"
    ]["met"]


def test_busbar_bias_is_a_fixed_offset_and_the_lag_delays_the_residuals():
    from test_sensing import _state  # noqa: PLC0415

    model = sn.MeasurementModel(bias_v_substation=-0.005)
    readings = sn.measure(_state(), np.zeros(STEPS, int), SUB, LAYOUT, model, None,
                          noise=sn.NoiseBank("net", "nominal"), day=50)  # fmt: skip
    assert np.allclose(readings["busbar_vm"][:, 0], 1.0 - 0.005)  # every reading, every day
    lagged = _corrector(lag_days=1)
    lagged.observe(40, _readings(offset=0.03), np.zeros(STEPS, int), DAYLIGHT)
    assert lagged.estimate["v_hat"] == 0.0  # day 40's injections not yet available
    lagged.observe(41, _readings(offset=0.03), np.zeros(STEPS, int), DAYLIGHT)
    assert lagged.estimate["v_hat"] == pytest.approx(0.03)


class _Guarded(dict):
    """A day-keyed dict that fails on any read beyond `limit` (a future day)."""

    limit = -1

    def __getitem__(self, day):
        if day > self.limit:
            raise AssertionError(f"read day {day} while only days <= {self.limit} are known")
        return super().__getitem__(day)


def test_corrector_never_reads_a_future_plan_or_nominal_state():
    plan, nominal = _Guarded(), _Guarded()
    plan.update({d: _plan() for d in range(0, 60)})
    nominal.update({d: _nominal_state() for d in range(0, 60)})
    c = mg.ResidualCorrector(plan, nominal, LAYOUT, METERS, sn.MeasurementModel(),
                             mg.CorrectorSettings(meters="checked", lag_days=1))  # fmt: skip
    for day in range(30, 50):
        plan.limit, nominal.limit = day - 1, day - 1
        c.replay(day)  # planned before day `day`: replayed days strictly earlier
        nominal.limit = day  # day `day`'s metered injections, after the day
        c.observe(day, _readings(offset=0.01, meter_offset=0.01), np.zeros(STEPS, int), DAYLIGHT)


def test_lag_and_meter_delay_add_up():
    model = sn.MeasurementModel(remote_delay_days=1)
    c = _corrector(METERS, model, meters="naive", lag_days=1)
    for day in (40, 41):
        c.observe(day, _readings(meter_offset=0.02), np.zeros(STEPS, int), DAYLIGHT)
        assert c.estimate["v_hat"] == 0.0  # day 40's meter data: delay 1 + lag 1
    c.observe(42, _readings(meter_offset=0.02), np.zeros(STEPS, int), DAYLIGHT)
    assert c.estimate["v_hat"] == pytest.approx(0.02)


def test_label_precedence_and_the_legacy_path_refuses_busbar_bias():
    from test_sensing import _state  # noqa: PLC0415

    # no feasible action wins over every other condition (H5 counts only the model-error
    # label, so such a day would not count as flagged; none occurred in the evaluation)
    both = {"no_feasible_action": True, "meters_inconsistent": 1, "physical_model_uncertainty": 1}
    assert mg.evidence_label(both) == "NO_VERIFIED_FEASIBLE_ACTION"
    model = sn.MeasurementModel(bias_v_substation=-0.005)
    with pytest.raises(ValueError, match="NoiseBank"):
        sn.measure(_state(), np.zeros(STEPS, int), SUB, LAYOUT, model, np.random.default_rng(0))


_CACHES = Path("outputs/dual_study/physics_cache"), Path("outputs/sense_study/fullstate_cache")


@pytest.mark.skipif(not all(p.exists() for p in _CACHES), reason="needs the local physics caches")
def test_plan_loader_matches_the_planner_on_a_real_network():
    code = "1-LV-semiurb4--2-sw"
    contexts, layout, _ = sn.build_contexts(code, *_CACHES, "evaluation", truths=("nominal",))
    ctx = contexts["nominal"]
    raw = ms.plan_raw(code, _CACHES[0])
    for day in list(ctx.plan_norm)[:: max(1, len(ctx.plan_norm) // 5)]:
        assert np.allclose(ds.normalised(raw[day][ds.REALISED]), ctx.plan_norm[day][ds.REALISED])
    config = sn.Config("substation", transformer=True, heads=layout.feeder_heads)
    model, online = sn.MeasurementModel(), ds.OnlineSettings()
    plain = sn.run_feedback_policy(ctx, "replay_robust", config, model, 0, online)
    reference = mg.ResidualCorrector(raw, ctx.nominal_states, layout, config, model,
                                     mg.CorrectorSettings(correct=False))  # fmt: skip
    same = sn.run_feedback_policy(ctx, "replay_robust", config, model, 0, online,
                                  corrector=reference)  # fmt: skip
    keys = ("curtailed_mwh", "avoidable_violation_steps", "intervention_steps")
    assert [[r[k] for k in keys] for r in plain] == [[r[k] for k in keys] for r in same]
