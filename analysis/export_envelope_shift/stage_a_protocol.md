# Stage A protocol: PV correlation, sensitivity identifiability and the safety of data-driven export envelopes

**Status.**
- EXPLORATORY, internally pre-specified (Mission 11, 2026-10-24). Not externally preregistered and not confirmatory: the SimBench networks and earlier GridPulse results have been examined extensively.
- Written by the board before any scored solve. Board design audits (106 counted solves, `docs/provenance/mission11_board_audit/`) preceded it and are in the ledger (§12).
- **Revision 2.** The pre-experiment review (Paperclip AKK-58) and the board design audit were applied before any scored solve. The drafting record at the end lists every change.
- Changes after the first scored solve are dated amendments at the end. Nothing above them is edited.

**Design input.** `docs/research_strategy_assessment.md` (sha256 `dc214c37…`), direction 5 and its Part IX Stage A. This protocol departs from that design as follows, each departure stated:

| Design input (Part IX) | This protocol | Why |
|---|---|---|
| Shift = SimBench base year → 2034 PV (magnitude) | **Primary:** allocation shift at fixed deployment conditions. Magnitude shift is not run. | The mission asks to isolate spatial excitation; budget |
| Envelope against every network limit | **Primary decision = the voltage component of the envelope.** The thermal limits are excluded from the primary decision; a thermal-included arm is run as control T (§6) | Finding F0 (§2): in all six SimBench LV networks at the registered scale, thermal limits bind before voltage. Every method using a common thermal module would therefore be voltage-safe on one candidate network *by construction*, and on the other unsafe only through the tie-broken allocation. The voltage component is the part a learned voltage model decides. If it is voltage-safe, so is its componentwise minimum with any thermal component (monotonicity, §6) |
| 6 networks; verdicts "≥ 4 of 6" / "≥ 5 of 6" | 2 networks; "both networks" | Budget: about 3,500 solves per network. Only 2 networks with ≥ 10 PV units are voltage-limited at no action (§3) |
| Primary cell σ = 0.005; σ 0.002 secondary | **σ_v = 0.002 is the primary value**; 0.005 is control I's upper arm | 0.005 pu is the class-0.5 *bound* (m1). Field evidence for smart-meter voltage error is nearer 0.002 (Vanin et al. 2023, 0.38 V) |
| Training window 60 days | 4 days (384 steps); control H doubles it | Budget: 60 days would be 5,760 solves per regime and network |
| Monte Carlo replicates so the violation-rate SE < 0.005 | R = 2 noise realisations | Budget: each replicate needs its own AC-scored envelope |
| Allocation with an equal-share fairness constraint | Pure max Σe primary; proportional-fair (= equal share of availability) as control J | Equal-share allocation lies on the common-mode direction, which correlated data identify. It cannot exhibit decision-induced extrapolation, so it serves as the control |
| B2 = ridge with a conformal margin | **B2m = ridge plus a split-conformal margin**, as specified (§7) | — (adopted) |
| NC1 no-shift, NC3 records = truth, NC4 time-shuffled | NC1 → the in-distribution test day and the far set; NC3 → Method A / A′; **NC4 → control K** (time-shuffled training, zero solves) | Covered at no AC cost |
| Baselines included a neural network | No neural network | The mechanism is linear sensitivity identification. A neural network would confound capacity with excitation (the mission: "avoid unnecessary neural networks"). Recorded as a limitation |
| Compute "≈ one CPU-hour, up to a few hundred thousand solves" | **≤ 8,000 new AC solves**, ≤ 3 workers (1 used), ≤ 3 CPU-h, ≤ 1 GB | The owner's hard ceiling in Mission 11 |

- **The balanced model.** The design input's criticism of the balanced model (Mission 10) concerned a phase-frame sensitivity mechanism. It does not transfer to injection collinearity, which is a property of the data, not the phase model.
- **What is preserved:** decision-induced extrapolation, a physics-structured competitor, a certify-or-fall-back policy, AC ground truth, a partitioned outcome space and one primary cell.

**Prior art and what would make this non-novel** (targeted search, 2026-10-24; access levels in brackets):
- **Mandatory precedent — Gupta, Sossan & Paolone**, "Model-less robust voltage control in active distribution networks using sensitivity coefficients estimated from measurements", *EPSR* 212 (2022) 108547, doi:10.1016/j.epsr.2022.108547 [FULL]. Regularised and recursive least-squares sensitivities, a ±3σ box per coefficient (off-diagonal covariance dropped) and a Bertsimas–Sim budget, for PV curtailment and voltage control. It notes LS "does not perform well" under multicollinearity but does not quantify it. **Reproduced here as baseline B4box (on the regularised fit, as in the precedent).**
- **Other relevant work:**
  - Liu, Braslavsky & Mahdavi 2024 (robust envelopes; assumed impedance norm balls; model-based) [FULL].
  - Kumarawadu et al. 2025 (smart-meter data-driven envelopes) [ABSTRACT only: the full text could not be read, a stated gap].
  - Jalilian, Deka, Hashmi & Van Hertem 2026, arXiv:2604.17081 (coordinated envelopes, joint feasibility over boxes; sensitivities treated as exact) [FULL, partly read].
  - Valverde et al. 2018 (collinearity in smart-meter sensitivity estimation) [ABSTRACT].
  - Zhang et al., *IEEE TPWRS* 33(2) (2018), doi:10.1109/TPWRS.2017.2733580 (locally weighted ridge against collinearity) [METADATA].
  - Mittal, Pareek & Verma 2023, *EPSR*, doi:10.1016/j.epsr.2023.110083 (correlated injections, errors-in-variables line estimation) [METADATA].
  - Picallo et al., arXiv:2110.00954 (persistent excitation by dithering) [FULL].
  - Chan et al., CDC 2025, arXiv:2503.24151 (robust feedback optimisation, tuned radii) [FULL].
- **Not novel** (and not claimed):
  - ill-conditioning under correlated injections;
  - ridge or probing as remedies;
  - "robust is safer but more conservative";
  - the ellipsoidal robust counterpart, which is textbook (Ben-Tal & Nemirovski);
  - that LV hosting capacity can be thermally limited.
- **Possibly new** (to be tested, not assumed):
  - a measured relation between injection excitation and *envelope safety* under simultaneous at-limit export;
  - whether in-distribution prediction accuracy predicts that safety;
  - whether data-consistent models disagree on the decision;
  - the robust ellipsoid against Gupta's box, ridge and a topology-structured estimate, on a safety-utilisation frontier;
  - whether the voltage-identification problem matters at all once thermal limits are included (F0, control T).

---

## 1. Question

Smart-meter data are used to learn customer-bus voltage sensitivities, and individual PV injections in those data are strongly correlated. **When the voltage component of an export envelope is optimised on the learned sensitivities, is it physically safe** when every participant simultaneously exports at its limit? And:
- **When** does correlation harm decision reliability, and when does it not?
- **Do established methods prevent it:** regularisation, topology-structured estimation, robust optimisation over a data-consistent set, or a simple conservative policy?
- **Can a reliability-aware rule tell** when the data do not justify an allocation, without simply being more conservative?
- **Does it matter in the full decision?** On these networks, thermal limits bind first (F0). Control T measures how much of any voltage-component effect survives when the thermal limits are included.

**The six things kept apart:**
1. predictive accuracy;
2. parameter identifiability;
3. decision identifiability;
4. physical safety;
5. operational usefulness (export utilisation);
6. generalisation under changed allocation.

