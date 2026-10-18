# Phase 7 protocol: continuous model-residual correction versus binary alarm feedback

**Status.** Registered before the Phase 7 development and evaluation stages. SHA-256 of
this file and of the code are in `docs/provenance/phase7/registration_log.txt`; later
changes are dated amendments at the end.

**Identity.**

- Phase 7 is an **exploratory replication**.
- The six SimBench LV networks, the 2016 profiles, both half-years, the four model truths
  and the sensor placements have all been examined in Phases 4–6.
- No unexamined SimBench LV network exists: the catalogue holds exactly these six `--2-sw`
  networks.
- New noise realisations are not independent evidence.
- **No result of this phase is confirmatory** (s. 9).

## 1. Question

**Primary.** Phases 5–6 fed the planner a *binary* signal: the daily count of quarter-hours
whose readings crossed a limit. Can a *continuous* signal improve decisions under limited
observability and model mismatch? The signal is the residual between measured substation
quantities and the nominal model's prediction for the same metered injections and applied
caps.

**Primary hypothesis (H1).** Continuous model-residual correction using **substation
telemetry only** (C1) has:

- (a) fewer avoidable violations under the model-error truths than binary feedback with
  **two remote meters and exact readings** (B3); and
- (b) correct-model curtailment within 10 % of binary substation feedback (B2).

**Secondary questions.**

- Is the method insensitive to meter noise (H2)?
- Can a physically grounded consistency check stop biased meters from steering it (H3)?
- Is the correction itself the active ingredient (H4)?
- Does the model-error evidence label behave as defined (H5)?
- Descriptively: where is the information? What can and cannot be observed? How do
  measurement intervals cover the truth under noise and under bias?

## 2. Why this question (Phase 6 starting point)

- Binary alarms from noisy meters cause noise-driven over-curtailment.
- Persistence filters hide short violations.
- Per-meter bias defeats reading-level filters.
- 77 % of the remaining violations are at unmetered buses.
- Phase 5 had already shown that the substation busbar-voltage residual flags tap and
  MV-voltage errors on every day. That information was used only as a label, never in the
  decision.
- A tap or MV-voltage error shifts every LV voltage by nearly the same amount.
  Development check: rural3 under MV 1.055, the true-minus-nominal overvoltage exceedance
  is 0.0295–0.0310 p.u. at every cap level.
- A correction estimated at the substation therefore also applies at unmetered buses.
- A PV reactive-power error changes currents. The transformer and feeder-head current
  residuals measure that.

**Prior art** (`docs/phase7_literature.md`).

- **The method is not new.** The correction is the classic offset-free MPC / DMC bias
  update (Muske & Badgwell 2002; Pannocchia & Rawlings 2003), with a fixed back-off.
- **Substation-only estimation of LV voltages exists** for OLTC control (Procopiou & Ochoa
  2017).
- **Not found in a targeted search:**
  - day-ahead LV PV caps corrected by substation-residual offsets;
  - a comparison of that approach with binary-count feedback.
- **The possible contribution is therefore** an empirical benchmark comparison plus the
  identifiability split between common-mode and local model errors. It is not a method.

## 3. Information layers and timing

- **Ground truth:** the simulated true state (`fullstate`, Phase 4 cache). It is read only
  by the scorer, by `sensing.measure` to produce readings, and by the evaluator-side
  observability and coverage analyses.
- **Measurements:** readings from `sensing.measure` with identity-based noise
  (`NoiseBank`, Phase 6), missing meter-days and reporting delays.
- **Model / estimates:** the operator's nominal model evaluated at the metered injections
  and the applied caps. These are the same information Phase 4 replay planning and the
  Phase 5 consistency label use. The `ResidualCorrector`'s estimates come from model and
  measurements only.
