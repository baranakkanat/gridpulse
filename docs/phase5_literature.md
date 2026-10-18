# Phase 5 literature: limited observability, sensor placement, decision sufficiency

**Review.** A focused, citation-checked review (2026-10-18). It was targeted, not
systematic.

**Flags.**

- *FULL:* full text read, at least the relevant sections.
- *ABS:* abstract or metadata only.
- *UNVERIFIED:* not traced to the source; not relied on.
- *META:* bibliographic data verified (Crossref or the publisher) in the post-evaluation
  novelty review. The one-line summary is the reviewer's, and no number is taken from it.

## 1. State estimation with few measurements

**LV state estimation is usually underdetermined.**

- The German guidance (VDE FNN 2025, *FULL*) says the LV equations "are and remain"
  underdetermined. It renames the task *Netzzustandsermittlung*.
- Its study (Consentec & BUW 2024, *FULL*) uses WLS. Pseudo-measurements come from
  spreading the transformer measurement over unmeasured nodes, or from standard profiles.

**Pseudo-measurement uncertainty is large.**

- de Jongh et al. 2025 (IEEE TSG, *FULL*) use 3σ = 50 %, citing Angioni et al. 2016 (*ABS*)
  for over 50 %.
- Jafarian et al. 2021 (IET GTD, *FULL*) found relative standard deviations of 0.25–0.45
  for standard load profiles.
- High pseudo variance can ill-condition the gain matrix (Dehghanpour et al. 2019, IEEE
  TSG, *FULL*).

**Observability says nothing about accuracy.**

- Numerical and topological observability are standard (Abur & Gómez-Expósito 2004, *ABS*).
- Observability is no statement about accuracy, and without redundancy bad data cannot be
  detected (Zeraati et al. 2022, IET RPG, *FULL*).

**pandapower 3.5.6** (documentation and installed source, *FULL*):

- WLS, IRWLS, LP and optimisation estimators.
- Measurement types: v, p, q, i.
- Bad-data tests: χ² and largest normalised residual. The documentation says bad-data
  removal "is not very robust".
- Its observability check is only m ≥ 2n − k. A count-sufficient but rank-deficient set
  gives a singular gain matrix.
- **Hence Phase 5's own rank test.**

## 2. The four given references

| Reference | Problem and method | Model mismatch? | Downstream decision? | Flag |
|---|---|---|---|---|
| Buason, Misra, Talkington, Molzahn 2024, EPSR 232:110387 | Fewest voltage sensors plus alarm thresholds that catch every voltage violation, for injections in given ranges. Bilevel MILP on conservative linear power flow | No (known model, noise-free) | No (alarms) | FULL (arXiv v4) |
| de Jongh, Mueller, Cañizares, Leibfried, Bhattacharya 2025, IEEE TSG 16(5) | LV WLS with a transformer measurement and optional smart meters; ML-disaggregated pseudo-measurements. Reports violation counts; end-of-feeder meters most valuable | No (stated limitation) | No | FULL (accepted manuscript) |
| Rangarajan, Gupta, Molzahn, Roald 2025, SEGAN 43:101863 | Forecast-aided estimation when only 10–20 % of meters report; IEEE 123-bus | No | No | Metadata verified; content via the authors' PSERC report |
| Zeraati, Shabanzadeh, Sheibani, Jabari 2022, IET RPG 16(15) ("…: Review, challenges and future research directions") | Review of meter placement for state estimation | Lists parameter uncertainty | Not as an objective | FULL |

## 3. Placement and decision-aware sensing

**Accuracy-driven placement.**

- Singh, Pal & Vinter 2009 (*ABS*).
- Singh et al. 2011 (*ABS*).
- Pegoraro & Sulis 2013: includes parameter uncertainty and meter malfunction (*ABS*).
- Netto et al. 2022 (review, *FULL*): application-oriented placement is scarce.

**German practice** (FNN 2025 and the Consentec/BUW 2024 study, *FULL*).

- The Consentec/BUW study (s. 2), not the FNN Hinweis, distributes smart-meter gateways
  in its simulations as follows:
  - first to mandatory installations (PV > 7 kW, consumption > 6,000 kWh/a), ordered by
    rated power or annual energy;
  - then at random.
