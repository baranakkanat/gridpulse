"""Tests for the Mission 12 Stage A rating-decision core (`ratings_core.py`).

**Zero power flows and zero cache reads.** Every fixture is synthetic and round-valued: no
SimBench or IEEE number appears here, and no cable table. A table line's loading falls
linearly with the cap level, `max(base - dec * level, 0)`, with `base` and `dec` chosen by
hand so that every expected decision, blocking count, ranking and VoI below is computable on
paper.

The toy tables:

* `toy_table()` -- 4 steps, 4 table lines. Columns 0 and 1 are **co-blocking series
  segments** with identical loading (95 at no cap); column 2 is a single blocker on two
  steps; column 3 never blocks. Step D is blocked by the transformer alone.
* `cobloc_table()` -- step A twice: the only way to a larger cap is to verify **both**
  co-blockers.
* `route_table()` -- 20 steps on a 5-line tree, built for B9: a tie between two
  co-blockers, a path member at exactly the 10 % rule's boundary, a pool member on the path
  that blocks in 0 % of the top blocker's steps, and a blocker that only appears after the
  verified ratings are substituted.
"""

from __future__ import annotations

import ast
import itertools
import sys
import time
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import ratings_core as rc  # noqa: E402

NET = "toy"  # a seed label, not a real network
LB = 0.8  # the believed lower bound of U2 at w = 0.2 and of U3
UB = 1.2

# --- the synthetic fixtures ----------------------------------------------------------------


def _ramp(base, dec, n_levels: int = rc.N_LEVELS) -> np.ndarray:
    """(levels x units): `max(base - dec * level, 0)`, non-increasing in the level index."""
    level = np.arange(n_levels)[:, None]
    return np.maximum(np.asarray(base, float)[None, :] - np.asarray(dec, float)[None, :] * level, 0)


def step(base, dec, trafo=(70.0, 2.0), export=(10.0, 1.0), volt_ok=True) -> dict:
    """One step of a decision table, every quantity a ramp in the level index."""
    return {
        "load": _ramp(base, dec),
        "trafo": _ramp([trafo[0]], [trafo[1]])[:, 0],
        "export": _ramp([export[0]], [export[1]])[:, 0],
        "volt_ok": np.full(rc.N_LEVELS, bool(volt_ok)),
    }


def build(steps: list[dict], line_ids) -> rc.DecisionTable:
    return rc.DecisionTable(
        load=np.stack([s["load"] for s in steps]),
        trafo=np.stack([s["trafo"] for s in steps]),
        volt_ok=np.stack([s["volt_ok"] for s in steps]),
        export=np.stack([s["export"] for s in steps]),
        line_ids=np.asarray(line_ids, int),
    )


STEP_A = step([95, 95, 60, 40], [10, 10, 5, 4])  # the co-blocking pair, B2 -> level 2
STEP_B = step([60, 60, 90, 30], [5, 5, 10, 3], export=(20.0, 2.0))  # column 2 alone, level 1
STEP_D = step([50, 50, 50, 40], [5, 5, 5, 4], trafo=(110.0, 20.0), export=(12.0, 1.0))

TOY_IDS = (10, 11, 12, 13)  # network line indices of the table columns
#: a parent-pointer description covering those network indices: 10 is a feeder head, then a
#: chain 10 <- 11 <- 12 <- 13. Lines 0 to 9 are not table lines and are left as heads.
TOY_PARENT = np.array([-1] * 11 + [10, 11, 12])


def toy_table() -> rc.DecisionTable:
    return build([STEP_A, STEP_B, STEP_B, STEP_D], TOY_IDS)


def cobloc_table() -> rc.DecisionTable:
    return build([STEP_A, STEP_A], TOY_IDS)


#: B9's tree: line 0 is the feeder head, 1 <- 0, 2 <- 1, 3 <- 2 is the trunk, 4 <- 0 branches.
ROUTE_PARENT = np.array([-1, 0, 1, 2, 0])


def route_table() -> rc.DecisionTable:
    trunk, branch = [], []
    for t in range(10):  # the trunk steps: columns 2 and 3 co-block, column 1 only in step 0
        one = 95 if t == 0 else 50
        trunk.append(step([50, one, 95, 95, 90], [2, 10, 10, 10, 20], trafo=(60.0, 0.0)))
    for t in range(10):  # the branch steps: column 0 blocks on 3 of them
        zero = 90 if t < 3 else 50
        branch.append(step([zero, 50, 50, 50, 50], [20, 2, 2, 2, 0], trafo=(60.0, 0.0)))
    return build(trunk + branch, (0, 1, 2, 3, 4))


def big_table(n_steps: int = 2000, n_lines: int = 22, seed: int = 3) -> rc.DecisionTable:
    """A larger synthetic table for the micro-benchmark only: round loadings in 5 % steps."""
    rng = np.random.default_rng(seed)
    base = rng.integers(14, 24, size=(n_steps, n_lines)) * 5.0
    dec = rng.integers(1, 4, size=(n_steps, n_lines)) * 5.0
    level = np.arange(rc.N_LEVELS)[None, :, None]
    load = np.maximum(base[:, None, :] - dec[:, None, :] * level, 0.0)
    trafo = np.maximum(rng.integers(12, 20, size=n_steps)[:, None] * 5.0 - 2.0 * level[:, :, 0], 0)
    export = np.maximum(10.0 - np.arange(rc.N_LEVELS)[None, :], 0.0).repeat(n_steps, axis=0)
    return rc.DecisionTable(
        load=load,
        trafo=trafo,
        volt_ok=np.ones((n_steps, rc.N_LEVELS), bool),
        export=export,
        line_ids=np.arange(n_lines),
    )


