# Phase 7 literature: offset correction, measurement-based voltage planning, margins, bias

**Review.** A focused, citation-checked review (2026-10-18), targeted rather than
systematic. It extends `docs/phase5_literature.md` and `docs/phase6_literature.md`.

**Flags.**

- *FULL:* the relevant full-text part was read.
- *ABS:* abstract or metadata only.
- *META:* bibliographic metadata verified on Crossref after the evaluation (review F); the
  content is described from the title and the reviewer's reading, not read here.
- *UNVERIFIED:* not relied on.

**Post-evaluation additions** (review F, 2026-10-18): references 17–21 and the operating-
envelope section 2a. The Ortmann et al. description was corrected: SYSLAB is a laboratory
grid.

## 1. Correcting a model from a persistent measured offset

**Removing persistent plant–model offsets** by estimating a disturbance and shifting the
model's predictions is decades-old control practice.

- The canonical offset-free MPC references are Muske & Badgwell (2002) and Pannocchia &
  Rawlings (2003).
- Pannocchia & Rawlings show that one integrating disturbance per *measured* variable is
  enough for zero offset at those outputs.
- Kuntz & Rawlings (2024, arXiv, *FULL* §1–2) combine a disturbance estimator with
  constraint back-offs. Their guarantees hold only for small enough mismatch.
- Disturbance-observer-based control lumps disturbance and uncertainty into one estimated
  "total disturbance" (Chen et al. 2016).

**Implication for Phase 7.**

- The `ResidualCorrector` is this technique: a bias update estimated from busbar and
  current residuals, with a fixed back-off (the safety margin). It is not a new method.
- The offset can be removed exactly only at measured outputs. At unmetered buses the
  correction is an *extrapolation* through the model. That extrapolation is valid for
  errors common to the feeder (tap, MV voltage), not for local ones.

## 2. Measurement-based voltage control in LV grids

- **Online feedback optimisation** is surveyed in Hauswirth et al. (2024).
- **Ortmann et al. (2020, *FULL*)** found that dispatch from a well-parameterised OPF
  still left a persistent voltage violation on a real laboratory distribution grid
  (SYSLAB, DTU Risø), which feedback removed. The
  authors suggest that disturbance observers or model adaptation could also be used, but
  do not test it.
- **Procopiou & Ochoa (2017)** estimate feeder-end voltages from substation measurements
  and a generic feeder model, for OLTC control without remote monitoring. This is the
  **closest prior work**: substation data used for estimation, not to correct a planning
  model's constraint margins.
- **Bassi et al. (2023)** compute LV voltages without a network model, from smart-meter
  data.
- **Gupta, Buason & Molzahn (2024)** set day-ahead PV limits with conservative
  power-flow approximations. Their conservatism comes from scenarios, not from measured
  feedback.

## 2a. Operating envelopes (added after the evaluation)

Day-ahead PV caps are a form of operating envelope: a time-varying export limit per
customer or feeder.

- **Petrou et al. (2021, *META*)** set dynamic operating limits for prosumers to keep the
  network within its limits.
- **Bassi et al. (2023, ISGT-LA, *META*)** compute operating envelopes from smart-meter
  data without a network model.
- **Kumarawadu et al. (2025, *META*)** derive dynamic operating envelopes from smart-meter
  data.
- **Not checked:** whether any of these corrects a planning model with substation
  residuals. Phase 7 claims no novelty against this literature.

## 3. Continuous margins and severity

- **Navarro-Espinosa & Ochoa (2016, *FULL*)** use two probabilistic metrics: EN 50160
  compliance on 10-min averages per customer, and a feeder-level probability that at
  least 1 % of customers are affected.
- **Jain et al. (2020)** use time-aware, duration-sensitive violation metrics over yearly
  time series.
- **Dall'Anese, Baker & Summers (2017)** enforce voltage limits with a prescribed
  probability, using distribution-free bounds. This is the probabilistic counterpart to a
  margin.
- **Not found:** a standard continuous "voltage violation severity index". Phase 7
  therefore reports signed margins, magnitude, duration and frequency separately, in their
  own units.

## 4. Meter bias and identifiability

