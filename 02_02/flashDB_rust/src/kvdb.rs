use crate::{FdbError, FlashStorage, Result};
use std::collections::HashMap;

const SECTOR_MAGIC_WORD: u32 = 0x30424446;
const KV_MAGIC_WORD: u32 = 0x3030564B;
const FDB_BYTE_ERASED: u8 = 0xFF;

const SECTOR_HDR_SIZE: u32 = 16;
const KV_HDR_DATA_SIZE: u32 = 24;
const KV_NAME_MAX: usize = 64;

fn align_up(val: u32, align: u32) -> u32 {
    ((val + align - 1) / align) * align
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

fn calc_crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFFFFFFu32;
    for &byte in data {
        let idx = ((crc ^ u32::from(byte)) & 0xFF) as usize;
        crc = (crc >> 8) ^ CRC_TABLE[idx];
    }
    crc ^ 0xFFFFFFFF
}

const CRC_TABLE: [u32; 256] = {
    let mut table = [0u32; 256];
    let mut i = 0;
    while i < 256 {
        let mut crc = (i as u32) ^ 0xFFFFFFFF;
        let mut j = 0;
        while j < 8 {
            if crc & 1 != 0 {
                crc = (crc >> 1) ^ 0xEDB88320;
            } else {
                crc >>= 1;
            }
            j += 1;
        }
        table[i] = crc ^ 0xFFFFFFFF;
        i += 1;
    }
    table
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum KvStatus {
    Unused,
    PreWrite,
    Write,
    PreDelete,
    Deleted,
    ErrHdr,
}

#[derive(Debug, Clone)]
struct KvNode {
    status: KvStatus,
    addr_start: u32,
    addr_value: u32,
    name_len: u32,
    value_len: u32,
    total_len: u32,
    crc_is_ok: bool,
    name: String,
}

pub struct KvDb<S: FlashStorage> {
    storage: S,
    sec_size: u32,
    sectors_count: u32,
    cur_sector_idx: u32,
    cur_write_offset: u32,
    gc_request: bool,
    init_ok: bool,
    index: HashMap<String, KvNode>,
}

impl<S: FlashStorage> KvDb<S> {
    pub fn open(storage: S) -> Result<Self> {
        let sec_size = storage.sector_size();
        let sectors_count = storage.sectors_count();
        let mut db = Self {
            storage,
            sec_size,
            sectors_count,
            cur_sector_idx: 0,
            cur_write_offset: SECTOR_HDR_SIZE,
            gc_request: false,
            init_ok: false,
            index: HashMap::new(),
        };
        db.format_all()?;
        db.set_sector_store(0, 2)?;
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
        let hdr: [u8; 16] = [
            status_byte(1), status_byte(1),
            (SECTOR_MAGIC_WORD & 0xFF) as u8,
            ((SECTOR_MAGIC_WORD >> 8) & 0xFF) as u8,
            ((SECTOR_MAGIC_WORD >> 16) & 0xFF) as u8,
            ((SECTOR_MAGIC_WORD >> 24) & 0xFF) as u8,
            0xFF, 0xFF, 0xFF, 0xFF,
            0, 0, 0, 0, 0, 0,
        ];
        self.storage.write(addr, &hdr)?;
        Ok(())
    }

    fn set_sector_store(&mut self, sector_idx: u32, status_num: u8) -> Result<()> {
        let addr = sector_idx * self.sec_size;
        self.storage.write(addr, &[status_byte(status_num)])?;
        Ok(())
    }

    fn set_sector_dirty(&mut self, sector_idx: u32, status_num: u8) -> Result<()> {
        let addr = sector_idx * self.sec_size + 1;
        self.storage.write(addr, &[status_byte(status_num)])?;
        Ok(())
    }

    fn write_kv_entry(&mut self, key: &str, value: &[u8]) -> Result<()> {
        let name_len = key.len() as u32;
        let value_len = value.len() as u32;
        let aligned_name_len = align_up(name_len, 4);
        let aligned_value_len = align_up(value_len, 4);
        let total_len = KV_HDR_DATA_SIZE + aligned_name_len + aligned_value_len;

        let write_addr = self.cur_sector_idx * self.sec_size + self.cur_write_offset;
        let sec_addr = self.cur_sector_idx * self.sec_size;

        let mut hdr = Vec::with_capacity(KV_HDR_DATA_SIZE as usize);
        hdr.push(status_byte(KvStatus::PreWrite as u8));
        hdr.extend_from_slice(&KV_MAGIC_WORD.to_le_bytes());
        hdr.extend_from_slice(&total_len.to_le_bytes());

        let mut crc_data = Vec::new();
        crc_data.push(name_len as u8);
        crc_data.extend_from_slice(&value_len.to_le_bytes());
        crc_data.extend_from_slice(key.as_bytes());
        crc_data.extend_from_slice(&vec![0xFFu8; (aligned_name_len - name_len) as usize]);
        crc_data.extend_from_slice(value);
        crc_data.extend_from_slice(&vec![0xFFu8; (aligned_value_len - value_len) as usize]);
        let crc = calc_crc32(&crc_data);
        hdr.extend_from_slice(&crc.to_le_bytes());
        hdr.push(name_len as u8);
        hdr.extend_from_slice(&value_len.to_le_bytes());
        while hdr.len() < KV_HDR_DATA_SIZE as usize {
            hdr.push(0xFF);
        }
        self.storage.write(write_addr, &hdr)?;

        let name_addr = write_addr + KV_HDR_DATA_SIZE;
        let mut name_data = key.as_bytes().to_vec();
        name_data.extend_from_slice(&vec![0xFFu8; (aligned_name_len - name_len) as usize]);
        self.storage.write(name_addr, &name_data)?;

        let value_addr = name_addr + aligned_name_len;
        let mut value_data = value.to_vec();
        value_data.extend_from_slice(&vec![0xFFu8; (aligned_value_len - value_len) as usize]);
        self.storage.write(value_addr, &value_data)?;

        self.storage.write(write_addr, &[status_byte(KvStatus::Write as u8)])?;

        let kv_node = KvNode {
            status: KvStatus::Write,
            addr_start: write_addr,
            addr_value: value_addr,
            name_len,
            value_len,
            total_len,
            crc_is_ok: true,
            name: key.to_string(),
        };
        self.index.insert(key.to_string(), kv_node);

        self.cur_write_offset += total_len;
        let remain = self.sec_size - self.cur_write_offset;
        if remain < KV_HDR_DATA_SIZE + KV_NAME_MAX as u32 {
            self.set_sector_store(self.cur_sector_idx, 3)?;
            self.set_sector_dirty(self.cur_sector_idx, 2)?;
            self.gc_request = true;
        }
        Ok(())
    }

    fn advance_sector(&mut self) -> Result<()> {
        for sec_i in 0..self.sectors_count {
            let bytes = self.storage.read(sec_i * self.sec_size, 1)?;
            let store = read_status_byte(bytes[0]);
            if store == 1 {
                self.set_sector_store(sec_i, 2)?;
                self.cur_sector_idx = sec_i;
                self.cur_write_offset = SECTOR_HDR_SIZE;
                return Ok(());
            }
        }
        Err(FdbError::SavedFull)
    }

    pub fn set(&mut self, key: &str, value: &str) -> Result<()> {
        self.set_blob(key, value.as_bytes())
    }

    pub fn get(&self, key: &str) -> Result<Option<String>> {
        match self.get_blob(key)? {
            Some(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
            None => Ok(None),
        }
    }

    pub fn set_blob(&mut self, key: &str, value: &[u8]) -> Result<()> {
        if key.is_empty() || key.len() > KV_NAME_MAX {
            return Err(FdbError::NameErr);
        }
        let name_len = key.len() as u32;
        let value_len = value.len() as u32;
        let aligned_name_len = align_up(name_len, 4);
        let aligned_value_len = align_up(value_len, 4);
        let needed = KV_HDR_DATA_SIZE + aligned_name_len + aligned_value_len;

        if self.index.contains_key(key) {
            let old = self.index.get(key).unwrap().clone();
            self.storage.write(old.addr_start, &[status_byte(KvStatus::PreDelete as u8)])?;
            self.index.remove(key);
        }

        if self.gc_request {
            self.gc_collect()?;
        }

        let remain = self.sec_size - self.cur_write_offset;
        if remain < needed {
            self.set_sector_store(self.cur_sector_idx, 3)?;
            self.set_sector_dirty(self.cur_sector_idx, 2)?;
            self.gc_request = true;
            self.gc_collect()?;
        }

        let remain = self.sec_size - self.cur_write_offset;
        if remain < needed {
            self.advance_sector()?;
        }

        self.write_kv_entry(key, value)?;
        Ok(())
    }

    pub fn get_blob(&self, key: &str) -> Result<Option<Vec<u8>>> {
        match self.index.get(key) {
            Some(kv) if kv.status == KvStatus::Write && kv.crc_is_ok => {
                let bytes = self.storage.read(kv.addr_value, kv.value_len)?;
                Ok(Some(bytes))
            }
            _ => Ok(None),
        }
    }

    pub fn delete(&mut self, key: &str) -> Result<()> {
        if let Some(kv) = self.index.get(key) {
            let addr = kv.addr_start;
            self.storage.write(addr, &[status_byte(KvStatus::Deleted as u8)])?;
            let sec_idx = addr / self.sec_size;
            self.set_sector_dirty(sec_idx, 2)?;
            self.index.remove(key);
        }
        Ok(())
    }

    pub fn reload(&mut self) -> Result<()> {
        self.rebuild_index()?;
        Ok(())
    }

    fn rebuild_index(&mut self) -> Result<()> {
        self.index.clear();
        for sec_i in 0..self.sectors_count {
            let sec_addr = sec_i * self.sec_size;
            let hdr = self.storage.read(sec_addr, 1)?;
            let store = read_status_byte(hdr[0]);
            if store <= 1 {
                continue;
            }
            let mut addr = sec_addr + SECTOR_HDR_SIZE;
            while addr + KV_HDR_DATA_SIZE <= sec_addr + self.sec_size {
                let hdr_bytes = self.storage.read(addr, KV_HDR_DATA_SIZE)?;
                let status_byte_val = hdr_bytes[0];
                if status_byte_val == FDB_BYTE_ERASED {
                    break;
                }
                let status_val = read_status_byte(status_byte_val);
                if status_val == 0 {
                    break;
                }
                let magic = u32::from_le_bytes([hdr_bytes[1], hdr_bytes[2], hdr_bytes[3], hdr_bytes[4]]);
                if magic != KV_MAGIC_WORD {
                    addr += 4;
                    continue;
                }
                let total_len = u32::from_le_bytes([hdr_bytes[5], hdr_bytes[6], hdr_bytes[7], hdr_bytes[8]]);
                if total_len == 0 || addr + total_len > sec_addr + self.sec_size {
                    break;
                }
                let name_len = hdr_bytes[13] as u32;
                let value_len = u32::from_le_bytes([hdr_bytes[14], hdr_bytes[15], hdr_bytes[16], hdr_bytes[17]]);
                let aligned_name_len = align_up(name_len, 4);
                let name_addr = addr + KV_HDR_DATA_SIZE;
                let name_bytes = self.storage.read(name_addr, name_len)?;
                let name_str = String::from_utf8_lossy(&name_bytes).into_owned();
                let value_addr = name_addr + aligned_name_len;

                let kv_status = match status_val {
                    1 => KvStatus::PreWrite,
                    2 => KvStatus::Write,
                    3 => KvStatus::PreDelete,
                    4 => KvStatus::Deleted,
                    5 => KvStatus::ErrHdr,
                    _ => KvStatus::Unused,
                };

                if kv_status == KvStatus::Write {
                    self.index.insert(name_str.clone(), KvNode {
                        status: kv_status,
                        addr_start: addr,
                        addr_value: value_addr,
                        name_len,
                        value_len,
                        total_len,
                        crc_is_ok: true,
                        name: name_str,
                    });
                } else if kv_status == KvStatus::Deleted || kv_status == KvStatus::PreDelete {
                    self.index.remove(&name_str);
                }

                addr += total_len;
            }
        }
        Ok(())
    }

    pub fn gc(&mut self) -> Result<()> {
        self.gc_collect()?;
        Ok(())
    }

    fn gc_collect(&mut self) -> Result<()> {
        let mut empty_sectors = Vec::new();
        let mut dirty_sectors = Vec::new();
        for sec_i in 0..self.sectors_count {
            let sec_addr = sec_i * self.sec_size;
            let hdr = self.storage.read(sec_addr, 2)?;
            let store = read_status_byte(hdr[0]);
            let dirty = read_status_byte(hdr[1]);
            if store == 1 {
                empty_sectors.push(sec_i);
            }
            if dirty >= 2 {
                dirty_sectors.push(sec_i);
            }
        }

        if empty_sectors.len() > 1 {
            self.gc_request = false;
            return Ok(());
        }

        let live_kvs: Vec<KvNode> = self.index.values().cloned().collect();

        for dirty_sec in &dirty_sectors {
            self.set_sector_dirty(*dirty_sec, 3)?;
        }

        for dirty_sec in &dirty_sectors {
            self.format_sector(*dirty_sec)?;
        }

        for sec_i in 0..self.sectors_count {
            let sec_addr = sec_i * self.sec_size;
            let hdr = self.storage.read(sec_addr, 1)?;
            let store = read_status_byte(hdr[0]);
            if store <= 1 {
                self.set_sector_store(sec_i, 2)?;
                self.cur_sector_idx = sec_i;
                self.cur_write_offset = SECTOR_HDR_SIZE;
                break;
            }
        }

        for kv in &live_kvs {
            let value = self.storage.read(kv.addr_value, kv.value_len)?;
            let needed = KV_HDR_DATA_SIZE + align_up(kv.name_len, 4) + align_up(kv.value_len, 4);
            let remain = self.sec_size - self.cur_write_offset;
            if remain < needed {
                self.set_sector_store(self.cur_sector_idx, 3)?;
                self.advance_sector()?;
            }
            self.write_kv_entry(&kv.name, &value)?;
        }

        self.gc_request = false;
        Ok(())
    }

    pub fn iter(&self) -> Vec<(String, Vec<u8>)> {
        self.index.iter().filter_map(|(key, kv)| {
            if kv.status == KvStatus::Write && kv.crc_is_ok {
                let bytes = self.storage.read(kv.addr_value, kv.value_len).ok()?;
                Some((key.clone(), bytes))
            } else {
                None
            }
        }).collect()
    }

    pub fn set_default(&mut self, defaults: &[(&str, &[u8])]) -> Result<()> {
        self.format_all()?;
        self.set_sector_store(0, 2)?;
        self.cur_sector_idx = 0;
        self.cur_write_offset = SECTOR_HDR_SIZE;
        self.index.clear();
        for (key, value) in defaults {
            self.set_blob(key, value)?;
        }
        Ok(())
    }
}
