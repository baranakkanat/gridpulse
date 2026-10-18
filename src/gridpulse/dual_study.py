"""Phase 4: reliability under dual uncertainty (docs/research_protocol.md, s. 4).

Two sources of uncertainty are varied one at a time and jointly:

- forecast information: a decision sees either the realised injections of the day
  ("perfect", F0) or the Phase 3 naive day-ahead forecast with 28 residual scenarios (F1);
- physical model: decisions are always made with the nominal SimBench network, while the
  grid that scores them ("truth") is either that network (M0) or a physically justified
  variant of it (transformer tap, MV voltage, PV reactive power, storage behaviour).

The physics stage reuses the Phase 3 injection sets (`grid_study.injection_sets`) and cap
levels and caches AC power-flow margins per network, model variant and day. Every policy is
then a rule over cached margins, scored on the true model's realised margins.

Information timing: decisions for day d use only days before d, plus (for F0) the realised
injections of day d. Online calibration uses realised violations of earlier days, measured on
the true grid at the cap that was actually applied.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path

import numpy as np

from gridpulse import grid, grid_study
from gridpulse.grid import GridSolver, absolute_profiles, cap_pv, load_network
from gridpulse.grid_study import CAP_LEVELS, FIRST_DECISION_DAY, FORECAST_DAYS, STEPS
from gridpulse.uncertainty import block_bootstrap, block_bootstrap_mean

# --- Model variants ----------------------------------------------------------------


@dataclass(frozen=True)
class ModelVariant:
    """A physically justified deviation of the true grid from the nominal model.

    - `tap_steps`: added to every transformer's benchmark tap position. Taps are on the HV
      side, so +1 lowers and -1 raises the LV voltage by one 2.5 % step;
    - `slack_vm_pu`: MV voltage at the secondary substation (None = benchmark 1.025 p.u.);
    - `pv_reactive`: PV reactive power, generator convention, underexcited (absorbing):
      "none" (q = 0, the benchmark), "cosphi_p" (VDE-AR-N 4105 standard characteristic:
      cos phi = 1 up to half the rating, then linear to `pv_cosphi` at full rating) or
      "fixed" (cos phi = `pv_cosphi` at every output);
    - `storage`: "idle" (0 MW, the nominal model), "profile_charging" (the benchmark's
      one-signed storage series read as charging, limited by each unit's energy content,
      emptied at 00:00 UTC) or "greedy" (the network's total storage power and energy moved
      to the PV buses in proportion to PV rating, maximising self-consumption against the
      local load).

    Storage schedules do not depend on the PV cap: batteries are assumed to act on
    uncurtailed PV (curtailment mostly binds when greedy batteries are already full).
    """

    tap_steps: int = 0
    slack_vm_pu: float | None = None
    pv_reactive: str = "none"
    pv_cosphi: float = 1.0
    storage: str = "idle"


NOMINAL = ModelVariant()
STORAGE_EFFICIENCY = 0.95  # one-way efficiency (the benchmark storage units' value)


def variant_network(code: str, variant: ModelVariant, pv_scale: float = 1.0):
    """The SimBench network `code` with its PV installations scaled by `pv_scale` (rating
    and output alike), the variant's transformer and MV settings, and for "greedy" storage
    the storage units moved to the PV buses."""
    net = load_network(code)
    if pv_scale != 1.0:
        net.sgen["p_mw"] = net.sgen["p_mw"] * pv_scale
        net.sgen["sn_mva"] = net.sgen["sn_mva"] * pv_scale
    if variant.tap_steps:
        position = net.trafo["tap_pos"] + variant.tap_steps
        if ((position < net.trafo["tap_min"]) | (position > net.trafo["tap_max"])).any():
            raise ValueError(f"tap shift {variant.tap_steps} leaves the tap range of {code}")
        net.trafo["tap_pos"] = position
    if variant.slack_vm_pu is not None:
        net.ext_grid["vm_pu"] = variant.slack_vm_pu
    if variant.storage == "greedy":
        import pandapower as pp

        power, energy = net.storage["sn_mva"].sum(), net.storage["max_e_mwh"].sum()
        profile = net.storage["profile"].iloc[0]  # zero power below; keeps profiles valid
        net.storage = net.storage.drop(net.storage.index)
        share = net.sgen["sn_mva"] / net.sgen["sn_mva"].sum()
        for bus, fraction in zip(net.sgen["bus"], share, strict=True):
            index = pp.create_storage(
                net, bus=bus, p_mw=0.0, max_e_mwh=energy * fraction, sn_mva=power * fraction
            )
            net.storage.loc[index, "profile"] = profile
    return net


def pv_reactive_power(p_mw: np.ndarray, rating_mw: np.ndarray, mode: str, cosphi: float):
    """Reactive power (generator convention, < 0 = absorbing) of the PV units."""
    if mode == "none":
        return np.zeros_like(p_mw)
    if mode == "fixed":
        return -p_mw * np.tan(np.arccos(cosphi))
    if mode != "cosphi_p":
        raise ValueError(f"unknown PV reactive-power mode {mode!r}")
    ratio = np.divide(p_mw, rating_mw, out=np.zeros_like(p_mw), where=rating_mw > 0)
    value = np.where(ratio <= 0.5, 1.0, 1.0 - (1.0 - cosphi) * (ratio - 0.5) / 0.5)
    return -p_mw * np.tan(np.arccos(np.clip(value, cosphi, 1.0)))


class VariantSolver(GridSolver):
    """`GridSolver` whose PV units follow the variant's reactive-power rule. Limits,
    margins and failure handling are those of `GridSolver`."""

    def __init__(self, net, variant: ModelVariant):
        super().__init__(net)
        self.pv_reactive, self.pv_cosphi = variant.pv_reactive, variant.pv_cosphi

    def solve(self, load_p_mw, load_q_mvar, sgen_p_mw, storage_p_mw) -> np.ndarray:
        self.net.sgen["q_mvar"] = pv_reactive_power(
            np.asarray(sgen_p_mw, dtype=float), self.pv_rating_mw, self.pv_reactive, self.pv_cosphi
        )
        return super().solve(load_p_mw, load_q_mvar, sgen_p_mw, storage_p_mw)


def storage_schedule(net, variant: ModelVariant, n_days: int) -> np.ndarray:
    """Storage power (days x 96 x units, MW, load convention: + = charging) of the variant.

    - "profile_charging": the magnitude of the benchmark storage series as charging power
      while the unit's energy content is below `max_e_mwh`; emptied at 00:00 UTC each day
      (overnight discharge into local load is not modelled).
    - "greedy": each unit (at a PV bus, see `variant_network`) charges with the PV surplus
      over its share of the bus load and discharges into the deficit, within its power and
      energy limits; the energy content carries over from day to day, starting empty.
    """
    units = len(net.storage)
    if variant.storage == "idle" or units == 0:
        return np.zeros((n_days, STEPS, units))
    capacity = net.storage["max_e_mwh"].to_numpy(dtype=float)
    profiles = absolute_profiles(net)
    start = profiles["sgen_p_mw"].index.get_loc(grid_study.FIRST_DAY)

    def steps(name: str) -> np.ndarray:
        return profiles[name].to_numpy()[start : start + n_days * STEPS]

    schedule = np.zeros((n_days * STEPS, units))
    content = np.zeros(units)
    dt, eta = grid.STEP_HOURS, STORAGE_EFFICIENCY
    if variant.storage == "profile_charging":
        power = np.abs(steps("storage_p_mw"))
        for i in range(n_days * STEPS):
            if i % STEPS == 0:
                content[:] = 0.0
            schedule[i] = np.minimum(power[i], np.maximum(capacity - content, 0) / (dt * eta))
            content += schedule[i] * dt * eta
    elif variant.storage == "greedy":
        same_bus = net.load["bus"].to_numpy()[:, None] == net.sgen["bus"].to_numpy()[None, :]
        rating = net.sgen["sn_mva"].to_numpy(dtype=float)
        weight = same_bus * rating / np.maximum(same_bus @ rating, 1e-12)[:, None]
        surplus = steps("sgen_p_mw") - steps("load_p_mw") @ weight
        limit = net.storage["sn_mva"].to_numpy(dtype=float)
        for i in range(n_days * STEPS):
            room = np.maximum(capacity - content, 0) / (dt * eta)
            charge = np.minimum(np.minimum(np.maximum(surplus[i], 0), limit), room)
            discharge = np.minimum(
                np.minimum(np.maximum(-surplus[i], 0), limit), content * eta / dt
            )
            schedule[i] = charge - discharge
            content += charge * dt * eta - discharge * dt / eta
    else:
        raise ValueError(f"unknown storage behaviour {variant.storage!r}")
    return schedule.reshape(n_days, STEPS, units)


# --- Physics stage -----------------------------------------------------------------


def day_margins(solver: GridSolver, sets: dict, storage_mw: np.ndarray) -> np.ndarray:
    """Margins (sets x 96 x cap levels x MARGINS) of every injection set under every cap,
    with a storage schedule per set and step (sets x 96 x units). As
    `grid_study.day_physics`, the solver restarts each day and a cap that does not bind
    reproduces the uncapped flow."""
    solver.reset()
    rating = solver.pv_rating_mw
    n_sets = sets["sgen_p_mw"].shape[0]
    margins = np.empty((n_sets, STEPS, len(CAP_LEVELS), len(grid.MARGINS)), dtype=np.float32)
    for s in range(n_sets):
        for t in range(STEPS):
            load_p, load_q = sets["load_p_mw"][s, t], sets["load_q_mvar"][s, t]
            available, storage = sets["sgen_p_mw"][s, t], storage_mw[s, t]
            margins[s, t, 0] = solver.solve(load_p, load_q, available, storage)
            for level, cap in enumerate(CAP_LEVELS[1:], start=1):
                if np.all(available <= cap * rating):
                    margins[s, t, level] = margins[s, t, 0]
                else:
                    capped = cap_pv(available, rating, cap)
                    margins[s, t, level] = solver.solve(load_p, load_q, capped, storage)
    return margins


def day_storage(schedule: np.ndarray, day: int, n_sets: int) -> np.ndarray:
    """Storage power per injection set (sets x 96 x units): the day's own schedule for the
    realised set, its FORECAST_DAYS-day mean for the forecast set (the schedule follows
    same-day PV, so it must not inform a day-ahead decision), and none for scenarios (the
    nominal model, the only one with scenario sets, has idle storage)."""
    storage = np.zeros((n_sets,) + schedule.shape[1:])
    storage[0] = schedule[day]
    if n_sets > 1:
        storage[1] = grid_study.forecast(schedule, day)
    if n_sets > 2 and schedule.any():
        raise ValueError("scenario sets are defined for the nominal (idle storage) model only")
    return storage


def day_sets(arrays: dict, day: int, rating: np.ndarray, n_sets: int) -> dict:
    """The first `n_sets` Phase 3 injection sets of `day` (0 realised, 1 forecast, 2.. the
    28 scenarios); days before the first decision day have the realised set only."""
    if day < FIRST_DECISION_DAY:
        return {name: arrays[name][day][None] for name in grid_study.PROFILE_KEYS}
    sets = grid_study.injection_sets(arrays, day, rating)
    return {name: values[:n_sets] for name, values in sets.items()}


_WORKER: dict = {}


def _init_worker(code: str, variant: ModelVariant, pv_scale: float) -> None:
    net = variant_network(code, variant, pv_scale)
    arrays = grid_study.daily_arrays(absolute_profiles(net))
    _WORKER.clear()
    _WORKER.update(
        solver=VariantSolver(net, variant),
        arrays=arrays,
        storage=storage_schedule(net, variant, len(arrays["sgen_p_mw"])),
    )


def _compute(task: tuple[int, int]) -> tuple[int, np.ndarray]:
    day, n_sets = task
    sets = day_sets(_WORKER["arrays"], day, _WORKER["solver"].pv_rating_mw, n_sets)
    storage = day_storage(_WORKER["storage"], day, sets["sgen_p_mw"].shape[0])
    return day, day_margins(_WORKER["solver"], sets, storage)


def physics_fingerprint() -> str:
    """Hash of the code, settings and package versions that determine Phase 4 physics."""
    sources = [
        inspect.getsource(obj)
        for obj in (
            grid.load_network,
            grid.absolute_profiles,
            grid.cap_pv,
            grid.GridSolver,
            grid_study.daily_arrays,
            grid_study.forecast,
            grid_study.scenarios,
            grid_study.injection_sets,
            ModelVariant,
            variant_network,
            pv_reactive_power,
            VariantSolver,
            storage_schedule,
            day_margins,
            day_storage,
            day_sets,
            _init_worker,
            _compute,
        )
    ]
    settings = [repr(CAP_LEVELS.tolist()), STEPS, FORECAST_DAYS, STORAGE_EFFICIENCY]
    versions = [version(name) for name in ("numpy", "pandas", "pandapower", "simbench")]
    return hashlib.sha256(repr((sources, settings, versions)).encode()).hexdigest()


def compute_physics(
    code: str,
    pv_scale: float,
    variant_name: str,
    variant: ModelVariant,
    tasks: list[tuple[int, int]],
    cache_dir: Path,
    workers: int | None = None,
) -> dict:
    """Compute the missing (day, number of sets) margins of one network and model variant.

    Layout: cache_dir/<network>/<variant>/day_NNN.npy, with a manifest recording the
    physics fingerprint and the variant definition; a folder produced by other code or for
    another variant is refused. Files are written atomically.
    """
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    fingerprint = physics_fingerprint()
    folder = cache_dir / code / variant_name
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.json"
    expected = {
        "fingerprint": fingerprint,
        "network": code,
        "pv_scale": pv_scale,
        "variant": asdict(variant),
    }
    if manifest.exists():
        if json.loads(manifest.read_text()) != expected:
            raise ValueError(f"{folder} was produced by different physics; delete it")
    elif any(folder.glob("day_*.npy")):
        raise ValueError(f"{folder} has cached days but no manifest; delete it")
    else:
        manifest.write_text(json.dumps(expected) + "\n")
    path = {day: folder / f"day_{day:03d}.npy" for day, _ in tasks}
    missing = [(day, n_sets) for day, n_sets in tasks if not path[day].exists()]
    if missing:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker, initargs=(code, variant, pv_scale)
        ) as pool:
            for day, margins in pool.map(_compute, missing, chunksize=1):
                temporary = path[day].with_name(path[day].stem + ".partial.npy")
                np.save(temporary, margins)
                temporary.replace(path[day])
    return {
        "fingerprint": fingerprint,
        "computed": len(missing),
        "from_cache": len(tasks) - len(missing),
    }


def load_margins(
    cache_dir: Path, code: str, variant_name: str, days, pv_scale: float, variant: ModelVariant
) -> dict[int, np.ndarray]:
    """Cached margins of one network and model variant; refused unless the folder's manifest
    matches the current physics code, PV scale and variant definition."""
    folder = cache_dir / code / variant_name
    expected = {
        "fingerprint": physics_fingerprint(),
        "network": code,
        "pv_scale": pv_scale,
        "variant": asdict(variant),
    }
    manifest = folder / "manifest.json"
    if not manifest.exists() or json.loads(manifest.read_text()) != expected:
        raise ValueError(f"{folder} does not match the current physics; recompute it")
    return {day: np.load(folder / f"day_{day:03d}.npy") for day in days}


# --- Network stress: PV hosting capacity ------------------------------------------


def violates_at_scale(code: str, pv_scale: float, days) -> bool:
    """Whether any daylight step of `days` violates a limit at no action (nominal model,
    storage idle) with the network's PV scaled by `pv_scale`."""
    net = variant_network(code, NOMINAL, pv_scale)
    arrays = grid_study.daily_arrays(absolute_profiles(net))
    solver = GridSolver(net)
    storage = np.zeros(len(net.storage))
    for day in days:
        solver.reset()
        for t in range(STEPS):
            available = arrays["sgen_p_mw"][day, t]
            if not available.any():
                continue
            injections = (arrays["load_p_mw"][day, t], arrays["load_q_mvar"][day, t])
            if grid.is_violation(solver.solve(*injections, available, storage)):
                return True
    return False


