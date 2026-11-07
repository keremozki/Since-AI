"""The reading core: page maps, title blocks and calibration, on small documents built in memory."""
from __future__ import annotations

import os
import io
import re
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.models import Box
from app.reading import pagemap
from app.reading.calibrate import calibrate_page, fit_deck_ladder, fit_frame_ruler
from app.reading.model import DocumentMap, Line, PageInfo, Word
from app.reading.pagemap import build_document_map, classify_page
from app.reading.titleblock import find_scale_notes, read_title_block

RCRV = Path(os.environ.get("RCRV_GA_PDF", "RCRV General Arrangement not set"))  # tests on it skip without this file


# ---------------------------------------------------------------- builders

def pdf_bytes(draw, width: float = 400, height: float = 300, rotation: int = 0, pages: int = 1) -> bytes:
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=width, height=height)
        draw(page)
        if rotation:
            page.set_rotation(rotation)
    return doc.tobytes()


def noise_png(size: int = 120) -> bytes:
    rng = np.random.default_rng(1)
    out = io.BytesIO()
    Image.fromarray(rng.integers(0, 255, (size, size), dtype=np.uint8)).save(out, "PNG")
    return out.getvalue()


def ink_box(page: pymupdf.Page, zoom: int = 4) -> tuple[float, float, float, float]:
    """Bounding box in displayed points of everything dark on the page, from a render."""
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY, alpha=False)
    pixels = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    ys, xs = np.nonzero(pixels < 128)
    return xs.min() / zoom, ys.min() / zoom, (xs.max() + 1) / zoom, (ys.max() + 1) / zoom


class Sheet:
    """A hand-built DocumentMap: labels with exact boxes, no PDF involved."""

    def __init__(self, pages: int = 1, width: float = 1224, height: float = 792) -> None:
        self.dm = DocumentMap(file="sheet.pdf", sha256="0" * 64)
        for n in range(1, pages + 1):
            self.dm.pages.append(PageInfo(page=n, width_pt=width, height_pt=height, kind="vector_strokes"))
        self.lines = {n: 0 for n in range(1, pages + 1)}
        self.words = {n: 0 for n in range(1, pages + 1)}

    def label(self, text: str, x0: float, y0: float, x1: float, y1: float, page: int = 1, conf: float | None = 0.95) -> str:
        self.lines[page] += 1
        line_id = f"p{page}-l{self.lines[page]}"
        box = Box(page=page, x0=x0, y0=y0, x1=x1, y1=y1)
        word_ids = []
        parts = text.split()
        for i, part in enumerate(parts):
            self.words[page] += 1
            word_ids.append(f"p{page}-w{self.words[page]}")
            step = (x1 - x0) / len(parts)
            self.dm.words.append(Word(id=word_ids[-1], page=page, text=part, source="ocr", confidence=conf,
                                      box=Box(page=page, x0=x0 + i * step, y0=y0, x1=x0 + (i + 1) * step, y1=y1)))
        self.dm.lines.append(Line(id=line_id, page=page, text=text, box=box, source="ocr", word_ids=word_ids, confidence=conf))
        return line_id

    def ruler(self, frames, x_at_0: float = 963.5, pt_per_frame: float = 8.7895, y: float = 458.0, page: int = 1,
              misread: dict[int, str] | None = None) -> None:
        for frame in frames:
            text = (misread or {}).get(frame, str(frame))
            x = x_at_0 - pt_per_frame * frame
            self.label(text, x - 3.5, y, x + 3.5, y + 6.5, page)

    def ladder(self, levels_in, baseline_y: float = 536.7, in_per_pt: float = 2.7319, x: float = 1058.0,
               page: int = 1, shift: dict[float, float] | None = None) -> None:
        for inches in levels_in:
            y = baseline_y - inches / in_per_pt + (shift or {}).get(inches, 0.0)
            feet, rest = divmod(inches, 12)
            self.label(f"{int(feet)}'-{int(rest)}\" ABL", x, y, x + 32, y + 7.5, page)


# ---------------------------------------------------------------- the text layer

def test_text_layer_gives_words_lines_and_ids():
    def draw(page):
        page.insert_text((50, 60), "LOA 199 FT", fontsize=12)
        page.insert_text((50, 100), "BEAM 41 FT", fontsize=12)
    dm = build_document_map(pdf_bytes(draw), "plain.pdf")
    assert dm.status == "read" and dm.status_reason == ""
    assert [l.text for l in dm.lines] == ["LOA 199 FT", "BEAM 41 FT"]
    assert [l.id for l in dm.lines] == ["p1-l1", "p1-l2"]
    assert [w.text for w in dm.words] == ["LOA", "199", "FT", "BEAM", "41", "FT"]
    assert dm.lines[0].word_ids == ["p1-w1", "p1-w2", "p1-w3"]
    assert all(l.source == "text_layer" and l.confidence is None for l in dm.lines)
    info = dm.pages[0]
    assert (info.kind, info.rotation, info.text_words, info.ocr_used) == ("vector_text", 0, 6, False)
    line = dm.lines[0]
    assert 49 <= line.box.x0 <= 52 and 45 <= line.box.y0 <= 52 and line.box.y1 <= 64
    assert line.box.x0 == min(w.box.x0 for w in dm.words[:3]) and line.box.x1 == max(w.box.x1 for w in dm.words[:3])


def test_cells_far_apart_on_one_baseline_are_separate_lines():
    line = [("SIZE", (10.0, 100.0, 30.0, 108.0)), ("FSCM", (36.0, 100.0, 60.0, 108.0)), ("DRAWING", (100.0, 100.0, 140.0, 108.0)),
            ("NO.", (143.0, 100.0, 157.0, 108.0))]
    pieces = pagemap._split_at_wide_gaps(line)
    assert [[w for w, _ in p] for p in pieces] == [["SIZE", "FSCM"], ["DRAWING", "NO."]]  # a 40 pt gap, not a 6 pt space
    column = [("A", (10.0, 10.0, 18.0, 20.0)), ("B", (10.0, 21.0, 18.0, 31.0)), ("C", (10.0, 80.0, 18.0, 90.0))]
    assert [[w for w, _ in p] for p in pagemap._split_at_wide_gaps(column)] == [["A", "B"], ["C"]]
    assert pagemap._split_at_wide_gaps([("ONE", (0.0, 0.0, 20.0, 8.0))]) == [[("ONE", (0.0, 0.0, 20.0, 8.0))]]


