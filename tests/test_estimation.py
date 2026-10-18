import copy

import numpy as np
import pytest

pp = pytest.importorskip("pandapower")

from gridpulse import estimation as es  # noqa: E402


@pytest.fixture(scope="module")
def feeder():
    """A 4-bus radial LV feeder: MV slack, LV busbar, junction, two customer buses."""
    net = pp.create_empty_network()
    mv = pp.create_bus(net, 20.0)
    busbar, junction, c1, c2 = (pp.create_bus(net, 0.4) for _ in range(4))
    pp.create_ext_grid(net, mv, vm_pu=1.0)
    pp.create_transformer(net, mv, busbar, "0.25 MVA 20/0.4 kV")
    for a, b in ((busbar, junction), (junction, c1), (junction, c2)):
        pp.create_line(net, a, b, 0.1, "NAYY 4x150 SE")
    pp.create_load(net, c1, 0.01, 0.002)
    pp.create_sgen(net, c2, 0.05)
    pp.runpp(net)
    return net, {"busbar": busbar, "junction": junction, "c1": c1, "c2": c2}


def _with(net, measurements):
    m = copy.deepcopy(net)
    m.measurement = m.measurement.iloc[0:0]
    for kind, element_type, value, sigma, element, side in measurements:
        pp.create_measurement(m, kind, element_type, value, sigma, element, side=side)
    return m


def _substation(net, b):
    return [
        ("v", "bus", net.res_bus.vm_pu[b["busbar"]], 0.001, b["busbar"], None),
        ("p", "trafo", net.res_trafo.p_lv_mw[0], 0.0005, 0, "lv"),
        ("q", "trafo", net.res_trafo.q_lv_mvar[0], 0.0005, 0, "lv"),
    ]


def _pseudo(net, b, error=0.0):
    out = []
    for name in ("c1", "c2"):
        bus = b[name]
        out.append(("p", "bus", net.res_bus.p_mw[bus] * (1 + error), 0.005, bus, None))
        out.append(("q", "bus", net.res_bus.q_mvar[bus] * (1 + error), 0.005, bus, None))
    return out


def test_zero_injection_buses_are_the_junctions(feeder):
    net, b = feeder
    assert es.zero_injection_buses(net) == [b["busbar"], b["junction"]]


def test_substation_only_is_underdetermined_and_refused(feeder):
    net, b = feeder
    m = _with(net, _substation(net, b))
    obs = es.numerical_observability(m)
    assert not obs["observable"] and obs["rank"] < obs["states"]
    assert es.estimate(m)["success"] is False  # refused, not silently "estimated"


def test_rank_deficiency_is_detected_even_with_enough_measurements(feeder):
    net, b = feeder
    # as many readings as states, but all at one bus: count suffices, rank does not
    v = net.res_bus.vm_pu[b["c1"]]
    repeated = [("v", "bus", v, 0.001, b["c1"], None)] * 12
    m = _with(net, _substation(net, b) + repeated)
    obs = es.numerical_observability(m)
    assert len(m.measurement) >= obs["states"] and not obs["observable"]


def test_pseudo_measurements_make_it_observable_and_exact_values_recover_the_state(feeder):
    net, b = feeder
    m = _with(net, _substation(net, b) + _pseudo(net, b))
    result = es.estimate(m)
    assert result["observable"] and result["success"]
    for bus, vm in result["vm"].items():
        assert vm == pytest.approx(net.res_bus.vm_pu[bus], abs=1e-4)


def test_biased_pseudo_measurements_bias_the_estimate(feeder):
    net, b = feeder
    exact = es.estimate(_with(net, _substation(net, b) + _pseudo(net, b)))
    biased = es.estimate(_with(net, _substation(net, b) + _pseudo(net, b, error=-0.5)))
    remote = b["c2"]
    assert abs(biased["vm"][remote] - net.res_bus.vm_pu[remote]) > abs(
        exact["vm"][remote] - net.res_bus.vm_pu[remote]
    )
    # a remote voltage reading pulls the estimate back towards the truth
    sensor = [("v", "bus", net.res_bus.vm_pu[remote], 0.001, remote, None)]
    corrected = es.estimate(_with(net, _substation(net, b) + _pseudo(net, b, -0.5) + sensor))
    assert abs(corrected["vm"][remote] - net.res_bus.vm_pu[remote]) < abs(
        biased["vm"][remote] - net.res_bus.vm_pu[remote]
    )
    assert np.isfinite(list(corrected["vm"].values())).all()


def test_pseudo_measurements_use_only_past_days_and_respect_the_cap():
    rng = np.random.default_rng(0)
    days, steps = 40, 96
    load = rng.uniform(0.0, 0.01, size=(days, steps, 1))
    pv = rng.uniform(0.0, 0.05, size=(days, steps, 1))
    series = {
        "buses": [7], "p": load - pv, "q": 0.2 * load, "sgen_p": pv,
        "sgen_map": np.ones((1, 1)),
    }  # fmt: skip
    before = es.pseudo_measurements(series, 35, 48)
    for name in ("p", "q", "sgen_p"):
        series[name][35:] = 99.0  # the day itself and later must not matter
    assert es.pseudo_measurements(series, 35, 48) == before
    (p, _), (sigma_p, _) = before[7]
    assert p == pytest.approx((load - pv)[28:35, 48, 0].mean())
    assert sigma_p > 0
    capped = es.pseudo_measurements(series, 35, 48, cap=0.0, rating=np.array([1.0]))
    assert capped[7][0][0] == pytest.approx(load[28:35, 48, 0].mean())  # no PV left


def test_estimator_inputs_drop_current_magnitudes_but_keep_the_rest():
    from gridpulse import sensing

    config = sensing.Config("c", transformer=True, heads=(1, 2), voltages=(5,), lines=(3,))
    inputs = es.estimator_inputs(config)
    assert inputs.transformer and inputs.voltages == (5,)
    assert inputs.heads == () and inputs.lines == ()
