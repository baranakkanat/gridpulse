"""Board audit pilot (counted solves): binding constraints and timing at the registered PV scale."""
import sys, time
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[3] / "src"))  # edited: was an absolute local path
import numpy as np
from gridpulse import dual_study as ds, grid, grid_study
SOLVES = 0
for code in ("1-LV-urban6--2-sw", "1-LV-rural3--2-sw"):
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    solver = grid.GridSolver(net)
    pv = np.asarray(arrays["sgen_p_mw"]); tot = pv.sum(axis=2)
    day, step = np.unravel_index(np.argmax(tot[150:200]), tot[150:200].shape); day += 150  # a June day, max PV step
    rows = []
    t0 = time.perf_counter()
    for t in range(step - 4, step + 6):
        m = solver.solve(arrays["load_p_mw"][day, t], arrays["load_q_mvar"][day, t], pv[day, t], np.zeros(len(net.storage)))
        SOLVES += 1
        rows.append(m)
    dt = (time.perf_counter() - t0) / 10
    rows = np.array(rows)
    cust_buses = sorted(set(net.load.bus) | set(net.sgen.bus))
    print(f"{code}: day {day} steps {step-4}..{step+5}  per-solve {dt*1000:.1f} ms  customer buses {len(cust_buses)}  "
          f"max margins [vmax, vmin, line, trafo] = {np.round(rows.max(axis=0), 4)}  total PV MW {tot[day, step]:.3f}  load MW {arrays['load_p_mw'][day, step].sum():.3f}")
print("board audit pilot solves:", SOLVES)
