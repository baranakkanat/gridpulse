"""Markdown tables from Phase 6 outputs: `python report.py <stage>` from the repo root.

Reads only `outputs/noise_study/<stage>_results.json` and `<stage>_hypotheses.json`.
"""

import json
import sys
from pathlib import Path

OUT = Path("outputs/noise_study")
stage = sys.argv[1]
D = json.loads((OUT / f"{stage}_results.json").read_text())
R, PLACEMENTS = D["results"], D["placements"]
H = json.loads((OUT / f"{stage}_hypotheses.json").read_text())
NETS = [c for c in R if "rural1" not in c]
TRUTHS = ("nominal", "tap_raise_lv", "mv_high", "pv_fixed_095")
MIS = TRUTHS[1:]
P, REAL = "persist3_meters", "realistic"  # primary rule (amendment 6A)


def short(code):
    return code.replace("1-LV-", "").replace("--2-sw", "")


def key(config, condition=REAL, rule=P, rep=0):
    return f"{config}/{condition}/{rule}/{rep}"


def run(code, truth, k):
    return R[code][truth]["runs"][k]


def cells(k, nets=NETS):
    return sum(run(c, t, k)["meets_beta"] for c in nets for t in MIS)


def tot(k, metric, truths=("nominal",), nets=NETS):
    return sum(run(c, t, k)[metric] for c in nets for t in truths)


print(f"# Phase 6 report: {stage}\n")
print("## Hypotheses\n\n```json")
print(json.dumps(H, indent=1))
print("```\n")

print("## Placements (development data)\n")
for c in R:
    p = PLACEMENTS[c]
    print(f"- {short(c)}: " + "; ".join(f"{r} {p[r][:4]}" for r in
                                         ("topology", "risk", "mandatory", "greedy_detect",
                                          "decision_aware")))  # fmt: skip

LINES = [
    ("static_dev (open loop)", "static_dev"),
    ("substation, realistic, unfiltered", key("substation", rule="unfiltered")),
    ("substation, realistic, persist3_meters", key("substation")),
    ("+2 topology, exact, unfiltered", key("substation+2:topology", "exact", "unfiltered")),
    ("+2 topology, realistic, unfiltered", key("substation+2:topology", rule="unfiltered")),
    ("+2 topology, realistic, guard2", key("substation+2:topology", rule="guard2")),
    ("+2 topology, realistic, persist2", key("substation+2:topology", rule="persist2")),
    ("+2 topology, realistic, persist3 (all readings)", key("substation+2:topology", rule="persist3")),
    ("+2 topology, exact, persist3_meters", key("substation+2:topology", "exact")),
    ("+2 topology, realistic, persist3_meters (primary)", key("substation+2:topology")),
    ("+2 decision-aware, realistic, persist3_meters", key("substation+2:decision_aware")),
    ("full, exact, unfiltered (full-information ref.)", key("full", "exact", "unfiltered")),
    ("full, realistic, unfiltered", key("full", rule="unfiltered")),
    ("full, realistic, persist3 (all readings)", key("full", rule="persist3")),
    ("full, realistic, persist3_meters", key("full")),
    ("oracle (unattainable)", "oracle"),
]
print("\n## Summary over the five new networks\n")
print("| policy / telemetry | mismatch cells met (of 15) | mismatch avoidable viol. | "
      "mismatch MWh | nominal viol. | nominal MWh | nominal unneeded MWh | nominal false "
      "alarms | mismatch missed steps | nominal interventions |")  # fmt: skip
print("|---" * 10 + "|")
for label, k in LINES:
    print(f"| {label} | {cells(k)} | {tot(k, 'avoidable_violation_steps', MIS):.0f} | "
          f"{tot(k, 'curtailed_mwh', MIS):.1f} | {tot(k, 'avoidable_violation_steps'):.0f} | "
          f"{tot(k, 'curtailed_mwh'):.1f} | {tot(k, 'unneeded_curtailment_mwh'):.1f} | "
          f"{tot(k, 'false_alarm_steps'):.0f} | {tot(k, 'missed_steps', MIS):.0f} | "
          f"{tot(k, 'intervention_steps'):.0f} |")  # fmt: skip

