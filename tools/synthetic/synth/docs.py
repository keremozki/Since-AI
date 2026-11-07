"""Text documents: outline specification SYN-SPEC-001 (A4, 2 pages) and evacuation analysis EA-101."""
import re

import pymupdf

from . import data as D
from .pen import MM, RED, Pen

A4 = (210, 297)
L, R = 20.0, 190.0  # text margins, mm
META_DATE = "D:20261001000000Z"


def new_doc(title, subject):
    doc = pymupdf.open()
    doc.set_metadata({"title": title, "author": "synthetic generator", "subject": subject,
                      "creator": "tools/synthetic", "producer": "PyMuPDF", "creationDate": META_DATE,
                      "modDate": META_DATE, "keywords": "SYNTHETIC TEST DATA"})
    return doc


ID_RE = re.compile(rb"/ID\[(?:<[0-9A-Fa-f]*>|\((?:\\.|[^\\)])*\))+\]")


def save(doc, path):
    """Save with a fixed trailer ID (hex or literal string form) so the bytes are reproducible."""
    data = ID_RE.sub(b"/ID[<" + b"0" * 32 + b"><" + b"0" * 32 + b">]", doc.tobytes(garbage=4, deflate=True))
    with open(path, "wb") as f:
        f.write(data)


def new_page(doc):
    page = doc.new_page(width=A4[0] * MM, height=A4[1] * MM)
    return Pen(page)


def wrap(pen, text, width, cap):
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if pen.width(t, cap) <= width:
            cur = t
        else:
            lines.append(cur)
            cur = w
    return lines + [cur]


def para(pen, y, text, cap=2.5, width=R - L, pitch=4.6):
    for ln in wrap(pen, text, width, cap):
        pen.text(L, y, ln, cap=cap)
        y += pitch
    return y


def heading(pen, y, num, title):
    pen.text(L, y, f"{num}. {title}", cap=3.1, bold=True)
    pen.line(L, y + 1.8, R, y + 1.8, w=0.35, cap=0)
    return y + 5.0


def table(pen, y, rows, split=95.0, pitch=6.4):
    """Two-column grid table; returns the y below it."""
    n = len(rows)
    pen.rect(L, y, R - L, pitch * n, lw=0.3)
    pen.line(split, y, split, y + pitch * n, w=0.25, cap=0)
    for i, (a, b) in enumerate(rows):
        if i:
            pen.line(L, y + i * pitch, R, y + i * pitch, w=0.2, cap=0)
        pen.text(L + 2, y + i * pitch + 4.4, a, cap=2.5)
        pen.text(split + 2, y + i * pitch + 4.4, b, cap=2.5)
    return y + pitch * n + 7


def banner(pen, y):
    pen.rect(L, y, R - L, 7.5, lw=0.6, color=RED)
    pen.text((L + R) / 2, y + 5.2, D.SYNTH, cap=3.0, anchor="c", bold=True, color=RED)


def strip(pen, doc_no, rev, date, page, pages, title):
    """Document title strip at the foot of the page."""
    y, h = 268.0, 19.0
    pen.rect(L, y, R - L, h, lw=0.6)
    pen.line(L, y + 9.5, R, y + 9.5, w=0.3, cap=0)
    for x in (80, 115, 150):
        pen.line(x, y + 9.5, x, y + h, w=0.3, cap=0)
    pen.text(L + 2, y + 6.2, title, cap=2.6, bold=True)
    pen.text(R - 2, y + 6.2, D.SYNTH, cap=2.2, anchor="r", bold=True)
    for x, lab, val in ((L, "DOCUMENT NO.", doc_no), (80, "REV", rev), (115, "DATE", date), (150, "PAGE", f"{page} OF {pages}")):
        pen.text(x + 2, y + 12.8, lab, cap=1.5)
        pen.text(x + 2, y + 17.2, val, cap=2.6, bold=True)


