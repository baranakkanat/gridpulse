# Experiment results

Every experiment here follows the registered protocol in `docs/research_protocol.md`.
Labels used throughout:

- **Registered:** a prediction or decision rule fixed before the run.
- **Exploratory:** an analysis decided after seeing results.
- **Negative:** a result that went against an expectation, reported as found.

Reproduce Track 1 with:

```bash
uv run python -m gridpulse forecast-study --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/forecast_study
```

## Track 1: national load forecasting (OPSD, Germany, hourly MW)

2018 is the selection period. 2019 was inspected in earlier phases, so no Track 1 result
is confirmatory. All comparisons use the same 8,760 common-valid pairs per year.

### C1: boosting cap (registered rule: adopt only if the 2018 MAE gain is ≥ 1 %)

| Cap | Best iteration | Training time | 2018 MAE (MW) | 2018 RMSE (MW) |
|---|---:|---:|---:|---:|
| 500 (Phase 2A) | 500 (cap reached) | 0.5 s | 1,505.0 | 2,717.0 |
| 3,000 | 2,220 (early stopping triggered) | 2.0 s | 1,430.8 | 2,622.9 |

- The 2018 MAE gain is 4.93 %, so the 3,000 cap was adopted for C2 and C3.
- The 2,220 iterations were selected on 2018, so the 2018 gain is optimistic. The 2019
  values below are not selected on.
- The Phase 2A results are not rewritten. The `train-lightgbm` command still uses 500.

### C2: known-ahead holiday flags (exploratory: hypothesis formed after inspecting errors)

Arm B adds three features to arm A (cap 3,000 for both): `target_is_holiday`,
`lag_24h_source_is_holiday` and `lag_168h_source_is_holiday`.

| Period | Weekly naive MAE | A MAE | B MAE | B − A per-day MAE (95 % block bootstrap) | A RMSE | B RMSE |
|---|---:|---:|---:|---:|---:|---:|
| 2018 | 2,555.6 | 1,430.8 | **1,199.3** | −231.5 [−401.2, −93.5] | 2,622.9 | 1,837.7 |
| 2019 | 2,558.1 | 1,369.8 | **1,164.5** | −205.3 [−381.1, −62.3] | 2,482.5 | 1,748.2 |

MAE and RMSE in MW. By holiday category (MAE, MW):

| Category (pairs per year) | 2018 A → B | 2019 A → B |
|---|---:|---:|
| `neither_holiday` (8,352) | 1,186.5 → 1,147.2 | 1,141.8 → 1,132.6 |
| `target_holiday_only` (192; 8 dates) | 9,737.4 → **1,843.5** | 9,906.3 → **1,447.3** |
| `weekly_reference_holiday_only` (192; 8 dates) | 2,272.4 → 1,872.1 | 1,973.4 → 1,863.0 |
| `both_holidays` (24; 2 dates) | 13,249.4 → 8,787.1 | 7,592.6 → 4,417.5 |

**Findings:**

- The holiday failure that Phase 2A documented almost disappears on holiday targets. MAE
  falls by 81 % (2018) and 85 % (2019).
- On ordinary days the gain is small (−39 and −9 MW).
- The about-10 holiday-related dates per year account for 84 % (2018) and 96 % (2019) of
  the overall B − A difference. The overall interval therefore mostly reflects how many
  holiday days a bootstrap resample draws. Holiday and ordinary days should be read
  separately.
- MAE also improves on Mondays (−595 / −379 MW), consistent with weekly lags that
  reference holiday Mondays.
- `both_holidays` (1 January, whose weekly reference is Christmas) stays poor. It
  contains only 2 dates per year, so no conclusion is drawn.
- Selection rule for C3: B, because its 2018 MAE is lower.

### C3: rolling split-conformal intervals (registered; model B; 56-day window, nominal 90 %)

| Period | Coverage (95 % block bootstrap) | Mean width | Days with all 24 hours covered |
|---|---:|---:|---:|
| 2018-02-26 – 2018-12-31 (7,416 h) | 0.893 [0.863, 0.922] | 4,988 MW | 48.5 % |
| 2019 (8,760 h) | 0.914 [0.888, 0.937] | 5,124 MW | 52.6 % |

**Findings:**

- **Overall coverage** is close to nominal in both years. Per-lead coverage lies between
  0.88 and 0.93 throughout.
- **Misses cluster within days.** About half of all days have every hour covered. Under
  independent misses at the observed coverage that share would be 0.893²⁴ ≈ 7 % (2018) or
  0.914²⁴ ≈ 12 % (2019), or 17–21 % allowing month-specific coverage.
  - Misses therefore cluster within days, beyond month-level heterogeneity.
  - The independent statistics review reports that per-day miss variance is 8–9× the
    binomial value.
- **Holiday coverage (registered prediction: under-coverage).** Holiday targets are
  covered at 0.833 (2018) and 0.865 (2019). Days whose weekly reference is a holiday are
  covered at 0.931 and 0.797. The 24 `both_holidays` hours in 2019 are covered at 0.542.
  These groups have 8 dates or fewer per year, so the numbers are descriptive only.
- **Seasonal swings are large.**
  - March 2018: 0.794. (February 2018 contains only the 3 evaluated days 26–28 Feb, at
    0.667, too few to interpret.)
  - October: 0.855 (2018) and 0.863 (2019).
  - December: 0.839 and 0.810.
  - August 2018: 0.831.
  - Some months over-cover, e.g. June 2018 at 0.978 and July 2019 at 0.983.
