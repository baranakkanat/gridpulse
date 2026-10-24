"""Unit tests of the Phase 9 sweep engine, driver and gate (`phase9_sweep.py`).

Every test here runs on synthetic data. No power flow is solved, no network is loaded and no
cache or `vm` array is read, so the whole file is cheap and touches no Phase 9 statistic. The
pieces that need the grid (`error_network`, `level0_states`, `expected_specs`,
`structural_checks`) assert their own registered invariants and are exercised by Stage G.

The four held-out networks of registration s. 2 are never named here.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import numpy as np
import pandas as pd
import phase9_sweep as ps
import pytest

KEY = "0" * 64
OTHER_KEY = "1" * 64


def spec(line: int = 7, error: str = "E-R", factor: float = 1.5, rating: float = 0.8,
         item: str = "W6", network: str = "net-a") -> ps.RunSpec:  # fmt: skip
    return ps.RunSpec(network, line, error, factor, rating, item)


def synthetic_rows(n_days: int, n_buses: int) -> list[dict]:
    return [
        {
            "dmean_daylight": np.full(n_buses, 1e-3 * (i + 1), dtype=np.float64),
            "dmean_night": np.full(n_buses, -5e-4, dtype=np.float64),
            "n_daylight_valid": 40,
            "n_night_valid": 56,
            "n_daylight_steps": 40,
            "n_night_steps": 56,
            "failed_truth": 0,
            "nan_nominal": 0,
        }
        for i in range(n_days)
    ]


def written(path, run: ps.RunSpec, key: str = KEY, n_days: int = 3, n_buses: int = 2):
    """Write one synthetic artefact and return (arrays, sidecar)."""
    days = list(range(182, 182 + n_days))
    arrays = ps.build_arrays(synthetic_rows(n_days, n_buses), days, range(n_buses))
    sidecar = ps.sidecar_payload(
        run, key, arrays, {"runtime_seconds": 12.5, "workers": 3, "pool_worked": True}
    )
    ps.write_run(path, arrays, sidecar)
    return arrays, sidecar


# --- s. 7: the per-day reduction over valid steps ------------------------------------------


def test_reduce_day_averages_valid_steps_only_and_counts_them():
    steps, buses = 8, 3
    truth = np.full((steps, buses), 1.0)  # Delta = 1.0 wherever nothing else is set
    nominal = np.zeros((steps, buses))
    daylight = np.array([True, True, True, True, False, False, False, False])
    truth[0] = 3.0  # Delta = 3.0 on one valid daylight step
    truth[1] = np.nan  # a failed truth flow on a daylight step
    nominal[5] = np.nan  # a non-finite nominal step at night

    out = ps.reduce_day(truth, nominal, daylight)

    # valid daylight steps are 0, 2, 3 -> mean of (3, 1, 1) = 5/3; valid night steps 4, 6, 7
    assert out["n_daylight_steps"] == 4
    assert out["n_night_steps"] == 4
    assert out["n_daylight_valid"] == 3
    assert out["n_night_valid"] == 3
    assert out["failed_truth"] == 1  # step 1 only; a nominal NaN is not a failed truth flow
    assert out["nan_nominal"] == buses  # non-finite nominal *entries*, i.e. day x bus cells
    assert np.allclose(out["dmean_daylight"], 5.0 / 3.0)
    assert np.allclose(out["dmean_night"], 1.0)


def test_reduce_day_is_nan_when_a_leg_has_no_valid_step():
    steps, buses = 4, 2
    truth = np.full((steps, buses), np.nan)
    nominal = np.zeros((steps, buses))
    truth[2:] = 1.0
    daylight = np.array([True, True, False, False])

    out = ps.reduce_day(truth, nominal, daylight)

    assert out["n_daylight_valid"] == 0
    assert np.isnan(out["dmean_daylight"]).all()
    assert out["n_night_valid"] == 2
    assert np.allclose(out["dmean_night"], 1.0)
    assert out["failed_truth"] == 2


def test_reduce_day_accumulates_in_float64():
    steps, buses = 2, 1
    truth = np.array([[1.0 + 1e-9], [1.0 + 3e-9]])
    nominal = np.ones((steps, buses))
    out = ps.reduce_day(truth, nominal, np.array([True, False]))
    assert out["dmean_daylight"].dtype == np.float64
    assert out["dmean_daylight"][0] == pytest.approx(1e-9, rel=1e-6)


def test_reduce_day_refuses_mismatched_shapes():
    with pytest.raises(ValueError):
        ps.reduce_day(np.zeros((4, 2)), np.zeros((4, 3)), np.ones(4, dtype=bool))
    with pytest.raises(ValueError):
        ps.reduce_day(np.zeros((4, 2)), np.zeros((4, 2)), np.ones(3, dtype=bool))


def test_build_arrays_writes_float32_means_and_int_counters():
    days = [182, 183, 184]
    arrays = ps.build_arrays(synthetic_rows(3, 2), days, [5, 9])
    for name, (dtype, _) in ps.ARRAY_SPEC.items():
        assert arrays[name].dtype == np.dtype(dtype), name
    assert arrays["dmean_daylight"].shape == (3, 2)
    assert arrays["day_index"].tolist() == days
    assert arrays["bus_index"].tolist() == [5, 9]


def test_build_arrays_refuses_a_row_count_that_is_not_the_scored_days():
    with pytest.raises(ValueError):
        ps.build_arrays(synthetic_rows(2, 2), [182, 183, 184], [0, 1])


# --- s. 7: the atomic write -----------------------------------------------------------------


def test_write_run_is_atomic_and_stores_both_keys_in_both_files(tmp_path):
    run = spec()
    path = tmp_path / "a" / run.network / f"{run.stem}.npz"
    arrays, sidecar = written(path, run)

    assert path.exists() and ps.sidecar_path(path).exists()
    assert not list(path.parent.glob("*.partial.*"))
    with np.load(path) as data:
        assert str(data["physics_key"]) == KEY
        assert str(data["spec_key"]) == run.spec_key
        assert np.array_equal(data["dmean_daylight"], arrays["dmean_daylight"])
    payload = json.loads(ps.sidecar_path(path).read_text())
    assert payload["physics_key"] == KEY and payload["spec_key"] == run.spec_key
    assert payload == sidecar


def test_write_run_leaves_no_partial_file_when_the_npz_write_fails(tmp_path, monkeypatch):
    run = spec()
    path = tmp_path / "a" / run.network / f"{run.stem}.npz"
    path.parent.mkdir(parents=True)
    days = [182, 183, 184]
    arrays = ps.build_arrays(synthetic_rows(3, 2), days, [0, 1])
    sidecar = ps.sidecar_payload(run, KEY, arrays, {})

    def boom(file, **kwargs):
        Path(file).write_bytes(b"half an npz")  # the temporary file now exists
        raise OSError("disk full")

    monkeypatch.setattr(ps.np, "savez_compressed", boom)
    with pytest.raises(OSError):
        ps.write_run(path, arrays, sidecar)

    assert not path.exists()
    assert not ps.sidecar_path(path).exists()
    assert not list(path.parent.glob("*.partial.*"))


def test_write_run_leaves_no_partial_file_when_the_sidecar_write_fails(tmp_path, monkeypatch):
    run = spec()
    path = tmp_path / "a" / run.network / f"{run.stem}.npz"
    days = [182, 183, 184]
    arrays = ps.build_arrays(synthetic_rows(3, 2), days, [0, 1])
    sidecar = ps.sidecar_payload(run, KEY, arrays, {})

    monkeypatch.setattr(ps, "json_text", lambda payload: (_ for _ in ()).throw(ValueError("x")))
    with pytest.raises(ValueError):
        ps.write_run(path, arrays, sidecar)

    assert not path.exists()
    assert not ps.sidecar_path(path).exists()
    assert not list(path.parent.glob("*.partial.*"))


# --- s. 7: an artefact is accepted only after both keys are recomputed ----------------------


def test_verify_run_accepts_a_matching_artefact(tmp_path):
    run = spec()
    path = tmp_path / f"{run.stem}.npz"
    _, sidecar = written(path, run)
    assert ps.verify_run(path, KEY, run, 3) == sidecar
    assert ps.run_status(run, KEY, 3, tmp_path / "missing")["status"] == "missing"


def test_verify_run_refuses_a_different_physics_key(tmp_path):
    run = spec()
    path = tmp_path / f"{run.stem}.npz"
    written(path, run)
    with pytest.raises(RuntimeError, match="delete it and recompute"):
        ps.verify_run(path, OTHER_KEY, run, 3)


def test_verify_run_refuses_a_different_spec_key(tmp_path):
    run = spec(line=7)
    path = tmp_path / f"{run.stem}.npz"
    written(path, run)
    for other in (spec(line=8), spec(factor=1.25), spec(error="E-L", rating=1.0),
                  spec(network="net-b")):  # fmt: skip
        with pytest.raises(RuntimeError):
            ps.verify_run(path, KEY, other, 3)


def test_verify_run_refuses_a_wrong_row_count(tmp_path):
    run = spec()
    path = tmp_path / f"{run.stem}.npz"
    written(path, run, n_days=3)
    with pytest.raises(RuntimeError, match="rows for"):
        ps.verify_run(path, KEY, run, 183)


def test_verify_run_refuses_a_malformed_artefact(tmp_path):
    run = spec()

    truncated = tmp_path / "truncated.npz"
    written(truncated, run)
    truncated.write_bytes(b"PK\x03\x04 not an npz")
    with pytest.raises(RuntimeError, match="unreadable npz"):
        ps.verify_run(truncated, KEY, run, 3)

    orphan = tmp_path / "orphan.npz"
    written(orphan, run)
    ps.sidecar_path(orphan).unlink()
    with pytest.raises(RuntimeError, match="sidecar JSON is missing"):
        ps.verify_run(orphan, KEY, run, 3)

    bad_json = tmp_path / "bad_json.npz"
    written(bad_json, run)
    ps.sidecar_path(bad_json).write_text("{not json")
    with pytest.raises(RuntimeError, match="unreadable sidecar JSON"):
        ps.verify_run(bad_json, KEY, run, 3)

    incomplete = tmp_path / "incomplete.npz"
    np.savez_compressed(incomplete, physics_key=np.asarray(KEY),
                        spec_key=np.asarray(run.spec_key), day_index=np.arange(3, dtype=np.int32),
                        bus_index=np.arange(2, dtype=np.int32))  # fmt: skip
    ps.sidecar_path(incomplete).write_text(json.dumps({"physics_key": KEY,
                                                       "spec_key": run.spec_key}))  # fmt: skip
    with pytest.raises(RuntimeError, match="missing arrays"):
        ps.verify_run(incomplete, KEY, run, 3)

    wrong_dtype = tmp_path / "wrong_dtype.npz"
    days = [182, 183, 184]
    arrays = ps.build_arrays(synthetic_rows(3, 2), days, [0, 1])
    arrays["dmean_daylight"] = arrays["dmean_daylight"].astype(np.float64)
    ps.write_run(wrong_dtype, arrays, ps.sidecar_payload(run, KEY, arrays, {}))
    with pytest.raises(RuntimeError, match="dtype"):
        ps.verify_run(wrong_dtype, KEY, run, 3)

    disagreeing = tmp_path / "disagreeing.npz"
    written(disagreeing, run)
    payload = json.loads(ps.sidecar_path(disagreeing).read_text())
    payload["spec_key"] = OTHER_KEY
    ps.sidecar_path(disagreeing).write_text(json.dumps(payload))
    with pytest.raises(RuntimeError, match="sidecar keys differ"):
        ps.verify_run(disagreeing, KEY, run, 3)


# --- s. 7: deterministic keys ---------------------------------------------------------------


def test_spec_key_is_deterministic_and_separates_every_field():
    assert spec().spec_key == spec().spec_key
    base = spec().spec_key
    assert len({base, spec(line=8).spec_key, spec(factor=1.25).spec_key,
                spec(error="E-L", rating=1.0).spec_key, spec(rating=0.9).spec_key,
                spec(network="net-b").spec_key}) == 6  # fmt: skip
    # the work item is a label, not a physics input, so it is not part of the key
    assert spec(item="W6").spec_key == spec(item="W8").spec_key


def test_physics_key_is_deterministic_and_sensitive_to_every_part():
    parts = {
        "stress_fingerprint": "a",
        "fullstate_fingerprint": "b",
        "nominal_leg_manifests": {"net-a": "{}", "net-b": "{}"},
        "pandapower_version": "3.5.6",
        "numpy_version": "2.4.6",
        "schema_version": 1,
        "level": 0,
        "steps": 96,
        "scored_days": [182, 183],
        "reduction_definition": ps.REDUCTION_TEXT,
    }
    assert ps.physics_key(parts) == ps.physics_key(dict(parts))
    assert ps.physics_key(parts) == ps.physics_key(dict(reversed(list(parts.items()))))
    keys = {ps.physics_key(parts)}
    for name, replacement in (
        ("stress_fingerprint", "z"),
        ("fullstate_fingerprint", "z"),
        ("nominal_leg_manifests", {"net-a": "{}", "net-b": '{"x": 1}'}),
        ("pandapower_version", "3.5.7"),
        ("numpy_version", "2.4.7"),
        ("schema_version", 2),
        ("level", 1),
        ("steps", 48),
        ("scored_days", [182, 184]),
        ("reduction_definition", "other"),
    ):
        keys.add(ps.physics_key({**parts, name: replacement}))
    assert len(keys) == 11


def test_artefact_path_and_stem_follow_the_registered_layout():
    assert ps.factor_text(1.5) == "1.5"
    assert ps.factor_text(2.0) == "2"
    assert ps.factor_text(1.25) == "1.25"
    run = spec(line=37, factor=1.5)
    path = ps.artefact_path(run, KEY, root="/tmp/sweep")
    assert path.parts[-3:] == (KEY[:16], "net-a", "E-R-1.5-line37.npz")
    assert ps.sidecar_path(path).name == "E-R-1.5-line37.json"
    assert ps.artefact_path(spec(line=3, error="E-L", factor=1.25, rating=1.0), KEY).name == (
        "E-L-1.25-line3.npz"
    )


# --- s. 7: the derived manifest -------------------------------------------------------------


def test_derive_manifest_scans_and_reverifies(tmp_path):
    runs = [spec(line=7), spec(line=8), spec(line=3, error="E-L", factor=1.25, rating=1.0,
                                             item="W9")]  # fmt: skip
    for run in runs:
        written(ps.artefact_path(run, KEY, tmp_path), run)

    manifest = ps.derive_manifest(tmp_path, KEY, runs, days=[182, 183, 184])

    assert manifest["physics_key_prefix"] == KEY[:16]
    assert manifest["present_runs"] == {"W6": 2, "W8": 0, "W9": 1}
    assert manifest["complete"] is False
    assert [r["line"] for r in manifest["runs"]] == [3, 7, 8]
    assert all(r["runtime_seconds"] == 12.5 and r["workers"] == 3 for r in manifest["runs"])
    assert manifest["other_physics_keys"] == {}

    rewritten = ps.write_manifest(tmp_path, KEY, runs, days=[182, 183, 184])
    on_disk = json.loads((tmp_path / "manifest.json").read_text())
    assert on_disk == json.loads(json.dumps(ps.plain(rewritten)))
    assert not list(tmp_path.glob("manifest.partial.json"))
    # derived, so it is rebuilt rather than refused
    assert ps.write_manifest(tmp_path, KEY, runs, days=[182, 183, 184])["present_runs"] == (
        manifest["present_runs"]
    )


def test_derive_manifest_separates_other_physics_keys(tmp_path):
    runs = [spec(line=7)]
    written(ps.artefact_path(runs[0], KEY, tmp_path), runs[0])
    stale = ps.artefact_path(runs[0], OTHER_KEY, tmp_path)
    written(stale, runs[0], key=OTHER_KEY)

    manifest = ps.derive_manifest(tmp_path, KEY, runs, days=[182, 183, 184])

    assert manifest["present_runs"]["W6"] == 1
    assert manifest["other_physics_keys"] == {OTHER_KEY[:16]: [str(stale.relative_to(tmp_path))]}


def test_derive_manifest_refuses_unexpected_and_partial_artefacts(tmp_path):
    runs = [spec(line=7)]
    written(ps.artefact_path(runs[0], KEY, tmp_path), runs[0])
    intruder = spec(line=99)
    written(ps.artefact_path(intruder, KEY, tmp_path), intruder)
    with pytest.raises(RuntimeError, match="no registered run expects"):
        ps.derive_manifest(tmp_path, KEY, runs, days=[182, 183, 184])

    ps.artefact_path(intruder, KEY, tmp_path).unlink()
    ps.sidecar_path(ps.artefact_path(intruder, KEY, tmp_path)).unlink()
    (tmp_path / KEY[:16] / "net-a" / "E-R-1.5-line7.partial.npz").write_bytes(b"x")
    with pytest.raises(RuntimeError, match="partial artefact"):
        ps.derive_manifest(tmp_path, KEY, runs, days=[182, 183, 184])


# --- s. 4: the error networks change only the intended line --------------------------------


def line_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "from_bus": [0, 1, 2],
            "to_bus": [1, 2, 3],
            "r_ohm_per_km": [0.2, 0.3, 0.4],
            "x_ohm_per_km": [0.08, 0.09, 0.10],
            "c_nf_per_km": [210.0, 220.0, 230.0],
            "length_km": [0.05, 0.06, 0.07],
            "max_i_ka": [0.27, 0.28, 0.29],
            "parallel": [1, 1, 1],
        },
        index=[0, 1, 2],
    )


def test_apply_error_r_changes_only_the_target_line_r_and_rating():
    net = types.SimpleNamespace(line=line_table())
    before = line_table()

    ps.apply_error(net, "E-R", 1.5, 1, 0.8)

    assert net.line.loc[1, "r_ohm_per_km"] == pytest.approx(0.3 * 1.5)
    assert net.line.loc[1, "max_i_ka"] == pytest.approx(0.28 * 0.8)
    untouched = [c for c in before.columns if c not in ("r_ohm_per_km", "max_i_ka")]
    pd.testing.assert_frame_equal(net.line[untouched], before[untouched])
    for column in ("r_ohm_per_km", "max_i_ka"):
        others = [i for i in before.index if i != 1]
        pd.testing.assert_series_equal(net.line.loc[others, column], before.loc[others, column])


def test_apply_error_l_changes_only_the_target_line_length():
    net = types.SimpleNamespace(line=line_table())
    before = line_table()

    ps.apply_error(net, "E-L", 1.25, 2, 1.0)

    assert net.line.loc[2, "length_km"] == pytest.approx(0.07 * 1.25)
    untouched = [c for c in before.columns if c != "length_km"]
    pd.testing.assert_frame_equal(net.line[untouched], before[untouched])
    pd.testing.assert_series_equal(
        net.line.loc[[0, 1], "length_km"], before.loc[[0, 1], "length_km"]
    )
    # R and X scale together because both are the per-km value times the length
    for column in ("r_ohm_per_km", "x_ohm_per_km"):
        after = net.line.loc[2, column] * net.line.loc[2, "length_km"]
        assert after == pytest.approx(before.loc[2, column] * before.loc[2, "length_km"] * 1.25)


def test_apply_error_refuses_an_unknown_type_a_missing_line_and_an_e_l_rating():
    net = types.SimpleNamespace(line=line_table())
    with pytest.raises(ValueError, match="unknown error type"):
        ps.apply_error(net, "E-X", 1.5, 0, 0.8)
    with pytest.raises(ValueError, match="not in the line table"):
        ps.apply_error(net, "E-R", 1.5, 99, 0.8)
    with pytest.raises(ValueError, match="rating factor is 1.0"):
        ps.apply_error(net, "E-L", 1.25, 0, 0.8)
    pd.testing.assert_frame_equal(net.line, line_table())


def test_run_spec_refuses_an_e_l_rating_factor_and_a_bad_factor():
    with pytest.raises(ValueError, match="rating factor is 1.0"):
        ps.RunSpec("net-a", 3, "E-L", 1.25, 0.8, "W9")
    with pytest.raises(ValueError, match="must be positive"):
        ps.RunSpec("net-a", 3, "E-R", 0.0, 0.8, "W6")
    with pytest.raises(ValueError, match="unknown error type"):
        ps.RunSpec("net-a", 3, "E-C", 1.5, 0.8, "W6")


def test_registered_constants_match_the_registration():
    assert ps.EXPECTED_RUNS == {"W6": 89, "W8": 6, "W9": 4}
    assert sum(ps.EXPECTED_RUNS.values()) == 99
    assert ps.REGISTERED_CANDIDATES == {"1-LV-semiurb4--2-sw": 39, "1-LV-urban6--2-sw": 50}
    assert ps.REGISTERED_CABLE == {"1-LV-semiurb4--2-sw": 37, "1-LV-urban6--2-sw": 3}
    assert ps.W8_R_FACTORS == (1.1, 1.25, 2.0) and ps.W6_R_FACTOR not in ps.W8_R_FACTORS
    assert ps.W9_L_FACTORS == (1.25, 1.5)
    assert ps.RATING_FACTOR == 0.8 and ps.W6_R_FACTOR == 1.5
    assert ps.LEVEL == 0 and ps.STEPS == 96


# --- s. 11.4: the gate's tolerance bands ----------------------------------------------------


def test_classify_at_the_registered_boundaries():
    assert ps.classify(0.0) == "PASS"
    assert ps.classify(1e-6) == "PASS"  # PASS is "<= 1e-6"
    assert ps.classify(np.nextafter(1e-6, 1.0)) == "WARN"
    assert ps.classify(5e-6) == "WARN"
    assert ps.classify(1e-5) == "WARN"  # WARN is "(1e-6, 1e-5]"
    assert ps.classify(np.nextafter(1e-5, 1.0)) == "ABORT"
    assert ps.classify(1e-4) == "ABORT"
    assert ps.classify(float("nan")) == "ABORT"
    assert ps.classify(float("inf")) == "ABORT"


def test_worst_verdict_takes_the_strictest():
    assert ps.worst_verdict("PASS", "PASS") == "PASS"
    assert ps.worst_verdict("PASS", "WARN") == "WARN"
    assert ps.worst_verdict("WARN", "ABORT") == "ABORT"
    assert ps.worst_verdict("ABORT", "PASS") == "ABORT"


# --- s. 7: the time budget ------------------------------------------------------------------


def test_budget_allows_starts_no_run_that_would_exceed_the_budget():
    assert ps.budget_allows(0.0, None, 1e9) is True  # no budget, no limit
    assert ps.budget_allows(0.0, 200.0, 120.0) is True
    assert ps.budget_allows(0.0, 120.0, 120.0) is True  # exactly the budget still starts
    assert ps.budget_allows(0.1, 120.0, 120.0) is False
    assert ps.budget_allows(0.0, 100.0, 120.0) is False  # too small for even one run
    assert ps.budget_allows(900.0, 1080.0, 120.0) is True
    assert ps.budget_allows(1000.0, 1080.0, 120.0) is False


# --- s. 12 Stage 0: the registration-commit check -------------------------------------------


def git_stub(log: tuple[int, str], diff: tuple[int, str]):
    def run(args: list[str]) -> tuple[int, str]:
        if args[0] == "log":
            return log
        if args[0] == "diff":
            return diff
        raise AssertionError(f"unexpected git call {args!r}; only read-only git is allowed")

    return run


def test_registration_state_accepts_a_committed_unmodified_file():
    state = ps.registration_state(git_stub((0, "a" * 40), (0, "")))
    assert state["committed"] and state["unmodified"] and state["ok"]
    assert state["commit"] == "a" * 40
    assert state["reasons"] == []
    assert state["sha256"] == ps.REGISTRATION_SHA256


def test_registration_state_rejects_an_untracked_file():
    state = ps.registration_state(git_stub((0, ""), (0, "")))
    assert not state["committed"] and not state["ok"]
    assert state["commit"] is None
    assert "not tracked in any commit" in state["reasons"][0]


def test_registration_state_rejects_a_modified_file():
    state = ps.registration_state(git_stub((0, "b" * 40), (1, "")))
    assert state["committed"] and not state["unmodified"] and not state["ok"]
    assert "differs from HEAD" in state["reasons"][0]


def test_require_committed_registration_accepts_and_refuses():
    assert ps.require_committed_registration(git_stub((0, "c" * 40), (0, "")))["ok"]
    with pytest.raises(RuntimeError, match="Stage 2 refuses to run"):
        ps.require_committed_registration(git_stub((0, ""), (0, "")))
    with pytest.raises(RuntimeError, match="Stage 2 refuses to run"):
        ps.require_committed_registration(git_stub((0, "c" * 40), (1, "")))


def test_sweep_refuses_while_the_registration_is_uncommitted(tmp_path):
    """Stage 2 must not start before the owner's commit (s. 12). The refusal happens before
    any network is loaded, so this test still solves no power flow."""
    with pytest.raises(RuntimeError, match="committed and unmodified"):
        ps.run_sweep(stage="w6", max_runs=1, time_budget_seconds=60.0, root=tmp_path,
                     git=git_stub((0, ""), (0, "")))  # fmt: skip
    with pytest.raises(RuntimeError, match="Stage 2 refuses to run"):
        ps.run_sweep(stage="all", root=tmp_path, git=git_stub((0, "d" * 40), (1, "")))
    assert not list(tmp_path.iterdir())


def test_the_registration_on_disk_still_has_the_bound_sha256():
    assert ps._sha256_file(ps.REPO / ps.REGISTRATION) == ps.REGISTRATION_SHA256
