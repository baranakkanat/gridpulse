"""Phase 5: grid decisions under limited measurement availability (docs/phase5_protocol.md).

Three kinds of information are kept apart:

- ground truth: the full AC state of the true grid (`fullstate` cache) and its margins
  (Phase 4 cache). Only `measure`, `true_events` and the scoring functions read it;
- observations: what the sensors of a configuration report, with noise, missing days and
  reporting delay (`measure`, `observed_feedback`);
- decisions: day-ahead caps from the nominal planning model and past measured injections
  (as in Phase 4), corrected online only by *observed* violations.

Units: voltage magnitude in p.u. of nominal; line and transformer loading in % of rating
(a current measurement); transformer power in MW / MVAr at its LV terminal, positive
from the LV busbar into the transformer (reverse flow).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import networkx as nx
import numpy as np
import pandas as pd

from gridpulse import dual_study as ds
from gridpulse import grid_study
from gridpulse.grid_study import FIRST_DECISION_DAY, STEPS
from gridpulse.uncertainty import block_bootstrap_mean

# --- Network layout and sensor configurations --------------------------------------


@dataclass(frozen=True)
class Layout:
    """What a utility knows about where things are (no state information).

    `buses` are the LV buses in the column order of the `fullstate` arrays."""

    buses: tuple[int, ...]
    max_vm: tuple[float, ...]  # upper voltage limit per LV bus, p.u.
    customer_buses: tuple[int, ...]  # buses with a load or a PV unit (meter locations)
    lv_busbar: int
    feeder_heads: tuple[int, ...]  # line indices attached to the LV busbar
    feeder_of: dict  # bus -> feeder head line index
    distance: dict  # bus -> resistance distance from the LV busbar, ohm


def network_layout(net) -> Layout:
    """Topology facts of a network as a utility's asset register would hold them."""
    slack = set(net.ext_grid["bus"])
    buses = tuple(int(b) for b in sorted(set(net.bus.index) - slack))
    busbar = int(net.trafo["lv_bus"].iloc[0])
    graph = nx.Graph()
    for i, line in net.line.iterrows():
        resistance = line["r_ohm_per_km"] * line["length_km"] / max(line["parallel"], 1)
        graph.add_edge(int(line["from_bus"]), int(line["to_bus"]), r=resistance, line=int(i))
    distance = nx.single_source_dijkstra_path_length(graph, busbar, weight="r")
    paths = nx.single_source_dijkstra_path(graph, busbar, weight="r")
    heads = tuple(
        sorted(int(i) for i, ln in net.line.iterrows() if busbar in (ln["from_bus"], ln["to_bus"]))
    )
    feeder_of = {
        b: graph.edges[path[0], path[1]]["line"] for b, path in paths.items() if len(path) > 1
    }
    customers = sorted(set(net.load["bus"]) | set(net.sgen["bus"]))
    return Layout(
        buses=buses,
        max_vm=tuple(float(v) for v in net.bus.loc[list(buses), "max_vm_pu"]),
        customer_buses=tuple(int(b) for b in customers if b != busbar),
        lv_busbar=busbar,
        feeder_heads=heads,
        feeder_of={int(b): int(line) for b, line in feeder_of.items()},
        distance={int(b): float(d) for b, d in distance.items()},
    )


@dataclass(frozen=True)
class Config:
    """A measurement configuration: which quantities are reported, and where.

    - `transformer`: one device at the transformer's LV terminals reporting LV busbar
      voltage, transformer loading (current), P and Q;
    - `heads`: current (loading) of the listed feeder-head lines, measured in the
      substation;
    - `voltages`: remote bus voltage magnitudes (smart-meter-like sensors);
    - `lines`: further line currents (only the full-observability reference uses them);
    - `export_threshold_mw`: if set, a step also counts as a (model-inferred) violation
      when the measured transformer reverse flow exceeds it (see `export_threshold`).
    """

    name: str
    transformer: bool = False
    heads: tuple[int, ...] = ()
    voltages: tuple[int, ...] = ()
    lines: tuple[int, ...] = ()
    export_threshold_mw: float | None = None


def standard_configs(layout: Layout, n_lines: int) -> dict[str, Config]:
    """The fixed configurations of protocol s. 3 (placement-based ones are added later)."""
    return {
        "none": Config("none"),
        "transformer": Config("transformer", transformer=True),
        "substation": Config("substation", transformer=True, heads=layout.feeder_heads),
        "full": Config(
            "full", transformer=True, voltages=layout.buses, lines=tuple(range(n_lines))
        ),
    }


def with_remote(config: Config, buses, name: str) -> Config:
    """`config` plus remote voltage sensors at `buses`."""
    return Config(
        name, config.transformer, config.heads, tuple(buses), config.lines,
        config.export_threshold_mw,
    )  # fmt: skip


# --- Measurement model -------------------------------------------------------------


@dataclass(frozen=True)
class MeasurementModel:
    """Noise, missingness and delay of the sensors (values recorded in the protocol).

    Substation quantities (`transformer`, `heads`) are reported every quarter-hour without
    loss and are available at the next decision. Remote sensors report daily batches that
    can be missing (whole sensor-days, i.i.d.) and arrive `remote_delay_days` later than
    the substation data. Noise is Gaussian and independent per reading."""

    sigma_v_substation: float = 0.0  # p.u.
    sigma_v_remote: float = 0.0  # p.u.
    sigma_loading: float = 0.0  # relative (fraction of the reading)
    remote_missing: float = 0.0  # probability that a remote sensor-day is missing
    remote_delay_days: int = 0
    sigma_bias_remote: float = 0.0  # p.u.; fixed per meter (Phase 6 sensitivity only)


def _noisy(values: np.ndarray, sigma: float, rng, relative: bool = False) -> np.ndarray:
    if sigma == 0:
        return values
    scale = sigma * np.abs(values) if relative else sigma
    return values + rng.normal(0.0, 1.0, size=values.shape) * scale


def _stable_int(text: str) -> int:
    """A 64-bit integer from text that is the same in every process and on every platform
    (unlike Python's salted `hash`)."""
    return int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little")


