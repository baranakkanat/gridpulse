"""Tests of Stage 3 run in parts (`stage3 --part`, `--part merge`, `stage3-benchmark`).

Everything here is synthetic. No power flow is solved, no cache is opened, no sweep artefact
is read, no `vm` array is loaded and the four held-out networks of registration s. 2 are never
loaded: `stage3_context`, `stage3_core` and `control3_network` are replaced by stubs, so the
tests exercise the part mechanics and the merge, not the real pipeline.

The binding property is that splitting Stage 3 changes no number. It is checked two ways:
block-level, that a control restricted to one sigma_tot is bit-identical to that sigma's slice
of the full run; and end-to-end, that the controls block `merge` assembles from written part
files is byte-identical to the monolithic `controls`.
"""

from __future__ import annotations

import json

import numpy as np
import phase9_analysis as pa
import pytest
from test_phase9_controls import TOY_DOWNSTREAM, toy_arrays, toy_inputs, toy_stats

CODE = "synthetic-network"
REPLICATES = {"control1_replicates": 6, "fa_replicates": 3, "cov_replicates": 3,
              "permutations": 4}  # fmt: skip
INPUTS_SHA = "a" * 64
PHYSICS_KEY = "c" * 64


def git_clean(args):
    """A tracked, unmodified registration (the real file's sha256 is the registered one)."""
    return (0, "b" * 40) if args[0] == "log" else (0, "")


def git_untracked(args):
    """`git log` returns no commit: s. 12 Stage 0 refuses Stages 1-3."""
    return (0, "")


def toy_loaded() -> dict:
    arrays = toy_arrays(days=40, buses=8)
    return {
        (CODE, "W6", "E-R", 1.5, line): {"stats": toy_stats(), "arrays": arrays}
        for line in TOY_DOWNSTREAM
    }


def text(payload) -> str:
    """The exact bytes Stage 3 would write for `payload`."""
    return pa.json_text(pa.plain(payload))


@pytest.fixture
def one_network(monkeypatch, tmp_path):
    """One synthetic network wired in as the whole of Stage 3: a stubbed context, core and
    control 3, a written `phase9_inputs.json` and a clean injected git."""
    inputs, loaded = toy_inputs(CODE), toy_loaded()
    monkeypatch.setattr(pa, "SWEEP_NETWORKS", (CODE,))
    monkeypatch.setattr(pa, "ALL_NETWORKS", (CODE,))
    inputs_path = tmp_path / "phase9_inputs.json"
    pa.write_new_json_atomic(inputs_path, inputs)

    state = {"inputs_sha": INPUTS_SHA, "physics_key": PHYSICS_KEY}

    def fake_context(path=inputs_path, root=None, git=None):
        return {
            "registration": {"ok": True, "commit": "b" * 40},
            "stage1_file": {"path": str(path), "sha256": state["inputs_sha"], "inputs": inputs},
            "inputs": inputs,
            "days": [],
            "physics_key": state["physics_key"],
            "specs": [],
            "manifest": {"complete": True},
            "loaded": loaded,
            "failed_flows": {"within_limits": True},
        }

    monkeypatch.setattr(pa, "stage3_context", fake_context)
    monkeypatch.setattr(pa, "stage3_core", lambda context: {"stage": "3 core", "networks": {}})
    monkeypatch.setattr(
        pa, "control3_network",
        lambda code, _inputs, permutations=pa.PERMUTATIONS: {
            "network": code, "permutations": int(permutations), "stub": True,
        },
    )  # fmt: skip
    return {"inputs": inputs, "loaded": loaded, "inputs_path": inputs_path,
            "parts_dir": tmp_path / "stage3_parts", "state": state}  # fmt: skip


def write_every_part(fixture, **overrides) -> None:
    """Every part of `expected_stage3_parts`, at the test replicate counts."""
    for item in pa.expected_stage3_parts():
        pa.stage3_part(
            item["part"], network=item["network"], sigma=item["sigma"],
            inputs_path=fixture["inputs_path"], parts_dir=fixture["parts_dir"],
            git=git_clean, **{**REPLICATES, **overrides},
        )  # fmt: skip


# --- the part list and the file names ------------------------------------------------------