def test_rotated_page_boxes_are_in_the_displayed_frame():
    def draw(page):
        page.insert_text((60, 100), "HELLO WORLD", fontsize=28)
    data = pdf_bytes(draw, 400, 300, rotation=90)
    dm = build_document_map(data, "rotated.pdf")
    info = dm.pages[0]
    assert (info.width_pt, info.height_pt, info.rotation) == (300, 400, 90)  # displayed, not the mediabox 400 x 300

    doc = pymupdf.open(stream=data, filetype="pdf")
    unrotated = doc[0].get_text("words")[0][:4]  # PyMuPDF reports the unrotated frame
    h = 300  # a 90 degree turn sends (x, y) to (H - y, x), with H the unrotated page height
    expected = (h - unrotated[3], unrotated[0], h - unrotated[1], unrotated[2])
    hello = dm.words[0]
    assert hello.text == "HELLO"
    assert (hello.box.x0, hello.box.y0, hello.box.x1, hello.box.y1) == pytest.approx(expected, abs=0.02)
    # the displayed render has its ink inside the words' boxes
    ink = ink_box(doc[0])
    left, top = min(w.box.x0 for w in dm.words), min(w.box.y0 for w in dm.words)
    right, bottom = max(w.box.x1 for w in dm.words), max(w.box.y1 for w in dm.words)
    assert left - 1.5 <= ink[0] and ink[2] <= right + 1.5 and top - 1.5 <= ink[1] and ink[3] <= bottom + 1.5
    assert ink[3] - ink[1] > 150  # the two words run down the page, so the boxes are tall rather than wide


def test_text_layer_and_ocr_land_in_the_same_displayed_box_on_a_rotated_page():
    def draw(page):
        page.insert_text((90, 250), "FRAME 90 LOA", fontsize=24, rotate=90)  # upright once the page is turned
    data = pdf_bytes(draw, 400, 300, rotation=90)
    dm = build_document_map(data, "rotated.pdf")
    assert [l.text for l in dm.lines] == ["FRAME 90 LOA"]
    text_box = dm.lines[0].box
    assert text_box.x1 - text_box.x0 > 3 * (text_box.y1 - text_box.y0)  # horizontal in the displayed frame

    page = pymupdf.open(stream=data, filetype="pdf")[0]
    ocr_lines = pagemap._ocr_page(page, 300)
    assert len(ocr_lines) == 1 and re.sub(r"\s", "", ocr_lines[0].text.upper()) == "FRAME90LOA"
    ocr_box = ocr_lines[0].box  # the text layer's box includes the font's ascent and descent; the OCR box hugs the ink
    assert (ocr_box[0], ocr_box[2]) == pytest.approx((text_box.x0, text_box.x1), abs=5.0)
    assert (ocr_box[1] + ocr_box[3]) / 2 == pytest.approx((text_box.y0 + text_box.y1) / 2, abs=4.0)
    assert text_box.y0 - 3 <= ocr_box[1] and ocr_box[3] <= text_box.y1 + 3


# ---------------------------------------------------------------- page kinds

def test_page_with_many_strokes_and_no_text_is_vector_strokes():
    def draw(page):
        for i in range(80):
            page.draw_line((20 + 4 * i, 40), (22 + 4 * i, 90), width=0.5)
    dm = build_document_map(pdf_bytes(draw), "strokes.pdf", ocr=False)
    info = dm.pages[0]
    assert info.kind == "vector_strokes" and info.text_words == 0 and info.vector_paths >= 80
    assert dm.status == "partly read" and "page(s) 1" in dm.status_reason and "OCR was off" in dm.status_reason


def test_empty_text_raster_and_mixed_pages():
    assert build_document_map(pdf_bytes(lambda p: None), "blank.pdf").pages[0].kind == "empty"

    def scan(page):
        page.insert_image(page.rect, stream=noise_png(), keep_proportion=False)
    raster = build_document_map(pdf_bytes(scan), "scan.pdf", ocr=False)
    assert raster.pages[0].kind == "raster" and raster.pages[0].image_cover > 0.9

    def labeled_scan(page):
        page.insert_image(page.rect, stream=noise_png(), keep_proportion=False)
        for i in range(12):
            page.insert_text((20, 20 + 18 * i), f"word{i} text", fontsize=9)
    mixed = build_document_map(pdf_bytes(labeled_scan), "mixed.pdf")
    assert mixed.pages[0].kind == "mixed" and mixed.pages[0].ocr_used is False  # a text layer exists: no OCR here


@pytest.mark.parametrize("words, paths, cover, kind", [
    (0, 0, 0.0, "empty"),
    (5, 3, 0.0, "vector_text"),
    (300, 40, 0.0, "vector_text"),
    (800, 150_000, 0.0, "vector_text"),
    (20, 50_000, 0.0, "mixed"),  # a text layer, but most lettering is probably drawn
    (0, 4_800, 0.0, "vector_strokes"),
    (3, 60_000, 0.0, "vector_strokes"),  # a stamp's worth of text on a stroked drawing
    (0, 0, 0.95, "raster"),
    (4, 10, 0.8, "raster"),
    (400, 100, 0.8, "mixed"),
])
def test_classify_page(words, paths, cover, kind):
    assert classify_page(words, paths, cover) == kind


# ---------------------------------------------------------------- status, pages, cache

def test_not_a_document_and_encrypted_pdfs_couldnt_be_read():
    assert build_document_map(b"not a pdf at all", "x.pdf").status == "couldn't be read"
    assert build_document_map(b"plain text", "notes.txt").status == "couldn't be read"
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret")
    locked = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o")
    dm = build_document_map(locked, "locked.pdf")
    assert dm.status == "couldn't be read" and "password" in dm.status_reason and dm.pages == []