# --- the zero-flow rule --------------------------------------------------------------------


def test_no_power_flow_package_is_imported():
    """The core must not pull in a solver at all: this task runs zero flows.

    The check parses the module's own source, so it is independent of collection order.
    """
    tree = ast.parse(Path(rc.__file__).read_text())
    forbidden = ("pandapower", "simbench")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] not in forbidden, f"ratings_core imports {name}"


# --- A. constants and seeds ----------------------------------------------------------------


def test_cap_levels_and_constants_match_the_protocol():
    assert rc.CAP_LEVELS.size == 11
    assert rc.CAP_LEVELS[0] == 1.0 and rc.CAP_LEVELS[rc.LEVEL_ZERO] == 0.0
    assert np.allclose(np.diff(rc.CAP_LEVELS), -0.1)
    assert rc.SEED_ROOT == 20261026
    assert rc.TOL_UNSAFE == 0.5
    assert rc.PURPOSES == ("truth", "prior", "random_order")


def test_rng_for_is_deterministic_and_separates_its_streams():
    first = rc.rng_for(NET, "U2", "truth", 0).random(4)
    again = rc.rng_for(NET, "U2", "truth", 0).random(4)
    assert np.array_equal(first, again)
    for other in (
        rc.rng_for(NET, "U2", "truth", 1).random(4),
        rc.rng_for(NET, "U3", "truth", 0).random(4),
        rc.rng_for(NET, "U2", "prior", 0).random(4),
        rc.rng_for("other", "U2", "truth", 0).random(4),
    ):
        assert not np.array_equal(first, other)
    with pytest.raises(ValueError, match="purpose"):
        rc.rng_for(NET, "U2", "oracle")


# --- B. the table --------------------------------------------------------------------------


def test_decision_table_validates_its_shapes_and_keeps_float32_loadings():
    table = toy_table()
    assert table.load.dtype == np.float32
    assert (table.n_steps, table.n_levels, table.n_table) == (4, 11, 4)
    assert np.array_equal(table.column_of([12, 10, 99]), [2, 0, -1])
    with pytest.raises(ValueError, match="line ids"):
        build([STEP_A], (1, 2, 3))
    bad = toy_table()
    with pytest.raises(ValueError, match="levels"):
        rc.DecisionTable(bad.load[:, :5], bad.trafo, bad.volt_ok, bad.export, bad.line_ids)


def test_table_line_mask_takes_the_p_or_e_maximum():
    mask = rc.table_line_mask([60.0, 80.0, 10.0], [10.0, 10.0, 71.0])
    assert np.array_equal(mask, [False, True, True])
    with pytest.raises(ValueError, match="shape"):
        rc.table_line_mask([1.0], [1.0, 2.0])


def test_candidate_pool_certifies_the_irrelevant_columns():
    assert np.array_equal(rc.candidate_pool(toy_table(), LB), [0, 1, 2])  # column 3 peaks at 40


# --- C. the decision rule ------------------------------------------------------------------


def test_decide_takes_the_first_admissible_level():
    table = toy_table()
    dec = rc.decide(table, 100.0 * LB, 100.0)
    assert np.array_equal(dec.level, [2, 1, 1, 1])  # A: co-blockers; B/C: column 2; D: trafo
    assert not dec.infeasible.any()
    assert rc.export_total(table, dec.level) == pytest.approx(8 + 18 + 18 + 11)

    oracle = rc.decide(table, 100.0, 100.0)
    assert np.array_equal(oracle.level, [0, 0, 0, 1])  # step D is still blocked by the trafo
    assert rc.export_total(table, oracle.level) == pytest.approx(10 + 20 + 20 + 11)


def test_decide_respects_the_transformer_and_the_voltage_margins():
    table = build([STEP_A], TOY_IDS)
    assert rc.decide(table, 100.0, 100.0).level == 0
    assert rc.decide(table, 100.0, 60.0).level == 5  # trafo 70 - 2*level <= 60
    dark = build([{**STEP_A, "volt_ok": np.array([False] + [True] * 10)}], TOY_IDS)
    assert rc.decide(dark, 100.0, 100.0).level == 1


def test_decide_applies_the_nan_rule_at_every_quantity():
    for quantity in ("load", "trafo", "export"):
        spec = {k: v.copy() for k, v in STEP_D.items()}
        if quantity == "load":
            spec["load"][0, 2] = np.nan  # one table line at the no-cap level
        else:
            spec[quantity][0] = np.nan
        table = build([spec], TOY_IDS)
        assert not table.finite[0, 0] and table.finite[0, 1]
        dec = rc.decide(table, 100.0, 200.0)  # the transformer is wide open here
        assert dec.level == 1, f"a NaN {quantity} must make level 0 inadmissible"
    # a NaN loading at every level of a step leaves nothing admissible
    spec = {k: v.copy() for k, v in STEP_D.items()}
    spec["load"][:, 2] = np.nan
    dec = rc.decide(build([spec], TOY_IDS), 100.0, 200.0)
    assert dec.level == rc.LEVEL_ZERO and bool(dec.infeasible)


def test_decide_flags_infeasible_at_level_ten():
    hopeless = step([200, 50, 50, 40], [0, 5, 5, 4])
    table = build([STEP_A, hopeless], TOY_IDS)
    dec = rc.decide(table, 100.0 * LB, 100.0)
    assert np.array_equal(dec.level, [2, rc.LEVEL_ZERO])
    assert np.array_equal(dec.infeasible, [False, True])