---

## 2. Facts fixed by the board audit

The scripts and their printed outputs are in `docs/provenance/mission11_board_audit/` (106 counted AC solves, of which 38 were invalid or diagnostic and are counted anyway). Every number in this section is reproducible from that record.

- **Networks:** SimBench LV `--2-sw`, built with GridPulse's `dual_study.variant_network(code, NOMINAL, pv_scale(code))`.
  - This is the Phase 4 registered PV scale: each network's PV is scaled so that it sits at 1.40× **its own** hosting capacity. The 1.40 multiple is rural1's (`dual_study.HOSTING_CAPACITY`, `pv_scale`).
  - No switch is open. No line has `parallel` > 1.
- **Native SimBench PV is degenerate.** Every PV unit takes one of a few standard profile types (PV1–PV8), and units of the same type have *identical* series:
  - mean daylight pairwise correlation 0.82–0.88, and exactly 1.0 for semiurb4's 6 units;
  - effective rank 1.0–1.7;
  - condition number ≈ 3e14–6e14, i.e. singular.
  - Learning per-unit sensitivities from native profiles is therefore impossible *by construction*. That is the predetermined-answer case the mission forbids. **Native profiles (call it P0) are documented analytically and not used as a scored regime.**
- **Storage.** The SimBench networks contain storage units with a non-zero, discharging default dispatch (rural3: 16 units, −0.093 MW). **Storage is held at 0 MW in every solve of this study.** The first board binding audit had left the default in place; it is recorded as invalid.
- **F0 — thermal limits bind before voltage at the registered scale.** No action, peak-availability step, days 100–131 (outside every split), storage 0 MW:

  | Network | PV units | Voltage margin (pu) | Thermal loading | θ_V | θ_T |
  |---|---|---|---|---|---|
  | rural1 | 8 | −0.066 to −0.067 | trafo 135–141 % | 1.00 | 0.71–0.74 |
  | rural2 | 11 | −0.009 to −0.010 | trafo 129–130 % | 1.00 | 0.77–0.78 |
  | rural3 | 27 | **+0.003 to +0.005** | trafo 122–126 % | 0.92–0.96 | 0.79–0.82 |
  | semiurb4 | 6 | −0.007 to −0.013 | line 129–130 % | 1.00 | 0.77 |
  | semiurb5 | 15 | **−0.0006 to +0.0045** | line 122–130 % | 0.95–1.00 | 0.77–0.82 |
  | urban6 | 12 | −0.0001 to +0.0019 | line 125–128 % | 0.97–1.00 | 0.78–0.80 |

  - θ_V is the uniform availability fraction that just removes the voltage exceedance (balanced LinDistFlow from the AC state). θ_T is the same for thermal (≈ 100 / loading).
  - **With a common thermal module in the decision** (rural3 and urban6, deployment-window peak days):
    - the LP optimum has the thermal row active and no voltage row active;
    - the worst thermally feasible allocation at the same total gives an AC voltage margin of +0.003 to +0.004 pu on rural3, and −0.011 pu on urban6.
  - **Consequences:**
    - on urban6, voltage-unsafe envelopes are structurally impossible for every method;
    - the proportional-fair objective is structurally voltage-safe on both networks, since θ ≤ θ_T < θ_V;
    - on rural3, only the allocation could create a voltage violation.
  - This motivates the primary decision of §6 and control T.
- **Definitions checked** (zero solves):
  - every PV unit sits on a bus that carries a SimBench load;
  - `max_vm_pu` = 1.10 and `min_vm_pu` = 0.90 at every customer bus;
  - min(`max_vm_pu`) over all LV buses = 1.10.
- **Speed:** about 6 ms per AC solve (balanced `pandapower.runpp`).

---

## 3. Networks (selection policy fixed before scoring)

The rule, applied to the six SimBench LV networks GridPulse uses:
1. require **at least 10 PV units**, because allocation must be non-trivial: rural2 (11), rural3 (27), semiurb5 (15) and urban6 (12) qualify;
2. require the network to be **voltage-limited at no action**: the median no-action voltage exceedance over the three audit peak steps (§2, days 100–131) must be > +0.001 pu. This leaves rural3 (+0.0037) and semiurb5 (+0.0043); urban6 (+0.0005) and rural2 (−0.0097) fail;
3. take the qualifying network with the most PV units as the **evaluation** network: **1-LV-rural3--2-sw** (27 PV units, 118 customer buses);
4. the other qualifying network is the **development** network: **1-LV-semiurb5--2-sw** (15 PV units, 104 customer buses).

**How each network is used:**
- **semiurb5:** the implementation pilot runs here, and the full design is also run. Its results are labelled *development (inspected during implementation)*. It is **corroborative**: its inspection status is restated wherever a verdict cites it.
- **rural3:** run once with frozen code. The primary claim rests on rural3. It is **not** genuinely unseen: SimBench and rural3 were examined in Phases 4–9 and in the board audit.
- **No third network.** The budget does not allow one (§12).

**Physical conventions, kept from GridPulse:**
- balanced positive-sequence model (a limitation);
- MV supply and transformer tap at nominal and *constant*;
- loads at SimBench P and Q, scaled by §4's load process;
- PV at unity power factor;
- **storage at 0 MW**;
- line and transformer limits at 100 % loading.

**Definitions:**
- A **customer bus** is an LV bus carrying at least one SimBench `load`: 118 on rural3, 104 on semiurb5. Before the first solve, the code asserts these counts and that every PV unit's bus is a customer bus.
- **Voltage limits** come from the bus table: `max_vm_pu` and `min_vm_pu` at customer buses, 1.10 and 0.90 on both networks.
  - The criterion is evaluated at customer buses. Exceedance at **every** LV bus is also reported.
  - A zero-flow assertion checks that min(`max_vm_pu`) over customer buses ≤ min over all LV buses.
- Per-bus voltages and per-branch loadings are read from `net.res_bus` / `net.res_line` / `net.res_trafo` after each solve, as `gridpulse.fullstate._state` does. `GridSolver.solve` returns only aggregated margins.

---

## 4. Data regimes (synthetic interventions on SimBench base profiles)

Every regime uses the **same physical networks, the same days and the same load process**. Only the PV heterogeneity process differs. Every intervention is synthetic and labelled as such.

**PV unit i** (rating r_i, SimBench type τ(i)):

  a_i(t) = r_i · min(1, max(0, s_τ(i)(t + δ_i) + w_τ(i)(t)) · c_i(t))

- g_τ is the unit's SimBench normalised profile of type τ. It is split into:
  - a smooth component s_τ, a centred 2-hour (8-step) rolling mean of g_τ;
  - a weather residual w_τ = g_τ − s_τ, which carries the benchmark's own clouds.
- δ_i is the **orientation**, as a fixed time shift of the smooth component only, drawn once per unit from U(−Δ, Δ) hours.
  - East/west azimuths shift the clear-sky diurnal curve. They do not shift when a cloud passes, so w_τ stays at wall-clock time. Shifting the whole profile would decorrelate the weather too, which azimuth diversity does not do.
  - δ_i is a property of the installation, identical in training and deployment.
  - max(0, ·) prevents negative output at dawn and dusk.
- c_i(t) = exp(σ_c·η_i(t) − σ_c²/2) is **local cloud and shading**. η_i is a unit-specific AR(1) series with φ = 0.8 per 15 minutes and unit variance, independent across units.
- min(1, ·) is **inverter clipping** at the rating.
- After generation, each unit's series is rescaled so its mean over the training days equals the native P0 mean, preserving energy. The rating clip is re-applied, and the residual marginal differences are reported (control C).

