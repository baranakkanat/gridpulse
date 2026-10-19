# GridPulse

Explainable electricity load forecasting and machine learning reliability.

GridPulse is an independent applied-AI research project. Its long-term question is
how well electricity load forecasting models perform, and how reliable they remain,
when temporal and data conditions change. This repository currently contains only the
research foundation: a validated dataset pipeline, two deliberately simple reference
forecasts, one learned model (LightGBM), and leakage-free, paired temporal evaluation.
Phase 3 adds pre-registered research experiments: forecast reliability on national load,
and uncertainty-aware decisions on a simulated distribution grid.

## Current scope (Phases 0, 1, 1B, 2A, 3, 4, 5, 6, 7 and 8)

Implemented:

- Loading and validating the German hourly load series from Open Power System Data
  (schema, UTC timestamps, temporal coverage, missing and implausible values, checksum).
- A precisely defined forecasting task: at 00:00 UTC each day, forecast the next 24
  hourly load values (MW).
- Two seasonal naive baselines, both using only data from before the forecast origin:
  - weekly: `prediction(t) = load(t − 168 h)`;
  - daily: `prediction(t) = load(t − 24 h)`.
- A paired comparison of the two on identical forecast–target pairs, plus a
  retrospective error analysis by German nationwide public holidays and local weekday.
  Holiday labels are used for analysis only, never for forecasting.
- A first learned model: one pooled LightGBM regressor for all 24 leads, with five inputs
  known at the forecast origin (24-hour and 168-hour load lags, and the target's local
  hour, weekday and month). It is trained on 2015–2017, with early stopping on 2018, and
  compared with both baselines on identical pairs.
- **Phase 3, Track 1 (national load):**
  - a boosting-cap check;
  - a known-ahead holiday-flag ablation;
  - rolling split-conformal day-ahead intervals, with coverage by lead, calendar
    condition and month.
- **Phase 3, Track 2 (SimBench LV grid, pandapower AC power flow):**
  - day-ahead PV feed-in-cap policies (point, scenario-risk, robust, selective with
    explicit deferral criteria and simulated fallbacks, static caps, oracle) on
    identical physics;
  - risk-calibration scoring;
  - per-decision evidence records ("decision passports").
- **Phase 4:** PV-cap decisions when both the forecast and the grid model are uncertain,
  with online-calibrated margins.
- **Phase 5:** the same decisions under limited measurement:
  - a measurement model separating truth, readings, estimates and plans;
  - sensor placement rules;
  - WLS state estimation with an observability test;
  - evidence labels.
- **Phase 6:**
  - measurement noise tied to sensor identity;
  - noise-aware alarm rules for the feedback;
  - a chi-square test for state estimation;
  - protected, frozen study stages.
- **Phase 7:**
  - signed constraint margins (voltage in p.u., loading in %, never added);
  - a model-residual correction from substation measurements, with meter consistency
    checks and operational evidence labels;
  - an exploratory, offline static-HTML demonstrator.
- **Phase 8:**
  - separate voltage (p.u.) and loading (%) reserves, fixed or re-tuned daily;
  - erroneous, missing and late customer data, and imperfect substation instrumentation;
  - three stress cases: opposite tap error, MV voltage rising with PV, and a wrong cable
    record.
- Chronological train / validation / test periods, with 2020 reserved and unused.
- MAE, RMSE and WAPE on valid prediction/target pairs only, overall and per lead hour,
  with explicit counts of excluded pairs.
- Auditable outputs: every prediction records the exact historical timestamp it came from.

Not implemented (and not claimed):

- hyperparameter tuning, other model families, deep learning or ensembles;
- explainability, and uncertainty guarantees (intervals and risks are empirical, with no
  coverage guarantee);
- controlled distribution-shift experiments (2020 stays reserved);
- weather or other external data;
- real feeder data, operator validation, or any control of real equipment;
- any service, dashboard, or deployment infrastructure.

See [docs/methodology.md](docs/methodology.md) for the full experimental protocol and its
limitations.

## Data and reuse

| | |
|---|---|
| Dataset | Open Power System Data (OPSD), *Time series*, version 2020-10-06 |
| DOI | https://doi.org/10.25832/time_series/2020-10-06 |
| File | `time_series_60min_singleindex.csv` (130,339,665 bytes) |
| SHA-256 | `6a7f2bc571314cbf9c321cc03437691cd4be95c3a6f075e60ff99e8035c704c8` (matches the `hash` in the official `datapackage.json`) |
| Target | `DE_load_actual_entsoe_transparency`: total load in Germany, **MW** |
| Timestamp | `utc_timestamp`: start of the hourly interval, UTC |
| Primary source | ENTSO-E Transparency Platform (via OPSD) |

OPSD asks for attribution in this form:

> Open Power System Data. 2020. Data Package Time series. Version 2020-10-06.
> https://doi.org/10.25832/time_series/2020-10-06. (Primary data from various sources,
> for a complete list see URL).

