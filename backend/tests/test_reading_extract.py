"""The extraction half of the reading pipeline: labeled values, AI pointers, second readings, file readers, tiers.

Document maps are built by hand, and the AI is a fake, so nothing here touches the network.
"""
import csv

import ifcopenshell
import ifcopenshell.api
import openpyxl
import pymupdf
import pytest

from app import dictionary
from app.ai_gateway import AIResponsePending, OfflineAI, save_answer, validate
from app.models import Box, SourceKind, Tier
from app.reading import second_reading
from app.reading.labeled import extract_labeled, parse_value, scan_labeled, stated_unit
from app.reading.model import DocumentMap, FactCandidate, Line, PageInfo
from app.reading.pointing import SYSTEM, build_pointing_request, point_facts, verify_pointer
from app.reading.readers import read_ifc, read_table_file
from app.reading.second_reading import (add_second_readings, attach_reading, ocr_box, readings_agree,
                                        transcription_request)
from app.reading.to_facts import candidate_to_fact, facts_from_candidates, tier_for


def line(n, text, x0, y0, x1, y1, source="ocr", conf=0.97, page=1):
    return Line(id=f"p{page}-l{n}", page=page, text=text, box=Box(page=page, x0=x0, y0=y0, x1=x1, y1=y1),
                source=source, confidence=None if source == "text_layer" else conf)


def doc(lines, width=1224.0, height=792.0, pages=1):
    infos = [PageInfo(page=p, width_pt=width, height_pt=height, kind="vector_strokes") for p in range(1, pages + 1)]
    return DocumentMap(file="test.pdf", sha256="0", pages=infos, lines=lines)


def by_fact(candidates, fact_id):
    return [c for c in candidates if c.fact_id == fact_id]


def only(candidates, fact_id):
    found = by_fact(candidates, fact_id)
    assert len(found) == 1, f"{fact_id}: {[(c.value, c.unit, c.line_ids) for c in found]}"
    return found[0]


@pytest.fixture
def particulars():
    """The RCRV particulars as OCR gave them: the inch mark lost on LOA, BEAM's value far right on its row."""
    return doc([
        line(1, "GENERAL PARTICULARS", 100, 60, 260, 74),
        line(2, "LOA 199'-6", 100, 100, 180, 112),
        line(3, "BEAM", 100, 120, 140, 132),
        line(4, "41'-0\"", 460, 120, 500, 132),
        line(5, "DESIGN DRAFT 12'-6\"", 100, 140, 230, 152),
        line(6, "SIDE DECK LENGTH 79'-0\"", 100, 160, 270, 172),
        line(7, "LWL 184'-0\"", 100, 180, 180, 192),
    ])


@pytest.fixture
def spec_table():
    """A specification table from a text layer: some rows are one line, some are a label cell and a value cell."""
    return doc([
        line(1, "Length overall 299.80 m", 72, 200, 250, 212, "text_layer"),
        line(2, "Breadth, moulded", 72, 220, 170, 232, "text_layer"),
        line(3, "37.00 m", 300, 220, 350, 232, "text_layer"),
        line(4, "Gross tonnage", 72, 240, 150, 252, "text_layer"),
        line(5, "141,500", 300, 240, 350, 252, "text_layer"),
        line(6, "Persons on board (certified)", 72, 260, 230, 272, "text_layer"),
        line(7, "4,750", 300, 260, 340, 272, "text_layer"),
    ], width=612, height=792)


# -- labeled path ----------------------------------------------------------------------------------------------

def test_rcrv_particulars_values_and_units(particulars):
    found = extract_labeled(particulars)
    loa = only(found, "ship.length_overall")
    assert (loa.value, loa.unit, loa.subject, loa.property) == (2394.0, "in", "ship", "length_overall")
    assert loa.method == "labeled_rule" and loa.line_ids == ["p1-l2"] and loa.label_text == "LOA"
    assert loa.quote == "LOA 199'-6"
    assert loa.readings == [{"method": "ocr", "text": "199'-6", "value": 2394.0, "unit": "in", "confidence": 0.97}]
    assert "label 'LOA' is a listed label for ship.length_overall" in loa.checks
    assert "value parsed by code: 199'-6 = 2394 in" in loa.checks
    assert "in range 5-500 m" in loa.checks and loa.problems == []

    beam = only(found, "ship.beam")
    assert (beam.value, beam.unit) == (492.0, "in")
    assert beam.line_ids == ["p1-l3", "p1-l4"] and beam.quote == 'BEAM 41\'-0"'
    assert beam.box == Box(page=1, x0=100, y0=120, x1=500, y1=132)  # the union of the two line boxes
    assert "the value is on the same row as the label, to its right" in beam.checks

    draft = only(found, "ship.design_draft")
    assert (draft.value, draft.unit) == (150.0, "in")
    lwl = only(found, "ship.length_waterline")
    assert (lwl.value, lwl.unit, lwl.line_ids) == (2208.0, "in", ["p1-l7"])