def hosting_capacity(code: str, days, tolerance: float = 0.005) -> dict:
    """Largest uniform PV scale (of the benchmark's installations) without a no-action
    violation on any daylight step of `days`, by bisection to a relative `tolerance`.
    The bracket ends are verified (no violation at the returned scale, a violation at the
    first-violation scale); a non-monotone response inside the bracket could be missed."""
    low, high = 0.0, 1.0
    while not violates_at_scale(code, high, days):
        low, high = high, 2 * high
        if high > 64:
            raise ValueError(f"{code}: no violation up to 64x the benchmark PV")
    while high - low > tolerance * high:
        middle = (low + high) / 2
        if violates_at_scale(code, middle, days):
            high = middle
        else:
            low = middle
    return {"network": code, "hosting_capacity_scale": low, "first_violation_scale": high}


# Development-half PV hosting capacities as multiples of each network's benchmark PV
# (`hosting_capacity` over 2016-01-01 .. 06-30 UTC, tolerance 0.5 %), computed before any
# policy was run on these networks (protocol s. 4.2).
HOSTING_CAPACITY = {
    "1-LV-rural1--2-sw": 0.71484375,
    "1-LV-rural2--2-sw": 2.09375,
    "1-LV-rural3--2-sw": 3.109375,
    "1-LV-semiurb4--2-sw": 2.6640625,
    "1-LV-semiurb5--2-sw": 4.96875,
    "1-LV-urban6--2-sw": 4.296875,
}
DEVELOPMENT_NETWORK = "1-LV-rural1--2-sw"


