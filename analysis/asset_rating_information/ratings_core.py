"""Mission 12 Stage A: the rating-decision numerical core (`stage_a_protocol.md`, revision 2.2).

EXPLORATORY and internally pre-specified, not externally preregistered. The protocol's
**as-executed** text (the amendments replaced by "(none)", see `executed_text_sha`) hashes to
`PROTOCOL_SHA256_EXECUTED`; `check_protocol` enforces that and returns the full-file hash,
and every later stage is expected to call it before it starts.

This module runs **zero power flows** and reads **no cache**. It imports neither pandapower
nor simbench (a test parses this file and asserts that), and it knows nothing about any
particular network: every network fact (line loadings, transformer loading, voltage
admissibility, export, parent pointers, `std_type` labels, feeder ids) arrives as an array
argument. Task 2 builds the decision tables from the Phase 5 cache and task 3 scores them.

Conventions (protocol s. 0 to s. 10):

* a **level** is an index into `CAP_LEVELS` = 1.0, 0.9, ..., 0.0, so index 0 is the
  uncurtailed decision and index 10 (`LEVEL_ZERO`) is cap 0;
* loadings and believed thresholds are in **% of the record** `r_rec` (for a line,
  `max_i_ka * df * parallel`; for the transformer, `sn_mva`), so a believed rating
  rho_hat enters as the threshold `100 * rho_hat`;
* rho = r_true / r_rec, one per line plus one for the transformer;
* a decision table's **table lines** are the columns kept from a network: those whose
  P-or-E maximum loading exceeds `TABLE_LOADING_PCT`, the most permissive bound any model
  can believe. Every other line is admissible at every level under every believed rating
  >= its lower bound, so it can never block (protocol s. 6, "candidate pool");
* **unit** = one verification action: a segment under U0, U2, U3 and U2', a route under U4.
  Budgets here are counted in units; the realised segment count is reported alongside.

**The NaN rule.** A NaN anywhere at (step, level) -- in any table line's loading, in the
transformer loading or in the export -- makes that level inadmissible, and the step is never
counted safe. `DecisionTable.finite` carries that mask and every decision path applies it.

**Topology index space.** `routes`, `root_path` and `route_rule`'s `parent_line` are in
**network** line indices; the decision table's columns are table lines, mapped by
`DecisionTable.line_ids`. `unit_groups` entries are table **columns**, because a ranking
only ever sees the table.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
for _path in (REPO / "src", HERE):  # imported, never copied or edited
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from gridpulse.sensing import _stable_int  # noqa: E402

# --- A. constants and seeds ----------------------------------------------------------------

STATUS = (
    "EXPLORATORY Mission 12 Stage A: decision-sufficient asset information under uncertain "
    "thermal ratings; zero power flows in this module; unregistered"
)

PROTOCOL = HERE / "stage_a_protocol.md"
#: the protocol's amendment heading: everything below it is append-only (amendment A1).
AMENDMENTS_HEADING = "## Amendments (after the first scored computation)"
#: the protocol **as executed**: revision 2.2's text with everything below
#: `AMENDMENTS_HEADING` replaced by "(none)" (see `executed_text_sha`). This is the hash
#: `check_protocol` enforces; the full-file hash is recorded in every artefact instead of
#: being pinned, so a dated amendment can be appended without invalidating earlier solves.
PROTOCOL_SHA256_EXECUTED = "9fc9108c0e70c1d2ec3eea19df659d1231ad175634aacb03a9fe326ce521af36"

SEED_ROOT = 20261026

#: the uniform PV feed-in caps, protocol s. 4. Index 0 = no cap, index 10 = cap 0.
CAP_LEVELS = np.array([1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0])
CAP_LEVELS.flags.writeable = False
N_LEVELS = CAP_LEVELS.size
LEVEL_ZERO = N_LEVELS - 1

#: "unsafe" means the true utilisation exceeds this many % above 100 (protocol s. 0, row E).
TOL_UNSAFE = 0.5

#: a line enters a decision table if its P-or-E maximum loading exceeds this (protocol s. 6:
#: 100 * (1 - w) with the most permissive w = 0.3 is 70 %).
TABLE_LOADING_PCT = 70.0

#: seed purposes (protocol s. 5): the truth draws, the shared prior sample, B5's orders.
PURPOSES = ("truth", "prior", "random_order")

MODELS = ("U0", "U2", "U3", "U4", "UT", "U2P")
#: U3's stylised class ratios and their prior (protocol s. 5).
U3_CLASSES = (0.8, 1.0, 1.25)
U3_PROBS = (0.25, 0.5, 0.25)
#: U2' (prior misspecification): the truth is drawn at w = 0.3, every policy believes w.
W_U2P_TRUTH = 0.3
#: U-T's transformer interval (protocol s. 5), stated as literal bounds.
TRAFO_INTERVAL = (0.8, 1.2)

#: how many descending loadings per (step, level) the s. 10 reduction keeps. A verified set
#: of size |S| needs |S| + 1 entries, so 8 covers the protocol's |S| <= 6 with margin.
TOP_K_DEFAULT = 8

_VERIFY_POLICIES = ("B5", "B6", "B7", "B8", "B8P", "B9", "OB")


def rng_for(network: str, model: str, purpose: str, index: int = 0) -> np.random.Generator:
    """The study's only entropy source (protocol s. 5).

    The stream is a function of (network, model, purpose, index) alone, so a truth draw, the
    shared prior sample and B5's random orders are reproducible independently of which
    policies, budgets or networks a run happens to touch.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"purpose {purpose!r} is not one of {PURPOSES}")
    entropy = [
        SEED_ROOT,
        _stable_int(str(network)),
        _stable_int(str(model)),
        _stable_int(str(purpose)),
        int(index),
    ]
    return np.random.default_rng(np.random.SeedSequence(entropy))


# --- B. the decision table -----------------------------------------------------------------


@dataclass
class DecisionTable:
    """One network, one period: every state the decision rule needs, re-labelled from cache.

    `load` is (steps x levels x table lines) line loading in % of the record, `trafo` is
    (steps x levels) transformer loading in % of `sn_mva`, `volt_ok` is (steps x levels) and
    is True where **both** Phase 4 voltage margins are <= 0, `export` is (steps x levels)
    MWh in the step, and `line_ids` holds the table lines' **network** indices.
    """

    load: np.ndarray
    trafo: np.ndarray
    volt_ok: np.ndarray
    export: np.ndarray
    line_ids: np.ndarray
    _finite: np.ndarray | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.load = np.ascontiguousarray(self.load, dtype=np.float32)
        self.trafo = np.ascontiguousarray(self.trafo, dtype=np.float32)
        self.volt_ok = np.ascontiguousarray(self.volt_ok, dtype=bool)
        self.export = np.ascontiguousarray(self.export, dtype=np.float64)
        self.line_ids = np.ascontiguousarray(self.line_ids, dtype=np.int64).reshape(-1)
        if self.load.ndim != 3:
            raise ValueError(f"load must be steps x levels x lines, got {self.load.shape}")
        steps, levels, n_table = self.load.shape
        if levels != N_LEVELS:
            raise ValueError(f"load has {levels} levels, expected {N_LEVELS}")
        if n_table != self.line_ids.size:
            raise ValueError(f"load has {n_table} columns but {self.line_ids.size} line ids")
        for name in ("trafo", "volt_ok", "export"):
            got = getattr(self, name).shape
            if got != (steps, levels):
                raise ValueError(f"{name} has shape {got}, expected {(steps, levels)}")

    @property
    def n_steps(self) -> int:
        return self.load.shape[0]

    @property
    def n_levels(self) -> int:
        return self.load.shape[1]

    @property
    def n_table(self) -> int:
        return self.load.shape[2]

    @property
    def finite(self) -> np.ndarray:
        """(steps x levels): False where any quantity at that level is not finite. A level
        with a NaN is inadmissible and never safe (the NaN rule, protocol s. 10's tables are
        complete, so this is a guard, not an expected path)."""
        if self._finite is None:
            ok = np.isfinite(self.trafo) & np.isfinite(self.export)
            if self.n_table:
                ok &= np.isfinite(self.load).all(axis=2)
            self._finite = ok
        return self._finite

    def column_of(self, line_ids: Sequence[int] | np.ndarray) -> np.ndarray:
        """Table columns of the given **network** line indices (-1 where not a table line)."""
        lookup = {int(nid): col for col, nid in enumerate(self.line_ids)}
        return np.array([lookup.get(int(i), -1) for i in np.asarray(line_ids).reshape(-1)], int)


