import pytest

pytest.importorskip("pandapower")

from gridpulse import noise_study as ns  # noqa: E402
from gridpulse.__main__ import main  # noqa: E402

NETS = ("1-LV-rural1--2-sw", "n1", "n2", "n3", "n4", "n5")


def test_run_plan_covers_registered_comparisons_and_matched_conditions():
    names = list(ns.CORE_CONFIGS) + ["substation+4:risk", "substation+1:random_3"]
    plan = ns.run_plan(names)
    keys = {(c, cond, rule) for c, cond, rule, rep in plan if rep == 0}
    for a, b in ns.PAIRS:
        assert a in keys and b in keys
    for c in ns.CORE_CONFIGS:  # every condition and rule for the core configurations
        assert all((c, cond, r) in keys for cond in ns.CONDITIONS for r in ns.RULES)
    assert ("substation+1:random_3", "realistic", ns.PRIMARY_RULE) in keys
    assert ("substation+1:random_3", "exact", "unfiltered") not in keys
    replicated = {(c, rep) for c, _, _, rep in plan if rep}
    assert {c for c, _ in replicated} == set(ns.REPLICATED_CONFIGS)
    assert len(plan) == len(set(plan))  # no duplicate run


def _results(cells: dict, mwh: dict, violations: dict | None = None, nominal_met=(),
             se_rows=None):  # fmt: skip
    """Synthetic results for the five new networks: `cells[key]` = mismatch cells met per
    network (0-3), `mwh[key]` = nominal curtailment per network, `violations[key]` = per
    (network, truth), `nominal_met` = keys that meet the requirement under the nominal truth.
    Replications 1-4 copy replication 0."""
    violations = violations or {}
    results = {}
    for i, code in enumerate(NETS):
        results[code] = {}
        for t in ("nominal", *ns.MISMATCH):
            runs = {}
            defaults = {
                ns.run_key(c, cond, rule)
                for c in ("substation", "substation+2:topology", "substation+2:decision_aware",
                          "full")
                for cond, rule in (("realistic", ns.PRIMARY_RULE), ("realistic", "unfiltered"),
                                   ("exact", "unfiltered"), ("realistic", "guard2"))
            }  # fmt: skip
            for base in defaults | set(cells) | set(mwh) | set(violations) | set(nominal_met):
                met = cells.get(base, [0] * 5)[i - 1] if i else 0
                record = {
                    "meets_beta": (base in nominal_met) if t == "nominal"
                    else ns.MISMATCH.index(t) < met,
                    "curtailed_mwh": mwh.get(base, 0.0) if t == "nominal" else 0.0,
                    "avoidable_violation_steps": violations.get(base, 0.0),
                }  # fmt: skip
                for rep in range(5):
                    runs[base[: base.rindex("/")] + f"/{rep}"] = record
            rows = (se_rows or {}).get((code, t), [])
            results[code][t] = {"runs": runs, "state_estimation": rows}
    return results


K, T2, FULL, SUB = ns.run_key, "substation+2:topology", "full", "substation"
DA, P = "substation+2:decision_aware", ns.PRIMARY_RULE


def test_hypothesis_rules_follow_the_protocol():
    cells = {
        K(T2, "realistic", P): [2, 2, 2, 2, 2],
        K(T2, "exact", "unfiltered"): [2, 2, 2, 2, 3],  # 11 vs 10: within one cell
        K(FULL, "realistic", P): [3] * 5,
        K(FULL, "exact", "unfiltered"): [3] * 5,
        K(SUB, "realistic", P): [0, 0, 1, 1, 1],
        K(DA, "realistic", P): [3, 3, 2, 2, 1],  # better in 2 networks, ties in 2
        K(T2, "realistic", "guard2"): [1] * 5,
    }
    mwh = {
        K(T2, "realistic", "unfiltered"): 30.0, K(T2, "realistic", P): 12.0,
        K(T2, "exact", "unfiltered"): 10.0,  # removes 90 of 100 MWh excess: 0.9
        K(FULL, "realistic", "unfiltered"): 60.0, K(FULL, "realistic", P): 30.0,
        K(FULL, "exact", "unfiltered"): 10.0,  # removes 150 of 250: 0.6 < 0.75
        K(SUB, "realistic", P): 11.5, K(SUB, "realistic", "unfiltered"): 11.5,
    }  # fmt: skip
    violations = {K(T2, "realistic", "guard2"): 40.0, K(T2, "realistic", P): 20.0,
                  K(T2, "exact", "unfiltered"): 18.0, K(FULL, "realistic", P): 5.0,
                  K(FULL, "exact", "unfiltered"): 5.0}  # fmt: skip
    nominal_met = {
        K(T2, "exact", "unfiltered"),
        K(FULL, "exact", "unfiltered"),
        K(FULL, "realistic", P),
    }
    h = ns.evaluate_hypotheses(_results(cells, mwh, violations, nominal_met))
    assert h["H1_cost"][T2]["met"] and not h["H1_cost"][FULL]["met"]
    assert h["H2_reliability"][T2]["met"] and h["H2_reliability"][FULL]["met"]
    # + 2 topology loses every nominal cell (5 -> 0): under-protection is caught
    assert not h["H2b_nominal_reliability"][T2]["met"] and h["H2b_nominal_reliability"][FULL]["met"]
    assert not h["noise_aware_feedback_supported"]
    assert h["H3_sensor_value"]["met"]  # 10 >= 3 + 3 and 60 <= 1.1 x 57.5
    assert h["H4_placement"]["networks_where_decision_aware_better"] == 2
    assert not h["H4_placement"]["met"]  # ties are not wins
    assert h["H5_guard_band"]["met"]  # 3 x 40 >= 1.5 x 3 x 20 per network
    assert set(h["replications"]) == set(ns.REPLICATIONS)
    assert h["replications"][1]["H3_met"]