def test_pages_argument_limits_ocr_and_skipped_pages_make_it_partly_read(monkeypatch):
    def draw(page):
        for i in range(60):
            page.draw_line((10 + 5 * i, 20), (12 + 5 * i, 80), width=0.5)
    ocr_calls = []

    def fake_ocr(page, dpi):
        ocr_calls.append((page.number + 1, dpi))
        return [pagemap._Raw("FAKE 12", (10.0, 100.0, 60.0, 112.0), "ocr", 0.9, [("FAKE", (10.0, 100.0, 35.0, 112.0)), ("12", (37.0, 100.0, 60.0, 112.0))])]
    monkeypatch.setattr(pagemap, "_ocr_page", fake_ocr)
    dm = build_document_map(pdf_bytes(draw, pages=3), "three.pdf", pages=[2], dpi=250)
    assert ocr_calls == [(2, 250)]
    assert [p.ocr_used for p in dm.pages] == [False, True, False]
    assert [l.id for l in dm.lines] == ["p2-l1"] and dm.lines[0].source == "ocr" and dm.lines[0].confidence == 0.9
    assert [w.id for w in dm.words] == ["p2-w1", "p2-w2"] and dm.words[0].confidence == 0.9
    assert dm.status == "partly read" and "1, 3" in dm.status_reason and "not requested" in dm.status_reason

    ocr_calls.clear()
    full = build_document_map(pdf_bytes(draw, pages=3), "three.pdf")
    assert [c[0] for c in ocr_calls] == [1, 2, 3] and full.status == "read"


def test_ocr_failure_is_reported_not_hidden(monkeypatch):
    def draw(page):
        for i in range(60):
            page.draw_line((10 + 5 * i, 20), (12 + 5 * i, 80), width=0.5)

    def broken(page, dpi):
        raise RuntimeError("model missing")
    monkeypatch.setattr(pagemap, "_ocr_page", broken)
    dm = build_document_map(pdf_bytes(draw), "strokes.pdf")
    assert dm.status == "partly read" and "OCR failed" in dm.status_reason and "model missing" in dm.status_reason


def test_cache_is_keyed_by_content_and_parameters(tmp_path, monkeypatch):
    def draw(page):
        page.insert_text((50, 60), "DRAWING NO. SYN-GA-105", fontsize=12)
    data = pdf_bytes(draw)
    first = build_document_map(data, "a.pdf", cache_dir=tmp_path / "cache")
    files = list((tmp_path / "cache").glob("*.json"))
    assert len(files) == 1 and files[0].name.startswith(first.sha256 + "-")

    def no_rebuild(*args, **kwargs):
        raise AssertionError("the cache should have answered")
    monkeypatch.setattr(pagemap, "_read_pdf", no_rebuild)
    again = build_document_map(data, "renamed.pdf", cache_dir=tmp_path / "cache")
    assert again.file == "renamed.pdf" and again.lines == first.lines and again.pages == first.pages
    monkeypatch.undo()
    build_document_map(data, "a.pdf", cache_dir=tmp_path / "cache", ocr=False)
    assert len(list((tmp_path / "cache").glob("*.json"))) == 2  # other parameters, other file
    files[0].write_text("{ broken")
    assert build_document_map(data, "a.pdf", cache_dir=tmp_path / "cache").lines == first.lines  # rebuilt, not trusted


# ---------------------------------------------------------------- OCR

def test_ocr_reads_a_rendered_image_with_boxes_in_points():
    font = ImageFont.load_default(size=56)
    image = Image.new("L", (900, 260), 255)
    draw = ImageDraw.Draw(image)
    draw.text((60, 40), "LOA 199 FT", fill=0, font=font)
    draw.text((500, 150), "FRAME 90", fill=0, font=font)
    out = io.BytesIO()
    image.save(out, "PNG")
    dm = build_document_map(out.getvalue(), "plan.png")
    assert dm.status == "read" and dm.pages[0].kind == "raster" and dm.pages[0].ocr_used
    assert (dm.pages[0].width_pt, dm.pages[0].height_pt) == (900, 260)  # 72 dpi: a pixel is a point
    texts = {re.sub(r"\s", "", l.text.upper()): l for l in dm.lines}
    assert "LOA199FT" in texts and "FRAME90" in texts
    loa, frame = texts["LOA199FT"], texts["FRAME90"]
    assert loa.source == "ocr" and 0.5 < loa.confidence <= 1.0
    assert 40 <= loa.box.x0 <= 80 and 30 <= loa.box.y0 <= 60 and loa.box.x1 > 300
    assert frame.box.x0 > 450 and frame.box.y0 > 130
    words = [w for w in dm.words if w.id in loa.word_ids]
    assert [w.text.upper() for w in words] == ["LOA", "199", "FT"]
    assert words[0].box.x1 <= words[1].box.x0 + 1 and words[1].box.x1 <= words[2].box.x0 + 1  # proportional split keeps order


class SceneEngine:
    """A stand-in for the OCR engine that finds the lines of a scene in whatever tile it is asked to read.

    A line cut by the tile edge comes back truncated, the way a real detector cuts one.
    """

    def __init__(self, scene, rec_text=None) -> None:  # rec_text: a string, a list read in turn, or a function of the crop
        self.scene, self.rec_text, self.origin = scene, rec_text, (0, 0)
        self.rec_calls = 0

    def __call__(self, array, use_det=True, use_cls=False, use_rec=True, **kwargs):
        if not use_det:
            self.rec_calls += 1
            if callable(self.rec_text):
                return [list(self.rec_text(array))], None
            text = self.rec_text.pop(0) if isinstance(self.rec_text, list) else self.rec_text
            return [[text or "", 0.97]], None
        ox, oy = self.origin
        height, width = array.shape[:2]
        found = []
        for text, (x0, y0, x1, y1), *options in self.scene:
            options = options[0] if options else {}
            if options.get("strips") and height >= 400:
                continue  # the detector misses it among the lines of a full tile but finds it in a thin strip
            cx0, cy0, cx1, cy1 = max(x0 - ox, 0), max(y0 - oy, 0), min(x1 - ox, width), min(y1 - oy, height)
            seen = (cx1 - cx0) / (x1 - x0)
            if seen < 0.5 or cy1 <= cy0:
                continue
            found.append([[[cx0, cy0], [cx1, cy0], [cx1, cy1], [cx0, cy1]], text[: round(len(text) * seen)],
                          options.get("conf", 0.9)])
        return found, None


def scene_render(engine):
    def render(x0, y0, x1, y1):
        engine.origin = (x0, y0)
        return np.zeros((y1 - y0, x1 - x0), np.uint8), x0, y0
    return render


