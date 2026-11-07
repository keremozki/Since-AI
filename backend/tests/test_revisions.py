"""A newer revision replaces the older one's facts, and only when the order is certain."""
from app.models import Evidence, Fact, Source, SourceKind
from app.revisions import newer, revision_key, supersede, value_changes


def drawing_fact(prop, value, revision, doc="GA-501", unit="mm", subject="stair:S5"):
    return Fact(subject=subject, property=prop, value=value, unit=unit,
                source=Source(kind=SourceKind.DOCUMENT, file=f"ga-rev{revision}.pdf", quote=f"{value}"),
                evidence=Evidence(file=f"ga-rev{revision}.pdf", doc_id=doc, revision=revision))


def test_revision_order_only_within_one_kind():
    assert newer("B", "A") and newer("AA", "Z") and newer("2", "1") and newer("P2", "P1")
    assert newer("Rev. C", "B")
    assert newer("B", "2") is None and newer("P1", "A") is None and revision_key("draft") is None


def test_newer_revision_replaces_older_facts():
    old = [drawing_fact("clear_width", 1200.0, "A")]
    existing, incoming, notes = supersede(old, [drawing_fact("clear_width", 1100.0, "B")])
    assert existing[0].superseded_by == "GA-501 revision B" and not incoming[0].superseded_by
    assert notes == [{"doc_id": "GA-501", "old": "A", "new": "B", "replaced": 1, "file": "ga-revB.pdf"}]


def test_older_revision_uploaded_late_is_replaced_at_once():
    existing, incoming, _ = supersede([drawing_fact("clear_width", 1100.0, "B")], [drawing_fact("clear_width", 1200.0, "A")])
    assert not existing[0].superseded_by and incoming[0].superseded_by == "GA-501 revision B"


def test_revisions_that_cant_be_ordered_both_stay_and_ask():
    existing, incoming, notes = supersede([drawing_fact("clear_width", 1100.0, "B")], [drawing_fact("clear_width", 1200.0, "2")])
    assert not existing[0].superseded_by and not incoming[0].superseded_by
    assert "Which revision" in notes[0]["question"]


def test_other_drawings_are_untouched():
    other = drawing_fact("clear_width", 900.0, "A", doc="GA-502")
    existing, _, _ = supersede([other], [drawing_fact("clear_width", 1100.0, "B")])
    assert not existing[0].superseded_by


def test_value_changes_list_changed_added_and_removed():
    old = [drawing_fact("clear_width", 1200.0, "A"), drawing_fact("persons_served", 120.0, "A", unit="")]
    new = [drawing_fact("clear_width", 1100.0, "B"), drawing_fact("opening_depth", 300.0, "B", subject="door-number:5-301")]
    changes = {(c["subject"], c["property"]): c for c in value_changes(old, new)}
    assert changes[("stair:S5", "clear_width")]["change"] == "changed"
    assert changes[("stair:S5", "clear_width")]["old"] == "1200 mm" and changes[("stair:S5", "clear_width")]["new"] == "1100 mm"
    assert changes[("stair:S5", "persons_served")]["change"] == "removed"
    assert changes[("door-number:5-301", "opening_depth")]["change"] == "added"
