"""truth.json: file list, every stated fact per file, planted items and expected check results."""
from . import data as D
from .tables import HEAD_ROW

SPEC, EA, XLSX, DCSV, SCSV, IFC = ("spec.pdf", "evacuation-analysis-EA-101.pdf", "door-schedule.xlsx",
                                   "door-schedule.csv", "stair-schedule.csv", "model.ifc")
GA_A, GA_B, GA_S, GA_SCAN_PDF, GA_SCAN_PNG = ("ga-deck5-revA.pdf", "ga-deck5-revB.pdf", "ga-deck5-revA-stroked.pdf",
                                              "ga-deck5-revA-scan.pdf", "ga-deck5-revA-scan.png")
GA_FILES = [(GA_A, "A"), (GA_B, "B"), (GA_S, "A"), (GA_SCAN_PDF, "A"), (GA_SCAN_PNG, "A")]
GA_REV_A = [GA_A, GA_S, GA_SCAN_PDF, GA_SCAN_PNG]
ALL_GA = [f for f, _ in GA_FILES]
SHEET_NAME = "DOOR SCHEDULE DECK 5"
SCAN_NOTE = "image only: readable by OCR or vision, not by text extraction"


def file_list():
    ga = "A3 landscape GA deck 5 (MVZ 3), drawn at 1:200, title block says 1:100. "
    return [
        dict(file=SPEC, kind="outline specification", text_layer=True, doc_no="SYN-SPEC-001", rev="2",
             holds="Principal particulars, complement, registry and dates, MVZ count, life-saving appliances (no liferaft capacity), reference to EA-101"),
        dict(file=GA_A, kind="general arrangement drawing", text_layer=True, doc_no=D.GA["no"], rev="A",
             holds=ga + "Rev A: stair B 850 mm. Particulars box says LOA 300.10 m."),
        dict(file=GA_B, kind="general arrangement drawing", text_layer=True, doc_no=D.GA["no"], rev="B",
             holds=ga + "Rev B: stair B widened to 1000 mm, revision cloud, revision row B."),
        dict(file=GA_S, kind="general arrangement drawing (stroked text)", text_layer=False, doc_no=D.GA["no"], rev="A",
             holds="Rev A geometry with every character drawn as single-stroke line paths: no text layer, like a plotted CAD drawing."),
        dict(file=GA_SCAN_PDF, kind="general arrangement scan (image-only PDF)", text_layer=False, doc_no=D.GA["no"], rev="A",
             holds="Rev A rasterized at 150 dpi, grey, rotated 0.4 degrees, blur and noise. One JPEG image per page."),
        dict(file=GA_SCAN_PNG, kind="general arrangement scan (PNG)", text_layer=False, doc_no=D.GA["no"], rev="A",
             holds="Same scan as the image-only PDF, lossless PNG."),
        dict(file=XLSX, kind="door schedule", text_layer=None, doc_no="SYN-DS-105", rev="A",
             holds=f"Sheet '{SHEET_NAME}': title row 1, note row 2, header row {HEAD_ROW}, 12 door rows. Blank cells: 5108 clear width, 5112 opening depth."),
        dict(file=DCSV, kind="door schedule (csv)", text_layer=None, doc_no="SYN-DS-105", rev="A",
             holds="Same table as the xlsx, header in row 1. No in-file marking, a comment row would break CSV parsers."),
        dict(file=SCSV, kind="stair schedule (csv)", text_layer=None, doc_no="SYN-SS-105", rev="A",
             holds="Stairs A, B, C on deck 5 with rev A values (B = 850). No in-file marking, see door-schedule.csv."),
        dict(file=IFC, kind="IFC4 model", text_layer=None, doc_no=None, rev="A",
             holds="12 IfcDoor (SYN_DoorData, OverallWidth = clear + 100) and 3 IfcStairFlight (SYN_EscapeData); stair C 950, door 5110 clear 900, door 5108 no ClearWidth, door 5112 no OpeningDepth."),
        dict(file=EA, kind="evacuation analysis", text_layer=True, doc_no="EA-101", rev="1",
             holds="Simplified method MSC.1/Circ.1533: R+T 38.0, E+L 30.0, total 67.5 min, governing Case 1 (night), 7 MVZ."),
    ]


