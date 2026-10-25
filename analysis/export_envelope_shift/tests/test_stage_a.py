"""Tests for the Mission 11 Stage A runner (`stage_a.py`).

**Zero power flows.** An autouse fixture replaces `pandapower.runpp` with a function that
fails the test, so nothing here can spend a solve against the protocol's ceiling. pandapower
itself *is* imported, to build the synthetic feeder below; building a network runs no flow.

Every fixture is a genuinely synthetic radial LV feeder with round parameter values chosen
here (protocol s. 16). No SimBench or IEEE parameter value appears in this file:

* a 0.4 kV LV feeder: an MV bus, the transformer's LV busbar and 4 LV buses;
* a transformer with S_n = 0.4 MVA, vk = 5 %, vkr = 3 %, so that
  V_lv^2/S_n = 0.4 ohm, z = 0.02, r = 0.012 and x = sqrt(z^2 - r^2) = 0.016 ohm exactly;
* lines at 0.2 ohm/km and 0.1 ohm/km over 0.1 km, so r = 0.02 and x = 0.01 ohm, with one
  doubled circuit (`parallel` = 2) to exercise the divisor;
* `max_i_ka` = 0.2, so a single circuit's capacity is 0.2.sqrt(3).0.4 MVA;
* 4 loads and 2 sgens, at round MW values.
"""

from __future__ import annotations

import json
import math
import signal
import sys
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import envelope_core as ec  # noqa: E402
import envelope_lp as el  # noqa: E402
import stage_a  # noqa: E402

# --- the synthetic feeder (round values, chosen here) --------------------------------------

V_LV_KV = 0.4
TRAFO_SN_MVA = 0.4
VK_PERCENT = 5.0
VKR_PERCENT = 3.0
BASE_OHM = V_LV_KV**2 / TRAFO_SN_MVA  # 0.4 ohm
Z_TRAFO = VK_PERCENT / 100.0 * BASE_OHM  # 0.020 ohm
R_TRAFO = VKR_PERCENT / 100.0 * BASE_OHM  # 0.012 ohm
X_TRAFO = math.sqrt(Z_TRAFO**2 - R_TRAFO**2)  # 0.016 ohm, a 3-4-5 triangle

R_PER_KM = 0.2
X_PER_KM = 0.1
LENGTH_KM = 0.1
MAX_I_KA = 0.2
SINGLE_CAP_MVA = MAX_I_KA * math.sqrt(3.0) * V_LV_KV

LOAD_MW = (0.004, 0.006, 0.003, 0.005)
TAN_PHI = 0.25
SGEN_MW = (0.008, 0.010)


@pytest.fixture(autouse=True)
def no_power_flows(monkeypatch):
    """Protocol: this task's tests run zero AC power flows."""
    import pandapower as pp

    def refuse(*_args, **_kwargs):
        raise AssertionError("a test attempted an AC power flow; this task's tests run none")

    monkeypatch.setattr(pp, "runpp", refuse)


@pytest.fixture(autouse=True)
def restore_signal_handlers():
    """`stage_a.main` installs a SIGTERM handler; the test runner gets its own back."""
    saved = [(sig, signal.getsignal(sig)) for sig in (signal.SIGTERM, signal.SIGHUP)]
    yield
    for sig, handler in saved:
        signal.signal(sig, handler)


def synthetic_net():
    """A 6-bus radial LV feeder: MV bus, LV busbar, and 4 LV buses in a 2-branch tree.

    The topology, with branch numbers as `stage_a.build` assigns them (0 = transformer):

        busbar --1--> b1 --2--> b2
               --3--> b3 --4--> b4   (branch 3 is the doubled circuit)

    Breadth-first from the busbar visits the busbar's two lines first, then their children,
    so the line creation order below is deliberately *not* the breadth-first order.
    """
    import pandapower as pp

    net = pp.create_empty_network()
    mv = pp.create_bus(net, vn_kv=20.0, name="mv")
    busbar = pp.create_bus(net, vn_kv=V_LV_KV, name="busbar", max_vm_pu=1.10, min_vm_pu=0.90)
    b1 = pp.create_bus(net, vn_kv=V_LV_KV, name="b1", max_vm_pu=1.10, min_vm_pu=0.90)
    b2 = pp.create_bus(net, vn_kv=V_LV_KV, name="b2", max_vm_pu=1.10, min_vm_pu=0.90)
    b3 = pp.create_bus(net, vn_kv=V_LV_KV, name="b3", max_vm_pu=1.10, min_vm_pu=0.90)
    b4 = pp.create_bus(net, vn_kv=V_LV_KV, name="b4", max_vm_pu=1.10, min_vm_pu=0.90)
    pp.create_ext_grid(net, bus=mv, vm_pu=1.0)
    pp.create_transformer_from_parameters(
        net,
        hv_bus=mv,
        lv_bus=busbar,
        sn_mva=TRAFO_SN_MVA,
        vn_hv_kv=20.0,
        vn_lv_kv=V_LV_KV,
        vk_percent=VK_PERCENT,
        vkr_percent=VKR_PERCENT,
        pfe_kw=0.0,
        i0_percent=0.0,
    )

    def line(from_bus, to_bus, parallel=1):
        return pp.create_line_from_parameters(
            net,
            from_bus=from_bus,
            to_bus=to_bus,
            length_km=LENGTH_KM,
            r_ohm_per_km=R_PER_KM,
            x_ohm_per_km=X_PER_KM,
            c_nf_per_km=0.0,
            max_i_ka=MAX_I_KA,
            parallel=parallel,
        )

    line(b1, b2)  # created first, but breadth-first reaches it second
    line(busbar, b1)
    line(b3, b4)
    line(busbar, b3, parallel=2)

    for bus, p_mw in zip((b1, b2, b3, b4), LOAD_MW, strict=True):
        pp.create_load(net, bus=bus, p_mw=p_mw, q_mvar=TAN_PHI * p_mw)
    for bus, p_mw in zip((b2, b4), SGEN_MW, strict=True):
        pp.create_sgen(net, bus=bus, p_mw=p_mw, sn_mva=p_mw)
    return net, (busbar, b1, b2, b3, b4)


def built_synthetic():
    net, buses = synthetic_net()
    return stage_a.network_arrays(net, "toy", "toy-feeder", 4, 2), buses


# --- A. the tree builder, impedances, incidences and caps (zero flows) ---------------------


def test_network_arrays_finds_the_customer_buses_and_pv_units():
    built, (busbar, b1, b2, b3, b4) = built_synthetic()
    assert built.n_customers == 4
    assert built.n_units == 2
    np.testing.assert_array_equal(built.customer_buses, np.array([b1, b2, b3, b4]))
    assert busbar not in set(built.customer_buses.tolist())  # the busbar carries no load
    np.testing.assert_allclose(built.ratings, np.array(SGEN_MW), rtol=0, atol=0)
    assert built.v_lv_kv == V_LV_KV


def test_the_tree_is_breadth_first_from_the_transformer_lv_bus():
    """Branch 0 is the transformer; 1..L-1 are the lines in breadth-first order (not the
    order they were created in)."""
    built, (busbar, b1, b2, b3, b4) = built_synthetic()
    assert built.parent_branch.size == 5  # 1 transformer + 4 lines
    np.testing.assert_array_equal(built.parent_branch, np.array([-1, 0, 0, 1, 2]))

    # the customer-bus index downstream of each branch; the busbar is not a customer bus
    index_of = {bus: k for k, bus in enumerate(built.customer_buses.tolist())}
    np.testing.assert_array_equal(
        built.bus_of_branch_child,
        np.array([-1, index_of[b1], index_of[b3], index_of[b2], index_of[b4]]),
    )

    # b2's path to the source is the transformer, busbar->b1 and b1->b2
    np.testing.assert_array_equal(built.path[index_of[b2]], np.array([1.0, 1.0, 0.0, 1.0, 0.0]))
    np.testing.assert_array_equal(built.path[index_of[b4]], np.array([1.0, 0.0, 1.0, 0.0, 1.0]))
    np.testing.assert_array_equal(built.down, built.path.T)


def test_branch_impedances_rho_and_chi_are_the_protocol_formulas():
    built, _ = built_synthetic()
    r_line = R_PER_KM * LENGTH_KM  # 0.020 ohm on a single circuit
    x_line = X_PER_KM * LENGTH_KM  # 0.010 ohm
    # branch order: transformer, busbar->b1, busbar->b3 (parallel 2), b1->b2, b3->b4
    np.testing.assert_allclose(
        built.r_ohm,
        np.array([R_TRAFO, r_line, r_line / 2.0, r_line, r_line]),
        rtol=0,
        atol=1e-15,
    )
    np.testing.assert_allclose(
        built.x_ohm,
        np.array([X_TRAFO, x_line, x_line / 2.0, x_line, x_line]),
        rtol=0,
        atol=1e-15,
    )
    np.testing.assert_allclose(built.rho, built.r_ohm / V_LV_KV**2, rtol=0, atol=0)
    np.testing.assert_allclose(built.chi, built.x_ohm / V_LV_KV**2, rtol=0, atol=0)
    # the transformer's x closes the 3-4-5 triangle exactly
    assert built.x_ohm[0] == pytest.approx(0.016, abs=1e-15)


