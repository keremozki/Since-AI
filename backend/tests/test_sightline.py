"""SOLAS V/22.1.1 on the drawing: code measures the engineer's three points on a calibrated profile."""
import pytest

from app.checks import check_bridge_visibility
from app.models import Fact, Rule, Source, SourceKind, Tier
from app.reading.model import Calibration, LadderFit, RulerFit
from app.sightline import Pick, SightlineError, SightlineRequest, derive
from app.store import FactStore

RULE = Rule(id="SOLAS-V-22", title="Bridge", area="A", source="S", check="bridge_visibility",
            params={"max_ship_lengths": 2, "max_metres": 500})


def calibration(agree=True):
    return Calibration(page=1, ruler=RulerFit(page=1, labels=10, used=10, pt_per_frame=1.0, x_at_frame0=0, max_residual_pt=0.1),
                       ladder=LadderFit(page=1, labels=5, used=5, in_per_pt=1.0, baseline_y_pt=500.0, max_residual_in=0.1),
                       real_mm_per_pt=25.4, scale_measured="1:72.0", methods_agree=agree, certificate="test")


def request(**kw):
    base = dict(file="ga.pdf", page=1, eye=Pick(x=100, y=100), obstruction=Pick(x=300, y=300), bow=Pick(x=400, y=380), by="J. Engineer")
    return SightlineRequest(**{**base, **kw})


def test_points_become_bridge_facts_and_the_check_runs_on_them():
    facts, overlay = derive(request(), calibration(), 2.0, "spec")
    got = {f.property: f.value for f in facts}
    assert got == {"eye_height_above_water": 8.16, "obstruction_height_above_water": 3.08, "eye_to_obstruction": 5.08,
                   "eye_to_bow": 7.62}
    assert all(f.tier == Tier.B for f in facts) and "picked by J. Engineer" in facts[0].source.locator
    loa = Fact(subject="ship", property="length_overall", value=60.0, unit="m", source=Source(kind=SourceKind.CHAT))
    finding = check_bridge_visibility(RULE, FactStore([*facts, loa]), None)[0]
    assert finding.status.value == "pass" and finding.measured.startswith("1 m")  # 0.54 m hidden, limit 120 m
    assert overlay["lines"] and overlay["lines"][0]["to"]["y"] == pytest.approx(500 - 2000 / 25.4)


def test_a_scale_checked_one_way_gives_tier_c_and_no_ladder_is_refused():
    facts, _ = derive(request(), calibration(agree=None), 2.0, "spec")
    assert all(f.tier == Tier.C for f in facts)
    no_ladder = calibration().model_copy(update={"ladder": None})
    with pytest.raises(SightlineError):
        derive(request(), no_ladder, 2.0, "spec")


def test_an_obstruction_beyond_the_bow_is_refused():
    with pytest.raises(SightlineError):
        derive(request(obstruction=Pick(x=450, y=300)), calibration(), 2.0, "spec")
