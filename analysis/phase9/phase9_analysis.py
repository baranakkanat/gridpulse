"""Phase 9 analysis core: Stages 0, 1, 3 and 4 of the registration
`docs/provenance/phase9/phase9_registration.md` (sha256
737a252dab231b9c5303d4b5e8ad1af0adb93051f0de621d41a38f82af5bc4e1).

This module owns the *zero-flow* side of Phase 9: the integrity stage (s. 12 Stage 0 and
Stage 4), the input and threshold stage (s. 3, s. 7, s. 8, s. 9 and W3), the statistics
stage (s. 8, s. 9, W1, W2, W5, W8, W9) and the s. 10 controls (controls 1-5 and the A*
amplitude sweep, with their noise simulator). The power-flow side -- the s. 6 engine, the
s. 7 driver and the Stage G gate -- stays in `phase9_sweep.py`, which is imported and reused
here for the reduction, the keys, the artefact reading and the registration-commit check.

The s. 10 controls are simulated analytically on the per-day means the s. 7 artefacts already
store (s. 16), so they run at zero extra power flow. Control 3 is the one exception: it
permutes per-step labels and therefore reads the caches, at the registered and the four
held-out cables only (s. 10).

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9/phase9_analysis.py stage0
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9/phase9_analysis.py stage1
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9/phase9_analysis.py stage3
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9/phase9_analysis.py stage4
    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9/phase9_analysis.py \
        controls-selftest

Stage 3 also runs in parts, because a single sandbox command stops at 9 minutes while the
s. 10 controls take longer than that together. This is execution mechanics only: a part calls
the same block the monolithic `stage3` calls, at the same replicate counts, and the s. 10 seed
is per (network, condition, control, index), so a control's numbers do not depend on what else
ran in the same process.

    ... phase9_analysis.py stage3 --part core
    ... phase9_analysis.py stage3 --part control1      --network <code>
    ... phase9_analysis.py stage3 --part control2_fa   --network <code> --sigma <0.005|0.01>
    ... phase9_analysis.py stage3 --part control2_cov  --network <code> --sigma <0.005|0.01>
    ... phase9_analysis.py stage3 --part control3      --network <code>
    ... phase9_analysis.py stage3 --part control45
    ... phase9_analysis.py stage3 --part merge
    ... phase9_analysis.py stage3-benchmark

Each part writes `results/stage3_parts/<part>[-<network>][-<sigma>].json`, atomically and
refusing to overwrite, after every refusal check the monolithic `stage3` performs; `merge`
requires every part, one Stage 1 inputs hash and one sweep `physics_key`, and writes the
registered `results/phase9_results.json`. `stage3-benchmark` projects each part's wall time
from synthetic runs at the real shapes and touches no real data.

Nothing runs at import, nothing outside `analysis/phase9/` is written and `src/gridpulse/`,
`outputs/`, `data/` and the Q1 files are read-only.

There is no `--allow-uncommitted` flag and there never may be: s. 12 Stage 0 requires the
registration to be tracked, committed and unmodified before Stages 1-3, so Stages 1 and 3
refuse while it is uncommitted. Stage 0 itself reports the state and does not refuse, because
it is the check.

Readings of the registration, each recorded in the output
---------------------------------------------------------
R-a (s. 3). "the set of buses whose busbar path (`nx.shortest_path` on a plain `nx.Graph`)
    traverses line l": a plain `nx.Graph` cannot distinguish two lines on the same bus pair,
    so the cross-check graph stores the *set* of line indices of every bus pair and a path
    traverses line l iff l is in the set of one of its edges. Under the s. 3.1 invariants
    (acyclic line graph, `parallel == 1`) every pair carries exactly one line and the two
    readings coincide; the set form only keeps the cross-check honest on a graph that
    violates them.
R-b (s. 8). "A retained day on which a run has no valid daylight step, or no valid night
    step, is dropped from that run's average and counted." The sentence is read as one day
    set per run: a retained day is usable iff it has at least one valid daylight *and* one
    valid night step, and m, night and k all average over the usable days. This keeps
    s. 7's "thresholds and statistics use the same retained days" true of all three
    statistics at once.
R-c (s. 7, s. 11.4). "Any statistic below 1e-6 p.u. is reported as at the cache precision
    floor". The label is attached to any statistic with |value| < 1e-6, and it is a label:
    the number is still reported.
R-d (s. 9). R1-R4 and R3s are evaluated on the registered estimator (the mean over days).
    The median over days is the s. 8 robustness check; it is reported per bus and in the
    coverage tables, and it does not carry a rule verdict.
R-e (s. 8). The Q9a headline coverage is the `mean` estimator; the same table is repeated
    for `median_averaging_floors` as the s. 8 robustness check.
R-f (s. 9, W8). "The linearity of |k| in (f - 1): the slope ratio across f" is reported as
    slope(f) = max over downstream(l) of |k| divided by (f - 1), and the ratio of every
    slope to the slope at the W6 factor f = 1.5.
R-g (s. 9, W9). "the R-only prediction" for E-L(g) is the resistance increment ratio
    (g - 1) / (R_FACTOR - 1) = (g - 1) / 0.5, since E-L(g) scales R by g while E-R(1.5)
    scales it by 1.5.
R-h (s. 12 Stage 0). s. 12 lists five file hashes plus the 27 `freeze.json` code entries.
    Two of the five and the code entries are exactly Q1's `hash_checks()`, which is reused
    unmodified; the other three (the frozen placements and Q1's two committed result files)
    are checked here, against the hashes written in s. 12.
R-i (s. 10). The seed is fixed as
    `SeedSequence([20261023, sn._stable_int(network), sn._stable_int(condition),
    sn._stable_int(control), index])`, but the registration does not fix the `control`
    strings. They are `control_1`, `control_1_sqrt2`, `control_2_fa`, `control_2_cov` and
    `control_3`, so the mandatory sqrt(2) variant is a separate stream from the measured-leg
    variant. Control 3 has no noise condition, so its `condition` string is `none`.
R-j (s. 10). The simulator's day axis is the *usable* retained days of reading R-b --
    intersected over the network's W6 artefacts, so one measurement realisation can be
    applied to every cable -- with "the 1-day delay removes the last retained day" applied as
    the removal of the last retained day of s. 7. A meter that loses every day of a replicate
    has no reading: its k-hat is NaN and it raises no alarm.
R-k (s. 10). The crossing records are typed. "interpolated" is the s. 10 rule, linear in the
    rate between the bracketing grid points on log A. "<= 0.003 sigma" is reported when the
    crossing is not bracketed at the bottom, that is when the condition already holds at
    A = 0 or at the first positive grid point, because log A = -inf is not interpolable.
    "> 0.3 sigma" is reported when the condition holds at no grid point; that is s. 10's
    "not reached" case, and the record carries `not_reached: true`.
    A*_fa must be read against its own A = 0 rate: the A = 0 grid point is the floor's own
    family-wise false-alarm rate under that condition, K and sigma_tot, with no diurnal bias
    at all, so it is emitted next to every A*_fa record. A crossing recorded at or below the
    first positive grid point ("<= 0.003 sigma") is therefore a baseline artefact of that
    A = 0 rate -- the floor already alarms above 0.05 before any bias is added -- and not a
    measured tolerance of the method to diurnal bias.
R-l (s. 10). One replicate is one measurement realisation of the meters, shared by every
    rule x K of that replicate and, in A*_cov, by every (cable, rule) pair: the noise is a
    property of the meters and the s. 10 seeds carry neither a rule nor a cable index. The
    intervals therefore stay descriptive, exactly as s. 8 already says of pairs.
R-m (s. 10). The mandatory sqrt(2) variant draws a second, independent leg for the per-day
    noise *and* for the static bias, so the contrast carries 2 sigma_v^2 / n and the level
    2 sigma_bias^2. The bias still cancels in k, which is the point of the contrast.
R-n (s. 8, s. 10). The threshold sigma_tot of `biased_meters_matched` is the registered 0.01
    of s. 8 -- its total uncertainty, by the amendment 6A that defines it -- not
    sqrt(0.002^2 + 0.0098^2) = 0.0100020.
R-o (s. 10). The per-day step counts of the simulator are the *valid* counts
    (`n_daylight_valid`, `n_night_valid`) of the network's registered-cable artefact, because
    s. 10 fixes the variance as sigma_v^2 / n_daylight_valid. The issue admits either Stage 1
    or the artefacts; the artefacts carry validity, Stage 1 only the step counts.
R-p (s. 10). Control 3 permutes the labels over all 96 steps of the day with the daylight
    *count* preserved, as s. 10 says. Validity is then re-intersected with the permuted
    labels, and a day left without a valid daylight or a valid night step drops from that
    permutation's average (reading R-b again), counted per permutation.
R-q (s. 10). The sinusoid's per-day daylight mean is taken over all `n_daylight_steps` of the
    day, in the step order within that day, because only per-day means are stored. On a day
    with an invalid daylight step this is an approximation; it is flagged per network and the
    flag is reported.
R-r (s. 9 R7). The R7 verdict is taken on the family-wise rate against z_K * F_C,real under
    the measured-leg-only variant, over every condition x rule x K: it holds iff every such
    Wilson 95 % lower bound is at most 0.05. The z_K * F_C,matched arm of
    `biased_meters_matched` and the sqrt(2) variant are reported as diagnostics and carry no
    verdict.
R-s (s. 12.5, W1). "W1: R1/R3s/R4 at the registered cables, from Q1's committed per-bus
    arrays, checked against the sweep artefacts" is read as *both* evaluations, reported side
    by side. R1, R3s and R4 are evaluated at the registered cable twice -- once on Q1's
    committed per-bus arrays of `results/q1_results.json` and once on the sweep artefact's --
    at both co-primary sigma_tot and z_{K_all}, together with the maximum absolute difference
    between the two sets of arrays. The sweep arrays are the registered estimator everywhere
    else in Stage 3, so they stay the verdict of record; the Q1-sourced verdict is W1's
    fidelity check of them. A disagreement is reported as a disagreement, not reconciled.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import phase9_sweep as ps
import q1_voltage_residual as q1
from q1_voltage_residual import _plain as plain
from q1_voltage_residual import json_text, write_new_json

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = HERE / "results"
INPUTS_FILE = RESULTS / "phase9_inputs.json"
RESULTS_FILE = RESULTS / "phase9_results.json"
STAGE3_PARTS = RESULTS / "stage3_parts"  # `stage3 --part` writes here (one file per part)
Q1_RESULTS = RESULTS / "q1_results.json"
Q1_INPUTS = RESULTS / "registration_inputs.json"

REGISTRATION = ps.REGISTRATION
REGISTRATION_SHA256 = ps.REGISTRATION_SHA256

# --- registered constants ------------------------------------------------------------------

SWEEP_NETWORKS = ps.NETWORKS  # s. 2
HELD_OUT_NETWORKS = (  # s. 2; loaded by Stage 3 (W5) only, never by Stage 1's vm-free work
    "1-LV-rural1--2-sw",
    "1-LV-rural2--2-sw",
    "1-LV-rural3--2-sw",
    "1-LV-semiurb5--2-sw",
)
ALL_NETWORKS = SWEEP_NETWORKS + HELD_OUT_NETWORKS

SIGMA_GRID = (0.003, 0.005, 0.01, 0.02)  # s. 8
SIGMA_CO_PRIMARY = (0.01, 0.005)  # s. 8, sub-decision (ii)
K_GRID = (1, 2, 4)  # s. 8 meter configurations
ESTIMATORS = ("mean", "median_averaging_floors")  # s. 8
NAMED_RULES = ("mandatory", "topology", "risk", "greedy_detect", "decision_aware")  # s. 8
RANDOM_RULES = tuple(f"random_{i}" for i in range(20))
EXPECTED_RULES = len(NAMED_RULES) + len(RANDOM_RULES)  # 25
RULE_FAMILIES = {"all": None, "named": NAMED_RULES, "random": RANDOM_RULES}

REMOTE_MISSING = q1.REMOTE_MISSING  # s. 7: D_eff = 0.95 * D_ret
NOMINAL_KV = q1.NOMINAL_KV  # s. 3 / s. 9: V = 0.4 kV
R_FACTOR = q1.R_FACTOR  # 1.5, the W6 resistance factor
PRECISION_FLOOR_PU = 1e-6  # s. 7
SENSITIVITY_MIN_DAYLIGHT = 8  # s. 7 sensitivity retention
STEPS = ps.STEPS

R1_SHARE = 0.90  # s. 9
R2_JACCARD = 0.8  # s. 9
R3_SPEARMAN = 0.9  # s. 9
R4_CV = 0.2  # s. 9
R5_RATIO = (0.50, 0.90)  # s. 9
R3S_MIN_BUSES = 3  # s. 9, G2 typed record below this

FAILED_TOTAL_FRACTION = 0.001  # s. 7: 0.1 % of all sweep solves
FAILED_RUN_FRACTION = 0.01  # s. 7: 1 % of any single run's solves on retained days

W8_FACTORS = (1.1, 1.25, 1.5, 2.0)  # s. 9 f* search set; 1.5 is the W6 artefact
W9_FACTORS = ps.W9_L_FACTORS  # (1.25, 1.5)

# s. 12 Stage 0, the three hashes Q1's `hash_checks()` does not cover (reading R-h)
PHASE9_HASHES = {
    "outputs/noise_study/development_results.json": (
        "8c587b16d1898e133f63ebcbc55c63e1efc828233a3bbf3c1a067a57f1923dbd"
    ),
    "analysis/phase9/results/registration_inputs.json": (
        "0374cd09355dd513da11aee2e9cffa72ae14ea34f8d5fe24f998cf91a9006810"
    ),
    "analysis/phase9/results/q1_results.json": (
        "b24fe4523e87bcdcf20f7b8972697d17584754bbeaf1e7e89cad70710f535a9f"
    ),
}

# s. 3's registered counts, recorded so a mismatch is reported as a mismatch
REGISTERED_CANDIDATES = ps.REGISTERED_CANDIDATES
REGISTERED_CABLE = ps.REGISTERED_CABLE
REGISTERED_DOWNSTREAM = {code: set(v) for code, v in ps.REGISTERED_DOWNSTREAM.items()}
REGISTERED_RETAINED = ps.REGISTERED_RETAINED

# W2 hits out of the 25 rules at K = 1, 2, 4. These counts come from the Phase 9
# *implementation issue*, not from the registration: `docs/provenance/phase9/
# phase9_registration.md` fixes no W2 hit count anywhere, so this is an issue-sourced
# expectation and carries no registered status. A mismatch is reported as a mismatch and
# changes no registered quantity. The name is kept for continuity; `W2_EXPECTATION_SOURCE`
# is what the results file reports.
W2_REGISTERED_HITS = {
    "1-LV-semiurb4--2-sw": {1: 3, 2: 5, 4: 5},
    "1-LV-urban6--2-sw": {1: 5, 2: 10, 4: 15},
}
W2_EXPECTATION_SOURCE = (
    "the Phase 9 implementation issue's expected W2 hit counts: an issue-sourced expectation, "
    "not a registered quantity -- the registration fixes no W2 hit count"
)

# s. 9, "Stated before any new number (HYPOTHESES)", transcribed verbatim
HYPOTHESES = {
    "R1_R2": (
        "R1/R2 can fail only at cables whose downstream flow does not reverse between day "
        "and night (little downstream PV). Such cables, if any, will be listed."
    ),
    "W8": (
        "W8: band C survives down to f = 1.1 at sigma_tot = 0.01, at a meter on downstream(l) "
        "with K = 2 (extrapolated linearly from 3.4-5.6x headroom)."
    ),
    "W9": (
        "W9: the downstream / off-downstream sign split is unchanged, while the ratio of |k| "
        "to E-R(1.5) differs from the R-only prediction by more than 10 %."
    ),
    "A_star": "A*_fa is about the band-C boundary, ~ 3.5e-4 p.u. ~ 0.035 * sigma_tot.",
    "rule": "Any contradiction is reported as a contradiction, not reconciled.",
}

Z_95 = 1.959963984540054  # Phi^-1(0.975), the descriptive Wilson interval of s. 8


# --- small pure helpers --------------------------------------------------------------------


def write_new_json_atomic(path: Path, payload) -> str:
    """Write `payload` atomically, refusing to overwrite; return the file's sha256.

    Q1's `write_new_json` is exclusive but writes in place, so an interrupted write leaves a
    truncated file. Stage 3's parts are written by separate commands, so each one lands whole
    or not at all: the text goes to a temporary file in the same directory and is published
    with `os.link`, which is atomic and fails if the destination already exists.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json_text(payload)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with open(temporary, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise RuntimeError(f"refusing to overwrite {path}") from error
    finally:
        if temporary.exists():
            temporary.unlink()
    return q1.sha256_text(text)


def at_precision_floor(value: float) -> bool:
    """s. 7 (reading R-c): any statistic with |value| < 1e-6 p.u. carries the floor label."""
    value = float(value)
    return math.isfinite(value) and abs(value) < PRECISION_FLOOR_PU


def floor_label(value: float) -> dict:
    """One statistic with its precision-floor label."""
    return {
        "value": float(value),
        "at_cache_precision_floor": at_precision_floor(value),
    }


def wilson(successes: int, trials: int, z: float = Z_95) -> dict:
    """The Wilson score interval, labelled descriptive (s. 8: pairs share days and topology)."""
    successes, trials = int(successes), int(trials)
    if successes < 0 or trials < 0 or successes > trials:
        raise ValueError(f"{successes} successes of {trials} trials is not a proportion")
    if trials == 0:
        return {"successes": 0, "trials": 0, "rate": None, "low": None, "high": None,
                "interval": "undefined, n = 0", "z": z,
                "label": "descriptive (s. 8)"}  # fmt: skip
    rate = successes / trials
    denominator = 1.0 + z * z / trials
    centre = (rate + z * z / (2.0 * trials)) / denominator
    half = (z / denominator) * math.sqrt(rate * (1.0 - rate) / trials + z * z / (4.0 * trials**2))
    return {
        "successes": successes,
        "trials": trials,
        "rate": rate,
        "low": max(0.0, centre - half),
        "high": min(1.0, centre + half),
        "z": z,
        "label": "descriptive (s. 8): pairs share days, profiles and topology",
    }


def jaccard(left, right) -> float:
    """|A n B| / |A u B|, NaN when both sets are empty (the s. 9 empty-set case)."""
    left, right = set(left), set(right)
    union = left | right
    if not union:
        return float("nan")
    return len(left & right) / len(union)


def opposite_sign(a: float, b: float) -> bool:
    """`sign(b) = -sign(a)` of s. 9 R1. A zero on either side is not an opposite sign."""
    sa, sb = np.sign(float(a)), np.sign(float(b))
    return bool(sa != 0 and sb != 0 and sb == -sa)


def population_cv(values) -> float:
    """CV = population sd / mean of s. 9 R4. NaN when the mean is zero or n = 0."""
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return float("nan")
    mean = float(values.mean())
    if mean == 0.0:
        return float("nan")
    return float(values.std(ddof=0) / mean)


def coverage_table(pairs) -> dict:
    """s. 8 coverage over (cable, rule) pairs.

    `pairs` is a sequence of `(band, intersects)` with `band` in {"A", "B", "C"} and
    `intersects` the W3 fact "the configuration intersects downstream(l)".
    """
    pairs = [(str(b), bool(i)) for b, i in pairs]
    detected = [p for p in pairs if p[0] == "C"]
    crossing = [p for p in pairs if p[1]]
    not_crossing = [p for p in pairs if not p[1]]
    return {
        "pairs": len(pairs),
        "band_counts": {b: sum(1 for p in pairs if p[0] == b) for b in ("A", "B", "C")},
        "coverage": wilson(len(detected), len(pairs)),
        "coverage_given_intersects": wilson(sum(1 for p in crossing if p[0] == "C"),
                                            len(crossing)),  # fmt: skip
        "coverage_given_not_intersects": wilson(sum(1 for p in not_crossing if p[0] == "C"),
                                                len(not_crossing)),  # fmt: skip
        "intersection_coverage": wilson(len(crossing), len(pairs)),
        "note": (
            "intersection coverage is the W3 topological ceiling against which coverage is "
            "read (s. 8, s. 14)"
        ),
    }


# --- s. 3: topology, on an `nx.MultiGraph` keyed by line index ------------------------------


def line_multigraph(net):
    """s. 3: an `nx.MultiGraph` whose edges are keyed by line index (G1).

    Every index of `net.line.index` is enumerated, so two lines on the same bus pair stay two
    edges. Tree edges are not used anywhere in this module.
    """
    import networkx as nx

    graph = nx.MultiGraph()
    for index, row in net.line.iterrows():
        graph.add_edge(int(row["from_bus"]), int(row["to_bus"]), key=int(index),
                       line=int(index))  # fmt: skip
    return graph


def downstream_multigraph(graph, busbar: int, line: int) -> set[int]:
    """s. 3: the buses disconnected from the LV busbar when line `line` is removed."""
    import networkx as nx

    busbar, line = int(busbar), int(line)
    if busbar not in graph:
        raise ValueError(f"the LV busbar {busbar} is not a node of the line graph")
    pair = [(u, v) for u, v, k in graph.edges(keys=True) if k == line]
    if not pair:
        raise ValueError(f"line {line} is not an edge of the line graph")
    cut = graph.copy()
    cut.remove_edge(pair[0][0], pair[0][1], key=line)
    reachable = nx.node_connected_component(cut, busbar)
    return {int(b) for b in cut.nodes if b not in reachable}


def _plain_graph(net):
    """The independent cross-check graph: a plain `nx.Graph` whose edges carry the *set* of
    line indices on that bus pair (reading R-a)."""
    import networkx as nx

    graph = nx.Graph()
    for index, row in net.line.iterrows():
        u, v = int(row["from_bus"]), int(row["to_bus"])
        if graph.has_edge(u, v):
            graph.edges[u, v]["lines"].add(int(index))
        else:
            graph.add_edge(u, v, lines={int(index)})
    return graph


def downstream_shortest_path(net, busbar: int, line: int) -> set[int]:
    """s. 3 invariant 2's second, independent derivation: the buses whose busbar path
    (`nx.shortest_path` on a plain `nx.Graph`) traverses line `line`."""
    import networkx as nx

    graph = _plain_graph(net)
    busbar, line = int(busbar), int(line)
    paths = nx.shortest_path(graph, source=busbar)
    out = set()
    for bus, path in paths.items():
        for u, v in zip(path, path[1:], strict=False):
            if line in graph.edges[u, v]["lines"]:
                out.add(int(bus))
                break
    return out


def downstream_sets(net, busbar: int, lines) -> dict[int, set[int]]:
    """Both derivations of s. 3 for every line in `lines`; a disagreement stops Stage 1."""
    graph = line_multigraph(net)
    out = {}
    for line in lines:
        line = int(line)
        primary = downstream_multigraph(graph, busbar, line)
        cross = downstream_shortest_path(net, busbar, line)
        if primary != cross:
            raise RuntimeError(
                f"line {line}: the MultiGraph downstream set {sorted(primary)} differs from the "
                f"independent shortest-path derivation {sorted(cross)}; registration s. 3 "
                "invariant 2 stops Stage 1 on any failure"
            )
        out[line] = primary
    return out


def structural_invariants(net, layout) -> dict:
    """s. 3 invariant 1, per network. Every clause is reported; `ok` is their conjunction."""
    import networkx as nx

    lv_buses = [int(b) for b in layout.buses]
    n_lines = int(len(net.line.index))
    graph = line_multigraph(net)
    nodes = set(graph.nodes)
    covers = nodes == set(lv_buses)
    connected = bool(nodes) and nx.is_connected(graph) if covers else False
    acyclic = covers and connected and n_lines == len(lv_buses) - 1
    parallel_ok = bool((net.line["parallel"].to_numpy() == 1).all())
    in_service_ok = bool(net.line["in_service"].to_numpy().all())

    switches = getattr(net, "switch", None)
    if switches is None or len(switches) == 0:
        line_switches, open_line_switches = 0, []
    else:
        mask = switches["et"].astype(str).to_numpy() == "l"
        line_switches = int(mask.sum())
        closed = switches.loc[mask, "closed"].to_numpy()
        open_line_switches = [
            int(i) for i, shut in zip(switches.index[mask], closed, strict=True) if not shut
        ]
    switches_ok = not open_line_switches

    clauses = {
        "lv_buses_equal_lines_plus_one": len(lv_buses) == n_lines + 1,
        "line_graph_covers_the_lv_buses": covers,
        "line_graph_connected": connected,
        "line_graph_acyclic": acyclic,
        "every_line_parallel_is_one": parallel_ok,
        "every_line_in_service": in_service_ok,
        "every_line_switch_closed": switches_ok,
    }
    return {
        **clauses,
        "lv_buses": len(lv_buses),
        "lines": n_lines,
        "line_switches": line_switches,
        "open_line_switches": open_line_switches,
        "ok": all(clauses.values()),
    }


def network_topology(code: str, full: bool) -> dict:
    """s. 3 for one network: the invariants, and either every candidate (`full`) or only the
    `stress.local_line` cable with its downstream set.

    No state file is opened and no flow is run, so Stage 1 stays vm-free (s. 12).
    """
    from gridpulse import dual_study as ds
    from gridpulse import grid, grid_study
    from gridpulse import sensing as sn
    from gridpulse import stress as st

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    layout = sn.network_layout(net)
    invariants = structural_invariants(net, layout)
    if not invariants["ok"]:
        raise RuntimeError(
            f"{code}: a s. 3 structural invariant failed: {invariants}; Stage 1 stops"
        )
    cable = int(st.local_line(net, layout))
    all_candidates = ps.candidates(net, layout)
    if full:
        registered = REGISTERED_CANDIDATES.get(code)
        if registered is not None and len(all_candidates) != registered:
            raise RuntimeError(
                f"{code}: {len(all_candidates)} candidate lines, registration s. 3 fixes "
                f"{registered}; Stage 1 stops"
            )
        lines = all_candidates
    else:
        lines = [cable]
    if cable not in all_candidates:
        raise RuntimeError(f"{code}: stress.local_line {cable} is not a candidate")

    sets = downstream_sets(net, layout.lv_busbar, lines)
    for line, below in sets.items():
        if not below:
            raise RuntimeError(f"{code}: downstream({line}) is empty; s. 3 invariant 2 stops "
                               "Stage 1")  # fmt: skip
        if layout.lv_busbar in below:
            raise RuntimeError(f"{code}: downstream({line}) contains the LV busbar "
                               f"{layout.lv_busbar}; s. 3 invariant 2 stops Stage 1")  # fmt: skip

    reproduces = None
    if code in REGISTERED_DOWNSTREAM:
        reproduces = {
            "stress_local_line": cable,
            "registered_line": REGISTERED_CABLE[code],
            "downstream": sorted(sets[cable]),
            "registered_downstream": sorted(REGISTERED_DOWNSTREAM[code]),
            "ok": cable == REGISTERED_CABLE[code]
            and sets[cable] == REGISTERED_DOWNSTREAM[code],
        }
        if not reproduces["ok"]:
            raise RuntimeError(
                f"{code}: the registered cable does not reproduce Q1: {reproduces}; s. 3 "
                "invariant 3 stops Stage 1"
            )

    available = grid_study.daily_arrays(grid.absolute_profiles(net))["sgen_p_mw"]
    return {
        "network": net,
        "layout": layout,
        "available": available,
        "invariants": invariants,
        "candidates": all_candidates,
        "lines": [int(x) for x in lines],
        "local_line": cable,
        "downstream": sets,
        "reproduces_q1": reproduces,
    }


# --- s. 7: retention, and s. 8's floors and thresholds -------------------------------------


def daylight_counts(available, days) -> np.ndarray:
    """s. 2: the number of daylight steps per scored day (`available[d].sum(axis=1) > 0`)."""
    return np.array([int((available[d].sum(axis=1) > 0).sum()) for d in days], dtype=int)


def retention(days, counts, steps: int = STEPS, min_daylight: int = 1) -> dict:
    """s. 7 day retention, network-level and identical for every error.

    A scored day is retained iff it has at least `min_daylight` daylight steps and at least
    one night step. A scored day with **zero** night steps is a hard error (s. 7), raised by
    `q1.partition_days`, whatever `min_daylight` is.
    """
    days = [int(d) for d in days]
    counts = [int(c) for c in counts]
    q1.partition_days(days, counts, steps)  # raises on a day with no night step
    retained, dropped = [], []
    for day, count in zip(days, counts, strict=True):
        (retained if count >= int(min_daylight) else dropped).append(day)
    if not retained:
        raise RuntimeError("no scored day is retained; s. 7 fixes no rule for that")
    kept = np.array([c for d, c in zip(days, counts, strict=True) if d in set(retained)])
    d_ret = len(retained)
    return {
        "min_daylight_steps": int(min_daylight),
        "scored_days": len(days),
        "retained": retained,
        "dropped": dropped,
        "D_ret": d_ret,
        "D_eff": (1.0 - REMOTE_MISSING) * d_ret,
        "n_day_median": float(np.median(kept)),
        "n_night_median": float(np.median(steps - kept)),
        "daylight_per_day_min": int(kept.min()),
        "daylight_per_day_max": int(kept.max()),
    }


def threshold_grid(days: dict, k_all: int) -> dict:
    """s. 8's thresholds at every registered sigma_tot, K and estimator, from one retention
    set. K_all is the network's LV bus count (s. 9)."""
    out = {}
    for estimator in ESTIMATORS:
        out[estimator] = {}
        for sigma in SIGMA_GRID:
            entry = {"sigma_tot": sigma, "co_primary": sigma in SIGMA_CO_PRIMARY,
                     "matched_arm_is_band_arithmetic_only": sigma == 0.005}  # fmt: skip
            for k in (*K_GRID, int(k_all)):
                entry[f"K_{k}"] = q1.thresholds(
                    sigma, days["n_day_median"], days["n_night_median"], days["D_eff"],
                    q1.z_bonferroni(k), estimator,
                )  # fmt: skip
            entry["K_all"] = int(k_all)
            out[estimator][f"{sigma:g}"] = entry
    return out


# --- s. 8: one run's per-bus statistics ----------------------------------------------------


def run_statistics(arrays, retained_days) -> dict:
    """s. 8's m, night and k per bus, as the mean and the median over the usable retained days
    of one run (reading R-b).

    `arrays` is an artefact's array mapping (`np.load` result or a dict); `retained_days` the
    network-level retained scored days of s. 7.
    """
    day_index = np.asarray(arrays["day_index"], dtype=int)
    daylight = np.asarray(arrays["dmean_daylight"], dtype=float)
    night = np.asarray(arrays["dmean_night"], dtype=float)
    n_day = np.asarray(arrays["n_daylight_valid"], dtype=int)
    n_night = np.asarray(arrays["n_night_valid"], dtype=int)
    wanted = set(int(d) for d in retained_days)
    retained = np.array([int(d) in wanted for d in day_index], dtype=bool)
    usable = retained & (n_day > 0) & (n_night > 0)
    usable &= np.isfinite(daylight).all(axis=1) & np.isfinite(night).all(axis=1)
    if not usable.any():
        raise RuntimeError("no retained day of this run has a valid daylight and night step")
    level, dark = daylight[usable], night[usable]
    contrast = level - dark
    return {
        "days_retained": int(retained.sum()),
        "days_used": int(usable.sum()),
        "days_dropped_no_valid_step": [int(d) for d in day_index[retained & ~usable]],
        "m": {"mean": level.mean(axis=0), "median": np.median(level, axis=0)},
        "night": {"mean": dark.mean(axis=0), "median": np.median(dark, axis=0)},
        "k": {"mean": contrast.mean(axis=0), "median": np.median(contrast, axis=0)},
        "failed_truth_retained": int(np.asarray(arrays["failed_truth"], dtype=int)[retained].sum()),
        "failed_truth_total": int(np.asarray(arrays["failed_truth"], dtype=int).sum()),
    }


def estimator_key(estimator: str) -> str:
    """The `run_statistics` key of one s. 8 estimator."""
    return "mean" if estimator == "mean" else "median"


# --- s. 9: the pre-registered rules, as pure functions -------------------------------------


def r1_network(cables, level_low: float) -> dict:
    """R1 (s. 9): over the network's W6 pairs (l, b) with |m| >= z * F_ind, the share with
    sign(night) = -sign(m) is at least 0.90.

    `cables` is a sequence of dicts with `line`, `m` and `night` per-bus arrays.
    """
    total = opposite = 0
    failing = []
    for cable in cables:
        m = np.asarray(cable["m"], dtype=float)
        night = np.asarray(cable["night"], dtype=float)
        selected = np.abs(m) >= float(level_low)
        hits = [opposite_sign(m[i], night[i]) for i in np.flatnonzero(selected)]
        total += len(hits)
        opposite += sum(hits)
        if hits and not all(hits):
            failing.append({"line": int(cable["line"]), "pairs": len(hits),
                            "same_or_zero_sign": int(len(hits) - sum(hits))})  # fmt: skip
    if total == 0:
        return {"rule": "R1", "pairs": 0, "opposite_sign": 0, "share": None,
                "threshold": R1_SHARE, "holds": None,
                "record": "undefined, n = 0 selected pairs (G2 typed record)",
                "failing_cables": failing}  # fmt: skip
    share = opposite / total
    return {
        "rule": "R1",
        "pairs": total,
        "opposite_sign": opposite,
        "share": share,
        "threshold": R1_SHARE,
        "holds": share >= R1_SHARE,
        "aggregation": "pooled share over the network's W6 pairs (s. 16)",
        "failing_cables": failing,
    }


def r2_cable(m, night, k, buses, downstream, level_low: float, contrast_high: float) -> dict:
    """R2 (s. 9) for one cable: S_detect subset of downstream(l), and Jaccard(S_detect, ref)
    at least 0.8. A cable is evaluable iff `ref` or `S_detect` is non-empty."""
    m = np.asarray(m, dtype=float)
    night = np.asarray(night, dtype=float)
    k = np.asarray(k, dtype=float)
    buses = [int(b) for b in buses]
    downstream = set(int(b) for b in downstream)
    s_detect = {
        buses[i]
        for i in range(len(buses))
        if abs(k[i]) >= float(contrast_high) and opposite_sign(m[i], night[i])
    }
    ref = {buses[i] for i in range(len(buses)) if abs(m[i]) >= float(level_low)} & downstream
    evaluable = bool(ref or s_detect)
    subset = s_detect <= downstream
    index = jaccard(s_detect, ref)
    holds = None
    if evaluable:
        holds = bool(subset and math.isfinite(index) and index >= R2_JACCARD)
    return {
        "S_detect": sorted(s_detect),
        "ref": sorted(ref),
        "downstream": sorted(downstream),
        "evaluable": evaluable,
        "subset_of_downstream": subset,
        "jaccard": index,
        "jaccard_threshold": R2_JACCARD,
        "holds": holds,
        "record": None if evaluable else "not evaluable: ref and S_detect are both empty",
    }


def r2_network(per_cable: dict) -> dict:
    """R2's network verdict: it holds iff it holds at every evaluable cable (s. 16)."""
    evaluable = {line: r for line, r in per_cable.items() if r["evaluable"]}
    failing = sorted(line for line, r in evaluable.items() if not r["holds"])
    return {
        "rule": "R2",
        "cables": len(per_cable),
        "evaluable_cables": len(evaluable),
        "failing_cables": failing,
        "holds": None if not evaluable else not failing,
        "aggregation": "every evaluable cable (s. 16)",
        "per_cable": per_cable,
    }


def r3_network(scores, max_downstream_k) -> dict:
    """R3 (s. 9, sub-decision iii): Spearman over the network's W6 cables of (S_l, max over
    downstream(l) of |k|), at least 0.9."""
    rho = q1.rank_correlation(scores, max_downstream_k)
    return {
        "rule": "R3",
        "cables": int(np.asarray(scores).size),
        "spearman": rho,
        "threshold": R3_SPEARMAN,
        "holds": None if not math.isfinite(rho) else bool(rho >= R3_SPEARMAN),
        "reading": "per-cable, the sub-decision (iii) disambiguation of Q1 s. 6",
    }


def r3s_cable(m, buses, downstream, distance) -> dict:
    """R3s (s. 9): per cable, Spearman(|m|, resistance distance) within downstream(l) for
    n >= 3, else a typed "undefined, n = ..." record (G2); plus whether the argmax over all
    buses of |m| lies in downstream(l)."""
    m = np.asarray(m, dtype=float)
    buses = [int(b) for b in buses]
    downstream = sorted(set(int(b) for b in downstream))
    columns = [buses.index(b) for b in downstream if b in buses]
    argmax_bus = buses[int(np.argmax(np.abs(m)))]
    out = {
        "n_downstream": len(columns),
        "argmax_bus": argmax_bus,
        "argmax_in_downstream": argmax_bus in set(downstream),
        "argmax_abs_m": float(np.abs(m).max()),
    }
    if len(columns) < R3S_MIN_BUSES:
        out["spearman"] = None
        out["record"] = f"undefined, n = {len(columns)} (G2 typed record)"
        return out
    out["spearman"] = q1.rank_correlation(
        np.abs(m[columns]), [float(distance[b]) for b in downstream if b in buses]
    )
    out["record"] = None
    return out


def r4_cable(k, buses, downstream, contrast_high: float) -> dict:
    """R4 (s. 9): CV of |k| over downstream(l) at most 0.2, for every W6 cable with
    |downstream(l)| >= 2 and max over downstream of |k| >= z * F_C,real."""
    k = np.asarray(k, dtype=float)
    buses = [int(b) for b in buses]
    downstream = sorted(set(int(b) for b in downstream))
    columns = [buses.index(b) for b in downstream if b in buses]
    magnitudes = np.abs(k[columns]) if columns else np.array([])
    peak = float(magnitudes.max()) if magnitudes.size else float("nan")
    evaluable = len(columns) >= 2 and math.isfinite(peak) and peak >= float(contrast_high)
    cv = population_cv(magnitudes) if columns else float("nan")
    return {
        "n_downstream": len(columns),
        "max_abs_k_downstream": peak,
        "cv": cv,
        "cv_threshold": R4_CV,
        "evaluable": evaluable,
        "holds": bool(math.isfinite(cv) and cv <= R4_CV) if evaluable else None,
    }


def r4_network(per_cable: dict) -> dict:
    """R4's network verdict: every evaluable cable must satisfy the CV bound (s. 16)."""
    evaluable = {line: r for line, r in per_cable.items() if r["evaluable"]}
    failing = sorted(line for line, r in evaluable.items() if not r["holds"])
    return {
        "rule": "R4",
        "cables": len(per_cable),
        "evaluable_cables": len(evaluable),
        "failing_cables": failing,
        "holds": None if not evaluable else not failing,
        "aggregation": "every evaluable cable (s. 16)",
        "per_cable": per_cable,
    }


def r5_ratio(m, buses, m_pred: float) -> dict:
    """R5 (s. 9), the pre-registered held-out statistic: ratio = m(b*) / m_pred with b* the
    argmax over all LV buses of |m| and m signed. It holds iff the ratio is in [0.50, 0.90]."""
    m = np.asarray(m, dtype=float)
    buses = [int(b) for b in buses]
    if m.shape != (len(buses),):
        raise ValueError(f"m is {m.shape} for {len(buses)} buses")
    column = int(np.argmax(np.abs(m)))
    signed = float(m[column])
    m_pred = float(m_pred)
    ratio = float("nan") if m_pred == 0.0 else signed / m_pred
    low, high = R5_RATIO
    return {
        "rule": "R5",
        "b_star": buses[column],
        "m_at_b_star_pu": signed,
        "m_at_b_star_at_cache_precision_floor": at_precision_floor(signed),
        "m_pred_pu": m_pred,
        "ratio": ratio,
        "interval": [low, high],
        "holds": bool(math.isfinite(ratio) and low <= ratio <= high),
        "note": "m is signed, so a sign flip against m_pred falls outside [0.50, 0.90]",
    }


# --- s. 8: the meter configurations and the s. 9 R6 identity -------------------------------


def placements(code: str) -> dict[str, list[int]]:
    """s. 8: the 25 frozen Phase 6 rules of `outputs/noise_study/development_results.json`."""
    data = json.loads((REPO / q1.PLACEMENTS).read_text())["placements"][code]
    rules = {name: [int(b) for b in buses] for name, buses in data.items()}
    if len(rules) != EXPECTED_RULES or set(NAMED_RULES) - set(rules):
        raise RuntimeError(
            f"{code}: {len(rules)} frozen placement rules {sorted(rules)}; s. 8 fixes "
            f"{EXPECTED_RULES} (5 named plus random_0...random_19)"
        )
    missing = [r for r in RANDOM_RULES if r not in rules]
    if missing:
        raise RuntimeError(f"{code}: missing random placement rules {missing}")
    return rules


def configuration(rule_buses, k: int) -> list[int]:
    """s. 8: a configuration is the first K buses of a rule."""
    buses = [int(b) for b in rule_buses]
    if len(buses) < int(k):
        raise ValueError(f"a rule of {len(buses)} buses has no configuration of K = {k}")
    return buses[: int(k)]


def c_meter(k_values, buses, configuration_buses) -> float:
    """s. 8: C_meter(e, rule, K) = max over the configuration's buses of |k(e, b)|."""
    k_values = np.asarray(k_values, dtype=float)
    buses = [int(b) for b in buses]
    columns = [buses.index(int(b)) for b in configuration_buses]
    return float(np.abs(k_values[columns]).max())


# --- s. 12 Stage 0 and Stage 4 -------------------------------------------------------------


def phase9_hash_checks() -> dict:
    """The three s. 12 hashes Q1's `hash_checks()` does not cover (reading R-h)."""
    report, mismatches = {}, []
    for name, expected in PHASE9_HASHES.items():
        actual = q1.sha256_file(REPO / name)
        report[name] = {"expected": expected, "actual": actual, "ok": actual == expected}
        if actual != expected:
            mismatches.append(name)
    return {"files": report, "mismatches": mismatches, "passed": not mismatches}


def stage0(git=ps._git, label: str = "0") -> dict:
    """s. 12 Stage 0 (and Stage 4, which repeats it): every listed hash, the 27 `freeze.json`
    code entries with Q1's log exception, and the registration-commit check.

    Stage 0 reports the commit state; it does not refuse on it. Stages 1-3 do, through
    `require_committed_registration`.
    """
    q1_report = q1.hash_checks()
    extra = phase9_hash_checks()
    state = ps.registration_state(git)
    on_disk = q1.sha256_file(REPO / REGISTRATION)
    registration_ok = on_disk == REGISTRATION_SHA256
    if not extra["passed"]:
        raise RuntimeError(f"Stage {label}: hash mismatches {extra['mismatches']}")
    if not registration_ok:
        raise RuntimeError(
            f"Stage {label}: {REGISTRATION} sha256 {on_disk} differs from the registered "
            f"{REGISTRATION_SHA256}; stopping"
        )
    return {
        "stage": f"{label} (registration s. 12)",
        "registration": {
            "path": REGISTRATION,
            "sha256_on_disk": on_disk,
            "expected_sha256": REGISTRATION_SHA256,
            "sha256_ok": registration_ok,
            "state": state,
            "stages_1_to_3_allowed": state["ok"],
            "note": (
                "s. 12 Stage 0 requires this file to be tracked, committed and unmodified "
                "before Stages 1-3. There is no --allow-uncommitted flag; the commit is the "
                "owner's."
            ),
        },
        "q1_hash_checks": q1_report,
        "phase9_hash_checks": extra,
        "passed": q1_report["passed"] and extra["passed"] and registration_ok,
    }


def require_committed_registration(git=ps._git) -> dict:
    """Stages 1-3 refuse while the registration is uncommitted or modified (s. 12 Stage 0)."""
    state = ps.registration_state(git)
    on_disk = q1.sha256_file(REPO / REGISTRATION)
    if on_disk != REGISTRATION_SHA256:
        raise RuntimeError(
            f"{REGISTRATION}: sha256 {on_disk} differs from the registered "
            f"{REGISTRATION_SHA256}; stopping"
        )
    if not state["ok"]:
        raise RuntimeError(
            "refusing to run: " + "; ".join(state["reasons"]) + ". Registration s. 12 Stage 0 "
            "requires the registration to be committed and unmodified before Stages 1-3. "
            "There is no --allow-uncommitted flag; the commit is the owner's."
        )
    return state


# --- Stage 1 (s. 3, s. 7, s. 8, s. 9, W3) --------------------------------------------------


def cable_facts(topology: dict, line: int, days, retained) -> dict:
    """s. 3 cable facts and the W3 map for one cable: R_l, X_l, installed downstream PV, P_l,
    S_l = R_l * P_l and m_pred(l) = 0.5 * R_l * P_l / V^2."""
    net = topology["network"]
    available = topology["available"]
    below = sorted(topology["downstream"][int(line)])
    r_per_km = float(net.line.at[int(line), "r_ohm_per_km"])
    x_per_km = float(net.line.at[int(line), "x_ohm_per_km"])
    length = float(net.line.at[int(line), "length_km"])
    resistance, reactance = r_per_km * length, x_per_km * length

    sgen_bus = net.sgen["bus"].to_numpy(dtype=int)
    sgen_mva = net.sgen["sn_mva"].to_numpy(dtype=float)
    mask = np.isin(sgen_bus, below)
    installed = float(sgen_mva[mask].sum())
    if mask.any():
        # P_l: the mean over the daylight steps of the retained days of the summed
        # availability of the generators on downstream(l), in MW (the Q1 definition, s. 3)
        rows = [available[d][available[d].sum(axis=1) > 0][:, mask] for d in retained]
        stacked = np.concatenate(rows) if rows else np.zeros((0, int(mask.sum())))
        p_mw = float(stacked.sum(axis=1).mean()) if stacked.size else 0.0
    else:
        p_mw = 0.0
    score = resistance * p_mw
    return {
        "line": int(line),
        "from_bus": int(net.line.at[int(line), "from_bus"]),
        "to_bus": int(net.line.at[int(line), "to_bus"]),
        "r_ohm_per_km": r_per_km,
        "x_ohm_per_km": x_per_km,
        "length_km": length,
        "R_ohm": resistance,
        "X_ohm": reactance,
        "max_i_ka": float(net.line.at[int(line), "max_i_ka"]),
        "downstream_buses": below,
        "downstream_size": len(below),
        "installed_pv_sn_mva": installed,
        "P_l_mw": p_mw,
        "S_l": score,
        "m_pred_pu": 0.5 * resistance * p_mw / NOMINAL_KV**2,
        "m_pred_definition": "0.5 * R_l * P_l / V^2 with V = 0.4 kV (s. 3, s. 9 R5)",
        "is_local_line": int(line) == topology["local_line"],
        "scored_days_used_for_P_l": len(retained),
    }


def intersection_coverage(rules: dict, cable_downstream: dict) -> dict:
    """W3 (s. 8, zero-flow): per rule and K, the fraction of cables whose configuration
    intersects downstream(l), and the pooled fraction over all pairs."""
    per_rule, pooled = {}, {}
    for k in K_GRID:
        hits_total = 0
        per_rule[f"K_{k}"] = {}
        for name, buses in rules.items():
            config = set(configuration(buses, k))
            hits = sum(1 for below in cable_downstream.values() if config & set(below))
            per_rule[f"K_{k}"][name] = {
                "configuration": sorted(config),
                "cables": len(cable_downstream),
                "intersecting": hits,
                "fraction": hits / len(cable_downstream) if cable_downstream else None,
            }
            hits_total += hits
        pooled[f"K_{k}"] = wilson(hits_total, len(cable_downstream) * len(rules))
    return {"per_rule": per_rule, "pooled_over_pairs": pooled,
            "definition": "the W3 topological ceiling of s. 8"}  # fmt: skip


def stage1(inputs_path: Path = INPUTS_FILE, git=ps._git) -> dict:
    """Stage 1 (s. 12.3): topology, invariants, candidates, downstream sets, cable facts,
    S_l, m_pred, intersection coverage, retention and every threshold.

    No vm array is loaded and no flow is run. It refuses while the registration is
    uncommitted (s. 12 Stage 0).
    """
    registration = require_committed_registration(git)
    days = ps.scored_days()
    networks = {}
    for code in ALL_NETWORKS:
        full = code in SWEEP_NETWORKS
        topology = network_topology(code, full=full)
        layout = topology["layout"]
        counts = daylight_counts(topology["available"], days)
        primary = retention(days, counts, STEPS, 1)
        sensitivity = retention(days, counts, STEPS, SENSITIVITY_MIN_DAYLIGHT)
        registered = REGISTERED_RETAINED.get(code)
        if registered is not None and primary["D_ret"] != registered:
            raise RuntimeError(
                f"{code}: {primary['D_ret']} retained days, s. 7 records {registered}"
            )
        facts = {
            str(line): cable_facts(topology, line, days, primary["retained"])
            for line in topology["lines"]
        }
        rules = placements(code)
        downstream = {int(line): sorted(topology["downstream"][int(line)])
                      for line in topology["lines"]}  # fmt: skip
        k_all = len(layout.buses)
        networks[code] = {
            "network": code,
            "role": "sweep (W6, W8, W9)" if full else "held out (W5)",
            "invariants": topology["invariants"],
            "lv_buses": [int(b) for b in layout.buses],
            "K_all": k_all,
            "lv_busbar": int(layout.lv_busbar),
            "resistance_distance_ohm": {str(int(b)): float(layout.distance[int(b)])
                                        for b in layout.buses},  # fmt: skip
            "feeder_heads": [int(i) for i in layout.feeder_heads],
            "candidates": topology["candidates"],
            "candidate_count": len(topology["candidates"]),
            "candidate_count_registered": REGISTERED_CANDIDATES.get(code),
            "local_line": topology["local_line"],
            "lines_analysed": topology["lines"],
            "lines_analysed_note": (
                "every candidate (s. 3)" if full else
                "the stress.local_line cable only; this network is held out until the "
                "registration is committed (s. 2)"
            ),  # fmt: skip
            "downstream": {str(line): below for line, below in downstream.items()},
            "reproduces_q1": topology["reproduces_q1"],
            "cable_facts": facts,
            "placement_rules": {"named": list(NAMED_RULES), "random": list(RANDOM_RULES),
                                "buses": rules}, # fmt: skip
            "intersection_coverage": intersection_coverage(rules, downstream),
            "days": {
                "scored": days,
                "scored_count": len(days),
                "daylight_per_day": [int(c) for c in counts],
                "retention_primary": primary,
                "retention_sensitivity_min_8_daylight": sensitivity,
                "retained_registered": registered,
            },
            "thresholds": threshold_grid(primary, k_all),
            "thresholds_sensitivity_min_8_daylight": threshold_grid(sensitivity, k_all),
        }

    report = {
        "stage": "1 (registration s. 3, s. 7, s. 8, s. 9, W3)",
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256,
                         "state": registration},  # fmt: skip
        "constants": {
            "sigma_grid": list(SIGMA_GRID),
            "sigma_co_primary": list(SIGMA_CO_PRIMARY),
            "K_grid": list(K_GRID),
            "estimators": list(ESTIMATORS),
            "remote_missing": REMOTE_MISSING,
            "nominal_kv": NOMINAL_KV,
            "line_r_factor": R_FACTOR,
            "precision_floor_pu": PRECISION_FLOOR_PU,
            "sensitivity_min_daylight_steps": SENSITIVITY_MIN_DAYLIGHT,
            "alpha": q1.ALPHA,
        },
        "sources": {
            "placements": q1.PLACEMENTS,
            "nominal_variant_network": "ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))",
            "no_vm_loaded_in_stage1": True,
            "no_flows_run_in_stage1": True,
        },
        "hypotheses": HYPOTHESES,
        "readings": {
            "R-a": "the plain-Graph cross-check stores the line-index set of every bus pair",
            "R-c": f"the precision-floor label applies to |value| < {PRECISION_FLOOR_PU:g} p.u.",
        },
        "networks": networks,
    }
    report["sha256"] = write_new_json(Path(inputs_path), plain(report))
    return report


