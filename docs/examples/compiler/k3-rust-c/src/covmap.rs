// Coverage remap: clang's coverage mapping ignores `#line`, so llvm-cov reports against the generated C.
// This reads `llvm-cov export -format=text` (JSON) for the C file plus the compiler's line table
// (`<stem>.c.map`: C line -> .p3 line) and produces an lcov file and a text report against the .p3 file.
use std::collections::BTreeMap;
use std::fmt::Write;

enum J { Null, Bool(bool), Num(f64), Str(String), Arr(Vec<J>), Obj(Vec<(String, J)>) }

impl J {
    fn get(&self, k: &str) -> Option<&J> { if let J::Obj(o) = self { o.iter().find(|x| x.0 == k).map(|x| &x.1) } else { None } }
    fn arr(&self) -> &[J] { if let J::Arr(a) = self { a } else { &[] } }
    fn num(&self) -> f64 { match self { J::Num(n) => *n, J::Bool(b) => *b as u8 as f64, _ => 0.0 } }
    fn flag(&self) -> bool { match self { J::Bool(b) => *b, J::Num(n) => *n != 0.0, _ => false } }
    fn str(&self) -> &str { if let J::Str(s) = self { s } else { "" } }
}

struct P<'a> { b: &'a [u8], i: usize }
impl<'a> P<'a> {
    fn ws(&mut self) { while self.i < self.b.len() && self.b[self.i].is_ascii_whitespace() { self.i += 1; } }
    fn val(&mut self) -> Result<J, String> {
        self.ws();
        match self.b.get(self.i).copied() {
            Some(b'{') => {
                self.i += 1; let mut o = vec![];
                loop {
                    self.ws();
                    if self.b[self.i] == b'}' { self.i += 1; return Ok(J::Obj(o)); }
                    if self.b[self.i] == b',' { self.i += 1; continue; }
                    let k = match self.val()? { J::Str(s) => s, _ => return Err("object key".into()) };
                    self.ws();
                    if self.b[self.i] != b':' { return Err("expected ':'".into()); }
                    self.i += 1;
                    o.push((k, self.val()?));
                }
            }
            Some(b'[') => {
                self.i += 1; let mut a = vec![];
                loop {
                    self.ws();
                    if self.b[self.i] == b']' { self.i += 1; return Ok(J::Arr(a)); }
                    if self.b[self.i] == b',' { self.i += 1; continue; }
                    a.push(self.val()?);
                }
            }
            Some(b'"') => {
                self.i += 1; let mut s = Vec::new();
                while self.b[self.i] != b'"' {
                    if self.b[self.i] == b'\\' {
                        self.i += 1;
                        match self.b[self.i] { b'n' => s.push(b'\n'), b't' => s.push(b'\t'), b'u' => { s.push(b'?'); self.i += 4; } c => s.push(c) }
                    } else { s.push(self.b[self.i]); }
                    self.i += 1;
                }
                self.i += 1;
                Ok(J::Str(String::from_utf8_lossy(&s).into_owned()))
            }
            Some(b't') => { self.i += 4; Ok(J::Bool(true)) }
            Some(b'f') => { self.i += 5; Ok(J::Bool(false)) }
            Some(b'n') => { self.i += 4; Ok(J::Null) }
            Some(_) => {
                let s = self.i;
                while self.i < self.b.len() && (self.b[self.i].is_ascii_digit() || b"+-.eE".contains(&self.b[self.i])) { self.i += 1; }
                std::str::from_utf8(&self.b[s..self.i]).unwrap().parse().map(J::Num).map_err(|_| "bad number".to_string())
            }
            None => Err("unexpected end of JSON".into()),
        }
    }
}

fn norm(p: &str) -> String { p.replace('\\', "/") }