class Facts:
    def __init__(self):
        self.items = []

    def add(self, subject, prop, value, unit, file, where, note="", page=None, sheet=None, cell=None):
        self.items.append(dict(subject=subject, property=prop, value=value, unit=unit, file=file, page=page,
                               sheet=sheet, cell=cell, where=where, note=note))


def spec_facts(f):
    p1 = {"length_overall": "Principal particulars: Length overall",
          "length_between_perpendiculars": "Principal particulars: Length between perpendiculars",
          "beam": "Principal particulars: Breadth, moulded", "breadth_greatest": "Principal particulars: Breadth, greatest",
          "depth": "Principal particulars: Depth to main deck", "design_draft": "Principal particulars: Design draught",
          "gross_tonnage": "Principal particulars: Gross tonnage", "frame_spacing": "Principal particulars: Frame spacing",
          "passengers": "Complement: Passengers", "crew_complement": "Complement: Crew",
          "persons_on_board": "Complement: Persons on board (certified)", "flag": "Registry and dates: Flag",
          "contract_date": "Registry and dates: Contract date (1 March 2025)",
          "keel_date": "Registry and dates: Keel laying (15 February 2027)",
          "delivery_date": "Registry and dates: Delivery (30 May 2029)",
          "main_vertical_zones": "Subdivision: 'Main vertical zones: 7'", "ship_type": "General: Ship type",
          "voyage_type": "General: Voyages"}
    for k, where in p1.items():
        v, u = D.SHIP[k]
        f.add("ship", k, v, u, SPEC, where, "PLANTED P-LOA: the GA says 300.10 m" if k == "length_overall" else "", page=1)
    for side, (n, cap) in D.LIFEBOATS.items():
        sub = f"lifeboats:{side}"
        f.add(sub, "capacity_persons", n * cap, "persons", SPEC, f"Life-saving appliances: {n} x {cap} persons = {n * cap:,}", page=2)
        f.add(sub, "boat_count", n, "", SPEC, "Life-saving appliances", page=2)
        f.add(sub, "persons_per_boat", cap, "persons", SPEC, "Life-saving appliances", page=2)
    f.add("liferafts", "count", D.LIFERAFTS, "", SPEC, "Life-saving appliances: '16 davit-launched liferafts'",
          "PLANTED P-RAFT-CAP: no capacity stated anywhere", page=2)
    f.add("evacuation", "analysis_present", "yes", "", SPEC, "Evacuation: 'Evacuation analysis: see EA-101'", page=2)


def ga_facts(f, file, rev):
    scan = SCAN_NOTE if "scan" in file else ("no text layer, strokes only" if "stroked" in file else "")
    n = lambda s: (s + "; " + scan) if scan else s
    f.add("ship", "length_overall", D.GA_LOA, "m", file, "Particulars box: 'LOA 300.10 m'", n("PLANTED P-LOA: spec says 299.80 m"), page=1)
    f.add("ship", "length_between_perpendiculars", 271.00, "m", file, "Particulars box: LPP", n(""), page=1)
    f.add("ship", "beam", 37.00, "m", file, "Particulars box: BREADTH MLD", n(""), page=1)
    f.add("ship", "beam", 37000, "mm", file, "Breadth dimension left of the plan, text reads upward", n("same value as the box, in mm"), page=1)
    f.add("ship", "frame_spacing", 800, "mm", file, "Particulars box and frame ruler caption", n(""), page=1)
    f.add("deck:5", "main_vertical_zone", D.STAIR_MVZ, "", file, "Title 'GENERAL ARRANGEMENT DECK 5 (MVZ 3)'", n(""), page=1)
    for d in D.DOORS:
        if d["clear"] is not None:
            note = "PLANTED P-DOOR-5110: IFC says 900" if d["no"] == 5110 else ""
            f.add(f"door-number:{d['no']}", "clear_width", d["clear"], "mm", file, "Width dimension beside the door swing", n(note), page=1)
    for name in D.STAIRS:
        w = D.stair_flight(name, rev)
        note = {"B": "PLANTED P-STAIR-B (fails FSS 950 mm)" if rev == "A" else "rev B: widened to 1000, passes",
                "C": "PLANTED P-STAIR-C: IFC says 950"}.get(name, "")
        f.add(f"stair:{name}", "clear_width", w, "mm", file, "Dimension line across the flight", n(note), page=1)
        f.add(f"stair:{name}", "persons_served", D.STAIRS[name]["persons"], "persons", file, "Label under 'STAIR x', e.g. '95 P'", n(""), page=1)
    f.add(f"drawing:{D.GA['no']}", "scale_note", D.GA["scale_note"], "", file, "Title block: 'SCALE 1:100'",
          n("PLANTED P-SCALE: the sheet is really drawn at 1:200 (frame ruler 4 mm per frame)"), page=1)
    f.add(f"drawing:{D.GA['no']}", "revision", rev, "", file, "Title block REV", n(""), page=1)
    f.add(f"drawing:{D.GA['no']}", "sheet_size", D.GA["size"], "", file, "Title block 'SHEET SIZE A3'", n(""), page=1)


