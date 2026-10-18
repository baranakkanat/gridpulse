# Phase 7 post-evaluation reviews (archived)

Final reports of the independent reviews run after the single Phase 7 evaluation, and
of the privacy review and the final evidence gate. They are archived verbatim, except
that local absolute paths are shortened. Each finding was checked against the outputs
before it was applied; what was changed is listed in `docs/phase7_results.md` s. 11.
The reports describe the documents as they were when each review ran.

## Review A + B: power-system physics and measurement

**Phase 7 post-evaluation review (A: physics, B: measurement)**

All the reported totals I recomputed match the outputs, with one exception (A7). The units are right: `MARGIN_SCALE` is 0.1 p.u. and 100 %. The safety margins are 0.04 for the rural networks and 0.02 for the others. The observability and busbar-bias sums also check out (17 = 1 tap + 16 MV).

##### Review A: power-system physics

**A1. Major. s. 3 "By truth" (tap and MV): the reason given for over-protection is wrong.**
- Evidence, tap + MV totals: C1 885.2, C1s0 701.6, oracle 489.9 MWh.
  - The safety margin accounts for 184 MWh, 46 % of the excess over the oracle.
  - For rural2 MV, the margin is 41 of the 57 MWh excess.
- The rest is mostly 28-day worst-case replay combined with the 11-step cap grid.
- The 1/V over-correction is at most about 0.0013 p.u. (protocol development check 0.0295–0.031 against v̂ 0.0308), about a third of the rural margin. No run isolates it.
- Correction: name the margin, applied to voltage, as the main cause, then replay. Call 1/V secondary and unquantified.

**A2. Major. s. 1 item 2: the margin is given in the wrong physical unit for H1(b).**
- Under the correct model every violation is thermal: 1716 substation-observable plus 370 unmeasured-line, and no remote overvoltage.
- A busbar bias of ±0.005 leaves correct-model curtailment unchanged in 4 of 5 networks. Only rural3 at +0.005 moves, from 22.8 to 29.1 MWh.
- So the H1(b) cost comes from a 2–4 percentage-point *loading* margin, costing 17.5 MWh.
- The same normalised s becomes 0.002–0.004 p.u. on *voltage* under tap and MV, and costs 184 MWh there.
- s was tuned where loading binds and then applied to voltage without a test.
- Correction: state both meanings of s and add this caveat to s. 9.

**A3. Major. s. 1, s. 9 "without remote meters": the dependence on exact injections is hidden.**
- The residual is the reading minus the nominal model at the exact realised customer injections.
- Any systematic injection error passes one-for-one into ρ. A 5 % error equals the label threshold; the cos φ signal is 8–20 %.
- The binary policies' *feedback signal* does not have this dependence. C1lag tests only delay.
- Correction: write "substation telemetry plus complete, exact 15-minute customer metering", and list injection error as untested.

**A4. Minor. s. 1 item 4, s. 3, s. 8: the semiurb4 cable explanation.**
- C1 and C1s0 both curtail 22.2 MWh, against the oracle's 8.8. Replay alone costs only 7.1 against 6.7 under the correct model.
- So C1 protects the cable by over-correcting: ρ_line 0.195 against roughly 5–7 % expected for a cable carrying mainly PV export at cos φ 0.95. The median over daylight includes hours where load offsets the PV's P but not its Q.
- "No cable is loaded beyond the head ratio" is asserted; no output shows it.
- B2 and B3 sit at the τ floor (mean −0.10). Their 157 violations are worse than open-loop R0 at 111 and Rdev at 102.
- Correction: say C1 over-corrects here, and compare it with Rdev as well as B3.

**A5. Minor. s. 4: "MV voltage varying within the day" is listed as a local error, but it is not one.**
- It is common-mode and the busbar sees it every quarter-hour.
- The limitation is temporal: a daylight mean, a 7-day median, used the next day.
- Midday MV rises line up with the PV peak, and an excursion of 0.01 p.u. exceeds s.
- Constant MV within the day is the most favourable case for C1 (this assumption is stated). Constant-power loads would only make the tested positive offsets more conservative.

**A6. Note. Checks that hold.**
- Relaxing voltage planning by the negative v̂ under cos φ is safe in this direction: the reactive-power drop at remote buses is at least the busbar's, and the daylight mean is below the peak.
- ρ of −0.023 to −0.029 under tap and MV relaxes loading. That is valid only for constant-power injections.
- `first_safe` handles non-monotonic responses. Reverse flow is magnitude-symmetric.
- Energy accounting ignores the inverter apparent-power limit at fixed cos φ (S = 1.053 S_n at full output).

**A7. Minor. s. 1 item 2: "116" should be 120.** The development R0 correct-model total is 120, which s. 9 already uses.

##### Review B: measurement

**B1. Minor. s. 5 busbar bias: class 0.2 tolerance is really the safety margin.**
- In the s = 0.02 networks, C1 with a −0.002 bias equals C1s0 cell for cell under tap and MV (urban6 MV 11 / 118.6 both; semiurb4 MV 3 / 19.0 both).
- At −0.005 the rural margin of 0.004 is exceeded, giving rural2 tap 33 and MV 14 violations.
- Class limits are maximum permissible errors, not typical errors. A 0.4 kV busbar is normally measured directly (IEC 61557-12 / 61000-4-30), not through a voltage transformer (IEC 61869-3).
- At ±0.005 the bias equals the label threshold, so the label is a coin flip: it fires on 471 of 915 correct-model days.
- Correction: "tolerated bias ≈ s"; "a class 0.5 device at its low-reading limit".

**B2. Minor. s. 5: "cannot be told apart" is overstated.**
- A true offset leaves a current signature here, ρ ≈ −Δv/V (ρ_trafo −0.028 under MV, about 0 under tap). A busbar bias does not.
- It cannot be told apart *in practice* when |b| ≤ 0.005: the signature is at most about 0.5 %, against 0.5–1 % current-transformer error and unknown load voltage dependence. Rephrase to say that.
- "Two local states can give the same residuals" holds to first order (differences only through losses) but is not demonstrated.
- The best support in the data: C3x under cos φ with exact, unbiased meters gets INSUFFICIENT_INFORMATION_TO_IDENTIFY_BIAS on 106 days.