def pv_scale(code: str) -> float:
    """PV scale that loads `code` to the same multiple of its own hosting capacity as the
    benchmark's rural1 scenario 2 (which keeps its published PV)."""
    if code == DEVELOPMENT_NETWORK:
        return 1.0
    return HOSTING_CAPACITY[code] / HOSTING_CAPACITY[DEVELOPMENT_NETWORK]


# --- Decision stage ----------------------------------------------------------------

REALISED, FORECAST = grid_study.REALISED, grid_study.FORECAST
LAST_LEVEL = len(CAP_LEVELS) - 1
# Normalised margin: value minus limit as a share of the allowed band (0.1 p.u. from
# nominal voltage to its limit, 100 % loading), the largest over the four constraint types.
MARGIN_SCALE = np.array([0.1, 0.1, 100.0, 100.0], dtype=np.float32)
REPLAY_DAYS = 28  # historical replay window (as the Phase 3 frequency reference)
RISK_MAX_COUNT = 1  # Phase 3 risk rule: at most 1 of 28 scenarios violates (alpha 0.05)
TAU_GRID = np.round(np.arange(0.0, 1.0001, 0.01), 2)  # development-tuned point margin
SEVERE_MARGIN = 0.2  # secondary check: e.g. above 120 % loading or 0.02 p.u. beyond a limit
LONG_RUN_STEPS = 4  # secondary check: runs of at least one hour of violation


@dataclass(frozen=True)
class OnlineSettings:
    """Online calibration (ACI-style) of a planning margin from measured violations.

    After each day, tau <- clip(tau + gamma x (V - beta), tau_min, tau_max), where V is the
    number of daylight quarter-hours that violated a limit on the true grid under the
    applied caps and beta the target mean per day. `tau_max` (amendment 4B) keeps tau below
    the point (about 0.5) where, in networks whose LV voltage sits near 1.05 p.u. without
    PV, no cap level satisfies the margin and the rule degenerates to curtailing all PV.
    `static_aci` adapts a cap-level index c in [0, 10] instead, by `gamma_level` x (V - beta),
    starting from the development-tuned `static_beta` level, and applies c rounded half up.
    """

    beta: float = 0.1
    gamma: float = 0.01
    tau_min: float = -0.10
    tau_max: float = 0.40
    gamma_level: float = 0.03


def normalised(margins: np.ndarray) -> np.ndarray:
    """Largest normalised margin over constraint types; a failed flow counts as +inf."""
    value = (margins / MARGIN_SCALE).max(axis=-1)
    return np.where(np.isnan(margins).any(axis=-1), np.inf, value)


