# Utility application concept: offline measurement-sufficiency and decision-reliability analysis

**Status.**

- **What this is.** A research-positioning document. It describes how GridPulse's methods
  could eventually support engineering work on real distribution networks.
- **What this is not.**
  - GridPulse is an independent research project. It is not associated with any utility,
    country, government or commercial partner.
  - No utility data has been requested or used.
  - GridPulse is an offline research system. It is not operational software, not
    certified and not field-validated. It must not be used for real-time decisions.
- **Evidence.** Every result cited here comes from SimBench benchmark networks with
  synthetic 2016 profiles and simulated measurements:
  - `docs/phase5_results.md`, `docs/phase6_results.md` and `docs/phase7_results.md`;
  - Phase 8 has been evaluated (exploratory): `docs/phase8_results.md`.

## 1. The engineering problem

LV feeders with much distributed PV can exceed voltage or loading limits at midday.
Operators then limit export (curtailment), refuse connections, or invest. Whether a limit
is reached depends on three things that are known only imperfectly:

- the **network model**: cable data, transformer tap, MV voltage, inverter settings;
- the **measurements**: often only at the secondary substation, with finite accuracy;
- the **customer load and generation data**: metered with gaps, delays and errors.

**The research question behind every application:**

> Are the measurements and models available for a network sufficient to identify its
> important constraints (feeder-end voltage, cable loading, transformer loading) and to
> support reliable planning decisions, such as connection approvals or export limits?
> And which additional information would change those decisions?

This concerns *planning and assessment*, offline, from historical data. It does not
concern controlling equipment.

## 2. Who could use such analyses

- **Distribution system operators (DSOs):** LV and MV planning, hosting-capacity and
  export-limit assessments, and decisions on where to measure.
- **Transmission system operators (TSOs), where appropriate.** The methodology transfers
  in principle:
  - measurement sufficiency and observability;
  - model-consistency residuals;
  - decision reliability under model mismatch;
  - guarded, pre-registered evaluation.

  The implemented physics is LV-specific, so this is a FUTURE APPLICATION.
- **Energy systems researchers:** reproducible benchmark experiments on decision
  reliability under forecast, model and measurement uncertainty.
- **Electrical engineering teams, and grid planning and consulting organisations:**
  structured checks of what a measurement set can and cannot reveal before a decision
  is made.

## 3. Status of the capabilities

| Status | Meaning here |
|---|---|
| IMPLEMENTED AND TESTED | Code with tests, run on benchmark networks |
| RESEARCH PROTOTYPE | Implemented and studied, with known limits; not a dependable tool |
| EXPERIMENTALLY SUPPORTED | A benchmark finding from a guarded, pre-registered study (exploratory; not field evidence) |
| FUTURE APPLICATION | A plausible use that has not been implemented or studied |
| NOT VALIDATED | Untested against real networks, measurements or customer data |

Everything below is **NOT VALIDATED** on real networks.

| Capability | Status | Notes |
|---|---|---|
| Quarter-hourly AC power flow of an LV feeder and its MV/LV transformer over a year (pandapower) | IMPLEMENTED AND TESTED | Balanced single-phase-equivalent model |
| Signed constraint margins: voltage in p.u., loading in % of rating, never added | IMPLEMENTED AND TESTED | |
| Violation counting, severity and duration, and the curtailment needed to avoid them | IMPLEMENTED AND TESTED | |
| Simulating what a measurement set would report: noise, per-meter bias, missing data, delay; each reading's noise tied to its sensor | IMPLEMENTED AND TESTED | The averaging behaviour of real meters (often 15-min means) is not modelled |
| Which risks a measurement set can and cannot see (detection, false alarms, misses) | RESEARCH PROTOTYPE | Results depend strongly on the assumed meter error structure (random or bias) |
| Model-consistency check: substation voltage and reactive power against the model's prediction from metered consumption and generation | RESEARCH PROTOTYPE | Idealised tests only |
| Ranking a few candidate meter locations (feeder ends, largest PV, decision-aware) | RESEARCH PROTOTYPE | |
| WLS state estimation with pseudo-measurements and a chi-square consistency test | RESEARCH PROTOTYPE | It cannot certify an estimate. It is blind to voltage offsets, with 1.5–37 % false flags under a correct model |
| Model-residual correction from substation measurements: busbar-voltage offset and current ratios, against the model at metered injections | RESEARCH PROTOTYPE; EXPERIMENTALLY SUPPORTED on benchmarks | Removed almost all violations caused by three simulated common-mode or distributed model errors, without remote voltage meters. Its registered cost test failed: 27 % more curtailment than simpler feedback under a correct model. It depends on an unbiased busbar voltage. It met the registered robustness rule under the tested consistent customer-data errors; a two-day data delay cost about a third more curtailment (Phase 8) |
| Separate voltage and loading reserves (fixed or re-tuned daily); behaviour under customer-data and instrumentation errors | RESEARCH PROTOTYPE; evaluated (exploratory, Phase 8) | Separate reserves are established in the literature. On benchmarks, fixed separate reserves (with the registered tap-step voltage rule) saved no more than a finer shared margin. Daily re-tuned reserves curtailed less in one half-year at more violations, and cost more in the other. Both registered hypotheses failed |
| Operational evidence labels (model error, meter inconsistency, bias not identifiable) | RESEARCH PROTOTYPE | Operational definitions, not certificates |
| Offline static HTML demonstrator | IMPLEMENTED AND TESTED | Exploratory; synthetic data |
| Analysis of a real network's historical data | FUTURE APPLICATION | Needs the data and the safeguards in s. 5 and s. 7 |
| Any real-time or control use | NOT INTENDED | |