- **Forecast:** the 28-day replay of past days through the (corrected) model, unchanged.
- **Timing:**
  - Caps for day d are decided at 00:00 UTC of day d.
  - Substation readings of day d (quarter-hour values) are used from day d + 1.
  - Meter readings of day d are used from day d + 1 + delay (delay 1 day when
    realistic).
  - Metered injections of day d are available at 00:00 of day d + 1, the Phase 4/5
    assumption. They are needed for the nominal prediction.
  - Estimates are medians of the last 7 available daily values.
  - An action affects only its own day.
  - Tests check that readings of day d cannot affect any decision before d + 1
    (d + 2 for delayed meters).

## 4. Constraints and margins

**Signed margins** (`margins.py`), positive inside the limits:

- voltage m_V = min(V_max − V, V − V_min), in p.u.;
- loading m_I = 100 − loading, in % of rating (all limits are 100 % here).

**Derived quantities.**

- Violation magnitude: max(−m, 0).
- Duration: the length of a violated run in quarter-hours.
- Frequency: violated quarter-hours.
- Severity: the Phase 4 sum of positive normalised margins, reported with its unit
  convention (0.1 p.u. ≙ 100 %). It is never presented as a physical safety score.

The Phase 4 cache stores *exceedances* (−m). Voltage and loading are never added.

## 5. Methods

All policies use the same planner family (28-day replay of the nominal model, Phase 4),
the same action set (one uniform PV cap level per quarter-hour, 11 levels), the same days,
timing and, for shared sensors, the same noise.

**Strong baselines (Phases 5–6 implementations, unchanged).**

| ID | Policy |
|---|---|
| static_dev | Development-tuned static cap (open loop) |
| B2 / B2x | Binary count feedback (ACI margin), substation telemetry; realistic / exact readings |
| B3 | Binary count feedback, substation + 2 topology meters, exact readings: the information-value reference |
| B4 / B5 / B6 | Binary feedback, + 2 meters, realistic readings: unfiltered / persistence on meters (Phase 6 primary) / guard band |
| B7 | Binary feedback, every bus and line measured, exact readings (full-information reference) |
| R0 / Rdev | Replay planner with no feedback: margin 0 / the development-tuned margin of C1 (isolates the correction) |
| oracle | True grid, unattainable; for interpreting the gap |

**Candidates (`margins.ResidualCorrector`).** After each day, the residuals of available
readings against the nominal model at the applied caps give daily estimates:

- **v̂:** the daylight mean of the busbar-voltage residual, p.u.
- **ρ_trafo, ρ_line:** the median measured/predicted − 1 of transformer and feeder-head
  currents, where the model predicts at least 20 % loading. For lines, the worst head is
  used.
- **Combination:** the estimate in force is the median of the last 7 daily values,
  clipped to |v̂| ≤ 0.05 p.u. and |ρ| ≤ 0.3.
- **Planning correction:** the replayed nominal exceedances are corrected (overvoltage
  + v̂, undervoltage − v̂, loading × (1 + ρ)). The plan then takes the least curtailment
  whose corrected worst case keeps a fixed safety margin s.
- **The safety margin s** is tuned per network on development days from the nominal
  model alone. It is the smallest s on {0, 0.02, …, 0.40} for which the nominal model's
  own replay plan would have kept ≤ β = 0.1 avoidable violations per day
  (`margins.tuned_safety_margin`; development values 0.02–0.04).
- There is no count feedback in C1 and C3.

| ID | Telemetry and use |
|---|---|
| **C1 / C1x** | Substation only; realistic / exact readings. **Primary candidate** |
| C3 / C3x | + 2 topology meters, *checked*. A meter's 7-day residual is used only if it lies within 0.005 p.u. of the busbar residual. Consistent meters can only raise v̂ (v̂ = max(busbar, meters)) |
| C3_1, C3_4, C3full | As C3 with 1, 4 or all meters (realistic): sensor value under the continuous method |
| C3b / C3nb | + 2 meters under matched per-meter bias (`biased_meters_matched`, total u = 0.01 p.u.), *checked* / *naive* (unchecked), 5 bias draws each |
| C4 | Hybrid: correction (margin 0) plus the Phase 6 count feedback with `persist3_meters` on + 2 meters, realistic |

