"""Tests for the Mission 11 Stage A analysis (`analyse.py` and `svgplot.py`).

**Zero power flows and zero solves.** Nothing here imports `pandapower`, `simbench` or
`stage_a`; a hygiene test parses `analyse.py` and `svgplot.py` and rejects any import of
either package. Every verdict test builds its own synthetic records, so the boundaries of
s. 9's tables are exercised whether or not this checkout carries the local artefacts.

The handful of tests that genuinely need the local artefacts **skip only when every required
file is absent** and **fail loudly** when the set is partial or inconsistent.
"""

from __future__ import annotations

import ast
import json
import math
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

MODULE_DIR = Path(__file__).resolve().parents[1]
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import analyse  # noqa: E402
import envelope_core as ec  # noqa: E402
import svgplot  # noqa: E402

NEAR_ROWS = tuple(range(10))
FAR_ROWS = tuple(range(10, 20))


@pytest.mark.parametrize("module", [analyse, svgplot])
def test_no_power_flow_dependency_is_imported(module):
    """The analysis is physics-free: an imported `pandapower` would be a protocol breach.

    The check parses each module's own source, so it is independent of collection order: a
    session-wide `sys.modules` assertion would pass or fail depending on whether some other
    test file had already imported pandapower to build its fixture.
    """
    tree = ast.parse(Path(module.__file__).read_text())
    forbidden = ("pandapower", "simbench")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            assert root not in forbidden, f"{Path(module.__file__).name} imports {name}"


# --- synthetic records ---------------------------------------------------------------------


def record(
    method: str,
    regime: str,
    kind: str,
    row: int,
    replicate: int,
    total_e: float,
    unsafe: bool,
    status: str = "ok",
    converged: bool = True,
    **extra,
) -> dict:
    payload = {
        "method": method,
        "regime": regime,
        "kind": kind,
        "row": int(row),
        "replicate": int(replicate),
        "total_e": float(total_e),
        "unsafe": bool(unsafe),
        "status": status,
        "converged": bool(converged),
        "stage2_l1_move": 0.0,
        "max_exceedance": 0.001 if unsafe else -0.001,
        "line_loading": 50.0,
        "trafo_loading": 60.0,
    }
    payload.update(extra)
    return payload


def two_replicate_records(
    method: str,
    regime: str,
    totals: list[float],
    unsafe: list[bool] | list[list[bool]],
    statuses: list[str] | None = None,
    **extra,
) -> list[dict]:
    """One record per (near row, replicate), from per-row totals and unsafe flags."""
    out = []
    for row in NEAR_ROWS:
        flags = unsafe[row]
        per_replicate = flags if isinstance(flags, list) else [flags, flags]
        status = statuses[row] if statuses is not None else "ok"
        for replicate, flag in enumerate(per_replicate):
            out.append(
                record(
                    method,
                    regime,
                    "near",
                    row,
                    replicate,
                    totals[row],
                    flag,
                    status=status,
                    **extra,
                )
            )
    return out


def make_network(records: list[dict], name: str = "rural3", policies=None) -> analyse.Network:
    """A `Network` carrying only what the tested functions read."""
    payloads = {
        "envelopes": {
            "records": records,
            "fits": [],
            "n_near": len(NEAR_ROWS),
            "code": "synthetic-feeder",
            "sigma_v": 0.002,
            "near_evaluable": True,
        },
        "ambiguity": {
            "policies": policies if policies is not None else [],
            "measures": [],
            "records": [],
        },
    }
    net = analyse.Network(
        name=name,
        payloads=payloads,
        paths={},
        best_e=np.ones((len(NEAR_ROWS), 1)),
        near_rows=NEAR_ROWS,
        far_rows=FAR_ROWS,
    )
    net.oracle_total = {row: 1.0 for row in NEAR_ROWS}
    return net


# --- H1: the detectable effect and the verdict table ---------------------------------------


@pytest.mark.parametrize(
    "k, lower_bound_positive",
    [(4, True), (3, False)],
)
def test_h1_discordant_condition_boundary(k, lower_bound_positive):
    """s. 9: with n = 10 a percentile lower bound above 0 needs at least 4 discordant
    conditions (0.6^10 = 0.0060 against 0.7^10 = 0.028)."""
    differences = np.array([1.0] * k + [0.0] * (10 - k))
    block = analyse.bootstrap_block(differences, "rural3", "H1")
    assert block["n"] == 10
    assert block["mean"] == pytest.approx(k / 10.0)
    assert (block["interval_95"][0] > 0.0) is lower_bound_positive


def test_h1_four_half_magnitude_conditions_give_exactly_0_20():
    """s. 9: at R = 2 a condition with one of two replicates unsafe scores 0.5."""
    records = two_replicate_records(
        "B2",
        "P1",
        [1.0] * 10,
        [[True, False]] * 4 + [[False, False]] * 6,
    )
    rates = analyse.condition_rates(analyse.pick(records, "B2", "P1", "near"), NEAR_ROWS)
    assert list(rates) == [0.5] * 4 + [0.0] * 6
    assert float(np.mean(rates)) == pytest.approx(analyse.H1_SUPPORT_DIFFERENCE)


def h1_block(mean, low, high, small=False, noise=False, control_c=True):
    return {
        "p1_minus_p3": {"mean": mean, "interval_95": [low, high], "p": 0.01},
        "control_h": {"small_data_effect_fires": small},
        "control_i": {"noise_only_effect_fires": noise},
        "control_c": {"passed": control_c},
    }


def holm_stub(rejected: bool):
    return {
        "raw_p": 0.01,
        "p_used": 0.01,
        "adjusted_p": 0.04,
        "rejected": rejected,
        "evaluable": True,
    }


@pytest.mark.parametrize(
    "interval, expected",
    [
        ((-0.10, 0.10), "Rejected"),
        ((-0.10, 0.1001), "Inconclusive"),
        ((-0.1001, 0.10), "Inconclusive"),
    ],
)
def test_h1_null_band_boundary(interval, expected):
    """The rejection row's interval branch is inclusive at exactly +/- 0.10."""
    block = h1_block(0.05, interval[0], interval[1])
    verdict = analyse.h1_verdict(block, holm_stub(False))
    assert verdict["verdict"] == expected


