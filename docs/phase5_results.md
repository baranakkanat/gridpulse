# Phase 5 results: decisions under limited measurement availability

**Protocol and status.**

- Protocol: `docs/phase5_protocol.md`, with amendments 5A–5C.
- Run: one evaluation run on 2026-10-18 (2016-07-01 – 12-30, 183 days).
- Code: frozen; hashes are in `docs/provenance/phase5/registration_log.txt`.
- Full tables: `outputs/sense_study/logs/evaluation_report.md` (git-ignored), regenerated
  by `docs/provenance/phase5/scripts/report.py`.
- Four independent post-evaluation reviews (power systems with state estimation, leakage
  with reproducibility, statistics, novelty) and a final readiness check went over this
  document. Their corrections are included, and s. 11 lists what they found.

**How to read these results.**

- **Exploratory replication.** The networks and the 2016 profiles are those of Phase 4,
  so the evaluation half-year is not an unseen holdout. The registered criteria protect
  against tuning; they do not make the data new.
- **Counts.** Counts are over the five new networks. rural1 is the development network.
- **Cells.** A *cell* is (network, true model). The *mismatch cells* are the 15 (network ×
  {`tap_raise_lv`, `mv_high`, `pv_fixed_095`}).
- **The requirement.** At most 0.1 avoidable daylight violation quarter-hours per day.
- **Three facts decide how far the headline results reach.**
  1. **The primary result P holds in the evaluation half only.**
     - In the development half the same networks gave substation 0, two sensors 4 and
       full metering 6 of 15 cells, so P(b) fails there.
     - The online margin starts at zero on the first decision day and is learned during
       the development half. The evaluation half inherits a margin that has already
       adapted.
  2. **Much of the apparent value of remote sensors comes from measurement noise.**
     - With exact readings, two sensors meet the requirement in 9 cells, not 14.
     - Under the correct model, all the extra curtailment of noisy metering is
       noise-driven.
  3. **In rural3, two of the 14 supporting cells are met through the NO_FEASIBLE_ACTION
     fallback,** which curtails all PV on the affected quarter-hours (s. 6).

## Networks and placements (development data only)

| Network | LV buses | Feeders | Export threshold p\* (MW) | Topology k=1, 2 | Mandatory-like k=1, 2 | Decision-aware k=1, 2 |
|---|---|---|---|---|---|---|
| rural2 | 96 | 4 | 0.259 | 66, 59 | 62, 38 | 66, 59 |
| rural3 | 128 | 9 | 0.413 | 83, 14 | 52, 1 | 121, 83 |
| semiurb4 | 43 | 3 | 0.179 | 26, 43 | 40, 5 | 40, 26 |
| semiurb5 | 110 | 6 | 0.395 | 52, 35 | 16, 69 | 22, 52 |
| urban6 | 58 | 7 | 0.263 | 18, 19 | 40, 13 | 40, 18 |

- **Greedy and decision-aware rules often fall back to topology order.** Their development
  objectives were flat beyond the first pick, so amendment 5B's tie rule applied.
- **Rerunning the design gives identical results.** The evaluation stage recomputed the
  placements, p\*, coverage and labels from development days, and all of them matched
  the development outputs in all six networks.

## 1. What substation telemetry can see (detection, no action, daylight)

Recall of avoidable violations. Substation = transformer device plus feeder-head currents;
realistic readings.

| Network | Truth | Events | Substation | + 1 sensor | + 2 sensors | Full | False-alarm rate, + 2 / full |
|---|---|---|---|---|---|---|---|
| rural2 | nominal | 424 | 0.99 | 0.98 | 0.98 | 1.00 | 0.002 / 0.017 |
| rural2 | MV 1.055 | 1392 | **0.27** | 0.75 | 0.77 | 1.00 | 0.140 / 0.894 |
| rural3 | nominal | 425 | 0.98 | 0.98 | 0.99 | 1.00 | 0.006 / 0.096 |
| rural3 | MV 1.055 | 2581 | **0.14** | 0.70 | 0.77 | 1.00 | 0.144 / 0.926 |
| semiurb4 | nominal | 479 | **0.25** | 0.23 | 0.22 | 0.97 | 0.000 / 0.001 |
| semiurb4 | fixed cos φ | 658 | **0.49** | 0.48 | 0.49 | 0.99 | 0.000 / 0.001 |
| semiurb5 | MV 1.055 | 1033 | **0.37** | 0.82 | 0.84 | 1.00 | 0.036 / 0.164 |
| urban6 | MV 1.055 | 1877 | **0.14** | 0.19 | 0.76 | 1.00 | 0.137 / 0.830 |

