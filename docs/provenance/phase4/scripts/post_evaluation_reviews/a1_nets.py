import numpy as np
from gridpulse import dual_study as ds
from gridpulse.grid import load_network
for code in ds.HOSTING_CAPACITY:
    net = load_network(code)
    s = ds.pv_scale(code)
    lv = net.bus[~net.bus.index.isin(net.ext_grid.bus)]
    t = net.trafo.iloc[0]
    print(code, "scale %.2f" % s, "PV MW %.3f" % (net.sgen.sn_mva.sum()*s), "trafo MVA", t.sn_mva,
          "tap", t.tap_pos, "tap_side", t.tap_side, "vn_hv", t.vn_hv_kv, "vn_lv", t.vn_lv_kv,
          "max_vm", sorted(set(lv.max_vm_pu.round(3))), "min_vm", sorted(set(lv.min_vm_pu.round(3))),
          "line maxload", sorted(set(net.line.max_loading_percent)), "trafo maxload", net.trafo.max_loading_percent.tolist(),
          "n_sgen", len(net.sgen), "n_storage", len(net.storage), "stor MW", round(net.storage.sn_mva.sum(),3),
          "ext vm", net.ext_grid.vm_pu.tolist(), "vk %", t.vk_percent, "vkr", t.vkr_percent)
