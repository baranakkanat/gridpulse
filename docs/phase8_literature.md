# Phase 8 literature: constraint-specific margins and data-error sensitivity

**Review.** A focused review (2026-10-19), targeted rather than systematic. It was run by
an AI-assisted research agent. Every DOI was checked on Crossref, and every arXiv id on
the arXiv API; seven DOIs were re-checked independently afterwards. It extends
`docs/phase7_literature.md` and does not repeat it.

**Flags.** As in Phase 7:

- *FULL:* the relevant full-text part was read.
- *ABS:* abstract or metadata only.
- *META:* bibliographic metadata only.
- *UNVERIFIED:* not relied on.

## 1. Separate margins per constraint are established

**Constraint tightening in robust and stochastic MPC.**

- **Mayne et al. (2005, *ABS*)**, tube MPC: plan the nominal trajectory and keep a reserve
  as large as the bounded disturbance can push the state.
- **Mayne et al. (2006, *ABS*)**: under output feedback, the reserve has two parts, one
  for the estimation error and one for the disturbance.
- **Hewing & Zeilinger (2018, *FULL* s. IV-C, Remark 5)**: tighten each constraint
  individually, using that constraint's own error distribution. The locator was
  corrected after the evaluation; s. III-C is the reachable-set construction.

**Chance-constrained OPF.**

- **Roald & Andersson (2018, *FULL* s. III–IV, VII-D):**
  - every voltage and every current constraint gets its own uncertainty margin
    (sensitivity × error spread × a quantile);
  - each type can have its own risk level;
  - the margins bound how *often* a violation occurs, not how *large* it is.
- **Mieth & Dvorkin (2018, *FULL* s. II):** separate risk levels for voltage, generation
  and flow constraints in a linearised distribution power flow. Flow limits are then
  omitted by assumption ("typically voltage-constrained"), so loading constraints are
  often absent from distribution chance-constrained OPF.

**Implication for Phase 8.**

- Phase 7's single normalised margin is the special case of equal tightening.
- Separate voltage and loading reserves are **established**. Phase 8 claims no method.
- The standard formulation is finer still: one margin per constraint, derived from
  sensitivities.

## 2. How injection errors reach voltages and loadings

- **Christakou et al. (2013, *FULL* introduction):** analytical sensitivities of node
  voltages and branch currents to nodal injections and to the slack voltage (tap) in
  radial networks.
- **Bolognani & Zampieri (2016, *ABS*):** a power flow linear in P and Q, with error
  bounds.
- **Implication.** To first order, metering errors map to voltage and loading errors
  through these sensitivities. A random error that is independent per customer largely
  cancels in feeder aggregates; a systematic error does not.

## 3. Metering errors and pseudo-measurements in distribution state estimation

- **Alimardani et al. (2015, *ABS*):** stale or unsynchronised smart-meter readings are
  handled by inflating each reading's variance.
- **Muscas et al. (2014, *ABS*):** correlations between measurements and pseudo-
  measurements change estimation quality.
- **Implication.** Systematic, common-mode errors are correlated errors. A margin
  derived only from variance underestimates them, which is why Phase 8 tests random and
  systematic errors separately.

## 4. Measurement-chain uncertainty

- **Asprou et al. (2014, *ABS*):** measurement weights that combine instrument-
  transformer and device uncertainty.
- **Muscas et al. (2016, *ABS*):** how voltage-estimate uncertainty depends on the
  installed measurement system.
- **Fatemi et al. (2023, arXiv, *FULL* s. 2–5).** A study with two German DSOs.
  - It assumes ±0.5 % busbar voltage and ±1 % current accuracy at digital secondary
    substations (taken as 3σ).
  - It states the DSOs' accuracy requirements separately: voltage ±1–2 %, line loading
    ±5–10 %.
  - These are assumptions, not field measurements.
  - Practitioners do state voltage and loading tolerances in their own units.

## 5. Operating envelopes under uncertainty

- **Liu & Braslavsky (2024, *ABS*):** robust dynamic operating envelopes hedged against
  uncertain customer load and generation.
- **Liu, Braslavsky & Mahdavi (2024, *FULL* s. I–III):** norm-ball uncertainty in
  forecasts and line impedances. It models voltage constraints only and has no
  measurement feedback.

