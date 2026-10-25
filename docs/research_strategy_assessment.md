# GridPulse research strategy assessment: novelty, research gaps and direction

**Status:** an independent strategy assessment, written 2026-10-24 after Mission 10.
- No experiment was run for it.
- No result, protocol or registered hypothesis was changed.
- The literature evidence was gathered by targeted, non-systematic searches. Every reference records whether its **full text** or only its **abstract** was read.
- The adversarial reviews in Part VI (Paperclip AKK-56 and AKK-57) are automated AI reviews by the project's own sandboxed agents. They are not human peer review.
- **Revision note.** The first draft preferred a different direction (decision-sufficient network information). Both adversarial reviews returned CHANGES REQUIRED. After checking their arguments, the board corrected the factual errors they found and **changed the preferred direction** (Parts VI–VII explain why). The revised recommendation was not re-reviewed.

---

## Part I — GridPulse: where we stand

### I.1 What has actually been established

| Kind of evidence | What it shows | Where |
|---|---|---|
| **Implemented and tested methods** | Forecasting baselines and LightGBM. SimBench LV AC simulation. PV-cap and curtailment policies, including static, robust, scenario, selective-with-deferral and online-calibrated policies. A measurement chain (noise, missing data, delay). WLS state estimation. Residual (offset-free) correction. Constraint-specific reserves. Calibrated residual detectors (C2-ref). Phase-frame sensitivity predictors (M1, H3). | `src/gridpulse/`, `analysis/` |
| **Registered results** (single frozen evaluations) | Phases 4–8 on 5–6 SimBench LV networks; Phase 9's detectability rules. | `docs/phase*_results.md` |
| **Registered failures** | Phase 7 H1 (cost); Phase 8 H1 and H2; Phase 9 R3, R5 and R7, R1/R2 at σ = 0.005 outside reversing cables, and the W8/W9 hypotheses. They stay failed. | as above |
| **Exploratory findings** | The Phase 9 follow-up (calibration), the pilot, and Mission 10. | `analysis/phase9_followup/`, `analysis/calibrated_detection_pilot/` |
| **Mathematical derivations** | Standard results only: the fixed-current drop sensitivity, sequence ↔ phase mapping, and contrast variance formulas. **No new theorem.** | M10 protocol §3 |
| **AI-assisted reviews** | Every QA verdict in this project is by AI agents. **No independent human validation exists.** | Paperclip AKK-* |
| **Independently validated results** | **None** in the academic sense: no external replication, no field data, no peer review. | — |

### I.2 A recurring physical pattern across Phases 4–10 (the most important finding)

Read across phases, GridPulse's results sort model errors into three groups:

1. **Common-mode errors (transformer tap, MV voltage)**
   - They are *identifiable* and *decision-relevant*.
   - Phase 7: the busbar residual matched the true tap or MV offset within 1e-4 pu, and residual correction met the violation target in 15 of 15 model-error cases. That cost 1.27× the binary baseline's correct-model curtailment (the registered H1 failure) and +41 % curtailment under model mismatch.
   - Phase 4: model errors broke model-tuned rules in about half of the cells, and measured feedback restored reliability (46–49 of 50 cells) under full observation.
2. **Local impedance errors (a wrong cable section)**
   - They are *weakly identifiable* and, so far, *decision-irrelevant*. That "so far" means a lightly loaded scenario.
   - Phase 9 and Mission 10: at most a 5.8e-4 pu day–night contrast from a 1.5× resistance error; about 5 of 203 sections detectable at σ 0.005 and D 60, even with every customer metered; no loading or voltage decision changed.
3. **Thermal-rating errors**
   - They are *decision-critical*, and they are unidentifiable from voltage and flow data **when the rating is mis-recorded independently of the conductor**.
   - Phase 8's README summary says: "No attainable policy handles a cable whose recorded thermal rating is wrong." Phase 8's registered truth, however, **bundled** R × 1.5 with rating × 0.8 (`docs/phase8_results.md`), and it failed in 3 of 5 networks. Phase 8 tested no rating-only error.
   - A wrong cable *type* changes R (strongly), X (slightly) and the rating together, so voltage data carry *partial* information about it.
   - Mission 10, Control B: a rating-only record error changes every voltage and current by exactly 0. That is a simulator tautology, since `max_i_ka` is not in the power-flow equations.
   - **Caveat (AKK-56).** Signal strength and thermal criticality are both driven by branch current (signal ρ 0.79 with R1 × mean current). Under constraint-proximate loading, the identifiable and decision-relevant sets may overlap rather than separate. The clean three-way split above may partly be a light-load artefact.

**Further results that matter for any "act or defer" direction:**
- **Phase 3 deferral.** H4a was *not supported*: 0.028 against 0.009 violations per active step, a difference of 0.019 with interval [−0.014, 0.047], and the direction reversed in the one month containing both day types. That is an underpowered null, not a demonstrated failure. The selective policy's safety gain held only by construction: the fallback caps at least as deeply.
- **Phase 5 measurement value.** One or two smart-meter voltages recovered remote-overvoltage reliability (12–14 of 15 cases). About half of that apparent recovery reflects noise-driven conservatism: with exact readings, two sensors reached 9 of 15. Decision-aware placement did no better than simple rules under noise.

### I.3 Verification of the Mission 10 claims, with the precise scope of each

| Claim | Verified scope and caveat |
|---|---|
| 1,166 new AC solves, 0 failures | Correct: E0 960, E1 180, E2 26. |
| 203 sections against 144 | 203 candidate sections. 59 feed no customer and carry no current, leaving 144 with downstream customers. "5 of 203 detectable" equals 5 of 144. The 59 have no signal *and* no consequence. |
| 906 or 907 buses | The instantiated pandapower model has 907 buses: 906 LV plus the MV bus. "906-bus" is the benchmark's LV count. |
| 0 false negatives | 0 in **150** eligible (section, operating point) pairs, from **18** sections × 12 operating points, E-R(1.5) only. The sample is stratified and not independent. The nominal rule-of-three figure of 2 % is not a confidence bound for the feeder. The criterion's τ/2 band is deliberately loose. |
| 1,917 pairs, 98.7 % within 10 % (M1) | Correct. All 11 pairs outside 25 % are **section 22, OP 8, phase c**, where the self and mutual terms cancel: a cancellation failure. Pilot section 15 has 13 pairs at 10–20.4 %. |
| H3: 93.9 % within 10 %, 0 sign errors | Correct, but **H3 is less reliable in magnitude**: 26 pairs outside 25 %, worst 117 %, contrast bridge 6.4 %. Its section ranking matches M1's (Spearman 0.9998 over 144). |
| G: 218 sign errors; H1: 280 | Correct, on 1,917 pairs. |
| Reactance and length | Tested on **2 sections × 2 operating points only**. G4 was not rankable there. "VALID" means valid on the testable criteria only. |
| Modelling assumptions | Neutral and earth merged (no explicit four-wire neutral). Constant-power single-phase loads. One synthetic 10-day June scenario of SimBench profiles. PV at unity power factor. No voltage regulation. The topology is not independent of the pilot. **Conductor temperature is not modelled** (AKK-56): AC resistance rises about 0.4 %/K, so effective R swings with loading by an amount comparable to a one-size type error, and in the same diurnal shape the day–night contrast exploits. |
| "Undetectable" | **Not impossibility.** It means C2-ref power < 0.8 at a stated σ, D and placement, under stipulated noise. "Physically weak" means the oracle matched-filter SNR < 1.96 even at σ 0.002, D 120. Longer horizons or better sensors could detect more, but diurnal systematic bias grows relatively more harmful with D. |
| No decision changed | True **in a lightly loaded scenario**: maximum loading 19.8 %, voltages ≤ 1.075 pu. This shows *nothing* about constraint-proximate operation, and is the scenario's property as much as the error's. |
| Detectability for D > 10 days | Monte Carlo extrapolation by resampling 10 synthetic days. The matched-filter column is an analytic expectation. No direct multi-week physics. |

**Bottom line for Part I.** GridPulse has a credible, carefully documented *simulation* toolkit and a sequence of mostly *negative or bounded* exploratory findings. Its most valuable asset is the decision layer (Phases 3–8), together with the cross-phase pattern in I.2, not the cable-detection pipeline.

---

## Part II — Is our current research original?

