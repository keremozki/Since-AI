"""The synthetic SYN-1 package must match its own truth.json: files, text layers, values and planted items."""
import csv
import json
import sys
from pathlib import Path

import ifcopenshell
import ifcopenshell.util.element as ue
import ifcopenshell.util.unit as uu
import openpyxl
import pymupdf
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "synthetic"))
import make_package  # noqa: E402

FILES = ["spec.pdf", "ga-deck5-revA.pdf", "ga-deck5-revB.pdf", "ga-deck5-revA-stroked.pdf", "ga-deck5-revA-scan.png",
         "ga-deck5-revA-scan.pdf", "door-schedule.xlsx", "door-schedule.csv", "stair-schedule.csv", "model.ifc",
         "evacuation-analysis-EA-101.pdf", "truth.json"]
SYNTH = "SYNTHETIC TEST DATA: not a real ship"
MM = 72 / 25.4


@pytest.fixture(scope="module")
def pkg(tmp_path_factory):
    out = tmp_path_factory.mktemp("synthetic_package")
    return out, make_package.generate(out)


def text(path):
    doc = pymupdf.open(path)
    return "\n".join(p.get_text() for p in doc)


def facts(truth, file, subject=None, prop=None):
    return [f for f in truth["facts"] if f["file"] == file and (subject is None or f["subject"] == subject)
            and (prop is None or f["property"] == prop)]


def fact(truth, file, subject, prop):
    found = facts(truth, file, subject, prop)
    assert len(found) == 1, (file, subject, prop, found)
    return found[0]


def flight_heights(path):
    """Heights in mm on paper of the stair flight rectangles (31 mm long), sorted."""
    page = pymupdf.open(path)[0]
    out = []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "re" and abs(it[1].width / MM - 31.0) < 0.2:
                out.append(round(it[1].height / MM, 2))
    return sorted(out)


def test_all_files_exist(pkg):
    out, _ = pkg
    for name in FILES:
        assert (out / name).stat().st_size > 0, name
    assert sum(p.stat().st_size for p in out.iterdir()) < 10_000_000


def test_spec_text_layer(pkg):
    out, _ = pkg
    doc = pymupdf.open(out / "spec.pdf")
    assert len(doc) == 2 and abs(doc[0].rect.width - 595.3) < 1 and abs(doc[0].rect.height - 841.9) < 1
    assert not any(p.get_images() for p in doc)
    t = text(out / "spec.pdf")
    for s in [SYNTH, "OUTLINE SPECIFICATION", "SYN-SPEC-001", "Principal particulars", "Length overall", "299.80 m",
              "271.00 m", "37.00 m", "37.40 m", "21.50 m", "8.40 m", "141,500", "800 mm", "Complement", "3,300",
              "1,450", "4,750", "Registry and dates", "Malta", "1 March 2025", "15 February 2027", "30 May 2029",
              "Main vertical zones: 7", "Life-saving appliances", "Evacuation analysis: see EA-101"]:
        assert s in t, s
    assert t.count("7 x 350 persons = 2,450 persons") == 2
    raft = [ln for ln in t.splitlines() if "davit-launched liferafts" in ln]
    assert raft == ["16 davit-launched liferafts"]  # no capacity stated: planted gap


def test_ga_rev_a_text_layer_and_scale(pkg):
    out, truth = pkg
    path = out / "ga-deck5-revA.pdf"
    doc = pymupdf.open(path)
    assert len(doc) == 1
    assert abs(doc[0].rect.width - 420 * MM) < 1 and abs(doc[0].rect.height - 297 * MM) < 1
    t = text(path)
    for s in [SYNTH, "SYN-GA-105", "GENERAL ARRANGEMENT DECK 5 (MVZ 3)", "SCALE 1:100", "SHEET SIZE A3", "FIRST ISSUE",
              "DIMENSIONS IN MM", "LOA 300.10 m", "2026-10-01", "STAIR A", "STAIR B", "STAIR C"]:
        assert s in t, s
    for n in range(5101, 5113):
        assert str(n) in t
    words = {w[4] for w in doc[0].get_text("words")}
    for f in facts(truth, "ga-deck5-revA.pdf"):
        if f["unit"] == "mm" and f["subject"].split(":")[0] in ("door-number", "stair"):
            assert str(f["value"]) in words, f
    # the frame ruler is drawn at 1:200: 60 frames of 800 mm = 240 mm on paper
    page = doc[0]
    x100 = max(page.search_for("FR 100"), key=lambda r: r.y0)
    x160 = max(page.search_for("FR 160"), key=lambda r: r.y0)
    per_frame = ((x160.x0 + x160.x1) / 2 - (x100.x0 + x100.x1) / 2) / 60 / MM
    assert abs(per_frame - 4.0) < 0.05
    assert abs(0.8 / (per_frame / 1000) - 200) < 3


