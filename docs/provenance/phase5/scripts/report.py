"""Markdown tables from Phase 5 outputs: `python report.py <stage>` from the repo root.

Reads only `outputs/sense_study/<stage>_results.json` and `<stage>_hypotheses.json`.
"""

import json
import sys
from pathlib import Path

OUT = Path("outputs/sense_study")
stage = sys.argv[1]
R = json.loads((OUT / f"{stage}_results.json").read_text())
H = json.loads((OUT / f"{stage}_hypotheses.json").read_text())
NETS = list(R)
TRUTHS = ("nominal", "tap_raise_lv", "mv_high", "pv_fixed_095")
MISMATCH = TRUTHS[1:]
PRIMARY = "realistic"


def short(code):
    return code.replace("1-LV-", "").replace("--2-sw", "")


def f(x, d=2):
    if x is None:
        return "—"
    if isinstance(x, str):
        return x
    return f"{x:.{d}f}"


print(f"# Phase 5 report: {stage}\n")
print("## Networks, placements (development data) and export threshold\n")
print("| network | LV buses | feeders | customer buses | export threshold p* (MW) | "
      "topology k=4 | risk k=4 | mandatory k=4 | greedy k=4 | decision-aware k=4 |")
print("|---|---|---|---|---|---|---|---|---|---|")
for c in NETS:
    r, p = R[c], R[c]["placements"]
    fa = r["facts"]
    print(f"| {short(c)} | {fa['lv_buses']} | {fa['feeders']} | {fa['customer_buses']} | "
          f"{f(r['export_threshold_mw'], 4)} | {p['topology']} | {p['risk']} | {p['mandatory']} | "
          f"{p['greedy_detect']} | {p['decision_aware']} |")

CFG = ("transformer", "substation", "substation_proxy", "substation+1:topology",
       "substation+2:topology", "substation+4:topology", "full")
print("\n## Development coverage (recall of direct detection, nominal, realistic) and "
      "INSUFFICIENT_EVIDENCE (< 0.8)\n")
print("| config | " + " | ".join(short(c) for c in NETS) + " |")
print("|---" * (len(NETS) + 1) + "|")
for name in ("none",) + CFG + ("substation+2:decision_aware", "substation+2:risk",
                               "substation+2:mandatory"):
    row = []
    for c in NETS:
        cov = R[c]["coverage_development"].get(name)
        flag = " (I)" if R[c]["insufficient_evidence"].get(name) else ""
        row.append(f"{f(cov)}{flag}")
    print(f"| {name} | " + " | ".join(row) + " |")

print(f"\n## Detection of avoidable violations at no action ({stage}, realistic): recall "
      "any / voltage / line / trafo; false-alarm rate\n")
for truth in TRUTHS:
    print(f"\n**{truth}**\n")
    print("| config | " + " | ".join(short(c) for c in NETS) + " |")
    print("|---" * (len(NETS) + 1) + "|")
    for name in CFG:
        row = []
        for c in NETS:
            d = R[c]["detection"][truth][name]
            row.append(f"{f(d['recall'])} / {f(d['recall_voltage'])} / {f(d['recall_line'])} / "
                       f"{f(d['recall_trafo'])}; FA {f(d['false_alarm_rate'], 3)}")
        print(f"| {name} | " + " | ".join(row) + " |")
    pos = [f"{short(c)}: {R[c]['detection'][truth]['full']['tp'] + R[c]['detection'][truth]['full']['fn']}"
           for c in NETS]
    print(f"\nEvents (avoidable violation steps at no action): {', '.join(pos)}")

print(f"\n## Decisions ({stage}, realistic): avoidable violation quarter-hours / curtailed "
      "MWh (* meets beta)\n")
DEC = [("static_dev", "none"), ("replay_robust", "none"), ("static_aci", "substation"),
       ("replay_aci", "transformer"), ("replay_aci", "substation"),
       ("replay_aci", "substation_proxy"), ("replay_aci", "substation_se"),
       ("replay_aci", "substation+1:topology"), ("replay_aci", "substation+2:topology"),
       ("replay_aci", "substation+4:topology"), ("replay_aci", "substation+2:risk"),
       ("replay_aci", "substation+2:mandatory"), ("replay_aci", "substation+2:decision_aware"),
       ("replay_aci", "full"), ("oracle", "none")]