def test_side_deck_length_is_never_length_overall(particulars):
    found, refused = scan_labeled(particulars)
    loa = by_fact(found, "ship.length_overall")
    assert [c.line_ids for c in loa] == [["p1-l2"]]
    assert not any(c.value == 79 * 12 for c in found)  # the side deck length 79'-0" was not read as anything
    assert not [r for r in refused if "p1-l6" in r["line_ids"] and r["fact_id"] == "ship.length_overall"]


def test_waterline_goes_to_waterline_not_loa():
    dm = doc([line(1, "LWL 184'-0\"", 100, 100, 180, 112), line(2, "LENGTH WATERLINE 56.10 m", 100, 120, 300, 132)])
    found = extract_labeled(dm)
    assert not by_fact(found, "ship.length_overall")
    assert [c.line_ids for c in by_fact(found, "ship.length_waterline")] == [["p1-l1"], ["p1-l2"]]


def test_spec_table_text_layer(spec_table):
    found = extract_labeled(spec_table)
    loa = only(found, "ship.length_overall")
    assert (loa.value, loa.unit, loa.quote) == (299.8, "m", "Length overall 299.80 m")
    assert loa.readings[0]["method"] == "text_layer" and loa.readings[0]["confidence"] is None
    beam = only(found, "ship.beam")
    assert (beam.value, beam.unit, beam.label_text) == (37.0, "m", "BREADTH MOULDED")
    assert beam.line_ids == ["p1-l2", "p1-l3"]
    assert only(found, "ship.gross_tonnage").value == 141500.0
    pob = only(found, "ship.persons_on_board")
    assert (pob.value, pob.unit) == (4750.0, "")
    assert "in range 1-12000" in pob.checks


def test_double_s_r_berths_are_not_persons_on_board():
    stacked = doc([line(1, "PERSONS ON BOARD", 72, 300, 200, 312), line(2, "7 DOUBLE S/R", 72, 314, 160, 326)])
    found, refused = scan_labeled(stacked)
    assert not by_fact(found, "ship.persons_on_board")
    assert "S/R" in refused[0]["reasons"][0]
    same_row = doc([line(1, "PERSONS ON BOARD", 72, 300, 200, 312), line(2, "7 DOUBLE S/R", 300, 300, 400, 312)])
    assert not extract_labeled(same_row)
    crew = doc([line(1, "CREW BERTHS 24", 72, 300, 200, 312)])
    assert not extract_labeled(crew)  # a berth count is a lookalike for crew complement too


def test_stacked_label_and_value_below():
    dm = doc([line(1, "GROSS TONNAGE", 100, 100, 200, 112), line(2, "141,500", 120, 114, 180, 126)])
    gt = only(extract_labeled(dm), "ship.gross_tonnage")
    assert gt.value == 141500.0 and "the value is directly below the label" in gt.checks
    far = doc([line(1, "GROSS TONNAGE", 100, 100, 200, 112), line(2, "141,500", 120, 160, 180, 172)])
    assert not extract_labeled(far)


def test_value_must_be_the_nearest_cell_on_the_row():
    dm = doc([line(1, "BEAM", 100, 100, 140, 112), line(2, "SEE NOTE", 200, 100, 260, 112),
              line(3, "41'-0\"", 300, 100, 340, 112)])
    assert not extract_labeled(dm)  # a cell that isn't the value blocks the row; the value beyond it isn't taken


def test_label_must_start_the_line_and_one_letter_labels_need_the_value_on_the_line():
    assert not extract_labeled(doc([line(1, "THE BEAM OF THE DAVIT IS 3.5 m", 100, 100, 400, 112)]))
    assert not extract_labeled(doc([line(1, "DECK B 12.5 m", 100, 100, 200, 112)]))
    assert not extract_labeled(doc([line(1, "B", 100, 100, 110, 112), line(2, "12.5 m", 150, 100, 200, 112)]))
    assert only(extract_labeled(doc([line(1, "B 12.5 m", 100, 100, 200, 112)])), "ship.beam").value == 12.5


def test_second_number_or_extra_words_give_no_value():
    for text in ('Length overall 299.80 m (983\'-6")', "Persons on board 4,750 / 5,000", "Length overall approx 299.80 m",
                 "Length overall 299.80 m between perpendiculars", "Persons on board 4,750 and 7 crew"):
        assert not extract_labeled(doc([line(1, text, 72, 100, 400, 112, "text_layer")])), text
    assert only(extract_labeled(doc([line(1, "Length overall 299.80 m (extreme)", 72, 100, 400, 112)])),
                "ship.length_overall").value == 299.8


def test_range_check_in_si_and_unit_hint():
    too_long = doc([line(1, "LOA 5000 m", 100, 100, 200, 112)])
    found, refused = scan_labeled(too_long)
    assert not found and "outside the plausible range 5-500 m" in refused[0]["reasons"][0]
    assert not extract_labeled(doc([line(1, "FRAME SPACING 600", 100, 100, 220, 112)]))  # no unit stated: no value
    stated = doc([line(1, "ALL DIMENSIONS IN MM", 100, 50, 300, 62), line(2, "FRAME SPACING 600", 100, 100, 220, 112)])
    spacing = only(extract_labeled(stated), "ship.frame_spacing")
    assert (spacing.value, spacing.unit) == (600.0, "mm")
    assert any(c.startswith("unit mm stated in") for c in spacing.checks)
    in_label = doc([line(1, "FRAME SPACING (mm)", 100, 100, 220, 112), line(2, "600", 300, 100, 330, 112)])
    assert only(extract_labeled(in_label), "ship.frame_spacing").unit == "mm"