def first_safe(worst: np.ndarray, tau: float = 0.0) -> np.ndarray:
    """Per step, the least curtailment whose (worst-case) normalised margin is <= -tau;
    the deepest cap if none is."""
    return grid_study.first_level(worst <= -tau)


def daylight_of(available: np.ndarray) -> np.ndarray:
    """Quarter-hours with any available PV (days x 96 or 96)."""
    return available.sum(axis=-1) > 0


def static_level(realised: list[np.ndarray], daylight: list[np.ndarray], per_day: float) -> int:
    """Largest uniform cap whose mean daylight violation steps per day on the given days
    (realised normalised margins, steps x levels) is <= `per_day`; else the fewest."""
    counts = sum(
        ((n > 0) & d[:, None]).sum(axis=0) for n, d in zip(realised, daylight, strict=True)
    )
    ok = counts / len(realised) <= per_day
    return int(np.flatnonzero(ok)[0]) if ok.any() else int(counts.argmin())


def tuned_point_margin(point: list[np.ndarray], realised: list[np.ndarray]) -> float:
    """Smallest tau on TAU_GRID with which the point rule causes no violation on the given
    days (decision and realised margins of the nominal model); if none, the smallest tau
    with the fewest violations (the same fallback as `static_level`)."""
    steps = np.arange(STEPS)
    counts = []
    for tau in TAU_GRID:
        levels = [first_safe(p, tau) for p in point]
        counts.append(
            sum(int((r[steps, lv] > 0).sum()) for r, lv in zip(realised, levels, strict=True))
        )
        if counts[-1] == 0:
            return float(tau)
    return float(TAU_GRID[int(np.argmin(counts))])


def curtailed_mwh(available: np.ndarray, rating: np.ndarray, levels: np.ndarray) -> float:
    capped = np.minimum(available, CAP_LEVELS[levels][:, None] * rating)
    return float((available - capped).sum() * grid.STEP_HOURS)


def runs(flags: np.ndarray) -> list[int]:
    """Lengths of the runs of consecutive True values."""
    lengths, run = [], 0
    for flag in list(flags) + [False]:
        if flag:
            run += 1
        elif run:
            lengths.append(run)
            run = 0
    return lengths


def score(truth: np.ndarray, levels: np.ndarray, available: np.ndarray, rating) -> dict:
    """Realised outcome of a cap schedule on the true grid (truth: 96 x levels normalised).

    A violation is *avoidable* if some cap level is safe at that step on the true grid; the
    requirement is scored on avoidable daylight violations. Run lengths, severe steps and
    the peak margin indicate thermal relevance (one quarter-hour at 101 % is not a thermal
    event for an ONAN transformer; hours at 140 % are)."""
    applied = truth[np.arange(STEPS), levels]
    violated = applied > 0
    daylight = daylight_of(available)
    avoidable = (truth <= 0).any(axis=1)
    finite = np.isfinite(applied)
    lengths = runs(violated)
    return {
        "violation_steps": int(violated.sum()),
        "daylight_violation_steps": int((violated & daylight).sum()),
        "avoidable_violation_steps": int((violated & daylight & avoidable).sum()),
        "nonconverged_steps": int((~finite).sum()),
        "severity": float(np.where(finite, np.maximum(applied, 0), 0).sum()),
        "severe_steps": int((applied > SEVERE_MARGIN).sum()),
        "longest_violation_run": max(lengths, default=0),
        "long_runs": sum(length >= LONG_RUN_STEPS for length in lengths),
        "peak_margin": float(applied.max()),  # +inf if any applied flow failed
        "curtailed_mwh": curtailed_mwh(available, rating, levels),
    }


POLICIES_F0 = ("point", "point_aci", "ensemble")
POLICIES_F1 = (
    "point",
    "point_margin",
    "point_aci",
    "scenario_risk",
    "scenario_robust",
    "scenario_aci",
    "ensemble",
)
POLICIES_COMMON = (
    "no_action",
    "static_dev",
    "static_beta",
    "static_aci",
    "replay_robust",
    "replay_aci",
    "oracle",
)
MARGIN_ONLINE = ("point_aci", "scenario_aci", "replay_aci")


def decision_plans(
    norm: dict[int, np.ndarray],
    norm_v: dict[str, dict[int, np.ndarray]],
    day: int,
    information: str,
    ensemble: tuple[str, ...],
    tau: dict[str, float],
    level_index: float,
    tuned: dict,
) -> dict[str, np.ndarray]:
    """Cap-level schedules of every non-oracle policy for `day`, from normalised margins.

    Uses the nominal model's realised sets of days before `day` (replay), and for `day`
    itself only its forecast and scenario sets (F1) or its realised injections under the
    nominal model and the ensemble members (F0). The true model never enters. `tuned`
    holds the development-tuned settings (static levels, point margin)."""
    point = norm[day][REALISED if information == "perfect" else FORECAST]
    replay = np.stack([norm[j][REALISED] for j in range(day - REPLAY_DAYS, day)]).max(axis=0)
    if information == "perfect":
        ensemble_worst = np.max([norm_v[v][day][REALISED] for v in ensemble] + [point], axis=0)
    else:
        scenario = norm[day][FORECAST + 1 :]
        scenario_worst = scenario.max(axis=0)
        with np.errstate(invalid="ignore"):
            shifts = [norm_v[v][day][FORECAST] - point for v in ensemble]
        shift = np.max([np.where(np.isnan(s), np.inf, s) for s in shifts], axis=0)
        shift = np.where(np.isinf(point), np.inf, shift)  # a failed nominal flow is unsafe
        ensemble_worst = scenario_worst + np.maximum(shift, 0.0)
    plan = {
        "no_action": np.zeros(STEPS, dtype=int),
        "static_dev": np.full(STEPS, tuned["static_dev_level"]),
        "static_beta": np.full(STEPS, tuned["static_beta_level"]),
        "static_aci": np.full(STEPS, int(np.floor(level_index + 0.5))),
        "replay_robust": first_safe(replay),
        "replay_aci": first_safe(replay, tau["replay_aci"]),
        "point": first_safe(point),
        "point_aci": first_safe(point, tau["point_aci"]),
        "ensemble": first_safe(ensemble_worst),
    }
    if information == "forecast":
        plan["point_margin"] = first_safe(point, tuned["point_margin_tau"])
        plan["scenario_risk"] = grid_study.first_level((scenario > 0).sum(axis=0) <= RISK_MAX_COUNT)
        plan["scenario_robust"] = first_safe(scenario_worst)
        plan["scenario_aci"] = first_safe(scenario_worst, tau["scenario_aci"])
    return plan