The other cells are in the full report. The tap truth behaves like MV 1.055.

**Findings.**

1. **Substation telemetry detects no overvoltage as such.**
   - The busbar voltage moves with the offset but never exceeds 1.10 p.u.; the highest
     value is 1.095 p.u., in rural2 under MV 1.055.
   - Its voltage-event recall under the tap and MV truths (0.14–0.45, S1) is made up
     entirely of overvoltage steps that coincide with a detected overload. For example,
     in rural2 under MV 1.055, 382 of 1392 = 0.27.
   - Transformer and feeder-head overloads are detected with recall 0.96–0.99.
2. **In semiurb4 the binding cables are downstream segments of one feeder trunk.**
   - The most loaded is the far-end segment, at 134 %. The feeder-head line exceeds
     100 % in only 115 of 479 line-overload steps under the nominal truth.
   - Substation recall is 0.13–0.49 under every truth.
   - Remote voltage sensors with threshold detection do not change it. Only the full
     reference, which measures every cable, detects these overloads.
   - In semiurb5 and urban6, by contrast, the feeder-head line itself overloads on
     98–100 % of those steps, so the substation sees them.
3. **Noisy meters near the limit raise false alarms.**
   - With smart-meter noise σ = 0.01 p.u. and remote voltages under the voltage-offset
     truths just below the limit, noisy readings cross it.
   - The false-alarm rate is 0.003–0.144 with two sensors.
   - With every bus metered it is 0.04–0.93: 0.67–0.93 in rural2, rural3 and urban6
     under the tap and MV truths, the maximum over many noisy buses.

## 2. Decisions under limited telemetry (primary hypothesis P)

Cells meeting the requirement with `replay_aci`, out of 15 mismatch cells (evaluation
half):

| Telemetry | realistic (primary) | ideal readings | precise meters (0.2 %) |
|---|---|---|---|
| none (`static_dev`, open loop) | 1 | — | — |
| transformer device only | 2 | 2 | 2 |
| substation | **4** | 4 | 4 |
| substation + 1 topology sensor | 12 | — | — |
| substation + 2 topology sensors | **14** | **9** | 10 |
| substation + 4 topology sensors | 14 | — | — |
| full observability | **15** | 14 | 15 |

**The registered verdict on P (evaluation stage) is SUPPORTED:**

- C(substation) = 4 ≤ C(full) − 3 = 12;
- C(substation + 2) = 14 ≥ C(full) − 1 = 14, with no slack.

Under the realistic condition, the outcomes of + 2 topology and full are far from the
threshold. Their cells that meet it have at most 8 of the 18 allowed steps, and those
that fail have at least 155. So 14 and 15 are not borderline.

**Four qualifications decide how to read it.**

1. **In the development half, P was not supported.**
   - On the same five networks: substation 0, + 2 topology 4, full 6 cells, so P(b) fails
     (4 < 5).
   - With exact readings: 0, 0 and 1 cells.
   - The development half covers the controller's learning phase: τ starts at 0 on day 35
     while PV rises towards its June peak.
   - P is therefore a statement about a controller whose margin has already adapted, not
     about a cold start.
