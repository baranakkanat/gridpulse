"""Phase 6: measurement integrity and noise-aware feedback (docs/phase6_protocol.md).

Reuses the Phase 5 decision contexts, placement design and feedback policy, with the
changes the Phase 5 reviews motivated:

- measurement noise tied to the observation identity (`sensing.NoiseBank`): sensors that
  two runs share see the same noise, whatever the configuration, rule or condition;
- alarm rules turning readings into violation feedback (`sensing.AlarmRule`): the Phase 5
  unfiltered rule, a metrology guard band, and persistence rules;
- a chi-square test on the state estimator's weighted residuals.

Ground truth enters only through `sensing.measure` (readings) and the scoring functions.
Placements are designed on development days only and reused unchanged in evaluation.
"""

from __future__ import annotations

import copy

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import sensing as sn
from gridpulse.uncertainty import block_bootstrap_mean

PROTOCOL = "docs/phase6_protocol.md"
MISMATCH = ("tap_raise_lv", "mv_high", "pv_fixed_095")

# Measurement conditions (protocol s. 4). Substation: busbar voltage 0.2 %, current and
# power 1 %. Smart-meter voltage 1 % (Phase 5), with the sensitivity values below.
_SUB = {"sigma_v_substation": 0.002, "sigma_loading": 0.01}
_REAL = {"remote_missing": 0.05, "remote_delay_days": 1, **_SUB}
CONDITIONS = {
    "exact": sn.MeasurementModel(),
    "noisy": sn.MeasurementModel(sigma_v_remote=0.01, **_SUB),
    "noisy_missing": sn.MeasurementModel(sigma_v_remote=0.01, remote_missing=0.05, **_SUB),
    "noisy_delayed": sn.MeasurementModel(sigma_v_remote=0.01, remote_delay_days=1, **_SUB),
    "realistic": sn.MeasurementModel(sigma_v_remote=0.01, **_REAL),
    "sigma_0.005": sn.MeasurementModel(sigma_v_remote=0.005, **_REAL),
    "sigma_0.02": sn.MeasurementModel(sigma_v_remote=0.02, **_REAL),
    "biased_meters": sn.MeasurementModel(sigma_v_remote=0.002, sigma_bias_remote=0.005, **_REAL),
    # amendment 6A: per-meter bias at the same total uncertainty as `realistic` (0.01 p.u.)
    "biased_meters_matched": sn.MeasurementModel(
        sigma_v_remote=0.002, sigma_bias_remote=0.0098, **_REAL
    ),
}
PRIMARY_CONDITION = "realistic"

RULES = {
    rule.name: rule
    for rule in (
        sn.AlarmRule("unfiltered"),
        sn.AlarmRule("guard2", guard=2.0),
        sn.AlarmRule("persist2", persistence=2),
        sn.AlarmRule("persist3", persistence=3),
        sn.AlarmRule("persist3_meters", persistence=3, scope="meters"),  # amendment 6A
    )
}
PRIMARY_RULE = "persist3_meters"  # amendment 6A (was "persist3")

CORE_CONFIGS = (
    "substation", "substation+1:topology", "substation+2:topology", "substation+4:topology",
    "substation+2:risk", "substation+2:mandatory", "substation+2:greedy_detect",
    "substation+2:decision_aware", "full",
)  # fmt: skip
REPLICATIONS = (1, 2, 3, 4)  # noise realisations beyond 0, for the configurations below
REPLICATED_CONFIGS = ("substation", "substation+2:topology", "substation+2:decision_aware", "full")
REPLICATED_CONDITIONS = ("realistic", "biased_meters_matched")
EXTRA = ("flagged_steps", "false_alarm_steps", "missed_steps", "intervention_steps")
BLOCK_DAYS = (7, 14, 28)  # 7 registered; 14 and 28 descriptive (amendment 6A)
MIN_EXCESS_MWH = 10.0  # H1 is not evaluable below this pooled noise-induced excess

# Registered paired comparisons (a minus b, per day), replication 0.
_T2, _DA, _R, _P = "substation+2:topology", "substation+2:decision_aware", "realistic", PRIMARY_RULE
PAIRS = (
    ((_T2, _R, _P), (_T2, _R, "unfiltered")),
    (("full", _R, _P), ("full", _R, "unfiltered")),
    ((_T2, _R, _P), (_T2, "exact", "unfiltered")),
    (("full", _R, _P), ("full", "exact", "unfiltered")),
    ((_T2, "exact", _P), (_T2, "exact", "unfiltered")),
    ((_T2, _R, _P), ("substation", _R, _P)),
    ((_DA, _R, _P), (_T2, _R, _P)),
    ((_T2, _R, "guard2"), (_T2, _R, _P)),
    ((_T2, _R, "persist3"), (_T2, _R, _P)),
)

