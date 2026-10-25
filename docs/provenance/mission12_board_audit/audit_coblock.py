"""Board audit, zero solves: are co-blocking lines series segments of one route with equal recorded ratings?"""
import sys, json, collections
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np, networkx as nx
from gridpulse import dual_study as ds
A = json.load(open("audit_relevance.json"))  # edited: was a local scratch path (run audit_relevance.py first, same directory)
for code in ["1-LV-semiurb4--2-sw", "1-LV-semiurb5--2-sw", "1-LV-urban6--2-sw"]:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    root = int(net.trafo.lv_bus.iloc[0]); g = nx.Graph()
    for i, r in net.line.iterrows(): g.add_edge(int(r.from_bus), int(r.to_bus), line=int(i))
    tree = nx.bfs_tree(g, root)
    def path_lines(bus):
        p = nx.shortest_path(tree, root, bus); return [g.edges[p[k], p[k+1]]["line"] for k in range(len(p)-1)]
    child = {}
    for u, v in tree.edges(): child[g.edges[u, v]["line"]] = v
    top = [l for l, _ in A[code]["top_blocking_lines_recorded"]]
    rated = net.line.max_i_ka.to_numpy()
    print(code, "top co-blocking lines:", top)
    for l in top:
        pl = path_lines(child[l])
        print(f"  line {l}: depth {len(pl)}, path {pl}, same-rating-as-first-top: {np.isclose(rated[l], rated[top[0]])}, std_type-equal-first: {net.line.std_type[l] == net.line.std_type[top[0]]}")
    # are the top lines nested on one root path?
    paths = [set(path_lines(child[l])) for l in top]
    print("  all top lines on one root-to-leaf path:", all(set(top) <= max(paths, key=len) | {top[i]} for i in range(len(top))), "| distinct max_i_ka among top:", len(set(np.round(rated[top], 6))))
