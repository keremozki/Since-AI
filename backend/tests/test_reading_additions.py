"""Reader additions found by testing on the synthetic package: count x rating totals, side-named items, title presence."""
import pymupdf

from app import dictionary
from app.models import Box
from app.reading.labeled import _PRODUCT, parse_value, scan_labeled, subject_in_line
from app.reading.model import DocumentMap, Line, PageInfo
from app.reading.pipeline import presence_candidates


def line(i, text, x0, y0, x1, page=1):
    return Line(id=f"p{page}-l{i}", page=page, text=text, box=Box(page=page, x0=x0, y0=y0, x1=x1, y1=y0 + 13), source="text_layer")


def doc(lines):
    return DocumentMap(file="t.pdf", sha256="x", pages=[PageInfo(page=1, width_pt=595, height_pt=842, kind="vector_text")], lines=lines)


def test_count_times_rating_gives_the_total_only_when_the_product_holds():
    defn = dictionary.by_id("lifeboat.capacity")
    parsed, why = parse_value(defn, "7 x 350 persons = 2,450 persons")
    assert parsed.value == 2450.0 and "checked by code" in parsed.shown
    assert parse_value(defn, "7 x 350 persons 2,450 persons")[0].value == 2450.0  # OCR dropped the "="
    parsed, why = parse_value(defn, "7 x 350 persons = 2,400 persons")
    assert parsed is None and "is not 7 x 350" in why
    assert _PRODUCT.match("16 davit-launched liferafts") is None


def test_side_named_subject_comes_from_the_label_line():
    defn = dictionary.by_id("lifeboat.capacity")
    assert subject_in_line(defn, "Lifeboats, port side") == "lifeboats:port"
    assert subject_in_line(defn, "LIFEBOATS STBD") == "lifeboats:starboard"
    assert subject_in_line(defn, "Lifeboats, port and starboard") is None
    assert subject_in_line(defn, "Lifeboats are totally enclosed") is None


def test_a_long_value_on_the_same_row_is_read():
    dm = doc([line(1, "Lifeboats, port side", 62, 107, 146), line(2, "7 x 350 persons = 2,450 persons", 275, 107, 419),
              line(3, "Lifeboats, starboard side", 62, 125, 170), line(4, "7 x 350 persons = 2,450 persons", 275, 125, 419)])
    found, _refused = scan_labeled(dm)
    got = {(c.subject, c.value) for c in found if c.fact_id == "lifeboat.capacity"}
    assert got == {("lifeboats:port", 2450.0), ("lifeboats:starboard", 2450.0)}


def test_a_heading_is_not_a_flag_value():
    dm = doc([line(1, "4. Registry and dates", 57, 100, 200), line(2, "Flag", 62, 120, 80), line(3, "Malta", 275, 120, 300)])
    found, refused = scan_labeled(dm)
    assert [c.value for c in found if c.fact_id == "ship.flag"] == ["Malta"]
    assert any("not one of the values listed" in r["reasons"][0] for r in refused if r["fact_id"] == "ship.flag")


def _pdf(lines: list[str]) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    for i, text in enumerate(lines):
        page.insert_text((72, 80 + 20 * i), text, fontsize=11)
    return document.tobytes()


def test_presence_needs_the_documents_own_title():
    from app.reading.pagemap import build_document_map
    analysis = _pdf(["EA-101 Evacuation analysis (simplified method)", "1. Scope"])
    found = presence_candidates(build_document_map(analysis, "ea.pdf", ocr=False), analysis)
    assert [(c.subject, c.value) for c in found] == [("evacuation", "yes")]
    assert {r["method"] for r in found[0].readings} == {"text_layer", "ocr"}
    spec = _pdf(["OUTLINE SPECIFICATION", "7. Evacuation", "Evacuation analysis: see EA-101"])
    assert presence_candidates(build_document_map(spec, "spec.pdf", ocr=False), spec) == []
