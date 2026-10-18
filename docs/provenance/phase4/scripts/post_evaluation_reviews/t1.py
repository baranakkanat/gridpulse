"""Task 1: recompute document tables from the evaluation daily CSV only."""
import numpy as np
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_rows", 500)

df = pd.read_csv("outputs/dual_study/evaluation_daily_outcomes.csv")
R1 = "1-LV-rural1--2-sw"
NETS = sorted(df.network.unique())
NEW = [n for n in NETS if n != R1]
short = {n: n.split("-")[2] for n in NETS}
VARIANTS = [t for t in df.truth.unique() if t != "nominal"]
BETA = 0.1

# (a) forecast/nominal table
pols = ["no_action", "static_dev", "static_beta", "static_aci", "point_margin", "scenario_robust",
        "scenario_aci", "replay_robust", "replay_aci", "ensemble", "oracle"]
fn = df[(df.information == "forecast") & (df.truth == "nominal")]
print("(a) forecast/nominal: avoidable steps / curtailed MWh; * = meets beta")
rows = []
for p in pols:
    row = {"policy": p}
    sv, se = 0, 0.0
    for n in NETS:
        g = fn[fn.network == n]
        v = g[f"{p}__avoidable_violation_steps"].sum()
        e = g[f"{p}__curtailed_mwh"].sum()
        meets = v / len(g) <= BETA
        row[short[n]] = f"{v} / {e:.2f}{'*' if meets else ''}"
        if n != R1:
            sv += v; se += e
    row["SUM_new"] = f"{sv} / {se:.2f}"
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))

# static_dev == static_beta check in forecast/nominal
for n in NETS:
    g = fn[fn.network == n]
    same = (g.static_dev__curtailed_mwh == g.static_beta__curtailed_mwh).all()
    print(short[n], "static_dev==static_beta (curtailment per day identical):", same)
# all cells
print("static_dev==static_beta in all cells:",
      (df.static_dev__curtailed_mwh == df.static_beta__curtailed_mwh).all(),
      "new nets only:", (df[df.network != R1].static_dev__curtailed_mwh == df[df.network != R1].static_beta__curtailed_mwh).all())

# ratios in the reading
def tot(g, p, m):
    return g[f"{p}__{m}"].sum()
sd = sum(tot(fn[fn.network == n], "static_dev", "curtailed_mwh") for n in NEW)
orc = sum(tot(fn[fn.network == n], "oracle", "curtailed_mwh") for n in NEW)
ens = sum(tot(fn[fn.network == n], "ensemble", "curtailed_mwh") for n in NEW)
ra = sum(tot(fn[fn.network == n], "replay_aci", "curtailed_mwh") for n in NEW)
print(f"static_dev/oracle = {sd/orc:.4f}; ensemble/static_dev = {ens/sd:.3f}; replay_aci/static_dev = {ra/sd:.4f}")
for n in NETS:
    g = fn[fn.network == n]
    print(short[n], "replay_aci/static_dev curtailment ratio:",
          round(tot(g, "replay_aci", "curtailed_mwh") / tot(g, "static_dev", "curtailed_mwh"), 4),
          " replay_aci/static_aci:", round(tot(g, "replay_aci", "curtailed_mwh") / tot(g, "static_aci", "curtailed_mwh"), 4))

# (b) cells meeting beta, forecast, 5 new x 10 truths
print("\n(b) cells meeting beta (forecast, new nets x 10 truths)")
fc = df[(df.information == "forecast") & (df.network.isin(NEW))]
agg = fc.groupby(["network", "truth"]).sum(numeric_only=True)
ndays = fc.groupby(["network", "truth"]).size()
for p in ["static_dev", "static_beta", "scenario_robust", "replay_robust", "ensemble", "point_margin",
          "static_aci", "scenario_aci", "replay_aci", "point", "point_aci", "scenario_risk"]:
    per_day = agg[f"{p}__avoidable_violation_steps"] / ndays
    counts = {b: int((per_day <= b).sum()) for b in (0.1, 0.05, 0.2)}
    print(f"{p:16s} 0.1:{counts[0.1]:3d}/50  0.05:{counts[0.05]:3d}/50  0.2:{counts[0.2]:3d}/50   n_cells={len(per_day)}")