# --- Stage 3 (s. 8, s. 9, W1, W2, W5, W8, W9) ----------------------------------------------


def load_stage1(path: Path = INPUTS_FILE) -> dict:
    """Stage 3's first barrier: Stage 1's file must exist, and its hash is recorded."""
    path = Path(path)
    if not path.exists():
        raise RuntimeError(
            f"{path} is missing; Stage 1 must run and write the registered inputs before "
            "Stage 3 computes any statistic (s. 12)"
        )
    text = path.read_text()
    return {"path": str(path), "sha256": q1.sha256_text(text), "inputs": json.loads(text)}


def failed_flow_check(runs, total_solves: int) -> dict:
    """s. 7: Stage 3 stops if failed truth flows exceed 0.1 % of all sweep solves, or 1 % of
    any single run's solves on retained days.

    `runs` is a sequence of dicts with `path`, `failed_total`, `failed_retained` and
    `solves_retained`.
    """
    runs = list(runs)
    total_failed = sum(int(r["failed_total"]) for r in runs)
    share = total_failed / int(total_solves) if total_solves else 0.0
    affected, over = [], []
    for run in runs:
        failed = int(run["failed_retained"])
        solves = int(run["solves_retained"])
        if not failed:
            continue
        fraction = failed / solves if solves else float("inf")
        entry = {"path": run["path"], "failed_retained": failed, "solves_retained": solves,
                 "fraction": fraction}  # fmt: skip
        affected.append(entry)
        if fraction > FAILED_RUN_FRACTION:
            over.append(entry)
    report = {
        "runs": len(runs),
        "total_solves": int(total_solves),
        "failed_truth_total": total_failed,
        "failed_truth_share": share,
        "total_limit": FAILED_TOTAL_FRACTION,
        "per_run_limit": FAILED_RUN_FRACTION,
        "runs_with_failed_flows": affected,
        "runs_over_the_per_run_limit": over,
        "within_limits": share <= FAILED_TOTAL_FRACTION and not over,
        "note": "below the limits, failed steps are excluded as invalid and every affected "
                "run is listed (s. 7)",  # fmt: skip
    }
    if not report["within_limits"]:
        raise RuntimeError(
            "Stage 3 stops and the board reports to the owner (s. 7): failed truth flows are "
            f"{share:.3%} of all sweep solves (limit {FAILED_TOTAL_FRACTION:.1%}) and "
            f"{len(over)} run(s) exceed {FAILED_RUN_FRACTION:.0%} of their retained solves"
        )
    return report


