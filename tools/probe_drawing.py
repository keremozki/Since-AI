"""Quick, AI-free probe of a drawing file: is it vector or a scan, does it state a scale,
and does its text name objects our checks need (doors, corridors, ramps, ...).

Usage: python tools/probe_drawing.py file.pdf [more files]   (prints JSON per file)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pymupdf

SCALE = re.compile(r"\b(scale\s*[:=]?\s*)?1\s*:\s*(20|25|50|75|100|125|150|200|250|300|500)\b", re.I)
DIMENSION = re.compile(r"\b\d{1,2}'\s*-?\s*\d{1,2}(\s*\d/\d)?\"|\b\d{3,5}\s*mm\b|\b\d{2,3}\s*(in|\")\b", re.I)
OBJECTS = {
    "door": r"\bdoors?\b|\bdr\.?\s*\d|\bwtd\b",
    "corridor": r"\bcorridors?\b|\bpassage(way)?s?\b|\bhallway\b",
    "ramp": r"\bramps?\b",
    "elevator": r"\belevators?\b|\blifts?\b",
    "stair": r"\bstairs?\b|\bstairway\b|\bladder\b",
    "cabin": r"\bcabins?\b|\bstateroom\b|\bberths?\b",
    "accessible": r"\baccessible\b|\bada\b|\bwheelchair\b|\bhandicap",
    "toilet": r"\btoilets?\b|\bwc\b|\blav(atory)?\b|\bhead\b",
}


def probe_pdf(path: Path) -> dict:
    doc = pymupdf.open(path)
    pages = []
    all_text = []
    for page in doc:
        text = page.get_text()
        all_text.append(text)
        drawings = len(page.get_drawings())
        images = len(page.get_images())
        pages.append({"page": page.number + 1, "size_pt": [round(page.rect.width), round(page.rect.height)],
                      "text_chars": len(text), "vector_paths": drawings, "images": images,
                      "kind": "vector" if drawings > 200 or (len(text) > 200 and images == 0) else
                              ("scan/image" if images and len(text) < 50 else "mixed/text")})
    text = "\n".join(all_text)
    return {
        "file": path.name, "pages": len(doc),
        "page_summary": pages[:12],
        "scale_mentions": sorted({m.group(0).strip() for m in SCALE.finditer(text)})[:10],
        "dimension_strings_sample": [m.group(0) for m in DIMENSION.finditer(text)][:15],
        "dimension_strings_count": len(DIMENSION.findall(text)),
        "object_word_counts": {k: len(re.findall(v, text, re.I)) for k, v in OBJECTS.items()},
    }


def main() -> None:
    for arg in sys.argv[1:]:
        p = Path(arg)
        result = probe_pdf(p) if p.suffix.lower() == ".pdf" else {"file": p.name, "note": "not a PDF; open with ezdxf/svg tools"}
        print(json.dumps(result))


if __name__ == "__main__":
    main()
