# Phase 6 protocol: measurement integrity, noise-aware feedback and sensor value

**Status.** Registered before the Phase 6 development and evaluation stages. The SHA-256
of this file and the code are recorded in `docs/provenance/phase6/registration_log.txt`;
any later change is a dated amendment at the end.

**Experiment identity.**

- Phase 6 is a **CORRECTED** study (repaired measurement implementation) and an
  **exploratory replication**.
- The networks, profiles and periods are those of Phases 4 and 5. They have been examined
  extensively, so the evaluation half-year is **not** a pristine holdout. New noise
  realisations are not independent validation.
- **No confirmatory claim is made.**
- The **ORIGINAL** Phase 5 results stay frozen in `outputs/sense_study/` and
  `docs/phase5_results.md`, and the Phase 5 code path reproduces them exactly (s. 2).

## 1. Questions

**Primary.** Can measurement-aware, noise-robust feedback improve reliability while
controlling unnecessary curtailment, under limited observability and network-model
mismatch?

**Secondary.** Which additional measurements provide decision value once measurement
noise, false alarms and the cost of sensing are accounted for?

Negative results are reported as such.

## 2. What changed since Phase 5, and what is preserved

**Repaired defects** (found in the Phase 5 post-evaluation reviews):

1. **Noise identity.**
   - Phase 5 drew all noise from one random stream per run, seeded from the
     configuration's *name* (`sensing.seed_of`, which also collides).
   - Identical sensors therefore received different noise in different configurations.
     Even substation sensors shared by two configurations got different noise, because
     the stream was consumed in configuration order.
   - Phase 6 ties each reading's noise to the identity of the physical observation
     (`sensing.NoiseBank`): network, truth, replication, quantity, sensor element, day
     and quarter-hour.
   - The seeds come from SHA-256 of the identity parts through numpy's `SeedSequence`,
     so they are stable across processes.
   - Missingness is a uniform draw per (sensor, day), nested across missingness rates.
   - A meter's calibration bias (sensitivity condition only) is per device and constant.
   - The draws do not depend on the configuration, the other sensors, the applied caps,
     the alarm rule, the condition or which days are simulated. This gives common random
     numbers wherever runs share a sensor.
2. **Evaluation protection.**
   - New outputs go to `outputs/noise_study/`. Each stage writes a manifest at its start
     (status "running", identity, code and protocol hashes) and finishes it with the
     output hashes.
   - All outputs are written atomically.
   - A stage is refused if:
     - its manifest exists (complete or interrupted);
     - or its files exist without a manifest.
   - The evaluation is also refused unless:
     - a freeze record exists;
     - the code and protocol hashes equal it;
     - and the development outputs still verify (`runguard`).
3. **State-estimation diagnostics.** The estimator now also returns its weighted residual
   sum J = r'R⁻¹r and degrees of freedom (s. 6).

**Preserved.**

- Phase 5 outputs are untouched. The Phase 5 analysis path (`seed_of`, one stream per
  run) is kept unchanged.
- Before and after the repair, a re-run of the semiurb4 evaluation analysis matched the
  frozen Phase 5 results exactly: 504 of 504 decision runs, every detection summary and
  every placement.
- The physics caches are reused. They are bit-identical to Phase 4 (Phase 5 post-
  evaluation check).

## 3. Networks, periods, truths, information timing

**Networks, truths and periods.** As in Phase 5:

- six SimBench LV networks, rural1 for development and five new;
- truths: nominal, `tap_raise_lv`, `mv_high`, `pv_fixed_095`;
- development days 35–181, evaluation days 182–364 of 2016;
- a *cell* is (new network, truth); the *mismatch cells* are 5 × 3 = 15;
- requirement: at most 0.1 avoidable daylight violation quarter-hours per day.

**Information timing** (unchanged).

- Day-ahead caps are decided at 00:00 UTC from the nominal planning model and past
  metered injections.
- Substation readings of day d are available at the decision for day d + 1. Remote meter
  readings of day d arrive with the reporting delay (one day in the realistic
  condition).
- An alarm rule is applied to a sensor's complete daily batch once it is available. So
  persistence over consecutive quarter-hours of that day uses no future information
  relative to the decision it informs.
- The controller never reads ground truth.

**Warm-up.**

- The online margin starts at τ = 0 on day 35 in both stages. Evaluation records
  therefore come from a controller that has adapted for 147 days, and development records
  include the learning phase.