- **Interpretation.** The window adapts to level shifts with a lag of weeks. It cannot
  anticipate transitions or one-off events.
- **Hypothesis, not verified:** the early-2018 under-coverage coincides with the
  late-February / March 2018 European cold spell. The model has no temperature input.
- **Width.** The intervals are wide (about ±2.5 GW, roughly 4.5 % of mean load) because
  the heavy-tailed absolute residuals set the 90 % quantile.

### What Track 1 does and does not show

- **Shown:** on this dataset, holiday information was the largest single improvement to
  the learned forecaster. A simple rolling interval reaches near-nominal *average*
  coverage while failing systematically in transition months and on rare calendar days.
- **Not shown:** confirmatory evidence (2019 was pre-inspected); any coverage guarantee;
  causes of the monthly under-coverage; performance under the 2020 shift (still reserved).

## Track 2: day-ahead PV caps on a SimBench LV grid

Network `1-LV-rural1--2-sw`, pandapower AC power flow, 15-minute steps. The scenario is
"PV and load without battery dispatch", with the benchmark transformer tap applied
(protocol s. 3.6b). Reproduce with:

```bash
uv run python -m gridpulse grid-study --period development --output-dir outputs/grid_study
```

```bash
uv run python -m gridpulse grid-study --period evaluation --output-dir outputs/grid_study
```

### Development period (2016-02-05 – 06-30, 147 days): verification only

| Policy | Violation steps | Curtailed energy |
|---|---:|---:|
| `no_action` | 757 | 0 MWh |
| `static_70` | 757 (never binds) | 0 MWh |
| `point` | 626 | 1.77 MWh |
| `risk` (α = 0.05) | 93 | 12.27 MWh |
| `robust` (no scenario violates) | 46 | 15.12 MWh |
| `selective` (F-ROBUST) | 57 | 14.59 MWh |
| `oracle` (unattainable) | 0 | 7.69 MWh |
| `static_dev` (A1; chosen *on* these days, so in-sample) | 0 | 22.70 MWh |

- **Violations.** All violations are transformer overloads from reverse power flow,
  peaking at 145 % loading. There are no voltage or line violations and no
  non-converged flows.
- **Risk calibration (development).**
  - Brier 0.0372 vs the reference 0.0357, so BSS −0.042 [−0.146, 0.062]. The no-action
    risk shows no skill over the rolling-frequency reference.
  - Mean predicted risk 0.055 vs observed rate 0.054. ECE 0.013.
- **Decision calibration.** On `risk`'s active steps, 81 violations were realised against
  24.5 predicted, i.e. 3.3 times as many. That is a realised rate of 0.031.
- **Deferral.** The D2 monitor deferred 86 of 147 days. On deferred days `risk`'s active
  steps violate at 0.035, against 0.020 on recommended days.

**The tap defect and its effect.** Development rerun before and after the fix:

| | Tap ignored (defect) | Tap applied |
|---|---:|---:|
| `no_action` violation steps | 689 | 757 |
| `point` | 566 | 626 |
| `risk` | 65 (8.26 MWh) | 93 (12.27 MWh) |
| `selective` (F-ROBUST) | 50 (9.90 MWh) | 57 (14.59 MWh) |
| `oracle` curtailment | 6.18 MWh | 7.69 MWh |
| deferred days | 69 | 86 |

Ignoring the tap understated transformer current and therefore the problem being
studied.

**Storage sensitivity (exploratory, development days).** Realised no-action violations
under three readings of the SimBench storage series:

| Storage | Violation steps | Max transformer loading |
|---|---:|---:|
| Held at 0 MW (study scenario) | 757 | 145 % |
| As published (pandapower load convention: discharging at the PV peak) | 1,571 | 214 % |
| Sign-reversed (charging at the PV peak) | 4 | 105 % |

Whether this benchmark grid has a congestion problem at all depends on how its storage data
are interpreted. The Track 2 results describe the zero-storage scenario only.

### Evaluation period (2016-07-01 – 12-30, 183 days): single run with frozen, fingerprinted code

| Policy | Violation steps | Transformer severity (%·steps) | Curtailed energy | Excess over oracle |
|---|---:|---:|---:|---:|
| `no_action` | 448 | 7,342 | 0 MWh | — |
| `static_70` (never binds) | 448 | 7,342 | 0 MWh | — |
| `point` | 439 | 6,705 | 0.35 MWh | — |
| `risk` (α = 0.05) | 59 | 190 | 8.40 MWh | +3.03 MWh |
| `robust` (no scenario violates) | 24 | 63 | 9.42 MWh | +4.06 MWh |
| `selective`, F-ROBUST | 25 | 65 | 9.34 MWh | +3.97 MWh |
| `selective`, F-NONE (= F-STATIC70) | 444 | 7,274 | 0.11 MWh | — |
| `static_dev` (A1, cap 0.3 chosen on development) | 0 | 0 | 13.55 MWh | +8.19 MWh |
| `oracle` (unattainable) | 0 | 0 | 5.37 MWh | 0 |

- Every violation is a transformer overload. There are no voltage or line violations and
  no non-converged flows.
- Violations occur in July–September only. October to December has 0–2 violating steps
  per policy.

**Registered hypotheses.** All intervals are 95 % circular block bootstraps of per-day
differences (7-day blocks).

