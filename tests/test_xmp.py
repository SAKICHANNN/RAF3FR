from __future__ import annotations

import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from raf2hncs.xmp import append_ifd0_xmp, build_fuji_xmp, read_xmp_payload


def _tiny_tiff(path: Path) -> None:
    old_xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"/>'
    ifd_offset = 8
    entry_count = 2
    payload_offset = ifd_offset + 2 + entry_count * 12 + 4
    orientation = struct.pack("<HHI", 274, 3, 1) + struct.pack("<H", 1) + b"\0\0"
    xmp = struct.pack("<HHII", 700, 1, len(old_xmp), payload_offset)
    path.write_bytes(
        b"II" + struct.pack("<H", 42) + struct.pack("<I", ifd_offset)
        + struct.pack("<H", entry_count) + orientation + xmp + b"\0\0\0\0" + old_xmp
    )


def _packet(
    *,
    preserve_location: bool = True,
    preserve_rights: bool = True,
    preserve_provenance: bool = True,
    existing_payload: bytes | None = None,
) -> bytes:
    return build_fuji_xmp(
        safe_metadata={
            "time": {
                "date_time_original": "2026:08:27 16:06:26",
                "subsec_time_original": "65",
                "offset_time_original": "+08:00",
            },
            "location": {
                "present": True,
                "latitude": 30.2440888888889,
                "longitude": 120.161971388889,
                "altitude_m": 20,
                "map_datum": "WGS-84",
            },
            "rights": {
                "rating": 4,
                "artist": "Miao & Co",
                "copyright": "Copyright <Miao>",
                "user_comment": "note > draft",
            },
            "provenance": {
                "original_make": "FUJIFILM",
                "original_model": "GFX100RF",
                "source_firmware": "0112",
            },
        },
        framing={"orientation": 8},
        capture_state={"shutter_type": {"code": 0, "value": "mechanical"}},
        rendering_intent={"creative": {"film_simulation": {"value": "reala-ace"}}},
        source_name="DSCF0001.RAF",
        existing_payload=existing_payload,
        preserve_location=preserve_location,
        preserve_rights=preserve_rights,
        preserve_provenance=preserve_provenance,
    )


def test_xmp_packet_is_parseable_standard_and_private_metadata() -> None:
    packet = _packet()
    root = ET.fromstring(packet.decode("utf-8"))
    serialized = ET.tostring(root, encoding="unicode")
    assert "2026-08-27T16:06:26.65+08:00" in serialized
    assert "30,14.6453333333N" in serialized
    assert "120,9.7182833333E" in serialized
    assert "Miao &amp; Co" in serialized
    assert "Copyright &lt;Miao&gt;" in serialized
    assert "FUJIFILM" in serialized
    assert "reala-ace" in serialized


def test_xmp_location_can_be_omitted_without_losing_provenance() -> None:
    packet = _packet(preserve_location=False)
    serialized = ET.tostring(ET.fromstring(packet.decode("utf-8")), encoding="unicode")
    assert "GPSLatitude" not in serialized
    assert "GFX100RF" in serialized


def test_xmp_privacy_policies_remove_values_from_existing_packet() -> None:
    packet = _packet(
        preserve_location=False,
        preserve_rights=False,
        preserve_provenance=False,
        existing_payload=_packet(),
    )
    serialized = ET.tostring(ET.fromstring(packet.decode("utf-8")), encoding="unicode")
    for excluded in (
        "GPSLatitude",
        "GPSLongitude",
        "GPSAltitude",
        "Miao &amp; Co",
        "Copyright &lt;Miao&gt;",
        "DSCF0001.RAF",
        "GFX100RF",
    ):
        assert excluded not in serialized
    assert "FujiRenderingIntent" in serialized


def test_xmp_append_repoints_ifd0_without_moving_existing_bytes(tmp_path: Path) -> None:
    path = tmp_path / "tiny.3fr"
    _tiny_tiff(path)
    before = path.read_bytes()
    packet = _packet()
    report = append_ifd0_xmp(path, packet)
    after = path.read_bytes()
    assert after[8 : len(before)] == before[8:]
    assert after[:4] == before[:4]
    assert after[4:8] != before[4:8]
    assert report["pointer_range"] == [4, 8]
    assert report["append_range"] == [len(before), len(after)]
    assert read_xmp_payload(path) == packet