**B3. Minor. Label logic (s. 1 item 7, s. 5).**
- There is no outcome for a biased reference. With the busbar at −0.005, unbiased meters are labelled "meter bias suspected" on 278 days.
- The 732 / 732 split holds by construction: bias draws ignore the truth, and no truth contains a local error.
- m − v_bus already removes the common-mode error, so the split encodes a prior, not identifiability.

**B4. Minor. H3 and the meter results.**
- C3b in draw r equals C1 in replication r in 4 of 5 draws. The 66.0–66.9 spread is busbar noise, and H3 compares against C1/0 rather than pairing by replication.
- H3 is tested only where voltage does not bind. Under mismatch, accepted positive biases raise v̂ through `max`: C3b/0 curtails 1080.7 against C1's 1027.0 MWh.
- The cost rising with meter count is noise passing through `max`: C3x 1026.9 against C1x 1024.9.

**B5. Note. Coverage is computed correctly.**
- The daily-mean coverage expected under bias is about 0.35; the pooled result is 0.28.
- Values are identical across truths, so there are five independent values, not twenty.
- n is 20 midday readings; state it. The single-reading coverage is a marginal over meters; for one meter it is close to 0 or 1.
- The correct uncertainty for a mean is u = √(σ_b² + σ_r²/n).

**B6. Note.** "No bias is ever estimated or subtracted" is true of `_update`.

##### Verdicts

**A:** The tap, MV and cos φ corrections are physically sound and err on the safe side, and the reliability result stands. But the cost is misattributed (it is the margin, not 1/V), the margin's unit is wrong, and the dependence on exact injections is hidden.

**B:** The noise, bias and coverage computations are correct. The class 0.2 "robustness" is the safety margin; the label split and the claim about telling bias from a model error are stronger than the evidence.

## Review C: statistics and number fidelity

#### Review C (statistics and number fidelity): Phase 7 results draft

**Pre-registration fidelity.**
- **H1–H5 recomputed from `evaluation_results.json`:** all five reproduce.
  - H1(a): 1 < 513.
  - H1(b): 66.233 > 1.1 × 52.325 (ratio 1.266), so H1 is not met.
  - H1 also fails in all 5 noise replications (ratios 1.23–1.27).
  - H2, H3, H4 and H5 are met.
- **Timeline is clean.** Registration 21:29:34Z → development v1 21:31Z → code changes 21:41Z → amendment 7A 21:43:29Z → development re-run 21:45:37Z → freeze 21:45:59Z → evaluation 21:49:14Z → results draft 21:51:48Z.
- **Nothing changed after the evaluation.** The current hashes of the code, dependency pins, protocol and all outputs equal the frozen and logged hashes. The probe script predates registration.
- **Pre-freeze check passes**, but the log describes it inaccurately (note n1).
- **Claim rule 6** (busbar robustness) is applied correctly. **Claim rule 7** is applied in s. 3 only (finding M1).

##### Findings

**M1 (major). Claim rule 7A-7 is not applied in the summary sections.**
- *Location:* s. 1 items 1 and 3, s. 9 "Can be claimed", s. 10.
- *Evidence:* The rule applies here, because C1s0 does not beat B3 on mismatch MWh (835 > 728). That means "fewer violations than two exact meters" must always come with the mismatch curtailment. Section 3 does this. Sections 1 and 10 give "1 vs 513" and "15 vs 9 cells" without it.
- *Correction:* Add "at 1027 vs 728 mismatch MWh (+41 %)" wherever the B3 comparison appears.

**M2 (major). The cost attribution is over-generalised, and 7A-7's "clean cost" is only half reported.**
- *Location:* s. 9 ("at a curtailment cost that here comes from the safety margin"), s. 10 ("The cost is due to a spring-tuned margin").
- *Evidence:*
  - Under the correct model the attribution holds, but trivially. There v̂ ≈ 0 and ρ ≤ 0.003, so C1 ≈ Rdev by construction (66.2 vs 66.0). R0 and C1s0 are both 48.7.
  - Under model errors it does not hold. The margin accounts for only 192 MWh (1027 vs C1s0 835). Even without a margin, C1s0 curtails 107 MWh more than B3.
  - 7A-7's clean cost of the correction under mismatch, C1 vs Rdev, is +829 MWh (1027 vs 198). It is never reported.
- *Correction:* Limit the attribution to the correct-model cost (H1(b)), and report the C1 − Rdev cost under mismatch.

**m1 (minor). Wrong development number in s. 1 item 2.**
- *Evidence:* The draft says plain replay leaves "116" correct-model violations in development. Development R0 is 120; 116 is C1s0. Section 9 correctly says 120.
- *Correction:* Change 116 to 120.

**m2 (minor). The 28-day robustness claim in s. 3 is not accurate.**
- *Evidence:*
  - For the quoted rural3 tap cell, the violation interval gets *narrower* at 28 days: [−0.514, −0.235] against [−0.547, −0.240] at 7 days.
  - 6 of the 20 C1 − B3 tap/MV intervals narrow at 28 days.
  - semiurb5 tap violations lose zero-exclusion (upper bound −0.005 → +0.000).
  - rural2 tap: both intervals include 0, and the MWh mean is negative (C1 curtails *less* than B3 there).
  - Only the most favourable cell is quoted. With 183 days, 28-day blocks give only about 6.5 blocks, so the intervals are unstable.
- *Correction:* Report the counts. Violation intervals exclude 0 in 8 of 10 cells at 7 days and 7 of 10 at 28 days. MWh intervals are above 0 in 9 of 10 cells. Drop "widen".

