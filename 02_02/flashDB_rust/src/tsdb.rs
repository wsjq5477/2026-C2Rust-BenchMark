use crate::{FdbError, FlashStorage, Result};

const SECTOR_MAGIC_WORD: u32 = 0x304C5354;
const FDB_BYTE_ERASED: u8 = 0xFF;
const SECTOR_HDR_SIZE: u32 = 56;
const TSL_IDX_HDR_SIZE: u32 = 20;

fn align_up(val: u32, align: u32) -> u32 {
    ((val + align - 1) / align) * align
}

fn align_down(val: u32, align: u32) -> u32 {
    (val / align) * align
}

fn status_byte(status: u8) -> u8 {
    let mut byte = 0xFFu8;
    for i in 0..status {
        byte &= !(0x80u8 >> i);
    }
    byte
}

fn read_status_byte(byte: u8) -> u8 {
    for s in 0..6u8 {
        if byte == status_byte(s) {
            return s;
        }
    }
    if byte == 0 {
        return 5;
    }
    0
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum SectorStoreStatus {
    Unused,
    Empty,
    Using,
    Full,
}

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
    fn from_byte(byte: u8) -> Self {
        match read_status_byte(byte) {
            0 => TslStatus::Unused,
            1 => TslStatus::PreWrite,
            2 => TslStatus::Write,
            3 => TslStatus::UserStatus1,
            4 => TslStatus::Deleted,
            5 => TslStatus::UserStatus2,
            _ => TslStatus::Unused,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TslRecord {
    pub timestamp: u64,
    pub payload: Vec<u8>,
    pub status: TslStatus,
}

#[derive(Debug, Clone)]
struct SectorInfo {
    addr: u32,
    store_status: SectorStoreStatus,
    start_time: u64,
    end_time: u64,
    end_idx: u32,
    empty_idx: u32,
    empty_data: u32,
    remain: u32,
}

pub struct TsDb<S: FlashStorage> {
    storage: S,
    sec_size: u32,
    sectors_count: u32,
    max_len: u32,
    oldest_addr: u32,
    last_time: u64,
    cur_sec: SectorInfo,
    rollover: bool,
    init_ok: bool,
}

impl<S: FlashStorage> TsDb<S> {
    pub fn open(storage: S, max_len: u32) -> Result<Self> {
        let sec_size = storage.sector_size();
        let sectors_count = storage.sectors_count();
        if max_len >= sec_size {
            return Err(FdbError::InvalidInput("max_len must be less than sec_size".into()));
        }
        let mut db = Self {
            storage,
            sec_size,
            sectors_count,
            max_len,
            oldest_addr: 0,
            last_time: 0,
            cur_sec: SectorInfo {
                addr: 0,
                store_status: SectorStoreStatus::Empty,
                start_time: 0,
                end_time: 0,
                end_idx: 0,
                empty_idx: SECTOR_HDR_SIZE,
                empty_data: sec_size,
                remain: sec_size - SECTOR_HDR_SIZE,
            },
            rollover: true,
            init_ok: false,
        };
        db.format_all()?;
        db.oldest_addr = 0;
        db.init_ok = true;
        Ok(db)
    }

    fn format_all(&mut self) -> Result<()> {
        for i in 0..self.sectors_count {
            self.format_sector(i)?;
        }
        Ok(())
    }

    fn format_sector(&mut self, sector_idx: u32) -> Result<()> {
        self.storage.erase_sector(sector_idx)?;
        let addr = sector_idx * self.sec_size;
        let mut hdr = vec![0xFFu8; self.sec_size as usize];
        hdr[0] = status_byte(SectorStoreStatus::Empty as u8);
        hdr[1] = (SECTOR_MAGIC_WORD & 0xFF) as u8;
        hdr[2] = ((SECTOR_MAGIC_WORD >> 8) & 0xFF) as u8;
        hdr[3] = ((SECTOR_MAGIC_WORD >> 16) & 0xFF) as u8;
        hdr[4] = ((SECTOR_MAGIC_WORD >> 24) & 0xFF) as u8;
        self.storage.write(addr, &hdr)?;
        Ok(())
    }

    fn read_sector_info(&self, sector_idx: u32) -> Result<SectorInfo> {
        let addr = sector_idx * self.sec_size;
        let hdr = self.storage.read(addr, SECTOR_HDR_SIZE)?;
        let store_byte = hdr[0];
        let store_status = match read_status_byte(store_byte) {
            0 => SectorStoreStatus::Unused,
            1 => SectorStoreStatus::Empty,
            2 => SectorStoreStatus::Using,
            3 => SectorStoreStatus::Full,
            _ => SectorStoreStatus::Unused,
        };
        let _magic = u32::from_le_bytes([hdr[1], hdr[2], hdr[3], hdr[4]]);
        let start_time = u64::from_le_bytes([
            hdr[8], hdr[9], hdr[10], hdr[11],
            hdr[12], hdr[13], hdr[14], hdr[15],
        ]);
        let mut end_idx = 0u32;
        let mut end_time = 0u64;
        let cur_addr = addr + SECTOR_HDR_SIZE;
        let mut idx_addr = cur_addr;
        while idx_addr + TSL_IDX_HDR_SIZE <= addr + self.sec_size {
            let idx_bytes = self.storage.read(idx_addr, TSL_IDX_HDR_SIZE)?;
            let tsl_status_byte = idx_bytes[0];
            if tsl_status_byte == FDB_BYTE_ERASED {
                break;
            }
            let tsl_status = TslStatus::from_byte(tsl_status_byte);
            if tsl_status == TslStatus::Unused {
                break;
            }
            let time = u64::from_le_bytes([
                idx_bytes[4], idx_bytes[5], idx_bytes[6], idx_bytes[7],
                idx_bytes[8], idx_bytes[9], idx_bytes[10], idx_bytes[11],
            ]);
            let _log_len = u32::from_le_bytes([idx_bytes[12], idx_bytes[13], idx_bytes[14], idx_bytes[15]]);
            let _log_addr = u32::from_le_bytes([idx_bytes[16], idx_bytes[17], idx_bytes[18], idx_bytes[19]]);
            if tsl_status == TslStatus::Write || tsl_status == TslStatus::UserStatus1 || tsl_status == TslStatus::UserStatus2 {
                end_idx = idx_addr;
                end_time = time;
            }
            idx_addr += TSL_IDX_HDR_SIZE;
        }
        let empty_idx = idx_addr;
        let _last_data_addr = addr + self.sec_size;
        let _scan_addr = addr + self.sec_size;
        let mut used_data = 0u32;
        if end_idx > 0 {
            let idx_bytes = self.storage.read(end_idx, TSL_IDX_HDR_SIZE)?;
            let log_len = u32::from_le_bytes([idx_bytes[12], idx_bytes[13], idx_bytes[14], idx_bytes[15]]);
            let _aligned_log_len = align_up(log_len, 4);
            let mut check_addr = addr + SECTOR_HDR_SIZE;
            while check_addr < empty_idx {
                let check_bytes = self.storage.read(check_addr, TSL_IDX_HDR_SIZE)?;
                let check_status = TslStatus::from_byte(check_bytes[0]);
                let check_log_len = u32::from_le_bytes([check_bytes[12], check_bytes[13], check_bytes[14], check_bytes[15]]);
                let _check_log_addr = u32::from_le_bytes([check_bytes[16], check_bytes[17], check_bytes[18], check_bytes[19]]);
                if check_status != TslStatus::Unused {
                    used_data += align_up(check_log_len, 4);
                }
                check_addr += TSL_IDX_HDR_SIZE;
            }
        }
        let empty_data = addr + self.sec_size - used_data;
        let remain = empty_data - empty_idx;
        Ok(SectorInfo {
            addr,
            store_status,
            start_time,
            end_time,
            end_idx,
            empty_idx,
            empty_data,
            remain,
        })
    }

    fn write_sector_store_status(&mut self, sector_addr: u32, status: SectorStoreStatus) -> Result<()> {
        self.storage.write(sector_addr, &[status_byte(status as u8)])?;
        Ok(())
    }

    fn write_start_time(&mut self, sector_addr: u32, time: u64) -> Result<()> {
        self.storage.write(sector_addr + 8, &time.to_le_bytes())?;
        Ok(())
    }

    fn find_next_sector(&self, current_sector_idx: u32) -> u32 {
        let next = current_sector_idx + 1;
        if next >= self.sectors_count {
            if self.rollover {
                0
            } else {
                current_sector_idx
            }
        } else {
            next
        }
    }

    pub fn append(&mut self, timestamp: u64, payload: &[u8]) -> Result<()> {
        if payload.len() as u32 > self.max_len {
            return Err(FdbError::InvalidInput("payload exceeds max_len".into()));
        }
        if timestamp <= self.last_time && self.last_time != 0 {
            return Err(FdbError::InvalidInput("timestamp must be strictly increasing".into()));
        }
        let aligned_payload_len = align_up(payload.len() as u32, 4);
        let needed_idx = TSL_IDX_HDR_SIZE;
        let needed_data = aligned_payload_len;
        let needed = needed_idx + needed_data;
        if self.cur_sec.remain < needed || self.cur_sec.store_status == SectorStoreStatus::Full {
            self.move_to_next_sector(timestamp)?;
        }
        if self.cur_sec.store_status == SectorStoreStatus::Empty {
            self.write_sector_store_status(self.cur_sec.addr, SectorStoreStatus::Using)?;
            self.write_start_time(self.cur_sec.addr, timestamp)?;
            self.cur_sec.store_status = SectorStoreStatus::Using;
            self.cur_sec.start_time = timestamp;
        }
        let idx_addr = self.cur_sec.empty_idx;
        let log_addr = self.cur_sec.empty_data - aligned_payload_len;
        let mut idx_data = Vec::with_capacity(TSL_IDX_HDR_SIZE as usize);
        idx_data.extend_from_slice(&[status_byte(TslStatus::PreWrite as u8), 0xFF, 0xFF, 0xFF]);
        idx_data.extend_from_slice(&timestamp.to_le_bytes());
        idx_data.extend_from_slice(&(payload.len() as u32).to_le_bytes());
        idx_data.extend_from_slice(&log_addr.to_le_bytes());
        self.storage.write(idx_addr, &idx_data)?;
        self.storage.write(log_addr, payload)?;
        if payload.len() as u32 != aligned_payload_len {
            let pad = aligned_payload_len - payload.len() as u32;
            self.storage.write(log_addr + payload.len() as u32, &vec![0xFF; pad as usize])?;
        }
        self.storage.write(idx_addr, &[status_byte(TslStatus::Write as u8)])?;
        self.cur_sec.end_idx = idx_addr;
        self.cur_sec.end_time = timestamp;
        self.cur_sec.empty_idx += TSL_IDX_HDR_SIZE;
        self.cur_sec.empty_data = log_addr;
        self.cur_sec.remain = self.cur_sec.empty_data - self.cur_sec.empty_idx;
        self.last_time = timestamp;
        if self.cur_sec.remain < TSL_IDX_HDR_SIZE + align_up(self.max_len, 4) {
            self.write_sector_store_status(self.cur_sec.addr, SectorStoreStatus::Full)?;
            self.cur_sec.store_status = SectorStoreStatus::Full;
        }
        Ok(())
    }

    fn move_to_next_sector(&mut self, _timestamp: u64) -> Result<()> {
        self.write_sector_store_status(self.cur_sec.addr, SectorStoreStatus::Full)?;
        self.cur_sec.store_status = SectorStoreStatus::Full;
        let current_idx = self.cur_sec.addr / self.sec_size;
        let next_idx = self.find_next_sector(current_idx);
        let next_sec_info = self.read_sector_info(next_idx)?;
        if next_sec_info.store_status != SectorStoreStatus::Empty {
            self.format_sector(next_idx)?;
            self.oldest_addr = self.find_next_sector(next_idx) * self.sec_size;
        }
        let new_sec = self.read_sector_info(next_idx)?;
        self.cur_sec = new_sec;
        Ok(())
    }

    pub fn iter(&self) -> Vec<TslRecord> {
        let mut records = Vec::new();
        for sec_i in 0..self.sectors_count {
            let sec_addr = sec_i * self.sec_size;
            let sec_info = match self.read_sector_info(sec_i) {
                Ok(info) => info,
                Err(_) => continue,
            };
            if sec_info.store_status == SectorStoreStatus::Empty || sec_info.store_status == SectorStoreStatus::Unused {
                continue;
            }
            let mut idx_addr = sec_addr + SECTOR_HDR_SIZE;
            while idx_addr + TSL_IDX_HDR_SIZE <= sec_addr + self.sec_size {
                let idx_bytes = match self.storage.read(idx_addr, TSL_IDX_HDR_SIZE) {
                    Ok(b) => b,
                    Err(_) => break,
                };
                let status = TslStatus::from_byte(idx_bytes[0]);
                if status == TslStatus::Unused {
                    break;
                }
                if status == TslStatus::Write || status == TslStatus::UserStatus1 || status == TslStatus::UserStatus2 {
                    let time = u64::from_le_bytes([
                        idx_bytes[4], idx_bytes[5], idx_bytes[6], idx_bytes[7],
                        idx_bytes[8], idx_bytes[9], idx_bytes[10], idx_bytes[11],
                    ]);
                    let log_len = u32::from_le_bytes([idx_bytes[12], idx_bytes[13], idx_bytes[14], idx_bytes[15]]);
                    let log_addr = u32::from_le_bytes([idx_bytes[16], idx_bytes[17], idx_bytes[18], idx_bytes[19]]);
                    let payload = match self.storage.read(log_addr, log_len) {
                        Ok(b) => b,
                        Err(_) => break,
                    };
                    records.push(TslRecord {
                        timestamp: time,
                        payload,
                        status,
                    });
                }
                idx_addr += TSL_IDX_HDR_SIZE;
            }
        }
        records
    }

    pub fn query_by_time(&self, from: u64, to: u64) -> Result<Vec<TslRecord>> {
        let mut records = Vec::new();
        for sec_i in 0..self.sectors_count {
            let sec_addr = sec_i * self.sec_size;
            let sec_info = self.read_sector_info(sec_i)?;
            if sec_info.store_status == SectorStoreStatus::Empty || sec_info.store_status == SectorStoreStatus::Unused {
                continue;
            }
            if sec_info.start_time > to && from <= to {
                continue;
            }
            let mut idx_addr = sec_addr + SECTOR_HDR_SIZE;
            while idx_addr + TSL_IDX_HDR_SIZE <= sec_addr + self.sec_size {
                let idx_bytes = self.storage.read(idx_addr, TSL_IDX_HDR_SIZE)?;
                let status = TslStatus::from_byte(idx_bytes[0]);
                if status == TslStatus::Unused {
                    break;
                }
                let time = u64::from_le_bytes([
                    idx_bytes[4], idx_bytes[5], idx_bytes[6], idx_bytes[7],
                    idx_bytes[8], idx_bytes[9], idx_bytes[10], idx_bytes[11],
                ]);
                if from <= to {
                    if time >= from && time <= to {
                        if status == TslStatus::Write || status == TslStatus::UserStatus1 || status == TslStatus::UserStatus2 {
                            let log_len = u32::from_le_bytes([idx_bytes[12], idx_bytes[13], idx_bytes[14], idx_bytes[15]]);
                            let log_addr = u32::from_le_bytes([idx_bytes[16], idx_bytes[17], idx_bytes[18], idx_bytes[19]]);
                            let payload = self.storage.read(log_addr, log_len)?;
                            records.push(TslRecord {
                                timestamp: time,
                                payload,
                                status,
                            });
                        }
                    }
                } else {
                    if time >= to && time <= from {
                        if status == TslStatus::Write || status == TslStatus::UserStatus1 || status == TslStatus::UserStatus2 {
                            let log_len = u32::from_le_bytes([idx_bytes[12], idx_bytes[13], idx_bytes[14], idx_bytes[15]]);
                            let log_addr = u32::from_le_bytes([idx_bytes[16], idx_bytes[17], idx_bytes[18], idx_bytes[19]]);
                            let payload = self.storage.read(log_addr, log_len)?;
                            records.push(TslRecord {
                                timestamp: time,
                                payload,
                                status,
                            });
                        }
                    }
                }
                idx_addr += TSL_IDX_HDR_SIZE;
            }
        }
        Ok(records)
    }

    pub fn count_by_time(&self, from: u64, to: u64) -> Result<u32> {
        let records = self.query_by_time(from, to)?;
        Ok(records.len() as u32)
    }

    pub fn set_status(&mut self, timestamp: u64, status: TslStatus) -> Result<()> {
        for sec_i in 0..self.sectors_count {
            let sec_addr = sec_i * self.sec_size;
            let sec_info = self.read_sector_info(sec_i)?;
            if sec_info.store_status == SectorStoreStatus::Empty || sec_info.store_status == SectorStoreStatus::Unused {
                continue;
            }
            let mut idx_addr = sec_addr + SECTOR_HDR_SIZE;
            while idx_addr + TSL_IDX_HDR_SIZE <= sec_addr + self.sec_size {
                let idx_bytes = self.storage.read(idx_addr, TSL_IDX_HDR_SIZE)?;
                let cur_status = TslStatus::from_byte(idx_bytes[0]);
                if cur_status == TslStatus::Unused {
                    break;
                }
                let time = u64::from_le_bytes([
                    idx_bytes[4], idx_bytes[5], idx_bytes[6], idx_bytes[7],
                    idx_bytes[8], idx_bytes[9], idx_bytes[10], idx_bytes[11],
                ]);
                if time == timestamp {
                    self.storage.write(idx_addr, &[status_byte(status as u8)])?;
                    return Ok(());
                }
                idx_addr += TSL_IDX_HDR_SIZE;
            }
        }
        Ok(())
    }

    pub fn clean(&mut self) -> Result<()> {
        self.format_all()?;
        self.last_time = 0;
        self.oldest_addr = 0;
        self.cur_sec = self.read_sector_info(0)?;
        Ok(())
    }

    pub fn reload(&mut self) -> Result<()> {
        for sec_i in 0..self.sectors_count {
            let sec_info = self.read_sector_info(sec_i)?;
            if sec_info.store_status == SectorStoreStatus::Using {
                self.last_time = sec_info.end_time;
                self.cur_sec = sec_info;
                return Ok(());
            }
        }
        self.cur_sec = self.read_sector_info(0)?;
        Ok(())
    }
}
