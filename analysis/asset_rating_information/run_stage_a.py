"""Mission 12 Stage A runner: decision tables, the controls, the scored evaluation, the verdicts.

`stage_a_protocol.md` revision 2.2 as executed (`ratings_core.PROTOCOL_SHA256_EXECUTED`,
which the appended amendments leave untouched), Paperclip AKK-77 and AKK-78. Every
command calls `rc.check_protocol()` before it touches anything, writes JSON to `results/` and
arrays to `runs/` through `ratings_core`'s write-once helpers, and records the sha256 of
`ratings_core.py` and of this file in the artefact.

Six commands:

* **`tables --network K`** -- zero solves. Re-labels the Phase 5 nominal full-state cache of
  one network into the protocol's P-period and E-period decision tables and writes the counts,
  the candidate pools, the topology (routes, root paths, feeder ids), the H1 situation shares,
  the curtailed-step counts and the cross-check against the board's zero-solve export audit.
* **`control-d`** -- the only command that solves (two AC flows, a ledger counts every
  attempt). A rating-only change must leave the electrical state bit-identical.
* **`control-e --network K`** -- zero solves. The Phase 8 `line_local` cache (R x 1.5 and
  `max_i_ka` x 0.8 on one cable) against the Phase 5 nominal cache: the measured propagation of
  an impedance error, and the share of steps where the modified cable is overloaded invisibly.
* **`pilot`** -- zero solves. Times a reduced evaluation of every protocol s. 6 policy on
  semiurb5 and projects the full run. Writes timings only, never a scored result.
* **`evaluate --network K --model M`** -- zero solves. The scored evaluation of one
  (network, model): every protocol s. 6 policy at every budget, the recovery curves, the
  unsafe and severity read-outs, the value of information, Controls C, F, G, H and J, H4, and
  the B3-against-B2 check. Rankings and sets are planned on the **P** table from deployable
  inputs alone; every scored number is computed on the **E** table against the truth draws.
* **`verdicts`** -- zero solves and no new scoring. Applies protocol s. 7's verdicts, s. 8's
  controls and s. 12's stop conditions to the written evaluations.

**Foreground only** (protocol s. 10): no command forks, detaches or writes in the background.

**Data:** SimBench (ODbL 1.0), see `DATA_ATTRIBUTION.md`. The caches under `outputs/` are
local and git-ignored; this module only ever reads them.
"""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import os
import signal
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import NamedTuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (REPO / "src", HERE):  # imported, never copied or edited
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import ratings_core as rc  # noqa: E402

from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import fullstate, grid, grid_study, sensing, stress  # noqa: E402

# --- A. constants --------------------------------------------------------------------------

#: protocol s. 3: every daylight quarter-hour of these days.
DAYS = tuple(range(35, 365))
#: protocol s. 3: alternating 7-day blocks, b = floor((day - 35) / 7); even = P, odd = E.
PERIOD_BLOCK = 7
PERIODS = ("P", "E")

SENSE_CACHE = REPO / "outputs" / "sense_study" / "fullstate_cache"
ROBUST_CACHE = REPO / "outputs" / "robust_study" / "fullstate_cache"
RESULTS = HERE / "results"
RUNS = HERE / "runs"

#: the board's zero-solve export audit, `docs/provenance/mission12_board_audit/README.md`,
#: in MWh over days 35-364, daylight steps. The three columns this runner reproduces.
AUDIT_EXPORT_MWH = {
    "rural1": {
        "nocap": 291.261,
        "recorded": 278.210,
        "robust_w0.2": 278.210,
        "robust_w0.3": 278.210,
    },  # noqa: E501
    "rural2": {
        "nocap": 432.976,
        "recorded": 416.831,
        "robust_w0.2": 416.831,
        "robust_w0.3": 416.735,
    },  # noqa: E501
    "rural3": {
        "nocap": 690.347,
        "recorded": 666.335,
        "robust_w0.2": 666.230,
        "robust_w0.3": 662.282,
    },  # noqa: E501
    "semiurb4": {
        "nocap": 417.431,
        "recorded": 398.170,
        "robust_w0.2": 360.692,
        "robust_w0.3": 350.773,
    },  # noqa: E501
    "semiurb5": {
        "nocap": 812.819,
        "recorded": 782.157,
        "robust_w0.2": 717.072,
        "robust_w0.3": 694.124,
    },  # noqa: E501
    "urban6": {
        "nocap": 632.542,
        "recorded": 614.478,
        "robust_w0.2": 569.875,
        "robust_w0.3": 548.326,
    },  # noqa: E501
}
#: the audit table is rounded to 3 decimals, so this is the tightest meaningful tolerance.
AUDIT_TOL_MWH = 1e-3

#: Control D (protocol s. 8): the network, the cable and the solve ceiling.
CONTROL_D_NETWORK = "urban6"
CONTROL_D_LINE = 33
CONTROL_D_RATING_FACTOR = 0.8
CONTROL_D_MAX_SOLVES = 4
CONTROL_D_REL_TOL = 1e-9

#: the pilot (protocol s. 10): the network, the model and the reduced sizes.
PILOT_NETWORK = "semiurb5"
PILOT_MODEL = "U2"
PILOT_N_TRUTH = 10
PILOT_N_PRIOR = 100
FULL_N_TRUTH = 200
PILOT_BUDGETS = (1, 2, 3, 4, 6, 8)
#: B8P's pair search is quadratic in the pool, so the pilot times it at the budget H3b uses
#: and extrapolates linearly in greedy steps to `PILOT_B8_BUDGET` (judgement call, recorded).
PILOT_B8P_BUDGET = 4
PILOT_TOP_M = 10
PILOT_OB_KMAX = 3
PILOT_H4_KMAX = 6
#: protocol s. 10: the board reduces N_truth if the projection exceeds this.
CPU_HOUR_CEILING = 2.5
#: which models apply to which networks (protocol s. 5: U-T is rural, U2' cable-limited).
MODELS_ALL = ("U0", "U2", "U3", "U4")
TRANSFORMER_LIMITED = ("rural1", "rural2", "rural3")
CABLE_LIMITED = ("semiurb4", "semiurb5", "urban6")

W_PRIMARY, W_SECONDARY = 0.2, 0.3


def networks() -> dict[str, str]:
    """Short name -> SimBench code, in `dual_study.HOSTING_CAPACITY` order."""
    return {code.split("-LV-")[1].split("--")[0]: code for code in ds.HOSTING_CAPACITY}


def code_of(name: str) -> str:
    table = networks()
    if name not in table:
        raise ValueError(f"network {name!r} is not one of {tuple(table)}")
    return table[name]


