# GridPulse

Explainable electricity load forecasting and machine learning reliability.

GridPulse is an independent applied-AI research project. Its long-term question is
how well electricity load forecasting models perform, and how reliable they remain,
when temporal and data conditions change. This repository currently contains only the
research foundation: a validated dataset pipeline, two deliberately simple reference
forecasts, one learned model (LightGBM), and leakage-free, paired temporal evaluation.

## Current scope (Phases 0, 1, 1B and 2A)

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
- Chronological train / validation / test periods, with 2020 reserved and unused.
- MAE, RMSE and WAPE on valid prediction/target pairs only, overall and per lead hour,
  with explicit counts of excluded pairs.
- Auditable outputs: every prediction records the exact historical timestamp it came from.

Not implemented (and not claimed):

- hyperparameter tuning, other model families, deep learning or ensembles;
- holiday-aware forecasting;
- explainability, uncertainty estimation or calibration;
- distribution-shift experiments;
- weather or other external data;
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

```bash
uv sync
```

Without uv: create a virtual environment, then `pip install -e . pytest ruff`
(dependency versions will then not be locked).

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
src/gridpulse/__main__.py    command-line interface and output/metadata writing
tests/                       unit tests and end-to-end CLI tests on synthetic data
docs/methodology.md          experimental protocol, decisions, limitations
```