def test_placeholder_imo_is_rejected_and_a_real_one_read():
    found, refused = scan_labeled(doc([line(1, "IMO 1234567", 100, 100, 200, 112, "text_layer")]))
    assert not found and "placeholder" in refused[0]["reasons"][0]
    real = only(extract_labeled(doc([line(1, "IMO NO. 9241061", 100, 100, 250, 112, "text_layer")])), "ship.imo_number")
    assert real.value == "9241061"
    assert not extract_labeled(doc([line(1, "IMO 9241062", 100, 100, 200, 112)]))  # fails its check digit


def test_dates_and_text_facts():
    dm = doc([line(1, "KEEL LAID 15 Feb 2027", 100, 100, 300, 112), line(2, "CONTRACT DATE 02/03/2027", 100, 120, 300, 132),
              line(3, "FLAG: Bahamas", 100, 140, 300, 152)])
    found = extract_labeled(dm)
    assert only(found, "ship.keel_date").value == "2027-02-15"
    assert not by_fact(found, "ship.contract_date")  # a slash date is ambiguous
    assert only(found, "ship.flag").value == "Bahamas"


def test_low_ocr_confidence_is_a_problem_and_pages_filter():
    dm = doc([line(1, "LOA 199'-6", 100, 100, 180, 112, conf=0.31), line(2, "LOA 60.0 m", 100, 100, 180, 112, page=2)],
             pages=2)
    both = extract_labeled(dm)
    assert only([c for c in both if c.page == 1], "ship.length_overall").problems
    assert [c.page for c in extract_labeled(dm, pages=[2])] == [2]


def test_parse_value_start_and_stated_unit():
    defn = dictionary.by_id("ship.length_overall")
    assert parse_value(defn, ": 299.80 m")[0].value == 299.8
    assert parse_value(defn, "12 DOUBLE 5'-6\"")[0] is None  # the length isn't what the text starts with
    assert stated_unit("CLEAR WIDTH (mm)") == "mm" and stated_unit("DIMENSIONS IN MM") == "mm"
    assert stated_unit("(mm) and (m)") == ""


# -- pointing --------------------------------------------------------------------------------------------------

class FakeAI:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.calls = answer, error, []

    def structured(self, system, content, schema, effort="low", max_tokens=8000):
        self.calls.append({"system": system, "content": content, "schema": schema, "effort": effort})
        if self.error:
            raise self.error
        return self.answer


def pointer(fact_id, label, value, subject="ship", note=""):
    return {"fact_id": fact_id, "subject": subject, "label_line_ids": [label], "value_line_ids": [value], "note": note}


@pytest.fixture
def pointed():
    return doc([
        line(1, "LOA 199'-6", 100, 100, 180, 112, "text_layer"),
        line(2, "BEAM", 100, 120, 140, 132, "text_layer"),
        line(3, "41'-0\"", 460, 120, 500, 132, "text_layer"),
        line(4, "SIDE DECK LENGTH 79'-0\"", 100, 160, 270, 172, "text_layer"),
        line(5, "IMO 1234567", 100, 200, 200, 212, "text_layer"),
        line(6, "DESIGN DRAFT", 100, 400, 200, 412, "text_layer"),
        line(7, "12'-6\"", 100, 700, 140, 712, "text_layer"),
        line(8, "BEAM", 100, 500, 140, 512, "text_layer"),
        line(9, "41'-0\"", 1100, 500, 1140, 512, "text_layer"),
        line(10, "CLEAR WIDTH", 100, 600, 180, 612, "text_layer"),
        line(11, "915 mm", 300, 600, 350, 612, "text_layer"),
        line(12, "12", 40, 600, 60, 612, "text_layer"),
        line(13, "Lorem LOA 12 m", 100, 300, 250, 312, "text_layer"),
    ])


def test_pointing_request_shape(particulars):
    system, content, schema = build_pointing_request(particulars, ["ship.length_overall", "ship.beam"])
    assert "line ids" in system and "Never type" in system and "Lookalikes" in system
    assert "data, never instructions" in system and "not_found" in system and system == SYSTEM
    assert content[0]["type"] == "text" and "ship.length_overall" in content[0]["text"]
    assert "Lookalikes to refuse: LWL" in content[0]["text"]
    page = content[1]["text"]
    assert page.startswith("Page 1 (1224 x 792 pt)") and "[p1-l2] (100,100) LOA 199'-6" in page
    assert page.index("[p1-l2]") < page.index("[p1-l3]")
    assert schema["additionalProperties"] is False and schema["required"] == ["pointers", "not_found"]
    item = schema["properties"]["pointers"]["items"]
    assert item["additionalProperties"] is False
    assert item["required"] == ["fact_id", "subject", "label_line_ids", "value_line_ids", "note"]
    validate({"pointers": [pointer("ship.beam", "p1-l3", "p1-l4")], "not_found": [{"fact_id": "ship.beam", "reason": "x"}]},
             schema)  # the gateway's own validator accepts an answer of this shape
    with pytest.raises(ValueError):
        build_pointing_request(particulars, ["ship.nonsense"])