# State estimation (protocol s. 6): Phase 5 sample, chi-square test on J = r' R^-1 r.
SE_CONFIGS = ("substation", "substation+2:topology")
CHI2_ALPHA = 0.01
GROSS_VM = 0.02  # p.u.: an estimate is grossly wrong above this largest voltage error ...
GROSS_LOADING = 20.0  # ... or this largest line-loading error (percentage points)


def run_key(config: str, condition: str, rule: str, replication: int = 0) -> str:
    return f"{config}/{condition}/{rule}/{replication}"


def configurations(layout: sn.Layout, n_lines: int, placements: dict) -> dict[str, sn.Config]:
    base = sn.Config("substation", transformer=True, heads=layout.feeder_heads)
    out = {"substation": base, "full": sn.standard_configs(layout, n_lines)["full"]}
    for rule, buses in placements.items():
        for k in sn.BUDGETS:
            name = f"substation+{k}:{rule}"
            out[name] = sn.with_remote(base, buses[:k], name)
    return out


def run_plan(names) -> list[tuple[str, str, str, int]]:
    """(configuration, condition, rule, replication) of every feedback run (protocol s. 5)."""
    plan = [(c, cond, rule, 0) for c in CORE_CONFIGS for cond in CONDITIONS for rule in RULES]
    plan += [
        (c, PRIMARY_CONDITION, rule, 0)
        for c in names
        if c not in CORE_CONFIGS
        for rule in ("unfiltered", PRIMARY_RULE)
    ]
    plan += [
        (c, cond, rule, rep)
        for c in REPLICATED_CONFIGS
        for cond in REPLICATED_CONDITIONS
        for rule in ("unfiltered", PRIMARY_RULE)
        for rep in REPLICATIONS
    ]
    return plan


def summary(records: list[dict], online) -> dict:
    """Phase 5 totals, the alarm bookkeeping, and warm-up indicators: tau on the first
    scored day and the first 31 scored days' violations and curtailment."""
    out = sn.summarise_decisions(records, online)
    out.update({key: float(sum(r[key] for r in records)) for key in EXTRA})
    out["mean_tau"] = float(np.mean([r["tau"] for r in records]))
    out["first_tau"] = float(records[0]["tau"])
    first = [r for r in records if r["day"] < records[0]["day"] + 31]
    out["first_month_violation_steps"] = float(sum(r["avoidable_violation_steps"] for r in first))
    out["first_month_mwh"] = float(sum(r["curtailed_mwh"] for r in first))
    return out


def design(code: str, phase4_cache, fullstate_cache) -> dict:
    """Sensor placements of every rule, from development days only (as in Phase 5)."""
    contexts, layout, _ = sn.build_contexts(code, phase4_cache, fullstate_cache, "development")
    placements = sn.design_placements(contexts, layout, ds.OnlineSettings())
    return {rule: [int(b) for b in buses] for rule, buses in placements.items()}


def task(args: tuple) -> dict:
    """All feedback runs, references, paired comparisons and the state-estimation sample of
    one (network, truth) in one period."""
    code, truth, stage, placements, phase4_cache, fullstate_cache = args
    contexts, layout, facts = sn.build_contexts(
        code, phase4_cache, fullstate_cache, stage, truths=(truth,)
    )
    ctx = contexts[truth]
    configs = configurations(layout, ctx.states[ctx.days[0]]["line"].shape[2], placements)
    online = ds.OnlineSettings()
    banks: dict = {}
    runs, kept = {}, {}
    wanted = {(*key, 0) for pair in PAIRS for key in pair}
    for name, condition, rule, rep in run_plan(configs):
        bank = banks.setdefault(rep, sn.NoiseBank(code, truth, rep))
        records = sn.run_feedback_policy(
            ctx, "replay_aci", configs[name], CONDITIONS[condition], 0, online, noise=bank,
            alarm=RULES[rule],
        )  # fmt: skip
        runs[run_key(name, condition, rule, rep)] = summary(records, online)
        if (name, condition, rule, rep) in wanted:
            kept[(name, condition, rule)] = records
    for policy in ("static_dev", "oracle"):
        records = sn.run_feedback_policy(
            ctx, policy, configs["substation"], CONDITIONS["exact"], 0, online
        )
        runs[policy] = summary(records, online)
    paired = {}
    for a, b in PAIRS:
        ra, rb = kept[a], kept[b]
        entry = {}
        for metric in ("avoidable_violation_steps", "curtailed_mwh"):
            diff = np.array([x[metric] - y[metric] for x, y in zip(ra, rb, strict=True)])
            for block in BLOCK_DAYS:
                name = metric if block == 7 else f"{metric}_block{block}"
                entry[name] = block_bootstrap_mean(diff, block_days=block)
        paired[f"{run_key(*a)} - {run_key(*b)}"] = entry
    return {
        "network": code,
        "truth": truth,
        "facts": facts,
        "runs": runs,
        "paired": paired,
        "state_estimation": se_sample(code, truth, ctx, layout, configs),
    }


