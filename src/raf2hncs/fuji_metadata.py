from __future__ import annotations

import math
from typing import Any


_SHUTTER_TYPES = {
    0: "mechanical",
    1: "electronic",
    2: "electronic-long-exposure",
    3: "electronic-front-curtain",
}
_FOCUS_MODES = {0: "auto", 1: "manual", 65535: "movie"}
_AF_MODES = {0: "none", 1: "single-point", 256: "zone", 512: "wide-tracking"}
_DRIVE_MODES = {0: "single", 1: "continuous-low", 2: "continuous-high"}


def _integer(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _number(value: object) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _pair(value: object) -> list[int] | None:
    if isinstance(value, (list, tuple)):
        fields = list(value)
    else:
        fields = str(value).replace("x", " ").split() if value is not None else []
    if len(fields) != 2:
        return None
    try:
        return [int(float(item)) for item in fields]
    except (TypeError, ValueError):
        return None


def _coded(value: object, labels: dict[int, str]) -> dict[str, Any]:
    code = _integer(value)
    return {"code": code, "value": labels.get(code) if code is not None else None}


def _signed_coordinate(value: object, ref: object, negative_ref: str) -> float | None:
    number = _number(value)
    if number is None:
        return None
    if str(ref).strip().upper() == negative_ref:
        return -abs(number)
    return number


def fuji_framing(row: dict[str, object]) -> dict[str, Any]:
    ratio = _pair(row.get("RAF:RawImageAspectRatio"))
    zoom_active = _integer(row.get("RAF:RawZoomActive"))
    return {
        "orientation": _integer(row.get("IFD0:Orientation")),
        "aspect_ratio": {
            "width": ratio[0] if ratio else None,
            "height": ratio[1] if ratio else None,
            "source": "RAF:RawImageAspectRatio" if ratio else None,
        },
        "raw_zoom": {
            "active": zoom_active == 1 if zoom_active in (0, 1) else None,
            "top_left": _pair(row.get("RAF:RawZoomTopLeft")),
            "size": _pair(row.get("RAF:RawZoomSize")),
            "crop_mode": _integer(row.get("FujiFilm:CropMode")),
        },
        "raw_crop": {
            "top_left": _pair(row.get("RAF:RawImageCropTopLeft")),
            "size": _pair(row.get("RAF:RawImageCroppedSize")),
        },
        "source": "Fujifilm RAF framing metadata",
    }


def fuji_safe_metadata(row: dict[str, object]) -> dict[str, Any]:
    latitude = _signed_coordinate(
        row.get("GPS:GPSLatitude", row.get("Composite:GPSLatitude")),
        row.get("GPS:GPSLatitudeRef"),
        "S",
    )
    longitude = _signed_coordinate(
        row.get("GPS:GPSLongitude", row.get("Composite:GPSLongitude")),
        row.get("GPS:GPSLongitudeRef"),
        "W",
    )
    altitude = _number(row.get("GPS:GPSAltitude", row.get("Composite:GPSAltitude")))
    if altitude is not None and _integer(row.get("GPS:GPSAltitudeRef")) == 1:
        altitude = -abs(altitude)
    rating = _integer(row.get("XMP-xmp:Rating", row.get("FujiFilm:Rating")))
    return {
        "time": {
            "date_time_original": row.get("ExifIFD:DateTimeOriginal"),
            "create_date": row.get("ExifIFD:CreateDate"),
            "modify_date": row.get("IFD0:ModifyDate"),
            "offset_time": row.get("ExifIFD:OffsetTime"),
            "offset_time_original": row.get("ExifIFD:OffsetTimeOriginal"),
            "offset_time_digitized": row.get("ExifIFD:OffsetTimeDigitized"),
            "subsec_time": row.get("ExifIFD:SubSecTime"),
            "subsec_time_original": row.get("ExifIFD:SubSecTimeOriginal"),
            "subsec_time_digitized": row.get("ExifIFD:SubSecTimeDigitized"),
        },
        "location": {
            "present": latitude is not None and longitude is not None,
            "latitude": latitude,
            "longitude": longitude,
            "altitude_m": altitude,
            "gps_date_stamp": row.get("GPS:GPSDateStamp"),
            "gps_time_stamp": row.get("GPS:GPSTimeStamp"),
            "map_datum": row.get("GPS:GPSMapDatum"),
        },
        "rights": {
            "rating": rating,
            "artist": row.get("IFD0:Artist", row.get("IFD1:Artist")),
            "copyright": row.get("IFD0:Copyright"),
            "user_comment": row.get("ExifIFD:UserComment"),
        },
        "provenance": {
            "original_make": row.get("IFD0:Make"),
            "original_model": row.get("IFD0:Model"),
            "source_firmware": row.get("RAF:FirmwareVersion"),
        },
        "source": "standard EXIF/XMP and safe Fujifilm RAF fields",
    }


def fuji_capture_state(row: dict[str, object]) -> dict[str, Any]:
    return {
        "shutter_type": _coded(row.get("FujiFilm:ShutterType"), _SHUTTER_TYPES),
        "focus_mode": _coded(row.get("FujiFilm:FocusMode"), _FOCUS_MODES),
        "af_mode": _coded(row.get("FujiFilm:AFMode"), _AF_MODES),
        "focus_pixel": _pair(row.get("FujiFilm:FocusPixel")),
        "drive_mode": _coded(row.get("FujiFilm:DriveMode"), _DRIVE_MODES),
        "flash_exposure_compensation_ev": _number(
            row.get("FujiFilm:FlashExposureComp")
        ),
        "flicker_reduction_code": _integer(row.get("FujiFilm:FlickerReduction")),
        "camera_elevation_degrees": _number(row.get("ExifIFD:CameraElevationAngle")),
        "camera_roll_degrees": _number(row.get("FujiFilm:RollAngle")),
        "composite_image_code": _integer(row.get("ExifIFD:CompositeImage")),
        "warnings": {
            "blur": _integer(row.get("FujiFilm:BlurWarning")),
            "focus": _integer(row.get("FujiFilm:FocusWarning")),
            "exposure": _integer(row.get("FujiFilm:ExposureWarning")),
        },
        "source_encoding": {
            "raf_compression_code": _integer(row.get("RAF:RAFCompression")),
            "bits_per_sample": _integer(
                row.get("FujiIFD:BitsPerSample", row.get("File:BitsPerSample"))
            ),
        },
        "application_status": "record_only",
    }