def test_h1_supported_needs_threshold_holm_and_both_controls():
    block = h1_block(0.30, 0.15, 0.45, small=False, noise=False, control_c=True)
    assert analyse.h1_verdict(block, holm_stub(True))["verdict"] == "Supported"
    # Holm alone can take Supported away without firing any rejection branch.
    assert analyse.h1_verdict(block, holm_stub(False))["verdict"] == "Inconclusive"


@pytest.mark.parametrize("control", ["small", "noise", "control_c"])
def test_h1_support_fails_on_each_control(control):
    kwargs = {"small": False, "noise": False, "control_c": True}
    if control == "control_c":
        kwargs["control_c"] = False
    else:
        kwargs[control] = True
    block = h1_block(0.30, 0.15, 0.45, **kwargs)
    verdict = analyse.h1_verdict(block, holm_stub(True))
    assert verdict["verdict"] != "Supported"
    if control != "control_c":
        assert verdict["rejection_branches_fired"]


# --- the Holm family -----------------------------------------------------------------------


def holm_inputs(h1_p: float):
    h1 = {
        "rural3": {"p1_minus_p3": {"p": h1_p}},
        "semiurb5": {"p1_minus_p3": {"p": 0.001}},
    }
    pair = {
        "evaluable": True,
        "paired_bootstrap": {"p": 0.5, "mean": 0.2},
    }
    h3 = {
        "rural3": {"better_robust_method": "B4", "selected": {"B4": {"pair": pair}}},
        "semiurb5": {
            "better_robust_method": "B4",
            "selected": {"B4": {"pair": dict(pair, paired_bootstrap={"p": 0.001, "mean": 0.3})}},
        },
    }
    return h1, h3


def test_holm_family_has_exactly_four_tests_and_not_evaluable_enters_at_one():
    family = analyse.holm_family(*holm_inputs(0.01))
    assert family["family_size"] == 4
    assert [(t["test"], t["network"]) for t in family["tests"]] == list(analyse.HOLM_FAMILY)
    semiurb5 = [t for t in family["tests"] if t["network"] == "semiurb5"]
    assert len(semiurb5) == 2
    for entry in semiurb5:
        assert entry["evaluable"] is False
        assert entry["p_used"] == 1.0
        assert "NOT EVALUABLE" in entry["reason"]
    rural_h1 = next(t for t in family["tests"] if t["test"] == "H1" and t["network"] == "rural3")
    # Holm's first step multiplies the smallest p by the family size, which stays 4.
    assert rural_h1["adjusted_p"] == pytest.approx(0.04)
    assert rural_h1["rejected_at_0.05"] is True


def test_holm_family_keeps_family_size_four_when_rural3_is_not_significant():
    family = analyse.holm_family(*holm_inputs(0.02))
    rural_h1 = next(t for t in family["tests"] if t["test"] == "H1" and t["network"] == "rural3")
    assert rural_h1["adjusted_p"] == pytest.approx(0.08)
    assert rural_h1["rejected_at_0.05"] is False
    assert all(t["adjusted_p"] <= 1.0 for t in family["tests"])


# --- H3: the pairing rule, degeneracy and the companion sign rule --------------------------


def h3_records(
    robust_unsafe, simple_unsafe, robust_statuses=None, robust_total=0.9, simple_total=0.5
):
    records = two_replicate_records(
        "B4",
        "P1",
        [robust_total] * 10,
        robust_unsafe,
        statuses=robust_statuses,
        restored=True,
        gap=0.1,
    )
    records += two_replicate_records("B2p", "P1", [simple_total] * 10, simple_unsafe)
    return records


def test_h3_pairing_not_evaluable_below_seven_joint_conditions():
    """s. 9: the comparison is NOT EVALUABLE if fewer than 7 of 10 joint conditions remain."""
    simple_unsafe = [True] * 4 + [False] * 6
    net = make_network(h3_records([False] * 10, simple_unsafe))
    pair = analyse._pair_block(net, "B4", "B2p", "P1")
    assert pair["n_joint"] == 6
    assert pair["evaluable"] is False
    assert pair["status"] == analyse.NOT_EVALUABLE
    assert "fewer than 7" in pair["reason"]


def test_h3_pairing_evaluable_at_exactly_seven_joint_conditions():
    simple_unsafe = [True] * 3 + [False] * 7
    net = make_network(h3_records([False] * 10, simple_unsafe))
    pair = analyse._pair_block(net, "B4", "B2p", "P1")
    assert pair["n_joint"] == 7
    assert pair["evaluable"] is True
    assert pair["median_difference"] == pytest.approx(0.4)


def test_h3_pairing_excludes_robust_degenerate_conditions():
    """A `robust-degenerate` record is never a safe envelope, so its condition leaves the
    joint set even though its `unsafe` flag is false."""
    statuses = [analyse.DEGENERATE] * 4 + ["ok"] * 6
    net = make_network(h3_records([False] * 10, [False] * 10, robust_statuses=statuses))
    pair = analyse._pair_block(net, "B4", "B2p", "P1")
    assert pair["n_joint"] == 6
    assert pair["evaluable"] is False
    assert (
        analyse.degenerate_conditions(analyse.pick(net.records, "B4", "P1", "near"), NEAR_ROWS) == 4
    )


def test_h3_companion_scores_unsafe_and_degenerate_as_zero():
    statuses = ["ok"] * 8 + [analyse.DEGENERATE] * 2
    net = make_network(h3_records([False] * 8 + [True] * 2, [False] * 10, robust_statuses=statuses))
    robust = analyse.pick(net.records, "B4", "P1", "near")
    strict = analyse.condition_utilisation(robust, NEAR_ROWS, net.oracle_total, False)
    companion = analyse.condition_utilisation(robust, NEAR_ROWS, net.oracle_total, True)
    assert np.isnan(strict[-1])
    assert companion[-1] == 0.0
    assert companion[0] == pytest.approx(0.9)


