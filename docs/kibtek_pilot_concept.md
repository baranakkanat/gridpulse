# GridPulse: offline measurement-sufficiency pilot for one LV feeder (concept)

**Status.**

- This is a concept for a future technical discussion.
- No contact has been made. No utility data has been requested or used.
- Nothing here describes KIB-TEK's actual network, measurements, systems or practices.
- GridPulse is an offline research system. It is not operational software, it is not
  certified, and it must not be used for real-time decisions.

## 1. Problem definition

> Can we determine whether the measurements that already exist on one distribution
> feeder are sufficient to identify its important constraints (feeder-end voltage,
> cable loading, transformer loading) and to support reliable planning decisions, such
> as PV connection approvals or curtailment limits? And would a few targeted additional
> measurements change those decisions?

The question is about *planning and assessment*, offline, from historical data. It is not
about controlling equipment.

## 2. What GridPulse can do today, and what is still a prototype

All of this has been shown only on SimBench benchmark networks with synthetic 2016
profiles (`docs/phase5_results.md`, `docs/phase6_results.md`, `docs/phase7_results.md`).
None of it has been validated on a real feeder.

| Capability | Status |
|---|---|
| Quarter-hourly AC power flow of an LV feeder and its MV/LV transformer over a year (pandapower) | Implemented and tested on benchmarks; not field-validated |
| Counting voltage and loading violations, and the PV curtailment needed to avoid them | Implemented and tested on benchmarks; not field-validated |
| Simulating what a given measurement set would report: noise, per-meter bias, missing data, reporting delay; each reading's noise tied to its sensor | Implemented and tested on benchmarks. The averaging behaviour of real meters (often 15-min means) is not modelled |
| Which risks a given measurement set can and cannot see (detection, false alarms, misses) | Implemented on benchmarks. The results depend strongly on the assumed meter error structure (random vs bias) |
| Model-consistency check: measured substation voltage and reactive power against the model's prediction from metered consumption and generation | Research prototype; idealised test only |
| Ranking a few candidate meter locations (feeder ends, largest PV, decision-aware) | Research prototype |
| Online margin calibration from measured violations, with a noise-aware alarm rule | Research prototype; **not part of this pilot**, which involves no control |
| Signed constraint margins: voltage in p.u., loading in % of rating, reported separately and never added | Implemented and tested on benchmarks |
| Model-residual correction from substation measurements: the busbar-voltage offset and the transformer and feeder-head current ratios, each against the model run at the metered injections | Research prototype. On benchmarks it removed almost all violations caused by the three simulated model errors (tap, MV voltage, PV reactive power), including at unmetered buses, without remote voltage meters, at more curtailment than binary feedback with two exact meters. Its registered cost test failed: under a correct model it curtailed 27 % more than simpler alarm feedback. It assumes exact customer injection data and an accurate busbar voltage. It was not tested on local or time-varying model errors |
| Operational evidence labels (model error, meter inconsistency, cannot tell bias from model error) | Research prototype. Operational definitions, not certificates; they trust the busbar measurement |
| WLS state estimation with forecast pseudo-measurements and a chi-square consistency test | Research prototype. It can flag a wrong reactive-power model only when there is enough PV (78 % of estimates flagged in December in the benchmark). It gives 1.5–37 % false flags under a correct model and cannot see voltage offsets. It cannot certify an estimate |

## 3. What Phase 7 changes for a pilot

Three benchmark findings decide what a pilot must ask about first:

1. **The LV busbar voltage measurement is the critical measurement.**
   - The residual correction moves one-for-one with any busbar bias.
   - On the benchmarks, the tolerated bias was about the planning safety margin, roughly
     0.002–0.004 p.u.
   - A −0.005 p.u. bias cost reliability in some networks.
   - The accuracy of the whole measurement chain matters, not a nameplate class. Class
     limits are maximum permissible errors, not typical errors.
2. **Substation residuals see common-mode errors; local ones are argued, not tested, to be
   beyond them.**
   - A wrong tap position or MV voltage shifts every LV voltage almost alike. The busbar
     residual measures that shift, and the correction then protects unmetered buses too.
   - A local error is not expected to be seen (no local error was simulated): one
     inverter's setting, one poor cable, phase imbalance.
   - Whether a real feeder's model errors are mostly common-mode is the first thing a
     pilot should establish. It is unknown.
