# Research protocol

This protocol fixes hypotheses, data separation, settings and decision rules *before* the
corresponding experiments are run. Anything decided after seeing results is labelled
exploratory in the results document.

| Section | Registered | Status |
|---|---|---|
| 1–2 Track 1 (national load) experiments C1–C3 | 2026-10-17, before any C-experiment run | registered |
| 3.0 Track 2 data split and network | 2026-10-17, before exploring any profile | registered |
| 3.1–3.7 Track 2 experiments | 2026-10-17, after the literature review and development exploration, before any evaluation-period run | registered |
| 3.6a Amendment A1 | 2026-10-17, during the evaluation run, before any evaluation result was viewed | registered (exploratory additions only) |
| 3.6b Amendment A2 | 2026-10-17, evaluation run stopped before writing any result | registered (physics defect fix) |
| 4 Phase 4 (dual uncertainty) | 2026-10-17, after the reproduction, the rural1 diagnosis, the literature reviews and the development-half network survey; before any Phase 4 policy run | registered |
| 4.11 Amendment 4A | 2026-10-17, after three independent pre-evaluation reviews; before any Phase 4 policy run | registered |
| 4.12 Amendment 4B | 2026-10-17, after the power-systems review; before any Phase 4 policy run | registered |
| 4.13 Amendment 4C | 2026-10-17, after the development check of 4A item 10; before any evaluation run | registered |
| 4.14 Amendment 4D | 2026-10-18, after the full development run; before the evaluation run | registered |

## 1. Two tracks that must not be conflated

- **Track 1** studies national German load: OPSD, hourly, MW. It concerns forecasting and
  forecast reliability.
- **Track 2** studies a benchmark low-voltage distribution grid (SimBench, pandapower AC
  power flow). It concerns physical constraint risk and operational decisions.

National load is never mapped onto feeder buses. Methods may be shared between the tracks
(rolling residual calibration, block bootstrap); data and conclusions are not.

## 2. Track 1: forecasting foundation (Milestone C)

The common protocol is unchanged from methodology sections 1–9 and 13:

- 00:00 UTC origins, 24 hourly targets.
- Fit on 2015–2017 targets; 2018 is the selection period (early stopping, all choices
  below); 2019 is evaluated.
- 2019 was inspected in Phases 1A–2A, so Track 1 results are **not confirmatory**.
- 2020 stays excluded.
- Comparisons always use common-valid pairs.

### C1. Boosting cap

- **Question:** does the 500-round cap of Phase 2A materially limit 2018 performance?
- **Arms:** cap 500 (Phase 2A) vs cap 3,000. All other settings, including early-stopping
  patience 50, are unchanged.
- **Why 3,000:** the 2018 MAE was still falling at round 500. A six-fold cap gives early
  stopping room to trigger at learning rate 0.05 with the slowly converging L1 objective.
- **Recorded:** best iteration, training time, 2018 MAE and RMSE.
- **Decision rule:** adopt the 3,000 cap for C2–C3 only if its 2018 MAE is at least 1.0 %
  lower than the 500 cap's. Otherwise keep 500.
- **Caveat:** under early stopping the 2018 MAE of the 3,000 arm is selected on 2018 and
  therefore optimistic; the 1 % threshold is the guard against a trivial gain.

### C2. Holiday-feature ablation

- **Question:** does known-ahead holiday information reduce the documented holiday
  failure?
- **Arm A:** the five Phase 2A features.
- **Arm B:** A plus three binary flags, each from the Europe/Berlin local date and the
  nationwide holiday table:
  - `target_is_holiday`;
  - `lag_24h_source_is_holiday`;
  - `lag_168h_source_is_holiday`.
- **Availability:** all three flags depend only on calendar dates known before the origin.
- **Holiday table:** extended to 2014-12-25 – 2020-01-01 and verified against
  timeanddate.com, including the one-off nationwide Reformation Day on 2017-10-31.
- **Configuration:** from C1, identical for A and B.
- **Reported:** both periods, overall and per Phase 1B holiday category, MAE/RMSE/WAPE on
  common pairs.
- **Uncertainty:** paired day-level differences in MAE (B − A) with a 95 % circular block
  bootstrap interval (7-day blocks, 2,000 resamples, seed 42).
- **Expectation:** B lowers MAE on `target_holiday_only`. The overall change is expected to
  be small, because only about 2 % of hours are holidays.
- **Status:** the hypothesis was formed after inspecting 2018 and 2019 errors, so C2 is
  exploratory. Neither year is confirmatory.
- **Model choice for C3:** B if its 2018 overall MAE is lower than A's, otherwise A.

### C3. Day-ahead prediction intervals (rolling split conformal)

**Method:** one method only.

- For origin *d* and lead *h*, take the absolute residuals |*y* − *ŷ*| of the same lead
  from origins *d* − 56 … *d* − 1. All of these targets are completed before origin *d*.
- The interval is *ŷ* ± *q*, where *q* is the ⌈(*n* + 1)(1 − α)⌉-th smallest of the
  *n* available residuals.
- α = 0.10 (nominal 90 %); *n* = 56 when the window is complete.

**Information timing:** a residual is used only after its target interval has ended, and
the protocol already ignores publication delay.

**Separation of roles:**

| Role | Data |
|---|---|
| Fitting | 2015–2017 |
| Model selection | 2018 (early stopping, C1/C2 rules) |
| Calibration | rolling window of past out-of-sample residuals |
| Evaluation | 2018-02-26 – 2018-12-31 (development; first 56 days of 2018 form the first window) and 2019 (each day calibrated on the previous 56 days, starting with late 2018) |

- 2019's first windows use 2018 residuals. 2018 influenced model selection, so it is not
  fully independent of the model. This is acknowledged.
- Residuals from training-period origins are never used, because they are in-sample.

**Reported:**

- empirical coverage and mean width: overall, by lead, by holiday category, by month;
- the share of days with all 24 hours covered;
- 95 % circular block bootstrap intervals (7-day blocks) for coverage and width.

**What is not claimed:**

- No finite-sample coverage guarantee holds here: residuals are temporally dependent and
  the distribution shifts.
- The rolling window is an adaptive heuristic in the spirit of conformal methods for
  non-exchangeable data. It is not a guarantee.

**Expected failure:** under-coverage on holidays and in the days after them, because the
window contains few such days.

### C4. Reliability diagnostics

No separate method. C3 outputs the monthly coverage and width, and coverage by holiday
category. No new reliability score is defined.

## 3. Track 2: distribution-grid risk and decisions