def test_h3_sign_rule_disagreement_gives_inconclusive():
    """The joint set favours the robust method, the companion set the simple one: s. 9 makes
    the verdict Inconclusive rather than Supported."""
    # B4 is never unsafe, so it keeps zero observed unsafe, but it is `robust-degenerate` on
    # rows 7-9 (3 of 10, below the rejection row's 5). On the 7 joint conditions its median
    # utilisation beats B2p's by 0.4; over all 10 the degenerate zeros pull its companion
    # median below B2p's, so the two comparisons disagree in sign. B2p is unsafe on row 7, so
    # it is not "at least as safe" and the simple-policy rejection branch cannot fire either.
    robust_statuses = ["ok"] * 7 + [analyse.DEGENERATE] * 3
    robust_totals = [0.2, 0.2, 0.2, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9, 0.9]
    simple_totals = [0.1, 0.1, 0.1, 0.5, 0.5, 0.5, 0.5, 0.95, 0.95, 0.95]
    simple_unsafe = [False] * 7 + [True] + [False] * 2
    net = make_network(
        two_replicate_records(
            "B4",
            "P1",
            robust_totals,
            [False] * 10,
            statuses=robust_statuses,
            restored=True,
            gap=0.1,
        )
        + two_replicate_records("B2p", "P1", simple_totals, simple_unsafe)
        + two_replicate_records("B2m", "P1", [0.1] * 10, [True] * 10)
        + two_replicate_records("B0", analyse.NO_REGIME, [0.1] * 10, [True] * 10)
        + two_replicate_records("B4box", "P1", [0.9] * 10, [True] * 10)
    )
    pair = analyse._pair_block(net, "B4", "B2p", "P1")
    assert pair["n_joint"] == 7
    assert pair["median_difference"] == pytest.approx(0.4)
    assert pair["companion_all_conditions"]["median_difference"] == pytest.approx(-0.3)
    assert pair["sign_agreement"] is False

    block = analyse.h3_network(net, "P1")
    verdict = analyse.h3_verdict(block, holm_stub(True))
    assert block["better_robust_method"] == "B4"
    assert block["robust_methods"]["B4"]["zero_observed_unsafe"] is True
    assert block["robust_methods"]["B4"]["degenerate_branch_fires"] is False
    assert verdict["support_requirements"]["sign_agreement"] is False
    assert verdict["rejection_branches_fired"] == []
    assert verdict["verdict"] == "Inconclusive"


def test_h3_rejection_branch_simple_policy_suffices():
    """A simple policy that is at least as safe and within 0.05 fires the rejection row."""
    net = make_network(
        two_replicate_records("B4", "P1", [0.90] * 10, [False] * 10, restored=True, gap=0.1)
        + two_replicate_records("B2p", "P1", [0.88] * 10, [False] * 10)
        + two_replicate_records("B2m", "P1", [0.1] * 10, [True] * 10)
        + two_replicate_records("B0", analyse.NO_REGIME, [0.1] * 10, [True] * 10)
        + two_replicate_records("B4box", "P1", [0.9] * 10, [True] * 10)
    )
    block = analyse.h3_network(net, "P1")
    verdict = analyse.h3_verdict(block, holm_stub(False))
    assert verdict["rejection_branches"]["simple_suffices_B2p"] is True
    assert verdict["verdict"] == "Rejected"
    detail = verdict["rejection_branch_detail"]["B2p"]
    assert detail["at_least_as_safe"] is True
    assert detail["within_0.05_of_robust"] is True


def test_h3_rejection_branch_robust_degenerate_on_five_of_ten():
    statuses = [analyse.DEGENERATE] * 5 + ["ok"] * 5
    net = make_network(
        two_replicate_records(
            "B4", "P1", [0.9] * 10, [False] * 10, statuses=statuses, restored=True, gap=0.1
        )
        + two_replicate_records("B2p", "P1", [0.5] * 10, [False] * 10)
        + two_replicate_records("B2m", "P1", [0.1] * 10, [True] * 10)
        + two_replicate_records("B0", analyse.NO_REGIME, [0.1] * 10, [True] * 10)
        + two_replicate_records("B4box", "P1", [0.9] * 10, [True] * 10)
    )
    block = analyse.h3_network(net, "P1")
    assert block["robust_methods"]["B4"]["degenerate_conditions"] == 5
    assert block["robust_methods"]["B4"]["degenerate_branch_fires"] is True
    verdict = analyse.h3_verdict(block, holm_stub(False))
    assert verdict["rejection_branches"]["robust_degenerate_on_at_least_5_of_10"] is True
    assert verdict["verdict"] == "Rejected"


def test_h3_b4_bracket_uses_the_cut_lp_upper_bound():
    net = make_network(
        two_replicate_records("B4", "P1", [0.8] * 10, [False] * 10, restored=True, gap=0.2)
    )
    bracket = analyse._b4_bracket(net, "P1")
    assert bracket["median_lower"] == pytest.approx(0.8)
    assert bracket["median_upper"] == pytest.approx(1.0)
    assert bracket["upper_end_ac_scored"] is False


# --- CERT ----------------------------------------------------------------------------------


def cert_policy(k: int, cert_unsafe: int, rand_unsafe: int, n: int = 10) -> dict:
    return {
        "regime": "P1",
        "replicate": 0,
        "k": k,
        "n": n,
        "fallback_rate": k / n,
        "cert_unsafe": cert_unsafe,
        "rand_unsafe": rand_unsafe,
        "always_unsafe": 0,
        "b2_unsafe": 10,
        "verdict": "artefact",
        "act": [True] * n,
        "rand_fallback": [False] * n,
    }


@pytest.mark.parametrize("k", [0, 10])
def test_cert_not_evaluable_at_zero_or_full_fallback(k):
    """s. 7: at a realised fallback rate of 0 or 1, RAND is identical to CERT."""
    net = make_network([], policies=[cert_policy(k, 4, 4)])
    block = analyse._cert_block(net, "P1")
    assert block["evaluable"] is False
    assert block["verdict"] == analyse.NOT_EVALUABLE
    assert f"k = {k}" in block["reason"]


@pytest.mark.parametrize(
    "cert_unsafe, rand_unsafe, expected",
    [(2, 5, "credited"), (5, 2, "not credited"), (3, 3, "not credited")],
)
def test_cert_credited_only_when_it_beats_rand(cert_unsafe, rand_unsafe, expected):
    net = make_network([], policies=[cert_policy(3, cert_unsafe, rand_unsafe)])
    block = analyse._cert_block(net, "P1")
    assert block["evaluable"] is True
    assert block["verdict"] == expected


# --- H4 ------------------------------------------------------------------------------------


def h4_block(spread, disagreement):
    return {
        "median_export_spread": spread,
        "safety_disagreement_rate": disagreement,
    }


