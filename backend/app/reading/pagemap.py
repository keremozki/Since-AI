"""Page maps: every word and line of a document with its position on the page.

Words come from the PDF text layer when there is one. Pages drawn as strokes or scanned are read with OCR in
overlapping tiles. OCR is a reading, not a truth: confidence is kept, and nothing here decides a value.
Coordinates are PDF points in the page's displayed (rotated) frame; element ids are "p{page}-l{n}" and "p{page}-w{n}".
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pymupdf

from ..models import Box
from .model import DocumentMap, Line, PageInfo, Word

log = logging.getLogger(__name__)

CACHE_VERSION = 2  # bump when the map's content changes for the same file and parameters

# Page kind thresholds. A text layer with fewer words than this is treated as no usable text layer.
MIN_TEXT_WORDS = 10
MIN_STROKES = 30  # drawn paths that make a page with no text a drawing rather than a blank
STROKES_PER_WORD = 200  # more paths than this per text word: part of the lettering is probably drawn
RASTER_COVER = 0.5  # share of the page covered by images that makes it a scan
SOME_IMAGE_COVER = 0.1
BIG_IMAGE_SHARE = 0.005  # images smaller than this share of the page are hatch patterns, not scans

# OCR tiling. RapidOCR shrinks any input whose long side exceeds 2000 px, so tiles stay at or under that.
TILE_PX = 2400
OVERLAP_PX = 300
EDGE_PX = 4  # a detected box this close to a tile seam is probably cut by it
REPAIR_PAD_PX = 80
MIN_ROW = 5  # short numbers on one line that count as a ruler or scale worth reading again
ROW_OVERLAP_PX = 6  # sideways overlap of two boxes on one line that means one split line, not two neighbors
ROW_OVERLAP_SHARE = 0.15
MAX_ROW_REREADS = 3
STRIP_PX = 250  # height of the strip; the detector enlarges it, so thinner is slower, not better
STRIP_MARGIN_PX = 500
_GLYPH_LABELS = {"REV", "REV.", "REV:", "SIZE", "SIZE:"}
_SHORT_NUMBER = re.compile(r"-?\d{1,3}")
OCR_USE_CLS = False  # the 180-degree classifier turns drawing numbers such as "90" into "06"
TEXT_SCORE = 0.5  # detections read with less confidence than this are dropped, unless a turned reading is sure
TURNED_SCORE = 0.8  # confidence a reading of rotated or upside-down text must reach
MAX_TURNED_PER_REGION = 60

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}

_engine = None
_engine_lock = threading.Lock()  # guards creating the engine
_run_lock = threading.Lock()  # one OCR call at a time; the engine already uses every core


def _ocr_engine():
    """One RapidOCR instance per process, created on first use because loading the models takes a second or two."""
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR
            _engine = RapidOCR(max_side_len=3000)
        return _engine


# ---------------------------------------------------------------- public entry point

def build_document_map(data: bytes, filename: str, cache_dir: Path | None = None, ocr: bool = True,
                       dpi: int = 400, pages: list[int] | None = None) -> DocumentMap:
    """Read a PDF or image into a DocumentMap. `pages` (counted from 1) limits OCR only; every page is classified.

    The status is "partly read" when a page that needs OCR was skipped or failed, so a quiet gap never looks complete.
    """
    sha = hashlib.sha256(data).hexdigest()
    cache_file = _cache_path(cache_dir, sha, ocr, dpi, pages)
    if cache_file is not None and cache_file.exists():
        try:
            dm = DocumentMap.model_validate_json(cache_file.read_text(encoding="utf-8"))
            dm.file = filename
            _fill_title_block(dm)  # the title block is cheap and always read with the current rules
            return dm
        except Exception:  # a damaged cache file is rebuilt, not trusted
            log.warning("ignoring unreadable cache file %s", cache_file)

    dm = DocumentMap(file=filename, sha256=sha)
    suffix = Path(filename).suffix.lower()
    try:
        if data[:5] == b"%PDF-" or suffix == ".pdf":
            _read_pdf(dm, data, ocr, dpi, pages)
        elif suffix in _IMAGE_SUFFIXES or _looks_like_image(data):
            _read_image(dm, data, ocr, pages)
        else:
            _fail(dm, "the file is not a PDF or an image")
    except Exception as exc:  # corrupt files raise anything from the PDF library
        log.exception("could not read %s", filename)
        _fail(dm, f"the file could not be opened ({type(exc).__name__}: {exc})")

    if dm.status != "couldn't be read":
        _fill_title_block(dm)
        if cache_file is not None:
            _write_cache(cache_file, dm)
    return dm


def _fill_title_block(dm: DocumentMap) -> None:
    try:
        from .titleblock import read_title_block
        dm.title_block = read_title_block(dm)
    except Exception:  # the title block is a convenience; the map stands without it
        log.exception("title block failed for %s", dm.file)


def _fail(dm: DocumentMap, reason: str) -> None:
    dm.status, dm.status_reason = "couldn't be read", reason


def _cache_path(cache_dir: Path | None, sha: str, ocr: bool, dpi: int, pages: list[int] | None) -> Path | None:
    if cache_dir is None:
        return None
    selection = "all" if pages is None else "-".join(str(p) for p in sorted(set(pages)))
    return Path(cache_dir) / f"{sha}-v{CACHE_VERSION}-ocr{int(ocr)}-dpi{dpi}-p{selection}.json"


def _write_cache(path: Path, dm: DocumentMap) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(dm.model_dump_json(), encoding="utf-8")
        tmp.replace(path)  # a reader never sees a half-written file
    except OSError:
        log.warning("could not write cache file %s", path)


def _looks_like_image(data: bytes) -> bool:
    return data[:8] == b"\x89PNG\r\n\x1a\n" or data[:3] == b"\xff\xd8\xff" or data[:2] == b"BM" \
        or data[:4] in (b"II*\x00", b"MM\x00*") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


# ---------------------------------------------------------------- PDF

@dataclass
class _Raw:
    """A line before ids are assigned. Boxes are (x0, y0, x1, y1) in displayed points."""
    text: str
    box: tuple[float, float, float, float]
    source: str
    confidence: float | None = None
    words: list[tuple[str, tuple[float, float, float, float]]] = field(default_factory=list)


def _read_pdf(dm: DocumentMap, data: bytes, ocr: bool, dpi: int, pages: list[int] | None) -> None:
    doc = pymupdf.open(stream=data, filetype="pdf")
    if doc.needs_pass:
        return _fail(dm, "the PDF is password protected")
    if doc.page_count == 0:
        return _fail(dm, "the PDF has no pages")

    wanted = None if pages is None else set(pages)
    skipped: list[int] = []  # no text layer and no OCR
    problems: list[str] = []
    for number in range(1, doc.page_count + 1):
        try:
            page = doc[number - 1]
            raws, info = _classify_and_read_text(page, number)
            if info.kind in ("vector_strokes", "raster"):
                if ocr and (wanted is None or number in wanted):
                    try:
                        raws += _drop_text_layer_duplicates(_ocr_page(page, dpi), raws)
                        info.ocr_used = True
                    except Exception as exc:
                        log.exception("OCR failed on page %d", number)
                        problems.append(f"page {number} OCR failed ({type(exc).__name__}: {exc})")
                else:
                    skipped.append(number)
        except Exception as exc:
            log.exception("page %d could not be read", number)
            problems.append(f"page {number} could not be read ({type(exc).__name__}: {exc})")
            continue
        dm.pages.append(info)
        _add_lines(dm, number, raws)

    if not dm.pages:
        return _fail(dm, "no page could be read: " + "; ".join(problems))
    reasons = list(problems)
    if skipped:
        why = "OCR was off" if not ocr else "OCR was not requested for them"
        reasons.insert(0, f"no text layer on page(s) {_ranges(skipped)} of {doc.page_count} and {why}")
    if reasons:
        dm.status, dm.status_reason = "partly read", "; ".join(reasons)


def _ranges(numbers: list[int]) -> str:
    """[1, 2, 3, 5] as "1-3, 5"."""
    out, run = [], []
    for n in sorted(numbers):
        if run and n == run[-1] + 1:
            run.append(n)
            continue
        if run:
            out.append(run)
        run = [n]
    if run:
        out.append(run)
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 2 else ", ".join(map(str, r)) for r in out)


def _classify_and_read_text(page: pymupdf.Page, number: int) -> tuple[list[_Raw], PageInfo]:
    rect = page.rect
    raws = _text_layer_lines(page)
    word_count = sum(len(r.words) for r in raws)
    paths, cover = _paths_and_image_cover(page)
    info = PageInfo(page=number, width_pt=round(rect.width, 2), height_pt=round(rect.height, 2),
                    rotation=page.rotation, kind=classify_page(word_count, paths, cover),
                    text_words=word_count, vector_paths=paths, image_cover=round(cover, 3))
    return raws, info


def classify_page(words: int, paths: int, image_cover: float) -> str:
    """vector_text, vector_strokes, raster, mixed or empty, from the counts alone."""
    if words < MIN_TEXT_WORDS:
        if image_cover >= RASTER_COVER:
            return "raster"
        if paths >= MIN_STROKES:
            return "vector_strokes"
        if image_cover >= SOME_IMAGE_COVER:
            return "raster"
        return "vector_text" if words else "empty"
    if image_cover >= RASTER_COVER or paths > STROKES_PER_WORD * words:
        return "mixed"
    return "vector_text"


def _paths_and_image_cover(page: pymupdf.Page) -> tuple[int, float]:
    """Drawn path count, and the share of the page covered by images big enough to be a scan."""
    log_items = page.get_bboxlog()
    paths = sum(1 for kind, _ in log_items if kind in ("stroke-path", "fill-path"))
    unrotated = page.rect * page.derotation_matrix
    area = max(unrotated.width * unrotated.height, 1.0)
    grid = np.zeros((100, 100), bool)
    for kind, bbox in log_items:
        if kind not in ("fill-image", "fill-imgmask"):
            continue
        r = pymupdf.Rect(bbox) & unrotated
        if r.is_empty or r.width * r.height < BIG_IMAGE_SHARE * area:
            continue
        i0, i1 = int((r.x0 - unrotated.x0) / unrotated.width * 100), math.ceil((r.x1 - unrotated.x0) / unrotated.width * 100)
        j0, j1 = int((r.y0 - unrotated.y0) / unrotated.height * 100), math.ceil((r.y1 - unrotated.y0) / unrotated.height * 100)
        grid[j0:j1, i0:i1] = True
    return paths, float(grid.mean())


def _text_layer_lines(page: pymupdf.Page) -> list[_Raw]:
    """Text-layer lines with word boxes moved into the displayed frame (PyMuPDF reports the unrotated one)."""
    rotation = page.rotation_matrix
    groups: dict[tuple[int, int], list[tuple[str, tuple[float, float, float, float]]]] = {}
    for x0, y0, x1, y1, text, block, line, _ in page.get_text("words"):
        text = text.strip()
        if not text:
            continue
        r = pymupdf.Rect(x0, y0, x1, y1) * rotation
        r.normalize()
        groups.setdefault((block, line), []).append((text, _round_box((r.x0, r.y0, r.x1, r.y1))))
    out = []
    for group in groups.values():
        for words in _split_at_wide_gaps(group):
            box = (min(w[1][0] for w in words), min(w[1][1] for w in words),
                   max(w[1][2] for w in words), max(w[1][3] for w in words))
            out.append(_Raw(" ".join(w[0] for w in words), box, "text_layer", None, words))
    return out


_Word = tuple[str, tuple[float, float, float, float]]


def _split_at_wide_gaps(words: list[_Word]) -> list[list[_Word]]:
    """Cut a text-layer line where the gap is wider than two line heights: separate cells of a title block or table.

    PyMuPDF can join cells that share a baseline into one line, which would hide a label such as "REV" inside it.
    """
    if len(words) < 2:
        return [words]
    x_span = max(w[1][2] for w in words) - min(w[1][0] for w in words)
    y_span = max(w[1][3] for w in words) - min(w[1][1] for w in words)
    horizontal = x_span >= y_span
    height = max(min((w[1][3] - w[1][1]) if horizontal else (w[1][2] - w[1][0]) for w in words), 1.0)
    pieces = [[words[0]]]
    for before, after in zip(words, words[1:]):
        gap = (after[1][0] - before[1][2]) if horizontal else (after[1][1] - before[1][3])
        if gap > 2.0 * height:
            pieces.append([])
        pieces[-1].append(after)
    return pieces


def _round_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return tuple(round(v, 2) for v in box)  # type: ignore[return-value]


def _add_lines(dm: DocumentMap, page: int, raws: list[_Raw]) -> None:
    """Order lines top to bottom, left to right, and give lines and words their ids."""
    word_n = line_n = 0
    for raw in sorted(raws, key=lambda r: (round(r.box[1], 1), r.box[0])):
        line_n += 1
        ids = []
        for text, box in raw.words:
            word_n += 1
            ids.append(f"p{page}-w{word_n}")
            dm.words.append(Word(id=ids[-1], page=page, text=text, box=Box(page=page, x0=box[0], y0=box[1], x1=box[2], y1=box[3]),
                                 source=raw.source, confidence=raw.confidence))
        dm.lines.append(Line(id=f"p{page}-l{line_n}", page=page, text=raw.text,
                             box=Box(page=page, x0=raw.box[0], y0=raw.box[1], x1=raw.box[2], y1=raw.box[3]),
                             source=raw.source, word_ids=ids, confidence=raw.confidence))


# ---------------------------------------------------------------- images

def _read_image(dm: DocumentMap, data: bytes, ocr: bool, pages: list[int] | None) -> None:
    from PIL import Image

    image = Image.open(io.BytesIO(data))
    image.load()
    dpi = image.info.get("dpi", (72, 72))[0] or 72
    if not 10 <= dpi <= 1200:
        dpi = 72
    gray = np.asarray(image.convert("L"))
    height, width = gray.shape
    scale = 72.0 / dpi
    info = PageInfo(page=1, width_pt=round(width * scale, 2), height_pt=round(height * scale, 2), kind="raster",
                    image_cover=1.0)
    raws: list[_Raw] = []
    if ocr and (pages is None or 1 in pages):
        def render(x0: int, y0: int, x1: int, y1: int) -> tuple[np.ndarray, int, int]:
            return gray[y0:y1, x0:x1], x0, y0
        try:
            raws = _hits_to_raws(_ocr_surface(render, width, height, dpi / 72.0))
            info.ocr_used = True
        except Exception as exc:
            log.exception("OCR failed on the image")
            dm.pages.append(info)
            dm.status, dm.status_reason = "partly read", f"OCR failed ({type(exc).__name__}: {exc})"
            return
    dm.pages.append(info)
    _add_lines(dm, 1, raws)
    if not info.ocr_used:
        dm.status = "partly read"
        dm.status_reason = "the image has no text layer and " + ("OCR was off" if not ocr else "OCR was not requested for it")


# ---------------------------------------------------------------- OCR

@dataclass
class _Hit:
    """One OCR box in surface pixels, with the seam it touches (None if it is whole)."""
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    conf: float
    seam_x: float | None = None
    seam_y: float | None = None


def _ocr_page(page: pymupdf.Page, dpi: int) -> list[_Raw]:
    zoom = dpi / 72.0
    rect = page.rect
    matrix = pymupdf.Matrix(zoom, zoom)

    def render(x0: int, y0: int, x1: int, y1: int) -> tuple[np.ndarray, int, int]:
        clip = pymupdf.Rect(x0 / zoom, y0 / zoom, x1 / zoom, y1 / zoom) & rect
        pix = page.get_pixmap(matrix=matrix, clip=clip, colorspace=pymupdf.csGRAY, alpha=False)
        return np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width), pix.x, pix.y

    started = time.time()
    hits = _ocr_surface(render, math.ceil(rect.width * zoom), math.ceil(rect.height * zoom), zoom)
    log.info("OCR page %d: %d lines in %.1f s", page.number + 1, len(hits), time.time() - started)
    return _hits_to_raws(hits)


def _tiles(length: int, tile: int = TILE_PX, overlap: int = OVERLAP_PX) -> list[tuple[int, int]]:
    """Spans that cover 0..length, each at most `tile` long, neighbors sharing `overlap`."""
    if length <= tile:
        return [(0, length)]
    count = math.ceil((length - overlap) / (tile - overlap))
    size = (length + (count - 1) * overlap) / count
    spans = [(round(i * (size - overlap)), round(i * (size - overlap) + size)) for i in range(count)]
    return [(a, min(b, length)) for a, b in spans[:-1]] + [(spans[-1][0], length)]


def _ocr_surface(render, width: int, height: int, zoom: float) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """OCR a surface of width x height pixels in tiles; returns (text, confidence, box in points).

    A box that touches an interior tile seam may be a line cut in half, and a cut line can read as a shorter
    value. Such boxes are dropped when another tile saw the same text whole, and otherwise read again from a
    region centered on the seam. Anything still cut is dropped: no reading beats a truncated one.
    """
    whole: list[_Hit] = []
    cut: list[_Hit] = []
    for ty0, ty1 in _tiles(height):
        for tx0, tx1 in _tiles(width):
            for hit in _read_region(render, tx0, ty0, tx1, ty1, width, height):
                (cut if hit.seam_x is not None or hit.seam_y is not None else whole).append(hit)
    kept = _merge(whole)
    index = _Grid(kept)
    repaired: list[_Hit] = []
    for hit in sorted(cut, key=lambda h: (h.y0, h.x0)):
        if any(_covered(hit, k) for k in index.near(hit)):
            continue  # another tile saw it whole, or an earlier repair did
        for fixed in _read_region(render, *_seam_region(hit, width, height), width, height):
            if fixed.seam_x is None and fixed.seam_y is None and _overlap_share(fixed, hit) >= 0.3:
                repaired.append(fixed)
                index.add(fixed)
    kept = _merge(kept + repaired)
    kept = _merge(kept + _reread_number_rows(render, kept, width, height))
    kept = _merge(kept + _read_glyph_cells(render, kept, width, height))
    kept = _fuse_row_overlaps(render, kept, width, height)
    return [(h.text, h.conf, _round_box((h.x0 / zoom, h.y0 / zoom, h.x1 / zoom, h.y1 / zoom))) for h in kept]


def _reread_number_rows(render, hits: list[_Hit], width: int, height: int) -> list[_Hit]:
    """Read rows of small numbers again as thin strips.

    A frame ruler or dimension scale is a row of short numbers, and the tile pass tends to miss some of them
    among nearby lines. A thin strip is enlarged by the detector, which finds the rest. Only whole boxes count.
    """
    found: list[_Hit] = []
    for row in sorted(_number_rows(hits), key=len, reverse=True)[:MAX_ROW_REREADS]:
        middle = (min(h.y0 for h in row) + max(h.y1 for h in row)) / 2
        y0, y1 = max(math.floor(middle - STRIP_PX / 2), 0), min(math.ceil(middle + STRIP_PX / 2), height)
        left = max(math.floor(min(h.x0 for h in row) - STRIP_MARGIN_PX), 0)
        right = min(math.ceil(max(h.x1 for h in row) + STRIP_MARGIN_PX), width)
        for x0, x1 in _tiles(right - left):
            found += [h for h in _read_region(render, left + x0, y0, left + x1, y1, width, height)
                      if h.seam_x is None and h.seam_y is None]
    return found


def _same_row_overlap(a: _Hit, b: _Hit) -> bool:
    """Two upright boxes on one line that overlap sideways by more than the detector's usual padding."""
    ha, hb = a.y1 - a.y0, b.y1 - b.y0
    if ha > 1.5 * (a.x1 - a.x0) or hb > 1.5 * (b.x1 - b.x0):
        return False  # rotated text
    if min(a.y1, b.y1) - max(a.y0, b.y0) < 0.6 * min(ha, hb):
        return False
    overlap = min(a.x1, b.x1) - max(a.x0, b.x0)
    return overlap >= max(ROW_OVERLAP_PX, ROW_OVERLAP_SHARE * min(a.x1 - a.x0, b.x1 - b.x0))