- This is a modelling key, not a description of how rollout actually proceeds.
  (Corrected after the post-evaluation review; the claim was first attributed to the
  Hinweis.)
- The FNN Hinweis gives the required penetration for reliable detection, assuming no
  communication failures:

  | Substation measurement | Radial feeders | Meshed, one transformer |
  |---|---|---|
  | Per-feeder | 15 % | 5 % |
  | Transformer total only | 30 % | 10 % |
  | None | 70 % | 40 % |

- Inferring congestion at unmeasured assets from a direct measurement is
  "nicht zulässig" (not permitted).
  - The Hinweis says this about justifying a control action from a direct measurement.
  - Its context is §14a EnWG load control, not PV curtailment.

**Violation- and certification-aware selection.**

- Buason 2024.
- Chen & Roald 2024 (IEEE CDC, *ABS*).
- Talkington et al. 2024 (IEEE CDC, *ABS*).
- Zhang, Roald & Singh 2026 (arXiv:2609.28785, *FULL*): bilevel selection for certifiable
  voltage monitoring; noiseless linearised model. The preprint is v1 of 23 Sep 2026; its
  abstract does not state the noise model.
- Jafarian et al. 2021 also belongs here. It treats placement as feature selection for
  classifying whether operating constraints are violated.
  - Its 0.25–0.45 pseudo-measurement figure (s. 1) could not be re-found in the
    post-evaluation review.
  - That figure was not used for any parameter.
- Molzahn & Roald 2019 (HICSS, *ABS*): certify or name the critical constraints.

**Decision-aware.**

- Kekatos et al. 2026 (IEEE TPWRS, *ABS*): select data to maximise OPF fidelity.
- Picallo et al. 2018 (IEEE CDC, *FULL*): stochastic OPF with the estimator's covariance,
  fixed sensors.
- Ghazanfariharandi & Mieth 2024 (arXiv, *ABS*): value of data in stochastic OPF.

**Model mismatch.**

- Transmission parameter-error identification needs redundancy: Zhu & Abur 2006; Lin &
  Abur 2018 (both *ABS*).
- Táczi et al. 2023 (*ABS*): modelling tap changers in LV state estimation cut errors "by
  two magnitudes".
- Asiamah et al. 2025 (*ABS*): classifying PV reactive-power control laws from smart-meter
  data.
- Picallo et al. 2022 (EPSR, *ABS*): feedback optimisation with online sensitivity
  learning, with measured outputs.

## 4. What is and is not covered

| Reference | Sparse measurements | Model mismatch | Downstream decision evaluated |
|---|---|---|---|
| Buason 2024 | yes | no | no (alarms) |
| Zhang/Roald/Singh 2026 | yes | no | no (certification) |
| de Jongh 2025 | yes | no | no |
| FNN/Consentec 2024–25 | yes (realistic) | no | no (detection, load-driven) |
| Kekatos 2026 | yes | no | yes (OPF fidelity) |
| Picallo 2018 | yes (fixed) | no | yes |
| Picallo 2022 | no | yes | yes |
| Pegoraro & Sulis 2013 | yes | yes (parameters) | no |

**Partial precedents** (added after the post-evaluation novelty review):

- feedback control fed by state estimation from sparse measurements (Picallo et al.
  2020);
- feedback optimisation under model mismatch (Picallo et al. 2022);
- dynamic operating limits for PV export (Petrou et al. 2021);
- tap-setting observability in state estimation (Korres et al. 2004);
- model calibration from smart-meter and inverter data (Peppanen et al. 2016);
- information-based and cost–benefit meter placement (Xygkis et al. 2018; Pau et al.
  2024; Liu et al. 2014).

**Not found** (targeted search, not exhaustive; the specific combination):

- outcome-level evaluation (realised violations and curtailment) of an online,
  violation-calibrated curtailment policy whose feedback comes from partial telemetry;
- that evaluation under persistent network-parameter mismatch (tap, MV voltage, PV
  reactive power);
- an evidence label that separates "model inconsistency" from "insufficient evidence" and
  "no feasible action".

**Decision-aware placement in general is not new.** Kekatos 2026 and Zhang 2026 are close.
Phase 5 therefore claims no new placement method. Its possible contribution is the
outcome-level comparison under mismatch.

