# Phase 5 protocol: decisions under limited measurement availability

**Registration.** This protocol was written on 2026-10-18 and fixes the questions,
definitions and decision criteria of Phase 5.

**What had been seen before writing it:**

- the Phase 4 results;
- the literature review (`docs/phase5_literature.md`);
- exploratory checks on development days only:
  - a rural1 development run of the analysis code;
  - a state-estimation trial on six rural2 development days.

No Phase 5 evaluation-period result had been computed or seen. Later changes are recorded
as dated amendments at the end. Hashes of this file and of the code are written into
every run's metadata and into `docs/provenance/phase5/`.

## 0. Status of the data

Phase 5 reuses the six SimBench LV networks, the PV stress rule, the model variants and
the 2016 profiles of Phase 4. None of them is pristine:

- **Phase 4 already evaluated these networks on 2016-07-01 – 12-30**, and its results
  shaped the Phase 5 question.
- **The evaluation half-year is therefore not an unseen holdout.**
  - Phase 5 evaluation results are an **exploratory replication under pre-registered
    criteria**. The criteria protect against tuning; they do not make the data new.
  - No independent dataset was available. Changing seeds would not create one.
- **rural1 stays the development network.** Its results are reported but never counted.

## 1. Question and hypotheses

**Primary question.** Phase 4 found that measured feedback keeps a curtailment policy near
its violation target under physical-model mismatch. That finding assumed every bus voltage
and line current was measured. How much of that benefit remains with realistic
distribution telemetry? And which additional measurements recover it?

The realistic telemetry studied is:

- transformer and feeder-head measurements at the secondary substation;
- k ∈ {0, 1, 2, 4} smart-meter voltage readings, with noise, loss and next-day delivery.

**Primary hypothesis P: feedback reliability requires observing the binding constraint.**

- C(x) is the number of (new network × mismatch truth) cells, out of 5 × 3 = 15, in which
  `replay_aci` with telemetry x meets the requirement under the primary (realistic)
  measurement condition.
- (a) C(substation) ≤ C(full) − 3: substation telemetry loses at least three cells.
- (b) C(substation + 2 topology sensors) ≥ C(full) − 1: two remote voltage sensors placed
  by the topology rule recover all but at most one.
- *Supported* if (a) and (b) hold. *Refuted* if (a) fails, because substation telemetry
  already suffices, or if (b) fails, because two sensors do not recover.
- *Physics-based expectation, not a criterion.* Voltage sensors cannot see an overload of
  a mid-feeder cable, so (b) may fail where such overloads bind.

**Secondary hypotheses** (each reported per network):

- **S1, detection gap.** Recall of avoidable violations by direct substation detection is
  below 0.5 for voltage violations in every new network where they occur. Steps: no
  action, daylight, evaluation days.
- **S2, value of sensors.** The curve C(substation + k topology sensors), k = 0, 1, 2, 4,
  is non-decreasing. The first sensor recovers at least half of the k = 4 gain
  (diminishing returns).
- **S3, decision-aware placement.** At k = 2, decision-aware greedy placement is "better"
  than a rival rule in a network if:
  - it meets the requirement in more of that network's 3 mismatch cells; or
  - it meets it in as many cells and curtails less in total.

  It is better overall if this holds in ≥ 3 of 5 networks. The rivals are topology,
  historical risk and mandatory-like placement. *Prediction:* not better than the simple
  rules.
- **S4, state estimation.**
  - The question is whether WLS state estimation can compensate for missing remote
    sensors. Its inputs are substation readings plus forecast pseudo-measurements.
  - Gate (development sample): see s. 7.4.
  - If the gate opens, C(substation with state-estimation feedback) is compared with
    C(substation) and C(substation + 2 topology sensors).
- **S5, model-consistency label.** It is flagged on:
  - ≥ 90 % of days under the tap and MV-voltage truths;
  - ≥ 50 % of days under the PV reactive-power truth;
  - ≤ 5 % of days under the nominal truth.

  These are idealised: s. 8 explains why.
- **S6, insufficiency label.** Configurations labelled INSUFFICIENT_EVIDENCE fail the
  requirement under at least one mismatch truth more often than configurations labelled
  sufficient. This is shown as a 2 × 2 table over (network, configuration).