def test_ga_rev_b_changes_only_stair_b(pkg):
    out, _ = pkg
    t = text(out / "ga-deck5-revB.pdf")
    assert "B 2026-11-01" in t.replace("\n", " ") or ("2026-11-01" in t and "STAIR B WIDENED TO 1000 MM CLEAR" in t)
    assert "FIRST ISSUE" in t and "SCALE 1:100" in t and "LOA 300.10 m" in t
    assert flight_heights(out / "ga-deck5-revA.pdf") == [4.25, 5.0, 6.0]  # B, C, A at 5 mm per metre
    assert flight_heights(out / "ga-deck5-revB.pdf") == [5.0, 5.0, 6.0]
    page = pymupdf.open(out / "ga-deck5-revB.pdf")[0]
    red = [d for d in page.get_drawings() if d.get("color") and d["color"][0] > 0.8 and d["color"][1] < 0.2]
    assert len(red) > 20  # revision cloud scallops and delta
    page_a = pymupdf.open(out / "ga-deck5-revA.pdf")[0]
    assert not [d for d in page_a.get_drawings() if d.get("color") and d["color"][0] > 0.8 and d["color"][1] < 0.2]


def test_stroked_and_scan_have_no_text(pkg):
    out, _ = pkg
    stroked = pymupdf.open(out / "ga-deck5-revA-stroked.pdf")
    assert stroked[0].get_text("words") == []
    assert len(stroked[0].get_drawings()) > len(pymupdf.open(out / "ga-deck5-revA.pdf")[0].get_drawings())
    assert flight_heights(out / "ga-deck5-revA-stroked.pdf") == [4.25, 5.0, 6.0]
    scan = pymupdf.open(out / "ga-deck5-revA-scan.pdf")
    assert len(scan) == 1 and scan[0].get_text("words") == [] and len(scan[0].get_images()) == 1
    assert not scan[0].get_drawings()
    img = Image.open(out / "ga-deck5-revA-scan.png")
    assert img.mode == "L" and abs(img.width - 420 / 25.4 * 150) < 2 and abs(img.height - 297 / 25.4 * 150) < 2


def test_xlsx_and_csv_match_truth(pkg):
    out, truth = pkg
    ws = openpyxl.load_workbook(out / "door-schedule.xlsx").active
    assert ws.title == "DOOR SCHEDULE DECK 5"
    assert [c.value for c in ws[3]] == ["DOOR NO.", "LOCATION", "TYPE", "CLEAR WIDTH (mm)", "OPENING DEPTH (mm)",
                                        "ACCESSIBLE ROUTE", "FIRE CLASS"]
    assert SYNTH in ws["A2"].value
    assert [ws.cell(r, 1).value for r in range(4, 16)] == list(range(5101, 5113))
    rows = list(csv.reader(open(out / "door-schedule.csv", encoding="utf-8")))
    assert rows[0] == [c.value for c in ws[3]] and len(rows) == 13
    for file, sheet in (("door-schedule.xlsx", ws), ("door-schedule.csv", rows)):
        got = facts(truth, file)
        assert len(got) == 36
        for f in got:
            col, row = ord(f["cell"][0]) - 65, int(f["cell"][1:])
            raw = sheet.cell(row, col + 1).value if file.endswith("xlsx") else rows[row - 1][col]
            want = f["value"]
            if f["property"] == "accessible_route":
                assert raw.lower() == want, f
            elif want is None:
                assert raw in (None, ""), f
            else:
                assert str(raw) == str(want), f
    srows = list(csv.reader(open(out / "stair-schedule.csv", encoding="utf-8")))
    assert srows[0] == ["STAIR", "DECK", "CLEAR WIDTH (mm)", "PERSONS SERVED", "MVZ"]
    assert srows[1:] == [["STAIR A", "5", "1200", "110", "3"], ["STAIR B", "5", "850", "95", "3"],
                         ["STAIR C", "5", "1000", "80", "3"]]