def tune_on_development(
    norm: dict[int, np.ndarray], information: str, available, development, online: OnlineSettings
) -> dict:
    """Settings a DSO would fix from development days with its (nominal) model."""
    realised = [norm[d][REALISED] for d in development]
    daylight = [daylight_of(available[d]) for d in development]
    return {
        "static_dev_level": static_level(realised, daylight, 0.0),
        "static_beta_level": static_level(realised, daylight, online.beta),
        "point_margin_tau": 0.0
        if information == "perfect"
        else tuned_point_margin([norm[d][FORECAST] for d in development], realised),
    }


def run_cell(
    norm: dict[int, np.ndarray],
    norm_v: dict[str, dict[int, np.ndarray]],
    truth: str,
    ensemble: tuple[str, ...],
    information: str,
    available: np.ndarray,
    rating: np.ndarray,
    development: list[int],
    days: list[int],
    online: OnlineSettings,
) -> tuple[list[dict], dict]:
    """Apply every policy of one (truth model, forecast information) cell day by day.

    `norm[d]` and `norm_v[v][d]` are normalised margins (sets x 96 x levels): the nominal
    model has 30 sets on decision days and the realised set only on earlier days; a variant
    has its realised and forecast sets. `information` is "perfect" (F0) or "forecast" (F1).
    Online policies start from neutral settings on the first decision day and learn from
    measured (true-grid) daylight violations at the caps they applied. Returns the per-day
    records of the scored `days` and the development-tuned settings, with the online states
    reached at the end of development.
    """
    if information not in ("perfect", "forecast"):
        raise ValueError(f"unknown information {information!r}")
    if not ensemble:
        raise ValueError("the model ensemble needs at least one variant")
    truth_of = norm if truth == "nominal" else norm_v[truth]
    tuned = tune_on_development(norm, information, available, development, online)
    policies = POLICIES_COMMON + (POLICIES_F0 if information == "perfect" else POLICIES_F1)
    tau = dict.fromkeys(MARGIN_ONLINE, 0.0)
    # static_aci starts at the development-tuned static_beta level (amendment 4C); within
    # development this is look-ahead, so only its evaluation results are meaningful
    level_index = float(tuned["static_beta_level"])
    records = []
    for day in sorted(d for d in norm if d >= FIRST_DECISION_DAY):
        plan = decision_plans(norm, norm_v, day, information, ensemble, tau, level_index, tuned)
        truth_day = truth_of[day][REALISED]
        plan["oracle"] = first_safe(truth_day)
        outcome = {name: score(truth_day, plan[name], available[day], rating) for name in policies}
        clip = {}
        for name in MARGIN_ONLINE:
            if name in outcome:
                step = tau[name] + online.gamma * (
                    outcome[name]["daylight_violation_steps"] - online.beta
                )
                clip[name] = float(np.clip(step, online.tau_min, online.tau_max)) - step
        step = level_index + online.gamma_level * (
            outcome["static_aci"]["daylight_violation_steps"] - online.beta
        )
        clip["static_aci"] = float(np.clip(step, 0, LAST_LEVEL)) - step
        if day in days:
            daylight = daylight_of(available[day])
            unavoidable = ~(truth_day <= 0).any(axis=1)
            record = {
                "day": day,
                "unavoidable_steps": int(unavoidable.sum()),
                "unavoidable_daylight_steps": int((unavoidable & daylight).sum()),
            }
            for name, result in outcome.items():
                record.update({f"{name}__{key}": value for key, value in result.items()})
            record.update({f"{name}__tau": value for name, value in tau.items()})  # as applied
            record["static_aci__level_index"] = level_index  # as applied
            record.update({f"{name}__clip": value for name, value in clip.items()})
            records.append(record)
        for name in MARGIN_ONLINE:
            if name in outcome:
                tau[name] = float(
                    np.clip(
                        tau[name]
                        + online.gamma * (outcome[name]["daylight_violation_steps"] - online.beta),
                        online.tau_min,
                        online.tau_max,
                    )
                )
        level_index = float(np.clip(step, 0, LAST_LEVEL))
        if day == max(development):
            tuned["online_state_end_of_development"] = {
                **{name: tau[name] for name in MARGIN_ONLINE if name in outcome},
                "static_aci_level_index": level_index,
            }
    return records, tuned


# --- Risk diagnostics (H1) --------------------------------------------------------


UNBOUNDED_RATIO = 1e6  # realised over predicted when nothing was predicted but some occurred


def _ratio(numerator: float, denominator: float) -> float:
    """Realised over predicted; 0/0 counts as 1 (no evidence either way) and x/0 as
    UNBOUNDED_RATIO, a finite stand-in for +inf that keeps bootstrap percentiles defined."""
    if denominator > 0:
        return numerator / denominator
    return 1.0 if numerator == 0 else UNBOUNDED_RATIO


def risk_diagnostics(norm: dict[int, np.ndarray], truth: dict[int, np.ndarray], days) -> dict:
    """Calibration of the risk reported at the Phase 3 rule's chosen caps.

    For the residual scenarios and for the replay ensemble (realised days d-28..d-1), the
    rule picks the least curtailment with at most 1 violating member. On steps where some
    member violates at no action, realised true-grid violations at the chosen caps are
    compared with:
    - the in-sample risk (share of members violating at the chosen cap);
    - the leave-one-out risk: for each member i, the rule is applied to the other members
      and member i's violation at that cap is recorded; the mean over i estimates the
      rule's out-of-sample risk without the selection bias of the in-sample estimate.
    Ratios carry 95 % day-block bootstrap intervals; `violation_days` counts the distinct
    days with a realised violation (informative if >= 8).
    """
    steps = np.arange(STEPS)
    result = {}
    for ensemble in ("scenario", "replay"):
        rows = []
        for day in days:
            if ensemble == "scenario":
                members = norm[day][FORECAST + 1 :] > 0
            else:
                members = np.stack([norm[j][REALISED] for j in range(day - REPLAY_DAYS, day)]) > 0
            counts = members.sum(axis=0)
            active = members[:, :, 0].any(axis=0)
            levels = grid_study.first_level(counts <= RISK_MAX_COUNT)
            in_sample = (counts / len(members))[steps, levels]
            loo = np.mean(
                [
                    member[steps, grid_study.first_level(counts - member <= RISK_MAX_COUNT)]
                    for member in members
                ],
                axis=0,
            )
            realised = truth[day][steps, levels] > 0
            rows.append(
                [realised[active].sum(), in_sample[active].sum(), loo[active].sum(), active.sum()]
            )
        rows = np.array(rows, dtype=float)
        summary = {
            "active_steps": int(rows[:, 3].sum()),
            "realised_violations": int(rows[:, 0].sum()),
            "violation_days": int((rows[:, 0] > 0).sum()),
            "in_sample_predicted": float(rows[:, 1].sum()),
            "leave_one_out_predicted": float(rows[:, 2].sum()),
        }
        for name, column in (("in_sample", 1), ("leave_one_out", 2)):
            summary[f"realised_over_{name}"] = block_bootstrap(
                rows, lambda x, c=column: _ratio(x[:, 0].sum(), x[:, c].sum())
            )
        result[ensemble] = summary
    # Probabilistic skill at no action: residual-scenario risk vs replay frequency.
    scenario, replay, observed = [], [], []
    for day in days:
        scenario.append((norm[day][FORECAST + 1 :, :, 0] > 0).mean(axis=0))
        replay.append(
            np.mean([norm[j][REALISED][:, 0] > 0 for j in range(day - REPLAY_DAYS, day)], axis=0)
        )
        observed.append((truth[day][:, 0] > 0).astype(float))
    scenario, replay, observed = (np.stack(x) for x in (scenario, replay, observed))
    per_day = np.stack(
        [((scenario - observed) ** 2).sum(axis=1), ((replay - observed) ** 2).sum(axis=1)], axis=1
    )
    result["no_action_brier"] = {
        "scenario": float(((scenario - observed) ** 2).mean()),
        "replay": float(((replay - observed) ** 2).mean()),
        "skill_scenario_vs_replay": block_bootstrap(
            per_day, lambda x: 1 - x[:, 0].sum() / x[:, 1].sum() if x[:, 1].sum() else 0.0
        )
        if per_day[:, 1].sum()
        else None,
        "observed_rate": float(observed.mean()),
    }
    return result