**m3 (minor). "Large and robust" (s. 1 item 3) overstates.**
- *Evidence:* The replications vary only noise. All tested errors are in the favourable direction. A busbar bias of −0.005 drops C1 to 11 cells and 260 violations.
- *Correction:* "Large and consistent across 15 cells and 5 noise draws."

**m4 (minor). "Class 0.2 keeps reliability here" (s. 5) is a softened form of the claim rule 6 forbids.**
- *Evidence:* At −0.002, violations rise from 1 to 17. At +0.002, mismatch curtailment rises 12 %.
- *Correction:* State those numbers and that the robustness claim is not made.

**m5 (minor). The label rates under busbar bias are misdescribed.**
- *Location:* s. 1 item 6 and s. 6.
- *Evidence:* The draft says "up to 60 % … in some networks". The actual rates are 41–61 % in *all five* networks at −0.005, and 39–59 % at +0.005. Mean v̂ is exactly ±0.0050, which equals the 0.005 label threshold, so these rates sit on a knife edge.
- *Correction:* Give the per-network range and say the bias equals the threshold.

**m6 (minor). The meter-bias label counts come from one draw only.**
- *Location:* s. 1 item 7 and s. 5.
- *Evidence:* 732/915 is draw 0. Draws 1–4 give 889, 913, 915 and 915. In draw 0, semiurb5 had 0 flagged days, so the bias went unflagged in that network.
- *Correction:* Say "draw 0" and give the range 732–915.

**m7 (minor). The s. 3 trade-offs are incomplete.**
- *Evidence:*
  - The B3 trade-off is missing: +41 % (+299 MWh) for 512 fewer violations.
  - C1s0's evaluation dominance over B4 and B5 omits that it met 0 of 15 cells, with 429 violations, in development.
  - Under the correct model, C1s0 is the same as R0 (16, 48.7). That dominance comes from replay without a margin, not from the correction.
- *Correction:* Add these three points.

**m8 (minor). "Over-protects slightly" is not supported (s. 3, by truth).**
- *Evidence:* C1 curtails 1.1–2.8× the oracle. The 1/V mechanism was not isolated. The margin explains part of the gap: C1s0 is at 1.47× the oracle over all mismatch cells, C1 at 1.80×.
- *Correction:* Drop "slightly" and state that the gap is not decomposed.

**m9 (minor). The seasonal cause is stated as fact.**
- *Location:* s. 1 item 2 and s. 9.
- *Evidence:* The numbers are correct: R0 has 120 correct-model violations in development and 16 in evaluation. But the mechanism was not tested, and the stages differ in length (147 vs 183 days; per network-day 0.16 vs 0.017). The draft also omits that H1 *passed* in development (C1 91.0 vs B2 86.7 MWh, 1.05×), which is the most direct supporting evidence.
- *Correction:* Write "consistent with" and report the development H1 result.

**Notes.**
- **n1:** The registration log says the pre-freeze differences were "the 24 C3full runs". In fact 46 of 792 differ: 24 C3full plus 22 C3b/C3nb runs where only the labels differ. These are allowed under 7A, so the check still passes, but the log line should be corrected.
- **n2:** "Within about 0.001 p.u." (s. 1 item 4) cannot be checked: the true offsets are not in the JSON. semiurb4/5 tap v̂ of 0.0263 against "about 0.028" is about 0.0017 off.
- **n3:** C1lag "changed nothing" should be "almost nothing" (1027.07 vs 1027.02 MWh).
- **n4:** There is no significance language. The H1 failure is prominent enough. "No policy is best" holds for the attainable policies. In s. 7, add "(noise only)" after "5 of 5 replications".

##### Numbers checked

| Location | Document | Source | Status |
|---|---|---|---|
| s. 3 table, all 17 rows × 6 columns | — | JSON totals | 102/102 OK |
| H1(a) / H1(b) | 1/513; 66.2/52.3, 1.27× | 1/513; 66.233/52.325, 1.266 | OK |
| Rdev vs C1, correct model | 66.0, +0.2 | 66.030, +0.204 | OK |
| Development plain replay, correct-model violations | 116 | R0 120 (116 is C1s0) | **Mismatch** |
| Development C1 vs B3; cells | 166/1495; 9/0 | 166/1495; 9/0 | OK |
| Severity / long runs: C1, B3, B7, B2 | 0.0/0, 10.0/24, 1.7/5, 1055/697 | 0.01/0, 9.96/24, 1.68/5, 1054.7/697 | OK |
| Unneeded MWh: C1/Rdev, binary, B4 | 5.7, 2.4–3.2, 28.7 | 5.73/5.69, 2.39–3.22, 28.70 | OK |
| C1 vs B7 | +26 %, −157 | +25.8 %, −157 | OK |
| C1s0 vs B7 | −118, +19 MWh | −118, +19.1 | OK |
| C1 vs B2, correct model | +14 MWh, −47 | +13.9, −47 | OK |
| rural3 tap, paired C1 − B3 | −0.38 [−0.55, −0.24]; +0.47 [+0.38, +0.57] | −0.377 [−0.547, −0.240]; +0.474 [+0.377, +0.566] | OK |
| 28-day intervals "widen, same sign" | — | narrower for violations; semiurb5 tap loses zero-exclusion | **Mismatch** |
| v̂ under tap/MV; ρ under cos φ | +0.026 to +0.031; +0.08 to +0.20 | 0.0263–0.0308; 0.075–0.195 | OK |
| Oracle ratios; rural2 MV | 1.1–2.8×; 96.0/38.7 | 1.13–2.84; 95.97/38.67 | OK |
| B3 failures in rural3 | 62–69 | 62, 69 | OK |
| PV-Q violations: binary; semiurb4 | 5–11; 157 | 5–11; 157 | OK |
| PV-Q MWh: C1, binary, oracle | 22–38, 7–33, 9–25 | 22.2–38.1, 6.9–33.0, 8.8–25.4 | OK |
| PV-Q v̂ | −0.004 to −0.007 | −0.0043 to −0.0074 | OK |
| Meters 0/1/2/4/all: MWh | 1027/1043/1054/1073/1133 | 1027.0/1042.7/1053.7/1072.5/1132.7 | OK |
| s. 4 observability (12 cells) | as drafted | 5-network sums | OK |
| s. 5 busbar-bias table (25 cells) | as drafted | sensitivity rows | OK |
| C3 at −0.005 | 88, 12 cells | 88, 12 | OK |
| Meter bias: checked / unchecked MWh | 66.0–66.9 / 82.8–145.6 | 65.98–66.88 / 82.75–145.63 | OK |
| Checked within 1 % of C1 | <1 % | max 0.98 % | OK |
| Coverage | 0.954–0.955 / 0.945–0.961 / 0.88–1.00 / 0.10–0.40 | 0.954–0.956 / 0.945–0.961 / 0.877–1.000 / 0.101–0.400 | OK |
| s. 6 labels | 915, 915, 890/25 | same | OK |
| C3b labels | 732/915 | draw 0 only (range 732–915) | OK, needs scope |
| H5 rates | 100 %/0 % | min 1.0 / max 0.0 | OK |
| C1lag: evaluation; development | unchanged; 166→220 | 1/1027.07; 220 | OK |
| R0 correct-model: evaluation / development | 16/120 | 16/120 | OK |