| Hypothesis | Evidence | Verdict |
|---|---|---|
| H1: no-action risk has skill over the rolling-frequency reference | BSS −0.090 [−0.204, 0.014] (development −0.042 [−0.146, 0.062]) | **Not supported** |
| H2a: `risk` has fewer violations than `point` | −2.08 steps/day [−3.45, −0.91]; all 37 informative days favour `risk`, at 24× `point`'s curtailment (8.40 vs 0.35 MWh) | **Supported** |
| H2b: `risk` curtails less than `static_70` | +0.046 MWh/day [0.021, 0.076]; `static_70` never binds | **Not supported** (degenerate; announced in A1 before results) |
| H3: `risk`'s realised rate on active steps exceeds α | 50 / 2,103 = 0.024 < 0.05 | **Falsified** as stated. Realised violations were still 3.1× the predicted count (16.3) |
| H4a: on deferred days `risk` fails more than on recommended days | 0.028 vs 0.009 per active step; difference 0.019 [−0.014, 0.047]; in September (the only month with both day types) the direction reverses: 1/300 deferred vs 4/94 recommended | **Not supported** |
| H4b: `selective` (F-ROBUST) has fewer violations than `risk` | −0.19 steps/day [−0.36, −0.05]; 12 of 12 informative days; costs +0.94 MWh (9.34 vs 8.40) | Supported, but **by construction**: the fallback caps at least as deeply as `risk` |
| H4c: `selective` (F-NONE) has *more* violations than `risk` | +2.10 steps/day [0.88, 3.56]; 36 of 36 informative days | Supported, also by construction. It demonstrates that deferral without a protective fallback is not safety, and says nothing about whether the deferral criterion is useful |

**Risk calibration (evaluation).**

- Observed violation rate 0.0255; mean predicted risk 0.0296; Brier 0.0203 vs reference
  0.0186.
- ECE is 0.006 over all steps but 0.048 over non-zero-risk steps. The headline value is
  dominated by the 88 % of steps with zero risk.
- Reliability by predicted-risk bin:

| Predicted risk | Steps | Mean risk | Observed frequency |
|---|---:|---:|---:|
| 0 | 15,465 | 0 | 0.0006 |
| (0, 0.1] | 404 | 0.056 | 0.079 |
| (0.1, 0.3] | 1,066 | 0.195 | 0.188 |
| (0.3, 0.6] | 537 | 0.418 | 0.320 |
| (0.6, 1] | 96 | 0.677 | 0.365 |

- The bins suggest overstatement at high risk and understatement at low non-zero risk.
  The direction repeats in development, but every bin's day-block interval includes its
  mean risk (the top bin rests on 12 days), so this is suggestive only.
- **The reference is the stronger probability forecast**, not a trivial one (all verified
  by recomputation):

| | Scenario risk | 28-day frequency reference |
|---|---:|---:|
| AUC | 0.957 | 0.970 |
| Brier reliability term (lower is better) | 0.00142 | 0.00040 |
| Brier resolution term (higher is better) | 0.00598 | 0.00664 |

- Against an always-zero forecast the scenario risk has BSS +0.20. It carries information,
  just not more than recent violation history.

**Exploratory analyses** (decided after seeing evaluation results):

- **Deferral tracks the season, driven by a real excess of violations.** All 31 July and
  all 31 August days were deferred, plus 17 in September; none from October to December.
  - Deferred days contain 434 of the 448 no-action violations and 49 of `risk`'s 59.
  - On every deferred day the 28-day window held 7–38 realised violations against 1.9–6.6
    predicted. The median ratio is 5.5, and the Poisson thresholds were 4–11. The
    "single violation" resolution case of amendment A1.4 never occurred.
  - D2 therefore correctly detected a season-long under-prediction (consistent with H3's
    3.1×), i.e. a *regime*, not individually unreliable days.
- **D2 caveats.**
  - The Poisson test ignores clustering: 15 days hold all 50 active-step violations.
  - Consecutive windows overlap in 27 of 28 days, so daily decisions are strongly
    dependent: the deferral sequence is just 4 runs. The nominal 5 % is a per-day marginal
    level, not a false-alarm rate.
- **H3 split (exploratory).** Where `risk`'s constraint was slack (chosen cap with zero
  scenario risk) the realised rate was 15 / 1,646 = 0.009. Where it was binding (chosen
  risk 1/28) it was 35 / 457 = 0.077 [0.028, 0.131], against 16.3 predicted.
- **The selective layer adds nothing over always using `robust`.** The two differ by one
  violation step on a single day. The decision-assurance mechanism, as designed, is
  indistinguishable from the simplest conservative scenario rule.
- **The fixed cap from development** (`static_dev`, 0.3) had zero evaluation violations,
  but curtailed +0.023 MWh/day [0.015, 0.031] more than `robust` (13.55 vs 9.42 MWh;
  2.5× the oracle).
- **Trade-off.** No feasible policy dominates on both axes.
  - In violation steps / curtailment: `risk` (59 / 8.4 MWh), `robust` (24 / 9.4) and
    `static_dev` (0 / 13.6) trace a trade-off.
  - `point` (439 / 0.35) barely improves on no action, because the 7-day-mean forecast
    smooths out PV peaks.
  - α = 0.10 gives 93 / 7.2 MWh; α = 0.01 equals `robust`.

### What Track 2 shows, and does not

- **Supported (on this one benchmark grid, synthetic profiles, naive forecaster):**
  - Scenario-aware curtailment rules cut realised transformer overloads by 87–95 %
    relative to no action, at 1.6–1.8× the oracle's curtailment.
  - The point-forecast rule is nearly useless.
- **Negative:**
  - The scenario risk estimates show no evidence of skill relative to a 28-day empirical
    violation-frequency reference, in either period. That reference also discriminates
    better (AUC 0.970 vs 0.957).
  - Realised violations at the chosen caps were about 3× the predicted count, so the
    chance-constraint threshold under-protected.