def spec(path):
    """SYN-SPEC-001 rev 2: outline specification with the planted raft gap (no liferaft capacity)."""
    S = D.SHIP
    doc = new_doc("Outline Specification SYN-SPEC-001", D.SYNTH)
    title = f"OUTLINE SPECIFICATION {D.SHIP_NAME}"
    # ---- page 1
    pen = new_page(doc)
    pen.text(L, 20, "OUTLINE SPECIFICATION", cap=6.0, bold=True)
    pen.text(L, 29, f"{D.SHIP_NAME}   Yard hull {D.HULL}", cap=3.6)
    banner(pen, 33)
    y = heading(pen, 52, 1, "General")
    y = table(pen, y, [("Ship type", "Passenger ship"), ("Voyages", "International voyages (not short international voyages)"),
                       ("Regulations", "SOLAS 1974 as amended, FSS Code, LSA Code"),
                       ("Accessibility", "ADA / PVAG for accessible cabins and routes")])
    y = heading(pen, y + 1, 2, "Principal particulars")
    f = lambda k, nd=2: f"{S[k][0]:.{nd}f} m"
    y = table(pen, y, [("Length overall", f("length_overall")), ("Length between perpendiculars", f("length_between_perpendiculars")),
                       ("Breadth, moulded", f("beam")), ("Breadth, greatest", f("breadth_greatest")),
                       ("Depth to main deck", f("depth")), ("Design draught", f("design_draft")),
                       ("Gross tonnage", f"{S['gross_tonnage'][0]:,}"), ("Frame spacing", f"{S['frame_spacing'][0]} mm")])
    y = heading(pen, y + 1, 3, "Complement")
    y = table(pen, y, [("Passengers", f"{S['passengers'][0]:,}"), ("Crew", f"{S['crew_complement'][0]:,}"),
                       ("Persons on board (certified)", f"{S['persons_on_board'][0]:,}")])
    y = heading(pen, y + 1, 4, "Registry and dates")
    y = table(pen, y, [("Flag", S["flag"][0]), ("Contract date", "1 March 2025"), ("Keel laying", "15 February 2027"),
                       ("Delivery", "30 May 2029")])
    y = heading(pen, y + 1, 5, "Subdivision")
    pen.text(L, y + 1, f"Main vertical zones: {S['main_vertical_zones'][0]}", cap=2.8, bold=True)
    para(pen, y + 7, "The ship is divided into main vertical zones by A-60 class divisions. Each zone has its own "
         "escape stairs and fire doors. Zone 3 covers frames 100 to 160.")
    strip(pen, "SYN-SPEC-001", "2", "2026-09-15", 1, 2, title)
    pen.done()
    # ---- page 2
    pen = new_page(doc)
    pen.text(L, 17, f"SYN-SPEC-001 rev 2 / {D.SHIP_NAME}", cap=2.6)
    pen.text(R, 17, D.SYNTH, cap=2.6, anchor="r", bold=True, color=RED)
    pen.line(L, 20, R, 20, w=0.3, cap=0)
    y = heading(pen, 32, 6, "Life-saving appliances")
    (np_, cp), (ns, cs) = D.LIFEBOATS["port"], D.LIFEBOATS["starboard"]
    y = table(pen, y, [("Lifeboats, port side", f"{np_} x {cp} persons = {np_ * cp:,} persons"),
                       ("Lifeboats, starboard side", f"{ns} x {cs} persons = {ns * cs:,} persons"),
                       ("Liferafts", f"{D.LIFERAFTS} davit-launched liferafts")])
    y = para(pen, y, "Lifeboats are totally enclosed and launched from davits. All survival craft and launching "
             "appliances comply with the LSA Code.")
    y = heading(pen, y + 4, 7, "Evacuation")
    pen.text(L, y + 1, "Evacuation analysis: see EA-101", cap=2.8, bold=True)
    y = para(pen, y + 7, "An evacuation analysis is carried out under SOLAS II-2/13.3.2.7 using the simplified method "
             "and is issued as a separate document.")
    y = heading(pen, y + 4, 8, "Accessibility")
    y = para(pen, y, "Accessible cabins are on accessible routes. Door and stair widths on these routes are shown on "
             "the general arrangement drawings and in the door and stair schedules. The yard issues the schedules "
             "with each drawing revision.")
    y = heading(pen, y + 4, 9, "Documents")
    y = table(pen, y, [("SYN-SPEC-001", "Outline specification, this document"), ("SYN-GA-105", "General arrangement deck 5 (MVZ 3)"),
                       ("SYN-DS-105", "Door schedule deck 5"), ("EA-101", "Evacuation analysis, simplified method")])
    strip(pen, "SYN-SPEC-001", "2", "2026-09-15", 2, 2, title)
    pen.done()
    save(doc, path)