def _fuse_row_overlaps(render, hits: list[_Hit], width: int, height: int) -> list[_Hit]:
    """Read one line again when the detector split it into boxes that overlap.

    "15 February 2" and "2027" overlapping on the "2" would join as "15 February 2 2027". The union box is read
    as a single line instead. If that reading comes back empty the boxes stay as they were.
    """
    index = _Grid(hits)
    parent = list(range(len(hits)))
    position = {id(h): i for i, h in enumerate(hits)}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, hit in enumerate(hits):
        for other in index.near(hit):
            j = position[id(other)]
            if j > i and _same_row_overlap(hit, other):
                parent[root(j)] = root(i)
    groups: dict[int, list[_Hit]] = {}
    for i, hit in enumerate(hits):
        groups.setdefault(root(i), []).append(hit)
    out: list[_Hit] = []
    for group in groups.values():
        if len(group) == 1:
            out += group
            continue
        x0, y0 = max(math.floor(min(h.x0 for h in group)) - 2, 0), max(math.floor(min(h.y0 for h in group)) - 2, 0)
        x1, y1 = min(math.ceil(max(h.x1 for h in group)) + 2, width), min(math.ceil(max(h.y1 for h in group)) + 2, height)
        array, _, _ = render(x0, y0, x1, y1)
        with _run_lock:
            result, _ = _ocr_engine()(array, use_det=False, use_cls=False, use_rec=True)
        text = str(result[0][0]).strip() if result else ""
        if not text:
            out += group
            continue
        out.append(_Hit(min(h.x0 for h in group), min(h.y0 for h in group), max(h.x1 for h in group),
                        max(h.y1 for h in group), text, min(float(result[0][1]), min(h.conf for h in group))))
    return sorted(out, key=lambda h: (h.y0, h.x0))


