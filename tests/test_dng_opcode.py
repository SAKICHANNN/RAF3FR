from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from raf2hncs.dng_opcode import OPCODE_LIST_3
from raf2hncs.dng_opcode import append_raw_opcode_list
from raf2hncs.dng_opcode import fuji_lens_opcode_list
from raf2hncs.dng_opcode import fuji_warp_rectilinear_opcode
from raf2hncs.dng_opcode import opcode_list
from raf2hncs.tiff import TiffReader


def _write_tiff_with_raw_subifd(path: Path) -> None:
    data = bytearray(160)
    data[:8] = b"II" + struct.pack("<HI", 42, 8)
    data[8:26] = (
        struct.pack("<H", 1)
        + struct.pack("<HHII", 330, 4, 1, 64)
        + struct.pack("<I", 0)
    )
    data[64:82] = (
        struct.pack("<H", 1)
        + struct.pack("<HHII", 256, 4, 1, 11648)
        + struct.pack("<I", 0)
    )
    path.write_bytes(data)


def _decoded_profile() -> dict[str, object]:
    return {
        "knots": np.linspace(0.2, 1.0, 9).tolist(),
        "distortion_percent": np.linspace(-0.5, -9.0, 9).tolist(),
        "ca_red_scale_offset": np.linspace(0.0, 0.0003, 9).tolist(),
        "ca_blue_scale_offset": np.linspace(0.0, -0.0002, 9).tolist(),
        "vignetting_percent": [50.0] * 9,
    }


def _gfx100rf_profile() -> dict[str, object]:
    return {
        "crop_mode": 0,
        "knots": [
            0.3535648995,
            0.5001828154,
            0.6124314442,
            0.7071297989,
            0.7904936015,
            0.8661791590,
            0.9352833638,
            1.0,
            1.0606946980,
        ],
        "distortion_percent": [
            -1.114685059,
            -2.335388184,
            -3.556091309,
            -4.736648560,
            -5.899520874,
            -7.022247314,
            -8.116058350,
            -9.171325684,
            -10.098098750,
        ],
        "ca_red_scale_offset": [0.0] * 9,
        "ca_blue_scale_offset": [0.0] * 9,
        "vignetting_percent": [50.0] * 9,
    }


def test_fuji_warp_opcode_is_big_endian_three_plane_and_excludes_vignetting() -> None:
    opcode, report = fuji_warp_rectilinear_opcode(_decoded_profile())

    opcode_id, version, flags, parameter_size = struct.unpack(">4I", opcode[:16])
    assert (opcode_id, version, flags) == (1, 0x01030000, 0)
    assert parameter_size == len(opcode) - 16
    assert struct.unpack(">I", opcode[16:20])[0] == 3
    assert report["planes"] == ["R", "G", "B"]
    assert report["vignetting_strength"] == 0.0
    assert report["coefficients"][0] != report["coefficients"][2]
    assert report["framing"]["policy"] == "maximum_in_bounds_rectilinear_frame"
    assert report["framing"]["uniform_scale"] > 1.0
    for base, framed in zip(report["base_coefficients"], report["coefficients"]):
        assert base[0] == 1.0
        assert framed[0] == report["framing"]["uniform_scale"]


def test_fuji_warp_framing_maximizes_view_without_sampling_outside() -> None:
    _, report = fuji_warp_rectilinear_opcode(
        _decoded_profile(), image_width=11664, image_height=8750
    )
    half_width = 11664 / 2
    half_height = 8750 / 2
    diagonal = np.hypot(half_width, half_height)
    edge_x = half_width / diagonal
    edge_y = half_height / diagonal
    horizontal = np.linspace(0.0, edge_x, 8193)
    vertical = np.linspace(0.0, edge_y, 8193)
    boundaries = (np.hypot(horizontal, edge_y), np.hypot(edge_x, vertical))
    maximum_boundary_scale = 0.0
    for coefficients in report["coefficients"]:
        kr0, kr1, kr2, kr3 = coefficients
        for radius in boundaries:
            radius2 = radius * radius
            scale = kr0 + kr1 * radius2 + kr2 * radius2**2 + kr3 * radius2**3
            maximum_boundary_scale = max(maximum_boundary_scale, float(scale.max()))
            assert float(scale.max()) <= 1.0 + 1e-12
    assert maximum_boundary_scale > 1.0 - 1e-8


