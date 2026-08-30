from __future__ import annotations

from raf2hncs.fuji_metadata import (
    fuji_capture_state,
    fuji_framing,
    fuji_safe_metadata,
)


def test_framing_decodes_orientation_aspect_ratio_and_digital_crop() -> None:
    framing = fuji_framing(
        {
            "IFD0:Orientation": 8,
            "RAF:RawImageAspectRatio": "65 24",
            "RAF:RawZoomActive": 1,
            "RAF:RawZoomTopLeft": "1296 972",
            "RAF:RawZoomSize": "9056 6792",
            "RAF:RawImageCropTopLeft": "7 8",
            "RAF:RawImageCroppedSize": "11648 8736",
            "FujiFilm:CropMode": 8,
        }
    )
    assert framing["orientation"] == 8
    assert framing["aspect_ratio"] == {
        "width": 65,
        "height": 24,
        "source": "RAF:RawImageAspectRatio",
    }
    assert framing["raw_zoom"] == {
        "active": True,
        "top_left": [1296, 972],
        "size": [9056, 6792],
        "crop_mode": 8,
    }
    assert framing["raw_crop"]["size"] == [11648, 8736]


def test_safe_metadata_preserves_time_location_rights_without_private_identity() -> None:
    metadata = fuji_safe_metadata(
        {
            "IFD0:Make": "FUJIFILM",
            "IFD0:Model": "GFX100RF",
            "RAF:FirmwareVersion": "0112",
            "ExifIFD:DateTimeOriginal": "2026:08:27 16:06:26",
            "ExifIFD:OffsetTimeOriginal": "+08:00",
            "ExifIFD:SubSecTimeOriginal": "65",
            "GPS:GPSLatitude": 30.2,
            "GPS:GPSLatitudeRef": "N",
            "GPS:GPSLongitude": 120.1,
            "GPS:GPSLongitudeRef": "E",
            "GPS:GPSAltitude": 20,
            "GPS:GPSAltitudeRef": 0,
            "XMP-xmp:Rating": 4,
            "IFD0:Artist": "Miao",
            "IFD0:Copyright": "Copyright Miao",
            "ExifIFD:UserComment": "note",
            "ExifIFD:SerialNumber": "must-not-copy",
            "FujiFilm:InternalSerialNumber": "must-not-copy",
            "FujiFilm:Face1Name": "must-not-copy",
        }
    )
    assert metadata["location"]["present"] is True
    assert metadata["location"]["latitude"] == 30.2
    assert metadata["location"]["longitude"] == 120.1
    assert metadata["rights"]["rating"] == 4
    assert metadata["time"]["subsec_time_original"] == "65"
    serialized = repr(metadata).lower()
    assert "serial" not in serialized
    assert "face" not in serialized
    assert "must-not-copy" not in serialized


def test_safe_metadata_signs_south_west_and_below_sea_level() -> None:
    location = fuji_safe_metadata(
        {
            "GPS:GPSLatitude": 33.9,
            "GPS:GPSLatitudeRef": "S",
            "GPS:GPSLongitude": 18.4,
            "GPS:GPSLongitudeRef": "W",
            "GPS:GPSAltitude": 12,
            "GPS:GPSAltitudeRef": 1,
        }
    )["location"]
    assert location["latitude"] == -33.9
    assert location["longitude"] == -18.4
    assert location["altitude_m"] == -12


def test_capture_state_is_record_only_and_unknown_codes_fail_soft() -> None:
    state = fuji_capture_state(
        {
            "FujiFilm:ShutterType": 0,
            "FujiFilm:FocusMode": 0,
            "FujiFilm:AFMode": 256,
            "FujiFilm:FocusPixel": "2107 1499",
            "FujiFilm:DriveMode": 9,
            "ExifIFD:CameraElevationAngle": -3.8,
            "FujiFilm:RollAngle": 2.2,
            "RAF:RAFCompression": 2,
            "FujiIFD:BitsPerSample": 16,
        }
    )
    assert state["shutter_type"] == {"code": 0, "value": "mechanical"}
    assert state["af_mode"] == {"code": 256, "value": "zone"}
    assert state["focus_pixel"] == [2107, 1499]
    assert state["drive_mode"] == {"code": 9, "value": None}
    assert state["source_encoding"] == {
        "raf_compression_code": 2,
        "bits_per_sample": 16,
    }
    assert state["application_status"] == "record_only"
