"""Data shapes for the reading pipeline. Builders produce them; consumers read them. No logic here.

Coordinates are PDF points in the page's displayed (rotated) frame: x to the right, y down, origin top left,
the same frame PyMuPDF uses for page.rect after rotation. Element ids are stable within one document:
"p{page}-l{n}" for lines and "p{page}-w{n}" for words, pages counted from 1.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..models import Box


class Word(BaseModel):
    id: str
    page: int
    text: str
    box: Box
    source: str  # "text_layer" or "ocr"
    confidence: float | None = None  # OCR confidence 0..1; None for a text layer


class Line(BaseModel):
    id: str
    page: int
    text: str
    box: Box
    source: str  # "text_layer" or "ocr"
    word_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None


class PageInfo(BaseModel):
    page: int
    width_pt: float
    height_pt: float
    rotation: int = 0
    # vector_text: real text layer; vector_strokes: drawn lines but no text layer (text must be OCR'd);
    # raster: mostly an image; mixed: text layer plus large images or strokes; empty: nothing found.
    kind: str
    text_words: int = 0
    vector_paths: int = 0
    image_cover: float = 0.0
    ocr_used: bool = False
    text_layer_checked: bool = False  # the text layer was compared with OCR of the rendered page
    text_layer_agrees: bool | None = None


class TitleBlock(BaseModel):
    drawing_no: str = ""
    revision: str = ""
    title: str = ""
    scale_notes: list[str] = Field(default_factory=list)  # as written, e.g. '1/8"=1\'-0"' or "1:100"
    sheet_size: str = ""  # as written, e.g. "D" or "A3"
    hulls: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)  # line ids


class DocumentMap(BaseModel):
    file: str
    sha256: str
    pages: list[PageInfo] = Field(default_factory=list)
    lines: list[Line] = Field(default_factory=list)
    words: list[Word] = Field(default_factory=list)
    title_block: TitleBlock = Field(default_factory=TitleBlock)
    status: str = "read"  # read, partly read, couldn't be read
    status_reason: str = ""

    def line(self, line_id: str) -> Line | None:
        return next((l for l in self.lines if l.id == line_id), None)

    def page_lines(self, page: int) -> list[Line]:
        return [l for l in self.lines if l.page == page]


class RulerFit(BaseModel):
    page: int
    labels: int  # frame labels read
    used: int  # labels on the fitted line
    pt_per_frame: float
    x_at_frame0: float
    max_residual_pt: float
    rejected: list[dict] = Field(default_factory=list)  # {text, confidence, box, position_says_frame}


class LadderFit(BaseModel):
    page: int
    labels: int
    used: int
    in_per_pt: float  # real inches per drawing point (vertical)
    baseline_y_pt: float  # y of the baseline (0 ABL) on the page
    max_residual_in: float
    levels: list[dict] = Field(default_factory=list)  # {name, value_in, y_pt, line_id}
    rejected: list[dict] = Field(default_factory=list)


class Calibration(BaseModel):
    """A drawing as a measuring instrument: the scale, checked two ways when possible."""

    page: int
    ruler: RulerFit | None = None
    ladder: LadderFit | None = None
    scale_measured: str = ""  # e.g. "1:196.7"
    real_mm_per_pt: float | None = None
    scale_noted: list[str] = Field(default_factory=list)
    noted_matches: bool | None = None  # does any scale note agree with the measured scale (within 2%)?
    implied_frame_spacing_mm: float | None = None  # ruler x ladder, when both exist
    stated_frame_spacing_mm: float | None = None
    methods_agree: bool | None = None  # two independent methods agree within 0.5%
    certificate: str = ""  # one plain sentence for the engineer


class FactCandidate(BaseModel):
    """A value found in a document, before it becomes a Fact. Code parsed the value from the cited text."""

    fact_id: str  # id in rules/facts, e.g. ship.length_overall
    subject: str
    property: str
    value: float | str
    unit: str = ""
    page: int
    line_ids: list[str] = Field(default_factory=list)
    label_text: str = ""  # the dictionary label found next to the value
    quote: str = ""  # exact text of the cited lines
    box: Box | None = None
    method: str = ""  # labeled_rule, ai_pointer, table_cell, ifc_property
    readings: list[dict] = Field(default_factory=list)  # {method, text, value, confidence}
    checks: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
