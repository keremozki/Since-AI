"""General arrangement drawing, deck 5, MVZ 3: A3 landscape, drawn at 1:200 (title block says 1:100)."""
import math

from . import data as D
from .pen import BLACK, GREY, LGREY, RED, WHITE

X0, YC, S = 46.0, 125.5, 5.0  # plan origin (FR 100, centreline) in mm; 5 mm per metre = 1:200
HALF_B = 18.5  # moulded half breadth, m
LEN_M = (D.FR1 - D.FR0) * D.FSP  # 48 m
CAB_OUT, CAB_IN = (11.0, 18.1), (4.4, 9.0)  # cabin rows, |y| in m
RIGHT = 304.0  # left edge of the right-hand column
DASHDOT = "[6 1.2 0.8 1.2] 0"


def X(xm):
    return X0 + xm * S


def Y(ym):
    return YC - ym * S


# ---------------------------------------------------------------- sheet frame
def border(pen):
    """Sheet border with zone letters and numbers."""
    pen.rect(15, 5, 400, 287, lw=0.25)
    pen.rect(20, 10, 390, 277, lw=0.7)
    cw, rh = 390 / 8, 277 / 6
    for i in range(9):
        x = 20 + i * cw
        pen.line(x, 5, x, 10, w=0.25, cap=0)
        pen.line(x, 287, x, 292, w=0.25, cap=0)
    for j in range(7):
        y = 10 + j * rh
        pen.line(15, y, 20, y, w=0.25, cap=0)
        pen.line(410, y, 415, y, w=0.25, cap=0)
    for i in range(8):
        for y in (8.6, 290.6):
            pen.text(20 + (i + 0.5) * cw, y, str(i + 1), cap=2.0, anchor="c")
    for j in range(6):
        for x in (17.5, 412.5):
            pen.text(x, 10 + (j + 0.5) * rh + 1.0, "ABCDEF"[j], cap=2.0, anchor="c")
    for x, y0, y1 in ((215, 5, 10), (215, 287, 292)):
        pen.line(x, y0, x, y1, w=0.6, cap=0)
    for y, x0, x1 in ((148.5, 15, 20), (148.5, 410, 415)):
        pen.line(x0, y, x1, y, w=0.6, cap=0)


# ---------------------------------------------------------------- dimension and tag helpers
def tick(pen, x, y):
    pen.line(x - 0.7, y + 0.7, x + 0.7, y - 0.7, w=0.3, cap=0)


def dimension(pen, a, b, off, text, tx, ty, anchor="l", cap=2.0):
    """Linear dimension: extension lines, dimension line with oblique ticks, text at (tx, ty)."""
    n = math.hypot(*off)
    ux, uy = off[0] / n, off[1] / n
    A, B = (a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])
    for P, Q in ((a, A), (b, B)):
        pen.line(P[0] + ux * 0.8, P[1] + uy * 0.8, Q[0] + ux * 1.0, Q[1] + uy * 1.0, w=0.13, cap=0)
    pen.line(*A, *B, w=0.18, cap=0)
    tick(pen, *A)
    tick(pen, *B)
    if text:
        pen.text(tx, ty, text, cap=cap, anchor=anchor)


def tag(pen, cx, cy, s):
    """Door number tag: white pill with the number, centred at (cx, cy)."""
    w = pen.width(s, 2.0) + 1.8
    pen.rect(cx - w / 2, cy - 1.8, w, 3.6, lw=0.25, fill=WHITE)
    pen.text(cx, cy + 1.0, s, cap=2.0, anchor="c")


def arrow(pen, x0, y0, x1, y1, lw=0.25, head=1.8):
    pen.line(x0, y0, x1, y1, w=lw, cap=0)
    a = math.atan2(y1 - y0, x1 - x0)
    p = [(x1, y1)] + [(x1 - head * math.cos(a + s * 0.3), y1 - head * math.sin(a + s * 0.3)) for s in (1, -1)]
    pen.poly(p, w=0.1, fill=BLACK, closed=True)


def swing(pen, hx, hy, r, closed, opened, w=0.18):
    """Door leaf (open position) and swing arc about the hinge; directions are unit vectors."""
    pen.line(hx, hy, hx + opened[0] * r, hy + opened[1] * r, w=0.35, cap=0)
    a0 = math.degrees(math.atan2(closed[1], closed[0]))
    a1 = math.degrees(math.atan2(opened[1], opened[0]))
    d = (a1 - a0 + 540) % 360 - 180  # shortest way round
    pen.arc(hx, hy, r, a0, a0 + d, w=w)