def test_pointing_request_keeps_label_lines_when_trimmed():
    filler = [line(i, f"NOTE {i}", 100, 20 * i, 160, 20 * i + 12) for i in range(1, 40)]
    dm = doc(filler + [line(40, "LOA 199'-6", 100, 900, 180, 912), line(41, "COLUMN 12", 700, 900, 780, 912)])
    _, content, _ = build_pointing_request(dm, ["ship.length_overall"], max_lines=5)
    text = content[1]["text"]
    assert "[p1-l40]" in text and text.count("[p1-l") == 5 and "lines of this page are not listed" in text


def test_good_pointers_become_verified_candidates(pointed):
    answer = {"pointers": [pointer("ship.length_overall", "p1-l1", "p1-l1", note="particulars"),
                           pointer("ship.beam", "p1-l2", "p1-l3")], "not_found": []}
    ai = FakeAI(answer)
    found, rejected = point_facts(ai, pointed, ["ship.length_overall", "ship.beam"])
    assert rejected == [] and ai.calls[0]["effort"] == "medium"
    loa, beam = found
    assert (loa.value, loa.unit, loa.method, loa.line_ids) == (2394.0, "in", "ai_pointer", ["p1-l1"])
    assert (beam.value, beam.unit, beam.line_ids) == (492.0, "in", ["p1-l2", "p1-l3"])
    assert loa.readings[0]["method"] == "text_layer"
    assert "pointed at by the AI; code re-read the value from the cited text" in loa.checks
    assert not any("particulars" in c for c in loa.checks + loa.problems)  # the AI's note is not evidence


def test_bad_pointers_are_rejected_with_reasons(pointed):
    answer = {"pointers": [
        pointer("ship.length_overall", "p1-l4", "p1-l4"),  # a lookalike label
        pointer("ship.design_draft", "p1-l6", "p1-l7"),  # the value is far below the label
        pointer("ship.beam", "p1-l8", "p1-l9"),  # same row, but wider than half the page
        pointer("ship.imo_number", "p1-l5", "p1-l5"),  # a placeholder
        pointer("ship.beam", "p1-l2", "p1-l3", subject="vessel"),  # a subject this fact can't have
        pointer("ship.beam", "p1-l2", "p1-l99"),  # a line that doesn't exist
        pointer("ship.length_overall", "p1-l13", "p1-l13"),  # the label is in the middle of a sentence
        pointer("ship.depth", "p1-l2", "p1-l3"),  # a line with no label for that fact
        pointer("ship.gross_tonnage", "p1-l1", "p1-l1"),  # not asked for
    ], "not_found": []}
    ids = ["ship.length_overall", "ship.design_draft", "ship.beam", "ship.imo_number", "ship.depth"]
    found, rejected = point_facts(FakeAI(answer), pointed, ids)
    assert found == [] and len(rejected) == 9
    reasons = [" ".join(r["reasons"]) for r in rejected]
    assert "lookalike 'SIDE DECK LENGTH'" in reasons[0]
    assert "not on the label's row" in reasons[1]
    assert "not on the label's row" in reasons[2]
    assert "placeholder" in reasons[3]
    assert "subject 'vessel' is not valid" in reasons[4]
    assert "does not exist" in reasons[5]
    assert "not at the start of its line" in reasons[6]
    assert "no listed label for ship.depth" in reasons[7]
    assert "was not asked for" in reasons[8]
    assert all(r["pointer"] for r in rejected)


def test_pointer_across_pages_and_label_between_are_rejected():
    dm = doc([line(1, "LOA", 100, 100, 130, 112), line(2, "BEAM", 300, 100, 340, 112),
              line(3, "41'-0\"", 400, 100, 440, 112), line(4, "199'-6\"", 100, 100, 160, 112, page=2)], pages=2)
    _, reasons = verify_pointer(dm, pointer("ship.length_overall", "p1-l1", "p2-l4"))
    assert "page 1" in reasons[0] and "page 2" in reasons[0]
    _, reasons = verify_pointer(dm, pointer("ship.length_overall", "p1-l1", "p1-l3"))
    assert any("another label" in r for r in reasons)
    assert verify_pointer(dm, {"fact_id": "ship.beam", "subject": "ship", "label_line_ids": [], "value_line_ids": [],
                               "note": ""})[0] is None


def test_pointer_subject_id_must_be_on_the_row(pointed):
    good = verify_pointer(pointed, pointer("door.clear_width", "p1-l10", "p1-l11", subject="door-number:12"))[0]
    assert good.value == 915.0 and good.unit == "mm" and good.problems == []
    assert "subject id '12' is written on the label's row" in good.checks
    guessed = verify_pointer(pointed, pointer("door.clear_width", "p1-l10", "p1-l11", subject="door-number:99"))[0]
    assert guessed is not None and "subject id '99' is not written" in guessed.problems[0]
    assert tier_for(guessed) == Tier.D