**Reuse status is unresolved.** The 2020-10-06 package's `README.md` and
`datapackage.json` give attribution guidance but declare no license. The primary data
come from the ENTSO-E Transparency Platform, whose terms of use govern reuse; ENTSO-E
maintains a list of data available for free reuse, but it could not be confirmed from
official ENTSO-E pages whether "Actual Total Load" is on that list. Therefore:

- raw data and derived outputs are **not** tracked in this repository (`data/` and
  `outputs/` are git-ignored) and must not be redistributed;
- verify the current ENTSO-E terms before publishing any derived dataset.

No software license has been chosen for this repository yet.

## Setup

Requires Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/). The exact environment
(Python 3.12, NumPy, pandas, LightGBM, pytest, ruff) is pinned in `uv.lock`.

The distribution-grid track (Track 2) needs the optional `grid` extra (pandapower,
SimBench). SimBench ships its benchmark data inside the package, about 87 MB.

```bash
uv sync --all-extras
```

- **pandas version:** the project uses pandas 2.3 and NumPy < 2.5, because pandapower
  3.5.6 supports only those. Phase 0–2A outputs were verified byte-identical under the
  earlier pandas 3 environment.
- **Without the extra:** `uv sync` installs only the forecasting track, and the grid
  tests are skipped.
- **Without uv:** create a virtual environment, then `pip install -e ".[grid]" pytest
  ruff` (dependency versions will then not be locked).

On macOS, LightGBM's prebuilt wheel needs the OpenMP runtime, installed once outside the
project:

```bash
brew install libomp
```

## Obtain the data

```bash
mkdir -p data/raw
curl --fail --retry 3 -o data/raw/time_series_60min_singleindex.csv https://data.open-power-system-data.org/time_series/2020-10-06/time_series_60min_singleindex.csv
```

```bash
shasum -a 256 data/raw/time_series_60min_singleindex.csv
```

The checksum must equal the SHA-256 above. Both commands below also verify it and warn on
a mismatch.

## Validate the dataset

```bash
uv run python -m gridpulse validate --input data/raw/time_series_60min_singleindex.csv
```

Prints a JSON data-quality report for the whole file: coverage per year and per period,
gaps, missing and non-finite values, distribution, and largest hour-to-hour changes.

Exits with status 1 if:

- the time index has blocking problems (non-UTC, duplicated, unordered or off-hour
  timestamps);
- the file cannot be read (missing columns, non-numeric target text).

## Run the weekly baseline

```bash
uv run python -m gridpulse baseline --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/baseline
```

The reserved period (2020 onward) is dropped right after reading, so nothing written by
this command depends on 2020 data. Writes to `outputs/baseline/`:

| File | Content |
|---|---|
| `data_quality.json` | Data-quality report for the rows used (before 2020), including the file checksum |
| `validation_predictions.csv`, `test_predictions.csv` | One row per (origin, lead): `forecast_origin_utc`, `target_timestamp_utc`, `lead_hours`, `reference_timestamp_utc`, `predicted_load_mw`, `actual_load_mw`, `status` |
| `metrics.json` | Pair counts, exclusions by reason, metrics overall and per lead hour |
| `run_metadata.json` | Environment, dataset provenance, task, splits, policies, metric definitions |

## Compare daily and weekly baselines

```bash
uv run python -m gridpulse compare --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/comparison
```

This command:

- runs both seasonal naive baselines on the same origins and periods, with 2020 dropped
  right after reading;
- aligns their predictions target by target;
- compares them on the pairs that are valid for both (the *common sample*);
- adds a calendar analysis in German local time (Europe/Berlin).

Re-running overwrites only the files listed below. Writes to `outputs/comparison/`:

| File | Content |
|---|---|
| `comparison_metrics.json` | Per period: coverage counts, exclusions by reason, paired MAE/RMSE/WAPE on the common sample, `daily_naive_minus_weekly_naive_mae_mw`, lower-absolute-error counts and ties; plus each model's standalone metrics |
| `comparison_predictions.csv` | One row per period and target: `forecast_origin_utc`, `target_timestamp_utc`, `lead_hours`, `actual_load_mw`, each model's reference timestamp and prediction, `comparison_status`, the target's local date and weekday, holiday flags, and `holiday_category` |
| `calendar_analysis.csv` | Per period: pairs, forecast origins (UTC days), local target dates, and both models' MAE and RMSE for each holiday category and target local weekday |
| `data_quality.json`, `run_metadata.json` | As for `baseline`; metadata adds the baselines, holiday dates and source, and the classification rules |

Holidays are the nine nationwide statutory public holidays (regional ones excluded),
verified against timeanddate.com and an independent computation of the Easter dates. See
the methodology for definitions and limitations.

## Train and evaluate LightGBM

