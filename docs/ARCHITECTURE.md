# Architecture

One rule runs through the whole design: **the AI reads and points, code decides, the engineer has the
final say.** Every value carries its evidence and a trust tier. Only tier A or B values can back a pass
or a fail, and anything unproven becomes a question.

## How the two gates and the two readers fit together

- **Readers.** A PDF goes through the reading pipeline, then the drawing reader (`app/drawing.py`) for door tags,
  corridors, and ramps. `app/reading/code_reader.py` reads each of its values again by OCR of the line: digits agree and a
  clear pairing give tier B, anything else stays below. If code finds nothing, the AI reads the whole page (`app/ingest.py`),
  and those values stay at tier C.
- **Gates.** After the checks, the confidence gate (`app/confidence.py`) can move a likely misread from fail to can't tell.
  The tier gate (`app/tiers.py`) then holds any pass or fail resting on a tier C or D input. Neither can create a fail or
  turn anything into a pass.
- **Review.** `POST /api/feedback` is the one answer flow. "Read correctly" confirms the weak readings, "misread" with a
  value replaces the reading with an engineer fact, and both can be undone. Only fails with a compared value train the
  model. Answers on anything else are saved but never trained on.

```
 files ──► reading pipeline ──► facts (value, unit, evidence, tier)
            │  page map: text layer, OCR where there's none        │
            │  labeled values found by code                        ├──► ship card ──► design basis
            │  AI points at lines, code verifies (offline replay)  │      (type, size, persons, dates)
            │  second reading: OCR or AI transcription of the crop │              │ which rules apply, and why
            ▼                                                       ▼              ▼
       revisions: a newer drawing revision replaces the old facts ──► checks (code only) ──► tier gate
                                                                                   │
                       proof bundle (zip, hashes, replay) ◄── findings: pass, fail, conflict, can't tell,
                                                              not applicable; clause, evidence, question, fix
```

## Where things live

| Part | File | What it does |
|---|---|---|
| Data shapes | `backend/app/models.py` | Fact, Evidence, Box, Reading, Tier, Finding, Rule |
| Fact dictionary | `rules/facts/*.yaml`, `app/dictionary.py` | Each fact's meaning, labels, lookalikes to refuse, range, allowed values |
| Page map | `app/reading/pagemap.py` | Text layer and OCR lines with ids and boxes; page kinds; cache |
| Title block | `app/reading/titleblock.py` | Drawing number, revision, scale notes |
| Calibration | `app/reading/calibrate.py` | Frame ruler and deck ladder fits: the drawing as a measuring tool |
| Labeled values | `app/reading/labeled.py` | Values beside listed labels, parsed by code |
| AI pointing | `app/reading/pointing.py` | The AI names line ids; code re-reads and verifies |
| Second readings | `app/reading/second_reading.py` | OCR of the crop, or AI transcription for OCR values |
| Schedules and IFC | `app/reading/readers.py` | XLSX, CSV and IFC4: cells and properties (OverallWidth is never clear width) |
| Tiers | `app/reading/to_facts.py`, `app/tiers.py` | A: exact data or text layer confirmed by OCR. B: two methods agree. C: one reading. D: a problem |
| Pipeline | `app/reading/pipeline.py` | One uploaded file to facts |
| Ship card, design basis | `app/basis/` and `rules/applicability.yaml`, `rules/amendments.yaml` | Which rules and editions apply to this hull, as three-valued conditions with clauses |
| Checks | `app/checks.py` with limits in `rules/rules.yaml` | Deterministic tests; missing data is "can't tell", never a pass |
| Gate | `app/tiers.py` `gate()` | A pass or fail resting on a tier C or D input is held back to "can't tell", naming the reading to confirm |
| Engine | `app/engine.py` | Scope, checks, gate, order, summary, report |
| Revisions | `app/revisions.py` | Newer revision supersedes older facts; value-by-value impact |
| Proof bundles | `app/proof.py`, `tools/verify_proof.py` | Zip of rules, facts, findings, files and hashes; independent verification and replay |
| AI gateway | `app/ai_gateway.py`, `tools/ai_offline.py` | Offline, API or record mode; schema validation; see `docs/ai-offline.md` |
| API | `app/main.py` | FastAPI endpoints below |
| Scoreboard | `tools/scoreboard.py`, `tools/accuracy_report.py` | Accuracy on the synthetic package and on the RCRV model |

## API

| Endpoint | Use |
|---|---|
| `GET /api/run/{profile}` | Run the checks. Profile `card` lets the ship card choose the rules. |
| `GET /api/report/{profile}` | Plain-text report |
| `POST /api/upload` | Read a PDF, image, XLSX, CSV or IFC file |
| `POST /api/inputs/reread` | Read a stored file again, for example after offline AI answers arrived |
| `GET /api/facts`, `POST /api/facts/confirm` | Facts with their tier. The engineer confirms or corrects a reading. |
| `GET /api/evidence/crop` | The cited part of a page with the reading's box drawn on it |
| `GET /api/shipcard`, `POST /api/shipcard/confirm` | The ship card, its open questions, confirmations |
| `GET /api/basis` | Rules that apply, with clauses, required numbers, missing inputs and amendments |
| `POST /api/whatif` | Try card values without saving them, for example a sister hull's dates |
| `GET /api/proof/{profile}` | Download a proof bundle |
| `GET /api/ai/status` | AI mode, waiting requests, answers replayed |

## Invariants, and where they're enforced

- The AI never decides a result. It has no path to a Finding. Checks read facts only (`checks.py`).
- The AI never types a number that is used. Pointers name line ids and code parses the text (`pointing.py`); chat may record only a number the engineer wrote (`chat.in_engineers_words`).
- A pass needs tier A or B inputs. That's `tiers.gate()`, applied to every finding in `engine.run()`.
- Missing data is "can't tell" with a question, never a pass (every check, `tests/test_checks.py`).
- Applicability with a missing input is "can't tell", never assumed (`basis/conditions.py`).
- Every finding names its rule clause and edition. Its inputs list each fact's id, tier, source and quote.
- A rule's limit counts as verified only when its quote is in the rule texts (`rules.py`, `docs/rules/imo/`).