**Verdict.** The registered verdicts and nearly all numbers are faithful: H1 is correctly reported as not met, the timeline is clean, and there are 2 number mismatches. Before s. 11 is closed, fix M1 and M2 (claim rule 7 missing from the summary sections; the margin-only cost attribution applied to model errors) and the 28-day interval statement.

## Review D + E: leakage, software and reproducibility

**Phase 7 post-evaluation review: leakage (D) and engineering/reproducibility (E)**

I found no leakage and no defect that changes a reported result. There is one major provenance problem: the working tree no longer matches the freeze, and the registration log and results doc don't say so.

Files were edited while I was reviewing. My first `git diff` had no `trace` parameter. Then `sensing.py` changed at 21:53:11Z, `__main__.py` at 21:56:43Z, and new `src/gridpulse/demonstrator.py` and `tests/test_demonstrator.py` appeared at 21:58Z. The evaluation had completed at 21:49:14Z.

#### Integrity

- **`runguard.verify`:** returns `[]` for both `evaluation` and `development`.
- **Evaluation ran on frozen code:** the evaluation manifest's `code_sha256` equals `freeze.json`, including `sensing.py` 56f08e27….
- **Registration-log hashes:** the freeze, development-output and evaluation-output blocks all match. The two code blocks differ only in files changed since (the first block predates amendment 7A; the second differs in `sensing.py`).
- **Pre-freeze check:** 746 of 792 shared run summaries are identical. The differences are 24 C3full runs, plus 4 C3b and 18 C3nb runs that differ only in labels. Paired comparisons, observability, coverage and `safety_margin` are unchanged. This matches 7A items 1 and 3.

#### Findings

1. **Major (provenance), no result impact: `require_freeze` now fails.**
   - It names `src/gridpulse/__main__.py`, `demonstrator.py` and `sensing.py`.
   - In `sensing.py`, removing `trace` at :539 and the two lines at :586–587 restores the frozen hash 56f08e27… exactly. So the only post-freeze change there is an opt-in `trace` hook.
   - The current tree reproduces the stored outputs:
     - Phase 7 semiurb4/nominal: 0 of 1738 values differ.
     - Phase 7 semiurb4/tap_raise_lv: 0 of 1739 differ.
     - Phase 6 semiurb4/nominal: 607 of 607 run summaries and all 432 paired values identical.
   - Neither the registration log nor results §11 discloses the change. Record the new hashes and this replay evidence, or keep demonstrator hooks out of frozen modules.
2. **Minor, `__main__.py:862`, no result impact:** the run metadata records `noise_study.CONDITIONS`, so the four `busbar_bias_*` conditions that `plan` uses are missing from `evaluation_run_metadata.json`. Use `margin_study.CONDITIONS`.
3. **Minor, registration log line 3:** "792 identical except the 24 C3full runs" leaves out the 22 C3b/C3nb label-only differences. Only the wording needs fixing.
4. **Minor (latent), `margins.py:272–283` with `margin_study.py:275`:** `NO_VERIFIED_FEASIBLE_ACTION` takes precedence, so a day that has both conditions is not counted in the H5 flag rate. C1 had 0 no-feasible days in the evaluation, so H5 is unaffected.
5. **Minor (latent), `sensing.py:229–230`:** `bias_v_substation` is applied only in `_measure_identified`. The legacy `measure(noise=None)` path silently drops it, as it already drops `sigma_bias_remote`. Every bias run uses a NoiseBank, so nothing changed; raising a `ValueError` there would be safer.
6. **Minor, `margins.py:147–151` and :173:** for C3full, `rho_line` includes non-feeder-head lines, so its "substation residuals only" label is not strictly that. No hypothesis uses C3full labels.
7. **Note, `margins.py:129`:** `corrected()` works in float64 while `plan_norm` is float32, so they are only `allclose`, not bitwise equal. `first_safe` levels are still identical on every decision day for semiurb4 and rural2 at margins 0, 0.02 and 0.04, so R0 equivalence holds.
8. **Note, `margins.py:224`:** `max(v, m)` raises `v`, which makes the undervoltage column less cautious. Undervoltage isn't binding in these PV-export cases.
9. **Note, `margin_study.py:99` and :277–279:** `records[0]` and `min()` fail on empty input. A `--networks` subset with no new network would raise after `runguard.begin` and leave the manifest at "running".

#### Leakage checks (all pass)

