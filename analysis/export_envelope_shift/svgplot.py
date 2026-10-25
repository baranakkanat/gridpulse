"""A dependency-free SVG writer for Mission 11 Stage A's figures.

Matplotlib is not installed in this environment and adding a dependency is forbidden, so
the figures are written as plain SVG text. The writer draws only what the data contain:
axes with units, markers, lines, error bars and a legend. Every figure carries a `<title>`
and a `<desc>` that states n, the uncertainty shown and the data source, and a footer band
holding the ODbL notice for the SimBench data the figures derive from.

Nothing here reads the repository or runs a solve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "Series",
    "Panel",
    "Figure",
    "nice_ticks",
    "log_ticks",
    "text_width",
    "TICK_FONT_PX",
    "ATTRIBUTION_NOTICE",
    "FOOTER_HEIGHT",
    "CREDIT_FONT_PX",
    "HEADER_FIRST_BASELINE",
    "HEADER_LINE_PX",
    "HEADER_FREE_LINES",
]

# The writer has no font metrics, so it estimates a run of text as a fixed fraction of the
# font size per character. 0.6 em is a deliberate over-estimate for Helvetica's lower case,
# which is what a layout check wants: it errs towards declaring an overlap.
CHAR_WIDTH_EM = 0.6
TICK_FONT_PX = 9.0  # must track `.tick` in the stylesheet below


def text_width(text: str, font_px: float = TICK_FONT_PX) -> float:
    """The writer's own width estimate for one run of text, in px."""
    return len(text) * font_px * CHAR_WIDTH_EM


# ODbL 1.0 s. 4.3 wants a notice associated with every Produced Work, reasonably calculated
# to make a viewer aware of the source and the licence. A figure is often viewed on its own,
# so the sentence is drawn on the canvas as well as appended to `<desc>`; a sidecar file
# alone would not travel with the image. See analysis/export_envelope_shift/DATA_ATTRIBUTION.md.
ATTRIBUTION_NOTICE = (
    "Contains information from SimBench (simbench.de), made available under the Open "
    "Database License (ODbL 1.0). "
    "See analysis/export_envelope_shift/DATA_ATTRIBUTION.md."
)

# The footer band. It is added below the existing content, so the canvas grows by exactly
# FOOTER_HEIGHT and no drawn element moves.
FOOTER_HEIGHT = 30.0
FOOTER_MARGIN_X = 12.0  # the figure title's left margin
FOOTER_FIRST_BASELINE = 12.0  # below the top of the band
FOOTER_LINE_PX = 10.0
FOOTER_MAX_LINES = 2  # what FOOTER_HEIGHT holds: 12 + 2 x 10 px, with room for descenders

# The header: the figure title, then the description note wrapped to the canvas width.
HEADER_FIRST_BASELINE = 40.0  # the note's first baseline, below the title's at y = 26
HEADER_LINE_PX = 11.0
# Three note lines clear the first panel title, whose baseline sits at 72 + _PAD_TOP - 12 =
# 90 px. A fourth line would land on it, so every line past the third moves the panels down.
HEADER_FREE_LINES = 3

CREDIT_FONT_PX = 8.0  # must track CREDIT_STYLE below; no larger than `.tick`
# An inline style, not a stylesheet class, so the figures' `<style>` element is untouched:
# the notice must not perturb a single byte of the existing content. A presentation
# attribute would not do, since the sheet's `text{fill:#000000}` rule would override it.
CREDIT_STYLE = "font-size:8px;fill:#595959"


# A print-safe, colour-blind-distinguishable sequence (Okabe-Ito, black first).
PALETTE = (
    "#000000",
    "#e69f00",
    "#56b4e9",
    "#009e73",
    "#cc79a7",
    "#0072b2",
    "#d55e00",
    "#7f7f7f",
)

_MARKERS = ("circle", "square", "triangle", "diamond", "cross")


