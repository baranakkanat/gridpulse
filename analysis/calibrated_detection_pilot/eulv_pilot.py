"""Calibrated-detection pilot, steps 2-4: the IEEE European LV feeder.

EXPLORATORY and unregistered, steps 2, 3 and 4 of the four-step pilot of
`docs/proposal_calibrated_detection.md` s. 10, approved by the owner on 2026-10-24.
Nothing is downloaded, no dependency is added and no ENWL file is read. The network is
pandapower 3.5.6's shipped `pandapower.networks.ieee_european_lv_asymmetric()` in its
default `on_peak_566` scenario. Nothing outside `analysis/calibrated_detection_pilot/`
is written and no Phase 9 or follow-up file is modified: `phase9_sweep` and
`q1_voltage_residual` are *imported* and reused unchanged.

Three questions, in cost order:

* **Step 2 (zero flows)** -- what is this feeder, do Phase 9's structural invariants hold
  on it, and what are its *cable sections* (maximal chains of segments between nodes of
  degree != 2 or carrying a load)? The 905 segments have a median length of 0.49 m, so the
  segment is not the unit an asset-record error lives on; the section is.
* **Step 3 (384 flows)** -- what does one solve actually cost at 906 buses, three-phase
  and balanced, and how much memory does it take? This replaces the proposal's 20-60 ms
  HYPOTHESIS with a measurement.
* **Step 4 (3,840 flows)** -- does the Phase 9 pipeline run end to end on a non-SimBench
  topology, and what do the first non-SimBench contrasts look like?

Run from the repository root, one command per invocation:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python \
        analysis/calibrated_detection_pilot/eulv_pilot.py topology
    ... the same prefix with: timing
    ... the same prefix with: smoke --leg nominal
    ... the same prefix with: smoke --leg a
    ... the same prefix with: smoke --leg b
    ... the same prefix with: smoke --leg c
    ... the same prefix with: report

`topology` writes nothing (it is free to recompute). `timing`, `smoke` and `report` write
their files once, through a temporary file in the same directory and one `os.replace`, and
refuse to overwrite an existing file.

**This is a pipeline and cost pilot, not evidence.** The load and PV profiles are SimBench
`1-LV-semiurb4--2-sw` profiles, so only the *topology* is independent of the material
Phase 9 and its follow-up were built on. No coverage, size or power claim is made here, and
the single C1-style ratio reported is labelled ILLUSTRATIVE.

Judgement calls (numbered, and repeated in the output JSON)
-----------------------------------------------------------
J1  **Section downstream set.** A section's downstream buses are the buses disconnected
    from the LV busbar when *all* of the section's segments are removed: the chain's
    internal nodes plus the whole subtree below its far endpoint. Internal nodes are
    degree-2 and load-free by the definition of a section, so they carry no customer and
    this choice changes no customer count; it is Phase 9's `downstream(l)` read on a
    section instead of a segment.
J2  **Section depth.** A section's busbar depth is the number of segments on the unique
    busbar-to-near-endpoint path, i.e. the count of segments strictly upstream of the
    section. A section incident to the busbar therefore has depth 0.
J3  **The selection rules run over candidate sections only** (sections not incident to the
    LV busbar), matching Phase 9's exclusion of feeder heads from `candidates`. Rule (a) is
    the `local_line` analogue and `stress.local_line` is likewise chosen among candidates.
J4  **Downstream installed PV** is 4 kWp x (downstream customers at an even position in
    bus-index order) and **downstream peak load** is 4 kW x (downstream customers), both
    exactly as the stated scenario fixes them. No flow is needed to evaluate the three
    selection rules, and they are computed and recorded before any flow runs.
J5  **`scaling` is forced to 1.0** on the asymmetric load and sgen tables, so that the
    stated 4 kW and 4 kWp are the powers actually injected. The shipped network's
    `on_peak_566` snapshot values are overwritten by the scenario at every step anyway, so
    nothing of the snapshot survives except the element-to-bus-and-phase map.
J6  **Per-step voltages are stored in float64, not Phase 9's float32.** Phase 9's float32
    rule applies to per-day *means* of an already-formed Delta; here the two legs are
    differenced at report time, and a float32 round trip would inject about 1.7e-7 p.u. of
    quantisation into a Delta whose detection scale is 3.5e-4 p.u. Four legs at float64
    cost 1.8 MB, well inside the 5 MB budget.
J7  **The timing probe is stored under `results/parts/`,** not under `eulv/`: it is not a
    leg and has no per-leg npz. It follows the same write-once discipline.
J8  **The per-solve constant used for the cost extrapolation is the smoke run's**
    (3,840 solves over four legs), not the 192-solve probe's, because it is measured over
    20x more solves and includes the error-leg networks. The probe's constant is reported
    beside it and the two are compared.
J9  **A failed or non-converged flow is NaN** for every column of that step, and
    `phase9_sweep.reduce_day` then drops the step from both the daylight and the night mean
    of that day. A day with no valid daylight step or no valid night step is unusable and
    drops from k, k_ref, m and night, which is Phase 9 reading R-b.
J10 **The C1-style ratio is ILLUSTRATIVE and is not a detection claim.** It is
    |k_ref| / (z_K sigma sqrt(sum_d(1/n_d + 1/m_d)) / D) at sigma = 0.01, K = 1, D = 10 on
    a noise-free Delta over 10 days, with no meter-placement rule, no multiplicity over
    cables, and a denominator that omits the busbar noise term the proposal's s. 3.2
    derives. It says only whether the signal is of the order of the noise floor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PHASE9 = REPO / "analysis" / "phase9"
if str(PHASE9) not in sys.path:  # imported, never copied or edited
    sys.path.insert(0, str(PHASE9))

import numpy as np  # noqa: E402
import phase9_sweep as ps  # noqa: E402
import q1_voltage_residual as q1  # noqa: E402

EULV = HERE / "eulv"
RESULTS = HERE / "results"
OUTPUT = RESULTS / "eulv_pilot.json"
TIMING_FILE = RESULTS / "parts" / "eulv_timing.json"

STATUS = ("EXPLORATORY pilot steps 2-4; ~4,000 power flows; pandapower "
          "ieee_european_lv_asymmetric with a synthetic stated scenario; unregistered")  # fmt: skip

NETWORK_SCENARIO = "on_peak_566"
BUSBAR = 1  # the LV busbar, s. "Board-verified facts"
PHASES = ("a", "b", "c")

PROFILE_NETWORK = "1-LV-semiurb4--2-sw"
START_DATE = "2016-06-01"
N_DAYS = 10
STEPS = 96
CUSTOMER_PEAK_KW = 4.0
PV_KWP = 4.0
COS_PHI = 0.95  # inductive
PV_EVERY = 2  # every second customer in bus-index order, starting at position 0

R_FACTOR = 1.5  # E-R(1.5): r_ohm_per_km and r0_ohm_per_km
RATING_FACTOR = 0.8  # max_i_ka
ERROR = "E-R"

TIMING_DAYS = 2  # step 3 (a) and (b): 2 days x 96 steps each
SIGMA_ILLUSTRATIVE = 0.01
K_ILLUSTRATIVE = 1
MAIN_STUDY = {"runs": 504, "days": 60, "steps": 96}  # proposal s. 6
K1_CPU_HOURS = 60.0  # kill criterion K1

LINE_FIELDS = ("from_bus", "to_bus", "length_km", "r_ohm_per_km", "x_ohm_per_km",
               "c_nf_per_km", "r0_ohm_per_km", "x0_ohm_per_km", "c0_nf_per_km",
               "max_i_ka", "parallel", "df", "in_service")  # fmt: skip
ERROR_FIELDS = ("r_ohm_per_km", "r0_ohm_per_km", "max_i_ka")

SCENARIO = {
    "note": "Fixed before any flow and recorded verbatim. SYNTHETIC.",
    "days": {
        "source": "day index from gridpulse.grid_study (FIRST_DAY = 2016-01-01 UTC)",
        "half": "SimBench development half, grid_study.period_days('development')",
        "start_date": START_DATE,
        "n_days": N_DAYS,
        "consecutive": True,
        "steps_per_day": STEPS,
    },
    "loads": {
        "assignment": "customer i, in bus-index order, takes the normalised household "
                      "profile of semiurb4 load (i mod n_loads)",
        "profile_source": f"gridpulse.grid.absolute_profiles on the nominal {PROFILE_NETWORK} "
                          "variant (dual_study.variant_network, NOMINAL, pv_scale)",
        "normalisation": "divided by that profile's annual maximum over the complete UTC "
                         "days of 2016",
        "peak_kw": CUSTOMER_PEAK_KW,
        "phase": "the customer's own IEEE phase; the other two phases stay at zero",
        "power_factor": {"cos_phi": COS_PHI, "sign": "inductive (q > 0, load convention)"},
    },
    "pv": {
        "placement": "every second customer (even positions in bus-index order) gets a "
                     "single-phase asymmetric_sgen on its own phase",
        "rating_kwp": PV_KWP,
        "profile": "normalised PV availability of semiurb4's first sgen "
                   "(sgen_p_mw[:, 0] / sn_mva[0]), i.e. availability / rating",
    },
    "daylight": {
        "rule": "a step is daylight iff the normalised PV availability is > 0; night is "
                "the rest",
        "retention": "retain a day only if it has at least 1 daylight and 1 night step",
    },
    "independence": (
        "The load and PV profiles come from SimBench, the same material Phase 9 and its "
        "follow-up were built on, so only the TOPOLOGY of this feeder is independent. "
        "This is a pipeline and cost pilot, not evidence: no size, coverage or power "
        "claim is made from it."
    ),
}

JUDGEMENT_CALLS = {
    "J1": "Section downstream set: the buses disconnected from the LV busbar when all of "
          "the section's segments are removed, i.e. the chain's internal nodes plus the "
          "whole subtree below its far endpoint. Internal nodes are degree-2 and load-free "
          "by definition, so no customer count changes.",
    "J2": "Section busbar depth: the number of segments on the busbar-to-near-endpoint "
          "path. A section incident to the busbar has depth 0.",
    "J3": "The three selection rules run over candidate sections only (not incident to the "
          "LV busbar), matching Phase 9's exclusion of feeder heads from `candidates`.",
    "J4": "Downstream installed PV is 4 kWp x (downstream customers at an even position in "
          "bus-index order); downstream peak load is 4 kW x (downstream customers). Both "
          "are fixed by the stated scenario, so the three rules are evaluated and recorded "
          "before any flow.",
    "J5": "`scaling` is forced to 1.0 on the asymmetric load and sgen tables so that the "
          "stated 4 kW and 4 kWp are the powers actually injected. Nothing of the "
          "on_peak_566 snapshot survives except the element-to-bus-and-phase map.",
    "J6": "Per-step voltages are stored in float64, not Phase 9's float32: the two legs are "
          "differenced at report time, and a float32 round trip would inject about 1.7e-7 "
          "p.u. into a Delta whose detection scale is 3.5e-4 p.u. Four legs cost 1.8 MB.",
    "J7": "The timing probe is stored under `results/parts/`, not under `eulv/`: it is not "
          "a leg and has no per-leg npz. It follows the same write-once discipline.",
    "J8": "The cost extrapolation uses the smoke run's per-solve constant (3,840 solves, "
          "four legs), not the 192-solve probe's. Both are reported and compared.",
    "J9": "A failed or non-converged flow is NaN in every column of that step, and "
          "`phase9_sweep.reduce_day` then drops the step from both means of that day. A day "
          "with no valid daylight or no valid night step is unusable (Phase 9 reading R-b).",
    "J10": "The C1-style ratio is ILLUSTRATIVE and is not a detection claim: 10 days, a "
           "noise-free Delta, no placement rule, no multiplicity over cables, and a "
           "denominator that omits the busbar noise term of proposal s. 3.2.",
}


# --- the network, its customers and the line graph -----------------------------------------


def eulv_network():
    """The shipped IEEE European LV asymmetric network, `on_peak_566`."""
    from pandapower.networks import ieee_european_lv_asymmetric

    return ieee_european_lv_asymmetric(NETWORK_SCENARIO)


def line_table_sha256(net) -> str:
    """sha256 of the nominal line table over `LINE_FIELDS`, in index order."""
    table = net.line.loc[sorted(net.line.index), list(LINE_FIELDS)]
    return hashlib.sha256(table.to_csv(index=True, lineterminator="\n").encode()).hexdigest()


def physics_key(net=None) -> str:
    """The artefact key: sha256 of the nominal line table plus the scenario spec."""
    net = eulv_network() if net is None else net
    payload = {
        "line_table_sha256": line_table_sha256(net),
        "line_fields": list(LINE_FIELDS),
        "scenario": SCENARIO,
        "network": {"loader": "pandapower.networks.ieee_european_lv_asymmetric",
                    "scenario": NETWORK_SCENARIO,
                    "pandapower": _package_version("pandapower")},  # fmt: skip
        "error": {"type": ERROR, "r_factor": R_FACTOR, "rating_factor": RATING_FACTOR,
                  "columns": list(ERROR_FIELDS)},  # fmt: skip
    }
    return hashlib.sha256(q1.json_text(payload).encode()).hexdigest()


def _package_version(name: str) -> str:
    from importlib.metadata import version

    return version(name)


def customers(net) -> list[dict]:
    """The 55 single-phase `asymmetric_load`s, in bus-index order, with their IEEE phase.

    A customer's phase is the one phase whose snapshot `p_a/b/c_mw` is non-zero; a load
    with none or more than one non-zero phase is not single-phase and is a hard error.
    """
    table = net.asymmetric_load
    rows = []
    for element in table.index:
        p = np.array([float(table.at[element, f"p_{ph}_mw"]) for ph in PHASES])
        live = np.flatnonzero(p != 0.0)
        if live.size != 1:
            raise RuntimeError(f"asymmetric_load {element} is not single-phase: p = {p}")
        rows.append({"element": int(element), "bus": int(table.at[element, "bus"]),
                     "phase": PHASES[int(live[0])], "phase_index": int(live[0]),
                     "snapshot_p_mw": float(p[live[0]])})  # fmt: skip
    rows.sort(key=lambda r: (r["bus"], r["element"]))
    for position, row in enumerate(rows):
        row["position"] = position
        row["has_pv"] = position % PV_EVERY == 0
    return rows


def line_graph(net) -> dict[int, list[tuple[int, int]]]:
    """Adjacency over the LV buses: bus -> [(neighbour, line index), ...]."""
    adjacency: dict[int, list[tuple[int, int]]] = {}
    for line in net.line.index:
        a, b = int(net.line.at[line, "from_bus"]), int(net.line.at[line, "to_bus"])
        adjacency.setdefault(a, []).append((b, int(line)))
        adjacency.setdefault(b, []).append((a, int(line)))
    return adjacency


def rooted_tree(net, root: int = BUSBAR) -> dict:
    """Parent bus, parent line, depth in segments, and the subtree bus set, rooted at `root`.

    Raises if the line graph is not a connected tree over the buses it touches. Connected
    plus |E| = |V| - 1 is acyclic, so the two checks below are a tree test.
    """
    adjacency = line_graph(net)
    if root not in adjacency:
        raise RuntimeError(f"bus {root} carries no line")
    parent: dict[int, int | None] = {root: None}
    parent_line: dict[int, int | None] = {root: None}
    depth = {root: 0}
    order = [root]
    cursor = 0
    while cursor < len(order):
        bus = order[cursor]
        cursor += 1
        for neighbour, line in adjacency[bus]:
            if neighbour in parent:
                continue
            parent[neighbour] = bus
            parent_line[neighbour] = line
            depth[neighbour] = depth[bus] + 1
            order.append(neighbour)
    if len(order) != len(adjacency):
        raise RuntimeError(f"the line graph is not connected: {len(order)} of "
                           f"{len(adjacency)} buses reachable from {root}")  # fmt: skip
    if len(net.line.index) != len(adjacency) - 1:
        raise RuntimeError(f"{len(net.line.index)} lines over {len(adjacency)} buses is not "
                           "acyclic")  # fmt: skip
    children: dict[int, list[int]] = {bus: [] for bus in order}
    for bus in order[1:]:
        children[parent[bus]].append(bus)
    subtree: dict[int, set[int]] = {}
    for bus in reversed(order):
        found = {bus}
        for child in children[bus]:
            found |= subtree[child]
        subtree[bus] = found
    return {"adjacency": adjacency, "parent": parent, "parent_line": parent_line,
            "depth": depth, "order": order, "children": children, "subtree": subtree}  # fmt: skip


def sections(net, load_buses, root: int = BUSBAR) -> list[dict]:
    """The cable sections: maximal chains of segments between boundary nodes.

    A boundary node has degree != 2 in the segment graph, or carries a load; the busbar
    counts as one. Per section: its segments, length, R and R0 (series sums), its busbar
    depth in segments (J2), its downstream bus set (J1) and its downstream customers.
    """
    tree = rooted_tree(net, root)
    adjacency, children, subtree, depth = (tree["adjacency"], tree["children"],
                                           tree["subtree"], tree["depth"])  # fmt: skip
    load_buses = {int(b) for b in load_buses}
    boundary = {bus for bus in adjacency
                if len(adjacency[bus]) != 2 or bus in load_buses} | {root}  # fmt: skip
    out = []
    for near in sorted(boundary):
        for child in children[near]:
            segments = [int(tree["parent_line"][child])]
            internal: list[int] = []
            cursor = child
            while cursor not in boundary:
                internal.append(int(cursor))
                if len(children[cursor]) != 1:
                    raise RuntimeError(f"bus {cursor} is not a boundary node but has "
                                       f"{len(children[cursor])} children")  # fmt: skip
                nxt = children[cursor][0]
                segments.append(int(tree["parent_line"][nxt]))
                cursor = nxt
            far = int(cursor)
            table = net.line.loc[segments]
            downstream = set(internal) | set(subtree[far])
            out.append({
                "section": len(out),
                "near_bus": int(near),
                "far_bus": far,
                "segments": [int(s) for s in segments],
                "n_segments": len(segments),
                "internal_buses": internal,
                "first_segment": int(segments[0]),
                "depth_segments": int(depth[near]),
                "length_km": float((table["length_km"]).sum()),
                "r_ohm": float((table["r_ohm_per_km"] * table["length_km"]).sum()),
                "r0_ohm": float((table["r0_ohm_per_km"] * table["length_km"]).sum()),
                "x_ohm": float((table["x_ohm_per_km"] * table["length_km"]).sum()),
                "downstream_buses": sorted(int(b) for b in downstream),
                "incident_to_busbar": int(near) == int(root),
            })
    if sum(s["n_segments"] for s in out) != len(net.line.index):
        raise RuntimeError("the sections do not partition the segments")
    return out


def annotate_sections(secs: list[dict], custs: list[dict]) -> list[dict]:
    """Add each section's downstream customers, their phases, installed PV and peak load (J4)."""
    for section in secs:
        buses = set(section["downstream_buses"])
        inside = [c for c in custs if c["bus"] in buses]
        phases = {ph: sum(1 for c in inside if c["phase"] == ph) for ph in PHASES}
        with_pv = [c for c in inside if c["has_pv"]]
        section["downstream_customers"] = [c["position"] for c in inside]
        section["n_downstream_customers"] = len(inside)
        section["downstream_customer_phases"] = phases
        section["n_downstream_pv"] = len(with_pv)
        section["downstream_pv_kwp"] = PV_KWP * len(with_pv)
        section["downstream_peak_load_kw"] = CUSTOMER_PEAK_KW * len(inside)
        section["pv_kwp_times_r"] = section["downstream_pv_kwp"] * section["r_ohm"]
        section["peak_load_kw_times_r"] = section["downstream_peak_load_kw"] * section["r_ohm"]
    return secs


