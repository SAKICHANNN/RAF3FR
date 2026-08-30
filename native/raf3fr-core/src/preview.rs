use std::fs::{File, OpenOptions};
use std::io::{Cursor, Read, Seek, SeekFrom};
use std::path::Path;

use image::codecs::jpeg::JpegEncoder;
use image::imageops::FilterType;
use image::{ColorType, ImageFormat};
use serde::Serialize;
use sha2::{Digest, Sha256};

use crate::tiff::{Tiff, invalid, required};
use crate::{DonorLayout, Error, PreviewLocation, Result};

const QUALITY_STEPS: [u8; 8] = [85, 75, 65, 60, 55, 50, 45, 40];

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct PreviewEmbedReport {
    pub source_range: [u64; 2],
    pub source_byte_count: u64,
    pub source_sha256: String,
    pub encoded_byte_count: u64,
    pub encoded_sha256: String,
    pub quality: u8,
    pub dimensions: [u32; 2],
    pub destination_range: [u64; 2],
    pub destination_capacity: u64,
    pub byte_count_patch_range: [u64; 2],
}

fn io_error(operation: &'static str, path: &Path, source: std::io::Error) -> Error {
    Error::Io {
        operation,
        path: path.to_path_buf(),
        source,
    }
}

fn digest(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}

fn encode_to_capacity(
    source: &[u8],
    capacity: usize,
    target_dimensions: [u32; 2],
) -> Result<(Vec<u8>, u8, [u32; 2])> {
    let source_image = image::load_from_memory_with_format(source, ImageFormat::Jpeg)
        .map_err(|error| invalid(format!("failed to decode RAF JPEG preview: {error}")))?
        .to_rgb8();
    let image = if [source_image.width(), source_image.height()] == target_dimensions {
        source_image
    } else {
        image::imageops::resize(
            &source_image,
            target_dimensions[0],
            target_dimensions[1],
            FilterType::Lanczos3,
        )
    };
    let dimensions = [image.width(), image.height()];
    for quality in QUALITY_STEPS {
        let mut encoded = Vec::new();
        JpegEncoder::new_with_quality(&mut encoded, quality)
            .encode(
                image.as_raw(),
                image.width(),
                image.height(),
                ColorType::Rgb8.into(),
            )
            .map_err(|error| invalid(format!("failed to encode JPEG preview: {error}")))?;
        if encoded.len() <= capacity {
            return Ok((encoded, quality, dimensions));
        }
    }
    Err(invalid(format!(
        "RAF preview cannot fit in donor preview slot of {capacity} bytes"
    )))
}

