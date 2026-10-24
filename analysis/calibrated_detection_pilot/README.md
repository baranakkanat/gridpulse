# Calibrated-detection pilot (exploratory, unregistered)

This directory is the four-step pilot of `docs/proposal_calibrated_detection.md` §10. The owner approved it on 2026-10-24.

- **Step 1:** `size_grid.py` → `results/size_grid.json`. Zero power flows.
- **Steps 2–4:** `eulv_pilot.py` → `eulv/`, `results/parts/eulv_timing.json` and `results/eulv_pilot.json`. 4,224 level-0 flows on pandapower's `ieee_european_lv_asymmetric`.

## What is public and what stays local

**Public:** this README, the two scripts and `tests/`.

**Local only, untracked:** `eulv/` and `results/`. They are derived data:
- Every voltage in `eulv/` comes from the IEEE European LV Test Feeder, driven by SimBench load and PV profiles.
- `results/` summarises those voltages, and also records step counts that come from the SimBench profiles.
- **IEEE feeder:** the scripts load it from the installed pandapower package and never copy it into this repository. No licence is stated for it (proposal §6, item A).
- **SimBench:** ODbL 1.0 / DbCL 1.0, per the installed `simbench` package's licence file. ODbL places attribution and share-alike obligations on derived databases.
- These files stay unpublished until two things happen: the IEEE terms are verified, and the owner decides how ODbL applies to the derived files. Attribution alone is not treated as permission.

**Running the tests without the local files:**
- All 51 tests run without `eulv/`, `results/` or any git-ignored `outputs/` file.
- **The four size-grid pipeline tests.** If the git-ignored frozen Phase 6 placements file is absent, they substitute 25 synthetic rules with the frozen names; under J5, a rule's bus identity carries no information. If the file is present, they read the real rules.
- Rerunning the scripts themselves needs the local Phase 6 outputs and the SimBench profiles.

## Scope

None of this is evidence for or against the proposal's hypotheses. It measures cost, the size grid's numbers and whether the pipeline works end to end. Phase 9's registered failures R3, R5 and R7 are unchanged.

## Errata from the independent QA check (AKK-46, PASS WITH LIMITATIONS)

Every result file is write-once, and each one records the sha256 of the script that produced it. So the corrections below are **recorded here** and not made in the scripts. Editing a script would break the hash link between it and its artefact. These corrections apply to any successor registration or rerun.

**E-1. K2's cell tolerance is a board interpretation, and the verdict depends on it.**
- Proposal §9 K2 is one sentence and fixes no N1 cell tolerance.
- The restriction to the 12 N1 cells, with one failing cell allowed (11 of 12), came from the board's AKK-44 brief. It was written before any rate existed and is recorded in `K2_rule`.
- The logic is the same one-sided 2.5 % per-cell logic as H1a's 33 of 36: P(Bin(12, 0.025) ≥ 2) = 0.035.
- It is not the proposal's text, and `K2_rule.source` should not read as if it were.
- urban6's C2-ref N1 block has **exactly one** failing cell, `sigma0.01_K1_N1_bb1`. With no failing cell allowed, that block would be FALSIFIED and K2 TRIPPED.
- Read the step-1 verdict as **K2 not tripped under the 11-of-12 reading**.

**E-2. Provenance limitation: `results/eulv_pilot.json` was overwritten and regenerated once, and the artefact does not record it.**
- The Implementer deleted the first report and regenerated it after lint-only edits to `eulv_pilot.py`. That breaks the write-once rule this pilot otherwise follows.
- The four leg artefacts in `eulv/` came from the pre-edit revision and were not regenerated.
- The legs carry no script hash, and no earlier revision of the script survives. So "lint-only" cannot be verified from the repository.
- What limits the risk: the stored voltages predate the edit, every reported number is recomputed from them at report time, and the 16 step 2–4 tests in `tests/test_eulv_pilot.py` pin the reduction.
- A successor should write `script_sha256` into each leg's sidecar.

**E-3. Tie-breaks for selection rules (a) and (c).**
- `SELECTION_RULES` states a tie-break only for rule (b).
- Rules (a) and (c) are implemented with the lowest first-segment index as the tie-break.