```bash
uv run python -m gridpulse train-lightgbm --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/lightgbm
```

The command:

- reads the CSV once and drops 2020;
- builds the feature table by timestamp;
- trains on targets from 2015–2017, using 2018 only to choose the boosting iteration
  (early stopping);
- predicts 2018 and 2019 with the frozen model;
- compares it with both baselines on the pairs valid for all three, with the same
  calendar analysis as `compare`.

The configuration is fixed and was not tuned. In the current run, early stopping did not
trigger: the best iteration is the 500-round cap.

Re-running overwrites only the files below. Writes to `outputs/lightgbm/`:

| File | Content |
|---|---|
| `metrics.json` | Per period: coverage and exclusions; MAE/RMSE/WAPE of all three models on the common sample; LightGBM's absolute and relative MAE improvement (and RMSE difference, win counts) over each baseline; each model's standalone metrics, including per lead hour |
| `predictions.csv` | One row per period and target: origin, target, lead, actual, each model's prediction, the naive reference timestamps (which are LightGBM's lag sources), `comparison_status`, calendar labels |
| `calendar_analysis.csv` | Per period: pairs, origins, local dates, MAE and RMSE of all three models, and LightGBM − weekly MAE, for each holiday category and local weekday |
| `model.txt` | The fitted model in LightGBM's text format; reloaded and checked against the in-memory predictions on every run |
| `data_quality.json`, `run_metadata.json` | As for `compare`; metadata adds features and their availability, configuration, best iteration, training and early-stopping row counts with exclusions, the reload check and limitations |

## Current results

OPSD 2020-10-06, 365 daily forecast origins per period, no excluded pairs. All models are
scored on the same 8,760 pairs per period. MAE and RMSE in MW:

| Period | Weekly MAE | Daily MAE | LightGBM MAE | Weekly RMSE | Daily RMSE | LightGBM RMSE | Weekly WAPE | Daily WAPE | LightGBM WAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Validation (2018) | 2,555.6 | 4,607.9 | 1,505.0 | 4,364.1 | 7,017.4 | 2,717.0 | 4.49 % | 8.09 % | 2.64 % |
| Test (2019) | 2,558.1 | 4,557.7 | 1,452.4 | 4,465.0 | 6,944.0 | 2,588.9 | 4.57 % | 8.14 % | 2.59 % |

2018 is the early-stopping selection period for LightGBM; 2019 is held out.

LightGBM against the weekly naive (the stronger baseline):

- MAE is lower by 1,050.6 MW (41.1 %) in 2018 and 1,105.7 MW (43.2 %) in 2019.
- RMSE is lower too.
- LightGBM has the lower error on about 70 % of pairs.

Holidays remain its main failure. On holiday targets its MAE is about 10.5 GW, better than
the weekly naive but worse than the daily naive. Its 15 worst days hold about 68 % of its
squared error.

Between the two baselines, the weekly naive is the stronger reference on all three metrics
in both periods:

- Paired MAE difference (daily − weekly): +2,052.3 MW in 2018 and +1,999.5 MW in 2019.
- The weekly naive has the lower absolute error on about 58 % of pairs.

The calendar analysis shows:

- When exactly one of the target day and the weekly reference day is a holiday, the
  weekly naive's MAE rises to 12.9–14.6 GW; the daily naive's is lower there, at
  5.7–7.3 GW.
- The daily naive is much worse on Mondays and weekends.

These are descriptive results:

- The holiday groups contain few days.
- No significance test and no causal claim is made.
- 2019 had already been inspected in Phases 1A and 1B, so it is not an untouched
  confirmatory period. The LightGBM model itself was fixed before its single evaluation
  run.

## Research experiments (Phase 3)

**Headline results** (details, intervals and caveats in
[docs/experiment_results.md](docs/experiment_results.md)):

- **Track 1:**
  - Known-ahead holiday flags cut LightGBM MAE by about 15 % overall and by 81–85 % on
    holiday targets (exploratory: 2019 had been inspected before).
  - Rolling 56-day split-conformal 90 % intervals reach 0.89–0.91 average coverage, but
    under-cover in transition months (e.g. 0.79 in March 2018, 0.81 in December 2019) and
    on rare calendar days.
- **Track 2, evaluation half-year:**
  - Scenario-aware PV-cap rules cut simulated transformer overloads by 87–95 %, at
    1.6–1.8× the oracle's curtailed energy.
  - The point-forecast rule barely helps (448 → 439 violation steps).
  - The static 70 % cap never binds in this benchmark.
- **Negative results:**
  - The scenario risk scores show no evidence of skill relative to a 28-day
    violation-frequency reference (BSS −0.09 [−0.20, 0.01]), which also discriminates
    better.
  - Realised violations at the chosen caps were about 3× the predicted count.
  - The selective decision-assurance layer is indistinguishable from always applying the
    conservative rule. Its deferrals mark a season-long miscalibration, not individually
    unreliable days.
  - Deferral with a no-action fallback increases violations, so deferral alone is not
    safety.