# --- step 2: the structural invariants -----------------------------------------------------


def invariants(net) -> dict:
    """Phase 9's s. 3 structural invariants, read on this feeder. Exact and flow-free."""
    lv_buses = sorted({int(b) for b in net.line["from_bus"]} | {int(b) for b in net.line["to_bus"]})
    n_lines = int(len(net.line.index))
    try:
        tree = rooted_tree(net)
        connected_acyclic, reason = True, None
    except RuntimeError as error:
        tree, connected_acyclic, reason = None, False, str(error)
    switches = net.switch[net.switch["et"] == "l"] if len(net.switch.index) else net.switch
    checks = {
        "lv_buses_equal_lines_plus_one": {
            "lv_buses": len(lv_buses), "lines": n_lines,
            "ok": len(lv_buses) == n_lines + 1},  # fmt: skip
        "line_graph_connected_and_acyclic": {
            "ok": connected_acyclic, "reason": reason,
            "reachable_from_busbar": None if tree is None else len(tree["order"])},  # fmt: skip
        "every_line_parallel_is_one": {
            "distinct": sorted({int(v) for v in net.line["parallel"]}),
            "ok": bool((net.line["parallel"] == 1).all())},  # fmt: skip
        "every_line_in_service": {
            "out_of_service": int((~net.line["in_service"].astype(bool)).sum()),
            "ok": bool(net.line["in_service"].astype(bool).all())},  # fmt: skip
        "every_line_switch_closed": {
            "line_switches": int(len(switches.index)),
            "open": int((~switches["closed"].astype(bool)).sum()) if len(switches.index) else 0,
            "ok": bool(switches["closed"].astype(bool).all()) if len(switches.index) else True},
        "radial": {
            "reading": "one slack through one transformer, and a connected acyclic line "
                       "graph over the LV buses, is a radial feeder",
            "ext_grid": int(len(net.ext_grid.index)), "trafo": int(len(net.trafo.index)),
            "ok": connected_acyclic and len(net.ext_grid.index) == 1
                  and len(net.trafo.index) == 1},  # fmt: skip
    }
    return {"checks": checks, "ok": all(c["ok"] for c in checks.values())}