2. **Under the realistic condition, part of the "recovery" is noise-driven
   conservatism.**
   - With exact readings, two topology sensors meet the requirement in only 9 cells, so
     P(b) would fail. With 0.2 % meters it is 10.
   - The feedback counts readings above the limit. Noise therefore adds alarms that push
     the margin up, and that also covers violations the sensors cannot see.
   - Measurement noise is modelled as independent per reading. Real meter error is
     largely a fixed bias per device, which would act differently.
   - The cost is curtailment. Summed over the five networks (avoidable violations /
     curtailed MWh):

     | Telemetry | MV 1.055 truth | Nominal truth |
     |---|---|---|
     | substation | 6968 / 46.2 | 54 / 51.7 |
     | + 2 sensors, realistic | 0 / 700.8 | 30 / 145.1 |
     | + 2 sensors, ideal | 193 / 361.4 | 57 / 53.4 |
     | full, realistic | 0 / 732.7 | 2 / 320.7 |
     | full, ideal | 64 / 404.5 | 25 / 53.7 |
     | oracle (unattainable) | 0 / 279.5 | 0 / 39.3 |

   - **Under the correct model with exact readings, more telemetry costs nothing:**
     substation 53.4, two sensors 53.4, full 53.7 MWh.
   - With realistic readings, the two-sensor and full configurations curtail 145.1 and
     320.7 MWh. **The difference is entirely noise-driven.**
   - Of that, 29 and 123 MWh fall on days on which no action would have caused no
     avoidable violation.
   - Figure: `outputs/sense_study/figures/telemetry_noise.svg` (from
     `docs/provenance/phase5/scripts/figure.py`).
3. **rural3 relies on the fallback.**
   - Under the tap and MV truths, the realistic-condition successes coincide with the
     NO_FEASIBLE_ACTION fallback (s. 6). τ reaches its 0.40 bound, and on up to 28 of 183
     days no cap level satisfies the replayed margin.
   - With exact readings:
     - under MV 1.055, even full metering fails rural3 (19 steps against the 18.3
       allowed);
     - under the tap truth, full and + 2 decision-aware meet the requirement (11 steps)
       while + 2 topology fails.
4. **The cost of reaching the requirement under the voltage-offset truths is high
   whatever the telemetry.**
   - The oracle itself curtails 210–280 MWh (5.4–7.1× the nominal oracle).
   - On the networks tapped to −1, these truths are the stress brackets of Phase 4
     amendment 4B. An operator would re-tap instead.

**Paired per-day differences, + 2 topology sensors minus substation** (realistic).
Avoidable violations per day and curtailed MWh per day, with 95 % percentile intervals
from a circular 7-day block bootstrap:

| Network | Tap −1 truth | MV 1.055 truth | Nominal truth (curtailment) |
|---|---|---|---|
| rural2 | −5.6 [−8.1, −3.3] viol.; +0.59 [+0.44, +0.74] MWh | −7.6 [−10.5, −4.8]; +0.59 [+0.44, +0.74] | +0.049 [+0.025, +0.076] |
| rural3 | −11.9 [−15.3, −8.4]; +1.56 [+1.20, +1.92] | −14.1 [−17.9, −10.2]; +1.60 [+1.23, +1.98] | +0.225 [+0.139, +0.317] |
| semiurb4 | −0.15 [−0.31, −0.04]; +0.014 [+0.006, +0.024] | −0.50 [−0.85, −0.21]; +0.083 [+0.052, +0.116] | +0.000 [+0.000, +0.001] |
| semiurb5 | −4.8 [−6.9, −2.9]; +0.44 [+0.30, +0.58] | −5.6 [−7.9, −3.5]; +0.44 [+0.30, +0.58] | +0.090 [+0.046, +0.138] |
| urban6 | −8.0 [−10.7, −5.3]; +0.86 [+0.64, +1.09] | −10.3 [−13.4, −7.0]; +0.86 [+0.64, +1.09] | +0.146 [+0.083, +0.220] |

- Under the fixed-cos φ (loading) truth the differences are about 0: voltage sensors with
  threshold detection do not see overloads.
- **Caveats on the intervals.**
  - Every comparison uses the same resampled blocks.
  - Percentile intervals on zero-inflated daily counts (e.g. semiurb4) may under-cover.

## 3. Value of additional sensors and of placement (S2, S3)

**Sensor-value curve (S2).** For topology placement under the realistic condition, the
number of mismatch cells meeting the requirement is 4 → 12 → 14 → 14 for k = 0, 1, 2, 4.

- The curve is non-decreasing, and the first sensor recovers 8 of the 10-cell gain:
  returns diminish.
- The fourth sensor adds no cell.
- This is the registered, realistic-condition curve. With exact readings, two sensors
  reach 9 cells, about half of the gap.