def se_sample(code: str, truth: str, ctx, layout: sn.Layout, configs: dict) -> list[dict]:
    """Phase 5's state-estimation sample (every third scored day, 11:00-14:00 UTC, no
    action), realistic readings with identity-based noise. Per step: success, J and its
    degrees of freedom, the estimate's largest errors against the true state, the chi-
    square flag, true events and the state-estimation and direct alarms."""
    from scipy.stats import chi2

    from gridpulse import estimation as es
    from gridpulse import grid_study
    from gridpulse.grid import absolute_profiles

    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    series = es.bus_series(net, grid_study.daily_arrays(absolute_profiles(net)))
    model = CONDITIONS[PRIMARY_CONDITION]
    bank = sn.NoiseBank(code, truth, 0)
    work, cache = copy.deepcopy(net), {}
    limits = np.array(layout.max_vm)
    rows = []
    for day in (d for d in ctx.days if d % es.SE_DAY_STRIDE == 0):
        state = ctx.states[day]
        events = sn.true_events(ctx.truth_norm[day], state, 0, layout)
        daylight = ctx.available[day].sum(axis=1) > 0
        for name in SE_CONFIGS:
            config = configs[name]
            readings = sn.measure(
                state, np.zeros(96, int), config, layout, model, None, noise=bank, day=day
            )
            sub, remote = sn.flagged_steps(readings, config, layout)
            inputs = es.estimator_inputs(config)
            for t in es.SE_STEPS:
                if not daylight[t]:
                    continue
                pseudo = es.pseudo_measurements(series, day, t)
                m = es.add_measurements(work, readings, t, inputs, layout, model, pseudo, True)
                result = es.estimate(m, cache)
                row = {
                    "config": name, "day": day, "step": t, "success": result["success"],
                    "event": bool(events["any"][t]), "event_voltage": bool(events["voltage"][t]),
                    "direct_flag": bool(sub[t] or remote[t]),
                }  # fmt: skip
                if result["success"]:
                    estimated = np.array([result["vm"][b] for b in layout.buses])
                    error_vm = np.abs(estimated - state["vm"][t, 0])
                    error_loading = np.abs(result["line_loading"] - state["line"][t, 0])
                    dof = result["dof"]
                    row.update(
                        objective=result["objective"], dof=dof,
                        rmse_vm=float(np.sqrt(np.mean(error_vm**2))),
                        max_error_vm=float(error_vm.max()),
                        max_error_loading=float(error_loading.max()),
                        chi2_flag=bool(dof > 0 and result["objective"]
                                       > chi2.ppf(1 - CHI2_ALPHA, dof)),
                        se_flag=bool((estimated > limits).any()
                                     or (result["line_loading"] > 100.0).any()
                                     or readings["trafo_loading"][t, 0] > 100.0),
                    )  # fmt: skip
                    row["gross"] = bool(
                        row["max_error_vm"] > GROSS_VM or row["max_error_loading"] > GROSS_LOADING
                    )
                rows.append(row)
    return rows


def summarise_se(rows: list[dict]) -> dict:
    """Per configuration: estimator success, gross errors, the chi-square test's detection
    of them and its flags on other estimates, and alarms of state estimation without and
    with the chi-square gate (a rejected estimate raises no alarm) against direct
    detection on the same readings."""
    out = {}
    for name in SE_CONFIGS:
        g = [r for r in rows if r["config"] == name]
        ok = [r for r in g if r["success"]]
        gross = [r for r in ok if r["gross"]]
        fine = [r for r in ok if not r["gross"]]

        def rate(subset, flag):
            return sum(bool(r.get(flag)) for r in subset) / len(subset) if subset else None

        def confusion(flag, g=g):
            pos = [r for r in g if r["event"]]
            neg = [r for r in g if not r["event"]]
            return {"recall": rate(pos, flag), "false_alarm_rate": rate(neg, flag),
                    "events": len(pos)}  # fmt: skip

        for r in ok:
            r["gated_flag"] = r["se_flag"] and not r["chi2_flag"]
        out[name] = {
            "steps": len(g),
            "success_rate": len(ok) / len(g) if g else None,
            "gross_errors": len(gross),
            "chi2_detects_gross": rate(gross, "chi2_flag"),
            "chi2_flags_fine": rate(fine, "chi2_flag"),
            "rmse_vm_median": float(np.median([r["rmse_vm"] for r in ok])) if ok else None,
            "se": confusion("se_flag"),
            "se_gated": confusion("gated_flag"),
            "direct": confusion("direct_flag"),
        }
    return out


