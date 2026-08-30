use std::fs::{File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};

use serde::Serialize;

use crate::{DecodedRaf, DonorLayout, Error, Result};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct X2dCalibrationGains {
    pub red: u32,
    pub green_1: u32,
    pub green_2: u32,
    pub blue: u32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MappingReport {
    pub mode: String,
    pub source_origin: [usize; 2],
    pub source_size: [usize; 2],
    pub target_origin: [usize; 2],
    pub target_size: [usize; 2],
    pub default_crop_inset: [usize; 4],
    pub cfa: String,
    pub black_noise_policy: String,
    pub preserved_below_black: u64,
    pub clipped_below_code_zero: u64,
    pub clipped_below_black: u64,
    pub clipped_above_white: u64,
    pub total_samples: u64,
    pub raw_payload_md5: String,
}

fn scale_signed_signal(signal: i64, target_range: u32, denominator: u32) -> i64 {
    let numerator = signal * i64::from(target_range);
    let magnitude =
        (numerator.unsigned_abs() + u64::from(denominator / 2)) / u64::from(denominator);
    if numerator < 0 {
        -(magnitude as i64)
    } else {
        magnitude as i64
    }
}

fn apply_inverse_gain(value: i64, gain: u32) -> i64 {
    let magnitude = (value.unsigned_abs() * 65_536).div_ceil(u64::from(gain));
    if value < 0 {
        -(magnitude as i64)
    } else {
        magnitude as i64
    }
}

fn io_error(operation: &'static str, path: &Path, source: std::io::Error) -> Error {
    Error::Io {
        operation,
        path: path.to_path_buf(),
        source,
    }
}

fn exact_level(value: f64, label: &str) -> Result<u32> {
    if !value.is_finite() || value < 0.0 || value > f64::from(u32::MAX) || value.fract() != 0.0 {
        return Err(Error::InvalidMetadata(format!(
            "{label} must be an exact non-negative integer"
        )));
    }
    Ok(value as u32)
}

fn validate_matrix(matrix: [[f64; 3]; 3]) -> Result<[[f64; 3]; 3]> {
    if matrix.iter().flatten().any(|value| !value.is_finite()) {
        return Err(Error::InvalidMetadata(
            "sensor transform must be finite".to_owned(),
        ));
    }
    Ok(matrix)
}

fn gain_for_site(gains: X2dCalibrationGains, global_y: usize, global_x: usize) -> u32 {
    match (global_y & 1, global_x & 1) {
        (0, 0) => gains.red,
        (0, 1) => gains.green_1,
        (1, 0) => gains.green_2,
        (1, 1) => gains.blue,
        _ => unreachable!(),
    }
}

fn copy_no_overwrite(source: &Path, destination: &Path) -> Result<()> {
    let mut input = File::open(source).map_err(|error| io_error("open", source, error))?;
    let mut output = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(destination)
        .map_err(|error| io_error("create", destination, error))?;
    std::io::copy(&mut input, &mut output)
        .map_err(|error| io_error("copy donor to", destination, error))?;
    output
        .sync_all()
        .map_err(|error| io_error("sync", destination, error))
}

pub fn map_active_lattice(
    source: &DecodedRaf,
    donor_path: impl AsRef<Path>,
    output_path: impl AsRef<Path>,
    donor: &DonorLayout,
    sensor_matrix: Option<[[f64; 3]; 3]>,
    calibration_gains: Option<X2dCalibrationGains>,
    cancellation: Option<&AtomicBool>,
) -> Result<MappingReport> {
    let donor_path = donor_path.as_ref();
    let output_path = output_path.as_ref();
    if donor_path == output_path {
        return Err(Error::InvalidMetadata(
            "output must differ from donor".to_owned(),
        ));
    }
    if donor.byte_order != "little" {
        return Err(Error::InvalidMetadata(
            "portable mapper currently requires a little-endian donor".to_owned(),
        ));
    }
    let source_area = source.metadata.active_area;
    let target_x = donor.crop_origin[0]
        .checked_sub(4)
        .ok_or_else(|| Error::InvalidMetadata("donor crop origin is too small".to_owned()))?;
    let target_y = donor.crop_origin[1]
        .checked_sub(4)
        .ok_or_else(|| Error::InvalidMetadata("donor crop origin is too small".to_owned()))?;
    let target_width = donor.crop_size[0] + 8;
    let target_height = donor.crop_size[1] + 8;
    if (source_area.width, source_area.height) != (target_width, target_height) {
        return Err(Error::InvalidMetadata(format!(
            "Fuji/X2D active lattices differ: {}x{} != {}x{}",
            source_area.width, source_area.height, target_width, target_height
        )));
    }
    if source_area.x + source_area.width > source.metadata.width
        || source_area.y + source_area.height > source.metadata.height
        || target_x + target_width > donor.width
        || target_y + target_height > donor.height
    {
        return Err(Error::InvalidMetadata(
            "active lattice lies outside source or donor canvas".to_owned(),
        ));
    }
    if ((target_x ^ source_area.x) & 1) != 0 || ((target_y ^ source_area.y) & 1) != 0 {
        return Err(Error::InvalidMetadata(
            "active-lattice placement changes CFA phase".to_owned(),
        ));
    }
    let transform = sensor_matrix.map(validate_matrix).transpose()?;
    let black_width = source.metadata.black_width;
    let black_height = source.metadata.black_height;
    if black_width == 0
        || black_height == 0
        || source.metadata.black_levels.len() != black_width * black_height
    {
        return Err(Error::InvalidMetadata(
            "source black-level repeat pattern is invalid".to_owned(),
        ));
    }
    let black_levels = source
        .metadata
        .black_levels
        .iter()
        .enumerate()
        .map(|(index, value)| exact_level(*value, &format!("black level {index}")))
        .collect::<Result<Vec<_>>>()?;
    let source_white = source.metadata.white_level;
    if black_levels.iter().any(|black| *black >= source_white) {
        return Err(Error::InvalidMetadata(
            "source black level must be below white level".to_owned(),
        ));
    }
    if let Some(gains) = calibration_gains
        && [gains.red, gains.green_1, gains.green_2, gains.blue].contains(&0)
    {
        return Err(Error::InvalidMetadata(
            "X2D calibration gains must be positive".to_owned(),
        ));
    }

    copy_no_overwrite(donor_path, output_path)?;
    let mut output = OpenOptions::new()
        .read(true)
        .write(true)
        .open(output_path)
        .map_err(|error| io_error("open", output_path, error))?;
    let target_range = u64::try_from(target_y * donor.width + target_x)
        .ok()
        .and_then(|samples| samples.checked_mul(2))
        .and_then(|bytes| donor.strip_offset.checked_add(bytes))
        .ok_or_else(|| Error::InvalidMetadata("target payload offset overflow".to_owned()))?;
    let mut clipped_below = 0_u64;
    let mut clipped_above = 0_u64;
    let mut preserved_below_black = 0_u64;
    let mut encoded = vec![0_u8; target_width * 2];
    let signal_row = |row: usize| -> Vec<f64> {
        (0..target_width)
            .map(|column| {
                let source_x = source_area.x + column;
                let source_y = source_area.y + row;
                let pixel = i64::from(source.pixels[source_y * source.metadata.width + source_x]);
                let black =
                    black_levels[(source_y % black_height) * black_width + source_x % black_width];
                (pixel - i64::from(black)) as f64 / f64::from(source_white - black)
            })
            .collect()
    };
    let horizontal = |values: &[f64], column: usize| -> f64 {
        let mut total = 0.0;
        let mut count = 0;
        if column > 0 {
            total += values[column - 1];
            count += 1;
        }
        if column + 1 < values.len() {
            total += values[column + 1];
            count += 1;
        }
        total / f64::from(count)
    };
    let vertical = |previous: Option<&[f64]>, following: Option<&[f64]>, column: usize| -> f64 {
        let mut total = 0.0;
        let mut count = 0;
        if let Some(values) = previous {
            total += values[column];
            count += 1;
        }
        if let Some(values) = following {
            total += values[column];
            count += 1;
        }
        total / f64::from(count)
    };
    let diagonal = |previous: Option<&[f64]>, following: Option<&[f64]>, column: usize| -> f64 {
        let mut total = 0.0;
        let mut count = 0;
        for values in [previous, following].into_iter().flatten() {
            if column > 0 {
                total += values[column - 1];
                count += 1;
            }
            if column + 1 < values.len() {
                total += values[column + 1];
                count += 1;
            }
        }
        total / f64::from(count)
    };
    let mut previous: Option<Vec<f64>> = None;
    let mut current = transform.map(|_| signal_row(0));
    let mut following = transform.and_then(|_| (target_height > 1).then(|| signal_row(1)));
    for row in 0..target_height {
        if cancellation.is_some_and(|flag| flag.load(Ordering::Relaxed)) {
            return Err(Error::Cancelled);
        }
        for column in 0..target_width {
            let source_x = source_area.x + column;
            let source_y = source_area.y + row;
            let pixel = i64::from(source.pixels[source_y * source.metadata.width + source_x]);
            let black =
                black_levels[(source_y % black_height) * black_width + source_x % black_width];
            let signal = pixel - i64::from(black);
            let denominator = source_white - black;
            let global_target_x = target_x + column;
            let global_target_y = target_y + row;
            let mut mapped_signal = if let Some(matrix) = transform {
                let current = current.as_deref().ok_or_else(|| {
                    Error::InvalidMetadata("sensor row cache is empty".to_owned())
                })?;
                let previous_slice = previous.as_deref();
                let following_slice = following.as_deref();
                let h = horizontal(current, column);
                let v = vertical(previous_slice, following_slice, column);
                let d = diagonal(previous_slice, following_slice, column);
                let both_vertical = previous_slice.is_some() && following_slice.is_some();
                let transformed = match (source_y & 1, source_x & 1) {
                    (0, 0) => {
                        let green = (h * 2.0 + v * if both_vertical { 2.0 } else { 1.0 })
                            / if both_vertical { 4.0 } else { 3.0 };
                        matrix[0][0] * current[column] + matrix[0][1] * green + matrix[0][2] * d
                    }
                    (0, 1) => matrix[1][0] * h + matrix[1][1] * current[column] + matrix[1][2] * v,
                    (1, 0) => matrix[1][0] * v + matrix[1][1] * current[column] + matrix[1][2] * h,
                    (1, 1) => {
                        let green = (h * 2.0 + v * if both_vertical { 2.0 } else { 1.0 })
                            / if both_vertical { 4.0 } else { 3.0 };
                        matrix[2][0] * d + matrix[2][1] * green + matrix[2][2] * current[column]
                    }
                    _ => unreachable!(),
                };
                (transformed * f64::from(donor.white_level - donor.black_level)).round_ties_even()
                    as i64
            } else {
                scale_signed_signal(signal, donor.white_level - donor.black_level, denominator)
            };
            if let Some(gains) = calibration_gains {
                let gain = gain_for_site(gains, global_target_y, global_target_x);
                mapped_signal = apply_inverse_gain(mapped_signal, gain);
            }
            let mapped = i64::from(donor.black_level) + mapped_signal;
            if (0..i64::from(donor.black_level)).contains(&mapped) {
                preserved_below_black += 1;
            } else if mapped < 0 {
                clipped_below += 1;
            } else if mapped > i64::from(donor.white_level) {
                clipped_above += 1;
            }
            let value = u16::try_from(mapped.clamp(0, i64::from(donor.white_level)))
                .map_err(|_| Error::InvalidMetadata("mapped sample exceeds 16 bits".to_owned()))?;
            encoded[column * 2..column * 2 + 2].copy_from_slice(&value.to_le_bytes());
        }
        let offset = target_range
            + u64::try_from(row * donor.width * 2)
                .map_err(|_| Error::InvalidMetadata("target row offset overflow".to_owned()))?;
        output
            .seek(SeekFrom::Start(offset))
            .and_then(|_| output.write_all(&encoded))
            .map_err(|error| io_error("write", output_path, error))?;
        if transform.is_some() {
            previous = current.take();
            current = following.take();
            following = (row + 2 < target_height).then(|| signal_row(row + 2));
        }
    }
    output
        .sync_all()
        .map_err(|error| io_error("sync", output_path, error))?;

    let mut digest = md5::Context::new();
    let mut remaining = donor.strip_byte_count;
    let mut buffer = vec![0_u8; 1024 * 1024];
    output
        .seek(SeekFrom::Start(donor.strip_offset))
        .map_err(|error| io_error("seek", output_path, error))?;
    while remaining > 0 {
        let length = usize::try_from(remaining.min(buffer.len() as u64)).unwrap();
        output
            .read_exact(&mut buffer[..length])
            .map_err(|error| io_error("read", output_path, error))?;
        digest.consume(&buffer[..length]);
        remaining -= u64::try_from(length).unwrap();
    }
    Ok(MappingReport {
        mode: "active_lattice_1_to_1".to_owned(),
        source_origin: [source_area.x, source_area.y],
        source_size: [source_area.width, source_area.height],
        target_origin: [target_x, target_y],
        target_size: [target_width, target_height],
        default_crop_inset: [4, 4, 4, 4],
        cfa: "RGGB".to_owned(),
        black_noise_policy: "preserve_signed_source_residual".to_owned(),
        preserved_below_black,
        clipped_below_code_zero: clipped_below,
        clipped_below_black: clipped_below,
        clipped_above_white: clipped_above,
        total_samples: u64::try_from(target_width * target_height).unwrap(),
        raw_payload_md5: format!("{:x}", digest.finalize()),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn donor_calibration_gains_follow_rggb_planes() {
        let gains = X2dCalibrationGains {
            red: 1,
            green_1: 2,
            green_2: 3,
            blue: 4,
        };
        assert_eq!(gain_for_site(gains, 0, 0), 1);
        assert_eq!(gain_for_site(gains, 0, 1), 2);
        assert_eq!(gain_for_site(gains, 1, 0), 3);
        assert_eq!(gain_for_site(gains, 1, 1), 4);
    }

    #[test]
    fn signed_scaling_preserves_sub_black_residuals() {
        assert_eq!(scale_signed_signal(-1, 61_439, 61_445), -1);
        assert_eq!(scale_signed_signal(0, 61_439, 61_445), 0);
        assert_eq!(scale_signed_signal(1, 61_439, 61_445), 1);
    }

    #[test]
    fn inverse_gain_rounding_is_symmetric() {
        assert_eq!(apply_inverse_gain(-1, 67_376), -1);
        assert_eq!(apply_inverse_gain(1, 67_376), 1);
        assert_eq!(apply_inverse_gain(-67_376, 67_376), -65_536);
        assert_eq!(apply_inverse_gain(67_376, 67_376), 65_536);
    }
}
