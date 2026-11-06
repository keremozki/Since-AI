"""Decode named parts from a Navisworks .nwd file into ship-data/parts.json.

The .nwd format is reverse engineered from one file (the RCRV model), so treat
other files as unsupported. No Navisworks install is needed.

Usage: python tools/decode_nwd.py <file.nwd> [output.json]
"""
from __future__ import annotations

import json
import re
import struct
import sys
import zlib
from pathlib import Path

INT = struct.Struct("<i")
DOUBLE = struct.Struct("<d")
HEADER_BYTES = 96
STEP = 1 << 18
PRINTABLE = re.compile(rb"[\x20-\x7e]+")
KEEP_FIELDS = {
    "Part Name": "name",
    "Description": "description",
    "Compartment": "compartment",
    "Item No.": "item",
    "Drawing Ref No.": "drawing",
    "Source of Dimensional Data": "dimension_source",
    "SWBS": "swbs",
    "PWBS": "pwbs",
    "Part GUID": "guid",
    "Manufacturer Model": "model",
    "Revision": "revision",
    "Preliminary/Final VFI": "status",
}
CG = re.compile(r"x=(-?[\d.]+),\s*y=(-?[\d.]+),\s*z=(-?[\d.]+)")


def inflate_chunks(data: bytes):
    """Yield each zlib chunk in the file, skipping any non-zlib gap between them."""
    view = memoryview(data)
    pos = HEADER_BYTES
    while pos < len(data):
        decoder = zlib.decompressobj()
        parts, cursor = [], pos
        try:
            while not decoder.eof and cursor < len(data):
                parts.append(decoder.decompress(view[cursor : cursor + STEP]))
                cursor += STEP
        except zlib.error:
            next_pos = _next_chunk(data, view, pos)
            if next_pos is None:
                return
            pos = next_pos
            continue
        yield b"".join(parts)
        pos = cursor - len(decoder.unused_data)


def _next_chunk(data: bytes, view: memoryview, pos: int) -> int | None:
    for k in range(pos + 1, min(pos + 65536, len(data) - 2)):
        if data[k] == 0x78 and data[k + 1] in (0x01, 0x5E, 0x9C, 0xDA):
            try:
                zlib.decompressobj().decompress(view[k : k + 1024])
                return k
            except zlib.error:
                continue
    return None


def _pad(n: int) -> int:
    return (n + 3) & ~3


def _read_value(b: bytes, i: int, kind: int):
    if kind == 4:
        length = INT.unpack_from(b, i)[0]
        if length < 0 or length > 5000:
            return None, None
        return b[i + 4 : i + 4 + length].decode("latin1"), i + 4 + _pad(length)
    if kind == 1:
        return DOUBLE.unpack_from(b, i)[0], i + 8
    if kind in (0, 2):
        return INT.unpack_from(b, i)[0], i + 4
    return None, None


def parse_records(b: bytes) -> list[dict]:
    """Walk one property chunk. Attribute ids are local to the chunk."""
    names: dict[int, str] = {}
    records: list[dict] = []
    current: dict | None = None
    i, n = 0, len(b)
    while i + 12 <= n:
        a, c, e = struct.unpack_from("<iii", b, i)
        if e == -1 and a >= 100 and c in (0x56, 0x42):
            current = {} if c == 0x56 else None
            if current is not None:
                records.append(current)
            i += 12
            continue
        if c == 0x34 and a >= 100 and 0 < e < 80:
            j = i + 12
            name = b[j : j + e]
            j += _pad(e)
            if j + 8 <= n and PRINTABLE.fullmatch(name):
                class_len = INT.unpack_from(b, j)[0]
                if 0 < class_len < 80:
                    j += 4 + _pad(class_len)
                    kind = INT.unpack_from(b, j)[0]
                    j += 4
                    if kind in (0, 1, 2, 4):
                        value, end = _read_value(b, j, kind)
                        if end:
                            names[a] = name.decode()
                            if current is not None and kind != 0:
                                current[names[a]] = value
                            i = end
                            continue
        if a == 1 and c in names and e in (0, 1, 2, 4):
            value, end = _read_value(b, i + 12, e)
            if end:
                if current is not None and e != 0:
                    current[names[c]] = value
                i = end
                continue
        i += 4
    return records


def to_part(record: dict) -> dict | None:
    match = CG.search(str(record.get("CG Point", "")))
    if not match or "Part Name" not in record:
        return None
    part = {out: str(record[key]).strip() for key, out in KEEP_FIELDS.items() if key in record}
    part["x_in"], part["y_in"], part["z_in"] = (float(v) for v in match.groups())
    return part


def decode(path: Path) -> list[dict]:
    parts: list[dict] = []
    for chunk in inflate_chunks(path.read_bytes()):
        if len(chunk) == 65536 or len(chunk) > 3_000_000 or b"Part Name" not in chunk:
            continue
        parts.extend(p for p in map(to_part, parse_records(chunk)) if p)
    return parts


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    source = Path(sys.argv[1])
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("ship-data/parts.json")
    parts = decode(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"source": source.name, "parts": parts}, indent=0), encoding="utf-8")
    print(f"{len(parts)} parts written to {target}")


if __name__ == "__main__":
    main()