def period_of(day: int) -> str:
    """Protocol s. 3: P on even 7-day blocks counted from day 35, E on odd ones."""
    return PERIODS[((int(day) - DAYS[0]) // PERIOD_BLOCK) % 2]


def _rel(path: Path) -> str:
    """A repo-relative path for the artefacts; absolute if it lies outside the repo."""
    try:
        return str(Path(path).relative_to(REPO))
    except ValueError:
        return str(path)


def code_hashes() -> dict[str, str]:
    """The sha256 of the two files that produce every artefact (protocol s. 10)."""
    return {
        "ratings_core.py": rc.sha256_of(HERE / "ratings_core.py"),
        "run_stage_a.py": rc.sha256_of(Path(__file__).resolve()),
    }


def _stamp(command: str, **extra) -> dict:
    return {
        "status": rc.STATUS,
        "command": command,
        "protocol_sha256": rc.check_protocol(),
        "code_sha256": code_hashes(),
        "days": [DAYS[0], DAYS[-1]],
        **extra,
    }


# --- B. topology (one convention, protocol s. 5 / s. 6) ------------------------------------


class Topology(NamedTuple):
    """Per-line arrays in **network** line indices, plus the checks that produced them.

    `parent_line` is the next line towards the LV busbar (-1 at a feeder head), `feeder_of`
    the busbar-outgoing line whose subtree holds it, `depth` its hop distance from the busbar
    and `route_of` `ratings_core.routes`' label. `child_bus` is the downstream endpoint.
    """

    parent_line: np.ndarray
    feeder_of: np.ndarray
    depth: np.ndarray
    std_type: np.ndarray
    route_of: np.ndarray
    child_bus: np.ndarray
    lv_busbar: int
    checks: dict


def line_topology(net) -> Topology:
    """The study's single topology function (protocol s. 5, U4).

    `pandapower.topology.create_nxgraph(net, respect_switches=True)` restricted to in-service
    **lines**, rooted at the transformer LV bus. The line graph is asserted to be a tree: no
    parallel edges, no cycles, and every line inside the busbar's component (board check,
    protocol s. 2: all six networks are radial and every line is in service).
    """
    import networkx as nx
    from pandapower import topology as pp_topology

    graph = pp_topology.create_nxgraph(
        net,
        respect_switches=True,
        include_lines=True,
        include_impedances=False,
        include_dclines=False,
        include_trafos=False,
        include_trafo3ws=False,
        include_tcsc=False,
        include_vsc=False,
        include_line_dc=False,
        include_out_of_service=False,
        include_switches=False,
        multi=True,
    )
    busbar = int(net.trafo["lv_bus"].iloc[0])
    simple = nx.Graph()
    for u, v, key in graph.edges(keys=True):
        element, index = key
        if element != "line":
            continue
        if simple.has_edge(int(u), int(v)):
            raise ValueError(f"parallel lines {index} and {simple.edges[u, v]['line']}: not a tree")
        simple.add_edge(int(u), int(v), line=int(index))
    n_lines = len(net.line)
    if busbar not in simple:
        raise ValueError(f"the LV busbar {busbar} carries no in-service line")
    component = nx.node_connected_component(simple, busbar)
    tree = simple.subgraph(component)
    if tree.number_of_edges() != tree.number_of_nodes() - 1:
        raise ValueError(
            f"the busbar's line graph has {tree.number_of_edges()} edges on "
            f"{tree.number_of_nodes()} buses: not a tree"
        )
    if tree.number_of_edges() != simple.number_of_edges():
        raise ValueError("an in-service line lies outside the LV busbar's tree")

    predecessor = {int(child): int(parent) for parent, child in nx.bfs_edges(tree, busbar)}
    hops = nx.single_source_shortest_path_length(tree, busbar)
    into = {child: int(tree.edges[parent, child]["line"]) for child, parent in predecessor.items()}
    parent_line = np.full(n_lines, -1, dtype=int)
    depth = np.full(n_lines, -1, dtype=int)
    child_bus = np.full(n_lines, -1, dtype=int)
    for child, parent in predecessor.items():
        line = into[child]
        child_bus[line] = int(child)
        depth[line] = int(hops[child])
        parent_line[line] = -1 if int(parent) == busbar else into[parent]

    in_tree = np.flatnonzero(child_bus >= 0)
    feeder_of = np.full(n_lines, -1, dtype=int)
    for line in in_tree:
        feeder_of[line] = int(rc.root_path(parent_line, int(line))[-1])
    std_type = np.array([str(value) for value in net.line["std_type"].to_numpy()], dtype=object)
    route_of = rc.routes(parent_line, std_type, feeder_of)
    checks = {
        "lv_busbar": busbar,
        "n_lines": n_lines,
        "n_lines_in_tree": int(in_tree.size),
        "n_buses_in_tree": int(tree.number_of_nodes()),
        "n_line_edges": int(simple.number_of_edges()),
        "cycles": 0,
        "is_tree": True,
        "lines_out_of_tree": [int(i) for i in np.flatnonzero(child_bus < 0)],
        "n_feeders": int(np.unique(feeder_of[in_tree]).size),
        "n_routes": int(np.unique(route_of).size),
        "df_all_one": bool(np.all(net.line["df"].to_numpy(float) == 1.0)),
        "parallel_all_one": bool(np.all(net.line["parallel"].to_numpy(int) == 1)),
        "all_in_service": bool(np.all(net.line["in_service"].to_numpy(bool))),
    }
    if in_tree.size != n_lines:
        raise ValueError(
            f"{n_lines - in_tree.size} of {n_lines} lines are not in the LV busbar's tree; "
            "the protocol's topology convention assumes a single radial LV line graph"
        )
    return Topology(parent_line, feeder_of, depth, std_type, route_of, child_bus, busbar, checks)


def downstream_buses(topology: Topology, line: int) -> np.ndarray:
    """The buses in the subtree below `line`, its own child bus included."""
    children: dict[int, list[int]] = {}
    for other in range(topology.parent_line.size):
        children.setdefault(int(topology.parent_line[other]), []).append(other)
    stack, out = [int(line)], []
    while stack:
        current = stack.pop()
        out.append(int(topology.child_bus[current]))
        stack.extend(children.get(current, []))
    return np.array(sorted(set(out)), dtype=int)


# --- C. availability, export and the cache -------------------------------------------------


def availability(net) -> tuple[np.ndarray, np.ndarray]:
    """(days x 96 x units) available PV and the units' `sn_mva` rating (protocol s. 4)."""
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    return arrays["sgen_p_mw"], net.sgen["sn_mva"].to_numpy(dtype=float)


def step_export(available: np.ndarray, rating: np.ndarray) -> np.ndarray:
    """(steps x levels) export in MWh: sum_i min(a_i, c . sn_i) x 0.25 (protocol s. 4)."""
    caps = np.asarray(rc.CAP_LEVELS, dtype=float)[:, None] * np.asarray(rating, dtype=float)[None]
    return np.minimum(np.asarray(available, dtype=float)[:, None, :], caps[None]).sum(axis=2) * 0.25


def cache_provenance(folder: Path, expected: dict, fingerprint_fn) -> dict:
    """The cache's `manifest.json`, the asserted fields, and whether its fingerprint can be
    recomputed. `fingerprint_fn` is the producing module's own function or None if it has none;
    the protocol forbids inventing one (Control E's provenance check)."""
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"{manifest_path} is missing; the cache has no provenance")
    manifest = json.loads(manifest_path.read_text())
    mismatched = {
        key: {"manifest": manifest.get(key), "expected": value}
        for key, value in expected.items()
        if manifest.get(key) != value
    }
    if mismatched:
        raise ValueError(f"{folder} does not match the network build: {mismatched}")
    out = {
        "folder": _rel(folder),
        "manifest": manifest,
        "asserted": sorted(expected),
        "fingerprint_function": None
        if fingerprint_fn is None
        else fingerprint_fn.__module__ + "." + fingerprint_fn.__name__,
        "fingerprint_recomputed": None,
        "fingerprint_matches": None,
    }
    if fingerprint_fn is None:
        out["fingerprint_note"] = (
            "the producing module exposes no fingerprint function; none was invented"
        )
    else:
        recomputed = fingerprint_fn()
        out["fingerprint_recomputed"] = recomputed
        out["fingerprint_matches"] = bool(recomputed == manifest.get("fingerprint"))
    missing = [day for day in DAYS if not (folder / f"day_{day:03d}.npz").exists()]
    out["missing_days"] = missing
    out["covers_days_35_364"] = not missing
    if missing:
        raise FileNotFoundError(f"{folder} is missing {len(missing)} of {len(DAYS)} days")
    return out


def nominal_folder(code: str) -> Path:
    return SENSE_CACHE / code / "nominal"


def nominal_provenance(code: str) -> dict:
    """The Phase 5 nominal cache's provenance: `pv_scale`, the NOMINAL variant (storage idle)
    and `fullstate.fingerprint`."""
    expected = {
        "network": code,
        "pv_scale": ds.pv_scale(code),
        "variant": asdict(ds.NOMINAL),
    }
    if expected["variant"]["storage"] != "idle":
        raise ValueError("the Phase 5 nominal variant must have idle storage")
    return cache_provenance(nominal_folder(code), expected, fullstate.fingerprint)


# --- D. the `tables` command ---------------------------------------------------------------


class Built(NamedTuple):
    tables: dict[str, rc.DecisionTable]
    index: dict[str, dict[str, np.ndarray]]
    diagnostics: dict


def build_tables(code: str, available: np.ndarray, rating: np.ndarray) -> Built:
    """Protocol s. 2 / s. 6: the P and E decision tables of one network, from the Phase 5
    nominal cache alone. Two passes over the cache: the first finds the table lines (P-or-E
    maximum loading above 70 %), the second keeps only those columns.

    NaNs are carried through: `DecisionTable.finite` turns any NaN at a (step, level) into an
    inadmissible level, which is the protocol's NaN rule, applied in the core.
    """
    folder = nominal_folder(code)
    daylight = {
        period: np.array(
            [
                (day, step)
                for day in DAYS
                if period_of(day) == period
                for step in np.flatnonzero(available[day].sum(axis=1) > 0.0)
            ],
            dtype=int,
        ).reshape(-1, 2)
        for period in PERIODS
    }
    strict = sum(int(v.shape[0]) for v in daylight.values())
    loose = sum(int((available[day].sum(axis=1) > 1e-9).sum()) for day in DAYS)
    n_lines = None
    running = {period: None for period in PERIODS}
    for day in DAYS:  # pass 1: the table-line mask only
        lit = np.flatnonzero(available[day].sum(axis=1) > 0.0)
        if lit.size == 0:
            continue
        with np.load(folder / f"day_{day:03d}.npz") as data:
            load = np.asarray(data["line"])[lit]
        n_lines = load.shape[2] if n_lines is None else n_lines
        finite = np.where(np.isfinite(load), load, -np.inf).max(axis=(0, 1))
        period = period_of(day)
        running[period] = finite if running[period] is None else np.fmax(running[period], finite)
    if n_lines is None:
        raise ValueError(f"{folder} yielded no daylight step")
    maxima = {
        period: (np.full(n_lines, -np.inf) if value is None else value)
        for period, value in running.items()
    }
    mask = rc.table_line_mask(maxima["P"], maxima["E"])
    line_ids = np.flatnonzero(mask)

    parts: dict[str, dict[str, list]] = {
        period: {"load": [], "trafo": [], "volt_ok": [], "export": [], "nan_levels": 0, "vdiff": 0}
        for period in PERIODS
    }
    for day in DAYS:  # pass 2: the tables, table lines only
        lit = np.flatnonzero(available[day].sum(axis=1) > 0.0)
        if lit.size == 0:
            continue
        with np.load(folder / f"day_{day:03d}.npz") as data:
            load = np.asarray(data["line"])[lit][:, :, line_ids]
            trafo = np.asarray(data["trafo"])[lit][:, :, 2]
            margins = np.asarray(data["margins"])[lit]
        over, under = margins[:, :, 0] <= 0.0, margins[:, :, 1] <= 0.0
        bucket = parts[period_of(day)]
        bucket["load"].append(load.astype(np.float32))
        bucket["trafo"].append(trafo.astype(np.float32))
        bucket["volt_ok"].append(over & under)
        bucket["export"].append(step_export(available[day][lit], rating))
        bucket["nan_levels"] += int((~np.isfinite(load).all(axis=2) | ~np.isfinite(trafo)).sum())
        bucket["vdiff"] += int((over & ~under).sum())  # the audit used the overvoltage margin only

    tables, index, diagnostics = {}, {}, {}
    for period in PERIODS:
        bucket = parts[period]
        if not bucket["load"]:
            raise ValueError(f"period {period} has no daylight step in {code}")
        tables[period] = rc.DecisionTable(
            load=np.concatenate(bucket["load"]),
            trafo=np.concatenate(bucket["trafo"]),
            volt_ok=np.concatenate(bucket["volt_ok"]),
            export=np.concatenate(bucket["export"]),
            line_ids=line_ids,
        )
        index[period] = {
            "day": daylight[period][:, 0],
            "step_of_day": daylight[period][:, 1],
        }
        diagnostics[period] = {
            "daylight_steps": int(daylight[period].shape[0]),
            "nan_step_levels": bucket["nan_levels"],
            "overvoltage_ok_but_undervoltage_not": bucket["vdiff"],
        }
    order = np.lexsort(
        (
            np.concatenate([index[p]["step_of_day"] for p in PERIODS]),
            np.concatenate([index[p]["day"] for p in PERIODS]),
        )
    )
    rank = np.empty(order.size, dtype=int)
    rank[order] = np.arange(order.size)
    offset = 0
    for period in PERIODS:
        size = index[period]["day"].size
        index[period]["step_index"] = rank[offset : offset + size]
        offset += size
    diagnostics["n_lines"] = int(n_lines)
    diagnostics["daylight_steps_total"] = strict
    diagnostics["daylight_steps_total_above_1e-9"] = loose
    diagnostics["max_loading_pct"] = {p: float(np.max(maxima[p])) for p in PERIODS}
    return Built(tables, index, diagnostics)


def concat_tables(tables: dict[str, rc.DecisionTable]) -> rc.DecisionTable:
    """One table over P and E (the certificate period, protocol s. 6). The table lines are
    chosen on P-or-E maxima, so both periods already share `line_ids`."""
    first = tables[PERIODS[0]]
    for period in PERIODS[1:]:
        if not np.array_equal(tables[period].line_ids, first.line_ids):
            raise ValueError("the periods disagree on the table lines")
    return rc.DecisionTable(
        load=np.concatenate([tables[p].load for p in PERIODS]),
        trafo=np.concatenate([tables[p].trafo for p in PERIODS]),
        volt_ok=np.concatenate([tables[p].volt_ok for p in PERIODS]),
        export=np.concatenate([tables[p].export for p in PERIODS]),
        line_ids=first.line_ids,
    )


def _pools(tables: dict[str, rc.DecisionTable], line_ids: np.ndarray, w: float) -> dict:
    """Protocol s. 6: the candidate pool per period, their union and the evaluation-only
    cables (the board's check that E adds nothing to P)."""
    per_period = {p: rc.candidate_pool(tables[p], 1.0 - w) for p in PERIODS}
    ids = {p: line_ids[per_period[p]] for p in PERIODS}
    union = np.array(sorted(set(ids["P"].tolist()) | set(ids["E"].tolist())), dtype=int)
    e_only = np.array(sorted(set(ids["E"].tolist()) - set(ids["P"].tolist())), dtype=int)
    return {
        "w": w,
        "threshold_pct": 100.0 * (1.0 - w),
        "P": ids["P"].tolist(),
        "E": ids["E"].tolist(),
        "P_union_E": union.tolist(),
        "E_only": e_only.tolist(),
        "n_P": int(ids["P"].size),
        "n_E": int(ids["E"].size),
        "n_P_union_E": int(union.size),
        "n_E_only": int(e_only.size),
        "columns_P": per_period["P"].tolist(),
        "columns_E": per_period["E"].tolist(),
    }


def _audit_cross_check(name: str, tables: dict[str, rc.DecisionTable]) -> dict:
    """Protocol s. 2: E + P export at recorded ratings and at the robust lower bounds, against
    the board's audit table. A mismatch is recorded with its size, never hidden."""
    cases = {
        "recorded": 100.0,
        f"robust_w{W_PRIMARY}": 100.0 * (1.0 - W_PRIMARY),
        f"robust_w{W_SECONDARY}": 100.0 * (1.0 - W_SECONDARY),
    }
    computed = {"nocap": float(sum(float(tables[p].export[:, 0].sum()) for p in PERIODS))}
    for key, threshold in cases.items():
        total = 0.0
        for period in PERIODS:
            level = rc.decide(tables[period], threshold, 100.0).level
            total += float(rc.export_total(tables[period], level))
        computed[key] = total
    audit = AUDIT_EXPORT_MWH[name]
    differences = {key: computed[key] - audit[key] for key in audit}
    worst = max(abs(value) for value in differences.values())
    return {
        "computed_MWh": computed,
        "audit_MWh": audit,
        "difference_MWh": differences,
        "max_abs_difference_MWh": worst,
        "tolerance_MWh": AUDIT_TOL_MWH,
        "pass": bool(worst <= AUDIT_TOL_MWH),
    }


def cmd_tables(args) -> dict:
    rc.check_protocol()
    name = args.network
    code = code_of(name)
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    topology = line_topology(net)
    available, rating = availability(net)
    provenance = nominal_provenance(code)
    built = build_tables(code, available, rating)
    tables, index, diagnostics = built.tables, built.index, built.diagnostics
    line_ids = tables["P"].line_ids

    pools = {f"w{w}": _pools(tables, line_ids, w) for w in (W_PRIMARY, W_SECONDARY)}
    pool_union = np.array(pools[f"w{W_PRIMARY}"]["P_union_E"], dtype=int)
    route_list = [
        {
            "route": int(route),
            "lines": [int(i) for i in np.flatnonzero(topology.route_of == route)],
            "std_type": str(topology.std_type[np.flatnonzero(topology.route_of == route)[0]]),
            "feeder": int(topology.feeder_of[np.flatnonzero(topology.route_of == route)[0]]),
        }
        for route in np.unique(topology.route_of)
    ]
    situation = {}
    for period in PERIODS:
        labels = rc.situation(tables[period], 100.0 * (1.0 - W_PRIMARY), 100.0 * (1.0 + W_PRIMARY))
        situation[period] = {
            "n_steps": int(labels.size),
            "share_situation_1": float(np.mean(labels == 1)),
            "share_situation_2": float(np.mean(labels == 2)),
        }
    curtailed = {}
    for period in PERIODS:
        decision = rc.decide(tables[period], 100.0, 100.0)
        curtailed[period] = {
            "curtailed_steps": int(np.count_nonzero(decision.level > 0)),
            "infeasible_at_zero": int(np.count_nonzero(decision.infeasible)),
            "n_steps": int(decision.level.size),
        }

    arrays: dict[str, np.ndarray] = {
        "line_ids": line_ids,
        "parent_line": topology.parent_line,
        "feeder_of_line": topology.feeder_of,
        "depth": topology.depth,
        "route_of_line": topology.route_of,
        "child_bus": topology.child_bus,
        "std_type": np.array([str(s) for s in topology.std_type]),
    }
    for period in PERIODS:
        table = tables[period]
        arrays[f"{period}_load"] = table.load
        arrays[f"{period}_trafo"] = table.trafo
        arrays[f"{period}_volt_ok"] = table.volt_ok
        arrays[f"{period}_export"] = table.export
        arrays[f"{period}_day"] = index[period]["day"]
        arrays[f"{period}_step_of_day"] = index[period]["step_of_day"]
        arrays[f"{period}_step_index"] = index[period]["step_index"]
    npz_path = rc.write_npz_once(RUNS / f"tables_{name}.npz", **arrays)

    record = _stamp(
        "tables",
        network=name,
        network_code=code,
        pv_scale=ds.pv_scale(code),
        new_ac_solves=0,
        cache=provenance,
        topology=topology.checks,
        counts={
            "n_lines": diagnostics["n_lines"],
            "n_table_lines": int(line_ids.size),
            "table_lines": line_ids.tolist(),
            "table_loading_threshold_pct": rc.TABLE_LOADING_PCT,
            "daylight_steps": {p: diagnostics[p]["daylight_steps"] for p in PERIODS},
            "daylight_steps_total": diagnostics["daylight_steps_total"],
            "daylight_steps_total_above_1e-9": diagnostics["daylight_steps_total_above_1e-9"],
            "nan_step_levels": {p: diagnostics[p]["nan_step_levels"] for p in PERIODS},
            "overvoltage_ok_but_undervoltage_not": {
                p: diagnostics[p]["overvoltage_ok_but_undervoltage_not"] for p in PERIODS
            },
            "max_loading_pct": diagnostics["max_loading_pct"],
        },
        pools=pools,
        routes={"n_routes": len(route_list), "list": route_list},
        root_paths={
            str(int(line)): rc.root_path(topology.parent_line, int(line)).tolist()
            for line in pool_union
        },
        feeders={
            "feeder_of_line": topology.feeder_of.tolist(),
            "feeder_heads": sorted({int(f) for f in topology.feeder_of}),
            "feeder_of_pool_lines": {
                str(int(line)): int(topology.feeder_of[int(line)]) for line in pool_union
            },
        },
        situation_u2_w02=situation,
        curtailed_recorded=curtailed,
        audit_cross_check=_audit_cross_check(name, tables),
        arrays_written=_rel(npz_path),
    )
    path = rc.write_json_once(RESULTS / f"tables_{name}.json", record)
    print(f"tables {name}: {_rel(path)}")
    print(
        f"  table lines {int(line_ids.size)}/{diagnostics['n_lines']}, "
        f"daylight P/E {diagnostics['P']['daylight_steps']}/{diagnostics['E']['daylight_steps']}, "
        f"pool w0.2 P/E {pools['w0.2']['n_P']}/{pools['w0.2']['n_E']}, "
        f"audit {'PASS' if record['audit_cross_check']['pass'] else 'FAIL'} "
        f"(max |d| {record['audit_cross_check']['max_abs_difference_MWh']:.2e} MWh)"
    )
    return record


# --- E. loading a written table ------------------------------------------------------------


class Loaded(NamedTuple):
    tables: dict[str, rc.DecisionTable]
    index: dict[str, dict[str, np.ndarray]]
    parent_line: np.ndarray
    route_of_line: np.ndarray
    result: dict


#: `ratings_core.py` as it stood when task 2 (AKK-76) wrote the decision tables, under the
#: protocol's revision 2.1. Task 3 (AKK-77) re-pinned the protocol hash to revision 2.2 and
#: task 3a-fix (AKK-78) moved that pin onto the as-executed text (amendment A1); **no
#: numerical code changed in either**, and
#: the decision tables are write-once artefacts that must not be regenerated. The one
#: predecessor hash is therefore accepted by name, and the accepted hash is recorded in every
#: artefact that reads a table, so the substitution is auditable rather than silent.
CORE_SHA256_PREDECESSORS = ("94025e20718d7d8efda42573310ff240a2ea7a5151623c6217a1af18361d6273",)


def load_tables(name: str) -> Loaded:
    """Re-read `runs/tables_<K>.npz` and `results/tables_<K>.json` (zero solves, no cache)."""
    npz_path, json_path = RUNS / f"tables_{name}.npz", RESULTS / f"tables_{name}.json"
    for path in (npz_path, json_path):
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run `tables --network {name}` first")
    result = json.loads(json_path.read_text())
    written_by = result["code_sha256"]["ratings_core.py"]
    if written_by not in (code_hashes()["ratings_core.py"], *CORE_SHA256_PREDECESSORS):
        raise ValueError(f"{json_path} was written by a different ratings_core.py")
    with np.load(npz_path, allow_pickle=False) as data:
        line_ids = data["line_ids"]
        tables = {
            period: rc.DecisionTable(
                load=data[f"{period}_load"],
                trafo=data[f"{period}_trafo"],
                volt_ok=data[f"{period}_volt_ok"],
                export=data[f"{period}_export"],
                line_ids=line_ids,
            )
            for period in PERIODS
        }
        index = {
            period: {key: data[f"{period}_{key}"] for key in ("day", "step_of_day", "step_index")}
            for period in PERIODS
        }
        parent_line = data["parent_line"]
        route_of_line = data["route_of_line"]
    return Loaded(tables, index, parent_line, route_of_line, result)


# --- F. Control D: a rating-only change (the only solves in this file) ---------------------


_LEDGER: dict = {}


def _free_path(stem: str) -> Path:
    for suffix in itertools.count():
        path = RESULTS / (f"{stem}.json" if suffix == 0 else f"{stem}_{suffix}.json")
        if not path.exists():
            return path
    raise AssertionError("unreachable")


def _install_abort_handler(stem: str) -> None:
    """Protocol s. 10 (foreground only, write-once): a SIGTERM or SIGINT during the solves
    writes an abort record with the ledger as it stands, then re-raises the default action."""

    def handler(signum, frame):  # noqa: ARG001
        _LEDGER["aborted"] = {"signal": int(signum), "name": signal.Signals(signum).name}
        try:
            rc.write_json_once(_free_path(stem), _LEDGER)
        except OSError:  # a write failure must not mask the signal
            pass
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, handler)


def _compare(label: str, a: np.ndarray, b: np.ndarray, tol: float) -> dict:
    """Maximum absolute and relative difference of two state vectors."""
    a = np.asarray(a, dtype=float).reshape(-1)
    b = np.asarray(b, dtype=float).reshape(-1)
    if a.shape != b.shape:
        raise ValueError(f"{label}: shapes {a.shape} vs {b.shape}")
    absolute = np.abs(a - b)
    scale = np.maximum(np.abs(a), np.abs(b))
    relative = np.divide(absolute, scale, out=np.zeros_like(absolute), where=scale > 0)
    return {
        "quantity": label,
        "n": int(a.size),
        "max_abs_diff": float(absolute.max()) if a.size else 0.0,
        "max_rel_diff": float(relative.max()) if a.size else 0.0,
        "argmax_abs": int(absolute.argmax()) if a.size else -1,
        "n_zero_scale": int(np.count_nonzero(scale == 0)),
        "tolerance_rel": tol,
        "within_tolerance": bool(relative.max() <= tol) if a.size else True,
    }