def test_thermal_caps_are_the_rating_and_the_line_currents():
    built, _ = built_synthetic()
    np.testing.assert_allclose(
        built.cap_mva,
        np.array(
            [
                TRAFO_SN_MVA,
                SINGLE_CAP_MVA,
                2.0 * SINGLE_CAP_MVA,  # the doubled circuit carries twice the current
                SINGLE_CAP_MVA,
                SINGLE_CAP_MVA,
            ]
        ),
        rtol=0,
        atol=1e-15,
    )


def test_the_incidences_carry_the_sign_convention_of_the_protocol():
    """P_bus = U.pv - W.l and Q_bus = -W.q, both export-positive at the bus (s. 4)."""
    built, (_, b1, b2, b3, b4) = built_synthetic()
    index_of = {bus: k for k, bus in enumerate(built.customer_buses.tolist())}
    assert built.U.shape == (4, 2)
    assert built.W.shape == (4, 4)
    np.testing.assert_array_equal(built.U.sum(axis=0), np.ones(2))  # one bus per PV unit
    np.testing.assert_array_equal(built.W.sum(axis=0), np.ones(4))  # one bus per load
    assert built.U[index_of[b2], 0] == 1.0  # the first sgen sits on b2
    assert built.U[index_of[b4], 1] == 1.0

    pv = np.array(SGEN_MW)
    ell = np.array(LOAD_MW)
    P_bus = built.U @ pv - built.W @ ell
    assert P_bus[index_of[b1]] == pytest.approx(-LOAD_MW[0])  # a load-only bus imports
    assert P_bus[index_of[b2]] == pytest.approx(SGEN_MW[0] - LOAD_MW[1])


def test_structured_predict_reproduces_lindistflow_on_the_synthetic_tree():
    """The runner's own zero-flow check of the tree (s. 7's structured model)."""
    built, _ = built_synthetic()
    assert stage_a.check_linear_structure(built) <= 1e-12

    S_P, S_Q = ec.lindistflow(built.path, built.rho, built.chi)
    assert np.all(S_P >= 0.0)  # a radial feeder's corner sensitivities are non-negative
    # a bus's own sensitivity is the sum of rho along its path
    index = 0
    assert S_P[index, index] == pytest.approx(float(built.path[index] @ built.rho))
    np.testing.assert_allclose(S_Q, S_Q.T, rtol=0, atol=1e-18)


def test_network_arrays_refuses_a_wrong_customer_count():
    net, _ = synthetic_net()
    with pytest.raises(ValueError, match="customer buses, expected 99"):
        stage_a.network_arrays(net, "toy", "toy-feeder", 99, 2)


def test_network_arrays_refuses_a_pv_unit_on_a_bus_with_no_load():
    """s. 3: every PV unit sits on a bus that carries a load."""
    import pandapower as pp

    net, (busbar, *_) = synthetic_net()
    pp.create_sgen(net, bus=busbar, p_mw=0.001, sn_mva=0.001)
    with pytest.raises(ValueError, match="carries no load"):
        stage_a.network_arrays(net, "toy", "toy-feeder", 4, 3)


def test_network_arrays_refuses_a_second_transformer():
    import pandapower as pp

    net, (busbar, b1, *_) = synthetic_net()
    pp.create_transformer_from_parameters(
        net,
        hv_bus=net.bus.index[0],
        lv_bus=b1,
        sn_mva=TRAFO_SN_MVA,
        vn_hv_kv=20.0,
        vn_lv_kv=V_LV_KV,
        vk_percent=VK_PERCENT,
        vkr_percent=VKR_PERCENT,
        pfe_kw=0.0,
        i0_percent=0.0,
    )
    with pytest.raises(ValueError, match="transformers; the tree assumes one"):
        stage_a.network_arrays(net, "toy", "toy-feeder", 4, 2)


def test_network_arrays_refuses_a_loop():
    """The tree builder is only valid on a radial feeder."""
    import pandapower as pp

    net, (_, b1, b2, b3, b4) = synthetic_net()
    pp.create_line_from_parameters(
        net,
        from_bus=b2,
        to_bus=b4,
        length_km=LENGTH_KM,
        r_ohm_per_km=R_PER_KM,
        x_ohm_per_km=X_PER_KM,
        c_nf_per_km=0.0,
        max_i_ka=MAX_I_KA,
    )
    with pytest.raises(ValueError, match="closes a loop"):
        stage_a.network_arrays(net, "toy", "toy-feeder", 4, 2)


# --- B. the ledger reconstruction (zero flows) ---------------------------------------------


def write_record(directory: Path, name: str, solves: int, stage: str = "physics") -> Path:
    return ec.write_json_once(directory / name, {"stage": stage, "solves": solves})


def test_ledger_total_starts_at_the_board_audit_count(tmp_path):
    """s. 12: the ledger starts at the 106 solves of the board design audits."""
    assert stage_a.LEDGER_START == 106
    assert stage_a.ledger_total(tmp_path) == 106


def test_ledger_total_sums_every_artefact_including_an_abort_record(tmp_path):
    write_record(tmp_path, "physics_toy_P1.json", 480)
    write_record(tmp_path, "physics_toy_P2.json", 480)
    write_record(tmp_path, "marginals_toy.json", 0, stage="physics_marginals")
    write_record(tmp_path, "abort_physics_toy_37.json", 37, stage="abort_physics")
    assert stage_a.ledger_total(tmp_path) == 106 + 480 + 480 + 0 + 37


def test_ledger_total_ignores_a_json_without_a_solve_count(tmp_path):
    ec.write_json_once(tmp_path / "notes.json", {"stage": "notes"})
    assert stage_a.ledger_total(tmp_path) == 106


def test_assert_budget_refuses_a_stage_that_would_break_the_ceiling(tmp_path):
    write_record(tmp_path, "huge.json", 7800)
    assert stage_a.ledger_total(tmp_path) == 7906
    assert stage_a.assert_budget(94, tmp_path) == 8000  # exactly the ceiling is allowed
    with pytest.raises(RuntimeError, match="solve ceiling 8000 would be exceeded"):
        stage_a.assert_budget(95, tmp_path)


def test_an_abort_record_carries_only_the_solves_no_artefact_has_counted(tmp_path, monkeypatch):
    """A stage that raises after solving must leave the ledger exact, not double-counted."""
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    counter = stage_a.SolveCounter()
    counter.attempts = 480  # the first regime solved and wrote its artefact
    write_record(tmp_path, "physics_toy_P1.json", counter.bank())
    counter.attempts += 37  # the second regime raised part-way through
    counter.failures = 1

    path = stage_a.abort_record("physics", "toy", counter, ValueError("boom"))
    assert path is not None and path.name == "abort_physics_toy_37.json"
    payload = json.loads(path.read_text())
    assert payload["solves"] == 37
    assert payload["failures"] == 1
    assert payload["status"] == "ABORTED"
    assert "ValueError: boom" in payload["error"]
    assert stage_a.ledger_total(tmp_path) == 106 + 480 + 37


def test_an_abort_record_keeps_the_partial_measurements(tmp_path, monkeypatch):
    """An abort costs the ledger its solves; it must not also discard their results."""
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    counter = stage_a.SolveCounter()
    counter.attempts = 2
    partial = {"candidates": [{"day": 160, "step": 15400}], "skipped_far_days": [163]}
    path = stage_a.abort_record("select", "toy", counter, ValueError("boom"), partial)
    payload = json.loads(path.read_text())
    assert payload["partial"]["candidates"] == [{"day": 160, "step": 15400}]
    assert payload["partial"]["skipped_far_days"] == [163]
    assert payload["solves"] == 2


def test_an_abort_record_is_not_written_when_nothing_was_solved(tmp_path, monkeypatch):
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    counter = stage_a.SolveCounter()
    assert stage_a.abort_record("select", "toy", counter, ValueError("boom")) is None
    assert list(tmp_path.glob("*.json")) == []


def test_the_solve_counter_banks_each_artefacts_share_exactly():
    counter = stage_a.SolveCounter()
    counter.attempts = 10
    assert counter.pending == 10
    assert counter.bank() == 10
    assert counter.pending == 0
    assert counter.bank() == 0  # banking twice never counts a solve twice
    counter.attempts += 4
    assert counter.bank() == 4


# --- C. write-once refusal and the protocol-hash refusal -----------------------------------


def test_a_stage_rerun_is_refused_rather_than_overwriting_a_counted_result(tmp_path, monkeypatch):
    """Rerunning a stage would silently discard counted solves, so the write refuses."""
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    write_record(tmp_path, "physics_toy_P1.json", 480)
    with pytest.raises(FileExistsError, match="written once and never rewritten"):
        write_record(tmp_path, "physics_toy_P1.json", 480)
    with pytest.raises(FileExistsError, match="written once and never rewritten"):
        ec.write_npz_once(tmp_path / "physics_toy_P1.json", x=np.zeros(1))

    # the first record is intact, so the ledger is unchanged by the refused rerun
    assert json.loads((tmp_path / "physics_toy_P1.json").read_text())["solves"] == 480
    assert stage_a.ledger_total(tmp_path) == 586


def test_an_abort_record_for_the_same_count_is_refused_too(tmp_path, monkeypatch):
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    counter = stage_a.SolveCounter()
    counter.attempts = 5
    stage_a.abort_record("select", "toy", counter, ValueError("boom"))
    counter.attempts = 10  # a rerun that aborted after the same 5 pending solves
    counter.banked = 5
    with pytest.raises(FileExistsError):
        stage_a.abort_record("select", "toy", counter, ValueError("boom"))


