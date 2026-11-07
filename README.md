# Dynamis SCC

Since AI Hackathon 2026, Meyer Turku challenge. A web app that checks a ship design against rules and
regulations, and tells the engineer what passes, what fails, where sources conflict, and what's missing.

**Coded tests decide every result. AI never does.** Claude reads drawings and documents into facts,
records values the engineer states in chat, and answers questions. Every fact keeps its source.

Every result is one of six:

| Result | Meaning |
|---|---|
| Pass | Tested and within the limit, on inputs that are proven (tier A or B) |
| Fail | Tested and outside the limit, with the measured value, the limit, the gap, and a fix |
| Conflict | Sources disagree, so any check that needs the value waits |
| Can't tell | A value is missing or unproven. The tool names it and asks for it. It never guesses |
| Needs review | A rule written in words: an engineer decides |
| Not applicable | The rule doesn't cover this item, and the result says why |

If everything passes, the app says no issues were found and lists which rules it covered. It never
claims that a ship is compliant overall: class and the flag state make the final call.

## What it does

- **Reads** PDF, images, XLSX, CSV, IFC, and Navisworks `.nwd`: every value keeps its file, page, box, and quote.
- **Trust levels:** only exact values (A) or values read two independent ways (B) can back a pass or a fail. One
  reading (C) or a problem (D) gives can't tell, and an engineer can confirm or correct it (`backend/app/tiers.py`).
- **Ship card and design basis:** the rules that apply come from type, size, persons, voyage, and dates, each with
  its clause (`rules/applicability.yaml`). Choose the profile "rules chosen by the ship card".
- **Learns from engineers:** a confidence model, and reader lessons from every misread (below).
- **Proof files** that `tools/verify_proof.py` checks: hashes, quotes, replay.
- **Revisions**, **what-if** and sister hulls, a **drawing scale check**, the **SOLAS V/22 sight line** on a drawing,
  and **label suggestions** an engineer approves. What-if, the sight line, and label approval are in the API only.
- **Offline AI by default:** no request leaves the machine unless `AI_MODE=api` or `record` is set. See
  `docs/ai-offline.md`.
- **Scoreboard** on a synthetic, team-made package (`samples/meyer-style-v1`): `tools/scoreboard.py`. It is a
  regression and reading test we wrote ourselves, not a validation on real Meyer data.

Details: `docs/ARCHITECTURE.md`. The overnight build plan and scoreboard are in `docs/overnight/`.

## How it works

1. **Read:** 3D model parts, 2D drawings, documents, and chat answers become one list of facts, each with a trust level.
2. **Scope:** the ship card, or a fixed profile, decides which rules apply.
3. **Test:** each rule runs as code in `backend/app/checks.py`, with limits in `rules/rules.yaml`.
4. **Hold back:** the confidence gate can move a likely misread from fail to can't tell. The tier gate holds any
   pass or fail that rests on an unconfirmed reading. Neither can create a fail or a pass.
5. **Report:** findings with their inputs and clause, markers in the 3D viewer, a text report, and a proof file.

A rule's limit counts as confirmed only when its quote appears word for word in the rule texts under `docs/rules/`.
Until then, its findings are marked provisional. The IMO excerpts and their quotes are local files for now, kept out
of this public repo because IMO bars commercial reuse of its texts. In a fresh clone those limits still run, but show
as not confirmed.

### Reading the 3D model

`tools/decode_nwd.py` reads part names, stated dimensions, and positions straight from a Navisworks
`.nwd` file, with no Navisworks install. The format was reverse engineered from the RCRV model, so other
files may not work. Engineers can also click two points in the viewer to measure a distance and save it.

## Set up

You need **Python 3.12** and Node 20 or later. Newer Python versions don't work yet, because the OCR package
doesn't install on them. The ship files aren't in this repo: get them from the Since AI App, and put the model's
`.nwd` file and the prototype viewer page somewhere local.

```bash
python3.12 -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt       # on macOS or Linux: .venv/bin/pip
npm --prefix frontend install
npm --prefix frontend run build

.venv/Scripts/python tools/decode_nwd.py path/to/model.nwd    # writes ship-data/parts.json
.venv/Scripts/python tools/extract_viewer_model.py path/to/RCRV-3D.html   # 3D geometry for the viewer
.venv/Scripts/python tools/accuracy_report.py                 # writes the scoreboard
```

