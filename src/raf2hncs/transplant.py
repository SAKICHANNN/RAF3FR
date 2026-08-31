from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .dng_opcode import append_raw_opcode_list, fuji_lens_opcode_list
from .hashing import sha256
from .lens import _profile_splines, extract_fuji_lens_profile
from .sensor import (
    GFX100RF_TO_X2D100C_D65_BOOTSTRAP,
    adaptive_sensor_mapping,
    transform_wb_coefficients,
)
from .tiff import (
    TiffReader,
    X2DLayout,
    as_shot_neutral_info,
    hasselblad_makernote_tag_info,
    inspect_x2d,
    neutralize_hasselblad_lens_correction,
    patch_as_shot_neutral,
    patch_tiff_tags,
    tiff_tag_range,
)
from .xmp import append_ifd0_xmp, build_fuji_xmp, read_xmp_payload


X2D_100C_OBSERVED_Q16_PROFILES = {
    "01409AB1": {
        "software": "1.1.0",
        "q16_gains": {"R": 67_376, "G1": 65_536, "G2": 65_536, "B": 66_448},
        "evidence_pairs": [
            "B0000079.3FR / Job_0079.fff",
            "B0000080.3FR / Job_0080.fff",
        ],
    },
    "0140784A": {
        "software": "1.0.0",
        "q16_gains": {"R": 65_536, "G1": 65_708, "G2": 65_708, "B": 67_192},
        "evidence_pairs": [
            "0461605618.3fr / Q16X0461605618_0001.fff",
            "9742542576.3fr / Q16X9742542576_0001.fff",
            "8925806215.3fr / Q16X8925806215_0002.fff",
        ],
    },
}

X2D_100C_SELECTABLE_ISO = (64, 100, 200, 400, 800, 1600, 3200, 6400, 12800, 25600)
ISO_POLICIES = ("nearest-x2d", "hnnr-stable", "capture")

# Signal-code equivalents of the read-noise term used by the accepted
# full-plane physical-vignette experiment. The two green sites intentionally
# share one value; the order follows the RGGB parity lattice.
PHYSICAL_VIGNETTE_READ_NOISE_EQUIVALENT = ((0.0, 30.0), (30.0, 9.25))


def x2d_q16_profile(layout: X2DLayout) -> tuple[str, dict[str, object]]:
    raw_id = getattr(layout, "raw_data_unique_id", None) or ""
    cohort = raw_id[:8]
    profile = X2D_100C_OBSERVED_Q16_PROFILES.get(cohort)
    if profile is None:
        raise ValueError(
            "inverse X2D calibration is unavailable for donor calibration cohort "
            f"{cohort or 'unknown'}"
        )
    expected_software = str(profile["software"])
    software = getattr(layout, "software", None)
    if software != expected_software:
        raise ValueError(
            "donor Software tag does not match the observed calibration profile: "
            f"{software!r} != {expected_software!r}"
        )
    return cohort, profile


def publish_no_overwrite(temporary: Path, destination: Path) -> None:
    """Atomically publish a same-directory temporary file without replacement."""
    if temporary.parent.resolve() != destination.parent.resolve():
        raise ValueError("atomic publish requires temporary and destination in one directory")
    try:
        os.link(temporary, destination)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite {destination}") from None
    temporary.unlink()


