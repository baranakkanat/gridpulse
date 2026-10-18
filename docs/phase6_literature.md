# Phase 6 literature: noise-aware alarms, noisy feedback, bad data, sensor value

**Review.** A focused, citation-checked review (2026-10-18), targeted rather than
systematic. It extends `docs/phase5_literature.md`.

**Flags.**

- *FULL:* the relevant part of the full text was read.
- *ABS:* abstract or metadata only.
- *UNVERIFIED:* not traced to the source; not relied on.

## 1. Deciding "limit exceeded" from uncertain readings

**Guard bands are standard metrology** (JCGM 106:2012 s. 8.3, *FULL*; ILAC-G8:09/2019
s. 4 and Table 1, *FULL*; Eurachem/CITAC 2021 s. 4.3, *FULL*).

- A guard band w = rU moves the decision limit by a multiple of the expanded uncertainty
  U = 2u.
- *Guarded rejection* puts it outside the tolerance limit, so an exceedance is declared
  only with clear evidence. r = 1 (w = 2u) is the common choice.
- Guard bands trade false accepts against false rejects. For a one-sided limit with
  normal errors, w = 2u gives a false-alarm probability of about 2.3 %.
- **No application to smart-meter voltage alarms was found.**

**Grid practice aggregates in time before judging a voltage limit.**

- EN 50160 judges LV supply voltage on 10-min RMS means over a week: 95 % within
  Un ± 10 %. Source: the ECI application note Cu0147, which reproduces the standard,
  *FULL*.
- EN 50549-1 s. 4.9.3.4 trips inverters on a moving 10-min mean. Source: a test report
  reproducing the clause, *FULL* (secondary).
- VDE FNN 2025 recommends 1-min or rolling 10-min means for grid-state determination
  (*FULL*).

**Persistence ("n consecutive samples") and on-delay alarm rules** have a known trade-off
between false alarms, missed alarms and detection delay (Adnan, Izadi & Chen 2011, *FULL*).

## 2. Smart-meter voltage accuracy

- **VDE FNN Hinweis 2025** (*FULL*): required voltage accuracy f_U = 2.0 % of Un at the
  99th percentile. That is σ ≈ 0.008–0.009 p.u. if errors are normal.
- **A US utility filing** (Kentucky PSC case 2025-00131, *FULL*):
  - AMI voltage is reported as 15-min averages;
  - the meters are ANSI C12.20 class 0.2, which is an energy class;
  - voltage accuracy is ±1 % by manufacturer specification.
- **Not found:** a voltage accuracy class for smart meters. IEC 62053 and EN 50470
  specify energy accuracy only.
- **Implication for Phase 6** (corrected after the post-evaluation review).
  - The specifications bound the voltage error at about σ ≤ 0.008 p.u. A ±1 %
    specification read as a 2–3σ error limit gives σ ≈ 0.003–0.005.
  - So the Phase 5 value σ = 0.01 p.u., independent per reading, is pessimistic, not
    typical.
  - True violations are mostly smaller even than that: median overshoot 0.001–0.014 p.u.
    on development days. Single readings cannot separate most of them from noise.

## 3. Online calibration with noisy feedback

- **Wang, Zecchin & Simeone 2026**, *Online conformal prediction with corrupted
  feedback*, arXiv:2605.20515 (*FULL*).
  - The long-run bias of online conformal calibration depends on the imbalance between
    0→1 and 1→0 flips of the feedback.
  - They propose filtering and active compensation.
  - This is the mechanism behind Phase 5's noise confound: false alarms are 0→1 flips
    and push τ upward.
- **Einbinder et al. 2024** (*JMLR*, see `docs/phase5_literature.md`): calibration on
  noisy labels is conservative on the true labels.
- **Xi et al. 2025** (NeurIPS, *ABS*) and **Sesia, Wang & Tong 2025** (*JRSS-B*, *ABS*):
  corrections that assume a known, uniform noise rate. Here the flip rate depends on how
  close the true voltage is to the limit, so those assumptions do not hold.
- **The online update itself:** Gibbs & Candès 2021 (*ABS*); Feldman et al. 2023 (TMLR,
  *ABS*).

## 4. Bad-data tests with pseudo-measurements

- **The tests work only with redundancy.** Chi-square and largest-normalised-residual
  tests need measurement redundancy. They are weak when pseudo-measurements dominate, and
  high-variance pseudo-measurements can ill-condition the problem (Dehghanpour et al.
  2019, *FULL*).
