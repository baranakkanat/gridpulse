import numpy as np
import pytest

pytest.importorskip("pandapower")

from gridpulse import demonstrator as dm  # noqa: E402
from gridpulse import dual_study as ds  # noqa: E402
from gridpulse import sensing as sn  # noqa: E402
from gridpulse.__main__ import main  # noqa: E402
from gridpulse.grid_study import STEPS  # noqa: E402

SUB = sn.Config("substation", transformer=True, heads=(0,))


def test_trace_records_the_applied_caps_and_changes_nothing():
    from test_sensing import _context  # noqa: PLC0415

    ctx = _context(line_violation_day=44)
    args = (ctx, "replay_aci", SUB, sn.MeasurementModel(), 0, ds.OnlineSettings())
    plain = sn.run_feedback_policy(*args)
    trace: dict = {}
    traced = sn.run_feedback_policy(*args, trace=trace)
    assert plain == traced
    assert {r["day"] for r in traced} <= set(trace)  # warm-up days are traced too
    assert all(levels.shape == (STEPS,) for levels in trace.values())


def _scenario():
    margins = {"vm_margin": [0.02, -0.003, 0.005], "line_margin": [-5.0, 12.0]}
    daylight = [False] * 30 + [True] * 40 + [False] * 26
    return {
        "network": "net<1>", "truth": "tap_raise_lv", "day": 200, "step": 48,
        "timestamp": "2016-07-19 12:00 UTC", "safety_margin": 0.02,
        "positions": {1: (30.0, 30.0), 2: (100.0, 80.0), 3: (150.0, 160.0)},
        "edges": [(1, 2, 0), (2, 3, 1)], "busbar": 1, "heads": [0], "meters": [3],
        "buses": [1, 2, 3], "lines": 2, "daylight": daylight,
        "panels": {"No action (true state)": margins, "C1 decision (true state)": margins},
        "timeline": {"No action": {"levels": [0] * 96, "violated": [False] * 50 + [True] * 46},
                     "C1": {"levels": [3] * 96, "violated": [False] * 96}},
        "policies": [{"label": "C1 <corrected>", "key": "C1/0", "cap_level": 3,
                      "cap_fraction": 0.7, "day_violations": 0, "day_mwh": 0.5,
                      "estimates": {"v_hat": 0.02}, "label_in_force": "PHYSICAL_MODEL_UNCERTAINTY",
                      "meters": 0}],
        "frozen": {"C1/0": {"avoidable_violation_steps": 1.0, "curtailed_mwh": 12.4,
                            "meets_beta": True}},
    }  # fmt: skip


def test_page_is_static_escaped_and_labelled_exploratory():
    page = dm.render(_scenario())
    assert page.startswith("<!doctype html>")
    assert "exploratory" in page.lower() and "not a control system" in page.lower()
    assert "net&lt;1&gt;" in page and "C1 &lt;corrected&gt;" in page  # escaped
    for external in ("<script", "http://", "https://", "<link", "src="):
        assert external not in page  # self-contained, no network access
    assert "-0.0030" in page and "-5.0" in page  # p.u. and % shown separately
    assert page.count("<svg") == 3  # two network panels and the timeline
    assert "Different units; never added" in page


def test_cli_refuses_unregistered_inputs(tmp_path, capsys):
    assert main(["demonstrate", "--network", "nope", "--output-dir", str(tmp_path)]) == 1
    assert "unregistered network" in capsys.readouterr().err
    assert main(["demonstrate", "--truth", "line_r_plus20", "--output-dir", str(tmp_path)]) == 1
    assert "not in the Phase 7 study" in capsys.readouterr().err
    assert not list(tmp_path.iterdir())


def test_colour_scale_is_signed():
    assert dm._colour(-0.001, 0.01) == "#c0392b"
    assert dm._colour(0.005, 0.01) == "#e67e22"
    assert dm._colour(0.02, 0.01) == "#2e8b57"
    assert dm._colour(np.nan, 0.01) == "#888888"


def test_phase8_page_shows_reserves_and_unfavourable_verdicts_as_they_are():
    sc = _scenario()
    sc["phase"] = 8
    sc["truth"] = "mv_daily"
    sc["policies"][0]["reserves"] = (0.0015, 1.5)
    sc["tuned"] = {"C1": 0.02, "C1f": 0.015, "C5_r_v": 0.0015, "C5_r_l": 1.5}
    sc["frozen"] = {"C5": {"avoidable_violation_steps": 3.0, "curtailed_mwh": 10.0,
                           "meets_beta": True,
                           "violations_by_type": {"over_v": 2, "under_v": 0, "line": 1,
                                                  "trafo": 0}}}  # fmt: skip
    h5 = {p: {"covers": False, "cells": 2} for p in ("B2", "B3", "C1", "C5", "C6")}
    sc["verdicts"] = {
        "H1": {"met": False, "attribution": "none", "non_inferior": False,
               "mismatch_ratio": 0.95, "nominal_ratio": 1.02},
        "H2": {"met": False, "non_inferior": True, "non_inferior_development": False,
               "mismatch_ratio": 0.8, "nominal_ratio": 0.7},
        "H5": h5,
    }  # fmt: skip
    page = dm.render(sc)
    assert "H1, separate fixed reserves (C5) vs C1: not met" in page
    assert "also in the development half: not met" in page
    assert "C5 does not cover (2/5)" in page
    assert "0.0015 p.u. / 1.5 %" in page and "2 / 1" in page  # voltage / loading, separately
    for external in ("<script", "http://", "https://", "<link", "src="):
        assert external not in page
