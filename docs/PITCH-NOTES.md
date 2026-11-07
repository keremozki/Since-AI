# Pitch notes

Every number here was measured on 7-8 Nov 2026 with the commands in the repo. SYNTHETIC means we
generated the drawing ourselves.

## 1. What it does

The tool checks ship designs against accessibility and safety rules. Drawings, the 3D model, documents,
and the engineer's chat answers become one list of facts. Each fact keeps its quote and where it came
from. Plain Python code then compares the facts with the rule limits and gives PASS, FAIL, CONFLICT,
or CAN'T TELL. The AI only reads and explains. It never decides a result. The engineer confirms or
corrects each reading, and the result updates.

**Drawing in -> facts out (with quote) -> plain Python decides -> engineer confirms.**

## 2. Why CAN'T TELL beats a false PASS

A false PASS sends a non-compliant ship forward with a green tick. A CAN'T TELL costs an engineer one
look. So when a value is missing, unclear, or could mean two things, the tool says CAN'T TELL and asks
one question.

Example from the held-out test set (SYNTHETIC, sheet `SYNTHETIC_cr_s202_04`): corridor C4-6 is labelled
`CLEAR WIDTH 790` with no unit and no unit note on the sheet. As mm it is 31.1 in, below the 36 in
limit. Read as inches it would pass easily. The tool says CAN'T TELL and asks for the unit.

## 3. Numbers

| What | Result |
|---|---|
| Automated tests | 231 pass (125 at the start of this session) |
| Rules coded | 8, of which 4 have their limit quote found word for word in the rule texts (PVAG V404.2.3, V403.5.1, V405.2, COLREG Annex I). The other 4 are marked provisional. |
| **SYNTHETIC, written by us** | |
| Door sheets (`reader_benchmark.py`, 60 sheets, 725 doors, OCR errors, far labels, rotated text) | 278 doors too narrow: 213 FAIL, 65 sent to review (60 CAN'T TELL, 5 CONFLICT), **0 false PASS**, 0 missed. 7 of 220 FAILs were misreads. Coverage (PASS or FAIL) 71% (514 of 725). |
| Corridors and ramps, first run before any reader change (seed 101, 69 objects) | Found 0 of 69. The code reader skipped corridors and ramps. 0 false PASS. |
| Same set after fixing the reader (no longer a fair test) | 69 of 69 right, 0 wrong readings, 0 false PASS |
| Corridors and ramps, held-out set made after the fix (seed 202, 69 objects) | 69 of 69 right, 0 wrong readings, **0 false PASS**. 30 violations: 18 FAIL, 12 sent to review, 0 missed. Coverage 61% (corridors 54%, ramps 70%). All 18 unreadable labels gave CAN'T TELL. |
| **Real drawings** | |
| Sikuliaq GA (real, hand-labelled) | 1 labelled value (length overall 261'-6"), read correctly. No pass/fail truth exists yet. |
| RCRV RFI and MARAD GA (real) | The code reader finds 0 values: the drawing pages have no text layer. They need the AI reader and an API key, and this hasn't been measured. |

The held-out set uses the same label templates as the first set, so it tests new values and layouts,
not new ways of writing a label.

## 4. Known limits

- The synthetic data is optimistic: we wrote both the drawings and the reader.
- The confidence model hasn't learned from real engineer labels yet (0 real labels so far).
- Scanned drawings need an API key, and real AI reader accuracy hasn't been measured.
- PVAG is a proposed rule, not in force.
- ADA isn't directly binding for ship interiors.
- No 3D input for corridors and ramps. The 3D model is used for doors, stairs, rafts, and lights only.
- The reader never measures from the drawing lines. It uses only written values.
- An object with no label gives CAN'T TELL, never a guess.

## 5. Likely judge questions

**How accurate is it?** On our own synthetic drawings: 0 false PASS on 794 objects, and every value it
read was right on the held-out corridor and ramp set. On real drawings we have measured only one value.
We say this openly.

**Why should I trust it?** The AI never decides. Each result comes from a short Python rule you can read,
with the limit and the clause number. Each value shows its quote and a crop of the drawing. When unsure,
it says CAN'T TELL.

**What about real data?** That is the next step: engineer-labelled real drawings. The review screen
already saves each engineer answer for that.

**What does the ML part actually do?** A small logistic regression learns which readings tend to be
misread, from how they were read (label distance, OCR, unit written or not). It can only move a FAIL to
CAN'T TELL for review, never to PASS. It starts only after 30 engineer answers, with at least 8 "read
correctly" and 8 "misread". Until then a fixed rule is used.

**What happens when rules change?** Limits live in `rules/rules.yaml` with the exact quote. If the quote
no longer matches the rule text, the rule is marked provisional on every finding. Changing a limit is a
one-line edit, and the tests show what moved.

## 6. Three-minute demo (offline, no API key, no Wi-Fi)

Start the app (`cd backend; ..\.venv\Scripts\python -m uvicorn app.main:app`), open
http://127.0.0.1:8000, and choose the **passenger-test** profile. Upload files from
`data/demo_offline_SYNTHETIC/`:

1. (0:00) One sentence on the flow. Upload `SYNTHETIC_demo_1_PASS.pdf`: door, corridor, and ramp pass, each with its quote.
2. (0:40) Upload `SYNTHETIC_demo_2_FAIL.pdf`: three FAILs with the gap ("2.0 in short"). Open one and show the drawing crop.
3. (1:20) Upload `SYNTHETIC_demo_3_CANT_TELL.pdf`: a door with no width, a 34 in corridor (an exception may apply), and a rotated ramp slope. Each asks one question. Say: "A guess here could be a false PASS."
4. (2:00) Upload `SYNTHETIC_demo_4_CONFLICT.pdf`: plan says 34 in, schedule says 30 in. CONFLICT, not a pick.
5. (2:30) On a FAIL, answer "Misread" with the right value: the check reruns. Close on the 0 false PASS number and the limits.