def _esc(text: object) -> str:
    """XML-escape text for element content and attribute values."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _fmt(value: float) -> str:
    """A short, deterministic coordinate string."""
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"non-finite coordinate: {value}")
    text = f"{value:.2f}"
    return text[:-3] if text.endswith(".00") else text


def _tick_label(value: float) -> str:
    if value == 0:
        return "0"
    magnitude = abs(value)
    if magnitude >= 1e4 or magnitude < 1e-3:
        return f"{value:.0e}".replace("e-0", "e-").replace("e+0", "e")
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text


def nice_ticks(lo: float, hi: float, target: int = 5) -> list[float]:
    """Ticks at 1, 2, 2.5 or 5 times a power of ten, covering [lo, hi]."""
    if not (hi > lo):
        return [lo]
    raw = (hi - lo) / max(target, 2)
    power = 10.0 ** math.floor(math.log10(raw))
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = multiple * power
        if step >= raw:
            break
    first = math.ceil(lo / step - 1e-9) * step
    ticks = []
    value = first
    while value <= hi + 1e-9 * step:
        ticks.append(0.0 if abs(value) < 1e-12 * step else value)
        value += step
    return ticks


def log_ticks(lo: float, hi: float) -> list[float]:
    """One tick per decade covering [lo, hi], thinned to at most 8."""
    if lo <= 0 or hi <= 0:
        raise ValueError("a logarithmic axis needs strictly positive limits")
    low, high = math.floor(math.log10(lo)), math.ceil(math.log10(hi))
    decades = list(range(int(low), int(high) + 1))
    stride = max(1, math.ceil(len(decades) / 8))
    return [10.0**d for d in decades[::stride]]


@dataclass
class Series:
    """One drawn set of points. `ylo`/`yhi` are absolute interval ends, not half-widths."""

    x: list[float]
    y: list[float]
    label: str = ""
    kind: str = "marker"  # "marker", "line" or "line+marker"
    marker: str = "circle"
    filled: bool = True
    colour: str = PALETTE[0]
    ylo: list[float] | None = None
    yhi: list[float] | None = None
    point_labels: list[str] | None = None
    dash: str | None = None
    size: float = 3.4

    def __post_init__(self) -> None:
        if len(self.x) != len(self.y):
            raise ValueError(f"series {self.label!r}: {len(self.x)} x against {len(self.y)} y")
        if self.marker not in _MARKERS:
            raise ValueError(f"unknown marker {self.marker!r}")
        for name in ("ylo", "yhi", "point_labels"):
            extra = getattr(self, name)
            if extra is not None and len(extra) != len(self.x):
                raise ValueError(f"series {self.label!r}: {name} has the wrong length")


@dataclass
class Panel:
    """One set of axes."""

    series: list[Series]
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    xlog: bool = False
    ylog: bool = False
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None
    xticks: list[tuple[float, str]] | None = None
    yticks: list[tuple[float, str]] | None = None
    hlines: list[tuple[float, str]] = field(default_factory=list)
    note: str = ""
    xtick_rotate: float = 0.0  # degrees anticlockwise; 0 leaves the labels horizontal

    def xtick_band(self) -> float:
        """The vertical room the x tick labels need below the axis, in px.

        Zero unless the labels are rotated, so an unrotated panel keeps the plain layout.
        A label rotated by `xtick_rotate` hangs `width * sin(angle)` below its anchor.
        """
        if not self.xtick_rotate or not self.xticks:
            return 0.0
        longest = max((text_width(label) for _, label in self.xticks), default=0.0)
        return longest * math.sin(math.radians(abs(self.xtick_rotate))) + TICK_FONT_PX

    def _data_range(self, axis: str) -> tuple[float, float]:
        values: list[float] = []
        for series in self.series:
            values.extend(series.x if axis == "x" else series.y)
            if axis == "y":
                for extra in (series.ylo, series.yhi):
                    if extra is not None:
                        values.extend(extra)
        if axis == "y":
            values.extend(level for level, _ in self.hlines)
        values = [v for v in values if v == v and abs(v) != float("inf")]
        if not values:
            return (0.0, 1.0)
        lo, hi = min(values), max(values)
        if hi == lo:
            pad = abs(hi) * 0.1 or 0.5
            return (lo - pad, hi + pad)
        return (lo, hi)

    def limits(self, axis: str) -> tuple[float, float]:
        explicit = self.xlim if axis == "x" else self.ylim
        if explicit is not None:
            return explicit
        lo, hi = self._data_range(axis)
        if self.xlog if axis == "x" else self.ylog:
            return (lo / 2.0, hi * 2.0)
        pad = (hi - lo) * 0.08
        return (lo - pad, hi + pad)


class Figure:
    """A grid of panels rendered as a single standalone SVG document."""

    def __init__(
        self,
        title: str,
        desc: str,
        panels: list[Panel],
        ncols: int = 1,
        panel_width: float = 540.0,
        panel_height: float = 300.0,
        legend_width: float = 150.0,
    ) -> None:
        if not panels:
            raise ValueError("a figure needs at least one panel")
        self.title = title
        self.desc = desc
        self.panels = panels
        self.ncols = max(1, int(ncols))
        self.nrows = math.ceil(len(panels) / self.ncols)
        self.panel_width = float(panel_width)
        self.panel_height = float(panel_height)
        self.legend_width = float(legend_width)
        # The wrap is done once here, and `to_svg` draws these very lines: the header's
        # height and its content must not be able to disagree.
        self.note_lines = _wrap(self.desc, int(self.width / 5.4))
        # HEADER_FREE_LINES of note fit between the figure title and the first panel title;
        # a longer note would run into it, so the panel grid and the footer move down by the
        # excess. Zero for a note of three lines or fewer, which keeps those figures' bytes.
        self.header_extra = HEADER_LINE_PX * max(0, len(self.note_lines) - HEADER_FREE_LINES)

    # --- geometry -------------------------------------------------------------------
    _PAD_LEFT = 74.0
    _PAD_RIGHT = 14.0
    _PAD_TOP = 30.0
    _PAD_BOTTOM = 56.0

    @property
    def width(self) -> float:
        return self.ncols * (self.panel_width + self.legend_width) + 24.0

    @property
    def content_height(self) -> float:
        """The canvas height before the footer band; no drawn element reaches below it."""
        return self.nrows * self.panel_height + 96.0 + self.header_extra

    @property
    def height(self) -> float:
        return self.content_height + FOOTER_HEIGHT

    def _plot_box(self, index: int) -> tuple[float, float, float, float]:
        column, row = index % self.ncols, index // self.ncols
        x0 = 12.0 + column * (self.panel_width + self.legend_width) + self._PAD_LEFT
        y0 = 72.0 + self.header_extra + row * self.panel_height + self._PAD_TOP
        return (
            x0,
            y0,
            self.panel_width - self._PAD_LEFT - self._PAD_RIGHT,
            self.panel_height - self._PAD_TOP - self._PAD_BOTTOM - self.panels[index].xtick_band(),
        )

    # --- drawing --------------------------------------------------------------------
    @staticmethod
    def _project(
        value: float, lo: float, hi: float, start: float, length: float, logarithmic: bool
    ) -> float:
        if logarithmic:
            value, lo, hi = max(value, 1e-300), max(lo, 1e-300), max(hi, 1e-300)
            value, lo, hi = math.log10(value), math.log10(lo), math.log10(hi)
        if hi == lo:
            return start + length / 2.0
        return start + (value - lo) / (hi - lo) * length

    def _marker(self, x: float, y: float, series: Series) -> str:
        size = series.size
        fill = series.colour if series.filled else "none"
        common = f'fill="{fill}" stroke="{series.colour}" stroke-width="1.2"'
        if series.marker == "circle":
            return f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(size)}" {common}/>'
        if series.marker == "square":
            return (
                f'<rect x="{_fmt(x - size)}" y="{_fmt(y - size)}" width="{_fmt(2 * size)}"'
                f' height="{_fmt(2 * size)}" {common}/>'
            )
        if series.marker == "triangle":
            points = f"{_fmt(x)},{_fmt(y - size)} {_fmt(x - size)},{_fmt(y + size)} " + (
                f"{_fmt(x + size)},{_fmt(y + size)}"
            )
            return f'<polygon points="{points}" {common}/>'
        if series.marker == "diamond":
            points = (
                f"{_fmt(x)},{_fmt(y - size)} {_fmt(x + size)},{_fmt(y)} "
                f"{_fmt(x)},{_fmt(y + size)} {_fmt(x - size)},{_fmt(y)}"
            )
            return f'<polygon points="{points}" {common}/>'
        stroke = f'stroke="{series.colour}" stroke-width="1.4"'
        return (
            f'<line x1="{_fmt(x - size)}" y1="{_fmt(y - size)}" x2="{_fmt(x + size)}"'
            f' y2="{_fmt(y + size)}" {stroke}/>'
            f'<line x1="{_fmt(x - size)}" y1="{_fmt(y + size)}" x2="{_fmt(x + size)}"'
            f' y2="{_fmt(y - size)}" {stroke}/>'
        )

    def _render_panel(self, index: int, panel: Panel) -> list[str]:
        x0, y0, w, h = self._plot_box(index)
        xlo, xhi = panel.limits("x")
        ylo, yhi = panel.limits("y")
        out: list[str] = []

        def px(value: float) -> float:
            return self._project(value, xlo, xhi, x0, w, panel.xlog)

        def py(value: float) -> float:
            return self._project(value, ylo, yhi, y0 + h, -h, panel.ylog)

        if panel.title:
            out.append(
                f'<text x="{_fmt(x0)}" y="{_fmt(y0 - 12)}" class="panel">{_esc(panel.title)}</text>'
            )
        out.append(
            f'<rect x="{_fmt(x0)}" y="{_fmt(y0)}" width="{_fmt(w)}" height="{_fmt(h)}"'
            ' fill="none" stroke="#000000" stroke-width="0.9"/>'
        )

        xtick_pairs = panel.xticks
        if xtick_pairs is None:
            marks = log_ticks(xlo, xhi) if panel.xlog else nice_ticks(xlo, xhi)
            xtick_pairs = [(m, _tick_label(m)) for m in marks]
        for position, label in xtick_pairs:
            if not (xlo <= position <= xhi):
                continue
            at = px(position)
            out.append(
                f'<line x1="{_fmt(at)}" y1="{_fmt(y0 + h)}" x2="{_fmt(at)}"'
                f' y2="{_fmt(y0 + h + 4)}" stroke="#000000" stroke-width="0.9"/>'
            )
            if panel.xtick_rotate:
                out.append(
                    f'<text transform="translate({_fmt(at)},{_fmt(y0 + h + 14)})'
                    f' rotate({_fmt(-abs(panel.xtick_rotate))})" class="tick"'
                    f' text-anchor="end">{_esc(label)}</text>'
                )
            else:
                out.append(
                    f'<text x="{_fmt(at)}" y="{_fmt(y0 + h + 16)}" class="tick"'
                    f' text-anchor="middle">{_esc(label)}</text>'
                )

        ytick_pairs = panel.yticks
        if ytick_pairs is None:
            marks = log_ticks(ylo, yhi) if panel.ylog else nice_ticks(ylo, yhi)
            ytick_pairs = [(m, _tick_label(m)) for m in marks]
        for position, label in ytick_pairs:
            if not (ylo <= position <= yhi):
                continue
            at = py(position)
            out.append(
                f'<line x1="{_fmt(x0 - 4)}" y1="{_fmt(at)}" x2="{_fmt(x0)}"'
                f' y2="{_fmt(at)}" stroke="#000000" stroke-width="0.9"/>'
            )
            out.append(
                f'<text x="{_fmt(x0 - 7)}" y="{_fmt(at + 3.5)}" class="tick"'
                f' text-anchor="end">{_esc(label)}</text>'
            )

        for level, label in panel.hlines:
            if not (ylo <= level <= yhi):
                continue
            at = py(level)
            out.append(
                f'<line x1="{_fmt(x0)}" y1="{_fmt(at)}" x2="{_fmt(x0 + w)}" y2="{_fmt(at)}"'
                ' stroke="#7f7f7f" stroke-width="0.8" stroke-dasharray="4 3"/>'
            )
            if label:
                out.append(
                    f'<text x="{_fmt(x0 + w - 3)}" y="{_fmt(at - 3)}" class="tick"'
                    f' text-anchor="end">{_esc(label)}</text>'
                )

        for series in panel.series:
            points = [
                (px(xv), py(yv))
                for xv, yv in zip(series.x, series.y, strict=False)
                if xv == xv and yv == yv
            ]
            if series.kind in ("line", "line+marker") and len(points) > 1:
                path = " ".join(f"{_fmt(a)},{_fmt(b)}" for a, b in points)
                dash = f' stroke-dasharray="{series.dash}"' if series.dash else ""
                out.append(
                    f'<polyline points="{path}" fill="none" stroke="{series.colour}"'
                    f' stroke-width="1.3"{dash}/>'
                )
            if series.ylo is not None and series.yhi is not None:
                for xv, low, high in zip(series.x, series.ylo, series.yhi, strict=False):
                    if xv != xv or low != low or high != high:
                        continue
                    at = px(xv)
                    out.append(
                        f'<line x1="{_fmt(at)}" y1="{_fmt(py(low))}" x2="{_fmt(at)}"'
                        f' y2="{_fmt(py(high))}" stroke="{series.colour}" stroke-width="1.0"/>'
                    )
                    for end in (low, high):
                        out.append(
                            f'<line x1="{_fmt(at - 2.6)}" y1="{_fmt(py(end))}"'
                            f' x2="{_fmt(at + 2.6)}" y2="{_fmt(py(end))}"'
                            f' stroke="{series.colour}" stroke-width="1.0"/>'
                        )
            if series.kind in ("marker", "line+marker"):
                for at, up in points:
                    out.append(self._marker(at, up, series))
            if series.point_labels is not None:
                for xv, yv, text in zip(series.x, series.y, series.point_labels, strict=False):
                    if not text or xv != xv or yv != yv:
                        continue
                    out.append(
                        f'<text x="{_fmt(px(xv) + 6)}" y="{_fmt(py(yv) - 5)}" class="point">'
                        f"{_esc(text)}</text>"
                    )

        band = panel.xtick_band()
        if panel.xlabel:
            out.append(
                f'<text x="{_fmt(x0 + w / 2)}" y="{_fmt(y0 + h + 36 + band)}" class="axis"'
                f' text-anchor="middle">{_esc(panel.xlabel)}</text>'
            )
        if panel.ylabel:
            cy = y0 + h / 2
            out.append(
                f'<text transform="translate({_fmt(x0 - 54)},{_fmt(cy)}) rotate(-90)"'
                f' class="axis" text-anchor="middle">{_esc(panel.ylabel)}</text>'
            )
        if panel.note:
            out.append(
                f'<text x="{_fmt(x0)}" y="{_fmt(y0 + h + 50 + band)}" class="note">'
                f"{_esc(panel.note)}</text>"
            )

        legend_x = x0 + w + 16.0
        legend_y = y0 + 10.0
        for series in panel.series:
            if not series.label:
                continue
            out.append(self._marker(legend_x + 5.0, legend_y - 3.5, series))
            out.append(
                f'<text x="{_fmt(legend_x + 15)}" y="{_fmt(legend_y)}" class="legend">'
                f"{_esc(series.label)}</text>"
            )
            legend_y += 15.0
        return out

    # --- the ODbL footer ------------------------------------------------------------------
    def footer_lines(self) -> list[str]:
        """`ATTRIBUTION_NOTICE` wrapped to the canvas width, by the writer's own estimate."""
        lines = _wrap_to_px(ATTRIBUTION_NOTICE, self.width - 2 * FOOTER_MARGIN_X, CREDIT_FONT_PX)
        if len(lines) > FOOTER_MAX_LINES:
            raise ValueError(
                f"the ODbL notice wraps to {len(lines)} lines in a {_fmt(self.width)} px"
                f" canvas; the footer band holds {FOOTER_MAX_LINES}"
            )
        return lines

    def _render_footer(self) -> list[str]:
        top = self.content_height
        return [
            f'<text x="{_fmt(FOOTER_MARGIN_X)}"'
            f' y="{_fmt(top + FOOTER_FIRST_BASELINE + FOOTER_LINE_PX * line_no)}"'
            f' style="{CREDIT_STYLE}">{_esc(line)}</text>'
            for line_no, line in enumerate(self.footer_lines())
        ]

    def to_svg(self) -> str:
        body: list[str] = []
        for index, panel in enumerate(self.panels):
            body.extend(self._render_panel(index, panel))
        body.extend(self._render_footer())
        head = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(self.width)}"'
            f' height="{_fmt(self.height)}" viewBox="0 0 {_fmt(self.width)}'
            f' {_fmt(self.height)}" role="img">',
            f"<title>{_esc(self.title)}</title>",
            f"<desc>{_esc(self.desc)} {_esc(ATTRIBUTION_NOTICE)}</desc>",
            "<style>"
            "text{font-family:Helvetica,Arial,sans-serif;fill:#000000}"
            ".fig{font-size:13px;font-weight:bold}"
            ".panel{font-size:11px;font-weight:bold}"
            ".axis{font-size:10px}"
            ".tick{font-size:9px}"
            ".legend{font-size:9px}"
            ".point{font-size:7.5px;fill:#404040}"
            ".note{font-size:8px;fill:#404040}"
            "</style>",
            f'<text x="12" y="26" class="fig">{_esc(self.title)}</text>',
        ]
        for line_no, line in enumerate(self.note_lines):
            baseline = HEADER_FIRST_BASELINE + HEADER_LINE_PX * line_no
            head.append(f'<text x="12" y="{_fmt(baseline)}" class="note">{_esc(line)}</text>')
        return "\n".join(head + body + ["</svg>", ""])


def _wrap_to_px(text: str, max_px: float, font_px: float) -> list[str]:
    """Greedy word wrap against `text_width`, so each line fits `max_px` on the canvas.

    A single word wider than `max_px` keeps its own line rather than being broken.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and text_width(candidate, font_px) > max_px:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap, so a long `<desc>` is also legible on the canvas."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > max(width, 20) and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines
