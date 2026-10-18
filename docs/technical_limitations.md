# Technical limitations

These are the limits of what GridPulse currently shows, grouped by origin. Experiment-
specific limits are repeated next to the results in `docs/experiment_results.md`.

## Data

- **Track 1** uses one national series (OPSD 2020-10-06, German load, 2015–2019). It is a
  retrospective 2020 snapshot, not the data as known in real time. Publication delays and
  revisions are ignored.
- **2019 is not a clean test year.** It was inspected in Phases 1A–2A, so Track 1
  evaluations on 2019 are not confirmatory. 2020 remains reserved and unused.
- **Track 2** uses SimBench benchmark profiles for 2016: 15-minute, synthetic or
  benchmark-generated, and not measurements of a real feeder. The forecast errors in
  Track 2 are therefore errors of a naive forecaster on benchmark profiles. Their size and
  structure drive the risk and calibration findings.
- **SimBench's storage time series are one-signed.** In pandapower's convention they
  would discharge at the PV peak and never charge, and their intended semantics could not
  be verified. All storage is therefore held at 0 MW: Track 2 studies "PV and load without
  battery dispatch", not the benchmark as published.
  - This choice is consequential: read as charging, the storage would remove most
    violations. The development-only sensitivity run quantifies this
    (`development_storage_sensitivity.json`).
- **Transformer tap (fixed).** simbench 1.6.3 with pandapower 3.5.6 silently ignored the
  benchmark's +1 HV transformer tap. `grid.load_network` now makes it effective, and a test
  checks the no-load LV voltage of 1.000 p.u. Development results from before the fix are
  kept in `outputs/grid_study_pre_tap_fix/` to quantify the defect.
- **SimBench's `time` column is German local time with daylight saving.** It is converted
  to UTC. The last UTC day (2016-12-31) is incomplete, so the evaluation ends on
  2016-12-30.

## Physical model (Track 2)

- **Network.** A single balanced (positive-sequence) AC model of one 15-bus LV feeder with
  its 20/0.4 kV transformer. There is no phase unbalance, no protection, and no
  transformer-tap or reactive-power control.
- **Limits** are the benchmark's own. The 0.9–1.1 p.u. LV band is an operational band, wider
  than DSO connection-planning rules (for example a 3 % PV voltage-rise budget, which the
  3–4 % PV-induced rise here would exceed).
  - The slack voltage is fixed at 1.025 p.u., which understates real MV voltage swings.
  - Voltage margins are computed over LV buses only.
- **Intervention.** One action: a uniform PV feed-in cap on all 8 PV systems. Curtailed
  energy is lost, not shifted. A real DSO curtailment scheme acts per installation, with
  communication delays and contractual rules.
- **70 % rule.** The static 70 % cap is a regulatory reference only.
  - It applied to systems of 30 kWp or less, and here it is applied to PV output rather
    than net feed-in.
  - The larger units in this grid would have fallen under remote-controlled curtailment
    instead.
  - Because the benchmark PV output peaks at about 60 % of rating, the 70 % cap never
    binds in this grid.
- **Loading is non-monotone in the cap.** Deep caps can increase transformer loading by
  turning reverse flow into forward flow. The decision rules evaluate every cap level and
  do not assume monotonicity.
- **Time resolution.** Quarter-hour mean powers. Sub-15-minute peaks and thermal time
  constants are not modelled; a limit exceeded for one quarter-hour counts as a
  violation.
- **Solver.** Simulated violations are not observed outages. A non-converged power flow
  is recorded as a failure with no valid physical state, never as safe. Severity sums
  ignore non-converged steps; none occurred.

## Statistics and evaluation

- **Unit of independence.** The day. Days within a season are themselves correlated; the
  7-day block bootstrap reduces but does not eliminate this.
- **No guarantees under shift.** Risk estimates are scenario frequencies under a stated
  scenario model. They are not certified probabilities. Conformal-style intervals carry
  no guarantee under temporal dependence and shift.
- **Small rare-event groups.** Holiday groups (8 dates per year) and deferred days are
  small, so their estimates are descriptive.
