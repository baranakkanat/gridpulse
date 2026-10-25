# Data attribution and licence notice: Mission 11 Stage A

**Contains information from [SimBench](https://simbench.de), which is made available here under the [Open Database License (ODbL 1.0)](https://opendatacommons.org/licenses/odbl/1-0/).** Any rights in individual contents of the SimBench database are licensed under the [Database Contents License (DbCL 1.0)](https://opendatacommons.org/licenses/dbcl/1-0/).

- **Copyright of the SimBench database:** University of Kassel, TU Dortmund, RWTH Aachen University and Fraunhofer IEE Kassel, and individual contributors (as stated in the `simbench` 1.6.3 package licence).
- **Reference:** S. Meinecke et al., "SimBench — A Benchmark Dataset of Electric Power Systems to Compare Innovative Solutions Based on Power Flow Analysis", *Energies* 13(12), 3290 (2020), doi:10.3390/en13123290. The reference is given for scholarly attribution; the licence itself does not require it.

This file is the ODbL notice for the Mission 11 files in this repository. It sits in the study directory so that readers find it. The registered protocol cannot carry the notice itself, because its sha256 is pinned by the code that ran the experiment.

---

## 1. What in this repository derives from SimBench

| Files | Classification under ODbL 1.0 | Obligation when publicly used |
|---|---|---|
| `stage_a_protocol.md` (§2, §3, §17, amendments), `../../docs/research_note_export_envelope_reliability.md`, `../../docs/provenance/mission11_board_audit/README.md` | **Produced Works** (text): summary statistics computed from the networks and profiles, such as PV correlations, voltage and thermal margins, loadings, and bus and PV-unit counts | ODbL §4.3 notice: **this file** |
| `figures/fig_a…fig_f*.svg` | **Produced Works** (images), computed from the derived arrays described in row 4 | ODbL §4.3 notice, embedded in each figure and given here; plus §4.4 and §4.6, see §2 below |
| `*.py`, `tests/*.py`, the audit scripts in `../../docs/provenance/mission11_board_audit/` | **Independently authored source code.** Not part of the SimBench Contents: network data are read at run time from the installed `simbench` package, and the test fixtures are synthetic round values | None under ODbL. The code's own licence is GridPulse's, and none has been chosen (see the repository README) |
| `results/*.json`, `runs/*.npz` (**not in this repository**) | **Derivative Database** (conservative reading): full-year PV and load series transformed from SimBench profiles, and AC power-flow results on SimBench networks | Held locally and not conveyed. See §2 |

Individual facts, such as "rural3 has 118 customer buses", are not covered by copyright (DbCL 1.0 cl. 2.4). Repeated insubstantial extraction is limited by ODbL §6.2. The documents above are nevertheless treated as Produced Works, the conservative reading, and carry this notice.

---

## 2. Derivative-database obligations triggered by publishing the figures

ODbL §4.4 states that a Derivative Database is Publicly Used if a Produced Work created from it is Publicly Used. Publishing figures A–F, which are computed from the local derived arrays, therefore triggers §4.4 and §4.6 for those arrays, even though the arrays themselves are not published. **Attribution alone does not discharge these obligations.**

How this repository meets them:
- **§4.4 (share-alike).** The Mission 11 derived arrays (`analysis/export_envelope_shift/results/`, `runs/`), to the extent they are a Derivative Database of SimBench, are made available under the **ODbL 1.0**, with their individual contents under the **DbCL 1.0**. They are not licensed under any other terms.
- **§4.6 (access).** Instead of the entire Derivative Database (option a), this repository offers option b: **the method of making the alterations**. It is published free of charge in machine-readable form. It is the method as frozen at the end of the experiment (revision R4 in `README.md`); revisions R0–R3, which produced the semiurb5 artefacts, are not published:
  - `stage_a.py` (network build, regime generators, physics, selection, envelopes, oracle and controls);
  - `envelope_core.py` and `envelope_lp.py`;
  - `stage_a_protocol.md` (seeds, regimes, splits and amendments A1–A3).
  - Running the commands listed in `README.md` against SimBench 1.6.3 regenerates the rural3 evaluation arrays. The semiurb5 descriptive arrays regenerate with the two documented differences recorded in `README.md`.
  - Determinism is conditional on the recorded environment: SimBench 1.6.3, pandapower 3.5.6, numpy 2.4.6 and SciPy 1.18.1 (see `provenance.versions` in the summary). Regenerated files record the current protocol hash, not the as-executed one, so regeneration is numerically faithful but not byte-identical.
  - `README.md` records which code revision produced each artefact.
- **§4.3 (notice for Produced Works).** This file, the notice line near the top of the research note and of the audit README, and a notice embedded in each figure.

**What is not done:** the derived arrays themselves are not published. Whether to publish them, or to offer them on request, is the repository owner's decision. If they are ever conveyed, §4.2 applies: include the ODbL text or its URI, and keep this notice intact.

---

## 3. What remains unresolved (the owner's decisions, not settled here)

1. **Whether the derived arrays are a Derivative Database at all,** or only the working material of Produced Works. This file takes the conservative reading. The obligations under either reading are met by §2.
2. **Earlier GridPulse documents.** Documents committed before Mission 11 (for example the Phase 3–9 results documents, and the Q1 addendum results committed in `1bba4e8`) also contain SimBench-derived results. They do not yet carry a §4.3 notice. Applying the same notice repository-wide is a separate decision.
3. **The software licence.** GridPulse's own code has no licence. ODbL places no obligation on it, but readers have no stated reuse rights until the owner chooses a licence.
4. **This is not legal advice.** It is an engineering reading of the licence texts linked above, made on 2026-10-25.