# --- Summaries ---------------------------------------------------------------------

AWARE = ("replay_aci", "scenario_aci")
SIMPLE = ("static_dev", "static_beta", "static_aci", "point_margin")
PAIRS = (  # registered paired comparisons (policy a minus policy b, per day)
    ("scenario_aci", "replay_aci"),  # H2: value of the day-ahead forecast over replay
    *((a, b) for a in AWARE for b in SIMPLE),  # H3: reliability-aware vs simple policies
    ("ensemble", "replay_aci"),  # H4: explicit model ensemble vs measured feedback
    ("ensemble", "point_aci"),
    ("point", "ensemble"),
)
METRICS = (
    "violation_steps",
    "daylight_violation_steps",
    "avoidable_violation_steps",
    "nonconverged_steps",
    "severity",
    "severe_steps",
    "long_runs",
    "curtailed_mwh",
)
EXPLORATORY_BETAS = (0.05, 0.2)


def summarise_cell(records: list[dict], online: OnlineSettings) -> dict:
    """Totals, worst-day statistics, online-calibration identities and registered paired
    comparisons of one cell. The requirement is scored on avoidable daylight violations."""
    frame = {key: np.array([r[key] for r in records]) for key in records[0]}
    policies = sorted({key.split("__")[0] for key in frame if key.endswith("__violation_steps")})
    days = len(records)
    unavoidable = int(frame["unavoidable_daylight_steps"].sum())
    totals = {}
    for policy in policies:
        result = {m: float(frame[f"{policy}__{m}"].sum()) for m in METRICS}
        daily = frame[f"{policy}__avoidable_violation_steps"]
        per_day = result["avoidable_violation_steps"] / days
        result.update(
            {
                "violation_steps_per_day": per_day,
                "meets_beta": bool(per_day <= online.beta),
                "meets_exploratory_beta": {str(b): bool(per_day <= b) for b in EXPLORATORY_BETAS},
                "days_with_violation": int((daily > 0).sum()),
                "worst_day_violation_steps": int(daily.max()),
                "longest_violation_run": int(frame[f"{policy}__longest_violation_run"].max()),
                "peak_margin": float(frame[f"{policy}__peak_margin"].max()),
                "excess_curtailment_vs_oracle_mwh": result["curtailed_mwh"]
                - float(frame["oracle__curtailed_mwh"].sum()),
            }
        )
        totals[policy] = result
    online_identity = {}
    for policy in (*MARGIN_ONLINE, "static_aci"):
        if f"{policy}__clip" not in frame:
            continue
        state = "static_aci__level_index" if policy == "static_aci" else f"{policy}__tau"
        gain = online.gamma_level if policy == "static_aci" else online.gamma
        feedback = frame[f"{policy}__daylight_violation_steps"].astype(float)
        start, last = float(frame[state][0]), float(frame[state][-1])
        end = last + gain * (feedback[-1] - online.beta) + float(frame[f"{policy}__clip"][-1])
        clipped = float(frame[f"{policy}__clip"].sum())
        online_identity[policy] = {
            "state_start": start,
            "state_end": end,
            "clipping_total": clipped,
            "mean_feedback_per_day": float(feedback.mean()),
            "identity_mean_feedback": online.beta + (end - start - clipped) / (gain * days),
        }
    paired = {}
    for a, b in PAIRS:
        if a in policies and b in policies:
            pair = {}
            for m in ("avoidable_violation_steps", "curtailed_mwh"):
                difference = (frame[f"{a}__{m}"] - frame[f"{b}__{m}"]).astype(float)
                pair[m] = block_bootstrap_mean(difference)
            either = (frame[f"{a}__avoidable_violation_steps"] > 0) | (
                frame[f"{b}__avoidable_violation_steps"] > 0
            )
            pair["informative_days"] = int(either.sum())
            dv = totals[a]["avoidable_violation_steps"] - totals[b]["avoidable_violation_steps"]
            de = totals[a]["curtailed_mwh"] - totals[b]["curtailed_mwh"]
            pair["mwh_per_violation_step"] = de / -dv if dv else None  # cost of reliability
            paired[f"{a}_minus_{b}"] = pair
    return {
        "days": days,
        "unavoidable_daylight_steps": unavoidable,
        "excluded": unavoidable > online.beta * days,
        "totals": totals,
        "online_identity": online_identity,
        "paired_per_day": paired,
    }


# --- Registered design and runner -------------------------------------------------