**The meter consistency check, and why bias is often not identifiable.**

- A remote voltage is not expected to equal the busbar voltage; the model accounts for
  the drop. The check compares a meter's *residual* against the model with the busbar's
  *residual*.
- A difference is either meter bias or a local model error (one not common to the whole
  feeder). The two cannot be told apart from these measurements.
- Hence the labels (s. 8). No bias is ever estimated or subtracted.

**Noise and bias conditions** (Phase 6 definitions, unchanged).

- `exact`.
- `realistic`: meter σ 0.01 p.u. independent per reading (the pessimistic end of
  specifications), busbar 0.002 p.u., currents 1 %, 5 % missing meter-days, 1-day meter
  delay.
- `biased_meters_matched`: meter random 0.002 plus a per-meter bias with σ 0.0098 p.u.
  (total 0.01).
- These are assumptions, not KIB-TEK or any utility's meter specifications.

## 6. Metrics

**Primary (per run, scored daylight).**

1. Avoidable violation quarter-hours under the mismatch truths (frequency).
2. Curtailed energy (MWh) under the correct model, and also under the mismatch truths.

**Secondary.**

- Cells meeting β (≤ 0.1 avoidable violation quarter-hours per day).
- Severity; long runs (≥ 1 h); the worst day.
- Unneeded curtailment: MWh on days with no avoidable violation at no action.
- Interventions: daylight steps with a binding cap.
- Alarm counts (binary policies).
- Estimates v̂ and ρ.
- Evidence-label frequencies.
- Runtime.

**Descriptive, evaluator-side.**

- Observability classes of the violations at no action: substation-observable,
  at a metered bus, unmetered voltage only, unmeasured line only.
- Empirical coverage of reading ± 2u and of the daily mean ± 2u/√n intervals, under
  independent noise and under bias.

Pareto views of violations against curtailment are reported per truth group. No composite
score is used.

## 7. Hypotheses and decision rules

All rules are evaluated in the **evaluation** stage, on the five new networks, noise
replication 0. Sums run over networks; "mismatch" means the tap, MV and fixed-cos φ
truths.

| ID | Rule |
|---|---|
| **H1** (primary) | (a) Σ mismatch violations of C1 < those of B3, **and** (b) Σ nominal curtailment of C1 ≤ 1.1 × that of B2. Met only if both hold |
| H2 | Noise invariance: \|viol(C1) − viol(C1x)\| ≤ 0.1·viol(C1x) + 10 **and** \|MWh(C1) − MWh(C1x)\| ≤ 0.05·MWh(C1x), nominal MWh |
| H3 | Bias check: (a) the nominal MWh of C3b is ≤ 1.1 × that of C1 in all 5 bias draws, **and** (b) the nominal MWh of C3nb is > 1.1 × that of C1 in at least one draw |
| H4 | The correction is active: Σ mismatch violations of C1 ≤ 0.2 × those of Rdev |
| H5 | Label: PHYSICAL_MODEL_UNCERTAINTY on ≥ 90 % of days under the tap and MV truths in every new network, and on ≤ 5 % under the nominal truth in every new network |

**Reported without decision rules:**

- cells meeting β for every policy;
- per-network and per-truth tables;
- paired daily differences (C1 − B3, C1 − B2, C1 − Rdev, C1 − C1x, C3 − C1, C1 − B5)
  with circular block-bootstrap intervals at 7, 14 and 28 days;
- H1 for noise replications 1–4;
- C4 and the sensor-count variants;
- the observability classes and coverage;
- the development stage.

## 8. Evidence labels (operational definitions; not safety certificates)

These are per decision, from information available at decision time
(`margins.evidence_label`):

