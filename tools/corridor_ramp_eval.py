"""Score the code reader and the corridor and ramp checks on a SYNTHETIC corridor/ramp set.

    .venv/Scripts/python tools/corridor_ramp_eval.py data/synthetic/SYNTHETIC_corridor_ramp_seed101 --tag first_run

Per object in the truth files: was it found (any reader fact for it), missed, read wrong; what the
check said vs the truth; false PASS (a violating object reported as PASS); coverage (share of objects
that got PASS or FAIL). Violations are split into caught (FAIL), sent to review (CAN'T TELL or CONFLICT),
missed (no result) and false PASS. Writes data/reports/corridor_ramp_SYNTHETIC_<set>_<tag>.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))

from app.confidence import ConfidenceGate  # noqa: E402
from app.drawing import read_pdf  # noqa: E402
from app.engine import run  # noqa: E402
from app.models import ShipProfile  # noqa: E402
from app.rules import load_rules  # noqa: E402
from app.store import FactStore  # noqa: E402
from validate_data import norm  # noqa: E402

VALUE_PROPS = {"clear_width", "rise", "run", "slope_run_per_rise"}


def evaluate(folder: Path) -> dict:
    rules = load_rules(ROOT / "rules" / "rules.yaml", ROOT / "docs" / "rules")
    t = Counter()
    rows = []
    for truth_path in sorted(folder.glob("*.truth.json")):
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        pdf = truth_path.with_name(truth["file"])
        read = read_pdf(pdf.read_bytes(), pdf.name)
        p = truth["profile"]
        profile = ShipProfile(id="truth", name=truth["file"], ship_type=p["ship_type"], passengers=p["passengers"],
                              flag=p.get("flag", ""))
        with tempfile.TemporaryDirectory() as tmp:
            result = run(FactStore(read.facts), rules, profile, gate=ConfidenceGate(Path(tmp)))
        got = {(f.rule_id, f.subject): f for f in result.findings}
        want = {norm(f) for f in truth["facts"]}
        read_values = [f.model_dump(mode="json") for f in read.facts if f.property in VALUE_PROPS]
        for e in truth["expected"]:
            subject, kind = e["subject"], e["subject"].split(":")[0]
            mine = [f for f in read.facts if f.subject == subject]
            values = [norm(f) for f in read_values if f["subject"] == subject]
            truth_values = {w for w in want if w[0] == subject}
            finding = got.get((e["rule_id"], subject))
            status = finding.status.value if finding else "no result"
            wrong = [v for v in values if v not in truth_values]
            row = {"file": truth["file"], "subject": subject, "case": e["case"], "style": e.get("style"),
                   "expected": e["expected"], "got": status, "violation": e["violation"],
                   "found": bool(mine), "wrong_readings": wrong, "missing_readings": sorted(truth_values - set(values))}
            rows.append(row)
            t[f"{kind}:objects"] += 1
            t[f"{kind}:found"] += bool(mine)
            t[f"{kind}:missed"] += not mine
            t[f"{kind}:wrong_reading"] += bool(wrong)
            t[f"{kind}:match"] += status == e["expected"]
            t[f"{kind}:evaluated"] += status in ("pass", "fail")
            t[f"{kind}:got_{status}"] += 1
            if e["violation"]:
                t[f"{kind}:violations"] += 1
                bucket = {"fail": "caught", "pass": "FALSE_PASS", "no result": "missed"}.get(status, "sent_to_review")
                t[f"{kind}:violations_{bucket}"] += 1
            if status == "fail" and not e["violation"]:
                t[f"{kind}:false_fail"] += 1
            if e["case"].startswith("unreadable"):
                t[f"{kind}:unreadable"] += 1
                t[f"{kind}:unreadable_cant_tell"] += status == "cant_tell"
    summary = {}
    for kind in ("corridor", "ramp"):
        n = t[f"{kind}:objects"]
        summary[kind] = {k.split(":", 1)[1]: v for k, v in sorted(t.items()) if k.startswith(kind + ":")}
        summary[kind]["coverage"] = round(t[f"{kind}:evaluated"] / n, 3) if n else None
        summary[kind]["status_accuracy"] = round(t[f"{kind}:match"] / n, 3) if n else None
    return {"SYNTHETIC": True, "set": folder.name, "summary": summary, "rows": rows}


def print_summary(report: dict) -> None:
    print(f"SYNTHETIC set {report['set']}")
    for kind, s in report["summary"].items():
        v = s.get("violations", 0)
        print(f"  {kind:8s} objects {s.get('objects', 0)}, found {s.get('found', 0)}, missed {s.get('missed', 0)}, "
              f"wrong readings {s.get('wrong_reading', 0)}, status right {s.get('match', 0)} "
              f"({s['status_accuracy']:.0%}), coverage {s['coverage']:.0%}")
        print(f"  {'':8s} violations {v}: caught {s.get('violations_caught', 0)}, sent to review "
              f"{s.get('violations_sent_to_review', 0)}, missed {s.get('violations_missed', 0)}, "
              f"FALSE PASS {s.get('violations_FALSE_PASS', 0)}; false fails {s.get('false_fail', 0)}; "
              f"unreadable -> can't tell {s.get('unreadable_cant_tell', 0)}/{s.get('unreadable', 0)}")
    bad = [r for r in report["rows"] if r["got"] != r["expected"]]
    for r in bad:
        print(f"    {r['file']} {r['subject']} [{r['case']}, {r['style']}]: expected {r['expected']}, got {r['got']}"
              + (f", wrong {r['wrong_readings']}" if r["wrong_readings"] else ""))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--tag", default="run")
    args = parser.parse_args()
    report = evaluate(args.folder)
    report["tag"] = args.tag
    out = ROOT / "data" / "reports" / f"corridor_ramp_SYNTHETIC_{args.folder.name}_{args.tag}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print_summary(report)
    print(f"Report: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
