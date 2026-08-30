use std::collections::BTreeMap;
use std::fs::OpenOptions;
use std::path::Path;

use serde::Serialize;

use crate::tiff::{Entry, Tiff, invalid, required};
use crate::{Error, FujiPrivateMetadata, Result};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct UnsignedRational {
    pub numerator: u32,
    pub denominator: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct SignedRational {
    pub numerator: i32,
    pub denominator: i32,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CaptureMetadata {
    pub modify_date: String,
    pub exposure_time: UnsignedRational,
    pub f_number: UnsignedRational,
    pub exposure_program: u16,
    pub iso: u32,
    pub date_time_original: String,
    pub exposure_compensation: SignedRational,
    pub max_aperture_value: UnsignedRational,
    pub metering_mode: u16,
    pub flash: u16,
    pub focal_length: UnsignedRational,
    pub color_space: u16,
    pub focal_length_35mm: u16,
    pub lens_make: String,
    pub lens_model: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct MetadataPatch {
    pub name: String,
    pub directory: String,
    pub tag: u16,
    pub range: [u64; 2],
}

fn one_unsigned(tiff: &mut Tiff<'_>, entry: &Entry, label: &str) -> Result<u64> {
    let values = tiff.unsigneds(entry)?;
    if values.len() != 1 {
        return Err(invalid(format!("{label} must contain one value")));
    }
    Ok(values[0])
}

fn one_unsigned_rational(
    tiff: &mut Tiff<'_>,
    entry: &Entry,
    label: &str,
) -> Result<UnsignedRational> {
    let pairs = tiff.unsigned_rational_pairs(entry)?;
    if pairs.len() != 1 {
        return Err(invalid(format!("{label} must contain one rational")));
    }
    let divisor = gcd_u32(pairs[0].0, pairs[0].1);
    Ok(UnsignedRational {
        numerator: pairs[0].0 / divisor,
        denominator: pairs[0].1 / divisor,
    })
}

fn one_signed_rational(tiff: &mut Tiff<'_>, entry: &Entry, label: &str) -> Result<SignedRational> {
    let pairs = tiff.signed_rational_pairs(entry)?;
    if pairs.len() != 1 {
        return Err(invalid(format!("{label} must contain one signed rational")));
    }
    let divisor = gcd_u32(pairs[0].0.unsigned_abs(), pairs[0].1.unsigned_abs());
    let divisor = i32::try_from(divisor).map_err(|_| invalid("rational divisor exceeds i32"))?;
    Ok(SignedRational {
        numerator: pairs[0].0 / divisor,
        denominator: pairs[0].1 / divisor,
    })
}

fn gcd_u32(mut left: u32, mut right: u32) -> u32 {
    while right != 0 {
        (left, right) = (right, left % right);
    }
    left.max(1)
}

pub fn read_capture_metadata(
    path: impl AsRef<Path>,
    fuji: &FujiPrivateMetadata,
) -> Result<CaptureMetadata> {
    let path = path.as_ref();
    let mut file = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|source| Error::Io {
            operation: "open",
            path: path.to_path_buf(),
            source,
        })?;
    let file_size = file
        .metadata()
        .map_err(|source| Error::MetadataIo { source })?
        .len();
    let tiff_base = fuji
        .preview
        .offset
        .checked_add(12)
        .ok_or_else(|| invalid("RAF EXIF TIFF offset overflow"))?;
    let mut tiff = Tiff::open(&mut file, file_size, tiff_base)?;
    let ifd0 = tiff.ifd(tiff.first_ifd)?;
    let exif_offset = one_unsigned(&mut tiff, required(&ifd0, 34665)?, "Exif IFD pointer")?;
    let exif_offset = u32::try_from(exif_offset)
        .map_err(|_| invalid("Exif IFD pointer exceeds classic TIFF range"))?;
    let exif = tiff.ifd(exif_offset)?;
    let focal_length = one_unsigned_rational(&mut tiff, required(&exif, 37386)?, "focal length")?;
    let focal_mm = f64::from(focal_length.numerator) / f64::from(focal_length.denominator);
    let full_frame_diagonal = f64::hypot(36.0, 24.0);
    let gfx_diagonal = f64::hypot(43.8, 32.9);
    let focal_length_35mm =
        u16::try_from((focal_mm * full_frame_diagonal / gfx_diagonal).round() as u64)
            .map_err(|_| invalid("derived 35mm focal length exceeds 16 bits"))?;
    Ok(CaptureMetadata {
        modify_date: tiff.ascii(required(&ifd0, 306)?)?,
        exposure_time: one_unsigned_rational(&mut tiff, required(&exif, 33434)?, "exposure time")?,
        f_number: one_unsigned_rational(&mut tiff, required(&exif, 33437)?, "F-number")?,
        exposure_program: u16::try_from(one_unsigned(
            &mut tiff,
            required(&exif, 34850)?,
            "exposure program",
        )?)
        .map_err(|_| invalid("exposure program exceeds 16 bits"))?,
        iso: u32::try_from(one_unsigned(&mut tiff, required(&exif, 34855)?, "ISO")?)
            .map_err(|_| invalid("ISO exceeds 32 bits"))?,
        date_time_original: tiff.ascii(required(&exif, 36867)?)?,
        exposure_compensation: one_signed_rational(
            &mut tiff,
            required(&exif, 37380)?,
            "exposure compensation",
        )?,
        max_aperture_value: one_unsigned_rational(
            &mut tiff,
            required(&exif, 37381)?,
            "maximum aperture",
        )?,
        metering_mode: u16::try_from(one_unsigned(
            &mut tiff,
            required(&exif, 37383)?,
            "metering mode",
        )?)
        .map_err(|_| invalid("metering mode exceeds 16 bits"))?,
        flash: u16::try_from(one_unsigned(&mut tiff, required(&exif, 37385)?, "flash")?)
            .map_err(|_| invalid("flash value exceeds 16 bits"))?,
        focal_length,
        color_space: u16::try_from(one_unsigned(
            &mut tiff,
            required(&exif, 40961)?,
            "colour space",
        )?)
        .map_err(|_| invalid("colour space exceeds 16 bits"))?,
        focal_length_35mm,
        lens_make: "FUJIFILM".to_owned(),
        lens_model: "35mm F4".to_owned(),
    })
}

fn encode_ascii(entry: &Entry, value: &str) -> Result<Vec<u8>> {
    if entry.type_id != 2 {
        return Err(invalid(format!(
            "target TIFF tag 0x{:04x} is not ASCII",
            entry.tag
        )));
    }
    let mut bytes = value.as_bytes().to_vec();
    bytes.push(0);
    let count = usize::try_from(entry.count).map_err(|_| invalid("ASCII slot is too large"))?;
    if bytes.len() > count {
        return Err(invalid(format!(
            "value for TIFF tag 0x{:04x} exceeds its fixed slot",
            entry.tag
        )));
    }
    bytes.resize(count, 0);
    Ok(bytes)
}

fn encode_unsigned(tiff: &Tiff<'_>, entry: &Entry, value: u64) -> Result<Vec<u8>> {
    if entry.count != 1 {
        return Err(invalid(format!(
            "target TIFF tag 0x{:04x} is not scalar",
            entry.tag
        )));
    }
    match entry.type_id {
        1 | 7 => Ok(vec![
            u8::try_from(value).map_err(|_| invalid("value exceeds BYTE range"))?,
        ]),
        3 => Ok(tiff
            .endian
            .put_u16(u16::try_from(value).map_err(|_| invalid("value exceeds SHORT range"))?)
            .to_vec()),
        4 => Ok(tiff
            .endian
            .put_u32(u32::try_from(value).map_err(|_| invalid("value exceeds LONG range"))?)
            .to_vec()),
        other => Err(invalid(format!(
            "target scalar TIFF type {other} is unsupported"
        ))),
    }
}

fn encode_unsigned_rationals(
    tiff: &Tiff<'_>,
    entry: &Entry,
    values: &[UnsignedRational],
) -> Result<Vec<u8>> {
    if entry.type_id != 5 || usize::try_from(entry.count).ok() != Some(values.len()) {
        return Err(invalid("target RATIONAL slot has a different layout"));
    }
    let mut bytes = Vec::with_capacity(values.len() * 8);
    for value in values {
        if value.denominator == 0 {
            return Err(invalid("RATIONAL denominator is zero"));
        }
        bytes.extend(tiff.endian.put_u32(value.numerator));
        bytes.extend(tiff.endian.put_u32(value.denominator));
    }
    Ok(bytes)
}

fn encode_signed_rational(
    tiff: &Tiff<'_>,
    entry: &Entry,
    value: SignedRational,
) -> Result<Vec<u8>> {
    if entry.type_id != 10 || entry.count != 1 || value.denominator == 0 {
        return Err(invalid("target SRATIONAL slot has a different layout"));
    }
    let mut bytes = Vec::with_capacity(8);
    bytes.extend(tiff.endian.put_i32(value.numerator));
    bytes.extend(tiff.endian.put_i32(value.denominator));
    Ok(bytes)
}

fn f64_integer_ratio(value: f64) -> Result<(i128, i128)> {
    if !value.is_finite() {
        return Err(invalid("cannot encode a non-finite rational"));
    }
    if value == 0.0 {
        return Ok((0, 1));
    }
    let bits = value.to_bits();
    let sign = if bits >> 63 == 0 { 1_i128 } else { -1_i128 };
    let exponent = ((bits >> 52) & 0x7ff) as i32;
    let fraction = bits & ((1_u64 << 52) - 1);
    let (mantissa, binary_exponent) = if exponent == 0 {
        (i128::from(fraction), -1074)
    } else {
        (i128::from(fraction | (1_u64 << 52)), exponent - 1023 - 52)
    };
    if binary_exponent >= 0 {
        Ok((sign * (mantissa << binary_exponent), 1))
    } else {
        Ok((sign * mantissa, 1_i128 << -binary_exponent))
    }
}

fn limit_denominator(value: f64, maximum: i128) -> Result<UnsignedRational> {
    let (mut numerator, mut denominator) = f64_integer_ratio(value)?;
    if numerator <= 0 || denominator <= 0 {
        return Err(invalid("DNG neutral rationals must be positive"));
    }
    let (mut p0, mut q0, mut p1, mut q1) = (0_i128, 1_i128, 1_i128, 0_i128);
    while denominator != 0 {
        let quotient = numerator / denominator;
        let q2 = q0 + quotient * q1;
        if q2 > maximum {
            break;
        }
        (p0, p1) = (p1, p0 + quotient * p1);
        (q0, q1) = (q1, q2);
        (numerator, denominator) = (denominator, numerator - quotient * denominator);
    }
    let k = (maximum - q0) / q1;
    let bound1 = (p0 + k * p1, q0 + k * q1);
    let bound2 = (p1, q1);
    let difference = |bound: (i128, i128)| (value - bound.0 as f64 / bound.1 as f64).abs();
    let selected = if difference(bound2) <= difference(bound1) {
        bound2
    } else {
        bound1
    };
    Ok(UnsignedRational {
        numerator: u32::try_from(selected.0)
            .map_err(|_| invalid("limited rational numerator exceeds 32 bits"))?,
        denominator: u32::try_from(selected.1)
            .map_err(|_| invalid("limited rational denominator exceeds 32 bits"))?,
    })
}

fn patch(
    tiff: &mut Tiff<'_>,
    entries: &BTreeMap<u16, Entry>,
    directory: &str,
    tag: u16,
    name: &str,
    bytes: Vec<u8>,
) -> Result<MetadataPatch> {
    let entry = required(entries, tag)?;
    let range = tiff.write_entry(entry, &bytes)?;
    Ok(MetadataPatch {
        name: name.to_owned(),
        directory: directory.to_owned(),
        tag,
        range,
    })
}

pub fn patch_capture_and_white_balance(
    path: impl AsRef<Path>,
    capture: &CaptureMetadata,
    target_wb_coefficients: Option<[f64; 3]>,
    raw_data_id: &str,
    neutralize_donor_lens: bool,
) -> Result<Vec<MetadataPatch>> {
    let path = path.as_ref();
    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .map_err(|source| Error::Io {
            operation: "open",
            path: path.to_path_buf(),
            source,
        })?;
    let file_size = file
        .metadata()
        .map_err(|source| Error::MetadataIo { source })?
        .len();
    let mut tiff = Tiff::open(&mut file, file_size, 0)?;
    let ifd0 = tiff.ifd(tiff.first_ifd)?;
    let exif_offset = one_unsigned(&mut tiff, required(&ifd0, 34665)?, "Exif IFD pointer")?;
    let exif = tiff.ifd(
        u32::try_from(exif_offset)
            .map_err(|_| invalid("Exif IFD pointer exceeds classic TIFF range"))?,
    )?;
    let mut patches = Vec::new();
    macro_rules! ascii_patch {
        ($entries:expr, $directory:expr, $tag:expr, $name:expr, $value:expr) => {{
            let entry = required($entries, $tag)?;
            let bytes = encode_ascii(entry, $value)?;
            patches.push(patch(&mut tiff, $entries, $directory, $tag, $name, bytes)?);
        }};
    }
    macro_rules! unsigned_patch {
        ($entries:expr, $directory:expr, $tag:expr, $name:expr, $value:expr) => {{
            let entry = required($entries, $tag)?;
            let bytes = encode_unsigned(&tiff, entry, u64::from($value))?;
            patches.push(patch(&mut tiff, $entries, $directory, $tag, $name, bytes)?);
        }};
    }
    macro_rules! urational_patch {
        ($entries:expr, $directory:expr, $tag:expr, $name:expr, $value:expr) => {{
            let entry = required($entries, $tag)?;
            let bytes = encode_unsigned_rationals(&tiff, entry, &[$value])?;
            patches.push(patch(&mut tiff, $entries, $directory, $tag, $name, bytes)?);
        }};
    }
    ascii_patch!(&ifd0, "IFD0", 306, "ModifyDate", &capture.modify_date);
    urational_patch!(
        &exif,
        "ExifIFD",
        33434,
        "ExposureTime",
        capture.exposure_time
    );
    urational_patch!(&exif, "ExifIFD", 33437, "FNumber", capture.f_number);
    unsigned_patch!(
        &exif,
        "ExifIFD",
        34850,
        "ExposureProgram",
        capture.exposure_program
    );
    unsigned_patch!(&exif, "ExifIFD", 34855, "ISO", capture.iso);
    ascii_patch!(
        &exif,
        "ExifIFD",
        36867,
        "DateTimeOriginal",
        &capture.date_time_original
    );
    let exposure_entry = required(&exif, 37380)?;
    let exposure_bytes =
        encode_signed_rational(&tiff, exposure_entry, capture.exposure_compensation)?;
    patches.push(patch(
        &mut tiff,
        &exif,
        "ExifIFD",
        37380,
        "ExposureCompensation",
        exposure_bytes,
    )?);
    urational_patch!(
        &exif,
        "ExifIFD",
        37381,
        "MaxApertureValue",
        capture.max_aperture_value
    );
    unsigned_patch!(
        &exif,
        "ExifIFD",
        37383,
        "MeteringMode",
        capture.metering_mode
    );
    unsigned_patch!(&exif, "ExifIFD", 37385, "Flash", capture.flash);
    urational_patch!(&exif, "ExifIFD", 37386, "FocalLength", capture.focal_length);
    unsigned_patch!(&exif, "ExifIFD", 40961, "ColorSpace", capture.color_space);
    unsigned_patch!(
        &exif,
        "ExifIFD",
        41989,
        "FocalLengthIn35mmFormat",
        capture.focal_length_35mm
    );
    let image_unique_id = raw_data_id.to_ascii_uppercase();
    ascii_patch!(&exif, "ExifIFD", 42016, "ImageUniqueID", &image_unique_id);
    ascii_patch!(&exif, "ExifIFD", 42035, "LensMake", &capture.lens_make);
    ascii_patch!(&exif, "ExifIFD", 42036, "LensModel", &capture.lens_model);

    let raw_id_entry = required(&ifd0, 50781)?;
    if !matches!(raw_id_entry.type_id, 1 | 7) || raw_id_entry.count != 16 || raw_data_id.len() != 32
    {
        return Err(invalid("RawDataUniqueID target slot or value is invalid"));
    }
    let raw_id = hex::decode(raw_data_id)
        .map_err(|_| invalid("raw payload MD5 is not a 16-byte hexadecimal value"))?;
    patches.push(patch(
        &mut tiff,
        &ifd0,
        "IFD0",
        50781,
        "RawDataUniqueID",
        raw_id,
    )?);

    if let Some(target_wb_coefficients) = target_wb_coefficients {
        if target_wb_coefficients
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        {
            return Err(invalid("target white balance must be positive and finite"));
        }
        let neutral = [
            limit_denominator(
                target_wb_coefficients[1] / target_wb_coefficients[0],
                1_000_000,
            )?,
            UnsignedRational {
                numerator: 1,
                denominator: 1,
            },
            limit_denominator(
                target_wb_coefficients[1] / target_wb_coefficients[2],
                1_000_000,
            )?,
        ];
        let neutral_entry = required(&ifd0, 50728)?;
        let neutral_bytes = encode_unsigned_rationals(&tiff, neutral_entry, &neutral)?;
        patches.push(patch(
            &mut tiff,
            &ifd0,
            "IFD0",
            50728,
            "AsShotNeutral",
            neutral_bytes,
        )?);
    }

    if neutralize_donor_lens {
        let maker_entry = required(&exif, 37500)?;
        if maker_entry.type_id != 7 {
            return Err(invalid("Hasselblad MakerNote has an unsupported layout"));
        }
        let (maker_offset, _) = tiff.value_location(maker_entry)?;
        let maker_offset = u32::try_from(maker_offset)
            .map_err(|_| invalid("MakerNote offset exceeds classic TIFF range"))?;
        let maker = tiff.ifd(maker_offset)?;
        if maker.contains_key(&0xff18) {
            return Err(invalid("neutralized MakerNote tag already exists"));
        }
        let lens_entry = required(&maker, 0x0018)?;
        if lens_entry.type_id != 7 || lens_entry.count != 17 {
            return Err(invalid(
                "Hasselblad lens-dispatch tag layout is unsupported",
            ));
        }
        let range = tiff.write_at(lens_entry.entry_offset, &tiff.endian.put_u16(0xff18))?;
        patches.push(MetadataPatch {
            name: "XCDLensCorrectionDispatch".to_owned(),
            directory: "HasselbladMakerNote".to_owned(),
            tag: 0x0018,
            range,
        });
    }
    tiff.sync()?;
    Ok(patches)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fraction_limit_matches_python_reference_values() {
        assert_eq!(
            limit_denominator(1.0 / 1.9043017571464003, 1_000_000).unwrap(),
            UnsignedRational {
                numerator: 324844,
                denominator: 618601,
            }
        );
        assert_eq!(
            limit_denominator(1.0 / 3.214468273784621, 1_000_000).unwrap(),
            UnsignedRational {
                numerator: 239061,
                denominator: 768454,
            }
        );
    }
}
