use std::path::PathBuf;

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("conversion cancelled")]
    Cancelled,
    #[error("cannot decode RAF {path}: {source}")]
    Decode {
        path: PathBuf,
        #[source]
        source: rawler::RawlerError,
    },
    #[error("expected a Fujifilm GFX100RF RAF, got {make} {model}")]
    UnsupportedCamera { make: String, model: String },
    #[error("RAF contains floating-point RAW samples")]
    FloatingPointRaw,
    #[error("invalid source metadata: {0}")]
    InvalidMetadata(String),
    #[error("cannot read RAF metadata: {source}")]
    MetadataIo {
        #[source]
        source: std::io::Error,
    },
    #[error("cannot {operation} {path}: {source}")]
    Io {
        operation: &'static str,
        path: PathBuf,
        #[source]
        source: std::io::Error,
    },
}

pub type Result<T> = std::result::Result<T, Error>;