def test_ifc_model(pkg):
    out, truth = pkg
    m = ifcopenshell.open(str(out / "model.ifc"))
    assert abs(uu.calculate_unit_scale(m) - 0.001) < 1e-9  # millimetres
    assert [b.Name for b in m.by_type("IfcBuilding")] == ["SYN-1"]
    assert [s.Name for s in m.by_type("IfcBuildingStorey")] == ["DECK 5"]
    assert SYNTH in m.by_type("IfcProject")[0].Description
    doors = {d.Name: d for d in m.by_type("IfcDoor")}
    assert sorted(doors) == [str(n) for n in range(5101, 5113)]
    for f in facts(truth, "model.ifc"):
        kind, num = f["subject"].split(":")
        if kind != "door-number":
            continue
        d = doors[num]
        data = ue.get_psets(d)["SYN_DoorData"]
        key = {"clear_width": "ClearWidth", "opening_depth": "OpeningDepth", "accessible_route": "AccessibleRoute"}.get(f["property"])
        if key:
            if f["value"] is None:
                assert key not in data, f
            elif f["property"] == "accessible_route":
                assert data[key].lower() == f["value"]
            else:
                assert data[key] == f["value"]
        elif f["property"] == "ifc_overall_width":
            assert d.OverallWidth == f["value"] == data["ClearWidth"] + 100
        assert d.OverallHeight == 2000
    assert ue.get_psets(doors["5110"])["SYN_DoorData"]["ClearWidth"] == 900
    assert "ClearWidth" not in ue.get_psets(doors["5108"])["SYN_DoorData"] and doors["5108"].OverallWidth is None
    assert "OpeningDepth" not in ue.get_psets(doors["5112"])["SYN_DoorData"]
    flights = {s.Name: ue.get_psets(s)["SYN_EscapeData"] for s in m.by_type("IfcStairFlight")}
    assert {k: (v["ClearWidth"], v["PersonsServed"]) for k, v in flights.items()} == {
        "STAIR A": (1200, 110), "STAIR B": (850, 95), "STAIR C": (950, 80)}
    assert len(m.by_type("IfcDoor")) == 12


def test_evacuation_report(pkg):
    out, _ = pkg
    t = text(out / "evacuation-analysis-EA-101.pdf")
    for s in ["EA-101 Evacuation analysis (simplified method, MSC.1/Circ.1533)", SYNTH, "38.0", "30.0", "67.5",
              "Case 1 (night)", "1.25 (R+T) + 2/3 (E+L)", "4,750"]:
        assert s in t, s
    assert 1.25 * 38.0 + 2 / 3 * 30.0 == pytest.approx(67.5)


# ---------------------------------------------------------------- truth.json
def door_rule(clear, depth, accessible, ifc_clear):
    """Independent restatement of the door rules (815 mm; 915 mm if the opening is deeper than 610 mm)."""
    if not accessible:
        return "not_applicable"
    if clear is not None and ifc_clear != clear:
        return "conflict"
    if clear is None:
        return "cant_tell"
    if depth is None:
        return "pass" if clear >= 915 else "fail" if clear < 815 else "cant_tell"
    return "pass" if clear >= (915 if depth > 610 else 815) else "fail"


def test_truth_is_internally_consistent(pkg):
    out, truth = pkg
    assert json.loads((out / "truth.json").read_text(encoding="utf-8")) == truth
    ship = truth["ship"]
    assert ship["passengers"]["value"] + ship["crew_complement"]["value"] == ship["persons_on_board"]["value"] == 4750
    assert ship["length_overall"]["value"] == 299.80 and ship["ga_length_overall"]["value"] == 300.10
    assert truth["package"] == "meyer-style-v1" and isinstance(truth["seed"], int)
    names = {f["file"] for f in truth["files"]}
    assert names == set(FILES) - {"truth.json"}
    for f in truth["files"]:
        assert isinstance(f["text_layer"], bool) or f["text_layer"] is None
    assert {f["file"]: f["text_layer"] for f in truth["files"] if f["file"].endswith((".pdf", ".png"))} == {
        "spec.pdf": True, "ga-deck5-revA.pdf": True, "ga-deck5-revB.pdf": True, "ga-deck5-revA-stroked.pdf": False,
        "ga-deck5-revA-scan.pdf": False, "ga-deck5-revA-scan.png": False, "evacuation-analysis-EA-101.pdf": True}
    # every fact points at a listed file and carries the required keys
    for f in truth["facts"]:
        assert f["file"] in names and {"subject", "property", "value", "unit", "file", "page", "sheet", "cell", "note"} <= set(f)
    spec_props = {f["property"] for f in facts(truth, "spec.pdf", "ship")}
    assert spec_props >= {"length_overall", "length_between_perpendiculars", "beam", "breadth_greatest", "depth",
                          "design_draft", "gross_tonnage", "frame_spacing", "passengers", "crew_complement",
                          "persons_on_board", "flag", "ship_type", "contract_date", "keel_date", "delivery_date",
                          "main_vertical_zones"}
    assert fact(truth, "spec.pdf", "ship", "length_overall")["value"] == 299.80
    assert fact(truth, "ga-deck5-revA.pdf", "ship", "length_overall")["value"] == 300.10
    assert fact(truth, "evacuation-analysis-EA-101.pdf", "evacuation", "time_minutes")["value"] == 67.5
    assert fact(truth, "spec.pdf", "lifeboats:port", "capacity_persons")["value"] == 2450
    assert fact(truth, "spec.pdf", "lifeboats:starboard", "capacity_persons")["value"] == 2450
    assert not facts(truth, "spec.pdf", "liferafts", "capacity_persons")
    # planted items
    assert {p["id"] for p in truth["planted"]} >= {"P-LOA", "P-RAFT-CAP", "P-STAIR-B", "P-STAIR-C", "P-DOOR-DEPTH", "P-DOOR-800",
                                                   "P-DOOR-MISSING", "P-DOOR-5110", "P-DOOR-DEPTH-UNKNOWN", "P-SCALE"}
    for p in truth["planted"]:
        assert p["kind"] in {"fail", "conflict", "gap", "trap"} and set(p["files"]) <= names
        assert {"id", "kind", "check", "subject", "property", "detail", "files"} <= set(p)