def wall(pen, y, gaps, x_from=0.0, x_to=LEN_M, lw=0.35):
    """Horizontal wall at y (m) from x_from to x_to (m) with gaps [(xa, xb)] in m; jamb ticks at the gaps."""
    pos = x_from
    for xa, xb in sorted(gaps):
        if xa > pos:
            pen.line(X(pos), Y(y), X(xa), Y(y), w=lw)
        pos = xb
        for x in (xa, xb):
            pen.line(X(x), Y(y) - 0.7, X(x), Y(y) + 0.7, w=0.25, cap=0)
    if pos < x_to:
        pen.line(X(pos), Y(y), X(x_to), Y(y), w=lw)


# ---------------------------------------------------------------- plan
def cabin_blocks(pen, tagged):
    """Cabin rows with partitions, bathroom pods and beds; returns the wall gaps per wall."""
    gaps = {}
    for sg in (1, -1):
        for kind, (ya, yb) in (("cab_out", CAB_OUT), ("cab_in", CAB_IN)):
            wy = 11.0 if kind == "cab_out" else 9.0
            g = gaps.setdefault((sg, wy), [])
            for i in range(15):
                x0 = i * D.CAB_W
                if i:
                    pen.line(X(x0), Y(sg * ya), X(x0), Y(sg * yb), w=0.18, cap=0)
                if kind == "cab_out":
                    pod = (x0 + 1.9, wy if sg > 0 else -wy - 1.9, 1.2, 1.9)
                    bed = (x0 + 1.8, 14.4 if sg > 0 else -16.4, 1.2, 2.0)
                else:
                    pod = (x0 + 1.9, wy - 1.9 if sg > 0 else -wy, 1.2, 1.9)
                    bed = (x0 + 1.8, 4.8 if sg > 0 else -6.8, 1.2, 2.0)
                for r, c in ((pod, GREY), (bed, LGREY)):
                    pen.rect(X(r[0]), Y(r[1] + r[3]), r[2] * S, r[3] * S, lw=0.13, color=c)
                d = tagged.get((kind, "P" if sg > 0 else "S", 100 + 4 * i))
                w = ((d["clear"] or 900) / 1000) if d else 0.9
                g.append((x0 + 0.4, x0 + 0.4 + w))
    return gaps


CORE = {
    "P": [(0, 1.6, "", "void"), (1.6, 11.2, "A", "stair"), (11.2, 14.4, "LIFT 1", "lift"),
          (14.4, 16.0, "", "void"), (16.0, 22.4, "CREW STORE", "store"), (22.4, 28.8, "ELEC", "room"),
          (28.8, 33.6, "PANTRY", "room"), (33.6, 36.8, "LIFT 2", "lift"), (36.8, 46.4, "C", "stair"),
          (46.4, 48.0, "", "void")],
    "S": [(0, 6.4, "LINEN", "room"), (6.4, 12.8, "STORE", "room"), (12.8, 16.0, "LIFT 3", "lift"),
          (16.0, 19.2, "", "void"), (19.2, 28.8, "B", "stair"), (28.8, 32.0, "LIFT 4", "lift"),
          (32.0, 38.4, "PANTRY", "room"), (38.4, 44.8, "TECH", "room"), (44.8, 48.0, "", "void")],
}