- **One year, one grid.** Both tracks rest on a single year of the relevant data and, in
  Track 2, on one network. No claim of external validity is made.

## Methodology and claims

- **Novelty.** Only moderately evidenced. The literature review was focused, not
  systematic (`docs/literature_review.md`).
- **No real-world validation.** No grid operator, field data or expert review has
  validated the decision rules or thresholds.
- **Deferral.** Deferral is evaluated as a workflow outcome with explicit fallback
  policies. It is never taken as evidence that a violation was prevented.

## Licensing and redistribution

- **OPSD reuse terms are unresolved** (see README).
- **SimBench data are licensed ODbL 1.0 / DbCL**, with share-alike obligations for
  derived databases.
- Neither raw data nor derived outputs (predictions, physics caches, trained models) are
  committed or redistributed. `data/` and `outputs/` are git-ignored.
- No licence has been chosen for this repository.

## Phase 4 (dual uncertainty)

- **Five of six networks are stress cases.** In their own 2034 scenario they have no
  violations.
  - Their PV is scaled, by a rule fixed before any policy ran, to the same multiple of
    their hosting capacity as rural1.
  - They are not forecasts of real PV growth.
  - Storage is not scaled with PV, so storage effects are diluted in them.
- **One synthetic year for everything.**
  - The new networks share PV and load profiles with rural1. Daily PV energy correlates
    0.72–0.82 between rural1's profiles and those of rural2 and rural3, and 0.92–0.94 for
    PV2, used in semiurb5 and urban6. Each new network shares 7–10 of its 20–23 load
    profiles with rural1.
  - The second half of 2016 is therefore only partly new information, and the results
    are semi-confirmatory.
- **The model variants are a short list, fixed for the whole year:** tap ±1, MV
  1.055 p.u., two PV reactive-power settings, two readings of home-storage behaviour, and
  two joints.
  - Real model errors drift and combine.
  - On networks already tapped to −1, `mv_high` and `tap_raise_lv` are stress brackets
    (zero-PV LV voltage near 1.08 p.u.).
  - `pv_cosphi_p` is nearly inert, because PV never exceeds about 0.63 of rating.
- **Storage readings are unresolved.** Neither the greedy relocation nor the "series read
  as charging" interpretation is the benchmark's verified intent.
  - Storage schedules ignore the cap, so at deep caps scheduled charging draws from the
    grid. This can make deeper curtailment worse. It is kept as a real non-monotonicity of
    that truth.
- **Online calibration needs measurements.** It assumes every limit is measured every
  quarter-hour on the real grid, which is rare in LV grids today.
  - Its guarantee is a long-run *average* that is vacuous over half a year here, and it
    is lost when τ sits at its upper bound.
- **The ensemble rule is exact only with perfect information.** With forecasts it uses an
  additive margin shift taken from the forecast set, not a full scenario × model product.
- **The normalised margin mixes units by convention:** 0.1 p.u. of voltage counts as much
  as 100 % of loading.
- **Statistical resolution.** Evaluation violations cluster in July–September, and day
  blocks are dependent.
  - Violation-count intervals have little power; curtailment intervals have much more.
  - Many cells share the same days, so counts across cells are not independent
    replications.
- **Observation.** The online policies are scored as if every bus voltage and branch
  current were measured every quarter-hour.
  - Here the binding voltage is at the most remote PV bus and the binding line is a single
    mid-feeder cable segment.
  - Substation metering would see only transformer overloads.
- **No inverter protection.** Inverters disconnecting above 1.10 p.u. (VDE-AR-N 4105) are
  not modelled, so the 1.11–1.124 p.u. exceedances would be PV trips in reality.
- **A uniform cap is unfavourable to model-based rules.** One cap applies to every PV unit,
  so model-based rules cannot choose where to curtail. In the line- and voltage-limited
  networks, 53–75 % of the PV is downstream of the binding line.
- **The static cap is favoured by design.**
  - The stress rule (1.40× hosting capacity) places the safe static cap near 0.4 in every
    new network.
  - Tuning on a half-year that contains the annual PV peak makes it conservative for the
    evaluation half.