### 3.0 Data split and network (frozen 2026-10-17, before any profile was explored)

**Network:** SimBench `1-LV-rural1--2-sw`, chosen on structural grounds only.

- It is the smallest SimBench LV grid: 15 buses (one 20 kV slack bus, 14 buses at
  0.4 kV), 13 cable sections NAYY 4x150 (270 A) and one 0.16 MVA 20/0.4 kV transformer.
- Scenario 2 is SimBench's "future grid without grid expansion". It has 8 PV systems
  totalling 0.468 MW, 5 PV home-storage units, heat pumps and home EV charging.
- The SimBench tutorial states that scenarios 1 and 2 violate limits, so stress is a
  property of the benchmark, not something constructed here.

**Limits:** those supplied by the benchmark.

| Element | Limit |
|---|---|
| LV buses | `min_vm_pu` 0.90, `max_vm_pu` 1.10 |
| Slack bus | 0.965 / 1.055 |
| Lines and transformer | `max_loading_percent` 100 |

**Time:** SimBench 2016 profiles, 35,136 quarter-hours.

*Correction (2026-10-17, made before any profile values were explored):* the SimBench
`time` column turned out to be German local time with daylight saving. 2016-03-27 skips
02:00–02:45 and 2016-10-30 repeats it. The profiles are localised to Europe/Berlin and
handled in UTC. Days are UTC days of 96 steps, as in Track 1.

| Period | Dates |
|---|---|
| Development | 2016-01-01 – 2016-06-30 |
| Evaluation | 2016-07-01 – 2016-12-31 |

- Only development data may be explored or used to choose the forecaster, the scenario
  method and the thresholds.
- Evaluation-period data enter only as past information at decision time (rolling
  windows) and as realised outcomes after the protocol is frozen.
- Development is mostly spring and evaluation summer to winter, so evaluation includes a
  seasonal shift by construction.

The remaining Track 2 protocol (sections 3.1 onward) is registered after the literature
review and development-period exploration, and before any evaluation-period run.

### 3.1 Findings from development exploration (January–June only)

- **Storage modification.** The SimBench storage series for this grid are one-signed: the
  benchmark's own bounds are `pMin` = rating < 0 and `pMax` = 0. In pandapower's load
  convention they would inject power at the PV peak and never charge, which is
  energy-infeasible for a battery. Their intended semantics could not be verified, so all
  storage units are held at **0 MW**. This is a stated modification of the benchmark
  scenario.
- **Realised violations.** With no action, 689 of 17,472 development steps violate a
  limit, on 64 of 182 days.
  - Every one is a **transformer overload** from PV reverse power flow, at 2–41 % above
    rating.
  - There are no voltage or line violations, and no non-converged flows.
  - Violations occur from March to June, between 07:00 and 14:00 UTC.
- **Forecaster choice.** The 7-day mean at the same UTC time of day (`mean_7d`) had the
  lowest development MAE for the feeder PV total (15.7 kW), against persistence 18.7,
  same-day-last-week 20.2 and a 14-day mean 15.9. For load (5.44 kW) it was within 1 % of
  the best. It is used for every element.

### 3.2 Decision problem

- **Origin:** 00:00 UTC of day *d*.
- **Decision:** for each of the 96 quarter-hours *t* of day *d*, a PV feed-in cap
  *k*ₜ ∈ {1.0, 0.9, …, 0.0} as a fraction of installed capacity, applied to all 8 PV
  systems. Output = min(available, *k*ₜ × rating).
- **Cost:** curtailed PV energy Σ (available − capped) × 0.25 h, in MWh. This energy is
  lost, not shifted.
- **Information at the origin:** every realised injection before day *d*. Nothing from
  day *d* or later.
- **Not modelled:** reactive-power control, transformer taps, storage, and any
  sub-15-minute dynamics. No equipment is ever commanded; this is an offline study.

### 3.3 Forecast, scenarios and risk

- **Forecast:** *F*_d(t) = mean of the realised values at the same UTC time on days
  *d* − 7 … *d* − 1, for each element (load P and Q, PV available P).
- **Residual day:** *R*_j = *A*_j − *F*_j, joint across all elements and all 96 steps. Using
  whole days keeps the spatial and intraday dependence that is actually present.
- **Scenarios:** *F*_d + *R*_j for the 28 days *j* = *d* − 28 … *d* − 1. Every scenario uses
  only data from before the origin. PV is clipped to [0, rating] and load P to ≥ 0. There
  is no random sampling, so no seed is needed.
- **Risk at level *k*:** *r*ₜ(*k*) = share of the 28 scenarios whose AC power flow, with cap
  *k*, violates any limit. A non-converged scenario counts as a violation.
- **First evaluable days:** development from 2016-02-05 (a full residual window is
  needed); evaluation from 2016-07-01, whose first windows use June data as past
  information only.

### 3.4 Policies

All policies use the same information, network, limits, action set and cost.

| Policy | Rule |
|---|---|
| `no_action` | *k* = 1 |
| `static_70` | *k* = 0.7 always: the German 70 % PV feed-in limit, applied here to PV output rather than to net feed-in |
| `point` | largest *k* whose AC flow on the point forecast is violation-free; if none, *k* = 0 |
| `risk` | largest *k* with *r*ₜ(*k*) ≤ α, α = 0.05; if none, *k* = 0 |
| `selective` | the `risk` schedule, unless the day is deferred (below) |
| `oracle` | largest *k* whose AC flow on the **realised** injections is violation-free; if none, *k* = 0. Uses future information; an unattainable reference only |

**Deferral criteria for `selective`:** whole days, each checked at the origin.

- **D1 (no feasible action):** some step has *r*ₜ(*k*) > α at every *k*.
- **D2 (calibration monitor):**
  - Over the previous 28 days, take the steps where `risk` acted on non-zero no-action
    risk, i.e. *r*ₜ(1) > 0.
  - Let *V* be their realised violations and μ = Σ *r*ₜ(*k*ₜ) their predicted count.
  - Defer when *V* exceeds the 95 % upper quantile of a Poisson(μ) distribution. This is a
    one-sided 5 % test that realised failures exceed predictions.
- **D3 (solver):** any scenario power flow for the day failed to converge.

**After deferral** (each evaluated separately; deferral itself is a workflow outcome, not
a physical action):

| Fallback | Schedule applied |
|---|---|
| F-ROBUST (primary) | largest *k* with *r*ₜ(*k*) = 0; if none, *k* = 0 |
| F-STATIC70 | 0.7 |
| F-NONE | no action |

