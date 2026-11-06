"""Decode named parts from a Navisworks .nwd file into ship-data/parts.json.

Usage: python tools/decode_nwd.py <file.nwd> [output.json]
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.nwd import decode  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "ship-data" / "parts.json"
    parts = decode(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": source.name, "parts": parts}, indent=0), encoding="utf-8")
    print(f"{len(parts)} parts written to {target}")


if __name__ == "__main__":
    main()