- **Negative (exploratory):** the selective decision-assurance layer, as registered, does
  not improve physical outcomes over always applying the conservative rule. Its deferrals
  mark a season-long miscalibration regime rather than individually unreliable days.
  H4b and H4c hold by construction.
- **Not shown:**
  - generalisation to other grids, real feeder data or better forecasters;
  - behaviour with the benchmark's storage (development sensitivity: violations range from
    4 to 1,571 steps depending on how the storage data are read);
  - any operational safety claim.

## Phase 4: reliability under dual uncertainty (protocol s. 4, amendments 4A–4D)

### Reproduction of Phase 3 (2026-10-17)

| Check | Result |
|---|---|
| Test suite and lint | 149 tests pass (before Phase 4); ruff lint and format clean |
| `forecast-study` re-run | all 7 output files byte-identical |
| `grid-study` re-run from the cache (both periods) | all 9 outputs byte-identical (summaries, calibration, daily outcomes, passports, storage sensitivity) |
| Physics cache vs a fresh AC computation | 5 days (35, 120, 172, 250, 364) bit-identical; fingerprint unchanged |
| Phase 4 code on Phase 3 inputs | reproduces the Phase 3 daily outcomes of `no_action`, `point`, `risk`, `robust`, `oracle` and `static_dev` exactly |
| Phase 4 rural1 nominal physics | bit-identical to the Phase 3 cache on all 330 days |

**Strongest Phase 3 baseline.** `static_dev`, a fixed 0.3 cap chosen on development data:

- no evaluation violation at 13.55 MWh, i.e. 2.5× the oracle's 5.36 MWh;
- `robust`: 24 violations at 9.42 MWh;
- `risk`: 59 violations at 8.40 MWh.

None of the three dominates the others; they are different points on the
violation-curtailment trade-off.

### Why scenario risk underperformed the frequency reference (rural1; exploratory)

The frequency reference is identical to a *replay* ensemble: at no action, a realised day
d−j "violates" exactly when its realised violation indicator is 1.

**Over days 63–364:**

| Quantity | Residual scenarios | Replay (past 28 days) |
|---|---|---|
| Total predicted / observed violations at fixed cap levels (no selection) | 1.07 | 1.00 (by construction) |
| Brier score at no action (lower is better) | 0.0304 | 0.0287 |
| Brier reliability / resolution | 0.0013 / 0.0108 | 0.0005 / 0.0117 |
| AUC | 0.949 | 0.953 |
| Realised / in-sample predicted at the chosen caps ("≤ 1 of 28" rule) | 131 / 38.9 = 3.4 | 86 / 36.1 = 2.4 |
| Realised / held-out predicted (half the members choose, the other half report) | 1.12–1.23 | 0.91–1.00 |

**Diagnosis:**

1. **The probabilistic difference is small and not established.** The Phase 3 Brier skill
   intervals included 0.
2. **The "3× more violations than predicted" is mainly selection optimism.**
   - Choosing the least curtailment whose in-sample estimate is ≤ 1/28 selects estimates
     that happened to be low.
   - Estimates not used for the choice are close to calibrated.
   - Theory agrees: under exchangeability the rule's expected violation probability is
     2/29 ≈ 0.069 (Campi & Garatti 2011).
3. **The 7-day-mean forecaster adds no decision value over replay.** It has no weather
   information.
4. **Only about four cap levels matter on this feeder.** PV peaks near 0.6 of rating: caps
   1.0–0.6 are physically identical, 0.4 still violates, and 0.3 never does.

### Network survey and stress rule (development half only)

**Survey.** Eligibility was fixed before the survey; the survey is s. 4.2 of the protocol.

- **No new network is eligible.** In their own 2034 scenario with idle storage, rural2,
  rural3, semiurb4, semiurb5 and urban6 have **zero** violations in the development half.
  - Their peak transformer loading is 30–60 %.
  - Their voltages stay at least 0.035 p.u. inside the limits.
- **The decision problem studied in Phase 3 exists in one of six SimBench LV topologies.**
- **Scenarios 0 and 1** add only rural1 `--1`, which is PV-driven. semiurb5 `--0` has an
  overvoltage at every step that no curtailment can remove; it comes from a 1.01 p.u. bus
  limit.

**Stress rule (registered before any policy run).** Each network's PV was scaled to the
same multiple of its own development-half hosting capacity as rural1 (1/0.715 = 1.40).

| Network | Hosting capacity (× benchmark PV) | PV scale | No-action development violations after scaling | Binding constraint |
|---|---|---|---|---|
| rural1 (development network) | 0.715 | 1 | 757 | transformer |
| rural2 | 2.094 | 2.93 | 588 | transformer |
| rural3 | 3.109 | 4.35 | 626 | transformer, overvoltage |
| semiurb4 | 2.664 | 3.73 | 820 | line |
| semiurb5 | 4.969 | 6.95 | 750 | line, overvoltage, transformer |
| urban6 | 4.297 | 6.01 | 554 | line, overvoltage |

- All scaled-network violations are PV-driven, and every flow converged.
- The scaled networks are stress cases, not growth forecasts.

### Development runs (verification only)

The development stage was run on every network, and every development output was
inspected before the evaluation.

- **4A item 10.** The `static_aci` check needed two revisions, recorded in amendments 4C and
  4D: a warm start, then a step size matched to the τ controllers. After that every
  network passed.
  - **The second re-check was close to certain to pass.** With 4D's smaller step, 147
    quiet development days relax the level index by only 0.44, which is less than the 0.5
    needed to change the applied cap.
  - **The failing output was not archived.** The development output that showed the
    urban6 failure (index 6.93) was overwritten by the re-check run.