def test_decide_batch_equals_the_loop_over_draws():
    table = toy_table()
    rng = np.random.default_rng(11)
    thr = 100.0 * rng.uniform(LB, UB, size=(7, table.n_table))
    thr_t = 100.0 * rng.uniform(0.9, 1.1, size=7)
    batch = rc.decide(table, thr, thr_t)
    assert batch.level.shape == (7, table.n_steps)
    for d in range(7):
        one = rc.decide(table, thr[d], float(thr_t[d]))
        assert np.array_equal(batch.level[d], one.level)
        assert np.array_equal(batch.infeasible[d], one.infeasible)


def test_decide_is_monotone_in_the_believed_thresholds():
    table = toy_table()
    rng = np.random.default_rng(5)
    low = 100.0 * rng.uniform(0.7, 1.0, size=(20, table.n_table))
    high = low + 100.0 * rng.uniform(0.0, 0.3, size=(20, table.n_table))
    assert np.all(rc.decide(table, high, 100.0).level <= rc.decide(table, low, 100.0).level)


def test_b3_equals_b2_when_the_prior_contains_the_corner():
    table = toy_table()
    prior = np.vstack(
        [
            np.full(table.n_table, LB),  # the lower corner of U2's box
            np.full(table.n_table, 1.0),
            np.full(table.n_table, UB),
        ]
    )
    b2 = rc.beliefs("B2", LB, n_lines=table.n_table)
    b3 = rc.beliefs("B3", LB, None, prior, n_lines=table.n_table)
    assert np.array_equal(b2, b3)
    assert np.array_equal(rc.decide(table, b2, 100.0).level, rc.decide(table, b3, 100.0).level)
    # B3 is the sampled scenario minimum and is not capped at the bound, so protocol s. 8's
    # "B3 = B2" control is a real check: a sample that misses the corner can decide otherwise.
    off_corner = np.vstack([np.full(table.n_table, 0.9), np.full(table.n_table, 1.0)])
    b3_off = rc.beliefs("B3", LB, None, off_corner, n_lines=table.n_table)
    assert np.all(b3_off == 90.0)
    assert not np.array_equal(
        rc.decide(table, b3_off, 100.0).level, rc.decide(table, b2, 100.0).level
    )


def test_outcome_counts_unsafe_steps_and_reports_severity():
    table = build([STEP_A], TOY_IDS)
    levels = np.array([0])  # loading 95 on columns 0 and 1, transformer 70
    safe = rc.outcome(table, levels, np.full(4, 0.96), 1.0)
    assert safe.unsafe_steps == 0
    assert safe.max_severity == pytest.approx(95 / 0.96 - 100, abs=1e-4)
    unsafe = rc.outcome(table, levels, np.full(4, 0.9), 1.0)
    assert unsafe.unsafe_steps == 1  # 95 / 0.9 = 105.6 % > 100.5 %
    assert unsafe.max_severity == pytest.approx(95 / 0.9 - 100, abs=1e-4)
    assert rc.outcome(table, levels, np.full(4, 1.0), 0.6).unsafe_steps == 1  # 70 / 0.6
    tol = rc.outcome(table, levels, np.array([95 / 100.5, 1.0, 1.0, 1.0]), 1.0)
    assert tol.unsafe_steps == 0  # exactly at the 100.5 % tolerance


def test_outcome_batches_over_draws_and_never_calls_a_nan_step_safe():
    table = toy_table()
    rho = np.vstack([np.full(4, 1.0), np.full(4, 0.9)])
    levels = rc.decide(table, 100.0, 100.0).level
    batched = rc.outcome(table, levels, rho, np.ones(2))
    for d in range(2):
        one = rc.outcome(table, levels, rho[d], 1.0)
        assert batched.export[d] == pytest.approx(one.export)
        assert batched.unsafe_steps[d] == one.unsafe_steps
    spec = {k: v.copy() for k, v in STEP_A.items()}
    spec["load"][:, 0] = np.nan
    out = rc.outcome(build([spec], TOY_IDS), np.array([rc.LEVEL_ZERO]), np.full(4, 1.0), 1.0)
    assert out.unsafe_steps == 1  # the NaN rule: a step with a NaN is never counted safe
    blind = {k: v.copy() for k, v in STEP_A.items()}
    blind["load"][:] = np.nan
    blind["trafo"][:] = np.nan
    out = rc.outcome(build([blind], TOY_IDS), np.array([rc.LEVEL_ZERO]), np.full(4, 1.0), 1.0)
    assert out.unsafe_steps == 1 and np.isnan(out.max_severity)


def test_any_belief_below_the_truth_is_never_unsafe():
    """The verification-safety property (protocol s. 1.2, H5a): a policy that believes
    rho_hat <= rho_true on every asset cannot be unsafe, because its admissible set lies
    inside the oracle's -- provided some level is admissible, which is why the draws below
    keep the transformer's belief above the toy's cap-0 loading."""
    table = toy_table()
    rng = np.random.default_rng(23)
    for _ in range(200):
        rho_true = rng.uniform(0.7, 1.3, size=table.n_table)
        rho_t = rng.uniform(0.7, 1.3)
        belief = 100.0 * rho_true * rng.uniform(0.3, 1.0, size=table.n_table)
        belief_t = 100.0 * rho_t * rng.uniform(0.75, 1.0)
        level = rc.decide(table, belief, belief_t)
        assert np.all(belief <= 100.0 * rho_true) and belief_t <= 100.0 * rho_t
        assert not level.infeasible.any()  # the toy is feasible at every step
        assert rc.outcome(table, level.level, rho_true, rho_t).unsafe_steps == 0


def test_situation_is_one_where_the_decision_is_bound_invariant():
    table = toy_table()
    sit = rc.situation(table, 100.0 * LB, 100.0 * UB)
    assert np.array_equal(sit, [2, 2, 2, 1])  # only step D decides alike at both bounds
    flat = rc.situation(table, 100.0 * LB, 100.0 * LB)
    assert np.all(flat == 1)