def core(pen, doors):
    """Central core: rooms either side of the passage; the stairs are drawn separately."""
    store = next(d for d in doors if d["kind"] == "store")
    for side, sg in (("P", 1), ("S", -1)):
        gaps = []
        for i, (xa, xb, label, kind) in enumerate(CORE[side]):
            if i:
                pen.line(X(xa), Y(sg * D.PASS_Y), X(xa), Y(sg * D.CORE_Y), w=0.3, cap=0)
            xc = (xa + xb) / 2
            if kind == "stair":
                gaps.append((xa + 0.2, xa + 1.8))
            elif kind == "lift":
                gaps.append((xc - 0.7, xc + 0.7))
                pen.rect(X(xa + 0.4), min(Y(sg * 1.7), Y(sg * 3.1)), (xb - xa - 0.8) * S, 1.4 * S, lw=0.18)
                pen.line(X(xa + 0.4), Y(sg * 1.7), X(xb - 0.4), Y(sg * 3.1), w=0.1, cap=0)
                pen.line(X(xa + 0.4), Y(sg * 3.1), X(xb - 0.4), Y(sg * 1.7), w=0.1, cap=0)
            elif kind == "store":
                w = store["clear"] / 1000
                gaps.append((18.4 - w / 2, 18.4 + w / 2))
            elif kind == "room":
                gaps.append((xa + 0.4, xa + 1.3))
            if label and kind != "stair":
                pen.text(X(xc), Y(sg * 3.55) if sg > 0 else Y(-3.95) , label, cap=1.8 if kind == "lift" else 2.0, anchor="c")
        wall(pen, sg * D.PASS_Y, gaps)
    wall(pen, D.CORE_Y, [], lw=0.35)
    wall(pen, -D.CORE_Y, [], lw=0.35)


def stair(pen, name, rev):
    """Stair enclosure, flight with tread lines, width dimension, label and persons served."""
    s = D.STAIRS[name]
    sg = 1 if s["side"] == "P" else -1
    w = D.stair_flight(name, rev) / 1000
    x0 = s["x0"]
    fx0, fx1 = x0 + 3.2, x0 + 9.4
    ya = sg * 1.4  # flight edge nearest the passage
    yb = sg * (1.4 + w)
    top, bot = min(Y(ya), Y(yb)), max(Y(ya), Y(yb))
    pen.rect(X(fx0), top, (fx1 - fx0) * S, bot - top, lw=0.25)
    n = 22
    for i in range(1, n):
        x = X(fx0 + i * (fx1 - fx0) / n)
        pen.line(x, top, x, bot, w=0.1, cap=0)
    ym = (top + bot) / 2
    arrow(pen, X(x0 + 4.0), ym, X(x0 + 8.6), ym, lw=0.18, head=1.4)
    # clear-width dimension: vertical, text to the right of the dimension line
    xd = X(x0 + 0.9)
    dimension(pen, (X(fx0), top), (X(fx0), bot), (xd - X(fx0), 0), f"{D.stair_flight(name, rev)}", xd + 1.6, ym + 1.25, cap=2.5)
    # label block in the free part of the enclosure
    if sg > 0:
        y1 = Y(D.CORE_Y) + 1.0 + 2.5
        y2 = y1 + 4.2
    else:
        y2 = Y(-D.CORE_Y) - 1.7
        y1 = y2 - 4.2
    pen.text(X(fx0 + 0.2), y1, f"STAIR {name}", cap=2.5, bold=True)
    pen.text(X(fx0 + 0.2), y2, f"{s['persons']} P", cap=2.5)


def door(pen, d):
    """Swing arc, leaf, width dimension and number tag of one numbered door."""
    w = (d["clear"] or 900) / 1000
    r = w * S
    xc, ym = D.door_xy(d)
    sg = 1 if d["side"] == "P" else -1
    text = None if d["clear"] is None else str(d["clear"])
    if d["kind"] == "zone":
        left = d["fr"] == D.FR0
        bx = X(0) if left else X(LEN_M)
        hy = Y(sg * (10.0 + w / 2))  # hinge at the outboard end
        cdir = (0, 1) if sg > 0 else (0, -1)
        odir = (1, 0) if left else (-1, 0)
        swing(pen, bx, hy, r, cdir, odir)
        ya, yb = hy, hy + cdir[1] * r
        out = -1 if left else 1
        dimension(pen, (bx, ya), (bx, yb), (out * 3.0, 0), text, bx + out * 4.2, (ya + yb) / 2 + 1.0,
                  "l" if out > 0 else "r")
        tx = bx + odir[0] * (r + 1.3 + (pen.width(str(d["no"]), 2.0) + 1.8) / 2)
        tag(pen, tx, (ya + yb) / 2, str(d["no"]))
        return
    if d["kind"] == "store":
        wy, face, into = D.PASS_Y, D.PASS_Y, 1
    elif d["kind"] == "cab_out":
        wy, face, into = 11.0, 11.0, sg
    else:
        wy, face, into = 9.0, 8.3, -sg  # deep recess: leaf sits on the inner face
    xa, xb = X(xc - w / 2), X(xc + w / 2)
    ydir = -1 if into > 0 else 1  # paper direction of the swing
    hy = Y(sg * face)
    swing(pen, xa, hy, r, (1, 0), (0, ydir))
    if d["kind"] == "cab_in":
        top = Y(9.0) if sg > 0 else Y(-8.3)
        for x0, x1 in ((xa - 1.0, xa), (xb, xb + 1.0)):
            pen.rect(x0, top, x1 - x0, 0.7 * S, lw=0.18, fill=(0.55, 0.55, 0.55))
    # width dimension on the corridor / passage side, 2.2 mm off the wall
    yw = Y(sg * wy)
    toward = -ydir
    off = 1.6 if d["kind"] == "store" else 2.2  # the store dimension must clear the centreline
    ydim = yw + toward * off
    ty = ydim + ((3.0 if d["kind"] == "store" else 3.7) if toward > 0 else -1.7)
    dimension(pen, (xa, yw), (xb, yw), (0, toward * off), text, (xa + xb) / 2, ty, "c")
    tcy = hy + ydir * (r + 3.4)
    tag(pen, xa + r / 2, tcy, str(d["no"]))
    pen.line(xa + r / 2, tcy - ydir * 1.8, xa, hy + ydir * r, w=0.13, cap=0)