def test_gfx100rf_profile_uses_held_out_vendor_geometry_calibration() -> None:
    opcode, report = fuji_warp_rectilinear_opcode(_gfx100rf_profile())
    assert report["framing"]["policy"] == "gfx100rf_native_vendor_render_match_v1"
    assert np.allclose(
        report["coefficients"][1],
        [
            1.029268747742375,
            -0.04267719544928282,
            -0.13848667506081908,
            0.10394817611116454,
        ],
        rtol=0.0,
        atol=2e-12,
    )
    assert np.allclose(
        report["center"], [0.500092050670, 0.499039419533], rtol=0.0, atol=1e-15
    )
    assert struct.unpack(">2d", opcode[-16:]) == tuple(report["center"])

    _, legacy = fuji_warp_rectilinear_opcode(
        _gfx100rf_profile(), distortion_model="legacy-in-bounds"
    )
    assert legacy["distortion_model"] == "legacy-in-bounds"
    assert legacy["framing"]["policy"] == "maximum_in_bounds_rectilinear_frame"
    assert np.isclose(
        legacy["framing"]["uniform_scale"], 1.0331706566178662, rtol=0.0, atol=1e-12
    )
    assert legacy["center"] == [0.5, 0.5]

    _, identity = fuji_warp_rectilinear_opcode(
        _gfx100rf_profile(), distortion_strength=0.0, chromatic_aberration_strength=1.0
    )
    assert identity["center"] == [0.5, 0.5]

    radius = np.linspace(0.0, 1.0, 4097)
    for strength in np.linspace(-2.0, 2.0, 17):
        _, varied = fuji_warp_rectilinear_opcode(
            _gfx100rf_profile(),
            distortion_strength=float(strength),
            chromatic_aberration_strength=1.0,
        )
        for kr0, kr1, kr2, kr3 in varied["coefficients"]:
            derivative = (
                kr0
                + 3.0 * kr1 * radius**2
                + 5.0 * kr2 * radius**4
                + 7.0 * kr3 * radius**6
            )
            assert float(np.min(derivative)) > 0.0


def test_combined_profile_defaults_to_warp_without_vignetting() -> None:
    payload, report = fuji_lens_opcode_list(_decoded_profile())
    assert payload is not None
    assert struct.unpack(">I", payload[:4])[0] == 1
    assert [item["opcode"] for item in report["opcodes"]] == ["WarpRectilinear"]
    assert report["strengths"] == {
        "distortion": 1.0,
        "lateral_chromatic_aberration": 1.0,
        "vignetting": 0.0,
    }


def test_combined_profile_can_add_vignetting_or_disable_everything() -> None:
    payload, report = fuji_lens_opcode_list(_decoded_profile(), vignetting_strength=1.0)
    assert payload is not None
    assert struct.unpack(">I", payload[:4])[0] == 2
    assert [item["opcode"] for item in report["opcodes"]] == [
        "WarpRectilinear",
        "FixVignetteRadial",
    ]
    disabled, disabled_report = fuji_lens_opcode_list(
        _decoded_profile(),
        distortion_strength=0.0,
        chromatic_aberration_strength=0.0,
        vignetting_strength=0.0,
    )
    assert disabled is None
    assert disabled_report["mode"] == "none"


def test_combined_profile_accepts_signed_strengths_and_rejects_outside_range() -> None:
    payload, report = fuji_lens_opcode_list(
        _decoded_profile(),
        distortion_strength=-1.0,
        chromatic_aberration_strength=-2.0,
        vignetting_strength=-1.0,
    )
    assert payload is not None
    assert report["strengths"] == {
        "distortion": -1.0,
        "lateral_chromatic_aberration": -2.0,
        "vignetting": -1.0,
    }
    for value in (-2.01, 2.01):
        try:
            fuji_lens_opcode_list(_decoded_profile(), distortion_strength=value)
        except ValueError as error:
            assert "between -2 and 2" in str(error)
        else:
            raise AssertionError(f"out-of-range signed strength {value} was accepted")


def test_append_opcode_list_preserves_original_bytes_except_subifd_pointer(
    tmp_path: Path,
) -> None:
    sample = tmp_path / "candidate.3FR"
    _write_tiff_with_raw_subifd(sample)
    before = sample.read_bytes()
    opcode, _ = fuji_warp_rectilinear_opcode(_decoded_profile())
    payload = opcode_list(opcode)

    patch = append_raw_opcode_list(sample, payload)

    after = sample.read_bytes()
    pointer_start, pointer_end = patch["pointer_range"]
    assert before[:pointer_start] == after[:pointer_start]
    assert before[pointer_end:] == after[pointer_end : len(before)]
    assert patch["append_range"][0] == len(before)
    with TiffReader(sample) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        raw = reader.ifd(int(reader.required(ifd0, 330)[0]))
        assert reader.required(raw, 256) == [11648]
        assert OPCODE_LIST_3 in raw
        offset, size = reader.value_location(raw[OPCODE_LIST_3])
        reader.handle.seek(offset)
        assert reader.handle.read(size) == payload


def test_append_opcode_list_refuses_to_replace_existing_tag(tmp_path: Path) -> None:
    sample = tmp_path / "candidate.3FR"
    _write_tiff_with_raw_subifd(sample)
    payload = opcode_list(fuji_warp_rectilinear_opcode(_decoded_profile())[0])
    append_raw_opcode_list(sample, payload)
    before = sample.read_bytes()

    try:
        append_raw_opcode_list(sample, payload)
    except ValueError as error:
        assert "already contains" in str(error)
    else:
        raise AssertionError("duplicate OpcodeList3 was accepted")
    assert sample.read_bytes() == before