- **Scope of the Track 2 results:** one 15-bus benchmark grid with synthetic profiles,
  naive forecasts and storage held at 0 MW. Depending on how the benchmark's storage data
  are read, no-action violations range from 4 to 1,571 development steps.

The pre-registered protocol is in [docs/research_protocol.md](docs/research_protocol.md).
Results, including negative ones, are in
[docs/experiment_results.md](docs/experiment_results.md).

**Track 1** studies national load: boosting cap (C1), holiday-flag ablation (C2) and
rolling split-conformal day-ahead intervals (C3).

```bash
uv run python -m gridpulse forecast-study --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/forecast_study
```

**Track 2** studies the SimBench LV grid `1-LV-rural1--2-sw` with pandapower AC power
flow. It compares day-ahead PV feed-in-cap policies:

- no action;
- a static 70 % cap;
- a point-forecast rule;
- a scenario risk rule;
- a selective rule that can defer to human review, with explicit fallbacks;
- an oracle.

Every policy runs on identical physics. Run the development period first, then the
evaluation period:

```bash
uv run python -m gridpulse grid-study --period development --output-dir outputs/grid_study
```

```bash
uv run python -m gridpulse grid-study --period evaluation --output-dir outputs/grid_study
```

Notes on the grid runs:

- Power flows run in parallel and are cached per day in
  `outputs/grid_study/physics_cache/`, which is git-ignored. A full period takes about
  10–30 minutes on 10 cores.
- Outputs per period: daily outcomes (CSV), a summary with hypothesis checks and
  block-bootstrap intervals, risk calibration, metadata, and one JSON "decision passport"
  per day. A passport records only the evidence available at the decision time.
- The two tracks are kept separate: national load is never mapped onto feeder buses.

Supporting documents:

- [docs/literature_review.md](docs/literature_review.md): prior work and an honest
  novelty assessment;
- [docs/technical_limitations.md](docs/technical_limitations.md);
- [docs/learning_guide.md](docs/learning_guide.md): the concepts needed to explain and
  defend the work.

## Research experiments (Phase 4: reliability under dual uncertainty)

**Question.** Can physically grounded, reliability-aware PV-cap decisions beat simple,
well-validated policies when the forecast *and* the grid model are uncertain?

**Design.**

- **Networks:** six SimBench LV networks. rural1 is now a development network.
- **Forecast information:** perfect, or the naive day-ahead forecast.
- **Physical model:** nine model variants of the "true" grid:
  - transformer tap;
  - MV voltage;
  - PV reactive power;
  - two readings of home-storage behaviour;
  - joint cases.
- **Policies:**
  - static caps: development-tuned, and adapted online;
  - deterministic forecast rules with and without a margin;
  - historical replay;
  - robust and risk scenario rules;
  - online-calibrated (ACI-style) margins;
  - a model-ensemble rule.

The protocol and its amendments are in s. 4 of
[docs/research_protocol.md](docs/research_protocol.md).

**Headline results** (evaluation half-year, five new networks; details, intervals and
caveats in [docs/experiment_results.md](docs/experiment_results.md)):

- **Only one SimBench LV topology is congested on its own.** In their 2034 scenario,
  rural2, rural3, semiurb4, semiurb5 and urban6 have no violations. They were scaled to the
  same PV stress as rural1 by a rule registered in advance.
- **Correct grid model.** A static cap tuned on development data curtails 30 % more than
  the oracle, with 3 violation quarter-hours in 183 days.
  - Neither online-calibrated rule beats it in aggregate.
  - The robust replay and scenario rules curtail about 5 % less, but with 16 and 34
    violation quarter-hours against 3.
  - The 7-day-mean forecast adds no value over replaying past days.
- **Model errors break model-tuned rules.** With the grid model wrong (tap, MV voltage, PV
  reactive power, joints), static and robust rules tuned with the nominal model fail the
  violation target in about half of the 50 cells.
  - The largest failures are overvoltage stress brackets on the −1-tapped networks.
  - Excluding them, they still fail 15 of 41 cells.
- **Measured feedback restores the target, under full observation.** Online margin
  calibration meets it in 46–49 of 50 cells, whether or not a grid model is used.
  - This assumes every bus voltage and branch current is observed; substation metering
    alone would miss every voltage and line violation here.
  - Replaying measured days through the AC model on top of feedback saves a median 5 % of
    curtailment, with a uniform cap across all PV units.
- **The registered H3 criterion gives "genuine value"** for that replay-plus-feedback rule,
  and for no forecast-based rule. The nominal-truth advantage is small and not uniform
  (rural3: +44 % curtailment).
- **Explicit robustness over a model ensemble** protects only against the modelled
  variants. Its out-of-list failures are marginal overvoltages. It is 5.4× as costly,
  driven by one voltage-offset member.