class NoiseBank:
    """Measurement noise tied to the identity of the physical observation (Phase 6).

    A reading's standard-normal noise is a function of (network, truth, replication,
    quantity, sensor element, day, quarter-hour) only, and a remote sensor-day's
    missingness draw of (network, truth, replication, quantity, element, day). It does not
    depend on the configuration's name, on which other sensors are installed, on the
    applied caps, or on which days are simulated: shared sensors see common random numbers
    across configurations, policies and measurement conditions. A meter's calibration bias
    is a property of the device, so it depends on (network, replication, element) only.

    Quantities: `busbar_voltage`, `trafo_loading`, `trafo_p`, `trafo_q` (element 0, the
    transformer device), `line_current` (line index; feeder-head and other line sensors
    measure the same physical current), `meter_voltage` (bus index).

    Phase 5 used one random stream per run, seeded from the configuration name
    (`seed_of`): identical sensors received different noise (docs/phase5_results.md s. 11).
    That path is kept unchanged so the frozen Phase 5 results stay reproducible."""

    DAYS = 366  # day-of-year index of the 2016 profiles

    def __init__(self, network: str, truth: str, replication: int = 0) -> None:
        self.network, self.truth, self.replication = network, truth, int(replication)
        self._streams: dict = {}

    def _generator(self, *parts) -> np.random.Generator:
        entropy = [_stable_int(self.network), self.replication, *(_stable_int(p) for p in parts)]
        return np.random.default_rng(np.random.SeedSequence(entropy))

    def _stream(self, kind: str, quantity: str, element: int) -> np.ndarray:
        key = (kind, quantity, int(element))
        if key not in self._streams:
            if kind == "bias":
                gen = self._generator("bias", quantity, str(int(element)))
                self._streams[key] = gen.standard_normal()
            else:
                gen = self._generator(self.truth, kind, quantity, str(int(element)))
                shape = (self.DAYS, STEPS) if kind == "normal" else (self.DAYS,)
                draw = gen.standard_normal if kind == "normal" else gen.random
                self._streams[key] = draw(shape)
        return self._streams[key]

    def normal(self, quantity: str, elements, day: int) -> np.ndarray:
        """Standard-normal noise of day `day`, quarter-hours x elements."""
        return np.stack([self._stream("normal", quantity, e)[day] for e in elements], axis=1)

    def uniform(self, quantity: str, elements, day: int) -> np.ndarray:
        """One uniform draw per element for day `day` (sensor-day missingness)."""
        return np.array([self._stream("uniform", quantity, e)[day] for e in elements])

    def bias(self, quantity: str, elements) -> np.ndarray:
        """One standard-normal calibration offset per device (constant over time)."""
        return np.array([self._stream("bias", quantity, e) for e in elements])


def _measure_identified(
    state: dict, levels: np.ndarray, config: Config, layout: Layout, model, noise: NoiseBank,
    day: int,
) -> dict:  # fmt: skip
    """`measure` with noise from `noise` (observation identity, common random numbers)."""
    steps = np.arange(STEPS)
    column = {b: i for i, b in enumerate(layout.buses)}

    def noisy(values, sigma, quantity, elements, relative=False):
        if sigma == 0:
            return values
        scale = sigma * np.abs(values) if relative else sigma
        return values + noise.normal(quantity, elements, day) * scale

    out = {}
    if config.transformer:
        trafo = state["trafo"][steps, levels]
        sigma = model.sigma_loading
        out["trafo_loading"] = noisy(trafo[:, 2:3], sigma, "trafo_loading", (0,), True)
        out["busbar_vm"] = noisy(trafo[:, 3:4], model.sigma_v_substation, "busbar_voltage", (0,))
        out["trafo_p"] = noisy(trafo[:, 0:1], sigma, "trafo_p", (0,), True)
        out["trafo_q"] = noisy(trafo[:, 1:2], sigma, "trafo_q", (0,), True)
    if config.heads:
        heads = state["line"][steps, levels][:, list(config.heads)]
        out["head_loading"] = noisy(heads, model.sigma_loading, "line_current", config.heads, True)
    if config.lines:
        lines = state["line"][steps, levels][:, list(config.lines)]
        out["line_loading"] = noisy(lines, model.sigma_loading, "line_current", config.lines, True)
    if config.voltages:
        vm = state["vm"][steps, levels][:, [column[b] for b in config.voltages]]
        vm = noisy(vm, model.sigma_v_remote, "meter_voltage", config.voltages)
        if model.sigma_bias_remote:
            vm = vm + noise.bias("meter_voltage", config.voltages) * model.sigma_bias_remote
        out["remote_vm"] = vm
        available = noise.uniform("meter_voltage", config.voltages, day) >= model.remote_missing
        out["remote_available"] = available
    return out


def measure(
    state: dict, levels: np.ndarray, config: Config, layout: Layout, model, rng, *,
    noise: NoiseBank | None = None, day: int | None = None,
) -> dict:  # fmt: skip
    """Readings of `config` on one day whose caps were `levels` (96), from the true state.

    Returns per-quantity arrays (96 x sensors) plus `remote_available` (sensor mask). This
    is the only place where a decision-side quantity is derived from ground truth. With a
    `noise` bank (Phase 6) the noise of day `day` is tied to the observation identity;
    without one, `rng` is drawn in configuration order (Phase 5, kept for reproduction)."""
    if noise is not None:
        if day is None:
            raise ValueError("identity-based noise needs the day")
        return _measure_identified(state, levels, config, layout, model, noise, day)
    steps = np.arange(STEPS)
    column = {b: i for i, b in enumerate(layout.buses)}
    out = {}
    if config.transformer:
        trafo = state["trafo"][steps, levels]
        out["trafo_loading"] = _noisy(trafo[:, 2:3], model.sigma_loading, rng, relative=True)
        out["busbar_vm"] = _noisy(trafo[:, 3:4], model.sigma_v_substation, rng)
        out["trafo_p"] = _noisy(trafo[:, 0:1], model.sigma_loading, rng, relative=True)
        out["trafo_q"] = _noisy(trafo[:, 1:2], model.sigma_loading, rng, relative=True)
    if config.heads:
        heads = state["line"][steps, levels][:, list(config.heads)]
        out["head_loading"] = _noisy(heads, model.sigma_loading, rng, relative=True)
    if config.lines:
        lines = state["line"][steps, levels][:, list(config.lines)]
        out["line_loading"] = _noisy(lines, model.sigma_loading, rng, relative=True)
    if config.voltages:
        vm = state["vm"][steps, levels][:, [column[b] for b in config.voltages]]
        out["remote_vm"] = _noisy(vm, model.sigma_v_remote, rng)
        out["remote_available"] = rng.random(len(config.voltages)) >= model.remote_missing
    return out


@dataclass(frozen=True)
class AlarmRule:
    """How readings become violation alarms (Phase 6, docs/phase6_protocol.md).

    - `guard`: each limit is raised by `guard` standard uncertainties of that reading
      (voltage: the sensor's sigma in p.u., for meters including calibration bias; loading:
      `sigma_loading` x 100 %), a guarded decision rule in the sense of JCGM 106;
    - `persistence`: a sensor's exceedance counts only inside a run of at least this many
      consecutive quarter-hours of that sensor;
    - `scope`: "all" applies the rule to every reading; "meters" only to remote meter
      voltages, leaving substation readings unfiltered (amendment 6A).

    The Phase 5 rule is AlarmRule("unfiltered") (no guard, persistence 1)."""

    name: str
    guard: float = 0.0
    persistence: int = 1
    scope: str = "all"

    def __post_init__(self) -> None:
        if self.scope not in ("all", "meters") or self.persistence < 1 or self.guard < 0:
            raise ValueError(f"invalid alarm rule {self}")


def _persistent(over: np.ndarray, length: int) -> np.ndarray:
    """Exceedances (steps x sensors) that lie in a run of >= `length` consecutive steps."""
    if length <= 1:
        return over
    keep = np.zeros_like(over)
    for j in range(over.shape[1]):
        edges = np.diff(np.concatenate(([0], over[:, j].astype(int), [0])))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1), strict=True):
            if end - start >= length:
                keep[start:end, j] = True
    return keep


