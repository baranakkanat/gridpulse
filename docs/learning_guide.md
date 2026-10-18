# Learning guide

This guide covers only the concepts this project actually uses, in the order needed to
explain and defend the work. Each section points to the code and the result it supports.

## 1. Forecast errors and why the unit of analysis matters

- **Metrics** (`src/gridpulse/evaluation.py`):
  - MAE = mean |y − ŷ|;
  - RMSE = √mean (y − ŷ)²;
  - WAPE = 100·Σ|y − ŷ| / Σ|y|.
- **What RMSE/MAE tells you.** When RMSE ≫ MAE the errors are heavy-tailed: a few days
  carry most of the squared error. In Phase 1A the 15 worst days held about 55 % of the
  weekly naive's squared error.
- **Dependence.** Hourly errors within a day are strongly dependent. 8,760 hourly pairs
  are not 8,760 independent observations.
  - Every uncertainty interval here resamples **days**, in 7-day blocks
    (`uncertainty.block_bootstrap`).
  - A naive iid test over hours would overstate the evidence by roughly the factor of
    within-day correlation.
- **Questions to be ready for:**
  - Why block bootstrap rather than a t-test?
  - Why 7-day blocks? (Weekly periodicity of load.)
  - What does a 95 % percentile bootstrap interval assume? (That resampling blocks mimics
    the sampling variability of the statistic. It is approximate with one year of data.)

## 2. Leakage and information timing

- **The rule.** A forecast made at origin O may only use observations whose interval
  starts before O. `baseline.seasonal_naive_forecast` enforces this with an explicit
  check.
- **Corruption tests.** The tests overwrite everything from O onward and require
  identical outputs (`test_features.py`, `test_baseline.py`, `test_grid_study.py`).
  - This is the strongest kind of leakage test: it checks behaviour, not code.
  - Mutation checks showed the tests fail when leakage is injected.
- **Model selection is information too.** Early stopping on 2018 means 2018 metrics are
  optimistic for any choice made on 2018. 2019 was inspected in earlier phases, so it is
  no longer a pristine test set.

## 3. Prediction intervals under dependence (Track 1, C3)

- **Split conformal.** With n exchangeable calibration residuals, the
  ⌈(n+1)(1−α)⌉-th smallest absolute residual gives marginal coverage ≥ 1 − α
  (`uncertainty.rolling_conformal_halfwidths`).
- **Exchangeability fails here:** residuals are serially dependent and seasonal. The
  rolling 56-day window is a heuristic for adapting to drift. It inherits no guarantee.
  - Barber et al. (2023) bound the coverage gap by how far the recent window is from the
    test day. Holidays rarely appear in a recent window, so their coverage gap is large.
- **What to inspect besides average coverage:**
  - coverage by lead, by calendar condition and by month;
  - whether misses cluster (the share of fully covered days).
  - A method can be "90 % on average" and still fail most of February.

## 4. AC power flow, per-unit and loading (Track 2)

- **Power-flow equations.** For each bus i:
  - Pᵢ = Σₖ |Vᵢ||Vₖ|(Gᵢₖ cos θᵢₖ + Bᵢₖ sin θᵢₖ)
  - Qᵢ = Σₖ |Vᵢ||Vₖ|(Gᵢₖ sin θᵢₖ − Bᵢₖ cos θᵢₖ)
  - They are solved by Newton–Raphson (pandapower). Non-convergence means no solution was
    found; it must never be read as "safe".
- **Per-unit.** Voltage is reported as |V| / V_nominal. The LV limits here are 0.9–1.1
  p.u.; the 20 kV slack bus is held at 1.025 p.u.
- **Loading.** Both loadings are **current-based** in pandapower.
  - Line loading = max(I_from, I_to) / I_max (270 A cables).
  - Transformer loading = the larger side current × that side's rated voltage, divided by
    S_rated (0.16 MVA). This equals |S| / (|V|·S_rated).
  - So at 1.06 p.u. the reported current-based loading (271 %) is lower than |S|/S_rated
    (287 %).
  - Apparent power is S = √(P² + Q²), so a transformer can be overloaded even when the
    active power alone is below its MVA rating.
  - Reverse power flow is flagged like forward flow, because loading uses current
    magnitude.
- **Voltage rise.** The rise along a feeder is approximately
  ΔV ≈ (R·P + X·Q) / V. PV injection P > 0 raises voltages, and capping PV lowers them.
