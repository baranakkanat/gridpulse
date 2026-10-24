# Research proposal — Calibrated detection of single-cable asset-record errors under sparse and imperfect LV measurements

**Status:** design document, revised after one independent QA review (Paperclip AKK-43). It has not been registered or committed; the owner decides. Only the exploratory §10 pilot has run.
- Post-pilot edits: §3.2, §6 items A and B, §9 K2 and §10.1.
- They record the pilot's QA (AKK-46) and the data-terms check. No hypothesis, criterion or threshold was changed.
- **Authorship:** drafted by the GridPulse Reviewer (AKK-42). The board applied QA's corrections C-1–C-10 and three consistency edits they imply:
  - the 36-cell tolerance in H1a;
  - H1a no longer claims validity under the MV swing;
  - H1b's falsification matches its two bars.
- **Evidence base:** the exploratory analyses in `analysis/phase9_followup/` (zero new power flows; QA verdict **PASS**):
  - `calibration.py` `b3193b1a…` → `results/calibration.json` `894079d4…`;
  - `tradeoff.py` `2c8f9e5d…` → `results/tradeoff.json` `f11635f6…`;
  - `common_mode.py` `f42e7b54…` → `results/common_mode.json` `d0831ab2…`;
  - 55 tests at that QA; now 56, after one test was split so that its part needing no held data runs in a public clone.
- **Data dependence:** these analyses read the Phase 9 artefacts that are held locally and untracked (`analysis/phase9/results/phase9_inputs.json`, `phase9_results.json`, `analysis/phase9/sweep/`). Their own `results/` files are derived from them and are held locally too.
- **Phase 9's registered failures R3, R5 and R7 are unchanged.**


**Scope:** one study, not a roadmap and not a "Phase 10".

---

## 1. Problem and motivation

Phase 9 (commit `19d94ce`; registration `docs/provenance/phase9/phase9_registration.md` **(V)**, results `docs/phase9_results.md`, 511 lines **(V)**) asked whether a day–night voltage-residual contrast at sparse, pre-committed meters detects a single cable whose recorded resistance is wrong by ×1.5. It established, on 89 candidate cables across SimBench `1-LV-semiurb4--2-sw` (39 candidates) and `1-LV-urban6--2-sw` (50 candidates) **(V, registration §3)**, with 25 frozen Phase 6 meter placements and noise-free Δ:

- Coverage at σ = 0.01, K = 2 is **4.7 %** and **4.6 %** of (cable, rule) pairs; at σ = 0.005, **9.6 %** and **5.4 %** **(B)**.
- **P(detect | no meter downstream of the cable) = 0** **(B)**.
- Localisation by night sign holds only for cables whose downstream flow reverses; R1/R2 fail at σ = 0.005 at non-reversing cables **(B)**.
- A wrong length behaves like a wrong resistance, to within 1.2–2.2 % **(B)**.
- A diurnal systematic meter error of 0.01 σ **doubles** false alarms **(B)**.

Three registered rules failed, stated exactly as registered:

- **R3 failed.** Per-cable Spearman of (S_l, max over downstream(l) of |k|) was **0.886** and **0.863**, against a registered threshold of **0.9** **(V,** `docs/phase9_results.md:244`**)**.
- **R5 failed.** The held-out magnitude ratio m(b\*)/m_pred for `1-LV-rural2--2-sw` was **0.490**, outside the registered band **[0.50, 0.90]** **(V,** `docs/phase9_results.md:289`**)**.
- **R7 failed.** Family-wise false alarms under truth = nominal were **0.064–0.078**, against a registered **0.05** **(B;** the failure is recorded at `docs/phase9_results.md:100-101,196` **(V))**.

An exploratory, zero-new-flow follow-up lives untracked in `analysis/phase9_followup/` (`calibration.py`, `tradeoff.py`, `common_mode.py` and `results/{calibration,common_mode,tradeoff}.json`) **(V, files present; sizes 391 kB / 80 kB / 1.70 MB)**. It is not documented in `docs/` **(V)**. Its findings **(B)**:

1. **R7 is explained, not merely observed.** The registered floor divides by a median step count; E[1/n_d] > 1/median(n) inflates the true sd by ≈ 6 %, the 1-day reporting delay adds 0.3 %, random missingness 0.02 %. Analytic predictions match Monte Carlo and the observed rates.
2. **Calibration is solvable; power is not bought by it.** Of C0 (registered floor), C1 (exact plug-in floor, σ known), C2 (day-level studentised t on the per-day contrasts, σ unknown), C3 (Newey–West HAC): under i.i.d. noise C1 and C2 reach 0.049–0.053; under **within-day AR(1)** noise C0 and C1 collapse to **0.25–0.91** while **C2 stays at 0.048–0.051**; C3 is anti-conservative at 0.06–0.08 even under i.i.d. noise. Under **across-day dependent diurnal error, all four are invalid**.
3. Coverage at a calibrated 5 % false-alarm rate (σ 0.01, K = 2) is 0.114/0.114/0.113 (semiurb4) and 0.084/0.084/0.085 (urban6) for C0/C1/C2 — calibration buys **validity, not power**.
4. **The binding limitation is placement, not statistics.**
   - **Partition** of **all** (cable, rule) pairs at K = 2, σ_tot = 0.01, against the C1 threshold, as placement (no meter downstream) / asset-physics / signal below threshold / detected:
     - semiurb4: **67 / 6 / 23 / 5 %**;
     - urban6: **78 / 10 / 7 / 5 %**.
   - **Checks:** the ordering absorbs no otherwise-detectable pair (`asset_physics_pairs_above_threshold = 0`), and the downstream-restricted peak agrees with the registered C_meter on every pair.
