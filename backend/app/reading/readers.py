"""Readers for files that hold values as data: spreadsheets (.xlsx, .csv) and IFC models. No AI, no OCR.

A value stored in a cell or a property is exact (tier A), but only if code ties it to the right item and the right
quantity: a door number from its row, a column from the dictionary's labels, never a lookalike (an IFC door's
OverallWidth is the opening width, not the clear width). Empty cells give no candidate and are listed as missing.
"""
from __future__ import annotations

import csv
import io
import os
import re
import tempfile
from functools import lru_cache

import openpyxl
from openpyxl.utils import get_column_letter

from .. import dictionary
from ..dictionary import FactDef
from .labeled import norm, parse_value, range_result, stated_unit
from .model import FactCandidate

DOOR_COLUMNS = {"DOOR", "DOOR NO", "DOOR NUMBER", "DOOR NUM", "DOOR ID"}
STAIR_COLUMNS = {"STAIR", "STAIR NO", "STAIR NUMBER", "STAIR ID", "STAIRWAY", "STAIR NAME"}
HEADER_SCAN_ROWS = 40
_TRAILING_UNIT = re.compile(r"[,\-–/]\s*(mm|cm|m|in|ft)\s*$", re.I)
_PARENTHESES = re.compile(r"\([^)]*\)|\[[^\]]*\]")
YES = {"yes", "y", "true", "accessible"}
NO = {"no", "n", "false", "not accessible", "non-accessible", "non accessible"}


@lru_cache(maxsize=1)
def _table_defs() -> tuple[FactDef, ...]:
    """The door and stair facts: their subjects come from a row (or an IFC element), never from a label alone."""
    return tuple(d for d in dictionary.load() if d.id.startswith(("door.", "stair.")))


def _blank(cell) -> bool:
    return cell is None or (isinstance(cell, str) and not cell.strip())


def _cell_text(cell) -> str:
    if isinstance(cell, float) and cell == int(cell):
        return str(int(cell))
    return str(cell).strip()


def _number(cell) -> bool:
    return isinstance(cell, (int, float)) and not isinstance(cell, bool)


def _door_number(cell) -> str | None:
    if _number(cell) and float(cell) == int(cell):
        return str(int(cell))
    match = re.fullmatch(r"(?:DOOR\s*)?(?:NO\.?\s*)?[#-]?\s*(\d+)", str(cell).strip(), re.I)
    return match.group(1) if match else None


def _stair_id(name) -> str | None:
    """The letter (or short id) in a name like "Stair B" or "Stair B Flight 1"."""
    cleaned = re.sub(r"\b(?:STAIRS?|STAIRWAY|STAIRCASE|FLIGHT)\b", " ", str(name or ""), flags=re.I)
    tokens = re.findall(r"[A-Za-z0-9]+", cleaned)
    letters = [t for t in tokens if len(t) == 1 and t.isalpha()]
    if len(letters) == 1:
        return letters[0].upper()
    if len(tokens) == 1 and len(tokens[0]) <= 3:
        return tokens[0].upper()
    return None


def _yes_no(cell) -> str | None:
    if isinstance(cell, bool):
        return "yes" if cell else "no"
    text = str(cell).strip().lower()
    return "yes" if text in YES else "no" if text in NO else None


def _header_unit(text: str) -> str:
    unit = stated_unit(text)
    match = _TRAILING_UNIT.search(text)
    return unit or (match.group(1).lower() if match else "")


# -- spreadsheets ----------------------------------------------------------------------------------------------

def _classify(cell) -> tuple[str, str] | None:
    """What a header cell is: ("subject", "door"|"stair"), ("property", name), or None."""
    if _blank(cell):
        return None
    text = str(cell)
    plain = norm(_PARENTHESES.sub(" ", text))
    if plain in DOOR_COLUMNS:
        return "subject", "door"
    if plain in STAIR_COLUMNS:
        return "subject", "stair"
    properties = {d.property for d in _table_defs() if dictionary.label_matches(d, text)}
    return ("property", properties.pop()) if len(properties) == 1 else None


def _find_header(rows: list[list], start: int) -> dict | None:
    for index in range(start, min(len(rows), start + HEADER_SCAN_ROWS)):
        kinds = {j: k for j, cell in enumerate(rows[index]) if (k := _classify(cell))}
        subjects = {j: k[1] for j, k in kinds.items() if k[0] == "subject"}
        properties = {j: k[1] for j, k in kinds.items() if k[0] == "property"}
        if subjects and properties:
            return {"row": index, "subjects": subjects, "properties": properties}
    return None