@pytest.mark.parametrize(
    "spread, disagreement, expected",
    [
        (0.10, 0.0, "Material ambiguity"),
        (0.02, 0.30, "Material ambiguity"),
        (0.049, 0.0, "Decision equivalence"),
        (0.05, 0.0, "Mixed"),
        (0.02, 0.10, "Mixed"),
        (0.099, 0.29, "Mixed"),
    ],
)
def test_h4_classification_boundaries(spread, disagreement, expected):
    assert analyse._classify_h4(h4_block(spread, disagreement))["classification"] == expected


def test_h4_spread_only_objective_is_labelled_so():
    """The proportional-fair envelopes are not AC-scored, so no disagreement is measured."""
    assert analyse._classify_h4(h4_block(0.02, None))["classification"] == (
        "Decision equivalence (spread only)"
    )
    assert analyse._classify_h4(h4_block(0.2, None))["classification"] == (
        "Material ambiguity (spread only)"
    )
    assert analyse._classify_h4(h4_block(0.07, None))["classification"] == "Mixed (spread only)"


def test_h4_not_evaluable_without_measures():
    assert analyse._classify_h4(h4_block(None, None))["classification"] == analyse.NOT_EVALUABLE


# --- control A' attribution and the s. 15 stop label ---------------------------------------


def aprime_network(aprime_unsafe: list[bool], method_unsafe: list[bool]) -> analyse.Network:
    records = [
        record(
            "Aprime", analyse.NO_REGIME, "near", row, analyse.NO_REPLICATE, 0.5, aprime_unsafe[row]
        )
        for row in NEAR_ROWS
    ]
    records += [
        record("A", analyse.NO_REGIME, "near", row, analyse.NO_REPLICATE, 0.5, False)
        for row in NEAR_ROWS
    ]
    for regime in analyse.TRAINING_REGIMES:
        for method in analyse.DATA_DRIVEN:
            flags = method_unsafe if method == "B2" else [False] * 10
            records += two_replicate_records(method, regime, [0.5] * 10, flags)
    return make_network(records)


def test_aprime_attribution_counts_only_the_excess():
    net = aprime_network([True] * 2 + [False] * 8, [True] * 6 + [False] * 4)
    block = analyse._aprime_attribution(net)
    b2 = block["per_method"]["B2"]["P1"]
    assert b2["expected_unsafe_count_method"] == pytest.approx(6.0)
    assert b2["expected_unsafe_count_aprime"] == pytest.approx(2.0)
    assert b2["excess_count_over_aprime"] == pytest.approx(4.0)
    assert b2["paired_bootstrap"]["mean"] == pytest.approx(0.4)
    # B3 is safe everywhere, so its excess is negative: A' explains those failures.
    assert block["per_method"]["B3"]["P1"]["excess_count_over_aprime"] == pytest.approx(-2.0)


@pytest.mark.parametrize(
    "n_unsafe, expected",
    [
        (0, "no s. 15 stop condition"),
        (2, "no s. 15 stop condition"),
        (3, "linearisation-sensitive"),
        (5, "linearisation-sensitive"),
        (6, "stop"),
        (10, "stop"),
    ],
)
def test_s15_aprime_stop_label(n_unsafe, expected):
    net = aprime_network([True] * n_unsafe + [False] * (10 - n_unsafe), [False] * 10)
    assert analyse._aprime_attribution(net)["s15_stop_label"].startswith(expected)


# --- s. 12: a failed flow counts as unsafe -------------------------------------------------


def test_failed_power_flow_counts_as_unsafe():
    failed = record("B2", "P1", "near", 0, 0, 0.5, False, converged=False)
    assert analyse.is_unsafe(failed) is True
    ok = record("B2", "P1", "near", 0, 0, 0.5, False)
    assert analyse.is_unsafe(ok) is False


def test_zero_export_envelope_is_not_a_failed_flow():
    """An infeasible LP returns an empty envelope, which is safe; the AC flow still ran."""
    empty = record("B1", "L0", "near", 0, 0, 0.0, False, status="infeasible")
    assert analyse.is_unsafe(empty) is False


# --- svgplot --------------------------------------------------------------------------------


def demo_figure() -> svgplot.Figure:
    series = svgplot.Series(
        x=[0.1, 0.2, 0.3],
        y=[0.2, 0.5, 0.9],
        ylo=[0.1, 0.4, 0.8],
        yhi=[0.3, 0.6, 1.0],
        label="demo & <series>",
        point_labels=["a", "b", "c"],
    )
    line = svgplot.Series(x=[1.0, 2.0, 3.0], y=[1e-3, 1e-6, 1e-9], label="log", kind="line")
    panels = [
        svgplot.Panel(
            series=[series],
            title="panel 1",
            xlabel="test-day MAE (pu)",
            ylabel="unsafe rate (share)",
            hlines=[(0.3, "0.30")],
        ),
        svgplot.Panel(series=[line], title="panel 2", xlabel="index", ylabel="ratio", ylog=True),
    ]
    return svgplot.Figure(
        title="demo <figure> & title",
        desc="n = 3 synthetic points; bars are 95 % intervals; source: this test",
        panels=panels,
        ncols=2,
    )


def test_svg_is_well_formed_and_carries_title_and_desc():
    text = demo_figure().to_svg()
    root = ET.fromstring(text)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    title = root.find("{http://www.w3.org/2000/svg}title")
    desc = root.find("{http://www.w3.org/2000/svg}desc")
    assert title is not None and "demo <figure> & title" == title.text
    assert desc is not None and "n = 3" in desc.text
    assert "95 %" in desc.text


def test_svg_axes_carry_units_and_every_series_is_drawn():
    text = demo_figure().to_svg()
    assert "test-day MAE (pu)" in text
    assert "unsafe rate (share)" in text
    ET.fromstring(text)  # a second parse after the assertions, to pin well-formedness
    root = ET.fromstring(text)
    namespace = "{http://www.w3.org/2000/svg}"
    assert len(root.findall(f".//{namespace}circle")) >= 3
    assert len(root.findall(f".//{namespace}polyline")) >= 1


def test_svg_escapes_markup_in_labels():
    text = demo_figure().to_svg()
    assert "demo &amp; &lt;series&gt;" in text
    ET.fromstring(text)


def test_series_rejects_mismatched_lengths():
    with pytest.raises(ValueError, match="2 x against 3 y"):
        svgplot.Series(x=[0.0, 1.0], y=[0.0, 1.0, 2.0])
    with pytest.raises(ValueError, match="ylo has the wrong length"):
        svgplot.Series(x=[0.0, 1.0], y=[0.0, 1.0], ylo=[0.0])


