#!/usr/bin/env python3
"""Build the privacy-safe X2D container resource used by the macOS app."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import struct
import tempfile
from io import BytesIO
from pathlib import Path

from PIL import Image

from raf2hncs.tiff import TiffReader, inspect_x2d, patch_as_shot_neutral, patch_tiff_tags


EXPECTED_SOURCE_SHA256 = "dcc5a4abe3498e6f25e89bb491995fd12c3b669d9277c71b45b49210d3e56280"
SANITIZED_RAW_DATA_ID = b"01409AB100000000"
SANITIZED_IMAGE_ID = "000000000000000001409AB100000000"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_region(path: Path, offset: int, length: int) -> str:
    digest = hashlib.sha256()
    remaining = length
    with path.open("rb") as handle:
        handle.seek(offset)
        while remaining:
            chunk = handle.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("truncated region while hashing")
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def neutral_preview() -> bytes:
    image = Image.new("RGB", (64, 48), (96, 96, 96))
    encoded = BytesIO()
    image.save(encoded, format="JPEG", quality=75, optimize=False, progressive=False)
    return encoded.getvalue()


def maker_identity_slots(path: Path) -> list[tuple[int, int, bytes]]:
    slots: list[tuple[int, int, bytes]] = []
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        exif = reader.ifd(int(reader.required(ifd0, 34665)[0]))
        maker_entry = exif[37500]
        maker_offset, _ = reader.value_location(maker_entry)
        maker = reader.ifd(maker_offset)
        for tag in (0x0060, 0x0061):
            entry = maker[tag]
            offset, size = reader.value_location(entry)
            reader.handle.seek(offset)
            original = reader.handle.read(size)
            if len(original) != size:
                raise ValueError(f"truncated MakerNote identity tag 0x{tag:04x}")
            slots.append((offset, size, original.rstrip(b"\0")))
        calibration_entry = maker[0x0019]
        calibration_offset, calibration_size = reader.value_location(calibration_entry)
        reader.handle.seek(calibration_offset)
        calibration = reader.handle.read(calibration_size)
        marker = b"isctool "
        marker_offset = calibration.index(marker)
        tool_end = calibration.index(b"\0", marker_offset)
        serial_start = tool_end + 1
        while serial_start < len(calibration) and calibration[serial_start] == 0:
            serial_start += 1
        serial_end = calibration.index(b"\0", serial_start)
        if not 1 <= serial_end - serial_start <= 64:
            raise ValueError("unexpected embedded lens identity layout")
        slots.append(
            (
                calibration_offset + serial_start,
                serial_end - serial_start + 1,
                calibration[serial_start:serial_end],
            )
        )
    return slots


def overwrite_constant_region(path: Path, offset: int, length: int, value: bytes) -> None:
    if not value or length % len(value):
        raise ValueError("constant region value must divide the target length")
    block = value * min(524288, length // len(value))
    remaining = length
    with path.open("r+b") as handle:
        handle.seek(offset)
        while remaining:
            chunk = block[: min(len(block), remaining)]
            handle.write(chunk)
            remaining -= len(chunk)
        handle.flush()
        os.fsync(handle.fileno())


def sanitize(source: Path, output: Path) -> dict[str, object]:
    source_sha = sha256_file(source)
    if source_sha != EXPECTED_SOURCE_SHA256:
        raise ValueError("source donor does not match the admitted X2D container")

    source_layout = inspect_x2d(source)
    source_raw_sha256 = sha256_region(source, source_layout.strip_offset, source_layout.strip_byte_count)
    source_preview_sha256 = sha256_region(
        source, source_layout.preview_offset, source_layout.preview_byte_count
    )
    identity_slots = maker_identity_slots(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, output)

    endian = "<" if source_layout.byte_order == "little" else ">"
    overwrite_constant_region(
        output,
        source_layout.strip_offset,
        source_layout.strip_byte_count,
        struct.pack(endian + "H", source_layout.black_level),
    )

    preview = neutral_preview()
    if len(preview) > source_layout.preview_byte_count:
        raise ValueError("neutral preview does not fit the donor preview region")
    with output.open("r+b") as handle:
        handle.seek(source_layout.preview_offset)
        handle.write(preview)
        remaining = source_layout.preview_byte_count - len(preview)
        zero_block = b"\0" * min(1024 * 1024, remaining)
        while remaining:
            chunk = zero_block[: min(len(zero_block), remaining)]
            handle.write(chunk)
            remaining -= len(chunk)

    patch_tiff_tags(
        output,
        [
            ("IFD0", 306, "1970:01:01 00:00:00", "ModifyDate"),
            ("IFD0", 33432, "", "Copyright"),
            ("IFD0", 50781, SANITIZED_RAW_DATA_ID, "RawDataUniqueID"),
            ("ExifIFD", 33434, 1.0, "ExposureTime"),
            ("ExifIFD", 33437, 1.0, "FNumber"),
            ("ExifIFD", 34850, 0, "ExposureProgram"),
            ("ExifIFD", 34855, 100, "ISO"),
            ("ExifIFD", 36867, "1970:01:01 00:00:00", "DateTimeOriginal"),
            ("ExifIFD", 37380, 0.0, "ExposureCompensation"),
            ("ExifIFD", 37381, 1.0, "MaxApertureValue"),
            ("ExifIFD", 37383, 0, "MeteringMode"),
            ("ExifIFD", 37385, 0, "Flash"),
            ("ExifIFD", 37386, 0.0, "FocalLength"),
            ("ExifIFD", 41989, 0, "FocalLengthIn35mmFormat"),
            ("ExifIFD", 42016, SANITIZED_IMAGE_ID, "ImageUniqueID"),
            ("ExifIFD", 42035, "", "LensMake"),
            ("ExifIFD", 42036, "", "LensModel"),
        ],
    )
    patch_as_shot_neutral(output, [1.0, 1.0, 1.0])

    with output.open("r+b") as handle:
        for offset, size, _ in identity_slots:
            handle.seek(offset)
            handle.write(b"\0" * size)
        handle.flush()
        os.fsync(handle.fileno())

    sanitized_layout = inspect_x2d(output)
    if sanitized_layout != source_layout.__class__(
        **{
            **source_layout.__dict__,
            "raw_data_unique_id": SANITIZED_RAW_DATA_ID.decode("ascii"),
        }
    ):
        raise AssertionError("sanitization changed the required X2D container layout")

    with output.open("rb") as handle:
        handle.seek(source_layout.strip_offset)
        raw_digest = hashlib.sha256(handle.read(source_layout.strip_byte_count)).hexdigest()
        handle.seek(source_layout.preview_offset)
        preview_region = handle.read(source_layout.preview_byte_count)
    if not preview_region.startswith(preview) or any(preview_region[len(preview) :]):
        raise AssertionError("preview region was not fully sanitized")
    sanitized_bytes = output.read_bytes()
    for _, _, original in identity_slots:
        if original and original in sanitized_bytes:
            raise AssertionError("a donor identity value remains in the sanitized resource")
    sanitized_preview_sha256 = hashlib.sha256(preview_region).hexdigest()
    if raw_digest == source_raw_sha256 or sanitized_preview_sha256 == source_preview_sha256:
        raise AssertionError("original donor image data remains in the sanitized resource")

    return {
        "schema": 1,
        "source_sha256": source_sha,
        "sanitized_sha256": sha256_file(output),
        "file_size": output.stat().st_size,
        "raw_region": {
            "offset": source_layout.strip_offset,
            "byte_count": source_layout.strip_byte_count,
            "fill_value": source_layout.black_level,
            "sha256": raw_digest,
            "source_sha256": source_raw_sha256,
            "source_pixels_absent": True,
        },
        "preview_region": {
            "offset": source_layout.preview_offset,
            "capacity": source_layout.preview_byte_count,
            "jpeg_bytes": len(preview),
            "jpeg_sha256": hashlib.sha256(preview).hexdigest(),
            "region_sha256": sanitized_preview_sha256,
            "source_region_sha256": source_preview_sha256,
            "source_preview_absent": True,
            "remaining_bytes_zero": True,
        },
        "identity": {
            "makernote_identity_slots_cleared": len(identity_slots),
            "capture_tags_neutralized": True,
            "raw_data_unique_id": SANITIZED_RAW_DATA_ID.decode("ascii"),
        },
        "layout": {
            "make": sanitized_layout.make,
            "model": sanitized_layout.model,
            "width": sanitized_layout.width,
            "height": sanitized_layout.height,
            "bits_per_sample": sanitized_layout.bits_per_sample,
            "compression": sanitized_layout.compression,
            "crop_origin": list(sanitized_layout.crop_origin),
            "crop_size": list(sanitized_layout.crop_size),
            "black_level": sanitized_layout.black_level,
            "white_level": sanitized_layout.white_level,
        },
    }


def write_deterministic_gzip(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_handle, destination.open("wb") as raw_output:
        with gzip.GzipFile(filename="SanitizedX2DTemplate.3FR", mode="wb", fileobj=raw_output, mtime=0) as compressed:
            shutil.copyfileobj(input_handle, compressed, length=1024 * 1024)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-gzip", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="raf3fr-sanitized-donor-") as temporary:
        expanded = Path(temporary) / "SanitizedX2DTemplate.3FR"
        evidence = sanitize(args.source, expanded)
        write_deterministic_gzip(expanded, args.output_gzip)
        evidence["gzip_sha256"] = sha256_file(args.output_gzip)
        evidence["gzip_size"] = args.output_gzip.stat().st_size
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    main()