The cost of review is reported as the number of deferred days. It has no monetary value.

### 3.5 Metrics

- **Realised violation steps:** the AC flow of the realised injections under the policy's
  cap. Reported in total, by type, and with non-convergence counted separately.
- **Severity:** Σ positive transformer-overload margin, in %·steps.
- **Curtailed energy** in MWh, and the excess over the oracle.
- **For `selective`:** deferral rate, recommendation coverage, and outcomes on deferred and
  non-deferred days under each fallback.
- **Risk calibration of *r*ₜ(1)** against realised no-action violations, over all steps:
  - Brier score;
  - Brier skill score against a reference available at the origin, namely the realised
    no-action violation frequency at the same UTC time over the previous 28 days;
  - a reliability table (bins 0, (0, 0.1], (0.1, 0.3], (0.3, 0.6], (0.6, 1]) and the
    expected calibration error (ECE).
- **Decision-level calibration:** the realised violation rate on `risk`'s active steps
  (*r*ₜ(1) > 0), compared with α.
- **Uncertainty:** the unit is the day. Paired per-day differences between policies get
  95 % circular block bootstrap intervals (7-day blocks, 2,000 resamples, seed 42).
  Correlated quarter-hours are never treated as independent replications.

### 3.6 Hypotheses and failure criteria (evaluation period, 2016-07-01 – 2016-12-31)

- **H1 (risk skill under seasonal shift):** BSS of *r*ₜ(1) > 0, with the 95 % CI excluding
  0. *Failure:* the CI includes or lies below 0. The development-vs-evaluation ECE
  comparison is exploratory.
- **H2 (decision value):**
  - (a) `risk` has fewer realised violation steps than `point` (CI of the per-day
    difference < 0);
  - (b) `risk` curtails less energy than `static_70` (CI < 0).
  - *Failure:* either CI includes 0 or has the opposite sign.
- **H3 (nominal vs realised):** on active steps, `risk`'s realised violation rate exceeds
  the nominal α = 0.05. This is a prediction about scenario-based chance constraints, not a
  success criterion; it is falsified if the realised rate is ≤ 0.05.
- **H4 (selective deferral):**
  - (a) Before any fallback, the realised violation rate of `risk` on active steps is
    higher on deferred days than on non-deferred days.
  - (b) With F-ROBUST, `selective` has fewer violation steps than `risk`.
  - (c) With F-NONE and at least one deferral, `selective` has *more* violation steps than
    `risk`. This demonstrates that deferral is not safety.
  - If no day is deferred, H4 is reported as untestable.

### 3.6a Amendment A1 (2026-10-17; written during the evaluation run, before any evaluation result was viewed)

An independent code review, using development data and input profiles only, found the
following. Each is recorded here before interpreting the evaluation.

1. **H2(b) is degenerate.**
   - SimBench PV output never exceeds about 0.60 of rating in this grid: 0.603 maximum in
     development, 0.591 in evaluation inputs.
   - So `static_70` never binds and equals `no_action`. Cap levels 1.0–0.7 are
     equivalent, and fallback F-STATIC70 equals F-NONE.
   - H2(b) as registered is therefore certain to fail. It will be reported as such, not
     redefined.
2. **One amendment baseline, exploratory only, is added:** `static_dev`.
   - It is the largest fixed cap *k* whose realised no-action violations over the whole
     development period are zero. If no *k* qualifies, it is the *k* with the fewest
     violations.
   - It represents a DSO choosing a fixed limit from historical simulation. It uses
     development data only and is evaluated unchanged on the evaluation period.
   - It does not replace any registered comparison.
3. **The evaluation period ends on 2016-12-30**, not 12-31. The profiles end at
   2016-12-31 22:45 UTC, so the last UTC day is incomplete. This is a data-availability
   correction.
4. **D2 resolution.** With 28 scenarios, *r* ≤ 0.05 means at most 1 violating scenario, so
   predicted counts μ on accepted steps are small. A Poisson(μ) upper quantile of 0 means
   a single realised violation in 28 days triggers D2. This follows from the registered
   design and is stated so that it is not discovered post hoc.

   *Post-hoc note:* in the runs this case never occurred. Every deferral had a threshold
   of 4–11 and 7–38 observed violations. See the results.

**Protocol deviation (recorded with A1).** The code review that prompted A1 computed one
evaluation-period *input* statistic: the maximum PV output relative to rating (0.591).
Section 3.0 allows only development data to be explored. No evaluation outcome was
involved, and the only use was to confirm that the 70 % cap cannot bind.

### 3.6b Amendment A2 (2026-10-17; the evaluation run was stopped before writing any result)

An independent physics review found a modelling defect. The evaluation run in progress
was stopped, and it had produced no output. No evaluation result has been viewed.

1. **Defect: the benchmark's transformer tap was silently dropped.**
   - SimBench sets `tap_pos` = +1 (HV side, 2.5 % step). The simbench 1.6.3 converter
     leaves `tap_changer_type` empty, so pandapower 3.5.6 ignores the tap.
   - Confirmed: LV no-load voltage was 1.025 p.u. instead of 1.000.
   - *Fix:* `tap_changer_type` = "Ratio" whenever a tap position is given. A test checks
     the no-load LV voltage.
   - Effect: higher transformer current (about +2.4 %), so more overloads. The
     development findings in s. 3.1 (689 violating steps) come from the defective model.
     The pre-fix development outputs are kept and compared with the corrected run in the
     results.
2. **Voltage margins** are computed over LV buses only, excluding the slack bus held at
   1.025 p.u. Violation flags are unaffected, but the stored margins now show the true LV
   headroom.
3. **Storage scenario wording.** Holding storage at 0 MW is a consequential modelling
   choice, not a neutral fix.
   - Under the published series (pandapower convention) development violations rise.
   - If the series is read as PV charging, they almost vanish.
   - The study is therefore described as "PV and load without battery dispatch".
   - A development-only exploratory run bounds the effect: storage as published, and
     storage as charging.
4. **Procedure.** Re-run development with the corrected model (verification), then run
   the evaluation once.
   - Policies, thresholds, hypotheses and amendment A1 are unchanged.
   - The physics cache now carries a code fingerprint and refuses stale physics.

### 3.7 Fixed settings and integrity

- **Fixed settings:** α = 0.05, window 28 days, `mean_7d`, the cap grid, the deferral
  test and the fallbacks are fixed here.
