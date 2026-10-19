# Phase 8 protocol: constraint-specific reserves and realistic data availability

**Status.** Registered before any Phase 8 experiment. Hashes are recorded in
`docs/provenance/phase8/registration_log.txt`. Amendments are allowed only before the
freeze, and each one is logged with a reason.

**Identity.**

- Experiment: `phase8-robust-study`; outputs in `outputs/robust_study/` (git-ignored).
- This is a **mechanism study and exploratory replication on previously examined data.**
  - The six SimBench LV networks, the 2016 profiles, both half-years and four of the
    truths were examined in Phases 4–7.
  - A new protocol or seed does not make them independent.
  - No independent LV benchmark with compatible physics was found:
    - SimBench offers no further LV networks of this kind;
    - OPSD and ENTSO-E data are national aggregates without feeder physics;
    - real feeder data are not available.
  - **No result here is confirmatory, and none is evidence about a real feeder.**

## 1. Research questions

- **RQ1.** Can physically separate voltage and loading reserves reduce curtailment
  while keeping the reliability of the Phase 7 substation-residual correction (C1),
  under model and measurement uncertainty?
- **RQ2.** How sensitive are the corrected policies to:
  - incomplete or erroneous customer injection data;
  - imperfect substation instrumentation;
  - model errors not tested in Phase 7?

## 2. What was seen before registration

- All Phase 4–7 results, both half-years.
- A development-only diagnosis of Phase 7's C1, C1s0, Rdev and R0, classifying their
  violations by constraint type
  (`docs/provenance/phase8/scripts/diagnose_types.py`):
  - Under the correct model every violation is a loading violation (transformer in the
    rural networks, cables elsewhere).
  - Under tap and MV errors, every violation that remains after correction is an
    overvoltage.
  - The shared margin cuts the overvoltage violations 2–10-fold. It costs up to 58 MWh
    per network over the development half.
  - The remaining violations come from the replay's forecast error while PV rises. They
    do not come from the offset estimate.
- Topology-only facts used to fix the stress cases (s. 6):
  - the selected cable per network;
  - load reactive-power ratios (cos φ 0.97–0.98; rural1 0.92);
  - transformer tap ranges.
- The Phase 8 literature review (`docs/phase8_literature.md`). Separate margins are
  established; no method is claimed.

## 3. Decision timing and information

The caps of day d are decided before day d. Allowed inputs:

- **Metered customer injections** of days ≤ d − 1 − D. D = 0, except in the delay
  condition I5.
- **Substation readings** of days ≤ d − 1 − L. L = 0, except in S3.
- **Remote meter readings** with their reporting delay (B3 only).
- **The operator's nominal model:** the Phase 4 solver and the asset register, at the
  metered injections.

**Never allowed:** the true model, true states or true margins. These are used only to
generate readings and to score. The oracle is the unattainable exception.

## 4. Networks, data and periods

- **Networks.** As Phases 4–7: SimBench LV rural1 (development network), rural2, rural3,
  semiurb4, semiurb5 and urban6, with the Phase 4 PV scaling.
- **Profiles.** SimBench 2016.
- **Development half:** 2016-02-05 – 06-30 (147 scored days).
- **Evaluation half:** 2016-07-01 – 12-30 (183 days).
- Totals are over the five networks other than rural1.

## 5. Margins and reserves

**Signed margins** (unchanged from Phase 7):

- voltage: m_V = min(V_max − V, V − V_min), in p.u.;
- loading: m_L = 100 − loading, in % of rating.

**Planning.** The planner replays the corrected nominal exceedances of the past 28 days
(Phase 7: overvoltage + v̂, undervoltage − v̂, loading × (1 + ρ)). It takes the least
curtailment for which every replayed constraint keeps its reserve:

- **Shared margin (C1, C1s0, C1f):** the Phase 7 rule. One normalised s means 0.1·s p.u.
  on voltage and 100·s % on loading.
- **Separate reserves (C5, C5L, C6):**
  - r_V (p.u.) is added to both voltage exceedances;
  - r_L (percentage points) is added to both loading exceedances;
  - the result is normalised and maximised as before.
  - Units are never added.

**Grids.**

- G_V: 0 to 0.010 p.u. in steps of 0.0005 (21 values).
- G_L: 0 to 10 % in steps of 0.5 (21 values).
- Phase 7's shared grid (0–0.40 in steps of 0.02) is coarser by a factor of four, so a
  fine shared-margin control (C1f) is included (s. 7).

**Requirement.** As in Phases 4–7, β = 0.1 avoidable violation quarter-hours per day per
cell.

## 6. Conditions

### Truths

| Truth | Definition | Physics |
|---|---|---|
| nominal, tap_raise_lv, mv_high, pv_fixed_095 | **Primary truths**, as in Phases 5–7 | Phase 5 full-state cache |
| tap_lower_lv | **Opposite-direction tap error:** tap +1, LV about −2.5 % (a Phase 4 variant) | New full states; their margins must equal the Phase 4 cache bit for bit |
| mv_daily | **Time-varying MV voltage:** slack voltage = nominal + 0.03·g(t). g(t) is the network's available PV divided by its PV rating, per quarter-hour (same weather). It peaks at SimBench's high-PV study-case value (1.055 at full PV). Stylised | New full states |
| line_local | **Wrong cable type in the records:** one cable is installed one cross-section smaller than recorded, so R × 1.5 and thermal rating × 0.8. The cable is the non-head line with the largest downstream installed PV × resistance. Stylised | New full states |

