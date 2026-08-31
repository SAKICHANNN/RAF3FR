from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_gfx100rf_phocus_geometry.py"
SPEC = importlib.util.spec_from_file_location("geometry_evaluation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_similarity_roundtrip_without_point_rejection() -> None:
    source = np.asarray(
        [[-2.0, -1.0], [0.0, 0.0], [3.0, 1.0], [1.0, 4.0], [-3.0, 2.0]]
    )
    angle = np.deg2rad(7.5)
    scale = 1.013
    rotation = np.asarray(
        [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
    )
    target = source @ (scale * rotation) + np.asarray([12.0, -4.0])
    matrix = MODULE.estimate_similarity(source, target)
    np.testing.assert_allclose(MODULE.transform_points(source, matrix), target, atol=1e-12)


def test_sparse_metrics_keep_outer_extreme() -> None:
    source = np.asarray([[40.0, 40.0], [50.0, 50.0], [60.0, 60.0], [99.0, 99.0]])
    target = source.copy()
    target[-1, 0] += 8.0
    matrix = np.asarray([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    metrics = MODULE.sparse_metrics(source, target, matrix, target_shape=(100, 100))
    assert metrics["all_matches_error_px"]["count"] == 4
    assert len(metrics["samples"]) == 4
    assert metrics["all_matches_error_px"]["max"] == 8.0
    assert metrics["rings"]["edge"]["error_px"]["max"] == 8.0
    assert metrics["worst_matches"][0]["error_px"] == 8.0
