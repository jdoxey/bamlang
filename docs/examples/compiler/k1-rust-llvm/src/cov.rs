// LLVM source-based coverage, hand-encoded (coverage mapping format, https://llvm.org/docs/CoverageMappingFormat.html).
// We emit llvm.instrprof.increment calls in the IR (done in emit.rs) and the __covrec_* / __llvm_coverage_mapping
// globals here; clang's InstrProfiling pass (-fprofile-instr-generate) then creates the counters and profile data.
use crate::ir::{Func, RKind, Region};

// Plain MD5 (RFC 1321). LLVM hashes function names and the filename table with the low 8 bytes of MD5.
pub fn md5(data: &[u8]) -> [u8; 16] {
    const S: [u32; 64] = [7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 7, 12, 17, 22, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20, 5, 9, 14, 20,
        4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 4, 11, 16, 23, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21, 6, 10, 15, 21];
    let k: Vec<u32> = (0..64).map(|i| ((i as f64 + 1.0).sin().abs() * 4294967296.0) as u32).collect();
    let (mut a0, mut b0, mut c0, mut d0) = (0x67452301u32, 0xefcdab89u32, 0x98badcfeu32, 0x10325476u32);
    let mut m = data.to_vec();
    m.push(0x80);
    while m.len() % 64 != 56 { m.push(0); }
    m.extend_from_slice(&((data.len() as u64) * 8).to_le_bytes());
    for chunk in m.chunks(64) {
        let w: Vec<u32> = chunk.chunks(4).map(|b| u32::from_le_bytes([b[0], b[1], b[2], b[3]])).collect();
        let (mut a, mut b, mut c, mut d) = (a0, b0, c0, d0);
        for i in 0..64 {
            let (f, g) = match i / 16 {
                0 => ((b & c) | (!b & d), i),
                1 => ((d & b) | (!d & c), (5 * i + 1) % 16),
                2 => (b ^ c ^ d, (3 * i + 5) % 16),
                _ => (c ^ (b | !d), (7 * i) % 16),
            };
            let f2 = f.wrapping_add(a).wrapping_add(k[i]).wrapping_add(w[g]);
            a = d; d = c; c = b;
            b = b.wrapping_add(f2.rotate_left(S[i]));
        }
        a0 = a0.wrapping_add(a); b0 = b0.wrapping_add(b); c0 = c0.wrapping_add(c); d0 = d0.wrapping_add(d);
    }
    let mut out = [0u8; 16];
    for (i, v) in [a0, b0, c0, d0].iter().enumerate() { out[i * 4..i * 4 + 4].copy_from_slice(&v.to_le_bytes()); }
    out
}

pub fn md5_low(data: &[u8]) -> i64 { i64::from_le_bytes(md5(data)[..8].try_into().unwrap()) }

fn uleb(out: &mut Vec<u8>, mut v: u64) {
    loop {
        let b = (v & 0x7f) as u8;
        v >>= 7;
        if v == 0 { out.push(b); return; }
        out.push(b | 0x80);
    }
}

// The hash that ties a function's counters to its mapping record (any stable 64-bit value will do).
pub fn func_hash(f: &Func) -> i64 {
    md5_low(format!("{}/{}/{}/{:?}", f.name, f.line, f.ncounters, f.regions.iter().map(|r| (r.span.l1, r.span.c1)).collect::<Vec<_>>()).as_bytes())
}

// The filename table: ULEB count, ULEB uncompressed size, ULEB compressed size (0 = not compressed), then
// length-prefixed names. Version 6 keeps the compilation directory as entry 0 and the source file as entry 1.
pub fn filenames_blob(dir: &str, file: &str) -> Vec<u8> {
    let mut body = vec![];
    for n in [dir, file] { uleb(&mut body, n.len() as u64); body.extend_from_slice(n.as_bytes()); }
    let mut out = vec![];
    uleb(&mut out, 2);
    uleb(&mut out, body.len() as u64);
    uleb(&mut out, 0);
    out.extend(body);
    out
}

fn counter(id: u32) -> u64 { ((id as u64) << 2) | 1 }

// One function's mapping: 1 file (table entry 1), no expressions, then its regions sorted by start.
// Code region: counter, line delta, start col, line count, end col. Branch region: 4<<3, true counter, false counter, then the same.
pub fn mapping(regions: &[Region]) -> Vec<u8> {
    let mut rs: Vec<Region> = regions.iter().copied().filter(|r| (r.span.l1, r.span.c1) < (r.span.l2, r.span.c2)).collect();
    let rank = |r: &Region| match r.kind { RKind::Code(_) => 0, RKind::Branch(..) => 1 };
    rs.sort_by_key(|r| (r.span.l1, r.span.c1, rank(r), std::cmp::Reverse((r.span.l2, r.span.c2))));
    let mut out = vec![];
    uleb(&mut out, 1);
    uleb(&mut out, 1);
    uleb(&mut out, 0);
    uleb(&mut out, rs.len() as u64);
    let mut prev = 0u32;
    for r in &rs {
        match r.kind {
            RKind::Code(c) => uleb(&mut out, counter(c)),
            RKind::Branch(t, f) => { uleb(&mut out, 4 << 3); uleb(&mut out, counter(t)); uleb(&mut out, counter(f)); }
        }
        uleb(&mut out, (r.span.l1 - prev) as u64);
        uleb(&mut out, r.span.c1 as u64);
        uleb(&mut out, (r.span.l2 - r.span.l1) as u64);
        uleb(&mut out, r.span.c2 as u64);
        prev = r.span.l1;
    }
    out
}