def test_the_part_list_is_the_registered_decomposition(monkeypatch):
    monkeypatch.setattr(pa, "SWEEP_NETWORKS", ("net-a", "net-b"))
    monkeypatch.setattr(pa, "ALL_NETWORKS", ("net-a", "net-b", "held-1", "held-2"))

    parts = pa.expected_stage3_parts()
    names = [item["part"] for item in parts]

    assert names.count("core") == 1
    assert names.count("control1") == 2  # once per sweep network
    assert names.count("control2_fa") == 4  # network x sigma_tot
    assert names.count("control2_cov") == 4
    assert names.count("control3") == 4  # once per `local_line` cable
    assert names.count("control45") == 1
    assert names[0] == "core" and names[-1] == "control45"
    assert [item["sigma"] for item in parts if item["part"] == "control2_fa"] == [
        "0.005", "0.01", "0.005", "0.01"
    ]


def test_the_part_file_name_carries_the_network_and_the_sigma(tmp_path):
    assert pa.part_path("core", None, None, tmp_path).name == "core.json"
    assert pa.part_path("control1", CODE, None, tmp_path).name == f"control1-{CODE}.json"
    assert pa.part_path("control2_fa", CODE, "0.005", tmp_path).name == (
        f"control2_fa-{CODE}-0.005.json"
    )
    assert pa.part_path("control2_fa", CODE, "0.005").parent == pa.STAGE3_PARTS
    assert pa.STAGE3_PARTS == pa.RESULTS / "stage3_parts"


@pytest.mark.parametrize(
    ("part", "network", "sigma", "message"),
    [
        ("control1", None, None, "runs per network"),
        ("core", "1-LV-urban6--2-sw", None, "does not run per network"),
        ("control2_fa", "1-LV-urban6--2-sw", None, "runs per sigma_tot"),
        ("control1", "1-LV-urban6--2-sw", "0.01", "does not run per sigma_tot"),
        ("control1", "1-LV-rural1--2-sw", None, "not a part-control1 network"),
        ("control2_fa", "1-LV-urban6--2-sw", "0.02", "not an s. 10 control 2 sigma_tot"),
        ("stage3", None, None, "is not a Stage 3 part"),
    ],
)
def test_a_part_refuses_coordinates_it_does_not_have(part, network, sigma, message):
    with pytest.raises(ValueError, match=message):
        pa.check_part_arguments(part, network, sigma)


def test_control3_runs_at_a_held_out_network_and_the_other_parts_do_not():
    pa.check_part_arguments("control3", "1-LV-semiurb5--2-sw", None)  # s. 10's six cables

    with pytest.raises(ValueError, match="not a part-control2_fa network"):
        pa.check_part_arguments("control2_fa", "1-LV-semiurb5--2-sw", "0.01")


# --- a control restricted to one sigma_tot is that sigma's slice of the full run ------------


def test_control_2_fa_at_one_sigma_is_bit_identical_to_the_full_run(one_network):
    net = pa.control_network_inputs(CODE, one_network["inputs"], one_network["loaded"])

    full = pa.control2_fa_block(net, replicates=4)
    parts = [pa.control2_fa_block(net, replicates=4,
                                  conditions={sigma: pa.A_STAR_CONDITIONS[sigma]})  # fmt: skip
             for sigma in sorted(pa.A_STAR_CONDITIONS)]  # fmt: skip

    assert text(pa.merge_per_sigma(parts)) == text(full)
    assert list(parts[0]["per_sigma_tot"]) == ["0.005"]


def test_control_2_cov_at_one_sigma_is_bit_identical_to_the_full_run(one_network):
    net = pa.control_network_inputs(CODE, one_network["inputs"], one_network["loaded"])

    full = pa.control2_cov_block(net, replicates=4)
    parts = [pa.control2_cov_block(net, replicates=4,
                                   conditions={sigma: pa.A_STAR_CONDITIONS[sigma]})  # fmt: skip
             for sigma in sorted(pa.A_STAR_CONDITIONS)]  # fmt: skip

    assert text(pa.merge_per_sigma(parts)) == text(full)


def test_merging_two_parts_carrying_the_same_sigma_is_refused():
    block = {"per_sigma_tot": {"0.01": {"rate": 1.0}}}

    with pytest.raises(RuntimeError, match="both carry sigma_tot 0.01"):
        pa.merge_per_sigma([block, block])

    with pytest.raises(ValueError, match="at least one control 2 block"):
        pa.merge_per_sigma([])


# --- a written part, and the refusal to overwrite one --------------------------------------


def test_a_part_records_its_wall_time_the_inputs_hash_and_the_physics_key(one_network):
    record = pa.stage3_part(
        "control1", network=CODE, inputs_path=one_network["inputs_path"],
        parts_dir=one_network["parts_dir"], git=git_clean, **REPLICATES,
    )  # fmt: skip

    path = pa.part_path("control1", CODE, None, one_network["parts_dir"])
    assert path.exists()
    assert record["wall_seconds"] >= 0.0
    assert record["stage1_inputs"]["sha256"] == INPUTS_SHA
    assert record["physics_key"] == PHYSICS_KEY
    assert record["registration"]["sha256"] == pa.REGISTRATION_SHA256
    on_disk = json.loads(path.read_text())
    assert on_disk["payload"]["control"] == "1"
    assert on_disk["per_network"] == {"cables": 2, "day_axis": 39}
    assert "sha256" not in on_disk  # the file cannot carry its own hash


