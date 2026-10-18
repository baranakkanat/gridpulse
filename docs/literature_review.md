# Literature review and research-gap assessment

Compiled 2026-10-17 for the reliability-and-decisions direction of GridPulse.

## Method and limits

- **Searches.** Three independent searches covered:
  - forecasting, distribution shift and conformal prediction;
  - grid risk, chance constraints and decision-focused learning;
  - selective prediction, deferral and simulation tooling.
- **Sources.** Each source was located in the session and recorded with the access level
  actually achieved: full text, abstract only, or documentation.
- **Second checks.** I re-checked the two claims this project's framing leans on most
  (Girigoudar et al. 2022, full text pp. 11–12; Stratigakos et al. 2026, abstract).
- **Adversarial prior-art review.** A fourth, independent search set out to undermine each
  candidate gap. It found the TenneT/N-SIDE, runtime-assurance, test-martingale and
  special-day density-forecast works added below, and corrected the Zufferey entry. The
  gap statements were narrowed accordingly.
- **Access gaps.** Several publisher pages (ScienceDirect, MDPI, IEEE Xplore) blocked
  automated access. Where only an abstract was seen, methods and results are marked
  unverified.
- **No proof of absence.** This is a focused review, not a systematic one. "Not found"
  means not found in these searches; it does not prove absence.

## Key works

Access: **FT** full text · **AB** abstract/metadata only · **DOC** documentation or repository.

### Forecasting, shift and intervals (Track 1)

| Work | Type, access | Relevance and finding |
|---|---|---|
| Hong et al., *Probabilistic energy forecasting: GEFCom2014 and beyond*, IJF 32(3), 2016, doi:10.1016/j.ijforecast.2016.02.001 | peer-reviewed, FT | Pinball-loss protocol for probabilistic load forecasts; no coverage breakdown by holiday |
| Ziel, *Modeling public holidays in load forecasting: a German case study*, JMPSCE 6(2), 2018, doi:10.1007/s40565-018-0385-5 | peer-reviewed, AB | Holiday modelling improves German holiday accuracy by more than 80 % (abstract); point forecasts |
| Qin et al., *Load forecasting under distribution shift: an online quantile ensembling approach*, Applied Energy 401:126812, 2025, doi:10.1016/j.apenergy.2025.126812 | peer-reviewed, metadata only | Direct competitor for "adaptive quantiles under shift"; content not verified |
| Barber, Candès, Ramdas, Tibshirani, *Conformal prediction beyond exchangeability*, Ann. Statist. 51(2), 2023, doi:10.1214/23-AOS2276 | peer-reviewed, FT | Weighted conformal; the coverage gap is bounded by distribution drift; how to choose weights is open |
| Gibbs & Candès, *Adaptive conformal inference under distribution shift*, NeurIPS 2021, arXiv:2106.00170 | peer-reviewed, FT | Long-run average coverage only; delayed feedback is left open |
| Xu & Xie, *Conformal prediction interval for dynamic time-series* (EnbPI), ICML 2021 | peer-reviewed, FT | Coverage degrades with horizon and under seasonal shift |
| Zaffran et al., *Adaptive conformal predictions for time series*, ICML 2022, arXiv:2202.07282 | peer-reviewed, FT | ACI/AgACI on French prices; infinite intervals possible |
| Angelopoulos, Candès, Tibshirani, *Conformal PID control*, NeurIPS 2023, arXiv:2307.16895 | peer-reviewed, FT | Reports the longest miss run, which suits clustered holiday failures |
| Dutot, Zaffran, Féron, Goude, *Adaptive probabilistic forecasting of French electricity spot prices*, arXiv:2405.15359, 2024 | **preprint**, FT | Calibration on same-horizon errors plus block-bootstrap CIs: the closest template to experiment C3; prices, not load |
| OpenSTEF (LF Energy), docs openstef.github.io, MPL-2.0 | software, DOC | Quantile forecasts with optional split-conformal calibration; used by Alliander at "thousands of grid locations" for congestion; no holiday evaluation documented |
| Arora & Taylor, *Rule-based autoregressive moving average models for forecasting load on special days*, EJOR 266, 2018, arXiv:1803.09590 | peer-reviewed, FT | Density forecasts evaluated on special days with CRPS; no interval coverage reported |
| Vovk et al., conformal test martingales for change detection, PMLR 152, 2021 | peer-reviewed, AB | Online detection of exchangeability violations; conceptually close to this project's calibration monitor (D2) |