def cmd_control_d(args) -> dict:  # noqa: ARG001
    rc.check_protocol()
    name = CONTROL_D_NETWORK
    code = code_of(name)
    loaded = load_tables(name)
    pool = np.array(loaded.result["pools"][f"w{W_PRIMARY}"]["P_union_E"], dtype=int)
    if CONTROL_D_LINE not in pool.tolist():
        raise ValueError(f"line {CONTROL_D_LINE} is not a pool line of {name}: {pool.tolist()}")

    per_day: dict[int, int] = {}
    for period in PERIODS:
        level = rc.decide(loaded.tables[period], 100.0, 100.0).level
        days = loaded.index[period]["day"]
        for day in np.unique(days):
            mask = days == day
            per_day[int(day)] = int(np.count_nonzero(level[mask] > 0))
    day = min(per_day, key=lambda d: (-per_day[d], d))

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    available, rating = availability(net)
    if not np.allclose(rating, net.sgen["sn_mva"].to_numpy(float)):
        raise AssertionError("the PV rating is not sn_mva")
    sets = ds.day_sets(available_arrays(net), day, rating, 1)
    totals = available[day].sum(axis=1)
    step = int(np.argmax(totals))  # ties go to the earliest step
    injections = {
        "load_p_mw": np.asarray(sets["load_p_mw"][0, step], dtype=float),
        "load_q_mvar": np.asarray(sets["load_q_mvar"][0, step], dtype=float),
        "sgen_p_mw": np.asarray(sets["sgen_p_mw"][0, step], dtype=float),
        "storage_p_mw": np.zeros(len(net.storage), dtype=float),
    }

    _LEDGER.clear()
    _LEDGER.update(
        _stamp("control-d"),
        network=name,
        network_code=code,
        line=CONTROL_D_LINE,
        rating_factor=CONTROL_D_RATING_FACTOR,
        day=day,
        day_expected_by_board=144,
        day_matches_board=bool(day == 144),
        curtailed_daylight_steps_on_day=per_day[day],
        curtailed_steps_per_day_top5=[
            {"day": int(d), "curtailed": int(per_day[d])}
            for d in sorted(per_day, key=lambda d: (-per_day[d], d))[:5]
        ],
        step_of_day=step,
        cap_level_index=0,
        cap_level=float(rc.CAP_LEVELS[0]),
        available_pv_mw=float(totals[step]),
        storage_units=int(len(net.storage)),
        max_solves_allowed=CONTROL_D_MAX_SOLVES,
        solves_attempted=0,
        solve_ledger=[],
        aborted=None,
    )
    _install_abort_handler("control_d_abort")

    def solve(label: str, target):
        if _LEDGER["solves_attempted"] >= CONTROL_D_MAX_SOLVES:
            raise RuntimeError(f"the Control D solve ceiling of {CONTROL_D_MAX_SOLVES} is reached")
        _LEDGER["solves_attempted"] += 1
        entry = {
            "index": _LEDGER["solves_attempted"],
            "label": label,
            "converged": None,
            "seconds": None,
        }
        _LEDGER["solve_ledger"].append(entry)
        solver = ds.VariantSolver(target, ds.NOMINAL)
        solver.reset()
        started = time.perf_counter()
        margins = solver.solve(
            injections["load_p_mw"],
            injections["load_q_mvar"],
            injections["sgen_p_mw"],
            injections["storage_p_mw"],
        )
        entry["seconds"] = time.perf_counter() - started
        entry["converged"] = bool(np.all(np.isfinite(margins)))
        entry["margins"] = [float(v) for v in margins]
        if not entry["converged"]:
            raise RuntimeError(f"the {label} flow did not converge")
        return solver.net

    written: list[Path] = []
    try:
        net_modified = copy.deepcopy(net)
        recorded = float(net_modified.line.at[CONTROL_D_LINE, "max_i_ka"])
        net_modified.line.at[CONTROL_D_LINE, "max_i_ka"] = recorded * CONTROL_D_RATING_FACTOR
        _LEDGER["max_i_ka"] = {
            "nominal": recorded,
            "modified": recorded * CONTROL_D_RATING_FACTOR,
        }
        solved_nominal = solve("nominal", net)
        solved_modified = solve("rating_x_0.8", net_modified)

        buses = fullstate.lv_buses(net)
        state_nominal = {
            "vm_pu": solved_nominal.res_bus["vm_pu"].to_numpy(float),
            "i_ka": solved_nominal.res_line["i_ka"].to_numpy(float),
            "loading_percent": solved_nominal.res_line["loading_percent"].to_numpy(float),
            "vm_lv": solved_nominal.res_bus.loc[buses, "vm_pu"].to_numpy(float),
        }
        state_modified = {
            "vm_pu": solved_modified.res_bus["vm_pu"].to_numpy(float),
            "i_ka": solved_modified.res_line["i_ka"].to_numpy(float),
            "loading_percent": solved_modified.res_line["loading_percent"].to_numpy(float),
        }
        _LEDGER["rating_only_change"] = {
            "comparisons": [
                _compare(
                    "res_bus.vm_pu",
                    state_nominal["vm_pu"],
                    state_modified["vm_pu"],
                    CONTROL_D_REL_TOL,
                ),  # noqa: E501
                _compare(
                    "res_line.i_ka",
                    state_nominal["i_ka"],
                    state_modified["i_ka"],
                    CONTROL_D_REL_TOL,
                ),  # noqa: E501
            ],
            "loading_percent_changes_as_expected": _compare(
                "res_line.loading_percent (the only quantity that must change)",
                state_nominal["loading_percent"],
                state_modified["loading_percent"],
                np.inf,
            ),
        }
        _LEDGER["rating_only_change"]["pass"] = all(
            entry["within_tolerance"] for entry in _LEDGER["rating_only_change"]["comparisons"]
        )

        with np.load(nominal_folder(code) / f"day_{day:03d}.npz") as data:
            cached = {
                "vm": np.asarray(data["vm"][step, 0], dtype=float),
                "line": np.asarray(data["line"][step, 0], dtype=float),
                "trafo": np.asarray(data["trafo"][step, 0], dtype=float),
            }
        _LEDGER["cache_reconstruction"] = {
            "cache": nominal_provenance(code),
            "note": (
                "the cache stores float32 line loading in % of the record and LV-bus voltages "
                "in the `fullstate.lv_buses` order; the solve here is a fresh Newton-Raphson "
                "start, so the residual is solver tolerance plus float32 storage"
            ),
            "comparisons": [
                _compare("vm (LV buses) vs cache", state_nominal["vm_lv"], cached["vm"], np.inf),
                _compare(
                    "res_line.loading_percent vs cache",
                    state_nominal["loading_percent"],
                    cached["line"],
                    np.inf,
                ),
            ],
            "trafo_loading_percent": {
                "solved": float(solved_nominal.res_trafo["loading_percent"].iloc[0]),
                "cached": float(cached["trafo"][2]),
            },
        }
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGINT, signal.SIG_DFL)
        written.append(rc.write_json_once(_free_path("control_d"), dict(_LEDGER)))
    print(f"control-d: {_rel(written[-1])}")
    print(
        f"  day {day} (board 144), step {step}, solves {_LEDGER['solves_attempted']}, "
        f"rating-only {'PASS' if _LEDGER['rating_only_change']['pass'] else 'FAIL'}"
    )
    return dict(_LEDGER)


def available_arrays(net) -> dict:
    """`grid_study.daily_arrays` of one network (all profile keys, not only the PV)."""
    return grid_study.daily_arrays(grid.absolute_profiles(net))


# --- G. Control E: impedance plus rating ---------------------------------------------------


def _distribution(chunks: list[np.ndarray], unit: str) -> dict:
    """Exact median, 95th percentile and maximum of per-day chunks, which are concatenated
    once in float32 and then released (the full-year arrays run to tens of millions of
    entries, so nothing is kept twice)."""
    values = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
    chunks.clear()
    n_all = int(values.size)
    if not np.isfinite(values).all():
        values = values[np.isfinite(values)]
    if values.size == 0:
        return {
            "unit": unit,
            "n": 0,
            "n_non_finite": n_all,
            "median": None,
            "p95": None,
            "max": None,
        }  # noqa: E501
    return {
        "unit": unit,
        "n": int(values.size),
        "n_non_finite": n_all - int(values.size),
        "median": float(np.median(values)),
        "p95": float(np.percentile(values, 95)),
        "max": float(values.max()),
        "mean": float(values.mean()),
    }