**Placement rules** (cells meeting the requirement, realistic, k = 1 / 2 / 4):

| Rule | k = 1 | k = 2 | k = 4 |
|---|---|---|---|
| mandatory-like | 14 | 14 | 14 |
| topology | 12 | 14 | 14 |
| historical risk | 12 | 14 | 14 |
| greedy detection | 12 | 14 | 14 |
| decision-aware greedy | 14 | 14 | 14 |
| random (20 seeds) | median 10, range 10–12 | median 12, range 10–14 | median 12, range 10–14 |

**S3 (registered, realistic): decision-aware placement is not better than the simple
rules.** The counts are against topology 0 of 5 networks, risk 2 and mandatory-like 1.

- **The counts do not discriminate.** At k = 2, all four rules meet the requirement in the
  same number of cells in every network.
- **The tie-break on curtailment is decided by noise.**
  - The differences are 0.02–0.6 %; semiurb4 is the exception, where decision-aware
    curtails 99.8 MWh against topology's 38.1.
  - The noise seed is derived from the configuration's name, so even identical sensor
    sets (rural2: decision-aware = topology = risk) differ only by noise (s. 11).
  - The per-rival counts (0, 2, 1) are therefore noise. The verdict "not better" stands
    only because no rule meets more cells.
- **With exact readings, decision-aware placement is better** (descriptive, not
  registered).
  - + 2 decision-aware meets 13 cells against topology's 9. It is better in 3 of 5
    networks (rural3, semiurb4, urban6) and equal in two.
  - With 0.2 % meters, missing-only or delay-only readings the counts are 14, 13 and 12
    against 10, 9 and 9.
  - **The placement null is conditional on noise.**
- **Context for the comparison.**
  - The decision-aware design used two mismatch truths (tap, fixed cos φ) on development
    days, as disclosed in protocol s. 4.
  - Amendment 5B, informed by development data, pushed the greedy rules toward topology
    order.
- **Mandatory-like placement** (largest PV first) met 14 cells at every budget under
  realistic readings. It was not run with exact readings.
  - It mirrors the distribution key of the Consentec/BUW (2024) study for German
    smart-meter rollout: mandatory installations ordered by rated power, then random.
  - The legal obligation is a threshold, so "largest first" is an idealisation.
- **Random placement.** Every rule beats the random median by 2–4 cells at k = 1 (realistic).
- **Voltage-offset cells with exact readings.** Placements designed on the nominal model
  (all rules except decision-aware) are less robust there: + 2 topology meets only 5 of
  the 10 voltage-offset cells.

## 4. Which model errors measurements can and cannot correct

| Mismatch type | What substation telemetry does | What remote voltage sensors add | What is needed |
|---|---|---|---|
| Voltage offset (tap, MV voltage) | Sees the offset in the busbar voltage (model-consistency flag on 100 % of days), but not the remote violations (recall 0.14–0.45) | Most of the detection (0.73–0.84 with two sensors; 0.25–0.27 in semiurb4) and, with noisy readings, the decision recovery, at high curtailment | A remote voltage reading, or simply re-tapping |
| PV reactive power (fixed cos φ 0.95) | Sees transformer and feeder-head overloads (recall 0.97–0.99 except semiurb4) | Nothing with threshold detection (differences ≈ 0) | Current sensing where the overload occurs. In semiurb4 these are downstream cable segments that no configuration below "full" measures. Estimating cable currents from metered P and Q was not tested |

## 5. State estimation

**Observability.**

- Substation measurements alone are never observable. The Jacobian rank is 9 of 193 to
  23 of 257 states in the new networks, and 5 of 29 in rural1.
- pandapower's own check only counts measurements. The rank test is Phase 5's.
- With forecast pseudo-measurements of every customer bus, the sets are observable.
- With amendment 5A (no current magnitudes as inputs), the estimator converged on
  ≥ 99.6 % of sampled steps. The lowest rates were 99.6 % in rural1 and 99.8 % in
  semiurb5, both under fixed cos φ.
- **Zero-injection buses are soft constraints.** pandapower weights them with σ = 0.001
  (1 kW at a 1 MVA base), which is looser than the 0.5 kW pseudo-measurement floor.