- **Reverse power flow.** When PV exceeds local load, power flows from LV up through the
  transformer. In the storage-zeroed development runs this is the only violation type
  observed (protocol s. 3.1).
- **Transformer tap.** The SimBench transformer has a +1 HV tap (2.5 %). It lowers LV
  voltage by about 0.025 p.u. and raises LV current. A converter incompatibility silently
  dropped it until it was fixed (protocol s. 3.6b).
  - Lesson: test the physical model against a known reference case (no-load LV voltage),
    not only against the solver itself.
- **Non-monotonicity.** A deeper cap does not always mean lower loading. Once PV falls
  below load, the transformer feeds the load and loading rises again
  (`test_grid_study.py::test_day_physics_reuses_unbinding_caps_and_transformer_loading_is_not_monotone`).
  This is why every cap level is simulated rather than assuming monotonicity.
- **Units.** MW (active), MVAr (reactive), MVA (apparent), MWh (energy = Σ power × 0.25 h
  per quarter-hour). Curtailed energy is MW summed over steps × 0.25 h.

## 5. Scenario-based risk and chance constraints

- **Risk estimate.** rₜ(k) = share of the 28 residual scenarios that violate a limit at cap
  level k (`grid_study.day_risk`). It is a frequency under a stated scenario model, not a
  certified probability.
- **Resolution.** With 28 scenarios the possible values are multiples of 1/28 ≈ 0.036.
  "rₜ(k) ≤ 0.05" therefore means "at most 1 of 28 scenarios violates".
  - The binomial standard error of an estimated probability p is √(p(1−p)/28). It is
    about 0.04 near p = 0.05, as large as the threshold itself.
- **Chance constraint.** Require P(violation) ≤ α.
  - The scenario approach (Campi & Garatti 2008) gives guarantees for *convex* problems
    with *independent samples from the true distribution*.
  - None of these conditions holds here: AC power flow is non-convex, the scenarios are
    residuals of past days, and the season shifts.
  - Hence the registered prediction H3: the realised violation rate on active steps will
    exceed α.

## 6. Calibration of probabilistic events

- **Brier score.** BS = mean (r − y)², where y ∈ {0, 1}. It mixes calibration and
  discrimination.
- **Skill.** BSS = 1 − BS / BS_ref, where the reference is a naive estimate available at
  the same time: the realised violation frequency at the same quarter-hour over the
  previous 28 days. BSS > 0 means better than the reference.
- **Reliability.** Within bins of predicted risk, compare the mean predicted risk with the
  observed frequency. ECE is the size-weighted mean absolute gap.
- **Questions to be ready for:**
  - Why not a reliability diagram? (Too few events in the high-risk bins.)
  - Why is BSS evaluated per day in the bootstrap? (Dependence again.)

## 7. Selective decisions, deferral and fallbacks

- **Deferral.** Defer (escalate to human review) when explicit criteria fire
  (`grid_study.deferral_reasons`):
  - D1: no cap level meets the risk threshold;
  - D2: recent realised violations exceed predictions;
  - D3: a scenario power flow failed.
- **D2 is a one-sided test.** Under correct calibration the realised count *V* is roughly
  Poisson with mean μ = Σ predicted risks. Defer if *V* exceeds the 95 % Poisson quantile.
- **Deferral is not safety.** What happens physically depends on the fallback. The study
  simulates three:
  - robust schedule (no scenario violates);
  - static 70 % cap;
  - no action.
  - With "no action", a deferred risky day is worse than following the model. Any claim
    that "abstention prevents violations" would be false there.
- **Decision passports** (`*_passports.jsonl`) record only what was known at the origin.
  The tests check they do not change when the realised outcome changes.

## 8. What a critical examiner will ask

1. Is the forecast error model realistic? (No: a naive 7-day-mean forecaster on benchmark
   profiles. The study is about propagating uncertainty into decisions, not about forecast
   skill.)
2. Would results change with stricter voltage limits, other grids or real feeder data?
   (Probably; external validity is not claimed.)
3. Why is storage at 0 MW? (The benchmark series are energy-infeasible under the
   pandapower convention; this is documented in protocol s. 3.1.)
4. Were any thresholds tuned on the evaluation period? (No. They were registered before
   the run; α sensitivity is labelled exploratory.)
