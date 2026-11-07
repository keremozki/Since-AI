"""Title block: drawing number, revision, title, scale notes, sheet size and hull numbers.

Read by labels and positions only. A value is taken from the cell next to or under its label, and only when it has
the right shape; two equally good candidates give no value, and pages that disagree give no value.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .model import DocumentMap, Line, PageInfo, TitleBlock

_DRAWING_LABEL = re.compile(r"\b(?:DRAWING|DWG|DRG|DOCUMENT|DOC)\s*\.?\s*(?:(?:NO|NUMBER|NUM)\b|#)\.?\s*[:#]?")
_REV_LABEL = re.compile(r"\bREV(?:ISION)?\b\.?\s*[:#]?")
_SIZE_LABEL = re.compile(r"\b(?:(?:SHEET|PAPER|DRAWING)\s+)?SIZE\b\s*[:#]?")
_TITLE_LABEL = re.compile(r"\b(?:DRAWING\s+|SHEET\s+)?TITLE\b\s*[:#]?", re.I)
_ANCHOR_LABEL = re.compile(r"\b(?:SIZE|FSCM|CAGE|DRAWING\s*NO|DWG\.?\s*NO|SCALE|SHEET|REV)\b")

_DRAWING_NO = re.compile(r"[A-Z0-9]{2,}(?:[-_/.][A-Z0-9]+){1,5}")
_REVISION = re.compile(r"[A-Z]|\d{1,2}|[A-Z]\d|\d[A-Z]")
_SHEET_SIZE = re.compile(r"[A-E]|A[0-5]")
_SIZE_INLINE = re.compile(r"\bSIZE\b\s*[:#]?\s*(?:(?:ANSI|ARCH|ISO)\s+)?([A-E]|A[0-5])\b")
_SIZE_NAMED = re.compile(r"\b(?:ANSI|ARCH|ISO)\s+([A-E]|A[0-5])\b")
_REV_INLINE = re.compile(r"\bREV(?:ISION)?\b\.?\s*[:#]?\s+([A-Z0-9]{1,2})\b")
_HULLS = re.compile(r"\bHULLS?\b\s*(?:NO\.?|NOS\.?|NUMBERS?|#)?\s*[:#.]*\s*((?:\d{2,6}\b(?:\s*(?:,|&|/|AND)\s*|\s+)?)+)")

_RATIO = re.compile(r"(?<![\d:.])1\s*:\s*\d{1,5}(?:\.\d+)?(?![\d:])")
_IMPERIAL = re.compile(
    r"\d+(?:\.\d+)?(?:\s*/\s*\d+)?\s*[\"”″]\s*=\s*\d+(?:\.\d+)?\s*['’′´`]\s*(?:[-–—−]\s*\d+(?:\s*\d/\d+)?\s*(?:[\"”″]|'')?)?")
_NO_SCALE_WORDS = r"(?:NONE|NTS|N\.T\.S\.?|NOT\s+TO\s+SCALE|AS\s+SHOWN)"
_NO_SCALE = re.compile(rf"\bSCALE\s*[:=]?\s*{_NO_SCALE_WORDS}", re.I)
_SCALE_LABEL = re.compile(r"SCALE\s*[:=]?")
_NO_SCALE_VALUE = re.compile(_NO_SCALE_WORDS, re.I)

# Where the title block usually is: bottom right. Used to rank, never to exclude.
_CORNER = (1.0, 1.0)


def find_scale_notes(text: str) -> list[str]:
    """Scale notes in a piece of text, as written: "1:100", '1/8"=1\'-0"', "SCALE: NONE"."""
    found: list[tuple[int, str]] = []
    for pattern in (_RATIO, _IMPERIAL, _NO_SCALE):
        for m in pattern.finditer(text):
            note = re.sub(r"\s+", " ", m.group(0)).strip()
            found.append((m.start(), re.sub(r"\s*:\s*", ":", note) if pattern is _RATIO else note))
    return [note for _, note in sorted(found)]


@dataclass
class _Found:
    value: str
    evidence: list[str] = field(default_factory=list)


def read_title_block(dm: DocumentMap) -> TitleBlock:
    """The title block of a document map. Fields stay empty when the pages give no single clear answer."""
    per_page: dict[int, dict[str, _Found]] = {}
    hulls: dict[int, _Found] = {}
    notes: list[str] = []
    evidence: list[str] = []
    for info in dm.pages:
        lines = dm.page_lines(info.page)
        found = {
            "drawing_no": _drawing_number(lines, info),
            "revision": _revision(lines, info),
            "sheet_size": _sheet_size(lines, info),
            "title": _title(lines, info),
        }
        per_page[info.page] = {k: v for k, v in found.items() if v}
        hull = _hull_numbers(lines, info)
        if hull:
            hulls[info.page] = hull
        for line in lines:
            for note in find_scale_notes(line.text):
                if note not in notes:
                    notes.append(note)
                if line.id not in evidence:
                    evidence.append(line.id)
        for note, ids in _scale_cells(lines):
            if note not in notes:
                notes.append(note)
            evidence += [i for i in ids if i not in evidence]

    block = TitleBlock(scale_notes=notes)
    for name in ("drawing_no", "revision", "sheet_size"):
        value = _vote({p: f[name] for p, f in per_page.items() if name in f})
        if value:
            setattr(block, name, value.value)
            evidence += [e for e in value.evidence if e not in evidence]
    title = _shared_title({p: f["title"] for p, f in per_page.items() if "title" in f})
    if title:
        block.title = title.value
        evidence += [e for e in title.evidence if e not in evidence]
    hull = _vote(hulls)
    if hull:
        block.hulls = hull.value.split()
        evidence += [e for e in hull.evidence if e not in evidence]
    block.evidence = evidence
    return block


def _shared_title(titles: dict[int, _Found]) -> _Found | None:
    """The title the sheets share. Sheets of one drawing differ only in their sub-title ("... - INBOARD PROFILE"), so
    the words they all start with stand; if they share none, the first sheet's title does."""
    if not titles:
        return None
    first = titles[min(titles)]
    words = [t.value.split() for t in titles.values()]
    common: list[str] = []
    for group in zip(*words):
        if len(set(group)) > 1:
            break
        common.append(group[0])
    while common and not any(c.isalnum() for c in common[-1]):
        common.pop()  # a dash that led into the sub-title
    return _Found(" ".join(common), first.evidence) if common else first


