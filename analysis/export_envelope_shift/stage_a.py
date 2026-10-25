"""Mission 11 Stage A: the runner that holds the pandapower solves.

EXPLORATORY and unregistered. The protocol is `stage_a_protocol.md` revision 2.2 plus the
dated amendments A1-A2, whose sha256 is `envelope_core.PROTOCOL_SHA256`; **every command
checks it, and the as-executed text above the amendments, before it does anything else**, so
a protocol edit stops the study rather than silently re-scoping it.

This module is the only part of Stage A that runs AC power flows. `envelope_core` (`ec`) and
`envelope_lp` (`el`) hold the physics-free data generation, estimators and decision LPs; they
are imported and never edited.

Commands (protocol s. 4, s. 5, s. 12):

* `build`    -- build the network and run the zero-flow assertions (0 solves);
* `days`     -- f(t) over the deployment days and their far candidates (0 solves);
* `ledger`   -- print the ledger reconstruction (0 solves);
* `summary`  -- print the report read-outs of this network's artefacts (0 solves);
* `physics`  -- the four regimes' training and test physics (s. 4, s. 17);
* `select`   -- the deployment conditions and the e = 0 vertex (s. 5, s. 17);
* `envelopes`-- the seven data-driven methods plus B0, A and A-prime, AC-scored (s. 6, s. 7);
* `oracle`   -- B5's sequential-LP oracle on the near set (s. 7);
* `controls` -- controls H, I and T and the B4box-OLS arm (s. 6, s. 7, s. 10);
* `ambiguity`-- s. 8's 8 data-consistent alternatives, and CERT, ALWAYS and RAND (s. 7);
* `monotonicity` -- s. 15's AC interior-point check of corner monotonicity.

Conventions are `envelope_core`'s: 15-minute steps indexed `day.96 + step` over SimBench's
2016, power in MW/Mvar and **export-positive at a bus**, voltage in pu, K customer buses, N
PV units, L branches with the transformer as branch 0.

**The ledger has no mutable file.** Every artefact in `results/` carries its own `"solves"`,
and `ledger_total()` reconstructs the running total as 106 (the board design audits) plus the
sum over `results/*.json`, abort records included. Artefacts are written once: a rerun of a
stage raises `FileExistsError` rather than overwriting a counted result.

**Storage is held at 0 MW in every solve** (protocol s. 2, s. 3).
"""

from __future__ import annotations

import argparse
import json
import math
import signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (REPO / "src", HERE):  # imported, never copied or edited
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import envelope_core as ec  # noqa: E402
import envelope_lp as el  # noqa: E402

from gridpulse import dual_study, grid, grid_study  # noqa: E402

# --- A. constants fixed by the protocol ----------------------------------------------------

#: protocol s. 3: the evaluation network is rural3, the development network semiurb5.
NETWORKS = {"semiurb5": "1-LV-semiurb5--2-sw", "rural3": "1-LV-rural3--2-sw"}

#: the zero-solve counts of the board audit (s. 2, s. 3), asserted before the first solve.
EXPECTED_CUSTOMERS = {"semiurb5": 104, "rural3": 118}
EXPECTED_PV = {"semiurb5": 15, "rural3": 27}

#: protocol s. 13 and s. 17: SimBench 2016 UTC day indices, as in `grid_study`.
TRAIN_DAYS = (152, 153, 154, 155)
TEST_DAYS = (156,)
EXTENSION_DAYS = (132, 133, 134, 135)  # rural3, P1 only
DEPLOY_DAYS = tuple(range(160, 200))

#: the regime order of the physics stage. L0 is P1's PV process with native loads (s. 4).
REGIME_ORDER = ("P1", "P2", "P3", "L0")
L0_SEED_REGIME = "P1"  # s. 17.2: L0 uses P1's PV seeds

SIGMA_V = 0.002  #: s. 4: the primary smart-meter voltage noise, in pu

DAYLIGHT_F = 0.01  #: s. 17.1: "daylight" means f(t) >= 0.01
FAR_F = 0.20  #: s. 5: the far candidate is the first step with f(t) >= 20 % of rating
NEAR_SCREEN_PU = 0.001  #: s. 5: the near screen keeps exceedances above +0.001 pu
FAR_LOADING_CAP = 80.0  #: s. 5: every thermal loading of a far candidate is at most 80 %
SET_SIZE = 10  #: s. 5: ten near and ten far conditions

VOLTAGE_UNSAFE_PU = 0.001  #: s. 13
THERMAL_UNSAFE_PCT = 0.5  #: s. 13
FAILURE_SHARE = 0.02  #: s. 12: more than 2 % failed solves in a stage is NOT EVALUABLE

LEDGER_START = 106  #: s. 12: the board design audits, already spent
LEDGER_CEILING = 8000  #: s. 12: the owner's ceiling

#: s. 6, s. 7: the seven AC-scored deployable methods of the primary decision.
DATA_METHODS = ("B1", "B2", "B2m", "B2p", "B3", "B4box", "B4")
#: s. 7, s. 9: the regime-independent arms, one envelope per condition.
FIXED_METHODS = ("B0", "A", "Aprime")
#: s. 4, s. 9: P1-P3 carry R = 2 noise realisations, the L0 control R = 1.
ENVELOPE_CELLS = (("P1", 0), ("P1", 1), ("P2", 0), ("P2", 1), ("P3", 0), ("P3", 1), ("L0", 0))
APRIME_CELL = ("P1", 0)  #: s. 17.5: Method A-prime's intercept is fitted on P1, replicate 0

B0_SHARE = 0.7  #: s. 7: the 70 % rule, e_i = min(a_i, 0.7.r_i)
K_SIGMA = 3.0  #: s. 7, B4box: the +- 3 sigma-hat per-coefficient box
SHORTCUT_TOL = 1e-12  #: s. 6: an envelope equal to a within this (MW) reuses the no-action solve

#: s. 15: the label every record carries on a network where the near set is not evaluable.
DESCRIPTIVE_LABEL = "descriptive (s. 15: H1-H3 NOT EVALUABLE on this network)"
EVALUABLE_LABEL = "scored"

#: s. 10's controls, s. 8's ambiguity and s. 15's monotonicity check.
CONTROL_REGIMES = ("P1", "P3")  #: s. 10 controls I and T, and s. 8: the H1 contrast's pair
CONTROL_REPLICATES = (0, 1)  #: s. 10 control T and the B4box-OLS arm run at R = 2
CONTROL_H_SHORT_DAYS = (152, 153)  #: s. 17.4: control H's T = 192, 2 CV folds
CONTROL_H_LONG_DAYS = (132, 133, 134, 135, 152, 153, 154, 155)  #: s. 17.4: T = 768, 8 folds
CONTROL_H_LONG_NETWORKS = ("rural3",)  #: s. 10 control H: T = 768 on rural3 P1 only
CONTROL_H_REGIME = "P1"  #: s. 10 control H is run on P1
CONTROL_I_SIGMA = (0.0005, 0.005)  #: s. 10 control I, with the same z as SIGMA_V (s. 17.3)
OLS_COND_LIMIT = 1e10  #: s. 7, B4box-OLS: a relative condition number above this is degenerate
THERMAL_P95_LIMIT = 0.05  #: s. 6: a 95th-percentile module error above 5 % is approximation-limited
N_ALTERNATIVES = 8  #: s. 8: M = 8 data-consistent alternatives, 4 random and 4 extreme
AMBIGUITY_REPLICATE = 0  #: s. 17.6: the alternatives, CERT, ALWAYS and RAND use replicate 0
MONOTONICITY_PU = 0.0  #: s. 15: the interior point must not violate the upper limit at all

#: bulk arrays and JSON records. Both are **local only** and never tracked (s. 16).
OUT = HERE / "runs"
RESULTS = HERE / "results"


# --- B. the ledger (no mutable file) -------------------------------------------------------


@dataclass
class SolveCounter:
    """Attempted AC solves, counted whether or not the flow converged (protocol s. 12).

    `banked` is the part already written into an artefact's `"solves"`. The difference is
    what an abort record must carry, so that no solve is ever counted twice or lost.
    """

    attempts: int = 0
    failures: int = 0
    banked: int = 0

    @property
    def pending(self) -> int:
        return self.attempts - self.banked

    def bank(self) -> int:
        """Hand the pending count to an artefact that is about to be written."""
        n = self.pending
        self.banked = self.attempts
        return n


def ledger_total(results: Path | None = None) -> int:
    """106 plus the `"solves"` of every `results/*.json`, abort records included.

    The arithmetic and the ceiling are `ec.SolveLedger`'s, so the runner cannot drift from
    the frozen core's rule.
    """
    directory = RESULTS if results is None else Path(results)
    ledger = ec.SolveLedger(start=LEDGER_START, ceiling=LEDGER_CEILING)
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text())
            if "solves" in payload:
                ledger.charge(path.stem, int(payload["solves"]))
    return ledger.total


def assert_budget(planned_max: int, results: Path | None = None) -> int:
    """Refuse to start a stage whose planned maximum would break the 8,000 ceiling."""
    ledger = ec.SolveLedger(start=ledger_total(results), ceiling=LEDGER_CEILING)
    ledger.charge("planned", int(planned_max))
    return ledger.total


def abort_record(
    stage: str,
    key: str,
    counter: SolveCounter,
    error: BaseException,
    partial: dict | None = None,
) -> Path | None:
    """Write `results/abort_<stage>_<network>_<n>.json` for solves not yet in an artefact.

    `partial` carries whatever the stage had already measured, so that an abort costs the
    ledger its solves but does not also throw their results away.
    """
    n = counter.bank()
    if n <= 0:
        return None
    payload = {
        "stage": f"abort_{stage}",
        "network": key,
        "solves": n,
        "failures": counter.failures,
        "error": f"{type(error).__name__}: {error}",
        "status": "ABORTED",
    }
    if partial:
        payload["partial"] = partial
    return ec.write_json_once(RESULTS / f"abort_{stage}_{key}_{n}.json", payload)


def terminated(signum: int, _frame) -> None:
    """Turn a terminating signal into an exception, so a stage's abort record is still written.

    A default SIGTERM kills the interpreter outright: `except BaseException` never runs and the
    solves already attempted go uncounted (AKK-65). Raising instead keeps the ledger honest.
    """
    raise SystemExit(f"stage_a: terminated by signal {signum}; the stage aborts (s. 12)")


def install_termination_handler() -> None:
    """Install `terminated` for SIGTERM and SIGHUP at CLI entry (s. 12)."""
    for name in ("SIGTERM", "SIGHUP"):
        number = getattr(signal, name, None)
        if number is not None:
            signal.signal(number, terminated)


# --- C. the network (zero solves) ----------------------------------------------------------


@dataclass
class Network:
    """One built network and every array the study needs from it (protocol s. 3, s. 7)."""

    key: str
    code: str
    net: object
    customer_buses: np.ndarray  # (K,) pandapower bus labels, sorted
    lv_positions: np.ndarray  # positions into net.bus of every LV bus (vn_kv < 1)
    customer_positions: np.ndarray  # positions into net.bus of the customer buses
    U: np.ndarray  # (K, N) PV unit -> customer bus
    W: np.ndarray  # (K, n_loads) load -> customer bus
    ratings: np.ndarray  # (N,) r_i = net.sgen.sn_mva, in MW
    parent_branch: np.ndarray  # (L,) the tree, branch 0 = the transformer
    bus_of_branch_child: np.ndarray  # (L,) customer-bus index downstream of each branch
    path: np.ndarray  # (K, L) float
    down: np.ndarray  # (L, K) float
    rho: np.ndarray  # (L,) r_l / V_lv^2
    chi: np.ndarray  # (L,) x_l / V_lv^2
    r_ohm: np.ndarray  # (L,) referred to LV
    x_ohm: np.ndarray  # (L,)
    cap_mva: np.ndarray  # (L,) thermal capacity
    vmax: np.ndarray  # (K,) max_vm_pu at customer buses
    vmin: np.ndarray  # (K,) min_vm_pu at customer buses
    lv_vmax: np.ndarray  # max_vm_pu at every LV bus
    v_lv_kv: float
    line_rows: np.ndarray  # (L-1,) positions into net.line, branch 1..L-1 in branch order

    @property
    def n_branches(self) -> int:
        return int(self.cap_mva.size)

    @property
    def n_customers(self) -> int:
        return int(self.customer_buses.size)

    @property
    def n_units(self) -> int:
        return int(self.ratings.size)


def _breadth_first_tree(net, root: int) -> tuple[list[int], dict[int, int]]:
    """Lines in breadth-first order from `root`, with the downstream bus of each branch.

    Returns (`line_order`, `branch_of_bus`), where `branch_of_bus[bus]` is the branch whose
    downstream end is that bus; branch 0 is the transformer, whose downstream end is `root`.
    """
    from_bus = net.line["from_bus"].to_numpy(dtype=int)
    to_bus = net.line["to_bus"].to_numpy(dtype=int)
    labels = net.line.index.to_numpy()
    incident: dict[int, list[int]] = {}
    for row in range(labels.size):
        incident.setdefault(int(from_bus[row]), []).append(row)
        incident.setdefault(int(to_bus[row]), []).append(row)

    line_order: list[int] = []
    branch_of_bus: dict[int, int] = {int(root): 0}
    queue = [int(root)]
    used = set()
    while queue:
        bus = queue.pop(0)
        for row in incident.get(bus, []):
            if row in used:
                continue
            other = int(to_bus[row]) if int(from_bus[row]) == bus else int(from_bus[row])
            if other in branch_of_bus:  # a loop would revisit a bus; these feeders are radial
                raise ValueError(f"{net.line.index[row]!r} closes a loop at bus {other}")
            used.add(row)
            line_order.append(row)
            branch_of_bus[other] = len(line_order)  # branch 0 is the transformer
            queue.append(other)
    if len(line_order) != labels.size:
        raise ValueError(
            f"breadth-first search reached {len(line_order)} of {labels.size} lines; "
            "the LV network is not a single radial feeder from the transformer"
        )
    return line_order, branch_of_bus


def build(key: str) -> Network:
    """Build one of the protocol's networks and run every zero-flow assertion of s. 3.

    The SimBench facts of s. 2 are asserted here rather than in `network_arrays`, because
    they are statements about these two networks, not about every radial LV feeder: no open
    switch, every line in service and **no line with `parallel` > 1**.
    """
    code = NETWORKS[key]
    net = dual_study.variant_network(code, dual_study.NOMINAL, dual_study.pv_scale(code))

    # storage is held at 0 MW in every solve (s. 2, s. 3).
    net.storage["p_mw"] = 0.0

    if len(net.switch) and not bool(net.switch["closed"].all()):
        raise ValueError(f"{code} has an open switch; the protocol's networks have none (s. 2)")
    if not bool(net.line["in_service"].all()):
        raise ValueError(f"{code} has a line out of service (s. 3)")
    if (net.line["parallel"].to_numpy(dtype=int) != 1).any():
        raise ValueError(f"{code} has a line with parallel > 1; s. 2 records none")

    return network_arrays(net, key, code, EXPECTED_CUSTOMERS[key], EXPECTED_PV[key])


