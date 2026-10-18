import json

import pytest

from gridpulse import runguard


def _run(tmp_path, stage="development", text="{}", protocol=None):
    runguard.begin(tmp_path, stage, {"study": "test"}, protocol)
    out = tmp_path / f"{stage}_results.json"
    runguard.atomic_write_text(out, text)
    return runguard.complete(tmp_path, stage, [out]), out


def test_completed_stage_is_frozen_and_verifies(tmp_path):
    record, out = _run(tmp_path)
    assert record["status"] == "complete" and out.name in record["outputs"]
    assert runguard.verify(tmp_path, "development") == []
    with pytest.raises(RuntimeError, match="already completed"):
        runguard.begin(tmp_path, "development", {"study": "test"})
    assert out.read_text() == "{}"  # nothing overwritten


def test_interrupted_run_and_stale_files_are_refused(tmp_path):
    runguard.begin(tmp_path, "evaluation", {"study": "test"})  # never completed
    with pytest.raises(RuntimeError, match="interrupted or concurrent"):
        runguard.begin(tmp_path, "evaluation", {"study": "test"})
    other = tmp_path / "other"
    other.mkdir()
    (other / "evaluation_results.json").write_text("{}")  # left over, no manifest
    with pytest.raises(RuntimeError, match="without a manifest"):
        runguard.begin(other, "evaluation", {"study": "test"})


def test_verify_detects_changed_missing_and_unlisted_outputs(tmp_path):
    _, out = _run(tmp_path)
    out.write_text('{"edited": true}')
    (tmp_path / "development_extra.json").write_text("{}")
    problems = runguard.verify(tmp_path, "development")
    assert f"changed {out.name}" in problems and "unlisted development_extra.json" in problems
    out.unlink()
    assert f"missing {out.name}" in runguard.verify(tmp_path, "development")


def test_atomic_write_leaves_the_old_file_on_failure(tmp_path):
    target = tmp_path / "results.json"
    runguard.atomic_write_json(target, {"a": 1})
    with pytest.raises(TypeError):
        runguard.atomic_write_json(target, {"a": object()})
    assert json.loads(target.read_text()) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["results.json"]  # no temporary file
    assert target.stat().st_mode & 0o777 == 0o644  # readable like any output


def test_evaluation_requires_an_unchanged_freeze(tmp_path, monkeypatch):
    monkeypatch.setattr(runguard, "REPO", tmp_path)
    protocol = tmp_path / "protocol.md"
    protocol.write_text("registered")
    with pytest.raises(RuntimeError, match="no freeze"):
        runguard.require_freeze(tmp_path, "protocol.md")
    _run(tmp_path, protocol="protocol.md")
    runguard.freeze(tmp_path, "protocol.md")
    runguard.require_freeze(tmp_path, "protocol.md")  # unchanged: passes
    with pytest.raises(RuntimeError, match="recorded once"):
        runguard.freeze(tmp_path, "protocol.md")
    protocol.write_text("edited after the freeze")
    with pytest.raises(RuntimeError, match="changed since the freeze"):
        runguard.require_freeze(tmp_path, "protocol.md")
    protocol.write_text("registered")
    (tmp_path / "development_results.json").write_text('{"tuned": true}')
    with pytest.raises(RuntimeError, match="development outputs changed"):
        runguard.require_freeze(tmp_path, "protocol.md")


def test_freeze_requires_the_code_that_produced_the_development_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(runguard, "REPO", tmp_path)
    protocol = tmp_path / "protocol.md"
    protocol.write_text("registered")
    _run(tmp_path, protocol="protocol.md")
    protocol.write_text("amended after the development stage")
    with pytest.raises(RuntimeError, match="produced the development outputs"):
        runguard.freeze(tmp_path, "protocol.md")
    assert not (tmp_path / "freeze.json").exists()


def test_stage_start_is_exclusive(tmp_path):
    target = tmp_path / "evaluation_manifest.json"
    runguard._create_exclusive(target, {"status": "running", "by": "first"})
    with pytest.raises(FileExistsError):
        runguard._create_exclusive(target, {"status": "running", "by": "second"})
    assert json.loads(target.read_text())["by"] == "first"
    assert [p.name for p in tmp_path.iterdir()] == [target.name]  # no temporary file left


def test_archived_run_folders_are_not_stale_outputs(tmp_path):
    (tmp_path / "development_v1").mkdir()  # an earlier run moved aside by hand
    (tmp_path / "development_v1" / "development_results.json").write_text("{}")
    _run(tmp_path)  # starts and completes normally
    assert runguard.verify(tmp_path, "development") == []


def test_completion_is_refused_if_the_code_changed_during_the_run(tmp_path, monkeypatch):
    monkeypatch.setattr(runguard, "REPO", tmp_path)
    (tmp_path / "protocol.md").write_text("registered")
    runguard.begin(tmp_path, "evaluation", {"study": "test"}, "protocol.md")
    out = tmp_path / "evaluation_results.json"
    runguard.atomic_write_text(out, "{}")
    (tmp_path / "protocol.md").write_text("edited while running")
    with pytest.raises(RuntimeError, match="changed while the stage was running"):
        runguard.complete(tmp_path, "evaluation", [out])
    assert json.loads(runguard.manifest_path(tmp_path, "evaluation").read_text())["status"] == (
        "running"
    )