# --- D. the s. 10 reduction ----------------------------------------------------------------


def test_top_reduction_orders_the_loadings_and_ranks_nan_first():
    table = toy_table()
    red = rc.top_reduction(table, 3)
    assert red.k == 3
    assert np.array_equal(red.index[0, 0], [0, 1, 2])  # 95, 95, 60
    assert np.allclose(red.values[0, 0], [95, 95, 60])
    spec = {k: v.copy() for k, v in STEP_A.items()}
    spec["load"][0, 3] = np.nan
    red_nan = rc.top_reduction(build([spec], TOY_IDS), 2)
    assert red_nan.index[0, 0, 0] == 3 and np.isposinf(red_nan.values[0, 0, 0])


@pytest.mark.parametrize("size", [0, 1, 2, 3, 4])
def test_decide_reduced_equals_the_full_rule(size):
    table = toy_table()
    red = rc.top_reduction(table, rc.TOP_K_DEFAULT)
    rng = np.random.default_rng(size + 1)
    for verified in itertools.combinations(range(table.n_table), size):
        rho = rng.uniform(0.7, 1.3, size=(4, table.n_table))  # includes rho < lb (U2')
        thr = np.full((4, table.n_table), 100.0 * LB)
        sel = np.array(verified, int)
        if sel.size:
            thr[:, sel] = 100.0 * rho[:, sel]
        full = rc.decide(table, thr, 100.0)
        reduced = rc.decide_reduced(
            table, red, sel, thr[:, sel] if sel.size else np.zeros((4, 0)), 100.0 * LB, 100.0
        )
        assert np.array_equal(full.level, reduced.level)
        assert np.array_equal(full.infeasible, reduced.infeasible)


def test_reveal_width_counts_columns_not_units():
    """Amendment A2: a route unit reveals every segment on it, so the unit count under-sizes
    a reduction. `reveal_width` answers in table columns."""
    routes = [np.array([0, 1, 2]), np.array([3]), np.array([4, 5])]
    assert rc.reveal_width(routes) == 6
    assert rc.reveal_width(routes, 1) == 3  # the widest single unit
    assert rc.reveal_width(routes, 2) == 5  # the two widest
    assert rc.reveal_width(routes, 0) == 0
    assert rc.reveal_width(routes, 9) == 6  # never more than every unit holds
    assert rc.reveal_width([np.array([j]) for j in range(4)], 2) == 2  # segment units


def test_reduction_for_sizes_from_the_columns_and_caps_at_the_table_width():
    table = toy_table()  # 4 columns
    assert rc.reduction_for(table, 0).k == 1
    assert rc.reduction_for(table, 2).k == 3
    assert rc.reduction_for(table, 3).k == 4  # k = n_table, not 4 + 1
    assert rc.reduction_for(table, 4).k == 4  # a whole-table set is exact at k = n_table
    assert rc.reduction_for(table, 99).k == 4


def test_a_route_unit_wider_than_the_pool_is_still_exact():
    """The A2 regression at core level: a reduction sized for a 2-column pool is too narrow
    for a route unit that spans every table column, and `decide_reduced` says so instead of
    truncating. Sized by `reduction_for` on the revealed **columns**, it is exact again."""
    table = toy_table()
    pool_cols, route_cols = (0, 1), tuple(range(table.n_table))
    narrow = rc.reduction_for(table, len(pool_cols))  # the A2 defect's width: k = 3
    assert narrow.k == 3
    with pytest.raises(ValueError, match="too few"):
        rc.decide_reduced(table, narrow, route_cols, np.full(len(route_cols), 100.0), 80.0, 100.0)

    wide = rc.reduction_for(table, rc.reveal_width([np.array(route_cols), np.array(pool_cols)], 1))
    assert wide.k == table.n_table
    rng = np.random.default_rng(42)
    for cols in (pool_cols, route_cols, (2,), ()):
        sel = np.array(cols, int)
        rho = rng.uniform(0.7, 1.3, size=(3, table.n_table))  # includes rho < lb (U2')
        thr = np.full((3, table.n_table), 100.0 * LB)
        if sel.size:
            thr[:, sel] = 100.0 * rho[:, sel]
        full = rc.decide(table, thr, 100.0)
        reduced = rc.decide_reduced(
            table, wide, sel, thr[:, sel] if sel.size else np.zeros((3, 0)), 100.0 * LB, 100.0
        )
        assert np.array_equal(full.level, reduced.level)
        assert np.array_equal(full.infeasible, reduced.infeasible)


def test_decide_reduced_refuses_a_reduction_that_is_too_narrow():
    table = toy_table()
    red = rc.top_reduction(table, 2)
    with pytest.raises(ValueError, match="too few"):
        rc.decide_reduced(table, red, [0, 1, 2], np.full(3, 100.0), 100.0 * LB, 100.0)
    with pytest.raises(ValueError, match="repeat"):
        rc.decide_reduced(table, red, [1, 1], np.full(2, 100.0), 100.0 * LB, 100.0)