def table_line_mask(
    max_loading_p: np.ndarray,
    max_loading_e: np.ndarray,
    threshold: float = TABLE_LOADING_PCT,
) -> np.ndarray:
    """Which lines enter a decision table: P-or-E maximum loading above `threshold` %."""
    p = np.asarray(max_loading_p, float).reshape(-1)
    e = np.asarray(max_loading_e, float).reshape(-1)
    if p.shape != e.shape:
        raise ValueError(f"P and E maxima differ in shape: {p.shape} vs {e.shape}")
    return np.fmax(p, e) > float(threshold)


def candidate_pool(table: DecisionTable, lb: float) -> np.ndarray:
    """The deployable candidate pool (protocol s. 6): table columns whose maximum loading at
    any step and level exceeds 100 * lb %. Every other column is certified decision-
    irrelevant over this period, because it cannot block at any believed rating >= lb."""
    if table.n_table == 0:
        return np.zeros(0, int)
    load = np.where(np.isfinite(table.load), table.load, -np.inf)
    return np.flatnonzero(load.max(axis=(0, 1)) > 100.0 * float(lb))


# --- C. the decision rule and its outcome --------------------------------------------------


class Decision(NamedTuple):
    """`level` is the chosen level index, `infeasible` flags protocol s. 4's
    `infeasible_at_zero`: no level qualified, so cap 0 was taken anyway."""

    level: np.ndarray
    infeasible: np.ndarray


class Outcome(NamedTuple):
    """`export` in MWh, `unsafe_steps` counted at `TOL_UNSAFE`, `max_severity` in % above
    100 (NaN if no chosen step has a finite utilisation)."""

    export: np.ndarray
    unsafe_steps: np.ndarray
    max_severity: np.ndarray


def _thr_lines(thr_line, n_table: int) -> tuple[np.ndarray, bool]:
    """Normalise a believed line threshold to (draws, n_table) in %. A 1-D argument is always
    per line (length n_table or 1); a batch over draws is 2-D."""
    thr = np.asarray(thr_line, dtype=float)
    if thr.ndim == 0:
        return thr.reshape(1, 1), False
    if thr.ndim == 1:
        if thr.size not in (1, n_table):
            raise ValueError(f"thr_line has {thr.size} entries, expected 1 or {n_table}")
        return thr.reshape(1, -1), False
    if thr.ndim == 2:
        if thr.shape[1] not in (1, n_table):
            raise ValueError(f"thr_line has {thr.shape[1]} columns, expected 1 or {n_table}")
        return thr, True
    raise ValueError(f"thr_line must be 0-, 1- or 2-D, got {thr.ndim}-D")


def _thr_trafo(thr_trafo) -> tuple[np.ndarray, bool]:
    """Normalise a believed transformer threshold to (draws,) in %. 1-D means per draw."""
    thr = np.asarray(thr_trafo, dtype=float)
    if thr.ndim == 0:
        return thr.reshape(1), False
    if thr.ndim == 1:
        return thr, True
    raise ValueError(f"thr_trafo must be 0- or 1-D, got {thr.ndim}-D")


def _first_admissible(ok: np.ndarray, batched: bool) -> Decision:
    any_ok = ok.any(axis=2)
    level = np.where(any_ok, np.argmax(ok, axis=2), LEVEL_ZERO).astype(np.int8)
    infeasible = ~any_ok
    if not batched:
        return Decision(level[0], infeasible[0])
    return Decision(level, infeasible)


def decide(table: DecisionTable, thr_line, thr_trafo) -> Decision:
    """The decision rule of protocol s. 4: the smallest level index at which every table line
    is <= its believed threshold, the transformer is <= its believed threshold and the voltage
    margins hold. If no level qualifies, level 10 (cap 0) with `infeasible` set.

    `thr_line` and `thr_trafo` are believed thresholds **in % of the record** (100 * rho_hat):
    per table line, or (draws x n_table) for a batch over draws. The batch is vectorised over
    draws; the loop is over the short line axis, which keeps the working set at
    (draws x steps x levels) booleans.
    """
    thr, b_line = _thr_lines(thr_line, table.n_table)
    thr_t, b_trafo = _thr_trafo(thr_trafo)
    batched = b_line or b_trafo
    n_draws = max(thr.shape[0], thr_t.shape[0])
    thr = np.broadcast_to(thr, (n_draws, table.n_table))
    thr_t = np.broadcast_to(thr_t, (n_draws,))
    ok = np.empty((n_draws, table.n_steps, table.n_levels), dtype=bool)
    ok[:] = (table.volt_ok & table.finite)[None]
    ok &= table.trafo[None] <= thr_t[:, None, None]
    for j in range(table.n_table):
        ok &= table.load[:, :, j][None] <= thr[:, j][:, None, None]
    return _first_admissible(ok, batched)


def export_total(table: DecisionTable, levels) -> np.ndarray:
    """Protocol s. 4: the sum over steps of the export at each step's chosen level."""
    lev = np.asarray(levels, dtype=np.intp)
    steps = np.arange(table.n_steps)
    chosen = table.export[steps, lev]
    return chosen.sum(axis=-1)


