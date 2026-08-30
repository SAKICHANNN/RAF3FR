from __future__ import annotations

import dataclasses
import hashlib
import os
import struct
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO


TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8, 11: 4, 12: 8}


@dataclasses.dataclass(frozen=True)
class IfdEntry:
    tag: int
    type_id: int
    count: int
    value_or_offset: bytes
    entry_offset: int


class TiffReader:
    def __init__(self, path: Path):
        self.path = path
        self.handle: BinaryIO = path.open("rb")
        header = self.handle.read(8)
        if len(header) != 8 or header[:2] not in (b"II", b"MM"):
            raise ValueError("not a classic TIFF file")
        self.endian = "<" if header[:2] == b"II" else ">"
        if struct.unpack(self.endian + "H", header[2:4])[0] != 42:
            raise ValueError("unsupported TIFF magic")
        self.first_ifd = struct.unpack(self.endian + "I", header[4:8])[0]

    def close(self) -> None:
        self.handle.close()

    def __enter__(self) -> "TiffReader":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def ifd(self, offset: int) -> dict[int, IfdEntry]:
        self.handle.seek(offset)
        count_data = self.handle.read(2)
        if len(count_data) != 2:
            raise ValueError(f"truncated IFD at {offset}")
        count = struct.unpack(self.endian + "H", count_data)[0]
        entries: dict[int, IfdEntry] = {}
        for _ in range(count):
            entry_offset = self.handle.tell()
            raw = self.handle.read(12)
            if len(raw) != 12:
                raise ValueError(f"truncated IFD entry at {self.handle.tell()}")
            tag, type_id, item_count = struct.unpack(self.endian + "HHI", raw[:8])
            entries[tag] = IfdEntry(tag, type_id, item_count, raw[8:12], entry_offset)
        return entries

    def values(self, entry: IfdEntry) -> list[int | float | str]:
        if entry.type_id not in TYPE_SIZES:
            raise ValueError(f"unsupported TIFF type {entry.type_id} for tag {entry.tag}")
        size = TYPE_SIZES[entry.type_id] * entry.count
        if size <= 4:
            raw = entry.value_or_offset[:size]
        else:
            offset = struct.unpack(self.endian + "I", entry.value_or_offset)[0]
            self.handle.seek(offset)
            raw = self.handle.read(size)
            if len(raw) != size:
                raise ValueError(f"truncated value for tag {entry.tag}")
        if entry.type_id == 2:
            return [raw.rstrip(b"\0").decode("utf-8", "replace")]
        formats = {1: "B", 3: "H", 4: "I", 7: "B", 9: "i", 11: "f", 12: "d"}
        if entry.type_id in formats:
            return list(struct.unpack(self.endian + formats[entry.type_id] * entry.count, raw))
        if entry.type_id in (5, 10):
            signed = entry.type_id == 10
            fmt = "i" if signed else "I"
            integers = struct.unpack(self.endian + fmt * entry.count * 2, raw)
            return [integers[i] / integers[i + 1] for i in range(0, len(integers), 2)]
        raise ValueError(f"unsupported TIFF type {entry.type_id}")

    def value_location(self, entry: IfdEntry) -> tuple[int, int]:
        if entry.type_id not in TYPE_SIZES:
            raise ValueError(f"unsupported TIFF type {entry.type_id} for tag {entry.tag}")
        size = TYPE_SIZES[entry.type_id] * entry.count
        if size <= 4:
            return entry.entry_offset + 8, size
        return struct.unpack(self.endian + "I", entry.value_or_offset)[0], size

    def required(self, entries: dict[int, IfdEntry], tag: int) -> list[int | float | str]:
        if tag not in entries:
            raise ValueError(f"required TIFF tag {tag} is missing")
        return self.values(entries[tag])


