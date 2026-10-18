"""The one Phase 5 figure: telemetry, reliability and cost, ideal vs realistic readings.

Plain SVG, no plotting dependency. It reads only `outputs/sense_study/evaluation_results.json`
and writes `outputs/sense_study/figures/telemetry_noise.svg` (git-ignored, derived data).
Usage, from the repository root:

    python docs/provenance/phase5/scripts/figure.py
"""

import json
from pathlib import Path

OUT = Path("outputs/sense_study")
MISMATCH = ("tap_raise_lv", "mv_high", "pv_fixed_095")
CONFIGS = (
    ("transformer", "transformer"),
    ("substation", "substation"),
    ("substation+2:topology", "+2 smart meters"),
    ("full", "every bus and cable"),
)
CONDITIONS = (
    ("ideal", "exact readings", "#4C72B0"),
    ("realistic", "realistic readings", "#DD8452"),
)


def collect(results):
    nets = [c for c in results if "rural1" not in c]
    cells, mwh = {}, {}
    for config, _ in CONFIGS:
        for cond, _, _ in CONDITIONS:
            key = f"replay_aci/{config}/{cond}"
            cells[config, cond] = sum(
                results[c]["decisions"][t][key]["meets_beta"] for c in nets for t in MISMATCH
            )
            mwh[config, cond] = sum(
                results[c]["decisions"]["nominal"][key]["curtailed_mwh"] for c in nets
            )
    oracle = sum(results[c]["decisions"]["nominal"]["oracle/none/realistic"]["curtailed_mwh"]
                 for c in nets)  # fmt: skip
    return cells, mwh, oracle, len(nets) * len(MISMATCH)


def panel(x0, title, ylabel, values, ymax, step, ref, ref_label, fmt):
    w, h, top, left = 330, 210, 60, 50
    base = top + h
    parts = [
        f'<text x="{x0 + left}" y="{top - 30}" font-weight="bold">{title}</text>',
        f'<text x="{x0 + left}" y="{top - 14}" font-size="11" fill="#555">{ref_label}</text>',
        f'<line x1="{x0 + left}" y1="{top}" x2="{x0 + left}" y2="{base}" stroke="#333"/>',
        f'<line x1="{x0 + left}" y1="{base}" x2="{x0 + left + w}" y2="{base}" stroke="#333"/>',
        f'<text transform="translate({x0 + 14},{top + h / 2}) rotate(-90)" '
        f'text-anchor="middle">{ylabel}</text>',
    ]
    for v in range(0, ymax + 1, step):
        y = base - h * v / ymax
        parts.append(f'<text x="{x0 + left - 6}" y="{y + 4}" text-anchor="end" '
                     f'font-size="11">{v:.0f}</text>')  # fmt: skip
    y_ref = base - h * ref / ymax
    parts.append(f'<line x1="{x0 + left}" y1="{y_ref}" x2="{x0 + left + w}" y2="{y_ref}" '
                 f'stroke="#555" stroke-dasharray="4 3"/>')  # fmt: skip
    group = w / len(CONFIGS)
    for g, (config, label) in enumerate(CONFIGS):
        gx = x0 + left + g * group
        for b, (cond, _, colour) in enumerate(CONDITIONS):
            v = values[config, cond]
            bh = h * v / ymax
            bx = gx + 12 + b * (group - 24) / 2
            bw = (group - 24) / 2 - 2
            parts.append(f'<rect x="{bx:.1f}" y="{base - bh:.1f}" width="{bw:.1f}" '
                         f'height="{bh:.1f}" fill="{colour}"/>')  # fmt: skip
            parts.append(f'<text x="{bx + bw / 2:.1f}" y="{base - bh - 4:.1f}" '
                         f'text-anchor="middle" font-size="11">{fmt(v)}</text>')  # fmt: skip
        words = label.split(" ")
        lines = [" ".join(words[:2]), " ".join(words[2:])] if len(words) > 2 else [label]
        for n, line in enumerate(lines):
            parts.append(f'<text x="{gx + group / 2:.1f}" y="{base + 16 + 13 * n}" '
                         f'text-anchor="middle" font-size="11">{line}</text>')  # fmt: skip
    return parts


def main():
    results = json.loads((OUT / "evaluation_results.json").read_text())
    cells, mwh, oracle, n_cells = collect(results)
    ymax_mwh = 50 * (int(max(mwh.values()) // 50) + 1)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="820" height="345" viewBox="0 0 820 345" '
        'font-family="Helvetica, Arial, sans-serif" font-size="12">',
        '<rect width="820" height="345" fill="white"/>',
        *panel(0, "a  Model-error cases meeting the target", "cells (of 15)", cells, n_cells,
               5, n_cells, f"dashed: all {n_cells} cells", lambda v: f"{v:d}"),
        *panel(400, "b  Curtailment under the correct model", "MWh, 5 networks", mwh,
               ymax_mwh, 50, oracle, f"dashed: oracle (unattainable), {oracle:.0f} MWh",
               lambda v: f"{v:.0f}"),
    ]  # fmt: skip
    for i, (_, label, colour) in enumerate(CONDITIONS):
        x = 250 + i * 170
        parts.append(f'<rect x="{x}" y="318" width="12" height="12" fill="{colour}"/>')
        parts.append(f'<text x="{x + 18}" y="328">{label}</text>')
    parts.append("</svg>")
    (OUT / "figures").mkdir(exist_ok=True)
    path = OUT / "figures" / "telemetry_noise.svg"
    path.write_text("\n".join(parts) + "\n")
    print(path, {k: v for k, v in cells.items()}, {k: round(v, 1) for k, v in mwh.items()})


if __name__ == "__main__":
    main()