for truth in TRUTHS:
    print(f"\n**{truth}**\n")
    print("| policy / telemetry | " + " | ".join(short(c) for c in NETS) + " |")
    print("|---" * (len(NETS) + 1) + "|")
    for policy, name in DEC:
        key = f"{policy}/{name}/{PRIMARY}"
        row = []
        for c in NETS:
            d = R[c]["decisions"][truth].get(key)
            row.append("—" if d is None else f"{d['avoidable_violation_steps']:.0f} / "
                       f"{d['curtailed_mwh']:.1f}{'*' if d['meets_beta'] else ''}")
        print(f"| {policy} / {name} | " + " | ".join(row) + " |")

print("\n## Hypotheses\n")
print("```json")
print(json.dumps(H, indent=1)[:12000])
print("```")

print("\n## Value curve: mismatch cells meeting beta (15 = 5 new networks x 3), realistic\n")
rules = ("topology", "risk", "mandatory", "greedy_detect", "decision_aware")
print("| rule | k=0 | k=1 | k=2 | k=4 |")
print("|---|---|---|---|---|")
base = H["P"]["meets_beta_cells"]["substation"]
for rule in rules:
    vals = [H["P"]["meets_beta_cells"].get(f"substation+{k}:{rule}") for k in (1, 2, 4)]
    print(f"| {rule} | {base} | " + " | ".join(str(v) for v in vals) + " |")
random_counts = {k: [] for k in (1, 2, 4)}
for seed in range(20):
    for k in (1, 2, 4):
        key = f"replay_aci/substation+{k}:random_{seed}/{PRIMARY}"
        random_counts[k].append(sum(
            R[c]["decisions"][t][key]["meets_beta"] for c in NETS if "rural1" not in c
            for t in MISMATCH))
for k, vals in random_counts.items():
    vals = sorted(vals)
    print(f"\nrandom k={k}: median {vals[len(vals) // 2]}, range {vals[0]}–{vals[-1]} over 20 seeds")
print(f"\nfull: {H['P']['meets_beta_cells']['full']}, transformer: "
      f"{H['P']['meets_beta_cells']['transformer']}, proxy: {H['P']['meets_beta_cells']['substation_proxy']}")

print("\n## State estimation (sample: every 3rd day, 11:00-14:00 UTC, no action, realistic)\n")
print("| network | truth | config | observable w/o pseudo (rank/states) | success | RMSE median | "
      "max err p95 | err at highest bus | SE recall V | direct recall V | SE FA | direct FA |")
print("|---|---|---|---|---|---|---|---|---|---|---|---|")
for c in NETS:
    for t in TRUTHS:
        for name, s in R[c]["state_estimation"].get(t, {}).items():
            print(f"| {short(c)} | {t} | {name} | {f(s['observable_without_pseudo'])} "
                  f"({s['rank_without_pseudo']}/{s['states']}) | {f(s['success_rate'])} | "
                  f"{f(s['rmse_vm_median'], 4)} | {f(s['max_abs_error_vm_p95'], 4)} | "
                  f"{f(s['error_at_highest_bus_median'], 4)} | {f(s['se_voltage']['recall'])} | "
                  f"{f(s['direct_voltage']['recall'])} | {f(s['se_any']['false_alarm_rate'], 3)} | "
                  f"{f(s['direct_any']['false_alarm_rate'], 3)} |")

print("\n## Paired per-day differences (replay_aci, realistic): mean [95 % CI]\n")
print("| network | truth | comparison | avoidable violations/day | curtailed MWh/day |")
print("|---|---|---|---|---|")
for c in NETS:
    for t in TRUTHS:
        for name, pair in R[c]["paired"][t].items():
            v, e = pair["avoidable_violation_steps"], pair["curtailed_mwh"]
            print(f"| {short(c)} | {t} | {name} | {v['estimate']:+.3f} [{v['ci_low']:+.3f}, "
                  f"{v['ci_high']:+.3f}] | {e['estimate']:+.3f} [{e['ci_low']:+.3f}, {e['ci_high']:+.3f}] |")