**E-4. Off-downstream night-sign shares are not a signature.**
- The off-downstream residuals are of order 1e-6 to 1e-9 p.u. On leg (a), max |k_ref| is 1.21e-6 and the share is 4 of 6.
- At that size their sign is numerical, not physical.
- Compare only the downstream shares: 0.35, 0.56 and 0.00.

**E-5. The illustrative C1 ratio is optimistic.**
- Its denominator leaves out the busbar noise term of proposal §3.2.
- That makes the ratio optimistic by a factor of √(1 + (σ_bb/σ_b)²): 2 % at ratio 0.2, and 41 % at σ_bb = σ_b.

**E-6. σ_bb is a ratio, not an absolute value.**
- The grid sets σ_bb = (σ_bb/σ_b) × σ_b. So the ratio-0.2 cells are σ_bb = 0.002 at σ = 0.01, and σ_bb = 0.001 at σ = 0.005.
- Proposal §6 defines the axis as a ratio. §2 and §3.2 quote the absolute 0.002.

**E-7. The scenario is not the proposal's §5 day synthesis.**
- The ten days are raw, consecutive SimBench development-half days. None of these were applied:
  - the day-level multiplicative scale;
  - the within-day AR(1) perturbation;
  - the day-level clear-sky index.
- All 28 PV units share one availability profile and inject active power only (unity power factor).
- This is adequate for a pipeline and cost pilot. No size or variance claim may rest on it.

**E-8. Step 1's "25 rules" are 25 interchangeable streams.**
- Under J5 they are 25 exchangeable K-meter noise streams. So H1a clause (ii)'s per-rule axis measures Monte Carlo scatter, not differences between placements.
- Nothing here shows robustness across the frozen Phase 6 placements.

**E-9. The busbar bus is not checked against the transformer.**
- `BUSBAR = 1` is hardcoded and never asserted against `net.trafo.lv_bus`.
- The artefact records `lv_bus = 1`, so this run is correct. The guard is still missing.

**E-10. Write discipline and flow budget.**
- **Step-1 writes are not atomic.** They are write-once through the frozen `q1.write_new_json`, which uses O_EXCL on the final path. An interrupted write would leave a truncated file that the same rule then refuses to replace. Steps 2–4 use temporary file plus `os.replace`.
- **Flow count.** Proposal §10 asks for about 4,000 flows: about 192 in step 3 and 3,840 in step 4. Step 3 was run twice, three-phase and balanced, for the R-d/K4 comparison. That gives 4,224 in total, 24 above the brief's rounded figure of about 4,200, as `results/eulv_pilot.json` `flows.note` records.

## Readings the QA check added

- **"H1a ACCEPTED" in step 1 is a measurement on the development half, not a passed pre-registered test.**
  - It holds under N1 and N2 only, and under this step's reading of the cell and K2 tolerances.
  - The C2-ref maximum per-rule rate is 0.066. The grid-wide maximum, 0.0685, belongs to the unreferenced C2 comparator.
- **There is no detectable referencing size penalty at 2,000 replicates per rule.**
  - The per-cell difference between C2-ref and C2 runs from −0.0055 to +0.0020.
  - Read that as "no detectable penalty", not as "slightly negative".
- **The signal is marginal.**
  - The C1 floor scales as D^(−1/2). The same arithmetic gives ratios of ≈ 0.83, 0.21 and 0.009 at the main study's D = 60, and leg (a) ≈ 1.29 at D = 145. This is HYPOTHESIS: it assumes the per-day count structure carries over.
  - With no customer over the floor on any leg, H1b retention would be 0/0 on this feeder. That is undefined, not failed.
  - H3 is untested here, not supported.
  - **K5 is a live risk on real topologies.**
- **K1 is NOT TRIPPED, with a 2.2× margin on this feeder.**
  - That is 27.8 CPU-h against the 60 CPU-h limit, single-worker, without numba.
  - It does not show that the main study is affordable on ENWL feeders.
  - It excludes the superposition sub-study, which needs another 103,680 solves.