def test_expected_statuses_follow_the_rules(pkg):
    _, truth = pkg
    exp = truth["expected"]
    checks = {"door_clear_width", "stair_width", "lifeboat_capacity", "liferaft_capacity", "evacuation_time",
              "evacuation_analysis_exists", "consistency", "scale_check"}
    statuses = {"pass", "fail", "conflict", "cant_tell", "not_applicable"}
    assert all(e["check"] in checks and e["status"] in statuses and e["why"] for e in exp)
    sched = {int(f["subject"].split(":")[1]): {} for f in facts(truth, "door-schedule.xlsx")}
    for f in facts(truth, "door-schedule.xlsx"):
        sched[int(f["subject"].split(":")[1])][f["property"]] = f["value"]
    ifc = {}
    for f in facts(truth, "model.ifc", prop="clear_width"):
        if f["subject"].startswith("door-number:"):
            ifc[int(f["subject"].split(":")[1])] = f["value"]
    got = {e["subject"]: e["status"] for e in exp if e["check"] == "door_clear_width"}
    assert len(got) == 12
    for no, s in sched.items():
        want = door_rule(s["clear_width"], s["opening_depth"], s["accessible_route"] == "yes", ifc[no])
        assert got[f"door-number:{no}"] == want, no
    assert got["door-number:5103"] == got["door-number:5105"] == "pass"
    assert got["door-number:5106"] == "not_applicable" and got["door-number:5110"] == "conflict"
    assert got["door-number:5104"] == got["door-number:5107"] == "fail"
    assert got["door-number:5108"] == got["door-number:5112"] == "cant_tell"
    # stairs: FSS ch. 13, 900 mm + 10 mm per person above 90
    req = lambda n: 900 + 10 * max(0, n - 90)
    stair = [e for e in exp if e["check"] == "stair_width"]
    assert {(e["subject"], e["status"]) for e in stair} == {("stair:A", "pass"), ("stair:B", "fail"), ("stair:B", "pass"), ("stair:C", "conflict")}
    assert req(110) <= 1200 and req(95) == 950 > 850 and req(95) <= 1000 and req(80) <= 950
    ga_b = fact(truth, "ga-deck5-revB.pdf", "stair:B", "clear_width")["value"]
    assert ga_b == 1000 and fact(truth, "ga-deck5-revA.pdf", "stair:B", "clear_width")["value"] == 850
    assert fact(truth, "model.ifc", "stair:C", "clear_width")["value"] == 950
    assert fact(truth, "stair-schedule.csv", "stair:C", "clear_width")["value"] == 1000
    # life-saving and evacuation
    pob = truth["ship"]["persons_on_board"]["value"]
    for side in ("port", "starboard"):
        cap = fact(truth, "spec.pdf", f"lifeboats:{side}", "capacity_persons")["value"]
        assert cap >= 0.5 * pob == 2375
        assert [e["status"] for e in exp if e["subject"] == f"lifeboats:{side}"] == ["pass"]
    assert [e["status"] for e in exp if e["check"] == "liferaft_capacity"] == ["cant_tell"]
    zones = truth["ship"]["main_vertical_zones"]["value"]
    limit = 80 if zones > 3 else 60
    total = fact(truth, "evacuation-analysis-EA-101.pdf", "evacuation", "time_minutes")["value"]
    assert total <= limit and [e["status"] for e in exp if e["check"] == "evacuation_time"] == ["pass"]
    assert [e["status"] for e in exp if e["check"] == "evacuation_analysis_exists"] == ["pass"]
    cons = [e for e in exp if e["check"] == "consistency" and e["status"] == "conflict"]
    assert "ship.length_overall" in {e["subject"] for e in cons}
    assert [e["status"] for e in exp if e["check"] == "scale_check"] == ["conflict"]
    assert "1:200" in [e["why"] for e in exp if e["check"] == "scale_check"][0]


def test_generation_is_reproducible(pkg, tmp_path):
    out, _ = pkg
    make_package.generate(tmp_path)
    for name in FILES:
        assert (tmp_path / name).read_bytes() == (out / name).read_bytes(), name