def _read_glyph_cells(render, hits: list[_Hit], width: int, height: int) -> list[_Hit]:
    """Read the one big letter under a title block label (SIZE, REV) that text detection tends to skip.

    One glyph is easy to misread with high confidence (a drawn "J" can read as "U"), so the cell is read four ways,
    tight and loose, at two enlargements, and the letter is kept only if every reading agrees once the cell's
    border strokes, which the loose reading picks up, are ignored.
    """
    found: list[_Hit] = []
    for label in hits:
        if _squash(label.text) not in _GLYPH_LABELS:
            continue
        h = label.y1 - label.y0
        below = (label.x0 - 1.5 * h, label.y1, label.x1 + 1.5 * h, label.y1 + 3.5 * h)
        if any(below[0] <= (o.x0 + o.x1) / 2 <= below[2] and below[1] <= (o.y0 + o.y1) / 2 <= below[3]
               for o in hits if o is not label):
            continue  # something was read there already
        readings: list[tuple[str, float]] = []
        for dx in (0.3, 0.9):
            x0, x1 = max(math.floor(label.x0 - dx * h), 0), min(math.ceil(label.x1 + dx * h), width)
            y0, y1 = math.floor(label.y1 + 0.15 * h), min(math.ceil(label.y1 + 2.5 * h), height)
            if x1 <= x0 or y1 <= y0:
                break
            array, _, _ = render(x0, y0, x1, y1)
            for factor in (1, 2):
                big = array if factor == 1 else np.kron(array, np.ones((factor, factor), np.uint8))
                with _run_lock:
                    result, _ = _ocr_engine()(big, use_det=False, use_cls=False, use_rec=True)
                text = re.sub(r"[\s\[\](){}|!/\\_:;.,'\"]", "", str(result[0][0])) if result else ""  # cell borders
                readings.append((text, float(result[0][1])) if result else ("", 0.0))
        texts = {t for t, _ in readings}
        if len(readings) == 4 and len(texts) == 1 and re.fullmatch(r"[A-Z0-9]{1,2}", next(iter(texts))):
            x0, x1 = label.x0 - 0.3 * h, label.x1 + 0.3 * h
            found.append(_Hit(x0, label.y1 + 0.15 * h, x1, label.y1 + 2.5 * h, texts.pop(), min(c for _, c in readings)))
    return found


