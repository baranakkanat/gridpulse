# Phase 9 results: day–night voltage-residual contrast at sparse, pre-committed meters

**Status.**

- **Registration:** `docs/provenance/phase9/phase9_registration.md`, committed in `a229dd6`
  (sha256 `737a252d…f5bc4e1`) before any Phase 9 statistic was computed. It was admitted by the
  owner on 2026-10-23 as Option B of the reviewed scoping design (Paperclip AKK-19 to AKK-22).
- **Evaluation:** one run on 2026-10-23, over the scored days of 2016-07-01 – 12-30 (183 days),
  at the no-cap level only.
- **Outputs** (all under `analysis/phase9/`):
  - code: `phase9_sweep.py` (`e2457a86…`) and `phase9_analysis.py` (`fade9b8e…`), with
    234 unit tests. 231 ran at execution; three cache-free Stage 0/4 tests were added
    afterwards (s. 9);
  - Stage 1 inputs: `results/phase9_inputs.json` (`8c09855e…`);
  - results: `results/phase9_results.json` (`daff6f96…`);
  - gate: `results/phase9_gate.json` (`a1c637e7…`);
  - sweep artefacts: 99 runs under `sweep/0ddb53ee56a5af81/`, with manifest `42dc448e…`;
  - Stage 3 part files: 18 JSON files under `results/stage3_parts/`, merged into the results
    file (s. 11).
- **Reviews:** four AI-assisted independent reviews (s. 11). They are not external peer review.
- **Data licence and attribution:** the networks and 2016 profiles come from the SimBench
  benchmark dataset (package 1.6.3). Its database is licensed **ODbL 1.0**, with contents under
  **DbCL 1.0**.
  - `results/phase9_inputs.json` restates each candidate line's recorded electrical
    parameters and topology. The sweep arrays, `phase9_results.json` and the Stage 3 parts are
    statistics derived from them.
  - The repository has no software licence (README), and `docs/technical_limitations.md`
    states that derived outputs are not committed. The Q1 addendum's derived results were
    nevertheless committed in `1bba4e8`.
  - **Whether these artefacts are published, and under what licence and attribution, is the
    owner's decision. This document does not settle it.**

**Identity.**

- This is an **exploratory study on examined data**: the SimBench LV networks and 2016
  profiles of Phases 4–8 and the Q1-L1 addendum.
- It contains **one pre-registered held-out statistic** (R5, s. 6), labelled
  "pre-registered held-out statistic, exploratory programme".
  - The label applies to the **observed** term m(b*). The band [0.50, 0.90] was fixed from the
    two Q1 sweep anchors (0.738 and 0.625) before any held-out residual existed.
  - The four held-out networks' per-bus residuals and downstream sets were first computed
    after the registration commit.
  - **Already known before the commit:**
    - their `line_local` margins and violation counts (Phase 8);
    - the identity of each `line_local` cable, which Phase 8 chose by maximising downstream
      PV × R;
    - their line and feeder counts (AKK-19, from the frozen Phase 8 facts);
    - their line tables, loaded by the board for the registration's s. 3 structural
      invariants (s. 11).
  - The prediction m_pred = 0.5 · R · P / V² is a function of that line table and of the
    examined PV profiles, so it was in principle computable before the commit. **R5 is held out
    in its observed term only, on examined, not fresh, networks.**
- **Nothing here is confirmatory, and nothing is evidence about a real feeder.**
- The residual Δ is noise-free, has no state-estimation error, is taken at no cap and assumes
  constant-power injections. **Every detection rate in this document is therefore an upper
  bound** for a single-cable impedance-record error (registration s. 1).

**Reading guide.**

- **Units:** p.u. throughout. σ_tot is the meter voltage noise; σ = 0.01 and σ = 0.005 are
  the co-primary values.
- **Signal:** k is the day–night contrast of Δ at one bus, averaged over retained days. It
  is insensitive to any fixed per-meter calibration offset.
- **Meters:** a *configuration* is the first K buses of one of the 25 placement rules frozen
  in Phase 6 (5 named, 20 random). A *pair* is (candidate cable, rule).
- **Band C:** the largest |k| over the configuration is at or above z_K · F_C,real.
  F_C,real is the registered contrast floor under `realistic` noise, and z_K is
  Bonferroni-corrected over K meters.
- **Coverage:** the share of pairs in band C. The *topological ceiling* is the share of
  pairs whose configuration contains at least one bus below the faulty cable.