def sweep_barrier(root: Path = ps.SWEEP, key: str | None = None, specs=None, days=None) -> dict:
    """s. 7: the completeness barrier. Stage 3 computes nothing unless all 99 expected
    artefacts are present and verified."""
    manifest = ps.derive_manifest(root, key, specs, days)
    if not manifest["complete"]:
        raise RuntimeError(
            "Stage 3 refuses: the derived manifest shows "
            f"{manifest['present_runs']} of {manifest['expected_runs']} verified runs; s. 7's "
            "completeness barrier requires all 99"
        )
    return manifest


def _rule_inputs(buses, downstream, stats, estimator: str) -> dict:
    which = estimator_key(estimator)
    return {
        "m": np.asarray(stats["m"][which], dtype=float),
        "night": np.asarray(stats["night"][which], dtype=float),
        "k": np.asarray(stats["k"][which], dtype=float),
        "buses": [int(b) for b in buses],
        "downstream": sorted(int(b) for b in downstream),
    }


def reversal_record(entry: dict, facts: dict) -> dict:
    """For a failing cable (s. 9): the sign of the cable's mean daylight vs night downstream
    residual, plus P_l."""
    buses, downstream = entry["buses"], entry["downstream"]
    columns = [buses.index(b) for b in downstream if b in buses]
    day = float(np.mean(entry["m"][columns])) if columns else float("nan")
    night = float(np.mean(entry["night"][columns])) if columns else float("nan")
    reverses = (
        math.isfinite(day) and math.isfinite(night)
        and np.sign(day) != 0 and np.sign(night) != 0 and np.sign(day) != np.sign(night)
    )
    return {
        "mean_daylight_residual_downstream_pu": floor_label(day),
        "mean_night_residual_downstream_pu": floor_label(night),
        "sign_daylight": int(np.sign(day)) if math.isfinite(day) else None,
        "sign_night": int(np.sign(night)) if math.isfinite(night) else None,
        "downstream_flow_reverses": bool(reverses),
        "P_l_mw": float(facts["P_l_mw"]),
        "installed_pv_sn_mva": float(facts["installed_pv_sn_mva"]),
        "hypothesis": HYPOTHESES["R1_R2"],
    }


def rule_block(entries: dict, facts: dict, distance: dict, thresholds: dict,
               scope: str) -> dict:  # fmt: skip
    """R1-R4 and R3s over one network's cables at one sigma_tot and one z (s. 9).

    `entries` maps line index to the `_rule_inputs` arrays, `facts` to Stage 1's cable facts
    and `thresholds` is one `q1.thresholds` dict at z = z_{K_all}.
    """
    level_low = float(thresholds["level"]["low"])  # z * F_ind
    contrast_high = float(thresholds["contrast"]["high"])  # z * F_C,real
    cables = [{"line": line, **entry} for line, entry in sorted(entries.items())]

    r1 = r1_network(cables, level_low)
    r2 = r2_network({
        line: r2_cable(e["m"], e["night"], e["k"], e["buses"], e["downstream"],
                       level_low, contrast_high)
        for line, e in sorted(entries.items())
    })  # fmt: skip
    peaks, scores = [], []
    for line, entry in sorted(entries.items()):
        columns = [entry["buses"].index(b) for b in entry["downstream"] if b in entry["buses"]]
        peaks.append(float(np.abs(entry["k"][columns]).max()) if columns else float("nan"))
        scores.append(float(facts[str(line)]["S_l"]))
    r3 = r3_network(scores, peaks)
    r3s = {
        str(line): r3s_cable(e["m"], e["buses"], e["downstream"], distance)
        for line, e in sorted(entries.items())
    }
    r4 = r4_network({
        line: r4_cable(e["k"], e["buses"], e["downstream"], contrast_high)
        for line, e in sorted(entries.items())
    })  # fmt: skip

    failing = sorted(
        {*(c["line"] for c in r1["failing_cables"]), *r2["failing_cables"], *r4["failing_cables"]}
    )
    return {
        "scope": scope,
        "z": float(thresholds["z"]),
        "z_F_ind": level_low,
        "z_F_C_real": contrast_high,
        "R1": r1,
        "R2": r2,
        "R3": r3,
        "R3s": r3s,
        "R4": r4,
        "failing_cables": {
            str(line): reversal_record(entries[line], facts[str(line)]) for line in failing
        },
        "hypotheses": {"R1_R2": HYPOTHESES["R1_R2"], "rule": HYPOTHESES["rule"]},
    }


def coverage_block(entries: dict, rules: dict, thresholds: dict, estimator: str) -> dict:
    """s. 8 coverage at one sigma_tot: every K and rule family, with the W3 ceiling."""
    out = {}
    for k in K_GRID:
        low = float(thresholds[f"K_{k}"]["contrast"]["low"])
        high = float(thresholds[f"K_{k}"]["contrast"]["high"])
        per_family = {}
        for family, names in RULE_FAMILIES.items():
            wanted = list(rules) if names is None else [n for n in names if n in rules]
            pairs = []
            for _line, entry in sorted(entries.items()):
                below = set(entry["downstream"])
                for name in wanted:
                    config = configuration(rules[name], k)
                    value = c_meter(entry["k"], entry["buses"], config)
                    pairs.append((q1.band(abs(value), low, high), bool(set(config) & below)))
            per_family[family] = {"rules": len(wanted), **coverage_table(pairs)}
        out[f"K_{k}"] = {"z": float(thresholds[f"K_{k}"]["z"]), "band_low": low,
                         "band_high": high, "families": per_family}  # fmt: skip
    return {"estimator": estimator, "per_K": out}


def r6_identity(entry: dict, rules: dict, thresholds_by_estimator: dict) -> dict:
    """R6 (s. 9), an identity, reported at the registered cable: band C <=> the configuration
    intersects downstream(l), over sigma x K x estimator."""
    out, holds = {}, True
    for estimator, by_sigma in thresholds_by_estimator.items():
        out[estimator] = {}
        for sigma_text, bundle in by_sigma.items():
            out[estimator][sigma_text] = {}
            for k in K_GRID:
                low = float(bundle[f"K_{k}"]["contrast"]["low"])
                high = float(bundle[f"K_{k}"]["contrast"]["high"])
                values = entry[estimator_key(estimator)]
                agree, disagree = 0, []
                for name, buses in rules.items():
                    config = configuration(buses, k)
                    band = q1.band(
                        abs(c_meter(values, entry["buses"], config)), low, high
                    )
                    intersects = bool(set(config) & set(entry["downstream"]))
                    if (band == "C") == intersects:
                        agree += 1
                    else:
                        disagree.append({"rule": name, "band": band,
                                         "intersects": intersects})  # fmt: skip
                out[estimator][sigma_text][f"K_{k}"] = {
                    "rules": len(rules), "agree": agree, "disagree": disagree,
                    "identity_holds": not disagree,
                }  # fmt: skip
                holds = holds and not disagree
    return {"rule": "R6", "status": "identity, withdrawn as a rule (s. 9)",
            "identity_holds_everywhere": holds, "per_estimator": out}  # fmt: skip


def w1_rules(line: int, entry: dict, distance: dict, thresholds: dict) -> dict:
    """R1, R3s and R4 at one cable, on one set of per-bus arrays (s. 12.5 W1, reading R-s).

    R2 and R3 are not part of W1: R3 is a Spearman over a network's cables and R2 is not
    named by s. 12.5. `entry` is an `_rule_inputs` mapping and `thresholds` one `q1.thresholds`
    bundle at z_{K_all}.
    """
    level_low = float(thresholds["level"]["low"])  # z * F_ind
    contrast_high = float(thresholds["contrast"]["high"])  # z * F_C,real
    return {
        "z": float(thresholds["z"]),
        "z_F_ind": level_low,
        "z_F_C_real": contrast_high,
        "R1": r1_network([{"line": int(line), **entry}], level_low),
        "R3s": r3s_cable(entry["m"], entry["buses"], entry["downstream"], distance),
        "R4": r4_cable(entry["k"], entry["buses"], entry["downstream"], contrast_high),
    }


def _w1_verdicts(block: dict) -> dict:
    """The three W1 verdicts of one `w1_rules` block, for the side-by-side comparison."""
    return {"R1": block["R1"]["holds"], "R3s": block["R3s"]["spearman"],
            "R3s_argmax_in_downstream": block["R3s"]["argmax_in_downstream"],
            "R4": block["R4"]["holds"]}  # fmt: skip


def w1_comparison(code: str, entry: dict, stats: dict, line: int, distance: dict,
                  thresholds: dict) -> dict:  # fmt: skip
    """W1 (s. 12.5): the registered cable's sweep m, k and night against Q1's committed
    per-bus arrays in `results/q1_results.json`. The max abs difference is expected at or
    below the precision floor.

    s. 12.5 reads "R1/R3s/R4 at the registered cables, from Q1's committed per-bus arrays,
    checked against the sweep artefacts", so the three rules are evaluated on *both* sets of
    arrays and the two verdicts are reported side by side with the maximum numerical
    difference between them (reading R-s). `thresholds` maps each co-primary sigma_tot's text
    to its z_{K_all} bundle; `distance` is Stage 1's resistance distance per bus.
    """
    q1_data = json.loads(Q1_RESULTS.read_text())["networks"][code]
    q1_buses = [int(b) for b in q1_data["buses"]]
    if q1_buses != entry["buses"]:
        raise RuntimeError(f"{code}: Q1's bus order differs from the sweep artefact's")
    out, worst, rule_worst = {}, 0.0, 0.0
    for name in ("m", "k", "night"):
        for which in ("mean", "median"):
            reference = np.asarray(q1_data["per_bus"][name][which], dtype=float)
            observed = np.asarray(stats[name][which], dtype=float)
            difference = float(np.abs(observed - reference).max())
            worst = max(worst, difference)
            if which == "mean":  # the registered estimator, the one the rules are read on
                rule_worst = max(rule_worst, difference)
            out[f"{name}_{which}"] = {
                "max_abs_difference_pu": difference,
                "at_or_below_precision_floor": difference <= PRECISION_FLOOR_PU,
                "argmax_bus": int(q1_buses[int(np.argmax(np.abs(observed - reference)))]),
            }

    sweep_entry = _rule_inputs(entry["buses"], entry["downstream"], stats, "mean")
    q1_entry = _rule_inputs(entry["buses"], entry["downstream"], q1_data["per_bus"], "mean")
    per_sigma, agree_everywhere = {}, True
    for sigma_text, bundle in thresholds.items():
        from_sweep = w1_rules(line, sweep_entry, distance, bundle)
        from_q1 = w1_rules(line, q1_entry, distance, bundle)
        agree = _w1_verdicts(from_sweep) == _w1_verdicts(from_q1)
        agree_everywhere = agree_everywhere and agree
        per_sigma[sigma_text] = {
            "from_sweep_artefacts": from_sweep,
            "from_q1_committed_arrays": from_q1,
            "verdicts_agree": bool(agree),
            "verdicts": {"from_sweep_artefacts": _w1_verdicts(from_sweep),
                         "from_q1_committed_arrays": _w1_verdicts(from_q1)},  # fmt: skip
        }
    return {
        "source": "analysis/phase9/results/q1_results.json (committed, read-only)",
        "line": int(line),
        "per_statistic": out,
        "max_abs_difference_pu": worst,
        "expectation": "at or below the cache precision floor of 1e-6 p.u. (s. 7)",
        "meets_expectation": worst <= PRECISION_FLOOR_PU,
        "rule_fidelity": {
            "statement": "s. 12.5 W1: R1, R3s and R4 at the registered cable, evaluated on "
                         "Q1's committed per-bus arrays and on the sweep artefact's, side by "
                         "side (reading R-s)",  # fmt: skip
            "estimator": "mean (the registered estimator, reading R-d)",
            "max_abs_difference_pu": rule_worst,
            "max_abs_difference_at_or_below_precision_floor": (
                rule_worst <= PRECISION_FLOOR_PU
            ),
            "per_sigma_tot": per_sigma,
            "verdicts_agree_everywhere": bool(agree_everywhere),
            "note": "a disagreement is reported as a disagreement, not reconciled; the sweep "
                    "arrays stay the verdict of record of s. 8 and s. 9",  # fmt: skip
        },
    }


