from __future__ import annotations

import json

import pytest

import numpy as np

from raf2hncs.lens import (
    _profile_splines,
    apply_fuji_lens_correction,
    decode_fuji_lens_arrays,
    extract_fuji_lens_profile,
    fuji_lens_maps,
)


def test_decode_modern_fuji_lens_arrays() -> None:
    knots = [0.35, 0.5, 0.61, 0.7, 0.79, 0.86, 0.93, 1.0, 1.06]
    profile = decode_fuji_lens_arrays(
        [808.0, *knots, *range(-1, -10, -1)],
        [808.0, *knots, *([0.001] * 9), *([0.002] * 9), 808.0],
        [808.0, *knots, *([50.0] * 9)],
        0,
    )
    assert profile["knots"] == knots
    assert profile["crop_factor"] == 1.0
    assert profile["distortion_percent"][-1] == -9
    assert profile["vignetting_percent"][-1] == 50.0


def test_decode_rejects_mismatched_knots() -> None:
    with pytest.raises(ValueError, match="knots disagree"):
        decode_fuji_lens_arrays(
            [0.0, *([1.0] * 18)],
            [0.0, *([2.0] * 9), *([0.0] * 18), 0.0],
            [0.0, *([1.0] * 18)],
            0,
        )


def test_fuji_lens_maps_identity_profile() -> None:
    decoded = {
        "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [100.0] * 9,
    }
    maps, vignette = fuji_lens_maps(decoded, width=8, height=6, y_start=1, y_end=4)
    expected_x = np.broadcast_to(np.arange(8, dtype=np.float32), (3, 8))
    expected_y = np.broadcast_to(np.arange(1, 4, dtype=np.float32)[:, None], (3, 8))
    for name in ("R", "G", "B"):
        assert np.allclose(maps[name][0], expected_x)
        assert np.allclose(maps[name][1], expected_y)
        assert np.allclose(vignette[name], 1.0)


def test_fuji_lens_maps_separates_red_and_blue_ca() -> None:
    decoded = {
        "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.01] * 9,
        "ca_blue_scale_offset": [-0.01] * 9,
        "vignetting_percent": [100.0] * 9,
    }
    maps, _ = fuji_lens_maps(decoded, width=100, height=80, y_start=0, y_end=1)
    center_x = 50.0
    assert maps["R"][0][0, 0] < maps["G"][0][0, 0] < maps["B"][0][0, 0] < center_x


def test_zero_component_strengths_make_non_identity_profile_identity() -> None:
    decoded = {
        "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        "distortion_percent": [-10.0] * 9,
        "ca_red_scale_offset": [0.02] * 9,
        "ca_blue_scale_offset": [-0.02] * 9,
        "vignetting_percent": [45.0] * 9,
    }
    maps, vignette = fuji_lens_maps(
        decoded,
        width=8,
        height=6,
        y_start=1,
        y_end=4,
        distortion_strength=0,
        chromatic_aberration_strength=0,
        vignetting_strength=0,
    )
    expected_x = np.broadcast_to(np.arange(8, dtype=np.float32), (3, 8))
    expected_y = np.broadcast_to(np.arange(1, 4, dtype=np.float32)[:, None], (3, 8))
    for name in ("R", "G", "B"):
        assert np.allclose(maps[name][0], expected_x)
        assert np.allclose(maps[name][1], expected_y)
        assert np.allclose(vignette[name], 1.0)


def test_component_strengths_are_bounded() -> None:
    decoded = {
        "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [100.0] * 9,
    }
    with pytest.raises(ValueError, match="between -2 and 2"):
        fuji_lens_maps(decoded, 8, 6, 0, 1, distortion_strength=2.1)
    with pytest.raises(ValueError, match="between -2 and 2"):
        fuji_lens_maps(decoded, 8, 6, 0, 1, chromatic_aberration_strength=-2.1)


