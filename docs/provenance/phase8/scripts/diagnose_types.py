# Phase 8 pre-registration diagnosis, run verbatim on 2026-10-19 (development half only).
# Run: python docs/provenance/phase8/scripts/diagnose_types.py <network>. Its JSON output was
# written to the session scratchpad and copied to outputs/robust_study/exploratory/.
"""Development-only diagnosis (Phase 8 audit): violations of Phase 7 C1 / C1s0 / R0 by
constraint type, and curtailment, per network and truth. Evaluator-side; reads caches."""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import margin_study as ms
from gridpulse import margins as mg
from gridpulse import noise_study as ns
from gridpulse import sensing as sn

P4, FS = Path("outputs/dual_study/physics_cache"), Path("outputs/sense_study/fullstate_cache")
design = json.loads(Path("outputs/noise_study/development_results.json").read_text())["placements"]
code = sys.argv[1]
contexts, layout, _ = sn.build_contexts(code, P4, FS, "development")
raw = ms.plan_raw(code, P4)
out = {}
for truth, ctx in contexts.items():
    configs = ns.configurations(layout, ctx.states[ctx.days[0]]["line"].shape[2], design[code])
    online = ds.OnlineSettings()
    s = mg.tuned_safety_margin(raw, ctx.available, list(ctx.development), online.beta)
    for name, margin, correct in (
        ("C1", s, True),
        ("C1s0", 0.0, True),
        ("Rdev", s, False),
        ("R0", 0.0, False),
    ):
        trace = {}
        corr = mg.ResidualCorrector(
            raw,
            ctx.nominal_states,
            layout,
            configs["substation"],
            ns.CONDITIONS["realistic"],
            mg.CorrectorSettings(safety_margin=margin, correct=correct),
        )
        recs = sn.run_feedback_policy(
            ctx,
            "replay_robust",
            configs["substation"],
            ns.CONDITIONS["realistic"],
            0,
            online,
            noise=sn.NoiseBank(code, truth, 0),
            alarm=ns.RULES["unfiltered"],
            corrector=corr,
            trace=trace,
        )
        types, first30 = Counter(), 0
        for r in recs:
            d = r["day"]
            lv = np.asarray(trace[d], int)
            norm = ctx.truth_norm[d]
            daylight = ctx.available[d].sum(axis=1) > 0
            hit = (norm[np.arange(96), lv] > 0) & (norm <= 0).any(axis=1) & daylight
            m = ctx.states[d]["margins"][np.arange(96), lv] / ds.MARGIN_SCALE
            for t in np.flatnonzero(hit):
                types[("over_v", "under_v", "line", "trafo")[int(np.nanargmax(m[t]))]] += 1
                first30 += d < ctx.days[0] + 30
        out[f"{truth} {name}"] = {
            "viol": sum(r["avoidable_violation_steps"] for r in recs),
            "mwh": round(sum(r["curtailed_mwh"] for r in recs), 1),
            "types": dict(types),
            "first30days": first30,
            "margin": s,
        }
        print(code, truth, name, out[f"{truth} {name}"], flush=True)
Path(
    f"/private/tmp/claude-501/-Users-baranakkanat-Developer-gridpulse/694472ba-46d0-4918-a7a3-5fa8e72fce5c/scratchpad/p8/diag_{code}.json"
).write_text(json.dumps(out, indent=1))