def w2_hits(code: str, downstream, rules: dict) -> dict:
    """W2 (s. 12.5): hit counts at the registered cable.

    The expected counts are the implementation issue's, not the registration's -- s. 12.5
    registers the hit rates as an output and fixes no number for them -- so they are reported
    as an issue-sourced expectation and a mismatch is reported as a mismatch.
    """
    below = set(int(b) for b in downstream)
    per_k, mismatches = {}, []
    for k in K_GRID:
        hits = [name for name, buses in rules.items() if set(configuration(buses, k)) & below]
        expected = W2_REGISTERED_HITS.get(code, {}).get(k)
        if expected is not None and len(hits) != expected:
            mismatches.append({"K": k, "observed": len(hits), "expected": expected})
        per_k[f"K_{k}"] = {
            "hits": len(hits),
            "rules": len(rules),
            "expected": expected,
            "expected_is_registered": False,
            "matches_expectation": None if expected is None else len(hits) == expected,
            "hitting_rules": sorted(hits),
        }
    return {"per_K": per_k, "mismatches": mismatches,
            "expectation_source": W2_EXPECTATION_SOURCE,
            "expectation_is_registered": False}  # fmt: skip


def w5_network(code: str, inputs: dict) -> dict:
    """W5 (s. 2, s. 9): the held-out networks' level-0 truth and nominal legs, reduced with
    the same per-day function, then R5 plus the four consistency checks.

    This is the only part of Stage 3 that loads a held-out network, and it reads the
    read-only caches of s. 2 only.
    """
    from gridpulse import fullstate
    from gridpulse import stress as st

    facts = inputs["networks"][code]
    days = [int(d) for d in facts["days"]["scored"]]
    retained = [int(d) for d in facts["days"]["retention_primary"]["retained"]]
    line = int(facts["local_line"])
    downstream = [int(b) for b in facts["downstream"][str(line)]]
    buses = [int(b) for b in facts["lv_buses"]]

    # the daylight mask is the registered network-wide one of s. 2, rebuilt from the nominal
    # variant network's own availability (not from Stage 1's per-day step counts)
    from gridpulse import dual_study as ds
    from gridpulse import grid, grid_study

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    available = grid_study.daily_arrays(grid.absolute_profiles(net))["sgen_p_mw"]
    daylight = {int(d): available[d].sum(axis=1) > 0 for d in days}
    counts = [int(daylight[int(d)].sum()) for d in days]
    if counts != [int(c) for c in facts["days"]["daylight_per_day"]]:
        raise RuntimeError(f"{code}: the daylight counts differ from Stage 1's")
    if [int(b) for b in fullstate.lv_buses(net)] != buses:
        raise RuntimeError(f"{code}: the cache bus order differs from Stage 1's LV buses")

    truth = st.load(ps.ROBUST_CACHE, code, ps.CACHED_TRUTH, days)
    nominal = fullstate.load_states(ps.NOMINAL_CACHE, code, ps.NOMINAL_TRUTH, days)

    rows = [
        ps.reduce_day(
            np.asarray(truth[d]["vm"], dtype=np.float64)[:, ps.LEVEL, :],
            np.asarray(nominal[d]["vm"], dtype=np.float64)[:, ps.LEVEL, :],
            daylight[d],
        )
        for d in days
    ]
    arrays = ps.build_arrays(rows, days, buses)
    stats = run_statistics(arrays, retained)
    entry = _rule_inputs(buses, downstream, stats, "mean")
    cable = facts["cable_facts"][str(line)]
    distance = {int(b): float(v) for b, v in facts["resistance_distance_ohm"].items()}
    thresholds = facts["thresholds"]["mean"]

    consistency = {}
    for sigma in SIGMA_CO_PRIMARY:
        bundle = thresholds[f"{sigma:g}"][f"K_{facts['K_all']}"]
        consistency[f"{sigma:g}"] = {
            **rule_block({line: entry}, facts["cable_facts"], distance, bundle,
                         "W5 consistency checks, not tests (s. 9)"),
            "label": "R1, R2, R4 and R3s are consistency checks on the held-out networks "
                     "(s. 9, sub-decision i)",
        }  # fmt: skip

    return {
        "network": code,
        "label": "pre-registered held-out statistic, exploratory programme (s. 13 (i))",
        "line": line,
        "downstream": downstream,
        "truth_leg": f"stress.load(outputs/robust_study/fullstate_cache, {code}, line_local)",
        "nominal_leg": (
            f"fullstate.load_states(outputs/sense_study/fullstate_cache, {code}, nominal)"
        ),
        "days": {"scored": len(days), "retained": len(retained),
                 "used": stats["days_used"],
                 "dropped_no_valid_step": stats["days_dropped_no_valid_step"]},  # fmt: skip
        "per_bus": {
            "buses": buses,
            "m": {w: stats["m"][w] for w in ("mean", "median")},
            "night": {w: stats["night"][w] for w in ("mean", "median")},
            "k": {w: stats["k"][w] for w in ("mean", "median")},
        },
        "cable_facts": cable,
        "R5": r5_ratio(entry["m"], buses, cable["m_pred_pu"]),
        "consistency_checks": consistency,
        "failed_truth_total": stats["failed_truth_total"],
    }


def w8_block(by_spec: dict, entry_downstream, buses, facts_thresholds: dict) -> dict:
    """W8 (s. 9, descriptive): f* per sigma, and the slope ratios of |k| in (f - 1)."""
    downstream = [int(b) for b in entry_downstream]
    columns = [list(buses).index(b) for b in downstream if b in list(buses)]
    peaks = {}
    for factor, stats in sorted(by_spec.items()):
        values = np.abs(np.asarray(stats["k"]["mean"], dtype=float)[columns])
        peaks[factor] = float(values.max()) if values.size else float("nan")
    reference = peaks.get(R_FACTOR)
    slopes = {f"{f:g}": peaks[f] / (f - 1.0) for f in peaks}
    base_slope = slopes.get(f"{R_FACTOR:g}")
    per_sigma = {}
    for sigma in SIGMA_GRID:
        bundle = facts_thresholds[f"{sigma:g}"]["K_2"]
        high = float(bundle["contrast"]["high"])
        reaching = [f for f in sorted(peaks) if peaks[f] >= high]
        per_sigma[f"{sigma:g}"] = {
            "z_2_F_C_real": high,
            "f_star": min(reaching) if reaching else None,
            "f_star_record": None if reaching else "not reached on {1.1, 1.25, 1.5, 2.0}",
            "band_C_factors": reaching,
        }
    return {
        "factors": [f"{f:g}" for f in sorted(peaks)],
        "max_abs_k_downstream_pu": {f"{f:g}": floor_label(v) for f, v in sorted(peaks.items())},
        "slopes_per_unit_r_increment": slopes,
        "slope_ratio_to_f_1.5": (
            {f: (s / base_slope if base_slope else None) for f, s in slopes.items()}
            if base_slope
            else None
        ),
        "max_abs_k_ratio_to_f_1.5": (
            {f"{f:g}": (v / reference if reference else None) for f, v in sorted(peaks.items())}
            if reference
            else None
        ),
        "per_sigma": per_sigma,
        "hypothesis": HYPOTHESES["W8"],
        "reading": "R-f: slope(f) = max over downstream of |k| / (f - 1)",
    }


def w9_block(by_spec: dict, reference_stats: dict, entry_downstream, buses) -> dict:
    """W9 (s. 9, descriptive): E-L(g)'s m, k and night per bus against E-R(1.5)."""
    buses = [int(b) for b in buses]
    downstream = set(int(b) for b in entry_downstream)
    inside = [buses.index(b) for b in sorted(downstream) if b in buses]
    outside = [i for i, b in enumerate(buses) if b not in downstream]
    base_k = np.asarray(reference_stats["k"]["mean"], dtype=float)
    out = {}
    for factor, stats in sorted(by_spec.items()):
        k = np.asarray(stats["k"]["mean"], dtype=float)
        predicted = (factor - 1.0) / (R_FACTOR - 1.0)
        peak_in = float(np.abs(k[inside]).max()) if inside else float("nan")
        base_in = float(np.abs(base_k[inside]).max()) if inside else float("nan")
        observed = peak_in / base_in if base_in else float("nan")
        out[f"{factor:g}"] = {
            "per_bus": {
                "buses": buses,
                "m": {w: stats["m"][w] for w in ("mean", "median")},
                "night": {w: stats["night"][w] for w in ("mean", "median")},
                "k": {w: stats["k"][w] for w in ("mean", "median")},
            },
            "sign_split_vs_E_R_1.5": {
                "downstream_signs_unchanged": int(
                    sum(1 for i in inside if np.sign(k[i]) == np.sign(base_k[i]))
                ),
                "downstream_buses": len(inside),
                "off_downstream_signs_unchanged": int(
                    sum(1 for i in outside if np.sign(k[i]) == np.sign(base_k[i]))
                ),
                "off_downstream_buses": len(outside),
                "unchanged": bool(
                    all(np.sign(k[i]) == np.sign(base_k[i]) for i in inside)
                    and all(np.sign(k[i]) == np.sign(base_k[i]) for i in outside)
                ),
            },
            "max_abs_k_downstream_ratio_to_E_R_1.5": observed,
            "r_only_prediction": predicted,
            "relative_deviation_from_prediction": (
                (observed - predicted) / predicted if predicted else None
            ),
            "deviation_exceeds_10_percent": (
                bool(abs((observed - predicted) / predicted) > 0.10)
                if predicted and math.isfinite(observed)
                else None
            ),
        }
    return {"per_factor": out, "hypothesis": HYPOTHESES["W9"],
            "reading": "R-g: the R-only prediction is (g - 1) / 0.5"}  # fmt: skip


# --- CONTROLS EXTENSION POINT (registration s. 10) -----------------------------------------
#
# Controls 1-5 and the A* amplitude sweep of s. 10 live between here and `controls()` below.
# They are all zero-flow: the noise is simulated analytically on the per-day means the s. 7
# artefacts already store, which s. 16 records as exact for the registered Gaussian,
# i.i.d.-per-reading model. Control 3 is the single exception named by s. 10 and s. 16: it
# permutes per-step labels, so it reads the caches, at the registered and the four held-out
# cables only.
#
#   control 1 (R7)  the family-wise false-alarm rate of the floor, truth = nominal, 2,000
#                   replicates per network x condition, Wilson 95 % intervals;
#   control 2 (A*)  the diurnal-bias amplitude sweep: A*_fa (binding, 2,000 replicates per
#                   grid point) and A*_cov (400), square and sinusoid shapes, random and
#                   adverse signs, with the log-A crossing rule;
#   control 3       permuted day/night labels, 200 permutations;
#   control 4       Jaccard(S_detect(l), downstream(l')) for every other candidate l';
#   control 5       coverage of random_0...19 against the 5 named rules.
#
# Readings R-i to R-r of the module docstring record every place s. 10 left a choice open.

CONTROL_CONDITIONS = ("realistic", "sigma_0.005", "sigma_0.02", "biased_meters_matched")  # s. 10
MATCHED_CONDITION = "biased_meters_matched"  # the one condition with a static bias (s. 10)

SEED_ROOT = 20261023  # s. 10
CONTROL1 = "control_1"  # the s. 10 `control` strings, reading R-i
CONTROL1_SQRT2 = "control_1_sqrt2"
CONTROL2_FA = "control_2_fa"
CONTROL2_COV = "control_2_cov"
CONTROL3 = "control_3"
NO_CONDITION = "none"  # control 3 has no noise condition (reading R-i)

CONTROL1_REPLICATES = 2000  # s. 10 control 1
A_STAR_FA_REPLICATES = 2000  # s. 10 control 2, A*_fa
A_STAR_COV_REPLICATES = 400  # s. 10 control 2, A*_cov
PERMUTATIONS = 200  # s. 10 control 3

A_OVER_SIGMA = (0.0, 0.003, 0.006, 0.01, 0.02, 0.03, 0.06, 0.1, 0.2, 0.3)  # s. 10 control 2
A_STAR_SHAPES = ("square", "sinusoid")  # square is primary (s. 10)
A_STAR_SIGNS = ("random", "adverse")  # random is primary (s. 10)
A_STAR_CONDITIONS = {"0.01": "realistic", "0.005": "sigma_0.005"}  # `realistic`-type noise
FAMILY_ALPHA = 0.05  # s. 8 family-wise alpha, and the A*_fa target of s. 10
COV_HALVING = 0.5  # s. 10: A*_cov is where coverage <= 0.5 * coverage(0)
R7_LIMIT = 0.05  # s. 9 R7: the Wilson 95 % lower bound is at most 0.05

# The threshold sigma_tot of each condition (reading R-n for the matched arm).
CONDITION_SIGMA_KEY = {
    "realistic": "0.01",
    "sigma_0.005": "0.005",
    "sigma_0.02": "0.02",
    MATCHED_CONDITION: "0.01",
}

CONTROL_READINGS = {
    "R-i": "the s. 10 `control` seed strings are control_1, control_1_sqrt2, control_2_fa, "
           "control_2_cov and control_3; control 3's `condition` is `none`",
    "R-j": "the simulator's day axis is the usable retained days (R-b), intersected over the "
           "network's W6 artefacts, minus the last retained day (the 1-day delay); a meter "
           "with no surviving day has k-hat = NaN and raises no alarm",
    "R-k": "the crossing records are typed: interpolated, `<= 0.003 sigma` when the crossing "
           "is not bracketed at the bottom, `> 0.3 sigma` (s. 10's `not reached`) when the "
           "condition holds at no grid point; A*_fa must be read against its own A = 0 rate, "
           "emitted next to every A*_fa record, and a crossing at or below the first positive "
           "grid point is a baseline artefact of that rate, not a measured tolerance",
    "R-l": "one replicate is one measurement realisation of the meters, shared by every "
           "rule x K and, in A*_cov, by every (cable, rule) pair; the intervals stay "
           "descriptive, as s. 8 already says of pairs",
    "R-m": "the sqrt(2) variant draws a second independent leg for the per-day noise and for "
           "the static bias; the bias still cancels in k",
    "R-n": "the threshold sigma_tot of biased_meters_matched is the registered 0.01 of s. 8, "
           "not sqrt(0.002^2 + 0.0098^2) = 0.0100020",
    "R-o": "the simulator's per-day counts are the valid counts of the registered cable's "
           "artefact, because s. 10 fixes the variance as sigma_v^2 / n_daylight_valid",
    "R-p": "control 3 permutes the labels over all 96 steps with the daylight count "
           "preserved; validity is re-intersected and a day without a valid daylight or "
           "night step drops from that permutation (R-b)",
    "R-q": "the sinusoid's per-day daylight mean is taken over all n_daylight_steps of the "
           "day; a day with an invalid daylight step makes it an approximation, flagged",
    "R-r": "the R7 verdict is the measured-leg-only variant against z_K * F_C,real over every "
           "condition x rule x K; the F_C,matched arm and the sqrt(2) variant are diagnostics",
}  # fmt: skip


def noise_spec(condition: str) -> dict:
    """One s. 10 condition, read from `noise_study.CONDITIONS` (`noise_study.py:31-45`).

    Nothing is retyped: sigma_v, sigma_bias, the missing probability and the delay all come
    from the frozen Phase 6 `MeasurementModel`. sigma_tot is sqrt(sigma_v^2 + sigma_bias^2),
    and the band threshold it is read against is reading R-n's registered key.
    """
    from gridpulse import noise_study as nst

    if condition not in nst.CONDITIONS:
        raise KeyError(f"{condition} is not a `noise_study.CONDITIONS` condition")
    model = nst.CONDITIONS[condition]
    sigma_v, sigma_bias = float(model.sigma_v_remote), float(model.sigma_bias_remote)
    spec = {
        "condition": condition,
        "sigma_v": sigma_v,
        "sigma_bias": sigma_bias,
        "remote_missing": float(model.remote_missing),
        "remote_delay_days": int(model.remote_delay_days),
        "sigma_tot": math.sqrt(sigma_v**2 + sigma_bias**2),
        "threshold_sigma_key": CONDITION_SIGMA_KEY[condition],
        "source": "gridpulse.noise_study.CONDITIONS (noise_study.py:31-45), frozen Phase 6",
    }
    if spec["remote_missing"] != REMOTE_MISSING or spec["remote_delay_days"] != 1:
        raise RuntimeError(
            f"{condition}: s. 10 fixes a 0.05 missing-day probability and a 1-day delay, the "
            f"frozen condition carries {spec['remote_missing']} and "
            f"{spec['remote_delay_days']}"
        )
    return spec


def control_rng(network: str, condition: str, control: str, index: int = 0):
    """The s. 10 seed, exactly as the registration writes it (reading R-i)."""
    from gridpulse import sensing as sn

    return np.random.default_rng(np.random.SeedSequence([
        SEED_ROOT, sn._stable_int(str(network)), sn._stable_int(str(condition)),
        sn._stable_int(str(control)), int(index),
    ]))  # fmt: skip


def rate_record(successes: int, trials: int) -> dict:
    """A Monte Carlo rate with its Wilson 95 % interval, without `wilson`'s per-cell label.

    The label is descriptive and is carried once per block (reading R-l), not per cell.
    """
    interval = wilson(successes, trials)
    return {name: interval[name] for name in ("successes", "trials", "rate", "low", "high")}


def meter_days(arrays_list, retained_days) -> dict:
    """The s. 10 simulator's day axis and per-day counts (readings R-j and R-o).

    `arrays_list` is one or more artefact array mappings sharing the scored-day axis; the
    first one supplies the counts (the registered cable's, in Stage 3). A day is kept iff it
    is retained, usable in *every* artefact (reading R-b) and is not the last retained day,
    which the 1-day delay of s. 10 removes.
    """
    arrays_list = list(arrays_list)
    if not arrays_list:
        raise ValueError("at least one artefact is needed for the s. 10 day axis")
    first = arrays_list[0]
    day_index = np.asarray(first["day_index"], dtype=int)
    wanted = sorted({int(d) for d in retained_days})
    if not wanted:
        raise ValueError("s. 10 needs at least one retained day")
    retained = np.isin(day_index, wanted)
    usable = retained.copy()
    for arrays in arrays_list:
        if not np.array_equal(np.asarray(arrays["day_index"], dtype=int), day_index):
            raise RuntimeError("the artefacts do not share one scored-day axis")
        usable &= np.asarray(arrays["n_daylight_valid"], dtype=int) > 0
        usable &= np.asarray(arrays["n_night_valid"], dtype=int) > 0
        usable &= np.isfinite(np.asarray(arrays["dmean_daylight"], dtype=float)).all(axis=1)
        usable &= np.isfinite(np.asarray(arrays["dmean_night"], dtype=float)).all(axis=1)
    keep = usable & (day_index != wanted[-1])
    if not keep.any():
        raise RuntimeError(
            "no retained day survives the s. 10 usability and 1-day-delay rules"
        )
    n_day = np.asarray(first["n_daylight_valid"], dtype=int)[keep]
    n_night = np.asarray(first["n_night_valid"], dtype=int)[keep]
    steps = np.asarray(first["n_daylight_steps"], dtype=int)[keep]
    return {
        "rows": keep,
        "days": [int(d) for d in day_index[keep]],
        "n_daylight_valid": n_day,
        "n_night_valid": n_night,
        "n_daylight_steps": steps,
        "simulated_days": int(keep.sum()),
        "delay_removed_day": wanted[-1],
        "retained_days": len(wanted),
        "dropped_not_usable": [int(d) for d in day_index[retained & ~usable]],
        "all_daylight_steps_valid": bool((n_day == steps).all()),
        "artefacts_intersected": len(arrays_list),
        "readings": ["R-j", "R-o"],
    }


def sinusoid_day_mean(n_daylight: int) -> float:
    """The per-day mean of s. 10's sinusoid shape over a day's `n_daylight` daylight steps:
    mean over i of sin(pi (i + 1/2) / n_d), in the step order within that day (reading R-q)."""
    n = int(n_daylight)
    if n < 1:
        raise ValueError(f"a day needs at least one daylight step, got {n}")
    return float(np.sin(np.pi * (np.arange(n, dtype=float) + 0.5) / n).mean())


def shape_day_means(shape: str, n_daylight) -> np.ndarray:
    """s-bar(d), the per-day daylight mean of one s. 10 bias shape. s is 0 at night for both
    shapes, so the night mean is 0 and only the daylight leg is shifted."""
    counts = np.asarray(n_daylight, dtype=int)
    if shape == "square":
        return np.ones(counts.size, dtype=float)
    if shape == "sinusoid":
        return np.array([sinusoid_day_mean(int(c)) for c in counts], dtype=float)
    raise ValueError(f"{shape} is not an s. 10 bias shape {A_STAR_SHAPES}")


def draw_replicate(rng, spec: dict, n_day, n_night, meters: int, both_legs: bool = False) -> dict:
    """One replicate of the s. 10 per-day-mean noise simulator, for `meters` meters.

    The draw order is fixed: the daylight noise, the night noise, the static bias, then --
    only in the sqrt(2) variant (reading R-m) -- the second leg's three draws in the same
    order, and finally the missing-day draw. The measured-leg variant's first three draws are
    therefore identical to the sqrt(2) variant's.
    """
    n_day = np.asarray(n_day, dtype=float)
    n_night = np.asarray(n_night, dtype=float)
    if n_day.ndim != 1 or n_night.shape != n_day.shape:
        raise ValueError(f"the per-day counts differ in shape: {n_day.shape}, {n_night.shape}")
    if (n_day <= 0).any() or (n_night <= 0).any():
        raise ValueError("every simulated day needs a valid daylight and a valid night step")
    days, meters = int(n_day.size), int(meters)
    sigma_v, sigma_bias = float(spec["sigma_v"]), float(spec["sigma_bias"])
    scale_day = (sigma_v / np.sqrt(n_day))[:, None]
    scale_night = (sigma_v / np.sqrt(n_night))[:, None]

    day = rng.standard_normal((days, meters)) * scale_day
    night = rng.standard_normal((days, meters)) * scale_night
    bias = rng.standard_normal(meters) * sigma_bias
    if both_legs:  # measurement against measurement: a second, independent leg (reading R-m)
        day = day - rng.standard_normal((days, meters)) * scale_day
        night = night - rng.standard_normal((days, meters)) * scale_night
        bias = bias - rng.standard_normal(meters) * sigma_bias
    survives = rng.random((days, meters)) >= float(spec["remote_missing"])
    return {"day": day, "night": night, "bias": bias, "survives": survives,
            "both_legs": bool(both_legs), "days": days, "meters": meters}  # fmt: skip


def survival_mean(values, survives) -> np.ndarray:
    """The mean of a per-day quantity over a meter's surviving days (s. 10).

    `survives` is [days, meters]; `values` broadcasts against it with the day axis second to
    last, so [days, meters] and [cables, days, meters] both work. A meter with no surviving
    day returns NaN (reading R-j).
    """
    survives = np.asarray(survives, dtype=bool)
    counts = survives.sum(axis=0)
    total = np.where(survives, np.asarray(values, dtype=float), 0.0).sum(axis=-2)
    return np.where(counts > 0, total / np.maximum(counts, 1), np.nan)