def _subject_for(row: list, header: dict) -> tuple[str | None, int, str]:
    """(subject, its column, reason) from the row's door or stair column. Two filled gives none: ambiguous."""
    found = []
    for col, kind in header["subjects"].items():
        cell = row[col] if col < len(row) else None
        if _blank(cell):
            continue
        ident = _door_number(cell) if kind == "door" else _stair_id(cell)
        found.append((f"door-number:{ident}" if kind == "door" else f"stair:{ident}", ident, col, cell))
    if not found:
        return None, -1, "no door or stair in the row"
    if len(found) > 1:
        return None, -1, "both a door and a stair are named in the row"
    subject, ident, col, cell = found[0]
    if ident is None:
        return None, -1, f"'{_cell_text(cell)}' is not a door number or stair id code can read"
    return subject, col, ""


def _table_cell(defn: FactDef, subject: str, sheet: str, row: int, col: int, header_text: str, unit_hint: str,
                subject_note: str, cell) -> tuple[FactCandidate | None, str]:
    coordinate = f"{get_column_letter(col + 1)}{row + 1}"
    text = _cell_text(cell)
    checks = [f"column '{header_text}' is a listed label for {defn.id}", subject_note]
    if defn.kind == "text":
        value = _yes_no(cell)
        if value is None:
            return None, f"'{text}' is not clearly yes or no"
        unit, shown = "", f"'{text}' = {value}"
    elif _number(cell):
        value = float(cell)
        unit = unit_hint if defn.kind == "length" else ""
        if defn.kind == "length" and not unit:
            return None, "the column states no unit, so the number can't be a length"
        shown = f"{text} {unit}".strip()
    else:
        parsed, why = parse_value(defn, text, unit_hint)
        if parsed is None:
            return None, why
        value, unit, shown = parsed.value, parsed.unit, parsed.shown
    checks.append(f"value read from the cell by code: {shown}")
    if unit_hint and defn.kind == "length":
        checks.append(f"unit {unit_hint} stated in the column header")
    check, problem = range_result(defn, value, unit)
    if check:
        checks.append(check)
    return FactCandidate(
        fact_id=defn.id, subject=subject, property=defn.property, value=value, unit=unit, page=1,
        line_ids=[f"{sheet}!{coordinate}"], label_text=dictionary.label_matches(defn, header_text) or header_text,
        quote=text, box=None, method="table_cell",
        readings=[{"method": "cell", "text": text, "value": value, "unit": unit, "confidence": None}],
        checks=checks, problems=[problem] if problem else []), ""


def _read_sheet(name: str, rows: list[list], info: dict) -> list[FactCandidate]:
    candidates: list[FactCandidate] = []
    start = 0
    while (header := _find_header(rows, start)) is not None:
        header["texts"] = {j: rows[header["row"]][j] for j in {*header["subjects"], *header["properties"]}}
        above = " ".join(_cell_text(c) for r in rows[max(0, header["row"] - 5):header["row"]] for c in r if not _blank(c))
        sheet_unit = stated_unit(above, phrase_only=True)
        units = {j: _header_unit(str(rows[header["row"]][j])) or sheet_unit for j in header["properties"]}
        mapped_ids = {*header["subjects"], *header["properties"]}
        unmapped = [{"column": get_column_letter(j + 1), "header": _cell_text(c)}
                    for j, c in enumerate(rows[header["row"]]) if not _blank(c) and j not in mapped_ids]
        table = {"sheet": name, "header_row": header["row"] + 1,
                 "subject_columns": {get_column_letter(j + 1): kind for j, kind in header["subjects"].items()},
                 "mapped_columns": {get_column_letter(j + 1): p for j, p in header["properties"].items()},
                 "units": {get_column_letter(j + 1): u for j, u in units.items() if u}, "unmapped_columns": unmapped}
        end = len(rows)
        following = _find_header(rows, header["row"] + 1)
        if following is not None:
            end = following["row"]
        for r in range(header["row"] + 1, end):
            row = rows[r]
            if all(_blank(c) for c in row):
                continue
            subject, subject_col, why = _subject_for(row, header)
            if subject is None:
                info["skipped_rows"].append({"sheet": name, "row": r + 1, "reason": why})
                continue
            note = (f"subject {subject} read from column '{_cell_text(header['texts'][subject_col])}', cell "
                    f"{get_column_letter(subject_col + 1)}{r + 1}: '{_cell_text(row[subject_col])}'")
            for col, prop in header["properties"].items():
                defn = dictionary.for_fact(subject, prop)
                if defn is None:
                    continue  # e.g. persons served for a door: the dictionary has no such fact
                cell = row[col] if col < len(row) else None
                where = f"{get_column_letter(col + 1)}{r + 1}"
                if _blank(cell):
                    info["missing"].append({"sheet": name, "row": r + 1, "column": get_column_letter(col + 1),
                                            "cell": f"{name}!{where}", "subject": subject, "property": prop,
                                            "header": _cell_text(header["texts"][col])})
                    continue
                candidate, why = _table_cell(defn, subject, name, r, col, _cell_text(header["texts"][col]),
                                             units[col], note, cell)
                if candidate is None:
                    info["unreadable"].append({"cell": f"{name}!{where}", "subject": subject, "property": prop,
                                               "reason": why})
                else:
                    candidates.append(candidate)
        info["tables"].append(table)
        if following is None:
            break
        start = following["row"]
    return candidates


