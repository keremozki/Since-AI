"""Score the whole product on the synthetic package, against its truth file, with no AI calls.

    python tools/scoreboard.py            # writes ship-data/scoreboard.json and docs/overnight/SCOREBOARD.md

AI steps replay answers recorded in ship-data/ai (offline mode); a step with no answer is counted as waiting,
never guessed. The truth file is read only here, to score: no reader, check or AI answerer ever sees it.

1. Reading: every value each file states (truth.json facts) against what the app read from that file.
   A wrong value at tier A or B could back a verdict, so it is the number that must stay at zero.
2. Checking: the app's results against the expected results, for the rev A set and then with rev B added.
   The engineer answers only the ship card questions the app asks, with the ship's real values.
3. Planted errors: each one caught or missed. 4. False passes: a pass the truth says is not a pass.
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from app.ai_gateway import OfflineAI  # noqa: E402
from app.main import AppState, create_app  # noqa: E402
from app.reading.pipeline import read_upload  # noqa: E402
from app.units import to_mm  # noqa: E402

PACKAGE = ROOT / "samples" / "meyer-style-v1"
AI_STORE = Path(os.environ.get("SCOREBOARD_AI_STORE", ROOT / "ship-data" / "ai"))
OUT_JSON = ROOT / "ship-data" / "scoreboard.json"
OUT_MD = ROOT / "docs" / "overnight" / "SCOREBOARD.md"
PROFILE = "card"

CHECK_RULES = {"door_clear_width": "PVAG-V404.2.3", "stair_width": "FSS-13-STAIR", "lifeboat_capacity": "SOLAS-III-21-LIFEBOATS",
               "liferaft_capacity": "SOLAS-III-21-LIFERAFTS", "evacuation_time": "MSC.1-CIRC.1533",
               "evacuation_analysis_exists": "SOLAS-II-2-13.3.2.7", "consistency": "CROSS-CHECK", "scale_check": "SCALE-CHECK"}
# Truth names that differ from the app's fact names.
PROPERTY_ALIASES = {"ifc_overall_width": "opening_width"}
REV_A_SET = ["spec.pdf", "ga-deck5-revA.pdf", "door-schedule.xlsx", "stair-schedule.csv", "model.ifc",
             "evacuation-analysis-EA-101.pdf"]
# Card fields an engineer knows about their own ship, from the truth file or plain fact (a cruise ship is power-driven).
CARD_FROM_TRUTH = {"ship_type": "ship_type", "flag": "flag", "contract_date": "contract_date", "keel_date": "keel_date",
                   "delivery_date": "delivery_date", "length_overall_m": "length_overall", "beam_m": "beam",
                   "breadth_greatest_m": "breadth_greatest", "passengers": "passengers", "crew": "crew",
                   "persons_on_board": "persons_on_board", "gross_tonnage": "gross_tonnage",
                   "main_vertical_zones": "main_vertical_zones"}
ENGINEER_KNOWS = {"voyage": "international", "propulsion": "power_driven", "overnight_passengers": None}


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def same_value(truth: dict, fact) -> bool:
    if truth["property"] in ("ship_type", "flag"):
        # The fact keeps the text as written ("Passenger ship"); the ship card maps it to a type. Score the mapping.
        from app.basis.shipcard import normalize_choice
        mapped = normalize_choice(truth["property"], fact.value) if truth["property"] == "ship_type" else fact.value
        return str(mapped).strip().lower() == str(truth["value"]).strip().lower()
    if truth["unit"] in ("mm", "m", "cm", "in", "ft") and fact.unit in ("mm", "m", "cm", "in", "ft"):
        return _num(fact.value) is not None and abs(to_mm(float(truth["value"]), truth["unit"]) - to_mm(float(fact.value), fact.unit)) < 0.5
    if _num(truth["value"]) is not None and _num(fact.value) is not None:
        return math.isclose(float(truth["value"]), float(fact.value), rel_tol=1e-9, abs_tol=1e-9)
    norm = lambda v: "".join(ch for ch in str(v).lower() if ch.isalnum())  # noqa: E731
    return norm(truth["value"]) == norm(fact.value)


def score_reading(ai, truth: dict) -> dict:
    """Per file: values read right, read wrong (by tier), missed, waiting for the AI, and values the truth doesn't have."""
    facts_by_file = defaultdict(list)
    for t in truth["facts"]:
        facts_by_file[t["file"]].append({**t, "property": PROPERTY_ALIASES.get(t["property"], t["property"])})
    out = {}
    with tempfile.TemporaryDirectory() as cache:
        for entry in truth["files"]:
            name = entry["file"]
            started = time.time()
            read = read_upload(ai, name, (PACKAGE / name).read_bytes(), cache_dir=Path(cache))
            seconds = round(time.time() - started, 1)
            got = defaultdict(list)
            for fact in read.facts:
                got[(fact.subject, fact.property)].append(fact)
            stated = [t for t in facts_by_file[name] if t["value"] is not None]
            blank = [t for t in facts_by_file[name] if t["value"] is None]
            row = Counter()
            wrong, missed, invented = [], [], []
            for t in stated:
                found = got.get((t["subject"], t["property"]), [])
                if not found:
                    row["missed"] += 1
                    missed.append(f"{t['subject']} {t['property']} = {t['value']} {t['unit']}".strip())
                    continue
                if any(same_value(t, f) for f in found):
                    row["right"] += 1
                    best = min((f for f in found if same_value(t, f)), key=lambda f: f.tier.value if f.tier else "Z")
                    row[f"right_tier_{best.tier.value if best.tier else '?'}"] += 1
                for f in found:
                    if not same_value(t, f):
                        tier = f.tier.value if f.tier else "?"
                        row[f"wrong_tier_{tier}"] += 1
                        wrong.append(f"{t['subject']} {t['property']}: truth {t['value']} {t['unit']}, read {f.value} {f.unit} (tier {tier})")
            truth_keys = {(t["subject"], t["property"]) for t in facts_by_file[name]}
            for t in blank:
                for f in got.get((t["subject"], t["property"]), []):
                    invented.append(f"{t['subject']} {t['property']}: blank in the file, read {f.value} {f.unit} (tier {f.tier.value if f.tier else '?'})")
            extra = [f"{f.subject} {f.property} = {f.value} {f.unit} (tier {f.tier.value if f.tier else '?'})"
                     for key, fs in got.items() if key not in truth_keys for f in fs]
            out[name] = {"kind": entry["kind"], "stated": len(stated), **dict(row), "wrong_values": wrong, "missed_values": missed,
                         "invented_from_blank": invented, "not_in_truth": extra, "pending_ai": len(read.pending),
                         "status": read.status, "seconds": seconds}
    return out