def flagged_steps(
    readings: dict, config: Config, layout: Layout, *, alarm: AlarmRule | None = None,
    model: MeasurementModel | None = None,
) -> tuple[np.ndarray, np.ndarray]:  # fmt: skip
    """Steps at which a reading shows a limit violation: (substation sensors, remote).

    Direct detection: voltage above the bus's limit, loading above 100 %. No inference.
    An `alarm` rule other than the Phase 5 one needs the measurement `model` (its sigmas)."""
    if alarm is not None and (alarm.guard != 0 or alarm.persistence != 1):
        return _flagged_with_rule(readings, config, layout, alarm, model)
    column = {b: i for i, b in enumerate(layout.buses)}
    sub = np.zeros(STEPS, dtype=bool)
    if "trafo_loading" in readings:
        sub |= readings["trafo_loading"][:, 0] > 100.0
        sub |= readings["busbar_vm"][:, 0] > layout.max_vm[column[layout.lv_busbar]]
        if config.export_threshold_mw is not None:
            sub |= readings["trafo_p"][:, 0] > config.export_threshold_mw
    if "head_loading" in readings:
        sub |= (readings["head_loading"] > 100.0).any(axis=1)
    if "line_loading" in readings:  # full-observability reference only
        sub |= (readings["line_loading"] > 100.0).any(axis=1)
    remote = np.zeros(STEPS, dtype=bool)
    if "remote_vm" in readings:
        limits = np.array([layout.max_vm[column[b]] for b in config.voltages])
        over = (readings["remote_vm"] > limits) & readings["remote_available"]
        remote = over.any(axis=1)
    return sub, remote


def _flagged_with_rule(
    readings: dict, config: Config, layout: Layout, alarm: AlarmRule, model: MeasurementModel
) -> tuple[np.ndarray, np.ndarray]:
    """`flagged_steps` under a guard band and/or persistence rule (same quantities)."""
    if model is None:
        raise ValueError("a guard or persistence rule needs the measurement model")
    if alarm.scope not in ("all", "meters"):
        raise ValueError(f"unknown alarm scope {alarm.scope!r}")
    column = {b: i for i, b in enumerate(layout.buses)}
    station = alarm.scope == "all"  # does the rule apply to substation readings?
    guard_station = alarm.guard if station else 0.0
    loading_limit = 100.0 * (1.0 + guard_station * model.sigma_loading)

    def over(values, limit, rule_applies=station):
        return _persistent(values > limit, alarm.persistence if rule_applies else 1)

    sub = np.zeros(STEPS, dtype=bool)
    if "trafo_loading" in readings:
        sub |= over(readings["trafo_loading"], loading_limit).any(axis=1)
        busbar_limit = layout.max_vm[column[layout.lv_busbar]]
        busbar_limit += guard_station * model.sigma_v_substation
        sub |= over(readings["busbar_vm"], busbar_limit).any(axis=1)
        if config.export_threshold_mw is not None:
            sub |= readings["trafo_p"][:, 0] > config.export_threshold_mw
    if "head_loading" in readings:
        sub |= over(readings["head_loading"], loading_limit).any(axis=1)
    if "line_loading" in readings:
        sub |= over(readings["line_loading"], loading_limit).any(axis=1)
    remote = np.zeros(STEPS, dtype=bool)
    if "remote_vm" in readings:
        limits = np.array([layout.max_vm[column[b]] for b in config.voltages])
        # the meter's total standard uncertainty: the operator knows the accuracy class,
        # not the individual calibration offset
        uncertainty = float(np.hypot(model.sigma_v_remote, model.sigma_bias_remote))
        exceed = over(readings["remote_vm"], limits + alarm.guard * uncertainty, True)
        exceed &= readings["remote_available"]
        remote = exceed.any(axis=1)
    return sub, remote


# --- Ground-truth events (evaluator only) ------------------------------------------


def true_events(truth_norm: np.ndarray, state: dict, level: int, layout: Layout) -> dict:
    """Avoidable true violations at cap `level` per step, in total and by type.

    `truth_norm` is the true grid's normalised margin (96 x levels, Phase 4); a violation
    is avoidable if some cap level is safe at that step."""
    avoidable = (truth_norm <= 0).any(axis=1)
    violated = (truth_norm[:, level] > 0) & avoidable
    limits = np.array(layout.max_vm)
    return {
        "any": violated,
        "voltage": violated & (state["vm"][:, level] > limits).any(axis=1),
        "line": violated & (state["line"][:, level] > 100.0).any(axis=1),
        "trafo": violated & (state["trafo"][:, level, 2] > 100.0),
    }


# --- Sensor placement (development data only) --------------------------------------


def place_random(layout: Layout, k: int, seed: int) -> tuple[int, ...]:
    rng = np.random.default_rng(seed)
    return tuple(int(b) for b in rng.choice(layout.customer_buses, size=k, replace=False))


def place_mandatory(layout: Layout, k: int, pv_by_bus: dict) -> tuple[int, ...]:
    """German rollout practice (FNN 2025): smart meters first where PV is installed; here
    the k buses with the largest installed PV (MW), ties by bus index."""
    ranked = sorted(layout.customer_buses, key=lambda b: (-pv_by_bus.get(b, 0.0), b))
    return tuple(ranked[:k])


def place_topology(layout: Layout, k: int) -> tuple[int, ...]:
    """Feeder ends first: the electrically farthest customer bus of each feeder, feeders
    ordered by that distance, then the next farthest per feeder, round robin."""
    by_feeder: dict[int, list[int]] = {}
    for b in sorted(layout.customer_buses, key=lambda b: (-layout.distance[b], b)):
        by_feeder.setdefault(layout.feeder_of[b], []).append(b)
    order = sorted(by_feeder.values(), key=lambda bs: (-layout.distance[bs[0]], bs[0]))
    chosen: list[int] = []
    for rank in range(max(len(bs) for bs in order)):
        for bs in order:
            if rank < len(bs) and len(chosen) < k:
                chosen.append(bs[rank])
    return tuple(chosen)


def place_risk(layout: Layout, k: int, states: dict, development) -> tuple[int, ...]:
    """Buses with the most development overvoltage steps at no action (nominal model);
    ties and remaining slots by the topology order."""
    limits = np.array(layout.max_vm)
    column = {b: i for i, b in enumerate(layout.buses)}
    counts = sum((states[d]["vm"][:, 0] > limits).sum(axis=0) for d in development)
    fallback = {b: i for i, b in enumerate(place_topology(layout, len(layout.customer_buses)))}
    ranked = sorted(layout.customer_buses, key=lambda b: (-counts[column[b]], fallback[b]))
    return tuple(ranked[:k])


def greedy(candidates, k: int, objective) -> tuple[int, ...]:
    """Add, k times, the candidate with the smallest objective(chosen + [candidate]);
    scores may be tuples (compared lexicographically); ties go to the earlier candidate."""
    chosen: list[int] = []
    for _ in range(k):
        remaining = [c for c in candidates if c not in chosen]
        scores = [objective(tuple(chosen + [c])) for c in remaining]
        chosen.append(remaining[min(range(len(scores)), key=scores.__getitem__)])
    return tuple(chosen)