def test_check_protocol_refuses_a_changed_protocol(tmp_path):
    """The hash guard is `ec.check_protocol`; a changed protocol stops the study."""
    other = tmp_path / "stage_a_protocol.md"
    other.write_text("not the registered protocol\n")
    with pytest.raises(ValueError, match="protocol sha256"):
        ec.check_protocol(other)
    assert ec.check_protocol() == ec.PROTOCOL_SHA256
    assert ec.PROTOCOL_SHA256 == (
        "610d144dc3dbcb9835387f31ff5cdbd3a87d35d61db4dec832d10d8618b1f7fd"
    )
    assert ec.PROTOCOL_SHA256_EXECUTED == (
        "1848a27963fc67e134eb6dbe97bd96f1bc29e0e7ce4a8d76a68dc8134aa122b4"
    )


@pytest.mark.parametrize(
    "cmd",
    ["build", "ledger", "physics", "select", "envelopes", "oracle", "controls", "ambiguity",
     "monotonicity"],
)  # fmt: skip
def test_every_command_checks_the_protocol_hash_before_anything_else(cmd, monkeypatch):
    """A failed hash check stops the command before it builds a network or solves."""
    calls = []

    def refuse(*_args, **_kwargs):
        raise ValueError("protocol sha256 mismatch")

    def must_not_run(*_args, **_kwargs):
        calls.append("built")
        raise AssertionError("the command ran past the protocol check")

    monkeypatch.setattr(stage_a.ec, "check_protocol", refuse)
    monkeypatch.setattr(stage_a, "build", must_not_run)
    monkeypatch.setattr(stage_a, "cmd_ledger", must_not_run)
    with pytest.raises(ValueError, match="protocol sha256 mismatch"):
        stage_a.main([cmd, "--network", "semiurb5"])
    assert calls == []


# --- D. the selection rules as pure functions (protocol s. 5) ------------------------------


def test_near_candidate_takes_the_argmax_and_the_earliest_step_on_ties():
    assert stage_a.near_candidate(np.array([0.0, 0.3, 0.9, 0.2])) == 2
    # a tie at the maximum resolves to the earliest step
    assert stage_a.near_candidate(np.array([0.1, 0.8, 0.5, 0.8, 0.8])) == 1
    assert stage_a.near_candidate(np.array([0.5, 0.5, 0.5])) == 0


def test_far_candidate_is_the_first_step_reaching_the_threshold():
    f = np.array([0.0, 0.05, 0.19, 0.20, 0.35, 0.21])
    assert stage_a.far_candidate(f) == 3  # exactly 0.20 qualifies (f >= 0.2)
    assert stage_a.far_candidate(np.array([0.0, 0.1, 0.199])) is None
    assert stage_a.far_candidate(np.array([0.9, 0.2])) == 0
    assert stage_a.FAR_F == 0.20


def test_near_screen_keeps_only_exceedances_above_the_threshold():
    exceedance = np.array([0.0020, 0.0010, 0.0011, -0.0050, 0.0009, np.nan])
    np.testing.assert_array_equal(
        stage_a.near_screen(exceedance),
        np.array([True, False, True, False, False, False]),
    )
    assert stage_a.NEAR_SCREEN_PU == 0.001  # exactly +0.001 pu does not pass ("> +0.001")


def test_near_set_orders_the_survivors_by_largest_exceedance_earliest_on_ties():
    exceedance = np.array([0.003, 0.009, 0.005, 0.009, 0.001])
    np.testing.assert_array_equal(stage_a.near_set(exceedance, size=3), np.array([1, 3, 2]))
    # fewer survivors than the set size returns what there is; the caller applies s. 15
    np.testing.assert_array_equal(stage_a.near_set(np.array([0.002, 0.004])), np.array([1, 0]))
    assert stage_a.near_set(np.array([])).size == 0


def test_too_few_near_survivors_cannot_fill_the_set():
    """s. 15: fewer than 10 survivors makes the near set NOT EVALUABLE on that network."""
    exceedance = np.array([0.002] * 9 + [0.0005] * 31)
    passed = stage_a.near_screen(exceedance)
    assert int(passed.sum()) == 9
    assert int(passed.sum()) < stage_a.SET_SIZE
    assert stage_a.near_set(exceedance[passed]).size == 9


def test_far_set_takes_the_most_negative_margin_under_the_eighty_percent_cap():
    margin = np.array([-0.05, -0.09, -0.02, -0.20, -0.07])
    loading = np.array([40.0, 95.0, 70.0, 80.0, 79.9])
    # index 1 is excluded by the cap; index 3 at exactly 80 % is eligible
    np.testing.assert_array_equal(stage_a.far_set(margin, loading, size=3), np.array([3, 4, 0]))
    assert stage_a.FAR_LOADING_CAP == 80.0


def test_far_set_excludes_a_failed_solve_and_ties_resolve_to_the_earliest():
    margin = np.array([-0.04, np.nan, -0.04, -0.01])
    loading = np.array([10.0, 10.0, 10.0, np.nan])
    np.testing.assert_array_equal(stage_a.far_set(margin, loading), np.array([0, 2]))


def test_an_overcast_day_yields_no_far_candidate_and_is_not_fatal():
    """s. 5 defines the far candidate as the first step with f >= 0.2 and asks for no
    fallback, so a day whose f(t) never reaches it simply contributes no candidate.

    On semiurb5, 5 of the 40 deployment days are like this, which still leaves 35 far
    candidates for a set of 10. An implementation that treated the missing step as fatal
    would abort the stage after spending its near solves.
    """
    overcast = np.concatenate([np.zeros(30), np.linspace(0.0, 0.10, 36), np.zeros(30)])
    assert stage_a.far_candidate(overcast) is None
    assert stage_a.near_candidate(overcast) == 65  # the day still has a near candidate

    # the far set only needs `size` eligible candidates, not one per day
    margin = np.linspace(-0.20, -0.01, 35)
    loading = np.full(35, 50.0)
    assert stage_a.far_set(margin, loading).size == stage_a.SET_SIZE


def test_the_far_set_is_short_when_too_few_candidates_pass_the_loading_cap():
    """A short far set is recorded, not silently padded, so the board can read it."""
    margin = np.linspace(-0.20, -0.01, 12)
    loading = np.full(12, 95.0)  # every candidate is above the 80 % cap
    loading[:4] = 60.0
    chosen = stage_a.far_set(margin, loading)
    assert chosen.size == 4
    assert chosen.size < stage_a.SET_SIZE
    np.testing.assert_array_equal(chosen, np.array([0, 1, 2, 3]))


# --- E. the stage plans and step indexing (zero flows) -------------------------------------


def test_the_step_index_is_day_times_ninety_six_plus_step():
    steps = stage_a.steps_of([152, 153])
    assert steps[0] == 152 * 96
    assert steps[-1] == 153 * 96 + 95
    assert steps.size == 192
    np.testing.assert_array_equal(np.diff(steps), np.ones(191, dtype=int))


def test_physics_steps_add_the_extension_for_rural3_p1_only():
    """s. 4: the sample-size extension is rural3, P1 only."""
    assert stage_a.physics_steps("semiurb5", "P1").size == 480
    assert stage_a.physics_steps("semiurb5", "P3").size == 480
    assert stage_a.physics_steps("rural3", "P1").size == 480 + 384
    assert stage_a.physics_steps("rural3", "P2").size == 480
    extension = set(stage_a.steps_of(stage_a.EXTENSION_DAYS).tolist())
    assert extension <= set(stage_a.physics_steps("rural3", "P1").tolist())
    assert not extension & set(stage_a.physics_steps("semiurb5", "P1").tolist())


def test_the_stage_plans_match_the_protocol_ledger_lines():
    """s. 12: 4 x 480 per network, plus rural3's 384; 40 + 40 + 20 for the selection."""
    assert stage_a.physics_planned("semiurb5") == 1920
    assert stage_a.physics_planned("rural3") == 1920 + 384
    assert stage_a.selection_planned() == 100
    assert len(stage_a.DEPLOY_DAYS) == 40


def test_the_splits_never_overlap():
    """s. 4: the deployment days never overlap training or test."""
    train = set(stage_a.TRAIN_DAYS)
    test = set(stage_a.TEST_DAYS)
    extension = set(stage_a.EXTENSION_DAYS)
    deploy = set(stage_a.DEPLOY_DAYS)
    assert not train & test
    assert not (train | test | extension) & deploy
    assert not extension & (train | test)


# --- E1. physics --resume and the termination handler (zero flows) -------------------------

TOY_PHYSICS_DAYS = 158  # enough whole days to index the test day (156) and its steps


def toy_profiles(built, n_days: int = TOY_PHYSICS_DAYS):
    """A synthetic full-year profile table for the toy feeder, with round parameters here."""
    rng = np.random.default_rng(90210)
    n_steps = n_days * 96
    g = rng.uniform(0.0, 1.2, size=(n_steps, built.n_units))
    loads = np.array(LOAD_MW) * rng.uniform(0.5, 1.5, size=(n_steps, len(LOAD_MW)))
    capped = np.minimum(1.0, g)
    return stage_a.Profiles(n_days=n_days, g=g, native_pv=built.ratings * capped, L=loads,
                            Lq=TAN_PHI * loads, f=capped.mean(axis=1))  # fmt: skip