def test_tiles_cover_the_surface_with_overlap():
    for length in (1900, 2400, 2401, 5100, 6800, 14000):
        spans = pagemap._tiles(length)
        assert spans[0][0] == 0 and spans[-1][1] == length
        assert all(b - a <= pagemap.TILE_PX for a, b in spans)
        assert all(spans[i + 1][0] < spans[i][1] for i in range(len(spans) - 1))  # neighbors overlap


def test_tiled_ocr_merges_overlap_duplicates_and_repairs_cut_lines(monkeypatch):
    whole_line = "LOA 199'-6\" OVERALL"
    scene = [
        ("ONLY ONCE", (100, 100, 400, 140)),
        ("IN THE OVERLAP", (1600, 300, 1760, 340)),  # both neighbors see it whole
        (whole_line, (1400, 600, 1900, 640)),  # cut by the seam at x=1867 in both neighbors
    ]
    engine = SceneEngine(scene)
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    hits = pagemap._ocr_surface(scene_render(engine), 5000, 1000, 1.0)
    assert sorted(t for t, _, _ in hits) == sorted(["ONLY ONCE", "IN THE OVERLAP", whole_line])
    box = next(b for t, _, b in hits if t == whole_line)
    assert box == pytest.approx((1400, 600, 1900, 640), abs=1)


def test_a_line_cut_at_a_seam_is_dropped_when_it_cannot_be_read_whole(monkeypatch):
    scene = [("A VERY LONG LINE", (500, 100, 2500, 140))]  # wider than any tile
    engine = SceneEngine(scene)
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    assert pagemap._ocr_surface(scene_render(engine), 5000, 400, 1.0) == []  # the truncated readings are not kept


def test_overlapping_detections_on_one_row_are_read_as_one_line(monkeypatch):
    scene = [("15 February 2", (100, 100, 440, 135)), ("2027", (407, 100, 540, 135))]
    engine = SceneEngine(scene, rec_text="15 February 2027")
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    hits = pagemap._ocr_surface(scene_render(engine), 1000, 300, 1.0)
    assert [t for t, _, _ in hits] == ["15 February 2027"] and engine.rec_calls == 1
    assert hits[0][2] == pytest.approx((100, 100, 540, 135), abs=0.5)
    assert hits[0][1] <= 0.9  # no more confident than the weakest detection


def test_neighbors_that_merely_touch_stay_separate(monkeypatch):
    scene = [("WET LAB", (100, 100, 300, 135)), ("440 FT2", (297, 100, 420, 135))]
    engine = SceneEngine(scene, rec_text="WRONG")
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    hits = pagemap._ocr_surface(scene_render(engine), 1000, 300, 1.0)
    assert sorted(t for t, _, _ in hits) == ["440 FT2", "WET LAB"] and engine.rec_calls == 0


def test_a_row_of_numbers_with_a_gap_is_read_again_as_a_strip(monkeypatch):
    row = [(str(v), (100 + 250 * i, 500, 130 + 250 * i, 530)) for i, v in enumerate([90, 85, 80, 75, 70, 65])]
    scene = [item for item in row if item[0] != "75"] + [("75", row[3][1], {"strips": True})]
    engine = SceneEngine(scene)
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    texts = sorted(t for t, _, _ in pagemap._ocr_surface(scene_render(engine), 2000, 1000, 1.0))
    assert texts == ["65", "70", "75", "80", "85", "90"]


def test_a_complete_row_of_numbers_is_not_read_again(monkeypatch):
    row = [(str(v), (100 + 250 * i, 500, 130 + 250 * i, 530)) for i, v in enumerate([90, 85, 80, 75, 70, 65])]
    engine = SceneEngine(row + [("65", (5000, 500, 5030, 530), {"strips": True})])
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    assert len(pagemap._ocr_surface(scene_render(engine), 2000, 1000, 1.0)) == 6  # the strip would have shown a seventh


@pytest.mark.parametrize("readings, expected", [
    (["J", "J", "[J", "[J"], ["J"]),  # the loose crop picks up the cell border; the letter is the same
    (["J", "U", "J", "J"], []),  # one reading differs: no value
    (["", "", "", ""], []),
    (["JJ", "JJ", "JJ", "JJ"], ["JJ"]),
    (["j!", "j!", "j", "j"], []),  # lower case is not a revision letter here
])
def test_the_one_big_letter_under_a_title_block_label_needs_every_reading_to_agree(monkeypatch, readings, expected):
    engine = SceneEngine([("REV", (1160, 734, 1170, 740))], rec_text=list(readings))
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    hits = pagemap._ocr_surface(scene_render(engine), 1400, 900, 1.0)
    assert [t for t, _, _ in hits if t != "REV"] == expected
    if expected:
        box = next(b for t, _, b in hits if t == expected[0])
        assert box[1] >= 740 and 1150 <= box[0] <= 1165  # the cell under the label


def test_weak_detections_of_turned_text_are_read_again_and_kept_only_if_sure(monkeypatch):
    upright_when_turned = lambda crop: ("LOA 199 FEET", 0.95) if crop.shape[1] > crop.shape[0] else ("", 0.0)
    scene = [("xq%", (700, 100, 745, 400), {"conf": 0.2}),  # tall: lettering that reads bottom to top
             ("blot", (900, 100, 910, 110), {"conf": 0.2})]  # a speck is not read again
    engine = SceneEngine(scene, rec_text=upright_when_turned)
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: engine)
    hits = pagemap._ocr_surface(scene_render(engine), 1400, 700, 1.0)
    assert [(t, c) for t, c, _ in hits] == [("LOA 199 FEET", 0.95)] and engine.rec_calls == 2  # one turn each way
    assert hits[0][2] == pytest.approx((700, 100, 745, 400), abs=0.5)

    unsure = SceneEngine(scene[:1], rec_text=lambda crop: ("LOA 199 FEET", 0.6))
    monkeypatch.setattr(pagemap, "_ocr_engine", lambda: unsure)
    assert pagemap._ocr_surface(scene_render(unsure), 1400, 700, 1.0) == []  # a weak turned reading is no reading


