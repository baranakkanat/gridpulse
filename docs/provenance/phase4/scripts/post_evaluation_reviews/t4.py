"""How much did online controller states move during evaluation (vs end of development)?"""
import pandas as pd

df = pd.read_csv("outputs/dual_study/evaluation_daily_outcomes.csv").sort_values(["network", "information", "truth", "day"])
R1 = "1-LV-rural1--2-sw"
fc = df[(df.information == "forecast") & (df.network != R1)]
rows = []
for (c, t), g in fc.groupby(["network", "truth"]):
    rows.append({
        "net": c.split("-")[2], "truth": t,
        "sa_level_start": round(g.static_aci__level_index.iloc[0], 2), "sa_level_end": round(g.static_aci__level_index.iloc[-1], 2),
        "sa_applied_levels": sorted(set((g.static_aci__level_index + 0.5).astype(int))),
        "ra_tau_start": round(g.replay_aci__tau.iloc[0], 3), "ra_tau_end": round(g.replay_aci__tau.iloc[-1], 3),
        "ra_tau_min": round(g.replay_aci__tau.min(), 3), "ra_tau_max": round(g.replay_aci__tau.max(), 3),
    })
r = pd.DataFrame(rows)
print(r.to_string())
print("\nstatic_aci applied level constant through evaluation in", int((r.sa_applied_levels.apply(len) == 1).sum()), "of", len(r), "cells")
print("replay_aci |tau_end - tau_start| median", (r.ra_tau_end - r.ra_tau_start).abs().median(), "max", (r.ra_tau_end - r.ra_tau_start).abs().max())
# static_dev level vs static_aci applied level at evaluation start by truth