5. **Common-mode MV swings are cancellable.** The raw contrast under a Phase 8 `mv_daily` MV swing is 4.4–5.3e-3 at every bus, so false alarms are **1.0**. Referencing to the LV busbar, k(b) − k(busbar), cancels **97.8–98.3 %**, leaving ≤ 1.2e-4, and false alarms fall to 0.052–0.090. Fault signal is retained: the busbar |k| under faults is ≤ 4.4e-6.
6. The registered R7 clause (pooled Wilson lower bound ≤ 0.05, registration §9 R7), combined with the follow-up's own pre-stated rate and conservatism limits, is **not reliably attainable**: pooled trials share one noise realisation across 25 rules, so they are correlated, and C1/C2 miss by 0.0003–0.0009. **That rule stands as written.** Any successor must use independent-trial intervals.

**The gap this study closes.** Phase 9 produced an upper-bound coverage number from a detector whose false-alarm rate was wrong, on two synthetic German-convention networks, with no dependence or common-mode stress in the null. The follow-up identified a candidate fix but evaluated it post-hoc on the same data. What does not yet exist is a **detector fixed in advance, whose size is measured under dependence, missingness, delay, diurnal bias and MV swings with independent replicates, and whose power is measured on real LV feeder topologies it was not designed on.**

---

## 2. Hypotheses

Let α = 0.05 family-wise. Candidate detector: **C2-ref**, the busbar-referenced, day-level studentised contrast (§3).

### H1 (primary, falsifiable) — C2-ref is calibrated and competitively powerful

**H1a (size).** On independent LV feeder topologies, C2-ref holds the family-wise false-alarm rate at 0.05 under unknown σ, unequal daily step counts, 5 % whole-day missingness, a 1-day reporting delay, and within-day AR(1) dependence up to ρ = 0.9. The common-mode MV swing and meter-specific diurnal error are reported as tolerance axes (§6), not claimed.

- **Acceptance**: (i) the rate pooled over rules *and over primary cells* has a 95 % Clopper–Pearson interval whose lower bound ≤ 0.05, and per primary cell the same lower-bound clause holds in **at least 33 of the 36** primary cells. This is a pre-stated tolerance: the clause is a 2.5 % one-sided test per cell at any replicate count, so an exactly calibrated detector fails ≈ 0.9 cells in expectation and ≥ 4 cells with probability 0.012; (ii) at most **2 of 25** rules have a per-rule CP lower bound above 0.05; (iii) **no** per-rule point estimate exceeds **0.08**.
- **Falsification:** the pooled-over-cells clause (i) failing, or more than 3 of the 36 primary cells failing the per-cell lower-bound clause, or any primary cell violating (ii) and (iii) together. Tolerance (ii) exists because with 25 rules at a true rate of 0.05 and independent replicates, some per-rule lower bounds exceed 0.05 by chance — independent replicates make the interval honest; the cell-axis tolerance above, not independence, is what makes the conjunction attainable.

**H1b (power).** At a critical-value multiplier calibrated to an empirical 5 % in the matched null cell, C2-ref retains **≥ 0.85** of the coverage of an oracle-calibrated detector (C1 with σ known, i.i.d. noise, no swing) on the same cables **at the registered substation accuracy σ_bb = 0.002 (σ_bb/σ_b = 0.2, `noise_study.CONDITIONS[...].sigma_v_substation`)**, and **≥ 0.60** in the σ_bb = σ_b sensitivity cell.

- **Prediction (H):**
  - ≈ 0.99 at σ_bb = 0.2 σ_b. The follow-up measures `W6_coverage_retention = 1.00` in all four noise-free cells, and a C2/C1 calibrated-5 % coverage ratio of 0.994–1.004.
  - ≈ 0.70 at σ_bb = σ_b. This comes not from the √2 sd factor directly but from the measured coverage-versus-threshold scaling, which is close to inverse in this regime: 46/975 detected at σ = 0.01 against 94/975 at σ = 0.005, exponent ≈ 1.03, so a √2 threshold increase gives ≈ 2^−0.515.
- **Falsification:** a point estimate below the applicable bar (0.85 at the registered σ_bb, 0.60 in the σ_bb = σ_b cell), with the cluster-bootstrap upper bound also below it.

### H2 (secondary) — no off-downstream leakage

On ENWL feeders, P(detect | no meter downstream of the errored cable) ≤ α, under the **network-level** alarm statistic of §3.3: max |T| over all K meters of the configuration, as in Phase 9's registered C_meter. Stated against the per-cable K_eff rule this quantity is 0 by construction, because an empty `config ∩ downstream(l)` means no statistic is examined; only the network-level statistic makes it a measurement. Phase 9's 0 was measured under that statistic, and the follow-up finds the two statistics never disagree on Phase 9's data.

- **Acceptance:** the one-sided 95 % CP upper bound ≤ 0.05.
- **Falsification:** upper bound > 0.05. Phase 9 measured exactly 0 on SimBench **(B)**; leakage on real feeders would break the localisation reading, so this is a genuine transfer test, not a formality.

### H3 (secondary) — a *necessary-condition* screenability map

Define Z(l, rule, K) = 1 iff config(rule, K) ∩ downstream(l) ≠ ∅. Z is proposed as an **exclusion screen**, not a predictor.

- **Acceptance:** sensitivity ≥ 0.95 (at least 95 % of detected pairs **under the network-level statistic** have Z = 1; under the K_eff rule, sensitivity is 1 by construction). Positive predictive value is **reported only**, with the pre-stated expectation that it is low (oracle single-meter coverage was 0.12–0.18 **(B)**).
- **Falsification:** sensitivity < 0.95.
- **Why this is not R5 or R3 again.** R5 failed as a *calibrated point prediction* (0.490 against [0.50, 0.90]); R3 failed as a *monotone rank claim* at ≥ 0.9 (0.886, 0.863). H3 claims neither a scale factor nor a rank ordering — only that a binary topological condition is **necessary** for detection. Note explicitly: the screening score S_l is **not** part of H3. S_l = 0 on 18 of 39 and 23 of 50 cables **(B)**, yet R3's shortfall was attributed to load-driven contrasts at cables with no downstream PV **(**`docs/phase9_results.md:270-273`, labelled HYPOTHESIS there **(V))** — so S_l = 0 does not imply non-detection. S_l and a load-inclusive variant S′_l = R_l·(P_l^PV + P_l^load-swing) are **reported as stratifiers only**, under no threshold.