def test_text_in_every_orientation_is_read():
    font = ImageFont.load_default(size=44)

    def lettering(text: str) -> Image.Image:
        image = Image.new("L", (520, 80), 255)
        ImageDraw.Draw(image).text((10, 10), text, fill=0, font=font)
        return image
    page = Image.new("L", (1400, 700), 255)
    page.paste(lettering("DECK HEIGHT 45 FT"), (50, 50))
    page.paste(lettering("LOA 199 FEET").rotate(90, expand=True), (700, 100))  # reads bottom to top
    page.paste(lettering("BEAM 41 FEET").rotate(-90, expand=True), (900, 100))  # reads top to bottom
    page.paste(lettering("DISTANCE 40 FEET").rotate(180, expand=True), (100, 300))  # upside down
    gray = np.asarray(page)
    hits = pagemap._ocr_surface(lambda x0, y0, x1, y1: (gray[y0:y1, x0:x1], x0, y0), 1400, 700, 1.0)
    texts = {re.sub(r"\s", "", t.upper()) for t, _, _ in hits}
    assert {"DECKHEIGHT45FT", "LOA199FEET", "BEAM41FEET"} <= texts
    assert any(t.startswith("DISTANCE") and t.endswith("FEET") for t in texts)  # upside down; a 0 may come back as O


def test_word_boxes_of_an_ocr_line_are_proportional_and_tall_lines_keep_the_line_box():
    words = pagemap._split_words("LOA 199 FT", (10.0, 20.0, 110.0, 30.0))
    assert [w for w, _ in words] == ["LOA", "199", "FT"]
    assert words[0][1][0] == 10.0 and words[-1][1][2] == pytest.approx(110.0, abs=0.01)
    assert words[0][1][2] <= words[1][1][0] <= words[1][1][2] <= words[2][1][0]
    tall = pagemap._split_words("FRAME 90", (10.0, 20.0, 20.0, 120.0))
    assert [b for _, b in tall] == [(10.0, 20.0, 20.0, 120.0)] * 2


# ---------------------------------------------------------------- title block

def title_block_pdf(rev: str = "B", extra=None) -> bytes:
    def draw(page):
        page.insert_text((40, 60), "DRAWING NO.", fontsize=7)  # a reference table elsewhere on the sheet
        page.insert_text((40, 72), "OTHER-REF-001", fontsize=10)
        page.insert_text((40, 84), "REV", fontsize=7)
        page.insert_text((40, 96), "A", fontsize=10)
        page.insert_text((780, 700), "TITLE: GENERAL ARRANGEMENT", fontsize=9)
        page.insert_text((780, 740), "SIZE", fontsize=7)
        page.insert_text((780, 752), "A3", fontsize=11)
        page.insert_text((840, 740), "DRAWING NO.", fontsize=7)
        page.insert_text((840, 752), "SYN-GA-105", fontsize=11)
        page.insert_text((1000, 740), "REV", fontsize=7)
        page.insert_text((1004, 752), rev, fontsize=11)
        page.insert_text((780, 780), "SCALE 1:100", fontsize=8)
        page.insert_text((900, 780), "HULL #: 6096 6097 6098", fontsize=8)
        page.insert_text((60, 500), "FOR HULLS 6096 & 6098 ONLY", fontsize=8)
        for fn in extra or []:
            fn(page)
    return pdf_bytes(draw, 1191, 842)


def test_title_block_from_a_text_layer_page():
    dm = build_document_map(title_block_pdf(), "syn.pdf")
    tb = dm.title_block  # build_document_map fills it
    assert tb == read_title_block(dm)
    assert tb.drawing_no == "SYN-GA-105"  # the cell nearest the corner, not the reference table's
    assert tb.revision == "B"
    assert tb.title == "GENERAL ARRANGEMENT"
    assert tb.sheet_size == "A3"
    assert tb.scale_notes == ["1:100"]
    assert tb.hulls == ["6096", "6097", "6098"]  # the "ONLY" line restricts a revision, not the sheet
    used = {dm.line(e).text for e in tb.evidence}
    assert {"SYN-GA-105", "DRAWING NO.", "B", "REV", "A3", "SIZE"} <= used and "OTHER-REF-001" not in used


def test_inline_label_and_value_forms():
    def draw(page):
        page.insert_text((700, 780), "DRAWING NUMBER: GA-101-R2", fontsize=9)
        page.insert_text((700, 795), "REV C", fontsize=9)
        page.insert_text((700, 810), "SHEET SIZE: ANSI D", fontsize=9)
        page.insert_text((700, 825), "SCALE: NTS", fontsize=9)
    tb = read_title_block(build_document_map(pdf_bytes(draw, 1191, 842), "inline.pdf"))
    assert (tb.drawing_no, tb.revision, tb.sheet_size) == ("GA-101-R2", "C", "D")
    assert tb.scale_notes == ["SCALE: NTS"]


def test_two_equally_good_values_give_no_value():
    sheet = Sheet(width=1000, height=700)
    sheet.label("REV", 900, 650, 915, 657)
    sheet.label("A", 897, 662, 907, 672)
    sheet.label("B", 910, 662, 920, 672)  # as near as the other one
    sheet.label("DRAWING NO.", 700, 650, 760, 657)
    sheet.label("AB-12-34", 700, 662, 740, 672)
    tb = read_title_block(sheet.dm)
    assert tb.revision == "" and tb.drawing_no == "AB-12-34"


def test_a_value_must_have_the_right_shape():
    sheet = Sheet(width=1000, height=700)
    sheet.label("DRAWING NO.", 700, 650, 760, 657)
    sheet.label("ISSUED", 700, 662, 740, 672)  # no digits, no separators: not a drawing number
    sheet.label("REV", 900, 650, 915, 657)
    sheet.label("2OF10", 897, 662, 920, 672)  # a sheet count, not a revision
    tb = read_title_block(sheet.dm)
    assert tb.drawing_no == "" and tb.revision == ""


def test_pages_that_disagree_give_no_value_and_the_majority_wins():
    def page_lines(sheet, page, number, rev):
        sheet.label("DRAWING NO.", 700, 650, 760, 657, page=page)
        sheet.label(number, 700, 662, 760, 672, page=page)
        sheet.label("REV", 900, 650, 915, 657, page=page)
        sheet.label(rev, 902, 662, 910, 672, page=page)
    sheet = Sheet(pages=3, width=1000, height=700)
    page_lines(sheet, 1, "AA-100-1", "C")
    page_lines(sheet, 2, "AA-100-1", "C")
    page_lines(sheet, 3, "BB-200-2", "D")
    assert (read_title_block(sheet.dm).drawing_no, read_title_block(sheet.dm).revision) == ("AA-100-1", "C")
    two = Sheet(pages=2, width=1000, height=700)
    page_lines(two, 1, "AA-100-1", "C")
    page_lines(two, 2, "BB-200-2", "D")
    tb = read_title_block(two.dm)
    assert tb.drawing_no == "" and tb.revision == ""