pub fn remap(json_path: &str, map_path: &str, src_path: &str, out: &str) -> Result<(), String> {
    let json = std::fs::read(json_path).map_err(|e| format!("{}: {}", json_path, e))?;
    let root = P { b: &json, i: 0 }.val()?;
    let map_text = std::fs::read_to_string(map_path).map_err(|e| format!("{}: {}", map_path, e))?;
    let src = std::fs::read_to_string(src_path).map_err(|e| format!("{}: {}", src_path, e))?;
    let mut map: BTreeMap<u32, u32> = BTreeMap::new(); // C line -> .p3 line
    for l in map_text.lines().filter(|l| !l.starts_with('#')) {
        let mut it = l.split_whitespace().map(|x| x.parse::<u32>());
        if let (Some(Ok(c)), Some(Ok(s))) = (it.next(), it.next()) { map.insert(c, s); }
    }
    let cname = norm(map_path);
    let cname = cname.strip_suffix(".map").unwrap_or(&cname).rsplit('/').next().unwrap().to_string();
    let data = root.get("data").and_then(|d| d.arr().first()).ok_or("no data in export")?;
    let is_ours = |f: &str| norm(f).rsplit('/').next() == Some(cname.as_str());
    let file = data.get("files").map(|f| f.arr()).unwrap_or(&[]).iter().find(|f| is_ours(f.get("filename").map_or("", |x| x.str()))).ok_or(format!("{} not in export", cname))?;

    // 1. per-C-line execution counts from the segments (the rule llvm-cov show uses: max of the
    //    segment active at the start of the line and the region entries on it).
    let segs: Vec<(u32, f64, bool, bool, bool)> = file.get("segments").map(|s| s.arr()).unwrap_or(&[]).iter().map(|s| {
        let a = s.arr();
        (a[0].num() as u32, a[2].num(), a[3].flag(), a[4].flag(), a.get(5).map_or(false, |g| g.flag()))
    }).collect();
    let max_c = segs.iter().map(|s| s.0).max().unwrap_or(0);
    let mut c_count: BTreeMap<u32, f64> = BTreeMap::new();
    for l in 1..=max_c {
        let wrapped = segs.iter().filter(|s| s.0 < l).last().filter(|s| s.2 && !s.4);
        let here: Vec<_> = segs.iter().filter(|s| s.0 == l).collect();
        let mut cnt: Option<f64> = wrapped.map(|w| w.1);
        for s in here.iter().filter(|s| s.2 && s.3 && !s.4) { cnt = Some(cnt.map_or(s.1, |c: f64| c.max(s.1))); }
        if let Some(c) = cnt { c_count.insert(l, c); }
    }
    // 2. fold C lines onto .p3 lines: max over the C lines that carry a #line directive's statement
    let mut lines: BTreeMap<u32, f64> = BTreeMap::new();
    for (c, n) in &c_count {
        if let Some(s) = map.get(c) { let e = lines.entry(*s).or_insert(0.0); if *n > *e { *e = *n; } }
    }
    // 3. branches (file level): [ls, cs, le, ce, taken, not_taken, fileId, expandedFileId, kind]
    let mut br: BTreeMap<u32, Vec<(f64, f64)>> = BTreeMap::new();
    for b in file.get("branches").map(|b| b.arr()).unwrap_or(&[]) {
        let a = b.arr();
        if let Some(s) = map.get(&(a[0].num() as u32)) { br.entry(*s).or_default().push((a[4].num(), a[5].num())); }
    }
    // 4. functions
    let mut fns: Vec<(u32, String, f64)> = vec![];
    for f in data.get("functions").map(|f| f.arr()).unwrap_or(&[]) {
        if !f.get("filenames").map_or(false, |n| n.arr().first().map_or(false, |x| is_ours(x.str()))) { continue; }
        let name = f.get("name").map_or("", |n| n.str()).rsplit(':').next().unwrap().to_string();
        let first = f.get("regions").and_then(|r| r.arr().first()).map(|r| r.arr()[0].num() as u32);
        if let Some(s) = first.and_then(|c| map.get(&c)) { fns.push((*s, name, f.get("count").map_or(0.0, |c| c.num()))); }
    }
    fns.sort_by(|a, b| a.0.cmp(&b.0));

    let shown = src_path.rsplit(|c| c == '/' || c == '\\').next().unwrap();
    let mut l = format!("TN:\nSF:{}\n", shown);
    for (s, n, _) in &fns { writeln!(l, "FN:{},{}", s, n).unwrap(); }
    for (_, n, c) in &fns { writeln!(l, "FNDA:{},{}", *c as u64, n).unwrap(); }
    writeln!(l, "FNF:{}\nFNH:{}", fns.len(), fns.iter().filter(|f| f.2 > 0.0).count()).unwrap();
    let (mut brf, mut brh) = (0, 0);
    for (s, v) in &br {
        for (i, (t, f)) in v.iter().enumerate() {
            for (k, c) in [t, f].iter().enumerate() { writeln!(l, "BRDA:{},{},{},{}", s, i, k, **c as u64).unwrap(); brf += 1; if **c > 0.0 { brh += 1; } }
        }
    }
    writeln!(l, "BRF:{}\nBRH:{}", brf, brh).unwrap();
    for (s, c) in &lines { writeln!(l, "DA:{},{}", s, *c as u64).unwrap(); }
    writeln!(l, "LF:{}\nLH:{}\nend_of_record", lines.len(), lines.values().filter(|c| **c > 0.0).count()).unwrap();
    std::fs::write(out, l).map_err(|e| format!("{}: {}", out, e))?;

    // text report
    println!("coverage of {} (remapped from {} through {}): count | branches [taken/not-taken per branch]", shown, cname, map_path.rsplit(|c| c == '/' || c == '\\').next().unwrap());
    for (i, text) in src.lines().enumerate() {
        let n = i as u32 + 1;
        let c = lines.get(&n).map_or(String::new(), |c| format!("{}", *c as u64));
        let b = br.get(&n).map_or(String::new(), |v| format!("  [{}]", v.iter().map(|(t, f)| format!("T{}/F{}", *t as u64, *f as u64)).collect::<Vec<_>>().join(" ")));
        println!("{:>4}|{:>5}| {}{}", n, c, text, b);
    }
    println!("lines hit {}/{}, branches taken {}/{}, functions hit {}/{}", lines.values().filter(|c| **c > 0.0).count(), lines.len(), brh, brf, fns.iter().filter(|f| f.2 > 0.0).count(), fns.len());
    Ok(())
}
