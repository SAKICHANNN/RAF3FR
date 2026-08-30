from __future__ import annotations

from pathlib import Path

from raf2hncs.source_info import source_presentation_from_row


def test_source_presentation_preserves_capture_facts(tmp_path: Path) -> None:
    source = tmp_path / "DSCF0001.RAF"
    source.write_bytes(b"raw")
    preview = tmp_path / "preview.jpg"
    preview.write_bytes(b"jpeg")
    row = {
        "IFD0:Make": "FUJIFILM",
        "IFD0:Model": "GFX 100RF",
        "ExifIFD:LensMake": "FUJIFILM",
        "ExifIFD:LensModel": "35mm F4",
        "ExifIFD:ExposureTime": 0.004,
        "ExifIFD:FNumber": 4,
        "ExifIFD:ISO": 4000,
        "ExifIFD:SensitivityType": 1,
        "ExifIFD:StandardOutputSensitivity": 5000,
        "ExifIFD:FocalLength": 35,
        "ExifIFD:FocalLengthIn35mmFormat": 28,
        "ExifIFD:ExposureCompensation": -0.67,
        "RAF:RawExposureBias": -1.72,
        "FujiFilm:AutoDynamicRange": 200,
        "FujiFilm:HighlightTone": 8,
        "FujiFilm:ShadowTone": -8,
        "FujiFilm:GrainEffectRoughness": 32,
        "FujiFilm:GrainEffectSize": 16,
        "ExifIFD:DateTimeOriginal": "2026:08:28 13:44:50",
        "ExifIFD:OffsetTimeOriginal": "+08:00",
        "FujiFilm:WhiteBalance": 0,
        "FujiFilm:ColorTemperature": 5200,
        "File:ImageWidth": 11648,
        "File:ImageHeight": 8736,
        "IFD0:Orientation": 8,
        "RAF:RawImageAspectRatio": "1 1",
        "RAF:RawZoomActive": 0,
        "RAF:RawZoomTopLeft": "0 0",
        "RAF:RawZoomSize": "11648 8736",
        "ExifIFD:SubSecTimeOriginal": "65",
        "XMP-xmp:Rating": 3,
        "FujiFilm:FilmMode": 2816,
        "FujiFilm:Saturation": 192,
    }

    result = source_presentation_from_row(source, row, preview)

    assert result["camera"] == {"make": "FUJIFILM", "model": "GFX 100RF"}
    assert result["lens"]["model"] == "35mm F4"
    assert result["capture"]["iso"] == 5000
    assert result["capture"]["exposure_time_seconds"] == 0.004
    assert result["capture"]["exposure_compensation_ev"] == -0.67
    assert result["capture"]["raw_exposure_bias_ev"] == -1.72
    assert result["capture"]["recommended_phocus_compensation_ev"] == 1.72
    assert result["capture"]["dynamic_range_percent"] == 200
    assert result["rendering_intent"]["tone_curve"]["highlight"] == -0.5
    assert result["rendering_intent"]["tone_curve"]["shadow"] == 0.5
    assert result["rendering_intent"]["grain"]["roughness"] == "weak"
    assert result["rendering_intent"]["creative"]["film_simulation"]["value"] == "reala-ace"
    assert result["framing"]["orientation"] == 8
    assert result["framing"]["aspect_ratio"]["width"] == 1
    assert result["standard_metadata"]["time"]["subsec_time_original"] == "65"
    assert result["standard_metadata"]["rights"]["rating"] == 3
    assert result["preview"] == {"path": str(preview), "bytes": 4}