def network_arrays(net, key: str, code: str, expected_customers: int, expected_pv: int) -> Network:
    """Every array the study needs from a radial LV network (protocol s. 3, s. 7).

    Separated from `build` so the tree, the impedances, the incidences and the caps can be
    checked on a genuinely synthetic feeder with round parameter values (s. 16), with no
    SimBench dependency and no power flow.
    """
    if len(net.trafo) != 1:
        raise ValueError(f"{code} has {len(net.trafo)} transformers; the tree assumes one")
    if (net.line["parallel"].to_numpy(dtype=float) <= 0).any():
        raise ValueError(f"{code} has a line with parallel <= 0")

    bus_labels = net.bus.index.to_numpy()
    position_of = {int(label): pos for pos, label in enumerate(bus_labels)}
    vn_kv = net.bus["vn_kv"].to_numpy(dtype=float)
    lv_positions = np.flatnonzero(vn_kv < 1.0)

    customer_buses = np.unique(net.load["bus"].to_numpy(dtype=int))
    index_of_customer = {int(label): k for k, label in enumerate(customer_buses)}
    customer_positions = np.array([position_of[int(b)] for b in customer_buses], dtype=int)
    n_customers = customer_buses.size

    if n_customers != expected_customers:
        raise ValueError(
            f"{key}: {n_customers} customer buses, expected {expected_customers} (s. 3)"
        )
    if len(net.sgen) != expected_pv:
        raise ValueError(f"{key}: {len(net.sgen)} PV units, expected {expected_pv} (s. 3)")
    pv_buses = net.sgen["bus"].to_numpy(dtype=int)
    if not all(int(b) in index_of_customer for b in pv_buses):
        raise ValueError(f"{key}: a PV unit sits on a bus that carries no load (s. 3)")

    max_vm = net.bus["max_vm_pu"].to_numpy(dtype=float)
    min_vm = net.bus["min_vm_pu"].to_numpy(dtype=float)
    vmax = max_vm[customer_positions]
    vmin = min_vm[customer_positions]
    lv_vmax = max_vm[lv_positions]
    if float(vmax.min()) > float(lv_vmax.min()):
        raise ValueError(
            f"{key}: min(max_vm_pu) over customer buses {vmax.min()} exceeds the minimum over "
            f"all LV buses {lv_vmax.min()}; the customer-bus criterion would not be the "
            "binding one (s. 3)"
        )

    # incidences: P_bus = U.pv - W.l, Q_bus = -W.q (PV at unity power factor).
    U = np.zeros((n_customers, len(net.sgen)))
    U[[index_of_customer[int(b)] for b in pv_buses], np.arange(len(net.sgen))] = 1.0
    load_buses = net.load["bus"].to_numpy(dtype=int)
    W = np.zeros((n_customers, len(net.load)))
    W[[index_of_customer[int(b)] for b in load_buses], np.arange(len(net.load))] = 1.0
    ratings = net.sgen["sn_mva"].to_numpy(dtype=float)

    # the tree: branch 0 = the transformer, 1..L-1 = lines in breadth-first order.
    root = int(net.trafo["lv_bus"].iloc[0])
    line_order, branch_of_bus = _breadth_first_tree(net, root)
    n_branches = 1 + len(line_order)
    parent_branch = np.empty(n_branches, dtype=int)
    bus_of_branch_child = np.full(n_branches, -1, dtype=int)
    parent_branch[0] = -1
    bus_of_branch_child[0] = index_of_customer.get(root, -1)
    from_bus = net.line["from_bus"].to_numpy(dtype=int)
    to_bus = net.line["to_bus"].to_numpy(dtype=int)
    for branch, row in enumerate(line_order, start=1):
        child = next(
            bus
            for bus in (int(from_bus[row]), int(to_bus[row]))
            if branch_of_bus[bus] == branch  # the end this branch feeds
        )
        upstream = int(to_bus[row]) if child == int(from_bus[row]) else int(from_bus[row])
        parent_branch[branch] = branch_of_bus[upstream]
        bus_of_branch_child[branch] = index_of_customer.get(child, -1)
    path_bool, down_bool = ec.tree_matrices(parent_branch, bus_of_branch_child, n_branches)
    path = path_bool.astype(float)
    down = down_bool.astype(float)

    # impedances in ohms referred to LV (s. 7's (rho_l, chi_l) = (r_l, x_l)/V_nom^2).
    v_lv_kv = float(net.trafo["vn_lv_kv"].iloc[0])
    parallel = net.line["parallel"].to_numpy(dtype=float)
    length = net.line["length_km"].to_numpy(dtype=float)
    line_r = net.line["r_ohm_per_km"].to_numpy(dtype=float) * length / parallel
    line_x = net.line["x_ohm_per_km"].to_numpy(dtype=float) * length / parallel
    sn_trafo = float(net.trafo["sn_mva"].iloc[0])
    z_trafo = float(net.trafo["vk_percent"].iloc[0]) / 100.0 * v_lv_kv**2 / sn_trafo
    r_trafo = float(net.trafo["vkr_percent"].iloc[0]) / 100.0 * v_lv_kv**2 / sn_trafo
    x_trafo = math.sqrt(max(z_trafo**2 - r_trafo**2, 0.0))
    r_ohm = np.concatenate([[r_trafo], line_r[line_order]])
    x_ohm = np.concatenate([[x_trafo], line_x[line_order]])
    rho = r_ohm / v_lv_kv**2
    chi = x_ohm / v_lv_kv**2

    # thermal capacities: lines from max_i_ka, the transformer from its rating.
    line_vn = vn_kv[[position_of[int(b)] for b in from_bus]]
    # s. 6's thermal module is I_max,l.sqrt(3).V_nom; `parallel` multiplies a circuit's
    # current capacity exactly as it divides its impedance. s. 2 records parallel = 1 on both
    # of the protocol's networks, where the factor is therefore the identity.
    line_cap = net.line["max_i_ka"].to_numpy(dtype=float) * math.sqrt(3.0) * line_vn * parallel
    cap_mva = np.concatenate([[sn_trafo], line_cap[line_order]])

    built = Network(
        key=key,
        code=code,
        net=net,
        customer_buses=customer_buses,
        lv_positions=lv_positions,
        customer_positions=customer_positions,
        U=U,
        W=W,
        ratings=ratings,
        parent_branch=parent_branch,
        bus_of_branch_child=bus_of_branch_child,
        path=path,
        down=down,
        rho=rho,
        chi=chi,
        r_ohm=r_ohm,
        x_ohm=x_ohm,
        cap_mva=cap_mva,
        vmax=vmax,
        vmin=vmin,
        lv_vmax=lv_vmax,
        v_lv_kv=v_lv_kv,
        # control T reports the AC loading of every branch, so the branch order has to be
        # invertible back to pandapower's own line rows.
        line_rows=np.asarray(line_order, dtype=int),
    )
    check_linear_structure(built)
    return built


def check_linear_structure(built: Network, n_draws: int = 8) -> float:
    """Zero-flow check: `ec.structured_predict` reproduces `ec.lindistflow` on random states.

    Both are the same LinDistFlow model with the network's true rho and chi, one in O(K.L)
    per step and one as a K x K matrix; a mismatch means the tree is wrong.
    """
    S_P, S_Q = ec.lindistflow(built.path, built.rho, built.chi)
    rng = ec.rng_for(built.key, "common", "interior_point")
    K = built.n_customers
    P_bus = rng.normal(0.0, 0.004, size=(n_draws, K))
    Q_bus = rng.normal(0.0, 0.001, size=(n_draws, K))
    direct = P_bus @ S_P.T + Q_bus @ S_Q.T
    structured = ec.structured_predict(0.0, built.path, built.rho, built.chi, P_bus, Q_bus)
    worst = float(np.max(np.abs(direct - structured)))
    if worst > 1e-12:
        raise ValueError(f"{built.key}: structured_predict and lindistflow differ by {worst}")
    return worst


# --- D. profiles (zero solves) -------------------------------------------------------------


@dataclass
class Profiles:
    """The SimBench year, flattened to full-year steps indexed `day.96 + step` (s. 17.2)."""

    n_days: int
    g: np.ndarray  # (T, N) native normalised PV, native MW / rating
    native_pv: np.ndarray  # (T, N) P0 availability r_i.min(1, g_i)
    L: np.ndarray  # (T, n_loads) native load P
    Lq: np.ndarray  # (T, n_loads) native load Q
    f: np.ndarray  # (T,) the unit-weighted mean of min(1, g_i) (s. 17.1)

    @property
    def n_steps(self) -> int:
        return int(self.g.shape[0])

    @property
    def daylight(self) -> np.ndarray:
        return self.f >= DAYLIGHT_F


def profiles_of(built: Network) -> Profiles:
    """`grid.absolute_profiles` -> `grid_study.daily_arrays`, flattened to full-year steps."""
    net = built.net
    tables = grid.absolute_profiles(net)
    for name, elements in (
        ("load_p_mw", net.load.index),
        ("load_q_mvar", net.load.index),
        ("sgen_p_mw", net.sgen.index),
    ):
        if not tables[name].columns.equals(elements):
            raise ValueError(f"{name} profile columns do not match the {name.split('_')[0]} table")
    arrays = grid_study.daily_arrays(tables)
    n_days = int(arrays["sgen_p_mw"].shape[0])

    def flat(name: str) -> np.ndarray:
        return arrays[name].reshape(n_days * grid_study.STEPS, -1).astype(float)

    native_mw = flat("sgen_p_mw")
    ratings = built.ratings
    if (ratings <= 0).any():
        raise ValueError(f"{built.key}: a PV unit has a non-positive rating")
    g = native_mw / ratings
    native_pv = ratings * np.minimum(1.0, g)
    f = np.minimum(1.0, g).mean(axis=1)
    return Profiles(n_days=n_days, g=g, native_pv=native_pv, L=flat("load_p_mw"),
                    Lq=flat("load_q_mvar"), f=f)  # fmt: skip


def steps_of(days) -> np.ndarray:
    """The full-year step indices of whole UTC days, in order."""
    return np.concatenate(
        [np.arange(int(day) * grid_study.STEPS, (int(day) + 1) * grid_study.STEPS) for day in days]
    )


def common_loads(built: Network, profiles: Profiles) -> tuple[np.ndarray, np.ndarray, dict]:
    """The synthetic household loads, one realisation shared by every regime (s. 4, s. 13)."""
    return ec.load_process(profiles.L, profiles.Lq, ec.rng_for(built.key, ec.LOAD_REGIME, "load"))


def regime_pv(
    built: Network, profiles: Profiles, regime: str, train_steps: np.ndarray
) -> tuple[np.ndarray, dict]:
    """One regime's full-year PV availability. L0 uses P1's seeds and parameters (s. 17.2)."""
    label = L0_SEED_REGIME if regime == "L0" else regime
    delta_h, sigma_c = ec.REGIMES[label]
    return ec.pv_regime(
        profiles.g,
        built.ratings,
        delta_h,
        sigma_c,
        ec.rng_for(built.key, label, "pv_orientation"),
        ec.rng_for(built.key, label, "pv_cloud"),
        train_steps,
        profiles.native_pv,
    )


# --- E. the one solve (protocol s. 3, s. 12) -----------------------------------------------


def solve(
    net_state: Network,
    pv: np.ndarray,
    load_p: np.ndarray,
    load_q: np.ndarray,
    ledger_counter: SolveCounter,
) -> dict:
    """One balanced AC power flow; the counter rises on **every attempt**, failures included.

    Returns the customer-bus voltages (float64), the largest `vm - max_vm_pu` over **all** LV
    buses, the largest line loading, the transformer loading, the loading of **every branch**
    in branch order (control T, s. 6) and a converged flag. A failure returns NaN with
    `converged = False`, so it can never be scored as safe (s. 12).
    """
    import pandapower as pp

    net = net_state.net
    net.sgen["p_mw"] = np.asarray(pv, dtype=float)
    net.sgen["q_mvar"] = 0.0  # PV at unity power factor (s. 3)
    net.load["p_mw"] = np.asarray(load_p, dtype=float)
    net.load["q_mvar"] = np.asarray(load_q, dtype=float)
    net.storage["p_mw"] = 0.0  # held at 0 MW in every solve (s. 2)

    ledger_counter.attempts += 1
    try:
        pp.runpp(net, algorithm="nr", numba=False, check_connectivity=False)
    except Exception:  # noqa: BLE001 - any solver failure is a failed solve, never "safe"
        ledger_counter.failures += 1
        return {
            "vm": np.full(net_state.n_customers, np.nan),
            "lv_exceedance": math.nan,
            "line_loading": math.nan,
            "trafo_loading": math.nan,
            "branch_loading": np.full(net_state.n_branches, math.nan),
            "converged": False,
        }

    vm_all = net.res_bus["vm_pu"].to_numpy(dtype=float)
    vm_lv = vm_all[net_state.lv_positions]
    line_loading = net.res_line["loading_percent"].to_numpy(dtype=float)
    trafo_loading = net.res_trafo["loading_percent"].to_numpy(dtype=float)
    return {
        "vm": vm_all[net_state.customer_positions],
        "lv_exceedance": float(np.max(vm_lv - net_state.lv_vmax)),
        "line_loading": float(line_loading.max()),
        "trafo_loading": float(trafo_loading.max()),
        # branch order, branch 0 = the transformer (s. 6's thermal module is written per branch).
        "branch_loading": np.concatenate(
            [[float(trafo_loading.max())], line_loading[net_state.line_rows]]
        ),
        "converged": True,
    }


def solve_steps(
    built: Network,
    steps: np.ndarray,
    pv: np.ndarray,
    ell: np.ndarray,
    q: np.ndarray,
    counter: SolveCounter,
) -> dict:
    """Solve a list of steps with the given full-year injection arrays."""
    n = int(steps.size)
    vm = np.empty((n, built.n_customers))
    lv_exceedance = np.empty(n)
    line_loading = np.empty(n)
    trafo_loading = np.empty(n)
    converged = np.empty(n, dtype=bool)
    for row, step in enumerate(steps):
        out = solve(built, pv[step], ell[step], q[step], counter)
        vm[row] = out["vm"]
        lv_exceedance[row] = out["lv_exceedance"]
        line_loading[row] = out["line_loading"]
        trafo_loading[row] = out["trafo_loading"]
        converged[row] = out["converged"]
    return {
        "vm": vm,
        "lv_exceedance": lv_exceedance,
        "line_loading": line_loading,
        "trafo_loading": trafo_loading,
        "converged": converged,
    }


# --- F. the selection rules as pure functions (protocol s. 5) ------------------------------


def near_candidate(f_day: np.ndarray) -> int:
    """The step of the day with the largest total base availability; earliest on ties (s. 5)."""
    return int(np.argmax(np.asarray(f_day, dtype=float)))


def far_candidate(f_day: np.ndarray, threshold: float = FAR_F) -> int | None:
    """The first daylight step of the day with f(t) >= `threshold`, or None (s. 5)."""
    hits = np.flatnonzero(np.asarray(f_day, dtype=float) >= threshold)
    return int(hits[0]) if hits.size else None


def near_screen(exceedance: np.ndarray, threshold: float = NEAR_SCREEN_PU) -> np.ndarray:
    """The s. 5 voltage screen: keep candidates exceeding the limit by more than +0.001 pu.

    A failed solve (NaN) never passes: no envelope there could be scored.
    """
    arr = np.asarray(exceedance, dtype=float)
    return np.greater(arr, threshold, out=np.zeros(arr.shape, dtype=bool), where=~np.isnan(arr))


def near_set(exceedance: np.ndarray, size: int = SET_SIZE) -> np.ndarray:
    """The screened candidates' indices, the largest exceedance first; earliest on ties.

    The caller passes the screened candidates only. Fewer than `size` survivors returns what
    there is, and the caller applies s. 15.
    """
    arr = np.asarray(exceedance, dtype=float)
    order = np.argsort(-arr, kind="stable")
    return order[:size]


def far_set(
    margin: np.ndarray,
    loading: np.ndarray,
    size: int = SET_SIZE,
    cap: float = FAR_LOADING_CAP,
) -> np.ndarray:
    """The s. 5 far rule: of the candidates with max(line, trafo) <= `cap`, the `size` with
    the most negative customer-bus voltage margin; earliest on ties.

    `margin` is `max_k (vm_k - max_vm_pu,k)`, so "most negative" is furthest from the limit.
    A failed solve (NaN margin or loading) is never eligible.
    """
    arr = np.asarray(margin, dtype=float)
    load = np.asarray(loading, dtype=float)
    eligible = np.flatnonzero(~np.isnan(arr) & ~np.isnan(load) & (load <= cap))
    order = eligible[np.argsort(arr[eligible], kind="stable")]
    return order[:size]


# --- G. the physics stage (protocol s. 4, s. 17) -------------------------------------------


def physics_steps(key: str, regime: str) -> np.ndarray:
    """Training (152-155) plus test (156), plus rural3 P1's extension (132-135) (s. 4)."""
    days = list(TRAIN_DAYS) + list(TEST_DAYS)
    if key == "rural3" and regime == "P1":
        days += list(EXTENSION_DAYS)
    return steps_of(days)


def physics_planned(key: str) -> int:
    """The stage's planned maximum: 480 steps x 4 regimes, plus rural3 P1's 384 (s. 12)."""
    per_regime = (len(TRAIN_DAYS) + len(TEST_DAYS)) * grid_study.STEPS
    extra = len(EXTENSION_DAYS) * grid_study.STEPS if key == "rural3" else 0
    return per_regime * len(REGIME_ORDER) + extra


def _generator_info(pv_info: dict, load_info: dict | None) -> dict:
    out = {
        "delta_h": pv_info["delta_h"],
        "k": pv_info["k"],
        "clip_share": pv_info["clip_share"],
        "clip_share_after_rescale": pv_info["clip_share_after_rescale"],
        "train_mean_native": pv_info["train_mean_native"],
        "train_mean_final": pv_info["train_mean_final"],
    }
    if load_info is None:
        out["loads"] = "native"
    else:
        out["loads"] = "synthetic"
        out["tau_min"] = load_info["tau_min"]
        out["s"] = load_info["s"]
        out["renorm"] = load_info["renorm"]
    return out


def physics_pending(key: str, resume: bool) -> tuple[tuple[str, ...], int]:
    """The regimes `physics` will actually solve, and their planned maximum (s. 12).

    Without `resume` that is every regime, and the planned maximum is `physics_planned`.
    With it, a regime whose artefact **pair** is already on disk is verified rather than
    solved, so it is not in the planned maximum either.
    """
    if not resume:
        return REGIME_ORDER, physics_planned(key)
    pending = tuple(
        regime
        for regime in REGIME_ORDER
        if not (
            (RESULTS / f"physics_{key}_{regime}.json").exists()
            and (OUT / f"physics_{key}_{regime}.npz").exists()
        )
    )
    return pending, sum(int(physics_steps(key, regime).size) for regime in pending)


def verify_stored_physics(
    key: str,
    regime: str,
    steps: np.ndarray,
    pv: np.ndarray,
    P_bus: np.ndarray,
    Q_bus: np.ndarray,
) -> None:
    """`--resume`: the regenerated inputs must equal the stored ones exactly, or nothing runs.

    The generators are seeded per network and regime, so a resumed run regenerates the same
    arrays bit for bit. Any difference means the stored artefact was not produced by this
    code path, and the stage raises here, before it spends a single solve.
    """
    with np.load(OUT / f"physics_{key}_{regime}.npz") as stored:
        for name, value in (("steps", steps.astype(np.int32)), ("pv", pv),
                            ("P_bus", P_bus), ("Q_bus", Q_bus)):  # fmt: skip
            if not np.array_equal(stored[name], value):
                raise ValueError(
                    f"{key} {regime}: the regenerated {name} does not equal the stored "
                    f"runs/physics_{key}_{regime}.npz; refusing to resume"
                )


