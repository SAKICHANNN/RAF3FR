from __future__ import annotations

import json
import math
import os
import subprocess
from pathlib import Path

from .transplant import effective_capture_iso
from .fuji_rendering import fuji_rendering_intent
from .fuji_metadata import fuji_capture_state, fuji_framing, fuji_safe_metadata


SOURCE_PRESENTATION_TAGS = (
    "Make",
    "Model",
    "LensMake",
    "LensModel",
    "ExposureTime",
    "FNumber",
    "ISO",
    "SensitivityType",
    "StandardOutputSensitivity",
    "DateTimeOriginal",
    "OffsetTimeOriginal",
    "ExposureCompensation",
    "RawExposureBias",
    "DevelopmentDynamicRange",
    "DynamicRangeSetting",
    "AutoDynamicRange",
    "DRangePriority",
    "DRangePriorityAuto",
    "DRangePriorityFixed",
    "HighlightTone",
    "ShadowTone",
    "GrainEffectRoughness",
    "GrainEffectSize",
    "FocalLength",
    "FocalLengthIn35mmFormat",
    "FocalLength35efl",
    "WhiteBalance",
    "ColorTemperature",
    "ImageWidth",
    "ImageHeight",
    "RawImageCroppedSize",
    "RawImageCropTopLeft",
    "RawImageAspectRatio",
    "RawZoomActive",
    "RawZoomTopLeft",
    "RawZoomSize",
    "Orientation",
    "CropMode",
    "FilmMode",
    "Saturation",
    "Contrast",
    "ColorChromeEffect",
    "ColorChromeFXBlue",
    "BWAdjustment",
    "BWMagentaGreen",
    "Clarity",
    "Sharpness",
    "NoiseReduction",
    "LensModulationOptimizer",
    "Artist",
    "Copyright",
    "UserComment",
    "Rating",
    "CreateDate",
    "ModifyDate",
    "OffsetTime",
    "OffsetTimeDigitized",
    "SubSecTime",
    "SubSecTimeOriginal",
    "SubSecTimeDigitized",
    "GPS*",
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
    "CameraElevationAngle",
    "RollAngle",
    "CompositeImage",
    "BlurWarning",
    "FocusWarning",
    "ExposureWarning",
)


def _first(row: dict[str, object], *keys: str, default: object = None) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return default


def source_presentation_from_row(
    source: Path, row: dict[str, object], preview: Path | None
) -> dict[str, object]:
    required = ("ExifIFD:ExposureTime", "ExifIFD:FNumber", "ExifIFD:ISO")
    missing = [key for key in required if key not in row]
    if missing:
        raise ValueError(f"source RAF lacks presentation metadata: {missing}")
    capture_iso, _, capture_iso_source = effective_capture_iso(row)
    lens_make = str(_first(row, "ExifIFD:LensMake", default="FUJIFILM"))
    lens_model = str(_first(row, "ExifIFD:LensModel", default="35mm F4"))
    focal_length = float(_first(row, "ExifIFD:FocalLength", default=0))
    focal_length_35mm = _first(
        row, "ExifIFD:FocalLengthIn35mmFormat", "Composite:FocalLength35efl"
    )
    if focal_length_35mm is None and focal_length:
        focal_length_35mm = focal_length * math.hypot(36.0, 24.0) / math.hypot(43.8, 32.9)
    raw_size = str(_first(row, "RAF:RawImageCroppedSize", default="0 0")).split()
    width, height = (int(float(value)) for value in raw_size[:2]) if len(raw_size) >= 2 else (0, 0)
    rendering_intent = fuji_rendering_intent(row)
    result: dict[str, object] = {
        "schema_version": 2,
        "file": {
            "name": source.name,
            "bytes": source.stat().st_size,
        },
        "camera": {
            "make": str(_first(row, "IFD0:Make", default="FUJIFILM")),
            "model": str(_first(row, "IFD0:Model", default="GFX 100RF")),
        },
        "lens": {
            "make": lens_make,
            "model": lens_model,
        },
        "capture": {
            "exposure_time_seconds": float(row["ExifIFD:ExposureTime"]),
            "f_number": float(row["ExifIFD:FNumber"]),
            "iso": capture_iso,
            "iso_source": capture_iso_source,
            "focal_length_mm": focal_length,
            "focal_length_equivalent_mm": int(round(float(focal_length_35mm or 0))),
            "exposure_compensation_ev": float(
                _first(row, "ExifIFD:ExposureCompensation", default=0)
            ),
            "raw_exposure_bias_ev": float(
                _first(row, "RAF:RawExposureBias", default=0)
            ),
            "recommended_phocus_compensation_ev": -float(
                _first(row, "RAF:RawExposureBias", default=0)
            ),
            "dynamic_range_percent": rendering_intent["dynamic_range"]["percent"],
            "date_time_original": str(
                _first(row, "ExifIFD:DateTimeOriginal", default="")
            ),
            "offset_time_original": str(
                _first(row, "ExifIFD:OffsetTimeOriginal", default="")
            ),
            "white_balance_code": int(
                _first(row, "FujiFilm:WhiteBalance", "ExifIFD:WhiteBalance", default=0)
            ),
            "color_temperature_kelvin": _first(
                row, "FujiFilm:ColorTemperature", default=None
            ),
        },
        "rendering_intent": rendering_intent,
        "framing": fuji_framing(row),
        "standard_metadata": fuji_safe_metadata(row),
        "capture_state": fuji_capture_state(row),
        "image": {
            "width": width,
            "height": height,
        },
        "preview": None,
    }
    if preview is not None:
        result["preview"] = {"path": str(preview), "bytes": preview.stat().st_size}
    return result


def inspect_fuji_source(
    source: Path, exiftool: str, preview_output: Path | None = None
) -> dict[str, object]:
    completed = subprocess.run(
        [
            exiftool,
            "-j",
            "-n",
            "-G1",
            "-s",
            *[f"-{tag}" for tag in SOURCE_PRESENTATION_TAGS],
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    row = json.loads(completed.stdout)[0]
    installed_preview: Path | None = None
    if preview_output is not None:
        preview = subprocess.run(
            [exiftool, "-PreviewImage", "-b", str(source)],
            check=True,
            capture_output=True,
        ).stdout
        if preview.startswith(b"\xff\xd8") and preview.rstrip().endswith(b"\xff\xd9"):
            preview_output.parent.mkdir(parents=True, exist_ok=True)
            partial = preview_output.with_name(preview_output.name + ".partial")
            partial.write_bytes(preview)
            os.replace(partial, preview_output)
            installed_preview = preview_output
    return source_presentation_from_row(source, row, installed_preview)