- **S7, measurement realism.** For each diagnostic configuration (s. 5),
  |C(realistic) − C(ideal)| ≤ 1. The effects of noise, loss, delay and more precise meters
  are reported separately.

**D, descriptive.**

- the "export proxy" rule (s. 6);
- the spread over 20 random placements;
- estimation errors.

## 2. Networks, truths and decision problem

**Networks, PV stress rule and decision problem: as in Phase 4.**

- day-ahead uniform PV caps per quarter-hour from {1.0, 0.9, …, 0};
- planning by the nominal model;
- protocol s. 4 of `docs/research_protocol.md`.

**Truths.** The truths cover the three mismatch types named for Phase 5. All are Phase 4
variants.

| Truth | What differs from the planning model |
|---|---|
| `nominal` | Nothing |
| `tap_raise_lv` | Transformer tap −1, so LV voltage +2.5 % |
| `mv_high` | MV voltage 1.055 p.u. |
| `pv_fixed_095` | PV at fixed cos φ 0.95, underexcited |

On networks already tapped to −1, `tap_raise_lv` and `mv_high` are stress brackets
(amendment 4B of the Phase 4 protocol).

**Periods.**

- Development: decision days 35–181 (2016-02-05 – 06-30).
- Evaluation: days 182–364 (2016-07-01 – 12-30).
- The requirement is β = 0.1 avoidable daylight violation quarter-hours per day, as in
  Phase 4.

**Physics.**

- A new full-state stage (`fullstate`, fingerprint `6898a6b3…`) re-solves the realised
  injections of every decision day at every cap level under each truth.
- It keeps every LV bus voltage, every line loading, and the transformer's LV-side P, Q,
  loading and voltage.
- Its worst-case margins are checked bit for bit against the Phase 4 cache.

## 3. Information separation and timing

**Ground truth.** The full state of the true grid. It is read only by the measurement
simulator (`sensing.measure`) and by scoring (`true_events`, `score`).

**Observations.** Readings of a configuration's sensors at the caps that were applied, with
noise, missing sensor-days and delivery delay (s. 5).

**Estimates.** WLS state estimates from observations plus pseudo-measurements (s. 7).

**Predictions.** The Phase 4 planning information: the nominal model, the replay of the
past 28 days' measured injections, and forecasts.

- Historical per-customer injections are assumed available the next day (smart-meter
  energy data). This assumption is shared by every configuration. Phase 5 varies only the
  operational telemetry.

**Decision timing.**

- The schedule for day d is fixed at 00:00 UTC of day d.
- Substation readings of day d−1 are available at that time.
- Smart-meter readings of day d−1−L are available at that time, with L = 1 (delivered the
  next day) in the realistic condition.
- Online correction after day d counts each daylight quarter-hour once:
  - steps flagged by substation sensors on day d;
  - steps flagged only by remote sensors on day d − L.
- No reading of day d informs day d's schedule.
- `sensing.decision_timing` records `decision_timestamp`, `forecast_origin`, the latest
  substation and remote measurement timestamps, `measurement_age` and the action-effective
  timestamps. Tests check them.

## 4. Sensor placement (development data only)

**Candidates.** Customer buses (with a load or PV): potential smart-meter locations. The
budgets are k ∈ {1, 2, 4} remote voltage sensors added to the substation configuration.

**Rules.** All are nested in k and deterministic. Every rule uses the development days of
the nominal model, except where stated.

1. **Random:** 20 fixed seeds.
2. **Mandatory-like:** largest installed PV first. This follows German smart-meter rollout
   practice (FNN 2025) and uses only the asset register.
3. **Topology:** feeder ends first. Take the electrically farthest customer bus of each
   feeder by resistance distance from the LV busbar, feeders in order of that distance,
   then round robin.
4. **Historical risk:** most development overvoltage steps at no action (nominal model).
5. **Greedy detection:** greedily maximise development true positives of direct detection
   (nominal model, ideal readings).
6. **Decision-aware greedy:** greedily minimise the development decision loss of
   `replay_aci` with that telemetry.
   - The loss is lexicographic, (Σ excess violations per day above β, Σ curtailment).
     There is no conversion between units.
   - It is averaged over the design truths {nominal, `tap_raise_lv`, `pv_fixed_095`},
     using ideal readings.
   - `mv_high` is withheld from the design, so it is an out-of-design truth in
     evaluation.