- **A field test needed near-full meter coverage.** Normalised residuals detected bad
  data in an LV field test with almost every customer metered (Waeresch et al. 2017,
  *ABS*).
- **Structural model errors need residuals over time.** Distribution-grid chi-square
  tests perform poorly on structural errors, which are found from residual patterns over
  time instead (Castin et al. 2026, CIRED, *FULL* intro; Vanin & Van Hertem 2022, *FULL*).
- **Classical parameter and tap observability:** Zhu & Abur 2006; Lin & Abur 2018; Korres
  et al. 2004 (see `docs/phase5_literature.md`).

## 5. Model mismatch from smart-meter data

- PV inverter reactive-power settings can be recovered from AMI net-load data (Talkington
  et al. 2022, *IEEE TPWRS*, *ABS*).
- Voltage-regulator taps can be estimated from AMI data (Yusuf, Azzolini & Reno 2022,
  KPEC, *ABS*).
- **Not found:** estimation of MV/LV transformer tap positions from smart-meter data
  alone.

## 6. Sensor value

Sensor value for decisions and value of information: Krause & Guestrin 2009; Pau et al.
2024; Mieth et al. 2025; Kekatos et al. 2026 (see `docs/phase5_literature.md`).

- Buason et al. 2024 assume "accurate and noise-free" sensors (*FULL* check). Their alarm
  thresholds therefore ignore measurement noise.
- JCGM 106 s. 9.5.6 (*FULL*): better metrology reduces both decision risks. Measurement
  quality is therefore part of a sensor's value.
- Common random numbers are standard variance reduction for simulation comparisons
  (Glasserman & Yao 1992, *Management Science* 38(6):884–908, *ABS*).

## 7. Where Phase 6 stands

| Item | Status |
|---|---|
| Guard band | Standard metrology; not found applied to smart-meter voltage alarms |
| Persistence / temporal aggregation | Standard grid and alarm practice |
| Chi-square bad-data test | Textbook; known to be weak with low redundancy and pseudo-measurements |
| Noise-driven bias of online calibration | Mechanism known in general ML (Wang et al. 2026). Not found for count-based conformal feedback in curtailment |
| Common random numbers | Standard |
| Possible contribution | A controlled benchmark showing how meter noise interacts with count-based feedback for PV curtailment. A standard persistence rule removes the noise-driven over-curtailment under the correct model, for independent per-reading noise only; it does not fix the reliability side. Not a new method |

## References

1. JCGM 106:2012. *Evaluation of measurement data – The role of measurement uncertainty in
   conformity assessment*. BIPM. https://www.bipm.org/documents/20126/2071204/JCGM_106_2012_E.pdf
   — FULL
2. ILAC-G8:09/2019. *Guidelines on Decision Rules and Statements of Conformity*. ILAC.
   https://ilac.org/?ddownload=122722 — FULL
3. Eurachem/CITAC (2021). *Use of Uncertainty Information in Compliance Assessment*, 2nd
   ed. https://www.eurachem.org/images/stories/Guides/pdf/MUC2021_P1_EN.pdf — FULL
4. Klajn A, Bątkiewicz-Pantuła M (2013). *Application Note – Standard EN 50160*. European
   Copper Institute, Cu0147.
   https://leonardo-energy.pl/wp-content/uploads/2016/07/EIM01201-Norma-EN-50160-ang..pdf
   — FULL
5. VDE FNN (2025). *Hinweis: Standardisiertes Vorgehen für die Durchführung der
   Netzzustandsermittlung … Sensitivität und Spezifität*, V1.0.
   https://www.vde.com/resource/blob/2383942/463b8b623a5394e189434660ce2dc7e6/vde-fnn-hinweis-netzustandsermittlung-data.pdf
   — FULL
6. Louisville Gas & Electric / Kentucky Utilities (2025). Responses to data requests,
   Kentucky PSC case 2025-00131 (filed 2025-06-27). Public case files at
   https://psc.ky.gov/ (case 2025-00131) — FULL
7. Adnan NA, Izadi I, Chen T (2011). Computing detection delays in industrial alarm
   systems. *ACC 2011*, 786–791. doi:10.1109/ACC.2011.5991505 — FULL