- **H1, selection optimism as the cause of Phase 3's 3× under-prediction,** was supported
  on rural1 by an exploratory cross-fit over most of the year.
  - On the new networks it was untestable: too few autumn violations.
  - rural1's own evaluation half is mixed: it passes for scenarios but fails the
    registered replay criteria.

Run the physics once (this is long: AC power flows for 6 networks × 10 models × 330 days;
cached and resumable), then the development and evaluation stages:

```bash
uv run python -m gridpulse dual-study --stage physics --output-dir outputs/dual_study
```

```bash
uv run python -m gridpulse dual-study --stage development --output-dir outputs/dual_study
```

```bash
uv run python -m gridpulse dual-study --stage evaluation --output-dir outputs/dual_study
```

Notes on the Phase 4 runs:

- **Runtime.** The physics is the long part.
  - Here it took about 55 CPU-hours in total, roughly 7 hours of wall time with
    `--workers 10` on a shared 11-core machine.
  - It is cached per network, model and day, so an interrupted run resumes where it
    stopped.
- **One evaluation run only.** The evaluation stage refuses to run when any
  `evaluation_*` output already exists.
- **Report tables.** They are regenerated from a stage's JSON outputs with:

```bash
uv run python docs/provenance/phase4/scripts/report/report.py evaluation > outputs/dual_study/evaluation_report.md
```

- **Provenance.** Registration timestamps, hashes and the scripts behind quoted numbers
  are in `docs/provenance/phase4/`.

## Research experiments (Phase 5: decisions under limited observability)

**Question.** How much measurement does an operator need for a reliable PV-cap decision
when most LV states are unobserved and the grid model may be wrong? And which additional
measurement is worth collecting?

**Design.**

- **Networks and periods.** The Phase 4 networks and periods are reused. rural1 is the
  development network.
- **True models.** Four:
  - correct;
  - transformer tap one step off;
  - MV voltage 1.055 p.u.;
  - PV at fixed cos φ 0.95.
- **Measurement chain.** Ground truth is separated from readings. One function turns the
  true state into readings, with:
  - noise;
  - 5 % missing remote sensor-days;
  - a one-day delay for smart-meter data.
- **Measurement configurations.**
  - transformer only;
  - substation (transformer plus feeder heads);
  - substation plus 1, 2 or 4 smart-meter voltages, placed by six rules on development
    data;
  - every bus and cable ("full").
- **Methods.**
  - WLS state estimation with forecast pseudo-measurements and a numerical observability
    test;
  - evidence labels: INSUFFICIENT_EVIDENCE, MODEL_INCONSISTENCY, NO_FEASIBLE_ACTION.

The protocol, with amendments 5A–5C, is
[docs/phase5_protocol.md](docs/phase5_protocol.md). The results are in
[docs/phase5_results.md](docs/phase5_results.md).

**Headline results** (exploratory replication on five PV-stressed benchmark networks;
reviewed after the run, details in the results document):

- **Substation telemetry sees transformer and feeder-head overloads but detects no remote
  overvoltage as such.**
  - Under voltage-offset model errors its voltage recall is 0.14–0.45.
  - Feedback driven by it meets the violation target in 4 of 15 model-error cases.
- **With realistic meter noise, one or two smart-meter voltages raised this to 12–14 of
  15.** Every bus metered gives 15. The registered primary hypothesis is supported, but
  only in the evaluation half-year.
  - In the development half, where the online margin is still being learned, the counts
    were 0, 4 and 6.
  - With exact readings, two sensors reach only 9.
- **Much of that recovery is noise.**
  - Noisy readings near the limit raise false alarms, which the feedback turns into
    curtailment.
  - Under the correct model, curtailment is 145 MWh with two sensors and 321 MWh with
    full metering, against about 53 MWh with exact readings in every configuration.
  - In one network, the alarms drove the margin to its bound, and the NO_FEASIBLE_ACTION
    fallback curtailed all PV on the affected quarter-hours of up to 28 days.
- **Placement.**
  - Under noise, decision-aware placement was no better than simple rules, but all rules
    tied on cells.
  - With exact readings it met 13 cells against 9 for feeder-end placement.
- **Threshold detection on remote voltages misses mid-feeder cable overloads.**
- **Substation readings plus metered injections flag a wrong model** on 88–100 % of
  model-error days and on no correct-model day. This is idealised and does not say which
  parameter is wrong.
- **State estimation from substation readings plus forecasts.**
  - It detects 0.88–1.0 of the remote overvoltages caused by voltage offsets.
  - It gives confident gross errors under a PV reactive-power model error. It has no
    bad-data test.
  - Its false alarms exceeded the registered gate, narrowly, so it was not used for
    decisions in the evaluation.

Run the full-state physics once (4 truths × 6 networks × 330 days, cached and
resumable), then the development and evaluation stages:

```bash
uv run python -m gridpulse sense-study --stage physics --output-dir outputs/sense_study
```

```bash
uv run python -m gridpulse sense-study --stage development --output-dir outputs/sense_study
```

```bash
uv run python -m gridpulse sense-study --stage evaluation --output-dir outputs/sense_study
```

Notes on the Phase 5 runs:

- **Dependency.** The development and evaluation stages read the Phase 4 physics cache in
  `outputs/dual_study/physics_cache` for the nominal-model plans, so run the Phase 4
  physics first.
- **Runtime and size.** The full-state cache takes about 0.9 GB. The evaluation stage
  took about 17 minutes of wall time on a shared 11-core machine.
- **One evaluation run only.** As in Phase 4, the evaluation stage refuses to run when
  any `evaluation_*` output exists.
- **Report tables.** Regenerate them with:

```bash
uv run python docs/provenance/phase5/scripts/report.py evaluation > outputs/sense_study/logs/evaluation_report.md
```

## Research experiments (Phase 6: measurement integrity and noise-aware feedback)

**Question.** Can measurement-aware feedback improve reliability without the noise-driven
over-curtailment found in Phase 5? And which measurements have real decision value once
noise and false alarms are accounted for?

**What changed.**

- **Measurement noise is now tied to the physical observation.** Identical sensors get
  identical noise in every comparison. Phase 5 seeded noise from configuration names.
- **Registered study stages are protected.** Manifests, atomic writes, a freeze bound to
  the development code, and refusal of reruns or stale outputs.
- **The Phase 5 code path and its frozen results are unchanged.** The repair is a new,
  opt-in path.

The protocol (with amendment 6A) is [docs/phase6_protocol.md](docs/phase6_protocol.md),
and the results are in [docs/phase6_results.md](docs/phase6_results.md). This is a
corrected, exploratory replication on previously examined benchmark data, not a
confirmatory test.

**Headline results** (five PV-stressed SimBench networks, evaluation half-year):

- **The Phase 5 over-curtailment is real.** It survives the seeding repair: with two
  noisy meters, unfiltered feedback curtails 144 MWh under the correct grid model,
  against 53 MWh with exact readings.
- **A 45-minute persistence rule on meter voltages removes almost all of it**, under the
  correct model and for meter noise that is independent per reading: 55 MWh with two
  meters, 69 MWh with every bus metered. With per-meter calibration bias it does not.
- **But under model errors, its reliability largely comes from the noise.**
  - Its mismatch-case count rises with noise, from 4 to 14 of 15 between exact readings
    and σ = 0.02.
  - With exact readings, two meters under this rule add nothing over substation
    telemetry (4 vs 4). Closed-loop violations are mostly shorter than 45 minutes.
  - It is a cost control, not a noise-robust reliability mechanism.
- **Remote voltage readings do carry information.** With exact readings and unfiltered
  feedback, two meters meet 9 of 15 cases against 4.
  - Under the persistence rule, placement matters: well-placed pairs meet 11–14 cases,
    random pairs a median of 7.
  - No tested rule realises the meters' exact-reading value under noise without relying
    on the noise.
- **Per-meter calibration bias makes the outcomes depend on the individual meters'
  offsets.** Two meters meet 6–11 of 15 cases, depending on the bias draw. Full metering
  stays reliable but curtails 90–150 MWh under the correct model. No reading-level filter
  removes a constant offset; that needs calibration.
- **The chi-square bad-data test detects a reactive-power imbalance, but it cannot
  certify a state estimate.** Under the correct model it is miscalibrated and misses
  plausible gross errors.

Run the development stage, freeze, then the single evaluation. All reuse the Phase 4 and
Phase 5 physics caches:

```bash
uv run python -m gridpulse noise-study --stage development --output-dir outputs/noise_study
```

```bash
uv run python -m gridpulse noise-study --stage freeze --output-dir outputs/noise_study
```

```bash
uv run python -m gridpulse noise-study --stage evaluation --output-dir outputs/noise_study
```

Each stage took about 17–19 minutes with 3 workers. Report tables:

```bash
uv run python docs/provenance/phase6/scripts/report.py evaluation > outputs/noise_study/logs/evaluation_report.md
```

## Research experiments (Phase 7: continuous margins and model-residual correction)

**Question.** Can continuous, uncertainty-aware constraint-margin estimates improve
decisions over binary threshold alarms, under limited observability and model mismatch?

**What changed.**

- **The planner now uses continuous substation residuals instead of counted alarms.**
  - The busbar voltage minus the nominal model's prediction at the metered injections
    gives an offset v̂.
  - The transformer and feeder-head current ratios give ρ.
  - The replayed nominal exceedances are corrected by v̂ and ρ, with a fixed safety margin
    tuned on development days. This is the classic offset-free MPC bias update, not a new
    method.
