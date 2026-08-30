from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest

from raf2hncs.tiff import IfdEntry
from raf2hncs.tiff import TiffReader
from raf2hncs.tiff import X2DLayout
from raf2hncs.tiff import encode_tiff_values
from raf2hncs.tiff import encode_unsigned_rationals
from raf2hncs.tiff import hasselblad_makernote_tag_info
from raf2hncs.tiff import neutralize_hasselblad_lens_correction
from raf2hncs.transplant import complement_ranges
from raf2hncs.transplant import apply_iso_policy
from raf2hncs.transplant import bake_negative_vignetting
from raf2hncs.transplant import apply_hnnr_iso_policy
from raf2hncs.transplant import effective_capture_iso
from raf2hncs.transplant import find_tool
from raf2hncs.transplant import jpeg_dimensions
from raf2hncs.transplant import map_active_lattice
from raf2hncs.transplant import map_crop
from raf2hncs.transplant import nearest_x2d_iso
from raf2hncs.transplant import parity_preserving_indices
from raf2hncs.transplant import publish_no_overwrite
from raf2hncs.transplant import read_fuji_capture_metadata
from raf2hncs.transplant import patch_preview_slot
from raf2hncs.transplant import wb_coefficients_from_grb_levels
from raf2hncs.transplant import write_json_temporary
from raf2hncs.sensor import GFX100RF_D65_COLOR_MATRIX
from raf2hncs.sensor import GFX100RF_A_COLOR_MATRIX
from raf2hncs.sensor import GFX100RF_TO_X2D100C_D65_BOOTSTRAP
from raf2hncs.sensor import X2D100C_D65_COLOR_MATRIX
from raf2hncs.sensor import adaptive_sensor_mapping
from raf2hncs.sensor import gfx100rf_matrix_for_cct
from raf2hncs.sensor import transform_wb_coefficients


def test_jpeg_dimensions_reads_frame_header() -> None:
    jpeg = (
        b"\xff\xd8"
        + b"\xff\xe0\x00\x04\x00\x00"
        + b"\xff\xc0\x00\x11\x08\x0b\xb8\x0f\xa0"
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )
    assert jpeg_dimensions(jpeg) == (4000, 3000)


def test_baked_negative_vignetting_is_physical_and_preserves_margins() -> None:
    target = np.full((40, 44), 777, dtype=np.uint16)
    rng = np.random.default_rng(7)
    active = target[4:36, 6:38]
    active[:] = np.clip(
        1000 + rng.normal(0, 40, active.shape), 0, 2000
    ).astype(np.uint16)
    before = target.copy()
    decoded = {
        "knots": np.linspace(0.1, 0.9, 9).tolist(),
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [50.0] * 9,
    }
    report = bake_negative_vignetting(
        target,
        black_level=100,
        white_level=2000,
        decoded_profile=decoded,
        distortion_strength=0,
        vignetting_strength=-1,
        crop_origin=(6, 4),
        crop_size=(32, 32),
        gaussian_sigma=2,
        noise_seed="physical-vignette-test",
    )
    assert np.array_equal(target[:4], before[:4])
    assert np.array_equal(target[36:], before[36:])
    assert np.array_equal(target[:, :6], before[:, :6])
    assert np.array_equal(target[:, 38:], before[:, 38:])
    center_mean = float(np.mean(target[17:23, 19:25]))
    corner_mean = float(np.mean(target[4:10, 6:12]))
    assert corner_mean < center_mean
    assert report["mode"] == "fullplane_physical_negative_vignette_v2"
    assert report["minimum_gain"] == pytest.approx(0.5)
    assert report["active_origin"] == [6, 4]
    assert report["active_size"] == [32, 32]
    assert report["clipped_below_code_zero"] == 0
    assert report["clipped_above_white"] == 0
    assert report["noise_generator"].startswith("NumPy PCG64")


def test_baked_negative_vignetting_does_not_create_point_light_dark_ring() -> None:
    target = np.full((128, 128), 1200, dtype=np.uint16)
    light_y, light_x = 20, 20
    target[light_y, light_x] = 60000
    decoded = {
        "knots": np.linspace(0.1, 0.9, 9).tolist(),
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [50.0] * 9,
    }
    bake_negative_vignetting(
        target,
        black_level=1000,
        white_level=65535,
        decoded_profile=decoded,
        distortion_strength=0,
        vignetting_strength=-1,
        gaussian_sigma=3,
        noise_seed="point-light-regression",
    )
    signal = target.astype(np.float64) - 1000
    yy, xx = np.indices(signal.shape)
    radius = np.hypot(xx - light_x, yy - light_y)
    annulus_mean = float(np.mean(signal[(radius >= 4) & (radius <= 12)]))
    background_mean = float(np.mean(signal[(radius >= 14) & (radius <= 20)]))
    assert annulus_mean == pytest.approx(background_mean, rel=0.03)
    assert signal[light_y, light_x] > 20000


