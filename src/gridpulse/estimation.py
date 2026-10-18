"""Phase 5: weighted-least-squares state estimation from sparse measurements.

pandapower's WLS estimator is used unchanged. Two things are added around it:

- a numerical observability test: the rank of the measurement Jacobian at a flat start
  (current-magnitude rows excluded, as they have zero derivative there). pandapower itself
  only compares the *number* of measurements with the number of states, which does not
  guarantee observability;
- pseudo-measurements of bus injections from the day-ahead forecast, with a standard
  deviation from the same bus's past forecast errors (days d-28..d-1, same quarter-hour).
  They are estimates, never treated as exact.

The estimator always uses the nominal network (the planning model). Measurements come from
`sensing.measure`, i.e. from the true grid with noise.
"""

from __future__ import annotations

import copy
import warnings

import numpy as np
import pandas as pd
from pandapower.estimation.algorithm.matrix_base import BaseAlgebra
from pandapower.estimation.ppc_conversion import _initialize_voltage, pp2eppci
from pandapower.estimation.state_estimation import StateEstimation

from gridpulse import grid_study

PSEUDO_FLOOR_MW = 0.0005  # smallest pseudo-measurement standard deviation, MW / MVAr
SUBSTATION_FLOOR = 0.0005  # smallest standard deviation of a substation P/Q reading


def bus_series(net, arrays: dict) -> dict:
    """Net injection per customer bus (load convention: consumption positive), as arrays
    days x 96 x buses for P (MW) and Q (MVAr), from the per-element series."""
    buses = sorted(set(net.load["bus"]) | set(net.sgen["bus"]))
    column = {b: i for i, b in enumerate(buses)}
    load_map = np.zeros((len(net.load), len(buses)))
    load_map[np.arange(len(net.load)), [column[b] for b in net.load["bus"]]] = 1.0
    sgen_map = np.zeros((len(net.sgen), len(buses)))
    sgen_map[np.arange(len(net.sgen)), [column[b] for b in net.sgen["bus"]]] = 1.0
    p = arrays["load_p_mw"] @ load_map - arrays["sgen_p_mw"] @ sgen_map
    q = arrays["load_q_mvar"] @ load_map
    return {
        "buses": [int(b) for b in buses], "p": p, "q": q,
        "sgen_p": arrays["sgen_p_mw"], "sgen_map": sgen_map,
    }  # fmt: skip


def pseudo_measurements(series: dict, day: int, t: int, window: int = 28, cap=None,
                        rating=None) -> dict:  # fmt: skip
    """Pseudo-measurements of every customer bus at step t of `day`: the day-ahead forecast
    (mean of the 7 previous days, as in Phase 4) and the standard deviation of that
    forecast's errors over the `window` previous days. Uses days before `day` only. With a
    `cap`, the forecast PV of each unit is limited to cap x rating (the applied action is
    known to the operator); the standard deviation is that of the uncapped forecast."""
    out = {}
    stats = []
    for name in ("p", "q"):
        values = series[name][:, t]
        forecast = values[day - grid_study.FORECAST_DAYS : day].mean(axis=0)
        errors = [
            values[j] - values[j - grid_study.FORECAST_DAYS : j].mean(axis=0)
            for j in range(day - window, day)
        ]
        stats.append((forecast, np.maximum(np.std(errors, axis=0), PSEUDO_FLOOR_MW)))
    p_forecast = stats[0][0]
    if cap is not None:
        pv = series["sgen_p"][day - grid_study.FORECAST_DAYS : day, t].mean(axis=0)
        reduction = pv - np.minimum(pv, cap * rating)
        p_forecast = p_forecast + reduction @ series["sgen_map"]  # less PV: more net load
    for i, bus in enumerate(series["buses"]):
        out[bus] = ((p_forecast[i], stats[1][0][i]), (stats[0][1][i], stats[1][1][i]))
    return out


MEASUREMENT_COLUMNS = ("name", "measurement_type", "element_type", "element", "value",
                       "std_dev", "side")  # fmt: skip


