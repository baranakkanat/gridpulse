"""Where do the binding voltage and line limits sit (feeder head vs remote)?"""
import numpy as np, pickle, os, warnings
import networkx as nx
import pandapower as pp, pandapower.topology as top
from pathlib import Path
from gridpulse import dual_study as ds, grid_study
from gridpulse.grid import absolute_profiles, cap_pv
warnings.simplefilter("ignore")
OUT = Path(os.path.dirname(__file__))
CACHE = Path("outputs/dual_study/physics_cache")
avail = pickle.load(open(OUT/"avail.pkl","rb"))
V = {"nominal": ds.NOMINAL, "tap_raise_lv": ds.ModelVariant(tap_steps=-1), "mv_high": ds.ModelVariant(slack_vm_pu=1.055),
     "pv_fixed_095": ds.ModelVariant(pv_reactive="fixed", pv_cosphi=0.95)}
for code in ds.HOSTING_CAPACITY:
    if "rural1" in code: continue
    pv, rating, _ = avail[code]
    net0 = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    arr = grid_study.daily_arrays(absolute_profiles(net0))
    lvbus = net0.trafo.lv_bus.iloc[0]
    g = top.create_nxgraph(net0, include_trafos=False)
    hops = nx.single_source_shortest_path_length(g, lvbus)
    # electrical distance: sum of line length along path
    gl = top.create_nxgraph(net0, include_trafos=False, calc_branch_impedances=False)
    dist = nx.single_source_dijkstra_path_length(gl, lvbus, weight="weight")
    maxhop = max(hops.values()); maxdist = max(dist.values())
    feeders = net0.line[(net0.line.from_bus == lvbus) | (net0.line.to_bus == lvbus)].index.tolist()
    pvbus_hops = sorted(hops[b] for b in net0.sgen.bus)
    print(f"\n=== {code}: LV busbar {lvbus}, {len(feeders)} feeder-head lines, max hops {maxhop}, max length {maxdist:.3f} km; PV-bus hops {pvbus_hops}")
    for vname, variant in V.items():
        net = ds.variant_network(code, variant, ds.pv_scale(code))
        solver = ds.VariantSolver(net, variant)
        # pick evaluation steps where the static cap (0.4) violates under this truth, else the 10 highest-PV steps
        m = {d: np.load(CACHE/code/vname/f"day_{d:03d}.npy")[0] for d in range(182, 365)}
        cand = [(d, t) for d in m for t in range(96) if (m[d][t, 6] > 0).any()]
        if not cand:
            tot = [(pv[d, t].sum(), d, t) for d in range(182, 365) for t in range(96)]
            cand = [(d, t) for _, d, t in sorted(tot)[-10:]]
            label = "top-PV steps (no violation)"
        else:
            label = f"{len(cand)} violating steps at cap 0.4"
        rng = np.random.default_rng(0)
        pick = [cand[i] for i in rng.choice(len(cand), size=min(15, len(cand)), replace=False)]
        vb, ln, onhead = [], [], 0
        for d, t in pick:
            capped = cap_pv(arr["sgen_p_mw"][d, t], solver.pv_rating_mw, 0.4)
            solver.reset()
            solver.solve(arr["load_p_mw"][d, t], arr["load_q_mvar"][d, t], capped, np.zeros(len(net.storage)))
            rb = solver.net.res_bus.vm_pu.drop(net.ext_grid.bus)
            b = rb.idxmax(); vb.append((hops.get(b, -1), round(rb.max(), 3), round(solver.net.res_bus.vm_pu[lvbus], 3)))
            l = solver.net.res_line.loading_percent.idxmax(); ln.append((l, round(solver.net.res_line.loading_percent.max())))
            onhead += l in feeders
        print(f"  {vname:13s} [{label}] maxV bus hops/Vmax/Vbusbar sample {vb[:5]} | max-loaded line on feeder head in {onhead}/{len(pick)}; lines {sorted(set(x[0] for x in ln))}, loading {[x[1] for x in ln[:5]]}")
