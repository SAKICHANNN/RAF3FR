use std::fs::{File, OpenOptions};
use std::io::{BufReader, BufWriter, Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};

use md5::Context as Md5;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

use crate::lens::read_lens_opcode_list;
use crate::tiff::invalid;
use crate::{
    Error, Result, X2dCalibrationGains, adaptive_sensor_mapping, append_lens_opcode_list,
    build_lens_opcode_list, d65_sensor_mapping, decode_gfx100rf, embed_source_preview,
    inspect_x2d_donor, map_active_lattice, patch_capture_and_white_balance, read_capture_metadata,
    transform_wb_coefficients,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum WhiteBalanceMode {
    Auto,
    AsShot,
    Donor,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum SensorMappingMode {
    Identity,
    D65DnglabBootstrap,
    WbAdaptiveBootstrap,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum PreviewMode {
    Source,
    Donor,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum DonorLensMode {
    Neutralize,
    Preserve,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum DistortionModel {
    NativeMatch,
    LegacyInBounds,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum IsoPolicy {
    NearestX2d,
    HnnrStable,
    Capture,
}

#[derive(Clone, Copy, Debug, PartialEq, Deserialize, Serialize)]
#[serde(default)]
pub struct ConversionOptions {
    pub white_balance: WhiteBalanceMode,
    pub sensor_mapping: SensorMappingMode,
    pub preview: PreviewMode,
    pub donor_lens_correction: DonorLensMode,
    pub distortion_model: DistortionModel,
    pub iso_policy: IsoPolicy,
    pub inverse_x2d_calibration: bool,
    pub distortion_strength: f64,
    pub chromatic_aberration_strength: f64,
    pub vignetting_strength: f64,
}

impl Default for ConversionOptions {
    fn default() -> Self {
        Self {
            white_balance: WhiteBalanceMode::Auto,
            sensor_mapping: SensorMappingMode::WbAdaptiveBootstrap,
            preview: PreviewMode::Source,
            donor_lens_correction: DonorLensMode::Neutralize,
            distortion_model: DistortionModel::NativeMatch,
            iso_policy: IsoPolicy::HnnrStable,
            inverse_x2d_calibration: false,
            distortion_strength: 1.0,
            chromatic_aberration_strength: 1.0,
            vignetting_strength: 0.0,
        }
    }
}

fn nearest_x2d_iso(capture_iso: u32) -> Result<u32> {
    const SELECTABLE: [u32; 10] = [64, 100, 200, 400, 800, 1_600, 3_200, 6_400, 12_800, 25_600];
    if capture_iso == 0 {
        return Err(invalid("capture ISO must be positive"));
    }
    SELECTABLE
        .into_iter()
        .min_by(|left, right| {
            let left_distance = (f64::from(*left) / f64::from(capture_iso)).log2().abs();
            let right_distance = (f64::from(*right) / f64::from(capture_iso)).log2().abs();
            left_distance
                .total_cmp(&right_distance)
                .then(left.cmp(right))
        })
        .ok_or_else(|| invalid("X2D ISO table is empty"))
}

fn select_model_iso(capture_iso: u32, policy: IsoPolicy) -> Result<u32> {
    match policy {
        IsoPolicy::NearestX2d => nearest_x2d_iso(capture_iso),
        IsoPolicy::HnnrStable => Ok(capture_iso.min(6_400)),
        IsoPolicy::Capture => Ok(capture_iso.min(65_535)),
    }
}

fn calibration_gains(layout: &crate::DonorLayout) -> Result<(String, X2dCalibrationGains)> {
    let raw_id = layout.raw_data_unique_id.as_deref().unwrap_or_default();
    let cohort = raw_id.get(..8).unwrap_or(raw_id);
    let (software, gains) = match cohort {
        "01409AB1" => (
            "1.1.0",
            X2dCalibrationGains {
                red: 67_376,
                green_1: 65_536,
                green_2: 65_536,
                blue: 66_448,
            },
        ),
        "0140784A" => (
            "1.0.0",
            X2dCalibrationGains {
                red: 65_536,
                green_1: 65_708,
                green_2: 65_708,
                blue: 67_192,
            },
        ),
        _ => {
            return Err(invalid(format!(
                "inverse X2D calibration is unavailable for donor cohort {}",
                if cohort.is_empty() { "unknown" } else { cohort }
            )));
        }
    };
    if layout.software.as_deref() != Some(software) {
        return Err(invalid(format!(
            "donor Software tag does not match calibration cohort {cohort}"
        )));
    }
    Ok((cohort.to_owned(), gains))
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct VerificationReport {
    pub status: String,
    pub output_sha256: String,
    pub raw_payload_md5: String,
    pub preview_sha256: String,
    pub lens_opcode_sha256: Option<String>,
    pub preserved_range_count: usize,
    pub source_checked: bool,
}

fn io_error(operation: &'static str, path: &Path, source: std::io::Error) -> Error {
    Error::Io {
        operation,
        path: path.to_path_buf(),
        source,
    }
}

fn appended_path(path: &Path, suffix: &str) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

fn check_cancelled(cancellation: Option<&AtomicBool>) -> Result<()> {
    if cancellation.is_some_and(|flag| flag.load(Ordering::Relaxed)) {
        return Err(Error::Cancelled);
    }
    Ok(())
}

fn hash_file(path: &Path, cancellation: Option<&AtomicBool>) -> Result<String> {
    let file = File::open(path).map_err(|error| io_error("open", path, error))?;
    let mut reader = BufReader::new(file);
    let mut digest = Sha256::new();
    let mut buffer = vec![0_u8; 1024 * 1024];
    loop {
        check_cancelled(cancellation)?;
        let count = reader
            .read(&mut buffer)
            .map_err(|error| io_error("read", path, error))?;
        if count == 0 {
            break;
        }
        digest.update(&buffer[..count]);
    }
    Ok(format!("{:x}", digest.finalize()))
}

fn hash_range(path: &Path, range: [u64; 2], algorithm: &str) -> Result<String> {
    if range[1] < range[0] {
        return Err(invalid("hash range is reversed"));
    }
    let mut file = File::open(path).map_err(|error| io_error("open", path, error))?;
    file.seek(SeekFrom::Start(range[0]))
        .map_err(|error| io_error("seek", path, error))?;
    let mut remaining = range[1] - range[0];
    let mut buffer = vec![0_u8; 1024 * 1024];
    if algorithm == "md5" {
        let mut digest = Md5::new();
        while remaining != 0 {
            let count = usize::try_from(remaining.min(buffer.len() as u64)).unwrap();
            file.read_exact(&mut buffer[..count])
                .map_err(|error| io_error("read", path, error))?;
            digest.consume(&buffer[..count]);
            remaining -= count as u64;
        }
        Ok(format!("{:x}", digest.finalize()))
    } else {
        let mut digest = Sha256::new();
        while remaining != 0 {
            let count = usize::try_from(remaining.min(buffer.len() as u64)).unwrap();
            file.read_exact(&mut buffer[..count])
                .map_err(|error| io_error("read", path, error))?;
            digest.update(&buffer[..count]);
            remaining -= count as u64;
        }
        Ok(format!("{:x}", digest.finalize()))
    }
}

fn merge_ranges(mut ranges: Vec<[u64; 2]>, limit: u64) -> Result<Vec<[u64; 2]>> {
    if ranges
        .iter()
        .any(|range| range[0] > range[1] || range[1] > limit)
    {
        return Err(invalid("allowed changed range is invalid"));
    }
    ranges.sort_by_key(|range| range[0]);
    let mut merged: Vec<[u64; 2]> = Vec::new();
    for range in ranges {
        if range[0] == range[1] {
            continue;
        }
        if let Some(last) = merged.last_mut()
            && range[0] <= last[1]
        {
            last[1] = last[1].max(range[1]);
            continue;
        }
        merged.push(range);
    }
    Ok(merged)
}

fn compare_preserved(
    donor: &Path,
    candidate: &Path,
    changed: &[[u64; 2]],
    limit: u64,
) -> Result<usize> {
    let mut donor_file = File::open(donor).map_err(|error| io_error("open", donor, error))?;
    let mut candidate_file =
        File::open(candidate).map_err(|error| io_error("open", candidate, error))?;
    let mut start = 0_u64;
    let mut count = 0_usize;
    let mut left = vec![0_u8; 1024 * 1024];
    let mut right = vec![0_u8; 1024 * 1024];
    for range in changed
        .iter()
        .copied()
        .chain(std::iter::once([limit, limit]))
    {
        let mut offset = start;
        while offset < range[0] {
            let length = usize::try_from((range[0] - offset).min(left.len() as u64)).unwrap();
            donor_file
                .seek(SeekFrom::Start(offset))
                .and_then(|_| donor_file.read_exact(&mut left[..length]))
                .map_err(|error| io_error("read", donor, error))?;
            candidate_file
                .seek(SeekFrom::Start(offset))
                .and_then(|_| candidate_file.read_exact(&mut right[..length]))
                .map_err(|error| io_error("read", candidate, error))?;
            if left[..length] != right[..length] {
                return Err(invalid(format!(
                    "candidate differs from donor outside declared ranges near byte {offset}"
                )));
            }
            offset += length as u64;
        }
        if start < range[0] {
            count += 1;
        }
        start = start.max(range[1]);
    }
    Ok(count)
}

fn write_manifest(path: &Path, manifest: &Value) -> Result<()> {
    let file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| io_error("create", path, error))?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer_pretty(&mut writer, manifest)
        .map_err(|error| invalid(format!("failed to encode manifest: {error}")))?;
    writer
        .write_all(b"\n")
        .map_err(|error| io_error("write", path, error))?;
    writer
        .flush()
        .map_err(|error| io_error("flush", path, error))?;
    writer
        .get_ref()
        .sync_all()
        .map_err(|error| io_error("sync", path, error))
}

fn publish_pair(
    output_partial: &Path,
    output: &Path,
    manifest_partial: &Path,
    manifest: &Path,
) -> Result<()> {
    std::fs::hard_link(output_partial, output)
        .map_err(|error| io_error("publish", output, error))?;
    if let Err(error) = std::fs::hard_link(manifest_partial, manifest) {
        let _ = std::fs::remove_file(output);
        return Err(io_error("publish", manifest, error));
    }
    std::fs::remove_file(output_partial)
        .map_err(|error| io_error("remove partial", output_partial, error))?;
    std::fs::remove_file(manifest_partial)
        .map_err(|error| io_error("remove partial", manifest_partial, error))?;
    Ok(())
}

pub fn convert(
    source: impl AsRef<Path>,
    donor: impl AsRef<Path>,
    output: impl AsRef<Path>,
    options: ConversionOptions,
) -> Result<Value> {
    convert_cancellable(source, donor, output, options, None)
}

pub fn convert_cancellable(
    source: impl AsRef<Path>,
    donor: impl AsRef<Path>,
    output: impl AsRef<Path>,
    options: ConversionOptions,
    cancellation: Option<&AtomicBool>,
) -> Result<Value> {
    let source = source.as_ref();
    let donor = donor.as_ref();
    let output = output.as_ref();
    if source == donor || source == output || donor == output {
        return Err(invalid("source, donor, and output must be different files"));
    }
    let manifest_path = appended_path(output, ".json");
    let output_partial = appended_path(output, ".partial");
    let manifest_partial = appended_path(&manifest_path, ".partial");
    for path in [output, &manifest_path, &output_partial, &manifest_partial] {
        if path.exists() {
            return Err(invalid(format!("refusing to overwrite {}", path.display())));
        }
    }
    let result = (|| {
        check_cancelled(cancellation)?;
        let decoded = decode_gfx100rf(source)?;
        check_cancelled(cancellation)?;
        let layout = inspect_x2d_donor(donor)?;
        let selected_wb = match options.white_balance {
            WhiteBalanceMode::AsShot => decoded.metadata.as_shot_wb_coefficients,
            WhiteBalanceMode::Auto | WhiteBalanceMode::Donor => {
                decoded.metadata.camera_auto_wb_coefficients
            }
        };
        let (sensor_matrix, sensor_evidence) = match options.sensor_mapping {
            SensorMappingMode::Identity => (None, json!({"mode":"identity", "matrix":null})),
            SensorMappingMode::D65DnglabBootstrap => {
                let matrix = d65_sensor_mapping();
                (
                    Some(matrix),
                    json!({"mode":"d65-dnglab-bootstrap", "matrix":matrix}),
                )
            }
            SensorMappingMode::WbAdaptiveBootstrap => {
                let sensor = adaptive_sensor_mapping(selected_wb)?;
                (
                    Some(sensor.matrix),
                    json!({"mode":"wb-adaptive-bootstrap", "evidence":sensor}),
                )
            }
        };
        let mut capture = read_capture_metadata(source, &decoded.metadata.fuji_private)?;
        let capture_iso = capture.iso;
        capture.iso = select_model_iso(capture_iso, options.iso_policy)?;
        let iso_evidence = json!({
            "mode": options.iso_policy,
            "capture_iso": capture_iso,
            "phocus_model_iso": capture.iso,
            "adjusted": capture_iso != capture.iso,
        });
        let target_wb = match options.white_balance {
            WhiteBalanceMode::Donor => None,
            _ => Some(if let Some(matrix) = sensor_matrix {
                transform_wb_coefficients(selected_wb, matrix)?
            } else {
                selected_wb
            }),
        };
        let (calibration_cohort, calibration) = if options.inverse_x2d_calibration {
            let (cohort, gains) = calibration_gains(&layout)?;
            (Some(cohort), Some(gains))
        } else {
            (None, None)
        };
        let mapping = map_active_lattice(
            &decoded,
            donor,
            &output_partial,
            &layout,
            sensor_matrix,
            calibration,
            cancellation,
        )?;
        check_cancelled(cancellation)?;
        let metadata = patch_capture_and_white_balance(
            &output_partial,
            &capture,
            target_wb,
            &mapping.raw_payload_md5,
            options.donor_lens_correction == DonorLensMode::Neutralize,
        )?;
        let preview = if options.preview == PreviewMode::Source {
            json!(embed_source_preview(
                source,
                &output_partial,
                decoded.metadata.fuji_private.preview,
                &layout,
            )?)
        } else {
            json!({
                "selection":"donor",
                "encoded_byte_count":layout.preview_byte_count,
                "encoded_sha256":hash_range(donor, [layout.preview_offset, layout.preview_end()], "sha256")?,
                "destination_range":[layout.preview_offset, layout.preview_end()],
                "destination_capacity":layout.preview_byte_count,
                "byte_count_patch_range":null
            })
        };
        let (lens_payload, lens) = build_lens_opcode_list(
            &decoded.metadata.fuji_private,
            options.distortion_model,
            options.distortion_strength,
            options.chromatic_aberration_strength,
            options.vignetting_strength,
        )?;
        let lens_patch = lens_payload
            .as_deref()
            .map(|payload| append_lens_opcode_list(&output_partial, payload))
            .transpose()?;
        let source_sha256 = hash_file(source, cancellation)?;
        let donor_sha256 = hash_file(donor, cancellation)?;
        let output_sha256 = hash_file(&output_partial, cancellation)?;
        let output_size = output_partial
            .metadata()
            .map_err(|error| io_error("inspect", &output_partial, error))?
            .len();
        let mut changed = vec![[layout.strip_offset, layout.payload_end()]];
        if options.preview == PreviewMode::Source {
            changed.push(value_range(&preview["byte_count_patch_range"])?);
            changed.push(value_range(&preview["destination_range"])?);
        }
        changed.extend(metadata.iter().map(|patch| patch.range));
        if let Some(patch) = &lens_patch {
            changed.push(patch.pointer_range);
            changed.push(patch.append_range);
        }
        let changed = merge_ranges(changed, output_size)?;
        let manifest = json!({
            "schema_version": 1,
            "engine": {"name":"raf3fr-core", "version":env!("CARGO_PKG_VERSION")},
            "source": {"filename":source.file_name().map(|v|v.to_string_lossy()).unwrap_or_default(), "sha256":source_sha256},
            "donor": {"filename":donor.file_name().map(|v|v.to_string_lossy()).unwrap_or_default(), "sha256":donor_sha256, "layout":layout},
            "output": {"filename":output.file_name().map(|v|v.to_string_lossy()).unwrap_or_default(), "sha256":output_sha256, "bytes":output_size},
            "options": options,
            "sensor_mapping": sensor_evidence,
            "target_wb_coefficients": target_wb,
            "x2d_calibration": {"enabled":options.inverse_x2d_calibration, "cohort":calibration_cohort, "gains":calibration.map(|value| [value.red, value.green_1, value.green_2, value.blue])},
            "capture_metadata": capture,
            "iso_policy": iso_evidence,
            "mapping": mapping,
            "metadata_patches": metadata,
            "preview": preview,
            "lens_correction": lens,
            "lens_container_patch": lens_patch,
            "allowed_changed_ranges": changed,
            "claim_boundary":"Observed X2D 3FR processing branch; no calibrated Fuji-to-X2D colour-equivalence or measured optical-accuracy claim."
        });
        write_manifest(&manifest_partial, &manifest)?;
        publish_pair(&output_partial, output, &manifest_partial, &manifest_path)?;
        Ok(manifest)
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&output_partial);
        let _ = std::fs::remove_file(&manifest_partial);
    }
    result
}

fn value_string<'a>(value: &'a Value, path: &[&str]) -> Result<&'a str> {
    let mut current = value;
    for key in path {
        current = current
            .get(*key)
            .ok_or_else(|| invalid(format!("manifest lacks {}", path.join("."))))?;
    }
    current
        .as_str()
        .ok_or_else(|| invalid(format!("manifest {} is not a string", path.join("."))))
}

fn value_range(value: &Value) -> Result<[u64; 2]> {
    let values = value
        .as_array()
        .ok_or_else(|| invalid("manifest range is not an array"))?;
    if values.len() != 2 {
        return Err(invalid("manifest range does not have two values"));
    }
    Ok([
        values[0]
            .as_u64()
            .ok_or_else(|| invalid("manifest range start is invalid"))?,
        values[1]
            .as_u64()
            .ok_or_else(|| invalid("manifest range end is invalid"))?,
    ])
}

pub fn verify(
    donor: impl AsRef<Path>,
    candidate: impl AsRef<Path>,
    source: Option<&Path>,
) -> Result<VerificationReport> {
    let donor = donor.as_ref();
    let candidate = candidate.as_ref();
    let manifest_path = appended_path(candidate, ".json");
    let manifest_file =
        File::open(&manifest_path).map_err(|error| io_error("open", &manifest_path, error))?;
    let manifest: Value = serde_json::from_reader(BufReader::new(manifest_file))
        .map_err(|error| invalid(format!("failed to parse manifest: {error}")))?;
    if value_string(&manifest, &["donor", "sha256"])? != hash_file(donor, None)? {
        return Err(invalid("manifest donor hash differs"));
    }
    let output_sha256 = hash_file(candidate, None)?;
    if value_string(&manifest, &["output", "sha256"])? != output_sha256 {
        return Err(invalid("manifest output hash differs"));
    }
    let donor_layout = inspect_x2d_donor(donor)?;
    let candidate_layout = inspect_x2d_donor(candidate)?;
    if donor_layout.width != candidate_layout.width
        || donor_layout.height != candidate_layout.height
        || donor_layout.strip_offset != candidate_layout.strip_offset
        || donor_layout.strip_byte_count != candidate_layout.strip_byte_count
        || donor_layout.crop_origin != candidate_layout.crop_origin
        || donor_layout.crop_size != candidate_layout.crop_size
        || donor_layout.black_level != candidate_layout.black_level
        || donor_layout.white_level != candidate_layout.white_level
    {
        return Err(invalid("candidate X2D RAW layout differs from donor"));
    }
    if candidate_layout.preview_byte_count == 0
        || candidate_layout.preview_byte_count > donor_layout.preview_byte_count
    {
        return Err(invalid("candidate preview does not fit donor slot"));
    }
    let raw_payload_md5 = hash_range(
        candidate,
        [
            candidate_layout.strip_offset,
            candidate_layout.payload_end(),
        ],
        "md5",
    )?;
    if value_string(&manifest, &["mapping", "raw_payload_md5"])? != raw_payload_md5 {
        return Err(invalid("candidate RAW payload differs from manifest"));
    }
    let preview_start = candidate_layout.preview_offset;
    let preview_end = preview_start + candidate_layout.preview_byte_count;
    let preview_sha256 = hash_range(candidate, [preview_start, preview_end], "sha256")?;
    if value_string(&manifest, &["preview", "encoded_sha256"])? != preview_sha256 {
        return Err(invalid("candidate preview differs from manifest"));
    }
    let padding = hash_range(
        candidate,
        [preview_end, donor_layout.preview_end()],
        "sha256",
    )?;
    let zero_padding =
        vec![0_u8; usize::try_from(donor_layout.preview_end() - preview_end).unwrap()];
    if padding != format!("{:x}", Sha256::digest(&zero_padding)) {
        return Err(invalid("candidate preview padding is not zero"));
    }
    let lens_opcode_sha256 = if manifest
        .get("lens_container_patch")
        .is_some_and(|value| !value.is_null())
    {
        let (_, payload) = read_lens_opcode_list(candidate)?;
        let digest = format!("{:x}", Sha256::digest(&payload));
        if value_string(&manifest, &["lens_container_patch", "payload_sha256"])? != digest {
            return Err(invalid("candidate OpcodeList3 differs from manifest"));
        }
        Some(digest)
    } else {
        None
    };
    let candidate_size = candidate
        .metadata()
        .map_err(|error| io_error("inspect", candidate, error))?
        .len();
    let ranges = manifest
        .get("allowed_changed_ranges")
        .and_then(Value::as_array)
        .ok_or_else(|| invalid("manifest lacks allowed changed ranges"))?
        .iter()
        .map(value_range)
        .collect::<Result<Vec<_>>>()?;
    let ranges = merge_ranges(ranges, candidate_size)?;
    let preserved_range_count = compare_preserved(
        donor,
        candidate,
        &ranges
            .iter()
            .copied()
            .filter(|range| range[0] < donor_layout.file_size)
            .map(|mut range| {
                range[1] = range[1].min(donor_layout.file_size);
                range
            })
            .collect::<Vec<_>>(),
        donor_layout.file_size,
    )?;
    let source_checked = if let Some(source) = source {
        if value_string(&manifest, &["source", "sha256"])? != hash_file(source, None)? {
            return Err(invalid("source RAF differs from manifest"));
        }
        true
    } else {
        false
    };
    Ok(VerificationReport {
        status: "PASS".to_owned(),
        output_sha256,
        raw_payload_md5,
        preview_sha256,
        lens_opcode_sha256,
        preserved_range_count,
        source_checked,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn iso_policies_match_the_product_contract() {
        assert_eq!(select_model_iso(40, IsoPolicy::NearestX2d).unwrap(), 64);
        assert_eq!(select_model_iso(320, IsoPolicy::NearestX2d).unwrap(), 400);
        assert_eq!(
            select_model_iso(102_400, IsoPolicy::NearestX2d).unwrap(),
            25_600
        );
        assert_eq!(
            select_model_iso(12_800, IsoPolicy::HnnrStable).unwrap(),
            6_400
        );
        assert_eq!(
            select_model_iso(102_400, IsoPolicy::Capture).unwrap(),
            65_535
        );
        assert!(select_model_iso(0, IsoPolicy::NearestX2d).is_err());
    }

    #[test]
    fn changed_ranges_are_sorted_and_merged() {
        assert_eq!(
            merge_ranges(vec![[20, 30], [4, 8], [7, 12], [30, 35]], 40).unwrap(),
            [[4, 12], [20, 35]]
        );
        assert!(merge_ranges(vec![[0, 41]], 40).is_err());
    }

    #[test]
    fn pre_cancelled_conversion_never_touches_inputs_or_output() {
        let cancellation = AtomicBool::new(true);
        let output = std::env::temp_dir().join(format!(
            "raf3fr-cancelled-{}-{}.3fr",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        let error = convert_cancellable(
            "missing-source.raf",
            "missing-donor.3fr",
            &output,
            ConversionOptions::default(),
            Some(&cancellation),
        )
        .unwrap_err();
        assert!(matches!(error, Error::Cancelled));
        assert!(!output.exists());
        assert!(!appended_path(&output, ".json").exists());
    }

    #[test]
    fn preservation_check_rejects_undeclared_changes() {
        let stamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let base =
            std::env::temp_dir().join(format!("raf3fr-preserve-{}-{stamp}", std::process::id()));
        let donor = appended_path(&base, "-donor");
        let candidate = appended_path(&base, "-candidate");
        std::fs::write(&donor, b"0123456789abcdef").unwrap();
        std::fs::write(&candidate, b"0123XX6789abcdef").unwrap();
        assert_eq!(
            compare_preserved(&donor, &candidate, &[[4, 6]], 16).unwrap(),
            2
        );
        assert!(compare_preserved(&donor, &candidate, &[], 16).is_err());
        std::fs::remove_file(donor).unwrap();
        std::fs::remove_file(candidate).unwrap();
    }
}
