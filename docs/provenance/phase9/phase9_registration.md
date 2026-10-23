# Phase 9: registration

**Title:** Day–night voltage-residual contrast at sparse, pre-committed meters, for single-cable asset-record errors on SimBench LV benchmark networks.

**Registration date:** 2026-10-23. Written on the owner's instruction before any Phase 9 statistic is computed. The owner's Git commit of this file is the registration timestamp.

**Status:** EXPLORATORY, on examined benchmark data (Phases 4–8 and the Q1-L1 addendum). It contains one pre-registered held-out statistic (R5, §9), labelled "pre-registered held-out statistic, exploratory programme". Nothing here is confirmatory, and nothing transfers to a real feeder.

**Admitted:** by the owner on 2026-10-23 as Option B of the Phase 9 scoping design (Paperclip AKK-21). The design was independently reviewed in AKK-20 (CHANGES REQUIRED) and re-reviewed in AKK-22 (PASS WITH LIMITATIONS). The admission includes:
- AKK-22's protocol additions N-1, N-2, N-3 and N-7;
- its corrected wording N-4a and N-4b;
- the owner's sub-decisions (i)–(iv), recorded in §13.

**Not changed:**
- No Phase 8 hypothesis, threshold, frozen output or `src/gridpulse/` module. Phase 8 is not re-run.
- The Q1-L1 registration (`docs/provenance/phase9/q1_addendum_registration.md`, commit `3ce2693`) and its committed results (`1bba4e8`) stand as they are.
- §13 amends three Q1 definitions for Phase 9 statistics only.

## 1. Questions
- **Q9a, coverage.** A single cable's impedance is recorded wrongly. What fraction of such errors does a day–night voltage-residual contrast detect? The meters are placed by rules frozen in Phase 6, before this question existed. The answer is reported as a function of σ_tot and the meter budget K.
- **Q9b, localisation.** Does the per-bus sign pattern of the residual identify the section below the faulty cable?
- **Secondary questions:**
  - Does the Q1 magnitude predictor hold on four held-out networks (R5)?
  - What is the smallest resistance error that still reaches band C (W8)?
  - How does a wrong-length error, which scales R and X together, change the signature (W9)?
  - What is the largest diurnal systematic meter error the method tolerates (A*, §10)?

Δ (§5) is noise-free, has no estimation error, is taken at no cap and assumes constant-power injections. Every detection rate here is therefore an **upper bound** for this error class.

## 2. Scope and data
- **Sweep networks:** `1-LV-semiurb4--2-sw` and `1-LV-urban6--2-sw`.
- **Held-out networks (W5):** `1-LV-rural1--2-sw`, `1-LV-rural2--2-sw`, `1-LV-rural3--2-sw` and `1-LV-semiurb5--2-sw`, each at its own `line_local` cable (`stress.local_line`). Their per-bus residual and downstream sets have not been computed before this registration.
- **Days:** the scored days of the evaluation period, `grid_study.period_days("evaluation")` ∩ [`FIRST_DECISION_DAY`, `ds.LAST_DAY`]. These are the 183 days of Q1, in Q1's order.
- **Level:** `CAP_LEVELS[0] = 1.0` (no cap) only.
- **Nominal leg:** `fullstate.load_states(outputs/sense_study/fullstate_cache, code, "nominal", days)`, level 0. It is read-only, and the manifest must match.
- **Truth legs:**
  - W5: `stress.load(outputs/robust_study/fullstate_cache, code, "line_local", days)`, level 0. Read-only, as in Q1.
  - W6, W8, W9: new level-0 power flows (§6).
- **Daylight:** step t of day d is daylight iff `available[d][t].sum() > 0`. Here `available = grid_study.daily_arrays(grid.absolute_profiles(net))["sgen_p_mw"]` of the nominal variant network at `ds.pv_scale(code)`. The mask is network-wide (G5) and identical for every cable.

## 3. Candidate cables and topology (N-2)
All quantities here come from the nominal variant network (`ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))`) and `sensing.network_layout`.

