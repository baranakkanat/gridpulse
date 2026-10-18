"""Markdown tables from Phase 7 outputs: `python report.py <stage>` from the repo root.

Reads only `outputs/margin_study/<stage>_results.json` and `<stage>_hypotheses.json`.
"""

import json
import sys
from pathlib import Path

OUT = Path("outputs/margin_study")
stage = sys.argv[1]
R = json.loads((OUT / f"{stage}_results.json").read_text())
H = json.loads((OUT / f"{stage}_hypotheses.json").read_text())
NETS = [c for c in R if "rural1" not in c]
TRUTHS = ("nominal", "tap_raise_lv", "mv_high", "pv_fixed_095")
MIS = TRUTHS[1:]
NAMES = {
    "static_dev": "static, development-tuned (open loop)",
    "B2/0": "B2 binary, substation, realistic",
    "B2x/0": "B2x binary, substation, exact",
    "B3/0": "B3 binary, + 2 meters, exact",
    "B4/0": "B4 binary, + 2 meters, realistic",
    "B5/0": "B5 binary + persistence, + 2 meters, realistic",
    "B6/0": "B6 binary + guard band, + 2 meters, realistic",
    "B7/0": "B7 binary, full metering, exact",
    "R0/0": "R0 replay, no feedback, margin 0",
    "Rdev/0": "Rdev replay, no feedback, tuned margin",
    "C1/0": "C1 corrected, substation, realistic",
    "C1x/0": "C1x corrected, substation, exact",
    "C3/0": "C3 corrected + 2 meters checked, realistic",
    "C3x/0": "C3x corrected + 2 meters checked, exact",
    "C3_1/0": "C3 with 1 meter",
    "C3_4/0": "C3 with 4 meters",
    "C3full/0": "C3 with every bus metered",
    "C4/0": "C4 hybrid: correction + persistence count feedback",
    "oracle": "oracle (unattainable)",
}


def short(code):
    return code.replace("1-LV-", "").replace("--2-sw", "")


def run(c, t, k):
    return R[c][t]["runs"][k]


def tot(k, metric, truths=("nominal",)):
    return sum(run(c, t, k)[metric] for c in NETS for t in truths)


def cells(k, truths=MIS):
    return sum(run(c, t, k)["meets_beta"] for c in NETS for t in truths)


print(f"# Phase 7 report: {stage}\n\n## Hypotheses\n\n```json")
print(json.dumps(H, indent=1))
print("```\n\n## Tuned safety margins (normalised; 0.01 = 0.001 p.u. or 1 % loading)\n")
print(", ".join(f"{short(c)} {R[c]['nominal']['safety_margin']}" for c in R))

print("\n## Totals over the five new networks\n")
print("| policy | mismatch cells | mismatch viol. | mismatch MWh | mismatch severity | "
      "mismatch long runs | nominal cells | nominal viol. | nominal MWh | nominal unneeded "
      "MWh | nominal interventions |")  # fmt: skip
print("|---" * 11 + "|")
for k, label in NAMES.items():
    print(f"| {label} | {cells(k)} | {tot(k, 'avoidable_violation_steps', MIS):.0f} | "
          f"{tot(k, 'curtailed_mwh', MIS):.1f} | {tot(k, 'severity', MIS):.1f} | "
          f"{tot(k, 'long_runs', MIS):.0f} | {cells(k, ('nominal',))} | "
          f"{tot(k, 'avoidable_violation_steps'):.0f} | {tot(k, 'curtailed_mwh'):.1f} | "
          f"{tot(k, 'unneeded_curtailment_mwh'):.1f} | {tot(k, 'intervention_steps'):.0f} |")  # fmt: skip

print("\n## Per network and truth: avoidable violations / curtailed MWh (* meets beta)\n")
KEYS = ("B2/0", "B3/0", "B5/0", "B7/0", "Rdev/0", "C1/0", "C3/0", "oracle")
for truth in TRUTHS:
    print(f"\n**{truth}**\n")
    print("| network | " + " | ".join(k.split("/")[0] for k in KEYS) + " | C1 v_hat / rho_line / rho_trafo |")
    print("|---" * (len(KEYS) + 2) + "|")
    for c in R:
        cellsx = [f"{run(c, truth, k)['avoidable_violation_steps']:.0f} / "
                  f"{run(c, truth, k)['curtailed_mwh']:.1f}{'*' if run(c, truth, k)['meets_beta'] else ''}"
                  for k in KEYS]  # fmt: skip
        c1 = run(c, truth, "C1/0")
        print(f"| {short(c)} | " + " | ".join(cellsx) + f" | {c1['mean_v_hat']:+.4f} / "
              f"{c1['mean_rho_line']:+.3f} / {c1['mean_rho_trafo']:+.3f} |")  # fmt: skip

print("\n## Bias (matched per-meter bias, 5 draws): nominal MWh; mismatch violations\n")
for name in ("C3b", "C3nb"):
    mwh = [round(tot(f"{name}/{r}", "curtailed_mwh"), 1) for r in range(5)]
    viol = [round(tot(f"{name}/{r}", "avoidable_violation_steps", MIS)) for r in range(5)]
    print(f"- {name}: nominal MWh {mwh}; mismatch violations {viol}")

print("\n## Evidence labels (C1 and C3b, days per truth, summed over new networks)\n")
for k in ("C1/0", "C3/0", "C3b/0"):
    for t in TRUTHS:
        counts = {}
        for c in NETS:
            for label, n in run(c, t, k)["labels"].items():
                counts[label] = counts.get(label, 0) + n
        print(f"- {k} {t}: {counts}")

print("\n## Observability of violations at no action (scored days)\n")
for t in TRUTHS:
    agg = {}
    for c in NETS:
        for cls, n in R[c][t]["observability"].items():
            agg[cls] = agg.get(cls, 0) + n
    print(f"- {t}: {agg}")

print("\n## Coverage of +/- 2u intervals (+ 2 meters, 5 noise draws)\n")
for c in NETS:
    cov = R[c]["nominal"]["coverage"]
    print(f"- {short(c)}: " + "; ".join(f"{k}: single {v['single_reading']:.3f}, daily mean "
                                        f"{v['daily_mean']:.3f}" for k, v in cov.items()))  # fmt: skip

print("\n## Paired per-day differences (a - b): mean [95 % CI], 7-day blocks (28-day)\n")
print("| network | truth | comparison | violations/day | MWh/day |")
print("|---|---|---|---|---|")
for c in NETS:
    for t in TRUTHS:
        for name, p in R[c][t]["paired"].items():
            v, e = p["avoidable_violation_steps"], p["curtailed_mwh"]
            v28, e28 = p["avoidable_violation_steps_block28"], p["curtailed_mwh_block28"]
            print(f"| {short(c)} | {t} | {name} | {v['estimate']:+.3f} [{v['ci_low']:+.3f}, "
                  f"{v['ci_high']:+.3f}] ([{v28['ci_low']:+.3f}, {v28['ci_high']:+.3f}]) | "
                  f"{e['estimate']:+.3f} [{e['ci_low']:+.3f}, {e['ci_high']:+.3f}] "
                  f"([{e28['ci_low']:+.3f}, {e28['ci_high']:+.3f}]) |")  # fmt: skip