def counted_solve(built, raise_at: int | None = None):
    """A stand-in for the AC solve: it counts the attempt and returns a safe, converged row.

    With `raise_at` the n-th attempt calls `stage_a.terminated`, which is exactly what a real
    SIGTERM would do once the handler is installed. No signal is sent to the test runner.
    """

    def fake(_net_state, _pv, _load_p, _load_q, counter):
        counter.attempts += 1
        if raise_at is not None and counter.attempts == raise_at:
            stage_a.terminated(int(signal.SIGTERM), None)
        return {
            "vm": np.full(built.n_customers, 1.01),
            "lv_exceedance": -0.05,
            "line_loading": 10.0,
            "trafo_loading": 20.0,
            "branch_loading": np.full(built.n_branches, 10.0),
            "converged": True,
        }

    return fake


def toy_physics(monkeypatch, tmp_path, raise_at: int | None = None):
    """Point `run_physics` at the toy feeder, one day of steps per regime and `tmp_path`."""
    built, _ = built_synthetic()
    monkeypatch.setattr(stage_a, "build", lambda _key: built)
    monkeypatch.setattr(stage_a, "profiles_of", toy_profiles)
    monkeypatch.setattr(stage_a, "physics_steps", lambda _key, _regime: stage_a.steps_of((152,)))
    monkeypatch.setattr(stage_a, "solve", counted_solve(built, raise_at))
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    return built


def drop_the_last_regime(tmp_path):
    """The AKK-65 state: P1-P3 written, L0 and the marginals not."""
    for name in ("physics_toy_L0.json", "physics_toy_L0.npz", "marginals_toy.json"):
        (tmp_path / name).unlink()


def test_resume_plans_only_the_regimes_whose_artefact_pair_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    assert stage_a.physics_pending("rural3", resume=False) == (
        stage_a.REGIME_ORDER,
        stage_a.physics_planned("rural3"),
    )
    assert stage_a.physics_pending("rural3", resume=True) == (stage_a.REGIME_ORDER, 1920 + 384)

    for regime in ("P1", "P2", "P3"):
        write_record(tmp_path, f"physics_rural3_{regime}.json", 480)
        np.savez_compressed(tmp_path / f"physics_rural3_{regime}.npz", x=np.zeros(1))
    assert stage_a.physics_pending("rural3", resume=True) == (("L0",), 480)

    # half a pair is not a resumable regime: the json alone still has to be solved
    (tmp_path / "physics_rural3_P2.npz").unlink()
    assert stage_a.physics_pending("rural3", resume=True) == (("P2", "L0"), 960)


def test_resume_verifies_the_stored_regimes_and_solves_the_missing_one(tmp_path, monkeypatch):
    """s. 12: a resumed regime costs zero solves, and the stage still writes the marginals."""
    toy_physics(monkeypatch, tmp_path)
    assert stage_a.run_physics("toy") == 0
    solved = {
        regime: json.loads((tmp_path / f"physics_toy_{regime}.json").read_text())["solves"]
        for regime in stage_a.REGIME_ORDER
    }
    assert solved == dict.fromkeys(stage_a.REGIME_ORDER, 96)
    stored_p1 = (tmp_path / "physics_toy_P1.npz").read_bytes()

    drop_the_last_regime(tmp_path)
    assert stage_a.physics_pending("toy", resume=True) == (("L0",), 96)

    assert stage_a.run_physics("toy", resume=True) == 0
    assert json.loads((tmp_path / "physics_toy_L0.json").read_text())["solves"] == 96
    assert json.loads((tmp_path / "marginals_toy.json").read_text())["stage_solves"] == 96
    # the verified regimes were neither re-solved nor rewritten
    assert (tmp_path / "physics_toy_P1.npz").read_bytes() == stored_p1
    assert not sorted(tmp_path.glob("abort_*.json"))


def test_resume_refuses_a_tampered_stored_array_before_any_solve(tmp_path, monkeypatch):
    toy_physics(monkeypatch, tmp_path)
    assert stage_a.run_physics("toy") == 0
    drop_the_last_regime(tmp_path)

    with np.load(tmp_path / "physics_toy_P2.npz") as stored:
        arrays = {name: stored[name] for name in stored.files}
    arrays["pv"] = arrays["pv"] + 1e-9  # one perturbed input entry is enough
    np.savez_compressed(tmp_path / "physics_toy_P2.npz", **arrays)

    def must_not_solve(*_args, **_kwargs):
        raise AssertionError("resume solved before it had verified every stored artefact")

    monkeypatch.setattr(stage_a, "solve", must_not_solve)
    with pytest.raises(ValueError, match="regenerated pv does not equal the stored"):
        stage_a.run_physics("toy", resume=True)
    assert not (tmp_path / "physics_toy_L0.json").exists()
    assert not sorted(tmp_path.glob("abort_*.json"))  # nothing was spent, nothing is charged


def test_without_resume_a_rerun_is_still_refused_rather_than_overwriting(tmp_path, monkeypatch):
    """The write-once rule is unchanged: only `--resume` may look at an existing artefact."""
    toy_physics(monkeypatch, tmp_path)
    assert stage_a.run_physics("toy") == 0
    stored_p1 = (tmp_path / "physics_toy_P1.npz").read_bytes()
    with pytest.raises(FileExistsError, match="written once and never rewritten"):
        stage_a.run_physics("toy")
    assert (tmp_path / "physics_toy_P1.npz").read_bytes() == stored_p1


def test_the_termination_handler_turns_a_signal_into_an_abort_record(tmp_path, monkeypatch):
    """AKK-65: a default SIGTERM bypassed `except BaseException` and lost 480 solves."""
    with pytest.raises(SystemExit, match="terminated by signal"):
        stage_a.terminated(int(signal.SIGTERM), None)

    toy_physics(monkeypatch, tmp_path, raise_at=7)
    with pytest.raises(SystemExit, match="terminated by signal"):
        stage_a.run_physics("toy")
    record = json.loads((tmp_path / "abort_physics_toy_7.json").read_text())
    assert record["solves"] == 7 and record["status"] == "ABORTED"
    assert "SystemExit" in record["error"]
    assert not (tmp_path / "physics_toy_P1.json").exists()  # the regime never completed


def test_install_termination_handler_registers_the_handler_for_sigterm():
    stage_a.install_termination_handler()
    assert signal.getsignal(signal.SIGTERM) is stage_a.terminated
    assert signal.getsignal(signal.SIGHUP) is stage_a.terminated


# --- F. the envelope and oracle stages (zero flows: the AC solve is a linear stand-in) -----

N_YEAR = 200 * 96  # enough absolute year steps to cover the training, test and deployment days
REGIME_SEED = {"P1": 1, "P2": 2, "P3": 3, "L0": 4}  # stable, unlike Python's salted `hash`


def linear_ac(built):
    """A linear stand-in for `stage_a.solve`: LinDistFlow on the true impedances.

    The envelope stages are driven entirely through `stage_a.solve`, so replacing it with a
    deterministic linear "AC" lets the whole runner be exercised at zero power flows. The
    counter is incremented exactly as the real solve does.
    """
    S_P, S_Q = ec.lindistflow(built.path, built.rho, built.chi)

    def fake_solve(net_state, pv, load_p, load_q, ledger_counter):
        ledger_counter.attempts += 1
        P_bus = net_state.U @ np.asarray(pv, float) - net_state.W @ np.asarray(load_p, float)
        Q_bus = -net_state.W @ np.asarray(load_q, float)
        vm = 1.0 + S_P @ P_bus + S_Q @ Q_bus
        return {
            "vm": vm,
            "lv_exceedance": float(np.max(vm - net_state.vmax)),
            "line_loading": 42.0,
            "trafo_loading": 43.0,
            "converged": True,
        }

    return fake_solve


def failing_solve(net_state, pv, load_p, load_q, ledger_counter):
    """What `stage_a.solve` returns when the flow does not converge (s. 12)."""
    ledger_counter.attempts += 1
    ledger_counter.failures += 1
    return {
        "vm": np.full(net_state.n_customers, np.nan),
        "lv_exceedance": math.nan,
        "line_loading": math.nan,
        "trafo_loading": math.nan,
        "converged": False,
    }


CONDITION_LOAD = (0.0010, 0.0015, 0.0008, 0.0012)


