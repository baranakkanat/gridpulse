"""Post-evaluation checks (read-only), quoted in `docs/phase5_results.md` s. 11.

1. Physics consistency: the Phase 5 full-state margins equal the Phase 4 physics cache
   (realised injection set) bit for bit in float32, with the same failure pattern, for
   every network, truth and decision day.
2. Unavoidable violations: daylight steps where no cap level is safe on the true grid
   (such steps would count as negatives in the detection study).

Usage, from the repository root:

    python docs/provenance/phase5/scripts/post_evaluation_checks.py
"""

from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import fullstate, grid_study
from gridpulse.grid import absolute_profiles

P4 = Path("outputs/dual_study/physics_cache")
FS = Path("outputs/sense_study/fullstate_cache")

if __name__ == "__main__":
    decision = list(range(ds.FIRST_DECISION_DAY, ds.LAST_DAY + 1))
    periods = {p: set(grid_study.period_days(p)) for p in ("development", "evaluation")}
    tasks = ds.physics_tasks()
    compared = identical = 0
    for code in ds.HOSTING_CAPACITY:
        net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
        available = grid_study.daily_arrays(absolute_profiles(net))["sgen_p_mw"]
        for truth in fullstate.TRUTHS:
            variant = ds.NOMINAL if truth == "nominal" else ds.VARIANTS[truth]
            days = [d for d, _ in tasks[truth]]
            raw = ds.load_margins(P4, code, truth, days, ds.pv_scale(code), variant)
            states = fullstate.load_states(FS, code, truth, decision)
            same = 0
            unavoidable = dict.fromkeys(periods, 0)
            for d in decision:
                a = np.asarray(raw[d][ds.REALISED]).astype(np.float32)
                b = np.asarray(states[d]["margins"])
                nan_a, nan_b = np.isnan(a), np.isnan(b)
                same += bool(np.array_equal(nan_a, nan_b) and np.array_equal(a[~nan_a], b[~nan_b]))
                norm = ds.normalised(np.asarray(raw[d][ds.REALISED]))
                daylight = available[d].sum(axis=1) > 0
                for period, members in periods.items():
                    if d in members:
                        unavoidable[period] += int(((norm > 0).all(axis=1) & daylight).sum())
            compared += len(decision)
            identical += same
            print(
                f"{code} {truth}: {same}/{len(decision)} days identical; unavoidable daylight "
                f"violation steps: development {unavoidable['development']}, "
                f"evaluation {unavoidable['evaluation']}"
            )
    print(f"identical day arrays: {identical} of {compared}")