8. Wang B, Zecchin M, Simeone O (2026). Online conformal prediction with corrupted
   feedback. arXiv:2605.20515 — FULL
9. Xi H, Liu J, Zeng H, Sun M, Wei H (2025). Exploring the noise robustness of online
   conformal prediction. NeurIPS 2025. arXiv:2501.18363 — ABS
10. Sesia M, Wang YXR, Tong X (2025). Adaptive conformal classification with noisy labels.
    *JRSS-B* 87(3):796–815. doi:10.1093/jrsssb/qkae114 — ABS
11. Gibbs I, Candès E (2021). Adaptive conformal inference under distribution shift.
    NeurIPS 2021. arXiv:2106.00170 — ABS
12. Dehghanpour K, Wang Z, Wang J, Yuan Y, Bu F (2019). A survey on state estimation
    techniques and challenges in smart distribution systems. *IEEE TSG* 10(2):2312–2322.
    doi:10.1109/TSG.2018.2870600 — FULL
13. Waeresch D, et al. (2017). Field test of a linear three-phase LV state estimation
    system based on smart meter data. *CIRED OAP* 2017(1):1773–1776.
    doi:10.1049/oap-cired.2017.0327 — ABS
14. Castin, et al. (2026). Detection of topological errors in distribution networks using
    state estimation residual patterns. CIRED 2026, paper 1423 — FULL (abstract,
    introduction). https://orbi.uliege.be/bitstream/2268/342287/1/Fullpaper_Theme2_1423_Castin.pdf
15. Vanin M, Van Hertem D (2022). The role of state estimation in the improvement of LV
    distribution network models. IEEE Smart Grid Bulletin, October 2022.
    https://smartgrid.ieee.org/bulletins/october-2022/the-role-of-state-estimation-in-the-improvement-of-low-voltage-distribution-network-models
    — FULL
16. Talkington S, Grijalva S, Reno MJ, Azzolini JA (2022). Solar PV inverter reactive power
    disaggregation and control setting estimation. *IEEE TPWRS* 37(6):4773–4784.
    doi:10.1109/TPWRS.2022.3144676 — ABS
17. Yusuf J, Azzolini JA, Reno MJ (2022). Data-driven methods for voltage regulator
    identification and tap estimation. *KPEC 2022*. doi:10.1109/KPEC54747.2022.9814721 —
    ABS
18. Glasserman P, Yao DD (1992). Some guidelines and guarantees for common random numbers.
    *Management Science* 38(6):884–908. doi:10.1287/mnsc.38.6.884 — ABS
19. Picallo M, Bolognani S, Dörfler F (2020). Closing the loop: Dynamic state estimation
    and feedback optimization of power grids. *EPSR* 189:106753.
    doi:10.1016/j.epsr.2020.106753 — ABS
20. Ortmann L, et al. (2020). Experimental validation of feedback optimization in power
    distribution grids. *EPSR* 189:106782. doi:10.1016/j.epsr.2020.106782 — ABS

**Added after the post-evaluation novelty review** (verified by the reviewer against
primary records):

21. Kreuwel et al. (2021). *Solar Energy* 227:312–320. doi:10.1016/j.solener.2021.09.009
    — ABS. Per the reviewer: over 200,000 AMI overvoltage events with a typical duration
    of about 5 min. The title was not recorded here.
22. Blakely L, Reno MJ, Ashok K (2019). *IEEE PVSC 2019*.
    doi:10.1109/PVSC40753.2019.8981211 — ABS. AMI data quality, including biased meters
    (Sandia). The title was not recorded here.
23. Braunstein, Bretas, Rossoni & Bretas (2015). *IEEE PES General Meeting 2015*.
    doi:10.1109/PESGM.2015.7286541 — ABS. Bad-data analysis in distribution state
    estimation. The title was not recorded here.
24. JCGM 100:2008. *Evaluation of measurement data – Guide to the expression of
    uncertainty in measurement*, s. 3.2. Only random effects shrink with repeated
    observation; systematic effects do not.
    https://www.iso.org/sites/JCGM/GUM/JCGM100/C045315e-html/C045315e_FILES/MAIN_C045315e/03_e.html
    — FULL (reviewer)

**UNVERIFIED and not relied on:**

- a 30-min default for GB SMETS2 voltage averaging;
- an IEC 61000-4-30 Class S voltage uncertainty figure;
- BSI TR-03109 TAF 10 voltage accuracy.
