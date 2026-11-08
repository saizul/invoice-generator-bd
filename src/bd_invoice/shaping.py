"""Bangla text shaping for ReportLab (optional, needs `uharfbuzz`).

ReportLab places glyphs one code point at a time and never applies OpenType substitution rules, so
Bangla vowel signs and conjuncts come out wrong. When `uharfbuzz` is installed we shape the text with
HarfBuzz and draw the glyph outlines as vector paths. The text is therefore not selectable in the PDF,
but it is visually correct. Without `uharfbuzz` the generator stays English-only.
"""

from __future__ import annotations

try:  # pragma: no cover - exercised only when the optional dependency is installed
    import uharfbuzz as hb
except ImportError:  # pragma: no cover
    hb = None

from reportlab.lib import colors
from reportlab.pdfgen.canvas import FILL_NON_ZERO
from reportlab.platypus import Flowable


def shaping_available() -> bool:
    return hb is not None


class _PathPen:
    """Collects HarfBuzz outline callbacks into a ReportLab path."""

    def __init__(self, path, ox: float, oy: float, scale: float):
        self.path, self.ox, self.oy, self.scale = path, ox, oy, scale
        self.current = (0.0, 0.0)

    def _pt(self, p):
        return (self.ox + p[0] * self.scale, self.oy + p[1] * self.scale)

    def moveTo(self, p):  # noqa: N802 - pen protocol names
        self.current = self._pt(p)
        self.path.moveTo(*self.current)

    def lineTo(self, p):  # noqa: N802
        self.current = self._pt(p)
        self.path.lineTo(*self.current)

    def _quad(self, ctrl, end):
        x0, y0 = self.current
        cx, cy = ctrl
        ex, ey = end
        self.path.curveTo(
            x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0),
            ex + 2 / 3 * (cx - ex), ey + 2 / 3 * (cy - ey),
            ex, ey,
        )  # fmt: skip
        self.current = end

    def qCurveTo(self, *points):  # noqa: N802
        pts = [self._pt(p) for p in points]
        # TrueType style: implied on-curve points sit between consecutive off-curve points
        for i in range(len(pts) - 2):
            mid = ((pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2)
            self._quad(pts[i], mid)
        self._quad(pts[-2], pts[-1])

    def curveTo(self, *points):  # noqa: N802
        pts = [self._pt(p) for p in points]
        self.path.curveTo(*pts[0], *pts[1], *pts[2])
        self.current = pts[2]

    def closePath(self):  # noqa: N802
        self.path.close()

    def endPath(self):  # noqa: N802
        self.path.close()


class BanglaShaper:
    """Shapes and draws Bangla (or any complex script) with a TrueType/OpenType font file."""

    def __init__(self, font_path: str, face_index: int = 0):
        if hb is None:
            raise RuntimeError("uharfbuzz is not installed")
        self.font_path = font_path
        blob = hb.Blob.from_file_path(str(font_path))
        self.face = hb.Face(blob, face_index)
        self.font = hb.Font(self.face)
        self.upem = self.face.upem

    def shape(self, text: str) -> list:
        """Return [(glyph_id, x_advance, x_offset, y_offset)] in font units."""
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        hb.shape(self.font, buf, {"kern": True, "liga": True})
        return [
            (i.codepoint, p.x_advance, p.x_offset, p.y_offset)
            for i, p in zip(buf.glyph_infos, buf.glyph_positions)
        ]

    def width(self, text: str, size: float) -> float:
        return sum(g[1] for g in self.shape(text)) * size / self.upem

    def draw(self, canvas, x: float, y: float, text: str, size: float, color=colors.black) -> float:
        """Draw text with its baseline at y; returns the width drawn."""
        scale = size / self.upem
        path = canvas.beginPath()
        cursor = 0.0
        for gid, adv, xo, yo in self.shape(text):
            pen = _PathPen(path, x + (cursor + xo) * scale, y + yo * scale, scale)
            self.font.draw_glyph_with_pen(gid, pen)
            cursor += adv
        canvas.saveState()
        canvas.setFillColor(color)
        canvas.drawPath(path, stroke=0, fill=1, fillMode=FILL_NON_ZERO)
        canvas.restoreState()
        return cursor * scale

    def wrap(self, text: str, size: float, max_width: float) -> list:
        """Greedy word wrap; words are shaped separately (Bangla words never join across spaces)."""
        space = self.width(" ", size) or size * 0.25
        lines, current, used = [], [], 0.0
        for word in text.split():
            w = self.width(word, size)
            extra = w if not current else space + w
            if current and used + extra > max_width:
                lines.append(" ".join(current))
                current, used = [word], w
            else:
                current.append(word)
                used += extra
        if current:
            lines.append(" ".join(current))
        return lines or [""]


class ShapedText(Flowable):
    """A flowable that draws (wrapped) shaped text; use for Bangla lines."""

    def __init__(self, text, shaper, size=10, leading=None, color=colors.black, align="left"):
        super().__init__()
        self.text, self.shaper, self.size = text, shaper, size
        self.leading = leading or size * 1.55
        self.color, self.align = color, align
        self._lines: list = []

    def wrap(self, avail_width, avail_height):
        self._lines = self.shaper.wrap(self.text, self.size, avail_width)
        self.width = avail_width
        self.height = self.leading * len(self._lines)
        return self.width, self.height

    def draw(self):
        for i, line in enumerate(self._lines):
            baseline = self.height - i * self.leading - self.size * 1.1
            w = self.shaper.width(line, self.size)
            x = {"left": 0, "right": self.width - w, "center": (self.width - w) / 2}[self.align]
            self.shaper.draw(self.canv, x, baseline, line, self.size, self.color)
