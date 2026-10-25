"""Board audit (read-only, zero solves): why B9 scores at two units for every k <= 8 on
semiurb5 under U2.

It prints B9-static's realised unit count when the rule is asked for budgets 1 to 8, and the
columns it verifies at budget 8 (its own stop). Then, after those verifications, it counts
for every still-unverified pool column the P-steps where that column exceeds its believed
threshold one cap level above the decision (B7's blocking definition), and at two or more
levels above. The protocol's s. 7 budget-matching rule scores a policy at its largest
realised count <= k, so a round that overshoots k is not eligible at k.
"""

import sys
from pathlib import Path

import numpy as np

MODULE = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(MODULE))
import ratings_core as rc  # noqa: E402
import run_stage_a as ra  # noqa: E402

name, label = sys.argv[2].split(":")
rc_model, w = ra.EVAL_MODELS[label]
loaded = ra.load_tables(name)
table = loaded.tables["P"]
lb = rc.rho_bounds(rc_model, w, "believed").line_lb
pool = rc.candidate_pool(table, lb)
counts = {b: rc.route_rule(table, lb, loaded.parent_line, b, pool=pool).n_units for b in range(1, 9)}
static = rc.route_rule(table, lb, loaded.parent_line, 8, pool=pool)  # B9-static to its own stop
verified = [int(c) for c in static.verified]
thr = np.full(table.n_table, 100.0 * lb)
thr[verified] = 100.0 * (2.0 - lb)
level = np.asarray(rc.decide(table, thr, 100.0).level).reshape(-1)
print(f"{name} {label}: B9-static verifies columns (budget 8, its own stop) {verified}; picks {static.picks}")
print(f"realised units when asked for budget 1..8: {counts}")
print(f"decision levels on P: share at level 0 (no cap) {np.mean(level == 0):.3f}")
for col in [int(c) for c in pool if int(c) not in verified]:
    one = two = 0
    for gap in range(1, table.n_levels):
        above = level - gap
        steps = np.flatnonzero(above >= 0)
        exceeds = table.load[steps, above[steps], col] > thr[col]
        if gap == 1:
            one = int(exceeds.sum())
        else:
            two = max(two, int(exceeds.sum()))
    if one or two:
        print(f"  column {col}: blocks one level up on {one} steps; exceeds at >= 2 levels up on up to {two} steps")