def _number_rows(hits: list[_Hit]) -> list[list[_Hit]]:
    """Groups of at least MIN_ROW short numbers sharing a line, with a gap where one is probably missing.

    A row with no gap is complete as far as anyone can tell, and reading it again would only cost time.
    """
    numbers = sorted((h for h in hits if _SHORT_NUMBER.fullmatch(h.text)), key=lambda h: (h.y0 + h.y1) / 2)
    rows: list[list[_Hit]] = []
    for hit in numbers:
        if rows and (hit.y0 + hit.y1) / 2 - (rows[-1][0].y0 + rows[-1][0].y1) / 2 <= 0.5 * (hit.y1 - hit.y0):
            rows[-1].append(hit)
        else:
            rows.append([hit])
    out = []
    for row in rows:
        if len(row) < MIN_ROW:
            continue
        row.sort(key=lambda h: h.x0)
        steps = np.diff([(h.x0 + h.x1) / 2 for h in row])
        if steps.max() >= 1.6 * np.median(steps):
            out.append(row)
    return out


def _seam_region(hit: _Hit, width: int, height: int) -> tuple[int, int, int, int]:
    """A region centered on the seam a box touches, wide enough to hold a whole line, and only as tall as the box."""
    half = TILE_PX // 2
    pad = REPAIR_PAD_PX
    x0, x1 = (hit.seam_x - half, hit.seam_x + half) if hit.seam_x is not None else (hit.x0 - pad, hit.x1 + pad)
    y0, y1 = (hit.seam_y - half, hit.seam_y + half) if hit.seam_y is not None else (hit.y0 - pad, hit.y1 + pad)
    return max(math.floor(x0), 0), max(math.floor(y0), 0), min(math.ceil(x1), width), min(math.ceil(y1), height)