**Short answer: the cable-error detectability work is not original enough to stand as a research contribution on its own.**
- Its parts are established.
- Its one interesting empirical result is a benchmark finding, not a new method: positive-sequence screens give wrong signs on an unbalanced LV feeder.
- Its strongest finding is the *mismatch* between what voltage data can identify and what decisions depend on, and it is a by-product.

**Already known (the prior art behind each item is in Part III):**
- **The linear voltage-drop relation** ΔV ≈ −ΔZ·I, its phase-frame form, and sensitivity-based screening are textbook.
- **Mutual coupling matters.** Multiphase linearisations exist precisely because positive-sequence models fail on unbalanced feeders.
- **Weak, low-current or unexcited segments are hard or impossible to identify.** Vanin et al. 2023 show line lengths are not identifiable even though voltages fit within 0.001 pu. Rosato et al. 2026 show only summed impedance of unexcited chains is identifiable, and that 0.5 % noise derails identification. Ardakanian et al. 2019 show voltage data are rank-deficient.
- **Smart-meter estimation of three-phase sensitivities exists**, including phase coupling: Fang et al. 2024; Kumarawadu et al. 2025.
- **Robust DER export envelopes under impedance uncertainty exist:** Liu, Braslavsky & Mahdavi 2024; Liu & Ma 2023. So do robust voltage control with uncertain line parameters (Christakou et al. 2018) and feedback optimisation that tolerates model mismatch (Ortmann et al. 2020).
- **Calibrated residual tests under serial dependence** use established tools: HAC, block bootstrap, conformal.

**What *might* be different, and is not yet supported:**
1. A test, *in decision units*, of whether the network-model ambiguity that remains after smart-meter inference changes DER export decisions. Rosato et al. build the data-compatible set but stop before decisions. Liu et al. make decisions robust to an *assumed* set but never ask what the data leave unresolved.
2. Treating **asset-record verification** (cable type, length, thermal rating) as an information source that competes with sensors and longer observation on a common regret scale. None of the four reviews found it.
3. GridPulse's cross-phase observation that a decision-critical parameter (the thermal rating, *when mis-recorded independently of the conductor*) is invisible to voltage data, while the identifiable ones (impedances) were decision-irrelevant **in a lightly loaded scenario**. As AKK-56 notes, this may weaken under constraint-proximate loading.

**Not novel:**
- M1 and H3 as methods. H3 is a standard phase-frame linearised current-injection sensitivity evaluated at flat voltages, under another name.
- The C2-ref detector as statistics.
- The idea that "you only need to identify what the decision needs": that is identification-for-control (Gevers 2005; Hjalmarsson 2005; Bombois et al. 2006) and partial identification for decisions (Manski).
- Value-of-information analysis: Howard 1966; structural-health-monitoring value of information (Straub 2014; Thöns 2018).

**Genuinely unresolved, in a targeted search:**
- Joining *data-compatible network-model sets* to *decision equivalence and regret* for LV DER decisions.
- The value of record verification against measurement.
- What learning adds when the guarantee must hold against **network-parameter error**, not just forecast error. The closest work, distributionally robust conformal screening for voltage control (Bouchkati et al. 2026), calibrates on simulation-to-reality error and has no measurement-request action.
- **Decision-induced extrapolation** of data-driven LV envelopes. The envelope asks for injection magnitudes and per-customer allocations that collinear historical PV data never excited. The pieces are known — collinearity (Valverde 2018), optimisers exploiting learned-model errors (Trabucco 2021) — but in a search-level check they had not been joined for envelopes. This became the preferred direction after review (Part VII).

---

## Part III — Closest existing scientific work

Access levels: **FULL** = methods and results read (arXiv HTML); **ABS** = abstract only; **META** = bibliographic data only. "Inference" marks our reading. The searches were targeted, not systematic.