- **`build_contexts`:** `nominal_states` is loaded once from the nominal model (`sensing.py:869`) and given to every truth (:880).
- **Corrector inputs:** readings, the applied caps, daylight, and the nominal model at day d's injections. `state()` is captured before `observe(day)`, and `replay` uses days d−28 to d−1 only.
- **Lag queue and meter delay:** the lag queue pops days ≤ d − `lag_days`. The meter delay is `remote_delay + lag`, consistent with the binary path's `pending.pop`.
- **`tuned_safety_margin`:** uses the nominal plan and development days only. Its evaluation value is identical across all four truths of each network (0.04 rural, 0.02 semiurb and urban).
- **`observability` and `coverage`:** evaluator-side only. `coverage` uses its own NoiseBank, and neither feeds a decision.
- **Injection timing:** C1lag ≈ C1 (1 vs 1 mismatch violations; 1027.1 vs 1027.0 MWh), so the same-day-injection assumption doesn't drive H1(a).
- **Development probe:** reads development days only.

#### Preservation and code quality

- With `corrector=None`, `bias_v_substation=0` and `trace=None`, the new code does nothing. `test_phase5_legacy_path_is_pinned` passes.
- `PLAN` has 45 rows with unique keys, and no name maps to two specifications.
- `sensitivity()` reads keys that exist (`labels`, `no_feasible_action_days`, `days`, `meets_beta`).
- `LOADING_LIMIT = 100` holds for every line and transformer in all six networks.

#### Missing tests (high value only)

- A guarded-dict test that raises if `plan_raw` or `nominal_states` is read for a future day. The current causality tests only perturb readings, so an off-by-one in the replay window would pass.
- An integration test (skipped if the caches are missing) that `plan_raw` normalises to `ctx.plan_norm` and R0 levels equal plain replay. The toy R0 test builds its plan from `plan_norm`, so a wrong loader would pass.
- The lag and meter delay combined.
- Label precedence when a day has both no feasible action and a model error.

#### Dependencies

`pyproject.toml` and `uv.lock` are unchanged from HEAD and match the freeze hashes. No new third-party imports.

#### Tool results

- **pytest:** 233 passed at the start; 237 passed on the current tree, including the 4 new demonstrator tests.
- **`ruff check`:** all checks passed.
- **`ruff format --check`:** 57 files already formatted.

#### Verdicts

**D (leakage):** Pass. Decisions see only readings, applied caps and the nominal model's past or same-day values; ground truth is used only for scoring and evaluator diagnostics.

**E (engineering and reproducibility):** Code is sound and the evaluation reproduces exactly on the tasks checked. Not clean until the post-evaluation edits and the missing bias conditions are recorded, because `require_freeze` fails and neither is disclosed.

Key paths:
- `src/gridpulse/sensing.py`
- `src/gridpulse/__main__.py`
- `src/gridpulse/margins.py`
- `src/gridpulse/margin_study.py`
- `docs/provenance/phase7/registration_log.txt`

## Review F: novelty, prior art and claims

I found no fabricated or misattributed references and no licence or data-redistribution problems. The main gaps are qualifiers missing from s. 1, s. 9 and s. 10. Everything below was checked read-only. Reference metadata comes from Crossref and arXiv; Ortmann's text was read in the arXiv PDF.

#### 1. Novelty table

| Finding | Class | Closest verified prior work | Note |
|---|---|---|---|
| Substation residuals carry common-mode information that binary alarms discard | (b) | Procopiou & Ochoa 2017, TPWRS 32(2), doi:10.1109/TPWRS.2016.2591063 (feeder-end voltages from substation data only, about as good as remote monitoring); Procopiou & Ochoa 2019, PowerTech, doi:10.1109/PTC.2019.8811004 (substation data for congestion limits; abstract seen only via a search snippet) | A thresholded count is a function of the readings, so losing information is expected. "Binary alarms" means the project's own Phase 5/6 baseline, not a field standard. |
| Substation-only offset correction gives near-full reliability under tap and MV errors | (b); the comparison alone may be (c) | Muske & Badgwell 2002; Pannocchia & Rawlings 2003; Procopiou & Ochoa 2017 | I also found no day-ahead PV-cap study comparing this against count feedback. It relies on **exact, complete per-customer injections the next day** (Phase 5 protocol l. 146), so "without remote meters" means without remote *voltage* meters. |
| H1 cost failure is due to a seasonally mis-tuned margin | (a), study-specific | Kuntz & Rawlings 2024 (back-offs); Dall'Anese et al. 2017 (conservative bounds) | Rdev ≈ C1 does show the cost belongs to the margin. The *seasonal* cause is post hoc and was not isolated. |
| Remote meters add little once the correction exists | (b) | Procopiou & Ochoa 2017; Pannocchia & Rawlings 2003 | This holds only for the tested common-mode or distributed errors. Local errors were not tested. |
| Busbar VT bias passes one-for-one into the correction | (a) | Pegoraro, Brady, Castello, Muscas, von Meier 2019, IEEE TIM 68(10):3871–3882, doi:10.1109/TIM.2019.2908703 (instrument-transformer systematic errors, distribution grid); JCGM 100 | This follows directly from how a residual estimator works. Only the violation counts are new. |
| Checked meter residuals detect but cannot attribute bias | (a) | Pegoraro et al. 2022 (attribution needs a model of the measurement chain); Peppanen, Reno, Broderick, Grijalva 2016, IEEE TSG 7(5):2497–2506, doi:10.1109/TSG.2016.2531994 (LV model calibration from AMI) | The label split happens by construction of the label definitions. |
| Averaging intervals fail under bias | (a) | JCGM 100:2008 s. 3.2 | Textbook result. |

#### 2. Reference spot-check (all 16 metadata records match)