def schedule_facts(f, file, first_row, is_xlsx):
    from .tables import door_rows
    for i, row in enumerate(door_rows()):
        d, r = D.DOORS[i], first_row + i
        sub = f"door-number:{d['no']}"
        sheet = SHEET_NAME if is_xlsx else None
        f.add(sub, "clear_width", d["clear"], "mm", file, "CLEAR WIDTH (mm)",
              {5108: "PLANTED P-DOOR-MISSING: blank cell", 5110: "PLANTED P-DOOR-5110: IFC says 900",
               5107: "PLANTED P-DOOR-800", 5104: "with depth 700 needs 915 (P-DOOR-DEPTH)"}.get(d["no"], ""),
              sheet=sheet, cell=f"D{r}")
        f.add(sub, "opening_depth", d["depth"], "mm", file, "OPENING DEPTH (mm)",
              "PLANTED P-DOOR-DEPTH-UNKNOWN: blank cell" if d["no"] == 5112 else "", sheet=sheet, cell=f"E{r}")
        f.add(sub, "accessible_route", "yes" if d["acc"] else "no", "", file, "ACCESSIBLE ROUTE", "written YES/NO",
              sheet=sheet, cell=f"F{r}")


def stair_csv_facts(f):
    for i, (name, s) in enumerate(D.STAIRS.items(), 2):
        sub = f"stair:{name}"
        f.add(sub, "clear_width", s["clear"], "mm", SCSV, "CLEAR WIDTH (mm)", "rev A value" if name == "B" else "", cell=f"C{i}")
        f.add(sub, "persons_served", s["persons"], "persons", SCSV, "PERSONS SERVED", cell=f"D{i}")
        f.add(sub, "main_vertical_zone", D.STAIR_MVZ, "", SCSV, "MVZ", cell=f"E{i}")


def ifc_facts(f):
    for d in D.DOORS:
        sub = f"door-number:{d['no']}"
        clear = d.get("ifc_clear", d["clear"])
        where = "IfcDoor SYN_DoorData."
        note = {5108: "PLANTED P-DOOR-MISSING: property absent", 5110: "PLANTED P-DOOR-5110: schedule and GA say 1000"}.get(d["no"], "")
        f.add(sub, "clear_width", clear, "mm", IFC, where + "ClearWidth", note)
        f.add(sub, "opening_depth", d["depth"], "mm", IFC, where + "OpeningDepth",
              "PLANTED P-DOOR-DEPTH-UNKNOWN: property absent" if d["no"] == 5112 else "")
        f.add(sub, "accessible_route", "yes" if d["acc"] else "no", "", IFC, where + "AccessibleRoute", "Yes/No")
        if clear is not None:
            f.add(sub, "ifc_overall_width", clear + 100, "mm", IFC, "IfcDoor.OverallWidth",
                  "frame opening = clear + 100, NOT the clear width (P-IFC-OVERALL)")
    for name, s in D.STAIRS.items():
        sub = f"stair:{name}"
        note = {"C": "PLANTED P-STAIR-C: schedule and GA say 1000"}.get(name, "")
        f.add(sub, "clear_width", s["ifc"], "mm", IFC, "IfcStairFlight SYN_EscapeData.ClearWidth", note)
        f.add(sub, "persons_served", s["persons"], "persons", IFC, "IfcStairFlight SYN_EscapeData.PersonsServed")