def test_log_axis_rejects_a_non_positive_limit():
    with pytest.raises(ValueError, match="strictly positive"):
        svgplot.log_ticks(0.0, 1.0)


def test_nice_ticks_cover_the_range():
    ticks = svgplot.nice_ticks(0.0, 1.0)
    assert ticks[0] >= 0.0 and ticks[-1] <= 1.0
    assert len(ticks) >= 3


# --- the ODbL notice in the figures (ODbL 1.0 s. 4.3; DATA_ATTRIBUTION.md) ------------------

SVG_NS = "{http://www.w3.org/2000/svg}"


def _drawn_text(svg_text: str) -> str:
    """Every `<text>` run of an SVG, in document order, joined by the spaces wrapping ate."""
    root = ET.fromstring(svg_text)
    return " ".join(node.text or "" for node in root.findall(f".//{SVG_NS}text"))


def _blank_figure(**geometry) -> svgplot.Figure:
    """A figure with one empty panel: no series, no data, nothing to draw but the frame."""
    return svgplot.Figure(
        title="no data",
        desc="n = 0; nothing to draw; source: this test",
        panels=[svgplot.Panel(series=[], title="empty")],
        **geometry,
    )


def test_notice_is_in_desc_and_visible_in_every_figure(artefacts):
    """s. 4.3 wants the notice associated with the Produced Work, so it is in both places."""
    figures = analyse.build_figures(analyse.build_summary())
    assert len(figures) == 6
    for name, text in figures:
        desc = ET.fromstring(text).find(f"{SVG_NS}desc")
        assert desc is not None and desc.text, name
        assert desc.text.endswith(svgplot.ATTRIBUTION_NOTICE), name
        assert desc.text != svgplot.ATTRIBUTION_NOTICE, name  # appended, not substituted
        assert svgplot.ATTRIBUTION_NOTICE in _drawn_text(text), name


def test_a_figure_without_data_still_carries_the_notice():
    text = _blank_figure().to_svg()
    desc = ET.fromstring(text).find(f"{SVG_NS}desc")
    assert desc.text.endswith(svgplot.ATTRIBUTION_NOTICE)
    assert svgplot.ATTRIBUTION_NOTICE in _drawn_text(text)


def test_the_footer_band_sits_below_the_pre_notice_canvas():
    """The band is added underneath, so the pre-notice geometry is untouched."""
    for figure in (demo_figure(), _blank_figure()):
        # The height the writer had before the notice: panels plus the original 96 px.
        assert figure.content_height == figure.nrows * figure.panel_height + 96.0
        assert figure.height == figure.content_height + svgplot.FOOTER_HEIGHT
        baselines = [
            float(node.get("y"))
            for node in ET.fromstring(figure.to_svg()).findall(f".//{SVG_NS}text")
            if node.get("style") == svgplot.CREDIT_STYLE
        ]
        assert baselines, "the notice must be drawn"
        assert min(baselines) > figure.content_height
        assert max(baselines) < figure.height


def test_the_notice_wraps_inside_the_canvas_width():
    """By `svgplot.text_width`, the writer's own deliberately generous estimate."""
    narrow = _blank_figure(panel_width=500.0, legend_width=100.0)
    assert len(narrow.footer_lines()) > 1, "this canvas is too narrow for one line"
    for figure in (demo_figure(), _blank_figure(), narrow):
        lines = figure.footer_lines()
        assert " ".join(lines) == svgplot.ATTRIBUTION_NOTICE
        for line in lines:
            assert svgplot.text_width(line, svgplot.CREDIT_FONT_PX) <= figure.width - 24.0
        assert svgplot.CREDIT_FONT_PX <= svgplot.TICK_FONT_PX


def test_a_canvas_too_narrow_for_the_band_is_rejected():
    """Silently overflowing the band would put the notice outside the viewBox."""
    with pytest.raises(ValueError, match="footer band holds"):
        _blank_figure(panel_width=200.0, legend_width=40.0).to_svg()


# --- figure B's Clopper-Pearson n (protocol s. 9) -------------------------------------------


def _one_network_study(records: list[dict], mae: float = 0.01) -> analyse.Study:
    """A Study carrying a single synthetic evaluation network, enough for `figure_b`."""
    net = make_network(records)
    net.payloads["envelopes"]["fits"] = [
        {
            "regime": regime,
            "replicate": replicate,
            "test_mae": dict.fromkeys(("OLS", "ridge", "NNLS"), mae),
        }
        for regime in analyse.TRAINING_REGIMES
        for replicate in (0, 1)
    ]
    return analyse.Study(networks={net.name: net}, summary={})


def test_figure_b_counts_conditions_not_records():
    """s. 9 fixes the Clopper-Pearson n at the conditions, because replicates are nested.

    Row 0 is unsafe in one replicate only and row 1 in both. Over records that is 3/20;
    over conditions, counting a condition unsafe when *any* replicate is, it is 2/10. The
    figure must draw the second, with an interval on n = 10.
    """
    flags: list[list[bool]] = [[False, False] for _ in NEAR_ROWS]
    flags[0] = [True, False]
    flags[1] = [True, True]
    records = []
    for _, method in analyse.VOLTAGE_MODELS:
        for regime in analyse.TRAINING_REGIMES:
            records.extend(
                two_replicate_records(method, regime, [1.0] * len(NEAR_ROWS), list(flags))
            )
    assert sum(1 for r in records if analyse.is_unsafe(r)) == 3 * 3 * 3  # 3 records per cell

    _, figure = analyse.figure_b(_one_network_study(records))
    (panel,) = figure.panels
    expected_lo, expected_hi = ec.clopper_pearson(2, len(NEAR_ROWS))
    for series in panel.series:
        for index, value in enumerate(series.y):
            assert value == pytest.approx(0.2), "the rate must be over conditions, not records"
            assert series.ylo[index] == pytest.approx(expected_lo)
            assert series.yhi[index] == pytest.approx(expected_hi)
    assert "n = the number of near conditions" in figure.desc
    assert "at least one replicate" in figure.desc
    assert "conditions x replicates" not in figure.desc


