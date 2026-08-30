use std::env;
use std::ffi::{OsStr, OsString};

use anyhow::{Context, bail};
use serde_json::json;
use sha2::{Digest, Sha256};

fn text<'a>(value: &'a OsStr, label: &str) -> anyhow::Result<&'a str> {
    value
        .to_str()
        .with_context(|| format!("{label} must be valid UTF-8"))
}

fn convert_arguments(
    paths: &[OsString],
) -> anyhow::Result<(&OsStr, &OsStr, &OsStr, raf3fr_core::ConversionOptions)> {
    if paths.len() < 3 {
        bail!("convert requires SOURCE RAF, DONOR 3FR, and OUTPUT 3FR");
    }
    let mut options = raf3fr_core::ConversionOptions::default();
    let mut index = 3;
    while index < paths.len() {
        let flag = text(&paths[index], "convert option")?;
        if flag == "--inverse-x2d-calibration" {
            options.inverse_x2d_calibration = true;
            index += 1;
            continue;
        }
        let value = paths
            .get(index + 1)
            .with_context(|| format!("{flag} requires a value"))?;
        let value = text(value, flag)?;
        match flag {
            "--white-balance" => {
                options.white_balance = match value {
                    "auto" => raf3fr_core::WhiteBalanceMode::Auto,
                    "as-shot" => raf3fr_core::WhiteBalanceMode::AsShot,
                    "donor" => raf3fr_core::WhiteBalanceMode::Donor,
                    _ => bail!("unsupported white balance: {value}"),
                }
            }
            "--sensor-mapping" => {
                options.sensor_mapping = match value {
                    "identity" => raf3fr_core::SensorMappingMode::Identity,
                    "d65-dnglab-bootstrap" => raf3fr_core::SensorMappingMode::D65DnglabBootstrap,
                    "wb-adaptive-bootstrap" => raf3fr_core::SensorMappingMode::WbAdaptiveBootstrap,
                    _ => bail!("unsupported sensor mapping: {value}"),
                }
            }
            "--preview" => {
                options.preview = match value {
                    "source" => raf3fr_core::PreviewMode::Source,
                    "donor" => raf3fr_core::PreviewMode::Donor,
                    _ => bail!("unsupported preview mode: {value}"),
                }
            }
            "--donor-lens-correction" => {
                options.donor_lens_correction = match value {
                    "neutralize" => raf3fr_core::DonorLensMode::Neutralize,
                    "preserve" => raf3fr_core::DonorLensMode::Preserve,
                    _ => bail!("unsupported donor lens-correction mode: {value}"),
                }
            }
            "--distortion-model" => {
                options.distortion_model = match value {
                    "native-match" => raf3fr_core::DistortionModel::NativeMatch,
                    "legacy-in-bounds" => raf3fr_core::DistortionModel::LegacyInBounds,
                    _ => bail!("unsupported distortion model: {value}"),
                }
            }
            "--iso-policy" => {
                options.iso_policy = match value {
                    "nearest-x2d" => raf3fr_core::IsoPolicy::NearestX2d,
                    "hnnr-stable" => raf3fr_core::IsoPolicy::HnnrStable,
                    "capture" => raf3fr_core::IsoPolicy::Capture,
                    _ => bail!("unsupported ISO policy: {value}"),
                }
            }
            "--distortion-strength" => options.distortion_strength = value.parse()?,
            "--ca-strength" => options.chromatic_aberration_strength = value.parse()?,
            "--vignetting-strength" => options.vignetting_strength = value.parse()?,
            _ => bail!("unknown convert option: {flag}"),
        }
        index += 2;
    }
    Ok((&paths[0], &paths[1], &paths[2], options))
}

fn main() -> anyhow::Result<()> {
    let mut arguments = env::args_os();
    let _program = arguments.next();
    let Some(command) = arguments.next() else {
        bail!("usage: raf3fr-cli <inspect-raf|inspect-donor|map-payload|convert|verify> <files>");
    };
    let paths: Vec<_> = arguments.collect();
    let report = if command == "inspect-raf" && paths.len() == 1 {
        let path = &paths[0];
        let decoded = raf3fr_core::decode_gfx100rf(path)
            .with_context(|| format!("failed to inspect {}", path.to_string_lossy()))?;
        let mut pixel_digest = Sha256::new();
        for pixel in &decoded.pixels {
            pixel_digest.update(pixel.to_le_bytes());
        }
        json!({
            "metadata": decoded.metadata,
            "pixel_count": decoded.pixels.len(),
            "pixel_sha256_le16": format!("{:x}", pixel_digest.finalize()),
        })
    } else if command == "inspect-donor" && paths.len() == 1 {
        let path = &paths[0];
        json!(
            raf3fr_core::inspect_x2d_donor(path)
                .with_context(|| format!("failed to inspect {}", path.to_string_lossy()))?
        )
    } else if command == "convert" {
        let (source, donor, output, options) = convert_arguments(&paths)?;
        raf3fr_core::convert(source, donor, output, options)?
    } else if command == "verify" && (paths.len() == 2 || paths.len() == 3) {
        json!(raf3fr_core::verify(
            &paths[0],
            &paths[1],
            paths.get(2).map(std::path::Path::new),
        )?)
    } else if command == "map-payload" && paths.len() == 3 {
        let source_path = &paths[0];
        let donor_path = &paths[1];
        let output_path = &paths[2];
        let decoded = raf3fr_core::decode_gfx100rf(source_path)
            .with_context(|| format!("failed to decode {}", source_path.to_string_lossy()))?;
        let donor = raf3fr_core::inspect_x2d_donor(donor_path)
            .with_context(|| format!("failed to inspect {}", donor_path.to_string_lossy()))?;
        let sensor =
            raf3fr_core::adaptive_sensor_mapping(decoded.metadata.camera_auto_wb_coefficients)?;
        let capture =
            raf3fr_core::read_capture_metadata(source_path, &decoded.metadata.fuji_private)?;
        let target_wb = raf3fr_core::transform_wb_coefficients(
            decoded.metadata.camera_auto_wb_coefficients,
            sensor.matrix,
        )?;
        let mapping = raf3fr_core::map_active_lattice(
            &decoded,
            donor_path,
            output_path,
            &donor,
            Some(sensor.matrix),
            None,
            None,
        )?;
        let metadata_patches = raf3fr_core::patch_capture_and_white_balance(
            output_path,
            &capture,
            Some(target_wb),
            &mapping.raw_payload_md5,
            true,
        )?;
        let preview = raf3fr_core::embed_source_preview(
            source_path,
            output_path,
            decoded.metadata.fuji_private.preview,
            &donor,
        )?;
        let (lens_payload, lens) = raf3fr_core::build_lens_opcode_list(
            &decoded.metadata.fuji_private,
            raf3fr_core::DistortionModel::NativeMatch,
            1.0,
            1.0,
            0.0,
        )?;
        let lens_container_patch = lens_payload
            .as_deref()
            .map(|payload| raf3fr_core::append_lens_opcode_list(output_path, payload))
            .transpose()?;
        json!({
            "capture": capture,
            "mapping": mapping,
            "metadata_patches": metadata_patches,
            "preview": preview,
            "lens": lens,
            "lens_container_patch": lens_container_patch,
            "target_wb_coefficients": target_wb,
        })
    } else {
        bail!("usage: raf3fr-cli <inspect-raf|inspect-donor|map-payload|convert|verify> <files>");
    };
    serde_json::to_writer_pretty(std::io::stdout().lock(), &report)?;
    println!();
    Ok(())
}