def test_a_part_refuses_to_overwrite_itself(one_network):
    pa.stage3_part("control45", inputs_path=one_network["inputs_path"],
                   parts_dir=one_network["parts_dir"], git=git_clean, **REPLICATES)  # fmt: skip
    path = pa.part_path("control45", None, None, one_network["parts_dir"])
    before = path.read_text()

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        pa.stage3_part("control45", inputs_path=one_network["inputs_path"],
                       parts_dir=one_network["parts_dir"], git=git_clean, **REPLICATES)  # fmt: skip

    assert path.read_text() == before


def test_the_atomic_write_refuses_an_existing_file_and_leaves_no_temporary(tmp_path):
    path = tmp_path / "part.json"
    sha = pa.write_new_json_atomic(path, {"a": 1})

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        pa.write_new_json_atomic(path, {"a": 2})

    assert pa.q1.sha256_text(path.read_text()) == sha
    assert sorted(p.name for p in tmp_path.iterdir()) == ["part.json"]


@pytest.mark.parametrize("part", pa.STAGE3_COMPUTE_PARTS)
def test_every_part_refuses_while_the_registration_is_uncommitted(part, one_network):
    network = CODE if part in pa.PARTS_BY_NETWORK else None
    sigma = "0.01" if part in pa.PARTS_BY_SIGMA else None

    with pytest.raises(RuntimeError, match="no --allow-uncommitted flag"):
        pa.stage3_part(part, network=network, sigma=sigma, git=git_untracked,
                       inputs_path=one_network["inputs_path"],
                       parts_dir=one_network["parts_dir"], **REPLICATES)  # fmt: skip

    assert not pa.part_path(part, network, sigma, one_network["parts_dir"]).exists()
    assert not one_network["parts_dir"].exists()


def test_a_part_refuses_without_stage_1s_file(one_network, tmp_path):
    with pytest.raises(RuntimeError, match="Stage 1 must run"):
        pa.stage3_part("control45", inputs_path=tmp_path / "missing.json",
                       parts_dir=one_network["parts_dir"], git=git_clean, **REPLICATES)  # fmt: skip

    assert not one_network["parts_dir"].exists()


# --- merge ---------------------------------------------------------------------------------


def test_merge_assembles_the_monolithic_controls_block_byte_for_byte(one_network):
    write_every_part(one_network)

    merged = pa.merge_stage3_parts(
        parts_dir=one_network["parts_dir"],
        results_path=one_network["parts_dir"] / "phase9_results.json",
        git=git_clean,
    )
    monolithic = pa.controls(
        one_network["inputs"], one_network["loaded"],
        control1_replicates=REPLICATES["control1_replicates"],
        fa_replicates=REPLICATES["fa_replicates"],
        cov_replicates=REPLICATES["cov_replicates"],
        permutations=REPLICATES["permutations"],
    )  # fmt: skip

    assert text(merged["controls"]) == text(monolithic)
    assert text(merged["R7"]) == text(monolithic["R7"])


@pytest.mark.parametrize("control", ["control_1", "control_2_A_star_fa", "control_2_A_star_cov",
                                     "control_3", "control_4", "control_5"])  # fmt: skip
def test_each_control_is_bit_identical_in_parts_and_monolithic(control, one_network):
    """The same property as the test above, one control at a time, so a regression names the
    control it broke instead of hiding in a whole-block comparison.

    Controls 1, 2 (both variants), 4 and 5 run their real implementations here. Control 3 is
    the stub of the `one_network` fixture, because the real `control3_network` reads the
    read-only per-step caches and this issue forbids real data; the stub still carries the
    coordinates the part is called with, so what is checked is that `stage3_part` and the
    monolithic `controls` reach control 3 with the same network and permutation count.
    """
    write_every_part(one_network)

    merged = pa.merge_stage3_parts(
        parts_dir=one_network["parts_dir"],
        results_path=one_network["parts_dir"] / "phase9_results.json",
        git=git_clean,
    )
    monolithic = pa.controls(
        one_network["inputs"], one_network["loaded"],
        control1_replicates=REPLICATES["control1_replicates"],
        fa_replicates=REPLICATES["fa_replicates"],
        cov_replicates=REPLICATES["cov_replicates"],
        permutations=REPLICATES["permutations"],
    )  # fmt: skip

    assert text(merged["controls"][control]) == text(monolithic[control])
    assert merged["controls"][control]  # a control that merged to nothing would compare equal


