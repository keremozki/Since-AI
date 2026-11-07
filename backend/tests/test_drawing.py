"""The code reader reports only what is written, and an uncertain reading never becomes a pass."""
import pymupdf
import pytest

from app.checks import check_door_clear_width
from app.drawing import find_lengths, read_pdf
from app.models import Rule, Status
from app.profiles import PROFILES
from app.store import FactStore

DOOR_RULE = Rule(id="D", title="Door", area="A", source="S", check="door_clear_width", params={"min_in": 32, "min_mm": 815})


@pytest.mark.parametrize("text, value, unit", [
    ('CL OPG 34"', 34, "in"), ('CL OPG 33 1/2"', 33.5, "in"), ("CL OPG 2'-8\"", 32, "in"),
    ("2' 8 1/2\"", 32.5, "in"), ("CL OPG 815 mm", 815, "mm"), ("1.2 m", 1.2, "m"),
    ("261’— 6”", 3138, "in"), ('31 7/8"', 31.875, "in"), ("30 in", 30, "in"),
])
def test_lengths_are_parsed(text, value, unit):
    found = find_lengths(text)
    assert len(found) == 1 and found[0].value == pytest.approx(value) and found[0].unit == unit


@pytest.mark.parametrize("text", ['31 7/2"', '30 7/3"', "2'-15\"", "CABIN 301", "1:12"])
def test_impossible_or_unitless_values_are_not_read(text):
    assert find_lengths(text) == []


def test_bare_number_needs_a_sheet_unit_and_a_width_keyword():
    assert find_lengths("CL OPG 850") == []
    found = find_lengths("CL OPG 850", sheet_unit="mm")
    assert found[0].value == 850 and not found[0].unit_written
    assert find_lengths("CABIN 850", sheet_unit="mm") == []


def sheet(*texts, scanned=False):
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    if scanned:
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 80, 60), False)
        pix.set_rect(pix.irect, (230,))
        page.insert_image(page.rect, pixmap=pix)
    for (x, y), text, *rotate in texts:
        page.insert_text((x, y), text, fontsize=9, rotate=rotate[0] if rotate else 0)
    return doc.tobytes()


def facts(data):
    return {(f.subject, f.property): f for f in read_pdf(data, "t.pdf").facts}


def test_tag_and_label_are_paired_and_traced():
    found = facts(sheet(((100, 100), "D301"), ((100, 112), 'CL OPG 30"'), ((300, 30), "SCALE 1:50")))
    width = found[("door-number:301", "clear_width")]
    assert width.value == 30 and width.unit == "in" and width.confidence == "high"
    assert width.meta["reader"] == "vector" and width.meta["scale_known"] and "page 1" in width.source.locator


def test_door_without_written_width_is_shown_not_guessed():
    found = facts(sheet(((100, 100), "D308")))
    assert ("door-number:308", "clear_width") not in found
    assert ("door-number:308", "shown_on") in found


def test_label_between_two_tags_is_ambiguous_and_low():
    found = facts(sheet(((100, 100), "D301"), ((160, 100), "D302"), ((128, 112), 'CL OPG 36"')))
    width = next(f for (s, p), f in found.items() if p == "clear_width")
    assert width.meta["ambiguous_pairing"] and width.confidence == "low"


def test_low_confidence_reading_never_passes():
    data = sheet(((100, 100), "D301"), ((160, 100), "D302"), ((128, 112), 'CL OPG 36"'))
    store = FactStore(read_pdf(data, "t.pdf").facts)
    statuses = {f.subject: f.status for f in check_door_clear_width(DOOR_RULE, store, PROFILES["passenger-test"])}
    assert Status.PASS not in statuses.values()


def test_scanned_sheet_readings_are_low_confidence():
    width = facts(sheet(((100, 100), 'D301 CL OPG 30"'), scanned=True))[("door-number:301", "clear_width")]
    assert width.meta["ocr_text"] and width.confidence == "low"


def test_schedule_row_is_read_as_a_table():
    found = facts(sheet(((500, 60), "DOOR SCHEDULE"), ((500, 76), 'D407    30"')))
    assert found[("door-number:407", "clear_width")].meta["from_table"]


def test_ship_length_from_a_rotated_table_row():
    data = sheet(((140, 500), "LENGTH OVERALL", 90), ((140, 300), "261'-6\"", 90))
    loa = facts(data)[("ship", "length_overall")]
    assert loa.value == 3138 and loa.meta["from_table"]


def test_drawing_door_gets_a_result_with_evidence():
    store = FactStore(read_pdf(sheet(((100, 100), 'D302 CL OPG 30"')), "t.pdf").facts)
    (finding,) = check_door_clear_width(DOOR_RULE, store, PROFILES["passenger-test"])
    assert finding.status == Status.FAIL and finding.evidence.facts[0].meta["reader"] == "vector"