def _sheets_xlsx(data: bytes) -> dict[str, list[list]]:
    workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
    return {ws.title: [list(row) for row in ws.iter_rows(min_row=1, min_col=1, values_only=True)]
            for ws in workbook.worksheets}


def _sheets_csv(data: bytes) -> dict[str, list[list]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return {"csv": [row for row in csv.reader(io.StringIO(text), dialect)]}


def read_table_file(data: bytes, filename: str) -> tuple[list[FactCandidate], dict]:
    """Door and stair values from a .xlsx or .csv schedule: (candidates, info about the tables found)."""
    suffix = os.path.splitext(filename)[1].lower()
    try:
        if suffix == ".xlsx":
            sheets = _sheets_xlsx(data)
        elif suffix == ".csv":
            sheets = _sheets_csv(data)
        else:
            return [], {"status": "couldn't be read", "reason": f"{suffix or filename} is not a .xlsx or .csv file"}
    except Exception as error:  # a damaged or protected file: say so, don't guess
        return [], {"status": "couldn't be read", "reason": f"{type(error).__name__}: {error}"}
    info: dict = {"status": "read", "format": suffix.lstrip("."), "sheets": list(sheets), "tables": [],
                  "missing": [], "skipped_rows": [], "unreadable": [], "sheets_without_table": []}
    candidates: list[FactCandidate] = []
    for name, rows in sheets.items():
        before = len(info["tables"])
        candidates += _read_sheet(name, rows, info)
        if len(info["tables"]) == before:
            info["sheets_without_table"].append(name)
    if not info["tables"]:
        info.update(status="couldn't be read",
                    reason="no header row has both a door or stair column and a column the dictionary lists")
        return [], info
    first = info["tables"][0]
    info.update(header_row=first["header_row"], mapped_columns=first["mapped_columns"],
                unmapped_columns=[u["header"] for u in first["unmapped_columns"]])
    return candidates, info


# -- IFC -------------------------------------------------------------------------------------------------------

IFC_PROPERTIES = {"clearwidth": "clear_width", "openingdepth": "opening_depth", "accessibleroute": "accessible_route",
                  "personsserved": "persons_served"}


def _open_ifc(data: bytes):
    import ifcopenshell
    handle, path = tempfile.mkstemp(suffix=".ifc")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        return ifcopenshell.open(path)
    finally:
        os.unlink(path)


def _length_unit(model) -> tuple[str, float] | None:
    """(unit, factor to apply to a raw IFC length) from the project length unit; mm or m, else converted to mm."""
    import ifcopenshell.util.unit as units
    if units.get_project_unit(model, "LENGTHUNIT") is None:
        return None
    scale = units.calculate_unit_scale(model)  # meters per project unit
    if abs(scale - 1.0) < 1e-12:
        return "m", 1.0
    if abs(scale - 0.001) < 1e-12:
        return "mm", 1.0
    return "mm", scale * 1000.0


def _raw_text(raw) -> str:
    return str(int(raw)) if isinstance(raw, float) and raw == int(raw) else str(raw)


def _ifc_candidate(defn: FactDef | None, fact_id: str, subject: str, prop: str, element, source: str, raw,
                   unit: str, factor: float, extra: list[str]) -> FactCandidate | None:
    kind = defn.kind if defn else "length"
    if kind == "text":
        value, unit = _yes_no(raw), ""
        if value is None:
            return None
    elif not _number(raw):
        return None
    elif kind == "length":
        value = round(float(raw) * factor, 9)
    else:
        value, unit = float(raw), ""
    quote = f"{source} = {_raw_text(raw)}"
    checks = [f"IFC property {source} maps to {fact_id}", *extra]
    problems: list[str] = []
    if defn is not None:
        check, problem = range_result(defn, value, unit)
        if check:
            checks.append(check)
        if problem:
            problems.append(problem)
    return FactCandidate(
        fact_id=fact_id, subject=subject, property=prop, value=value, unit=unit, page=1,
        line_ids=[element.GlobalId], label_text=source.split(".")[-1], quote=quote, box=None, method="ifc_property",
        readings=[{"method": "ifc_property", "text": quote, "value": value, "unit": unit, "confidence": None}],
        checks=checks, problems=problems)


def read_ifc(data: bytes, filename: str) -> tuple[list[FactCandidate], dict]:
    """Door and stair values from an IFC model, using the project's length unit. A door's OverallWidth is recorded
    as opening_width (a lookalike) and never as clear_width."""
    try:
        import ifcopenshell.util.element as element_util
        model = _open_ifc(data)
        length = _length_unit(model)
        doors, flights = model.by_type("IfcDoor"), model.by_type("IfcStairFlight") + model.by_type("IfcStair")
    except Exception as error:
        return [], {"status": "couldn't be read", "reason": f"{type(error).__name__}: {error}"}
    info: dict = {"status": "read", "schema": model.schema, "length_unit": length[0] if length else "not stated",
                  "doors": len(doors), "stairs": len(flights), "skipped": [], "unmapped_properties": []}
    if length is None:
        info["length_note"] = "the model states no length unit, so no length can be read from it"
    unit, factor = length or ("", 0.0)
    candidates: list[FactCandidate] = []
    unit_check = [f"IFC project length unit is {unit}"] if unit else []
    for kind, elements in (("door", doors), ("stair", flights)):
        for element in elements:
            ident = None
            if kind == "door":
                numbers = [re.findall(r"\d+", str(t or "")) for t in (element.Tag, element.Name)]
                ident = next((n[0] for n in numbers if len(n) == 1), None)
            else:
                ident = _stair_id(element.Name)
            if ident is None:
                info["skipped"].append({"entity": element.is_a(), "global_id": element.GlobalId,
                                        "name": element.Name, "reason": f"no {kind} number or id in Name or Tag"})
                continue
            subject = f"door-number:{ident}" if kind == "door" else f"stair:{ident}"
            if kind == "door" and getattr(element, "OverallWidth", None) is not None and unit:
                made = _ifc_candidate(None, "door.opening_width", subject, "opening_width", element,
                                      "IfcDoor.OverallWidth", element.OverallWidth, unit, factor,
                                      unit_check + ["IfcDoor.OverallWidth is the opening width (a lookalike of clear "
                                                    "width): recorded as opening_width, never as clear_width"])
                if made:
                    candidates.append(made)
            for pset, props in element_util.get_psets(element).items():
                for prop, raw in props.items():
                    if prop == "id":
                        continue
                    name = IFC_PROPERTIES.get(re.sub(r"[^a-z0-9]", "", prop.lower()))
                    defn = dictionary.for_fact(subject, name) if name else None
                    if defn is None:
                        if len(info["unmapped_properties"]) < 50:
                            info["unmapped_properties"].append(f"{pset}.{prop}")
                        continue
                    if defn.kind == "length" and not unit:
                        continue
                    made = _ifc_candidate(defn, defn.id, subject, name, element, f"{pset}.{prop}", raw, unit, factor,
                                          unit_check if defn.kind == "length" else [])
                    if made:
                        candidates.append(made)
                    else:
                        info["skipped"].append({"entity": element.is_a(), "global_id": element.GlobalId,
                                                "name": element.Name, "reason": f"{pset}.{prop} = {raw!r} is not readable"})
    info["unmapped_properties"] = sorted(set(info["unmapped_properties"]))
    return candidates, info