- **Fewer distinct truths than listed.** `pv_cosphi_p` and `storage_greedy` behave almost
  like nominal, and `joint_realistic` almost like `mv_high`, so the nine variant truths
  amount to about five distinct perturbations.

## Phase 5 (limited observability)

- **Exploratory replication, not confirmation.**
  - Networks, profiles and periods are those of Phase 4.
  - The protocol was registered before any Phase 5 development or evaluation run. The
    full-state physics, which depends on no Phase 5 choice, started 38 minutes earlier.
  - The registered criteria protect against tuning. They do not make the data new.
- **Idealised measurement model.**
  - Noise is Gaussian and independent across buses and quarter-hours. There is no bias,
    drift, quantisation, clock error or averaging-window mismatch.
  - A smart-meter voltage reading is the simulated quarter-hour voltage plus noise. Real
    meters' averaging, recording and phase conventions vary and are not modelled.
  - Missingness is independent per sensor-day, and the remote delay is a fixed one day.
- **A count-based feedback rule is sensitive to measurement noise.**
  - The margin update counts readings above the limit. Noisy readings near the limit
    therefore raise the margin even when no real violation occurs.
  - This noise interaction decides the primary verdict: two sensors meet the target in 14
    of 15 cells with noise and in 9 with exact readings. No noise-aware rule (guard band,
    persistence, interval test) was registered or tested.
- **Model-consistency label (MODEL_INCONSISTENCY).** It assumes exact metered injections
  and a constant MV voltage. Its 0 % false-flag rate under the correct model is an upper
  bound on real performance.
- **State estimation.**
  - Current magnitudes are excluded as estimator inputs (amendment 5A), because they made
    the Newton iterations diverge.
  - Pseudo-measurements come from a naive 7-day-mean forecast with error σ estimated from
    the past 28 days.
  - Topology and line parameters are assumed correct even when the true model differs in
    tap, MV voltage or PV reactive power.
  - It was evaluated on a sample (every third day, 11:00–14:00 UTC) and is not part of the
    evaluated decisions, because its gate closed.
- **Placement.**
  - Rules are designed on development days. The decision-aware rule also uses two
    mismatch truths on those days.
  - Candidates are customer buses only. Current sensors on mid-feeder cables were not
    candidates, although they are what the cable-limited network (semiurb4) needs.
- **Evidence labels.**
  - INSUFFICIENT_EVIDENCE is configuration-level, from development coverage under the
    nominal model, so it cannot anticipate violations that only a model error creates.
    Its perfect record (79 of 79 failed) comes almost entirely from one network
    (semiurb4).
  - NO_FEASIBLE_ACTION fired in rural3 only when noise-driven alarms had pushed τ to its
    bound. It is evaluated over all 96 steps, night included.
- **Counts of cells are not independent replications.** The 15 mismatch cells share days,
  profiles and, within a network, topology.
- **The primary result is period-dependent.**
  - The online margin starts at zero on the first decision day and learns during the
    development half.
  - P held in the evaluation half (4 / 14 / 15 cells) but not in the development half
    (0 / 4 / 6).
- **Noise seeds come from configuration names, not sensor sets** (no common random
  numbers), and `seed_of` collides.
  - Identical sensor sets therefore differ by noise. This decides the S3 tie-breaks.
  - The frozen code was not changed after the run.
- **No bad-data test in state estimation.** Under the PV reactive-power truth the
  estimator converges to grossly wrong states, for example 1.20 p.u. against a true
  1.055.
- **The evaluation guard checks output file names only.** A different output directory or
  deleted outputs would get around it.

## Phase 6 (measurement integrity, noise-aware feedback)

- **Replication, not confirmation.**
  - Same networks, profiles and periods as Phases 4–5. The author knew the ORIGINAL
    Phase 5 evaluation results when setting the criteria.
  - The primary rule and several criteria were set or amended after development data
    (disclosed in protocol s. 9 and amendment 6A).