def test_baked_negative_vignetting_has_no_chunk_boundary_signature() -> None:
    target = np.full((98, 102), 1200, dtype=np.uint16)
    yy, xx = np.indices(target.shape)
    target += ((xx + 2 * yy) % 17).astype(np.uint16)
    decoded = {
        "knots": np.linspace(0.1, 0.9, 9).tolist(),
        "distortion_percent": [0.0] * 9,
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [50.0] * 9,
    }
    reference = target.copy()
    bake_negative_vignetting(
        reference,
        black_level=100,
        white_level=2000,
        decoded_profile=decoded,
        distortion_strength=0,
        vignetting_strength=-2,
        gaussian_sigma=3,
        gain_chunk_rows=128,
        noise_seed="chunk-invariance",
    )
    chunked_gain = target.copy()
    bake_negative_vignetting(
        chunked_gain,
        black_level=100,
        white_level=2000,
        decoded_profile=decoded,
        distortion_strength=0,
        vignetting_strength=-2,
        gaussian_sigma=3,
        gain_chunk_rows=7,
        noise_seed="chunk-invariance",
    )
    assert np.array_equal(chunked_gain, reference)


def write_synthetic_hasselblad_makernote(
    path: Path, *, lens_tag_count: int = 17
) -> bytes:
    data = bytearray(128)
    payload = bytes(range(17))
    data[:8] = b"II" + struct.pack("<HI", 42, 8)
    data[8:26] = (
        struct.pack("<H", 1)
        + struct.pack("<HHII", 34665, 4, 1, 32)
        + struct.pack("<I", 0)
    )
    data[32:50] = (
        struct.pack("<H", 1)
        + struct.pack("<HHII", 37500, 7, 64, 64)
        + struct.pack("<I", 0)
    )
    data[64:82] = (
        struct.pack("<H", 1)
        + struct.pack("<HHII", 0x0018, 7, lens_tag_count, 96)
        + struct.pack("<I", 0)
    )
    data[96:113] = payload
    path.write_bytes(data)
    return payload


def test_centered_x_mapping_preserves_cfa_phase() -> None:
    indices = parity_preserving_indices(8, 11648, 128, 11656, 4)
    assert indices[4] == 0
    assert indices[-5] == 11647
    assert np.all(((8 + indices) ^ (128 + np.arange(11656))) & 1 == 0)


def test_centered_y_mapping_preserves_cfa_phase() -> None:
    indices = parity_preserving_indices(7, 8736, 96, 8742, 3)
    assert indices[3] == 0
    assert indices[-4] == 8735
    assert np.all(((7 + indices) ^ (96 + np.arange(8742))) & 1 == 0)


def test_border_extension_uses_same_color_sites() -> None:
    indices = parity_preserving_indices(7, 4, 96, 10, 3)
    assert list(indices[:3]) == [1, 0, 1]
    assert list(indices[-3:]) == [2, 3, 2]


def test_map_crop_preserves_margins_and_maps_code_domain() -> None:
    source = np.full((4, 6), 50, dtype=np.uint16)
    target = np.full((6, 10), 999, dtype=np.uint16)
    source_meta = {
        "crop_x": 0,
        "crop_y": 1,
        "crop_width": 4,
        "crop_height": 2,
        "black_levels": [0, 0, 0, 0],
        "black_width": 2,
        "black_height": 2,
        "white_level": 100,
    }
    layout = X2DLayout(
        byte_order="little",
        make="Hasselblad",
        model="X2D 100C",
        width=10,
        height=6,
        bits_per_sample=16,
        compression=1,
        strip_offset=0,
        strip_byte_count=120,
        preview_offset=0,
        preview_byte_count=0,
        crop_origin=(1, 0),
        crop_size=(6, 4),
        black_level=10,
        white_level=110,
        file_size=120,
    )

    padding = map_crop(source, target, source_meta, layout)

    assert padding == {
        "mode": "default_crop_with_same_colour_extension",
        "pad_left": 1,
        "pad_right": 1,
        "pad_top": 1,
        "pad_bottom": 1,
    }
    assert np.all(target[0:4, 1:7] == 60)
    assert np.all(target[:, 0] == 999)
    assert np.all(target[4:, :] == 999)


