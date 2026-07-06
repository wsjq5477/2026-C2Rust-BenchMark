use std::fs;
use std::path::PathBuf;

use crate::{FdbError, Result};

const FDB_BYTE_ERASED: u8 = 0xFF;

pub trait FlashStorage {
    fn read(&self, addr: u32, buf: &mut [u8]) -> Result<()>;
    fn write(&mut self, addr: u32, data: &[u8]) -> Result<()>;
    fn erase(&mut self, addr: u32, size: u32) -> Result<()>;
    fn sector_size(&self) -> u32;
    fn total_size(&self) -> u32;
}

pub struct MemFlash {
    data: Vec<u8>,
    sector_size: u32,
    sector_count: u32,
}

impl MemFlash {
    pub fn new(sector_size: u32, sector_count: u32) -> Self {
        let total_size = sector_size * sector_count;
        Self {
            data: vec![FDB_BYTE_ERASED; total_size as usize],
            sector_size,
            sector_count,
        }
    }

    pub fn sector_count(&self) -> u32 {
        self.sector_count
    }
}

impl FlashStorage for MemFlash {
    fn read(&self, addr: u32, buf: &mut [u8]) -> Result<()> {
        let total = self.total_size();
        if addr + buf.len() as u32 > total {
            return Err(FdbError::InvalidInput(format!(
                "read out of bounds: addr {} + len {} > total {}",
                addr,
                buf.len(),
                total
            )));
        }
        let start = addr as usize;
        buf.copy_from_slice(&self.data[start..start + buf.len()]);
        Ok(())
    }

    fn write(&mut self, addr: u32, data: &[u8]) -> Result<()> {
        let total = self.total_size();
        if addr + data.len() as u32 > total {
            return Err(FdbError::InvalidInput(format!(
                "write out of bounds: addr {} + len {} > total {}",
                addr,
                data.len(),
                total
            )));
        }
        let start = addr as usize;
        for i in 0..data.len() {
            if self.data[start + i] != FDB_BYTE_ERASED {
                return Err(FdbError::InvalidInput(format!(
                    "write to non-erased byte at addr {}: current 0x{:02X}",
                    addr + i as u32,
                    self.data[start + i]
                )));
            }
        }
        self.data[start..start + data.len()].copy_from_slice(data);
        Ok(())
    }

    fn erase(&mut self, addr: u32, size: u32) -> Result<()> {
        let total = self.total_size();
        if addr + size > total {
            return Err(FdbError::InvalidInput(format!(
                "erase out of bounds: addr {} + size {} > total {}",
                addr,
                size,
                total
            )));
        }
        let start = addr as usize;
        let end = start + size as usize;
        for b in &mut self.data[start..end] {
            *b = FDB_BYTE_ERASED;
        }
        Ok(())
    }

    fn sector_size(&self) -> u32 {
        self.sector_size
    }

    fn total_size(&self) -> u32 {
        self.sector_size * self.sector_count
    }
}

pub struct FileFlash {
    file_path: PathBuf,
    cache: Vec<u8>,
    sector_size: u32,
    total_size: u32,
}

impl FileFlash {
    pub fn new(file_path: PathBuf, sector_size: u32, total_size: u32) -> Result<Self> {
        let cache = if file_path.exists() {
            fs::read(&file_path).map_err(|e| FdbError::Io(e.to_string()))?
        } else {
            vec![FDB_BYTE_ERASED; total_size as usize]
        };
        if cache.len() != total_size as usize {
            return Err(FdbError::InvalidInput(format!(
                "file size {} does not match total_size {}",
                cache.len(),
                total_size
            )));
        }
        Ok(Self {
            file_path,
            cache,
            sector_size,
            total_size,
        })
    }

    fn flush(&self) -> Result<()> {
        fs::write(&self.file_path, &self.cache).map_err(|e| FdbError::Io(e.to_string()))
    }
}

impl FlashStorage for FileFlash {
    fn read(&self, addr: u32, buf: &mut [u8]) -> Result<()> {
        let total = self.total_size();
        if addr + buf.len() as u32 > total {
            return Err(FdbError::InvalidInput(format!(
                "read out of bounds: addr {} + len {} > total {}",
                addr,
                buf.len(),
                total
            )));
        }
        let start = addr as usize;
        buf.copy_from_slice(&self.cache[start..start + buf.len()]);
        Ok(())
    }

    fn write(&mut self, addr: u32, data: &[u8]) -> Result<()> {
        let total = self.total_size();
        if addr + data.len() as u32 > total {
            return Err(FdbError::InvalidInput(format!(
                "write out of bounds: addr {} + len {} > total {}",
                addr,
                data.len(),
                total
            )));
        }
        let start = addr as usize;
        for i in 0..data.len() {
            if self.cache[start + i] != FDB_BYTE_ERASED {
                return Err(FdbError::InvalidInput(format!(
                    "write to non-erased byte at addr {}: current 0x{:02X}",
                    addr + i as u32,
                    self.cache[start + i]
                )));
            }
        }
        self.cache[start..start + data.len()].copy_from_slice(data);
        self.flush()?;
        Ok(())
    }

    fn erase(&mut self, addr: u32, size: u32) -> Result<()> {
        let total = self.total_size();
        if addr + size > total {
            return Err(FdbError::InvalidInput(format!(
                "erase out of bounds: addr {} + size {} > total {}",
                addr,
                size,
                total
            )));
        }
        let start = addr as usize;
        let end = start + size as usize;
        for b in &mut self.cache[start..end] {
            *b = FDB_BYTE_ERASED;
        }
        self.flush()?;
        Ok(())
    }

    fn sector_size(&self) -> u32 {
        self.sector_size
    }

    fn total_size(&self) -> u32 {
        self.total_size
    }
}