def replicate_statistics(draws: dict, truth_day=0.0, truth_night=0.0, amplitude_day=0.0) -> dict:
    """m-hat, night-hat and k-hat per meter from one replicate (s. 10).

    `truth_day` and `truth_night` are the stored per-day means of the truth leg on the
    simulator's day axis (0 everywhere when truth = nominal, as in controls 1 and A*_fa).
    `amplitude_day` is control 2's A * g_b * s-bar(d) on the daylight leg only.
    """
    survives = draws["survives"]
    day = np.asarray(truth_day, dtype=float) + draws["day"] + draws["bias"]
    day = day + np.asarray(amplitude_day, dtype=float)
    night = np.asarray(truth_night, dtype=float) + draws["night"] + draws["bias"]
    return {
        "m": survival_mean(day, survives),
        "night": survival_mean(night, survives),
        "k": survival_mean(day - night, survives),
        "days_used": survives.sum(axis=0),
    }


def config_matrix(rules: dict, buses, k: int) -> tuple[np.ndarray, list[str]]:
    """The [rules, buses] membership matrix of the K-bus configurations of s. 8, with the rule
    names in sorted order so every block of the output is indexed the same way."""
    names = sorted(rules)
    buses = [int(b) for b in buses]
    position = {b: i for i, b in enumerate(buses)}
    mask = np.zeros((len(names), len(buses)), dtype=bool)
    for row, name in enumerate(names):
        for bus in configuration(rules[name], k):
            if int(bus) not in position:
                raise RuntimeError(f"rule {name} places a meter on bus {bus}, not an LV bus")
            mask[row, position[int(bus)]] = True
    return mask, names


def family_alarm(k_hat, mask, threshold: float) -> np.ndarray:
    """s. 10's event "any of the K meters has |k-hat| >= z_K * F_C,real", per rule.

    `k_hat` is [..., meters] and `mask` the [rules, meters] matrix of `config_matrix`, so the
    result is [..., rules]. A meter with no reading (NaN, reading R-j) raises no alarm.
    """
    values = np.abs(np.asarray(k_hat, dtype=float))
    values = np.where(np.isfinite(values), values, 0.0)
    peaks = np.where(np.asarray(mask, dtype=bool), values[..., None, :], -np.inf).max(axis=-1)
    return peaks >= float(threshold)


# --- s. 10 control 1: the unit test of the floor (R7) --------------------------------------


def control1_network(code: str, buses, rules: dict, counts: dict, thresholds: dict, *,
                     replicates: int = CONTROL1_REPLICATES,
                     conditions=CONTROL_CONDITIONS, specs: dict | None = None) -> dict:  # fmt: skip
    """s. 10 control 1 for one network: with truth = nominal (Delta == 0), the family-wise
    false-alarm rate of "any of K meters has |k-hat| >= z_K * F_C,real", per condition, rule
    and K, in the measured-leg and the mandatory sqrt(2) variants.

    `counts` is a `meter_days` result and `thresholds` one network's `thresholds[estimator]`
    mapping of Stage 1. The rate against z_K * F_C,matched is added for the matched condition
    only, as s. 10 says.
    """
    buses = [int(b) for b in buses]
    matrices = {k: config_matrix(rules, buses, k) for k in K_GRID}
    names = matrices[K_GRID[0]][1]
    per_condition = {}
    for condition in conditions:
        spec = (specs or {}).get(condition) or noise_spec(condition)
        bundle = thresholds[spec["threshold_sigma_key"]]
        arms = [("F_C_real", "high")]
        if condition == MATCHED_CONDITION:
            arms.append(("F_C_matched", "low"))
        variants = {}
        for both_legs, control in ((False, CONTROL1), (True, CONTROL1_SQRT2)):
            rng = control_rng(code, condition, control, 0)
            tally = {arm: {k: np.zeros(len(names), dtype=int) for k in K_GRID} for arm, _ in arms}
            no_reading = 0
            for _ in range(int(replicates)):
                draws = draw_replicate(rng, spec, counts["n_daylight_valid"],
                                       counts["n_night_valid"], len(buses), both_legs)  # fmt: skip
                k_hat = replicate_statistics(draws)["k"]
                no_reading += int((~np.isfinite(k_hat)).sum())
                for k in K_GRID:
                    mask, _ = matrices[k]
                    for arm, which in arms:
                        threshold = float(bundle[f"K_{k}"]["contrast"][which])
                        tally[arm][k] += family_alarm(k_hat, mask, threshold)
            variants["sqrt2" if both_legs else "measured_leg"] = {
                "control_seed_string": control,
                "both_legs_noisy": both_legs,
                "replicates": int(replicates),
                "meter_days_without_a_reading": no_reading,
                "arms": {
                    arm: {
                        f"K_{k}": {
                            "z": float(bundle[f"K_{k}"]["z"]),
                            "threshold_pu": float(bundle[f"K_{k}"]["contrast"][which]),
                            "per_rule": {
                                name: rate_record(int(tally[arm][k][i]), int(replicates))
                                for i, name in enumerate(names)
                            },
                            "pooled_over_rules": rate_record(
                                int(tally[arm][k].sum()), int(replicates) * len(names)
                            ),
                            "worst_rule": max(
                                (
                                    {"rule": name,
                                     **rate_record(int(tally[arm][k][i]), int(replicates))}
                                    for i, name in enumerate(names)
                                ),
                                key=lambda record: record["low"],
                            ),  # fmt: skip
                        }
                        for k in K_GRID
                    }
                    for arm, which in arms
                },
            }
        per_condition[condition] = {
            "spec": spec,
            "threshold_sigma_key": spec["threshold_sigma_key"],
            "variants": variants,
        }
    return {
        "control": "1",
        "statement": "s. 10: a unit test of the floor's treatment of missing sensor-days, the "
                     "1-day delay and day retention; not an empirical false-alarm rate for a "
                     "real deployment",
        "truth": "nominal (Delta == 0)",
        "rules": len(names),
        "rule_names": names,
        "K_grid": list(K_GRID),
        "day_axis": {name: counts[name] for name in
                     ("days", "simulated_days", "delay_removed_day", "retained_days",
                      "dropped_not_usable", "all_daylight_steps_valid")},  # fmt: skip
        "interval_label": "descriptive Wilson 95 % (s. 8, reading R-l)",
        "per_condition": per_condition,
    }  # fmt: skip


def r7_verdict(per_network: dict) -> dict:
    """R7 (s. 9): it holds iff every measured-leg, F_C,real Wilson 95 % lower bound of
    control 1 is at most 0.05 (reading R-r)."""
    cells, failing = 0, []
    for code, block in sorted(per_network.items()):
        for condition, entry in sorted(block["per_condition"].items()):
            arm = entry["variants"]["measured_leg"]["arms"]["F_C_real"]
            for k_text, per_k in sorted(arm.items()):
                for rule, record in sorted(per_k["per_rule"].items()):
                    cells += 1
                    if record["low"] is None or record["low"] > R7_LIMIT:
                        failing.append({"network": code, "condition": condition, "K": k_text,
                                        "rule": rule, **record})  # fmt: skip
    return {
        "rule": "R7",
        "statement": "s. 9: the family-wise false-alarm rate is at most 0.05 within Monte "
                     "Carlo error (Wilson 95 % lower bound <= 0.05)",
        "limit": R7_LIMIT,
        "cells": cells,
        "failing_cells": failing,
        "holds": None if not cells else not failing,
        "reading": CONTROL_READINGS["R-r"],
    }  # fmt: skip


# --- s. 10 control 2: the diurnal-bias amplitude sweep (A*) --------------------------------


def interpolate_crossing(amplitudes, rates, target: float, direction: str,
                         sigma_tot: float) -> dict:  # fmt: skip
    """s. 10's crossing rule: the smallest A at which the rate crosses `target`, interpolated
    linearly in the rate between the bracketing grid points on log A (reading R-k).

    `direction` is "above" for A*_fa ("the smallest A at which the rate exceeds 0.05") and
    "below" for A*_cov ("the smallest A at which coverage <= 0.5 * coverage(0)").
    """
    amplitudes = [float(a) for a in amplitudes]
    rates = [float(r) for r in rates]
    if len(amplitudes) != len(rates) or not amplitudes:
        raise ValueError("one rate per amplitude grid point is required")
    if direction not in ("above", "below"):
        raise ValueError(f"{direction} is not a crossing direction")
    crossed = [
        i for i, r in enumerate(rates)
        if (r > float(target) if direction == "above" else r <= float(target))
    ]  # fmt: skip
    out = {
        "target": float(target),
        "direction": direction,
        "sigma_tot": float(sigma_tot),
        "A_star_pu": None,
        "A_star_over_sigma_tot": None,
        "bracket": None,
        "not_reached": False,
        "reading": "R-k",
    }
    if not crossed:
        return {**out, "record": "> 0.3 sigma", "not_reached": True,
                "note": "the condition holds at no grid point; s. 10's `not reached` case"}
    first = crossed[0]
    if first == 0 or amplitudes[first - 1] <= 0.0:
        return {**out, "record": "<= 0.003 sigma",
                "note": ("the condition already holds at A = 0" if first == 0 else
                         "the bracket's lower point is A = 0, which log A cannot interpolate"),
                "crossed_at_grid_point_pu": amplitudes[first]}  # fmt: skip
    # the bracketing rates cannot be equal: `first` is the first index that crosses, so
    # rates[first] crosses and rates[first - 1] does not
    low, high = amplitudes[first - 1], amplitudes[first]
    rate_low, rate_high = rates[first - 1], rates[first]
    share = (float(target) - rate_low) / (rate_high - rate_low)
    crossing = math.exp(math.log(low) + share * (math.log(high) - math.log(low)))
    return {
        **out,
        "record": "interpolated",
        "A_star_pu": float(crossing),
        "A_star_over_sigma_tot": float(crossing / sigma_tot) if sigma_tot else None,
        "bracket": {"A_low_pu": low, "A_high_pu": high, "rate_low": rate_low,
                    "rate_high": rate_high},  # fmt: skip
        "note": "linear in the rate between the bracketing grid points, on log A (s. 10)",
    }  # fmt: skip


def control2_fa_network(code: str, buses, rules: dict, counts: dict, thresholds: dict, *,
                        replicates: int = A_STAR_FA_REPLICATES, grid=A_OVER_SIGMA,
                        shapes=A_STAR_SHAPES, conditions=A_STAR_CONDITIONS,
                        specs: dict | None = None) -> dict:  # fmt: skip
    """A*_fa (s. 10 control 2, primary and binding): truth = nominal, the family-wise
    false-alarm rate pooled over the 25 rules, per grid point, shape and K.

    The sign is random only, because the adverse sign is defined by k and k is 0 here (s. 10).

    Every A*_fa record carries the A = 0 rate it must be read against (reading R-k): that grid
    point is the floor's own family-wise false-alarm rate at this condition, K and sigma_tot,
    with no diurnal bias at all. Where the A = 0 rate already exceeds the 0.05 target the
    crossing is recorded at or below the first positive grid point, and that record is a
    baseline artefact of the floor, not a measured tolerance of the method to diurnal bias.
    """
    buses = [int(b) for b in buses]
    matrices = {k: config_matrix(rules, buses, k) for k in K_GRID}
    names = matrices[K_GRID[0]][1]
    bars = {shape: shape_day_means(shape, counts["n_daylight_steps"]) for shape in shapes}
    per_sigma = {}
    for sigma_key, condition in sorted(conditions.items()):
        spec = (specs or {}).get(condition) or noise_spec(condition)
        bundle = thresholds[sigma_key]
        sigma_tot = float(spec["sigma_tot"])
        tally = {shape: {k: np.zeros(len(grid), dtype=int) for k in K_GRID} for shape in shapes}
        for index, ratio in enumerate(grid):
            amplitude = float(ratio) * sigma_tot
            rng = control_rng(code, condition, CONTROL2_FA, index)
            for _ in range(int(replicates)):
                draws = draw_replicate(rng, spec, counts["n_daylight_valid"],
                                       counts["n_night_valid"], len(buses), False)  # fmt: skip
                signs = rng.integers(0, 2, size=len(buses)).astype(float) * 2.0 - 1.0
                for shape in shapes:
                    shift = amplitude * signs[None, :] * bars[shape][:, None]
                    k_hat = replicate_statistics(draws, amplitude_day=shift)["k"]
                    for k in K_GRID:
                        mask, _ = matrices[k]
                        threshold = float(bundle[f"K_{k}"]["contrast"]["high"])
                        tally[shape][k][index] += int(family_alarm(k_hat, mask, threshold).sum())
        trials = int(replicates) * len(names)
        zero = next((i for i, r in enumerate(grid) if float(r) == 0.0), None)  # the A = 0 point
        per_shape = {}
        for shape in shapes:
            per_k = {}
            for k in K_GRID:
                rates = [int(c) / trials for c in tally[shape][k]]
                crossing = interpolate_crossing(
                    [float(r) * sigma_tot for r in grid], rates, FAMILY_ALPHA, "above",
                    sigma_tot,
                )  # fmt: skip
                baseline = (
                    rate_record(int(tally[shape][k][zero]), trials) if zero is not None else None
                )
                per_k[f"K_{k}"] = {
                    "z": float(bundle[f"K_{k}"]["z"]),
                    "threshold_pu": float(bundle[f"K_{k}"]["contrast"]["high"]),
                    "per_grid_point": {
                        f"{ratio:g}": {
                            "A_over_sigma_tot": float(ratio),
                            "A_pu": float(ratio) * sigma_tot,
                            **rate_record(int(tally[shape][k][i]), trials),
                        }
                        for i, ratio in enumerate(grid)
                    },
                    # the rate A*_fa must be read against (reading R-k): the floor's own
                    # false-alarm rate at this condition, K and sigma_tot, with no bias
                    "false_alarm_rate_at_A_0": baseline,
                    "A_star_fa": {
                        **crossing,
                        "rate_at_A_0": None if baseline is None else baseline["rate"],
                        "exceeds_target_at_A_0": (
                            None if baseline is None else bool(baseline["rate"] > FAMILY_ALPHA)
                        ),
                        "baseline_artefact": bool(
                            crossing["record"] == "<= 0.003 sigma"
                        ),
                        "read_against": "its own A = 0 rate (reading R-k): a crossing at or "
                                        "below the first positive grid point is a baseline "
                                        "artefact of that rate, not a measured "
                                        "tolerance",  # fmt: skip
                    },
                }
            per_shape[shape] = {"primary": shape == "square", "per_K": per_k}
        per_sigma[sigma_key] = {
            "condition": condition,
            "spec": spec,
            "sigma_tot": sigma_tot,
            "replicates_per_grid_point": int(replicates),
            "pooled_over_rules": len(names),
            "per_shape": per_shape,
        }
    return {
        "control": "2 (A*_fa)",
        "status": "primary and binding A* (s. 16, N-3)",
        "truth": "nominal (Delta == 0)",
        "sign": "random only: the adverse sign is defined by k (s. 10)",
        "grid_A_over_sigma_tot": list(grid),
        "target_rate": FAMILY_ALPHA,
        "hypothesis": HYPOTHESES["A_star"],
        "interval_label": "descriptive Wilson 95 % (s. 8, reading R-l)",
        "read_against_A_0": (
            "A*_fa must be read against its own A = 0 rate, which is the floor's family-wise "
            "false-alarm rate with no diurnal bias at all; it is emitted next to every A*_fa "
            "record. A crossing recorded at or below the first positive grid point "
            "(`<= 0.003 sigma`, flagged `baseline_artefact`) is an artefact of that A = 0 "
            "rate, not a measured tolerance of the method to diurnal bias (reading R-k)."
        ),
        "per_sigma_tot": per_sigma,
    }


def adverse_signs(truth_k) -> np.ndarray:
    """s. 10's adverse variant: g_b = -sign(k(e, b)) at every meter. A meter with k = 0 gets
    g_b = 0 and therefore no bias, which is what the definition says."""
    return -np.sign(np.asarray(truth_k, dtype=float))


def control2_cov_network(code: str, buses, rules: dict, counts: dict, thresholds: dict,
                         truth_contrast, truth_k, lines, downstream: dict, *,
                         replicates: int = A_STAR_COV_REPLICATES, grid=A_OVER_SIGMA,
                         shapes=A_STAR_SHAPES, signs=A_STAR_SIGNS,
                         conditions=A_STAR_CONDITIONS,
                         specs: dict | None = None) -> dict:  # fmt: skip
    """A*_cov (s. 10 control 2): the detection rate over the W6 (cable, rule) pairs whose
    configuration intersects downstream(l), per grid point, shape, sign variant and K.

    `truth_contrast` is [cables, days, meters], the stored per-day daylight-minus-night means
    on the simulator's day axis; `truth_k` is [cables, meters], the mean over days, which
    fixes the adverse sign. One measurement realisation per replicate is shared by every pair
    (reading R-l). Under the alarm-on-|k| rule a large bias raises alarms, so a crossing may
    be "not reached" (s. 10); both sign variants are reported.
    """
    buses = [int(b) for b in buses]
    lines = [int(line) for line in lines]
    truth_contrast = np.asarray(truth_contrast, dtype=float)
    truth_k = np.asarray(truth_k, dtype=float)
    if truth_contrast.shape[0] != len(lines) or truth_contrast.shape[2] != len(buses):
        raise ValueError(
            f"the truth contrast is {truth_contrast.shape}, expected "
            f"({len(lines)}, {counts['simulated_days']}, {len(buses)})"
        )
    matrices = {k: config_matrix(rules, buses, k) for k in K_GRID}
    names = matrices[K_GRID[0]][1]
    bars = {shape: shape_day_means(shape, counts["n_daylight_steps"]) for shape in shapes}
    adverse = adverse_signs(truth_k)

    population = {}
    for k in K_GRID:
        pairs = np.zeros((len(lines), len(names)), dtype=bool)
        for row, line in enumerate(lines):
            below = set(int(b) for b in downstream[int(line)])
            for column, name in enumerate(names):
                pairs[row, column] = bool(set(configuration(rules[name], k)) & below)
        population[k] = pairs

    per_sigma = {}
    for sigma_key, condition in sorted(conditions.items()):
        spec = (specs or {}).get(condition) or noise_spec(condition)
        bundle = thresholds[sigma_key]
        sigma_tot = float(spec["sigma_tot"])
        tally = {(shape, sign, k): np.zeros(len(grid), dtype=int)
                 for shape in shapes for sign in signs for k in K_GRID}  # fmt: skip
        for index, ratio in enumerate(grid):
            amplitude = float(ratio) * sigma_tot
            rng = control_rng(code, condition, CONTROL2_COV, index)
            for _ in range(int(replicates)):
                draws = draw_replicate(rng, spec, counts["n_daylight_valid"],
                                       counts["n_night_valid"], len(buses), False)  # fmt: skip
                random_sign = rng.integers(0, 2, size=len(buses)).astype(float) * 2.0 - 1.0
                base = survival_mean(
                    truth_contrast + (draws["day"] - draws["night"]), draws["survives"]
                )
                weights = {
                    shape: survival_mean(
                        np.broadcast_to(bars[shape][:, None], draws["survives"].shape),
                        draws["survives"],
                    )
                    for shape in shapes
                }
                for shape in shapes:
                    carrier = np.nan_to_num(weights[shape], nan=0.0)
                    for sign in signs:
                        gain = random_sign[None, :] if sign == "random" else adverse
                        k_hat = base + amplitude * gain * carrier[None, :]
                        for k in K_GRID:
                            mask, _ = matrices[k]
                            threshold = float(bundle[f"K_{k}"]["contrast"]["high"])
                            alarms = family_alarm(k_hat, mask, threshold)
                            tally[(shape, sign, k)][index] += int(
                                (alarms & population[k]).sum()
                            )
        per_shape = {}
        for shape in shapes:
            per_sign = {}
            for sign in signs:
                per_k = {}
                for k in K_GRID:
                    trials = int(population[k].sum()) * int(replicates)
                    counts_grid = tally[(shape, sign, k)]
                    rates = [int(c) / trials if trials else float("nan") for c in counts_grid]
                    baseline = rates[0] if grid and float(grid[0]) == 0.0 else float("nan")
                    per_k[f"K_{k}"] = {
                        "z": float(bundle[f"K_{k}"]["z"]),
                        "threshold_pu": float(bundle[f"K_{k}"]["contrast"]["high"]),
                        "pairs_in_population": int(population[k].sum()),
                        "coverage_at_A_0": baseline,
                        "target_coverage": COV_HALVING * baseline,
                        "per_grid_point": {
                            f"{ratio:g}": {
                                "A_over_sigma_tot": float(ratio),
                                "A_pu": float(ratio) * sigma_tot,
                                **rate_record(int(counts_grid[i]), trials),
                            }
                            for i, ratio in enumerate(grid)
                        },
                        "A_star_cov": interpolate_crossing(
                            [float(r) * sigma_tot for r in grid], rates,
                            COV_HALVING * baseline, "below", sigma_tot,
                        ),  # fmt: skip
                    }
                per_sign[sign] = {"primary": sign == "random", "per_K": per_k}
            per_shape[shape] = {"primary": shape == "square", "per_sign": per_sign}
        per_sigma[sigma_key] = {
            "condition": condition,
            "spec": spec,
            "sigma_tot": sigma_tot,
            "replicates_per_grid_point": int(replicates),
            "cables": len(lines),
            "rules": len(names),
            "per_shape": per_shape,
        }
    return {
        "control": "2 (A*_cov)",
        "status": "reported, not binding; A*_fa is the binding A* (s. 16, N-3)",
        "population": "all W6 (cable, rule) pairs whose configuration intersects "
                      "downstream(l) (s. 10)",
        "grid_A_over_sigma_tot": list(grid),
        "note": "under the alarm-on-|k| rule a large bias raises alarms, so A*_cov may be "
                "`not reached` (s. 10); it is reported for both sign variants",
        "interval_label": "descriptive Wilson 95 % (s. 8, reading R-l)",
        "per_sigma_tot": per_sigma,
    }  # fmt: skip


# --- s. 10 control 3: permuted day/night labels --------------------------------------------


def permute_labels(daylight, rng) -> np.ndarray:
    """s. 10 control 3: one day's daylight/night labels permuted with the counts preserved
    (reading R-p). The permutation is over all the day's steps."""
    mask = np.asarray(daylight, dtype=bool)
    if mask.ndim != 1:
        raise ValueError(f"one day's label mask is 1-D, got {mask.shape}")
    out = np.zeros(mask.size, dtype=bool)
    out[rng.permutation(mask.size)[: int(mask.sum())]] = True
    return out