- **Exploratory only:** α ∈ {0.01, 0.10}.
- **Integrity:** the development period is run first to verify the implementation. The
  evaluation period is run once with frozen code. Any defect fixed after an evaluation run
  is documented together with its effect.

## 4. Phase 4: reliability under dual uncertainty

Section 4 is registered on 2026-10-17. It was written after the reproduction, the
diagnosis on rural1 (s. 4.1), the literature reviews and the development-half network
survey (s. 4.2), and **before any Phase 4 policy was run on any network**.

- **Physics start.** The physics computation (AC power flows only, no policy) started at
  14:05 UTC under code fingerprint `290e7371…`, once the networks, PV scales and model
  variants had been fixed in code. No physics output was inspected before this section
  was complete.

### 4.0 Question, and what is no longer pristine

**Question.** Can physically grounded, reliability-aware day-ahead decisions outperform
simple, strongly validated intervention policies when forecast errors and physical-model
errors are both present? If so, when and why?

**What is no longer pristine:**

- **`1-LV-rural1--2-sw` (all of 2016)** is a *development network*. Phase 3 evaluated it
  on 2016-07-01 – 12-30, and the Phase 4 diagnosis used all of it. Every Phase 4 rural1
  result is exploratory.
- **The SimBench 2016 profiles** are shared between networks, so the second half of 2016
  is not meteorologically pristine.
  - rural1's PV profiles PV5, PV6 and PV8 also feed semiurb4, semiurb5 and urban6.
  - rural2 and rural3 use PV1, PV3, PV4 and PV7, which no earlier phase used.
  - The evaluation of the five new networks is therefore *semi-confirmatory*. Their
    topologies, parameters and binding constraints are new; parts of their weather are
    not.

### 4.1 Reproduction and diagnosis (rural1; exploratory)

**Reproduction.** Phase 3 reproduces exactly:

- grid-study and forecast-study outputs are byte-identical;
- five cached physics days recomputed from scratch are bit-identical;
- the new Phase 4 code reproduces the Phase 3 daily outcomes of `no_action`, `point`,
  `risk`, `robust`, `oracle` and `static_dev` exactly.

**Why scenario risk underperformed the historical-frequency reference.** Days 63–364 of
rural1 were used; the frequency reference equals a "replay" ensemble of the past 28
realised days.

1. **No meaningful probabilistic difference.**
   - At fixed cap levels, with no selection, the residual-scenario risk overpredicts
     total violations by 7 %. Replay is unbiased by construction.
   - Brier scores at no action: scenario 0.0304, replay 0.0287. AUC: scenario 0.949,
     replay 0.953.
   - The Phase 3 bootstrap intervals of this difference included 0.
2. **The 3× gap is selection optimism.**
   - The rule "largest cap with at most 1 of 28 members violating" selects caps where the
     in-sample estimate is low. Realised over in-sample predicted violations on active
     steps: scenario 3.4, replay 2.4.
   - **Cross-fitted:** when one half of the members chooses the cap and the other half
     reports its risk, the ratios fall to 1.12–1.23 (scenario) and 0.91–1.00 (replay).
   - This matches theory. Under exchangeability and monotone violation, the "≤ 1 of 28"
     rule has expected violation probability 2/29 ≈ 0.069 with in-sample risk ≤ 1/28; the
     zero-violation rule has 1/29 (Campi & Garatti 2011).
3. **The forecaster adds little.** The 7-day mean carries no weather information.
   - Exploratory results on rural1 (2016-07-01 – 12-30): a robust rule on replay had 4
     violation steps at 10.2 MWh; on residual scenarios it had 24 at 9.4 MWh.
4. **The action space is coarse.** PV peaks at about 0.6 of rating, so caps 1.0–0.6 are
   physically identical. Cap 0.4 still violates, and 0.3 never does.

### 4.2 Networks: eligibility, survey result and stress rule

**Eligibility.** Written at 13:35 UTC, before the survey was run:

- **Survey design.** Development half only (2016-01-01 – 06-30). Scenario `--2`, with
  `--0` and `--1` descriptive. Benchmark taps made effective, storage idle, PV q = 0. Two
  flows per step: no action, and PV cap 0.
- **E1.** No non-converged flow.
- **E2.** At least 50 PV-driven violation steps (violation at no action, none at cap 0).
- **E3.** Violations that persist at cap 0 are reported separately.

**Survey result: no new network is eligible.**

| Network (`--2-sw`) | Transformer | Tap | PV (MW) | Development violation steps | Peak loading margin | Peak voltage margin |
|---|---|---|---|---|---|---|
| rural1 | 0.16 MVA | +1 | 0.468 | 757 (transformer) | +44.5 % | −0.064 p.u. |
| rural2 | 0.25 MVA | −1 | 0.234 | 0 | −54.9 % | −0.036 |
| rural3 | 0.40 MVA | −1 | 0.252 | 0 | −40.7 % | −0.036 |
| semiurb4 | 0.40 MVA | 0 | 0.172 | 0 | −69.2 % | −0.061 |
| semiurb5 | 0.63 MVA | 0 | 0.185 | 0 | −69.0 % | −0.066 |
| urban6 | 0.63 MVA | −1 | 0.171 | 0 | −66.1 % | −0.042 |

- **What this means.** The congestion studied in Phase 3 exists in only one of six
  SimBench LV topologies in their 2034 scenario. This is a finding in its own right.
- **Other scenarios.** Among `--0` and `--1`, only rural1 `--1` has PV-driven violations.
  semiurb5 `--0` has an overvoltage at every step that curtailment cannot remove: two LV
  buses have `max_vm_pu` 1.01, a data quirk. It is excluded.

**Stress rule.** Fixed after the survey and before any policy run. It is a stated
modification of the benchmark.

- **Hosting capacity.** *h*ₙ is the largest uniform scale of a network's PV installations
  (rating and output alike) with no no-action violation on any daylight quarter-hour of
  the development half.
  - Nominal model; bisection to 0.5 %; `dual_study.hosting_capacity`.
- **Scaling.** Each new network's PV is scaled by *s*ₙ = *h*ₙ / *h*_rural1. Each network
  then operates at the same multiple of its own hosting capacity (1/0.715 = 1.40) as the
  benchmark's rural1 scenario 2, which keeps its published PV.
- **Why this rule.** It uses no policy outcome, and the binding constraint emerges from
  each network's own physics.

