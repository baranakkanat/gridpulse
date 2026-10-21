"""Phase 8 exploratory addendum Q1-L1, implemented exactly as registered in
`docs/provenance/phase9/q1_addendum_registration.md` (committed 3ce2693, sha256
159df990be7638c9c964779da4a4272b632ece705af983e620b5768a8b0139d0).

The question (registration s. 1): under the `line_local` truth, how large is the idealised
best-case truth-minus-nominal LV bus-voltage residual at the no-cap level, and does it reach
the floor a smart-meter-class sensor could resolve? Delta is an upper bound on any operational
residual, so bands A and B are strong negative results and band C is only permissive.

Run from the repository root:

    PYTHONDONTWRITEBYTECODE=1 .venv/bin/python analysis/phase9/q1_voltage_residual.py

The four stages run in the registered order (s. 7):

0. hash checks of the two frozen Phase 8 outputs and of every `freeze.json` code hash;
1. the s. 5 inputs, every threshold, the s. 6 predictions and the stressed-line facts,
   computed and written **before any `vm` array is loaded**;
2. the residual statistics of s. 4, from the `vm` legs of `robust_study.truth_context`;
3. the Stage 0 checks again.

No solver and no power flow is run: the voltage legs are read from the frozen Phase 5 and
Phase 8 caches through the repository's own loaders. Nothing outside `analysis/phase9/` is
written.

Two implementation notes, both recorded in the results file:

- Stage 1 recomputes the network facts, the scored days and the PV availability from
  `dual_study.variant_network` / `grid_study.daily_arrays` exactly as
  `sensing.build_contexts` does, because `build_contexts` would load the `vm` arrays that
  Stage 1 must not see. Stage 2 then uses `robust_study.truth_context` unchanged.
- The registration fixes the refuse-to-overwrite rule for the Stage 2 results file. Stage 1's
  inputs file is also never overwritten: if it exists, the recomputed inputs must equal it
  byte for byte, so no threshold can change after a `vm` array has been loaded.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
RESULTS = HERE / "results"
INPUTS_FILE = RESULTS / "registration_inputs.json"
RESULTS_FILE = RESULTS / "q1_results.json"

REGISTRATION = "docs/provenance/phase9/q1_addendum_registration.md"
REGISTRATION_SHA256 = "159df990be7638c9c964779da4a4272b632ece705af983e620b5768a8b0139d0"

# --- registered constants (registration s. 2, s. 4-s. 8) -----------------------------------

TRUTH = "line_local"
STAGE = "evaluation"
NETWORKS = ("1-LV-semiurb4--2-sw", "1-LV-urban6--2-sw")
CREATED_VIOLATIONS = {"1-LV-semiurb4--2-sw": 399, "1-LV-urban6--2-sw": 319}  # s. 2
K_ALL_REGISTERED = {"1-LV-semiurb4--2-sw": 43, "1-LV-urban6--2-sw": 58}  # s. 5
B_METER_REGISTERED = {"1-LV-semiurb4--2-sw": (26, 43), "1-LV-urban6--2-sw": (18, 19)}  # s. 4
PLACEMENTS = "outputs/noise_study/development_results.json"  # frozen Phase 6 design
LEVEL = 0  # CAP_LEVELS[0] = 1.0, no cap (src/gridpulse/grid_study.py:42)

ALPHA = 0.05  # family-wise, Bonferroni two-sided
SIGMA_PRIMARY = 0.01  # `realistic` and `biased_meters_matched` (noise_study.py:38,43-45)
SIGMA_GRID = (0.003, 0.005, 0.01, 0.02)  # the primary plus the s. 5 sensitivity
BIAS_RATIO = 0.98  # F_bias = 0.98 * sigma_tot, the matched per-meter offset
MATCHED_RANDOM_RATIO = 0.2  # contrast random arm of `biased_meters_matched`
REMOTE_MISSING = 0.05  # `realistic`; D_eff = (1 - 0.05) * D
MEDIAN_FACTOR = math.sqrt(math.pi / 2)  # 1.2533, the median's floor factor
REFERENCE_LINE_PU = 0.0003  # busbar daily-mean floor, docs/phase7_results.md:295; label only
NOMINAL_KV = 0.4  # V in the s. 6 magnitude prediction
R_FACTOR = 1.5  # stress.LINE_R_FACTOR; the increment 0.5 is the prediction's factor

# Stage 0 (s. 7) -- frozen Phase 8 outputs and the two logged post-freeze exceptions.
FROZEN_OUTPUTS = {
    "outputs/robust_study/evaluation_results.json": (
        "a70c0aed35f97d48eb1587c7f7e5b0eec995c4d7c523cccd6dcbef8afff802ef"
    ),
    "outputs/robust_study/freeze.json": (
        "d191bb5dd416b7b9d5ed306f6cb2b68bcbe170aef753ad2cbb96a2114ab762bc"
    ),
}
FREEZE_FILE = "outputs/robust_study/freeze.json"
REGISTRATION_LOG = "docs/provenance/phase8/registration_log.txt"
LOG_EXCEPTIONS = ("src/gridpulse/__main__.py", "src/gridpulse/demonstrator.py")
EXPECTED_CODE_ENTRIES = 27
EXPECTED_MODULES = 24
EXPECTED_ENVIRONMENT = ("pyproject.toml", "uv.lock", "docs/phase8_protocol.md")

# Recorded from frozen output, not computed (s. 8: L0 and L2). The pairs are in the scope
# order of s. 2 (semiurb4, urban6); 878 is semiurb4 (docs/phase8_results.md:90).
RECORDED_L0_L2 = {
    "L0_busbar_mean_v_hat_abs_delta_max_pu": 8.1e-05,
    "L2_oracle_intervention_steps": {"1-LV-semiurb4--2-sw": 878, "1-LV-urban6--2-sw": 632},
    "L2_action_match_max_percent": {"1-LV-semiurb4--2-sw": 54.6, "1-LV-urban6--2-sw": 49.5},
    "note": (
        "recorded from the frozen Phase 8 output as registered (s. 8); not recomputed here. "
        "The S(i) observability rank is dropped."
    ),
}

PREDICTION_TEXT = {
    "magnitude": "0.5 * R * P / V^2 p.u. at buses downstream of the stressed line",
    "busbar": "approximately 0",
    "shape": "monotone in downstream PV x R, with the argmax downstream of the stressed line",
    "night_sign": "HYPOTHESIS: the night residual has the opposite sign to the daylight one",
    "rule": "any contradiction is reported as a contradiction, not reconciled",
}


# --- small pure helpers (unit-tested on synthetic arrays) ----------------------------------


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def z_bonferroni(k: int, alpha: float = ALPHA) -> float:
    """z_K = Phi^-1(1 - (alpha/2)/K), the two-sided Bonferroni critical value (s. 5)."""
    if k < 1:
        raise ValueError(f"K must be at least 1, got {k}")
    return statistics.NormalDist().inv_cdf(1.0 - (alpha / 2.0) / k)


def band(value: float, low: float, high: float) -> str:
    """The registered band of one statistic (s. 5): A below `low`, B in [low, high), C at or
    above `high`. `value` is already an absolute value."""
    if not high >= low:
        raise ValueError(f"band thresholds out of order: low={low}, high={high}")
    if value < low:
        return "A"
    if value < high:
        return "B"
    return "C"


def floors(sigma: float, n_day: float, n_night: float, d_eff: float, estimator: str) -> dict:
    """The s. 5 floors at one sigma_tot.

    `estimator`:
    - "mean": as registered;
    - "median_averaging_floors": the robustness check with the median's factor sqrt(pi/2) on
      the floors that average over days (F_ind and both contrast floors);
    - "median_all_floors": the same factor on every floor, including the per-meter offset.

    The registration says "the median over days is reported as a robustness check, with its
    floor x sqrt(pi/2)" without naming the floors; both readings are reported so neither is
    lost. They differ only in the B/C boundary of the level test.
    """
    if estimator not in ("mean", "median_averaging_floors", "median_all_floors"):
        raise ValueError(f"unknown estimator {estimator!r}")
    scale = 1.0 if estimator == "mean" else MEDIAN_FACTOR
    bias_scale = MEDIAN_FACTOR if estimator == "median_all_floors" else 1.0
    root = math.sqrt(1.0 / n_day + 1.0 / n_night) / math.sqrt(d_eff)
    return {
        "F_bias": BIAS_RATIO * sigma * bias_scale,
        "F_ind": sigma / math.sqrt(n_day * d_eff) * scale,
        "F_C_matched": MATCHED_RANDOM_RATIO * sigma * root * scale,
        "F_C_realistic": sigma * root * scale,
    }


def thresholds(sigma: float, n_day: float, n_night: float, d_eff: float, z: float,
               estimator: str) -> dict:  # fmt: skip
    """Band boundaries on |m| (level) and |k| (contrast) at one sigma_tot and one z_K."""
    f = floors(sigma, n_day, n_night, d_eff, estimator)
    return {
        **f,
        "z": z,
        "level": {"low": z * f["F_ind"], "high": z * f["F_bias"]},
        "contrast": {"low": z * f["F_C_matched"], "high": z * f["F_C_realistic"]},
    }


def partition_days(days, daylight_counts, steps: int = 96) -> tuple:
    """Split scored days into those on which the registered statistics are defined and those
    without a single daylight step.

    Registration s. 4 averages, over days, the mean of Delta over the daylight steps of a day.
    On a scored day with no daylight step (an overcast SimBench winter day: the PV profile is
    zero at all 96 quarter-hours) that inner mean does not exist, and the registration fixes
    no rule for it. Such a day is therefore not part of the average over days; it is listed,
    counted and reported. A day with no night step would leave the contrast undefined and is
    refused, because it would have to be dropped from one co-primary statistic only.
    """
    days = [int(d) for d in days]
    counts = [int(c) for c in daylight_counts]
    if len(days) != len(counts):
        raise ValueError("one daylight count per scored day is required")
    full = [d for d, c in zip(days, counts, strict=True) if c == steps]
    if full:
        raise RuntimeError(f"scored days without a night step: {full}; the registration fixes "
                           "no rule for them")  # fmt: skip
    defined = [d for d, c in zip(days, counts, strict=True) if c > 0]
    zero = [d for d, c in zip(days, counts, strict=True) if c == 0]
    return defined, zero


def day_statistics(delta: np.ndarray, daylight: np.ndarray) -> tuple:
    """One day's per-bus daylight mean, night mean and day-night contrast of Delta.

    `delta`: (steps, buses); `daylight`: (steps,) boolean (`available.sum(axis=1) > 0`, as
    margin_study.py:123). A per-bus constant added to either leg cancels in the contrast.
    """
    delta = np.asarray(delta, dtype=float)
    daylight = np.asarray(daylight, dtype=bool)
    if delta.ndim != 2 or daylight.shape != (delta.shape[0],):
        raise ValueError(f"shapes do not match: {delta.shape} and {daylight.shape}")
    if not daylight.any() or not (~daylight).any():
        raise ValueError("a scored day has no daylight or no night step; the registration "
                         "fixes no rule for it")  # fmt: skip
    day = delta[daylight].mean(axis=0)
    night = delta[~daylight].mean(axis=0)
    return day, night, day - night


def aggregate(per_day: np.ndarray) -> dict:
    """The registered estimator (mean over days) and its median robustness check."""
    per_day = np.asarray(per_day, dtype=float)
    return {
        "mean": per_day.mean(axis=0),
        "median": np.median(per_day, axis=0),
    }


def rank_correlation(x, y) -> float:
    """Spearman rank correlation, for the descriptive shape check of s. 6."""
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.size < 3:
        return float("nan")

    def ranks(values):
        """Ranks with ties averaged, so a constant vector has no rank variation."""
        order = np.argsort(values, kind="stable")
        ordered = values[order]
        out = np.empty(values.size, dtype=float)
        start = 0
        while start < values.size:
            stop = start
            while stop + 1 < values.size and ordered[stop + 1] == ordered[start]:
                stop += 1
            out[order[start : stop + 1]] = (start + stop) / 2.0
            start = stop + 1
        return out

    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def json_text(payload) -> str:
    return json.dumps(payload, indent=2, allow_nan=False) + "\n"


def write_new_json(path: Path, payload) -> str:
    """Write `payload` only if `path` does not exist; return the file's sha256."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json_text(payload)
    try:
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as error:
        raise RuntimeError(f"refusing to overwrite {path}") from error
    with os.fdopen(handle, "w") as stream:
        stream.write(text)
    return sha256_text(text)