---

## 3. Detector definition

### 3.1 Statistic

Measured voltage at meter bus b, retained day d, step t:

  y(b,d,t) = v(b,d,t) + ε(b,d,t) + β_b + A·g_b·s(d,t)

with v the true voltage, ε zero-mean reading noise, β_b a static per-meter bias, and A·g_b·s a diurnal systematic error (Phase 9 control 2 shapes: square primary, sinusoid variant **(V, registration §10)**). The residual against the asset-record model v̂ is Δ = y − v̂.

Per-day contrast at b over the day's n_d valid daylight and m_d valid night steps:

  c_d(b) = mean_{t ∈ D_d} Δ(b,d,t) − mean_{t ∈ N_d} Δ(b,d,t)
     = k_true(b,d) + (mean_D ε − mean_N ε) + **0·β_b** + A·g_b·(mean_D s − mean_N s)

The static bias cancels **exactly** — the original Phase 9 motivation. The diurnal term does not.

**Busbar reference:** c_d^ref(b) = c_d(b) − c_d(busbar).

**Statistic:** with S the retained day set, |S| days,

  c̄^ref(b) = |S|⁻¹ Σ_{d∈S} c_d^ref(b),  s_ref²(b) = (|S|−1)⁻¹ Σ_{d∈S} (c_d^ref(b) − c̄^ref(b))²,
  **T(b) = c̄^ref(b) / (s_ref(b)/√|S|)**, referred to t_{|S|−1}.

### 3.2 Variance derivation (meter plus busbar noise)

Under H0 (correct asset record), with meters' reading noise mutually independent and i.i.d. within a day:

  Var(c_d(b)) = σ_b²(1/n_d + 1/m_d)
  **Var(c_d^ref(b)) = (σ_b² + σ_bb²)(1/n_d + 1/m_d)**

because c_d(b) and c_d(busbar) are independent. With σ_bb = σ_b this is a **factor-2 variance**, i.e. a **√2 ≈ 1.414 sd inflation** — the price of cancelling common-mode error. With a higher-grade substation instrument at σ_bb = 0.3 σ_b the inflation is only √1.09 = 1.044, so σ_bb/σ_b is a design axis, not a constant. This repository actually registers σ_bb = 0.002 against σ_b = 0.01, i.e. σ_bb/σ_b = 0.2 and an inflation of √1.04 = 1.020; at that value the follow-up measures no coverage loss at all. The √2 figure is the worst case of the design axis, not the expected cost. *Ratio versus absolute (fix at registration):*
- §6 defines the axis as the ratio σ_bb/σ_b, so at σ_b = 0.005 the 0.2 cell is σ_bb = 0.001.
- The registered absolute σ_bb = 0.002 is ratio 0.2 only at σ_b = 0.01; at σ_b = 0.005 it is ratio 0.4.
- The pilot used the ratio. H1b's "registered σ_bb" bar must name which of the two binds.

If readings are AR(1) with parameter ρ within the day, the bracket becomes
 (1/n_d)[1 + 2Σ_{j=1}^{n_d−1}(1 − j/n_d)ρ^j] + (the same in m_d),
which is **unknown in deployment**. This is exactly why C1's exact plug-in floor collapses to 0.24–0.90 under N2 **(B)**: it assumes ρ = 0.

**C2-ref plugs none of this in.** It estimates Var(c^ref) on the day axis, so any within-day dependence structure, any n_d/m_d heterogeneity, and any missing-step pattern is absorbed into s_ref automatically.

**Signal retention.** The referenced signal is k_true(b,d) − k_true(busbar,d). Under a single-cable LV error the busbar |k| is ≤ 4.4e-6 p.u. **(B)**, negligible against detection thresholds ≈ 3.5e-4 p.u. **(B, registration §9 A\*_fa ≈ 3.5e-4 (V))**. A common-mode MV swing enters all LV buses nearly equally and cancels 97.8–98.3 % **(B)**.

**Honest caveat.** Under H0 the c_d^ref are independent and mean-zero but **heteroskedastic** (unequal n_d, m_d), so the t reference is **asymptotically**, not exactly, valid; its accuracy is O(1/|S|). The observed 0.048–0.053 **(B)** is empirical evidence at |S| = 145, not a proof. The study therefore **measures** size and does not assert it. Validity under **across-day** dependence is not claimed at all (§9).

### 3.3 Multiplicity rule

