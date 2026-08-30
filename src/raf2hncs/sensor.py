from __future__ import annotations

import numpy as np


# Experimental public-profile bootstraps. These matrices are interpreted as
# XYZ -> camera-native RGB. The GFX matrices match the installed Adobe Standard
# DCP's Standard Light A and D65 ColorMatrix tags; the X2D public database only
# supplies D65.
GFX100RF_A_COLOR_MATRIX = np.asarray(
    [
        [1.5656, -1.0088, 0.1263],
        [-0.2871, 1.0498, 0.2752],
        [0.0065, 0.0436, 0.6714],
    ],
    dtype=np.float64,
)
GFX100RF_D65_COLOR_MATRIX = np.asarray(
    [
        [1.2806, -0.5779, -0.1110],
        [-0.3546, 1.1507, 0.2318],
        [-0.0177, 0.0996, 0.5715],
    ],
    dtype=np.float64,
)

ILLUMINANT_A_K = 2856.0
D65_K = 6504.0
X2D100C_D65_COLOR_MATRIX = np.asarray(
    [
        [0.6468, -0.1899, -0.0545],
        [-0.4526, 1.2267, 0.2542],
        [-0.0388, 0.1276, 0.6096],
    ],
    dtype=np.float64,
)
GFX100RF_TO_X2D100C_D65_BOOTSTRAP = np.asarray(
    [
        [0.5339897394507298, 0.10615204857933061, -0.034703733651194786],
        [-0.06780459715148923, 1.030823644073599, 0.013523655327951817],
        [-0.01200696301633214, 0.013197711313486968, 1.0589816231368696],
    ],
    dtype=np.float64,
)


def _neutral_from_gains(coefficients: list[float] | tuple[float, ...]) -> np.ndarray:
    if len(coefficients) < 3 or any(
        not float(value) > 0 for value in coefficients[:3]
    ):
        raise ValueError("white-balance coefficients must contain positive R, G, B values")
    neutral = 1.0 / np.asarray(coefficients[:3], dtype=np.float64)
    return neutral / neutral[1]


def _cct_from_xy(x: float, y: float) -> float:
    """Return McCamy CCT, used only to choose the bounded A/D65 interpolation."""
    denominator = y - 0.1858
    if abs(denominator) < 1e-12:
        return D65_K
    n = (x - 0.3320) / denominator
    return float(-449.0 * n**3 + 3525.0 * n**2 - 6823.3 * n + 5520.33)


def gfx100rf_matrix_for_cct(cct_kelvin: float) -> tuple[np.ndarray, float]:
    """Interpolate the two source matrices in reciprocal-temperature space."""
    cct = float(np.clip(cct_kelvin, ILLUMINANT_A_K, D65_K))
    weight_a = (1.0 / cct - 1.0 / D65_K) / (
        1.0 / ILLUMINANT_A_K - 1.0 / D65_K
    )
    matrix = (
        weight_a * GFX100RF_A_COLOR_MATRIX
        + (1.0 - weight_a) * GFX100RF_D65_COLOR_MATRIX
    )
    return matrix, float(weight_a)


def adaptive_sensor_mapping(
    coefficients: list[float] | tuple[float, ...],
) -> tuple[np.ndarray, dict[str, object]]:
    """Estimate illuminant from a Fuji neutral and build a Fuji->X2D mapping.

    This is deliberately a bounded bootstrap, not a paired-camera calibration.
    Iteration only selects the source A/D65 matrix; tint remains present in the
    reconstructed XYZ white and is carried through the target transform.
    """
    source_neutral = _neutral_from_gains(coefficients)
    cct = D65_K
    source_matrix = GFX100RF_D65_COLOR_MATRIX
    weight_a = 0.0
    xyz = np.ones(3, dtype=np.float64)
    for _ in range(24):
        source_matrix, weight_a = gfx100rf_matrix_for_cct(cct)
        xyz = np.linalg.solve(source_matrix, source_neutral)
        if not np.all(np.isfinite(xyz)) or np.min(xyz) <= 0:
            raise ValueError("source white balance produced an invalid reconstructed illuminant")
        xyz /= xyz[1]
        chromaticity_sum = float(np.sum(xyz))
        x = float(xyz[0] / chromaticity_sum)
        y = float(xyz[1] / chromaticity_sum)
        next_cct = float(np.clip(_cct_from_xy(x, y), ILLUMINANT_A_K, D65_K))
        if abs(next_cct - cct) < 0.01:
            cct = next_cct
            break
        cct = next_cct
    source_matrix, weight_a = gfx100rf_matrix_for_cct(cct)
    xyz = np.linalg.solve(source_matrix, source_neutral)
    xyz /= xyz[1]
    target_neutral = X2D100C_D65_COLOR_MATRIX @ xyz
    target_neutral /= target_neutral[1]
    if not np.all(np.isfinite(target_neutral)) or np.min(target_neutral) <= 0:
        raise ValueError("adaptive sensor mapping produced an invalid target neutral")
    # A full cross-channel bootstrap is poorly constrained without a target
    # Illuminant-A matrix and can create large negative residuals.  Apply only
    # the positive diagonal needed to align the measured white point.  This
    # repairs the known WB-domain mismatch while preserving a separate claim
    # boundary for full colour calibration.
    mapping = np.diag(target_neutral / source_neutral)
    return mapping, {
        "operator": "positive_white_point_diagonal",
        "estimated_cct_kelvin": float(cct),
        "interpolation_weight_a": float(weight_a),
        "interpolation_weight_d65": float(1.0 - weight_a),
        "source_neutral": source_neutral.tolist(),
        "reconstructed_xyz_white": xyz.tolist(),
        "target_neutral": target_neutral.tolist(),
        "gfx100rf_xyz_to_camera": source_matrix.tolist(),
        "x2d100c_xyz_to_camera": X2D100C_D65_COLOR_MATRIX.tolist(),
    }


def transform_wb_coefficients(
    coefficients: list[float] | tuple[float, ...], matrix: np.ndarray
) -> list[float]:
    """Map source WB gains through the same source-to-target sensor matrix.

    DNG AsShotNeutral is a camera-native neutral, whereas Fuji metadata is
    represented here as R/G, 1, B/G gains.  Transform the reciprocal neutral,
    normalize target green to one, then return target-domain gains.
    """
    transform = np.asarray(matrix, dtype=np.float64)
    if transform.shape != (3, 3) or not np.all(np.isfinite(transform)):
        raise ValueError("sensor transform must be a finite 3x3 matrix")
    neutral = _neutral_from_gains(coefficients)
    target_neutral = transform @ neutral
    if not np.all(np.isfinite(target_neutral)) or np.min(target_neutral) <= 0:
        raise ValueError("sensor transform produced an invalid target neutral")
    target_neutral /= target_neutral[1]
    target_gains = 1.0 / target_neutral
    return [float(value) for value in target_gains]
