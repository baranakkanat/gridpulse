import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
from gridpulse import dual_study as ds
for code in ["1-LV-rural3--2-sw", "1-LV-urban6--2-sw"]:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    print(code, "storage", len(net.storage), net.storage.p_mw.sum(), "trafo maxload", net.trafo.max_loading_percent.tolist(),
          "line maxload uniq", sorted(set(net.line.max_loading_percent.round(1))), "vmax uniq", sorted(set(net.bus.max_vm_pu.round(3))))