# --- Detection study ----------------------------------------------------------------


def detection_counts(
    days, states: dict, truth_norm: dict, config: Config, layout: Layout, model, seed: int,
    available: np.ndarray, *, noise: NoiseBank | None = None, alarm=None,
) -> np.ndarray:  # fmt: skip
    """Per day (rows): TP, FP, FN, TN of direct detection of avoidable violations at no
    action on daylight steps, plus TP/positives by type (voltage, line, trafo)."""
    rng = np.random.default_rng(seed)
    rows = []
    for day in days:
        daylight = available[day].sum(axis=1) > 0
        readings = measure(
            states[day], np.zeros(STEPS, dtype=int), config, layout, model, rng, noise=noise,
            day=day,
        )  # fmt: skip
        sub, remote = flagged_steps(readings, config, layout, alarm=alarm, model=model)
        flagged = (sub | remote) & daylight
        events = true_events(truth_norm[day], states[day], 0, layout)
        actual = events["any"] & daylight
        row = [
            (flagged & actual).sum(),
            (flagged & ~actual).sum(),
            (~flagged & actual).sum(),
            (~flagged & ~actual & daylight).sum(),
        ]
        for kind in ("voltage", "line", "trafo"):
            positives = events[kind] & daylight
            row += [(flagged & positives).sum(), positives.sum()]
        rows.append(row)
    return np.array(rows, dtype=float)


# --- Decisions with observed feedback ------------------------------------------------


@dataclass(frozen=True)
class DecisionContext:
    """Everything one (network, truth) decision run needs. `plan_norm` is the nominal
    planning model (Phase 4 cache, normalised); `truth_norm` and `states` are ground
    truth, used only for scoring and to generate readings."""

    plan_norm: dict
    truth_norm: dict
    states: dict
    available: np.ndarray
    rating: np.ndarray
    layout: Layout
    development: tuple[int, ...]
    days: tuple[int, ...]
    nominal_states: dict | None = None  # nominal model at the realised injections
    trafo_mva: float = 1.0
    pv_by_bus: dict | None = None  # installed PV per bus (asset register), MW


# Model-consistency test (protocol s. 6): thresholds fixed from physics, not tuned. One
# 2.5 % tap step moves the LV voltage by about 0.025 p.u.; 0.005 p.u. is a fifth of it.
CONSISTENCY_V = 0.005  # |daily mean busbar-voltage residual|, p.u.
CONSISTENCY_Q = 0.02  # |daylight mean transformer-Q residual| / transformer rating


def consistency_residuals(readings: dict, nominal_state: dict, levels, daylight, trafo_mva):
    """Substation readings minus the nominal model's prediction for the same day and caps
    (given the metered injections): mean busbar-voltage residual (p.u.) and daylight-mean
    reactive-power residual (fraction of the transformer rating)."""
    predicted = nominal_state["trafo"][np.arange(STEPS), levels]
    dv = float(np.mean(readings["busbar_vm"][:, 0] - predicted[:, 3]))
    dq = readings["trafo_q"][:, 0] - predicted[:, 1]
    dq = float(np.mean(dq[daylight]) / trafo_mva) if daylight.any() else 0.0
    return dv, dq


def run_feedback_policy(
    ctx: DecisionContext, policy: str, config: Config, model: MeasurementModel, seed: int,
    online: ds.OnlineSettings, detector=None, *, noise: NoiseBank | None = None, alarm=None,
) -> list[dict]:  # fmt: skip
    """Run one policy day by day from the first decision day; return records of the scored
    days.

    Policies: `replay_aci` (Phase 4 replay rule, margin tau corrected online), `static_aci`
    (cap level corrected online), and the open-loop references `static_dev`,
    `replay_robust` and `oracle` (truth; unattainable). The online correction after day d
    counts daylight steps flagged by the substation sensors on day d and by remote sensors
    on day d - remote_delay_days (each step counted once), i.e. only observed violations.
    `detector(day, levels, readings)` may replace direct detection (e.g. state-estimation
    based inference, `estimation.se_detector`); it sees only the readings.
    """
    rng = np.random.default_rng(seed)
    tuned = ds.tune_on_development(
        ctx.plan_norm, "forecast", ctx.available, list(ctx.development), online
    )
    tau, level_index = 0.0, float(tuned["static_beta_level"])
    pending: dict[int, np.ndarray] = {}  # day -> remote-only flagged steps (not yet seen)
    inconsistent = False  # model-consistency flag from the previous day's readings
    # decisions after the last scored day cannot affect any record; a development run
    # therefore never simulates evaluation days
    last = max(ctx.days)
    decision_days = sorted(d for d in ctx.plan_norm if FIRST_DECISION_DAY <= d <= last)
    records = []
    for day in decision_days:
        if policy in ("replay_aci", "replay_robust"):
            replay = np.stack(
                [ctx.plan_norm[j][ds.REALISED] for j in range(day - ds.REPLAY_DAYS, day)]
            ).max(axis=0)
            margin = tau if policy == "replay_aci" else 0.0
            levels = ds.first_safe(replay, margin)
            no_feasible = bool((~(replay <= -margin).any(axis=1)).any())
        elif policy == "static_aci":
            levels = np.full(STEPS, int(np.floor(level_index + 0.5)))
        elif policy == "static_dev":
            levels = np.full(STEPS, tuned["static_dev_level"])
        elif policy == "oracle":
            levels = ds.first_safe(ctx.truth_norm[day])
        else:
            raise ValueError(f"unknown policy {policy!r}")
        if policy not in ("replay_aci", "replay_robust"):
            no_feasible = False
        daylight = ctx.available[day].sum(axis=1) > 0
        readings = measure(
            ctx.states[day], levels, config, ctx.layout, model, rng, noise=noise, day=day
        )
        if detector is None:
            sub, remote = flagged_steps(readings, config, ctx.layout, alarm=alarm, model=model)
        else:
            sub, remote = detector(day, levels, readings)
        pending[day] = remote & ~sub & daylight
        late = pending.pop(day - model.remote_delay_days, np.zeros(STEPS, dtype=bool))
        observed = int((sub & daylight).sum()) + int(late.sum())
        if day in ctx.days:
            result = ds.score(ctx.truth_norm[day], levels, ctx.available[day], ctx.rating)
            events = true_events(ctx.truth_norm[day], ctx.states[day], 0, ctx.layout)
            needed = bool((events["any"] & daylight).any())
            # scoring-side bookkeeping (never read by the controller): the day's own alarms
            # against the true violations of the applied schedule
            violated = ctx.truth_norm[day][np.arange(STEPS), levels] > 0
            flagged = (sub | remote) & daylight
            records.append(
                {
                    "day": day,
                    **result,
                    "observed_feedback": observed,
                    "tau": tau,
                    "level_index": level_index,
                    "unneeded_curtailment_mwh": 0.0 if needed else result["curtailed_mwh"],
                    "no_feasible_action": no_feasible,
                    "model_inconsistency": inconsistent,  # known at the decision time
                    "flagged_steps": int(flagged.sum()),
                    "false_alarm_steps": int((flagged & ~violated).sum()),
                    "missed_steps": int((~flagged & violated & daylight).sum()),
                    "intervention_steps": int(((levels > 0) & daylight).sum()),
                }
            )
        if ctx.nominal_states is not None and config.transformer:
            dv, dq = consistency_residuals(
                readings, ctx.nominal_states[day], levels, daylight, ctx.trafo_mva
            )
            inconsistent = abs(dv) > CONSISTENCY_V or abs(dq) > CONSISTENCY_Q
        if policy == "replay_aci":
            tau = float(
                np.clip(
                    tau + online.gamma * (observed - online.beta), online.tau_min, online.tau_max
                )
            )
        elif policy == "static_aci":
            level_index = float(
                np.clip(
                    level_index + online.gamma_level * (observed - online.beta), 0, ds.LAST_LEVEL
                )
            )
    return records


