use std::collections::BTreeMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom, Write};

use crate::{Error, Result};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum Endian {
    Little,
    Big,
}

impl Endian {
    pub(crate) fn u16(self, bytes: [u8; 2]) -> u16 {
        match self {
            Self::Little => u16::from_le_bytes(bytes),
            Self::Big => u16::from_be_bytes(bytes),
        }
    }

    pub(crate) fn u32(self, bytes: [u8; 4]) -> u32 {
        match self {
            Self::Little => u32::from_le_bytes(bytes),
            Self::Big => u32::from_be_bytes(bytes),
        }
    }

    pub(crate) fn i32(self, bytes: [u8; 4]) -> i32 {
        match self {
            Self::Little => i32::from_le_bytes(bytes),
            Self::Big => i32::from_be_bytes(bytes),
        }
    }

    pub(crate) fn put_u16(self, value: u16) -> [u8; 2] {
        match self {
            Self::Little => value.to_le_bytes(),
            Self::Big => value.to_be_bytes(),
        }
    }

    pub(crate) fn put_u32(self, value: u32) -> [u8; 4] {
        match self {
            Self::Little => value.to_le_bytes(),
            Self::Big => value.to_be_bytes(),
        }
    }

    pub(crate) fn put_i32(self, value: i32) -> [u8; 4] {
        match self {
            Self::Little => value.to_le_bytes(),
            Self::Big => value.to_be_bytes(),
        }
    }
}

#[derive(Clone, Debug)]
pub(crate) struct Entry {
    pub(crate) tag: u16,
    pub(crate) type_id: u16,
    pub(crate) count: u32,
    pub(crate) value_or_offset: [u8; 4],
    pub(crate) entry_offset: u64,
}

pub(crate) struct Tiff<'a> {
    file: &'a mut File,
    pub(crate) file_length: u64,
    pub(crate) base: u64,
    pub(crate) endian: Endian,
    pub(crate) first_ifd: u32,
}

impl<'a> Tiff<'a> {
    pub(crate) fn open(file: &'a mut File, file_length: u64, base: u64) -> Result<Self> {
        let header = read_at(file, file_length, base, 8)?;
        let endian = match &header[0..2] {
            b"II" => Endian::Little,
            b"MM" => Endian::Big,
            _ => return Err(invalid("file is not a classic TIFF")),
        };
        if endian.u16([header[2], header[3]]) != 42 {
            return Err(invalid("TIFF has unsupported magic"));
        }
        let first_ifd = endian.u32([header[4], header[5], header[6], header[7]]);
        Ok(Self {
            file,
            file_length,
            base,
            endian,
            first_ifd,
        })
    }

    pub(crate) fn ifd(&mut self, relative_offset: u32) -> Result<BTreeMap<u16, Entry>> {
        let offset = self
            .base
            .checked_add(u64::from(relative_offset))
            .ok_or_else(|| invalid("TIFF IFD offset overflow"))?;
        let count_bytes = read_at(self.file, self.file_length, offset, 2)?;
        let count = self.endian.u16([count_bytes[0], count_bytes[1]]);
        if count > 4096 {
            return Err(invalid("TIFF IFD has too many entries"));
        }
        let raw = read_at(
            self.file,
            self.file_length,
            offset + 2,
            usize::from(count) * 12,
        )?;
        let (chunks, remainder) = raw.as_chunks::<12>();
        if !remainder.is_empty() {
            return Err(invalid("TIFF IFD entry table is misaligned"));
        }
        let mut entries = BTreeMap::new();
        for (index, chunk) in chunks.iter().enumerate() {
            let tag = self.endian.u16([chunk[0], chunk[1]]);
            let type_id = self.endian.u16([chunk[2], chunk[3]]);
            let count = self.endian.u32([chunk[4], chunk[5], chunk[6], chunk[7]]);
            let value_or_offset = [chunk[8], chunk[9], chunk[10], chunk[11]];
            let entry_offset = offset + 2 + u64::try_from(index * 12).unwrap();
            if entries
                .insert(
                    tag,
                    Entry {
                        tag,
                        type_id,
                        count,
                        value_or_offset,
                        entry_offset,
                    },
                )
                .is_some()
            {
                return Err(invalid(format!("duplicate TIFF tag 0x{tag:04x}")));
            }
        }
        Ok(entries)
    }