def test_figure_b_interval_width_tracks_n_equals_conditions():
    """A one-condition-unsafe cell gets the n = 10 interval, which is strictly wider than the
    n = 20 interval the withdrawn instruction would have drawn."""
    flags: list[list[bool]] = [[False, False] for _ in NEAR_ROWS]
    flags[0] = [True, True]
    records = []
    for _, method in analyse.VOLTAGE_MODELS:
        for regime in analyse.TRAINING_REGIMES:
            records.extend(
                two_replicate_records(method, regime, [1.0] * len(NEAR_ROWS), list(flags))
            )
    _, figure = analyse.figure_b(_one_network_study(records))
    series = figure.panels[0].series[0]
    over_conditions = ec.clopper_pearson(1, 10)
    over_records = ec.clopper_pearson(2, 20)
    assert (series.ylo[0], series.yhi[0]) == pytest.approx(over_conditions)
    assert over_conditions[1] > over_records[1]


# --- figure F's label layout ----------------------------------------------------------------


def _controls_study() -> analyse.Study:
    """A synthetic evaluation network carrying every arm `figure_f` draws.

    The numbers do not matter here - only that all 17 arms are populated, so that the label
    layout is exercised at full width.
    """
    totals = [1.0] * len(NEAR_ROWS)
    safe = [False] * len(NEAR_ROWS)
    records = []
    for regime in ("P1", "P3", "L0"):
        records.extend(two_replicate_records("B2", regime, totals, list(safe)))
    for method in ("A", "Aprime"):
        records.extend(two_replicate_records(method, analyse.NO_REGIME, totals, list(safe)))
    for row in FAR_ROWS:
        records.append(record("B2", "P1", "far", row, 0, 1.0, False))

    controls = []
    for method in ("H192", "H768"):
        controls.extend(record(method, "P1", "near", row, 0, 1.0, False) for row in NEAR_ROWS)
    for method in ("I0.0005", "I0.005", "T"):
        for regime in ("P1", "P3"):
            controls.extend(record(method, regime, "near", row, 0, 1.0, False) for row in NEAR_ROWS)

    net = make_network(records)
    net.payloads["controls"] = {"records": controls}
    return analyse.Study(networks={net.name: net}, summary={})


def _rotated_label_boxes(figure: svgplot.Figure, index: int = 0) -> list[tuple[float, ...]]:
    """Each x tick label as a box in its own rotated frame: (u_lo, u_hi, v_lo, v_hi).

    The labels are drawn end-anchored along the direction `rotate(-angle)` gives them, so in
    the frame spanned by that direction and its normal every box is axis-aligned. Widths come
    from the writer's own estimate, `svgplot.text_width`.
    """
    panel = figure.panels[index]
    x0, y0, width, height = figure._plot_box(index)
    xlo, xhi = panel.limits("x")
    angle = math.radians(panel.xtick_rotate)
    along = (math.cos(angle), -math.sin(angle))  # rotate(-angle) applied to (1, 0)
    normal = (math.sin(angle), math.cos(angle))
    anchor_y = y0 + height + 14
    boxes = []
    for position, label in panel.xticks:
        anchor_x = figure._project(position, xlo, xhi, x0, width, panel.xlog)
        u = anchor_x * along[0] + anchor_y * along[1]
        v = anchor_x * normal[0] + anchor_y * normal[1]
        text = svgplot.text_width(label)
        # Helvetica at 9 px: cap height above the baseline, descenders below.
        boxes.append((u - text, u, v - 0.8 * svgplot.TICK_FONT_PX, v + 0.2 * svgplot.TICK_FONT_PX))
    return boxes


def test_figure_f_arm_labels_do_not_overlap():
    """The 17 control-arm labels must all be legible: no two label boxes may intersect."""
    _, figure = analyse.figure_f(_controls_study())
    panel = figure.panels[0]
    assert len(panel.xticks) == 17
    assert panel.xtick_rotate, "17 arm labels do not fit horizontally and must be rotated"
    boxes = _rotated_label_boxes(figure)
    for i, (u_lo, u_hi, v_lo, v_hi) in enumerate(boxes):
        for j, (o_u_lo, o_u_hi, o_v_lo, o_v_hi) in enumerate(boxes[i + 1 :], start=i + 1):
            overlaps = u_lo < o_u_hi and o_u_lo < u_hi and v_lo < o_v_hi and o_v_lo < v_hi
            assert not overlaps, f"labels {panel.xticks[i][1]!r} and {panel.xticks[j][1]!r} overlap"


def test_figure_f_labels_stay_inside_the_canvas_and_clear_the_axis_label():
    """Rotating the labels is only legible if the figure actually makes room for them."""
    _, figure = analyse.figure_f(_controls_study())
    panel = figure.panels[0]
    _, y0, _, height = figure._plot_box(0)
    band = panel.xtick_band()
    assert band > 0.0

    # The deepest ink: the far end of the longest label, plus its descenders.
    angle = math.radians(panel.xtick_rotate)
    longest = max(svgplot.text_width(label) for _, label in panel.xticks)
    deepest = (
        y0 + height + 14 + longest * math.sin(angle) + 0.2 * svgplot.TICK_FONT_PX * math.cos(angle)
    )
    xlabel_baseline = y0 + height + 36 + band
    note_baseline = y0 + height + 50 + band
    assert deepest < xlabel_baseline, "the rotated labels must not run into the x axis label"
    assert note_baseline < figure.height, "the note must stay on the canvas"

    text = figure.to_svg()
    ET.fromstring(text)
    assert "rotate(-45)" in text
    assert "rotated 45 degrees" in figure.desc


def test_xtick_band_is_zero_without_rotation():
    """The rotated-label layout is opt-in, so every other figure keeps its original geometry."""
    panel = svgplot.Panel(
        series=[svgplot.Series(x=[0.0, 1.0], y=[0.0, 1.0])],
        xticks=[(0.0, "a long label indeed"), (1.0, "another")],
    )
    assert panel.xtick_band() == 0.0
    assert svgplot.Panel(series=panel.series).xtick_band() == 0.0


# --- the header note against the first panel title -----------------------------------------

# The gap the check demands between the note's last baseline and the title's ink. Six px is
# about half a line of the 11 px title: enough that the two read as separate blocks.
HEADER_CLEARANCE_PX = 6.0


