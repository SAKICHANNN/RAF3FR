from __future__ import annotations

import json
import os
import subprocess
import hashlib
from pathlib import Path

import numpy as np

from .hashing import sha256


def _numbers(value: str) -> list[float]:
    return [float(item) for item in value.split()]


def decode_fuji_lens_arrays(
    geometric: list[float], chromatic: list[float], vignetting: list[float], crop_mode: int
) -> dict[str, object]:
    if (len(geometric), len(chromatic), len(vignetting)) != (19, 29, 19):
        raise ValueError("expected modern Fuji 19/29/19 lens-correction arrays")
    knots = geometric[1:10]
    if chromatic[1:10] != knots or vignetting[1:10] != knots:
        raise ValueError("Fuji distortion, CA, and vignetting knots disagree")
    crop_factor = 1.25 if crop_mode in (2, 4) else 1.0
    return {
        "knot_count": 9,
        "crop_mode": crop_mode,
        "crop_factor": crop_factor,
        "knots": [crop_factor * value for value in knots],
        "distortion_percent": geometric[10:19],
        "ca_red_scale_offset": chromatic[10:19],
        "ca_blue_scale_offset": chromatic[19:28],
        "vignetting_percent": vignetting[10:19],
        "raw_sentinels": {
            "geometric_0": geometric[0],
            "chromatic_0": chromatic[0],
            "chromatic_28": chromatic[28],
            "vignetting_0": vignetting[0],
        },
        "reference_algorithm": {
            "source": "darktable src/common/exif.cc and src/iop/lens.cc",
            "distortion_radial_scale": "1 + distortion_percent / 100",
            "red_radial_scale": "distortion_radial_scale * (1 + ca_red_scale_offset)",
            "blue_radial_scale": "distortion_radial_scale * (1 + ca_blue_scale_offset)",
            "vignetting_source_multiplier": "vignetting_percent / 100",
            "note": "Apply optical correction after Phocus rendering; do not pre-warp the Bayer mosaic.",
        },
    }