- **Cables:** "Downstream(l)" is the set of LV buses below cable l. A cable "reverses" if
  its downstream net flow changes direction between day (PV export) and night (load).

## 1. Answer in brief

1. **Coverage is low at sparse, pre-committed meters.** At σ = 0.01 with K = 2 meters, 4.7 %
   (semiurb4) and 4.6 % (urban6) of (cable, rule) pairs detect the error.
   - At σ = 0.005 the shares are 9.6 % and 5.4 %.
   - The topological ceiling is 33 % and 22 %.
   - Even with a meter below the faulty cable, only 14 % and 21 % detect (σ = 0.01).
   - The signal lives in a few cables with heavy downstream PV: 5 of 39 (semiurb4) and 6 of
     50 (urban6) clear the threshold.
2. **A meter not below the faulty cable never detects it:** 0 of 653 and 0 of 974 pairs at
   K = 2, and zero at every other σ and K. In the noise-free physics, the contrast does not leak into the wrong
   part of the feeder.
3. **Localisation by night sign works only for cables whose flow reverses.**
   - R1 and R2 hold at σ = 0.01: 24/24 and 53/53 pairs show the predicted opposite sign.
   - Both fail at σ = 0.005, each at a single cable: semiurb4 line 39 and urban6 line 32.
     Both cables have zero or almost zero downstream PV, which is the failure mode stated
     before any number existed.
   - Against the random-cable baseline, at σ = 0.01 a detected set matches another cable's
     section in only 0.27 % and 0.37 % of pairs (0.27 % and 0.61 % at σ = 0.005).
4. **The held-out magnitude test R5 fails narrowly.**
   - rural2's observed-to-predicted ratio is 0.490, against a registered band of
     [0.50, 0.90].
   - rural1, rural3 and semiurb5 give 0.580, 0.715 and 0.703.
   - The Q1 magnitude predictor therefore does not transfer within its band. Under the
     registration, **the screening score S_l must not be used to extrapolate coverage beyond
     the 89 swept cables.**
5. **The registered false-alarm floor is optimistic (R7 fails).**
   - Under truth = nominal, the registered noise conditions raise false alarms at a
     family-wise rate of **0.064–0.078 instead of at most 0.05**.
   - The coverage figures in item 1 are computed against that same threshold. They therefore
     correspond to a simulated false-alarm rate of 6–8 %, not 5 % (s. 4).
   - A post-hoc check (not registered, and not independently reviewed) finds the coverage
     counts unchanged by a threshold raised to compensate (s. 4).
6. **Diurnal systematic error is the binding limit.**
   - A day/night meter or model error of only **0.01 σ_tot (1e-4 p.u. at σ = 0.01) doubles the
     false-alarm rate**.
   - 0.02 σ raises it to 0.31–0.32, about 4.5–4.7 times the baseline, and 0.06 σ makes
     essentially every configuration alarm.
   - The registered A*_fa cannot be estimated, because the rate already exceeds 0.05 with no
     bias at all (s. 8).
   - A fixed calibration offset cancels in the contrast; a diurnal one does not.
7. **The signal is linear in the size of the error and blind to its type.**
   - |k| scales with the resistance increment to within 0.19 %.
   - The smallest error still detected at σ = 0.01 (K = 2) is +10 % resistance in semiurb4 and
     +25 % in urban6.
   - A wrong recorded length, which scales R and X together, matches the resistance-only
     prediction to within 1.2–2.2 %.
8. **Two registered rules about the shape of the signal:**
   - R3 fails narrowly: the per-cable Spearman correlation is 0.886 and 0.863, against 0.9.
   - R4 holds: |k| is flat below the faulty cable, with CV ≤ 0.004.

## 2. What was computed

- **Candidates:** 89 cables, every non-feeder-head line of semiurb4 (39) and urban6 (50).
  Stage 1 checked the structural invariants in all six networks:
  - radial, connected, acyclic;
  - single, in-service lines, with closed line switches.
- **Errors:**
  - W6: resistance × 1.5 and rating × 0.8 on each candidate; this is the `line_local` error.
  - W8: resistance × {1.1, 1.25, 2.0} at the registered cables (semiurb4 line 37, urban6
    line 3).
  - W9: length × {1.25, 1.5} at the same cables.
- **Physics:** 99 runs, 1,739,232 new level-0 power flows, with 0 failed flows and 0 non-finite
  nominal entries. All runs used the one-worker fallback, 84–100 s each (median 90 s); the agent sandbox
  refuses a process pool, and the registration provides for this.
