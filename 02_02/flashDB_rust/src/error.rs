use std::fmt::{Display, Formatter};

pub type Result<T> = std::result::Result<T, FdbError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FdbError {
    ReadErr,
    WriteErr,
    EraseErr,
    NameErr,
    NameExist,
    SavedFull,
    InitFailed,
    InvalidInput(String),
    Io(String),
    NotFound,
    KvErrHdr,
    SectorErrHdr,
}

impl Display for FdbError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::ReadErr => write!(f, "read error"),
            Self::WriteErr => write!(f, "write error"),
            Self::EraseErr => write!(f, "erase error"),
            Self::NameErr => write!(f, "kv name error"),
            Self::NameExist => write!(f, "kv name already exists"),
            Self::SavedFull => write!(f, "saved full"),
            Self::InitFailed => write!(f, "init failed"),
            Self::InvalidInput(msg) => write!(f, "invalid input: {msg}"),
            Self::Io(msg) => write!(f, "io error: {msg}"),
            Self::NotFound => write!(f, "not found"),
            Self::KvErrHdr => write!(f, "kv error header"),
            Self::SectorErrHdr => write!(f, "sector error header"),
        }
    }
}

impl std::error::Error for FdbError {}