- **Pegoraro et al. (2022)** estimate systematic instrument errors jointly with line
  parameters and tap ratios. They do so by modelling the measurement chain, with PMUs on
  transmission test systems. This is the clearest treatment of bias confounded with tap
  errors.
- **Pegoraro et al. (2019, *META*)** compensate systematic measurement errors, including
  instrument transformers, in a PMU-based monitoring system for *distribution* grids. This
  is closer to Phase 7's busbar-bias question than the 2022 transmission paper.
- **Peppanen et al. (2016, *META*)** calibrate distribution system models from AMI and PV
  inverter data.
- **Blakely, Reno & Ashok (2019)** report biased meters in AMI data (see
  `docs/phase6_literature.md`).
- **Instrument accuracy classes.** The ±0.002 and ±0.005 p.u. busbar biases were chosen
  to resemble the ratio-error limits of class 0.2 and 0.5 voltage transformers, as quoted
  by secondary sources. They were not checked against IEC 61869-3. An LV busbar is often
  measured directly, so the relevant figure is the accuracy of the whole measurement
  chain (UNVERIFIED; not relied on).
- **Implication.** Without a trusted reference, a bias common to all meters cannot be
  separated from an MV-voltage offset. With a trusted busbar measurement, a single meter's
  disagreement can be detected, but not attributed: bias and a local model error look the
  same. Hence the INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS label.

## 5. Primary voltage and secondary models from AMI

- **Netto et al. (2021)** estimate the primary-side voltage of service transformers from
  two smart meters, with a maximum relative error of about 3.9 % (*ABS*).
- **Short (2013)** estimates secondary impedances and primary voltage profiles by
  regression on AMI data.
- **Not found:** MV/LV tap estimation from secondary-substation busbar data.

## 6. Runtime assurance

- Only a single-author, non-peer-reviewed preprint was found (Xie 2026). It argues for
  runtime monitoring and evidence before deployment of AI in power systems.
- No peer-reviewed runtime-assurance work for DSO decision support was found.

## 7. Where Phase 7 stands

| Item | Status |
|---|---|
| Offset correction / bias update | Established (offset-free MPC, DOBC) |
| Substation-based LV voltage estimation | Established for OLTC control (Procopiou & Ochoa 2017) |
| Day-ahead LV PV caps corrected by substation-residual offsets | Not found in a targeted search. Operating envelopes (s. 2a) are the closest framing; checked at metadata level only |
| Comparison of binary-count with continuous residual feedback for voltage margins | Not found |
| Bias detection against a trusted busbar reference; non-identifiability vs local model error | Concept known (Pegoraro 2019, distribution/PMU; Pegoraro 2022, transmission/PMU); not found for AMI + busbar in LV planning |
| Possible contribution | A benchmark comparison of this project's count feedback with a standard offset correction, and the busbar-bias dependence quantified. The common-mode/local split is argued, not tested. **Not a new method** |

## References

1. Muske KR, Badgwell TA (2002). Disturbance modeling for offset-free linear model
   predictive control. *J. Process Control* 12(5):617–632.
   doi:10.1016/S0959-1524(01)00051-8 — ABS
2. Pannocchia G, Rawlings JB (2003). Disturbance models for offset-free model-predictive
   control. *AIChE J* 49(2):426–437. doi:10.1002/aic.690490213 — ABS
3. Kuntz SJ, Rawlings JB (2024). Offset-free model predictive control: stability under
   plant-model mismatch. arXiv:2412.08104 — FULL (abstract, s. 1–2; a v2 is dated
   2025-09-01)
4. Chen W-H, Yang J, Guo L, Li S (2016). Disturbance-observer-based control and related
   methods—an overview. *IEEE TIE* 63(2):1083–1095. doi:10.1109/TIE.2015.2478397 — ABS
5. Hauswirth A, He Z, Bolognani S, Hug G, Dörfler F (2024). Optimization algorithms as
   robust feedback controllers. *Annu. Rev. Control* 57:100941.
   doi:10.1016/j.arcontrol.2024.100941 — ABS
6. Procopiou AT, Ochoa LF (2017). Voltage control in PV-rich LV networks without remote
   monitoring. *IEEE TPWRS* 32(2):1224–1236. doi:10.1109/TPWRS.2016.2591063 — ABS