### Grid risk and decisions (Track 2)

| Work | Type, access | Relevance and finding |
|---|---|---|
| Roald & Andersson, *Chance-constrained AC OPF: reformulations and efficient algorithms*, IEEE TPWRS 33(3), 2018, doi:10.1109/TPWRS.2017.2745410 | peer-reviewed, FT | Monte Carlo and scenario margins with full AC; out-of-sample violation slightly above in-sample; random (not chronological) out-of-sample draws |
| Dall'Anese, Baker, Summers, *Chance-constrained AC OPF for distribution systems with renewables*, IEEE TPWRS 32(5), 2017, doi:10.1109/TPWRS.2017.2656080 | peer-reviewed, AB | Canonical distribution-grid chance constraints with linearized power flow |
| Campi & Garatti, *The exact feasibility of randomized solutions of uncertain convex programs*, SIAM J. Optim. 19(3), 2008, doi:10.1137/07069821X | peer-reviewed, FT | Scenario guarantees hold for the *sampling* distribution, under convexity |
| Girigoudar, Hou, Roald, *Chance-constrained AC OPF for unbalanced distribution grids*, IREP 2022, arXiv:2207.09520 | peer-reviewed, **FT (re-checked)** | Section V.B, Fig. 7: out-of-sample worst-case violation probabilities up to **0.6** against target 0.05, attributed to unrepresentative in-sample data; out-of-sample days are randomly chosen from summer |
| Zufferey, Renggli, Hug, *Probabilistic state forecasting and optimal voltage control in distribution grids under uncertainty*, PSCC 2020 / EPSR 188, doi:10.1016/j.epsr.2020.106562 | peer-reviewed, FT | **Closest prior.** Quantile forecasts drive AC PV curtailment on a real 400 V grid (196 buses); quantile strategies are about 27 % cheaper; hour-ahead. Reports quantile reliability (average coverage error ≈ −6 % on steps with predicted overvoltage). Real-time curtailment removes remaining overvoltages, so realised violations are not counted; the metric is cost. The test set is 10 weeks spread over the year, not a chronological hold-out. |
| Kop et al. (TenneT / N-SIDE), *Enhancing congestion forecast for TSOs: a probabilistic approach*, CIGRE C2-10298, 2026; vendor write-up at n-side.com | conference paper, AB; vendor page FT | Day-ahead correlated scenarios plus AC load flow, evaluated against realised congestion over six months: 63 % fewer missed congestions at a fixed false-alarm rate. Transmission level, self-reported; miss and false-alarm rates, not Brier or reliability |
| NESO NIA2_NGESO037 progress report, 2024 | report, FT | Scenario-based congestion risk with DC power flow; comparison against realised flows still ongoing |
| Memmel et al., *Forecast of renewable curtailment in distribution grids considering uncertainties*, IEEE Access 9, 2021, doi:10.1109/ACCESS.2021.3073754 | peer-reviewed, AB | Predicted curtailment on a real 110 kV grid, validated against historical curtailment (Dice 0.84) |
| Konrad, Gaugl, Maier, Wogrin, *Dynamic PV feed-in limitations in generation expansion planning*, Energy Strategy Reviews 59, 2025, doi:10.1016/j.esr.2025.101760 | peer-reviewed, FT | Dynamic vs fixed limits under perfect information; no out-of-sample test |
| Yi & Verbič, *Operating envelopes under probabilistic demand and solar forecasts*, IREP 2022, arXiv:2207.09818 | peer-reviewed, FT | Scenario-based chance-constrained export limits with an SOC relaxation; no out-of-sample violation count |
| Hernandez-Matheus et al., *Congestion forecast framework based on probabilistic power flow and ML*, IJEPES 156, 2024, doi:10.1016/j.ijepes.2023.109695 | peer-reviewed, FT | pandapower Monte Carlo PPF on synthetic hourly data; its congestion probabilities are compared with a deterministic power flow, not with realised outcomes |
| González-Ordiano et al., *Probabilistic forecasts of the distribution grid state*, Applied Energy 302, 2021, doi:10.1016/j.apenergy.2021.117498 | peer-reviewed, FT | Joint-event probabilities need a PPF; validated on 3 test days only |
| Donti, Amos, Kolter, *Task-based end-to-end model learning*, NeurIPS 2017, arXiv:1703.04529 | peer-reviewed, FT | Best RMSE ≠ best decision cost (38.6 % lower task loss) |
| Stratigakos, Wen, Spyrou, Pinson, *Decision-calibrated prediction sets for robust power system operations*, arXiv:2606.02081, 2026 | **preprint**, AB (re-checked) | Calibrates sets to constraint-satisfaction targets within about 3 pp; coverage-calibrated sets overshoot by more than 11 pp; DC transmission, 15-minute horizon |