### Customer injection data

Each condition changes the operator's metered injections. The operator's nominal model
is re-solved at them (plan exceedances and residual reference alike), for days 7–364.

| ID | Condition |
|---|---|
| I0 | exact metered injections (Phases 5–7) |
| I1 | meter noise: each load P, load Q and PV P value × (1 + 0.02·z), z standard normal, independent per element and quarter-hour (identity-seeded) |
| I2 | load reactive power not metered: assumed Q = P·tan(arccos 0.95), inductive |
| I3 | PV generation recorded 5 % high (systematic). It tightens the replayed plan and relaxes the residual correction; the net effect is not known in advance |
| I4 | missing data: each day, each load and each PV unit is missing independently with probability 0.10 (identity-seeded). The fallback is the same element's values 7 days earlier (from day 14; earlier days complete). This is a documented pseudo-measurement |
| I5 | delay: injections of day j are available only after day j + 2 (D = 2). The plan window and the residuals shift by two days. No new physics |

### Substation instrumentation (readings only)

| ID | Condition |
|---|---|
| S0 | realistic, as in Phases 5–7: σ 0.002 p.u. busbar voltage, 1 % currents |
| S1 | busbar bias b ∈ {−0.005, −0.002, +0.002, +0.005} p.u. (Phase 7 conditions) |
| S2 | noisy substation: σ 0.005 p.u. voltage, 2 % currents |
| S3 | delayed substation readings: day j is usable from day j + 3 (L = 2) |
| S4 | missing substation days: each day missing independently with probability 0.2 (identity-seeded). No residual update that day |

**Tuning data.** Under I1–I5 every tuning (static cap, shared margins, reserves) uses the
metered data, because that is all an operator has. The tuned values are recorded.

## 7. Policies

| ID | Policy | Information |
|---|---|---|
| static | development-tuned static cap (open loop) | design-time data only |
| B2 | binary count feedback, substation, realistic | substation |
| B3 | binary count feedback, + 2 topology meters, **exact** readings | substation + 2 meters |
| C1 | Phase 7 residual correction, shared margin on the Phase 7 grid | substation + metered injections |
| C1s0 | as C1, no margin | as C1 |
| C1f | as C1, shared margin tuned on the fine grid (0 to 0.10 in steps of 0.005) | as C1 |
| **C5** | **as C1, separate fixed reserves (r_V, r_L) tuned once on development days** | as C1 |
| C5L | as C5 with r_V = 0 (decomposition) | as C1 |
| C6 | as C1, separate reserves re-tuned every day on the last 28 days of the operator's corrected model | as C1 |
| oracle | the true grid | unattainable |