def boundary(pen, x, doors_at, lw):
    """Vertical MVZ boundary line at paper x from shell to shell, cut at each fire door."""
    spans = []
    for d in doors_at:
        c, w = (10.0 if d["side"] == "P" else -10.0), (d["clear"] or 900) / 1000
        spans.append((c + w / 2, c - w / 2))
    ys = [HALF_B]
    for hi, lo in sorted(spans, reverse=True):
        ys += [hi, lo]
    ys.append(-HALF_B)
    for a, b in zip(ys[0::2], ys[1::2]):
        pen.line(x, Y(a), x, Y(b), w=lw)


def hull(pen, doors):
    """Shell, MVZ boundaries (with fire-door gaps), frame lines and the centreline."""
    for fr in range(110, 160, 10):
        x = X((fr - D.FR0) * D.FSP)
        pen.line(x, Y(HALF_B), x, Y(-HALF_B), w=0.1, color=LGREY, dash=DASHDOT, cap=0)
    for sg in (1, -1):
        pen.line(X(0), Y(sg * HALF_B), X(LEN_M), Y(sg * HALF_B), w=0.5)
        pen.line(X(0), Y(sg * 18.1), X(LEN_M), Y(sg * 18.1), w=0.25)
    for fr, x_m, inward in ((D.FR0, 0.0, 1), (D.FR1, LEN_M, -1)):
        at = [d for d in doors if d["kind"] == "zone" and d["fr"] == fr]
        boundary(pen, X(x_m), at, 0.7)
        boundary(pen, X(x_m) + inward * 1.2, at, 0.18)
    pen.line(X(-1.6), YC, X(LEN_M + 1.6), YC, w=0.18, dash=DASHDOT, cap=0)
    pen.text(X(LEN_M + 1.6) + 1.0, YC + 1.0, "CL", cap=2.0)


def frame_ruler(pen):
    """Frame ruler under the plan: a tick every frame (4 mm), a label every 5 frames."""
    y = 228.0
    pen.line(X(0), y, X(LEN_M), y, w=0.35, cap=0)
    for k in range(D.FR1 - D.FR0 + 1):
        x = X(k * D.FSP)
        long = k % 5 == 0
        pen.line(x, y, x, y + (2.8 if long else 1.4), w=0.25 if long else 0.15, cap=0)
        if long:
            pen.text(x, y + 6.6, f"FR {D.FR0 + k}", cap=2.0, anchor="c")
    pen.text(X0 - 3.0, y + 1.0, "FRAME No.", cap=1.8, anchor="r")
    pen.text(X0, y + 14.4, "FRAME SPACING 800 MM", cap=1.8)