### Deferral, alarms and evaluation tooling

| Work | Type, access | Relevance and finding |
|---|---|---|
| Chow, *On optimum recognition error and reject tradeoff*, IEEE TIT, 1970, doi:10.1109/TIT.1970.1054406 | peer-reviewed, AB | The reject option has a constant cost; nothing downstream is modelled |
| Geifman & El-Yaniv, *Selective classification for deep neural networks*, NeurIPS 2017, arXiv:1705.08500 | peer-reviewed, FT | Risk is counted on accepted inputs only; rejected inputs are never scored |
| Madras, Pitassi, Zemel, *Predict responsibly*, NeurIPS 2018, arXiv:1711.06664 | peer-reviewed, FT | Learning to defer counts the downstream decision-maker's loss plus a deferral penalty; experts are simulated |
| Mozannar & Sontag, *Consistent estimators for learning to defer*, ICML 2020 | peer-reviewed, FT | Formal accounting of the expert's outcome after deferral |
| Marot et al., *Learning to run a power network with trust* (L2RPN 2021 alarm track), arXiv:2110.12908 / EPSR 2022 | peer-reviewed, FT | **Closest power-systems precedent for deferral**: agents raise alarms before failures (transmission, AC). Alarms have no physical effect; no operator response is modelled; false alarms cost only attention budget |
| L2RPN 2023 assistant track (Grid2Op `AlertReward`) | documentation and white paper | Asymmetric alert rewards; no fallback is simulated |
| Leyli Abadi et al., *LIPS – learning industrial physical simulation benchmark suite*, NeurIPS D&B 2022 | peer-reviewed, FT | Physics-compliance evaluation of surrogates, not of decisions |
| Damare et al., *A barrier certificate-based Simplex architecture* (Bb-Simplex), arXiv:2202.09710 | preprint, AB | Runtime assurance: a monitor switches a learned microgrid controller to a verified fallback, physically simulated (RTDS). The *concept* of a physically simulated fallback switch is established |
| Straitouri et al., arXiv:2109.11328 | preprint, AB | Reinforcement learning switching between machine and human control policies, in simulation |
| pandapower (BSD-3), SimBench (code BSD-3; data **ODbL 1.0 / DbCL**), Grid2Op and lightsim2grid (MPL-2.0) | DOC | Tools used or considered; the pandapower-to-lightsim2grid conversion is documented as able to fail silently |

## What is well covered

- Chance-constrained and scenario-based OPF formulations, including full-AC
  out-of-sample checks (Roald 2018, Girigoudar 2022).
- Distribution-free scenario guarantees for convex problems (Campi & Garatti 2008).
- Probabilistic power flow for congestion probabilities (Hernandez-Matheus 2024,
  González-Ordiano 2021).
