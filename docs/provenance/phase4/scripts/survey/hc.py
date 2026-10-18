import json, sys, time
from multiprocessing import Pool
def run(code):
    from gridpulse.dual_study import hosting_capacity
    t = time.perf_counter(); r = hosting_capacity(code, range(0, 182)); r["seconds"] = time.perf_counter() - t
    return r
if __name__ == "__main__":
    codes = [f"1-LV-{n}--2-sw" for n in ("rural1", "rural2", "rural3", "semiurb4", "semiurb5", "urban6")]
    with Pool(6) as pool:
        out = pool.map(run, codes, chunksize=1)
    json.dump(out, open(sys.argv[1], "w"), indent=1); print(json.dumps(out, indent=1))
