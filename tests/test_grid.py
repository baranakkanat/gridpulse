import copy

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("pandapower", reason="grid extra not installed (uv sync --all-extras)")

from gridpulse.grid import (  # noqa: E402
    MARGINS,
    STEP_HOURS,
    GridSolver,
    absolute_profiles,
    cap_pv,
    is_violation,
    load_network,
)


@pytest.fixture(scope="module")
def net():
    return load_network()


@pytest.fixture(scope="module")
def profiles(net):
    return absolute_profiles(net)


@pytest.fixture
def solver(net):
    return GridSolver(net)


def state(net, profiles, step: int, pv_scale: float = 1.0, load_scale: float = 1.0):
    return (
        profiles["load_p_mw"].iloc[step].to_numpy() * load_scale,
        profiles["load_q_mvar"].iloc[step].to_numpy() * load_scale,
        profiles["sgen_p_mw"].iloc[step].to_numpy() * pv_scale,
        profiles["storage_p_mw"].iloc[step].to_numpy(),
    )


def test_profiles_are_relative_benchmark_values_times_ratings_in_mw(net, profiles):
    index = profiles["sgen_p_mw"].index
    steps = index[1:] - index[:-1]
    assert len(index) == 366 * 96
    # SimBench's local 2016-01-01 00:00 (CET) is 2015-12-31 23:00 UTC; DST gaps are gone.
    assert index[0] == pd.Timestamp("2015-12-31 23:00", tz="UTC")
    assert (steps == pd.Timedelta(minutes=15)).all()
    step = 4 * 12 + 96 * 180  # noon on 29 June
    relative = net.profiles["renewables"].loc[step, net.sgen["profile"]].to_numpy(dtype=float)
    np.testing.assert_allclose(
        profiles["sgen_p_mw"].iloc[step].to_numpy(), relative * net.sgen["p_mw"].to_numpy()
    )
    # Installed PV never exceeds its rating in the benchmark profiles.
    assert (profiles["sgen_p_mw"].to_numpy() <= net.sgen["sn_mva"].to_numpy() + 1e-12).all()


def test_fast_solver_matches_a_full_pandapower_power_flow(net, profiles, solver):
    import pandapower as pp

    for step in (0, 96 * 100 + 50, 96 * 180 + 48):
        margins = solver.solve(*state(net, profiles, step))
        reference = copy.deepcopy(solver.net)
        pp.runpp(reference, numba=False)
        lv = reference.bus["vn_kv"] < 1
        vm = reference.res_bus.loc[lv, "vm_pu"].to_numpy()
        expected = [
            np.max(vm - reference.bus.loc[lv, "max_vm_pu"].to_numpy()),
            np.max(reference.bus.loc[lv, "min_vm_pu"].to_numpy() - vm),
            np.max(reference.res_line["loading_percent"] - reference.line["max_loading_percent"]),
            np.max(reference.res_trafo["loading_percent"] - reference.trafo["max_loading_percent"]),
        ]
        np.testing.assert_allclose(margins, expected, atol=1e-5)


def test_benchmark_transformer_tap_is_applied(net, solver):
    """+1 HV tap at 2.5 % with the slack at 1.025 p.u. gives about 1.000 p.u. at no load."""
    zero = np.zeros
    solver.solve(zero(len(net.load)), zero(len(net.load)), zero(len(net.sgen)), zero(5))
    lv = (net.bus["vn_kv"] < 1).to_numpy()
    assert solver.net.res_bus["vm_pu"].to_numpy()[lv] == pytest.approx(1.0, abs=1e-3)


def test_voltage_margins_ignore_the_fixed_slack_bus(net, profiles, solver):
    margins = solver.solve(*state(net, profiles, 96 * 100 + 50))
    lv = (net.bus["vn_kv"] < 1).to_numpy()
    lv_vm = solver.net.res_bus["vm_pu"].to_numpy()[lv]
    assert margins[MARGINS.index("overvoltage_pu")] == pytest.approx(np.max(lv_vm - 1.1))
    assert margins[MARGINS.index("undervoltage_pu")] == pytest.approx(np.max(0.9 - lv_vm))


def test_more_pv_raises_voltage_and_transformer_loading_at_low_load(net, profiles, solver):
    step = 96 * 180 + 48  # a summer noon
    lv = (net.bus["vn_kv"] < 1).to_numpy()
    lv_peak, trafo = [], []
    for pv_scale in (0.0, 0.5, 1.0):
        solver.solve(*state(net, profiles, step, pv_scale, load_scale=0.2))
        lv_peak.append(solver.net.res_bus["vm_pu"].to_numpy()[lv].max())
        trafo.append(solver.net.res_trafo["loading_percent"].iloc[0])
    assert lv_peak[0] < lv_peak[1] < lv_peak[2]
    assert trafo[1] < trafo[2]  # reverse power flow grows once PV exceeds local load


def test_full_installed_pv_at_low_load_overloads_the_transformer(net, solver):
    rating = net.sgen["sn_mva"].to_numpy()
    margins = solver.solve(
        0.01 * net.load["p_mw"].to_numpy(),
        0.01 * net.load["q_mvar"].to_numpy(),
        rating,
        np.zeros(len(net.storage)),
    )
    # 0.468 MW of PV through a 0.16 MVA transformer.
    assert margins[MARGINS.index("trafo_overload_pct")] > 100
    assert is_violation(margins)


def test_pv_cap_limits_output_and_curtailed_energy_is_accounted(net):
    rating = net.sgen["sn_mva"].to_numpy()
    available = np.array([0.0, 0.5, 0.9, 1.0, 0.2, 0.75, 0.65, 0.3]) * rating
    capped = cap_pv(available, rating, 0.7)

    np.testing.assert_allclose(capped, np.minimum(available, 0.7 * rating))
    curtailed_mwh = (available - capped).sum() * STEP_HOURS
    expected = (np.array([0, 0, 0.2, 0.3, 0, 0.05, 0, 0]) * rating).sum() * STEP_HOURS
    assert curtailed_mwh == pytest.approx(expected)
    np.testing.assert_array_equal(cap_pv(available, rating, 1.0), available)
    with pytest.raises(ValueError):
        cap_pv(available, rating, 1.2)


def test_non_converged_flow_is_never_safe_and_the_solver_recovers(net, profiles, solver):
    huge = np.full(len(net.load), 50.0)  # 50 MW per LV load: no physical solution
    failed = solver.solve(huge, huge * 0.4, net.sgen["sn_mva"].to_numpy() * 0, np.zeros(5))
    assert np.isnan(failed).all()
    assert is_violation(failed)

    normal = solver.solve(*state(net, profiles, 96 * 100 + 50))
    assert np.isfinite(normal).all()
    np.testing.assert_allclose(normal, GridSolver(net).solve(*state(net, profiles, 96 * 100 + 50)))


def test_violation_requires_a_positive_margin():
    margins = np.array([[-0.01, -0.05, -10.0, -1.0], [0.002, -0.05, -10.0, -1.0], [np.nan] * 4])
    assert is_violation(margins).tolist() == [False, True, True]
