
use std::fmt::{Display, Formatter};

pub type Result<T> = std::result::Result<T, FdbError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FdbError {
    NoErr,
    EraseErr,
    ReadErr,
    WriteErr,
    NameErr,
    NameExist,
    SavedFull,
    InitFailed,
    NotFound,
    InvalidInput(String),
    Io(String),
}

impl Display for FdbError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NoErr => write!(f, "no error"),
            Self::EraseErr => write!(f, "erase error"),
            Self::ReadErr => write!(f, "read error"),
            Self::WriteErr => write!(f, "write error"),
            Self::NameErr => write!(f, "name error"),
            Self::NameExist => write!(f, "name already exists"),
            Self::SavedFull => write!(f, "saved full"),
            Self::InitFailed => write!(f, "init failed"),
            Self::NotFound => write!(f, "not found"),
            Self::InvalidInput(message) => write!(f, "invalid input: {message}"),
            Self::Io(message) => write!(f, "io error: {message}"),
        }
    }
}

impl std::error::Error for FdbError {}
