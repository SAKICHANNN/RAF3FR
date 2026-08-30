from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .tiff import TiffReader


XMP_TAG = 700
_NS = {
    "x": "adobe:ns:meta/",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "xmp": "http://ns.adobe.com/xap/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "exif": "http://ns.adobe.com/exif/1.0/",
    "raf3fr": "https://raf3fr.app/ns/1.0/",
}
for _prefix, _uri in _NS.items():
    ET.register_namespace(_prefix, _uri)


def _qname(prefix: str, name: str) -> str:
    return f"{{{_NS[prefix]}}}{name}"


def _description(root: ET.Element) -> ET.Element:
    rdf = root.find(f".//{_qname('rdf', 'RDF')}")
    if rdf is None:
        rdf = ET.SubElement(root, _qname("rdf", "RDF"))
    description = rdf.find(_qname("rdf", "Description"))
    if description is None:
        description = ET.SubElement(rdf, _qname("rdf", "Description"))
        description.set(_qname("rdf", "about"), "")
    return description


def _parse_existing(payload: bytes | None) -> ET.Element:
    if payload:
        try:
            root = ET.fromstring(payload.decode("utf-8", errors="strict"))
            if root.tag == _qname("x", "xmpmeta"):
                return root
        except (UnicodeDecodeError, ET.ParseError):
            pass
    return ET.Element(_qname("x", "xmpmeta"))


def _iso_datetime(time: dict[str, object]) -> str | None:
    value = time.get("date_time_original")
    if not isinstance(value, str) or len(value) < 19:
        return None
    base = value[:10].replace(":", "-") + "T" + value[11:19]
    subsecond = time.get("subsec_time_original")
    if subsecond not in (None, ""):
        base += "." + str(subsecond).lstrip(".")
    offset = time.get("offset_time_original")
    if isinstance(offset, str) and offset:
        base += offset
    return base


def _gps_coordinate(value: object, positive: str, negative: str) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    direction = negative if number < 0 else positive
    absolute = abs(number)
    degrees = int(absolute)
    minutes = (absolute - degrees) * 60
    return f"{degrees},{minutes:.10f}".rstrip("0").rstrip(".") + direction


def _replace_sequence(description: ET.Element, name: str, value: str) -> None:
    tag = _qname("dc", name)
    for child in list(description.findall(tag)):
        description.remove(child)
    container = ET.SubElement(description, tag)
    sequence = ET.SubElement(container, _qname("rdf", "Seq"))
    ET.SubElement(sequence, _qname("rdf", "li")).text = value


def _replace_alt(description: ET.Element, name: str, value: str) -> None:
    tag = _qname("dc", name)
    for child in list(description.findall(tag)):
        description.remove(child)
    container = ET.SubElement(description, tag)
    alt = ET.SubElement(container, _qname("rdf", "Alt"))
    item = ET.SubElement(alt, _qname("rdf", "li"))
    item.set("{http://www.w3.org/XML/1998/namespace}lang", "x-default")
    item.text = value


def _remove_attribute(description: ET.Element, prefix: str, name: str) -> None:
    description.attrib.pop(_qname(prefix, name), None)


def _remove_children(description: ET.Element, prefix: str, name: str) -> None:
    for child in list(description.findall(_qname(prefix, name))):
        description.remove(child)


