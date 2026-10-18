# Phase 6 provenance

This folder holds the evidence for the Phase 6 pre-registration
(`docs/phase6_protocol.md`, with amendment 6A) and the scripts behind numbers quoted in
`docs/phase6_results.md`.

It contains code, timestamps and hashes only. Derived data stay in the git-ignored
`outputs/noise_study/`, because of the SimBench data licence. That folder holds:

- stage outputs and manifests;
- the freeze record;
- the archived first development run;
- the exploratory diagnostics and logs.

| File | What it shows |
|---|---|
| `registration_log.txt` | Timestamped SHA-256 records. In order:<br>1. protocol registration (with the disclosure of what was seen before);<br>2. amendment 6A and the archived first development run;<br>3. the guard's refusal of the first re-run, and its fix;<br>4. the freeze;<br>5. the single evaluation and its output hashes;<br>6. the post-evaluation diagnostic, reviews and engineering corrections |
| `scripts/development_diagnostics.py` | Development-only diagnostics of the noise mechanism and the alarm rules, run before registration |
| `scripts/se_diagnostics.py` | Development-only chi-square diagnostics of state estimation, run before registration |
| `scripts/post_evaluation_runs.py` | Post-evaluation diagnostic (not registered): longest true violation runs in closed loop with exact readings |
| `scripts/report.py` | All Phase 6 report tables from a stage's JSON outputs:<br>`python docs/provenance/phase6/scripts/report.py evaluation` |

## How the run is protected

- `src/gridpulse/runguard.py` writes a manifest at the start of each stage. The manifest
  holds:
  - its status;
  - the experiment identity;
  - the SHA-256 of the code, `pyproject.toml`, `uv.lock` and the protocol;
  - at completion, the SHA-256 of every output.
- **Exclusive start.** A stage starts exclusively and is refused when:
  - its manifest exists (completed or interrupted);
  - or output files of that stage exist without a manifest.
- **Freeze.** It is refused unless the code, pins and protocol equal those that produced
  the development outputs.
- **Evaluation.** It is refused unless the current hashes still equal the freeze and the
  development outputs still match it.

## The Phase 5 path is unchanged

Phase 6 adds identity-based noise (`sensing.NoiseBank`) as an opt-in path. The frozen
Phase 5 results remain reproducible:

- **Manual re-run.** Re-running Phase 5's semiurb4 evaluation analysis before and after
  the change matched the frozen outputs exactly: 504 of 504 decision runs.
- **Independent check.** A pre-evaluation review compared the committed and modified
  `sensing.py` on synthetic inputs and found them identical.
- **Unit test.** `test_phase5_legacy_path_is_pinned` fixes the legacy path's behaviour.