| # | Work | Access | What it establishes | What it does not do |
|---|---|---|---|---|
| 1 | Vanin, Geth, D'hulst, Van Hertem, "Combined unbalanced distribution system state and line impedance matrix estimation", *IJEPES* 151 (2023) 109155. [doi:10.1016/j.ijepes.2023.109155](https://doi.org/10.1016/j.ijepes.2023.109155), [arXiv:2209.10938](https://arxiv.org/abs/2209.10938) | FULL | Multi-period unbalanced state estimation with impedances or lengths as variables, on the IEEE European LV feeder (reduced to 109 buses) and a real Flemish feeder. Lengths are not identifiable, yet voltages fit within 0.001 pu. X is harder than R. They needed loads scaled ×3 for impedance-matrix estimation. Kron 3×3. | No decision evaluation. Topology and phases are known. Leaf-only metering is degenerate. |
| 2 | Rosato, Nespoli, Medici, "Underdetermined Library-aided Impedance Estimation with Terminal Smart Meter Data", [arXiv:2603.23222](https://arxiv.org/abs/2603.23222) (2026) | FULL | Builds an explicit **set of data-compatible impedance assignments**: an LP minimum worst-case error with 5 % slack, a Dikin walk, and a cable-library prior. Names the ambiguity sources: unexcited chains, constant power factor, noise. 0.5 % voltage noise derails identification. | Single-phase LinDistFlow. **No operational decision is evaluated.** |
| 3 | Fang, Pengwah, Andrew, Razzaghi, Muñoz, "Three-phase voltage sensitivity estimation and its application to topology identification in LV distribution networks", *IJEPES* 158 (2024) 109949. [doi:10.1016/j.ijepes.2024.109949](https://doi.org/10.1016/j.ijepes.2024.109949) | ABS | Estimates three-phase voltage sensitivities from smart meters, about 4× better than the prior state of the art, then uses them for topology identification. | Decisions not studied. Neutral treatment not verified. |
| 4 | Kumarawadu, Azim, Khorasany, Razzaghi, Heidari, "Smart meter data-driven dynamic operating envelopes for DERs", *Applied Energy* 384 (2025) 125469. [doi:10.1016/j.apenergy.2025.125469](https://doi.org/10.1016/j.apenergy.2025.125469) | ABS | Estimates sensitivities, then impedances with phase coupling, from smart meters, and computes operating envelopes on an unbalanced four-wire LV network. Claims robustness to unknown topology. | The abstract does not say whether estimation uncertainty is propagated into the envelopes. |
| 5 | Liu, Braslavsky, Mahdavi, "Linear OPF-based robust dynamic operating envelopes with uncertainties in unbalanced distribution networks", *JMPSCE* 12(4) (2024) 1320–1326. [doi:10.35833/MPCE.2023.000653](https://doi.org/10.35833/MPCE.2023.000653), [arXiv:2302.13472](https://arxiv.org/abs/2302.13472) | FULL (Table II checked by the board on arXiv v5) | Robust envelopes over **assumed** impedance norm-balls (∞-norm, γ = 5 %, 10 %). On a 33-bus, 87-customer Australian network the total export envelope falls from 78.7 kW to 49.2 kW (γ = 5 %) and 36.3 kW (γ = 10 %), i.e. −37 % and −54 %. 20 % load uncertainty gives 75.4 kW (−4 %). | The sets are not derived from data, no regret or violation check is made, and topology and phases are fixed. |
| 6 | Liu & Ma, "Feasible region for DERs in unbalanced distribution networks with uncertain line impedances", [arXiv:2212.03985](https://arxiv.org/abs/2212.03985) (PES GM 2023 per arXiv) | ABS | A robust DER feasible region under impedance uncertainty. | The uncertainty set is assumed. |
| 7 | Bassi, Ochoa, Alpcan, Leckie, "Electrical model-free voltage calculations using neural networks and smart meter data", *IEEE TSG* 14(4) (2023) 3271–3282. [doi:10.1109/TSG.2022.3227602](https://doi.org/10.1109/TSG.2022.3227602) | META | A model-free neural-network voltage calculator for operating envelopes, on a real Australian LV network (from project pages). | Extrapolation and parameter ambiguity not verified. |
| 8 | Petrou et al., *IEEE TSG* 12(5) (2021) 3877–3888, [doi:10.1109/TSG.2021.3081371](https://doi.org/10.1109/TSG.2021.3081371); Liu, Ochoa et al., *IEEE TSG* 13(6) (2022) 4494–4504, [doi:10.1109/TSG.2022.3188927](https://doi.org/10.1109/TSG.2022.3188927) | ABS | OPF-based dynamic operating envelopes in practice. | The network model is treated as correct (inference). |
| 9 | Claeys, Geth, Deconinck, "Optimal power flow in four-wire distribution networks: formulation and benchmarking", *EPSR* 213 (2022) 108522. [doi:10.1016/j.epsr.2022.108522](https://doi.org/10.1016/j.epsr.2022.108522) | FULL (preprint) | On 128 UK four-wire networks, the Kron-reduced model **overestimates capacity**: phase-to-neutral voltages exceed 1.10 pu by about 1–4 %. | Structural uncertainty only; no identification. |
| 10 | Ardakanian et al., "On identification of distribution grids", *IEEE TCNS* 6(3) (2019) 950–960. [doi:10.1109/TCNS.2019.2891002](https://doi.org/10.1109/TCNS.2019.2891002) | FULL (arXiv v1) | Voltage data are rank-deficient, so only a submatrix of the admittance is recoverable. | No decisions. |
| 11 | Moffat, Bariya, von Meier, *IEEE TSG* 11(1) (2020) 846–856. [doi:10.1109/TSG.2019.2956706](https://doi.org/10.1109/TSG.2019.2956706) | ABS | Fundamental limits of unsupervised impedance and topology estimation. | No decisions. |
| 12 | Buason, Misra, Talkington, Molzahn, "A data-driven sensor placement approach for detecting voltage violations in distribution systems", *EPSR* 232 (2024) 110387. [doi:10.1016/j.epsr.2024.110387](https://doi.org/10.1016/j.epsr.2024.110387) | FULL | Bilevel MILP placing sensors and thresholds to detect voltage violations, with costed false alarms. | Noise-free sensors, balanced model, **no network-parameter uncertainty**. |
| 13 | Vangulick, Bahmanyar, Ernst, "A practical approach for optimal placement of measurement devices in electrical distribution systems with ANM considerations", [ORBi 2268/320867](https://hdl.handle.net/2268/320867) (2024) | ABS | Placement scored by the curtailment and ANM outcome, not by estimation accuracy. | Parameter uncertainty not mentioned. Venue unconfirmed. |
| 14 | Nijhuis, Gibescu, Cobben, "Valuation of measurement data for LV network expansion planning", *EPSR* 151 (2017) 59–67. [doi:10.1016/j.epsr.2017.05.017](https://doi.org/10.1016/j.epsr.2017.05.017) | ABS | AMI data valued by avoided reinforcement cost; about half the benefit comes at 65 % coverage. | A planning decision; no parameter ambiguity. |
| 15 | Christakou, Paolone, Abur, "Voltage control in active distribution networks under uncertainty in the system model: a robust optimization approach", *IEEE TSG* 9(6) (2018) 5631–5642. [doi:10.1109/TSG.2017.2693212](https://doi.org/10.1109/TSG.2017.2693212) | ABS | Robust voltage control with bounded line-parameter uncertainty. | IEEE 13/34; the sets are assumed. |
| 16 | Ortmann, Hauswirth, Caduff, Dörfler, Bolognani, "Experimental validation of feedback optimization in power distribution grids", *EPSR* (2020). [doi:10.1016/j.epsr.2020.106782](https://doi.org/10.1016/j.epsr.2020.106782) | ABS | In a real-grid experiment, **model-based OPF violated limits under model mismatch while feedback did not**. Approximate sensitivities suffice. | Real-time control only. |
| 17 | Bouchkati et al., "Safety screening for voltage control in active distribution grids via distributionally robust conformal screening", [arXiv:2608.30889](https://arxiv.org/abs/2608.30889) (2026) | ABS | Conformal deploy-or-flag screening, calibrated on simulation-to-reality error. All unsafe scenarios flagged on IEEE 33- and 141-bus. | Two-way only; no measurement request. Guarantee type not verified. |
| 18 | Manoharan, "Audited selective verification for risk-controlled N-1 thermal contingency screening under deployment shift", [arXiv:2607.13221](https://arxiv.org/abs/2607.13221) (2026) | FULL | Verify / audit / skip triage with a Clopper–Pearson guarantee under shift. | Transmission. AC model assumed correct. |
| 19 | Stratigakos, Wen, Spyrou, Pinson, "Decision-calibrated prediction sets for robust power system operations", [arXiv:2606.02081](https://arxiv.org/abs/2606.02081) (2026) | FULL (≈75 %) | Uncertainty sets calibrated at decision level for robust DC-OPF. The violation loss is non-monotone, so the conformal-risk-control guarantee does not apply directly. | Network known; no abstention. |
| 20 | Lekeufack, Angelopoulos, Bajcsy, Jordan, Malik, "Conformal decision theory", ICRA 2024. [doi:10.1109/ICRA57147.2024.10610041](https://doi.org/10.1109/ICRA57147.2024.10610041) | FULL | Online calibration of decisions with long-run average-risk guarantees. | No per-step guarantee; generic. |
| 21 | Identification for control: Gevers, *Eur. J. Control* 11 (2005) [doi:10.3166/ejc.11.335-352](https://doi.org/10.3166/ejc.11.335-352); Hjalmarsson, *Automatica* 41 (2005) [doi:10.1016/j.automatica.2004.11.021](https://doi.org/10.1016/j.automatica.2004.11.021); Bombois et al., *Automatica* 42 (2006) [doi:10.1016/j.automatica.2006.05.016](https://doi.org/10.1016/j.automatica.2006.05.016) | META | The principle: identify only to the accuracy the application needs, at least cost ("least costly identification"). | Not transferred to distribution-network asset data (none found). |
| 22 | Value of information: Howard, *IEEE TSSC* 2(1) (1966) [doi:10.1109/TSSC.1966.300074](https://doi.org/10.1109/TSSC.1966.300074); Straub, *Struct. Safety* 49 (2014) 75–85 [doi:10.1016/j.strusafe.2013.08.006](https://doi.org/10.1016/j.strusafe.2013.08.006); Thöns, *CACAIE* 33(1) (2018) 79–94 [doi:10.1111/mice.12332](https://doi.org/10.1111/mice.12332) | ABS / META | Mature Bayesian value-of-information theory and structural-health-monitoring value-of-information practice. | Not applied to LV asset records (none found). |
| 23 | Manski, *Econometrica* 72(4) (2004) 1221–1246, [doi:10.1111/j.1468-0262.2004.00530.x](https://doi.org/10.1111/j.1468-0262.2004.00530.x); Long, Sim, Zhou, "Robust satisficing", *Oper. Res.* 71(1) (2023) 61–82, [doi:10.1287/opre.2021.2238](https://doi.org/10.1287/opre.2021.2238) | ABS | Minimax-regret treatment rules under partial identification; robust satisficing. | Generic. |
| 24 | Decision-focused learning: Elmachtoub & Grigas, *Mgmt Sci.* 68(1) (2022) [doi:10.1287/mnsc.2020.3922](https://doi.org/10.1287/mnsc.2020.3922); Donti, Amos, Kolter, NeurIPS 2017 [arXiv:1703.04529](https://arxiv.org/abs/1703.04529); Mandi et al., *JAIR* 80 (2024) [doi:10.1613/jair.1.15320](https://doi.org/10.1613/jair.1.15320) | ABS | Train models on decision loss, not prediction loss. | Learns predictors, not network-information acquisition. |
| 25 | Valverde, Zufferey, Karagiannopoulos, Hug, "Estimation of voltage sensitivities to power injections using smart meter data", IEEE ENERGYCON 2018. [IEEE Xplore](https://ieeexplore.ieee.org/iel7/8390721/8398733/08398841.pdf) | ABS (search-level) | **Collinearity** of smart-meter P and Q and across similar customers degrades sensitivity estimates; proposes regularisation and clustering. | Not tied to the envelope decision or to decision-induced shift. |
| 26 | Trabucco, Kumar, Geng, Levine, "Conservative objective models for effective offline model-based optimization", ICML 2021, PMLR 139:10358–10368. [arXiv:2107.06882](https://arxiv.org/abs/2107.06882) | ABS | An optimiser searching against a learned model is driven to out-of-distribution inputs where the model overestimates. Conservative models counter this. | Not physical systems or power networks. |
| 27 | University of Melbourne / C4NET, "Model-Free Operating Envelopes at NMI Level", project page and final report. [project page](https://electrical.eng.unimelb.edu.au/power-energy/projects/model-free-operating-envelopes), [report](https://c4net.com.au/wp-content/uploads/2023/09/UoM-C4NET-Model-Free_OEs-FinalReport_v02.pdf) | search-level only | Neural networks trained on historical smart-meter data replace the LV model for operating envelopes; demonstrated on real Australian data (155 customers). | Search-level evidence found no treatment of performance outside the training range. Unverified in the full report. |

**Searched without a match (weak evidence; abstracts mostly):**
- a study joining data-compatible LV network-model sets to decision equivalence or regret;
- asset-record verification valued against sensors;
- an act / robust / request-measurement / defer policy with guarantees against network-parameter error for DER decisions.

**Not searched:**
- Scopus or Web of Science;
- theses;
- non-English literature;
- set-membership and info-gap methods in depth.

---

## Part IV — Novelty matrix

Each originality score runs from 1 (none) to 5 (strong); "Unc." is our uncertainty in that judgement.

| Candidate claim | Closest work | What that work already establishes | What GridPulse establishes | What is genuinely different | Unsupported | Originality | Unc. | Minimum experiment to substantiate it |
|---|---|---|---|---|---|---|---|---|
| **N1. Mathematical:** first-order cable-error sensitivity (M1) | Baran & Wu 1989; Gan & Low 2014; Bernstein & Dall'Anese 2017; textbook KVL | The relation itself and its multiphase forms | AC validation of it as a screen on one feeder | Nothing mathematical | — | **1** | low | None: it is not a claim worth making |
| **N2. Algorithmic:** the power-only phase-frame screen (H3) | Linearisation at flat voltage (Bernstein & Dall'Anese); Kumarawadu 2025 | Fixed-point and flat-voltage linear models | H3 ranks sections like M1 (ρ 0.9998); magnitude errors up to 117 % | No algorithmic novelty; it is a renamed standard approximation | Generality | **1** | low | — |
| **N3. Empirical:** positive-sequence screens give wrong signs on an unbalanced LV feeder | Multiphase OPF literature; Claeys et al. 2022 (Kron vs four-wire) | Qualitatively, that coupling matters | 218 and 280 of 1,917 signs wrong on one feeder; mechanism shown (cancellation, neutral rise) | A quantified, sign-level benchmark for *screening* | One feeder; merged neutral; no explicit four-wire model | **2** | medium | 5–10 open feeders, plus an explicit four-wire model: does the error rate survive? |
| **N4. Empirical:** single-section impedance errors are mostly undetectable | Vanin 2023; Rosato 2026; Moffat 2020 | Weak lines are hard to identify (as an estimation side-effect) | A calibrated detector, and a decomposition into topological / weak / statistical / detectable (5 of 203) | A detection framing with calibrated false alarms; a negative result | Scenario-specific (light load, 10 days); extrapolated durations | **2** | medium | Multi-feeder, a full year, constraint-proximate loading |
| **N5. Methodological:** busbar-referenced studentised contrast (C2-ref) | HAC, self-normalisation, Liu et al. 1992 multi-snapshot residuals | Calibrated tests under dependence | Size about 0.05 under stipulated N1/N2; invalid under across-day dependence | An application | Real-noise validity | **1–2** | medium | Real smart-meter residuals |
| **N6. Decision-theoretic:** independently mis-recorded ratings are unidentifiable and decision-critical, while identifiable impedances were decision-irrelevant at light load | Identification-for-control (principle); envelope work that assumes a correct model; Liu 2024 (impedance boxes cut envelopes 37–54 %) | The principle, and that robust treatment of *assumed* impedance uncertainty is very costly | Phase 8 (a *bundled* R × 1.5 and rating × 0.8 error defeated all policies in 3 of 5 networks); M10 Control B (a rating-only error gives exactly zero signal, by construction); M10 (impedance errors changed no decision at light load) | The empirical juxtaposition, and the open tension with Liu 2024: how much robust-envelope conservatism is unnecessary once data are used? | Everything outside light-load SimBench and IEEE; no constraint-proximate test; may be a light-load artefact | **2–3 (potential)** | high | A constraint-proximate test (now secondary; see Part VII) |
| **N7. Decision-theoretic and methodological:** a decision-sufficiency *diagnostic* over data-compatible network-model sets | Rosato 2026 (sets); Liu & Ma 2023 and Liu 2024 (robust decisions over assumed sets); Manski (partial identification) | Each half exists separately | Nothing yet | Joining a calibrated data-compatible set to decision equivalence and regret for LV DER decisions | All of it; under the specified assumptions it may be analytically derivable (AKK-56) | **2** | high | Superseded by Part IX's revised design |
| **N8. Decision-theoretic:** asset-record verification as an information source on a common regret scale with sensors and longer observation | Value of information in structural health monitoring (Straub 2014; Thöns 2018); Nijhuis 2017 (AMI value); Vangulick 2024 (curtailment-aware placement) | Mature value-of-information machinery; placement judged by decisions | Nothing yet (Phase 5 compared sensors only) | Records as information, alongside sensors, under network-parameter ambiguity | All of it; record-error priors have no data | **3** | high (non-systematic search) | The competing direction (ampacity information, Part V.2 #9) |
| **N9. AI:** act / robust / measure / defer with guarantees against network-parameter error | Bouchkati 2026; Manoharan 2026; Stratigakos 2026; Lekeufack 2024 | Conformal screening and decision calibration, mostly with a known network | Phase 3 H4a was not supported, an underpowered null | A "request measurement" action priced by value of information; guarantees against parameter error | All of it; non-monotone losses complicate guarantees | **2–3** | high | A later stage (the abstain path of Part IX) |
| **N10. AI and EEE:** decision-induced extrapolation of data-driven operating envelopes | Bassi 2023; Kumarawadu 2025; the C4NET "model-free OE" project report; Valverde et al. 2018 (collinearity in sensitivity estimation); Trabucco et al. 2021 (optimisers exploit learned-model errors); Venzke 2020 | Model-free envelopes; smart-meter sensitivity estimation suffers from collinear injections; generic "optimiser exploits surrogate" failure | M1/H3 validated as sign- and ranking-correct physics structure; magnitude failures localised (cancellation) | The envelope itself requests injection *magnitudes and cross-customer allocations* that historical (PV-collinear) data never excited. A decision-induced shift in the electrical injection space, tested against physics-structured guards | All of it | **3** | high | **The preferred direction's decisive experiment (Part IX)** |

**Contribution categories:**
- **Credible today:** a careful exploratory benchmark (N3, N4) and an honest negative result for single-cable detection.
- **Credible only after the decisive experiment:** N6–N8 (decision-relevant identifiability and information value).
- **Not credible:** any mathematical or algorithmic novelty claim for M1, H3 or C2-ref.

---

## Part V — Challenging the current direction

### V.1 The seven assumptions

**A. Detecting cable-impedance errors is intrinsically useful.**
- *Valid when* the impedance enters a binding constraint. Examples: voltage rise on a long, PV-rich rural run near 1.10 pu, or protection settings.
- *Fails when* the section carries little current, the feeder has voltage headroom, or the decision is thermal. M10: 59 sections carry no current, and the largest error used ≤ 5.8 % of voltage headroom.
- *Counterexample:* a 1.5× resistance error on section 22 is the feeder's strongest signal, yet consumes 5.8 % of headroom and changes no verdict.
- *Literature:* Vanin 2023 judges estimation by voltage fit, not decisions.
- *Evidence needed:* the decision regret attributable to impedance errors in constraint-proximate, physically plausible scenarios.

**B. A physically accurate estimator necessarily improves operational decisions.**
- *Valid when* the decision is model-based, ex ante, and sensitive to the estimated quantity.
- *Fails when:*
  - feedback can replace the model, *for real-time control with controllable DER and telemetry* (Ortmann 2020; GridPulse Phases 4 and 7 restored reliability without identification). It cannot deliver a firm ex-ante contractual limit, or police thermal limits without current measurement (AKK-56);
  - the decision depends on unidentifiable quantities (ratings);
  - the estimator is accurate where it does not matter. Vanin: lengths wrong, voltages right.
- *Counterexample:* GridPulse Phase 7. Busbar residual correction (no impedance estimation at all) met 15 of 15 model-error cases.
- *Evidence needed:* regret of an estimated-model decision against model-free and robust decisions.

**C. Better measurement accuracy necessarily produces sufficient information.**
- *Fails* for structurally unidentifiable quantities, whatever the accuracy: the rating (Control B, exactly zero); unexcited chains (Rosato); rank-deficient data (Ardakanian). It also fails under systematic bias, which grows *relatively* more harmful with observation length (M10: b* falls from 8.2e-4 to 1.9e-4 pu over 10 to 120 days).
- *Counterexample:* no voltage sensor of any accuracy reveals a wrong `max_i_ka`.
- *Evidence needed:* information value against accuracy, separated by parameter class.

**D. Detecting every physical error is necessary for safe operation.**
- *Fails when* robust margins or feedback absorb the error. Phase 7 handled tap and MV errors without attributing them.
- *Holds for* errors that neither feedback nor margins see and that bind: wrong ratings (Phase 8).
- *Evidence needed:* which error classes are absorbed by which policies.

**E. If a model error cannot be identified, decisions must become unreliable.**
- *Fails when* the decision is invariant over the data-compatible set. Two networks with different cable lengths but identical metered sensitivities give the same voltage-constrained export limit, when the critical buses are metered.
- *Holds when* the unidentifiable direction moves a binding constraint: an unmetered extremity bus, or a rating.
- *This is the central conjecture of the preferred direction*, and it is testable.

**F. More sophisticated AI will improve this problem.**
- *Fails where* exact cheap physics exists. M10's linear phase-frame model matched nonlinear AC power flow within 10 % for 98.7 % of meter responses, with every sign right, so a neural surrogate of it adds nothing.
- *Learning is genuinely needed for:*
  - calibrating uncertainty sets and error distributions from data (statistical inference under dependence);
  - detecting distribution shift;
  - amortising expensive set or decision computations, and then only if exact enumeration is infeasible.
- *Evidence needed:* every learned component must beat its exact or physical baseline on the decision metric.

**G. The most promising contribution is another detector.**
- *Fails here.* Phase 9 and M10 show the binding limit is physics, not the detector. Even the oracle matched filter detects only 75 of 144 sections at σ 0.002 over 120 days.
- *Better:* ask which information changes which decision.

**The fact that no decision changed in Mission 10 is the key signal.** The question we optimised — detect impedance errors — is misaligned with the decision layer GridPulse built in Phases 3–8. It may also reflect a lightly loaded scenario. The decisive experiment must separate the two, using constraint-proximate scenarios chosen by a physically justified rule.

### V.2 Candidate directions

The "Gap" field uses four categories: **Known/known** (problem and solution known), **Known/limitation** (known problem, unresolved practical limitation), **Comparative** (established methods, insufficient comparative evidence) and **New** (a potentially new formulation).

**1. Decision-sufficient network information (DSNI): decision-relevant identifiability for ex-ante DER export decisions.** Covers Directions A and B, and absorbs D.
- *Question:* when several LV network models are consistent with smart-meter data and asset records, do they support the same safe export limit? And which additional information — sensors, current metering, record verification, longer observation — reduces *decision* regret most?
- *Gap:* Known/limitation plus Comparative, with a modest New component: joining a calibrated data-compatible set to decision equivalence and value of information.
- *Closest:* Rosato 2026 (sets, no decisions); Liu 2024 and Liu & Ma 2023 (robust decisions, assumed sets); identification-for-control (principle).
- *What they did not solve:* the decision consequence of data-left ambiguity; records as information.
- *Why it matters:* utilities must choose between surveying records, installing meters and accepting conservative limits. Liu 2024's 37–54 % envelope loss under assumed boxes suggests a large, possibly unnecessary, cost.
- *Easy modification of an existing method?* Partly. A robust OPF over a smaller set is routine; the empirical decision-misalignment question is not.
- *What would disprove novelty:* finding a paper that already compares information sources by decision regret under data-consistent network ambiguity.
- *Without ML?* It still matters, and it is mainly EEE plus decision theory plus statistics.
- *Strongest critique (AKK-56).* Under balanced models, known topology and phase, metered critical buses and linearised constraints, the result is **analytically derivable**: the envelope depends on the metered sensitivities, which AMI can estimate, and on the ratings, which lie outside the data. The experiment would be "true and uninformative". Everything that would make it non-trivial lies outside the first experiment's scope: unbalance and the neutral, unmetered extremities, conductor temperature, the coupling between the thermal limit and θ.
- *Its useful core survives as a lens* inside direction 5: which **decision directions** are identifiable from the data that operation actually produces.

**2. Value of information for grid decisions (Direction B standalone).** A Bayesian pre-posterior analysis across information sources.
- *Gap:* Comparative.
- *It loses as a standalone* because it is the evaluation layer of direction 1 without its identifiability insight. Direction 1 contains it.

**3. Selective decisions with network-parameter guarantees (Direction C):** act / robust / measure / defer.
- *Gap:* Known/limitation.
- *Closest:* Bouchkati 2026; Manoharan 2026; Stratigakos 2026; Lekeufack 2024.
- *Against it:*
  - GridPulse Phase 3's deferral criterion failed.
  - Decision losses are non-monotone, which weakens conformal guarantees.
  - The field is moving fast (three 2026 preprints).
- *Value:* the genuine AI/statistics component, *if* direction 1 first shows that decision ambiguity is often small and identifiable. Otherwise "defer" becomes "always defer".

**4. Consequence–identifiability map of realistic asset-record error classes (Direction D):** multi-section wrong cable type, phase mislabels, ratings, neutral/earthing, transformer tap, missing DER.
- *Gap:* Comparative.
- *Closest:* Lave 2019 (records are wrong in practice); Antić 2024 (phase choice changes hosting capacity by up to 14 MW in a day); Claeys 2022 (neutral modelling changes capacity); Liu 2024.
- *Value:* very useful to utilities and engineers.
- *Against it, standalone:* largely a sensitivity study without a unifying question. **Its error classes become the scenario axis of direction 1.**

**5. Decision-induced extrapolation in data-driven operating envelopes** *(new; the preferred direction after review)*.
- *The mechanism:* envelopes are meant to raise exports beyond what has been observed. A model learned from history (Bassi 2023; Kumarawadu 2025; the C4NET model-free OE project) is then queried *outside* its training support, at the operating points where safety matters most.
- *It has two physically distinct parts:*
  1. **Magnitude extrapolation:** exports larger than ever metered.
  2. **Allocation extrapolation:** rooftop PV on one feeder is strongly correlated (shared irradiance), so historical data barely excite *differences* between customers' injections. Per-customer sensitivities are then poorly identifiable (Valverde et al. 2018 report collinearity in smart-meter sensitivity estimation), yet a per-customer envelope is exactly a request for an un-excited allocation.
- An optimiser searching against a learned model is drawn to the model's errors: the offline model-based-optimisation failure mode (Trabucco et al., ICML 2021). Here it happens in a physical system with hard safety limits.
- *Question:* do model-free envelopes become unsafe exactly when they are useful? Can a physics-structured model (phase-frame sensitivities, validated in M10 for sign and ranking) bound the extrapolation error, and so certify or abstain?
- *Gap:* Known/limitation plus New: the decision-induced shift.
- *Closest:* Bassi 2023; Kumarawadu 2025; Venzke 2020; Pareek (GP bounds); performative-prediction ideas (not verified here).
- *Value:* the strongest AI-plus-EEE intersection.
- *Against it:*
  - real smart-meter voltage data are scarce, so external validity needs real data;
  - a synthetic study could produce the "obvious" result that physics extrapolates better. AKK-57 counters this with Mission 10's own evidence: H3's magnitudes were off by up to 117 % at cancellation points, so "physics wins" is a testable claim with a known failure mechanism, not a foregone conclusion.
- *Why the data objection is weaker than first scored (AKK-56, AKK-57):* the decisive test needs only simulated ground truth, which gives the true safe envelope. SimBench's own scenario years (today's PV against 2034) provide a shift that is not hand-picked. Real data matter for the *paper*, not for falsification.

**6. Four-wire neutral and earthing uncertainty as decision-relevant structural ambiguity** *(new)*.
- *Question:* unknown earthing resistances and neutral impedances, and Kron-reduction error: how much do they change voltage-constrained decisions? Are they identifiable from phase-to-neutral smart-meter voltages?
- *Gap:* Known/limitation.
- *Closest:* Claeys, Geth, Deconinck 2022; Geth, Heidari, Koirala 2022; Kotsonias (neutral-aware state estimation).
- *For it:* strong EEE. M10's sign results come from the zero-sequence (neutral) coupling, so this is physically motivated.
- *Against it:* weak AI; an active specialist group already works on it; it needs four-wire data (ENWL, licence unresolved).

**7. Multi-feeder benchmark of linearised screens on unbalanced LV networks** *(new; M10 extended)*.
- *Gap:* Comparative.
- *For it:* quick and reproducible.
- *Against it:* low novelty, at best a conference or workshop paper.

**8. Calibrated smart-meter residual monitoring under dependence** *(the Phase 9 line)*.
- *Gap:* Known/known for the statistics.
- *Against it:* low novelty, and the physics limits the decision value (G above).

**9. Decision-sufficient ampacity information for LV export approvals** *(proposed by AKK-56)*.
- *Question:* for export or connection approvals limited by thermal capacity, which information makes a safe approval possible, and at least cost? The candidates are record verification, mid-feeder current monitoring, conductor-temperature or thermal monitoring, and flat derating.
- *For it:*
  - it targets the parameter GridPulse found decision-critical and voltage-blind;
  - real ampacity depends on installation conditions (soil thermal resistivity, grouping, depth, ambient), so "verify the record" may *not* reveal it;
  - the competing information sources are real choices that utilities fund;
  - it does not collapse under full AMI;
  - it can be tested on SimBench, which has thermally binding segments.
- *Against it:*
  - the AI role is small;
  - realistic ampacity-error statistics have no data;
  - thermal modelling (IEC 60287-type) is a specialist area that needs a collaborator.
- *Gap:* Known/limitation plus Comparative.

---

## Part VI — Scientific ranking

**Scores** run from 1 to 5. The data criterion is split, as AKK-56 recommended:
- **Data-L:** licence-clear data exist.
- **Data-A:** the data are *adequate* for the decisive test.

**Revised after the adversarial reviews.** Changes from the first draft are marked †.

| Direction | Orig | Imp | Depth | Fals | Feas | Data-L | Data-A | Base | Gen | Fit | EEE+AI | Use | Pub |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **5 Decision-induced extrapolation** of data-driven envelopes | 3–4 | 4 | 4 | 4 | 4† | 4† | 3† | 4 | 3 | 4† | **5** | 4 | 3–4 |
| **9 Decision-sufficient ampacity information** (AKK-56) | 3 | **4–5** | 4 | 3 | 3 | 4 | 2 | 3 | 3 | 4 | 2 | **5** | 3 |
| 1 Decision-sufficient network information | 2–3† | 4 | 3† | 3† | 4 | 4 | 2† | 3† | 2† | 4† | 3 | 4 | 3 |
| 4 Error-class consequence map | 2 | 4 | 3 | 3 | 4 | 3 | 2 | 3 | 3 | 4 | 2 | **5** | 3 |
| 3 Selective act/measure/defer | 2–3 | 4 | 4 | 3 | 3 | 3 | 3 | 4 | 3 | 3 | 4 | 3 | 3 |
| 6 Four-wire neutral uncertainty | 2–3 | 4† | **5** | 4 | 3 | 2 | 2 | 4 | 3 | 3 | 2† | 3 | 3 |
| 2 Value of information standalone | 2 | 4 | 3 | 4 | 4 | 4 | 2 | 3 | 3 | 4 | 2 | 4 | 2–3 |
| 7 Multi-feeder screening benchmark | 1–2 | 2 | 2 | 4 | **5** | 3 | 3 | 3 | 3 | **5** | 1 | 3 | 2 |
| 8 Calibrated residual monitoring | 1–2 | 2 | 3 | 4 | 4 | 3 | 3 | 4 | 2 | 4 | 3 | 2 | 2 |

**The best three, and the trade-offs.**

1. **Direction 5: decision-induced extrapolation.**
   - It asks whether the data-driven envelope methods now being proposed for LV networks are safe exactly where they are used: beyond the injections they were trained on.
   - It has a physical mechanism that is not obvious: PV collinearity leaves the per-customer *allocation* directions un-excited.
   - It is falsifiable in simulation against known ground truth, with a shift that is not hand-picked (SimBench's own scenario years).
   - It has the strongest genuine AI-plus-EEE content: learned models, decision-induced distribution shift, calibrated certification or abstention, physics structure as a guard.
   - It reuses Mission 10's validated phase-frame sensitivity structure, together with its known failure mode (cancellation), as a competitor rather than an assumption.
2. **Direction 9: ampacity information** (AKK-56's proposal).
   - The most decision-relevant physical question GridPulse has uncovered, and the most useful to distribution engineers.
   - It ranks below direction 5 because:
     - its AI content is small;
     - its core input (realistic ampacity-error statistics, and installation derating) has no data GridPulse can obtain;
     - the thermal modelling needs a specialist collaborator.
   - **If the owner prefers a pure-EEE contribution, choose it over direction 5.**
3. **Direction 1, reduced to a short theory note.**
   - The reviews showed that its experiment would be analytically derivable. Its value is therefore as *propositions*:
     - when is a voltage-constrained envelope decision-identifiable without impedance identification?
     - why is an independently mis-recorded rating structurally unidentifiable?
   - These propositions also serve as the lens for direction 5. They are not a programme of their own.

**Why the others lost:**
- **Direction 4** becomes the scenario axis of directions 5 and 9.
- **Direction 3** is the "abstain" branch of direction 5, not a separate programme. Phase 3's H4a was an underpowered null, which neither supports nor refutes it.
- **Direction 6** is EEE-deep, but data-limited and owned by an established group.
- **Direction 2** is contained in directions 1 and 9.
- **Directions 7 and 8** are low in novelty. Direction 7 remains a possible short benchmark note to bank Mission 10.

### VI.2 Internal adversarial discussion of the preferred direction

**Power-systems researcher.**
- *"Utilities don't deploy neural-network envelopes; model-free operating envelopes are a research topic."*
  - They are an active research-and-pilot line with utility involvement (the C4NET project; Kumarawadu 2025).
  - Estimated-sensitivity envelopes are the realistic near-term practice, and are included as a baseline.
  - The risk that the topic stays academic is real, and it is stated.
- *"Ridge regression already handles collinearity."*
  - Regularisation stabilises the estimate by shrinking it in the *un-excited* directions, which are exactly the directions the per-customer envelope acts in.
  - Whether that bias is decision-relevant is the experiment's question, not something to assume.
- *"Balanced SimBench removes unbalance."*
  - Accepted. Stage A results are stated as conditional on balance. Stage B (unbalanced) is a precondition for any general claim.

**AI / statistics researcher.**
- *"Extrapolation failure of learned models is known, and covariate-shift conformal methods exist."*
  - Here the shift is *induced by the decision* and removes overlap with the training data by design. Overlap-based corrections (weighted conformal) cannot then certify, so abstention is necessary.
  - The research question is whether physics structure restores certifiability without overlap.
- *"Six SimBench networks are not six replicates."*
  - Accepted. Results are reported per network, with no pooled significance claims. Inference uses day-block bootstrap within networks.

**Skeptical reviewer.**
- *"This is offline model-based optimisation applied to operating envelopes."*
  - Partly yes. It is publishable only if it delivers more than that:
    - a physical characterisation of *which* directions are un-excited and why (PV collinearity, phase allocation, magnitude);
    - a certification method whose guarantee is validated against AC ground truth;
    - an honest comparison with simple conservative margins.
  - Otherwise it is a technical report.

### VI.3 External adversarial reviews (Paperclip AKK-56, AKK-57): what was accepted

Both reviews returned **CHANGES REQUIRED**.

**Accepted and applied:**
- **Phase 8's bundled rating error.** The report had misdescribed it as a rating-only error.
- **The thermal "first-order" claim.** Branch currents respond to ΔZ at first order through constant-power injections and losses. The claim was withdrawn.
- **The coupling between identifiability and thermal criticality** through branch current; the I.2 split may be a light-load artefact.
- **Phase 3, 5 and 7 citations** made precise; the list of registered failures completed.
- **Conductor temperature** added as an unmodelled confounder.
- **"Certificate" downgraded to "diagnostic"** for direction 1, and N7's originality lowered.
- **Direction 5's data score** raised, because simulated ground truth suffices for falsification.

**Accepted, and they drove the redesign.** The first draft's decisive experiment (for direction 1) was **withdrawn**:
- **Its H1 threshold was satisfied by noise.** With 6 sources, P(τ ≤ 0.4) = 0.864 under random ranking: at most 4 inversions out of 720 permutations has probability 98/720, and τ ≤ 0.4 needs at least 5.
- **Its χ² likelihood set was invalid** over a finite library with dependent noise, which is GridPulse's own R7 lesson.
- **Its outcome space was not partitioned.**
- **Its factorial invited forking paths.**
- **Its baseline under-covered the prior.** The ±γ box must cover about one cable size, roughly ±35 % in R.
- **It lacked the strongest baseline:** a measured-sensitivity envelope.
- **It ran on the balanced model class** that Mission 10 showed to be unreliable.

These lessons are built into the new Part IX.

**Considered but not adopted as the preferred direction:**
- **AKK-56's ampacity-centred direction.** It is adopted as the strongest *competing* alternative (#9), for the reasons in Part VI.
- **AKK-57 recommended direction 5,** with direction 4's error classes as its shift axis. Adopted, with the board's own addition of the allocation-extrapolation (PV collinearity) mechanism.

---

## Part VII — Independent opinion

**If this were my own project, I would pursue direction 5: decision-induced extrapolation in data-driven DER export decisions.**

The question: **when export limits are computed from models learned on historical smart-meter data, do they stay safe at the injection magnitudes and cross-customer allocations the limits themselves request, which the data never excited? And can a physics-structured model certify them, or know when to abstain?**

I would stop single-cable error detection entirely.

**Why this one:**
- It is the point where GridPulse's evidence, current practice and a real AI question meet.
  - **Evidence:** M10's validated phase-frame structure and its localised failure mode; Phase 5's measurement chain; Phases 4 and 7's finding that model errors break model-tuned rules.
  - **Practice:** data-driven and model-free envelopes are being proposed for LV networks *because* network models are poor.
  - **The AI question:** safety under a distribution shift that the decision itself causes.
- Its mechanism is physical and testable. It does not assume a field-level effect.

**I changed my mind during this assessment.** My first draft preferred direction 1, decision-sufficient network information. The adversarial reviews showed three things:
- my motivating claim about ratings was overstated (Phase 8 bundled R and rating);
- my decisive experiment's statistics would confirm my hypothesis under noise;
- under its own assumptions, the result would be derivable rather than discovered.

I checked each argument and accepted them. Direction 1 survives only as a short theory note and as a lens inside direction 5.

**Strongest competing alternative: direction 9, decision-sufficient ampacity information.**
- It is more practically important for distribution engineers and less crowded.
- It is weaker on AI and on obtainable data.
- If GridPulse should be a pure power-engineering contribution, I would choose it instead.

---

## Part VIII — Falsification: how the preferred direction could fail

I would abandon direction 5 if the decisive experiment shows any one of these:

1. **No decision-induced failure.** Under the registered shift (SimBench base-year profiles → 2034 scenario PV), data-driven envelopes keep AC-validated violations within target on at least 5 of 6 networks while reaching ≥ 95 % of the oracle's export.
   - Then the problem does not exist here.
2. **The failure is trivially fixed.** A simple conservative margin, or ensemble-disagreement abstention with no physics, achieves the same export as the physics-structured certifier at equal safety, within bootstrap intervals.
   - Then physics structure adds nothing.
3. **Physics fails equally.** The physics-structured model fails in the same way, through cancellation, record errors or unbalance in Stage B.
   - Then there is no certification advantage, and the result is reported as a negative.
4. **It only appears under hand-made conditions.** Effects appear only beyond SimBench's 2034 scenario, or only with a synthetic correlation structure.
   - Then the result is an artefact.
5. **Allocation does not matter.** Per-customer envelopes behave like a uniform cap, because the binding constraint is aggregate.
   - Then the allocation-extrapolation mechanism (PV collinearity) is irrelevant, and only "magnitude extrapolation", which is known, remains.

The most convincing failure is (2): a dumb margin works. That would mean the safety problem is real but the research contribution is not.

---

## Part IX — The smallest decisive experiment (Stage A; designed, not run)

**Research question.** Under a realistic, scenario-defined increase in PV, do per-customer export envelopes computed from models fitted to historical smart-meter data violate voltage limits on the true network? Do the violations grow with the decision-induced extrapolation, in magnitude and in allocation? Does a physics-structured fitted model with calibrated uncertainty certify safe envelopes, and abstain otherwise, at less export loss than physics-free conservative alternatives?

**Competing hypotheses** (with a pre-registered partition of the outcome space):
- **H0:** no decision-induced failure, or one trivially fixed (Part VIII, items 1–2).
- **H1 — decision-induced failure.** Data-driven envelopes exceed the violation target and the excess grows with extrapolation distance.
- **H2 — physics-structured certification.** Certified envelopes meet the target, and the physics-structured certifier reaches more export than physics-free conservative baselines.

| Verdict | H1 | H2 |
|---|---|---|
| **Supported** | On ≥ 4 of 6 networks, the bootstrap lower bound of the violation rate exceeds 3× the target; *and* the per-network permutation test of violation against extrapolation distance gives p < 0.01 | On ≥ 4 of 6 networks: the certified-envelope violation upper bound (Clopper–Pearson) is ≤ the target; *and* exported energy beats the best conservative baseline's by more than its bootstrap interval; *and* abstention ≤ 30 % |
| **Rejected** | On ≥ 5 of 6 networks, the violation upper bound is ≤ the target | The best conservative baseline's export is within the physics certifier's interval on ≥ 4 of 6 networks, or certified violations exceed the target |
| **Indeterminate** | Otherwise; no claim | Otherwise; no claim |

**Setup.**
- **Networks:** the 6 SimBench LV networks (ODbL 1.0 / DbCL 1.0).
- **Truth:** the SimBench network itself, solved by AC power flow.
- **Historical regime:** base-year SimBench load and PV profiles.
  - Smart-meter V, P and Q at every customer, with N1 noise (σ = 0.005, the primary cell), 5 % whole-day missingness and a 1-day delay.
  - The training window is 60 days, chosen before any run.
- **Decision regime:** the same networks with SimBench's 2034 PV scenario.
  - Envelopes are requested for daylight steps of held-out days.
  - **The shift is SimBench's own.** Nothing is tuned to produce failures.
- **Shift measures (independent variables):**
  - *magnitude:* the requested total export divided by the historical maximum;
  - *allocation:* the distance of the requested per-customer injection vector from the span of the historical injections, as the residual after projection onto the leading principal components, and the Mahalanobis distance.
- **Allocation policy:** one fixed policy for every model, so differences come from the model. It maximises total export subject to voltage ≤ 1.10 pu at customer buses, with an equal-share fairness constraint.
  - *Voltage convention.* The per-step cap is the base case, with a 10-minute-mean variant as a sensitivity. 0.90 pu is enforced under import.

**Models compared (the baselines):**
- **B1 Records:** the physics model from the asset records, using no data.
- **B2 Measured sensitivity:** linear sensitivity regression (ridge-regularised, Valverde- or Fang-style), with a conformal margin. **This is the strongest practical baseline.**
- **B3 Neural network:** a model-free voltage predictor (Bassi-style), with a conformal margin.
- **B4 Conservative neural network:** an ensemble-disagreement or conservative-objective-style penalty, which abstains when disagreement is high.
- **B5 Physics-structured fit:** tree topology and record impedances, with per-run correction factors fitted to the data (Vanin-style). Uncertainty comes from a parametric bootstrap calibrated under the stated noise model; no χ² reference.
- **B5-cert:** B5, accepting only envelopes whose bootstrap upper voltage bound is ≤ 1.10 pu. Otherwise it abstains and falls back to B1-robust.
- **B6 Oracle:** the true model.
- **B7 Feedback / online margin:** an operational reference only, not an ex-ante method.

**Metrics:**
- AC-validated violation rate per customer-step;
- exported energy relative to the oracle;
- abstention rate;
- the violation rate *conditional on certification*;
- predicted-against-true voltage error as a function of extrapolation distance.

**Statistics.**
- Per network, a day-block bootstrap; no pooled significance across networks.
- Monte Carlo noise replicates sized in advance so the violation-rate standard error is < 0.005 in the primary cell.
- **One primary cell** (σ 0.005, N1, 60 days, full AMI, base year → 2034). All other cells (σ 0.002, N2, 30 days, partial AMI) are labelled secondary and carry no claims.

**Negative controls:**
- **NC1, no shift** (decision regime = historical regime): every data-driven model should be safe. If not, there is an implementation fault.
- **NC2, decorrelated training PV** (independent per-customer variation, synthetic): the allocation effect should vanish.
- **NC3, records equal truth:** B1 and B5 should match the oracle.
- **NC4, time-shuffled training data:** the data-driven models should lose skill, which detects leakage.
- **NC5, a feeder whose binding constraint is thermal:** the voltage-model choice should not matter.

**Physical assumptions (stated limitations):**
- balanced SimBench, so every Stage A conclusion is conditional on balance;
- constant-power loads, PV at unity power factor;
- known topology and phase;
- no conductor temperature;
- an envelope evaluated per step.

**Stage B**, only if Stage A supports H1: an unbalanced replication. It would use the IEEE European LV feeder only once its terms are verified, or a licence-clear synthetic unbalanced feeder.

**Compute (estimate, not measured):**
- historical-regime truth: about 6 × 60 × 96 ≈ 35,000 small SimBench solves;
- decision-regime oracle envelopes and AC validation of the six models' envelopes on a stratified daylight sample: tens of thousands to a few hundred thousand solves.
- At about 6 ms per solve on SimBench LV networks, that is on the order of one CPU-hour.
- Existing Phase 4 caches may cover part of the 2034 regime.
- **This is a new compute scope that needs your approval.**

**What counts as a meaningful finding:**
- **H1 and H2 supported:** a publishable positive result.
- **H1 supported, H2 rejected:** an important negative — data-driven envelopes are unsafe under the shift they create, and physics structure does not fix it.
- **H0:** the direction closes cheaply and honestly.

---

## Part X — Publication path

| Level | What is needed |
|---|---|
| **Working paper or arXiv** | Stage A, with its verdicts and limitations. Achievable by GridPulse alone. |
| **Workshop** (an ML-for-energy or climate workshop; IEEE SmartGridComm or ISGT short paper) | Stage A with a clean H1 verdict; comparison against B2/B3/B4; the allocation-extrapolation mechanism shown with NC2. Venue fit to be checked; acceptance cannot be predicted. |
| **Conference paper** (PSCC, PowerTech) | Plus Stage B (unbalanced) and the secondary cells. |
| **Strong journal candidate** (IEEE TSG, EPSR, Applied Energy) | Plus: (i) a bound on the physics-structured model's extrapolation error in terms of parameter uncertainty and injection distance; (ii) validation on real smart-meter data, or a real LV feeder, through a collaborator; (iii) comparison against published model-free and estimated-sensitivity envelope methods on their own terms. |

---

## Part XI — Research resource requirements

**GridPulse can do alone:**
- Stage A: SimBench physics, smart-meter simulation, model fitting, envelopes, certification, statistics;
- the theory note (direction 1's propositions);
- a working paper.

**Needs a collaborator:**
- **power-systems:** operating-envelope practice and utility conventions, unbalanced and four-wire modelling, credibility, venue;
- **for direction 9:** thermal and ampacity modelling.

**Needs better data:**
- smart-meter voltage *and* power with feeder topology, licence-clear;
- licence-clear unbalanced LV feeders. The IEEE feeder's terms are unverified; ENWL's are unresolved.

---

## Part XII — Scientific recommendation

1. **Preferred research question.** When per-customer DER export limits are computed from models learned on historical smart-meter data, do they stay safe at the injection magnitudes and cross-customer allocations they request, which the data never excited? Can a physics-structured model certify safe limits, and abstain otherwise, at lower export loss than physics-free conservative methods?
2. **Tentative contribution statement.** A characterisation of decision-induced extrapolation in data-driven LV export envelopes:
   - magnitude, and allocation under PV collinearity, as distinct mechanisms;
   - an AC-validated comparison of data-driven, measured-sensitivity and physics-structured models;
   - a certify-or-abstain rule whose safety is tested against ground truth under a scenario-defined shift.
3. **Falsifiable hypotheses:**
   - **H1:** decision-induced violations exceed 3× the target and grow with extrapolation distance.
   - **H2:** physics-structured certification meets the target with more export than physics-free conservative baselines.
   - **Open question Q3:** does the allocation effect (NC2) dominate the magnitude effect?
   - The outcome-space partition is in Part IX.
4. **Closest prior-art challenge:**
   - **model-free and data-driven envelopes:** Bassi et al. 2023 (IEEE TSG; the C4NET model-free OE project); Kumarawadu et al. 2025 (Applied Energy);
   - **collinearity in smart-meter sensitivity estimation:** Valverde et al. 2018;
   - **optimisers exploiting learned-model errors:** Trabucco et al., ICML 2021;
   - **robust envelopes with uncertain impedances:** Liu, Braslavsky & Mahdavi 2024.
5. **Strongest baselines to beat:**
   - ridge-regularised measured-sensitivity envelopes with a conformal margin (B2);
   - a conservative ensemble neural network that abstains on disagreement (B4).
6. **First decisive experiment:** Stage A (Part IX), SimBench only, one primary cell; compute subject to your approval.
7. **Biggest unresolved risk:** a simple conservative margin may be enough (Part VIII, item 2). Second, the result may not survive real smart-meter data, which GridPulse does not have.
8. **Go / no-go:**
   - **GO for Stage A**, once you approve the compute.
   - **NO-GO for any further single-cable detection work.**
   - **Direction 1** only as a short theory note, if at all.
   - **Direction 9 (ampacity)** is the alternative to choose instead if you prefer a pure power-engineering contribution.
   - **No registered study, ENWL work or unbalanced Stage B** until Stage A has a verdict.

---

## Part XIII — Questions to discuss before committing

1. **Should GridPulse's central identity become "reliability of learned engineering decisions under the shifts those decisions create"** rather than "identifying the grid model"?
   - That is a real change of research programme. It moves GridPulse from grid-model *identification* towards *decision safety of data-driven methods*.
2. **AI-centred or engineering-centred?**
   - Direction 5 is the better AI-plus-EEE story. Direction 9 (ampacity) is the more important engineering problem and the less crowded one.
   - Which matters more for your MSc, your collaboration plans and the venues you want: an ML-for-energy audience, or a power-systems journal?
3. **Can you obtain, or seek through a collaborator, real smart-meter voltage and power data for some LV feeder?**
   - Without it, direction 5 tops out at a workshop or conference paper.
   - Direction 9 needs real ampacity and derating information instead.
   - If neither is realistic, the honest ceiling is a careful simulation-based working paper, and we should decide whether that is worth the effort.

---

## Part XIV — Publication safety of the Mission 10 files (recommendation; nothing edited)

- **Do not edit the frozen protocol.** `analysis/calibrated_detection_pilot/sensitivity_protocol.md` is the as-executed record; its executed sha256 is reconstructible and recorded in every artefact.
  - Keep it **local** until the IEEE feeder terms are verified.
  - It quotes exact feeder line-parameter tuples (§2, lines 34–36), the full 27-class downstream-customer histogram and section length statistics.
- **If Mission 10 is to be published sooner,** write a *separate*, clearly labelled `sensitivity_protocol_public.md`. It would:
  - reproduce the method, criteria and amendments;
  - replace feeder-specific values with qualitative statements ("r0/r varies by more than a factor of three across types");
  - record the original's sha256 so the provenance chain survives.
  - **Ratios are not automatically safe:** together with counts and lengths they can reconstruct parts of the line table, so redaction should be conservative.
- **`tests/test_sensitivity.py` lines 22–31** use real IEEE feeder cable types as toy-network fixtures. These are exact dataset records.
  - Replace them with synthetic round values in a public version; the tests do not depend on the specific values.
  - This is a test-only change for your approval.
- **`tests/test_detectability.py`** asserts two derived scalars (section 22's self and mutual terms). These are de minimis, but replaceable by synthetic values.
- **The research note** quotes coarse feeder statistics: the 907/906 bus count, 55 customers, r0/r range, voltage range. This is low risk but the same principle applies: keep it local, or review it alongside the protocol redaction.
- **Already committed (7925ac7):** `docs/proposal_calibrated_detection.md` and the pilot README quote public descriptors (906 LV buses, 55 single-phase loads, 0.416 kV). These are high-level facts from public descriptions, and low risk.
- **Unchanged:** all derived outputs, the held Phase 9 data and the pilot data stay local and untracked.