- **Remote meters are checked** against the busbar residual. Evidence labels separate
  "meter bias suspected" from "cannot tell bias from model error"; they never estimate a
  bias.
- **The Phase 4–6 code paths and frozen results are unchanged.** The corrector is opt-in.

The protocol (with amendment 7A) is [docs/phase7_protocol.md](docs/phase7_protocol.md),
and the results are in [docs/phase7_results.md](docs/phase7_results.md). This is an
exploratory replication on previously examined benchmark data, not a confirmatory test.

**Headline results** (five SimBench networks, evaluation half-year):

- **The registered primary hypothesis is not met.**
  - Substation-only correction has 1 violation under the three model errors, against 513
    for binary feedback with two exact remote meters, at 41 % more curtailment.
  - But under the correct model it curtails 27 % more than binary substation feedback
    (66.2 vs 52.3 MWh; the limit was 10 %). That cost is the cost of its registered
    safety margin.
- **Reliability under the tested model errors is large and consistent:** 15 of 15 cases,
  against 9 for two exact meters and 14 for exact full metering. The busbar residual
  matches the true tap or MV offset to within 0.0001 p.u., and so also protects buses no
  sensor sees.
- **It depends on two things the binary policies do not:**
  - an accurate busbar voltage: the tolerated bias is about the safety margin, and −0.005
    p.u. costs 260 violations;
  - exact customer injection data, which were assumed and not tested.
- **Remote meters add almost nothing** for these common-mode errors once the correction is
  in place. Local errors (argued, not tested, to be beyond what the substation can
  attribute) and time-varying errors (lagged by the daily averaging) were not tested.

Run the development stage, freeze, then the single evaluation. All reuse the Phase 4 and
Phase 5 physics caches:

```bash
uv run python -m gridpulse margin-study --stage development --output-dir outputs/margin_study
```

```bash
uv run python -m gridpulse margin-study --stage freeze --output-dir outputs/margin_study
```

```bash
uv run python -m gridpulse margin-study --stage evaluation --output-dir outputs/margin_study
```

Each stage took 2–3 minutes with 3 workers. The code has changed since the freeze, for
the demonstrator and review fixes, so a new evaluation is refused, by design
([docs/provenance/phase7/README.md](docs/provenance/phase7/README.md)). Report tables:

```bash
uv run python docs/provenance/phase7/scripts/report.py evaluation > outputs/margin_study/logs/evaluation_report.md
```

**Exploratory demonstrator.** This writes one static HTML page (no scripts, no network
access) for a network and truth. The page re-runs three frozen policies, checks them
against the frozen outputs, and shows:
- what is measured;
- the true signed margins on the network diagram;
- the caps per quarter-hour and the operator's estimates.

It is synthetic benchmark data, not an operator tool:

```bash
uv run python -m gridpulse demonstrate --network 1-LV-semiurb4--2-sw --truth tap_raise_lv --output-dir outputs/demonstrator
```

## Research experiments (Phase 8: constraint-specific reserves and data availability)

**Questions.**

- Can physically separate voltage and loading reserves cut the Phase 7 correction's
  curtailment without losing its reliability?
- How sensitive is it to imperfect customer data, to substation instrumentation, and to
  model errors not tested before?

The protocol (with amendment 8A, made before any development run) is
[docs/phase8_protocol.md](docs/phase8_protocol.md), and the results are in
[docs/phase8_results.md](docs/phase8_results.md). This is an exploratory mechanism study
on previously examined benchmark data, not a confirmatory test.

**Headline results** (five SimBench networks, evaluation half-year):

- **Both registered hypotheses failed.**
  - Fixed separate reserves kept Phase 7's reliability but saved only 2.6 % under model
    errors (the target was 10 %).
  - A shared margin on the same fine grid saved as much under the correct model and more
    under model errors (5.4 %). With the registered tap-step voltage rule, separation
    added nothing; other rules were not tested.
- **Daily re-tuned reserves curtailed 16–20 % less in the evaluation half** and met the
  requirement everywhere. But they gave up the near-zero violation level (29 against 1).
  In the other half-year (rising PV) they were the most reliable policy under model
  errors, still failed three cases, and cost 12 % more under the correct model.
- **Customer data.** Meter noise, an assumed load power factor, PV recorded 5 % high and
  10 % missing data met the registered robustness rule. PV over-recording was traded
  rather than absorbed: the re-tuned margins grew. A two-day data delay failed the rule
  for the fixed-reserve policies (C1, C5): it cost them 31–36 % more curtailment.
- **Substation instrumentation.** A low-reading busbar voltage (−0.005 p.u.) produced the
  most violations of any tested condition. Here, the smaller the reserve, the smaller
  the bias it tolerated.
- **Stress cases, all as predicted before the physics was run.**
  - Every corrected policy handles an opposite-direction tap error.
  - No attainable policy handles an MV voltage that rises with PV within the day.
  - No attainable policy handles a cable whose recorded thermal rating is wrong. The flows
    match the model, and no tested measurement or policy revealed the overload.