def plan(pen, rev):
    doors = D.DOORS
    tagged = {(d["kind"], d["side"], d.get("cs")): d for d in doors if d["kind"].startswith("cab")}
    # frame numbers above the plan
    for fr in range(100, 161, 10):
        pen.text(X((fr - D.FR0) * D.FSP), Y(HALF_B) - 2.2, f"FR {fr}", cap=2.0, anchor="c", bold=fr in (100, 160))
    hull(pen, doors)
    gaps = cabin_blocks(pen, tagged)
    for (sg, wy), g in gaps.items():
        wall(pen, sg * wy, g)
    core(pen, doors)
    for name in D.STAIRS:
        stair(pen, name, rev)
    for d in doors:
        door(pen, d)
    # breadth dimension at the left, text reads upward
    xb = 34.0
    dimension(pen, (X(0), Y(HALF_B)), (X(0), Y(-HALF_B)), (xb - X(0), 0), None, 0, 0)
    pen.text(xb - 1.4, YC + pen.width("37000", 2.5) / 2, "37000", cap=2.5, rot=90)
    # orientation
    pen.text(X(LEN_M / 2), Y(HALF_B) - 8.5, "PORT", cap=2.5, anchor="c", bold=True)
    pen.text(X(LEN_M / 2), Y(-HALF_B) + 7.0, "STBD", cap=2.5, anchor="c", bold=True)
    pen.text(X(LEN_M) - 2, Y(HALF_B) - 8.5, "FWD", cap=2.5, anchor="r", bold=True)
    arrow(pen, X(LEN_M) - 0.5, Y(HALF_B) - 9.6, X(LEN_M) + 7.5, Y(HALF_B) - 9.6, lw=0.35, head=2.2)
    pen.text(X0 - 3.0, Y(HALF_B) - 8.5, "TO MVZ 2", cap=2.0, anchor="r")
    pen.text(X(LEN_M) + 1.0, Y(-HALF_B) + 7.0, "TO MVZ 4", cap=2.0, anchor="r")
    pen.text(X0, 19.0, f"DECK 5 GENERAL ARRANGEMENT, MVZ 3, FR {D.FR0} TO FR {D.FR1}", cap=3.5, bold=True)
    frame_ruler(pen)
    if rev == "B":
        cloud(pen)


def cloud(pen):
    """Revision cloud around the stair B enclosure plus the revision delta."""
    s = D.STAIRS["B"]
    xa, xb = X(s["x0"]) - 2.0, X(s["x0"] + D.ENC_LEN) + 2.0
    ya, yb = Y(-D.PASS_Y) - 2.0, Y(-D.CORE_Y) + 2.0
    corners = [(xa, ya), (xb, ya), (xb, yb), (xa, yb), (xa, ya)]
    for (px, py), (qx, qy) in zip(corners, corners[1:]):
        length = math.hypot(qx - px, qy - py)
        n = max(2, round(length / 3.4))
        th = math.degrees(math.atan2(qy - py, qx - px))
        for i in range(n):
            ax, ay = px + (qx - px) * i / n, py + (qy - py) * i / n
            bx, by = px + (qx - px) * (i + 1) / n, py + (qy - py) * (i + 1) / n
            pen.arc((ax + bx) / 2, (ay + by) / 2, length / n / 2, th + 180, th + 360, w=0.35, color=RED)
    tx, ty = xb + 3.0, ya - 3.0
    pen.poly([(tx, ty - 3.2), (tx - 3.0, ty + 2.2), (tx + 3.0, ty + 2.2)], w=0.3, color=RED, closed=True)
    pen.text(tx, ty + 1.7, "B", cap=2.2, anchor="c", bold=True, color=RED)


# ---------------------------------------------------------------- right-hand column
def box(pen, x, y, w, h, title):
    pen.rect(x, y, w, h, lw=0.35)
    pen.line(x, y + 6.0, x + w, y + 6.0, w=0.25, cap=0)
    pen.text(x + 2, y + 4.2, title, cap=2.2, bold=True)


def particulars(pen):
    box(pen, RIGHT, 18, 106, 38, "PARTICULARS OF SHIP (REFERENCE)")
    rows = [f"{D.SHIP_NAME}  HULL {D.HULL}", f"LOA {D.GA_LOA:.2f} m",
            f"LPP {D.SHIP['length_between_perpendiculars'][0]:.2f} m", f"BREADTH MLD {D.SHIP['beam'][0]:.2f} m",
            f"FRAME SPACING {D.SHIP['frame_spacing'][0]} mm"]
    for i, r in enumerate(rows):
        pen.text(RIGHT + 3, 29.0 + i * 5.2, r, cap=2.5, bold=(i == 1))