def synthetic_selection(built, rise_share=0.5):
    """Two conditions on the toy feeder: a near one that must be curtailed and a far one.

    The near condition's availability is the full rating, and `built.vmax` is set, per bus,
    to `rise_share` of that condition's no-action voltage rise above its e = 0 voltage. So
    e = 0 is strictly feasible at every bus (as s. 5's selection guarantees) while e = a is
    not, and every method's LP has to move. The far condition's availability is a tenth of
    the rating, which leaves e = a feasible and exercises s. 6's scoring shortcut.
    """
    S_P, S_Q = ec.lindistflow(built.path, built.rho, built.chi)
    ell = np.array([CONDITION_LOAD, CONDITION_LOAD])
    q = 0.25 * ell
    a = np.array([built.ratings, 0.1 * built.ratings])
    P_no_action = a @ built.U.T - ell @ built.W.T
    Q_bus = -(q @ built.W.T)
    vm_no_action = 1.0 + P_no_action @ S_P.T + Q_bus @ S_Q.T
    vm_zero = 1.0 + (-(ell @ built.W.T)) @ S_P.T + Q_bus @ S_Q.T
    built.vmax = vm_zero[0] + rise_share * (vm_no_action[0] - vm_zero[0])

    conditions = []
    for row, kind in enumerate(("near", "far")):
        exceedance = float(np.max(vm_no_action[row] - built.vmax))
        conditions.append(
            {
                "kind": kind,
                "day": 160 + row,
                "step": (160 + row) * 96 + 48,
                "f": 1.0,
                "customer_exceedance": exceedance,
                "lv_exceedance": exceedance,
                "line_loading": 70.0,
                "trafo_loading": 80.0,
                "converged": True,
            }
        )
    return stage_a.Selection(
        key="toy",
        near_evaluable=True,
        far_evaluable=True,
        conditions=conditions,
        a=a,
        ell=ell,
        q=q,
        P_bus_no_action=P_no_action,
        Q_bus=Q_bus,
        vm_no_action=vm_no_action,
    )


def synthetic_rows(built, regime="P1"):
    """One regime's `physics` arrays on the toy feeder: the training days plus the test day.

    The voltages are the true LinDistFlow model of the injections, so a well-identified fit
    must recover the true sensitivities and the test-day MAE must be small.
    """
    steps = np.concatenate(
        [stage_a.steps_of(stage_a.TRAIN_DAYS), stage_a.steps_of(stage_a.TEST_DAYS)]
    )
    rng = np.random.default_rng(REGIME_SEED[regime])
    n = steps.size
    pv = built.ratings * rng.uniform(0.0, 1.0, size=(n, built.n_units))
    loads = np.array(CONDITION_LOAD) * rng.uniform(0.5, 1.5, size=(n, built.W.shape[1]))
    P_bus = pv @ built.U.T - loads @ built.W.T
    Q_bus = -(0.25 * loads) @ built.W.T
    S_P, S_Q = ec.lindistflow(built.path, built.rho, built.chi)
    vm = 1.0 + P_bus @ S_P.T + Q_bus @ S_Q.T
    return {"steps": steps, "P_bus": P_bus, "Q_bus": Q_bus, "vm": vm,
            "converged": np.ones(n, dtype=bool)}  # fmt: skip


# --- F1. the noise rule (s. 17.3) ----------------------------------------------------------


def test_the_noise_is_drawn_over_the_year_and_indexed_by_absolute_step():
    """s. 17.3: z covers every step of the year, so a subset of steps gets the same values."""
    k_bus = 3
    steps = np.array([10, 11, 150, 199])
    both = stage_a.noisy_voltage("toy", "P1", 0, np.zeros((4, k_bus)), steps, 200)
    z = ec.rng_for("toy", "P1", "noise", 0).standard_normal((200, k_bus))
    np.testing.assert_allclose(both, stage_a.SIGMA_V * z[steps], rtol=0, atol=0)

    later = stage_a.noisy_voltage("toy", "P1", 0, np.zeros((2, k_bus)), steps[2:], 200)
    np.testing.assert_allclose(later, both[2:], rtol=0, atol=0)

    replicate_one = stage_a.noisy_voltage("toy", "P1", 1, np.zeros((4, k_bus)), steps, 200)
    assert not np.allclose(replicate_one, both)


def test_every_sigma_level_uses_the_same_z(monkeypatch):
    """s. 17.3: common random numbers across control I's sigma_v arms."""
    k_bus = 2
    steps = np.array([5, 6])
    vm = np.full((2, k_bus), 1.02)
    primary = stage_a.noisy_voltage("toy", "P2", 0, vm, steps, 50)
    monkeypatch.setattr(stage_a, "SIGMA_V", 0.005)
    upper = stage_a.noisy_voltage("toy", "P2", 0, vm, steps, 50)
    np.testing.assert_allclose((upper - vm) / 0.005, (primary - vm) / 0.002, rtol=1e-12, atol=0)


# --- F2. the scoring shortcut and the failed flow (s. 6, s. 12) ----------------------------


def test_an_envelope_equal_to_a_reuses_the_no_action_solve_and_costs_no_solve(monkeypatch):
    """s. 6: the shortcut reuses the selection solve and counts zero."""
    built, _ = built_synthetic()
    monkeypatch.setattr(stage_a, "solve", linear_ac(built))
    sel = synthetic_selection(built)
    counter = stage_a.SolveCounter()

    score = stage_a.score_corner(built, sel, 1, sel.a[1], counter)
    assert score["shortcut"] is True
    assert counter.attempts == 0
    assert score["max_exceedance"] == sel.conditions[1]["customer_exceedance"]
    assert score["line_loading"] == sel.conditions[1]["line_loading"]
    np.testing.assert_allclose(score["vm"], sel.vm_no_action[1], rtol=0, atol=0)

    inside = sel.a[1].copy()
    inside[0] -= 1e-13  # within the 1e-12 MW tolerance: still the shortcut
    assert stage_a.score_corner(built, sel, 1, inside, counter)["shortcut"] is True
    assert counter.attempts == 0

    outside = sel.a[1].copy()
    outside[0] -= 1e-9  # outside it: a new solve, and it is counted
    assert stage_a.score_corner(built, sel, 1, outside, counter)["shortcut"] is False
    assert counter.attempts == 1


def test_the_shortcut_is_unsafe_when_the_no_action_solve_exceeded_the_limit(monkeypatch):
    """The near condition's no-action corner is above vmax by construction."""
    built, _ = built_synthetic()
    monkeypatch.setattr(stage_a, "solve", linear_ac(built))
    sel = synthetic_selection(built)
    score = stage_a.score_corner(built, sel, 0, sel.a[0], stage_a.SolveCounter())
    assert score["shortcut"] is True
    assert score["max_exceedance"] > stage_a.VOLTAGE_UNSAFE_PU
    assert score["unsafe"] is True


def test_a_failed_flow_is_recorded_as_failed_and_counted_unsafe(monkeypatch):
    """s. 12: a non-converged corner is never scored as safe, in any rate."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    monkeypatch.setattr(stage_a, "solve", failing_solve)
    counter = stage_a.SolveCounter()
    score = stage_a.score_corner(built, sel, 0, 0.5 * sel.a[0], counter)
    assert counter.attempts == 1 and counter.failures == 1
    assert score["converged"] is False
    assert math.isnan(score["max_exceedance"])
    assert score["unsafe"] is True


def test_a_failed_no_action_solve_makes_the_shortcut_unsafe_too(monkeypatch):
    """The shortcut inherits the selection solve's failure, so it cannot read as safe."""
    built, _ = built_synthetic()
    monkeypatch.setattr(stage_a, "solve", linear_ac(built))
    sel = synthetic_selection(built)
    sel.conditions[1]["converged"] = False
    sel.conditions[1]["customer_exceedance"] = math.nan
    score = stage_a.score_corner(built, sel, 1, sel.a[1], stage_a.SolveCounter())
    assert score["shortcut"] is True
    assert score["converged"] is False
    assert score["unsafe"] is True


# --- F3. the per-condition method dispatch (s. 7) ------------------------------------------


def test_every_method_returns_an_envelope_inside_the_availability_box():
    """s. 7: the seven deployable methods and the three fixed arms, on a tiny true model."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    cell = stage_a.fit_cell(built, "P1", 0, synthetic_rows(built), N_YEAR)
    P_fix = -(sel.ell @ built.W.T)
    Q_fix = -(sel.q @ built.W.T)
    aprime = ec.training_intercept(cell.Y, built.path, built.rho, built.chi, cell.X, cell.Q_train)

    for row in range(sel.n_conditions):
        for method in stage_a.DATA_METHODS:
            out = stage_a.method_envelope(method, cell, built, sel.a[row], P_fix[row], Q_fix[row])
            e = np.asarray(out["e"], dtype=float)
            assert e.shape == (built.n_units,)
            assert np.all(e >= -1e-12) and np.all(e <= sel.a[row] + 1e-12), method
            assert math.isfinite(out["total"]) and math.isfinite(out["predicted_corner_vm"])
            assert out["status"] in (el.OK, el.INFEASIBLE, el.STAGE2_FAILED, el.ROBUST_DEGENERATE)
        for method in stage_a.FIXED_METHODS:
            out = stage_a.fixed_envelope(method, built, sel, row, P_fix[row], Q_fix[row], aprime)
            e = np.asarray(out["e"], dtype=float)
            assert np.all(e >= -1e-12) and np.all(e <= sel.a[row] + 1e-12), method
    with pytest.raises(ValueError, match="unknown method"):
        stage_a.method_envelope("B9", cell, built, sel.a[0], P_fix[0], Q_fix[0])
    with pytest.raises(ValueError, match="unknown fixed method"):
        stage_a.fixed_envelope("B9", built, sel, 0, P_fix[0], Q_fix[0], aprime)


def test_b0_is_the_seventy_percent_rule_and_uses_no_voltage_model():
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    out = stage_a.fixed_envelope(
        "B0", built, sel, 0, -(sel.ell[0] @ built.W.T), -(sel.q[0] @ built.W.T), np.zeros(4)
    )
    np.testing.assert_allclose(out["e"], np.minimum(sel.a[0], 0.7 * built.ratings))
    assert math.isnan(out["predicted_corner_vm"])


def test_method_a_reproduces_the_no_action_state_at_e_equals_a():
    """s. 7: Method A's offset is the *whole* intercept, so its model is exact at e = a."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    offset = ec.offset_from_state(
        sel.vm_no_action[0], 0.0, built.path, built.rho, built.chi,
        sel.P_bus_no_action[0], sel.Q_bus[0],
    )  # fmt: skip
    alpha, S = el.affine_from_structured(
        offset, built.path, built.rho, built.chi, built.U,
        -(sel.ell[0] @ built.W.T), -(sel.q[0] @ built.W.T),
    )  # fmt: skip
    np.testing.assert_allclose(alpha + S @ sel.a[0], sel.vm_no_action[0], rtol=0, atol=1e-14)