Run the stages in order. They reuse the Phase 4/5 caches and add about 1.6 GB of new
physics:

```bash
uv run python -m gridpulse robust-study --stage physics --output-dir outputs/robust_study
```

```bash
uv run python -m gridpulse robust-study --stage development --output-dir outputs/robust_study
```

```bash
uv run python -m gridpulse robust-study --stage freeze --output-dir outputs/robust_study
```

```bash
uv run python -m gridpulse robust-study --stage evaluation --output-dir outputs/robust_study
```

The physics took about 1 h 50 min with 3 workers, development 5 min and evaluation 10 min.
Report tables:

```bash
uv run python docs/provenance/phase8/scripts/report.py evaluation > outputs/robust_study/logs/evaluation_report.md
```

Phase 8 demonstrator page, for any registered network and truth, including the stress
truths:

```bash
uv run python -m gridpulse demonstrate --phase 8 --network 1-LV-rural3--2-sw --truth mv_daily --output-dir outputs/demonstrator
```

## Tests and checks

```bash
uv run pytest
```

```bash
uv run ruff check . && uv run ruff format --check .
```

Unit tests use small synthetic fixtures and do not need the dataset download.

## Repository layout

```
src/gridpulse/data.py        loading, validation, hourly grid, data-quality report, splits
src/gridpulse/baseline.py    forecasting task definition, daily and weekly seasonal naive
src/gridpulse/evaluation.py  timestamp alignment, exclusion accounting, metrics, paired comparison
src/gridpulse/calendar_analysis.py  German holiday table, local-time labels, calendar breakdown
src/gridpulse/features.py    leak-free feature table (lags by timestamp, local calendar)
src/gridpulse/model.py       LightGBM configuration, training, prediction, save/reload check
src/gridpulse/uncertainty.py rolling split-conformal intervals, circular block bootstrap
src/gridpulse/forecast_study.py  Track 1 experiments C1-C3
src/gridpulse/grid.py        SimBench network and profiles, AC power-flow margins, PV cap
src/gridpulse/grid_study.py  Track 2 scenarios, policies, deferral, calibration, passports
src/gridpulse/dual_study.py  Phase 4 model variants, PV stress rule, policies, online calibration
src/gridpulse/fullstate.py   Phase 5 full network states per true model (cached)
src/gridpulse/sensing.py     Phase 5 measurement model, placement, detection, feedback, labels
src/gridpulse/estimation.py  Phase 5 WLS state estimation, pseudo-measurements, observability
src/gridpulse/noise_study.py Phase 6 noise-aware feedback study, hypotheses, state-estimation test
src/gridpulse/runguard.py    Phase 6 stage manifests, atomic writes, freeze and rerun protection
src/gridpulse/margins.py     Phase 7 signed margins, residual corrector, evidence labels, coverage
src/gridpulse/margin_study.py  Phase 7 study plan, observability, hypotheses
src/gridpulse/demonstrator.py  Phase 7/8 exploratory static-HTML demonstrator
src/gridpulse/reserves.py    Phase 8 separate voltage/loading reserves, delayed data, outages
src/gridpulse/stress.py      Phase 8 stress-truth and metered-injection physics (own cache)
src/gridpulse/robust_study.py  Phase 8 study plan, checks, hypotheses
src/gridpulse/__main__.py    command-line interface and output/metadata writing
tests/                       unit tests and end-to-end CLI tests on synthetic data
docs/methodology.md          Phase 0-2A protocol, decisions, limitations
docs/research_protocol.md    pre-registered protocols: Phase 3 (both tracks) and Phase 4
docs/experiment_results.md   Phase 3 and 4 results, exploratory and negative findings
docs/phase5_protocol.md      Phase 5 pre-registered protocol and amendments
docs/phase5_literature.md    Phase 5 literature review
docs/phase5_results.md       Phase 5 results, verdicts and limitations
docs/phase6_protocol.md      Phase 6 pre-registered protocol and amendment 6A
docs/phase6_literature.md    Phase 6 literature review
docs/phase6_results.md       Phase 6 results, verdicts and limitations
docs/phase7_protocol.md      Phase 7 pre-registered protocol and amendment 7A
docs/phase7_literature.md    Phase 7 literature review
docs/phase7_results.md       Phase 7 results, verdicts, reviews and limitations
docs/phase8_protocol.md      Phase 8 pre-registered protocol and amendment 8A
docs/phase8_literature.md    Phase 8 literature review
docs/phase8_results.md       Phase 8 results, verdicts, reviews and limitations
docs/provenance/             per-phase registration logs, hashes and report scripts
docs/learning_guide.md       concepts behind the methods, with equations and code locations
docs/technical_limitations.md  limitations across all phases
docs/utility_application_concept.md  how the methods could support offline network analyses (not validated)
```
