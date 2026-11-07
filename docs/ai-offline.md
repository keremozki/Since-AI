# Running the AI offline

The app talks to the AI through one door, `backend/app/ai_gateway.py`. `AI_MODE` picks how that door works:

| AI_MODE | What happens | Network | Cost |
|---|---|---|---|
| `offline` (default) | Each request is saved under `ship-data/ai/pending/<id>/`. A recorded answer for the same request replays. | none | none |
| `api` | The real Claude API, with the spending cap. | yes | yes |
| `record` | The real API, and every answer is saved too, so it replays offline later. | yes | once |

The request id is a hash of everything the model would see: model, system prompt, text, image bytes, the
JSON schema, and the effort. The same request always gets the same id. A changed prompt or a changed page
gets a new one, so an answer is never replayed for a request it wasn't given.

## What the AI is asked to do

It never decides a result. It does two narrow jobs, and code checks both:

1. **Point** (`reading/pointing.py`, effort medium). It gets a page's text lines with ids and positions, and
   names the line ids that hold a fact's label and value. It never types a value. Code re-reads the value
   from those lines with the same rules as the deterministic reader, and refuses the pointer if it fails
   them: a lookalike label, a value that doesn't start the text, lines that aren't near each other, and so on.
2. **Transcribe** (`reading/second_reading.py`, effort low). It gets a small crop image and writes the
   characters it sees. Code parses them and compares the value with the OCR reading. Agreement can raise a
   value to tier B. Disagreement makes it tier D, so it can't back any result.

Chat (`chat.py`) is the third use. It explains results and records values the engineer states.

## Answering saved requests without the API

```bash
python tools/ai_offline.py status
python tools/ai_offline.py list
python tools/ai_offline.py export-all /path/to/closed-folder      # one folder per request
#   ... the answerer writes answer.json in each folder ...
python tools/ai_offline.py import-all /path/to/closed-folder --by "closed agent, model X"
```

Each exported folder holds only `request.json`, the images it names, and `INSTRUCTIONS.md`. The answerer
works from that folder alone: no repository, no truth file, no other request. Every answer is validated
against the request's own JSON schema before it is saved. A schema mismatch is refused.

On the night of 7 November 2026, closed agents answered the saved requests this way, acting as the API.
Nothing else was given to them. Each answer records who answered it, in `ship-data/ai/responses/<id>.json`.

Then read the files again, so the answers are used:

```bash
curl -X POST "http://127.0.0.1:8000/api/inputs/reread?profile=card&name=spec.pdf"
```

## Moving to the real API

Set `AI_MODE=record` and `ANTHROPIC_API_KEY` in `.env`. Requests that were already answered still replay
for free. New ones go to the API and are saved. `AI_MODE=api` skips saving. The spending cap
(`BUDGET_USD`) holds in both.
