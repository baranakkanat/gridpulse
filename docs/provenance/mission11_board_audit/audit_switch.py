import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
from gridpulse import dual_study as ds
for code in ["1-LV-rural3--2-sw", "1-LV-urban6--2-sw", "1-LV-semiurb4--2-sw"]:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    sw = net.switch
    print(code, "lines", len(net.line), "in_service", int(net.line.in_service.sum()), "switches", len(sw),
          "open", int((~sw.closed).sum()), "et", sw.et.value_counts().to_dict(), "open et", sw[~sw.closed].et.value_counts().to_dict())
    print("  trafo sn_mva", net.trafo.sn_mva.tolist(), "line parallel>1:", int((net.line.parallel>1).sum()), "sgen", len(net.sgen), "loads", len(net.load))