- **Candidates:** every index of `net.line.index` that is not in `layout.feeder_heads`.
  - Registered counts: semiurb4 39, urban6 50.
  - Stage 1 stops on any other count.
- **downstream(l):** the LV buses disconnected from the LV busbar when line l is removed.
  - Computed on an `nx.MultiGraph` whose edges are keyed by line index (G1). Every index in `net.line.index` is enumerated; tree edges are not used.
- **Structural invariants.** Stage 1 checks these per network and stops on any failure:
  1. The number of LV buses equals the number of lines plus 1. The line graph over the LV buses is connected and acyclic. Every line has `parallel == 1` and `in_service == True`. Every line switch (`et == "l"`) is closed.
  2. For every candidate l, downstream(l) is non-empty and excludes the busbar. It must also equal a second, independent derivation: the set of buses whose busbar path (`nx.shortest_path` on a plain `nx.Graph`) traverses line l.
  3. The registered cables reproduce Q1:
     - semiurb4: line 37 is `stress.local_line`, with downstream {39, 40};
     - urban6: line 3 is `stress.local_line`, with downstream {6, 9, 19, 20, 23, 25, 29, 32, 34, 40, 42, 43}.
- **Cable facts:**
  - R_l = `r_ohm_per_km × length_km` (as recorded) and X_l likewise;
  - installed downstream PV (`sn_mva`);
  - P_l, the mean over the daylight steps of retained days (§7) of the summed availability of the generators on downstream(l), in MW (the Q1 definition);
  - the screening score S_l = R_l · P_l.

## 4. Error definitions
Each error is applied to a fresh copy of the nominal variant network. Nothing else changes.

| ID | Where | Change | Work item |
|---|---|---|---|
| E-R(1.5) | every candidate l | `r_ohm_per_km` × 1.5 and `max_i_ka` × 0.8. For l = `local_line` this is exactly `stress.stress_network(code, "line_local")`. | W6 |
| E-R(f) | the registered cable | `r_ohm_per_km` × f, f ∈ {1.1, 1.25, 2.0}, `max_i_ka` × 0.8. f = 1.5 is the W6 artefact of that cable and is not recomputed. | W8 |
| E-L(g) | the registered cable | `length_km` × g, g ∈ {1.25, 1.5}. R and X scale together; per-km values and `max_i_ka` are unchanged. | W9 |

The registered cables are semiurb4 line 37 and urban6 line 3.

**Power flows:**
- One run is 183 × 96 = 17,568 level-0 solves.
- W6 is 89 runs, 1,563,552 flows; W8 is 6 runs, 105,408; W9 is 4 runs, 70,272.
- In total, 1,739,232 new flows.

## 5. Quantity
Δ(e, d, t, b) = vm_truth(e; d, t, level 0, b) − vm_nominal(d, t, level 0, b), for error e, scored day d, step t and LV bus b.
- **Valid step:** both legs are finite at that step. A failed flow is NaN, as in `fullstate.day_states`.
- Means use valid steps only (N-1).

## 6. Sweep physics, outside `src/`, which is unchanged
A new script (§12) reproduces the `stress._init_worker` / `fullstate.day_states` path at level 0 only.

**Setup, per error e:**
1. Build the error network as in §4.
2. `arrays = grid_study.daily_arrays(grid.absolute_profiles(net))`.
3. `solver = ds.VariantSolver(net, ds.NOMINAL)`.
4. `storage = ds.storage_schedule(net, ds.NOMINAL, len(arrays["sgen_p_mw"]))`.
5. `buses = fullstate.lv_buses(net)`.

**Per day d:**
1. `sets = ds.day_sets(arrays, d, solver.pv_rating_mw, 1)`.
2. `storage_d = ds.day_storage(storage, d, 1)`.
3. Call `solver.reset()` once.
4. For each t in 0…95: `solver.solve(sets["load_p_mw"][0, t], sets["load_q_mvar"][0, t], sets["sgen_p_mw"][0, t], storage_d[0, t])`.
5. If every returned margin is finite, `vm[t] = net.res_bus.loc[buses, "vm_pu"]`; otherwise `vm[t]` is NaN.