- Showing that forecast accuracy differs from decision value (Donti 2017).
- Point-vs-probabilistic PV curtailment on a real LV grid, hour-ahead (Zufferey 2020).
- Learning to defer with expert-loss accounting, in classification (Madras 2018,
  Mozannar 2020).
- Alarm-raising for transmission topology control (L2RPN 2021/2023).
- Adaptive, weighted and horizon-matched conformal intervals (Barber 2023, Gibbs 2021,
  Dutot 2024).
- Operational evaluation of scenario-based congestion forecasts against realised outcomes,
  at transmission level with miss and false-alarm rates (TenneT/N-SIDE 2026).
- Runtime assurance with physically simulated fallback switching (Simplex architectures,
  e.g. Bb-Simplex).
- Change detection for calibration, via conformal test martingales (Vovk 2021).

## Candidate gaps and evidence

| Gap | What exists | Verdict |
|---|---|---|
| **G-A.** Day-ahead *violation probabilities* (full AC, LV) scored with proper scoring rules and reliability on a chronologically later, season-shifted period | TenneT/N-SIDE evaluate scenario-plus-AC forecasts against realised congestion (transmission; miss and false-alarm rates). Girigoudar uses random summer days. Stratigakos is DC, single-season. Memmel validates curtailment predictions. | **Partly covered.** LV with Brier and reliability on a later season was not found. Tested in H1, H3. |
| **G-B.** Same grid, same information: static cap vs point rule vs chance-constraint rule vs oracle, counting realised violations *and* curtailment | Zufferey compares point vs quantile (cost-based; violations removed in real time). Konrad compares dynamic vs fixed limits deterministically. | **Not found in this combination.** Tested in H2. |
| **G-C.** Deferral whose fallback branch is physically simulated | Runtime assurance (Simplex) switches to verified fallbacks in physical simulation. Learning to defer and L2RPN alarms do not simulate the fallback physically. | **Concept covered; the day-ahead curtailment application was not found.** Tested in H4. |
| **G-D.** Holiday coverage of day-ahead load intervals | Arora & Taylor evaluate special-day density forecasts (CRPS). Holiday-stratified coverage of rolling conformal intervals was not found. | **Partly covered.** Reported as a diagnostic finding, not a gap. |

## Selected direction and honest novelty assessment

**Research question.** In a benchmark LV grid, are scenario-based day-ahead violation
risks calibrated on a later season? Does a risk-aware curtailment rule beat simple rules
on realised violations and curtailment? And what does a selective variant that can defer
achieve once the deferral branch is physically simulated?

**Nature of the contribution.** A pre-registered, chronologically split evaluation, on
one public SimBench LV benchmark, of a standard pipeline (residual-day scenarios plus AC
power flow). It:

- (i) scores day-ahead violation probabilities with proper scoring rules and reliability
  tables on a later, season-shifted half-year. This complements transmission-level
  operational evaluations that report miss and false-alarm rates.
- (ii) compares a static cap, a point rule, a chance-constraint rule and an oracle on the
  same grid by realised violations *and* curtailed energy, with day-block bootstrap
  intervals.
- (iii) treats deferral as a runtime-assurance switch and simulates each fallback with AC
  power flow, which tests whether deferral without a protective fallback is a safety
  measure.

No new method is proposed. Every component is established: mean-based forecasts, residual
scenarios, AC power flow, chance-constraint thresholds, a Poisson calibration monitor (close
to test martingales) and fallback switching (close to Simplex).

**Strength of novelty evidence.** Modest.

- Two focused reviews plus one adversarial review; none was systematic.
- Close neighbours exist: Zufferey 2020, Girigoudar 2022, TenneT/N-SIDE 2026, Stratigakos
  2026, Simplex runtime assurance.
- Unread full texts (Qin 2025, CIGRE C2-10298, Konrad 2025) could cover more.

**Remaining uncertainty.** The results describe one 15-bus benchmark grid with synthetic
benchmark profiles and naive forecasts. They demonstrate a protocol and a set of failure
modes, not external validity.

## Phase 4 additions: online risk calibration and physical-model uncertainty