- **4B.** Only the point-forecast controller reached the τ bound.
- **Exclusions.** No cell had unavoidable violations.

### Evaluation (2016-07-01 – 12-30, 183 days)

**The run.** One run at 2026-10-18 01:24 UTC, with frozen code (physics fingerprint
`290e7371…`). Timestamps and hashes are in `docs/provenance/phase4/`.

- **Stale label.** The metadata's "protocol" label still reads "with amendment 4A". That
  string predates amendments 4B–4D, but the recorded SHA-256 of the protocol is that of
  the final text, which includes 4A–4D.
- **Protocol unchanged.** The protocol file has its registered text and hash.
- **One post-evaluation code change.** `__main__.py` had its re-run guard fixed: it had
  checked a file name the run does not write. This does not affect the analysis, and the
  old and new hashes are logged.
- **Everything else unchanged.** Every other source file has the hash recorded at run
  time. The full generated tables are in
`outputs/dual_study/evaluation_report.md`, which is git-ignored.

**How to read the results:**

- Semi-confirmatory counts (protocol s. 4.0) use the five new networks only; rural1 is a
  development network.
- β = 0.1 avoidable daylight violation quarter-hours per day is a modelling target.
- A cell = (network, information, truth).

#### Forecast uncertainty only (day-ahead forecast, nominal truth)

Each cell gives avoidable violation steps / curtailed MWh over 183 days; * = meets β.

| Policy | rural1 (dev.) | rural2 | rural3 | semiurb4 | semiurb5 | urban6 | Σ new networks |
|---|---|---|---|---|---|---|---|
| no action | 448 / 0 | 424 / 0 | 425 / 0 | 479 / 0 | 445 / 0 | 313 / 0 | 2086 / 0 |
| `static_dev` (= `static_beta` here) | 0 / 13.6* | 0 / 8.6* | 3 / 13.4* | 0 / 7.2* | 0 / 13.2* | 0 / 8.8* | 3 / 51.1 |
| `static_aci` | 7 / 12.5* | 8 / 8.5* | 12 / 13.2* | 9 / 7.1* | 11 / 12.9* | 7 / 8.5* | 47 / 50.2 |
| `point_margin` | 0 / 56.1* | 0 / 95.2* | 0 / 150.4* | 0 / 178.8* | 0 / 167.5* | 0 / 290.2* | 0 / 882.0 |
| `scenario_robust` | 24 / 9.4 | 8 / 7.9* | 9 / 13.5* | 8 / 7.0* | 7 / 12.3* | 2 / 7.5* | 34 / 48.2 |
| `scenario_aci` | 9 / 10.6* | 5 / 15.1* | 4 / 24.0* | 16 / 6.9* | 8 / 12.2* | 3 / 7.6* | 36 / 65.8 |
| `replay_robust` | 4 / 10.2* | 4 / 8.0* | 9 / 13.7* | 1 / 7.1* | 1 / 12.5* | 1 / 7.4* | 16 / 48.7 |
| `replay_aci` | 6 / 9.6* | 6 / 7.9* | 9 / 19.3* | 3 / 7.1* | 4 / 12.2* | 3 / 7.2* | 25 / 53.7 |
| `ensemble` | 1 / 11.3* | 0 / 45.8* | 0 / 103.8* | 0 / 19.6* | 0 / 39.7* | 0 / 68.0* | 0 / 276.9 |
| oracle | 0 / 5.4 | 0 / 6.4 | 0 / 9.3 | 0 / 6.7 | 0 / 10.6 | 0 / 6.3 | 0 / 39.3 |

**Reading:**

- **The development-tuned static cap is hard to beat when the model is right.**
  - Summed over the five new networks it curtails 51.1 MWh with 3 violation quarter-hours.
    That is 30 % above the oracle's 39.3 MWh.
  - `replay_aci` curtails 2–18 % less in rural2, semiurb4, semiurb5 and urban6, at the
    price of 3–6 violation quarter-hours (within β).
  - It curtails **44 % more** in rural3, so in aggregate it curtails slightly more than the
    static cap (53.7 MWh).
    - The rural3 loss is controller dynamics, not physics. On 2016-07-23, eight transformer
      overload quarter-hours raised τ from −0.02 to +0.06.
    - τ relaxes by only 0.001 per day, and at cap 0.4 rural3's transformer sits near
      100 %. So 413 midday steps dropped to cap 0.3 until September.
    - One cap level is 27 % of that transformer's rating, so a coarse action set amplifies
      a small margin.
  - **The static cap's efficiency is partly built in.**
    - The stress rule scales every network to 1.40× its hosting capacity, and coincident
      PV peaks are 0.54–0.60 of rating. That puts the safe uniform cap near 0.57/1.40 ≈
      0.4 in all five networks.
    - The development half contains the yearly PV peak, so a cap tuned on it is
      conservative for July–December. It curtails on only 53–73 of the 183 evaluation
      days per new network.
- **The deterministic forecast with a development-tuned margin is useless.** A margin large
  enough to remove all development violations curtails 41–45 % of the available PV in
  rural1, rural2, rural3 and semiurb5. In semiurb4 and urban6 it curtails 93–100 %.
  There, the tuned τ exceeds the zero-PV voltage headroom, which is the cliff of
  amendment 4B.