| Ref | Existence, authors, venue | Attributed claim |
|---|---|---|
| Muske & Badgwell 2002 | OK | OK |
| Pannocchia & Rawlings 2003 | OK | Consistent with the paper as known; abstract not re-read |
| Kuntz & Rawlings, arXiv:2412.08104 | OK; a v2 is dated 2025-09-01 | OK: the abstract says "sufficiently small" mismatch and uses constraint backoffs |
| Procopiou & Ochoa 2017 | OK (a PESGM 2017 version also exists) | OK |
| Ortmann, Hauswirth, Caduff, Dörfler, Bolognani 2020 | OK | Persistent OPF violation and the suggestion of disturbance observers or model adaptation are both verified in the text. But SYSLAB is a "small yet realistic" laboratory grid at DTU Risø, not "a real feeder". |
| Pegoraro et al. 2022 | OK | OK: IEEE 14-bus system reproduced in three phases |
| Netto et al. 2021 | OK | OK: two meters, about 3.9 % maximum error |
| Xie 2026, engrXiv | OK, posted 2026-05-26 | Preprint flag correct |
| Chen, Hauswirth, Bassi, Gupta, Navarro-Espinosa, Jain, Dall'Anese, Short | Metadata OK | Claims not re-read |

**Gaps in `phase7_literature.md`:**
- Kumarawadu et al. 2025 *does* exist: Applied Energy 384:125469, doi:10.1016/j.apenergy.2025.125469. It can move out of the UNVERIFIED list as "metadata only".
- The dynamic-operating-envelope literature is missing, and day-ahead PV caps are operating envelopes. Examples: Petrou et al. 2021, TSG, doi:10.1109/TSG.2021.3081371; Bassi et al. 2023, ISGT-LA, doi:10.1109/ISGT-LA56058.2023.10328319 (metadata only).
- Pegoraro 2019 (distribution grids) should be added; it is closer than the 2022 transmission paper.
- The IEC class 0.2 / 0.5 VT figures have no reference. They match the IEC 60044-2 / 61869-3 ratio limits as quoted by secondary sources, but are not checked against the standard.

#### 3. Wording corrections

1. **s. 1 item 2.**
   - Replace "The cost comes from the safety margin, not from the correction" with "Post-hoc diagnosis: the correct-model cost is that of C1's registered safety margin, which is part of the method."
   - Replace "because PV is rising … mostly unnecessary" with "A plausible, untested explanation is seasonal (s. 10)."
   - Reconcile the replay-violation count: 116 here against 120 in s. 9.
2. **s. 1 item 3.** Replace "large and robust" with "large and consistent across noise replications. It is not robust to a −0.005 p.u. busbar bias (s. 5)."
3. **s. 1 item 4.**
   - "within about 0.001 p.u." is not supported by 0.026–0.031 against 0.028/0.030. Use "about 0.002", or give the pairs per truth.
   - Replace "Binary alarms threw away…" with "The Phase 5–6 count feedback discarded… (substation-based estimation itself is known: Procopiou & Ochoa 2017)."
4. **s. 1 item 5.** Prefix with "For the three constant, positive-direction truths tested".
5. **s. 1 item 6.**
   - Replace "main measurement dependency" with "largest measurement dependency tested. Per-customer injections were assumed exact."
   - After "IEC class 0.2 limit", add: "An LV busbar is usually measured directly, so the relevant figure is the accuracy of the whole measurement chain."
6. **s. 1 item 7.**
   - "within 1 %" should be "within 1.1 %" (66.9 / 66.2).
   - Replace "Meter bias is caught" with "Biased meters are mostly excluded."
   - Add: "The label split follows from the label definitions."
7. **s. 4.** Replace "No substation signal can attribute them…" with "Substation residuals alone are not expected to attribute them (argued; no local error was simulated)."
8. **s. 5 "Practical implication."** Replace with: "In this benchmark, −0.002 p.u. kept 15 of 15 cells and −0.005 kept 11. No guidance for field equipment follows."
9. **s. 9, second "Can be claimed" bullet.** Add:
   - "…under three constant, positive-direction errors, given exact next-day per-customer injections."
   - "Under model errors C1 still curtails 41 % more than B3, and 15 % more without the margin (C1s0)."
10. **s. 10.**
    - "Possible contribution" should read: "A benchmark comparison of this project's count feedback with a standard offset correction, and the busbar-bias dependence quantified. The common-mode/local split is argued, not tested."
    - Move "Bias labels separate…" to the Engineering row.
    - Add Pegoraro 2019, Peppanen 2016 and the operating-envelope literature to "Existing knowledge".
11. **Literature s. 2.** Replace "on a real feeder" with "on a real laboratory distribution grid (SYSLAB, DTU Risø)".

**Licence and data:** no document chooses a licence or implies redistributing third-party data. SimBench is only named, and the outputs are git-ignored.

**Failed H1:** it is stated first and plainly, in s. 1, s. 7 and s. 9. Only the reframing in s. 1 item 2 softens it (item 1 above).

#### 4. Verdict

The claims are mostly disciplined: the failure of H1 is stated plainly, the method is labelled not new, and the "cannot be claimed" list is right. All seven findings are established or known-but-rarely-quantified. Only the benchmark comparison is plausibly new, and s. 1, s. 9 and s. 10 need the qualifiers above, especially the reliance on exact per-customer injections and the post-hoc seasonal explanation.