def outcome(table: DecisionTable, levels, rho_line, rho_trafo) -> Outcome:
    """The true outcome at the chosen levels (protocol s. 4), batched over draws.

    Export is the sum of `export[t, level_t]`. A step is unsafe if the largest true
    utilisation (loading / rho) exceeds 100 + `TOL_UNSAFE`, or if the chosen level carries a
    NaN (the NaN rule: never safe). Severity is the maximum true utilisation - 100 over the
    chosen steps, taken over the finite utilisations; it is NaN if none is finite.
    """
    lev = np.asarray(levels, dtype=np.intp)
    rho = np.asarray(rho_line, dtype=float)
    rho_t = np.asarray(rho_trafo, dtype=float)
    batched = lev.ndim == 2 or rho.ndim == 2 or rho_t.ndim == 1
    lev2 = lev if lev.ndim == 2 else lev.reshape(1, -1)
    rho2, _ = _thr_lines(rho, table.n_table)
    rho_t2, _ = _thr_trafo(rho_t)
    n_draws = max(lev2.shape[0], rho2.shape[0], rho_t2.shape[0])
    lev2 = np.broadcast_to(lev2, (n_draws, table.n_steps))
    rho2 = np.broadcast_to(rho2, (n_draws, table.n_table))
    rho_t2 = np.broadcast_to(rho_t2, (n_draws,))
    if np.any(rho2 <= 0) or np.any(rho_t2 <= 0):
        raise ValueError("rho must be positive")

    steps = np.arange(table.n_steps)[None, :]
    worst = np.full((n_draws, table.n_steps), -np.inf)
    not_finite = ~table.finite[steps, lev2]
    for j in range(table.n_table):
        util = table.load[:, :, j][steps, lev2] / rho2[:, j][:, None]
        worst = np.fmax(worst, util)
    util_t = table.trafo[steps, lev2] / rho_t2[:, None]
    worst = np.fmax(worst, util_t)

    unsafe = (worst > 100.0 + TOL_UNSAFE) | not_finite
    unsafe_steps = unsafe.sum(axis=1)
    severity = worst.max(axis=1) - 100.0
    severity = np.where(np.isfinite(severity), severity, np.nan)
    export = export_total(table, lev2)
    if not batched:
        return Outcome(export[0], unsafe_steps[0], severity[0])
    return Outcome(export, unsafe_steps, severity)


def situation(
    table: DecisionTable,
    thr_min,
    thr_max,
    *,
    thr_trafo_min: float = 100.0,
    thr_trafo_max: float = 100.0,
) -> np.ndarray:
    """Protocol s. 7 (H1): 1 where the decision is the same at the lower and the upper
    believed bound (decision-invariant), 2 where it is not. The transformer is known by
    default (rho_T = 1, so a threshold of 100 %)."""
    low = decide(table, thr_min, thr_trafo_min).level
    high = decide(table, thr_max, thr_trafo_max).level
    return np.where(low == high, 1, 2).astype(np.int8)


# --- D. the s. 10 reduction ----------------------------------------------------------------


@dataclass(frozen=True)
class Reduction:
    """Per (step, level), the `k` largest table-line loadings and their columns, descending.

    NaN loadings are ranked first (as +inf), so a NaN never hides behind a smaller value;
    `DecisionTable.finite` rejects the level in any case.
    """

    values: np.ndarray
    index: np.ndarray

    @property
    def k(self) -> int:
        return self.values.shape[2]


def top_reduction(table: DecisionTable, k: int = TOP_K_DEFAULT) -> Reduction:
    """Precompute protocol s. 10's reduction: with the unverified lines sharing one lower-bound
    threshold, admissibility needs only the largest unverified loading, which is the first of
    the top-(|S| + 1) entries whose column is unverified."""
    k = int(min(max(k, 0), table.n_table))
    load = np.where(np.isfinite(table.load), table.load, np.inf).astype(np.float32)
    order = np.argsort(-load, axis=2, kind="stable")[:, :, :k]
    return Reduction(np.take_along_axis(load, order, axis=2), order.astype(np.int32))


def reveal_width(units, budget: int | None = None) -> int:
    """The largest number of **table columns** that `budget` verification units can reveal
    together (every unit when `budget` is None).

    A unit is a segment under U0, U2, U3 and U2', but a whole **route** under U4 (protocol
    s. 5), and verifying a route reveals every segment on it. The protocol's units partition
    the columns they cover, so the largest reachable set is the sum of the largest unit sizes.
    """
    sizes = sorted((int(np.asarray(g, dtype=int).reshape(-1).size) for g in units), reverse=True)
    if budget is not None:
        sizes = sizes[: max(int(budget), 0)]
    return int(sum(sizes))


def reduction_for(table: DecisionTable, max_columns: int) -> Reduction:
    """`top_reduction` sized by `decide_reduced`'s exactness requirement (amendment A2).

    `max_columns` is the largest number of **table columns** any set scored through the
    reduction can reveal -- not a count of verification units, which is what the A2 defect
    confused it with. The reduction then keeps one entry more, capped at the table width: a set
    that reveals the whole table is exact at k = `n_table`, by the guard's own escape.
    """
    return top_reduction(table, min(int(max_columns) + 1, table.n_table))


def decide_reduced(
    table: DecisionTable,
    red: Reduction,
    verified,
    thr_verified,
    thr_unverified: float,
    thr_trafo,
    *,
    n_draws: int | None = None,
) -> Decision:
    """`decide` through the s. 10 reduction, for one verified set `S` shared by every draw.

    `thr_unverified` is the single believed lower-bound threshold in % that all unverified
    lines share; `thr_verified` is (|S|,) or (draws x |S|) in %. The verified lines are
    compared against their own thresholds directly from `table.load`, so the result is exact
    for any revealed rho -- including a revealed rho below the believed lower bound (U2').
    """
    sel = np.asarray(verified, dtype=int).reshape(-1)
    if np.unique(sel).size != sel.size:
        raise ValueError("the verified set must not repeat a column")
    if sel.size and red.k < sel.size + 1 and red.k < table.n_table:
        raise ValueError(
            f"the reduction keeps {red.k} entries, too few for |S| = {sel.size}: "
            f"rebuild it with k >= {sel.size + 1}"
        )
    thr_v = np.asarray(thr_verified, dtype=float)
    if thr_v.ndim == 1:
        thr_v = thr_v.reshape(1, -1)
    if thr_v.shape[1] != sel.size:
        raise ValueError(f"thr_verified has {thr_v.shape[1]} columns, expected {sel.size}")
    thr_t, b_trafo = _thr_trafo(thr_trafo)
    batched = n_draws is not None or thr_v.shape[0] > 1 or b_trafo
    n = int(n_draws) if n_draws is not None else max(thr_v.shape[0], thr_t.shape[0])
    thr_v = np.broadcast_to(thr_v, (n, sel.size))
    thr_t = np.broadcast_to(thr_t, (n,))

    base = table.volt_ok & table.finite
    if red.k:
        in_s = np.isin(red.index, sel)
        pos = np.argmax(~in_s, axis=2)
        max_unverified = np.take_along_axis(red.values, pos[:, :, None], axis=2)[:, :, 0]
        ok_unverified = max_unverified <= float(thr_unverified)
        all_verified = in_s.all(axis=2)
        if all_verified.any():  # every table line verified: nothing is left at the bound
            ok_unverified = ok_unverified | all_verified
        base = base & ok_unverified

    ok = np.empty((n, table.n_steps, table.n_levels), dtype=bool)
    ok[:] = base[None]
    ok &= table.trafo[None] <= thr_t[:, None, None]
    for i, j in enumerate(sel):
        ok &= table.load[:, :, j][None] <= thr_v[:, i][:, None, None]
    return _first_admissible(ok, batched)


def _set_decision(
    table: DecisionTable,
    rho_draws: np.ndarray,
    lb: float,
    verified,
    thr_trafo,
    red: Reduction | None = None,
) -> Decision:
    """The decision after verifying `verified`: the revealed rho for those columns, the
    believed lower bound for the rest (protocol s. 6, "unverified assets at their lower
    bound"). Uses the reduction when it is wide enough, else the full rule."""
    rho = np.atleast_2d(np.asarray(rho_draws, dtype=float))
    sel = np.asarray(verified, dtype=int).reshape(-1)
    n = rho.shape[0]
    usable = red is not None and (sel.size + 1 <= red.k or red.k >= table.n_table)
    if usable:
        thr_v = 100.0 * rho[:, sel] if sel.size else np.zeros((n, 0))
        return decide_reduced(table, red, sel, thr_v, 100.0 * float(lb), thr_trafo, n_draws=n)
    thr = np.full((n, table.n_table), 100.0 * float(lb))
    if sel.size:
        thr[:, sel] = 100.0 * rho[:, sel]
    thr_t = np.asarray(thr_trafo, dtype=float)
    if thr_t.ndim == 0:
        thr_t = np.full(n, float(thr_t))
    return decide(table, thr, thr_t)