@dataclasses.dataclass(frozen=True)
class X2DLayout:
    byte_order: str
    make: str
    model: str
    width: int
    height: int
    bits_per_sample: int
    compression: int
    strip_offset: int
    strip_byte_count: int
    preview_offset: int
    preview_byte_count: int
    crop_origin: tuple[int, int]
    crop_size: tuple[int, int]
    black_level: int
    white_level: int
    file_size: int
    preview_width: int | None = None
    preview_height: int | None = None
    software: str | None = None
    raw_data_unique_id: str | None = None

    @property
    def payload_end(self) -> int:
        return self.strip_offset + self.strip_byte_count

    @property
    def preview_end(self) -> int:
        return self.preview_offset + self.preview_byte_count

    @property
    def required_file_end(self) -> int:
        return max(self.payload_end, self.preview_end)

    @property
    def complete(self) -> bool:
        return self.file_size >= self.required_file_end


def inspect_x2d(path: Path) -> X2DLayout:
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        make = str(reader.required(ifd0, 271)[0])
        model = str(reader.required(ifd0, 272)[0])
        software = str(reader.values(ifd0[305])[0]) if 305 in ifd0 else None
        raw_data_unique_id = None
        if 50781 in ifd0:
            raw_id_values = reader.values(ifd0[50781])
            try:
                raw_data_unique_id = bytes(int(value) for value in raw_id_values).decode("ascii")
            except (TypeError, ValueError, UnicodeDecodeError):
                raw_data_unique_id = None
        preview_offsets = [int(value) for value in reader.required(ifd0, 273)]
        preview_counts = [int(value) for value in reader.required(ifd0, 279)]
        preview_width = int(reader.required(ifd0, 256)[0])
        preview_height = int(reader.required(ifd0, 257)[0])
        subifd_offset = int(reader.required(ifd0, 330)[0])
        raw = reader.ifd(subifd_offset)
        width = int(reader.required(raw, 256)[0])
        height = int(reader.required(raw, 257)[0])
        bits = int(reader.required(raw, 258)[0])
        compression = int(reader.required(raw, 259)[0])
        offsets = [int(value) for value in reader.required(raw, 273)]
        counts = [int(value) for value in reader.required(raw, 279)]
        crop_origin = tuple(int(value) for value in reader.required(raw, 50719))
        crop_size = tuple(int(value) for value in reader.required(raw, 50720))
        black = int(float(reader.required(raw, 50714)[0]))
        white = int(float(reader.required(raw, 50717)[0]))

    if len(offsets) != 1 or len(counts) != 1 or len(preview_offsets) != 1 or len(preview_counts) != 1:
        raise ValueError("only a one-strip X2D donor is supported")
    if len(crop_origin) != 2 or len(crop_size) != 2:
        raise ValueError("invalid X2D crop tags")
    if bits != 16 or compression != 1:
        raise ValueError(f"X2D donor must be uncompressed 16-bit RAW, got bits={bits}, compression={compression}")
    expected = width * height * 2
    if counts[0] != expected:
        raise ValueError(f"RAW strip length {counts[0]} does not match {width}x{height}x2={expected}")
    if not make.lower().startswith("hasselblad") or "x2d 100c" not in model.lower():
        raise ValueError(f"donor is not an X2D 100C: {make} {model}")
    return X2DLayout(
        byte_order="little" if reader.endian == "<" else "big",
        make=make,
        model=model,
        width=width,
        height=height,
        bits_per_sample=bits,
        compression=compression,
        strip_offset=offsets[0],
        strip_byte_count=counts[0],
        preview_offset=preview_offsets[0],
        preview_byte_count=preview_counts[0],
        crop_origin=(crop_origin[0], crop_origin[1]),
        crop_size=(crop_size[0], crop_size[1]),
        black_level=black,
        white_level=white,
        file_size=path.stat().st_size,
        preview_width=preview_width,
        preview_height=preview_height,
        software=software,
        raw_data_unique_id=raw_data_unique_id,
    )


def encode_unsigned_rationals(values: list[float], endian: str) -> bytes:
    encoded: list[int] = []
    for value in values:
        if not value > 0:
            raise ValueError("TIFF rational values must be positive")
        fraction = Fraction(value).limit_denominator(1_000_000)
        encoded.extend((fraction.numerator, fraction.denominator))
    return struct.pack(endian + "I" * len(encoded), *encoded)


