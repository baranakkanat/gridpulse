import networkx as nx, pandapower.topology as top, warnings
from gridpulse import dual_study as ds
warnings.simplefilter("ignore")
for code, line in [("1-LV-semiurb4--2-sw",38),("1-LV-semiurb5--2-sw",26),("1-LV-urban6--2-sw",33),("1-LV-rural3--2-sw",79)]:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    lvbus = net.trafo.lv_bus.iloc[0]
    hops = nx.single_source_shortest_path_length(top.create_nxgraph(net, include_trafos=False), lvbus)
    l = net.line.loc[line]
    # PV downstream of the line: buses on the far side
    g = top.create_nxgraph(net, include_trafos=False); g.remove_edge(l.from_bus, l.to_bus)
    far = l.to_bus if hops[l.to_bus] > hops[l.from_bus] else l.from_bus
    comp = nx.node_connected_component(g, far)
    share = net.sgen[net.sgen.bus.isin(comp)].sn_mva.sum()/net.sgen.sn_mva.sum()
    heads = net.line[(net.line.from_bus==lvbus)|(net.line.to_bus==lvbus)]
    print(code, "line", line, "hops", hops[l.from_bus], hops[l.to_bus], "max_i_ka", l.max_i_ka, "type", l.std_type, "| feeder-head max_i_ka", sorted(set(heads.max_i_ka.round(3))), f"| PV downstream share {share:.0%}")