def add_measurements(net, readings: dict, t: int, config, layout, model, pseudo=None,
                     inplace: bool = False):  # fmt: skip
    """`net` (or a copy) carrying the step-t readings of `config` and optional pseudo-
    measurements {bus: ((p, q), (sigma_p, sigma_q))} as its pandapower measurement table.
    The table is built in one step (equivalent to `pp.create_measurement` per row)."""
    m = net if inplace else copy.deepcopy(net)
    rows = []
    if "trafo_loading" in readings:
        sigma_v = max(model.sigma_v_substation, 1e-4)
        rows.append(("v", "bus", layout.lv_busbar, readings["busbar_vm"][t, 0], sigma_v, None))
        for kind, key in (("p", "trafo_p"), ("q", "trafo_q")):
            value = readings[key][t, 0]
            sigma = max(model.sigma_loading * abs(value), SUBSTATION_FLOOR)
            rows.append((kind, "trafo", 0, value, sigma, "lv"))
    for k, line in enumerate(getattr(config, "heads", ())):
        rated = float(m.line.loc[line, ["max_i_ka", "df", "parallel"]].prod())
        current = readings["head_loading"][t, k] / 100.0 * rated
        side = "from" if m.line.loc[line, "from_bus"] == layout.lv_busbar else "to"
        rows.append(("i", "line", line, current, max(model.sigma_loading * current, 1e-5), side))
    for k, bus in enumerate(getattr(config, "voltages", ())):
        if readings["remote_available"][k]:
            sigma_v = max(model.sigma_v_remote, 1e-4)
            rows.append(("v", "bus", bus, readings["remote_vm"][t, k], sigma_v, None))
    for bus, ((p, q), (sp, sq)) in (pseudo or {}).items():
        rows.append(("p", "bus", bus, p, sp, None))
        rows.append(("q", "bus", bus, q, sq, None))
    table = pd.DataFrame(
        [(None, kind, element_type, element, float(value), float(sigma), side)
         for kind, element_type, element, value, sigma, side in rows],
        columns=list(MEASUREMENT_COLUMNS),
    )  # fmt: skip
    m.measurement = table.astype({"element": "uint32", "value": float, "std_dev": float})
    return m


def estimator_inputs(config):
    """The readings a configuration feeds to the estimator (amendment 5A): everything
    except current magnitudes. pandapower's WLS failed to converge on many steps with
    feeder-head |I| measurements on development days (43 % of steps in urban6, all
    steps in rural3 under the reactive-power truth) and on none without them. Measured
    currents still raise direct alarms (`sensing.flagged_steps`)."""
    from gridpulse import sensing

    return sensing.Config(config.name, config.transformer, (), config.voltages, ())


def zero_injection_buses(net) -> list[int]:
    """Junction buses: no load, PV, storage or external grid (a topology fact). They are
    passed to pandapower explicitly; its "no_inj_bus" mode fails on these networks
    (pandapower 3.5.6, mask-length error)."""
    connected = set(net.load["bus"]) | set(net.sgen["bus"]) | set(net.storage["bus"])
    connected |= set(net.ext_grid["bus"])
    return [int(b) for b in net.bus.index if b not in connected]


def numerical_observability(net) -> dict:
    """Rank of the measurement Jacobian at a flat start versus the number of states."""
    v_start, delta_start = _initialize_voltage(net, "flat")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _, _, eppci = pp2eppci(
            copy.deepcopy(net), v_start=v_start, delta_start=delta_start,
            zero_injection=zero_injection_buses(net),
        )  # fmt: skip
        H = BaseAlgebra(eppci).create_hx_jacobian(eppci.E)
    H = H.toarray() if hasattr(H, "toarray") else np.asarray(H)
    if eppci.any_i_meas:
        H = H[eppci.idx_non_imeas]
    rank = int(np.linalg.matrix_rank(H))
    return {"rank": rank, "states": int(H.shape[1]), "observable": rank == H.shape[1]}


def structure_key(net) -> tuple:
    """The measured quantities and locations (not values) of `net`'s measurement table."""
    table = net.measurement
    return tuple(
        zip(table["measurement_type"], table["element_type"], table["element"], table["side"],
            strict=True)
    )  # fmt: skip