- **NO_VERIFIED_FEASIBLE_ACTION:** no cap level satisfies the corrected planning margin.
- **INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS:** a meter's residual disagrees with the
  busbar residual by more than 0.005 p.u. while the substation residuals also indicate a
  model error. Bias and a local model error are confounded.
- **MEASUREMENT_MODEL_INCONSISTENCY:** such a disagreement while the substation residuals
  show no model error (meter bias suspected).
- **PHYSICAL_MODEL_UNCERTAINTY:** |v̂| > 0.005 p.u. or |ρ| > 0.05.
- **EVIDENCE_SUFFICIENT_FOR_DEFINED_ANALYSIS:** none of the above.

INSUFFICIENT_MEASUREMENT_COVERAGE is the Phase 5 configuration-level label. It is not
recomputed here.

## 9. Statistics and validity

- Paired comparisons share days, noise and timing.
- Block bootstrap of mean daily differences at 7, 14 and 28 days; descriptive.
- Cells and networks are not independent replications, and nothing is a significance test.
- This is an exploratory replication on examined data. The decision rules were formulated
  after the development probe (s. 11), with the ORIGINAL Phase 5/6 evaluation results
  known.
- **H1 is a test of a mechanism on these benchmarks, not evidence for real feeders.**

## 10. Procedure and budget

1. Register this protocol.
2. Development stage, then review:

   ```bash
   uv run python -m gridpulse margin-study --stage development --output-dir outputs/margin_study
   ```

3. Freeze:

   ```bash
   uv run python -m gridpulse margin-study --stage freeze --output-dir outputs/margin_study
   ```

4. One evaluation:

   ```bash
   uv run python -m gridpulse margin-study --stage evaluation --output-dir outputs/margin_study
   ```

**Setup and budget.**

- No new power flows: the Phase 4/5 caches are reused, with fingerprints checked on load.
- About 12 s per (network, truth) task; 24 tasks per stage.
- The guarded stages, manifests and freeze are those of Phase 6 (`runguard`).
- Placements are the frozen Phase 6 development design (`outputs/noise_study/
  development_results.json`); its hash is recorded in the stage identity.

## 11. What was seen before registration

The development-only probe (`docs/provenance/phase7/scripts/development_probe.py`) read no
evaluation day. Totals over the five new networks, development half (learning phase):

| Policy | Mismatch violations | Correct-model curtailment | Mismatch cells met |
|---|---|---|---|
| B2 | 15858 | 86.7 MWh | 0 |
| B3 | 1495 | 86.1 MWh | 0 |
| B7 | 472 | 87.7 MWh | 1 |
| Rdev | 17257 | 90.3 MWh | 1 |
| **C1** | **166** | **91.0 MWh** | **9** |
| C1x | 163 | 90.3 MWh | 10 |

- **Margin drift.** A first variant kept the ACI count feedback on substation alarms. τ
  drifted to its lower bound (about −0.01 p.u.), because the substation never sees remote
  violations. That variant was replaced by the fixed development-tuned margin. Phase 5/6
  substation feedback has the same drift.
- **Biased meters** (`biased_meters_matched`), correct-model curtailment: naive 182.5 MWh,
  against 91.0 checked.

---

## Amendment 7A (2026-10-18, before any freeze or evaluation)

**Why.** Two independent pre-freeze reviews (code and leakage; physics, measurement and
design) examined the registered protocol, the code and the first registered development
stage. That stage is archived unchanged in `outputs/margin_study/development_v1/`.
Neither review found a defect in the runs behind H1–H5. The changes, each prompted by
development data or by the reviews:

1. **Defect: full metering never estimated a line-loading ratio.** The full configuration
   reports `line_loading`, not `head_loading`, so ρ_line stayed 0. The corrector now
   uses every measured line current: feeder heads, and with full metering all lines,
   taking the worst ratio. Only C3full changes.
2. **Finite-value guards.** A failed flow (NaN) at a daylight step is skipped rather than
   averaged. Otherwise it would make the 7-day median NaN for a week. None occurred on
   development days.
