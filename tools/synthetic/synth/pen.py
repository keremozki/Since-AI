"""Paper-space pen (mm, origin top-left): lines, arcs, and text as real glyphs or Hershey strokes."""
import math

import pymupdf
from HersheyFonts import HersheyFonts

MM = 72 / 25.4
BLACK, GREY, LGREY, RED, WHITE = (0, 0, 0), (0.45, 0.45, 0.45), (0.78, 0.78, 0.78), (0.85, 0.1, 0.1), (1, 1, 1)
CAP = 0.718  # Helvetica cap height per em
XS = 0.84  # horizontal squeeze so Hershey text is about as wide as Helvetica


def pt(x, y):
    return pymupdf.Point(x * MM, y * MM)


class Pen:
    """Draws on one page through a single Shape. strokes=True turns text into line paths (no text layer).

    Call done() once after drawing to write the page content.
    """

    def __init__(self, page, strokes=False):
        self.page, self.strokes = page, strokes
        self.sh = page.new_shape()
        self.fonts = {}
        if strokes:
            for name in ("futural", "futuram"):
                f = HersheyFonts()
                f.load_default_font(name)
                self.fonts[name] = f

    def done(self):
        self.sh.commit()

    # ---- geometry
    def line(self, x1, y1, x2, y2, w=0.25, color=BLACK, dash=None, cap=2):
        self.sh.draw_line(pt(x1, y1), pt(x2, y2))
        self.sh.finish(color=color, width=w * MM, dashes=dash, lineCap=cap, closePath=False)

    def poly(self, pts, w=0.25, color=BLACK, fill=None, closed=False, dash=None):
        self.sh.draw_polyline([pt(x, y) for x, y in pts])
        self.sh.finish(color=color, fill=fill, width=w * MM, dashes=dash, closePath=closed, lineJoin=0, lineCap=2)

    def rect(self, x, y, w, h, lw=0.25, color=BLACK, fill=None, dash=None):
        self.sh.draw_rect(pymupdf.Rect(x * MM, y * MM, (x + w) * MM, (y + h) * MM))
        self.sh.finish(color=color, fill=fill, width=lw * MM, dashes=dash, closePath=True)

    def arc(self, cx, cy, r, a0, a1, w=0.25, color=BLACK, dash=None):
        """Arc from angle a0 to a1 (degrees, page coordinates, y down) as cubic Beziers."""
        n = max(1, math.ceil(abs(a1 - a0) / 90 - 1e-9))
        step = math.radians(a1 - a0) / n
        k = 4 / 3 * math.tan(step / 4) * r
        for i in range(n):
            s = math.radians(a0) + i * step
            e = s + step
            p0 = (cx + r * math.cos(s), cy + r * math.sin(s))
            p3 = (cx + r * math.cos(e), cy + r * math.sin(e))
            p1 = (p0[0] - k * math.sin(s), p0[1] + k * math.cos(s))
            p2 = (p3[0] + k * math.sin(e), p3[1] - k * math.cos(e))
            self.sh.draw_bezier(pt(*p0), pt(*p1), pt(*p2), pt(*p3))
            self.sh.finish(color=color, width=w * MM, dashes=dash, lineCap=2, closePath=False)

    # ---- text
    def width(self, s, cap=2.5, bold=False):
        """Text width in mm for a cap height in mm."""
        if self.strokes:
            return sum(g.char_width for g in self._glyphs(s, bold)) * cap / 21 * XS
        return pymupdf.get_text_length(s, fontname="hebo" if bold else "helv", fontsize=cap / CAP * MM) / MM

    def _glyphs(self, s, bold):
        return list(self.fonts["futuram" if bold else "futural"].glyphs_for_text(s))

    def text(self, x, y, s, cap=2.5, anchor="l", rot=0, bold=False, color=BLACK):
        """Text with baseline-left at (x, y); anchor l/c/r shifts along the baseline. rot 0 or 90 (reads upward)."""
        w = self.width(s, cap, bold)
        off = {"l": 0, "c": -w / 2, "r": -w}[anchor]
        if rot == 90:
            x, y = x, y - off
        else:
            x += off
        if not self.strokes:
            self.sh.insert_text(pt(x, y), s, fontname="hebo" if bold else "helv", fontsize=cap / CAP * MM,
                                color=color, rotate=rot)
            return
        font = self.fonts["futuram" if bold else "futural"]
        k = cap / 21  # Hershey caps are 21 units high
        lw = max(0.13, cap * 0.09) * (1.25 if bold else 1)
        for st in font.strokes_for_text(s):
            pts = []
            for u, v in st:
                u, v = u * k * XS, (9 - v) * k  # baseline at v = 0, up positive
                pts.append((x + u, y - v) if rot == 0 else (x - v, y - u))
            if len(pts) == 1:
                pts.append((pts[0][0] + 0.01, pts[0][1]))
            self.sh.draw_polyline([pt(*q) for q in pts])
            self.sh.finish(color=color, width=lw * MM, lineCap=1, lineJoin=1, closePath=False)