VARIANTS = {
    # single deviations (the model ensemble)
    "tap_raise_lv": ModelVariant(tap_steps=-1),
    "tap_lower_lv": ModelVariant(tap_steps=1),
    "pv_cosphi_p": ModelVariant(pv_reactive="cosphi_p", pv_cosphi=0.90),
    "pv_fixed_095": ModelVariant(pv_reactive="fixed", pv_cosphi=0.95),
    "storage_greedy": ModelVariant(storage="greedy"),
    "storage_profile": ModelVariant(storage="profile_charging"),
    # outside the ensemble: MV voltage (SimBench's low-load / high-PV study case uses an LV
    # slack of 1.055 p.u.) alone and in a realistic joint, and an adverse loading joint
    "mv_high": ModelVariant(slack_vm_pu=1.055),
    "joint_realistic": ModelVariant(
        slack_vm_pu=1.055, pv_reactive="cosphi_p", pv_cosphi=0.90, storage="greedy"
    ),
    "joint_loading": ModelVariant(tap_steps=1, pv_reactive="fixed", pv_cosphi=0.95),
}
ENSEMBLE = (
    "tap_raise_lv",
    "tap_lower_lv",
    "pv_cosphi_p",
    "pv_fixed_095",
    "storage_greedy",
    "storage_profile",
)
TRUTHS = ("nominal", *VARIANTS)
INFORMATION = ("perfect", "forecast")
FIRST_REPLAY_DAY = FIRST_DECISION_DAY - REPLAY_DAYS
LAST_DAY = 364  # 2016-12-30, the last complete UTC day
SETS = {"nominal": 30, "variant": 2}  # injection sets per decision day
SHARED_PV_PROFILES = ("1-LV-semiurb4--2-sw", "1-LV-semiurb5--2-sw", "1-LV-urban6--2-sw")
NEW_PV_PROFILES = ("1-LV-rural2--2-sw", "1-LV-rural3--2-sw")
MATERIAL_CHANGE = 0.10  # a variant is material if it changes development violations >= 10 %


def physics_tasks() -> dict[str, list[tuple[int, int]]]:
    """(day, number of sets) per model: the nominal model's realised set from the first
    replay day, its 30 sets on decision days; each variant's realised and forecast sets."""
    nominal = [(d, 1) for d in range(FIRST_REPLAY_DAY, FIRST_DECISION_DAY)]
    nominal += [(d, SETS["nominal"]) for d in range(FIRST_DECISION_DAY, LAST_DAY + 1)]
    variant = [(d, SETS["variant"]) for d in range(FIRST_DECISION_DAY, LAST_DAY + 1)]
    return {"nominal": nominal, **{name: variant for name in VARIANTS}}


def compute_all_physics(cache_dir: Path, networks, workers: int | None = None) -> dict:
    provenance = {}
    for code in networks:
        for name, tasks in physics_tasks().items():
            variant = NOMINAL if name == "nominal" else VARIANTS[name]
            provenance[f"{code}/{name}"] = compute_physics(
                code, pv_scale(code), name, variant, tasks, cache_dir, workers
            )
    return provenance


def load_network_margins(cache_dir: Path, code: str) -> tuple[dict, dict]:
    """Normalised margins of the nominal model and of every variant of one network, after
    checking each folder's manifest and every array's number of injection sets."""
    norm, norm_v = {}, {}
    for name, tasks in physics_tasks().items():
        variant = NOMINAL if name == "nominal" else VARIANTS[name]
        raw = load_margins(cache_dir, code, name, [d for d, _ in tasks], pv_scale(code), variant)
        for day, n_sets in tasks:
            if raw[day].shape[0] != n_sets:
                raise ValueError(
                    f"{code}/{name} day {day}: {raw[day].shape[0]} sets, expected {n_sets}"
                )
        target = norm if name == "nominal" else norm_v.setdefault(name, {})
        target.update({day: normalised(m) for day, m in raw.items()})
    return norm, norm_v


def analyse_network(
    norm: dict, norm_v: dict, available: np.ndarray, rating: np.ndarray, period: str,
    online: OnlineSettings,
) -> dict:  # fmt: skip
    """All cells, summaries, risk diagnostics and the materiality of each variant for one
    network (normalised margins as returned by `load_network_margins`)."""
    days = [d for d in grid_study.period_days(period) if FIRST_DECISION_DAY <= d <= LAST_DAY]
    development = [
        d for d in grid_study.period_days("development") if FIRST_DECISION_DAY <= d <= LAST_DAY
    ]
    cells, rows = {}, []
    for information in INFORMATION:
        for truth in TRUTHS:
            records, tuned = run_cell(
                norm, norm_v, truth, ENSEMBLE, information, available, rating, development,
                days, online,
            )  # fmt: skip
            summary = summarise_cell(records, online)
            summary["tuned_on_development"] = tuned
            cells[f"{information}/{truth}"] = summary
            rows += [{"information": information, "truth": truth, **r} for r in records]
    diagnostics = {}
    for truth in TRUTHS:
        source = norm if truth == "nominal" else norm_v[truth]
        diagnostics[truth] = risk_diagnostics(norm, {d: source[d][REALISED] for d in days}, days)
    nominal_dev = sum(
        int(((norm[d][REALISED][:, 0] > 0) & daylight_of(available[d])).sum()) for d in development
    )
    materiality = {}
    for name in VARIANTS:
        count = sum(
            int(((norm_v[name][d][REALISED][:, 0] > 0) & daylight_of(available[d])).sum())
            for d in development
        )
        materiality[name] = {
            "development_no_action_violations": count,
            "nominal_development_no_action_violations": nominal_dev,
            "material": abs(count - nominal_dev) >= MATERIAL_CHANGE * max(nominal_dev, 1),
        }
    return {"cells": cells, "diagnostics": diagnostics, "materiality": materiality, "rows": rows}


def run_dual_study(period: str, cache_dir: Path, networks, online: OnlineSettings) -> dict:
    """Decisions, summaries, risk diagnostics and hypothesis checks for every network, from
    cached physics (see `compute_all_physics`)."""
    summaries, diagnostics, materiality, rows = {}, {}, {}, []
    for code in networks:
        net = variant_network(code, NOMINAL, pv_scale(code))
        available = grid_study.daily_arrays(absolute_profiles(net))["sgen_p_mw"]
        rating = net.sgen["sn_mva"].to_numpy(dtype=float)
        norm, norm_v = load_network_margins(cache_dir, code)
        result = analyse_network(norm, norm_v, available, rating, period, online)
        summaries[code] = {"pv_scale": pv_scale(code), "cells": result["cells"]}
        diagnostics[code] = result["diagnostics"]
        materiality[code] = result["materiality"]
        rows += [{"network": code, **r} for r in result["rows"]]
    new = [code for code in networks if code != DEVELOPMENT_NETWORK]
    hypotheses = evaluate_hypotheses(summaries, diagnostics, materiality, new) if new else None
    return {
        "summaries": summaries,
        "diagnostics": diagnostics,
        "materiality": materiality,
        "hypotheses": hypotheses,
        "rows": rows,
    }


# --- Registered hypothesis checks (protocol s. 4.8 with amendment 4A) ----------------

OUT_OF_ENSEMBLE = tuple(v for v in VARIANTS if v not in ENSEMBLE)