## 5a. Added after the evaluation (review F): adaptive tightening and robustness

Every DOI below was checked on Crossref and every arXiv id on the arXiv API.

- **Online constraint tightening.** Tightening adapted online to the *observed* violation
  frequency is established. It is the closest prior art to C6:
  - Oldewurtel et al. 2013, applied to security-constrained OPF in 2015;
  - Korda et al. 2014;
  - Shi & Jones 2025;
  - in conformal prediction, Gibbs & Candès 2021;
  - this project's own Phase 4 online margin.
- **What C6 does differently.** It calibrates against the operator's own corrected
  replay, not against observed violations. Its calibration target therefore contains
  neither the model error nor the busbar error.
- **Partial and biased feedback break these guarantees.** Guarantees for semi-bandit
  (partly observed) feedback exist (Ge, Bastani & Bastani 2024). Conformal guarantees
  survive dispersive label noise but not biased noise (Einbinder et al. 2022). A busbar
  bias is exactly such a biased proxy.
- **Why constant offsets fail and conservatism helps.**
  - A constant offset cannot track a disturbance that varies in time: the internal model
    principle (Francis & Wonham 1976).
  - Conservatism buys robustness to unmodelled error (Bertsimas & Sim 2004).
- **What these explain in Phase 8.** The mv_daily failure and the protection a larger
  reserve gave are expected, not new.

## 6. Where Phase 8 stands

| Item | Status |
|---|---|
| Separate voltage and loading margins | Established (chance-constrained OPF, robust and stochastic MPC) |
| Splitting the reserve into estimation-error and disturbance parts | Established (Mayne et al. 2006) |
| Robust operating envelopes against injection uncertainty | Existing engineering solutions (Liu & Braslavsky 2024) |
| Chronological, out-of-sample test of a residual-corrected day-ahead LV PV-cap planner with separate reserves, reporting violation size and duration with curtailment | Not found in this targeted search |
| Reserve needs attributed to metering (random, systematic, missing, delayed) and busbar instrumentation errors on LV feeders | Not found in this targeted search |
| **Possible contribution** | A controlled benchmark and the attribution of failures to error sources. **Not a new method** |

## References

1. Mayne DQ, Seron MM, Raković SV (2005). Robust model predictive control of constrained
   linear systems with bounded disturbances. *Automatica* 41(2):219–224.
   doi:10.1016/j.automatica.2004.08.019 — ABS
2. Mayne DQ, Raković SV, Findeisen R, Allgöwer F (2006). Robust output feedback model
   predictive control of constrained linear systems. *Automatica* 42(7):1217–1222.
   doi:10.1016/j.automatica.2006.03.005 — ABS
3. Hewing L, Zeilinger MN (2018). Stochastic model predictive control for linear systems
   using probabilistic reachable sets. *IEEE CDC 2018*, 5182–5188.
   doi:10.1109/CDC.2018.8619554; arXiv:1805.07145 — FULL (s. III-C)
4. Roald L, Andersson G (2018). Chance-constrained AC optimal power flow: reformulations
   and efficient algorithms. *IEEE TPWRS* 33(3):2906–2918. doi:10.1109/TPWRS.2017.2745410
   — FULL (s. III–IV, VII-D). Also in `docs/literature_review.md`
5. Mieth R, Dvorkin Y (2018). Data-driven distributionally robust optimal power flow for
   distribution systems. *IEEE Control Systems Letters* 2(3):363–368.
   doi:10.1109/LCSYS.2018.2836870; arXiv:1803.04912 — FULL (s. II)
6. Christakou K, Le Boudec J-Y, Paolone M, Tomozei D-C (2013). Efficient computation of
   sensitivity coefficients of node voltages and line currents in unbalanced radial
   electrical distribution networks. *IEEE TSG* 4(2):741–750.
   doi:10.1109/TSG.2012.2221751; arXiv:1203.6798 — FULL (introduction)
7. Bolognani S, Zampieri S (2016). On the existence and linear approximation of the power
   flow solution in power distribution networks. *IEEE TPWRS* 31(1):163–172.
   doi:10.1109/TPWRS.2015.2395452 — ABS
