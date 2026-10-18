"""Markdown report of a dual-study stage: `python report.py <stage>` from the repo root.

Reads only the stage's JSON outputs; computes nothing new beyond counting and formatting.
"""

import json
import sys
from pathlib import Path

OUT = Path("outputs/dual_study")
stage = sys.argv[1]
S = json.loads((OUT / f"{stage}_summaries.json").read_text())
D = json.loads((OUT / f"{stage}_diagnostics.json").read_text())
M = json.loads((OUT / f"{stage}_materiality.json").read_text())
hyp_path = OUT / f"{stage}_hypotheses.json"
H = json.loads(hyp_path.read_text()) if hyp_path.exists() else None
NETS = list(S)
TRUTHS = list(next(iter(M.values())))
KEY = [
    "no_action",
    "static_dev",
    "static_beta",
    "static_aci",
    "point",
    "point_margin",
    "point_aci",
    "scenario_risk",
    "scenario_robust",
    "scenario_aci",
    "replay_robust",
    "replay_aci",
    "ensemble",
    "oracle",
]


def short(code):
    return code.replace("1-LV-", "").replace("--2-sw", "")


def num(value, digits=2):
    return value if isinstance(value, str) else f"{value:.{digits}f}"


def ve(total):
    star = "*" if total["meets_beta"] else ""
    return f"{total['avoidable_violation_steps']:.0f} / {total['curtailed_mwh']:.1f}{star}"


def table(cell):
    print(f"\n#### {cell}: avoidable violation steps / curtailed MWh (* meets beta)\n")
    print("| policy | " + " | ".join(short(c) for c in NETS) + " |")
    print("|---" * (len(NETS) + 1) + "|")
    for policy in KEY:
        row = []
        for code in NETS:
            total = S[code]["cells"][cell]["totals"].get(policy)
            row.append("—" if total is None else ve(total))
        print(f"| {policy} | " + " | ".join(row) + " |")


print(f"# Dual-study report: {stage}\n")
print("## Tuned on development and online state at its end\n")
print("| network | PV scale | static_dev cap | static_beta cap | point_margin tau | "
      "replay_aci tau | scenario_aci tau | point_aci tau | static_aci index |")
print("|---|---|---|---|---|---|---|---|---|")
levels = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0]
for code in NETS:
    t = S[code]["cells"]["forecast/nominal"]["tuned_on_development"]
    o = t.get("online_state_end_of_development", {})
    print(
        f"| {short(code)} | {S[code]['pv_scale']:.2f} | {levels[t['static_dev_level']]} | "
        f"{levels[t['static_beta_level']]} | {t['point_margin_tau']:.2f} | "
        f"{o.get('replay_aci', float('nan')):.3f} | {o.get('scenario_aci', float('nan')):.3f} | "
        f"{o.get('point_aci', float('nan')):.3f} | {o.get('static_aci_level_index', float('nan')):.2f} |"
    )

print("\n## Policy outcomes per cell")
for cell in ("forecast/nominal", "perfect/nominal"):
    table(cell)

print("\n## Requirement met across truths (F1): cells meeting beta out of 10 truths\n")
print("| policy | " + " | ".join(short(c) for c in NETS) + " |")
print("|---" * (len(NETS) + 1) + "|")
for policy in KEY:
    row = []
    for code in NETS:
        cells = S[code]["cells"]
        met = [cells[f"forecast/{t}"]["totals"][policy]["meets_beta"] for t in ["nominal"] + TRUTHS
               if policy in cells[f"forecast/{t}"]["totals"]]
        row.append(f"{sum(met)}/{len(met)}" if met else "—")
    print(f"| {policy} | " + " | ".join(row) + " |")

print("\n## Curtailment (MWh) of key policies per truth (F1), with * when beta is met\n")
for policy in ("static_dev", "static_beta", "static_aci", "replay_aci", "scenario_aci", "ensemble"):
    print(f"\n**{policy}**\n")
    print("| truth | " + " | ".join(short(c) for c in NETS) + " |")
    print("|---" * (len(NETS) + 1) + "|")
    for truth in ["nominal"] + TRUTHS:
        row = [ve(S[c]["cells"][f"forecast/{truth}"]["totals"][policy]) for c in NETS]
        print(f"| {truth} | " + " | ".join(row) + " |")

print("\n## Physical-safety indicators (F1): worst over the 10 truths\n")
print("| policy | network | max worst-day steps | max longest run | max severe steps | "
      "max runs >= 1 h | max peak margin |")
