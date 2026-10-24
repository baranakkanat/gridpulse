"""Phase 9 sweep engine, driver and reproduction gate, implemented exactly as registered in
`docs/provenance/phase9/phase9_registration.md` (sha256
737a252dab231b9c5303d4b5e8ad1af0adb93051f0de621d41a38f82af5bc4e1).

This module owns the *power-flow* side of Phase 9 only (registration s. 4, s. 6, s. 7 and the
Stage G gate of s. 11). Every statistic of s. 8-s. 10 belongs to `phase9_analysis.py`, which is
not part of this module.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 nice -n 19 .venv/bin/python analysis/phase9/phase9_sweep.py plan
    PYTHONDONTWRITEBYTECODE=1 nice -n 19 .venv/bin/python analysis/phase9/phase9_sweep.py gate
    PYTHONDONTWRITEBYTECODE=1 nice -n 19 .venv/bin/python analysis/phase9/phase9_sweep.py \
        sweep --stage w6 --max-runs 8 --time-budget-seconds 1080 --workers 3
    PYTHONDONTWRITEBYTECODE=1 nice -n 19 .venv/bin/python analysis/phase9/phase9_sweep.py manifest

Nothing outside `analysis/phase9/` is written, `src/gridpulse/` is unchanged, and the four
held-out networks of registration s. 2 are never named, loaded or reduced here.

Subcommands
-----------
`plan`      lists the 99 expected runs and the status of each. It computes no power flow.
`gate`      Stage G (s. 11) at the two registered cables, through the s. 6 engine with three
            workers, so it is also the smoke test of the process pool. On PASS or WARN its two
            reductions are kept as those cables' W6 artefacts, at no extra flows.
`sweep`     Stage 2 (s. 6-s. 7). It refuses to start unless this file's registration is
            tracked, committed and unmodified (s. 12 Stage 0), using read-only `git log` and
            `git diff --quiet`.
`manifest`  derives `sweep/manifest.json` by scanning the artefact tree and re-verifying both
            keys of every artefact. It is never maintained incrementally (s. 7).

Three reading decisions, all recorded in the artefacts and in the gate file
--------------------------------------------------------------------------
1. s. 7 lists "the nominal-leg `manifest.json` text" in `physics_key`, while the artefact path
   puts the network *below* `physics_key[:16]`. The key must therefore be network-independent,
   so it hashes the nominal-leg manifest text of *both* sweep networks, in scope order.
2. "the text of the reduction definition" is the fixed `REDUCTION_TEXT` constant below, not the
   source of the reduction functions: a cosmetic edit must not invalidate 99 computed runs.
3. s. 7 words the two NaN counters differently: `failed_truth` counts *failed truth flows*
   (steps whose reproduced leg is non-finite), and `nan_nominal` counts *non-finite nominal
   entries* (day x bus cells), as written.

A step is valid (s. 5) iff both legs are finite at that step; a failed flow is an all-NaN row,
exactly as in `fullstate.day_states`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from q1_voltage_residual import _plain as plain
from q1_voltage_residual import json_text, write_new_json

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SWEEP = HERE / "sweep"
RESULTS = HERE / "results"
GATE_FILE = RESULTS / "phase9_gate.json"
MANIFEST_FILE = SWEEP / "manifest.json"
Q1_INPUTS = RESULTS / "registration_inputs.json"

REGISTRATION = "docs/provenance/phase9/phase9_registration.md"
REGISTRATION_SHA256 = "737a252dab231b9c5303d4b5e8ad1af0adb93051f0de621d41a38f82af5bc4e1"

NOMINAL_CACHE = REPO / "outputs/sense_study/fullstate_cache"
ROBUST_CACHE = REPO / "outputs/robust_study/fullstate_cache"

# --- registered constants (s. 2, s. 4, s. 7, s. 11) ----------------------------------------

NETWORKS = ("1-LV-semiurb4--2-sw", "1-LV-urban6--2-sw")  # s. 2 sweep networks
REGISTERED_CANDIDATES = {"1-LV-semiurb4--2-sw": 39, "1-LV-urban6--2-sw": 50}  # s. 3
REGISTERED_CABLE = {"1-LV-semiurb4--2-sw": 37, "1-LV-urban6--2-sw": 3}  # s. 4
REGISTERED_DOWNSTREAM = {  # s. 3.3, checked by Stage 1, recorded here for the gate's report
    "1-LV-semiurb4--2-sw": (39, 40),
    "1-LV-urban6--2-sw": (6, 9, 19, 20, 23, 25, 29, 32, 34, 40, 42, 43),
}
REGISTERED_RETAINED = {"1-LV-semiurb4--2-sw": 170, "1-LV-urban6--2-sw": 175}  # s. 7, Q1's counts

NOMINAL_TRUTH = "nominal"
CACHED_TRUTH = "line_local"
EVALUATION = "evaluation"
LEVEL = 0  # CAP_LEVELS[0] = 1.0, no cap (src/gridpulse/grid_study.py:42)
STEPS = 96
SCHEMA_VERSION = 1

W6_R_FACTOR = 1.5  # stress.LINE_R_FACTOR
RATING_FACTOR = 0.8  # stress.LINE_RATING_FACTOR
W8_R_FACTORS = (1.1, 1.25, 2.0)  # s. 4; f = 1.5 is the W6 artefact and is not recomputed
W9_L_FACTORS = (1.25, 1.5)  # s. 4
EXPECTED_RUNS = {"W6": 89, "W8": 6, "W9": 4}  # s. 7 completeness barrier: 99 runs

PASS_LIMIT, WARN_LIMIT = 1e-6, 1e-5  # s. 11.4, in p.u.
DEFAULT_WORKERS = 3  # s. 6
DEFAULT_RUN_ESTIMATE_SECONDS = 120.0  # only until the first run of an invocation has finished

LINE_FIELDS = ("r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "length_km", "max_i_ka")  # s. 11.1

REDUCTION_TEXT = (
    "Delta(e, d, t, b) = vm_truth(e; d, t, level 0, b) - vm_nominal(d, t, level 0, b). "
    "A step is valid iff every entry of both legs is finite at that step; a failed flow is an "
    "all-NaN row. Daylight is network-wide: available[d].sum(axis=1) > 0, with available = "
    "grid_study.daily_arrays(grid.absolute_profiles(net))['sgen_p_mw']. Per scored day and LV "
    "bus, dmean_daylight is the mean of Delta over the valid daylight steps of that day (NaN if "
    "there are none) and dmean_night the same over the valid night steps. Means accumulate in "
    "float64 and are cast to float32 on write. Counters per day: n_daylight_valid, "
    "n_night_valid, n_daylight_steps, n_night_steps, failed_truth (steps whose truth leg is "
    "non-finite) and nan_nominal (non-finite nominal day x bus entries). Rows cover every "
    "scored day in order; retention is not applied here."
)

ARRAY_SPEC = {
    "dmean_daylight": ("float32", "days_buses"),
    "dmean_night": ("float32", "days_buses"),
    "n_daylight_valid": ("int16", "days"),
    "n_night_valid": ("int16", "days"),
    "n_daylight_steps": ("int16", "days"),
    "n_night_steps": ("int16", "days"),
    "failed_truth": ("int16", "days"),
    "nan_nominal": ("int16", "days"),
    "day_index": ("int32", "days"),
    "bus_index": ("int32", "buses"),
}
KEY_FIELDS = ("physics_key", "spec_key")


# --- run specifications --------------------------------------------------------------------


@dataclass(frozen=True)
class RunSpec:
    """One error of s. 4: a network, a line, an error type and its factors."""

    network: str
    line: int
    error: str  # "E-R" or "E-L"
    factor: float
    rating_factor: float
    work_item: str  # "W6", "W8" or "W9"

    def __post_init__(self) -> None:
        if self.error not in ("E-R", "E-L"):
            raise ValueError(f"unknown error type {self.error!r}")
        if self.error == "E-L" and self.rating_factor != 1.0:
            raise ValueError("E-L leaves max_i_ka unchanged, so its rating factor is 1.0")
        if self.factor <= 0:
            raise ValueError(f"the factor must be positive, got {self.factor}")

    @property
    def spec(self) -> dict:
        """The s. 7 `spec_key` inputs: network, line index, error type, factor, rating factor."""
        return {
            "network": self.network,
            "line": int(self.line),
            "error": self.error,
            "factor": float(self.factor),
            "rating_factor": float(self.rating_factor),
        }

    @property
    def spec_key(self) -> str:
        return _sha256_json(self.spec)

    @property
    def stem(self) -> str:
        return f"{self.error}-{factor_text(self.factor)}-line{int(self.line)}"


def factor_text(factor: float) -> str:
    """The factor as it appears in an artefact's file name (1.5, 1.1, 1.25, 2)."""
    return f"{float(factor):g}"