def evac_facts(f):
    E, S = D.EVAC, D.SHIP
    f.add("evacuation", "time_minutes", E["total"], "min", EA, "Results table, governing case Case 1 (night)", "total 1.25(R+T) + 2/3(E+L)", page=2)
    f.add("evacuation", "rt_minutes", E["rt"], "min", EA, "Results table, R+T", page=2)
    f.add("evacuation", "el_minutes", E["el"], "min", EA, "Results table, E+L", page=2)
    f.add("evacuation", "governing_case", E["case"], "", EA, "'Governing case: Case 1 (night)'", page=2)
    f.add("evacuation", "analysis_present", "yes", "", EA, "the document itself, EA-101 rev 1", page=1)
    c2 = E["case2"]
    for prop, key, unit in (("time_minutes", "total", "min"), ("rt_minutes", "rt", "min"), ("el_minutes", "el", "min")):
        f.add("evacuation:case2", prop, c2[key], unit, EA, "Results table, Case 2 (day)", "not the governing case", page=2)
    for k, w in (("persons_on_board", "Persons on board (certified)"), ("passengers", "Passengers"),
                 ("crew_complement", "Crew"), ("main_vertical_zones", "Main vertical zones")):
        f.add("ship", k, S[k][0], S[k][1], EA, f"Ship data: {w}", page=1)


# ---------------------------------------------------------------- expected results
def door_status(d):
    """Expected door_clear_width status from the door rules: 815 mm, or 915 mm if the opening is deeper than 610 mm."""
    clear, depth = d["clear"], d["depth"]
    if not d["acc"]:
        return "not_applicable", "Crew store, not on an accessible route: the accessible-door rule does not apply."
    if clear is not None and d.get("ifc_clear", clear) != clear:
        return "conflict", f"Schedule and GA say {clear} mm, the IFC says {d['ifc_clear']} mm (each value alone would meet 815 mm)."
    if clear is None:
        return "cant_tell", "Clear width is blank in the schedule and absent in the IFC."
    if depth is None:
        if clear >= 915:
            return "pass", "Meets 915 mm, so passes whatever the depth is."
        if clear < 815:
            return "fail", "Under 815 mm, fails whatever the depth is."
        return "cant_tell", f"{clear} mm is under 915 mm and the opening depth is not stated, so the limit (815 or 915) is unknown."
    limit = 915 if depth > 610 else 815
    why = f"{clear} mm clear against {limit} mm required (opening depth {depth} mm, {'over' if depth > 610 else 'not over'} 610 mm)."
    return ("pass" if clear >= limit else "fail"), why


