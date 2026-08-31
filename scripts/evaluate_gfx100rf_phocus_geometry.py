#!/usr/bin/env python3
"""Measure Phocus-rendered 3FR geometry against original camera JPEGs.

Only a central-region similarity transform (translation, rotation and uniform
scale) is allowed to reconcile the two image coordinate frames.  Every mutual
high-confidence match is then retained for full-frame evaluation; no
full-frame homography or RANSAC inlier mask is used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import cv2
import numpy as np


RING_EDGES = (0.0, 0.35, 0.70, math.inf)
RING_NAMES = ("centre", "middle", "edge")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resize_to_width(image: np.ndarray, width: int) -> np.ndarray:
    if width <= 0:
        raise ValueError("evaluation width must be positive")
    height = max(1, round(image.shape[0] * width / image.shape[1]))
    return cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)


def estimate_similarity(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Least-squares source-to-target similarity without sample rejection."""
    source = np.asarray(source, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if source.shape != target.shape or source.ndim != 2 or source.shape[1] != 2:
        raise ValueError("similarity points must be matching Nx2 arrays")
    if len(source) < 3 or not np.all(np.isfinite(source)) or not np.all(np.isfinite(target)):
        raise ValueError("similarity fit requires at least three finite point pairs")
    source_mean = source.mean(axis=0)
    target_mean = target.mean(axis=0)
    source_zero = source - source_mean
    target_zero = target - target_mean
    variance = float(np.sum(source_zero * source_zero))
    if variance <= 0.0:
        raise ValueError("similarity source points have zero variance")
    # Closed-form 2-D Procrustes avoids platform BLAS/SVD warnings observed on
    # these large feature arrays while retaining the exact rotation + uniform
    # scale model.  ``a`` and ``b`` already include the fitted scale.
    a = float(
        np.sum(source_zero[:, 0] * target_zero[:, 0])
        + np.sum(source_zero[:, 1] * target_zero[:, 1])
    ) / variance
    b = float(
        np.sum(source_zero[:, 1] * target_zero[:, 0])
        - np.sum(source_zero[:, 0] * target_zero[:, 1])
    ) / variance
    scale = math.hypot(a, b)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("similarity fit produced a non-positive scale")
    linear = np.asarray([[a, -b], [b, a]], dtype=np.float64)
    translation = target_mean - np.asarray(
        [
            source_mean[0] * linear[0, 0] + source_mean[1] * linear[1, 0],
            source_mean[0] * linear[0, 1] + source_mean[1] * linear[1, 1],
        ]
    )
    # ``linear`` is expressed for row-vector points.  OpenCV's affine matrix
    # uses column vectors, so its 2x2 block is the transpose.
    return np.column_stack((linear.T, translation))


def transform_points(points: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=np.float64)
    matrix = np.asarray(matrix, dtype=np.float64)
    if matrix.shape != (2, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError("similarity matrix must be finite and 2x3")
    return np.column_stack(
        (
            points[:, 0] * matrix[0, 0] + points[:, 1] * matrix[0, 1] + matrix[0, 2],
            points[:, 0] * matrix[1, 0] + points[:, 1] * matrix[1, 1] + matrix[1, 2],
        )
    )


def _percentiles(values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return {"count": 0, "p50": None, "p90": None, "p99": None, "max": None}
    p50, p90, p99 = np.percentile(finite, (50, 90, 99))
    return {
        "count": int(len(finite)),
        "p50": float(p50),
        "p90": float(p90),
        "p99": float(p99),
        "max": float(np.max(finite)),
    }


def _signed_percentiles(values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if not len(finite):
        return {"mean": None, "p01": None, "p50": None, "p99": None}
    p01, p50, p99 = np.percentile(finite, (1, 50, 99))
    return {
        "mean": float(np.mean(finite)),
        "p01": float(p01),
        "p50": float(p50),
        "p99": float(p99),
    }


def mutual_sift_matches(
    source_gray: np.ndarray,
    target_gray: np.ndarray,
    *,
    features: int,
    ratio: float,
) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    detector = cv2.SIFT_create(nfeatures=features, contrastThreshold=0.012)
    source_keys, source_desc = detector.detectAndCompute(source_gray, None)
    target_keys, target_desc = detector.detectAndCompute(target_gray, None)
    if source_desc is None or target_desc is None:
        raise ValueError("SIFT found no descriptors")
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    forward = matcher.knnMatch(source_desc, target_desc, k=2)
    reverse = matcher.knnMatch(target_desc, source_desc, k=2)
    accepted_forward = {
        match.queryIdx: match.trainIdx
        for match, alternate in forward
        if match.distance < ratio * alternate.distance
    }
    accepted_reverse = {
        match.queryIdx: match.trainIdx
        for match, alternate in reverse
        if match.distance < ratio * alternate.distance
    }
    mutual = [
        (source_index, target_index)
        for source_index, target_index in accepted_forward.items()
        if accepted_reverse.get(target_index) == source_index
    ]
    if len(mutual) < 12:
        raise ValueError(f"only {len(mutual)} mutual high-confidence matches")
    source = np.asarray([source_keys[i].pt for i, _ in mutual], dtype=np.float64)
    target = np.asarray([target_keys[j].pt for _, j in mutual], dtype=np.float64)
    return source, target, {
        "source_keypoints": len(source_keys),
        "target_keypoints": len(target_keys),
        "ratio_pass_forward": len(accepted_forward),
        "ratio_pass_reverse": len(accepted_reverse),
        "mutual_matches": len(mutual),
    }


def sparse_metrics(
    source: np.ndarray,
    target: np.ndarray,
    matrix: np.ndarray,
    *,
    target_shape: tuple[int, int],
) -> dict[str, Any]:
    projected = transform_points(source, matrix)
    residual = target - projected
    error = np.linalg.norm(residual, axis=1)
    height, width = target_shape
    centre = np.asarray([width / 2.0, height / 2.0])
    vector = projected - centre
    distance = np.linalg.norm(vector, axis=1)
    radius = distance / math.hypot(width / 2.0, height / 2.0)
    radial_unit = vector / np.maximum(distance[:, None], 1e-12)
    tangent_unit = np.column_stack((-radial_unit[:, 1], radial_unit[:, 0]))
    radial = np.sum(residual * radial_unit, axis=1)
    tangential = np.sum(residual * tangent_unit, axis=1)
    rings: dict[str, Any] = {}
    for name, lower, upper in zip(RING_NAMES, RING_EDGES[:-1], RING_EDGES[1:]):
        selected = (radius >= lower) & (radius < upper)
        rings[name] = {
            "radius_interval": [lower, None if math.isinf(upper) else upper],
            "error_px": _percentiles(error[selected]),
            "radial_px": _signed_percentiles(radial[selected]),
            "tangential_px": _signed_percentiles(tangential[selected]),
        }
    worst_indices = np.argsort(error)[-min(20, len(error)) :][::-1]
    return {
        "all_matches_error_px": _percentiles(error),
        "all_matches_radial_px": _signed_percentiles(radial),
        "all_matches_tangential_px": _signed_percentiles(tangential),
        "rings": rings,
        "worst_matches": [
            {
                "x": float(projected[index, 0]),
                "y": float(projected[index, 1]),
                "radius": float(radius[index]),
                "error_px": float(error[index]),
                "radial_px": float(radial[index]),
                "tangential_px": float(tangential[index]),
            }
            for index in worst_indices
        ],
        "samples": [
            {
                "x": float(projected[index, 0]),
                "y": float(projected[index, 1]),
                "radius": float(radius[index]),
                "error_px": float(error[index]),
                "radial_px": float(radial[index]),
                "tangential_px": float(tangential[index]),
            }
            for index in range(len(error))
        ],
    }


def _contrast_image(gray: np.ndarray) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(12, 12)).apply(gray)


def dense_flow_metrics(
    aligned_source: np.ndarray,
    target: np.ndarray,
    *,
    stride: int,
) -> tuple[dict[str, Any], np.ndarray, np.ndarray]:
    source = _contrast_image(aligned_source)
    reference = _contrast_image(target)
    forward_engine = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    forward_engine.setFinestScale(2)
    backward_engine = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_MEDIUM)
    backward_engine.setFinestScale(2)
    forward = forward_engine.calc(source, reference, None)
    backward = backward_engine.calc(reference, source, None)
    height, width = source.shape
    yy, xx = np.mgrid[0:height:stride, 0:width:stride]
    sampled = forward[yy, xx]
    destination_x = np.clip(np.rint(xx + sampled[..., 0]).astype(int), 0, width - 1)
    destination_y = np.clip(np.rint(yy + sampled[..., 1]).astype(int), 0, height - 1)
    round_trip = sampled + backward[destination_y, destination_x]
    round_trip_error = np.linalg.norm(round_trip, axis=-1)
    gradient_x = cv2.Sobel(source, cv2.CV_32F, 1, 0, ksize=3)
    gradient_y = cv2.Sobel(source, cv2.CV_32F, 0, 1, ksize=3)
    texture = np.hypot(gradient_x[yy, xx], gradient_y[yy, xx])
    texture_floor = float(np.percentile(texture, 35))
    confidence = (round_trip_error <= 1.0) & (texture >= texture_floor)
    displacement = np.linalg.norm(sampled, axis=-1)
    centre_x, centre_y = width / 2.0, height / 2.0
    vector_x = xx - centre_x
    vector_y = yy - centre_y
    distance = np.hypot(vector_x, vector_y)
    radius = distance / math.hypot(centre_x, centre_y)
    inverse = 1.0 / np.maximum(distance, 1e-12)
    radial = sampled[..., 0] * vector_x * inverse + sampled[..., 1] * vector_y * inverse
    tangential = sampled[..., 0] * -vector_y * inverse + sampled[..., 1] * vector_x * inverse
    rings: dict[str, Any] = {}
    for name, lower, upper in zip(RING_NAMES, RING_EDGES[:-1], RING_EDGES[1:]):
        selected = confidence & (radius >= lower) & (radius < upper)
        rings[name] = {
            "radius_interval": [lower, None if math.isinf(upper) else upper],
            "error_px": _percentiles(displacement[selected]),
            "radial_px": _signed_percentiles(radial[selected]),
            "tangential_px": _signed_percentiles(tangential[selected]),
        }
    return {
        "algorithm": "OpenCV DIS medium on CLAHE grayscale",
        "grid_stride_px": stride,
        "grid_samples": int(displacement.size),
        "confidence_definition": "forward-backward error <= 1 px and source texture >= grid p35; independent of displacement magnitude",
        "confident_samples": int(np.sum(confidence)),
        "confident_fraction": float(np.mean(confidence)),
        "all_grid_error_px": _percentiles(displacement),
        "confident_error_px": _percentiles(displacement[confidence]),
        "forward_backward_error_px": _percentiles(round_trip_error),
        "rings": rings,
    }, forward, confidence


def line_curvature_metrics(
    target: np.ndarray,
    flow: np.ndarray,
    confidence: np.ndarray,
    *,
    stride: int,
) -> dict[str, Any]:
    lines = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD).detect(_contrast_image(target))[0]
    if lines is None:
        return {"detected_long_lines": 0, "usable_lines": 0, "lines": []}
    height, width = target.shape
    minimum_length = 0.12 * min(width, height)
    results: list[dict[str, float | int]] = []
    for raw in lines[:, 0, :]:
        x0, y0, x1, y1 = (float(value) for value in raw)
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < minimum_length:
            continue
        count = max(12, int(length / max(stride, 1)))
        parameter = np.linspace(0.0, 1.0, count)
        xs = np.clip(np.rint(x0 + parameter * dx).astype(int), 0, width - 1)
        ys = np.clip(np.rint(y0 + parameter * dy).astype(int), 0, height - 1)
        grid_x = np.clip(np.rint(xs / stride).astype(int), 0, confidence.shape[1] - 1)
        grid_y = np.clip(np.rint(ys / stride).astype(int), 0, confidence.shape[0] - 1)
        valid = confidence[grid_y, grid_x]
        if int(np.sum(valid)) < 8:
            continue
        normal = np.asarray([-dy, dx], dtype=np.float64) / length
        normal_flow = flow[ys[valid], xs[valid]] @ normal
        valid_parameter = parameter[valid]
        linear = np.column_stack((np.ones_like(valid_parameter), valid_parameter))
        baseline = linear @ np.linalg.lstsq(linear, normal_flow, rcond=None)[0]
        curvature = normal_flow - baseline
        results.append(
            {
                "length_px": length,
                "samples": int(len(curvature)),
                "curvature_p95_abs_px": float(np.percentile(np.abs(curvature), 95)),
                "curvature_max_abs_px": float(np.max(np.abs(curvature))),
            }
        )
    results.sort(key=lambda record: float(record["length_px"]), reverse=True)
    values = np.asarray([record["curvature_p95_abs_px"] for record in results], dtype=np.float64)
    return {
        "definition": "reference-JPEG LSD segments >= 12% of short side; normal flow after removing per-segment linear offset/slope",
        "detected_long_lines": int(sum(math.hypot(*(line[0, 2:] - line[0, :2])) >= minimum_length for line in lines)),
        "usable_lines": len(results),
        "line_p95_curvature_px": _percentiles(values),
        "lines": results[:50],
    }


def evaluate_pair(
    reference_path: Path,
    candidate_path: Path,
    *,
    width: int,
    features: int,
    ratio: float,
    centre_radius: float,
    dense_stride: int,
) -> dict[str, Any]:
    reference_full = cv2.imread(str(reference_path), cv2.IMREAD_GRAYSCALE)
    candidate_full = cv2.imread(str(candidate_path), cv2.IMREAD_GRAYSCALE)
    if reference_full is None or candidate_full is None:
        raise ValueError("could not decode reference or candidate image")
    reference = resize_to_width(reference_full, width)
    candidate = resize_to_width(candidate_full, width)
    source_points, target_points, match_counts = mutual_sift_matches(
        candidate, reference, features=features, ratio=ratio
    )
    source_centre = np.asarray([candidate.shape[1] / 2.0, candidate.shape[0] / 2.0])
    target_centre = np.asarray([reference.shape[1] / 2.0, reference.shape[0] / 2.0])
    source_radius = np.linalg.norm(source_points - source_centre, axis=1) / math.hypot(*source_centre)
    target_radius = np.linalg.norm(target_points - target_centre, axis=1) / math.hypot(*target_centre)
    centre_selection = (source_radius <= centre_radius) & (target_radius <= centre_radius)
    if int(np.sum(centre_selection)) < 20:
        raise ValueError(f"only {int(np.sum(centre_selection))} central matches")
    matrix = estimate_similarity(source_points[centre_selection], target_points[centre_selection])
    aligned = cv2.warpAffine(
        candidate,
        matrix.astype(np.float32),
        (reference.shape[1], reference.shape[0]),
        flags=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REPLICATE,
    )
    dense, flow, confidence = dense_flow_metrics(aligned, reference, stride=dense_stride)
    full_scale = reference_full.shape[1] / reference.shape[1]
    linear = matrix[:, :2]
    return {
        "reference": {
            "path": str(reference_path),
            "sha256": sha256(reference_path),
            "full_size": [int(reference_full.shape[1]), int(reference_full.shape[0])],
        },
        "candidate": {
            "path": str(candidate_path),
            "sha256": sha256(candidate_path),
            "full_size": [int(candidate_full.shape[1]), int(candidate_full.shape[0])],
        },
        "evaluation_size": [int(reference.shape[1]), int(reference.shape[0])],
        "full_width_scale": full_scale,
        "matching": {**match_counts, "ratio_threshold": ratio},
        "alignment": {
            "model": "centre-only similarity: translation, rotation, uniform scale",
            "centre_radius_max": centre_radius,
            "fit_matches": int(np.sum(centre_selection)),
            "sample_rejection": "none after mutual ratio matching",
            "matrix_source_to_reference": matrix.tolist(),
            "uniform_scale": float(math.sqrt(abs(np.linalg.det(linear)))),
            "rotation_degrees": float(math.degrees(math.atan2(linear[0, 1], linear[0, 0]))),
        },
        "sparse": sparse_metrics(
            source_points, target_points, matrix, target_shape=reference.shape
        ),
        "dense": dense,
        "straight_lines": line_curvature_metrics(
            reference, flow, confidence, stride=dense_stride
        ),
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path, help="JSON with a pairs array")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=2000)
    parser.add_argument("--features", type=int, default=12000)
    parser.add_argument("--ratio", type=float, default=0.68)
    parser.add_argument("--centre-radius", type=float, default=0.35)
    parser.add_argument("--dense-stride", type=int, default=8)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    manifest = json.loads(arguments.manifest.read_text())
    pairs = manifest.get("pairs")
    if not isinstance(pairs, list) or not pairs:
        raise SystemExit("manifest must contain a non-empty pairs array")
    reports = []
    for pair in pairs:
        report = evaluate_pair(
            Path(pair["reference"]),
            Path(pair["candidate"]),
            width=arguments.width,
            features=arguments.features,
            ratio=arguments.ratio,
            centre_radius=arguments.centre_radius,
            dense_stride=arguments.dense_stride,
        )
        report["stem"] = pair["stem"]
        report["variant"] = pair["variant"]
        report["split"] = pair.get("split", "diagnostic")
        reports.append(report)
    output = {
        "schema_version": 1,
        "contract": {
            "geometry_authority": "original in-camera JPEG file",
            "alignment": "centre-only translation, rotation and uniform scale",
            "prohibited": ["full-frame homography", "RANSAC evaluation inlier mask"],
            "sparse_evaluation": "all mutual high-confidence matches",
            "dense_confidence": "texture and forward-backward consistency only; never displacement magnitude",
        },
        "parameters": {
            "width": arguments.width,
            "features": arguments.features,
            "ratio": arguments.ratio,
            "centre_radius": arguments.centre_radius,
            "dense_stride": arguments.dense_stride,
        },
        "pairs": reports,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