def _vote(candidates: dict[int, _Found]) -> _Found | None:
    """The value most pages agree on; a tie between values is no value."""
    if not candidates:
        return None
    counts = Counter(c.value for c in candidates.values())
    ranked = counts.most_common()
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    winner = ranked[0][0]
    return next(candidates[p] for p in sorted(candidates) if candidates[p].value == winner)


# ---------------------------------------------------------------- geometry helpers

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.upper().replace(" ", " ")).strip()


def _corner_distance(line: Line, info: PageInfo) -> float:
    """How far a line's center is from the bottom right corner, as a share of the page."""
    cx = (line.box.x0 + line.box.x1) / 2 / max(info.width_pt, 1.0)
    cy = (line.box.y0 + line.box.y1) / 2 / max(info.height_pt, 1.0)
    return math.hypot(_CORNER[0] - cx, _CORNER[1] - cy)


def _height(line: Line) -> float:
    return max(line.box.y1 - line.box.y0, 1.0)


def _cells_near(label: Line, lines: list[Line]) -> list[tuple[float, Line]]:
    """Lines under the label or to its right, nearest first. The score is the distance in points."""
    h = _height(label)
    out = []
    for cand in lines:
        if cand.id == label.id:
            continue
        below = cand.box.y0 - label.box.y1
        overlaps = cand.box.x0 <= label.box.x1 + 40 and cand.box.x1 >= label.box.x0 - 10
        if -0.3 * h <= below <= 3 * h + 8 and overlaps:
            dx = abs((cand.box.x0 + cand.box.x1) / 2 - (label.box.x0 + label.box.x1) / 2)
            out.append((max(below, 0.0) + 0.5 * dx, cand))
            continue
        same_row = abs((cand.box.y0 + cand.box.y1) / 2 - (label.box.y0 + label.box.y1) / 2) <= 0.6 * h
        right = cand.box.x0 - label.box.x1
        if same_row and -0.5 * h <= right <= 150:
            out.append((max(right, 0.0), cand))
    return sorted(out, key=lambda s: s[0])


def _value_after(label: Line, lines: list[Line], accept) -> _Found | None:
    """The best cell next to a label that `accept` turns into a value; two different near-equal ones give None."""
    scored = []
    for score, cand in _cells_near(label, lines):
        value = accept(_norm(cand.text))
        if value:
            scored.append((score, value, cand))
    if not scored:
        return None
    best = scored[0]
    for score, value, cand in scored[1:]:
        if value != best[1] and score <= best[0] * 1.25 + 2.0:
            return None
    return _Found(best[1], [label.id, best[2].id])


def _label_lines(lines: list[Line], pattern: re.Pattern[str], info: PageInfo) -> list[Line]:
    """Lines that contain the label, the one nearest the bottom right corner first."""
    hits = [l for l in lines if pattern.search(_norm(l.text))]
    return sorted(hits, key=lambda l: _corner_distance(l, info))


# ---------------------------------------------------------------- fields

def _scale_cells(lines: list[Line]) -> list[tuple[str, list[str]]]:
    """"SCALE:" in one cell and "NONE" in the next is the note "SCALE: NONE"."""
    out = []
    for label in lines:
        if not _SCALE_LABEL.fullmatch(_norm(label.text)):
            continue
        found = _value_after(label, lines, lambda t: t if _NO_SCALE_VALUE.fullmatch(t) else "")
        if found:
            out.append((f"SCALE: {found.value}", found.evidence))
    return out


