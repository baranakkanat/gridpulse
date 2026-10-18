"""Smoke test: realised physics of one development peak day for every network x variant."""
import time, numpy as np
from multiprocessing import Pool
from gridpulse import dual_study as ds, grid_study as gs
from gridpulse.grid import absolute_profiles
DAY = 150  # 2016-05-30 (development half)
def one(code):
    out = []
    for name, variant in [("nominal", ds.NOMINAL), *ds.VARIANTS.items()]:
        t = time.perf_counter()
        net = ds.variant_network(code, variant, ds.pv_scale(code))
        arrays = gs.daily_arrays(absolute_profiles(net))
        solver = ds.VariantSolver(net, variant)
        storage = ds.storage_schedule(net, variant, len(arrays["sgen_p_mw"]))
        sets = ds.day_sets(arrays, DAY, solver.pv_rating_mw, 2)
        m = ds.day_margins(solver, sets, ds.day_storage(storage, DAY, 2))
        n = ds.normalised(m)[0]
        out.append((code, name, int((n[:, 0] > 0).sum()), int(np.isinf(n).sum()), float(n[:, 0].max()),
                    int(ds.first_safe(n).max()), round(time.perf_counter() - t, 1)))
    return out
if __name__ == "__main__":
    with Pool(6) as pool:
        for rows in pool.map(one, list(ds.HOSTING_CAPACITY)):
            for r in rows:
                print(f"{r[0]:22s} {r[1]:16s} no-action viol {r[2]:3d} nonconv {r[3]} peak margin {r[4]:+.3f} deepest oracle level {r[5]} ({r[6]} s)")
