use crate::{FdbError, FlashStorage, Result};
use std::collections::HashMap;

const SECTOR_HDR_SIZE: u32 = 8;
const KV_HDR_SIZE: u32 = 10;
const SECTOR_MAGIC: [u8; 4] = [0x46, 0x44, 0x42, 0x31];
const KV_MAGIC: [u8; 4] = [0x4B, 0x56, 0x30, 0x30];
const SEC_STATUS_EMPTY: u8 = 0;
const SEC_DIRTY_FALSE: u8 = 0;
const KV_STATUS_UNUSED: u8 = 0xFF;
const KV_STATUS_WRITE: u8 = 0;
const KV_STATUS_PRE_DELETE: u8 = 1;
const KV_STATUS_DELETED: u8 = 2;

#[allow(dead_code)]
enum KvStatus {
    Write,
    PreDelete,
    Deleted,
}

struct KvEntry {
    addr: u32,
    value: Vec<u8>,
    status: KvStatus,
}

pub struct KvDb {
    storage: Box<dyn FlashStorage>,
    sec_size: u32,
    max_size: u32,
    oldest_addr: u32,
    cur_sec_addr: u32,
    cur_empty_addr: u32,
    index: HashMap<String, KvEntry>,
    init_ok: bool,
    gc_request: bool,
}

impl KvDb {
    pub fn open(mut storage: Box<dyn FlashStorage>) -> Result<Self> {
        let sec_size = storage.sector_size();
        let max_size = storage.total_size();
        if sec_size == 0 || max_size == 0 || max_size < sec_size {
            return Err(FdbError::InvalidInput("invalid storage size".into()));
        }
        let num_sectors = max_size / sec_size;
        if num_sectors < 2 {
            return Err(FdbError::InvalidInput("need at least 2 sectors".into()));
        }

        let mut any_formatted = false;
        for i in 0..num_sectors {
            let addr = i * sec_size;
            let mut buf = [0u8; 4];
            storage.read(addr + 4, &mut buf)?;
            if buf == SECTOR_MAGIC {
                any_formatted = true;
                break;
            }
        }

        if !any_formatted {
            for i in 0..num_sectors {
                let addr = i * sec_size;
                storage.erase(addr, sec_size)?;
                let mut hdr = [0u8; SECTOR_HDR_SIZE as usize];
                hdr[0] = SEC_STATUS_EMPTY;
                hdr[1] = SEC_DIRTY_FALSE;
                hdr[4..8].copy_from_slice(&SECTOR_MAGIC);
                storage.write(addr, &hdr)?;
            }
        } else {
            for i in 0..num_sectors {
                let addr = i * sec_size;
                let mut buf = [0u8; 4];
                storage.read(addr + 4, &mut buf)?;
                if buf != SECTOR_MAGIC {
                    storage.erase(addr, sec_size)?;
                    let mut hdr = [0u8; SECTOR_HDR_SIZE as usize];
                    hdr[0] = SEC_STATUS_EMPTY;
                    hdr[1] = SEC_DIRTY_FALSE;
                    hdr[4..8].copy_from_slice(&SECTOR_MAGIC);
                    storage.write(addr, &hdr)?;
                }
            }
        }

        let mut db = KvDb {
            storage,
            sec_size,
            max_size,
            oldest_addr: 0,
            cur_sec_addr: 0,
            cur_empty_addr: SECTOR_HDR_SIZE,
            index: HashMap::new(),
            init_ok: false,
            gc_request: false,
        };

        db.scan_and_build_index()?;
        db.init_ok = true;
        Ok(db)
    }

