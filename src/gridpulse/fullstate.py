"""Phase 5 physics: full AC states for virtual sensors (docs/phase5_protocol.md).

The Phase 4 cache keeps only the worst normalised margin of each constraint type. Sensors
need the state at their own location, so this stage re-solves the *realised* injections of
every decision day, under the nominal model and the truth variants studied in Phase 5, at
every cap level, and keeps:

- `vm` (96 x levels x LV buses): bus voltage magnitude, p.u.;
- `line` (96 x levels x lines): line loading, % of `max_i_ka`;
- `trafo` (96 x levels x 4): transformer LV-side active and reactive power (MW, MVAr;
  pandapower's branch convention, positive = flowing from the LV busbar into the
  transformer, so positive under PV reverse flow), loading (%) and LV busbar voltage
  (p.u.);
- `margins` (96 x levels x 4): the Phase 4 margins of the same flows, for validation.

Solver, variants, storage schedules and injection sets are Phase 4's (`dual_study`), so the
margins here must equal the Phase 4 cache bit for bit. These arrays are *ground truth*:
only the evaluator and the measurement simulator (`sensing`) may read them.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import grid, grid_study
from gridpulse.grid_study import CAP_LEVELS, STEPS

TRUTHS = ("nominal", "tap_raise_lv", "mv_high", "pv_fixed_095")
TRAFO_FIELDS = ("p_lv_mw", "q_lv_mvar", "loading_percent", "vm_lv_pu")


def lv_buses(net) -> np.ndarray:
    """Bus indices of the LV network (every bus except the slack's MV bus), sorted."""
    return np.array(sorted(set(net.bus.index) - set(net.ext_grid["bus"])))


def _state(net, buses: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = net.res_trafo
    trafo = np.array(
        [t["p_lv_mw"].iloc[0], t["q_lv_mvar"].iloc[0], t["loading_percent"].iloc[0],
         t["vm_lv_pu"].iloc[0]]
    )  # fmt: skip
    return (
        net.res_bus.loc[buses, "vm_pu"].to_numpy(),
        net.res_line["loading_percent"].to_numpy(),
        trafo,
    )


def day_states(solver: ds.VariantSolver, sets: dict, storage_mw: np.ndarray, buses) -> dict:
    """Full states of the realised set (set 0) of one day at every cap level. A cap that
    does not bind reproduces the uncapped flow (as in Phase 4); a failed flow is NaN."""
    solver.reset()
    rating = solver.pv_rating_mw
    levels = len(CAP_LEVELS)
    n_bus, n_line = len(buses), len(solver.net.line)
    out = {
        "vm": np.full((STEPS, levels, n_bus), np.nan, dtype=np.float32),
        "line": np.full((STEPS, levels, n_line), np.nan, dtype=np.float32),
        "trafo": np.full((STEPS, levels, len(TRAFO_FIELDS)), np.nan, dtype=np.float32),
        "margins": np.full((STEPS, levels, len(grid.MARGINS)), np.nan, dtype=np.float32),
    }

    def solve(t: int, level: int, pv: np.ndarray) -> None:
        load_p, load_q = sets["load_p_mw"][0, t], sets["load_q_mvar"][0, t]
        margins = solver.solve(load_p, load_q, pv, storage_mw[0, t])
        out["margins"][t, level] = margins
        if not np.isnan(margins).any():
            out["vm"][t, level], out["line"][t, level], out["trafo"][t, level] = _state(
                solver.net, buses
            )

    for t in range(STEPS):
        available = sets["sgen_p_mw"][0, t]
        solve(t, 0, available)
        for level, cap in enumerate(CAP_LEVELS[1:], start=1):
            if np.all(available <= cap * rating):
                for key in out:
                    out[key][t, level] = out[key][t, 0]
            else:
                solve(t, level, grid.cap_pv(available, rating, cap))
    return out


_WORKER: dict = {}


def _init_worker(code: str, variant: ds.ModelVariant, pv_scale: float) -> None:
    net = ds.variant_network(code, variant, pv_scale)
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    _WORKER.clear()
    _WORKER.update(
        solver=ds.VariantSolver(net, variant),
        arrays=arrays,
        storage=ds.storage_schedule(net, variant, len(arrays["sgen_p_mw"])),
        buses=lv_buses(net),
    )


def _compute(day: int) -> tuple[int, dict]:
    w = _WORKER
    sets = ds.day_sets(w["arrays"], day, w["solver"].pv_rating_mw, 1)
    storage = ds.day_storage(w["storage"], day, 1)
    return day, day_states(w["solver"], sets, storage, w["buses"])


def fingerprint() -> str:
    """Phase 4 physics fingerprint plus the source of this stage and its settings."""
    sources = [
        inspect.getsource(obj) for obj in (lv_buses, _state, day_states, _init_worker, _compute)
    ]
    settings = [TRAFO_FIELDS, repr(CAP_LEVELS.tolist()), STEPS]
    return hashlib.sha256(repr((ds.physics_fingerprint(), sources, settings)).encode()).hexdigest()


def compute_states(
    code: str, truth: str, days, cache_dir: Path, workers: int | None = None
) -> dict:
    """Compute missing days of one network and truth into cache_dir/<network>/<truth>/
    (atomic writes; a manifest records the fingerprint, PV scale and variant)."""
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    variant = ds.NOMINAL if truth == "nominal" else ds.VARIANTS[truth]
    folder = cache_dir / code / truth
    folder.mkdir(parents=True, exist_ok=True)
    expected = {
        "fingerprint": fingerprint(),
        "network": code,
        "pv_scale": ds.pv_scale(code),
        "variant": asdict(variant),
    }
    manifest = folder / "manifest.json"
    if manifest.exists():
        if json.loads(manifest.read_text()) != expected:
            raise ValueError(f"{folder} was produced by different physics; delete it")
    elif any(folder.glob("day_*.npz")):
        raise ValueError(f"{folder} has cached days but no manifest; delete it")
    else:
        manifest.write_text(json.dumps(expected) + "\n")
    missing = [d for d in days if not (folder / f"day_{d:03d}.npz").exists()]
    if missing:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_init_worker,
            initargs=(code, variant, ds.pv_scale(code)),
        ) as pool:
            for day, state in pool.map(_compute, missing, chunksize=1):
                path = folder / f"day_{day:03d}.npz"
                temporary = path.with_name(path.stem + ".partial.npz")
                np.savez_compressed(temporary, **state)
                temporary.replace(path)
    return {
        "fingerprint": expected["fingerprint"],
        "computed": len(missing),
        "from_cache": len(days) - len(missing),
    }


def load_states(cache_dir: Path, code: str, truth: str, days) -> dict[int, dict]:
    """Cached states of one network and truth, refused unless the manifest matches."""
    variant = ds.NOMINAL if truth == "nominal" else ds.VARIANTS[truth]
    folder = cache_dir / code / truth
    expected = {
        "fingerprint": fingerprint(),
        "network": code,
        "pv_scale": ds.pv_scale(code),
        "variant": asdict(variant),
    }
    manifest = folder / "manifest.json"
    if not manifest.exists() or json.loads(manifest.read_text()) != expected:
        raise ValueError(f"{folder} does not match the current physics; recompute it")
    states = {}
    for day in days:
        with np.load(folder / f"day_{day:03d}.npz") as data:
            states[day] = {key: data[key] for key in data.files}
    return states