def encode_tiff_values(entry: IfdEntry, values: object, endian: str) -> bytes:
    """Encode values into an existing TIFF slot without changing its type/count."""
    if entry.type_id == 2:
        if not isinstance(values, str):
            raise TypeError(f"ASCII TIFF tag {entry.tag} requires a string")
        encoded = values.encode("ascii") + b"\0"
        if len(encoded) > entry.count:
            raise ValueError(f"value for TIFF tag {entry.tag} exceeds its fixed slot")
        return encoded.ljust(entry.count, b"\0")
    if entry.type_id in (1, 7) and isinstance(values, bytes):
        if len(values) != entry.count:
            raise ValueError(f"byte value for TIFF tag {entry.tag} has the wrong length")
        return values
    items = list(values) if isinstance(values, (list, tuple)) else [values]
    if len(items) != entry.count:
        raise ValueError(f"TIFF tag {entry.tag} expects {entry.count} values")
    formats = {1: "B", 3: "H", 4: "I", 7: "B", 9: "i", 11: "f", 12: "d"}
    if entry.type_id in formats:
        return struct.pack(endian + formats[entry.type_id] * entry.count, *items)
    if entry.type_id in (5, 10):
        encoded: list[int] = []
        signed = entry.type_id == 10
        for value in items:
            fraction = Fraction(float(value)).limit_denominator(1_000_000)
            if not signed and fraction.numerator < 0:
                raise ValueError(f"unsigned rational TIFF tag {entry.tag} cannot be negative")
            encoded.extend((fraction.numerator, fraction.denominator))
        fmt = "i" if signed else "I"
        return struct.pack(endian + fmt * len(encoded), *encoded)
    raise ValueError(f"unsupported TIFF type {entry.type_id} for tag {entry.tag}")


def patch_tiff_tags(
    path: Path, specifications: list[tuple[str, int, object, str]]
) -> list[dict[str, object]]:
    """Patch existing IFD0/ExifIFD slots and return exact changed ranges."""
    prepared: list[tuple[int, bytes, dict[str, object]]] = []
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        directories = {"IFD0": ifd0}
        if any(directory == "ExifIFD" for directory, *_ in specifications):
            exif_offset = int(reader.required(ifd0, 34665)[0])
            directories["ExifIFD"] = reader.ifd(exif_offset)
        for directory, tag, values, name in specifications:
            entries = directories.get(directory)
            if entries is None or tag not in entries:
                raise ValueError(f"required {directory} TIFF tag {tag} ({name}) is missing")
            entry = entries[tag]
            offset, size = reader.value_location(entry)
            raw = encode_tiff_values(entry, values, reader.endian)
            if len(raw) != size:
                raise AssertionError(f"encoded size changed for TIFF tag {tag}")
            prepared.append(
                (
                    offset,
                    raw,
                    {
                        "tag": name,
                        "directory": directory,
                        "tag_id": tag,
                        "range": [offset, offset + size],
                        "old": reader.values(entry),
                        "new": values.hex() if isinstance(values, bytes) else values,
                    },
                )
            )
    with path.open("r+b") as handle:
        for offset, raw, _ in prepared:
            handle.seek(offset)
            handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return [record for _, _, record in prepared]


def hasselblad_makernote_tag_info(
    path: Path, tag: int
) -> tuple[int, int, int, int, str]:
    """Return directory-entry and payload details for a Hasselblad MakerNote tag."""
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        exif_offset = int(reader.required(ifd0, 34665)[0])
        exif = reader.ifd(exif_offset)
        maker_entry = exif.get(37500)
        if maker_entry is None or maker_entry.type_id != 7:
            raise ValueError("required Hasselblad MakerNote is missing")
        maker_offset, _ = reader.value_location(maker_entry)
        maker = reader.ifd(maker_offset)
        entry = maker.get(tag)
        if entry is None:
            raise ValueError(f"required Hasselblad MakerNote tag 0x{tag:04x} is missing")
        payload_offset, payload_size = reader.value_location(entry)
        reader.handle.seek(payload_offset)
        payload = reader.handle.read(payload_size)
        if len(payload) != payload_size:
            raise ValueError(f"truncated Hasselblad MakerNote tag 0x{tag:04x}")
        return (
            entry.entry_offset,
            entry.type_id,
            entry.count,
            payload_size,
            hashlib.sha256(payload).hexdigest(),
        )