**Detection from substation readings plus pseudo-measurements.**

- Sample: every third evaluation day, 11:00–14:00 UTC, no action, realistic readings.
- Each cell gives voltage-event recall (state estimation vs direct) and the false-alarm
  rate of state estimation for any violation.
- The median voltage RMSE was 0.0014–0.0047 p.u.

| Network | Tap −1 | MV 1.055 | Fixed cos φ (FA, SE / direct) | Nominal (FA, SE / direct) |
|---|---|---|---|---|
| rural2 | 0.88 vs 0.48; FA 0.008 | 0.91 vs 0.34; FA 0.045 | 0.002 / 0.002 | 0.002 / 0.002 |
| rural3 | 0.92 vs 0.21; FA 0.064 | 0.94 vs 0.15; FA 0.038 | 0.003 / 0.003 | 0.002 / 0.002 |
| semiurb4 | 1.00 vs 0.32; FA 0.033 | 1.00 vs 0.21; FA 0.022 | 0.042 / 0.000 | 0.025 / 0.000 |
| semiurb5 | 1.00 vs 0.55; FA 0.030 | 0.99 vs 0.44; FA 0.031 | **0.171** / 0.000 | 0.017 / 0.000 |
| urban6 | 0.91 vs 0.28; FA 0.046 | 0.92 vs 0.22; FA 0.089 | **0.116** / 0.000 | 0.037 / 0.002 |

**State estimation under the voltage-offset truths.**

- It detects 0.88–1.00 of the remote overvoltage events.
- That success is structural. The estimator treats the MV voltage magnitude as a state,
  and the busbar reading pins it. An offset upstream of the busbar is therefore absorbed.

**Under the fixed-cos φ truth it gives confident gross errors.**

- Its planning model assumes PV draws no reactive power, and every reactive-power
  measurement has a tight σ.
- Reviewer-computed example: semiurb5, day 186, 11:30 UTC, exact readings.
  - The transformer measures −0.209 MVAr, while the pseudo-measurements sum to
    +0.016 MVAr.
  - The "converged" estimate puts one bus at 1.202 p.u. (true 1.055) and one line at
    301 % (true 109 %).
  - The 95th percentile of the maximum voltage error is 0.138 p.u. in semiurb5.
- No bad-data test (chi-square or largest normalised residual) was implemented. It would
  very likely have rejected these estimates.
- Overall, false alarms exceed 0.05 in four evaluation cells: rural3 tap, urban6 MV, and
  semiurb5 and urban6 under fixed cos φ.

**The gate (decided on development data).**

- The detection gain was large: SE recall 0.90–0.98 against direct 0.12–0.42.
- False alarms were 0.055 (semiurb4), 0.107 (semiurb5) and 0.104 (urban6), above the
  registered 0.05, so the gate closed with 2 of 5 networks. State-estimation feedback was
  **not** part of the evaluation.
- **The verdict was a knife-edge.** semiurb4 missed by 0.005, and one more passing network
  would have opened it.
- **The largest false-alarm rates come with the fixed-cos φ model error, not meter
  noise.** In the evaluation sample, semiurb5 and urban6 reach 0.171 and 0.116 under that
  truth, against 0.022–0.089 under the voltage offsets.
  - The stored gate file has no per-truth breakdown, so its effect on the gate count is
    not shown here.
- In the first development run the gate had opened only because failed estimates raised no
  alarms (amendment 5C).

## 6. Evidence labels

- **MODEL_INCONSISTENCY (S5, idealised).**
  - Flagged on 100 % of days under the tap and MV-voltage truths in every network.
  - Under fixed cos φ it is flagged on 88–92 % in the new networks (93 % in rural1), and
    under the nominal truth on 0 %.
  - It is idealised: metered injections are exact and the MV voltage does not vary. Noise
    proportional to a near-zero reactive power is itself near zero, which flatters the
    reactive-power part. A class-0.5 voltage-transformer error alone is about the
    0.005 p.u. threshold.
  - It does not identify which parameter is wrong: tap and MV voltage look alike.
  - It is the clearest positive result for substation telemetry. Telemetry that cannot
    see where limits are violated can still show that the model is wrong.
