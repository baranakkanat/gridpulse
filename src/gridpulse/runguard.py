"""Protection of registered study outputs (Phase 6): one explicit output directory, a
manifest per stage, atomic writes, and refusal of reruns or inconsistent states.

- `begin` refuses a stage whose manifest exists (status "complete": the stage was run;
  status "running": an interrupted or concurrent run, to be inspected by hand) or whose
  output files exist without a manifest (stale files). It then writes the manifest with
  status "running", the experiment identity and the SHA-256 of code and protocol.
- `complete` records the SHA-256 of every output and sets status "complete".
- `verify` re-hashes a completed stage's outputs and lists any problem.
- `freeze` / `require_freeze`: the freeze is refused unless the code, dependency pins and
  protocol equal those that produced the development outputs; an evaluation runs only if
  they still equal the freeze and the development outputs still match it.

Not a database or an experiment platform: JSON files next to the outputs.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` via a temporary file in the same directory and a rename, so
    a reader never sees a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)  # mkstemp creates owner-only files
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, content) -> None:
    atomic_write_text(path, json.dumps(content, indent=2) + "\n")


ENVIRONMENT = ("pyproject.toml", "uv.lock")  # pinned dependencies: numpy streams can change


def code_hashes(protocol: str | None = None) -> dict:
    """SHA-256 of every package source file, the dependency pins and, if given, the
    protocol document."""
    hashes = {f"src/gridpulse/{p.name}": sha256(p) for p in sorted(PACKAGE.glob("*.py"))}
    hashes.update({name: sha256(REPO / name) for name in ENVIRONMENT if (REPO / name).exists()})
    if protocol is not None:
        hashes[protocol] = sha256(REPO / protocol)
    return hashes


def _create_exclusive(path: Path, content) -> None:
    """Write JSON to `path` only if it does not exist yet, atomically: a complete
    temporary file is hard-linked into place, which fails if another run got there first."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "w") as stream:
            stream.write(json.dumps(content, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o644)
        os.link(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def manifest_path(output_dir: Path, stage: str) -> Path:
    return Path(output_dir) / f"{stage}_manifest.json"


def begin(output_dir: Path, stage: str, identity: dict, protocol: str | None = None) -> dict:
    """Start `stage` in `output_dir`, or raise RuntimeError if that would overwrite or
    mix with an earlier run (see the module docstring)."""
    output_dir = Path(output_dir)
    manifest = manifest_path(output_dir, stage)
    if manifest.exists():
        status = json.loads(manifest.read_text()).get("status")
        if status == "complete":
            raise RuntimeError(f"{stage} already completed in {output_dir}; outputs are frozen")
        raise RuntimeError(
            f"{manifest} has status {status!r}: an interrupted or concurrent run. Inspect it "
            "and move the directory aside by hand; nothing is deleted automatically"
        )
    stale = (
        sorted(p.name for p in output_dir.glob(f"{stage}_*") if p.is_file())
        if output_dir.exists()
        else []
    )  # fmt: skip  (archived run folders such as development_v1/ are not outputs)
    if stale:
        raise RuntimeError(f"{stage} outputs without a manifest in {output_dir}: {stale}")
    record = {
        "stage": stage,
        "status": "running",
        "started_utc": _now(),
        "identity": identity,
        "code_sha256": code_hashes(protocol),
    }
    try:
        _create_exclusive(manifest, record)
    except FileExistsError as error:
        raise RuntimeError(f"{manifest} appeared during start: a concurrent run") from error
    return record


def complete(output_dir: Path, stage: str, outputs: list[Path]) -> dict:
    """Record the hashes of `outputs` and mark `stage` complete."""
    manifest = manifest_path(output_dir, stage)
    record = json.loads(manifest.read_text())
    if record.get("status") != "running":
        raise RuntimeError(f"{manifest} is not a running stage")
    protocol = next((n for n in record["code_sha256"] if n.endswith(".md")), None)
    if code_hashes(protocol) != record["code_sha256"]:
        raise RuntimeError("code, pins or protocol changed while the stage was running")
    record.update(
        status="complete",
        completed_utc=_now(),
        outputs={Path(p).name: sha256(p) for p in outputs},
    )
    atomic_write_json(manifest, record)
    return record


def verify(output_dir: Path, stage: str) -> list[str]:
    """Problems with a completed stage: missing manifest, wrong status, missing, changed
    or unlisted outputs. An empty list means the outputs are as recorded."""
    output_dir = Path(output_dir)
    manifest = manifest_path(output_dir, stage)
    if not manifest.exists():
        return [f"no manifest for {stage}"]
    record = json.loads(manifest.read_text())
    problems = [] if record.get("status") == "complete" else [f"status {record.get('status')}"]
    listed = record.get("outputs", {})
    for name, digest in listed.items():
        path = output_dir / name
        if not path.exists():
            problems.append(f"missing {name}")
        elif sha256(path) != digest:
            problems.append(f"changed {name}")
    present = {p.name for p in output_dir.glob(f"{stage}_*") if p.is_file()} - {manifest.name}
    problems += [f"unlisted {name}" for name in sorted(present - set(listed))]
    return problems


def freeze(output_dir: Path, protocol: str) -> dict:
    """After a verified development stage: record the code, protocol and development
    output hashes that the evaluation must run with."""
    problems = verify(output_dir, "development")
    if problems:
        raise RuntimeError(f"development stage does not verify: {problems}")
    path = Path(output_dir) / "freeze.json"
    development = json.loads(manifest_path(output_dir, "development").read_text())
    current = code_hashes(protocol)
    differ = sorted(
        name for name in set(current) | set(development["code_sha256"])
        if current.get(name) != development["code_sha256"].get(name)
    )  # fmt: skip
    if differ:
        raise RuntimeError(
            f"code or protocol differ from those that produced the development outputs: {differ}"
        )
    record = {
        "frozen_utc": _now(),
        "code_sha256": current,
        "development_outputs": development["outputs"],
    }
    try:
        _create_exclusive(path, record)
    except FileExistsError as error:
        raise RuntimeError(f"{path} exists; a freeze is recorded once") from error
    return record


def require_freeze(output_dir: Path, protocol: str) -> dict:
    """Raise RuntimeError unless a freeze exists, the current code and protocol equal it,
    and the development outputs still verify."""
    path = Path(output_dir) / "freeze.json"
    if not path.exists():
        raise RuntimeError("no freeze.json: run the development stage and freeze it first")
    record = json.loads(path.read_text())
    changed = sorted(
        name for name, digest in code_hashes(protocol).items()
        if record["code_sha256"].get(name) != digest
    )  # fmt: skip
    changed += sorted(set(record["code_sha256"]) - set(code_hashes(protocol)))
    if changed:
        raise RuntimeError(f"code or protocol changed since the freeze: {changed}")
    problems = verify(output_dir, "development")
    problems += [
        f"changed {name}" for name, digest in record["development_outputs"].items()
        if not (Path(output_dir) / name).exists() or sha256(Path(output_dir) / name) != digest
    ]  # fmt: skip
    if problems:
        raise RuntimeError(f"development outputs changed since the freeze: {problems}")
    return record