def _set_exports(
    table: DecisionTable,
    rho_draws: np.ndarray,
    lb: float,
    verified,
    thr_trafo,
    red: Reduction | None = None,
) -> np.ndarray:
    """Export per draw after verifying `verified` (MWh)."""
    dec = _set_decision(table, rho_draws, lb, verified, thr_trafo, red)
    level = dec.level if dec.level.ndim == 2 else dec.level[None]
    return np.atleast_1d(export_total(table, level))


# --- E. topology ---------------------------------------------------------------------------


def _check_parent(parent_line) -> np.ndarray:
    parent = np.asarray(parent_line, dtype=int).reshape(-1)
    n = parent.size
    if np.any(parent >= n) or np.any(parent < -1):
        raise ValueError("parent_line entries must be a line index or -1 at a feeder head")
    if np.any(parent == np.arange(n)):
        raise ValueError("a line cannot be its own parent")
    return parent


def root_path(parent_line, line: int) -> np.ndarray:
    """The unique root path of `line`: itself first, then upstream to the feeder head
    (protocol s. 6 B9; the networks are radial, board check s. 2)."""
    parent = _check_parent(parent_line)
    current = int(line)
    if not 0 <= current < parent.size:
        raise ValueError(f"line {line} is outside 0..{parent.size - 1}")
    path = [current]
    seen = {current}
    while parent[path[-1]] >= 0:
        current = int(parent[path[-1]])
        if current in seen:
            raise ValueError("parent_line has a cycle; the line graph must be a tree")
        seen.add(current)
        path.append(current)
    return np.array(path, dtype=int)


def routes(parent_line, std_type, feeder_of_line) -> np.ndarray:
    """Protocol s. 5 (U4): the route of every line, as connected components of the lines that
    share one `std_type` within one feeder, read off the parent-pointer description.

    Two lines are in the same route when one is the other's parent and they agree on both
    `std_type` and feeder. Route labels are assigned in order of first appearance by line
    index. The caller supplies the feeder id (the subtree below one LV busbar outgoing line).
    """
    parent = _check_parent(parent_line)
    std = np.asarray(std_type).reshape(-1)
    feeder = np.asarray(feeder_of_line).reshape(-1)
    if std.size != parent.size or feeder.size != parent.size:
        raise ValueError("parent_line, std_type and feeder_of_line must have one entry per line")

    root = list(range(parent.size))

    def find(a: int) -> int:
        while root[a] != a:
            root[a] = root[root[a]]
            a = root[a]
        return a

    for line in range(parent.size):
        up = int(parent[line])
        if up >= 0 and std[line] == std[up] and feeder[line] == feeder[up]:
            ra, rb = find(line), find(up)
            if ra != rb:
                root[ra] = rb

    labels: dict[int, int] = {}
    out = np.empty(parent.size, dtype=int)
    for line in range(parent.size):
        key = find(line)
        if key not in labels:
            labels[key] = len(labels)
        out[line] = labels[key]
    return out


def groups_from_routes(route_of_column: np.ndarray, pool: np.ndarray) -> list[np.ndarray]:
    """Verification units for U4: the pool's columns grouped by route, in route order."""
    route_of_column = np.asarray(route_of_column, dtype=int).reshape(-1)
    pool = np.asarray(pool, dtype=int).reshape(-1)
    out: list[np.ndarray] = []
    for route in dict.fromkeys(route_of_column[pool].tolist()):
        out.append(pool[route_of_column[pool] == route])
    return out


# --- F. the uncertainty models (protocol s. 5) ---------------------------------------------


class RhoBounds(NamedTuple):
    line_lb: float
    line_ub: float
    trafo_lb: float
    trafo_ub: float


def _model(name: str) -> str:
    key = str(name).strip().upper().replace("-", "").replace("_", "")
    key = key.replace("′", "P").replace("'", "P")
    if key not in MODELS:
        raise ValueError(f"model {name!r} is not one of {MODELS}")
    return key


def rho_bounds(model: str, w: float = 0.2, kind: str = "believed") -> RhoBounds:
    """The lower and upper bounds of rho per model, believed or true (protocol s. 5).

    `kind="believed"` is what a deployable policy may assume; `kind="true"` is the support of
    the truth-generating distribution. They differ for U0 (records are correct but not
    trusted) and for U2' (the truth is drawn at w = `W_U2P_TRUTH` while policies believe `w`).
    """
    key = _model(model)
    if kind not in ("believed", "true"):
        raise ValueError(f"kind {kind!r} must be 'believed' or 'true'")
    if w <= 0 or w >= 1:
        raise ValueError(f"w = {w} must lie in (0, 1)")
    if key == "U0":
        return RhoBounds(1.0, 1.0, 1.0, 1.0) if kind == "true" else RhoBounds(1 - w, 1 + w, 1, 1)
    if key in ("U2", "U4"):
        return RhoBounds(1 - w, 1 + w, 1.0, 1.0)
    if key == "U3":
        return RhoBounds(min(U3_CLASSES), max(U3_CLASSES), 1.0, 1.0)
    if key == "UT":
        return RhoBounds(1.0, 1.0, TRAFO_INTERVAL[0], TRAFO_INTERVAL[1])
    wide = W_U2P_TRUTH if kind == "true" else w  # U2'
    return RhoBounds(1 - wide, 1 + wide, 1.0, 1.0)


def sample_rho(
    model: str,
    n_lines: int,
    rng: np.random.Generator,
    n: int,
    route_of_line=None,
    w: float = 0.2,
    kind: str = "truth",
) -> np.ndarray:
    """(n x n_lines) draws of the lines' rho under one model (protocol s. 5).

    `kind="truth"` draws the truth: U0 is exactly 1, U2' is drawn at `W_U2P_TRUTH`, and U-T's
    lines are known. `kind="prior"` draws the distribution a deployable policy believes: U0's
    interval prior, and U2' at the believed `w`. For U4 one rho per route is drawn and
    broadcast to the route's segments, so `route_of_line` (one route id per line, as returned
    by `routes` restricted to these lines) is required.
    """
    key = _model(model)
    if kind not in ("truth", "prior"):
        raise ValueError(f"kind {kind!r} must be 'truth' or 'prior'")
    if w <= 0 or w >= 1:
        raise ValueError(f"w = {w} must lie in (0, 1)")
    n, n_lines = int(n), int(n_lines)
    if n < 0 or n_lines < 0:
        raise ValueError("n and n_lines must not be negative")
    if key in ("U0", "UT") and kind == "truth":
        return np.ones((n, n_lines))
    if key == "U3":
        return rng.choice(np.array(U3_CLASSES), size=(n, n_lines), p=np.array(U3_PROBS))
    if key == "U4":
        if route_of_line is None:
            raise ValueError("U4 needs route_of_line: one rho per route, shared by its segments")
        route = np.asarray(route_of_line, dtype=int).reshape(-1)
        if route.size != n_lines:
            raise ValueError(f"route_of_line has {route.size} entries, expected {n_lines}")
        if route.size and (route.min() < 0):
            raise ValueError("route ids must be non-negative")
        per_route = rng.uniform(1 - w, 1 + w, size=(n, int(route.max()) + 1 if route.size else 0))
        return per_route[:, route] if route.size else np.ones((n, 0))
    width = W_U2P_TRUTH if (key == "U2P" and kind == "truth") else w
    return rng.uniform(1 - width, 1 + width, size=(n, n_lines))


