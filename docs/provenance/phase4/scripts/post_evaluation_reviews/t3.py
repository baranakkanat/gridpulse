"""Task 3/4: robustness of H3 to bootstrap seed and block length; duplicate cells; mismatch decomposition."""
import math

import numpy as np
import pandas as pd

from gridpulse.uncertainty import block_bootstrap_mean

df = pd.read_csv("outputs/dual_study/evaluation_daily_outcomes.csv").sort_values(["network", "information", "truth", "day"])
R1 = "1-LV-rural1--2-sw"
NEW = sorted(n for n in df.network.unique() if n != R1)
short = lambda n: n.split("-")[2]
VARIANTS = ["tap_raise_lv", "tap_lower_lv", "pv_cosphi_p", "pv_fixed_095", "storage_greedy", "storage_profile",
            "mv_high", "joint_realistic", "joint_loading"]
MATERIAL = {
    "1-LV-rural2--2-sw": ["tap_raise_lv", "pv_fixed_095", "storage_profile", "mv_high", "joint_realistic", "joint_loading"],
    "1-LV-rural3--2-sw": ["tap_raise_lv", "pv_fixed_095", "storage_profile", "mv_high", "joint_realistic", "joint_loading"],
    "1-LV-semiurb4--2-sw": ["pv_fixed_095", "joint_loading"],
    "1-LV-semiurb5--2-sw": ["tap_raise_lv", "pv_fixed_095", "storage_profile", "mv_high", "joint_realistic", "joint_loading"],
    "1-LV-urban6--2-sw": ["tap_raise_lv", "tap_lower_lv", "pv_fixed_095", "mv_high", "joint_realistic", "joint_loading"],
}
AWARE = ("replay_aci", "scenario_aci")
SIMPLE = ("static_dev", "static_beta", "static_aci", "point_margin")
BETA = 0.1
cells = {(c, i, t): g for (c, i, t), g in df.groupby(["network", "information", "truth"])}

def meets(g, p):
    return g[f"{p}__avoidable_violation_steps"].sum() / len(g) <= BETA

def better(g, a, b, **kw):
    ma, mb = meets(g, a), meets(g, b)
    m = "avoidable_violation_steps" if (ma and not mb) else "curtailed_mwh" if (ma and mb) else None
    if m is None:
        return False
    diff = g[f"{a}__{m}"].to_numpy(float) - g[f"{b}__{m}"].to_numpy(float)
    return block_bootstrap_mean(diff, **kw)["ci_high"] < 0

def verdict(**kw):
    res = {}
    for a in AWARE:
        nom = [c for c in NEW if all(better(cells[(c, "forecast", "nominal")], a, b, **kw) for b in SIMPLE)]
        mm = []
        for c in NEW:
            wins = [t for t in MATERIAL[c] if all(better(cells[(c, "forecast", t)], a, b, **kw) for b in SIMPLE)]
            if len(wins) >= math.ceil(len(MATERIAL[c]) / 2):
                mm.append(c)
        res[a] = (len(nom), len(mm), tuple(short(c) for c in nom))
    genuine = any(n >= 3 and m >= 3 for n, m, _ in res.values())
    simple = {b: sum(all(better(cells[(c, "forecast", "nominal")], b, a, **kw) for a in AWARE) for c in NEW) for b in SIMPLE}
    refuted = any(v >= 3 for v in simple.values())
    return res, ("genuine value" if genuine else "refuted" if refuted else "inconclusive")

# 1) block length sensitivity (seed 42)
print("=== block length sensitivity (seed 42, 2000 resamples) ===")
for bl in (1, 3, 5, 7, 10, 14, 21, 28):
    res, v = verdict(block_days=bl)
    print(f"block {bl:2d}: replay_aci nominal {res['replay_aci'][0]} {res['replay_aci'][2]} mismatch {res['replay_aci'][1]}; "
          f"scenario_aci nominal {res['scenario_aci'][0]} mismatch {res['scenario_aci'][1]} -> {v}")

# 2) seed sensitivity of each nominal replay_aci comparison (block 7)
print("\n=== seed sensitivity (seeds 0..199, block 7): share of seeds where replay_aci is 'better' at nominal ===")
for c in NEW:
    g = cells[(c, "forecast", "nominal")]
    for b in ("static_dev", "static_aci"):
        diff = g[f"replay_aci__curtailed_mwh"].to_numpy(float) - g[f"{b}__curtailed_mwh"].to_numpy(float)
        his = np.array([block_bootstrap_mean(diff, seed=s)["ci_high"] for s in range(200)])
        print(f"{short(c):9s} vs {b:10s}: P(ci_high<0) = {(his < 0).mean():.3f}; ci_high range [{his.min():+.5f}, {his.max():+.5f}]; est {diff.mean():+.5f}")