**Pre-specified heterogeneity levels** (parameters fixed now; the resulting correlation is *measured*, not tuned):

| Regime | Δ (h) | σ_c | Intended character |
|---|---|---|---|
| **P1** (correlated) | 0.0 | 0.05 | Nearly common irradiance: the realistic worst case short of identical |
| **P2** (moderate) | 0.5 | 0.15 | Mixed orientation, some local cloud: the realistic end of the range |
| **P3** (informative) | 1.0 | 0.30 | Strong orientation spread and independent local shading: an upper bound |

**Realism of the levels.** c_i is independent across units. Over a single LV feeder, though, 15-minute cloud transmittance is strongly correlated in space.
- **P3 is therefore an upper bound on achievable per-unit excitation, not a realistic regime.** P2 is the realistic end of the range, and P1 the realistic worst case.
- The H1 contrast P1 − P3 is an **upper bound** on what better excitation could deliver, and is reported as such. P1 − P2 is reported alongside as the realistic-range contrast (descriptive, outside the Holm family).

**Loads** (household heterogeneity, the same process in every regime): load j is

  ℓ_j(t) = L_j(t + τ_j) · s_j · exp(σ_L·ζ_j(t) − σ_L²/2)

- L_j is the SimBench load profile;
- τ_j ~ U(−30, 30) minutes;
- s_j ~ logN(0, 0.2²), renormalised to keep the feeder's mean load;
- σ_L = 0.3;
- ζ_j is AR(1) with φ = 0.7;
- Q is scaled with P to keep each load's SimBench power factor.
- **Limitation:** this process is smoother than real single-household demand at 15 minutes. Real load excitation therefore lies *above* both the synthetic process and L0.

**Control regime L0** ("load-homogeneous"): P1's PV process with *native* SimBench load profiles (σ_L = 0, τ = 0, s = 1). It tests whether household load variability, which smart meters see in **net** injection, already supplies the excitation PV lacks.

**Days** (SimBench 2016, UTC day indices, as in `grid_study`):
- **training:** days 152–155 (4 days, 384 steps);
- **in-distribution test:** day 156 (96 steps);
- **sample-size extension (rural3, P1 only):** days 132–135 (+384 steps);
- **deployment conditions** (§5): days 160–199, never overlapping training or test.

**Measurements** (smart meters at every customer bus):
- **voltage magnitude |V|** with i.i.d. Gaussian noise σ_v.
  - **σ_v = 0.002 pu is the primary value**: about a 0.2 %-of-nominal reading (0.46 V on a 230 V base), close to Vanin et al. 2023's 0.38 V.
  - 0.005 pu, the class-0.5 value and the design input's primary, is control I's upper arm; 0.0005 is its lower arm.
- **net active power P** per customer bus, exact (a stated simplification);
- **net reactive power Q** per customer bus, exact (the same simplification). B3 and Methods A/A′ need it; B1, B2, B2m, B2p, B4 and B4box use P only.
- Noise is applied after the physics, so noise realisations cost no solves.

**Excitation diagnostics**, reported per regime and network:
- the daylight pairwise correlation of PV outputs (mean, minimum);
- the singular-value spectrum of the standardised net-injection design matrix;
- the effective rank (entropy-based);
- the condition number with an explicit tolerance (singular values below 1e-10 × the largest count as zero);
- the independent excitation per bus: the residual variance after regressing a bus's injection on all others;
- **the distance of the deployment corner from the training support:**
  - the residual after projecting onto the leading training principal components that explain 99 % of the variance;
  - the Mahalanobis distance under the training covariance with a 1e-10 relative eigenvalue floor.

---

## 5. Deployment conditions (paired across regimes; selected by offline truth)

The ground truth may be used here, because this is offline experimental design, not a deployable estimator.

- **Near-constraint (control E).**
  - **Candidates:** for each day 160–199, the step with the largest total base availability. Solve it with no action at full availability (40 AC solves per network).
  - **Screen:** keep only candidates whose no-action voltage exceedance is **> +0.001 pu** at some customer bus. Otherwise no envelope can be voltage-unsafe there (§6, monotonicity).
  - **The near set:** the **10 surviving steps with the largest no-action voltage margin** (most violating), on distinct days.
  - The number of survivors is written into the selection record. **If fewer than 10 survive on a network, §15 applies to that network.**
- **Far-from-constraint (control D).**
  - **Candidates:** for each day 160–199, the first daylight step with base availability ≥ 20 % of rating. Solve with no action (40 per network).
  - **The far set:** the **10 steps with the most negative voltage margin, and every thermal loading ≤ 80 %**.
- **The e = 0 vertex** (no PV export, the same loads) is solved once per condition (20 per network). It is method-independent (§6).
- **Availability at a deployment condition:** a_i = r_i · f(t), with f(t) the mean of the SimBench PV type profiles at that step. It is **identical for every unit and every regime**.
  - Caveat: under P3, this rating-proportional alignment is rare in training. P3's well-excited design supports prediction in that direction, but the caveat is stated next to the H1 contrast.
- **Loads:** the same synthetic household loads in every regime, **including L0**. L0's native loads apply to its training data only, so its pairing is exact too.
- **The pairing is exact.** Across regimes only the training data differ, so any difference in decisions comes from what was learned.

---

## 6. Decision problem (common to every method)

**Envelope.** A vector e = (e_1, …, e_N) of per-PV-unit export limits, with 0 ≤ e_i ≤ a_i. It is a **rectangular joint envelope**: the claim is that every point of the box [0, e] is safe.

**Worst-case vertices.** Each bus voltage and each branch flow is (in the linear model) monotone in e. With sensitivities ≥ 0 on these radial feeders, over the box [0, e]:
- **the upper voltage limit** is worst at the **all-at-limit corner** e;
- **the lower voltage limit and the import direction of the thermal limits** are worst at **e = 0**.

**Both vertices are AC-scored.**
- e = 0 is method-independent, so it costs one solve per condition (§5).
- The thermal *export* direction is worst at the corner and is reported there.
- A zero-flow test checks the monotonicity in the linear model. §15 has an AC check of interior points.

**Primary decision — the voltage component.** Maximise Σ e_i (aggregate export, i.e. minimum curtailment) subject to:
- **(V)** predicted corner voltage at every customer bus k: v̂_k(e) ≤ V_max,k − m.

Thermal limits are **not** part of the primary decision (F0, §2).
- The corner's thermal loading is AC-measured and reported, but carries no verdict for the primary decision.
- A voltage-safe voltage component stays voltage-safe after a componentwise minimum with any thermal component, because a smaller box has a lower corner.

**Control T — the full decision** (secondary; B2 only; P1 and P3; near set; R = 2; both networks; 80 solves). Maximise Σe subject to (V) and:
- **(T)** the common thermal module: |Σ_{j downstream of l} (e_j − ℓ_j)| ≤ κ · I_max,l · √3 · V_nom for every line l, and the same for the transformer, with **κ = 0.95 fixed now**.
  - The lossless, P-only approximation is optimistic against pandapower's current-based `loading_percent`; κ absorbs that bias.
  - The realised approximation error (module flow against AC loading at every scored corner) is reported. If its 95th percentile exceeds 5 %, the thermal results are labelled approximation-limited.
  - The module depends only on topology, ratings, e and ℓ; no method is scored on a learned thermal model.

