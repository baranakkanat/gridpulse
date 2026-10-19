"""Phase 8 (docs/phase8_protocol.md s. 5, 7): separate voltage and loading reserves for the
Phase 7 residual-corrected replay planner, and the data-availability conditions it is
tested under (injection-data delay, missing substation days).

Separate reserves per constraint type are established practice (chance-constrained OPF,
robust MPC; docs/phase8_literature.md); this is the simplest version for the Phase 7
planner, not a new method. Reserves are physical: `r_v` in p.u. on both voltage
exceedances and `r_l` in percentage points of rating on both loading exceedances. They
are never added to each other: the planner normalises each exceedance with the Phase 4
scale and takes the maximum, as before.
"""

from __future__ import annotations

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import margins as mg
from gridpulse.grid_study import FIRST_DECISION_DAY

VOLTAGE, LOADING = (0, 1), (2, 3)  # columns of grid.MARGINS
GRID_V = tuple(round(0.0005 * i, 4) for i in range(21))  # p.u.
GRID_L = tuple(round(0.5 * i, 1) for i in range(21))  # percentage points
GRID_SHARED_FINE = tuple(round(0.005 * i, 3) for i in range(21))  # normalised (C1f)
TAP_STEP_PU = 0.025  # the common-mode offset the correction is designed to remove (C5)
MIN_WINDOW = 7  # rolling tuning: fewer window days -> the grid maxima (C6)


def reserve_vector(r_v: float, r_l: float) -> np.ndarray:
    """Reserves added to the four exceedances (overvoltage, undervoltage: p.u.; line,
    transformer: %)."""
    return np.array([r_v, r_v, r_l, r_l], dtype=float)


def type_norm(raw: np.ndarray, columns: tuple[int, ...]) -> np.ndarray:
    """Largest normalised exceedance over one constraint type; a failed flow (any NaN in
    the state) counts as +inf, as in `dual_study.normalised`."""
    raw = np.asarray(raw, dtype=float)
    value = (raw[..., list(columns)] / ds.MARGIN_SCALE[list(columns)]).max(axis=-1)
    return np.where(np.isnan(raw).any(axis=-1), np.inf, value)


def first_level(acceptable: np.ndarray) -> np.ndarray:
    """`grid_study.first_level` along the last axis (levels): the least curtailment that is
    acceptable, else the deepest cap."""
    return np.where(acceptable.any(axis=-1), acceptable.argmax(axis=-1), ds.LAST_LEVEL)


def replay_days(day: int, delay: int, first: int) -> range:
    """Days replayed for day `day` when injection data arrive `delay` days late: d-28-D ..
    d-1-D, truncated at the first day with data (amendment 8A)."""
    return range(max(first, day - delay - ds.REPLAY_DAYS), day - delay)


def violations_by_reserve(
    norm: dict, window, daylight: dict, grid: np.ndarray, delay: int = 0
) -> np.ndarray:
    """For each normalised reserve on `grid`, the avoidable daylight violations the replay
    rule would have had on the `window` days, judged against the same model's realised
    exceedances (`norm`: day -> steps x levels). The replay of day w is the one the planner
    uses (`replay_days`); `window` must be consecutive days."""
    grid = np.asarray(grid, dtype=float)
    counts = np.zeros(len(grid), dtype=int)
    if not len(window):
        return counts
    first_key = min(norm)
    lo = replay_days(window[0], delay, first_key).start
    stack = np.stack([norm[j] for j in range(lo, window[-1] - delay)])  # days x steps x levels
    for w in window:
        days = replay_days(w, delay, first_key)
        replay = stack[days.start - lo : days.stop - lo].max(axis=0)
        levels = first_level(replay[None] + grid[:, None, None] <= 0)  # reserves x steps
        realised = norm[w]
        violated = np.take_along_axis(np.broadcast_to(realised, (len(grid), *realised.shape)),
                                      levels[..., None], axis=-1)[..., 0] > 0  # fmt: skip
        avoidable = (realised <= 0).any(axis=-1)
        counts += (violated & avoidable & daylight[w]).sum(axis=1)
    return counts


def smallest(grid, counts: np.ndarray, beta: float, n_days: int) -> float:
    """The smallest grid value with at most `beta` violations per day; else the largest."""
    ok = np.flatnonzero(np.asarray(counts) <= beta * n_days)
    return float(grid[ok[0]]) if len(ok) else float(grid[-1])


def _daylight(available, days) -> dict:
    return {d: np.asarray(available[d]).sum(axis=1) > 0 for d in days}


def tuned_shared(
    plan_raw: dict, available, days, beta: float, grid=mg.MARGIN_GRID, delay: int = 0
) -> dict:
    """Phase 7's shared margin (`margins.tuned_safety_margin`) on any grid (C1f) and for a
    delayed replay (I5), with the violation count of every grid value recorded."""
    norm = {d: ds.normalised(np.asarray(m[ds.REALISED], dtype=float)) for d, m in plan_raw.items()}
    daylight = _daylight(available, days)
    counts = violations_by_reserve(norm, days, daylight, np.asarray(grid), delay)
    return {"s": smallest(grid, counts, beta, len(days)), "curve": counts.tolist()}


