# GridPulse: limited-measurement distribution grid risk assessment pilot (concept)

**Status:** a concept for a future technical discussion. No contact has been made, no
utility data has been requested or used, and nothing here describes KIB-TEK's actual
measurements, systems or practices.

GridPulse is an offline research system. It is not operational software and must not be
used for real-time decisions.

## 1. Pilot question

> Using the measurements the utility already has, can we identify important voltage and
> loading risks on one LV feeder? And can we determine whether a few targeted additional
> measurements would improve decisions?

## 2. What GridPulse can currently do (on synthetic benchmark networks)

**Simulation and comparison.**

- AC power flow (pandapower) of an LV feeder with its MV/LV transformer over a year of
  quarter-hours.
- Simulated PV curtailment decisions, with violations and curtailed energy counted on the
  simulated "true" grid.
- Comparison of what different measurement sets would detect:
  - substation only;
  - substation plus a few smart-meter voltages;
  - state estimation with pseudo-measurements.
- Rules for where a few extra sensors would help, designed only on historical data.

**Checking assumptions.**

- A model-consistency check: measured substation voltage and reactive power against the
  network model's prediction from metered consumption and generation.
- Explicit labels for when the evidence is insufficient or inconsistent.

The quantitative findings (`docs/phase5_results.md`) come from SimBench benchmark networks
with synthetic 2016 profiles. They are **not** evidence about any real utility's network.

### What the benchmark study suggests a pilot could test

These are hypotheses for a real feeder, not results about one.

1. **Is the network model consistent with what is measured?**
   - Comparing the measured substation voltage and reactive power with the model's
     prediction from metered consumption and generation flagged every day with a wrong
     tap or MV voltage.
   - It raised no false flag under the correct model.
   - This was idealised: exact metering and a constant MV voltage. It also cannot say
     which parameter is wrong.
   - It is the cheapest and clearest first step, and it needs no new sensors.
2. **What do the existing measurements miss?**
   - Substation telemetry saw transformer and feeder-head overloads.
   - It detected no remote overvoltage as such, and missed most of them when the model
     had a voltage offset (recall 0.14–0.45).
   - It missed overloads of mid-feeder cable segments.
3. **Would one or two extra voltage readings change decisions?**
   - In the benchmarks with realistic meter noise, one or two smart-meter voltages near
     the feeder end or the largest PV raised the cases meeting the violation target from
     4 to 12–14 of 15. The fourth added nothing.
   - About half of that gain came from noise-driven conservatism. With exact readings,
     two sensors reached 9 of 15, and placement chosen for the decision did better
     (13 of 15).
   - The answer for a real feeder therefore depends on the meters' actual accuracy.
4. **How noisy are the readings?**
   - Meter noise near the voltage limit created false alarms. A feedback rule then turned
     them into extra curtailment, under the correct model: about 3× with two sensors and
     6× with every bus metered.
   - With exact readings, extra sensors cost no extra curtailment.
   - A pilot should establish meter accuracy and averaging before any feedback use is
     considered.

## 3. Proposed pilot scope

- **One** small LV feeder, chosen with the utility's engineer.
- **Offline**, historical analysis only. No connection to SCADA, no automated control, no
  operational integration, no production deployment.
- **Deliverable:** a short technical report covering:
  - which risks the existing measurements can and cannot observe;
  - how sensitive the conclusions are to uncertain network parameters (transformer tap,
    MV voltage, inverter reactive-power settings);
  - whether the measured substation quantities are consistent with the model (a
    model-consistency check);
  - whether the binding limit is a voltage at a feeder end or the loading of a cable
    section. Only the latter needs current sensing;
  - whether and where 1–4 additional voltage measurements would change the conclusions.
- **Confidentiality:**
  - Utility data would stay outside the public repository.
  - It would be used only under written authorisation.
  - It would be deleted or returned on request.

## 4. Data requirements

