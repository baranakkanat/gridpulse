"""Phase 8 physics (docs/phase8_protocol.md s. 6): full AC states for the stress truths and
for the operator's nominal model at erroneous metered injections.

- Stress truths (decision days): `tap_lower_lv` (a Phase 4 variant, computed by
  `fullstate.compute_states` itself, so its margins must equal the Phase 4 cache);
  `mv_daily` (MV voltage rising with the network's PV output); `line_local` (one cable
  installed one cross-section smaller than recorded).
- Metered-injection conditions (all plan days 7-364): the operator's nominal model re-solved
  at the injections it would have recorded (`I1`-`I4`). Their `margins` are the replayed
  plan, their states the residual reference; nothing about the true grid changes.

The Phase 4 solver and the Phase 5 state layout are reused unchanged. This module writes
only to its own cache folders, each with a manifest, and never to the Phase 4/5 caches.
These arrays are ground truth or operator data as labelled; the decision code reads the
metered ones only through the planning model.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import fullstate, grid, grid_study
from gridpulse import sensing as sn
from gridpulse.grid_study import CAP_LEVELS, STEPS

TRUTHS = ("tap_lower_lv", "mv_daily", "line_local")
METERED = ("I1_meter_noise", "I2_load_q", "I3_pv_over", "I4_missing")
MV_SWING_PU = 0.03  # nominal slack + 0.03 at full PV output = SimBench's high-PV case
LINE_R_FACTOR, LINE_RATING_FACTOR = 1.5, 0.8  # one cross-section smaller (stylised)
METER_SIGMA = 0.02  # relative, per element and quarter-hour (I1)
ASSUMED_LOAD_COSPHI = 0.95  # inductive, when load Q is not metered (I2)
PV_RECORD_FACTOR = 1.05  # PV generation recorded 5 % high (I3)
MISSING_P, FALLBACK_DAYS = 0.10, 7  # missing elements per day; fallback a week earlier (I4)
PROFILE_NAMES = ("load_p_mw", "load_q_mvar", "sgen_p_mw")


def local_line(net, layout: sn.Layout) -> int:
    """`line_local`'s cable: the line that is not a feeder head with the largest downstream
    installed PV x resistance (the largest PV-driven voltage rise across one section)."""
    import networkx as nx

    graph = nx.Graph()
    for index, row in net.line.iterrows():
        graph.add_edge(int(row.from_bus), int(row.to_bus), line=int(index))
    tree = nx.bfs_tree(graph, layout.lv_busbar)
    pv = net.sgen.groupby("bus")["sn_mva"].sum()
    best, chosen = -1.0, None
    for upstream, downstream in tree.edges():
        line = graph.edges[upstream, downstream]["line"]
        if line in layout.feeder_heads:
            continue
        below = nx.descendants(tree, downstream) | {downstream}
        resistance = net.line.at[line, "r_ohm_per_km"] * net.line.at[line, "length_km"]
        score = float(sum(pv.get(b, 0.0) for b in below)) * float(resistance)
        if score > best:
            best, chosen = score, line
    if chosen is None:
        raise ValueError("no line besides the feeder heads")
    return chosen


def stress_network(code: str, condition: str):
    """The grid of one stress truth or metered condition (the nominal model except for
    `line_local`'s cable)."""
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    if condition == "line_local":
        line = local_line(net, sn.network_layout(net))
        net.line.at[line, "r_ohm_per_km"] *= LINE_R_FACTOR
        net.line.at[line, "max_i_ka"] *= LINE_RATING_FACTOR
    return net


def mv_profile(available: np.ndarray, rating: np.ndarray, base: float) -> np.ndarray:
    """`mv_daily` slack voltage per quarter-hour: base + 0.03 x (available PV / rating)."""
    share = np.asarray(available).sum(axis=-1) / float(np.sum(rating))
    return base + MV_SWING_PU * np.clip(share, 0.0, 1.0)


def _rng(code: str, condition: str, day: int, name: str) -> np.random.Generator:
    parts = [sn._stable_int(code), sn._stable_int(condition), int(day), sn._stable_int(name)]
    return np.random.default_rng(np.random.SeedSequence(parts))


def metered_sets(sets: dict, arrays: dict, code: str, condition: str, day: int) -> dict:
    """The realised injection set of one day as the operator would have recorded it."""
    out = {name: np.array(values, dtype=float) for name, values in sets.items()}
    if condition == "I1_meter_noise":
        for name in PROFILE_NAMES:
            noise = _rng(code, condition, day, name).standard_normal(out[name].shape)
            out[name] = out[name] * (1.0 + METER_SIGMA * noise)
    elif condition == "I2_load_q":
        out["load_q_mvar"] = out["load_p_mw"] * np.tan(np.arccos(ASSUMED_LOAD_COSPHI))
    elif condition == "I3_pv_over":
        out["sgen_p_mw"] = out["sgen_p_mw"] * PV_RECORD_FACTOR
    elif condition == "I4_missing":
        if day >= 2 * FALLBACK_DAYS:
            for kind, names in (("load", ("load_p_mw", "load_q_mvar")), ("sgen", ("sgen_p_mw",))):
                n = out[names[0]].shape[-1]
                missing = _rng(code, condition, day, kind).random(n) < MISSING_P
                for name in names:
                    out[name][..., missing] = np.asarray(arrays[name][day - FALLBACK_DAYS])[
                        ..., missing
                    ]
    else:
        raise ValueError(f"unknown metered condition {condition!r}")
    return out


def day_states(solver, sets: dict, storage_mw: np.ndarray, buses, slack=None) -> dict:
    """`fullstate.day_states` with an optional slack voltage per quarter-hour (`mv_daily`);
    the flow restarts from scratch whenever the slack voltage changes."""
    if slack is None:
        return fullstate.day_states(solver, sets, storage_mw, buses)
    solver.reset()
    rating = solver.pv_rating_mw
    levels = len(CAP_LEVELS)
    n_bus, n_line = len(buses), len(solver.net.line)
    out = {
        "vm": np.full((STEPS, levels, n_bus), np.nan, dtype=np.float32),
        "line": np.full((STEPS, levels, n_line), np.nan, dtype=np.float32),
        "trafo": np.full((STEPS, levels, len(fullstate.TRAFO_FIELDS)), np.nan, dtype=np.float32),
        "margins": np.full((STEPS, levels, len(grid.MARGINS)), np.nan, dtype=np.float32),
    }

    def solve(t: int, level: int, pv: np.ndarray) -> None:
        load_p, load_q = sets["load_p_mw"][0, t], sets["load_q_mvar"][0, t]
        margins = solver.solve(load_p, load_q, pv, storage_mw[0, t])
        out["margins"][t, level] = margins
        if not np.isnan(margins).any():
            out["vm"][t, level], out["line"][t, level], out["trafo"][t, level] = fullstate._state(
                solver.net, buses
            )

    for t in range(STEPS):
        solver.net.ext_grid["vm_pu"] = float(slack[t])
        solver.reset()
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


def _init_worker(code: str, condition: str) -> None:
    net = stress_network(code, condition)
    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    _WORKER.clear()
    _WORKER.update(
        code=code, condition=condition, solver=ds.VariantSolver(net, ds.NOMINAL),
        arrays=arrays, storage=ds.storage_schedule(net, ds.NOMINAL, len(arrays["sgen_p_mw"])),
        buses=fullstate.lv_buses(net), base=float(net.ext_grid["vm_pu"].iloc[0]),
    )  # fmt: skip


def _compute(day: int) -> tuple[int, dict]:
    w = _WORKER
    rating = w["solver"].pv_rating_mw
    sets = ds.day_sets(w["arrays"], day, rating, 1)
    storage = ds.day_storage(w["storage"], day, 1)
    slack = None
    if w["condition"] in METERED:
        sets = metered_sets(sets, w["arrays"], w["code"], w["condition"], day)
    elif w["condition"] == "mv_daily":
        slack = mv_profile(w["arrays"]["sgen_p_mw"][day], rating, w["base"])
    return day, day_states(w["solver"], sets, storage, w["buses"], slack)


def fingerprint() -> str:
    """Phase 5 full-state fingerprint plus this module's physics and settings."""
    sources = [
        inspect.getsource(obj)
        for obj in (local_line, stress_network, mv_profile, _rng, metered_sets, day_states,
                    _init_worker, _compute)
    ]  # fmt: skip
    settings = [MV_SWING_PU, LINE_R_FACTOR, LINE_RATING_FACTOR, METER_SIGMA, ASSUMED_LOAD_COSPHI,
                PV_RECORD_FACTOR, MISSING_P, FALLBACK_DAYS]  # fmt: skip
    return hashlib.sha256(repr((fullstate.fingerprint(), sources, settings)).encode()).hexdigest()


def days_of(condition: str) -> list[int]:
    """Truths: the decision days. Metered conditions: every plan day (the replay window)."""
    if condition in METERED:
        return [d for d, _ in ds.physics_tasks()["nominal"]]
    return list(range(grid_study.FIRST_DECISION_DAY, ds.LAST_DAY + 1))


def _expected(code: str, condition: str) -> dict:
    return {"fingerprint": fingerprint(), "network": code, "pv_scale": ds.pv_scale(code),
            "condition": condition}  # fmt: skip


def compute(code: str, condition: str, cache_dir: Path, workers: int = 3) -> dict:
    """Compute missing days of one network and condition (atomic writes, manifest)."""
    days = days_of(condition)
    if condition == "tap_lower_lv":
        return fullstate.compute_states(code, condition, days, cache_dir, workers)
    if condition not in TRUTHS + METERED:
        raise ValueError(f"unknown condition {condition!r}")
    folder = Path(cache_dir) / code / condition
    folder.mkdir(parents=True, exist_ok=True)
    expected, manifest = _expected(code, condition), folder / "manifest.json"
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
            max_workers=max(1, min(workers, os.cpu_count() or 1)),
            initializer=_init_worker, initargs=(code, condition),
        ) as pool:  # fmt: skip
            for day, state in pool.map(_compute, missing, chunksize=1):
                path = folder / f"day_{day:03d}.npz"
                temporary = path.with_name(path.stem + ".partial.npz")
                np.savez_compressed(temporary, **state)
                temporary.replace(path)
    return {"fingerprint": expected["fingerprint"], "computed": len(missing),
            "from_cache": len(days) - len(missing)}  # fmt: skip


def load(cache_dir: Path, code: str, condition: str, days=None) -> dict[int, dict]:
    """Cached states of one network and condition, refused unless the manifest matches."""
    days = days_of(condition) if days is None else days
    if condition == "tap_lower_lv":
        return fullstate.load_states(Path(cache_dir), code, condition, days)
    folder = Path(cache_dir) / code / condition
    manifest = folder / "manifest.json"
    if not manifest.exists() or json.loads(manifest.read_text()) != _expected(code, condition):
        raise ValueError(f"{folder}: missing or stale manifest")
    out = {}
    for day in days:
        with np.load(folder / f"day_{day:03d}.npz") as data:
            out[day] = {key: data[key] for key in data.files}
    return out