- **The model-ensemble rule costs 5.4× the static cap.** One member, `tap_raise_lv` (a
  uniform +0.027 p.u. voltage offset), drives this cost on almost every daylight step.
  - Without that member the ensemble would curtail 83.4 MWh, 1.6× the static cap. This is a
    reviewer's recomputation, not a registered policy.
  - In transformer-bound rural1 the ensemble is cheaper than the static cap (11.3 vs
    13.6 MWh).

**Cost of reliability** (registered metric, nominal truth): the extra curtailment of the
more cautious policy per avoided violation quarter-hour.

- Moving from `replay_aci` to the static cap costs 0.04–0.52 MWh per avoided step in
  rural2, semiurb4, semiurb5 and urban6. In rural3 the static cap is better on both counts.
- Moving from `replay_aci` to the ensemble costs 4.2–20.3 MWh per avoided step.

#### Physical-model uncertainty: does the requirement hold under the 9 variant truths?

Count of cells meeting β with the day-ahead forecast, over 5 new networks × 10 truths
(nominal plus 9 variants).

| Policy | β = 0.1 (registered) | β = 0.05 | β = 0.2 (exploratory) |
|---|---|---|---|
| `static_dev`, `static_beta` | 26/50 | 25/50 | 26/50 |
| `scenario_robust` | 24/50 | 21/50 | 26/50 |
| `replay_robust` | 25/50 | 24/50 | 26/50 |
| `ensemble` | 42/50 | 38/50 | 43/50 |
| `point_margin` | 44/50 (at 95–290 MWh) | 42/50 | 45/50 |
| `static_aci` (feedback only) | 46/50 | 26/50 | 50/50 |
| `scenario_aci` | 46/50 | 23/50 | 50/50 |
| `replay_aci` | **49/50** | 33/50 | 50/50 |

**Reading:**

- **Tuning with the nominal model breaks under model errors that raise stress.** Policies
  whose settings come from the nominal model fail the requirement in about half the truths:
  static caps and the robust scenario and replay rules.
  - **The largest failures are uniform LV voltage offsets** (`tap_raise_lv`, `mv_high`,
    `joint_realistic`). Every `static_dev` violation under them is an *overvoltage*.
  - Summed over the new networks: 5,480 avoidable violation quarter-hours under
    `tap_raise_lv` and 6,879 under `mv_high`; one cell reaches 2,580.
  - **84 % of these come from nine stress-bracket cells.** These are the −1-tapped
    networks (rural2, rural3, urban6), where the variant puts the zero-PV LV voltage at
    1.08 p.u. (amendment 4B). There, an operator would re-tap rather than curtail.
  - `joint_realistic` is almost identical to `mv_high`, so that error is counted twice.
  - **Excluding the stress brackets, `static_dev` still fails 15 of 41 cells:**
    - semiurb5 under a one-step tap or MV offset: 871–1,027 overvoltage steps, up to
      1.115 p.u., from a plausible 1.05 p.u. zero-PV setting;
    - semiurb4 under `mv_high`: 52 marginal steps;
    - every network under fixed cos φ 0.95 and `joint_loading`: transformer or cable
      overloads of 101–110 %, with no severe step.
- **Calibration to measured true-grid violations restores the requirement, given full
  observation.** It happened online, but mostly during the 147 development days. Under the
  stress truths, `static_aci` entered the evaluation at level index 6.5–8.9, and
  `replay_aci` at τ 0.07–0.31. The model errors are fixed for the year, so a one-off cap
  re-tuned on measured development violations was not tested and might do as well. All
  three online policies meet β in 46–49 of 50 cells, including `static_aci`, which uses no forecast and
  no grid model. This rests on a strong assumption: every bus voltage and branch current is
  observed exactly every quarter-hour.
  - The worst voltage is always at the most remote PV bus.
  - The binding line is a single cable segment one to six hops out.
  - Substation metering alone would see none of the voltage or line violations here, only
    the transformer overloads.
  - In practice the feedback would need smart-meter voltages at PV buses, whose ±0.5–1 %
    accuracy exceeds many of the exceedances, and branch currents from a state estimator.
    A state estimator is itself a grid model.
- **The AC model on top of feedback helps modestly.**
  - Replaying past days through the nominal AC model also yields a time-of-day cap
    schedule, unlike a uniform cap; the two effects are not separated.
  - In the 41 mismatch cells where both `replay_aci` and `static_aci` meet β, `replay_aci`
    curtails a median 5 % less (range −25 % to +89 %).
  - The curtailment interval is below 0 in 26 cells, includes 0 in 11 and is above 0 in 4,
    one of them material (urban6 `tap_lower_lv`, +89 %).
  - About 8 of the 41 cells are copies of the nominal cell, because their variants are
    inert, and `mv_high` and `joint_realistic` are near-duplicates.
  - Under `pv_fixed_095` it saves 3–10 MWh per network. The largest absolute savings are
    under `mv_high` (about 25 MWh).
  - **This understates what physics could add.** A single cap for all PV units cannot
    choose *which* units to curtail. In semiurb4, semiurb5 and urban6, 53–75 % of the PV
    sits downstream of the binding line, so a uniform cap mostly curtails PV that does not
    affect the binding constraint.
- **Calibration tracks the target it was given** (exploratory β column). Re-scored at
  β = 0.05, runs calibrated to β = 0.1 meet it in only 23–33 of 50 cells. That is expected:
  they hover near their own target. `static_dev` scores 25 of 50.

#### Registered hypotheses (protocol s. 4.8 with amendments 4A–4D)