def _read_region(render, x0: int, y0: int, x1: int, y1: int, width: int, height: int) -> list[_Hit]:
    """Run the OCR engine on one region and return its boxes in surface pixels, marking those cut by a seam."""
    array, ox, oy = render(x0, y0, x1, y1)
    if array.size == 0:
        return []
    engine = _ocr_engine()
    with _run_lock:  # text_score 0 keeps the weak readings so that turned text can get a second look below
        result, _ = engine(array, use_cls=OCR_USE_CLS, text_score=0.0, box_thresh=0.5, unclip_ratio=1.6)
    hits: list[_Hit] = []
    ah, aw = array.shape[:2]
    retries = 0
    for quad, text, conf in result or []:
        xs = [p[0] for p in quad]
        ys = [p[1] for p in quad]
        text, conf = str(text).strip(), float(conf)
        if conf < TEXT_SCORE or not text:
            retries += 1
            turned = None
            if retries <= MAX_TURNED_PER_REGION:
                turned = _read_turned(engine, array, min(xs), min(ys), max(xs), max(ys))
            if turned is None:
                continue
            text, conf = turned
        hit = _Hit(ox + min(xs), oy + min(ys), ox + max(xs), oy + max(ys), text, conf)
        if ox > 0 and min(xs) <= EDGE_PX:
            hit.seam_x = ox
        elif ox + aw < width and aw - max(xs) <= EDGE_PX:
            hit.seam_x = ox + aw
        if oy > 0 and min(ys) <= EDGE_PX:
            hit.seam_y = oy
        elif oy + ah < height and ah - max(ys) <= EDGE_PX:
            hit.seam_y = oy + ah
        hits.append(hit)
    return hits