def test_the_envelope_stage_runs_every_cell_and_labels_a_non_evaluable_network(
    tmp_path, monkeypatch
):
    """The whole stage on the toy feeder: 52 records per condition, and s. 15's label."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    sel.near_evaluable = False
    rows = {regime: synthetic_rows(built, regime) for regime in stage_a.REGIME_ORDER}
    monkeypatch.setattr(stage_a, "build", lambda key: built)
    monkeypatch.setattr(stage_a, "load_selection", lambda key: sel)
    monkeypatch.setattr(stage_a, "load_physics", lambda key: rows)
    monkeypatch.setattr(stage_a, "profiles_of", lambda b: _toy_profiles())
    monkeypatch.setattr(stage_a, "solve", linear_ac(built))
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)

    assert stage_a.run_envelopes("toy") == 0
    payload = json.loads((tmp_path / "envelopes_toy.json").read_text())
    assert len(payload["records"]) == stage_a.envelopes_planned(sel.n_conditions)
    assert payload["solves"] + payload["shortcut_records"] == len(payload["records"])
    assert all(r["label"] == stage_a.DESCRIPTIVE_LABEL for r in payload["records"])
    assert {r["method"] for r in payload["records"]} == set(
        stage_a.DATA_METHODS + stage_a.FIXED_METHODS
    )
    assert len(payload["fits"]) == len(stage_a.ENVELOPE_CELLS)
    with np.load(tmp_path / "envelopes_toy.npz", allow_pickle=False) as stored:
        assert stored["e"].shape == (len(payload["records"]), built.n_units)
        assert stored["vm_corner"].shape == (len(payload["records"]), built.n_customers)
        assert stored["vm_corner"].dtype == np.float32
        assert [str(m) for m in stored["method"]] == [r["method"] for r in payload["records"]]


def _toy_profiles():
    """Only `n_steps` is read by the envelope stage; the rest is never touched."""
    zeros = np.zeros((N_YEAR, 1))
    return stage_a.Profiles(
        n_days=N_YEAR // 96, g=zeros, native_pv=zeros, L=zeros, Lq=zeros, f=np.zeros(N_YEAR)
    )


# --- F4. the oracle driver (s. 7, B5) ------------------------------------------------------


def test_the_oracle_driver_terminates_inside_its_fourteen_solve_budget(tmp_path, monkeypatch):
    """s. 7: at most 6 sequential LPs plus 8 bisections, per near condition."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    monkeypatch.setattr(stage_a, "build", lambda key: built)
    monkeypatch.setattr(stage_a, "load_selection", lambda key: sel)
    monkeypatch.setattr(stage_a, "solve", linear_ac(built))
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)

    assert stage_a.run_oracle("toy") == 0
    payload = json.loads((tmp_path / "oracle_toy.json").read_text())
    assert payload["n_near"] == 1  # the far condition is not visited: its envelope is a
    assert payload["planned_max"] == 14
    assert payload["solves"] <= payload["planned_max"]
    for record in payload["records"]:
        assert record["solves"] <= 14
        assert record["lp_steps"] <= 6 and record["bisect_steps"] <= 8
        assert record["status"] in ("ok", "budget", "infeasible")
        assert len(record["history"]) == record["solves"]
    # the true-model oracle must find a safe envelope and it must bind a voltage row.
    best = payload["records"][0]
    assert best["status"] == "ok" and best["total_e"] > 0.0
    assert best["voltage_row_active"] is True
    with np.load(tmp_path / "oracle_toy.npz", allow_pickle=False) as stored:
        assert stored["best_e"].shape == (1, built.n_units)
        assert stored["history_e"].shape[0] == payload["solves"]


def test_the_oracle_never_relinearises_on_a_failed_flow(tmp_path, monkeypatch):
    """s. 12: a failed flow is infeasible, so the run falls back and never reports safety."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    monkeypatch.setattr(stage_a, "build", lambda key: built)
    monkeypatch.setattr(stage_a, "load_selection", lambda key: sel)
    monkeypatch.setattr(stage_a, "solve", failing_solve)
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)

    assert stage_a.run_oracle("toy") == 1  # every solve failed: NOT EVALUABLE (s. 12)
    payload = json.loads((tmp_path / "oracle_toy.json").read_text())
    record = payload["records"][0]
    assert record["solves"] == 14
    assert record["status"] == "infeasible" and record["total_e"] == 0.0
    assert all(entry["feasible"] is False for entry in record["history"])


def test_the_stage_plans_of_the_two_new_stages_match_the_protocol_ledger_lines():
    """s. 12: 52 per condition, and the oracle's 14 per near condition."""
    assert stage_a.envelopes_planned(20) == 1040
    assert stage_a.envelopes_planned(12) == 624
    assert stage_a.oracle_planned(10) == 140
    assert stage_a.oracle_planned(2) == 28


def test_load_selection_and_load_physics_refuse_a_missing_artefact(tmp_path, monkeypatch):
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    with pytest.raises(FileNotFoundError, match="run `select"):
        stage_a.load_selection("semiurb5")
    with pytest.raises(FileNotFoundError, match="run `physics"):
        stage_a.load_physics("semiurb5")


def test_the_summary_command_reads_the_artefacts_it_finds(tmp_path, monkeypatch, capsys):
    """`summary` is a zero-solve read-out; with no artefacts it says so rather than failing."""
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    assert stage_a.cmd_summary("semiurb5") == 0
    printed = capsys.readouterr().out
    assert "no selection_semiurb5.json" in printed
    assert "no envelopes_semiurb5.json" in printed
    assert "no oracle_semiurb5.json" in printed
    assert "no controls_semiurb5.json" in printed
    assert "no ambiguity_semiurb5.json" in printed
    assert "no monotonicity_semiurb5.json" in printed


# --- G. the read-out fix of task 2c (s. 9 H2) ----------------------------------------------


def test_the_predicted_corner_voltage_is_each_methods_own_nominal_model():
    """s. 9 H2: `predicted_corner_vm` is the method's **own** nominal model at its own corner.

    B1 reads out OLS, B2m its 152-154 ridge *without* the margin, B3 the structured fit, and
    B2, B2p, B4box and B4 all read out B2's ridge. The defect this replaces used B2's model
    for every method, so at least one of B1, B2m and B3 must now disagree with it.
    """
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    cell = stage_a.fit_cell(built, "P1", 0, synthetic_rows(built), N_YEAR)
    P_fix = -(sel.ell[0] @ built.W.T)
    Q_fix = -(sel.q[0] @ built.W.T)

    own = {
        "B1": el.affine_from_centred(cell.b1.ybar, cell.b1.slopes, cell.b1.mu, built.U, P_fix),
        "B2m": el.affine_from_centred(cell.b2m.ybar, cell.b2m.slopes, cell.b2m.mu, built.U, P_fix),
        "B3": el.affine_from_structured(
            cell.b3[0], built.path, cell.b3[1], cell.b3[2], built.U, P_fix, Q_fix
        ),
    }
    b2_model = el.affine_from_centred(cell.b2.ybar, cell.b2.slopes, cell.b2.mu, built.U, P_fix)
    gaps = []
    for method in stage_a.DATA_METHODS:
        out = stage_a.method_envelope(method, cell, built, sel.a[0], P_fix, Q_fix)
        alpha, S = own.get(method, b2_model)
        expected = float(np.max(alpha + S @ np.asarray(out["e"], dtype=float)))
        assert out["predicted_corner_vm"] == pytest.approx(expected, rel=0.0, abs=1e-14), method
        if method in own:
            b2_value = float(np.max(b2_model[0] + b2_model[1] @ np.asarray(out["e"], float)))
            gaps.append(abs(out["predicted_corner_vm"] - b2_value))
    assert max(gaps) > 0.0, "every read-out still equals B2's: the defect is not fixed"


def test_the_sigma_argument_reuses_the_regimes_own_z(monkeypatch):
    """s. 17.3: control I's levels are common random numbers against the primary SIGMA_V."""
    vm = np.full((2, 3), 1.01)
    steps = np.array([7, 8])
    primary = stage_a.noisy_voltage("toy", "P1", 0, vm, steps, 50)
    explicit = stage_a.noisy_voltage("toy", "P1", 0, vm, steps, 50, sigma=0.0005)
    np.testing.assert_allclose(
        (explicit - vm) / 0.0005, (primary - vm) / stage_a.SIGMA_V, rtol=1e-9, atol=0
    )