- **Reproduction gate (s. 9):** at the two registered cables, the new engine reproduces the
  frozen Phase 8 `line_local` voltages to E = 1.19e-7 p.u. That is one float32 rounding step,
  with E_C ≈ 1.4e-10 and identical NaN patterns.
- **Days:** 170 retained days for semiurb4 and 175 for urban6, with at least one daylight and
  one night step each, as Q1 had.
- **Zero-flow analyses:**
  - W5: the four held-out networks at their own `line_local` cables, from existing caches.
  - Controls 1–5, of which control 1 is the R7 test and control 2 the A* sweep.

## 3. Coverage (Q9a)

**Band-C coverage over (cable, rule) pairs.** Mean estimator, all 25 rules; 975 pairs for
semiurb4 and 1,250 for urban6. Wilson intervals are descriptive, because pairs share days,
profiles and topology.

| σ_tot | K | semiurb4 coverage | P(C \| meter below) | urban6 coverage | P(C \| meter below) |
|---|---|---|---|---|---|
| 0.01 | 1 | 16 (1.6 %) | 16/193 (8 %) | 32 (2.6 %) | 32/167 (19 %) |
| 0.01 | **2** | **46 (4.7 %)** [3.6, 6.2] | **46/322 (14 %)** | **57 (4.6 %)** [3.5, 5.9] | **57/276 (21 %)** |
| 0.01 | 4 | 59 (6.1 %) | 59/430 (14 %) | 86 (6.9 %) | 86/412 (21 %) |
| 0.005 | 1 | 53 (5.4 %) | 53/193 (27 %) | 37 (3.0 %) | 37/167 (22 %) |
| 0.005 | **2** | **94 (9.6 %)** [7.9, 11.7] | **94/322 (29 %)** | **67 (5.4 %)** [4.2, 6.8] | **67/276 (24 %)** |
| 0.005 | 4 | 107 (11.0 %) | 107/430 (25 %) | 99 (7.9 %) | 99/412 (24 %) |
| 0.003 | 2 | 161 (16.5 %) | 161/322 (50 %) | 78 (6.2 %) | 78/276 (28 %) |
| 0.02 | 2 | 46 (4.7 %) | 46/322 (14 %) | 22 (1.8 %) | 22/276 (8 %) |

**Topological ceiling** (pairs with a meter below the faulty cable):

| | K = 1 | K = 2 | K = 4 |
|---|---|---|---|
| semiurb4 | 19.8 % | 33.0 % | 44.1 % |
| urban6 | 13.4 % | 22.1 % | 33.0 % |

**Readings.**

- **P(C | no meter below the cable) = 0 everywhere.** Detection requires a meter below the
  faulty cable, as R6 already showed at the registered cables.
- **The signal sits in a handful of cables.** In semiurb4, lines 34–38 carry a maximum |k| of
  9.4e-4 to 2.0e-3, and the next cable has 2.5e-4. No cable lies between the σ = 0.01 and
  σ = 0.02 thresholds (3.7e-4 and 7.3e-4), which is why semiurb4's coverage is identical at
  those two σ. In urban6, six cables clear the σ = 0.01 threshold: lines 3 and 5 (1.2e-3),
  29, 33, 22 and 9.
- **The named Phase 6 rules do better than random placement** (control 5), at σ = 0.01, K = 2:
  - semiurb4: 19/195 (9.7 %) against 27/780 (3.5 %);
  - urban6: 30/250 (12.0 %) against 27/1000 (2.7 %).
  These rules were designed for over-voltage detection; the gain is incidental, not designed.
- **Q1's semiurb4 verdict was a placement fact.** At the registered cable, 3, 5 and 5 of the 25
  rules (K = 1, 2, 4) put a meter below it. The `topology` rule that Q1 used is not among
  them; `mandatory` and `decision_aware` are (W2, which matches the expectation).
- **Robustness:**
  - The median estimator gives the same or lower counts: semiurb4 46 and 70; urban6 42 and 67
    (K = 2, at σ = 0.01 and 0.005).
  - The stricter retention rule (≥ 8 daylight steps) leaves every K = 2 headline count
    unchanged.

## 4. The false-alarm floor (R7) and what it means for coverage

**R7 fails.** Control 1 sets truth = nominal and simulates the registered noise on the stored
per-day means:
- Gaussian noise, i.i.d. per reading;
- whole sensor-days missing with p = 0.05;
- a 1-day delay;
- static bias for the matched condition.