def _upload(api, name: str) -> dict:
    with open(PACKAGE / name, "rb") as handle:
        response = api.post("/api/upload", data={"profile": PROFILE}, files={"file": (name, handle)})
    response.raise_for_status()
    return response.json()


def _answer_card_questions(api, truth: dict) -> list[str]:
    """The engineer answers what the ship card asks, from what they know about the ship. Nothing else."""
    answered = []
    for item in api.get("/api/shipcard").json()["missing"]:
        field = item["field"]
        if field in CARD_FROM_TRUTH and CARD_FROM_TRUTH[field] in truth["ship"]:
            raw = truth["ship"][CARD_FROM_TRUTH[field]]
            value, unit = raw["value"], raw["unit"] if raw["unit"] not in ("date",) else ""
        elif ENGINEER_KNOWS.get(field) is not None:
            value, unit = ENGINEER_KNOWS[field], ""
        else:
            continue
        response = api.post("/api/shipcard/confirm", json={"field": field, "value": value, "unit": unit, "by": "scoreboard engineer"})
        if response.status_code == 200:
            answered.append(f"{field} = {value} {unit}".strip())
    return answered


def _matches(expected: dict, finding: dict) -> bool:
    rule = CHECK_RULES.get(expected["check"])
    if finding["rule_id"] != rule:
        return False
    subject = expected["subject"]
    if expected["check"] == "consistency":
        return finding["subject"] == subject or finding["subject"].startswith(subject + ".")
    return finding["subject"] == subject