def test_sheets_of_one_drawing_share_the_start_of_their_titles():
    sheet = Sheet(pages=2, width=1000, height=700)
    for page, view in ((1, "OUTBOARD PROFILE"), (2, "INBOARD PROFILE")):
        sheet.label("TITLE: GENERAL ARRANGEMENT - " + view, 700, 640, 900, 650, page=page)
    assert read_title_block(sheet.dm).title == "GENERAL ARRANGEMENT"


def test_scale_notes_as_written():
    assert find_scale_notes('SCALE 1:100 AND 1 : 50') == ["1:100", "1:50"]
    assert find_scale_notes("1/8\"=1'-0\"") == ["1/8\"=1'-0\""]
    assert find_scale_notes("3/16\" = 1'-0\"") == ["3/16\" = 1'-0\""]
    assert find_scale_notes("SCALE: NONE") == ["SCALE: NONE"]
    assert find_scale_notes("TIME 10:30 AND RATIO 11:50") == []  # not scale notes
    assert find_scale_notes("1:100.5") == ["1:100.5"]


def test_a_scale_label_and_its_none_cell_are_one_note():
    sheet = Sheet(width=1000, height=700)
    sheet.label("SCALE:", 700, 650, 730, 657)
    sheet.label("NONE", 745, 650, 770, 657)
    assert read_title_block(sheet.dm).scale_notes == ["SCALE: NONE"]


# ---------------------------------------------------------------- frame ruler

FRAMES = list(range(90, -6, -5))  # 90, 85, ... -5


def test_ruler_fit_recovers_the_line_and_rejects_a_misread_label():
    sheet = Sheet()
    sheet.ruler(FRAMES, misread={90: "06"})  # OCR read 90 as 06
    fit = fit_frame_ruler(sheet.dm, 1)
    assert fit is not None
    assert (fit.labels, fit.used) == (len(FRAMES), len(FRAMES) - 1)
    assert fit.pt_per_frame == pytest.approx(8.7895, abs=1e-6) and fit.x_at_frame0 == pytest.approx(963.5, abs=1e-6)
    assert fit.max_residual_pt < 0.01
    assert len(fit.rejected) == 1
    bad = fit.rejected[0]
    assert bad["text"] == "06" and bad["position_says_frame"] == 90.0 and bad["confidence"] == 0.95
    assert bad["box"]["page"] == 1 and bad["word_id"].startswith("p1-w")


def test_ruler_ignores_other_rows_and_zone_numbers():
    sheet = Sheet()
    sheet.ruler(FRAMES)
    for i, x in enumerate(range(85, 1200, 149)):  # sheet zone numbers 1..8 across the top: a regular row, but not a ruler
        sheet.label(str(8 - i), x, 12, x + 8, 24)
    for text, x in (("12", 300), ("7", 410), ("250", 520)):  # stray numbers on the ruler's row
        sheet.label(text, x, 458, x + 7, 464.5)
    fit = fit_frame_ruler(sheet.dm, 1)
    assert fit.used == len(FRAMES) and fit.labels == len(FRAMES) + 3
    assert {r["text"] for r in fit.rejected} == {"12", "7", "250"}
    assert fit.pt_per_frame == pytest.approx(8.7895, abs=1e-6)


def test_ruler_needs_five_labels_that_agree():
    few = Sheet()
    few.ruler([90, 85, 80, 75])
    assert fit_frame_ruler(few.dm, 1) is None
    scattered = Sheet()
    for i, (text, x) in enumerate(zip(["12", "47", "5", "88", "23", "61"], [100, 130, 300, 310, 700, 905])):
        scattered.label(text, x, 458, x + 7, 464.5)
    assert fit_frame_ruler(scattered.dm, 1) is None
    assert fit_frame_ruler(Sheet().dm, 1) is None


def test_ruler_at_two_different_scales_is_ambiguous():
    sheet = Sheet()
    sheet.ruler(FRAMES)
    sheet.ruler(FRAMES, pt_per_frame=5.0, y=300)  # another view at another scale
    assert fit_frame_ruler(sheet.dm, 1) is None
    sheet.dm.words = [w for w in sheet.dm.words if w.box.y0 != 300]
    assert fit_frame_ruler(sheet.dm, 1).pt_per_frame == pytest.approx(8.7895, abs=1e-6)
    same = Sheet()
    same.ruler(FRAMES)
    same.ruler(FRAMES[:9], y=718)  # the same scale in another view is fine
    assert fit_frame_ruler(same.dm, 1).used == len(FRAMES)


def test_ruler_runs_the_other_way_and_uses_only_the_requested_page():
    sheet = Sheet(pages=2)
    sheet.ruler(range(-10, 60, 5), x_at_0=100.0, pt_per_frame=-6.0, y=100, page=2)  # frames grow toward the right
    assert fit_frame_ruler(sheet.dm, 1) is None
    fit = fit_frame_ruler(sheet.dm, 2)
    assert fit.pt_per_frame == pytest.approx(-6.0) and fit.x_at_frame0 == pytest.approx(100.0)


# ---------------------------------------------------------------- deck ladder

LEVELS_IN = [6 * 12, 10 * 12, 19 * 12, 28 * 12, 37 * 12, 45 * 12 + 6, 54 * 12, 65 * 12, 71 * 12 + 9, 78 * 12 + 6, 88 * 12 + 4]


def test_ladder_fit_uses_text_tops_without_the_pdf_and_rejects_a_misplaced_label():
    sheet = Sheet()
    sheet.ladder(LEVELS_IN, shift={72: 3.0})  # the 6'-0" label sits 3 pt off its level
    fit = fit_deck_ladder(sheet.dm, 1)
    assert fit is not None and (fit.labels, fit.used) == (11, 10)
    assert fit.in_per_pt == pytest.approx(2.7319, abs=1e-4) and fit.baseline_y_pt == pytest.approx(536.7, abs=1e-3)
    assert fit.max_residual_in < 0.01
    assert [r["name"] for r in fit.rejected] == ["6'-0\" ABL"]
    assert fit.rejected[0]["position_says_height_in"] == pytest.approx(72 - 3.0 * 2.7319, abs=0.1)
    assert all(l["position_from"] == "text_top" for l in fit.levels) and len(fit.levels) == 10
    assert {"name", "value_in", "y_pt", "line_id"} <= set(fit.levels[0])