| Item | Priority | Why it is needed |
|---|---|---|
| Single-line diagram of the feeder (buses, cable sections, connection points) | REQUIRED | The power-flow model; where violations can occur |
| Cable types and lengths (or R, X per section) and thermal ratings | REQUIRED | Voltage rise and line loading |
| MV/LV transformer: rating, impedance, tap range and **registered tap position** | REQUIRED | Transformer loading and LV voltage level. A wrong tap is a key model uncertainty |
| Historical transformer loading (current or P/Q), with interval and period | REQUIRED | Validates the model; the main measured signal |
| PV connections: location, installed power, inverter settings if known (cos φ / Q(U)) | REQUIRED | PV-driven overvoltage and reverse flow |
| Customer connection points and annual energy or load profiles | REQUIRED | Load model; pseudo-measurements |
| Any existing voltage measurements (substation LV busbar, smart meters, PQ recorders) with accuracy class, averaging interval and reporting delay | USEFUL | Detection of remote violations; model-consistency checks. In the benchmarks, meter noise near the limit decided how much a feedback rule curtailed |
| Any current or loading measurements on feeder cable sections | USEFUL | Voltage readings cannot reveal mid-feeder cable overloads |
| Operational limits used by the utility (voltage band, loading limits) | USEFUL | Defines what counts as a violation |
| MV voltage at the secondary substation, or its typical range | USEFUL | Second main model uncertainty |
| Known operating events (complaints, inverter trips, tap changes) | OPTIONAL | Validation of detected risks |
| Communication and data-availability characteristics (latency, missing data) | OPTIONAL | Realistic measurement model |
| Historical curtailment or PV control actions | OPTIONAL | Comparison with simulated decisions |

## 5. What can be concluded at different data levels

| Data available | Can be concluded | Cannot be concluded |
|---|---|---|
| Diagram + parameters + transformer loading only | Whether transformer overload or reverse flow occurs, and how often. Model-based estimates of remote voltage risk, labelled as model-based | Whether remote voltage violations actually occur. Errors in tap or MV voltage stay undetected |
| … + substation LV busbar voltage and metered consumption and generation | The above, plus detection of a voltage offset between model and reality (wrong tap, high MV voltage) | Feeder-end voltages and mid-feeder cable loading, except by model-based inference (state estimation, whose false-alarm rate in the benchmarks exceeded the registered limit) |
| … + a few smart-meter voltages (with timestamps) | Direct evidence of feeder-end voltages at those points, and an estimate of the value of further sensors | Loading of unmeasured cable sections. Behaviour of unmeasured inverters |
| … + inverter settings | Assessment of reactive-power effects on transformer loading and voltage | Real-time state, unless real-time telemetry exists |

In every case the result is an engineering assessment that supports a decision. It is not
a certified safety conclusion.

## 6. Five questions for a technical conversation

1. Which measurements exist today at the secondary substations and on LV feeders? For each:
   quantities, accuracy, interval, and how quickly the data become available.
2. Which operational decisions on LV feeders are hardest today? For example PV connection
   approvals, curtailment, voltage complaints, transformer upgrades.
3. Which risks are hardest to observe with current measurements? For example voltage at
   feeder ends, cable loading, reverse power flow, unknown tap positions.
4. Which of the data above could be shared for an offline study, under what authorisation
   and confidentiality terms?
5. What result from a pilot would be useful enough to justify the engineer's time? For
   example a risk map, a sensor-placement recommendation, or a model-consistency check.

## 7. What remains unsuitable for operational use

- **Benchmarks only.** All results so far come from benchmark networks with synthetic
  profiles.
- **Simplified model.** The network model is balanced (single-phase equivalent), and
  curtailment is modelled as a uniform cap.
- **No field validation.** No result has been validated against field measurements.
- **No guarantees.** The online calibration provides long-run averages, not per-day
  guarantees. Labels such as "insufficient evidence" are research outputs, not
  certifications.
