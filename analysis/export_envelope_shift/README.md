# Mission 11 Stage A: PV correlation, learned voltage sensitivities and export-envelope safety

**EXPLORATORY**, internally pre-specified, with a single evaluation network.

| Document | Purpose |
|---|---|
| [`stage_a_protocol.md`](stage_a_protocol.md) | The protocol, frozen, with its drafting record and amendments A1–A3 |
| [`../../docs/research_note_export_envelope_reliability.md`](../../docs/research_note_export_envelope_reliability.md) | Results and interpretation |
| [`DATA_ATTRIBUTION.md`](DATA_ATTRIBUTION.md) | SimBench / ODbL notice |

**Outcome on rural3, as single-network verdicts:**
- **H1 Rejected.** The rejection rests on a ceiling: ridge is unsafe in every PV regime.
- **H2 Supported**, within the voltage-only conditional experiment.
- **H3 Inconclusive.**
- **H4 Decision equivalence.**

**Scope limits:**
- semiurb5 is NOT EVALUABLE (amendment A2). The effective evaluation sample is 10 near-limit conditions on one network.
- The primary decision is the voltage component of the envelope only. Thermal limits bind first in all six SimBench LV networks at the registered scale (F0). Under the full decision, no envelope was unsafe.
- The topology-structured baseline (B3) is safe in every regime.

**Recommendation:** PIVOT toward decision-sufficient thermal and rating information (not started).

## Files

| Path | Role | Public |
|---|---|---|
| `envelope_core.py` | Regime generators, estimators, bootstrap, statistics, ledger and write discipline (no power flow) | yes |
| `envelope_lp.py` | Envelope LPs, robust box and ellipsoid, oracle state machine, CERT (no power flow) | yes |
| `stage_a.py` | The runner: network build, AC solves, the stages and the ledger (pandapower and simbench) | yes |
| `analyse.py`, `svgplot.py` | Verdicts, summary and figures (no power flow, no pandapower import) | yes |
| `tests/` | 255 zero-flow tests, with synthetic round-valued fixtures only | yes |
| `figures/fig_a…fig_f*.svg` | Figures A–F (Produced Works; see `DATA_ATTRIBUTION.md`) | yes |
| `stage_a_protocol.md`, `README.md`, `DATA_ATTRIBUTION.md` | Documentation | yes |
| `results/*.json`, `runs/*.npz` | SimBench-derived artefacts, about 10.7 MB | **no, local only** |

The board's pre-scoring design audit and its zero-solve recomputations are in [`../../docs/provenance/mission11_board_audit/`](../../docs/provenance/mission11_board_audit/README.md).

## Reproducing

**Requirements:**
- `uv sync --all-extras` (the `grid` extra provides pandapower 3.5.6 and simbench 1.6.3);
- SciPy, which arrives with both lightgbm and pandapower.

