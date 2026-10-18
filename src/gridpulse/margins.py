"""Phase 7: continuous constraint margins and model-residual correction
(docs/phase7_protocol.md).

Conventions. A *signed margin* is positive inside the limits, zero at a limit and negative
when violated; it keeps the physical unit of its constraint:

- voltage: m_V = min(V_max - V, V - V_min), p.u.;
- loading: m_I = limit - loading, percentage points of the rating.

Violation magnitude is max(-m, 0) in the same unit; duration is a run of consecutive
violated quarter-hours; frequency counts violated quarter-hours. Voltage and loading
margins are never added: they describe different physical mechanisms. The Phase 4 cache
stores *exceedances* (positive = violation, columns `grid.MARGINS`), i.e. -m_V split into
its over- and undervoltage parts and -m_I for the most loaded line and the transformer.

Information layers. Ground truth (simulated true state) is read only by the evaluator.
`ResidualCorrector` sees only (a) the operator's nominal model evaluated at the metered
injections and the caps it applied (the same information Phase 4 replay planning uses), and
(b) sensor readings, with their availability delays.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

from gridpulse import dual_study as ds
from gridpulse.grid_study import STEPS

LOADING_LIMIT = 100.0  # % of rating for every line and transformer in these networks


# --- Signed margins and violation descriptors ----------------------------------------


def voltage_margin(vm: np.ndarray, v_min: np.ndarray, v_max: np.ndarray) -> np.ndarray:
    """Signed voltage margin, p.u.: min(V_max - V, V - V_min). NaN (failed flow) stays NaN."""
    vm = np.asarray(vm, dtype=float)
    return np.minimum(np.asarray(v_max) - vm, vm - np.asarray(v_min))


def loading_margin(loading: np.ndarray, limit: float = LOADING_LIMIT) -> np.ndarray:
    """Signed loading margin, percentage points of the rating: limit - loading."""
    return limit - np.asarray(loading, dtype=float)


def violation_magnitude(margin: np.ndarray) -> np.ndarray:
    """How far beyond the limit, in the margin's unit (0 inside the limits; NaN stays NaN)."""
    margin = np.asarray(margin, dtype=float)
    return np.where(np.isnan(margin), np.nan, np.maximum(-margin, 0.0))


def violation_runs(violated: np.ndarray) -> list[int]:
    """Lengths (quarter-hours) of the runs of consecutive violated steps of a 1-D series."""
    edges = np.diff(np.concatenate(([0], np.asarray(violated, dtype=int), [0])))
    return [int(e - s) for s, e in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1),
                                       strict=True)]  # fmt: skip


# --- Model-residual correction ---------------------------------------------------------


@dataclass(frozen=True)
class CorrectorSettings:
    """Model-residual correction (protocol s. 5). `meters` is "none" (substation only),
    "checked" (meter residuals used only when consistent with the busbar residual) or
    "naive" (meter residuals used unchecked; a reference showing what bias does)."""

    window_days: int = 7  # median of the last daily estimates
    min_loading_pct: float = 20.0  # loading ratios only where the model predicts this much
    max_offset_pu: float = 0.05  # plausibility bounds of the estimates
    max_ratio: float = 0.3
    meters: str = "none"
    meter_tolerance_pu: float = 0.005  # |meter - busbar residual| above this: inconsistent
    safety_margin: float = 0.0  # fixed planning margin (normalised), tuned on development
    correct: bool = True  # False: the same planner without correction (reference)
    lag_days: int = 0  # extra days before a day's residuals can be used (sensitivity)
    model_error_pu: float = 0.005  # evidence label thresholds (Phase 5 consistency: 0.005 p.u.)
    model_error_ratio: float = 0.05

    def __post_init__(self) -> None:
        if self.meters not in ("none", "checked", "naive") or self.window_days < 1:
            raise ValueError(f"invalid corrector settings {self}")


def _median(values) -> float:
    return float(np.median(values)) if values else 0.0