def sample_rho_trafo(
    model: str, rng: np.random.Generator, n: int, kind: str = "truth"
) -> np.ndarray:
    """(n,) draws of the transformer's rho. It is sampled separately from the lines and is
    known (rho_T = 1) in every model but U-T (protocol s. 5)."""
    key = _model(model)
    if kind not in ("truth", "prior"):
        raise ValueError(f"kind {kind!r} must be 'truth' or 'prior'")
    if key == "UT":
        return rng.uniform(TRAFO_INTERVAL[0], TRAFO_INTERVAL[1], size=int(n))
    return np.ones(int(n))


# --- G. beliefs and the information boundary -----------------------------------------------


def reveal(verified, rho_true, n_lines: int | None = None) -> np.ndarray:
    """The study's only information oracle (protocol s. 5): rho for the verified assets,
    NaN everywhere else. A deployable policy receives truth through this function alone."""
    rho = np.asarray(rho_true, dtype=float)
    if rho.ndim == 0:
        raise ValueError("rho_true must be per line")
    n = int(n_lines) if n_lines is not None else rho.shape[-1]
    if rho.shape[-1] != n:
        raise ValueError(f"rho_true has {rho.shape[-1]} columns, expected {n}")
    sel = np.asarray(verified, dtype=int).reshape(-1)
    out = np.full(rho.shape, np.nan)
    if sel.size:
        out[..., sel] = rho[..., sel]
    return out


def beliefs(
    policy: str,
    lb,
    rho_verified_mask=None,
    rho_true_or_prior=None,
    *,
    n_lines: int | None = None,
) -> np.ndarray:
    """Believed thresholds in % of the record (100 * rho_hat) for one policy (protocol s. 6).

    Verified assets take their revealed rho; unverified assets take the believed lower bound.
    `policy` is B0 (records), B1 (uniform derating), B2 (robust lower bound), B3
    (scenario-robust: the componentwise minimum of the prior samples in `rho_true_or_prior`),
    B4 (oracle: `rho_true_or_prior` is the truth) or any verification policy (B5 to B9, OB,
    or the literal "verify"), which reads `rho_verified_mask` and the revealed values.

    B1's derating is (1 + lb) / 2, which is the protocol's 1 - w/2 whenever lb = 1 - w, and
    the midpoint between the bound and the record otherwise (U3's lb = 0.8 gives 0.9).
    """
    name = str(policy).strip().upper()
    if name in _VERIFY_POLICIES:
        name = "VERIFY"
    lb_arr = np.asarray(lb, dtype=float)
    if np.any(lb_arr <= 0):
        raise ValueError("the believed lower bound must be positive")
    if name == "B0":
        base = np.ones_like(lb_arr)
    elif name == "B1":
        base = (1.0 + lb_arr) / 2.0
    elif name in ("B2", "VERIFY"):
        base = lb_arr
    elif name == "B3":
        prior = np.asarray(rho_true_or_prior, dtype=float)
        if prior.ndim != 2:
            raise ValueError("B3 needs the prior samples as (draws x lines)")
        # the componentwise minimum of the sampled scenarios, NOT capped at lb: a finite
        # sample need not reach the box's corner. Protocol s. 8 as restated in revision 2.1:
        # a gap to B2 is expected and reported; only a B3 decision *more conservative* than
        # B2 is a fault. Capping at lb would make that check vacuous.
        base = prior.min(axis=0)
    elif name == "B4":
        base = np.asarray(rho_true_or_prior, dtype=float)
        if not np.all(np.isfinite(base)):
            raise ValueError("the oracle B4 needs a finite rho_true for every asset")
    else:
        raise ValueError(f"unknown policy {policy!r}")

    if n_lines is not None and base.ndim and base.shape[-1] not in (1, int(n_lines)):
        raise ValueError(f"policy {policy!r} produced {base.shape[-1]} of {n_lines} assets")
    if n_lines is not None and base.ndim == 0:
        base = np.full(int(n_lines), float(base))

    if name == "VERIFY" and rho_verified_mask is not None:
        mask = np.asarray(rho_verified_mask, dtype=bool)
        revealed = np.asarray(rho_true_or_prior, dtype=float)
        if revealed.shape[-1] != mask.shape[-1]:
            raise ValueError("the verified mask and the revealed rho must agree in width")
        if np.any(~np.isfinite(revealed) & mask):
            raise ValueError("a verified asset has no revealed rho")
        base = np.where(mask, revealed, np.broadcast_to(base, revealed.shape))
    return 100.0 * base


def _forbid_truth(rho_true, who: str) -> None:
    """The information boundary (protocol s. 6, s. 12): a deployable ranking must run with
    `rho_true` unset. It is accepted only as None or as all-NaN, which is what `reveal`
    returns for the assets a policy has not verified."""
    if rho_true is None:
        return
    arr = np.asarray(rho_true, dtype=float)
    if arr.size and np.isfinite(arr).any():
        raise ValueError(
            f"{who} is deployable and must not read rho_true (protocol s. 6, s. 12): "
            "truth reaches a policy only through reveal() for assets it has verified"
        )


def _deployable(fn: Callable) -> Callable:
    fn.deployable = True
    return fn


# --- H. the rankings (protocol s. 6) -------------------------------------------------------


class Ranking(NamedTuple):
    """`order` holds the ranked columns (descending `score`, ties by the lower column)."""

    order: np.ndarray
    score: np.ndarray


class Blocking(NamedTuple):
    """`counts` per table column, `blocks` the (steps x columns) mask of blocking events,
    `level` the decision the count was taken under."""

    counts: np.ndarray
    blocks: np.ndarray
    level: np.ndarray


def _rank(pool: np.ndarray, score: np.ndarray) -> Ranking:
    order = np.lexsort((pool, -score))  # descending score, ties by the lower column
    return Ranking(pool[order], score[order])


@_deployable
def rank_loading(table: DecisionTable, pool=None, *, rho_true=None) -> Ranking:
    """B6, protocol s. 6: rank the candidates by their planning-period maximum **no-cap**
    (level 0) loading, in % of the record."""
    _forbid_truth(rho_true, "rank_loading (B6)")
    sel = np.asarray(pool, int).reshape(-1) if pool is not None else np.arange(table.n_table)
    load = np.where(np.isfinite(table.load[:, 0, :]), table.load[:, 0, :], -np.inf)
    score = load[:, sel].max(axis=0) if table.n_steps else np.full(sel.size, -np.inf)
    return _rank(sel, np.asarray(score, dtype=float))