| Network | *h*ₙ | *s*ₙ | Scaled-network development violations (no action) | Binding constraint |
|---|---|---|---|---|
| rural1 | 0.715 | 1 | 757 | transformer |
| rural2 | 2.094 | 2.929 | 588 | transformer |
| rural3 | 3.109 | 4.350 | 626 | transformer; overvoltage at 279 steps |
| semiurb4 | 2.664 | 3.727 | 820 | line |
| semiurb5 | 4.969 | 6.951 | 750 | line; overvoltage at 155 steps, transformer at 9 |
| urban6 | 4.297 | 6.011 | 554 | line; overvoltage at 47 steps |

All scaled-network violations are PV-driven, and every flow converged. The scaled
networks are stress cases with a lot of PV, not forecasts of real growth.

### 4.3 Two sources of uncertainty

**Forecast information.**

- **F0, perfect:** the decision sees the realised injections of day *d*.
- **F1, day-ahead:** the Phase 3 forecast (7-day mean) and 28 whole-day residual scenarios
  from days *d* − 28 … *d* − 1.
- **Replay** (both F0 and F1): the realised injections of days *d* − 28 … *d* − 1.

**Physical model.** Every decision uses the **nominal** model: the benchmark network,
storage idle, PV q = 0, benchmark tap and a 1.025 p.u. MV voltage. Outcomes are scored on
a **true** grid, either the nominal model or one of the variants below. Taps are on the HV
side, 2.5 % per step, range ±2.

| Variant | Change | Justification | In ensemble |
|---|---|---|---|
| `tap_raise_lv` | tap −1 | SimBench re-taps 37–50 % of MV/LV transformers by one step between scenarios. Off-load taps are set on site and rarely revised (FNN 2016) | yes |
| `tap_lower_lv` | tap +1 | as above | yes |
| `pv_cosphi_p` | cos φ(P): 1 up to 0.5 *P*ₙ, then linear to 0.90 underexcited at *P*ₙ | VDE-AR-N 4105 standard characteristic; the DSO chooses the method | yes |
| `pv_fixed_095` | fixed cos φ 0.95 underexcited | an admissible DSO specification under VDE-AR-N 4105 | yes |
| `storage_greedy` | the network's total storage power and energy moved to PV buses (pro rata to PV rating), self-consumption-maximising against local load, state of charge carried over days | the most common German home-battery operation (Weniger et al. 2014; HTW 2025) | yes |
| `storage_profile` | the one-signed benchmark storage series read as charging, energy-limited, emptied daily | one reading of the benchmark's own data. No reading tested was energy-consistent | yes |
| `mv_high` | MV voltage 1.055 p.u. | SimBench's own low-load / high-PV study case | no |
| `joint_realistic` | `mv_high` + `pv_cosphi_p` + `storage_greedy` | several plausible database omissions at once | no |
| `joint_loading` | `tap_lower_lv` + `pv_fixed_095` | adverse combination for loading | no |

**Two modelling details:**

- **Storage schedules** do not depend on the PV cap. For F1, the forecast set of a variant
  uses the 7-day mean of the storage schedule, because the benchmark series follows
  same-day PV.
- **A combination that was dropped.** Tap −1 together with MV 1.055 p.u. was considered as
  a joint and dropped before any study physics was computed. In the three networks
  already tapped to −1 it gives a no-load LV voltage above 1.10 p.u. at every step. That
  is an implausible operating point, and curtailment cannot fix it.

**Design.** 6 networks × 2 information levels × 10 truths (nominal + 9).

- **Forecast uncertainty only:** F1 with the nominal truth.
- **Model uncertainty only:** F0 with a variant truth.
- **Both:** F1 with a variant truth.

### 4.4 Policies

**Decision rule.** All policies pick, per quarter-hour, the largest cap in
{1.0, 0.9, …, 0} whose (worst-case) normalised margin is ≤ −τ; if none qualifies, cap 0.

- **Normalised margin:** value minus limit as a share of the allowed band (0.1 p.u. for
  voltage, 100 % for loading), maximised over constraint types. A failed flow counts as
  +∞.
- Cap levels are all simulated. No monotonicity in the cap is assumed.

| Policy | Information | Rule |
|---|---|---|
| `no_action` | — | cap 1.0 |
| `static_dev` | development days | one uniform cap: the largest with no violation on development days (nominal model, realised injections) |
| `static_aci` | measured feedback | cap-level index adapted online (s. 4.5); no forecast, no model |
| `point` | F0 or F1 | point set, τ = 0 |
| `point_margin` | F1 | point forecast with τ tuned on development: the smallest τ on {0, 0.01, …, 1} with no development violation |
| `point_aci` | F0 or F1 + feedback | point set, τ adapted online |
| `scenario_risk` | F1 | Phase 3 rule: at most 1 of 28 scenarios violates |
| `scenario_robust` | F1 | no scenario violates (τ = 0) |
| `scenario_aci` | F1 + feedback | worst scenario, τ adapted online |
| `replay_robust` | past days | no replay day violates |
| `replay_aci` | past days + feedback | worst replay day, τ adapted online |
| `ensemble` | F0: realised injections under the nominal model and all ensemble members. F1: worst scenario plus the largest positive shift of the forecast-set margin under any ensemble member | model-aware robust rule |
| `oracle` | true grid, realised | reference only (uses the future and the true model) |

### 4.5 Online calibration: fixed settings and what they guarantee

**Update rule.** After day *d*, measured feedback (*V*_d = daylight quarter-hours that
violated on the true grid at the applied caps) updates the policy:

- *τ*_{d+1} = max(*τ*_min, *τ*_d + γ(*V*_d − β)), with β = 0.1 violation quarter-hours per
  day, γ = 0.01 and *τ*_min = −0.10.
- `static_aci` updates a continuous cap-level index *c* ∈ [0, 10] by 0.1 × (*V*_d − β) and
  applies round(*c*).
- Online policies start neutral (τ = 0, no action) on the first decision day (2016-02-05),
  learn through development and are scored on evaluation days only.
- They use only outcomes at the caps actually applied (no counterfactual outcomes), so the
  feedback is model-free.

**Settings.** β, γ and *τ*_min are fixed here, from the rural1 exploration and the
literature. They are not tuned on any new network.

**What can be claimed.** This is the Rolling Risk Control / Conformal Decision Theory form
(Feldman et al. 2023; Lekeufack et al. 2023).

- Telescoping gives a deterministic bound for any window of *K* days: mean *V* ≤ β +
  (*τ*_max − *τ*_min)/(γ*K*). *τ*_max is bounded because a large τ forces cap 0 and so
  produces no PV-driven violation.
