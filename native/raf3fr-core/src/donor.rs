use std::fs::File;
use std::path::Path;

use serde::Serialize;

use crate::tiff::{Endian, Entry, Tiff, invalid, required};
use crate::{Error, Result};

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct DonorLayout {
    pub byte_order: String,
    pub make: String,
    pub model: String,
    pub width: usize,
    pub height: usize,
    pub bits_per_sample: u16,
    pub compression: u16,
    pub strip_offset: u64,
    pub strip_byte_count: u64,
    pub preview_offset: u64,
    pub preview_byte_count: u64,
    pub raw_ifd_pointer_range: [u64; 2],
    pub crop_origin: [usize; 2],
    pub crop_size: [usize; 2],
    pub black_level: u32,
    pub white_level: u32,
    pub file_size: u64,
    pub software: Option<String>,
    pub raw_data_unique_id: Option<String>,
}

impl DonorLayout {
    pub fn payload_end(&self) -> u64 {
        self.strip_offset + self.strip_byte_count
    }

    pub fn preview_end(&self) -> u64 {
        self.preview_offset + self.preview_byte_count
    }
}

fn one_unsigned(tiff: &mut Tiff<'_>, entry: &Entry, label: &str) -> Result<u64> {
    let values = tiff.unsigneds(entry)?;
    if values.len() != 1 {
        return Err(invalid(format!("{label} must contain one value")));
    }
    Ok(values[0])
}

fn numbers(tiff: &mut Tiff<'_>, entry: &Entry) -> Result<Vec<f64>> {
    if entry.type_id == 5 {
        tiff.unsigned_rationals(entry)
    } else {
        Ok(tiff
            .unsigneds(entry)?
            .into_iter()
            .map(|value| value as f64)
            .collect())
    }
}

fn pair_usize(tiff: &mut Tiff<'_>, entry: &Entry, label: &str) -> Result<[usize; 2]> {
    let values = numbers(tiff, entry)?;
    if values.len() != 2
        || values
            .iter()
            .any(|value| !value.is_finite() || *value < 0.0)
    {
        return Err(invalid(format!(
            "{label} must contain two non-negative values"
        )));
    }
    Ok([values[0] as usize, values[1] as usize])
}

fn level(tiff: &mut Tiff<'_>, entry: &Entry, label: &str) -> Result<u32> {
    let values = numbers(tiff, entry)?;
    if values.len() != 1 || !values[0].is_finite() || values[0] < 0.0 {
        return Err(invalid(format!(
            "{label} must contain one non-negative value"
        )));
    }
    Ok(values[0] as u32)
}