@pytest.mark.parametrize("n_steps", [2000, 8000])
def test_the_reduction_micro_benchmark(capsys, n_steps):
    """Protocol s. 10's reduction, timed but not asserted (reported in the task record).

    8,000 steps x 11 levels x 22 lines is the scale of one period table of the largest
    cable-limited network, and 100 draws is the shared prior sample.
    """
    table = big_table(n_steps=n_steps)
    n_draws, verified = 100, np.array([0, 3, 7])
    rho = np.random.default_rng(1).uniform(0.8, 1.2, size=(n_draws, table.n_table))
    thr = np.full((n_draws, table.n_table), 100.0 * LB)
    thr[:, verified] = 100.0 * rho[:, verified]

    start = time.perf_counter()
    full = rc.decide(table, thr, 100.0)
    t_full = time.perf_counter() - start
    start = time.perf_counter()
    red = rc.top_reduction(table, rc.TOP_K_DEFAULT)
    t_build = time.perf_counter() - start
    start = time.perf_counter()
    reduced = rc.decide_reduced(table, red, verified, thr[:, verified], 100.0 * LB, 100.0)
    t_red = time.perf_counter() - start

    assert np.array_equal(full.level, reduced.level)
    with capsys.disabled():
        print(
            f"\n[micro-benchmark] {table.n_steps} steps x {rc.N_LEVELS} levels x "
            f"{table.n_table} lines, {n_draws} draws, |S| = {verified.size}: "
            f"decide {t_full * 1e3:.1f} ms, top_reduction {t_build * 1e3:.1f} ms (once), "
            f"decide_reduced {t_red * 1e3:.1f} ms (speed-up {t_full / t_red:.1f}x)"
        )


# --- E. topology ---------------------------------------------------------------------------


def test_root_path_walks_to_the_feeder_head():
    assert np.array_equal(rc.root_path(ROUTE_PARENT, 3), [3, 2, 1, 0])
    assert np.array_equal(rc.root_path(ROUTE_PARENT, 4), [4, 0])
    assert np.array_equal(rc.root_path(ROUTE_PARENT, 0), [0])
    with pytest.raises(ValueError, match="cycle"):
        rc.root_path(np.array([1, 2, 1]), 0)
    with pytest.raises(ValueError, match="outside"):
        rc.root_path(ROUTE_PARENT, 9)


def test_routes_are_same_type_components_inside_one_feeder():
    #        0 -- 1 -- 2 (type A, feeder 0) | 3 (type B) -- 6 (type A, feeder 0, detached)
    #        4 -- 5 (type A, feeder 1)
    parent = np.array([-1, 0, 1, 1, -1, 4, 3])
    std = np.array(["A", "A", "A", "B", "A", "A", "A"])
    feeder = np.array([0, 0, 0, 0, 1, 1, 0])
    route = rc.routes(parent, std, feeder)
    assert np.array_equal(route, [0, 0, 0, 1, 2, 2, 3])  # labels by first appearance
    assert route[4] != route[0]  # same type, different feeder
    assert route[6] != route[0]  # same type and feeder, not connected
    with pytest.raises(ValueError, match="one entry per line"):
        rc.routes(parent, std[:3], feeder)
    with pytest.raises(ValueError, match="own parent"):
        rc.routes(np.array([0, 0]), std[:2], feeder[:2])


def test_groups_from_routes_builds_the_u4_units():
    groups = rc.groups_from_routes(np.array([0, 0, 1, 1]), np.array([0, 1, 2]))
    assert [g.tolist() for g in groups] == [[0, 1], [2]]


# --- F. the uncertainty models -------------------------------------------------------------


def test_rho_bounds_per_model_believed_and_true():
    assert rc.rho_bounds("U0") == (0.8, 1.2, 1.0, 1.0)
    assert rc.rho_bounds("U0", kind="true") == (1.0, 1.0, 1.0, 1.0)
    assert rc.rho_bounds("U2", w=0.3) == (0.7, 1.3, 1.0, 1.0)
    assert rc.rho_bounds("U3")[:2] == (0.8, 1.25)
    assert rc.rho_bounds("U4") == (0.8, 1.2, 1.0, 1.0)
    assert rc.rho_bounds("U-T") == (1.0, 1.0, 0.8, 1.2)
    assert rc.rho_bounds("U2'")[:2] == (0.8, 1.2)  # every policy believes w = 0.2
    assert rc.rho_bounds("U2'", kind="true")[:2] == (0.7, 1.3)  # the truth is drawn at 0.3
    with pytest.raises(ValueError, match="model"):
        rc.rho_bounds("U9")


def test_sample_rho_respects_the_bounds_and_the_seed():
    rng = rc.rng_for(NET, "U2", "truth", 0)
    draws = rc.sample_rho("U2", 5, rng, 500)
    assert draws.shape == (500, 5)
    assert draws.min() >= 0.8 and draws.max() <= 1.2
    again = rc.sample_rho("U2", 5, rc.rng_for(NET, "U2", "truth", 0), 500)
    assert np.array_equal(draws, again)

    assert np.all(rc.sample_rho("U0", 3, rng, 10) == 1.0)
    assert np.all(rc.sample_rho("U0", 3, rng, 10, kind="prior") >= 0.8)
    u3 = rc.sample_rho("U3", 4, rng, 400)
    assert set(np.unique(u3).tolist()) <= set(rc.U3_CLASSES)
    assert np.all(rc.sample_rho("UT", 3, rng, 5) == 1.0)  # U-T's lines are known


def test_sample_rho_u4_shares_one_draw_per_route():
    rng = rc.rng_for(NET, "U4", "truth", 0)
    route = np.array([0, 0, 1, 1, 1])
    draws = rc.sample_rho("U4", 5, rng, 50, route_of_line=route)
    assert np.array_equal(draws[:, 0], draws[:, 1])
    assert np.array_equal(draws[:, 2], draws[:, 4])
    assert not np.array_equal(draws[:, 0], draws[:, 2])
    assert draws.min() >= 0.8 and draws.max() <= 1.2
    with pytest.raises(ValueError, match="route_of_line"):
        rc.sample_rho("U4", 5, rng, 5)