def test_signed_profile_strengths_reverse_each_lens_component() -> None:
    decoded = {
        "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        "distortion_percent": [-8.0] * 9,
        "ca_red_scale_offset": [0.01] * 9,
        "ca_blue_scale_offset": [-0.01] * 9,
        "vignetting_percent": [50.0] * 9,
    }
    positive = _profile_splines(decoded, distortion_strength=1, chromatic_aberration_strength=1, vignetting_strength=1)
    negative = _profile_splines(decoded, distortion_strength=-1, chromatic_aberration_strength=-1, vignetting_strength=-1)

    assert positive["green_scale"][-1] < 1 < negative["green_scale"][-1]
    assert positive["red_scale"][-1] > positive["green_scale"][-1]
    assert negative["red_scale"][-1] < negative["green_scale"][-1]
    assert positive["blue_scale"][-1] < positive["green_scale"][-1]
    assert negative["blue_scale"][-1] > negative["green_scale"][-1]
    assert positive["vignette_scale"][-1] == pytest.approx(0.5)
    assert negative["vignette_scale"][-1] == pytest.approx(2.0)


def test_signed_vignetting_strength_is_reciprocal_and_doubles_in_log_domain() -> None:
    decoded = {
        "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [50.0] * 9,
    }
    scales = {
        strength: _profile_splines(decoded, vignetting_strength=strength)["vignette_scale"][-1]
        for strength in (-2, -1, 0, 1, 2)
    }
    assert scales == pytest.approx({-2: 4.0, -1: 2.0, 0: 1.0, 1: 0.5, 2: 0.25})


def test_extract_profile_uses_file_metadata_and_stable_profile_id(tmp_path, monkeypatch) -> None:
    source = tmp_path / "future-camera.RAF"
    source.write_bytes(b"profile-source")
    knots = " ".join(str(value) for value in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0])
    row = {
        "IFD0:Make": "FUTURE",
        "IFD0:Model": "CAMERA 2",
        "ExifIFD:LensMake": "OPTICS",
        "ExifIFD:LensModel": "ZOOM 20-40",
        "ExifIFD:FocalLength": 27,
        "ExifIFD:MaxApertureValue": 2.8,
        "ExifIFD:FocalLengthIn35mmFormat": 22,
        "FujiFilm:CropMode": 0,
        "FujiIFD:GeometricDistortionParams": f"0 {knots} " + " ".join(["-1"] * 9),
        "FujiIFD:ChromaticAberrationParams": f"0 {knots} " + " ".join(["0"] * 18) + " 0",
        "FujiIFD:VignettingParams": f"0 {knots} " + " ".join(["90"] * 9),
    }

    class Result:
        stdout = json.dumps([row])

    monkeypatch.setattr("raf2hncs.lens.subprocess.run", lambda *args, **kwargs: Result())
    first = extract_fuji_lens_profile(source, "exiftool")
    second = extract_fuji_lens_profile(source, "exiftool")
    assert first["schema_version"] == 2
    assert first["profile_id"] == second["profile_id"]
    assert first["camera"] == {"make": "FUTURE", "model": "CAMERA 2"}
    assert first["lens"]["model"] == "ZOOM 20-40"
    assert first["output_metadata"]["focal_length"] == 27
    assert first["output_metadata"]["focal_length_35mm"] == 22
    assert all(first["capabilities"].values()) is False


