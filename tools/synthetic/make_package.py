"""Build the synthetic SYN-1 design package (meyer-style-v1).

Usage: .venv/bin/python -I tools/synthetic/make_package.py [outdir]
Default outdir: samples/meyer-style-v1. No network, no AI; the output is deterministic.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pymupdf  # noqa: E402

from synth import data as D  # noqa: E402
from synth import docs, ga, ifcmodel, scan, tables, truth  # noqa: E402
from synth.pen import MM, Pen  # noqa: E402

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "samples" / "meyer-style-v1"


def ga_pdf(path, rev, strokes=False):
    """One A3 landscape sheet; strokes=True draws all text as line paths."""
    doc = docs.new_doc(f"{D.GA['no']} rev {rev}", D.SYNTH)
    page = doc.new_page(width=420 * MM, height=297 * MM)
    pen = Pen(page, strokes)
    ga.draw(pen, rev)
    pen.done()
    docs.save(doc, path)


def generate(outdir=DEFAULT_OUT):
    """Write every file of the package into outdir and return the truth dict."""
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    docs.spec(out / truth.SPEC)
    docs.evac(out / truth.EA)
    ga_pdf(out / truth.GA_A, "A")
    ga_pdf(out / truth.GA_B, "B")
    ga_pdf(out / truth.GA_S, "A", strokes=True)
    scan.scan(out / truth.GA_A, out / truth.GA_SCAN_PNG, out / truth.GA_SCAN_PDF)
    tables.door_xlsx(out / truth.XLSX)
    tables.write_csv(out / truth.DCSV, tables.DOOR_HEAD, tables.door_rows())
    tables.write_csv(out / truth.SCSV, tables.STAIR_HEAD, tables.stair_rows())
    ifcmodel.build(str(out / truth.IFC))
    data = truth.build(D.GENERATED)
    (out / "truth.json").write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    generate(target)
    for p in sorted(target.iterdir()):
        print(f"{p.stat().st_size:>9,}  {p.name}")