No evaluation-day information enters any placement.

## 5. Measurement configurations and model

| Configuration | Readings (units) |
|---|---|
| `none` | None |
| `transformer` | One device at the transformer's LV terminals: busbar voltage (p.u.), loading (% of rating, current-based), P (MW) and Q (MVAr), positive into the transformer |
| `substation` | `transformer` + current of every feeder-head cable (% of rating) |
| `substation+k:rule` | `substation` + k remote bus voltages (p.u.) |
| `substation_proxy` | `substation`, plus a model-based inference rule (s. 6) |
| `full` | Every LV bus voltage, every line current and the transformer device. Upper-information reference only, not typical telemetry |

**Measurement conditions.**

| Condition | Substation V σ | Substation I/P/Q σ | Remote V σ | Lost remote sensor-days | Remote delay |
|---|---|---|---|---|---|
| `realistic` (primary) | 0.2 % | 1 % of reading | 1 % (0.01 p.u.) | 5 %, i.i.d. whole days | 1 day |
| `ideal` | 0 | 0 | 0 | 0 | 0 |
| `noise_only` | as realistic | as realistic | as realistic | 0 | 0 |
| `missing_only` | 0 | 0 | 0 | 5 % | 0 |
| `delay_only` | 0 | 0 | 0 | 0 | 1 day |
| `precise_meters` | as realistic | as realistic | 0.2 % | 5 % | 1 day |

- **Sources** are in `docs/phase5_literature.md`.
  - Substation and current accuracies: de Jongh et al. 2025; FNN/Consentec 2024.
  - Smart-meter voltage accuracy: assumptions in the literature range from 0.5 % (3σ) to
    2 %, and no standard was verified. Hence `precise_meters`.
  - Next-day delivery: German metering law, MsbG §60(3).
  - Loss rate: low confidence (2.7–9.4 %/yr in a secondary source).
- **Noise** is Gaussian, independent per reading, and generated with seeds fixed by the run
  identity (network, truth, condition, configuration).
- **Reporting interval:** 15 minutes.
- **Units are never mixed.** Voltage limits are compared in p.u. and current limits in % of
  rating.
- **These are synthetic accuracies.** They are not the accuracies of any utility's
  devices.
- **Diagnostic configurations** (S7) are `transformer`, `substation`,
  `substation+2:topology`, `substation+2:decision_aware` and `full`. They run under every
  condition. All other configurations run under `realistic` only.

## 6. Detection study (current-state detection, not forecasting)

**Events.** An event is an avoidable true violation (Phase 4 definition: some cap is safe at
that step) at no action, on a daylight quarter-hour. Events are attributed to voltage,
line and transformer.

**Direct detection.** A step is flagged if any reading exceeds its own limit: voltage above
the bus's `max_vm_pu`, or loading above 100 %. No inference.

**Export proxy (model-based inference, labelled as such).**

- A step is also flagged if the measured transformer reverse flow exceeds p\*.
- p\* is the smallest reverse flow at which the nominal model shows an avoidable violation
  on a development daylight step at no action.

**Metrics** per network × truth × configuration:

- TP, FP, FN, TN, precision, recall and false-alarm rate;
- missed-violation rate;
- recall by type, with 95 % circular 7-day block-bootstrap intervals for recall.

No pooling across networks.

## 7. State estimation

1. **Estimator.** pandapower WLS (v3.5.6), unchanged, on the nominal model.
   - Zero-injection buses are passed explicitly: junction buses with no load, PV, storage
     or external grid. pandapower's `"no_inj_bus"` mode fails on these networks.
2. **Observability.** pandapower only compares the number of measurements with the number
   of states.
   - Phase 5 adds a numerical test: the rank of the measurement Jacobian at a flat start,
     with current-magnitude rows excluded.
   - A non-observable set is refused and never estimated. It is never filled from ground
     truth.
3. **Pseudo-measurements.** Customer-bus P and Q from the day-ahead forecast (7-day mean).
   - Their standard deviation is the forecast-error standard deviation of the same bus and
     quarter-hour over the past 28 days (floor 0.0005 MW).
   - When a cap applies, forecast PV is limited to cap × rating.
   - The literature uses 20–50 % or more; the data-driven value is used instead and both
     are reported.