def topology(net=None) -> dict:
    """Step 2, zero flows: the recorded facts, the invariants and the cable sections."""
    net = eulv_network() if net is None else net
    custs = customers(net)
    secs = annotate_sections(sections(net, {c["bus"] for c in custs}), custs)
    candidates = [s for s in secs if not s["incident_to_busbar"]]
    sizes = np.array([s["n_segments"] for s in secs], dtype=int)
    lengths = np.array([s["length_km"] for s in secs], dtype=float)
    boundary = sorted({s["near_bus"] for s in secs} | {s["far_bus"] for s in secs})
    nominal_voltages = net.bus["vn_kv"].value_counts().sort_index()
    seg_length = net.line["length_km"].to_numpy(dtype=float)
    zero_sequence = [f for f in ("r0_ohm_per_km", "x0_ohm_per_km", "c0_nf_per_km")
                     if f in net.line.columns and net.line[f].notna().all()]  # fmt: skip
    facts = {
        "buses": int(len(net.bus.index)),
        "buses_by_vn_kv": {f"{float(v):g}": int(n) for v, n in nominal_voltages.items()},
        "lines": int(len(net.line.index)),
        "total_length_km": float(seg_length.sum()),
        "segment_length_m": {"median": float(np.median(seg_length) * 1000.0),
                             "min": float(seg_length.min() * 1000.0),
                             "max": float(seg_length.max() * 1000.0)},  # fmt: skip
        "zero_sequence_columns_complete": zero_sequence,
        "asymmetric_loads": int(len(net.asymmetric_load.index)),
        "customers_by_phase": {ph: sum(1 for c in custs if c["phase"] == ph) for ph in PHASES},
        "snapshot_load_kw": {
            "mean": float(np.mean([c["snapshot_p_mw"] for c in custs]) * 1000.0),
            "min": float(np.min([c["snapshot_p_mw"] for c in custs]) * 1000.0),
            "max": float(np.max([c["snapshot_p_mw"] for c in custs]) * 1000.0)},  # fmt: skip
        "sgen": int(len(net.sgen.index)),
        "asymmetric_sgen": int(len(net.asymmetric_sgen.index)),
        "trafo": [{"sn_mva": float(net.trafo.at[i, "sn_mva"]),
                   "vn_hv_kv": float(net.trafo.at[i, "vn_hv_kv"]),
                   "vn_lv_kv": float(net.trafo.at[i, "vn_lv_kv"]),
                   "lv_bus": int(net.trafo.at[i, "lv_bus"])} for i in net.trafo.index],  # fmt: skip
        "lv_busbar": BUSBAR,
        "boundary_nodes": len(boundary),
        "switches": int(len(net.switch.index)),
    }
    selected = select_sections(secs)
    return {
        "facts": facts,
        "invariants": invariants(net),
        "customers": custs,
        "sections": secs,
        "section_summary": {
            "count": len(secs),
            "candidates": len(candidates),
            "incident_to_busbar": len(secs) - len(candidates),
            "segments_per_section": {
                "min": int(sizes.min()), "median": float(np.median(sizes)),
                "mean": float(sizes.mean()), "max": int(sizes.max()),
                "histogram": {str(int(k)): int(v) for k, v
                              in zip(*np.unique(sizes, return_counts=True),
                                     strict=True)}},  # fmt: skip
            "length_m": {"min": float(lengths.min() * 1000.0),
                         "median": float(np.median(lengths) * 1000.0),
                         "mean": float(lengths.mean() * 1000.0),
                         "max": float(lengths.max() * 1000.0)},  # fmt: skip
            "with_downstream_customers": int(sum(1 for s in secs
                                                 if s["n_downstream_customers"] > 0)),
            "with_downstream_pv": int(sum(1 for s in secs if s["n_downstream_pv"] > 0)),
            "candidate_definition": "a section not incident to the LV busbar",
        },
        "selected_sections": selected,
    }


# --- step 4: the three sections, fixed by rule before any flow -----------------------------


SELECTION_RULES = {
    "a": "the candidate section with the largest downstream installed PV (kWp) x section R "
         "(ohm); the stress.local_line analogue",
    "b": "among candidate sections with downstream PV > 0 and >= 3 downstream customers, the "
         "one whose busbar depth in segments is closest to the median depth of that group, "
         "ties broken by the lowest first-segment index",
    "c": "among candidate sections with zero downstream PV and >= 1 downstream customer, the "
         "largest downstream peak load (kW) x section R (ohm); a non-reversing cable",
}


