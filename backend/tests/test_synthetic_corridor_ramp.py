"""SYNTHETIC corridor and ramp drawings: the generator's truth, the reader on them, and the checks' edges."""
import json
import random
import sys
from fractions import Fraction
from pathlib import Path

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import synthetic_corridor_ramp as gen  # noqa: E402
from validate_data import compare_facts, compare_results  # noqa: E402

from app.models import Tier  # noqa: E402
from app.reading.code_reader import extra_facts  # noqa: E402

from app.checks import check_corridor_width, check_ramp_slope  # noqa: E402
from app.drawing import read_pdf  # noqa: E402
from app.models import Fact, Rule, ShipProfile, Source, SourceKind, Status  # noqa: E402
from app.rules import load_rules  # noqa: E402
from app.store import FactStore  # noqa: E402

SETS = sorted((ROOT / "data" / "synthetic").glob("SYNTHETIC_corridor_ramp_seed*"))
CORRIDOR_RULE = Rule(id="C", title="Corridor", area="A", source="S", check="corridor_width", params={"min_in": 36, "reduced_in": 32})
RAMP_RULE = Rule(id="RP", title="Ramp", area="A", source="S", check="ramp_slope", params={"max_run_per_rise": 12})
PASSENGER = ShipProfile(id="p", name="p", ship_type="passenger", passengers=400)


@pytest.mark.parametrize("case, style, text", [
    ("exactly_36", "in", '36"'), ("exactly_36", "ftin", "3'-0\""),
    ("just_above_36", "mm", "915 mm"), ("just_below_36", "mm", "914 mm"),
    ("just_above_36", "in", '36 1/8"'), ("just_below_36", "in", '35 7/8"'),
    ("just_above_36", "m", "0.92 m"), ("just_below_36", "m", "0.91 m"),
    ("just_above_32", "mm", "813 mm"), ("just_below_32", "mm", "812 mm"),
    ("just_below_36", "ftin", "2'-11 1/2\""), ("just_above_32", "bare", "815"),
])
def test_threshold_widths_are_written_exactly(case, style, text):
    assert gen.length_text(gen.corridor_value(random.Random(0), case, style), style) == text


def test_corridor_truth_follows_v403_5_1():
    assert gen.corridor_expected(36 * gen.IN_MM) == "pass"
    assert gen.corridor_expected(Fraction(914)) == "cant_tell"   # 35.98 in: exceptions may apply
    assert gen.corridor_expected(32 * gen.IN_MM) == "cant_tell"
    assert gen.corridor_expected(Fraction(812)) == "fail"


@pytest.mark.parametrize("style", ["ratio", "riserun_mm", "riserun_in", "riserun_m"])
def test_ramp_cases_sit_on_the_right_side_of_1_12(style):
    rng = random.Random(3)
    slope = lambda v: 1 / v[0] if style == "ratio" else v[0] / v[1]  # noqa: E731
    assert slope(gen.ramp_value(rng, "exactly_1_12", style)) == gen.RAMP_MAX
    assert slope(gen.ramp_value(rng, "just_steeper", style)) > gen.RAMP_MAX
    assert slope(gen.ramp_value(rng, "just_shallower", style)) < gen.RAMP_MAX


def test_generated_set_is_labelled_synthetic_and_covers_every_case(tmp_path):
    folder = gen.make_corridor_ramp_set(7, tmp_path, sheets=2)
    assert "SYNTHETIC" in folder.name
    cases = set()
    for truth_path in folder.glob("*.truth.json"):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        assert truth["synthetic"] is True and truth["file"].startswith("SYNTHETIC_")
        assert "SYNTHETIC" in pymupdf.open(truth_path.with_name(truth["file"])).metadata["keywords"]
        cases |= {e["subject"].split(":")[0] + ":" + e["case"] for e in truth["expected"]}
        for e in truth["expected"]:
            if e["case"].startswith("unreadable"):
                assert e["expected"] == "cant_tell"
                assert not any(f["subject"] == e["subject"] for f in truth["facts"])
    assert cases == {f"corridor:{c}" for c in gen.CORRIDOR_CASES} | {f"ramp:{c}" for c in gen.RAMP_CASES}


def test_same_seed_gives_the_same_truth(tmp_path):
    with pytest.raises(ValueError):
        gen.make_corridor_ramp_set(11, tmp_path / "c", sheets=1)
    a = gen.make_corridor_ramp_set(11, tmp_path / "a", sheets=2)
    b = gen.make_corridor_ramp_set(11, tmp_path / "b", sheets=2)
    name = "SYNTHETIC_cr_s11_01.truth.json"
    assert (a / name).read_text() == (b / name).read_text()