| Hypothesis | Verdict | Evidence |
|---|---|---|
| H1 selection optimism generalises | **Untestable** | No new network had ≥ 8 days with a realised violation at the Phase 3 rule's caps (replay members, the registered count): 1–5 per network in July–December; scenarios 3–9. |
| H2 forecast value over replay | **Prediction held:** the forecast adds value in 0 of 5 networks | `scenario_aci` − `replay_aci`: no violation interval below 0. The curtailment interval lies above 0 (scenario curtails more) in rural2, rural3 and urban6. No-action Brier skill of scenarios vs replay: −0.097 to +0.065, every interval includes 0. |
| H3 reliability-aware vs strong simple | **"Genuine value" by the registered criterion, for `replay_aci` only; see caveats** | See below. |
| H4 explicit ensemble vs feedback | **Prediction held** | See below. |

**H1 in detail.**

- **Descriptive values.** Leave-one-out ratios were below 1 in the evaluation half-year:
  0.06–0.59 in the new networks (rural1: 0.38–1.03). In-sample ratios were 0.13–1.90
  (rural1: 0.97–3.06).
- **rural1 is mixed.** Its evaluation half would count as informative (9 replay violation
  days) but fails the registered replay criteria: in-sample 0.97, leave-one-out 0.38
  [0.11, 0.74]. It passes them only for the residual scenarios (3.06 and 1.03). The
  exploratory diagnosis of s. 4.1 used a half-split cross-fit over days 63–364 and should
  not be read as a registered confirmation.
- **Weak evidence.** This rests on 1–9 violation days, and 3 of the 10 leave-one-out
  intervals include 1.
- **A hypothesis, not a result.** The size of the selection effect may depend on the
  seasonal direction: in spring, 28 past days under-represent rising PV; in autumn they
  over-represent it. rural1's autumn in-sample ratio of 3.06 for scenarios cautions
  against reading this as established.

**H3 in detail.**

- **`replay_aci` met both conditions:**
  - better than all four simple policies under the nominal truth in 3 of 5 networks
    (rural2, semiurb5, urban6);
  - better than all of them in at least half of the material mismatch cells in 5 of 5
    networks.
- **`scenario_aci` did not** (2 of 5 and 3 of 5).
- **No simple policy was better than both aware policies in 3 or more networks.**
  `static_dev`, `static_beta` and `static_aci` each were in 1 network (rural3).
- **By profile group** (4A), `replay_aci`'s nominal wins are:
  - 1 of 2 in the networks with new PV profiles: rural2 won, and rural3 lost
    significantly;
  - 2 of 3 in the networks sharing rural1's PV profiles.
- **Caveats** that the registered count does not capture:
  1. **Small, structurally thin nominal wins.**
     - The qualifying wins save 5.4–15.1 % (0.62–1.29 MWh per half-year) against the
       feedback-only cap, and 7.0–17.8 % (0.74–1.57 MWh) against `static_dev`.
     - Summed over the networks, `replay_aci` is not more economical than the static cap
       under the nominal truth, because rural3 goes the other way.
     - The verdict needs exactly 3 of 5 networks. It is stable across 100 bootstrap
       seeds and block lengths of 1–28 days, but one flipped network would make it
       "inconclusive".
     - Two mismatch passes sit exactly at the "half" threshold: rural2 (3 of 6) and
       semiurb4 (1 of 2).
  2. **Feedback carries most of the mismatch advantage.** Many mismatch wins arise because
     every simple policy tuned with the nominal model fails. `static_aci` is also in the
     simple set, so each win still needed `replay_aci` to curtail significantly less than
     the feedback-only controller.
  3. **In practice the verdict rests on `replay_aci` versus `static_aci`.**
     - `static_dev` equals `static_beta` in every cell, and `point_margin` is beaten
       trivially. So `static_aci` is the binding comparator in every mismatch win and in
       every nominal win except rural2.
     - `static_aci` is the least pre-specified policy (two revisions).
       - The warm start made it less conservative at the start of evaluation.
       - The smaller step slows both its relaxation and its reaction to violations.
       - So the net effect of the revisions on how hard it is to beat is not established.
  4. **Multiplicity.** Two aware policies were assessed, and one qualified.
  5. **Not forecast-based.** The qualifying policy uses no forecast: it replays the last 28
     measured days through the AC model and calibrates a margin online. "Reliability-aware"
     value here means physics plus measured feedback, not forecasting.

**H4 in detail.**

- **(a) A perfect forecast with the wrong model fails.** `point` with perfect injections and
  the nominal model fails β in 5–6 of 9 variant truths per network.
- **(b) The ensemble meets β in every in-ensemble cell.** This is by construction.
- **(c) Out of ensemble it fails more often than feedback.** As amendment 4A notes, this
  is close to true by construction: the feedback policies learned the true grid during
  development.
  - Perfect information: ensemble 11 of 15 cells failed, `point_aci` 2 of 15.
  - Day-ahead forecast: ensemble 7 of 15, `replay_aci` 1 of 15. Per network, semiurb5 is
    tied 0–0 and semiurb4 is 1–0.
  - **These ensemble failures are physically marginal.** `mv_high` exceeds the
    `tap_raise_lv` offset by only about 0.003 p.u. The resulting overvoltages have a median
    exceedance of 0.6–1.3 × 10⁻³ p.u. and peak at 1.106–1.109 p.u., which is below
    voltage-meter accuracy.
  - So the prediction holds formally ("robust only within its list"), but with a near-miss,
    not a gross failure.
  - The ensemble is also the most expensive rule after `point_margin`.

