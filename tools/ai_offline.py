"""Answer the app's saved AI requests without the API, then replay them.

In offline mode (the default, AI_MODE=offline) every AI request is saved under ship-data/ai/pending/<id>/
with its system prompt, content, images, and the JSON schema the answer must match. This tool moves those
requests to a closed answerer and stores the answers, validated against the same schema, so the app
replays them exactly as if the API had replied.

    python tools/ai_offline.py status
    python tools/ai_offline.py list
    python tools/ai_offline.py show <id>
    python tools/ai_offline.py export <id> <folder>      # a closed copy: request, images, instructions only
    python tools/ai_offline.py export-all <folder>
    python tools/ai_offline.py answer <id> <answer.json> --by "<who answered>"
    python tools/ai_offline.py import-all <folder> --by "<who answered>"

An exported folder holds nothing but what the API would see. The answerer reads only that folder and writes
answer.json next to it. It never sees the repository, the expected results, or any other request.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.ai_gateway import SchemaError, save_answer, validate  # noqa: E402

STORE = ROOT / "ship-data" / "ai"

INSTRUCTIONS = """# You are the model API for one request

Read request.json in this folder and any image files it names. Nothing else: do not open any other file or
folder, do not search the web, and do not use anything you know about this project.

- request.json "system" is your system prompt. "content" is the user turn, in order: text blocks, and image
  blocks that name a file in this folder.
- Answer as the model "{model}" would at effort "{effort}", following the system prompt exactly.
- Your whole answer is one JSON value that matches request.json "schema". Write it to answer.json in this
  folder, and nothing else. No markdown, no comments.
- Report only what the content shows. If the system prompt asks for quotes, copy them exactly as written.
  A wrong value is far worse than a missing one.
"""


def _pending() -> list[Path]:
    folder = STORE / "pending"
    answered = {p.stem for p in (STORE / "responses").glob("*.json")}
    return sorted((p for p in folder.glob("*") if p.is_dir() and p.name not in answered),
                  key=lambda p: p.stat().st_mtime) if folder.exists() else []


def _request(rid: str) -> dict:
    return json.loads((STORE / "pending" / rid / "request.json").read_text(encoding="utf-8"))


def _summary(request: dict) -> str:
    texts = [b["text"] for b in request["content"] if b["type"] == "text"]
    images = sum(b["type"] == "image" for b in request["content"])
    first = " ".join(" ".join(texts).split())[:90]
    return f"effort {request['effort']}, {images} image(s), {sum(map(len, texts))} chars: {first}"


def cmd_status(_args) -> None:
    answered = list((STORE / "responses").glob("*.json"))
    print(f"pending: {len(_pending())}, answered: {len(answered)}, store: {STORE}")


def cmd_list(_args) -> None:
    for folder in _pending():
        print(folder.name, "|", _summary(_request(folder.name)))


def cmd_show(args) -> None:
    print(json.dumps(_request(args.id), indent=1, ensure_ascii=False))


def _export(rid: str, out: Path) -> Path:
    source, target = STORE / "pending" / rid, out / rid
    request = _request(rid)
    target.mkdir(parents=True, exist_ok=True)
    keep = {"system", "content", "schema", "effort", "max_tokens", "model"}
    (target / "request.json").write_text(json.dumps({k: v for k, v in request.items() if k in keep},
                                                    indent=1, ensure_ascii=False), encoding="utf-8")
    for block in request["content"]:
        if block["type"] == "image":
            shutil.copy2(source / block["file"], target / block["file"])
    (target / "INSTRUCTIONS.md").write_text(INSTRUCTIONS.format(model=request["model"], effort=request["effort"]),
                                            encoding="utf-8")
    return target


def cmd_export(args) -> None:
    print(_export(args.id, Path(args.folder)))


def cmd_export_all(args) -> None:
    for folder in _pending():
        print(_export(folder.name, Path(args.folder)), "|", _summary(_request(folder.name)))


def _answer(rid: str, answer_file: Path, by: str) -> None:
    response = json.loads(answer_file.read_text(encoding="utf-8"))
    try:
        validate(response, _request(rid)["schema"])
    except SchemaError as error:
        raise SystemExit(f"{rid}: the answer doesn't match the request's schema: {error}") from error
    print(save_answer(STORE, rid, response, by))


def cmd_answer(args) -> None:
    _answer(args.id, Path(args.file), args.by)


def cmd_import_all(args) -> None:
    for folder in sorted(Path(args.folder).glob("*")):
        answer = folder / "answer.json"
        if folder.is_dir() and answer.exists() and (STORE / "pending" / folder.name).exists():
            _answer(folder.name, answer, args.by)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status").set_defaults(run=cmd_status)
    sub.add_parser("list").set_defaults(run=cmd_list)
    show = sub.add_parser("show")
    show.add_argument("id")
    show.set_defaults(run=cmd_show)
    export = sub.add_parser("export")
    export.add_argument("id")
    export.add_argument("folder")
    export.set_defaults(run=cmd_export)
    export_all = sub.add_parser("export-all")
    export_all.add_argument("folder")
    export_all.set_defaults(run=cmd_export_all)
    answer = sub.add_parser("answer")
    answer.add_argument("id")
    answer.add_argument("file")
    answer.add_argument("--by", required=True)
    answer.set_defaults(run=cmd_answer)
    import_all = sub.add_parser("import-all")
    import_all.add_argument("folder")
    import_all.add_argument("--by", required=True)
    import_all.set_defaults(run=cmd_import_all)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()
