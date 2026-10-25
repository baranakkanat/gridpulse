# Mission 12 Stage A: board zero-solve audit (before the protocol)

**Data attribution:** contains information from [SimBench](https://simbench.de), which is made available here under the [Open Database License (ODbL 1.0)](https://opendatacommons.org/licenses/odbl/1-0/). See [`analysis/asset_rating_information/DATA_ATTRIBUTION.md`](../../../analysis/asset_rating_information/DATA_ATTRIBUTION.md).

These scripts were run by the board on 2026-10-25, **with zero new AC solves**. They read the local, git-ignored Phase 5 nominal full-state cache (`outputs/sense_study/fullstate_cache/`), the SimBench profiles and the network records.
- **Kept verbatim** except for the path lines marked `# edited`.
- **Lint:** excluded, like the other archived scripts under `docs/provenance`.
- **The outputs below** are aggregates. No SimBench parameter values are reproduced.

## `audit_relevance.py`
For every daylight quarter-hour of days 35–364, it finds the largest admissible uniform PV cap (11 levels) under the following ratings, and records what blocks the next level:
- recorded ratings;
- cable lower bounds of 1 − w (w = 0.2, 0.3), with the transformer known;
- the transformer lowered as well.

| Network | Daylight steps | Curtailed steps (recorded) | What blocks the next level | Lines ever > 100 % / > 70 % at no cap | Distinct blocking lines (recorded / robust w = 0.2, 0.3) |
|---|---|---|---|---|---|
| rural1 | 13,479 | 1,205 | transformer 1,205 | 0 / 0 | 0 / 0, 0 |
| rural2 | 14,152 | 1,012 | transformer 1,012 | 0 / 3 | 0 / 0, 3 |
| rural3 | 14,152 | 1,051 | transformer 850; voltage + transformer 201 | 0 / 14 | 0 / 3, 4 |
| semiurb4 | 12,517 | 1,299 | lines 1,299 | 6 / 6 | 6 / 6, 6 |
| semiurb5 | 14,216 | 1,195 | lines 1,194; voltage + lines 1 | 22 / 30 | 16 / 16, 22 |
| urban6 | 14,216 | 867 | lines 867 | 11 / 12 | 11 / 12, 11 |

**Export in MWh** (days 35–364, daylight). "Robust lines" lowers the cable ratings only; "robust all" lowers the transformer too.

| Network | No cap | Recorded | Robust lines w = 0.2 | Robust lines w = 0.3 | Robust all w = 0.2 | Robust all w = 0.3 |
|---|---|---|---|---|---|---|
| rural1 | 291.261 | 278.210 | 278.210 | 278.210 | 260.659 | 241.553 |
| rural2 | 432.976 | 416.831 | 416.831 | 416.735 | 387.316 | 377.721 |
| rural3 | 690.347 | 666.335 | 666.230 | 662.282 | 618.528 | 595.209 |
| semiurb4 | 417.431 | 398.170 | 360.692 | 350.773 | 360.692 | 350.773 |
| semiurb5 | 812.819 | 782.157 | 717.072 | 694.124 | 717.072 | 694.124 |
| urban6 | 632.542 | 614.478 | 569.875 | 548.326 | 569.875 | 548.326 |

## `audit_coblock.py`
For the cable-limited networks, the four most often blocking lines under recorded ratings are always **series segments on one root path, with an identical `std_type` and an identical recorded rating**:

| Network | Lines | Arrangement |
|---|---|---|
| semiurb4 | 38, 37, 36, 35 | One trunk, depths 6, 5, 4, 3 |
| semiurb5 | 26, 58, 74, 62 | Depths 2, 1, 14, 13 on one root path |
| urban6 | 33, 4, 5, 55 | One trunk, depths 4, 3, 2, 1 |

## `audit_rankings.py` (after scoring, 2026-10-25)
Usage: `python audit_rankings.py analysis/asset_rating_information NETWORK:MODEL ...`.

The script rebuilds `cmd_evaluate`'s planning-period inputs with the frozen evaluation code (amendment A3). It prints the unit orders of B6 (loading), B7 (binding), B8 (VoI greedy) and B8P (pair greedy), and B8's expected gain per step. It reads only the local decision tables and writes nothing.

Why it exists: the scored records give recoveries, not orders. The question is whether B8 agrees with B6 because of what it measures, or only because of its tie rule (the lower unit index wins when every gain is 0).

| Network (model) | Pool | B6 = B7 = B8 order (to k_max) | B8 zero-gain steps | B8's per-step expected gains, MWh |
|---|---|---|---|---|
| semiurb4 (U2) | 6 | yes | none | 0.57, 4.82, 2.02, 0.84, 0.75, 1.00 |
| semiurb4 (U2w3) | 6 | yes | none | 4.09, 1.10, 0.42, 0.58, 1.64, 2.26 |
| semiurb4 (U2′) | 6 | yes | none | 0.58, 4.59, 1.90, 0.82, 0.72, 1.00 |
| semiurb5 (U2) | 22 | yes | none | 0.07, 1.87, 0.13, 0.05, 0.06, 0.05, 0.14, 0.05 |
| semiurb5 (U2w3) | 30 | yes | none | 0.29, 7.82, 0.04, 0.02, 0.03, 0.02, 0.02, 0.01 |
| urban6 (U2) | 12 | yes | none | 0.11, 0.09, 0.10, 1.67, 3.13, 0.81, 0.19, 0.57 |
| urban6 (U2w3) | 12 | yes | none | 0.69, 0.56, 0.37, 5.00, 1.72, 0.30, 0.06, 0.29 |
| urban6 (U2′) | 12 | yes | none | 0.11, 0.10, 0.10, 1.73, 2.95, 0.90, 0.20, 0.53 |
| rural3 (U2, transformer-limited) | 7 | **no** (B8 follows its tie rule) | 1, 2, 3, 4, 6 | 0, 0, 0, 0, 0.05, 0 |

Reading:
- On every cable-limited combination, the VoI greedy reproduces the simple loading order **with a strictly positive gain at every step**. The agreement is informative, not an artefact of ties.
- The gains are not diminishing: urban6's 4th and 5th cables are worth roughly 15–35 times each of its first three. This is the series co-blocking complementarity that makes the set function non-submodular.
- On rural3, single-cable VoI is 0, and B8's order is the tie rule's. There, no ranking matters, because the transformer decides.

B8P's order differs from B6's only by adjacent swaps. At k_max it ends on B6's segment set on urban6 (U2), and on B6's eight plus one overshoot segment (column 16) on semiurb5 (U2).

## `audit_b9_stop.py` (after scoring, 2026-10-25)
Usage: `python audit_b9_stop.py analysis/asset_rating_information NETWORK:MODEL`.

The script runs B9-static's route rule directly on the P table at budgets 1 to 8 and prints the realised unit counts. It reads only the local decision tables and writes nothing.

Why it exists: on semiurb5, B9 scores at exactly 2 units, with R = 0.540, at every k from 2 to 8 in all 200 draws. Meanwhile B6 keeps gaining (0.540 → 0.626).

| Network (U2) | Realised units when asked for budget 1 … 8 |
|---|---|
| semiurb5 | 2, 2, **14**, 14, 14, 14, 14, 14 |
| urban6 | 4, 4, 4, 4, 5, 8, 8, 8 |

Reading:
- semiurb5's second top blocker sits deep on a long feeder. B9's step (2), "verify every candidate segment on its root path that blocks in ≥ 10 % of its blocking steps", verifies 12 segments at once (2 → 14).
- §7's budget-matching rule scores a policy at its largest realised count ≤ k, so for every k ≤ 8 B9 is scored at its 2-unit state.
- That is the pre-registered behaviour, not a defect. It is the granularity cost of path-shaped verification units on deep feeders, and it is why Control I finds that "the structural rule" does not suffice.