def test_ladder_ignores_lines_that_are_not_heights_above_baseline():
    sheet = Sheet()
    sheet.ladder(LEVELS_IN[:5])
    sheet.label("12'-6\" DWL", 984, 473, 1017, 481)  # a waterline, not an ABL level
    sheet.label("199'-6\"", 998, 667, 1032, 679)
    sheet.label("45'-6\" ABL AND 30'-0\" ABL", 700, 100, 900, 108)  # two lengths: ambiguous, no value
    sheet.label("DECK ABL", 700, 200, 760, 208)
    fit = fit_deck_ladder(sheet.dm, 1)
    assert fit.labels == 5 and fit.used == 5
    assert fit_deck_ladder(sheet.dm, 2) is None
    two = Sheet()
    two.ladder(LEVELS_IN[:2])
    assert fit_deck_ladder(two.dm, 1) is None  # three labels at least


def test_ladder_accepts_a_period_style_abl_and_metric_heights():
    sheet = Sheet()
    for i, (text, h_in) in enumerate([("10'-0\" A.B.L.", 120), ("20'-0\" A.B.L", 240), ("30'-0\" ABL", 360), ("3.048 m ABL", 120)]):
        y = 500 - h_in / 2.7319
        sheet.label(text, 1058 + (60 if i == 3 else 0), y, 1090, y + 7)
    fit = fit_deck_ladder(sheet.dm, 1)
    assert fit.labels == 4 and fit.used == 3  # the metric label repeats a height already taken; one of the two is dropped
    assert fit.in_per_pt == pytest.approx(2.7319, abs=1e-3)


def test_ladder_snaps_to_the_leader_stroke_when_the_pdf_is_given():
    # A rotated sheet, like the RCRV: leaders are drawn in the unrotated frame and read back in the displayed one.
    levels = LEVELS_IN[1:6]
    baseline, scale = 536.7, 2.7319
    sheet = Sheet()
    ys = {h: baseline - h / scale for h in levels}

    def unrotated(x, y):  # the page is 792 x 1224 before its 90 degree turn: displayed (X, Y) is unrotated (Y, 1224 - X)
        return pymupdf.Point(y, 1224 - x)

    def draw(page):
        for y in ys.values():
            page.draw_line(unrotated(1033.3, y), unrotated(1055.2, y), width=0.5)
        page.draw_line(unrotated(1060, 100), unrotated(1063, 100), width=0.5)  # a glyph stroke, too short for a leader
    data = pdf_bytes(draw, 792, 1224, rotation=90)
    for h in levels:
        y = ys[h] + 0.4  # the text's top edge sits a little below its leader
        feet, rest = divmod(h, 12)
        sheet.label(f"{int(feet)}'-{int(rest)}\" ABL", 1058, y, 1090, y + 7.5)
    fit = fit_deck_ladder(sheet.dm, 1, data)
    assert fit.used == len(levels) and {l["position_from"] for l in fit.levels} == {"leader"}
    assert fit.baseline_y_pt == pytest.approx(baseline, abs=0.01) and fit.in_per_pt == pytest.approx(scale, abs=1e-4)
    assert sorted(l["y_pt"] for l in fit.levels) == pytest.approx(sorted(ys.values()), abs=0.01)
    plain = fit_deck_ladder(sheet.dm, 1)
    assert {l["position_from"] for l in plain.levels} == {"text_top"} and plain.baseline_y_pt == pytest.approx(baseline + 0.4, abs=0.01)


# ---------------------------------------------------------------- calibration of a page

MM_PER_PT_TRUE = 2.7319 * 25.4


def calibrated_sheet(note: str | None = None) -> Sheet:
    sheet = Sheet()
    sheet.ruler(FRAMES)
    sheet.ladder(LEVELS_IN)
    if note:
        sheet.label(note, 540, 560, 640, 570)
    return sheet


def test_calibration_from_both_methods_with_a_stated_frame_spacing():
    cal = calibrate_page(calibrated_sheet("1/8\"=1'-0\"").dm, 1, stated_frame_spacing_mm=609.6)
    assert cal.scale_measured == "1:196.7" and cal.real_mm_per_pt == pytest.approx(MM_PER_PT_TRUE, rel=1e-6)
    assert cal.implied_frame_spacing_mm == pytest.approx(8.7895 * MM_PER_PT_TRUE, rel=1e-6)  # about 609.9 mm
    assert cal.methods_agree is True and cal.stated_frame_spacing_mm == 609.6
    assert cal.scale_noted == ["1/8\"=1'-0\""] and cal.noted_matches is False
    assert cal.ruler.used == len(FRAMES) and cal.ladder.used == len(LEVELS_IN)
    assert cal.certificate == ("Sheet scale measured 1:196.7 from 11 deck-height labels; the note says 1:96, "
                               "so the note is not used. Frame ruler and deck heights agree: implied frame spacing 610 mm (24.01 in).")


def test_a_note_that_matches_the_measured_scale_is_reported_as_agreeing():
    cal = calibrate_page(calibrated_sheet("SCALE 1:200").dm, 1)
    assert cal.noted_matches is True and "the note says 1:200 and agrees" in cal.certificate
    assert cal.methods_agree is None and cal.implied_frame_spacing_mm is not None
    assert "no frame spacing was stated" in cal.certificate
    far = calibrate_page(calibrated_sheet("1:220").dm, 1)  # 12% off
    assert far.noted_matches is False


def test_methods_that_disagree_give_no_scale():
    cal = calibrate_page(calibrated_sheet().dm, 1, stated_frame_spacing_mm=600.0)  # 1.6% off the implied spacing
    assert cal.methods_agree is False and cal.real_mm_per_pt is None and cal.scale_measured == ""
    assert cal.noted_matches is None and "disagree" in cal.certificate and "no scale is reported" in cal.certificate
    assert cal.implied_frame_spacing_mm == pytest.approx(8.7895 * MM_PER_PT_TRUE)