def select_sections(secs: list[dict]) -> dict:
    """Rules (a), (b) and (c) over the candidate sections (J3). No power flow is needed."""
    candidates = [s for s in secs if not s["incident_to_busbar"]]
    if not candidates:
        raise RuntimeError("no candidate section")
    out: dict[str, dict] = {}

    pool_a = candidates
    pick_a = max(pool_a, key=lambda s: (s["pv_kwp_times_r"], -s["first_segment"]))
    out["a"] = _selection(pick_a, pool_a, "pv_kwp_times_r")

    pool_b = [s for s in candidates if s["n_downstream_pv"] > 0
              and s["n_downstream_customers"] >= 3]  # fmt: skip
    if not pool_b:
        raise RuntimeError("rule (b) has an empty pool")
    median_depth = float(np.median([s["depth_segments"] for s in pool_b]))
    pick_b = min(pool_b, key=lambda s: (abs(s["depth_segments"] - median_depth),
                                        s["first_segment"]))  # fmt: skip
    out["b"] = _selection(pick_b, pool_b, "depth_segments")
    out["b"]["median_depth_of_pool"] = median_depth
    out["b"]["depth_distance"] = abs(pick_b["depth_segments"] - median_depth)

    pool_c = [s for s in candidates if s["n_downstream_pv"] == 0
              and s["n_downstream_customers"] >= 1]  # fmt: skip
    if not pool_c:
        raise RuntimeError("rule (c) has an empty pool")
    pick_c = max(pool_c, key=lambda s: (s["peak_load_kw_times_r"], -s["first_segment"]))
    out["c"] = _selection(pick_c, pool_c, "peak_load_kw_times_r")

    for leg, block in out.items():
        block["rule"] = SELECTION_RULES[leg]
    return out


def _selection(pick: dict, pool: list[dict], criterion: str) -> dict:
    return {
        "criterion": criterion,
        "pool_size": len(pool),
        "section": pick["section"],
        "segments": list(pick["segments"]),
        "n_segments": pick["n_segments"],
        "first_segment": pick["first_segment"],
        "near_bus": pick["near_bus"],
        "far_bus": pick["far_bus"],
        "depth_segments": pick["depth_segments"],
        "length_m": pick["length_km"] * 1000.0,
        "r_ohm": pick["r_ohm"],
        "r0_ohm": pick["r0_ohm"],
        "n_downstream_buses": len(pick["downstream_buses"]),
        "n_downstream_customers": pick["n_downstream_customers"],
        "downstream_customers": list(pick["downstream_customers"]),
        "downstream_customer_phases": dict(pick["downstream_customer_phases"]),
        "n_downstream_pv": pick["n_downstream_pv"],
        "downstream_pv_kwp": pick["downstream_pv_kwp"],
        "downstream_peak_load_kw": pick["downstream_peak_load_kw"],
        "criterion_value": pick[criterion],
    }


def apply_section_error(net, segments) -> None:
    """E-R(1.5) on every segment of one section: r and r0 x 1.5, max_i_ka x 0.8. In place."""
    for segment in segments:
        segment = int(segment)
        if segment not in net.line.index:
            raise ValueError(f"segment {segment} is not in the line table")
        net.line.at[segment, "r_ohm_per_km"] *= R_FACTOR
        net.line.at[segment, "r0_ohm_per_km"] *= R_FACTOR
        net.line.at[segment, "max_i_ka"] *= RATING_FACTOR


# --- the synthetic scenario ----------------------------------------------------------------


def profile_inputs() -> dict:
    """The SimBench material the scenario is built from. Zero power flows."""
    import pandas as pd

    from gridpulse import dual_study as ds
    from gridpulse import grid, grid_study

    net_sb = ds.variant_network(PROFILE_NETWORK, ds.NOMINAL, ds.pv_scale(PROFILE_NETWORK))
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net_sb))
    load_p = np.asarray(arrays["load_p_mw"], dtype=float)
    n_loads = load_p.shape[2]
    annual_max = load_p.reshape(-1, n_loads).max(axis=0)
    if not (annual_max > 0).all():
        raise RuntimeError("a semiurb4 load profile has a non-positive annual maximum")
    rating = np.asarray(net_sb.sgen["sn_mva"], dtype=float)
    if rating[0] <= 0:
        raise RuntimeError("semiurb4's first sgen has a non-positive rating")
    available = np.asarray(arrays["sgen_p_mw"], dtype=float)[:, :, 0] / rating[0]
    day_zero = int((pd.Timestamp(START_DATE, tz="UTC") - grid_study.FIRST_DAY).days)
    days = list(range(day_zero, day_zero + N_DAYS))
    development = set(grid_study.period_days("development"))
    outside = [d for d in days if d not in development]
    if outside:
        raise RuntimeError(f"days {outside} are outside the development half")
    return {
        "days": days,
        "n_loads": int(n_loads),
        "norm_load": load_p[days] / annual_max,
        "availability": available[days],
        "pv_rating_mva": float(rating[0]),
        "annual_max_mw": annual_max,
    }


def scenario_arrays(n_customers: int, inputs: dict | None = None) -> dict:
    """The scenario as arrays: per-customer p and q, PV p, the daylight masks, the day list."""
    inputs = profile_inputs() if inputs is None else inputs
    columns = [i % inputs["n_loads"] for i in range(n_customers)]
    norm = inputs["norm_load"][:, :, columns]
    p_mw = norm * (CUSTOMER_PEAK_KW / 1000.0)
    q_mvar = p_mw * math.tan(math.acos(COS_PHI))
    availability = inputs["availability"]
    pv_mw = availability * (PV_KWP / 1000.0)
    daylight = availability > 0.0
    retained = [i for i in range(len(inputs["days"]))
                if bool(daylight[i].any()) and bool((~daylight[i]).any())]  # fmt: skip
    if not retained:
        raise RuntimeError("no scenario day has both a daylight and a night step")
    return {
        "days": [int(inputs["days"][i]) for i in retained],
        "all_days": [int(d) for d in inputs["days"]],
        "dropped_days": [int(inputs["days"][i]) for i in range(len(inputs["days"]))
                         if i not in retained],  # fmt: skip
        "p_mw": p_mw[retained],
        "q_mvar": q_mvar[retained],
        "pv_mw": pv_mw[retained],
        "daylight": daylight[retained],
        "profile_columns": columns,
    }


def scenario_network(custs: list[dict], segments=None):
    """A leg's network: the scenario's PV elements added, `scaling` forced to 1 (J5), and
    E-R(1.5) applied to `segments` if an error leg."""
    import pandapower as pp

    net = eulv_network()
    net.asymmetric_load["scaling"] = 1.0
    sgen_of: dict[int, int] = {}
    for customer in custs:
        if not customer["has_pv"]:
            continue
        index = pp.create_asymmetric_sgen(
            net, bus=customer["bus"], name=f"pv_customer_{customer['position']}",
            sn_mva=PV_KWP / 1000.0, type="wye",
        )  # fmt: skip
        sgen_of[customer["position"]] = int(index)
    if len(net.asymmetric_sgen.index):
        net.asymmetric_sgen["scaling"] = 1.0
    if segments:
        apply_section_error(net, segments)
    return net, sgen_of


def balanced_network(custs: list[dict], segments=None):
    """Step 3 (b): the balanced equivalent. Each single-phase load and PV becomes a balanced
    load / sgen of the same total P and Q at the same bus."""
    import pandapower as pp

    net = eulv_network()
    net.asymmetric_load = net.asymmetric_load.drop(net.asymmetric_load.index)
    load_of, sgen_of = {}, {}
    for customer in custs:
        load_of[customer["position"]] = int(pp.create_load(
            net, bus=customer["bus"], p_mw=0.0, q_mvar=0.0,
            name=f"balanced_customer_{customer['position']}"))  # fmt: skip
        if customer["has_pv"]:
            sgen_of[customer["position"]] = int(pp.create_sgen(
                net, bus=customer["bus"], p_mw=0.0, sn_mva=PV_KWP / 1000.0,
                name=f"balanced_pv_{customer['position']}"))  # fmt: skip
    if segments:
        apply_section_error(net, segments)
    return net, load_of, sgen_of


# --- the solve loops -----------------------------------------------------------------------


def own_phase_voltages(vm: np.ndarray, customer_rows, customer_phases, busbar_row: int):
    """Each customer's own-phase voltage and the busbar's three phase voltages.

    `vm` is the [buses, 3] array of `res_bus_3ph` `vm_{a,b,c}_pu` in row order.
    """
    vm = np.asarray(vm, dtype=float)
    if vm.ndim != 2 or vm.shape[1] != 3:
        raise ValueError(f"expected a [buses, 3] voltage array, got {vm.shape}")
    rows = np.asarray(customer_rows, dtype=int)
    phases = np.asarray(customer_phases, dtype=int)
    own = vm[rows, phases]
    return np.concatenate([own, vm[int(busbar_row)]])