4. **Sample.** Every third day (day % 3 = 0) of the stage; steps 44–56 (11:00–14:00 UTC);
   no action.
   - Configurations: `substation` and `substation+2:topology`.
   - All four truths, with realistic readings.
   - **Reported:**
     - observability without pseudo-measurements (rank) and with them;
     - estimator success;
     - voltage RMSE and the 95th percentile of the maximum absolute error;
     - the error at the truly highest bus;
     - detection by the estimate (any estimated voltage or line loading above its limit,
       or a measured transformer overload) versus direct detection on the same readings.
     - A failed estimate raises no alarm.
5. **Gate for decisions (S4).** Using the development sample:
   - Condition per network (configuration `substation`, all truths pooled):
     - state estimation raises voltage-event recall by ≥ 0.2 over direct detection;
     - its false-alarm rate is at most 0.05 higher.
   - Only networks with ≥ 10 voltage events count.
   - The gate opens if the condition holds in ≥ 3 new networks. The gate result is
     written by the development stage, and the evaluation stage only reads it.
   - **If the gate opens, the evaluation stage runs `replay_aci` whose feedback adds
     state-estimation inference:**
     - substation readings only;
     - estimation on steps with measured reverse flow and no direct alarm;
     - pseudo PV limited by the applied cap.

## 8. Evidence labels

These are research labels, not certified safety conclusions.

- **NO_FEASIBLE_ACTION:** for the day's schedule, some quarter-hour has no cap level that
  satisfies the margin rule. The rule then falls back to cap 0.
- **MODEL_INCONSISTENCY:** known at the decision time, from the previous day's readings.
  It is flagged if either:
  - |mean busbar-voltage residual| > 0.005 p.u.; or
  - |daylight-mean transformer-Q residual| / rating > 0.02.

  The residuals are the readings minus the nominal model at the same caps and the metered
  injections. The thresholds are fixed by physics (one tap step is about 0.025 p.u.), not
  tuned.
  - **Idealised in two ways.** The metered injections are exact, and the simulated MV
    voltage has no daily variation. So S5 is an upper bound on detectability.
- **INSUFFICIENT_EVIDENCE (configuration level):** development recall of direct detection
  (nominal truth, realistic readings) below 0.8. The configuration cannot confirm
  compliance.
- **SUFFICIENT_EVIDENCE:** none of the above.

**Fallback.** The policy keeps running and the labels are advisory. What a label would
imply, for example escalation with full curtailment until engineering review, is reported
as a cost. It is never counted as prevented violations.

## 9. Decisions and statistics

**Policies.**

- `replay_aci` for every configuration;
- `static_aci` for `transformer`, `substation`, `substation_proxy` and `full`;
- open-loop references: `static_dev`, `replay_robust` and `oracle` (unattainable).

All use the Phase 4 online settings (β = 0.1, γ = 0.01, τ ∈ [−0.1, 0.4], level step 0.03).

**Reported per run:**

- avoidable and total violation quarter-hours, severity, severe steps and runs of 1 hour
  or more;
- curtailed MWh, and "unneeded" curtailment (on days whose no-action state had no
  avoidable violation);
- observed feedback;
- days with each label.

**Paired comparisons.** Per-day differences of `replay_aci` between telemetry options, for
avoidable violations and curtailment, with 95 % circular 7-day block-bootstrap intervals
(2,000 resamples, seed 42):

- `substation` − `full`;
- substation + 1/2/4 topology sensors − `substation`;
- decision-aware − topology, and risk − topology, at k = 2;
- proxy − `substation`;
- state-estimation feedback − `substation`, and − substation + 2 topology sensors.

**How results are counted and reported.**

- Counts are per network.
- Cells share days and weather, so counts are not independent replications.
- No result is pooled into a single favourable aggregate.

**Runtime** (approximate, on a shared 11-core laptop at low priority):

- full-state physics: about 1.5 h;
- each stage's decision runs: minutes per network;
- state-estimation study: about 30 min per stage;
- state-estimation feedback, if gated: about 1–3 h.

## 10. Procedure and integrity