def decision_timing(day: int, model: MeasurementModel) -> dict:
    """Timing record of the day-ahead decision for `day` (UTC): decided at 00:00 of the
    day, from substation data up to the end of the previous day and remote data up to
    `remote_delay_days` earlier; actions take effect at each quarter-hour of the day."""
    origin = grid_study.FIRST_DAY + pd.Timedelta(days=int(day))
    latest_substation = origin - pd.Timedelta(minutes=15)
    latest_remote = latest_substation - pd.Timedelta(days=model.remote_delay_days)
    return {
        "decision_timestamp": origin.isoformat(),
        "forecast_origin": origin.isoformat(),
        "latest_substation_measurement": latest_substation.isoformat(),
        "latest_remote_measurement": latest_remote.isoformat(),
        "remote_measurement_age_hours": (origin - latest_remote).total_seconds() / 3600,
        "first_action_effective": origin.isoformat(),
        "last_action_effective": (origin + pd.Timedelta(minutes=15 * (STEPS - 1))).isoformat(),
    }


# --- Registered design (protocol s. 3-7) ---------------------------------------------

BUDGETS = (1, 2, 4)  # remote voltage sensors added to the substation configuration
RULES = ("mandatory", "topology", "risk", "greedy_detect", "decision_aware")
RANDOM_SEEDS = tuple(range(20))
DESIGN_TRUTHS = ("nominal", "tap_raise_lv", "pv_fixed_095")  # decision-aware design only
COVERAGE_MIN = 0.8  # development recall below this: INSUFFICIENT_EVIDENCE
# Protocol s. 5 (values from docs/phase5_literature.md): substation voltage 0.2 %, current
# and power 1 %, smart-meter voltage 1 %, 5 % of remote sensor-days lost, smart-meter data
# delivered the next day (German metering law: daily, for the previous day).
CONDITIONS = {
    "ideal": MeasurementModel(),
    "realistic": MeasurementModel(
        sigma_v_substation=0.002, sigma_v_remote=0.01, sigma_loading=0.01,
        remote_missing=0.05, remote_delay_days=1,
    ),
    "noise_only": MeasurementModel(
        sigma_v_substation=0.002, sigma_v_remote=0.01, sigma_loading=0.01
    ),
    "missing_only": MeasurementModel(remote_missing=0.05),
    "delay_only": MeasurementModel(remote_delay_days=1),
    "precise_meters": MeasurementModel(
        sigma_v_substation=0.002, sigma_v_remote=0.002, sigma_loading=0.01,
        remote_missing=0.05, remote_delay_days=1,
    ),
}  # fmt: skip
PRIMARY = "realistic"


def export_threshold(nominal_states: dict, nominal_norm: dict, available, layout, days) -> float:
    """Model-based inference rule: the smallest transformer reverse flow (MW) at which the
    nominal model shows an avoidable violation on a development daylight step at no
    action. Above it, a measured reverse flow is read as 'violation likely'."""
    exports = []
    for day in days:
        events = true_events(nominal_norm[day], nominal_states[day], 0, layout)
        daylight = available[day].sum(axis=1) > 0
        mask = events["any"] & daylight
        exports += list(nominal_states[day]["trafo"][:, 0, 0][mask])
    return float(min(exports)) if exports else float("inf")


def seed_of(*parts) -> int:
    """A reproducible seed from the run identity (network, truth, condition, config)."""
    return int(np.frombuffer(repr(parts).encode(), dtype=np.uint8).sum() * 7919 % 2**31)


def design_placements(ctx_by_truth: dict, layout: Layout, online) -> dict:
    """Sensor sets of every rule and budget, from development days only (protocol s. 4).

    Nested by construction: the k = 1 set is contained in k = 2, which is in k = 4."""
    k_max = max(BUDGETS)
    base = Config("substation", transformer=True, heads=layout.feeder_heads)
    nominal = ctx_by_truth["nominal"]
    dev = list(nominal.development)
    model = CONDITIONS["ideal"]
    placements = {
        "mandatory": place_mandatory(layout, k_max, nominal.pv_by_bus),
        "topology": place_topology(layout, k_max),
    }
    placements["risk"] = place_risk(layout, k_max, nominal.states, dev)

    def detected(buses) -> float:
        config = with_remote(base, buses, "candidate")
        counts = detection_counts(
            dev, nominal.states, nominal.truth_norm, config, layout, model, 0, nominal.available
        )
        return -counts[:, 0].sum()  # more true positives is better

    # candidates in topology order, so ties (flat objectives) fall back to feeder ends
    # rather than to bus numbering (amendment 5B)
    candidates = place_topology(layout, len(layout.customer_buses))
    placements["greedy_detect"] = greedy(candidates, k_max, detected)

    def decision_loss(buses) -> tuple:
        config = with_remote(base, buses, "candidate")
        excess, curtailed = 0.0, 0.0
        for truth in DESIGN_TRUTHS:
            ctx = ctx_by_truth[truth]
            dev_ctx = DecisionContext(
                plan_norm={d: m for d, m in ctx.plan_norm.items() if d <= max(dev)},
                truth_norm=ctx.truth_norm, states=ctx.states, available=ctx.available,
                rating=ctx.rating, layout=layout, development=ctx.development,
                days=ctx.development,
            )  # fmt: skip
            records = run_feedback_policy(dev_ctx, "replay_aci", config, model, 0, online)
            per_day = np.mean([r["avoidable_violation_steps"] for r in records])
            excess += max(0.0, per_day - online.beta)
            curtailed += sum(r["curtailed_mwh"] for r in records)
        return (round(excess, 9), curtailed)

    placements["decision_aware"] = greedy(candidates, k_max, decision_loss)
    for seed in RANDOM_SEEDS:
        placements[f"random_{seed}"] = place_random(layout, k_max, seed)
    return placements


def placement_configs(layout: Layout, placements: dict, threshold: float) -> dict[str, Config]:
    """Every configuration evaluated: the standard ones, the export-proxy rule, and the
    substation plus k remote voltage sensors for every placement rule."""
    configs = {name: c for name, c in standard_configs(layout, 0).items() if name != "full"}
    base = configs["substation"]
    configs["substation_proxy"] = Config(
        "substation_proxy", True, layout.feeder_heads, export_threshold_mw=threshold
    )
    for rule, buses in placements.items():
        for k in BUDGETS:
            name = f"substation+{k}:{rule}"
            configs[name] = with_remote(base, buses[:k], name)
    return configs