pub fn embed_source_preview(
    source_path: impl AsRef<Path>,
    output_path: impl AsRef<Path>,
    source_preview: PreviewLocation,
    donor: &DonorLayout,
) -> Result<PreviewEmbedReport> {
    let source_path = source_path.as_ref();
    let output_path = output_path.as_ref();
    let mut source =
        File::open(source_path).map_err(|error| io_error("open", source_path, error))?;
    let source_length = source
        .metadata()
        .map_err(|error| io_error("inspect", source_path, error))?
        .len();
    let source_end = source_preview
        .offset
        .checked_add(source_preview.length)
        .ok_or_else(|| invalid("RAF preview range overflow"))?;
    if source_end > source_length {
        return Err(invalid("RAF preview exceeds source file length"));
    }
    let mut source_bytes = vec![
        0_u8;
        usize::try_from(source_preview.length).map_err(|_| invalid(
            "RAF preview is too large for this platform"
        ))?
    ];
    source
        .seek(SeekFrom::Start(source_preview.offset))
        .and_then(|_| source.read_exact(&mut source_bytes))
        .map_err(|error| io_error("read preview from", source_path, error))?;
    let mut output = OpenOptions::new()
        .read(true)
        .write(true)
        .open(output_path)
        .map_err(|error| io_error("open", output_path, error))?;
    let output_length = output
        .metadata()
        .map_err(|error| io_error("inspect", output_path, error))?
        .len();
    if output_length != donor.file_size {
        return Err(invalid("output length no longer matches donor layout"));
    }
    let mut tiff = Tiff::open(&mut output, output_length, 0)?;
    let ifd0 = tiff.ifd(tiff.first_ifd)?;
    let preview_width = tiff.unsigneds(required(&ifd0, 256)?)?;
    let preview_height = tiff.unsigneds(required(&ifd0, 257)?)?;
    if preview_width.len() != 1 || preview_height.len() != 1 {
        return Err(invalid("preview dimensions must each contain one value"));
    }
    let target_dimensions = [
        u32::try_from(preview_width[0])
            .map_err(|_| invalid("preview width exceeds JPEG limits"))?,
        u32::try_from(preview_height[0])
            .map_err(|_| invalid("preview height exceeds JPEG limits"))?,
    ];
    if target_dimensions.contains(&0) {
        return Err(invalid("preview dimensions must be positive"));
    }
    let source_sha256 = digest(&source_bytes);
    let capacity = usize::try_from(donor.preview_byte_count)
        .map_err(|_| invalid("donor preview slot is too large for this platform"))?;
    let (encoded, quality, dimensions) =
        encode_to_capacity(&source_bytes, capacity, target_dimensions)?;
    let encoded_sha256 = digest(&encoded);

    let byte_count_entry = required(&ifd0, 279)?;
    if byte_count_entry.type_id != 4 || byte_count_entry.count != 1 {
        return Err(invalid("preview byte count is not a single LONG"));
    }
    let byte_count = u32::try_from(encoded.len())
        .map_err(|_| invalid("encoded preview exceeds classic TIFF range"))?;
    let byte_count_patch_range =
        tiff.write_entry(byte_count_entry, &tiff.endian.put_u32(byte_count))?;

    let mut slot = Cursor::new(vec![0_u8; capacity]);
    std::io::Write::write_all(&mut slot, &encoded)
        .map_err(|error| io_error("prepare preview for", output_path, error))?;
    let destination_range = tiff.write_at(donor.preview_offset, slot.get_ref())?;
    tiff.sync()?;

    Ok(PreviewEmbedReport {
        source_range: [source_preview.offset, source_end],
        source_byte_count: source_preview.length,
        source_sha256,
        encoded_byte_count: u64::try_from(encoded.len()).unwrap(),
        encoded_sha256,
        quality,
        dimensions,
        destination_range,
        destination_capacity: donor.preview_byte_count,
        byte_count_patch_range,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgb, RgbImage};

    #[test]
    fn preview_encoder_is_deterministic_and_respects_capacity() {
        let mut source = Vec::new();
        let image = RgbImage::from_fn(64, 48, |x, y| {
            Rgb([(x * 3) as u8, (y * 5) as u8, (x + y) as u8])
        });
        JpegEncoder::new_with_quality(&mut source, 95)
            .encode(
                image.as_raw(),
                image.width(),
                image.height(),
                ColorType::Rgb8.into(),
            )
            .unwrap();
        let first = encode_to_capacity(&source, source.len(), [64, 48]).unwrap();
        let second = encode_to_capacity(&source, source.len(), [64, 48]).unwrap();
        assert_eq!(first, second);
        assert!(first.0.len() <= source.len());
        assert_eq!(first.2, [64, 48]);
    }

    #[test]
    fn preview_encoder_matches_declared_target_dimensions() {
        let mut source = Vec::new();
        let image = RgbImage::from_pixel(64, 48, Rgb([12, 34, 56]));
        JpegEncoder::new_with_quality(&mut source, 95)
            .encode(
                image.as_raw(),
                image.width(),
                image.height(),
                ColorType::Rgb8.into(),
            )
            .unwrap();
        let encoded = encode_to_capacity(&source, source.len(), [48, 36]).unwrap();
        let decoded = image::load_from_memory_with_format(&encoded.0, ImageFormat::Jpeg).unwrap();
        assert_eq!(encoded.2, [48, 36]);
        assert_eq!([decoded.width(), decoded.height()], [48, 36]);
    }
}
