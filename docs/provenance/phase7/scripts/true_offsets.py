"""Post-evaluation, evaluator-side check (docs/phase7_results.md s. 11): the true-minus-
nominal busbar voltage at no cap (daylight mean, evaluation half) per network and truth,
against C1's mean v_hat. Reads the caches and the frozen outputs only; writes
`outputs/margin_study/exploratory/true_offsets.json`. Run from the repo root:
`python docs/provenance/phase7/scripts/true_offsets.py`."""

import json
from pathlib import Path

import numpy as np

from gridpulse import sensing as sn

P4, FS = Path("outputs/dual_study/physics_cache"), Path("outputs/sense_study/fullstate_cache")
OUT = Path("outputs/margin_study")
R = json.loads((OUT / "evaluation_results.json").read_text())
result = {}
for code in R:
    if "rural1" in code:
        continue
    for truth in ("tap_raise_lv", "mv_high", "pv_fixed_095"):
        contexts, _, _ = sn.build_contexts(code, P4, FS, "evaluation", truths=(truth,))
        ctx = contexts[truth]
        diffs = []
        for d in ctx.days:
            daylight = ctx.available[d].sum(axis=1) > 0
            true, nominal = ctx.states[d]["trafo"][:, 0, 3], ctx.nominal_states[d]["trafo"][:, 0, 3]
            diffs.append((true - nominal)[daylight])
        offset = float(np.nanmean(np.concatenate(diffs)))
        v_hat = R[code][truth]["runs"]["C1/0"]["mean_v_hat"]
        result[f"{code} {truth}"] = {"true_offset_pu": offset, "c1_mean_v_hat": v_hat,
                                     "difference": v_hat - offset}  # fmt: skip
        print(f"{code} {truth}: true {offset:+.4f}, v_hat {v_hat:+.4f}", flush=True)
(OUT / "exploratory").mkdir(exist_ok=True)
(OUT / "exploratory" / "true_offsets.json").write_text(json.dumps(result, indent=1))
