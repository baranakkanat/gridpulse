# Phase 7 provenance

This folder holds the evidence for the Phase 7 pre-registration
(`docs/phase7_protocol.md`, with amendment 7A) and the scripts behind numbers quoted in
`docs/phase7_results.md`.

It contains code, timestamps and hashes only. Derived data stay in the git-ignored
`outputs/margin_study/` and `outputs/demonstrator/`, because of the SimBench data
licence. `outputs/margin_study/` holds:

- stage outputs and manifests;
- the freeze record;
- the archived first development run (`development_v1/`);
- the exploratory probe and the post-evaluation true-offset check (`exploratory/`);
- the report tables (`logs/`).

| File | What it shows |
|---|---|
| `registration_log.txt` | Timestamped SHA-256 records. In order:<br>1. protocol registration (with the disclosure of what was seen before);<br>2. amendment 7A (the full-metering line-current fix, the busbar-only label, the added sensitivities) and the archived first development run;<br>3. the amended development stage and the pre-freeze check;<br>4. the freeze;<br>5. the single evaluation and its output hashes;<br>6. the post-evaluation engineering record: code changed after the evaluation, the replay evidence, a corrected pre-freeze count and a metadata omission |
| `scripts/development_probe.py` | Development-only probe of the corrector, run before registration |
| `scripts/report.py` | All Phase 7 report tables from a stage's JSON outputs:<br>`python docs/provenance/phase7/scripts/report.py evaluation` |
| `post_evaluation_reviews.md` | The final reports of the four post-evaluation reviews, the privacy review of the pilot concept and the final evidence gate, archived verbatim |
| `scripts/true_offsets.py` | Post-evaluation, evaluator-side check (not registered): the true busbar offset against C1's v̂ on the evaluation half |

## How the run is protected

Phase 7 uses the Phase 6 guard (`src/gridpulse/runguard.py`). It provides:

- stage manifests;
- exclusive start;
- a freeze bound to the code, pins and protocol of the development outputs;
- an evaluation that is refused unless the current hashes still equal the freeze.

## Code changed after the evaluation

The code changed after the single evaluation, for the demonstrator and for fixes from
the post-evaluation reviews. The changes are listed in `registration_log.txt` and in
`docs/phase7_results.md` s. 11. None changes a registered result.

- **`runguard.require_freeze` now refuses a new Phase 7 evaluation.** The code differs
  from the freeze. This is intended: the evaluation was run once.
- **`runguard.verify` still passes** for the stored development and evaluation outputs.
- **Removing the two post-freeze additions to `sensing.py`** (the opt-in `trace` argument
  and the legacy-path bias guard) gives the frozen hash exactly.
- **Replay on the current tree reproduces the stored outputs exactly:**
  - Phase 7 semiurb4 nominal and tap, every stored value (1738 and 1739 values);
  - Phase 6 semiurb4 nominal, 607 of 607 run summaries.

## Earlier phases are unchanged

The corrector, the busbar bias and the trace are opt-in. With their defaults, the
Phase 5 and Phase 6 paths behave as before:

- `test_phase5_legacy_path_is_pinned` passes.
- The Phase 6 replay above matches.