**Diminishing returns are expected.** Value-of-information theory (Krause & Guestrin
2009) predicts them, and data valuation for power-system decisions has been studied
(Mieth et al. 2025; Ghazanfariharandi & Mieth 2024).

**The controller and noisy labels.**

- The controller is an online risk-control / conformal-decision update. See
  `docs/literature_review.md`: Feldman et al. 2023; Lekeufack et al. 2023.
- Its guarantee concerns the *measured* violation rate.
- Calibrating on noisy labels is known to give conservative risk on the true labels
  (Einbinder et al. 2024). This predicts the direction of Phase 5's noise confound.
- What Phase 5 adds is its size, and the reversal of a registered verdict.

**Novelty assessment** (post-evaluation novelty review, summarised):

| Phase 5 finding | Status |
|---|---|
| Substation telemetry misses remote overvoltage under offset errors | Known (physics; FNN penetration table); new numbers only |
| One or two remote sensors recover most; diminishing returns | Known in principle; rarely measured by decision outcomes under mismatch; holds only with noise |
| Decision-aware placement no better | Conditional on noise; reverses with exact readings |
| Noise confound reversing a registered verdict | Direction known; size and verdict reversal plausibly new |
| Voltage sensors miss mid-feeder overloads | Known (physics) |
| Model-consistency flag | Known (tap observability, calibration); idealised here |
| SE detects remote overvoltage but with false alarms | Consistent with de Jongh 2025 and FNN |

**A hypothesis taken from the review** (inference, untested):

- A busbar voltage measurement directly observes the combined tap and MV-voltage offset.
- So the hard cases for substation telemetry would be PV reactive-power behaviour and
  mid-feeder cable loading.
- **Outcome (post-evaluation).**
  - The hypothesis held for *model-based* use of the busbar voltage: the
    model-consistency flag, and state-estimation recall under the offsets.
  - It did not hold for *direct threshold* feedback. There, the voltage offsets were the
    hard case: substation feedback met 0 of 10 offset cells but 4 of 5 fixed-cos φ cells.
    The busbar voltage never crosses the limit itself.

## 5. Measurement parameters adopted (protocol s. 5)

| Quantity | Value | Basis | Confidence |
|---|---|---|---|
| Substation busbar voltage | σ = 0.2 % | de Jongh (class 0.5S, 3σ = 0.5 %); FNN (1 %) | medium |
| Transformer / feeder current, P, Q | σ = 1 % | FNN study | medium |
| Smart-meter voltage | σ = 1 %; sweep 0.2 % | 0.5 % (3σ) to 2 % in the literature; no standard verified | low–medium |
| Pseudo-measurements | data-driven forecast-error spread; literature 20–50 %+ | de Jongh, Angioni, Jafarian | medium |
| Reporting interval | 15 min | MsbG §60 (*FULL*) | high |
| Smart-meter latency | next day | MsbG §60(3): "daily, for the previous day" | high (Germany) |
| Missing data | 5 % of sensor-days | Kodaira & Han 2018 (2.7–9.4 %/yr, secondary); FNN assumes none | low |

## 6. References

1. Buason P, Misra S, Talkington S, Molzahn DK (2024). A data-driven sensor placement
   approach for detecting voltage violations in distribution systems. *EPSR*
   232:110387. doi:10.1016/j.epsr.2024.110387 — FULL
2. de Jongh S, Mueller F, Cañizares CA, Leibfried T, Bhattacharya K (2025). Distribution
   Grid State Estimation With Limited Actual and Pseudo Measurements. *IEEE TSG*
   16(5):3638–3652. doi:10.1109/TSG.2025.3576697 — FULL
3. Rangarajan A, Gupta RK, Molzahn DK, Roald L (2025). Forecast-aided state estimation in
   unbalanced distribution networks using smart meter data under limited communication
   bandwidth. *SEGAN* 43:101863. doi:10.1016/j.segan.2025.101863 — metadata
4. Molzahn DK, Roald L, et al. (2025). Smart Meter-Driven Distribution Grid Visibility and
   Control. PSERC T-67 final report — FULL when first read. No online record could be
   found in the post-evaluation review, so it is treated as UNVERIFIED until a URL is
   recorded.