7. Bassi V, Ochoa LF, Alpcan T, Leckie C (2023). Electrical model-free voltage
   calculations using neural networks and smart meter data. *IEEE TSG* 14(4):3271–3282.
   doi:10.1109/TSG.2022.3227602 — ABS
8. Gupta RK, Buason P, Molzahn DK (2024). Fairness-aware photovoltaic generation limits for
   voltage regulation in power distribution networks using conservative linear
   approximations. *IEEE TPEC 2024*. doi:10.1109/TPEC60005.2024.10472277 — ABS
9. Ortmann L, et al. (2020). Experimental validation of feedback optimization in power
   distribution grids. *EPSR* 189:106782. doi:10.1016/j.epsr.2020.106782 — FULL
10. Navarro-Espinosa A, Ochoa LF (2016). Probabilistic impact assessment of low carbon
    technologies in LV distribution systems. *IEEE TPWRS* 31(3):2192–2203.
    doi:10.1109/TPWRS.2015.2448663 — FULL
11. Jain AK, Horowitz K, Ding F, Sedzro KS, Palmintier B, Mather B, Jain H (2020). Dynamic
    hosting capacity analysis for distributed photovoltaic resources: Framework and case
    study. *Applied Energy* 280:115633. doi:10.1016/j.apenergy.2020.115633 — ABS
12. Dall'Anese E, Baker K, Summers T (2017). Chance-constrained AC optimal power flow for
    distribution systems with renewables. *IEEE TPWRS* 32(5):3427–3438.
    doi:10.1109/TPWRS.2017.2656080 — ABS
13. Pegoraro PA, Sitzia C, Solinas AV, Sulis S (2022). PMU-based estimation of systematic
    measurement errors, line parameters, and tap changer ratios in three-phase power
    systems. *IEEE TIM* 71:1–12. doi:10.1109/TIM.2022.3165247 — ABS
14. Netto M, Hao J, Padullaparti H, Krishnan V (2021). On the use of smart meter data to
    estimate the voltage magnitude on the primary side of distribution service
    transformers. *IEEE PESGM 2021*. doi:10.1109/PESGM46819.2021.9638041 — ABS
15. Short TA (2013). Advanced metering for phase identification, transformer
    identification, and secondary modeling. *IEEE TSG* 4(2):651–658.
    doi:10.1109/TSG.2012.2219081 — ABS
16. Xie Y (2026). Safety assurance of AI-enabled power cyber-physical systems: a
    power-system-centric critical review. engrXiv. doi:10.31224/7160 — ABS (preprint, not
    peer-reviewed)
17. Pegoraro PA, Brady K, Castello P, Muscas C, von Meier A (2019). Compensation of
    systematic measurement errors in a PMU-based monitoring system for electric
    distribution grids. *IEEE TIM* 68(10):3871–3882. doi:10.1109/TIM.2019.2908703 — META
18. Peppanen J, Reno MJ, Broderick RJ, Grijalva S (2016). Distribution system model
    calibration with big data from AMI and PV inverters. *IEEE TSG* 7(5):2497–2506.
    doi:10.1109/TSG.2016.2531994 — META
19. Petrou K, Procopiou AT, Gutierrez-Lagos L, Liu MZ, Ochoa LF, Langstaff T, Theunissen JM
    (2021). Ensuring distribution network integrity using dynamic operating limits for
    prosumers. *IEEE TSG* 12(5):3877–3888. doi:10.1109/TSG.2021.3081371 — META
20. Bassi V, Ochoa LF, Alpcan T, Leckie C, Liu MZ (2023). Smart meter data and operating
    envelopes in LV networks: a model-free approach. *IEEE PES ISGT Latin America 2023*,
    pp. 1–5. doi:10.1109/ISGT-LA56058.2023.10328319 — META
21. Kumarawadu A, Azim MI, Khorasany M, Razzaghi R, Heidari R (2025). Smart meter
    data-driven dynamic operating envelopes for DERs. *Applied Energy* 384:125469.
    doi:10.1016/j.apenergy.2025.125469 — META

**UNVERIFIED and not relied on:**

- an OSTI over-voltage severity index (OSTI 1820341);
- Rigoni & Keane 2017;
- Cutler & Ramaker 1980 (DMC).