def expected():
    E = []
    for d in D.DOORS:
        st, why = door_status(d)
        E.append(dict(check="door_clear_width", subject=f"door-number:{d['no']}", status=st, why=why))
    need = lambda p: D.fss_required(p)
    s = D.STAIRS
    E += [
        dict(check="stair_width", subject="stair:A", status="pass", why=f"1200 mm against {need(110)} mm (900 + 10 x (110 - 90)) for 110 persons."),
        dict(check="stair_width", subject="stair:B", status="fail", scope="rev A set (ga-deck5-revA*, stair-schedule.csv, model.ifc)",
             why=f"850 mm against {need(95)} mm (900 + 10 x (95 - 90)) for 95 persons."),
        dict(check="stair_width", subject="stair:B", status="pass", scope="ga-deck5-revB.pdf on its own",
             why=f"1000 mm against {need(95)} mm for 95 persons."),
        dict(check="stair_width", subject="stair:C", status="conflict",
             why=f"GA and stair schedule say 1000 mm, the IFC says 950 mm (both would meet {need(80)} mm, but the sources disagree)."),
    ]
    for side, (n, cap) in D.LIFEBOATS.items():
        need_lb = D.SHIP["persons_on_board"][0] * 0.5
        E.append(dict(check="lifeboat_capacity", subject=f"lifeboats:{side}", status="pass",
                      why=f"{n * cap:,} persons against 50% of {D.SHIP['persons_on_board'][0]:,} = {need_lb:,.0f} each side (SOLAS III/21.1.1.1)."))
    E += [
        dict(check="liferaft_capacity", subject="liferafts", status="cant_tell", why="16 davit-launched liferafts, capacity not stated anywhere."),
        dict(check="evacuation_time", subject="evacuation", status="pass",
             why=f"{D.EVAC['total']} min against {D.EVAC_LIMIT_MIN:.0f} min: more than 3 main vertical zones (7)."),
        dict(check="evacuation_analysis_exists", subject="evacuation", status="pass", why="EA-101 is present and referenced by the spec."),
        dict(check="consistency", subject="ship.length_overall", status="conflict", files=[SPEC] + ALL_GA,
             why="spec.pdf says 299.80 m, the GA particulars box says 300.10 m."),
        dict(check="consistency", subject="stair:C", status="conflict", why="GA and stair schedule 1000 mm, IFC 950 mm."),
        dict(check="consistency", subject="door-number:5110", status="conflict", why="Schedule and GA 1000 mm, IFC 900 mm."),
        dict(check="consistency", subject="stair:B", status="conflict", scope="mixed set: ga-deck5-revB.pdf with stair-schedule.csv and model.ifc",
             why="Rev B GA says 1000 mm, the schedule and IFC still say 850 mm (not updated with rev B)."),
        dict(check="consistency", subject="stair:B", status="pass", scope="rev A set", why="850 mm in GA rev A, schedule and IFC."),
        dict(check="consistency", subject="stair:A", status="pass", why="1200 mm in GA, schedule and IFC."),
        dict(check="consistency", subject="ship.persons_on_board", status="pass", why="4,750 in spec.pdf and EA-101."),
        dict(check="consistency", subject="ship.main_vertical_zones", status="pass", why="7 in spec.pdf and EA-101."),
        dict(check="consistency", subject="ship.length_between_perpendiculars", status="pass", why="271.00 m in spec.pdf and the GA."),
        dict(check="consistency", subject="ship.beam", status="pass", why="37.00 m in spec.pdf and the GA (37000 mm dimension)."),
        dict(check="consistency", subject="ship.frame_spacing", status="pass", why="800 mm in spec.pdf and the GA."),
        dict(check="scale_check", subject=f"drawing:{D.GA['no']}", status="conflict", files=ALL_GA,
             why="drawn scale 1:200 differs from the 1:100 note (frame ruler: 4 mm per 800 mm frame)."),
    ]
    for d in D.DOORS:
        if d["no"] not in (5108, 5110):
            E.append(dict(check="consistency", subject=f"door-number:{d['no']}", status="pass",
                          why="Clear width equal in schedule, GA and IFC."))
    return E