def neutralize_hasselblad_lens_correction(path: Path) -> dict[str, object]:
    """Hide the private XCD lens-dispatch tag while preserving its payload bytes.

    Phocus uses MakerNote tag 0x0018 together with 0x0017 to select and apply the
    donor XCD vignetting profile. Retagging only the dispatch entry is the
    smallest reversible edit and leaves the 17-byte private payload in place.
    """
    source_tag = 0x0018
    replacement_tag = 0xFF18
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        exif_offset = int(reader.required(ifd0, 34665)[0])
        exif = reader.ifd(exif_offset)
        maker_entry = exif.get(37500)
        if maker_entry is None or maker_entry.type_id != 7:
            raise ValueError("required Hasselblad MakerNote is missing")
        maker_offset, _ = reader.value_location(maker_entry)
        maker = reader.ifd(maker_offset)
        if replacement_tag in maker:
            raise ValueError("reserved neutralized MakerNote tag 0xff18 already exists")
        entry = maker.get(source_tag)
        if entry is None:
            raise ValueError("required Hasselblad lens-dispatch MakerNote tag 0x0018 is missing")
        if entry.type_id != 7 or entry.count != 17:
            raise ValueError(
                "unsupported Hasselblad lens-dispatch layout: "
                f"type={entry.type_id}, count={entry.count}"
            )
        payload_offset, payload_size = reader.value_location(entry)
        reader.handle.seek(payload_offset)
        payload = reader.handle.read(payload_size)
        if len(payload) != payload_size:
            raise ValueError("truncated Hasselblad lens-dispatch payload")
        payload_sha256 = hashlib.sha256(payload).hexdigest()
        raw_tag = struct.pack(reader.endian + "H", replacement_tag)
        entry_offset = entry.entry_offset

    with path.open("r+b") as handle:
        handle.seek(entry_offset)
        handle.write(raw_tag)
        handle.flush()
        os.fsync(handle.fileno())

    return {
        "tag": "XCDLensCorrectionDispatch",
        "directory": "HasselbladMakerNote",
        "tag_id": source_tag,
        "replacement_tag_id": replacement_tag,
        "range": [entry_offset, entry_offset + 2],
        "payload_range": [payload_offset, payload_offset + payload_size],
        "payload_sha256": payload_sha256,
        "old": f"0x{source_tag:04x}",
        "new": f"0x{replacement_tag:04x}",
    }


def tiff_tag_range(path: Path, directory: str, tag: int) -> tuple[int, int]:
    """Resolve an existing tag's exact storage range for independent verification."""
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        if directory == "IFD0":
            entries = ifd0
        elif directory == "ExifIFD":
            exif_offset = int(reader.required(ifd0, 34665)[0])
            entries = reader.ifd(exif_offset)
        else:
            raise ValueError(f"unsupported TIFF directory {directory}")
        if tag not in entries:
            raise ValueError(f"required {directory} TIFF tag {tag} is missing")
        offset, size = reader.value_location(entries[tag])
        return offset, offset + size


def as_shot_neutral_info(path: Path) -> tuple[int, int, list[float], str]:
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        entry = ifd0.get(50728)
        if entry is None or entry.type_id != 5 or entry.count != 3:
            raise ValueError("X2D donor does not have a three-channel AsShotNeutral tag")
        values = [float(value) for value in reader.values(entry)]
        offset, size = reader.value_location(entry)
        return offset, size, values, reader.endian


def patch_as_shot_neutral(path: Path, wb_coeffs: list[float]) -> dict[str, object]:
    if len(wb_coeffs) < 3 or any(not value > 0 for value in wb_coeffs[:3]):
        raise ValueError("source white-balance coefficients must contain positive R, G, B values")
    neutral = [wb_coeffs[1] / wb_coeffs[0], 1.0, wb_coeffs[1] / wb_coeffs[2]]
    offset, size, old, endian = as_shot_neutral_info(path)
    raw = encode_unsigned_rationals(neutral, endian)
    if len(raw) != size:
        raise AssertionError("AsShotNeutral encoded length changed")
    with path.open("r+b") as handle:
        handle.seek(offset)
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return {"tag": "AsShotNeutral", "range": [offset, offset + size], "old": old, "new": neutral}
