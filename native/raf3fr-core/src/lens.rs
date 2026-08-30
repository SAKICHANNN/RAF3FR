use std::fs::{File, OpenOptions};
use std::io::{Seek, SeekFrom, Write};
use std::path::Path;

use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::math::solve;
use crate::tiff::{Tiff, invalid, read_at, required};
use crate::{DistortionModel, Error, FujiPrivateMetadata, Result};

const OPCODE_LIST_3: u16 = 51022;
const WARP_RECTILINEAR: u32 = 1;
const FIX_VIGNETTE_RADIAL: u32 = 3;
const DNG_1_3: u32 = 0x0103_0000;
const SAMPLE_COUNT: usize = 4096;
const GFX100RF_KNOTS: [f64; 9] = [
    0.3535648995,
    0.5001828154,
    0.6124314442,
    0.7071297989,
    0.7904936015,
    0.8661791590,
    0.9352833638,
    1.0,
    1.0606946980,
];
const GFX100RF_DISTORTION: [f64; 9] = [
    -1.114685059,
    -2.335388184,
    -3.556091309,
    -4.736648560,
    -5.899520874,
    -7.022247314,
    -8.116058350,
    -9.171325684,
    -10.098098750,
];
const GFX100RF_NATIVE_GREEN: [f64; 4] = [
    1.029268747742375,
    -0.04267719544928282,
    -0.13848667506081908,
    0.10394817611116454,
];
const GFX100RF_NATIVE_CENTER: [f64; 2] = [0.500092050670, 0.499039419533];

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct LensOpcodeItemReport {
    pub opcode: String,
    pub opcode_id: u32,
    pub coefficients: Vec<Vec<f64>>,
    pub maximum_residual: f64,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct LensOpcodeReport {
    pub mode: String,
    pub distortion_model: DistortionModel,
    pub strengths: [f64; 3],
    pub opcodes: Vec<LensOpcodeItemReport>,
    pub payload_bytes: usize,
    pub payload_sha256: Option<String>,
    pub default_policy: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct LensOpcodeWriteReport {
    pub tag: u16,
    pub pointer_range: [u64; 2],
    pub old_subifd_offset: u32,
    pub new_subifd_offset: u32,
    pub payload_range: [u64; 2],
    pub payload_sha256: String,
    pub append_range: [u64; 2],
}

fn checked_strength(value: f64, label: &str) -> Result<f64> {
    if !value.is_finite() || !(-2.0..=2.0).contains(&value) {
        return Err(invalid(format!(
            "{label} strength must be between -2 and 2"
        )));
    }
    Ok(value)
}

fn interpolate(x: f64, knots: &[f64], values: &[f64]) -> f64 {
    if x <= knots[0] {
        return values[0];
    }
    if x >= knots[knots.len() - 1] {
        return values[values.len() - 1];
    }
    let upper = knots.partition_point(|knot| *knot < x);
    let lower = upper - 1;
    let weight = (x - knots[lower]) / (knots[upper] - knots[lower]);
    values[lower] + weight * (values[upper] - values[lower])
}

struct Splines {
    destination_radius: Vec<f64>,
    red_scale: Vec<f64>,
    green_scale: Vec<f64>,
    blue_scale: Vec<f64>,
    source_knots: Vec<f64>,
    vignette_scale: Vec<f64>,
}

fn profile_splines(
    source: &FujiPrivateMetadata,
    distortion: f64,
    ca: f64,
    vignetting: f64,
) -> Result<Splines> {
    let geometric = &source.geometric_distortion_parameters;
    let chromatic = &source.chromatic_aberration_parameters;
    let shading = &source.vignetting_parameters;
    if geometric.len() != 19 || chromatic.len() != 29 || shading.len() != 19 {
        return Err(invalid("expected Fuji 19/29/19 lens arrays"));
    }
    let knots = &geometric[1..10];
    if chromatic[1..10] != *knots || shading[1..10] != *knots {
        return Err(invalid("Fuji lens correction knots disagree"));
    }
    if knots[0] <= 0.0 || knots.windows(2).any(|pair| pair[1] <= pair[0]) {
        return Err(invalid("Fuji lens correction knots are invalid"));
    }
    let mut source_knots = Vec::with_capacity(10);
    source_knots.push(0.0);
    source_knots.extend_from_slice(knots);
    let mut geometric_scale = vec![1.0];
    geometric_scale.extend(
        geometric[10..19]
            .iter()
            .map(|value| 1.0 + distortion * value / 100.0),
    );
    let mut red_offset = vec![0.0];
    red_offset.extend(chromatic[10..19].iter().map(|value| ca * value));
    let mut blue_offset = vec![0.0];
    blue_offset.extend(chromatic[19..28].iter().map(|value| ca * value));
    let mut vignette_scale = vec![1.0];
    for value in &shading[10..19] {
        let multiplier = value / 100.0;
        if multiplier <= 0.0 || !multiplier.is_finite() {
            return Err(invalid("Fuji vignetting multipliers must be positive"));
        }
        vignette_scale.push(multiplier.powf(vignetting));
    }

    let mut destination_radius = Vec::with_capacity(SAMPLE_COUNT);
    let mut red_scale = Vec::with_capacity(SAMPLE_COUNT);
    let mut green_scale = Vec::with_capacity(SAMPLE_COUNT);
    let mut blue_scale = Vec::with_capacity(SAMPLE_COUNT);
    for index in 0..SAMPLE_COUNT {
        let radius = index as f64 / (SAMPLE_COUNT - 1) as f64;
        let scale = interpolate(radius, &source_knots, &geometric_scale);
        destination_radius.push(radius / scale);
        green_scale.push(scale);
        red_scale.push(scale * (1.0 + interpolate(radius, &source_knots, &red_offset)));
        blue_scale.push(scale * (1.0 + interpolate(radius, &source_knots, &blue_offset)));
    }
    Ok(Splines {
        destination_radius,
        red_scale,
        green_scale,
        blue_scale,
        source_knots,
        vignette_scale,
    })
}

fn least_squares<const N: usize>(rows: impl Iterator<Item = ([f64; N], f64)>) -> Result<[f64; N]> {
    let mut normal = [[0.0; N]; N];
    let mut target = [0.0; N];
    for (row, value) in rows {
        for i in 0..N {
            target[i] += row[i] * value;
            for j in 0..N {
                normal[i][j] += row[i] * row[j];
            }
        }
    }
    solve(normal, target, "lens polynomial fit is singular")
}

fn fit_warp(radius: &[f64], scale: &[f64]) -> Result<([f64; 4], f64)> {
    let coefficients = least_squares(radius.iter().zip(scale).map(|(r, s)| {
        let r2 = r * r;
        ([r * r2, r * r2 * r2, r * r2 * r2 * r2], r * (s - 1.0))
    }))?;
    let result = [1.0, coefficients[0], coefficients[1], coefficients[2]];
    let residual = radius
        .iter()
        .zip(scale)
        .map(|(r, s)| {
            let fitted = 1.0
                + coefficients[0] * r.powi(2)
                + coefficients[1] * r.powi(4)
                + coefficients[2] * r.powi(6);
            (r * (fitted - s)).abs()
        })
        .fold(0.0, f64::max);
    for index in 0..=4096 {
        let r = index as f64 / 4096.0;
        let derivative = 1.0
            + 3.0 * coefficients[0] * r.powi(2)
            + 5.0 * coefficients[1] * r.powi(4)
            + 7.0 * coefficients[2] * r.powi(6);
        if derivative <= 0.0 {
            return Err(invalid("fitted DNG warp is not invertible"));
        }
    }
    Ok((result, residual))
}

fn is_gfx100rf_fixed_lens_profile(source: &FujiPrivateMetadata) -> bool {
    let geometric = &source.geometric_distortion_parameters;
    geometric.len() == 19
        && geometric[1..10]
            .iter()
            .zip(GFX100RF_KNOTS)
            .all(|(value, expected)| (*value - expected).abs() <= 5e-10)
        && geometric[10..19]
            .iter()
            .zip(GFX100RF_DISTORTION)
            .all(|(value, expected)| (*value - expected).abs() <= 5e-9)
}

fn validate_warp(coefficients: &[f64; 4]) -> Result<()> {
    for index in 0..=4096 {
        let r = index as f64 / 4096.0;
        let derivative = coefficients[0]
            + 3.0 * coefficients[1] * r.powi(2)
            + 5.0 * coefficients[2] * r.powi(4)
            + 7.0 * coefficients[3] * r.powi(6);
        if derivative <= 0.0 {
            return Err(invalid("calibrated DNG warp is not invertible"));
        }
    }
    Ok(())
}

fn maximum_in_bounds_uniform_scale(coefficients: &[[f64; 4]; 3]) -> Result<f64> {
    const IMAGE_WIDTH: f64 = 11_664.0;
    const IMAGE_HEIGHT: f64 = 8_750.0;
    let half_width = IMAGE_WIDTH * 0.5;
    let half_height = IMAGE_HEIGHT * 0.5;
    let minimum_radius = half_width.min(half_height) / half_width.hypot(half_height);
    let minimum_u = minimum_radius * minimum_radius;
    let mut maximum_scale = f64::INFINITY;
    for [kr0, kr1, kr2, kr3] in coefficients {
        let mut candidates = vec![minimum_u, 1.0];
        let a = 3.0 * kr3;
        let b = 2.0 * kr2;
        let c = *kr1;
        if a.abs() > f64::EPSILON {
            let discriminant = b * b - 4.0 * a * c;
            if discriminant >= 0.0 {
                let root = discriminant.sqrt();
                candidates.extend([(-b - root) / (2.0 * a), (-b + root) / (2.0 * a)]);
            }
        } else if b.abs() > f64::EPSILON {
            candidates.push(-c / b);
        }
        let channel_max = candidates
            .into_iter()
            .filter(|u| minimum_u <= *u && *u <= 1.0)
            .map(|u| kr0 + kr1 * u + kr2 * u.powi(2) + kr3 * u.powi(3))
            .try_fold(f64::NEG_INFINITY, |current: f64, value| {
                if !value.is_finite() || value <= 0.0 {
                    Err(invalid("fitted DNG warp has a non-positive boundary scale"))
                } else {
                    Ok(current.max(value))
                }
            })?;
        maximum_scale = maximum_scale.min(1.0 / channel_max);
    }
    if !maximum_scale.is_finite() || maximum_scale <= 0.0 {
        return Err(invalid(
            "could not derive an in-bounds DNG warp framing scale",
        ));
    }
    Ok(maximum_scale)
}

fn header(opcode: u32, parameters: &[u8]) -> Vec<u8> {
    let mut encoded = Vec::with_capacity(16 + parameters.len());
    encoded.extend(opcode.to_be_bytes());
    encoded.extend(DNG_1_3.to_be_bytes());
    encoded.extend(0_u32.to_be_bytes());
    encoded.extend(u32::try_from(parameters.len()).unwrap().to_be_bytes());
    encoded.extend(parameters);
    encoded
}

pub fn build_lens_opcode_list(
    source: &FujiPrivateMetadata,
    distortion_model: DistortionModel,
    distortion_strength: f64,
    chromatic_aberration_strength: f64,
    vignetting_strength: f64,
) -> Result<(Option<Vec<u8>>, LensOpcodeReport)> {
    let distortion = checked_strength(distortion_strength, "distortion")?;
    let ca = checked_strength(chromatic_aberration_strength, "chromatic aberration")?;
    let vignetting = checked_strength(vignetting_strength, "vignetting")?;
    let mut opcodes = Vec::new();
    let mut reports = Vec::new();
    if distortion != 0.0 || ca != 0.0 {
        let splines = profile_splines(source, distortion, ca, 0.0)?;
        let mut fits = [
            fit_warp(&splines.destination_radius, &splines.red_scale)?,
            fit_warp(&splines.destination_radius, &splines.green_scale)?,
            fit_warp(&splines.destination_radius, &splines.blue_scale)?,
        ];
        let mut center = [0.5_f64, 0.5_f64];
        if distortion_model == DistortionModel::NativeMatch
            && is_gfx100rf_fixed_lens_profile(source)
        {
            let reference = profile_splines(source, 1.0, 0.0, 0.0)?;
            let reference_green =
                fit_warp(&reference.destination_radius, &reference.green_scale)?.0;
            for (coefficients, _) in &mut fits {
                for index in 0..4 {
                    coefficients[index] +=
                        distortion * (GFX100RF_NATIVE_GREEN[index] - reference_green[index]);
                }
                validate_warp(coefficients)?;
            }
            for index in 0..2 {
                center[index] = 0.5 + distortion * (GFX100RF_NATIVE_CENTER[index] - 0.5);
            }
        } else {
            let coefficients = fits.map(|fit| fit.0);
            let framing_scale = maximum_in_bounds_uniform_scale(&coefficients)?;
            for (coefficients, _) in &mut fits {
                for coefficient in &mut *coefficients {
                    *coefficient *= framing_scale;
                }
                validate_warp(coefficients)?;
            }
        }
        let mut parameters = Vec::new();
        parameters.extend(3_u32.to_be_bytes());
        for (coefficients, _) in &fits {
            for value in [
                coefficients[0],
                coefficients[1],
                coefficients[2],
                coefficients[3],
                0.0,
                0.0,
            ] {
                parameters.extend(value.to_be_bytes());
            }
        }
        parameters.extend(center[0].to_be_bytes());
        parameters.extend(center[1].to_be_bytes());
        opcodes.push(header(WARP_RECTILINEAR, &parameters));
        reports.push(LensOpcodeItemReport {
            opcode: "WarpRectilinear".to_owned(),
            opcode_id: WARP_RECTILINEAR,
            coefficients: fits.iter().map(|fit| fit.0.to_vec()).collect(),
            maximum_residual: fits.iter().map(|fit| fit.1).fold(0.0, f64::max),
        });
    }
    if vignetting != 0.0 {
        let splines = profile_splines(source, distortion, 0.0, vignetting)?;
        let samples = splines
            .destination_radius
            .iter()
            .zip(&splines.green_scale)
            .map(|(destination, geometric)| {
                let source_radius = destination * geometric;
                let multiplier = interpolate(
                    source_radius,
                    &splines.source_knots,
                    &splines.vignette_scale,
                )
                .max(1e-6);
                let r2 = destination * destination;
                (
                    [r2, r2.powi(2), r2.powi(3), r2.powi(4), r2.powi(5)],
                    1.0 / multiplier - 1.0,
                )
            })
            .collect::<Vec<_>>();
        let coefficients = least_squares(samples.iter().copied())?;
        if samples.iter().any(|(row, _)| {
            1.0 + row
                .iter()
                .zip(coefficients)
                .map(|(x, c)| x * c)
                .sum::<f64>()
                <= 0.0
        }) {
            return Err(invalid("fitted DNG vignetting gain is not positive"));
        }
        let residual = samples
            .iter()
            .map(|(row, value)| {
                (row.iter()
                    .zip(coefficients)
                    .map(|(x, c)| x * c)
                    .sum::<f64>()
                    - value)
                    .abs()
            })
            .fold(0.0, f64::max);
        let mut parameters = Vec::new();
        for value in coefficients {
            parameters.extend(value.to_be_bytes());
        }
        parameters.extend(0.5_f64.to_be_bytes());
        parameters.extend(0.5_f64.to_be_bytes());
        opcodes.push(header(FIX_VIGNETTE_RADIAL, &parameters));
        reports.push(LensOpcodeItemReport {
            opcode: "FixVignetteRadial".to_owned(),
            opcode_id: FIX_VIGNETTE_RADIAL,
            coefficients: vec![coefficients.to_vec()],
            maximum_residual: residual,
        });
    }
    if opcodes.is_empty() {
        return Ok((
            None,
            LensOpcodeReport {
                mode: "none".to_owned(),
                distortion_model,
                strengths: [distortion, ca, vignetting],
                opcodes: reports,
                payload_bytes: 0,
                payload_sha256: None,
                default_policy: "correct distortion and lateral CA; preserve native vignetting"
                    .to_owned(),
            },
        ));
    }
    let mut payload = Vec::new();
    payload.extend(u32::try_from(opcodes.len()).unwrap().to_be_bytes());
    for opcode in opcodes {
        payload.extend(opcode);
    }
    let payload_sha256 = format!("{:x}", Sha256::digest(&payload));
    let report = LensOpcodeReport {
        mode: "embedded_dng_opcode_list_3".to_owned(),
        distortion_model,
        strengths: [distortion, ca, vignetting],
        opcodes: reports,
        payload_bytes: payload.len(),
        payload_sha256: Some(payload_sha256),
        default_policy: "correct distortion and lateral CA; preserve native vignetting".to_owned(),
    };
    Ok((Some(payload), report))
}

fn io_error(operation: &'static str, path: &Path, source: std::io::Error) -> Error {
    Error::Io {
        operation,
        path: path.to_path_buf(),
        source,
    }
}

pub fn append_lens_opcode_list(
    path: impl AsRef<Path>,
    payload: &[u8],
) -> Result<LensOpcodeWriteReport> {
    let path = path.as_ref();
    if payload.len() <= 4 {
        return Err(invalid("opcode-list payload is unexpectedly short"));
    }
    let mut file = File::open(path).map_err(|error| io_error("open", path, error))?;
    let original_size = file
        .metadata()
        .map_err(|error| io_error("inspect", path, error))?
        .len();
    let (endian, raw_offset, pointer_range) = {
        let mut tiff = Tiff::open(&mut file, original_size, 0)?;
        let ifd0 = tiff.ifd(tiff.first_ifd)?;
        let subifd = required(&ifd0, 330)?;
        if subifd.type_id != 4 || subifd.count != 1 {
            return Err(invalid("expected one LONG SubIFDs pointer"));
        }
        let raw_offset = u32::try_from(tiff.unsigneds(subifd)?[0])
            .map_err(|_| invalid("Raw IFD offset exceeds 32 bits"))?;
        let (pointer, size) = tiff.value_location(subifd)?;
        if size != 4 {
            return Err(invalid("SubIFDs pointer is not inline"));
        }
        let raw = tiff.ifd(raw_offset)?;
        if raw.contains_key(&OPCODE_LIST_3) {
            return Err(invalid("Raw IFD already contains OpcodeList3"));
        }
        (tiff.endian, raw_offset, [pointer, pointer + 4])
    };
    let count_bytes = read_at(&mut file, original_size, u64::from(raw_offset), 2)?;
    let count = endian.u16(count_bytes.try_into().unwrap());
    let entries = read_at(
        &mut file,
        original_size,
        u64::from(raw_offset) + 2,
        usize::from(count) * 12,
    )?;
    let next_ifd = read_at(
        &mut file,
        original_size,
        u64::from(raw_offset) + 2 + u64::from(count) * 12,
        4,
    )?;
    let payload_offset = original_size;
    let padding = usize::from((payload_offset + payload.len() as u64) & 1 != 0);
    let replacement_offset = payload_offset + payload.len() as u64 + padding as u64;
    let replacement_offset_u32 = u32::try_from(replacement_offset)
        .map_err(|_| invalid("classic TIFF offset exceeds 32 bits"))?;
    let mut all_entries = entries.as_chunks::<12>().0.to_vec();
    let mut new_entry = [0_u8; 12];
    new_entry[0..2].copy_from_slice(&endian.put_u16(OPCODE_LIST_3));
    new_entry[2..4].copy_from_slice(&endian.put_u16(7));
    new_entry[4..8].copy_from_slice(&endian.put_u32(
        u32::try_from(payload.len()).map_err(|_| invalid("opcode payload exceeds 32 bits"))?,
    ));
    new_entry[8..12].copy_from_slice(
        &endian.put_u32(
            u32::try_from(payload_offset)
                .map_err(|_| invalid("opcode payload offset exceeds 32 bits"))?,
        ),
    );
    all_entries.push(new_entry);
    all_entries.sort_by_key(|entry| endian.u16([entry[0], entry[1]]));
    let mut replacement = Vec::new();
    replacement.extend(endian.put_u16(count + 1));
    for entry in all_entries {
        replacement.extend(entry);
    }
    replacement.extend(next_ifd);
    drop(file);
    let mut output = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .map_err(|error| io_error("open", path, error))?;
    output
        .seek(SeekFrom::End(0))
        .and_then(|_| output.write_all(payload))
        .map_err(|error| io_error("append opcode to", path, error))?;
    if padding != 0 {
        output
            .write_all(&[0])
            .map_err(|error| io_error("append padding to", path, error))?;
    }
    output
        .write_all(&replacement)
        .map_err(|error| io_error("append Raw IFD to", path, error))?;
    output
        .seek(SeekFrom::Start(pointer_range[0]))
        .and_then(|_| output.write_all(&endian.put_u32(replacement_offset_u32)))
        .map_err(|error| io_error("patch Raw IFD pointer in", path, error))?;
    output
        .sync_all()
        .map_err(|error| io_error("sync", path, error))?;
    let final_size = output
        .metadata()
        .map_err(|error| io_error("inspect", path, error))?
        .len();
    Ok(LensOpcodeWriteReport {
        tag: OPCODE_LIST_3,
        pointer_range,
        old_subifd_offset: raw_offset,
        new_subifd_offset: replacement_offset_u32,
        payload_range: [payload_offset, payload_offset + payload.len() as u64],
        payload_sha256: format!("{:x}", Sha256::digest(payload)),
        append_range: [original_size, final_size],
    })
}

pub(crate) fn read_lens_opcode_list(path: &Path) -> Result<(u64, Vec<u8>)> {
    let mut file = File::open(path).map_err(|error| io_error("open", path, error))?;
    let length = file
        .metadata()
        .map_err(|error| io_error("inspect", path, error))?
        .len();
    let mut tiff = Tiff::open(&mut file, length, 0)?;
    let ifd0 = tiff.ifd(tiff.first_ifd)?;
    let raw_offset = u32::try_from(tiff.unsigneds(required(&ifd0, 330)?)?[0])
        .map_err(|_| invalid("Raw IFD offset exceeds 32 bits"))?;
    let raw = tiff.ifd(raw_offset)?;
    let entry = required(&raw, OPCODE_LIST_3)?;
    if entry.type_id != 7 {
        return Err(invalid("OpcodeList3 is not UNDEFINED"));
    }
    let (offset, _) = tiff.value_location(entry)?;
    Ok((offset, tiff.bytes(entry)?))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::PreviewLocation;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn profile() -> FujiPrivateMetadata {
        let knots: Vec<f64> = (1..=9).map(|v| v as f64 / 10.0).collect();
        let mut geometric = vec![808.0];
        geometric.extend(&knots);
        geometric.extend((1..=9).map(|v| -(v as f64)));
        let mut chromatic = vec![808.0];
        chromatic.extend(&knots);
        chromatic.extend((1..=9).map(|v| v as f64 / 100000.0));
        chromatic.extend((1..=9).map(|v| -(v as f64) / 100000.0));
        chromatic.push(808.0);
        let mut shading = vec![808.0];
        shading.extend(&knots);
        shading.extend(vec![50.0; 9]);
        FujiPrivateMetadata {
            camera_auto_grb_levels: [1; 3],
            camera_auto_wb_coefficients: [1.0; 3],
            as_shot_grb_levels: [1; 3],
            as_shot_wb_coefficients: [1.0; 3],
            geometric_distortion_parameters: geometric,
            chromatic_aberration_parameters: chromatic,
            vignetting_parameters: shading,
            preview: PreviewLocation {
                offset: 0,
                length: 4,
            },
        }
    }

    fn gfx100rf_profile() -> FujiPrivateMetadata {
        let mut source = profile();
        source.geometric_distortion_parameters = vec![808.8888889];
        source
            .geometric_distortion_parameters
            .extend(GFX100RF_KNOTS);
        source
            .geometric_distortion_parameters
            .extend(GFX100RF_DISTORTION);
        source.chromatic_aberration_parameters = vec![808.8888889];
        source
            .chromatic_aberration_parameters
            .extend(GFX100RF_KNOTS);
        source.chromatic_aberration_parameters.extend([0.0; 9]);
        source.chromatic_aberration_parameters.extend([0.0; 9]);
        source.chromatic_aberration_parameters.push(808.8888889);
        source.vignetting_parameters = vec![808.8888889];
        source.vignetting_parameters.extend(GFX100RF_KNOTS);
        source.vignetting_parameters.extend([50.0; 9]);
        source
    }

    #[test]
    fn defaults_emit_only_three_plane_warp() {
        let (payload, report) =
            build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, 1.0, 1.0, 0.0)
                .unwrap();
        let payload = payload.unwrap();
        assert_eq!(&payload[0..4], &1_u32.to_be_bytes());
        assert_eq!(&payload[4..8], &WARP_RECTILINEAR.to_be_bytes());
        assert_eq!(report.opcodes.len(), 1);
        assert_eq!(report.payload_bytes, 184);
    }

    #[test]
    fn gfx100rf_uses_vendor_matched_geometry_and_center() {
        let (payload, report) = build_lens_opcode_list(
            &gfx100rf_profile(),
            DistortionModel::NativeMatch,
            1.0,
            1.0,
            0.0,
        )
        .unwrap();
        let payload = payload.unwrap();
        for (actual, expected) in report.opcodes[0].coefficients[1]
            .iter()
            .zip(GFX100RF_NATIVE_GREEN)
        {
            assert!((*actual - expected).abs() <= 2e-12);
        }
        assert!(
            (f64::from_be_bytes(payload[168..176].try_into().unwrap()) - GFX100RF_NATIVE_CENTER[0])
                .abs()
                <= 1e-15
        );
        assert!(
            (f64::from_be_bytes(payload[176..184].try_into().unwrap()) - GFX100RF_NATIVE_CENTER[1])
                .abs()
                <= 1e-15
        );
    }

    #[test]
    fn gfx100rf_legacy_model_preserves_maximum_in_bounds_geometry() {
        let (_, report) = build_lens_opcode_list(
            &gfx100rf_profile(),
            DistortionModel::LegacyInBounds,
            1.0,
            1.0,
            0.0,
        )
        .unwrap();
        assert_eq!(report.distortion_model, DistortionModel::LegacyInBounds);
        assert!((report.opcodes[0].coefficients[1][0] - 1.0331706566178662).abs() <= 2e-12);
        assert_ne!(report.opcodes[0].coefficients[1], GFX100RF_NATIVE_GREEN);
    }

    #[test]
    fn vignetting_is_optional_and_all_corrections_can_be_disabled() {
        let (payload, report) =
            build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, 1.0, 1.0, 1.0)
                .unwrap();
        assert_eq!(&payload.unwrap()[0..4], &2_u32.to_be_bytes());
        assert_eq!(report.opcodes.len(), 2);
        let (payload, report) =
            build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, 0.0, 0.0, 0.0)
                .unwrap();
        assert!(payload.is_none());
        assert_eq!(report.mode, "none");
    }

    #[test]
    fn signed_strengths_reverse_profile_direction_and_enforce_bounds() {
        let (_, positive) =
            build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, 1.0, 1.0, 1.0)
                .unwrap();
        let (_, negative) =
            build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, -1.0, -1.0, -1.0)
                .unwrap();
        assert_eq!(positive.strengths, [1.0, 1.0, 1.0]);
        assert_eq!(negative.strengths, [-1.0, -1.0, -1.0]);
        assert_ne!(positive.payload_sha256, negative.payload_sha256);
        for value in [-2.01, 2.01] {
            let error =
                build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, value, 0.0, 0.0)
                    .unwrap_err();
            assert!(error.to_string().contains("between -2 and 2"));
        }
    }

    #[test]
    fn opcode_append_preserves_existing_ifd_and_installs_payload() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("raf3fr-opcode-{}-{stamp}.tiff", std::process::id()));
        let mut data = vec![0_u8; 160];
        data[0..8].copy_from_slice(&[b'I', b'I', 42, 0, 8, 0, 0, 0]);
        data[8..26].copy_from_slice(&[1, 0, 74, 1, 4, 0, 1, 0, 0, 0, 64, 0, 0, 0, 0, 0, 0, 0]);
        data[64..82].copy_from_slice(&[1, 0, 0, 1, 4, 0, 1, 0, 0, 0, 128, 45, 0, 0, 0, 0, 0, 0]);
        std::fs::write(&path, &data).unwrap();
        let payload =
            build_lens_opcode_list(&profile(), DistortionModel::NativeMatch, 1.0, 1.0, 0.0)
                .unwrap()
                .0
                .unwrap();
        let report = append_lens_opcode_list(&path, &payload).unwrap();
        let mut file = File::open(&path).unwrap();
        let length = file.metadata().unwrap().len();
        let mut tiff = Tiff::open(&mut file, length, 0).unwrap();
        let ifd0 = tiff.ifd(tiff.first_ifd).unwrap();
        let raw_offset =
            u32::try_from(tiff.unsigneds(required(&ifd0, 330).unwrap()).unwrap()[0]).unwrap();
        let raw = tiff.ifd(raw_offset).unwrap();
        assert_eq!(
            tiff.unsigneds(required(&raw, 256).unwrap()).unwrap(),
            [11648]
        );
        assert_eq!(
            tiff.bytes(required(&raw, OPCODE_LIST_3).unwrap()).unwrap(),
            payload
        );
        assert_eq!(report.pointer_range, [18, 22]);
        std::fs::remove_file(path).unwrap();
    }
}
