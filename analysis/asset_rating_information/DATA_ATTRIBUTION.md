# Data attribution and licence notice: Mission 12 Stage A

**Contains information from [SimBench](https://simbench.de), which is made available here under the [Open Database License (ODbL 1.0)](https://opendatacommons.org/licenses/odbl/1-0/).** Any rights in individual contents of the SimBench database are licensed under the [Database Contents License (DbCL 1.0)](https://opendatacommons.org/licenses/dbcl/1-0/).

- **Copyright of the SimBench database:** University of Kassel, TU Dortmund, RWTH Aachen University and Fraunhofer IEE Kassel, and individual contributors (as stated in the `simbench` 1.6.3 package licence).
- **Reference:** S. Meinecke et al., "SimBench — A Benchmark Dataset of Electric Power Systems to Compare Innovative Solutions Based on Power Flow Analysis", *Energies* 13(12), 3290 (2020), doi:10.3390/en13123290. The reference is given for scholarly attribution; the licence itself does not require it.

This file is the ODbL notice for the Mission 12 files. It follows the approach of [`analysis/export_envelope_shift/DATA_ATTRIBUTION.md`](../export_envelope_shift/DATA_ATTRIBUTION.md); see that file for the licence reasoning, which is not repeated here.

## What in this study derives from SimBench

| Files | Classification under ODbL 1.0 | Obligation when publicly used |
|---|---|---|
| `stage_a_protocol.md`, the research note, `../../docs/provenance/mission12_board_audit/README.md` | **Produced Works** (text): summary statistics such as loadings, curtailed-step counts, export totals and pool sizes | §4.3 notice: **this file** |
| `figures/*.svg` | **Produced Works** (images), computed from the derived arrays below | §4.3 notice, embedded in each figure and given here; §4.4 and §4.6, below |
| `*.py`, `tests/*.py`, the audit scripts | **Independently authored source code.** Network data are read at run time, and the test fixtures are synthetic round values | None under ODbL. GridPulse's own code has no chosen licence |
| `results/`, `runs/` (**not in the repository**) | **Derivative Database** (conservative reading): decision tables and evaluation results derived from SimBench-based power-flow states. These include the Phase 5 and Phase 8 caches they are built from, which stay in the git-ignored `outputs/` | Held locally, not conveyed |

**§4.4 and §4.6.**
- To the extent that the Mission 12 derived arrays are a Derivative Database of SimBench, they are made available under **ODbL 1.0**, with their contents under **DbCL 1.0**.
- The method of making them (ODbL §4.6 option b) is the published code (`ratings_core.py`, `run_stage_a.py`), together with `stage_a_protocol.md` (seeds, uncertainty models, splits).
- The figures and the summary are produced from those arrays by `analyse_stage_a.py`, using Mission 11's `../export_envelope_shift/svgplot.py`, which is also published.
- It also includes GridPulse's own Phase 5 and Phase 8 state builders (`src/gridpulse/fullstate.py`, `src/gridpulse/stress.py`), which regenerate the underlying caches from SimBench 1.6.3.
- **Determinism is conditional on the recorded environment** (SimBench 1.6.3, pandapower 3.5.6, and the numpy and SciPy versions recorded in the artefacts).

**Unresolved (the owner's decisions):**
- whether to publish the figures at all;
- whether the derived arrays are a Derivative Database or only working material (the conservative reading is taken);
- the GridPulse software licence;
- this is not legal advice.