- Both halves are reported, and they are not pooled.

## 4. Measurement conditions

Substation busbar voltage σ = 0.002 p.u.; transformer and line current, P and Q σ = 1 %
of the reading (as Phase 5).

| Condition | Meter voltage noise σ (p.u.) | Missing sensor-days | Delay | Role |
|---|---|---|---|---|
| exact | 0 (substation also 0) | 0 | 0 | information value without noise |
| noisy | 0.01 | 0 | 0 | noise alone |
| noisy_missing | 0.01 | 5 % | 0 | noise + loss |
| noisy_delayed | 0.01 | 0 | 1 day | noise + delay |
| **realistic** (primary) | 0.01 | 5 % | 1 day | Phase 5 primary |
| sigma_0.005 | 0.005 | 5 % | 1 day | sensitivity |
| sigma_0.02 | 0.02 | 5 % | 1 day | sensitivity |
| biased_meters | 0.002 random + 0.005 per-meter bias | 5 % | 1 day | systematic error instead of random |

- **The sensitivity values bracket the Phase 5 assumption** by a factor of 2 each way.
- **σ = 0.01 p.u. agrees with practice.** It is consistent with the VDE FNN 2025
  requirement of 2 % voltage accuracy at the 99th percentile (σ ≈ 0.008–0.009 p.u.), and with
  a utility's ±1 % AMI voltage specification. Both sources are cited in
  `docs/phase6_literature.md`.
- **The bias condition represents meters whose error is mostly a fixed calibration
  offset.** Its total standard uncertainty is √(0.002² + 0.005²) = 0.0054 p.u.
- **None of these values was chosen to favour a method.** All were fixed before the
  development diagnostics.

## 5. Alarm rules, configurations, policies

**Alarm rules** (`sensing.AlarmRule`). Each is applied identically to every measured
quantity: busbar voltage, transformer and line loading, meter voltages.

| Rule | Definition | Basis |
|---|---|---|
| unfiltered | reading > limit (Phase 5) | baseline |
| guard2 | reading > limit + 2u, u = the reading's standard uncertainty | metrology guarded rejection with guard band w = U = 2u (JCGM 106:2012 s. 8.3; ILAC-G8:09/2019) |
| persist2 | exceedance counted only in runs of ≥ 2 consecutive quarter-hours per sensor | "n consecutive samples" on-delay alarm rule (Adnan, Izadi & Chen 2011); sensitivity |
| **persist3** (primary) | runs of ≥ 3 consecutive quarter-hours (45 min) | as persist2. Temporal aggregation before judging a limit is grid practice: EN 50160 10-min means; EN 50549-1 moving 10-min mean overvoltage protection |

**Choice of the primary rule** (from the development diagnostics; disclosed in s. 9).

- The criterion was formulated after seeing those diagnostics: the smallest persistence
  m ∈ {1, 2, 3} for which development false alarms under the nominal truth, with
  realistic readings, are at most β/3 per network-day (24.5 steps over 5 networks ×
  147 days) for both + 2 topology and full metering.
  - m = 1: 75 and 150 steps.
  - m = 2: 17 and 55 steps.
  - m = 3: 5 and 22 steps.
- The metrology guard band was not eligible as primary. On development days it
  suppressed most true voltage violations: their median overshoot is 0.001–0.014 p.u.,
  below its 0.02 p.u. guard.

**Configurations.**

- Substation (transformer device plus feeder-head currents).
- Substation plus k ∈ {1, 2, 4} meter voltages, placed by:
  - topology;
  - historical risk;
  - mandatory-like (largest PV first);
  - greedy detection;
  - decision-aware greedy;
  - random (20 seeds).
- Full: every bus voltage and every line current.
- **Placements** are designed by `sensing.design_placements` on development days only,
  exactly as in Phase 5, and stored in the development output. The evaluation uses them
  unchanged.

**Run plan** (`noise_study.run_plan`), with `replay_aci` (Phase 4/5 feedback with the
alarm rule).

- **Core configurations** (substation; + 1, 2, 4 topology; + 2 of each other rule;
  full): every condition × every rule.
- **Other placements, including the 20 random placements:** realistic condition,
  unfiltered and persist3 rules.
- **Noise replications 1–4** (beyond 0): realistic condition, unfiltered and persist3,
  for substation, + 2 topology, + 2 decision-aware and full.

**References.**