5. Does deferral reduce violations? (Only under a protective fallback; see the H4
   results.)
6. Is this novel? (As an evaluation protocol and empirical study, moderately. Not as a
   method; see `docs/literature_review.md`.)

## 9. What the experiments demonstrated, and how to explain it

- **Holiday information matters more than model capacity** (Track 1, C2).
  - A three-flag feature reduced holiday-target MAE by over 80 %. The 3,000-round cap
    gained 5 % on 2018.
  - Examiner question: "Was this tested on unseen data?" Only on 2019, which had been
    inspected, so it is exploratory.
- **Average coverage hides structure** (Track 1, C3).
  - The intervals cover about 90 % on average, but 79 % in March 2018, 81 % in December
    2019 and 54 % on the 24 "both holidays" hours of 2019. These are small groups, so read
    them descriptively.
  - Under dependence, report coverage conditionally and by time.
- **Point forecasts fail exactly where it matters** (Track 2, H2a).
  - A 7-day-mean PV forecast averages sunny and cloudy days, so it underestimates the
    sunny-day peaks that cause reverse-flow overloads. The point rule therefore misses
    almost all of them.
  - Propagating the residual spread through AC power flow is what turns a forecast into a
    useful decision.
- **Useful decisions without demonstrated probabilistic skill** (Track 2, H1/H3).
  - The risk scores showed no evidence of skill over recent violation history
    (BSS −0.09 [−0.20, 0.01]; the reference even discriminates better), yet the rules
    built on them cut violations by about 87–95 % compared with no action.
  - Most of that value comes from propagating spread at all; the point forecast had none.
  - Decision value and probabilistic calibration must be evaluated separately.
- **A selective layer is only as good as what its trigger detects** (Track 2, H4).
  - The Poisson monitor fired because realised violations ran 3–5× above prediction for
    the whole PV season. It detected a miscalibrated *regime*, so deferral was on all
    summer and the result equalled "always conservative".
  - Two lessons:
    - a deferral criterion that should target individual days must be tested for exactly
      that (H4a was not supported);
    - overlapping windows and clustered failures make naive Poisson tests behave like
      control charts.
  - With a no-action fallback, deferral *increased* violations. Abstention is a workflow
    decision, not a safety mechanism.
- **Model-fidelity checks catch what unit tests miss.**
  - The silently dropped transformer tap passed every self-consistency test. Only an
    external reference check (the expected no-load voltage) exposed it.
  - Likewise, the benchmark's storage data turned out to decide whether the grid is
    congested at all (4 vs 1,571 violation steps).

## 10. Phase 4 concepts: selection optimism, online calibration, model uncertainty

### 10.1 Why "at most 1 of 28 scenarios violates" does not mean 5 %

**The rule.** Phase 3 picked the *largest* cap whose estimated risk was ≤ 0.05, that is,
at most 1 of 28 scenarios violating.

**Why that is optimistic.** Picking the extreme of noisy estimates selects the estimates
that happen to be too low. This is the optimizer's curse (Smith & Winkler 2006).

**Ideal case.** Even with exchangeable scenarios and violation monotone in the cap:

- the expected violation probability at the chosen cap is 2/29 ≈ 0.069;
- the in-sample estimate is ≤ 1/28;
- for the zero-violation rule the figure is 1/29 ≈ 0.034 (Campi & Garatti 2011).

**How the diagnosis showed it.** It *cross-fitted* the estimate on rural1
(`dual_study.risk_diagnostics`):

- choose the cap with one half of the members and report the risk of the other half;
- on rural1 the held-out risk matched realised violations within about 20 %;
- the in-sample risk was 2.4–3.4× too low.

**Lesson.** A risk number attached to a decision must not come from the same samples that
chose the decision.

### 10.2 Online calibration and what it does not give

**The update** (`dual_study.run_cell`):

- After each day, the planning margin moves: *τ* ← max(*τ*_min, *τ* + γ(*V* − β)), where
  *V* is the number of violating quarter-hours measured on the real grid at the applied
  caps.
- Too many violations widen the margin; quiet days slowly relax it.
- This is adaptive conformal inference / rolling risk control / conformal decision theory
  applied to a decision parameter.

**Strengths:**

- It needs no model of *why* the forecast or the grid model is wrong.
- It uses only outcomes that are actually measured, never counterfactuals.

