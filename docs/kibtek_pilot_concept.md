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
profiles (`docs/phase5_results.md`, `docs/phase6_results.md`). None of it has been
validated on a real feeder.

| Capability | Status |
|---|---|
| Quarter-hourly AC power flow of an LV feeder and its MV/LV transformer over a year (pandapower) | Implemented and tested on benchmarks; not field-validated |
| Counting voltage and loading violations, and the PV curtailment needed to avoid them | Implemented and tested on benchmarks; not field-validated |
| Simulating what a given measurement set would report: noise, per-meter bias, missing data, reporting delay; each reading's noise tied to its sensor | Implemented and tested on benchmarks. The averaging behaviour of real meters (often 15-min means) is not modelled |
| Which risks a given measurement set can and cannot see (detection, false alarms, misses) | Implemented on benchmarks. The results depend strongly on the assumed meter error structure (random vs bias) |
| Model-consistency check: measured substation voltage and reactive power against the model's prediction from metered consumption and generation | Research prototype; idealised test only |
| Ranking a few candidate meter locations (feeder ends, largest PV, decision-aware) | Research prototype |
| Online margin calibration from measured violations, with a noise-aware alarm rule | Research prototype; **not part of this pilot**, which involves no control |
| WLS state estimation with forecast pseudo-measurements and a chi-square consistency test | Research prototype. It can flag a wrong reactive-power model only when there is enough PV (78 % of estimates flagged in December in the benchmark). It gives 1.5–37 % false flags under a correct model and cannot see voltage offsets. It cannot certify an estimate |

## 3. Required network data (minimum)

| Item | Why |
|---|---|
| Single-line diagram of the feeder: buses, cable sections, connection points | Where violations can occur; the power-flow model |
| Cable types and lengths (or R, X per section) and thermal ratings | Voltage rise and cable loading |
| MV/LV transformer: rating, impedance, tap range and **registered tap position** | Transformer loading and LV voltage level. A wrong tap is a key model error |
| PV connections: location, installed power, inverter settings if known (cos φ, Q(U)) | PV-driven overvoltage and reverse flow. A wrong reactive-power setting is the other key model error |
| Customer connection points with annual energy or load profiles. Customer-level series are personal data: aggregated or pseudonymised, for the minimum period needed, and without identifiers | Load model; pseudo-measurements |
| The utility's operational limits (voltage band, loading limits) | What counts as a violation |

## 4. Minimum measurement requirements

| Item | Why |
|---|---|
| Historical transformer measurements (current or P and Q; LV busbar voltage if available), with interval, period and accuracy | The main measured signal. With metered consumption and generation it also allows the model-consistency check |
| Metered customer consumption and PV generation for the same period, with interval | Model consistency; pseudo-measurements |

## 5. Optional measurement improvements, and what they would add

| Item | What it would add | Caveat from the benchmark studies |
|---|---|---|
| Existing smart-meter or power-quality voltage readings (with accuracy class, averaging interval, reporting delay) | Direct evidence of feeder-end voltages | Violations are often smaller than single-reading meter noise. Averaging or persistence helps against random noise, but per-meter bias does not average out. Real overvoltages are often short (minutes; Kreuwel et al. 2021), so 15-min averages or persistence filters can hide them |
| One or two additional voltage measurements near feeder ends or the largest PV | The main candidates for "worth adding" | Their value depends on meter accuracy and on how alarms are filtered |
| Current measurements on mid-feeder cable sections | The only direct way to see cable overloads away from the substation | Voltage readings cannot reveal them |
| MV voltage at the secondary substation, or its range | Separates MV-voltage from tap-position errors | — |
| Known events: complaints, inverter trips, tap changes | Validation | — |

## 6. Expected validation procedure (for a pilot)

1. **Model check.** Run the feeder model against historical transformer measurements.
   Report the residuals, and whether tap or MV-voltage assumptions need correcting.
2. **Detection capability.** From the existing measurements, report which constraint
   types can be observed, and with which uncertainty.
3. **Sensor value.** Compare the existing measurements with "+1–2 voltage meters" and
   "+ cable current" alternatives. Simulate on the calibrated model, with the actual
   meter accuracy and reporting.
4. **Review.** The utility's engineers review every finding. Any recommendation is an
   engineering input, not an instruction.
5. **Independent check, where possible.** Compare against known events or a short
   independent measurement campaign.

## 7. Confidentiality and data handling

- Utility data would be used only under written authorisation and for the agreed offline
  analysis.
- Utility data and anything derived from it stay **outside** the GridPulse repository and
  any public release. Whether and how GridPulse is published is still undecided.
- Customer-level data are personal data. Only the minimum needed, aggregated or
  pseudonymised, would be requested.
- Data are deleted or returned on request. No connection to operational systems.
- A technical needs discussion can precede any formal data-sharing agreement. No data
  should be shared through informal channels.

## 8. Pilot success criteria (proposed, to be agreed)

| Criterion | Measure |
|---|---|
| Technical feasibility | A feeder model whose transformer-level predictions match historical measurements within a tolerance agreed with the engineer |
| Feeder-end check | An independent feeder-end voltage check, from an existing power-quality recorder or a short measurement campaign. A transformer-level match cannot validate feeder-end voltages, because tap and MV-voltage offsets are absorbed |
| Meter error bounded | Meter accuracy and bias bounded from specifications or a reference comparison, with results reported across plausible bias values |
| Not a criterion | Acceptance by a state-estimation chi-square test is not evidence of a correct state, and is not a success criterion |
| Usefulness of the finding | The engineer judges the observability findings ("which risks the current measurements can and cannot see") correct and relevant |
| Usefulness of the recommendation | Either a reasoned recommendation for 0–2 additional measurements, or a reasoned statement that none would change the planning decision |
| Data handling | All agreed confidentiality conditions met; nothing published |

No savings or monetary figures are estimated in advance.

## 9. Five questions for the engineering contact

1. **Measurement infrastructure** (ask first).
   - Which voltage measurements exist today on LV feeders: substation busbar, smart
     meters, power-quality recorders?
   - For each: are the values instantaneous or averaged, and over what interval?
   - What accuracy is specified? Has any meter been compared against a reference
     instrument?
   - How soon are the data available?
   - The benchmark studies show that meter accuracy, bias and averaging decide whether
     added sensing has any value. The question asks for no data.
2. **Network model.** Is there a technical model or single-line diagram of LV feeders
   with cable data and registered transformer tap positions? How reliable is it
   considered to be?
3. **Current problems.** Which voltage, transformer-loading or solar-connection
   assessment problems occur today? For example complaints, approvals, curtailment or
   reverse flow.
4. **Methods and their limits.** How are these assessed today, and where do the current
   methods fall short? For example missing measurements, uncertain models, effort.
5. **Value of a pilot.** Would an authorised, offline analysis of one feeder with
   appropriately protected historical data give useful planning insight? What result
   would justify the engineer's time?

## 10. What remains unsuitable for operational use

- **No real data yet.** All results so far come from benchmark networks with synthetic
  profiles. Nothing is validated against field measurements.
- **Simplified model.** Balanced single-phase-equivalent model; uniform PV caps; no
  inverter protection or dynamic effects.
- **Simplified measurement model.** Noise and bias are modelled as statistical
  assumptions, not as specific meter types.
- **No guarantees.** The online calibration gives long-run averages, not per-day
  guarantees. The evidence labels and the chi-square test are research outputs, not
  certifications.