3. **The correction needs customer injection data.**
   - The residual compares the measurement with the model run at the metered customer
     consumption and generation.
   - Any systematic error or gap in those data passes into the correction. This was not
     tested.

## 4. Data an analysis would need, in three tiers

This document requests no data. The tiers describe what an analysis would need, for a
later discussion only if the utility chooses one.

**MINIMUM REQUIRED** (without these, no meaningful offline analysis is possible):

| Item | Why |
|---|---|
| Feeder single-line diagram: buses and cable sections; cable types and lengths (or R, X) and thermal ratings | The power-flow model; where violations can occur |
| MV/LV transformer: rating, impedance, tap range and **registered tap position** | Transformer loading and LV voltage level. A wrong tap is a key model error |
| PV connections: model bus and installed power | PV-driven overvoltage and reverse flow |
| The utility's operational limits (voltage band, loading limits) | What counts as a violation |
| Historical secondary-substation measurements: LV busbar voltage, transformer current or P and Q, with interval, period, timestamp convention and the **measurement chain and its stated accuracy** | The residual signals. Busbar voltage accuracy bounds what the correction can do |
| Metered consumption and PV generation for the same period, summed per model bus, with interval, completeness and delivery delay | The model run that the residuals are computed against. Loads at the same bus add up in the power flow, so per-customer series are not needed. Personal data even when pseudonymised (s. 6) |

**USEFUL** (would materially change what can be concluded):

| Item | What it would add |
|---|---|
| Calibration records of the busbar voltage measurement, or a comparison against a reference instrument | Bounds the busbar bias, the method's largest tested measurement dependency |
| MV voltage at the secondary substation, or its range, and the tap-change history | Separates MV-voltage from tap-position errors, and shows whether the offset varies within the day |
| Feeder-head currents | Loading ratios per feeder, not only for the transformer |
| Inverter settings if known (cos φ, Q(U)) | Checks the other key model error, reactive power |
| Existing smart-meter or power-quality voltage readings, with accuracy class, averaging interval and reporting delay | An independent feeder-end check. Benchmark caveat: per-meter bias does not average out; short overvoltages can hide in 15-min averages |
| Known events: complaints, inverter trips, tap changes | Validation |

**OPTIONAL** (only if the first analysis shows a need):

| Item | What it would add | Caveat from the benchmark studies |
|---|---|---|
| A short independent measurement campaign at a feeder end | Tests whether the model errors are common-mode, which decides whether the substation suffices | — |
| One or two additional voltage meters near feeder ends or the largest PV | Local errors the substation cannot see | With the residual correction, added meters changed little for common-mode errors. Their value depends on meter accuracy and filtering |
| Current measurement on a mid-feeder cable section | The only direct view of cable overloads away from the substation | Voltage readings cannot reveal them |

## 5. Expected validation procedure (for a pilot)

1. **Model check.** Run the feeder model at the metered injections and compare it with
   the historical substation measurements. Report the busbar-voltage residual and the
   current ratios over time.
2. **Residual structure.** Check whether the residuals are roughly constant (common-mode:
   a tap or MV-voltage error) or vary with time of day, season or feeder (time-varying
   or local errors, which the substation cannot correct).
3. **Detection capability.** From the existing measurements, report which constraint
   types can be observed, and with which uncertainty.
4. **Sensor value.** Compare the existing measurements with "+1–2 voltage meters" and
   "+ cable current" alternatives. Simulate on the calibrated model, with the actual
   meter accuracy and reporting.
5. **Review.** The utility's engineers review every finding. Any recommendation is an
   engineering input, not an instruction.
6. **Independent check, where possible.** Compare against known events or a short
   independent measurement campaign.

## 6. Confidentiality and data handling

- Utility data would be used only under written authorisation and for the agreed offline
  analysis.
- Before any personal data is shared, the utility decides whether a legal basis exists
  under applicable data-protection law, as it determines that law, and completes a
  data-protection impact assessment or its equivalent. The utility sets the purpose and
  conditions in the written agreement.
- Utility data and anything derived from it stay **outside** the GridPulse repository and
  any public release. They are processed only by named persons on one encrypted,
  access-controlled computer, never on cloud storage, shared drives or online services,
  including AI assistants. No onward sharing and no attempt to re-identify anyone.
  Reported results are at transformer or feeder level, with no per-customer series.
  Whether and how GridPulse is published is still undecided.
