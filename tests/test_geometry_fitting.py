from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).parents[1] / "scripts" / "fit_gfx100rf_phocus_geometry.py"
SPEC = importlib.util.spec_from_file_location("geometry_fitting", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_warp_identity() -> None:
    points = np.asarray([[0.0, 0.0], [999.0, 749.0], [1999.0, 1499.0]])
    actual = MODULE.apply_warp(
        points,
        np.asarray([1.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        width=2000,
        height=1500,
        center=(0.5, 0.5),
    )
    np.testing.assert_allclose(actual, points, atol=1e-12)


def test_tangential_terms_follow_dng_equations() -> None:
    point = np.asarray([[1750.0, 1200.0]])
    identity = np.asarray([1.0, 0.0, 0.0, 0.0, 0.0, 0.0])
    kt0 = identity.copy()
    kt0[4] = 0.001
    kt1 = identity.copy()
    kt1[5] = 0.001
    base = MODULE.apply_warp(point, identity, width=2000, height=1500, center=(0.5, 0.5))
    moved0 = MODULE.apply_warp(point, kt0, width=2000, height=1500, center=(0.5, 0.5)) - base
    moved1 = MODULE.apply_warp(point, kt1, width=2000, height=1500, center=(0.5, 0.5)) - base
    assert moved0[0, 0] > 0 and moved0[0, 1] > 0
    assert moved1[0, 0] > moved0[0, 0]
    assert moved1[0, 1] > 0


def test_candidate_jacobian_gate_accepts_current_model() -> None:
    gate = MODULE.jacobian_gate(MODULE.CURRENT_GREEN)
    assert gate["minimum_dFxdx"] > 0
    assert gate["minimum_dFydy"] > 0
    assert gate["minimum_jacobian_determinant"] > 0
