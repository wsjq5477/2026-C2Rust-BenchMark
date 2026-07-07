use flashdb_rust::{KvDb, MemFlash, TsDb};
use std::time::Instant;

const SEC_SIZE: u32 = 4096;
const KVDB_SECS: u32 = 128;
const TSDB_SECS: u32 = 128;
const KV_COUNT: u32 = 1000;
const TSL_COUNT: u32 = 2000;

fn main() {
    println!("\n============================================================");
    println!("  FlashDB Rust (MemFlash) Performance Baseline Benchmark");
    println!("  Sector size: {} bytes, KVDB sectors: {}, TSDB sectors: {}", SEC_SIZE, KVDB_SECS, TSDB_SECS);
    println!("============================================================\n");

    let mut kvdb = KvDb::open(MemFlash::new(SEC_SIZE, KVDB_SECS)).expect("open kvdb");

    println!("--- KVDB Benchmarks ---\n");

    let start = Instant::now();
    for i in 0..KV_COUNT {
        kvdb.set(&format!("str_{}", i), &format!("val_{}", i)).expect("set");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = KV_COUNT as f64 / (elapsed / 1e6);
    println!("  KV set (string):      {} ops | {:.1} us | {:.1} ops/s", KV_COUNT, elapsed, ops);

    let start = Instant::now();
    for i in 0..KV_COUNT {
        kvdb.get(&format!("str_{}", i)).expect("get");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = KV_COUNT as f64 / (elapsed / 1e6);
    println!("  KV get (string):      {} ops | {:.1} us | {:.1} ops/s", KV_COUNT, elapsed, ops);

    let blob: Vec<u8> = vec![0xAB; 128];
    let start = Instant::now();
    for i in 0..KV_COUNT {
        kvdb.set_blob(&format!("blob_{}", i), &blob).expect("set blob");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = KV_COUNT as f64 / (elapsed / 1e6);
    println!("  KV set (blob):        {} ops | {:.1} us | {:.1} ops/s", KV_COUNT, elapsed, ops);

    let start = Instant::now();
    for i in 0..KV_COUNT {
        kvdb.get_blob(&format!("blob_{}", i)).expect("get blob");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = KV_COUNT as f64 / (elapsed / 1e6);
    println!("  KV get (blob):        {} ops | {:.1} us | {:.1} ops/s", KV_COUNT, elapsed, ops);

    let start = Instant::now();
    for i in 0..KV_COUNT {
        kvdb.set(&format!("str_{}", i), &format!("upd_{}", i)).expect("update");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = KV_COUNT as f64 / (elapsed / 1e6);
    println!("  KV update (string):   {} ops | {:.1} us | {:.1} ops/s", KV_COUNT, elapsed, ops);

    let start = Instant::now();
    let all = kvdb.iter();
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = all.len() as f64 / (elapsed / 1e6);
    println!("  KV iterate all:       {} ops | {:.1} us | {:.1} ops/s", all.len(), elapsed, ops);

    let start = Instant::now();
    for i in 0..KV_COUNT {
        kvdb.delete(&format!("str_{}", i)).expect("del");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = KV_COUNT as f64 / (elapsed / 1e6);
    println!("  KV delete:            {} ops | {:.1} us | {:.1} ops/s", KV_COUNT, elapsed, ops);

    println!("\n--- TSDB Benchmarks ---\n");

    let mut tsdb = TsDb::open(MemFlash::new(SEC_SIZE, TSDB_SECS), 256).expect("open tsdb");
    let tsl_blob = vec![0xCD; 64];

    let start = Instant::now();
    for i in 0..TSL_COUNT {
        tsdb.append(i as u64 * 2 + 1, &tsl_blob).expect("append");
    }
    let elapsed = start.elapsed().as_micros() as f64;
    let ops = TSL_COUNT as f64 / (elapsed / 1e6);
    let us_per_op = elapsed / TSL_COUNT as f64;
    println!("  TSL append:           {} ops | {:.1} us | {:.1} ops/s | {:.2} us/op", TSL_COUNT, elapsed, ops, us_per_op);

    let start = Instant::now();
    let all = tsdb.iter();
    let elapsed = start.elapsed().as_micros() as f64;
    println!("  TSL iterate all:      {} found | {:.1} us", all.len(), elapsed);

    let start = Instant::now();
    let queried = tsdb.query_by_time(1, TSL_COUNT as u64 * 2 + 1).expect("query");
    let elapsed = start.elapsed().as_micros() as f64;
    println!("  TSL iter by time:     {} found | {:.1} us", queried.len(), elapsed);

    let start = Instant::now();
    let count = tsdb.count_by_time(1, TSL_COUNT as u64 * 2 + 1).expect("count");
    let elapsed = start.elapsed().as_micros() as f64;
    println!("  TSL query count:      {} | {:.1} us", count, elapsed);

    println!("\n============================================================");
    println!("  Rust Benchmark complete.");
    println!("============================================================\n");
}