The family-wise false-alarm rate of "any of K meters crosses z_K · F_C,real" is then:

| Condition | semiurb4 K = 1 / 2 / 4 | urban6 K = 1 / 2 / 4 |
|---|---|---|
| `realistic` (σ 0.01) | 0.066 / 0.071 / 0.078 | 0.067 / 0.069 / 0.070 |
| `sigma_0.005` | 0.068 / 0.072 / 0.074 | 0.067 / 0.069 / 0.073 |
| `sigma_0.02` | 0.065 / 0.064 / 0.069 | 0.065 / 0.071 / 0.074 |
| `biased_meters_matched`, against F_C,matched | 0.067 / 0.069 / 0.073 | 0.066 / 0.068 / 0.075 |

- The table shows rates pooled over the rules. Of the 600 condition × rule × K cells, 420 have
  a Wilson lower bound above 0.05.
- Against F_C,real, `biased_meters_matched` raises no alarm (0.000), because the static bias
  cancels in k.
- The √2 variant, in which both legs are noisy, gives 0.19–0.34. This is the registered
  sensitivity, not a verdict.
- The excess is the same at every σ, so it is a property of the floor formula, not of the
  noise level.

**Likely cause (HYPOTHESIS).** The registered floor uses the median daylight and night step
counts (n̄_day 38.5 and 43). Real days range from 7 to 63 daylight steps, so the mean of 1/n
exceeds 1/median. The delay and the random missing days add a little more. Read as an
inflation of the contrast's standard deviation, the observed rates imply that the true spread
is 1.05–1.075 times the registered floor.

**Consequence for coverage.**
- Every band-C count in s. 3 is taken against the same z_K · F_C,real. The coverage figures
  are therefore detection shares **at a simulated 6–8 % false-alarm rate, not 5 %**.
  Control 1 tests the floor's treatment of missing sensor-days, delay and day retention; it is
  not an empirical false-alarm rate for a real deployment (registration s. 10).
- POST-HOC (computed by the board from `phase9_results.json`; not registered and not
  independently reviewed): raising the K = 2 threshold by 6 %, 8 % or 10 % leaves all four
  headline counts unchanged (46, 94, 57 and 67). The same recomputation at the registered
  threshold reproduces the registered counts exactly. The gaps in the signal distribution
  (s. 3) make the counts insensitive to a recalibration of this size.

## 5. Localisation (Q9b)

| Rule | σ 0.01, semiurb4 | σ 0.01, urban6 | σ 0.005, semiurb4 | σ 0.005, urban6 |
|---|---|---|---|---|
| R1 conditional night sign (share ≥ 0.90) | holds, 24/24 | holds, 53/53 | **fails**, 24/27 = 0.889 | **fails**, 76/89 = 0.854 |
| R2 detected set ⊆ downstream, Jaccard ≥ 0.8 | holds (5 evaluable cables) | holds (4) | **fails** at line 39 | **fails** at line 32 |
| R3 per-cable Spearman(S_l, max \|k\|) ≥ 0.9 | **fails**, 0.886 | **fails**, 0.863 | **fails**, 0.886 | **fails**, 0.863 |
| R4 flatness (CV ≤ 0.2) | holds (max CV 0.0034) | holds (0.0036) | holds | holds |

**Restriction of the localisation claim (registration s. 14).** Both R1/R2 failures are
non-reversing cables:
- **semiurb4 line 39:** downstream {41, 42, 43}, with 0.0 MVA of installed PV below it.
  m = −2.5e-4, night = −1.2e-4, so day and night have the same sign.
- **urban6 line 32:** 13 downstream buses, 0.031 MVA of installed PV, about 4.6 % of the
  registered cable's PV. m = −2.5e-4, night = −1.9e-4.

These cables become evaluable at σ = 0.005, where their load-driven level residual clears
the floor; at σ = 0.01 it does not.

**The localisation claim is therefore restricted to cables whose downstream flow reverses
between day and night.** For those, at every σ, the night-sign set coincides with the
downstream set.

**Topology-luck baseline (control 4).** At σ = 0.01, a detected set matches another
candidate's downstream set with Jaccard ≥ 0.8 in:
- semiurb4: 4 of 1,482 other pairs (0.27 %);
- urban6: 9 of 2,450 (0.37 %).
At σ = 0.01, every evaluable cable's own downstream set is the best match (5 of 5 and 4 of 4).
At σ = 0.005 this holds for 5 of 6 and 7 of 8; the exceptions are exactly the two
non-reversing cables above. At σ = 0.005 the matching shares are 0.27 % and 0.61 % (15 of
2,450).