**C5 tuning.** It uses development days and the operator's nominal model only, with the
Phase 7 rule (smallest grid value with at most β avoidable violations per day, judged
against the model's own realised exceedances). Each type is tuned alone:

- **r_L:** loading constraints only.
- **r_V:** voltage constraints only. All voltage exceedances are first shifted by one
  tap step, Δ = +0.025 p.u. (undervoltage −Δ), because the correction is designed to
  remove such offsets.
  - Under the correct model, voltage never binds, so a voltage reserve tuned there would
    always be 0.
  - Δ is a design assumption: the smallest common-mode error the method targets.

**C6 rolling tuning.** On each decision day d, using the estimates (v̂, ρ) in force at d:

- The window is W = {w : max(35, d − 28 − D) ≤ w ≤ d − 1 − D}.
- Each type k gets the smallest grid value r_k for which the corrected replay with
  reserve r_k on type k would have had at most β·|W| avoidable type-k violations over W,
  judged against the corrected model's own realised exceedances on those days.
- If |W| < 7, the grid maxima are used, as a conservative start.
- No truth is used.

The Phase 7 hypothesis tested here: an adaptive reserve might keep reliability without
the spring-tuned cost.

### Run plan

- Primary truths, I0, S0: all policies. Noise replications 1–4 for B2, C1, C5 and C6.
- Stress truths, I0, S0: all policies.
- Primary truths, I1–I5, S0: B2, B3, C1, C5, C6.
- Primary truths, I0, S1–S4: C1, C5, C6, plus B2 under S1 and S2.
  - B2 is not run under S3 and S4: the Phase 5 alarm loop has no delay or outage for
    substation alarms.

## 8. Metrics

**Primary** (per cell, totals over five networks, reported per network too):

- avoidable violation quarter-hours;
- violations split by type (voltage, loading);
- severity (sum of normalised exceedance);
- long runs (≥ 1 h);
- largest single-step exceedance;
- curtailed MWh;
- cells meeting β.

**Secondary:**

- intervention quarter-hours;
- curtailment on days with no avoidable violation at no action;
- tuned reserves;
- runtime.

**Reporting.** Always the pair (violations, MWh). No composite score.

## 9. Hypotheses and decision rules

**Notation.** MIS = {tap_raise_lv, mv_high, pv_fixed_095}; NOM = {nominal}. Totals are
over the five networks, under I0, S0, replication 0, in the evaluation half unless
stated.

**Strict non-inferiority**, NI(X vs Y), requires all four:

- Σ_MIS violations(X) ≤ Σ_MIS violations(Y) + 15;
- Σ_MIS long runs(X) ≤ Σ_MIS long runs(Y) + 1;
- MIS cells(X) ≥ MIS cells(Y);
- Σ_NOM violations(X) ≤ Σ_NOM violations(Y) + 5.

The margin of 15 is about one quarter-hour per mismatch cell per half-year, which is 5 %
of β. It is deliberately strict, because C1 has 1 mismatch violation. A policy that only
meets β in every cell, without NI, is reported as a **trade-off within the requirement**,
not as maintained reliability.

**H1 (primary, RQ1).** C5 meets NI(C5 vs C1), **and** Σ_MIS MWh(C5) ≤ 0.90 ×
Σ_MIS MWh(C1), **and** Σ_NOM MWh(C5) ≤ Σ_NOM MWh(C1).

- The 10 % threshold: the whole Phase 7 margin cost under mismatch was 19 % of C1's
  curtailment (C1 against C1s0), so 10 % means recovering more than half of it.
- **Attribution:** separation is credited only if C5 meets H1 and C1f does not meet the
  same rule. If both meet it, the gain is attributed to the finer resolution.

**H2 (secondary, RQ1).** C6 meets NI(C6 vs C1) **and** Σ_MIS MWh(C6) ≤ 0.90 ×
Σ_MIS MWh(C1) **and** Σ_NOM MWh(C6) ≤ 0.90 × Σ_NOM MWh(C1), in the evaluation half.

- The evaluation half has falling PV, which favours an adaptive reserve. So H2 is
  claimed only if NI(C6 vs C1) **also holds in the development half** (rising PV).

**H3 (RQ2, injection data).** For each condition c in I1–I5:

- robust(X, c) requires: MIS cells ≥ 14 of 15, NOM cells = 5 of 5, and Σ_NOM MWh(X, c) ≤
  1.1 × Σ_NOM MWh(X, I0). Reported for X in {C1, C5, C6, B3}.
- "Benefit survives" (only if H1 is met) requires NI(C5, c vs C1, c) and Σ_MIS MWh(C5, c)
  ≤ 0.90 × Σ_MIS MWh(C1, c).

**H4 (RQ2, instrumentation).** robust(X, s) as in H3, for each condition s in S1–S4 and X
in {C1, C5, C6}.

**H5 (RQ2, stress truths).** covers(X, truth) means at least 4 of the 5 networks meet β.
Predictions, written before any new physics is computed:

- **tap_lower_lv:** C1, C5 and C6 cover it.
- **mv_daily:** the substation-residual policies do **not** cover it. The daylight mean
  under-corrects the midday peak.
- **line_local:** the substation-only policies do **not** cover it in networks where the
  error creates avoidable violations, because the substation cannot see it. B3 covers it
  only where a meter lies downstream of the cable.
- The no-action violations created by each stress case are reported, so that a trivial
  "cover" can be recognised.

## 10. Statistics

- Paired day-level circular block bootstrap of C5 − C1, C6 − C1 and C5 − B3, per cell,
  for violations per day and MWh per day, with 7-, 14- and 28-day blocks.
- Noise replications vary only the noise.
- The cells share days and profiles, and the five networks are not independent
  replications.
- No significance claim.
- Development-half results are reported alongside.

## 11. Stages, reproducibility and compute

**Stages** (`python -m gridpulse robust-study --stage …`):

1. `physics`: new full states into `outputs/robust_study/fullstate_cache/`, with a
   manifest per network and condition.
   - Estimate: about 1.5–5 min per network and condition, so about 1–1.5 h.
   - Bounded to 3 workers at nice 19; about 1.6 GB of disk.
   - A condition whose flows fail to converge in more than 1 % of cases is reported and
     dropped.
2. `development`, then 3. `freeze`, then 4. a single `evaluation`. All are guarded by
   `runguard` as in Phases 6–7.

**Recorded:** code, protocol and dependency hashes, physics fingerprints, seeds (identity
hashing), conditions, tuned reserves, periods and runtime.

**Before the freeze, the development stage must show that:**

- C1 under I0/S0 reproduces the frozen Phase 7 development C1 summaries;
- the tap_lower_lv margins equal the Phase 4 cache;
- every stress case creates avoidable violations at no action in at least one network.

**Phase 4–7 outputs and caches are read, never written.**

## 12. Deviations

Any change after registration is logged in the registration log as an amendment, with
the reason, before the freeze. After the evaluation, only reporting may change. Any code
change is logged with replay evidence, as in Phase 7.