# check exclusions (unavoidable daylight steps)
unav = agg["unavoidable_daylight_steps"]
print("max unavoidable daylight steps in any forecast cell (new):", unav.max(), " excluded cells:", int((unav > 0.1 * 183).sum()))
unav_all = df.groupby(["network", "information", "truth"]).unavoidable_daylight_steps.sum()
print("max unavoidable daylight steps any cell (all):", unav_all.max())

# which truths fail for static_dev
per_day = agg["static_dev__avoidable_violation_steps"] / ndays
print("static_dev failing cells:\n", per_day[per_day > 0.1].unstack().round(2))

# (c) replay_aci / static_aci in mismatch cells where both meet beta
print("\n(c) replay_aci / static_aci curtailment ratio in mismatch cells where both meet beta")
mm = agg.reset_index()
mm = mm[mm.truth != "nominal"]
nd = 183
mm["ra_meets"] = mm.replay_aci__avoidable_violation_steps / nd <= BETA
mm["sa_meets"] = mm.static_aci__avoidable_violation_steps / nd <= BETA
both = mm[mm.ra_meets & mm.sa_meets].copy()
both["ratio"] = both.replay_aci__curtailed_mwh / both.static_aci__curtailed_mwh
print("n cells:", len(both), " median ratio:", round(both.ratio.median(), 4),
      " min:", round(both.ratio.min(), 4), " max:", round(both.ratio.max(), 4),
      " count<1:", int((both.ratio < 1).sum()))
print("cells where one fails:", mm[~(mm.ra_meets & mm.sa_meets)][["network", "truth", "ra_meets", "sa_meets",
      "replay_aci__avoidable_violation_steps", "static_aci__avoidable_violation_steps"]].to_string())
both["save_mwh"] = both.static_aci__curtailed_mwh - both.replay_aci__curtailed_mwh
print(both[["network", "truth", "replay_aci__curtailed_mwh", "static_aci__curtailed_mwh", "ratio", "save_mwh"]]
      .sort_values("ratio").to_string())
print("by truth median ratio:\n", both.groupby("truth").ratio.median().round(3))
pv = mm[mm.truth == "pv_fixed_095"]
print("pv_fixed_095 static_aci - replay_aci MWh by network:\n",
      (pv.set_index("network").static_aci__curtailed_mwh - pv.set_index("network").replay_aci__curtailed_mwh).round(2))

# (d) static_dev totals under tap_raise_lv, mv_high, pv_fixed_095 (forecast and perfect)
print("\n(d) static_dev avoidable violation totals, new networks")
for info in ("forecast", "perfect"):
    s = df[(df.information == info) & df.network.isin(NEW)].groupby(["truth", "network"]).static_dev__avoidable_violation_steps.sum()
    for t in ("tap_raise_lv", "mv_high", "pv_fixed_095"):
        print(info, t, int(s[t].sum()), dict(s[t].astype(int).rename(short)))
    print(info, "max single cell:", int(s.max()), s.idxmax())

# (e) physical-safety indicators at nominal truth, forecast, five new networks
print("\n(e) physical safety, forecast/nominal, new networks")
g = fn[fn.network.isin(NEW)]
for p in ["static_dev", "static_aci", "scenario_aci", "replay_aci", "ensemble"]:
    dv = (g[f"{p}__avoidable_violation_steps"] > 0).sum()
    worst = g[f"{p}__avoidable_violation_steps"].max()
    longest = g[f"{p}__longest_violation_run"].max()
    lr = g[f"{p}__long_runs"].sum()
    sev = g[f"{p}__severe_steps"].sum()
    peak = g[f"{p}__peak_margin"].max()
    allv = g[f"{p}__violation_steps"].sum()
    dl = g[f"{p}__daylight_violation_steps"].sum()
    per_net_days = g.groupby("network")[f"{p}__avoidable_violation_steps"].apply(lambda x: (x > 0).sum()).to_dict()
    print(f"{p:13s} days={dv} worst={worst} longest={longest} runs>=1h={lr} severe={sev} peak={peak:.3f} "
          f"all_viol={allv} daylight={dl} per-net-days={ {short[k]: v for k, v in per_net_days.items()} }")
