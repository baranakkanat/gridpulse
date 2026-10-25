# Research note: PV correlation, learned voltage sensitivities and the safety of export envelopes (Mission 11, Stage A)

**Status.**
- EXPLORATORY, internally pre-specified (protocol `analysis/export_envelope_shift/stage_a_protocol.md`).
- Single evaluation network.
- Not externally preregistered, not confirmatory, not peer reviewed.
- Every number below is read from local artefacts (`analysis/export_envelope_shift/results/`, `runs/`), except two zero-solve board recomputations from those artefacts: the sensitivity refit quoted in §VII and §XVI, and the safe-only utilisation medians in §VI. Both are archived as scripts with their outputs in `docs/provenance/mission11_board_audit/` (`board_refit_sensitivity.py`, `board_utilisation.py`).
- The SimBench-derived artefacts stay local.
- Written by the board (Research Lead) on 2026-10-25. Post-experiment QA status: see §XIII.
- **Data attribution:** contains information from [SimBench](https://simbench.de), which is made available here under the [Open Database License (ODbL 1.0)](https://opendatacommons.org/licenses/odbl/1-0/). See [`analysis/export_envelope_shift/DATA_ATTRIBUTION.md`](../analysis/export_envelope_shift/DATA_ATTRIBUTION.md) for the notice and the derivative-database terms.

---

## I. Executive summary

**What was investigated.** Smart-meter data are used to learn customer-bus voltage sensitivities to PV export, and those sensitivities are then used to optimise per-participant export limits (an "envelope"). Rooftop PV outputs on one feeder are strongly correlated. The pre-registered question was whether that correlation, through poor identification of per-unit sensitivities, makes the optimised envelope physically unsafe when every participant exports at its limit. And if so, whether established remedies prevent it.

**The strongest results:**
1. **F0 — thermal limits bind first (design audit, before scoring).**
   - In all six SimBench LV networks at the registered PV scale (1.40× each network's own hosting capacity), the thermal limit (transformer or a line) binds before the voltage limit. The fraction of availability that thermal limits allow is 0.71–0.82; voltage would allow 0.92–1.00.
   - With the thermal limit in the decision (control T, rural3), no envelope was voltage-unsafe (0/40), and the export was identical in every PV regime.
   - **In this test bed, the voltage-identification question has no safety consequence once thermal limits are respected.** The study therefore scored the voltage component of the envelope, a conditional question for voltage-limited feeders.
2. **The optimiser exploits model error ("decision-induced extrapolation").**
   - **Ridge, total-export LP (B2):** a cross-validated ridge sensitivity model with only 0.0008 pu in-distribution error, used to maximise total export, produced a voltage-unsafe envelope in **10 of 10** near-limit conditions in **every** PV regime. The AC corner voltage was on average **+0.0045 pu** above the model's own prediction (worst +0.0069 pu).
   - **The same ridge model, proportional allocation (B2p):** unsafe in only 0–2 of 10, with a prediction error of about 0 (0 in P1, −0.0006 in P3).
   - The failure is in the **allocation**, not the model's average accuracy.
3. **PV correlation matters for the unregularised estimator, but not for the registered contrast.**
   - **OLS (B1):** unsafe in 10/10 conditions under strongly correlated PV (P1, mean pairwise correlation 0.83), against 1/10 under decorrelated PV (P3, 0.69). P1 − P3 = 0.90, interval [0.75, 1.00] (descriptive).
   - **Ridge at σ_v = 0.0005:** P1 10/10 against P3 0/10.
   - **The registered H1 contrast** (ridge, σ_v = 0.002) is **0.00**, because ridge is unsafe in every regime. H1 is formally **Rejected**, but the rejection rests on a ceiling, not on an absence of correlation sensitivity.
4. **An established method suffices, given topology.**
   - **The topology-structured LinDistFlow fit (B3, NNLS):** 0/10 unsafe in every regime (P1, P2, P3, L0), at about **99 %** of the AC oracle's export (about 98.6 % after correcting the oracle's zero-tolerance stopping rule, §XIII).
   - **The robust ellipsoid (B4):** safe, at 57–73 % utilisation (a lower bound; see §IX).
   - **Gupta-style box (B4box) and conformal margin (B2m):** did **not** prevent the failures (8/10 and 9–10/10 unsafe).
5. **Agreement-based reliability checks are blind to the mechanism.**
   - Data-consistent alternative models (bootstrap refits) agreed within 1–3 % of export and were **all unsafe together** (H4: decision equivalence).
   - The certify-if-alternatives-agree rule (CERT) therefore certified every unsafe envelope (k = 0 fallbacks; NOT EVALUABLE by its own rule).

**Did the original hypothesis survive?** Not in its registered form:
- H1 (correlation-dependent reliability) was Rejected on rural3;
- H3 (robust and information-aware methods) was Inconclusive;
- semiurb5 was NOT EVALUABLE (only 2 near-limit days).

A narrower and better-supported statement survived. When an envelope optimiser re-allocates export, it exploits per-unit sensitivity errors that in-distribution accuracy does not reveal (H2 Supported). Correlated PV makes those errors large for least squares, regularisation produces them in every regime, and physics structure (known topology) removes them.

**Recommendation (§XVII): PIVOT.**

---

## II. Scientific background

**Closest work** (protocol §0, with access levels recorded there):
- **Gupta, Sossan & Paolone (EPSR 2022).** Measurement-estimated sensitivities with a ±3σ box and a Bertsimas–Sim budget; the mandatory precedent, reproduced here as B4box.
- **Liu, Braslavsky & Mahdavi (2024).** Robust envelopes over assumed impedance sets.
- **Jalilian et al. (2026, arXiv:2604.17081).** Coordinated envelopes, with sensitivities treated as exact.
- **Valverde et al. (2018); Zhang et al. (TPWRS 2018).** Collinearity in smart-meter sensitivity estimation, and ridge-type remedies.
- **Peppanen-style structured estimation.** The B3 baseline.

**Established before the experiment:**
- correlated injections ill-condition least squares;
- ridge and probing are remedies;
- robust optimisation is safer but more conservative.

**Uncertain before the experiment:**
- whether excitation is related to *envelope safety* at all;
- whether in-distribution accuracy predicts that safety;
- whether data-consistent models disagree on the decision;
- whether any of this matters once thermal limits are included.

A further, general background point: estimate-then-optimise pipelines are known to select for estimation error. This is the "optimiser's curse" (Smith & Winkler, *Management Science* 2006) and the motivation for decision-focused learning (e.g. Elmachtoub & Grigas, *Management Science* 2022). Those references are cited from memory, so their details are NOT CHECKED in this mission. The finding in §I.2 is an instance of that known mechanism. It is not a new mechanism.

---

## III. Experimental design (as executed)

**Networks.**
- **The rule (§3):** at least 10 PV units, and voltage-limited at no action.
- **rural3 (evaluation):** 27 PV units, 118 customer buses.
- **semiurb5 (development):** 15 PV units, 104 customer buses.
- Both are SimBench LV `--2-sw` networks at the registered Phase 4 PV scale, with storage at 0 MW and MV and tap at nominal.
- semiurb5 passed the audit rule but only 2 of its 40 deployment days cleared the near screen. Under §15 and amendment A2 it is NOT EVALUABLE for H1–H3, and its results are descriptive.

**PV regimes** (synthetic interventions on the SimBench profiles, parameters fixed in advance, correlation measured):

| Regime | Shift spread Δ | Cloud σ_c | Mean pairwise PV correlation (rural3) | Training-design condition number |
|---|---|---|---|---|
| P1 | 0 h | 0.05 | 0.832 | 276 |
| P2 | 0.5 h | 0.15 | 0.822 | 109 |
| P3 | 1.0 h | 0.30 | 0.685 | 58 |
| L0 (P1's PV, native loads) | — | — | 0.832 | ∞ (rank-deficient) |

- Orientation shifts act on the smooth part of each profile only, so the weather residual stays at wall-clock time (QA finding M13). P2 is therefore barely decorrelated from P1.
- The synthetic household load process (σ_L = 0.3, AR(1) with φ = 0.7) is common to P1–P3. It already makes P1's training design well-posed (condition number 276); only L0, with native loads, is degenerate.

**Measurements:**
- voltage at every customer bus with Gaussian noise σ_v = 0.002 pu (primary; 0.0005 and 0.005 as controls);
- net P and Q exact.

**Data:**
- training on days 152–155 (384 steps);
- in-distribution test on day 156;
- deployment on days 160–199.

**Deployment conditions** (selected from offline AC truth, identical for every regime):
- rural3's 10 near-limit steps: no-action exceedance +0.0017 to +0.0077 pu;
- 10 far-from-limit steps.

**Methods:**

| Code | Method |
|---|---|
| B0 | 70 % feed-in rule |
| B1 | OLS |
| B2 | Ridge (cross-validated) |
| B2m | Ridge plus a split-conformal margin |
| B2p | Ridge with proportional allocation |
| B3 | Topology-structured NNLS (LinDistFlow) |
| B4box | Gupta-style box |
| B4 | Bootstrap-calibrated robust ellipsoid |
| A | Exact linear with AC offset (reference) |
| A′ | Exact linear with learned intercept (attribution reference) |
| B5 | Sequential-LP AC oracle |
| CERT, ALWAYS, RAND | The reliability rule and its controls |

---

## IV. Mathematical formulation

**The voltage model.** For a learned model, the predicted corner voltage at customer bus k is affine in the export limits:

 v̂_k(e) = c_k + Σ_b β_kb · P_b(e),  with P_b(e) = Σ_{i at b} e_i − ℓ_b.

**The structured model (B3).** v_k = c + Σ_{l ∈ path(k)} (ρ_l F_l + χ_l G_l), where F_l and G_l are the downstream net P and Q, and ρ_l and χ_l are non-negative, unknown line parameters. Known topology is used; impedances are not.

**The envelope.** e ∈ [0, a], with a rectangular box claim.
- **Primary decision:** max Σ e_i subject to v̂_k(e) ≤ V_max,k − m.
- **Ties** are broken by a second stage that keeps the total and minimises Σ_i |e_i/a_i − θ̄|.
- **Worst cases:** with non-negative sensitivities, the all-at-limit corner is the worst case for the upper voltage limit, and e = 0 is the worst case for the lower limit and for import.
- **Control T** adds |downstream flow| ≤ 0.95 · rating.

**The robust methods:**
- **B4box:** ridge coefficients ± 3σ̂ (sandwich variance), with a Bertsimas–Sim budget Γ = ⌈√p⌉ = 11.
- **B4:** the ellipsoid {β : (β − β̂)ᵀ(XᵀX + Λ)(β − β̂) ≤ r_k²}.
  - The radius comes from a 16-step moving-block bootstrap with a simultaneous max-statistic. There is no F/χ² reference; that is GridPulse's R7 lesson.
  - It is solved by Kelley cutting planes: 60 rounds, then uniform restoration.

**Ambiguity alternatives.** Four bootstrap refits of a non-negative ridge, plus four extreme points on B4's set. The extreme points collapsed (see §X).

**Safety.**
- **Unsafe:** the AC corner voltage exceeds V_max + 0.001 pu at any customer bus. A failed flow counts as unsafe; there were none.
- **Utilisation:** Σe / Σe_B5.

---

## V. Statistical validity

**The unit** is a deployment condition, one step on a distinct day. There are 10 near and 10 far conditions per network. The 2 noise replicates are nested and averaged within each condition.

**Inference:**
- percentile paired bootstrap over conditions (2,000 resamples, seeded);
- Holm over exactly 4 tests (H1 and H3 on each network). semiurb5's tests enter at p = 1, because they are NOT EVALUABLE;
- Clopper–Pearson bounds for "zero observed".

**Resolution.** With n = 10, a positive lower bound needs at least 4 discordant conditions.

**Dependence.** Conditions lie on distinct days, but share one network, one training realisation per replicate and one load realisation. Intervals are therefore conditional on those realisations, and say nothing about other feeders.

**Not supported by this design:** any population claim about LV feeders; any two-network claim (A2); any claim at a PV scale other than 1.40×; any claim about unbalanced (three-phase) behaviour.

---

## VI. Numerical results (rural3, near set, 10 conditions; unsafe = conditions with ≥ 1 unsafe replicate)

| Method | P1 unsafe | P2 unsafe | P3 unsafe | L0 unsafe | Median utilisation (safe records) | Mean AC − predicted corner voltage, P1 / P3 (pu) |
|---|---|---|---|---|---|---|
| B0 70 % rule | 10 | 10 | 10 | 10 | — | — |
| B1 OLS | **10** | 2 | **1** | 0 (infeasible: e = 0) | 0.98 (P2, P3) | +0.0041 / −0.0006 |
| B2 ridge | **10** | **10** | **10** | 9 | — | +0.0046 / +0.0044 |
| B2m ridge + conformal | 10 | 10 | 9 | 9 | — | — |
| B2p ridge, proportional | 1 | 2 | 0 | 0 | 0.92–0.94 | 0.0000 / −0.0006 |
| **B3 structured NNLS** | **0** | **0** | **0** | **0** | **0.99** | −0.0013 / −0.0016 |
| B4box (Gupta box) | 8 | 8 | 8 | 6 | 0.94–0.95 | +0.0074 / +0.0083 (B2's model) |
| B4 robust ellipsoid | 0 | 0 | 0 | 0 | 0.73 / 0.68 / 0.57 / 0.61 | — |
| A exact linear, AC offset | 3 | — | — | — | 1.01 | — |
| A′ exact linear, learned intercept | 0 | — | — | — | 0.955 | — |

- **Severity:** B2's unsafe corners exceed V_max by +0.0044–0.0047 pu on average (worst +0.0069 pu, about 1.6 V on 230 V).
- **The far set:** 0 unsafe for every method in every regime (control D).
- **No failures:** 0 failed AC solves in any stage, and 0 monotonicity flags.
- **Oracle:** (V) binding on 10/10 near conditions. Its envelopes total 0.539–0.582 MW against 0.553–0.607 MW available.

**Hypothesis verdicts** (rural3, single network). Under A2, no formal two-network verdict of any kind, Supported or Rejected, is attainable. These are single-network verdicts reported under §15; the analysis reads §9's "both networks" as "rural3", a reading §15 does not itself authorise (it restricts only the Supported direction), and it is disclosed here:
- **H1 — Rejected.**
  - B2's P1 − P3 = 0.00, interval [0, 0], Holm p = 1.
  - The ±0.10 branch and the T = 768 small-data branch both fire (rates 1.00 / 1.00).
  - The small-data branch fires on the same ceiling: B2's rate is 1.00 at T = 192, 384 and 768, so nothing "fell".
  - The noise-only branch does **not**: at σ_v = 0.0005, P1 − P3 = 1.00.
  - Control C passed on rural3. It failed on semiurb5 by 0.0004, which carries no verdict.
- **H2 — Supported.**
  - A P1 cell with in-distribution MAE ≤ 0.001 pu and unsafe rate ≥ 0.30 exists: ridge/P1, MAE 0.00084, unsafe 1.00.
  - Spearman over the 9 model × regime cells is 0.43 (< 0.5; p = 0.25 at n = 9). The verdict therefore rests on a pre-registered threshold applied to a point estimate, not on an inference.
  - The NNLS model is both the most accurate in distribution (MAE 0.0003) and the only always-safe one. OLS is the least accurate (0.0019–0.0021), yet safe under P3.
- **H3 — Inconclusive.**
  - B4: 0/10 unsafe, Clopper–Pearson [0, 0.31].
  - **Against B2p** (the best simple policy; 9 jointly safe conditions): B4's median utilisation is 0.73 against 0.93, a difference of −0.20, so it is not Supported.
  - **Not Rejected either,** because B2p was unsafe on 1 condition.
  - CERT: NOT EVALUABLE (k = 0). §7 gates CERT on H1 not being rejected, so this read-out is descriptive only.
- **H4 — Decision equivalence** (P1 and P3). The random-alternative export spread is 0.008 (P1) and 0.031 (P3), with safety disagreement 0. Every alternative was unsafe.

---

## VII. Prediction versus decision

*All results in this section are for the voltage component of the envelope only. Under the full decision (control T), no envelope was unsafe (§I.1, F0).*

Yes, there was a large difference.
- The ridge model is 2.3× more accurate in distribution than OLS (MAE 0.0008 against 0.0019 pu), yet unsafe in 100 % of near-limit conditions.
- OLS under decorrelated PV is unsafe in 10 %.

**The mechanism.** The total-export LP decides *who* exports. It concentrates curtailment on the units the model believes are most voltage-sensitive, and lets the others export fully.
- A model that smears sensitivity across buses gets that ranking wrong in a systematic direction. Ridge does this: its per-unit error, relative to the true LinDistFlow sensitivities, is 0.86–0.90 in every regime, even though its aggregate at the remote bus is within 16–22 % (board refit, `docs/provenance/mission11_board_audit/board_refit_sensitivity.py`).
- The optimiser then reliably finds the allocations where the model underpredicts.
- **The direct evidence** is the same ridge model under two decision rules:
  - at the LP's allocation, the AC voltage exceeds the model's prediction by +0.0045 pu;
  - at the proportional allocation (B2p), the error is 0.000 / −0.0006 pu.
  - Both envelopes bind at a predicted corner of 1.100 pu, so the comparison is at equal predicted voltage.
  - B2p also exports 7 % less in total (0.525 against 0.564 MW in P1). Export level is not the explanation: B1 exports *more* than B2 (0.568 MW) at a smaller error (+0.0041), and B3 exports 99 % of B2's total (0.559 MW) at −0.0013.
- The test-day error says nothing about this, because the test day never visits the re-allocated corner.

---

## VIII. Physical safety

| Method | Unsafe records (of 60 per method across P1–P3) |
|---|---|
| B2 | 60 |
| B2m | 56 |
| B4box | 47 |
| B1 | 22 |
| B2p | 4 |
| B3 | 0 |
| B4 | 0 |

- **Totals on rural3's near set:**
  - B0, regime-independent: 10 of 10 conditions;
  - A: 3 of 10, at +0.0012–0.0013 pu, which is the linearisation error of an exact-slope model with an AC offset.
- **Where:** at remote customer buses of the feeder, under simultaneous at-limit export on the 10 sunniest deployment days.
- **How severe:** +0.001 to +0.007 pu above V_max = 1.10, i.e. up to about 1.6 V.
- **What caused them:** allocation-selected sensitivity error (§VII). Linearisation error is excluded as the cause by the A′ attribution, since A′ was unsafe on 0/10.
- **The 70 % rule** (B0) does nothing at these conditions, because availability (f ≈ 0.49–0.55 of rating) is already below 70 %.
- **Thermal:** under control T (thermal limits included), 0 voltage-unsafe and 0 thermal-unsafe in 40 records. The thermal module's approximation error had a p95 of 0.048, inside the 0.05 limit.

---

## IX. Strong baselines

*All results in this section are for the voltage component of the envelope only. Under the full decision (control T), no envelope was unsafe (§I.1, F0).*

**Topology-structured estimation solves the problem in this setting.**
- B3 uses known topology and non-negative line parameters, and no impedance values.
- **B3 also uses exactly measured reactive power** (protocol §7), which B1, B2, B2m, B2p, B4 and B4box do not. Part of its advantage is that extra channel, not topology alone. This study does not separate the two.
- It is safe in all four regimes at about 99 % of the oracle's export (about 98.6 % after the oracle-tolerance correction, §XIII), and slightly conservative (−0.0013 to −0.0016 pu).
- This is an established technique. **The research question, as posed, is largely answered by a known method when topology is known.**

**The textbook robust counterpart is safe but costly.**
- B4 is the bootstrap-calibrated ellipsoid.
- **Utilisation:** 0.57–0.73 of the oracle. Its cutting-plane solve was budget-limited and restored on every near record (gap 6–29 %), so the true robust optimum lies in a bracket with a median of [0.73, 0.79] in P1 (upper end not AC-scored).
- **Conservatism grows with excitation:** B4 is more conservative in P3 than in P1. P3's larger bootstrap radius reflects its larger refit spread; this is not interpreted further.

**The precedent's robust box is insufficient.** Gupta-style B4box was unsafe on 8/10. Its i.i.d. ±3σ intervals do not cover an error the optimiser selects.

**A simple decision rule nearly suffices.** Proportional allocation (B2p) is mostly safe (0–2/10) at 0.92–0.94, with a residual risk of up to +0.0014 pu.

**The conformal margin is insufficient.** The in-distribution conformal margin (B2m, median 0.0045 pu) was not enough. It covers prediction error on familiar operating points, not the error the optimiser selects.

---

## X. Decision identifiability

**Decision ambiguity among data-consistent models was small** (export spread 0.8–3 %), and the models were unanimous on safety. They were unanimously wrong.
- The danger here is **bias shared by the model class** (the ridge penalty, and smearing under a common design), not variance across plausible fits.
- Variance-based uncertainty checks (bootstrap ensembles, agreement certifiers) cannot see it.

**The extreme alternatives** along the weakest-excited directions collapsed onto the centre. The non-negative-ridge centre has many exactly-zero slopes, so admissibility forbids any move. They carry no information; §8 had given them no verdict.

**Parameter ambiguity had little operational consequence *between* plausible models. The model class's shared error had a large one.**

---

## XI. Novelty assessment

| Claim | Category |
|---|---|
| Correlated injections ill-condition OLS sensitivity estimates (B1, P1 against P3) | Reproduction of known findings |
| Topology-structured estimation is accurate | Reproduction |
| Robust is safer and more conservative | Reproduction |
| An envelope optimiser selects allocation-specific error that in-distribution accuracy, conformal margins, Gupta-style boxes and agreement certifiers all miss; quantified on a SimBench feeder (§VII, §IX, §X) | **New empirical benchmark evidence** for the DOE setting. The mechanism is the known optimiser's curse. |
| F0 — thermal-first in all six SimBench LV networks at the registered scale, masking the voltage-identification question | New empirical benchmark evidence. It is a property of the benchmark and its scale, and may not hold for real long rural feeders. |
| A new algorithm | None |
| "Correlation-driven envelope unsafety" as a distinct research gap | **Unsupported**: the registered contrast was null, and a known method solves it given topology |

*Novelty is assessed against the targeted search of protocol §0, in which Kumarawadu et al. 2025, Valverde et al. 2018, Zhang et al. 2018 and Mittal et al. 2023 were read in abstract or metadata only. The optimiser's-curse references in §II are cited from memory and NOT CHECKED.*

---

## XII. Publication potential

**What could become a working paper.** A short benchmark note: *"Estimate-then-optimise export envelopes select their own errors: evidence from SimBench."* Its contents:
- the optimiser's-curse evidence;
- the failure of in-distribution accuracy, conformal margins and agreement checks;
- the structured-estimation remedy;
- F0.

**What is missing for a credible peer-reviewed paper:**
- more than one evaluation network, including real or voltage-limited feeders;
- three-phase unbalanced modelling (Mission 10 showed that balanced sensitivities can mislead);
- realistic load variability, and more training data;
- topology or parameter uncertainty for the structured baseline (its main real-world weakness);
- a decision-focused or allocation-robust method, compared fairly against B3;
- external replication.

No acceptance prediction is made.

---

## XIII. Engineering quality

**Tests** (after the correction round; zero power flows; synthetic, round-valued fixtures only):
- module suite: 255 passed (after the publication freeze; 241 after the correction round);
- whole repository (`pytest tests analysis`): 1,040 passed;
- clean public export (HEAD plus the exact Mission 11 allowlist and the strategy report, without local artefacts): 853 passed and 10 skipped. The skips are artefact-dependent tests (6 for Mission 11, 4 earlier held-data tests), which skip only when every required file is absent. A partial artefact set fails, and so does any artefact that no longer matches the summary's pinned sha256 (board check).
- Ruff is clean on every Mission 11 file.
- **Reproducibility:** the summary JSON and all six figures regenerated byte-identically from copied artefacts in a clean copy (board check).

**AC validation:**
- 0 failed solves;
- the corner-monotonicity check is clean (0/32 interior points flagged);
- the e = 0 vertex is safe at every condition.

**Pre-experiment QA:** AKK-58, PROCEED WITH CORRECTIONS. All four blockers were addressed before scoring; the drafting record lists each disposition.

**Board-found defects:**
- **storage dispatch:** an unspecified default, fixed before scoring;
- **cut budget:** a row-counted cut budget that would have mis-labelled converged B4 problems as degenerate (revision 2.2);
- **read-out:** a read-out that used B2's model for every method's predicted voltage. It was fixed before rural3; the semiurb5 artefact keeps the defect, which is descriptive only.

**Amendments after the first counted solve:**
- **A1:** a far-candidate day rule.
- **A2:** semiurb5 NOT EVALUABLE.
- **A3:** a resume path after an adapter SIGTERM killed the rural3 physics. The killed L0 attempt is charged as 480 solves, an upper bound.

**Post-experiment QA:** Paperclip AKK-68, **PASS WITH LIMITATIONS**: 0 blockers, 3 major, 4 minor and 4 documentation findings. All 11 were applied in one correction round (the board for the documentation, AKK-69 for code, tests and figures). No verdict or headline number changed.

**Known limitations:**
- **Ledger gap:** a latent ledger gap (solves banked before a write-once refusal) that this run never triggered.
- **Figures:** figure F's tick labels overlapped, and figure B's intervals used n = records instead of §9's n = conditions. Both were fixed in AKK-69; figures A, C, D and E are byte-identical to before.
- **Publication freeze (AKK-70 to AKK-73):** the ODbL notice was embedded in every figure, and the header layout of B, D and F was fixed (a uniform vertical shift; no data element changed). A test now fails on any artefact that no longer matches its pinned sha256. A focused independent check (AKK-73) found wording and packaging issues only, and no scientific statement changed.
- **B4 fallbacks:** B4 always used its restoration fallback.
- **Oracle tolerance:** the oracle's feasibility test uses a zero tolerance rather than §13's +0.001 pu. So on all 10 conditions the sequential LP, already converged to about 1e-7 pu exceedance, was sent to the bisection back-off, which returns up to 0.4 % less export. Every utilisation figure is therefore about 0.4 % high, which is why A reaches 1.01. No verdict moves: H3's comparison shares the denominator.
- **Bootstrap p resolution:** with 2,000 resamples the bootstrap p cannot resolve below 0.0005; reported zeros mean p < 0.0005.
- **Unchecked change:** the claim that A3's resume change touches no method code rests on the Implementer's function-level diff summary and the unchanged test suite. The pre-change file was not retained, so a line diff was not possible.
- **Order-dependent hygiene tests:** two hygiene tests checked the session-wide `sys.modules` for pandapower and failed when run after other suites (board finding during the clean-copy check). Fixed in the correction round (AKK-69) with `ast`-based import checks.

---

## XIV. Computational record

| Item | Value |
|---|---|
| New AC solves (ledger) | **6,246** of the 8,000 ceiling |
| Board design audits | 106 (38 of them invalid or diagnostic, counted anyway) |
| semiurb5 | 2,276 |
| rural3 | 3,864 |
| L0 charged twice | +480 (the SIGTERM upper bound) |
| Workers | 1, sequential |
| Wall-clock of the solving stages | about 5 minutes in total. Each 480-step regime took about 6 s; the rural3 envelopes stage 77 s |
| CPU | well under the 3 CPU-hour cap |
| Storage | about 10.6 MB of local artefacts (runs 8.1 MB, results 2.4 MB, figures about 0.1 MB), against a 1 GB cap |
| Reused caches | none (fresh physics). Phase 4's registered PV scale and the GridPulse network builders were reused |
| Paid or cloud infrastructure | none |

---

## XV. Artefacts

**Code:** `analysis/export_envelope_shift/`:
- `envelope_core.py`
- `envelope_lp.py`
- `stage_a.py`
- `analyse.py`
- `svgplot.py`

**Tests:** `analysis/export_envelope_shift/tests/` (4 files).

**Documentation:**
- `analysis/export_envelope_shift/stage_a_protocol.md`;
- this note;
- `docs/provenance/mission11_board_audit/` (audit scripts and outputs).

**Figures:** `analysis/export_envelope_shift/figures/fig_a…fig_f*.svg`:
- A: excitation spectra;
- B: prediction against decision;
- C: safety against utilisation;
- D: correlation strength;
- E: model disagreement;
- F: negative controls.

**Local only:**
- `analysis/export_envelope_shift/results/*.json`;
- `analysis/export_envelope_shift/runs/*.npz`;
- the caches `analysis/export_envelope_shift/__pycache__/`, `tests/__pycache__/` (git-ignored) and the empty harness folders `.claude/.cc-writes/`, `results/.claude/.cc-writes/`.

These are SimBench-derived (ODbL 1.0 / DbCL 1.0).

---

## XVI. Learning notes for the project owner

**Why correlated PV makes sensitivity estimation hard.**
- A smart meter at bus k sees the sum of every bus's influence. If the 27 rooftops on rural3 rise and fall together (P1: pairwise correlation 0.83), the data contain almost one "direction" of PV movement. Regression can tell how voltage responds to *all PV together*, but not to *this rooftop rather than that one*.
- OLS then produces wild per-unit coefficients: 45 % of its 3,186 PV sensitivities came out negative in P1 (board refit, `board_refit_sensitivity.py`), physically impossible on a radial feeder.
- Household loads helped here, because each house's load varies independently. That is why P1's design was still well-posed (condition number 276) while L0, with identical native load profiles, was singular.

**Why low prediction error does not guarantee safe decisions.**
- The test day looks like the training days. The envelope optimiser deliberately goes somewhere new: it curtails a few "expensive" units fully and lets the rest export.
- The ridge model predicted the test day to 0.0008 pu. At the optimiser's chosen corner it was 0.0045 pu too optimistic, and it was too optimistic in the same direction every time. **The optimiser is an adversary to the model's errors.**

**Why physically accurate envelopes matter.**
- **The example:** the same ridge model, used with a dumb rule (everyone curtails by the same fraction, B2p), was safe 90–100 % of the time, because that rule never asks the model about allocations it cannot judge. The clever rule (maximise total export) was unsafe 100 % of the time.
- How much information a decision needs depends on the decision.

**How robust optimisation differs from point prediction.**
- B4 does not trust one coefficient vector. It requires safety for every vector in a data-consistent ellipsoid. It was always safe, but gave up about 27–43 % of the export.
- The Gupta-style box (B4box) was not robust enough, because its uncertainty set was built for random error, not for error selected by the optimiser.

**Why distribution shift matters.**
- The shift here is created by the decision itself. Training data never contain the envelope's corner, so the model is being asked to extrapolate.
- Correlation decides *how far* that extrapolation is for OLS: P1 was unsafe 10/10, P3 1/10.

**Why knowing less does not always mean deciding worse.**
- B3 knew the *wiring diagram* (which bus is downstream of which line) and saw reactive power, but not a single impedance. That made it the most accurate and the safest model (0/40 unsafe, about 99 % utilisation).
- Structure, together with the reactive-power channel, beat data volume. This study does not separate the two.
- And in the full problem (control T), knowing nothing about voltage sensitivities did no harm at all, because the thermal limit decided.

**Where AI is genuinely useful.**
- **Learning:** estimating physically structured parameters from meter data (B3 is learning).
- **Detecting:** when a decision leaves the support of the data (the corner-distance diagnostics).
- **Validating:** checking decisions against a physics simulator, as this study did with every envelope.
- **Not useful:** an unconstrained black-box regression handed to an optimiser.

---

## XVII. Research direction decision

**PIVOT.**

**Why not GO.**
- The registered hypothesis, that PV correlation drives envelope unsafety, failed its primary test on the only evaluable network (H1 Rejected).
- A known method (B3) removes the failure when topology is known.
- F0 shows that in the benchmark the question is masked by thermal limits.
- Continuing would mean rescuing the hypothesis by redefining it.

**Why not STOP.**
- Two findings make a different, sharper question worth asking:
  1. thermal limits, not voltage, bind first in every SimBench LV network at the registered scale (F0);
  2. an envelope optimiser reliably selects whatever error its binding model contains (§VII).
- Mission 10 showed that cable **rating** errors are effectively undetectable from voltage data. Together these point at a question the evidence makes urgent: *the binding constraint is the one that smart-meter voltage data cannot inform.*

**The strongest justified alternative.** Direction 9 of the strategy assessment, sharpened:

> *Decision-sufficient thermal information for LV export envelopes.* When thermal limits bind and ratings are uncertain (cable type or rating records wrong), does an export-maximising envelope select the allocations that overload the mis-rated branch? Which information source makes the envelope safe at the least utilisation cost: asset records, substation current measurements, or conservative defaults?

**Design principles carried over from this Stage A:**
- score the allocation-selected corner, not in-distribution accuracy;
- always include a proportional rule, a structured estimator, and a robust set as baselines;
- report agreement-based certifiers against a random-fallback control;
- choose networks by an audit of which constraint binds, before scoring.

**This is not executed.** A registered protocol would come first, in a separate decision by the owner.

---

## XVIII. Manual Git review

The exact allowlist and the local-only list are in the final report. In summary:
- **Code, tests and the protocol:** public candidates.
- **This note and the board-audit provenance:** public candidates. They quote aggregate SimBench-derived figures only.
- **Figures:** owner decision (Produced Works of ODbL data; attribution would be required).
- **`results/` and `runs/`:** local only.

No staging, commit, push, branch or history change has been made by any agent.