- With *τ*_max of about 1–2 and *K* = 183, the bound is vacuous (more than 0.5 violation
  quarter-hours per day).
- **Not claimed:**
  - any per-day or per-step guarantee;
  - any statement about caps not applied;
  - physical safety.

### 4.6 Periods, tuning and procedure

**Periods.** Development is days 35–181 (2016-02-05 – 06-30). Evaluation is days 182–364
(2016-07-01 – 12-30).

**Tuned on development days only:** the `static_dev` cap and the `point_margin` τ, both
with the nominal model, as a DSO would tune them.

**Procedure:**

1. Physics for all networks and variants.
2. Development run (`dual-study --stage development`). Development outputs may be
   inspected for verification across all networks. Any code change made after inspecting
   them is recorded as an amendment with its reason.
3. Evaluation run, once, with frozen code.

The exploratory rural1 evaluation-half results are reported but never counted as
confirmatory.

### 4.7 Metrics

Per (network, information, truth, policy), over evaluation days:

**Violations:**
- daylight violation steps, in total and per day;
- days with a violation, and the worst day;
- longest run of consecutive violation steps;
- peak normalised margin;
- severity (Σ positive normalised margin);
- non-converged steps.

**Curtailment:** curtailed MWh, and the excess over `oracle`.

**Meets the requirement:** daylight violation steps per evaluation day ≤ β = 0.1.

**Paired per-day differences**, with 95 % circular block bootstrap intervals (7-day
blocks, 2,000 resamples, seed 42), for:

- `scenario_aci` − `replay_aci`;
- `replay_aci` − `static_aci`;
- `scenario_aci` − `static_aci`;
- `ensemble` − `replay_aci`;
- `point` − `ensemble`.

**Risk diagnostics** (s. 4.1 definitions) per network and truth: in-sample and
cross-fitted realised/predicted ratios for both ensembles, and the no-action Brier skill
of scenarios against replay.

**Cost of reliability:** the extra curtailment of one policy over another per avoided
violation step, ΔMWh / Δsteps, reported where both differ.

### 4.8 Hypotheses and decision criteria

All hypotheses concern the evaluation half of the **five new networks**. Results are given
per network and summarised by counts; no claim rests on a single p-value.

**H1: selection optimism generalises.** (F1, nominal truth.)

- (a) The in-sample ratio realised/predicted at the Phase 3 rule's chosen caps exceeds 1.5,
  for both ensembles.
- (b) The cross-fitted ratio lies in [2/3, 3/2]. This is checked for replay (primary) and
  for scenarios (secondary).
- A network with fewer than 20 realised violations in the cross-fitted count is
  uninformative.
- *Supported* if (a) and the primary (b) hold in every informative network.

**H2: forecast value over replay.** (F1, nominal truth.)

- The day-ahead forecast "adds value" in a network if, for `scenario_aci` − `replay_aci`,
  one of the two intervals (violation steps per day, curtailed MWh per day) lies below 0
  and the other does not lie above 0.
- *Prediction (from rural1):* this holds in at most 1 of 5 networks.

**H3: reliability-aware vs strong simple policies.** (F1; 5 networks × 10 truths = 50
cells; primary.)

- **Comparisons.** In each cell, `replay_aci` and `scenario_aci` ("reliability-aware") are
  compared with `static_dev` and `static_aci` ("simple").
- **When A is better than B in a cell:**
  - A meets the requirement and B does not; or
  - both meet it and the curtailment interval (A − B) lies below 0.
- *Genuine value* is claimed only if:
  - the better of the two reliability-aware policies is better than **both** simple
    policies in at least 3 of 5 networks under the nominal truth; and
  - it is better in at least half of the 45 mismatch cells.
- *Refuted* if a simple policy is better than both reliability-aware policies in at least
  3 of 5 networks under the nominal truth.
- *Otherwise inconclusive.* The counts are reported in full in every case.

**H4: explicit model ensemble vs measured feedback.**

- (a) **Pure model uncertainty (F0).** `point` uses the nominal model with perfect
  injections. It fails the requirement in at least one variant-truth cell, so model error
  alone can matter.
- (b) **In-ensemble truths (F0).** `ensemble` meets the requirement in every in-ensemble
  truth cell. This is largely by construction and is reported as such.
- (c) **Out-of-ensemble truths** (`mv_high`, `joint_realistic`, `joint_loading`; F0 and
  F1). `ensemble` fails the requirement in more cells than `point_aci` (F0) or
  `replay_aci` (F1).
- *Prediction:* explicit robustness protects only against the modelled deviations;
  feedback calibration does not need them to be modelled.

**D1 (descriptive): joint vs individual effects.** For `point` and `scenario_robust`, the
violation steps under F1 × variant are compared with F1 × nominal and F0 × variant. Is the
joint effect roughly additive, larger, or smaller?

### 4.9 Statistical calibration is not physical safety

- **Average targets.** An online policy that meets β meets a long-run *average*. Its worst
  day, longest overload run and peak margin are reported next to it.
- **"Zero observed".** A policy with no evaluation violation is described as "no violation
  observed in 183 days on this model". The rule-of-three upper bound for its daily
  violation probability is about 3/183 ≈ 0.016. It is never called safe.
- **Physical robustness** (`ensemble`) is a claim about the modelled variant set only.

### 4.10 Known limitations of this design

- **Scaled networks.** Five of six networks are scaled to a PV stress chosen by rule.
- **Synthetic profiles.** One benchmark year of synthetic profiles.
- **Storage.** Its semantics in the benchmark are unresolved; two readings are tested.
- **Uniform cap.** A single cap is applied to all PV units.
- **Violation criterion.** A quarter-hour flag; no thermal transformer model. Run lengths
  and peaks are reported instead.
- **Static variants.** Model variants are fixed for the year, not time-varying.
- **Forecaster.** The forecaster is naive (7-day mean). F0 brackets the value of better
  forecasts; intermediate forecast skill is not studied.

### 4.11 Amendment 4A (2026-10-17; after the pre-evaluation reviews, before any Phase 4 policy run)

**Reviews.** Three independent reviews ran while the physics was computing:

- methodology and statistics;
- code;
- power systems (its findings, if any, are added as 4B).

They read code and documents only, and checked physics on development days only. No
Phase 4 policy had been run on any network. Section 4 above is kept unchanged as the audit
trail; where the items below differ, they supersede it.

**Settings that the rural1 exploration informed.**