**R3 (HYPOTHESIS for the cause).** The registered per-cable shape prediction, read per cable as
sub-decision (iii) allows, fails narrowly. Many candidate cables have S_l = 0, because no PV
sits downstream, but still carry a small load-driven contrast. Their ties and non-zero |k|
lower the rank correlation. The secondary per-bus reading, R3s, is reported in the results
file without a threshold.

**Held-out networks.** At their `line_local` cables, R1, R2 and R4 hold in all four held-out
networks at both σ. These are consistency checks, not tests: such a cable is chosen to
maximise downstream PV × R, and so reverses by construction.

## 6. Held-out magnitude test (W5, R5)

R5 compares m(b*) / m_pred with the band [0.50, 0.90]:
- b* is the bus with the largest |m|, with m signed;
- m_pred = 0.5 · R · P / V², the Q1 formula, at V = 0.4 kV.

| Held-out network | cable | b* (downstream) | m(b*) | m_pred | ratio | in band |
|---|---|---|---|---|---|---|
| rural1 | 8 | 6 (yes) | 1.06e-3 | 1.83e-3 | 0.580 | yes |
| rural2 | 55 | 53 (yes) | 4.25e-4 | 8.67e-4 | **0.490** | **no** |
| rural3 | 52 | 31 (yes) | 8.97e-4 | 1.25e-3 | 0.715 | yes |
| semiurb5 | 2 | 6 (yes) | 7.70e-4 | 1.10e-3 | 0.703 | yes |

- **R5 fails.** It was the one genuinely falsifiable member of W5. The two Q1 anchors were 0.738
  and 0.625; the held-out ratios span 0.49–0.72.
- **Consequence (registration s. 14):** the zero-flow screening score S_l and m_pred must
  **not** be used to extrapolate coverage beyond the 89 swept cables, or to other networks.
- The coverage in s. 3 is measured, not predicted, so it is unaffected.

## 7. Error magnitude and type (W8, W9)

**Magnitude (W8).** Results at the registered cables:

| f (resistance factor) | 1.1 | 1.25 | 1.5 | 2.0 |
|---|---|---|---|---|
| semiurb4, max \|k\| below the cable | 4.01e-4 | 1.00e-3 | 2.00e-3 | 4.00e-3 |
| urban6, max \|k\| below the cable | 2.41e-4 | 6.02e-4 | 1.20e-3 | 2.40e-3 |

- The slope per unit increment agrees across f to within 0.19 %, so the residual is linear in
  the resistance error.
- f*, the smallest factor in band C with a meter below the cable at K = 2:

| | σ 0.003 | σ 0.005 | σ 0.01 | σ 0.02 |
|---|---|---|---|---|
| semiurb4 | 1.1 | 1.1 | 1.1 | 1.25 |
| urban6 | 1.1 | 1.1 | 1.25 | 1.5 |

**Type (W9).** A length error × g scales R and X together.
- The downstream / off-downstream sign split is unchanged at every bus.
- Max |k| relative to E-R(1.5) is 0.494 (semiurb4) and 0.489 (urban6) at g = 1.25, and
  0.987 and 0.978 at g = 1.5.
- The resistance-only predictions are 0.5 and 1.0, so the deviation is −1.2 % to −2.2 %.
- **The contrast does not distinguish a wrong length from a wrong conductor resistance.**

## 8. Diurnal systematic error (A*)

A diurnal bias of amplitude A is added to each meter's measured leg:
- shape: a square wave, +A on daylight steps and 0 at night (primary);
- sign: random per meter;
- noise: `realistic`-type.

**Registered records.**
- **A*_fa is "≤ 0.003 σ", a baseline artefact.** The false-alarm rate already exceeds 0.05 at
  A = 0 (0.065–0.070, which is the R7 excess), so no tolerance can be read off as registered.
- **A*_cov is "not reached"** for both shapes and both sign variants. Under an alarm-on-|k|
  rule, a large bias adds alarms rather than masking them, as the registration anticipated.

**Descriptive false-alarm curve** (truth = nominal, K = 2, square, pooled over the 25 rules).
It is read against its own A = 0 value:

| A / σ_tot | 0 | 0.003 | 0.006 | 0.01 | 0.02 | 0.03 | 0.06 | 0.1 |
|---|---|---|---|---|---|---|---|---|
| semiurb4, σ 0.01 | 0.065 | 0.072 | 0.090 | 0.133 | 0.309 | 0.574 | 0.992 | 1.0 |
| urban6, σ 0.01 | 0.068 | 0.076 | 0.090 | 0.136 | 0.320 | 0.600 | 0.995 | 1.0 |
| semiurb4, σ 0.005 | 0.069 | 0.073 | 0.091 | 0.130 | 0.312 | 0.582 | 0.992 | 1.0 |

- The curve depends on A/σ_tot, not on A, because the threshold scales with σ.
- A diurnal systematic error of **0.01 σ_tot** doubles the false-alarm rate: 1e-4 p.u. at
  σ = 0.01, or 5e-5 p.u. at σ = 0.005.
- The pre-stated HYPOTHESIS placed the limit at ≈ 0.035 σ (the band-C boundary). Read as the
  level at which most configurations alarm, the curve crosses 0.5 near 0.026–0.027 σ. Read as
  doubling the baseline, it is 3–4 times lower.
- The sinusoidal shape gives the same pattern, about 1.5–2 times later in A: the rate is 0.095–0.099
  at 0.01 σ and 0.165–0.172 at 0.02 σ. Its day-mean is smaller than the square wave's.
- No evidence in this repository bounds real diurnal meter or model errors at the 1e-4 p.u.
  level. Whether any deployment meets this tolerance is **NOT CHECKED**.

## 9. Reproduction and integrity

- **Gate (s. 2):** E = 1.19e-7 p.u., E_C ≈ 1.4e-10 in both networks. Physics, day sets and
  storage are structurally identical to `stress.stress_network(code, "line_local")`.
- **W1:** at the registered cables, the sweep's per-bus m, night and k equal Q1's committed
  arrays to at most 1.2e-8 p.u. R1, R3s and R4 give the same verdicts on both array sets.
- **Control 3:** with day/night labels permuted within days, the largest |mean k| is 7.3e-5
  (semiurb4) and 3.5e-5 (urban6), and at most 5.1e-5 in the held-out networks. Real contrasts
  reach 1–2e-3, and the threshold is about 3.6e-4, so no artefact of the day/night split is
  visible.
- **Integrity:** Stage 0 passed before, and Stage 4 after, Stages 1–3:
  - frozen Phase 8 outputs and the 27 `freeze.json` code hashes;
  - the Q1 committed results and the frozen placements;
  - the registration commit.
  The code was frozen at the hashes above from the start of execution, and no file under
  `src/`, `outputs/` or `docs/` changed during execution (Stages 0–4). This document was
  written afterwards.
- **Checks that need locally generated or retained research data.** The public repository
  holds the registration, the code, the unit tests, the gate record and this document. The
  inputs these checks need are not part of it:

  | Check | Needs, besides the tracked code and the SimBench package |
  |---|---|
  | Unit tests in `analysis/phase9/tests` | Nothing for all but two. The two Stage 0/Stage 4 integration tests need the frozen cache in the next row. They are **skipped** when all of it is absent, as in a fresh clone, so the clone gives 232 passed and 2 skipped. A partial or altered cache runs them, and they fail. The same Stage 0/4 logic also runs without the cache, on a self-contained temporary fixture. |
  | Stage 0 and Stage 4 integrity | The git-ignored frozen outputs `outputs/robust_study/evaluation_results.json` and `outputs/robust_study/freeze.json` (Phase 8), and `outputs/noise_study/development_results.json` (the Phase 6 placements) |
  | Stage 1 | Those placements |
  | Reproduction gate, sweep (Stage 2), W5 and control 3 | The Phase 8 physics caches `outputs/robust_study/fullstate_cache` (`line_local`) and `outputs/sense_study/fullstate_cache` (`nominal`) |
  | Stage 3 and re-checking the cited hashes of the held artefacts | The four SimBench-derived data groups the owner holds locally pending a licensing decision: `results/phase9_inputs.json`, `results/phase9_results.json`, `results/stage3_parts/` and `sweep/` (see Status) |

  None of these checks is weakened when the data are absent. Stage 0/4 still stop on any
  missing or mismatching file, and Stages 1–3 still refuse without the committed
  registration.

  No Phase 9 check reads the Phase 4 cache `outputs/dual_study/physics_cache`. W1 compares
  against Q1's committed results. Only re-running the Q1 addendum script itself
  (`q1_voltage_residual.py`) needs that cache, in addition to the two caches above.
