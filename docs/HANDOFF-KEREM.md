# Handoff: what is on `ediz-ML` and how to bring it into the web app

Written 7 Nov 2026 for Kerem (and his Claude). Branch `ediz-ML`, last commit listed below.

## 0. Why your Claude thinks "it only scans doors"

`origin/ediz-ML` on GitHub stopped at **274d934 (04:17)**. At that point the code PDF reader only read
door tags and door widths. Everything below was committed locally after 04:17 and is only on GitHub once
the branch is pushed. Check with `git log origin/ediz-ML --oneline -12` after fetching.

| Commit | What |
|---|---|
| 092c821, 274d934 (04:16-04:17, already on GitHub) | Confidence model, code PDF reader (doors), data validation |
| a0e7550 | Engineer review loop: review queue, feedback, undo, lessons, learning tool |
| fbc8292 | Corridor width (PVAG V403.5.1) and ramp slope (PVAG V405.2) checks |
| 5ebf699 | SYNTHETIC corridor/ramp test set (seed 101), scorer, fresh first-run result |
| 6c15ca6 | Code reader reads corridor widths and ramp slopes; 1:12 rounding fix |
| 86ea966 | Held-out SYNTHETIC set (seed 202) and tests |
| c1f2940 | Offline demo set: one PDF per result type, works with no API key |
| 9580a6c | Error handling: clear messages and HTTP codes for every bad input |
| 67b05cf | `docs/PITCH-NOTES.md` |
| d14d43b | Missing-value CAN'T TELL now names the label, page and reason |

Tests: 232 pass (`cd backend; ..\.venv\Scripts\python -m pytest -q`).

## 1. What the backend checks now (8 rules, `rules/rules.yaml`)

| Rule | Check | Reads from |
|---|---|---|
| PVAG V404.2.3 door clear width, 32 in | `door_clear_width` | 3D model, drawings, chat |
| PVAG V403.5.1 corridor width, 36 in (32-36 in = CAN'T TELL, an exception may apply) | `corridor_width` | drawings, chat (**new**) |
| PVAG V405.2 ramp slope, max 1:12 | `ramp_slope` | drawings, chat (**new**) |
| FSS Code ch. 13 stair width | `stair_width` | 3D model |
| MSC.1/Circ.1533 evacuation time | `evacuation_time` | documents, chat |
| SOLAS III liferaft capacity | `raft_capacity` | 3D model + persons on board |
| SOLAS V/22 bridge visibility | `bridge_visibility` | 3D model, measure tool |
| COLREG Annex I masthead height | `masthead_height` | 3D model |

Plus the consistency check (two sources disagree → CONFLICT) and a new INPUT-CHECK (an unusable value,
e.g. a width of 0 or an unknown unit → CAN'T TELL with the reason, never a made-up FAIL).

Pass/fail is always plain Python in `checks.py`. The AI only reads and explains.

## 2. Drawing reader (`backend/app/drawing.py`, new file)

Vector PDFs are read with pymupdf, no API key, no cost. It reads:

- door tags (`D204`) with the width next to them or in a door schedule;
- corridor labels (`CORRIDOR C2-4`) with `CLEAR WIDTH ...` on the same line, a nearby line, or a corridor schedule;
- ramp labels (`RAMP R1`) with `SLOPE 1:14`, or `RISE ... RUN ...` with units.

Units: in, ft-in, mm, m, and bare numbers only when the sheet has a unit note. Rotated value text is never used.
A label with no usable value becomes a `shown_on` fact, so the check says CAN'T TELL with the reason, e.g.:

> Clear width not readable: label 'CORRIDOR C2-4  CLEAR WIDTH 1065' is on page 1, but the width on that line
> has no unit, and the sheet has no unit note.

Scanned PDFs and images still go to the AI reader (needs `ANTHROPIC_API_KEY`).

## 3. API changes the UI needs to know about

New routes (all tested in `backend/tests/test_routes_smoke.py`):

| Route | Purpose |
|---|---|
| `GET /api/confidence` | Confidence model status: `mode` (cold_start / model), label counts, recent answers, lessons |
| `GET /api/review-queue/{profile_id}?limit=5` | FAILs to review next, most useful for learning first, each with `why_now` |
| `GET /api/evidence?file=&locator=` | PNG crop of the drawing where a value was read |
| `POST /api/feedback` | Engineer answer: `{profile, rule_id, subject, decision: accept/reject/unsure, corrected_value?, corrected_unit?}`; the check reruns |
| `DELETE /api/feedback?profile=&key=` | Undo an answer |
| `POST /api/inputs/model/restore` | Bring back the removed 3D model |

New `Finding` fields (types already in our `frontend/src/api.ts`): `original_status`, `p_real`, `gate_note`,
`reviewable`, `read_quote`, `read_file`, `read_locator`. Show `read_quote` + the `/api/evidence` crop next to a
finding so the engineer sees exactly which text caused it. `measured` now carries the reason for CAN'T TELL.

Error codes: 400 bad input, 413 file over 50 MB, 409 finding already answered (message says "Undo"),
422 unknown decision, 503 no API key / API down / budget used up. Every error has a plain `detail` message.
Upload refuses empty, damaged, password-protected, renamed-text and over-200-page files with a clear reason.

## 4. Merging into `main` (not done by us)

A trial merge (`git merge-tree origin/main ediz-ML`, nothing changed) shows 3 conflicts:

- `backend/app/checks.py`: keep both. Your `PLAIN_NAMES` / `describe_fact` / `_plain` and the new stair
  and raft wording, plus our `FLOAT_SLACK`, `_not_written`, corridor/ramp checks and `unusable_facts`.
  Add `"rise"`, `"run"`, `"slope_run_per_rise"` to `PLAIN_NAMES`, and let `describe_fact` name
  `corridor:` / `ramp:` subjects like it does doors.
- `backend/app/main.py`: keep both. Your streamed model import (`Request`, `run_in_threadpool`) and
  `describe_fact`, plus our new routes, `parse_pages`, size cap and error mapping.
- `frontend/src/App.tsx`: you split App into `Results.tsx`, `FindingDetail.tsx`, etc. Our review UI was
  added to the old single `App.tsx` (commit a0e7550). Take your version, then port our parts:
  review queue panel, Accept / Misread / Unsure buttons with a corrected value field, Undo, the
  evidence crop, the confidence status line. `api.ts` and `styles.css` merged cleanly.

Run the full test suite after the merge.

## 5. Try it offline

`data/demo_offline_SYNTHETIC/`: `SYNTHETIC_demo_1_PASS.pdf`, `_2_FAIL`, `_3_CANT_TELL`, `_4_CONFLICT`.
Profile **passenger-test**, upload each, no key needed. The demo script is in `docs/PITCH-NOTES.md` section 6.

## 6. Honest limits

- All strong numbers are on SYNTHETIC drawings we generated ourselves (0 false PASS on 794 objects).
- Real drawings: one hand-labelled value measured. AI reader accuracy not measured (no key).
- A ramp 1:N slope can't yet be corrected in the review form (it asks for a unit).
- A corrupted `ship-data/*.json` still stops the app at startup.