def run_physics(key: str, resume: bool = False) -> int:
    """The four regimes' training and test physics, one artefact pair per regime."""
    pending, planned = physics_pending(key, resume)
    counter = SolveCounter()
    built = build(key)
    profiles = profiles_of(built)
    train_steps = steps_of(TRAIN_DAYS)
    assert_budget(planned)
    print(f"physics {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}")
    if resume:
        verified = [regime for regime in REGIME_ORDER if regime not in pending]
        print(
            f"  resume: verifying {', '.join(verified) or '(none)'}; "
            f"solving {', '.join(pending) or '(none)'}"
        )

    synthetic_ell, synthetic_q, load_info = common_loads(built, profiles)
    full_year_pv: dict[str, np.ndarray] = {}
    stage_failures = 0
    try:
        for regime in REGIME_ORDER:
            started = time.perf_counter()
            pv, pv_info = regime_pv(built, profiles, regime, train_steps)
            if not np.all(np.isfinite(pv)) or pv.min() < 0.0:
                raise ValueError(f"{key} {regime}: the generator produced invalid PV (s. 15)")
            if np.any(pv > built.ratings + 1e-12):
                raise ValueError(f"{key} {regime}: the generator exceeded a rating (s. 15)")
            if regime in ec.REGIMES:
                full_year_pv[regime] = pv

            native = regime == "L0"
            ell = profiles.L if native else synthetic_ell
            q = profiles.Lq if native else synthetic_q

            steps = physics_steps(key, regime)
            P_bus = pv[steps] @ built.U.T - ell[steps] @ built.W.T
            Q_bus = -q[steps] @ built.W.T

            if regime not in pending:  # --resume: verified, then skipped, at zero solves
                verify_stored_physics(key, regime, steps, pv[steps], P_bus, Q_bus)
                print(
                    f"  {regime}: the stored artefact matches the regenerated inputs, "
                    f"0 solves, {time.perf_counter() - started:.1f} s"
                )
                continue

            out = solve_steps(built, steps, pv, ell, q, counter)
            solves = counter.bank()
            failures = int((~out["converged"]).sum())
            stage_failures += failures

            ec.write_npz_once(
                OUT / f"physics_{key}_{regime}.npz",
                steps=steps.astype(np.int32),
                pv=pv[steps],
                P_bus=P_bus,
                Q_bus=Q_bus,
                vm=out["vm"].astype(np.float32),  # s. 12: float32 voltages
                lv_exceedance=out["lv_exceedance"],
                line_loading=out["line_loading"],
                trafo_loading=out["trafo_loading"],
                converged=out["converged"],
            )

            in_train = np.isin(steps, train_steps)
            daylight_train = profiles.daylight[steps[in_train]]
            diagnostics = ec.excitation_diagnostics(
                pv[steps][in_train], P_bus[in_train], daylight_train
            )
            share = failures / max(solves, 1)
            ec.write_json_once(
                RESULTS / f"physics_{key}_{regime}.json",
                {
                    "stage": "physics",
                    "network": key,
                    "code": built.code,
                    "regime": regime,
                    "solves": solves,
                    "failures": failures,
                    "failure_share": share,
                    "steps": int(steps.size),
                    "train_steps": int(in_train.sum()),
                    "daylight_train_steps": int(daylight_train.sum()),
                    "sigma_v": SIGMA_V,
                    "generator": _generator_info(pv_info, None if native else load_info),
                    "excitation": {
                        "pv_corr_mean": diagnostics["pv_corr_mean"],
                        "pv_corr_min": diagnostics["pv_corr_min"],
                        "effective_rank": diagnostics["effective_rank"],
                        "condition_number": diagnostics["condition_number"],
                        "singular_values": diagnostics["singular_values"],
                        "independent_variance": diagnostics["independent_variance"],
                    },
                    "runtime_s": time.perf_counter() - started,
                    "protocol_sha256": ec.PROTOCOL_SHA256,
                },
            )
            print(
                f"  {regime}: {solves} solves, {failures} failures, "
                f"corr mean {diagnostics['pv_corr_mean']:.4f} min "
                f"{diagnostics['pv_corr_min']:.4f}, eff rank "
                f"{diagnostics['effective_rank']:.3f}, cond "
                f"{diagnostics['condition_number']:.3e}, "
                f"{time.perf_counter() - started:.1f} s"
            )
            if stage_failures > FAILURE_SHARE * counter.attempts:
                break
    except BaseException as error:
        abort_record("physics", key, counter, error)
        raise

    evaluable = stage_failures <= FAILURE_SHARE * counter.attempts
    control_c = ec.marginal_check(full_year_pv, train_steps, profiles.daylight)
    ec.write_json_once(
        RESULTS / f"marginals_{key}.json",
        {
            "stage": "physics_marginals",
            "network": key,
            "solves": 0,  # control C is a zero-solve check on the generated arrays
            "stage_solves": counter.attempts,
            "stage_failures": stage_failures,
            "stage_failure_share": stage_failures / max(counter.attempts, 1),
            "evaluable": evaluable,
            "verdict": "OK" if evaluable else "NOT EVALUABLE",
            "control_c": control_c,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(
        f"  control C: {'pass' if control_c['passed'] else 'FAIL'}; "
        f"stage {counter.attempts} solves, {stage_failures} failures"
    )
    for regime, comparison in control_c["against_P1"].items():
        print(
            f"    {regime} vs P1: worst |mean ratio - 1| "
            f"{float(np.max(np.abs(np.asarray(comparison['mean_ratio']) - 1.0))):.5f}, "
            f"median |P95 ratio - 1| "
            f"{float(np.median(np.abs(np.asarray(comparison['p95_ratio']) - 1.0))):.5f}"
        )
    if not evaluable:
        print(f"PHYSICS NOT EVALUABLE (s. 12): {stage_failures}/{counter.attempts} failed")
        return 1
    return 0


# --- H. the selection stage (protocol s. 5, s. 17) -----------------------------------------


def selection_planned() -> int:
    """40 near candidates + 40 far candidates + 20 e = 0 vertices (s. 12)."""
    return 2 * len(DEPLOY_DAYS) + 2 * SET_SIZE


def _candidate_record(built: Network, kind: str, day: int, step: int, f: float, out: dict) -> dict:
    """One candidate's record, with every field s. 17.7 lists."""
    vm = np.asarray(out["vm"], dtype=float)
    converged = bool(out["converged"])
    return {
        "kind": kind,
        "day": int(day),
        "step": int(step),
        "f": float(f),
        "customer_exceedance": float(np.max(vm - built.vmax)) if converged else math.nan,
        "lv_exceedance": out["lv_exceedance"],
        "line_loading": out["line_loading"],
        "trafo_loading": out["trafo_loading"],
        "converged": converged,
    }


def run_select(key: str) -> int:
    """The deployment conditions of s. 5 and the method-independent e = 0 vertex."""
    planned = selection_planned()
    counter = SolveCounter()
    built = build(key)
    profiles = profiles_of(built)
    assert_budget(planned)
    print(f"select {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}")

    # the common synthetic loads, regenerated from the same seed as `physics`'s.
    ell, q, _ = common_loads(built, profiles)
    checked = assert_loads_match_physics(built, ell, q)
    print(f"  common loads: {'identical to physics ' + checked if checked else 'no physics npz'}")

    candidates: list[dict] = []
    skipped_far_days: list[int] = []
    no_action_vm: dict[int, np.ndarray] = {}
    try:
        for kind in ("near", "far"):
            for day in DEPLOY_DAYS:
                day_steps = steps_of([day])
                f_day = profiles.f[day_steps]
                local = near_candidate(f_day) if kind == "near" else far_candidate(f_day)
                if local is None:
                    # An overcast day whose f(t) never reaches 20 % of rating yields no far
                    # candidate (s. 5 defines one per day where the step exists; it asks for
                    # no fallback). The day is recorded and the far set is drawn from the
                    # rest, so the stage spends fewer than 40 far solves.
                    skipped_far_days.append(int(day))
                    continue
                step = int(day_steps[local])
                availability = built.ratings * float(profiles.f[step])
                out = solve(built, availability, ell[step], q[step], counter)
                no_action_vm[step] = np.asarray(out["vm"], dtype=float)
                record = _candidate_record(built, kind, day, step, profiles.f[step], out)
                record["availability_mw"] = float(availability.sum())
                candidates.append(record)

        near = [c for c in candidates if c["kind"] == "near"]
        far = [c for c in candidates if c["kind"] == "far"]
        passed = near_screen(np.array([c["customer_exceedance"] for c in near]))
        for record, flag in zip(near, passed, strict=True):
            record["passed_near_screen"] = bool(flag)
        survivors = [c for c, flag in zip(near, passed, strict=True) if flag]
        n_survivors = len(survivors)
        near_evaluable = n_survivors >= SET_SIZE
        chosen_near = [
            survivors[i] for i in near_set(np.array([c["customer_exceedance"] for c in survivors]))
        ]

        far_margin = np.array([c["customer_exceedance"] for c in far])
        far_loading = np.array([max(c["line_loading"], c["trafo_loading"]) for c in far])
        chosen_far = [far[i] for i in far_set(far_margin, far_loading)]
        far_evaluable = len(chosen_far) >= SET_SIZE

        selected = chosen_near + chosen_far
        vertices, arrays = _zero_vertex(built, profiles, ell, q, selected, no_action_vm, counter)
        solves = counter.bank()
    except BaseException as error:
        abort_record(
            "select",
            key,
            counter,
            error,
            {"candidates": candidates, "skipped_far_days": skipped_far_days},
        )
        raise

    ec.write_npz_once(OUT / f"selection_{key}.npz", **arrays)
    ec.write_json_once(
        RESULTS / f"selection_{key}.json",
        {
            "stage": "select",
            "network": key,
            "code": built.code,
            "solves": solves,
            "failures": counter.failures,
            "deploy_days": list(DEPLOY_DAYS),
            "skipped_far_days": skipped_far_days,
            "n_far_candidates": len(far),
            "far_evaluable": far_evaluable,
            "candidates": candidates,
            "n_near_survivors": n_survivors,
            "near_evaluable": near_evaluable,
            "near_conditions": chosen_near,
            "far_conditions": chosen_far,
            "zero_vertex": vertices,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(f"  candidates: {len(candidates)} solved, {counter.failures} failures")
    if skipped_far_days:
        print(f"  far days with no step at f >= {FAR_F}: {skipped_far_days}")
    print(f"  far candidates: {len(far)}, far_evaluable {far_evaluable}")
    print(f"  near survivors: {n_survivors}/{len(DEPLOY_DAYS)}, near_evaluable {near_evaluable}")
    for record in chosen_near:
        print(
            f"    near day {record['day']} step {record['step']} f {record['f']:.3f} "
            f"exceedance {record['customer_exceedance']:+.5f} line "
            f"{record['line_loading']:.1f} % trafo {record['trafo_loading']:.1f} %"
        )
    for record in chosen_far:
        print(
            f"    far  day {record['day']} step {record['step']} f {record['f']:.3f} "
            f"margin {record['customer_exceedance']:+.5f} line "
            f"{record['line_loading']:.1f} % trafo {record['trafo_loading']:.1f} %"
        )
    unsafe = [v for v in vertices if v["unsafe_voltage"] or v["unsafe_thermal"]]
    print(f"  e = 0 vertex: {len(vertices)} solved, {len(unsafe)} unsafe")
    if not near_evaluable:
        print(f"NEAR SET NOT EVALUABLE (s. 15): {n_survivors} survivors of {SET_SIZE} needed")
        return 1
    return 0


def assert_loads_match_physics(
    built: Network, ell: np.ndarray, q: np.ndarray, out: Path | None = None
) -> str:
    """s. 5: the deployment loads are `physics`'s realisation, regenerated from the same seed.

    The stored `pv`, `P_bus` and `Q_bus` pin the load side exactly: W.l = U.pv - P_bus and
    W.q = -Q_bus. Checking those is checking the realisation without storing the loads twice.
    Returns the regime checked against, or "" when `physics` has not run on this network.
    """
    directory = OUT if out is None else Path(out)
    for regime in REGIME_ORDER:
        if regime == "L0":
            continue  # L0's physics used native loads; s. 5's pairing is on the synthetic ones
        path = directory / f"physics_{built.key}_{regime}.npz"
        if not path.exists():
            continue
        with np.load(path) as stored:
            steps = stored["steps"].astype(int)
            np.testing.assert_allclose(
                stored["pv"] @ built.U.T - stored["P_bus"], ell[steps] @ built.W.T,
                rtol=0, atol=1e-12,
            )  # fmt: skip
            np.testing.assert_allclose(-stored["Q_bus"], q[steps] @ built.W.T, rtol=0, atol=1e-12)
        return regime
    return ""


def _zero_vertex(
    built: Network,
    profiles: Profiles,
    ell: np.ndarray,
    q: np.ndarray,
    selected: list[dict],
    no_action_vm: dict[int, np.ndarray],
    counter: SolveCounter,
) -> tuple[list[dict], dict]:
    """The e = 0 vertex of every selected condition, and the npz arrays of s. 17.7."""
    n = len(selected)
    K, N = built.n_customers, built.n_units
    arrays = {
        "step": np.empty(n, dtype=np.int32),
        "day": np.empty(n, dtype=np.int32),
        "kind": np.array([c["kind"] for c in selected]),
        "a": np.empty((n, N)),
        "ell": np.empty((n, built.W.shape[1])),
        "q": np.empty((n, built.W.shape[1])),
        "P_bus": np.empty((n, K)),
        "Q_bus": np.empty((n, K)),
        "vm_no_action": np.empty((n, K)),  # Method A's offset (s. 7), float64
    }
    vertices: list[dict] = []
    for row, condition in enumerate(selected):
        step = int(condition["step"])
        availability = built.ratings * float(profiles.f[step])
        arrays["step"][row] = step
        arrays["day"][row] = int(condition["day"])
        arrays["a"][row] = availability
        arrays["ell"][row] = ell[step]
        arrays["q"][row] = q[step]
        arrays["P_bus"][row] = built.U @ availability - built.W @ ell[step]
        arrays["Q_bus"][row] = -built.W @ q[step]
        arrays["vm_no_action"][row] = no_action_vm[step]  # Method A's offset (s. 7)

        out = solve(built, np.zeros(N), ell[step], q[step], counter)
        vm = np.asarray(out["vm"], dtype=float)
        converged = bool(out["converged"])
        under = float(np.max(built.vmin - vm)) if converged else math.nan
        loading = max(out["line_loading"], out["trafo_loading"]) if converged else math.nan
        vertices.append(
            {
                "kind": condition["kind"],
                "day": int(condition["day"]),
                "step": step,
                # the protocol records min(vm) - min_vm_pu; `undervoltage_pu` is its negative
                "min_vm_margin_pu": -under if converged else math.nan,
                "undervoltage_pu": under,
                "line_loading": out["line_loading"],
                "trafo_loading": out["trafo_loading"],
                "converged": converged,
                # a failed solve is never scored as safe (s. 12)
                "unsafe_voltage": (not converged) or under > VOLTAGE_UNSAFE_PU,
                "unsafe_thermal": (not converged) or loading - 100.0 > THERMAL_UNSAFE_PCT,
            }
        )
    return vertices, arrays


# --- I. reading `select` and `physics` back (zero solves) ----------------------------------


@dataclass
class Selection:
    """`select`'s artefact pair read back: the chosen conditions and their no-action solves.

    `conditions` is the near list followed by the far list, in the same order as the npz
    rows and as `select`'s `zero_vertex`. Each entry is the candidate record itself, so it
    carries the no-action AC read-outs that s. 6's scoring shortcut reuses.
    """

    key: str
    near_evaluable: bool
    far_evaluable: bool
    conditions: list[dict]
    a: np.ndarray  # (n, N) availability r_i.f(t) at the condition
    ell: np.ndarray  # (n, n_loads) the condition's load P
    q: np.ndarray  # (n, n_loads) the condition's load Q
    P_bus_no_action: np.ndarray  # (n, K) U.a + P_fix
    Q_bus: np.ndarray  # (n, K) -W.q
    vm_no_action: np.ndarray  # (n, K) Method A's offset state (s. 7)

    @property
    def n_conditions(self) -> int:
        return len(self.conditions)

    @property
    def near_rows(self) -> list[int]:
        return [i for i, c in enumerate(self.conditions) if c["kind"] == "near"]


def load_selection(key: str) -> Selection:
    """Read `selection_<key>` back. Raises `FileNotFoundError` if `select` has not run."""
    payload_path = RESULTS / f"selection_{key}.json"
    array_path = OUT / f"selection_{key}.npz"
    for path in (payload_path, array_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing: run `select --network {key}` first")
    payload = json.loads(payload_path.read_text())
    conditions = list(payload["near_conditions"]) + list(payload["far_conditions"])
    with np.load(array_path, allow_pickle=False) as stored:
        kinds = [str(k) for k in stored["kind"]]
        steps = stored["step"].astype(int)
        if kinds != [c["kind"] for c in conditions] or list(steps) != [
            int(c["step"]) for c in conditions
        ]:
            raise ValueError(f"selection_{key}: the npz rows do not match the chosen conditions")
        return Selection(
            key=key,
            near_evaluable=bool(payload["near_evaluable"]),
            far_evaluable=bool(payload["far_evaluable"]),
            conditions=conditions,
            a=stored["a"],
            ell=stored["ell"],
            q=stored["q"],
            P_bus_no_action=stored["P_bus"],
            Q_bus=stored["Q_bus"],
            vm_no_action=stored["vm_no_action"],
        )


def load_physics(key: str) -> dict[str, dict]:
    """Every regime's `physics` artefact pair. Raises unless all four regimes are present."""
    out: dict[str, dict] = {}
    for regime in REGIME_ORDER:
        payload_path = RESULTS / f"physics_{key}_{regime}.json"
        array_path = OUT / f"physics_{key}_{regime}.npz"
        for path in (payload_path, array_path):
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} is missing: run `physics --network {key}` first (all four regimes)"
                )
        with np.load(array_path, allow_pickle=False) as stored:
            out[regime] = {
                "steps": stored["steps"].astype(int),
                "P_bus": stored["P_bus"].astype(float),
                "Q_bus": stored["Q_bus"].astype(float),
                "vm": stored["vm"].astype(float),  # stored float32 (s. 12), widened to fit
                "converged": stored["converged"],
            }
    return out


# --- J. the envelope stage (protocol s. 6, s. 7, s. 17) ------------------------------------


def envelopes_planned(n_conditions: int) -> int:
    """s. 12: per condition, 7 methods x (3 regimes x R = 2 plus L0 x R = 1) plus B0, A, A'.

    That is 52 per condition: 624 at semiurb5's 12 conditions, 1,040 at the registered 20.
    """
    per_condition = len(DATA_METHODS) * len(ENVELOPE_CELLS) + len(FIXED_METHODS)
    return per_condition * int(n_conditions)


def noisy_voltage(
    key: str,
    regime: str,
    replicate: int,
    vm_true: np.ndarray,
    steps: np.ndarray,
    n_year: int,
    sigma: float | None = None,
) -> np.ndarray:
    """s. 17.3: z ~ N(0, 1) over **every step of the year** and every customer bus.

    Drawing the whole year and then indexing by absolute step is what makes the realisation
    independent of which steps a stage happens to need, and gives every sigma_v level the
    same z (common random numbers across control I). `sigma` defaults to the primary
    `SIGMA_V`; control I passes its two levels, and gets the very same z for both.
    """
    vm = np.asarray(vm_true, dtype=float)
    level = SIGMA_V if sigma is None else float(sigma)
    z = ec.rng_for(key, regime, "noise", replicate).standard_normal((int(n_year), vm.shape[1]))
    return vm + level * z[np.asarray(steps, dtype=int)]


@dataclass
class Cell:
    """Every fit and read-out of one (regime, replicate) training cell (s. 7)."""

    regime: str
    replicate: int
    X: np.ndarray  # (T, K) the training design, P_bus over days 152-155
    Y: np.ndarray  # (T, K) the noisy training voltages
    Q_train: np.ndarray  # (T, K)
    lam: float
    lam_m: float
    b1: ec.OLSFit
    b2: ec.RidgeFit
    b2m: ec.RidgeFit
    margin: np.ndarray  # (K,) the 0.95 split-conformal margin on day 155
    margin_insample: np.ndarray  # (K,) the 2.sqrt(sigma2) diagnostic of the B2 fit
    b3: tuple  # (c, rho, chi, residual_norm)
    sd: np.ndarray  # (K, p) the Gupta-style per-coefficient sd
    gamma: int
    radius: ec.RadiusResult
    minv: np.ndarray  # (p, p) inv(M) of B2's fit
    readouts: dict


def fit_cell(built: Network, regime: str, replicate: int, rows: dict, n_year: int) -> Cell:
    """The five fits and the zero-solve read-outs of one (regime, replicate) cell (s. 7)."""
    steps = rows["steps"]
    train_steps = steps_of(TRAIN_DAYS)
    test_steps = steps_of(TEST_DAYS)
    in_train = np.isin(steps, train_steps)
    in_test = np.isin(steps, test_steps)
    if not in_train.any() or not in_test.any():
        raise ValueError(f"physics {built.key} {regime}: no training or test steps stored")

    V = noisy_voltage(built.key, regime, replicate, rows["vm"], steps, n_year)
    X = rows["P_bus"][in_train]
    Y = V[in_train]
    Q_train = rows["Q_bus"][in_train]
    day = steps[in_train] // grid_study.STEPS

    b1 = ec.fit_ols(X, Y)
    lam, _ = ec.cv_lambda(X, Y, day)
    b2 = ec.fit_ridge(X, Y, lam)

    # B2m: ridge on 152-154, the margin on the held-out 155 (s. 7, s. 13).
    conformal_day = int(TRAIN_DAYS[-1])
    early = day != conformal_day
    held = ~early
    lam_m, _ = ec.cv_lambda(X[early], Y[early], day[early])
    b2m = ec.fit_ridge(X[early], Y[early], lam_m)
    resid = Y[held] - (b2m.intercepts + X[held] @ b2m.slopes)
    margin = ec.conformal_margin(resid)
    margin_insample = 2.0 * np.sqrt(b2.sigma2)

    b3 = ec.fit_structured_nnls(built.path, X, Q_train, Y)
    sd = ec.ridge_box_sd(X, b2.M, b2.sigma2)
    gamma = math.ceil(math.sqrt(built.n_customers + 1))
    refit_rng = ec.rng_for(built.key, regime, "radius_refit", replicate)
    radius = ec.bootstrap_radius(X, Y, lam, refit_rng)
    # the radius must come from B2's own fit, or B4's ellipsoid would be centred elsewhere.
    np.testing.assert_allclose(radius.fit.slopes, b2.slopes, rtol=0, atol=0)
    np.testing.assert_allclose(radius.fit.intercepts, b2.intercepts, rtol=0, atol=0)
    np.testing.assert_allclose(radius.fit.M, b2.M, rtol=0, atol=0)
    minv = np.linalg.inv(b2.M)

    # --- zero-solve read-outs (s. 9 H2, s. 10 NC4) ---
    X_test = rows["P_bus"][in_test]
    Q_test = rows["Q_bus"][in_test]
    vm_test = rows["vm"][in_test]

    def mae(pred: np.ndarray) -> float:
        return float(np.mean(np.abs(pred - vm_test)))

    shuffled = ec.shuffled_fit(X, Y, lam, ec.rng_for(built.key, regime, "shuffle", replicate))
    b2_norm = float(np.linalg.norm(b2.slopes))
    readouts = {
        "regime": regime,
        "replicate": replicate,
        "lam": float(lam),
        "lam_m": float(lam_m),
        "ols_rank": int(b1.rank),
        "ridge_df": float(b2.df),
        "gamma": int(gamma),
        "test_mae": {
            "OLS": mae(b1.intercepts + X_test @ b1.slopes),
            "ridge": mae(b2.intercepts + X_test @ b2.slopes),
            "NNLS": mae(ec.structured_predict(b3[0], built.path, b3[1], b3[2], X_test, Q_test)),
        },
        "control_k": {
            "test_mae": mae(shuffled.intercepts + X_test @ shuffled.slopes),
            "slope_norm": float(np.linalg.norm(shuffled.slopes)),
            "b2_slope_norm": b2_norm,
            "slope_norm_ratio": float(np.linalg.norm(shuffled.slopes) / max(b2_norm, 1e-300)),
        },
        "margin": {
            "conformal_median": float(np.median(margin)),
            "conformal_max": float(np.max(margin)),
            "insample_median": float(np.median(margin_insample)),
            "insample_max": float(np.max(margin_insample)),
        },
        "radius": {
            "c": float(radius.c),
            "r2_median": float(np.median(radius.r2)),
            "r2_max": float(np.max(radius.r2)),
            "f_radius_median": float(np.median(radius.f_radius)),
        },
        "b3_residual_norm": float(b3[3]),
        "nnls_structured_rho_nonzero": int(np.count_nonzero(b3[1])),
    }
    return Cell(
        regime=regime, replicate=replicate, X=X, Y=Y, Q_train=Q_train, lam=float(lam),
        lam_m=float(lam_m), b1=b1, b2=b2, b2m=b2m, margin=margin,
        margin_insample=margin_insample, b3=b3, sd=sd, gamma=int(gamma), radius=radius,
        minv=minv, readouts=readouts,
    )  # fmt: skip


def _nominal_max(alpha: np.ndarray, S: np.ndarray, e: np.ndarray) -> float:
    """The predicted maximum corner voltage of a nominal affine model (s. 9 H2)."""
    return float(np.max(np.asarray(alpha, dtype=float) + np.asarray(S, dtype=float) @ e))


def method_envelope(
    method: str,
    cell: Cell,
    built: Network,
    a: np.ndarray,
    P_fix: np.ndarray,
    Q_fix: np.ndarray,
) -> dict:
    """One deployable method's envelope at one condition (s. 7), with its LP read-outs.

    **`predicted_corner_vm` is each method's own nominal model** evaluated at its own corner
    (s. 9 H2): OLS for B1, B2m's 152-154 ridge *without* its margin for B2m, the structured
    fit for B3, and B2's ridge for B2, B2p, B4box and B4 - the two robust arms are read out
    at B2's point prediction, not at their robust bound, which is what s. 9 H2 asks for.
    """
    nominal = el.affine_from_centred(cell.b2.ybar, cell.b2.slopes, cell.b2.mu, built.U, P_fix)
    if method == "B1":
        alpha, S = el.affine_from_centred(cell.b1.ybar, cell.b1.slopes, cell.b1.mu, built.U, P_fix)
        out = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
    elif method == "B2":
        alpha, S = nominal
        out = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
    elif method == "B2m":
        alpha, S = el.affine_from_centred(
            cell.b2m.ybar, cell.b2m.slopes, cell.b2m.mu, built.U, P_fix
        )
        out = el.voltage_envelope(alpha, S, built.vmax, cell.margin, a)
    elif method == "B2p":
        alpha, S = nominal
        out = el.proportional_envelope(alpha, S, built.vmax, 0.0, a)
        # the scalar decision has one binding row rather than an active set; the bus that
        # sets theta is its (V) read-out, so s. 9's binding diagnostic is comparable.
        binding = int(out["binding"])
        out["active_v"] = np.array([binding]) if binding >= 0 else np.zeros(0, dtype=int)
    elif method == "B3":
        c, rho, chi, _ = cell.b3
        alpha, S = el.affine_from_structured(c, built.path, rho, chi, built.U, P_fix, Q_fix)
        out = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
    elif method == "B4box":
        alpha, S = nominal
        out = el.box_envelope(
            cell.b2.ybar, cell.b2.slopes, cell.sd, cell.b2.mu, built.U, P_fix,
            built.vmax, a, cell.gamma, K_SIGMA,
        )  # fmt: skip
    elif method == "B4":
        alpha, S = nominal
        out = el.ellipsoid_envelope(
            cell.b2.ybar, cell.b2.slopes, cell.minv, cell.radius.r2, cell.b2.mu, built.U,
            P_fix, built.vmax, a,
        )  # fmt: skip
    else:
        raise ValueError(f"unknown method {method!r}")
    out["predicted_corner_vm"] = _nominal_max(alpha, S, out["e"])
    return out


def fixed_envelope(
    method: str,
    built: Network,
    sel: Selection,
    row: int,
    P_fix: np.ndarray,
    Q_fix: np.ndarray,
    aprime_intercept: np.ndarray,
) -> dict:
    """B0, Method A and Method A' at one condition: regime-independent, one envelope each."""
    a = sel.a[row]
    if method == "B0":
        # s. 7: a real pre-existing engineering policy; it uses no network data and so has
        # no voltage model, hence no predicted corner voltage.
        e = np.minimum(a, B0_SHARE * built.ratings)
        return {
            "e": e,
            "total": float(e.sum()),
            "status": el.OK,
            "stage2_l1_move": 0.0,
            "active_v": np.zeros(0, dtype=int),
            "predicted_corner_vm": math.nan,
        }
    if method == "A":
        c = ec.offset_from_state(
            sel.vm_no_action[row], 0.0, built.path, built.rho, built.chi,
            sel.P_bus_no_action[row], sel.Q_bus[row],
        )  # fmt: skip
    elif method == "Aprime":
        c = aprime_intercept
    else:
        raise ValueError(f"unknown fixed method {method!r}")
    alpha, S = el.affine_from_structured(c, built.path, built.rho, built.chi, built.U, P_fix, Q_fix)
    out = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
    out["predicted_corner_vm"] = _nominal_max(alpha, S, out["e"])
    return out


def score_corner(
    built: Network, sel: Selection, row: int, e: np.ndarray, counter: SolveCounter
) -> dict:
    """AC-score one envelope at its corner (s. 6, s. 12).

    **The shortcut of s. 6:** an envelope equal to a within 1e-12 MW is scored by the
    no-action selection solve already made, and costs no new solve. A failed flow is
    recorded as failed and counted unsafe in every rate; it is never scored as safe.

    `branch_loading` is the per-branch AC loading control T reports. The selection record
    stores only the two maxima, so a shortcut-scored corner has **no** per-branch read-out
    and returns NaN; control T counts those corners and leaves them out of its approximation
    error rather than filling them in.
    """
    a = sel.a[row]
    e = np.asarray(e, dtype=float).ravel()
    if float(np.max(np.abs(e - a))) <= SHORTCUT_TOL:
        condition = sel.conditions[row]
        converged = bool(condition["converged"])
        exceedance = float(condition["customer_exceedance"])
        return {
            "shortcut": True,
            "converged": converged,
            "max_exceedance": exceedance,
            "unsafe": (not converged) or exceedance > VOLTAGE_UNSAFE_PU,
            "lv_exceedance": condition["lv_exceedance"],
            "line_loading": condition["line_loading"],
            "trafo_loading": condition["trafo_loading"],
            "branch_loading": np.full(built.n_branches, math.nan),
            "vm": sel.vm_no_action[row],
        }
    out = solve(built, e, sel.ell[row], sel.q[row], counter)
    converged = bool(out["converged"])
    vm = np.asarray(out["vm"], dtype=float)
    exceedance = float(np.max(vm - built.vmax)) if converged else math.nan
    return {
        "shortcut": False,
        "converged": converged,
        "max_exceedance": exceedance,
        "unsafe": (not converged) or exceedance > VOLTAGE_UNSAFE_PU,
        "lv_exceedance": out["lv_exceedance"],
        "line_loading": out["line_loading"],
        "trafo_loading": out["trafo_loading"],
        "branch_loading": np.asarray(
            out.get("branch_loading", np.full(built.n_branches, math.nan)), dtype=float
        ),
        "vm": vm,
    }


def _envelope_record(
    method: str, regime: str, replicate: int, row: int, condition: dict,
    out: dict, score: dict, label: str,
) -> dict:  # fmt: skip
    """One (method, regime, replicate, condition) record: every field s. 6 and s. 9 ask for."""
    e = np.asarray(out["e"], dtype=float)
    record = {
        "method": method,
        "regime": regime,
        "replicate": replicate,
        "row": int(row),
        "kind": condition["kind"],
        "day": int(condition["day"]),
        "step": int(condition["step"]),
        "label": label,
        "total_e": float(out["total"]),
        "status": out["status"],
        "stage2_l1_move": float(out.get("stage2_l1_move", 0.0)),
        "n_active_v": int(np.asarray(out["active_v"]).size),
        "active_v": [int(k) for k in np.asarray(out["active_v"]).ravel()],
        "predicted_corner_vm": float(out["predicted_corner_vm"]),
        "e_equals_a": bool(score["shortcut"]),
        "max_exceedance": score["max_exceedance"],
        "unsafe": bool(score["unsafe"]),
        "lv_exceedance": score["lv_exceedance"],
        "line_loading": score["line_loading"],
        "trafo_loading": score["trafo_loading"],
        "converged": bool(score["converged"]),
        "e_min": float(e.min()) if e.size else math.nan,
        "e_max": float(e.max()) if e.size else math.nan,
    }
    for flag in ("restored", "gap", "gap_flag", "n_rounds", "n_cuts", "max_g", "reason"):
        if flag in out:
            value = out[flag]
            record[flag] = value if isinstance(value, (str, bool)) else float(value)
    for flag in ("theta", "binding"):  # B2p's scalar decision
        if flag in out:
            record[flag] = float(out[flag])
    if "negative_headroom" in out:
        record["n_negative_headroom"] = int(np.asarray(out["negative_headroom"]).size)
    return record


def run_envelopes(key: str) -> int:
    """Every method's envelope on `select`'s conditions, AC-scored at its corner (s. 6, s. 7)."""
    built = build(key)
    profiles = profiles_of(built)
    sel = load_selection(key)
    physics = load_physics(key)
    planned = envelopes_planned(sel.n_conditions)
    counter = SolveCounter()
    assert_budget(planned)
    label = EVALUABLE_LABEL if sel.near_evaluable else DESCRIPTIVE_LABEL
    print(
        f"envelopes {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}; "
        f"{sel.n_conditions} conditions ({len(sel.near_rows)} near), "
        f"near_evaluable {sel.near_evaluable}"
    )
    if not sel.near_evaluable:
        print(f"  every record is labelled: {label}")

    # P_bus(e) = U.e + P_fix with P_fix = -W.l, and Q is fixed at the condition (s. 6, s. 7).
    P_fix = -(sel.ell @ built.W.T)
    Q_fix = -(sel.q @ built.W.T)
    np.testing.assert_allclose(Q_fix, sel.Q_bus, rtol=0, atol=1e-12)
    np.testing.assert_allclose(P_fix + sel.a @ built.U.T, sel.P_bus_no_action, rtol=0, atol=1e-12)

    records: list[dict] = []
    e_rows: list[np.ndarray] = []
    vm_rows: list[np.ndarray] = []
    readouts: list[dict] = []
    aprime_intercept: np.ndarray | None = None
    started_stage = time.perf_counter()
    try:
        for regime, replicate in ENVELOPE_CELLS:
            started = time.perf_counter()
            cell = fit_cell(built, regime, replicate, physics[regime], profiles.n_steps)
            if (regime, replicate) == APRIME_CELL:
                # s. 17.5: A-prime's intercept is the training-step mean residual of noisy V.
                aprime_intercept = ec.training_intercept(
                    cell.Y, built.path, built.rho, built.chi, cell.X, cell.Q_train
                )
            cell.readouts["corner_distance"] = [
                ec.corner_distance(cell.X, sel.P_bus_no_action[row])
                for row in range(sel.n_conditions)
            ]
            for row in range(sel.n_conditions):
                for method in DATA_METHODS:
                    out = method_envelope(method, cell, built, sel.a[row], P_fix[row], Q_fix[row])
                    score = score_corner(built, sel, row, out["e"], counter)
                    records.append(
                        _envelope_record(
                            method, regime, replicate, row, sel.conditions[row], out, score, label
                        )
                    )
                    e_rows.append(np.asarray(out["e"], dtype=float))
                    vm_rows.append(np.asarray(score["vm"], dtype=float))
            cell.readouts["runtime_s"] = time.perf_counter() - started
            readouts.append(cell.readouts)
            print(
                f"  {regime} r{replicate}: lam {cell.lam:.4g}, lam_m {cell.lam_m:.4g}, "
                f"test MAE ridge {cell.readouts['test_mae']['ridge']:.3e}, "
                f"{counter.attempts} solves so far, {time.perf_counter() - started:.1f} s"
            )

        if aprime_intercept is None:  # unreachable while APRIME_CELL is in ENVELOPE_CELLS
            raise RuntimeError(f"A-prime's cell {APRIME_CELL} was never fitted")
        for row in range(sel.n_conditions):
            for method in FIXED_METHODS:
                out = fixed_envelope(
                    method, built, sel, row, P_fix[row], Q_fix[row], aprime_intercept
                )
                score = score_corner(built, sel, row, out["e"], counter)
                records.append(
                    _envelope_record(method, "-", -1, row, sel.conditions[row], out, score, label)
                )
                e_rows.append(np.asarray(out["e"], dtype=float))
                vm_rows.append(np.asarray(score["vm"], dtype=float))
        solves = counter.bank()
    except BaseException as error:
        abort_record("envelopes", key, counter, error, {"records": records})
        raise

    failures = counter.failures
    evaluable = failures <= FAILURE_SHARE * max(counter.attempts, 1)
    shortcuts = sum(1 for r in records if r["e_equals_a"])
    ec.write_npz_once(
        OUT / f"envelopes_{key}.npz",
        method=np.array([r["method"] for r in records]),
        regime=np.array([r["regime"] for r in records]),
        replicate=np.array([r["replicate"] for r in records], dtype=np.int32),
        row=np.array([r["row"] for r in records], dtype=np.int32),
        step=np.array([r["step"] for r in records], dtype=np.int32),
        kind=np.array([r["kind"] for r in records]),
        e=np.asarray(e_rows, dtype=float),
        vm_corner=np.asarray(vm_rows, dtype=np.float32),  # s. 12: float32 voltages
    )
    ec.write_json_once(
        RESULTS / f"envelopes_{key}.json",
        {
            "stage": "envelopes",
            "network": key,
            "code": built.code,
            "solves": solves,
            "failures": failures,
            "failure_share": failures / max(counter.attempts, 1),
            "evaluable": evaluable,
            "verdict": "OK" if evaluable else "NOT EVALUABLE",
            "planned_max": planned,
            "shortcut_records": shortcuts,
            "near_evaluable": sel.near_evaluable,
            "far_evaluable": sel.far_evaluable,
            "label": label,
            "n_conditions": sel.n_conditions,
            "n_near": len(sel.near_rows),
            "methods": list(DATA_METHODS) + list(FIXED_METHODS),
            "cells": list(ENVELOPE_CELLS),
            "sigma_v": SIGMA_V,
            "k_sigma": K_SIGMA,
            "fits": readouts,
            "records": records,
            "runtime_s": time.perf_counter() - started_stage,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(
        f"  {len(records)} records, {solves} solves ({shortcuts} reused the no-action solve), "
        f"{failures} failures, {time.perf_counter() - started_stage:.1f} s"
    )
    if not evaluable:
        print(f"ENVELOPES NOT EVALUABLE (s. 12): {failures}/{counter.attempts} failed")
        return 1
    return 0


# --- K. the AC oracle B5 (protocol s. 7, s. 9) ---------------------------------------------


def oracle_planned(n_near: int) -> int:
    """s. 12: at most 6 sequential LPs plus 8 bisection solves per near condition."""
    return el.OracleState().budget * int(n_near)


def run_oracle(key: str) -> int:
    """B5 on the near set: the true sensitivities, re-linearised at each AC state (s. 7).

    On the far set the oracle envelope is a, which costs no solve, so this stage visits the
    near conditions only. `el.OracleState` holds the protocol as a state machine and never
    solves; every power flow is here, where the ledger is.
    """
    built = build(key)
    sel = load_selection(key)
    near_rows = sel.near_rows
    planned = oracle_planned(len(near_rows))
    counter = SolveCounter()
    assert_budget(planned)
    label = EVALUABLE_LABEL if sel.near_evaluable else DESCRIPTIVE_LABEL
    print(
        f"oracle {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}; "
        f"{len(near_rows)} near conditions, near_evaluable {sel.near_evaluable}"
    )

    # the true P-sensitivity in envelope space; Q is fixed at the condition (s. 7).
    S_true = (built.path * built.rho) @ (built.down @ built.U)

    records: list[dict] = []
    best_e: list[np.ndarray] = []
    best_vm: list[np.ndarray] = []
    hist_e: list[np.ndarray] = []
    hist_vm: list[np.ndarray] = []
    hist_row: list[int] = []
    started_stage = time.perf_counter()
    try:
        for row in near_rows:
            a = sel.a[row]
            condition = sel.conditions[row]
            state = el.OracleState()
            # the first re-linearisation is at the no-action state (s. 7).
            v_state = np.asarray(sel.vm_no_action[row], dtype=float)
            e_state = np.asarray(a, dtype=float).copy()
            last_lp: dict | None = None
            vm_of_best: np.ndarray | None = None
            history: list[dict] = []
            while not state.done:
                action = state.next_action()
                if action["kind"] == "stop":
                    break
                if action["kind"] == "relinearise":
                    alpha, S = el.affine_at_state(v_state, S_true, e_state)
                    last_lp = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
                    e = np.asarray(last_lp["e"], dtype=float)
                else:
                    e = float(action["factor"]) * np.asarray(state.reference, dtype=float)
                out = solve(built, e, sel.ell[row], sel.q[row], counter)
                converged = bool(out["converged"])
                vm = np.asarray(out["vm"], dtype=float)
                if converged:
                    exceedance = float(np.max(vm - built.vmax))
                    # the next re-linearisation point is this AC-scored envelope's state.
                    v_state, e_state = vm, e.copy()
                else:
                    # s. 12: a failed flow is never scored as safe, and its NaN state must
                    # not become the next linearisation point, so the last good one is kept.
                    exceedance = math.inf
                submitted = dict(state.submit(e, exceedance))
                submitted.update(
                    {
                        "kind": action["kind"],
                        "factor": float(action.get("factor", math.nan)),
                        "converged": converged,
                        "lv_exceedance": out["lv_exceedance"],
                        "line_loading": out["line_loading"],
                        "trafo_loading": out["trafo_loading"],
                        "lp_status": last_lp["status"] if last_lp is not None else None,
                    }
                )
                history.append(submitted)
                hist_e.append(e)
                hist_vm.append(vm)
                hist_row.append(int(row))
                if state.best_e is not None and np.array_equal(state.best_e, e):
                    vm_of_best = vm  # the voltages of the envelope the oracle now keeps

            chosen = np.asarray(state.best_e, dtype=float).ravel()
            if chosen.size != a.size:  # `_finish` returns a length-0 array when none was safe
                chosen = np.zeros(a.size)
                vm_of_best = None
            active = np.asarray(last_lp["active_v"]).ravel() if last_lp is not None else []
            records.append(
                {
                    "row": int(row),
                    "kind": condition["kind"],
                    "day": int(condition["day"]),
                    "step": int(condition["step"]),
                    "label": label,
                    "status": state.status,
                    "solves": state.solves,
                    "lp_steps": int(state.lp_steps),
                    "bisect_steps": int(state.bisect_steps),
                    "total_e": float(chosen.sum()),
                    "total_a": float(np.sum(a)),
                    "best_is_zero": bool(not np.any(chosen)),
                    "last_lp_status": last_lp["status"] if last_lp is not None else None,
                    "last_lp_n_active_v": int(np.asarray(active).size),
                    "last_lp_active_v": [int(k) for k in np.asarray(active)],
                    "voltage_row_active": bool(np.asarray(active).size > 0),
                    "last_lp_stage2_l1_move": (
                        float(last_lp["stage2_l1_move"]) if last_lp is not None else math.nan
                    ),
                    "history": history,
                }
            )
            best_e.append(chosen)
            best_vm.append(
                vm_of_best if vm_of_best is not None else np.full(built.n_customers, math.nan)
            )
            print(
                f"    near day {condition['day']} step {condition['step']}: {state.status}, "
                f"{state.solves} solves, sum e {chosen.sum():.5f} MW of {np.sum(a):.5f}, "
                f"(V) active {np.asarray(active).size}"
            )
            if state.solves > state.budget:
                raise RuntimeError(f"oracle row {row} exceeded its {state.budget}-solve budget")
        solves = counter.bank()
    except BaseException as error:
        abort_record("oracle", key, counter, error, {"records": records})
        raise

    failures = counter.failures
    evaluable = failures <= FAILURE_SHARE * max(counter.attempts, 1)
    # s. 9, s. 15: (V) active on fewer than 7 of 10 near conditions makes H1-H3 NOT EVALUABLE.
    binding = sum(1 for r in records if r["voltage_row_active"])
    ec.write_npz_once(
        OUT / f"oracle_{key}.npz",
        row=np.array([r["row"] for r in records], dtype=np.int32),
        step=np.array([r["step"] for r in records], dtype=np.int32),
        best_e=np.asarray(best_e, dtype=float),
        best_vm=np.asarray(best_vm, dtype=np.float32),  # s. 12: float32 voltages
        history_row=np.array(hist_row, dtype=np.int32),
        history_e=np.asarray(hist_e, dtype=float),
        history_vm=np.asarray(hist_vm, dtype=np.float32),
    )
    ec.write_json_once(
        RESULTS / f"oracle_{key}.json",
        {
            "stage": "oracle",
            "network": key,
            "code": built.code,
            "solves": solves,
            "failures": failures,
            "failure_share": failures / max(counter.attempts, 1),
            "evaluable": evaluable,
            "verdict": "OK" if evaluable else "NOT EVALUABLE",
            "planned_max": planned,
            "near_evaluable": sel.near_evaluable,
            "label": label,
            "n_near": len(near_rows),
            "n_voltage_binding": binding,
            "binding_share": binding / max(len(records), 1),
            "records": records,
            "runtime_s": time.perf_counter() - started_stage,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(
        f"  {len(records)} near conditions, {solves} solves, {failures} failures, "
        f"(V) active on {binding}/{len(records)}, {time.perf_counter() - started_stage:.1f} s"
    )
    if not evaluable:
        print(f"ORACLE NOT EVALUABLE (s. 12): {failures}/{counter.attempts} failed")
        return 1
    return 0


# --- K2. the negative controls H, I, T and the B4box-OLS arm (s. 6, s. 7, s. 10) -----------


def controls_planned(key: str, n_conditions: int, n_near: int) -> int:
    """The planned maximum of controls H, I and T plus the B4box-OLS arm (s. 10, s. 12).

    Per condition: one control H envelope at T = 192, one more at T = 768 on the network
    whose extension physics s. 4 registers, and 4 control I envelopes (2 sigma x 2 regimes).
    Per **near** condition: 4 control T envelopes and 4 B4box-OLS envelopes (2 regimes x
    R = 2). That is 76 on semiurb5's 12 conditions (2 near) and 200 on rural3's 20 (10 near).
    """
    n_c, n_n = int(n_conditions), int(n_near)
    arms = len(CONTROL_REGIMES) * len(CONTROL_REPLICATES)
    total = n_c  # control H at T = 192
    if key in CONTROL_H_LONG_NETWORKS:
        total += n_c  # control H at T = 768
    total += len(CONTROL_I_SIGMA) * len(CONTROL_REGIMES) * n_c  # control I
    total += arms * n_n  # control T
    total += arms * n_n  # B4box-OLS
    return total


def control_h_ridge(
    built: Network, rows: dict, regime: str, replicate: int, days, n_year: int
) -> tuple[ec.RidgeFit, dict]:
    """B2's own procedure on a different training window: control H's T = 192 and T = 768.

    One cross-validation fold per training day (s. 17.4). **Refuses cleanly** when the
    `physics` artefact does not cover the window, which is how the T = 768 arm behaves on a
    network without the registered extension days: it raises before any solve is charged.
    """
    steps = np.asarray(rows["steps"], dtype=int)
    want = steps_of(days)
    missing = np.setdiff1d(want, steps)
    if missing.size:
        raise FileNotFoundError(
            f"control H on {built.key} {regime} needs days {tuple(int(d) for d in days)}, but "
            f"{missing.size} of {want.size} steps are absent from physics_{built.key}_{regime}; "
            "only the network whose extension days s. 4 registers can run the T = 768 arm"
        )
    V = noisy_voltage(built.key, regime, replicate, rows["vm"], steps, n_year)
    keep = np.isin(steps, want)
    X, Y = rows["P_bus"][keep], V[keep]
    day = steps[keep] // grid_study.STEPS
    lam, _ = ec.cv_lambda(X, Y, day)
    fit = ec.fit_ridge(X, Y, lam)
    info = {
        "lam": float(lam),
        "train_steps": int(X.shape[0]),
        "cv_folds": int(np.unique(day).size),
    }
    return fit, info


def control_i_ridge(
    built: Network, rows: dict, regime: str, replicate: int, sigma: float, n_year: int
) -> tuple[ec.RidgeFit, dict]:
    """B2 refitted on the same training days with control I's measurement noise (s. 10, s. 17.3).

    Only sigma_v changes: the standard normal z is the regime's own, so the two levels are
    common random numbers against the primary SIGMA_V arm.
    """
    steps = np.asarray(rows["steps"], dtype=int)
    train_steps = steps_of(TRAIN_DAYS)
    keep = np.isin(steps, train_steps)
    if not keep.any():
        raise FileNotFoundError(f"physics_{built.key}_{regime} stores no training step")
    V = noisy_voltage(built.key, regime, replicate, rows["vm"], steps, n_year, sigma=sigma)
    X, Y = rows["P_bus"][keep], V[keep]
    day = steps[keep] // grid_study.STEPS
    lam, _ = ec.cv_lambda(X, Y, day)
    return ec.fit_ridge(X, Y, lam), {"lam": float(lam), "sigma_v": float(sigma)}


def thermal_module_loading(built: Network, e: np.ndarray, ell: np.ndarray) -> np.ndarray:
    """s. 6's thermal module as a per-branch loading fraction: |f_l(e)| / cap_l.

    f_l(e) = down_l . (U.e - W.l) is the lossless, P-only net downstream export, exactly the
    quantity `el.thermal_rows` bounds by kappa.cap_l. Division by cap_l (not kappa.cap_l)
    makes it comparable with pandapower's `loading_percent`/100 at the same corner.
    """
    e_arr = np.asarray(e, dtype=float).ravel()
    ell_arr = np.asarray(ell, dtype=float).ravel()
    return np.abs(built.down @ (built.U @ e_arr - built.W @ ell_arr)) / built.cap_mva


def thermal_error(module_loading: np.ndarray, branch_loading_pct: np.ndarray) -> np.ndarray:
    """Control T's approximation error per branch: |module |flow|/cap - AC loading_percent/100|.

    s. 6 reports its 95th percentile over every branch at every scored control T corner, and
    labels the thermal results **approximation-limited** when that exceeds 5 %.
    """
    module = np.asarray(module_loading, dtype=float).ravel()
    ac = np.asarray(branch_loading_pct, dtype=float).ravel() / 100.0
    if module.size != ac.size:
        raise ValueError(f"module has {module.size} branches, AC loading {ac.size}")
    return np.abs(module - ac)


def _p95(values) -> float:
    """The 95th percentile over the finite entries, NaN if there are none."""
    arr = np.asarray(values, dtype=float).ravel()
    finite = arr[np.isfinite(arr)]
    return float(np.percentile(finite, 95)) if finite.size else math.nan


def _affine_envelope(fit, built: Network, a: np.ndarray, P_fix: np.ndarray) -> dict:
    """One ridge or OLS fit's primary-decision envelope, with its own nominal read-out."""
    alpha, S = el.affine_from_centred(fit.ybar, fit.slopes, fit.mu, built.U, P_fix)
    out = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
    out["predicted_corner_vm"] = _nominal_max(alpha, S, out["e"])
    return out


def _extra_row_label(index: int, n_branches: int) -> dict:
    """Which branch and direction an active `A_extra` row of `el.thermal_rows` is.

    `thermal_rows` stacks the export rows first and the import rows second, so row i is
    branch i % L, exporting while i < L and importing after.
    """
    i, n = int(index), int(n_branches)
    return {"row": i, "branch": i % n, "direction": "export" if i < n else "import"}


def run_controls(key: str) -> int:
    """Controls H, I and T and the B4box-OLS arm, each AC-scored exactly like `envelopes`."""
    built = build(key)
    profiles = profiles_of(built)
    sel = load_selection(key)
    physics = load_physics(key)
    near_rows = sel.near_rows
    planned = controls_planned(key, sel.n_conditions, len(near_rows))
    counter = SolveCounter()
    assert_budget(planned)
    label = EVALUABLE_LABEL if sel.near_evaluable else DESCRIPTIVE_LABEL
    print(
        f"controls {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}; "
        f"{sel.n_conditions} conditions ({len(near_rows)} near), "
        f"near_evaluable {sel.near_evaluable}"
    )
    if not sel.near_evaluable:
        print(f"  every record is labelled: {label}")

    P_fix = -(sel.ell @ built.W.T)
    Q_fix = -(sel.q @ built.W.T)
    np.testing.assert_allclose(Q_fix, sel.Q_bus, rtol=0, atol=1e-12)

    # --- every fit first, so an absent training window refuses before a solve is charged ---
    started_stage = time.perf_counter()
    h_arms: list[tuple[str, ec.RidgeFit, dict]] = []
    windows = [("H192", CONTROL_H_SHORT_DAYS)]
    if key in CONTROL_H_LONG_NETWORKS:
        windows.append(("H768", CONTROL_H_LONG_DAYS))
    else:
        print(
            f"  control H's T = 768 arm is not run on {key}: s. 10 registers it on "
            f"{', '.join(CONTROL_H_LONG_NETWORKS)} P1 only"
        )
    for arm, days in windows:
        fit, info = control_h_ridge(
            built, physics[CONTROL_H_REGIME], CONTROL_H_REGIME, 0, days, profiles.n_steps
        )
        info.update({"arm": arm, "regime": CONTROL_H_REGIME, "replicate": 0, "days": list(days)})
        h_arms.append((arm, fit, info))
        print(
            f"  {arm}: T = {info['train_steps']}, {info['cv_folds']} folds, lam {info['lam']:.4g}"
        )

    i_arms: list[tuple[str, str, float, ec.RidgeFit, dict]] = []
    for regime in CONTROL_REGIMES:
        for sigma in CONTROL_I_SIGMA:
            fit, info = control_i_ridge(built, physics[regime], regime, 0, sigma, profiles.n_steps)
            arm = f"I{sigma:g}"
            info.update({"arm": arm, "regime": regime, "replicate": 0})
            i_arms.append((arm, regime, sigma, fit, info))
            print(f"  {arm} {regime}: lam {info['lam']:.4g}")

    cells: dict[tuple[str, int], Cell] = {}
    ols_box: dict[tuple[str, int], dict] = {}
    for regime in CONTROL_REGIMES:
        for replicate in CONTROL_REPLICATES:
            started = time.perf_counter()
            cell = cells[(regime, replicate)] = fit_cell(
                built, regime, replicate, physics[regime], profiles.n_steps
            )
            sd, cond = ec.ols_box_sd(cell.X, cell.b1.sigma2)
            ill = not math.isfinite(cond) or cond > OLS_COND_LIMIT
            ols_box[(regime, replicate)] = {"sd": sd, "cond": float(cond), "ill_conditioned": ill}
            print(
                f"  cell {regime} r{replicate}: lam {cell.lam:.4g}, OLS rank {cell.b1.rank}, "
                f"X'X cond {cond:.4g}{' ILL-CONDITIONED' if ill else ''}, "
                f"{time.perf_counter() - started:.1f} s"
            )

    records: list[dict] = []
    e_rows: list[np.ndarray] = []
    vm_rows: list[np.ndarray] = []
    thermal_errors: list[float] = []
    thermal_shortcut_corners = 0
    try:
        # --- control H: B2 on a shorter (and, on rural3, a longer) training window ---
        for arm, fit, info in h_arms:
            for row in range(sel.n_conditions):
                out = _affine_envelope(fit, built, sel.a[row], P_fix[row])
                score = score_corner(built, sel, row, out["e"], counter)
                record = _envelope_record(
                    arm, CONTROL_H_REGIME, 0, row, sel.conditions[row], out, score, label
                )
                record.update(
                    {
                        "control": "H",
                        "scored": True,
                        "lam": info["lam"],
                        "train_steps": info["train_steps"],
                        "cv_folds": info["cv_folds"],
                    }
                )
                records.append(record)
                e_rows.append(np.asarray(out["e"], dtype=float))
                vm_rows.append(np.asarray(score["vm"], dtype=float))

        # --- control I: B2 at two measurement-noise levels, the same z (s. 17.3) ---
        for arm, regime, sigma, fit, info in i_arms:
            for row in range(sel.n_conditions):
                out = _affine_envelope(fit, built, sel.a[row], P_fix[row])
                score = score_corner(built, sel, row, out["e"], counter)
                record = _envelope_record(
                    arm, regime, 0, row, sel.conditions[row], out, score, label
                )
                record.update(
                    {"control": "I", "scored": True, "lam": info["lam"], "sigma_v": float(sigma)}
                )
                records.append(record)
                e_rows.append(np.asarray(out["e"], dtype=float))
                vm_rows.append(np.asarray(score["vm"], dtype=float))

        # --- control T: the full decision, B2's model plus the thermal module ---
        for regime in CONTROL_REGIMES:
            for replicate in CONTROL_REPLICATES:
                cell = cells[(regime, replicate)]
                for row in near_rows:
                    a = sel.a[row]
                    alpha, S = el.affine_from_centred(
                        cell.b2.ybar, cell.b2.slopes, cell.b2.mu, built.U, P_fix[row]
                    )
                    A_x, b_x = el.thermal_rows(
                        built.down, built.U, P_fix[row], built.cap_mva, kappa=el.KAPPA_T
                    )
                    out = el.voltage_envelope(
                        alpha, S, built.vmax, 0.0, a, A_extra=A_x, b_extra=b_x
                    )
                    out["predicted_corner_vm"] = _nominal_max(alpha, S, out["e"])
                    score = score_corner(built, sel, row, out["e"], counter)
                    record = _envelope_record(
                        "T", regime, replicate, row, sel.conditions[row], out, score, label
                    )
                    module = thermal_module_loading(built, out["e"], sel.ell[row])
                    ac_branch = np.asarray(score["branch_loading"], dtype=float)
                    extra = [
                        _extra_row_label(i, built.n_branches)
                        for i in np.asarray(out["active_extra"]).ravel()
                    ]
                    if np.all(np.isfinite(ac_branch)):
                        error = thermal_error(module, ac_branch)
                        thermal_errors.extend(float(v) for v in error)
                    else:
                        # s. 6's scoring shortcut ran no new flow, so there is no per-branch
                        # AC read-out to compare the module against at this corner.
                        error = np.full(built.n_branches, math.nan)
                        thermal_shortcut_corners += 1
                    finite = error[np.isfinite(error)]
                    error_max = float(finite.max()) if finite.size else math.nan
                    record.update(
                        {
                            "control": "T",
                            "scored": True,
                            "kappa": float(el.KAPPA_T),
                            "n_active_extra": len(extra),
                            "active_extra": extra,
                            "module_loading": [float(v) for v in module],
                            "ac_branch_loading": [float(v) for v in ac_branch],
                            "approximation_error_max": error_max,
                            "thermal_unsafe": bool(
                                max(score["line_loading"], score["trafo_loading"])
                                > 100.0 + THERMAL_UNSAFE_PCT
                            )
                            if score["converged"]
                            else True,
                        }
                    )
                    records.append(record)
                    e_rows.append(np.asarray(out["e"], dtype=float))
                    vm_rows.append(np.asarray(score["vm"], dtype=float))

        # --- the B4box-OLS secondary arm (s. 7) ---
        for regime in CONTROL_REGIMES:
            for replicate in CONTROL_REPLICATES:
                cell = cells[(regime, replicate)]
                box = ols_box[(regime, replicate)]
                for row in near_rows:
                    condition = sel.conditions[row]
                    if box["ill_conditioned"]:
                        # s. 7: no solve is run, and the condition is never a safe envelope.
                        records.append(
                            {
                                "method": "B4boxOLS",
                                "control": "G",
                                "regime": regime,
                                "replicate": replicate,
                                "row": int(row),
                                "kind": condition["kind"],
                                "day": int(condition["day"]),
                                "step": int(condition["step"]),
                                "label": label,
                                "status": el.ROBUST_DEGENERATE,
                                "reason": "ill-conditioned",
                                "ols_cond": box["cond"],
                                "total_e": 0.0,
                                "n_active_v": 0,
                                "active_v": [],
                                "predicted_corner_vm": math.nan,
                                "e_equals_a": False,
                                "max_exceedance": math.nan,
                                "unsafe": False,
                                "scored": False,
                                "converged": False,
                                "stage2_l1_move": 0.0,
                                "lv_exceedance": math.nan,
                                "line_loading": math.nan,
                                "trafo_loading": math.nan,
                                "e_min": math.nan,
                                "e_max": math.nan,
                            }  # fmt: skip
                        )
                        continue
                    a = sel.a[row]
                    out = el.box_envelope(
                        cell.b1.ybar, cell.b1.slopes, box["sd"], cell.b1.mu, built.U,
                        P_fix[row], built.vmax, a, cell.gamma, K_SIGMA,
                    )  # fmt: skip
                    alpha, S = el.affine_from_centred(
                        cell.b1.ybar, cell.b1.slopes, cell.b1.mu, built.U, P_fix[row]
                    )
                    out["predicted_corner_vm"] = _nominal_max(alpha, S, out["e"])
                    score = score_corner(built, sel, row, out["e"], counter)
                    record = _envelope_record(
                        "B4boxOLS", regime, replicate, row, condition, out, score, label
                    )
                    record.update(
                        {
                            "control": "G",
                            "ols_cond": box["cond"],
                            "gamma": int(cell.gamma),
                            "k_sigma": K_SIGMA,
                            "scored": True,
                        }  # fmt: skip
                    )
                    records.append(record)
                    e_rows.append(np.asarray(out["e"], dtype=float))
                    vm_rows.append(np.asarray(score["vm"], dtype=float))
        solves = counter.bank()
    except BaseException as error:
        abort_record("controls", key, counter, error, {"records": records})
        raise

    failures = counter.failures
    evaluable = failures <= FAILURE_SHARE * max(counter.attempts, 1)
    error_p95 = _p95(thermal_errors)
    thermal = {
        "kappa": float(el.KAPPA_T),
        "n_branch_samples": len(thermal_errors),
        "n_shortcut_corners": thermal_shortcut_corners,
        "approximation_error_p95": error_p95,
        "approximation_error_max": float(np.max(thermal_errors)) if thermal_errors else math.nan,
        "limit": THERMAL_P95_LIMIT,
        "approximation_limited": bool(math.isfinite(error_p95) and error_p95 > THERMAL_P95_LIMIT),
    }
    # one npz row per **scored** record: the B4box-OLS `ill-conditioned` path runs no solve
    # and so has no envelope to store (s. 7).
    solved = [r for r in records if r["scored"]]
    if len(solved) != len(e_rows):
        raise RuntimeError(f"{len(solved)} scored records but {len(e_rows)} envelopes")
    ec.write_npz_once(
        OUT / f"controls_{key}.npz",
        method=np.array([r["method"] for r in solved]),
        regime=np.array([r["regime"] for r in solved]),
        replicate=np.array([r["replicate"] for r in solved], dtype=np.int32),
        row=np.array([r["row"] for r in solved], dtype=np.int32),
        e=np.asarray(e_rows, dtype=float),
        vm_corner=np.asarray(vm_rows, dtype=np.float32),  # s. 12: float32 voltages
    )
    ec.write_json_once(
        RESULTS / f"controls_{key}.json",
        {
            "stage": "controls",
            "network": key,
            "code": built.code,
            "solves": solves,
            "failures": failures,
            "failure_share": failures / max(counter.attempts, 1),
            "evaluable": evaluable,
            "verdict": "OK" if evaluable else "NOT EVALUABLE",
            "planned_max": planned,
            "near_evaluable": sel.near_evaluable,
            "label": label,
            "n_conditions": sel.n_conditions,
            "n_near": len(near_rows),
            "control_h": [info for _, _, info in h_arms],
            "control_h_long_run": key in CONTROL_H_LONG_NETWORKS,
            "control_i": [info for *_, info in i_arms],
            "control_t": thermal,
            "b4box_ols": {
                f"{regime}_r{replicate}": {
                    "cond": ols_box[(regime, replicate)]["cond"],
                    "ill_conditioned": ols_box[(regime, replicate)]["ill_conditioned"],
                    "limit": OLS_COND_LIMIT,
                }
                for regime in CONTROL_REGIMES
                for replicate in CONTROL_REPLICATES
            },
            "records": records,
            "runtime_s": time.perf_counter() - started_stage,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(
        f"  {len(records)} records, {solves} solves, {failures} failures, "
        f"thermal error p95 {error_p95:.4f} over {len(thermal_errors)} branch samples, "
        f"{time.perf_counter() - started_stage:.1f} s"
    )
    if not evaluable:
        print(f"CONTROLS NOT EVALUABLE (s. 12): {failures}/{counter.attempts} failed")
        return 1
    return 0


# --- K3. decision ambiguity, CERT, ALWAYS and RAND (protocol s. 7, s. 8) -------------------


def ambiguity_planned(n_near: int) -> int:
    """s. 8: the 8 alternatives' primary-decision envelopes, AC-scored, on P1 and P3."""
    return N_ALTERNATIVES * int(n_near) * len(CONTROL_REGIMES)


def require_artefacts(key: str, stages: tuple[str, ...]) -> None:
    """Refuse a stage whose prerequisite artefacts are absent (no solve is charged)."""
    for stage in stages:
        for path in (RESULTS / f"{stage}_{key}.json", OUT / f"{stage}_{key}.npz"):
            if not path.exists():
                raise FileNotFoundError(f"{path} is missing: run `{stage} --network {key}` first")


def load_envelopes(key: str) -> tuple[list[dict], np.ndarray, list[dict]]:
    """`envelopes`' records, their envelopes and the per-cell fit read-outs."""
    require_artefacts(key, ("envelopes",))
    payload = json.loads((RESULTS / f"envelopes_{key}.json").read_text())
    with np.load(OUT / f"envelopes_{key}.npz", allow_pickle=False) as stored:
        e = stored["e"].astype(float)
        methods = [str(m) for m in stored["method"]]
    records = list(payload["records"])
    if methods != [r["method"] for r in records] or e.shape[0] != len(records):
        raise ValueError(f"envelopes_{key}: the npz rows do not match the records")
    return records, e, list(payload["fits"])


def _envelope_index(records: list[dict]) -> dict[tuple, int]:
    return {
        (r["method"], r["regime"], int(r["replicate"]), int(r["row"])): i
        for i, r in enumerate(records)
    }


def verify_stored_fit(cell: Cell, stored: dict, rtol: float = 1e-12) -> dict:
    """s. 8 step 1: the recomputed B2 fit and radius must equal `envelopes`' stored read-outs.

    The artefact stores lambda, the slope norm (control K's denominator) and the radius, which
    is every scalar summary of B2's fit it carries. A mismatch means the seeds or the fit have
    drifted since the counted run, and the ambiguity stage must not proceed on a different B2.
    """
    checks = {
        "lam": (float(cell.lam), float(stored["lam"])),
        "b2_slope_norm": (
            float(np.linalg.norm(cell.b2.slopes)),
            float(stored["control_k"]["b2_slope_norm"]),
        ),  # fmt: skip
        "radius_c": (float(cell.radius.c), float(stored["radius"]["c"])),
        "r2_median": (float(np.median(cell.radius.r2)), float(stored["radius"]["r2_median"])),
        "r2_max": (float(np.max(cell.radius.r2)), float(stored["radius"]["r2_max"])),
    }
    for name, (got, want) in checks.items():
        if not math.isclose(got, want, rel_tol=rtol, abs_tol=0.0):
            raise ValueError(
                f"ambiguity: recomputed {name} {got!r} != the stored {want!r} of "
                f"{stored['regime']} r{stored['replicate']}"
            )
    return {name: got for name, (got, _) in checks.items()}


def policy_bookkeeping(
    act: np.ndarray, unsafe_b2: np.ndarray, unsafe_b2p: np.ndarray, rand_mask: np.ndarray
) -> dict:
    """CERT, ALWAYS and RAND's unsafe counts at one (regime, replicate 0) cell (s. 7).

    CERT acts with B2's already-scored envelope where the alternatives agree and with B2p's
    where they do not; ALWAYS always uses B2p; RAND falls back on `rand_mask`, which carries
    exactly CERT's realised fallback count k. **CERT is NOT EVALUABLE at k = 0 or k = n**,
    because RAND is then identical to it.
    """
    act_arr = np.asarray(act, dtype=bool).ravel()
    b2 = np.asarray(unsafe_b2, dtype=bool).ravel()
    b2p = np.asarray(unsafe_b2p, dtype=bool).ravel()
    rand = np.asarray(rand_mask, dtype=bool).ravel()
    if not (act_arr.size == b2.size == b2p.size == rand.size):
        raise ValueError(
            "act, the two unsafe masks and rand_mask must have one entry per condition"
        )
    n = int(act_arr.size)
    k = int((~act_arr).sum())
    if int(rand.sum()) != k:
        raise ValueError(
            f"RAND fell back {int(rand.sum())} times, CERT {k}; s. 7 requires the same count"
        )
    evaluable = 0 < k < n
    return {
        "n": n,
        "k": k,
        "fallback_rate": k / n if n else math.nan,
        "cert_unsafe": int(np.where(act_arr, b2, b2p).sum()),
        "always_unsafe": int(b2p.sum()),
        "rand_unsafe": int(np.where(rand, b2p, b2).sum()),
        "b2_unsafe": int(b2.sum()),
        "rand_fallback": [bool(v) for v in rand],
        "act": [bool(v) for v in act_arr],
        "evaluable": evaluable,
        "verdict": "OK" if evaluable else "NOT EVALUABLE",
    }


def _alt_envelope(alt, built: Network, a: np.ndarray, P_fix: np.ndarray) -> tuple[dict, dict]:
    """One alternative's primary-decision and proportional-fair envelopes (s. 8 step 3).

    The alternatives are non-negative ridge fits in slope space, so `el.affine_from_slopes`
    takes their recovered intercept directly. Only the primary one is AC-scored (s. 8).
    """
    alpha, S = el.affine_from_slopes(alt.intercepts, alt.slopes, built.U, P_fix)
    primary = el.voltage_envelope(alpha, S, built.vmax, 0.0, a)
    primary["predicted_corner_vm"] = _nominal_max(alpha, S, primary["e"])
    fair = el.proportional_envelope(alpha, S, built.vmax, 0.0, a)
    return primary, fair


def run_ambiguity(key: str) -> int:
    """s. 8's 8 data-consistent alternatives on the near set, and s. 7's CERT/ALWAYS/RAND."""
    require_artefacts(key, ("envelopes", "oracle"))
    built = build(key)
    profiles = profiles_of(built)
    sel = load_selection(key)
    physics = load_physics(key)
    near_rows = sel.near_rows
    planned = ambiguity_planned(len(near_rows))
    counter = SolveCounter()
    assert_budget(planned)
    label = EVALUABLE_LABEL if sel.near_evaluable else DESCRIPTIVE_LABEL
    stored_records, stored_e, stored_fits = load_envelopes(key)
    index = _envelope_index(stored_records)
    oracle = json.loads((RESULTS / f"oracle_{key}.json").read_text())
    oracle_total = {int(r["row"]): float(r["total_e"]) for r in oracle["records"]}
    print(
        f"ambiguity {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}; "
        f"{len(near_rows)} near conditions x {N_ALTERNATIVES} alternatives x "
        f"{len(CONTROL_REGIMES)} regimes, near_evaluable {sel.near_evaluable}"
    )
    if not sel.near_evaluable:
        print(f"  every record is labelled: {label}")

    P_fix = -(sel.ell @ built.W.T)
    records: list[dict] = []
    measures: list[dict] = []
    policies: list[dict] = []
    fits: list[dict] = []
    e_rows: list[np.ndarray] = []
    vm_rows: list[np.ndarray] = []
    started_stage = time.perf_counter()
    try:
        for regime in CONTROL_REGIMES:
            started = time.perf_counter()
            cell = fit_cell(built, regime, AMBIGUITY_REPLICATE, physics[regime], profiles.n_steps)
            stored_fit = next(
                f
                for f in stored_fits
                if f["regime"] == regime and int(f["replicate"]) == AMBIGUITY_REPLICATE
            )
            verified = verify_stored_fit(cell, stored_fit)

            random_alts, rmse_ratio = ec.random_alternatives(
                cell.X, cell.Y, cell.b2.Lambda_s,
                ec.rng_for(key, regime, "ambiguity_refit", 0),
            )  # fmt: skip
            extreme_alts, shrink = ec.extreme_alternatives(
                cell.X, cell.Y, cell.b2.Lambda_s, cell.radius.r2, cell.radius.fit.M
            )
            fits.append(
                {
                    "regime": regime,
                    "replicate": AMBIGUITY_REPLICATE,
                    "verified_against_stored": verified,
                    "rmse_ratio": [float(v) for v in rmse_ratio],
                    "shrink_min": float(np.min(shrink)),
                    "shrink_median": float(np.median(shrink)),
                    "shrink_max": float(np.max(shrink)),
                    "shrink_share_below_one": float(np.mean(shrink < 1.0)),
                }
            )
            families = (("random", random_alts), ("extreme", extreme_alts))

            act_mask: list[bool] = []
            cert_rows: list[dict] = []
            for row in near_rows:
                a = sel.a[row]
                # the stored B2 envelope of this cell is what CERT certifies and acts with.
                b2_key = ("B2", regime, AMBIGUITY_REPLICATE, int(row))
                e_b2 = stored_e[index[b2_key]]
                per_family: dict[str, dict] = {}
                for family, alts in families:
                    primary_e, primary_safe, fair_e = [], [], []
                    for number, alt in enumerate(alts):
                        primary, fair = _alt_envelope(alt, built, a, P_fix[row])
                        score = score_corner(built, sel, row, primary["e"], counter)
                        record = _envelope_record(
                            f"{family}{number}", regime, AMBIGUITY_REPLICATE, row,
                            sel.conditions[row], primary, score, label,
                        )  # fmt: skip
                        is_random = family == "random"
                        record.update(
                            {
                                "family": family,
                                "alternative": number,
                                "rmse_ratio": (
                                    float(rmse_ratio[number]) if is_random else math.nan
                                ),
                                "shrink_min": (
                                    math.nan if is_random else float(np.min(shrink[number]))
                                ),
                                "fair_total_e": float(fair["total"]),
                                "fair_theta": float(fair["theta"]),
                                "fair_status": fair["status"],
                                "fair_ac_scored": False,
                            }
                        )
                        records.append(record)
                        e_rows.append(np.asarray(primary["e"], dtype=float))
                        vm_rows.append(np.asarray(score["vm"], dtype=float))
                        primary_e.append(np.asarray(primary["e"], dtype=float))
                        primary_safe.append(not bool(score["unsafe"]))
                        fair_e.append(np.asarray(fair["e"], dtype=float))

                    primary_arr = np.asarray(primary_e)
                    fair_arr = np.asarray(fair_e)
                    total = oracle_total.get(int(row), math.nan)
                    primary_m = el.ambiguity_measures(
                        primary_arr.sum(axis=1), primary_arr, total, np.asarray(primary_safe)
                    )
                    # s. 8: the proportional-fair envelopes are compared by sum(e) and
                    # allocation only, so no safety disagreement is defined for them.
                    fair_m = el.ambiguity_measures(
                        fair_arr.sum(axis=1), fair_arr, total, np.zeros(fair_arr.shape[0], bool)
                    )
                    fair_m["safety_disagreement"] = None
                    per_family[family] = {"primary": primary_m, "fair": fair_m}
                    measures.append(
                        {
                            "regime": regime,
                            "row": int(row),
                            "kind": sel.conditions[row]["kind"],
                            "day": int(sel.conditions[row]["day"]),
                            "family": family,
                            "oracle_total": total,
                            "primary": primary_m,
                            "fair": fair_m,
                            "n_unsafe": int(sum(1 for s in primary_safe if not s)),
                        }
                    )
                    if family == "random":
                        random_primary = primary_arr

                choice = el.cert_choice(e_b2, random_primary)
                act_mask.append(bool(choice["act"]))
                l1 = np.asarray(choice["l1"], dtype=float)
                cert_rows.append(
                    {
                        "row": int(row),
                        "day": int(sel.conditions[row]["day"]),
                        "act": bool(choice["act"]),
                        "spread": float(choice["spread"]),
                        "l1_max": float(l1.max()) if l1.size else math.nan,
                        "total_b2": float(choice["total_b2"]),
                        "export_spread": per_family["random"]["primary"]["export_spread"],
                    }
                )

            def stored_unsafe(method: str, regime: str = regime) -> np.ndarray:
                """s. 7: CERT and ALWAYS act with envelopes `envelopes` already scored."""
                return np.array(
                    [
                        bool(
                            stored_records[index[(method, regime, AMBIGUITY_REPLICATE, int(row))]][
                                "unsafe"
                            ]
                        )
                        for row in near_rows
                    ]
                )

            unsafe_b2 = stored_unsafe("B2")
            unsafe_b2p = stored_unsafe("B2p")
            act = np.asarray(act_mask, dtype=bool)
            k = int((~act).sum())
            rand_mask = el.rand_fallback(ec.rng_for(key, regime, "rand_fallback"), act.size, k)
            policy = policy_bookkeeping(act, unsafe_b2, unsafe_b2p, rand_mask)
            policy.update({"regime": regime, "replicate": AMBIGUITY_REPLICATE, "cert": cert_rows})
            policies.append(policy)
            print(
                f"  {regime}: {len(near_rows)} near conditions, CERT acted "
                f"{policy['n'] - policy['k']}/{policy['n']} (k = {policy['k']}, "
                f"{policy['verdict']}), {counter.attempts} solves so far, "
                f"{time.perf_counter() - started:.1f} s"
            )
        solves = counter.bank()
    except BaseException as error:
        abort_record("ambiguity", key, counter, error, {"records": records})
        raise

    failures = counter.failures
    evaluable = failures <= FAILURE_SHARE * max(counter.attempts, 1)
    ec.write_npz_once(
        OUT / f"ambiguity_{key}.npz",
        method=np.array([r["method"] for r in records]),
        regime=np.array([r["regime"] for r in records]),
        row=np.array([r["row"] for r in records], dtype=np.int32),
        e=np.asarray(e_rows, dtype=float),
        vm_corner=np.asarray(vm_rows, dtype=np.float32),  # s. 12: float32 voltages
    )
    ec.write_json_once(
        RESULTS / f"ambiguity_{key}.json",
        {
            "stage": "ambiguity",
            "network": key,
            "code": built.code,
            "solves": solves,
            "failures": failures,
            "failure_share": failures / max(counter.attempts, 1),
            "evaluable": evaluable,
            "verdict": "OK" if evaluable else "NOT EVALUABLE",
            "planned_max": planned,
            "near_evaluable": sel.near_evaluable,
            "label": label,
            "n_near": len(near_rows),
            "regimes": list(CONTROL_REGIMES),
            "replicate": AMBIGUITY_REPLICATE,
            "fits": fits,
            "measures": measures,
            "policies": policies,
            "records": records,
            "runtime_s": time.perf_counter() - started_stage,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(
        f"  {len(records)} alternative envelopes, {solves} solves, {failures} failures, "
        f"{time.perf_counter() - started_stage:.1f} s"
    )
    if not evaluable:
        print(f"AMBIGUITY NOT EVALUABLE (s. 12): {failures}/{counter.attempts} failed")
        return 1
    return 0


# --- K4. the s. 15 monotonicity check ------------------------------------------------------


def monotonicity_planned(n_conditions: int) -> int:
    """s. 12: one interior point per condition, on the oracle envelope (= a on the far set)."""
    return int(n_conditions)


def monotonicity_flag(corner_exceedance: float, interior_exceedance: float) -> bool:
    """s. 15: the corner-monotonicity assumption fails when an **interior** point violates
    the upper voltage limit while the corner does not.

    A non-finite exceedance - a failed flow - is not a monotonicity failure; it is a failed
    solve, counted as such and never scored as safe (s. 12).
    """
    corner = float(corner_exceedance)
    interior = float(interior_exceedance)
    if not (math.isfinite(corner) and math.isfinite(interior)):
        return False
    return bool(interior > MONOTONICITY_PU and corner <= MONOTONICITY_PU)


def oracle_corner_exceedance(record: dict) -> float:
    """The corner exceedance the oracle stored for the envelope it kept (`best_e`).

    `best_e` is the largest AC-feasible envelope the oracle scored, so its exceedance is the
    one its history recorded at the largest feasible total. NaN when none was feasible.
    """
    feasible = [h for h in record["history"] if h["feasible"]]
    if not feasible:
        return math.nan
    best = max(feasible, key=lambda h: float(h["total"]))
    stored_total = float(record["total_e"])
    if not math.isclose(float(best["total"]), stored_total, rel_tol=1e-12, abs_tol=1e-15):
        raise ValueError(
            f"oracle row {record['row']}: best_e totals {record['total_e']!r} but its largest "
            f"feasible history entry totals {best['total']!r}"
        )
    return float(best["max_exceedance"])


def run_monotonicity(key: str) -> int:
    """s. 15's AC check of corner monotonicity: one interior point per condition."""
    require_artefacts(key, ("oracle",))
    built = build(key)
    sel = load_selection(key)
    planned = monotonicity_planned(sel.n_conditions)
    counter = SolveCounter()
    assert_budget(planned)
    label = EVALUABLE_LABEL if sel.near_evaluable else DESCRIPTIVE_LABEL
    oracle = json.loads((RESULTS / f"oracle_{key}.json").read_text())
    oracle_records = {int(r["row"]): r for r in oracle["records"]}
    with np.load(OUT / f"oracle_{key}.npz", allow_pickle=False) as stored:
        best_e = {int(row): stored["best_e"][i] for i, row in enumerate(stored["row"])}
    print(
        f"monotonicity {key}: ledger {ledger_total()} + at most {planned} <= {LEDGER_CEILING}; "
        f"{sel.n_conditions} conditions ({len(sel.near_rows)} near)"
    )

    records: list[dict] = []
    x_rows: list[np.ndarray] = []
    started_stage = time.perf_counter()
    try:
        for row in range(sel.n_conditions):
            condition = sel.conditions[row]
            near = condition["kind"] == "near"
            if near:
                if row not in best_e:
                    raise ValueError(f"oracle_{key} has no record for near condition {row}")
                e = np.asarray(best_e[row], dtype=float)
                corner = oracle_corner_exceedance(oracle_records[row])
                source = "oracle best_e"
            else:
                # s. 7: on the far set the oracle envelope is a, whose corner is the
                # selection's own no-action solve (s. 12: it costs no new solve).
                e = np.asarray(sel.a[row], dtype=float)
                corner = float(condition["customer_exceedance"])
                source = "selection no-action"
            x = el.interior_point(ec.rng_for(key, "common", "interior_point", row), e)
            out = solve(built, x, sel.ell[row], sel.q[row], counter)
            converged = bool(out["converged"])
            vm = np.asarray(out["vm"], dtype=float)
            interior = float(np.max(vm - built.vmax)) if converged else math.nan
            flag = monotonicity_flag(corner, interior)
            records.append(
                {
                    "row": int(row),
                    "kind": condition["kind"],
                    "day": int(condition["day"]),
                    "step": int(condition["step"]),
                    "label": label,
                    "corner_source": source,
                    "corner_exceedance": corner,
                    "interior_exceedance": interior,
                    "interior_total": float(x.sum()),
                    "envelope_total": float(e.sum()),
                    "share_of_envelope": float(x.sum() / e.sum()) if e.sum() > 0.0 else math.nan,
                    "converged": converged,
                    "lv_exceedance": out["lv_exceedance"],
                    "line_loading": out["line_loading"],
                    "trafo_loading": out["trafo_loading"],
                    "monotonicity_failure": flag,
                }
            )
            x_rows.append(x)
            print(
                f"    {condition['kind']:<5} day {condition['day']}: corner "
                f"{corner:+.5f}, interior {interior:+.5f} pu at "
                f"{records[-1]['share_of_envelope']:.3f} of sum(e)"
                f"{'  MONOTONICITY FAILURE (s. 15)' if flag else ''}"
            )
        solves = counter.bank()
    except BaseException as error:
        abort_record("monotonicity", key, counter, error, {"records": records})
        raise

    failures = counter.failures
    evaluable = failures <= FAILURE_SHARE * max(counter.attempts, 1)
    flags = [r for r in records if r["monotonicity_failure"]]
    ec.write_npz_once(
        OUT / f"monotonicity_{key}.npz",
        row=np.array([r["row"] for r in records], dtype=np.int32),
        interior_e=np.asarray(x_rows, dtype=float),
    )
    ec.write_json_once(
        RESULTS / f"monotonicity_{key}.json",
        {
            "stage": "monotonicity",
            "network": key,
            "code": built.code,
            "solves": solves,
            "failures": failures,
            "failure_share": failures / max(counter.attempts, 1),
            "evaluable": evaluable,
            "verdict": "OK" if evaluable else "NOT EVALUABLE",
            "planned_max": planned,
            "label": label,
            "n_conditions": sel.n_conditions,
            "n_failures_flagged": len(flags),
            "flagged_rows": [r["row"] for r in flags],
            "stop_condition_triggered": bool(flags),
            "records": records,
            "runtime_s": time.perf_counter() - started_stage,
            "protocol_sha256": ec.PROTOCOL_SHA256,
        },
    )
    print(
        f"  {len(records)} interior points, {solves} solves, {failures} failures, "
        f"{len(flags)} monotonicity flags, {time.perf_counter() - started_stage:.1f} s"
    )
    if flags:
        print(f"MONOTONICITY FAILURE (s. 15) on rows {[r['row'] for r in flags]}")
    if not evaluable:
        print(f"MONOTONICITY NOT EVALUABLE (s. 12): {failures}/{counter.attempts} failed")
        return 1
    return 0


# --- L. the report read-out (zero solves) --------------------------------------------------


def _median(values: list[float]) -> float:
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return float(np.median(finite)) if finite else math.nan


def _print_selection_summary(key: str) -> None:
    """`select`'s record: the screen, the candidate table and the e = 0 vertex (s. 5, s. 17.7)."""
    path = RESULTS / f"selection_{key}.json"
    if not path.exists():
        print(f"  no selection_{key}.json")
        return
    payload = json.loads(path.read_text())
    print(
        f"  select: {payload['solves']} solves, {payload['failures']} failures; "
        f"near survivors {payload['n_near_survivors']}/{len(payload['deploy_days'])}, "
        f"near_evaluable {payload['near_evaluable']}; "
        f"far candidates {payload['n_far_candidates']}, far_evaluable {payload['far_evaluable']}"
    )
    print(f"  skipped far days (no step at f >= {FAR_F}): {payload['skipped_far_days']}")
    candidates = sorted(
        payload["candidates"],
        key=lambda c: -c["customer_exceedance"] if math.isfinite(c["customer_exceedance"]) else 1,
    )
    print("  top 12 candidates by customer exceedance:")
    print("      kind  day  step   f      exceed_cust  exceed_lv   line %  trafo %  screen")
    for c in candidates[:12]:
        print(
            f"      {c['kind']:<5} {c['day']:>3} {c['step']:>6} {c['f']:.3f} "
            f"{c['customer_exceedance']:>+11.5f} {c['lv_exceedance']:>+10.5f} "
            f"{c['line_loading']:>7.1f} {c['trafo_loading']:>8.1f}  "
            f"{c.get('passed_near_screen', '-')}"
        )
    vertices = payload["zero_vertex"]
    unsafe = [v for v in vertices if v["unsafe_voltage"] or v["unsafe_thermal"]]
    margins = [v["min_vm_margin_pu"] for v in vertices]
    loadings = [max(v["line_loading"], v["trafo_loading"]) for v in vertices]
    print(
        f"  e = 0 vertex: {len(vertices)} solved, {len(unsafe)} unsafe; "
        f"min_vm margin {min(margins):+.5f}..{max(margins):+.5f} pu, "
        f"max loading {max(loadings):.1f} %"
    )


def _print_envelope_summary(key: str) -> None:
    """Every read-out the envelope stage's report needs, grouped as s. 9 reports them."""
    path = RESULTS / f"envelopes_{key}.json"
    if not path.exists():
        print(f"  no envelopes_{key}.json")
        return
    payload = json.loads(path.read_text())
    print(
        f"  envelopes: {payload['solves']} solves "
        f"({payload['shortcut_records']} of {len(payload['records'])} records reused the "
        f"no-action solve), {payload['failures']} failures, verdict {payload['verdict']}, "
        f"{payload['runtime_s']:.1f} s"
    )
    print(f"  label: {payload['label']}")

    print("  fits per cell: lam, lam_m, test-day MAE (s. 9 H2), control K (NC4), margins, radius")
    print(
        "      cell    lam      lam_m    MAE_OLS   MAE_ridge MAE_NNLS  K_MAE     K_norm/B2 "
        "m_med     2sig_med  c        r2_med    F_med"
    )
    for fit in payload["fits"]:
        mae = fit["test_mae"]
        k = fit["control_k"]
        print(
            f"      {fit['regime']} r{fit['replicate']}  {fit['lam']:<8.4g} {fit['lam_m']:<8.4g} "
            f"{mae['OLS']:<9.3e} {mae['ridge']:<9.3e} {mae['NNLS']:<9.3e} "
            f"{k['test_mae']:<9.3e} {k['slope_norm_ratio']:<9.3f} "
            f"{fit['margin']['conformal_median']:<9.3e} {fit['margin']['insample_median']:<9.3e} "
            f"{fit['radius']['c']:<8.4g} {fit['radius']['r2_median']:<9.3e} "
            f"{fit['radius']['f_radius_median']:.3e}"
        )

    records = payload["records"]
    print("  per method x cell x set: unsafe per replicate, median sum(e), statuses")
    print(
        "      method  cell    set   n   unsafe  med_sum_e  med_exceed  max_exceed  "
        "fail  (V)act  statuses"
    )
    cells = [f"{r}_r{i}" for r, i in payload["cells"]] + ["-_r-1"]
    for method in payload["methods"]:
        for cell in cells:
            for kind in ("near", "far"):
                group = [
                    r
                    for r in records
                    if r["method"] == method
                    and f"{r['regime']}_r{r['replicate']}" == cell
                    and r["kind"] == kind
                ]
                if not group:
                    continue
                statuses: dict[str, int] = {}
                for r in group:
                    statuses[r["status"]] = statuses.get(r["status"], 0) + 1
                exceedances = [r["max_exceedance"] for r in group]
                worst = max(exceedances, key=lambda v: v if math.isfinite(v) else -math.inf)
                extra = ""
                restored = [r for r in group if r.get("restored")]
                if restored:
                    gaps = [r["gap"] for r in restored]
                    extra = f" restored {len(restored)} gap {min(gaps):.4f}..{max(gaps):.4f}"
                    if any(r.get("gap_flag") for r in restored):
                        extra += " GAP>1%"
                moved = [r for r in group if r["stage2_l1_move"] > 0.01]
                if moved:
                    extra += f" stage2>1% {len(moved)}"
                print(
                    f"      {method:<7} {cell:<7} {kind:<5} {len(group):<3} "
                    f"{sum(1 for r in group if r['unsafe']):<7} "
                    f"{_median([r['total_e'] for r in group]):<10.5f} "
                    f"{_median(exceedances):<+11.5f} {worst:<+11.5f} "
                    f"{sum(1 for r in group if not r['converged']):<5} "
                    f"{_median([float(r['n_active_v']) for r in group]):<7.1f} "
                    f"{statuses}{extra}"
                )
    loadings = [
        max(r["line_loading"], r["trafo_loading"])
        for r in records
        if math.isfinite(r["line_loading"])
    ]
    print(
        f"  corner loading over every scored envelope: median {_median(loadings):.1f} %, "
        f"max {max(loadings):.1f} %"
    )
    corner = payload["fits"][0]["corner_distance"]
    print(
        "  corner distance of the conditions (P1 r0 design): residual norm "
        f"{_median([c['residual_norm'] for c in corner]):.4g} median, mahalanobis "
        f"{_median([c['mahalanobis'] for c in corner]):.4g} median"
    )


def _print_oracle_summary(key: str) -> None:
    """B5 per near condition, and s. 9's binding diagnostic."""
    path = RESULTS / f"oracle_{key}.json"
    if not path.exists():
        print(f"  no oracle_{key}.json")
        return
    payload = json.loads(path.read_text())
    print(
        f"  oracle: {payload['solves']} solves, {payload['failures']} failures, "
        f"verdict {payload['verdict']}, (V) active on "
        f"{payload['n_voltage_binding']}/{payload['n_near']}, {payload['runtime_s']:.1f} s"
    )
    print("      day  step   status      solves  LP  bis  sum_e      sum_a      (V)act")
    for r in payload["records"]:
        print(
            f"      {r['day']:>3} {r['step']:>6} {r['status']:<11} {r['solves']:>6} "
            f"{r['lp_steps']:>3} {r['bisect_steps']:>4} {r['total_e']:<10.5f} "
            f"{r['total_a']:<10.5f} {r['last_lp_n_active_v']}"
        )


def _print_controls_summary(key: str) -> None:
    """Controls H, I and T and the B4box-OLS arm, grouped as s. 10 reports them."""
    path = RESULTS / f"controls_{key}.json"
    if not path.exists():
        print(f"  no controls_{key}.json")
        return
    payload = json.loads(path.read_text())
    print(
        f"  controls: {payload['solves']} solves, {payload['failures']} failures, "
        f"verdict {payload['verdict']}, {payload['runtime_s']:.1f} s"
    )
    for info in payload["control_h"]:
        print(
            f"      control {info['arm']}: T = {info['train_steps']}, {info['cv_folds']} folds, "
            f"lam {info['lam']:.4g}"
        )
    if not payload["control_h_long_run"]:
        print("      control H's T = 768 arm: not run on this network (s. 10)")
    thermal = payload["control_t"]
    print(
        f"      control T: kappa {thermal['kappa']}, approximation error p95 "
        f"{thermal['approximation_error_p95']:.5f}, max {thermal['approximation_error_max']:.5f} "
        f"over {thermal['n_branch_samples']} branch samples "
        f"({thermal['n_shortcut_corners']} corners reused the no-action solve, no per-branch AC); "
        f"approximation-limited {thermal['approximation_limited']} (limit {thermal['limit']})"
    )
    for cell, info in sorted(payload["b4box_ols"].items()):
        print(
            f"      B4box-OLS {cell}: X'X cond {info['cond']:.4g}, ill-conditioned "
            f"{info['ill_conditioned']} (limit {info['limit']:.0e})"
        )
    print("      arm     cell     set   n   unsafe  med_sum_e  med_exceed  max_exceed  statuses")
    records = payload["records"]
    arms = sorted({(r["method"], r["regime"], int(r["replicate"])) for r in records})
    for method, regime, replicate in arms:
        for kind in ("near", "far"):
            group = [
                r
                for r in records
                if r["method"] == method
                and r["regime"] == regime
                and int(r["replicate"]) == replicate
                and r["kind"] == kind
            ]
            if not group:
                continue
            statuses: dict[str, int] = {}
            for r in group:
                statuses[r["status"]] = statuses.get(r["status"], 0) + 1
            exceedances = [r["max_exceedance"] for r in group]
            worst = max(exceedances, key=lambda v: v if math.isfinite(v) else -math.inf)
            extra = ""
            active_extra = [r.get("n_active_extra") for r in group if "n_active_extra" in r]
            if active_extra:
                extra = f" active_extra {min(active_extra)}..{max(active_extra)}"
                thermal_unsafe = sum(1 for r in group if r.get("thermal_unsafe"))
                extra += f" thermal_unsafe {thermal_unsafe}"
            print(
                f"      {method:<7} {regime}_r{replicate:<3} {kind:<5} {len(group):<3} "
                f"{sum(1 for r in group if r['unsafe']):<7} "
                f"{_median([r['total_e'] for r in group]):<10.5f} "
                f"{_median(exceedances):<+11.5f} {worst:<+11.5f} {statuses}{extra}"
            )


def _print_ambiguity_summary(key: str) -> None:
    """s. 8's measures per family, and s. 7's CERT, ALWAYS and RAND bookkeeping."""
    path = RESULTS / f"ambiguity_{key}.json"
    if not path.exists():
        print(f"  no ambiguity_{key}.json")
        return
    payload = json.loads(path.read_text())
    print(
        f"  ambiguity: {payload['solves']} solves, {payload['failures']} failures, "
        f"verdict {payload['verdict']}, {payload['runtime_s']:.1f} s"
    )
    for fit in payload["fits"]:
        ratios = fit["rmse_ratio"]
        print(
            f"      {fit['regime']} r{fit['replicate']}: random RMSE ratios "
            f"{', '.join(f'{v:.4f}' for v in ratios)}; shrink min {fit['shrink_min']:.4f}, "
            f"median {fit['shrink_median']:.4f}, max {fit['shrink_max']:.4f}, "
            f"share < 1 {fit['shrink_share_below_one']:.3f}"
        )
    print(
        "      cell  family   objective  n   med_export_spread  max_export_spread  "
        "med_alloc_spread  disagree  unsafe"
    )
    for regime in payload["regimes"]:
        for family in ("random", "extreme"):
            group = [
                m for m in payload["measures"] if m["regime"] == regime and m["family"] == family
            ]
            if not group:
                continue
            for objective in ("primary", "fair"):
                spreads = [m[objective]["export_spread"] for m in group]
                allocs = [m[objective]["allocation_spread"] for m in group]
                disagree = sum(1 for m in group if m[objective]["safety_disagreement"])
                print(
                    f"      {regime:<5} {family:<8} {objective:<10} {len(group):<3} "
                    f"{_median(spreads):<18.5f} "
                    f"{max(spreads, key=lambda v: v if math.isfinite(v) else -math.inf):<18.5f} "
                    f"{_median(allocs):<17.6f} "
                    f"{disagree if objective == 'primary' else '-':<9} "
                    f"{sum(m['n_unsafe'] for m in group) if objective == 'primary' else '-'}"
                )
    print("      cell  n   k   rate    CERT  ALWAYS  RAND  B2  verdict")
    for policy in payload["policies"]:
        print(
            f"      {policy['regime']:<5} {policy['n']:<3} {policy['k']:<3} "
            f"{policy['fallback_rate']:<7.3f} {policy['cert_unsafe']:<5} "
            f"{policy['always_unsafe']:<7} {policy['rand_unsafe']:<5} {policy['b2_unsafe']:<3} "
            f"{policy['verdict']}"
        )


def _print_monotonicity_summary(key: str) -> None:
    """s. 15's interior-point check, one row per condition."""
    path = RESULTS / f"monotonicity_{key}.json"
    if not path.exists():
        print(f"  no monotonicity_{key}.json")
        return
    payload = json.loads(path.read_text())
    print(
        f"  monotonicity: {payload['solves']} solves, {payload['failures']} failures, "
        f"{payload['n_failures_flagged']} flags, verdict {payload['verdict']}, "
        f"{payload['runtime_s']:.1f} s"
    )
    print("      set   day  corner      interior    share  source               flag")
    for r in payload["records"]:
        print(
            f"      {r['kind']:<5} {r['day']:>3} {r['corner_exceedance']:>+11.5f} "
            f"{r['interior_exceedance']:>+11.5f} {r['share_of_envelope']:>6.3f} "
            f"{r['corner_source']:<20} {r['monotonicity_failure']}"
        )


def cmd_summary(key: str) -> int:
    """Zero-solve: print the report read-outs of whichever artefacts this network has.

    Every number it prints is already in `results/`; nothing is recomputed and no solve is
    run, so this command can be repeated without touching the ledger.
    """
    print(f"summary {key}: ledger {ledger_total()} (ceiling {LEDGER_CEILING})")
    _print_selection_summary(key)
    _print_envelope_summary(key)
    _print_oracle_summary(key)
    _print_controls_summary(key)
    _print_ambiguity_summary(key)
    _print_monotonicity_summary(key)
    return 0


# --- M. the command line -------------------------------------------------------------------


def cmd_build(key: str) -> int:
    built = build(key)
    print(f"{key} ({built.code}): {built.n_customers} customer buses, {built.n_units} PV units")
    print(f"  branches: {built.parent_branch.size} (branch 0 = the transformer)")
    print(f"  V_lv {built.v_lv_kv} kV, rho {built.rho.min():.4g}..{built.rho.max():.4g}")
    print(f"  vmax {built.vmax.min()}..{built.vmax.max()}, vmin {built.vmin.min()}")
    print(f"  structured_predict vs lindistflow: {check_linear_structure(built):.2e}")
    print(f"  total PV rating {built.ratings.sum():.4f} MW; ledger {ledger_total()}")
    return 0


def cmd_days(key: str) -> int:
    """Zero-solve: f(t) over the deployment days, and which of them yield a far candidate.

    s. 5's far candidate is the first step with f(t) >= 0.2; this prints the days where no
    step reaches it, which is what the near and far candidate counts depend on.
    """
    built = build(key)
    profiles = profiles_of(built)
    missing = []
    print(f"{key}: deployment days {DEPLOY_DAYS[0]}-{DEPLOY_DAYS[-1]}, f(t) over each day")
    for day in DEPLOY_DAYS:
        day_steps = steps_of([day])
        f_day = profiles.f[day_steps]
        near = near_candidate(f_day)
        far = far_candidate(f_day)
        if far is None:
            missing.append(int(day))
        print(
            f"  day {day}: max f {f_day.max():.4f} at step {near:2d}, "
            f"first f >= {FAR_F} at {'none' if far is None else f'step {far}'}"
        )
    print(f"{len(DEPLOY_DAYS) - len(missing)} of {len(DEPLOY_DAYS)} days yield a far candidate")
    if missing:
        print(f"no far candidate on days: {missing}")
    return 0


def cmd_ledger(key: str) -> int:
    ledger = ec.SolveLedger(start=LEDGER_START, ceiling=LEDGER_CEILING)
    rows = []
    if RESULTS.is_dir():
        for path in sorted(RESULTS.glob("*.json")):
            payload = json.loads(path.read_text())
            if "solves" in payload:
                ledger.charge(path.stem, int(payload["solves"]))
                rows.append((path.name, payload.get("stage", "?"), int(payload["solves"])))
    print(f"board design audits: {LEDGER_START}")
    for name, stage, solves in rows:
        print(f"  {solves:>6}  {stage:<18} {name}")
    print(f"ledger total: {ledger.total}  (ceiling {LEDGER_CEILING}, "
          f"{ledger.remaining()} remaining)")  # fmt: skip
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "cmd",
        choices=(
            "build", "days", "ledger", "summary", "physics", "select", "envelopes", "oracle",
            "controls", "ambiguity", "monotonicity",
        ),
    )  # fmt: skip
    parser.add_argument("--network", required=True, choices=tuple(NETWORKS))
    parser.add_argument(
        "--resume",
        action="store_true",
        help="physics only: verify and skip the regimes already written, solve the rest",
    )
    args = parser.parse_args(argv)

    # a terminating signal must leave an abort record rather than a silent gap (s. 12).
    install_termination_handler()
    # revision 2.2 plus amendments A1-A2, and the as-executed text; before anything else.
    ec.check_protocol()
    if args.cmd == "build":
        return cmd_build(args.network)
    if args.cmd == "days":
        return cmd_days(args.network)
    if args.cmd == "ledger":
        return cmd_ledger(args.network)
    if args.cmd == "summary":
        return cmd_summary(args.network)
    if args.cmd == "physics":
        return run_physics(args.network, resume=args.resume)
    if args.cmd == "select":
        return run_select(args.network)
    if args.cmd == "envelopes":
        return run_envelopes(args.network)
    if args.cmd == "controls":
        return run_controls(args.network)
    if args.cmd == "ambiguity":
        return run_ambiguity(args.network)
    if args.cmd == "monotonicity":
        return run_monotonicity(args.network)
    return run_oracle(args.network)


if __name__ == "__main__":
    raise SystemExit(main())