# --- H. the controls stage (s. 6, s. 7, s. 10) ---------------------------------------------


def test_the_stage_plans_of_the_control_stages_match_the_protocol_ledger_lines():
    """The brief's arithmetic: 76 on semiurb5 (12 conditions, 2 near), 200 on rural3 (20, 10)."""
    assert stage_a.controls_planned("semiurb5", 12, 2) == 76
    assert stage_a.controls_planned("rural3", 20, 10) == 200
    # the T = 768 arm is rural3's alone, so the same counts without it are 20 lower.
    assert stage_a.controls_planned("semiurb5", 20, 10) == 180
    assert stage_a.ambiguity_planned(2) == 32
    assert stage_a.ambiguity_planned(10) == 160
    assert stage_a.monotonicity_planned(12) == 12
    assert stage_a.monotonicity_planned(20) == 20


def test_control_h_refits_on_its_own_window_and_refuses_one_the_physics_lacks():
    """s. 17.4: T = 192 is days 152-153 with one fold per day; T = 768 needs the extension."""
    built, _ = built_synthetic()
    rows = synthetic_rows(built)
    _, info = stage_a.control_h_ridge(built, rows, "P1", 0, stage_a.CONTROL_H_SHORT_DAYS, N_YEAR)
    assert info["train_steps"] == 192
    assert info["cv_folds"] == 2
    with pytest.raises(FileNotFoundError, match="control H"):
        stage_a.control_h_ridge(built, rows, "P1", 0, stage_a.CONTROL_H_LONG_DAYS, N_YEAR)


def test_control_t_wires_the_thermal_module_into_the_lp_rows():
    """s. 6: `thermal_rows` bounds down_l.(U.e + P_fix) by kappa.cap_l in both directions."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    n_branches = built.n_branches
    P_fix = -(sel.ell[0] @ built.W.T)
    A_x, b_x = el.thermal_rows(built.down, built.U, P_fix, built.cap_mva, kappa=el.KAPPA_T)
    assert A_x.shape == (2 * n_branches, built.n_units)
    np.testing.assert_allclose(A_x[n_branches:], -A_x[:n_branches], rtol=0, atol=0)

    e = 0.5 * sel.a[0]
    flow = built.down @ (built.U @ e - built.W @ sel.ell[0])
    base = built.down @ P_fix
    np.testing.assert_allclose(A_x[:n_branches] @ e + base, flow, rtol=0, atol=1e-15)
    limit = el.KAPPA_T * built.cap_mva
    np.testing.assert_allclose(b_x[:n_branches], limit - base, rtol=0, atol=1e-15)
    np.testing.assert_allclose(b_x[n_branches:], limit + base, rtol=0, atol=1e-15)

    # the module's loading fraction, and which branch and direction an active row names.
    np.testing.assert_allclose(
        stage_a.thermal_module_loading(built, e, sel.ell[0]),
        np.abs(flow) / built.cap_mva,
        rtol=0,
        atol=0,
    )
    for i in range(2 * n_branches):
        label = stage_a._extra_row_label(i, n_branches)
        assert label["branch"] == i % n_branches
        assert label["direction"] == ("export" if i < n_branches else "import")

    # the LP must respect the rows it was given.
    alpha, S = el.affine_from_structured(
        1.0, built.path, built.rho, built.chi, built.U, P_fix, -(sel.q[0] @ built.W.T)
    )
    out = el.voltage_envelope(alpha, S, built.vmax, 0.0, sel.a[0], A_extra=A_x, b_extra=b_x)
    assert np.all(A_x @ np.asarray(out["e"], dtype=float) <= b_x + 1e-9)


def test_the_control_t_approximation_error_is_the_module_against_the_ac_loading():
    """s. 6: |module |flow|/cap - AC loading_percent/100|, p95 over every branch and corner."""
    module = np.array([0.20, 0.50, 0.80, 0.95])
    ac_percent = 100.0 * (module + np.array([0.01, -0.02, 0.03, -0.04]))
    np.testing.assert_allclose(
        stage_a.thermal_error(module, ac_percent),
        np.array([0.01, 0.02, 0.03, 0.04]),
        rtol=0,
        atol=1e-15,
    )
    with pytest.raises(ValueError, match="branches"):
        stage_a.thermal_error(module, ac_percent[:-1])

    sample = [0.01] * 19 + [0.40]
    assert stage_a._p95(sample) == pytest.approx(float(np.percentile(sample, 95)))
    assert stage_a._p95([0.02, math.nan, 0.02]) == pytest.approx(0.02)
    assert math.isnan(stage_a._p95([math.nan, math.nan]))


def _branch_aware_ac(built, offset=0.01):
    """`linear_ac` plus the per-branch AC loading control T reads, offset by a known amount.

    The "AC" loading of branch l is `offset` above the thermal module's own |flow|/cap, so
    the realised approximation error is exactly `offset` at every branch of every corner.
    """
    base = linear_ac(built)

    def fake_solve(net_state, pv, load_p, load_q, ledger_counter):
        out = base(net_state, pv, load_p, load_q, ledger_counter)
        module = stage_a.thermal_module_loading(net_state, pv, load_p)
        out["branch_loading"] = 100.0 * (module + offset)
        return out

    return fake_solve


def _controls_fixture(built, sel, tmp_path, monkeypatch, solver):
    rows = {regime: synthetic_rows(built, regime) for regime in stage_a.REGIME_ORDER}
    monkeypatch.setattr(stage_a, "build", lambda key: built)
    monkeypatch.setattr(stage_a, "load_selection", lambda key: sel)
    monkeypatch.setattr(stage_a, "load_physics", lambda key: rows)
    monkeypatch.setattr(stage_a, "profiles_of", lambda b: _toy_profiles())
    monkeypatch.setattr(stage_a, "solve", solver)
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)


def test_the_controls_stage_runs_every_arm_and_measures_the_thermal_error(tmp_path, monkeypatch):
    """Controls H, I and T plus B4box-OLS, with a known per-branch approximation error."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    _controls_fixture(built, sel, tmp_path, monkeypatch, _branch_aware_ac(built, 0.01))

    assert stage_a.run_controls("toy") == 0
    payload = json.loads((tmp_path / "controls_toy.json").read_text())
    planned = stage_a.controls_planned("toy", sel.n_conditions, len(sel.near_rows))
    assert payload["planned_max"] == planned == 18
    assert len(payload["records"]) == planned
    assert payload["solves"] <= planned
    assert payload["control_h_long_run"] is False
    assert [info["arm"] for info in payload["control_h"]] == ["H192"]
    assert {info["arm"] for info in payload["control_i"]} == {"I0.0005", "I0.005"}
    assert {r["method"] for r in payload["records"]} == {
        "H192", "I0.0005", "I0.005", "T", "B4boxOLS",
    }  # fmt: skip

    thermal = payload["control_t"]
    assert thermal["n_shortcut_corners"] == 0
    assert thermal["n_branch_samples"] == 4 * built.n_branches  # 2 regimes x R = 2, 1 near
    assert thermal["approximation_error_p95"] == pytest.approx(0.01)
    assert thermal["approximation_limited"] is False
    control_t = [r for r in payload["records"] if r["method"] == "T"]
    assert len(control_t) == 4
    for record in control_t:
        assert record["kappa"] == el.KAPPA_T
        assert record["kind"] == "near"
        assert len(record["module_loading"]) == built.n_branches
        assert len(record["ac_branch_loading"]) == built.n_branches
        assert record["approximation_error_max"] == pytest.approx(0.01)
        for row in record["active_extra"]:
            assert row["branch"] in range(built.n_branches)

    with np.load(tmp_path / "controls_toy.npz", allow_pickle=False) as stored:
        assert stored["e"].shape == (planned, built.n_units)
        assert stored["vm_corner"].dtype == np.float32