def estimate(net, observability_cache: dict | None = None) -> dict:
    """WLS estimate of `net`'s measurements, refused (not attempted) when the
    measurement set is not numerically observable. The flat-start Jacobian depends only on
    the measurement structure, so its rank can be cached by `structure_key`. Returns bus
    voltages (p.u., by bus index) and line loadings (%) if successful."""
    key = structure_key(net)
    if observability_cache is not None and key in observability_cache:
        observability = observability_cache[key]
    else:
        observability = numerical_observability(net)
        if observability_cache is not None:
            observability_cache[key] = observability
    result = {"observable": observability["observable"], "success": False, **observability}
    if not observability["observable"]:
        return result
    se = StateEstimation(net, 1e-6, 50, algorithm="wls")
    v_start, delta_start = _initialize_voltage(net, "flat")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            outcome = se.estimate(
                v_start=v_start, delta_start=delta_start, zero_injection=zero_injection_buses(net)
            )
        except (UserWarning, np.linalg.LinAlgError, ValueError):
            return result
    success = bool(outcome["success"]) if isinstance(outcome, dict) else bool(outcome)
    vm = net.res_bus_est["vm_pu"] if success else None
    if success and np.isfinite(vm.to_numpy()).all():
        result.update(
            success=True,
            vm=vm.to_dict(),
            line_loading=net.res_line_est["loading_percent"].to_numpy(),
            iterations=int(outcome["num_iterations"]),
        )
    return result


SE_STEPS = tuple(range(44, 57))  # 11:00-14:00 UTC, the hours with PV-driven violations
SE_DAY_STRIDE = 3  # every third day (protocol s. 5)


# --- State-estimation study (protocol s. 5) ----------------------------------------

SE_CONFIGS = ("substation", "substation+2:topology")
_SE: dict = {}


def _se_init(code: str) -> None:
    from gridpulse import dual_study as ds
    from gridpulse import sensing
    from gridpulse.grid import absolute_profiles

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    arrays = grid_study.daily_arrays(absolute_profiles(net))
    _SE.clear()
    _SE.update(
        net=net, series=bus_series(net, arrays), layout=sensing.network_layout(net),
        available=arrays["sgen_p_mw"],
    )  # fmt: skip


def _se_task(task: tuple) -> list[dict]:
    """State estimation on the sampled steps of one (truth, day), for each configuration;
    the same readings feed direct detection for comparison."""
    from gridpulse import fullstate, sensing

    code, truth, day, configs, truth_norm, cache_dir, model, seed = task
    net, layout, series = _SE["net"], _SE["layout"], _SE["series"]
    state = fullstate.load_states(cache_dir, code, truth, [day])[day]
    events = sensing.true_events(truth_norm, state, 0, layout)
    daylight = _SE["available"][day].sum(axis=1) > 0
    limits = np.array(layout.max_vm)
    rng = np.random.default_rng(seed)
    work = copy.deepcopy(net)  # one working copy per task; tables replaced per step
    cache = _SE.setdefault("observability", {})
    rows = []
    for name, config in configs.items():
        readings = sensing.measure(state, np.zeros(96, dtype=int), config, layout, model, rng)
        sub, remote = sensing.flagged_steps(readings, config, layout)
        inputs = estimator_inputs(config)
        bare = numerical_observability(
            add_measurements(net, readings, SE_STEPS[0], inputs, layout, model)
        )
        for t in SE_STEPS:
            if not daylight[t]:
                continue
            m = add_measurements(
                work, readings, t, inputs, layout, model, pseudo_measurements(series, day, t),
                inplace=True,
            )  # fmt: skip
            result = estimate(m, cache)
            row = {
                "config": name, "truth": truth, "day": day, "step": t,
                "observable_without_pseudo": bare["observable"],
                "rank_without_pseudo": bare["rank"], "states": bare["states"],
                "observable": result["observable"], "success": result["success"],
                "event": bool(events["any"][t]), "event_voltage": bool(events["voltage"][t]),
                "event_line": bool(events["line"][t]), "event_trafo": bool(events["trafo"][t]),
                "direct_flag": bool(sub[t] or remote[t]),
            }  # fmt: skip
            if result["success"]:
                estimated = np.array([result["vm"][b] for b in layout.buses])
                true_vm = state["vm"][t, 0]
                worst = int(np.argmax(true_vm))
                row.update(
                    rmse_vm=float(np.sqrt(np.mean((estimated - true_vm) ** 2))),
                    max_abs_error_vm=float(np.max(np.abs(estimated - true_vm))),
                    error_at_highest_bus=float(estimated[worst] - true_vm[worst]),
                    se_flag=bool(
                        (estimated > limits).any()
                        or (result["line_loading"] > 100.0).any()
                        or readings["trafo_loading"][t, 0] > 100.0
                    ),
                )
            rows.append(row)
    return rows


