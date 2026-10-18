"""AC power-flow evaluation of a SimBench low-voltage benchmark grid (Track 2).

Units and conventions (pandapower):

- active power in MW, reactive power in MVAr;
- voltages in p.u. of each bus's nominal voltage;
- line loading = conductor current / `max_i_ka`, in %;
- transformer loading = current-based apparent power / `sn_mva`, in %;
- loads and storage use the load convention (positive = consumption, storage positive =
  charging); PV (`sgen`) uses the generator convention (positive = injection).

Limits are the benchmark's own `min_vm_pu` / `max_vm_pu` per bus and `max_loading_percent`
per line and transformer. Voltage margins cover the LV buses only; the slack bus is held
at a fixed voltage by the external grid. A margin is "value minus limit" in the violating
direction, so a margin > 0 is a violation and its size is the severity. A power flow that
does not converge has no valid physical state: its margins are NaN and it is never treated
as safe.
"""

from __future__ import annotations

import copy
import warnings

import numpy as np
import pandas as pd

NETWORK_CODE = "1-LV-rural1--2-sw"
STEP_HOURS = 0.25
INJECTIONS = ("load_p_mw", "load_q_mvar", "sgen_p_mw", "storage_p_mw")
# Signed margins of the four constraint types, in their own units (p.u. or %).
MARGINS = ("overvoltage_pu", "undervoltage_pu", "line_overload_pct", "trafo_overload_pct")


def load_network(code: str = NETWORK_CODE):
    """The SimBench network, with the benchmark's transformer taps made effective.

    simbench 1.6.3 sets `tap_pos` but leaves `tap_changer_type` empty, and pandapower 3.5
    then ignores the tap. This network's +1 HV tap (2.5 % step) would be dropped, raising
    LV voltages by about 0.025 p.u. and lowering transformer current.
    """
    import simbench

    net = simbench.get_simbench_net(code)
    has_tap = net.trafo["tap_pos"].notna() & net.trafo["tap_changer_type"].isna()
    net.trafo.loc[has_tap, "tap_changer_type"] = "Ratio"
    return net


def absolute_profiles(net) -> dict[str, pd.DataFrame]:
    """Absolute time series (steps x elements) of every injection, from the SimBench profiles.

    Values are the benchmark's relative profiles multiplied by each element's rating
    (`simbench.get_absolute_values`). SimBench's `time` column is German local time with
    daylight saving (2016-03-27 skips 02:00-02:45, 2016-10-30 repeats it); it is localised
    to Europe/Berlin, resolving the repeated hour by order, and returned in UTC.
    """
    import simbench

    absolute = simbench.get_absolute_values(net, profiles_instead_of_study_cases=True)
    local = pd.to_datetime(net.profiles["load"]["time"], format="%d.%m.%Y %H:%M")
    index = pd.DatetimeIndex(
        local.dt.tz_localize("Europe/Berlin", ambiguous="infer").dt.tz_convert("UTC"),
        name="time_utc",
    )
    if not (index[1:] - index[:-1] == pd.Timedelta(minutes=15)).all():
        raise ValueError("SimBench profile clock is not a regular 15-minute UTC grid")
    tables = {
        "load_p_mw": absolute[("load", "p_mw")],
        "load_q_mvar": absolute[("load", "q_mvar")],
        "sgen_p_mw": absolute[("sgen", "p_mw")],
        "storage_p_mw": absolute[("storage", "p_mw")],
    }
    return {name: table.set_axis(index) for name, table in tables.items()}


def cap_pv(available_mw: np.ndarray, rating_mw: np.ndarray, cap_fraction: float) -> np.ndarray:
    """PV output under a feed-in cap: min(available, cap_fraction x installed rating)."""
    if not 0 <= cap_fraction <= 1:
        raise ValueError(f"cap fraction must lie in [0, 1], got {cap_fraction}")
    return np.minimum(available_mw, cap_fraction * rating_mw)


class GridSolver:
    """Run AC power flows on one network, changing only load, PV and storage injections.

    pandapower's `recycle` option reuses the network model between calls and updates only
    the PQ injections; after a non-converged flow the next call starts from scratch.
    """

    def __init__(self, net):
        self.net = copy.deepcopy(net)
        self.pv_rating_mw = self.net.sgen["sn_mva"].to_numpy(dtype=float)
        self._monitored_buses = ~self.net.bus.index.isin(self.net.ext_grid["bus"])
        buses = self.net.bus[self._monitored_buses]
        self._limits = {
            "max_vm": buses["max_vm_pu"].to_numpy(dtype=float),
            "min_vm": buses["min_vm_pu"].to_numpy(dtype=float),
            "line": self.net.line["max_loading_percent"].to_numpy(dtype=float),
            "trafo": self.net.trafo["max_loading_percent"].to_numpy(dtype=float),
        }
        self._recycle_ready = False

    def reset(self) -> None:
        """Make the next flow start from scratch, so results do not depend on call order."""
        self._recycle_ready = False

    def solve(
        self,
        load_p_mw: np.ndarray,
        load_q_mvar: np.ndarray,
        sgen_p_mw: np.ndarray,
        storage_p_mw: np.ndarray,
    ) -> np.ndarray:
        """Margins (see MARGINS) of one operating state; all NaN if the flow fails."""
        import pandapower as pp

        net = self.net
        net.load["p_mw"] = load_p_mw
        net.load["q_mvar"] = load_q_mvar
        net.sgen["p_mw"] = sgen_p_mw
        net.storage["p_mw"] = storage_p_mw
        recycle = {"bus_pq": True, "trafo": False, "gen": False} if self._recycle_ready else None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                pp.runpp(
                    net, algorithm="nr", numba=False, check_connectivity=False, recycle=recycle
                )
        except pp.LoadflowNotConverged:
            self._recycle_ready = False
            return np.full(len(MARGINS), np.nan)
        self._recycle_ready = True
        vm = net.res_bus["vm_pu"].to_numpy()[self._monitored_buses]
        limits = self._limits
        return np.array(
            [
                np.max(vm - limits["max_vm"]),
                np.max(limits["min_vm"] - vm),
                np.max(net.res_line["loading_percent"].to_numpy() - limits["line"]),
                np.max(net.res_trafo["loading_percent"].to_numpy() - limits["trafo"]),
            ]
        )


def is_violation(margins: np.ndarray) -> np.ndarray:
    """True where any margin is positive or the flow did not converge (never 'safe')."""
    margins = np.asarray(margins, dtype=float)
    return np.isnan(margins).any(axis=-1) | (margins > 0).any(axis=-1)
