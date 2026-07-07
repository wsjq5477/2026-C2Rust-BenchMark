use crate::{FdbError, Result};

pub trait FlashStorage {
    fn sector_size(&self) -> u32;
    fn sectors_count(&self) -> u32;
    fn read(&self, addr: u32, len: u32) -> Result<Vec<u8>>;
    fn write(&mut self, addr: u32, data: &[u8]) -> Result<()>;
    fn erase_sector(&mut self, sector_idx: u32) -> Result<()>;
}

#[derive(Debug, Clone)]
pub struct MemFlash {
    sectors: Vec<Vec<u8>>,
    sec_size: u32,
}

impl MemFlash {
    pub fn new(sec_size: u32, sectors_count: u32) -> Self {
        let sectors = (0..sectors_count)
            .map(|_| vec![0xFF; sec_size as usize])
            .collect();
        Self { sectors, sec_size }
    }
}

impl FlashStorage for MemFlash {
    fn sector_size(&self) -> u32 {
        self.sec_size
    }

    fn sectors_count(&self) -> u32 {
        self.sectors.len() as u32
    }

    fn read(&self, addr: u32, len: u32) -> Result<Vec<u8>> {
        if addr + len > self.sectors.len() as u32 * self.sec_size {
            return Err(FdbError::ReadErr);
        }
        let sec_idx = (addr / self.sec_size) as usize;
        let offset = (addr % self.sec_size) as usize;
        let mut result = Vec::with_capacity(len as usize);
        let mut remaining = len as usize;
        let mut cur_sec = sec_idx;
        let mut cur_offset = offset;
        while remaining > 0 && cur_sec < self.sectors.len() {
            let available = self.sectors[cur_sec].len() - cur_offset;
            let chunk_len = remaining.min(available);
            result.extend_from_slice(&self.sectors[cur_sec][cur_offset..cur_offset + chunk_len]);
            remaining -= chunk_len;
            cur_sec += 1;
            cur_offset = 0;
        }
        Ok(result)
    }

    fn write(&mut self, addr: u32, data: &[u8]) -> Result<()> {
        if addr as usize + data.len() > self.sectors.len() * self.sec_size as usize {
            return Err(FdbError::WriteErr);
        }
        let mut cur_addr = addr;
        for &byte in data {
            let sec_idx = (cur_addr / self.sec_size) as usize;
            let offset = (cur_addr % self.sec_size) as usize;
            self.sectors[sec_idx][offset] &= byte;
            cur_addr += 1;
        }
        Ok(())
    }

    fn erase_sector(&mut self, sector_idx: u32) -> Result<()> {
        if sector_idx as usize >= self.sectors.len() {
            return Err(FdbError::EraseErr);
        }
        self.sectors[sector_idx as usize] = vec![0xFF; self.sec_size as usize];
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct FileFlash {
    dir: String,
    name: String,
    sec_size: u32,
    sectors_count: u32,
}

impl FileFlash {
    pub fn new(dir: impl AsRef<str>, name: impl AsRef<str>, sec_size: u32, sectors_count: u32) -> Self {
        Self {
            dir: dir.as_ref().to_string(),
            name: name.as_ref().to_string(),
            sec_size,
            sectors_count,
        }
    }

    fn sector_path(&self, sector_idx: u32) -> std::path::PathBuf {
        std::path::PathBuf::from(format!("{}/{}.fdb.{}", self.dir, self.name, sector_idx))
    }

    fn ensure_dir(&self) -> Result<()> {
        std::fs::create_dir_all(&self.dir).map_err(|e| FdbError::Io(e.to_string()))
    }
}

impl FlashStorage for FileFlash {
    fn sector_size(&self) -> u32 {
        self.sec_size
    }

    fn sectors_count(&self) -> u32 {
        self.sectors_count
    }

    fn read(&self, addr: u32, len: u32) -> Result<Vec<u8>> {
        let sec_idx = addr / self.sec_size;
        let offset = (addr % self.sec_size) as usize;
        let path = self.sector_path(sec_idx);
        let data = std::fs::read(&path).map_err(|e| FdbError::Io(e.to_string()))?;
        let end = offset + len as usize;
        if end > data.len() {
            let mut padded = data;
            padded.resize(end, 0xFF);
            Ok(padded[offset..end].to_vec())
        } else {
            Ok(data[offset..end].to_vec())
        }
    }

    fn write(&mut self, addr: u32, data: &[u8]) -> Result<()> {
        self.ensure_dir()?;
        let sec_idx = addr / self.sec_size;
        let offset = (addr % self.sec_size) as usize;
        let path = self.sector_path(sec_idx);
        let mut sector_data = match std::fs::read(&path) {
            Ok(d) => d,
            Err(_) => vec![0xFF; self.sec_size as usize],
        };
        if sector_data.len() < self.sec_size as usize {
            sector_data.resize(self.sec_size as usize, 0xFF);
        }
        for (i, &byte) in data.iter().enumerate() {
            sector_data[offset + i] &= byte;
        }
        std::fs::write(&path, &sector_data).map_err(|e| FdbError::Io(e.to_string()))?;
        Ok(())
    }

    fn erase_sector(&mut self, sector_idx: u32) -> Result<()> {
        self.ensure_dir()?;
        let path = self.sector_path(sector_idx);
        let erased = vec![0xFF; self.sec_size as usize];
        std::fs::write(&path, &erased).map_err(|e| FdbError::Io(e.to_string()))?;
        Ok(())
    }
}