def score_results(findings: list[dict], expected: list[dict], scope_ok) -> dict:
    rows, false_passes = [], []
    for e in expected:
        if not scope_ok(e):
            continue
        mine = [f for f in findings if _matches(e, f)]
        statuses = sorted({f["status"] for f in mine})
        if e["check"] == "consistency" and e["status"] == "pass":
            got = "conflict" if "conflict" in statuses else "pass"  # no conflict raised is the consistency pass
        else:
            got = statuses[0] if len(statuses) == 1 else ("missing" if not statuses else "+".join(statuses))
        held = [f["gate"] for f in mine if f.get("gate")]
        rows.append({"check": e["check"], "subject": e["subject"], "expected": e["status"], "got": got,
                     "ok": got == e["status"], "held_back": held, "why_expected": e["why"]})
        if "pass" in statuses and e["status"] != "pass" and e["check"] != "consistency":
            false_passes.append(f"{e['check']} {e['subject']}: app passed, truth says {e['status']}")
    agree = sum(r["ok"] for r in rows)
    return {"expected": len(rows), "agree": agree, "false_passes": false_passes,
            "false_fails": [f"{r['check']} {r['subject']}" for r in rows if r["got"] == "fail" and r["expected"] != "fail"],
            "rows": rows}


def scenario(ai, truth: dict) -> dict:
    with tempfile.TemporaryDirectory() as data_dir:
        state = AppState(Path(data_dir), ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules", claude=ai)
        api = TestClient(create_app(state))
        for name in REV_A_SET:
            _upload(api, name)
        before = api.get(f"/api/run/{PROFILE}").json()["result"]
        answered = _answer_card_questions(api, truth)
        rev_a = api.get(f"/api/run/{PROFILE}").json()["result"]
        basis = api.get("/api/basis").json()
        rev_a_scope = lambda e: e.get("scope") in (None, "rev A set (ga-deck5-revA*, stair-schedule.csv, model.ifc)", "rev A set")  # noqa: E731
        upload_b = _upload(api, "ga-deck5-revB.pdf")
        mixed = api.get(f"/api/run/{PROFILE}").json()["result"]
        mixed_scope = lambda e: e.get("scope") in (None, "mixed set: ga-deck5-revB.pdf with stair-schedule.csv and model.ifc")  # noqa: E731
        proof = api.get(f"/api/proof/{PROFILE}").content
        return {
            "before_engineer": {"counts": before["counts"], "summary": before["summary"]},
            "engineer_answered": answered,
            "rev_a": {"counts": rev_a["counts"], "summary": rev_a["summary"],
                      **score_results(rev_a["findings"], truth["expected"], rev_a_scope)},
            "rules_applying": {i["rule_id"]: i["status"] for i in basis["items"]},
            "rev_b_revision_report": upload_b.get("revisions", []),
            "mixed": {"counts": mixed["counts"], "summary": mixed["summary"],
                      **score_results(mixed["findings"], truth["expected"], mixed_scope)},
            "proof_bundle_bytes": len(proof),
        }


def planted_caught(truth: dict, rev_a: dict, mixed: dict) -> list[dict]:
    rows = {(r["check"], r["subject"]): r for r in rev_a["rows"]}
    rows_mixed = {(r["check"], r["subject"]): r for r in mixed["rows"]}
    out = []
    for item in truth["planted"]:
        related = [r for key, r in (rows_mixed if item["id"] == "P-REVB-STALE" else rows).items()
                   if r["subject"].split(".")[0] == item["subject"].split(".")[0] and (key[0] == item["check"] or item["check"] == "consistency")]
        if item["id"] == "P-IFC-OVERALL":
            caught = all(r["got"] != "pass" for r in rows.values() if r["subject"] in ("door-number:5104", "door-number:5107")
                         and r["check"] == "door_clear_width")
            out.append({"id": item["id"], "kind": item["kind"], "caught": caught, "how": "doors 5104 and 5107 not passed"})
            continue
        caught = any(r["ok"] for r in related) if related else False
        out.append({"id": item["id"], "kind": item["kind"], "caught": caught,
                    "how": "; ".join(f"{r['check']} {r['subject']}: {r['got']} (expected {r['expected']})" for r in related) or "no result"})
    return out


def markdown(board: dict) -> str:
    lines = ["# Scoreboard: synthetic package meyer-style-v1", "",
             f"Made {board['made']} with AI mode offline: {board['ai']['answered']} recorded AI answers replayed, "
             f"{board['ai']['pending']} AI request(s) waiting. No AI was called.", "",
             "The package is synthetic and team-made: this is a regression and reading test, not a validation on "
             "real Meyer data. A false pass here means a pass where truth.json says anything else.", "",
             "## 1. Reading", "", "| File | Kind | Stated | Right | Wrong at A/B | Wrong at C/D | Missed | AI waiting |",
             "|---|---|---|---|---|---|---|---|"]
    for name, r in board["reading"].items():
        wrong_ab = r.get("wrong_tier_A", 0) + r.get("wrong_tier_B", 0)
        wrong_cd = r.get("wrong_tier_C", 0) + r.get("wrong_tier_D", 0)
        lines.append(f"| {name} | {r['kind']} | {r['stated']} | {r.get('right', 0)} | {wrong_ab} | {wrong_cd} | {r.get('missed', 0)} | {r['pending_ai']} |")
    t = board["reading_totals"]
    lines.append(f"| **All files** | | {t['stated']} | {t['right']} | {t['wrong_ab']} | {t['wrong_cd']} | {t['missed']} | |")
    lines += ["", "Wrong at A/B is a misreading that could back a verdict, so it must stay at zero. Wrong at C/D was caught "
              "by the second reading or the tier rules and can't back any result."]
    s = board["scenario"]
    lines += ["", "## 2. Checking", "",
              f"Rev A set: {s['rev_a']['agree']} of {s['rev_a']['expected']} expected results matched; "
              f"false passes: {len(s['rev_a']['false_passes'])}. With rev B added: {s['mixed']['agree']} of {s['mixed']['expected']}; "
              f"false passes: {len(s['mixed']['false_passes'])}.", "",
              f"The engineer answered {len(s['engineer_answered'])} ship card question(s): {', '.join(s['engineer_answered']) or 'none'}.", "",
              "| Check | Subject | Expected | Got |", "|---|---|---|---|"]
    lines += [f"| {r['check']} | {r['subject']} | {r['expected']} | {r['got']}{'' if r['ok'] else ' (differs)'} |" for r in s["rev_a"]["rows"]]
    lines += ["", "## 3. Planted errors", "", "| Id | Kind | Caught | How |", "|---|---|---|---|"]
    lines += [f"| {p['id']} | {p['kind']} | {'yes' if p['caught'] else 'NO'} | {p['how']} |" for p in board["planted"]]
    lines += ["", "## 4. RCRV (real 3D model data)", "", f"```\n{json.dumps(board.get('rcrv'), indent=1)}\n```"]
    return "\n".join(lines) + "\n"


def main() -> int:
    truth = json.loads((PACKAGE / "truth.json").read_text(encoding="utf-8"))
    ai = OfflineAI(AI_STORE)
    reading = score_reading(ai, truth)
    scen = scenario(ai, truth)
    planted = planted_caught(truth, scen["rev_a"], scen["mixed"])
    rcrv_file = ROOT / "ship-data" / "accuracy.json"
    totals = {"stated": sum(r["stated"] for r in reading.values()), "right": sum(r.get("right", 0) for r in reading.values()),
              "wrong_ab": sum(r.get("wrong_tier_A", 0) + r.get("wrong_tier_B", 0) for r in reading.values()),
              "wrong_cd": sum(r.get("wrong_tier_C", 0) + r.get("wrong_tier_D", 0) for r in reading.values()),
              "missed": sum(r.get("missed", 0) for r in reading.values())}
    board = {"made": time.strftime("%Y-%m-%d %H:%M"), "reading_totals": totals, "ai": {"answered": len(list((AI_STORE / "responses").glob("*.json"))),
                                                         "pending": len(ai.status()["pending"])},
             "reading": reading, "scenario": scen, "planted": planted,
             "rcrv": json.loads(rcrv_file.read_text()) if rcrv_file.exists() else None}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(board, indent=1, default=str), encoding="utf-8")
    OUT_MD.write_text(markdown(board), encoding="utf-8")
    print(markdown(board))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