def _class_font_px(svg_text: str, class_name: str) -> float:
    """The font size the figure's own stylesheet gives one class, in px.

    Read from the drawn document rather than restated here, so the check cannot drift from
    the sheet the figure actually carries.
    """
    style = ET.fromstring(svg_text).find(f"{SVG_NS}style")
    assert style is not None and style.text, "the figure must carry a stylesheet"
    match = re.search(rf"\.{class_name}\{{[^}}]*font-size:([0-9.]+)px", style.text)
    assert match, f"the stylesheet has no font-size for .{class_name}"
    return float(match.group(1))


def _header_note_baselines(svg_text: str) -> list[float]:
    """The baselines of the wrapped description note, which the header draws at x = 12.

    A panel's own note shares the class but never the x: a plot box starts at 12 + 74 px.
    """
    return sorted(
        float(node.get("y"))
        for node in ET.fromstring(svg_text).findall(f".//{SVG_NS}text")
        if node.get("class") == "note" and node.get("x") == "12"
    )


def _panel_title_baselines(svg_text: str) -> list[float]:
    return sorted(
        float(node.get("y"))
        for node in ET.fromstring(svg_text).findall(f".//{SVG_NS}text")
        if node.get("class") == "panel"
    )


def _assert_note_clears_the_first_panel_title(svg_text: str, name: str) -> None:
    notes = _header_note_baselines(svg_text)
    titles = _panel_title_baselines(svg_text)
    assert notes, f"{name}: the description note must be drawn"
    assert titles, f"{name}: a panel title must be drawn"
    # The title's ink reaches one font size above its baseline; the topmost title is the
    # first row's, which is the one a long header note can run into.
    title_ink_top = titles[0] - _class_font_px(svg_text, "panel")
    assert notes[-1] <= title_ink_top - HEADER_CLEARANCE_PX, (
        f"{name}: the note's last baseline at {notes[-1]} px leaves"
        f" {title_ink_top - notes[-1]} px to the first panel title's ink at {title_ink_top} px,"
        f" under the {HEADER_CLEARANCE_PX} px the layout demands"
    )


def _note_figure(desc: str) -> svgplot.Figure:
    """One panel with a title, so the header note has something to collide with."""
    return svgplot.Figure(
        title="header layout",
        desc=desc,
        panels=[
            svgplot.Panel(series=[svgplot.Series(x=[0.0, 1.0], y=[0.0, 1.0])], title="first panel")
        ],
    )


def _words(count: int) -> str:
    """`count` seven-character words, which the default canvas wraps 16 to a line."""
    return " ".join(f"word{i:03d}" for i in range(count))


def test_every_figure_note_clears_the_first_panel_title(artefacts):
    """The defect: a note of four or more lines was drawn over the first panel title."""
    figures = analyse.build_figures(analyse.build_summary())
    assert len(figures) == 6
    wrapped = {}
    for name, text in figures:
        _assert_note_clears_the_first_panel_title(text, name)
        wrapped[name] = len(_header_note_baselines(text))
    assert max(wrapped.values()) > svgplot.HEADER_FREE_LINES, (
        f"no figure's note overflows the header, so the shift is untested here: {wrapped}"
    )


@pytest.mark.parametrize(("words", "lines"), [(54, 4), (70, 5), (85, 6)])
def test_a_long_note_still_clears_the_panel_title(words, lines):
    figure = _note_figure(_words(words))
    assert len(figure.note_lines) == lines
    overflow = lines - svgplot.HEADER_FREE_LINES
    assert figure.header_extra == svgplot.HEADER_LINE_PX * overflow
    text = figure.to_svg()
    ET.fromstring(text)
    _assert_note_clears_the_first_panel_title(text, f"a synthetic {lines}-line note")
    # The panels and the footer band move down by the overflow and by nothing else.
    _, y0, _, _ = figure._plot_box(0)
    assert y0 == 72.0 + figure.header_extra + figure._PAD_TOP
    assert figure.content_height == figure.nrows * figure.panel_height + 96.0 + figure.header_extra


@pytest.mark.parametrize("lines", [1, 2, 3])
def test_header_extra_is_zero_for_a_short_note(lines):
    """A note of three lines or fewer already clears the title, so nothing may move."""
    figure = _note_figure(_words(16 * lines))
    assert len(figure.note_lines) == lines
    assert figure.header_extra == 0
    _, y0, _, _ = figure._plot_box(0)
    assert y0 == 72.0 + figure._PAD_TOP
    assert figure.content_height == figure.nrows * figure.panel_height + 96.0
    _assert_note_clears_the_first_panel_title(figure.to_svg(), f"a {lines}-line note")


# --- write-once discipline -----------------------------------------------------------------


def test_write_json_once_refuses_to_overwrite(tmp_path):
    target = tmp_path / "stage_a_summary.json"
    ec.write_json_once(target, {"a": 1})
    with pytest.raises(FileExistsError, match="written once"):
        ec.write_json_once(target, {"a": 2})
    assert json.loads(target.read_text()) == {"a": 1}


def test_write_once_svg_refuses_to_overwrite(tmp_path):
    target = tmp_path / "fig_a.svg"
    analyse._write_once_svg(target, "<svg/>")
    with pytest.raises(FileExistsError, match="written once"):
        analyse._write_once_svg(target, "<svg>changed</svg>")
    assert target.read_text() == "<svg/>"


# --- the local artefacts -------------------------------------------------------------------


def artefact_state() -> str:
    """One of complete, absent or partial, over both networks' required artefacts."""
    present, missing = [], []
    for network in analyse.NETWORKS:
        found, lost = analyse.artefacts_present(network)
        present.extend(found)
        missing.extend(lost)
    if not missing:
        return "complete"
    if not present:
        return "absent"
    return "partial"


@pytest.fixture
def artefacts():
    """Skip only when every required file is absent; fail loudly on a partial set."""
    state = artefact_state()
    if state == "absent":
        pytest.skip("no Stage A artefact is present in this checkout")
    if state == "partial":
        detail = {network: analyse.artefacts_present(network)[1] for network in analyse.NETWORKS}
        pytest.fail(
            f"the Stage A artefacts are partly present, which is an inconsistency: {detail}"
        )
    return {name: analyse.load_network(name) for name in analyse.NETWORKS}


def test_local_artefacts_load_consistently(artefacts):
    for name, net in artefacts.items():
        assert net.name == name
        assert net.n_near == int(net.envelopes["n_near"])
        assert set(net.oracle_total) == set(net.near_rows)
        assert all(total > 0.0 for total in net.oracle_total.values())