print("\n## Per network and truth: avoidable violations / curtailed MWh (* meets beta)\n")
for truth in TRUTHS:
    print(f"\n**{truth}**\n")
    print("| policy / telemetry | " + " | ".join(short(c) for c in R) + " |")
    print("|---" * (len(R) + 1) + "|")
    for label, k in LINES:
        row = []
        for c in R:
            r = run(c, truth, k)
            row.append(f"{r['avoidable_violation_steps']:.0f} / {r['curtailed_mwh']:.1f}"
                       f"{'*' if r['meets_beta'] else ''}")  # fmt: skip
        print(f"| {label} | " + " | ".join(row) + " |")

print("\n## Conditions x rules: mismatch cells met / nominal MWh / nominal false alarms\n")
CONDS = ("exact", "noisy", "noisy_missing", "noisy_delayed", "realistic", "sigma_0.005",
         "sigma_0.02", "biased_meters", "biased_meters_matched")  # fmt: skip
for config in ("substation", "substation+2:topology", "substation+2:decision_aware", "full"):
    print(f"\n**{config}**\n")
    print("| rule | " + " | ".join(CONDS) + " |")
    print("|---" * (len(CONDS) + 1) + "|")
    for rule in ("unfiltered", "guard2", "persist2", "persist3", "persist3_meters"):
        row = [f"{cells(key(config, c, rule))} / {tot(key(config, c, rule), 'curtailed_mwh'):.0f}"
               f" / {tot(key(config, c, rule), 'false_alarm_steps'):.0f}" for c in CONDS]  # fmt: skip
        print(f"| {rule} | " + " | ".join(row) + " |")

print("\n## Value of sensors (realistic): cells met / mismatch viol. / nominal MWh\n")
print("| rule | alarm | k=0 | k=1 | k=2 | k=4 |")
print("|---|---|---|---|---|---|")
for placement in ("topology", "risk", "mandatory", "greedy_detect", "decision_aware"):
    for rule in ("unfiltered", P):
        vals = [key("substation", rule=rule)] + [
            key(f"substation+{k}:{placement}", rule=rule) for k in (1, 2, 4)
        ]
        print(f"| {placement} | {rule} | " + " | ".join(
            f"{cells(v)} / {tot(v, 'avoidable_violation_steps', MIS):.0f} / "
            f"{tot(v, 'curtailed_mwh'):.0f}" for v in vals) + " |")  # fmt: skip
for rule in ("unfiltered", P):
    for k in (1, 2, 4):
        vals = sorted(cells(key(f"substation+{k}:random_{s}", rule=rule)) for s in range(20))
        mwh = sorted(tot(key(f"substation+{k}:random_{s}", rule=rule), "curtailed_mwh")
                     for s in range(20))  # fmt: skip
        print(f"\nrandom k={k}, {rule}: cells median {vals[10]}, range {vals[0]}-{vals[-1]}; "
              f"nominal MWh median {mwh[10]:.0f}, range {mwh[0]:.0f}-{mwh[-1]:.0f}")

print("\n## Noise replications 0-4: cells met; nominal cells met; nominal MWh\n")
for cond in ("realistic", "biased_meters_matched"):
    for config in ("substation", "substation+2:topology", "substation+2:decision_aware", "full"):
        for rule in ("unfiltered", P):
            ks = [key(config, cond, rule, r) for r in range(5)]
            c = [cells(k) for k in ks]
            n = [sum(run(x, "nominal", k)["meets_beta"] for x in NETS) for k in ks]
            m = [round(tot(k, "curtailed_mwh"), 1) for k in ks]
            print(f"- {cond}, {config}, {rule}: cells {c}; nominal cells {n}; MWh {m}")