def _read_turned(engine, array: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> tuple[str, float] | None:
    """Read a weak detection again as text turned a quarter or half turn; None unless one reading is sure.

    The detector turns tall boxes one way only, and the 180-degree classifier is off, so lettering that reads
    bottom to top or upside down comes back weak. Turning the crop each way and reading it settles it.
    """
    w, h = x1 - x0, y1 - y0
    if min(w, h) < 12 or max(w, h) < 24:
        return None  # a speck, not lettering
    crop = array[max(int(y0) - 2, 0):int(y1) + 3, max(int(x0) - 2, 0):int(x1) + 3]
    turns = (-1, 1) if h > 1.5 * w else (2,)
    best: tuple[str, float] | None = None
    for k in turns:
        with _run_lock:
            result, _ = engine(np.ascontiguousarray(np.rot90(crop, k)), use_det=False, use_cls=False, use_rec=True)
        text = str(result[0][0]).strip() if result else ""
        conf = float(result[0][1]) if result else 0.0
        if text and conf >= TURNED_SCORE and (best is None or conf > best[1]):
            best = (text, conf)
    return best


def _iou(a: _Hit, b: _Hit) -> float:
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a.x1 - a.x0) * (a.y1 - a.y0) + (b.x1 - b.x0) * (b.y1 - b.y0) - inter)