3. **Evidence labels follow s. 8.** The model-error part is now decided on the
   *substation* residuals (busbar-only v̂ and ρ), not on a v̂ raised by meters. It
   affects only C3 labels.
4. **Observability classes.** Busbar overvoltage now counts as substation-observable.
   Events that are neither overvoltage nor line or transformer overload are counted as
   "other". This is evaluator-side only.
5. **Noise-paired replication rows.** B2 is also run for noise replications 1–4.
6. **Busbar voltage-transformer bias sensitivity.**
   - The busbar reading gets a fixed offset b ∈ {−0.005, −0.002, +0.002, +0.005} p.u. These
     are the IEC class 0.2 and 0.5 ratio-error limits, the values the reviewer gave
     (`MeasurementModel.bias_v_substation`).
   - C1 and C3 run under each value.
   - Reported per b: H1(a), H1(b), mismatch MWh, cells, nominal flag rates and
     no-feasible days.
   - There is no decision rule. **Pre-stated claim rule:** "robust to busbar accuracy" may
     be claimed only if H1(a) and H1(b) both hold at b = −0.002.
   - Any busbar bias passes one-for-one into v̂ and cannot be told apart from a
     common-mode model error.
7. **No-margin comparison.** C1s0 (realistic, s = 0) is added.
   - **Pre-stated claim rule:** "fewer violations than two exact meters" is reported as a
     trade-off together with the mismatch curtailment, unless C1s0 beats B3 on both
     mismatch violations and mismatch curtailment.
   - C1 against Rdev is reported as the clean cost of the correction.
8. **Injection-availability sensitivity.**
   - C1lag uses each day's residuals one day later (d + 2), as if the metered injections
     arrived with the meters' voltage delay.
   - C1's feedback signal itself depends on the metered injections. The binary baselines
     use them only for the replay. They are exact and complete here.
9. **Wording and units.**
   - H2 concerns *substation* noise: C1 uses no meters. H2 compares mismatch violations
     and nominal MWh.
   - The "77 %" in s. 2 means steps seen by no sensor (unmetered buses or unmeasured
     lines).
   - Normalised margins: 0.01 = 0.001 p.u. of voltage = 1 percentage point of loading. So
     s = 0.02 means 0.002 p.u.
   - **H2, H4 and H5 are implementation checks,** passing almost by construction here:
     busbar noise averages to about 0.0003 p.u. against offsets of about 0.03. They are
     not evidence for the method.
   - **Label definitions, narrowed:**
     - PHYSICAL_MODEL_UNCERTAINTY: substation residuals beyond the thresholds. That is a
       model error *or* substation measurement bias; the two cannot be distinguished.
     - EVIDENCE_SUFFICIENT_FOR_DEFINED_ANALYSIS: the substation residuals are small. It
       says nothing about local errors at unmetered buses.
     - NO_VERIFIED_FEASIBLE_ACTION: no cap level satisfies the corrected planning margin
       (checked against the model only).
10. **Limits stated now** (report only; new truths would need new power flows). Every
    tested error is in the easy direction for a uniform correction:
    - **Positive offsets** over-protect slightly, because the PV voltage rise scales with
      1/V.
    - **Untested:**
      - negative offsets (tap lowered, low MV), which would under-correct by about half of
        s in three networks;
      - a reversed PV reactive-power error;
      - MV voltage varying within the day (a 7-day median of daylight means misses a
        midday peak);
      - cables loaded beyond the worst feeder head's ratio;
      - voltage-dependent loads and inverter Q(U) or P(U).
    - A distributed error also leaks into the "common-mode" estimate, which blurs the
      common-mode/local split.

**Procedure.**

- The first development stage's files are moved, unmodified, to
  `outputs/margin_study/development_v1/`.
- The development stage is re-run with this code and protocol.
- Before the freeze, every run summary present in both development stages must be
  identical, except C3full, the labels of C3 runs and the observability counts.
- Then freeze and evaluate.