def write_inputs_json(path: Path, payload) -> str:
    """Stage 1's file: written once and then immutable. An existing file must hold exactly
    these inputs, so no threshold can change after a `vm` array has been loaded."""
    path = Path(path)
    text = json_text(payload)
    if path.exists():
        if path.read_text() != text:
            raise RuntimeError(f"{path} exists and differs from the recomputed inputs; the "
                               "registered inputs are fixed and are not rewritten")  # fmt: skip
        return sha256_text(text)
    return write_new_json(path, payload)


def load_stage1(path: Path = INPUTS_FILE) -> dict:
    """Stage 2's guard: it refuses to start without Stage 1's file."""
    path = Path(path)
    if not path.exists():
        raise RuntimeError(f"{path} is missing; Stage 1 must run and write the registered "
                           "inputs before any vm array is loaded")  # fmt: skip
    return json.loads(path.read_text())


def _plain(value):
    """Recursively convert numpy scalars and arrays to plain JSON values. A non-finite float
    (an undefined rank correlation) becomes its string, so the output stays valid JSON."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return [_plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


# --- Stage 0 and Stage 3: hash checks (registration s. 7) ----------------------------------


def latest_log_hashes(path: Path) -> dict:
    """The last-recorded sha256 of every path in the Phase 8 registration log."""
    out = {}
    for line in Path(path).read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(\S+)", line.strip())
        if match:
            out[match.group(2)] = match.group(1)
    return out


def hash_checks() -> dict:
    """Stage 0 / Stage 3. Raises RuntimeError on any mismatch that the registration does not
    except."""
    report: dict = {"outputs": {}, "code": {}, "mismatches": []}
    for name, expected in FROZEN_OUTPUTS.items():
        actual = sha256_file(REPO / name)
        report["outputs"][name] = {"expected": expected, "actual": actual,
                                   "ok": actual == expected}  # fmt: skip
        if actual != expected:
            report["mismatches"].append(name)

    frozen = json.loads((REPO / FREEZE_FILE).read_text())["code_sha256"]
    logged = latest_log_hashes(REPO / REGISTRATION_LOG)
    modules = sorted(n for n in frozen if n.startswith("src/gridpulse/"))
    environment = sorted(n for n in frozen if not n.startswith("src/gridpulse/"))
    checked, exceptions = {}, {}
    for name, expected in sorted(frozen.items()):
        actual = sha256_file(REPO / name)
        if name in LOG_EXCEPTIONS:
            reference = logged.get(name)
            ok = reference is not None and actual == reference
            exceptions[name] = {
                "frozen": expected, "latest_logged": reference, "actual": actual, "ok": ok,
                "why": "logged post-freeze, presentation-only change "
                       f"({REGISTRATION_LOG}:77)",
            }  # fmt: skip
        else:
            ok = actual == expected
            checked[name] = {"expected": expected, "actual": actual, "ok": ok}
        if not ok:
            report["mismatches"].append(name)

    report["code"] = {
        "freeze_file": FREEZE_FILE,
        "entries": len(frozen),
        "entries_expected": EXPECTED_CODE_ENTRIES,
        "modules": len(modules),
        "modules_expected": EXPECTED_MODULES,
        "environment": environment,
        "environment_expected": sorted(EXPECTED_ENVIRONMENT),
        "reconciliation_of_27": (
            f"{len(modules)} src/gridpulse/*.py modules plus {', '.join(environment)} "
            f"= {len(frozen)} entries, the \"27\" of {REGISTRATION_LOG}:56"
        ),
        "equal_to_freeze": checked,
        "exceptions": exceptions,
    }
    report["registration"] = {
        "path": REGISTRATION,
        "sha256": sha256_file(REPO / REGISTRATION),
        "expected": REGISTRATION_SHA256,
        "note": "provenance only; the registration fixes no self-check",
    }
    counts_ok = (
        len(frozen) == EXPECTED_CODE_ENTRIES
        and len(modules) == EXPECTED_MODULES
        and environment == sorted(EXPECTED_ENVIRONMENT)
    )
    report["counts_ok"] = counts_ok
    report["passed"] = counts_ok and not report["mismatches"]
    if not report["passed"]:
        raise RuntimeError(
            f"hash checks failed: counts_ok={counts_ok}, mismatches={report['mismatches']}"
        )
    return report


# --- Stage 1: inputs, thresholds and predictions, with no `vm` array loaded ----------------


def network_facts(code: str) -> dict:
    """Scored days, PV availability, LV buses and the stressed cable of one network, from the
    network and the profiles only. No state file is opened, so no `vm` array is loaded."""
    import networkx as nx

    from gridpulse import dual_study as ds
    from gridpulse import grid, grid_study
    from gridpulse import sensing as sn
    from gridpulse import stress as st

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    layout = sn.network_layout(net)
    available = grid_study.daily_arrays(grid.absolute_profiles(net))["sgen_p_mw"]
    decision = range(grid_study.FIRST_DECISION_DAY, ds.LAST_DAY + 1)
    days = [d for d in grid_study.period_days(STAGE) if d in decision]

    daylight = np.array([int((available[d].sum(axis=1) > 0).sum()) for d in days])
    defined, zero_daylight = partition_days(days, daylight, available.shape[1])

    # the stressed cable of `line_local` and the buses below it (stress.local_line's own tree)
    line = int(st.local_line(net, layout))
    graph = nx.Graph()
    for index, row in net.line.iterrows():
        graph.add_edge(int(row.from_bus), int(row.to_bus), line=int(index))
    tree = nx.bfs_tree(graph, layout.lv_busbar)
    below = None
    for upstream, downstream in tree.edges():
        if graph.edges[upstream, downstream]["line"] == line:
            below = sorted(nx.descendants(tree, downstream) | {downstream})
            break
    if below is None:
        raise RuntimeError(f"{code}: the stressed line {line} is not a tree edge")

    sgen_bus = net.sgen["bus"].to_numpy(dtype=int)
    sgen_mva = net.sgen["sn_mva"].to_numpy(dtype=float)
    mask = np.isin(sgen_bus, below)
    installed = float(sgen_mva[mask].sum())
    if installed <= 0:
        raise RuntimeError(f"{code}: no installed PV below the stressed line")
    daylight_steps = np.concatenate(
        [available[d][available[d].sum(axis=1) > 0][:, mask] for d in defined]
    )
    mean_mw = float(daylight_steps.sum(axis=1).mean())
    r_per_km = float(net.line.at[line, "r_ohm_per_km"])
    length = float(net.line.at[line, "length_km"])
    resistance = r_per_km * length

    return {
        "layout": layout,
        "days": days,
        "days_with_daylight": defined,
        "days_without_daylight": zero_daylight,
        "daylight_per_day": daylight,
        "k_all": len(layout.buses),
        "line": line,
        "line_facts": {
            "index": line,
            "from_bus": int(net.line.at[line, "from_bus"]),
            "to_bus": int(net.line.at[line, "to_bus"]),
            "r_ohm_per_km_recorded": r_per_km,
            "length_km": length,
            "R_recorded_ohm": resistance,
            "R_truth_ohm": R_FACTOR * resistance,
            "max_i_ka_recorded": float(net.line.at[line, "max_i_ka"]),
            "is_feeder_head": line in layout.feeder_heads,
        },
        "downstream": {
            "buses": below,
            "columns": [layout.buses.index(b) for b in below if b in layout.buses],
            "installed_pv_sn_mva": installed,
            "mean_daylight_available_mw": mean_mw,
            "mean_daylight_availability_fraction": mean_mw / installed,
        },
    }


def stage1() -> dict:
    """Registration s. 5 inputs, every threshold, the s. 6 predictions and the stressed-line
    facts. Nothing here opens a state file."""
    placements = json.loads((REPO / PLACEMENTS).read_text())["placements"]
    evaluation = json.loads((REPO / "outputs/robust_study/evaluation_results.json").read_text())

    networks = {}
    for code in NETWORKS:
        facts = network_facts(code)
        layout = facts["layout"]
        days, daylight = facts["days"], facts["daylight_per_day"]
        defined, zero_daylight = facts["days_with_daylight"], facts["days_without_daylight"]
        d = len(days)
        d_eff = (1.0 - REMOTE_MISSING) * d
        n_day = float(np.median(daylight))
        n_night = float(np.median(96 - daylight))
        # the same inputs over the days the estimator can average (see `partition_days`),
        # fixed here, before any vm array is loaded; reported, never a registered verdict
        kept = np.array([c for day, c in zip(days, daylight, strict=True) if day in set(defined)])
        d_defined = len(defined)
        d_eff_defined = (1.0 - REMOTE_MISSING) * d_defined
        n_day_defined = float(np.median(kept))
        n_night_defined = float(np.median(96 - kept))

        k_all = facts["k_all"]
        if k_all != K_ALL_REGISTERED[code]:
            raise RuntimeError(f"{code}: {k_all} LV buses, the registration fixes "
                               f"{K_ALL_REGISTERED[code]}")  # fmt: skip
        b_meter = tuple(int(b) for b in placements[code]["topology"][:2])
        if tuple(sorted(b_meter)) != tuple(sorted(B_METER_REGISTERED[code])):
            raise RuntimeError(f"{code}: B_meter {b_meter}, the registration fixes "
                               f"{B_METER_REGISTERED[code]}")  # fmt: skip
        z_meter, z_all = z_bonferroni(2), z_bonferroni(k_all)

        installed = facts["downstream"]["installed_pv_sn_mva"]
        p_mw = facts["downstream"]["mean_daylight_available_mw"]
        resistance = facts["line_facts"]["R_recorded_ohm"]
        predicted = 0.5 * resistance * p_mw / NOMINAL_KV**2

        created = evaluation[code][TRUTH]["no_action"]["created"]
        networks[code] = {
            "network": code,
            "truth": TRUTH,
            "stage": STAGE,
            "level_index": LEVEL,
            "days": {
                "count": d,
                "D_eff": d_eff,
                "first": days[0],
                "last": days[-1],
                "list": days,
                "with_daylight_count": d_defined,
                "with_daylight": defined,
                "without_daylight": zero_daylight,
                "note": "the registered D is every scored day; the statistics of s. 4 are "
                        "undefined on a day with no daylight step and average over the "
                        "with_daylight set (see `partition_days`)",
            },  # fmt: skip
            "steps": {
                "n_day_median": n_day,
                "n_night_median": n_night,
                "daylight_per_day_min": int(daylight.min()),
                "daylight_per_day_max": int(daylight.max()),
                "n_day_median_with_daylight": n_day_defined,
                "n_night_median_with_daylight": n_night_defined,
            },
            "buses": {
                "K_all": k_all,
                "K_meter": 2,
                "B_meter": list(b_meter),
                "B_meter_columns": [layout.buses.index(b) for b in b_meter],
                "busbar_bus": layout.lv_busbar,
                "busbar_column": layout.buses.index(layout.lv_busbar),
                "lv_buses": list(layout.buses),
                "resistance_distance_ohm": [layout.distance[b] for b in layout.buses],
            },
            "z": {"z_meter": z_meter, "z_all": z_all, "alpha": ALPHA},
            "stressed_line": facts["line_facts"],
            "downstream": {k: v for k, v in facts["downstream"].items()},
            "prediction": {
                **PREDICTION_TEXT,
                "R_ohm": resistance,
                "P_mw": p_mw,
                "installed_pv_sn_mva": installed,
                "V_kv": NOMINAL_KV,
                "level_pu_downstream": predicted,
                "busbar_pu": 0.0,
            },
            "thresholds": {
                estimator: {
                    f"{sigma:g}": {
                        "sigma_tot": sigma,
                        "primary": sigma == SIGMA_PRIMARY,
                        "meter": thresholds(sigma, n_day, n_night, d_eff, z_meter, estimator),
                        "all": thresholds(sigma, n_day, n_night, d_eff, z_all, estimator),
                    }
                    for sigma in SIGMA_GRID
                }
                for estimator in ("mean", "median_averaging_floors", "median_all_floors")
            },
            "thresholds_with_daylight_days": {
                estimator: {
                    f"{sigma:g}": {
                        "sigma_tot": sigma,
                        "primary": sigma == SIGMA_PRIMARY,
                        "meter": thresholds(sigma, n_day_defined, n_night_defined,
                                            d_eff_defined, z_meter, estimator),
                        "all": thresholds(sigma, n_day_defined, n_night_defined, d_eff_defined,
                                          z_all, estimator),
                    }
                    for sigma in SIGMA_GRID
                }
                for estimator in ("mean", "median_averaging_floors", "median_all_floors")
            },  # fmt: skip
            "thresholds_note": (
                "`thresholds` are the registered ones (D = every scored day). "
                "`thresholds_with_daylight_days` repeat the same formulas over the days the "
                "estimator can average; reported for transparency, not a registered verdict. "
                "Both sets are fixed in Stage 1, before any vm array is loaded."
            ),
            "scope_check": {
                "created_violations_frozen": created,
                "created_violations_registered": CREATED_VIOLATIONS[code],
                "ok": created == CREATED_VIOLATIONS[code],
            },
        }
        if not networks[code]["scope_check"]["ok"]:
            raise RuntimeError(f"{code}: frozen created violations {created}, the registration "
                               f"records {CREATED_VIOLATIONS[code]}")  # fmt: skip

    return {
        "stage": "1 (registration s. 5, s. 6)",
        "registration": {"path": REGISTRATION, "sha256": REGISTRATION_SHA256},
        "constants": {
            "alpha": ALPHA, "sigma_primary": SIGMA_PRIMARY, "sigma_grid": list(SIGMA_GRID),
            "bias_ratio": BIAS_RATIO, "matched_random_ratio": MATCHED_RANDOM_RATIO,
            "remote_missing": REMOTE_MISSING, "median_factor": MEDIAN_FACTOR,
            "reference_line_pu": REFERENCE_LINE_PU, "cap_level_index": LEVEL,
            "line_r_factor": R_FACTOR,
        },  # fmt: skip
        "sources": {
            "placements": PLACEMENTS,
            "truth_leg": "robust_study.truth_context -> stress.load(outputs/robust_study/"
                         "fullstate_cache, line_local)",
            "nominal_leg": "robust_study.truth_context -> fullstate.load_states("
                           "outputs/sense_study/fullstate_cache, nominal)",
            "no_vm_loaded_in_stage1": True,
        },  # fmt: skip
        "recorded": RECORDED_L0_L2,
        "networks": networks,
    }


# --- Stage 2: the statistics (registration s. 4) -------------------------------------------


def residuals(code: str, days: list[int], averaged: list[int]) -> dict:
    """Per-day, per-bus Delta statistics at the no-cap level, from the two `vm` legs.

    `days` are Stage 1's scored days and `averaged` the subset the registered statistics are
    defined on; both are checked against the context before any array is read.
    """
    from gridpulse import robust_study

    ctx, layout, _ = robust_study.truth_context(
        code, TRUTH, STAGE, REPO / "outputs/dual_study/physics_cache",
        REPO / "outputs/sense_study/fullstate_cache",
    )  # fmt: skip
    scored = list(ctx.days)
    if scored != list(days):
        raise RuntimeError(f"{code}: the context's scored days differ from Stage 1's")
    counts = [int((ctx.available[d].sum(axis=1) > 0).sum()) for d in scored]
    defined, zero_daylight = partition_days(scored, counts)
    if defined != list(averaged):
        raise RuntimeError(f"{code}: the days with daylight differ from Stage 1's")

    day_rows, night_rows, contrast_rows, nonfinite = [], [], [], 0
    for d in defined:
        truth = np.asarray(ctx.states[d]["vm"], dtype=float)[:, LEVEL, :]
        nominal = np.asarray(ctx.nominal_states[d]["vm"], dtype=float)[:, LEVEL, :]
        nonfinite += int((~np.isfinite(truth)).sum() + (~np.isfinite(nominal)).sum())
        day, night, contrast = day_statistics(
            truth - nominal, ctx.available[d].sum(axis=1) > 0
        )
        day_rows.append(day)
        night_rows.append(night)
        contrast_rows.append(contrast)
    if nonfinite:
        raise RuntimeError(f"{code}: {nonfinite} non-finite vm entries at the no-cap level; "
                           "the registration fixes no rule for failed flows")  # fmt: skip

    return {
        "buses": list(layout.buses),
        "level": aggregate(np.stack(day_rows)),
        "night": aggregate(np.stack(night_rows)),
        "contrast": aggregate(np.stack(contrast_rows)),
        "nonfinite_vm_entries": nonfinite,
        "days": scored,
        "days_averaged": defined,
        "days_without_daylight": zero_daylight,
    }


def verdicts(value: float, inputs: dict, estimator: str, kind: str, scope: str,
             source: str = "thresholds") -> dict:  # fmt: skip
    """The band of one statistic at every registered sigma_tot."""
    out = {}
    for key, entry in inputs[source][estimator].items():
        limits = entry[scope][kind]
        out[key] = {
            "sigma_tot": entry["sigma_tot"],
            "primary": entry["primary"],
            "band": band(abs(value), limits["low"], limits["high"]),
            "low": limits["low"],
            "high": limits["high"],
        }
    return out


def observed(code: str, inputs: dict, stats: dict) -> dict:
    """Registration s. 4 statistics, the s. 5 bands and the s. 6 predictions against what was
    observed, for one network."""
    buses = stats["buses"]
    columns = inputs["buses"]["B_meter_columns"]
    busbar = inputs["buses"]["busbar_column"]
    downstream = set(inputs["downstream"]["buses"])
    down_cols = [i for i, b in enumerate(buses) if b in downstream]
    z_meter = inputs["z"]["z_meter"]

    out: dict = {
        "network": code,
        "buses": buses,
        "days_scored": len(stats["days"]),
        "days_averaged": len(stats["days_averaged"]),
        "days_without_daylight": stats["days_without_daylight"],
        "nonfinite_vm_entries": stats["nonfinite_vm_entries"],
        "per_bus": {},
    }
    for name, source in (("m", "level"), ("k", "contrast"), ("night", "night")):
        out["per_bus"][name] = {
            "mean": stats[source]["mean"], "median": stats[source]["median"]
        }

    summary, extremes = {}, {}
    for label, source in (("M", "level"), ("C", "contrast")):
        for estimator, key in (("mean", "mean"), ("median", "median")):
            vector = np.abs(stats[source][key])
            meter_i = int(columns[int(np.argmax(vector[columns]))])
            all_i = int(np.argmax(vector))
            suffix = "" if estimator == "mean" else "_median"
            summary[f"{label}_meter{suffix}"] = float(vector[meter_i])
            summary[f"{label}_all{suffix}"] = float(vector[all_i])
            extremes[f"{label}{suffix}"] = {
                "meter_argmax_bus": buses[meter_i],
                "meter_argmax_column": meter_i,
                "all_argmax_bus": buses[all_i],
                "all_argmax_column": all_i,
                "all_argmax_is_downstream": buses[all_i] in downstream,
                "signed_at_all_argmax": float(stats[source][key][all_i]),
            }
    out["statistics"] = summary
    out["argmax"] = extremes

    for key, source in (("bands", "thresholds"),
                        ("bands_with_daylight_days", "thresholds_with_daylight_days")):  # fmt: skip
        block: dict = {}
        for estimator in ("mean", "median_averaging_floors", "median_all_floors"):
            suffix = "" if estimator == "mean" else "_median"
            block[estimator] = {
                "level_meter": verdicts(summary[f"M_meter{suffix}"], inputs, estimator, "level",
                                        "meter", source),  # fmt: skip
                "level_all": verdicts(summary[f"M_all{suffix}"], inputs, estimator, "level",
                                      "all", source),  # fmt: skip
                "contrast_meter": verdicts(summary[f"C_meter{suffix}"], inputs, estimator,
                                           "contrast", "meter", source),  # fmt: skip
                "contrast_all": verdicts(summary[f"C_all{suffix}"], inputs, estimator,
                                         "contrast", "all", source),  # fmt: skip
            }
        out[key] = block
    bands = out["bands"]
    primary = f"{SIGMA_PRIMARY:g}"
    out["primary_pair"] = {
        "sigma_tot": SIGMA_PRIMARY,
        "level_meter": bands["mean"]["level_meter"][primary]["band"],
        "contrast_meter": bands["mean"]["contrast_meter"][primary]["band"],
        "level_all": bands["mean"]["level_all"][primary]["band"],
        "contrast_all": bands["mean"]["contrast_all"][primary]["band"],
    }
    out["sigma_bias_required_pu"] = {
        "mean": summary["M_meter"] / z_meter,
        "median": summary["M_meter_median"] / z_meter,
        "definition": "M_meter / z_2 (registration s. 9)",
    }

    m = np.asarray(stats["level"]["mean"], dtype=float)
    k = np.asarray(stats["contrast"]["mean"], dtype=float)
    night = np.asarray(stats["night"]["mean"], dtype=float)
    predicted = inputs["prediction"]["level_pu_downstream"]
    argmax_col = extremes["M"]["all_argmax_column"]
    off = [i for i in range(len(buses)) if i not in down_cols]
    distances = np.asarray(inputs["buses"]["resistance_distance_ohm"], dtype=float)
    opposite = int(np.sum(np.sign(m) * np.sign(night) < 0))
    out["predictions_vs_observations"] = {
        "magnitude": {
            "predicted_pu": predicted,
            "observed_max_abs_m_downstream": float(np.abs(m[down_cols]).max()),
            "observed_mean_abs_m_downstream": float(np.abs(m[down_cols]).mean()),
            "observed_m_at_all_argmax": float(m[argmax_col]),
            "ratio_observed_over_predicted": (
                float(m[argmax_col] / predicted) if predicted else None
            ),
            "note": "R is the recorded (nominal) resistance, so 0.5 * R is the truth-minus-"
                    "nominal increment of the stressed cable (stress.LINE_R_FACTOR = 1.5)",
        },  # fmt: skip
        "busbar": {
            "predicted_pu": 0.0,
            "observed_m_pu": float(m[busbar]),
            "observed_k_pu": float(k[busbar]),
            "reference_line_pu": REFERENCE_LINE_PU,
        },
        "shape": {
            "all_argmax_bus": buses[argmax_col],
            "all_argmax_is_downstream": buses[argmax_col] in downstream,
            "held": bool(buses[argmax_col] in downstream),
            "max_abs_m_off_downstream": float(np.abs(m[off]).max()) if off else None,
            "spearman_abs_m_vs_resistance_distance_downstream": rank_correlation(
                distances[down_cols], np.abs(m[down_cols])
            ),
            "spearman_abs_m_vs_resistance_distance_all": rank_correlation(distances, np.abs(m)),
        },
        "night_sign": {
            "hypothesis": PREDICTION_TEXT["night_sign"],
            "m_at_all_argmax": float(m[argmax_col]),
            "night_at_all_argmax": float(night[argmax_col]),
            "opposite_at_all_argmax": bool(m[argmax_col] * night[argmax_col] < 0),
            "buses_with_opposite_sign": opposite,
            "buses_total": len(buses),
            "at_B_meter": [
                {"bus": buses[i], "m": float(m[i]), "night": float(night[i]),
                 "opposite": bool(m[i] * night[i] < 0)}
                for i in columns
            ],  # fmt: skip
        },
    }
    return out


def interpretation(pair: dict) -> str:
    """Registration s. 9, from the co-primary pair at sigma_tot = 0.01."""
    level, contrast = pair["level_meter"], pair["contrast_meter"]
    if level == "C":
        return ("level C: the Phase 8 register entry (docs/phase8_results.md:413) needs "
                "amending, for this best-case placement only")  # fmt: skip
    if contrast == "C":
        return ("contrast C with level A/B: a bias-invariant temporal signature the level test "
                "cannot see; a Phase 9 candidate for residual-pattern screening, not a "
                "detectability claim")  # fmt: skip
    return ("level and contrast both A or B: do not pursue meter-voltage detection of this "
            "error class in Phase 9; the standing remedy hypothesis (a corrected asset record "
            "or thermal monitoring) stands (docs/phase8_results.md:367,505)")  # fmt: skip


def stage2(inputs_path: Path = INPUTS_FILE, results_path: Path = RESULTS_FILE) -> dict:
    """Load the `vm` legs and compute s. 4. Refuses to start without Stage 1's file and
    refuses to overwrite an existing results file."""
    results_path = Path(results_path)
    if results_path.exists():
        raise RuntimeError(f"refusing to overwrite {results_path}")
    inputs = load_stage1(inputs_path)

    networks = {}
    for code in NETWORKS:
        per_network = inputs["networks"][code]
        stats = residuals(code, per_network["days"]["list"],
                          per_network["days"]["with_daylight"])  # fmt: skip
        entry = observed(code, per_network, stats)
        entry["interpretation"] = interpretation(entry["primary_pair"])
        networks[code] = entry
    return {"inputs": inputs, "recorded": RECORDED_L0_L2, "networks": networks}


# --- the run -------------------------------------------------------------------------------


def main() -> int:
    if Path.cwd().resolve() != REPO:
        print(f"run from the repository root ({REPO}); the Phase 8 caches are addressed "
              "relative to it", file=sys.stderr)  # fmt: skip
        return 2

    print("Stage 0: hash checks")
    stage0 = hash_checks()
    code = stage0["code"]
    print(f"  frozen outputs: {len(stage0['outputs'])} of {len(stage0['outputs'])} match")
    print(f"  freeze.json code hashes: {code['entries']} entries = {code['modules']} "
          f"src/gridpulse/*.py modules + {', '.join(code['environment'])}")  # fmt: skip
    print(f"  reconciliation of \"27\": {code['reconciliation_of_27']}")
    for name, entry in code["exceptions"].items():
        print(f"  exception {name}: equals its latest logged hash "
              f"{entry['latest_logged'][:12]}... ({entry['ok']})")  # fmt: skip
    print(f"  registration {REGISTRATION} sha256 {stage0['registration']['sha256'][:12]}... "
          f"(matches the dispatched hash: "
          f"{stage0['registration']['sha256'] == REGISTRATION_SHA256})")  # fmt: skip
    print("  Stage 0 passed")

    print("Stage 1: inputs, thresholds and predictions (no vm array loaded)")
    inputs = _plain(stage1())
    digest = write_inputs_json(INPUTS_FILE, inputs)
    print(f"  wrote {INPUTS_FILE.relative_to(REPO)}")
    print(f"  sha256 {digest}")
    for name, entry in inputs["networks"].items():
        primary = entry["thresholds"]["mean"][f"{SIGMA_PRIMARY:g}"]
        print(f"  {name}: D={entry['days']['count']} D_eff={entry['days']['D_eff']:.2f} "
              f"n_day={entry['steps']['n_day_median']:.0f} "
              f"n_night={entry['steps']['n_night_median']:.0f} K_all={entry['buses']['K_all']} "
              f"B_meter={entry['buses']['B_meter']}")  # fmt: skip
        print(f"    days with at least one daylight step: "
              f"{entry['days']['with_daylight_count']} of {entry['days']['count']}; "
              f"the statistics of s. 4 are undefined on the other "
              f"{len(entry['days']['without_daylight'])}")  # fmt: skip
        print(f"    stressed line {entry['stressed_line']['index']} "
              f"R={entry['stressed_line']['R_recorded_ohm']:.5f} ohm, "
              f"downstream PV {entry['downstream']['installed_pv_sn_mva']:.3f} MVA, "
              f"P={entry['prediction']['P_mw']:.5f} MW, "
              f"predicted {entry['prediction']['level_pu_downstream']:.3e} p.u.")  # fmt: skip
        print(f"    level thresholds {primary['meter']['level']['low']:.3e} / "
              f"{primary['meter']['level']['high']:.3e}; contrast "
              f"{primary['meter']['contrast']['low']:.3e} / "
              f"{primary['meter']['contrast']['high']:.3e} (meter, sigma_tot=0.01)")  # fmt: skip

    print("Stage 2: the statistics")
    results = _plain(stage2())
    results["stage0"] = stage0
    print("Stage 3: hash checks again")
    results["stage3"] = hash_checks()
    print("  Stage 3 passed")
    digest = write_new_json(RESULTS_FILE, results)
    print(f"  wrote {RESULTS_FILE.relative_to(REPO)}")
    print(f"  sha256 {digest}")

    for name, entry in results["networks"].items():
        stats, pair = entry["statistics"], entry["primary_pair"]
        print(f"  {name}: M_meter={stats['M_meter']:.3e} M_all={stats['M_all']:.3e} "
              f"C_meter={stats['C_meter']:.3e} C_all={stats['C_all']:.3e}")  # fmt: skip
        print(f"    bands at sigma_tot=0.01: level {pair['level_meter']} (meter) / "
              f"{pair['level_all']} (all), contrast {pair['contrast_meter']} (meter) / "
              f"{pair['contrast_all']} (all)")  # fmt: skip
        print(f"    sigma_bias_required = "
              f"{entry['sigma_bias_required_pu']['mean']:.3e} p.u.")  # fmt: skip
        print(f"    {entry['interpretation']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