def _overlap_share(a: _Hit, b: _Hit) -> float:
    """How much of b's area a covers."""
    w = min(a.x1, b.x1) - max(a.x0, b.x0)
    h = min(a.y1, b.y1) - max(a.y0, b.y0)
    area = max((b.x1 - b.x0) * (b.y1 - b.y0), 1e-9)
    return (w * h) / area if w > 0 and h > 0 else 0.0


def _covered(cut: _Hit, kept: _Hit) -> bool:
    return _overlap_share(kept, cut) >= 0.5 or _iou(kept, cut) > 0.3


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text).upper()


class _Grid:
    """Boxes bucketed by center, so a duplicate check looks at neighbors instead of every box on the page."""

    CELL = 512

    def __init__(self, hits: list[_Hit] | None = None) -> None:
        self.cells: dict[tuple[int, int], list[_Hit]] = {}
        for hit in hits or []:
            self.add(hit)

    def _key(self, hit: _Hit) -> tuple[int, int]:
        return int((hit.x0 + hit.x1) / 2) // self.CELL, int((hit.y0 + hit.y1) / 2) // self.CELL

    def add(self, hit: _Hit) -> None:
        self.cells.setdefault(self._key(hit), []).append(hit)

    def near(self, hit: _Hit) -> list[_Hit]:
        cx, cy = self._key(hit)
        return [k for dx in (-1, 0, 1) for dy in (-1, 0, 1) for k in self.cells.get((cx + dx, cy + dy), [])]