@pytest.mark.parametrize("folder", SETS, ids=[s.name for s in SETS])
def test_committed_sets_validate_with_no_false_pass(folder):
    rules = load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
    for truth_path in sorted(folder.glob("*.truth.json")):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        read = read_pdf(truth_path.with_name(truth["file"]).read_bytes(), truth["file"])
        facts = compare_facts([f.model_dump(mode="json") for f in read.facts], truth["facts"], [])
        assert facts["wrong_or_extra"] == [] and facts["missed"] == [], truth["file"]
        trusted = [f.model_copy(update={"tier": Tier.B}) for f in read.facts]
        tally = compare_results(trusted, truth, rules)["tally"]
        assert tally.get("FALSE_PASS", 0) == 0 and tally.get("mismatch", 0) == 0, truth["file"]
        graded = extra_facts(truth["file"], truth_path.with_name(truth["file"]).read_bytes(), None, [])
        assert compare_results(graded, truth, rules)["tally"].get("FALSE_PASS", 0) == 0, truth["file"]


def page_pdf(*items):
    doc = pymupdf.open()
    page = doc.new_page(width=800, height=600)
    for text, at, rotate in items:
        page.insert_text(at, text, fontsize=8, rotate=rotate)
    return doc.tobytes()


def test_reader_corridor_layouts():
    data = page_pdf(('CORRIDOR C1  CLEAR WIDTH 42"', (50, 50), 0),
                    ("CORRIDOR C2", (50, 150), 0), ("CLR WIDTH 1200 mm", (50, 162), 0),
                    ("CORRIDOR C3", (50, 250), 0),
                    ("CORRIDOR SCHEDULE", (500, 50), 0), ("C3    0.95 m", (500, 64), 0))
    read = read_pdf(data, "t.pdf")
    got = {(f.subject, f.property): (f.value, f.unit) for f in read.facts}
    assert got[("corridor:C1", "clear_width")] == (42, "in")
    assert got[("corridor:C2", "clear_width")] == (1200, "mm")
    assert got[("corridor:C3", "clear_width")] == (0.95, "m")


def test_reader_never_uses_rotated_or_unitless_values():
    data = page_pdf(("CORRIDOR C1", (50, 50), 0), ('CLR WIDTH 30"', (90, 75), 90),
                    ("CORRIDOR C2  CLEAR WIDTH 1100", (50, 200), 0),
                    ("RAMP R1", (400, 50), 0), ("RISE 150  RUN 1800", (400, 62), 0))
    read = read_pdf(data, "t.pdf")
    props = {(f.subject, f.property) for f in read.facts}
    assert props == {("corridor:C1", "shown_on"), ("corridor:C2", "shown_on"), ("ramp:R1", "shown_on")}
    assert any("rotated" in s for s in read.skipped)


def test_reader_ramp_labels_and_scale_note():
    data = page_pdf(("RAMP R1  SLOPE 1:12.5", (50, 50), 0),
                    ("RAMP R2", (50, 150), 0), ("RISE 6\"  RUN 6'-0\"", (50, 162), 0),
                    ("SCALE 1:50", (500, 500), 0))
    read = read_pdf(data, "t.pdf")
    got = {(f.subject, f.property): f.value for f in read.facts}
    assert got[("ramp:R1", "slope_run_per_rise")] == 12.5
    assert got[("ramp:R2", "rise")] == 6 and got[("ramp:R2", "run")] == 72
    assert not any(f.value == 50 for f in read.facts)


def fact(subject, prop, value, unit="in"):
    return Fact(subject=subject, property=prop, value=value, unit=unit, confidence="high",
                source=Source(kind=SourceKind.DOCUMENT, file="t.pdf"))


@pytest.mark.parametrize("rise, run, unit", [(4, 48, "in"), (6, 72, "in"), (0.15, 1.8, "m"), (150, 1800, "mm")])
def test_exactly_1_12_passes_in_every_unit(rise, run, unit):
    store = FactStore([fact("ramp:R", "rise", rise, unit), fact("ramp:R", "run", run, unit)])
    assert check_ramp_slope(RAMP_RULE, store, PASSENGER)[0].status == Status.PASS


def test_corridor_named_without_width_is_cant_tell():
    store = FactStore([fact("corridor:C9", "shown_on", "page 1", "")])
    finding = check_corridor_width(CORRIDOR_RULE, store, PASSENGER)[0]
    assert finding.status == Status.CANT_TELL and "C9" in finding.question


def test_cant_tell_names_the_label_page_and_reason():
    """A labelled object with no usable value says which text was found, where, and why it wasn't used."""
    from app.engine import run
    from app.models import ShipProfile
    from app.rules import load_rules
    from app.store import FactStore
    pdf = ROOT / "data" / "synthetic" / "SYNTHETIC_corridor_ramp_seed202" / "SYNTHETIC_cr_s202_02.pdf"
    facts = read_pdf(pdf.read_bytes(), pdf.name).facts
    rules = load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
    result = run(FactStore(facts), rules, ShipProfile(id="p", name="t", ship_type="passenger", passengers=400))
    c24 = next(f for f in result.findings if f.label == "Corridor C2-4")
    assert c24.status.value == "cant_tell"
    assert "'CORRIDOR C2-4  CLEAR WIDTH 1065'" in c24.measured and "page 1" in c24.measured
    assert "no unit" in c24.measured and c24.read_quote and c24.sources
