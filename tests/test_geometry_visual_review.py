from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "build_geometry_visual_review.py"
SPEC = importlib.util.spec_from_file_location("geometry_visual_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_full_resolution_matrix_scales_both_coordinate_frames() -> None:
    pair = {
        "alignment": {"matrix_source_to_reference": [[1.0, 0.0, 2.0], [0.0, 1.0, -3.0]]},
        "evaluation_size": [2000, 1500],
        "candidate": {"full_size": [10000, 7500]},
        "reference": {"full_size": [12000, 9000]},
    }
    actual = MODULE.full_resolution_matrix(pair)
    np.testing.assert_allclose(actual, [[1.2, 0.0, 12.0], [0.0, 1.2, -18.0]])
