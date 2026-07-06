use crate::{FdbError, Result};
use crate::flash::{FlashStorage, MemFlash};

const SECTOR_HDR_SIZE: u32 = 40;
const TSL_IDX_SIZE: u32 = 17;
const MAGIC: [u8; 4] = [0x54, 0x53, 0x4C, 0x30];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TslStatus {
    Unused,
    PreWrite,
    Write,
    UserStatus1,
    Deleted,
    UserStatus2,
}

impl TslStatus {
    fn from_byte(b: u8) -> Self {
        match b {
            0xFF => TslStatus::Unused,
            0 => TslStatus::PreWrite,
            1 => TslStatus::Write,
            2 => TslStatus::UserStatus1,
            3 => TslStatus::Deleted,
            4 => TslStatus::UserStatus2,
            _ => TslStatus::Unused,
        }
    }

    fn to_byte(&self) -> u8 {
        match self {
            TslStatus::Unused => 0xFF,
            TslStatus::PreWrite => 0,
            TslStatus::Write => 1,
            TslStatus::UserStatus1 => 2,
            TslStatus::Deleted => 3,
            TslStatus::UserStatus2 => 4,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TslRecord {
    pub timestamp: u64,
    pub payload: Vec<u8>,
    pub status: TslStatus,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SectorStatus {
    NotFormatted,
    Empty,
    Using,
    Full,
}

#[derive(Debug, Clone)]
struct SectorInfo {
    status: SectorStatus,
    start_time: u64,
}

pub struct TsDb {
    flash: MemFlash,
    sector_size: u32,
    sector_count: usize,
    max_len: u32,
    records: Vec<TslRecord>,
    record_sectors: Vec<usize>,
    cur_sec_idx: usize,
    write_pos: u32,
    data_pos: u32,
    last_timestamp: u64,
    sectors: Vec<SectorInfo>,
}

impl TsDb {
    pub fn open(sector_size: u32, sector_count: u32, max_len: u32) -> Result<Self> {
        let count = sector_count as usize;
        let flash = MemFlash::new(sector_size, sector_count);
        let mut db = Self {
            flash,
            sector_size,
            sector_count: count,
            max_len,
            records: Vec::new(),
            record_sectors: Vec::new(),
            cur_sec_idx: 0,
            write_pos: SECTOR_HDR_SIZE,
            data_pos: sector_size,
            last_timestamp: 0,
            sectors: Vec::new(),
        };
        for i in 0..count {
            db.format_sector(i as u32)?;
            db.sectors.push(SectorInfo {
                status: SectorStatus::Empty,
                start_time: 0,
            });
        }
        db.cur_sec_idx = 0;
        db.sectors[0].status = SectorStatus::Using;
        db.write_us_marker(0)?;
        Ok(db)
    }

    fn sec_addr(&self, idx: u32) -> u32 {
        idx * self.sector_size
    }

    fn format_sector(&mut self, idx: u32) -> Result<()> {
        let addr = self.sec_addr(idx);
        self.flash.erase(addr, self.sector_size)?;
        self.flash.write(addr, &[0x00])?;
        self.flash.write(addr + 4, &MAGIC)?;
        Ok(())
    }

    fn write_us_marker(&mut self, idx: u32) -> Result<()> {
        let addr = self.sec_addr(idx);
        self.flash.write(addr + 1, &[0x00])?;
        Ok(())
    }

    fn write_full_marker(&mut self, idx: u32) -> Result<()> {
        let addr = self.sec_addr(idx);
        self.flash.write(addr + 2, &[0x00])?;
        Ok(())
    }

    fn write_start_time(&mut self, idx: u32, time: u64) -> Result<()> {
        let addr = self.sec_addr(idx);
        self.flash.write(addr + 8, &time.to_le_bytes())?;
        Ok(())
    }

    fn read_sector_status_from_flash(&self, idx: usize) -> SectorStatus {
        let addr = self.sec_addr(idx as u32);
        let mut hdr = [0u8; 3];
        if self.flash.read(addr, &mut hdr).is_err() {
            return SectorStatus::NotFormatted;
        }
        let mut magic_buf = [0u8; 4];
        if self.flash.read(addr + 4, &mut magic_buf).is_err() || magic_buf != MAGIC {
            return SectorStatus::NotFormatted;
        }
        if hdr[0] == 0xFF {
            return SectorStatus::NotFormatted;
        }
        if hdr[2] == 0x00 {
            SectorStatus::Full
        } else if hdr[1] == 0x00 {
            SectorStatus::Using
        } else {
            SectorStatus::Empty
        }
    }

    fn read_start_time_from_flash(&self, idx: usize) -> u64 {
        let addr = self.sec_addr(idx as u32);
        let mut buf = [0u8; 8];
        if self.flash.read(addr + 8, &mut buf).is_err() {
            return 0;
        }
        let ts = u64::from_le_bytes(buf);
        if ts == u64::MAX { 0 } else { ts }
    }

    fn find_next_empty_sector(&self) -> Option<usize> {
        let start = (self.cur_sec_idx + 1) % self.sector_count;
        for offset in 0..self.sector_count {
            let idx = (start + offset) % self.sector_count;
            if self.sectors[idx].status == SectorStatus::Empty {
                return Some(idx);
            }
        }
        None
    }

    fn find_oldest_active_sector(&self) -> usize {
        let mut oldest_idx = 0;
        let mut oldest_time = u64::MAX;
        for (i, info) in self.sectors.iter().enumerate() {
            if (info.status == SectorStatus::Using || info.status == SectorStatus::Full)
                && info.start_time > 0
                && info.start_time < oldest_time
            {
                oldest_time = info.start_time;
                oldest_idx = i;
            }
        }
        oldest_idx
    }

    fn transition_sector(&mut self) -> Result<()> {
        self.sectors[self.cur_sec_idx].status = SectorStatus::Full;
        self.write_full_marker(self.cur_sec_idx as u32)?;
        let next_idx = match self.find_next_empty_sector() {
            Some(idx) => idx,
            None => {
                let oldest = self.find_oldest_active_sector();
                self.remove_records_for_sector(oldest);
                self.format_sector(oldest as u32)?;
                self.sectors[oldest] = SectorInfo {
                    status: SectorStatus::Empty,
                    start_time: 0,
                };
                oldest
            }
        };
        self.cur_sec_idx = next_idx;
        self.sectors[next_idx].status = SectorStatus::Using;
        self.write_us_marker(next_idx as u32)?;
        self.write_pos = SECTOR_HDR_SIZE;
        self.data_pos = self.sector_size;
        Ok(())
    }

    fn remove_records_for_sector(&mut self, sec_idx: usize) {
        let mut new_records = Vec::new();
        let mut new_sectors = Vec::new();
        for i in 0..self.records.len() {
            if self.record_sectors[i] != sec_idx {
                new_records.push(self.records[i].clone());
                new_sectors.push(self.record_sectors[i]);
            }
        }
        self.records = new_records;
        self.record_sectors = new_sectors;
    }

    pub fn append(&mut self, timestamp: u64, payload: impl AsRef<[u8]>) -> Result<()> {
        if timestamp <= self.last_timestamp {
            return Err(FdbError::InvalidInput(format!(
                "timestamp {} must be > last {}",
                timestamp, self.last_timestamp
            )));
        }
        let data = payload.as_ref();
        if data.len() as u32 > self.max_len {
            return Err(FdbError::InvalidInput(format!(
                "payload len {} exceeds max_len {}",
                data.len(), self.max_len
            )));
        }
        let data_len = data.len() as u32;
        if self.write_pos + TSL_IDX_SIZE > self.data_pos - data_len {
            self.transition_sector()?;
        }
        if self.sectors[self.cur_sec_idx].start_time == 0 {
            self.sectors[self.cur_sec_idx].start_time = timestamp;
            self.write_start_time(self.cur_sec_idx as u32, timestamp)?;
        }
        let sec_addr = self.sec_addr(self.cur_sec_idx as u32);
        let new_data_pos = self.data_pos - data_len;
        self.flash.write(sec_addr + new_data_pos, data)?;
        let mut idx_buf = [0u8; TSL_IDX_SIZE as usize];
        idx_buf[0] = TslStatus::Write.to_byte();
        idx_buf[1..9].copy_from_slice(&timestamp.to_le_bytes());
        idx_buf[9..13].copy_from_slice(&data_len.to_le_bytes());
        idx_buf[13..17].copy_from_slice(&new_data_pos.to_le_bytes());
        self.flash.write(sec_addr + self.write_pos, &idx_buf)?;
        self.write_pos += TSL_IDX_SIZE;
        self.data_pos = new_data_pos;
        self.last_timestamp = timestamp;
        self.records.push(TslRecord {
            timestamp,
            payload: data.to_vec(),
            status: TslStatus::Write,
        });
        self.record_sectors.push(self.cur_sec_idx);
        Ok(())
    }

    pub fn iter(&self) -> impl Iterator<Item = &TslRecord> {
        self.records.iter().filter(|r| r.status == TslStatus::Write)
    }

    pub fn iter_reverse(&self) -> impl Iterator<Item = &TslRecord> {
        self.records.iter().rev().filter(|r| r.status == TslStatus::Write)
    }

    pub fn query_by_time(&self, from: u64, to: u64) -> Result<Vec<TslRecord>> {
        Ok(self
            .records
            .iter()
            .filter(|r| r.timestamp >= from && r.timestamp <= to && r.status == TslStatus::Write)
            .cloned()
            .collect())
    }

    pub fn count_by_time(&self, from: u64, to: u64, status: TslStatus) -> usize {
        self.records
            .iter()
            .filter(|r| r.timestamp >= from && r.timestamp <= to && r.status == status)
            .count()
    }

    pub fn set_status(&mut self, timestamp: u64, status: TslStatus) -> Result<()> {
        for record in &mut self.records {
            if record.timestamp == timestamp {
                record.status = status;
            }
        }
        Ok(())
    }

    pub fn clean(&mut self) -> Result<()> {
        for i in 0..self.sector_count {
            self.format_sector(i as u32)?;
            self.sectors[i] = SectorInfo {
                status: SectorStatus::Empty,
                start_time: 0,
            };
        }
        self.cur_sec_idx = 0;
        self.sectors[0].status = SectorStatus::Using;
        self.write_us_marker(0)?;
        self.write_pos = SECTOR_HDR_SIZE;
        self.data_pos = self.sector_size;
        self.last_timestamp = 0;
        self.records.clear();
        self.record_sectors.clear();
        Ok(())
    }

    pub fn reload(&mut self) -> Result<()> {
        self.records.clear();
        self.record_sectors.clear();
        self.last_timestamp = 0;
        for i in 0..self.sector_count {
            self.sectors[i].status = self.read_sector_status_from_flash(i);
            self.sectors[i].start_time = self.read_start_time_from_flash(i);
        }
        let mut active_sectors: Vec<usize> = (0..self.sector_count)
            .filter(|&i| {
                self.sectors[i].status == SectorStatus::Using
                    || self.sectors[i].status == SectorStatus::Full
            })
            .filter(|&i| self.sectors[i].start_time > 0)
            .collect();
        active_sectors.sort_by_key(|&i| self.sectors[i].start_time);
        for &sec_idx in &active_sectors {
            self.scan_sector(sec_idx)?;
        }
        let using_idx = self.sectors.iter().position(|s| s.status == SectorStatus::Using);
        if let Some(idx) = using_idx {
            self.cur_sec_idx = idx;
            self.recalc_positions(idx)?;
        } else {
            let empty_idx = self.sectors.iter().position(|s| s.status == SectorStatus::Empty);
            let idx = match empty_idx {
                Some(e) => e,
                None => {
                    let oldest = self.find_oldest_active_sector();
                    self.remove_records_for_sector(oldest);
                    self.format_sector(oldest as u32)?;
                    self.sectors[oldest] = SectorInfo {
                        status: SectorStatus::Empty,
                        start_time: 0,
                    };
                    oldest
                }
            };
            self.cur_sec_idx = idx;
            self.sectors[idx].status = SectorStatus::Using;
            self.write_us_marker(idx as u32)?;
            self.write_pos = SECTOR_HDR_SIZE;
            self.data_pos = self.sector_size;
        }
        if let Some(last) = self.records.last() {
            self.last_timestamp = last.timestamp;
        }
        Ok(())
    }

    fn scan_sector(&mut self, sec_idx: usize) -> Result<()> {
        let sec_addr = self.sec_addr(sec_idx as u32);
        let mut pos = SECTOR_HDR_SIZE;
        while pos + TSL_IDX_SIZE <= self.sector_size {
            let mut idx_buf = [0u8; TSL_IDX_SIZE as usize];
            if self.flash.read(sec_addr + pos, &mut idx_buf).is_err() {
                break;
            }
            let status_byte = idx_buf[0];
            if status_byte == 0xFF {
                break;
            }
            let timestamp = u64::from_le_bytes(idx_buf[1..9].try_into().unwrap());
            let log_len = u32::from_le_bytes(idx_buf[9..13].try_into().unwrap());
            let log_addr = u32::from_le_bytes(idx_buf[13..17].try_into().unwrap());
            if log_len == 0 || log_addr + log_len > self.sector_size {
                pos += TSL_IDX_SIZE;
                continue;
            }
            let mut payload = vec![0u8; log_len as usize];
            if self.flash.read(sec_addr + log_addr, &mut payload).is_err() {
                pos += TSL_IDX_SIZE;
                continue;
            }
            self.records.push(TslRecord {
                timestamp,
                payload,
                status: TslStatus::from_byte(status_byte),
            });
            self.record_sectors.push(sec_idx);
            pos += TSL_IDX_SIZE;
        }
        Ok(())
    }

    fn recalc_positions(&mut self, sec_idx: usize) -> Result<()> {
        let sec_addr = self.sec_addr(sec_idx as u32);
        let mut pos = SECTOR_HDR_SIZE;
        while pos + TSL_IDX_SIZE <= self.sector_size {
            let mut buf = [0u8; 1];
            if self.flash.read(sec_addr + pos, &mut buf).is_err() || buf[0] == 0xFF {
                break;
            }
            pos += TSL_IDX_SIZE;
        }
        self.write_pos = pos;
        let mut min_data = self.sector_size;
        let mut scan = SECTOR_HDR_SIZE;
        while scan + TSL_IDX_SIZE <= self.sector_size {
            let mut idx_buf = [0u8; TSL_IDX_SIZE as usize];
            if self.flash.read(sec_addr + scan, &mut idx_buf).is_err() || idx_buf[0] == 0xFF {
                break;
            }
            let log_addr = u32::from_le_bytes(idx_buf[13..17].try_into().unwrap());
            if log_addr < min_data {
                min_data = log_addr;
            }
            scan += TSL_IDX_SIZE;
        }
        self.data_pos = min_data;
        Ok(())
    }
}