    fn scan_and_build_index(&mut self) -> Result<()> {
        self.index.clear();
        let num_sectors = self.max_size / self.sec_size;
        let mut found_data = false;
        let mut last_data_sec = 0u32;
        let mut last_data_offset = SECTOR_HDR_SIZE;

        for i in 0..num_sectors {
            let sec_addr = i * self.sec_size;
            let mut magic_buf = [0u8; 4];
            self.storage.read(sec_addr + 4, &mut magic_buf)?;
            if magic_buf != SECTOR_MAGIC {
                continue;
            }

            let mut pos: u32 = SECTOR_HDR_SIZE;

            while pos + KV_HDR_SIZE <= self.sec_size {
                let abs_addr = sec_addr + pos;
                let mut hdr_buf = [0u8; KV_HDR_SIZE as usize];
                self.storage.read(abs_addr, &mut hdr_buf)?;

                if hdr_buf[0] == KV_STATUS_UNUSED {
                    break;
                }

                if hdr_buf[1..5] != KV_MAGIC {
                    pos += 1;
                    continue;
                }

                let name_len = hdr_buf[5] as u32;
                let value_len =
                    u32::from_le_bytes([hdr_buf[6], hdr_buf[7], hdr_buf[8], hdr_buf[9]]);
                let record_len = KV_HDR_SIZE + name_len + value_len;

                if pos + record_len > self.sec_size {
                    pos += 1;
                    continue;
                }

                let mut name_buf = vec![0u8; name_len as usize];
                self.storage.read(abs_addr + KV_HDR_SIZE, &mut name_buf)?;
                let key = String::from_utf8_lossy(&name_buf).into_owned();

                let mut value_buf = vec![0u8; value_len as usize];
                self.storage.read(abs_addr + KV_HDR_SIZE + name_len, &mut value_buf)?;

                match hdr_buf[0] {
                    KV_STATUS_WRITE => {
                        self.index.insert(
                            key,
                            KvEntry {
                                addr: abs_addr,
                                value: value_buf,
                                status: KvStatus::Write,
                            },
                        );
                        if !found_data {
                            self.oldest_addr = sec_addr;
                            found_data = true;
                        }
                        last_data_sec = sec_addr;
                        last_data_offset = pos + record_len;
                    }
                    KV_STATUS_PRE_DELETE | KV_STATUS_DELETED => {
                        self.index.remove(&key);
                        last_data_sec = sec_addr;
                        last_data_offset = pos + record_len;
                    }
                    _ => {
                        pos += 1;
                        continue;
                    }
                }

                pos += record_len;
            }
        }

        if found_data {
            self.cur_sec_addr = last_data_sec;
            self.cur_empty_addr = last_data_sec + last_data_offset;
        } else {
            self.cur_sec_addr = 0;
            self.cur_empty_addr = SECTOR_HDR_SIZE;
            self.oldest_addr = 0;
        }

        Ok(())
    }

    pub fn set(&mut self, key: impl Into<String>, value: impl Into<String>) -> Result<()> {
        self.write_kv_record(key.into(), value.into().into_bytes(), KV_STATUS_WRITE)
    }

    pub fn get(&self, key: impl AsRef<str>) -> Result<Option<String>> {
        match self.index.get(key.as_ref()) {
            Some(entry) if matches!(entry.status, KvStatus::Write) => {
                Ok(Some(String::from_utf8_lossy(&entry.value).into_owned()))
            }
            _ => Ok(None),
        }
    }

    pub fn set_blob(&mut self, key: impl Into<String>, value: impl AsRef<[u8]>) -> Result<()> {
        self.write_kv_record(key.into(), value.as_ref().to_vec(), KV_STATUS_WRITE)
    }

    pub fn get_blob(&self, key: impl AsRef<str>) -> Result<Option<Vec<u8>>> {
        match self.index.get(key.as_ref()) {
            Some(entry) if matches!(entry.status, KvStatus::Write) => {
                Ok(Some(entry.value.clone()))
            }
            _ => Ok(None),
        }
    }

    pub fn delete(&mut self, key: impl AsRef<str>) -> Result<()> {
        if !self.index.contains_key(key.as_ref()) {
            return Ok(());
        }
        self.write_kv_record(key.as_ref().to_string(), Vec::new(), KV_STATUS_PRE_DELETE)
    }

    pub fn iter(&self) -> impl Iterator<Item = (String, Vec<u8>)> {
        self.index
            .iter()
            .filter(|(_, e)| matches!(e.status, KvStatus::Write))
            .map(|(k, e)| (k.clone(), e.value.clone()))
            .collect::<Vec<_>>()
            .into_iter()
    }

