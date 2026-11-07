"""The .nwd reader, on small files built the way the real format is laid out."""
import struct
import zlib

from app.nwd import GEOMETRY_CHUNK, HEADER_BYTES, MAX_PROPERTY_CHUNK, PROPERTY_MARKER, decode


def text(value: str) -> bytes:
    raw = value.encode()
    return struct.pack("<i", len(raw)) + raw + b"\0" * (-len(raw) % 4)


def attribute(attribute_id: int, name: str, value: str) -> bytes:
    return (struct.pack("<ii", attribute_id, 0x34) + text(name) + text("LcClass")
            + struct.pack("<i", 4) + text(value))


def property_chunk(part_name: str) -> bytes:
    return (struct.pack("<iii", 100, 0x56, -1)
            + attribute(101, "Part Name", part_name)
            + attribute(102, "Description", "CLEAR OPENING 32x78")
            + attribute(103, "CG Point", "x=-1.5, y=2.5, z=3.5"))


def model(*chunks: bytes) -> bytes:
    return b"#LcUStream".ljust(HEADER_BYTES, b"\0") + b"".join(chunks)


def geometry() -> bytes:
    return zlib.compress(b"\x11" * GEOMETRY_CHUNK)


def properties(name: str) -> bytes:
    return zlib.compress(property_chunk(name))


def write(tmp_path, data):
    path = tmp_path / "model.nwd"
    path.write_bytes(data)
    return path


def test_reads_parts_with_their_position_and_description(tmp_path):
    path = write(tmp_path, model(geometry(), b"\0\0\0\0", properties("DOOR 212")))
    assert decode(path) == [{"name": "DOOR 212", "description": "CLEAR OPENING 32x78",
                             "x_in": -1.5, "y_in": 2.5, "z_in": 3.5}]


def test_skips_the_geometry_by_starting_at_the_marker(tmp_path):
    # Corrupt geometry proves that it was never read.
    corrupt = b"\x78\x9c" + b"\xff" * 2000
    path = write(tmp_path, model(corrupt, PROPERTY_MARKER[:4], properties("DOOR 212")))
    assert [part["name"] for part in decode(path)] == ["DOOR 212"]


def test_reads_several_property_chunks(tmp_path):
    path = write(tmp_path, model(geometry(), b"\0\0\0\0", properties("DOOR 1"), properties("DOOR 2")))
    assert [part["name"] for part in decode(path)] == ["DOOR 1", "DOOR 2"]


def test_stops_at_the_first_large_chunk_after_the_properties(tmp_path):
    large = zlib.compress(b"\0" * (MAX_PROPERTY_CHUNK + 1))
    path = write(tmp_path, model(geometry(), b"\0\0\0\0", properties("DOOR 1"), large, properties("LATER")))
    assert [part["name"] for part in decode(path)] == ["DOOR 1"]


def test_falls_back_to_the_whole_file_without_a_marker(tmp_path):
    path = write(tmp_path, model(geometry(), properties("DOOR 212")))
    assert [part["name"] for part in decode(path)] == ["DOOR 212"]


def test_falls_back_when_the_marker_leads_to_nothing(tmp_path):
    misleading = zlib.compress(b"nothing useful here")
    path = write(tmp_path, model(properties("DOOR 212"), b"\0\0\0\0", misleading))
    assert [part["name"] for part in decode(path)] == ["DOOR 212"]


def test_a_file_with_no_parts_gives_an_empty_list(tmp_path):
    assert decode(write(tmp_path, b"this is not a real model")) == []
