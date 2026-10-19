"""Markdown tables from Phase 8 outputs: `python report.py <stage>` from the repo root.

Reads only `outputs/robust_study/<stage>_results.json` and `<stage>_hypotheses.json`.
"""

import json
import sys
from pathlib import Path

OUT = Path("outputs/robust_study")
stage = sys.argv[1]
R = json.loads((OUT / f"{stage}_results.json").read_text())
H = json.loads((OUT / f"{stage}_hypotheses.json").read_text())
NETS = [c for c in R if "rural1" not in c]
PRIMARY = ("nominal", "tap_raise_lv", "mv_high", "pv_fixed_095")
MIS = PRIMARY[1:]
STRESS = ("tap_lower_lv", "mv_daily", "line_local")
POLICIES = ("static", "B2", "B3", "C1", "C1s0", "C1f", "C5", "C5L", "C6", "oracle")


def short(code):
    return code.replace("1-LV-", "").replace("--2-sw", "")


def key(p, i="I0", s="S0", r=0):
    return f"{p}|{i}|{s}|{r}"


def tot(k, metric, truths, nets=NETS):
    return sum(R[c][t]["runs"][k][metric] for c in nets for t in truths)


def cells(k, truths):
    return sum(R[c][t]["runs"][k]["meets_beta"] for c in NETS for t in truths)


def types(k, truths):
    out = {}
    for c in NETS:
        for t in truths:
            for name, n in R[c][t]["runs"][k]["violations_by_type"].items():
                out[name] = out.get(name, 0) + n
    return out


print(f"# Phase 8 report: {stage}\n\n## Hypotheses and checks\n\n```json")
print(json.dumps(H, indent=1)[:20000])
print("```\n\n## Tuned settings per network (I0)\n")
print("| network | C1 s | C1f s | C5 r_V (p.u.) | C5 r_L (%) |\n|---|---|---|---|---|")
for c in R:
    t = R[c]["nominal"]["tuning"]["I0"]
    print(f"| {short(c)} | {t['C1']} | {t['C1f']} | {t['C5_r_v']} | {t['C5_r_l']} |")

print("\n## Primary comparison (I0, S0, replication 0; five networks)\n")
print("| policy | mismatch cells | mismatch viol. (V/L) | severity | long runs | largest exc. | "
      "mismatch MWh | nominal cells | nominal viol. | nominal MWh | nominal unneeded MWh | "
      "interventions (nominal) |")  # fmt: skip
print("|---" * 12 + "|")
for p in POLICIES:
    k = key(p)
    ty = types(k, MIS)
    largest = max(R[c][t]["runs"][k]["largest_exceedance"] for c in NETS for t in MIS)
    print(f"| {p} | {cells(k, MIS)} | {tot(k, 'avoidable_violation_steps', MIS):.0f} "
          f"({ty['over_v'] + ty['under_v']}/{ty['line'] + ty['trafo']}) | "
          f"{tot(k, 'severity', MIS):.2f} | {tot(k, 'long_runs', MIS):.0f} | {largest:.3f} | "
          f"{tot(k, 'curtailed_mwh', MIS):.1f} | {cells(k, ('nominal',))} | "
          f"{tot(k, 'avoidable_violation_steps', ('nominal',)):.0f} | "
          f"{tot(k, 'curtailed_mwh', ('nominal',)):.1f} | "
          f"{tot(k, 'unneeded_curtailment_mwh', ('nominal',)):.1f} | "
          f"{tot(k, 'intervention_steps', ('nominal',)):.0f} |")  # fmt: skip

print("\n## Per network and truth: violations / MWh (* meets beta)\n")
SHOW = ("B2", "B3", "C1", "C1s0", "C1f", "C5", "C6", "oracle")
for truth in (*PRIMARY, *STRESS):
    print(f"\n**{truth}**\n")
    print("| network | " + " | ".join(SHOW) + " | no-action violations |")
    print("|---" * (len(SHOW) + 2) + "|")
    for c in R:
        row = []
        for p in SHOW:
            r = R[c][truth]["runs"][key(p)]
            row.append(f"{r['avoidable_violation_steps']:.0f} / {r['curtailed_mwh']:.1f}"
                       f"{'*' if r['meets_beta'] else ''}")  # fmt: skip
        noact = sum(R[c][truth]["observability"].values())
        print(f"| {short(c)} | " + " | ".join(row) + f" | {noact} |")