8. Alimardani A, Therrien F, Atanackovic D, Jatskevich J, Vaahedi E (2015). Distribution
   system state estimation based on nonsynchronized smart meters. *IEEE TSG*
   6(6):2919–2928. doi:10.1109/TSG.2015.2429640 — ABS
9. Muscas C, Pau M, Pegoraro PA, Sulis S (2014). Effects of measurements and
   pseudomeasurements correlation in distribution system state estimation. *IEEE TIM*
   63(12):2813–2823. doi:10.1109/TIM.2014.2318391 — ABS
10. Asprou M, Kyriakides E, Albu M (2014). The effect of variable weights in a WLS state
    estimator considering instrument transformer uncertainties. *IEEE TIM*
    63(6):1484–1495. doi:10.1109/TIM.2013.2292138 — ABS
11. Muscas C, Pau M, Pegoraro PA, Sulis S (2016). Uncertainty of voltage profile in
    PMU-based distribution system state estimation. *IEEE TIM* 65(5):988–998.
    doi:10.1109/TIM.2015.2494619 — ABS
12. Fatemi A, Tischbein F, Wirtz F, Schmoger C, Dorendorf S, Schurtz A, Echternacht D,
    Ulbig A (2023). On the impact of smartification strategies for the state estimation
    of low voltage grids. *IEWT 2023*, Vienna. arXiv:2303.07964 (no DOI) — FULL (s. 2–5)
13. Liu B, Braslavsky JH (2024). Robust dynamic operating envelopes for DER integration in
    unbalanced distribution networks. *IEEE TPWRS* 39(2):3921–3936.
    doi:10.1109/TPWRS.2023.3308104 — ABS
14. Liu B, Braslavsky JH, Mahdavi N (2024). Linear OPF-based robust dynamic operating
    envelopes with uncertainties in unbalanced distribution networks. *J. Mod. Power
    Syst. Clean Energy* 12(4):1320–1326. doi:10.35833/MPCE.2023.000653;
    arXiv:2302.13472 — FULL (s. I–III)

15. Oldewurtel F, Sturzenegger D, Esfahani PM, Andersson G, Morari M, Lygeros J (2013).
    Adaptively constrained stochastic model predictive control for closed-loop constraint
    satisfaction. *ACC 2013*, 4674–4681. doi:10.1109/ACC.2013.6580560 — META
16. Oldewurtel F, Roald L, Andersson G, Tomlin C (2015). Adaptively constrained stochastic
    model predictive control applied to security constrained optimal power flow. *ACC
    2015*, 931–936. doi:10.1109/ACC.2015.7170853 — META
17. Korda M, Gondhalekar R, Oldewurtel F, Jones CN (2014). Stochastic MPC framework for
    controlling the average constraint violation. *IEEE TAC* 59(7):1706–1721.
    doi:10.1109/TAC.2014.2310066 — META
18. Shi J, Jones CN (2025). Disturbance-adaptive model predictive control for bounded
    average constraint violations. arXiv:2503.24169 — META (preprint)
19. Gibbs I, Candès E (2021). Adaptive conformal inference under distribution shift.
    *NeurIPS 2021*; arXiv:2106.00170 — META
20. Ge H, Bastani H, Bastani O (2024). Stochastic online conformal prediction with
    semi-bandit feedback. arXiv:2405.13268 — META (preprint)
21. Einbinder B-S, Feldman S, Bates S, Angelopoulos AN, Gendler A, Romano Y (2022). Label
    noise robustness of conformal prediction. arXiv:2209.14295 — META
22. Francis BA, Wonham WM (1976). The internal model principle of control theory.
    *Automatica* 12(5):457–465. doi:10.1016/0005-1098(76)90006-6 — META
23. Bertsimas D, Sim M (2004). The price of robustness. *Operations Research*
    52(1):35–53. doi:10.1287/opre.1030.0065 — META

**Not relied on.**

- *META only:* Chisci, Rossiter & Zappa 2001 (doi:10.1016/S0005-1098(01)00051-6);
  Farina, Giulioni & Scattolini 2016 (doi:10.1016/j.jprocont.2016.03.005).
- *UNVERIFIED:*
  - Liu & Braslavsky, arXiv:2404.03355 (journal acceptance not confirmed);
  - the IEC 61869 and IEC 61000-4-30 accuracy figures.