- **Environment traces.** The frozen results file and the 18 Stage 3 part files record the
  absolute local path of the Stage 1 inputs file. The gate and sweep sidecars record worker
  process IDs. These are build-environment provenance and contain no credential. They are not
  edited, because the outputs are frozen.

## 10. Pre-stated hypotheses against observations

| Hypothesis (registration s. 9) | Observation | Status |
|---|---|---|
| R1/R2 can fail only at cables whose flow does not reverse (little downstream PV) | Both failures are at cables with 0 and 0.031 MVA of downstream PV | Holds |
| W8: band C survives down to f = 1.1 at σ = 0.01, K = 2 | semiurb4 f* = 1.1; urban6 f* = 1.25 | **Contradicted in urban6** |
| W9: sign split unchanged | Unchanged at every bus | Holds |
| W9: \|k\| ratio deviates from the R-only prediction by more than 10 % | Deviation 1.2–2.2 % | **Contradicted** |
| A*_fa ≈ 3.5e-4 p.u. ≈ 0.035 σ | Not estimable as registered (baseline above α); the descriptive curve crosses 0.5 near 0.026–0.027 σ | Not testable as registered |

## 11. Reviews and execution record

**Reviews** (GridPulse QA, sandboxed; AI-assisted; not external peer review).

- **AKK-28, the code, before any result existed:** PASS WITH LIMITATIONS, with four minor and
  three documentation findings:
  - constants not pinned to literals;
  - `merge` not re-checking the registration commit;
  - W1 rules evaluated on the sweep arrays only;
  - wording.
  All seven were corrected in AKK-29/AKK-30 and verified by the board. No statistic, threshold,
  seed or replicate count changed.
- **AKK-36, focused re-review of the corrections and the results:** PASS WITH LIMITATIONS.
  - Six spot-checks match exactly.
  - Every rule verdict follows from the numbers printed beside it.
  - No claim in the results file exceeds the registration.
  - Its findings were reader-facing, and this document addresses them:
    - the R7 link to coverage (s. 4);
    - the non-reversal restriction (s. 5);
    - the R5 extrapolation prohibition (s. 6);
    - the caveats (s. 12);
    - the equivalence of the parts run, below.
- **AKK-37, final review of this document and the publication set:** READY AFTER LISTED
  DOCUMENTATION CORRECTIONS.
  - About 160 numbers were checked against the frozen JSON. Every table, rule verdict and
    cited hash is exact.
  - Five prose mismatches and seven documentation gaps were found. All were corrected here
    after the board confirmed each against the sources: the precision of the sinusoid,
    "triples" and W9 figures, σ scoping of control 4, the "simulated" qualifier, post-hoc
    tagging, held-out wording, the outputs list and the environment traces.
  - It found the data licensing and attribution of the SimBench-derived artefacts undecided (see
    Status). That is an owner decision. The owner has held those artefacts locally, untracked.
- **AKK-38, focused check of the cache-absent test guard (s. 9):** PASS WITH LIMITATIONS.
  - The skip set equals every git-ignored file Stage 0 reads, and a partial or corrupted cache
    runs the two integration tests and fails them.
  - The two original tests' assertions are intact.
  - `phase9_analysis.py` is byte-identical at its frozen hash.
  - The fixture tests exercise the real Stage 0 code without leaking state.
  - The clean-export run was performed by the board; the reviewer's sandbox could not
    reproduce it.

**Execution deviations, disclosed.**

- **Parallelism:** the sandbox refuses a process pool, so all 99 runs used the registered
  one-worker fallback.
- **Stage 3 in parts:** Stage 3 ran as 18 parts plus a merge, to fit the agent's 9-minute
  command limit.
  - Every part shares one Stage 1 inputs hash and one physics key.
  - Bit-identity with the monolithic Stage 3 is unit-tested for every control (control 3 is
    stubbed there).
  - `stage3-benchmark` and `controls-selftest` pass on synthetic data.
- **Turn limits:** three implementation runs (AKK-26, AKK-29, AKK-30) hit their turn limits,
  and their partial work was kept. AKK-27 and AKK-30 were the narrowed retries of AKK-26 and
  AKK-29. Because AKK-30 also hit its limit, the board ran the two remaining synthetic
  self-checks.
- **Held-out data seen before the commit:** on 2026-10-23, before the registration commit, the
  board loaded the four held-out networks' line tables to check line counts, `parallel`,
  `in_service` and switch counts for the registration's s. 3 structural invariants. No downstream set, residual or
  voltage array of those networks was computed before the commit. The AKK-19 design had read
  their line and feeder counts from the frozen Phase 8 facts.