print("|---|---|---|---|---|---|---|")
for policy in ("static_dev", "static_beta", "static_aci", "replay_aci", "scenario_aci", "ensemble"):
    for code in NETS:
        totals = [S[code]["cells"][f"forecast/{t}"]["totals"][policy] for t in ["nominal"] + TRUTHS]
        peak = max(float(x["peak_margin"]) for x in totals)
        print(
            f"| {policy} | {short(code)} | {max(x['worst_day_violation_steps'] for x in totals)} | "
            f"{max(x['longest_violation_run'] for x in totals)} | "
            f"{max(x['severe_steps'] for x in totals):.0f} | {max(x['long_runs'] for x in totals):.0f} | "
            f"{peak:.3f} |"
        )

print("\n## Risk diagnostics (nominal truth): realised / predicted at the Phase 3 rule's caps\n")
print("| network | ensemble | realised (days) | in-sample ratio [95 % CI] | leave-one-out ratio [95 % CI] |")
print("|---|---|---|---|---|")
for code in NETS:
    for ensemble in ("scenario", "replay"):
        d = D[code]["nominal"][ensemble]
        a, b = d["realised_over_in_sample"], d["realised_over_leave_one_out"]
        print(
            f"| {short(code)} | {ensemble} | {d['realised_violations']} ({d['violation_days']}) | "
            f"{num(a['estimate'])} [{num(a['ci_low'])}, {num(a['ci_high'])}] | "
            f"{num(b['estimate'])} [{num(b['ci_low'])}, {num(b['ci_high'])}] |"
        )
print("\n| network | Brier scenario | Brier replay | skill of scenario vs replay [95 % CI] |")
print("|---|---|---|---|")
for code in NETS:
    br = D[code]["nominal"]["no_action_brier"]
    sk = br["skill_scenario_vs_replay"]
    ci = "—" if not sk else f"{num(sk['estimate'], 3)} [{num(sk['ci_low'], 3)}, {num(sk['ci_high'], 3)}]"
    print(f"| {short(code)} | {br['scenario']:.4f} | {br['replay']:.4f} | {ci} |")

print("\n## Registered paired comparisons (F1, nominal truth): per-day mean difference [95 % CI]\n")
print("| network | pair | avoidable violation steps | curtailed MWh | informative days |")
print("|---|---|---|---|---|")
for code in NETS:
    for name, pair in S[code]["cells"]["forecast/nominal"]["paired_per_day"].items():
        v, e = pair["avoidable_violation_steps"], pair["curtailed_mwh"]
        print(
            f"| {short(code)} | {name.replace('_minus_', ' − ')} | {v['estimate']:+.3f} [{v['ci_low']:+.3f}, "
            f"{v['ci_high']:+.3f}] | {e['estimate']:+.3f} [{e['ci_low']:+.3f}, {e['ci_high']:+.3f}] | "
            f"{pair['informative_days']} |"
        )

print("\n## Materiality of the variants (development no-action daylight violations)\n")
print("| variant | " + " | ".join(short(c) for c in NETS) + " |")
print("|---" * (len(NETS) + 1) + "|")
print("| nominal | " + " | ".join(str(next(iter(M[c].values()))["nominal_development_no_action_violations"]) for c in NETS) + " |")
for truth in TRUTHS:
    print(f"| {truth} | " + " | ".join(
        f"{M[c][truth]['development_no_action_violations']}{'' if M[c][truth]['material'] else ' (n.m.)'}"
        for c in NETS) + " |")

excluded = [(c, k) for c in NETS for k, v in S[c]["cells"].items() if v["excluded"]]
unavoidable = {(c, k): v["unavoidable_daylight_steps"] for c in NETS for k, v in S[c]["cells"].items()
               if v["unavoidable_daylight_steps"]}
print(f"\nExcluded cells: {excluded or 'none'}; cells with unavoidable daylight steps: {unavoidable or 'none'}")

if H:
    print("\n## Hypothesis checks (registered criteria)\n")
    print(f"- **H1** verdict: {H['H1']['verdict']} ({H['H1']['informative_networks']} informative networks)")
    for code, v in H["H1"]["per_network"].items():
        print(f"  - {short(code)}: {v}")
    print(f"- **H2** forecast adds value in {H['H2']['networks_with_value']} networks "
          f"(prediction {H['H2']['prediction']}): {H['H2']['forecast_adds_value']}")
    h3 = H["H3"]
    print(f"- **H3** verdict: {h3['verdict']}; simple better than both aware (networks): "
          f"{h3['simple_better_than_both_aware_networks']}")
    for aware, v in h3["aware"].items():
        print(f"  - {aware}: nominal networks {v['nominal_networks']}, mismatch networks "
              f"{v['mismatch_networks']}, genuine value {v['genuine_value']}, by profile group "
              f"{v['by_profile_group']}")
        for code, w in v["per_network"].items():
            print(f"    - {short(code)}: nominal {w['nominal_better_than_all_simple']}, wins "
                  f"{w['wins']} of material {w['material_mismatch_cells']}")
    print(f"- **H4**: {json.dumps(H['H4'])}")
    print(f"- **D1** point interaction (avoidable steps): {json.dumps(H['D1_point_interaction'])}")