def test_h1_is_not_evaluable_without_a_noise_induced_excess():
    mwh = {K(T2, "realistic", "unfiltered"): 10.5, K(T2, "realistic", P): 10.0,
           K(T2, "exact", "unfiltered"): 10.0}  # excess 2.5 MWh pooled  # fmt: skip
    h1 = ns.evaluate_hypotheses(_results({}, mwh))["H1_cost"][T2]
    assert not h1["evaluable"] and not h1["met"]


def test_bad_data_test_follows_its_three_registered_parts():
    def r(chi2_flag, gross):
        return {"config": "substation", "success": True, "chi2_flag": chi2_flag, "gross": gross}

    se_rows = {}
    for code in NETS[1:]:
        se_rows[(code, "pv_fixed_095")] = [r(True, True)] * 19 + [r(False, False)]  # 0.95
        se_rows[(code, "nominal")] = [r(False, False)] * 19 + [r(True, False)]  # 0.05
        se_rows[(code, "nominal")] += [r(True, True), r(False, True)]  # gross: half caught
    se_rows[(NETS[1], "nominal")] += [r(True, False)] * 5  # one network over 5 %
    se_rows[(NETS[2], "tap_raise_lv")] = [r(True, True)] * 50  # other truths do not count
    h6 = ns.evaluate_hypotheses(_results({}, {}, se_rows=se_rows))["H6_bad_data_test"]
    assert h6["a_met"] and h6["b_met"]  # 4 of 5 networks at <= 5 %
    assert h6["c_nominal_gross_errors"] == 10 and h6["c_nominal_gross_detected"] == 0.5
    assert not h6["c_met"]


def test_state_estimation_summary_gates_rejected_estimates():
    def row(event, se_flag, chi2_flag, gross):
        return {"config": "substation", "success": True, "event": event, "se_flag": se_flag,
                "chi2_flag": chi2_flag, "gross": gross, "direct_flag": False,
                "rmse_vm": 0.002}  # fmt: skip

    rows = [row(True, True, False, False), row(True, True, True, True),
            row(False, True, True, True), row(False, False, False, False)]  # fmt: skip
    s = ns.summarise_se(rows)["substation"]
    assert s["gross_errors"] == 2 and s["chi2_detects_gross"] == 1.0
    assert s["chi2_flags_fine"] == 0.0
    assert s["se"]["recall"] == 1.0 and s["se"]["false_alarm_rate"] == 0.5
    assert s["se_gated"]["recall"] == 0.5 and s["se_gated"]["false_alarm_rate"] == 0.0


def test_cli_refuses_an_evaluation_without_a_freeze(tmp_path, capsys):
    code = main(["noise-study", "--stage", "evaluation", "--output-dir", str(tmp_path)])
    assert code == 1 and "no freeze.json" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []  # nothing written


def test_replication_verdicts_are_computed_per_replication():
    cells = {K(T2, "realistic", P): [3] * 5, K(T2, "exact", "unfiltered"): [3] * 5,
             K(SUB, "realistic", P): [0] * 5}  # fmt: skip
    results = _results(cells, {})
    for code in NETS[1:]:  # replication 2 loses every two-meter cell
        for t in ns.MISMATCH:
            run = dict(results[code][t]["runs"][K(T2, "realistic", P, 2)], meets_beta=False)
            results[code][t]["runs"][K(T2, "realistic", P, 2)] = run
    h = ns.evaluate_hypotheses(results)
    assert h["H3_sensor_value"]["met"] and h["replications"][1]["H3_met"]
    assert not h["replications"][2]["H3_met"] and not h["replications"][2]["H2_met"][T2]


def test_legacy_commands_refuse_a_guarded_study_directory(tmp_path, capsys):
    (tmp_path / "development_manifest.json").write_text("{}")
    code = main(["sense-study", "--stage", "development", "--output-dir", str(tmp_path)])
    assert code == 1 and "guarded (Phase 6) study" in capsys.readouterr().err
