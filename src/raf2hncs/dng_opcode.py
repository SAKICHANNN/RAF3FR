from __future__ import annotations

import hashlib
import math
import os
import struct
from pathlib import Path

import numpy as np

from .lens import _profile_splines
from .tiff import TiffReader


OPCODE_LIST_3 = 51022
WARP_RECTILINEAR = 1
FIX_VIGNETTE_RADIAL = 3
_DNG_1_3 = 0x01030000

_GFX100RF_KNOTS = np.asarray(
    [
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
    dtype=np.float64,
)
_GFX100RF_DISTORTION = np.asarray(
    [
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
    dtype=np.float64,
)
_GFX100RF_VENDOR_GREEN = np.asarray(
    [
        1.029268747742375,
        -0.04267719544928282,
        -0.13848667506081908,
        0.10394817611116454,
    ],
    dtype=np.float64,
)
_GFX100RF_CAMERA_JPEG_GREEN = np.asarray(
    [
        1.0342072867488865,
        -0.09747928869977876,
        -0.0009676148258258296,
        0.007647450440475954,
    ],
    dtype=np.float64,
)
_GFX100RF_CAMERA_JPEG_TANGENTIAL = (-0.000006957220381847184, -0.000015691195800021954)
_GFX100RF_NATIVE_CENTER = (0.500092050670, 0.499039419533)


def _is_gfx100rf_fixed_lens_profile(decoded: dict[str, object]) -> bool:
    knots = np.asarray(decoded.get("knots", []), dtype=np.float64)
    distortion = np.asarray(decoded.get("distortion_percent", []), dtype=np.float64)
    return (
        int(decoded.get("crop_mode", 0)) == 0
        and knots.shape == (9,)
        and distortion.shape == (9,)
        and np.allclose(knots, _GFX100RF_KNOTS, rtol=0.0, atol=5e-10)
        and np.allclose(distortion, _GFX100RF_DISTORTION, rtol=0.0, atol=5e-9)
    )


def _fit_radial_polynomial(
    destination_radius: np.ndarray, source_scale: np.ndarray
) -> tuple[tuple[float, float, float, float], float]:
    """Fit DNG's source-coordinate radial polynomial with an exact unit centre."""
    radius = np.asarray(destination_radius, dtype=np.float64)
    scale = np.asarray(source_scale, dtype=np.float64)
    if radius.shape != scale.shape or radius.ndim != 1 or radius.size < 8:
        raise ValueError("radial fit requires matching one-dimensional samples")
    if not np.all(np.isfinite(radius)) or not np.all(np.isfinite(scale)):
        raise ValueError("radial fit samples must be finite")

    # DNG WarpRectilinear maps output coordinates back to source coordinates:
    # source_radius = r * (1 + k1*r^2 + k2*r^4 + k3*r^6).
    design = np.stack((radius**3, radius**5, radius**7), axis=1)
    target = radius * (scale - 1.0)
    k1, k2, k3 = np.linalg.lstsq(design, target, rcond=None)[0]
    coefficients = (1.0, float(k1), float(k2), float(k3))
    fitted_scale = 1.0 + k1 * radius**2 + k2 * radius**4 + k3 * radius**6
    residual = float(np.max(np.abs(radius * (fitted_scale - scale))))

    probe = np.linspace(0.0, 1.0, 4097)
    derivative = 1.0 + 3.0 * k1 * probe**2 + 5.0 * k2 * probe**4 + 7.0 * k3 * probe**6
    if float(np.min(derivative)) <= 0.0:
        raise ValueError("fitted DNG warp is not invertible over the image radius")
    return coefficients, residual


def _radial_scale(
    coefficients: tuple[float, float, float, float], radius: np.ndarray
) -> np.ndarray:
    kr0, kr1, kr2, kr3 = coefficients
    radius2 = radius * radius
    return kr0 + kr1 * radius2 + kr2 * radius2**2 + kr3 * radius2**3


def _maximum_in_bounds_uniform_scale(
    coefficients: list[tuple[float, float, float, float]],
    *,
    image_width: int,
    image_height: int,
) -> float:
    """Return the largest common framing scale that keeps a radial warp in-bounds.

    DNG normalizes radius to the centre-to-corner distance.  Checking both
    positive rectangle edges is sufficient for a centred radial transform; a
    positive radial derivative then keeps every interior point on that ray
    inside the same boundary.
    """
    if image_width <= 0 or image_height <= 0:
        raise ValueError("invalid image geometry for DNG warp framing")
    half_width = 0.5 * float(image_width)
    half_height = 0.5 * float(image_height)
    diagonal = float(np.hypot(half_width, half_height))
    minimum_boundary_radius = min(half_width, half_height) / diagonal
    maximum_scale = np.inf
    for values in coefficients:
        _, kr1, kr2, kr3 = values
        candidates = [minimum_boundary_radius, 1.0]
        # The boundary scale is a cubic in u=r^2.  Add its real stationary
        # points so the maximum is exact rather than dependent on sampling.
        derivative = np.trim_zeros(
            np.asarray([3.0 * kr3, 2.0 * kr2, kr1], dtype=np.float64),
            trim="f",
        )
        roots = np.roots(derivative) if derivative.size > 1 else []
        for root in roots:
            if abs(float(np.imag(root))) <= 1e-12:
                radius2 = float(np.real(root))
                if minimum_boundary_radius**2 < radius2 < 1.0:
                    candidates.append(float(np.sqrt(radius2)))
        scales = _radial_scale(values, np.asarray(candidates, dtype=np.float64))
        if not np.all(np.isfinite(scales)) or float(np.min(scales)) <= 0.0:
            raise ValueError("fitted DNG warp has a non-positive boundary scale")
        maximum_scale = min(maximum_scale, 1.0 / float(np.max(scales)))
    if not np.isfinite(maximum_scale) or maximum_scale <= 0.0:
        raise ValueError("could not derive an in-bounds DNG warp framing scale")
    return float(maximum_scale)


def _validate_rectilinear_warp(
    coefficients: tuple[float, float, float, float, float, float],
    *,
    center: tuple[float, float],
    image_width: int,
    image_height: int,
) -> None:
    """Enforce the DNG radial, axis-monotonicity and 2-D invertibility gates."""
    kr0, kr1, kr2, kr3, kt0, kt1 = coefficients
    cx = center[0] * (image_width - 1)
    cy = center[1] * (image_height - 1)
    mx = max(cx, image_width - 1 - cx)
    my = max(cy, image_height - 1 - cy)
    normalizer = math.hypot(mx, my)
    x = (np.linspace(0.0, image_width - 1, 81) - cx) / normalizer
    y = (np.linspace(0.0, image_height - 1, 61) - cy) / normalizer
    dx, dy = np.meshgrid(x, y)
    radius2 = dx * dx + dy * dy
    radius4 = radius2 * radius2
    f = kr0 + kr1 * radius2 + kr2 * radius4 + kr3 * radius4 * radius2
    slope = kr1 + 2.0 * kr2 * radius2 + 3.0 * kr3 * radius4
    df_dx = 2.0 * dx * slope
    df_dy = 2.0 * dy * slope
    dfx_dx = f + dx * df_dx + 2.0 * kt0 * dy + 6.0 * kt1 * dx
    dfx_dy = dx * df_dy + 2.0 * kt0 * dx + 2.0 * kt1 * dy
    dfy_dx = dy * df_dx + 2.0 * kt1 * dy + 2.0 * kt0 * dx
    dfy_dy = f + dy * df_dy + 2.0 * kt1 * dx + 6.0 * kt0 * dy
    determinant = dfx_dx * dfy_dy - dfx_dy * dfy_dx
    radius = np.linspace(0.0, 1.0, 4097)
    radial_derivative = (
        kr0 + 3.0 * kr1 * radius**2 + 5.0 * kr2 * radius**4 + 7.0 * kr3 * radius**6
    )
    if (
        float(np.min(radial_derivative)) <= 0.0
        or float(np.min(dfx_dx)) <= 0.0
        or float(np.min(dfy_dy)) <= 0.0
        or float(np.min(determinant)) <= 0.0
    ):
        raise ValueError("calibrated DNG warp violates invertibility or axis monotonicity")


def fuji_warp_rectilinear_opcode(
    decoded: dict[str, object],
    *,
    distortion_model: str = "camera-jpeg",
    distortion_strength: float = 1.0,
    chromatic_aberration_strength: float = 1.0,
    image_width: int = 11664,
    image_height: int = 8750,
) -> tuple[bytes, dict[str, object]]:
    """Encode a Fuji per-image distortion/CA profile as DNG WarpRectilinear."""
    if distortion_model not in ("camera-jpeg", "native-match", "legacy-in-bounds"):
        raise ValueError(f"unsupported distortion model: {distortion_model}")
    splines = _profile_splines(
        decoded,
        sample_count=4096,
        distortion_strength=distortion_strength,
        chromatic_aberration_strength=chromatic_aberration_strength,
        vignetting_strength=0.0,
    )
    radius = np.asarray(splines["distortion_knots"], dtype=np.float64)
    fits = [
        _fit_radial_polynomial(radius, np.asarray(splines[name], dtype=np.float64))
        for name in ("red_scale", "green_scale", "blue_scale")
    ]
    base_coefficients = [fit[0] for fit in fits]
    center = (0.5, 0.5)
    if (
        distortion_model in ("camera-jpeg", "native-match")
        and _is_gfx100rf_fixed_lens_profile(decoded)
    ):
        reference = _profile_splines(
            decoded,
            sample_count=4096,
            distortion_strength=1.0,
            chromatic_aberration_strength=0.0,
            vignetting_strength=0.0,
        )
        reference_green = np.asarray(
            _fit_radial_polynomial(
                np.asarray(reference["distortion_knots"], dtype=np.float64),
                np.asarray(reference["green_scale"], dtype=np.float64),
            )[0],
            dtype=np.float64,
        )
        target_green = (
            _GFX100RF_CAMERA_JPEG_GREEN
            if distortion_model == "camera-jpeg"
            else _GFX100RF_VENDOR_GREEN
        )
        calibration_delta = target_green - reference_green
        tangential = (
            tuple(distortion_strength * value for value in _GFX100RF_CAMERA_JPEG_TANGENTIAL)
            if distortion_model == "camera-jpeg"
            else (0.0, 0.0)
        )
        coefficients = [
            tuple(
                float(value)
                for value in np.asarray(plane, dtype=np.float64)
                + distortion_strength * calibration_delta
            )
            + tangential
            for plane in base_coefficients
        ]
        center = tuple(
            0.5 + distortion_strength * (value - 0.5)
            for value in _GFX100RF_NATIVE_CENTER
        )
        framing = {
            "policy": (
                "gfx100rf_camera_jpeg_phocus_fit_experimental_v3"
                if distortion_model == "camera-jpeg"
                else "gfx100rf_native_vendor_render_match_v1"
            ),
            "calibration": (
                "calibration/gfx100rf/PHOCUS_GEOMETRY_FIT_EXPERIMENT_0_9_6.json"
                if distortion_model == "camera-jpeg"
                else "calibration/gfx100rf/NATIVE_DISTORTION_MATCH_0_9_4.json"
            ),
            "image_width": int(image_width),
            "image_height": int(image_height),
            "strength_interpolation": float(distortion_strength),
        }
    else:
        framing_scale = _maximum_in_bounds_uniform_scale(
            base_coefficients,
            image_width=image_width,
            image_height=image_height,
        )
        coefficients = [
            tuple(float(framing_scale * value) for value in plane) + (0.0, 0.0)
            for plane in base_coefficients
        ]
        framing = {
            "policy": "maximum_in_bounds_rectilinear_frame",
            "uniform_scale": framing_scale,
            "image_width": int(image_width),
            "image_height": int(image_height),
            "guarantee": "centred radial boundary remains within the source rectangle",
        }
    for values in coefficients:
        _validate_rectilinear_warp(
            values,
            center=center,
            image_width=image_width,
            image_height=image_height,
        )
    parameters = struct.pack(">I", 3)
    for values in coefficients:
        parameters += struct.pack(">6d", *values)
    parameters += struct.pack(">2d", *center)
    opcode = struct.pack(">4I", WARP_RECTILINEAR, _DNG_1_3, 0, len(parameters)) + parameters
    report = {
        "opcode": "WarpRectilinear",
        "opcode_id": WARP_RECTILINEAR,
        "dng_version": "1.3.0.0",
        "planes": ["R", "G", "B"],
        "coefficients": [list(values) for values in coefficients],
        "base_coefficients": [list(values) for values in base_coefficients],
        "maximum_normalized_coordinate_residual": max(fit[1] for fit in fits),
        "center": list(center),
        "distortion_model": distortion_model,
        "framing": framing,
        "distortion_strength": float(distortion_strength),
        "lateral_chromatic_aberration_strength": float(chromatic_aberration_strength),
        "vignetting_strength": 0.0,
    }
    return opcode, report


def fuji_fix_vignette_radial_opcode(
    decoded: dict[str, object],
    *,
    distortion_strength: float = 1.0,
    vignetting_strength: float = 1.0,
) -> tuple[bytes, dict[str, object]]:
    """Encode Fuji's shading table as DNG's radial vignetting correction."""
    splines = _profile_splines(
        decoded,
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
    gain = 1.0 / np.maximum(source_multiplier, 1e-6)
    design = np.stack(
        [destination_radius ** power for power in (2, 4, 6, 8, 10)], axis=1
    )
    coefficients = np.linalg.lstsq(design, gain - 1.0, rcond=None)[0]
    fitted = 1.0 + np.sum(design * coefficients[None, :], axis=1)
    if float(np.min(fitted)) <= 0.0:
        raise ValueError("fitted DNG vignetting gain is not positive")
    parameters = struct.pack(">7d", *coefficients, 0.5, 0.5)
    opcode = (
        struct.pack(
            ">4I", FIX_VIGNETTE_RADIAL, _DNG_1_3, 0, len(parameters)
        )
        + parameters
    )
    report = {
        "opcode": "FixVignetteRadial",
        "opcode_id": FIX_VIGNETTE_RADIAL,
        "dng_version": "1.3.0.0",
        "coefficients": coefficients.tolist(),
        "maximum_gain_residual": float(np.max(np.abs(fitted - gain))),
        "vignetting_strength": float(vignetting_strength),
    }
    return opcode, report


def fuji_lens_opcode_list(
    decoded: dict[str, object],
    *,
    distortion_model: str = "camera-jpeg",
    distortion_strength: float = 1.0,
    chromatic_aberration_strength: float = 1.0,
    vignetting_strength: float = 0.0,
    image_width: int = 11664,
    image_height: int = 8750,
) -> tuple[bytes | None, dict[str, object]]:
    """Build the selected in-RAW lens operations; defaults preserve vignetting."""
    strengths = {
        "distortion": float(distortion_strength),
        "lateral_chromatic_aberration": float(chromatic_aberration_strength),
        "vignetting": float(vignetting_strength),
    }
    if any(not np.isfinite(value) or not -2.0 <= value <= 2.0 for value in strengths.values()):
        raise ValueError("lens correction strengths must be between -2 and 2")
    opcodes: list[bytes] = []
    reports: list[dict[str, object]] = []
    if distortion_strength or chromatic_aberration_strength:
        encoded, report = fuji_warp_rectilinear_opcode(
            decoded,
            distortion_model=distortion_model,
            distortion_strength=distortion_strength,
            chromatic_aberration_strength=chromatic_aberration_strength,
            image_width=image_width,
            image_height=image_height,
        )
        opcodes.append(encoded)
        reports.append(report)
    if vignetting_strength:
        encoded, report = fuji_fix_vignette_radial_opcode(
            decoded,
            distortion_strength=distortion_strength,
            vignetting_strength=vignetting_strength,
        )
        opcodes.append(encoded)
        reports.append(report)
    return (
        opcode_list(*opcodes) if opcodes else None,
        {
            "mode": "embedded_dng_opcode_list_3" if opcodes else "none",
            "distortion_model": distortion_model,
            "strengths": strengths,
            "opcodes": reports,
            "default_policy": "correct distortion and lateral CA; preserve native vignetting",
        },
    )


def opcode_list(*opcodes: bytes) -> bytes:
    if not opcodes:
        raise ValueError("an opcode list must contain at least one opcode")
    return struct.pack(">I", len(opcodes)) + b"".join(opcodes)


def append_raw_opcode_list(
    path: Path, payload: bytes, *, tag: int = OPCODE_LIST_3
) -> dict[str, object]:
    """Append a replacement Raw IFD containing one DNG opcode-list tag.

    Existing image data and TIFF value slots remain in place. Only the IFD0
    SubIFDs pointer is changed; the replacement Raw IFD and opcode bytes are
    appended. This keeps the operation reversible and avoids relocating the RAW
    strip, preview, MakerNote, or any pre-existing metadata payload.
    """
    if tag not in (51008, 51009, 51022):
        raise ValueError("tag is not a DNG opcode-list tag")
    if len(payload) <= 4:
        raise ValueError("opcode-list payload is unexpectedly short")

    original_size = path.stat().st_size
    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        subifds = ifd0.get(330)
        if subifds is None or subifds.type_id != 4 or subifds.count != 1:
            raise ValueError("expected exactly one LONG SubIFDs pointer")
        raw_offset = int(reader.values(subifds)[0])
        raw_entries = reader.ifd(raw_offset)
        if tag in raw_entries:
            raise ValueError(f"Raw IFD already contains opcode-list tag {tag}")
        reader.handle.seek(raw_offset)
        entry_count = struct.unpack(reader.endian + "H", reader.handle.read(2))[0]
        original_entries = [reader.handle.read(12) for _ in range(entry_count)]
        if any(len(entry) != 12 for entry in original_entries):
            raise ValueError("truncated Raw IFD")
        next_ifd = reader.handle.read(4)
        if len(next_ifd) != 4:
            raise ValueError("truncated Raw IFD next pointer")
        pointer_offset, pointer_size = reader.value_location(subifds)
        if pointer_size != 4:
            raise AssertionError("SubIFDs pointer is not inline")
        endian = reader.endian

    payload_offset = original_size
    padding = b"\0" if (payload_offset + len(payload)) & 1 else b""
    replacement_ifd_offset = payload_offset + len(payload) + len(padding)
    if replacement_ifd_offset > 0xFFFFFFFF:
        raise ValueError("classic TIFF offset exceeds 32-bit range")
    new_entry = struct.pack(
        endian + "HHII", tag, 7, len(payload), payload_offset
    )
    all_entries = sorted(
        [*original_entries, new_entry],
        key=lambda raw: struct.unpack(endian + "H", raw[:2])[0],
    )
    replacement_ifd = (
        struct.pack(endian + "H", len(all_entries))
        + b"".join(all_entries)
        + next_ifd
    )

    with path.open("r+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() != original_size:
            raise RuntimeError("file size changed while preparing opcode append")
        handle.write(payload)
        handle.write(padding)
        handle.write(replacement_ifd)
        handle.flush()
        os.fsync(handle.fileno())
        handle.seek(pointer_offset)
        handle.write(struct.pack(endian + "I", replacement_ifd_offset))
        handle.flush()
        os.fsync(handle.fileno())

    with TiffReader(path) as reader:
        ifd0 = reader.ifd(reader.first_ifd)
        installed_offset = int(reader.required(ifd0, 330)[0])
        installed = reader.ifd(installed_offset)
        if installed_offset != replacement_ifd_offset or tag not in installed:
            raise RuntimeError("failed to install replacement Raw IFD")
        value_offset, value_size = reader.value_location(installed[tag])
        reader.handle.seek(value_offset)
        if value_size != len(payload) or reader.handle.read(value_size) != payload:
            raise RuntimeError("installed opcode-list payload differs")

    return {
        "tag": "OpcodeList3" if tag == OPCODE_LIST_3 else f"OpcodeList{tag}",
        "directory": "RawIFD",
        "tag_id": tag,
        "pointer_range": [pointer_offset, pointer_offset + 4],
        "old_subifd_offset": raw_offset,
        "new_subifd_offset": replacement_ifd_offset,
        "payload_range": [payload_offset, payload_offset + len(payload)],
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "append_range": [original_size, path.stat().st_size],
    }