def planted():
    ga_a = GA_REV_A
    return [
        dict(id="P-LOA", kind="conflict", check="consistency", subject="ship", property="length_overall",
             detail="Spec LOA 299.80 m, GA particulars box LOA 300.10 m.", files=[SPEC] + ALL_GA),
        dict(id="P-RAFT-CAP", kind="gap", check="liferaft_capacity", subject="liferafts", property="capacity_persons",
             detail="Spec lists 16 davit-launched liferafts with no capacity.", files=[SPEC]),
        dict(id="P-STAIR-B", kind="fail", check="stair_width", subject="stair:B", property="clear_width",
             detail="850 mm for 95 persons, FSS Code ch. 13 needs 950 mm. Rev B widens it to 1000 mm.",
             files=ga_a + [SCSV, IFC]),
        dict(id="P-STAIR-C", kind="conflict", check="consistency", subject="stair:C", property="clear_width",
             detail="GA and stair schedule 1000 mm, IFC 950 mm.", files=ALL_GA + [SCSV, IFC]),
        dict(id="P-DOOR-DEPTH", kind="fail", check="door_clear_width", subject="door-number:5104", property="clear_width",
             detail="900 mm clear with 700 mm opening depth: over 610 mm needs 915 mm.", files=[XLSX, DCSV, IFC, GA_A]),
        dict(id="P-DOOR-800", kind="fail", check="door_clear_width", subject="door-number:5107", property="clear_width",
             detail="800 mm clear on an accessible route, under 815 mm. IFC OverallWidth 900 would hide it.",
             files=[XLSX, DCSV, IFC, GA_A]),
        dict(id="P-DOOR-MISSING", kind="gap", check="door_clear_width", subject="door-number:5108", property="clear_width",
             detail="Clear width blank in the schedule, absent in the IFC, no width dimension on the GA.", files=[XLSX, DCSV, IFC, GA_A]),
        dict(id="P-DOOR-5110", kind="conflict", check="consistency", subject="door-number:5110", property="clear_width",
             detail="Schedule and GA 1000 mm, IFC ClearWidth 900 mm.", files=[XLSX, DCSV, IFC] + ALL_GA),
        dict(id="P-DOOR-DEPTH-UNKNOWN", kind="gap", check="door_clear_width", subject="door-number:5112", property="opening_depth",
             detail="880 mm clear is under 915 mm; opening depth blank in the schedule and absent in the IFC, so the limit is unknown.",
             files=[XLSX, DCSV, IFC]),
        dict(id="P-SCALE", kind="trap", check="scale_check", subject=f"drawing:{D.GA['no']}", property="scale",
             detail="Title block says SCALE 1:100, the sheet is drawn at 1:200 (frame ruler 4 mm per frame, stair 1200 mm = 6 mm).",
             files=ALL_GA),
        dict(id="P-IFC-OVERALL", kind="trap", check="door_clear_width", subject="door-number:*", property="clear_width",
             detail="IfcDoor.OverallWidth is clear + 100 mm (the frame opening). Reading it as the clear width passes door 5107 and 5104 wrongly.",
             files=[IFC]),
        dict(id="P-REVB-STALE", kind="conflict", check="consistency", subject="stair:B", property="clear_width",
             detail="Rev B GA shows 1000 mm but stair-schedule.csv and model.ifc still hold the rev A value 850 mm.",
             files=[GA_B, SCSV, IFC]),
    ]


def build(generated):
    f = Facts()
    spec_facts(f)
    for file, rev in GA_FILES:
        ga_facts(f, file, rev)
    schedule_facts(f, XLSX, HEAD_ROW + 1, True)
    schedule_facts(f, DCSV, 2, False)
    stair_csv_facts(f)
    ifc_facts(f)
    evac_facts(f)
    S = {k: dict(value=v, unit=u) for k, (v, u) in D.SHIP.items()}
    return dict(
        package=D.PACKAGE, seed=D.SEED, generated=generated, note=D.SYNTH,
        ship=dict(name=D.SHIP_NAME, hull=D.HULL, ga_length_overall=dict(value=D.GA_LOA, unit="m"), **S,
                  lifeboats={s: dict(count=n, persons_each=c, capacity_persons=n * c) for s, (n, c) in D.LIFEBOATS.items()},
                  liferafts=dict(count=D.LIFERAFTS, capacity_persons=None, note="not stated"),
                  evacuation=dict(rt_minutes=D.EVAC["rt"], el_minutes=D.EVAC["el"], time_minutes=D.EVAC["total"],
                                  governing_case=D.EVAC["case"], limit_minutes=D.EVAC_LIMIT_MIN)),
        assumed_rules=dict(door_min_clear_mm=815, door_deep_min_clear_mm=915, door_deep_threshold_mm=610,
                           stair_fss="900 mm up to 90 persons + 10 mm per extra person",
                           lifeboats="50% of persons on board on each side, SOLAS III/21.1.1.1",
                           evacuation_limit_min="80 when more than 3 main vertical zones, else 60"),
        drawing=dict(no=D.GA["no"], sheet="A3 landscape", scale_note=D.GA["scale_note"], scale_drawn=D.GA["scale_drawn"],
                     mm_per_frame=4.0, pt_per_frame=4.0 * 72 / 25.4),
        files=file_list(), facts=f.items, planted=planted(), expected=expected())