**Guarantee.** By telescoping, the average of *V* over any *K* days is at most
β + (*τ*_max − *τ*_min)/(γ*K*). This holds for every sequence, but:

- it is a long-run *average*, not a statement about any day;
- with one bad day able to contribute 96 violating steps, the bound is loose (vacuous over
  half a year here);
- a policy can meet its average target and still have an hours-long overload on one day.

Report the worst day and the longest run next to the average.

### 10.3 Physical-model uncertainty

**What the DSO's model may get wrong:**

- the transformer tap position;
- the MV voltage;
- the reactive-power setting of PV inverters;
- what home batteries do.

**Two defences:**

- **Explicit robustness:** check the decision against every plausible model variant. It
  protects exactly against the variants that were listed, and is conservative.
- **Feedback calibration** (s. 10.2): corrects whatever the measurements reveal,
  including errors nobody modelled, but only on average and only after violations have
  happened.

**How to test either honestly:** score decisions on a "true" grid that differs from the
decision model, including variants *outside* the robust set.

### 10.4 Questions to be ready for (Phase 4)

1. *Why scale the PV of five networks?*
   - In their own 2034 scenario they have no violations at all, so there is no decision
     to study.
   - Each is scaled to the same multiple of its own hosting capacity as rural1, by a rule
     fixed before any policy was run.
2. *Is long-run calibration a safety guarantee?* No. See 10.2.
3. *Is the ensemble policy safe?* Only against the listed model variants, and only in this
   simulation.

### 10.5 What Phase 4 demonstrated, and how to explain it

- **Check that the problem exists before studying it.**
  - Five of six benchmark grids had no congestion at all.
  - A study on one hand-picked grid would have generalised from a single example.
  - Scaling the other grids by a rule fixed in advance (equal multiple of hosting
    capacity) gives comparable stress without choosing the outcome.
- **When the model is right, the simple validated rule wins.**
  - A static cap tuned on development data was within 30 % of the oracle and almost never
    violated.
  - Forecast-based rules could not beat it, because the naive forecast has no weather
    information.
- **When the model is wrong, feedback beats foresight.**
  - Rules tuned with a wrong model (one tap step, MV voltage, inverter reactive-power
    setting) failed by hundreds to thousands of quarter-hours.
  - A one-line online update of a margin from measured violations restored the target,
    even without any grid model.
  - The AC model plus replayed measured days added only a few percent of curtailment
    saving on top.
  - **The catch is observation.** The update needs the violation where it happens: remote
    PV buses and mid-feeder cables, not the substation. Without that measurement, the
    "model-free" controller needs a state estimator, which is a model again.
- **Robustness is only as good as its list.**
  - The model-ensemble rule was safe against exactly the variants it listed. Against
    unlisted ones it failed narrowly.
  - The median overvoltage was about 0.001 p.u. (a quarter of a volt at 230 V) and the
    peaks about 0.009 p.u.
  - In one case it failed on loading instead: a 102.9 % overload.
  - It cost 5.4× the curtailment, almost all because of one listed voltage offset.
  - Lesson: a worst case over a list is dominated by its most extreme member.
- **Average targets are not safety.**
  - Online controllers met the average target but had bad days.
  - The static cap had almost no violations under the right model, but under the wrong
    one it produced hours-long runs. The robust rules and the point rule did as badly or
    worse.
  - Always report the worst day, the run lengths and the peak next to averages.
- **Pre-registration costs something and is worth it.**
  - Two revisions of one baseline were needed during development, and both are recorded.
  - The registered H3 count says "genuine value", but the aggregate numbers show how small
    that value is under the correct model.
  - Report both, and let the reader see the gap.

## 11. Phase 5 concepts: observability, state estimation and the value of a sensor

### 11.1 Truth, reading, estimate, plan

Keep four objects apart, and make the code enforce it.

- **Ground truth.** The simulated state of the real grid.
- **Readings.** What the configured sensors report: truth plus noise, sometimes missing,
  sometimes late. In `sensing.py` one function, `measure()`, is the only path from truth
  to readings.
- **Estimates.** What an estimator infers from readings and a model.
- **Plans.** What the controller decides from its own model and forecasts.

A result is only meaningful if the controller never touches ground truth. A test checks
that a violation at an unmeasured bus never changes the controller's behaviour.

### 11.2 Observability is a rank, not a count

