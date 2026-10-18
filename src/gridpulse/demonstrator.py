"""Phase 7 offline engineering demonstrator (EXPLORATORY; docs/phase7_results.md).

One static HTML page for one SimBench network and model-error truth. It shows what an
engineer would want to inspect: which quantities are measured and which are not, the true
(simulated) signed margins at one critical quarter-hour, what the operator's model-residual
estimates were at that time, and how three policies decided, next to the frozen Phase 7
evaluation totals. The re-run uses the frozen policy code and is checked against the frozen
outputs. Synthetic benchmark data only; not a control system and not a safety assessment.
"""

from __future__ import annotations

import html
import json
import math
from pathlib import Path

import numpy as np

from gridpulse import dual_study as ds
from gridpulse import margin_study as ms
from gridpulse import margins as mg
from gridpulse import noise_study as ns
from gridpulse import sensing as sn
from gridpulse.grid_study import CAP_LEVELS, FIRST_DAY

P4 = Path("outputs/dual_study/physics_cache")
FS = Path("outputs/sense_study/fullstate_cache")
DESIGN = Path("outputs/noise_study/development_results.json")
FROZEN = Path("outputs/margin_study/evaluation_results.json")
POLICIES = (  # (label, frozen key, configuration, condition, kind)
    ("B2 binary alarms, substation only", "B2/0", "substation", "realistic", "binary"),
    ("B3 binary alarms, + 2 meters, exact readings", "B3/0", ms.T2, "exact", "binary"),
    ("C1 continuous residual correction, substation only", "C1/0", "substation", "realistic",
     "corrected"),
)  # fmt: skip


def _positions(net, buses) -> dict[int, tuple[float, float]]:
    """SVG coordinates of LV buses from the benchmark's (synthetic) geodata."""
    points = {b: json.loads(net.bus.at[b, "geo"])["coordinates"] for b in buses}
    xs, ys = np.array([p[0] for p in points.values()]), np.array([p[1] for p in points.values()])
    span = max(np.ptp(xs), np.ptp(ys), 1e-9)
    return {b: (30 + 360 * (p[0] - xs.min()) / span, 30 + 360 * (ys.max() - p[1]) / span)
            for b, p in points.items()}  # fmt: skip


