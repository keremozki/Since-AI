"""Turn the decoded 3D model parts into structured facts about the ship."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Fact, Point, Source, SourceKind

CLEAR = re.compile(r"(CLEAR\w*\s+OPEN\w*|LIGHT\s+OPEN\w*)\s*([\d.]+)\s*[xX]\s*([\d.]+)", re.I)
DOOR_NAME = re.compile(r"\bDOOR\b", re.I)
DOOR_EXCLUDED = re.compile(r"PUMP|PANEL|\bJB\b|CABINET|CAINET|HOLD-BACK|CONTROL|CLEARANCE|BRACKET|PARTS|\bHATCH\b", re.I)
NUMBER_LIST = re.compile(r"-\s*(\d+(?:\s*,\s*\d+)*)\s*$")
TRAILING_NUMBER = re.compile(r"\bDOOR\s+(\d{3})\s*$", re.I)
TREAD = re.compile(r"STAIR\s+TREADS?", re.I)
TREAD_LENGTH = re.compile(r'(\d+(?:\.\d+)?)\s*"\s*L', re.I)
RAFT_RACK = re.compile(r"LIFERAFT\s+(SINGLE|DOUBLE)\s+RACK", re.I)
NAV_LIGHT = re.compile(r"NAVIGATION/SIGNAL LIGHT", re.I)
DECKS_FT = [(6, "Lower level"), (10, "Second level"), (19, "Main Deck"), (28, "01 Level"),
            (37, "02 Level"), (45.5, "03 Level"), (54, "04 Level")]
STAIR_LINK_X_IN = 60.0
STAIR_LINK_YZ_IN = 24.0
INCHES_PER_METRE = 39.3701


def deck_name(z_in: float) -> str:
    """Nearest deck at or below the part. Deck heights come from the model's largest plates."""
    z_ft = z_in / 12
    name = "Below lowest deck"
    for height, label in DECKS_FT:
        if z_ft >= height - 0.5:
            name = label
    return f"{name} ({z_ft:.1f} ft above baseline)"


def load_parts(path: Path) -> tuple[str, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("source", path.name), data["parts"]


def _point(part: dict) -> Point:
    return Point(x=part["x_in"], y=part["y_in"], z=part["z_in"])


def _source(file: str, part: dict) -> Source:
    locator = f'part "{part["name"]}"'
    if part.get("item"):
        locator += f', item {part["item"]}'
    if part.get("drawing"):
        locator += f', drawing {part["drawing"]}'
    return Source(kind=SourceKind.MODEL_3D, file=file, locator=locator, quote=part.get("description", ""))


def _door_series(z_in: float) -> str:
    """The first digit of door numbers on this deck, seen across the model's named doors."""
    z_ft = z_in / 12
    for top_ft, series in ((15, "1"), (24, "5"), (33, "2"), (42, "3"), (51, "4")):
        if z_ft < top_ft:
            return series
    return ""


def door_numbers(part: dict) -> list[str]:
    """Door numbers this part could be.

    A part type name can list several doors, like "(RI-LO)-205,207,304". An item number
    settles it. Otherwise, only numbers in this deck's series stay.
    """
    name = part["name"]
    match = NUMBER_LIST.search(name) or TRAILING_NUMBER.search(name)
    numbers = re.findall(r"\d+", match.group(1)) if match else []
    item = re.search(r"(\d{3})\s*$", part.get("item", ""))
    if item and (item.group(1) in numbers or not numbers):
        return [item.group(1)]
    on_this_deck = [n for n in numbers if n.startswith(_door_series(part["z_in"]))]
    return on_this_deck or numbers


def _door_kind(name: str) -> str:
    upper = name.upper()
    if upper.startswith("ACCESS DOOR"):
        return "service_access"
    if "ROLL UP" in upper:
        return "cargo"
    return "passage"


def door_facts(file: str, parts: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    counter = 0
    for part in parts:
        name = part["name"]
        if not DOOR_NAME.search(name) or DOOR_EXCLUDED.search(name):
            continue
        counter += 1
        numbers = door_numbers(part)
        subject = f"door:{counter}"
        common = dict(subject=subject, source=_source(file, part), location=_point(part))
        facts.append(Fact(property="kind", value=_door_kind(name), **common))
        facts.append(Fact(property="name", value=name, **common))
        facts.append(Fact(property="numbers", value=",".join(numbers), **common))
        facts.append(Fact(property="deck", value=deck_name(part["z_in"]), **common))
        if part.get("compartment"):
            facts.append(Fact(property="compartment", value=part["compartment"], **common))
        match = CLEAR.search(part.get("description", ""))
        if match:
            imperial = match.group(1).upper().startswith("CLEAR")
            facts.append(Fact(property="clear_width", value=float(match.group(2)),
                              unit="in" if imperial else "mm", **common))
    return facts


def _same_stair(a: dict, b: dict) -> bool:
    return (a["name"][:14] == b["name"][:14]
            and abs(a["x_in"] - b["x_in"]) < STAIR_LINK_X_IN
            and abs(a["y_in"] - b["y_in"]) < STAIR_LINK_YZ_IN
            and abs(a["z_in"] - b["z_in"]) < STAIR_LINK_YZ_IN)


def stair_facts(file: str, parts: list[dict]) -> list[Fact]:
    """Group individual stair treads into stairs by how close they are to each other."""
    treads = sorted((p for p in parts if TREAD.search(p["name"])), key=lambda t: t["z_in"])
    groups: list[list[dict]] = []
    for tread in treads:
        home = next((g for g in groups if any(_same_stair(tread, other) for other in g)), None)
        if home is None:
            groups.append([tread])
        else:
            home.append(tread)
    facts: list[Fact] = []
    for index, group in enumerate(sorted(groups, key=lambda g: (g[0]["z_in"], g[0]["x_in"])), start=1):
        lengths = [float(m.group(1)) for t in group if (m := TREAD_LENGTH.search(t.get("description", "")))]
        middle = group[len(group) // 2]
        common = dict(subject=f"stair:{index}", source=_source(file, middle), location=_point(middle))
        facts.append(Fact(property="tread_count", value=float(len(group)), **common))
        facts.append(Fact(property="name", value=middle["name"], **common))
        facts.append(Fact(property="deck", value=deck_name(group[0]["z_in"]), **common))
        if lengths:
            facts.append(Fact(property="tread_length", value=min(lengths), unit="in", **common))
    return facts


def raft_facts(file: str, parts: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    for index, part in enumerate(p for p in parts if RAFT_RACK.search(p["name"])):
        kind = RAFT_RACK.search(part["name"]).group(1).upper()
        common = dict(subject=f"raft_rack:{index}", source=_source(file, part), location=_point(part))
        facts.append(Fact(property="raft_count", value=2.0 if kind == "DOUBLE" else 1.0, **common))
        # Model axes: positive y is port.
        facts.append(Fact(property="side", value="port" if part["y_in"] > 0 else "starboard", **common))
    return facts


def nav_light_facts(file: str, parts: list[dict]) -> list[Fact]:
    facts: list[Fact] = []
    for index, part in enumerate(p for p in parts if NAV_LIGHT.search(p.get("description", ""))):
        facts.append(Fact(subject=f"nav_light:{index}", property="height_above_baseline",
                          value=round(part["z_in"] / INCHES_PER_METRE, 2), unit="m",
                          source=_source(file, part), location=_point(part)))
    return facts


def facts_from_parts(file: str, parts: list[dict]) -> list[Fact]:
    return (door_facts(file, parts) + stair_facts(file, parts)
            + raft_facts(file, parts) + nav_light_facts(file, parts))
