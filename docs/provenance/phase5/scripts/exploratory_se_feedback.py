"""EXPLORATORY (amendment 5C): state-estimation feedback on development days only.

The registered gate closed, so state-estimation feedback is not part of the evaluation.
This script runs `replay_aci` with substation readings plus state-estimation inference on
development days, for every network and truth, and compares it with the development-
stage runs of `substation`, `substation+2:topology` and `full`. It is not part of any
hypothesis. Usage, from the repository root:

    python docs/provenance/phase5/scripts/exploratory_se_feedback.py
"""

import json
from pathlib import Path

from gridpulse import dual_study as ds
from gridpulse import estimation, fullstate

OUT = Path("outputs/sense_study")

if __name__ == "__main__":
    runs = estimation.se_feedback_runs(
        list(ds.HOSTING_CAPACITY), fullstate.TRUTHS, "development",
        Path("outputs/dual_study/physics_cache"), OUT / "fullstate_cache", 8,
    )  # fmt: skip
    dev = json.loads((OUT / "development_results.json").read_text())
    table = {}
    for run in runs:
        code, truth = run["network"], run["truth"]
        decisions = dev[code]["decisions"][truth]
        table.setdefault(code, {})[truth] = {
            "substation_se": run["summary"],
            **{
                ref: decisions[f"replay_aci/{ref}/realistic"]
                for ref in ("substation", "substation+2:topology", "full")
            },
        }
    (OUT / "exploratory").mkdir(exist_ok=True)
    (OUT / "exploratory" / "se_feedback_development.json").write_text(json.dumps(table, indent=1))
    for code, by_truth in table.items():
        for truth, row in by_truth.items():
            cells = "  ".join(
                f"{name}={r['avoidable_violation_steps']:.0f}/{r['curtailed_mwh']:.1f}"
                f"{'*' if r['meets_beta'] else ''}"
                for name, r in row.items()
            )
            print(code.replace("1-LV-", "").replace("--2-sw", ""), truth, cells)