- **INSUFFICIENT_EVIDENCE (S6).** The label is configuration-level, from development
  coverage below 0.8. Over (network × configuration), where "fail" means missing the
  requirement under at least one mismatch truth:

  | | fails | meets |
  |---|---|---|
  | insufficient | 79 | 0 |
  | sufficient | 55 | 261 |

  - **Supported by rule, but driven by one network.** 77 of the 79 insufficient
    configurations are in semiurb4, and all of them fail through its fixed-cos φ cell.
    The other two are the transformer-only configuration in semiurb5 and urban6.
  - **The units are pseudo-replicated.** 60 of each network's 79 configurations are
    random placements.
  - **"Sufficient" did not guarantee success.** Development coverage under the nominal
    model cannot reveal violations that only a model error creates.
- **NO_FEASIBLE_ACTION.** It fired in rural3 under the tap and MV truths, and only with
  noisy readings.
  - It fired in 79 of the 104 `replay_aci` runs per truth: every realistic run with remote
    voltage sensors, and three noise-only runs.
  - Each of those runs had 28 of 183 evaluation days with the label, except one with 21.
  - That is 4,417 run-days in total.
  - Noise-driven alarms pushed τ to its 0.40 bound. At that bound no cap level, not even
    zero PV, reaches the replayed margin, so the policy falls back to the deepest cap.
  - In that sense the label works as intended: curtailment alone cannot buy the demanded
    margin, and the operator's remedy would be re-tapping.
  - But here it is triggered by false alarms, and with exact readings τ never reached the
    bound.
  - It never fired in the development half or with substation-only telemetry.
  - It is evaluated over all 96 steps, night included.

## 7. Measurement realism (S7)

Cells meeting the requirement, by condition:

| Configuration | ideal | realistic | noise only | missing only | delay only | precise meters |
|---|---|---|---|---|---|---|
| transformer | 2 | 2 | 2 | 2 | 2 | 2 |
| substation | 4 | 4 | 4 | 4 | 4 | 4 |
| + 2 topology | 9 | 14 | 14 | 9 | 9 | 10 |
| + 2 decision-aware | 13 | 14 | 14 | 13 | 12 | 14 |
| full | 14 | 15 | 15 | 14 | 14 | 15 |

- **S7 fails for "+ 2 topology"** (|14 − 9| = 5 > 1). It passes for + 2 decision-aware
  (|14 − 13| = 1) and full (|15 − 14| = 1).
- **Noise is the factor that changes the outcome.** Loss of 5 % of sensor-days and a
  one-day delay do not: they use exact readings and match the ideal column within one
  cell.
- **The direction is the warning.** Noise makes the count-based controller more
  conservative, so its "reliability" partly reflects false alarms (s. 2).
  - This direction is expected when calibrating on noisy labels (Einbinder et al. 2024).
  - What Phase 5 adds is its size, and that it reverses a registered verdict.

## 8. Hypotheses: verdicts

| Hypothesis | Verdict | Key evidence |
|---|---|---|
| P: feedback needs to observe the binding constraint | **Supported** in the registered evaluation stage under realistic readings (4 / 14 / 15). **Not supported** in the development half (0 / 4 / 6). **Not robust** to exact readings (9 vs 14) | s. 2 |
| S1: substation voltage recall < 0.5 wherever voltage events occur | **Not supported as registered.** True under the tap and MV truths (0.14–0.45). Under the nominal truth, the few voltage events coincide with detected overloads (recall 1.0 in rural3, semiurb5, urban6) | s. 1 |
| S2: non-decreasing value curve; first sensor recovers ≥ half | **Supported** (4 → 12 → 14 → 14), realistic readings | s. 3 |
| S3: decision-aware placement better than simple rules | **Not supported**, as predicted, but uninformative: the rules tie on cells, and tie-breaks are decided by noise. With exact readings decision-aware was better (13 vs 9, descriptive) | s. 3 |
| S4: state estimation compensates for missing sensors | **Gate closed** on false alarms, by a narrow margin (semiurb4 0.055). Detection gain large under voltage offsets; gross errors under fixed cos φ; decisions only exploratory | s. 5, s. 9 |
| S5: model-consistency label | **Met**, idealised | s. 6 |
| S6: insufficiency label predicts failure | **Supported by rule** (79/79 fail), driven by semiurb4; sufficient ≠ safe (55 of 316 fail) | s. 6 |
| S7: realism changes cells by ≤ 1 | **Not supported** for + 2 topology (noise). Met for + 2 decision-aware and full | s. 7 |