def _assign_three_phase(net, custs, sgen_of, p_mw, q_mvar, pv_mw) -> None:
    """One step's injections on the asymmetric tables, as whole columns."""
    load_rows = {int(e): i for i, e in enumerate(net.asymmetric_load.index)}
    pl = np.zeros((len(load_rows), 3))
    ql = np.zeros((len(load_rows), 3))
    for customer in custs:
        row, phase = load_rows[customer["element"]], customer["phase_index"]
        pl[row, phase] = p_mw[customer["position"]]
        ql[row, phase] = q_mvar[customer["position"]]
    for index, phase in enumerate(PHASES):
        net.asymmetric_load[f"p_{phase}_mw"] = pl[:, index]
        net.asymmetric_load[f"q_{phase}_mvar"] = ql[:, index]
    if not sgen_of:
        return
    sgen_rows = {int(e): i for i, e in enumerate(net.asymmetric_sgen.index)}
    pg = np.zeros((len(sgen_rows), 3))
    for customer in custs:
        if not customer["has_pv"]:
            continue
        pg[sgen_rows[sgen_of[customer["position"]]], customer["phase_index"]] = pv_mw
    for index, phase in enumerate(PHASES):
        net.asymmetric_sgen[f"p_{phase}_mw"] = pg[:, index]


def _solve_3ph(net) -> bool:
    import pandapower as pp

    try:
        pp.runpp_3ph(net, numba=False)
    except Exception:  # a non-converged flow has no valid state (grid.py's convention)
        return False
    return bool(net.get("converged", True)) and bool(net.res_bus_3ph["vm_a_pu"].notna().all())


def run_leg(leg: str, custs: list[dict], segments, scenario: dict, root: int = BUSBAR) -> dict:
    """One leg: a three-phase solve per retained day and step, own-phase voltages recorded."""
    net, sgen_of = scenario_network(custs, segments)
    n_days, n_steps = scenario["daylight"].shape
    n_customers = len(custs)
    out = np.full((n_days, n_steps, n_customers + 3), np.nan, dtype=np.float64)
    rows = None
    failed = 0
    started = time.perf_counter()
    for day in range(n_days):
        for step in range(n_steps):
            _assign_three_phase(net, custs, sgen_of, scenario["p_mw"][day, step],
                                scenario["q_mvar"][day, step],
                                float(scenario["pv_mw"][day, step]))  # fmt: skip
            if not _solve_3ph(net):
                failed += 1
                continue
            if rows is None:
                index = net.res_bus_3ph.index
                rows = {
                    "customers": index.get_indexer([c["bus"] for c in custs]),
                    "phases": [c["phase_index"] for c in custs],
                    "busbar": int(index.get_indexer([root])[0]),
                }
                if min(rows["customers"].min(), rows["busbar"]) < 0:
                    raise RuntimeError("a customer bus or the busbar is not in res_bus_3ph")
            vm = net.res_bus_3ph[[f"vm_{ph}_pu" for ph in PHASES]].to_numpy(dtype=float)
            out[day, step] = own_phase_voltages(vm, rows["customers"], rows["phases"],
                                                rows["busbar"])  # fmt: skip
    elapsed = time.perf_counter() - started
    solves = n_days * n_steps
    return {
        "leg": leg,
        "segments": [int(s) for s in (segments or [])],
        "vm": out,
        "solves": solves,
        "failed": failed,
        "elapsed_seconds": elapsed,
        "per_solve_seconds": elapsed / solves,
        "peak_rss_bytes": peak_rss_bytes(),
    }


def peak_rss_bytes() -> int:
    """`ru_maxrss` normalised to bytes: macOS reports bytes, Linux kilobytes."""
    raw = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return raw if sys.platform == "darwin" else raw * 1024


# --- step 3: the timing probe --------------------------------------------------------------


def timing_probe(days: int = TIMING_DAYS) -> dict:
    """Step 3: `days` x 96 steps three-phase, then the same steps balanced."""
    import pandapower as pp

    net_eulv = eulv_network()
    custs = customers(net_eulv)
    scenario = scenario_arrays(len(custs))
    if len(scenario["days"]) < days:
        raise RuntimeError(f"only {len(scenario['days'])} retained days for a {days}-day probe")
    probe_days = list(range(days))

    asym, sgen_asym = scenario_network(custs, None)
    times_a, failed_a = [], 0
    for day in probe_days:
        for step in range(STEPS):
            _assign_three_phase(asym, custs, sgen_asym,
                                scenario["p_mw"][day, step], scenario["q_mvar"][day, step],
                                float(scenario["pv_mw"][day, step]))  # fmt: skip
            started = time.perf_counter()
            ok = _solve_3ph(asym)
            times_a.append(time.perf_counter() - started)
            failed_a += 0 if ok else 1

    balanced, load_of, sgen_of = balanced_network(custs, None)
    times_b, failed_b = [], 0
    for day in probe_days:
        for step in range(STEPS):
            _assign_balanced(balanced, custs, load_of, sgen_of,
                             scenario["p_mw"][day, step], scenario["q_mvar"][day, step],
                             float(scenario["pv_mw"][day, step]))  # fmt: skip
            started = time.perf_counter()
            try:
                pp.runpp(balanced, numba=False)
                ok = bool(balanced["converged"]) and bool(balanced.res_bus["vm_pu"].notna().all())
            except Exception:
                ok = False
            times_b.append(time.perf_counter() - started)
            failed_b += 0 if ok else 1

    return {
        "status": STATUS,
        "step": "3 (timing probe)",
        "days": [int(scenario["days"][d]) for d in probe_days],
        "steps_per_day": STEPS,
        "numba": False,
        "numba_installed": _numba_installed(),
        "three_phase": _timing_record("pp.runpp_3ph on the asymmetric network",
                                      times_a, failed_a),  # fmt: skip
        "balanced": _timing_record("pp.runpp on the balanced equivalent (same total P and Q "
                                   "per bus)", times_b, failed_b),  # fmt: skip
        "peak_rss_bytes": peak_rss_bytes(),
        "peak_rss_mb": peak_rss_bytes() / 1e6,
        "flows": len(times_a) + len(times_b),
        "platform": {"system": platform.system(), "release": platform.release(),
                     "machine": platform.machine(), "python": platform.python_version(),
                     "pandapower": _package_version("pandapower")},  # fmt: skip
    }


def _assign_balanced(net, custs, load_of, sgen_of, p_mw, q_mvar, pv_mw) -> None:
    rows = {int(e): i for i, e in enumerate(net.load.index)}
    p = np.zeros(len(rows))
    q = np.zeros(len(rows))
    for customer in custs:
        row = rows[load_of[customer["position"]]]
        p[row] = p_mw[customer["position"]]
        q[row] = q_mvar[customer["position"]]
    net.load["p_mw"] = p
    net.load["q_mvar"] = q
    if not sgen_of:
        return
    sgen_rows = {int(e): i for i, e in enumerate(net.sgen.index)}
    g = np.zeros(len(sgen_rows))
    for customer in custs:
        if customer["has_pv"]:
            g[sgen_rows[sgen_of[customer["position"]]]] = pv_mw
    net.sgen["p_mw"] = g


def _timing_record(what: str, times: list[float], failed: int) -> dict:
    array = np.asarray(times, dtype=float)
    return {
        "what": what,
        "solves": int(array.size),
        "failed_flows": int(failed),
        "mean_ms": float(array.mean() * 1000.0),
        "median_ms": float(np.median(array) * 1000.0),
        "max_ms": float(array.max() * 1000.0),
        "min_ms": float(array.min() * 1000.0),
        "total_seconds": float(array.sum()),
    }


def _numba_installed() -> bool:
    from importlib.util import find_spec

    return find_spec("numba") is not None


# --- the artefacts -------------------------------------------------------------------------


def leg_stem(leg: str, selected: dict, key: str) -> str:
    if leg == "nominal":
        return f"nominal_{key[:16]}"
    block = selected[leg]
    return (f"er{_factor_text(R_FACTOR)}_{leg}_sec{block['section']}"
            f"_s{block['first_segment']}_{key[:16]}")  # fmt: skip


def _factor_text(factor: float) -> str:
    return ps.factor_text(factor)


def leg_path(leg: str, selected: dict, key: str, root: Path = EULV) -> Path:
    return Path(root) / f"{leg_stem(leg, selected, key)}.npz"


