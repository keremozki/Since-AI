"""Door schedule (xlsx and csv) and stair schedule (csv)."""
import csv
import datetime
import re
import zipfile

import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill

from . import data as D

DOOR_HEAD = ["DOOR NO.", "LOCATION", "TYPE", "CLEAR WIDTH (mm)", "OPENING DEPTH (mm)", "ACCESSIBLE ROUTE", "FIRE CLASS"]
STAIR_HEAD = ["STAIR", "DECK", "CLEAR WIDTH (mm)", "PERSONS SERVED", "MVZ"]
SHEET = "DOOR SCHEDULE DECK 5"
HEAD_ROW = 3  # xlsx: title row 1, note row 2, header row 3


def door_rows():
    """Door table rows; blank cells are None."""
    return [[d["no"], d["loc"] + ("" if d["kind"] == "zone" else f", FR {round(D.door_fr(d))}"), d["typ"], d["clear"], d["depth"],
             "YES" if d["acc"] else "NO", d["fire"]] for d in D.DOORS]


def stair_rows():
    return [[f"STAIR {n}", D.STAIR_DECK, s["clear"], s["persons"], D.STAIR_MVZ] for n, s in D.STAIRS.items()]


def write_csv(path, head, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(head)
        w.writerows([["" if v is None else v for v in r] for r in rows])


def door_xlsx(path):
    wb = openpyxl.Workbook()
    wb.properties.creator = "synthetic generator"
    wb.properties.created = wb.properties.modified = datetime.datetime(2026, 10, 1)
    ws = wb.active
    ws.title = SHEET
    ws["A1"] = "DOOR SCHEDULE DECK 5 (MVZ 3)"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"SYN-DS-105 REV A, 2026-10-01, {D.SHIP_NAME}, hull {D.HULL}. {D.SYNTH}"
    ws["A2"].font = Font(italic=True, color="9C0006")
    for c, h in enumerate(DOOR_HEAD, 1):
        cell = ws.cell(HEAD_ROW, c, h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9D9D9")
        cell.alignment = Alignment(horizontal="center", wrap_text=True)
    for r, row in enumerate(door_rows(), HEAD_ROW + 1):
        for c, v in enumerate(row, 1):
            ws.cell(r, c, v)
    for col, w in zip("ABCDEFG", (10, 44, 20, 18, 20, 18, 12)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = ws.cell(HEAD_ROW + 1, 1)
    wb.save(path)
    fix_zip_times(path)


def fix_zip_times(path):
    """Rewrite the xlsx zip with fixed member timestamps so the bytes are reproducible."""
    with zipfile.ZipFile(path) as z:
        items = [(i.filename, z.read(i.filename)) for i in z.infolist()]
    items = [(n, re.sub(rb"(<dcterms:modified[^>]*>)[^<]*", rb"\g<1>2026-10-01T00:00:00Z", b)) for n, b in items]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in items:
            z.writestr(zipfile.ZipInfo(name, (2026, 10, 1, 0, 0, 0)), blob, zipfile.ZIP_DEFLATED)