## 4. Benchmark findings that shape any application

These findings are EXPERIMENTALLY SUPPORTED on benchmarks only.

1. **The secondary-substation busbar voltage measurement is critical.**
   - A substation-residual correction moves one-for-one with any busbar bias.
   - The tolerated bias was about the planning safety margin (0.002–0.004 p.u.).
   - The accuracy of the whole measurement chain matters, not a nameplate class.
2. **Substation residuals see errors common to a feeder, such as a wrong tap or MV
   voltage.**
   - Time-varying common-mode errors were not covered: an MV voltage rising with PV
     defeated every attainable policy in the Phase 8 benchmark. The busbar sees the swing; a
     daily-average correction cannot follow it.
   - A stylised wrong cable record (lower rating than recorded) was tested. No attainable
     policy covered it: the flows match the model, and no tested measurement or policy
     revealed the overload.
   - Other local errors (one inverter, phase imbalance) are untested.
   - Whether a real feeder's model errors are mostly common-mode is unknown. It is the
     first question an application should answer.
3. **A correction against a model run at metered injections depends on those data.**
   - In Phase 8, random metering noise, an assumed load power factor, PV recorded 5 %
     high and 10 % missing data met the registered robustness rule. The systematic PV
     error was traded through re-tuned margins rather than absorbed.
   - A two-day data delay cost about a third more curtailment.
4. **Per-meter calibration bias does not average out.** Short overvoltages can hide in
   15-minute averages or behind persistence filters.
5. **A bad-data test that is passed is not evidence that the estimated state is
   correct.**

## 5. Data an offline analysis would need

This document requests no data.

**MINIMUM REQUIRED** (without these, no meaningful analysis is possible):

| Item | Why |
|---|---|
| Feeder single-line diagram: buses and cable sections; cable types and lengths (or R, X) and thermal ratings | The power-flow model; where violations can occur |
| MV/LV transformer: rating, impedance, tap range and **registered tap position** | Transformer loading and LV voltage level. A wrong tap is a key model error |
| PV connections: model bus and installed power | PV-driven overvoltage and reverse flow |
| Operational limits (voltage band, loading limits) | What counts as a violation |
| Historical secondary-substation measurements: busbar voltage, transformer current or P and Q, with interval, period, timestamp convention and the **measurement chain and its stated accuracy** | The residual signals. Voltage accuracy bounds what a correction can do |
| Metered consumption and PV generation for the same period, summed per model bus, with interval, completeness and delivery delay | The model run that residuals are computed against. Loads at the same bus add up in the power flow, so per-customer series are not needed |

**USEFUL** (would materially change what can be concluded):

| Item | What it would add |
|---|---|
| Calibration records of the busbar voltage measurement, or a comparison against a reference instrument | Bounds the busbar bias |
| MV voltage at the secondary substation, or its range, and the tap-change history | Separates MV-voltage from tap errors, and shows whether the offset varies within the day |
| Feeder-head currents | Loading ratios per feeder |
| Inverter settings (cos φ, Q(U)) | Checks the reactive-power model |
| Existing smart-meter or power-quality voltage readings, with accuracy class, averaging interval and delay | An independent feeder-end check |
| Known events: complaints, inverter trips, tap changes | Validation |

**OPTIONAL** (only if the first analysis shows a need):

| Item | What it would add | Caveat from the benchmark studies |
|---|---|---|
| A short independent measurement campaign at a feeder end | Tests whether model errors are common-mode | — |
| One or two additional voltage meters near feeder ends or the largest PV | Local errors the substation cannot see | Their value depends on meter accuracy and filtering |
| Current measurement on a mid-feeder cable section | The only direct view of cable currents away from the substation | In the benchmark no tested measurement revealed a wrongly recorded thermal rating; correct asset data or thermal monitoring is the hypothesised remedy |

## 6. How an offline analysis could support an engineering workflow

These are FUTURE APPLICATION steps, not an operational procedure.

1. **Authorisation first.** The data owner gives written authorisation and completes its
   own data-protection assessment (s. 7) before any data is exchanged.
2. **Model check.** Run the network model at the metered injections. Compare it with
   historical substation measurements: residual size, constancy, time-of-day pattern.
