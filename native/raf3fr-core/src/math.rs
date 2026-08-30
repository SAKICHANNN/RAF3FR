use crate::Result;
use crate::tiff::invalid;

pub(crate) fn solve<const N: usize>(
    matrix: [[f64; N]; N],
    vector: [f64; N],
    singular_message: &str,
) -> Result<[f64; N]> {
    let mut coefficients = matrix;
    let mut values = vector;
    for pivot in 0..N {
        let row = (pivot..N)
            .max_by(|left, right| {
                coefficients[*left][pivot]
                    .abs()
                    .total_cmp(&coefficients[*right][pivot].abs())
            })
            .expect("pivot range is non-empty");
        coefficients.swap(pivot, row);
        values.swap(pivot, row);
        let divisor = coefficients[pivot][pivot];
        if divisor.abs() < 1e-14 {
            return Err(invalid(singular_message));
        }
        for coefficient in &mut coefficients[pivot][pivot..] {
            *coefficient /= divisor;
        }
        values[pivot] /= divisor;
        let pivot_row = coefficients[pivot];
        let pivot_value = values[pivot];
        for row in 0..N {
            if row == pivot {
                continue;
            }
            let factor = coefficients[row][pivot];
            for (column, pivot_coefficient) in pivot_row.iter().enumerate().skip(pivot) {
                coefficients[row][column] -= factor * pivot_coefficient;
            }
            values[row] -= factor * pivot_value;
        }
    }
    Ok(values)
}