**D1: forecast and model errors do not add.** The interaction for `point` is strongly
negative (−455 to 0 steps per cell).

- **A ceiling effect.** At nominal, `point` with a forecast already has 301–455 of no
  action's 313–479 avoidable violation steps, so model error cannot add many.
- **Not computable for `scenario_robust`.** The registered D1 for it has no perfect-
  information version, because scenarios exist only with a forecast.

#### Physical-safety indicators (statistical calibration is not physical safety)

Nominal truth, day-ahead forecast, five new networks:

| Policy | Days with a violation | Worst day (quarter-hours) | Longest run | Runs ≥ 1 h | Severe steps (> 0.2 margin) |
|---|---|---|---|---|---|
| `static_dev` | 2 | 2 | 1 | 0 | 0 |
| `static_aci` | 8 | 11 | 11 | 5 | 1 |
| `scenario_aci` | 16 | 6 | 6 | 2 | 0 |
| `replay_aci` | 13 | 8 | 3 | 0 | 0 |
| `ensemble` | 0 | 0 | 0 | 0 | 0 |

**Under adverse mismatch the ranking inverts:**

- `static_dev` reaches 22–35 violating quarter-hours on its worst day and up to 121
  violation runs of 1 h or more per cell.
  - The extremes (the 35-step worst day, 121 runs, 333 severe steps and the +0.24 peak)
    all come from rural3 under `mv_high` and `joint_realistic`. Amendment 4B labels these
    a stress bracket.
  - There, `replay_aci` meets the target only by curtailing 168 MWh, against 13.4 MWh for
    `static_dev`.
  - In rural3 under MV 1.055 p.u. it has 333 severe steps, peaking at 1.124 p.u. at the
    feeder-end bus, while loading stays ≤ 98 %.
  - Under the loading truths (`pv_fixed_095`, `joint_loading`) its peaks are 101–110 %
    loading with no severe step. That is thermally mild for an ONAN transformer
    (IEC 60076-7).
  - Real inverters would disconnect above 1.10 p.u. (VDE-AR-N 4105, 10-minute mean), so
    the 1.11–1.124 p.u. exceedances would appear as PV trips rather than sustained
    overvoltage. That protection is not modelled.
- `replay_aci` stays at ≤ 13 quarter-hours on its worst day, ≤ 9 in its longest run, no
  severe step, and a peak margin ≤ 0.12.

**What "no violation observed" supports.** For a policy with none, the rule-of-three bound
on the probability of a violation on a *stressed* day is 3/n.

- n counts the days on which no action violates (31–45 per network), not calendar days.
- That gives about 0.07–0.10.
- The bound is optimistic, because those days are dependent.

#### What Phase 4 shows, and does not

**When reliability-aware decision support has value here:**

- **The grid model is wrong in a way that persistently raises stress, and the operator can
  observe violations wherever they occur.**
  - Then measured feedback keeps the average violation rate near its target.
  - Replaying measured days through the AC model saves a further median 5 % of
    curtailment over a feedback-only cap (3–10 MWh per network under the reactive-power
    variant).
  - For the largest effects, uniform voltage offsets on the −1-tapped networks, the
    realistic remedy is re-tapping or Q(U), not 25–49 % curtailment.
- **The grid model is right.** A cap validated on a half-year that contains the annual PV
  peak is about as efficient as anything tested, and the safest of the efficient policies.
  (`ensemble` and `point_margin` have zero violations but curtail 5× and 17× as much.)
  Part of this is by design of the stress rule.
- **The naive day-ahead forecast adds no value over replay** (H2, nominal truth). A
  forecaster with weather information was not tested.

**Not shown:**

- any per-day guarantee;
- benefits under realistic observation (substation metering alone misses every voltage and
  line violation here);
- robustness to model errors that change during the year;
- the value of per-unit (non-uniform) curtailment, which is where model-based rules should
  gain most;
- results beyond five PV-stressed synthetic benchmark networks sharing one 2016 profile
  year. In practice the nine variant truths amount to about five distinct perturbations,
  because `pv_cosphi_p` and `storage_greedy` behave almost like nominal.

### Post-evaluation reviews (2026-10-18)

Three independent reviews read the evaluation outputs. None re-ran the evaluation.

1. **Statistical verification.** It recomputed the reported numbers from the daily-outcome
   CSV and re-derived H2–H4 with its own bootstrap.
   - All numbers and verdicts reproduced. Its intervals matched to 7 × 10⁻¹⁶.
   - It flagged overstated wording ("physically the safest", the β = 0.05 reading, H1, the
     rule of three), the missing profile-group split, and that H3 effectively rests on
     `replay_aci` vs `static_aci`.
2. **Power-systems review.** It rebuilt the policies from the physics cache and matched
   curtailment exactly.
   - It showed that the large mismatch failures are overvoltages, mostly in stress-bracket
     cells.
   - It showed that the ensemble's cost comes from one voltage-offset member, and that the
     online policies assume observation at remote buses and mid-feeder cables.
   - It noted that the uniform cap and the stress rule favour static caps.
3. **Readiness gate.** It found:
   - a broken re-run guard (fixed, with a test);
   - provenance kept only in ignored folders (now in `docs/provenance/phase4/`);
   - a mixed H1 result on rural1;
   - two wrong figures: a 5–18 % range that mixed comparators, and the "37–53 days";
   - the unreported cost-of-reliability metric.

All findings were corrected in the text above. No number from the evaluation run changed;
the corrections are interpretation and reporting. The scripts behind reviewer-computed
numbers are in `docs/provenance/phase4/scripts/post_evaluation_reviews/`.