def test_offline_ai_pending_propagates(particulars, tmp_path):
    with pytest.raises(AIResponsePending):
        point_facts(FakeAI(error=AIResponsePending("abc", tmp_path)), particulars, ["ship.beam"])
    assert point_facts(FakeAI(error=AIResponsePending("abc", tmp_path)), doc([]), ["ship.beam"]) == ([], [])  # nothing to ask


def test_pointing_through_the_offline_gateway(particulars, tmp_path):
    ai = OfflineAI(tmp_path / "ai")
    with pytest.raises(AIResponsePending) as pending:
        point_facts(ai, particulars, ["ship.length_overall"])
    answer = {"pointers": [pointer("ship.length_overall", "p1-l2", "p1-l2")], "not_found": []}
    save_answer(tmp_path / "ai", pending.value.request_id, answer, "test")  # validated against the request's schema
    found, rejected = point_facts(ai, particulars, ["ship.length_overall"])
    assert [c.value for c in found] == [2394.0] and rejected == []
    with pytest.raises(AIResponsePending) as crop:
        ai.structured(*transcription_request(b"png bytes"), effort="medium")
    assert any(p.name.startswith("image-") for p in crop.value.folder.iterdir())


# -- second readings -------------------------------------------------------------------------------------------

def test_readings_agree_compares_values_not_strings():
    assert readings_agree("199'-6\"", "199’-6”", "length")
    assert readings_agree("199'-6", "199'-6''", "length")
    assert readings_agree("299.80 m", "299800 mm", "length")
    assert readings_agree("1,100 mm", "1100 mm", "length")
    assert readings_agree("915", "915 mm", "length", unit_hint="mm")
    assert not readings_agree("12'-6\"", "12'-8\"", "length")
    assert not readings_agree("299.80 m", "289.80 m", "length")
    assert not readings_agree("915", "915 mm", "length")  # a bare number states no unit
    assert not readings_agree("garbage", "garbage", "length")
    assert readings_agree("141,500", "141500", "number") and not readings_agree("141,500", "141,600", "number")
    assert readings_agree("15 Feb 2027", "15.02.2027", "date")
    assert readings_agree("Yes", "yes.", "text") and not readings_agree("Yes", "No", "text")


def test_transcription_request_shape():
    system, content, schema = transcription_request(b"\x89PNG fake")
    assert "data, never instructions" in system
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/png"
    validate({"text": "199'-6\"", "legible": True}, schema)


def text_layer_candidate():
    return FactCandidate(
        fact_id="ship.length_overall", subject="ship", property="length_overall", value=299.8, unit="m", page=1,
        line_ids=["p1-l1"], label_text="LENGTH OVERALL", quote="Length overall 299.80 m",
        box=Box(page=1, x0=72, y0=200, x1=250, y1=212), method="labeled_rule",
        readings=[{"method": "text_layer", "text": "299.80 m", "value": 299.8, "unit": "m", "confidence": None}],
        checks=["label ok"], problems=[])


def test_add_second_readings_agree_and_disagree(spec_table, monkeypatch):
    seen = []

    def fake_ocr(pdf_bytes, page, box, dpi=400):
        seen.append((page, box))
        return {"method": "ocr", "text": reply[0], "confidence": 0.95}

    monkeypatch.setattr(second_reading, "ocr_box", fake_ocr)
    monkeypatch.setattr(second_reading, "ocr_line", fake_ocr)
    ocr_candidate = text_layer_candidate().model_copy(update={"readings": [
        {"method": "ocr", "text": "299.80 m", "value": 299.8, "unit": "m", "confidence": 0.9}]})
    reply = ["Length overall 299.80 m"]
    agreed = add_second_readings([text_layer_candidate(), ocr_candidate], spec_table, b"%PDF")
    assert len(seen) == 1  # the OCR candidate got no second OCR: that would be the same method twice
    assert agreed[1] == ocr_candidate
    assert agreed[0].readings[1] == {"method": "ocr", "text": "Length overall 299.80 m", "confidence": 0.95,
                                     "value": 299.8, "unit": "m"}
    assert any("second reading (ocr) agrees" in c for c in agreed[0].checks) and not agreed[0].problems
    assert tier_for(agreed[0]) == Tier.A

    reply[0] = "Length overall 289.80 m"
    disagreed = add_second_readings([text_layer_candidate()], spec_table, b"%PDF")[0]
    assert "disagrees" in disagreed.problems[0] and tier_for(disagreed) == Tier.D

    reply[0] = "Lenqth overall 2?9.80 m"  # unreadable: kept as evidence, but it confirms nothing
    unsure = add_second_readings([text_layer_candidate()], spec_table, b"%PDF")[0]
    assert unsure.readings[1]["value"] is None and not unsure.problems and tier_for(unsure) == Tier.C