    pub fn gc(&mut self) -> Result<()> {
        let dirty = self.find_dirty_sector()?;
        if dirty.is_none() {
            return Ok(());
        }
        let dirty_addr = dirty.unwrap();

        let dest_addr = self.find_or_create_empty_sector()?;

        let mut dest_offset: u32 = SECTOR_HDR_SIZE;
        let mut src_offset: u32 = SECTOR_HDR_SIZE;

        while src_offset + KV_HDR_SIZE <= self.sec_size {
            let src_abs = dirty_addr + src_offset;
            let mut hdr_buf = [0u8; KV_HDR_SIZE as usize];
            self.storage.read(src_abs, &mut hdr_buf)?;

            if hdr_buf[0] == KV_STATUS_UNUSED {
                break;
            }

            if hdr_buf[1..5] != KV_MAGIC {
                src_offset += 1;
                continue;
            }

            let name_len = hdr_buf[5] as u32;
            let value_len =
                u32::from_le_bytes([hdr_buf[6], hdr_buf[7], hdr_buf[8], hdr_buf[9]]);
            let record_len = KV_HDR_SIZE + name_len + value_len;

            if src_offset + record_len > self.sec_size {
                src_offset += 1;
                continue;
            }

            if hdr_buf[0] == KV_STATUS_WRITE {
                let mut name_buf = vec![0u8; name_len as usize];
                self.storage.read(src_abs + KV_HDR_SIZE, &mut name_buf)?;
                let key = String::from_utf8_lossy(&name_buf).into_owned();

                let is_current = match self.index.get(&key) {
                    Some(e) => e.addr == src_abs && matches!(e.status, KvStatus::Write),
                    None => false,
                };

                if is_current && dest_offset + record_len <= self.sec_size {
                    let dest_abs = dest_addr + dest_offset;
                    let mut record_buf = vec![0u8; record_len as usize];
                    self.storage.read(src_abs, &mut record_buf)?;
                    self.storage.write(dest_abs, &record_buf)?;

                    let old_entry = self.index.remove(&key).unwrap();
                    self.index.insert(
                        key,
                        KvEntry {
                            addr: dest_abs,
                            value: old_entry.value,
                            status: KvStatus::Write,
                        },
                    );

                    dest_offset += record_len;
                }
            }

            src_offset += record_len;
        }

        self.format_sector(dirty_addr)?;

        self.cur_sec_addr = dest_addr;
        self.cur_empty_addr = dest_addr + dest_offset;

        if dirty_addr == self.oldest_addr {
            self.oldest_addr = self.find_oldest_data_sector()?;
        }

        self.gc_request = false;
        Ok(())
    }

    pub fn reload(&mut self) -> Result<()> {
        self.scan_and_build_index()
    }

    fn write_kv_record(&mut self, key: String, value: Vec<u8>, status: u8) -> Result<()> {
        let name_bytes = key.as_bytes();
        if name_bytes.len() > 255 {
            return Err(FdbError::InvalidInput("key exceeds 255 bytes".into()));
        }
        let name_len = name_bytes.len() as u8;
        let value_len = value.len() as u32;
        let record_size = KV_HDR_SIZE + name_len as u32 + value_len;

        if record_size > self.sec_size - SECTOR_HDR_SIZE {
            return Err(FdbError::InvalidInput("record too large for sector".into()));
        }

        if self.cur_empty_addr + record_size > self.cur_sec_addr + self.sec_size {
            self.advance_to_next_sector(record_size)?;
        }

        let addr = self.cur_empty_addr;
        let mut buf = Vec::with_capacity(record_size as usize);
        buf.push(status);
        buf.extend_from_slice(&KV_MAGIC);
        buf.push(name_len);
        buf.extend_from_slice(&value_len.to_le_bytes());
        buf.extend_from_slice(name_bytes);
        buf.extend_from_slice(&value);

        self.storage.write(addr, &buf)?;

        if status == KV_STATUS_WRITE {
            self.index.insert(
                key,
                KvEntry {
                    addr,
                    value,
                    status: KvStatus::Write,
                },
            );
        } else if status == KV_STATUS_PRE_DELETE {
            self.index.remove(&key);
        }

        self.cur_empty_addr = addr + record_size;
        Ok(())
    }

    fn advance_to_next_sector(&mut self, required_size: u32) -> Result<()> {
        let num_sectors = self.max_size / self.sec_size;
        let cur_idx = self.cur_sec_addr / self.sec_size;

        for offset in 1..num_sectors {
            let idx = (cur_idx + offset) % num_sectors;
            let sec_addr = idx * self.sec_size;
            if self.is_sector_empty_with_space(sec_addr, required_size)? {
                self.cur_sec_addr = sec_addr;
                self.cur_empty_addr = sec_addr + SECTOR_HDR_SIZE;
                return Ok(());
            }
        }

        self.gc()?;

        for offset in 1..num_sectors {
            let idx = (cur_idx + offset) % num_sectors;
            let sec_addr = idx * self.sec_size;
            if self.is_sector_empty_with_space(sec_addr, required_size)? {
                self.cur_sec_addr = sec_addr;
                self.cur_empty_addr = sec_addr + SECTOR_HDR_SIZE;
                return Ok(());
            }
        }

        self.gc_request = true;
        Err(FdbError::InvalidInput("no available sector".into()))
    }