def scenario(code: str, truth: str) -> dict:
    """Re-run three frozen policies for one network and truth (evaluation half) and collect
    one critical quarter-hour; verify the re-run against the frozen evaluation outputs."""
    placements = json.loads(DESIGN.read_text())["placements"][code]
    contexts, layout, facts = sn.build_contexts(code, P4, FS, "evaluation", truths=(truth,))
    ctx = contexts[truth]
    raw = ms.plan_raw(code, P4)
    n_lines = ctx.states[ctx.days[0]]["line"].shape[2]
    configs = ns.configurations(layout, n_lines, placements)
    online = ds.OnlineSettings()
    margin = mg.tuned_safety_margin(raw, ctx.available, list(ctx.development), online.beta)
    frozen = json.loads(FROZEN.read_text())[code][truth]["runs"]
    runs = {}
    for label, key, config, condition, kind in POLICIES:
        trace: dict = {}
        model, bank = ns.CONDITIONS[condition], sn.NoiseBank(code, truth, 0)
        if kind == "binary":
            records = sn.run_feedback_policy(
                ctx, "replay_aci", configs[config], model, 0, online, noise=bank,
                alarm=ns.RULES["unfiltered"], trace=trace,
            )  # fmt: skip
        else:
            settings = mg.CorrectorSettings(safety_margin=margin)
            corrector = mg.ResidualCorrector(
                raw, ctx.nominal_states, layout, configs[config], model, settings
            )
            records = sn.run_feedback_policy(
                ctx, "replay_robust", configs[config], model, 0, online, noise=bank,
                alarm=ns.RULES["unfiltered"], corrector=corrector, trace=trace,
            )  # fmt: skip
        violations = sum(r["avoidable_violation_steps"] for r in records)
        mwh = sum(r["curtailed_mwh"] for r in records)
        if violations != frozen[key]["avoidable_violation_steps"] or not math.isclose(
            mwh, frozen[key]["curtailed_mwh"], rel_tol=1e-9, abs_tol=1e-9
        ):
            raise RuntimeError(f"re-run of {key} does not reproduce the frozen evaluation")
        runs[label] = {"records": {r["day"]: r for r in records}, "trace": trace, "key": key,
                       "config": configs[config]}  # fmt: skip

    def no_action_violations(d):
        events = sn.true_events(ctx.truth_norm[d], ctx.states[d], 0, layout)
        return int((events["any"] & (ctx.available[d].sum(axis=1) > 0)).sum())

    day = max(ctx.days, key=no_action_violations)  # ties: earliest day
    state = ctx.states[day]
    daylight = ctx.available[day].sum(axis=1) > 0
    # largest normalised exceedance at no action (positive = violation), daylight only
    step = int(np.argmax(np.where(daylight, ctx.truth_norm[day][:, 0], -np.inf)))
    net = ds.variant_network(code, ds.NOMINAL, ds.pv_scale(code))
    v_min = net.bus.loc[list(layout.buses), "min_vm_pu"].to_numpy(dtype=float)
    v_max = np.array(layout.max_vm)
    out = {
        "network": code, "truth": truth, "day": day, "step": step,
        "timestamp": (FIRST_DAY + np.timedelta64(int(day), "D")
                      + np.timedelta64(15 * step, "m")).strftime("%Y-%m-%d %H:%M UTC"),
        "positions": _positions(net, layout.buses),
        "edges": [(int(r.from_bus), int(r.to_bus), int(i)) for i, r in net.line.iterrows()],
        "busbar": layout.lv_busbar, "heads": list(layout.feeder_heads),
        "meters": list(placements["topology"][:2]), "buses": list(layout.buses),
        "lines": n_lines, "safety_margin": margin,
        "frozen": {key: frozen[key] for key in ("B2/0", "B3/0", "C1/0", "oracle")},
        "panels": {}, "policies": [],
    }  # fmt: skip

    def panel(level: int) -> dict:  # true signed margins at the chosen step and cap level
        return {
            "vm_margin": mg.voltage_margin(state["vm"][step, level], v_min, v_max).tolist(),
            "line_margin": mg.loading_margin(state["line"][step, level]).tolist(),
        }

    def violated(levels) -> list[bool]:  # avoidable true violation per quarter-hour
        norm = ctx.truth_norm[day]
        hit = (norm[np.arange(len(levels)), levels] > 0) & (norm <= 0).any(axis=1) & daylight
        return hit.tolist()

    out["daylight"] = daylight.tolist()
    none = np.zeros(len(daylight), dtype=int)
    out["timeline"] = {"No action": {"levels": none.tolist(), "violated": violated(none)}}
    out["panels"]["No action (true state)"] = panel(0)
    for label, run in runs.items():
        level = int(run["trace"][day][step])
        record = run["records"][day]
        out["panels"][f"{label.split(' ')[0]} decision (true state)"] = panel(level)
        levels = np.asarray(run["trace"][day], dtype=int)
        out["timeline"][label.split(" ")[0]] = {
            "levels": levels.tolist(),
            "violated": violated(levels),
        }
        out["policies"].append({
            "label": label, "key": run["key"], "cap_level": level,
            "cap_fraction": float(CAP_LEVELS[level]),
            "day_violations": record["avoidable_violation_steps"],
            "day_mwh": record["curtailed_mwh"],
            "estimates": {k: record[k] for k in ("v_hat", "rho_line", "rho_trafo")
                          if k in record},  # fmt: skip
            "label_in_force": mg.evidence_label(record) if "v_hat" in record else "—",
            "meters": len(run["config"].voltages),
        })  # fmt: skip
    return out


def _colour(margin: float, warn: float) -> str:
    if not np.isfinite(margin):
        return "#888888"
    if margin < 0:
        return "#c0392b"
    return "#e67e22" if margin < warn else "#2e8b57"


def _panel(sc: dict, title: str, panel: dict) -> str:
    pos, cols = sc["positions"], {b: i for i, b in enumerate(sc["buses"])}
    parts = [f'<svg viewBox="0 0 420 420" width="310" height="310" role="img" '
             f'aria-label="{html.escape(title)}"><text x="10" y="18" font-size="13" '
             f'font-weight="bold">{html.escape(title)}</text>']  # fmt: skip
    for a, b, i in sc["edges"]:
        if a in pos and b in pos:
            (x1, y1), (x2, y2) = pos[a], pos[b]
            colour = _colour(panel["line_margin"][i], 10.0)
            width = 3 if i in sc["heads"] else 1.5
            parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                         f'stroke="{colour}" stroke-width="{width}"/>')  # fmt: skip
    for b, (x, y) in pos.items():
        colour = _colour(panel["vm_margin"][cols[b]], 0.01)
        if b == sc["busbar"]:
            parts.append(f'<rect x="{x - 7:.1f}" y="{y - 7:.1f}" width="14" height="14" '
                         f'fill="{colour}" stroke="black" stroke-width="2"/>')  # fmt: skip
        else:
            ring = ' stroke="black" stroke-width="2.5"' if b in sc["meters"] else ""
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{colour}"{ring}/>')
    parts.append("</svg>")
    return "".join(parts)