def summarise_detection(rows: np.ndarray) -> dict:
    """Confusion counts, precision, recall (with a day-block bootstrap interval), false-
    alarm and missed-violation rates, and recall by violation type."""
    tp, fp, fn, tn = rows[:, :4].sum(axis=0)
    out = {
        "tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn),
        "precision": float(tp / (tp + fp)) if tp + fp else None,
        "recall": float(tp / (tp + fn)) if tp + fn else None,
        "false_alarm_rate": float(fp / (fp + tn)) if fp + tn else None,
        "missed_violation_rate": float(fn / (tp + fn)) if tp + fn else None,
        "violation_days": int((rows[:, 0] + rows[:, 2] > 0).sum()),
    }  # fmt: skip
    if tp + fn:
        out["recall_ci"] = block_bootstrap_ratio(rows[:, 0], rows[:, 0] + rows[:, 2])
    for i, kind in enumerate(("voltage", "line", "trafo")):
        hit, positives = rows[:, 4 + 2 * i].sum(), rows[:, 5 + 2 * i].sum()
        out[f"recall_{kind}"] = float(hit / positives) if positives else None
        out[f"positives_{kind}"] = int(positives)
    return out


def block_bootstrap_ratio(numerator: np.ndarray, denominator: np.ndarray) -> dict:
    """95 % circular 7-day block bootstrap interval of sum(numerator)/sum(denominator)."""
    table = np.stack([numerator, denominator], axis=1).astype(float)

    def ratio(x):
        return x[:, 0].sum() / x[:, 1].sum() if x[:, 1].sum() else np.nan

    replicates = []
    n = len(table)
    rng = np.random.default_rng(42)
    starts = rng.integers(0, n, size=(2000, int(np.ceil(n / 7))))
    index = ((starts[:, :, None] + np.arange(7)) % n).reshape(2000, -1)[:, :n]
    for rows in index:
        replicates.append(ratio(table[rows]))
    replicates = np.array(replicates)
    replicates = replicates[np.isfinite(replicates)]
    low, high = np.quantile(replicates, [0.025, 0.975]) if len(replicates) else (np.nan, np.nan)
    return {"estimate": float(ratio(table)), "ci_low": float(low), "ci_high": float(high)}


def summarise_decisions(records: list[dict], online) -> dict:
    """Totals of one decision run (scored days only)."""
    days = len(records)
    total = {key: float(sum(r[key] for r in records)) for key in (
        "avoidable_violation_steps", "violation_steps", "severity", "severe_steps",
        "long_runs", "curtailed_mwh", "unneeded_curtailment_mwh", "observed_feedback",
    )}  # fmt: skip
    per_day = total["avoidable_violation_steps"] / days
    return {
        **total,
        "violation_steps_per_day": per_day,
        "meets_beta": bool(per_day <= online.beta),
        "missed_violation_steps": total["avoidable_violation_steps"],
        "days_with_violation": int(sum(r["avoidable_violation_steps"] > 0 for r in records)),
        "worst_day": int(max(r["avoidable_violation_steps"] for r in records)),
        "no_feasible_action_days": int(sum(r["no_feasible_action"] for r in records)),
        "model_inconsistency_days": int(sum(r["model_inconsistency"] for r in records)),
        "days": days,
    }


# --- Study runner ---------------------------------------------------------------------

FIXED_POLICY_CONFIGS = ("transformer", "substation", "substation_proxy", "full")
DIAGNOSTIC_CONFIGS = (
    "transformer", "substation", "substation+2:topology", "substation+2:decision_aware", "full",
)  # fmt: skip
PAIRS = (  # registered paired comparisons of replay_aci, primary condition (a minus b)
    ("substation", "full"),
    ("substation+1:topology", "substation"),
    ("substation+2:topology", "substation"),
    ("substation+4:topology", "substation"),
    ("substation+2:decision_aware", "substation+2:topology"),
    ("substation+2:risk", "substation+2:topology"),
    ("substation_proxy", "substation"),
)


def build_contexts(
    code: str, phase4_cache, fullstate_cache, period: str, truths=None
) -> tuple[dict, Layout, dict]:
    """Decision contexts of every Phase 5 truth for one network, plus its layout and the
    network facts used by the design (layout, ratings)."""
    from gridpulse import fullstate
    from gridpulse.grid import absolute_profiles

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    layout = network_layout(net)
    available = grid_study.daily_arrays(absolute_profiles(net))["sgen_p_mw"]
    rating = net.sgen["sn_mva"].to_numpy(dtype=float)
    norm, norm_v = ds.load_network_margins(phase4_cache, code)
    decision = [d for d in range(FIRST_DECISION_DAY, ds.LAST_DAY + 1)]
    development = tuple(d for d in grid_study.period_days("development") if d in decision)
    days = tuple(d for d in grid_study.period_days(period) if d in decision)
    nominal_states = fullstate.load_states(fullstate_cache, code, "nominal", decision)
    contexts = {}
    for truth in truths or fullstate.TRUTHS:
        states = (
            nominal_states if truth == "nominal"
            else fullstate.load_states(fullstate_cache, code, truth, decision)
        )  # fmt: skip
        source = norm if truth == "nominal" else norm_v[truth]
        contexts[truth] = DecisionContext(
            plan_norm=norm, truth_norm={d: source[d][ds.REALISED] for d in decision},
            states=states, available=available, rating=rating, layout=layout,
            development=development, days=days, nominal_states=nominal_states,
            trafo_mva=float(net.trafo["sn_mva"].iloc[0]),
            pv_by_bus=net.sgen.groupby("bus")["sn_mva"].sum().astype(float).to_dict(),
        )  # fmt: skip
    facts = {
        "pv_scale": ds.pv_scale(code),
        "lv_buses": len(layout.buses),
        "lines": len(net.line),
        "feeders": len(layout.feeder_heads),
        "customer_buses": len(layout.customer_buses),
        "trafo_mva": float(net.trafo["sn_mva"].iloc[0]),
        "n_lines": len(net.line),
    }
    return contexts, layout, facts