def test_sample_rho_u2_prime_draws_wide_truths_and_narrow_beliefs():
    rng = rc.rng_for(NET, "U2P", "truth", 0)
    truth = rc.sample_rho("U2'", 4, rng, 2000)
    assert truth.min() < 0.8 and truth.max() > 1.2  # the truth escapes the believed box
    assert truth.min() >= 0.7 and truth.max() <= 1.3
    prior = rc.sample_rho("U2'", 4, rng, 2000, kind="prior")
    assert prior.min() >= 0.8 and prior.max() <= 1.2


def test_sample_rho_trafo_is_known_except_under_ut():
    rng = rc.rng_for(NET, "UT", "truth", 0)
    assert np.all(rc.sample_rho_trafo("U2", rng, 7) == 1.0)
    trafo = rc.sample_rho_trafo("U-T", rng, 500)
    assert trafo.min() >= 0.8 and trafo.max() <= 1.2


# --- G. beliefs and the information boundary -----------------------------------------------


def test_beliefs_per_policy():
    n = 4
    assert np.all(rc.beliefs("B0", LB, n_lines=n) == 100.0)
    assert np.all(rc.beliefs("B1", LB, n_lines=n) == 90.0)  # 1 - w/2 at lb = 1 - w
    assert np.all(rc.beliefs("B2", LB, n_lines=n) == 80.0)
    truth = np.array([1.0, 1.1, 0.9, 1.2])
    assert np.allclose(rc.beliefs("B4", LB, None, truth), 100.0 * truth)
    mask = np.array([True, False, True, False])
    revealed = rc.reveal(np.flatnonzero(mask), truth)
    assert np.allclose(rc.beliefs("B7", LB, mask, revealed), [100.0, 80.0, 90.0, 80.0])
    with pytest.raises(ValueError, match="no revealed rho"):
        rc.beliefs("B8", LB, np.ones(n, bool), revealed)
    with pytest.raises(ValueError, match="unknown policy"):
        rc.beliefs("B42", LB, n_lines=n)


def test_reveal_hands_over_the_verified_assets_only():
    truth = np.array([[1.0, 1.1, 0.9]])
    out = rc.reveal([2], truth)
    assert np.isnan(out[0, 0]) and np.isnan(out[0, 1]) and out[0, 2] == 0.9
    assert np.all(np.isnan(rc.reveal([], truth)))


def test_every_deployable_ranking_runs_with_rho_true_unset():
    """The information boundary (protocol s. 6, s. 12). Each ranking is called once with
    rho_true=None and once with an all-NaN reveal, and must refuse a finite truth."""
    table = toy_table()
    pool = rc.candidate_pool(table, LB)
    prior = np.vstack([np.full(table.n_table, LB), np.ones(table.n_table)])
    unset = rc.reveal([], np.ones(table.n_table))
    calls = {
        "B5": (rc.random_orders, (pool, rc.rng_for(NET, "U2", "random_order")), {}),
        "B6": (rc.rank_loading, (table, pool), {}),
        "B7": (rc.rank_binding, (table, LB), {}),
        "B8": (rc.greedy_voi, (table, prior, LB, 1), {}),
        "B8P": (rc.greedy_voi_pairs, (table, prior, LB, 1), {}),
        "B9": (rc.route_rule, (table, LB, TOY_PARENT, 1), {}),
    }
    assert set(calls) == set(rc.DEPLOYABLE_RANKINGS)
    for name, (fn, args, kwargs) in calls.items():
        assert rc.DEPLOYABLE_RANKINGS[name] is fn
        assert getattr(fn, "deployable", False) is True
        fn(*args, **kwargs, rho_true=None)
        fn(*args, **kwargs, rho_true=unset)
        with pytest.raises(ValueError, match="must not read rho_true"):
            fn(*args, **kwargs, rho_true=np.ones(table.n_table))
    assert rc.exhaustive_best.deployable is False


# --- H. the rankings -----------------------------------------------------------------------


def test_rank_loading_uses_the_no_cap_maximum():
    table = toy_table()
    rank = rc.rank_loading(table, rc.candidate_pool(table, LB))
    assert np.array_equal(rank.order, [0, 1, 2])  # 95, 95, 90; the tie by the lower column
    assert np.allclose(rank.score, [95, 95, 90])


def test_rank_binding_counts_co_blockers_each_and_credits_no_line_to_the_transformer():
    table = toy_table()
    blocking = rc.blocking_counts(table, 100.0 * LB)
    assert np.array_equal(blocking.counts, [1, 1, 2, 0])
    assert np.array_equal(blocking.blocks[0], [True, True, False, False])  # step A co-blocks
    assert not blocking.blocks[3].any()  # step D is blocked by the transformer alone
    assert np.array_equal(rc.rank_binding(table, LB).order, [2, 0, 1])
    with pytest.raises(ValueError, match="not a batch"):
        rc.blocking_counts(table, np.full((2, table.n_table), 80.0))


def test_a_step_at_level_zero_has_no_blocker():
    table = build([STEP_A], TOY_IDS)
    assert not rc.blocking_counts(table, 100.0).blocks.any()  # B0 already takes level 0


def test_greedy_voi_is_the_textbook_myopic_greedy_on_the_toy():
    table = toy_table()
    prior = np.ones((1, table.n_table))
    result = rc.greedy_voi(table, prior, LB, 3)
    assert result.units == (2, 0, 1)  # column 2 pays 4 MWh; the pair pays only together
    assert np.allclose(result.expected, [55, 59, 59, 61])
    assert np.allclose(result.gains, [4, 0, 2])
    assert (result.n_units, result.n_segments) == (3, 3)
    assert rc.greedy_voi(table, prior, LB, 1).units == (2,)


