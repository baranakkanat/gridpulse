"""Task 1 (cont.): adverse-mismatch safety claims, rule of three, H4, D1 from the CSV."""
import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)
df = pd.read_csv("outputs/dual_study/evaluation_daily_outcomes.csv")
R1 = "1-LV-rural1--2-sw"
NEW = sorted(n for n in df.network.unique() if n != R1)
short = lambda n: n.split("-")[2]
VARIANTS = [t for t in df.truth.unique() if t != "nominal"]
ENSEMBLE = ["tap_raise_lv", "tap_lower_lv", "pv_cosphi_p", "pv_fixed_095", "storage_greedy", "storage_profile"]
OOE = ["mv_high", "joint_realistic", "joint_loading"]
FAILING = ["tap_raise_lv", "pv_fixed_095", "mv_high", "joint_realistic", "joint_loading"]

def cellstats(g, p):
    return pd.Series({
        "aviol": g[f"{p}__avoidable_violation_steps"].sum(),
        "worst": g[f"{p}__avoidable_violation_steps"].max(),
        "longest": g[f"{p}__longest_violation_run"].max(),
        "long_runs": g[f"{p}__long_runs"].sum(),
        "severe": g[f"{p}__severe_steps"].sum(),
        "peak": g[f"{p}__peak_margin"].max(),
        "curt": g[f"{p}__curtailed_mwh"].sum(),
    })

fc = df[(df.information == "forecast") & df.network.isin(NEW)]
for p in ("static_dev", "replay_aci"):
    s = fc[fc.truth != "nominal"].groupby(["network", "truth"]).apply(lambda g: cellstats(g, p))
    print(f"\n=== {p}, forecast, variant truths (new nets) ===")
    print(s.round(3).to_string())
    sf = s[s.index.get_level_values("truth").isin(FAILING)]
    print(f"{p} over FAILING truths: worst-day range {sf.worst.min()}-{sf.worst.max()}, max long_runs {sf.long_runs.max()},"
          f" max longest {sf.longest.max()}, max severe {sf.severe.max()}, peak max {sf.peak.max():.3f}")
    print(f"{p} over ALL variant truths: worst-day max {s.worst.max()}, longest max {s.longest.max()}, severe max {s.severe.max()}, peak max {s.peak.max():.3f}")
    # static_dev failing cells only
    if p == "static_dev":
        failing_cells = s[s.aviol / 183 > 0.1]
        print("static_dev failing cells: worst-day range", failing_cells.worst.min(), "-", failing_cells.worst.max(),
              "; long_runs max", failing_cells.long_runs.max(), "; severe by cell:\n", failing_cells.severe)

# replay_aci also in F0? (perfect info) for completeness
fp = df[(df.information == "perfect") & df.network.isin(NEW)]
s = fp[fp.truth != "nominal"].groupby(["network", "truth"]).apply(lambda g: cellstats(g, "replay_aci"))
print("\nreplay_aci F0 variants: worst max", s.worst.max(), "longest max", s.longest.max(), "severe max", s.severe.max(), "peak max", round(s.peak.max(), 3))

# rule of three: days on which no_action has an avoidable violation at nominal truth
print("\nRule of three n (no_action avoidable-violation days, nominal truth):")
for info in ("forecast", "perfect"):
    g = df[(df.information == info) & (df.truth == "nominal")]
    n = g.groupby("network").no_action__avoidable_violation_steps.apply(lambda x: int((x > 0).sum()))
    print(info, {short(k): (v, round(3 / v, 3)) for k, v in n.items()})
# across all truths for context
g = df[(df.information == "forecast")]
n = g.groupby(["network", "truth"]).no_action__avoidable_violation_steps.apply(lambda x: int((x > 0).sum()))
print("no_action violation days across truths, min/max per network:", n.groupby(level=0).agg(["min", "max"]).to_dict())

# H4 from CSV
def meets(info, truth, policy, code, beta=0.1):
    g = df[(df.information == info) & (df.truth == truth) & (df.network == code)]
    return g[f"{policy}__avoidable_violation_steps"].sum() / len(g) <= beta
print("\nH4(a) point F0 fails per network:", {short(c): sum(not meets("perfect", t, "point", c) for t in VARIANTS) for c in NEW})
print("H4(a) point F0 nominal meets:", {short(c): meets("perfect", "nominal", "point", c) for c in NEW})
print("H4(b) ensemble F0 in-ensemble fails:", {short(c): sum(not meets("perfect", t, "ensemble", c) for t in ENSEMBLE) for c in NEW})
print("H4(c) F0: ensemble fails", sum(not meets("perfect", t, "ensemble", c) for c in NEW for t in OOE),
      " point_aci fails", sum(not meets("perfect", t, "point_aci", c) for c in NEW for t in OOE))
print("H4(c) F1: ensemble fails", sum(not meets("forecast", t, "ensemble", c) for c in NEW for t in OOE),
      " replay_aci fails", sum(not meets("forecast", t, "replay_aci", c) for c in NEW for t in OOE),
      " static_aci fails", sum(not meets("forecast", t, "static_aci", c) for c in NEW for t in OOE),
      " scenario_aci fails", sum(not meets("forecast", t, "scenario_aci", c) for c in NEW for t in OOE))
print("H4(c) F0: replay_aci fails", sum(not meets("perfect", t, "replay_aci", c) for c in NEW for t in OOE),
      " static_aci fails", sum(not meets("perfect", t, "static_aci", c) for c in NEW for t in OOE))
# per network
for info, fb in (("perfect", "point_aci"), ("forecast", "replay_aci")):
    print(info, {short(c): (sum(not meets(info, t, "ensemble", c) for t in OOE), sum(not meets(info, t, fb, c) for t in OOE)) for c in NEW})
# ensemble F1 in-ensemble fails
print("ensemble F1 in-ensemble fails:", {short(c): [t for t in ENSEMBLE if not meets("forecast", t, "ensemble", c)] for c in NEW})

# D1 interaction for point
def V(info, truth, c, p="point"):
    g = df[(df.information == info) & (df.truth == truth) & (df.network == c)]
    return g[f"{p}__avoidable_violation_steps"].sum()
inter = {short(c): {t: V("forecast", t, c) - V("forecast", "nominal", c) - V("perfect", t, c) + V("perfect", "nominal", c) for t in VARIANTS} for c in NEW}
it = pd.DataFrame(inter)
print("\nD1 point interaction:\n", it, "\nmin", it.values.min(), "max", it.values.max())
print("point F1 nominal per net:", {short(c): V("forecast", "nominal", c) for c in NEW})
print("point F0 nominal per net:", {short(c): V("perfect", "nominal", c) for c in NEW})
print("no_action nominal per net:", {short(c): V("forecast", "nominal", c, "no_action") for c in NEW})
# also scenario_robust: D1 registered 'for point and scenario_robust' - scenario_robust only F1, so compare F1xv vs F1xnom
print("scenario_robust F1 by truth:\n", pd.DataFrame({short(c): {t: V("forecast", t, c, "scenario_robust") for t in ["nominal"] + VARIANTS} for c in NEW}))
print("point F0 by truth:\n", pd.DataFrame({short(c): {t: V("perfect", t, c) for t in ["nominal"] + VARIANTS} for c in NEW}))
print("point F1 by truth:\n", pd.DataFrame({short(c): {t: V("forecast", t, c) for t in ["nominal"] + VARIANTS} for c in NEW}))
print("no_action by truth:\n", pd.DataFrame({short(c): {t: V("forecast", t, c, "no_action") for t in ["nominal"] + VARIANTS} for c in NEW}))