def build_fuji_xmp(
    *,
    safe_metadata: dict[str, Any],
    framing: dict[str, Any],
    capture_state: dict[str, Any],
    rendering_intent: dict[str, Any],
    source_name: str,
    existing_payload: bytes | None = None,
    preserve_location: bool = True,
    preserve_rights: bool = True,
    preserve_provenance: bool = True,
) -> bytes:
    """Merge safe Fuji provenance and standard metadata into an XMP packet."""

    root = _parse_existing(existing_payload)
    description = _description(root)
    rights = safe_metadata.get("rights", {})
    time = safe_metadata.get("time", {})
    location = safe_metadata.get("location", {})
    provenance = safe_metadata.get("provenance", {})

    _remove_attribute(description, "xmp", "Rating")
    for name in ("creator", "rights", "description"):
        _remove_children(description, "dc", name)
    rating = rights.get("rating")
    if preserve_rights and isinstance(rating, int) and 0 <= rating <= 5:
        description.set(_qname("xmp", "Rating"), str(rating))
    captured = _iso_datetime(time)
    if captured:
        description.set(_qname("xmp", "CreateDate"), captured)
        description.set(_qname("exif", "DateTimeOriginal"), captured)
    artist = rights.get("artist")
    if preserve_rights and isinstance(artist, str) and artist.strip():
        _replace_sequence(description, "creator", artist.strip())
    copyright_text = rights.get("copyright")
    if preserve_rights and isinstance(copyright_text, str) and copyright_text.strip():
        _replace_alt(description, "rights", copyright_text.strip())
    comment = rights.get("user_comment")
    if preserve_rights and isinstance(comment, str) and comment.strip():
        _replace_alt(description, "description", comment.strip())

    for name in ("GPSLatitude", "GPSLongitude", "GPSAltitude", "GPSAltitudeRef", "GPSMapDatum"):
        _remove_attribute(description, "exif", name)
    if preserve_location and location.get("present") is True:
        latitude = _gps_coordinate(location.get("latitude"), "N", "S")
        longitude = _gps_coordinate(location.get("longitude"), "E", "W")
        if latitude and longitude:
            description.set(_qname("exif", "GPSLatitude"), latitude)
            description.set(_qname("exif", "GPSLongitude"), longitude)
        altitude = location.get("altitude_m")
        if isinstance(altitude, (int, float)) and math.isfinite(float(altitude)):
            millimetres = int(round(abs(float(altitude)) * 1000))
            description.set(_qname("exif", "GPSAltitude"), f"{millimetres}/1000")
            description.set(_qname("exif", "GPSAltitudeRef"), "1" if altitude < 0 else "0")
        if location.get("map_datum"):
            description.set(_qname("exif", "GPSMapDatum"), str(location["map_datum"]))

    for name in ("OriginalMake", "OriginalModel", "SourceFirmware", "SourceFileName"):
        _remove_attribute(description, "raf3fr", name)
    if preserve_provenance:
        description.set(_qname("raf3fr", "OriginalMake"), str(provenance.get("original_make") or ""))
        description.set(_qname("raf3fr", "OriginalModel"), str(provenance.get("original_model") or ""))
        description.set(_qname("raf3fr", "SourceFirmware"), str(provenance.get("source_firmware") or ""))
        description.set(_qname("raf3fr", "SourceFileName"), source_name)
    description.set(
        _qname("raf3fr", "Framing"),
        json.dumps(framing, sort_keys=True, separators=(",", ":")),
    )
    description.set(
        _qname("raf3fr", "CaptureState"),
        json.dumps(capture_state, sort_keys=True, separators=(",", ":")),
    )
    description.set(
        _qname("raf3fr", "FujiRenderingIntent"),
        json.dumps(rendering_intent, sort_keys=True, separators=(",", ":")),
    )

    xml = ET.tostring(root, encoding="utf-8", xml_declaration=False)
    return b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n' + xml + b'\n<?xpacket end="w"?>'


def read_xmp_payload(path: Path) -> bytes | None:
    with TiffReader(path) as reader:
        entry = reader.ifd(reader.first_ifd).get(XMP_TAG)
        if entry is None:
            return None
        offset, size = reader.value_location(entry)
        reader.handle.seek(offset)
        payload = reader.handle.read(size)
    if len(payload) != size:
        raise ValueError("truncated XMP packet")
    return payload


def append_ifd0_xmp(path: Path, payload: bytes) -> dict[str, object]:
    """Append XMP and a replacement IFD0, changing only the TIFF root pointer."""

    if not payload.startswith(b"<?xpacket") or len(payload) <= 238:
        raise ValueError("XMP packet is unexpectedly short")
    original_size = path.stat().st_size
    with TiffReader(path) as reader:
        ifd_offset = reader.first_ifd
        reader.handle.seek(ifd_offset)
        count = struct.unpack(reader.endian + "H", reader.handle.read(2))[0]
        entries = [reader.handle.read(12) for _ in range(count)]
        if any(len(entry) != 12 for entry in entries):
            raise ValueError("truncated IFD0")
        next_ifd = reader.handle.read(4)
        if len(next_ifd) != 4:
            raise ValueError("truncated IFD0 next pointer")
        endian = reader.endian

    payload_offset = original_size
    padding = b"\0" if (payload_offset + len(payload)) & 1 else b""
    replacement_ifd_offset = payload_offset + len(payload) + len(padding)
    if replacement_ifd_offset > 0xFFFFFFFF:
        raise ValueError("classic TIFF offset exceeds 32-bit range")
    replacement_entry = struct.pack(
        endian + "HHII", XMP_TAG, 1, len(payload), payload_offset
    )
    retained = [
        entry for entry in entries if struct.unpack(endian + "H", entry[:2])[0] != XMP_TAG
    ]
    all_entries = sorted(
        [*retained, replacement_entry],
        key=lambda entry: struct.unpack(endian + "H", entry[:2])[0],
    )
    replacement_ifd = (
        struct.pack(endian + "H", len(all_entries))
        + b"".join(all_entries)
        + next_ifd
    )

    with path.open("r+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() != original_size:
            raise RuntimeError("file size changed while preparing XMP append")
        handle.write(payload)
        handle.write(padding)
        handle.write(replacement_ifd)
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(4)
        handle.write(struct.pack(endian + "I", replacement_ifd_offset))
        handle.flush()
        os.fsync(handle.fileno())

    installed = read_xmp_payload(path)
    if installed != payload:
        raise RuntimeError("failed to install XMP packet")
    return {
        "mode": "append_replacement_ifd0_xmp",
        "pointer_range": [4, 8],
        "append_range": [original_size, path.stat().st_size],
        "payload_range": [payload_offset, payload_offset + len(payload)],
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
    }