def test_merge_writes_the_results_file_with_the_parts_provenance(one_network):
    write_every_part(one_network)
    results_path = one_network["parts_dir"] / "phase9_results.json"

    merged = pa.merge_stage3_parts(parts_dir=one_network["parts_dir"],
                                   results_path=results_path, git=git_clean)  # fmt: skip

    expected = pa.expected_stage3_parts()
    assert merged["stage"] == "3 core"  # the stubbed `core` payload, unchanged
    assert list(merged) == ["stage", "networks", "controls", "controls_note", "R7", "parts",
                            "sha256"]  # `sha256` is the return value only, not in the file
    assert list(json.loads(results_path.read_text())) == [
        "stage", "networks", "controls", "controls_note", "R7", "parts"
    ]
    assert merged["parts"]["count"] == len(expected)
    assert merged["parts"]["stage1_inputs_sha256"] == INPUTS_SHA
    assert merged["parts"]["physics_key"] == PHYSICS_KEY
    assert len(merged["parts"]["per_part"]) == len(expected)
    assert merged["parts"]["wall_seconds_total"] > 0.0
    on_disk = json.loads(results_path.read_text())
    assert pa.q1.sha256_text(results_path.read_text()) == merged["sha256"]
    assert on_disk["parts"]["physics_key"] == PHYSICS_KEY

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        pa.merge_stage3_parts(parts_dir=one_network["parts_dir"], results_path=results_path,
                              git=git_clean)  # fmt: skip


def test_merge_refuses_a_missing_part(one_network):
    write_every_part(one_network)
    pa.part_path("control2_cov", CODE, "0.01", one_network["parts_dir"]).unlink()
    results_path = one_network["parts_dir"] / "phase9_results.json"

    with pytest.raises(RuntimeError, match="Stage 3 parts are missing"):
        pa.merge_stage3_parts(parts_dir=one_network["parts_dir"], results_path=results_path,
                              git=git_clean)  # fmt: skip

    assert not results_path.exists()


def test_merge_refuses_a_mismatched_inputs_hash(one_network):
    for item in pa.expected_stage3_parts():
        one_network["state"]["inputs_sha"] = (
            "f" * 64 if item["part"] == "control45" else INPUTS_SHA
        )
        pa.stage3_part(item["part"], network=item["network"], sigma=item["sigma"],
                       inputs_path=one_network["inputs_path"],
                       parts_dir=one_network["parts_dir"], git=git_clean, **REPLICATES)  # fmt: skip
    results_path = one_network["parts_dir"] / "phase9_results.json"

    with pytest.raises(RuntimeError, match="2 different phase9_inputs.json hashes"):
        pa.merge_stage3_parts(parts_dir=one_network["parts_dir"], results_path=results_path,
                              git=git_clean)  # fmt: skip

    assert not results_path.exists()


def test_merge_refuses_a_mismatched_physics_key(one_network):
    for item in pa.expected_stage3_parts():
        one_network["state"]["physics_key"] = (
            "e" * 64 if item["part"] == "core" else PHYSICS_KEY
        )
        pa.stage3_part(item["part"], network=item["network"], sigma=item["sigma"],
                       inputs_path=one_network["inputs_path"],
                       parts_dir=one_network["parts_dir"], git=git_clean, **REPLICATES)  # fmt: skip
    results_path = one_network["parts_dir"] / "phase9_results.json"

    with pytest.raises(RuntimeError, match="2 different sweep physics keys"):
        pa.merge_stage3_parts(parts_dir=one_network["parts_dir"], results_path=results_path,
                              git=git_clean)  # fmt: skip

    assert not results_path.exists()


def test_merge_refuses_while_the_registration_is_uncommitted(one_network):
    """`merge` writes the registered results file, so s. 12 Stage 0 binds it too: with every
    part present and agreeing, an uncommitted registration still refuses the merge."""
    write_every_part(one_network)
    results_path = one_network["parts_dir"] / "phase9_results.json"

    with pytest.raises(RuntimeError, match="no --allow-uncommitted flag"):
        pa.merge_stage3_parts(parts_dir=one_network["parts_dir"], results_path=results_path,
                              git=git_untracked)  # fmt: skip

    assert not results_path.exists()