def analyse_network(contexts: dict, layout: Layout, facts: dict, online) -> dict:
    """Placement design, detection study and decision study of one network."""
    nominal = contexts["nominal"]
    dev = list(nominal.development)
    threshold = export_threshold(nominal.states, nominal.truth_norm, nominal.available, layout, dev)
    placements = design_placements(contexts, layout, online)
    configs = placement_configs(layout, placements, threshold)
    configs["full"] = standard_configs(layout, facts["n_lines"])["full"]
    coverage = {}
    for name, config in configs.items():
        counts = detection_counts(
            dev, nominal.states, nominal.truth_norm, config, layout, CONDITIONS[PRIMARY],
            seed_of("coverage", name), nominal.available,
        )  # fmt: skip
        positives = counts[:, 0].sum() + counts[:, 2].sum()
        coverage[name] = float(counts[:, 0].sum() / positives) if positives else None
    detection, decisions, paired, daily = {}, {}, {}, {}
    for truth, ctx in contexts.items():
        detection[truth] = {}
        for name, config in configs.items():
            rows = detection_counts(
                list(ctx.days), ctx.states, ctx.truth_norm, config, layout, CONDITIONS[PRIMARY],
                seed_of("detect", truth, name), ctx.available,
            )  # fmt: skip
            detection[truth][name] = summarise_detection(rows)
        runs = {}
        for policy in ("static_dev", "replay_robust", "oracle"):
            runs[(policy, "none", PRIMARY)] = run_feedback_policy(
                ctx, policy, configs["none"], CONDITIONS[PRIMARY], 0, online
            )
        for name, config in configs.items():
            if name == "none":
                continue
            conditions = (PRIMARY,) + (
                tuple(c for c in CONDITIONS if c != PRIMARY) if name in DIAGNOSTIC_CONFIGS else ()
            )
            for condition in conditions:
                seed = seed_of(truth, condition, name)
                runs[("replay_aci", name, condition)] = run_feedback_policy(
                    ctx, "replay_aci", config, CONDITIONS[condition], seed, online
                )
                if name in FIXED_POLICY_CONFIGS:
                    runs[("static_aci", name, condition)] = run_feedback_policy(
                        ctx, "static_aci", config, CONDITIONS[condition], seed, online
                    )
        decisions[truth] = {
            "/".join(key): summarise_decisions(records, online) for key, records in runs.items()
        }
        daily[truth] = {
            "/".join(key): {
                "avoidable_violation_steps": [r["avoidable_violation_steps"] for r in records],
                "curtailed_mwh": [r["curtailed_mwh"] for r in records],
            }
            for key, records in runs.items()
            if key[2] == PRIMARY and key[1] in ("substation", "substation+2:topology", "full")
        }
        paired[truth] = {}
        for a, b in PAIRS:
            ra, rb = runs[("replay_aci", a, PRIMARY)], runs[("replay_aci", b, PRIMARY)]
            paired[truth][f"{a} - {b}"] = {
                metric: block_bootstrap_mean(
                    np.array([x[metric] - y[metric] for x, y in zip(ra, rb, strict=True)])
                )
                for metric in ("avoidable_violation_steps", "curtailed_mwh")
            }
    return {
        "facts": facts,
        "export_threshold_mw": threshold,
        "placements": {rule: [int(b) for b in buses] for rule, buses in placements.items()},
        "coverage_development": coverage,
        "insufficient_evidence": {
            name: (c is not None and c < COVERAGE_MIN) for name, c in coverage.items()
        },
        "detection": detection,
        "decisions": decisions,
        "paired": paired,
        "daily": daily,
    }


# --- State-estimation summary, gate and hypothesis checks (protocol s. 7-9) ----------

SE_GATE_RECALL_GAIN = 0.2
SE_GATE_MAX_FAR_INCREASE = 0.05
SE_GATE_MIN_EVENTS = 10
MISMATCH = ("tap_raise_lv", "mv_high", "pv_fixed_095")


def summarise_se(rows: list[dict]) -> dict:
    """Per (truth, config): observability, estimator success, voltage error and detection
    of avoidable violations by state estimation versus direct detection on the same
    readings. A failed estimate raises no alarm."""
    groups: dict = {}
    for r in rows:
        groups.setdefault(r["truth"], {}).setdefault(r["config"], []).append(r)
    out: dict = {}
    for truth, by_config in groups.items():
        out[truth] = {}
        for config, g in by_config.items():
            ok = [r for r in g if r["success"]]

            def confusion(flag: str, subset: list, event: str = "event") -> dict:
                tp = sum(bool(r.get(flag)) and r[event] for r in subset)
                fp = sum(bool(r.get(flag)) and not r["event"] for r in subset)
                pos = sum(r[event] for r in subset)
                neg = sum(not r["event"] for r in subset)
                return {
                    "tp": tp, "fp": fp, "positives": pos, "negatives": neg,
                    "recall": tp / pos if pos else None,
                    "false_alarm_rate": fp / neg if neg else None,
                }  # fmt: skip

            def stat(field: str, how, ok=ok) -> float | None:
                return float(how([r[field] for r in ok])) if ok else None

            out[truth][config] = {
                "steps": len(g),
                "observable_without_pseudo": float(
                    np.mean([r["observable_without_pseudo"] for r in g])
                ),
                "rank_without_pseudo": int(g[0]["rank_without_pseudo"]),
                "states": int(g[0]["states"]),
                "observable_with_pseudo": float(np.mean([r["observable"] for r in g])),
                "success_rate": len(ok) / len(g),
                "rmse_vm_median": stat("rmse_vm", np.median),
                "max_abs_error_vm_p95": stat("max_abs_error_vm", lambda x: np.quantile(x, 0.95)),
                "error_at_highest_bus_median": stat("error_at_highest_bus", np.median),
                "se_any": confusion("se_flag", g),
                "direct_any": confusion("direct_flag", g),
                "se_voltage": confusion("se_flag", g, "event_voltage"),
                "direct_voltage": confusion("direct_flag", g, "event_voltage"),
            }  # fmt: skip
    return out


def se_gate(se_rows_by_network: dict) -> dict:
    """Protocol s. 7.4 gate (development sample, configuration `substation`, all truths
    pooled): state estimation must raise voltage-event recall by >= 0.2 over direct
    detection, at a false-alarm rate at most 0.05 higher, in >= 3 of the new networks
    with >= 10 voltage events."""
    per_network = {}
    for code, rows in se_rows_by_network.items():
        g = [r for r in rows if r["config"] == "substation"]
        positives = sum(r["event_voltage"] for r in g)
        negatives = sum(not r["event"] for r in g)
        if positives < SE_GATE_MIN_EVENTS or not negatives:
            per_network[code] = {"informative": False, "voltage_events": positives}
            continue
        recall = {f: sum(bool(r.get(f)) and r["event_voltage"] for r in g) / positives
                  for f in ("se_flag", "direct_flag")}  # fmt: skip
        far = {f: sum(bool(r.get(f)) and not r["event"] for r in g) / negatives
               for f in ("se_flag", "direct_flag")}  # fmt: skip
        passed = (recall["se_flag"] - recall["direct_flag"] >= SE_GATE_RECALL_GAIN
                  and far["se_flag"] - far["direct_flag"] <= SE_GATE_MAX_FAR_INCREASE)  # fmt: skip
        per_network[code] = {
            "informative": True, "voltage_events": positives, "recall": recall,
            "false_alarm_rate": far, "passed": bool(passed),
        }  # fmt: skip
    new = {c: v for c, v in per_network.items() if c != ds.DEVELOPMENT_NETWORK}
    passed = sum(v.get("passed", False) for v in new.values())
    return {"per_network": per_network, "networks_passed": passed, "open": passed >= 3}


def cells_meeting(results: dict, key: str, truths=MISMATCH) -> int:
    """Number of (new network x truth) cells in which decision run `key` meets beta."""
    return sum(
        results[c]["decisions"][t][key]["meets_beta"]
        for c in results if c != ds.DEVELOPMENT_NETWORK
        for t in truths if key in results[c]["decisions"][t]
    )  # fmt: skip