def test_apply_identity_profile_preserves_pixels_and_writes_fuji_metadata(
    tmp_path, monkeypatch
) -> None:
    cv2 = pytest.importorskip("cv2")
    image = np.arange(8 * 10 * 3, dtype=np.uint8).reshape(8, 10, 3)
    source = tmp_path / "source.tif"
    output = tmp_path / "output.tif"
    profile_path = tmp_path / "profile.json"
    assert cv2.imwrite(str(source), image)
    profile_path.write_text(
        json.dumps(
            {
                "source": {"sha256": "ab" * 32},
                "output_metadata": {
                    "make": "FUJIFILM",
                    "model": "GFX100RF",
                    "lens_make": "FUJIFILM",
                    "lens_model": "FUJINON 35mm F4",
                    "focal_length_35mm": 28,
                },
                "decoded": {
                    "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
                    "distortion_percent": [0.0] * 9,
                    "ca_red_scale_offset": [0.0] * 9,
                    "ca_blue_scale_offset": [0.0] * 9,
                    "vignetting_percent": [100.0] * 9,
                }
            }
        ),
        encoding="utf-8",
    )
    exiftool_calls = []

    def fake_run(arguments, **_kwargs):
        exiftool_calls.append(arguments)

    monkeypatch.setattr("raf2hncs.lens.subprocess.run", fake_run)
    manifest = apply_fuji_lens_correction(
        source, profile_path, output, stripe_rows=3, input_gamma=2.2, exiftool="exiftool"
    )
    assert np.array_equal(cv2.imread(str(output), cv2.IMREAD_UNCHANGED), image)
    assert manifest["algorithm"]["input_transfer_gamma"] == 2.2
    assert manifest["algorithm"]["components"] == {
        "distortion_strength": 1.0,
        "vignetting_strength": 1.0,
        "lateral_chromatic_aberration_strength": 1.0,
        "defringe": {
            "strength": 0.0,
            "threshold": 0.04,
            "radius": 1.5,
            "source": "image_analysis_not_lens_profile",
        },
    }
    assert "-Make=FUJIFILM" in exiftool_calls[0]
    assert "-LensModel=FUJINON 35mm F4" in exiftool_calls[0]
    assert "-FocalLengthIn35mmFormat=28" in exiftool_calls[0]
    assert "-ImageUniqueID=" + "AB" * 16 in exiftool_calls[0]


def test_optional_defringe_changes_high_contrast_fringe_and_records_parameters(tmp_path) -> None:
    cv2 = pytest.importorskip("cv2")
    image = np.full((20, 24, 3), 40, dtype=np.uint8)
    image[:, 12:, :] = 220
    image[4:16, 11, :] = [255, 0, 255]
    source = tmp_path / "fringe.tif"
    output = tmp_path / "defringed.tif"
    profile_path = tmp_path / "profile.json"
    assert cv2.imwrite(str(source), image)
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source": {"sha256": "cd" * 32},
                "decoded": {
                    "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
                    "distortion_percent": [0.0] * 9,
                    "ca_red_scale_offset": [0.0] * 9,
                    "ca_blue_scale_offset": [0.0] * 9,
                    "vignetting_percent": [100.0] * 9,
                },
            }
        ),
        encoding="utf-8",
    )
    manifest = apply_fuji_lens_correction(
        source,
        profile_path,
        output,
        distortion_strength=0,
        vignetting_strength=0,
        chromatic_aberration_strength=0,
        defringe_strength=1.0,
        defringe_threshold=0.0,
        defringe_radius=1.0,
        stripe_rows=7,
    )
    corrected = cv2.imread(str(output), cv2.IMREAD_UNCHANGED)
    assert not np.array_equal(corrected[4:16, 11], image[4:16, 11])
    assert manifest["algorithm"]["components"]["defringe"]["strength"] == 1.0


def test_disabling_all_profile_components_is_pixel_exact_for_16_bit(tmp_path) -> None:
    cv2 = pytest.importorskip("cv2")
    image = np.arange(12 * 16 * 3, dtype=np.uint16).reshape(12, 16, 3) * 97
    source = tmp_path / "source-16.tif"
    output = tmp_path / "disabled-16.tif"
    profile_path = tmp_path / "non-identity-profile.json"
    assert cv2.imwrite(str(source), image)
    profile_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "source": {"sha256": "ef" * 32},
                "decoded": {
                    "knots": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0],
                    "distortion_percent": [-10.0] * 9,
                    "ca_red_scale_offset": [0.02] * 9,
                    "ca_blue_scale_offset": [-0.02] * 9,
                    "vignetting_percent": [45.0] * 9,
                },
            }
        ),
        encoding="utf-8",
    )
    apply_fuji_lens_correction(
        source,
        profile_path,
        output,
        distortion_strength=0,
        vignetting_strength=0,
        chromatic_aberration_strength=0,
        defringe_strength=0,
        input_gamma=2.19921875,
        stripe_rows=5,
    )
    assert np.array_equal(cv2.imread(str(output), cv2.IMREAD_UNCHANGED), image)