def _sha256_json(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


# --- days, keys and paths ------------------------------------------------------------------


def scored_days() -> list[int]:
    """s. 2: `grid_study.period_days("evaluation")` intersected with the decision days."""
    from gridpulse import dual_study as ds
    from gridpulse import grid_study

    decision = range(grid_study.FIRST_DECISION_DAY, ds.LAST_DAY + 1)
    return [int(d) for d in grid_study.period_days(EVALUATION) if d in decision]


def physics_parts() -> dict:
    """The s. 7 `physics_key` inputs (see reading decisions 1 and 2 in the module docstring)."""
    import pandapower

    from gridpulse import fullstate
    from gridpulse import stress as st

    return {
        "stress_fingerprint": st.fingerprint(),
        "fullstate_fingerprint": fullstate.fingerprint(),
        "nominal_leg_manifests": {
            code: (NOMINAL_CACHE / code / NOMINAL_TRUTH / "manifest.json").read_text()
            for code in NETWORKS
        },
        "pandapower_version": pandapower.__version__,
        "numpy_version": np.__version__,
        "schema_version": SCHEMA_VERSION,
        "level": LEVEL,
        "steps": STEPS,
        "scored_days": scored_days(),
        "reduction_definition": REDUCTION_TEXT,
    }


def physics_key(parts: dict | None = None) -> str:
    return _sha256_json(physics_parts() if parts is None else parts)


def artefact_path(spec: RunSpec, key: str, root: Path = SWEEP) -> Path:
    """s. 7: `sweep/<physics_key[:16]>/<network>/<E-R|E-L>-<factor>-line<idx>.npz`."""
    return Path(root) / key[:16] / spec.network / f"{spec.stem}.npz"


def sidecar_path(path: Path) -> Path:
    return Path(path).with_suffix(".json")


# --- s. 4: the error networks --------------------------------------------------------------


def apply_error(net, error: str, factor: float, line: int, rating_factor: float) -> None:
    """Apply one s. 4 error to `net.line`, in place. Nothing else changes.

    E-R(f): `r_ohm_per_km` x f and `max_i_ka` x `rating_factor`. At f = 1.5 and 0.8 on the
    network's `local_line` this is exactly `stress.stress_network(code, "line_local")`.
    E-L(g): `length_km` x g. R and X scale together; per-km values and `max_i_ka` are unchanged.
    """
    line = int(line)
    if line not in net.line.index:
        raise ValueError(f"line {line} is not in the line table")
    if error == "E-R":
        net.line.at[line, "r_ohm_per_km"] *= float(factor)
        net.line.at[line, "max_i_ka"] *= float(rating_factor)
    elif error == "E-L":
        if rating_factor != 1.0:
            raise ValueError("E-L leaves max_i_ka unchanged, so its rating factor is 1.0")
        net.line.at[line, "length_km"] *= float(factor)
    else:
        raise ValueError(f"unknown error type {error!r}")


def error_network(spec: RunSpec):
    """s. 4: the error applied to a fresh nominal variant network."""
    from gridpulse import dual_study as ds

    net = ds.variant_network(spec.network, ds.NOMINAL, ds.pv_scale(spec.network))
    apply_error(net, spec.error, spec.factor, spec.line, spec.rating_factor)
    return net


def candidates(net, layout) -> list[int]:
    """s. 3: every index of `net.line.index` that is not a feeder head."""
    heads = set(int(i) for i in layout.feeder_heads)
    return [int(i) for i in net.line.index if int(i) not in heads]


def expected_specs() -> list[RunSpec]:
    """The 99 registered runs: W6 over every candidate, W8 and W9 at the registered cables."""
    from gridpulse import dual_study as ds
    from gridpulse import sensing as sn
    from gridpulse import stress as st

    out: list[RunSpec] = []
    for code in NETWORKS:
        net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
        layout = sn.network_layout(net)
        lines = candidates(net, layout)
        if len(lines) != REGISTERED_CANDIDATES[code]:
            raise RuntimeError(
                f"{code}: {len(lines)} candidate lines, the registration fixes "
                f"{REGISTERED_CANDIDATES[code]}"
            )
        cable = int(st.local_line(net, layout))
        if cable != REGISTERED_CABLE[code]:
            raise RuntimeError(
                f"{code}: stress.local_line is {cable}, the registration fixes "
                f"{REGISTERED_CABLE[code]}"
            )
        if cable not in lines:
            raise RuntimeError(f"{code}: the registered cable {cable} is not a candidate")
        out += [RunSpec(code, line, "E-R", W6_R_FACTOR, RATING_FACTOR, "W6") for line in lines]
        out += [RunSpec(code, cable, "E-R", f, RATING_FACTOR, "W8") for f in W8_R_FACTORS]
        out += [RunSpec(code, cable, "E-L", g, 1.0, "W9") for g in W9_L_FACTORS]
    counts = {item: sum(1 for s in out if s.work_item == item) for item in EXPECTED_RUNS}
    if counts != EXPECTED_RUNS:
        raise RuntimeError(f"planned {counts}, the registration fixes {EXPECTED_RUNS}")
    return out


# --- s. 6: the level-0 engine --------------------------------------------------------------


def level0_states(net, days):
    """`stress._init_worker` + `fullstate.day_states` at level 0 only.

    Yields `(day, vm)` with `vm` of shape (STEPS, LV buses), float64, and an all-NaN row for a
    failed flow. `solver.reset()` is called once per day, so the warm-start sequence is the
    level-0 subsequence of the cache's (s. 6, measured by the gate).

    Scope of the measured equivalence with the cache (s. 11): the Stage G gate runs this
    engine for **E-R(1.5) at the two registered cables only** -- semiurb4 line 37 and urban6
    line 3 -- because those are the only specs the frozen cache holds a truth leg for. E and
    E_C are therefore measured there and nowhere else; every other W6 cable, and all of W8 and
    W9, carry that result by inference, not by measurement.

    The two engine inputs that are *not* re-derived per error are independent of the line
    parameters by construction, so E-L(g) -- which changes `length_km`, and with it R and X --
    inherits the gate's result on the same footing as E-R(f), which changes `r_ohm_per_km`:
    - the daylight mask and the per-step injections come from `grid.absolute_profiles`
      (`src/gridpulse/grid.py:50-74`), which is SimBench's relative profiles times each
      element's rating on a 15-minute UTC clock. It reads `net.load`, `net.sgen`,
      `net.storage` and `net.profiles`, never `net.line`;
    - the nominal storage schedule comes from `ds.storage_schedule`
      (`src/gridpulse/dual_study.py:131-149`), and `ds.NOMINAL` has `storage = "idle"`, so the
      schedule is identically zero; even its non-idle branches read only the storage ratings
      and the same profiles.
    Both are functions of the injection tables and the storage table alone. Changing a line's
    `length_km`, `r_ohm_per_km` or `max_i_ka` cannot move either, so the gate's measured
    discrepancy bounds the same solver sequence for E-L(g) as for E-R(1.5). What the gate does
    *not* measure for E-L(g) is the Newton path itself at the altered X; that is the inference,
    and it is recorded as one.
    """
    from gridpulse import dual_study as ds
    from gridpulse import fullstate, grid, grid_study

    arrays = grid_study.daily_arrays(grid.absolute_profiles(net))
    solver = ds.VariantSolver(net, ds.NOMINAL)
    storage = ds.storage_schedule(net, ds.NOMINAL, len(arrays["sgen_p_mw"]))
    buses = fullstate.lv_buses(net)
    rating = solver.pv_rating_mw
    for day in days:
        sets = ds.day_sets(arrays, day, rating, 1)
        storage_d = ds.day_storage(storage, day, 1)
        solver.reset()
        vm = np.full((STEPS, len(buses)), np.nan, dtype=np.float64)
        for t in range(STEPS):
            margins = solver.solve(
                sets["load_p_mw"][0, t],
                sets["load_q_mvar"][0, t],
                sets["sgen_p_mw"][0, t],
                storage_d[0, t],
            )
            if not np.isnan(margins).any():
                vm[t] = solver.net.res_bus.loc[buses, "vm_pu"].to_numpy()
        yield int(day), vm


def daylight_masks(net, days) -> dict[int, np.ndarray]:
    """s. 2: the network-wide daylight mask, `available[d].sum(axis=1) > 0`.

    The mask is a function of `grid.absolute_profiles` (`src/gridpulse/grid.py:50-74`) only,
    which reads the SimBench profiles and the generator ratings and never `net.line`. It is
    therefore identical for the nominal network, for E-R(f) and for E-L(g), which is why
    `level0_states`' docstring can carry the gate's E-R(1.5) result -- measured at the two
    registered cables only (s. 11) -- over to E-L(g).
    """
    from gridpulse import grid, grid_study

    available = grid_study.daily_arrays(grid.absolute_profiles(net))["sgen_p_mw"]
    return {int(d): available[d].sum(axis=1) > 0 for d in days}


# --- s. 7: the per-day reduction -----------------------------------------------------------


def _masked_mean(delta: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return np.full(delta.shape[1], np.nan, dtype=np.float64)
    return delta[mask].mean(axis=0)


def reduce_day(vm_truth, vm_nominal, daylight) -> dict:
    """One scored day's reduction (`REDUCTION_TEXT`). Everything accumulates in float64."""
    truth = np.asarray(vm_truth, dtype=np.float64)
    nominal = np.asarray(vm_nominal, dtype=np.float64)
    mask = np.asarray(daylight, dtype=bool)
    if truth.ndim != 2 or nominal.shape != truth.shape:
        raise ValueError(f"the two legs differ in shape: {truth.shape} and {nominal.shape}")
    if mask.shape != (truth.shape[0],):
        raise ValueError(f"the daylight mask is {mask.shape}, expected {(truth.shape[0],)}")
    finite_truth = np.isfinite(truth).all(axis=1)
    finite_nominal = np.isfinite(nominal).all(axis=1)
    valid = finite_truth & finite_nominal
    delta = truth - nominal
    return {
        "dmean_daylight": _masked_mean(delta, valid & mask),
        "dmean_night": _masked_mean(delta, valid & ~mask),
        "n_daylight_valid": int((valid & mask).sum()),
        "n_night_valid": int((valid & ~mask).sum()),
        "n_daylight_steps": int(mask.sum()),
        "n_night_steps": int((~mask).sum()),
        "failed_truth": int((~finite_truth).sum()),
        "nan_nominal": int((~np.isfinite(nominal)).sum()),
    }


def build_arrays(rows: list[dict], days, buses) -> dict[str, np.ndarray]:
    """The s. 7 artefact arrays, cast on write: float32 means plus the int counters."""
    days = [int(d) for d in days]
    if len(rows) != len(days):
        raise ValueError(f"{len(rows)} reduced days for {len(days)} scored days")
    out = {
        "dmean_daylight": np.stack([r["dmean_daylight"] for r in rows]).astype(np.float32),
        "dmean_night": np.stack([r["dmean_night"] for r in rows]).astype(np.float32),
        "day_index": np.asarray(days, dtype=np.int32),
        "bus_index": np.asarray([int(b) for b in buses], dtype=np.int32),
    }
    for name in ("n_daylight_valid", "n_night_valid", "n_daylight_steps", "n_night_steps",
                 "failed_truth", "nan_nominal"):  # fmt: skip
        values = [int(r[name]) for r in rows]
        if any(v > np.iinfo(np.int16).max for v in values):
            raise ValueError(f"{name} overflows int16")
        out[name] = np.asarray(values, dtype=np.int16)
    return out


# --- s. 7: the artefact, written atomically and verified before it is trusted ---------------


def write_run(path: Path, arrays: dict[str, np.ndarray], sidecar: dict) -> None:
    """Write the `.npz` and its sidecar `.json` through temporary files in the same directory,
    then `os.replace` both.

    Each file individually lands whole or not at all: it is built in a temporary file in the
    same directory and published with one `os.replace`, and the `finally` clause removes any
    temporary a raising write left behind. No partial `.npz` and no partial `.json` can be
    observed.

    The *pair* is not atomic. The two `os.replace` calls are separate, so a crash or a kill
    between them leaves a published `.npz` whose sidecar is still missing. That window is
    real and is not closed here; `verify_run` refuses such an artefact ("the sidecar JSON is
    missing") and the driver then stops and requires explicit deletion, which is s. 7's
    convention. The consequence is a recompute of that one run, never a statistic computed
    from a half-written pair.

    Both keys are written into both files (s. 7); the `.npz` copies them from the sidecar, so
    the two can never disagree.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    stored = {**arrays, **{field: np.asarray(sidecar[field]) for field in KEY_FIELDS}}
    tmp_npz = path.with_name(path.stem + ".partial.npz")
    tmp_json = path.with_name(path.stem + ".partial.json")
    try:
        np.savez_compressed(tmp_npz, **stored)
        tmp_json.write_text(json_text(sidecar))
        os.replace(tmp_npz, path)
        os.replace(tmp_json, sidecar_path(path))
    finally:
        for temporary in (tmp_npz, tmp_json):
            if temporary.exists():
                temporary.unlink()


def _expect(condition: bool, path: Path, message: str) -> None:
    if not condition:
        raise RuntimeError(f"{path}: {message}; delete it and recompute")


def verify_run(path: Path, key: str, spec: RunSpec, n_days: int | None = None) -> dict:
    """Recompute both keys and accept an existing artefact only if they are equal (s. 7).

    Returns the sidecar on success. A malformed file, a missing sidecar or a key mismatch
    raises: the driver stops and requires explicit deletion, as `stress.py:219,221,247` does.
    """
    path = Path(path)
    sidecar = sidecar_path(path)
    _expect(sidecar.exists(), path, "the sidecar JSON is missing")
    try:
        payload = json.loads(sidecar.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f"{sidecar}: unreadable sidecar JSON; delete it and recompute")\
            from error  # fmt: skip
    try:
        with np.load(path) as data:
            present = set(data.files)
            _expect(
                present >= set(ARRAY_SPEC) | set(KEY_FIELDS),
                path,
                f"missing arrays {sorted((set(ARRAY_SPEC) | set(KEY_FIELDS)) - present)}",
            )
            stored = {field: str(data[field]) for field in KEY_FIELDS}
            days = int(data["day_index"].size)
            buses = int(data["bus_index"].size)
            for name, (dtype, shape) in ARRAY_SPEC.items():
                array = data[name]
                _expect(array.dtype == np.dtype(dtype), path, f"{name} has dtype {array.dtype}")
                want = {"days": (days,), "buses": (buses,), "days_buses": (days, buses)}[shape]
                _expect(array.shape == want, path, f"{name} has shape {array.shape}")
    except RuntimeError:
        raise
    except Exception as error:  # a truncated or non-npz file
        raise RuntimeError(f"{path}: unreadable npz ({error}); delete it and recompute") from error
    expected = {"physics_key": key, "spec_key": spec.spec_key}
    _expect(stored == expected, path, f"stored keys {stored} differ from the recomputed {expected}")
    _expect(
        {field: payload.get(field) for field in KEY_FIELDS} == expected,
        sidecar,
        f"the sidecar keys differ from the recomputed {expected}",
    )
    _expect(payload.get("spec") == spec.spec, sidecar, "the sidecar spec differs")
    if n_days is not None:
        _expect(days == n_days, path, f"{days} rows for {n_days} scored days")
    return payload


def _reported_path(path: Path) -> str:
    """Relative to `analysis/phase9/` when it lies there, absolute otherwise (tests)."""
    path = Path(path)
    return str(path.relative_to(HERE)) if path.is_relative_to(HERE) else str(path)


def run_status(spec: RunSpec, key: str, n_days: int | None = None, root: Path = SWEEP) -> dict:
    """`missing` or `verified` for one expected run. A bad artefact raises."""
    path = artefact_path(spec, key, root)
    if not path.exists():
        return {"status": "missing", "path": _reported_path(path), **spec.spec,
                "work_item": spec.work_item}  # fmt: skip
    sidecar = verify_run(path, key, spec, n_days)
    return {"status": "verified", "path": _reported_path(path), **spec.spec,
            "work_item": spec.work_item, "runtime_seconds": sidecar.get("runtime_seconds"),
            "workers": sidecar.get("workers"), "pool_worked": sidecar.get("pool_worked"),
            "failed_truth_total": sidecar.get("failed_truth_total")}  # fmt: skip


def sidecar_payload(spec: RunSpec, key: str, arrays: dict, extra: dict) -> dict:
    """The s. 7 sidecar: both keys, the spec and the run's accounting."""
    return {
        "physics_key": key,
        "spec_key": spec.spec_key,
        "spec": spec.spec,
        "work_item": spec.work_item,
        "schema_version": SCHEMA_VERSION,
        "level": LEVEL,
        "steps": STEPS,
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256},
        "days": int(arrays["day_index"].size),
        "buses": int(arrays["bus_index"].size),
        "failed_truth_total": int(arrays["failed_truth"].sum()),
        "nan_nominal_total": int(arrays["nan_nominal"].sum()),
        **extra,
    }


# --- s. 7: the derived manifest ------------------------------------------------------------


def derive_manifest(root: Path = SWEEP, key: str | None = None, specs=None, days=None) -> dict:
    """Rebuild the manifest by scanning the artefact tree and re-verifying both keys.

    It is never maintained incrementally (s. 7). Artefacts outside the current `physics_key`
    directory are listed as `other_physics_keys`, never silently accepted.
    """
    root = Path(root)
    key = physics_key() if key is None else key
    specs = expected_specs() if specs is None else list(specs)
    days = scored_days() if days is None else [int(d) for d in days]
    by_path = {artefact_path(s, key, root).resolve(): s for s in specs}
    entries, unexpected, other = [], [], {}
    for path in sorted(root.rglob("*.npz")):
        if path.name.endswith(".partial.npz"):
            raise RuntimeError(f"{path}: a partial artefact is present; delete it")
        resolved = path.resolve()
        folder = path.relative_to(root).parts[0]
        if folder != key[:16]:
            other.setdefault(folder, []).append(str(path.relative_to(root)))
            continue
        spec = by_path.get(resolved)
        if spec is None:
            unexpected.append(str(path.relative_to(root)))
            continue
        payload = verify_run(path, key, spec, len(days))
        entries.append({
            "path": str(path.relative_to(root)), **spec.spec, "work_item": spec.work_item,
            "spec_key": spec.spec_key, "runtime_seconds": payload.get("runtime_seconds"),
            "workers": payload.get("workers"), "pool_worked": payload.get("pool_worked"),
            "failed_truth_total": payload.get("failed_truth_total"),
            "nan_nominal_total": payload.get("nan_nominal_total"),
        })  # fmt: skip
    if unexpected:
        raise RuntimeError(
            f"{root}: artefacts that no registered run expects: {unexpected}; delete them"
        )
    present = {e["work_item"] for e in entries}
    counts = {item: sum(1 for e in entries if e["work_item"] == item) for item in EXPECTED_RUNS}
    return {
        "derived": "rebuilt by scanning and re-verifying; never maintained incrementally (s. 7)",
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256},
        "physics_key": key,
        "physics_key_prefix": key[:16],
        "schema_version": SCHEMA_VERSION,
        "scored_days": {"count": len(days), "first": days[0], "last": days[-1]},
        "expected_runs": EXPECTED_RUNS,
        "present_runs": counts,
        "complete": counts == EXPECTED_RUNS,
        "completeness_barrier": (
            "Stage 3 computes no coverage or rule statistic unless every expected artefact is "
            "present and verified (s. 7)"
        ),
        "work_items_present": sorted(present),
        "other_physics_keys": other,
        "runs": sorted(entries, key=lambda e: e["path"]),
    }