## 9. Exploratory: state-estimation feedback on development days

This run was not registered as a hypothesis test. Amendment 5C allowed it on development
days only, after the gate closed.

- **Setup.**
  - `replay_aci` with substation readings, plus state-estimation inference on steps with
    measured reverse flow and no direct alarm.
  - Realistic readings; all networks and truths; 147 development days.
  - Script: `docs/provenance/phase5/scripts/exploratory_se_feedback.py`.
  - Output: `outputs/sense_study/exploratory/se_feedback_development.json`.

| Telemetry (development half) | Mismatch cells meeting the requirement (of 15) | Curtailed MWh, mismatch truths | Nominal truth: avoidable violations / curtailed MWh |
|---|---|---|---|
| substation | 0 | 335.1 | 145 / 87.5 |
| substation + state estimation | **7** | 1513.3 | 34 / 167.2 |
| + 2 topology sensors | 4 | 1661.4 | 120 / 170.4 |
| full | 6 | 1799.9 | 21 / 349.6 |

- **The count mixes two kinds of success.** State estimation meets more development cells
  than any measured configuration. Of the seven:
  - Four are voltage-offset cells in semiurb4 and semiurb5. These look genuine: detection
    recall there is about 1.0 with false-alarm rates of 0.022–0.033 (evaluation sample,
    s. 5). In semiurb4 it meets them where two topology sensors do not.
  - Three are fixed-cos φ cells (semiurb4, semiurb5, urban6). There they coincide with
    the gross estimation errors and false alarms of s. 5. In semiurb5 it curtails
    131.9 MWh against substation's 59.1; in semiurb4 it reaches 0 violations where full
    metering has 21.
- **It fails the remote-overvoltage cells in rural2, rural3 and urban6** (27–91
  violations against the 14.7 allowed), although its detection recall there is about
  0.9 (evaluation sample).
- **Its nominal-truth curtailment is about the same as two noisy sensors'** (167 vs
  170 MWh).
- **Reading.**
  - Model-based inference from substation readings partly substituted for missing sensors
    in two networks under voltage offsets.
  - Its fixed-cos φ "successes" rest on gross estimation errors, which a bad-data test
    should catch.
  - Its failures in rural2, rural3 and urban6 are not explained here.
  - This result is exploratory and labelled as such.

## 10. What Phase 5 shows, and does not

**Shows**, on five PV-stressed synthetic benchmark networks with persistent model errors:

- **What substation telemetry is enough for.**
  - It suffices for transformer and feeder-head overloads.
  - It detects no remote overvoltage as such. A feedback controller driven by it fails
    the requirement in 11 of 15 mismatch cases (evaluation half).
- **Remote voltage readings, under the registered realistic condition.**
  - One or two raised the cells meeting the requirement from 4 to 12–14 of 15.
  - With exact readings, two topology sensors reached 9, so about half of the apparent
    recovery reflects noise-driven conservatism.
  - In the development half, even full metering met only 6 cells.
- **Placement.**
  - Under 1 % meter noise, decision-aware placement was not better than simple rules (S3),
    but the rules tied on cells.
  - Under exact, missing-only, delay-only and precise-meter conditions it met the
    requirement in 12–14 of 15 cells against 9–10 for topology placement (descriptive).
  - The placement null is conditional on noise.
- **Measurement noise interacts with count-based feedback.**
  - Realistic smart-meter noise near the limit produces false alarms that the controller
    turns into curtailment.
  - Under the correct model, all the extra curtailment of additional noisy sensors is
    noise-driven: 51.7 → 145.1 MWh with two sensors and 320.7 MWh with full metering,
    against about 53 MWh with exact readings in every configuration.
  - The direction is expected from calibrating on noisy labels. The size, and the
    reversal of a registered verdict, are this study's main methodological finding.