def test_greedy_voi_stops_at_the_pool():
    table = cobloc_table()
    result = rc.greedy_voi(table, np.ones((1, table.n_table)), LB, 8)
    assert result.n_units == rc.candidate_pool(table, LB).size == 2
    assert np.allclose(result.expected[-1], 20.0)  # both co-blockers verified: level 0 twice


def test_greedy_voi_pairs_prefers_a_single_at_a_tie_and_may_overshoot():
    table = toy_table()
    prior = np.ones((1, table.n_table))
    result = rc.greedy_voi_pairs(table, prior, LB, 2)
    assert result.units == (2, 0, 1)  # round 1: the single 2 (gain 4 > 2/2); round 2: the pair
    assert result.n_units == 3 > 2  # the pair overshoots the budget, which is reported
    assert np.allclose(result.gains, [4, 2])
    assert result.pairs == 3 + 1  # C(3, 2) pairs, then C(2, 2)


def test_route_rule_follows_the_three_steps_and_the_ten_percent_rule():
    table = route_table()
    assert np.array_equal(rc.candidate_pool(table, LB), [0, 1, 2, 3, 4])
    counts = rc.blocking_counts(table, 100.0 * LB).counts
    assert np.array_equal(counts, [3, 1, 10, 10, 0])  # column 4 blocks only after verification

    result = rc.route_rule(table, LB, ROUTE_PARENT, 4)
    # round 1: the tie between columns 2 and 3 goes to the lower index; on 2's root path,
    # column 1 blocks in exactly 1 of 10 steps (the 10 % boundary, kept) and column 0 in none;
    # round 2: column 3 is now the top blocker; round 3: column 4 appears in the recount.
    assert result.picks == (2, 3, 4)
    assert np.array_equal(result.verified, [2, 1, 3, 4])  # in the order they were verified
    assert (result.n_units, result.n_segments, result.rounds) == (4, 4, 3)

    assert rc.route_rule(table, LB, ROUTE_PARENT, 2).verified.tolist() == [2, 1]
    assert rc.route_rule(table, LB, ROUTE_PARENT, 3).picks == (2, 3)
    overshoot = rc.route_rule(table, LB, ROUTE_PARENT, 1)
    assert overshoot.n_units == 2 > 1  # the path is verified whole


def test_route_rule_stops_when_nothing_blocks_and_can_use_revealed_ratings():
    table = route_table()
    quiet = rc.route_rule(table, 1.0, ROUTE_PARENT, 4)  # believing the records, nothing blocks
    assert quiet.n_units == 0 and quiet.picks == ()
    revealed = rc.reveal([1, 2], np.full(table.n_table, 0.95))
    with_truth = rc.route_rule(table, LB, ROUTE_PARENT, 4, revealed=revealed)
    assert with_truth.picks[0] == 2  # the same first pick; the recount now uses rho = 0.95
    assert set(with_truth.verified.tolist()) >= {1, 2}


def test_route_rule_takes_whole_routes_as_units_under_u4():
    table = route_table()
    groups = [np.array([1, 2, 3]), np.array([0]), np.array([4])]
    result = rc.route_rule(table, LB, ROUTE_PARENT, 1, unit_groups=groups)
    assert result.n_units == 1 and sorted(result.verified.tolist()) == [1, 2, 3]


def test_random_orders_permutes_the_pool():
    pool = np.array([2, 5, 7])
    orders = rc.random_orders(pool, rc.rng_for(NET, "U2", "random_order"), 20)
    assert orders.shape == (20, 3)
    assert all(sorted(row.tolist()) == [2, 5, 7] for row in orders)
    again = rc.random_orders(pool, rc.rng_for(NET, "U2", "random_order"), 20)
    assert np.array_equal(orders, again)


def test_exhaustive_best_reads_truth_and_finds_the_co_blocking_pair():
    table = cobloc_table()
    truth = np.ones((1, table.n_table))
    result = rc.exhaustive_best(table, truth, LB, [0, 1, 2], 2)
    assert result.n_subsets == 3 + 3  # sizes 1 and 2 over 3 candidates
    best = int(np.argmax(result.export[:, 0]))
    assert result.subsets[best] == (0, 1)
    assert result.export[best, 0] == pytest.approx(20.0) == result.oracle_export[0]
    assert result.agreement[best, 0] == 1.0
    assert result.b2_export[0] == pytest.approx(16.0)
    singles = [i for i, s in enumerate(result.subsets) if len(s) == 1]
    assert np.allclose(result.export[singles, 0], 16.0)  # no single asset buys anything


# --- I. the value of information -----------------------------------------------------------


def test_verifying_one_co_blocker_is_worth_exactly_zero_and_the_pair_is_not():
    table = cobloc_table()
    prior = np.vstack([np.full(table.n_table, LB), np.ones(table.n_table), np.full(4, UB)])
    for single in ([0], [1], [2], [3]):
        assert rc.voi(table, prior, LB, single) == (0.0, 0.0, 0.0)
    pair = rc.voi(table, prior, LB, [0, 1])
    assert pair.expected > 0 and pair.best == pytest.approx(4.0)
    greedy = rc.greedy_voi(table, prior, LB, 1)
    assert greedy.gains[0] == 0.0  # no single asset has any value: B8 fails at k = 1
    pairs = rc.greedy_voi_pairs(table, prior, LB, 1)
    assert sorted(pairs.segments.tolist()) == [0, 1] and pairs.gains[0] > 0