def write_json_temporary(path: Path, value: dict[str, object]) -> None:
    """Write and fsync a JSON file that is not yet externally published."""
    if path.exists():
        raise FileExistsError(f"remove stale temporary output first: {path}")
    raw = (json.dumps(value, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def hash_ranges(path: Path, ranges: list[tuple[int, int]]) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for start, end in ranges:
            handle.seek(start)
            remaining = end - start
            while remaining:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    raise ValueError("truncated file while hashing byte ranges")
                digest.update(block)
                remaining -= len(block)
    return digest.hexdigest()


def md5_range(path: Path, start: int, end: int) -> str:
    """Return the DNG-style 128-bit identity of a bounded RAW byte range."""
    digest = hashlib.md5()
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start
        while remaining:
            block = handle.read(min(1024 * 1024, remaining))
            if not block:
                raise ValueError("truncated file while hashing RAW identity")
            digest.update(block)
            remaining -= len(block)
    return digest.hexdigest()


def complement_ranges(file_size: int, excluded: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for start, end in sorted(excluded):
        if start < 0 or end < start or end > file_size:
            raise ValueError(f"invalid excluded byte range {(start, end)}")
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for start, end in merged:
        if cursor < start:
            ranges.append((cursor, start))
        cursor = end
    if cursor < file_size:
        ranges.append((cursor, file_size))
    return ranges


def find_tool(path: str | None, name: str) -> str:
    if path:
        candidate = Path(path)
        if candidate.is_file():
            return str(candidate)
        raise FileNotFoundError(candidate)
    found = shutil.which(name)
    if found:
        return found
    configured_directory = os.environ.get("RAF2HNCS_TOOL_DIR")
    local_candidates = [
        Path(configured_directory) / name if configured_directory else None,
        Path.cwd() / ".tools" / "bin" / name,
        Path(__file__).resolve().parents[2] / ".tools" / "bin" / name,
    ]
    for local in local_candidates:
        if local is not None and local.is_file():
            return str(local)
    raise FileNotFoundError(f"cannot find {name}; pass its path explicitly")


def jpeg_dimensions(data: bytes) -> tuple[int, int]:
    """Return the dimensions declared by a complete baseline/progressive JPEG."""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("preview is not a JPEG")
    index = 2
    sof_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
    while index + 4 <= len(data):
        while index < len(data) and data[index] != 0xFF:
            index += 1
        while index < len(data) and data[index] == 0xFF:
            index += 1
        if index >= len(data):
            break
        marker = data[index]
        index += 1
        if marker in (0x01, 0xD8) or 0xD0 <= marker <= 0xD7:
            continue
        if marker in (0xD9, 0xDA) or index + 2 > len(data):
            break
        segment_length = int.from_bytes(data[index:index + 2], "big")
        if segment_length < 2 or index + segment_length > len(data):
            break
        if marker in sof_markers and segment_length >= 7:
            height = int.from_bytes(data[index + 3:index + 5], "big")
            width = int.from_bytes(data[index + 5:index + 7], "big")
            if width > 0 and height > 0:
                return width, height
        index += segment_length
    raise ValueError("JPEG preview has no valid frame dimensions")


def source_preview_for_slot(
    source: Path,
    exiftool: str,
    capacity: int,
    work: Path,
    target_dimensions: tuple[int, int],
) -> tuple[bytes, dict[str, object]]:
    """Extract the RAF preview and, only when needed, recompress it to the donor slot."""
    completed = subprocess.run(
        [exiftool, "-PreviewImage", "-b", str(source)],
        check=True,
        capture_output=True,
    )
    original = completed.stdout
    if not original.startswith(b"\xff\xd8") or not original.rstrip().endswith(
        b"\xff\xd9"
    ):
        raise ValueError("RAF PreviewImage is not a complete JPEG")
    source_dimensions = jpeg_dimensions(original)
    if source_dimensions == target_dimensions and len(original) <= capacity:
        return original, {
            "mode": "source_preview_exact",
            "source_bytes": len(original),
            "embedded_bytes": len(original),
            "jpeg_quality": None,
            "source_dimensions": list(source_dimensions),
            "embedded_dimensions": list(target_dimensions),
        }

    sips = shutil.which("sips")
    if not sips:
        raise ValueError(
            f"RAF preview is {len(original)} bytes but donor slot is {capacity}; "
            "macOS sips is required to recompress it"
        )
    source_jpeg = work / "source-preview.jpg"
    source_jpeg.write_bytes(original)
    for quality in (85, 75, 65, 60, 55, 50, 45, 40):
        candidate = work / f"source-preview-q{quality}.jpg"
        subprocess.run(
            [
                sips,
                "-s",
                "format",
                "jpeg",
                "-s",
                "formatOptions",
                str(quality),
                "--resampleHeightWidth",
                str(target_dimensions[1]),
                str(target_dimensions[0]),
                str(source_jpeg),
                "--out",
                str(candidate),
            ],
            check=True,
            capture_output=True,
        )
        encoded = candidate.read_bytes()
        if (
            encoded.startswith(b"\xff\xd8")
            and encoded.rstrip().endswith(b"\xff\xd9")
            and len(encoded) <= capacity
        ):
            return encoded, {
                "mode": "source_preview_recompressed",
                "source_bytes": len(original),
                "embedded_bytes": len(encoded),
                "jpeg_quality": quality,
                "source_dimensions": list(source_dimensions),
                "embedded_dimensions": list(jpeg_dimensions(encoded)),
            }
    raise ValueError(
        f"could not fit RAF preview ({len(original)} bytes) into donor slot ({capacity})"
    )


def patch_preview_slot(path: Path, layout: X2DLayout, preview: bytes) -> dict[str, object]:
    if len(preview) > layout.preview_byte_count:
        raise ValueError("source preview exceeds donor preview slot")
    padding = layout.preview_byte_count - len(preview)
    with path.open("r+b") as handle:
        handle.seek(layout.preview_offset)
        handle.write(preview)
        handle.write(b"\0" * padding)
    return {
        "range": [layout.preview_offset, layout.preview_end],
        "jpeg_bytes": len(preview),
        "padding_bytes": padding,
        "sha256": hashlib.sha256(preview).hexdigest(),
    }


def read_fuji_metadata(source: Path, dnglab: str, raw_identify: str) -> dict[str, object]:
    result = subprocess.run(
        [dnglab, "analyze", "--meta", "--json", str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    metadata = json.loads(result.stdout)["data"]["metadata"]
    params = metadata["rawParams"]
    raw_metadata = metadata["rawMetadata"]
    make = str(raw_metadata.get("make", ""))
    model = str(raw_metadata.get("model", ""))
    if make.casefold() != "fujifilm" or model.replace(" ", "").casefold() != "gfx100rf":
        raise ValueError(f"expected Fujifilm GFX100RF source, got {make} {model}".strip())
    identify = subprocess.run(
        [raw_identify, "-v", str(source)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    pattern_line = next((line for line in identify.splitlines() if line.startswith("Filter pattern:")), "")
    pattern = pattern_line.partition(":")[2].strip()[:4]
    if pattern != "RGGB":
        raise ValueError(f"expected full-canvas RGGB source, got {pattern!r}")
    crop = params["cropArea"]
    active = params["activeArea"]
    black = params["blacklevels"]
    return {
        "make": make,
        "model": model,
        "bit_depth": int(params["bitDepth"]),
        "width": int(params["rawWidth"]),
        "height": int(params["rawHeight"]),
        "crop_x": int(crop["p"]["x"]),
        "crop_y": int(crop["p"]["y"]),
        "crop_width": int(crop["d"]["w"]),
        "crop_height": int(crop["d"]["h"]),
        "active_x": int(active["p"]["x"]),
        "active_y": int(active["p"]["y"]),
        "active_width": int(active["d"]["w"]),
        "active_height": int(active["d"]["h"]),
        "black_levels": [int(value.split("/", 1)[0]) for value in black["levels"]],
        "black_width": int(black["width"]),
        "black_height": int(black["height"]),
        "white_level": int(params["whitelevels"][0]),
        "wb_coeffs": [float(value) for value in params["wbCoeffs"][:3]],
        "cfa": pattern,
    }


def wb_coefficients_from_grb_levels(value: str) -> tuple[list[int], list[float]]:
    levels = [int(item) for item in value.split()]
    if len(levels) != 3 or min(levels) <= 0:
        raise ValueError(f"expected three positive Fuji G/R/B white-balance levels, got {value!r}")
    green, red, blue = levels
    return levels, [red / green, 1.0, blue / green]


def read_fuji_white_balances(source: Path, exiftool: str) -> dict[str, object]:
    result = subprocess.run(
        [
            exiftool,
            "-j",
            "-n",
            "-G1",
            "-WB_GRBLevelsAuto",
            "-WB_GRBLevels",
            "-WhiteBalance",
            "-ColorTemperature",
            "-WhiteBalanceFineTune",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    row = json.loads(result.stdout)[0]
    auto_levels, auto_coeffs = wb_coefficients_from_grb_levels(
        row["FujiIFD:WB_GRBLevelsAuto"]
    )
    as_shot_levels, as_shot_coeffs = wb_coefficients_from_grb_levels(
        row["FujiIFD:WB_GRBLevels"]
    )
    return {
        "camera_auto": {"grb_levels": auto_levels, "rgb_coeffs": auto_coeffs},
        "as_shot": {"grb_levels": as_shot_levels, "rgb_coeffs": as_shot_coeffs},
        "mode_code": row.get("FujiFilm:WhiteBalance"),
        "color_temperature_kelvin": row.get("FujiFilm:ColorTemperature"),
        "fine_tune": row.get("FujiFilm:WhiteBalanceFineTune"),
    }


def effective_capture_iso(row: dict[str, object]) -> tuple[int, int, str]:
    iso_field = int(row["ExifIFD:ISO"])
    sensitivity_type = int(row.get("ExifIFD:SensitivityType", 0))
    standard_output_sensitivity = row.get("ExifIFD:StandardOutputSensitivity")
    if sensitivity_type in (1, 4, 5, 7) and standard_output_sensitivity is not None:
        return (
            int(standard_output_sensitivity),
            iso_field,
            "ExifIFD:StandardOutputSensitivity",
        )
    return iso_field, iso_field, "ExifIFD:ISO"


def read_fuji_capture_metadata(source: Path, exiftool: str) -> dict[str, object]:
    from .fuji_rendering import fuji_rendering_intent
    from .fuji_metadata import fuji_capture_state, fuji_framing, fuji_safe_metadata

    tags = [
        "Make",
        "Model",
        "ModifyDate",
        "ExposureTime",
        "FNumber",
        "ExposureProgram",
        "ISO",
        "SensitivityType",
        "StandardOutputSensitivity",
        "DateTimeOriginal",
        "CreateDate",
        "OffsetTime",
        "OffsetTimeOriginal",
        "OffsetTimeDigitized",
        "ShutterSpeedValue",
        "ApertureValue",
        "BrightnessValue",
        "ExposureCompensation",
        "RawExposureBias",
        "DynamicRange",
        "DynamicRangeSetting",
        "DevelopmentDynamicRange",
        "AutoDynamicRange",
        "DRangePriority",
        "DRangePriorityAuto",
        "DRangePriorityFixed",
        "HighlightTone",
        "ShadowTone",
        "GrainEffectRoughness",
        "GrainEffectSize",
        "MaxApertureValue",
        "MeteringMode",
        "LightSource",
        "Flash",
        "FocalLength",
        "SubSecTime",
        "SubSecTimeOriginal",
        "SubSecTimeDigitized",
        "CameraElevationAngle",
        "ColorSpace",
        "ExposureMode",
        "WhiteBalance",
        "SceneCaptureType",
        "CustomRendered",
        "Sharpness",
        "SubjectDistanceRange",
        "CompositeImage",
        "Orientation",
        "RawImageAspectRatio",
        "RawImageCropTopLeft",
        "RawImageCroppedSize",
        "RawZoomActive",
        "RawZoomTopLeft",
        "RawZoomSize",
        "CropMode",
        "FilmMode",
        "Saturation",
        "Contrast",
        "ColorChromeEffect",
        "ColorChromeFXBlue",
        "BWAdjustment",
        "BWMagentaGreen",
        "Clarity",
        "NoiseReduction",
        "LensModulationOptimizer",
        "Artist",
        "Copyright",
        "UserComment",
        "Rating",
        "FirmwareVersion",
        "RAFCompression",
        "BitsPerSample",
        "ShutterType",
        "FocusMode",
        "AFMode",
        "FocusPixel",
        "DriveMode",
        "FlashExposureComp",
        "FlickerReduction",
        "RollAngle",
        "BlurWarning",
        "FocusWarning",
        "ExposureWarning",
        "GPS*",
    ]
    result = subprocess.run(
        [exiftool, "-j", "-n", "-G1", "-s", *[f"-{tag}" for tag in tags], str(source)],
        check=True,
        capture_output=True,
        text=True,
    )
    row = json.loads(result.stdout)[0]
    required = {
        "IFD0:ModifyDate",
        "ExifIFD:ExposureTime",
        "ExifIFD:FNumber",
        "ExifIFD:ExposureProgram",
        "ExifIFD:ISO",
        "ExifIFD:DateTimeOriginal",
        "ExifIFD:ExposureCompensation",
        "ExifIFD:MaxApertureValue",
        "ExifIFD:MeteringMode",
        "ExifIFD:Flash",
        "ExifIFD:FocalLength",
        "ExifIFD:ColorSpace",
    }
    missing = sorted(required - row.keys())
    if missing:
        raise ValueError(f"source RAF lacks required capture metadata: {missing}")
    focal_length = float(row["ExifIFD:FocalLength"])
    capture_iso, iso_field, capture_iso_source = effective_capture_iso(row)
    raw_exposure_bias = float(row.get("RAF:RawExposureBias", 0.0))
    rendering_intent = fuji_rendering_intent(row)
    phocus_compensation = -raw_exposure_bias
    if not math.isfinite(phocus_compensation) or not -5.0 <= phocus_compensation <= 5.0:
        raise ValueError(
            f"source RAF exposure bias is outside the supported range: {raw_exposure_bias}"
        )
    full_frame_diagonal = math.hypot(36.0, 24.0)
    gfx_diagonal = math.hypot(43.8, 32.9)
    derived_35mm = int(round(focal_length * full_frame_diagonal / gfx_diagonal))
    return {
        "source_standard": {
            key: value for key, value in row.items() if key != "SourceFile"
        },
        "embedded_values": {
            "Orientation": int(row.get("IFD0:Orientation", 1)),
            "ModifyDate": row["IFD0:ModifyDate"],
            "ExposureTime": row["ExifIFD:ExposureTime"],
            "FNumber": row["ExifIFD:FNumber"],
            "ExposureProgram": row["ExifIFD:ExposureProgram"],
            "ISO": capture_iso,
            "DateTimeOriginal": row["ExifIFD:DateTimeOriginal"],
            "ExposureCompensation": row["ExifIFD:ExposureCompensation"],
            "MaxApertureValue": row["ExifIFD:MaxApertureValue"],
            "MeteringMode": row["ExifIFD:MeteringMode"],
            "Flash": row["ExifIFD:Flash"],
            "FocalLength": focal_length,
            "ColorSpace": row["ExifIFD:ColorSpace"],
            "FocalLengthIn35mmFormat": derived_35mm,
            "LensMake": "FUJIFILM",
            "LensModel": "35mm F4",
        },
        "derived": {
            "CaptureISO": {
                "value": capture_iso,
                "source": capture_iso_source,
                "legacy_iso_field": iso_field,
            },
            "FocalLengthIn35mmFormat": {
                "value": derived_35mm,
                "formula": "round(focal_mm * hypot(36,24) / hypot(43.8,32.9))",
            },
            "LensMake": "FUJIFILM",
            "LensModelFull": "FUJINON 35mm F4 fixed lens",
            "LensModelEmbeddedCompact": "35mm F4",
        },
        "exposure_matching": {
            "source_raw_exposure_bias_ev": raw_exposure_bias,
            "recommended_phocus_compensation_ev": phocus_compensation,
            "linear_multiplier": 2.0**phocus_compensation,
            "source": (
                "RAF:RawExposureBias"
                if "RAF:RawExposureBias" in row
                else "missing_default_zero"
            ),
            "dynamic_range_percent": rendering_intent["dynamic_range"]["percent"],
            "dynamic_range": row.get("FujiFilm:DynamicRange"),
            "dynamic_range_setting": row.get("FujiFilm:DynamicRangeSetting"),
            "application_stage": "Phocus sidecar; RAW payload remains linear and unchanged",
        },
        "rendering_intent": rendering_intent,
        "framing": fuji_framing(row),
        "standard_metadata": fuji_safe_metadata(row),
        "capture_state": fuji_capture_state(row),
    }


def patch_capture_metadata(
    path: Path, capture: dict[str, object], raw_data_id: str
) -> list[dict[str, object]]:
    values = capture.get("embedded_values")
    if not isinstance(values, dict):
        raise ValueError("capture metadata lacks embedded values")
    specifications = [
        ("IFD0", 274, values["Orientation"], "Orientation"),
        ("IFD0", 306, values["ModifyDate"], "ModifyDate"),
        ("ExifIFD", 33434, values["ExposureTime"], "ExposureTime"),
        ("ExifIFD", 33437, values["FNumber"], "FNumber"),
        ("ExifIFD", 34850, values["ExposureProgram"], "ExposureProgram"),
        ("ExifIFD", 34855, values["ISO"], "ISO"),
        ("ExifIFD", 36867, values["DateTimeOriginal"], "DateTimeOriginal"),
        ("ExifIFD", 37380, values["ExposureCompensation"], "ExposureCompensation"),
        ("ExifIFD", 37381, values["MaxApertureValue"], "MaxApertureValue"),
        ("ExifIFD", 37383, values["MeteringMode"], "MeteringMode"),
        ("ExifIFD", 37385, values["Flash"], "Flash"),
        ("ExifIFD", 37386, values["FocalLength"], "FocalLength"),
        ("ExifIFD", 40961, values["ColorSpace"], "ColorSpace"),
        ("ExifIFD", 41989, values["FocalLengthIn35mmFormat"], "FocalLengthIn35mmFormat"),
        ("ExifIFD", 42016, raw_data_id.upper(), "ImageUniqueID"),
        ("ExifIFD", 42035, values["LensMake"], "LensMake"),
        ("ExifIFD", 42036, values["LensModel"], "LensModel"),
        ("IFD0", 50781, bytes.fromhex(raw_data_id), "RawDataUniqueID"),
    ]
    return patch_tiff_tags(path, specifications)


def nearest_x2d_iso(capture_iso: int) -> int:
    """Return the closest selectable X2D ISO in exposure-value space."""
    if capture_iso <= 0:
        raise ValueError("capture ISO must be positive")
    return min(
        X2D_100C_SELECTABLE_ISO,
        key=lambda candidate: (abs(math.log2(candidate / capture_iso)), candidate),
    )


def apply_iso_policy(
    capture: dict[str, object], policy: str = "nearest-x2d"
) -> dict[str, object]:
    """Select the ISO exposed to Phocus while retaining the Fuji capture ISO."""
    values = capture.get("embedded_values")
    if not isinstance(values, dict) or "ISO" not in values:
        raise ValueError("capture metadata lacks ISO")
    capture_iso = int(values["ISO"])
    if policy == "nearest-x2d":
        model_iso = nearest_x2d_iso(capture_iso)
        policy_detail = "nearest_selectable_x2d_iso_ev_lower_tie"
    elif policy == "hnnr-stable":
        model_iso = min(capture_iso, 6400)
        policy_detail = "cap_above_6400"
    elif policy == "capture":
        model_iso = min(capture_iso, 65535)
        policy_detail = (
            "exif_short_sentinel"
            if capture_iso > 65535
            else "preserve_capture_iso"
        )
    else:
        raise ValueError(f"unsupported ISO policy: {policy}")
    values["ISO"] = model_iso
    capture["capture_iso"] = capture_iso
    capture["iso_policy"] = {
        "mode": policy,
        "capture_iso": capture_iso,
        "phocus_model_iso": model_iso,
        "selection": policy_detail,
        "adjusted": model_iso != capture_iso,
    }
    # Retain the old manifest object for readers created before 0.3.0.
    capture["hnnr_compatibility"] = {
        "enabled": policy == "hnnr-stable",
        "capture_iso": capture_iso,
        "phocus_model_iso": model_iso,
        "policy": policy_detail,
        "adjusted": model_iso != capture_iso,
    }
    return capture


def apply_hnnr_iso_policy(
    capture: dict[str, object], enabled: bool
) -> dict[str, object]:
    """Compatibility wrapper for the pre-0.3.0 binary ISO option."""
    return apply_iso_policy(capture, "hnnr-stable" if enabled else "capture")


def read_pgm(path: Path) -> tuple[np.memmap, int, int]:
    with path.open("rb") as handle:
        if handle.readline() != b"P5\n":
            raise ValueError("LibRaw output is not binary PGM")
        line = handle.readline()
        while line.startswith(b"#"):
            line = handle.readline()
        width, height = (int(value) for value in line.split())
        if int(handle.readline()) != 65535:
            raise ValueError("LibRaw PGM is not 16-bit")
        offset = handle.tell()
    expected = offset + width * height * 2
    if path.stat().st_size != expected:
        raise ValueError(f"PGM length {path.stat().st_size} != expected {expected}")
    return np.memmap(path, mode="r", dtype=">u2", offset=offset, shape=(height, width)), width, height


def parity_preserving_indices(
    source_origin: int,
    source_length: int,
    target_origin: int,
    target_length: int,
    leading_pad: int,
) -> np.ndarray:
    indices = np.clip(np.arange(target_length, dtype=np.int64) - leading_pad, 0, source_length - 1)
    source_parity = (source_origin + indices) & 1
    target_parity = (target_origin + np.arange(target_length, dtype=np.int64)) & 1
    mismatch = source_parity != target_parity
    plus = mismatch & (indices + 1 < source_length)
    indices[plus] += 1
    indices[mismatch & ~plus] -= 1
    if np.any(((source_origin + indices) ^ (target_origin + np.arange(target_length))) & 1):
        raise AssertionError("failed to preserve CFA parity")
    return indices


def map_crop(
    source: np.ndarray,
    target: np.memmap,
    source_meta: dict[str, object],
    target_layout: X2DLayout,
    x2d_calibration_gains: dict[str, int] | None = None,
) -> dict[str, int]:
    sx = int(source_meta["crop_x"])
    sy = int(source_meta["crop_y"])
    sw = int(source_meta["crop_width"])
    sh = int(source_meta["crop_height"])
    tx, ty = target_layout.crop_origin
    tw, th = target_layout.crop_size
    if sw > tw or sh > th:
        raise ValueError("Fuji visible crop is larger than X2D crop")
    pad_left = (tw - sw) // 2
    pad_top = (th - sh) // 2
    if ((tx + pad_left - sx) & 1) or ((ty + pad_top - sy) & 1):
        raise ValueError("centered placement would change CFA phase")

    x_indices = parity_preserving_indices(sx, sw, tx, tw, pad_left)
    y_indices = parity_preserving_indices(sy, sh, ty, th, pad_top)
    black_values = np.asarray(source_meta["black_levels"], dtype=np.uint32).reshape(
        int(source_meta["black_height"]), int(source_meta["black_width"])
    )
    source_white = int(source_meta["white_level"])
    target_black = target_layout.black_level
    target_white = target_layout.white_level
    source_crop = source[sy : sy + sh, sx : sx + sw]

    global_source_x = sx + x_indices
    for target_row, source_row in enumerate(y_indices):
        pixels = np.asarray(source_crop[source_row, x_indices], dtype=np.uint32)
        source_global_y = sy + int(source_row)
        blacks = black_values[
            source_global_y % black_values.shape[0],
            global_source_x % black_values.shape[1],
        ]
        signal = np.maximum(pixels, blacks) - blacks
        denominator = source_white - blacks
        mapped_signal = (
            signal * (target_white - target_black) + denominator // 2
        ) // denominator
        if x2d_calibration_gains:
            global_target_y = ty + target_row
            global_target_x = tx + np.arange(tw, dtype=np.int64)
            if global_target_y % 2 == 0:
                channels = ((global_target_x & 1) == 0, (global_target_x & 1) == 1)
                names = ("R", "G1")
            else:
                channels = ((global_target_x & 1) == 0, (global_target_x & 1) == 1)
                names = ("G2", "B")
            for channel_mask, name in zip(channels, names):
                gain = int(x2d_calibration_gains[name])
                if gain <= 0:
                    raise ValueError(f"invalid X2D calibration gain for {name}: {gain}")
                if gain != 65_536:
                    values = mapped_signal[channel_mask]
                    mapped_signal[channel_mask] = (values * 65_536 + gain - 1) // gain
        mapped = target_black + mapped_signal
        target[ty + target_row, tx : tx + tw] = np.minimum(mapped, target_white).astype("<u2")

    return {
        "mode": "default_crop_with_same_colour_extension",
        "pad_left": pad_left,
        "pad_right": tw - sw - pad_left,
        "pad_top": pad_top,
        "pad_bottom": th - sh - pad_top,
    }


def map_active_lattice(
    source: np.ndarray,
    target: np.memmap,
    source_meta: dict[str, object],
    target_layout: X2DLayout,
    x2d_calibration_gains: dict[str, int] | None = None,
    sensor_matrix: np.ndarray | None = None,
) -> dict[str, object]:
    """Map the matching 11664x8750 RGGB sensor lattices without resampling."""
    sx = int(source_meta["active_x"])
    sy = int(source_meta["active_y"])
    sw = int(source_meta["active_width"])
    sh = int(source_meta["active_height"])
    crop_x, crop_y = target_layout.crop_origin
    crop_width, crop_height = target_layout.crop_size
    # The observed X2D content lattice extends four same-phase pixels around
    # DefaultCrop. This yields LibRaw's independently reported 11664x8750 image.
    tx, ty = crop_x - 4, crop_y - 4
    tw, th = crop_width + 8, crop_height + 8
    if (sw, sh) != (tw, th):
        raise ValueError(f"Fuji/X2D active lattices differ: {(sw, sh)} != {(tw, th)}")
    if min(sx, sy, tx, ty) < 0 or sx + sw > source.shape[1] or sy + sh > source.shape[0]:
        raise ValueError("active lattice lies outside source or target canvas")
    if tx + tw > target_layout.width or ty + th > target_layout.height:
        raise ValueError("X2D content lattice lies outside donor canvas")
    if ((tx - sx) & 1) or ((ty - sy) & 1):
        raise ValueError("active-lattice placement would change CFA phase")

    black_values = np.asarray(source_meta["black_levels"], dtype=np.uint32).reshape(
        int(source_meta["black_height"]), int(source_meta["black_width"])
    )
    source_white = int(source_meta["white_level"])
    target_black = target_layout.black_level
    target_white = target_layout.white_level
    global_source_x = sx + np.arange(sw, dtype=np.int64)
    global_target_x = tx + np.arange(tw, dtype=np.int64)

    def signal_row(row: int) -> np.ndarray:
        pixels = np.asarray(source[sy + row, sx : sx + sw], dtype=np.int64)
        blacks = black_values[
            (sy + row) % black_values.shape[0], global_source_x % black_values.shape[1]
        ].astype(np.int64)
        signal = pixels - blacks
        denominator = source_white - blacks
        return signal.astype(np.float64) / denominator

    def scale_signed_signal(signal: np.ndarray, denominator: np.ndarray) -> np.ndarray:
        numerator = signal.astype(np.int64) * (target_white - target_black)
        magnitude = (np.abs(numerator) + denominator // 2) // denominator
        return np.where(numerator < 0, -magnitude, magnitude)

    def apply_inverse_gain(values: np.ndarray, gain: int) -> np.ndarray:
        magnitude = (np.abs(values) * 65_536 + gain - 1) // gain
        return np.where(values < 0, -magnitude, magnitude)

    def mean_horizontal(current: np.ndarray, indices: np.ndarray) -> np.ndarray:
        total = np.zeros(indices.size, dtype=np.float64)
        count = np.zeros(indices.size, dtype=np.uint8)
        valid = indices > 0
        total[valid] += current[indices[valid] - 1]
        count[valid] += 1
        valid = indices + 1 < sw
        total[valid] += current[indices[valid] + 1]
        count[valid] += 1
        return total / count

    def mean_vertical(
        previous: np.ndarray | None, following: np.ndarray | None, indices: np.ndarray
    ) -> np.ndarray:
        total = np.zeros(indices.size, dtype=np.float64)
        count = np.zeros(indices.size, dtype=np.uint8)
        if previous is not None:
            total += previous[indices]
            count += 1
        if following is not None:
            total += following[indices]
            count += 1
        return total / count

    def mean_diagonal(
        previous: np.ndarray | None, following: np.ndarray | None, indices: np.ndarray
    ) -> np.ndarray:
        total = np.zeros(indices.size, dtype=np.float64)
        count = np.zeros(indices.size, dtype=np.uint8)
        for neighbour in (previous, following):
            if neighbour is None:
                continue
            valid = indices > 0
            total[valid] += neighbour[indices[valid] - 1]
            count[valid] += 1
            valid = indices + 1 < sw
            total[valid] += neighbour[indices[valid] + 1]
            count[valid] += 1
        return total / count

    transform = (
        None if sensor_matrix is None else np.asarray(sensor_matrix, dtype=np.float64)
    )
    if transform is not None and (
        transform.shape != (3, 3) or not np.all(np.isfinite(transform))
    ):
        raise ValueError("sensor transform must be a finite 3x3 matrix")
    clipped_low = 0
    clipped_high = 0
    preserved_below_black = 0
    previous = None
    current = signal_row(0) if transform is not None else None
    following = signal_row(1) if transform is not None and sh > 1 else None
    for row in range(sh):
        if transform is None:
            pixels = np.asarray(source[sy + row, sx : sx + sw], dtype=np.int64)
            blacks = black_values[
                (sy + row) % black_values.shape[0], global_source_x % black_values.shape[1]
            ].astype(np.int64)
            signal = pixels - blacks
            denominator = source_white - blacks
            mapped_signal = scale_signed_signal(signal, denominator)
        else:
            if current is None:
                raise AssertionError("sensor-transform row cache is empty")
            transformed = np.empty(sw, dtype=np.float64)
            even_sites = np.arange((-(sx & 1)) & 1, sw, 2, dtype=np.int64)
            odd_sites = np.arange((1 - (sx & 1)) & 1, sw, 2, dtype=np.int64)
            if ((sy + row) & 1) == 0:
                r_sites, g_sites = even_sites, odd_sites
                r_g = (
                    mean_horizontal(current, r_sites) * 2
                    + mean_vertical(previous, following, r_sites)
                    * (2 if previous is not None and following is not None else 1)
                ) / (4 if previous is not None and following is not None else 3)
                r_b = mean_diagonal(previous, following, r_sites)
                g_r = mean_horizontal(current, g_sites)
                g_b = mean_vertical(previous, following, g_sites)
                transformed[r_sites] = (
                    transform[0, 0] * current[r_sites]
                    + transform[0, 1] * r_g
                    + transform[0, 2] * r_b
                )
                transformed[g_sites] = (
                    transform[1, 0] * g_r
                    + transform[1, 1] * current[g_sites]
                    + transform[1, 2] * g_b
                )
            else:
                g_sites, b_sites = even_sites, odd_sites
                g_r = mean_vertical(previous, following, g_sites)
                g_b = mean_horizontal(current, g_sites)
                b_r = mean_diagonal(previous, following, b_sites)
                b_g = (
                    mean_horizontal(current, b_sites) * 2
                    + mean_vertical(previous, following, b_sites)
                    * (2 if previous is not None and following is not None else 1)
                ) / (4 if previous is not None and following is not None else 3)
                transformed[g_sites] = (
                    transform[1, 0] * g_r
                    + transform[1, 1] * current[g_sites]
                    + transform[1, 2] * g_b
                )
                transformed[b_sites] = (
                    transform[2, 0] * b_r
                    + transform[2, 1] * b_g
                    + transform[2, 2] * current[b_sites]
                )
            mapped_signal = np.rint(
                transformed * (target_white - target_black)
            ).astype(np.int64)
        if x2d_calibration_gains:
            global_target_y = ty + row
            if global_target_y % 2 == 0:
                names = ("R", "G1")
            else:
                names = ("G2", "B")
            masks = ((global_target_x & 1) == 0, (global_target_x & 1) == 1)
            for mask, name in zip(masks, names):
                gain = int(x2d_calibration_gains[name])
                if gain <= 0:
                    raise ValueError(f"invalid X2D calibration gain for {name}: {gain}")
                if gain != 65_536:
                    values = mapped_signal[mask]
                    mapped_signal[mask] = apply_inverse_gain(values, gain)
        mapped_codes = target_black + mapped_signal
        preserved_below_black += int(
            np.count_nonzero((mapped_codes >= 0) & (mapped_codes < target_black))
        )
        clipped_low += int(np.count_nonzero(mapped_codes < 0))
        clipped_high += int(np.count_nonzero(mapped_codes > target_white))
        target[ty + row, tx : tx + tw] = np.clip(
            mapped_codes, 0, target_white
        ).astype("<u2")
        if transform is not None:
            previous, current = current, following
            following = signal_row(row + 2) if row + 2 < sh else None
    return {
        "mode": "active_lattice_1_to_1",
        "source_origin": [sx, sy],
        "source_size": [sw, sh],
        "target_origin": [tx, ty],
        "target_size": [tw, th],
        "default_crop_inset": [4, 4, 4, 4],
        "cfa": "RGGB",
        "sensor_transform_clipping": {
            "below_black": clipped_low,
            "above_white": clipped_high,
            "total": sw * sh,
        },
        "black_noise_mapping": {
            "policy": "preserve_signed_source_residual",
            "preserved_below_black": preserved_below_black,
            "clipped_below_code_zero": clipped_low,
        },
    }


def bake_negative_vignetting(
    target: np.ndarray,
    *,
    black_level: int,
    white_level: int,
    decoded_profile: dict[str, object],
    distortion_strength: float,
    vignetting_strength: float,
    crop_origin: tuple[int, int] = (0, 0),
    crop_size: tuple[int, int] | None = None,
    gaussian_sigma: float = 6.0,
    safety_code_floor: int = 64,
    gain_chunk_rows: int = 256,
    noise_seed: str = "raf2hncs-negative-vignette-v2",
) -> dict[str, object]:
    """Simulate optical falloff without tiled noise or edge-frequency halos."""
    if not -2.0 <= vignetting_strength < 0.0:
        raise ValueError("baked vignetting strength must be negative and within -2..0")
    if target.ndim != 2 or min(target.shape) < 2:
        raise ValueError("target RAW must be a two-dimensional image")
    if not np.isfinite(gaussian_sigma) or gaussian_sigma <= 0:
        raise ValueError("negative-vignette Gaussian sigma must be positive")
    if gain_chunk_rows <= 0:
        raise ValueError("negative-vignette gain chunk must be positive")
    crop_x, crop_y = (int(value) for value in crop_origin)
    crop_width, crop_height = (
        (target.shape[1], target.shape[0])
        if crop_size is None
        else (int(value) for value in crop_size)
    )
    if (
        crop_x < 0
        or crop_y < 0
        or crop_width < 2
        or crop_height < 2
        or crop_x + crop_width > target.shape[1]
        or crop_y + crop_height > target.shape[0]
    ):
        raise ValueError("negative-vignette crop is outside the target RAW")
    if safety_code_floor < 0 or safety_code_floor >= black_level:
        raise ValueError("negative-vignette safety floor must be below black level")
    try:
        from scipy.ndimage import gaussian_filter
    except ImportError as error:
        raise RuntimeError(
            "physical negative vignetting requires scipy; install raf2hncs 0.6 dependencies"
        ) from error
    splines = _profile_splines(
        decoded_profile,
        sample_count=4096,
        distortion_strength=distortion_strength,
        chromatic_aberration_strength=0.0,
        vignetting_strength=vignetting_strength,
    )
    destination_radius = np.asarray(splines["distortion_knots"], dtype=np.float64)
    geometric_scale = np.asarray(splines["green_scale"], dtype=np.float64)
    source_radius = destination_radius * geometric_scale
    source_multiplier = np.interp(
        source_radius,
        np.asarray(splines["vignette_knots"], dtype=np.float64),
        np.asarray(splines["vignette_scale"], dtype=np.float64),
    )
    gain_profile = 1.0 / np.maximum(source_multiplier, 1e-6)
    if np.any(~np.isfinite(gain_profile)) or np.min(gain_profile) <= 0 or np.max(gain_profile) > 1.000001:
        raise ValueError("negative vignetting must produce finite attenuation gains in (0, 1]")

    active = target[crop_y : crop_y + crop_height, crop_x : crop_x + crop_width]
    height, width = active.shape
    center_x = (width - 1) / 2.0
    center_y = (height - 1) / 2.0
    maximum_radius = float(np.hypot(center_x, center_y))
    clipped_low = 0
    clipped_high = 0
    floor_limited = 0
    seed_fingerprint = hashlib.sha256(noise_seed.encode("utf-8")).hexdigest()
    # Work on each Bayer site independently. The Gaussian estimates only local
    # photon variance; it is never subtracted from the image. Direct photometric
    # attenuation therefore cannot create the dark edge halos produced by the
    # old frequency-split method. Independent deterministic noise then restores
    # the variance lost when the already-noisy RAW sample is multiplied by gain.
    for parity_y in (0, 1):
        y_coordinates = np.arange(parity_y, height, 2, dtype=np.float32)
        for parity_x in (0, 1):
            x_coordinates = np.arange(parity_x, width, 2, dtype=np.float32)
            signal = np.asarray(
                active[parity_y::2, parity_x::2], dtype=np.float32
            )
            signal -= float(black_level)
            scene = gaussian_filter(
                np.maximum(signal, 0.0),
                sigma=gaussian_sigma,
                mode="reflect",
                output=np.float32,
            )
            gain = np.empty(scene.shape, dtype=np.float32)
            x2 = ((x_coordinates - center_x) / maximum_radius) ** 2
            for row_start in range(0, scene.shape[0], gain_chunk_rows):
                row_end = min(scene.shape[0], row_start + gain_chunk_rows)
                y2 = (
                    (y_coordinates[row_start:row_end] - center_y) / maximum_radius
                ) ** 2
                radius = np.sqrt(y2[:, None] + x2[None, :])
                gain[row_start:row_end] = np.interp(
                    radius, destination_radius, gain_profile
                ).astype(np.float32)
            read_noise_equivalent = PHYSICAL_VIGNETTE_READ_NOISE_EQUIVALENT[
                parity_y
            ][parity_x]
            # If input variance is scene + read, multiplying the sample by g
            # leaves g^2(scene + read). A physical lens falloff instead yields
            # g*scene + read, so add the non-negative variance difference.
            scene *= gain * (1.0 - gain)
            if read_noise_equivalent:
                scene += (1.0 - gain * gain) * read_noise_equivalent
            np.maximum(scene, 0.0, out=scene)
            np.sqrt(scene, out=scene)
            channel_seed = hashlib.sha256(
                f"{noise_seed}:{parity_y}:{parity_x}".encode("utf-8")
            ).digest()
            random = np.random.default_rng(
                int.from_bytes(channel_seed[:8], "little")
            ).standard_normal(scene.shape, dtype=np.float32)
            scene *= random
            signal *= gain
            signal += scene
            signal += float(black_level)
            rounded = np.rint(signal)
            floor_mask = rounded < safety_code_floor
            floor_limited += int(np.count_nonzero(floor_mask))
            rounded[floor_mask] = safety_code_floor
            clipped_low += int(np.count_nonzero(rounded < 0))
            clipped_high += int(np.count_nonzero(rounded > white_level))
            active[parity_y::2, parity_x::2] = np.clip(
                rounded, 0, white_level
            ).astype("<u2")
    return {
        "mode": "fullplane_physical_negative_vignette_v2",
        "strength": float(vignetting_strength),
        "minimum_gain": float(np.min(gain_profile)),
        "maximum_gain": float(np.max(gain_profile)),
        "active_origin": [crop_x, crop_y],
        "active_size": [crop_width, crop_height],
        "cfa_planes": "RGGB separated",
        "scene_estimator": {
            "filter": "full-plane Gaussian used only for local photon variance",
            "sigma_cfa_samples": float(gaussian_sigma),
            "boundary": "reflect",
        },
        "noise_model": (
            "signal is attenuated pointwise by gain; independent deterministic noise "
            "adds variance gain*(1-gain)*scene + (1-gain^2)*read"
        ),
        "noise_generator": "NumPy PCG64, independent full-plane CFA streams",
        "noise_seed_fingerprint": seed_fingerprint[:16],
        "read_noise_signal_equivalent_by_cfa": {
            "R": PHYSICAL_VIGNETTE_READ_NOISE_EQUIVALENT[0][0],
            "G1": PHYSICAL_VIGNETTE_READ_NOISE_EQUIVALENT[0][1],
            "G2": PHYSICAL_VIGNETTE_READ_NOISE_EQUIVALENT[1][0],
            "B": PHYSICAL_VIGNETTE_READ_NOISE_EQUIVALENT[1][1],
        },
        "safety_code_floor": int(safety_code_floor),
        "floor_limited_samples": floor_limited,
        "clipped_below_code_zero": clipped_low,
        "clipped_above_white": clipped_high,
        "policy": (
            "Negative vignetting is simulated over the complete active CFA planes without "
            "striped filtering or frequency-split edge halos; optical margins stay byte-identical "
            "and positive correction remains a DNG opcode."
        ),
    }


def convert(
    source: Path,
    donor: Path,
    output: Path,
    *,
    dnglab_path: str | None = None,
    raw_identify_path: str | None = None,
    unprocessed_raw_path: str | None = None,
    exiftool_path: str | None = None,
    white_balance: str = "auto",
    inverse_x2d_calibration: bool = False,
    iso_policy: str = "hnnr-stable",
    hnnr_compatibility: bool | None = None,
    sensor_mapping: str = "wb-adaptive-bootstrap",
    preview: str = "source",
    donor_lens_correction: str = "neutralize",
    distortion_model: str = "camera-jpeg",
    distortion_strength: float = 1.0,
    chromatic_aberration_strength: float = 1.0,
    vignetting_strength: float = 0.0,
    preserve_location: bool = True,
    preserve_rights: bool = True,
    preserve_provenance: bool = True,
) -> dict[str, object]:
    source = source.resolve()
    donor = donor.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if not donor.is_file():
        raise FileNotFoundError(donor)
    if output in (source, donor):
        raise ValueError("output must differ from source and donor")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    manifest_path = output.with_suffix(output.suffix + ".json")
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite {manifest_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    source_sha256 = sha256(source)
    donor_sha256 = sha256(donor)
    layout = inspect_x2d(donor)
    if not layout.complete or layout.file_size != donor.stat().st_size:
        raise ValueError("donor download is incomplete")
    if layout.byte_order != "little":
        raise ValueError("only the observed little-endian X2D layout is supported")

    dnglab = find_tool(dnglab_path, "dnglab")
    raw_identify = find_tool(raw_identify_path, "raw-identify")
    unprocessed_raw = find_tool(unprocessed_raw_path, "unprocessed_raw")
    exiftool = find_tool(exiftool_path, "exiftool")
    source_meta = read_fuji_metadata(source, dnglab, raw_identify)
    source_meta["white_balances"] = read_fuji_white_balances(source, exiftool)
    if hnnr_compatibility is not None:
        iso_policy = "hnnr-stable" if hnnr_compatibility else "capture"
    capture_metadata = apply_iso_policy(
        read_fuji_capture_metadata(source, exiftool), iso_policy
    )
    lens_profile = extract_fuji_lens_profile(source, exiftool)
    embedded_vignetting_strength = max(0.0, vignetting_strength)
    lens_opcode_payload, lens_correction = fuji_lens_opcode_list(
        lens_profile["decoded"],
        distortion_model=distortion_model,
        distortion_strength=distortion_strength,
        chromatic_aberration_strength=chromatic_aberration_strength,
        vignetting_strength=embedded_vignetting_strength,
        image_width=int(source_meta["active_width"]),
        image_height=int(source_meta["active_height"]),
    )
    lens_correction["strengths"]["vignetting"] = float(vignetting_strength)
    if white_balance not in ("auto", "as-shot", "donor"):
        raise ValueError(f"unsupported white-balance selection: {white_balance}")
    if sensor_mapping not in (
        "identity",
        "d65-dnglab-bootstrap",
        "wb-adaptive-bootstrap",
    ):
        raise ValueError(f"unsupported sensor mapping: {sensor_mapping}")
    selected_source_key = "as_shot" if white_balance == "as-shot" else "camera_auto"
    selected_coefficients = source_meta["white_balances"][selected_source_key][
        "rgb_coeffs"
    ]
    sensor_mapping_evidence: dict[str, object] = {}
    if sensor_mapping == "identity":
        sensor_matrix = None
    elif sensor_mapping == "d65-dnglab-bootstrap":
        sensor_matrix = GFX100RF_TO_X2D100C_D65_BOOTSTRAP
    else:
        sensor_matrix, sensor_mapping_evidence = adaptive_sensor_mapping(
            selected_coefficients
        )
    if preview not in ("source", "donor"):
        raise ValueError(f"unsupported preview selection: {preview}")
    if donor_lens_correction not in ("neutralize", "preserve"):
        raise ValueError(
            f"unsupported donor lens-correction selection: {donor_lens_correction}"
        )

    temporary_output = output.with_name(output.name + ".partial")
    temporary_manifest = manifest_path.with_name(manifest_path.name + ".partial")
    if temporary_output.exists():
        raise FileExistsError(f"remove stale temporary output first: {temporary_output}")
    if temporary_manifest.exists():
        raise FileExistsError(f"remove stale temporary output first: {temporary_manifest}")
    try:
        with tempfile.TemporaryDirectory(prefix="raf2hncs-") as directory:
            work = Path(directory)
            local_source = work / "source.RAF"
            local_source.symlink_to(source)
            subprocess.run([unprocessed_raw, "-q", local_source.name], cwd=work, check=True)
            pgm = work / "source.RAF.pgm"
            mosaic, width, height = read_pgm(pgm)
            if (width, height) != (int(source_meta["width"]), int(source_meta["height"])):
                raise ValueError("LibRaw and DNGLab disagree on Fuji full RAW dimensions")

            shutil.copyfile(donor, temporary_output)
            target = np.memmap(
                temporary_output,
                mode="r+",
                dtype="<u2",
                offset=layout.strip_offset,
                shape=(layout.height, layout.width),
            )
            calibration_cohort = None
            calibration_profile = None
            if inverse_x2d_calibration:
                calibration_cohort, calibration_profile = x2d_q16_profile(layout)
            calibration_gains = (
                dict(calibration_profile["q16_gains"])
                if calibration_profile is not None
                else None
            )
            mapping = map_active_lattice(
                mosaic, target, source_meta, layout, calibration_gains, sensor_matrix
            )
            baked_vignetting = None
            if vignetting_strength < 0:
                baked_vignetting = bake_negative_vignetting(
                    target,
                    black_level=layout.black_level,
                    white_level=layout.white_level,
                    decoded_profile=lens_profile["decoded"],
                    distortion_strength=distortion_strength,
                    vignetting_strength=vignetting_strength,
                    noise_seed=source_sha256,
                    crop_origin=layout.crop_origin,
                    crop_size=layout.crop_size,
                )
            target.flush()
            del target
            metadata_patches: list[dict[str, object]] = []
            if donor_lens_correction == "neutralize":
                metadata_patches.append(
                    neutralize_hasselblad_lens_correction(temporary_output)
                )
            if white_balance != "donor":
                source_key = "camera_auto" if white_balance == "auto" else "as_shot"
                coefficients = source_meta["white_balances"][source_key]["rgb_coeffs"]
                if sensor_matrix is not None:
                    coefficients = transform_wb_coefficients(coefficients, sensor_matrix)
                metadata_patches.append(
                    patch_as_shot_neutral(
                        temporary_output, [float(value) for value in coefficients]
                    )
                )
            raw_data_id = md5_range(
                temporary_output, layout.strip_offset, layout.payload_end
            )
            metadata_patches.extend(
                patch_capture_metadata(temporary_output, capture_metadata, raw_data_id)
            )
            preview_evidence: dict[str, object]
            preview_range: tuple[int, int] | None = None
            if preview == "source":
                if layout.preview_width is None or layout.preview_height is None:
                    raise ValueError("X2D donor preview dimensions are missing")
                preview_bytes, preview_evidence = source_preview_for_slot(
                    source,
                    exiftool,
                    layout.preview_byte_count,
                    work,
                    (layout.preview_width, layout.preview_height),
                )
                preview_patch = patch_preview_slot(temporary_output, layout, preview_bytes)
                metadata_patches.extend(
                    patch_tiff_tags(
                        temporary_output,
                        [("IFD0", 279, len(preview_bytes), "PreviewByteCount")],
                    )
                )
                preview_evidence = {**preview_evidence, **preview_patch}
                preview_range = (layout.preview_offset, layout.preview_end)
            else:
                preview_evidence = {
                    "mode": "donor_preview_preserved",
                    "range": [layout.preview_offset, layout.preview_end],
                }
            lens_opcode_patch = None
            if lens_opcode_payload is not None:
                lens_opcode_patch = append_raw_opcode_list(
                    temporary_output, lens_opcode_payload
                )
            existing_xmp = read_xmp_payload(temporary_output)
            xmp_payload = build_fuji_xmp(
                safe_metadata=capture_metadata["standard_metadata"],
                framing=capture_metadata["framing"],
                capture_state=capture_metadata["capture_state"],
                rendering_intent=capture_metadata["rendering_intent"],
                source_name=source.name,
                existing_payload=existing_xmp,
                preserve_location=preserve_location,
                preserve_rights=preserve_rights,
                preserve_provenance=preserve_provenance,
            )
            metadata_xmp_patch = append_ifd0_xmp(temporary_output, xmp_payload)
            with temporary_output.open("r+b") as handle:
                os.fsync(handle.fileno())

        allowed_changes = [(layout.strip_offset, layout.payload_end)] + [
            tuple(int(value) for value in patch["range"])
            for patch in metadata_patches
        ]
        if preview_range is not None:
            allowed_changes.append(preview_range)
        if lens_opcode_patch is not None:
            allowed_changes.append(tuple(lens_opcode_patch["pointer_range"]))
        allowed_changes.append(tuple(metadata_xmp_patch["pointer_range"]))
        preserved_ranges = complement_ranges(layout.file_size, allowed_changes)
        donor_preserved = hash_ranges(donor, preserved_ranges)
        output_preserved = hash_ranges(temporary_output, preserved_ranges)
        if donor_preserved != output_preserved:
            raise RuntimeError("donor bytes changed outside declared ranges")
        if sha256(source) != source_sha256:
            raise RuntimeError("source RAF changed during conversion")
        if sha256(donor) != donor_sha256:
            raise RuntimeError("X2D donor changed during conversion")

        manifest: dict[str, object] = {
            "schema_version": 1,
            "source": {
                "path": str(source),
                "sha256": source_sha256,
                "metadata": source_meta,
            },
            "donor": {"path": str(donor), "sha256": donor_sha256},
            "output": {"path": str(output), "sha256": sha256(temporary_output)},
            "x2d_layout": {
                "width": layout.width,
                "height": layout.height,
                "strip_offset": layout.strip_offset,
                "strip_byte_count": layout.strip_byte_count,
                "preview_offset": layout.preview_offset,
                "preview_byte_count": layout.preview_byte_count,
                "crop_origin": layout.crop_origin,
                "crop_size": layout.crop_size,
                "black_level": layout.black_level,
                "white_level": layout.white_level,
                "software": layout.software,
                "raw_data_unique_id": layout.raw_data_unique_id,
            },
            "mapping": {**mapping, "preserved_sha256": donor_preserved},
            "sensor_mapping": {
                "mode": sensor_mapping,
                "matrix": sensor_matrix.tolist() if sensor_matrix is not None else None,
                "profile": (
                    "calibration/sensor/GFX100RF_TO_X2D100C_WB_ADAPTIVE_BOOTSTRAP.json"
                    if sensor_mapping == "wb-adaptive-bootstrap"
                    else "calibration/sensor/GFX100RF_TO_X2D100C_D65_BOOTSTRAP.json"
                    if sensor_mapping == "d65-dnglab-bootstrap"
                    else None
                ),
                "status": (
                    "experimental_bootstrap_not_camera_calibrated"
                    if sensor_matrix is not None
                    else "identity"
                ),
                "illuminant_source": (
                    selected_source_key
                    if sensor_mapping == "wb-adaptive-bootstrap"
                    else "fixed_d65"
                    if sensor_mapping == "d65-dnglab-bootstrap"
                    else None
                ),
                **sensor_mapping_evidence,
            },
            "x2d_calibration": {
                "mode": (
                    "inverse_precompensation" if inverse_x2d_calibration else "none"
                ),
                "q16_gains": calibration_gains,
                "calibration_cohort": calibration_cohort,
                "donor_software": layout.software,
                "evidence_pairs": (
                    list(calibration_profile["evidence_pairs"])
                    if calibration_profile is not None
                    else []
                ),
                "validated_scope": (
                    "Exact only for the selected observed donor body/firmware cohort; "
                    "body and firmware effects remain confounded"
                    if inverse_x2d_calibration
                    else "not applied"
                ),
            },
            "white_balance": {
                "selection": white_balance,
                "default": "auto",
                "source": (
                    "FujiIFD:WB_GRBLevelsAuto"
                    if white_balance == "auto"
                    else "FujiIFD:WB_GRBLevels"
                    if white_balance == "as-shot"
                    else "donor AsShotNeutral"
                ),
            },
            "preview": {
                "selection": preview,
                **preview_evidence,
                "policy": (
                    "The source RAF preview replaces the stale donor JPEG; zero padding "
                    "keeps the observed X2D file layout and preview slot unchanged."
                    if preview == "source"
                    else "The donor JPEG is retained only by explicit request."
                ),
            },
            "donor_lens_correction": {
                "selection": donor_lens_correction,
                "default": "neutralize",
                "status": (
                    "private_xcd_vignetting_dispatch_neutralized"
                    if donor_lens_correction == "neutralize"
                    else "donor_private_profile_preserved_for_diagnostics"
                ),
                "policy": (
                    "Retag only MakerNote 0x0018; preserve its 17-byte payload, "
                    "RAW pixels, camera calibration, and all other MakerNote fields."
                    if donor_lens_correction == "neutralize"
                    else "Phocus may automatically apply the donor XCD lens profile."
                ),
            },
            "lens_correction": {
                **lens_correction,
                "baked_vignetting": baked_vignetting,
                "profile_id": lens_profile["profile_id"],
                "profile_instance_id": lens_profile["profile_instance_id"],
                "lens": lens_profile["lens"],
                "container_patch": lens_opcode_patch,
                "execution_stage": (
                    "physical full-plane negative vignette in linear RAW; distortion and CA via RawIFD OpcodeList3"
                    if baked_vignetting is not None
                    else "Phocus RAW pipeline via RawIFD OpcodeList3"
                ),
                "claim_boundary": (
                    "Phocus 4.2.2 renders the embedded WarpRectilinear path; "
                    "profile accuracy remains bounded by the Fuji metadata model "
                    "and DNG radial-polynomial fit."
                ),
            },
            "capture_metadata": {
                **capture_metadata,
                "raw_data_unique_id": raw_data_id,
                "policy": {
                    "embedded": (
                        "source facts that fit existing standard X2D TIFF/EXIF slots"
                    ),
                    "sidecar_only": (
                        "source standard fields absent from the donor schema, including "
                        "timezone, subseconds, exposure mode, and optional GPS"
                    ),
                    "preserved_donor": (
                        "X2D camera identity, DNG color identity, and private "
                        "MakerNotes except the lens-correction dispatch tag when "
                        "neutralization is selected"
                    ),
                },
            },
            "metadata_patches": metadata_patches,
            "metadata_xmp": {
                **metadata_xmp_patch,
                "location_policy": "preserve" if preserve_location else "remove",
                "rights_policy": "preserve" if preserve_rights else "remove",
                "provenance_policy": "preserve" if preserve_provenance else "remove",
                "privacy_exclusions": [
                    "camera_serial",
                    "internal_serial",
                    "face_identity_and_geometry",
                ],
            },
            "allowed_changed_ranges": [
                list(byte_range) for byte_range in allowed_changes
            ]
            + ([lens_opcode_patch["append_range"]] if lens_opcode_patch is not None else [])
            + [metadata_xmp_patch["append_range"]],
            "claim_boundary": (
                "Observed X2D 3FR Phocus branch; no claim of complete hidden "
                "HNCS-stage identity or calibrated Fuji-to-X2D color equivalence."
            ),
        }
        write_json_temporary(temporary_manifest, manifest)
        publish_no_overwrite(temporary_output, output)
        try:
            publish_no_overwrite(temporary_manifest, manifest_path)
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        return manifest
    except BaseException:
        temporary_output.unlink(missing_ok=True)
        temporary_manifest.unlink(missing_ok=True)
        raise


def verify(donor: Path, candidate: Path) -> dict[str, object]:
    donor_layout = inspect_x2d(donor)
    candidate_layout = inspect_x2d(candidate)
    raw_layout_fields = (
        "byte_order", "make", "model", "width", "height", "bits_per_sample",
        "compression", "strip_offset", "strip_byte_count", "preview_offset",
        "crop_origin", "crop_size", "black_level", "white_level",
    )
    if any(
        getattr(donor_layout, field) != getattr(candidate_layout, field)
        for field in raw_layout_fields
    ):
        raise ValueError("candidate X2D RAW layout differs from donor")
    if not 0 < candidate_layout.preview_byte_count <= donor_layout.preview_byte_count:
        raise ValueError("candidate preview does not fit the donor preview slot")
    manifest_path = candidate.with_suffix(candidate.suffix + ".json")
    allowed = [(donor_layout.strip_offset, donor_layout.payload_end)]
    candidate_sha256 = sha256(candidate)
    source_check: dict[str, object] | None = None
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        append_ranges: list[tuple[int, int]] = []
        if manifest["donor"]["sha256"] != sha256(donor):
            raise ValueError("manifest donor hash differs from supplied donor")
        if manifest["output"]["sha256"] != candidate_sha256:
            raise ValueError("manifest output hash differs from supplied candidate")
        lens_record = manifest.get("lens_correction")
        if isinstance(lens_record, dict) and lens_record.get("mode") == "embedded_dng_opcode_list_3":
            patch = lens_record.get("container_patch")
            if not isinstance(patch, dict):
                raise ValueError("embedded lens correction lacks a container patch")
            with TiffReader(donor) as reader:
                ifd0 = reader.ifd(reader.first_ifd)
                subifds = ifd0.get(330)
                if subifds is None:
                    raise ValueError("donor lacks a SubIFDs pointer")
                pointer_offset, pointer_size = reader.value_location(subifds)
            expected_pointer_range = [pointer_offset, pointer_offset + pointer_size]
            if patch.get("pointer_range") != expected_pointer_range:
                raise ValueError("embedded lens correction pointer range differs")
            append_range = patch.get("append_range")
            if (
                not isinstance(append_range, list)
                or len(append_range) != 2
                or not all(isinstance(value, int) for value in append_range)
                or append_range[0] < donor.stat().st_size
                or append_range[1] <= append_range[0]
                or append_range[1] > candidate.stat().st_size
            ):
                raise ValueError("embedded lens correction append range differs")
            append_ranges.append((append_range[0], append_range[1]))
            with TiffReader(candidate) as reader:
                ifd0 = reader.ifd(reader.first_ifd)
                raw = reader.ifd(int(reader.required(ifd0, 330)[0]))
                opcode_entry = raw.get(51022)
                if opcode_entry is None:
                    raise ValueError("candidate lacks embedded OpcodeList3")
                payload_offset, payload_size = reader.value_location(opcode_entry)
                reader.handle.seek(payload_offset)
                payload = reader.handle.read(payload_size)
            if hashlib.sha256(payload).hexdigest() != patch.get("payload_sha256"):
                raise ValueError("embedded OpcodeList3 hash differs from manifest")
            allowed.append((pointer_offset, pointer_offset + pointer_size))
        xmp_record = manifest.get("metadata_xmp")
        if isinstance(xmp_record, dict):
            if xmp_record.get("pointer_range") != [4, 8]:
                raise ValueError("XMP root pointer range differs")
            append_range = xmp_record.get("append_range")
            if (
                not isinstance(append_range, list)
                or len(append_range) != 2
                or not all(isinstance(value, int) for value in append_range)
                or append_range[0] < donor.stat().st_size
                or append_range[1] <= append_range[0]
                or append_range[1] > candidate.stat().st_size
            ):
                raise ValueError("XMP append range differs")
            payload = read_xmp_payload(candidate)
            if payload is None:
                raise ValueError("candidate lacks embedded XMP")
            if hashlib.sha256(payload).hexdigest() != xmp_record.get("payload_sha256"):
                raise ValueError("embedded XMP hash differs from manifest")
            append_ranges.append((append_range[0], append_range[1]))
            allowed.append((4, 8))
        if append_ranges:
            cursor = donor.stat().st_size
            for start, end in sorted(append_ranges):
                if start != cursor:
                    raise ValueError("container append evidence is not contiguous")
                cursor = end
            if cursor != candidate.stat().st_size:
                raise ValueError("container append evidence does not cover candidate length")
        elif candidate.stat().st_size != donor.stat().st_size:
            raise ValueError("candidate length differs without append evidence")
        source_record = manifest.get("source")
        if isinstance(source_record, dict) and isinstance(source_record.get("path"), str):
            source_path = Path(source_record["path"])
            source_check = {"path": str(source_path), "present": source_path.is_file()}
            if source_path.is_file():
                source_digest = sha256(source_path)
                source_check["sha256"] = source_digest
                source_check["matches_manifest"] = source_digest == source_record.get("sha256")
                if not source_check["matches_manifest"]:
                    raise ValueError("source RAF hash differs from conversion manifest")
        preview_record = manifest.get("preview")
        preview_change_authorized = False
        if isinstance(preview_record, dict) and preview_record.get("selection") == "source":
            expected_preview_range = [donor_layout.preview_offset, donor_layout.preview_end]
            if preview_record.get("range") != expected_preview_range:
                raise ValueError("manifest preview range differs from donor slot")
            if preview_record.get("jpeg_bytes") != candidate_layout.preview_byte_count:
                raise ValueError("manifest preview length differs from candidate TIFF tag")
            with candidate.open("rb") as handle:
                handle.seek(candidate_layout.preview_offset)
                preview_bytes = handle.read(candidate_layout.preview_byte_count)
                padding = handle.read(
                    donor_layout.preview_byte_count - candidate_layout.preview_byte_count
                )
            if hashlib.sha256(preview_bytes).hexdigest() != preview_record.get("sha256"):
                raise ValueError("candidate preview hash differs from manifest")
            if any(padding):
                raise ValueError("candidate preview slot padding is not zero")
            allowed.append((donor_layout.preview_offset, donor_layout.preview_end))
            preview_change_authorized = True
        if (
            candidate_layout.preview_byte_count != donor_layout.preview_byte_count
            and not preview_change_authorized
        ):
            raise ValueError("candidate preview length differs without preview evidence")
        for patch in manifest.get("metadata_patches", []):
            if patch.get("tag") == "AsShotNeutral":
                offset, size, _, _ = as_shot_neutral_info(donor)
                expected_range = [offset, offset + size]
            elif patch.get("directory") == "HasselbladMakerNote":
                tag_id = patch.get("tag_id")
                if not isinstance(tag_id, int):
                    raise ValueError("MakerNote patch lacks a source tag id")
                entry_offset, type_id, count, payload_size, payload_sha256 = (
                    hasselblad_makernote_tag_info(donor, tag_id)
                )
                if type_id != 7 or count != 17 or payload_size != 17:
                    raise ValueError("donor MakerNote lens-dispatch layout is unsupported")
                if patch.get("payload_sha256") != payload_sha256:
                    raise ValueError("manifest MakerNote payload hash differs from donor")
                expected_range = [entry_offset, entry_offset + 2]
            else:
                directory = patch.get("directory")
                tag_id = patch.get("tag_id")
                if not isinstance(directory, str) or not isinstance(tag_id, int):
                    raise ValueError("metadata patch lacks a TIFF directory/tag id")
                expected_range = list(tiff_tag_range(donor, directory, tag_id))
            if patch.get("range") != expected_range:
                raise ValueError(f"manifest {patch.get('tag')} range differs from donor tag location")
            allowed.append((expected_range[0], expected_range[1]))
    else:
        if candidate_layout.preview_byte_count != donor_layout.preview_byte_count:
            raise ValueError("candidate preview length differs without an audit manifest")
        if candidate.stat().st_size != donor.stat().st_size:
            raise ValueError("candidate length differs without an audit manifest")
    ranges = complement_ranges(donor_layout.file_size, allowed)
    donor_preserved = hash_ranges(donor, ranges)
    candidate_preserved = hash_ranges(candidate, ranges)
    if donor_preserved != candidate_preserved:
        raise ValueError("candidate changed bytes outside declared ranges")
    return {
        "file_size": candidate.stat().st_size,
        "raw_range": [donor_layout.strip_offset, donor_layout.payload_end],
        "allowed_changed_ranges": [list(byte_range) for byte_range in allowed],
        "preserved_sha256": donor_preserved,
        "candidate_sha256": candidate_sha256,
        "source_check": source_check,
    }


def dataclass_replace_file_size(layout: X2DLayout, file_size: int) -> X2DLayout:
    values = {field: getattr(layout, field) for field in layout.__dataclass_fields__}
    values["file_size"] = file_size
    return X2DLayout(**values)