def test_complement_ranges_merges_declared_changes() -> None:
    assert complement_ranges(100, [(10, 20), (18, 30), (70, 80)]) == [(0, 10), (30, 70), (80, 100)]


@pytest.mark.parametrize(
    ("capture_iso", "expected_model_iso"),
    [
        (40, 40),
        (64, 64),
        (80, 80),
        (320, 320),
        (6400, 6400),
        (8000, 6400),
        (10000, 6400),
        (12800, 6400),
        (102400, 6400),
    ],
)
def test_hnnr_iso_policy_only_caps_high_iso(
    capture_iso: int, expected_model_iso: int
) -> None:
    capture = {
        "source_standard": {"ExifIFD:ISO": capture_iso},
        "embedded_values": {"ISO": capture_iso},
    }

    result = apply_hnnr_iso_policy(capture, True)

    assert result["capture_iso"] == capture_iso
    assert result["source_standard"]["ExifIFD:ISO"] == capture_iso
    assert result["embedded_values"]["ISO"] == expected_model_iso
    assert result["hnnr_compatibility"]["adjusted"] is (
        capture_iso != expected_model_iso
    )


def test_hnnr_iso_policy_can_preserve_capture_iso() -> None:
    capture = {"embedded_values": {"ISO": 12800}}

    result = apply_hnnr_iso_policy(capture, False)

    assert result["capture_iso"] == 12800
    assert result["embedded_values"]["ISO"] == 12800
    assert result["hnnr_compatibility"]["policy"] == "preserve_capture_iso"

    extended = apply_hnnr_iso_policy(
        {
            "source_standard": {"ExifIFD:StandardOutputSensitivity": 102400},
            "embedded_values": {"ISO": 102400},
        },
        False,
    )
    assert extended["capture_iso"] == 102400
    assert extended["embedded_values"]["ISO"] == 65535
    assert extended["hnnr_compatibility"]["policy"] == "exif_short_sentinel"


@pytest.mark.parametrize(
    ("capture_iso", "expected_model_iso"),
    [
        (40, 64),
        (64, 64),
        (80, 64),
        (100, 100),
        (320, 400),
        (6400, 6400),
        (8000, 6400),
        (10000, 12800),
        (12800, 12800),
        (25600, 25600),
        (51200, 25600),
        (102400, 25600),
    ],
)
def test_nearest_x2d_iso_uses_ev_distance_and_lower_tie(
    capture_iso: int, expected_model_iso: int
) -> None:
    assert nearest_x2d_iso(capture_iso) == expected_model_iso
    result = apply_iso_policy({"embedded_values": {"ISO": capture_iso}})
    assert result["capture_iso"] == capture_iso
    assert result["embedded_values"]["ISO"] == expected_model_iso
    assert result["iso_policy"]["mode"] == "nearest-x2d"


def test_iso_policy_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="unsupported ISO policy"):
        apply_iso_policy({"embedded_values": {"ISO": 320}}, "invalid")
    with pytest.raises(ValueError, match="positive"):
        nearest_x2d_iso(0)


@pytest.mark.parametrize(
    ("raw_bias", "dynamic_range", "expected_compensation"),
    [(-0.72, 100, 0.72), (-1.72, 200, 1.72)],
)
def test_fuji_raw_exposure_bias_is_recorded_for_phocus_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    raw_bias: float,
    dynamic_range: int,
    expected_compensation: float,
) -> None:
    row = {
        "IFD0:Make": "FUJIFILM",
        "IFD0:Model": "GFX100RF",
        "IFD0:ModifyDate": "2026:08:28 13:44:50",
        "ExifIFD:ExposureTime": 0.004,
        "ExifIFD:FNumber": 4,
        "ExifIFD:ExposureProgram": 1,
        "ExifIFD:ISO": 6400,
        "ExifIFD:SensitivityType": 1,
        "ExifIFD:StandardOutputSensitivity": 6400,
        "ExifIFD:DateTimeOriginal": "2026:08:28 13:44:50",
        "ExifIFD:ExposureCompensation": -0.67,
        "ExifIFD:MaxApertureValue": 4,
        "ExifIFD:MeteringMode": 5,
        "ExifIFD:Flash": 0,
        "ExifIFD:FocalLength": 35,
        "ExifIFD:ColorSpace": 1,
        "RAF:RawExposureBias": raw_bias,
        "FujiFilm:AutoDynamicRange": dynamic_range,
    }

    class Completed:
        stdout = json.dumps([row])

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Completed())
    result = read_fuji_capture_metadata(Path("source.RAF"), "exiftool")
    matching = result["exposure_matching"]
    assert result["standard_metadata"]["provenance"] == {
        "original_make": "FUJIFILM",
        "original_model": "GFX100RF",
        "source_firmware": None,
    }
    assert matching["source_raw_exposure_bias_ev"] == raw_bias
    assert matching["recommended_phocus_compensation_ev"] == pytest.approx(
        expected_compensation
    )
    assert matching["linear_multiplier"] == pytest.approx(2**expected_compensation)
    assert matching["dynamic_range_percent"] == dynamic_range


