"""Board design audit (counted): voltage- vs thermal-limited regime per SimBench LV network, storage idle,
days 100-131 (outside every Mission 11 split). No-action AC per condition; theta from balanced LinDistFlow."""
import sys, copy, warnings, collections
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np, pandapower as pp
from gridpulse import dual_study as ds, grid, grid_study
SOLVES = 0
for code in ds.HOSTING_CAPACITY:
    net0 = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code)); net0.storage["p_mw"] = 0.0
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net0))
    root = int(net0.trafo.lv_bus.iloc[0]); adj = collections.defaultdict(list)
    for l in net0.line.index:
        x, y = int(net0.line.at[l, "from_bus"]), int(net0.line.at[l, "to_bus"]); adj[x].append((y, l)); adj[y].append((x, l))
    parent = {root: (None, None)}; order = [root]
    for u in order:
        for v, l in adj[u]:
            if v not in parent: parent[v] = (u, l); order.append(v)
    paths = {}
    for bb in parent:
        p, cur = set(), bb
        while parent[cur][0] is not None: p.add(parent[cur][1]); cur = parent[cur][0]
        paths[bb] = p
    V = float(net0.bus.vn_kv[root]); tr = net0.trafo.iloc[0]; r_tr = tr.vkr_percent / 100 * tr.vn_lv_kv**2 / tr.sn_mva
    rl = {l: net0.line.at[l, "r_ohm_per_km"] * net0.line.at[l, "length_km"] for l in net0.line.index}
    cust = sorted(set(net0.load.bus) | set(net0.sgen.bus)); pvb = list(net0.sgen.bus)
    S = np.array([[(r_tr + sum(rl[l] for l in paths[k] & paths[j])) / V**2 for j in pvb] for k in cust])
    pv = np.asarray(arrays["sgen_p_mw"]); tot = pv.sum(axis=2)
    rows = []
    for d in np.argsort(tot[100:132].max(axis=1))[-3:] + 100:
        t = int(np.argmax(tot[d])); net = copy.deepcopy(net0)
        net.load["p_mw"] = arrays["load_p_mw"][d, t]; net.load["q_mvar"] = arrays["load_q_mvar"][d, t]; net.sgen["p_mw"] = pv[d, t]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore"); pp.runpp(net, algorithm="nr", numba=False, check_connectivity=False)
        SOLVES += 1
        a = pv[d, t]; v0 = net.res_bus.vm_pu.reindex(cust).to_numpy(); vmax = net.bus.max_vm_pu.reindex(cust).to_numpy()
        dv = S @ a; th_v = float(np.clip(np.min(np.where(dv > 0, 1 - (v0 - vmax) / np.maximum(dv, 1e-12), 9)), 0, 1))
        lp = net.res_line.loading_percent.max(); tp = net.res_trafo.loading_percent.max()
        th_th = min(1.0, 100 / max(lp, tp)) if max(lp, tp) > 100 else 1.0
        rows.append((d, t, np.max(v0 - vmax), lp, tp, th_v, th_th))
    print(code, " | ".join(f"d{d} t{t} vmarg {m:+.4f} line {lp:.0f}% trafo {tp:.0f}% thV~{tv:.2f} thT~{tt:.2f}" for d, t, m, lp, tp, tv, tt in rows))
print("audit solves:", SOLVES)