Copy `.env.example` to `.env`. The AI runs offline by default (`AI_MODE=offline`): requests are saved
and replayed once answered, so nothing is sent anywhere. To use the real API, add your Anthropic API key
and set `AI_MODE=record` (or `api`). Then start the app:

```bash
cd backend
../.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000. The checks and the code readers work with no API key. With `AI_MODE=offline`, the
default, chat and the AI reading steps wait for a recorded answer (`tools/ai_offline.py`). To use the real API,
set a key and `AI_MODE=record` or `api`.

## Managing inputs

The Inputs panel lists the 3D model, each drawing or document, saved measurements, and chat answers. Each
can be removed, and the checks rerun at once. The app holds one 3D model at a time.

- Removing the 3D model takes it out completely, along with any measurements taken on it. To use it again,
  upload the `.nwd` file. `ship-data/parts.json` and the viewer geometry stay on disk, as they're set up by hand.
- Importing a different `.nwd` replaces the current model and deletes measurements taken on the old one.
- A removed drawing can be added again at no cost, because its facts are cached.
- The 3D view exists only for the RCRV. Other models are checked, but aren't shown in the viewer.

## Confidence gate (learns from engineers)

**What the engineer answers:** "Was this value read correctly?" They judge the reading, not the ship. Next to
the question they see where the value came from: the file, the place on the page, the text it was read from, and a
close-up of the drawing. The same question appears on every fail, and on any result held back by a weak reading.

| Button | What it does | Label |
|---|---|---|
| **Read correctly** | Confirms the reading, so it can back the result | 1 |
| **Misread** (the right value and unit are optional) | A right value becomes an engineer fact that replaces the reading, and the check reruns | 0 |
| **Not sure** | Nothing changes | None. Logged, never trained on |

Only fails teach the model. An answer on a held-back pass is saved and can be undone, but it isn't trained on.

Each answer is one row in `ship-data/confidence/labels.jsonl`, with who gave it and when. Any answer can
be undone; the model then refits without it. The model starts after **30 answers with at least 8 "read
correctly" and 8 "misread"**. Before that a fixed rule applies (low reading confidence gives can't tell),
and the screen says what is still needed. Misreads are rare (about 3% of fails), so the panel's "Review
next" list shows the shakiest readings first, where misreads hide.

A logistic regression (`backend/app/confidence.py`) predicts P(real fail), retrained every 5 answers, with
each version saved. A fail with P(real) under 0.7, or with low reading confidence, is shown as can't tell
with the reason. The gate never creates a fail and never touches a pass.

The model learns only from engineers' answers. `tools/simulate_labels.py` makes SIMULATED labels to test
the pipeline; the app ignores them unless `CONFIDENCE_ALLOW_SYNTHETIC=1`, and then shows a yellow
SIMULATED LABELS band and names them in every note.
`backend/app/logreg.py` is the same model written from the course formulas in NumPy (`CONFIDENCE_ENGINE=numpy`).

### The AI reader learns from misreads

The confidence model learns *when to doubt* a reading. `backend/app/lessons.py` makes the AI reader learn
*not to repeat* one: every "misread" answer (with the right value, if given) goes into the next AI read as
a worked example. It works from the first correction, with no training run. Lessons are passed as quoted
data, never as instructions. To measure it on drawings the lessons did not come from:

```bash
.venv/Scripts/python tools/reader_learning.py --dry-run   # split and cost, no API
.venv/Scripts/python tools/reader_learning.py             # needs ANTHROPIC_API_KEY
```

It reads every drawing with a truth file, turns the mistakes on half of them into corrections (the truth
file stands in for the engineer), and compares the other half read with and without those lessons.

## How a file is read

Every upload first goes through the reading pipeline (`backend/app/reading/`): text layer and OCR, labeled values
found by code, the AI pointing at lines that code then verifies, and a second reading of each value. Schedules and
IFC models are read as data. PDFs then also go through the drawing reader below, for door tags, corridors, and ramps.
Each value it finds is read again by OCR of its line (`reading/code_reader.py`): if the digits agree and the label's
pairing is clear it is tier B, otherwise it stays below B. Label and value are tied by position, so it never reaches A.
If code finds nothing at all, like on a clean scan, the AI reads the whole page, and those values stay at tier C.

## Reading vector PDFs with code

`backend/app/drawing.py` reads a PDF's text layer with no API: door tags, clear widths in any unit
(`2'-8"`, `31 7/8"`, `815 mm`), door schedules, and table rows, even rotated. It also reads corridor
clear widths (label, next line, or corridor schedule) and ramp slopes (`1:12`, or rise and run). For
corridors and ramps, rotated value text and numbers with no unit are not used: the result is can't tell.
It never scales a size off the lines. Each fact records how it was read (pairing distance, ambiguity, OCR, scale), which the
confidence model uses. A reading with low confidence never passes.