def legend(pen):
    y0 = 60
    box(pen, RIGHT, y0, 106, 50, "LEGEND")
    # door
    x, y = RIGHT + 6, y0 + 15
    pen.line(x, y, x + 5, y, w=0.35)
    swing(pen, x, y, 4.5, (1, 0), (0, -1))
    pen.text(RIGHT + 18, y - 0.5, "DOOR SWING, TAG = DOOR NUMBER", cap=2.0)
    # stair
    y += 7.5
    pen.rect(x - 1, y - 2.5, 8, 5, lw=0.25)
    for i in range(1, 8):
        pen.line(x - 1 + i, y - 2.5, x - 1 + i, y + 2.5, w=0.1, cap=0)
    pen.text(RIGHT + 18, y + 0.5, "STAIR: CLEAR WIDTH (MM), PERSONS SERVED (P)", cap=2.0)
    for lw, label, dash, col in ((0.7, "MVZ BOUNDARY (A-60 DIVISION)", None, BLACK), (0.35, "CORRIDOR AND CORE WALLS", None, BLACK),
                                 (0.18, "CABIN PARTITION", None, BLACK), (0.1, "FRAME LINE", DASHDOT, GREY)):
        y += 6.0
        pen.line(x - 1, y, x + 7, y, w=lw, dash=dash, color=col, cap=0)
        pen.text(RIGHT + 18, y + 0.7, label, cap=2.0)


def key_plan(pen):
    y0 = 114
    box(pen, RIGHT, y0, 106, 38, "KEY PLAN, NOT TO SCALE")
    xs, xe = RIGHT + 6, RIGHT + 100
    deck, wl = y0 + 22, y0 + 30
    zw = (xe - xs) / 7
    pen.rect(xs + 2 * zw, y0 + 9, zw, wl - y0 - 10.5, lw=0.1, color=(0.82, 0.82, 0.82), fill=(0.82, 0.82, 0.82))
    pen.poly([(xs, deck), (xs + 2, wl), (xe - 8, wl), (xe, deck)], w=0.3, closed=True)
    pen.rect(xs + 8, y0 + 15, xe - xs - 22, deck - y0 - 15, lw=0.3)
    for i in range(8):
        pen.line(xs + i * zw, y0 + 9, xs + i * zw, wl - 1.5, w=0.3 if i in (2, 3) else 0.18, cap=0)
    for i in range(7):
        pen.text(xs + (i + 0.5) * zw, y0 + 13, str(i + 1), cap=2.0, anchor="c", bold=i == 2)
    pen.line(xs + 2, y0 + 25, xe - 4, y0 + 25, w=0.18, dash="[2 1] 0", cap=0)
    pen.text(xs + 3, y0 + 24.2, "DECK 5", cap=1.6)
    pen.text(RIGHT + 3, y0 + 36, "MAIN VERTICAL ZONES 1-7, THIS SHEET = MVZ 3", cap=1.8)


def scale_bar(pen):
    """Graphical scale 0 to 15 m: 5 m = 25 mm on paper at 1:200."""
    y = 162
    pen.text(RIGHT, y - 3, "GRAPHICAL SCALE", cap=2.0, bold=True)
    for i in range(3):
        pen.rect(RIGHT + 4 + i * 25, y, 25, 1.6, lw=0.18, fill=BLACK if i % 2 == 0 else WHITE)
    for i in range(4):
        pen.text(RIGHT + 4 + i * 25, y + 5.2, str(i * 5), cap=1.8, anchor="c")
    pen.text(RIGHT + 4 + 75 + 4, y + 5.2, "m", cap=1.8)


def references(pen):
    y = 176
    pen.text(RIGHT, y, "REFERENCE DOCUMENTS", cap=2.0, bold=True)
    for i, t in enumerate(("SYN-SPEC-001 OUTLINE SPECIFICATION, REV 2", "SYN-DS-105 DOOR SCHEDULE DECK 5",
                           "EA-101 EVACUATION ANALYSIS, REV 1", "SYN-GA-104 AND SYN-GA-106 GA DECKS 4 AND 6")):
        pen.text(RIGHT, y + 4.6 + i * 4.2, t, cap=1.8)


