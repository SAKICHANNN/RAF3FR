#!/usr/bin/env python3
"""Fit a DNG WarpRectilinear candidate from real Phocus render residuals.

The input is produced by ``evaluate_gfx100rf_phocus_geometry.py``.  Alignment
is already frozen to a centre-only similarity.  Robust weights affect the
training fit only; every admitted sample is retained in the output metrics.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np


TRAIN_STEMS = ("DSCF1774", "DSCF2277", "DSCF2279", "DSCF2306")
HOLDOUT_STEMS = ("DSCF1791", "DSCF2286", "DSCF2290", "DSCF2308")
CURRENT_GREEN = np.asarray(
    [1.0332375407506207, -0.07588401621563211, -0.06749895991093312, 0.06133001754710046, 0.0, 0.0],
    dtype=np.float64,
)
CURRENT_CENTER = (0.500092050670, 0.499039419533)


def warp_geometry(width: int, height: int, center: tuple[float, float]) -> tuple[float, float, float]:
    if width < 2 or height < 2:
        raise ValueError("warp image dimensions must be at least 2x2")
    cx = center[0] * (width - 1)
    cy = center[1] * (height - 1)
    mx = max(cx, width - 1 - cx)
    my = max(cy, height - 1 - cy)
    return cx, cy, math.hypot(mx, my)


def warp_design(points: np.ndarray, *, width: int, height: int, center: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
    points = np.asarray(points, dtype=np.float64)
    cx, cy, normalizer = warp_geometry(width, height, center)
    dx = (points[:, 0] - cx) / normalizer
    dy = (points[:, 1] - cy) / normalizer
    radius2 = dx * dx + dy * dy
    radial = np.column_stack((np.ones(len(points)), radius2, radius2**2, radius2**3))
    x_design = np.column_stack((radial * dx[:, None], 2.0 * dx * dy, radius2 + 2.0 * dx * dx))
    y_design = np.column_stack((radial * dy[:, None], radius2 + 2.0 * dy * dy, 2.0 * dx * dy))
    return x_design, y_design


def apply_warp(points: np.ndarray, coefficients: np.ndarray, *, width: int, height: int, center: tuple[float, float]) -> np.ndarray:
    x_design, y_design = warp_design(points, width=width, height=height, center=center)
    cx, cy, normalizer = warp_geometry(width, height, center)
    # Explicit reduction avoids spurious Accelerate/BLAS overflow warnings
    # seen for these tiny six-column products on some macOS NumPy builds.
    warped_x = np.sum(x_design * coefficients[None, :], axis=1)
    warped_y = np.sum(y_design * coefficients[None, :], axis=1)
    return np.column_stack((cx + normalizer * warped_x, cy + normalizer * warped_y))


def reconstruct_points(pair: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    samples = pair["sparse"]["samples"]
    current = np.asarray([[sample["x"], sample["y"]] for sample in samples], dtype=np.float64)
    height = int(pair["evaluation_size"][1])
    width = int(pair["evaluation_size"][0])
    centre = np.asarray([width / 2.0, height / 2.0])
    vector = current - centre
    distance = np.linalg.norm(vector, axis=1)
    radial_unit = vector / np.maximum(distance[:, None], 1e-12)
    tangent_unit = np.column_stack((-radial_unit[:, 1], radial_unit[:, 0]))
    radial = np.asarray([sample["radial_px"] for sample in samples], dtype=np.float64)
    tangential = np.asarray([sample["tangential_px"] for sample in samples], dtype=np.float64)
    reference = current + radial[:, None] * radial_unit + tangential[:, None] * tangent_unit
    return current, reference


def base_weights(points: np.ndarray, *, width: int, height: int, bins: int = 8) -> np.ndarray:
    centre = np.asarray([width / 2.0, height / 2.0])
    radius = np.linalg.norm(points - centre, axis=1) / math.hypot(*centre)
    indices = np.minimum(bins - 1, np.floor(radius * bins).astype(int))
    counts = np.bincount(indices, minlength=bins)
    nonempty = max(1, int(np.sum(counts > 0)))
    return np.asarray([1.0 / (nonempty * counts[index]) for index in indices], dtype=np.float64)


def fit_coefficients(pairs: list[dict[str, Any]], *, huber_px: float, iterations: int = 12) -> tuple[np.ndarray, list[dict[str, Any]]]:
    blocks: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, str]] = []
    for pair in pairs:
        if pair["stem"] not in TRAIN_STEMS:
            continue
        current, reference = reconstruct_points(pair)
        width, height = (int(value) for value in pair["evaluation_size"])
        source = apply_warp(current, CURRENT_GREEN, width=width, height=height, center=CURRENT_CENTER)
        x_design, y_design = warp_design(reference, width=width, height=height, center=CURRENT_CENTER)
        _, _, normalizer = warp_geometry(width, height, CURRENT_CENTER)
        target = (source - np.asarray(warp_geometry(width, height, CURRENT_CENTER)[:2])) / normalizer
        design = np.concatenate((x_design, y_design), axis=0)
        values = np.concatenate((target[:, 0], target[:, 1]))
        scene_weight = base_weights(reference, width=width, height=height)
        weights = np.concatenate((scene_weight, scene_weight))
        pixel_scales = np.full(len(values), normalizer, dtype=np.float64)
        blocks.append((design, values, weights, pixel_scales, str(pair["stem"])))
    if {block[4] for block in blocks} != set(TRAIN_STEMS):
        raise ValueError("report does not contain every frozen training scene")
    design = np.concatenate([block[0] for block in blocks])
    target = np.concatenate([block[1] for block in blocks])
    base = np.concatenate([block[2] for block in blocks])
    pixel_scales = np.concatenate([block[3] for block in blocks])
    coefficients = CURRENT_GREEN.copy()
    history: list[dict[str, Any]] = []
    for iteration in range(iterations):
        residual = np.sum(design * coefficients[None, :], axis=1) - target
        # The x/y rows are consecutive halves within each scene.  A scalar
        # Huber weight per coordinate is sufficient here and stays auditable.
        robust = np.minimum(
            1.0,
            huber_px / np.maximum(np.abs(residual) * pixel_scales, 1e-12),
        )
        weight = np.sqrt(base * robust)
        next_coefficients = np.linalg.lstsq(design * weight[:, None], target * weight, rcond=None)[0]
        history.append({"iteration": iteration + 1, "coefficient_delta_l2": float(np.linalg.norm(next_coefficients - coefficients))})
        coefficients = next_coefficients
    return coefficients, history


def percentiles(values: np.ndarray) -> dict[str, float]:
    p50, p90, p99 = np.percentile(values, (50, 90, 99))
    return {"p50": float(p50), "p90": float(p90), "p99": float(p99), "max": float(np.max(values))}


def evaluate_model(pairs: list[dict[str, Any]], coefficients: np.ndarray) -> list[dict[str, Any]]:
    results = []
    for pair in pairs:
        current, reference = reconstruct_points(pair)
        width, height = (int(value) for value in pair["evaluation_size"])
        source = apply_warp(current, CURRENT_GREEN, width=width, height=height, center=CURRENT_CENTER)
        before_source = apply_warp(reference, CURRENT_GREEN, width=width, height=height, center=CURRENT_CENTER)
        after_source = apply_warp(reference, coefficients, width=width, height=height, center=CURRENT_CENTER)
        before = np.linalg.norm(before_source - source, axis=1)
        after = np.linalg.norm(after_source - source, axis=1)
        centre = np.asarray([width / 2.0, height / 2.0])
        radius = np.linalg.norm(reference - centre, axis=1) / math.hypot(*centre)
        rings = {}
        for name, lower, upper in (("centre", 0.0, 0.35), ("middle", 0.35, 0.7), ("edge", 0.7, math.inf)):
            selected = (radius >= lower) & (radius < upper)
            rings[name] = {"count": int(np.sum(selected)), "before_source_error_px": percentiles(before[selected]), "after_source_error_px": percentiles(after[selected])}
        results.append({
            "stem": pair["stem"],
            "split": "training" if pair["stem"] in TRAIN_STEMS else "holdout",
            "all_samples_retained": int(len(after)),
            "before_source_error_px": percentiles(before),
            "after_source_error_px": percentiles(after),
            "rings": rings,
        })
    return results


def jacobian_gate(coefficients: np.ndarray, *, width: int = 2000, height: int = 1500) -> dict[str, float]:
    # Finite differences cover the complete rectangle, including tangential
    # terms; this supplements the one-dimensional radial derivative gate.
    xs = np.linspace(0.0, width - 1.0, 81)
    ys = np.linspace(0.0, height - 1.0, 61)
    xx, yy = np.meshgrid(xs, ys)
    points = np.column_stack((xx.ravel(), yy.ravel()))
    epsilon = 0.05
    base = apply_warp(points, coefficients, width=width, height=height, center=CURRENT_CENTER)
    x_step = apply_warp(points + (epsilon, 0.0), coefficients, width=width, height=height, center=CURRENT_CENTER)
    y_step = apply_warp(points + (0.0, epsilon), coefficients, width=width, height=height, center=CURRENT_CENTER)
    dx = (x_step - base) / epsilon
    dy = (y_step - base) / epsilon
    determinant = dx[:, 0] * dy[:, 1] - dx[:, 1] * dy[:, 0]
    return {
        "minimum_dFxdx": float(np.min(dx[:, 0])),
        "minimum_dFydy": float(np.min(dy[:, 1])),
        "minimum_jacobian_determinant": float(np.min(determinant)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--huber-px", type=float, default=1.5)
    arguments = parser.parse_args()
    report = json.loads(arguments.report.read_text())
    pairs = report.get("pairs", [])
    stems = {pair.get("stem") for pair in pairs}
    if stems != set(TRAIN_STEMS) | set(HOLDOUT_STEMS):
        raise SystemExit("report stems do not match the frozen 4/4 dataset")
    coefficients, history = fit_coefficients(pairs, huber_px=arguments.huber_px)
    gate = jacobian_gate(coefficients)
    if min(gate.values()) <= 0.0:
        raise SystemExit(f"candidate fails invertibility gate: {gate}")
    output = {
        "schema_version": 1,
        "status": "experimental_not_for_release",
        "contract": {
            "authority": "original in-camera JPEG versus full-size Phocus render",
            "training": list(TRAIN_STEMS),
            "holdout": list(HOLDOUT_STEMS),
            "fit_weights": "equal scene and equal occupied radial bin, coordinate-wise Huber IRLS",
            "evaluation": "all mutual high-confidence samples retained; no RANSAC or residual rejection",
        },
        "huber_px_at_2000_width": arguments.huber_px,
        "current_green_coefficients": CURRENT_GREEN.tolist(),
        "candidate_green_coefficients": coefficients.tolist(),
        "center": list(CURRENT_CENTER),
        "fit_history": history,
        "invertibility": gate,
        "scenes": evaluate_model(pairs, coefficients),
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(output, indent=2) + "\n")


if __name__ == "__main__":
    main()