**Parallelism:**
- `ProcessPoolExecutor(max_workers=3)` over runs (one task per error e), at `nice -n 19`.
- If a process pool cannot run under the agent sandbox, the driver falls back to one worker. The fallback is recorded and is not a deviation.
- No sandbox, permission or `src/` change is made to obtain parallelism.

Level-0-only solving changes the solver's warm-start sequence relative to the cache, where cap levels are interleaved. The reproduction gate (§11) measures the consequence.

## 7. Days, artefacts and accounting (F-2, N-1, F-11)
**Day retention.** These rules are network-level, identical for every error, and fixed in Stage 1:
- A scored day is **retained** iff it has at least 1 daylight step and at least 1 night step.
- A scored day with zero night steps is a hard error.
- D_ret is the number of retained days, and D_eff = 0.95 · D_ret.
- n̄_day and n̄_night are the medians of the daylight and night step counts over retained days.
- Thresholds and statistics use the same retained days. This removes Q1's G4 mismatch.
- Q1's committed counts give semiurb4 170/183 and urban6 175/183.
- **Sensitivity:** repeat every statistic and threshold with retention at 8 or more daylight steps.

**Per-error artefact.**
- **Path:** `analysis/phase9/sweep/<physics_key[:16]>/<network>/<E-R|E-L>-<factor>-line<idx>.npz`, plus a sidecar `.json` with the same stem.
- **Write discipline:** the artefact is written to a temporary file in the same directory, then moved into place with `os.replace`. No multi-run files exist.
- **Arrays** (accumulated in float64, cast on write; Δ only, never absolute vm, because float32 at vm ≈ 1 resolves only 1.2e-7):

| Array | dtype | Shape | Content |
|---|---|---|---|
| `dmean_daylight` | float32 | [183, B] | per scored day and LV bus: mean of Δ over valid daylight steps (NaN if none) |
| `dmean_night` | float32 | [183, B] | the same over valid night steps |
| `n_daylight_valid`, `n_night_valid` | int16 | [183] | valid steps per day |
| `n_daylight_steps`, `n_night_steps` | int16 | [183] | daylight and night steps per day |
| `failed_truth`, `nan_nominal` | int16 | [183] | failed truth flows and non-finite nominal entries per day |
| `day_index` | int32 | [183] | scored days |
| `bus_index` | int32 | [B] | LV buses, in `fullstate.lv_buses` order |

**Keys, stored in both files:**
- `physics_key`: sha256 over `stress.fingerprint()`, `fullstate.fingerprint()`, the nominal-leg `manifest.json` text, the pandapower and numpy versions, the schema version, the level, `STEPS`, the ordered scored-day list and the text of the reduction definition.
- `spec_key`: network, line index, error type, factor and rating factor.
- Each run's runtime and worker count are also recorded.

**Driver:**
- It accepts an existing artefact only after recomputing both keys and finding them equal.
- On any mismatch, or on a malformed file, it **stops and requires explicit deletion**. This is the committed convention of `stress.py:219,221,247`.
- `--max-runs N` and `--time-budget-seconds S` make each invocation stop cleanly before the agent run cap. Invocations are planned at 20 minutes or less.

**Manifest:**
- `analysis/phase9/sweep/manifest.json` is **derived**: rebuilt by scanning the artefact directory and re-verifying both keys. It is never maintained incrementally.

**Completeness barrier:**
- Stage 3 computes no coverage or rule statistic unless every expected artefact (W6 89, W8 6, W9 4: 99 runs) is present and verified.

**Failed flows:**
- They are counted per run and day, and reported.
- Stage 3 stops, and the board reports to the owner, if failed truth flows exceed 0.1 % of all sweep solves, or 1 % of any single run's solves on retained days.
- Below those limits, failed steps are excluded as invalid, and every affected run is listed.

