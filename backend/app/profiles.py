"""Ship profiles: the facts that decide which rules apply."""
from __future__ import annotations

from .models import Fact, ShipProfile, Source, SourceKind

RCRV = ShipProfile(
    id="rcrv",
    name="RCRV as designed (research vessel)",
    ship_type="research",
    passengers=0,
    flag="US",
    note="US research vessel under 46 CFR Subchapter U with a SOLAS Special Purpose certificate.",
)

PASSENGER_TEST = ShipProfile(
    id="passenger-test",
    name="RCRV test case: passenger ship rules, with seeded faults",
    ship_type="passenger",
    passengers=200,
    flag="US",
    note=("Test case only. The real RCRV isn't a passenger ship. This profile applies passenger ship "
          "rules to its real design data, and adds one labelled seeded conflict."),
    accessible_route_all_passage_doors=True,
    use_demo_faults=True,
)

PROFILES = {profile.id: profile for profile in (RCRV, PASSENGER_TEST)}


def demo_faults() -> list[Fact]:
    """Seeded faults for the test profile. Always labelled as seeded in every result."""
    def seeded(value: float, locator: str) -> Fact:
        return Fact(subject="ship", property="lightship_weight", value=value, unit="LT",
                    source=Source(kind=SourceKind.DEMO_SEED, locator=locator))

    return [seeded(2600.0, "table A, seeded"), seeded(2510.0, "table B, seeded")]