def better(cell: dict, a: str, b: str) -> bool:
    """Amendment 4A: `a` is better than `b` if
    - it meets the requirement, `b` does not, and the per-day avoidable-violation interval
      of (a - b) lies below 0; or
    - both meet it and the per-day curtailment interval of (a - b) lies below 0."""
    meets_a, meets_b = cell["totals"][a]["meets_beta"], cell["totals"][b]["meets_beta"]
    paired = cell["paired_per_day"]

    def below_zero(metric: str) -> bool:
        if f"{a}_minus_{b}" in paired:
            return paired[f"{a}_minus_{b}"][metric]["ci_high"] < 0
        return paired[f"{b}_minus_{a}"][metric]["ci_low"] > 0  # (a - b) < 0

    if meets_a and not meets_b:
        return below_zero("avoidable_violation_steps")
    if meets_a and meets_b:
        return below_zero("curtailed_mwh")
    return False


def _h3(summaries: dict, materiality: dict, networks: list[str]) -> dict:
    result = {}
    for a in AWARE:
        per_network = {}
        for code in networks:
            cells = summaries[code]["cells"]
            nominal = cells["forecast/nominal"]
            material = [t for t in VARIANTS if materiality[code][t]["material"]]
            usable = [t for t in material if not cells[f"forecast/{t}"]["excluded"]]
            wins = [t for t in usable if all(better(cells[f"forecast/{t}"], a, b) for b in SIMPLE)]
            per_network[code] = {
                "nominal_better_than_all_simple": not nominal["excluded"]
                and all(better(nominal, a, b) for b in SIMPLE),
                "material_mismatch_cells": material,
                "excluded_cells": [t for t in material if t not in usable],
                "wins": wins,
                "mismatch_criterion": bool(usable) and len(wins) >= int(np.ceil(len(usable) / 2)),
            }
        nominal_count = sum(v["nominal_better_than_all_simple"] for v in per_network.values())
        mismatch_count = sum(v["mismatch_criterion"] for v in per_network.values())
        result[a] = {
            "per_network": per_network,
            "nominal_networks": nominal_count,
            "mismatch_networks": mismatch_count,
            "genuine_value": nominal_count >= 3 and mismatch_count >= 3,
            "by_profile_group": {
                group: sum(
                    per_network[c]["nominal_better_than_all_simple"]
                    for c in codes
                    if c in per_network
                )
                for group, codes in (
                    ("new_pv_profiles", NEW_PV_PROFILES),
                    ("shared_pv_profiles", SHARED_PV_PROFILES),
                )
            },
        }
    simple_wins = {
        b: sum(
            all(better(summaries[c]["cells"]["forecast/nominal"], b, a) for a in AWARE)
            for c in networks
            if not summaries[c]["cells"]["forecast/nominal"]["excluded"]
        )
        for b in SIMPLE
    }
    genuine = any(result[a]["genuine_value"] for a in AWARE)
    refuted = any(n >= 3 for n in simple_wins.values())
    return {
        "aware": result,
        "simple_better_than_both_aware_networks": simple_wins,
        "verdict": "genuine value" if genuine else "refuted" if refuted else "inconclusive",
        "note": "two reliability-aware policies are assessed; a 'genuine value' verdict "
        "needs only one of them, which is a two-way multiplicity",
    }


def evaluate_hypotheses(summaries: dict, diagnostics: dict, materiality: dict, networks) -> dict:
    """Apply the registered decision criteria of H1-H4 and D1 to the new networks."""
    result = {"networks": list(networks)}
    h1 = {}
    for code in networks:
        d = diagnostics[code]["nominal"]
        h1[code] = {
            "informative": d["replay"]["violation_days"] >= 8,
            "a_in_sample_ratio_above_1_5": all(
                d[e]["realised_over_in_sample"]["estimate"] > 1.5 for e in ("scenario", "replay")
            ),
            "b_replay_loo_ratio_in_band": 2 / 3
            <= d["replay"]["realised_over_leave_one_out"]["estimate"]
            <= 1.5,
            "b_scenario_loo_ratio_in_band": 2 / 3
            <= d["scenario"]["realised_over_leave_one_out"]["estimate"]
            <= 1.5,
        }
    informative = [c for c in networks if h1[c]["informative"]]
    if len(informative) < 3:
        verdict = "untestable"
    elif all(
        h1[c]["a_in_sample_ratio_above_1_5"] and h1[c]["b_replay_loo_ratio_in_band"]
        for c in informative
    ):
        verdict = "supported"
    else:
        verdict = "not supported"
    result["H1"] = {"per_network": h1, "informative_networks": len(informative), "verdict": verdict}
    h2 = {}
    for code in networks:
        pair = summaries[code]["cells"]["forecast/nominal"]["paired_per_day"][
            "scenario_aci_minus_replay_aci"
        ]
        v, e = pair["avoidable_violation_steps"], pair["curtailed_mwh"]
        h2[code] = bool(
            (v["ci_high"] < 0 and e["ci_low"] <= 0) or (e["ci_high"] < 0 and v["ci_low"] <= 0)
        )
    result["H2"] = {
        "forecast_adds_value": h2,
        "networks_with_value": sum(h2.values()),
        "prediction": "at most 1 network",
    }
    result["H3"] = _h3(summaries, materiality, list(networks))

    def fails(info: str, truth: str, policy: str, code: str) -> bool:
        cell = summaries[code]["cells"][f"{info}/{truth}"]
        return not cell["excluded"] and not cell["totals"][policy]["meets_beta"]

    result["H4"] = {
        "a_point_F0_fails_per_network": {
            c: sum(fails("perfect", t, "point", c) for t in VARIANTS) for c in networks
        },
        "b_ensemble_F0_in_ensemble_fails_per_network": {
            c: sum(fails("perfect", t, "ensemble", c) for t in ENSEMBLE) for c in networks
        },
        "c_out_of_ensemble_F0": {
            "ensemble_fails": sum(
                fails("perfect", t, "ensemble", c) for c in networks for t in OUT_OF_ENSEMBLE
            ),
            "point_aci_fails": sum(
                fails("perfect", t, "point_aci", c) for c in networks for t in OUT_OF_ENSEMBLE
            ),
        },
        "c_out_of_ensemble_F1": {
            "ensemble_fails": sum(
                fails("forecast", t, "ensemble", c) for c in networks for t in OUT_OF_ENSEMBLE
            ),
            "replay_aci_fails": sum(
                fails("forecast", t, "replay_aci", c) for c in networks for t in OUT_OF_ENSEMBLE
            ),
        },
        "cells_per_information": len(networks) * len(OUT_OF_ENSEMBLE),
    }

    def violations(info: str, truth: str, code: str) -> float:
        return summaries[code]["cells"][f"{info}/{truth}"]["totals"]["point"][
            "avoidable_violation_steps"
        ]

    result["D1_point_interaction"] = {
        c: {
            t: violations("forecast", t, c) - violations("forecast", "nominal", c)
            - violations("perfect", t, c) + violations("perfect", "nominal", c)
            for t in VARIANTS
        }
        for c in networks
    }  # fmt: skip
    return result