- **Interpretation decisions:** the implementation's readings of the registration text are
  recorded in the results file (`readings`), and the registration's own drafting decisions in
  its s. 16.

## 12. Caveats carried in every claim (registration s. 15)

- **Physics:** constant-power injections and no voltage-dependent loads. Balanced three-phase;
  no Q(U)/P(U); one error at a time; no cap. SimBench benchmark networks only.
- **Data:** all six networks are examined data. The held-out networks' `line_local` margins
  and violation counts were read in Phase 8.
- **Noise:** the simulated noise is Gaussian and i.i.d. per reading, with whole-day missingness.
  No other measurement error is modelled except the diurnal arm of s. 8.
- **Detection rates** are upper bounds for this error class: noise-free Δ, no state-estimation
  error, no cap.
- **Novelty is narrow.** Residual-pattern detection of structural errors is prior art (Castin
  et al. 2026; Vanin & Van Hertem 2022), as is the near-full-metering caveat (Waeresch et al.
  2017; `docs/phase6_literature.md:79-84,153-158`). Phase 9's contributions are:
  - the static-bias-cancelling day–night contrast at sparse, pre-committed meters;
  - its coverage-versus-placement curve;
  - the diurnal tolerance;
  - a population statement over 89 benchmark cables.

## 13. What is known, what was built, what was found

| Category | Content |
|---|---|
| Existing knowledge | Structural errors show as residual patterns over time (Castin et al. 2026; Vanin & Van Hertem 2022). Residual tests needed near-full metering in an LV field test (Waeresch et al. 2017). Parameter observability (Zhu & Abur; Korres). AMI model mismatch (Talkington 2022; Yusuf 2022) |
| Engineering implementation | A level-0 power-flow engine reproducing the frozen `line_local` physics to one float32 step. A resumable, key-verified sweep over every candidate cable. Zero-flow per-day-mean noise simulation with registered seeds. A held-out test path from existing caches |
| Experimental findings (simulation, exploratory, this benchmark) | Coverage is about 5 % at σ = 0.01 and K = 2, against a 22–33 % topological ceiling, with no off-downstream detections. Night-sign localisation holds for reversing cables only. The magnitude predictor does not transfer (R5). The registered floor is 5–7.5 % optimistic in spread (R7). A diurnal error of 0.01 σ doubles false alarms. The signal is linear in the error and blind to length versus resistance |
| Possible contribution | A pre-registered, population-level account of when a bias-cancelling voltage contrast at pre-committed sparse meters can and cannot screen a single-cable asset-record error, with its diurnal tolerance. **No new method** |
| Unverified hypotheses | The R7 excess comes from the median-based floor. R3 fails because of load-driven contrasts at cables with no downstream PV. Real diurnal meter or model errors exceed 1e-4 p.u. Any of this transfers to unbalanced or real feeders |

## 14. Evidence status

| Status | Items |
|---|---|
| IMPLEMENTED | The level-0 sweep engine and gate; the analysis Stages 0–4; controls 1–5 and the A* sweep; Stage 3 in parts |
| VERIFIED | Gate reproduction (1 float32 step). W1 agreement with Q1 (≤ 1.2e-8). W2 hit counts. 234 unit tests. Registered constants pinned to literals. Stage 0/4 integrity. 0 failed flows. Independent reviews (s. 11) |
| EXPERIMENTALLY SUPPORTED (this benchmark) | The coverage table (s. 3); P(C \| no meter below) = 0; R1/R2 at σ = 0.01; R4; W8 linearity; W9 type-blindness; the diurnal false-alarm curve |
| NOT SUPPORTED | R5 (held-out magnitude); R7 (registered false-alarm floor); R3 (per-cable shape, ≥ 0.9); R1/R2 at σ = 0.005 outside reversing cables; the W8 HYPOTHESIS in urban6; the W9 HYPOTHESIS of a > 10 % type effect |
| EXPLORATORY | Everything, as a study on examined data. The post-hoc threshold check (s. 4) |
| INCONCLUSIVE | A*_fa as registered (baseline above α); A*_cov (not reached) |
| HYPOTHESIZED | The cause of the R7 excess; the cause of R3's shortfall; real-world diurnal error magnitudes |
| NOT IMPLEMENTED | Phase imbalance; voltage-dependent loads; inverter Q(U)/P(U); errors at several locations at once; wrong-topology errors; state-estimation error; real networks |