class ResidualCorrector:
    """Corrects the nominal planning model from the residuals of measured quantities.

    After each day d it compares the day's readings with the nominal model's prediction
    for the same metered injections and applied caps:

    - busbar voltage residual (daylight mean, p.u.): estimates a common voltage offset
      (e.g. a wrong tap position or MV voltage shifts every LV voltage alike);
    - transformer and measured line current ratios (median of measured/predicted - 1 where
      the model predicts at least `min_loading_pct`; the worst line): a loading error;
    - optionally remote meter residuals (daylight means), which arrive with the meters'
      reporting delay.

    The estimates in force are medians over the last `window_days` daily values. `replay`
    then shifts the replayed nominal exceedances: overvoltage + v, undervoltage - v, line
    and transformer loading x (1 + rho). Substation data of day d are used from day d + 1,
    meter data from day d + 1 + delay."""

    def __init__(self, plan_raw: dict, nominal_states: dict, layout, config, model,
                 settings: CorrectorSettings) -> None:  # fmt: skip
        self.plan_raw, self.nominal, self.layout = plan_raw, nominal_states, layout
        self.config, self.model, self.settings = config, model, settings
        self.column = {b: i for i, b in enumerate(layout.buses)}
        w = settings.window_days
        self.v_days: deque = deque(maxlen=w)
        self.rho_trafo_days: deque = deque(maxlen=w)
        self.rho_line_days: deque = deque(maxlen=w)
        self.meter_days = {b: deque(maxlen=w) for b in config.voltages}
        self.pending: dict[int, dict] = {}  # day -> meter residuals not yet delivered
        self.lagged: dict[int, tuple] = {}  # day -> substation daily values not yet usable
        self.estimate = {"v_hat": 0.0, "rho_line": 0.0, "rho_trafo": 0.0}
        self.v_bus = 0.0  # busbar-only offset estimate (for the evidence labels)
        self.flags = {"meters_used": 0, "meters_inconsistent": 0}

    # planning side ----------------------------------------------------------------
    def corrected(self, raw: np.ndarray) -> np.ndarray:
        """Nominal exceedances (96 x levels x 4) shifted by the current estimates."""
        e = np.array(raw, dtype=float)
        v, rho_l, rho_t = (self.estimate[k] for k in ("v_hat", "rho_line", "rho_trafo"))
        e[..., 0] += v
        e[..., 1] -= v
        e[..., 2] = (e[..., 2] + LOADING_LIMIT) * (1.0 + rho_l) - LOADING_LIMIT
        e[..., 3] = (e[..., 3] + LOADING_LIMIT) * (1.0 + rho_t) - LOADING_LIMIT
        return e

    def replay(self, day: int) -> np.ndarray:
        """Normalised worst case over the replayed days (as Phase 4 replay), corrected, plus
        the fixed safety margin (so that `first_safe(replay, 0)` keeps that margin)."""
        days = range(day - ds.REPLAY_DAYS, day)
        return self.settings.safety_margin + np.stack(
            [ds.normalised(self.corrected(self.plan_raw[j][ds.REALISED])) for j in days]
        ).max(axis=0)

    def state(self) -> dict:
        s = self.settings
        model_error = (  # from the substation residuals only (protocol s. 8)
            abs(self.v_bus) > s.model_error_pu
            or max(abs(self.estimate["rho_line"]), abs(self.estimate["rho_trafo"]))
            > s.model_error_ratio
        )
        return {**self.estimate, **self.flags, "physical_model_uncertainty": bool(model_error)}

    # measurement side ----------------------------------------------------------------
    def observe(self, day: int, readings: dict, levels: np.ndarray, daylight: np.ndarray) -> None:
        if not self.settings.correct:
            return
        steps = np.arange(STEPS)
        nominal = self.nominal[day]
        s = self.settings
        v_day = rho_t_day = rho_l_day = None
        if "busbar_vm" in readings:
            residual = readings["busbar_vm"][:, 0] - nominal["trafo"][steps, levels, 3]
            usable = daylight & np.isfinite(residual)  # a failed flow is skipped, not averaged
            if usable.any():
                v_day = float(np.mean(residual[usable]))
            predicted = nominal["trafo"][steps, levels, 2]
            rho_t_day = self._ratio(readings["trafo_loading"][:, 0], predicted, daylight)
        # every measured line current: feeder heads (substation) and, with full metering,
        # all lines (amendment 7A: the full configuration reports `line_loading`)
        currents = [(readings["head_loading"][:, i], h) for i, h in enumerate(self.config.heads)
                    if "head_loading" in readings]  # fmt: skip
        currents += [(readings["line_loading"][:, i], ln) for i, ln in enumerate(self.config.lines)
                     if "line_loading" in readings]  # fmt: skip
        ratios = [
            self._ratio(m, nominal["line"][steps, levels, ln], daylight) for m, ln in currents
        ]
        ratios = [r for r in ratios if r is not None]
        if ratios:
            rho_l_day = max(ratios)  # the worst measured line
        self.lagged[day] = (v_day, rho_t_day, rho_l_day)
        for k in sorted(d for d in self.lagged if d <= day - s.lag_days):
            for value, window in zip(self.lagged.pop(k),
                                     (self.v_days, self.rho_trafo_days, self.rho_line_days),
                                     strict=True):  # fmt: skip
                if value is not None:
                    window.append(value)
        if "remote_vm" in readings and s.meters != "none":
            vm = nominal["vm"][steps, levels]
            means = {}
            for i, b in enumerate(self.config.voltages):
                r = readings["remote_vm"][:, i] - vm[:, self.column[b]]
                usable = daylight & np.isfinite(r)
                if readings["remote_available"][i] and usable.any():
                    means[b] = float(np.mean(r[usable]))
            self.pending[day] = means
            delay = self.model.remote_delay_days + s.lag_days
            for k in sorted(d for d in self.pending if d <= day - delay):
                for b, value in self.pending.pop(k).items():
                    self.meter_days[b].append(value)
        self._update()

    def _ratio(self, measured, predicted, daylight) -> float | None:
        with np.errstate(invalid="ignore"):
            mask = daylight & np.isfinite(measured) & (predicted > self.settings.min_loading_pct)
        if not mask.any():
            return None
        return float(np.median(measured[mask] / predicted[mask] - 1.0))

    def _update(self) -> None:
        s = self.settings
        v_bus = _median(self.v_days)
        self.v_bus = v_bus
        v = v_bus
        used = inconsistent = 0
        for values in self.meter_days.values():
            if not values:
                continue
            m = _median(values)
            if s.meters == "checked" and abs(m - v_bus) > s.meter_tolerance_pu:
                inconsistent += 1
                continue
            used += 1
            v = max(v, m)  # a meter can only make the plan more cautious
        self.estimate = {
            "v_hat": float(np.clip(v, -s.max_offset_pu, s.max_offset_pu)),
            "rho_line": float(np.clip(_median(self.rho_line_days), -s.max_ratio, s.max_ratio)),
            "rho_trafo": float(np.clip(_median(self.rho_trafo_days), -s.max_ratio, s.max_ratio)),
        }
        self.flags = {"meters_used": used, "meters_inconsistent": inconsistent}