def test_manual_dr400_uses_development_dynamic_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = {
        "IFD0:ModifyDate": "2026:08:29 12:00:00",
        "ExifIFD:ExposureTime": 0.003125,
        "ExifIFD:FNumber": 4,
        "ExifIFD:ExposureProgram": 1,
        "ExifIFD:ISO": 320,
        "ExifIFD:SensitivityType": 1,
        "ExifIFD:StandardOutputSensitivity": 320,
        "ExifIFD:DateTimeOriginal": "2026:08:29 12:00:00",
        "ExifIFD:ExposureCompensation": -1,
        "ExifIFD:MaxApertureValue": 4,
        "ExifIFD:MeteringMode": 5,
        "ExifIFD:Flash": 0,
        "ExifIFD:FocalLength": 35,
        "ExifIFD:ColorSpace": 1,
        "RAF:RawExposureBias": -2.49,
        "FujiFilm:DynamicRangeSetting": 1,
        "FujiFilm:DevelopmentDynamicRange": 400,
    }

    class Completed:
        stdout = json.dumps([row])

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Completed())
    result = read_fuji_capture_metadata(Path("source.RAF"), "exiftool")
    assert result["exposure_matching"]["dynamic_range_percent"] == 400
    assert result["exposure_matching"]["recommended_phocus_compensation_ev"] == 2.49
    assert result["rendering_intent"]["dynamic_range"]["source"] == (
        "FujiFilm:DevelopmentDynamicRange"
    )


def test_effective_capture_iso_uses_standard_output_sensitivity_for_extended_iso() -> None:
    assert effective_capture_iso(
        {
            "ExifIFD:ISO": 65535,
            "ExifIFD:SensitivityType": 1,
            "ExifIFD:StandardOutputSensitivity": 102400,
        }
    ) == (102400, 65535, "ExifIFD:StandardOutputSensitivity")
    assert effective_capture_iso({"ExifIFD:ISO": 320}) == (
        320,
        320,
        "ExifIFD:ISO",
    )


def test_encode_unsigned_rationals_round_trips() -> None:
    import struct

    raw = encode_unsigned_rationals([302 / 575, 1.0, 302 / 488], "<")
    values = struct.unpack("<IIIIII", raw)
    decoded = [values[index] / values[index + 1] for index in range(0, 6, 2)]
    assert np.allclose(decoded, [302 / 575, 1.0, 302 / 488], rtol=0, atol=1e-9)


def test_encode_tiff_values_respects_fixed_ascii_and_signed_rational_slots() -> None:
    ascii_entry = IfdEntry(42036, 2, 8, b"\0" * 4, 100)
    assert encode_tiff_values(ascii_entry, "35mm F4", "<") == b"35mm F4\0"
    rational_entry = IfdEntry(37380, 10, 1, b"\0" * 4, 120)
    numerator, denominator = struct.unpack(
        "<ii", encode_tiff_values(rational_entry, -0.67, "<")
    )
    assert (numerator, denominator) == (-67, 100)


def test_inline_tiff_value_location_points_inside_ifd_entry() -> None:
    entry = IfdEntry(34855, 3, 1, b"@\0\0\0", 200)
    reader = object.__new__(TiffReader)
    assert reader.value_location(entry) == (208, 2)