def evac(path):
    """EA-101 rev 1: evacuation analysis, simplified method of MSC.1/Circ.1533."""
    S, E = D.SHIP, D.EVAC
    doc = new_doc("EA-101 Evacuation analysis", D.SYNTH)
    title = "EA-101 EVACUATION ANALYSIS"
    pen = new_page(doc)
    pen.text(L, 20, "EA-101 Evacuation analysis (simplified method, MSC.1/Circ.1533)", cap=3.4, bold=True)
    pen.text(L, 30, f"{D.SHIP_NAME}   Yard hull {D.HULL}", cap=3.2)
    banner(pen, 40)
    y = table(pen, 56, [("Document no.", "EA-101"), ("Revision", "1"), ("Date", "2026-09-30"),
                        ("Prepared by", "SYN-GEN (script)")])
    y = heading(pen, y + 2, 1, "Scope")
    y = para(pen, y, "This report gives the evacuation analysis of the ship required by SOLAS II-2/13.3.2.7. It uses the "
             "simplified method of MSC.1/Circ.1533. It covers the whole ship and both assessment cases, night and day.")
    y = heading(pen, y + 4, 2, "Ship data")
    y = table(pen, y, [("Persons on board (certified)", f"{S['persons_on_board'][0]:,}"),
                       ("Passengers", f"{S['passengers'][0]:,}"), ("Crew", f"{S['crew_complement'][0]:,}"),
                       ("Main vertical zones", str(S["main_vertical_zones"][0]))])
    strip(pen, "EA-101", "1", "2026-09-30", 1, 2, title)
    pen.done()
    pen = new_page(doc)
    pen.text(L, 17, f"EA-101 rev 1 / {D.SHIP_NAME}", cap=2.6)
    pen.text(R, 17, D.SYNTH, cap=2.6, anchor="r", bold=True, color=RED)
    pen.line(L, 20, R, 20, w=0.3, cap=0)
    y = heading(pen, 32, 3, "Method")
    y = para(pen, y, "The total evacuation time is found from the response and travel time R+T and the embarkation and "
             "launching time E+L:")
    pen.text(L + 6, y + 1.5, "Total = 1.25 (R+T) + 2/3 (E+L)", cap=2.8, bold=True)
    y = heading(pen, y + 9, 4, "Results")
    cols = [L, 70, 105, 140]
    heads = ("Case", "R+T (min)", "E+L (min)", "Total (min)")
    rows = [("Case 1 (night)", f"{E['rt']:.1f}", f"{E['el']:.1f}", f"{E['total']:.1f}"),
            (E["case2"]["name"], f"{E['case2']['rt']:.1f}", f"{E['case2']['el']:.1f}", f"{E['case2']['total']:.1f}")]
    pen.rect(L, y, R - L, 6.4 * 3, lw=0.3)
    for i in range(1, 3):
        pen.line(L, y + 6.4 * i, R, y + 6.4 * i, w=0.2, cap=0)
    for x in cols[1:]:
        pen.line(x - 2, y, x - 2, y + 6.4 * 3, w=0.25, cap=0)
    for x, h in zip(cols, heads):
        pen.text(x + 1, y + 4.4, h, cap=2.5, bold=True)
    for i, r in enumerate(rows):
        for x, t in zip(cols, r):
            pen.text(x + 1, y + 6.4 * (i + 1) + 4.4, t, cap=2.5)
    y += 6.4 * 3 + 6
    y = para(pen, y, f"Governing case: {E['case']}")
    y = para(pen, y + 1, f"Worked result for {E['case']}: 1.25 x {E['rt']:.1f} + 2/3 x {E['el']:.1f} = "
             f"{1.25 * E['rt']:.1f} + {2 / 3 * E['el']:.1f} = {E['total']:.1f} min.")
    y = heading(pen, y + 4, 5, "Conclusion")
    y = para(pen, y, f"The governing total evacuation time is {E['total']:.1f} min, {E['case']}. The result is to be "
             "compared with the criterion of SOLAS II-2/13.3.2.7 for a ship with this number of main vertical zones.")
    strip(pen, "EA-101", "1", "2026-09-30", 2, 2, title)
    pen.done()
    save(doc, path)