```bash
.venv/Scripts/python tools/validate_data.py        # reader and checks vs every truth file in data/
.venv/Scripts/python tools/reader_benchmark.py     # hard SYNTHETIC sheets: false passes, misreads, learning curve
.venv/Scripts/python tools/corridor_ramp_eval.py data/synthetic/SYNTHETIC_corridor_ramp_seed202   # corridors, ramps
```

Offline demo: `data/demo_offline_SYNTHETIC/` has one drawing per result type (pass, fail, can't tell,
conflict). Upload with the passenger-test profile; no API key or network needed.

Uploads: 50 MB and 200 PDF pages at most (choose pages for larger sets). Broken, empty, renamed, or
password-protected files get a 400 with the reason. Without an API key, scanned drawings, images, and
chat answer 503 and say a key is needed; everything else keeps working. API timeouts and rate limits are
retried once after 2 s. A value with no or an unknown unit, or a zero or negative length, is never used:
it shows as can't tell.

## Spending cap

AI calls stop at `BUDGET_USD` (default $4.00), tracked in `ship-data/usage.json`. Facts read from a file
are cached, so reading the same file again is free.

## Tests

```bash
cd backend
../.venv/Scripts/python -m pytest tests
```

No test calls the real API. `tools/accuracy_report.py` measures the checks on the real ship data: a
hand-checked door set, faults seeded one at a time, and a run with all dimensions removed.

## Known limits

- Rule texts in this repo cover COLREG, PVAG, and ADA. Local excerpts of the adopted SOLAS, FSS Code, and
  MSC.1/Circ.1533 texts confirm 6 more limits on the team's machines only (see "How it works"). These are adopted
  texts, not consolidated editions, and later amendments were checked only in places. The liferaft rule
  `SOLAS-III-RAFTS` (100% each side) can't be traced to a clause yet, so it stays marked not confirmed. DNV rules
  couldn't be retrieved.
- Persons on board must be stated. Crew and science are never added up, because that could undercount.
- The door check uses PVAG V404.2.3, which is a proposed rule, not in force. ADA 404.2.3 sets the same limit,
  but the ADA Standards don't state that they apply to vessels.
- The 3D model doesn't state opening depth, so the passenger profiles keep the approved assumption that door
  openings aren't more than 24 in deep. The ship card profile (`card`) makes no such assumption: a door
  between 32 and 36 in passes only when its stated depth is 24 in or less, and with no depth it's "can't tell".
- The hand-checked set was typed from the model's own description text, so it tests our parsing and
  logic, not whether the model itself is right. An engineer should spot-check it against the drawings.
- The RCRV is a research vessel, so passenger ship rules don't apply to it. The "passenger test" profile
  applies them to its real data to show the method. It's a test case, not a finding about the ship.
- That profile treats every passage door as on an accessible route, because the model doesn't mark routes.
- Stair width is read from tread length. A pass needs an extra margin for handrails, which is our own
  assumption, not a rule value.
- The hackathon version uses the cloud Claude API. Private deployment would come later.
- **No dimension is ever measured off the drawing lines.** The readers take only written values (labels,
  tables, OCR). This is on purpose: a wrong value is worse than a missing one. So a door whose width isn't
  written gives can't tell, and the question asks for it.
- **The reader-specific learning signals are for PDFs.** 3D-model fails also pass through the confidence
  gate, but we had no documentation of the 3D format to build reading signals for it. That is roadmap.
- The synthetic test drawings and the code reader were written by the same team, so results on them are
  optimistic. Drawings made by others (`data/synthetic/team/`) and real engineer answers are the real test.