def blocking_counts(table: DecisionTable, thr_line, thr_trafo=100.0) -> Blocking:
    """B7's blocking definition (protocol s. 6): under the decision taken at `thr_line`, count
    for every table column the steps where it exceeds its believed threshold **at the level
    just above the chosen one**. Co-blocking columns each count, and a NaN loading counts as
    blocking. A step already at level 0 has no level above it and therefore no blocker; an
    `infeasible` step sits at level 10 and is counted at level 9 like any other."""
    thr, _ = _thr_lines(thr_line, table.n_table)
    if thr.shape[0] != 1:
        raise ValueError("blocking_counts takes one believed threshold vector, not a batch")
    thr = np.broadcast_to(thr, (1, table.n_table))[0]
    level = decide(table, thr, thr_trafo).level
    above = level - 1
    steps = np.flatnonzero(above >= 0)
    blocks = np.zeros((table.n_steps, table.n_table), dtype=bool)
    if steps.size:
        load_above = table.load[steps, above[steps], :]
        blocks[steps] = ~(load_above <= thr[None, :])  # a NaN loading blocks
    return Blocking(blocks.sum(axis=0), blocks, level)


@_deployable
def rank_binding(table: DecisionTable, lb: float, pool=None, thr_trafo=100.0, *, rho_true=None):
    """B7, protocol s. 6: rank the candidates by how often they block under B2."""
    _forbid_truth(rho_true, "rank_binding (B7)")
    sel = np.asarray(pool, int).reshape(-1) if pool is not None else candidate_pool(table, lb)
    counts = blocking_counts(table, 100.0 * float(lb), thr_trafo).counts
    return _rank(sel, counts[sel].astype(float))


class GreedyResult(NamedTuple):
    """`units` in the order chosen, `segments` the verified columns, `expected` the expected
    P-period export after 0, 1, ... units, `gains` the increments, `n_units` / `n_segments`
    the realised counts, `evaluated` the number of candidate sets scored and `pairs` how many
    of those were pairs (protocol s. 6 B8P, s. 10)."""

    units: tuple[int, ...]
    segments: np.ndarray
    expected: np.ndarray
    gains: np.ndarray
    n_units: int
    n_segments: int
    evaluated: int
    pairs: int


def _unit_list(table: DecisionTable, lb: float, unit_groups) -> list[np.ndarray]:
    if unit_groups is None:
        return [np.array([j]) for j in candidate_pool(table, lb)]
    out = [np.asarray(g, dtype=int).reshape(-1) for g in unit_groups]
    for g in out:
        if g.size == 0:
            raise ValueError("a verification unit must hold at least one column")
        if np.any(g < 0) or np.any(g >= table.n_table):
            raise ValueError("a unit refers to a column outside the table")
    return out


def _reduction_for(table: DecisionTable, units: list[np.ndarray], budget: int) -> Reduction:
    """A reduction wide enough for the largest set this greedy can reach, in table **columns**:
    the greedy may take one unit past its budget, and a unit may be a whole route."""
    return reduction_for(table, reveal_width(units, int(budget) + 1))


@_deployable
def greedy_voi(
    table: DecisionTable,
    prior_rho,
    lb: float,
    budget: int,
    unit_groups=None,
    *,
    thr_trafo=100.0,
    red: Reduction | None = None,
    rho_true=None,
) -> GreedyResult:
    """B8, protocol s. 6: myopic VoI greedy. Repeatedly add the unit with the largest expected
    planning-period export gain given those already chosen, averaging over the prior samples.

    **Non-adaptive** (protocol s. 6, revision 2.1): the whole set is planned from the prior
    before any verification, so no revealed rating ever enters the choice. The asymmetry with
    the adaptive B9 (`route_rule`) is disclosed, not corrected.

    `budget` counts **units** (segments under U0/U2/U3/U2', routes under U4 via
    `unit_groups`). Units are the candidate pool's columns unless `unit_groups` is given. The
    greedy keeps adding until the budget or the pool is exhausted, even where the best gain is
    zero, so that every budget has a realised count to be scored at (protocol s. 7, H3b).
    """
    _forbid_truth(rho_true, "greedy_voi (B8)")
    prior = np.atleast_2d(np.asarray(prior_rho, dtype=float))
    units = _unit_list(table, lb, unit_groups)
    budget = int(budget)
    if red is None:
        red = _reduction_for(table, units, budget)

    chosen: list[int] = []
    sel: list[int] = []
    expected = [float(_set_exports(table, prior, lb, sel, thr_trafo, red).mean())]
    gains: list[float] = []
    remaining = set(range(len(units)))
    evaluated = 0
    while len(chosen) < budget and remaining:
        best_unit, best_value = -1, -np.inf
        for unit in sorted(remaining):
            cand = sorted(set(sel) | set(units[unit].tolist()))
            value = float(_set_exports(table, prior, lb, cand, thr_trafo, red).mean())
            evaluated += 1
            if value > best_value:
                best_unit, best_value = unit, value
        chosen.append(best_unit)
        remaining.discard(best_unit)
        sel = sorted(set(sel) | set(units[best_unit].tolist()))
        gains.append(best_value - expected[-1])
        expected.append(best_value)
    return GreedyResult(
        tuple(chosen),
        np.array(sel, dtype=int),
        np.array(expected),
        np.array(gains),
        len(chosen),
        len(sel),
        evaluated,
        0,
    )


@_deployable
def greedy_voi_pairs(
    table: DecisionTable,
    prior_rho,
    lb: float,
    budget: int,
    unit_groups=None,
    *,
    thr_trafo=100.0,
    red: Reduction | None = None,
    rho_true=None,
) -> GreedyResult:
    """B8P, protocol s. 6: the same greedy with a pair look-ahead. **Non-adaptive**, like B8.

    At each step the single unit **or pair** with the largest expected gain **per added unit**
    is taken; the pair search is over all pairs of units still in the pool, and the number of
    pairs scored is reported. A tie goes to the single, then to the lower index. A pair may
    push the realised count past `budget`, which is reported (protocol s. 6, "Budgets").
    """
    _forbid_truth(rho_true, "greedy_voi_pairs (B8P)")
    prior = np.atleast_2d(np.asarray(prior_rho, dtype=float))
    units = _unit_list(table, lb, unit_groups)
    budget = int(budget)
    if red is None:
        red = _reduction_for(table, units, budget + 1)

    chosen: list[int] = []
    sel: list[int] = []
    expected = [float(_set_exports(table, prior, lb, sel, thr_trafo, red).mean())]
    gains: list[float] = []
    remaining = set(range(len(units)))
    evaluated, pairs = 0, 0
    while len(chosen) < budget and remaining:
        current = expected[-1]
        best_key: tuple | None = None
        best: tuple[tuple[int, ...], float] | None = None
        candidates: list[tuple[int, ...]] = [(u,) for u in sorted(remaining)]
        candidates += list(itertools.combinations(sorted(remaining), 2))
        for combo in candidates:
            cand = sorted(set(sel).union(*(units[u].tolist() for u in combo)))
            value = float(_set_exports(table, prior, lb, cand, thr_trafo, red).mean())
            evaluated += 1
            pairs += len(combo) == 2
            score = (value - current) / len(combo)
            key = (-score, len(combo) > 1, combo)
            if best_key is None or key < best_key:
                best_key, best = key, (combo, value)
        combo, value = best  # type: ignore[misc]
        for unit in combo:
            chosen.append(unit)
            remaining.discard(unit)
        sel = sorted(set(sel).union(*(units[u].tolist() for u in combo)))
        gains.append(value - current)
        expected.append(value)
    return GreedyResult(
        tuple(chosen),
        np.array(sel, dtype=int),
        np.array(expected),
        np.array(gains),
        len(chosen),
        len(sel),
        evaluated,
        pairs,
    )


