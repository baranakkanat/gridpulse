"""Board design audit (counted solves): which constraints bind at the TRUE-model envelope optimum?
Offline truth used for design relevance only. Balanced LinDistFlow sensitivities + AC offset."""
import sys, copy, warnings, collections
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np
from scipy.optimize import linprog
import pandapower as pp
from gridpulse import dual_study as ds, grid, grid_study
SOLVES = 0
def solve(net):
    global SOLVES
    SOLVES += 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pp.runpp(net, algorithm="nr", numba=False, check_connectivity=False)
def tree(net):
    root = int(net.trafo.lv_bus.iloc[0]); adj = collections.defaultdict(list)
    for l in net.line.index:
        a, b = int(net.line.at[l, "from_bus"]), int(net.line.at[l, "to_bus"]); adj[a].append((b, l)); adj[b].append((a, l))
    parent = {root: (None, None)}; order = [root]
    for u in order:
        for v, l in adj[u]:
            if v not in parent: parent[v] = (u, l); order.append(v)
    return root, parent
for code in ["1-LV-rural3--2-sw", "1-LV-urban6--2-sw"]:
    net0 = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code)); net0.storage["p_mw"] = 0.0
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net0))
    root, parent = tree(net0)
    V = float(net0.bus.vn_kv[root]); tr = net0.trafo.iloc[0]
    r_tr = tr.vkr_percent / 100 * tr.vn_lv_kv**2 / tr.sn_mva
    # path resistance R_path[bus] as set of lines; common-path R for sensitivity
    paths = {}
    for b in parent:
        p, cur = [], b
        while parent[cur][0] is not None: p.append(parent[cur][1]); cur = parent[cur][0]
        paths[b] = set(p)
    rl = {l: net0.line.at[l, "r_ohm_per_km"] * net0.line.at[l, "length_km"] / net0.line.at[l, "parallel"] for l in net0.line.index}
    cust = sorted(set(net0.load.bus) | set(net0.sgen.bus)); pvb = list(net0.sgen.bus)
    S = np.array([[ (r_tr + sum(rl[l] for l in paths[k] & paths[j])) / V**2 for j in pvb] for k in cust])  # pu per MW
    imax = {l: net0.line.at[l, "max_i_ka"] * np.sqrt(3) * V for l in net0.line.index}  # MVA
    pv = np.asarray(arrays["sgen_p_mw"]); tot = pv.sum(axis=2)
    days = np.argsort(tot[150:200].max(axis=1))[-3:] + 150
    for d in days:
        t = int(np.argmax(tot[d])); net = copy.deepcopy(net0)
        net.load["p_mw"] = arrays["load_p_mw"][d, t]; net.load["q_mvar"] = arrays["load_q_mvar"][d, t]
        a = net0.sgen.sn_mva.to_numpy() * float(np.mean(pv[d, t] / net0.sgen.sn_mva.to_numpy()))
        net.sgen["p_mw"] = a; solve(net)
        v0 = net.res_bus.vm_pu.reindex(cust).to_numpy(); vmax = net.bus.max_vm_pu.reindex(cust).to_numpy()
        # LP: max sum e, e<=a; v0 + S(e-a) <= vmax ; thermal: line downstream flows
        A, b = [S], [vmax - v0 + S @ a]
        loadP = net.load.groupby("bus").p_mw.sum()
        for l in net0.line.index:
            to = int(net0.line.at[l, "to_bus"]); fr = int(net0.line.at[l, "from_bus"])
            child = to if parent.get(to, (None,))[0] == fr else fr
            down = {bb for bb in parent if l in paths[bb]}
            row = np.array([1.0 if j in down else 0.0 for j in pvb]); base = loadP.reindex(list(down)).fillna(0).sum()
            A.append(row[None, :]); b.append(np.array([imax[l] + base]))  # reverse flow: sum e - load <= cap
        A.append(np.ones((1, len(pvb)))); b.append(np.array([tr.sn_mva + loadP.sum()]))
        res = linprog(-np.ones(len(pvb)), A_ub=np.vstack(A), b_ub=np.concatenate(b), bounds=list(zip([0]*len(pvb), a)), method="highs")
        e = res.x; tot_e = e.sum(); Aub, bub = np.vstack(A[len(cust)>0 and 1:]) if False else None, None
        Ath, bth = np.vstack(A[1:]), np.concatenate(b[1:])
        lin_v = v0 + S @ (e - a)
        # worst allocation at the same total, thermal-feasible: max S_k e over polytope, every k
        worst, wk, we = -9, None, None
        for k in range(len(cust)):
            r = linprog(-S[k], A_ub=Ath, b_ub=bth, A_eq=np.ones((1, len(pvb))), b_eq=[tot_e], bounds=list(zip([0]*len(pvb), a)), method="highs")
            val = v0[k] + S[k] @ (r.x - a) - vmax[k]
            if val > worst: worst, wk, we = val, k, r.x
        # proportional fair: theta_th and theta_v (linear)
        th_th = min(1.0, min((bth - 0) / np.maximum(Ath @ a, 1e-12)))
        dv = S @ a; th_v = min(1.0, np.min(np.where(dv > 0, 1 - (v0 - vmax) / np.maximum(dv, 1e-12) * 0 - (v0 - vmax + 0) / np.maximum(dv,1e-12), 9)))
        net.sgen["p_mw"] = e; solve(net); vm1 = net.res_bus.vm_pu.reindex(cust).to_numpy()
        net.sgen["p_mw"] = we; solve(net); vm2 = net.res_bus.vm_pu.reindex(cust).to_numpy()
        print(f"{code} d{d} t{t}: sum e {tot_e:.3f}/{a.sum():.3f}; HiGHS alloc AC v-margin {np.max(vm1-vmax):+.4f} (lin {np.max(lin_v-vmax):+.4f}); "
              f"worst same-total alloc lin {worst:+.4f} AC {np.max(vm2-vmax):+.4f} line {net.res_line.loading_percent.max():.0f}% trafo {net.res_trafo.loading_percent.max():.0f}%; "
              f"no-action v-margin {np.max(v0-vmax):+.4f}; theta_th {th_th:.2f} theta_v {th_v:.2f}")
print("audit solves:", SOLVES)