    pub(crate) fn bytes(&mut self, entry: &Entry) -> Result<Vec<u8>> {
        let size = value_size(entry)?;
        if size <= 4 {
            return Ok(entry.value_or_offset[..size].to_vec());
        }
        let relative = self.endian.u32(entry.value_or_offset);
        let offset = self
            .base
            .checked_add(u64::from(relative))
            .ok_or_else(|| invalid("TIFF payload offset overflow"))?;
        read_at(self.file, self.file_length, offset, size)
    }

    pub(crate) fn value_location(&self, entry: &Entry) -> Result<(u64, usize)> {
        let size = value_size(entry)?;
        if size <= 4 {
            return Ok((entry.entry_offset + 8, size));
        }
        let relative = self.endian.u32(entry.value_or_offset);
        let offset = self
            .base
            .checked_add(u64::from(relative))
            .ok_or_else(|| invalid("TIFF payload offset overflow"))?;
        let end = offset
            .checked_add(u64::try_from(size).unwrap())
            .ok_or_else(|| invalid("TIFF payload range overflow"))?;
        if end > self.file_length {
            return Err(invalid("TIFF payload exceeds file length"));
        }
        Ok((offset, size))
    }

    pub(crate) fn unsigneds(&mut self, entry: &Entry) -> Result<Vec<u64>> {
        let endian = self.endian;
        let bytes = self.bytes(entry)?;
        match entry.type_id {
            1 | 7 => Ok(bytes.into_iter().map(u64::from).collect()),
            3 => {
                let (chunks, remainder) = bytes.as_chunks::<2>();
                if !remainder.is_empty() {
                    return Err(invalid("TIFF SHORT payload is misaligned"));
                }
                Ok(chunks
                    .iter()
                    .map(|chunk| u64::from(endian.u16(*chunk)))
                    .collect())
            }
            4 | 13 => {
                let (chunks, remainder) = bytes.as_chunks::<4>();
                if !remainder.is_empty() {
                    return Err(invalid("TIFF LONG payload is misaligned"));
                }
                Ok(chunks
                    .iter()
                    .map(|chunk| u64::from(endian.u32(*chunk)))
                    .collect())
            }
            other => Err(invalid(format!(
                "TIFF tag 0x{:04x} has non-unsigned type {other}",
                entry.tag
            ))),
        }
    }

    pub(crate) fn unsigned_rationals(&mut self, entry: &Entry) -> Result<Vec<f64>> {
        Ok(self
            .unsigned_rational_pairs(entry)?
            .into_iter()
            .map(|(numerator, denominator)| f64::from(numerator) / f64::from(denominator))
            .collect())
    }

    pub(crate) fn unsigned_rational_pairs(&mut self, entry: &Entry) -> Result<Vec<(u32, u32)>> {
        if entry.type_id != 5 {
            return Err(invalid(format!(
                "TIFF tag 0x{:04x} is not RATIONAL",
                entry.tag
            )));
        }
        let endian = self.endian;
        let bytes = self.bytes(entry)?;
        let (chunks, remainder) = bytes.as_chunks::<8>();
        if !remainder.is_empty() {
            return Err(invalid("TIFF RATIONAL payload is misaligned"));
        }
        chunks
            .iter()
            .map(|chunk| {
                let numerator = endian.u32(chunk[0..4].try_into().unwrap());
                let denominator = endian.u32(chunk[4..8].try_into().unwrap());
                if denominator == 0 {
                    return Err(invalid("TIFF RATIONAL has a zero denominator"));
                }
                Ok((numerator, denominator))
            })
            .collect()
    }

    pub(crate) fn signed_rationals(&mut self, entry: &Entry) -> Result<Vec<f64>> {
        Ok(self
            .signed_rational_pairs(entry)?
            .into_iter()
            .map(|(numerator, denominator)| f64::from(numerator) / f64::from(denominator))
            .collect())
    }