pub fn inspect_x2d_donor(path: impl AsRef<Path>) -> Result<DonorLayout> {
    let path = path.as_ref();
    let mut file = File::open(path).map_err(|source| Error::MetadataIo { source })?;
    let file_size = file
        .metadata()
        .map_err(|source| Error::MetadataIo { source })?
        .len();
    let mut tiff = Tiff::open(&mut file, file_size, 0)?;
    let ifd0 = tiff.ifd(tiff.first_ifd)?;
    let make = tiff.ascii(required(&ifd0, 271)?)?;
    let model = tiff.ascii(required(&ifd0, 272)?)?;
    if !make.eq_ignore_ascii_case("hasselblad") || !model.eq_ignore_ascii_case("x2d 100c") {
        return Err(invalid(format!(
            "expected a Hasselblad X2D 100C donor, got {make} {model}"
        )));
    }
    let software = ifd0.get(&305).map(|entry| tiff.ascii(entry)).transpose()?;
    let raw_data_unique_id = ifd0
        .get(&50781)
        .map(|entry| {
            let bytes = tiff.bytes(entry)?;
            Ok(String::from_utf8(bytes.clone()).unwrap_or_else(|_| hex::encode_upper(bytes)))
        })
        .transpose()?;
    let preview_offset = one_unsigned(&mut tiff, required(&ifd0, 273)?, "preview offset")?;
    let preview_byte_count = one_unsigned(&mut tiff, required(&ifd0, 279)?, "preview byte count")?;
    let raw_ifd_entry = required(&ifd0, 330)?;
    let (raw_ifd_pointer_offset, raw_ifd_pointer_size) = tiff.value_location(raw_ifd_entry)?;
    if raw_ifd_pointer_size != 4 {
        return Err(invalid("Raw IFD pointer is not a single inline LONG"));
    }
    let raw_ifd_offset = one_unsigned(&mut tiff, raw_ifd_entry, "Raw IFD pointer")?;
    let raw_ifd_offset = u32::try_from(raw_ifd_offset)
        .map_err(|_| invalid("Raw IFD pointer exceeds classic TIFF range"))?;
    let raw = tiff.ifd(raw_ifd_offset)?;
    let width = usize::try_from(one_unsigned(&mut tiff, required(&raw, 256)?, "RAW width")?)
        .map_err(|_| invalid("RAW width exceeds platform range"))?;
    let height = usize::try_from(one_unsigned(&mut tiff, required(&raw, 257)?, "RAW height")?)
        .map_err(|_| invalid("RAW height exceeds platform range"))?;
    let bits_per_sample = u16::try_from(one_unsigned(
        &mut tiff,
        required(&raw, 258)?,
        "bits per sample",
    )?)
    .map_err(|_| invalid("bits per sample exceeds 16 bits"))?;
    let compression = u16::try_from(one_unsigned(
        &mut tiff,
        required(&raw, 259)?,
        "compression",
    )?)
    .map_err(|_| invalid("compression exceeds 16 bits"))?;
    let strip_offset = one_unsigned(&mut tiff, required(&raw, 273)?, "RAW strip offset")?;
    let strip_byte_count = one_unsigned(&mut tiff, required(&raw, 279)?, "RAW strip byte count")?;
    let crop_origin = pair_usize(&mut tiff, required(&raw, 50719)?, "default crop origin")?;
    let crop_size = pair_usize(&mut tiff, required(&raw, 50720)?, "default crop size")?;
    let black_level = level(&mut tiff, required(&raw, 50714)?, "black level")?;
    let white_level = level(&mut tiff, required(&raw, 50717)?, "white level")?;
    if bits_per_sample != 16 || compression != 1 {
        return Err(invalid(format!(
            "donor RAW must be uncompressed 16-bit, got bits={bits_per_sample} compression={compression}"
        )));
    }
    let expected_bytes = u64::try_from(width)
        .ok()
        .and_then(|value| value.checked_mul(u64::try_from(height).ok()?))
        .and_then(|value| value.checked_mul(2))
        .ok_or_else(|| invalid("donor RAW dimensions overflow"))?;
    if strip_byte_count != expected_bytes {
        return Err(invalid(format!(
            "RAW strip length {strip_byte_count} does not match {width}x{height}x2"
        )));
    }
    let payload_end = strip_offset
        .checked_add(strip_byte_count)
        .ok_or_else(|| invalid("RAW strip range overflow"))?;
    let preview_end = preview_offset
        .checked_add(preview_byte_count)
        .ok_or_else(|| invalid("preview range overflow"))?;
    if payload_end > file_size || preview_end > file_size {
        return Err(invalid("donor RAW or preview range exceeds file length"));
    }
    Ok(DonorLayout {
        byte_order: match tiff.endian {
            Endian::Little => "little",
            Endian::Big => "big",
        }
        .to_owned(),
        make,
        model,
        width,
        height,
        bits_per_sample,
        compression,
        strip_offset,
        strip_byte_count,
        preview_offset,
        preview_byte_count,
        raw_ifd_pointer_range: [raw_ifd_pointer_offset, raw_ifd_pointer_offset + 4],
        crop_origin,
        crop_size,
        black_level,
        white_level,
        file_size,
        software,
        raw_data_unique_id,
    })
}