def permuted_contrast(delta, daylight, valid, rng, permutations: int = PERMUTATIONS) -> dict:
    """s. 10 control 3: k recomputed from `permutations` label permutations.

    `delta` is [days, steps, buses], `daylight` and `valid` [days, steps]. Each permutation
    preserves the day's daylight count, re-intersects validity and drops a day left without a
    valid daylight or night step (reading R-p). k_perm is the mean over the surviving days.
    """
    delta = np.asarray(delta, dtype=float)
    daylight = np.asarray(daylight, dtype=bool)
    valid = np.asarray(valid, dtype=bool)
    if delta.ndim != 3 or daylight.shape != delta.shape[:2] or valid.shape != delta.shape[:2]:
        raise ValueError(
            f"shapes do not match: delta {delta.shape}, daylight {daylight.shape}, "
            f"valid {valid.shape}"
        )
    clean = np.where(valid[:, :, None], np.nan_to_num(delta, nan=0.0), 0.0)
    out = np.empty((int(permutations), delta.shape[2]), dtype=float)
    dropped, label_counts = [], []
    for replicate in range(int(permutations)):
        labels = np.stack([permute_labels(daylight[d], rng) for d in range(delta.shape[0])])
        label_counts.append(int(labels.sum()))
        day_mask = labels & valid
        night_mask = (~labels) & valid
        day_n, night_n = day_mask.sum(axis=1), night_mask.sum(axis=1)
        usable = (day_n > 0) & (night_n > 0)
        dropped.append(int((~usable).sum()))
        day_mean = (clean * day_mask[:, :, None]).sum(axis=1) / np.maximum(day_n, 1)[:, None]
        night_mean = (
            (clean * night_mask[:, :, None]).sum(axis=1) / np.maximum(night_n, 1)[:, None]
        )
        out[replicate] = (day_mean - night_mean)[usable].mean(axis=0)
    return {
        "k_perm": out,
        "permutations": int(permutations),
        "days_dropped_per_permutation": dropped,
        "daylight_labels_per_permutation": label_counts,
        "daylight_labels_observed": int(daylight.sum()),
        "counts_preserved": bool(all(c == int(daylight.sum()) for c in label_counts)),
        "reading": "R-p",
    }


def control3_distribution(k_perm, buses, thresholds: dict, k_all: int) -> dict:
    """s. 10 control 3's report: the max over buses of |mean k_perm| per permutation, its
    distribution, and the exceedance of z_{K_all} * F_C,real at both co-primary sigma."""
    k_perm = np.asarray(k_perm, dtype=float)
    peaks = np.abs(k_perm).max(axis=1)
    worst = int(np.argmax(peaks))
    per_sigma = {}
    for sigma in SIGMA_CO_PRIMARY:
        high = float(thresholds[f"{sigma:g}"][f"K_{int(k_all)}"]["contrast"]["high"])
        per_sigma[f"{sigma:g}"] = {
            "z_K_all_F_C_real": high,
            "K_all": int(k_all),
            "exceeding_permutations": rate_record(int((peaks >= high).sum()), peaks.size),
        }
    return {
        "permutations": int(peaks.size),
        "max_abs_mean_k_perm_pu": {
            "mean": floor_label(float(peaks.mean())),
            "sd": float(peaks.std(ddof=0)),
            "min": floor_label(float(peaks.min())),
            "median": floor_label(float(np.median(peaks))),
            "p95": floor_label(float(np.quantile(peaks, 0.95))),
            "max": floor_label(float(peaks.max())),
            "argmax_permutation": worst,
            "argmax_bus": int(list(buses)[int(np.argmax(np.abs(k_perm[worst])))]),
        },
        "per_bus_mean_over_permutations_pu": np.abs(k_perm).mean(axis=0),
        "expectation": "about 0: control 3 is a pipeline sanity check (s. 10)",
        "per_sigma_tot": per_sigma,
    }


def control3_network(code: str, inputs: dict, *, permutations: int = PERMUTATIONS) -> dict:
    """s. 10 control 3 at one network's `stress.local_line` cable, from the read-only caches.

    This is the one control that reads per-step data, so s. 10 restricts it to the registered
    and the four held-out cables. The loading path is `w5_network`'s, unchanged.
    """
    from gridpulse import dual_study as ds
    from gridpulse import fullstate, grid, grid_study
    from gridpulse import stress as st

    facts = inputs["networks"][code]
    days = [int(d) for d in facts["days"]["scored"]]
    retained = [int(d) for d in facts["days"]["retention_primary"]["retained"]]
    line = int(facts["local_line"])
    buses = [int(b) for b in facts["lv_buses"]]

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    available = grid_study.daily_arrays(grid.absolute_profiles(net))["sgen_p_mw"]
    if [int(b) for b in fullstate.lv_buses(net)] != buses:
        raise RuntimeError(f"{code}: the cache bus order differs from Stage 1's LV buses")
    truth = st.load(ps.ROBUST_CACHE, code, ps.CACHED_TRUTH, days)
    nominal = fullstate.load_states(ps.NOMINAL_CACHE, code, ps.NOMINAL_TRUTH, days)

    deltas, daylight, valid = [], [], []
    for day in retained:
        left = np.asarray(truth[day]["vm"], dtype=np.float64)[:, ps.LEVEL, :]
        right = np.asarray(nominal[day]["vm"], dtype=np.float64)[:, ps.LEVEL, :]
        deltas.append(left - right)
        daylight.append(available[day].sum(axis=1) > 0)
        valid.append(np.isfinite(left).all(axis=1) & np.isfinite(right).all(axis=1))
    rng = control_rng(code, NO_CONDITION, CONTROL3, 0)
    permuted = permuted_contrast(
        np.stack(deltas), np.stack(daylight), np.stack(valid), rng, permutations
    )
    distribution = control3_distribution(
        permuted["k_perm"], buses, facts["thresholds"]["mean"], facts["K_all"]
    )
    return {
        "network": code,
        "line": line,
        "role": facts["role"],
        "days_permuted": len(retained),
        "truth_leg": f"stress.load(outputs/robust_study/fullstate_cache, {code}, line_local)",
        "nominal_leg": (
            f"fullstate.load_states(outputs/sense_study/fullstate_cache, {code}, nominal)"
        ),
        "labels": {name: permuted[name] for name in
                   ("permutations", "daylight_labels_observed", "counts_preserved",
                    "days_dropped_per_permutation")},  # fmt: skip
        "buses": buses,
        **distribution,
    }  # fmt: skip


# --- s. 10 controls 4 and 5 ----------------------------------------------------------------


def control4_network(entries: dict, downstream: dict, level_low: float,
                     contrast_high: float) -> dict:  # fmt: skip
    """s. 10 control 4: the topology-luck baseline of R2. For every W6 cable, the Jaccard of
    S_detect(l) against downstream(l') for every *other* candidate l' of the same network."""
    lines = sorted(int(line) for line in entries)
    per_cable, best_is_own, pooled_hits, pooled_pairs = {}, 0, 0, 0
    for line in lines:
        entry = entries[line]
        verdict = r2_cable(entry["m"], entry["night"], entry["k"], entry["buses"],
                           entry["downstream"], level_low, contrast_high)  # fmt: skip
        detect = set(verdict["S_detect"])
        own = jaccard(detect, set(int(b) for b in downstream[line]))
        others = {
            other: jaccard(detect, set(int(b) for b in downstream[other]))
            for other in sorted(downstream)
            if int(other) != line
        }
        values = np.array([v for v in others.values() if math.isfinite(v)], dtype=float)
        above = sorted(other for other, v in others.items()
                       if math.isfinite(v) and v >= R2_JACCARD)  # fmt: skip
        pooled_hits += len(above)
        pooled_pairs += int(values.size)
        if math.isfinite(own) and (values.size == 0 or own > values.max()):
            best_is_own += 1
        per_cable[str(line)] = {
            "S_detect": verdict["S_detect"],
            "evaluable": verdict["evaluable"],
            "jaccard_own_downstream": own,
            "other_candidates": int(values.size),
            "jaccard_other_max": float(values.max()) if values.size else None,
            "jaccard_other_mean": float(values.mean()) if values.size else None,
            "others_at_or_above_0.8": above,
            "own_is_the_best_match": bool(
                math.isfinite(own) and (values.size == 0 or own > values.max())
            ),
        }
    return {
        "control": "4",
        "statement": "s. 10: the topology-luck baseline of R2",
        "cables": len(lines),
        "jaccard_threshold": R2_JACCARD,
        "pooled_other_pairs_at_or_above_0.8": rate_record(pooled_hits, pooled_pairs),
        "cables_whose_own_downstream_is_the_best_match": best_is_own,
        "per_cable": per_cable,
    }


def control5_network(entries: dict, rules: dict, thresholds: dict) -> dict:
    """s. 10 control 5: the coverage of `random_0...19` against the 5 named rules of s. 8.

    The rules are frozen in Phase 6, so this is a baseline and not a choice (s. 10).
    """
    per_k = {}
    for k in K_GRID:
        low = float(thresholds[f"K_{k}"]["contrast"]["low"])
        high = float(thresholds[f"K_{k}"]["contrast"]["high"])
        families = {}
        for family in ("named", "random"):
            wanted = [n for n in RULE_FAMILIES[family] if n in rules]
            pairs = []
            for _line, entry in sorted(entries.items()):
                below = set(entry["downstream"])
                for name in wanted:
                    config = configuration(rules[name], k)
                    value = c_meter(entry["k"], entry["buses"], config)
                    pairs.append((q1.band(abs(value), low, high), bool(set(config) & below)))
            families[family] = {"rules": len(wanted), **coverage_table(pairs)}
        named = families["named"]["coverage"]
        random = families["random"]["coverage"]
        per_k[f"K_{k}"] = {
            "z": float(thresholds[f"K_{k}"]["z"]),
            "band_low": low,
            "band_high": high,
            "families": families,
            "random_minus_named": (
                None if named["rate"] is None or random["rate"] is None
                else random["rate"] - named["rate"]
            ),  # fmt: skip
            "intersection_ceiling": {
                family: families[family]["intersection_coverage"]["rate"]
                for family in families
            },
        }
    return {
        "control": "5",
        "statement": "s. 10: the coverage of random_0...19 against the 5 named rules; the "
                     "rules are frozen, so this is a baseline, not a choice",
        "per_K": per_k,
    }  # fmt: skip


# --- s. 10: the controls block of Stage 3 --------------------------------------------------


def control_network_inputs(code: str, inputs: dict, loaded: dict) -> dict:
    """The per-network inputs every s. 10 control shares, from Stage 1's `inputs` and Stage 3's
    loaded artefacts.

    `controls` and every `stage3 --part control*` invocation go through this one function, so a
    control is handed the same arrays, counts and thresholds whichever way it is run.
    """
    facts = inputs["networks"][code]
    buses = [int(b) for b in facts["lv_buses"]]
    rules = {name: [int(b) for b in bs]
             for name, bs in facts["placement_rules"]["buses"].items()}  # fmt: skip
    downstream = {int(line): [int(b) for b in below]
                  for line, below in facts["downstream"].items()}  # fmt: skip
    retained = [int(d) for d in facts["days"]["retention_primary"]["retained"]]
    thresholds = facts["thresholds"]["mean"]
    registered = int(facts["local_line"])

    w6 = {key[4]: value for key, value in loaded.items()
          if key[0] == code and key[1] == "W6"}  # fmt: skip
    if registered not in w6:
        raise RuntimeError(f"{code}: the registered cable {registered} has no W6 artefact")
    lines = sorted(w6)
    counts = meter_days(
        [w6[registered]["arrays"], *(w6[line]["arrays"] for line in lines
                                     if line != registered)],  # fmt: skip
        retained,
    )
    rows = counts["rows"]
    truth_contrast = np.stack([
        np.asarray(w6[line]["arrays"]["dmean_daylight"], dtype=float)[rows]
        - np.asarray(w6[line]["arrays"]["dmean_night"], dtype=float)[rows]
        for line in lines
    ])
    truth_k = np.stack([
        np.asarray(w6[line]["stats"]["k"]["mean"], dtype=float) for line in lines
    ])
    entries = {
        line: _rule_inputs(buses, downstream[line], w6[line]["stats"], "mean")
        for line in lines
    }
    return {
        "code": code, "facts": facts, "buses": buses, "rules": rules,
        "downstream": downstream, "thresholds": thresholds, "registered": registered,
        "lines": lines, "counts": counts, "truth_contrast": truth_contrast,
        "truth_k": truth_k, "entries": entries,
        "per_network": {"cables": len(lines), "day_axis": counts["simulated_days"]},
    }  # fmt: skip


def control1_block(net: dict, *, replicates: int = CONTROL1_REPLICATES,
                   conditions=CONTROL_CONDITIONS, specs: dict | None = None) -> dict:  # fmt: skip
    """s. 10 control 1 for one `control_network_inputs` network."""
    return control1_network(
        net["code"], net["buses"], net["rules"], net["counts"], net["thresholds"],
        replicates=replicates, conditions=conditions, specs=specs,
    )  # fmt: skip


def control2_fa_block(net: dict, *, replicates: int = A_STAR_FA_REPLICATES,
                      conditions=A_STAR_CONDITIONS, grid=A_OVER_SIGMA,
                      specs: dict | None = None) -> dict:  # fmt: skip
    """A*_fa for one `control_network_inputs` network, over `conditions` (one sigma_tot key per
    entry). Each sigma's replicates are drawn from their own seed, so restricting `conditions`
    to one key leaves that key's numbers bit-identical (s. 10's seed is per condition)."""
    return control2_fa_network(
        net["code"], net["buses"], net["rules"], net["counts"], net["thresholds"],
        replicates=replicates, conditions=conditions, grid=grid, specs=specs,
    )  # fmt: skip


def control2_cov_block(net: dict, *, replicates: int = A_STAR_COV_REPLICATES,
                       conditions=A_STAR_CONDITIONS, grid=A_OVER_SIGMA,
                       specs: dict | None = None) -> dict:  # fmt: skip
    """A*_cov for one `control_network_inputs` network, over `conditions` as above."""
    return control2_cov_network(
        net["code"], net["buses"], net["rules"], net["counts"], net["thresholds"],
        net["truth_contrast"], net["truth_k"], net["lines"], net["downstream"],
        replicates=replicates, conditions=conditions, grid=grid, specs=specs,
    )  # fmt: skip


def control4_block(net: dict) -> dict:
    """s. 10 control 4 at both co-primary sigma for one `control_network_inputs` network."""
    thresholds, facts = net["thresholds"], net["facts"]
    return {
        f"{sigma:g}": control4_network(
            net["entries"], net["downstream"],
            float(thresholds[f"{sigma:g}"][f"K_{facts['K_all']}"]["level"]["low"]),
            float(thresholds[f"{sigma:g}"][f"K_{facts['K_all']}"]["contrast"]["high"]),
        )
        for sigma in SIGMA_CO_PRIMARY
    }  # fmt: skip


def control5_block(net: dict) -> dict:
    """s. 10 control 5 at both co-primary sigma for one `control_network_inputs` network."""
    return {
        f"{sigma:g}": control5_network(net["entries"], net["rules"],
                                      net["thresholds"][f"{sigma:g}"])  # fmt: skip
        for sigma in SIGMA_CO_PRIMARY
    }


def controls_envelope(specs: dict, per_network: dict, control1: dict, control2_fa: dict,
                      control2_cov: dict, control3: dict | None, control4: dict,
                      control5: dict, *, include_control3: bool) -> dict:  # fmt: skip
    """The s. 10 controls block itself, assembled from its per-network pieces.

    `controls` and `merge_stage3_parts` both end here, which is what makes the merged results
    file structurally identical to the monolithic `stage3`'s.
    """
    return {
        "section": "registration s. 10, all zero-flow except control 3's cache reads",
        "noise_model": {
            "leg": "the measured (truth) leg only; the comparison is measurement against "
                   "model (s. 10, F-5)",
            "per_day_means": "simulated analytically on the stored per-day means, which s. 16 "
                             "records as exact for the registered Gaussian, i.i.d.-per-reading "
                             "model",
            "mandatory_sensitivity": "the sqrt(2) measurement-against-measurement variant, "
                                     "with both legs noisy (reading R-m)",
            "conditions": specs,
            "seed": "np.random.default_rng(np.random.SeedSequence([20261023, "
                    "sn._stable_int(network), sn._stable_int(condition), "
                    "sn._stable_int(control), index]))",
            "seed_root": SEED_ROOT,
        },
        "readings": CONTROL_READINGS,
        "per_network": per_network,
        "control_1": control1,
        "control_2_A_star_fa": control2_fa,
        "control_2_A_star_cov": control2_cov,
        "control_3": control3,
        "control_3_note": (
            "s. 10: control 3 uses cached per-step data, so it runs at the registered cables "
            "and the four held-out cables only"
            if include_control3
            else "not computed in this call"
        ),
        "control_4": control4,
        "control_5": control5,
        "R7": r7_verdict(control1),
    }  # fmt: skip


def controls(inputs: dict, loaded: dict, *, conditions=CONTROL_CONDITIONS,
             control1_replicates: int = CONTROL1_REPLICATES,
             fa_replicates: int = A_STAR_FA_REPLICATES,
             cov_replicates: int = A_STAR_COV_REPLICATES,
             permutations: int = PERMUTATIONS, include_control3: bool = True) -> dict:  # fmt: skip
    """s. 10 controls 1-5 and the A* amplitude sweep, over Stage 3's loaded artefacts.

    `inputs` is Stage 1's `inputs` mapping and `loaded` Stage 3's per-spec bundle, keyed by
    (network, work item, error, factor, line) with `stats` and `arrays`. Everything here is
    zero-flow except control 3's cache reads, which s. 10 allows at the registered and the
    four held-out cables only.

    This is the monolithic path. `stage3 --part control*` runs the same blocks one at a time
    and `merge_stage3_parts` reassembles them; both end in `controls_envelope`.
    """
    specs = {condition: noise_spec(condition) for condition in conditions}
    per_network, control1, control2_fa, control2_cov, control4, control5 = {}, {}, {}, {}, {}, {}
    for code in SWEEP_NETWORKS:
        net = control_network_inputs(code, inputs, loaded)
        control1[code] = control1_block(
            net, replicates=control1_replicates, conditions=conditions, specs=specs,
        )  # fmt: skip
        control2_fa[code] = control2_fa_block(net, replicates=fa_replicates, specs=specs)
        control2_cov[code] = control2_cov_block(net, replicates=cov_replicates, specs=specs)
        control4[code] = control4_block(net)
        control5[code] = control5_block(net)
        per_network[code] = net["per_network"]

    control3 = None
    if include_control3:
        control3 = {
            code: control3_network(code, inputs, permutations=permutations)
            for code in ALL_NETWORKS
        }
    return controls_envelope(
        specs, per_network, control1, control2_fa, control2_cov, control3, control4, control5,
        include_control3=include_control3,
    )  # fmt: skip


SELFTEST_RULES = {  # synthetic placements for `controls-selftest`: no real network is read
    "rule_a": [0, 1, 2, 3],
    "rule_b": [4, 5, 6, 7],
    "rule_c": [0, 2, 4, 6],
    "rule_d": [7, 5, 3, 1],
}
SELFTEST_BUSES = tuple(range(8))
SELFTEST_DAYS = 120  # retained days
SELFTEST_DAYLIGHT = 40  # valid daylight steps per day
SELFTEST_NIGHT = STEPS - SELFTEST_DAYLIGHT  # valid night steps per day
SELFTEST_TOLERANCE = 0.02  # |rate - alpha|, against a 0.0049 standard error at 2,000 draws


def selftest_inputs(days: int = SELFTEST_DAYS, daylight: int = SELFTEST_DAYLIGHT) -> dict:
    """The synthetic network of `controls-selftest`: known, constant per-day counts, synthetic
    placements and thresholds computed from those counts. No real data is touched."""
    scored = list(range(days))
    arrays = {
        "day_index": np.asarray(scored, dtype=np.int32),
        "bus_index": np.asarray(SELFTEST_BUSES, dtype=np.int32),
        "n_daylight_valid": np.full(days, daylight, dtype=np.int16),
        "n_night_valid": np.full(days, STEPS - daylight, dtype=np.int16),
        "n_daylight_steps": np.full(days, daylight, dtype=np.int16),
        "n_night_steps": np.full(days, STEPS - daylight, dtype=np.int16),
        "dmean_daylight": np.zeros((days, len(SELFTEST_BUSES)), dtype=np.float32),
        "dmean_night": np.zeros((days, len(SELFTEST_BUSES)), dtype=np.float32),
        "failed_truth": np.zeros(days, dtype=np.int16),
        "nan_nominal": np.zeros(days, dtype=np.int16),
    }
    retention = {
        "D_ret": days,
        "D_eff": (1.0 - REMOTE_MISSING) * days,
        "n_day_median": float(daylight),
        "n_night_median": float(STEPS - daylight),
    }
    return {
        "network": "synthetic-selftest",
        "buses": list(SELFTEST_BUSES),
        "rules": {name: list(buses) for name, buses in SELFTEST_RULES.items()},
        "arrays": arrays,
        "retained": scored,
        "retention": retention,
        "thresholds": threshold_grid(retention, len(SELFTEST_BUSES))["mean"],
    }


