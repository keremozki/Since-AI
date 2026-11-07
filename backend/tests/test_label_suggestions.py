"""The AI can teach the reader a wording, but only through an engineer's approval; it never supplies a value."""
import shutil
from pathlib import Path

import pytest

from app import dictionary
from app.models import Box
from app.reading.model import DocumentMap, Line, PageInfo
from app.reading.pipeline import label_suggestions

FACTS = Path(__file__).resolve().parents[2] / "rules" / "facts"


def line(i, text, x0=62, y0=100):
    return Line(id=f"p1-l{i}", page=1, text=text, box=Box(page=1, x0=x0, y0=y0, x1=x0 + 80, y1=y0 + 13), source="text_layer")


def test_only_short_wordings_refused_for_a_missing_label_become_suggestions():
    dm = DocumentMap(file="s.pdf", sha256="x", pages=[PageInfo(page=1, width_pt=595, height_pt=842, kind="vector_text")],
                     lines=[line(1, "Breadth, greatest"), line(2, "37.40 m", 275), line(3, "5101", 300, 300), line(4, "900", 300, 320)])
    rejected = [
        {"pointer": {"fact_id": "ship.breadth_greatest", "label_line_ids": ["p1-l1"], "value_line_ids": ["p1-l2"], "note": "n"},
         "reasons": ["the label line holds no listed label for ship.breadth_greatest"]},
        {"pointer": {"fact_id": "door.clear_width", "label_line_ids": ["p1-l3"], "value_line_ids": ["p1-l4"], "note": "n"},
         "reasons": ["the label line holds no listed label for door.clear_width"]},
        {"pointer": {"fact_id": "ship.beam", "label_line_ids": ["p1-l1"], "value_line_ids": ["p1-l2"], "note": "n"},
         "reasons": ["the value line is not on the label's row"]},
    ]
    found = label_suggestions(dm, "s.pdf", rejected)
    assert [(s["fact_id"], s["label"]) for s in found] == [("ship.breadth_greatest", "Breadth, greatest")]


def test_approved_label_is_added_with_who_approved_it_and_lookalikes_are_refused(tmp_path):
    facts = tmp_path / "facts"
    shutil.copytree(FACTS, facts)
    try:
        updated = dictionary.add_label("ship.breadth_greatest", "Breadth, greatest", "J. Engineer", "from spec.pdf", facts)
        assert "BREADTH, GREATEST" in updated.labels
        assert "approved by J. Engineer" in (facts / "ship.breadth_greatest.yaml").read_text()
        with pytest.raises(ValueError):
            dictionary.add_label("ship.breadth_greatest", "Breadth moulded", "J. Engineer", directory=facts)
        with pytest.raises(ValueError):
            dictionary.add_label("ship.breadth_greatest", "Beam 2", "J. Engineer", directory=facts)
    finally:
        dictionary.load.cache_clear()