@pytest.mark.parametrize("change", [
    {"state": {"ok": True, "commit": "9" * 40}},  # a part computed under another commit
    {"sha256": "d" * 64},                         # a part computed under another registration
], ids=["commit", "sha256"])  # fmt: skip
def test_merge_refuses_a_part_recording_a_different_registration(change, one_network):
    """A part is written under one registration commit; `merge` must not assemble the results
    file from a part that records a different commit or sha256 (s. 12)."""
    write_every_part(one_network)
    path = pa.part_path("control1", CODE, None, one_network["parts_dir"])
    record = json.loads(path.read_text())
    record["registration"].update(change)
    path.unlink()  # the part files refuse to be overwritten in place
    pa.write_new_json_atomic(path, record)
    results_path = one_network["parts_dir"] / "phase9_results.json"

    with pytest.raises(RuntimeError, match="record a different registration") as refusal:
        pa.merge_stage3_parts(parts_dir=one_network["parts_dir"], results_path=results_path,
                              git=git_clean)  # fmt: skip

    assert f"1 of {len(pa.expected_stage3_parts())}" in str(refusal.value)
    assert f"control1-{CODE} records commit" in str(refusal.value)
    assert not results_path.exists()


# --- the monolithic path still composes the same report ------------------------------------


def test_the_monolithic_report_is_the_core_block_plus_the_controls_block():
    report = pa.stage3_report({"stage": "3 core", "networks": {}}, {"R7": {"holds": True}})

    assert list(report) == ["stage", "networks", "controls", "controls_note", "R7"]
    assert report["R7"] is report["controls"]["R7"]
    assert "s. 10 controls 1-5" in report["controls_note"]


# --- `stage3-benchmark`: synthetic, at the real shapes -------------------------------------


def test_the_benchmark_shapes_are_the_registered_cable_and_day_counts():
    by_network = {shape["network"]: shape for shape in pa.BENCHMARK_SHAPES}

    assert set(by_network) == set(pa.SWEEP_NETWORKS)
    for code, shape in by_network.items():
        assert shape["cables"] == pa.REGISTERED_CANDIDATES[code]
        assert shape["retained_days"] == pa.REGISTERED_RETAINED[code]
        assert shape["scored_days"] == 183
    assert {shape["buses"] for shape in pa.BENCHMARK_SHAPES} == {43, 58}


def test_the_benchmark_inputs_are_synthetic_and_carry_the_registered_shapes():
    shape = pa.BENCHMARK_SHAPES[1]

    net = pa.benchmark_network_inputs(shape)

    assert len(net["buses"]) == shape["buses"]
    assert len(net["lines"]) == shape["cables"]
    assert len(net["rules"]) == pa.EXPECTED_RULES
    assert net["counts"]["simulated_days"] == shape["retained_days"] - 1  # the 1-day delay
    assert not np.asarray(net["truth_k"]).any()  # truth = nominal everywhere
    assert sorted(net["rules"]) == sorted((*pa.NAMED_RULES, *pa.RANDOM_RULES))


def test_the_benchmark_projects_every_part_and_touches_no_real_data():
    report = pa.stage3_benchmark(fraction=0.002)

    assert report["touches_real_data"] is False
    expected = pa.expected_stage3_parts()
    assert len(report["projected_parts"]) == len(expected)
    assert [entry["part"] for entry in report["projected_parts"]] == [
        item["part"] for item in expected
    ]
    for entry in report["projected_parts"]:
        assert entry["projected_seconds"] >= pa.CONTEXT_ALLOWANCE_SECONDS
        assert entry["limit_seconds"] == pa.PART_LIMIT_SECONDS
        assert entry["fits"] is (entry["projected_seconds"] <= pa.PART_LIMIT_SECONDS)
    assert report["every_part_fits"] is not report["parts_over_the_limit"]
    assert len(report["invocations"]) == len(expected)


def test_the_benchmark_refuses_a_fraction_outside_the_unit_interval():
    for fraction in (0.0, -0.5, 1.5):
        with pytest.raises(ValueError, match="replicate fraction is in"):
            pa.stage3_benchmark(fraction=fraction)


# --- the CLI -------------------------------------------------------------------------------


def test_the_stage3_part_flag_accepts_only_the_registered_part_names():
    with pytest.raises(SystemExit):
        pa.main(["stage3", "--part", "controls"])


def test_the_benchmark_subcommand_exits_zero_when_every_part_fits(capsys):
    assert pa.main(["stage3-benchmark", "--fraction", "0.002"]) == 0

    captured = capsys.readouterr()
    assert "stage3-benchmark PASS" in captured.err
    assert "min projected" in captured.err
    assert '"benchmark"' in captured.out