def _accept_drawing_no(text: str) -> str:
    token = text.strip(" :#")
    if _DRAWING_NO.fullmatch(token) and any(c.isdigit() for c in token) and len(token) >= 5:
        return token
    return ""


def _accept_revision(text: str) -> str:
    token = text.strip(" :#.")
    return token if _REVISION.fullmatch(token) else ""


def _accept_size(text: str) -> str:
    token = text.strip(" :#.")
    return token if _SHEET_SIZE.fullmatch(token) else ""


def _inline(label: Line, pattern: re.Pattern[str], accept) -> _Found | None:
    """A value on the same line as its label, such as "DRAWING NO: SYN-GA-105"."""
    text = _norm(label.text)
    m = pattern.search(text)
    rest = text[m.end():] if m else ""
    token = rest.split()[0] if rest.split() else ""
    value = accept(token)
    return _Found(value, [label.id]) if value else None


def _drawing_number(lines: list[Line], info: PageInfo) -> _Found | None:
    for label in _label_lines(lines, _DRAWING_LABEL, info):
        found = _inline(label, _DRAWING_LABEL, _accept_drawing_no) or _value_after(label, lines, _accept_drawing_no)
        if found:
            return found
    return None


def _revision(lines: list[Line], info: PageInfo) -> _Found | None:
    for label in _label_lines(lines, _REV_LABEL, info):
        text = _norm(label.text)
        m = _REV_INLINE.search(text)
        if m and _accept_revision(m.group(1)):
            return _Found(m.group(1), [label.id])
        if not re.fullmatch(r"REV(?:ISION)?\.?\s*[:#]?", text):
            continue  # a sentence that mentions a revision, not the label cell
        found = _value_after(label, lines, _accept_revision)
        if found:
            return found
    return None


def _sheet_size(lines: list[Line], info: PageInfo) -> _Found | None:
    for line in sorted(lines, key=lambda l: _corner_distance(l, info)):
        text = _norm(line.text)
        m = _SIZE_INLINE.search(text) or _SIZE_NAMED.search(text)
        if m:
            return _Found(m.group(1), [line.id])
    for label in _label_lines(lines, _SIZE_LABEL, info):
        if not re.fullmatch(r"(?:(?:SHEET|PAPER|DRAWING)\s+)?SIZE\s*[:#]?", _norm(label.text)):
            continue
        found = _value_after(label, lines, _accept_size)
        if found:
            return found
    return None


def _title(lines: list[Line], info: PageInfo) -> _Found | None:
    """The text after a TITLE label; otherwise the lines stacked just above the title block's label row."""
    for label in sorted((l for l in lines if _TITLE_LABEL.search(l.text)), key=lambda l: _corner_distance(l, info)):
        m = _TITLE_LABEL.search(label.text)
        rest = label.text[m.end():].strip(" :#") if m else ""
        if rest:
            return _Found(rest, [label.id])
        stacked = [c for score, c in _cells_near(label, lines) if c.box.y0 >= label.box.y1 - 1]
        if stacked:
            first = min(stacked, key=lambda c: (c.box.y0, c.box.x0))
            return _Found(first.text.strip(), [label.id, first.id])
    return _stacked_title(lines, info)


def _stacked_title(lines: list[Line], info: PageInfo) -> _Found | None:
    """Up to three text lines directly above the label row (SIZE, DRAWING NO, SCALE...) of the corner block.

    Only lines without digits count, so addresses, dimensions and sheet numbers don't end up in a title.
    """
    anchors = [l for l in lines if _ANCHOR_LABEL.search(_norm(l.text)) and _corner_distance(l, info) < 0.5]
    if len(anchors) < 2:
        return None
    top = min(l.box.y0 for l in anchors)
    left = min(l.box.x0 for l in anchors) - 10
    right = max(l.box.x1 for l in anchors) + 10
    above = sorted((l for l in lines if l.box.y1 <= top + 1 and l.box.x0 >= left and l.box.x1 <= right),
                   key=lambda l: -l.box.y1)
    picked: list[Line] = []
    edge = top
    for line in above:
        if edge - line.box.y1 > 2.5 * _height(line) + 4:
            break
        edge = line.box.y0
        if any(c.isdigit() for c in line.text) or len(line.text.strip()) < 3:
            continue
        picked.append(line)
        if len(picked) == 3:
            break
    if not picked:
        return None
    picked.reverse()
    return _Found(" ".join(l.text.strip() for l in picked), [l.id for l in picked])


def _hull_numbers(lines: list[Line], info: PageInfo) -> _Found | None:
    """Hull numbers from the title block, in the order written. Lines saying "ONLY" restrict a revision, not the sheet."""
    best: _Found | None = None
    for line in sorted(lines, key=lambda l: _corner_distance(l, info)):
        text = _norm(line.text)
        if "ONLY" in text:
            continue
        m = _HULLS.search(text)
        if m:
            numbers = re.findall(r"\d{2,6}", m.group(1))
            if numbers:
                best = _Found(" ".join(dict.fromkeys(numbers)), [line.id])
                break
    return best