def test_value_line_is_cropped_alone_when_label_is_a_separate_line(spec_table, monkeypatch):
    boxes = []
    monkeypatch.setattr(second_reading, "ocr_line", lambda pdf, page, box, dpi=400: boxes.append(box) or
                        {"method": "ocr", "text": "37.00 m", "confidence": 0.9})
    beam = only(extract_labeled(spec_table), "ship.beam")
    result = add_second_readings([beam], spec_table, b"%PDF")[0]
    assert boxes == [spec_table.line("p1-l3").box] and tier_for(result) == Tier.A


def test_a_quick_reading_that_doesnt_confirm_gets_the_full_reading_before_it_counts(spec_table, monkeypatch):
    calls = []
    monkeypatch.setattr(second_reading, "ocr_line", lambda pdf, page, box, dpi=400: calls.append("quick") or
                        {"method": "ocr", "text": "87.00 m", "confidence": 0.9})
    monkeypatch.setattr(second_reading, "ocr_box", lambda pdf, page, box, dpi=400: calls.append("full") or
                        {"method": "ocr", "text": "37.00 m", "confidence": 0.9})
    beam = only(extract_labeled(spec_table), "ship.beam")
    result = add_second_readings([beam], spec_table, b"%PDF")[0]
    assert calls == ["quick", "full"] and tier_for(result) == Tier.A and not result.problems


def test_ai_transcription_gives_the_second_reading_of_an_ocr_value(particulars):
    loa = only(extract_labeled(particulars), "ship.length_overall")
    assert tier_for(loa) == Tier.C
    confirmed = attach_reading(loa, {"method": "ai_transcription", "text": "199'-6\"", "confidence": None})
    assert tier_for(confirmed) == Tier.B and any("agrees" in c for c in confirmed.checks)
    wrong = attach_reading(loa, {"method": "ai_transcription", "text": "199'-8\"", "confidence": None})
    assert tier_for(wrong) == Tier.D
    assert loa.readings == [loa.readings[0]]  # the original candidate is untouched


def test_ocr_box_reads_a_rendered_crop():
    pdf = pymupdf.open()
    page = pdf.new_page(width=400, height=200)
    page.insert_text((40, 100), "LOA 199 ft", fontsize=28)
    reading = ocr_box(pdf.tobytes(), 1, Box(page=1, x0=30, y0=70, x1=300, y1=115))
    assert reading["method"] == "ocr" and "LOA" in reading["text"].upper() and "199" in reading["text"]
    assert 0 < reading["confidence"] <= 1


# -- spreadsheet and IFC readers -------------------------------------------------------------------------------

def door_workbook(path):
    book = openpyxl.Workbook()
    doors = book.active
    doors.title = "Doors"
    doors.append(["DOOR SCHEDULE - DIMENSIONS IN MM"])
    doors.append(["DOOR NO", "CLEAR WIDTH (mm)", "OPENING DEPTH (mm)", "LEAF WIDTH", "ACCESSIBLE ROUTE"])
    doors.append([101, 915, 200, 1000, "Yes"])
    doors.append([102, None, 150.5, 1000, "No"])
    doors.append(["DOOR 103", "36 in", "bad", 1000, "maybe"])
    doors.append([None, None, None, None, None])
    doors.append(["NOTE: all doors fire rated", None, None, None, None])
    stairs = book.create_sheet("Stairs")
    stairs.append(["STAIR", "CLEAR WIDTH (mm)", "PERSONS SERVED"])
    stairs.append(["STAIR B", 1200, 120])
    stairs.append(["C", 1100, None])
    book.save(path)
    return path.read_bytes()


def test_xlsx_schedule(tmp_path):
    data = door_workbook(tmp_path / "doors.xlsx")
    found, info = read_table_file(data, "doors.xlsx")
    assert info["status"] == "read" and info["sheets"] == ["Doors", "Stairs"]
    assert info["header_row"] == 2 and info["mapped_columns"] == {
        "B": "clear_width", "C": "opening_depth", "E": "accessible_route"}
    assert info["unmapped_columns"] == ["LEAF WIDTH"]  # a lookalike column is never mapped
    cell = {(c.subject, c.property): c for c in found}
    width = cell[("door-number:101", "clear_width")]
    assert (width.value, width.unit, width.method, width.page) == (915.0, "mm", "table_cell", 1)
    assert width.line_ids == ["Doors!B3"] and width.quote == "915" and width.fact_id == "door.clear_width"
    assert width.readings[0]["method"] == "cell" and "unit mm stated in the column header" in width.checks
    assert cell[("door-number:101", "accessible_route")].value == "yes"
    assert cell[("door-number:102", "opening_depth")].value == 150.5
    assert cell[("door-number:103", "clear_width")].unit == "in"  # a cell's own unit wins over the header's
    assert ("door-number:103", "accessible_route") not in cell and ("door-number:103", "opening_depth") not in cell
    assert cell[("stair:B", "clear_width")].fact_id == "stair.clear_width"
    assert cell[("stair:B", "persons_served")].value == 120.0 and cell[("stair:C", "clear_width")].value == 1100.0
    assert ("door-number:102", "clear_width") not in cell  # the blank cell gives no candidate
    missing = {(m["subject"], m["property"]): m for m in info["missing"]}
    assert set(missing) == {("door-number:102", "clear_width"), ("stair:C", "persons_served")}
    assert (missing[("door-number:102", "clear_width")]["row"], missing[("door-number:102", "clear_width")]["column"]) == (4, "B")
    assert any(r["row"] == 7 for r in info["skipped_rows"])  # the NOTE row names no door
    assert {u["cell"] for u in info["unreadable"]} == {"Doors!C5", "Doors!E5"}
    assert all(tier_for(c) == Tier.A for c in found)