def test_frames_that_grow_toward_the_right_give_the_same_positive_scale():
    sheet = Sheet()
    sheet.ruler(range(-10, 60, 5), x_at_0=100.0, pt_per_frame=-8.7895)  # frame numbers increase left to right
    sheet.ladder(LEVELS_IN)
    cal = calibrate_page(sheet.dm, 1, stated_frame_spacing_mm=609.6)
    assert cal.ruler.pt_per_frame < 0  # the ruler keeps the direction
    assert cal.scale_measured == "1:196.7" and cal.real_mm_per_pt > 0
    assert cal.implied_frame_spacing_mm == pytest.approx(8.7895 * MM_PER_PT_TRUE, rel=1e-6) and cal.methods_agree is True
    assert "-" not in cal.scale_measured and "1:-" not in cal.certificate and "disagree" not in cal.certificate
    ruler_only = Sheet()
    ruler_only.ruler(range(-10, 60, 5), x_at_0=100.0, pt_per_frame=-8.7895)
    alone = calibrate_page(ruler_only.dm, 1, stated_frame_spacing_mm=609.6)
    assert alone.scale_measured == f"1:{609.6 / 8.7895 / (25.4 / 72):.1f}" and alone.real_mm_per_pt > 0
    assert "8.79 points per frame" in calibrate_page(ruler_only.dm, 1).certificate


def test_ladder_alone_and_ruler_alone():
    sheet = Sheet()
    sheet.ladder(LEVELS_IN)
    ladder_only = calibrate_page(sheet.dm, 1)
    assert ladder_only.scale_measured == "1:196.7" and ladder_only.implied_frame_spacing_mm is None
    assert ladder_only.methods_agree is None and ladder_only.ruler is None and "11 deck-height labels" in ladder_only.certificate

    ruler = Sheet()
    ruler.ruler(FRAMES)
    with_spacing = calibrate_page(ruler.dm, 1, stated_frame_spacing_mm=609.6)
    assert with_spacing.real_mm_per_pt == pytest.approx(609.6 / 8.7895)
    assert with_spacing.scale_measured == f"1:{609.6 / 8.7895 / (25.4 / 72):.1f}"
    assert with_spacing.methods_agree is None and "frame labels at the stated frame spacing" in with_spacing.certificate
    without = calibrate_page(ruler.dm, 1)
    assert without.real_mm_per_pt is None and without.scale_measured == "" and "can't be measured" in without.certificate


def test_nothing_to_measure():
    cal = calibrate_page(Sheet().dm, 1, stated_frame_spacing_mm=609.6)
    assert cal.ruler is None and cal.ladder is None and cal.real_mm_per_pt is None
    assert cal.scale_measured == "" and cal.certificate.startswith("No scale could be measured")


def test_a_pages_notes_come_from_that_page_else_from_the_title_block():
    sheet = Sheet(pages=2)
    sheet.label("1:50", 100, 100, 130, 108, page=1)
    sheet.ladder(LEVELS_IN, page=2)
    sheet.dm.title_block.scale_notes = ["1:100"]
    assert calibrate_page(sheet.dm, 2).scale_noted == ["1:100"]
    assert calibrate_page(sheet.dm, 1).scale_noted == ["1:50"]


# ---------------------------------------------------------------- the real drawing

@pytest.fixture(scope="module")
def rcrv(tmp_path_factory):
    data = RCRV.read_bytes()
    dm = build_document_map(data, RCRV.name, cache_dir=tmp_path_factory.mktemp("rcrv-cache"), pages=[4, 6])
    return data, dm


@pytest.mark.slow
@pytest.mark.skipif(not RCRV.exists(), reason="the RCRV general arrangement is not on this machine")
def test_real_general_arrangement(rcrv):
    data, dm = rcrv
    assert [p.kind for p in dm.pages] == ["vector_strokes"] * 12 and all(p.rotation == 90 for p in dm.pages)
    assert [p.ocr_used for p in dm.pages] == [n in (4, 6) for n in range(1, 13)]
    assert dm.status == "partly read" and "1-3, 5, 7-12" in dm.status_reason  # ten pages were not asked for

    ruler = fit_frame_ruler(dm, 4)
    assert ruler is not None and ruler.used >= 17 and ruler.used >= 0.9 * ruler.labels
    assert ruler.pt_per_frame == pytest.approx(8.79, abs=0.05) and ruler.x_at_frame0 == pytest.approx(963.5, abs=1.0)
    assert ruler.max_residual_pt <= 1.5
    # OCR can turn "90" into "06"; whatever it read, a label on the wrong frame must not be one of the inliers
    for r in ruler.rejected:
        if r["text"].lstrip("-").isdigit():
            assert r["position_says_frame"] != int(r["text"])

    ladder = fit_deck_ladder(dm, 6, data)
    assert ladder is not None and ladder.used >= 9
    assert ladder.in_per_pt * 72 == pytest.approx(196.7, abs=1.0) and ladder.baseline_y_pt == pytest.approx(536.7, abs=0.5)
    assert all(l["position_from"] == "leader" for l in ladder.levels)

    cal = calibrate_page(dm, 6, data, stated_frame_spacing_mm=24 * 25.4)
    assert float(cal.scale_measured.split(":")[1]) == pytest.approx(196.7, abs=1.0)
    assert cal.noted_matches is False  # the sheet says 1/8" = 1'-0" (1:96)
    assert cal.methods_agree is True and "the note is not used" in cal.certificate
    assert calibrate_page(dm, 4, data, stated_frame_spacing_mm=24 * 25.4).ruler is not None

    spacing_in = ruler.pt_per_frame * ladder.in_per_pt
    assert spacing_in == pytest.approx(24.0, abs=0.2)

    tb = dm.title_block
    assert tb.drawing_no == "6096-070-001" and tb.hulls == ["6096", "6097", "6098"]
    assert tb.sheet_size == "D" and tb.revision == "J"
    assert tb.title.startswith("GENERAL ARRANGEMENT")
    assert '1/8"=1\'-0"' in tb.scale_notes and "SCALE: NONE" in tb.scale_notes
    assert tb.evidence and all(dm.line(e) is not None for e in tb.evidence)