def tuned_fixed_reserves(plan_raw: dict, available, days, beta: float, delay: int = 0) -> dict:
    """C5: r_l from the operator's nominal model with loading constraints only; r_v from the
    same model with voltage constraints only, after shifting every voltage by one tap step
    (overvoltage + 0.025, undervoltage - 0.025 p.u.), the offset the correction is designed
    to remove; under the nominal model alone voltage never binds. Development days only."""
    shift = np.array([TAP_STEP_PU, -TAP_STEP_PU, 0.0, 0.0])
    voltage = {d: type_norm(m[ds.REALISED] + shift, VOLTAGE) for d, m in plan_raw.items()}
    loading = {d: type_norm(m[ds.REALISED], LOADING) for d, m in plan_raw.items()}
    daylight = _daylight(available, days)
    grid_v, grid_l = np.array(GRID_V) / ds.MARGIN_SCALE[0], np.array(GRID_L) / ds.MARGIN_SCALE[2]
    curve_v = violations_by_reserve(voltage, days, daylight, grid_v, delay)
    curve_l = violations_by_reserve(loading, days, daylight, grid_l, delay)
    return {
        "r_v": smallest(GRID_V, curve_v, beta, len(days)),
        "r_l": smallest(GRID_L, curve_l, beta, len(days)),
        "curve_v": curve_v.tolist(),
        "curve_l": curve_l.tolist(),
    }


class ReserveCorrector(mg.ResidualCorrector):
    """The Phase 7 corrector with (a) optional separate reserves, fixed (`(r_v, r_l)`, C5)
    or re-tuned every day (`"rolling"`, C6), (b) an injection-data delay of `delay_days`
    (the replay uses days d-28-D..d-1-D, truncated at the first day with data; pass
    `lag_days=D` in the settings so that the residuals wait for the same data) and (c) days
    without substation data, on which no estimate is updated. With `reserves=None` the plan
    is Phase 7's (the shared `safety_margin` of the settings); without a delay it is
    computed by the Phase 7 code itself."""

    def __init__(self, plan_raw, nominal_states, layout, config, model, settings, *,
                 reserves=None, available=None, beta: float = 0.1, delay_days: int = 0,
                 missing_days=frozenset()) -> None:  # fmt: skip
        super().__init__(plan_raw, nominal_states, layout, config, model, settings)
        if reserves == "rolling":
            if available is None:
                raise ValueError("rolling reserves need the PV availability (daylight)")
        elif reserves is not None and len(reserves) != 2:
            raise ValueError("reserves are (r_v p.u., r_l %), 'rolling' or None")
        if delay_days < 0:
            raise ValueError("delay_days must be >= 0")
        self.reserves, self.available, self.beta = reserves, available, float(beta)
        self.delay, self.missing = int(delay_days), frozenset(missing_days)
        self.in_force: tuple = (None, None)
        self.first_day = min(plan_raw)

    def replay(self, day: int) -> np.ndarray:
        days = replay_days(day, self.delay, self.first_day)
        if self.reserves is None:
            if not self.delay:
                return super().replay(day)  # the Phase 7 code path
            return self.settings.safety_margin + np.stack(
                [ds.normalised(self.corrected(self.plan_raw[j][ds.REALISED])) for j in days]
            ).max(axis=0)
        r_v, r_l = self.rolling(day) if self.reserves == "rolling" else self.reserves
        self.in_force = (float(r_v), float(r_l))
        vector = reserve_vector(r_v, r_l)
        return np.stack(
            [ds.normalised(self.corrected(self.plan_raw[j][ds.REALISED]) + vector) for j in days]
        ).max(axis=0)

    def rolling(self, day: int) -> tuple[float, float]:
        """C6: per type, the smallest reserve that would have kept the corrected model's own
        replay within beta on the last 28 days with data (estimates in force now)."""
        last = day - 1 - self.delay
        window = range(max(FIRST_DECISION_DAY, day - ds.REPLAY_DAYS - self.delay), last + 1)
        if len(window) < MIN_WINDOW:
            return GRID_V[-1], GRID_L[-1]
        lo = replay_days(window[0], self.delay, self.first_day).start
        corrected = {j: self.corrected(self.plan_raw[j][ds.REALISED]) for j in range(lo, last + 1)}
        daylight = _daylight(self.available, window)
        voltage = {j: type_norm(e, VOLTAGE) for j, e in corrected.items()}
        loading = {j: type_norm(e, LOADING) for j, e in corrected.items()}
        grid_v = np.array(GRID_V) / ds.MARGIN_SCALE[0]
        grid_l = np.array(GRID_L) / ds.MARGIN_SCALE[2]
        counts_v = violations_by_reserve(voltage, window, daylight, grid_v, self.delay)
        counts_l = violations_by_reserve(loading, window, daylight, grid_l, self.delay)
        r_v = smallest(GRID_V, counts_v, self.beta, len(window))
        r_l = smallest(GRID_L, counts_l, self.beta, len(window))
        return r_v, r_l

    def observe(self, day: int, readings: dict, levels: np.ndarray, daylight: np.ndarray) -> None:
        if day in self.missing:  # no substation data that day: nothing is learnt
            return
        super().observe(day, readings, levels, daylight)

    def state(self) -> dict:
        r_v, r_l = self.in_force
        return {**super().state(), "r_v": r_v, "r_l": r_l}
