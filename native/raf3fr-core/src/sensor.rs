use serde::Serialize;

use crate::math::solve;
use crate::{Error, Result};

const ILLUMINANT_A_K: f64 = 2856.0;
const D65_K: f64 = 6504.0;

const GFX100RF_A: [[f64; 3]; 3] = [
    [1.5656, -1.0088, 0.1263],
    [-0.2871, 1.0498, 0.2752],
    [0.0065, 0.0436, 0.6714],
];
const GFX100RF_D65: [[f64; 3]; 3] = [
    [1.2806, -0.5779, -0.1110],
    [-0.3546, 1.1507, 0.2318],
    [-0.0177, 0.0996, 0.5715],
];
const X2D100C_D65: [[f64; 3]; 3] = [
    [0.6468, -0.1899, -0.0545],
    [-0.4526, 1.2267, 0.2542],
    [-0.0388, 0.1276, 0.6096],
];
const D65_SENSOR_MAPPING: [[f64; 3]; 3] = [
    [
        0.5339897394507298,
        0.10615204857933061,
        -0.034703733651194786,
    ],
    [
        -0.06780459715148923,
        1.030823644073599,
        0.013523655327951817,
    ],
    [
        -0.01200696301633214,
        0.013197711313486968,
        1.0589816231368696,
    ],
];

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SensorMapping {
    pub matrix: [[f64; 3]; 3],
    pub estimated_cct_kelvin: f64,
    pub interpolation_weight_a: f64,
    pub source_neutral: [f64; 3],
    pub reconstructed_xyz_white: [f64; 3],
    pub target_neutral: [f64; 3],
}

fn mat_vec(matrix: [[f64; 3]; 3], vector: [f64; 3]) -> [f64; 3] {
    matrix.map(|row| row[0] * vector[0] + row[1] * vector[1] + row[2] * vector[2])
}

fn source_neutral(coefficients: [f64; 3]) -> Result<[f64; 3]> {
    if coefficients
        .iter()
        .any(|value| !value.is_finite() || *value <= 0.0)
    {
        return Err(Error::InvalidMetadata(
            "white-balance coefficients must be positive and finite".to_owned(),
        ));
    }
    let neutral = coefficients.map(|value| 1.0 / value);
    Ok(neutral.map(|value| value / neutral[1]))
}

fn gfx_matrix(cct_kelvin: f64) -> ([[f64; 3]; 3], f64) {
    let cct = cct_kelvin.clamp(ILLUMINANT_A_K, D65_K);
    let weight_a = (1.0 / cct - 1.0 / D65_K) / (1.0 / ILLUMINANT_A_K - 1.0 / D65_K);
    let matrix = std::array::from_fn(|row| {
        std::array::from_fn(|column| {
            weight_a * GFX100RF_A[row][column] + (1.0 - weight_a) * GFX100RF_D65[row][column]
        })
    });
    (matrix, weight_a)
}

fn cct_from_xy(x: f64, y: f64) -> f64 {
    let denominator = y - 0.1858;
    if denominator.abs() < 1e-12 {
        return D65_K;
    }
    let n = (x - 0.3320) / denominator;
    -449.0 * n.powi(3) + 3525.0 * n.powi(2) - 6823.3 * n + 5520.33
}

pub fn adaptive_sensor_mapping(coefficients: [f64; 3]) -> Result<SensorMapping> {
    let source_neutral = source_neutral(coefficients)?;
    let mut cct = D65_K;
    for _ in 0..24 {
        let (matrix, _) = gfx_matrix(cct);
        let mut xyz = solve(matrix, source_neutral, "singular sensor colour matrix")?;
        if xyz.iter().any(|value| !value.is_finite() || *value <= 0.0) {
            return Err(Error::InvalidMetadata(
                "white balance reconstructed an invalid illuminant".to_owned(),
            ));
        }
        xyz = xyz.map(|value| value / xyz[1]);
        let sum: f64 = xyz.iter().sum();
        let next = cct_from_xy(xyz[0] / sum, xyz[1] / sum).clamp(ILLUMINANT_A_K, D65_K);
        if (next - cct).abs() < 0.01 {
            cct = next;
            break;
        }
        cct = next;
    }
    let (source_matrix, weight_a) = gfx_matrix(cct);
    let mut xyz = solve(
        source_matrix,
        source_neutral,
        "singular sensor colour matrix",
    )?;
    xyz = xyz.map(|value| value / xyz[1]);
    let mut target_neutral = mat_vec(X2D100C_D65, xyz);
    target_neutral = target_neutral.map(|value| value / target_neutral[1]);
    if target_neutral
        .iter()
        .any(|value| !value.is_finite() || *value <= 0.0)
    {
        return Err(Error::InvalidMetadata(
            "sensor mapping produced an invalid target neutral".to_owned(),
        ));
    }
    Ok(SensorMapping {
        matrix: [
            [target_neutral[0] / source_neutral[0], 0.0, 0.0],
            [0.0, target_neutral[1] / source_neutral[1], 0.0],
            [0.0, 0.0, target_neutral[2] / source_neutral[2]],
        ],
        estimated_cct_kelvin: cct,
        interpolation_weight_a: weight_a,
        source_neutral,
        reconstructed_xyz_white: xyz,
        target_neutral,
    })
}

pub fn d65_sensor_mapping() -> [[f64; 3]; 3] {
    D65_SENSOR_MAPPING
}

pub fn transform_wb_coefficients(
    coefficients: [f64; 3],
    mapping: [[f64; 3]; 3],
) -> Result<[f64; 3]> {
    let neutral = source_neutral(coefficients)?;
    let mut target = mat_vec(mapping, neutral);
    if target
        .iter()
        .any(|value| !value.is_finite() || *value <= 0.0)
    {
        return Err(Error::InvalidMetadata(
            "sensor mapping produced an invalid white balance".to_owned(),
        ));
    }
    target = target.map(|value| value / target[1]);
    Ok(target.map(|value| 1.0 / value))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn close(actual: f64, expected: f64) {
        assert!((actual - expected).abs() < 1e-10, "{actual} != {expected}");
    }

    #[test]
    fn dscf2166_auto_wb_matches_python_reference() {
        let source = [415.0 / 302.0, 1.0, 1051.0 / 302.0];
        let mapping = adaptive_sensor_mapping(source).unwrap();
        close(mapping.estimated_cct_kelvin, 3226.7686360411262);
        close(mapping.interpolation_weight_a, 0.795138256148767);
        close(mapping.matrix[0][0], 0.7216147232304523);
        close(mapping.matrix[2][2], 1.0826463831399773);
        let target = transform_wb_coefficients(source, mapping.matrix).unwrap();
        close(target[0], 1.9043017571464003);
        close(target[1], 1.0);
        close(target[2], 3.214468273784621);
    }

    #[test]
    fn invalid_white_balance_fails_closed() {
        assert!(adaptive_sensor_mapping([1.0, 0.0, 1.0]).is_err());
    }
}