def test_local_summary_is_internally_consistent(artefacts):
    study = analyse.build_summary()
    summary = study.summary
    assert summary["holm_family"]["family_size"] == 4
    assert summary["ledger"]["total"] <= summary["ledger"]["ceiling"]
    for name in analyse.NETWORKS:
        for key in (
            "h1_correlation_dependent_reliability",
            "h2_prediction_against_decision",
            "h3_information_aware_and_robust",
        ):
            block = summary[key][name]
            assert block["formal_two_network"] == "Supported not attainable (A2)"
            if name == analyse.EVALUATION_NETWORK:
                assert block["single_network_verdict"]["verdict"] in (
                    "Supported",
                    "Rejected",
                    "Inconclusive",
                    analyse.NOT_EVALUABLE,
                )
            else:
                assert block["single_network_verdict"]["verdict"] == analyse.NOT_EVALUABLE
    assert summary["provenance"]["protocol"]["sha256"] == ec.PROTOCOL_SHA256
    assert summary["provenance"]["protocol"]["as_executed_sha256"] == ec.PROTOCOL_SHA256_EXECUTED


def test_local_figures_are_well_formed(artefacts):
    study = analyse.build_summary()
    figures = analyse.build_figures(study)
    assert [name for name, _ in figures] == [
        "fig_a_excitation_structure.svg",
        "fig_b_prediction_against_decision.svg",
        "fig_c_safety_against_utilisation.svg",
        "fig_d_correlation_strength.svg",
        "fig_e_model_disagreement.svg",
        "fig_f_negative_controls.svg",
    ]
    namespace = "{http://www.w3.org/2000/svg}"
    for name, text in figures:
        root = ET.fromstring(text)
        assert root.find(f"{namespace}title") is not None, name
        desc = root.find(f"{namespace}desc")
        assert desc is not None and desc.text, name
        assert "n = " in desc.text, name
        assert "ource" in desc.text, name


# --- the summary's provenance pins against the files on disk -------------------------------

CODE_PINS = {
    "frozen_code_sha256": tuple(analyse.FROZEN_CODE),
    "analysis_code_sha256": ("analyse.py", "svgplot.py"),
}


def _pin_problem(path: Path, pinned: str, label: str) -> list[str]:
    if not path.exists():
        return [f"{label}: {path} is missing"]
    digest = ec.sha256_of(path)
    if digest != pinned:
        return [f"{label}: on disk {digest} != pinned {pinned}"]
    return []


def pin_mismatches(base: Path, protocol: Path, expected_executed: str) -> list[str]:
    """Every disagreement between `stage_a_summary.json`'s pins and the files under `base`.

    An empty list means the artefact set on disk is exactly the one the summary was written
    from. A missing summary is itself a disagreement: nothing then pins the inputs.
    """
    summary_path = base / "results" / "stage_a_summary.json"
    if not summary_path.exists():
        return [f"{summary_path} is missing, so nothing pins the inputs"]
    provenance = json.loads(summary_path.read_text())["provenance"]
    problems = []
    for relative, pinned in sorted(provenance["inputs_sha256"].items()):
        problems += _pin_problem(base / relative, pinned, f"inputs_sha256[{relative}]")
    for key, names in CODE_PINS.items():
        pins = provenance[key]
        if sorted(pins) != sorted(names):
            problems.append(f"{key} pins {sorted(pins)}, expected {sorted(names)}")
        for name in names:
            if name in pins:
                problems += _pin_problem(base / name, pins[name], f"{key}[{name}]")
    problems += _pin_problem(protocol, provenance["protocol"]["sha256"], "protocol.sha256")
    if protocol.exists():
        executed = ec.executed_text_sha(protocol)
        if executed != expected_executed:
            problems.append(
                f"protocol as-executed sha256 {executed} != expected {expected_executed}"
            )
    return problems


def test_local_provenance_pins_match_the_files_on_disk(artefacts):
    """A corrupt or swapped artefact must fail here: the summary pins every input."""
    problems = pin_mismatches(analyse.HERE, ec.PROTOCOL, ec.PROTOCOL_SHA256_EXECUTED)
    assert not problems, "the summary's provenance pins disagree with the files on disk:\n" + (
        "\n".join(problems)
    )


def _synthetic_pinned_tree(root: Path) -> Path:
    """A minimal artefact tree whose summary pins every file in it. Returns the protocol."""
    (root / "results").mkdir()
    (root / "runs").mkdir()
    inputs = {
        "results/envelopes_rural3.json": '{"n_near": 10}\n',
        "runs/oracle_rural3.npz": "a stand-in for the replicate archive\n",
    }
    for relative, text in inputs.items():
        (root / relative).write_text(text)
    code = (*analyse.FROZEN_CODE, "analyse.py", "svgplot.py")
    for name in code:
        (root / name).write_text(f"# stand-in for {name}\n")
    protocol = root / "stage_a_protocol.md"
    protocol.write_text(f"# stand-in protocol\n{ec.AMENDMENTS_HEADING}\n\nA1 a dated decision\n")
    summary = {
        "provenance": {
            "inputs_sha256": {rel: ec.sha256_of(root / rel) for rel in inputs},
            "protocol": {"sha256": ec.sha256_of(protocol)},
            **{
                key: {name: ec.sha256_of(root / name) for name in names}
                for key, names in CODE_PINS.items()
            },
        }
    }
    (root / "results" / "stage_a_summary.json").write_text(json.dumps(summary))
    return protocol


def test_a_one_byte_change_to_a_pinned_input_fails_the_check(tmp_path):
    protocol = _synthetic_pinned_tree(tmp_path)
    executed = ec.executed_text_sha(protocol)
    assert pin_mismatches(tmp_path, protocol, executed) == []

    pinned_input = tmp_path / "results" / "envelopes_rural3.json"
    pinned_input.write_text(pinned_input.read_text().replace('"n_near": 10', '"n_near": 11'))
    problems = pin_mismatches(tmp_path, protocol, executed)
    assert len(problems) == 1
    assert problems[0].startswith("inputs_sha256[results/envelopes_rural3.json]: on disk ")

    (tmp_path / "results" / "stage_a_summary.json").unlink()
    assert pin_mismatches(tmp_path, protocol, executed) == [
        f"{tmp_path / 'results' / 'stage_a_summary.json'} is missing, so nothing pins the inputs"
    ]