    pub(crate) fn signed_rational_pairs(&mut self, entry: &Entry) -> Result<Vec<(i32, i32)>> {
        if entry.type_id != 10 {
            return Err(invalid(format!(
                "TIFF tag 0x{:04x} is not SRATIONAL",
                entry.tag
            )));
        }
        let endian = self.endian;
        let bytes = self.bytes(entry)?;
        let (chunks, remainder) = bytes.as_chunks::<8>();
        if !remainder.is_empty() {
            return Err(invalid("TIFF SRATIONAL payload is misaligned"));
        }
        chunks
            .iter()
            .map(|chunk| {
                let numerator = endian.i32(chunk[0..4].try_into().unwrap());
                let denominator = endian.i32(chunk[4..8].try_into().unwrap());
                if denominator == 0 {
                    return Err(invalid("TIFF SRATIONAL has a zero denominator"));
                }
                Ok((numerator, denominator))
            })
            .collect()
    }

    pub(crate) fn ascii(&mut self, entry: &Entry) -> Result<String> {
        if entry.type_id != 2 {
            return Err(invalid(format!(
                "TIFF tag 0x{:04x} is not ASCII",
                entry.tag
            )));
        }
        let mut bytes = self.bytes(entry)?;
        while bytes.last() == Some(&0) {
            bytes.pop();
        }
        String::from_utf8(bytes).map_err(|_| invalid("TIFF ASCII value is not UTF-8"))
    }

    pub(crate) fn write_entry(&mut self, entry: &Entry, bytes: &[u8]) -> Result<[u64; 2]> {
        let (offset, size) = self.value_location(entry)?;
        if bytes.len() != size {
            return Err(invalid(format!(
                "encoded TIFF tag 0x{:04x} length {} differs from fixed slot {size}",
                entry.tag,
                bytes.len()
            )));
        }
        self.file
            .seek(SeekFrom::Start(offset))
            .and_then(|_| self.file.write_all(bytes))
            .map_err(|source| Error::MetadataIo { source })?;
        Ok([offset, offset + u64::try_from(size).unwrap()])
    }

    pub(crate) fn write_at(&mut self, offset: u64, bytes: &[u8]) -> Result<[u64; 2]> {
        let end = offset
            .checked_add(u64::try_from(bytes.len()).unwrap())
            .ok_or_else(|| invalid("TIFF write range overflow"))?;
        if end > self.file_length {
            return Err(invalid("TIFF write range exceeds file length"));
        }
        self.file
            .seek(SeekFrom::Start(offset))
            .and_then(|_| self.file.write_all(bytes))
            .map_err(|source| Error::MetadataIo { source })?;
        Ok([offset, end])
    }

    pub(crate) fn sync(&mut self) -> Result<()> {
        self.file
            .sync_all()
            .map_err(|source| Error::MetadataIo { source })
    }
}

pub(crate) fn required(entries: &BTreeMap<u16, Entry>, tag: u16) -> Result<&Entry> {
    entries
        .get(&tag)
        .ok_or_else(|| invalid(format!("required TIFF tag 0x{tag:04x} is missing")))
}

fn value_size(entry: &Entry) -> Result<usize> {
    let item_size = match entry.type_id {
        1 | 2 | 7 => 1_u64,
        3 => 2,
        4 | 9 | 11 | 13 => 4,
        5 | 10 | 12 => 8,
        other => return Err(invalid(format!("unsupported TIFF type {other}"))),
    };
    let size = item_size
        .checked_mul(u64::from(entry.count))
        .ok_or_else(|| invalid("TIFF value length overflow"))?;
    usize::try_from(size).map_err(|_| invalid("TIFF value is too large"))
}

pub(crate) fn invalid(message: impl Into<String>) -> Error {
    Error::InvalidMetadata(message.into())
}

pub(crate) fn read_at(
    file: &mut File,
    file_length: u64,
    offset: u64,
    length: usize,
) -> Result<Vec<u8>> {
    let end = offset
        .checked_add(u64::try_from(length).map_err(|_| invalid("read length overflow"))?)
        .ok_or_else(|| invalid("read range overflow"))?;
    if end > file_length {
        return Err(invalid(format!(
            "metadata range {offset}..{end} exceeds file length {file_length}"
        )));
    }
    file.seek(SeekFrom::Start(offset))
        .map_err(|source| Error::MetadataIo { source })?;
    let mut bytes = vec![0; length];
    file.read_exact(&mut bytes)
        .map_err(|source| Error::MetadataIo { source })?;
    Ok(bytes)
}