def _merge(hits: list[_Hit]) -> list[_Hit]:
    """Drop duplicates from tile overlaps, keeping the more confident reading.

    The same text with IoU above 0.3 is a duplicate; different text at the same spot (IoU above 0.5) is two
    readings of one box, and only the more confident one is kept.
    """
    index = _Grid()
    kept: list[_Hit] = []
    for hit in sorted(hits, key=lambda h: -h.conf):
        for other in index.near(hit):
            iou = _iou(hit, other)
            if iou > 0.5 or (iou > 0.3 and _squash(hit.text) == _squash(other.text)):
                break
        else:
            kept.append(hit)
            index.add(hit)
    return sorted(kept, key=lambda h: (h.y0, h.x0))


def _hits_to_raws(hits: list[tuple[str, float, tuple[float, float, float, float]]]) -> list[_Raw]:
    return [_Raw(text, box, "ocr", round(conf, 4), _split_words(text, box)) for text, conf, box in hits]


def _split_words(text: str, box: tuple[float, float, float, float]) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Word boxes from a line: proportional to character position along a horizontal line.

    A tall line (rotated text) can't be split reliably because its reading direction is unknown, so each of its
    words gets the whole line box.
    """
    parts = text.split()
    x0, y0, x1, y1 = box
    if len(parts) <= 1 or (y1 - y0) > 1.5 * (x1 - x0):
        return [(p, box) for p in parts]
    joined = " ".join(parts)
    total, width = len(joined), x1 - x0
    words, start = [], 0
    for part in parts:
        words.append((part, _round_box((x0 + width * start / total, y0, x0 + width * (start + len(part)) / total, y1))))
        start += len(part) + 1
    return words


def _drop_text_layer_duplicates(ocr_lines: list[_Raw], text_lines: list[_Raw]) -> list[_Raw]:
    """On a page with a few text-layer words and drawn text, keep the text-layer reading of a line both found."""
    if not text_lines:
        return ocr_lines
    out = []
    for line in ocr_lines:
        a = _Hit(*line.box, line.text, 0.0)
        if not any(_squash(t.text) == _squash(line.text) and _iou(a, _Hit(*t.box, t.text, 0.0)) > 0.3 for t in text_lines):
            out.append(line)
    return out