- Consumption and generation series per connection point are personal data, also when
  pseudonymised. Pseudonymisation is not anonymisation: 15-minute profiles can reveal
  occupancy and daily routines, and on a small feeder a bus position or PV size can
  identify a household. Only the minimum would be considered:
  - series summed per model bus, with consumption and generation separate only where the
    model needs it;
  - no names, addresses, account or meter numbers;
  - random bus labels not derived from any identifier, with any mapping kept only by the
    utility;
  - a period fixed in advance (a full year only if seasonal residuals must be checked).
- The residual correction needs injections per model bus, so aggregation to the feeder
  alone is not enough for that analysis. This is why the data tier and the protection
  measures must be agreed together.
- Data, and any series derived from them, are deleted or returned at the end of the
  agreed analysis, or earlier on request, with written confirmation. No connection to
  operational systems.
- A technical discussion with no data exchanged can come first. No data would be
  accepted before the written agreement and the impact assessment, or through informal
  channels such as e-mail, messaging or personal storage.

## 7. Pilot success criteria (proposed, to be agreed)

| Criterion | Measure |
|---|---|
| Technical feasibility | A feeder model whose transformer-level predictions match historical measurements within a tolerance agreed with the engineer |
| Feeder-end check | An independent feeder-end voltage check, from an existing power-quality recorder or a short measurement campaign. A transformer-level match cannot validate feeder-end voltages, because tap and MV-voltage offsets are absorbed |
| Meter error bounded | Meter accuracy and bias bounded from specifications or a reference comparison, with results reported across plausible bias values. The busbar voltage measurement first |
| Residual structure reported | Whether the feeder's model errors are mostly common-mode (correctable from the substation) or local, with the evidence |
| Not a criterion | Acceptance by a state-estimation chi-square test is not evidence of a correct state, and is not a success criterion |
| Usefulness of the finding | The engineer judges the observability findings ("which risks the current measurements can and cannot see") correct and relevant |
| Usefulness of the recommendation | Either a reasoned recommendation for 0–2 additional measurements, or a reasoned statement that none would change the planning decision |
| Data handling | All agreed conditions met; data deleted or returned with confirmation; no utility data or per-customer results published |

No savings or monetary figures are estimated in advance.

## 8. Five questions for the engineering contact

1. **Substation measurements** (ask first).
   - Which measurements exist at secondary substations today: LV busbar voltage,
     transformer current or P and Q, feeder-head currents?
   - How is the busbar voltage measured (directly or through a transformer), with what
     stated accuracy, and has it ever been checked against a reference instrument?
   - Are the values instantaneous or averaged, over what interval, and how soon are they
     available?
   - The benchmark studies show that busbar voltage accuracy bounds what a model
     correction can do. The question asks for no data.
2. **Customer metering.** For consumption and PV generation: what interval, how complete,
   how time-aligned with the substation data, and how soon available? Are smart-meter or
   power-quality voltage readings also available, with which accuracy and averaging?
   Could such series, if ever needed, be provided summed per bus? The question asks for
   no data.
3. **Network model.** Is there a technical model or single-line diagram of LV feeders
   with cable data and registered transformer tap positions? How reliable is it
   considered to be, and is the MV voltage at the substation known?
4. **Current problems and methods.** Which voltage, transformer-loading or
   solar-connection problems occur today (complaints, approvals, curtailment, reverse
   flow)? How are they assessed, and where do the current methods fall short?
5. **Value of a pilot.** Would an authorised, offline analysis of one feeder with
   appropriately protected historical data give useful planning insight? What result
   would justify the engineer's time?

## 9. What remains unsuitable for operational use

- **No real data yet.** All results so far come from benchmark networks with synthetic
  profiles. Nothing is validated against field measurements.
- **Simplified model.** Balanced single-phase-equivalent model; uniform PV caps; no
  inverter protection or dynamic effects.
- **Simplified measurement model.** Noise and bias are modelled as statistical
  assumptions, not as specific meter types.
- **No guarantees.** The online calibration gives long-run averages, not per-day
  guarantees. The evidence labels and the chi-square test are research outputs, not
  certifications.
- **Residual correction untested where it matters most.** It was tested only on constant
  model errors that raise voltage or loading, with exact customer data and a busbar bias
  tested only as a constant offset up to ±0.005 p.u. It was not tested on local, time-varying or opposite-direction
  errors, or with imperfect metering. Under a correct model it curtailed more than
  simpler feedback on the benchmarks.