print("\n## Per-network H2 ratio (mismatch violations, primary / exact unfiltered)\n")
for config in ("substation+2:topology", "full"):
    ratios = {}
    for c in NETS:
        a = sum(run(c, t, key(config))["avoidable_violation_steps"] for t in MIS)
        b = sum(run(c, t, key(config, "exact", "unfiltered"))["avoidable_violation_steps"]
                for t in MIS)  # fmt: skip
        ratios[short(c)] = round(a / b, 2) if b else None
    rest = [c for c in NETS if "semiurb4" not in c]
    a = sum(run(c, t, key(config))["avoidable_violation_steps"] for c in rest for t in MIS)
    b = sum(run(c, t, key(config, "exact", "unfiltered"))["avoidable_violation_steps"]
            for c in rest for t in MIS)  # fmt: skip
    print(f"- {config}: {ratios}; without semiurb4 {a / b:.2f}")

print("\n## Warm-up: tau on the first scored day; first-month violations (realistic)\n")
for config in ("substation", "substation+2:topology", "full"):
    for rule in ("unfiltered", P):
        k = key(config, rule=rule)
        taus = [round(run(c, t, k)["first_tau"], 3) for c in NETS for t in MIS]
        first = tot(k, "first_month_violation_steps", MIS)
        print(f"- {config}, {rule}: first tau {taus}; first-month mismatch violations {first:.0f}")

print("\n## State estimation: monthly chi-square flag rates and gross errors at 0.01 / 10\n")
for truth in ("nominal", "pv_fixed_095"):
    by_month = {}
    for c in NETS:
        for r in R[c][truth]["state_estimation"]:
            if r["config"] == "substation" and r["success"]:
                by_month.setdefault(min(r["day"] // 30.5, 11), []).append(r["chi2_flag"])
    rates = {int(m) + 1: round(sum(v) / len(v), 2) for m, v in sorted(by_month.items())}
    print(f"- {truth}: flag rate by month {rates}")
    rows = [r for c in NETS for r in R[c][truth]["state_estimation"]
            if r["config"] == "substation" and r["success"]]  # fmt: skip
    gross = [r for r in rows if r["max_error_vm"] > 0.01 or r["max_error_loading"] > 10]
    caught = sum(r["chi2_flag"] for r in gross) / len(gross) if gross else None
    print(f"  gross at 0.01 p.u. / 10 points: {len(gross)} of {len(rows)}; chi2 flags {caught}")

print("\n## Paired per-day differences (a - b): mean [95 % CI]\n")
print("| network | truth | comparison | avoidable viol./day | MWh/day |")
print("|---|---|---|---|---|")
for c in R:
    for t in TRUTHS:
        for name, pair in R[c][t]["paired"].items():
            v, e = pair["avoidable_violation_steps"], pair["curtailed_mwh"]
            print(f"| {short(c)} | {t} | {name} | {v['estimate']:+.3f} [{v['ci_low']:+.3f}, "
                  f"{v['ci_high']:+.3f}] | {e['estimate']:+.3f} [{e['ci_low']:+.3f}, "
                  f"{e['ci_high']:+.3f}] |")  # fmt: skip

print("\n## State estimation (sample): chi-square test and gated detection\n")
print("| network | truth | config | success | gross | chi2 detects gross | chi2 flags fine | "
      "SE recall / FA | gated recall / FA | direct recall / FA |")  # fmt: skip
print("|---" * 10 + "|")


def f(x, d=2):
    return "—" if x is None else f"{x:.{d}f}"


for c in R:
    for t in TRUTHS:
        for name, s in R[c][t]["state_estimation_summary"].items():
            print(f"| {short(c)} | {t} | {name} | {f(s['success_rate'], 3)} | {s['gross_errors']} | "
                  f"{f(s['chi2_detects_gross'])} | {f(s['chi2_flags_fine'], 3)} | "
                  f"{f(s['se']['recall'])} / {f(s['se']['false_alarm_rate'], 3)} | "
                  f"{f(s['se_gated']['recall'])} / {f(s['se_gated']['false_alarm_rate'], 3)} | "
                  f"{f(s['direct']['recall'])} / {f(s['direct']['false_alarm_rate'], 3)} |")  # fmt: skip
