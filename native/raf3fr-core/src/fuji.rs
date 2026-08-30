use std::fs::File;
use std::path::Path;

use serde::Serialize;

use crate::tiff::{Tiff, invalid, read_at, required};
use crate::{Error, Result};

const RAF_JPEG_POINTER: u64 = 84;
const RAF_PRIVATE_TIFF_POINTER: u64 = 100;

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct PreviewLocation {
    pub offset: u64,
    pub length: u64,
}

#[derive(Clone, Debug, PartialEq, Serialize)]
pub struct FujiPrivateMetadata {
    pub camera_auto_grb_levels: [u32; 3],
    pub camera_auto_wb_coefficients: [f64; 3],
    pub as_shot_grb_levels: [u32; 3],
    pub as_shot_wb_coefficients: [f64; 3],
    pub geometric_distortion_parameters: Vec<f64>,
    pub chromatic_aberration_parameters: Vec<f64>,
    pub vignetting_parameters: Vec<f64>,
    pub preview: PreviewLocation,
}

fn grb(levels: Vec<u32>, label: &str) -> Result<([u32; 3], [f64; 3])> {
    let levels: [u32; 3] = levels
        .try_into()
        .map_err(|_| invalid(format!("{label} must contain three levels")))?;
    if levels.contains(&0) {
        return Err(invalid(format!("{label} contains a zero level")));
    }
    let [green, red, blue] = levels;
    Ok((
        levels,
        [
            f64::from(red) / f64::from(green),
            1.0,
            f64::from(blue) / f64::from(green),
        ],
    ))
}

pub fn read_fuji_private_metadata(path: impl AsRef<Path>) -> Result<FujiPrivateMetadata> {
    let path = path.as_ref();
    let mut file = File::open(path).map_err(|source| Error::MetadataIo { source })?;
    let file_length = file
        .metadata()
        .map_err(|source| Error::MetadataIo { source })?
        .len();
    let signature = read_at(&mut file, file_length, 0, 8)?;
    if signature != b"FUJIFILM" {
        return Err(invalid("source does not have the RAF signature"));
    }
    let jpeg_pointer = read_at(&mut file, file_length, RAF_JPEG_POINTER, 8)?;
    let preview = PreviewLocation {
        offset: u64::from(u32::from_be_bytes(jpeg_pointer[0..4].try_into().unwrap())),
        length: u64::from(u32::from_be_bytes(jpeg_pointer[4..8].try_into().unwrap())),
    };
    if preview.length < 4
        || preview.offset.checked_add(preview.length).is_none()
        || preview.offset + preview.length > file_length
    {
        return Err(invalid("RAF preview range is invalid"));
    }
    let jpeg_edges = [
        read_at(&mut file, file_length, preview.offset, 2)?,
        read_at(
            &mut file,
            file_length,
            preview.offset + preview.length - 2,
            2,
        )?,
    ];
    if jpeg_edges[0] != [0xff, 0xd8] || jpeg_edges[1] != [0xff, 0xd9] {
        return Err(invalid("RAF preview is not a complete JPEG"));
    }

    let pointer = read_at(&mut file, file_length, RAF_PRIVATE_TIFF_POINTER, 4)?;
    let base = u64::from(u32::from_be_bytes(pointer.try_into().unwrap()));
    let mut tiff = Tiff::open(&mut file, file_length, base)?;
    let root = tiff.ifd(tiff.first_ifd)?;
    let fuji_pointer = required(&root, 0xf000)?;
    if fuji_pointer.type_id != 13 || fuji_pointer.count != 1 {
        return Err(invalid("FujiIFD pointer has an unsupported layout"));
    }
    let fuji_offset = tiff.endian.u32(fuji_pointer.value_or_offset);
    let entries = tiff.ifd(fuji_offset)?;
    let exact_longs = |values: Vec<u64>| {
        values
            .into_iter()
            .map(|value| {
                u32::try_from(value).map_err(|_| invalid("Fuji LONG value exceeds 32 bits"))
            })
            .collect::<Result<Vec<_>>>()
    };
    let auto_values = exact_longs(tiff.unsigneds(required(&entries, 0xf00d)?)?)?;
    let as_shot_values = exact_longs(tiff.unsigneds(required(&entries, 0xf00e)?)?)?;
    let (camera_auto_grb_levels, camera_auto_wb_coefficients) =
        grb(auto_values, "camera auto white balance")?;
    let (as_shot_grb_levels, as_shot_wb_coefficients) =
        grb(as_shot_values, "as-shot white balance")?;
    let geometric_distortion_parameters = tiff.signed_rationals(required(&entries, 0xf00b)?)?;
    let chromatic_aberration_parameters = tiff.signed_rationals(required(&entries, 0xf00f)?)?;
    let vignetting_parameters = tiff.signed_rationals(required(&entries, 0xf010)?)?;
    if geometric_distortion_parameters.len() != 19
        || chromatic_aberration_parameters.len() != 29
        || vignetting_parameters.len() != 19
    {
        return Err(invalid("Fuji lens-profile vector lengths are unsupported"));
    }
    Ok(FujiPrivateMetadata {
        camera_auto_grb_levels,
        camera_auto_wb_coefficients,
        as_shot_grb_levels,
        as_shot_wb_coefficients,
        geometric_distortion_parameters,
        chromatic_aberration_parameters,
        vignetting_parameters,
        preview,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grb_levels_preserve_exact_fuji_auto_white_balance() {
        let (levels, coefficients) =
            grb(vec![302, 415, 1051], "camera auto white balance").unwrap();
        assert_eq!(levels, [302, 415, 1051]);
        assert_eq!(coefficients, [415.0 / 302.0, 1.0, 1051.0 / 302.0]);
    }

    #[test]
    fn grb_levels_fail_closed_on_invalid_payloads() {
        assert!(grb(vec![302, 415], "test").is_err());
        assert!(grb(vec![302, 0, 1051], "test").is_err());
    }
}