def test_neutralize_hasselblad_lens_dispatch_changes_only_tag_word(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "sample.3FR"
    payload = write_synthetic_hasselblad_makernote(sample)
    before = sample.read_bytes()

    patch = neutralize_hasselblad_lens_correction(sample)

    after = sample.read_bytes()
    assert patch["range"] == [66, 68]
    assert patch["payload_range"] == [96, 113]
    assert before[:66] + before[68:] == after[:66] + after[68:]
    assert after[66:68] == struct.pack("<H", 0xFF18)
    assert after[96:113] == payload
    entry_offset, type_id, count, size, digest = hasselblad_makernote_tag_info(
        sample, 0xFF18
    )
    assert (entry_offset, type_id, count, size) == (66, 7, 17, 17)
    assert digest == patch["payload_sha256"]


def test_neutralize_hasselblad_lens_dispatch_fails_closed_on_unknown_layout(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "unknown.3FR"
    write_synthetic_hasselblad_makernote(sample, lens_tag_count=16)
    before = sample.read_bytes()

    with pytest.raises(ValueError, match="unsupported Hasselblad lens-dispatch layout"):
        neutralize_hasselblad_lens_correction(sample)

    assert sample.read_bytes() == before


def test_inverse_x2d_calibration_precompensates_red_and_blue() -> None:
    source = np.full((4, 4), 50, dtype=np.uint16)
    target = np.zeros((4, 4), dtype=np.uint16)
    source_meta = {
        "crop_x": 0,
        "crop_y": 0,
        "crop_width": 4,
        "crop_height": 4,
        "black_levels": [0, 0, 0, 0],
        "black_width": 2,
        "black_height": 2,
        "white_level": 100,
    }
    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=4, height=4,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=32,
        preview_offset=0, preview_byte_count=0, crop_origin=(0, 0), crop_size=(4, 4),
        black_level=10, white_level=110, file_size=32,
    )
    gains = {"R": 131072, "G1": 65536, "G2": 65536, "B": 131072}
    map_crop(source, target, source_meta, layout, gains)
    assert np.all(target[0::2, 0::2] == 35)
    assert np.all(target[1::2, 1::2] == 35)
    assert np.all(target[0::2, 1::2] == 60)
    assert np.all(target[1::2, 0::2] == 60)


def test_x2d_q16_profile_is_selected_by_donor_cohort_and_software() -> None:
    from raf2hncs.transplant import x2d_q16_profile

    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=4, height=4,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=32,
        preview_offset=0, preview_byte_count=0, crop_origin=(0, 0), crop_size=(4, 4),
        black_level=10, white_level=110, file_size=32, software="1.0.0",
        raw_data_unique_id="0140784A00002086",
    )
    cohort, profile = x2d_q16_profile(layout)
    assert cohort == "0140784A"
    assert profile["q16_gains"] == {
        "R": 65536, "G1": 65708, "G2": 65708, "B": 67192
    }


def test_x2d_q16_profile_rejects_unknown_or_mismatched_donor() -> None:
    import dataclasses

    import pytest

    from raf2hncs.transplant import x2d_q16_profile

    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=4, height=4,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=32,
        preview_offset=0, preview_byte_count=0, crop_origin=(0, 0), crop_size=(4, 4),
        black_level=10, white_level=110, file_size=32, software="1.0.0",
        raw_data_unique_id="UNKNOWN000002086",
    )
    with pytest.raises(ValueError, match="unavailable"):
        x2d_q16_profile(layout)
    with pytest.raises(ValueError, match="Software tag"):
        x2d_q16_profile(dataclasses.replace(layout, raw_data_unique_id="0140784A00002086", software="1.1.0"))


def test_x2d_q16_code_profiles_match_calibration_artifact() -> None:
    from raf2hncs.transplant import X2D_100C_OBSERVED_Q16_PROFILES

    artifact = json.loads(
        (Path(__file__).parents[1] / "calibration/x2d100c/Q16_CALIBRATION.json").read_text()
    )
    for cohort, profile in X2D_100C_OBSERVED_Q16_PROFILES.items():
        assert artifact["profiles"][cohort]["software"] == profile["software"]
        assert artifact["profiles"][cohort]["q16_gains"] == profile["q16_gains"]


def test_fuji_grb_white_balance_levels_become_rgb_coefficients() -> None:
    levels, coefficients = wb_coefficients_from_grb_levels("302 598 516")
    assert levels == [302, 598, 516]
    assert np.allclose(coefficients, [598 / 302, 1.0, 516 / 302])


def test_active_lattice_maps_one_to_one_and_preserves_target_margins() -> None:
    source = np.arange(12 * 12, dtype=np.uint16).reshape(12, 12)
    target = np.full((14, 16), 999, dtype=np.uint16)
    source_meta = {
        "active_x": 0,
        "active_y": 0,
        "active_width": 12,
        "active_height": 12,
        "black_levels": [0, 0, 0, 0],
        "black_width": 2,
        "black_height": 2,
        "white_level": 143,
    }
    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=16, height=14,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=448,
        preview_offset=0, preview_byte_count=0, crop_origin=(6, 4), crop_size=(4, 4),
        black_level=10, white_level=153, file_size=448,
    )
    mapping = map_active_lattice(source, target, source_meta, layout)
    assert mapping["mode"] == "active_lattice_1_to_1"
    assert mapping["target_origin"] == [2, 0]
    assert np.array_equal(target[:12, 2:14], source + 10)
    assert np.all(target[:, :2] == 999)
    assert np.all(target[:, 14:] == 999)
    assert np.all(target[12:, :] == 999)