def extract_fuji_lens_profile(source: Path, exiftool: str) -> dict[str, object]:
    result = subprocess.run(
        [
            exiftool,
            "-j",
            "-n",
            "-G1",
            "-Make",
            "-Model",
            "-LensMake",
            "-LensModel",
            "-MaxApertureValue",
            "-FocalLength",
            "-FocalLengthIn35mmFormat",
            "-FocalLength35efl",
            "-CropMode",
            "-GeometricDistortionParams",
            "-ChromaticAberrationParams",
            "-VignettingParams",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    row = json.loads(result.stdout)[0]
    decoded = decode_fuji_lens_arrays(
        _numbers(row["FujiIFD:GeometricDistortionParams"]),
        _numbers(row["FujiIFD:ChromaticAberrationParams"]),
        _numbers(row["FujiIFD:VignettingParams"]),
        int(row.get("FujiFilm:CropMode", 0)),
    )
    make = str(row.get("IFD0:Make", "FUJIFILM")).strip() or "FUJIFILM"
    model = str(row.get("IFD0:Model", "Unknown camera")).strip() or "Unknown camera"
    focal_length = float(row["ExifIFD:FocalLength"]) if "ExifIFD:FocalLength" in row else None
    maximum_aperture = (
        float(row["ExifIFD:MaxApertureValue"])
        if "ExifIFD:MaxApertureValue" in row
        else None
    )
    lens_make = str(row.get("ExifIFD:LensMake", make)).strip() or make
    lens_model = str(row.get("ExifIFD:LensModel", "")).strip()
    if not lens_model:
        focal_label = f"{focal_length:g}mm" if focal_length is not None else "Unknown focal length"
        aperture_label = f" F{maximum_aperture:g}" if maximum_aperture is not None else ""
        lens_model = f"{focal_label}{aperture_label} embedded profile"
    source_hash = sha256(source)
    profile_fingerprint = hashlib.sha256(
        json.dumps(decoded, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    output_metadata: dict[str, object] = {
        "make": make,
        "model": model,
        "lens_make": lens_make,
        "lens_model": lens_model,
    }
    if focal_length is not None:
        output_metadata["focal_length"] = focal_length
    focal_length_35mm = row.get(
        "ExifIFD:FocalLengthIn35mmFormat", row.get("Composite:FocalLength35efl")
    )
    if focal_length_35mm is not None:
        output_metadata["focal_length_35mm"] = round(float(focal_length_35mm))
    return {
        "schema_version": 2,
        "profile_id": f"fujiifd-{profile_fingerprint[:24]}",
        "profile_instance_id": f"source-{source_hash[:24]}",
        "source": {"path": str(source), "sha256": source_hash},
        "camera": {"make": make, "model": model},
        "lens": {
            "make": lens_make,
            "model": lens_model,
            "focal_length_mm": focal_length,
            "maximum_aperture": maximum_aperture,
        },
        "capabilities": {
            "distortion": True,
            "vignetting": True,
            "lateral_chromatic_aberration": True,
            "image_analysis_defringe": False,
        },
        "output_metadata": output_metadata,
        "profile_kind": "per-image embedded Fuji optical correction",
        "decoded": decoded,
        "claim_boundary": "Decoded profile candidate; correction quality remains subject to held-out image validation.",
    }


def _strength(value: float, name: str) -> float:
    value = float(value)
    if not np.isfinite(value) or not 0.0 <= value <= 2.0:
        raise ValueError(f"{name} strength must be between 0 and 2")
    return value


def _signed_lens_strength(value: float, name: str) -> float:
    value = float(value)
    if not np.isfinite(value) or not -2.0 <= value <= 2.0:
        raise ValueError(f"{name} strength must be between -2 and 2")
    return value


def _profile_splines(
    decoded: dict[str, object],
    sample_count: int = 64,
    *,
    distortion_strength: float = 1.0,
    chromatic_aberration_strength: float = 1.0,
    vignetting_strength: float = 1.0,
) -> dict[str, np.ndarray]:
    distortion_strength = _signed_lens_strength(distortion_strength, "distortion")
    chromatic_aberration_strength = _signed_lens_strength(
        chromatic_aberration_strength, "chromatic aberration"
    )
    vignetting_strength = _signed_lens_strength(vignetting_strength, "vignetting")
    knots = np.asarray(decoded["knots"], dtype=np.float64)
    distortion = np.asarray(decoded["distortion_percent"], dtype=np.float64)
    ca_red = np.asarray(decoded["ca_red_scale_offset"], dtype=np.float64)
    ca_blue = np.asarray(decoded["ca_blue_scale_offset"], dtype=np.float64)
    vignetting = np.asarray(decoded["vignetting_percent"], dtype=np.float64) / 100.0
    if any(values.shape != (9,) for values in (knots, distortion, ca_red, ca_blue, vignetting)):
        raise ValueError("expected nine Fuji lens-profile knots and values")
    if np.any(np.diff(knots) <= 0) or knots[0] <= 0:
        raise ValueError("Fuji lens-profile knots must be positive and strictly increasing")

    source_knots = np.concatenate(([0.0], knots))
    geometric_scale = np.concatenate(
        ([1.0], 1.0 + distortion_strength * distortion / 100.0)
    )
    red_offset = np.concatenate(([0.0], chromatic_aberration_strength * ca_red))
    blue_offset = np.concatenate(([0.0], chromatic_aberration_strength * ca_blue))
    if np.any(vignetting <= 0):
        raise ValueError("Fuji vignetting multipliers must be positive")
    # A signed exponent makes the two directions reciprocal: +1 removes one
    # measured profile falloff, while -1 adds that same falloff once.
    vignette_scale = np.concatenate(([1.0], np.power(vignetting, vignetting_strength)))

    source_radius = np.linspace(0.0, 1.0, sample_count, dtype=np.float64)
    scale = np.interp(source_radius, source_knots, geometric_scale)
    destination_knots = source_radius / scale
    return {
        "distortion_knots": destination_knots,
        "green_scale": scale,
        "red_scale": scale * (1.0 + np.interp(source_radius, source_knots, red_offset)),
        "blue_scale": scale * (1.0 + np.interp(source_radius, source_knots, blue_offset)),
        "vignette_knots": source_knots,
        "vignette_scale": vignette_scale,
    }


def fuji_lens_maps(
    decoded: dict[str, object],
    width: int,
    height: int,
    y_start: int,
    y_end: int,
    *,
    distortion_strength: float = 1.0,
    chromatic_aberration_strength: float = 1.0,
    vignetting_strength: float = 1.0,
) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], dict[str, np.ndarray]]:
    """Return darktable-v2-compatible output-to-source maps for one image stripe."""
    if width <= 0 or height <= 0 or not 0 <= y_start < y_end <= height:
        raise ValueError("invalid image or stripe geometry")
    splines = _profile_splines(
        decoded,
        distortion_strength=distortion_strength,
        chromatic_aberration_strength=chromatic_aberration_strength,
        vignetting_strength=vignetting_strength,
    )
    center_x = 0.5 * width
    center_y = 0.5 * height
    norm = float(np.hypot(center_x, center_y))
    x = np.arange(width, dtype=np.float32)[None, :] - center_x
    y = np.arange(y_start, y_end, dtype=np.float32)[:, None] - center_y
    destination_radius = np.hypot(x, y) / norm
    maps: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    vignette: dict[str, np.ndarray] = {}
    for name, scale_name in (("R", "red_scale"), ("G", "green_scale"), ("B", "blue_scale")):
        radial_scale = np.interp(
            destination_radius,
            splines["distortion_knots"],
            splines[scale_name],
        ).astype(np.float32)
        source_x = (radial_scale * x + center_x).astype(np.float32)
        source_y = (radial_scale * y + center_y).astype(np.float32)
        maps[name] = (source_x, source_y)
        source_radius = np.hypot(source_x - center_x, source_y - center_y) / norm
        vignette[name] = np.interp(
            source_radius,
            splines["vignette_knots"],
            splines["vignette_scale"],
        ).astype(np.float32)
    return maps, vignette


def _defringe_bgr(
    image: np.ndarray,
    *,
    strength: float,
    threshold: float,
    radius: float,
    input_gamma: float,
    stripe_rows: int,
) -> np.ndarray:
    """Reduce high-contrast purple/green fringes without claiming profile calibration."""
    strength = _strength(strength, "defringe")
    if strength == 0.0:
        return image
    if not np.isfinite(threshold) or not 0.0 <= threshold <= 0.5:
        raise ValueError("defringe threshold must be between 0 and 0.5")
    if not np.isfinite(radius) or not 0.5 <= radius <= 8.0:
        raise ValueError("defringe radius must be between 0.5 and 8")
    import cv2

    maximum = float(np.iinfo(image.dtype).max)
    result = image.copy()
    halo = max(2, int(np.ceil(radius * 3.0)))
    height = image.shape[0]
    for y_start in range(0, height, stripe_rows):
        y_end = min(height, y_start + stripe_rows)
        source_start = max(0, y_start - halo)
        source_end = min(height, y_end + halo)
        work = image[source_start:source_end].astype(np.float32) / maximum
        if input_gamma != 1.0:
            np.power(work, input_gamma, out=work)
        blue, green, red = cv2.split(work)
        luminance = 0.0722 * blue + 0.7152 * green + 0.2126 * red
        gradient_x = cv2.Sobel(luminance, cv2.CV_32F, 1, 0, ksize=3)
        gradient_y = cv2.Sobel(luminance, cv2.CV_32F, 0, 1, ksize=3)
        edge = np.clip(np.hypot(gradient_x, gradient_y) / 0.12, 0.0, 1.0)
        local_blue = cv2.GaussianBlur(blue, (0, 0), radius)
        local_green = cv2.GaussianBlur(green, (0, 0), radius)
        local_red = cv2.GaussianBlur(red, (0, 0), radius)
        purple = np.minimum(red - local_red, blue - local_blue) - (green - local_green)
        green_fringe = (green - local_green) - np.maximum(
            red - local_red, blue - local_blue
        )
        chroma = np.maximum(purple, green_fringe)
        mask = np.clip((chroma - threshold) / max(0.25 - threshold, 1e-3), 0.0, 1.0)
        alpha = np.clip(mask * edge * strength, 0.0, 1.0)
        work += alpha[:, :, None] * (luminance[:, :, None] - work)
        np.clip(work, 0.0, 1.0, out=work)
        if input_gamma != 1.0:
            np.power(work, 1.0 / input_gamma, out=work)
        inner_start = y_start - source_start
        inner_end = inner_start + (y_end - y_start)
        result[y_start:y_end] = np.clip(
            np.rint(work[inner_start:inner_end] * maximum), 0, maximum
        ).astype(image.dtype)
    return result


def apply_fuji_lens_correction(
    source: Path,
    profile_path: Path,
    output: Path,
    *,
    stripe_rows: int = 256,
    exiftool: str | None = None,
    input_gamma: float = 1.0,
    distortion_strength: float = 1.0,
    vignetting_strength: float = 1.0,
    chromatic_aberration_strength: float = 1.0,
    defringe_strength: float = 0.0,
    defringe_threshold: float = 0.04,
    defringe_radius: float = 1.5,
) -> dict[str, object]:
    """Apply the embedded Fuji profile after Phocus rendering, preserving RGB/bit depth."""
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if stripe_rows <= 0:
        raise ValueError("stripe_rows must be positive")
    if not np.isfinite(input_gamma) or input_gamma <= 0:
        raise ValueError("input_gamma must be positive")
    distortion_strength = _signed_lens_strength(distortion_strength, "distortion")
    vignetting_strength = _signed_lens_strength(vignetting_strength, "vignetting")
    chromatic_aberration_strength = _signed_lens_strength(
        chromatic_aberration_strength, "chromatic aberration"
    )
    defringe_strength = _strength(defringe_strength, "defringe")
    try:
        import cv2
    except ImportError as error:  # pragma: no cover - depends on local optional runtime
        raise RuntimeError("lens correction requires the optional opencv-python-headless package") from error

    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    if int(profile.get("schema_version", 1)) not in (1, 2):
        raise ValueError("unsupported lens-profile schema")
    decoded = profile["decoded"]
    image = cv2.imread(str(source), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"OpenCV could not decode {source}")
    if image.ndim != 3 or image.shape[2] != 3 or image.dtype not in (np.uint8, np.uint16):
        raise ValueError("lens correction requires an 8-bit or 16-bit three-channel image")
    height, width = image.shape[:2]
    corrected = np.empty_like(image)
    maximum = float(np.iinfo(image.dtype).max)
    # OpenCV stores colour images as BGR; profile names remain physical RGB.
    channel_indices = {"B": 0, "G": 1, "R": 2}
    for name, channel_index in channel_indices.items():
        linear_source = image[:, :, channel_index].astype(np.float32) / maximum
        if input_gamma != 1.0:
            np.power(linear_source, input_gamma, out=linear_source)
        for y_start in range(0, height, stripe_rows):
            y_end = min(height, y_start + stripe_rows)
            maps, vignette = fuji_lens_maps(
                decoded,
                width,
                height,
                y_start,
                y_end,
                distortion_strength=distortion_strength,
                chromatic_aberration_strength=chromatic_aberration_strength,
                vignetting_strength=vignetting_strength,
            )
            map_x, map_y = maps[name]
            remapped = cv2.remap(
                linear_source,
                map_x,
                map_y,
                interpolation=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_REPLICATE,
            )
            remapped /= np.maximum(vignette[name], 1e-4)
            np.clip(remapped, 0.0, 1.0, out=remapped)
            if input_gamma != 1.0:
                np.power(remapped, 1.0 / input_gamma, out=remapped)
            corrected[y_start:y_end, :, channel_index] = np.clip(
                np.rint(remapped * maximum), 0, maximum
            ).astype(image.dtype)

    corrected = _defringe_bgr(
        corrected,
        strength=defringe_strength,
        threshold=defringe_threshold,
        radius=defringe_radius,
        input_gamma=input_gamma,
        stripe_rows=stripe_rows,
    )

    partial = output.with_name(output.stem + ".partial" + output.suffix)
    if partial.exists():
        raise FileExistsError(f"remove stale temporary output first: {partial}")
    compression = [cv2.IMWRITE_TIFF_COMPRESSION, 1] if output.suffix.lower() in (".tif", ".tiff") else []
    if not cv2.imwrite(str(partial), corrected, compression):
        raise RuntimeError(f"OpenCV could not write {partial}")
    metadata_status = "NOT_COPIED"
    if exiftool:
        output_metadata = profile.get("output_metadata", {})
        image_unique_id = str(profile["source"]["sha256"])[:32].upper()
        metadata_arguments: list[str] = []
        metadata_tags = {
            "make": "Make",
            "model": "Model",
            "lens_make": "LensMake",
            "lens_model": "LensModel",
            "focal_length": "FocalLength",
            "focal_length_35mm": "FocalLengthIn35mmFormat",
        }
        for key, tag in metadata_tags.items():
            if key in output_metadata and output_metadata[key] is not None:
                metadata_arguments.append(f"-{tag}={output_metadata[key]}")
        subprocess.run(
            [
                exiftool,
                "-overwrite_original",
                "-TagsFromFile",
                str(source),
                "-all:all",
                "-icc_profile",
                *metadata_arguments,
                f"-ImageUniqueID={image_unique_id}",
                "-Software=raf2hncs 0.7.0; Phocus-rendered; profile lens-corrected",
                str(partial),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        metadata_status = "COPIED_WITH_EXIFTOOL"
    with partial.open("r+b") as handle:
        os.fsync(handle.fileno())
    partial.replace(output)
    manifest = {
        "schema_version": 1,
        "source": {"path": str(source), "sha256": sha256(source)},
        "profile": {"path": str(profile_path), "sha256": sha256(profile_path)},
        "output": {"path": str(output), "sha256": sha256(output)},
        "geometry": {"width": width, "height": height, "channels": "RGB", "bit_depth": image.dtype.itemsize * 8},
        "algorithm": {
            "reference": "darktable embedded-metadata algorithm v2",
            "interpolation": "OpenCV cubic stripe remap",
            "border": "replicate",
            "vignetting": "source-radius multiplier before-equivalent remap",
            "input_transfer_gamma": input_gamma,
            "metadata": metadata_status,
            "components": {
                "distortion_strength": distortion_strength,
                "vignetting_strength": vignetting_strength,
                "lateral_chromatic_aberration_strength": chromatic_aberration_strength,
                "defringe": {
                    "strength": defringe_strength,
                    "threshold": defringe_threshold,
                    "radius": defringe_radius,
                    "source": "image_analysis_not_lens_profile",
                },
            },
        },
        "claim_boundary": "Embedded-profile implementation candidate; held-out target validation is still required.",
    }
    manifest_path = output.with_suffix(output.suffix + ".json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest
