# Mission 12 Stage A: decision-sufficient asset information under uncertain thermal ratings

**EXPLORATORY**, internally pre-specified; six SimBench LV networks, all examined in earlier phases. Not confirmatory.

| Document | Purpose |
|---|---|
| [`stage_a_protocol.md`](stage_a_protocol.md) | The protocol: as-executed revision 2.2 plus dated amendments A1–A5 |
| [`../../docs/research_note_asset_rating_information.md`](../../docs/research_note_asset_rating_information.md) | Results and interpretation (report sections I–XX) |
| [`DATA_ATTRIBUTION.md`](DATA_ATTRIBUTION.md) | SimBench / ODbL notice |

**The question:** when recorded static cable or transformer ratings may be wrong while the electrical model is right, which asset information does a safe PV-export cap decision need?

**Outcome (verdicts under U2, w = 0.2):**

| Hypothesis | Verdict |
|---|---|
| H1 | Descriptive. Cable-rating uncertainty is irrelevant on the transformer-limited networks. The ≥ 3 % relevance rule is met on semiurb4 only. |
| H2 | Analytic. Control D: in the simulated electrical model, a rating-only change leaves voltages and currents exactly unchanged. This is not a claim about thermal measurements or asset identification. |
| H3a | REJECTED, fragile. |
| H3b | REJECTED. |
| H3c | SUPPORTED. |
| H4 | SUPPORTED on semiurb4 and urban6 (urban6 fragile); none found within the top-10 pool on semiurb5. |
| H5 | SUPPORTED, fragile. |

**In one sentence:** a robust lower bound plus verification of the few most-loaded cables is the best policy found. The loading rank equals the VoI greedy, and nothing more sophisticated helped.

**Recommendation:** PIVOT, to verification under a misspecified uncertainty interval.

## Files

| Path | Role | Public |
|---|---|---|
| `ratings_core.py` | Decision tables, decisions, outcomes, uncertainty models, rankings, VoI greedy, route rule, recovery, write-once I/O, protocol pin (no power flow) | yes |
| `run_stage_a.py` | The runner: `tables`, `control-d` (the only AC solves), `control-e`, `pilot`, `evaluate`, `verdicts` | yes |
| `analyse_stage_a.py` | The read-out: `summarise` writes the summary JSON and six figures, `figure` regenerates one, `verify` checks the local data (no power flow). It imports `../export_envelope_shift/svgplot.py` | yes |
| `tests/` | Zero-flow tests, with synthetic round-valued fixtures only | yes |
| `figures/fig_a…fig_f*.svg` | Figures A–F (Produced Works; see `DATA_ATTRIBUTION.md`) | owner's decision |
| `stage_a_protocol.md`, `README.md`, `DATA_ATTRIBUTION.md` | Documentation | yes |
| `results/*.json`, `runs/*.npz` (including the `superseded_*` folders) | The SimBench-derived derivative database, about 27 MB | **no, local only** |

The board's zero-solve audits (before the protocol: decision relevance and co-blocking; after scoring: ranking orders and B9's overshoot) are in [`../../docs/provenance/mission12_board_audit/`](../../docs/provenance/mission12_board_audit/README.md).

## Reproducing

**Requirements:**
- `uv sync --all-extras`;
- the local, git-ignored caches: the Phase 5 nominal full-state cache (`outputs/sense_study/fullstate_cache/`) and the Phase 8 `line_local` cache (`outputs/robust_study/fullstate_cache/`);
- `control-d` needs pandapower and simbench (the `grid` extra).

**Tests** (zero power flows; an autouse guard forbids them):

```bash
python -m pytest -q analysis/asset_rating_information/tests
```

**Full regeneration.** It costs 2 new AC solves (Control D) and well under one CPU-hour. Every command writes once and refuses to overwrite, so start from empty `results/`, `runs/` and `figures/`.

```bash
python analysis/asset_rating_information/run_stage_a.py tables --network rural1
python analysis/asset_rating_information/run_stage_a.py control-d
python analysis/asset_rating_information/run_stage_a.py control-e --network rural1
python analysis/asset_rating_information/run_stage_a.py evaluate --network rural1 --model U2
python analysis/asset_rating_information/run_stage_a.py verdicts
python analysis/asset_rating_information/analyse_stage_a.py summarise
```

- Repeat `tables` and `control-e` for all six networks.
- Repeat `evaluate` for every protocol §5 combination:
  - rural1–3: U0, U2, U2w3, U3, U4, UT;
  - semiurb4, semiurb5, urban6: U0, U2, U2w3, U3, U4, U2P.
- `pilot --network semiurb5` writes only the timing ledger.

The public code is the final frozen revision. The decision tables and Controls D and E were produced by an earlier revision (see the manifest). The later fixes (A1–A3) touched only the scoring harness, so those stages are reproduced by the final code.

## Run manifest (the experiment as executed)

**Code revisions,** by sha256 prefix:

| Revision | `ratings_core.py` | `run_stage_a.py` | Produced | Status |
|---|---|---|---|---|
| T | `94025e20` | `e293f9e9` | `tables_*` (6), `control_d`, `control_e_*` (6), `pilot_timing` | **in use** (recorded as `tables_code_sha256` in every evaluation) |
| E0 | `adfc35b6` | `6eb898bc` | 6 evaluations (rural1 U0/U2; rural2, rural3, semiurb4, urban6 U2) | superseded by A1 (`superseded_A1/`) |
| E1 | `7133d45a` | `f586697e` | 16 evaluations (batch 1) | superseded by A2 (`superseded_A2/`) |
| E2 | `8527be1d` | `ebd917e5` | 30 evaluations (batch A) | superseded by A3 (`superseded_A3/`) |
| **E3** | **`8527be1d`** | **`4fd263fc`** | **all 36 evaluations and `verdicts.json`** | **final, frozen** |

**The read-out:**

| `analyse_stage_a.py` | Produced | Status |
|---|---|---|
| `7e33ac17` | first summary and figures | superseded by A5 (`results/superseded_R1/`) |
| **`0e21705e`** | **`stage_a_summary.json` (sha256 `1f6faed5…`) and figures A, B, C, E and F** | **final** (the summary records this hash, and `provenance.frozen_code_check.all_match = true`) |
| **`268388f3`** | **figure D only** (`fig_d_complementarity.svg`, `7324259c…`; wording from the recorded ratios), via `figure --name` | **final**. The publication freeze (AKK-90) added the completeness guard, `verify` and `figure`. The superseded figure D is in `results/superseded_R2/` |

The read-out also records the `svgplot.py` hash (`c0410f61`, Mission 11's plotting module, unchanged).

**Integrity of the local data:**
- `python analysis/asset_rating_information/analyse_stage_a.py verify` (read-only) checks the summary against its pinned sha256, and every input the summary records (36 evaluations, `verdicts.json`, the controls, and the 6 per-draw arrays the read-out uses) against its recorded hash. It also fails on an unexpected extra evaluation.
- The other 30 `runs/eval_*.npz` are not inputs to any reported number and are not pinned.
- A test (`test_analyse_stage_a.py`) runs the same check whenever any local artefact is present. It skips only in a checkout with none.
- `figure --name <file>` regenerates one figure, and refuses unless the recomputed summary equals the stored one.

**Protocol hashes recorded by the artefacts:**
- `16b2f2aa…`: revision 2.1 (tables, controls, pilot);
- `9fc9108c…`: revision 2.2, which is also the pinned as-executed text (E0);
- `a27cf5a7…`, `083b88af…` and `d1fb8c66…`: 2.2 plus A1, plus A1–A2, and plus A1–A3 (E1, E2 and E3).

Revision 2.2 changed hypothesis counts and the U4 reporting status only, not table construction or the controls. The as-executed text has been `9fc9108c…` since the first scored evaluation.

**Every reproduction check:**
- after A2: 16/16 overlapping combinations identical;
- after A3: 30/30 identical on every non-OB field.

**AC solves:** 2 (Control D, urban6 day 144, cap level index 0). The ceiling was 2,000.

**CPU:** final evaluations 1,362 CPU s; superseded evaluations 925 CPU s.