print("\n## Injection-data conditions (S0): mismatch cells / viol. / MWh; nominal viol. / MWh\n")
print("| condition | policy | mismatch cells | mismatch viol. | mismatch MWh | nominal viol. | "
      "nominal MWh |\n|---|---|---|---|---|---|---|")  # fmt: skip
for i in ("I0", "I1_meter_noise", "I2_load_q", "I3_pv_over", "I4_missing", "I5_delay"):
    for p in ("B2", "B3", "C1", "C5", "C6"):
        k = key(p, i)
        print(f"| {i} | {p} | {cells(k, MIS)} | {tot(k, 'avoidable_violation_steps', MIS):.0f} | "
              f"{tot(k, 'curtailed_mwh', MIS):.1f} | "
              f"{tot(k, 'avoidable_violation_steps', ('nominal',)):.0f} | "
              f"{tot(k, 'curtailed_mwh', ('nominal',)):.1f} |")  # fmt: skip

print("\n## Substation conditions (I0)\n")
print("| condition | policy | mismatch cells | mismatch viol. | mismatch MWh | nominal viol. | "
      "nominal MWh |\n|---|---|---|---|---|---|---|")  # fmt: skip
SUB = ("S0", "S1-0.005", "S1-0.002", "S1+0.002", "S1+0.005", "S2_noisy", "S3_delay", "S4_missing")
for s in SUB:
    for p in ("B2", "C1", "C5", "C6"):
        k = key(p, "I0", s)
        if k not in R[NETS[0]]["nominal"]["runs"]:
            continue
        print(f"| {s} | {p} | {cells(k, MIS)} | {tot(k, 'avoidable_violation_steps', MIS):.0f} | "
              f"{tot(k, 'curtailed_mwh', MIS):.1f} | "
              f"{tot(k, 'avoidable_violation_steps', ('nominal',)):.0f} | "
              f"{tot(k, 'curtailed_mwh', ('nominal',)):.1f} |")  # fmt: skip

print("\n## Noise replications (I0, S0): nominal MWh and mismatch violations per replication\n")
for p in ("B2", "C1", "C5", "C6"):
    mwh = [round(tot(key(p, r=r), "curtailed_mwh", ("nominal",)), 1) for r in range(5)]
    viol = [round(tot(key(p, r=r), "avoidable_violation_steps", MIS)) for r in range(5)]
    mmwh = [round(tot(key(p, r=r), "curtailed_mwh", MIS), 1) for r in range(5)]
    print(f"- {p}: nominal MWh {mwh}; mismatch violations {viol}; mismatch MWh {mmwh}")

print("\n## Paired per-day differences (a - b), mean [95 % CI] for 7 / 14 / 28-day blocks\n")
print("| network | truth | pair | violations/day | MWh/day |\n|---|---|---|---|---|")
for c in NETS:
    for t in PRIMARY:
        for name, p in R[c][t]["paired"].items():
            cells_ = []
            for metric in ("avoidable_violation_steps", "curtailed_mwh"):
                parts = [f"{p[f'{metric}_block{b}']['estimate']:+.3f} "
                         f"[{p[f'{metric}_block{b}']['ci_low']:+.3f}, "
                         f"{p[f'{metric}_block{b}']['ci_high']:+.3f}]" for b in (7, 14, 28)]  # fmt: skip
                cells_.append(" / ".join(parts))
            print(f"| {short(c)} | {t} | {name} | {cells_[0]} | {cells_[1]} |")

print("\n## Reserves in force (C6, I0, S0): mean r_V p.u. / mean r_L %\n")
for c in NETS:
    row = []
    for t in (*PRIMARY, *STRESS):
        r = R[c][t]["runs"][key("C6")]
        row.append(f"{t}: {r['mean_r_v']:.4f} / {r['mean_r_l']:.2f}")
    print(f"- {short(c)}: " + "; ".join(row))
