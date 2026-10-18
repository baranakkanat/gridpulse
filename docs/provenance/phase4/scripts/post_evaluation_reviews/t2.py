"""Task 2: independent H2/H3 re-derivation from the daily CSV with own bootstrap calls."""
import json
import math

import numpy as np
import pandas as pd

from gridpulse.uncertainty import block_bootstrap_mean

df = pd.read_csv("outputs/dual_study/evaluation_daily_outcomes.csv").sort_values(["network", "information", "truth", "day"])
dev = pd.read_csv("outputs/dual_study/development_daily_outcomes.csv")
summ = json.load(open("outputs/dual_study/evaluation_summaries.json"))
hyp = json.load(open("outputs/dual_study/evaluation_hypotheses.json"))
mat_json = json.load(open("outputs/dual_study/evaluation_materiality.json"))
R1 = "1-LV-rural1--2-sw"
NEW = sorted(n for n in df.network.unique() if n != R1)
short = lambda n: n.split("-")[2]
VARIANTS = ["tap_raise_lv", "tap_lower_lv", "pv_cosphi_p", "pv_fixed_095", "storage_greedy", "storage_profile",
            "mv_high", "joint_realistic", "joint_loading"]
AWARE = ("replay_aci", "scenario_aci")
SIMPLE = ("static_dev", "static_beta", "static_aci", "point_margin")
BETA = 0.1

# --- materiality recomputed from the development CSV (no_action daylight violations, dev days)
print("dev days per cell:", dev.groupby(["network", "information", "truth"]).size().unique(), dev.day.min(), dev.day.max())
d0 = dev[dev.information == "forecast"]
material = {}
for c in NEW:
    g = d0[d0.network == c]
    nom = g[g.truth == "nominal"].no_action__daylight_violation_steps.sum()
    material[c] = []
    for t in VARIANTS:
        cnt = g[g.truth == t].no_action__daylight_violation_steps.sum()
        ismat = abs(cnt - nom) >= 0.1 * max(nom, 1)
        assert cnt == mat_json[c][t]["development_no_action_violations"], (c, t, cnt)
        assert ismat == mat_json[c][t]["material"]
        if ismat:
            material[c].append(t)
    print(short(c), "nominal dev", nom, "material:", material[c])

def cell(c, info, t):
    return df[(df.network == c) & (df.information == info) & (df.truth == t)]

CACHE = {}
def ci(g, a, b, m, **kw):
    key = (g.network.iloc[0], g.information.iloc[0], g.truth.iloc[0], a, b, m, tuple(sorted(kw.items())))
    if key not in CACHE:
        diff = (g[f"{a}__{m}"].to_numpy(float) - g[f"{b}__{m}"].to_numpy(float))
        CACHE[key] = block_bootstrap_mean(diff, **kw)
    return CACHE[key]

def meets(g, p, beta=BETA):
    return g[f"{p}__avoidable_violation_steps"].sum() / len(g) <= beta

def better(g, a, b, **kw):
    ma, mb = meets(g, a), meets(g, b)
    if ma and not mb:
        return ci(g, a, b, "avoidable_violation_steps", **kw)["ci_high"] < 0
    if ma and mb:
        return ci(g, a, b, "curtailed_mwh", **kw)["ci_high"] < 0
    return False

def h3(**kw):
    out = {}
    for a in AWARE:
        per = {}
        for c in NEW:
            gn = cell(c, "forecast", "nominal")
            nom = all(better(gn, a, b, **kw) for b in SIMPLE)
            wins = [t for t in material[c] if all(better(cell(c, "forecast", t), a, b, **kw) for b in SIMPLE)]
            per[c] = (nom, wins, len(wins) >= math.ceil(len(material[c]) / 2))
        out[a] = per
    simple_wins = {b: sum(all(better(cell(c, "forecast", "nominal"), b, a, **kw) for a in AWARE) for c in NEW) for b in SIMPLE}
    return out, simple_wins