def revision_table(pen, rev):
    x0, y0 = RIGHT, 213
    cols = [(0, 10, "REV"), (10, 32, "DATE"), (32, 86, "DESCRIPTION"), (86, 96, "BY"), (96, 106, "CHKD")]
    pen.rect(x0, y0, 106, 26, lw=0.35)
    for xa, xb, h in cols:
        pen.text(x0 + xa + 1.2, y0 + 3.7, h, cap=1.8, bold=True)
        if xa:
            pen.line(x0 + xa, y0, x0 + xa, y0 + 26, w=0.25, cap=0)
    for r in range(1, 5):
        pen.line(x0, y0 + r * 5.2 + 0.0, x0 + 106, y0 + r * 5.2, w=0.25, cap=0)
    rows = [("A",) + D.GA["revs"]["A"]] + ([("B",) + D.GA["revs"]["B"]] if rev == "B" else [])
    for r, (rv, date, desc) in enumerate(rows):
        yy = y0 + (r + 1) * 5.2 + 3.7
        for (xa, _, _), t in zip(cols, (rv, date, desc, "GEN", "GEN")):
            pen.text(x0 + xa + 1.2, yy, t, cap=1.9)


def title_block(pen, rev):
    x0, x1, y0, y1 = 220, 410, 242, 287
    pen.rect(x0, y0, x1 - x0, y1 - y0, lw=0.7)
    for y in (254, 268, 278):
        pen.line(x0, y, x1, y, w=0.35, cap=0)
    for x, ya, yb in ((265, 242, 254), (285, 268, 278), (300, 268, 278), (335, 268, 278), (365, 268, 278),
                      (265, 278, 287), (305, 278, 287), (330, 278, 287)):
        pen.line(x, ya, x, yb, w=0.35, cap=0)

    def cell(xa, ya, label, value, vy, cap=2.8, bold=False):
        if label:
            pen.text(xa + 1.2, ya + 2.6, label, cap=1.5)
        pen.text(xa + 1.5, vy, value, cap=cap, bold=bold)

    cell(220, 242, "COMPANY", D.YARD.split(" (")[0], 249.0, cap=2.4, bold=True)
    pen.text(221.5, 252.8, "(INVENTED)", cap=1.6)
    cell(265, 242, "PROJECT", f"{D.SHIP_NAME}   YARD HULL {D.HULL}", 250.2, cap=3.0, bold=True)
    cell(220, 254, "TITLE", D.GA["title"], 265.0, cap=4.0, bold=True)
    cell(220, 268, "DRAWING NO.", D.GA["no"], 275.4, cap=3.0, bold=True)
    cell(285, 268, "REV", rev, 275.6, cap=3.5, bold=True)
    cell(300, 268, "DATE", D.GA["revs"][rev][0], 275.4, cap=2.6)
    cell(335, 268, "", "SHEET SIZE " + D.GA["size"], 274.2, cap=2.2)
    cell(365, 268, "", "SCALE " + D.GA["scale_note"], 274.6, cap=3.0, bold=True)
    cell(220, 278, "DRAWN", "SYN-GEN (SCRIPT)", 284.4, cap=1.9)
    cell(265, 278, "CHECKED", "N/A (SYNTHETIC)", 284.4, cap=1.9)
    cell(305, 278, "SHEET", "1 OF 1", 284.4, cap=1.9)
    cell(330, 278, "", D.SYNTH, 283.6, cap=2.1, bold=True)


def notes(pen):
    y = 249.0
    pen.text(22, y, "NOTES", cap=2.2, bold=True)
    lines = ["1. DIMENSIONS IN MM.",
             "2. DOOR AND STAIR WIDTHS SHOWN ARE CLEAR WIDTHS UNLESS NOTED.",
             "3. P = PERSONS SERVED BY THE STAIR (ESCAPE ANALYSIS).",
             "4. NUMBERED DOORS ARE LISTED IN DOOR SCHEDULE SYN-DS-105.",
             "5. TYPICAL CABIN DOORS ARE NOT NUMBERED, SEE CABIN ARRANGEMENT DRAWINGS.",
             f"6. {D.SYNTH}."]
    for i, t in enumerate(lines):
        pen.text(22, y + 5.0 + i * 4.2, t, cap=2.0)


def draw(pen, rev):
    """Draw the whole sheet for revision 'A' or 'B'."""
    border(pen)
    plan(pen, rev)
    particulars(pen)
    legend(pen)
    key_plan(pen)
    scale_bar(pen)
    references(pen)
    revision_table(pen, rev)
    title_block(pen, rev)
    notes(pen)