def _timeline(sc: dict) -> str:
    """Cap depth (bar height) and true avoidable violations (red) per daylight quarter-hour."""
    steps = [t for t, d in enumerate(sc["daylight"]) if d]
    if not steps:
        return ""
    first, last = steps[0], steps[-1]
    width, row = 12, 34
    rows = list(sc["timeline"].items())
    total_w = 120 + width * (last - first + 1) + 10
    parts = [f'<svg viewBox="0 0 {total_w} {row * len(rows) + 30}" width="{total_w}" '
             f'height="{row * len(rows) + 30}" role="img" aria-label="Cap and violation '
             f'timeline">']  # fmt: skip
    for r, (name, entry) in enumerate(rows):
        y0 = 10 + r * row
        parts.append(f'<text x="0" y="{y0 + 20}" font-size="12">{html.escape(name)}</text>')
        for t in range(first, last + 1):
            x = 120 + (t - first) * width
            level = entry["levels"][t]
            h = 24 * level / (len(CAP_LEVELS) - 1)
            parts.append(f'<rect x="{x}" y="{y0 + 24 - h:.1f}" width="{width - 1}" '
                         f'height="{h:.1f}" fill="#5b7db1"/>')  # fmt: skip
            if entry["violated"][t]:
                parts.append(f'<rect x="{x}" y="{y0 + 25}" width="{width - 1}" height="4" '
                             f'fill="#c0392b"/>')  # fmt: skip
    for t in range(first + (-first) % 8, last + 1, 8):  # every two hours on the hour
        x = 120 + (t - first) * width
        parts.append(f'<text x="{x}" y="{row * len(rows) + 25}" font-size="10">'
                     f'{t // 4:02d}:00</text>')  # fmt: skip
    if first <= sc["step"] <= last:
        x = 120 + (sc["step"] - first) * width + width / 2
        parts.append(f'<line x1="{x}" y1="4" x2="{x}" y2="{row * len(rows) + 12}" '
                     f'stroke="black" stroke-dasharray="3,2"/>')  # fmt: skip
    parts.append("</svg>")
    return "".join(parts)


