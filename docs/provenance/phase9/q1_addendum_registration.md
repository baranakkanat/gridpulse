# Phase 8 exploratory addendum Q1-L1: registration

**Registration date:** 2026-10-21. Written on the owner's instruction before any Phase 9 implementation or evaluation. The owner's Git commit of this file is the registration timestamp.
**Status:** EXPLORATORY ADDENDUM to Phase 8. It uses examined SimBench data and networks from Phases 4–7. Nothing here is confirmatory, and nothing transfers to a real feeder.
**Admitted:** by the owner on 2026-10-21. Design: Paperclip AKK-15 Part D, independently reviewed in AKK-14 and re-reviewed in AKK-16 (PASS WITH LIMITATIONS). The fixes AKK-16 required before registration are applied below.
**Not changed:** no Phase 8 hypothesis, threshold, frozen output or `src/gridpulse/` module. Phase 8 is not re-run or re-frozen.

## 1. Question
Under the `line_local` truth (one cable with `r_ohm_per_km` × 1.5 and `max_i_ka` × 0.8; `x_ohm_per_km` unchanged), how large is the **idealised best-case** truth-minus-nominal LV bus-voltage residual? "Best case" means: noise-free, free of estimation error, at the no-cap level (maximum PV export), and at the single worst-case cable placement in each network.

Does that magnitude reach the floor that a smart-meter-class sensor could resolve?
- for the level residual, a sensor with an unknown fixed calibration offset;
- for the day-night contrast, a sensor whose offset cancels.

Δ is an **upper bound** on any operational residual. Bands A and B are therefore strong negative results; Band C is only permissive.

## 2. Scope
Networks: `1-LV-semiurb4--2-sw` and `1-LV-urban6--2-sw` (the 2 of 6 Phase 8 networks with material `line_local` created violations: 399 and 319). Truth: `line_local`. Days: the scored days of the Phase 8 robust-study evaluation context (D as realised).

## 3. Quantity
`Δ(c, d, b, t) = vm_truth(d, t, 0, b) − vm_nominal(d, t, 0, b)`, where:
- level index 0 is `CAP_LEVELS[0] = 1.0`, i.e. no cap (`src/gridpulse/grid_study.py:42`);
- the truth leg is `ctx.states[d]["vm"]` and the nominal leg is `ctx.nominal_states[d]["vm"]`, from the context built by `robust_study.truth_context` for `line_local`. That puts both legs on the same days at the same realised injections, by construction (`robust_study.py:118-125`, `sensing.py:516`);
- daylight steps are those where `ctx.available[d].sum(axis=1) > 0` (as `margin_study.py:123`); night steps are the complement.

## 4. Statistics (two co-primary)
- **Level.** `m(c, b) = mean over d of [mean over daylight t of Δ]`.
  - `M_meter(c) = max over b ∈ B_meter of |m|`.
  - `M_all(c) = max over all LV buses` (reported, not a verdict).
- **Contrast.** `k(c, b) = mean over d of [mean over daylight t of Δ − mean over night t of Δ]`.
  - `C_meter(c) = max over b ∈ B_meter of |k|`.
  - `C_all(c)` is reported.
  - A fixed per-meter offset cancels in this contrast, because the offset in `sensing.py:242-243` has no day or step index.
- `B_meter` = the frozen Phase 6 `placements["topology"][:2]`: semiurb4 {26, 43}, urban6 {18, 19}.
- The estimator is the mean over days. The median over days is reported as a robustness check, with its floor × √(π/2) = 1.253.
- Both co-primary verdicts are reported as a pair, and neither overrides the other.

## 5. Floors and bands: formulas fixed now, inputs fixed in Stage 1
**Inputs** (Stage 1, read before any `vm` array is loaded):
- n̄_day and n̄_night: median daylight and night steps per scored day;
- D, the scored days, and D_eff = 0.95 · D, allowing for `remote_missing` = 0.05 in `realistic`;
- K_meter = 2 and K_all, the LV bus counts (43 for semiurb4, 58 for urban6).

**Multiplicity:** family-wise α = 0.05, Bonferroni two-sided, z_K = Φ⁻¹(1 − 0.025/K).

**Primary σ_tot = 0.01** (the registered `realistic` and `biased_meters_matched` conditions, `noise_study.py:38,43-45`).

**Level floors:**
- F_bias = 0.98 · σ_tot, the matched per-meter offset, which does not average out;
- F_ind = σ_tot / √(n̄_day · D_eff).

**Level bands on M_meter:**
- **A:** M_meter < z₂ · F_ind;
- **B:** z₂ · F_ind ≤ M_meter < z₂ · F_bias;
- **C:** M_meter ≥ z₂ · F_bias.

**Contrast floors:**
- F_C,matched = 0.002 · √(1/n̄_day + 1/n̄_night) / √D_eff (the random arm of `biased_meters_matched`);
- F_C,realistic = 0.01 · √(1/n̄_day + 1/n̄_night) / √D_eff.

**Contrast bands on C_meter:**
- **A:** C_meter < z₂ · F_C,matched;
- **B:** z₂ · F_C,matched ≤ C_meter < z₂ · F_C,realistic;
- **C:** C_meter ≥ z₂ · F_C,realistic.

