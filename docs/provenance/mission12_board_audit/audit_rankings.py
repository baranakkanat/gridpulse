"""Board audit (read-only, zero solves): the B6, B7, B8 and B8P orders on P, with B8's
per-step expected gains. It shows whether B8 agrees with B6 by information or only by its
tie rule (the lower unit index wins when every gain is 0).

It rebuilds exactly the inputs `cmd_evaluate` builds, using the frozen library, and writes
nothing.
"""

import sys
from pathlib import Path

import numpy as np

MODULE = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(MODULE))
import ratings_core as rc  # noqa: E402
import run_stage_a as ra  # noqa: E402

for spec in sys.argv[2:]:
    name, label = spec.split(":")
    rc_model, w = ra.EVAL_MODELS[label]
    loaded = ra.load_tables(name)
    table_p = loaded.tables["P"]
    lb = rc.rho_bounds(rc_model, w, "believed").line_lb
    route_of_column = loaded.route_of_line[table_p.line_ids]
    pool_p = rc.candidate_pool(table_p, lb)
    units = [np.array([j]) for j in pool_p]
    prior_rng = rc.rng_for(name, label, "prior")
    rho_prior = rc.sample_rho(
        rc_model, table_p.n_table, prior_rng, ra.N_PRIOR, route_of_line=route_of_column, w=w,
        kind="prior",
    )
    budgets = [k for k in ra.EVAL_BUDGETS if k <= max(len(units), 1)]
    k_max = max(budgets)
    red_p = rc.reduction_for(table_p, max(len(pool_p), 1))
    b6 = [int(c) for c in ra._lift_rank(rc.rank_loading(table_p, pool_p).order, units)]
    b7 = [int(c) for c in ra._lift_rank(rc.rank_binding(table_p, lb, pool_p).order, units)]
    g8 = rc.greedy_voi(table_p, rho_prior, lb, k_max, None, red=red_p)
    g8p = rc.greedy_voi_pairs(table_p, rho_prior, lb, k_max, None, red=red_p)
    col = lambda u: int(pool_p[u])  # noqa: E731
    print(f"== {name} {label}: pool columns {pool_p.tolist()}, k_max {k_max}")
    print(f"   B6 unit order  {b6[:k_max]}  -> columns {[col(u) for u in b6[:k_max]]}")
    print(f"   B7 unit order  {b7[:k_max]}  -> columns {[col(u) for u in b7[:k_max]]}")
    print(f"   B8 unit order  {list(g8.units)}  -> columns {[col(u) for u in g8.units]}")
    print(f"   B8 gains MWh   {[round(float(g), 4) for g in g8.gains]}")
    print(f"   B8 zero-gain steps (tie rule decides): {[i + 1 for i, g in enumerate(g8.gains) if abs(g) < 1e-12]}")
    print(f"   B8P units      {list(g8p.units)}  segments {g8p.segments.tolist()}  pairs {g8p.pairs}")
