# Research note: decision-sufficient asset information under uncertain thermal ratings (Mission 12, Stage A)

**Status.**
- EXPLORATORY, internally pre-specified (protocol `analysis/asset_rating_information/stage_a_protocol.md`, as-executed text sha256 `9fc9108c…`, with dated amendments A1–A5 appended after the first scored computation).
- Six SimBench LV networks; every one has been examined in earlier phases, so nothing here is confirmatory. Not externally preregistered, not peer reviewed.
- **Every number below is read from local artefacts:**
  - `analysis/asset_rating_information/results/stage_a_summary.json` and `results/eval_<network>_<model>.json`;
  - `results/verdicts.json`, `results/control_d.json` and `results/control_e_*.json`.

  The exceptions are two zero-solve board audits archived with their outputs in `docs/provenance/mission12_board_audit/` (`audit_rankings.py`, `audit_b9_stop.py`).
- The SimBench-derived artefacts stay local.
- Written by the board (Research Lead) on 2026-10-25. The post-experiment QA status is in §XIV.
- **Data attribution:** contains information from [SimBench](https://simbench.de), which is made available here under the [Open Database License (ODbL 1.0)](https://opendatacommons.org/licenses/odbl/1-0/). See [`analysis/asset_rating_information/DATA_ATTRIBUTION.md`](../analysis/asset_rating_information/DATA_ATTRIBUTION.md).

**What "rating", "unsafe" and "safe" mean here** (protocol §0):
- **The rating** is a static admissibility threshold on line current or transformer apparent power. It is not a temperature, not a dynamic rating, and not an IEC 60287 ampacity.
- **"Unsafe"** means the simulated loading exceeds an *assumed* true static rating by more than 0.5 %.
- **No claim about real thermal safety, overheating, damage or asset life is made anywhere in this note.**

**Four distinctions (eight terms) this note keeps apart throughout:**

| This study measures or assumes | It does **not** measure or claim |
|---|---|
| **Per-draw recovery R:** the mean over truth draws of (policy − B2) / (oracle − B2). The pre-registered verdict statistic | **Energy-weighted recovery:** the share of the total lost MWh recovered. A secondary, descriptive statistic (A5); often much lower |
| **Simulated exceedance** of an *assumed* static rating ("unsafe") | **Physical overheating,** conductor temperature, damage or ageing: not modelled, not measured |
| **A rating-only uncertainty:** the same cable, the same impedance, a wrong recorded threshold | **A physically different cable** (another type or cross-section), which would also change impedance and therefore the electrical state (Control E, Mission 10) |
| **Robustness under a correctly specified uncertainty set:** the lower-bound policy never exceeds an assumed rating, by construction | **Failure under a misspecified set:** when the true errors are wider than assumed, the "robust" policy exceeds them in 43–84 % of draws (U2′) |

**The unobservability result is narrow.** Control D shows that, in this study's power-flow model with its electrical parameters unchanged, an independent rating-only parameter has no effect on any simulated voltage or current. So no estimator that uses only those electrical quantities can identify it. That does **not** extend to:
- thermal measurements (conductor or sheath temperature, distributed temperature sensing), which carry information about a thermal limit through a thermal model;
- asset-identification methods: record audits, inspection, or cable-type identification. A wrong cable type usually also changes impedance and is then electrically visible.

---

## I. Executive summary

**What was investigated.** Mission 11 found that thermal limits, not voltage, bind first in all six SimBench LV networks. Mission 12 asked the next question:
- When the recorded static ratings of LV assets may be wrong while the electrical model is right, which asset information is necessary and sufficient for a safe, useful PV-export decision?
- When does verifying an asset's rating pay off, and when is it worthless despite large numerical uncertainty?

The decision is GridPulse's uniform PV feed-in cap (11 levels), taken every daylight quarter-hour of a year. Ratings enter only as admissibility thresholds.

**The strongest results:**
1. **Rating uncertainty matters only where cables bind** (H1, descriptive). Losses are 0–0.015 % on one side and 1.6–5.3 % on the other, but the cable-limited losses mostly fall short of the pre-specified relevance threshold. Under independent ±20 % cable-rating uncertainty (U2), the robust lower-bound policy B2 loses:
   - **0 %, 0 % and 0.015 %** of the oracle's export on the three transformer-limited networks, where every single-cable value of information is exactly 0;
   - **5.28 %, 1.60 % and 2.47 %** on the three cable-limited networks (semiurb4, semiurb5, urban6).

   **H1's pre-specified relevance rule (loss ≥ 3 %) is met on semiurb4 only** (`relevant_by_H1_rule = false` for semiurb5 and urban6). The §12 stop rule (< 1 %) does not fire.

   Why are these losses below the audit's full-year robust-against-recorded losses (8.3 % and 7.3 %)? Because the denominator here is the **oracle**, not the record. Under U2 the oracle is itself limited by the weakest true rating among the co-blocking segments, so B2 sits closer to it than to the records.

   The decision is identical at the lowest and the highest plausible ratings (Situation 1) on 99.9–100 % of evaluation steps in the transformer-limited networks, and on 79–86 % in the cable-limited ones.
2. **A rating-only error leaves no trace in the simulated electrical state** (H2, Control D). With the electrical model unchanged, changing one cable's rating changes neither a bus voltage nor a line current (|Δ| = 0.0 exactly).
   - So every step where the uncertainty changes the decision (Situation 2) cannot be resolved by any estimator that uses only voltages and currents: Situation 3 for such estimators.
   - The information has to come from outside the electrical state: records, inspection, or thermal sensing. Thermal sensing was not studied.
3. **Trusting the records produces exceedances; the robust bound avoids them but is conservative; the sampled scenario-robust policy is neither exceedance-free nor better.** All exceedances are simulated, against assumed ratings.
   - Under U2, the record-trusting policy B0 exceeds an assumed true rating on at least one step in 94.5–100 % of truth draws, with a severity p95 of 22.7–23.9 % above that rating.
   - B2 never exceeds an assumed rating, by construction under the correctly specified set.
   - Scenario-robust B3 gains at most 0.39 MWh over B2, and is unsafe on semiurb4 in 2.5 % of draws (up to 17 steps): the finite-sample risk §8 predicted.
   - **When the records are in fact correct (U0), B2 gives up 7.6–9.9 % of export:** the price of distrust.
4. **A handful of targeted verifications recovers much of the loss, but how much depends on the statistic** (H3c and H5 SUPPORTED under the pre-registered statistic).

   | Verify the **four** most-loaded cables (B6) | semiurb4 | semiurb5 | urban6 |
   |---|---|---|---|
   | Mean per-draw recovery R (pre-registered) | 0.90 | 0.59 | 0.55 (fragile) |
   | Share of the **total lost energy** recovered | **0.82** | **0.38** | **0.22** |

   - The two diverge because draws with a small gap are recovered almost fully, while the draws that lose the most energy need more cables.
   - Random verification recovers 0.3–37 % (per-draw) or 0.1–26 % (energy).
   - Six verifications recover 95 % per-draw and 85 % of the energy on urban6.
   - On semiurb5, eight verifications recover only 40 % of the energy: the gap there is spread thinly over many cables.
5. **The simplest ranking is as good as the value-of-information search** (Control I: "a simple heuristic suffices"; H3b REJECTED).
   - The loading rank (B6), the binding-count rank (B7) and the myopic VoI greedy (B8) choose **identical** cables in identical order on every cable-limited combination. The greedy's expected gain is strictly positive at every step, so this is agreement, not a tie-break artefact.
   - Neither the pair look-ahead (B8P) nor the structural route rule (B9) beats them: the smallest gaps over k = 2–4 are 0.00, −0.04 and −0.06.
6. **Single-cable value of information badly understates joint value** (series co-blocking).
   - The sum of single-cable VoI is **7.4 %, 0.36 % and 0.47 %** of the value of verifying the whole candidate pool. Most cables are individually worthless and jointly essential.
   - The pre-registered H3a prediction (R₁ ≤ 0.10) held on semiurb5 (0.013) and urban6 (0.033), but **failed on semiurb4 (0.27), where one cable alone recovers 27 %**. H3a is formally REJECTED, and the rejection is fragile.
7. **When the uncertainty interval itself is too narrow, verification becomes a safety repair.** This is robustness under a correctly specified set failing under a misspecified one.
   - Under prior misspecification U2′ (true w = 0.3, believed 0.2), the "robust" B2 exceeds an assumed true rating in **43 %, 84 % and 56.5 %** of draws.
   - Four loading-ranked verifications cut this to **12.5 %, 55 % and 21 %**; random verification does not (60 %, 86 % and 56 %).
   - The recovery statistic is meaningless there, because the oracle exports *less* than B2 in 53–163 of 200 draws.

**Did the hypotheses survive?**

| Hypothesis | Verdict |
|---|---|
| H1 | Descriptive, as expected. semiurb5's loss is 1.6 %, below the anticipated ≥ 3 %. |
| H2 | Analytic, confirmed by Control D. |
| H3a | REJECTED, fragile. |
| H3b | REJECTED. |
| H3c | SUPPORTED. |
| H4 | SUPPORTED on semiurb4 (5 of 42 cables, 98.0 % of draws) and urban6 (6 of 57, 95.5 % of draws: a margin of 0.005 over the 95 % criterion, so fragile). On semiurb5, no set of size ≤ 6 is found **within the top-10 pool**. The top-10 restriction binds on semiurb5 and on urban6. |
| H5 | SUPPORTED. The verdict is fragile, because it rests on urban6 (margin 0.049 over 0.50, below 2·SE = 0.052). |

**Timing of the amendments:**
- A1–A3, the scoring-harness fixes, were made before any verdict existed, and each triggered a full re-run.
- A4 and A5 were written after `verdicts.json`. They are disclosure-only read-out corrections that edit no frozen code and change no verdict.

**Bottom line.** In this benchmark, a safe and useful export decision under uncertain cable ratings needs **no learned model and no sophisticated information policy**:
- a robust lower bound plus verification of the most-loaded cables is the best available policy;
- no tested alternative did better;
- how many cables suffice is network-specific: 4 on semiurb4, about 6 on urban6, and more than 8 on semiurb5 by the energy measure.

The scientifically interesting residue is twofold:
- the complementarity structure (single-asset VoI is nearly blind);
- the misspecification failure mode (the robust bound is only as safe as its interval).

**Recommendation (§XVIII): PIVOT** to verification under a misspecified uncertainty set.

---

## II. Physical insight: why an accurate electrical model can carry a wrong safety threshold

**Ratings are thresholds, not physics.**
- A power flow computes voltages and currents from injections, impedances and topology: V = f(P, Q, Z, topology) and I = h(·).
- A cable's static rating r_l does not appear in either function. It enters only afterwards, as the admissibility test |I_l| ≤ r_l.
- So, as long as the cable itself is the one the model assumes, a record that overstates or understates its rating changes **nothing** in the simulated voltages and currents: nothing a voltmeter, a smart meter or a state estimator working from electrical quantities could see.
- A thermal measurement (conductor or sheath temperature) is a different channel and is not covered by this argument.
- **Control D** confirms this on the one network tested (urban6, day 144, at cap level index 0, i.e. c = 1.0, uncapped):
  - with line 33's rating reduced by 20 %, all 59 bus voltages and all 57 line currents agree with the nominal solve to 0.0 (tolerance 1e-9 relative);
  - only `loading_percent`, the current divided by the rating, changes, by exactly 20 % on that line.

**Where do wrong records come from?** The literature (§III) documents missing and default-valued cable data in DSO databases. The physical permissible current depends on burial depth, soil thermal resistivity, grouping and ambient temperature (IEC 60287), none of which a static record captures.
- The study does **not** model any of these. It treats r_true / r_rec = ρ as an assumed stress distribution (§V).
- That is the main limit on how far the result transfers to real cables (§XIII).

**An impedance error is different.** Control E compares the Phase 8 `line_local` cache (one cable at R × 1.5 **and** rating × 0.8) with the nominal cache over the full year:
- The electrical state moves: the largest bus-voltage change per network is 0.0025–0.0063 p.u.
- Even so, of the step-levels where the modified cable is truly over 100.5 %, most look ≤ 100 % to the nominal model:

  | Network | Share of true overloads invisible to the nominal model |
  |---|---|
  | semiurb4 | 57 % |
  | urban6 | 64 % |
  | semiurb5 | 99 % |
  | rural2 | 100 % (all 1,283 overloaded step-levels) |
  | rural1, rural3 | no such step |
- An error that *is* electrically visible can still hide most of its safety consequence from a model that does not know about it.

---

## III. Literature (deliverable A, part)

The full targeted review (Stage 1) was written as board notes. Its conclusions, with access levels (FULL = full text read in targeted sections; ABSTRACT; METADATA):

**The robust part is textbook.**
- With uncertainty only on constraint right-hand sides, constraint by constraint, the robust feasible set is the one at the componentwise lower bound (Soyster 1973; Gabrel, Murat & Remli 2010, ABSTRACT).
- Correlation does not change robust feasibility.

**Uncertain ratings in operation are established**, but for transmission and weather-driven dynamic line rating:
- Rashkovska et al. 2022 (FULL; operational DTR uncertainty at ELES);
- Viafora et al. 2020 (chance-constrained OPF with DLR, METADATA);
- Wang et al. (distributionally robust OPF with DLR, ABSTRACT).

Robust dynamic operating envelopes treat ratings as known, and uncertainty as impedance or DER (Liu, Braslavsky & Mahdavi 2023, FULL; de Carvalho et al. 2026, FULL).

**Choosing which limits to learn has close prior art:** dynamic-line-rating placement.
- Chu 1992 (METADATA) and Jabarnejad & Valenzuela 2016 (ABSTRACT): an MIP choosing which lines get DTR, with bottleneck shifting.
- Long et al. 2022 (FULL): two-stage DTR placement with a submodularity proof under stated conditions.
- Tiwari et al. 2026 (ABSTRACT).

All of these are transmission, weather-driven upside, and contain no epistemic record error.

**Value of information is standard, and its non-submodularity is documented.**
- For inspection and sensor placement: Malings & Pozzi 2016, 2019 (METADATA, ABSTRACT); Straub 2014; Thöns 2018.
- Theory: Krause & Guestrin 2009 (ABSTRACT; optimal VoI tractable on chains, NP^PP-hard on polytrees); Golovin & Krause 2011 (adaptive submodularity).

**Paying to observe chosen uncertain parameters before a robust decision** is the generic template of decision-dependent information discovery (Vayanos, Georghiou & Yu, ABSTRACT).

**Decision sufficiency.** Data that suffice for an optimal decision have been characterised for linear programs, but for **cost** uncertainty only (Bennouna et al. 2025, ABSTRACT). Explorable-uncertainty query minimisation covers combinatorial objectives.

**DSO data quality.** Missing or non-standard cable data are common, handled by rule-based defaults (Geth, Vanin & Van Hertem 2023, METADATA; Ali et al. 2025, ABSTRACT). No public prior on rating-error rates was found.

**Closest competing work:** Jabarnejad & Valenzuela (2016), read at abstract level only. **The closest methodological template:** Vayanos et al.

**Not read in full:** several paywalled works (Chu; Jabarnejad & Valenzuela; Viafora; Greenwood et al.; Malings & Pozzi; Straub; Thöns; Geth; Gabrel). IEEE Xplore, Scopus and Google Scholar were not queried. A utility report on rating-record verification may exist unseen.

---

## IV. Research novelty

What is **not** new:
- the robust policy (Soyster);
- choosing which limits to learn (DLR placement);
- VoI-based inspection and its non-submodularity;
- the information-discovery template.

No new algorithm is claimed, and none is needed: the strongest finding is that the simplest ranking suffices.

What is defensibly new, as **reproducible benchmark evidence plus structural characterisation** in a setting the literature does not cover (an LV PV-export decision, **two-sided epistemic record errors**, one-shot verification):
1. **Decision relevance splits cleanly by which asset class binds.** Cable-rating uncertainty is exactly worthless to resolve on transformer-limited feeders, whatever its size.
2. **Series co-blocking on radial trunks** makes single-asset VoI nearly blind (the sum of singles is 0.4–7 % of the joint value). Yet a myopic VoI greedy, the loading rank and the binding rank still coincide and perform as well as a pair look-ahead and an ex-post best set at k ≤ 3. So, on these trunks, the non-submodularity is real but not harmful to greedy *ordering*.
3. **The verification unit matters.** Path- or route-shaped verification (B9; U4 routes) overshoots on deep feeders: semiurb5's second round jumps from 2 to 14 segments. Segment-level records allow finer, cheaper verification.
4. **The robust bound's safety is only as good as its interval.** A modest widening of the true support (w = 0.2 believed, 0.3 true) makes B2 unsafe in 43–84 % of draws (simulated exceedance of an assumed rating). Targeted verification then acts mainly as a safety repair, not an export gain.

---

## V. Mathematical formulation (deliverables B and C)

**The decision.** At each daylight step t, choose the largest uniform PV cap c ∈ {1.0, 0.9, …, 0.0} such that, at the believed ratings θ̂:
- every line satisfies loading_l(c, t) ≤ 100·θ̂_l / r_rec,l %;
- the transformer satisfies the same against θ̂_T;
- the voltage margins are ≤ 0.

The export is Σ_i min(a_i, c·r_i^PV) × 0.25 h. The decision at the true ratings is the **oracle B4**.

**The rating uncertainty model (deliverable B)**, with ρ = r_true / r_rec. All models are hypothetical stress assumptions; no realism is claimed.

| Model | Truth | What deployable policies believe |
|---|---|---|
| U0 | ρ ≡ 1 (the records are right) | the interval [0.8, 1.2] |
| **U2** (primary) | ρ_l ~ U[0.8, 1.2], independent per segment | the same interval and the same prior |
| U2w3 | ρ_l ~ U[0.7, 1.3] | the same |
| U3 | ρ_l ∈ {0.8, 1.0, 1.25} w.p. {0.25, 0.5, 0.25} | the same classes |
| U4 | one ρ per cable route (same type within a feeder) ~ U[0.8, 1.2] | the interval and the route grouping |
| U-T | transformer ρ_T ~ U[0.8, 1.2]; lines known (rural networks) | the same |
| **U2′** | ρ_l ~ U[0.7, 1.3] | **w = 0.2** (misspecified) |

Truth draws: 200 per (network, model). The prior samples used by the VoI policies are 100 per (network, model), from an independent seed stream.

**Robust decision.** For any uncertainty set Θ with RHS-only uncertainty, the robust feasible set ∩_{θ∈Θ} F(θ) = F(θ^min). So B2 (the lower bound) is the robust policy, and B3 (the minimum over sampled scenarios) equals it up to sampling.

**Value of information.** For a verified set S, the ratings θ_S are revealed exactly, and θ_¬S is believed at its lower bound:
- VoI_X(S) = E_prior[ export_X(decide(θ_S revealed, θ_¬S = θ^min)) ] − export_X(B2), over period X ∈ {P (planning), E (evaluation)}.
- **The worst case is always 0** (the adversary sets θ_S at its minimum), so a worst-case criterion cannot rank verifications. The expected value under a stated prior is therefore primary.
- **Recovery** R_k = (export(policy, k) − export(B2)) / (export(B4) − export(B2)), per truth draw on E, then averaged.
- Under a correctly specified support, every verification policy believes θ̂ ≤ θ_true, so R ∈ [0, 1] and no verification policy can be unsafe. This guarantee fails under U2′.

**Decision equivalence (deliverable C).** Two rating assignments are decision-equivalent at step t when they yield the same cap.
- **Situation 1** (protocol): the decision at θ^min equals the decision at θ^max, so every plausible assignment is equivalent, and no information can help at that step.
- **Situation 2:** they differ, so information can help.
- **Certificate:** a cable whose planning-period maximum loading at any cap never exceeds 100·(1 − w) % can never block at any believed rating ≥ its lower bound. It is therefore certified decision-irrelevant, and its VoI is exactly 0 (Control G).

| Network | Situation 1 share of E-steps (U2) | Situation 2 share | Network lines | Candidate pool (certified relevant), w = 0.2 |
|---|---|---|---|---|
| rural1 | 1.000 | 0.000 | 13 | 0 |
| rural2 | 1.000 | 0.000 | 95 | 3 |
| rural3 | 0.999 | 0.001 | 127 | 7 |
| semiurb4 | 0.793 | 0.207 | 42 | 6 |
| semiurb5 | 0.828 | 0.172 | 109 | 22 |
| urban6 | 0.857 | 0.143 | 57 | 12 |

Even on the cable-limited networks, **79–86 % of steps need no information at all**, and **79–86 % of cables are certified irrelevant** before any verification (36 of 42, 87 of 109 and 45 of 57).

---

## VI. Network and scenario design

- **Networks:** all six SimBench LV `--2-sw` networks. None is excluded or modified.
- **Classification** (zero-solve audit, by what blocks the next cap level under recorded ratings):
  - transformer-limited: rural1, rural2, rural3;
  - cable-limited: semiurb4, semiurb5, urban6.
- **Steps:** every daylight quarter-hour of days 35–364.
- **Split:** alternating 7-day blocks. The **planning period P** is the only information deployable rankings may use; every scored metric is on the **evaluation period E** (5,993–6,802 steps per network).
- **States:** re-labelled from the Phase 5 nominal full-state cache (per step, per cap level: line loading in % of the record, transformer loading, voltage margins). **No new power flow was needed for any scored result.**
- **The known-electrical-state idealisation is deliberate:** forecast and model errors are excluded, to isolate rating uncertainty.
- **Co-blocking** (zero-solve audit): in each cable-limited network, the four most frequent blockers under recorded ratings are series segments on **one root path** with an identical type and recorded rating (semiurb4 lines 38/37/36/35; semiurb5 26/58/74/62; urban6 33/4/5/55).

---

## VII. Baselines (deliverable E)

Unverified cables are believed at their lower bound unless stated.

| Code | Policy | Information |
|---|---|---|
| B0 | Trust the records | records |
| B1 | Uniform derating to (1 − w/2) | records |
| B2 | **Robust lower bound** (1 − w) | records and the interval |
| B3 | Scenario-robust: the minimum over 100 prior samples | prior |
| B4 | Oracle (true ratings) | truth (reference only) |
| B5 / B5-all | Random verification from the pool / from all cables, 20 orders | P |
| B6 | **Loading rank:** the highest planning-period no-cap loading | P |
| B7 | Binding rank: how often the cable blocks the next cap level under B2 | P |
| B8 | **Myopic VoI greedy** over the prior (non-adaptive) | P and the prior |
| B8P | VoI greedy with a pair look-ahead over all pool pairs | P and the prior |
| B9 | Adaptive structural route rule (verify the top blocker's co-blocking root path; recount with revealed ratings) | P and revealed ratings |
| OB | Ex-post best subset of the top-10 candidates, k ≤ 3 | **truth** (regret reference) |

These are strong, standard baselines:
- the robust bound is the textbook answer;
- the loading and binding ranks are what an engineer would do;
- myopic VoI is the standard information-acquisition baseline;
- pair look-ahead is the standard remedy for non-submodularity;
- OB bounds any subset policy at k ≤ 3.

**No deployable policy reads the truth.** This is enforced by decorators, and B9 sees only revealed ratings through a per-round wrapper.

---

## VIII. Decision sufficiency: which assets matter (deliverable C)

**Transformer-limited networks.**
- No cable matters. Under U2:
  - rural1 has no candidate cable at all;
  - rural2's 3 and rural3's 7 candidates each have single-cable VoI_P and VoI_E of exactly 0 (expected, best and worst cases).
- The transformer is the asset that matters. Under U-T, B2 loses **6.0 %, 6.8 % and 6.4 %**, and verifying the transformer recovers **all** of it (R = 1.000 ± 0).

**Cable-limited networks: a small, structured subset matters.**

| Network | Lines | Pool (U2) | B6 smallest k for per-draw R ≥ 0.5 / ≥ 0.9 | … for energy-weighted ≥ 0.5 / ≥ 0.9 | H4 smallest sufficient set found (95 % of steps in 95 % of draws) |
|---|---|---|---|---|---|
| semiurb4 | 42 | 6 | 2 / 4 | 2 / 6 | **5 cables** (12 % of lines), exhaustive, 98.0 % of draws |
| semiurb5 | 109 | 22 | 2 / only "all" (22) | only "all" / only "all" | **none of size ≤ 6 within the top-10 pool**. B8P's 7 cables reach 87.5 % of draws; B9's 2 reach 86.5 % |
| urban6 | 57 | 12 | 4 / 6 | 6 / 8 | **6 cables** (10.5 % of lines), exhaustive, 95.5 % of draws (**fragile**: margin 0.005 < 2·SE 0.029) |

H4's search scored up to 847 enumerated subsets (fewer where the pool is smaller than 10: 61 and 67 on semiurb4), plus the empty set and the named candidate sets (up to 851 as scored).

**Reading:**
- semiurb4 and urban6 have a **compact bottleneck**: one co-blocking trunk plus a few branches.
- semiurb5 has a **diffuse tail**. Two cables recover 54 %, but the rest of the gap is spread across many weakly binding cables: R = 0.63 at k = 8, against a 22-cable pool.
- §12 of the protocol applies here: the top-10 restriction binds on semiurb5 **and** urban6, so H4 bounds the sufficient set **within that pool only**. Minimality is never claimed.

**Competing bottlenecks (Control H).** Verifying the top-B7 cable alone leaves another cable binding on **99.75 %** (semiurb4) and **99.995 %** (urban6) of the steps B2 curtails. The transformer never takes over. This is co-blocking measured directly.

---

## IX. Information value (deliverable D)

**Recovery under U2.** Each cell gives the mean per-draw R (protocol §7) over 200 truth draws, with its SE in brackets, then **/ the energy-weighted recovery**: (mean export(policy) − mean export(B2)) / (mean export(B4) − mean export(B2)), i.e. the share of the total lost MWh recovered. The realised count equals k for B6.

| k | semiurb4 B6 | semiurb5 B6 | urban6 B6 | semiurb4 B5 (random) | semiurb5 B5 | urban6 B5 |
|---|---|---|---|---|---|---|
| 1 | 0.271 (0.021) / 0.07 | 0.013 (0.003) / 0.00 | 0.033 (0.007) / 0.00 | 0.041 / 0.01 | 0.001 / 0.00 | 0.002 / 0.00 |
| 2 | 0.703 (0.017) / 0.51 | 0.540 (0.018) / 0.35 | 0.090 (0.011) / 0.02 | 0.124 / 0.07 | 0.001 / 0.00 | 0.003 / 0.00 |
| 3 | 0.830 (0.011) / 0.72 | 0.553 (0.018) / 0.36 | 0.141 (0.014) / 0.03 | 0.229 / 0.16 | 0.002 / 0.00 | 0.017 / 0.00 |
| 4 | **0.900** (0.008) / **0.82** | **0.594** (0.020) / **0.38** | **0.549** (0.026) / **0.22** | 0.351 / 0.26 | 0.003 / 0.00 | 0.020 / 0.00 |
| 6 | 1.000 (0) / 1.00 | 0.613 (0.020) / 0.39 | 0.948 (0.008) / 0.85 | 1.000 / 1.00 | 0.030 / 0.02 | 0.060 / 0.02 |
| 8 | — (6-cable pool) | 0.626 (0.020) / 0.40 | 0.996 (0.001) / 0.99 | — | 0.032 / 0.02 | 0.164 / 0.09 |

**Why the two statistics differ, and which to read.**
- The mean of per-draw ratios weights every draw equally. A draw where B2 loses little and four cables recover it fully counts as much as one where B2 loses a lot and four cables recover a little.
- On urban6 and semiurb5, the high-loss draws are the ones where many cables have high true ratings, so more of them must be verified.
- The per-draw R is the pre-registered verdict statistic, and the verdicts stand as computed.
- **For operational value (energy), the energy-weighted column is the relevant one**, and it is materially lower on semiurb5 and urban6.
- The policy ordering is the same under both: B6 = B7 = B8 ≥ B8P ≥ B9 > B5.

**Policy comparison (Figure B):**
- B7 and B8 equal B6 at every budget on all three networks. The board audit (`audit_rankings.py`) shows identical unit orders, with B8's expected gains strictly positive at every step:

  | Network (U2) | B8's expected gain per step (MWh) |
  |---|---|
  | urban6 | 0.11, 0.09, 0.10, **1.67, 3.13**, 0.81, 0.19, 0.57 |
  | semiurb5 | 0.07, **1.87**, 0.13, … |

  The large late gains are the co-blocking payoff: urban6's 4th and 5th cables are each worth 15–35 times each of the first three. Greedy still orders correctly, because each step's gain, though small, is positive and points along the trunk.
- **OB (ex-post best set at k ≤ 3, with truth)** is no better than B6. It is identical on semiurb4 and urban6, and within 0.006 on semiurb5. So at k ≤ 3, **the loading rank is regret-free in this benchmark**.
- **B8P** equals B6 at its realised counts. Where a pair step overshoots the budget (k = 1 on semiurb4 and semiurb5; k = 2 and 4 on urban6; k = 4, 6 and 8 on semiurb5), budget matching scores B8P at its previous count, so it never exceeds B6.
- **B9** (route rule) is never better.
  - On semiurb5, its second round verifies a 12-segment root path at once (2 → 14 segments, `audit_b9_stop.py`). Under the budget-matching rule it is scored at its 2-segment state for every k ≤ 8 (R = 0.540).
  - On urban6 it realises 4, 5 and 8 segments at k = 4, 6 and 8.
  - **Control I:** "a simple heuristic suffices" on all three networks; "the structural rule suffices": no.

**Complementarity (Figure D).** Under U2, single-cable VoI_E is exactly 0 for 5 of semiurb4's 6 pool cables and 11 of urban6's 12:

| Network | Σ single-cable VoI_E (MWh) | Value of verifying the pool, oracle − B2 on E (MWh) | Ratio |
|---|---|---|---|
| semiurb4 | 0.707 | 9.50 | 0.074 |
| semiurb5 | 0.020 | 5.53 | 0.0036 |
| urban6 | 0.033 | 6.86 | 0.0047 |

**Model sensitivity (Figure E), B6 at k = 4:**

| Network | U2 | U2w3 | U3 (discrete classes) | U4 (one route unit, k = 1) |
|---|---|---|---|---|
| semiurb4 | 0.90 | 0.84 | 0.93 | 1.00 |
| semiurb5 | 0.59 | 0.86 | 0.96 | 1.00 |
| urban6 | 0.55 | 0.69 | 0.76 | 1.00 |

Under U4 the whole pool sits in one route, so one route verification resolves everything by construction. It is reported descriptively only (revision 2.2).

**Absolute value.**
- B2's mean loss on E is 9.50, 5.53 and 6.86 MWh over the evaluation half-year, for semiurb4, semiurb5 and urban6.
- Four loading-ranked verifications recover on average 7.80, 2.09 and 1.54 MWh.
- Whether that justifies the cost of inspecting four cables is outside this benchmark.

---

## X. Safety and utilisation

**Under U2 (Figure C):**
- **B0 (trust records)** exports 105–108 % of the oracle, but is unsafe on ≥ 1 step in 94.5 %, 100 % and 99 % of draws. Its unsafe-step share is 9.6–13.9 % of E-steps, and its severity p95 is 22.7–23.9 % over the assumed rating. This follows from two-sided record errors (H5(b), a check), not from an empirical discovery.
- **B1 (halfway derating)** exports 96.5 %, 101.8 % and 100.5 % of the oracle, and is unsafe in 61.5 %, 94 % and 65.5 % of draws. Halving the margin does not buy safety.
- **B2** is safe (0 unsafe E-steps; H5(a)) at 94.7 %, 98.4 % and 97.5 % of the oracle.
- **B3** differs from B2 by 0.39, 0.06 and 0.01 MWh. On semiurb4 it is unsafe in 2.5 % of draws (≤ 17 steps): the scenario approach's known finite-sample risk.
- **B6 at k = 4** is safe (by construction under U2), at 99.1 %, 99.0 % and 98.1 % of the oracle.

**The price of distrust (U0, records actually correct).** B2 gives up **9.9 %, 8.75 % and 7.6 %** of the export the records would have allowed safely. Verification recovers it in proportion to the pool covered.

**Misspecification (U2′: true w = 0.3, believed w = 0.2).** Share of draws with ≥ 1 unsafe E-step, at k = 4 for the verification policies:

| Network | B2 | B3 | B5 (random) | B6 = B7 = B8 | B8P | B9 |
|---|---|---|---|---|---|---|
| semiurb4 | 0.43 | 0.53 | 0.60 | **0.125** | 0.125 | 0.43 |
| semiurb5 | 0.84 | 0.88 | 0.86 | **0.55** | 0.65 | 0.72 |
| urban6 | 0.565 | 0.605 | 0.56 | **0.21** | 0.22 | 0.21 |

- The robust bound's guarantee is conditional on its interval. Once the interval is too narrow, B2 and B3 are routinely unsafe.
- Verifying the most-loaded cables removes most of the unsafe draws, because it replaces the wrong lower bound with the true rating exactly where it binds.
- **The per-draw R is not interpretable here:** oracle − B2 ≤ 0 in 53, 163 and 110 of 200 draws (the oracle exports *less* than the over-optimistic B2). U2′ is therefore reported in MWh and unsafe shares only.

---

## XI. Negative results (deliverable F)

1. **Cable-rating uncertainty is decision-irrelevant on transformer-limited feeders:** VoI exactly 0, Situation 1 on ≥ 99.9 % of steps. Verifying cables there is pure cost.
2. **Simulated electrical quantities carry zero information about a rating-only error** (Control D). Within this study's idealisations (static ratings; an unchanged electrical model; a known electrical state), no state estimator, smart-meter analysis or learned model working from voltages and currents can identify which record is wrong. Thermal sensing and asset identification are outside this result.
3. **Value-of-information search adds nothing over the loading rank** (B8 = B6 everywhere), nor does the pair look-ahead (H3b REJECTED), nor does the structural route rule (Control I).
4. **The complementarity prediction H3a is not universal:** on semiurb4 one cable alone recovers 27 %.
5. **No small sufficient set exists within the top-10 pool on semiurb5** (H4). Decision sufficiency there needs many cables.
6. **The scenario-robust B3 is never meaningfully better than the analytic lower bound** (≤ 0.39 MWh), and is unsafe in 2.5 % of semiurb4's draws. It is never more conservative than B2.
7. **Route-level verification units** (U4, B9) are coarse: they either resolve everything at once by construction (U4) or overshoot the budget (B9 on semiurb5).
8. **Zero export (cap 0)** is safe and useless (Control J), and is never counted as a success.

**Negative controls, all as specified** (protocol §8):

| Control | Outcome |
|---|---|
| A | rural1: 0 candidate cables, VoI 0 |
| B | rural2 and rural3 cable VoI exactly 0; the transformer recovers R = 1 |
| C | U0: B0 = B4 on all six networks |
| D | exact zero; read-out gap disclosed in amendment A4 |
| E | alignment passed on all six |
| F | verifying all candidates equals the oracle, all 36 combinations |
| G | certified-irrelevant VoI = 0 |
| H | above |
| I | above |
| J | cap 0: 0 unsafe, 0 export |
| B3 vs B2 | no B3 decision more conservative than B2's (no fault) |

---

## XII. AI relevance

**Where learning genuinely helps: nowhere, in this question as posed.** The scope is this benchmark's idealisations: static, rating-only errors; a known electrical state; hypothetical rating priors. This is not a claim about learned models in general.
- The decision-relevant quantity, which records are wrong and by how much, is **not identifiable from voltages and currents** when the error is rating-only (Control D). More electrical data or model capacity cannot change that. Other data could: temperature measurements, or asset records.
- The information policy that works best is a one-line ranking by planning-period loading. It equals the VoI greedy that a probabilistic model would compute.
- The safety-critical failure mode (a misspecified interval) is not something a learned predictor of loadings can detect, because the loadings are right.

**The legitimate AI-adjacent roles are elsewhere:**
- prioritising record audits across many feeders, which is the same ranking at scale;
- estimating the error *distribution* from inspection outcomes, a statistical-calibration problem (§XIX);
- the impedance-error case (Control E), where electrical data *do* carry information (Missions 10–11 and Phase 9 studied that detection problem).

**This mission's methodological conclusion, stated without bias from the project's "AI" identity:** *robust optimisation plus a small amount of targeted asset verification is sufficient, without an AI model.*

---

## XIII. Statistical validity and scientific limitations (deliverable H)

**What the sample supports:**
- 200 truth draws per (network, model) give Monte-Carlo SEs of 0.001–0.026 in R. Every threshold comparison uses the point estimate, as pre-specified.
- **Fragile verdicts** (margin < 2·SE):
  - H3a's rejection (0.2705 vs 0.25, SE 0.021);
  - H5(c) on urban6 (0.549 vs 0.50, SE 0.026), on which H5's SUPPORTED verdict rests;
  - H4 on urban6 (draw share 0.955 vs 0.95, binomial SE 0.015).

  `verdicts.json` also flags H3b on semiurb4 and semiurb5, with summed marginal SEs. Under §9's paired SE, those flags do not hold (below).
- **The verdict statistic is a mean of per-draw ratios** (protocol §7).
  - On semiurb5 and urban6 it is markedly higher than the energy-weighted recovery (at k = 4: 0.59 vs 0.38 and 0.55 vs 0.22), because small-gap draws dominate it.
  - Under the energy-weighted statistic, H5(c)'s 0.5 threshold would be met on semiurb4 only.
  - The verdicts are reported as pre-registered. Every operational claim in this note uses both statistics, and the protocol is not changed after the fact.
- With 3 cable-limited networks, the "on every network" verdicts are statements about **these three feeders**, not about LV networks in general.
- **The only out-of-sample check is temporal** (planning weeks versus evaluation weeks).
  - Rankings learned on P transfer to E well (B6 = OB at k ≤ 3), but that is within one year of one load and PV profile per network.
  - It is out-of-sample in **time only**: one rating vector per truth draw applies to both periods (ρ is static by design), and no held-out rating sample exists.
- **No multiple-comparison adjustment is made or claimed.** The verdicts cover 5 hypotheses × 3 networks × up to 7 budgets. §9's per-network thresholds and the fragility flags are the only error control, and no population claim is made.
- **Fragility flags in `verdicts.json`** use summed marginal SEs, which is conservative. The read-out recomputes H3b and H3c with the paired-difference SE that §9 names (A5).
  - **Neither is fragile.** H3b's margins are 0.050, 0.090 and 0.106 against 2·paired SE of 0, 0.009 and 0.012; H3c's are 0.35, 0.39 and 0.33 against at most 0.05.
  - H3b's minimum-over-k selection biases towards rejection, but that does not bite: the per-budget gaps never exceed 0.0, so H3b is REJECTED at every budget individually.
- **The §5 `worst_MWh` field** is the minimum over 100 prior samples, not the infimum over Θ. It is strictly positive in 35 of 526 (unit, period) records under the continuous models, where the sample minimum lies above the interval's lower bound. §1.2's zero worst case concerns the set Θ and is unaffected.
- **Control G** computes VoI for three certified-irrelevant cables per combination (all 0.0, in both periods and in every case). The remaining certified-irrelevant cables rest on the pool-certificate argument, not on a computed VoI. Control A covers all of rural1's lines.
- **Nothing is confirmatory.** All networks had been examined before. The board's zero-solve audit saw full-year decision-relevance numbers before the protocol was written, and H1 is therefore descriptive.
- **Amendments A1–A4** fixed scoring-harness defects found before any verdict:

  | Amendment | Defect |
  |---|---|
  | A1 | B9 round wrapper |
  | A2 | reduction width under route units |
  | A3 | OB scored only at k = 3 |
  | A4 | two read-out gaps (Control D key; H3a fragility flag), disclosed without re-running |

  Each superseded artefact is kept. After A2 and A3, all 30 overlapping combinations reproduced identically on every non-OB field. No definition, threshold or hypothesis was changed.

**What the benchmark cannot establish:**
- **Real ratings.** ρ is an assumed stress distribution: uniform ±20 % and ±30 %, or three stylised classes. No empirical distribution of record errors was available. The results are conditional on these distributions, and the misspecification result shows how strongly safety depends on the interval.
- **Thermal physics.** There is no conductor temperature, thermal time constant, soil or ambient model, cyclic rating, or emergency rating. "Unsafe" is a static-threshold exceedance > 0.5 %, not overheating, damage or ageing.
- **Inspection realism.** Verification reveals ρ exactly, at unit cost. Real inspection is noisy, costly, sometimes impossible (buried cables), and may reveal only a type or class.
- **Operation.** A static annual re-labelling with known injections: no forecast error, no dynamic or real-time rating, no protection, no unbalance.
- **Network coverage.** Six synthetic SimBench LV feeders at one registered PV scale, of which three are cable-limited. Different topologies (meshed, longer feeders) may change the co-blocking structure.

---

## XIV. Engineering QA

- **Tests:**
  - the module suite: 213 passing (`ratings_core`, `run_stage_a`, `analyse_stage_a`, after the publication freeze);
  - with Mission 11's suite, which shares `svgplot`: 468 passing;
  - an autouse guard forbids power flows in tests, and a `_forbid_truth` / `_deployable` mechanism blocks truth access by deployable policies;
  - `ruff check` and `ruff format` are clean.
- **Provenance:**
  - every evaluation artefact records the frozen code pair (`ratings_core.py` `8527be1d…`, `run_stage_a.py` `4fd263fc…`) and the protocol hash;
  - the read-out verifies that all 36 artefacts and `verdicts.json` match (`provenance.frozen_code_check.all_match = true`);
  - the decision tables carry their own build hash;
  - Controls D and E were run before A1 and carry the earlier code hashes. A1–A3 changed only the scoring harness.
- **Write-once artefacts.** Superseded artefacts are moved, never deleted.
- **Board audits (zero solves),** archived in `docs/provenance/mission12_board_audit/`: decision relevance and co-blocking before the protocol; ranking orders and B9's overshoot after scoring.
- **Independent reviews:**
  - one pre-experiment QA (18 findings, F1–F18; all applied in protocol revisions 2–2.2);
  - one post-experiment QA (AKK-87): **ACCEPT WITH CORRECTIONS**, detailed below.
- **What the post-experiment QA verified independently:**
  - It recomputed six recovery values, B0's safety, B2's safety and B3's export gap from the raw per-draw arrays: exact to the last digit.
  - It confirmed:
    - the frozen-code pinning (one code pair across all 36 artefacts; the as-executed protocol text is unedited);
    - the information boundary (`_forbid_truth` on every ranking; B9 sees only revealed ratings; deployable policies read only P);
    - that A1–A3 changed only what they claim (the A2 artefact diff is disclosure-only, and A3's touches only OB);
    - Controls A, B, C, F and J as specified;
    - that Controls D and E are independent of A1–A3 by code path.
- **What the single correction round changed** (amendment A5, read-out only):
  - **Verdict wording:**
    - H1's ≥ 3 % rule is met on semiurb4 only;
    - B3 is unsafe on semiurb4 in 2.5 % of draws;
    - H5's support rests on fragile urban6;
    - H4 on urban6 is fragile;
    - Control E's rural2 value is 100 %;
    - A4 and A5 are post-verdict.
  - **The §9 fragility flags** were computed where `verdicts.json` lacked them (H5, H4). H3b and H3c were recomputed with paired SEs: **neither is fragile under the paired rule**. The paired gaps equal `verdicts.json`'s, so its H3b flags came from summed marginal SEs.
  - **The energy-weighted recovery** was added as a secondary statistic.
  - **Disclosures added:**
    - the 100-sample `worst_MWh` (positive in 35 of 526 records);
    - Control G's 3-cable sample;
    - H4's scored-subset count;
    - Control D's cap level;
    - the temporal-only P/E split;
    - no multiplicity adjustment.
  - **Figures:**
    - corrected policy labels;
    - no connector to the full-pool point;
    - an energy-weighted panel row;
    - a log-scale complementarity panel;
    - the attribution-notice global restored after drawing.

  The first read-out is kept in `results/superseded_R1/`. **No verdict changed.**
- **Publication freeze (AKK-90):**
  - Figure D's description said single-cable value is "two to three orders of magnitude" below joint value. That is wrong for semiurb4, whose ratio is 0.074. The description is now generated from the recorded ratios (0.074, 0.0036, 0.0047, i.e. about 13× to 280×), and only Figure D was regenerated. The previous version is kept in `results/superseded_R2/`.
  - The read-out gained:
    - a completeness guard: the evaluations found must equal `verdicts.json`'s `combinations_scored`. Before this, a partial set was summarised silently;
    - a read-only `verify` command, which checks every local input against the hashes the frozen summary pins.

  No number changed.
- **What QA could not verify:**
  - the pre-A4 full-file protocol bytes (`d1fb8c66…`): the module is untracked, so no copy exists;
  - byte-level equality of the helpers shared with the earlier code revision used by Controls D and E: no copy is retained;
  - the decision tables re-derived from the git-ignored caches.
- **Hygiene:**
  - a clean export of the tracked files plus this mission's allowlist passes 1,065 tests, with 11 skipped. Each skip names absent local data, and Mission 12's pin test skips only when no local artefact exists. With the local data present, the full suite passes 1,253 with no skip;
  - `ruff` is clean;
  - no SimBench type name or rating value appears in any public candidate, other than two generic cable-family prefixes in the read-out's own disclosure blocklist (`analyse_stage_a.py`, `FORBIDDEN_TOKENS`). The test fixture's cable type name was made synthetic: task AKK-89.
- **Automated agent reviews are not human peer review.**

---

**Figures (deliverable G)** are in `analysis/asset_rating_information/figures/`. They are Produced Works under the ODbL, with the notice on the canvas.

| Figure | Content |
|---|---|
| A, decision relevance | B2's loss against the oracle, per network (U2 and the companion model); B0's unsafe-draw share |
| B, verification curves | Number of verified cables against recovery, per cable-limited network. Top row: per-draw R. Bottom row: the energy-weighted recovery, which is safe export |
| C, safety against utilisation | Export in % of the oracle against the unsafe-step share, for B0–B4 and B6 at k = 4 |
| D, complementarity | Single-cable VoI against the joint value, on a log scale |
| E, model sensitivity | B6's recovery under U2, U2w3, U3 and U4 |
| F, Controls D and E | A rating-only change does not move the simulated electrical state; an impedance change does |

## XV. Computational record

- **New AC power-flow solves: 2** (Control D), against a ceiling of 2,000. Every scored result re-labels the Phase 5 and Phase 8 caches.
- **CPU:**
  - final evaluations: 1,362 CPU s for the 36 (network, model) combinations, the largest 191 s (semiurb5, U2w3);
  - superseded evaluations: 925 CPU s;
  - table building, the pilot and Control E ran inside agent runs of ≤ 26 minutes wall time each.

  The total is well under 1 CPU-hour, against a ceiling of 3.
- **Execution:** foreground only, a single repository writer at a time. Every Paperclip run was bounded, and two were stopped by their own turn limits and continued in a fresh task.
- **Output size (local only):**
  - `results/` 5.1 MB, including 2.5 MB superseded;
  - `runs/` 22 MB (15 MB of decision tables, 3.8 MB superseded);
  - `figures/` 88 KB.

---

## XVI. Publication potential

**Contribution level:** (2) reproducible benchmark evidence, plus (3) a scientific negative finding, with an element of (4) methodological characterisation (series co-blocking and verification granularity). There is no algorithmic contribution, and none is needed.

**What is missing for a credible paper:**
1. **An empirical prior on record errors.** Even a DSO audit sample would do: rating-record verification outcomes for a few hundred cables. Without one, every number is conditional on an assumed interval, and the misspecification result shows the conclusions are sensitive to it.
2. **More cable-limited feeders,** including real or larger synthetic LV and MV networks with longer and meshed topologies, to test whether "loading rank = VoI greedy" holds beyond radial trunks.
3. **A realistic inspection model:** noisy or partial verification (type only), costs, and inaccessible assets.
4. **Thermal grounding** for the safety metric (at least a cyclic-rating or temperature model), or an explicit framing as a constraint-admissibility study.
5. **A full-text check** of the closest works (Jabarnejad & Valenzuela; Malings & Pozzi; Bennouna et al.) and an IEEE Xplore and Scopus search.

**The strongest baseline** is the loading rank (B6) on top of the robust bound (B2). Any proposed method must beat that pair. On this benchmark nothing did.

---

## XVII. Learning appendix (deliverable I)

*For an MSc AI student with an electrical-engineering background.*

**1. Why the power flow cannot see a wrong rating.**
- Kirchhoff's laws and the line impedances fix the currents for given injections.
- The rating is a number on a datasheet that says how much current the cable may carry. It is the right-hand side of an inequality, |I| ≤ r, not a parameter of the physics.
- Change r and every voltage and current stays the same; only the *verdict* "is this allowed?" changes.
- So a model can be electrically perfect and still let an overloaded cable through, or curtail when it did not need to. In machine-learning terms: the label (admissible or not) depends on a feature you never observe *in the electrical data*.
- Two caveats keep this honest:
  - A temperature sensor on the cable *would* observe something related to the limit.
  - If the "wrong record" is really a different cable (another cross-section), its impedance differs too, and the electrical data change (Control E).

  The invisibility argument covers a wrong *threshold* on the right cable.

**2. Why the robust answer is trivial.**
- If each cable's true rating lies in [0.8 r, 1.2 r] and you must never exceed it, you must assume 0.8 r for every cable. No correlation or clever reasoning can do better, because the worst case for each inequality is its own lower bound, independently.
- That is the Soyster result, and it is why "robust optimisation over uncertain ratings" is not a research contribution by itself.

**3. Why a single inspection is often worthless (co-blocking).**
- Picture a radial trunk of four cable segments in series, all carrying nearly the same current from the PV at the end.
- If you verify one segment and find it can carry 20 % more, the export is still limited by the three you did not verify, so the decision does not change. The value of that single inspection is zero.
- Verify all four and the whole trunk opens up. The value of information is **complementary**: the whole is worth far more than the sum of its parts (here, 13× to 280× more).
- This is why the greedy "inspect the most valuable single asset" looks blind. Yet in these feeders, greedy still picks the trunk in order, because each step's tiny gain points in the right direction.

**4. Why the simplest ranking wins.** The most-loaded cables are exactly the trunk segments that co-block, so ranking by loading *is* the structural rule, without any topology analysis or probabilistic model.

**5. Why the robust bound can still fail.** The robust guarantee assumes the interval is right. If real ratings can be 30 % low but you assumed 20 %, the "robust" policy exceeds an assumed true rating in about half of the scenarios (simulated exceedance, not measured overheating). Inspecting the binding cables fixes the problem where it matters, because it replaces the wrong assumption with the truth there. **The safety of a robust decision depends on the calibration of its uncertainty set**, a lesson that transfers to any constraint-tightening method, learned or not.

**6. The three situations of the mission brief**, answered:
- **Situation 1** (all plausible models agree) covers 79–100 % of steps. No information is needed.
- **Situation 2** (they disagree) covers 0–21 %. Information has value, concentrated in a few cables.
- **Situation 3** (measurements cannot resolve the ambiguity) applies to **every** Situation 2 step, for rating-only errors and *electrical* measurements, because such an error leaves the simulated voltages and currents unchanged.
  - The choice is between robust action (B2) and acquiring non-electrical information: inspection (B6), and, not studied here, thermal sensing.
  - No estimator working from electrical data can substitute for that information. Deferral is not modelled.

---

## XVIII. Final scientific judgement

**PIVOT.**

**Why not GO.**
- The registered multi-network study that GO would fund would mostly confirm a simple-heuristic result. The loading rank equals VoI search, and structure-aware rules do not help.
- SimBench offers only three cable-limited LV feeders, and real record-error data are unavailable.
- A larger study of the same question would add precision, not insight.

**Why not STOP.** Two findings point to a stronger, related problem:
- **(i)** the robust bound's guarantee collapses under a modest interval misspecification (simulated exceedances in 43–84 % of draws), and targeted verification repairs much of it;
- **(ii)** complementarity makes single-asset reasoning blind, while path-level reasoning overshoots.

Together they make **"verification as calibration of the uncertainty set"** a well-posed and non-trivial question: what to inspect when the inspection outcomes should also tell you whether your interval is wrong. It connects to GridPulse's core theme, trustworthy decisions when physical information is missing.

**Evidence summary:**
- H3c and H5 SUPPORTED: targeted verification works. Under the energy-weighted statistic it is strong on semiurb4 (82 % of the lost energy at 4 cables) and partial on semiurb5 and urban6 (38 % and 22 % at 4; 85 % on urban6 at 6).
- H3b REJECTED and Control I: no sophistication is needed.
- H3a REJECTED, fragile: complementarity is not universal.
- H4 SUPPORTED on 2 of 3 (urban6 fragile).
- Controls A–J pass.
- U2′: the robust bound is exceedance-free against its assumed ratings only under its own interval.

---

## XIX. Next experiment (one; not executed without separate authorisation)

**"Verify-then-recalibrate under a misspecified rating interval."** Zero new AC solves: it re-labels the existing caches. It is a design only, revised in the publication freeze after the critical assessment below.

**Question.** Verifying a cable reveals its rating. If the revealed rating falls **outside** the believed interval, does that justify widening the believed interval for the **unverified** cables, and by how much? How does such a rule trade simulated exceedances against export, compared with established ways of calibrating an uncertainty set?

**When an out-of-range verified rating justifies widening for others:**
- **Logically, it falsifies the believed support** for whatever population the verified cable belongs to. Under a uniform belief on [1 − w, 1 + w], one value outside it has probability 0, so the model is wrong.
- **It says something about *unverified* cables only under exchangeability:** their errors must come from the same error-generating process as the verified cables' (the same record-keeping practice, installation era, cable class). If the out-of-range value comes from an asset-specific cause (one mislabelled cable), widening for every other cable is over-conservative and costs export for nothing. U2′ draws every cable's error independently from one wider distribution, so it is **exchangeable by construction**: the scenario most favourable to widening. A fair test must add non-exchangeable misspecification (errors wider only in one feeder or cable class, or a single gross error) and a correctly specified control, where widening rules must not cost export.
- **Selection must be ignorable.** The verified cables are chosen by loading rank, not at random. In this model, ρ is independent of loading, so the selection is ignorable. Real record errors could correlate with loading (for example, heavily loaded cables may be newer or more often re-rated), and then a targeted sample would mis-estimate the population's spread.
- **How much to widen is not identified by one observation** without a parametric model. With k ≤ 6 verified cables, finite-sample guarantees are weak:
  - a nonparametric one-sided 95 %/95 % tolerance bound needs 59 samples (Wilks);
  - a split-conformal lower bound cannot certify miscoverage below 1/(k + 1), i.e. 0.2 at k = 4;
  - an exact upper confidence bound on the half-width of a uniform error, from the largest of k observed deviations M, is M / α^(1/k): 2.1 × M at k = 4, α = 0.05, which is very conservative.

**Analytic gate (computed now, before any run).**
- Under U2′ (true w = 0.3, believed 0.2), each verified cable falls outside the believed interval with probability 1/3. A detect-then-widen rule therefore misses the misspecification with probability (2/3)^k: **0.44, 0.20 and 0.09 at k = 2, 4 and 6**. At true w = 0.25 the per-cable probability is 0.2, and the miss rate at k = 4 is 0.8⁴ = 0.41.
- If the draws where the rule misses the misspecification then show exceedances at B6's U2′ rate at k = 4 (12.5 %, 55 %, 21 %), the floor on exceedance draws is about **2.5 %, 11 % and 4 %**. This is (2/3)⁴ × B6's exceedance-draw share: a rough estimate that assumes independence.
- **The originally proposed success criterion (≤ 5 % on all three networks at w ≤ 0.3) is therefore close to predetermined:** it fails on semiurb5 by detection arithmetic alone, unless widening also responds to in-range values or k grows. The revised design reports these bounds as pre-registered predictions rather than as a pass or fail target.

**Revised design (for authorisation):**
- **Networks and draws:** the three cable-limited networks, 200 truth draws, the same P/E split.
- **Scenarios:**
  - true w ∈ {0.2 (correctly specified control), 0.25, 0.3, 0.4}, exchangeable;
  - **non-exchangeable** variants: misspecification confined to one feeder or class, and a single gross error;
  - k ∈ {2, 4, 6}.
- **Update rules** (at most three, pre-specified):
  - detect-then-widen to the minimum verified ρ;
  - a parametric uniform-width upper-confidence widening;
  - a Bayesian hierarchical posterior on w with a stated prior.
- **Established baselines:**
  - B2 at the believed interval;
  - B2 at fixed, pre-emptively widened intervals (w = 0.3 and 0.4: the price of insurance);
  - B6 without recalibration;
  - random verification plus the same update rule, which separates selection from detection;
  - a split-conformal and a nonparametric tolerance bound, to show the finite-sample floor;
  - for reference, data-driven robust sets (Bertsimas, Gupta & Kallus 2018) and Wasserstein DRO (Mohajerin Esfahani & Kuhn 2018). These are cited, not reimplemented, unless the simple rules fail.
- **Metrics:**
  - the share of draws with a simulated exceedance (primary);
  - export as a % of the oracle;
  - the false-widening cost under correct specification.
- **Cost:** about 0.5 CPU-hour, reusing `ratings_core`.

**Assessment.**
- The experiment is scientifically well-posed and cheap. Its central claim, that verification outcomes can calibrate the interval, rests entirely on an exchangeability assumption that the benchmark cannot test. Its external value therefore depends on empirical record-error data (§XVI).
- **Recommendation:** run it only together with, or after, obtaining even a small audit sample of real rating-record errors. Without one, report the analytic bounds above as the main result. The decision on Mission 13 is the owner's.

---

## XX. Manual Git review

The exact allowlist is in the final report. In summary:
- **Public candidates:**
  - code, tests, the protocol, `DATA_ATTRIBUTION.md` and the module README;
  - this note and the board-audit provenance (aggregate SimBench-derived figures only);
  - figures (Produced Works with the ODbL notice), at the owner's decision.
- **Local only:** `analysis/asset_rating_information/results/` and `runs/`, the derivative database, including every superseded artefact.

No staging, commit, push, branch or history change has been made by any agent.