# --- check bootstrap equality with summaries for one pair, then registered H3
g = cell(NEW[0], "forecast", "nominal")
mine = ci(g, "replay_aci", "static_dev", "curtailed_mwh")
theirs = summ[NEW[0]]["cells"]["forecast/nominal"]["paired_per_day"]["replay_aci_minus_static_dev"]["curtailed_mwh"]
print("bootstrap check:", {k: mine[k] for k in ("estimate", "ci_low", "ci_high")}, {k: theirs[k] for k in ("estimate", "ci_low", "ci_high")})

# Full CI equality check across all aware-simple pairs in forecast cells
maxdiff = 0
for c in NEW:
    for t in ["nominal"] + VARIANTS:
        gg = cell(c, "forecast", t)
        for a in AWARE:
            for b in SIMPLE + (("replay_aci",) if a == "scenario_aci" else ()):
                for m in ("avoidable_violation_steps", "curtailed_mwh"):
                    r = ci(gg, a, b, m)
                    s = summ[c]["cells"][f"forecast/{t}"]["paired_per_day"][f"{a}_minus_{b}"][m]
                    maxdiff = max(maxdiff, abs(r["ci_low"] - s["ci_low"]), abs(r["ci_high"] - s["ci_high"]), abs(r["estimate"] - s["estimate"]))
        # meets check vs summaries
        for p in AWARE + SIMPLE:
            assert meets(gg, p) == summ[c]["cells"][f"forecast/{t}"]["totals"][p]["meets_beta"], (c, t, p)
print("max |CI difference| vs summaries over all aware-simple pairs:", maxdiff)

res, sw = h3()
print("\n=== H3 (registered settings) ===")
for a in AWARE:
    nn = sum(v[0] for v in res[a].values()); mn = sum(v[2] for v in res[a].values())
    print(a, "nominal networks", nn, "mismatch networks", mn, "genuine", nn >= 3 and mn >= 3)
    for c, v in res[a].items():
        js = hyp["H3"]["aware"][a]["per_network"][c]
        ok = (v[0] == js["nominal_better_than_all_simple"]) and (v[1] == js["wins"]) and (v[2] == js["mismatch_criterion"])
        print("   ", short(c), "nominal", v[0], "wins", v[1], "crit", v[2], "| matches JSON:", ok)
print("simple better than both aware:", sw, "JSON:", hyp["H3"]["simple_better_than_both_aware_networks"])

# --- nominal comparisons detail
print("\n=== Nominal comparisons (forecast/nominal): meets flags, curtailment & violation CIs ===")
for a in AWARE:
    for c in NEW:
        gn = cell(c, "forecast", "nominal")
        for b in SIMPLE:
            e = ci(gn, a, b, "curtailed_mwh"); v = ci(gn, a, b, "avoidable_violation_steps")
            tot_b = gn[f"{b}__curtailed_mwh"].sum()
            print(f"{a:12s} {short(c):9s} vs {b:12s} meets(a,b)=({meets(gn,a)!s:5},{meets(gn,b)!s:5}) "
                  f"dMWh/day est {e['estimate']:+.4f} CI [{e['ci_low']:+.4f}, {e['ci_high']:+.4f}]  "
                  f"(ci_high as % of est: {100*e['ci_high']/e['estimate'] if e['estimate'] else float('nan'):6.1f}%; total diff {e['estimate']*183:+.2f} MWh = {100*e['estimate']*183/tot_b:+.1f}% of b) "
                  f"dV/day CI [{v['ci_low']:+.4f}, {v['ci_high']:+.4f}]  better={better(gn,a,b)}")

# --- H2
print("\n=== H2 ===")
for c in NEW:
    gn = cell(c, "forecast", "nominal")
    v = ci(gn, "scenario_aci", "replay_aci", "avoidable_violation_steps")
    e = ci(gn, "scenario_aci", "replay_aci", "curtailed_mwh")
    val = (v["ci_high"] < 0 and e["ci_low"] <= 0) or (e["ci_high"] < 0 and v["ci_low"] <= 0)
    print(short(c), f"dV CI [{v['ci_low']:+.4f},{v['ci_high']:+.4f}] dE CI [{e['ci_low']:+.4f},{e['ci_high']:+.4f}] est {e['estimate']:+.4f}  value={val}")