- The following were chosen after seeing rural1 outcomes for all of 2016, including the
  Phase 3 evaluation half:
  - β = 0.1, γ = 0.01, *τ*_min = −0.10 and the `static_aci` step of 0.1;
  - the set of online policies;
  - the 28-day replay window;
  - the normalised-margin family.
- **Weather.** The new networks share part of that weather.
  - Development-half daily PV energy correlates at 0.72–0.82 between rural1's profiles
    (PV5, PV6, PV8) and the PV1/3/4/7 profiles of rural2 and rural3.
  - PV2 correlates at 0.92–0.94 with PV5/6/8.
- **Loads.** Each new network shares 7–10 of its 20–23 load profiles with rural1.
- H2 and H3 are therefore also reported separately for {rural2, rural3} and {semiurb4,
  semiurb5, urban6}. "Semi-confirmatory" should be read with these numbers in mind.

**Comparisons and decision rules.**

1. **A fair simple policy.** `static_beta` is added: the largest uniform cap whose
   development daylight violation steps per day (nominal model, realised injections) are
   ≤ β. The simple set used in H3 becomes {`static_dev`, `static_beta`, `static_aci`,
   `point_margin`}.
2. **When A is better than B in a cell.** Inequalities are strict.
   - A meets the requirement, B does not, and the per-day interval of (A − B) for avoidable
     violation steps lies below 0; or
   - both meet it and the per-day curtailment interval of (A − B) lies below 0.
3. **What the requirement counts.** It is scored on *avoidable* daylight violations: steps
   at which some cap is safe on the true grid. "Meets" means avoidable daylight violation
   steps per evaluation day ≤ β.
   - A cell whose unavoidable daylight steps exceed β × 183 is listed and excluded from the
     H3 and H4 counts.
   - The online feedback stays as all measured daylight violations, because that is what
     an operator measures.
   - Fallback when no τ gives zero development violations: `point_margin` uses the
     smallest τ with the fewest, matching `static_level`.
4. **H1 as amended.** The half-split cross-fit is replaced by a leave-one-out estimate.
   - For each member *i*, the Phase 3 rule is applied to the other 27 members, and member
     *i*'s violation at that cap is recorded. The mean over *i* is the out-of-sample risk
     of essentially the same rule.
   - Realised violations at the Phase 3 caps are compared with the in-sample risk (a) and
     with the leave-one-out risk (b). Both ratios get 95 % day-block bootstrap intervals.
   - A network is informative with at least 8 distinct days with a realised violation
     (replay). H1 is "untestable" with fewer than 3 informative networks.
   - (a) is close to a theorem under exchangeability; (b) is the informative test.
5. **H3 as amended.**
   - Each of `replay_aci` and `scenario_aci` is assessed separately against all four
     simple policies.
   - *Genuine value* for a policy needs both of:
     - better than all simple policies under the nominal truth in ≥ 3 of 5 networks;
     - in ≥ 3 of 5 networks, better than all simple policies in at least half of that
       network's *material*, non-excluded mismatch cells. A variant is material if its
       development no-action daylight violations differ from nominal by ≥ 10 %.
   - *Overall verdict:*
     - "genuine value" if either policy qualifies (a stated two-way multiplicity);
     - "refuted" if any simple policy is better than both aware policies in ≥ 3 of 5
       networks under the nominal truth;
     - otherwise "inconclusive".
6. **H4 as amended.** Counts are reported per network, and F0 and F1 separately. H4(c) is
   close to true by construction, because the feedback policies learned the true grid
   during development.
   - D1 interaction for `point`: *V*(F1, *v*) − *V*(F1, nom) − *V*(F0, *v*) + *V*(F0, nom),
     in avoidable violation steps.
7. **Paired comparisons:**
   - `scenario_aci` − `replay_aci`;
   - each aware policy − each simple policy;
   - `ensemble` − `replay_aci`;
   - `ensemble` − `point_aci`;
   - `point` − `ensemble`.

   Each has the number of informative days (days where either policy violates) and the
   cost of reliability (ΔMWh per avoided violation step). Intervals resample days and are
   conditional on the realised path of each online controller.

**Physical-safety metrics.**

8. **Metrics not targeted by online calibration:**
   - severe steps (normalised margin > 0.2, e.g. more than 120 % loading);
   - runs of ≥ 4 consecutive violating quarter-hours;
   - the peak margin, which is +∞ if any applied flow failed.

   The same runs are also re-scored at β ∈ {0.05, 0.2} (exploratory).
9. **Online identity, reported per cell.** Mean feedback per day = β + (state_end −
   state_start − clipping)/(γ*K*), computed from the recorded controller path. Two notes
   for reading it:
   - τ relaxes by only 0.001 per quiet day, so evaluation behaviour is largely the margin
     inherited at the end of development;
   - one cap level corresponds to different τ steps in different networks.
10. **Development check, before the evaluation run.** In every network, `static_aci`'s
    level index at the end of development must not sit at a bound, and its applied level
    must not be more conservative than `static_dev`. If this fails, `static_aci` is
    revised before evaluation and the revision is recorded here.
11. **Rule of three (s. 4.9).** It uses *n* = days on which `no_action` has an avoidable
    violation on the true grid, and is labelled optimistic, because these days are
    serially dependent.
    - β = 0.1 (about 9 hours a year of exceedance of any size) is a modelling target, not
      an operational standard (cf. EN 50160 and IEC 60076-7).

**Physics and implementation notes.**

12. **Stress caveats.**
    - Hosting capacity is an extreme-value statistic, and the 1.40 multiple comes from
      rural1.
    - Storage is not scaled with PV, so storage variants are diluted 3–7× in the scaled
      networks.
    - Scaling PV by up to 7× changes a network's character.
    - The dropped joint (tap −1 with MV 1.055 p.u.) is excluded on plausibility. The
      no-load LV voltage would be about 1.055 × 1.05 ≈ 1.108 p.u., and an operator would
      re-tap.
    - Online calibration assumes every LV limit is measured each quarter-hour, which is
      rare in today's LV grids.
13. **Code fixes from the code review** (no run had used the faulty code):
    - the decision stage passed too few arguments to `load_margins` (it would have
      crashed);
    - cached physics is now refused unless its manifest matches the current code, PV scale
      and variant, and every day's array has the expected number of sets;
    - non-finite numbers are written as strings, so the JSON stays valid;
    - a second evaluation run is refused;
    - the protocol hash no longer depends on the working directory;
    - the physics code and its fingerprint (`290e7371…`) are unchanged.
    - **Known gap.** `grid_study.WINDOW_DAYS` and a few constants are in the hashed source
      but not in the fingerprint's settings. This is mitigated by those constants being
      fixed since Phase 3.