5. Zeraati M, Shabanzadeh M, Sheibani MR, Jabari F (2022). Meter placement algorithms to
   enhance distribution systems state estimation: Review, challenges and future research
   directions. *IET RPG* 16(15):3422–3444. doi:10.1049/rpg2.12570 — FULL
6. VDE FNN (2025). Hinweis: Standardisiertes Vorgehen für die Durchführung der
   Netzzustandsermittlung … Sensitivität und Spezifität, v1.0 — FULL
7. Consentec & Bergische Universität Wuppertal (2024). Study for VDE FNN on standardised
   network state determination — FULL
8. pandapower documentation, "State Estimation", and source v3.5.6 — FULL
9. Primadianto A, Lu C-N (2017). A Review on Distribution System State Estimation. *IEEE
   TPWRS* 32(5). doi:10.1109/TPWRS.2016.2632156 — ABS
10. Dehghanpour K, Wang Z, Wang J, Yuan Y, Bu F (2019). A Survey on State Estimation
    Techniques and Challenges in Smart Distribution Systems. *IEEE TSG* 10(2).
    doi:10.1109/TSG.2018.2870600 — FULL
11. Abur A, Gómez-Expósito A (2004). *Power System State Estimation*. CRC — ABS
12. Singh R, Pal BC, Vinter RB (2009). Measurement placement in DSSE. *IEEE TPWRS* 24(2).
    doi:10.1109/TPWRS.2009.2016457 — ABS
13. Singh R, Pal BC, Jabr RA, Vinter RB (2011). Meter placement for DSSE: an ordinal
    optimization approach. *IEEE TPWRS* 26(4). doi:10.1109/TPWRS.2011.2118771 — ABS
14. Pegoraro PA, Sulis S (2013). Robustness-oriented meter placement for DSSE in presence
    of network parameter uncertainty. *IEEE TIM* 62(5):954–962.
    doi:10.1109/TIM.2013.2243502 — ABS
15. Angioni A, Schlösser T, Ponci F, Monti A (2016). Impact of pseudo-measurements from
    new power profiles on state estimation in low-voltage grids. *IEEE TIM* 65(1).
    doi:10.1109/TIM.2015.2454673 — ABS
16. Netto M, Krishnan V, Zhang Y, Mili L (2022; online 2021). Measurement placement in
    electric power transmission and distribution grids: Review of concepts, methods, and
    research needs. *IET GTD* 16(5). doi:10.1049/gtd2.12336 — FULL
17. Chen J, Roald L (2024). Real-time assessment of distribution grid security through
    adaptive smart meter measurements. *IEEE CDC*. doi:10.1109/CDC56724.2024.10885867 —
    ABS
18. Talkington S, et al. (2024). Strategic electric distribution network sensing via
    spectral bandits. *IEEE CDC*. doi:10.1109/CDC56724.2024.10886546 — ABS
19. Zhang P, Roald L, Singh MK (2026). Optimal measurement selection for certifiable
    voltage monitoring in power distribution systems. arXiv:2609.28785 — FULL (preprint)
20. Molzahn DK, Roald L (2019). Grid-aware versus grid-agnostic distribution system
    control. *HICSS*. doi:10.24251/HICSS.2019.417 — ABS
21. Jafarian MJ, Soroudi A, Keane A (2021). A data-driven measurement placement to
    evaluate the well-being of distribution systems operation. *IET GTD* 15(9).
    doi:10.1049/gtd2.12114 — FULL
22. Kekatos V, Annin R, Singh MK, Qin J (2026). Solving optimal power flow on a
    data-budget: Feature selection on smart meter data. *IEEE TPWRS* 41(3):1978–1991.
    doi:10.1109/TPWRS.2025.3638272 — ABS
23. Picallo M, Anta A, De Schutter B (2018). Stochastic optimal power flow in distribution
    grids under uncertainty from state estimation. *IEEE CDC*.
    doi:10.1109/CDC.2018.8619713 — FULL
24. Picallo M, Ortmann L, Bolognani S, Dörfler F (2022). Adaptive real-time grid
    operation via online feedback optimization with sensitivity estimation. *EPSR*
    212:108405. doi:10.1016/j.epsr.2022.108405 — ABS