def cells(results: dict, key: str, truths=MISMATCH) -> int:
    """Cells (new network x truth) meeting the requirement for one run key."""
    return int(sum(
        results[c][t]["runs"][key]["meets_beta"]
        for c in results if c != ds.DEVELOPMENT_NETWORK for t in truths
    ))  # fmt: skip


def total(results: dict, key: str, metric: str, truths=("nominal",)) -> float:
    return float(sum(
        results[c][t]["runs"][key][metric]
        for c in results if c != ds.DEVELOPMENT_NETWORK for t in truths
    ))  # fmt: skip


def _new(results: dict) -> list[str]:
    return [c for c in results if c != ds.DEVELOPMENT_NETWORK]


def decision_rules(results: dict, rep: int = 0) -> dict:
    """H1-H4 and H2b (protocol s. 7 and amendment 6A) for noise replication `rep`; the
    exact-reading references have no noise and always come from replication 0."""
    k = run_key
    t2, full, sub, da = "substation+2:topology", "full", "substation", "substation+2:decision_aware"
    p, real = PRIMARY_RULE, PRIMARY_CONDITION
    h1, h2, h2b = {}, {}, {}
    for c in (t2, full):
        noisy = total(results, k(c, real, "unfiltered", rep), "curtailed_mwh")
        aware = total(results, k(c, real, p, rep), "curtailed_mwh")
        exact = total(results, k(c, "exact", "unfiltered"), "curtailed_mwh")
        excess = noisy - exact
        evaluable = excess >= MIN_EXCESS_MWH
        removed = (noisy - aware) / excess if excess > 0 else None
        h1[c] = {"unfiltered_mwh": noisy, "noise_aware_mwh": aware, "exact_mwh": exact,
                 "excess_mwh": excess, "evaluable": evaluable,
                 "share_of_excess_removed": removed,
                 "under_curtails_exact": aware < exact,
                 "met": bool(evaluable and removed >= 0.75)}  # fmt: skip
        v_aware = total(results, k(c, real, p, rep), "avoidable_violation_steps", MISMATCH)
        v_exact = total(results, k(c, "exact", "unfiltered"), "avoidable_violation_steps", MISMATCH)
        h2[c] = {"noise_aware_cells": cells(results, k(c, real, p, rep)),
                 "exact_cells": cells(results, k(c, "exact", "unfiltered")),
                 "noise_aware_violations": v_aware, "exact_violations": v_exact}  # fmt: skip
        h2[c]["met"] = bool(
            h2[c]["noise_aware_cells"] >= h2[c]["exact_cells"] - 1 and v_aware <= 1.25 * v_exact
        )
        nominal = ("nominal",)
        h2b[c] = {
            "noise_aware_nominal_cells": cells(results, k(c, real, p, rep), nominal),
            "exact_nominal_cells": cells(results, k(c, "exact", "unfiltered"), nominal),
            "noise_aware_nominal_violations": total(
                results, k(c, real, p, rep), "avoidable_violation_steps"
            ),
            "exact_nominal_violations": total(
                results, k(c, "exact", "unfiltered"), "avoidable_violation_steps"
            ),
        }
        h2b[c]["met"] = bool(
            h2b[c]["noise_aware_nominal_cells"] >= h2b[c]["exact_nominal_cells"] - 1
        )
    h3 = {
        "sensor_cells": cells(results, k(t2, real, p, rep)),
        "substation_cells": cells(results, k(sub, real, p, rep)),
        "substation_unfiltered_cells": cells(results, k(sub, real, "unfiltered", rep)),
        "sensor_mwh": total(results, k(t2, real, p, rep), "curtailed_mwh"),
        "substation_mwh": total(results, k(sub, real, p, rep), "curtailed_mwh"),
    }
    h3["met"] = bool(
        h3["sensor_cells"] >= h3["substation_cells"] + 3
        and h3["sensor_mwh"] <= 1.1 * h3["substation_mwh"]
    )
    wins, curtail = {}, {}
    for c in _new(results):
        mine = sum(results[c][t]["runs"][k(da, real, p, rep)]["meets_beta"] for t in MISMATCH)
        theirs = sum(results[c][t]["runs"][k(t2, real, p, rep)]["meets_beta"] for t in MISMATCH)
        wins[c] = bool(mine > theirs)
        curtail[c] = sum(
            results[c][t]["runs"][k(da, real, p, rep)]["curtailed_mwh"]
            - results[c][t]["runs"][k(t2, real, p, rep)]["curtailed_mwh"]
            for t in ("nominal", *MISMATCH)
        )
    h4 = {"networks_where_decision_aware_better": int(sum(wins.values())), "by_network": wins,
          "curtailment_difference_mwh": curtail}  # fmt: skip
    h4["met"] = h4["networks_where_decision_aware_better"] >= 3
    joint = all(h1[c]["met"] and h2[c]["met"] and h2b[c]["met"] for c in (t2, full))
    return {"H1_cost": h1, "H2_reliability": h2, "H2b_nominal_reliability": h2b,
            "H3_sensor_value": h3, "H4_placement": h4,
            "noise_aware_feedback_supported": bool(joint)}  # fmt: skip