**What WLS state estimation does.** It finds the voltage magnitudes and angles that best
fit the measurements, weighted by 1/σ². It needs the measurement Jacobian H to have full
column rank (number of states = 2 × buses − 1).

**Why counts mislead.** Counting measurements is not enough. Ten measurements at the
substation say nothing about a feeder end.

**What Phase 5 found.** The numerical test computes the rank of H at a flat start.

- Substation telemetry alone determined only 9 of 193 to 23 of 257 states in the new
  networks (5 of 29 in rural1).
- Adding pseudo-measurements for every customer bus makes the system observable.
  These are forecasts, with σ from past forecast errors.
- The estimate is then only as good as the forecasts.
- Junction buses without load or generation give "zero-injection" constraints, and must
  be declared. pandapower treats them as very accurate measurements (σ = 0.001), not as
  exact constraints.

### 11.3 Detection: recall, false alarms, and why both matter for control

**The four outcomes.** For each quarter-hour, an avoidable violation either occurs or not,
and is either flagged or not: TP, FP, FN, TN.

- **Recall** = TP / (TP + FN), the share of real violations seen.
- **False-alarm rate** = FP / (FP + TN).

**What a feedback controller does with them.**

- A missed violation leaves the margin too small.
- A false alarm makes it larger than necessary.

**The trap in Phase 5.** With 1 % smart-meter noise and voltages just below the limit,
noise produced false alarms.

- The controller therefore curtailed more, and that extra margin also covered violations
  it could not see.
- Reliability looked better because measurement was *worse*. With exact readings, two
  sensors met the target in 9 cells instead of 14.

**Lesson.** When a controller learns from alarms, report reliability *and* cost under
exact and noisy readings. Then the gain can be traced to information rather than to noise.

### 11.4 The value of a sensor

**The value of information.** It is the improvement in the decision, not in the estimate.
In Phase 5 it was measured as cells meeting the target and as curtailed energy, sensor by
sensor.

**Typical shape: steeply diminishing returns,** as value-of-information theory predicts.

- With noisy readings, the first remote voltage reading recovered most of the gap and the
  fourth added nothing.
- With exact readings, two sensors recovered only about half of it.
- Always check *why* a sensor helps.

**Placement.**

- With noisy readings and two sensors, every rule (feeder end, largest PV, historical
  risk, decision-aware) met the target in the same number of cases.
- With exact readings, decision-aware placement was clearly better (13 vs 9 cells).
- A placement comparison is only meaningful under the measurement conditions it will
  face.
- **Use common random numbers.**
  - When comparing configurations, give the same sensors the same noise realisation.
  - Phase 5 derived its noise seeds from configuration names, so two rules that chose
    identical sensors still "differed", by pure noise. That noise decided the registered
    tie-breaks.
- **What a sensor *measures* matters more than where it sits.** Threshold detection on
  voltages cannot see a cable overload.

### 11.5 Knowing when you do not know

Phase 5 tested three labels.

- **INSUFFICIENT_EVIDENCE: the measurements could not have seen enough.** It is based on
  development coverage.
  - Every configuration it flagged did fail.
  - But "sufficient" did not guarantee success, because coverage under the nominal model
    cannot anticipate violations that only a model error creates.
- **MODEL_INCONSISTENCY: what the substation measures disagrees with what the model
  predicts from metered consumption and generation.**
  - It flagged voltage-offset errors on every day (idealised), even though the same
    telemetry could not see where the limits were violated.
  - Detecting that the model is wrong is a different, and easier, task than detecting
    where the grid is overloaded.
- **NO_FEASIBLE_ACTION: no available action reaches the demanded margin.**
  - It fired in one network when noise-driven alarms had pushed the margin to its bound.
  - At that bound, even switching off all PV could not deliver the margin.
  - The label is right in principle: curtailment cannot fix a voltage offset, re-tapping
    can. But here it was triggered by false alarms.
- **A label is only as good as the signal that triggers it.**

### 11.6 Questions to be ready for (Phase 5)

1. *Why not just install meters everywhere?*
   - Full metering met the target in 15 of 15 cells. Under the correct model, though, it
     curtailed 6× as much as substation-driven feedback, because noisy readings raise
     alarms.
   - With exact readings it curtailed the same as substation-driven feedback.
   - More data needs a better rule for using it, for example a guard band or a
     persistence test.
