import json, statistics as st, collections
R = str(__import__("pathlib").Path(__file__).resolve().parents[3] / "analysis" / "export_envelope_shift" / "results") + "/"  # edited: was an absolute local path
env = json.load(open(R + "envelopes_rural3.json")); orc = json.load(open(R + "oracle_rural3.json"))
okeys = [k for k in orc.keys()]
conds = orc.get("conditions") or orc.get("records")
o_tot = {}
for c in conds:
    o_tot[(c["day"], c["step"])] = c.get("total_e") or c.get("sum_e")
groups = collections.defaultdict(list)
for r in env["records"]:
    if r["kind"] != "near": continue
    key = (r["method"], r.get("regime") or "-")
    groups[key].append(r)
print("method regime | n unsafe-conds | median companion util | median util(safe only) | max exceed | mean exceed(unsafe)")
for (m, g), rs in sorted(groups.items()):
    byc = collections.defaultdict(list)
    for r in rs: byc[(r["day"], r["step"])].append(r)
    comp, safe_u, unsafe_c = [], [], 0
    for c, lst in byc.items():
        u = [0.0 if x["unsafe"] else x["total_e"] / o_tot[c] for x in lst]
        comp.append(sum(u) / len(u))
        if all(not x["unsafe"] for x in lst): safe_u.append(sum(x["total_e"] / o_tot[c] for x in lst) / len(lst))
        if any(x["unsafe"] for x in lst): unsafe_c += 1
    ex = [x["max_exceedance"] for x in rs]; exu = [e for e in ex if e > 0.001]
    print(f"{m:7s} {g:3s} | {unsafe_c:2d}/{len(byc)} | {st.median(comp):.3f} | {(st.median(safe_u) if safe_u else float('nan')):.3f} | {max(ex):+.4f} | {(sum(exu)/len(exu) if exu else 0):+.4f}")
print("oracle totals", sorted(round(v, 4) for v in o_tot.values()))