- **Threshold detection on remote voltages did not detect mid-feeder cable overloads.**
  Estimating cable currents from metered P and Q was not tested.
- **The model-consistency flag.** In an idealised test (exact metered injections, constant
  MV voltage), it fired on every day under the voltage-offset errors and on no day under
  the correct model. It does not identify which parameter is wrong.
- **State estimation from substation readings plus forecast pseudo-measurements.**
  - It detects most remote overvoltages caused by an upstream voltage offset.
  - It produces confident gross errors when the model error is spread across the network
    (PV reactive power).
  - Its false alarms exceeded the registered gate.

**Does not show:**

- anything about a real utility, KIB-TEK included;
- per-unit curtailment or the value of Q(U) control;
- time-varying model errors, unbalanced three-phase effects, or real meter behaviour
  (bias, averaging, clock errors);
- a noise-aware feedback rule (guard band, persistence, interval test) or a bad-data test
  for state estimation. The results suggest both are the next design steps;
- a new placement method. Decision-aware placement is known in the literature; here its
  advantage appeared only with exact readings.

## 11. Post-evaluation reviews and checks

**Reviews.** Four independent read-only reviews ran after the evaluation: power systems
with state estimation, leakage with reproducibility, statistics, and novelty. Their
corrections to this document are applied above.

**Confirmed facts.**

- **Registration timeline.** Protocol at 15:25:03Z, the first development run 9 s later,
  amendments 5A/5B at 15:47:22Z, and 5C plus the freeze at 16:03:27Z. The evaluation
  started at 16:04:46Z.
- **Hashes.** The evaluation metadata's code and protocol hashes match the freeze and the
  current files.
- **Truth reaches decisions only through the measurement function,** the oracle
  reference, and the disclosed planning channel (replay of the nominal model on past
  metered injections).
- **Pseudo-measurements use strictly past days.** The state-estimation detector never
  reads the true state.
- **Physics consistency** (`docs/provenance/phase5/scripts/post_evaluation_checks.py`).
  All 7,920 full-state margin arrays (6 networks × 4 truths × 330 days) are bit-identical
  in float32 to the Phase 4 physics cache, with identical failure patterns. The readings
  and the scoring therefore come from the same flows.
- **No unavoidable violations** (same script). In both halves, no daylight step has a
  violation that no cap level avoids. Counting non-avoidable steps as negatives therefore
  never turns a correct flag into a false alarm.
- **Physics of the truths.**
  - Tap −1 (HV side, 2.5 % steps) raises the busbar voltage by about 0.0275 p.u.
  - MV 1.055 raises it by about 0.0305 p.u.
  - Fixed cos φ 0.95 absorbs Q = −0.329 P.
  - Every LV bus has limits of 0.90–1.10 p.u., and every branch a 100 % loading limit.

**Confirmed code defects.** None changes a registered verdict. The frozen code was left
unchanged so that the evaluation stays reproducible, and fixes are recommended for the
next phase.

1. **Noise seeds are derived from the configuration's name, not its sensors**
   (`sensing.seed_of`).
   - Identical sensor sets get different noise, so there are no common random numbers.
   - This decides the S3 tie-breaks (s. 3).
   - `seed_of` sums bytes, so seeds also collide: 79 run identities map to 45 seeds per
     truth.
2. **The evaluation guard checks file names only.** It writes no start marker and does not
   check the frozen hashes.
3. **NO_FEASIBLE_ACTION is evaluated over all 96 steps,** not only daylight.
4. **No bad-data test in state estimation** (s. 5).

**Tests.**

- **Added after the reviews.** Neither changes the frozen code.
  - `test_sensor_design_uses_development_days_only`: changing evaluation-day truth,
    states and plans leaves every placement unchanged, while changing development data
    moves them.
  - `test_seed_of_is_unique_across_run_identities`: a strict expected failure that
    documents the seed collision until it is fixed.
- **Still recommended.**
  - Identical sensor sets give identical records.
  - The CLI guard refuses a second evaluation run.
  - Missing readings, delay and substation/remote overlap tested together.