3. **Residual structure.** Are the residuals roughly constant (common-mode: tap, MV
   level), or do they vary with time of day, season or feeder (time-varying or local
   errors, which a substation cannot correct)?
4. **Observability.** Which constraint types can the existing measurements observe, and
   with what uncertainty?
5. **Sensitivity.** How much do conclusions depend on busbar accuracy, customer-data
   errors and the model errors that remain plausible?
6. **Measurement value.** Compare the existing measurements with "+1–2 voltage meters"
   and "+ cable current", simulated with realistic accuracy and reporting.
7. **Engineering review.** The owner's engineers review every finding. Recommendations
   are engineering inputs, not instructions. No result controls any equipment.
8. **Independent check, where possible.** Compare against known events or a short
   measurement campaign.

**What an engineering team could learn:**

- whether its model agrees with its substation measurements;
- whether its model errors are common-mode or local;
- which risks its measurements cannot see;
- how sensitive conclusions are to data errors;
- whether a specific additional measurement would change a planning decision.

## 7. Data protection and confidentiality

- Data would be used only under the owner's written authorisation, for the agreed offline
  analysis.
- **Legal basis.** Before any personal data is shared, the owner decides whether a legal
  basis exists under applicable data-protection law, as it determines that law. It also
  completes a data-protection impact assessment or its equivalent.
- **Where the data stay.** The data and anything derived from them stay **outside** the
  GridPulse repository and any public release.
  - They are processed only by named persons, on an encrypted, access-controlled
    computer.
  - They are never placed on cloud storage, shared drives or online services, including
    AI-assistant services, without explicit, lawful institutional authorisation.
  - There is no onward sharing and no attempt to re-identify anyone.
  - Results are reported at transformer or feeder level, with no per-customer series.
- **Customer series are personal data.** Consumption and generation series per connection
  point are personal data, also when pseudonymised. Pseudonymisation is not
  anonymisation: 15-minute profiles can reveal occupancy and daily routines, and on a
  small feeder a bus position or PV size can identify a household.
- **Minimisation.**
  - Series are summed per model bus.
  - No names, addresses, account or meter numbers.
  - Random bus labels, with any mapping kept only by the owner.
  - A period fixed in advance.
- **Retention.** Data and derived series are deleted or returned at the end of the
  analysis, with written confirmation. There is no connection to operational systems,
  and no data is accepted through informal channels.

## 8. How success or failure would be judged

| Criterion | Measure |
|---|---|
| Technical feasibility | Transformer-level predictions match historical measurements within an agreed tolerance |
| Feeder-end check | An independent feeder-end voltage check. A transformer-level match cannot validate feeder-end voltages, because tap and MV-voltage offsets are absorbed |
| Measurement error bounded | Accuracy and bias bounded from specifications or a reference comparison, the busbar voltage first; results reported across plausible bias values |
| Residual structure reported | Whether model errors are mostly common-mode or local, with the evidence |
| Not a criterion | Passing a state-estimation chi-square test |
| Usefulness | Engineers judge the observability and sensitivity findings correct and relevant |
| Recommendation | A reasoned recommendation for 0–2 additional measurements, or a reasoned "none needed" |
| Failure is a valid outcome | For example, the model cannot be reconciled with the measurements, or the data are insufficient |

No savings or monetary figures are estimated.

## 9. Questions any network owner would need to answer first

1. **Busbar voltage.** Is busbar voltage measured at secondary substations? How is it
   measured, and how is its accuracy verified?
2. **Historical data.** What historical load and generation measurements exist at
   feeder, transformer and connection-point level, with what interval, completeness and
   delay?
3. **Asset records.** How complete and reliable are the records for transformers
   (including tap positions), feeders and line parameters?
4. **Workload.** Which planning or operating decisions currently need time-consuming
   manual analysis?
5. **Value.** What measurable outcome would make an offline analysis valuable?

## 10. What would be required before any operational use

**What remains unsuitable now:**

- **No real data yet.** Nothing is validated against field measurements.
- **Simplified model.** Balanced single-phase-equivalent model; uniform PV caps;
  constant-power loads; no inverter protection or dynamics.
- **Simplified measurements.** Noise and bias are statistical assumptions, not specific
  meter types.
- **No guarantees.** Online calibration gives long-run averages, not per-day
  guarantees. Evidence labels and the chi-square test are research outputs, not
  certifications.
- **Correction methods tested only on stylised model errors and data conditions**
  (Phases 7 and 8). Time-varying and asset-record errors defeated them on benchmarks.

**What would be required:**

- field validation on real networks, with an independent feeder-end reference;
- a pre-registered, out-of-sample evaluation on real historical data, with failures
  reported;
- an offline shadow comparison against actual planning decisions;
- measurement-chain verification and documented failure modes;
- software assurance, and the network owner's own engineering review and approval under
  its procedures and regulation.