def test_identity_sensor_matrix_preserves_uniform_rgb_mosaic() -> None:
    source = np.full((6, 6), 50, dtype=np.uint16)
    target = np.zeros((6, 6), dtype=np.uint16)
    source_meta = {
        "active_x": 0, "active_y": 0, "active_width": 6, "active_height": 6,
        "black_levels": [0, 0, 0, 0], "black_width": 2, "black_height": 2,
        "white_level": 100,
    }
    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=6, height=6,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=72,
        preview_offset=0, preview_byte_count=0, crop_origin=(4, 4), crop_size=(-2, -2),
        black_level=10, white_level=110, file_size=72,
    )
    mapping = map_active_lattice(source, target, source_meta, layout, sensor_matrix=np.eye(3))
    assert np.all(target == 60)
    assert mapping["sensor_transform_clipping"] == {
        "below_black": 0, "above_white": 0, "total": 36
    }


def test_mosaic_sensor_matrix_uses_only_cross_channel_neighbours() -> None:
    source = np.zeros((6, 6), dtype=np.uint16)
    source[0::2, 0::2] = 20
    source[0::2, 1::2] = 40
    source[1::2, 0::2] = 40
    source[1::2, 1::2] = 60
    target = np.zeros((6, 6), dtype=np.uint16)
    source_meta = {
        "active_x": 0, "active_y": 0, "active_width": 6, "active_height": 6,
        "black_levels": [0, 0, 0, 0], "black_width": 2, "black_height": 2,
        "white_level": 100,
    }
    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=6, height=6,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=72,
        preview_offset=0, preview_byte_count=0, crop_origin=(4, 4), crop_size=(-2, -2),
        black_level=0, white_level=100, file_size=72,
    )
    matrix = np.asarray([[1, .5, .25], [.5, 1, .25], [.5, .25, 1]], dtype=float)
    map_active_lattice(source, target, source_meta, layout, sensor_matrix=matrix)
    assert np.all(target[0::2, 0::2] == 55)
    assert np.all(target[0::2, 1::2] == 65)
    assert np.all(target[1::2, 0::2] == 65)
    assert np.all(target[1::2, 1::2] == 80)


def test_sensor_mapping_transforms_white_balance_neutral_consistently() -> None:
    source_gains = [1.98, 1.0, 1.7]
    target_gains = transform_wb_coefficients(
        source_gains, GFX100RF_TO_X2D100C_D65_BOOTSTRAP
    )
    source_neutral = 1.0 / np.asarray(source_gains)
    expected = GFX100RF_TO_X2D100C_D65_BOOTSTRAP @ source_neutral
    expected /= expected[1]
    actual = 1.0 / np.asarray(target_gains)
    assert np.allclose(actual, expected)


def test_adaptive_sensor_mapping_recovers_a_and_d65_endpoints() -> None:
    cases = (
        (GFX100RF_A_COLOR_MATRIX, [1.0985, 1.0, 0.35585], 2856.0, 1.0),
        (GFX100RF_D65_COLOR_MATRIX, [0.95047, 1.0, 1.08883], 6504.0, 0.0),
    )
    for source_matrix, xyz_white, expected_cct, expected_a_weight in cases:
        source_neutral = source_matrix @ np.asarray(xyz_white)
        source_neutral /= source_neutral[1]
        source_gains = (1.0 / source_neutral).tolist()
        mapping, evidence = adaptive_sensor_mapping(source_gains)
        interpolated, weight_a = gfx100rf_matrix_for_cct(
            float(evidence["estimated_cct_kelvin"])
        )
        assert abs(float(evidence["estimated_cct_kelvin"]) - expected_cct) < 2
        assert abs(weight_a - expected_a_weight) < 0.001
        assert np.allclose(interpolated, evidence["gfx100rf_xyz_to_camera"])
        assert np.allclose(mapping, np.diag(np.diag(mapping)))
        assert np.min(np.diag(mapping)) > 0


