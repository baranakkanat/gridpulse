# Mission 11 Stage A: board design audit (before any scored solve)

**Data attribution:** contains information from [SimBench](https://simbench.de), which is made available here under the [Open Database License (ODbL 1.0)](https://opendatacommons.org/licenses/odbl/1-0/). See [`analysis/export_envelope_shift/DATA_ATTRIBUTION.md`](../../../analysis/export_envelope_shift/DATA_ATTRIBUTION.md).

These scripts were run by the board on 2026-10-24, before any scored solve, to fix the facts in §2 of `analysis/export_envelope_shift/stage_a_protocol.md`.
- **Kept verbatim** apart from one edited line per script: the `sys.path.insert` line originally held an absolute local path and now resolves `src/` relative to the file. It is marked `# edited`.
- **Lint:** excluded, like the other archived audit scripts under `docs/provenance`.
- **Re-running** the scripts that solve power flows would cost new AC solves, and those would have to be counted in the Mission 11 ledger.
- **Outputs:** quoted below as printed. SimBench-derived figures are aggregates only; no SimBench parameter values are reproduced.

## Solve ledger: 106 counted AC solves

| Script | Solves | Status | What it measured |
|---|---|---|---|
| `audit_nets.py` | 0 | valid | profile types, PV correlation, effective rank, condition number, limits |
| `audit_pilot.py` | 20 | valid (storage passed as 0 MW) | solve speed; no-action margins, urban6 day 172 and rural3 day 174 |
| `audit_binding.py` | 36 | **invalid**: SimBench's default storage dispatch was left in the network | binding constraints at the true-model envelope optimum (6 networks) |
| `audit_dbg.py` | 2 | diagnostic | traced the invalid run's transformer loading to the default storage dispatch |
| `audit_binding2.py` | 12 | valid (storage 0 MW) | `audit_binding.py`, repeated on rural3 and urban6 |
| `audit_binding3.py` | 18 | valid | adds the worst thermally feasible allocation at the same total, and θ_T and θ_V |
| `audit_regime.py` | 18 | valid | voltage- against thermal-limited regime, 6 networks, days 100–131 |
| `audit_switch.py`, `audit_st.py`, `audit_counts.py`, `audit_defs.py` | 0 | valid | switches, storage defaults, bus and unit counts, limit definitions |

**Days touched.**
- `audit_pilot.py` and `audit_binding*.py` used days in the deployment window: 160, 165, 172, 174, 180 and 188. They used AC truth only, never a method. This is the same information the method-independent deployment selection uses.
- `audit_regime.py` used days 100–131, which lie outside every Mission 11 split.

## Outputs

**`audit_nets.py`** (zero solves; native SimBench PV profiles, daylight steps of the year):
```
rural1   PV types {PV8:3, PV6:3, PV5:2}            mean pair corr 0.8765  eff.rank 1.44  cond 3.19e+14
rural2   {PV3:5, PV4:3, PV7:2, PV1:1}              0.8584  1.59  3.8e+14
rural3   {PV1:9, PV3:7, PV4:6, PV7:5}              0.8228  1.73  5.81e+14
semiurb4 {PV5:6}                                   1.0000  1.00  2.82e+14
semiurb5 {PV5:5, PV2:4, PV8:4, PV6:2}              0.8382  1.63  4.38e+14
urban6   {PV8:7, PV2:2, PV5:2, PV6:1}              0.8302  1.60  3.92e+14
```

**`audit_pilot.py`** (20 solves; margins [vmax, vmin, line %, trafo %]; storage at 0 MW):
```
urban6 day 172 steps 40..49  6.3 ms/solve  customer buses 53   max margins [-0.0004, -0.1533, +26.09, -29.49]
rural3 day 174 steps 40..49  6.2 ms/solve  customer buses 118  max margins [+0.0067, -0.1551, -4.92, +32.30]
```

**`audit_binding2.py` / `audit_binding3.py`** (storage at 0 MW):
- Envelope LP: maximise Σe with true balanced LinDistFlow voltage sensitivities and the lossless P-only thermal module.
- Results at the LP optimum:
  - the thermal row is active and **no voltage row is active**;
  - AC voltage margin at the solver's allocation: −0.013 pu in 5 of 6 conditions, +0.0005 in 1.
- Worst thermally feasible allocation at the same total, then AC-checked:

| Network | Linear model (pu) | AC (pu) | Verdict |
|---|---|---|---|
| rural3 | +0.0013 to +0.0020 | +0.0032 to +0.0041 | voltage-unsafe is possible only through the allocation |
| urban6 | −0.013 | −0.011 | voltage-unsafe is impossible for every method |

- θ_T (thermal) against θ_V (voltage):

| Network | θ_T | θ_V |
|---|---|---|
| rural3 | 0.73–0.74 | 0.89–0.91 |
| urban6 | 0.76–0.78 | 1.00 |

**`audit_regime.py`** (18 solves; no action at the peak-availability step; days 100–131; storage 0 MW):
```
rural1   vmarg -0.0657..-0.0672  line 37–40 %   trafo 135–141 %  thV 1.00       thT 0.71–0.74
rural2   vmarg -0.0090..-0.0100  line 86–88 %   trafo 129–130 %  thV 1.00       thT 0.77–0.78
rural3   vmarg +0.0029..+0.0051  line 86–93 %   trafo 122–126 %  thV 0.92–0.96  thT 0.79–0.82
semiurb4 vmarg -0.0073..-0.0134  line 129–130 % trafo 69–75 %    thV 1.00       thT 0.77
semiurb5 vmarg -0.0006..+0.0045  line 122–130 % trafo 85–96 %    thV 0.95–1.00  thT 0.77–0.82
urban6   vmarg -0.0001..+0.0019  line 125–128 % trafo 68–71 %    thV 0.97–1.00  thT 0.78–0.80
```
In every network θ_T < θ_V: **thermal limits bind before voltage** at the registered 1.40× scale.

**`audit_st.py`, `audit_counts.py`, `audit_defs.py`, `audit_switch.py`** (zero solves):

| | rural3 | semiurb5 | urban6 |
|---|---|---|---|
| Storage units | 16 | 15 | 7 |
| Default storage dispatch (MW) | −0.093 | not printed | −0.051 |
| Customer buses (each carries a SimBench load) | 118 | 104 | 53 |
| PV units, each on its own customer bus | 27 | 15 | 12 |

- **Storage:** the default dispatch is non-zero and discharging.
- **Customer buses:** the trafo LV busbar is not one.
- **Voltage limits:** `max_vm_pu` = 1.10 and `min_vm_pu` = 0.90 at every customer bus, and min(`max_vm_pu`) over all LV buses is also 1.10.
- **Switches:** none open in rural3, urban6 or semiurb4. No line has `parallel` > 1.

## Post-run board recomputations (zero solves, 2026-10-25)

These two scripts read the local Stage A artefacts and refit models. They run **no** power flow. They are the source of the research note's §VI utilisation column (safe-only medians), §VII's per-unit sensitivity errors and §XVI's negative-coefficient share. Re-run them from the repository root.

**`board_refit_sensitivity.py`**
- **What it does:** refits B2 (ridge, the same cross-validation as the runner) and B1 (OLS) on rural3, replicate 0, and compares the learned PV-export sensitivities (customer bus × PV unit, 118 × 27 = 3,186 entries) with the true balanced LinDistFlow sensitivities.
- **Measures:**
  - the aggregate ratio at the bus with the largest true aggregate sensitivity;
  - the relative Frobenius error;
  - the number of negative entries.

```
P1 ridge lam   215.9  remote-bus aggregate ratio 1.163  rel Frobenius err 0.889  negative entries 4/3186
P1 ols   lam   215.9  remote-bus aggregate ratio -0.149  rel Frobenius err 8.673  negative entries 1451/3186
P2 ridge lam   215.9  remote-bus aggregate ratio 1.199  rel Frobenius err 0.874  negative entries 3/3186
P2 ols   lam   215.9  remote-bus aggregate ratio 0.880  rel Frobenius err 3.612  negative entries 1328/3186
P3 ridge lam   215.9  remote-bus aggregate ratio 1.225  rel Frobenius err 0.857  negative entries 14/3186
P3 ols   lam   215.9  remote-bus aggregate ratio 0.941  rel Frobenius err 1.954  negative entries 1199/3186
L0 ridge lam    68.3  remote-bus aggregate ratio 1.224  rel Frobenius err 0.903  negative entries 18/3186
L0 ols   lam    68.3  remote-bus aggregate ratio 2.191  rel Frobenius err 10.055  negative entries 1462/3186
```

**`board_utilisation.py`**
- **What it does:** per method and regime on rural3's near set, it reports:
  - the number of conditions with at least one unsafe replicate;
  - the median companion utilisation (unsafe = 0);
  - the median utilisation over conditions safe in both replicates;
  - the maximum exceedance;
  - the mean exceedance of unsafe records.
- **Source:** `envelopes_rural3.json` and `oracle_rural3.json`. Run it to reproduce the table.

**The corner prediction error in §VII** (mean of AC max corner voltage − the method's own predicted max) comes directly from `envelopes_rural3.json` (`max_exceedance + 1.10 − predicted_corner_vm`, mean over near records). The post-experiment QA (AKK-68) recomputed it independently.
