import numpy as np, pandas as pd
from pathlib import Path
from gridpulse import dual_study as ds, grid_study as gs
from gridpulse.grid import absolute_profiles
cache = Path("outputs/grid_study/physics_cache")
nom = {d: np.load(cache / f"day_{d:03d}.npy") for d in range(35, 365)}
net = ds.variant_network(gs.NETWORK_CODE, ds.NOMINAL)
arrays = gs.daily_arrays(absolute_profiles(net)); rating = net.sgen["sn_mva"].to_numpy(float)
solver = ds.VariantSolver(net, ds.NOMINAL)
for d in range(7, 35):
    nom[d] = ds.day_margins(solver, ds.day_sets(arrays, d, rating, 1), np.zeros((96, len(net.storage))))
variants = {"copy": {d: nom[d][:2] for d in range(35, 365)}}
records, tuned = ds.run_cell(nom, variants, "nominal", ("copy",), "forecast", arrays["sgen_p_mw"], rating,
                             list(range(35, 182)), list(range(182, 365)), ds.OnlineSettings())
new = pd.DataFrame(records).set_index("day")
old = pd.read_csv("outputs/grid_study/evaluation_daily_outcomes.csv").set_index("day")
print("tuned", tuned)
for a, b in (("no_action", "no_action"), ("point", "point"), ("scenario_risk", "risk"), ("scenario_robust", "robust"), ("oracle", "oracle"), ("static_dev", "static_dev")):
    v = (new[f"{a}__violation_steps"] == old[f"{b}__violation_steps"]).all()
    e = np.abs(new[f"{a}__curtailed_mwh"] - old[f"{b}__curtailed_mwh"]).max()
    print(f"{a:16s} violations identical: {v}, max |curtailment diff| {e:.2e}, total V {new[f'{a}__violation_steps'].sum()}, E {new[f'{a}__curtailed_mwh'].sum():.3f}")
for a in ("ensemble", "point_margin", "point_aci", "scenario_aci", "replay_robust", "replay_aci", "static_aci"):
    print(f"{a:16s} V {new[f'{a}__violation_steps'].sum():4d}  E {new[f'{a}__curtailed_mwh'].sum():7.3f}")
print("ensemble==scenario_robust:", (new["ensemble__violation_steps"] == new["scenario_robust__violation_steps"]).all())
