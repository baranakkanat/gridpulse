import numpy as np
import pytest

pytest.importorskip("pandapower")

from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import fullstate as fs  # noqa: E402
from gridpulse import grid_study as gs  # noqa: E402
from gridpulse.grid import absolute_profiles  # noqa: E402


def test_full_states_reproduce_phase4_margins_and_reverse_flow_sign():
    code, day = gs.NETWORK_CODE, 172
    net = ds.variant_network(code, ds.NOMINAL, 1.0)
    arrays = gs.daily_arrays(absolute_profiles(net))
    solver = ds.VariantSolver(net, ds.NOMINAL)
    sets = ds.day_sets(arrays, day, solver.pv_rating_mw, 1)
    storage = np.zeros((1, gs.STEPS, len(net.storage)))
    states = fs.day_states(solver, sets, storage, fs.lv_buses(net))
    phase4 = ds.day_margins(ds.VariantSolver(net, ds.NOMINAL), sets, storage)[0]
    assert np.array_equal(states["margins"], phase4, equal_nan=True)
    noon, night = states["trafo"][48, 0], states["trafo"][4, 0]
    assert noon[0] > 0 > night[0]  # MW into the transformer: reverse flow at noon only
    assert states["vm"].shape == (gs.STEPS, len(gs.CAP_LEVELS), len(net.bus) - 1)
    # voltages and margins agree: the overvoltage margin is the highest LV voltage minus 1.1
    worst = (states["vm"][:, 0] - 1.1).max(axis=1)
    assert np.allclose(worst, states["margins"][:, 0, 0], atol=1e-6)
