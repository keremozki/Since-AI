"""Measure how well the checks catch faults on the real ship data, and write the scoreboard.

Runs without any AI, so it costs nothing:
1. Hand-checked set: expected door results, typed by hand from the model's description text.
2. Seeded faults: each door and stair tread is made too small in turn. The checks must catch
   exactly that change, and nothing else may move.
3. Missing data: every stated dimension is removed. No dimension check may pass.

Usage: python tools/accuracy_report.py        (writes ship-data/accuracy.json)
"""
from __future__ import annotations

import copy
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.engine import run  # noqa: E402
from app.models import Status  # noqa: E402
from app.parts import facts_from_parts, load_parts  # noqa: E402
from app.profiles import PASSENGER_TEST  # noqa: E402
from app.rules import load_rules  # noqa: E402
from app.store import FactStore  # noqa: E402

DOOR_RULE, STAIR_RULE = "PVAG-V404.2.3", "FSS-13-STAIR"
# Door number: expected result against 32 in, typed from the model's description text.
HAND_CHECKED = {
    "212": "pass", "317": "pass", "504": "pass", "509": "fail", "310": "fail", "506": "pass", "510": "pass",
    "118": "pass", "511": "pass", "542": "pass", "117": "pass", "540": "pass", "502": "pass", "518": "pass",
    "116": "pass", "210": "fail", "302": "fail", "305": "fail", "217": "pass", "225": "fail", "326": "fail",
    "503": "pass", "507": "pass", "204": "pass", "224": "pass", "301": "pass", "501": "pass", "516": "fail",
}
OPENING = re.compile(r"((?:CLEAR\w*|LIGHT)\s+OPEN\w*\s*)[\d.]+", re.I)
TREAD_LENGTH = re.compile(r'\d+(\s*"\s*L)', re.I)
# Anything but a pass counts as caught. A too-narrow stairway door is "can't tell", because PVAG
# defers its limit to the administrative authority.
CAUGHT = {Status.FAIL, Status.CONFLICT, Status.CANT_TELL}


def findings_for(parts, source, rules):
    return run(FactStore(facts_from_parts(source, parts)), rules, PASSENGER_TEST).findings


def snapshot(findings):
    return {(f.rule_id, f.subject): (f.status, f.measured) for f in findings}


def changed_keys(base, after):
    return [key for key in after.keys() | base.keys() if base.get(key) != after.get(key)]


def hand_checked(baseline) -> dict:
    got = {f.label.removeprefix("Door "): f.status.value for f in baseline if f.rule_id == DOOR_RULE}
    pairs = {number: (expected, got.get(number)) for number, expected in HAND_CHECKED.items()}
    return {
        "total": len(pairs),
        "correct": sum(expected == actual for expected, actual in pairs.values()),
        "false_passes": sum(expected == "fail" and actual == "pass" for expected, actual in pairs.values()),
        "false_fails": sum(expected == "pass" and actual == "fail" for expected, actual in pairs.values()),
        "not_found": sorted(number for number, (_, actual) in pairs.items() if actual is None),
    }


def seed(parts, source, rules, base, rule_id, is_target, mutate) -> dict:
    faults = caught = missed = spread = 0
    for index, part in enumerate(parts):
        if not is_target(part):
            continue
        changed = copy.deepcopy(parts)
        changed[index]["description"] = mutate(part["description"])
        after = snapshot(findings_for(changed, source, rules))
        keys = changed_keys(base, after)
        faults += 1
        spread += sum(key[0] != rule_id for key in keys)
        on_rule = [key for key in keys if key[0] == rule_id]
        if on_rule and all(after[key][0] in CAUGHT for key in on_rule if key in after):
            caught += 1
        else:
            missed += 1
    return {"faults": faults, "caught": caught, "missed": missed, "changes_outside_the_rule": spread}


def door_target(part) -> bool:
    return (re.search(r"\bDOOR\b", part["name"]) is not None and OPENING.search(part.get("description", "")) is not None
            and not part["name"].startswith(("ACCESS DOOR", "ROLL UP")))


def make_door_narrow(description: str) -> str:
    too_narrow = "20" if description.upper().lstrip().startswith("CLEAR") else "500"
    return OPENING.sub(lambda m: m.group(1) + too_narrow, description, count=1)


def tread_target(part) -> bool:
    return re.search(r"STAIR\s+TREADS?", part["name"]) is not None and TREAD_LENGTH.search(part.get("description", "")) is not None


def make_tread_short(description: str) -> str:
    return TREAD_LENGTH.sub(lambda m: "20" + m.group(1), description, count=1)


def missing_data(parts, source, rules) -> dict:
    stripped = copy.deepcopy(parts)
    for part in stripped:
        part.pop("description", None)
    findings = findings_for(stripped, source, rules)
    return {"checks": len(findings), "false_passes": sum(f.status == Status.PASS for f in findings)}


def main() -> None:
    source, parts = load_parts(ROOT / "ship-data" / "parts.json")
    rules = load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
    baseline = findings_for(parts, source, rules)
    base = snapshot(baseline)
    report = {
        "hand_checked": hand_checked(baseline),
        "seeded_door_faults": seed(parts, source, rules, base, DOOR_RULE, door_target, make_door_narrow),
        "seeded_stair_faults": seed(parts, source, rules, base, STAIR_RULE, tread_target, make_tread_short),
        "missing_data": missing_data(parts, source, rules),
    }
    (ROOT / "ship-data" / "accuracy.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