def write_leg(path: Path, arrays: dict, sidecar: dict) -> dict:
    """Write the `.npz` and its sidecar `.json` once, each atomically, refusing to overwrite.

    Both files are built in a temporary file in the same directory and published with one
    `os.replace`; the `finally` clause removes any temporary a raising write left behind.
    An existing target is never replaced: the leg must be deleted by hand first, which is
    Phase 9's s. 7 convention.
    """
    path = Path(path)
    sidecar_file = path.with_suffix(".json")
    for target in (path, sidecar_file):
        if target.exists():
            raise RuntimeError(f"refusing to overwrite {target}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = q1.json_text(sidecar)
    tmp_npz = path.with_name(path.stem + ".partial.npz")
    tmp_json = path.with_name(path.stem + ".partial.json")
    try:
        with open(tmp_npz, "wb") as stream:
            np.savez_compressed(stream, **arrays)
        tmp_json.write_text(text)
        if path.exists() or sidecar_file.exists():
            raise RuntimeError(f"refusing to overwrite {path}")
        os.replace(tmp_npz, path)
        os.replace(tmp_json, sidecar_file)
    finally:
        for temporary in (tmp_npz, tmp_json):
            if temporary.exists():
                temporary.unlink()
    return {"npz": _reported(path), "sidecar": _reported(sidecar_file)}


def write_json_once(path: Path, payload) -> dict:
    """`q1.write_new_json`'s refuse-to-overwrite rule, through a temporary and `os.replace`."""
    path = Path(path)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    text = q1.json_text(payload)
    temporary = path.with_name(path.stem + ".partial.json")
    try:
        temporary.write_text(text)
        if path.exists():
            raise RuntimeError(f"refusing to overwrite {path}")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _reported(path)


def run_smoke(leg: str) -> dict:
    """Step 4, one leg: 10 retained days x 96 steps, written once under `eulv/`."""
    net = eulv_network()
    custs = customers(net)
    key = physics_key(net)
    secs = annotate_sections(sections(net, {c["bus"] for c in custs}), custs)
    selected = select_sections(secs)
    segments = None if leg == "nominal" else selected[leg]["segments"]
    path = leg_path(leg, selected, key)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite {path}; delete it to recompute")
    scenario = scenario_arrays(len(custs))
    result = run_leg(leg, custs, segments, scenario)
    arrays = {
        "vm": result["vm"],
        "daylight": scenario["daylight"].astype(np.bool_),
        "day_index": np.asarray(scenario["days"], dtype=np.int32),
        "customer_bus": np.asarray([c["bus"] for c in custs], dtype=np.int32),
        "customer_phase_index": np.asarray([c["phase_index"] for c in custs], dtype=np.int8),
        "customer_has_pv": np.asarray([c["has_pv"] for c in custs], dtype=np.bool_),
        "columns": np.asarray([f"customer_{c['position']}_vm_{c['phase']}_pu" for c in custs]
                              + [f"busbar_vm_{ph}_pu" for ph in PHASES]),  # fmt: skip
    }
    sidecar = {
        "status": STATUS,
        "step": "4 (smoke run)",
        "leg": leg,
        "key": key,
        "error": None if leg == "nominal" else {
            "type": ERROR, "r_factor": R_FACTOR, "rating_factor": RATING_FACTOR,
            "columns": list(ERROR_FIELDS), "segments": [int(s) for s in segments],
            "selection": selected[leg]},  # fmt: skip
        "scenario": SCENARIO,
        "days": scenario["days"],
        "dropped_days": scenario["dropped_days"],
        "steps_per_day": STEPS,
        "solves": result["solves"],
        "failed_flows": result["failed"],
        "elapsed_seconds": result["elapsed_seconds"],
        "per_solve_seconds": result["per_solve_seconds"],
        "peak_rss_bytes": result["peak_rss_bytes"],
        "shape": list(result["vm"].shape),
        "dtype": "float64 (J6)",
        "provenance": {"pandapower": _package_version("pandapower"),
                       "numba_installed": _numba_installed(),
                       "line_table_sha256": line_table_sha256(net)},  # fmt: skip
    }
    return {**write_leg(path, arrays, sidecar), "spec": sidecar}


# --- the reduction and the report -----------------------------------------------------------


def reduce_leg(vm_error: np.ndarray, vm_nominal: np.ndarray, daylight: np.ndarray,
               custs: list[dict]) -> dict:  # fmt: skip
    """Phase 9's per-day reduction, then k, k_ref, m and night per customer.

    `phase9_sweep.reduce_day` is called unchanged, once per day, on the [96, customers + 3]
    column block. c_d is its daylight mean minus its night mean; c_d^ref subtracts the
    busbar's c_d on the customer's own phase.
    """
    vm_error = np.asarray(vm_error, dtype=np.float64)
    vm_nominal = np.asarray(vm_nominal, dtype=np.float64)
    daylight = np.asarray(daylight, dtype=bool)
    n_days = vm_error.shape[0]
    n_customers = len(custs)
    phase_column = {ph: n_customers + i for i, ph in enumerate(PHASES)}
    rows = [ps.reduce_day(vm_error[d], vm_nominal[d], daylight[d]) for d in range(n_days)]
    usable = [d for d, row in enumerate(rows)
              if row["n_daylight_valid"] > 0 and row["n_night_valid"] > 0
              and np.isfinite(row["dmean_daylight"]).all()
              and np.isfinite(row["dmean_night"]).all()]  # fmt: skip
    if not usable:
        raise RuntimeError("no day has a valid daylight and a valid night step")
    day_light = np.stack([rows[d]["dmean_daylight"] for d in usable])
    day_night = np.stack([rows[d]["dmean_night"] for d in usable])
    contrast = day_light - day_night
    reference = np.stack([contrast[:, phase_column[c["phase"]]] for c in custs], axis=1)
    contrast_ref = contrast[:, :n_customers] - reference
    return {
        "per_day": [{k: (v if not isinstance(v, np.ndarray) else None)
                     for k, v in row.items() if not isinstance(v, np.ndarray)}
                    for row in rows],  # fmt: skip
        "usable_days": usable,
        "n_daylight_valid": [int(rows[d]["n_daylight_valid"]) for d in usable],
        "n_night_valid": [int(rows[d]["n_night_valid"]) for d in usable],
        "failed_steps": int(sum(row["failed_truth"] for row in rows)),
        "c_d": contrast[:, :n_customers],
        "c_d_ref": contrast_ref,
        "c_d_busbar": contrast[:, n_customers:],
        "m": day_light[:, :n_customers].mean(axis=0),
        "night": day_night[:, :n_customers].mean(axis=0),
        "k": contrast[:, :n_customers].mean(axis=0),
        "k_ref": contrast_ref.mean(axis=0),
        "k_busbar": contrast[:, n_customers:].mean(axis=0),
    }


def _split(values: np.ndarray, downstream: np.ndarray) -> dict:
    values = np.abs(np.asarray(values, dtype=float))
    out = {}
    for label, mask in (("downstream", downstream), ("off_downstream", ~downstream)):
        if not mask.any():
            out[label] = {"customers": 0, "max": None, "median": None}
            continue
        out[label] = {"customers": int(mask.sum()), "max": float(values[mask].max()),
                      "median": float(np.median(values[mask]))}  # fmt: skip
    return out


def _night_sign_split(m: np.ndarray, night: np.ndarray, downstream: np.ndarray) -> dict:
    """The share of customers whose night residual has the opposite sign to their daylight
    residual, downstream against off-downstream (`phase9_analysis.opposite_sign`)."""
    out = {}
    for label, mask in (("downstream", downstream), ("off_downstream", ~downstream)):
        index = np.flatnonzero(mask)
        if index.size == 0:
            out[label] = {"customers": 0, "opposite_sign": 0, "share": None}
            continue
        hits = sum(1 for i in index if _opposite_sign(float(m[i]), float(night[i])))
        out[label] = {"customers": int(index.size), "opposite_sign": int(hits),
                      "share": hits / index.size}  # fmt: skip
    return out


def _opposite_sign(a: float, b: float) -> bool:
    return (math.isfinite(a) and math.isfinite(b) and np.sign(a) != 0
            and np.sign(b) != 0 and np.sign(a) != np.sign(b))  # fmt: skip


def illustrative_c1(k_ref: np.ndarray, n_daylight: list[int], n_night: list[int],
                    downstream: np.ndarray) -> dict:  # fmt: skip
    """ILLUSTRATIVE only (J10): |k_ref| / (z_K sigma sqrt(sum_d(1/n_d + 1/m_d)) / D)."""
    n_d = np.asarray(n_daylight, dtype=float)
    m_d = np.asarray(n_night, dtype=float)
    days = n_d.size
    z = q1.z_bonferroni(K_ILLUSTRATIVE)
    floor = z * SIGMA_ILLUSTRATIVE * math.sqrt(float((1.0 / n_d + 1.0 / m_d).sum())) / days
    ratio = np.abs(np.asarray(k_ref, dtype=float)) / floor
    return {
        "label": "ILLUSTRATIVE",
        "caveat": "10 days, noise-free Delta, no meter-placement rule, no multiplicity over "
                  "cables, and the denominator omits the busbar noise term of proposal "
                  "s. 3.2. Not a detection rate.",
        "sigma": SIGMA_ILLUSTRATIVE,
        "K": K_ILLUSTRATIVE,
        "D": int(days),
        "z_K": z,
        "floor_pu": floor,
        "ratio": _split(ratio, downstream),
        "customers_over_one": {
            "downstream": int(((ratio >= 1.0) & downstream).sum()),
            "off_downstream": int(((ratio >= 1.0) & ~downstream).sum()),
        },
    }


def cost_extrapolation(per_solve_3ph: float, per_solve_balanced: float,
                       probe_per_solve_3ph: float) -> dict:  # fmt: skip
    solves = MAIN_STUDY["runs"] * MAIN_STUDY["days"] * MAIN_STUDY["steps"]
    hours_3ph = solves * per_solve_3ph / 3600.0
    hours_balanced = solves * per_solve_balanced / 3600.0
    return {
        "measured_per_solve_seconds": {
            "three_phase_smoke_run": per_solve_3ph,
            "three_phase_timing_probe": probe_per_solve_3ph,
            "balanced_timing_probe": per_solve_balanced,
            "source": "the smoke run's constant is used for the extrapolation (J8)",
        },
        "main_study": {
            "definition": f"{MAIN_STUDY['runs']} runs x {MAIN_STUDY['days']} days x "
                          f"{MAIN_STUDY['steps']} steps (proposal s. 6)",
            "solves": solves,
            "cpu_hours_three_phase": hours_3ph,
            "cpu_hours_balanced": hours_balanced,
        },
        "K1": {
            "criterion": f"more than {K1_CPU_HOURS:g} CPU-hours for the main study",
            "three_phase_tripped": bool(hours_3ph > K1_CPU_HOURS),
            "balanced_tripped": bool(hours_balanced > K1_CPU_HOURS),
            "verdict": "TRIPPED" if hours_3ph > K1_CPU_HOURS else "NOT TRIPPED",
            "reading": "the three-phase figure is the binding one: the proposal's detector "
                       "reads per-phase voltages at single-phase customers, which the "
                       "balanced solve cannot produce. The balanced figure is reported as "
                       "the cost of the weaker, balanced-only variant.",
        },
    }


def report(output: Path = OUTPUT, timing_file: Path = TIMING_FILE) -> dict:
    """Step 4's reduction and the cost extrapolation, written once."""
    net = eulv_network()
    custs = customers(net)
    key = physics_key(net)
    topo = topology(net)
    selected = topo["selected_sections"]
    if not Path(timing_file).exists():
        raise RuntimeError(f"{timing_file} is missing; run the `timing` command first")
    timing = json.loads(Path(timing_file).read_text())

    legs = {}
    for leg in ("nominal", "a", "b", "c"):
        path = leg_path(leg, selected, key)
        if not path.exists():
            raise RuntimeError(f"{path} is missing; run `smoke --leg {leg}` first")
        with np.load(path, allow_pickle=False) as data:
            legs[leg] = {name: data[name] for name in data.files}
        legs[leg]["sidecar"] = json.loads(path.with_suffix(".json").read_text())
        legs[leg]["record"] = _reported(path)
        legs[leg]["sidecar_record"] = _reported(path.with_suffix(".json"))

    nominal = legs["nominal"]
    daylight = nominal["daylight"]
    for leg, block in legs.items():
        if not np.array_equal(block["day_index"], nominal["day_index"]):
            raise RuntimeError(f"leg {leg} carries a different day list")
        if not np.array_equal(block["daylight"], daylight):
            raise RuntimeError(f"leg {leg} carries a different daylight mask")
        if block["sidecar"]["key"] != key:
            raise RuntimeError(f"leg {leg} carries key {block['sidecar']['key']}, not {key}")

    per_leg = {}
    for leg in ("a", "b", "c"):
        downstream_buses = set(topo["sections"][selected[leg]["section"]]["downstream_buses"])
        downstream = np.asarray([c["bus"] in downstream_buses for c in custs], dtype=bool)
        reduction = reduce_leg(legs[leg]["vm"], nominal["vm"], daylight, custs)
        per_leg[leg] = {
            "selection": selected[leg],
            "artefact": legs[leg]["record"],
            "sidecar": legs[leg]["sidecar_record"],
            "solves": int(legs[leg]["sidecar"]["solves"]),
            "failed_flows": int(legs[leg]["sidecar"]["failed_flows"]),
            "per_solve_seconds": float(legs[leg]["sidecar"]["per_solve_seconds"]),
            "usable_days": reduction["usable_days"],
            "n_daylight_valid": reduction["n_daylight_valid"],
            "n_night_valid": reduction["n_night_valid"],
            "downstream_customers": [int(i) for i in np.flatnonzero(downstream)],
            "n_downstream_customers": int(downstream.sum()),
            "k_pu": _split(reduction["k"], downstream),
            "k_ref_pu": _split(reduction["k_ref"], downstream),
            "m_pu": _split(reduction["m"], downstream),
            "night_pu": _split(reduction["night"], downstream),
            "k_busbar_pu": {ph: float(reduction["k_busbar"][i]) for i, ph in enumerate(PHASES)},
            "night_sign_split": _night_sign_split(reduction["m"], reduction["night"], downstream),
            "illustrative_c1": illustrative_c1(reduction["k_ref"], reduction["n_daylight_valid"],
                                               reduction["n_night_valid"], downstream),  # fmt: skip
            "per_customer": [
                {"customer": c["position"], "bus": c["bus"], "phase": c["phase"],
                 "has_pv": bool(c["has_pv"]), "downstream": bool(downstream[i]),
                 "k_pu": float(reduction["k"][i]), "k_ref_pu": float(reduction["k_ref"][i]),
                 "m_pu": float(reduction["m"][i]), "night_pu": float(reduction["night"][i])}
                for i, c in enumerate(custs)],  # fmt: skip
        }

    smoke_solves = sum(int(legs[leg]["sidecar"]["solves"]) for leg in legs)
    smoke_seconds = sum(float(legs[leg]["sidecar"]["elapsed_seconds"]) for leg in legs)
    flows = {
        "timing_three_phase": int(timing["three_phase"]["solves"]),
        "timing_balanced": int(timing["balanced"]["solves"]),
        "smoke": smoke_solves,
        "tests": 0,
        "total": int(timing["three_phase"]["solves"]) + int(timing["balanced"]["solves"])
                 + smoke_solves,  # fmt: skip
        "budget": "at most about 4,200 power flows (issue AKK-45)",
        "note": "192 + 192 + 3,840 = 4,224; the stated 4,200 is the issue's rounded figure "
                "and the three component counts it fixes sum to 4,224.",
    }
    payload = {
        "task": "Calibrated-detection pilot steps 2-4: the IEEE European LV feeder",
        "status": STATUS,
        "key": key,
        "scenario": SCENARIO,
        "judgement_calls": JUDGEMENT_CALLS,
        "flows": flows,
        "topology": {k: v for k, v in topo.items() if k != "sections"},
        "sections": topo["sections"],
        "selection_rules": SELECTION_RULES,
        "timing": timing,
        "timing_artefact": _reported(Path(timing_file)),
        "smoke": {
            "legs": {leg: legs[leg]["record"] for leg in legs},
            "sidecars": {leg: legs[leg]["sidecar_record"] for leg in legs},
            "solves": smoke_solves,
            "elapsed_seconds": smoke_seconds,
            "per_solve_seconds": smoke_seconds / smoke_solves,
            "failed_flows": sum(int(legs[leg]["sidecar"]["failed_flows"]) for leg in legs),
            "days": [int(d) for d in nominal["day_index"]],
            "daylight_steps_per_day": [int(v) for v in daylight.sum(axis=1)],
            "night_steps_per_day": [int(v) for v in (~daylight).sum(axis=1)],
        },
        "reduction": per_leg,
        "cost": cost_extrapolation(
            smoke_seconds / smoke_solves,
            timing["balanced"]["total_seconds"] / timing["balanced"]["solves"],
            timing["three_phase"]["total_seconds"] / timing["three_phase"]["solves"]),  # fmt: skip
        "limitations": [
            "The profiles are SimBench, so only the topology is independent (SCENARIO."
            "independence). No size, coverage or power claim is made.",
            "Four legs on one feeder, 10 days, noise-free Delta. The C1-style ratio is "
            "ILLUSTRATIVE (J10).",
            "The customer set is the 55 asymmetric_loads, not a pre-committed meter "
            "placement; no placement rule is applied.",
            "Phase 9's registered failures R3, R5 and R7 are unchanged by this pilot.",
        ],
        "provenance": {
            "pandapower": _package_version("pandapower"),
            "numba_installed": _numba_installed(),
            "line_table_sha256": line_table_sha256(net),
            "script": _reported(Path(__file__)),
            "phase9_sweep": _reported(PHASE9 / "phase9_sweep.py"),
            "q1_voltage_residual": _reported(PHASE9 / "q1_voltage_residual.py"),
            "platform": timing["platform"],
        },
        "disk_bytes": {
            "eulv": int(sum(p.stat().st_size for p in EULV.glob("*") if p.is_file())),
            "timing": int(Path(timing_file).stat().st_size),
        },
    }
    record = write_json_once(Path(output), payload)
    payload["_path"], payload["_sha256"] = record["path"], record["sha256"]
    return payload


def _reported(path: Path) -> dict:
    path = Path(path)
    data = path.read_bytes()
    try:
        reported = str(path.relative_to(REPO))
    except ValueError:  # a path outside the repository (only in tests, under tmp_path)
        reported = str(path)
    return {"path": reported, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


# --- the command line ----------------------------------------------------------------------


def print_topology(topo: dict) -> None:
    facts, summary = topo["facts"], topo["section_summary"]
    print("== step 2: the IEEE European LV feeder (zero flows) ==")
    print(f"  buses {facts['buses']} {facts['buses_by_vn_kv']}  lines {facts['lines']}  "
          f"length {facts['total_length_km']:.3f} km  "
          f"median segment {facts['segment_length_m']['median']:.2f} m")  # fmt: skip
    print(f"  asymmetric_load {facts['asymmetric_loads']} {facts['customers_by_phase']}  "
          f"snapshot mean {facts['snapshot_load_kw']['mean']:.3f} kW  "
          f"sgen {facts['sgen']}  switches {facts['switches']}")  # fmt: skip
    print(f"  zero-sequence complete: {facts['zero_sequence_columns_complete']}")
    print(f"  trafo {facts['trafo']}  LV busbar {facts['lv_busbar']}  "
          f"boundary nodes {facts['boundary_nodes']}")  # fmt: skip
    print("  invariants: " + ("ALL OK" if topo["invariants"]["ok"] else "FAILURE"))
    for name, check in topo["invariants"]["checks"].items():
        print(f"    {name:<38}{'ok' if check['ok'] else 'FAIL'}")
    print(f"  sections {summary['count']} (candidates {summary['candidates']}, "
          f"busbar-incident {summary['incident_to_busbar']})")  # fmt: skip
    print(f"    segments per section min {summary['segments_per_section']['min']} "
          f"median {summary['segments_per_section']['median']} "
          f"mean {summary['segments_per_section']['mean']:.2f} "
          f"max {summary['segments_per_section']['max']}")  # fmt: skip
    length = summary["length_m"]
    print(f"    length m min {length['min']:.2f} median {length['median']:.2f} "
          f"mean {length['mean']:.2f} max {length['max']:.2f}")  # fmt: skip
    print(f"    with downstream customers {summary['with_downstream_customers']}, "
          f"with downstream PV {summary['with_downstream_pv']}")  # fmt: skip
    print("  selected sections (before any flow):")
    for leg, block in topo["selected_sections"].items():
        print(f"    ({leg}) section {block['section']:<4} segments {block['n_segments']:<3} "
              f"R {block['r_ohm']:.5f} ohm  R0 {block['r0_ohm']:.5f}  "
              f"depth {block['depth_segments']:<3} down buses "
              f"{block['n_downstream_buses']:<4} customers "
              f"{block['n_downstream_customers']:<3} PV {block['downstream_pv_kwp']:g} kWp  "
              f"pool {block['pool_size']}")  # fmt: skip


def print_report(payload: dict) -> None:
    print("\n== step 3: the timing probe ==")
    for name in ("three_phase", "balanced"):
        block = payload["timing"][name]
        print(f"  {name:<12}solves {block['solves']:<5}mean {block['mean_ms']:7.2f} ms  "
              f"median {block['median_ms']:7.2f}  max {block['max_ms']:8.2f}  "
              f"failed {block['failed_flows']}")  # fmt: skip
    print(f"  peak RSS {payload['timing']['peak_rss_mb']:.1f} MB  "
          f"numba installed {payload['timing']['numba_installed']}")  # fmt: skip

    smoke = payload["smoke"]
    print("\n== step 4: the smoke run ==")
    print(f"  {smoke['solves']} solves in {smoke['elapsed_seconds']:.1f} s "
          f"({smoke['per_solve_seconds'] * 1000.0:.2f} ms/solve), "
          f"failed {smoke['failed_flows']}")  # fmt: skip
    print(f"  days {smoke['days']}  daylight/day {smoke['daylight_steps_per_day']}")
    for leg, block in payload["reduction"].items():
        k, kr = block["k_pu"], block["k_ref_pu"]
        print(f"  ({leg}) section {block['selection']['section']} "
              f"down customers {block['n_downstream_customers']}")  # fmt: skip
        for name, record in (("|k|", k), ("|k_ref|", kr)):
            down = record["downstream"]["max"]
            off = record["off_downstream"]["max"]
            print(f"      max {name:<8}downstream {_pu(down)}  off-downstream {_pu(off)}")
        split = block["night_sign_split"]
        print(f"      night-sign opposite share downstream "
              f"{_share(split['downstream'])}  off-downstream "
              f"{_share(split['off_downstream'])}")  # fmt: skip
        c1 = block["illustrative_c1"]
        print(f"      ILLUSTRATIVE C1 ratio |k_ref|/floor ({c1['floor_pu']:.3e} p.u.): "
              f"max downstream {_num(c1['ratio']['downstream']['max'])}, "
              f"off-downstream {_num(c1['ratio']['off_downstream']['max'])}, "
              f">=1 downstream {c1['customers_over_one']['downstream']}/"
              f"{block['n_downstream_customers']}")  # fmt: skip

    cost = payload["cost"]
    print("\n== cost extrapolation ==")
    print(f"  main study {cost['main_study']['solves']:,} solves: "
          f"three-phase {cost['main_study']['cpu_hours_three_phase']:.1f} CPU-hours, "
          f"balanced {cost['main_study']['cpu_hours_balanced']:.1f}")  # fmt: skip
    print(f"  K1 (> {K1_CPU_HOURS:g} CPU-hours): {cost['K1']['verdict']}")
    print(f"\n  flows {payload['flows']}")
    print(f"  disk {payload['disk_bytes']}")


def _pu(value) -> str:
    return "n/a" if value is None else f"{value:.3e}"


def _num(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _share(record: dict) -> str:
    if record["share"] is None:
        return "n/a"
    return f"{record['opposite_sign']}/{record['customers']} = {record['share']:.2f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("command", choices=("topology", "timing", "smoke", "report"))
    parser.add_argument("--leg", choices=("nominal", "a", "b", "c"), default=None)
    parser.add_argument("--out", default=str(OUTPUT))
    args = parser.parse_args(argv)

    if args.command == "topology":
        print_topology(topology())
        return 0
    if args.command == "timing":
        started = time.perf_counter()
        payload = timing_probe()
        record = write_json_once(TIMING_FILE, payload)
        print(f"wrote {record['path']} sha256={record['sha256']}")
        for name in ("three_phase", "balanced"):
            block = payload[name]
            print(f"  {name:<12}solves {block['solves']:<5}"
                  f"mean {block['mean_ms']:7.2f} ms  median {block['median_ms']:7.2f}  "
                  f"max {block['max_ms']:8.2f}  failed {block['failed_flows']}")  # fmt: skip
        print(f"  peak RSS {payload['peak_rss_mb']:.1f} MB  flows {payload['flows']}  "
              f"elapsed {time.perf_counter() - started:.1f}s")  # fmt: skip
        return 0
    if args.command == "smoke":
        if args.leg is None:
            parser.error("`smoke` needs --leg")
        result = run_smoke(args.leg)
        sidecar = result["spec"]
        for name in ("npz", "sidecar"):
            print(f"wrote {result[name]['path']} sha256={result[name]['sha256']} "
                  f"bytes={result[name]['bytes']}")  # fmt: skip
        segments = len(sidecar["error"]["segments"]) if sidecar["error"] else 0
        print(f"  leg {sidecar['leg']}  segments {segments}"
              f"  solves {sidecar['solves']}  failed {sidecar['failed_flows']}  "
              f"{sidecar['per_solve_seconds'] * 1000.0:.2f} ms/solve  "
              f"elapsed {sidecar['elapsed_seconds']:.1f}s  "
              f"peak RSS {sidecar['peak_rss_bytes'] / 1e6:.1f} MB")  # fmt: skip
        return 0
    payload = report(Path(args.out))
    print(f"wrote {payload['_path']} sha256={payload['_sha256']}")
    print_topology(payload["topology"] | {"sections": payload["sections"]})
    print_report(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