def write_manifest(root: Path = SWEEP, key: str | None = None, specs=None, days=None) -> dict:
    """Write the derived manifest atomically. Being derived, it is rewritten, not refused."""
    manifest = derive_manifest(root, key, specs, days)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / "manifest.json"
    temporary = target.with_name("manifest.partial.json")
    try:
        temporary.write_text(json_text(plain(manifest)))
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return manifest


# --- s. 12 Stage 0: the registration must be committed and unmodified ----------------------


def _git(args: list[str]) -> tuple[int, str]:
    """Read-only git only. Git is the owner's; nothing here mutates the repository."""
    result = subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=False
    )
    return result.returncode, result.stdout.strip()


def registration_state(git=_git, path: str = REGISTRATION) -> dict:
    """s. 12 Stage 0: the registration's commit and whether the working tree matches it.

    `git` is injected so the check is unit-testable without a repository. Both commands are
    read-only (`git log -1 --format=%H -- <path>` and `git diff --quiet HEAD -- <path>`).
    """
    code, commit = git(["log", "-1", "--format=%H", "--", path])
    committed = code == 0 and bool(commit)
    diff_code, _ = git(["diff", "--quiet", "HEAD", "--", path]) if committed else (0, "")
    unmodified = committed and diff_code == 0
    on_disk = REPO / path
    reasons = []
    if not committed:
        reasons.append(f"{path} is not tracked in any commit (`git log` returned no commit)")
    elif not unmodified:
        reasons.append(f"{path} differs from HEAD (`git diff --quiet HEAD` exited {diff_code})")
    return {
        "path": path,
        "commit": commit or None,
        "committed": committed,
        "unmodified": unmodified,
        "ok": committed and unmodified,
        "sha256": _sha256_file(on_disk) if on_disk.exists() else None,
        "expected_sha256": REGISTRATION_SHA256,
        "reasons": reasons,
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require_committed_registration(git=_git) -> dict:
    """Stage 2's gate. Stage G may run before the commit (s. 11); Stages 1-3 may not (s. 12)."""
    state = registration_state(git)
    if state["sha256"] != REGISTRATION_SHA256:
        raise RuntimeError(
            f"{REGISTRATION}: sha256 {state['sha256']} differs from the registered "
            f"{REGISTRATION_SHA256}; stopping"
        )
    if not state["ok"]:
        raise RuntimeError(
            "Stage 2 refuses to run: " + "; ".join(state["reasons"]) + ". Registration s. 12 "
            "Stage 0 requires the registration to be committed and unmodified before Stages "
            "1-3. The commit is the owner's."
        )
    return state


# --- the time budget ------------------------------------------------------------------------


def budget_allows(elapsed: float, budget: float | None, estimate: float) -> bool:
    """s. 7: no new run is started once the time budget would be exceeded."""
    if budget is None:
        return True
    return float(elapsed) + float(estimate) <= float(budget)


# --- the process pool, with the recorded one-worker fallback (s. 6) -------------------------


def _probe() -> int:
    return os.getpid()


def open_pool(workers: int) -> tuple[ProcessPoolExecutor | None, dict]:
    """A `ProcessPoolExecutor(max_workers=workers)` whose startup is verified by a probe task.

    If a process pool cannot run under the agent sandbox, the caller falls back to one
    in-process worker. The fallback is recorded and is not a deviation (s. 6).
    """
    if workers <= 1:
        return None, {"pool_worked": False, "workers": 1, "reason": "one worker was requested"}
    try:
        pool = ProcessPoolExecutor(max_workers=workers)
        pool.submit(_probe).result(timeout=120)
    except Exception as error:  # BrokenProcessPool, OSError, PermissionError, ...
        return None, {"pool_worked": False, "workers": 1,
                      "reason": f"the process pool could not start: {type(error).__name__}: "
                                f"{error}"}  # fmt: skip
    return pool, {"pool_worked": True, "workers": workers, "reason": None}


# --- Stage 2: one sweep run ----------------------------------------------------------------


def sweep_run(spec: RunSpec) -> dict:
    """One error's level-0 run and reduction (s. 6, s. 7). Runs in a pool worker."""
    from gridpulse import fullstate

    started = time.perf_counter()
    days = scored_days()
    net = error_network(spec)
    masks = daylight_masks(net, days)
    buses = fullstate.lv_buses(net)
    nominal = _nominal_leg(spec.network, days)
    rows = [
        reduce_day(vm, nominal[day], masks[day]) for day, vm in level0_states(net, days)
    ]
    arrays = build_arrays(rows, days, buses)
    return {
        "spec": spec,
        "arrays": arrays,
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "pid": os.getpid(),
    }


_NOMINAL: dict[str, np.ndarray] = {}


def _nominal_leg(code: str, days) -> dict[int, np.ndarray]:
    """s. 2: the read-only nominal leg at level 0, memoised per process."""
    from gridpulse import fullstate

    if code not in _NOMINAL:
        states = fullstate.load_states(NOMINAL_CACHE, code, NOMINAL_TRUTH, days)
        _NOMINAL[code] = {
            int(d): np.asarray(states[d]["vm"], dtype=np.float64)[:, LEVEL, :] for d in days
        }
    return _NOMINAL[code]


# --- Stage G: the reproduction gate (s. 11) ------------------------------------------------


def classify(value: float) -> str:
    """s. 11.4: PASS at or below 1e-6, WARN up to and including 1e-5, ABORT above it."""
    value = float(value)
    if not np.isfinite(value):
        return "ABORT"
    if value <= PASS_LIMIT:
        return "PASS"
    if value <= WARN_LIMIT:
        return "WARN"
    return "ABORT"


def worst_verdict(*verdicts: str) -> str:
    order = ("PASS", "WARN", "ABORT")
    return max(verdicts, key=order.index)


def gate_run(spec: RunSpec) -> dict:
    """One registered cable's gate run: the reduction plus the s. 11.2-11.3 comparison.

    Everything that needs a `vm` array stays in the worker; only the reduced arrays and the
    gate's scalars cross the process boundary.
    """
    from gridpulse import fullstate
    from gridpulse import stress as st

    started = time.perf_counter()
    days = scored_days()
    net = error_network(spec)
    masks = daylight_masks(net, days)
    buses = fullstate.lv_buses(net)
    nominal = _nominal_leg(spec.network, days)
    cached = st.load(ROBUST_CACHE, spec.network, CACHED_TRUTH, days)

    rows, discrepancy, retained, nan_pattern_differs = [], [], [], []
    e_max, e_argmax = 0.0, None
    for day, vm in level0_states(net, days):
        repro = vm.astype(np.float32)
        reference = np.asarray(cached[day]["vm"], dtype=np.float32)[:, LEVEL, :]
        if reference.shape != repro.shape:
            raise RuntimeError(f"{spec.network} day {day}: cached vm is {reference.shape}, "
                               f"the engine produced {repro.shape}")  # fmt: skip
        if not np.array_equal(np.isnan(repro), np.isnan(reference)):
            nan_pattern_differs.append(day)
        difference = repro.astype(np.float64) - reference.astype(np.float64)
        finite = np.isfinite(difference)
        if finite.any():
            local = float(np.abs(difference[finite]).max())
            if local > e_max:
                flat = np.argmax(np.where(finite, np.abs(difference), -1.0))
                e_max = local
                e_argmax = {"day": day, "step": int(flat // repro.shape[1]),
                            "bus": int(buses[flat % repro.shape[1]])}  # fmt: skip
        rows.append(reduce_day(vm, nominal[day], masks[day]))
        contrast = reduce_day(repro, reference, masks[day])
        discrepancy.append(contrast["dmean_daylight"] - contrast["dmean_night"])
        retained.append(masks[day].any() and (~masks[day]).any())

    retained = np.asarray(retained, dtype=bool)
    stack = np.stack(discrepancy)[retained]
    per_bus = np.nanmean(stack, axis=0) if stack.size else np.full(len(buses), np.nan)
    arrays = build_arrays(rows, days, buses)
    defined = np.isfinite(per_bus)
    e_c = float(np.abs(per_bus[defined]).max()) if defined.any() else float("nan")
    e_c_bus = int(buses[int(np.nanargmax(np.abs(per_bus)))]) if defined.any() else None
    return {
        "spec": spec,
        "arrays": arrays,
        "runtime_seconds": round(time.perf_counter() - started, 3),
        "pid": os.getpid(),
        "E": e_max,
        "E_argmax": e_argmax,
        "E_C": e_c,
        "E_C_argmax_bus": e_c_bus,
        "nan_pattern_identical": not nan_pattern_differs,
        "nan_pattern_differs_on_days": nan_pattern_differs,
        "retained_days": int(retained.sum()),
        "failed_truth_total": int(arrays["failed_truth"].sum()),
        "nan_nominal_total": int(arrays["nan_nominal"].sum()),
        "failed_truth_per_day": {
            int(d): int(n)
            for d, n in zip(arrays["day_index"], arrays["failed_truth"], strict=True)
            if n
        },
    }


def structural_checks(code: str) -> dict:
    """s. 11.1, exact and flow-free: the cable, the line table, the storage schedule and the
    three day lists against Q1's committed `registration_inputs.json`."""
    from gridpulse import dual_study as ds
    from gridpulse import grid, grid_study
    from gridpulse import sensing as sn
    from gridpulse import stress as st

    nominal = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    layout = sn.network_layout(nominal)
    # the engine's cable is the registered one; `stress.local_line` is derived independently
    spec = RunSpec(code, REGISTERED_CABLE[code], "E-R", W6_R_FACTOR, RATING_FACTOR, "W6")
    cable, local = int(spec.line), int(st.local_line(nominal, layout))
    engine = error_network(spec)
    reference = st.stress_network(code, CACHED_TRUTH)

    fields = list(LINE_FIELDS)
    line_table = bool(engine.line[fields].equals(reference.line[fields]))

    available = grid_study.daily_arrays(grid.absolute_profiles(nominal))["sgen_p_mw"]
    n_days = len(available)
    schedule_engine = ds.storage_schedule(engine, ds.NOMINAL, n_days)
    schedule_reference = ds.storage_schedule(nominal, ds.NOMINAL, n_days)
    storage = bool(np.array_equal(schedule_engine, schedule_reference))

    days = scored_days()
    counts = {int(d): int((available[d].sum(axis=1) > 0).sum()) for d in days}
    no_night = [d for d in days if counts[d] == STEPS]
    if no_night:
        raise RuntimeError(f"{code}: scored days with no night step {no_night}; s. 7 makes this "
                           "a hard error")  # fmt: skip
    with_daylight = [d for d in days if counts[d] > 0]
    without_daylight = [d for d in days if counts[d] == 0]
    q1 = json.loads(Q1_INPUTS.read_text())["networks"][code]["days"]
    day_lists = {
        "scored": days == [int(d) for d in q1["list"]],
        "with_daylight": with_daylight == [int(d) for d in q1["with_daylight"]],
        "without_daylight": without_daylight == [int(d) for d in q1["without_daylight"]],
    }

    return {
        "cable_equals_stress_local_line": {
            "engine_line": cable,
            "stress_local_line": local,
            "registered": REGISTERED_CABLE[code],
            "ok": cable == local == REGISTERED_CABLE[code],
        },
        "line_table_equals_stress_network": {"fields": fields, "ok": line_table},
        "storage_schedule_equals_nominal": {"shape": list(schedule_engine.shape), "ok": storage},
        "day_lists_equal_q1_registration_inputs": {
            **day_lists,
            "ok": all(day_lists.values()),
            "scored_days": len(days),
            "with_daylight": len(with_daylight),
            "without_daylight": without_daylight,
            "retained_days": len(with_daylight),
            "retained_registered": REGISTERED_RETAINED[code],
            "retained_matches_registration": len(with_daylight) == REGISTERED_RETAINED[code],
        },
        "downstream_registered": list(REGISTERED_DOWNSTREAM[code]),
        "ok": (
            cable == local == REGISTERED_CABLE[code]
            and line_table
            and storage
            and all(day_lists.values())
        ),
    }


def run_gate(workers: int = DEFAULT_WORKERS, root: Path = SWEEP,
             gate_file: Path = GATE_FILE) -> dict:  # fmt: skip
    """Stage G (s. 11), through the s. 6 engine and the process pool."""
    key = physics_key()
    days = scored_days()
    structural = {code: structural_checks(code) for code in NETWORKS}
    specs = [
        RunSpec(code, REGISTERED_CABLE[code], "E-R", W6_R_FACTOR, RATING_FACTOR, "W6")
        for code in NETWORKS
    ]
    for spec in specs:
        if not structural[spec.network]["ok"]:
            raise RuntimeError(f"{spec.network}: a s. 11.1 structural check failed; aborting "
                               "before any flow")  # fmt: skip

    started = time.perf_counter()
    pool, pool_info = open_pool(workers)
    try:
        if pool is None:
            results = [gate_run(spec) for spec in specs]
        else:
            futures = [pool.submit(gate_run, spec) for spec in specs]
            results = [future.result() for future in futures]
    finally:
        if pool is not None:
            pool.shutdown()
    wall = round(time.perf_counter() - started, 3)

    networks, verdicts = {}, []
    for result in results:
        spec = result["spec"]
        e_verdict, c_verdict = classify(result["E"]), classify(result["E_C"])
        verdict = worst_verdict(e_verdict, c_verdict)
        if not result["nan_pattern_identical"]:
            verdict = "ABORT"
        verdicts.append(verdict)
        networks[spec.network] = {
            "spec": spec.spec,
            "spec_key": spec.spec_key,
            "E": result["E"],
            "E_argmax": result["E_argmax"],
            "E_verdict": e_verdict,
            "E_C": result["E_C"],
            "E_C_argmax_bus": result["E_C_argmax_bus"],
            "E_C_verdict": c_verdict,
            "nan_pattern_identical": result["nan_pattern_identical"],
            "nan_pattern_differs_on_days": result["nan_pattern_differs_on_days"],
            "verdict": verdict,
            "structural": structural[spec.network],
            "retained_days": result["retained_days"],
            "failed_truth_total": result["failed_truth_total"],
            "failed_truth_per_day": result["failed_truth_per_day"],
            "nan_nominal_total": result["nan_nominal_total"],
            "runtime_seconds": result["runtime_seconds"],
            "worker_pid": result["pid"],
            "workers": pool_info["workers"],
            "pool_worked": pool_info["pool_worked"],
        }
    overall = worst_verdict(*verdicts)

    kept = []
    if overall in ("PASS", "WARN"):
        for result in results:
            spec = result["spec"]
            path = artefact_path(spec, key, root)
            extra = {
                "runtime_seconds": result["runtime_seconds"],
                "workers": pool_info["workers"],
                "pool_worked": pool_info["pool_worked"],
                "worker_pid": result["pid"],
                "source": "Stage G (s. 11.5): the gate's reduction kept as the W6 artefact",
                "gate": {"E": result["E"], "E_C": result["E_C"], "verdict": overall},
            }
            payload = sidecar_payload(spec, key, result["arrays"], extra)
            if path.exists():
                verify_run(path, key, spec, len(days))
                kept.append({"path": _reported_path(path), "written": False,
                             "note": "already present and verified"})  # fmt: skip
                continue
            write_run(path, result["arrays"], payload)
            kept.append({"path": _reported_path(path), "written": True})

    report = {
        "stage": "G (registration s. 11)",
        "registration": {
            "path": REGISTRATION,
            "sha256_on_disk": _sha256_file(REPO / REGISTRATION),
            "expected_sha256": REGISTRATION_SHA256,
            "state": registration_state(),
            "note": "Stage G may run before this file is committed (s. 11); it reproduces "
                    "frozen arrays and computes no Phase 9 statistic",
        },  # fmt: skip
        "physics_key": key,
        "physics_key_prefix": key[:16],
        "schema_version": SCHEMA_VERSION,
        "level": LEVEL,
        "tolerances_pu": {"PASS": f"<= {PASS_LIMIT:g}", "WARN": f"({PASS_LIMIT:g}, "
                          f"{WARN_LIMIT:g}]", "ABORT": f"> {WARN_LIMIT:g}"},  # fmt: skip
        "scored_days": {"count": len(days), "first": days[0], "last": days[-1]},
        "pool": {**pool_info, "requested_workers": workers, "runs": len(specs),
                 "wall_seconds": wall},  # fmt: skip
        "verdict": overall,
        "networks": networks,
        "artefacts_kept": kept,
        "consequence": (
            "On PASS or WARN the two reductions are this run's W6 artefacts, at no extra flows "
            "(s. 11.5). On ABORT no sweep statistic is computed and the board reports to the "
            "owner (s. 11.6)."
        )
        if overall != "ABORT"
        else (
            "ABORT (s. 11.6): no sweep statistic is computed, Phase 9 reduces to its zero-flow "
            "items plus W5, and the board reports to the owner. Nothing is tuned to make the "
            "gate pass."
        ),
    }
    report["sha256"] = write_new_json(Path(gate_file), plain(report))
    return report


# --- Stage 2: the driver -------------------------------------------------------------------


def run_sweep(stage: str = "all", max_runs: int | None = None,
              time_budget_seconds: float | None = None, workers: int = DEFAULT_WORKERS,
              root: Path = SWEEP, git=_git) -> dict:  # fmt: skip
    """Stage 2 (s. 6, s. 7): compute the missing artefacts of one work item, within a budget."""
    registration = require_committed_registration(git)
    key = physics_key()
    days = scored_days()
    wanted = {"all": set(EXPECTED_RUNS)}.get(stage, {stage.upper()})
    if not wanted <= set(EXPECTED_RUNS):
        raise ValueError(f"unknown stage {stage!r}")
    pending = []
    for spec in expected_specs():
        if spec.work_item not in wanted:
            continue
        if run_status(spec, key, len(days), root)["status"] == "missing":
            pending.append(spec)
    if max_runs is not None:
        pending = pending[: int(max_runs)]

    started = time.perf_counter()
    pool, pool_info = open_pool(workers)
    done, skipped, estimate = [], [], DEFAULT_RUN_ESTIMATE_SECONDS
    try:
        queue = list(pending)
        running: dict = {}

        def finish(spec: RunSpec, result: dict) -> None:
            nonlocal estimate
            extra = {
                "runtime_seconds": result["runtime_seconds"],
                "workers": pool_info["workers"],
                "pool_worked": pool_info["pool_worked"],
                "worker_pid": result["pid"],
                "source": "Stage 2 (s. 6, s. 7)",
            }
            payload = sidecar_payload(spec, key, result["arrays"], extra)
            write_run(artefact_path(spec, key, root), result["arrays"], payload)
            done.append({**spec.spec, "work_item": spec.work_item,
                         "runtime_seconds": result["runtime_seconds"]})  # fmt: skip
            estimate = sum(d["runtime_seconds"] for d in done) / len(done)

        while queue or running:
            while queue and len(running) < max(1, pool_info["workers"]):
                elapsed = time.perf_counter() - started
                if not budget_allows(elapsed, time_budget_seconds, estimate):
                    skipped = [s.spec for s in queue]
                    queue = []
                    break
                spec = queue.pop(0)
                if pool is None:
                    finish(spec, sweep_run(spec))
                else:
                    running[pool.submit(sweep_run, spec)] = spec
            if not running:
                continue
            completed, _ = wait(list(running), return_when=FIRST_COMPLETED)
            for future in completed:
                finish(running.pop(future), future.result())
    finally:
        if pool is not None:
            pool.shutdown()
    manifest = write_manifest(root, key)
    return {
        "stage": f"2 ({stage})",
        "registration": registration,
        "physics_key": key,
        "pool": {**pool_info, "requested_workers": workers},
        "pending_at_start": len(pending),
        "computed": done,
        "skipped_for_time_budget": skipped,
        "time_budget_seconds": time_budget_seconds,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "mean_run_seconds": estimate if done else None,
        "complete": manifest["complete"],
        "present_runs": manifest["present_runs"],
    }


def run_plan(root: Path = SWEEP) -> dict:
    """List the expected runs and their status. It computes nothing."""
    key = physics_key()
    days = scored_days()
    rows = [run_status(spec, key, len(days), root) for spec in expected_specs()]
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(row["work_item"], {"verified": 0, "missing": 0})
        counts[row["work_item"]][row["status"]] += 1
    return {
        "stage": "plan (computes nothing)",
        "registration": registration_state(),
        "physics_key": key,
        "physics_key_prefix": key[:16],
        "scored_days": {"count": len(days), "first": days[0], "last": days[-1]},
        "flows_per_run": len(days) * STEPS,
        "expected_runs": EXPECTED_RUNS,
        "status_counts": counts,
        "runs": rows,
    }


# --- CLI ------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan", help="list the expected runs and their status; computes nothing")
    gate = sub.add_parser("gate", help="Stage G, the reproduction gate (s. 11)")
    gate.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    sweep = sub.add_parser("sweep", help="Stage 2, the sweep (s. 6, s. 7)")
    sweep.add_argument("--stage", choices=("w6", "w8", "w9", "all"), default="all")
    sweep.add_argument("--max-runs", type=int, default=None)
    sweep.add_argument("--time-budget-seconds", type=float, default=None)
    sweep.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    sub.add_parser("manifest", help="derive sweep/manifest.json by scanning and re-verifying")
    args = parser.parse_args(argv)

    if args.command == "plan":
        report = run_plan()
    elif args.command == "gate":
        report = run_gate(workers=args.workers)
    elif args.command == "sweep":
        report = run_sweep(
            stage=args.stage,
            max_runs=args.max_runs,
            time_budget_seconds=args.time_budget_seconds,
            workers=args.workers,
        )
    else:
        report = write_manifest()
    print(json_text(plain(report)), end="")
    if args.command == "gate" and report["verdict"] == "ABORT":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