- `static_dev`, the development-tuned static cap (strong simple baseline).
- Full-information reference: full metering, exact readings, unfiltered.
- `oracle`: the true grid, unattainable, for interpreting the decision gap.

Every method uses the same days, truths, timing, action set and, for shared sensors, the
same noise.

## 6. State estimation (secondary)

**Sample.**

- As in Phase 5: every third scored day, 11:00–14:00 UTC, no action, realistic
  readings.
- Configurations: substation, and substation + 2 topology meters.
- WLS with forecast pseudo-measurements and explicit zero-injection buses; no current
  magnitudes (amendment 5A).

**Chi-square test.** J > χ²₁₋α(m − n), with α = 0.01. Here m counts the measurement
rows, including zero-injection rows, and n = 2N − 1 states.

**Gross error.** The estimate's largest voltage error exceeds 0.02 p.u., or its largest
line-loading error exceeds 20 percentage points.

**Gated detector.** A state-estimation alarm counts only if the chi-square test does not
reject the estimate. Detection recall and false alarms are reported for:

- direct detection;
- state estimation;
- gated state estimation.

**Not in this phase.** State-estimation-driven feedback decisions are not rerun: the
Phase 5 gate closed, and the test below is a prerequisite. A downstream decision effect
is reported only as detection-level change.

## 7. Hypotheses and decision rules

All hypotheses are evaluated in the **evaluation** stage, on the five new networks,
replication 0. Sums are over networks; "cells" are mismatch cells meeting the
requirement. P3 = persist3 with realistic readings; "exact" = unfiltered with exact
readings.

| ID | Statement | Decision rule |
|---|---|---|
| **H1** (cost; primary) | Noise-aware feedback removes the noise-induced excess curtailment under the correct model | For + 2 topology and for full: (C_unfiltered,realistic − C_P3) / (C_unfiltered,realistic − C_exact) ≥ 0.75, with C the nominal-truth curtailment. Met only if both hold |
| **H2** (reliability; primary) | It keeps the reliability that the sensors provide with exact readings | For + 2 topology and for full: cells_P3 ≥ cells_exact − 1 **and** mismatch-truth avoidable violations_P3 ≤ 1.25 × violations_exact |
| **H3** (sensor value) | With noise-aware feedback, two meters add reliability without adding cost | cells(+ 2 topology, P3) ≥ cells(substation, P3) + 3 **and** C(+ 2 topology, P3) ≤ 1.1 × C(substation, P3) (nominal truth) |
| **H4** (placement) | With matched noise, decision-aware placement beats topology placement | cells(+ 2 decision-aware, P3) > cells(+ 2 topology, P3) in ≥ 3 of 5 networks (ties are not wins; no curtailment tie-break) |
| **H5** (guard band; predicted) | The metrology guard band trades violations for curtailment | Mismatch-truth violations of guard2 ≥ 1.5 × those of P3 (+ 2 topology, realistic) |
| **H6** (bad-data test; predicted mixed) | The chi-square test detects the PV reactive-power model error but cannot certify estimates | (a) Under `pv_fixed_095`, it flags ≥ 90 % of successful substation estimates in every new network. (b) Under the nominal truth, it flags ≤ 5 % of non-gross estimates in ≥ 4 of 5 networks. (c) Under the nominal truth, it flags ≥ 90 % of gross estimates (pooled). Development predicts (a) met, (b) and (c) not met |

**Joint reading.**

- Noise-aware feedback is "supported" only if H1 **and** H2 are met.
- H3–H6 are secondary. Each is reported as met or not met, without re-weighting.

**Reported without a decision rule.**

- Per network and truth: violations, curtailment, false alarms, missed violations,
  interventions, excess curtailment over the oracle.
- The value curve over k = 0, 1, 2, 4 (all rules, random spread) and the marginal value
  of each sensor.
- Pareto views: violations vs curtailment vs number of sensors.
- The sensitivity, missingness, delay and bias conditions.
- Replication spread.
- The development stage.
- The static and oracle references.

## 8. Statistics

**Paired comparisons** (`noise_study.PAIRS`).

- Per network and truth: the mean daily difference in avoidable violations and in
  curtailed MWh.
- 95 % percentile interval from a circular 7-day block bootstrap (as Phases 4–5).

**Counts.**

- Counts of cells are reported with their per-cell margins, not as significance tests.
- The 15 cells share days, profiles and topologies. They are not independent
  replications.

