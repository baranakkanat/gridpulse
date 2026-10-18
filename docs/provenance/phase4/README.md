# Phase 4 provenance

This folder holds the evidence for the Phase 4 pre-registration and the scripts behind
numbers quoted in `docs/research_protocol.md` (s. 4) and `docs/experiment_results.md`. It
contains code, timestamps and hashes only. Derived data stay in the git-ignored
`outputs/dual_study/`: physics cache, survey JSONs, hosting-capacity JSON, results. The
reason is the SimBench data licence.

| File | What it shows |
|---|---|
| `ELIGIBILITY_PRESPECIFIED.md` | Network eligibility rules, written at 13:35 UTC before the network survey ran |
| `physics_started_utc.txt` | Physics start (14:05 UTC) and resume times, and the physics fingerprint |
| `protocol_s4_registered.txt` | Timestamped SHA-256 records: s. 4 registration, amendments 4A–4D, the 4D pre-commitment, the evaluation freeze and post-evaluation notes |
| `development_run_metadata.json`, `evaluation_run_metadata.json` | Written by the code at run time: SHA-256 of every source file and the protocol, settings, environment |
| `scripts/survey/` | Development-half network survey (`survey.py`), scaled-network survey (`survey_scaled.py`) and hosting-capacity search (`hc.py`) |
| `scripts/diagnosis/` | Exploratory rural1 diagnosis (s. 4.1), the decision-layer cross-check against Phase 3 (`check_cell.py`) and the variant smoke tests |
| `scripts/report/report.py` | Generates `outputs/dual_study/<stage>_report.md` from a stage's JSON outputs |
| `scripts/post_evaluation_reviews/` | Scripts of the independent post-evaluation reviews: statistics (`t*.py`), power systems (`a*.py`) and the readiness gate (`spot.py`). They are the source of the reviewer-computed numbers quoted in the results, e.g. 83.4 MWh, the seed and block-length stability, the share of PV downstream of the binding line, and the 2016-07-23 event |

## Notes on completeness

- **The evaluation-freeze block lists only 6 of the 14 hashed files** in
  `protocol_s4_registered.txt`: a `head` in the recording pipeline cut the output short.
  The complete list of source hashes at run time is in `evaluation_run_metadata.json`.
- **Post-evaluation hash state.**
  - Every source file is unchanged since the run, except the `__main__.py` re-run guard
    fix (old and new hashes logged).
  - The protocol is restored to exactly its registered text: its SHA-256 equals the
    recorded value.
- **One development output was not archived.** The failing development output that
  triggered amendment 4D (urban6 `static_aci` index 6.93) was overwritten by the re-check
  run.
- **Machine-specific paths.** The review scripts assume this repository layout and, in
  places, scratch paths on the original machine. They are kept for audit, not as a
  supported tool.