@pytest.mark.parametrize("model", ["U2", "U3", "U4"])
def test_the_worst_case_value_of_information_is_zero(model):
    """Protocol s. 1.2: whenever the uncertainty set contains its own lower corner, the robust
    value after verifying any set is unchanged in the worst case."""
    table = toy_table()
    bounds = rc.rho_bounds(model)
    route = np.array([0, 0, 1, 1])
    rng = rc.rng_for(NET, model, "prior")
    prior = rc.sample_rho(model, table.n_table, rng, 20, route_of_line=route, kind="prior")
    prior = np.vstack([np.full(table.n_table, bounds.line_lb), prior])  # the corner is in it
    for verified in ([0], [2], [0, 1], [0, 1, 2, 3]):
        value = rc.voi(table, prior, bounds.line_lb, verified)
        assert value.worst == 0.0
        assert value.expected >= 0.0 and value.best >= value.expected


def test_voi_matches_an_explicit_average_over_the_prior():
    table = toy_table()
    prior = np.array([[1.0, 1.0, 1.0, 1.0], [LB, LB, LB, LB], [1.0, 0.9, 1.0, 1.0]])
    base = rc.export_total(table, rc.decide(table, 100.0 * LB, 100.0).level)
    by_hand = []
    for row in prior:
        thr = np.full(table.n_table, 100.0 * LB)
        thr[[0, 1]] = 100.0 * row[[0, 1]]
        by_hand.append(rc.export_total(table, rc.decide(table, thr, 100.0).level) - base)
    value = rc.voi(table, prior, LB, [0, 1])
    assert value.expected == pytest.approx(float(np.mean(by_hand)))
    assert value.best == pytest.approx(max(by_hand))
    assert value.worst == pytest.approx(min(by_hand))


# --- J. the metrics ------------------------------------------------------------------------


def test_recovery_excludes_the_draws_where_the_oracle_equals_b2():
    out = rc.recovery([5.0, 7.0, 3.0], [3.0, 3.0, 3.0], [7.0, 7.0, 3.0])
    assert np.allclose(out.r[:2], [0.5, 1.0])
    assert np.isnan(out.r[2]) and out.excluded == 1


def test_match_budget_takes_the_largest_realised_count_at_or_below_k():
    realised = [1, 2, 5, 3]
    assert rc.match_budget(realised, 3) == 3  # the run with 3, not the run with 2
    assert rc.match_budget(realised, 4) == 3
    assert rc.match_budget(realised, 5) == 2
    assert rc.match_budget(realised, 0) is None


def test_paired_summary_and_the_fragile_flag():
    diff = np.array([1.0, 2.0, 3.0, 4.0, np.nan])
    summary = rc.paired_summary(diff)
    assert summary.n == 4 and summary.mean == pytest.approx(2.5)
    assert summary.se == pytest.approx(np.std([1, 2, 3, 4], ddof=1) / 2.0)
    assert summary.p5 == pytest.approx(np.percentile([1, 2, 3, 4], 5))
    assert rc.paired_summary([]).n == 0
    assert rc.fragile(0.1, 0.2) is True  # 0.1 < 2 * 0.2
    assert rc.fragile(0.5, 0.2) is False
    assert np.array_equal(rc.fragile([0.1, 0.5], [0.2, 0.2]), [True, False])


# --- K. write discipline -------------------------------------------------------------------


def test_write_json_once_and_write_npz_once_refuse_to_overwrite(tmp_path):
    target = tmp_path / "nested" / "record.json"
    rc.write_json_once(target, {"export": np.float32(1.5), "levels": np.arange(2)})
    assert "1.5" in target.read_text()
    with pytest.raises(FileExistsError, match="written once"):
        rc.write_json_once(target, {"export": 2.0})
    npz = tmp_path / "table.npz"
    rc.write_npz_once(npz, load=np.zeros((2, 2)))
    with pytest.raises(FileExistsError, match="written once"):
        rc.write_npz_once(npz, load=np.ones((2, 2)))


def test_check_protocol_pins_the_as_executed_revision_and_returns_the_file_hash(tmp_path):
    # revision 2.2 as executed: the text above the amendments, which no amendment may edit.
    assert rc.PROTOCOL_SHA256_EXECUTED == (
        "9fc9108c0e70c1d2ec3eea19df659d1231ad175634aacb03a9fe326ce521af36"
    )
    assert rc.executed_text_sha() == rc.PROTOCOL_SHA256_EXECUTED
    # what the check returns, and what every artefact records, is the **whole file**
    assert rc.check_protocol() == rc.sha256_of(rc.PROTOCOL)
    stand_in = tmp_path / "not_the_protocol.md"
    stand_in.write_text("# an edited protocol\n")
    with pytest.raises(ValueError, match="cannot be recovered"):
        rc.check_protocol(stand_in)


def test_an_appended_amendment_passes_and_an_edit_above_the_heading_fails(tmp_path):
    """Amendment A1: the amendments are append-only, so only the as-executed text is pinned."""
    text = rc.PROTOCOL.read_text()
    appended = tmp_path / "appended.md"
    appended.write_text(
        text + "\n**A9 (2026-10-25; a test) -- an appended amendment.**\n- nothing changes.\n"
    )
    assert rc.executed_text_sha(appended) == rc.PROTOCOL_SHA256_EXECUTED
    assert rc.check_protocol(appended) == rc.sha256_of(appended)
    assert rc.sha256_of(appended) != rc.sha256_of(rc.PROTOCOL)  # the file hash does move

    edited = tmp_path / "edited.md"
    edited.write_text("an edit above the amendments heading\n" + text)
    with pytest.raises(ValueError, match="as-executed protocol sha256"):
        rc.check_protocol(edited)

    twice = tmp_path / "twice.md"
    twice.write_text(text + "\n" + rc.AMENDMENTS_HEADING + "\n")
    with pytest.raises(ValueError, match="starts 2 lines"):
        rc.executed_text_sha(twice)