def render(sc: dict) -> str:
    """Static HTML for a scenario dict (pure; testable without caches)."""
    e = html.escape
    worst = {t: (min(p["vm_margin"]), min(p["line_margin"])) for t, p in sc["panels"].items()}
    rows = "".join(
        f"<tr><td>{e(t)}</td><td>{v:+.4f}</td><td>{ln:+.1f}</td></tr>"
        for t, (v, ln) in worst.items()
    )
    policies = "".join(
        f"<tr><td>{e(p['label'])}</td><td>{p['meters']}</td>"
        f"<td>{p['cap_level']} ({100 * p['cap_fraction']:.0f} % of PV rating)</td>"
        f"<td>{p['day_violations']}</td><td>{p['day_mwh']:.2f}</td>"
        f"<td>{e(', '.join(f'{k} {v:+.4f}' for k, v in p['estimates'].items()) or '—')}</td>"
        f"<td>{e(p['label_in_force'])}</td></tr>"
        for p in sc["policies"]
    )
    frozen = "".join(
        f"<tr><td>{e(k)}</td><td>{v['avoidable_violation_steps']:.0f}</td>"
        f"<td>{v['curtailed_mwh']:.1f}</td><td>{'yes' if v['meets_beta'] else 'no'}</td></tr>"
        for k, v in sc["frozen"].items()
    )
    panels = "".join(_panel(sc, t, p) for t, p in sc["panels"].items())
    unmetered = len(sc["buses"]) - 1 - len(sc["meters"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GridPulse demonstrator: {e(sc["network"])}, {e(sc["truth"])}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1350px;margin:16px auto;padding:0 16px;
color:#222;background:#fff}}table{{border-collapse:collapse;margin:8px 0 16px}}
td,th{{border:1px solid #ccc;padding:4px 8px;font-size:14px;text-align:left}}
.panels{{display:flex;flex-wrap:wrap;gap:8px}}.note{{background:#fff4e5;border:1px solid #e67e22;
padding:8px 12px}}</style></head><body>
<h1>GridPulse demonstrator (exploratory)</h1>
<p class="note"><b>Exploratory research demonstrator.</b> Synthetic SimBench benchmark network
and 2016 profiles; simulated measurements; one assumed model error. Not a control system, not a
safety assessment, not evidence about any real feeder. Ground truth is shown for evaluation only;
the operator's policies never see it.</p>
<h2>Scenario</h2>
<p>Network <b>{e(sc["network"])}</b>; true model <b>{e(sc["truth"])}</b> (the operator plans with
the nominal model); critical quarter-hour {e(sc["timestamp"])} (day {sc["day"]}, step
{sc["step"]}): the evaluation day with most avoidable violations at no action, and its
quarter-hour with the largest normalised exceedance at no action. The selection uses the
no-action state only, not the policies' outcomes.</p>
<h2>What is measured</h2>
<table><tr><th>Quantity</th><th>Available to the operator?</th></tr>
<tr><td>LV busbar voltage, transformer current, P and Q (square)</td><td>yes (substation)</td></tr>
<tr><td>Feeder-head currents ({len(sc["heads"])} thick lines)</td><td>yes (substation)</td></tr>
<tr><td>Two remote meter voltages (ringed buses)</td><td>only for B3</td></tr>
<tr><td>Voltages at the other {unmetered} LV buses</td><td>no</td></tr>
<tr><td>Currents of the other {sc["lines"] - len(sc["heads"])} lines</td><td>no</td></tr>
<tr><td>Metered customer injections (previous day)</td>
<td>yes, assumed exact (model input)</td></tr>
</table>
<h2>True signed margins at the critical quarter-hour (evaluator view)</h2>
<p>Bus colour: voltage margin min(V<sub>max</sub> − V, V − V<sub>min</sub>) in p.u. (red &lt; 0,
orange &lt; 0.01, green otherwise). Line colour: loading margin 100 − loading in % (red &lt; 0,
orange &lt; 10). Different units; never added.</p>
<div class="panels">{panels}</div>
<table><tr><th>Panel</th><th>Worst voltage margin (p.u.)</th><th>Worst loading margin (%)</th>
</tr>{rows}</table>
<h2>Decisions on this day</h2>
<p>Blue bar height: cap depth per daylight quarter-hour (none to no PV export). Red tick: a true
avoidable violation in that quarter-hour. Dashed line: the quarter-hour shown above. Times UTC.</p>
<div style="overflow-x:auto">{_timeline(sc)}</div>
<table><tr><th>Policy</th><th>Remote meters</th>
<th>Cap level at this step (0 = none, 10 = no PV)</th>
<th>Avoidable violation quarter-hours that day</th><th>Curtailed MWh that day</th>
<th>Estimates in force (C1)</th><th>Evidence label</th></tr>{policies}</table>
<h2>Whole evaluation half-year, this network and truth (frozen registered outputs)</h2>
<table><tr><th>Run</th><th>Avoidable violation quarter-hours</th><th>Curtailed MWh</th>
<th>Meets the requirement</th></tr>{frozen}</table>
<p>Re-run check: the violation and curtailment totals of the three re-run policies equal the
frozen evaluation outputs. C1 safety margin (development-tuned, normalised):
{sc["safety_margin"]}.</p>
<h2>Evidence and limits</h2>
<ul>
<li>C1 corrects the nominal model by the busbar-voltage residual (common voltage offset) and the
transformer/feeder-head current ratios. This works for errors common to the feeder (tap, MV
voltage). It is not expected to see local errors (one inverter, one cable, phase
imbalance): argued, not tested.</li>
<li>It trusts the busbar voltage measurement. The tolerated bias is about the safety margin;
a −0.005 p.u. bias raised mismatch violations from 1 to 260 (five networks).</li>
<li>"Substation only" assumes complete, exact customer injection metering of the previous
day. Errors in those data were not tested; they would pass one-for-one into the ratios.</li>
<li>The registered primary hypothesis was <b>not met</b>: under the correct model C1 curtailed
27 % more than binary substation feedback, the cost of its registered loading safety margin.
Under model errors it curtailed 41 % more than binary feedback with two exact meters.</li>
<li>Evidence labels are operational definitions, not certificates. "Evidence sufficient" means
only that the substation residuals are small.</li>
<li>Only constant model errors that raise voltage or loading were tested; constant-power loads;
MV voltage constant within the day.</li>
</ul></body></html>
"""


def write(code: str, truth: str, output_dir: Path) -> Path:
    from gridpulse.runguard import atomic_write_text

    sc = scenario(code, truth)
    path = Path(output_dir) / f"{code}_{truth}.html"
    atomic_write_text(path, render(sc))
    return path