def test_csv_with_mm_headers(tmp_path):
    path = tmp_path / "doors.csv"
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerows([["Door No", "Clear Width [mm]", "Opening Depth, mm"], ["201", "900", ""], ["202", "", "310"]])
    found, info = read_table_file(path.read_bytes(), "doors.csv")
    assert info["sheets"] == ["csv"] and info["header_row"] == 1
    assert {(c.subject, c.property, c.value, c.unit) for c in found} == {
        ("door-number:201", "clear_width", 900.0, "mm"), ("door-number:202", "opening_depth", 310.0, "mm")}
    assert [c.line_ids for c in found] == [["csv!B2"], ["csv!C3"]]
    assert {(m["subject"], m["property"]) for m in info["missing"]} == {
        ("door-number:201", "opening_depth"), ("door-number:202", "clear_width")}


def test_table_without_a_unit_gives_no_length(tmp_path):
    path = tmp_path / "doors.csv"
    path.write_text("DOOR NO,CLEAR WIDTH\n301,915\n")
    found, info = read_table_file(path.read_bytes(), "doors.csv")
    assert found == [] and "stated unit" in info["unreadable"][0]["reason"]


def test_unreadable_tables(tmp_path):
    assert read_table_file(b"not a workbook", "x.xlsx")[1]["status"] == "couldn't be read"
    assert read_table_file(b"a,b\n1,2\n", "x.csv")[1]["status"] == "couldn't be read"
    assert read_table_file(b"", "x.pdf")[1]["status"] == "couldn't be read"


def build_ifc(path, metric="MILLIMETERS"):
    model = ifcopenshell.api.run("project.create_file")
    ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject", name="RCRV")
    if metric:
        ifcopenshell.api.run("unit.assign_unit", model, length={"is_metric": True, "raw": metric})
    door = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcDoor", name="Door 12")
    door.OverallWidth = 1000.0 if metric == "MILLIMETERS" else 1.0
    clear = 915.0 if metric == "MILLIMETERS" else 0.915
    pset = ifcopenshell.api.run("pset.add_pset", model, product=door, name="Pset_Custom")
    ifcopenshell.api.run("pset.edit_pset", model, pset=pset, properties={
        "ClearWidth": clear, "OpeningDepth": 200.0, "AccessibleRoute": True, "FireRating": "A60"})
    nameless = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcDoor", name="Main entrance")
    nameless.OverallWidth = 1200.0
    flight = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcStairFlight", name="Stair B")
    stair_pset = ifcopenshell.api.run("pset.add_pset", model, product=flight, name="Pset_Stair")
    ifcopenshell.api.run("pset.edit_pset", model, pset=stair_pset, properties={"ClearWidth": 1200.0, "PersonsServed": 120})
    model.write(str(path))
    return path.read_bytes(), door.GlobalId


def test_ifc_overall_width_is_opening_width_never_clear_width(tmp_path):
    data, door_id = build_ifc(tmp_path / "ship.ifc")
    found, info = read_ifc(data, "ship.ifc")
    assert info["status"] == "read" and info["length_unit"] == "mm" and info["doors"] == 2 and info["stairs"] == 1
    cell = {(c.subject, c.property): c for c in found}
    opening = cell[("door-number:12", "opening_width")]
    assert (opening.value, opening.unit, opening.method, opening.fact_id) == (1000.0, "mm", "ifc_property", "door.opening_width")
    assert opening.quote == "IfcDoor.OverallWidth = 1000" and opening.line_ids == [door_id]
    clear = cell[("door-number:12", "clear_width")]
    assert (clear.value, clear.unit, clear.fact_id) == (915.0, "mm", "door.clear_width")
    assert clear.quote == "Pset_Custom.ClearWidth = 915" and clear.value != opening.value
    assert not [c for c in found if c.property == "clear_width" and c.value == 1000.0]
    assert cell[("door-number:12", "opening_depth")].value == 200.0
    assert cell[("door-number:12", "accessible_route")].value == "yes"
    assert cell[("stair:B", "clear_width")].value == 1200.0 and cell[("stair:B", "persons_served")].value == 120.0
    assert info["skipped"][0]["name"] == "Main entrance"  # no door number: skipped, and said so
    assert "Pset_Custom.FireRating" in info["unmapped_properties"]
    assert all(tier_for(c) == Tier.A for c in found)