# verdict over seeds
counts = {}
for s in range(100):
    _, v = verdict(seed=s)
    counts[v] = counts.get(v, 0) + 1
print("verdict across seeds 0..99 (block 7):", counts)

# 3) days with non-zero curtailment difference, nominal
print("\n=== informative days of nominal curtailment differences ===")
for c in NEW:
    g = cells[(c, "forecast", "nominal")]
    for b in ("static_dev", "static_aci"):
        diff = g["replay_aci__curtailed_mwh"].to_numpy(float) - g[f"{b}__curtailed_mwh"].to_numpy(float)
        nz = np.abs(diff) > 1e-9
        pos = (diff > 1e-9).sum(); neg = (diff < -1e-9).sum()
        # also by month
        months = pd.to_datetime(g.date).dt.month.to_numpy()
        by_m = {m: round(diff[months == m].sum(), 3) for m in range(7, 13)}
        print(f"{short(c):9s} replay_aci - {b:10s}: nonzero days {nz.sum()} (neg {neg}, pos {pos}); monthly sums {by_m}")

# 4) duplicate cells: variant cells whose replay_aci and static_aci outcomes equal the nominal cell
print("\n=== variant cells identical to nominal for replay_aci and static_aci (curtailment and violations, forecast) ===")
for c in NEW:
    gn = cells[(c, "forecast", "nominal")]
    same = []
    for t in VARIANTS:
        g = cells[(c, "forecast", t)]
        eq = all(np.allclose(g[f"{p}__{m}"].to_numpy(float), gn[f"{p}__{m}"].to_numpy(float))
                 for p in ("replay_aci", "static_aci") for m in ("curtailed_mwh", "avoidable_violation_steps"))
        if eq:
            same.append(t)
    # pairwise near-identical variant cells
    pairs = []
    for i, t1 in enumerate(VARIANTS):
        for t2 in VARIANTS[i + 1:]:
            g1, g2 = cells[(c, "forecast", t1)], cells[(c, "forecast", t2)]
            d = max(abs(g1[f"{p}__curtailed_mwh"].sum() - g2[f"{p}__curtailed_mwh"].sum()) for p in ("replay_aci", "static_aci", "static_dev", "point_margin"))
            if d < 0.05 * g1["static_aci__curtailed_mwh"].sum():
                pairs.append(f"{t1}~{t2}")
    print(short(c), "identical-to-nominal:", same, "| near-duplicate variant pairs (<5% curtailment diff):", pairs)

# 5) mismatch cells (forecast, 45): replay_aci - static_aci curtailment CI below/above 0 where both meet
print("\n=== replay_aci vs static_aci in 45 mismatch cells (forecast) ===")
below = above = incl = 0
rows = []
for c in NEW:
    for t in VARIANTS:
        g = cells[(c, "forecast", t)]
        ma, mb = meets(g, "replay_aci"), meets(g, "static_aci")
        diff = g["replay_aci__curtailed_mwh"].to_numpy(float) - g["static_aci__curtailed_mwh"].to_numpy(float)
        r = block_bootstrap_mean(diff)
        tag = "below" if r["ci_high"] < 0 else "above" if r["ci_low"] > 0 else "incl0"
        if ma and mb:
            below += tag == "below"; above += tag == "above"; incl += tag == "incl0"
        rows.append((short(c), t, ma, mb, tag, t in MATERIAL[c]))
print(f"both meet: CI below 0 in {below}, above 0 in {above}, includes 0 in {incl}")
r = pd.DataFrame(rows, columns=["net", "truth", "ra_meets", "sa_meets", "tag", "material"])
print("material & both meet:", r[r.material & r.ra_meets & r.sa_meets].tag.value_counts().to_dict())
print(r[r.tag == "above"].to_string())

# 6) what decided each replay_aci mismatch win: which simple policies fail there
print("\n=== replay_aci material mismatch cells: simple policies meeting beta, and decisive comparison ===")
for c in NEW:
    for t in MATERIAL[c]:
        g = cells[(c, "forecast", t)]
        status = {b: meets(g, b) for b in SIMPLE}
        win = all(better(g, "replay_aci", b) for b in SIMPLE)
        failed = [b for b in SIMPLE if not better(g, "replay_aci", b)]
        print(f"{short(c):9s} {t:16s} replay meets={meets(g,'replay_aci')!s:5} simple meets={ {k[:9]: v for k, v in status.items()} } win={win} lost_to={failed}")