**Further rules:**
- `M_all` and `C_all` use the same bands with z_K at K_all.
- 0.0003 p.u. (busbar daily-mean floor, `docs/phase7_results.md:295`) is a labelled reference line only.
- **σ sensitivity:** recompute every band at σ_tot ∈ {0.003, 0.005, 0.02}.
  - The bias term holds the registered 0.98 ratio.
  - The contrast random arms are 0.2 · σ_tot (matched bias: 0.002 at σ_tot = 0.01) and σ_tot (`realistic`).
  - 0.003 comes from the literature (`docs/phase6_literature.md:50`) and is not a registered condition.
  - Report all four verdict pairs; the primary pair is at 0.01.
- **Illustration only** (n̄_day = 40, n̄_night = 56, D = 183, D_eff ≈ 174): level thresholds z₂F_ind ≈ 2.7e-4 and z₂F_bias = 0.0220 p.u.; contrast thresholds z₂F_C,matched ≈ 7.0e-5 and z₂F_C,realistic ≈ 3.5e-4 p.u. The binding numbers are the ones Stage 1 writes.
- **Relative sensitivity** (descriptive, same illustrative inputs): the level threshold divided by the contrast threshold is ≈ 312× within the matched-bias condition and ≈ 0.76× within `realistic`. So the contrast is far more sensitive under matched bias and slightly less sensitive under `realistic`.

## 6. Pre-stated predictions (Stage 1, recorded before Δ)
- **Magnitude** at buses downstream of the stressed line: ≈ 0.5 · R · P / V² p.u., where:
  - R = `r_ohm_per_km` · `length_km` of the stressed line;
  - P = downstream installed PV `sn_mva` × mean daylight availability of those generators;
  - V = 0.4 kV.
  - The busbar is predicted at ≈ 0.
- **Shape:** monotone in downstream PV × R, with the argmax downstream of the stressed line.
- **HYPOTHESIS:** the night residual has the opposite sign to the daylight residual.
- Any contradiction is reported as a contradiction, not reconciled.

## 7. Procedure: one script, run in order
1. **Stage 0.** Verify `outputs/robust_study/evaluation_results.json` sha256 `a70c0aed35f97d48eb1587c7f7e5b0eec995c4d7c523cccd6dcbef8afff802ef` and `outputs/robust_study/freeze.json` sha256 `d191bb5dd416b7b9d5ed306f6cb2b68bcbe170aef753ad2cbb96a2114ab762bc`.
   - Verify every entry of `freeze.json` `code_sha256` against the current file. There are 27 entries: the 24 `src/gridpulse/*.py` modules plus `pyproject.toml`, `uv.lock` and `docs/phase8_protocol.md`; this is the "27" of `docs/provenance/phase8/registration_log.txt:56`.
   - Exception: `src/gridpulse/__main__.py` and `src/gridpulse/demonstrator.py` must equal their latest hashes in that registration log. They carry the logged post-freeze, presentation-only change.
   - Report the counts. Stop on any other mismatch.
2. **Stage 1.** Compute the §5 inputs, all thresholds, the §6 predictions and the stressed-line facts, **without loading any `vm` array**. Write `analysis/phase9/results/registration_inputs.json` and print its SHA-256.
3. **Stage 2.** Only then load the `vm` legs and compute §4. Write `analysis/phase9/results/q1_results.json`, and refuse to overwrite an existing results file.
4. **Stage 3.** Repeat the Stage 0 checks.

## 8. Locations and invariants
- **Code:** `analysis/phase9/q1_voltage_residual.py`. **Tests:** `analysis/phase9/tests/`. **Results:** `analysis/phase9/results/` (small JSON).
- No change to `src/gridpulse/`, `outputs/`, `data/`, `.venv/` or `docs/provenance/` (except this registration, which the owner writes). No new dependencies, no power flows, no network-data writes.
- **Recorded from frozen output, not computed (L0 and L2):**
  - busbar `mean_v_hat` |Δ| ≤ 8.1e-05 p.u.;
  - oracle intervention steps 878 and 632, with action match ≤ 54.6 % and 49.5 %, and no threshold.
- The S(i) observability rank is dropped.

## 9. Interpretation map
- **Level and contrast both A or B:** do not pursue meter-voltage detection of this error class in Phase 9. The standing remedy hypothesis (a corrected asset record or thermal monitoring) stands (`docs/phase8_results.md:367,505`). Report σ_bias,req = M_meter / z₂ as the calibration needed.
- **Contrast C, level A or B:** a bias-invariant temporal signature exists that the level test cannot see. This would be a Phase 9 candidate for residual-pattern screening; it is not a detectability claim.
- **Level C:** the Phase 8 register entry (`docs/phase8_results.md:413`) needs amending. This holds for this best-case placement only.

## 10. Caveats carried in the claim
- Constant-power injections and no voltage-dependent loads.
- A stylised R/rating change with X unchanged.
- Balanced three-phase, no Q(U)/P(U), a single error location.
- No-cap level only, so the residual is lower under any curtailment.
- One best-case cable per network: Bands A and B generalise within a network; Band C does not.
- SimBench benchmark networks only, so this is not evidence about a real feeder.

## 11. Drafting record
Changes from the Paperclip draft (AKK-17 document `registration-draft`, revision 4a6da5b9), made while writing this file. No hypothesis, statistic, formula, band rule, scope or acceptance criterion changed.
- Filled in the registration date.
- Corrected the Stage 0 code-hash rule. As drafted, it would have failed on the two post-freeze, presentation-only modules recorded in the Phase 8 log, and it now states what the 27 frozen entries are.
- Aligned the illustrative thresholds and the relative-sensitivity figures with the registered D_eff, and added the illustrative contrast thresholds.
- Made explicit which contrast noise arms the σ sensitivity uses.

