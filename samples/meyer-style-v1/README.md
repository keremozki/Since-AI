# meyer-style-v1: synthetic cruise-ship design package

SYNTHETIC TEST DATA: not a real ship. Ship "SYN-1 (synthetic cruise ship)", yard hull S-701, invented yard. Every PDF, the xlsx and the IFC carry the marking. The two CSV files cannot (a comment row would break CSV parsers), so treat them as marked by this README.

The package imitates a yard design set (outline spec, GA drawings in several forms, schedules, IFC model, evacuation analysis) with exact ground truth in `truth.json`. It is meant to test reading and checking, so it holds planted errors, conflicts, gaps and traps.

## Files

| File | What it is | Text layer |
|---|---|---|
| `spec.pdf` | SYN-SPEC-001 rev 2, outline specification, A4, 2 pages, vector | yes |
| `ga-deck5-revA.pdf` | SYN-GA-105 rev A, GA deck 5 (MVZ 3), FR 100 to FR 160, A3 landscape, vector | yes |
| `ga-deck5-revB.pdf` | Rev B: stair B widened to 1000 mm, revision cloud, revision row B | yes |
| `ga-deck5-revA-stroked.pdf` | Rev A with every character drawn as single-stroke line paths (like a CAD plot) | no |
| `ga-deck5-revA-scan.pdf` / `.png` | Rev A rasterized at 150 dpi, grey, rotated 0.4 degrees, blur and noise; PDF is image-only | no |
| `door-schedule.xlsx` | Sheet "DOOR SCHEDULE DECK 5": title row 1, note row 2, header row 3, doors in rows 4 to 15 | n/a |
| `door-schedule.csv` | Same table, header in row 1 | n/a |
| `stair-schedule.csv` | Stairs A, B, C with rev A values (B = 850) | n/a |
| `model.ifc` | IFC4, mm: 12 IfcDoor (property set `SYN_DoorData`) and 3 IfcStairFlight (`SYN_EscapeData`) | n/a |
| `evacuation-analysis-EA-101.pdf` | EA-101 rev 1, simplified method MSC.1/Circ.1533 | yes |
| `truth.json` | Ground truth: ship values, per-file facts, planted items, expected check results | n/a |

The GA is drawn to scale at 1:200 (frame spacing 800 mm is 4 mm on paper, 11.339 pt) while its title block says `SCALE 1:100`.

## Ship values (truth)

Passenger ship, international voyages (not short), flag Malta. Contract 2025-03-01, keel 2027-02-15, delivery 2029-05-30. LOA 299.80 m (spec), LPP 271.00 m, breadth moulded 37.00 m, greatest 37.40 m, depth 21.50 m, draught 8.40 m, GT 141,500, frame spacing 800 mm, 7 main vertical zones. Passengers 3,300, crew 1,450, persons on board 4,750. Lifeboats 7 x 350 = 2,450 per side. 16 davit-launched liferafts, no capacity stated. EA-101: R+T 38.0 min, E+L 30.0 min, total 67.5 min, governing Case 1 (night).

## Planted items

| ID | Kind | What | Expected |
|---|---|---|---|
| P-LOA | conflict | Spec LOA 299.80 m, GA particulars box 300.10 m | consistency: conflict |
| P-RAFT-CAP | gap | 16 liferafts, no capacity anywhere | liferaft_capacity: cant_tell |
| P-STAIR-B | fail | Rev A stair B 850 mm for 95 persons, FSS needs 950 mm; rev B says 1000 mm | rev A fail, rev B GA pass |
| P-STAIR-C | conflict | Stair C 1000 mm in GA and schedule, 950 mm in the IFC | conflict |
| P-DOOR-DEPTH | fail | Door 5104: 900 mm clear, 700 mm opening depth, needs 915 mm | fail |
| P-DOOR-800 | fail | Door 5107: 800 mm, under 815 mm | fail |
| P-DOOR-MISSING | gap | Door 5108: clear width blank (schedule), absent (IFC), no dimension on the GA | cant_tell |
| P-DOOR-5110 | conflict | Door 5110: 1000 mm in schedule and GA, 900 mm in the IFC | conflict |
| P-DOOR-DEPTH-UNKNOWN | gap | Door 5112: 880 mm clear, depth blank/absent, so the limit (815 or 915) is unknown | cant_tell |
| P-SCALE | trap | Title block `SCALE 1:100`, sheet really drawn at 1:200 | scale_check: conflict |
| P-IFC-OVERALL | trap | `IfcDoor.OverallWidth` is clear + 100 mm, not the clear width | do not use it |
| P-REVB-STALE | conflict | Rev B GA shows stair B 1000 mm, schedule and IFC still hold 850 mm | only in a mixed rev B set |

Other expected results: doors 5101, 5102, 5103 (815 exactly), 5105 (920 against 915), 5109 and 5111 pass; 5106 (crew store, not on an accessible route) is not applicable; stair A passes (1200 against 1100); both lifeboat sides pass (2,450 against 2,375); evacuation time passes (67.5 against 80 min, more than 3 MVZ); the evacuation analysis exists.

## truth.json

- `ship`: every value with its unit, plus lifeboats, liferafts, evacuation.
- `files`: file, kind, text_layer, doc_no, rev, what it holds.
- `facts`: every value as stated in each file: subject, property, value, unit, file, page or sheet and cell, where, note. `value: null` means a blank cell or an absent property. Subjects: `ship`, `door-number:5101`, `stair:A`, `lifeboats:port`, `liferafts`, `evacuation`, `evacuation:case2` (non-governing), `deck:5`, `drawing:SYN-GA-105`. The IFC facts also list `ifc_overall_width`.
- `planted`: id, kind, check, subject, property, detail, files.
- `expected`: check, subject, status (pass, fail, conflict, cant_tell, not_applicable), why, and where it matters a `scope` or `files`.
- `assumed_rules`: the limits behind the expected statuses (815 mm doors, 915 mm if the opening is deeper than 610 mm, FSS 900 mm + 10 mm per person above 90, 50% lifeboats per side, 80 min when more than 3 MVZ).

## Notes for whoever reads these files

- The GA states clear widths beside the door swings (all doors except 5108) and persons served as "95 P". It states no opening depths; deep openings (5104, 5105) show as thick jambs only.
- Door and stair numbers on the GA: cabin doors other than 5101 to 5112 are plain openings and are not in any schedule (note 5 on the sheet).
- The scan is 150 dpi; the smallest labels are about 9 pixels high. Read it with OCR or vision, not text extraction.
- The EA-101 report does not print the 80 min limit. The checker must get it from the rules and the MVZ count.
- Output is deterministic (seed 701, fixed dates, fixed GUIDs and PDF IDs): regenerating gives identical bytes.

## Regenerate

From the repo root:

```
.venv/bin/python -I tools/synthetic/make_package.py [outdir]
```

The default outdir is `samples/meyer-style-v1`. This README is hand-written and is not touched by the generator. Tests: `cd backend && env -u ANTHROPIC_API_KEY ../.venv/bin/python -m pytest -q tests/test_synthetic_package.py`.
