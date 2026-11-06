"""Copy the compressed RCRV geometry out of the prototype viewer page into ship-data/.

Usage: python tools/extract_viewer_model.py <RCRV-3D.html>
"""
import base64
import re
import sys
from pathlib import Path


def main() -> None:
    page = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
    meta = re.search(r'<script type="application/json" id="model-meta">(.*?)</script>', page, re.S).group(1)
    blob = re.search(r'<script type="text/plain" id="model-b64">(.*?)</script>', page, re.S).group(1)
    out = Path("ship-data")
    out.mkdir(exist_ok=True)
    (out / "model-meta.json").write_text(meta, encoding="utf-8")
    (out / "model.bin").write_bytes(base64.b64decode(blob))
    print("geometry bytes:", (out / "model.bin").stat().st_size)


if __name__ == "__main__":
    main()
