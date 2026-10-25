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
for code in ["1-LV-rural3--2-sw"]:
    net0 = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
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
    days = [188]
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
        e = res.x; slack = np.concatenate(b) - np.vstack(A) @ e
        nv = len(cust); act_v = int((slack[:nv] < 1e-6).sum()); act_t = int((slack[nv:] < 1e-6).sum())
        net.sgen["p_mw"] = e; solve(net)
        vm = net.res_bus.vm_pu.reindex(cust).to_numpy()
        print(f"{code} day {d} t {t}: avail {a.sum():.3f} MW -> e {e.sum():.3f} MW ({e.sum()/a.sum():.2f}); active V {act_v}, thermal {act_t}; "
              f"AC corner max(v-vmax) {np.max(vm - vmax):+.4f}, max line {net.res_line.loading_percent.max():.1f}%, trafo {net.res_trafo.loading_percent.max():.1f}%; units at bound {int((np.abs(e-a)<1e-9).sum())}/{len(a)}, at zero {int((e<1e-9).sum())}")
print("audit solves:", SOLVES)
print("load P sum", net.load.p_mw.sum(), "load Q sum", net.load.q_mvar.sum(), "sgen sum", net.sgen.p_mw.sum(), "n loads", len(net.load))
print(net.res_trafo[["p_hv_mw","q_hv_mvar","p_lv_mw","q_lv_mvar","i_lv_ka","loading_percent"]])
print("trafo", net.trafo[["sn_mva","vn_lv_kv","vn_hv_kv"]].to_dict("records"), "ext_grid vm", net.ext_grid.vm_pu.tolist())
print("load shape", np.asarray(arrays["load_p_mw"]).shape, "sgen shape", pv.shape)
print("bus at trafo lv", net.res_bus.vm_pu[root])