**Noise replications 1–4.** They show how much a result depends on one noise
realisation. They are not independent data.

**No new tuning after this registration.** No threshold, rule or criterion is changed
after the evaluation; changes before it are amendments.

## 9. What was seen before registration (disclosure)

The development-only diagnostics were run on days 35–181 with the repaired noise and
read no evaluation day:
- `docs/provenance/phase6/scripts/development_diagnostics.py`;
- `docs/provenance/phase6/scripts/se_diagnostics.py`.

They showed:

- **True voltage violations are mostly smaller than the meter noise.**
  - Median overshoot at no action under the nominal truth: 0.001–0.0035 p.u.
    (70–94 % below 0.005 p.u.).
  - Under MV 1.055: 0.007–0.014 p.u.
  - Line overloads: median about 11 %.
- **Development figures for + 2 topology with realistic readings**, summed over the new
  networks: mismatch violations and nominal-truth curtailment.

  | Rule | Mismatch violations | Nominal-truth curtailment |
  |---|---|---|
  | exact | 1495 | 86.1 MWh |
  | unfiltered | 833 | 159.2 MWh |
  | persist3 | 1652 | 79.3 MWh |
  | guard2 | 5438 | 79.1 MWh |

- **Full metering:**

  | Rule | Mismatch violations | Nominal-truth curtailment |
  |---|---|---|
  | exact | 472 | 87.7 MWh |
  | unfiltered | 220 | 344.4 MWh |
  | persist3 | 376 | 100.9 MWh |

- **Development is in the controller's learning phase.** Few mismatch cells meet the
  requirement in any configuration (exact full: 1 of 15).
- **The chi-square test under `pv_fixed_095`** flagged 94.8–99.3 % of substation
  estimates in the new networks. Median J was 124–269, against 1.5–7.4 under the correct
  model, with 2–4 degrees of freedom.
- **The chi-square test under the nominal truth** flagged 1.6–38 % of non-gross
  substation estimates. It caught 11–100 % of the gross ones, by network.

The H1 and H2 criteria were formulated with these numbers known. They are reported as
replication tests on the evaluation half, not as independent confirmation.

**The criteria are not blind to the evaluation half.**

- The author knows the ORIGINAL Phase 5 evaluation results for the same days, for
  example two topology sensors with exact readings meeting 9 of 15 cells.
- The Phase 5 reproduction check also re-ran Phase 5's own analysis on semiurb4
  evaluation days, to confirm the frozen outputs.
- The Phase 6 code itself has read no evaluation day.

## 10. Procedure

1. Register this protocol (hash in the registration log).
2. Run the development stage:

   ```bash
   uv run python -m gridpulse noise-study --stage development --output-dir outputs/noise_study
   ```

3. Review it, then freeze the code and protocol hashes:

   ```bash
   uv run python -m gridpulse noise-study --stage freeze --output-dir outputs/noise_study
   ```

4. Run the evaluation stage once:

   ```bash
   uv run python -m gridpulse noise-study --stage evaluation --output-dir outputs/noise_study
   ```

5. Report every hypothesis, including those not met, per network and truth.
6. Run independent reviews afterwards. Corrections after the evaluation go to the
   documentation, with their dates. Frozen outputs are never edited.

---

## Amendment 6A (2026-10-18, before any freeze or evaluation)

**Why.** Two independent pre-evaluation reviews (code and leakage; methods, physics and
statistics) examined the registered protocol, the code and the exploratory development
diagnostics. Meanwhile a first registered development stage was run with the registered
code. It is archived unchanged as `development_v1`, and the reviews did not see its
outputs. Their findings, and the changes made here:

1. **H6 code did not implement the registered rule** (blocker).
   - The code pooled sub-rule (b) across networks and (c) across all truths, and never
     computed (a).
   - It is now implemented as registered: three separate sub-results, (a) per network,
     (b) at least 4 of 5 networks, (c) the nominal truth only. There is no single H6
     verdict.
   - A synthetic test covers all three parts.
2. **Persistence on substation readings only adds missed violations.**
   - Measurement noise causes almost no substation false alarms: 6 nominal-truth steps on
     development days.
   - Persistence there adds missed short overloads: +44 nominal-truth violations, and 3
     nominal cells lost.
   - The failure mechanism is meter-voltage noise.
   - **The primary rule is now `persist3_meters`:** persistence of 3 quarter-hours on
     meter voltages only; substation readings unfiltered (`AlarmRule.scope`).
   - `persist3` (all quantities) stays as a registered secondary rule.
   - The persistence length 3 is unchanged.
   - This change was prompted by development data.