def test_ifc_in_meters(tmp_path):
    data, _ = build_ifc(tmp_path / "ship_m.ifc", metric="METERS")
    found, info = read_ifc(data, "ship_m.ifc")
    assert info["length_unit"] == "m"
    cell = {(c.subject, c.property): c for c in found}
    assert (cell[("door-number:12", "clear_width")].value, cell[("door-number:12", "clear_width")].unit) == (0.915, "m")
    assert cell[("door-number:12", "clear_width")].problems == []  # 0.915 m is read as 915 mm for the range check


def test_ifc_without_a_length_unit_gives_no_length(tmp_path):
    data, _ = build_ifc(tmp_path / "nounit.ifc", metric=None)
    found, info = read_ifc(data, "nounit.ifc")
    assert info["length_unit"] == "not stated" and not [c for c in found if c.unit]
    assert any(c.property == "accessible_route" for c in found)


def test_ifc_that_will_not_open():
    found, info = read_ifc(b"this is not an IFC file", "bad.ifc")
    assert found == [] and info["status"] == "couldn't be read" and info["reason"]


# -- tiers and facts -------------------------------------------------------------------------------------------

def cand(method="labeled_rule", readings=(), problems=(), value=299.8, unit="m"):
    return FactCandidate(fact_id="ship.length_overall", subject="ship", property="length_overall", value=value,
                         unit=unit, page=4, line_ids=["p4-l17"], label_text="LOA", quote="LOA 299.80 m",
                         box=Box(page=4, x0=1, y0=2, x1=3, y1=4), method=method, readings=list(readings),
                         checks=["a check"], problems=list(problems))


def reading(method, text="299.80 m", value=299.8, unit="m"):
    return {"method": method, "text": text, "value": value, "unit": unit, "confidence": None}


def test_tier_rules():
    assert tier_for(cand("table_cell")) == Tier.A and tier_for(cand("ifc_property")) == Tier.A
    assert tier_for(cand("table_cell", problems=["out of range"])) == Tier.D
    assert tier_for(cand(readings=[reading("text_layer"), reading("ocr", "299800 mm", 299800.0, "mm")])) == Tier.A
    assert tier_for(cand(readings=[reading("ocr"), reading("ai_transcription")])) == Tier.B
    assert tier_for(cand(readings=[reading("text_layer"), reading("ai_transcription")])) == Tier.B
    assert tier_for(cand(readings=[reading("ocr")])) == Tier.C
    assert tier_for(cand(readings=[reading("text_layer")])) == Tier.C
    assert tier_for(cand(readings=[reading("ocr"), reading("ocr")])) == Tier.C  # one method twice is one reading
    assert tier_for(cand()) == Tier.C
    assert tier_for(cand(readings=[reading("text_layer"), reading("ocr")], problems=["disagrees"])) == Tier.D
    assert tier_for(cand(readings=[reading("text_layer"), reading("ocr", "289.80 m", 289.8)])) == Tier.D
    assert tier_for(cand(readings=[reading("text_layer"), reading("ocr", "garbage", None)])) == Tier.C


def test_candidate_to_fact_for_a_document_reading():
    c = cand(readings=[reading("text_layer"), reading("ocr")])
    fact = candidate_to_fact(c, "spec.pdf", doc_id="SPEC-1", revision="B")
    assert (fact.subject, fact.property, fact.value, fact.unit) == ("ship", "length_overall", 299.8, "m")
    assert fact.tier == Tier.A and fact.confidence == "high"
    assert fact.source.kind == SourceKind.DOCUMENT and fact.source.file == "spec.pdf"
    assert fact.source.locator == "page 4, lines p4-l17" and fact.source.quote == "LOA 299.80 m"
    evidence = fact.evidence
    assert (evidence.file, evidence.doc_id, evidence.revision, evidence.page) == ("spec.pdf", "SPEC-1", "B", 4)
    assert evidence.element_ids == ["p4-l17"] and evidence.box == c.box and evidence.checks == ["a check"]
    assert [r.method for r in evidence.readings] == ["text_layer", "ocr"] and evidence.readings[0].value == 299.8


def test_candidate_to_fact_locators_and_tiers(tmp_path):
    cells, _ = read_table_file(door_workbook(tmp_path / "d.xlsx"), "d.xlsx")
    fact = candidate_to_fact(cells[0], "d.xlsx")
    assert fact.source.locator == "Doors!B3" and fact.tier == Tier.A
    data, door_id = build_ifc(tmp_path / "s.ifc")
    ifc, _ = read_ifc(data, "s.ifc")
    assert candidate_to_fact(ifc[0], "s.ifc", kind=SourceKind.MODEL_3D).source.locator == f"IFC GlobalId {door_id}"
    bad = candidate_to_fact(cand(problems=["second reading disagrees"]), "x.pdf")
    assert bad.tier == Tier.D and bad.confidence == "low" and bad.evidence.problems == ["second reading disagrees"]
    assert candidate_to_fact(cand(readings=[reading("ocr")]), "x.pdf").tier == Tier.C
    assert len(facts_from_candidates(cells, "d.xlsx", "DOORS", "A")) == len(cells)