These sections come from two focused reviews made on 2026-10-17, before the Phase 4
protocol (`docs/research_protocol.md`, s. 4) was registered.

- **Not systematic.** Neither review was systematic.
- **Verification.** "Verified" means the reviewer read the full text, or at least the
  theorem statements or the abstract. References marked *unverified* rest on a secondary
  record only.

### Online calibration under shift: what each method guarantees

| Method | Guarantee | Feedback needed | Under shift |
|---|---|---|---|
| Adaptive conformal inference (Gibbs & Candès 2021, NeurIPS) | Deterministic: \|mean miscoverage − α\| ≤ (max(α₁, 1 − α₁) + γ)/(γT). The paper states it gives no single-step information | Miss / no miss at the parameter used | Any sequence |
| Conformal PID / quantile tracking (Angelopoulos, Candès, Tibshirani 2023, NeurIPS) | Long-run bound for bounded scores | Realised miss | Any sequence |
| Decaying step sizes (Angelopoulos, Barber, Bates 2024, ICML) | Long-run bound on any sequence. Per-time convergence only under i.i.d. data. Fixed-step ACI hits empty and full sets infinitely often | Realised miss | Long-run part only |
| Rolling risk control (Feldman, Ringel, Bates, Romano 2023, TMLR) | θ ← θ + γ(lₜ − r) gives \|mean loss − r\| ≤ C/T | Realised loss at the parameter used | Any sequence |
| Conformal decision theory (Lekeufack, Angelopoulos, Bajcsy, Jordan, Malik 2023, arXiv:2310.05921) | Calibrates a *decision* parameter. Average realised loss ≤ ε + O(1/t). Needs no monotonicity, only an "eventually safe" parameter region | Realised loss at the parameter used | Any sequence. Guarantee is on the historical average |
| Conformal risk control (Angelopoulos et al. 2024, ICLR); Learn-then-Test (2021) | Marginal / high-probability risk control | Full loss curves (here counterfactual) | Exchangeable only. Batch conformal risk control needs a loss monotone in λ, which the realised violation is not here |
| Weighted conformal (Barber, Candès, Ramdas, Tibshirani 2023, Ann. Statist.) | Coverage ≥ 1 − α − Σ w̃ᵢ·d_TV | Full scores | Bounded degradation |
| Test martingales and e-values (Vovk 2021; Arnold, Henzi, Ziegel 2023; Henzi & Ziegel 2022; Waudby-Smith & Ramdas 2024) | Anytime-valid detection of miscalibration (Ville's inequality) | Realised outcomes and predicted risks | Detect shift; do not correct it |

**Consequences for Phase 4:**

1. **Feedback.** Only the realised-loss controllers (ACI, rolling risk control, conformal
   decision theory) work with feedback at the applied cap alone. Every other method needs
   outcomes at caps that were not applied. Those can only come from a grid model, which
   may be the misspecified one.
2. **Long-run averages only.** All guarantees are long-run averages. None gives per-step or
   per-day safety, and several papers say so explicitly. Physical safety needs a
   worst case over a declared physical set, which is a modelling claim.
3. **Scenario approach.** Campi & Garatti (2011, JOTA; sampling-and-discarding) give the
   bound for the Phase 3 rule (*N* = 28, one scenario discarded, one decision variable).
   Assuming i.i.d. scenarios and monotone violation, the violation probability is ≤ 0.159
   with confidence 0.95. Its expectation is 2/29 ≈ 0.069, against an in-sample level
   ≤ 1/28.
   - The zero-violation rule gives 1/29 ≈ 0.034.
   - Garatti & Campi (2025, Math. Program.) extend a posteriori bounds to non-convex
     decisions.
   - This is the optimizer's curse (Smith & Winkler 2006, Manag. Sci.). Sample-average
     chance constraints are known to need an in-sample level below the target (Luedtke &
     Ahmed 2008; Pagnoncelli, Ahmed, Shapiro 2009).

**Closest power-system work** found; the searches were not exhaustive:

- **Costilla-Enriquez, Weng, Ortega-Vazquez** (2026, arXiv:2610.16075). ACI and rolling risk
  control for day-ahead reserve requirements, with no network constraints.
- **Stratigakos, Wen, Spyrou, Pinson** (2026, arXiv:2606.02081). Decision-calibrated
  prediction sets for robust DC-OPF, offline.
- **Manoharan** (2026, arXiv:2607.13221). Risk-controlled N-1 screening with an online
  audit.
- **Earlier work:**
  - chance-constrained AC-OPF for distribution grids (Dall'Anese, Baker, Summers 2017);
  - a-posteriori chance-constraint tuning (Hou & Roald 2020, arXiv);
  - feedback optimisation against model mismatch (Ortmann et al. 2020, EPSR; Picallo et
    al. 2021, arXiv).

No paper was found that couples online realised-loss calibration with AC power-flow
violations of LV PV curtailment under joint forecast and grid-model uncertainty. This is
evidence of a gap, but only moderate evidence.

### Physical-model uncertainty in LV grids

- **SimBench itself** (package data, simbench 1.6.3; read directly):
  - the MV/LV tap is set per network and scenario: 37–50 % of the 412 MV/LV transformers
    change by one step between scenarios;
  - the LV slack voltage in the study cases ranges from 0.965 (high load) to 1.055 (low
    load / high PV), whereas the time series use a fixed 1.025.
  - The time-series preprint (Spalthoff et al. 2019) describes home-storage series as
    self-consumption-maximising PV-battery systems. No reading of the series tested here
    is energy-consistent.
- **Tap practice and voltage-band budget.** FNN-Hinweis rONT (VDE|FNN 2016): off-load taps
  are set on site and rarely changed. The same note covers the 10 % EN 50160 band and the
  3 % rise rule of VDE-AR-N 4105.
- **PV reactive power.**
  - VDE-AR-N 4105:2018 lets the DSO choose the method. A secondary source (a DSO
    presentation, 2019) was read; the standard itself was not (*unverified*).
  - Heier (2020) analyses the effect of the standard cos φ(P) characteristic.
- **Home batteries.**
  - Weniger, Bergner, Tjaden, Quaschning (2014): self-consumption batteries are full
    before the midday peak on clear days.
  - Moshövel et al. (2015, Applied Energy): grid-relieving strategies.
  - KfW programme 275 (2016) required a 50 % feed-in limit.
- **Transformer loading.** IEC 60076-7 (loading guide; read via IS 2026-7:2009) allows
  normal cyclic loading up to 1.5 p.u. and a 120 °C hot-spot. With an oil time constant of
  about 180 min, a single quarter-hour slightly above rating is not a thermal event.
- **Parameter-error and hosting-capacity studies:**
  - Navarro & Ochoa (2015, ISGT);
  - Mulenga, Bollen, Etherden (2020, IJEPES; 2021, IJEPES);
  - Nainar & Iov (2020, Energies): ±10 % line R/X error;
  - Pezeshki, Wolfs, Ledwich (2014, TPWRD): PV and transformer ageing.

**Not found.** No quantitative source was found on how often DSO databases record the
wrong tap position, or on the share of home batteries operated grid-friendly.

### Novelty after Phase 4 (2026-10-18)

**What Phase 4 adds.** Phase 4 adds an empirical, pre-registered comparison on six SimBench
LV networks. It covers:

- online realised-loss calibration (rolling risk control / conformal decision theory form)
  of an AC-power-flow curtailment margin;
- strong static and deterministic baselines, a historical-replay ensemble, and an explicit
  model-ensemble robust rule;
- truth grids that differ from the decision model.

**The finding.** Measured-feedback calibration, not forecast scenarios, carries the value
under model mismatch. A development-validated static cap is near-oracle when the model is
right. This is consistent with the feedback-optimisation literature (Ortmann et al. 2020;
Picallo et al. 2021).

**Contribution level.** The contribution is an evaluation result and protocol, not a new
method. The evidence for novelty remains moderate: the searches were focused, not
systematic. The closest operational analogue (Costilla-Enriquez et al. 2026) calibrates
reserve requirements without network physics.
