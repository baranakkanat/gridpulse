import sys; sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np
from gridpulse import dual_study as ds
for code in ["1-LV-rural3--2-sw", "1-LV-semiurb5--2-sw", "1-LV-urban6--2-sw"]:
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    cust = sorted(set(net.load.bus) | set(net.sgen.bus))
    prof = net.sgen.profile.value_counts().to_dict()
    print(code, "customer buses", len(cust), "pv units", len(net.sgen), "pv buses", net.sgen.bus.nunique(), "profiles", prof, "storage", len(net.storage), "lines", len(net.line))