def se_study(code: str, days, truths, configs: dict, truth_norms: dict, cache_dir, model,
             workers: int) -> list[dict]:  # fmt: skip
    """Run `_se_task` over every (truth, sampled day) in parallel; returns step rows."""
    from concurrent.futures import ProcessPoolExecutor

    from gridpulse import sensing

    sample = [d for d in days if d % SE_DAY_STRIDE == 0]
    tasks = [
        (code, truth, day, configs, truth_norms[truth][day], cache_dir, model,
         sensing.seed_of("se", code, truth, day))
        for truth in truths
        for day in sample
    ]  # fmt: skip
    rows: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_se_init, initargs=(code,)) as pool:
        for part in pool.map(_se_task, tasks, chunksize=1):
            rows += part
    return rows


def se_detector(net, series: dict, config, layout, model, rating: np.ndarray):
    """A detector for `sensing.run_feedback_policy` that adds state-estimation inference
    to direct detection: on steps with measured reverse flow (where PV-driven violations
    can occur) and no direct alarm, it estimates the state from the substation readings
    and pseudo-measurements; the pseudo PV injection respects the cap that was applied.
    Labelled model-based inference, not measurement."""
    from gridpulse import sensing
    from gridpulse.grid_study import CAP_LEVELS

    work = copy.deepcopy(net)
    cache: dict = {}
    limits = np.array(layout.max_vm)
    inputs = estimator_inputs(config)

    def detect(day: int, levels, readings) -> tuple[np.ndarray, np.ndarray]:
        sub, remote = sensing.flagged_steps(readings, config, layout)
        candidates = np.flatnonzero((readings["trafo_p"][:, 0] > 0) & ~sub)
        for t in candidates:
            pseudo = pseudo_measurements(
                series, day, int(t), cap=CAP_LEVELS[levels[t]], rating=rating
            )
            m = add_measurements(
                work, readings, int(t), inputs, layout, model, pseudo, inplace=True
            )
            result = estimate(m, cache)
            if result["success"]:
                estimated = np.array([result["vm"][b] for b in layout.buses])
                sub[t] = bool((estimated > limits).any() or (result["line_loading"] > 100.0).any())
        return sub, remote

    return detect


def _se_feedback_task(task: tuple) -> dict:
    """One (network, truth) run of `replay_aci` whose feedback uses substation readings
    plus state-estimation inference (protocol s. 7.4; run only if the gate opened)."""
    from gridpulse import dual_study as ds
    from gridpulse import sensing
    from gridpulse.grid import absolute_profiles

    code, truth, stage, phase4_cache, fullstate_cache = task
    contexts, layout, _ = sensing.build_contexts(
        code, phase4_cache, fullstate_cache, stage, truths=(truth,)
    )
    ctx = contexts[truth]
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    series = bus_series(net, grid_study.daily_arrays(absolute_profiles(net)))
    config = sensing.Config("substation", transformer=True, heads=layout.feeder_heads)
    model = sensing.CONDITIONS[sensing.PRIMARY]
    detector = se_detector(net, series, config, layout, model, ctx.rating)
    seed = sensing.seed_of(truth, sensing.PRIMARY, "substation")
    records = sensing.run_feedback_policy(
        ctx, "replay_aci", config, model, seed, ds.OnlineSettings(), detector
    )
    return {
        "network": code,
        "truth": truth,
        "summary": sensing.summarise_decisions(records, ds.OnlineSettings()),
        "daily": {
            "avoidable_violation_steps": [r["avoidable_violation_steps"] for r in records],
            "curtailed_mwh": [r["curtailed_mwh"] for r in records],
        },
    }


def se_feedback_runs(networks, truths, stage, phase4_cache, fullstate_cache, workers) -> list:
    from concurrent.futures import ProcessPoolExecutor

    tasks = [(c, t, stage, phase4_cache, fullstate_cache) for c in networks for t in truths]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_se_feedback_task, tasks, chunksize=1))