3. **Nominal-truth reliability enters the joint reading.**
   - H1 scores only nominal-truth curtailment, and H2 only the mismatch truths. A rule
     could pass both by under-protecting under the correct model.
   - On development days `persist3` curtailed less than exact readings, while nominal
     violations rose from 143 to 186 (+ 2 topology).
   - New **H2b:** for + 2 topology and for full, the nominal cells meeting the requirement
     with the primary rule ≥ nominal cells with exact readings − 1. Nominal violations are
     reported next to H1.
   - **Noise-aware feedback is "supported" only if H1, H2 and H2b all hold for both
     configurations.**
   - This amendment works against the proposed rule. It was prompted by development data.
4. **H1 edge cases.**
   - If the pooled noise-induced excess (unfiltered realistic minus exact) is below
     10 MWh, H1 is *not evaluable*, not "not met".
   - A share above 1 means under-curtailment relative to exact readings, and is flagged
     (`under_curtails_exact`).
   - Shares are also reported per network.
5. **The noise structure favours persistence.**
   - Independent noise per reading is the case persistence can filter. Real meters
     average over 15 minutes and carry mostly systematic error.
   - New condition `biased_meters_matched`: random 0.002 plus a per-meter bias with
     σ = 0.0098 p.u. Its total uncertainty is 0.01 p.u., the same as `realistic`, so
     only the *structure* of the error changes.
   - It is replicated, like `realistic`, over noise replications 1–4: five bias draws
     per meter.
   - The earlier `biased_meters` condition (total 0.0054) is kept and labelled as
     changing both size and structure.
   - **Wording.** σ = 0.01 independent per reading is the pessimistic end of the plausible
     range. Persistence is a statistical filter for independent noise. The 10-min
     aggregation of EN 50160 and EN 50549-1 is already met by single 15-min averages, so
     those standards do not support requiring 45 min.
6. **Replications.**
   - H1–H4, H2b and the joint reading are also evaluated for noise replications 1–4.
     Replication 0 decides; disagreements are reported prominently.
   - The exact-reading references have no noise and are shared.
7. **Statistics.** Paired intervals are also given with 14- and 28-day blocks. τ carries
   memory over weeks, so these are descriptive. No multiplicity adjustment is made, and
   no interval is called significant.
8. **Warm-up.** Each run also reports τ on its first scored day and the violations and
   curtailment of its first 31 scored days.
9. **State estimation, wording and reporting.**
   - With substation readings the test has 2 degrees of freedom. The only redundancy is
     transformer P and Q against the summed injections, so J is in effect a feeder
     power-balance test.
   - It cannot see voltage offsets, and (a) measures the same signal as the reactive-power
     part of the model-consistency label.
   - pandapower gives zero-injection rows σ = 0.001, which makes the test conservative.
   - Reported in addition:
     - monthly flag rates;
     - gross errors at a decision-relevant threshold of 0.01 p.u. / 10 points;
     - the substation H3 comparison against unfiltered feedback;
     - H4 together with its curtailment difference;
     - the three-way comparison exact unfiltered / exact primary / realistic primary;
     - per-network H2 ratios, and the ratio without semiurb4.
10. **Run protection.**
    - Stage start is exclusive.
    - The freeze is refused unless code, dependency pins (`pyproject.toml`, `uv.lock`)
      and protocol equal those that produced the development outputs.
    - The evaluation also checks the development output hashes stored in the freeze.
11. **Disclosures.**
    - H3's "+3" and H4's "3 of 5" sit just under the known ORIGINAL Phase 5
      exact-reading results (+5; 3 networks).
    - In rural2, decision-aware and topology placements are the same sensors, so with
      common random numbers H4 is a guaranteed tie there.
    - `persist3` was chosen by a false-alarm-only criterion with thin slack (full: 22
      against 24.5) that ignored missed violations.
    - The H2 margin on development is thin: 1.20 without semiurb4. Per network it is
      1.63 in semiurb5 and 1.57 in urban6.

**Procedure.**

- Because the code changed, the development stage is run again in the same output
  directory.
- The first run's files (manifest, results, hypotheses, metadata) are moved, unmodified,
  to `outputs/noise_study/development_v1/`.
- The freeze then binds the evaluation to the code that produced the second development
  run.