**Secondary objective (control J):** *proportional-fair* — maximise θ with e = θ·a, a single scalar.
- The decision then depends only on the common-mode direction, which correlated data identify.
- It is expected to be decision-equivalent across data-consistent models.

**Solver and ties.** `scipy.optimize.linprog` (HiGHS). Ties are broken by a second stage, not by a perturbation below the solver's tolerance:
- **stage 1** maximises Σe;
- **stage 2** fixes Σe ≥ Σe* − 1e-6 MW and minimises Σ_i |e_i/a_i − θ̄|, with θ̄ = Σe*/Σa (L1, written as an LP with auxiliary variables). It selects the most proportional optimum.
- The share of conditions on which stage 2 moves the allocation by more than 1 % in L1 is reported.

**Scoring shortcut.** An envelope equal to a (to 1e-12 MW) is scored by the no-action selection solve already made. No new solve is run or counted.

---

## 7. Methods

**Deployable methods** use smart-meter data (P, Q and noisy V at customer buses), plus topology and ratings (ratings for control T only). They are never given true impedances.

**Common regression set-up:**
- For each customer bus k, v_k = c_k + Σ_b β_kb·P_b over all customer buses' net P, export-positive. With N_b buses there are p = N_b + 1 parameters per bus.
- X̃ is the training design [1, P].
- **Ridge** standardises the regressors with the training mean and standard deviation, and leaves the intercept unpenalised.
- **λ** is chosen by time-blocked cross-validation with one block per training day.
- Predicted corner voltage: v̂_k = c_k + Σ_b β_kb·P_b(e). Here P_b(e) = e_i − ℓ_b at PV unit i's bus and −ℓ_b elsewhere.

| Code | Method | How the voltage model and the decision are obtained |
|---|---|---|
| **B0** | 70 % rule (static) | e_i = min(a_i, 0.7·r_i). A real pre-existing engineering policy (Germany's former EEG 70 % feed-in limit), with no network data. |
| **B1** | OLS sensitivity | Least squares on X̃ (`numpy.linalg.lstsq`, minimum-norm solution if rank-deficient), m = 0. |
| **B2** | Ridge sensitivity | Ridge on days 152–155, λ by 4-fold day-blocked cross-validation, m = 0. **The primary data-driven method.** |
| **B2m** | Ridge plus conformal margin | Ridge refitted on days 152–154 (λ by 3-fold day-blocked cross-validation on those days). m_k = the 0.95 split-conformal quantile of \|v_k − v̂_k\| on held-out day 155. **The design input's named strongest practical baseline.** Being in-distribution, the margin is *not* expected to cover a decision-induced shift; that is part of what H3 tests. **Diagnostic, no AC:** the in-sample margin 2·σ̂_res,k is reported beside m_k. |
| **B2p** | Ridge, proportional-fair | B2's model with the secondary objective. |
| **B3** | Topology-structured estimate | Known topology, unknown line parameters: Δv_k = Σ_{l∈path(k)} (ρ_l·F_l + χ_l·G_l), with F_l and G_l the downstream net P and Q, so (ρ_l, χ_l) = (r_l, x_l)/V_nom². The busbar intercept is fitted jointly. Fitted by non-negative least squares (LinDistFlow; established, in the spirit of Peppanen et al.). m = 0. |
| **B4box** | Gupta-style robust box | B2's ridge coefficients, each ± 3σ̂_j. σ̂_j comes from diag(σ̂²·(X̃ᵀX̃ + Λ)⁻¹X̃ᵀX̃(X̃ᵀX̃ + Λ)⁻¹), with Λ the ridge penalty matrix in X̃'s units (zero for the intercept). Off-diagonal terms are dropped, as in Gupta et al. 2022, whose i.i.d. assumption is reproduced and stated. The worst case uses a Bertsimas–Sim budget of Γ = ⌈√p⌉ coefficients per bus, in its LP dual form, with \|P_b(e)\| linearised by auxiliary variables. |
| **B4box-OLS** | Secondary arm | The same box on B1's OLS fit, with σ̂_j from diag(σ̂²(X̃ᵀX̃)⁺). P1 and P3, near set, R = 2 (80 solves). If X̃ᵀX̃ has a relative condition number > 1e10, it is recorded as `robust-degenerate`. |
| **B4** | Robust ellipsoid (data-consistent set) | **E_k = {β : (β − β̂_k)ᵀ M (β − β̂_k) ≤ r_k²}**, with β̂_k B2's ridge estimate and M = X̃ᵀX̃ + Λ. M is positive definite, so E_k is bounded in the un-excited directions. **The radius comes from a moving-block bootstrap, not an F/χ² reference** (GridPulse's R7 lesson, `docs/phase9_results.md`; the design input, `docs/research_strategy_assessment.md`): see the radius rule below. **Robust constraint:** β̂_kᵀx(e) + r_k·√(x(e)ᵀM⁻¹x(e)) ≤ V_max,k, solved by Kelley cutting planes (each cut uses the closed-form worst β; each round adds one cut for every violated bus) to 1e-6 pu. **The cut budget is at most 60 rounds** (revision 2.2). If the cuts have not converged by then, the last stage-1 envelope is shrunk uniformly by the largest factor that makes every robust constraint hold (bisection, 50 steps). That envelope is used and labelled `restored`, together with its optimality gap against the cut LP's upper bound; a gap > 1 % is flagged. **Degenerate rule:** if the robust LP is infeasible (including g(0) > 0), or returns Σe ≤ 0.02·Σa, the condition is recorded as `robust-degenerate`, never as a safe envelope. A budget limit alone is never `robust-degenerate`. |

**B4's radius rule.**
1. Draw 400 moving-block bootstrap refits of the ridge with λ fixed. Blocks are 16 steps (4 h), resampled circularly within the 384 training steps, with their noise.
2. For each refit b and bus k, compute d_kb = (β*_kb − β̂_k)ᵀM(β*_kb − β̂_k).
3. **Simultaneous radius over buses:** c = the 0.95 quantile over b of max_k (d_kb / median_b d_kb), and r_k² = c · median_b d_kb.
4. The F-quantile radius p·σ̂²·F_{p,T−p}(0.95) is computed and reported only as a diagnostic of how far the independence assumption is off.

**Reference and diagnostic methods** (not deployable):

| Code | Method | Role |
|---|---|---|
| **A** | Exact linear, AC offset | B3's structure evaluated with the true r_l, x_l. Its intercept is set from the condition's no-action AC state (the selection solve, no extra cost). |
| **A′** | Exact linear, training intercept | B3's structure with the true r_l, x_l, but with the intercept fitted on the training days (the mean training residual of noisy V), as the deployable methods fit theirs. **Control A′ is the attribution reference (§10).** A − A′ is the size of the offset-extrapolation term. |
| **B5** | AC oracle (voltage component) | Maximise Σe subject to AC-feasible upper voltage limits. Sequential LP: true-impedance sensitivities re-linearised at the current AC state, with an offset correction from the AC solution. At most 6 iterations, stopping when the AC power flow is feasible within tolerance and Σe changes < 0.5 %. If still infeasible, a uniform back-off by bisection, at most 8 solves. Near set only (on the far set the oracle envelope is a). **Utilisation and regret are measured against B5.** |

**Reliability-aware rule** (run only if §9 H1 is not rejected):
- **CERT.** Act with B2's envelope when the four random data-consistent alternatives (§8, built from B2's ridge) agree. Their total-export spread must be < 10 % of B2's total, and their envelopes must lie within the B2 box's ±10 % in L1. Otherwise fall back to B2p.
- **Controls for Phase 3's deferral lesson:**
  - **ALWAYS:** always use B2p;
  - **RAND:** fall back at random at CERT's realised rate, seeded.
