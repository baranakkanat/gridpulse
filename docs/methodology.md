# Methodology

This document defines the GridPulse experiments (Phases 0 to 2A) precisely enough to be
audited and repeated. It describes what has been done, not planned work.

## 1. Forecasting problem

Predict the next 24 hourly values of German electricity load, once per day.

- **Forecast origin:** 00:00 UTC on the target day *D*.
- **Targets:** the 24 hourly intervals starting at 00:00, 01:00, …, 23:00 UTC on *D*.
- **Lead time:** lead *h* ∈ {1, …, 24} is the interval starting at origin + (*h* − 1) h.
  Lead 1 is the interval starting at the origin; lead 24 starts 23 hours after it.
- **Frequency:** one forecast per UTC day.

This is a batch forecast of the next 24 UTC hours. It is **not** a reproduction of the
German day-ahead market process, which closes around noon local time on the previous day
and covers a local-time delivery day. Here the forecaster is assumed to know all
observations up to the origin, which is more information than a day-ahead participant has.

## 2. Dataset and target

Open Power System Data, *Time series*, version 2020-10-06
(DOI [10.25832/time_series/2020-10-06](https://doi.org/10.25832/time_series/2020-10-06)),
file `time_series_60min_singleindex.csv`. Only two of its 300 columns are read:

- `utc_timestamp`: start of the hourly period in UTC (format `2015-01-01T00:00:00Z`);
- `DE_load_actual_entsoe_transparency`: "Total load in Germany in MW as published on
  ENTSO-E Transparency Platform" (OPSD field description).

The target is the *actual* load. The file also contains a day-ahead load *forecast*
(`DE_load_forecast_entsoe_transparency`), generation and price columns; none are used.

### Validation findings (computed from the file)

From `python -m gridpulse validate`, which audits the whole file, including the reserved
period:

| Check | Result |
|---|---|
| SHA-256 | `6a7f2bc5…c704c8`, identical to the `hash` in the official `datapackage.json` |
| Rows | 50,401 |
| First / last timestamp | 2014-12-31T23:00Z / 2020-09-30T23:00Z |
| Intervals | all 50,400 consecutive steps are exactly 1 h; no duplicates, no gaps |
| Missing target values | 1, at 2014-12-31T23:00Z (before the train period) |
| Non-finite, negative, zero values | none |
| Available values per year | 2015: 8,760 · 2016: 8,784 · 2017: 8,760 · 2018: 8,760 · 2019: 8,760 · 2020: 6,576 (to 30 Sep) |
| Range | 31,307 to 77,549 MW; median 55,092 MW (whole file), 55,467 MW (before 2020) |

The first row is local (CET) midnight of 2015-01-01, which is why the file starts at 23:00
UTC. Train, validation and test periods are therefore complete.

**Suspicious observations (not modified).** Most of the largest hour-to-hour changes are
early-morning increases of about +10 GW (04:00–06:00 UTC) at the start of a working week.
Two September/October 2015 events look different:

- At 2015-09-21T10:00Z the load drops by −11,353 MW at midday. It stays roughly 11 GW low
  for about 20 hours, and the +10,957 MW change at 2015-09-22T06:00Z appears to be the
  recovery.
- At 2015-10-02T11:00Z there is a similar −11,675 MW midday drop.

These look like level shifts in the source data rather than real demand behavior. They
fall in the train period, so they do not affect validation or test metrics. They are
reported in `data_quality.json` and left unchanged.

## 3. Physical unit

Values are electrical load (power) in **MW**, not energy. Each value is the hourly figure
published by OPSD for the interval starting at its timestamp. The ENTSO-E data for Germany
are published at a finer resolution. *Unverified assumption:* OPSD's 60-minute value is
the mean power over the hour. The aggregation is defined by OPSD's processing script and
was not re-derived here. Its definition of "total load" follows ENTSO-E/TSO conventions and
may differ from national consumption statistics.

## 4. Information available at the origin

A forecast for origin *O* may use only observations whose intervals start before *O*.
It never uses:

- actual load from any target interval;
- future values as features;
- centered windows or retrospective transformations.

The data are the 2020 snapshot of each value. Real-time vintages and publication delays are
not modelled (see Limitations).

## 5. Time convention

- All timestamps are timezone-aware UTC internally and in every output.
- Timestamps without an explicit UTC designator are rejected rather than assumed to be UTC.
- Each timestamp denotes the *start* of its hourly interval.
- Fixed UTC days avoid 23- and 25-hour local days at daylight-saving transitions.
- Electricity demand follows local time. In UTC, the daily load profile therefore shifts by
  one hour between winter (CET) and summer (CEST).

## 6. Chronological splits

Half-open UTC intervals `[start, end)`:

| Period | Start | End (exclusive) | Last hour |
|---|---|---|---|
| Train | 2015-01-01T00:00Z | 2018-01-01T00:00Z | 2017-12-31T23:00Z |
| Validation | 2018-01-01T00:00Z | 2019-01-01T00:00Z | 2018-12-31T23:00Z |
| Test | 2019-01-01T00:00Z | 2020-01-01T00:00Z | 2019-12-31T23:00Z |
| Reserved | 2020-01-01T00:00Z | (end of data) | — |

- Validation and test each have 365 daily origins, and every target lies inside its own
  period. The two target sets do not overlap.
- An origin may use history from earlier periods. For example, the first test origin
  (2019-01-01) uses observations from 2018-12-25. This is information that would have been
  available in real operation; it is not training on the evaluation period.
- The `baseline` and `compare` commands drop observations from 2020 onward immediately
  after reading the file, before any check, statistic or forecast. Their outputs,
  including `data_quality.json`, contain no 2020 load information. A test checks, for both
  commands, that corrupting or duplicating 2020 rows leaves every experiment output
  unchanged.
- The separate `validate` command audits the whole file, including the availability and
  summary statistics of 2020 shown in section 2. No implementation choice was based on
  them.
- The proposed split had complete coverage, so it was used unchanged.
- The train period is defined for protocol consistency. Neither baseline has parameters,
  so nothing is fitted on it.

## 7. Seasonal naive baselines

For target timestamp *t* and season length *s*:

```
prediction(t) = load(t − s)
weekly naive: s = 168 h        daily naive: s = 24 h
```

- **Weekly naive** keeps the same weekday and UTC hour. For an origin at 00:00 UTC its
  references lie 168 h (lead 1) to 145 h (lead 24) before the origin.
- **Daily naive** uses the previous UTC day: for origin *O*, the references of leads
  1–24 are *O* − 24 h, …, *O* − 1 h. The latest one ends exactly at the origin.
- Both use the same function with a season-length parameter. It rejects any season
  shorter than the 24-hour horizon, because some reference would then fall at or after the
  origin, and any season that is not a whole number of hours.
- References are looked up by timestamp label, never by row position. A test removes an
  hour from the index and checks that no prediction shifts to the wrong hour; for the
  daily naive the removed hour becomes a missing prediction.
- Both are deterministic, have no fitted parameters and are not tuned.

## 8. Missing-data handling

- Target values are never filled with zero, interpolated, clipped or otherwise repaired.
- Timestamps absent from the source and non-finite values are treated as *unavailable*.
- Only empty fields count as missing. Any other non-numeric text, including `NA`, `null`
  or `nan`, makes the file fail to load rather than being silently treated as missing.
- Each (origin, lead) pair of a single model gets a `status`:
  - `valid`;
  - `reference_unavailable`: no prediction can be made;
  - `target_unavailable`: there is nothing to score against;
  - `reference_and_target_unavailable`.
- In the comparison, each target row gets a `comparison_status`:
  - `common_valid`: the target and both models' references are available;
  - `target_unavailable`;
  - `daily_naive_reference_unavailable`, `weekly_naive_reference_unavailable`, or
    `both_references_unavailable`.

  An unavailable target takes precedence, so a row with a missing target is counted as
  `target_unavailable` even if a reference is also missing.
- Metrics use valid pairs only. The output JSON reports the counts behind each metric:
  possible origins and targets, available targets, valid pairs per model, common-valid
  pairs, and exclusions by reason.
- **Possible bias:** if missing data clustered in particular hours or seasons, metrics would
  describe a non-representative subset. In these runs no pair was excluded (8,760 of 8,760
  common-valid in both periods), so this bias does not arise here.

## 9. Evaluation metrics and paired comparison

With *y* the actual and *ŷ* the predicted load over *n* valid pairs:

- **MAE** = mean(|*y* − *ŷ*|), in MW.
- **RMSE** = sqrt(mean((*y* − *ŷ*)²)), in MW.
- **WAPE** = 100 · Σ|*y* − *ŷ*| / Σ|*y*|, in %. It is undefined when Σ|*y*| = 0 and then
  raises an error rather than returning a value. Unlike MAPE, it does not average
  per-point percentage errors.

Metric functions reject empty, mismatched or non-finite inputs. Predictions and actuals are
always joined on `target_timestamp_utc`.

Metrics are reported overall and per lead hour. Because every origin is at 00:00 UTC, lead
*h* is always the UTC hour *h* − 1. For the weekly naive every reference is 145–168 h old,
so its per-lead profile reflects time-of-day effects, not forecast-horizon effects.

**Fair comparison.** Both models are scored with the same origins, targets, periods, unit
and metric functions:

- The comparison table is built only if both models were evaluated on exactly the same
  (origin, target, lead) rows with the same observed load; otherwise it is an error.
- The **primary (paired) comparison** uses only `common_valid` rows, so both models are
  scored on an identical sample. The paired scoring function refuses any other row.
- **Standalone** metrics, each model on its own valid pairs, are reported separately. The
  weekly standalone metrics are the Phase 1A metrics.
- **Paired MAE difference:** `daily_naive_minus_weekly_naive_mae_mw` = MAE(daily) −
  MAE(weekly) on the common sample. Positive means the weekly naive has lower MAE.
- **Lower absolute error:** the number and share of common pairs where each model's
  absolute error is strictly lower than the other's. Exactly equal absolute errors are
  counted as ties.
- No significance test is reported. Hourly errors are strongly autocorrelated within a day
  and across days, so a standard test that treats the 8,760 pairs as independent would
  overstate the evidence.

### Results (single run, OPSD 2020-10-06)

Paired comparison on 8,760 common-valid pairs per period. Standalone and paired values are
identical here because no pair was excluded.

| Period | Weekly MAE | Daily MAE | Weekly RMSE | Daily RMSE | Weekly WAPE | Daily WAPE |
|---|---:|---:|---:|---:|---:|---:|
| Validation (2018) | 2,555.6 MW | 4,607.9 MW | 4,364.1 MW | 7,017.4 MW | 4.49 % | 8.09 % |
| Test (2019) | 2,558.1 MW | 4,557.7 MW | 4,465.0 MW | 6,944.0 MW | 4.57 % | 8.14 % |

| Period | Daily − weekly MAE | Weekly lower error | Daily lower error | Ties |
|---|---:|---:|---:|---:|
| Validation (2018) | +2,052.3 MW | 5,076 (57.9 %) | 3,683 (42.0 %) | 1 |
| Test (2019) | +1,999.5 MW | 5,105 (58.3 %) | 3,653 (41.7 %) | 2 |

- The weekly naive has the lower MAE, RMSE and WAPE in both periods.
- The weekly naive results are identical to Phase 1A (see section 12).
- During development all six metric values per period were re-derived with a separate
  throwaway script (positional 24- and 168-row shifts on the raw file, valid because it
  has no gaps). It matched to six decimals. The script is not part of the repository.

The weekly naive's errors are heavy-tailed: RMSE ≈ 1.7 × MAE, and in Phase 1A the 15 worst
days accounted for about 55 % of its squared error. Most of those days were holidays,
Christmas Eve, or days whose weekly reference was a holiday. Section 10 analyses the
holiday part systematically.

## 10. Calendar analysis

Holiday labels are used **only to group already-made forecasts** for error analysis. They
are never used to produce or adjust a forecast.

**Holiday definition.**

- *Included:* nationwide statutory public holidays in Germany — New Year's Day, Good
  Friday, Easter Monday, Labour Day (1 May), Ascension Day, Whit Monday, Day of German
  Unity (3 October), Christmas Day and the Second Day of Christmas.
- *Excluded:*
  - holidays of only some federal states, e.g. Epiphany, Corpus Christi, Reformation Day
    from 2018, All Saints' Day, Repentance Day, International Women's Day (Berlin);
  - Easter and Whit Sunday, which are Sundays anyway;
  - Christmas Eve and New Year's Eve, which are not statutory holidays.

**Source and verification.**

- The dates were checked against timeanddate.com ("Holidays and Observances in Germany"
  for 2017–2020, rows of type "National Holiday") on 2026-10-17.
- A unit test re-derives every date independently: fixed-date holidays plus
  Easter-dependent holidays from the Gregorian computus.
- The table covers German local dates 2017-12-25 to 2020-01-01. These are all the dates
  that evaluated targets and their daily or weekly references can fall on, including:
  - Christmas 2017, the weekly references of the first validation days;
  - New Year's Day 2020: the last test target, 2019-12-31T23:00Z, is 00:00 on 1 January
    2020 in Germany. Only this calendar date is used; no 2020 load data enters.
- A timestamp outside the covered range raises an error instead of being silently counted
  as an ordinary day.

**German local time and daylight saving.**

- Forecasting stays UTC-based. Only for classification, each UTC timestamp is converted to
  Europe/Berlin, and its local calendar date is compared with the holiday table, hour by
  hour.
- A German holiday therefore covers 2018-12-24T23:00Z–2018-12-25T22:59Z in winter (CET,
  UTC+1) and, for example, 2018-05-20T22:00Z–2018-05-21T21:59Z in summer (CEST, UTC+2). It
  touches two UTC forecast days.
- Local calendar days have 23 hours (last Sunday of March) or 25 hours (last Sunday of
  October). UTC forecast days always have 24. The two are never assumed to coincide; the
  tests check the 23/25-hour days and the hour-by-hour classification.

**Categories.** Each target row gets one category, combining the target's local date and
the weekly naive's reference local date. The same categories are used for both models, so
both are always compared on the same subsets.

| Category | Target is holiday | Weekly reference is holiday |
|---|---|---|
| `neither_holiday` | no | no |
| `target_holiday_only` | yes | no |
| `weekly_reference_holiday_only` | no | yes |
| `both_holidays` | yes | yes |

Each group reports, for common-valid pairs only:

- `n_pairs`;
- `n_forecast_origins` (distinct UTC forecast days);
- `n_local_target_dates`. A local date counts even if only one hour of it is in the
  group; for example, the validation period's last UTC hour is 1 January 2019 in Germany;
- MAE and RMSE of both models;
- the daily − weekly MAE difference.

Empty groups are listed with empty metrics. The same table is also reported by the
target's German local weekday. Weekday groups include holiday rows and days after
holidays; they are not restricted to ordinary days. The prediction table records `target_is_holiday`,
`weekly_reference_is_holiday` and `daily_reference_is_holiday` for every row.

### Results (MAE in MW, common-valid pairs)

| Category | Pairs | UTC days | Local dates | 2018 daily / weekly | 2019 daily / weekly |
|---|---:|---:|---:|---:|---:|
| `neither_holiday` | 8,352 | 363 | 348 | 4,522.8 / 2,042.6 | 4,481.2 / 2,009.0 |
| `target_holiday_only` | 192 | 15 | 8 | 5,995.9 / 14,646.1 | 6,935.0 / 14,581.4 |
| `weekly_reference_holiday_only` | 192 | 16 | 8 | 7,273.2 / 12,856.7 | 5,722.8 / 14,482.5 |
| `both_holidays` | 24 | 2 | 2 | 1,764.1 / 1,929.7 | 2,821.7 / 2,087.2 |

Group sizes are the same in both years. RMSE values are in `calendar_analysis.csv`.

| Target local weekday | 2018 daily / weekly | 2019 daily / weekly |
|---|---:|---:|
| Monday | 11,537.7 / 3,288.3 | 11,681.4 / 3,037.2 |
| Tuesday | 2,588.9 / 2,839.4 | 2,561.3 / 2,169.3 |
| Wednesday | 1,583.9 / 2,730.3 | 1,451.1 / 2,689.0 |
| Thursday | 1,607.6 / 3,071.6 | 1,801.2 / 3,372.6 |
| Friday | 1,945.9 / 2,673.4 | 2,103.5 / 3,293.0 |
| Saturday | 8,187.1 / 1,658.7 | 8,174.0 / 1,752.6 |
| Sunday | 4,677.9 / 1,613.7 | 4,170.6 / 1,600.5 |

**Descriptive observations, consistent in both years.**

- On ordinary days (`neither_holiday`) the weekly naive's MAE is less than half the daily
  naive's.
- When exactly one of the target and the weekly reference is a holiday
  (`target_holiday_only`, `weekly_reference_holiday_only`), the weekly naive's MAE rises
  to 12.9–14.6 GW. The daily naive's is lower there, at 5.7–7.3 GW, though still worse
  than its own ordinary-day level.
- In the very small `both_holidays` group (24 pairs), both models are at 1.8–2.8 GW, and
  neither is better in both years.
- By weekday, the daily naive is far worse on Mondays, Saturdays and Sundays, when the
  previous day is a different kind of day. It is better than the weekly naive on
  Wednesdays to Fridays.

**Limitations of the holiday analysis.**

- **Few days.** Each holiday group contains only 8 local dates per year. `both_holidays`
  has 24 pairs: 23 hours of 1 January plus the first local hour of the following
  1 January. The 24 hours of a day are
  strongly dependent, so the effective sample is closer to 8 days than to 192
  observations. No significance is claimed.
- **Weekday confounding.** Categories are not balanced by weekday. Several holidays follow
  a Sunday or another holiday (Easter Monday, Whit Monday, 26 December), which favours the
  daily naive on those dates.
- **Days after a holiday.** `neither_holiday` includes 168 rows per year (7 local days)
  whose *daily* reference is a holiday. These raise the daily naive's error in that group.
- **Coarse definition.** Bridge days, school holidays, the Christmas-to-New-Year period and
  regional holidays are not labelled, although they plausibly affect load.
- **Association only.** These are associations in a retrospective error analysis, not
  evidence of a causal effect of holidays.

## 11. Exploratory and confirmatory use of the periods

- 2018 (validation) is the primary exploratory period.
- The 2019 (test) results were already inspected in Phase 1A. The holiday weakness was
  noticed partly from 2019's worst days. 2019 is therefore **not** an untouched
  confirmatory period for the holiday question.
- The category definitions, holiday table and metrics above were fixed before the real
  comparison was run and were applied unchanged to both years. No model, parameter or
  definition was tuned or selected on 2019 results.
- The holiday hypothesis was not established before examining 2019, and is not presented
  as such.
- 2020 remains reserved for a future, separately specified experiment. No model was
  evaluated on it.
- The same rules apply to the LightGBM experiment; see section 13.9.

## 12. Leakage prevention and regression

- The forecast function rejects any season length that would put a reference at or after
  its origin.
- Every output row records each model's reference timestamp, so the source observation of
  each prediction can be audited.
- A regression test forecasts each origin twice, for both season lengths: once with the
  data unchanged, and once after overwriting every observation at or after that origin.
  The outputs must be identical.
- Splits are chronological. Nothing is shuffled, tuned or selected on validation or test
  results, and 2020 is excluded before forecasting.
- Phase 1B regression check: after the changes, the `baseline` command reproduced the
  Phase 1A prediction, metric and data-quality files byte for byte. `run_metadata.json`
  differed only in its run timestamp. The weekly standalone metrics in
  `comparison_metrics.json` equal the Phase 1A `metrics.json` exactly.
- Mutation checks run on throwaway copies of the code confirmed that the tests fail if:
  - the daily reference is wrong;
  - references are matched by row position;
  - target-day actuals are used;
  - UTC dates are treated as German local dates;
  - each model is scored on its own sample instead of the common one.

## 13. Phase 2A: first learned model (LightGBM)

### 13.1 Research question

Can a gradient-boosted model, given only historical load and calendar information known
at the forecast origin, beat the seasonal naive baselines on exactly the same forecast
targets? And do its gains hold across calendar conditions, or do weaknesses remain?

The dataset, target, forecast task (00:00 UTC origins, 24 hourly targets, leads 1–24),
splits and metrics are unchanged from sections 1–9.

### 13.2 Model inputs and their availability at the origin

One row per (origin, lead). Five features, in this order:

| Feature | Definition | Why it is available at origin *O* |
|---|---|---|
| `lag_24h_mw` | load(*t* − 24 h) | its interval starts 1–24 h before *O* |
| `lag_168h_mw` | load(*t* − 168 h) | its interval starts 145–168 h before *O* |
| `target_local_hour` | Europe/Berlin hour of *t* (0–23) | depends only on the timestamp |
| `target_local_weekday` | Europe/Berlin weekday of *t* (Monday = 0) | depends only on the timestamp |
| `target_local_month` | Europe/Berlin month of *t* (1–12) | depends only on the timestamp |

- The lag features are built by the same timestamp-label lookup as the naive baselines:
  `lag_24h_mw` is the daily naive prediction and `lag_168h_mw` the weekly one. Each row
  records the source timestamp of both lags, so the same function's guard ensures every
  source precedes the origin.
- `load(t − 1 h)` and other short lags are not used: for later leads they would come from
  inside the forecast horizon.
- The calendar features are plain integers; the tree model needs no encoding or scaling.
  The UTC targets are unchanged: on the autumn DST day local hour 2 occurs twice, and on
  the spring DST day it does not occur.
- Not used: holiday labels, weather, generation, prices, external load forecasts, rolling
  statistics. The forecast is a batch forecast: no prediction inside a horizon is updated
  with actual load from that horizon.

### 13.3 Training and validation protocol

- **Fit (gradients):** targets 2015-01-01 to 2017-12-31 UTC. Of 26,304 rows, 168 (the
  first week of 2015) lack the 168-hour lag (24 of them also the 24-hour lag) and are
  excluded, not filled: 26,136 rows are used.
- **Early stopping:** the 2018 rows (8,760), used only to choose the boosting iteration
  by validation L1 (MAE). They are never added to training. LightGBM builds feature bins
  from the training rows only.
- **Evaluation:** the frozen model predicts 2018 and 2019 in the same run. There is no
  retraining on 2018 and no change after seeing 2019. 2020 is dropped before anything
  else (section 6).
- 2018 is the selection period: its LightGBM MAE is the early-stopping objective itself.
  Only 2019 is held out from every model choice. Because the round cap bound
  (section 13.5), early stopping did not in fact change the model.
- One pooled model is used for all 24 leads; lead is not a feature.

### 13.4 Configuration (predefined, not tuned)

LightGBM 4.7.0 native API, `objective=regression_l1`, `metric=l1`, `learning_rate=0.05`,
`num_leaves=15`, `min_data_in_leaf=100`, `num_boost_round=500`, early stopping after 50
rounds without improvement, `seed=42`, `device_type=cpu`, `deterministic=true`,
`force_col_wise=true`, `num_threads=1`.

- The only addition is `verbosity=-1`, which affects logging only.
- No grid search, Bayesian optimisation or second configuration was run.

### 13.5 Early stopping did not stop training

The best iteration was **500 of 500**. Validation MAE was still decreasing when the
predefined round limit was reached:

| Trees | 50 | 100 | 200 | 300 | 400 | 450 | 500 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2018 MAE (MW) | 2,285.3 | 1,780.9 | 1,630.6 | 1,559.7 | 1,525.3 | 1,513.6 | 1,505.0 |

The improvement had flattened to about 9 MW over the last 50 trees. The model is
therefore limited by the predefined cap, not selected by early stopping. The cap was
deliberately not raised, because that would be tuning. Whether more rounds help is a
question for a separate, validation-only experiment.

### 13.6 Comparison procedure and common sample

- In each period the weekly naive, daily naive and LightGBM predictions are aligned target
  by target. Alignment is an error unless all three were made for identical
  (origin, target, lead) rows.
- The primary comparison uses only `common_valid` rows, where the target and all three
  predictions are available. Standalone metrics, each model on its own valid rows, are
  reported separately.
- **Improvement over a baseline** = MAE(baseline) − MAE(LightGBM). It is positive when
  LightGBM is better, and also reported relative to the baseline MAE (undefined, shown as
  null, if that MAE is 0). The RMSE difference and lower-absolute-error counts are
  reported too.
- For LightGBM, `lightgbm_reference_unavailable` means one of its lag inputs was
  unavailable. With these features that cannot happen without a baseline reference also
  being missing.
- In both periods all 8,760 pairs were common-valid; nothing was excluded.

### 13.7 Results (single run, OPSD 2020-10-06, 8,760 common pairs per period)

2018 is the early-stopping selection period; 2019 is the held-out period.

| Period | Weekly MAE | Daily MAE | LightGBM MAE | Weekly RMSE | Daily RMSE | LightGBM RMSE | Weekly WAPE | Daily WAPE | LightGBM WAPE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018 (validation) | 2,555.6 | 4,607.9 | 1,505.0 | 4,364.1 | 7,017.4 | 2,717.0 | 4.49 % | 8.09 % | 2.64 % |
| 2019 (test) | 2,558.1 | 4,557.7 | 1,452.4 | 4,465.0 | 6,944.0 | 2,588.9 | 4.57 % | 8.14 % | 2.59 % |

MAE and RMSE in MW.

| Period | Improvement over weekly MAE | Over daily MAE | RMSE improvement over weekly | LightGBM lower error than weekly |
|---|---:|---:|---:|---:|
| 2018 | 1,050.6 MW (41.1 %) | 3,102.8 MW (67.3 %) | 1,647.1 MW | 6,226 of 8,760 pairs (71.1 %) |
| 2019 | 1,105.7 MW (43.2 %) | 3,105.3 MW (68.1 %) | 1,876.0 MW | 6,075 of 8,760 pairs (69.3 %) |

The baseline values are identical to sections 9 and 10. As a check, the five features
were rebuilt independently from the raw CSV (positional shifts, Python `zoneinfo`) and
fed to the saved model. The predictions matched `predictions.csv` to 7 × 10⁻¹² MW.

### 13.8 Calendar and reliability diagnostics

The categories and holiday table are those of section 10. They are used only to group
errors and are not model inputs. In `calendar_analysis.csv`,
`lightgbm_minus_weekly_naive_mae_mw` is LightGBM MAE minus weekly MAE, so a negative value
means LightGBM is better. This is the opposite sign to the improvement figures in
`metrics.json`. "Days" below are UTC forecast days (one per origin).

MAE in MW (RMSE in `calendar_analysis.csv`):

| Category | Pairs | 2018 weekly / daily / LightGBM | 2019 weekly / daily / LightGBM |
|---|---:|---:|---:|
| `neither_holiday` | 8,352 | 2,042.6 / 4,522.8 / 1,240.7 | 2,009.0 / 4,481.2 / 1,204.6 |
| `target_holiday_only` | 192 | 14,646.1 / 5,995.9 / 10,436.0 | 14,581.4 / 6,935.0 / 10,646.0 |
| `weekly_reference_holiday_only` | 192 | 12,856.7 / 7,273.2 / 2,682.9 | 14,482.5 / 5,722.8 / 2,286.6 |
| `both_holidays` | 24 | 1,929.7 / 1,764.1 / 12,620.5 | 2,087.2 / 2,821.7 / 7,470.7 |

Descriptive observations, the same in both years unless noted:

- **Ordinary days:** LightGBM has the lowest MAE, about 40 % below the weekly naive.
- **Holiday targets** remain a large failure: about 10.4–10.6 GW MAE. This is better
  than the weekly naive (~14.6 GW) but worse than the daily naive (6.0–6.9 GW). The model
  has no holiday information. Of its 15 worst days, 9 (2018) and 8 (2019) mostly cover a
  nationwide holiday: Easter Monday, Good Friday, Whit Monday, 1 May, 3 October,
  Ascension, 1 January, 25–26 December. Most of the others are Christmas Eve, New Year's
  Eve, regional holidays (Corpus Christi, All Saints' Day), 2 January or Easter Sunday.
- **Weekly reference was a holiday:** LightGBM falls to 2.3–2.7 GW, far below both naive
  forecasts. The other features appear to compensate for an abnormal week-old value.
- **`both_holidays`** (24 pairs on 2 dates around 1 January): LightGBM is much worse than
  both naive forecasts. The group is too small to generalise from.
- **Weekdays:** LightGBM has a lower MAE than the weekly naive on every local weekday in
  both years. Against the daily naive it is lower on all weekdays except Wednesday 2019
  (1,481.5 vs 1,451.1 MW).
- **Lead hours:** LightGBM is better than the weekly naive at every lead. Errors are
  highest in daytime, roughly leads 6–17 (05:00–16:00 UTC), at about 1.55–1.8 GW. At
  night (leads 1–4 and 21–24) they are about 1.1–1.25 GW.
- **Bad days:** LightGBM's day-level MAE is worse than the weekly naive's on 81 (2018)
  and 82 (2019) of 365 days. It is worse by more than 1 GW on 6 and 5 days: mostly New
  Year's Day, days just after a holiday, and the days between Christmas and New Year.
- **Error concentration:** its errors are more concentrated than the weekly naive's: the
  15 worst days hold about 68 % of its squared error (about 55 % for the weekly naive).

### 13.9 Integrity of the test period

- The model, features, configuration and evaluation were fixed in code and tests before
  the first real-data run. That single run produced both the 2018 and 2019 results.
- Nothing that affects the model, its predictions or the metrics was changed afterwards.
  Later review fixes changed tests, the reload-check mechanics, metadata wording and
  documentation. Re-running then reproduced byte-identical `model.txt`, predictions and
  metrics.
- This LightGBM model had never been evaluated on 2019 before. However, 2019 was examined
  in Phases 1A and 1B (baseline errors, holiday analysis), so it is not an untouched
  period for the project's broader questions.
- 2018 was the only period used for early stopping and for exploring model behaviour,
  such as the boosting path in section 13.5.
- The 2019 diagnostics in section 13.8 are post-hoc and descriptive. They were produced
  after the model was frozen and did not feed back into it.

### 13.10 Reproducibility

- The environment is pinned by `uv.lock`: LightGBM 4.7.0, which requires SciPy and
  Narwhals.
- On macOS the LightGBM wheel needs the OpenMP runtime: `brew install libomp`.
- Training uses one CPU thread, a fixed seed and deterministic mode.
- A second training run on the same machine gave a byte-identical `model.txt` and
  identical predictions, metrics and calendar outputs.
- The saved model (`model.txt`, LightGBM text format, the 500 trees kept) reloads with
  predictions identical to the original on all 17,520 evaluation rows. The run checks
  this every time and fails if they differ by more than 10⁻⁶ MW.
- Bitwise identity across operating systems, compilers or LightGBM versions is not
  expected.

### 13.11 Interpretation limits

- These results support one claim: on this dataset, task and periods, this fixed
  LightGBM configuration had lower MAE, RMSE and WAPE than both naive baselines on
  identical pairs. This holds in the held-out 2019 period and in the 2018 selection
  period.
- They do not establish statistical significance, and they say nothing about uncertainty
  or calibration.
- A tree model is not "explainable" merely by being a tree. No explanation method has
  been applied, and no claim is made about why the model behaves as it does beyond the
  descriptive breakdowns above.
- The configuration is not shown to be optimal; early stopping did not trigger
  (section 13.5).

## 14. Limitations

**Scientific**

- One learned model, with one predefined configuration that is capped by the round limit,
  compared with two naive references. No other learned model has been evaluated.
- No uncertainty in the metrics is quantified: no confidence intervals, no significance
  tests. Hourly errors within a day are strongly dependent.
- Holidays are not modelled. They are only analysed retrospectively, and they remain the
  dominant failure of all three forecasts.
- The task assumes full information up to the origin. It ignores publication delays,
  data revisions and day-ahead gate-closure times, so it is not an operational
  day-ahead evaluation. This favours inputs close to the origin: the daily naive and
  LightGBM's 24-hour lag.
- 2019 is not an untouched confirmatory period for calendar questions (sections 11 and
  13.9).

**Dataset**

- Only one country and one data source (ENTSO-E via OPSD) are used, covering 2015 to
  September 2020.
- The values are a retrospective 2020 snapshot, not what was known in real time.
- Apparent level-shift artifacts in 2015 (train period) are documented, not corrected;
  they are in LightGBM's training data.
- The 60-minute aggregation method and the precise "total load" definition are taken from
  OPSD/ENTSO-E and not independently verified.
- The reuse terms for the underlying ENTSO-E data are unresolved (see README). Neither
  data nor the trained model, which is derived from the data, is redistributed.

**Implementation**

- The forecasting setup (daily 00:00 UTC origins, 24-hour horizon), the season lengths,
  the feature set and the LightGBM configuration are fixed constants, not configuration.
- The holiday table is explicit and covers only the dates needed (2017-12-25 to
  2020-01-01). Extending the evaluation requires extending and re-verifying it.
- Validation stops on structural time-index problems (non-UTC, duplicated, unordered or
  off-hour timestamps) instead of repairing them.
- Tests use synthetic fixtures. The real-data numbers were checked by independent
  re-computation, not by a unit test.
- On macOS, LightGBM depends on a system OpenMP runtime installed outside the project
  (`brew install libomp`).

## 15. Reproduction

```bash
uv sync
mkdir -p data/raw
curl --fail --retry 3 -o data/raw/time_series_60min_singleindex.csv https://data.open-power-system-data.org/time_series/2020-10-06/time_series_60min_singleindex.csv
uv run python -m gridpulse validate --input data/raw/time_series_60min_singleindex.csv
uv run python -m gridpulse baseline --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/baseline
uv run python -m gridpulse compare --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/comparison
uv run python -m gridpulse train-lightgbm --input data/raw/time_series_60min_singleindex.csv --output-dir outputs/lightgbm
uv run pytest
```

On macOS, run `brew install libomp` once before the LightGBM command and tests.

`run_metadata.json` records:

- the Python, NumPy and pandas versions;
- the dataset checksum and whether it matched the official one;
- the split boundaries and the task definition;
- the baseline definitions;
- for `compare` and `train-lightgbm`, the calendar time zone, holiday dates, source and
  classification rule;
- for `train-lightgbm`, the LightGBM version, feature definitions and order, availability
  assumptions, configuration, best iteration, row counts with exclusions, the
  model-reload check and the stated limitations;
- the number of valid (or common-valid) pairs per period.

The baselines are deterministic. LightGBM training is deterministic on the same platform
and library versions.
