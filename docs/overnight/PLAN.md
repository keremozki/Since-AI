# Overnight build plan (7-8 Nov 2026)

Goal: turn Dynamis SCC plus the three design documents into a working prototype. The three documents are the checking design, the reading design, and the product direction "proof or question".

The backend comes first. AI runs in **offline mode** tonight: requests are saved, answered by closed agents acting as the API, and replayed. Tomorrow, one setting (`AI_MODE=api`) switches to the real API.

## Principles (from the team rules, never broken)
- Code decides every verdict; the AI only reads, points, and explains. Zero false passes.
- A pass or fail needs tier A or B inputs. A single reading (tier C) gives "can't tell" plus a question to confirm.
- Every fact keeps its evidence: file, page, box, quote, and its readings. Every finding keeps its inputs, clause, and edition.
- No defaults are invented. Derived values come only from stated inputs, and the derivation is recorded.

## Phases
0. **Setup:** baseline tests pass (75/75). Get the RCRV `.nwd` and decode `parts.json`. Done tonight.
1. **Contracts (me):** the models (Evidence, Box, Reading, Tier; inputs and overlay on findings; two new statuses), the fact dictionary YAML plus loader, and the offline AI gateway interface.
2. **Parallel build:** agents each own a new package and never edit shared files.
   - B1, synthetic Meyer-style package (`tools/synthetic/`): independent of the reader. Spec, GA (vector, stroked, scan), rev B, door schedule XLSX, IFC, evacuation analysis, `truth.json`.
   - B2, reading pipeline (`backend/app/reading/`): page map (text layer plus OCR), calibration (frame ruler plus deck ladder), labeled values, value parsing (ft-in, metric), AI pointing plus code verification, XLSX/CSV/IFC readers.
   - B3, ship card and design basis (`backend/app/basis/`): ship card, the `applies_if` evaluator (dates and thresholds), required values, what-if, sister-hull delta, amendments data.
   - R1, business research (background): pricing, buyers, sales path, funding, partners.
3. **Integration (me):**
   - tier gating in the engine
   - new checks: V/22 from the drawing with overlay, evacuation analysis must-exist, FSS persons-based stair width, door opening-depth rule
   - revision impact
   - proof bundles plus verifier
   - evidence crops, and the engineer confirm/correct API
   - endpoints and minimal frontend type updates
4. **Offline AI run:** run the pipeline on RCRV and the package, export pending AI requests to closed sandboxes, answer with closed agents, replay, verify.
5. **Scoreboard and tests:** reading accuracy per fact kind, planted errors caught, false passes, the RCRV checks, and the full pytest suite.
6. **Review and improvement round (one pass):** QA, product/innovation, and rule-accuracy reviewers. Implement the fixes and the best improvements, then retest.
7. **Docs and delivery:** README, ARCHITECTURE, offline AI guide, Dockerfile and compose, the short PDF for the team, and memory.

## Out of scope tonight
UI polish (only type updates so the app keeps working), real API calls, pushing to GitHub.
