import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
from gridpulse import dual_study as ds
for code in ["1-LV-rural3--2-sw", "1-LV-semiurb5--2-sw", "1-LV-urban6--2-sw"]:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    lb, pb = set(net.load.bus), set(net.sgen.bus)
    lv = net.bus.index[net.bus.vn_kv < 1]
    cust = sorted(lb | pb)
    print(code, "load buses", len(lb), "pv buses", len(pb), "pv not on load bus", len(pb - lb), "storage buses not cust", len(set(net.storage.bus) - set(cust)),
          "LV buses", len(lv), "max_vm cust min/max", net.bus.max_vm_pu[cust].min(), net.bus.max_vm_pu[cust].max(),
          "max_vm LV min", net.bus.max_vm_pu[lv].min(), "min_vm cust", net.bus.min_vm_pu[cust].min(), "trafo lv bus in cust", int(net.trafo.lv_bus.iloc[0]) in cust)