def test_the_b4box_ols_arm_runs_no_solve_when_the_design_is_ill_conditioned(tmp_path, monkeypatch):
    """s. 7: cond > 1e10 is recorded as `robust-degenerate` with no envelope and no solve."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    _controls_fixture(built, sel, tmp_path, monkeypatch, _branch_aware_ac(built))
    monkeypatch.setattr(stage_a, "OLS_COND_LIMIT", 0.0)  # every design is now "ill-conditioned"

    assert stage_a.run_controls("toy") == 0
    payload = json.loads((tmp_path / "controls_toy.json").read_text())
    arm = [r for r in payload["records"] if r["method"] == "B4boxOLS"]
    assert len(arm) == 4  # 2 regimes x R = 2, on the one near condition
    for record in arm:
        assert record["status"] == el.ROBUST_DEGENERATE
        assert record["reason"] == "ill-conditioned"
        assert record["scored"] is False
        assert record["unsafe"] is False  # never recorded as a safe envelope either
        assert record["total_e"] == 0.0
    assert all(cell["ill_conditioned"] for cell in payload["b4box_ols"].values())

    scored = [r for r in payload["records"] if r["scored"]]
    shortcuts = sum(1 for r in scored if r["e_equals_a"])
    assert payload["solves"] + shortcuts == len(scored) == len(payload["records"]) - 4
    with np.load(tmp_path / "controls_toy.npz", allow_pickle=False) as stored:
        assert stored["e"].shape[0] == len(scored)


# --- I. ambiguity, CERT, ALWAYS and RAND (s. 7, s. 8) --------------------------------------


def test_the_policy_bookkeeping_counts_cert_always_and_rand():
    """s. 7: CERT acts with B2 where it certifies and with B2p where it does not; RAND falls
    back the same number of times; ALWAYS is B2p throughout."""
    act = np.array([True, True, False, False])
    unsafe_b2 = np.array([True, False, True, False])
    unsafe_b2p = np.array([False, False, False, True])
    rand = np.array([True, False, False, True])

    out = stage_a.policy_bookkeeping(act, unsafe_b2, unsafe_b2p, rand)
    assert out["n"] == 4 and out["k"] == 2 and out["fallback_rate"] == pytest.approx(0.5)
    # CERT: rows 0 and 1 act on B2 (row 0 unsafe), rows 2 and 3 fall back to B2p (row 3 unsafe).
    assert out["cert_unsafe"] == 2
    assert out["always_unsafe"] == 1
    # RAND: rows 0 and 3 fall back to B2p (row 3 unsafe), rows 1 and 2 use B2 (row 2 unsafe).
    assert out["rand_unsafe"] == 2
    assert out["b2_unsafe"] == 2
    assert out["evaluable"] is True and out["verdict"] == "OK"

    with pytest.raises(ValueError, match="one entry per condition"):
        stage_a.policy_bookkeeping(act[:3], unsafe_b2, unsafe_b2p, rand)
    with pytest.raises(ValueError, match="requires the same count"):
        stage_a.policy_bookkeeping(act, unsafe_b2, unsafe_b2p, np.zeros(4, dtype=bool))


@pytest.mark.parametrize("k", [0, 3])
def test_cert_is_not_evaluable_when_it_never_or_always_falls_back(k):
    """s. 7: at k = 0 or k = n, RAND is identical to CERT and the comparison is empty."""
    n = 3
    act = np.array([k == 0] * n)
    rand = np.array([k != 0] * n)
    out = stage_a.policy_bookkeeping(act, np.zeros(n, bool), np.ones(n, bool), rand)
    assert out["k"] == k
    assert out["evaluable"] is False and out["verdict"] == "NOT EVALUABLE"


def test_the_new_stages_refuse_without_their_prerequisites(tmp_path, monkeypatch):
    """`ambiguity` needs `envelopes` and `oracle`; `monotonicity` needs `oracle` (s. 8, s. 15)."""
    monkeypatch.setattr(stage_a, "OUT", tmp_path)
    monkeypatch.setattr(stage_a, "RESULTS", tmp_path)
    with pytest.raises(FileNotFoundError, match="run `envelopes"):
        stage_a.run_ambiguity("semiurb5")
    with pytest.raises(FileNotFoundError, match="run `oracle"):
        stage_a.run_monotonicity("semiurb5")

    # with `envelopes` in place but no oracle, `ambiguity` still refuses - on the oracle.
    (tmp_path / "envelopes_semiurb5.json").write_text("{}")
    np.savez(tmp_path / "envelopes_semiurb5.npz", e=np.zeros((1, 1)))
    with pytest.raises(FileNotFoundError, match="run `oracle"):
        stage_a.run_ambiguity("semiurb5")
    assert not list(tmp_path.glob("abort_*"))  # a refusal charges the ledger nothing


def test_the_ambiguity_stage_scores_eight_alternatives_and_books_the_policies(
    tmp_path, monkeypatch
):
    """s. 8: 8 alternatives x the near conditions x P1 and P3, and s. 7's three policies.

    The stage is run after `envelopes` and `oracle` on the same toy feeder, so its
    recomputation of B2's fit and radius is checked against the stored read-outs for real.
    """
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    _controls_fixture(built, sel, tmp_path, monkeypatch, linear_ac(built))

    assert stage_a.run_envelopes("toy") == 0
    assert stage_a.run_oracle("toy") == 0
    assert stage_a.run_ambiguity("toy") == 0

    payload = json.loads((tmp_path / "ambiguity_toy.json").read_text())
    planned = stage_a.ambiguity_planned(len(sel.near_rows))
    assert payload["planned_max"] == planned == 16
    assert len(payload["records"]) == planned
    assert len(payload["fits"]) == len(stage_a.CONTROL_REGIMES)
    for fit in payload["fits"]:
        assert len(fit["rmse_ratio"]) == 4
        assert 0.0 <= fit["shrink_min"] <= fit["shrink_max"] <= 1.0
        assert set(fit["verified_against_stored"]) == {
            "lam", "b2_slope_norm", "radius_c", "r2_median", "r2_max",
        }  # fmt: skip
    families = {r["family"] for r in payload["records"]}
    assert families == {"random", "extreme"}
    for record in payload["records"]:
        assert record["fair_ac_scored"] is False
        assert math.isfinite(record["fair_total_e"])
    for measure in payload["measures"]:
        assert measure["primary"]["safety_disagreement"] in (True, False)
        assert measure["fair"]["safety_disagreement"] is None
    # one near condition on the toy feeder, so k is 0 or 1 and CERT is NOT EVALUABLE (s. 7).
    for policy in payload["policies"]:
        assert policy["n"] == 1
        assert policy["verdict"] == "NOT EVALUABLE"
        assert sum(policy["rand_fallback"]) == policy["k"]


def test_the_ambiguity_stage_refuses_a_fit_that_has_drifted_from_the_stored_one():
    """s. 8 step 1: a recomputed lambda or radius that differs stops the stage."""
    built, _ = built_synthetic()
    cell = stage_a.fit_cell(built, "P1", 0, synthetic_rows(built), N_YEAR)
    stored = {
        "regime": "P1",
        "replicate": 0,
        "lam": float(cell.lam),
        "control_k": {"b2_slope_norm": float(np.linalg.norm(cell.b2.slopes))},
        "radius": {
            "c": float(cell.radius.c),
            "r2_median": float(np.median(cell.radius.r2)),
            "r2_max": float(np.max(cell.radius.r2)),
        },
    }
    verified = stage_a.verify_stored_fit(cell, stored)
    assert verified["lam"] == pytest.approx(cell.lam)

    drifted = json.loads(json.dumps(stored))
    drifted["radius"]["c"] = float(cell.radius.c) * 1.001
    with pytest.raises(ValueError, match="recomputed radius_c"):
        stage_a.verify_stored_fit(cell, drifted)


# --- J. the s. 15 monotonicity check -------------------------------------------------------


def test_the_monotonicity_flag_fires_only_on_a_safe_corner_and_an_unsafe_interior():
    """s. 15: an interior point above the limit while the corner is not."""
    assert stage_a.monotonicity_flag(-0.01, 0.002) is True
    assert stage_a.monotonicity_flag(0.0, 1e-9) is True
    assert stage_a.monotonicity_flag(-0.01, -0.002) is False
    assert stage_a.monotonicity_flag(-0.01, 0.0) is False
    assert stage_a.monotonicity_flag(0.004, 0.002) is False  # the corner already violates
    # s. 12: a failed flow is a failed solve, not a monotonicity failure.
    assert stage_a.monotonicity_flag(-0.01, math.nan) is False
    assert stage_a.monotonicity_flag(math.nan, 0.01) is False


def test_the_oracle_corner_exceedance_is_the_kept_envelopes_own_history_entry():
    record = {
        "row": 0,
        "total_e": 0.7,
        "history": [
            {"total": 0.9, "max_exceedance": 0.004, "feasible": False},
            {"total": 0.5, "max_exceedance": -0.02, "feasible": True},
            {"total": 0.7, "max_exceedance": -0.001, "feasible": True},
        ],
    }
    assert stage_a.oracle_corner_exceedance(record) == pytest.approx(-0.001)
    none_feasible = {"row": 1, "total_e": 0.0, "history": [record["history"][0]]}
    assert math.isnan(stage_a.oracle_corner_exceedance(none_feasible))
    inconsistent = {"row": 2, "total_e": 0.6, "history": record["history"]}
    with pytest.raises(ValueError, match="largest"):
        stage_a.oracle_corner_exceedance(inconsistent)


def test_the_monotonicity_stage_visits_every_condition_and_flags_a_monotone_model(
    tmp_path, monkeypatch
):
    """s. 15: one interior point per condition, the oracle's `best_e` near and a far."""
    built, _ = built_synthetic()
    sel = synthetic_selection(built)
    _controls_fixture(built, sel, tmp_path, monkeypatch, linear_ac(built))

    assert stage_a.run_oracle("toy") == 0
    assert stage_a.run_monotonicity("toy") == 0
    payload = json.loads((tmp_path / "monotonicity_toy.json").read_text())
    assert payload["planned_max"] == stage_a.monotonicity_planned(sel.n_conditions) == 2
    assert payload["solves"] == 2
    assert [r["corner_source"] for r in payload["records"]] == [
        "oracle best_e",
        "selection no-action",
    ]
    # the stand-in AC is the exact linear model, which is monotone in e by construction.
    assert payload["n_failures_flagged"] == 0
    assert payload["stop_condition_triggered"] is False
    for record in payload["records"]:
        assert 0.0 <= record["share_of_envelope"] <= 1.0
        assert record["interior_exceedance"] <= record["corner_exceedance"] + 1e-12
    with np.load(tmp_path / "monotonicity_toy.npz", allow_pickle=False) as stored:
        assert stored["interior_e"].shape == (2, built.n_units)