MARGIN_GRID = tuple(round(0.02 * i, 2) for i in range(21))  # 0 .. 0.40, as tau's range


def tuned_safety_margin(plan_raw: dict, available, development, beta: float) -> float:
    """The smallest fixed replay margin (normalised) for which the nominal model's own
    replay plan would have had at most `beta` avoidable daylight violations per day on the
    development days, judged against the nominal model's realised margins. Uses only the
    operator's model and metered history, as the Phase 4 static tuning does; never truth."""
    norm = {d: ds.normalised(np.asarray(m[ds.REALISED], dtype=float)) for d, m in plan_raw.items()}
    for margin in MARGIN_GRID:
        violations = 0
        for day in development:
            replay = np.stack([norm[j] for j in range(day - ds.REPLAY_DAYS, day)]).max(axis=0)
            levels = ds.first_safe(replay, margin)
            realised = norm[day]
            daylight = available[day].sum(axis=1) > 0
            avoidable = (realised <= 0).any(axis=1)
            violated = realised[np.arange(STEPS), levels] > 0
            violations += int((violated & daylight & avoidable).sum())
        if violations <= beta * len(development):
            return margin
    return MARGIN_GRID[-1]


# --- Evidence labels -----------------------------------------------------------------


def evidence_label(record: dict) -> str:
    """One operational label per decision, from information available at decision time
    (protocol s. 8). Not a safety certificate.

    - NO_VERIFIED_FEASIBLE_ACTION: no cap level satisfies the (corrected) planning margin;
    - INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS: a meter disagrees with the busbar while the
      substation residuals also indicate a model error (bias and a local model error are
      confounded);
    - MEASUREMENT_MODEL_INCONSISTENCY: a meter disagrees with the busbar and the substation
      residuals show no model error (meter bias suspected);
    - PHYSICAL_MODEL_UNCERTAINTY: substation residuals beyond the label thresholds;
    - EVIDENCE_SUFFICIENT_FOR_DEFINED_ANALYSIS: none of the above."""
    if record.get("no_feasible_action"):
        return "NO_VERIFIED_FEASIBLE_ACTION"
    model_error = record.get("physical_model_uncertainty", False)
    if record.get("meters_inconsistent", 0):
        return (
            "INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS"
            if model_error
            else "MEASUREMENT_MODEL_INCONSISTENCY"
        )
    if model_error:
        return "PHYSICAL_MODEL_UNCERTAINTY"
    return "EVIDENCE_SUFFICIENT_FOR_DEFINED_ANALYSIS"


# --- Measurement-interval coverage ----------------------------------------------------


def interval_coverage(errors: np.ndarray, half_width: float) -> float:
    """Share of readings whose error lies within +/- half_width (empirical coverage of the
    interval reading +/- half_width against the simulated truth)."""
    errors = np.asarray(errors, dtype=float)
    errors = errors[np.isfinite(errors)]
    return float(np.mean(np.abs(errors) <= half_width)) if errors.size else float("nan")