- **Noise model.**
  - The realistic condition puts the meter error into independent per-reading noise
    (σ 0.01 p.u.). That is the pessimistic end of the plausible range, and the case
    that persistence can filter.
  - Real meters average over minutes and can carry substantial systematic error
    (calibration offsets; JCGM 100, and AMI data-quality studies such as Blakely et al.
    2019). The bias conditions show that outcomes then depend on the individual meters'
    offsets.
  - No meter model (averaging window, quantisation, clock error) is simulated.
- **The persistence rule is not a reliability mechanism.**
  - With exact readings it misses most closed-loop violations, which are shorter than
    45 min.
  - Its mismatch reliability under noise depends on the noise level.
  - A rule fed by a continuous, noise-unbiased statistic was not tested.
- **The chi-square test** checks a feeder's power balance. It is not calibrated under the
  correct model, it is blind to voltage offsets, and in winter it is weak against
  reactive-power errors. It cannot certify a state estimate.
- **Statistics.**
  - One noise path per paired interval; 5 networks; the 15 cells share days and
    profiles.
  - Noise replications 1–4 vary only the noise, not the data.
  - Nothing is a significance test.
- **Run protection is local.**
  - `runguard` protects against accidents in one output directory.
  - It cannot stop a deliberate rerun in another directory, and it is not a
    tamper-proof record. The outputs and the provenance folder are not under version
    control until the user commits them.

## Phase 7 (continuous margins, model-residual correction)

- **Exploratory replication, not confirmation.**
  - Same networks, profiles and periods as Phases 4–6. The decision rules were set after
    a development probe, with the Phase 5/6 results known (protocol s. 11).
  - The registered primary hypothesis H1 was not met (cost). H2, H4 and H5 pass by
    construction.
- **The method is not new.** It is the offset-free MPC / DMC bias update (Muske &
  Badgwell 2002; Pannocchia & Rawlings 2003) applied to day-ahead PV caps, with a fixed
  back-off.
- **Model errors tested.**
  - Only three constant errors were tested: tap, MV level and PV at fixed cos φ. All
    raise voltage or loading.
  - Not tested:
    - negative offsets;
    - a reversed reactive-power error;
    - MV voltage varying within the day;
    - local errors (one inverter, one cable, phase imbalance);
    - voltage-dependent loads;
    - inverter Q(U), P(U) and the apparent-power limit.
  - The substation is expected to correct only errors common to the feeder (argued, not
    tested: no local error was simulated).
- **Injection data are assumed exact.**
  - The residual is the reading minus the nominal model at the metered customer
    injections, so any systematic injection error passes into ρ one-for-one.
  - Delay was tested (C1lag); error was not.
  - The binary policies' feedback signal has no such dependence.
- **The busbar measurement is trusted.**
  - The tolerated busbar bias is about the safety margin (0.002–0.004 p.u.).
  - At ±0.005 p.u. the labels flip on about half the correct-model days.
  - No outcome exists for a biased reference.
- **The safety margin is one normalised number.** It acts as a loading margin under the
  correct model and as a voltage margin under tap and MV errors. It was tuned on the
  spring half, where loading binds.
- **The correction can over-correct.**
  - The daylight median of the current ratio over-corrects a PV-loaded cable (semiurb4:
    ρ_line 0.195, 22.2 against the oracle's 8.8 MWh).
  - The `max` rule for checked meters passes positive meter noise and accepted positive
    biases upward.
- **The labels are operational definitions.**
  - "Evidence sufficient" means only small substation residuals.
  - The split between "meter bias suspected" and "cannot tell bias from model error"
    follows from the label definitions and the simulated truths. It does not identify a
    bias.
- **Statistics.**
  - 5 networks; the 15 cells share days and profiles. Noise replications vary only the
    noise.
  - 28-day blocks give about 6.5 blocks per half-year, so those intervals are unstable.
  - The seasonal explanation of the H1 cost is consistent with the data but untested.
- **Post-evaluation code changes.** The code changed after the single evaluation (a
  demonstrator hook and review fixes). The replay evidence shows no result changed, but
  the frozen evaluation cannot be re-run under its freeze.
- **The demonstrator is exploratory.**
  - It shows ground truth for evaluation only.
  - It picks a day and a quarter-hour by a fixed rule on the no-action state.
  - It is not an operator interface or a safety assessment.