25. Zhu J, Abur A (2006). Identification of network parameter errors. *IEEE TPWRS* 21(2).
    doi:10.1109/TPWRS.2006.873419 — ABS
26. Lin Y, Abur A (2018). Robust state estimation against measurement and network
    parameter errors. *IEEE TPWRS* 33(5). doi:10.1109/TPWRS.2018.2794331 — ABS
27. Táczi I, et al. (2023). Role of voltage control devices in low voltage state
    estimation process. *Int. Trans. Electr. Energy Syst.* doi:10.1155/2023/6614905 —
    ABS
28. Asiamah R, et al. (2025). Classifying reactive power control laws of behind-the-meter
    solar PV inverters. *KPEC*. doi:10.1109/KPEC65465.2025.11045009 — ABS
29. Kodaira D, Han S (2018). Topology-based estimation of missing smart meter readings.
    *Energies* 11(1):224. doi:10.3390/en11010224 — ABS (the rate figure is secondary)
30. Messstellenbetriebsgesetz §60 (gesetze-im-internet.de) — FULL
31. Ghazanfariharandi M, Mieth R (2024). Analysis of data value in stochastic optimal
    power flow for distribution systems. arXiv:2406.13148 — ABS

**Added after the post-evaluation novelty review** (all *META*):

32. Liu J, Ponci F, Monti A, Muscas C, Pegoraro PA, Sulis S (2014). Optimal meter
    placement for robust measurement systems in active distribution grids. *IEEE TIM*
    63(5):1096–1105. doi:10.1109/TIM.2013.2295657
33. Xygkis TC, Korres GN, Manousakis NM (2018). Fisher information-based meter placement
    in distribution grids via the D-optimal experimental design. *IEEE TSG*
    9(2):1452–1461. doi:10.1109/TSG.2016.2592102
34. Pau M, Ginocchi M, et al. (2024). A meter placement strategy for distribution grids
    based on cost–benefit analysis. *IEEE TIM* 73:1–12. doi:10.1109/TIM.2024.3387503
35. Krause A, Guestrin C (2009). Optimal value of information in graphical models.
    *JAIR* 35:557–591. doi:10.1613/jair.2737
36. Mieth R, Morales JM, Poor HV (2025). Data valuation from data-driven optimization.
    *IEEE TCNS* 12(1):954–966. doi:10.1109/TCNS.2024.3431415
37. Bhela S, Kekatos V, Veeramachaneni S (2018). Enhancing observability in distribution
    grids using smart meter data. *IEEE TSG* 9(6):5953–5961.
    doi:10.1109/TSG.2017.2699939
38. Einbinder B-S, Feldman S, Bates S, Angelopoulos AN, Gendler A, Romano Y (2024). Label
    noise robustness of conformal prediction. *JMLR* 25(328):1–66
39. Picallo M, Bolognani S, Dörfler F (2020). Closing the loop: Dynamic state estimation
    and feedback optimization of power grids. *EPSR* 189:106753.
    doi:10.1016/j.epsr.2020.106753
40. Petrou K, Procopiou AT, Gutierrez-Lagos L, Liu MZ, Ochoa LF, Langstaff T, Theunissen
    JM (2021). Ensuring distribution network integrity using dynamic operating limits for
    prosumers. *IEEE TSG* 12(5):3877–3888. doi:10.1109/TSG.2021.3081371
41. Korres GN, Katsikas PJ, Contaxis GC (2004). Transformer tap setting observability in
    state estimation. *IEEE TPWRS* 19(2):699–706. doi:10.1109/TPWRS.2003.821629
42. Peppanen J, Reno MJ, Broderick RJ, Grijalva S (2016). Distribution system model
    calibration with big data from AMI and PV inverters. *IEEE TSG* 7(5):2497–2506.
    doi:10.1109/TSG.2016.2531994

**UNVERIFIED and not relied on:**

- an IEC 61000-4-30 Class S accuracy figure;
- Zamani & Baran 2018 (CVR meter placement);
- a 2025 thesis on wrongly registered tap positions;
- a smart-meter voltage-noise figure from Ashok et al. 2019.