14. **Self-attested pre-registration.** The SHA-256 of this protocol and of every source
    file is written into each run's metadata. A commit or tag by the user before the
    evaluation run would make the registration verifiable by others; git stays under the
    user's control.

### 4.12 Amendment 4B (2026-10-17; power-systems review, before any Phase 4 policy run)

**Review result.** No blocker was found. The review confirmed:

- sign conventions (sgen q < 0 absorbs; storage p > 0 charges);
- tap direction and range;
- reactive power following the capped output;
- exact PV scaling;
- greedy-storage energy accounting and placement;
- the `profile_charging` energy limit and daily reset;
- cap-reuse validity under the variants;
- recycle behaviour;
- NaN handling;
- the hosting capacities (reproduced for rural1 and semiurb4).

All checks used development days. The changes and disclosures:

1. **Upper bound on τ.** Online margins are clipped above at τ_max = 0.40.
   - Voltage margins are normalised to the 0.1 p.u. band above 1.0 p.u. In networks tapped
     to −1 (rural2, rural3, urban6) the LV voltage with zero PV is already about 1.05 p.u.
   - So for τ ≳ 0.5 no cap level satisfies the rule, and it curtails all PV.
   - Development evidence from the review (share of daylight steps forced to cap 0): 0–20 %
     at τ = 0.50, 86–95 % at τ = 0.55.
   - With the clip, the long-run bound of s. 4.5 no longer holds when violations persist
     at τ_max. Clipping at both ends is included in the reported online identity.
   - `point_margin` keeps its grid up to τ = 1. If only a τ beyond the cliff removes all
     development violations, that rule *is* full daylight curtailment, and is reported as
     such.
2. **Failed nominal forecast flow.** In the F1 ensemble rule a failed nominal forecast flow
   is now treated as unsafe; previously a −∞ shift could hide it. No such failure was
   observed.
3. **Scheduled storage at deep caps.** Storage truth schedules do not depend on the cap, so
   at deep caps scheduled charging draws from the grid.
   - On rural1's `storage_profile` this caused 6 cap-0 violation steps on 82 development
     days. In other words, curtailing more can *increase* violations under this truth.
   - This is kept as part of that truth, a non-monotonicity of the kind the study must not
     assume away, and is not "fixed".
   - For greedy storage the assumption is benign at caps ≥ 0.3: at most 4.2 % of charging
     is uncovered by the capped own-bus surplus.
4. **Readings of the variants:**
   - **`storage_profile`.** It charges 15–21 % of its energy at night. The series looks like
     a charge-plus-discharge magnitude, which adds to the "no energy-consistent reading"
     note.
   - **`pv_cosphi_p`.** It is nearly inert, because PV never exceeds about 0.63 of rating
     (cos φ ≥ 0.974), so `joint_realistic` acts essentially as `mv_high` + `storage_greedy`.
   - **`mv_high` and `tap_raise_lv`.** On the networks tapped to −1 they put the zero-PV LV
     voltage near 1.08 p.u. and are reported as *stress brackets*.
5. **Further limitations.** These add to s. 4.10.
   - A uniform cap overstates curtailment in networks bound by local (line or voltage)
     limits, compared with transformer-bound ones.
   - The storage efficiency of 0.95 is read as one-way, which is unverified.

### 4.13 Amendment 4C (2026-10-17; development check of 4A item 10, before any evaluation run)

**The failed check.**

- Development runs on rural1 and rural2 (the first networks whose physics was complete)
  tested `static_aci` as 4A item 10 requires.
- In rural2 the check **failed**: `static_aci` started from no action, overshot during the
  spring violations, and ended development at level index 6.56 (applied cap 0.3).
  `static_dev` uses 0.4.
- **Cause.** With β = 0.1 the controller relaxes by only 0.01 level per quiet day. A cold
  start at the most aggressive setting therefore handicaps it.
- **The τ controllers do not have this problem.** They start at τ = 0, which is the robust
  rule and already a sensible operating point.

**Revision.** As 4A requires, `static_aci` is revised: it now starts from the
development-tuned `static_beta` level instead of from no action.

- Within development this is look-ahead, so its development scores are not meaningful.
  Its evaluation behaviour is "the development-validated cap, corrected online by measured
  feedback".
- After the revision, the end-of-development level index is 7.23 in rural1 and 5.83 in
  rural2 (applied 7 and 6, equal to `static_dev`), and neither is at a bound.
- The check is repeated for every network before the evaluation run.

**Two further fixes:**

- Numpy scalars are now converted for JSON output; the hypothesis file of the first
  development run failed to serialise.
- No other code or setting changed.

### 4.14 Amendment 4D (2026-10-18; full development run, before the evaluation run)

**Development run.** After the physics for all six networks was complete, the development
stage was run on all of them. The development outputs of every network were inspected:
policy totals, tuned settings, online states and diagnostics.

**Checks:**

- **4B check passes.** Only `point_aci` reaches the τ bound (0.29–0.40); this is the
  documented failure of a point-forecast controller. The `scenario_aci` and `replay_aci`
  margins stay between −0.03 and 0.10.
- **No exclusions.** No cell has unavoidable daylight violations, so no cell is excluded.
- **4A item 10 failed once more.** With the 4C warm start, urban6's `static_aci` still
  ended development at level index 6.93 (applied cap 0.3, versus 0.4 for `static_dev`).

**Revision of `static_aci`.**

- The pre-evaluation review had already identified the cause: unequal step sizes.
- A violation quarter-hour moved `static_aci` by 0.1 cap level. It moves a τ controller by
  0.01 in τ, and one cap level corresponds to about 0.1–0.3 of τ, i.e. about 0.03–0.1
  levels.
- *Pre-commitment, recorded before the re-check:* `gamma_level` changes from 0.1 to 0.03,
  matching the τ controllers' effective step in level units. If any network still failed,
  there would be no further revision; the failure would be recorded and the run would
  proceed.
- **Result:** all six networks pass. The end-of-development index is 5.56–6.56, and the
  applied cap equals `static_dev` everywhere.

**Why this does not bias H3.** Two revisions of `static_aci` were needed, so it is the
least pre-specified of the simple policies. The H3 criterion does not depend on it alone:
a reliability-aware policy must also beat `static_dev`, `static_beta` and `point_margin`.

No other code, setting or criterion changed. The physics fingerprint is unchanged
(`290e7371…`).
