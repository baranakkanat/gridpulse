# Phase 5 provenance

This folder holds the evidence for the Phase 5 pre-registration
(`docs/phase5_protocol.md`) and the scripts behind numbers quoted in
`docs/phase5_results.md`. As in Phase 4, it contains code, timestamps and hashes only.
Derived data stay in the git-ignored `outputs/sense_study/` because of the SimBench data
licence:

- the full-state cache;
- the results and hypotheses JSONs;
- the report and the figure.

| File | What it shows |
|---|---|
| `physics_started_utc.txt` | The full-state physics start (14:47 UTC) and its fingerprint. The physics depends on no Phase 5 design choice |
| `fullstate_provenance.json` | Days computed per network and truth, and the physics fingerprint |
| `registration_log.txt` | Timestamped SHA-256 records: protocol registration (15:25 UTC), amendments 5A/5B and the development re-run, the gate outcome and amendment 5C, the evaluation freeze, and the refused first evaluation launch |
| `development_run_metadata.json`, `evaluation_run_metadata.json` | Written by the code at run time: SHA-256 of every source file and the protocol, the measurement conditions, the design settings and the environment |
| `scripts/report.py` | Prints a stage's report tables from its JSON outputs (kept as `outputs/sense_study/development_report.md` and `outputs/sense_study/logs/evaluation_report.md`) |
| `scripts/figure.py` | Generates the one figure, `outputs/sense_study/figures/telemetry_noise.svg` |
| `scripts/exploratory_se_feedback.py` | The exploratory, development-only state-estimation feedback run (amendment 5C; not part of any hypothesis) |
| `scripts/post_evaluation_checks.py` | Post-evaluation checks quoted in the results (s. 11): the full-state margins are bit-identical to the Phase 4 cache (7,920 day arrays), and no daylight step has an unavoidable violation |

## Notes on completeness

- **The first development run is archived.** It ran before amendments 5A/5B and is kept
  in `outputs/sense_study/development_v1/`. Its open SE gate came from failed estimates
  raising no alarms (amendment 5C).
- **One evaluation run.** The first evaluation launch was refused by the re-run guard
  before any computation, because its own shell log was named `evaluation_*`. Its log is
  kept in `outputs/sense_study/logs/refused_attempt_evaluation_run.log`.
- **Machine-specific paths.** The scripts assume this repository layout and run from the
  repository root.