- CERT is credited with risk discrimination only if it beats RAND at the same fallback rate.
- **CERT is NOT EVALUABLE on a network where its realised fallback rate is 0 or 1**, because RAND would then be identical to it.

---

## 8. Decision ambiguity (H4; control J)

For each regime, network and near-constraint condition:
1. Build data-consistent alternatives from the training data. **They never use the true network.** Each must be physically admissible: every sensitivity ≥ 0, as it is on these radial feeders.
2. Draw **M = 8 alternatives**:
   - **4 random:** 4 moving-block bootstrap refits (as in B4's radius rule, a separate seed) of the **non-negative ridge** model. This is B2's λ with every slope constrained ≥ 0, solved by `scipy.optimize.nnls` on the augmented system [X̃; √Λ]. Each refit is admissible by construction and fits a resample of the same training data, so no rejection sampling is needed.
     - Each alternative's full-training RMSE relative to B2's is reported.
   - **4 extreme:** around the full-sample non-negative ridge fit, move ± along the two weakest eigen-directions of M (shared by every bus, because the design is shared), to the boundary of B4's set E_k for each bus. If a point is inadmissible, shrink it toward the centre until it is admissible.
     - The realised shrink factors are reported.
     - **By construction these maximise disagreement within the set. They are a stated upper bound on ambiguity and carry no verdict.**
3. For each alternative, compute the primary-decision envelope and the proportional-fair envelope.
   - **AC-score the primary-decision envelopes** for regimes P1 and P3 at the 10 near conditions: 8 × 10 × 2 × 2 = 320 solves.
   - The proportional-fair envelopes are compared by Σe and allocation only, without AC.
4. **Measures** (random and extreme alternatives reported separately):
   - the export spread: (max − min) of Σe over the alternatives, divided by the oracle's Σe;
   - the allocation spread (L1 distance);
   - the safety disagreement: the share of conditions where at least one alternative is voltage-safe and at least one is voltage-unsafe.

---

## 9. Hypotheses, metrics and the partitioned outcome space (fixed now)

**Primary unit:** a deployment condition (one step on a distinct day).
- Per network: 10 near conditions plus 10 far.
- 2 noise realisations per training regime and method (R = 2). These are nested inside the condition and averaged within it before inference.
- **The two networks are not treated as replicates.** "Supported" requires *both* networks. The primary claim rests on rural3; semiurb5 is corroborative (development network).

**Voltage-unsafe:** at the envelope corner, the AC voltage exceeds V_max,k + 0.001 pu at any customer bus.
- The tolerance is far above the solver noise of about 1e-8 to 1e-7 pu.
- **Severity:** the maximum exceedance in pu.
- **The e = 0 vertex:** if its AC voltage falls below V_min,k − 0.001 pu, or any loading exceeds 100 % + 0.5, the condition is unsafe for *every* method (method-independent). Such a condition is reported and excluded from method comparisons.
- **Thermal loading at the corner:** reported for every envelope. It is a verdict input only in control T, where thermal-unsafe means any loading > 100 % + 0.5.
- **"Zero observed unsafe"** means no unsafe envelope in **either** replicate at **any** of the conditions. The Clopper–Pearson n is the number of conditions, because replicates are nested.

**Utilisation:** Σe / Σe_B5, defined only for voltage-safe envelopes. Unsafe envelopes count as unsafe, not as utilisation.

**Binding-constraint diagnostic** (reported for every method, condition and regime; LP only):
- the active-constraint set at the LP optimum;
- the share of near conditions on which at least one (V) row is active;
- whether stage 2 moved the allocation.
- **If (V) is active for the oracle B5 on fewer than 7 of 10 near conditions on a network, H1–H3 are NOT EVALUABLE on that network.**

**Inference:**
- percentile bootstrap over conditions within a network, 2,000 resamples, seeded;
- for differences, a paired bootstrap on the same conditions;
- **Holm correction across a primary family of exactly 4 tests, fixed now:**
  1. H1's P1 − P3 paired voltage-unsafe-rate difference on rural3;
  2. the same on semiurb5;
  3. H3's paired utilisation difference (better robust method minus best simple policy) on rural3;
  4. the same on semiurb5.

  Nothing else enters the family. Every other interval in this protocol is descriptive and is labelled so in the report.
- **zero observed failures is never reported as "safe"**: the Clopper–Pearson upper bound is given. Pooled bounds over both networks are descriptive only; the criterion is per network.

**Primary cell:** σ_v = 0.002, training T = 384, near-constraint conditions, primary decision. Every other cell is labelled secondary and carries no claim.

**H1 — correlation-dependent reliability.** Contrast: the voltage-unsafe rate of **B2** (the primary data-driven method, the strongest standard one) for P1 minus P3, paired.

| Verdict | Condition |
|---|---|
| **Supported** | The difference is ≥ 0.20, with the paired bootstrap 95 % lower bound > 0 after Holm, on both networks; **and** control C passes; **and** the effect survives controls H and I as defined in the rejection row. |
| **Rejected** | Any one of:<br>• the 95 % interval lies within [−0.10, 0.10] on both networks;<br>• **small-data effect**: with training doubled to T = 768 (rural3, P1), B2's unsafe rate falls to within 0.10 of P3's at T = 384;<br>• **noise-only effect**: at σ_v = 0.0005, the P1 − P3 difference is < 0.10 on both networks.<br>Whether a standard structured or robust method (B3, B4, B4box) removes the effect is **not** an H1 criterion. It is reported under H3 and control F as "an established method suffices". |
| **Inconclusive** | Otherwise. |

**Detectable effect.**
- The 0.20 threshold is a mean paired difference of 0.20 over the 10 conditions. The binding requirement is the bootstrap, not the threshold.
- With n = 10 and no condition differing in the opposite direction, a percentile lower bound above 0 requires **at least 4 discordant conditions**:
  - k = 4 gives P(no discordant condition in a resample) = 0.6¹⁰ = 0.0060, below both Holm's most stringent lower tail (0.0125 / 2 = 0.00625) and the least stringent (0.025);
  - k = 3 gives 0.7¹⁰ = 0.028, which fails.
- Any opposite-direction condition raises that count.
- At R = 2, a condition with one of two replicates unsafe scores 0.5. So 4 half-magnitude conditions give exactly 0.20.
- Both are fixed before scoring.
- **Interpretation:** P1 − P3 is an upper bound (§4); P1 − P2 is reported beside it.

**H2 — prediction against decision.**
- **In-distribution accuracy:** the MAE of the noise-free predicted voltage against the AC truth on the test day (96 steps), for each of the **3 distinct voltage models** (OLS = B1's, ridge = B2's, NNLS = B3's) and regime. For B4 and B4box, the MAE is that of the nominal point prediction, not the robust bound.
- **Decision-point error:** |predicted − AC| maximum corner voltage, from the envelope checks (no extra solves).

| Verdict | Condition |
|---|---|
| **Supported** | On both networks, some voltage model in P1 has in-distribution MAE ≤ 0.001 pu **and** a voltage-unsafe rate ≥ 0.30 on the near set (primary decision, m = 0); **and** across the **9 voltage-model × regime cells** (3 models × 3 regimes; unsafe rate under the primary decision with m = 0, so that the decision rule is held fixed), the Spearman correlation between in-distribution MAE and the unsafe rate is < 0.5. |
| **Rejected** | No such cell exists on either network, **or** the Spearman correlation over the same 9 cells is ≥ 0.8 on both networks. |
| **Inconclusive** | Otherwise. |

The 7 methods collapse onto 3 voltage models, so a method-level Spearman would be tied and attenuated by construction. The full 21-cell scatter is reported as a figure and carries no verdict.

**H3 — information-aware and robust methods.** Compared on the near set, P1, both networks:
- **B4** and **B4box** against **B2m**, **B2p** and **B0**;
- **CERT** against **ALWAYS** and **RAND**.

| Verdict | Condition |
|---|---|
| **Supported** | B4 or B4box has **zero observed voltage-unsafe envelopes** on each network's near set (Clopper–Pearson upper bound 0.31 per network: reported, not hidden); **and**, over the near conditions on which **both** compared methods are voltage-safe and neither is `robust-degenerate`, its median utilisation exceeds the best of B2m, B2p and B0 by ≥ 0.10, with the paired bootstrap lower bound > 0. The count of joint conditions is reported per pair; the comparison is **NOT EVALUABLE** if fewer than 7 of 10 remain on either network. A companion comparison over all 10 conditions, with utilisation 0 for unsafe or degenerate envelopes, is reported alongside; if the two disagree in sign, the verdict is Inconclusive. Separately, CERT is credited only if it has fewer unsafe outcomes than RAND at the same fallback rate on both networks. |
| **Rejected** | A simple policy (B2m, B2p or B0) is at least as safe and within 0.05 of the better robust method's utilisation, on both networks. Then **the established or simple baseline suffices**, and that is reported as the finding. **Or** the better robust method is `robust-degenerate` on ≥ 5 of 10 near conditions on both networks: **the established robust method is unusable under this excitation**, reported as the finding. |
| **Inconclusive** | Otherwise. |

**H4 — decision relevance of non-identifiability.** In P1 near conditions, primary decision, over the **4 random alternatives**:

| Verdict | Condition |
|---|---|
| **Material ambiguity** | On both networks, the median export spread is ≥ 0.10 **or** the safety disagreement rate is ≥ 0.30. |
| **Decision equivalence** | The export spread is < 0.05 **and** the safety disagreement is 0, on both networks. |
| **Mixed** | Otherwise. |

The same is reported for P3 and for the proportional-fair objective. The extreme alternatives are reported separately as an upper bound and carry no verdict.

**Control T read-out** (descriptive, no verdict): B2's P1 − P3 voltage-unsafe difference under the full decision, beside the same under the primary decision. F0 predicts a much smaller difference under the full decision. The result is stated whichever way it falls.

**Expected-against-observed honesty.** The board expects (a HYPOTHESIS, written down now) that:
- household load variability will supply substantial excitation (control L0), even though the synthetic process understates real load variability (§4);
- B3 and B4 may remove most of the effect;
- the full decision (control T) will mask most of any voltage-component effect.

Any of these would weaken or reject H1 or H3, or limit their practical relevance. **That outcome is reported, not rescued.**

---

## 10. Negative controls (each able to fail the hypothesis)

| Control | How it is tested | What would undermine H1 |
|---|---|---|
| **A / A′** correct physics | Method A (true impedances, AC offset), Method A′ (true impedances, training intercept), B5 | **Attribution rule:** a data-driven method's unsafe outcomes are attributed to identification only *in excess of* **A′'s** on the same conditions (paired). A′, not A, is the reference: A carries a condition-exact AC offset that no deployable method has. If A′ is unsafe often, the linear model with a learned offset, not identification, explains the failures |
| **B** independent excitation | P3 against P1 (the H1 contrast) | No difference |
| **C** matched marginals | **Pass criterion, fixed now:** every PV unit's training-day mean within 1 % across P1–P3, **and** the median over units of the relative difference in the training-day daylight 95th percentile (P3 or P2 against P1) within 10 %. Reported only: per-unit maxima, per-unit KS statistics, the total-injection distribution and the corner distance (§4). The cloud factor widens each unit's distribution, and decorrelation narrows the aggregate's tail; that is the manipulation itself, not a confound. Deployment conditions are identical by construction | Failing the criterion, which confounds the contrast through magnitude |
| **D** far from constraint | The far set: every method should be voltage-safe there (monotonicity) | Unsafe outcomes on the far set: a methodology fault |
| **E** near constraint | The near set (primary) | — |
| **F** regularisation and structure | B2 (ridge) and B3 (topology-structured) | B3 safe in P1 at P1 = P3 |
| **G** robust optimisation | B4, B4box (and B4box-OLS) | B4 is safe with high utilisation, so the established method solves it (H3) |
| **H** sample size | B2 at T = 192 on both networks (40 envelope solves), and at T = 768 on rural3 P1 (+384 training solves, +20 envelope solves) | The effect vanishes at T = 768 |
| **I** measurement noise | B2 at σ_v ∈ {0.0005, 0.005} for P1 and P3 (160 envelope solves) | The effect vanishes at σ_v = 0.0005 |
| **J** decision equivalence | The proportional-fair objective (B2p) and §8's proportional-fair alternatives | — |
| **K** time-shuffled training (NC4) | B2 refitted with V shuffled across training time against P (zero AC solves): test-day MAE and coefficient norm only | A shuffled model predicting as well as B2 means leakage or a degenerate target |
| **T** full decision | §6 control T | — (bounds practical relevance) |
| **L0** load excitation | P1's PV with native loads, all seven data-driven methods, R = 1 | P1 is safe *because* of load excitation: L0 unsafe while P1 is safe |

---

## 11. Leakage rules

- Deployable methods see **only**: training-day smart-meter P **and Q**, noisy V, topology, and line and transformer ratings (ratings in control T only).
  - Never the true r and x.
  - Never test-day, deployment-condition or oracle outcomes.
  - Never the regime label.
- Ridge λ, B2m's conformal margin and B4's radius come from training data alone. B2m's held-out day 155 is part of the training window.
- Deployment conditions are selected by the offline no-action AC power flow, which does not depend on any method.
- The deployment set and its pairing are written to a selection record **before any envelope is computed**.

---

## 12. Compute budget and ledger (ceiling 8,000 new AC solves)

| Item | Solves |
|---|---|
| Board design audits (done; `docs/provenance/mission11_board_audit/`) | 106 |
| Training and test physics: 4 regimes (P1, P2, P3, L0) × 2 networks × 480 steps | 3,840 |
| Sample-size extension (rural3, P1, days 132–135) | 384 |
| Deployment selection: 2 networks × (40 near + 40 far candidates) | 160 |
| e = 0 vertex (method-independent): 20 conditions × 2 networks | 40 |
| Envelopes, data-driven: 7 methods (B1, B2, B2m, B2p, B3, B4box, B4) × R = 2 × 20 conditions × 3 regimes × 2 networks | 1,680 |
| Envelopes, L0 control: 7 × R = 1 × 20 × 2 | 280 |
| B0, Method A and Method A′: 3 × 20 × 2 | 120 |
| Oracle B5, near set: ≤ 6 sequential-LP + ≤ 8 bisection = ≤ 14 × 10 × 2 | 280 |
| Control H (T = 192: 40; T = 768: 20) | 60 |
| Control I (2 σ × 2 regimes × 20 × 2) | 160 |
| Ambiguity, AC-scored (§8) | 320 |
| §15 monotonicity check: 1 interior point × 20 conditions × 2 networks, oracle envelope (= a on the far set) | 40 |
| Control T (full decision): B2 × R = 2 × 10 near × 2 regimes × 2 networks | 80 |
| B4box-OLS secondary arm: R = 2 × 10 near × 2 regimes × 2 networks | 80 |
| **Planned total (upper bound)** | **7,630** |
| **Reserve** (convergence failures, pilot overrun) | 370 |

**Rules for the budget:**
- **Upper bounds.** Envelopes equal to a are scored by the selection solve (§6), and the oracle may stop early. Actual counts are recorded.
- **Cut order if the pilot forecasts an overrun:**
  0. the monotonicity check on semiurb5 only (−20);
  1. control I on semiurb5 only;
  2. R = 1 for P2;
  3. the B4box-OLS arm;
  4. the T = 768 extension.
- **One worker.** The sandbox blocks multiprocessing.
- **Expected CPU:** about 1–2 minutes of solves at 6 ms each, plus a few minutes of bootstrap refits and cutting planes.
- **Storage:** float32 voltages, in megabytes.
- **Ledger:** every solve-running function increments a ledger written into its artefact. The cumulative total, starting at 106, is asserted ≤ 8,000 before every stage.
- **Non-convergence:** recorded as failed and **never scored as safe**. More than 2 % failures in any stage means NOT EVALUABLE for that stage.

---

## 13. Seeds, splits and tolerances

- **Seeds:** SeedSequence([20261025, stable_int(network), stable_int(regime), stable_int(purpose), replicate]), with `stable_int` = `gridpulse.sensing._stable_int`.
  - "purpose" is one of: `pv_orientation`, `pv_cloud`, `load`, `noise`, `bootstrap`, `radius_refit`, `ambiguity_refit`, `rand_fallback`, `shuffle`, `interior_point`.
  - The load seed uses the regime label "common", so loads are identical across P1–P3.
- **Splits:**
  - training: days 152–155 (B2m: ridge on 152–154, conformal on 155);
  - test: day 156;
  - extension: days 132–135;
  - deployment: days 160–199.
- **Tolerances:**
  - AC: pandapower defaults, Newton–Raphson;
  - voltage-unsafe: +0.001 pu;
  - thermal-unsafe (control T and e = 0): +0.5 %;
  - linprog: HiGHS defaults; stage-2 total within 1e-6 MW;
  - robust cutting plane: 1e-6 pu, at most 60 rounds, then uniform restoration;
  - rank and eigenvalue tolerance: 1e-10 relative.

---

## 14. QA plan

- **Pre-experiment:** one independent review of revision 1 (Paperclip AKK-58, GridPulse QA, sandboxed): physical validity, statistics, leakage, baseline strength, the plausibility of the shifts, decision relevance, compute and falsifiability. Its confirmed corrections and the board audit's findings are applied in this revision 2 and listed in the drafting record.
- **Post-experiment:** one independent review of code, protocol compliance, numbers, statistics, claims and public-repository hygiene. **It must specifically check:**
  - the revision 2 decisions that departed from the pre-experiment review's own proposals (the drafting record, items marked *modified*);
  - the voltage-component framing (F0).

  One correction round. No loops.

## 15. Stop conditions

Stop expanding, and report, if any of these happens:
- **fewer than 10 near candidates pass the §5 voltage screen on a network.**
  - H1–H3 are NOT EVALUABLE on that network; nothing that needs "both networks" can be Supported.
  - The remaining network's results are still reported.
- **the binding-constraint diagnostic (§9)** puts B5's (V) rows active on fewer than 7 of 10 near conditions on a network: H1–H3 are NOT EVALUABLE there.
- **the AC power flow fails on > 2 % of a stage.**
- **the corner-monotonicity assumption fails in AC.** An interior point, sampled uniformly from [0, e] for the oracle's envelope, violates the upper voltage limit while the corner does not (1 point per condition per network).
- **the regime generator produces implausible injections** (above rating, or negative PV).
- **the ledger would exceed 8,000.**
- **Method A′ is unsafe on > 5 of 10 near conditions on either network** (Method A reported alongside).
  - Linear modelling with a learned offset is then inadequate for this decision. The study reports that instead of attributing failures to identification.
  - Between 3 and 5, the attribution rule of control A′ applies and the result is labelled linearisation-sensitive.

A negative result still runs its diagnostics (controls and ambiguity) to explain itself.

## 16. Public hygiene

- **New fixtures** use genuinely synthetic electrical parameters (round values with a documented origin). No SimBench or IEEE parameter values are copied into code, tests or docs.
- **Derived arrays and results stay local** (SimBench is ODbL 1.0 / DbCL 1.0).
  - The board audit record in `docs/provenance/mission11_board_audit/` quotes aggregate figures only.
- **Not touched:** the frozen Mission 10 protocol and its tests.

## 17. Implementation clarifications (revision 2.1, before any scored solve)

These fix choices the sections above leave open. None changes a hypothesis, threshold or ledger line.

1. **f(t):**
   - f(t) is the unit-weighted mean over the network's PV units of min(1, g_i(t)), where g_i is the unit's native series divided by its rating.
   - "Total base availability" at a step is f(t)·Σr_i.
   - "Daylight" means f(t) ≥ 0.01.
2. **Generated series:**
   - PV and load series are generated over the full year, so every split and every deployment step comes from one realisation per seed.
   - **L0 uses P1's PV seeds** (regime label "P1" for `pv_orientation` and `pv_cloud`), so that L0 differs from P1 only in its training loads.
3. **Noise:**
   - per (network, regime, replicate), z ~ N(0, 1) is drawn for every step of the year and every customer bus, from purpose `noise`;
   - the measured voltage is v + σ_v·z. Every σ_v level uses the same z (common random numbers across control I).
4. **Training subsets:**
   - control H's T = 192 uses days 152–153;
   - T = 768 uses days 132–135 plus 152–155;
   - cross-validation always has one fold per training day.
5. **Method A′'s intercept** is fitted on regime P1, replicate 0. A′ is therefore one envelope per condition.
6. **Ambiguity alternatives (§8) and CERT** use replicate 0. CERT, ALWAYS and RAND are evaluated on replicate 0's B2 and B2p envelopes, so that n is the number of conditions.
7. **The deployment selection record** stores, per network, for every candidate:
   - the step;
   - f(t);
   - the no-action maximum voltage exceedance at customer buses and at all LV buses;
   - the line and transformer loadings;
   - whether the step passed the near screen.

## Drafting record (before any scored solve)

**Revision 1** (sha256 `c93584ae7dc432bc796343af302ee9df563221141d2dc33ae6280021d4a23730`) was reviewed in Paperclip AKK-58. **Verdict: PROCEED WITH CORRECTIONS** (4 blockers, 15 major, 11 minor).

In parallel, the board ran design audits (86 solves beyond the 20-solve pilot). They found:
- the unspecified storage dispatch (§2);
- F0, thermal-first in all six networks (§2).

**Revision 2** applies the following. *Accepted* means as proposed by the review. *Modified* means the review's concern is accepted but the remedy differs, for the reason given.

**Blockers**

| Item | Disposition | What was done |
|---|---|---|
| **B1** near set thermally clamped | **Modified** | The review proposed a thermal screen on the near set. The board audit showed it would empty the near set on every network: peak no-action thermal loading is 122–141 % on all six. Instead:<br>• F0 is recorded;<br>• the primary decision is the voltage component;<br>• the networks were reselected by a voltage-limited rule (urban6 → semiurb5);<br>• a voltage screen was added to the near set;<br>• the binding diagnostic and the §15 rules were added as proposed;<br>• control T measures the full decision.<br>The PV scale is unchanged, so no owner decision is needed. |
| **B2** B4/B4box undefined on a rank-deficient design | **Modified** | B4box is on the ridge fit, with the sandwich variance, as proposed; B4box-OLS is a secondary arm. B4 is centred on the ridge fit with metric X̃ᵀX̃ + Λ, which is positive definite, instead of δI plus a sign constraint: the sign-constrained ellipsoid needs a conic solver, which the environment lacks. `robust-degenerate` and the H3 rejection branch were added as proposed. |
| **B3** F/χ² set | **Modified** | No F/χ² radius. A day-block bootstrap has only 4 blocks, and the Bonferroni quantile 1 − α/K cannot be estimated from 400 refits. B4's radius therefore comes from a 16-step moving-block bootstrap with a simultaneous max-statistic. The F radius is a diagnostic only. |
| **B4** unobtainable random alternatives | **Modified** | Random alternatives are bootstrap refits of a non-negative ridge, admissible by construction (no QP, no rejection sampling). H4 is on random alternatives only, as proposed; the extremes are an upper bound with no verdict. Because the alternatives come from B2's ridge, CERT is gated by B2's own uncertainty (m7). |

**Major findings**

| Item | Disposition | What was done |
|---|---|---|
| **M1** undeclared departures | Accepted | Rows added to §0. |
| **M2** conformal margin | Accepted with a cut | Accepted as proposed, except that B2m-insample is reported as a margin diagnostic without AC solves, for budget. |
| **M3** detectable effect | Accepted | The arithmetic was re-derived for both Holm levels. |
| **M4** Holm family | Accepted | Enumerated in §9. |
| **M5** H2 cells | Accepted | 9 cells. |
| **M6** Q for B3 | Accepted | Q is measured exactly. |
| **M7** thermal module bias | Accepted | κ = 0.95, now in control T only. |
| **M8** tie-break | Accepted with L1 | Stage 2 uses an L1 proportionality objective instead of the proposed quadratic one, so it stays an LP. |
| **M9** e = 0 vertex | Accepted | The interior check is on the oracle envelope. |
| **M10** A′ | Accepted | |
| **M11** control C | Modified | Per-unit KS is not a pass criterion. The cloud factor σ_c widens each unit's marginal by construction, the same argument the review made for the total distribution. The criterion is the per-unit mean (1 %) plus the median relative P95 difference (10 %); KS, maxima and the corner distance are reported. |
| **M12** paired utilisation | Accepted | |
| **M13** P3 realism; smooth-component shift | Accepted | |
| **M14** audit artefact | Accepted | Placed under `docs/provenance/` following the repository's convention for verbatim audit scripts. |
| **M15** ledger | Accepted and extended | B5 runs on the near set only; the B4box-OLS arm and control T were added; total 7,630, reserve 370. |

**Minor findings**

| Item | Disposition | What was done |
|---|---|---|
| m1, m2, m3, m4, m5, m6, m8, m9, m10, m11 | Accepted | Counts checked by zero-solve audit: 118 and 104 customer buses; every PV bus is a customer bus; voltage limits uniform. |
| m7 | Accepted | Via B4. |

**Revision 2.1** (before any scored solve) was prepared while writing the runner specification. It:
- adds §17's implementation clarifications;
- corrects §5 so that L0's deployment loads are the common synthetic loads (exact pairing). Revision 2 had said native loads, which would have changed L0's deployment conditions.

Revision 2 was `cf91ac42a8c72bdce7d9af05551889d1e533e9b8694d1daa5b6b73cb51d083e5`.

**Revision 2.2** (before any scored solve) fixes B4's cut budget. Implementation task 1b (Paperclip AKK-60) found that revision 2's "at most 200 cuts", counted per added row, is exhausted in two rounds at K = 118. Nearly converged problems would then have been recorded as `robust-degenerate`, which would have fed H3's rejection branch on a numerical artefact.
- A board benchmark on the synthetic K = 118 chain needed 37–841 rounds to converge to 1e-6 pu.
- 60 rounds followed by uniform restoration left an optimality gap of at most 0.3 %.
- The budget is therefore 60 rounds plus restoration, with the gap reported.

Revision 2.1 was `73442eaf3413c49164bf317ca1f87db6cc212c1cbb6e694f2de97944bfd75da0`.

**Hashes**
- Each revision's sha256 is recorded in the Paperclip issue that dispatches implementation, and in the final report. A file cannot contain its own hash.
- The design input remains `dc214c37…`.

## Amendments (after the first scored solve)

The first counted experimental solve was semiurb5 `physics` (Paperclip AKK-61, 2026-10-24). These amendments are dated board decisions. Everything above them is unchanged, and the as-executed text of revision 2.2 is recovered by replacing this section's body with "(none)".

**A1 (2026-10-25; AKK-61, AKK-62) — far candidates on days without f ≥ 0.2.**
- §5 assumed every deployment day has a step with f ≥ 0.2. On semiurb5, days 163, 171, 175, 178 and 199 have none; on rural3, days 165, 171, 172, 175 and 178 have none.
- Such a day contributes **no** far candidate. 35 remain on each network, well above the 10 needed.
- The first semiurb5 `select` aborted on the assumption after 43 solves. They are counted, and no selection was produced. One corrected run followed (87 solves).

**A2 (2026-10-25; AKK-62, AKK-63) — §15 triggered on semiurb5.**
- Only 2 of 40 near candidates exceed +0.001 pu: day 172 (+0.00418) and day 182 (+0.00409); the next is day 173 (+0.00093). The threshold is **not** changed.
- **Consequences:**
  - H1–H3 are NOT EVALUABLE on semiurb5;
  - no verdict that requires "both networks" can be Supported;
  - verdicts are reported for rural3, the evaluation network, as single-network results, as §15 provides.
- semiurb5 continues as the **descriptive development pilot** on its 2 near and 10 far conditions, so that the envelope, oracle and control code runs before the frozen rural3 run.
- The rural3 `select` (method-independent, the frozen selection code) was run before any further implementation, to establish that rural3 is near-evaluable. It is: 11 of 40 survive, and the top 10 are used.

**A3 (2026-10-25; AKK-65) — rural3 `physics` interrupted; a resume path is added before any rural3 method stage.**
- The Implementer started rural3 `physics` as a background job and ended its run. The Paperclip adapter then terminated the process (SIGTERM, exit 143) during regime L0, after P1 (864 solves, including the 384-step extension), P2 (480) and P3 (480) had been written.
- No L0 artefact or abort record was written, because SIGTERM bypassed the abort handler. The board charged the full 480 L0 solves to the ledger as an upper bound (`results/abort_physics_rural3_L0_sigterm.json`); about 240 had probably run.
- **The change.** Before any rural3 method stage, the frozen runner is changed in exactly two ways that touch no method code:
  1. `physics --resume` verifies an existing regime artefact by regenerating its PV and load series deterministically (zero solves; the stored arrays must match exactly) and skips it, then solves only the missing regime;
  2. SIGTERM is converted into an exception, so an interrupted stage writes its abort record.
- **The rerun.** L0 is solved again from the start (480 more solves).
- **The freeze** is re-established at new hashes recorded in the final report.
- At the time of the change, no rural3 envelope, oracle or control result existed. The only rural3 outputs were the method-independent selection and the P1–P3 physics.
