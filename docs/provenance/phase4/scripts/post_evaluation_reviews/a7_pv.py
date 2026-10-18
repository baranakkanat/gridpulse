import numpy as np, pickle, os
from pathlib import Path
from gridpulse import dual_study as ds
avail = pickle.load(open(Path(os.path.dirname(__file__))/"avail.pkl","rb"))
for code,(pv,rating,load) in avail.items():
    tot = pv.sum(-1)/rating.sum()
    unit = (pv/rating).max(axis=(0,1))
    dev, ev = tot[35:182], tot[182:365]
    # noon (max per day) fraction quantiles
    print(code[5:-5], f"coincident peak frac dev {dev.max():.3f} eval {ev.max():.3f} | per-unit max {unit.min():.2f}-{unit.max():.2f} | 0.6/1.4={0.6/1.4:.2f} | days with coincident peak>0.4: dev {(dev.max(1)>0.4*1).sum()} eval {(ev.max(1)>0.4).sum()} | Jul-Sep {(tot[182:274].max(1)>0.4).sum()} Oct-Dec {(tot[274:365].max(1)>0.4).sum()}")