class RouteRuleResult(NamedTuple):
    """`verified` the columns in the order they were added, `picks` the top blocker of each
    round, `n_units` / `n_segments` the realised counts (which may overshoot the budget),
    `rounds` how many times the blocking was recounted."""

    verified: np.ndarray
    picks: tuple[int, ...]
    n_units: int
    n_segments: int
    rounds: int


@_deployable
def route_rule(
    table: DecisionTable,
    lb: float,
    parent_line,
    budget: int,
    *,
    pool=None,
    unit_groups=None,
    revealed=None,
    ub: float | None = None,
    thr_trafo=100.0,
    rho_true=None,
) -> RouteRuleResult:
    """B9, protocol s. 6: the structural route rule.

    (1) among the unverified candidates, take the one blocking on the most P-steps under B2
    (B7's definition, ties by the lower line index); (2) verify every candidate segment on its
    root path, itself included, that blocks in >= 10 % of that asset's blocking steps; (3)
    substitute the verified ratings, recount the blocking and repeat from (1) until the budget
    is reached or no unverified candidate blocks.

    `parent_line` is in **network** line indices (`table.line_ids` maps them to columns);
    `pool`, `unit_groups` and `revealed` are indexed by table column. For step (3), `revealed`
    holds the revealed rho with NaN for the unverified (what `reveal` returns); where it is
    missing, a verified asset is believed at its upper bound `ub` (default 2 - lb, which is
    1 + w for lb = 1 - w), the most that verification could reveal. That keeps the rule
    deployable: it reads no truth, and a segment loaded above the upper bound still blocks.

    **Both variants of protocol s. 6 (revision 2.1) live in this one function, and the runner
    chooses between them by what it passes:**

    * **B9** (the scored policy, **adaptive**) -- the runner passes `revealed=reveal(verified,
      rho_true)` of the already-verified columns, so step (3) recounts the blocking under the
      *revealed* ratings. This is deployable because verification reveals exactly those
      ratings and nothing else; `_forbid_truth` still rejects an unmasked `rho_true`. Since the
      revealed set grows round by round, the runner re-calls `route_rule` per truth draw.
    * **B9-static** (reported descriptively) -- `revealed=None`, so every verified asset is
      believed at `ub` during planning. It reads no truth at all and is therefore identical
      across truth draws; any gap to B9 is the value of adaptivity alone.

    B8 (`greedy_voi`) and B8P (`greedy_voi_pairs`) are **non-adaptive** by contrast: they plan
    the whole set from the prior before any verification. The asymmetry is disclosed in the
    protocol (s. 6, revision 2.1).
    """
    _forbid_truth(rho_true, "route_rule (B9)")
    parent = _check_parent(parent_line)
    sel_pool = np.asarray(pool, int).reshape(-1) if pool is not None else candidate_pool(table, lb)
    in_pool = set(sel_pool.tolist())
    column_of = {int(nid): col for col, nid in enumerate(table.line_ids)}
    upper = (2.0 - float(lb)) if ub is None else float(ub)
    revealed_arr = None if revealed is None else np.asarray(revealed, dtype=float).reshape(-1)
    groups = None if unit_groups is None else _unit_list(table, lb, unit_groups)

    def unit_of(column: int) -> np.ndarray:
        if groups is None:
            return np.array([column])
        for g in groups:
            if column in g.tolist():
                return g
        return np.array([column])

    thr = np.full(table.n_table, 100.0 * float(lb))
    verified: list[int] = []
    picks: list[int] = []
    used_units: set[tuple[int, ...]] = set()
    rounds = 0
    while len(used_units) < int(budget):
        rounds += 1
        counts = blocking_counts(table, thr, thr_trafo)
        live = [c for c in sorted(in_pool) if c not in verified and counts.counts[c] > 0]
        if not live:
            break
        top = min(live, key=lambda c: (-int(counts.counts[c]), int(table.line_ids[c])))
        picks.append(top)
        top_steps = counts.blocks[:, top]
        n_top = int(top_steps.sum())
        path = root_path(parent, int(table.line_ids[top]))
        to_verify: list[int] = []
        for network_line in path:
            column = column_of.get(int(network_line), -1)
            if column < 0 or column not in in_pool:
                continue
            share = int(counts.blocks[top_steps, column].sum()) / n_top
            if column == top or share >= 0.10:
                to_verify.append(column)
        for column in to_verify:
            members = tuple(int(m) for m in unit_of(column).tolist())
            used_units.add(members)  # one verification action; a repeat costs nothing
            for member in members:
                if member in verified:
                    continue
                verified.append(member)
                if revealed_arr is not None and np.isfinite(revealed_arr[member]):
                    thr[member] = 100.0 * float(revealed_arr[member])
                else:
                    thr[member] = 100.0 * upper
    return RouteRuleResult(
        np.array(verified, dtype=int), tuple(picks), len(used_units), len(verified), rounds
    )


@_deployable
def random_orders(pool, rng: np.random.Generator, n_orders: int = 20, *, rho_true=None):
    """B5, protocol s. 6: `n_orders` uniform random verification orders of the candidate pool.
    A budget of k takes the first k entries of an order."""
    _forbid_truth(rho_true, "random_orders (B5)")
    sel = np.asarray(pool, dtype=int).reshape(-1)
    return np.stack([rng.permutation(sel) for _ in range(int(n_orders))]).reshape(
        int(n_orders), sel.size
    )


class ExhaustiveResult(NamedTuple):
    """Every enumerated subset with its E-period export and its oracle agreement, per draw.
    `subsets` is ordered by size then lexicographically; `export` and `agreement` are
    (n_subsets x draws); `oracle_export` and `b2_export` are (draws,)."""

    subsets: tuple[tuple[int, ...], ...]
    export: np.ndarray
    agreement: np.ndarray
    oracle_export: np.ndarray
    b2_export: np.ndarray
    n_subsets: int


def exhaustive_best(
    table: DecisionTable,
    rho_true,
    lb: float,
    pool_top10,
    kmax: int,
    *,
    thr_trafo=100.0,
    red: Reduction | None = None,
) -> ExhaustiveResult:
    """OB and H4 (protocol s. 6, s. 7): exhaustively score every subset of the top candidates
    up to size `kmax`, under **truth**.

    NOT DEPLOYABLE: it reads rho_true directly, which is why OB is a regret reference and H4 an
    upper bound on the minimal sufficient set within the given pool. The caller picks the best
    export per draw (OB) or the smallest subset whose oracle agreement meets H4's criterion.
    """
    rho = np.atleast_2d(np.asarray(rho_true, dtype=float))
    if not np.all(np.isfinite(rho)):
        raise ValueError("exhaustive_best needs a finite rho_true for every asset")
    pool = np.asarray(pool_top10, dtype=int).reshape(-1)
    kmax = int(min(int(kmax), pool.size))
    everything = np.arange(table.n_table)
    if red is None:  # every enumerated subset holds at most `kmax` table columns
        red = reduction_for(table, kmax)

    oracle = _set_decision(table, rho, lb, everything, thr_trafo, None)
    oracle_level = np.atleast_2d(oracle.level)
    oracle_export = np.atleast_1d(export_total(table, oracle_level))
    b2_export = _set_exports(table, rho, lb, [], thr_trafo, red)

    subsets = [
        c for size in range(1, kmax + 1) for c in itertools.combinations(pool.tolist(), size)
    ]
    export = np.empty((len(subsets), rho.shape[0]))
    agreement = np.empty((len(subsets), rho.shape[0]))
    for i, combo in enumerate(subsets):
        dec = _set_decision(table, rho, lb, np.array(combo), thr_trafo, red)
        level = np.atleast_2d(dec.level)
        export[i] = export_total(table, level)
        agreement[i] = (level == oracle_level).mean(axis=1)
    return ExhaustiveResult(
        tuple(subsets), export, agreement, oracle_export, b2_export, len(subsets)
    )