Sources:
- [Procopiou & Ochoa 2017 (Manchester record)](https://research.manchester.ac.uk/en/publications/voltage-control-in-pv-rich-lv-networks-without-remote-monitoring)
- [Kuntz & Rawlings, arXiv:2412.08104](https://arxiv.org/abs/2412.08104)
- [Ortmann et al., arXiv:1910.03384](https://arxiv.org/abs/1910.03384v3)
- [Pegoraro et al. 2019 (UNICA repository)](https://iris.unica.it/handle/11584/263107)
- [Pegoraro et al. 2022 (UNICA repository)](https://iris.unica.it/handle/11584/334751)
- [Peppanen et al. 2016 (OSTI)](https://www.osti.gov/biblio/1259833)
- [Netto et al. 2021 (NJIT record)](https://researchwith.njit.edu/en/publications/on-the-use-of-smart-meter-data-to-estimate-the-voltage-magnitude-/)
- [KTH instrument transformer notes (VT classes)](https://www.kth.se/social/files/55f12ed5f2765409c53d3c14/2%20Instrument%20transformers.pdf)
- Crossref API records for all DOIs listed above.

## Privacy review of the KIB-TEK pilot concept (sections 4 and 6)

I read `docs/kibtek_pilot_concept.md` in full and edited nothing. The document makes no claims about TRNC law. I checked no TRNC law myself, so the suggested wording below stays neutral.

1. **High, s.6 l.124–127 (and s.4 l.79): overstates the protection.** "pseudonymised ... without names, addresses or meter identifiers" reads as close to anonymous. But the minimum tier also asks for connection points on the single-line diagram and for PV location and size, and those can lead to a specific house. The text never says that pseudonymisation is not anonymisation, or that load profiles reveal behaviour. Replace l.124–127 with:
   > - Consumption and generation series per connection point are personal data, also when pseudonymised. Pseudonymisation is not anonymisation: 15-minute profiles can reveal occupancy and daily routines, and on a small feeder a bus position or PV size can identify a household. Only the minimum would be considered: series summed per model bus, with consumption and generation separate only where the model needs it; no names, addresses, account or meter numbers; random bus labels not derived from any identifier, with any mapping kept only by the utility; and a period fixed in advance (a full year only if seasonal residuals must be checked).

2. **High, s.6: no legal basis or impact assessment.** Insert after l.121:
   > - Before any personal data is shared, the utility decides whether a legal basis exists under applicable data-protection law, as it determines that law, and completes a data-protection impact assessment or its equivalent. The utility sets the purpose and conditions in the written agreement.

3. **Medium, s.6 l.122–123: no processing location, access limits or rule for outputs.** Replace with:
   > - Utility data and anything derived from it stay outside the GridPulse repository and any public release. They are processed only by named persons on one encrypted, access-controlled computer, never on cloud storage, shared drives or online services, including AI assistants. No onward sharing and no attempt to re-identify anyone. Reported results are at transformer or feeder level, with no per-customer series. Whether and how GridPulse is published is still undecided.

   The AI-assistant clause matters here because this repository is worked on with one.

4. **Medium, s.6 l.131: data is deleted only "on request", and derived data is not covered.** Replace with:
   > - Data, and any series derived from them, are deleted or returned at the end of the agreed analysis, or earlier on request, with written confirmation. No connection to operational systems.

5. **Medium, s.4 l.76 and l.79: the tier table asks for more detail than s.6 allows.** Replace these rows:
   > | PV connections: model bus and installed power | PV-driven overvoltage and reverse flow |

   > | Metered consumption and PV generation for the same period, summed per model bus, with interval, completeness and delivery delay | The model run that the residuals are computed against. Personal data even when pseudonymised (s. 6) |

   Summing per bus works because loads at the same bus add up in the power flow. This keeps l.128–130 accurate as written.

6. **Low, s.4 l.65–68: the heading and "MINIMUM REQUIRED" read like a request list.** Replace with:
   > ## 4. Data an analysis would need, in three tiers
   >
   > This document requests no data. The tiers describe what an analysis would need, for a later discussion only if the utility chooses one.

7. **Low, s.6 l.132–133: "should" is weak.** Replace with:
   > - A technical discussion with no data exchanged can come first. No data would be accepted before the written agreement and the impact assessment, or through informal channels such as e-mail, messaging or personal storage.

8. **Low, s.8 Q2 l.161–163: missing the "asks for no data" note that Q1 has.** Append:
   > Could such series, if ever needed, be provided summed per bus? The question asks for no data.

9. **Low, s.7 l.146: "nothing published" is ambiguous.** Replace the Measure cell with:
   > All agreed conditions met; data deleted or returned with confirmation; no utility data or per-customer results published.

**No change needed:** the status block (l.5–9), s.2, s.3 item 3 and s.5 step 1 are accurate and don't promise any protection.

## Reality Checker: final evidence gate

**Verdict: READY AS EXPLORATORY INCREMENT.** I found no blocking issues. Of about 90 numbers I recomputed, two are slightly off, and five wording problems remain. None of these changes a registered result or a verdict.

#### Blocking issues
None.

#### Non-blocking issues
1. **Coverage wording is wrong in two places** (`docs/phase7_results.md`).
   - Line 363: the realistic single-reading coverage reaches 0.9557 (rural2/MV), so the range is 0.954–0.956, not "0.954–0.955".
   - Line 369: "identical across truths" is not true. The values are nearly identical: semiurb5's biased daily-mean coverage runs 0.2934–0.3005 across truths. Fix: "nearly identical (within 0.01)".
2. **The README contradicts results s. 4.** README line "Local or time-varying errors, which the substation cannot see". Results lines 278–279 say the busbar does see MV variation within the day, and the problem is C1's daily averaging. Fix: "local errors (not expected to be attributable from the substation) and time-varying errors (lagged by C1's averaging) were not tested."
3. **An argued point is presented as a finding.** Results s. 4 (lines 282–285) correctly says the common-mode/local split is "argued, not tested". Four places state it as fact:
   - `demonstrator.py:289`: "it cannot see local errors";
   - `kibtek_pilot_concept.md:53–56`, listed under "benchmark findings";
   - `technical_limitations.md`: "The substation can only correct errors that are common to the feeder";
   - learning guide 13.11, question 3.

   Fix: add "(argued, not tested)". This understates the method rather than overstating safety.
4. **`kibtek_pilot_concept.md:206`** says it was tested with "a near-exact busbar measurement". A busbar bias of ±0.005 p.u. was tested, with 260 violations at −0.005. Fix: "busbar bias tested only as a constant offset up to ±0.005 p.u."
5. **Learning guide 13.11, question 1** gives "1 against 513" without the +41 % mismatch curtailment. That breaks the rule stated in results s. 11 that this figure appears in every summary.
6. **`__main__.py` `run_demonstrator` docstring** cites "s. 10"; the demonstrator is in s. 12.
7. **The demonstrator's re-run check** compares violation totals only, not MWh. The docs say so. It would be stronger with MWh added.
8. **Review evidence:** the four review reports are not archived; only the s. 11 summary exists. I did not check the 16 references externally.

#### Evidence summary
- **Numbers (item 1).** Recomputed with a script that only reads the stored results:
  - All 17 rows of the s. 3 table match, and all 20 rows of the by-network table.
  - The busbar-bias table matches.
  - H1(a) 1 vs 513; H1(b) 66.23/52.33 = 1.266. The five noise replications give 1.233–1.273.
  - Mismatch curtailment: +41 % vs B3 (1.411×); C1 − Rdev = 828.9 MWh; margin cost 183.6 MWh, which is 46.4 % of the excess over the oracle.
  - Margin cost under the correct model: Rdev − R0 = 17.29 MWh.
  - Label rates at −0.005 are 0.41–0.61 and at +0.005 are 0.388–0.59; 471 of 915 days.
  - "Tolerated bias ≈ s": C1 at −0.002 equals C1s0 cell for cell in semiurb4, semiurb5 and urban6 (urban6 MV: 11 violations, 118.6 MWh in both); 1 tap + 16 MV violations.
  - Also match: label counts 732, 278 and 106; development figures 120, 166/1495, 91.0/86.7, 429 and 220; paired-interval counts 8/7/9/9; v̂ and ρ ranges; true offsets within 7.1e-5 p.u.
- **Claims (item 2).** I found no claim of safety, readiness or novelty. The method is called "Not a new method" (literature line 132) and "not a control system / safety assessment" (`demonstrator.py:245–248`). The KIB-TEK concept says it is "not certified" (line 9).
- **H1 failure stated early (item 3).** It is the first point of s. 1 (line 38) and of the README results. Negative findings appear in s. 9 "Cannot be claimed" and s. 14 "NOT SUPPORTED".
- **Causality (item 4).**
  - `replay(day)` reads only days day−28 to day−1 (`margins.py:140`).
  - `observe` runs after `measure()`, and `state()` is recorded before `observe` (`sensing.py`).
  - Lag and meter delay are applied in `margins.py:182,197`.
  - `test_corrector_never_reads_a_future_plan_or_nominal_state` passes.
- **Provenance (item 5).**
  - All seven post-evaluation hashes in the log match the files.
  - `margins.py` and `margin_study.py` still equal their frozen hashes.
  - Removing the two additions from `sensing.py` reproduces the frozen hash `56f08e27…`; I checked this myself.
  - `verify` returns [] for development, evaluation, and the Phase 6 outputs.
  - `require_freeze` refuses because `__main__`, `demonstrator` and `sensing` changed. That is documented as intended.
  - `demonstrate` ran in 7.7 s and its page is byte-identical to `outputs/demonstrator/…tap_raise_lv.html`, with no scripts and no external URLs.
- **Tests and CLI (item 6).** 241 tests pass; `ruff check` and `ruff format --check` are clean; all 11 commands respond to `--help`.
- **KIB-TEK concept (item 7).** It says no contact was made (line 6) and asks for no data (lines 67, 177, 182). The three tiers are at lines 70, 81 and 92. Customer data is treated as personal "even when pseudonymised" (lines 79, 132). Line 7 disclaims any KKTC facts.
- **Git (item 8).** On `main`; HEAD and origin/main are both 5d645eb. Nothing is staged, there are no stashes, and the changes are only unstaged edits plus untracked files.

#### Checklist
| Item | Status | Evidence |
|---|---|---|
| Existing results preserved | PASS | Phase 6 `verify` returns []; phase 5/6 docs untouched; earlier docs only had additions (learning guide 218/0) |
| Current tests verified | PASS | 241 passed |
| Prior art investigated | PASS | Literature s. 1–7, 16 references (not checked externally by me) |
| Falsifiable question | PASS | H1 had numeric thresholds and failed |
| Protocol registered | PASS | Timestamped log; 7A before the freeze |
| Continuous margins correctly implemented | PASS | `margins.py:38–46` plus a sign/unit test |
| Measurement uncertainty explicit | PASS | s. 13 sensor-uncertainty row; s. 5 |
| Random noise vs bias distinguished | PASS | C1 vs C1x; coverage 0.10–0.40 |
| Causal timing valid | PASS | Future-read guard; C1lag |
| Sparse observability quantified | PASS | s. 4 table; C3_1, C3_4, C3full |
| Continuous method evaluated fairly | PASS | Same days and noise; reliance on injection data disclosed |
| Strong simple baselines | PASS | B2–B7, static, R0, Rdev, oracle |
| Physical model mismatch evaluated | PASS | Three truths; untested directions listed |
| Curtailment and violations both measured | PASS | Reported as pairs throughout |
| Results by network | PASS | 20-row table |
| Statistical uncertainty considered | PASS | Block bootstrap, 5 replications, non-independence noted |
| Negative findings documented | PASS | H1, bias −0.005, season |
| Independent review completed | PASS | s. 11 (reports not archived) |
| No unsupported safety claims | PASS | — |
| No unsupported novelty claims | PASS | "Not a new method" |
| Existing tests pass | PASS | Phase 5 legacy pin included |
| New meaningful tests pass | PASS | Guard, lag, precedence, loader, demonstrator |
| Existing CLI functional | PASS | 11/11 `--help` |
| Artifacts reproducible | PASS | Hashes, `verify`, byte-identical demonstrator page; re-evaluation refused by design |
| Demonstrator created if justified | PASS | Static and labelled exploratory |
| KIB-TEK concept updated | PASS | Phase 7 s. 3, three tiers |
| No confidential data | PASS | `outputs/` git-ignored; no utility data |
| No staging | PASS | `git diff --cached` is empty |
| No commits | PASS | HEAD = 5d645eb |
| No pushes | PASS | origin/main = 5d645eb |

The scratch files are in `<scratchpad>/` (`rc_check.py`, `rc_check2.py`, `rc_pytest.txt`, `rc_demo/run1/`).
