# Phase 8 provenance

This folder holds the evidence for the Phase 8 pre-registration
(`docs/phase8_protocol.md`, with amendment 8A) and the scripts behind numbers quoted in
`docs/phase8_results.md`.

It contains code, timestamps and hashes only. Derived data stay in the git-ignored
`outputs/robust_study/`, because of the SimBench data licence. That folder holds:

- the Phase 8 physics cache (`fullstate_cache/`, about 1.6 GB);
- the stage outputs and manifests;
- the freeze record;
- the pre-registration diagnosis (`exploratory/`);
- the logs and report tables (`logs/`).

| File | What it shows |
|---|---|
| `registration_log.txt` | Timestamped SHA-256 records. In order:<br>1. protocol registration (with what was seen before);<br>2. amendment 8A after two pre-evaluation reviews;<br>3. the physics, development and freeze records;<br>4. the single evaluation and its output hashes;<br>5. the post-evaluation record |
| `protocol_registered.md`, `literature_registered.md` | The protocol and literature exactly as registered (sha256 2cc2d955… and 9698a25f…), reconstructed byte-for-byte after the evaluation. Amendment 8A was a pure append to the protocol, so s. 1–12 are unchanged |
| `scripts/diagnose_types.py` | Pre-registration, development-only diagnosis: Phase 7 violations by constraint type |
| `scripts/physics_driver.py` | The driver that computed the physics cache, through the same function as the `physics` stage, which then verified every folder |
| `scripts/report.py` | All Phase 8 report tables from a stage's JSON outputs:<br>`python docs/provenance/phase8/scripts/report.py evaluation` |

## How the run is protected

As in Phases 6 and 7 (`src/gridpulse/runguard.py`), plus:

- **Physics stage.** It records each cache folder's share of failed flows and a digest
  of its files.
  - A condition with more than 1 % failed flows would be dropped. None was.
  - The evaluation is refused if any digest has changed.
- **Freeze.** It is refused unless the development checks passed:
  - C1 reproduces the frozen Phase 7 development summaries;
  - the opposite-tap margins equal the Phase 4 cache bit for bit;
  - every stress truth creates violations beyond the nominal model.
- **Placements.** The evaluation is refused if the placement design changed since
  development.
- **Earlier phases.** Phase 4–7 outputs and caches are only read. The Phase 7 code path
  is reused unchanged: C1 reproduces Phase 7 exactly.