def bad_data_test(results: dict) -> dict:
    """H6 (protocol s. 7): three separate sub-results on the substation sample."""
    networks = _new(results)

    def rows(c, truth):
        return [r for r in results[c][truth]["state_estimation"]
                if r["config"] == "substation" and r["success"]]  # fmt: skip

    def share(subset, flag="chi2_flag"):
        return sum(bool(r[flag]) for r in subset) / len(subset) if subset else None

    a = {c: share(rows(c, "pv_fixed_095")) for c in networks}
    b = {c: share([r for r in rows(c, "nominal") if not r["gross"]]) for c in networks}
    gross = [r for c in networks for r in rows(c, "nominal") if r["gross"]]
    return {
        "a_pv_reactive_power_flagged": a,
        "a_met": all(v is not None and v >= 0.9 for v in a.values()),
        "b_nominal_false_flags": b,
        "b_met": sum(v is not None and v <= 0.05 for v in b.values()) >= 4,
        "c_nominal_gross_errors": len(gross),
        "c_nominal_gross_detected": share(gross),
        "c_met": bool(gross) and share(gross) >= 0.9,
    }


def evaluate_hypotheses(results: dict) -> dict:
    """The registered decision rules on the five new networks: replication 0 decides;
    replications 1-4 are reported (amendment 6A)."""
    k, t2, p, real = run_key, "substation+2:topology", PRIMARY_RULE, PRIMARY_CONDITION
    out = decision_rules(results, 0)
    out["H5_guard_band"] = {
        "guard_violations": total(results, k(t2, real, "guard2"), "avoidable_violation_steps",
                                  MISMATCH),
        "persistence_violations": total(results, k(t2, real, p), "avoidable_violation_steps",
                                        MISMATCH),
    }  # fmt: skip
    h5 = out["H5_guard_band"]
    h5["met"] = bool(h5["guard_violations"] >= 1.5 * h5["persistence_violations"])
    out["H6_bad_data_test"] = bad_data_test(results)
    out["replications"] = {}
    for rep in REPLICATIONS:
        rules = decision_rules(results, rep)
        out["replications"][rep] = {
            "H1_met": {c: v["met"] for c, v in rules["H1_cost"].items()},
            "H2_met": {c: v["met"] for c, v in rules["H2_reliability"].items()},
            "H2b_met": {c: v["met"] for c, v in rules["H2b_nominal_reliability"].items()},
            "H3_met": rules["H3_sensor_value"]["met"],
            "H4_met": rules["H4_placement"]["met"],
            "noise_aware_feedback_supported": rules["noise_aware_feedback_supported"],
        }
    return out


def run_study(stage: str, phase4_cache, fullstate_cache, networks, workers: int,
              placements: dict | None = None) -> dict:  # fmt: skip
    """Every analysis of one stage. Development designs the placements; evaluation must be
    given the development placements (frozen)."""
    from concurrent.futures import ProcessPoolExecutor

    from gridpulse import fullstate

    if placements is None:
        if stage != "development":
            raise ValueError("the evaluation uses the frozen development placements")
        placements = {code: design(code, phase4_cache, fullstate_cache) for code in networks}
    tasks = [
        (code, truth, stage, placements[code], phase4_cache, fullstate_cache)
        for code in networks
        for truth in fullstate.TRUTHS
    ]
    results: dict = {code: {} for code in networks}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(task, tasks, chunksize=1):
            part["state_estimation_summary"] = summarise_se(part["state_estimation"])
            results[part["network"]][part["truth"]] = part
    return {
        "placements": placements,
        "results": results,
        "hypotheses": evaluate_hypotheses(results),
    }
