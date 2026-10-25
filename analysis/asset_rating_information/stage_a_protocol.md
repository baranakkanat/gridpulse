# Mission 12 Stage A protocol: decision-sufficient asset information under uncertain thermal ratings

**Status.**
- EXPLORATORY and internally pre-specified (Mission 12, 2026-10-25). Not externally preregistered and not confirmatory: all six SimBench LV networks, their constraints and the Phase 5 cache used here have been examined in Phases 4–9 and Missions 10–11. The board's zero-solve audit (§2) also inspected full-year decision-relevance numbers before this protocol was written.
- Changes after the first scored computation are dated amendments at the end. Nothing above them is edited.

**Research question.** When the *recorded static current ratings* of LV assets may be wrong while the electrical model is right, which asset information is necessary and sufficient for a record-admissible, useful PV-export decision (see §0, row E)? When does verifying an asset's rating pay off, and when is it worthless despite large numerical uncertainty?

---

## 0. Definitions (what this study does and does not measure)

| Quantity | Meaning here |
|---|---|
| **A. Recorded static rating** r_rec | The asset record: for lines, `max_i_ka · df · parallel` (the quantity pandapower's `loading_percent` normalises by; `df` = `parallel` = 1 on every line of all six networks, board check); for the transformer, `sn_mva` |
| **B. Permissible continuous loading** r_true | Current for lines, apparent power for the transformer. A **benchmark assumption** drawn from a stated uncertainty model around r_rec. It is **not** a measured or IEC 60287-computed ampacity |
| **C. Dynamic thermal rating** | **Not modelled** |
| **D. Thermal state** (conductor temperature) | **Not modelled.** Loading percentage is **not** temperature |
| **E. Thermal safety** | **Not claimed.** "Unsafe" means: the simulated loading (line current, or transformer apparent power) exceeds the assumed true static rating by more than 0.5 %. It is not an outage, overheating, damage or a lifetime claim |

The study is a **static, rating-only** benchmark. Ratings enter only as admissibility thresholds, |I_l| ≤ r_l for lines and |S_T| ≤ r_T for the transformer. They are not in the power-flow equations (§8, Control D).

---

## 1. Design input and prior art (summary; the full review is in the research note)

**What this builds on.**
- Mission 11 (F0): thermal limits bind before voltage in all six networks at the registered PV scale.
- Phase 8: a *bundled* R × 1.5 and rating × 0.8 cable error defeated every attainable policy in 3 of 5 networks. **No rating-only error was tested.**
- Mission 10, Control B: a rating-only change gives exactly zero electrical signal.

**Triviality gate (decided before scoring).**
1. **The robust decision is trivial.** Ratings appear only on the constraints' right-hand sides, constraint by constraint. So for *any* uncertainty set Θ, ∩_{θ∈Θ} F(θ) = F(θ^min), where θ^min_l = inf_{θ∈Θ} θ_l (Soyster 1973; Gabrel et al. 2010). Correlation does not change robust feasibility. B2 (lower bound) and B3 (scenario-robust) are therefore the same policy, and B3 is checked only numerically.
2. **Worst-case information value is zero.** For box sets (U2, U3) and shared-factor sets (U4), and indeed whenever Θ contains θ^min, the robust value after verifying any set S is unchanged in the worst case: the adversary sets θ_S at its minimum. A **worst-case-value** criterion cannot rank verifications. Distribution-free criteria that can (minimax regret, best-case upside) are reported as the upside column. The primary information value is stated under an **explicit, hypothetical prior** (expected value).
   - Also by construction: every verification policy believes θ̂ ≤ θ_true componentwise, so its admissible set lies inside the oracle's. Hence R_k ∈ [0, 1], and no verification policy can be unsafe. The safety question therefore concerns B0 and B1 only.
3. **Choosing which limits to learn has close prior art.**
   - Dynamic-line-rating placement on transmission networks (Chu 1992; Jabarnejad & Valenzuela 2016; Long et al. 2022; Tiwari et al. 2026).
   - Value of information for inspection, and its non-submodularity (Krause & Guestrin 2009; Malings & Pozzi 2019).
   - Decision-dependent information discovery (Vayanos et al.).
   - Decision-sufficient data for linear programs, cost-side only (Bennouna et al. 2025).
   - **A new algorithm is not claimed.**
4. **What remains open and is tested here,** as reproducible benchmark evidence:
   - (i) how decision relevance splits by which asset class binds;
   - (ii) whether series-segment co-blocking on radial LV trunks defeats standard single-asset rankings (loading, binding sensitivity, myopic VoI);
   - (iii) whether a simple structural rule ("verify the whole bottleneck route") matches VoI search;
   - (iv) whether the information unit matters (segment-level against route-level records);
   - (v) the unsafe side of two-sided record errors (the recorded-rating policy B0).

**Abandon criteria** (§15 gives the stop rules):
- the network decisions do not depend on cable ratings;
- every ranking performs alike;
- the structural rule is trivially implied with no empirical surprise. That last outcome is reported as a negative finding, not engineered away.

---

## 2. Facts fixed by the zero-solve audit (board, before this protocol)

**Data:**
- **Phase 5 nominal full-state cache:** `outputs/sense_study/fullstate_cache/<network>/nominal/day_DDD.npz`, days 35–364.
  - Per quarter-hour, at the 11 uniform PV-cap levels `CAP_LEVELS = 1.0, 0.9, …, 0.0`, it holds: line loading in % of `max_i_ka`; transformer [P, Q, loading %, LV voltage]; bus voltages; Phase 4 margins.
  - The model: the registered Phase 4 PV scale, storage idle, the NOMINAL variant, native SimBench realised injections.
- **Phase 8 `line_local` cache** (`outputs/robust_study/fullstate_cache/<network>/line_local/`, the same days): one cable at R × 1.5 and `max_i_ka` × 0.8, used for Control E.
- Both caches are local, git-ignored, and derived from SimBench (ODbL).

**Full-year audit** (days 35–364, daylight steps, recorded ratings; cable lower bound 1 − w with the transformer known):

| Network | What blocks the next cap level when curtailment is needed | Robust export loss vs recorded, w = 0.2 / 0.3 | Co-blocking |
|---|---|---|---|
| rural1 | transformer (1,205 steps) | 0 / 0 (no line ever > 70 %) | — |
| rural2 | transformer (1,012) | 0 / 0.02 % | — |
| rural3 | transformer (850), voltage + transformer (201) | 0.02 % / 0.6 % | — |
| semiurb4 | lines (1,299) | 9.4 % / 11.9 % | lines 38, 37, 36, 35: one series trunk, identical type and rating |
| semiurb5 | lines (1,194) | 8.3 % / 11.3 % | lines 26, 58, 74, 62 on one root path, identical type and rating |
| urban6 | lines (867) | 7.3 % / 10.8 % | lines 33, 4, 5, 55: one series trunk, identical type and rating |

Under the hypothetical U-T interval, lowering the transformer bound as well would cost the rural networks 6–13 % of recorded export (w = 0.2 and 0.3).

**Topology facts** (board check, zero solves): all six networks are radial on the in-service line graph with switch states applied (0 cycles). Every line is in service, and `df` = `parallel` = 1 on every line. Root paths are therefore unique. The audit's hop-wise depths coincide with this convention.

**Consequence.** **H1's classification is already visible in the audit, so H1 is descriptive here, not a test.** The tested questions are H3–H5.

---

## 3. Networks and conditions

- **Networks:** all six SimBench LV `--2-sw` networks, classified by the audit rule "what blocks the next cap level on most curtailed steps under recorded ratings":
  - **transformer-limited:** rural1, rural2, rural3;
  - **cable-limited:** semiurb4, semiurb5, urban6.

  No network is excluded or modified, and no impedance is changed.
- **Decision steps:** every daylight quarter-hour (available PV > 0) of days 35–364.
- **Planning and evaluation periods:** alternating 7-day blocks, b = ⌊(day − 35)/7⌋.
  - The **planning period P** (even b) is the only information deployable rankings may use.
  - The **evaluation period E** (odd b) is where every scored metric is computed.
- **Electrical knowledge (an idealisation, stated):** the electrical state at every cap level is taken as known (known injections and impedances). This isolates rating uncertainty. Forecast and model error are deliberately excluded.

---

## 4. The decision (GridPulse's existing action)

- **The action** is a uniform PV feed-in cap c ∈ `CAP_LEVELS`: unit output min(a_i, c·r_i^PV), with r^PV the installed `sn_mva` (`grid.cap_pv`), exactly as in Phases 3–8.
- **The rule:** for a believed rating vector θ̂, the decision at step t is the **largest cap** (smallest level index) at which, simultaneously:
  - every line's loading ≤ 100·θ̂_l/r_rec,l %;
  - the transformer's loading ≤ 100·θ̂_T/r_rec,T %;
  - the voltage margins (vmax and vmin) are ≤ 0.

  If no level qualifies, cap 0 is chosen and flagged `infeasible_at_zero`.
- **Export** = Σ_i min(a_i, c·r_i^PV) × 0.25 h, in MWh.
- **True outcome** at the chosen level: unsafe if any line's loading/ρ_l or the transformer's loading/ρ_T exceeds 100.5 %. Here ρ = r_true/r_rec. **Severity** = the maximum true utilisation − 100 %.

---

## 5. Rating uncertainty models (all hypothetical stress assumptions; no realism is claimed)

ρ_l = r_true,l / r_rec,l. Uncertain assets are **all LV lines (cables)** unless stated. The transformer is known (ρ_T = 1) except in U-T.

| Model | Truth | Deployable knowledge |
|---|---|---|
| **U0** correct records | ρ ≡ 1 | Interval [1 − w, 1 + w] believed (the records are not trusted) |
| **U2** independent interval | ρ_l ~ Uniform[1 − w, 1 + w], independent per segment; **w = 0.2 primary**, 0.3 secondary | The same interval and the same prior |
| **U3** discrete class ambiguity | ρ_l ∈ {0.8, 1.0, 1.25} with probabilities {0.25, 0.5, 0.25}, independent per segment (one size smaller / correct / larger). The ratios are stylised, not the ampacity ratios of adjacent `std_type` cross-sections | The same classes and prior |
| **U4** route-correlated | One ρ per **cable route** g ~ Uniform[1 − w, 1 + w] (w = 0.2). A route is a connected component of the lines that share one `std_type` within one feeder (the subtree below one LV busbar outgoing line); it is computed from the records only. Segments of a route share ρ. Routes, feeders and root paths come from one function: `pandapower.topology.create_nxgraph(net, respect_switches=True)` on in-service lines, rooted at the LV busbar. The graph is asserted to be a tree (it is, on all six networks) | The interval, the prior and the route grouping (from the records) |
| **U-T** transformer only (rural networks) | ρ_T ~ Uniform[0.8, 1.2]; lines known | The interval and the prior |
| **U2′** prior misspecification (cable-limited networks) | As U2 but with w = 0.3 | Every deployable policy believes w = 0.2. A fairness check on the prior-using policies (B3, B8, B8P). B2 may then be unsafe, and its unsafe count is reported |

- **Truth draws:** N_truth = 200 per (network, model), with seeds `SeedSequence([20261026, stable_int(network), stable_int(model), stable_int("truth"), d])`.
- **Prior samples used by deployable VoI policies:** an independent stream, purpose `"prior"`, N_prior = 100, drawn **once per (network, model)** and shared by all policies and all truth draws.
- **The prior is correctly specified** for U0, U2, U3 and U4 (it is the truth-generating distribution). This is the most favourable case for B3, B8 and B8P; U2′ tests misspecification.
- **U1** (an independently incorrect record, unaware policy) is the behaviour of B0 under U2 or U3 truths.

**Value of information (definition).** For a verification set S and a period X ∈ {P, E}:

  VoI_X(S) = E_prior[ export_X(decide with θ_S revealed and θ_¬S at its lower bound) ] − export_X(B2),

with the expectation over the N_prior prior samples. Deployable policies use VoI_P. Controls A, B and G report both VoI_P and VoI_E. The **best case** replaces the expectation by the maximum over the prior samples; the **worst case** by the minimum, which §1.2 predicts is 0.

**Verification action** `verify(x)` reveals ρ of x exactly: a segment under U0, U2 and U3; a route under U4. This is a **mathematical information oracle at unit cost per action.** It is not a claim that inspection is free or perfect. Costs are reported as counts: segments verified, and actions taken.

---

## 6. Policies

**Unverified assets are always believed at their lower bound** (robust), unless the policy states otherwise.

| Code | Policy | Uses |
|---|---|---|
| B0 | Recorded ratings, θ̂ = r_rec | records only |
| B1 | Uniform derating, θ̂ = (1 − w/2)·r_rec | records |
| B2 | Robust lower bound, θ̂ = (1 − w)·r_rec (U3: 0.8) | records and the interval |
| B3 | Scenario-robust over the N_prior prior scenarios (componentwise minimum). **Expected to equal B2** (§1.1); this is a numerical check | prior samples |
| B4 | Oracle, θ̂ = r_true | **truth** (reference only) |
| B5 | Random verification of k assets **drawn uniformly from the candidate pool** (cables or routes), averaged over 20 random orders per truth draw. **B5-all**, the same over all cables or routes, is reported as a weaker reference | the pool (P) |
| B6 | Loading rank: verify the k assets with the highest planning-period maximum no-cap loading (% of record) | P |
| B7 | Binding-sensitivity rank: verify the k assets most often *blocking* under B2 in P (counted at the level just above B2's choice, with co-blocking assets each counted) | P |
| B8 | Myopic VoI greedy: repeatedly add the asset with the largest expected P-period export gain given those already chosen, averaged over the prior samples. **Non-adaptive:** the set is planned from the prior before any verification (as is B8P's). This asymmetry with B9 is disclosed | P and the prior |
| B8P | VoI greedy with a pair look-ahead: at each step choose the single asset or **pair** with the largest expected gain per added asset. The pair search is over **all pairs in the candidate pool** (at most C(22, 2) = 231 at w = 0.2; the count is reported) | P and the prior |
| B9 | Structural route rule:<br>(1) among unverified candidates, take the one blocking on the most P-steps under B2 (B7's blocking definition; ties broken by the lower line index);<br>(2) verify every candidate segment on its root path (the same topology function as U4), including itself, that blocks in ≥ 10 % of that asset's blocking steps;<br>(3) recompute B2 with the **revealed** ratings of the verified assets substituted, recount the blocking, and repeat from (1) until the budget is reached or no unverified candidate blocks. This is deployable: verification reveals those ratings. B9 is therefore **adaptive**.<br>The realised count may overshoot k and is reported. Under U4 the unit is the route containing the top blocker.<br>**B9-static**, where verified assets are believed at the interval's upper bound during planning (no revealed values), is reported descriptively, so any advantage that comes only from adaptivity is visible | P (no prior); the revealed ratings of verified assets |
| OB | Ex-post best set: an exhaustive search over the **m = 10 top candidates** (ranked by blocking count under B2 over P ∪ E) for k ≤ 3 (at most 175 subsets), maximising E-period export under **truth** | **truth** (regret reference; not deployable) |

**Rules that apply to every policy:**
- **Budgets:** k ∈ {1, 2, 3, 4, 6, 8}, then "all candidates". Policies that add pairs or paths may overshoot k; they are scored at their realised count and plotted against it.
- **Candidate pool (deployable):** cables whose P-period maximum loading at any level exceeds 100·(1 − w) %. Every other cable is certified decision-irrelevant **over the planning period**, because it cannot block at any believed rating ≥ its lower bound.
- **Certificate pool (for the certificate, OB, H4 and Control G):** recomputed on P ∪ E. Cables exceeding the threshold in E but not in P are counted. Board check: 0 on every network.
- **Pool sizes** (board check, w = 0.2 / 0.3): rural1 0/0, rural2 3/3, rural3 7/14, semiurb4 6/6, semiurb5 22/30, urban6 12/12.
- **Information boundary:** no deployable policy (B0–B3, B5–B9) reads ρ_true, except for assets it has verified. Rankings use only P-period states, records, the interval and the prior. A unit test enforces this.

---

## 7. Hypotheses (fixed before scoring)

- **H1 — decision irrelevance.** Descriptive, already visible in the audit. Under U2 (w = 0.2), cable-rating uncertainty is decision-irrelevant in the transformer-limited networks: the B2 export loss is ≤ 0.5 % of oracle, and **Situation 1** (the decision is identical at θ^min and θ^max) holds on ≥ 99 % of E-steps. It is decision-relevant in the cable-limited networks (loss ≥ 3 %). This is reported, not tested.

- **H2 — measurement insufficiency.** Analytic: r_l does not enter V = f(P, Q, Z, topology) or I = h(·), so electrical data carry zero information about a rating-only error. It is checked by Control D (identical states) and contrasted with Control E (impedance plus rating: the states change). It is **not** an empirical hypothesis.

- **H3 — verification value.** Cable-limited networks, w = 0.2. **Verdicts under U2**; U4 is reported descriptively (revision 2.2). The **recovery** is R_k = (export(policy, k) − export(B2)) / (export(B4) − export(B2)), on E, averaged over truth draws. Differences between policies are paired by draw.
  - **H3a, the complementarity prediction.** A structural prediction, partly derivable. Under U2, at k = 1, every single-asset ranking (B6, B7, B8) has R_1 ≤ 0.10 on each cable-limited network whose top-blocking set contains ≥ 2 co-blocking series segments.
    - *Rejected* if any of them reaches R_1 ≥ 0.25.
    - *Inconclusive* if 0.10 < max R_1 < 0.25. The maximum is taken over B6, B7, B8 **and** over the qualifying networks.
  - **H3b, structure helps.** Under U2, at budgets k ∈ {2, 3, 4}. Each policy enters at its **largest realised count ≤ k** (a policy with no realised count ≤ k scores R = 0 at that k). Each k is compared separately, and H3b uses the k with the **smallest** gap (the conservative choice):
    - *Supported* if max(B8P, B9) − max(B6, B7, B8) ≥ 0.20 in R on ≥ 2 of 3 cable-limited networks.
    - *Rejected* if ≤ 0.05 on all 3.
    - *Inconclusive* otherwise.
  - **H3c, targeted against random.** At budget 4:
    - *Supported* if the best deployable targeted policy exceeds B5 by ≥ 0.20 on all 3.
    - *Rejected* if ≤ 0.05 on all 3.
  - **Control I.** If B6 or B7 comes within 0.05 of the best VoI policy at every budget, the verdict is **"a simple heuristic suffices"**. Likewise, if B9 comes within 0.05 of B8P, **"the structural rule suffices"**.

- **H4 — decision sufficiency.** For each cable-limited network and model (U2, U4), consider the smallest set S found by B8P, B9 and an exhaustive search (sizes ≤ 6 over the **m = 10 top candidates** of the certificate pool, ranked by blocking count under B2 over P ∪ E; C(10, 6) = 210 subsets of size 6) such that, after verifying S, the decision equals the oracle's on ≥ 95 % of E-steps in ≥ 95 % of truth draws.
  - *Supported* (a sufficient set much smaller than the asset list) if |S| ≤ 25 % of the network's cables.
  - *Rejected* if no S of size ≤ 6 reaches the criterion.
  - **Minimality is not claimed**, only an upper bound on the minimal size, **within the top-10 pool**.

- **H5 — robust plus information.** Cable-limited networks, U2 (w = 0.2).
  - **(a)** B2 has 0 unsafe E-steps. This holds by construction, so it is a check.
  - **(b) A check, expected to hold with probability ≈ 1 by construction:** B0 is unsafe on ≥ 1 E-step in ≥ 50 % of truth draws on every cable-limited network. The informative quantities are reported descriptively: the unsafe-step share per draw, the 95th percentile of severity, and the share of draws with severity > 5 %.
  - **(c)** The best deployable targeted policy recovers ≥ 50 % of B2's export loss at a realised budget ≤ 4 segments, **under U2**, on every cable-limited network. U4 is reported descriptively (revision 2.2): on these networks the whole pool lies in one route, so one route verification resolves it by construction.
  - *Supported* if (c) holds on every cable-limited network. *Rejected* if (c) fails on all three. *Inconclusive* otherwise.

**Effect sizes** were chosen before scoring. A recovery difference of 0.20 is the smallest gap treated as operationally meaningful, and 0.05 is "no difference".
- In absolute terms (audit §2), 0.20 of recovery is 0.20 × the B2-to-oracle gap, about 1.9 %, 1.7 % and 1.5 % of recorded annual export in semiurb4, semiurb5 and urban6: roughly 7.5, 13.0 and 8.9 MWh a year.
- R_k is defined for the verification policies only. B0 and B1 can believe ratings above the truth: they are shown separately, with their export and unsafe counts, not as recovery.

---

## 8. Negative controls

| Control | Test | What would undermine the study |
|---|---|---|
| **A** no binding thermal constraint | rural1 cables: the certified-irrelevant count = all lines; VoI of any cable = 0 | Non-zero cable VoI in rural1 means an implementation fault |
| **B** transformer dominates | Cable VoI under U2 in rural2 and rural3 (≈ 0); U-T: verifying the transformer recovers its full loss | Cable VoI comparable to the cable-limited networks |
| **C** correct records | U0: B0 = B4 (0 unsafe, equal export); any recovery by verification is uncertainty-resolution value, reported as such | B0 ≠ B4 under U0 means a fault |
| **D** rating-only change | ≤ 4 new AC solves. urban6, on the day with the most curtailed daylight steps under recorded ratings (recomputed from the Phase 5 cache and recorded in the ledger; ties by the earliest day; board check: day 144, 20 steps), at the step with the largest available PV that day. Both solves at cap level 0 with identical injections: the nominal network, and the same network with line 33's `max_i_ka` × 0.8. Compare `res_bus.vm_pu` and `res_line.i_ka` (not `loading_percent`); they must agree to ≤ 1e-9 relative. Mission 10's Control B already reports the same on another network | Any difference |
| **E** impedance plus rating | The Phase 8 `line_local` cache against Phase 5 nominal on the same days, steps and levels. **Provenance and alignment check first:** both manifests match their recomputed fingerprints (`fullstate.fingerprint`, `stress.fingerprint`); both cover days 35–364; PV scale and variant agree; the available-PV series is identical. **Currents are compared as currents:** the `line_local` loading of the modified cable (index from `stress.local_line`) is multiplied by `LINE_RATING_FACTOR` = 0.8 before comparison. The change in transformer P (MW), in other feeders' voltages (p.u.) and in the cable's current is **reported** as the measured propagation of the impedance error, not tested against a tolerance | — (a contrast, not a test) |
| **F** perfect knowledge | Verifying all candidates equals B4 on E (decisions identical) | Any difference |
| **G** information without decision change | VoI of certified-irrelevant cables = 0 exactly; the count of zero-value verifications among candidates | — |
| **H** competing bottlenecks | The share of E-steps where verifying the top-B7 asset alone leaves another cable or the transformer binding; bottleneck-shift maps | — |
| **I** simple heuristic | §7, Control I | — |
| **J** safety by zero export | The cap-0 policy: 0 unsafe, export 0. Reported as a reference, never as a success | — |
| **B3 against B2** | B3 is the componentwise minimum of the N_prior **sampled** scenarios, so it equals B2 only up to a finite-sample gap. It is slightly less conservative than the interval's lower bound, and it can be unsafe when a truth draw falls below the sample minimum: the scenario approach's known finite-sample risk. The export gap and B3's unsafe counts are reported | A B3 decision **more conservative** than B2 on any step means a fault |

---

## 9. Statistics

- **The unit** is a truth draw: 200 independent draws by design. Means and the 5th–95th percentiles across draws are reported. Policy differences are paired by draw.
- **Steps within the evaluation period** are time-correlated. They are **aggregated** into period totals, not treated as independent observations.
- **The networks are not replicates.** Verdicts are per network, with the stated "all 3" / "≥ 2 of 3" rules.
- **No population claim** about real LV feeders is made. All magnitudes are conditional on the hypothetical uncertainty widths.
- **Threshold comparisons** use the point estimate, as pre-specified. Each paired mean difference is reported with its Monte-Carlo standard error and its 5th–95th percentile interval. A verdict whose margin is below twice the standard error is flagged as **fragile**.

---

## 10. Computation, outputs and data

- **New AC solves:** ≤ 4 (Control D only). Everything else re-labels cached states.
- **CPU:** ≤ 1 h expected; 3 CPU-h is the ceiling.
  - **Enumeration counts:** OB, ≤ 175 subsets per network; H4, ≤ 847 subsets (sizes 1–6 over 10: 10 + 45 + 120 + 210 + 252 + 210); B8P pairs, ≤ 231 per greedy step.
  - **Reduction:** per (step, level), precompute the largest critical ratios loading/100 and their line indices, so a subset of size ≤ 6 is scored from the top-7 entries alone.
  - **A measured pilot timing on semiurb5** is recorded in the ledger before any scored run. If the projected total exceeds 3 CPU-h, the board reduces N_truth before scoring, and records the reduction as an amendment.
- **Outputs:**
  - in `analysis/asset_rating_information/results/` and `runs/`, both **local only**: per-network decision tables (compressed), evaluation results, a summary and the ledger;
  - in `figures/`: SVG figures, with the ODbL notice embedded;
  - total ≤ 300 MB.
- **Write-once artefacts** and a **foreground-only** execution rule. No detached jobs: an earlier Paperclip run was killed while awaiting a background process.
- **Seeds:** as in §5. The code version is recorded by sha256 in every artefact. This protocol's sha256 is pinned by the code.
- **Data notice:** a `DATA_ATTRIBUTION.md` following Mission 11's approach. The decision tables and results are a SimBench-derived derivative database, held locally. Figures and summary text are Produced Works.

---

## 11. QA plan

- **Pre-experiment:** one focused independent review of this protocol (the sandboxed QA agent). Corrections are applied before scoring and listed in the drafting record.
- **Post-experiment:** one independent review of code, numbers, controls, information boundaries, VoI calculations and claims. One correction round.

## 12. Stop conditions

- **Control C, D, F or B3 = B2 fails:** stop and fix the implementation before any interpretation.
- **Control E's provenance and alignment check fails:** Control E is NOT COMPARABLE. This does not block H1–H5.
- **If the top-m restriction binds,** H4 bounds the minimal sufficient set within that pool only, and says so.
- **The cable-limited networks show B2 loss < 1 % on E** (contradicting the audit): report "no decision relevance" and stop H3–H5.
- **Any deployable policy is found reading ρ_true:** its results are void.

## Drafting record (before scoring)

**Revision 1** (sha256 `0e5b317aa09482f9…`) was reviewed in Paperclip AKK-74: **PROCEED WITH CORRECTIONS** (1 blocker, 10 major, 7 minor or documentation findings). Revision 2 applies all of them:

| Finding | What was done |
|---|---|
| F1 (blocker) | The exhaustive searches (OB, H4) run over the top-10 certificate candidates, with enumeration counts, a reduction and a pilot timing (§10); H4 is bounded within that pool |
| F2 | Planning pool against certificate pool (P ∪ E); the count of evaluation-only cables (board check: 0) |
| F3, F4 | Control E compares currents (the modified cable × 0.8); the provenance and alignment check replaces a physical tolerance |
| F5 | One topology convention (`create_nxgraph`, switches respected), asserted radial (board check: radial; `df` = `parallel` = 1) |
| F6 | VoI is defined, with expected, best and worst cases, for P and E |
| F7 | H5(b) is a check; the H5 verdict rests on (c) |
| F8 | The budget-matching rule for H3b |
| F9 | B5 samples from the candidate pool; B5-all is a weaker reference |
| F10 | B9 is fully specified |
| F11 | The worst-case sentence is narrowed; minimax regret and upside are named |
| F12 | Transformer apparent power; `r_rec` includes `df · parallel`; the U3 ratios are labelled stylised |
| F13 | B8P searches all pool pairs |
| F14 | H3a has an inconclusive band; the fragile-margin rule |
| F15 | Control D is fully specified (urban6, day 144) |
| F16 | `DATA_ATTRIBUTION.md` is created before any artefact |
| F17 | The question wording, the U-T statement as hypothetical, and the absolute effect sizes |
| F18 | The prior is drawn once per (network, model); U2′ is added as the misspecification check |

**Board zero-solve facts added** (`docs/provenance/mission12_board_audit/`): radiality, the `df`/`parallel` factors, the pool sizes, and the Control D day.

**Revision 2.2** (before scoring; prompted by implementation task 2, AKK-76, whose artefacts are unscored tables, controls and a pilot timing):
- §10's H4 subset count is corrected: it is 847 (sizes 1–6 over 10), not 386.
- **A structural fact, found before any scoring.** In every SimBench network each feeder uses one `std_type`, so routes coincide with feeders. On semiurb4, semiurb5 and urban6, the whole w = 0.2 candidate pool lies in **one** route. U4 therefore has a single verification unit, and resolves it at k = 1 by construction.
- **To avoid a predetermined verdict,** the H3 and H5(c) verdicts are evaluated **under U2 only**. U4 results (recovery, H4) are reported descriptively, as the "record errors correlated at feeder level" bracket.

**Revision 2.1** (before scoring; prompted by implementation task 1, AKK-75):
- B9's recount uses the revealed ratings of verified assets (adaptive), with B9-static reported. B8 and B8P are stated to be non-adaptive.
- The B3 control is restated: revision 2's "identical, any difference is a fault" was wrong for a sampled scenario set (§1.1 holds for the set Θ, not for finite samples from it).

Revision 2 was `68497c437d646913…`.

## Amendments (after the first scored computation)
(none)

**A1 (2026-10-25; AKK-77) — B9 implementation defect; evaluations re-run.**
- **Found:** a board sanity check of the first six scored evaluations, before any verdict. B9 stopped after its first round in every draw: urban6 under U2 realised 4 verifications at k = 6 and 8, while line 3 still blocked on 847 planning steps after the trunk was verified.
- **Cause:** the runner's per-round reveal wrapper asked the rule for a budget of round-number units. When the first round verified a whole co-blocking path (more than one unit), the next request returned the same set, and the wrapper misread that as the rule's own termination (protocol §6, step 3).
- **The fix:** each round asks for (units verified so far + 1). Termination is declared only when the rule verifies nothing new.
- **What is kept:** the six evaluation artefacts produced with the defect (rural1 U0 and U2; rural2, rural3, semiurb4 and urban6 U2) are moved to `results/superseded_A1/` and `runs/superseded_A1/`. They are kept, not deleted, and are not used.
- **What is re-run:** every evaluation, on the fixed code. Nothing in the protocol's definitions, thresholds or hypotheses changes.
- **The protocol check:** from this amendment on, the code pins the protocol text **above** the Amendments heading (`9fc9108c…`, revision 2.2's as-executed text), so that appended amendments do not break it. The full-file hash is still recorded in every artefact.

**A2 (2026-10-25; AKK-79) — scoring-harness reduction sizing; evaluations re-run.**
- **Found:** evaluation batch 1 stopped at `evaluate rural3 U4` on the exactness guard of the §10 reduction (`decide_reduced`: "keeps 9 entries, too few for |S| = 14"). The guard fired as designed, and nothing was truncated silently.
- **Cause:** the runner sized the reduction from the pool's *unit* count. Under U4 a route unit reveals every segment on the route, so a scored set can hold more table columns than (units + 2).
- **The fix:** size the reduction from the largest number of table columns any scored set can reveal (capped at the table width), with a regression test showing that the reduced decision equals the full decision on a route-unit case.
- **What is kept:** the 16 evaluations completed in batch 1 (rural1 and rural2: all six models; rural3: U0, U2, U2w3, U3) passed the guard, so they were exact. They are nevertheless moved to `results/superseded_A2/` and `runs/superseded_A2/`, so that every scored result comes from one code version.
- **What is re-run:** everything, on the A2 code. No definition, threshold or hypothesis changes.

**A3 (2026-10-25; AKK-81) — OB scored below its budget; evaluations re-run.**
- **Found:** a board review of evaluation batch A (30 evaluations, on the A2 code), before any verdict. OB, the §6 ex-post best set for k ≤ 3, scored below the deployable policies at k = 1 and 2. On semiurb4 under U2 it scored R = 0.020 against B6's 0.271 at k = 1, even though semiurb4's whole pool (6 cables) lies inside OB's top-10 search set, where a best-set reference cannot lose.
- **Cause:** the runner searched OB only at k = 3 and kept two states per draw: the empty set, and the best set of size ≤ 3. Wherever that set held more units than the budget, the §7 budget-matching rule scored k = 1 and 2 as the empty set, which is B2.
- **The fix:**
  - per draw, keep the best non-empty subset of size ≤ k for each k = 1, 2, 3, drawn from the same 175 subsets and scored at its own budget;
  - for k > 3, OB carries its k = 3 set and is reported as searched to k ≤ 3 only;
  - record the modal set per k.

  A regression test checks that OB's per-draw export is non-decreasing in k. It also checks that, on a table whose pool lies inside the top-m, OB is at least every deployable policy at the same k ≤ 3 under U2.
- **What is unaffected:**
  - OB enters no hypothesis or verdict (§7), and OB's objective is unchanged: export under truth, over the 175 non-empty subsets counted in §6 and §10.
  - No non-OB quantity changes.
  - Batch A reproduced superseded_A2's 16 combinations exactly, which confirms that A2 only widened an exact reduction.
- **What is kept:** the 30 batch-A artefacts are moved to `results/superseded_A3/` and `runs/superseded_A3/`.
- **What is re-run:** everything, on the A3 code. No definition, threshold or hypothesis changes.

**A4 (2026-10-25; AKK-84) — two verdict read-out gaps; disclosure only, nothing re-run.**
- **Found:** a board review of `results/verdicts.json`, which was written by the frozen A3 code from all 36 evaluations.
- **Gap 1, Control D:**
  - `controls.D.pass` is null. `cmd_verdicts` reads `pass` at the top level of `results/control_d.json`, but the record stores it at `rating_only_change.pass`, which is **true**: |Δ res_bus.vm_pu| = |Δ res_line.i_ka| = 0.0 exactly, over 59 buses and 57 lines; only `loading_percent` changes, by the rating factor.
  - Effect: none on any verdict. §12's stop rule fires only on a *failed* Control D, and D passes in substance, so the rule is correctly not triggered. H2 is analytic.
- **Gap 2, the H3a fragility flag:**
  - The §9 fragile-margin rule (margin < 2·SE) applies to every verdict, but `verdicts.json` reports no flag for H3a.
  - H3a's maximum R₁ is 0.2705 (B6 = B7 = B8 on semiurb4, SE 0.0210). Its margin over the 0.25 rejection threshold is 0.0205, below 2·SE = 0.0420, so **H3a's REJECTED verdict is fragile**.
- **Remedy:** the frozen evaluation code is not edited, because its sha256 is pinned in all 36 evaluations. The read-out module (`analyse_stage_a.py`) takes Control D from `rating_only_change.pass` and computes H3a's fragility, citing this amendment. `verdicts.json` is kept as written.

**A5 (2026-10-25; AKK-87) — post-QA read-out corrections; disclosure only, nothing re-scored.**
- **Found:** the one independent post-experiment review (AKK-87, ACCEPT WITH CORRECTIONS). It was written after `verdicts.json`, as was A4.
- **The read-out module (`analyse_stage_a.py`, not the frozen evaluation code) now adds:**
  - **§9 fragility flags** for H5(c), using the per-network margin over 0.50 against 2·SE, and for H4, using the draw-share margin over 0.95 against 2 × the binomial SE.
  - **Paired-SE fragility for H3b and H3c,** from the per-draw recovery differences. The existing flags are kept and labelled "conservative (summed marginal SEs)".
  - **An energy-weighted recovery,** (mean export(policy) − mean export(B2)) / (mean export(B4) − mean export(B2)), reported **as a secondary descriptive statistic**. The §7 verdict statistic stays the mean of per-draw ratios.
  - **Disclosures:**
    - the §5 `worst_MWh` field is a 100-sample minimum, so it is > 0 in some records under continuous models; §1.2 concerns the set Θ;
    - Control G evaluates three non-pool columns per combination;
    - H4's scored count includes the empty set and the named candidates;
    - Control D's cap is level index 0 (c = 1.0, uncapped);
    - the P/E split is temporal only;
    - no multiplicity adjustment is made.
- **Figure corrections:** policy labels; no connector to the "all" point; an energy-weighted panel row; a readable complementarity panel. The attribution notice override is restored after drawing.
- **What is kept:**
  - the first read-out, `results/superseded_R1/` (the summary and six figures);
  - `verdicts.json` and every evaluation artefact, unchanged.
- **No verdict changes.**
