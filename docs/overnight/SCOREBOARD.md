# Scoreboard: synthetic package meyer-style-v1

Made 2026-11-07 14:35 with AI mode offline: 25 recorded AI answers replayed, 0 AI request(s) waiting. No AI was called.

The package is synthetic and team-made: this is a regression and reading test, not a validation on real Meyer data. A false pass here means a pass where truth.json says anything else.

## 1. Reading

| File | Kind | Stated | Right | Wrong at A/B | Wrong at C/D | Missed | AI waiting |
|---|---|---|---|---|---|---|---|
| spec.pdf | outline specification | 26 | 18 | 0 | 0 | 8 | 0 |
| ga-deck5-revA.pdf | general arrangement drawing | 26 | 20 | 0 | 0 | 6 | 0 |
| ga-deck5-revB.pdf | general arrangement drawing | 26 | 20 | 0 | 0 | 6 | 0 |
| ga-deck5-revA-stroked.pdf | general arrangement drawing (stroked text) | 26 | 18 | 0 | 0 | 8 | 0 |
| ga-deck5-revA-scan.pdf | general arrangement scan (image-only PDF) | 26 | 0 | 0 | 0 | 26 | 0 |
| ga-deck5-revA-scan.png | general arrangement scan (PNG) | 26 | 0 | 0 | 0 | 26 | 0 |
| door-schedule.xlsx | door schedule | 34 | 34 | 0 | 0 | 0 | 0 |
| door-schedule.csv | door schedule (csv) | 34 | 34 | 0 | 0 | 0 | 0 |
| stair-schedule.csv | stair schedule (csv) | 9 | 6 | 0 | 0 | 3 | 0 |
| model.ifc | IFC4 model | 51 | 51 | 0 | 0 | 0 | 0 |
| evacuation-analysis-EA-101.pdf | evacuation analysis | 12 | 5 | 0 | 0 | 7 | 0 |
| **All files** | | 296 | 206 | 0 | 0 | 90 | |

Wrong at A/B is a misreading that could back a verdict, so it must stay at zero. Wrong at C/D was caught by the second reading or the tier rules and can't back any result.

## 2. Checking

Rev A set: 40 of 41 expected results matched; false passes: 0. With rev B added: 39 of 40; false passes: 0.

The engineer answered 4 ship card question(s): length_overall_m = 299.8 m, propulsion = power_driven, breadth_greatest_m = 37.4 m, voyage = international.

| Check | Subject | Expected | Got |
|---|---|---|---|
| door_clear_width | door-number:5101 | pass | pass |
| door_clear_width | door-number:5102 | pass | pass |
| door_clear_width | door-number:5103 | pass | pass |
| door_clear_width | door-number:5104 | fail | fail |
| door_clear_width | door-number:5105 | pass | pass |
| door_clear_width | door-number:5106 | not_applicable | not_applicable |
| door_clear_width | door-number:5107 | fail | fail |
| door_clear_width | door-number:5108 | cant_tell | cant_tell |
| door_clear_width | door-number:5109 | pass | pass |
| door_clear_width | door-number:5110 | conflict | conflict |
| door_clear_width | door-number:5111 | pass | pass |
| door_clear_width | door-number:5112 | cant_tell | cant_tell |
| stair_width | stair:A | pass | pass |
| stair_width | stair:B | fail | fail |
| stair_width | stair:C | conflict | conflict |
| lifeboat_capacity | lifeboats:port | pass | pass |
| lifeboat_capacity | lifeboats:starboard | pass | pass |
| liferaft_capacity | liferafts | cant_tell | cant_tell |
| evacuation_time | evacuation | pass | cant_tell (differs) |
| evacuation_analysis_exists | evacuation | pass | pass |
| consistency | ship.length_overall | conflict | conflict |
| consistency | stair:C | conflict | conflict |
| consistency | door-number:5110 | conflict | conflict |
| consistency | stair:B | pass | pass |
| consistency | stair:A | pass | pass |
| consistency | ship.persons_on_board | pass | pass |
| consistency | ship.main_vertical_zones | pass | pass |
| consistency | ship.length_between_perpendiculars | pass | pass |
| consistency | ship.beam | pass | pass |
| consistency | ship.frame_spacing | pass | pass |
| scale_check | drawing:SYN-GA-105 | conflict | conflict |
| consistency | door-number:5101 | pass | pass |
| consistency | door-number:5102 | pass | pass |
| consistency | door-number:5103 | pass | pass |
| consistency | door-number:5104 | pass | pass |
| consistency | door-number:5105 | pass | pass |
| consistency | door-number:5106 | pass | pass |
| consistency | door-number:5107 | pass | pass |
| consistency | door-number:5109 | pass | pass |
| consistency | door-number:5111 | pass | pass |
| consistency | door-number:5112 | pass | pass |

## 3. Planted errors

| Id | Kind | Caught | How |
|---|---|---|---|
| P-LOA | conflict | yes | consistency ship.length_overall: conflict (expected conflict); consistency ship.persons_on_board: pass (expected pass); consistency ship.main_vertical_zones: pass (expected pass); consistency ship.length_between_perpendiculars: pass (expected pass); consistency ship.beam: pass (expected pass); consistency ship.frame_spacing: pass (expected pass) |
| P-RAFT-CAP | gap | yes | liferaft_capacity liferafts: cant_tell (expected cant_tell) |
| P-STAIR-B | fail | yes | stair_width stair:B: fail (expected fail) |
| P-STAIR-C | conflict | yes | stair_width stair:C: conflict (expected conflict); consistency stair:C: conflict (expected conflict) |
| P-DOOR-DEPTH | fail | yes | door_clear_width door-number:5104: fail (expected fail) |
| P-DOOR-800 | fail | yes | door_clear_width door-number:5107: fail (expected fail) |
| P-DOOR-MISSING | gap | yes | door_clear_width door-number:5108: cant_tell (expected cant_tell) |
| P-DOOR-5110 | conflict | yes | door_clear_width door-number:5110: conflict (expected conflict); consistency door-number:5110: conflict (expected conflict) |
| P-DOOR-DEPTH-UNKNOWN | gap | yes | door_clear_width door-number:5112: cant_tell (expected cant_tell) |
| P-SCALE | trap | yes | scale_check drawing:SYN-GA-105: conflict (expected conflict) |
| P-IFC-OVERALL | trap | yes | doors 5104 and 5107 not passed |
| P-REVB-STALE | conflict | yes | consistency stair:B: conflict (expected conflict) |

## 4. RCRV (real 3D model data)

```
{
 "hand_checked": {
  "total": 28,
  "correct": 28,
  "false_passes": 0,
  "false_fails": 0,
  "not_found": []
 },
 "seeded_door_faults": {
  "faults": 81,
  "caught": 81,
  "missed": 0,
  "changes_outside_the_rule": 0
 },
 "seeded_stair_faults": {
  "faults": 112,
  "caught": 112,
  "missed": 0,
  "changes_outside_the_rule": 0
 },
 "missing_data": {
  "checks": 94,
  "false_passes": 0
 }
}
```