def evaluate_hypotheses(results: dict, online) -> dict:
    """Registered decision criteria (protocol s. 9) on the new networks."""

    def key(config: str, condition: str = PRIMARY) -> str:
        return f"replay_aci/{config}/{condition}"

    count = {name: cells_meeting(results, key(name)) for name in (
        "substation", "full", "transformer", "substation_proxy",
        *(f"substation+{k}:{rule}" for k in BUDGETS for rule in RULES),
    )}  # fmt: skip
    p = {
        "cells": 3 * sum(1 for c in results if c != ds.DEVELOPMENT_NETWORK),
        "meets_beta_cells": count,
        "a_substation_loses_at_least_3": count["substation"] <= count["full"] - 3,
        "b_two_topology_sensors_recover": count["substation+2:topology"] >= count["full"] - 1,
    }
    p["supported"] = bool(
        p["a_substation_loses_at_least_3"] and p["b_two_topology_sensors_recover"]
    )
    gap = count["full"] - count["substation"]
    s2 = {
        "topology_curve": [count["substation"]]
        + [count[f"substation+{k}:topology"] for k in BUDGETS],
        "first_sensor_recovers_half_of_k4_gain": (
            count["substation+1:topology"] - count["substation"]
            >= (count["substation+4:topology"] - count["substation"]) / 2
        ),
        "gap_full_minus_substation": gap,
    }  # fmt: skip
    curve = s2["topology_curve"]
    s2["non_decreasing"] = all(a <= b for a, b in zip(curve, curve[1:], strict=False))
    s1 = {}
    for c, r in results.items():
        if c == ds.DEVELOPMENT_NETWORK:
            continue
        recalls = {t: r["detection"][t]["substation"]["recall_voltage"] for t in r["detection"]}
        observed = [v for v in recalls.values() if v is not None]
        s1[c] = {
            "substation_voltage_recall": recalls,
            "below_half_wherever_voltage_events": bool(observed) and all(v < 0.5 for v in observed),
            "has_voltage_events": bool(observed),
        }
    s3 = {}
    for rival in ("topology", "risk", "mandatory"):
        wins = 0
        for c in results:
            if c == ds.DEVELOPMENT_NETWORK:
                continue
            dec = results[c]["decisions"]
            mine = sum(dec[t][key("substation+2:decision_aware")]["meets_beta"] for t in MISMATCH)
            theirs = sum(dec[t][key(f"substation+2:{rival}")]["meets_beta"] for t in MISMATCH)
            curtail = sum(
                dec[t][key("substation+2:decision_aware")]["curtailed_mwh"] for t in MISMATCH
            )
            curtail_r = sum(dec[t][key(f"substation+2:{rival}")]["curtailed_mwh"] for t in MISMATCH)
            wins += mine > theirs or (mine == theirs and curtail < curtail_r)
        s3[rival] = {"networks_where_decision_aware_better": wins, "better": wins >= 3}
    s6 = {"insufficient_and_fail": 0, "insufficient_and_meet": 0,
          "sufficient_and_fail": 0, "sufficient_and_meet": 0}  # fmt: skip
    for c, r in results.items():
        if c == ds.DEVELOPMENT_NETWORK:
            continue
        for name, insufficient in r["insufficient_evidence"].items():
            k = key(name)
            if name == "none" or k not in r["decisions"]["nominal"]:
                continue
            fails = any(not r["decisions"][t][k]["meets_beta"] for t in MISMATCH)
            label = "insufficient" if insufficient else "sufficient"
            s6[f"{label}_and_{'fail' if fails else 'meet'}"] += 1
    s7 = {
        name: {cond: cells_meeting(results, key(name, cond)) for cond in CONDITIONS}
        for name in DIAGNOSTIC_CONFIGS
    }
    return {"P": p, "S1_detection_gap": s1, "S2_value_curve": s2, "S3_placement": s3,
            "S6_insufficiency": s6, "S7_measurement_realism": s7}  # fmt: skip


def run_study(stage: str, phase4_cache, fullstate_cache, networks, workers: int, gate=None) -> dict:
    """Every analysis of one stage (protocol s. 10). `gate` is the development-stage
    state-estimation gate; the evaluation stage runs state-estimation feedback only if it
    opened."""
    from gridpulse import estimation, fullstate

    online = ds.OnlineSettings()
    results, se_rows = {}, {}
    for code in networks:
        contexts, layout, facts = build_contexts(code, phase4_cache, fullstate_cache, stage)
        result = analyse_network(contexts, layout, facts, online)
        base = Config("substation", transformer=True, heads=layout.feeder_heads)
        se_configs = {
            "substation": base,
            "substation+2:topology": with_remote(
                base, result["placements"]["topology"][:2], "substation+2:topology"
            ),
        }
        rows = estimation.se_study(
            code, list(contexts["nominal"].days), fullstate.TRUTHS, se_configs,
            {t: c.truth_norm for t, c in contexts.items()}, fullstate_cache,
            CONDITIONS[PRIMARY], workers,
        )  # fmt: skip
        result["state_estimation"] = summarise_se(rows)
        se_rows[code] = rows
        results[code] = result
        del contexts
    output = {"results": results}
    if stage == "development":
        output["se_gate"] = se_gate(se_rows)
    elif gate is not None and gate["open"]:
        runs = estimation.se_feedback_runs(
            networks, fullstate.TRUTHS, stage, phase4_cache, fullstate_cache, workers
        )
        for run in runs:
            code, truth = run["network"], run["truth"]
            decisions = results[code]["decisions"][truth]
            decisions["replay_aci/substation_se/realistic"] = run["summary"]
            base_daily = results[code]["daily"][truth]
            for ref in ("substation", "substation+2:topology"):
                reference = base_daily[f"replay_aci/{ref}/realistic"]
                results[code]["paired"][truth][f"substation_se - {ref}"] = {
                    m: block_bootstrap_mean(np.array(run["daily"][m]) - np.array(reference[m]))
                    for m in ("avoidable_violation_steps", "curtailed_mwh")
                }
    hypotheses = evaluate_hypotheses(results, online)

    def recall(r: dict, truth: str, which: str):
        return r["state_estimation"].get(truth, {}).get("substation", {}).get(which)

    se_open = gate is not None and gate.get("open")
    hypotheses["S4_state_estimation"] = {
        "gate_from_development": gate if stage != "development" else output.get("se_gate"),
        "voltage_recall": {
            c: {
                t: {"se": recall(r, t, "se_voltage"), "direct": recall(r, t, "direct_voltage")}
                for t in fullstate.TRUTHS
            }
            for c, r in results.items()
        },
        "meets_beta_cells_substation_se": (
            cells_meeting(results, "replay_aci/substation_se/realistic") if se_open else None
        ),
    }
    hypotheses["S5_model_consistency"] = {
        c: {
            t: r["decisions"][t]["replay_aci/substation/realistic"]["model_inconsistency_days"]
            / r["decisions"][t]["replay_aci/substation/realistic"]["days"]
            for t in fullstate.TRUTHS
        }
        for c, r in results.items()
    }
    output["hypotheses"] = hypotheses
    return output