1. Run the full-state physics. Validate it against the Phase 4 margins.
2. Run the development stage on all networks. It fixes:
   - the placements;
   - p\*;
   - the coverage labels;
   - the state-estimation gate.

   Its outputs may be inspected. Any change after inspecting them is recorded as an
   amendment.
3. Freeze the code and record hashes. Then run the evaluation stage once; the CLI refuses
   a second run.
4. Run independent reviews of the results and report every outcome, including negative
   ones.

## 11. Limitations known in advance

- **Synthetic, non-pristine data.** The profiles and networks are synthetic and reused.
  Five networks have scaled PV.
- **Balanced single-phase model.** Real LV feeders are unbalanced, and phase-specific
  meters see different voltages.
- **Uniform cap.** Per-unit curtailment, where sensing could help most, is not studied.
- **Constant model errors.** Model mismatch is constant for a year. There is no MV voltage
  variation, and topology errors are not studied.
- **Exact metered injections.** They are assumed both for planning and for the consistency
  label.
- **Feedback is a count.** The online feedback counts violations. It does not use voltage
  magnitudes or trends.
- **Pseudo-measurements.** Their quality depends on the naive 7-day forecast.

## Amendments

### 5A and 5B (2026-10-18; after the first development run, before any evaluation-stage run)

**Context.** The first development run of all networks was inspected.

- Its outputs are archived in `outputs/sense_study/development_v1/`.
- No evaluation-stage computation had been made at this point.

**5A: estimator inputs exclude current magnitudes.**

- **The problem.** With the feeder-head current-magnitude readings as WLS inputs,
  pandapower's estimator failed to converge on many development steps:
  - 55–57 % success in urban6 under the nominal, tap and MV-voltage truths;
  - 79–82 % success in rural3 under those truths;
  - 2–77 % success across the networks under the PV reactive-power truth (rural3 4 %,
    urban6 2 %).

  A failed estimate raises no alarm, so these failures would have counted as missed
  detections.
- **The diagnosis.** On development days, without those readings every estimate converged.
  Voltage-event recall in urban6 under `tap_raise_lv` rose from 33 to 50 of 58.
  Warm-starting from a power flow did not help.
- **The rule.** Current magnitudes are dropped from the estimator's inputs
  (`estimation.estimator_inputs`).
- **What is kept.** Measured currents still raise direct alarms, and the gate and
  hypotheses are unchanged.
- **Procedure.** The development stage, including the gate, is re-run with this change.

**5B: greedy ties follow the topology order.**

- **The problem.** Where substation telemetry already detects almost every development
  violation, the greedy detection objective is flat. The decision-aware objective was flat
  after its first pick in several networks.
- **Effect of the registered rule.** Ties went to the lowest bus index, i.e. an arbitrary
  placement.
- **The rule.** Candidates are now ordered by the topology rule, so ties fall back to
  feeder ends. This makes the greedy rules no weaker than the topology rule when their
  objective cannot discriminate.

**Not amended** (both are reported as findings, not tuned away):

- **Smart-meter noise and over-curtailment.** Development showed that 1 % smart-meter
  noise causes false alarms and over-curtailment under the nominal truth. The primary
  detection rule and noise level stay as registered; the `precise_meters` condition shows
  the effect of precision.
- **The τ bound.** The 0.40 bound of Phase 4 amendment 4B limits recovery in the
  stress-bracket cells.

### 5C (2026-10-18; after the development re-run, before the evaluation run)

**Gate outcome.**

- With amendment 5A the estimator converged on every sampled step.
- State-estimation voltage-event recall was 0.88–0.98, against 0.10–0.44 for direct
  substation detection.
- But its false-alarm rate rose to 0.055–0.107 in semiurb4, semiurb5 and urban6, above the
  registered 0.05 increase.
- The gate therefore passes in 2 of 5 networks and is **closed**. (In the first
  development run it was open, but only because failed estimates raised no false alarms.)

**What the closed gate means.**

- The evaluation stage does not run state-estimation feedback (s. 7.4).
- State-estimation *detection* is still evaluated (s. 7).
- An **exploratory, development-only** run of state-estimation feedback (all networks and
  truths, development days) is reported separately and labelled exploratory. It is not
  part of any hypothesis.

**Efficiency change, results unchanged.** A run now stops at its last scored day, so a
development run never simulates evaluation days. Development records are unchanged; this
was checked on rural1.