**Precision floor:**
- The cached nominal leg is float32 (`fullstate.py:67`), so Δ carries about 6e-8 to 1.2e-7 p.u. of quantisation.
- Any statistic below 1e-6 p.u. is reported as "at the cache precision floor", not as a measured magnitude.

## 8. Statistics and bands
**Per error e and LV bus b:**
- m(e,b): the mean over retained days of the daylight mean of Δ.
- night(e,b): the same over night means.
- k(e,b): the mean over retained days of (daylight mean − night mean).
- Day-level means use valid steps. A retained day on which a run has no valid daylight step, or no valid night step, is dropped from that run's average and counted.
- The median over days is a robustness check, with √(π/2) applied to the floors that average over days (Q1's `median_averaging_floors`).

**Floors and bands.** These are Q1's §5 formulas, with Stage-1 inputs taken over retained days:
- F_ind(σ) = σ / √(n̄_day · D_eff); F_bias(σ) = 0.98 σ.
- F_C,matched(σ) = 0.2 σ · √(1/n̄_day + 1/n̄_night) / √D_eff.
- F_C,real(σ) = σ · √(1/n̄_day + 1/n̄_night) / √D_eff.
- z_K = Φ⁻¹(1 − 0.025/K). Family-wise α = 0.05, two-sided Bonferroni.
- **Contrast bands on |k|:**
  - **A:** below z_K · F_C,matched;
  - **B:** from z_K · F_C,matched up to, but not including, z_K · F_C,real;
  - **C:** at or above z_K · F_C,real.
- **Level bands:** as Q1, reported only.

**σ_tot.**
- **Co-primary:** 0.01 and 0.005 (sub-decision ii). Both verdicts are always reported as a pair, and neither overrides the other.
- **Sensitivity:** 0.003 and 0.02.
- At 0.005 the `realistic`-type arm is the registered `sigma_0.005` condition (`noise_study.py:39`).
- The matched-bias arm at 0.005 is **band arithmetic only** (0.2·σ): no noise condition exists at that σ_tot (N-4b).

**Meter configurations.**
- The 25 frozen Phase 6 rules in `outputs/noise_study/development_results.json` `placements[network]` (sha256 `8c587b16…3dbd`): 5 named rules plus `random_0`…`random_19`. A configuration is the first K buses of a rule, K ∈ {1, 2, 4}.
- C_meter(e, rule, K) is the maximum over the configuration's buses of |k(e,b)|, banded with z_K.

**Coverage.**
- **Q9a headline:** at each σ and K, the fraction of (cable, rule) pairs over W6 with band C, per network. It is reported:
  - for all 25 rules;
  - for the 5 named rules;
  - for the 20 random rules;
  - with Wilson 95 % intervals, labelled descriptive, because pairs share days, profiles and topology.
- **Conditional coverage:** P(C | the configuration intersects downstream(l)) and P(C | it does not).
- **Intersection coverage (W3, zero-flow):** the fraction of pairs whose configuration intersects downstream(l). This is the topological ceiling against which the measured coverage is read.

## 9. Pre-registered rules
z is taken at K_all, the network's LV bus count. Each rule is evaluated at both co-primary σ, and each verdict is reported per σ.

| ID | Statement | Holds iff | Status |
|---|---|---|---|
| **R1** | Conditional night sign. Replaces Q1 §6's unconditional hypothesis. | Over the network's W6 pairs (l, b) with \|m\| ≥ z·F_ind, the share with sign(night) = −sign(m) is at least 0.90, in each sweep network. | rule |
| **R2** | Localisation. S_detect(l) = {b : \|k\| ≥ z·F_C,real and sign(night) = −sign(m)}; ref(l) = downstream(l) ∩ {b : \|m\| ≥ z·F_ind}. | For every evaluable W6 cable (ref or S_detect non-empty): S_detect(l) ⊆ downstream(l) and Jaccard(S_detect, ref) ≥ 0.8. | rule |
| **R3** | Per-cable shape: Q1 §6's shape prediction read per cable (sub-decision iii). | Spearman, over each network's W6 cables, of (S_l, max over downstream(l) of \|k\|) is at least 0.9. | rule |
| **R3s** | Q1 §6's per-bus reading. | Reported, no threshold: per cable, Spearman(\|m\|, resistance distance) within downstream(l) for n ≥ 3 (else a typed "undefined, n = …" record, G2), and whether argmax over all buses of \|m\| lies in downstream(l). | secondary |
| **R4** | Flatness (an addition). | CV = population sd / mean of \|k\| over downstream(l) is at most 0.2, for every W6 cable with \|downstream(l)\| ≥ 2 and max over downstream of \|k\| ≥ z·F_C,real. | rule |
| **R5** | **Held-out magnitude (W5)**: the only genuinely falsifiable member of W5. | ratio = m(b*) / m_pred lies in [0.50, 0.90] in **every** one of the four held-out networks. Here b* is the argmax over all LV buses of \|m\|, m is signed, and m_pred = 0.5 · R · P / V² with V = 0.4 kV (exactly Q1's `level_pu_downstream` and `ratio_observed_over_predicted`). | **held-out statistic** |
| R6 | Withdrawn as a rule (true by construction). | Reported: at the registered cables, band C ⟺ the configuration intersects downstream(l), over σ × K × estimator. | identity |
| R7 | False alarms of the meter alarm rule. | Control 1 (§10): the family-wise false-alarm rate is at most 0.05 within Monte Carlo error (Wilson 95 % lower bound ≤ 0.05). | rule |

**On the four held-out networks, R1, R2, R4 and R3s** are computed as **consistency checks**, not tests. They are near-deterministic consequences of radial flow reversal at a cable chosen to maximise downstream PV × R.

**Stated before any new number (HYPOTHESES):**
- R1/R2 can fail only at cables whose downstream flow does not reverse between day and night (little downstream PV). Such cables, if any, will be listed.
- W8: band C survives down to f = 1.1 at σ_tot = 0.01, at a meter on downstream(l) with K = 2 (extrapolated linearly from 3.4–5.6× headroom).
- W9: the downstream / off-downstream sign split is unchanged, while the ratio of |k| to E-R(1.5) differs from the R-only prediction by more than 10 %.
- A*_fa is about the band-C boundary, ≈ 3.5e-4 p.u. ≈ 0.035 · σ_tot.
- Any contradiction is reported as a contradiction, not reconciled.

**W8 and W9 outputs, descriptive:**
- f*: the smallest f in {1.1, 1.25, 1.5, 2.0} with max over downstream of |k| at or above z_2 · F_C,real(σ), per network and σ.
- The linearity of |k| in (f − 1): the slope ratio across f.
- For E-L(g): m, k and night per bus, compared with E-R(1.5).

## 10. Controls, all zero-flow
**Noise simulation.**
- **Leg:** noise enters the **measured (truth) leg only**. The comparison is measurement against model (F-5).
- **Per-day means:** noise is simulated analytically on the stored per-day means. For one meter on day d:
  - the daylight mean receives N(0, σ_v² / n_daylight_valid), and the night mean N(0, σ_v² / n_night_valid), independently;
  - the meter loses the whole day with probability 0.05 (`remote_missing`);
  - a static bias β_b ~ N(0, σ_bias²) adds equally to both means;
  - the 1-day delay removes the last retained day (period-end screening).
  - This is exact for the registered Gaussian, i.i.d.-per-reading model.
- **Conditions** (`noise_study.py:31-45`): `realistic`, `sigma_0.005`, `sigma_0.02` and `biased_meters_matched`.
- **Mandatory sensitivity:** the √2 measurement-against-measurement variant, with both legs noisy.
- **Seeds:** `np.random.default_rng(np.random.SeedSequence([20261023, sn._stable_int(network), sn._stable_int(condition), sn._stable_int(control), index]))`. Here `index` is the amplitude index, or 0.

**Control 1: unit test of the floor (R7).**
- Truth = nominal (Δ ≡ 0).
- For every rule × K and condition, compute the rate of "any of K meters has |k̂| ≥ z_K · F_C,real".
- For `biased_meters_matched`, also compute the rate against z_K · F_C,matched.
- 2,000 replicates per network × condition. Report Wilson 95 % intervals.
- It tests the floor's treatment of missing sensor-days, delay and day retention. It is not an empirical false-alarm rate for a real deployment.

**Control 2: diurnal-bias amplitude sweep (A*, N-3).**
- **Bias:** A · g_b · s(d, t) is added to each meter's measured leg.
- **Shapes:**
  - *square* (primary): s = 1 on daylight steps, 0 at night;
  - *sinusoid*: s = sin(π (i + ½) / n_d) on the i-th of the day's n_d daylight steps, 0 at night.
- **Signs:** g_b = ±1, i.i.d. per meter and replicate (primary). An *adverse* variant has g_b = −sign(k(e,b)) at every meter.
- **Grid:** A / σ_tot ∈ {0, 0.003, 0.006, 0.01, 0.02, 0.03, 0.06, 0.1, 0.2, 0.3}, under `realistic`-type noise at both co-primary σ_tot, K ∈ {1, 2, 4}.
- **A*_fa (primary, binding):**
  - Truth = nominal. Compute the family-wise false-alarm rate, as in control 1, pooled over the 25 rules.
  - A*_fa is the smallest A at which the rate exceeds 0.05.
  - 2,000 replicates per grid point.
- **A*_cov:**
  - The population is all W6 (cable, rule) pairs whose configuration intersects downstream(l).
  - Coverage(A) is the detection rate. A*_cov is the smallest A at which coverage ≤ 0.5 · coverage(0).
  - 400 replicates per grid point.
  - Under the alarm-on-|k| rule, a large bias *raises* alarms, so A*_cov may be "not reached". It is reported for both sign variants.
- **Crossings:** linear interpolation in the rate between the bracketing grid points, on log A. "≤ 0.003 σ" or "> 0.3 σ" is reported when the crossing is not bracketed.
- **Reporting:** in p.u. and as A/σ_tot, per network, σ and K, with replicate counts and Wilson intervals.

**Control 3: permuted day/night labels.**
- Day/night labels are permuted within each retained day (counts preserved), then k is recomputed.
- 200 permutations.
- It uses cached per-step data, so it runs at the registered cables and the four held-out cables only.
- It is a pipeline sanity check; the expected k is about 0.

**Control 4: random cable for R2.**
- For every W6 cable, compute Jaccard(S_detect(l), downstream(l′)) for every other candidate l′ of the same network.
- This is the topology-luck baseline.

**Control 5: random against designed placements.**
- Coverage of `random_0…19` against the 5 named rules (§8). These rules are frozen, so this is a baseline, not a choice.

## 11. Reproduction gate (F-1, N-7): Stage G
This runs at the registered cables (E-R(1.5), semiurb4 line 37 and urban6 line 3), through the §6 engine with `max_workers = 3`. This makes it the smoke run of the process pool too.

1. **Structural, exact.** Each must hold; any difference aborts:
   - the engine's cable equals `stress.local_line`;
   - its line table (`r_ohm_per_km`, `x_ohm_per_km`, `c_nf_per_km`, `length_km`, `max_i_ka`, for every line) equals `stress.stress_network(code, "line_local")`;
   - its storage schedule equals that network's `ds.storage_schedule`;
   - its scored-day, with-daylight and without-daylight day lists equal Q1's committed `registration_inputs.json`.
2. **Numerical, on vm.**
   - Cast the reproduced vm to float32 and compare with `stress.load(…, "line_local")` at level 0.
   - The NaN patterns must be identical. E = max |vm_repro − vm_cached|.
3. **Contrast of the discrepancy.** Take the daylight-mean minus night-mean of (vm_repro − vm_cached) per day, and its mean over retained days. E_C is its maximum over buses.
4. **Tolerances for E and E_C:**
   - **PASS:** ≤ 1e-6 p.u.
   - **WARN:** in (1e-6, 1e-5]. Record it. Label as precision-limited all off-downstream leakage statistics and all R1/R2 sign calls with |k| < 1e-4.
   - **ABORT:** above 1e-5.
5. **On PASS or WARN,** the gate's outputs are kept as those two cables' W6 artefacts, at 0 extra flows.
6. **On ABORT,** no sweep statistic is computed. Phase 9 reduces to its zero-flow items plus W5, and the board reports to the owner.

Stage G may run before this file is committed. It reproduces frozen arrays and computes no Phase 9 statistic.

## 12. Procedure, locations and invariants
**Stages, in order:**
1. **Stage 0.** Integrity:
   - sha256 of `outputs/robust_study/evaluation_results.json` `a70c0aed35f97d48eb1587c7f7e5b0eec995c4d7c523cccd6dcbef8afff802ef`;
   - `outputs/robust_study/freeze.json` `d191bb5dd416b7b9d5ed306f6cb2b68bcbe170aef753ad2cbb96a2114ab762bc`;
   - the 27 `freeze.json` `code_sha256` entries, with Q1's `__main__.py`/`demonstrator.py` log exception;
   - `outputs/noise_study/development_results.json` `8c587b16d1898e133f63ebcbc55c63e1efc828233a3bbf3c1a067a57f1923dbd`;
   - Q1's `registration_inputs.json` `0374cd09355dd513da11aee2e9cffa72ae14ea34f8d5fe24f998cf91a9006810` and `q1_results.json` `b24fe4523e87bcdcf20f7b8972697d17584754bbeaf1e7e89cad70710f535a9f`.
   - **Before Stages 1–3:**
     - this file must be tracked, with a commit returned by `git log -1 --format=%H -- docs/provenance/phase9/phase9_registration.md`;
     - it must be unmodified (`git diff --quiet HEAD -- <this file>`);
     - its sha256 is recorded.
2. **Stage G.** The gate (§11).
3. **Stage 1.** No vm is loaded and no flows are run. Stage 1 computes:
   - topology and invariants (§3) for all six networks;
   - candidates, downstream sets, cable facts, S_l and m_pred (W3);
   - intersection coverage;
   - retention and thresholds for all σ, K and estimators.
   It writes `analysis/phase9/results/phase9_inputs.json` (refusing to overwrite) and prints its sha256.
4. **Stage 2.** The sweep (§6–§7), in invocations of 20 minutes or less, until the completeness barrier holds.
5. **Stage 3.** Statistics. All are zero-flow except the artefacts already computed:
   - W1: R1/R3s/R4 at the registered cables, from Q1's committed per-bus arrays, checked against the sweep artefacts;
   - W2: hit rates and the R6 identity;
   - W5 from the caches;
   - all §8–§10 statistics, W8 and W9.
   It writes `analysis/phase9/results/phase9_results.json`, refusing to overwrite.
6. **Stage 4.** Repeat Stage 0.

**Locations:**
- Code: `analysis/phase9/phase9_sweep.py` (engine, driver, gate) and `analysis/phase9/phase9_analysis.py` (Stages 0, 1, 3 and 4).
- Tests: `analysis/phase9/tests/`.
- Artefacts: `analysis/phase9/sweep/`, about 8 MB, npz plus JSON.
- Results: `analysis/phase9/results/`.

**Invariants:**
- No change to `src/gridpulse/`, `outputs/`, `data/`, `.venv/`, `docs/provenance/` (except this file, written for the owner), the Q1 files or any sandbox or permission setting.
- No new dependencies and no network access. Git is the owner's.

## 13. Owner sub-decisions and amendments to Q1 definitions (Phase 9 only)
- **(i)** W5 is labelled "pre-registered held-out statistic, exploratory programme". R5 is its only falsifiable rule; R1/R2/R4 are consistency checks there, and R6 is an identity.
- **(ii)** σ_tot = 0.005 is promoted to co-primary with 0.01. This amends Q1 §5 ("the primary pair is at 0.01") for Phase 9 statistics. The matched-bias arm at 0.005 is band arithmetic only (N-4b).
- **(iii)** Q1 §6 "Shape: monotone in downstream PV × R, with the argmax downstream of the stressed line" is ambiguous:
  - It can be read per bus. This is how AKK-17 implemented it (`q1_voltage_residual.py:803-806`), and the only reading testable with Q1's one cable per network.
  - It can be read per cable, which is how its symbols are defined.
  - Phase 9 **disambiguates it to the per-cable reading, with a ≥ 0.9 threshold, as R3**, and keeps the per-bus form and the argmax clause as the reported secondary R3s. This is a Level C clarification of a registered definition.
  - Q1 §6's unconditional night-sign HYPOTHESIS is amended to the conditional R1, and R4 is added.
- **(iv)** The diurnal-bias arm is added as the amplitude sweep of §10, control 2.

## 14. Interpretation map
- **Coverage (Q9a)** is reported, not tested, against intersection coverage, its topological ceiling.
  - Headline: σ ∈ {0.01, 0.005}, K = 2, all 25 rules, per network.
  - A large gap between P(C | intersect) and 1 means signal limits detection, not placement.
- **R1/R2 hold:** the night/day sign split localises the faulty section across the candidate population, at least for cables whose flow reverses.
- **R1/R2 fail:** report which cables fail and whether they are non-reversing. The localisation claim is then restricted to the subset where they hold.
- **R5 fails** in any held-out network: the magnitude predictor does not transfer. S_l must not be used to extrapolate coverage beyond the sweep.
- **A*_fa:**
  - Any diurnal systematic error above A*_fa produces alarms above the registered α. A*_fa is the method's tolerance, and it bounds its headline bias-cancellation advantage. That advantage is about 312× under matched bias and holds only while static bias dominates; under `realistic` noise the contrast is 0.76× as sensitive as the level.
  - No deployment claim is made.
- **Gate ABORT:** see §11.6.

## 15. Caveats carried in every claim
- Q1 §10 applies: constant-power injections; balanced three-phase; no Q(U)/P(U); one error at a time; no cap; SimBench benchmark networks only.
- All six networks are examined data. The held-out networks' `line_local` margins and violation counts were already read in Phase 8.
- The simulated noise model is Gaussian and i.i.d. per reading, with whole-day missingness. No other measurement error is modelled except the §10 diurnal arm.
- The novelty is narrow. Residual-pattern detection of structural errors is prior art (`docs/phase6_literature.md:79-84,153-158`: Castin et al. 2026; Vanin & Van Hertem 2022), as is the near-full-metering caveat (Waeresch et al. 2017). Phase 9's contributions are:
  - the static-bias-cancelling day–night contrast at sparse, pre-committed meters;
  - the coverage-versus-placement curve;
  - A*;
  - a population statement over 89 benchmark cables.

## 16. Drafting record
This file transcribes AKK-21 with the AKK-22 amendments. The following were fixed while drafting; none changes a reviewed rule's threshold or the option's scope:
- **W8:** f = 1.5 reuses the W6 artefact, so W8 needs 6 new runs, not 8; total new flows are 1,739,232 rather than 1,774,368.
- **W9:** the factors {1.25, 1.5}, which AKK-21 left open.
- **W3:** the "predictor-based coverage" of AKK-21 §6 is replaced by intersection coverage plus the m_pred map, because Q1's linear predictor is for the level m, not the contrast k.
- **N-1:** the 0.1 % / 1 % failed-flow limits make "zero unexplained failures" operational.
- **N-3:**
  - Under the alarm-on-|k| rule, the reviewed A*_cov is not monotone in A.
  - A*_fa is therefore made the binding A*, and A*_cov is also reported with an adverse-sign variant.
- **Controls 1 and 2** are simulated analytically on per-day means, which is exact for the registered noise model. Control 3 therefore runs on cached per-step data at the registered and held-out cables only.
- **Network-level aggregation** of R1 (pooled share), R2 and R4 (every evaluable cable) is made explicit.
- **Line switch states** are added to the §3 structural invariants.
- **Stage 0** checks that this file is committed before Stages 1–3.