- **Level 1, meters within a configuration.** Per-cable test: alarm iff max over b ∈ config(rule,K) ∩ downstream(l) of |T(b)| ≥ t_{|S|−1}(1 − α/(2·K_eff)), with K_eff = |config ∩ downstream(l)| — the number of statistics actually examined. Network-level alarm (kept for B0-comparability with Phase 9's rule): the same with K in place of K_eff over all K meters.
- **Level 2, cables.** With L candidate cables per feeder, the **binding** rule is Bonferroni at per-cable level α/L. A **descriptive** variant applies Benjamini–Hochberg at FDR 0.05 to the L per-cable p-values p(l) = min(1, 2·K_eff·[1 − F_{t,|S|−1}(|T|)]). Declared caveat: the nested downstream sets make these p-values strongly dependent, and the verified citation (Benjamini & Hochberg 1995) does not cover that dependence structure; no stronger dependence-robust FDR result is cited because none on the verified list covers it. BH is therefore **never** the binding rule.
- **Level 3, feeders.** Population statements come from the cluster bootstrap (§7), not from further correction.

---

## 4. Baselines

| ID | Detector | Role |
|---|---|---|
| **B0** | Registered Phase 9 floor C0: alarm on \|k̂\| ≥ z_K·F_C,real with the median-step-count floor | The failing status quo (R7: 0.064–0.078 **(V)**) |
| **B1** | Exact plug-in floor C1, σ²Σ_S(1/n_d + 1/m_d)/\|S\|², σ **known** | Oracle-information lower bound on achievable size |
| **B2** | Normalised-residual / level test on m(b) rather than the contrast, in the Lin & Abur 2018 idiom | The naive prior-art lower bound |
| **B3** | **Strongest:** Peppanen-style regression of the busbar-differenced residual on the downstream branch current **modelled from the asset record under test**, not from the true network, so that B3 is a fair competitor and not an oracle (an oracle-current variant is reported separately as an upper bound), and, as a variant, on downstream power, studentised with Newey–West HAC and with a self-normalised statistic | The binding comparison |
| **B4** | Conformal calibration of the contrast on healthy reference periods (split-conformal p-values, plus block-permutation under dependence) | Optional; exchangeability caveat below |

**Which must be beaten, and by how much.**

1. **Against B0 and B1 — validity, decisively.** In the N2 (ρ = 0.9) cells where B0/B1 exceed 0.20 **(B)**, C2-ref's worst per-rule false-alarm point estimate must be ≤ **0.08**. Failure here kills H1a.
2. **Against B2 — size and power.** C2-ref must dominate B2 on both: a calibrated size per H1a, and coverage at calibrated 5 % not below B2's. B2 is expected to be weaker because the level m does not cancel static bias **(H)**.
3. **Against B3 — non-inferiority, the binding rule.** With both calibrated to an empirical 5 %, C2-ref's ENWL coverage must be within **0.02 absolute** (≈ 20 % of the 0.084–0.114 coverage scale it is compared against; this is a relative-scale margin, not a conventional small absolute one) of B3's (paired cluster-bootstrap 95 % CI on the difference excluding −0.02). **If B3 is calibrated and beats C2-ref by more than 0.02 absolute, the study concludes B3 is the better detector** and C2-ref's claim is reduced to one of simplicity and assumption-economy. This is a pre-registered outcome in which the proposal's own candidate loses.
4. **B3's size must be reported, not assumed.** C3 (Newey–West on the day axis) was anti-conservative at 0.06–0.08 even under i.i.d. noise **(B)** — the small-bandwidth HAC size distortion of Kiefer & Vogelsang 2005 and Shao 2015. B3 therefore runs in both a HAC form and a self-normalised form, and if neither is calibrated, B3 is reported as *more powerful but invalid* rather than as the winner.
5. **B4 is exploratory only.** Conformal p-values give exact finite-sample FDR control with BH (Bates et al. 2023) **under exchangeability**, which a diurnal, seasonal, load-driven residual series violates across days; block-permutation (Chernozhukov et al. 2018) weakens but does not remove the requirement. B4 is reported with its violated assumption stated, and cannot satisfy H1 by itself.

---

## 5. Data and independence

**Development half (selection, then freeze).** SimBench `semiurb4` and `urban6`, development-half day axis, **145 retained days (144 after the 1-day delay)**.
- It is derived from the SimBench profiles alone (`grid_study.period_days('development')` and `phase9_sweep.daylight_masks`, as in `analysis/phase9_followup/calibration.py`).
- It gives per-day daylight and night **step counts and masks only: no per-day voltage means and no fault signal**. That is sufficient for all size, false-alarm and critical-value work, which is analytic under truth = nominal, and insufficient for any power quantity.
- The 99 `.npz` per-day-mean artefacts (7.3 MB, under `analysis/phase9/sweep/`) are **evaluation-half** (registration §2 fixes the Phase 9 axis as `period_days('evaluation')`) and are not part of the development half. Everything is selected and frozen here: the statistic, the reference bus, K_eff, retention, critical values, the stress grid, the seed scheme, the decision rules. The frozen registration's sha256 is recorded **before any ENWL number is computed**, mirroring Phase 9 Stage 0 **(V, registration §12)**.

**Evaluation half (independent benchmark).** ENWL "Low Voltage Network Solutions" network models — 25 real UK LV networks, 128 feeders, OpenDSS text with per-km R/X, lengths, 0.23 kV single-phase loads and an 11/0.416 kV transformer **(B, board scouting; nothing downloaded)**.

**Held out / excluded.**
- ENWL **network 1 feeder 1** is reportedly identical to the IEEE European LV Test Feeder **(B)**, which pandapower 3.5.6 ships as `ieee_european_lv_asymmetric` — 906 LV buses, 55 single-phase loads, one 0.8 MVA MV/LV transformer at 0.416 kV **(V, installed package docstring)**. It is used **only** as the free converter-correctness check and the compute probe, and is **excluded from every evaluation statistic**, because it is already inspectable in the venv.
- All 128 remaining feeders are unexamined at the time of freezing **(NC — I have not opened any ENWL file; nothing is downloaded)**.

**Contamination that remains, stated plainly.**
1. The detector *family* — day–night contrast, busbar referencing, day-axis studentisation — was chosen after seeing Phase 9 and its follow-up on SimBench. ENWL therefore tests **transfer of a fixed detector**, not discovery. The study is confirmatory for H1–H3 and exploratory for nothing else.
2. The noise and stress models are the same analytic family on both halves. ENWL results are independent evidence about **topology and geometry**, and **not** about whether the noise model resembles reality.
3. SimBench's six networks are all examined data **(V, registration §15)**; no new SimBench claim is made.
4. **SimBench has no unused half left for power.** Every coverage, calibrated-5 % and retention number in the follow-up was computed on the evaluation-half artefacts. Power-dependent choices (the H1b threshold, the calibrated multipliers c*, the critical values) therefore cannot be frozen on an unexamined SimBench half; they are frozen on examined data and are declared as such. Only the size and false-alarm machinery is frozen on genuinely unused material.

**The single-day profile limitation.** ENWL supplies per-feeder 288-point 5-min single-day load shapes (with some profile paths pointing at missing files) plus separate summer/winter load, summer PV and winter EV/HP/µCHP profile workbooks; **no measured voltages** **(B)**. A multi-day series must be synthesised:

- Resample to 96 steps/day to match Phase 9's step grid and cut per-day solve cost 3× (stated as a deviation from the native 5-min resolution).
- Build D synthetic days as: per-customer daily shape × a day-level multiplicative scale drawn from the seasonal workbook profiles, × a within-day AR(1) multiplicative perturbation; PV from the summer PV profile scaled by a day-level clear-sky index; day/night masks derived network-wide from PV availability, as in Phase 9 **(V, registration §2)**.
- **Why acceptable:** H1's size claim depends on the **day-to-day variance structure of the contrast** and on the **topology** that maps a cable error to meter voltages — not on load realism. H2 and H3 are purely geometric.
- **Why not acceptable, and said in the paper:** a synthesised day axis cannot evidence **real** across-day dependence or **real** diurnal meter error. The size results are size **under a stipulated stochastic model on real topologies**. No open dataset pairs measured smart-meter voltages with feeder topology **(B)**, so this limitation is not removable within this study. H1a's claim is worded accordingly and never as a deployment false-alarm rate.

---

## 6. Experimental design

**Stress and condition grid.** σ_tot ∈ {0.005, 0.01} co-primary (0.003, 0.02 sensitivity); K ∈ {1, 2, 4}; noise N1 i.i.d., N2 AR(1) ρ ∈ {0.5, 0.9}, N3 across-day dependent diurnal (**reported, expected to fail**); MV swing off/on; meter-specific diurnal amplitude A/σ ∈ {0, 0.01, 0.03, 0.1}; whole-day missingness 0.05; 1-day delay on/off; σ_bb/σ_b ∈ {0.2 (registered), 0.3, 1}. **Primary cells** (binding for H1a): σ(2) × K(3) × {N1, N2ρ0.5, N2ρ0.9}(3) × swing off × A/σ = 0 × σ_bb/σ_b ∈ {0.2, 1} = **36 cells**. The MV-swing and meter-diurnal axes are **reported tolerance axes, not validity axes**. The follow-up measures referenced family-wise rates of 0.052–0.090 under `mv_daily` (0.087–0.090 at σ = 0.005); C2 is indistinguishable from C1 there because the residual is a mean bias. Phase 9 measured the diurnal false-alarm curve crossing 0.5 near A/σ ≈ 0.026–0.027. H1a is therefore not claimed in those cells. The study instead reports the largest swing residual, and the largest A/σ, at which the three-part criterion still holds.

**Replicates and seeds.** 2,000 **independent** replicates per primary cell **per rule** — one fresh noise realisation per (rule, replicate), never shared — giving a per-rule CP half-width ≈ ±0.010 at p = 0.05. 500 per sensitivity cell. Seeds follow the Phase 9 convention **(V, registration §10)**: `default_rng(SeedSequence([<registration-date int>, stable_int(network), stable_int(feeder), stable_int(condition), stable_int(control), replicate]))`, recorded in every artefact.

**False alarms cost zero power flows.** As in Phase 9 controls 1–2, the null is truth = nominal and the noise is simulated analytically on the stored per-day means — exact for the registered reading-noise model **(V, registration §10, §16)**. N2/N3 need a per-day covariance factor rather than 1/n_d, computed from the retained step counts.

**Stratified sample of ENWL feeders and cables.** All feeders × all cables is infeasible: 128 feeders at ~900 buses each is ~10⁵ candidate cables **(H, extrapolated from the one feeder whose size is VERIFIED)**. Proposed: **24 feeders**, stratified by bus-count tercile × parent network (8 per tercile, at most 2 per network, feeder 1 of network 1 excluded); within each, **20 candidate cables** stratified by downstream-bus-count tercile × R_l·length tercile, with both S_l = 0 and S_l > 0 guaranteed present. Error injected: E-R(1.5) — `r_ohm_per_km` × 1.5 with `max_i_ka` × 0.8, Phase 9's definition **(V, registration §4)** — so the result is directly comparable to the 4.6–4.7 % coverage baseline.

**Power-flow and compute estimate.**
- Measured constant **(V)**: Phase 9 ran 17,568 level-0 solves per run in 96.6–100.2 s on a 39–50-line SimBench LV network → **5.5–5.7 ms/solve**; 99 artefacts totalled **7.3 MB**.
- A 906-bus feeder solves more slowly; **(H)** 20–60 ms/solve, to be replaced by a measured constant in the pilot.
- Main study: 24 feeders × (1 nominal + 20 error) = **504 runs** × 60 days × 96 steps = **2,903,040 solves** → **16–48 CPU-hours**; at 3 workers, **5.4–16 h wall-clock**, in ≤ 20-minute invocations per Phase 9's convention **(V, registration §7)** → **17–50 invocations**.
- Superposition sub-study (resolving a standing HYPOTHESIS: a cable error and an MV swing have never been simulated together **(B)**): 3 feeders × 3 cables × 2 swing states × 60 × 96 = **103,680 solves**, 0.6–1.7 CPU-hours at the §6 per-solve band.
- Disk: per-day means only, never absolute vm (Phase 9's float32 precision rule **(V, registration §7)**): 2 × 60 × 906 × 4 B ≈ 435 kB/run → **≈ 220 MB**, budget **≤ 300 MB** under `analysis/`.
- Day-count sensitivity D ∈ {30, 60, 120} runs **free** on the development half, since false alarms are analytic.
- At the upper end of the 20–60 ms band, the main study costs 48 CPU-hours, i.e. 80 % of kill criterion K1's 60-hour trigger. The pilot tripping K1 and forcing the ≤ 8-feeder rescope is a realistic outcome, not a remote one.

**What requires owner approval (Level C — I do not decide these).**
- **A. ENWL licence clearance.** The LVNS page states only that the models are "available to the research and engineering communities"; **no licence is stated**, so reuse and redistribution are **UNVERIFIED** **(B)**. Owner decision before any download.
  - *Re-checked 2026-10-24.* The page still states no licence, terms of use, redistribution condition or citation requirement, and no site-wide ENWL terms were found.
  - The IEEE European LV Test Feeder, shipped in pandapower and used by the pilot, has the same status. The IEEE PES test-feeder resources page states no licence for it. The site footer reserves all rights and defers to the general IEEE terms, under which reproduction needs IEEE's consent unless an exception applies.
  - pandapower redistributes the feeder inside a BSD-3-licensed package. That licence covers pandapower; it does not show that IEEE permitted redistribution of the data.
  - Neither dataset, nor arrays derived from it, may therefore be published from this repository until its terms are verified. Attribution alone is not treated as permission.
  - Code that loads the feeder from the installed pandapower at run time redistributes nothing.
- **B. Converter route.** `pandapower.converter.from_opendss` requires OpenDSSDirect.py, which is **not in `uv.lock`** **(V — grep for `opendss` in `uv.lock` returns nothing; pandapower is pinned `~=3.5.6`, version 3.5.6 installed)**. Either a new dependency or a small custom OpenDSS parser. Owner decision.
  - *Is it actually needed? (assessed 2026-10-24)* pandapower 3.5.6 ships the converter (`pandapower/converter/opendss/from_dss.py`). It imports `opendssdirect` and refuses to run without it; the optional extra `pandapower[opendss]` pins `OpenDSSDirect.py~=0.9` **(V, installed package)**.
  - The pilot did not need it: it read pandapower's shipped JSON network.
  - For ENWL it is needed **only** if the converter route is chosen. A parser limited to the element types the ENWL files use is a reproducible alternative. It can be checked against the pandapower-shipped IEEE feeder, which is reportedly identical to ENWL network 1 feeder 1 **(B, unverified until the files are opened)**.
  - OpenDSSDirect.py would add one thing a parser cannot: an independent solver cross-check of converted voltages.
  - **Recommendation:** do not add it now. Decide after item A clears, and add it only if the parser fails the IEEE-feeder check or a solver cross-check is required.
- **C. New power flows** at the scale above, outside `src/gridpulse/`.
- **D. Registration** of this protocol, if it proceeds.

---

## 7. Statistical evaluation

1. **Size.** Per-rule Clopper–Pearson 95 % intervals from independent replicates; pooled-over-rules CP interval; H1a's three-part criterion (§2). The pooled Wilson rule of Phase 9 is **not** reused, and the reason is recorded: pooled trials sharing one noise realisation across 25 rules are correlated, which cost C1/C2 0.0003–0.0009 **(B)**.
2. **Multiplicity variants.** Bonferroni binding at every level; BH at FDR 0.05 descriptive, with the dependence caveat of §3.3 attached to every BH number.
3. **Power.** Coverage at a **calibrated** 5 %: for each detector, find the critical-value multiplier producing an empirical 0.05 in the matched null cell, then report coverage at that multiplier — the only fair comparison, and the method the follow-up used **(B)**. Report coverage both unconditionally and conditional on a downstream meter, since the unconditional number is dominated by placement (§9).
4. **Population statements.** Cluster bootstrap over **feeders** (2,000 resamples, clusters = feeders, because cables within a feeder share topology and profiles), stratified by bus-count tercile; all population coverage and difference-vs-B3 intervals come from it. Wilson/CP intervals over (cable, rule) pairs remain **descriptive**, as in Phase 9 **(V, registration §8)**.
5. **Pre-registered decision rules.** D1 = H1a; D2 = H1b; D3 = H2; D4 = H3; D5 = the B3 non-inferiority margin of 0.02 absolute (§4.3); D6 = B0/B1 must exceed 0.20 where C2-ref stays ≤ 0.08; D7 = superposition: the measured combined (error + swing) contrast agrees with the sum of the separate contrasts to within 10 % at every tested cable, else superposition is reported **falsified** and all swing-based reasoning is restricted to directly simulated cases.
6. **Integrity.** Phase 9's Stage 0/Stage 4 sha256 pattern, the derived-manifest rule, the `os.replace` write discipline, the completeness barrier before any statistic, and the refuse-to-overwrite results convention are all carried over verbatim **(V, registration §7, §12)**.

---

## 8. Prior art and the novelty claim

Only VERIFIED items are cited.

- **Multi-snapshot residual parameter-error detection.** Liu, Wu & Lun 1992 (doi:10.1109/59.141690) derives parameter errors from residual bias across snapshots — the day–night contrast is a two-bin special case. Lin & Abur 2018 (doi:10.1109/TSG.2016.2597286) gives normalised Lagrange-multiplier and normalised-residual tests, but assumes known variances and transmission-level redundancy that sparse LV metering lacks; it is B2's idiom. Liang et al. 2022 (doi:10.3389/fenrg.2022.840736) is the closest statistical analogue — estimated variances, per-parameter tests — but at transmission level with no serial dependence and no diurnal bias.
- **AMI-based LV model calibration.** Peppanen et al. 2015 (doi:10.1109/TSG.2014.2385636) is the strongest direct competitor and the basis of B3. Lave, Reno & Peppanen 2019 (doi:10.1109/TSTE.2019.2917679) gives real-feeder evidence that asset records are wrong, but estimates without false-alarm control. Vanin et al. 2023 (doi:10.1016/j.ijepes.2023.109155) jointly estimates state and impedance on the 906-bus European LV feeder — heavier, and again without test-level error control. Iakovlev et al. 2018 (doi:10.1109/CDC.2018.8619563) and Pappu et al. 2018 (doi:10.1109/TSG.2017.2680542) cover LV impedance and topology from smart meters.
- **Confounders.** Olivier et al. 2018 (doi:10.23919/PSCC.2018.8442853): phase mislabels create structured residuals — a prerequisite and a confounder, out of this study's scope and named as such.
- **Calibration machinery.** Newey & West 1987 (doi:10.2307/1913610) for HAC; Kiefer & Vogelsang 2005 (doi:10.1017/S0266466605050565) and Shao 2015 (doi:10.1080/01621459.2015.1050493) for the small-bandwidth size distortion we observed as C3's 0.06–0.08. Benjamini & Hochberg 1995 (doi:10.1111/j.2517-6161.1995.tb02031.x) for the FDR variant. Bates et al. 2023 (doi:10.1214/22-AOS2244) and Chernozhukov et al. 2018 (PMLR 75:732-749) for B4 and its exchangeability requirement; Laxhammar & Falkman 2014 (doi:10.1007/s10472-013-9381-7) for inductive conformal anomaly detection.
- **Meter accuracy.** IEC 62053-21:2020 specifies active-energy accuracy and **no voltage accuracy class** **(NOT CHECKED: the standard was not read; this is reported from secondary sources)** — so σ_v is a stipulation, not a standard. Xiong et al. 2021 (doi:10.3390/app112311457) gives indirect (energy, not voltage) support for temperature-driven diurnal metering error; Pau et al. 2019 (doi:10.1109/TIM.2018.2890399) for uncertainty propagation.

**Novelty claim, narrow and honest.** *Apparent* novelty — the prior-art search was targeted, not systematic **(B)** — is the **combination**: a per-cable day–night voltage-residual contrast test whose family-wise false-alarm rate is calibrated under **unequal and unknown daily sample counts, whole-day missingness, a reporting delay, within-day serial dependence and common-mode MV-side voltage swings**, achieved by studentising on the day axis (no variance plug-in) and referencing to the LV busbar (common-mode cancellation inside a calibrated test), and evaluated on **real LV feeder topologies** against a Peppanen-style regression baseline with pre-registered falsifiable criteria. No component is new on its own: contrasts of residuals are Liu 1992; studentisation and HAC are standard; busbar differencing is standard practice in instrumentation. What does not appear in the verified literature is a sparse-LV asset-error test with **measured, dependence-robust size** and a stated power cost.

---

## 9. Risks, kill criteria, and what the study cannot show

**Risks.**
- **R-a. Across-day dependence (N3) defeats everything.** All four calibrations were **invalid** under across-day dependent diurnal error, with HAC degrading slowest **(B)**. C2-ref's day-axis studentisation assumes independent days and will not fix this. Mitigation: busbar referencing removes the common-mode part only; N3 is run and **reported as a failure mode**, with the across-day block-bootstrap and self-normalised variants as exploratory repairs. H1a makes **no** N3 claim.
- **R-b. Meter-specific diurnal error is not cancelled** **(B)**. The study reports an A\* analogue — the largest meter-specific amplitude at which H1a still holds — as a **tolerance bound**, not validity. Phase 9's finding that 0.01 σ doubles false alarms **(B)** sets the expectation that this tolerance is small, and the real-world amplitude is unknown: IEC 62053-21 is reported to have no voltage accuracy class **(NOT CHECKED)**.
- **R-c. The placement/physics ceiling caps any gain.** 67 % and 78 % of cables have no meter downstream under the frozen K = 2 rules **(B)**; no amount of calibration moves coverage above the topological ceiling. The study's honest headline is therefore about **validity and transfer**, not about detecting most cable errors.
- **R-d. Balanced import of unbalanced feeders.** ENWL feeders are single-phase-load; a balanced import changes the physics. Mitigated by the asymmetric-vs-balanced comparison on the pandapower-shipped feeder, and by kill criterion K4.
- **R-e. Licence and profile defects** — unstated licence, single-day profiles, broken profile paths **(B)**.
- **R-f. Superposition is unproven** **(B)** — addressed by D7, with a real possibility of falsification.

**Kill criteria (pre-registered).**
- **K1.** Pilot-measured per-solve cost implies > 60 CPU-hours for the main study → rescope to ≤ 8 feeders, or stop.
- **K2.** C2-ref fails H1a on the **development** half under N1 → the primary hypothesis dies before any ENWL work; fall back to B4 or a block-bootstrap critical value, and re-register. *Tolerance (fix at registration):*
  - The pilot read "fails H1a under N1" as H1a's three-part rule restricted to the 12 N1 primary cells, with at most one failing cell; P(Bin(12, 0.025) ≥ 2) = 0.035.
  - That reading came from the board's pilot brief, not from this text.
  - urban6 sits exactly on it (one failing cell). With no failing cell allowed, K2 would trip (`analysis/calibrated_detection_pilot/README.md` E-1).
- **K3.** ENWL licence cannot be cleared → evaluation reduces to the single pandapower-shipped feeder plus the SimBench rural/semiurb networks; the "independent benchmark" claim is **dropped** and the contribution is downgraded to calibration-only. This is a realistic outcome, not a contingency footnote.
- **K4.** The day–night contrast sign structure on a balanced import differs from the asymmetric reference run beyond a frozen tolerance → no geometry claim on balanced imports.
- **K5.** ENWL coverage at calibrated 5 % < 0.03 in every stratum → report as a negative result and stop; the detector has no practical power on real topologies.

**What the study cannot show, under any outcome.** Real-world false-alarm rates (no dataset pairs measured smart-meter voltages with topology **(B)**). Validity under across-day dependence. Tolerance to real meter-specific diurnal error, as opposed to a stipulated one. Anything about unbalanced physics, Q(U)/P(U) control, multiple simultaneous errors, phase mislabels, or capped operation. Any claim that coverage above the placement ceiling is attainable. And it does not revive R3, R5 or R7: those registered rules **failed and stay failed**.

---

## 10. Minimal first step, and the single owner decision

**Pilot (four steps, no download, no new dependency, no licence question).**

1. **Zero-flow.** Re-run the full C2-ref **size** grid on the development-half day axis (profile-derived step counts, as in `analysis/phase9_followup/calibration.py`).
   - Use **independent-trial** replicates, per-rule CP intervals and the corrected cell-axis tolerance of H1a.
   - Measure the referencing size penalty at σ_bb/σ_b ∈ {0.2, 1}.
   - Deliverable: does the follow-up's C2 result survive the corrected interval rule? This answers K2.
   - It does **not** calibrate H1b. The development half carries no fault signal, so the referencing *power* cost is taken from the follow-up's evaluation-half measurement (retention 1.00 at the registered σ_bb) and is re-measured on ENWL, not here.
2. **Zero-flow.** Load `ieee_european_lv_asymmetric` from the installed pandapower 3.5.6 **(V)** and record its true size and topology (906 buses, 55 1-ph loads, 0.416 kV **(V)**), the candidate-cable count, downstream-set sizes, and whether Phase 9's structural invariants **(V, registration §3)** hold on it.
3. **Timing probe.** Two synthetic days × 96 steps, one leg → a **measured** per-solve constant and peak memory at 906 buses, replacing the 20–60 ms HYPOTHESIS. ≈ 192 solves.
4. **End-to-end smoke.** One nominal leg + three E-R(1.5) error legs × 10 synthetic days × 96 steps = **3,840 solves** (≈ 1.3–4 min at the probed constant), through the Phase 9 artefact conventions, to prove the pipeline and produce the first non-SimBench contrast.

Total new flows ≈ **4,000**; disk < 5 MB; no `src/`, `outputs/`, `data/`, `docs/provenance/` or sandbox change; Git untouched.

**OWNER DECISION NEEDED:** approval to run approximately **4,000 new level-0 power flows** on pandapower's shipped `ieee_european_lv_asymmetric` network, in new code under `analysis/`, under the Phase 9 artefact and integrity conventions.

This asks only for §6 item **C at pilot scale** (≈ 4,000 flows under `analysis/`).
- Items **A** (ENWL licence), **B** (converter route) and **D** (registration of the protocol) remain open and are not requested here.
- The pilot is itself **exploratory and unregistered**, under the Phase 9 convention for `analysis/`.
- Its step-1 output is what H1a's acceptance thresholds would be frozen against. That freezing therefore happens at registration (item D), on the pilot's recorded numbers, not inside the pilot.

**Recommendation: approve the pilot.** It is the cheapest action that can kill the study (K2 is decidable from step 1 alone, at zero flows) and it replaces the single largest unknown in §6 — the per-solve cost at 906 buses — with a measurement, **before** the owner has to decide the three expensive and irreversible questions: the ENWL licence, the OpenDSSDirect.py dependency versus a custom parser, and the 2.9-million-flow main study. Those three stay deferred until the pilot reports.

### 10.1 Pilot outcome (2026-10-24; exploratory, unregistered)

Artefacts and errata are in `analysis/calibrated_detection_pilot/`, which has a `README.md`. The independent QA verdict (AKK-46) is **PASS WITH LIMITATIONS**: it found no computational defect, and its two major findings concern documentation and provenance.

- **Step 1 (zero flows).** C2-ref meets H1a's three-part rule on both networks:
  - pooled rate 0.0488;
  - 35 of 36 cells pass in each network, failing different cells (semiurb4 `sigma0.01_K1_N2_rho_0.5_bb1`, urban6 `sigma0.01_K1_N1_bb1`);
  - no cell has more than 2 rules with a lower bound above 0.05;
  - the maximum per-rule rate is 0.066.
  - **K2 is not tripped**, under the 11-of-12 reading in §9: semiurb4 passes 12 of 12 N1 cells, urban6 only 11 of 12. With no failing cell allowed, K2 would trip. There is no detectable referencing size penalty.
  - This is a measurement under N1 and N2 on the development half, not a passed pre-registered test.
- **Step 2.** The feeder has 204 cable sections, 203 of them candidates. Phase 9's structural invariants hold.
- **Step 3.** A three-phase solve takes 33.7 ms and a balanced solve 14.0 ms, without numba.
- **Step 4.** 4,224 flows ran in total, with 0 failures.
  - The smoke run took 34.4 ms per solve, which puts the main study at 27.8 CPU-h. **K1 is not tripped** (2.2× margin, this feeder only).
- **Warnings for the main study.**
  - **Marginal signal.** The strongest selected cable stays below the C1 floor at D = 10 (ratio 0.34). By D^(−1/2) scaling it reaches ≈ 0.83 at the main study's D = 60 (HYPOTHESIS). Nothing crossed the floor on any leg, so H1b and H3 are unmeasured here. **K5 is a live risk, not a footnote.**
  - **Weak night-sign signature.** The downstream opposite-sign share is 0.35 / 0.56 / 0.00, against Phase 9's 0.90.
  - Off-downstream leakage is ≤ 1.2e-6 p.u.
