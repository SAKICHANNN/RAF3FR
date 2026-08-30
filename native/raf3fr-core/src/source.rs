use std::path::Path;

use rawler::{RawImageData, rawimage::RawImage};
use serde::Serialize;

use crate::{Error, FujiPrivateMetadata, Result, read_fuji_private_metadata};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct ImageArea {
    pub x: usize,
    pub y: usize,
    pub width: usize,
    pub height: usize,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct SourceMetadata {
    pub make: String,
    pub model: String,
    pub width: usize,
    pub height: usize,
    pub bit_depth: usize,
    pub active_area: ImageArea,
    pub crop_area: ImageArea,
    pub black_levels: Vec<f64>,
    pub black_width: usize,
    pub black_height: usize,
    pub white_level: u32,
    pub camera_auto_wb_coefficients: [f64; 3],
    pub as_shot_wb_coefficients: [f64; 3],
    pub fuji_private: FujiPrivateMetadata,
}

#[derive(Debug)]
pub struct DecodedRaf {
    pub metadata: SourceMetadata,
    pub pixels: Vec<u16>,
}

fn image_area(area: Option<rawler::imgop::Rect>, label: &str) -> Result<ImageArea> {
    let area = area.ok_or_else(|| Error::InvalidMetadata(format!("missing {label}")))?;
    Ok(ImageArea {
        x: area.p.x,
        y: area.p.y,
        width: area.d.w,
        height: area.d.h,
    })
}

fn metadata(image: &RawImage, fuji_private: FujiPrivateMetadata) -> Result<SourceMetadata> {
    if !image.make.eq_ignore_ascii_case("fujifilm")
        || !image
            .model
            .replace(' ', "")
            .eq_ignore_ascii_case("gfx100rf")
    {
        return Err(Error::UnsupportedCamera {
            make: image.make.clone(),
            model: image.model.clone(),
        });
    }
    if image.cpp != 1 {
        return Err(Error::InvalidMetadata(format!(
            "expected one Bayer component per pixel, got {}",
            image.cpp
        )));
    }
    if image.blacklevel.levels.len()
        != image.blacklevel.width * image.blacklevel.height * image.blacklevel.cpp
    {
        return Err(Error::InvalidMetadata(
            "black-level repeat dimensions do not match its values".to_owned(),
        ));
    }
    let white_level = *image
        .whitelevel
        .0
        .first()
        .ok_or_else(|| Error::InvalidMetadata("missing white level".to_owned()))?;
    let green = f64::from(image.wb_coeffs[1]);
    if !green.is_finite() || green <= 0.0 {
        return Err(Error::InvalidMetadata(
            "invalid as-shot white-balance green coefficient".to_owned(),
        ));
    }
    let rawler_as_shot = [
        f64::from(image.wb_coeffs[0]) / green,
        1.0,
        f64::from(image.wb_coeffs[2]) / green,
    ];
    if rawler_as_shot
        .iter()
        .zip(fuji_private.as_shot_wb_coefficients)
        .any(|(decoded, exact)| (decoded - exact).abs() > 1e-5)
    {
        return Err(Error::InvalidMetadata(
            "decoded and private as-shot white balance disagree".to_owned(),
        ));
    }
    let camera_auto_wb_coefficients = fuji_private.camera_auto_wb_coefficients;
    let as_shot_wb_coefficients = fuji_private.as_shot_wb_coefficients;
    Ok(SourceMetadata {
        make: image.make.clone(),
        model: image.model.clone(),
        width: image.width,
        height: image.height,
        bit_depth: image.bps,
        active_area: image_area(image.active_area, "active area")?,
        crop_area: image_area(image.crop_area, "crop area")?,
        black_levels: image
            .blacklevel
            .levels
            .iter()
            .map(|value| f64::from(value.n) / f64::from(value.d))
            .collect(),
        black_width: image.blacklevel.width,
        black_height: image.blacklevel.height,
        white_level,
        camera_auto_wb_coefficients,
        as_shot_wb_coefficients,
        fuji_private,
    })
}

pub fn decode_gfx100rf(path: impl AsRef<Path>) -> Result<DecodedRaf> {
    let path = path.as_ref();
    let fuji_private = read_fuji_private_metadata(path)?;
    let image = rawler::decode_file(path).map_err(|source| Error::Decode {
        path: path.to_path_buf(),
        source,
    })?;
    let metadata = metadata(&image, fuji_private)?;
    let pixels = match image.data {
        RawImageData::Integer(pixels) => pixels,
        RawImageData::Float(_) => return Err(Error::FloatingPointRaw),
    };
    if pixels.len() != metadata.width * metadata.height {
        return Err(Error::InvalidMetadata(format!(
            "decoded sample count {} does not match {}x{}",
            pixels.len(),
            metadata.width,
            metadata.height
        )));
    }
    Ok(DecodedRaf { metadata, pixels })
}