def controls_selftest(replicates: int = CONTROL1_REPLICATES,
                      tolerance: float = SELFTEST_TOLERANCE,
                      conditions=CONTROL_CONDITIONS) -> dict:  # fmt: skip
    """The `controls-selftest` subcommand: control 1 on a synthetic network with known counts.

    With truth = nominal and i.i.d. noise at exactly the counts the floor is built from, the
    family-wise rate must come out at about the registered alpha = 0.05. The arm checked is
    the one whose floor is matched to the condition's *random* noise: z_K * F_C,real for the
    `realistic`-type conditions, where sigma_v is the whole sigma_tot, and z_K * F_C,matched
    for `biased_meters_matched`, whose 0.2 sigma_tot floor is exactly its sigma_v = 0.002
    (s. 10 asks for that arm for that condition). Its z_K * F_C,real rate is checked to stay
    at or below alpha instead: the static bias cancels in k, which is the s. 14 headline
    advantage, so that arm is conservative by construction and is not "about alpha".

    In every checked arm the sqrt(2) variant must be *above* the measured-leg rate, which is
    the s. 10 mandatory sensitivity acting as its own check. The expected residual inflation
    is sqrt(D_ret / (D_ret - 1)): the 1-day delay removes a day the floor's D_eff still
    counts.

    It reads no cache, no network, no sweep artefact and no result file. Only the registered
    noise conditions come from `gridpulse.noise_study`, which is source, not data.
    """
    setup = selftest_inputs()
    counts = meter_days([setup["arrays"]], setup["retained"])
    report = control1_network(
        setup["network"], setup["buses"], setup["rules"], counts, setup["thresholds"],
        replicates=replicates, conditions=conditions,
    )  # fmt: skip

    checks, failures = [], []
    for condition, entry in sorted(report["per_condition"].items()):
        matched = condition == MATCHED_CONDITION
        arm = "F_C_matched" if matched else "F_C_real"
        variants = entry["variants"]

        def pooled(variant: str, which: str, step: int, arms=variants) -> float:
            return arms[variant]["arms"][which][f"K_{step}"]["pooled_over_rules"]["rate"]

        for k in K_GRID:
            measured = pooled("measured_leg", arm, k)
            both = pooled("sqrt2", arm, k)
            check = {
                "condition": condition,
                "K": k,
                "arm": arm,
                "arm_reason": (
                    "0.2 sigma_tot is exactly this condition's sigma_v = 0.002 (s. 10)"
                    if matched
                    else "sigma_v is the whole sigma_tot of this condition"
                ),
                "measured_leg_rate": measured,
                "sqrt2_rate": both,
                "alpha": FAMILY_ALPHA,
                "abs_deviation": abs(measured - FAMILY_ALPHA),
                "tolerance": float(tolerance),
                "about_alpha": bool(abs(measured - FAMILY_ALPHA) <= float(tolerance)),
                "sqrt2_inflates": bool(both > measured),
            }
            if matched:  # the bias cancels in k: the F_C,real arm must stay conservative
                check["F_C_real_rate"] = pooled("measured_leg", "F_C_real", k)
                check["bias_cancellation_keeps_F_C_real_at_or_below_alpha"] = bool(
                    check["F_C_real_rate"] <= FAMILY_ALPHA
                )
            checks.append(check)
            if not all(v for key, v in check.items() if isinstance(v, bool)):
                failures.append(check)
    return {
        "selftest": "control 1 on a synthetic network with known counts (s. 10)",
        "touches_real_data": False,
        "sources": "synthetic counts, synthetic placements; the noise conditions come from "
                   "gridpulse.noise_study.CONDITIONS (source, not data)",
        "network": setup["network"],
        "buses": len(setup["buses"]),
        "rules": len(setup["rules"]),
        "retained_days": setup["retention"]["D_ret"],
        "simulated_days": counts["simulated_days"],
        "daylight_steps_per_day": SELFTEST_DAYLIGHT,
        "night_steps_per_day": SELFTEST_NIGHT,
        "replicates": int(replicates),
        "expected_inflation_from_the_1_day_delay": math.sqrt(
            setup["retention"]["D_ret"] / (setup["retention"]["D_ret"] - 1)
        ),
        "checks": checks,
        "failures": failures,
        "holds": not failures,
        "control_1": report,
    }  # fmt: skip


# --- Stage 3 -------------------------------------------------------------------------------


def stage3_context(inputs_path: Path = INPUTS_FILE, root: Path = ps.SWEEP,
                   git=ps._git) -> dict:  # fmt: skip
    """Stage 3's refusal checks and its loaded artefacts, shared by `stage3` and every part.

    It refuses unless the registration is committed, Stage 1's file exists, the derived
    manifest shows all 99 runs verified and the s. 7 failed-flow limits hold. Nothing is
    written here, so a refusal leaves no file behind.
    """
    registration = require_committed_registration(git)
    stage1_file = load_stage1(inputs_path)
    inputs = stage1_file["inputs"]
    days = ps.scored_days()
    key = ps.physics_key()
    specs = ps.expected_specs()
    manifest = sweep_barrier(root, key, specs, days)

    # load every artefact once, reduce it, and collect the s. 7 failure accounting
    loaded, accounting = {}, []
    for spec in specs:
        facts = inputs["networks"][spec.network]
        retained = [int(d) for d in facts["days"]["retention_primary"]["retained"]]
        sensitivity = [
            int(d) for d in facts["days"]["retention_sensitivity_min_8_daylight"]["retained"]
        ]
        path = ps.artefact_path(spec, key, root)
        with np.load(path) as data:
            arrays = {name: np.array(data[name]) for name in ps.ARRAY_SPEC}
        if [int(b) for b in arrays["bus_index"]] != [int(b) for b in facts["lv_buses"]]:
            raise RuntimeError(f"{path}: the artefact's bus order differs from Stage 1's")
        stats = run_statistics(arrays, retained)
        loaded[(spec.network, spec.work_item, spec.error, spec.factor, spec.line)] = {
            "spec": spec, "stats": stats, "arrays": arrays,
            "sensitivity": run_statistics(arrays, sensitivity),
        }  # fmt: skip
        accounting.append({
            "path": ps._reported_path(path),
            "failed_total": stats["failed_truth_total"],
            "failed_retained": stats["failed_truth_retained"],
            "solves_retained": len(retained) * STEPS,
        })
    failures = failed_flow_check(accounting, len(specs) * len(days) * STEPS)
    return {
        "registration": registration,
        "stage1_file": stage1_file,
        "inputs": inputs,
        "days": days,
        "physics_key": key,
        "specs": specs,
        "manifest": manifest,
        "loaded": loaded,
        "failed_flows": failures,
    }


def stage3_core(context: dict) -> dict:
    """Everything Stage 3 writes except the s. 10 controls block: the s. 8-s. 9 statistics,
    W1, W2, W5, W8 and W9, with the barrier record `stage3` reports.

    `context` is a `stage3_context` result. This is the `core` part of `stage3 --part`, and
    `stage3` itself calls it, so the two cannot drift apart.
    """
    inputs = context["inputs"]
    loaded = context["loaded"]
    registration = context["registration"]
    stage1_file = context["stage1_file"]
    manifest = context["manifest"]
    failures = context["failed_flows"]

    networks = {}
    for code in SWEEP_NETWORKS:
        facts = inputs["networks"][code]
        buses = [int(b) for b in facts["lv_buses"]]
        distance = {int(b): float(v) for b, v in facts["resistance_distance_ohm"].items()}
        rules = {name: [int(b) for b in bs]
                 for name, bs in facts["placement_rules"]["buses"].items()}  # fmt: skip
        cable = int(facts["local_line"])
        downstream = {int(line): [int(b) for b in below]
                      for line, below in facts["downstream"].items()}  # fmt: skip

        w6 = {
            k[4]: v for k, v in loaded.items() if k[0] == code and k[1] == "W6"
        }
        entries = {
            line: _rule_inputs(buses, downstream[line], v["stats"], "mean")
            for line, v in w6.items()
        }
        entries_sensitivity = {
            line: _rule_inputs(buses, downstream[line], v["sensitivity"], "mean")
            for line, v in w6.items()
        }

        per_bus = {
            str(line): {
                "days_used": v["stats"]["days_used"],
                "days_dropped_no_valid_step": v["stats"]["days_dropped_no_valid_step"],
                "m": {w: v["stats"]["m"][w] for w in ("mean", "median")},
                "night": {w: v["stats"]["night"][w] for w in ("mean", "median")},
                "k": {w: v["stats"]["k"][w] for w in ("mean", "median")},
                "max_abs_k_pu": floor_label(float(np.abs(v["stats"]["k"]["mean"]).max())),
                "max_abs_m_pu": floor_label(float(np.abs(v["stats"]["m"]["mean"]).max())),
            }
            for line, v in sorted(w6.items())
        }

        coverage = {
            estimator: {
                f"{sigma:g}": coverage_block(
                    {
                        line: _rule_inputs(buses, downstream[line], v["stats"], estimator)
                        for line, v in w6.items()
                    },
                    rules,
                    facts["thresholds"][estimator][f"{sigma:g}"],
                    estimator,
                )
                for sigma in SIGMA_GRID
            }
            for estimator in ESTIMATORS
        }
        rules_block = {
            f"{sigma:g}": rule_block(
                entries, facts["cable_facts"], distance,
                facts["thresholds"]["mean"][f"{sigma:g}"][f"K_{facts['K_all']}"],
                "W6, every candidate cable (s. 9)",
            )  # fmt: skip
            for sigma in SIGMA_CO_PRIMARY
        }

        registered_entry = {
            "buses": buses,
            "downstream": downstream[cable],
            "mean": np.asarray(w6[cable]["stats"]["k"]["mean"], dtype=float),
            "median": np.asarray(w6[cable]["stats"]["k"]["median"], dtype=float),
        }
        w8 = w8_block(
            {
                **{k[3]: v["stats"] for k, v in loaded.items()
                   if k[0] == code and k[1] == "W8"},  # fmt: skip
                R_FACTOR: w6[cable]["stats"],
            },
            downstream[cable], buses, facts["thresholds"]["mean"],
        )  # fmt: skip
        w9 = w9_block(
            {k[3]: v["stats"] for k, v in loaded.items() if k[0] == code and k[1] == "W9"},
            w6[cable]["stats"], downstream[cable], buses,
        )  # fmt: skip

        sensitivity = {
            "retention": facts["days"]["retention_sensitivity_min_8_daylight"],
            "coverage": {
                f"{sigma:g}": coverage_block(
                    entries_sensitivity, rules,
                    facts["thresholds_sensitivity_min_8_daylight"]["mean"][f"{sigma:g}"],
                    "mean",
                )  # fmt: skip
                for sigma in SIGMA_CO_PRIMARY
            },
            "rules": {
                f"{sigma:g}": rule_block(
                    entries_sensitivity, facts["cable_facts"], distance,
                    facts["thresholds_sensitivity_min_8_daylight"]["mean"][f"{sigma:g}"][
                        f"K_{facts['K_all']}"
                    ],
                    "W6 under the >= 8-daylight retention set (s. 7)",
                )  # fmt: skip
                for sigma in SIGMA_CO_PRIMARY
            },
            "note": "the headline coverage and R1-R4 repeated under the s. 7 sensitivity "
                    "retention set",  # fmt: skip
        }

        networks[code] = {
            "network": code,
            "role": "sweep (W6, W8, W9)",
            "cables": len(w6),
            "registered_cable": cable,
            "per_bus": per_bus,
            "coverage": coverage,
            "headline": {
                "definition": "s. 14: sigma in {0.01, 0.005}, K = 2, all 25 rules, per network",
                "estimator": "mean (reading R-e)",
                "values": {
                    f"{sigma:g}": coverage["mean"][f"{sigma:g}"]["per_K"]["K_2"]["families"]["all"]
                    for sigma in SIGMA_CO_PRIMARY
                },
            },
            "rules": rules_block,
            "R6_identity": r6_identity(registered_entry, rules, facts["thresholds"]),
            "W1": w1_comparison(
                code, registered_entry, w6[cable]["stats"], line=cable, distance=distance,
                thresholds={
                    f"{sigma:g}": facts["thresholds"]["mean"][f"{sigma:g}"][
                        f"K_{facts['K_all']}"
                    ]
                    for sigma in SIGMA_CO_PRIMARY
                },
            ),
            "W2": w2_hits(code, downstream[cable], rules),
            "W8": w8,
            "W9": w9,
            "sensitivity": sensitivity,
        }

    held_out = {code: w5_network(code, inputs) for code in HELD_OUT_NETWORKS}
    r5_holds = all(entry["R5"]["holds"] for entry in held_out.values())

    return {
        "stage": "3 core (registration s. 8, s. 9, W1, W2, W5, W8, W9)",
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256,
                         "state": registration},  # fmt: skip
        "barriers": {
            "stage1_inputs": {"path": stage1_file["path"], "sha256": stage1_file["sha256"]},
            "sweep_manifest": {
                "physics_key": manifest["physics_key"],
                "expected_runs": manifest["expected_runs"],
                "present_runs": manifest["present_runs"],
                "complete": manifest["complete"],
            },
            "failed_flows": failures,
        },
        "readings": {
            "R-b": "a retained day is usable iff it has a valid daylight and a valid night "
                   "step; m, night and k average over the usable days",
            "R-c": f"the precision-floor label applies to |value| < {PRECISION_FLOOR_PU:g} p.u.",
            "R-d": "R1-R4 and R3s carry verdicts on the mean estimator only",
            "R-e": "the headline coverage is the mean estimator; the median is the s. 8 "
                   "robustness check",
            "R-f": "slope(f) = max over downstream of |k| / (f - 1)",
            "R-g": "the W9 R-only prediction is (g - 1) / 0.5",
            "R-s": "W1 evaluates R1, R3s and R4 at the registered cable on Q1's committed "
                   "per-bus arrays and on the sweep artefact's, and reports both verdicts "
                   "side by side with the maximum absolute difference between the arrays",
            **CONTROL_READINGS,
        },  # fmt: skip
        "hypotheses": HYPOTHESES,
        "networks": networks,
        "W5": {
            "label": "pre-registered held-out statistic, exploratory programme (s. 13 (i))",
            "networks": held_out,
            "R5": {
                "statement": "ratio = m(b*) / m_pred lies in [0.50, 0.90] in every one of the "
                             "four held-out networks",
                "per_network": {code: entry["R5"] for code, entry in held_out.items()},
                "holds": bool(r5_holds),
            },  # fmt: skip
            "consistency_check_note": (
                "R1, R2, R4 and R3s are consistency checks here, not tests; R6 is an identity "
                "(s. 9, s. 13 (i))"
            ),
        },
    }


def stage3_report(core: dict, controls_block: dict) -> dict:
    """Stage 3's results structure: the `core` block plus the s. 10 controls block.

    The monolithic `stage3` and `merge_stage3_parts` both assemble the file here, in this key
    order, so the merged file is the monolithic one.
    """
    return {
        **core,
        "controls": controls_block,
        "controls_note": (
            "registration s. 10 controls 1-5 and the A* amplitude sweep, all zero-flow except "
            "control 3's reads of the read-only caches"
        ),
        "R7": controls_block["R7"],
    }


def stage3(inputs_path: Path = INPUTS_FILE, results_path: Path = RESULTS_FILE,
           root: Path = ps.SWEEP, git=ps._git) -> dict:  # fmt: skip
    """Stage 3 (s. 12.5) in one command: every s. 8-s. 9 statistic, W1, W2, W5, W8, W9 and the
    s. 10 controls, written to `results_path`, refusing to overwrite.

    `stage3 --part` runs the same work in parts under the sandbox's per-command time limit;
    this monolithic path is kept and is the reference the parts are checked against.
    """
    context = stage3_context(inputs_path, root, git)
    report = stage3_report(
        stage3_core(context), controls(context["inputs"], context["loaded"])
    )
    report["sha256"] = write_new_json(Path(results_path), plain(report))
    return report


# --- Stage 3 in parts (execution mechanics only; no statistic changes) ---------------------
#
# The sandbox's Bash tool stops a single command at 9 minutes, and Stage 3's s. 10 controls
# alone run longer than that. `stage3 --part <name>` therefore runs one slice at a time and
# `--part merge` assembles the registered results file from the slices. Nothing about the
# statistics changes: every part calls the same block function `controls` calls, with the same
# replicate counts, and the s. 10 seed is per (network, condition, control, index), so a
# control's numbers do not depend on which other controls ran in the same process.

STAGE3_COMPUTE_PARTS = ("core", "control1", "control2_fa", "control2_cov", "control3",
                        "control45")  # fmt: skip
STAGE3_PART_NAMES = (*STAGE3_COMPUTE_PARTS, "merge")
PARTS_BY_NETWORK = ("control1", "control2_fa", "control2_cov", "control3")
PARTS_BY_SIGMA = ("control2_fa", "control2_cov")
PART_LIMIT_SECONDS = 8 * 60  # the issue's per-part budget inside the 9-minute command limit


def expected_stage3_parts() -> list[dict]:
    """Every part `merge` requires, in the order the execution task should run them."""
    out: list[dict] = [{"part": "core", "network": None, "sigma": None}]
    for code in SWEEP_NETWORKS:
        out.append({"part": "control1", "network": code, "sigma": None})
    for part in ("control2_fa", "control2_cov"):
        for code in SWEEP_NETWORKS:
            for sigma in sorted(A_STAR_CONDITIONS):
                out.append({"part": part, "network": code, "sigma": sigma})
    for code in ALL_NETWORKS:  # s. 10: control 3 runs at the six `local_line` cables
        out.append({"part": "control3", "network": code, "sigma": None})
    out.append({"part": "control45", "network": None, "sigma": None})
    return out


def part_path(part: str, network: str | None = None, sigma: str | None = None,
              parts_dir: Path = STAGE3_PARTS) -> Path:  # fmt: skip
    """`analysis/phase9/results/stage3_parts/<part>[-<network>][-<sigma>].json`."""
    stem = part
    if network:
        stem += f"-{network}"
    if sigma:
        stem += f"-{sigma}"
    return Path(parts_dir) / f"{stem}.json"


def check_part_arguments(part: str, network: str | None, sigma: str | None) -> None:
    """A part name with the coordinates it needs, and nothing it does not."""
    if part not in STAGE3_COMPUTE_PARTS:
        raise ValueError(f"{part} is not a Stage 3 part {STAGE3_COMPUTE_PARTS}")
    wants_network, wants_sigma = part in PARTS_BY_NETWORK, part in PARTS_BY_SIGMA
    if wants_network and not network:
        raise ValueError(f"part {part} runs per network: --network is required")
    if not wants_network and network:
        raise ValueError(f"part {part} does not run per network: drop --network")
    if wants_sigma and not sigma:
        raise ValueError(f"part {part} runs per sigma_tot: --sigma is required")
    if not wants_sigma and sigma:
        raise ValueError(f"part {part} does not run per sigma_tot: drop --sigma")
    allowed = ALL_NETWORKS if part == "control3" else SWEEP_NETWORKS
    if network and network not in allowed:
        raise ValueError(f"{network} is not a part-{part} network {allowed}")
    if sigma and sigma not in A_STAR_CONDITIONS:
        raise ValueError(f"{sigma} is not an s. 10 control 2 sigma_tot key "
                         f"{tuple(sorted(A_STAR_CONDITIONS))}")  # fmt: skip


def stage3_part(part: str, *, network: str | None = None, sigma: str | None = None,
                inputs_path: Path = INPUTS_FILE, parts_dir: Path = STAGE3_PARTS,
                root: Path = ps.SWEEP, git=ps._git,
                control1_replicates: int = CONTROL1_REPLICATES,
                fa_replicates: int = A_STAR_FA_REPLICATES,
                cov_replicates: int = A_STAR_COV_REPLICATES,
                permutations: int = PERMUTATIONS) -> dict:  # fmt: skip
    """One part of Stage 3, written to `stage3_parts/<part>[-<network>][-<sigma>].json`.

    Every refusal check of the monolithic `stage3` runs first and nothing is written if any of
    them refuses. The record carries the part's own wall time, the sha256 of Stage 1's
    `phase9_inputs.json` and the sweep's `physics_key`, which `merge` requires to agree across
    the parts.
    """
    check_part_arguments(part, network, sigma)
    require_committed_registration(git)  # refuse before touching any artefact or results file
    load_stage1(inputs_path)
    path = part_path(part, network, sigma, parts_dir)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite {path}")

    started = time.perf_counter()
    context = stage3_context(inputs_path, root, git)
    inputs, loaded = context["inputs"], context["loaded"]
    extra: dict = {}
    if part == "core":
        payload = stage3_core(context)
    elif part == "control3":
        payload = control3_network(network, inputs, permutations=permutations)
    else:
        net = control_network_inputs(network, inputs, loaded) if network else None
        if part == "control1":
            specs = {condition: noise_spec(condition) for condition in CONTROL_CONDITIONS}
            payload = control1_block(net, replicates=control1_replicates, specs=specs)
            extra["per_network"] = net["per_network"]
        elif part in PARTS_BY_SIGMA:
            condition = A_STAR_CONDITIONS[sigma]
            specs = {condition: noise_spec(condition)}
            one = {sigma: condition}
            block = control2_fa_block if part == "control2_fa" else control2_cov_block
            replicates = fa_replicates if part == "control2_fa" else cov_replicates
            payload = block(net, replicates=replicates, conditions=one, specs=specs)
        else:  # control45: controls 4 and 5 at both sweep networks, both co-primary sigma
            nets = {code: control_network_inputs(code, inputs, loaded)
                    for code in SWEEP_NETWORKS}  # fmt: skip
            payload = {
                "control_4": {code: control4_block(one) for code, one in nets.items()},
                "control_5": {code: control5_block(one) for code, one in nets.items()},
            }
    seconds = time.perf_counter() - started

    record = {
        "stage": "3 part (registration s. 12 Stage 3, run in parts)",
        "part": part,
        "network": network,
        "sigma_tot_key": sigma,
        "wall_seconds": float(seconds),
        "physics_key": context["physics_key"],
        "stage1_inputs": {
            "path": context["stage1_file"]["path"],
            "sha256": context["stage1_file"]["sha256"],
        },
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256,
                         "state": context["registration"]},  # fmt: skip
        "note": "execution mechanics only: the same block `controls` calls, at the registered "
                "replicate counts and seeds",  # fmt: skip
        **extra,
        "payload": payload,
    }
    record["sha256"] = write_new_json_atomic(path, plain(record))
    record["path"] = str(path)
    return record


def read_stage3_part(part: str, network: str | None, sigma: str | None,
                     parts_dir: Path = STAGE3_PARTS) -> dict:  # fmt: skip
    """One written part, with the file's own sha256 recorded for the `parts` provenance."""
    path = part_path(part, network, sigma, parts_dir)
    text = path.read_text()
    record = json.loads(text)
    record["sha256"] = q1.sha256_text(text)
    record["path"] = str(path)
    return record


def merge_per_sigma(blocks: list[dict]) -> dict:
    """One control-2 block per sigma_tot key, merged into the mapping the monolithic run
    writes. The envelope is the parts' common one and `per_sigma_tot` is reassembled in the
    monolith's order, which is `sorted(A_STAR_CONDITIONS)`."""
    if not blocks:
        raise ValueError("at least one control 2 block is needed")
    merged, seen = dict(blocks[0]), {}
    for block in blocks:
        for key, value in block["per_sigma_tot"].items():
            if key in seen:
                raise RuntimeError(f"two control 2 parts both carry sigma_tot {key}")
            seen[key] = value
    merged["per_sigma_tot"] = {
        key: seen[key] for key in sorted(A_STAR_CONDITIONS) if key in seen
    }
    return merged