2. *Does state estimation remove the need for sensors?*
   - It detected most remote overvoltages from substation readings and forecasts.
   - But false alarms rose above the registered limit, so it was not used for decisions.
   - It also inherits every model error it is not told about.
     - Under a wrong PV reactive-power setting it "converged" to a voltage of 1.20 p.u.
       where the truth was 1.055.
     - A bad-data test (chi-square, largest normalised residual) is the standard
       safeguard.
3. *Are these results about a real utility?* No. They come from benchmark networks with
   synthetic profiles and a short list of persistent model errors.

### 11.7 What Phase 5 demonstrated, and how to explain it

- **Substation telemetry is enough for what it measures.** It is not enough for remote
  voltage when the model has a voltage offset.
- **A small number of smart meters recovered most of the reliability, but only with
  noisy readings.**
  - Only in the second half-year, after the controller had learned its margin.
  - With exact readings, about half.
- **Measurement noise interacts with how a controller learns.**
  - It inflated apparent reliability and multiplied curtailment.
  - That finding came from running an "ideal readings" condition next to the realistic one.
  - Without that condition the primary verdict would have been read as a clean success.
- **"Is my model wrong?" is easier to answer than "where is my grid violated?".** It is
  worth asking first.

## 12. Phase 6 concepts: noisy feedback, common random numbers, and what a test can certify

### 12.1 Compare like with like: common random numbers

When two configurations share a sensor, that sensor should report the *same* noise in
both. Then a difference in outcome comes from the configurations, not from luck.

- **What Phase 5 did.** It drew noise from one random stream per run, seeded from the
  configuration's name.
  - Two rules that chose identical meters still "differed".
  - Those differences decided its placement tie-breaks.
- **What Phase 6 does.** It derives each reading's noise from the identity of the
  physical observation: network, truth, quantity, sensor, day, quarter-hour.
  - The derivation uses a stable hash.
  - Python's `hash` is salted per process, so it is not used.

### 12.2 When the noise is bigger than the signal

**The numbers.**

- Simulated voltage violations here exceed the limit by about 0.001–0.014 p.u.
- The study models a smart-meter reading as uncertain by 0.01 p.u., independent per
  reading. That is a pessimistic value: specifications bound it at about 0.008 p.u. or
  below.

**Why no single-reading rule works.**

- *Unfiltered:* every noisy exceedance is an alarm. A count-based controller then
  curtails until no meter reads near the limit. That is safe-looking and expensive.
- *Guard band* (alarm above limit + 2σ): false alarms vanish, but so do most real
  violations.

**Averaging or persistence helps against independent noise** (√n). It fails in two
cases:

- *against bias*: a meter that reads 0.01 p.u. high does so every time;
- *against short events*: here most closed-loop violations last under 45 min, so a
  45-min persistence rule cannot see them with exact readings.

**Lesson.** Always run the "exact readings" condition next to the noisy one. If a method
does better with noise than without, part of what it does is driven by the noise.

### 12.3 What a residual test can and cannot tell you

**What a chi-square test checks.** A WLS state estimate passes when its weighted
residuals look like noise. With only substation measurements here, that checks just one
thing: does the measured transformer P and Q match the sum of the forecast injections?

**What it catches and what it misses.**

- It catches a wrong inverter reactive-power setting, because Q does not balance. Late
  in the year, with little PV, it can miss even that: in one network only 51 % of
  December estimates were flagged.
- It is blind to a wrong tap or MV voltage: the estimator absorbs the offset.
- It is blind to a large error at one customer when the totals balance.

**Lesson.** "Converged" and "passed the bad-data test" are not evidence that the state
is right.

### 12.4 Questions to be ready for (Phase 6)

1. *Did fixing the seeding change Phase 5?* No: 14 cells and about 145 MWh before and
   after. It did make Phase 5's placement tie-breaks meaningless.
2. *So is noise-aware feedback solved?*
   - The cost under the correct model is, for independent per-reading noise: 55 MWh
     against 53 MWh with exact readings. Under per-meter bias it is not.
   - Reliability under model errors still borrows from noise.
   - The next step is a feedback signal that estimates how far the voltage is from the
     limit, not whether a reading crossed it.
3. *Should a utility install more meters?*
   - In this benchmark, two well-placed meters gave most of the value.
   - Their accuracy, and especially their bias, decide whether that value is real.
