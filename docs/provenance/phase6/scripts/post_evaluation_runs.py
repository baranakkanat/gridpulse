"""POST-EVALUATION diagnostic (not a registered analysis): how long are the true violation
runs left by closed-loop feedback? If most last under 45 min, a 3-quarter-hour persistence
rule cannot see them with exact readings. The script re-runs the frozen policy code for
+ 2 topology sensors with exact readings (evaluation half, mismatch truths) and reads each
scored day's longest violation run (`dual_study.score`). Usage, from the repository root:

    python docs/provenance/phase6/scripts/post_evaluation_runs.py
"""

import json
from collections import Counter
from pathlib import Path

from gridpulse import dual_study as ds
from gridpulse import noise_study as ns
from gridpulse import sensing as sn

P4 = Path("outputs/dual_study/physics_cache")
FS = Path("outputs/sense_study/fullstate_cache")

if __name__ == "__main__":
    placements = json.loads(Path("outputs/noise_study/development_results.json").read_text())[
        "placements"
    ]
    out = {}
    for code in placements:
        if code == ds.DEVELOPMENT_NETWORK:
            continue
        for truth in ns.MISMATCH:
            contexts, layout, _ = sn.build_contexts(code, P4, FS, "evaluation", truths=(truth,))
            ctx = contexts[truth]
            configs = ns.configurations(layout, ctx.states[ctx.days[0]]["line"].shape[2],
                                        placements[code])  # fmt: skip
            for rule in ("unfiltered", ns.PRIMARY_RULE):
                records = sn.run_feedback_policy(
                    ctx, "replay_aci", configs["substation+2:topology"], ns.CONDITIONS["exact"], 0,
                    ds.OnlineSettings(), noise=sn.NoiseBank(code, truth, 0), alarm=ns.RULES[rule],
                )  # fmt: skip
                lengths = Counter(r["longest_violation_run"] for r in records
                                  if r["daylight_violation_steps"])  # fmt: skip
                out[f"{code}/{truth}/{rule}"] = dict(sorted(lengths.items()))
    for rule in ("unfiltered", ns.PRIMARY_RULE):
        total = Counter()
        for key, counts in out.items():
            if key.endswith(rule):
                total.update(counts)
        days = sum(total.values())
        short = sum(n for length, n in total.items() if length < 3)
        print(f"exact readings, {rule}: {days} days with violations; longest run < 3 "
              f"quarter-hours on {short} ({short / days:.0%}); distribution {dict(sorted(total.items()))}")  # fmt: skip