    fn is_sector_empty_with_space(
        &mut self,
        sec_addr: u32,
        required_size: u32,
    ) -> Result<bool> {
        let mut first_byte = [0u8; 1];
        self.storage.read(sec_addr + SECTOR_HDR_SIZE, &mut first_byte)?;
        if first_byte[0] != KV_STATUS_UNUSED {
            return Ok(false);
        }
        let mut magic_buf = [0u8; 4];
        self.storage.read(sec_addr + 4, &mut magic_buf)?;
        if magic_buf != SECTOR_MAGIC {
            self.format_sector(sec_addr)?;
        }
        Ok(SECTOR_HDR_SIZE + required_size <= self.sec_size)
    }

    fn format_sector(&mut self, addr: u32) -> Result<()> {
        self.storage.erase(addr, self.sec_size)?;
        let mut hdr = [0u8; SECTOR_HDR_SIZE as usize];
        hdr[0] = SEC_STATUS_EMPTY;
        hdr[1] = SEC_DIRTY_FALSE;
        hdr[4..8].copy_from_slice(&SECTOR_MAGIC);
        self.storage.write(addr, &hdr)?;
        Ok(())
    }

    fn find_dirty_sector(&mut self) -> Result<Option<u32>> {
        let num_sectors = self.max_size / self.sec_size;
        let start_idx = self.oldest_addr / self.sec_size;

        for offset in 0..num_sectors {
            let idx = (start_idx + offset) % num_sectors;
            let sec_addr = idx * self.sec_size;

            let mut magic_buf = [0u8; 4];
            self.storage.read(sec_addr + 4, &mut magic_buf)?;
            if magic_buf != SECTOR_MAGIC {
                continue;
            }

            if self.sector_has_waste(sec_addr)? {
                return Ok(Some(sec_addr));
            }
        }

        Ok(None)
    }

    fn sector_has_waste(&mut self, sec_addr: u32) -> Result<bool> {
        let mut pos: u32 = SECTOR_HDR_SIZE;

        while pos + KV_HDR_SIZE <= self.sec_size {
            let abs_addr = sec_addr + pos;
            let mut hdr_buf = [0u8; KV_HDR_SIZE as usize];
            self.storage.read(abs_addr, &mut hdr_buf)?;

            if hdr_buf[0] == KV_STATUS_UNUSED {
                break;
            }

            if hdr_buf[1..5] != KV_MAGIC {
                pos += 1;
                continue;
            }

            let name_len = hdr_buf[5] as u32;
            let value_len =
                u32::from_le_bytes([hdr_buf[6], hdr_buf[7], hdr_buf[8], hdr_buf[9]]);
            let record_len = KV_HDR_SIZE + name_len + value_len;

            if pos + record_len > self.sec_size {
                pos += 1;
                continue;
            }

            if hdr_buf[0] == KV_STATUS_PRE_DELETE || hdr_buf[0] == KV_STATUS_DELETED {
                return Ok(true);
            }

            if hdr_buf[0] == KV_STATUS_WRITE {
                let mut name_buf = vec![0u8; name_len as usize];
                self.storage.read(abs_addr + KV_HDR_SIZE, &mut name_buf)?;
                let key = String::from_utf8_lossy(&name_buf).into_owned();

                match self.index.get(&key) {
                    Some(e)
                        if e.addr == abs_addr && matches!(e.status, KvStatus::Write) => {}
                    _ => return Ok(true),
                }
            }

            pos += record_len;
        }

        Ok(false)
    }

    fn find_or_create_empty_sector(&mut self) -> Result<u32> {
        let num_sectors = self.max_size / self.sec_size;

        for i in 0..num_sectors {
            let sec_addr = i * self.sec_size;
            let mut first_byte = [0u8; 1];
            self.storage.read(sec_addr + SECTOR_HDR_SIZE, &mut first_byte)?;

            if first_byte[0] == KV_STATUS_UNUSED {
                let mut magic_buf = [0u8; 4];
                self.storage.read(sec_addr + 4, &mut magic_buf)?;
                if magic_buf == SECTOR_MAGIC {
                    return Ok(sec_addr);
                }
                self.format_sector(sec_addr)?;
                return Ok(sec_addr);
            }
        }

        Err(FdbError::InvalidInput("no empty sector for GC destination".into()))
    }

    fn find_oldest_data_sector(&mut self) -> Result<u32> {
        let num_sectors = self.max_size / self.sec_size;

        for i in 0..num_sectors {
            let sec_addr = i * self.sec_size;
            let mut first_byte = [0u8; 1];
            self.storage.read(sec_addr + SECTOR_HDR_SIZE, &mut first_byte)?;
            if first_byte[0] != KV_STATUS_UNUSED {
                let mut magic_buf = [0u8; 4];
                self.storage.read(sec_addr + 4, &mut magic_buf)?;
                if magic_buf == SECTOR_MAGIC {
                    return Ok(sec_addr);
                }
            }
        }

        Ok(0)
    }
}
