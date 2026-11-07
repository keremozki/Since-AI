"""Proof bundles: one run, packed so anyone can check it without trusting this app.

A bundle is a zip with bundle.json and manifest.json. bundle.json holds the ship profile, every rule as
applied (clause, edition, quote, whether the quote was found in the rule text), every fact the run used with
its evidence and tier, every finding with the ids of the facts it rests on, the sha256 of each input file,
and the ids of the AI answers that were replayed. manifest.json holds the sha256 of bundle.json and of every
other file in the zip.

tools/verify_proof.py checks a bundle three ways: the hashes match, every quote is found on its cited page
of the cited file, and rerunning the deterministic checks on the bundled facts gives the same results.
"""
from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .models import Fact, Rule, RunResult

BUNDLE_VERSION = 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def code_version(root: Path) -> str:
    try:
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "--short", "HEAD"], capture_output=True,
                                text=True, timeout=5).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "backend/app", "rules"],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return f"{commit}{'+local changes' if dirty else ''}" if commit else "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_bundle(result: RunResult, facts: list[Fact], rules: list[Rule], files: dict[str, bytes],
                 ai_answers: list[str], root: Path) -> bytes:
    """The zip bytes. `files` maps each input file name to its bytes, `ai_answers` the replayed request ids."""
    used = {f.uid(): f for f in facts}
    bundle = {
        "bundle_version": BUNDLE_VERSION,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "code_version": code_version(root),
        "profile": result.profile.model_dump(mode="json"),
        "summary": result.summary,
        "counts": result.counts,
        "rules": [{**r.model_dump(mode="json"), "quote_found_in_rule_text": r.verified} for r in rules],
        "scope": [d.model_dump(mode="json") for d in result.scope],
        "facts": [{"id": uid, **fact.model_dump(mode="json")} for uid, fact in used.items()],
        "findings": [f.model_dump(mode="json") for f in result.findings],
        "files": [{"name": name, "sha256": sha256(data), "bytes": len(data)} for name, data in sorted(files.items())],
        "ai_answers": sorted(ai_answers),
        "statement": ("Code decided every result from the facts listed here. The AI read and pointed; it decided "
                      "nothing. A pass or fail rests only on facts of tier A or B. The engineer has the final say, "
                      "and class and the flag state make the final call."),
    }
    body = json.dumps(bundle, indent=1, ensure_ascii=False, sort_keys=True).encode()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bundle.json", body)
        manifest = {"bundle.json": sha256(body)}
        for name, data in sorted(files.items()):
            archive.writestr(f"files/{name}", data)
            manifest[f"files/{name}"] = sha256(data)
        archive.writestr("manifest.json", json.dumps(manifest, indent=1, sort_keys=True))
    return out.getvalue()


def read_bundle(data: bytes) -> tuple[dict, dict[str, bytes], list[str]]:
    """(bundle, files, problems). Problems name every hash that doesn't match its manifest entry."""
    problems: list[str] = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json")) if "manifest.json" in names else {}
        if not manifest:
            problems.append("No manifest.json in the bundle.")
        contents = {name: archive.read(name) for name in names if name != "manifest.json"}
    for name, digest in manifest.items():
        if name not in contents:
            problems.append(f"{name} is listed in the manifest but missing.")
        elif sha256(contents[name]) != digest:
            problems.append(f"{name} was changed after the bundle was made (hash mismatch).")
    for name in contents:
        if name not in manifest:
            problems.append(f"{name} isn't in the manifest.")
    bundle = json.loads(contents.get("bundle.json", b"{}"))
    files = {name.removeprefix("files/"): body for name, body in contents.items() if name.startswith("files/")}
    for entry in bundle.get("files", []):
        body = files.get(entry["name"])
        if body is not None and sha256(body) != entry["sha256"]:
            problems.append(f"Input file {entry['name']} doesn't match the hash recorded for the run.")
    return bundle, files, problems
