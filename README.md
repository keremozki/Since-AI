# Ship Compliance Checker

Since AI Hackathon 2026, Meyer Turku challenge. A web app that checks a ship design against rules and
regulations, and tells the engineer what passes, what fails, where sources conflict, and what's missing.

**Coded tests decide every result. AI never does.** Claude reads drawings and documents into facts,
records values the engineer states in chat, and answers questions. Every fact keeps its source.

Every result is one of four:

| Result | Meaning |
|---|---|
| Pass | Tested and within the limit |
| Fail | Tested and outside the limit, with the measured value, the limit, and the gap |
| Conflict | Sources disagree, so any check that needs the value waits |
| Can't tell | A value is missing. The tool names it and asks for it. It never guesses |

If everything passes, the app says no issues were found and lists which rules it covered. It never
claims that a ship is compliant overall: class and the flag state make the final call.

## How it works

1. **Read:** 3D model parts, 2D drawings, documents, and chat answers become one list of facts.
2. **Scope:** ship type, passengers, and flag decide which rules apply.
3. **Test:** each rule runs as code in `backend/app/checks.py`, with limits in `rules/rules.yaml`.
4. **Report:** plain-text findings, with markers in the 3D viewer.

A rule's limit counts as confirmed only when its `quote` in `rules/rules.yaml` appears word for word in
the rule texts under `docs/rules/`. Until then, its findings are marked provisional.

### Reading the 3D model

`tools/decode_nwd.py` reads part names, stated dimensions, and positions straight from a Navisworks
`.nwd` file, with no Navisworks install. The format was reverse engineered from the RCRV model, so other
files may not work. Engineers can also click two points in the viewer to measure a distance and save it.

## Set up

You need Python 3.12 or later and Node 20 or later. The ship files aren't in this repo: get them from
the Since AI App, and put the model's `.nwd` file and the prototype viewer page somewhere local.

```bash
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt       # on macOS or Linux: .venv/bin/pip
npm --prefix frontend install
npm --prefix frontend run build

.venv/Scripts/python tools/decode_nwd.py path/to/model.nwd    # writes ship-data/parts.json
.venv/Scripts/python tools/extract_viewer_model.py path/to/RCRV-3D.html   # 3D geometry for the viewer
.venv/Scripts/python tools/accuracy_report.py                 # writes the scoreboard
```

Copy `.env.example` to `.env` and add your Anthropic API key. Then start the app:

```bash
cd backend
../.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000. The checks, vector PDF drawings, and the offline demo work with no API key. Chat, images, and scanned drawings need one.

## Managing inputs

The Inputs panel lists the 3D model, each drawing or document, saved measurements, and chat answers. Each
can be removed, and the checks rerun at once. The app holds one 3D model at a time.

- Removing the 3D model keeps its files on disk, so Restore brings it back at once. Its measurements stop
  counting until then.
- Importing a different `.nwd` replaces the current model and deletes measurements taken on the old one.
- A removed drawing can be added again at no cost, because its facts are cached.
- The 3D view exists only for the RCRV. Other models are checked, but aren't shown in the viewer.

## Confidence gate (learns from engineers)

**What the engineer answers:** "Was this value read correctly from the drawing?" They judge the reading,
not the ship. Next to the question they see where the value came from: the file, the place on the page,
the text it was read from, and a close-up of the drawing.

| Button | Label |
|---|---|
| **Read correctly** | 1 |
| **Misread** (the right value and unit are optional) | 0. A right value becomes an engineer fact that replaces the reading, and the check reruns |
| **Not sure** | No label. Logged, never trained on |

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

## Reading vector PDFs with code

`backend/app/drawing.py` reads a PDF's text layer with no API: door tags, clear widths in any unit
(`2'-8"`, `31 7/8"`, `815 mm`), door schedules, and table rows, even rotated. It also reads corridor
clear widths (label, next line, or corridor schedule) and ramp slopes (`1:12`, or rise and run). For
corridors and ramps, rotated value text and numbers with no unit are not used: the result is can't tell.
It never scales a size off the lines. Each fact records how it was read (pairing distance, ambiguity, OCR, scale), which the
confidence model uses. A reading with low confidence never passes. The AI reader runs only when code
finds nothing, or on every file with `CROSS_CHECK_READERS=1`.

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

- Rule texts in `docs/rules/` cover COLREG, PVAG, and ADA. SOLAS, the FSS Code, and MSC.1/Circ.1533 aren't
  there yet, so those limits are still provisional. DNV rules couldn't be retrieved.
- The door check uses PVAG V404.2.3, which is a proposed rule, not in force. ADA 404.2.3 sets the same limit,
  but the ADA Standards don't state that they apply to vessels.
- The door check doesn't test the 36 in limit for openings more than 24 in deep, because the model doesn't
  state opening depth.
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