exhaustive_best.deployable = False

#: every deployable ranking, for the information-boundary test (protocol s. 6, s. 12).
DEPLOYABLE_RANKINGS: dict[str, Callable] = {
    "B5": random_orders,
    "B6": rank_loading,
    "B7": rank_binding,
    "B8": greedy_voi,
    "B8P": greedy_voi_pairs,
    "B9": route_rule,
}


# --- I. the value of information (protocol s. 5) -------------------------------------------


class VoI(NamedTuple):
    expected: float
    best: float
    worst: float


def voi(
    table: DecisionTable,
    prior_rho,
    lb: float,
    verified,
    *,
    thr_trafo=100.0,
    red: Reduction | None = None,
) -> VoI:
    """Protocol s. 5's definition, for one period table: the expected, best and worst export
    of "verify `verified`, believe the lower bound elsewhere" against B2, over the prior
    samples. s. 1.2 predicts `worst` = 0 whenever the prior's support contains the bound."""
    prior = np.atleast_2d(np.asarray(prior_rho, dtype=float))
    sel = np.asarray(verified, dtype=int).reshape(-1)
    if red is None:  # `verified` is already a column list, whatever unit it came from
        red = reduction_for(table, sel.size)
    with_set = _set_exports(table, prior, lb, sel, thr_trafo, red)
    base = _set_exports(table, prior[:1], lb, [], thr_trafo, red)[0]
    diff = with_set - base
    return VoI(float(diff.mean()), float(diff.max()), float(diff.min()))


# --- J. the metrics (protocol s. 7, s. 9) --------------------------------------------------


class Recovery(NamedTuple):
    """`r` per draw (NaN where the oracle equals B2) and `excluded`, the count of such draws."""

    r: np.ndarray
    excluded: int


def recovery(export_policy, export_b2, export_oracle) -> Recovery:
    """Protocol s. 7 (H3): R = (policy - B2) / (oracle - B2) per truth draw. A draw where the
    oracle equals B2 has nothing to recover: R is NaN and the draw is excluded, with a count."""
    policy = np.asarray(export_policy, dtype=float)
    base = np.asarray(export_b2, dtype=float)
    oracle = np.asarray(export_oracle, dtype=float)
    gap = oracle - base
    degenerate = gap == 0
    safe = np.where(degenerate, 1.0, gap)
    r = np.where(degenerate, np.nan, (policy - base) / safe)
    return Recovery(r, int(np.count_nonzero(degenerate)))


def match_budget(realised_counts, k: int) -> int | None:
    """Protocol s. 7 (H3b): the index of the largest realised count <= k, or None when the
    policy has no run at or below k (it then scores R = 0 at that budget). Ties go to the
    first such run."""
    counts = np.asarray(realised_counts, dtype=float).reshape(-1)
    ok = counts <= float(k)
    if not ok.any():
        return None
    where = np.flatnonzero(ok)
    return int(where[np.argmax(counts[where])])


class Paired(NamedTuple):
    mean: float
    se: float
    p5: float
    p95: float
    n: int


def paired_summary(diff_per_draw) -> Paired:
    """Protocol s. 9: a paired difference's mean, its Monte-Carlo standard error and its 5th
    and 95th percentiles across draws. Non-finite draws (an excluded recovery) are dropped."""
    diff = np.asarray(diff_per_draw, dtype=float).reshape(-1)
    diff = diff[np.isfinite(diff)]
    n = int(diff.size)
    if n == 0:
        return Paired(np.nan, np.nan, np.nan, np.nan, 0)
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else np.nan
    p5, p95 = (float(v) for v in np.percentile(diff, [5, 95]))
    return Paired(float(diff.mean()), se, p5, p95, n)


def fragile(margin, se):
    """Protocol s. 9: a verdict whose margin is below twice the Monte-Carlo standard error is
    flagged fragile."""
    flag = np.asarray(margin, dtype=float) < 2.0 * np.asarray(se, dtype=float)
    return bool(flag) if flag.ndim == 0 else flag


# --- K. write discipline (protocol s. 10) --------------------------------------------------


def _json_default(obj):
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"{type(obj)!r} is not JSON serialisable")


def write_json_once(path: str | Path, obj) -> Path:
    """Write JSON, refusing to overwrite: every artefact of this study is written once."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} exists; artefacts are written once and never rewritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(obj, indent=2, sort_keys=True, default=_json_default) + "\n")
    return target


def write_npz_once(path: str | Path, **arrays: np.ndarray) -> Path:
    """Write a compressed npz, refusing to overwrite."""
    target = Path(path)
    if target.exists():
        raise FileExistsError(f"{target} exists; artefacts are written once and never rewritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(target, **arrays)
    return target


def sha256_of(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def executed_text_sha(path: str | Path = PROTOCOL) -> str:
    """The sha256 of the protocol's **as-executed** text: amendments replaced by "(none)".

    Everything after the line `AMENDMENTS_HEADING` is replaced by `"(none)\\n"`, exactly as
    the amendments section itself reads before the first amendment. A dated amendment may
    therefore record a board decision without changing the text the already-counted solves
    ran under: that text must still hash to `PROTOCOL_SHA256_EXECUTED`.

    The heading must appear exactly once, at the start of a line; anything else means the
    file is not this protocol and no as-executed text can be recovered from it.
    """
    text = Path(path).read_text()
    marker = "\n" + AMENDMENTS_HEADING
    found = text.count(marker)
    if found != 1:
        raise ValueError(
            f"{path}: {AMENDMENTS_HEADING!r} starts {found} lines, expected exactly 1; "
            "the as-executed protocol text cannot be recovered"
        )
    head = text[: text.index(marker) + len(marker)]
    return hashlib.sha256((head + "\n(none)\n").encode("utf-8")).hexdigest()


def check_protocol(path: str | Path = PROTOCOL, expected: str = PROTOCOL_SHA256_EXECUTED) -> str:
    """Raise unless the protocol's **as-executed** text hashes to `expected`; return the
    sha256 of the whole file, which every artefact records.

    Amendments are append-only (protocol amendment A1): appending a dated amendment leaves
    the as-executed text untouched and so is allowed, while any edit above
    `AMENDMENTS_HEADING` is refused. Every stage that writes an artefact calls this first, so
    no result can be produced under an edited protocol.
    """
    executed = executed_text_sha(path)
    if executed != expected:
        raise ValueError(
            f"as-executed protocol sha256 {executed} != expected {expected} ({path}): "
            f"the text above {AMENDMENTS_HEADING!r} has changed"
        )
    return sha256_of(path)