def cmd_control_e(args) -> dict:
    rc.check_protocol()
    name = args.network
    code = code_of(name)
    net_nominal = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    net_local = stress.stress_network(code, "line_local")
    modified = int(stress.local_line(net_nominal, sensing.network_layout(net_nominal)))
    topology = line_topology(net_nominal)

    provenance = {
        "phase5_nominal": nominal_provenance(code),
        "phase8_line_local": cache_provenance(
            ROBUST_CACHE / code / "line_local",
            {"network": code, "pv_scale": ds.pv_scale(code), "condition": "line_local"},
            stress.fingerprint,
        ),
    }
    available_nominal, rating_nominal = availability(net_nominal)
    available_local, rating_local = availability(net_local)
    alignment = {
        "pv_scale_equal": bool(
            provenance["phase5_nominal"]["manifest"]["pv_scale"]
            == provenance["phase8_line_local"]["manifest"]["pv_scale"]
        ),
        "variant_nominal": provenance["phase5_nominal"]["manifest"]["variant"],
        "condition_line_local": provenance["phase8_line_local"]["manifest"]["condition"],
        "both_cover_days_35_364": bool(
            provenance["phase5_nominal"]["covers_days_35_364"]
            and provenance["phase8_line_local"]["covers_days_35_364"]
        ),
        "availability_identical": bool(np.array_equal(available_nominal, available_local)),
        "pv_rating_identical": bool(np.array_equal(rating_nominal, rating_local)),
        "modified_line": modified,
        "modified_line_std_type": str(topology.std_type[modified]),
        "modified_line_depth": int(topology.depth[modified]),
        "line_rating_factor": stress.LINE_RATING_FACTOR,
        "line_r_factor": stress.LINE_R_FACTOR,
    }
    alignment["pass"] = bool(
        alignment["pv_scale_equal"]
        and alignment["both_cover_days_35_364"]
        and alignment["availability_identical"]
        and alignment["pv_rating_identical"]
        and provenance["phase5_nominal"]["fingerprint_matches"]
        and provenance["phase8_line_local"]["fingerprint_matches"]
    )
    if not alignment["pass"]:
        alignment["verdict"] = "NOT COMPARABLE (protocol s. 12); H1-H5 are not blocked"

    below = downstream_buses(topology, modified)
    lv_buses = fullstate.lv_buses(net_nominal)
    below_columns = np.flatnonzero(np.isin(lv_buses, below))
    other_lines = np.array([j for j in range(len(net_nominal.line)) if j != modified], dtype=int)
    recorded = float(net_nominal.line.at[modified, "max_i_ka"])

    chunks: dict[str, list[np.ndarray]] = {
        "cable_rel": [],
        "cable_abs": [],
        "other": [],
        "trafo": [],
        "vm_all": [],
        "vm_below": [],
    }
    invisible = {"steps": 0, "invisible": 0, "true_over": 0, "model_ok": 0, "n_nan": 0}
    for day in DAYS:
        lit = np.flatnonzero(available_nominal[day].sum(axis=1) > 0.0)
        if lit.size == 0:
            continue
        with np.load(nominal_folder(code) / f"day_{day:03d}.npz") as data:
            nominal_line = np.asarray(data["line"][lit], dtype=float)
            nominal_trafo = np.asarray(data["trafo"][lit, :, 0], dtype=float)
            nominal_vm = np.asarray(data["vm"][lit], dtype=float)
        with np.load(ROBUST_CACHE / code / "line_local" / f"day_{day:03d}.npz") as data:
            local_line_pct = np.asarray(data["line"][lit], dtype=float)
            local_trafo = np.asarray(data["trafo"][lit, :, 0], dtype=float)
            local_vm = np.asarray(data["vm"][lit], dtype=float)
        # currents compared as currents: the modified cable's loading is in % of its REDUCED
        # record, so x 0.8 puts it back in % of the nominal record (protocol s. 8, Control E).
        nominal_cable = nominal_line[:, :, modified]
        local_cable = local_line_pct[:, :, modified] * stress.LINE_RATING_FACTOR
        delta = np.abs(local_cable - nominal_cable)
        chunks["cable_abs"].append(delta.ravel().astype(np.float32))
        with np.errstate(divide="ignore", invalid="ignore"):
            chunks["cable_rel"].append(
                np.where(nominal_cable > 0.0, 100.0 * delta / nominal_cable, np.nan)
                .ravel()
                .astype(np.float32)
            )
        chunks["other"].append(
            np.abs(local_line_pct[:, :, other_lines] - nominal_line[:, :, other_lines])
            .ravel()
            .astype(np.float32)
        )
        chunks["trafo"].append(np.abs(local_trafo - nominal_trafo).ravel().astype(np.float32))
        delta_vm = np.abs(local_vm - nominal_vm)
        chunks["vm_all"].append(delta_vm.ravel().astype(np.float32))
        if below_columns.size:
            chunks["vm_below"].append(delta_vm[:, :, below_columns].ravel().astype(np.float32))
        # the Phase 8 "invisible" mechanism: true utilisation = the line_local loading, which
        # pandapower already normalises by the reduced (0.8 x record) rating.
        true_utilisation = local_line_pct[:, :, modified]
        both = np.isfinite(true_utilisation) & np.isfinite(nominal_cable)
        invisible["steps"] += int(both.size)
        invisible["n_nan"] += int(np.count_nonzero(~both))
        invisible["true_over"] += int(np.count_nonzero(both & (true_utilisation > 100.5)))
        invisible["model_ok"] += int(np.count_nonzero(both & (nominal_cable <= 100.0)))
        invisible["invisible"] += int(
            np.count_nonzero(both & (true_utilisation > 100.5) & (nominal_cable <= 100.0))
        )

    denominator = invisible["steps"] - invisible["n_nan"]
    distributions = {
        "modified_cable_abs_delta_current_pct_of_record": _distribution(
            chunks["cable_abs"], "percentage points of the nominal record"
        ),
        "modified_cable_rel_delta_current": _distribution(
            chunks["cable_rel"], "% of its nominal current"
        ),
        "other_lines_abs_delta_loading": _distribution(
            chunks["other"], "percentage points of loading"
        ),
        "trafo_abs_delta_p": _distribution(chunks["trafo"], "MW"),
        "vm_abs_delta_all_buses": _distribution(chunks["vm_all"], "p.u."),
        "vm_abs_delta_downstream_buses": _distribution(chunks["vm_below"], "p.u."),
    }
    record = _stamp(
        "control-e",
        network=name,
        network_code=code,
        new_ac_solves=0,
        provenance=provenance,
        alignment=alignment,
        modified_cable={
            "line": modified,
            "max_i_ka_record": recorded,
            "max_i_ka_modified": recorded * stress.LINE_RATING_FACTOR,
            "std_type": str(topology.std_type[modified]),
            "child_bus": int(topology.child_bus[modified]),
            "downstream_buses": below.tolist(),
            "n_downstream_lv_bus_columns": int(below_columns.size),
        },
        counts={
            "daylight_steps": int(invisible["steps"] // rc.N_LEVELS),
            "step_levels": invisible["steps"],
            "step_levels_with_nan": invisible["n_nan"],
            "n_other_lines": int(other_lines.size),
            "n_lv_buses": int(lv_buses.size),
        },
        distributions=distributions,
        invisible_overload={
            "definition": (
                "true utilisation = line_local loading (already in % of 0.8 x record) > 100.5 %, "
                "while the nominal model's loading vs the record is <= 100 %"
            ),
            "n_step_levels": denominator,
            "n_true_over_100_5": invisible["true_over"],
            "n_model_at_or_below_100": invisible["model_ok"],
            "n_invisible": invisible["invisible"],
            "share_invisible": (invisible["invisible"] / denominator) if denominator else None,
            "share_of_true_over_that_is_invisible": (
                invisible["invisible"] / invisible["true_over"] if invisible["true_over"] else None
            ),
        },
    )
    path = rc.write_json_once(RESULTS / f"control_e_{name}.json", record)
    print(f"control-e {name}: {_rel(path)}")
    print(
        f"  line {modified}, alignment {'PASS' if alignment['pass'] else 'NOT COMPARABLE'}, "
        f"invisible {invisible['invisible']}/{denominator}"
    )
    return record


# --- H. the pilot timing -------------------------------------------------------------------


class Timer:
    """Wall and CPU seconds of one named stage; CPU time drives the s. 10 projection."""

    def __init__(self) -> None:
        self.stages: dict[str, dict] = {}

    def run(self, label: str, fn, **meta):
        wall, cpu = time.perf_counter(), time.process_time()
        value = fn()
        entry = {
            "wall_s": time.perf_counter() - wall,
            "cpu_s": time.process_time() - cpu,
            **meta,
        }
        self.stages[label] = entry
        return value

    @property
    def cpu_total(self) -> float:
        return float(sum(entry["cpu_s"] for entry in self.stages.values()))

    @property
    def wall_total(self) -> float:
        return float(sum(entry["wall_s"] for entry in self.stages.values()))


def _verified_export(
    table: rc.DecisionTable, columns, rho_true: np.ndarray, lb: float
) -> np.ndarray:
    """Export per draw after verifying `columns`, through the public belief path: the revealed
    rho for the verified columns, the believed lower bound elsewhere (protocol s. 6)."""
    sel = np.asarray(columns, dtype=int).reshape(-1)
    mask = np.zeros(table.n_table, dtype=bool)
    mask[sel] = True
    revealed = rc.reveal(sel, rho_true, table.n_table)
    thresholds = rc.beliefs("B7", lb, mask, revealed, n_lines=table.n_table)
    level = rc.decide(table, thresholds, 100.0).level
    return np.atleast_1d(rc.export_total(table, np.atleast_2d(level)))


def cmd_pilot(args) -> dict:  # noqa: ARG001
    rc.check_protocol()
    name, model, w = PILOT_NETWORK, PILOT_MODEL, W_PRIMARY
    loaded = load_tables(name)
    tables = loaded.tables
    table_p, table_e = tables["P"], tables["E"]
    certificate = concat_tables(tables)
    bounds = rc.rho_bounds(model, w)
    lb = bounds.line_lb

    pool_p = rc.candidate_pool(table_p, lb)
    pool_pe = rc.candidate_pool(certificate, lb)
    route_of_column = loaded.route_of_line[table_p.line_ids]
    unit_groups = rc.groups_from_routes(route_of_column, pool_p)
    truth_rng = rc.rng_for(name, model, "truth")
    prior_rng = rc.rng_for(name, model, "prior")
    order_rng = rc.rng_for(name, model, "random_order")
    rho_truth = rc.sample_rho(model, table_p.n_table, truth_rng, PILOT_N_TRUTH, w=w, kind="truth")
    rho_prior = rc.sample_rho(model, table_p.n_table, prior_rng, PILOT_N_PRIOR, w=w, kind="prior")
    budgets = [k for k in PILOT_BUDGETS if k <= max(pool_p.size, 1)] or [1]
    k_max = max(budgets)
    #: the only consumer is OB below, whose subsets hold at most `PILOT_OB_KMAX` table
    #: **columns** -- the budget's unit count never sizes a reduction (amendment A2).
    reduction = rc.reduction_for(table_e, PILOT_OB_KMAX)

    timer = Timer()
    timer.run(
        "B0_B1_B2_B4_direct_policies",
        lambda: (
            [
                rc.outcome(
                    table_e,
                    rc.decide(
                        table_e,
                        rc.beliefs(policy, np.full(table_e.n_table, lb), n_lines=table_e.n_table),
                        100.0,
                    ).level,
                    rho_truth,
                    np.ones(PILOT_N_TRUTH),
                )
                for policy in ("B0", "B1", "B2")
            ]
            + [
                rc.outcome(
                    table_e,
                    rc.decide(table_e, 100.0 * rho_truth, 100.0).level,
                    rho_truth,
                    np.ones(PILOT_N_TRUTH),
                )
            ]
        ),  # noqa: E501
        n_truth=PILOT_N_TRUTH,
        policies=["B0", "B1", "B2", "B4"],
    )
    timer.run(
        "B3_scenario_robust",
        lambda: rc.outcome(
            table_e,
            rc.decide(
                table_e,
                rc.beliefs("B3", np.full(table_e.n_table, lb), None, rho_prior),
                100.0,
            ).level,
            rho_truth,
            np.ones(PILOT_N_TRUTH),
        ),
        n_prior=PILOT_N_PRIOR,
    )
    orders = timer.run(
        "B5_random_orders",
        lambda: rc.random_orders(pool_p, order_rng, 20),
        n_orders=20,
        pool=int(pool_p.size),
    )
    timer.run(
        "B5_evaluation",
        lambda: [
            _verified_export(table_e, order[:k], rho_truth, lb) for k in budgets for order in orders
        ],
        budgets=budgets,
        evaluations=len(budgets) * len(orders),
    )
    rank_b6 = timer.run("B6_rank_loading", lambda: rc.rank_loading(table_p, pool_p))
    rank_b7 = timer.run("B7_rank_binding", lambda: rc.rank_binding(table_p, lb, pool_p))
    timer.run(
        "B6_B7_evaluation",
        lambda: [
            _verified_export(table_e, ranking.order[:k], rho_truth, lb)
            for ranking in (rank_b6, rank_b7)
            for k in budgets
        ],
        budgets=budgets,
    )
    greedy_b8 = timer.run(
        "B8_greedy_voi",
        lambda: rc.greedy_voi(table_p, rho_prior, lb, k_max),
        budget=k_max,
    )
    timer.stages["B8_greedy_voi"]["sets_evaluated"] = int(greedy_b8.evaluated)
    greedy_b8p = timer.run(
        "B8P_greedy_voi_pairs",
        lambda: rc.greedy_voi_pairs(table_p, rho_prior, lb, PILOT_B8P_BUDGET),
        budget=PILOT_B8P_BUDGET,
        note=(
            "timed at the budget H3b uses; the full run's k = 6 and 8 are projected by scaling "
            "linearly in greedy steps, which over-states them (the pair count shrinks)"
        ),
    )
    timer.stages["B8P_greedy_voi_pairs"]["sets_evaluated"] = int(greedy_b8p.evaluated)
    timer.stages["B8P_greedy_voi_pairs"]["pairs_evaluated"] = int(greedy_b8p.pairs)
    timer.run(
        "B8_B8P_evaluation",
        lambda: [
            _verified_export(table_e, result.segments[:k], rho_truth, lb)
            for result in (greedy_b8, greedy_b8p)
            for k in budgets
        ],
        budgets=budgets,
    )
    timer.run(
        "B9_route_rule_adaptive_per_draw",
        lambda: [
            _verified_export(
                table_e,
                rc.route_rule(
                    table_p,
                    lb,
                    loaded.parent_line,
                    k_max,
                    pool=pool_p,
                    revealed=rho_truth[draw],
                ).verified,
                rho_truth[draw : draw + 1],
                lb,
            )
            for draw in range(PILOT_N_TRUTH)
        ],
        n_truth=PILOT_N_TRUTH,
        note=(
            "adaptive (protocol s. 6, revision 2.1). `revealed` is handed in as the full true "
            "rho because `route_rule` reads it only at the columns it has already decided to "
            "verify, so it acts as the verification oracle's query interface; it is NOT a "
            "truth leak into the ranking, but task 3's information-boundary test should wrap "
            "it in a per-round `reveal` to make that mechanical rather than argued"
        ),
    )
    timer.run(
        "B9_static_once",
        lambda: rc.route_rule(table_p, lb, loaded.parent_line, k_max, pool=pool_p),
        note="descriptive: verified assets believed at the upper bound, no revealed rating",
    )
    timer.run(
        "B9_U4_route_units",
        lambda: rc.route_rule(
            table_p, lb, loaded.parent_line, k_max, pool=pool_p, unit_groups=unit_groups
        ),
        n_units=len(unit_groups),
    )
    top_blocking = rc.rank_binding(certificate, lb, pool_pe).order
    top_m = top_blocking[:PILOT_TOP_M]
    ob = timer.run(
        "OB_exhaustive_top10_k3",
        lambda: rc.exhaustive_best(table_e, rho_truth, lb, top_m, PILOT_OB_KMAX, red=reduction),
        n_truth=PILOT_N_TRUTH,
        top_m=int(top_m.size),
        kmax=PILOT_OB_KMAX,
    )
    timer.stages["OB_exhaustive_top10_k3"]["subsets"] = int(ob.n_subsets)
    h4 = timer.run(
        "H4_exhaustive_top10_k6_single_draw",
        lambda: rc.exhaustive_best(
            table_e,
            rho_truth[:1],
            lb,
            top_m,
            PILOT_H4_KMAX,
            red=rc.reduction_for(table_e, PILOT_H4_KMAX),
        ),
        n_truth=1,
        top_m=int(top_m.size),
        kmax=PILOT_H4_KMAX,
    )
    timer.stages["H4_exhaustive_top10_k6_single_draw"]["subsets"] = int(h4.n_subsets)

    #: the stages whose cost is paid once per (network, model); the rest scale with N_truth.
    fixed_stages = (
        "B3_scenario_robust",
        "B5_random_orders",
        "B6_rank_loading",
        "B7_rank_binding",
        "B8_greedy_voi",
        "B8P_greedy_voi_pairs",
        "B9_static_once",
        "B9_U4_route_units",
    )
    fixed_cpu = sum(timer.stages[s]["cpu_s"] for s in fixed_stages)
    draw_cpu = (timer.cpu_total - fixed_cpu) / PILOT_N_TRUTH
    #: B8P was timed at `PILOT_B8P_BUDGET` greedy steps, the full run wants `k_max`.
    b8p_cpu = timer.stages["B8P_greedy_voi_pairs"]["cpu_s"]
    b8p_top_up = b8p_cpu * (k_max / PILOT_B8P_BUDGET - 1.0)
    fixed_cpu += b8p_top_up

    sizes = {}
    for other in networks():
        path = RESULTS / f"tables_{other}.json"
        if not path.exists():
            continue
        other_result = json.loads(path.read_text())
        steps = sum(other_result["counts"]["daylight_steps"].values())
        pool = max(other_result["pools"][f"w{W_PRIMARY}"]["n_P"], 1)
        sizes[other] = {"steps": steps, "pool": pool, "work": steps * pool}
    base = sizes.get(name)
    if base is None:
        raise ValueError(f"the pilot needs results/tables_{name}.json for its own size")
    projection, total_cpu = {}, 0.0
    for other, size in sizes.items():
        models = list(MODELS_ALL)
        if other in TRANSFORMER_LIMITED:
            models.append("UT")
        if other in CABLE_LIMITED:
            models.append("U2P")
        scale = size["work"] / base["work"]
        per_combination = scale * (fixed_cpu + FULL_N_TRUTH * draw_cpu)
        projection[other] = {
            "models": models,
            "daylight_steps": size["steps"],
            "pool_w0.2_P": size["pool"],
            "work_scale_vs_pilot": scale,
            "cpu_s_per_model": per_combination,
            "cpu_s": per_combination * len(models),
        }
        total_cpu += per_combination * len(models)
    networks_missing = [n for n in networks() if n not in sizes]

    record = _stamp(
        "pilot",
        network=name,
        model=model,
        w=w,
        new_ac_solves=0,
        scored_results_written=False,
        reduced_sizes={
            "n_truth": PILOT_N_TRUTH,
            "n_prior": PILOT_N_PRIOR,
            "budgets": budgets,
            "top_m": PILOT_TOP_M,
            "ob_kmax": PILOT_OB_KMAX,
            "h4_kmax": PILOT_H4_KMAX,
        },
        table={
            "n_table_lines": int(table_p.n_table),
            "steps_P": int(table_p.n_steps),
            "steps_E": int(table_e.n_steps),
            "pool_P": pool_p.tolist(),
            "pool_P_union_E": pool_pe.tolist(),
            "n_route_units": len(unit_groups),
            "top_blocking_columns": top_m.tolist(),
        },
        timings=timer.stages,
        totals={
            "wall_s": timer.wall_total,
            "cpu_s": timer.cpu_total,
            "fixed_cpu_s": fixed_cpu,
            "fixed_stages": list(fixed_stages),
            "b8p_budget_top_up_cpu_s": b8p_top_up,
            "b8p_timed_budget": PILOT_B8P_BUDGET,
            "b8p_projected_budget": k_max,
            "cpu_s_per_truth_draw": draw_cpu,
        },
        projection={
            "method": (
                "cpu_s(network, model) = work_scale x (fixed_cpu_s + 200 x cpu_s_per_draw), "
                "with work_scale = (daylight steps x P-pool size) / the pilot's. semiurb5 has "
                "the largest pool of the six, so a linear scale over-states the pair search's "
                "pool-quadratic cost on every other network: the projection is conservative"
            ),
            "n_truth": FULL_N_TRUTH,
            "models_all_networks": list(MODELS_ALL),
            "models_transformer_limited_extra": ["UT"],
            "models_cable_limited_extra": ["U2P"],
            "per_network": projection,
            "networks_without_tables": networks_missing,
            "n_network_model_combinations": sum(
                len(entry["models"]) for entry in projection.values()
            ),
            "total_cpu_s": total_cpu,
            "total_cpu_h": total_cpu / 3600.0,
            "ceiling_cpu_h": CPU_HOUR_CEILING,
            "exceeds_ceiling": bool(total_cpu / 3600.0 > CPU_HOUR_CEILING),
            "recommended_n_truth": (
                FULL_N_TRUTH
                if total_cpu / 3600.0 <= CPU_HOUR_CEILING
                else max(
                    1,
                    int(FULL_N_TRUTH * CPU_HOUR_CEILING / max(total_cpu / 3600.0, 1e-12)),
                )
            ),
            "recommendation": (
                "no N_truth reduction needed"
                if total_cpu / 3600.0 <= CPU_HOUR_CEILING
                else "reduce N_truth (an OWNER/board decision and a protocol amendment)"
            ),
        },
    )
    path = rc.write_json_once(RESULTS / "pilot_timing.json", record)
    print(f"pilot: {_rel(path)}")
    print(
        f"  pilot cpu {timer.cpu_total:.2f} s (wall {timer.wall_total:.2f} s), "
        f"projection {total_cpu / 3600.0:.3f} CPU-h "
        f"({'over' if record['projection']['exceeds_ceiling'] else 'within'} "
        f"{CPU_HOUR_CEILING} CPU-h)"
    )
    return record


# --- I. the scored evaluation (protocol s. 6, s. 7) ----------------------------------------

#: the scored combinations: label -> (`ratings_core` model, the **believed** w). `U2w3` is U2
#: at the protocol's secondary width; `U2P` believes w = 0.2 while the truth is drawn at 0.3.
EVAL_MODELS = {
    "U0": ("U0", W_PRIMARY),
    "U2": ("U2", W_PRIMARY),
    "U2w3": ("U2", W_SECONDARY),
    "U3": ("U3", W_PRIMARY),
    "U4": ("U4", W_PRIMARY),
    "UT": ("UT", W_PRIMARY),
    "U2P": ("U2P", W_PRIMARY),
}
#: every network carries these; the rural networks add U-T and the cable-limited ones U2'.
EVAL_MODELS_EVERY_NETWORK = ("U0", "U2", "U2w3", "U3", "U4")

EVAL_BUDGETS = (1, 2, 3, 4, 6, 8)
BUDGET_ALL = "all"
N_TRUTH = FULL_N_TRUTH
N_PRIOR = PILOT_N_PRIOR
N_ORDERS = 20
TOP_M = PILOT_TOP_M
OB_KMAX = PILOT_OB_KMAX
H4_KMAX = PILOT_H4_KMAX
#: H4's criterion (protocol s. 7): oracle-equal on >= 95 % of E-steps in >= 95 % of draws.
H4_STEP_SHARE = 0.95
H4_DRAW_SHARE = 0.95
#: the policies scored at every budget. B5all is the weaker random reference of protocol s. 6
#: (drawn from **all** cables or routes, not from the candidate pool).
BUDGETED_POLICIES = ("B5", "B5all", "B6", "B7", "B8", "B8P", "B9", "B9static", "OB")
#: the policies with one decision each, scored once (protocol s. 6, s. 8 Control J).
DIRECT_POLICIES = ("B0", "B1", "B2", "B3", "B4", "VERIFYALL", "CAP0")
#: Control G reports the value of information of this many non-pool cables (0 by construction).
CONTROL_G_LINES = 3


def eval_models(network: str) -> list[str]:
    """The combinations of protocol s. 5 for one network, in the order they are scored."""
    models = list(EVAL_MODELS_EVERY_NETWORK)
    if network in TRANSFORMER_LIMITED:
        models.append("UT")
    if network in CABLE_LIMITED:
        models.append("U2P")
    return models


def _f(value):
    """A JSON-safe float: None where the value is not finite, so no artefact carries a NaN."""
    v = float(value)
    return v if np.isfinite(v) else None


def _dist(values) -> dict:
    """The protocol s. 9 read-out of a per-draw quantity: mean and the 5th/95th percentiles."""
    v = np.asarray(values, dtype=float).reshape(-1)
    fin = v[np.isfinite(v)]
    if fin.size == 0:
        return {"mean": None, "p5": None, "p95": None, "n": 0}
    return {
        "mean": _f(fin.mean()),
        "p5": _f(np.percentile(fin, 5)),
        "p95": _f(np.percentile(fin, 95)),
        "n": int(fin.size),
    }


class Scored(NamedTuple):
    """Per-draw outcome of one scored policy run: export in MWh, unsafe E-step count, the
    maximum severity in % above 100, and the chosen levels (only when asked for)."""

    export: np.ndarray
    unsafe: np.ndarray
    severity: np.ndarray
    level: np.ndarray | None


def _score_set(
    table: rc.DecisionTable,
    red: rc.Reduction | None,
    rho: np.ndarray,
    rho_t: np.ndarray,
    lb: float,
    lb_t: float,
    cols,
    verify_trafo: bool,
    *,
    keep_level: bool = False,
) -> Scored:
    """One verified set shared by every draw, scored on `table` against the truth draws.

    The verified columns take their revealed rho, every other column the believed lower
    bound, and the transformer either its revealed rho (`verify_trafo`) or `lb_t`. The s. 10
    reduction is used whenever it is wide enough; otherwise the full decision rule runs.
    """
    sel = np.array(sorted({int(c) for c in cols}), dtype=int)
    n = int(rho.shape[0])
    thr_t = 100.0 * (np.asarray(rho_t, float) if verify_trafo else np.full(n, float(lb_t)))
    if red is not None and (sel.size + 1 <= red.k or red.k >= table.n_table):
        thr_v = 100.0 * rho[:, sel] if sel.size else np.zeros((n, 0))
        dec = rc.decide_reduced(table, red, sel, thr_v, 100.0 * float(lb), thr_t, n_draws=n)
    else:
        thr = np.full((n, table.n_table), 100.0 * float(lb))
        if sel.size:
            thr[:, sel] = 100.0 * rho[:, sel]
        dec = rc.decide(table, thr, thr_t)
    level = np.atleast_2d(dec.level)
    out = rc.outcome(table, level, rho, rho_t)
    return Scored(
        np.atleast_1d(out.export),
        np.atleast_1d(out.unsafe_steps),
        np.atleast_1d(out.max_severity),
        level if keep_level else None,
    )


def _score_grouped(table, red, rho, rho_t, lb, lb_t, cols_per_draw, verify_trafo: bool) -> Scored:
    """`_score_set` for a policy whose verified set differs by draw (B9, OB). Draws that share
    a set are scored in one batch, which is exact and keeps the adaptive policies affordable."""
    n = int(rho.shape[0])
    export = np.empty(n)
    unsafe = np.empty(n)
    severity = np.empty(n)
    groups: dict[tuple, list[int]] = {}
    for draw, cols in enumerate(cols_per_draw):
        groups.setdefault(tuple(sorted({int(c) for c in cols})), []).append(draw)
    for cols, draws in groups.items():
        idx = np.array(draws, dtype=int)
        part = _score_set(table, red, rho[idx], rho_t[idx], lb, lb_t, cols, verify_trafo)
        export[idx], unsafe[idx], severity[idx] = part.export, part.unsafe, part.severity
    return Scored(export, unsafe, severity, None)


def _state_at(states, k):
    """Protocol s. 7's budget-matching rule: the last cumulative state whose realised **unit**
    count is <= k. A policy with no such state scores the empty set, which is B2 (R = 0)."""
    best = (0, 0, ())
    for units, segments, cols in states:
        if int(units) <= int(k):
            best = (int(units), int(segments), tuple(cols))
    return best


def _prefix_states(order, units: list[np.ndarray], budget: int):
    """Cumulative (units, segments, columns) after verifying the first 1, 2, ... units of a
    ranking. Used by B5, B5-all, B6 and B7, whose realised count always equals the budget."""
    states = [(0, 0, ())]
    cols: set[int] = set()
    for rank, unit in enumerate(np.asarray(order, dtype=int).reshape(-1)[: int(budget)], 1):
        cols |= {int(c) for c in units[int(unit)].tolist()}
        states.append((rank, len(cols), tuple(sorted(cols))))
    return states


def _greedy_states(result: rc.GreedyResult, units: list[np.ndarray], expected_of):
    """Cumulative states of a VoI greedy, at its **greedy-step** boundaries.

    B8 adds one unit per step, so every prefix is a step. B8P may add a pair atomically, and
    then its realised unit count steps by two and overshoots a budget (protocol s. 6,
    "Budgets"); the budget-matching rule of s. 7 needs the step boundaries, not every prefix.
    `GreedyResult` reports the units in the order chosen and the expected planning-period
    export **after each step**, so the boundaries are recovered by re-evaluating the expected
    export of each prefix and keeping the prefixes that reproduce `result.expected`.
    `expected_of(columns)` is the planning-period expected export of a verified set.
    """
    states = [(0, 0, ())]
    cols: set[int] = set()
    count = 0
    targets = [float(v) for v in np.asarray(result.expected, dtype=float)[1:]]
    reached = 0
    for unit in result.units:
        cols |= {int(c) for c in units[int(unit)].tolist()}
        count += 1
        if reached >= len(targets):
            break
        value = float(expected_of(tuple(sorted(cols))))
        if abs(value - targets[reached]) <= 1e-9 * max(1.0, abs(targets[reached])):
            states.append((count, len(cols), tuple(sorted(cols))))
            reached += 1
    if states[-1][0] != count:  # the boundaries did not reproduce: fall back to every prefix
        states = [(0, 0, ())]
        cols, count = set(), 0
        for unit in result.units:
            cols |= {int(c) for c in units[int(unit)].tolist()}
            count += 1
            states.append((count, len(cols), tuple(sorted(cols))))
    return states


# --- I.1 B9 behind a per-round reveal boundary ---------------------------------------------


def _route_rule_rounds(ask, budget: int):
    """Drive B9's rounds under a budget in **realised units** (protocol s. 6, step 3).

    `ask(asked, verified)` runs `rc.route_rule` for a budget of `asked` units, given the
    columns verified so far, and returns its `RouteRuleResult`.

    Round b asks for (the units realised so far) **+ 1**, not for b: one round may verify a
    whole co-blocking path, and a later request for fewer units than that path would return
    the same set and look like the rule's own termination. That misreading is the defect of
    protocol amendment A1, which this loop repairs. Because the rule is deterministic in what
    it is handed, each call reproduces the earlier rounds' picks and then takes one more, so
    the cumulative states are the rule's trajectory.

    Returns `(states, terminated)` with `states` the cumulative (realised units, realised
    segments, columns) and `terminated` True **only** when a round that asked for one more
    unit verified nothing new, i.e. no unverified candidate blocks. Stopping because the
    realised count reached the budget (possibly overshooting it) is not termination.
    """
    states = [(0, 0, ())]
    verified = np.zeros(0, dtype=int)
    previous = 0
    while previous < int(budget):
        result = ask(previous + 1, verified)
        n_units = int(result.n_units)
        if n_units == previous:
            return states, True
        cols = tuple(sorted(int(c) for c in result.verified.tolist()))
        states.append((n_units, int(result.n_segments), cols))
        verified = result.verified
        previous = n_units
    return states, False


def route_rule_static(
    table: rc.DecisionTable,
    lb: float,
    parent_line,
    budget: int,
    *,
    pool=None,
    unit_groups=None,
    ub: float | None = None,
    thr_trafo=100.0,
):
    """B9-static (protocol s. 6, reported descriptively) over the same round loop.

    No rating is ever revealed: a verified asset is believed at its upper bound `ub` during
    planning, so the trajectory is identical across truth draws. Returns `(states,
    terminated)` exactly as `_route_rule_rounds` does.
    """

    def ask(asked, verified):  # noqa: ARG001 -- the static rule is handed nothing
        return rc.route_rule(
            table,
            lb,
            parent_line,
            asked,
            pool=pool,
            unit_groups=unit_groups,
            ub=ub,
            thr_trafo=thr_trafo,
        )

    return _route_rule_rounds(ask, budget)


def route_rule_revealed(
    table: rc.DecisionTable,
    lb: float,
    parent_line,
    budget: int,
    rho_true,
    *,
    pool=None,
    unit_groups=None,
    thr_trafo=100.0,
    probe=None,
):
    """B9 (protocol s. 6, adaptive) behind a **per-round reveal wrapper**.

    `rc.route_rule` is called once per round and is handed, as `revealed`, nothing but
    `rc.reveal(the units verified so far, rho_true)`: the revealed rho of those units and NaN
    for every other column. The full truth vector therefore never reaches the rule, so the
    information boundary of protocol s. 6 is mechanical instead of argued (the pilot's note).

    Each round asks for (the units realised so far) + 1 and the reveal boundary is applied
    per round; see `_route_rule_rounds` for the round loop and amendment A1 for the defect it
    repairs. Returns `(states, terminated)` as that function does.
    """

    def ask(asked, verified):
        revealed = rc.reveal(verified, rho_true, table.n_table)
        if probe is not None:
            probe(np.asarray(verified, dtype=int), revealed)
        return rc.route_rule(
            table,
            lb,
            parent_line,
            asked,
            pool=pool,
            unit_groups=unit_groups,
            revealed=revealed,
            thr_trafo=thr_trafo,
        )

    return _route_rule_rounds(ask, budget)


# --- I.2 the two exhaustive searches (OB and H4), protocol s. 10's reduction ----------------


class SubsetEngine:
    """Every subset of the top-m certificate candidates, scored under truth, as bit tests.

    For a subset S of the m candidates a (step, level) is admissible exactly when

    * the **base** is admissible: the voltage margins, finiteness, the transformer, and every
      column outside the candidate list within the believed lower bound;
    * every candidate **outside** S is within the lower bound -- the m-bit mask `fl`, which is
      the same for every draw;
    * every candidate **inside** S is within its revealed true rating -- the mask `ft`, one
      per draw.

    So a subset costs two integer comparisons over the (step, level) grid rather than a
    decision scan per column, which is protocol s. 10's reduction stated as a bitmask.

    **The row restriction.** Verification can only raise a believed threshold whenever
    rho >= lb (U0, U2, U3, U4), so the oracle's level <= a subset's level <= B2's level. On
    every step where B2 already equals the oracle, every subset equals both, so only the
    disagreeing steps are kept. The squeeze is **asserted** draw by draw; where it does not
    hold (U2', whose truth can fall below the believed bound) every step is kept instead.
    """

    def __init__(
        self,
        table: rc.DecisionTable,
        pool,
        rho: np.ndarray,
        lb: float,
        lb_t: float,
        b2_level: np.ndarray,
        oracle_level: np.ndarray,
        *,
        restrict: bool,
    ) -> None:
        self.pool = np.asarray(pool, dtype=int).reshape(-1)
        self.m = int(self.pool.size)
        if self.m > 31:
            raise ValueError(f"the subset engine takes at most 31 candidates, got {self.m}")
        self.n_steps = int(table.n_steps)
        self.restricted = bool(restrict)
        changeable = (oracle_level != b2_level[None, :]).any(axis=0)
        self.rows = np.flatnonzero(changeable) if restrict else np.arange(table.n_steps)
        rows = self.rows
        self.b2_level = np.asarray(b2_level, dtype=np.intp)
        self.oracle_level = np.asarray(oracle_level, dtype=np.intp)
        self.export_rows = table.export[rows]
        load = np.where(np.isfinite(table.load[rows]), table.load[rows], np.inf)
        candidates = load[:, :, self.pool]
        others = np.setdiff1d(np.arange(table.n_table), self.pool)
        base = table.volt_ok[rows] & table.finite[rows]
        base &= table.trafo[rows] <= 100.0 * float(lb_t)
        if others.size:
            base &= load[:, :, others].max(axis=2) <= 100.0 * float(lb)
        self.base = base
        bits = (1 << np.arange(self.m)).astype(np.int32)
        self.fl = ((candidates > 100.0 * float(lb)) * bits).sum(axis=2).astype(np.int32)
        self.candidates = candidates
        self.bits = bits
        self.rho_pool = np.asarray(rho, dtype=float)[:, self.pool]

    def ft(self, draw: int) -> np.ndarray:
        """The "inside S exceeds its true rating" mask of one draw."""
        over = self.candidates > 100.0 * self.rho_pool[draw][None, None, :]
        return (over * self.bits).sum(axis=2).astype(np.int32)

    def levels(self, ft: np.ndarray, mask: int) -> np.ndarray:
        ok = self.base & ((self.fl & ~np.int32(mask)) == 0) & ((ft & np.int32(mask)) == 0)
        any_ok = ok.any(axis=1)
        return np.where(any_ok, np.argmax(ok, axis=1), rc.LEVEL_ZERO).astype(np.intp)

    def mask_of(self, combo) -> int:
        return int(sum(1 << int(i) for i in combo))

    def export_delta(self, levels: np.ndarray, draw: int) -> float:
        """Export (MWh) minus B2's over the kept rows; add B2's total for the absolute value."""
        rows = self.rows
        chosen = self.export_rows[np.arange(rows.size), levels]
        baseline = self.export_rows[np.arange(rows.size), self.b2_level[rows]]
        return float(chosen.sum() - baseline.sum())

    def agreement(self, levels: np.ndarray, draw: int) -> float:
        """The share of **all** E-steps where this subset decides as the oracle does."""
        disagree = int(np.count_nonzero(levels != self.oracle_level[draw][self.rows]))
        return 1.0 - disagree / self.n_steps

    def check_squeeze(self) -> bool:
        """The restriction's premise: the oracle is never more conservative than B2."""
        return bool(np.all(self.oracle_level <= self.b2_level[None, :]))


def _ob_best(engine: SubsetEngine, kmax: int, b2_export: np.ndarray):
    """OB (protocol s. 6; amendment A3): per draw **and per budget** k = 1 .. `kmax`, the
    non-empty subset of size <= k of the top-m candidates with the largest E-period export
    **under truth**. Not deployable; a regret reference.

    A3's fix is one pass over the same subsets for every budget: a subset of size s is a
    candidate for every k >= s, so the per-k maxima come out of the single enumeration that
    the old per-draw maximum already cost. The objective and the tie rule are unchanged --
    the first maximum in enumeration order, sizes ascending.

    Two consequences the caller relies on. The per-k values are non-decreasing in k, because
    the size-<= k subsets include the size-<= (k - 1) ones. And the per-k **sizes** are
    non-decreasing too: if the maximum does not rise at k the first subset attaining it still
    has size <= k - 1, so the k = (k - 1) pick is reused verbatim; if it does rise, no subset
    of size <= k - 1 attains it and the pick has size exactly k.

    Returns `(cols_per_k, export_per_k, n_subsets)`, the first two indexed `[k - 1]` and then
    by draw / over draws.
    """
    kmax = int(kmax)
    combos = [
        c for size in range(1, kmax + 1) for c in itertools.combinations(range(engine.m), size)
    ]
    masks = [engine.mask_of(c) for c in combos]
    n_draws = engine.rho_pool.shape[0]
    cols_per_k: list[list[tuple[int, ...]]] = [[] for _ in range(kmax)]
    gain_per_k = [np.zeros(n_draws) for _ in range(kmax)]
    for draw in range(n_draws):
        ft = engine.ft(draw)
        gain = [-np.inf] * kmax
        pick: list[tuple[int, ...]] = [()] * kmax
        for combo, mask in zip(combos, masks, strict=True):
            value = engine.export_delta(engine.levels(ft, mask), draw)
            for k in range(len(combo) - 1, kmax):  # a size-s subset competes at every k >= s
                if value > gain[k]:
                    gain[k], pick[k] = value, combo
        for k in range(kmax):
            gain_per_k[k][draw] = gain[k]
            cols_per_k[k].append(tuple(int(engine.pool[i]) for i in pick[k]))
    b2 = np.asarray(b2_export, dtype=float)
    return cols_per_k, [gain + b2 for gain in gain_per_k], len(combos)


def _h4_search(engine: SubsetEngine, kmax: int, extra):
    """H4 (protocol s. 7): the smallest subset of the top-m candidates -- or of the named B8P
    and B9 candidates in `extra` -- that decides as the oracle on >= `H4_STEP_SHARE` of
    E-steps in >= `H4_DRAW_SHARE` of draws. Sizes are searched in order and the search stops
    at the first size that succeeds, so the reported size is the smallest one found."""
    n_draws = engine.rho_pool.shape[0]
    fts = [engine.ft(draw) for draw in range(n_draws)]
    column_of = {int(col): i for i, col in enumerate(engine.pool.tolist())}

    def qualifies(mask: int) -> tuple[bool, float]:
        ok = 0
        for draw in range(n_draws):
            if engine.agreement(engine.levels(fts[draw], mask), draw) >= H4_STEP_SHARE:
                ok += 1
        return ok / n_draws >= H4_DRAW_SHARE, ok / n_draws

    tried = 0
    named: list[dict] = []
    for label, cols in extra:
        inside = [column_of[int(c)] for c in cols if int(c) in column_of]
        if len(inside) != len(set(int(c) for c in cols)):
            named.append(
                {
                    "source": label,
                    "columns": [int(c) for c in cols],
                    "size": len(set(int(c) for c in cols)),
                    "qualifies": None,
                    "draw_share": None,
                    "note": "not inside the top-m certificate pool, so it is not enumerable here",
                }
            )
            continue
        passed, share = qualifies(engine.mask_of(inside))
        tried += 1
        named.append(
            {
                "source": label,
                "columns": sorted(int(c) for c in cols),
                "size": len(inside),
                "qualifies": bool(passed),
                "draw_share": _f(share),
            }
        )
    empty_passed, empty_share = qualifies(0)
    tried += 1

    winner = None
    for size in range(1, int(kmax) + 1):
        for combo in itertools.combinations(range(engine.m), size):
            passed, share = qualifies(engine.mask_of(combo))
            tried += 1
            if passed:
                winner = {
                    "size": size,
                    "columns": sorted(int(engine.pool[i]) for i in combo),
                    "draw_share": _f(share),
                    "source": "exhaustive",
                }
                break
        if winner is not None:
            break
    for entry in named:
        if entry.get("qualifies") and (winner is None or entry["size"] < winner["size"]):
            winner = {
                "size": entry["size"],
                "columns": entry["columns"],
                "draw_share": entry["draw_share"],
                "source": entry["source"],
            }
    return {
        "criterion": {"step_share": H4_STEP_SHARE, "draw_share": H4_DRAW_SHARE},
        "kmax": int(kmax),
        "top_m_columns": engine.pool.tolist(),
        "subsets_scored": int(tried),
        "named_candidates": named,
        "empty_set_qualifies": bool(empty_passed),
        "empty_set_draw_share": _f(empty_share),
        "smallest": winner,
    }


# --- I.3 the evaluate command --------------------------------------------------------------


def _truth_draws(name, label, rc_model, n_lines, w, route_of_column, n):
    """Protocol s. 5: one stream per truth draw,
    `SeedSequence([20261026, network, model, "truth", d])`. The lines are drawn first and the
    transformer from the same per-draw stream, so a draw is reproducible on its own."""
    rho = np.ones((int(n), int(n_lines)))
    rho_t = np.ones(int(n))
    for draw in range(int(n)):
        rng = rc.rng_for(name, label, "truth", draw)
        rho[draw] = rc.sample_rho(
            rc_model, n_lines, rng, 1, route_of_line=route_of_column, w=w, kind="truth"
        )[0]
        rho_t[draw] = rc.sample_rho_trafo(rc_model, rng, 1, kind="truth")[0]
    return rho, rho_t


def _direct_policy(table, policy, rho, rho_t, lb, lb_t, rho_prior, rho_t_prior):
    """B0, B1, B2, B3, B4 and Control J's cap-0 reference: one decision, scored on truth."""
    n = int(rho.shape[0])
    if policy == "CAP0":
        level = np.full((n, table.n_steps), rc.LEVEL_ZERO, dtype=np.intp)
        out = rc.outcome(table, level, rho, rho_t)
        return Scored(
            np.atleast_1d(out.export),
            np.atleast_1d(out.unsafe_steps),
            np.atleast_1d(out.max_severity),
            level,
        )
    if policy == "B4":
        thr = 100.0 * rho
        thr_t = 100.0 * rho_t
    else:
        lb_vec = np.full(table.n_table, float(lb))
        prior = rho_prior if policy == "B3" else None
        base = rc.beliefs(policy, lb_vec, None, prior, n_lines=table.n_table)
        thr = np.broadcast_to(np.atleast_1d(base), (n, table.n_table))
        if policy == "B0":
            trafo = 1.0
        elif policy == "B1":
            trafo = (1.0 + float(lb_t)) / 2.0
        elif policy == "B2":
            trafo = float(lb_t)
        else:  # B3: the componentwise minimum of the sampled transformer scenarios
            trafo = float(np.asarray(rho_t_prior, dtype=float).min())
        thr_t = np.full(n, 100.0 * trafo)
    dec = rc.decide(table, thr, thr_t)
    level = np.atleast_2d(dec.level)
    out = rc.outcome(table, level, rho, rho_t)
    return Scored(
        np.atleast_1d(out.export),
        np.atleast_1d(out.unsafe_steps),
        np.atleast_1d(out.max_severity),
        level,
    )


def _policy_record(scored: Scored, n_steps: int, *, units=None, segments=None, recovery=None):
    """Protocol s. 7's per-policy, per-budget read-out."""
    unsafe = np.asarray(scored.unsafe, dtype=float)
    severity = np.asarray(scored.severity, dtype=float)
    finite = severity[np.isfinite(severity)]
    record = {
        "export_MWh": _dist(scored.export),
        "unsafe": {
            "mean_steps": _f(unsafe.mean()),
            "share_draws_ge1": _f(np.mean(unsafe >= 1.0)),
            "unsafe_step_share": _f(unsafe.mean() / float(n_steps)),
            "max_steps": int(unsafe.max()) if unsafe.size else 0,
        },
        "severity_pct": {
            "max": _f(finite.max()) if finite.size else None,
            "p95": _f(np.percentile(finite, 95)) if finite.size else None,
        },
    }
    if units is not None:
        record["realised_units"] = _dist(np.asarray(units, dtype=float))
        record["realised_segments"] = _dist(np.asarray(segments, dtype=float))
    if recovery is not None:
        record["recovery"] = recovery
    return record


def _recovery_record(export_policy, export_b2, export_oracle) -> dict:
    """Protocol s. 7 / s. 9: R per draw, its mean, Monte-Carlo SE and 5th/95th percentiles."""
    rec = rc.recovery(export_policy, export_b2, export_oracle)
    paired = rc.paired_summary(rec.r)
    return {
        "mean": _f(paired.mean),
        "se": _f(paired.se),
        "p5": _f(paired.p5),
        "p95": _f(paired.p95),
        "n": int(paired.n),
        "nan_excluded": int(rec.excluded),
    }


def _voi_record(table, red, rho_prior, lb, lb_t, cols, verify_trafo, rho_t_prior) -> dict:
    """Protocol s. 5's VoI for one verification unit on one period table: expected, best and
    worst export gain over the prior samples against B2."""
    n = int(rho_prior.shape[0])
    base = _score_set(table, red, rho_prior[:1], np.ones(1), lb, lb_t, (), False).export[0]
    with_set = _score_set(
        table, red, rho_prior, np.asarray(rho_t_prior, dtype=float), lb, lb_t, cols, verify_trafo
    ).export
    diff = np.asarray(with_set, dtype=float) - float(base)
    return {
        "expected_MWh": _f(diff.mean()),
        "best_MWh": _f(diff.max()),
        "worst_MWh": _f(diff.min()),
        "n_prior": n,
    }


def _control_h(table, red, rho, rho_t, lb, lb_t, top_cols, b2_level) -> dict:
    """Control H (protocol s. 8): on the E-steps where B2 curtails, the share where verifying
    the top-B7 unit alone -- at its true rating -- still leaves another cable or the
    transformer blocking the level above the new decision."""
    sel = np.array(sorted({int(c) for c in top_cols}), dtype=int)
    curtailed = np.flatnonzero(np.asarray(b2_level, dtype=int) > 0)
    if sel.size == 0 or curtailed.size == 0:
        return {
            "n_curtailed_E_steps": int(curtailed.size),
            "top_b7_columns": sel.tolist(),
            "share_other_asset_still_blocks": None,
            "note": "no B2-curtailed step or no top-B7 unit on this combination",
        }
    others = np.setdiff1d(np.arange(table.n_table), sel)
    shares = np.empty(int(rho.shape[0]))
    trafo_shares = np.empty(int(rho.shape[0]))
    for draw in range(int(rho.shape[0])):
        thr = np.full(table.n_table, 100.0 * float(lb))
        thr[sel] = 100.0 * rho[draw, sel]
        thr_t = 100.0 * float(lb_t)
        blocking = rc.blocking_counts(table, thr, thr_t)
        above = np.asarray(blocking.level, dtype=int) - 1
        live = curtailed[above[curtailed] >= 0]
        if live.size == 0:
            shares[draw] = np.nan
            trafo_shares[draw] = np.nan
            continue
        other_line = (
            blocking.blocks[live][:, others].any(axis=1)
            if others.size
            else np.zeros(live.size, dtype=bool)
        )
        trafo_blocks = table.trafo[live, above[live]] > thr_t
        shares[draw] = float(np.mean(other_line | trafo_blocks))
        trafo_shares[draw] = float(np.mean(trafo_blocks))
    return {
        "n_curtailed_E_steps": int(curtailed.size),
        "top_b7_columns": sel.tolist(),
        "share_other_asset_still_blocks": _dist(shares),
        "share_transformer_still_blocks": _dist(trafo_shares),
    }


def cmd_evaluate(args) -> dict:
    """The scored evaluation of one (network, model). Zero power flows, write-once."""
    rc.check_protocol()
    wall, cpu = time.perf_counter(), time.process_time()
    name, label = args.network, args.model
    if label not in EVAL_MODELS:
        raise ValueError(f"model {label!r} is not one of {tuple(EVAL_MODELS)}")
    if label not in eval_models(name):
        raise ValueError(f"{label} is not a protocol s. 5 combination for {name}")
    rc_model, w = EVAL_MODELS[label]
    loaded = load_tables(name)
    tables = loaded.tables
    table_p, table_e = tables["P"], tables["E"]
    certificate = concat_tables(tables)
    believed = rc.rho_bounds(rc_model, w, "believed")
    true_support = rc.rho_bounds(rc_model, w, "true")
    lb, ub = believed.line_lb, believed.line_ub
    lb_t, ub_t = believed.trafo_lb, believed.trafo_ub
    trafo_uncertain = rc_model == "UT"

    route_of_column = loaded.route_of_line[table_p.line_ids]
    pool_p = np.zeros(0, int) if trafo_uncertain else rc.candidate_pool(table_p, lb)
    pool_pe = np.zeros(0, int) if trafo_uncertain else rc.candidate_pool(certificate, lb)
    if trafo_uncertain:
        units: list[np.ndarray] = [np.zeros(0, int)]
        unit_kind = "transformer"
        unit_groups = None
        all_units = units
    elif rc_model == "U4":
        units = rc.groups_from_routes(route_of_column, pool_p)
        unit_kind = "route"
        unit_groups = units
        every = np.arange(table_p.n_table)
        all_units = rc.groups_from_routes(route_of_column, every) if every.size else []
    else:
        units = [np.array([j]) for j in pool_p]
        unit_kind = "segment"
        unit_groups = None
        all_units = [np.array([j]) for j in range(table_p.n_table)]
    n_units = len(units)
    pool_cols = tuple(sorted({int(c) for unit in units for c in unit.tolist()}))

    rho, rho_t = _truth_draws(name, label, rc_model, table_p.n_table, w, route_of_column, N_TRUTH)
    prior_rng = rc.rng_for(name, label, "prior")
    rho_prior = rc.sample_rho(
        rc_model,
        table_p.n_table,
        prior_rng,
        N_PRIOR,
        route_of_line=route_of_column,
        w=w,
        kind="prior",
    )
    rho_t_prior = rc.sample_rho_trafo(rc_model, prior_rng, N_PRIOR, kind="prior")

    budgets = [k for k in EVAL_BUDGETS if k <= max(n_units, 1)]
    k_max = max(budgets) if budgets else 1
    #: Protocol s. 10's reduction is exact only while it keeps one entry more than the largest
    #: set scored through it, counted in **table columns** (amendment A2). On P the widest set
    #: is the candidate pool's columns, which bound every greedy set and every VoI unit. On E
    #: the B5-all reference is wider: it draws its units from the routes of the **whole table**
    #: (protocol s. 6, "B5-all over all cables or routes"), so under U4 one of its units can
    #: reveal more columns than the pool holds -- up to the whole table, where k = `n_table` is
    #: exact by `decide_reduced`'s escape. Control G verifies one non-pool column at a time and
    #: OB subsets hold at most `OB_KMAX`, so both stay inside these widths.
    width_p = max(len(pool_cols), 1)
    width_e = max(width_p, rc.reveal_width(all_units, k_max), OB_KMAX)
    red_e = rc.reduction_for(table_e, width_e)
    red_p = rc.reduction_for(table_p, width_p)

    # --- the direct policies, and the two references every recovery needs
    direct: dict[str, Scored] = {}
    for policy in ("B0", "B1", "B2", "B3", "B4", "CAP0"):
        direct[policy] = _direct_policy(
            table_e, policy, rho, rho_t, lb, lb_t, rho_prior, rho_t_prior
        )
    direct["VERIFYALL"] = _score_set(
        table_e, red_e, rho, rho_t, lb, lb_t, pool_cols, trafo_uncertain, keep_level=True
    )
    export_b2 = direct["B2"].export
    export_oracle = direct["B4"].export
    b2_level_e = np.asarray(direct["B2"].level, dtype=int)[0]
    oracle_level_e = np.asarray(direct["B4"].level, dtype=int)

    policies: dict[str, dict] = {}
    for policy in DIRECT_POLICIES:
        recovery = None
        if policy in ("VERIFYALL", "B4"):
            recovery = _recovery_record(direct[policy].export, export_b2, export_oracle)
        policies[policy] = {
            "na": _policy_record(direct[policy], table_e.n_steps, recovery=recovery)
        }

    # --- Control F and Control C, read straight off the decisions
    control_f = {
        "verify_all_equals_B4_decisions": bool(
            np.array_equal(
                np.asarray(direct["VERIFYALL"].level, dtype=int),
                oracle_level_e,
            )
        ),
        "max_abs_export_difference_MWh": _f(
            np.max(np.abs(direct["VERIFYALL"].export - export_oracle))
        ),
    }
    control_c = {
        "model_is_U0": rc_model == "U0",
        "B0_equals_B4_decisions": bool(
            np.array_equal(np.asarray(direct["B0"].level, dtype=int), oracle_level_e)
        ),
        "B0_unsafe_steps_total": int(np.sum(direct["B0"].unsafe)),
        "max_abs_export_difference_MWh": _f(np.max(np.abs(direct["B0"].export - export_oracle))),
    }
    b3_vs_b2 = {
        "export_gap_MWh": _dist(direct["B3"].export - export_b2),
        "B3_unsafe": policies["B3"]["na"]["unsafe"],
        "B3_more_conservative_than_B2_steps": int(
            np.count_nonzero(np.asarray(direct["B3"].level, dtype=int) > b2_level_e[None, :])
        ),
        "fault": bool(np.any(np.asarray(direct["B3"].level, dtype=int) > b2_level_e[None, :])),
        "believed_lower_bound_pct": 100.0 * lb,
        "B3_threshold_pct": (
            rc.beliefs("B3", np.full(table_p.n_table, lb), None, rho_prior).tolist()
            if table_p.n_table
            else []
        ),
    }

    # --- the rankings and the greedies (planning on P, deployable inputs only)
    plans: dict[str, dict] = {}
    if trafo_uncertain:
        states_trafo = [(0, 0, ()), (1, 0, ())]
        for policy in BUDGETED_POLICIES:
            plans[policy] = {"states": states_trafo, "per_draw": False}
    elif n_units == 0:
        for policy in BUDGETED_POLICIES:
            plans[policy] = {"states": [(0, 0, ())], "per_draw": False}
    else:
        order_rng = rc.rng_for(name, label, "random_order")
        orders_pool = rc.random_orders(np.arange(n_units), order_rng, N_ORDERS)
        all_rng = rc.rng_for(name, label, "random_order", 1)
        orders_all = rc.random_orders(np.arange(len(all_units)), all_rng, N_ORDERS)
        rank_b6 = rc.rank_loading(table_p, pool_p)
        rank_b7 = rc.rank_binding(table_p, lb, pool_p)
        unit_rank_b6 = _lift_rank(rank_b6.order, units)
        unit_rank_b7 = _lift_rank(rank_b7.order, units)
        greedy_b8 = rc.greedy_voi(table_p, rho_prior, lb, k_max, unit_groups, red=red_p)
        greedy_b8p = rc.greedy_voi_pairs(table_p, rho_prior, lb, k_max, unit_groups, red=red_p)
        plans["B5"] = {
            "states": [_prefix_states(o, units, k_max) for o in orders_pool],
            "per_draw": False,
            "orders": True,
        }
        plans["B5all"] = {
            "states": [_prefix_states(o, all_units, k_max) for o in orders_all],
            "per_draw": False,
            "orders": True,
        }
        plans["B6"] = {"states": _prefix_states(unit_rank_b6, units, k_max), "per_draw": False}
        plans["B7"] = {"states": _prefix_states(unit_rank_b7, units, k_max), "per_draw": False}

        def expected_of(cols, _table=table_p, _red=red_p):
            return _score_set(
                _table, _red, rho_prior, rho_t_prior, lb, lb_t, cols, False
            ).export.mean()

        plans["B8"] = {
            "states": _greedy_states(greedy_b8, units, expected_of),
            "per_draw": False,
        }
        plans["B8P"] = {
            "states": _greedy_states(greedy_b8p, units, expected_of),
            "per_draw": False,
        }
        static_states, _ = route_rule_static(
            table_p,
            lb,
            loaded.parent_line,
            k_max,
            pool=pool_p,
            unit_groups=unit_groups,
            ub=ub,
        )
        plans["B9static"] = {"states": static_states, "per_draw": False}
        b9_states, b9_terminated = [], []
        for draw in range(N_TRUTH):
            states, terminated = route_rule_revealed(
                table_p,
                lb,
                loaded.parent_line,
                k_max,
                rho[draw],
                pool=pool_p,
                unit_groups=unit_groups,
            )
            b9_states.append(states)
            b9_terminated.append(terminated)
        plans["B9"] = {"states": b9_states, "per_draw": True}

    # --- OB and H4 through the subset engine
    top_m = np.zeros(0, int)
    if pool_pe.size:
        top_m = rc.rank_binding(certificate, lb, pool_pe).order[:TOP_M]
    engine = None
    if top_m.size and not trafo_uncertain:
        restrict = bool(np.all(rho[:, top_m] >= lb)) and bool(
            np.all(oracle_level_e <= b2_level_e[None, :])
        )
        engine = SubsetEngine(
            table_e, top_m, rho, lb, lb_t, b2_level_e, oracle_level_e, restrict=restrict
        )
    ob_record: dict = {"available": engine is not None}
    if engine is not None:
        ob_per_k, ob_export_per_k, n_ob = _ob_best(engine, OB_KMAX, export_b2)
        ob_cols = ob_per_k[-1]  # the size-<= OB_KMAX best set, which `modal_set` has always held
        ob_record.update(
            {
                "kmax": OB_KMAX,
                "searched_kmax": int(OB_KMAX),
                "subsets_scored_per_draw": int(n_ob),
                "rows_kept": int(engine.rows.size),
                "rows_total": int(engine.n_steps),
                "row_restriction_used": bool(engine.restricted),
                "squeeze_holds": bool(engine.check_squeeze()),
                "modal_set": sorted(max(set(ob_cols), key=ob_cols.count) if ob_cols else ()),
                "modal_set_per_k": {
                    str(k): sorted(max(set(cols), key=cols.count) if cols else ())
                    for k, cols in enumerate(ob_per_k, 1)
                },
            }
        )
        #: amendment A3: one state per budget, so s. 7's budget matching has a set at every
        #: k <= OB_KMAX. `_state_at` takes the last state with units <= k, which is the right
        #: one here without a per-k lookup: `_ob_best`'s sizes are non-decreasing in k, and a
        #: state that sits past k carries the same columns as the one at k (see `_ob_best`).
        #: Budgets above OB_KMAX land on the k = OB_KMAX state, as A3 requires.
        plans["OB"] = {
            "states": [
                [(0, 0, ()), *((len(c), len(c), tuple(sorted(c))) for c in per_draw)]
                for per_draw in zip(*ob_per_k, strict=True)
            ],
            "per_draw": True,
        }
    elif trafo_uncertain:
        plans["OB"] = {"states": [(0, 0, ()), (1, 0, ())], "per_draw": False}

    # --- score every budgeted policy at every budget
    for policy in BUDGETED_POLICIES:
        plan = plans.get(policy)
        if plan is None:
            policies[policy] = {"note": "no candidate on this combination"}
            continue
        entry: dict = {}
        for k in [*budgets, BUDGET_ALL]:
            if k == BUDGET_ALL:
                scored = direct["VERIFYALL"]
                used_units = np.full(N_TRUTH, float(n_units))
                used_segments = np.full(N_TRUTH, float(len(pool_cols)))
            elif plan.get("orders"):
                parts = []
                for states in plan["states"]:
                    chosen = _state_at(states, k)
                    parts.append(
                        _score_set(table_e, red_e, rho, rho_t, lb, lb_t, chosen[2], trafo_uncertain)
                    )
                scored = Scored(
                    np.mean([p.export for p in parts], axis=0),
                    np.mean([p.unsafe for p in parts], axis=0),
                    np.nanmax([p.severity for p in parts], axis=0),
                    None,
                )
                picked = [_state_at(s, k) for s in plan["states"]]
                used_units = np.array([float(p[0]) for p in picked])
                used_segments = np.array([float(p[1]) for p in picked])
            elif plan["per_draw"]:
                picked = [_state_at(states, k) for states in plan["states"]]
                scored = _score_grouped(
                    table_e,
                    red_e,
                    rho,
                    rho_t,
                    lb,
                    lb_t,
                    [p[2] for p in picked],
                    trafo_uncertain,
                )
                used_units = np.array([float(p[0]) for p in picked])
                used_segments = np.array([float(p[1]) for p in picked])
            else:
                chosen = _state_at(plan["states"], k)
                scored = _score_set(
                    table_e, red_e, rho, rho_t, lb, lb_t, chosen[2], trafo_uncertain
                )
                used_units = np.full(N_TRUTH, float(chosen[0]))
                used_segments = np.full(N_TRUTH, float(chosen[1]))
            entry[str(k)] = _policy_record(
                scored,
                table_e.n_steps,
                units=used_units,
                segments=used_segments,
                recovery=_recovery_record(scored.export, export_b2, export_oracle),
            )
            entry[str(k)]["export_per_draw_key"] = f"{policy}__{k}__export"
            _ARRAYS[f"{policy}__{k}__export"] = np.asarray(scored.export, dtype=float)
            _ARRAYS[f"{policy}__{k}__unsafe"] = np.asarray(scored.unsafe, dtype=float)
            _ARRAYS[f"{policy}__{k}__severity"] = np.asarray(scored.severity, dtype=float)
        policies[policy] = entry

    # --- VoI, Control G, Control H, the situation shares
    voi_units = []
    for index, unit in enumerate(units):
        cols = tuple(int(c) for c in unit.tolist())
        voi_units.append(
            {
                "unit": index,
                "kind": unit_kind,
                "columns": list(cols),
                "line_ids": [int(table_p.line_ids[c]) for c in cols],
                "VoI_P": _voi_record(
                    table_p, red_p, rho_prior, lb, lb_t, cols, trafo_uncertain, rho_t_prior
                ),
                "VoI_E": _voi_record(
                    table_e, red_e, rho_prior, lb, lb_t, cols, trafo_uncertain, rho_t_prior
                ),
            }
        )
    non_pool_cols = [c for c in range(table_p.n_table) if c not in set(pool_cols)]
    control_g = {"non_pool_table_columns": [], "non_table_lines": [], "zero_value_candidates": 0}
    for col in non_pool_cols[:CONTROL_G_LINES]:
        control_g["non_pool_table_columns"].append(
            {
                "column": int(col),
                "line_id": int(table_p.line_ids[col]),
                "VoI_P": _voi_record(
                    table_p, red_p, rho_prior, lb, lb_t, (col,), False, rho_t_prior
                ),
                "VoI_E": _voi_record(
                    table_e, red_e, rho_prior, lb, lb_t, (col,), False, rho_t_prior
                ),
            }
        )
    short = CONTROL_G_LINES - len(control_g["non_pool_table_columns"])
    if short > 0:
        n_lines = len(loaded.parent_line)
        outside = [i for i in range(n_lines) if i not in set(table_p.line_ids.tolist())][:short]
        control_g["non_table_lines"] = [
            {
                "line_id": int(line),
                "VoI_P": 0.0,
                "VoI_E": 0.0,
                "reason": (
                    "not a table line: its P-or-E maximum loading is at or below "
                    f"{rc.TABLE_LOADING_PCT} % of the record, so it cannot block at any "
                    "believed rating >= 0.7 and verifying it cannot change a decision"
                ),
            }
            for line in outside
        ]
    control_g["zero_value_candidates"] = int(
        sum(1 for entry in voi_units if (entry["VoI_P"]["expected_MWh"] or 0.0) <= 0.0)
    )

    top_b7_cols: tuple[int, ...] = ()
    if not trafo_uncertain and n_units:
        top_b7_cols = tuple(_state_at(plans["B7"]["states"], 1)[2])
    control_h = _control_h(table_e, red_e, rho, rho_t, lb, lb_t, top_b7_cols, b2_level_e)

    situation = {}
    for period, table in (("P", table_p), ("E", table_e)):
        labels = rc.situation(
            table,
            100.0 * lb,
            100.0 * ub,
            thr_trafo_min=100.0 * lb_t,
            thr_trafo_max=100.0 * ub_t,
        )
        situation[period] = {
            "n_steps": int(labels.size),
            "share_situation_1": _f(np.mean(labels == 1)),
            "share_situation_2": _f(np.mean(labels == 2)),
        }

    h4_record: dict = {"available": False}
    if engine is not None and label in ("U2", "U4"):
        extra = []
        if "B8P" in plans and not plans["B8P"].get("per_draw"):
            extra.append(("B8P", _state_at(plans["B8P"]["states"], k_max)[2]))
        if "B9static" in plans:
            extra.append(("B9-static", _state_at(plans["B9static"]["states"], k_max)[2]))
        if "B9" in plans and plans["B9"].get("per_draw"):
            modal = max(
                {tuple(_state_at(s, k_max)[2]) for s in plans["B9"]["states"]},
                key=lambda c: sum(
                    1 for s in plans["B9"]["states"] if tuple(_state_at(s, k_max)[2]) == c
                ),
            )
            extra.append(("B9", modal))
        h4_record = _h4_search(engine, H4_KMAX, extra)
        h4_record["available"] = True
        n_cables = int(len(loaded.parent_line))
        smallest = h4_record.get("smallest")
        h4_record["n_cables"] = n_cables
        h4_record["cable_fraction"] = (
            _f(smallest["size"] / n_cables) if smallest and n_cables else None
        )
        h4_record["supported"] = (
            bool(smallest and smallest["size"] <= 0.25 * n_cables) if smallest else False
        )
        h4_record["rejected"] = smallest is None
        h4_record["rows_kept"] = int(engine.rows.size)
        h4_record["row_restriction_used"] = bool(engine.restricted)

    _ARRAYS["rho_truth"] = rho
    _ARRAYS["rho_trafo_truth"] = rho_t
    _ARRAYS["rho_prior"] = rho_prior
    _ARRAYS["rho_trafo_prior"] = rho_t_prior
    for policy in DIRECT_POLICIES:
        _ARRAYS[f"{policy}__na__export"] = np.asarray(direct[policy].export, dtype=float)
        _ARRAYS[f"{policy}__na__unsafe"] = np.asarray(direct[policy].unsafe, dtype=float)
        _ARRAYS[f"{policy}__na__severity"] = np.asarray(direct[policy].severity, dtype=float)
    npz_path = rc.write_npz_once(RUNS / f"eval_{name}_{label}.npz", **_ARRAYS)
    arrays_written = sorted(_ARRAYS)
    _ARRAYS.clear()

    record = _stamp(
        "evaluate",
        network=name,
        model=label,
        rc_model=rc_model,
        new_ac_solves=0,
        tables_code_sha256=loaded.result["code_sha256"],
        w_believed=w,
        w_truth=(rc.W_U2P_TRUTH if rc_model == "U2P" else w),
        bounds={
            "believed": believed._asdict(),
            "true_support": true_support._asdict(),
        },
        sizes={
            "n_truth": N_TRUTH,
            "n_prior": N_PRIOR,
            "n_orders": N_ORDERS,
            "budgets": [*budgets, BUDGET_ALL],
            "steps_P": int(table_p.n_steps),
            "steps_E": int(table_e.n_steps),
            "n_table_lines": int(table_p.n_table),
            "n_network_lines": int(len(loaded.parent_line)),
            #: amendment A2: the widest set each reduction must stay exact for, in table
            #: columns, and the entries it keeps.
            "reduction_columns_P": int(width_p),
            "reduction_columns_E": int(width_e),
            "reduction_k_P": int(red_p.k),
            "reduction_k_E": int(red_e.k),
        },
        pool={
            "unit_kind": unit_kind,
            "n_units": int(n_units),
            "columns": list(pool_cols),
            "line_ids": [int(table_p.line_ids[c]) for c in pool_cols],
            "units": [[int(c) for c in unit.tolist()] for unit in units],
            "certificate_columns": pool_pe.tolist(),
            "top_m_columns": top_m.tolist(),
            "n_units_all_reference": int(len(all_units)) if not trafo_uncertain else 1,
        },
        policies=policies,
        b3_vs_b2=b3_vs_b2,
        control_c=control_c,
        control_f=control_f,
        control_g=control_g,
        control_h=control_h,
        control_j={
            "export_MWh": policies["CAP0"]["na"]["export_MWh"],
            "unsafe": policies["CAP0"]["na"]["unsafe"],
        },
        situation=situation,
        voi=voi_units,
        ob=ob_record,
        h4=h4_record,
        b9={
            "terminated_by_kmax_share": (
                _f(float(np.mean(b9_terminated))) if not trafo_uncertain and n_units else None
            ),
            "note": (
                "B9 runs behind the per-round reveal wrapper `route_rule_revealed`: each "
                "round sees only `reveal(the units verified in the earlier rounds, rho_true)` "
                "and asks for one unit more than it has realised (amendment A1), and "
                "'terminated' means a round verified nothing new, not that it overshot the "
                "budget. At the 'all' budget every verification policy verifies the whole "
                "candidate pool, so B9's entry there is the pool, not its own stopping point"
            ),
        },
        arrays_written=_rel(npz_path),
        array_keys=arrays_written,
        cpu_s=time.process_time() - cpu,
        wall_s=time.perf_counter() - wall,
    )
    path = rc.write_json_once(RESULTS / f"eval_{name}_{label}.json", record)
    best = max(
        (
            policies[p][str(k_max)]["recovery"]["mean"] or 0.0
            for p in ("B6", "B7", "B8", "B8P", "B9")
            if str(k_max) in policies.get(p, {})
        ),
        default=float("nan"),
    )
    print(f"evaluate {name} {label}: {_rel(path)}")
    print(
        f"  units {n_units} ({unit_kind}), B2 {export_b2.mean():.3f} MWh, "
        f"oracle {export_oracle.mean():.3f} MWh, best R at k={k_max} {best:.3f}, "
        f"cpu {record['cpu_s']:.1f} s"
    )
    return record


#: the per-draw arrays of the evaluation in progress; emptied when the npz is written.
_ARRAYS: dict[str, np.ndarray] = {}


def _lift_rank(column_order, units: list[np.ndarray]) -> np.ndarray:
    """Lift a segment ranking onto verification units: a unit takes the rank of its
    best-placed member column (protocol s. 6 -- under U4 the unit is the route, so B6's and
    B7's segment scores have to be read as route scores; the lift is order-preserving)."""
    order: list[int] = []
    for col in np.asarray(column_order, dtype=int).reshape(-1):
        for index, unit in enumerate(units):
            if int(col) in unit.tolist() and index not in order:
                order.append(index)
    for index in range(len(units)):
        if index not in order:
            order.append(index)
    return np.array(order, dtype=int)


# --- J. the verdicts (protocol s. 7, s. 8, s. 12) ------------------------------------------

#: protocol s. 7's pre-specified effect sizes.
H3A_UPPER, H3A_REJECT = 0.10, 0.25
H3B_SUPPORT, H3B_REJECT = 0.20, 0.05
H3C_SUPPORT, H3C_REJECT = 0.20, 0.05
CONTROL_I_CLOSE = 0.05
H5C_RECOVERY, H5C_BUDGET = 0.50, 4
H1_LOSS_SHARE, H1_SITUATION_1 = 0.005, 0.99
H1_RELEVANT_LOSS = 0.03
H4_CABLE_FRACTION = 0.25
#: the single-asset rankings of H3a and the structural pair of H3b.
SINGLE_RANKINGS = ("B6", "B7", "B8")
STRUCTURAL = ("B8P", "B9")


def _load_eval(network: str, label: str) -> dict | None:
    path = RESULTS / f"eval_{network}_{label}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _recovery_at(result: dict, policy: str, k) -> dict:
    """The recovery entry of one policy at one budget, or a zero entry (protocol s. 7 H3b: a
    policy with no realised count <= k scores R = 0 at that budget)."""
    entry = result["policies"].get(policy, {}).get(str(k))
    if entry is None or entry.get("recovery") is None:
        return {"mean": 0.0, "se": None, "realised_units": None, "missing": True}
    return {
        "mean": entry["recovery"]["mean"] if entry["recovery"]["mean"] is not None else 0.0,
        "se": entry["recovery"]["se"],
        "p5": entry["recovery"]["p5"],
        "p95": entry["recovery"]["p95"],
        "nan_excluded": entry["recovery"]["nan_excluded"],
        "realised_units": entry.get("realised_units", {}).get("mean"),
        "realised_segments": entry.get("realised_segments", {}).get("mean"),
        "missing": False,
    }


def _best_of(result: dict, policies, k) -> tuple[str | None, float, float | None]:
    best, value, se = None, -np.inf, None
    for policy in policies:
        entry = _recovery_at(result, policy, k)
        if entry["mean"] > value:
            best, value, se = policy, float(entry["mean"]), entry.get("se")
    return best, (value if np.isfinite(value) else 0.0), se


def cmd_verdicts(args) -> dict:  # noqa: ARG001
    """Protocol s. 7's verdicts, s. 8's controls and s. 12's stop conditions, applied to the
    written evaluations. Zero solves, no new scoring: every number is read from an artefact."""
    rc.check_protocol()
    wall, cpu = time.perf_counter(), time.process_time()
    results: dict[tuple[str, str], dict] = {}
    missing: list[str] = []
    for network in networks():
        for label in eval_models(network):
            result = _load_eval(network, label)
            if result is None:
                missing.append(f"{network}/{label}")
            else:
                results[(network, label)] = result

    def get(network, label):
        return results.get((network, label))

    # --- H1: descriptive (protocol s. 7)
    h1 = {"verdict": "DESCRIPTIVE (protocol s. 7: already visible in the audit)", "networks": {}}
    for network in networks():
        result = get(network, "U2")
        if result is None:
            h1["networks"][network] = {"status": "NOT CHECKED: no eval_U2 artefact"}
            continue
        b2 = result["policies"]["B2"]["na"]["export_MWh"]["mean"]
        oracle = result["policies"]["B4"]["na"]["export_MWh"]["mean"]
        loss = (oracle - b2) / oracle if oracle else 0.0
        h1["networks"][network] = {
            "class": ("transformer-limited" if network in TRANSFORMER_LIMITED else "cable-limited"),
            "B2_export_MWh": b2,
            "oracle_export_MWh": oracle,
            "B2_loss_share_of_oracle": _f(loss),
            "situation_1_share_E": result["situation"]["E"]["share_situation_1"],
            "irrelevant_by_H1_rule": bool(
                loss <= H1_LOSS_SHARE
                and (result["situation"]["E"]["share_situation_1"] or 0.0) >= H1_SITUATION_1
            ),
            "relevant_by_H1_rule": bool(loss >= H1_RELEVANT_LOSS),
        }

    # --- H3 under U2 (protocol s. 7, revision 2.2)
    h3: dict = {"model": "U2", "note": "revision 2.2: the H3 verdicts are evaluated under U2 only"}
    per_network: dict[str, dict] = {}
    for network in CABLE_LIMITED:
        result = get(network, "U2")
        if result is None:
            per_network[network] = {"status": "NOT CHECKED: no eval_U2 artefact"}
            continue
        entry: dict = {}
        entry["H3a"] = {policy: _recovery_at(result, policy, 1) for policy in SINGLE_RANKINGS}
        entry["H3a"]["max_R1"] = max(float(entry["H3a"][p]["mean"]) for p in SINGLE_RANKINGS)
        gaps = {}
        for k in (2, 3, 4):
            best_structural, value_s, se_s = _best_of(result, STRUCTURAL, k)
            best_single, value_1, se_1 = _best_of(result, SINGLE_RANKINGS, k)
            gaps[str(k)] = {
                "structural": best_structural,
                "structural_R": _f(value_s),
                "structural_se": se_s,
                "single": best_single,
                "single_R": _f(value_1),
                "single_se": se_1,
                "gap": _f(value_s - value_1),
            }
        smallest = min(gaps, key=lambda k: gaps[k]["gap"] if gaps[k]["gap"] is not None else 0.0)
        entry["H3b"] = {
            "per_budget": gaps,
            "budget_with_smallest_gap": int(smallest),
            "gap": gaps[smallest]["gap"],
            "fragile": bool(
                rc.fragile(
                    abs(gaps[smallest]["gap"] or 0.0),
                    float(gaps[smallest]["structural_se"] or 0.0)
                    + float(gaps[smallest]["single_se"] or 0.0),
                )
            ),
        }
        best_targeted, value_t, se_t = _best_of(result, (*SINGLE_RANKINGS, *STRUCTURAL), H5C_BUDGET)
        random_entry = _recovery_at(result, "B5", H5C_BUDGET)
        entry["H3c"] = {
            "best_targeted": best_targeted,
            "targeted_R": _f(value_t),
            "B5_R": random_entry["mean"],
            "gap": _f(value_t - float(random_entry["mean"])),
            "fragile": bool(
                rc.fragile(
                    abs(value_t - float(random_entry["mean"])),
                    float(se_t or 0.0) + float(random_entry.get("se") or 0.0),
                )
            ),
        }
        close = []
        for simple in ("B6", "B7"):
            per_budget = {}
            for k in [*EVAL_BUDGETS, BUDGET_ALL]:
                if str(k) not in result["policies"].get(simple, {}):
                    continue
                best_voi, value_v, _ = _best_of(result, ("B8", "B8P"), k)
                mine = float(_recovery_at(result, simple, k)["mean"])
                per_budget[str(k)] = _f(value_v - mine)
            worst = max((v for v in per_budget.values() if v is not None), default=None)
            close.append(
                {
                    "policy": simple,
                    "largest_gap_to_best_VoI": worst,
                    "within_0.05_at_every_budget": bool(
                        worst is not None and worst <= CONTROL_I_CLOSE
                    ),
                    "per_budget_gap": per_budget,
                }
            )
        b9_gaps = {}
        for k in [*EVAL_BUDGETS, BUDGET_ALL]:
            if str(k) not in result["policies"].get("B9", {}):
                continue
            b9_gaps[str(k)] = _f(
                float(_recovery_at(result, "B8P", k)["mean"])
                - float(_recovery_at(result, "B9", k)["mean"])
            )
        worst_b9 = max((v for v in b9_gaps.values() if v is not None), default=None)
        entry["control_I"] = {
            "simple_heuristics": close,
            "B9_vs_B8P": {
                "largest_gap": worst_b9,
                "structural_rule_suffices": bool(
                    worst_b9 is not None and worst_b9 <= CONTROL_I_CLOSE
                ),
                "per_budget_gap": b9_gaps,
            },
            "verdict": None,
        }
        simple_ok = [c["policy"] for c in close if c["within_0.05_at_every_budget"]]
        verdicts_i = []
        if simple_ok:
            verdicts_i.append(f"a simple heuristic suffices ({', '.join(simple_ok)})")
        if entry["control_I"]["B9_vs_B8P"]["structural_rule_suffices"]:
            verdicts_i.append("the structural rule suffices")
        entry["control_I"]["verdict"] = verdicts_i or ["neither"]
        entry["H5a"] = {
            "B2_unsafe_steps_total": result["policies"]["B2"]["na"]["unsafe"]["max_steps"],
            "holds": bool(result["policies"]["B2"]["na"]["unsafe"]["max_steps"] == 0),
        }
        b0 = result["policies"]["B0"]["na"]
        entry["H5b"] = {
            "B0_share_draws_with_ge1_unsafe": b0["unsafe"]["share_draws_ge1"],
            "B0_unsafe_step_share": b0["unsafe"]["unsafe_step_share"],
            "B0_severity_p95_pct": b0["severity_pct"]["p95"],
            "B0_severity_max_pct": b0["severity_pct"]["max"],
            "holds": bool((b0["unsafe"]["share_draws_ge1"] or 0.0) >= 0.50),
        }
        best_le4 = {"policy": None, "R": 0.0, "realised_units": None}
        for policy in (*SINGLE_RANKINGS, *STRUCTURAL):
            for k in EVAL_BUDGETS:
                if k > H5C_BUDGET:
                    continue
                candidate = _recovery_at(result, policy, k)
                units = candidate.get("realised_segments")
                if units is not None and units > H5C_BUDGET:
                    continue
                if float(candidate["mean"]) > best_le4["R"]:
                    best_le4 = {
                        "policy": policy,
                        "R": _f(candidate["mean"]),
                        "budget": k,
                        "realised_units": candidate.get("realised_units"),
                        "realised_segments": units,
                        "se": candidate.get("se"),
                    }
        entry["H5c"] = {
            **best_le4,
            "threshold": H5C_RECOVERY,
            "holds": bool(float(best_le4["R"] or 0.0) >= H5C_RECOVERY),
            "fragile": bool(
                rc.fragile(
                    abs(float(best_le4["R"] or 0.0) - H5C_RECOVERY),
                    float(best_le4.get("se") or 0.0),
                )
            ),
        }
        entry["control_H"] = result["control_h"]
        entry["B3_vs_B2"] = result["b3_vs_b2"]
        per_network[network] = entry
    h3["per_network"] = per_network

    scored = [n for n in CABLE_LIMITED if "H3a" in per_network.get(n, {})]
    if scored:
        max_r1 = max(per_network[n]["H3a"]["max_R1"] for n in scored)
        h3["H3a"] = {
            "max_R1_over_policies_and_networks": _f(max_r1),
            "verdict": (
                "SUPPORTED (every single-asset ranking at or below 0.10)"
                if max_r1 <= H3A_UPPER
                else "REJECTED"
                if max_r1 >= H3A_REJECT
                else "INCONCLUSIVE (0.10 < max R1 < 0.25)"
            ),
            "networks_scored": scored,
        }
        gaps = {n: per_network[n]["H3b"]["gap"] or 0.0 for n in scored}
        n_support = sum(1 for v in gaps.values() if v >= H3B_SUPPORT)
        h3["H3b"] = {
            "gap_per_network": {n: _f(v) for n, v in gaps.items()},
            "n_networks_at_or_above_0.20": n_support,
            "verdict": (
                "SUPPORTED"
                if n_support >= 2 and len(scored) == 3
                else "REJECTED"
                if len(scored) == 3 and all(v <= H3B_REJECT for v in gaps.values())
                else "INCONCLUSIVE"
            ),
            "fragile_networks": [n for n in scored if per_network[n]["H3b"]["fragile"]],
            "incomplete": len(scored) != 3,
        }
        gaps_c = {n: per_network[n]["H3c"]["gap"] or 0.0 for n in scored}
        h3["H3c"] = {
            "gap_per_network": {n: _f(v) for n, v in gaps_c.items()},
            "verdict": (
                "SUPPORTED"
                if len(scored) == 3 and all(v >= H3C_SUPPORT for v in gaps_c.values())
                else "REJECTED"
                if len(scored) == 3 and all(v <= H3C_REJECT for v in gaps_c.values())
                else "INCONCLUSIVE"
            ),
            "fragile_networks": [n for n in scored if per_network[n]["H3c"]["fragile"]],
            "incomplete": len(scored) != 3,
        }
        holds = {n: per_network[n]["H5c"]["holds"] for n in scored}
        h3["H5"] = {
            "a_check": {n: per_network[n]["H5a"] for n in scored},
            "b_check": {n: per_network[n]["H5b"] for n in scored},
            "c": {n: per_network[n]["H5c"] for n in scored},
            "verdict": (
                "SUPPORTED"
                if len(scored) == 3 and all(holds.values())
                else "REJECTED"
                if len(scored) == 3 and not any(holds.values())
                else "INCONCLUSIVE"
            ),
            "incomplete": len(scored) != 3,
        }
    else:
        for key in ("H3a", "H3b", "H3c", "H5"):
            h3[key] = {"verdict": "NOT CHECKED: no cable-limited U2 artefact"}

    # --- H4: U2 for the verdict, U4 descriptive (revision 2.2)
    h4: dict = {"verdict_model": "U2", "descriptive_model": "U4", "per_network": {}}
    for network in CABLE_LIMITED:
        entry = {}
        for label in ("U2", "U4"):
            result = get(network, label)
            entry[label] = (
                result["h4"] if result is not None else {"status": "NOT CHECKED: no artefact"}
            )
        u2 = entry["U2"]
        entry["verdict"] = (
            "NOT CHECKED"
            if not isinstance(u2, dict) or not u2.get("available")
            else "SUPPORTED"
            if u2.get("supported")
            else "REJECTED (no set of size <= 6 reaches the criterion)"
            if u2.get("rejected")
            else "INCONCLUSIVE"
        )
        h4["per_network"][network] = entry

    # --- the controls (protocol s. 8)
    controls: dict = {}
    rural1 = get("rural1", "U2")
    controls["A"] = (
        {
            "network": "rural1",
            "n_table_lines": rural1["sizes"]["n_table_lines"],
            "n_network_lines": rural1["sizes"]["n_network_lines"],
            "certified_irrelevant_lines": (
                rural1["sizes"]["n_network_lines"] - rural1["pool"]["n_units"]
            ),
            "n_candidate_units": rural1["pool"]["n_units"],
            "max_cable_VoI_P_MWh": max(
                (u["VoI_P"]["expected_MWh"] or 0.0 for u in rural1["voi"]), default=0.0
            ),
            "pass": bool(rural1["pool"]["n_units"] == 0),
        }
        if rural1
        else {"status": "NOT CHECKED: no eval_rural1_U2 artefact"}
    )
    controls["B"] = {"cable_VoI_U2": {}, "UT_transformer_recovery": {}}
    for network in ("rural2", "rural3"):
        result = get(network, "U2")
        controls["B"]["cable_VoI_U2"][network] = (
            {
                "max_expected_VoI_P_MWh": max(
                    (u["VoI_P"]["expected_MWh"] or 0.0 for u in result["voi"]), default=0.0
                ),
                "max_expected_VoI_E_MWh": max(
                    (u["VoI_E"]["expected_MWh"] or 0.0 for u in result["voi"]), default=0.0
                ),
                "B2_loss_MWh": _f(
                    (result["policies"]["B4"]["na"]["export_MWh"]["mean"] or 0.0)
                    - (result["policies"]["B2"]["na"]["export_MWh"]["mean"] or 0.0)
                ),
            }
            if result
            else {"status": "NOT CHECKED"}
        )
    for network in TRANSFORMER_LIMITED:
        result = get(network, "UT")
        controls["B"]["UT_transformer_recovery"][network] = (
            {
                "recovery_at_k1": _recovery_at(result, "B7", 1),
                "verify_all_recovery": result["policies"]["VERIFYALL"]["na"]["recovery"],
                "B2_export_MWh": result["policies"]["B2"]["na"]["export_MWh"]["mean"],
                "oracle_export_MWh": result["policies"]["B4"]["na"]["export_MWh"]["mean"],
            }
            if result
            else {"status": "NOT CHECKED"}
        )
    controls["C"] = {
        network: (get(network, "U0")["control_c"] if get(network, "U0") else "NOT CHECKED")
        for network in networks()
    }
    control_d_path = RESULTS / "control_d.json"
    controls["D"] = (
        {
            "source": _rel(control_d_path),
            "pass": json.loads(control_d_path.read_text()).get("pass"),
            "summary": json.loads(control_d_path.read_text()).get("comparison"),
        }
        if control_d_path.exists()
        else {"status": "NOT CHECKED: results/control_d.json is missing"}
    )
    controls["E"] = {}
    for network in networks():
        path = RESULTS / f"control_e_{network}.json"
        if not path.exists():
            controls["E"][network] = {"status": "NOT CHECKED: artefact missing"}
            continue
        stored = json.loads(path.read_text())
        controls["E"][network] = {
            "source": _rel(path),
            "provenance_pass": stored.get("alignment", {}).get("pass", stored.get("pass")),
            "comparable": stored.get("comparable", stored.get("alignment", {}).get("pass")),
        }
    controls["F"] = {
        f"{network}/{label}": result["control_f"] for (network, label), result in results.items()
    }
    controls["G"] = {
        f"{network}/{label}": result["control_g"] for (network, label), result in results.items()
    }
    controls["H"] = {
        network: (get(network, "U2")["control_h"] if get(network, "U2") else "NOT CHECKED")
        for network in CABLE_LIMITED
    }
    controls["I"] = {
        network: per_network.get(network, {}).get("control_I", "NOT CHECKED")
        for network in CABLE_LIMITED
    }
    controls["J"] = {
        f"{network}/{label}": result["control_j"] for (network, label), result in results.items()
    }
    controls["B3_vs_B2"] = {
        f"{network}/{label}": result["b3_vs_b2"] for (network, label), result in results.items()
    }

    control_pass = {
        "A": controls["A"].get("pass"),
        "C": all(
            entry["B0_equals_B4_decisions"] and entry["B0_unsafe_steps_total"] == 0
            for entry in controls["C"].values()
            if isinstance(entry, dict)
        )
        or None,
        "D": controls["D"].get("pass"),
        "F": all(entry["verify_all_equals_B4_decisions"] for entry in controls["F"].values())
        or None,
        "J": all(
            (entry["export_MWh"]["mean"] or 0.0) == 0.0 and entry["unsafe"]["max_steps"] == 0
            for entry in controls["J"].values()
        )
        or None,
        "B3_vs_B2": not any(entry["fault"] for entry in controls["B3_vs_B2"].values()),
    }

    # --- U2' read-out (protocol s. 5, s. 7)
    u2p: dict = {}
    for network in CABLE_LIMITED:
        result = get(network, "U2P")
        if result is None:
            u2p[network] = {"status": "NOT CHECKED: no eval_U2P artefact"}
            continue
        u2p[network] = {
            "B2_unsafe": result["policies"]["B2"]["na"]["unsafe"],
            "B2_severity_pct": result["policies"]["B2"]["na"]["severity_pct"],
            "B3_unsafe": result["policies"]["B3"]["na"]["unsafe"],
            "recovery_at_4": {
                policy: _recovery_at(result, policy, 4)
                for policy in ("B7", "B8", "B8P", "B9")
                if str(4) in result["policies"].get(policy, {})
            },
        }

    # --- s. 12 stop conditions
    stop: dict = {
        "control_C_D_F_or_B3_fails": bool(
            control_pass["C"] is False
            or control_pass["D"] is False
            or control_pass["F"] is False
            or control_pass["B3_vs_B2"] is False
        ),
        "control_E_not_comparable": [
            network
            for network, entry in controls["E"].items()
            if isinstance(entry, dict) and entry.get("comparable") is False
        ],
        "top_m_restriction_binds": {
            network: bool(
                (get(network, "U2") or {}).get("pool", {}).get("certificate_columns")
                and len((get(network, "U2") or {})["pool"]["certificate_columns"]) > TOP_M
            )
            for network in CABLE_LIMITED
        },
        "cable_limited_B2_loss_below_1pct": {
            network: (
                _f(h1["networks"][network]["B2_loss_share_of_oracle"])
                if isinstance(h1["networks"].get(network), dict)
                and h1["networks"][network].get("B2_loss_share_of_oracle") is not None
                else None
            )
            for network in CABLE_LIMITED
        },
        "deployable_policy_read_rho_true": False,
        "note": (
            "the information boundary is enforced in `ratings_core._forbid_truth` and, for B9, "
            "by `route_rule_revealed`'s per-round `reveal`; the module tests assert both"
        ),
    }

    record = _stamp(
        "verdicts",
        new_ac_solves=0,
        combinations_scored=sorted(f"{n}/{m}" for (n, m) in results),
        combinations_missing=sorted(missing),
        effect_sizes={
            "H3a_upper": H3A_UPPER,
            "H3a_reject": H3A_REJECT,
            "H3b_support": H3B_SUPPORT,
            "H3b_reject": H3B_REJECT,
            "H3c_support": H3C_SUPPORT,
            "H3c_reject": H3C_REJECT,
            "control_I_close": CONTROL_I_CLOSE,
            "H5c_recovery": H5C_RECOVERY,
            "H5c_budget_segments": H5C_BUDGET,
            "H4_cable_fraction": H4_CABLE_FRACTION,
        },
        H1=h1,
        H2={
            "verdict": "ANALYTIC (protocol s. 7: not an empirical hypothesis)",
            "checked_by": ["Control D (identical states)", "Control E (impedance plus rating)"],
        },
        H3=h3,
        H4=h4,
        H5=h3.get("H5"),
        controls=controls,
        control_pass=control_pass,
        u2_prime=u2p,
        stop_conditions=stop,
        cpu_s=time.process_time() - cpu,
        wall_s=time.perf_counter() - wall,
    )
    path = rc.write_json_once(RESULTS / "verdicts.json", record)
    print(f"verdicts: {_rel(path)}")
    print(
        f"  scored {len(results)} combinations, missing {len(missing)}; "
        f"H3a {h3.get('H3a', {}).get('verdict')}; H3b {h3.get('H3b', {}).get('verdict')}; "
        f"H3c {h3.get('H3c', {}).get('verdict')}; H5 {h3.get('H5', {}).get('verdict')}"
    )
    return record


# --- I. the CLI ----------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_stage_a",
        description=(
            "Mission 12 Stage A: decision tables, Controls D and E, and the pilot timing. "
            "Foreground only; new AC solves in `control-d` alone."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    tables = sub.add_parser("tables", help="build one network's P and E decision tables")
    tables.add_argument("--network", required=True, choices=sorted(networks()))
    tables.set_defaults(func=cmd_tables)
    control_d = sub.add_parser("control-d", help="Control D: a rating-only change (2 AC solves)")
    control_d.set_defaults(func=cmd_control_d)
    control_e = sub.add_parser("control-e", help="Control E: impedance plus rating (zero solves)")
    control_e.add_argument("--network", required=True, choices=sorted(networks()))
    control_e.set_defaults(func=cmd_control_e)
    pilot = sub.add_parser("pilot", help="pilot timing and the full-run projection")
    pilot.set_defaults(func=cmd_pilot)
    evaluate = sub.add_parser("evaluate", help="the scored evaluation of one (network, model)")
    evaluate.add_argument("--network", required=True, choices=sorted(networks()))
    evaluate.add_argument("--model", required=True, choices=sorted(EVAL_MODELS))
    evaluate.set_defaults(func=cmd_evaluate)
    verdicts = sub.add_parser("verdicts", help="protocol s. 7 verdicts from the evaluations")
    verdicts.set_defaults(func=cmd_verdicts)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