**Tests** (zero power flows; the six tests that read local artefacts skip only when *every* artefact is absent, and fail on a partial set or on any file that no longer matches the summary's pinned sha256):

```bash
python -m pytest -q analysis/export_envelope_shift/tests
```

**Full regeneration** of the local artefacts:
- It costs about 5,600 new AC solves (the 6,140 non-audit ledger solves, less the 523 in the two abort records), a few minutes on one core.
- Every stage writes once and refuses to overwrite, so start from an empty `results/` and `runs/`.
- The ledger counts from the 106 board-audit solves.

```bash
python analysis/export_envelope_shift/stage_a.py physics --network semiurb5
python analysis/export_envelope_shift/stage_a.py select --network semiurb5
python analysis/export_envelope_shift/stage_a.py envelopes --network semiurb5
python analysis/export_envelope_shift/stage_a.py oracle --network semiurb5
python analysis/export_envelope_shift/stage_a.py controls --network semiurb5
python analysis/export_envelope_shift/stage_a.py ambiguity --network semiurb5
python analysis/export_envelope_shift/stage_a.py monotonicity --network semiurb5
python analysis/export_envelope_shift/stage_a.py select --network rural3
python analysis/export_envelope_shift/stage_a.py physics --network rural3
python analysis/export_envelope_shift/stage_a.py envelopes --network rural3
python analysis/export_envelope_shift/stage_a.py oracle --network rural3
python analysis/export_envelope_shift/stage_a.py controls --network rural3
python analysis/export_envelope_shift/stage_a.py ambiguity --network rural3
python analysis/export_envelope_shift/stage_a.py monotonicity --network rural3
python analysis/export_envelope_shift/analyse.py summary
python analysis/export_envelope_shift/analyse.py figures
```

The public code is the final frozen revision. semiurb5's descriptive artefacts were produced by earlier revisions (see the manifest), so regenerating them differs in documented ways:
- the corrected `predicted_corner_vm` read-out;
- the far-candidate day rule (A1), which is already the code's behaviour.

The rural3 evaluation is reproduced by the frozen revision directly.

## Run manifest (the experiment as executed)

**The code revisions,** by the sha256 prefix of each file:

| Revision | `stage_a.py` | `envelope_core.py` | `envelope_lp.py` | Notes |
|---|---|---|---|---|
| R0 | not recorded | `7d281c1d` | `ccc715a7` | AKK-61 before its zero-solve select fix. It differs from R1 only in select's far-candidate rule and the abort-record payload |
| R1 | `9efb65e1` | `7d281c1d` | `ccc715a7` | Frozen selection code |
| R2 | `5c2e8881` | `7d281c1d` | `ccc715a7` | Adds envelopes and oracle |
| R3 | `274c41d6` | `f6d49f51` | `ccc715a7` | Read-out fix and protocol re-pin (first freeze) |
| **R4** | **`319020ec`** | **`442a4d0f`** | **`ccc715a7`** | **Final freeze:** the A3 resume path and SIGTERM handler, plus the protocol re-pin. No method code changed |

`envelope_lp.py` has been `ccc715a7` for every counted solve. Its only earlier change, the B4 cut budget (revision 2.2), was made before any solve.

**The protocol hash recorded by each artefact:**
- `1848a279…` — revision 2.2, which is also the as-executed text;
- `7fa20b54…` — 2.2 plus A1–A2;
- `610d144d…` — 2.2 plus A1–A3, the current file.

Nothing above the amendments changed: the executed-text hash is `1848a279…` throughout.

**Every counted solve:**

| Network | Artefact | Solves | Protocol | Code | Paperclip |
|---|---|---|---|---|---|
| — | Board design audits (`docs/provenance/mission11_board_audit/`) | 106 | — | audit scripts | — |
| semiurb5 | `physics_semiurb5_{P1,P2,P3,L0}` | 1,920 | `1848a279` | R0 | AKK-61 |
| semiurb5 | `abort_select_semiurb5_43` | 43 | — | R0 | AKK-61 |
| semiurb5 | `selection_semiurb5` | 87 | `1848a279` | R1 | AKK-62 |
| semiurb5 | `envelopes_semiurb5` (B1, B2m and B3 `predicted_corner_vm` carry the read-out defect; descriptive only) | 129 | `1848a279` | R2 | AKK-63 |
| semiurb5 | `oracle_semiurb5` | 28 | `1848a279` | R2 | AKK-63 |
| semiurb5 | `controls`, `ambiguity`, `monotonicity` | 25 + 32 + 12 | `7fa20b54` | R3 | AKK-64 |
| rural3 | `selection_rural3` | 95 | `1848a279` | R1 | AKK-63 |
| rural3 | `physics_rural3_{P1,P2,P3}` (P1 includes the 384-step extension) | 864 + 480 + 480 | `7fa20b54` | R3 | AKK-65 |
| rural3 | `abort_physics_rural3_L0_sigterm` (board record, upper bound for the SIGTERM-killed attempt; amendment A3) | 480 | — | R3 | AKK-65 |
| rural3 | `physics_rural3_L0` (`--resume`; P1–P3 inputs re-verified bit-exact) | 480 | `610d144d` | R4 | AKK-66 |
| rural3 | `envelopes`, `oracle`, `controls`, `ambiguity`, `monotonicity` | 527 + 140 + 139 + 159 + 20 | `610d144d` | R4 | AKK-66 |
| **Total** | | **6,246** (ceiling 8,000) | | | |

**The analysis:**
- `results/stage_a_summary.json` is written by `analyse.py` and `svgplot.py` at the hashes recorded in its `provenance` block.
- `provenance.inputs_sha256` pins all 24 input artefacts.
- The summary was first written in AKK-67, then regenerated after the post-experiment QA (AKK-68, PASS WITH LIMITATIONS) in AKK-69. That regeneration changed only figure B's interval n, figure F's layout, and the provenance and disagreement notes; no numeric result changed.
- It was regenerated once more in AKK-70 and AKK-71, when the figures gained the ODbL footer and the header-layout fix. Only the recorded `svgplot.py` hash changed.
- **Known comment inaccuracy in frozen code:** `stage_a.py`'s comment beside its protocol check says "amendments A1-A2", but the pinned hash is A1–A3. It is left as is, because editing the frozen file would change its pinned sha256.
- The board reproduced the summary and every figure byte-identically from copied artefacts in a clean copy.

## Protective `.gitignore` entries (proposed; not applied by the agents — apply them in the same commit)

```
analysis/export_envelope_shift/results/
analysis/export_envelope_shift/runs/
```