def test_adaptive_mapping_transforms_selected_neutral_in_same_domain() -> None:
    source_gains = [1.374172, 1.0, 3.480132]
    mapping, evidence = adaptive_sensor_mapping(source_gains)
    target_gains = transform_wb_coefficients(source_gains, mapping)
    assert 3200 < float(evidence["estimated_cct_kelvin"]) < 3250
    assert evidence["operator"] == "positive_white_point_diagonal"
    assert np.allclose(1.0 / np.asarray(target_gains), evidence["target_neutral"])


def test_versioned_adaptive_profile_matches_implementation() -> None:
    profile_path = (
        Path(__file__).parents[1]
        / "calibration/sensor/GFX100RF_TO_X2D100C_WB_ADAPTIVE_BOOTSTRAP.json"
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["status"] == "experimental_bootstrap_not_paired_camera_calibrated"
    assert np.allclose(profile["gfx100rf_a_xyz_to_camera"], GFX100RF_A_COLOR_MATRIX)
    assert np.allclose(profile["gfx100rf_d65_xyz_to_camera"], GFX100RF_D65_COLOR_MATRIX)
    assert np.allclose(profile["x2d100c_d65_xyz_to_camera"], X2D100C_D65_COLOR_MATRIX)


def test_versioned_d65_profile_matches_implementation() -> None:
    profile_path = (
        Path(__file__).parents[1]
        / "calibration/sensor/GFX100RF_TO_X2D100C_D65_BOOTSTRAP.json"
    )
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["status"] == "experimental_bootstrap_not_camera_calibrated"
    assert np.allclose(
        profile["gfx100rf_to_x2d100c"],
        GFX100RF_TO_X2D100C_D65_BOOTSTRAP,
        rtol=0,
        atol=5e-13,
    )
    computed = X2D100C_D65_COLOR_MATRIX @ np.linalg.inv(GFX100RF_D65_COLOR_MATRIX)
    assert np.allclose(computed, GFX100RF_TO_X2D100C_D65_BOOTSTRAP, rtol=0, atol=1e-15)


def test_active_lattice_maps_per_channel_black_without_unsigned_wrap() -> None:
    black_pattern = np.asarray([[10, 11], [12, 13]], dtype=np.uint16)
    source = np.tile(black_pattern, (3, 3))
    source[0, 0] = 0  # An extreme sub-black code must clamp at container zero.
    target = np.zeros((6, 6), dtype=np.uint16)
    source_meta = {
        "active_x": 0,
        "active_y": 0,
        "active_width": 6,
        "active_height": 6,
        "black_levels": [10, 11, 12, 13],
        "black_width": 2,
        "black_height": 2,
        "white_level": 110,
    }
    layout = X2DLayout(
        byte_order="little",
        make="Hasselblad",
        model="X2D 100C",
        width=6,
        height=6,
        bits_per_sample=16,
        compression=1,
        strip_offset=0,
        strip_byte_count=72,
        preview_offset=0,
        preview_byte_count=0,
        crop_origin=(4, 4),
        crop_size=(-2, -2),
        black_level=4096,
        white_level=65535,
        file_size=72,
    )
    mapping = map_active_lattice(source, target, source_meta, layout)
    assert target[0, 0] == 0
    assert np.all(target[target != 0] == 4096)
    assert mapping["black_noise_mapping"] == {
        "policy": "preserve_signed_source_residual",
        "preserved_below_black": 0,
        "clipped_below_code_zero": 1,
    }


def test_active_lattice_preserves_realistic_sub_black_noise() -> None:
    black_pattern = np.asarray([[4090, 4091], [4092, 4093]], dtype=np.uint16)
    source = np.tile(black_pattern - 1, (3, 3))
    source_meta = {
        "active_x": 0,
        "active_y": 0,
        "active_width": 6,
        "active_height": 6,
        "black_levels": black_pattern.ravel().tolist(),
        "black_width": 2,
        "black_height": 2,
        "white_level": 65535,
    }
    layout = X2DLayout(
        byte_order="little",
        make="Hasselblad",
        model="X2D 100C",
        width=6,
        height=6,
        bits_per_sample=16,
        compression=1,
        strip_offset=0,
        strip_byte_count=72,
        preview_offset=0,
        preview_byte_count=0,
        crop_origin=(4, 4),
        crop_size=(-2, -2),
        black_level=4096,
        white_level=65535,
        file_size=72,
    )
    for sensor_matrix in (None, np.eye(3)):
        target = np.zeros((6, 6), dtype=np.uint16)
        mapping = map_active_lattice(
            source, target, source_meta, layout, sensor_matrix=sensor_matrix
        )
        assert np.all(target == 4095)
        assert mapping["black_noise_mapping"]["preserved_below_black"] == 36
        assert mapping["sensor_transform_clipping"]["below_black"] == 0


def test_active_lattice_maps_source_white_exactly_without_overflow() -> None:
    source = np.full((6, 6), 110, dtype=np.uint16)
    target = np.zeros((6, 6), dtype=np.uint16)
    source_meta = {
        "active_x": 0,
        "active_y": 0,
        "active_width": 6,
        "active_height": 6,
        "black_levels": [10, 11, 12, 13],
        "black_width": 2,
        "black_height": 2,
        "white_level": 110,
    }
    layout = X2DLayout(
        byte_order="little",
        make="Hasselblad",
        model="X2D 100C",
        width=6,
        height=6,
        bits_per_sample=16,
        compression=1,
        strip_offset=0,
        strip_byte_count=72,
        preview_offset=0,
        preview_byte_count=0,
        crop_origin=(4, 4),
        crop_size=(-2, -2),
        black_level=4096,
        white_level=65535,
        file_size=72,
    )
    map_active_lattice(source, target, source_meta, layout)
    assert np.all(target == 65535)


def test_active_lattice_ramp_is_monotonic_with_exact_endpoints() -> None:
    row = np.asarray([0, 10, 20, 30, 40, 50, 60, 70], dtype=np.uint16)
    source = np.tile(row, (6, 1))
    target = np.zeros((6, 8), dtype=np.uint16)
    source_meta = {
        "active_x": 0,
        "active_y": 0,
        "active_width": 8,
        "active_height": 6,
        "black_levels": [0, 0, 0, 0],
        "black_width": 2,
        "black_height": 2,
        "white_level": 70,
    }
    layout = X2DLayout(
        byte_order="little",
        make="Hasselblad",
        model="X2D 100C",
        width=8,
        height=6,
        bits_per_sample=16,
        compression=1,
        strip_offset=0,
        strip_byte_count=96,
        preview_offset=0,
        preview_byte_count=0,
        crop_origin=(4, 4),
        crop_size=(0, -2),
        black_level=10,
        white_level=110,
        file_size=96,
    )
    map_active_lattice(source, target, source_meta, layout)
    assert target[0, 0] == 10
    assert target[0, -1] == 110
    assert np.all(np.diff(target.astype(np.int32), axis=1) >= 0)


def test_publish_no_overwrite_is_atomic_and_refuses_existing_destination(tmp_path: Path) -> None:
    temporary = tmp_path / "candidate.partial"
    destination = tmp_path / "candidate.3FR"
    temporary.write_bytes(b"candidate")
    publish_no_overwrite(temporary, destination)
    assert destination.read_bytes() == b"candidate"
    assert not temporary.exists()

    second = tmp_path / "second.partial"
    second.write_bytes(b"other")
    with np.testing.assert_raises(FileExistsError):
        publish_no_overwrite(second, destination)
    assert destination.read_bytes() == b"candidate"
    assert second.read_bytes() == b"other"


def test_write_json_temporary_fsyncs_and_refuses_collision(tmp_path: Path) -> None:
    temporary = tmp_path / "manifest.partial"
    write_json_temporary(temporary, {"answer": 42})
    assert json.loads(temporary.read_text(encoding="utf-8")) == {"answer": 42}
    with np.testing.assert_raises(FileExistsError):
        write_json_temporary(temporary, {"answer": 0})
    assert json.loads(temporary.read_text(encoding="utf-8")) == {"answer": 42}


def test_preview_patch_replaces_entire_fixed_slot_and_zero_pads(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.3FR"
    candidate.write_bytes(b"header" + b"donor-preview")
    layout = X2DLayout(
        byte_order="little", make="Hasselblad", model="X2D 100C", width=1, height=1,
        bits_per_sample=16, compression=1, strip_offset=0, strip_byte_count=2,
        preview_offset=6, preview_byte_count=13, crop_origin=(0, 0), crop_size=(1, 1),
        black_level=0, white_level=65535, file_size=19,
    )
    evidence = patch_preview_slot(candidate, layout, b"\xff\xd8x\xff\xd9")
    assert candidate.read_bytes() == b"header\xff\xd8x\xff\xd9" + b"\0" * 8
    assert evidence["range"] == [6, 19]
    assert evidence["jpeg_bytes"] == 5
    assert evidence["padding_bytes"] == 8


def test_find_tool_uses_explicit_runtime_directory(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "dnglab"
    executable.write_bytes(b"tool")
    monkeypatch.setenv("RAF2HNCS_TOOL_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "")
    assert find_tool(None, "dnglab") == str(executable)