def part_registration_mismatches(records: dict, state: dict) -> list[dict]:
    """The parts whose recorded registration commit or sha256 is not the current one (s. 12).

    A part is written under one registration commit; `merge` writes the registered results
    file, so it must not assemble parts from a different one. A missing field counts as a
    mismatch: a part that records no commit cannot be shown to share this one.
    """
    out = []
    for (part, network, sigma), record in records.items():
        registration = record.get("registration") or {}
        commit = (registration.get("state") or {}).get("commit")
        sha = registration.get("sha256")
        if commit != state["commit"] or sha != REGISTRATION_SHA256:
            out.append({
                "part": part, "network": network, "sigma_tot_key": sigma,
                "recorded_commit": commit, "recorded_sha256": sha,
                "current_commit": state["commit"], "current_sha256": REGISTRATION_SHA256,
            })
    return out


def merge_stage3_parts(parts_dir: Path = STAGE3_PARTS, results_path: Path = RESULTS_FILE,
                       conditions=CONTROL_CONDITIONS, git=ps._git) -> dict:  # fmt: skip
    """`stage3 --part merge`: the registered results file, assembled from the written parts.

    It refuses unless the registration is committed and unmodified, because this is the
    command that writes the registered `results/phase9_results.json` and s. 12 Stage 0
    requires the commit before Stages 1-3. It then requires every part of
    `expected_stage3_parts`, requires them to share one Stage 1 inputs hash, one sweep
    `physics_key` and the current registration commit and sha256, assembles exactly the
    structure the monolithic `stage3` writes plus a `parts` provenance block, and refuses to
    overwrite.
    """
    state = require_committed_registration(git)  # refuse before reading or writing anything
    expected = expected_stage3_parts()
    records, missing = {}, []
    for item in expected:
        path = part_path(item["part"], item["network"], item["sigma"], parts_dir)
        if not path.exists():
            missing.append(str(path))
            continue
        records[(item["part"], item["network"], item["sigma"])] = read_stage3_part(
            item["part"], item["network"], item["sigma"], parts_dir
        )
    if missing:
        raise RuntimeError(
            f"merge refuses: {len(missing)} of {len(expected)} Stage 3 parts are missing "
            f"({', '.join(missing)}); every part must be written before the results file is "
            "assembled"
        )
    hashes = sorted({record["stage1_inputs"]["sha256"] for record in records.values()})
    keys = sorted({record["physics_key"] for record in records.values()})
    if len(hashes) != 1:
        raise RuntimeError(
            f"merge refuses: the parts carry {len(hashes)} different phase9_inputs.json "
            f"hashes ({', '.join(hashes)}); they must all come from one Stage 1 file"
        )
    if len(keys) != 1:
        raise RuntimeError(
            f"merge refuses: the parts carry {len(keys)} different sweep physics keys "
            f"({', '.join(keys)}); they must all come from one sweep"
        )
    stale = part_registration_mismatches(records, state)
    if stale:
        raise RuntimeError(
            f"merge refuses: {len(stale)} of {len(expected)} Stage 3 parts record a different "
            "registration than the current one "
            f"(commit {state['commit']}, sha256 {REGISTRATION_SHA256}): "
            + "; ".join(
                f"{item['part']}"
                + (f"-{item['network']}" if item["network"] else "")
                + (f"-{item['sigma_tot_key']}" if item["sigma_tot_key"] else "")
                + f" records commit {item['recorded_commit']}, sha256 {item['recorded_sha256']}"
                for item in stale
            )
            + ". Every part must be computed under the committed registration this file is "
            "written for; delete the stale parts and recompute them."
        )

    specs = {condition: noise_spec(condition) for condition in conditions}
    control45 = records[("control45", None, None)]["payload"]
    controls_block = controls_envelope(
        specs,
        {code: records[("control1", code, None)]["per_network"] for code in SWEEP_NETWORKS},
        {code: records[("control1", code, None)]["payload"] for code in SWEEP_NETWORKS},
        {code: merge_per_sigma([records[("control2_fa", code, sigma)]["payload"]
                               for sigma in sorted(A_STAR_CONDITIONS)])  # fmt: skip
         for code in SWEEP_NETWORKS},  # fmt: skip
        {code: merge_per_sigma([records[("control2_cov", code, sigma)]["payload"]
                               for sigma in sorted(A_STAR_CONDITIONS)])  # fmt: skip
         for code in SWEEP_NETWORKS},  # fmt: skip
        {code: records[("control3", code, None)]["payload"] for code in ALL_NETWORKS},
        control45["control_4"],
        control45["control_5"],
        include_control3=True,
    )
    report = stage3_report(records[("core", None, None)]["payload"], controls_block)
    report["parts"] = {
        "note": "Stage 3 was run in parts under the sandbox's 9-minute command limit; the "
                "statistics, seeds and replicate counts are the monolithic `stage3`'s",  # fmt: skip
        "count": len(records),
        "stage1_inputs_sha256": hashes[0],
        "physics_key": keys[0],
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256,
                         "commit": state["commit"],
                         "shared_by_every_part": True},  # fmt: skip
        "wall_seconds_total": float(sum(r["wall_seconds"] for r in records.values())),
        "per_part": [
            {
                "part": item["part"],
                "network": item["network"],
                "sigma_tot_key": item["sigma"],
                "file": Path(records[(item["part"], item["network"], item["sigma"])]["path"]).name,
                "sha256": records[(item["part"], item["network"], item["sigma"])]["sha256"],
                "wall_seconds": records[(item["part"], item["network"],
                                         item["sigma"])]["wall_seconds"],  # fmt: skip
            }
            for item in expected
        ],
    }
    report["sha256"] = write_new_json_atomic(Path(results_path), plain(report))
    return report


# --- `stage3-benchmark`: the per-part wall time, on synthetic data at the real shapes -------

BENCHMARK_SHAPES = (  # s. 3 candidate counts, s. 7 retained days; buses from Stage 1's W3
    {"network": "1-LV-semiurb4--2-sw", "cables": 39, "buses": 43, "scored_days": 183,
     "retained_days": 170},  # fmt: skip
    {"network": "1-LV-urban6--2-sw", "cables": 50, "buses": 58, "scored_days": 183,
     "retained_days": 175},  # fmt: skip
)
BENCHMARK_DAYLIGHT = 40  # a representative valid-daylight count; only array shapes matter
BENCHMARK_RULES = EXPECTED_RULES  # 25, as s. 8 registers
BENCHMARK_RULE_BUSES = 4  # K <= 4, so a rule needs four distinct buses
# Loading the 99 artefacts, deriving the manifest and importing the engine happen once per
# part. Timing that would mean reading real artefacts, which this issue forbids, so it is
# carried as a stated allowance and is NOT a measurement.
CONTEXT_ALLOWANCE_SECONDS = 120.0
CORE_ALLOWANCE_SECONDS = 60.0  # the `core` part's own reduction, also a stated allowance


def benchmark_network_inputs(shape: dict) -> dict:
    """A `control_network_inputs`-shaped bundle at one real shape, built from zeros.

    No network, cache, artefact or results file is read: the buses are `range`, the rules are
    synthetic placements and the thresholds come from `threshold_grid` on the synthetic counts.
    """
    buses = list(range(int(shape["buses"])))
    names = (*NAMED_RULES, *RANDOM_RULES)  # the registered rule names, so control 5 is real
    rules = {
        name: [buses[(i * 3 + j) % len(buses)] for j in range(BENCHMARK_RULE_BUSES)]
        for i, name in enumerate(names)
    }
    if len(rules) != BENCHMARK_RULES:
        raise RuntimeError(f"s. 8 registers {BENCHMARK_RULES} rules, built {len(rules)}")
    for name, placed in rules.items():  # a rule with a repeated bus would shrink K
        if len(set(placed)) != BENCHMARK_RULE_BUSES:
            raise RuntimeError(f"{name}: the synthetic placement repeats a bus: {placed}")
    scored, retained_days = int(shape["scored_days"]), int(shape["retained_days"])
    arrays = {
        "day_index": np.arange(scored, dtype=np.int32),
        "bus_index": np.asarray(buses, dtype=np.int32),
        "n_daylight_valid": np.full(scored, BENCHMARK_DAYLIGHT, dtype=np.int16),
        "n_night_valid": np.full(scored, STEPS - BENCHMARK_DAYLIGHT, dtype=np.int16),
        "n_daylight_steps": np.full(scored, BENCHMARK_DAYLIGHT, dtype=np.int16),
        "n_night_steps": np.full(scored, STEPS - BENCHMARK_DAYLIGHT, dtype=np.int16),
        "dmean_daylight": np.zeros((scored, len(buses)), dtype=np.float32),
        "dmean_night": np.zeros((scored, len(buses)), dtype=np.float32),
        "failed_truth": np.zeros(scored, dtype=np.int16),
        "nan_nominal": np.zeros(scored, dtype=np.int16),
    }
    retention = {
        "D_ret": retained_days,
        "D_eff": (1.0 - REMOTE_MISSING) * retained_days,
        "n_day_median": float(BENCHMARK_DAYLIGHT),
        "n_night_median": float(STEPS - BENCHMARK_DAYLIGHT),
    }
    counts = meter_days([arrays], list(range(retained_days)))
    lines = list(range(int(shape["cables"])))
    downstream = {line: buses[: max(1, len(buses) // 3)] for line in lines}
    stats = {which: {"mean": np.zeros(len(buses)), "median": np.zeros(len(buses))}
             for which in ("m", "night", "k")}  # fmt: skip
    entries = {line: _rule_inputs(buses, downstream[line], stats, "mean") for line in lines}
    return {
        "code": shape["network"],
        "facts": {"K_all": len(buses)},
        "buses": buses,
        "rules": rules,
        "downstream": downstream,
        "thresholds": threshold_grid(retention, len(buses))["mean"],
        "registered": 0,
        "lines": lines,
        "counts": counts,
        "truth_contrast": np.zeros((len(lines), counts["simulated_days"], len(buses))),
        "truth_k": np.zeros((len(lines), len(buses))),
        "entries": entries,
        "per_network": {"cables": len(lines), "day_axis": counts["simulated_days"]},
        "retention": retention,
    }


def _timed(call, *args, **kwargs) -> tuple[object, float]:
    """`call(*args, **kwargs)` and the wall seconds it took."""
    started = time.perf_counter()
    out = call(*args, **kwargs)
    return out, time.perf_counter() - started


def benchmark_projection(part: str, measured: float, *, fraction: float, factor: int,
                         grid_point: str) -> dict:  # fmt: skip
    """One part's projected wall time: the measured slice, scaled to the registered replicate
    count and multiplied by the slices the part runs, plus the context allowance."""
    compute = measured / float(fraction) * int(factor)
    projected = compute + CONTEXT_ALLOWANCE_SECONDS
    return {
        "part": part,
        "timed_slice": grid_point,
        "replicate_fraction": float(fraction),
        "measured_seconds": float(measured),
        "slices_per_part": int(factor),
        "projected_compute_seconds": float(compute),
        "context_allowance_seconds": CONTEXT_ALLOWANCE_SECONDS,
        "projected_seconds": float(projected),
        "projected_minutes": float(projected / 60.0),
        "limit_seconds": float(PART_LIMIT_SECONDS),
        "fits": bool(projected <= PART_LIMIT_SECONDS),
    }


def stage3_benchmark(fraction: float = 1.0) -> dict:
    """`stage3-benchmark`: project each part's wall time from synthetic runs at the real shapes.

    One grid point of each s. 10 control is timed at the registered replicate count (or at
    `fraction` of it, extrapolated linearly), on zeros at the registered cable, bus, day and
    rule counts. No network, cache, artefact or results file is read.
    """
    if not 0.0 < float(fraction) <= 1.0:
        raise ValueError(f"the replicate fraction is in (0, 1], got {fraction}")
    specs = {condition: noise_spec(condition) for condition in CONTROL_CONDITIONS}
    one_point = (0.02,)  # a non-zero grid point: A = 0 skips no work, but is not typical
    per_network = {}
    for shape in BENCHMARK_SHAPES:
        net = benchmark_network_inputs(shape)
        code = net["code"]
        timings = []

        condition = CONTROL_CONDITIONS[0]
        replicates = max(1, round(CONTROL1_REPLICATES * fraction))
        _, seconds = _timed(control1_block, net, replicates=replicates,
                            conditions=(condition,), specs=specs)  # fmt: skip
        timings.append(benchmark_projection(
            "control1", seconds, fraction=replicates / CONTROL1_REPLICATES,
            factor=len(CONTROL_CONDITIONS),
            grid_point=f"condition {condition}, both variants, {replicates} replicates",
        ))

        for part, block, registered in (("control2_fa", control2_fa_block, A_STAR_FA_REPLICATES),
                                        ("control2_cov", control2_cov_block,
                                         A_STAR_COV_REPLICATES)):  # fmt: skip
            sigma = sorted(A_STAR_CONDITIONS)[0]
            replicates = max(1, round(registered * fraction))
            _, seconds = _timed(block, net, replicates=replicates,
                                conditions={sigma: A_STAR_CONDITIONS[sigma]},
                                grid=one_point, specs=specs)  # fmt: skip
            timings.append(benchmark_projection(
                part, seconds, fraction=replicates / registered, factor=len(A_OVER_SIGMA),
                grid_point=f"sigma_tot {sigma}, A/sigma_tot {one_point[0]:g}, "
                           f"{replicates} replicates",  # fmt: skip
            ))

        permutations = max(1, round(PERMUTATIONS * fraction))
        days = net["retention"]["D_ret"]
        daylight = np.zeros((days, STEPS), dtype=bool)
        daylight[:, :BENCHMARK_DAYLIGHT] = True
        permuted, seconds = _timed(
            permuted_contrast, np.zeros((days, STEPS, len(net["buses"]))), daylight,
            np.ones((days, STEPS), dtype=bool), control_rng(code, NO_CONDITION, CONTROL3, 0),
            permutations,
        )  # fmt: skip
        _, distribution_seconds = _timed(
            control3_distribution, permuted["k_perm"], net["buses"], net["thresholds"],
            net["facts"]["K_all"],
        )  # fmt: skip
        timings.append(benchmark_projection(
            "control3", seconds + distribution_seconds,
            fraction=permutations / PERMUTATIONS, factor=1,
            grid_point=f"{permutations} label permutations at {days} days x {STEPS} steps",
        ))

        _, seconds = _timed(control4_block, net)
        _, more = _timed(control5_block, net)
        timings.append(benchmark_projection(
            "control45", seconds + more, fraction=1.0, factor=1,
            grid_point="controls 4 and 5 at both co-primary sigma, in full, this network only",
        ))

        per_network[code] = {
            "shape": {**shape, "rules": BENCHMARK_RULES, "K_grid": list(K_GRID),
                      "daylight_steps_per_day": BENCHMARK_DAYLIGHT,
                      "simulated_days": net["counts"]["simulated_days"]},  # fmt: skip
            "per_part": {entry["part"]: entry for entry in timings},
        }
    # the `control45` part runs both sweep networks in one command, so its projection is the
    # sum of the per-network measurements, not either one of them
    control45 = benchmark_projection(
        "control45",
        sum(entry["per_part"]["control45"]["projected_compute_seconds"]
            for entry in per_network.values()),  # fmt: skip
        fraction=1.0, factor=1,
        grid_point="controls 4 and 5 at both sweep networks and both co-primary sigma, in full",
    )
    # the four held-out networks are smaller than either sweep network, so control 3 there is
    # bounded by the slower sweep shape; that bound is what is reported for them
    slowest = {
        part: max((entry["per_part"][part] for entry in per_network.values()),
                  key=lambda one: one["projected_seconds"])  # fmt: skip
        for part in ("control1", "control2_fa", "control2_cov", "control3")
    }
    projections = []
    for item in expected_stage3_parts():
        part, code, sigma = item["part"], item["network"], item["sigma"]
        if part == "core":
            entry = {
                "part": "core", "measured": False,
                "timed_slice": "not timed: vectorised zero-flow reduction with no Monte Carlo "
                               "loop, over the artefacts the context already loads",  # fmt: skip
                "projected_compute_seconds": CORE_ALLOWANCE_SECONDS,
                "context_allowance_seconds": CONTEXT_ALLOWANCE_SECONDS,
                "projected_seconds": CORE_ALLOWANCE_SECONDS + CONTEXT_ALLOWANCE_SECONDS,
                "limit_seconds": float(PART_LIMIT_SECONDS),
            }
            entry["projected_minutes"] = entry["projected_seconds"] / 60.0
            entry["fits"] = bool(entry["projected_seconds"] <= PART_LIMIT_SECONDS)
        elif part == "control45":
            entry = {**control45, "measured": True}
        elif code in per_network:
            entry = {**per_network[code]["per_part"][part], "measured": True}
        else:  # a held-out network: bounded by the slower sweep shape
            entry = {**slowest[part], "measured": True,
                     "basis": f"bounded by the slower sweep shape; {code} is smaller"}  # fmt: skip
        projections.append({**entry, "network": code, "sigma_tot_key": sigma})
    over = [entry for entry in projections if not entry["fits"]]
    return {
        "benchmark": "s. 12 Stage 3 per-part wall time, synthetic, at the registered shapes",
        "touches_real_data": False,
        "sources": "zeros at the s. 3 cable counts, the Stage 1 bus counts and the s. 7 "
                   "retained-day counts; synthetic placements; the noise conditions come from "
                   "gridpulse.noise_study.CONDITIONS (source, not data)",  # fmt: skip
        "replicate_fraction": float(fraction),
        "registered_replicates": {
            "control1": CONTROL1_REPLICATES, "control2_fa": A_STAR_FA_REPLICATES,
            "control2_cov": A_STAR_COV_REPLICATES, "control3": PERMUTATIONS,
        },  # fmt: skip
        "context_allowance_seconds": CONTEXT_ALLOWANCE_SECONDS,
        "context_allowance_note": (
            "every part loads the 99 artefacts and derives the manifest; timing that would "
            "read real data, which this benchmark does not do, so the allowance is a stated "
            "figure and not a measurement"
        ),
        "limit_seconds": float(PART_LIMIT_SECONDS),
        "core_allowance_seconds": CORE_ALLOWANCE_SECONDS,
        "per_network": per_network,
        "projected_parts": projections,
        "parts_over_the_limit": over,
        "core_part_note": (
            "the `core` part is not benchmarked: it is vectorised zero-flow reduction over the "
            "same artefacts the context already loads, with no Monte Carlo loop, so it carries "
            "a stated allowance like the context does"
        ),
        "invocations": [
            {"part": item["part"], "network": item["network"], "sigma": item["sigma"],
             "file": part_path(item["part"], item["network"], item["sigma"]).name}  # fmt: skip
            for item in expected_stage3_parts()
        ],
        "every_part_fits": not over,
    }


# --- CLI ------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stage0", help="integrity: hashes and the registration-commit check (s. 12)")
    sub.add_parser("stage1", help="inputs, topology, retention and thresholds (s. 3, s. 7-s. 9)")
    stage3_parser = sub.add_parser(
        "stage3", help="the statistics core (s. 8, s. 9, W1, W2, W5, W8, W9)"
    )
    stage3_parser.add_argument(
        "--part", choices=STAGE3_PART_NAMES,
        help="run one part of Stage 3 instead of the whole stage, or `merge` to assemble the "
             "results file from the written parts; omit it for the monolithic run",  # fmt: skip
    )
    stage3_parser.add_argument("--network", help="the part's network (control1, control2_*, "
                                                 "control3)")  # fmt: skip
    stage3_parser.add_argument("--sigma", help="the part's sigma_tot key (control2_fa, "
                                               "control2_cov)")  # fmt: skip
    sub.add_parser("stage4", help="repeat Stage 0 (s. 12.6)")
    benchmark = sub.add_parser(
        "stage3-benchmark",
        help="project each Stage 3 part's wall time on synthetic data at the real shapes; no "
             "real data",  # fmt: skip
    )
    benchmark.add_argument(
        "--fraction", type=float, default=1.0,
        help="run this fraction of each registered replicate count and extrapolate linearly",
    )
    selftest = sub.add_parser(
        "controls-selftest",
        help="s. 10 control 1 on a synthetic network with known counts; no real data",
    )
    selftest.add_argument("--replicates", type=int, default=CONTROL1_REPLICATES)
    args = parser.parse_args(argv)

    if args.command == "stage0":
        report = stage0(label="0")
    elif args.command == "stage1":
        report = stage1()
    elif args.command == "stage3":
        if args.part == "merge":
            report = merge_stage3_parts()
        elif args.part:
            report = stage3_part(args.part, network=args.network, sigma=args.sigma)
        else:
            report = stage3()
    elif args.command == "stage3-benchmark":
        report = stage3_benchmark(fraction=args.fraction)
    elif args.command == "controls-selftest":
        report = controls_selftest(replicates=args.replicates)
    else:
        report = stage0(label="4")
    print(json_text(plain(report)), end="")
    if args.command in ("stage1", "stage3"):
        label = f"{args.command} --part {args.part}" if getattr(args, "part", None) else (
            args.command
        )
        print(f"{label} sha256 {report['sha256']}", file=sys.stderr)
    if args.command == "stage3-benchmark":
        for entry in report["projected_parts"]:
            name = entry["part"] + (f" {entry['network']}" if entry["network"] else "")
            name += f" {entry['sigma_tot_key']}" if entry.get("sigma_tot_key") else ""
            print(f"{name}: {entry['projected_minutes']:.2f} min projected "
                  f"({'fits' if entry['fits'] else 'OVER THE 8-MINUTE LIMIT'})",
                  file=sys.stderr)  # fmt: skip
        print(f"stage3-benchmark {'PASS' if report['every_part_fits'] else 'SPLIT NEEDED'}: "
              f"{len(report['projected_parts']) - len(report['parts_over_the_limit'])} of "
              f"{len(report['projected_parts'])} projected parts fit", file=sys.stderr)  # fmt: skip
        return 0 if report["every_part_fits"] else 1
    if args.command == "controls-selftest":
        print(
            f"controls-selftest {'PASS' if report['holds'] else 'FAIL'}: "
            f"{len(report['checks']) - len(report['failures'])} of {len(report['checks'])} "
            "checks hold",
            file=sys.stderr,
        )
        return 0 if report["holds"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
