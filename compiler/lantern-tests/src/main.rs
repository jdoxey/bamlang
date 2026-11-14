//! Conformance harness. See tests/README.md.
use lantern::Diag;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, PartialEq, Eq)]
pub enum Outcome {
    Pass,
    Fail(String),
    NotImpl,
}

pub type Stage<'a> = &'a dyn Fn(&str) -> Result<String, Diag>;

pub fn strip_cr(s: &str) -> String {
    s.replace('\r', "")
}

pub fn to_crlf(s: &str) -> String {
    strip_cr(s).replace('\n', "\r\n")
}

/// Parse the first line `# expect: LINE: substring`.
pub fn parse_expect(src: &str) -> Option<(usize, String)> {
    let first = src.lines().next()?.trim_end_matches('\r');
    let rest = first.strip_prefix("# expect:")?.trim_start();
    let (num, sub) = rest.split_once(':')?;
    let line: usize = num.trim().parse().ok()?;
    let sub = sub.trim_start();
    if sub.is_empty() {
        return None;
    }
    Some((line, sub.to_string()))
}

pub fn compare_ast(expected: &str, actual: &str) -> Result<(), String> {
    let (e, a) = (strip_cr(expected), strip_cr(actual));
    if e == a {
        return Ok(());
    }
    for (i, (el, al)) in e.lines().zip(a.lines()).enumerate() {
        if el != al {
            return Err(format!("AST differs at line {}: expected {:?}, got {:?}", i + 1, el, al));
        }
    }
    Err(format!("AST differs in length: expected {} lines, got {}", e.lines().count(), a.lines().count()))
}

pub fn check_good(stage: Stage, src: &str, expected: &str) -> Outcome {
    match stage(src) {
        Err(Diag::NotImplemented) => Outcome::NotImpl,
        Err(Diag::Error { line, message }) => Outcome::Fail(format!("unexpected error at line {}: {}", line, message)),
        Ok(out) => match compare_ast(expected, &out) {
            Ok(()) => Outcome::Pass,
            Err(m) => Outcome::Fail(m),
        },
    }
}

pub fn check_bad(stage: Stage, src: &str) -> Outcome {
    let Some((line, sub)) = parse_expect(src) else {
        return Outcome::Fail("missing or malformed first line `# expect: LINE: substring`".into());
    };
    match stage(src) {
        Err(Diag::NotImplemented) => Outcome::NotImpl,
        Ok(_) => Outcome::Fail("parsed, expected an error".into()),
        Err(Diag::Error { line: l, message }) => {
            if l != line {
                Outcome::Fail(format!("expected line {}, got line {}: {}", line, l, message))
            } else if !message.contains(&sub) {
                Outcome::Fail(format!("expected message containing {:?}, got {:?}", sub, message))
            } else {
                Outcome::Pass
            }
        }
    }
}

fn files_with_ext(dir: &Path, ext: &str) -> Result<Vec<PathBuf>, String> {
    let mut v = Vec::new();
    for e in fs::read_dir(dir).map_err(|e| format!("{}: {}", dir.display(), e))? {
        let p = e.map_err(|e| e.to_string())?.path();
        if p.is_file() && p.extension().and_then(|x| x.to_str()) == Some(ext) {
            v.push(p);
        }
    }
    v.sort();
    Ok(v)
}

fn stem(p: &Path) -> String {
    p.file_stem().unwrap().to_string_lossy().into_owned()
}

#[derive(Default, Debug, PartialEq, Eq)]
pub struct Summary {
    pub pass: usize,
    pub fail: usize,
    pub not_impl: usize,
}

impl Summary {
    fn add(&mut self, name: &str, o: Outcome) {
        match o {
            Outcome::Pass => {
                self.pass += 1;
                println!("PASS {}", name);
            }
            Outcome::Fail(m) => {
                self.fail += 1;
                println!("FAIL {}: {}", name, m);
            }
            Outcome::NotImpl => {
                self.not_impl += 1;
                println!("NOT-IMPLEMENTED {}", name);
            }
        }
    }
}

/// Run all cases under `root` (the tests/ directory) through `stage`.
pub fn run_all(root: &Path, stage: Stage, update: bool) -> Result<Summary, String> {
    let mut s = Summary::default();
    let corpus = files_with_ext(&root.join("corpus"), "ltn")?;
    let bad = files_with_ext(&root.join("bad"), "ltn")?;
    for p in &corpus {
        let name = stem(p);
        let src = fs::read_to_string(p).map_err(|e| format!("{}: {}", p.display(), e))?;
        let exp_path = root.join("expected").join("ast").join(format!("{}.ast", name));
        if update {
            match stage(&src) {
                Ok(out) => {
                    fs::write(&exp_path, strip_cr(&out)).map_err(|e| e.to_string())?;
                    println!("UPDATED {}", exp_path.display());
                }
                Err(Diag::NotImplemented) => return Err("--update refused: the stage is not implemented".into()),
                Err(Diag::Error { line, message }) => {
                    return Err(format!("--update refused: corpus/{}.ltn fails at line {}: {}", name, line, message))
                }
            }
            continue;
        }
        let label = format!("corpus/{}", name);
        match fs::read_to_string(&exp_path) {
            Err(e) => {
                s.add(&label, Outcome::Fail(format!("cannot read {}: {}", exp_path.display(), e)));
                continue;
            }
            Ok(exp) => {
                s.add(&label, check_good(stage, &src, &exp));
                s.add(&format!("{} [crlf]", label), check_good(stage, &to_crlf(&src), &exp));
            }
        }
    }
    if update {
        return Ok(s);
    }
    for p in &bad {
        let src = fs::read_to_string(p).map_err(|e| format!("{}: {}", p.display(), e))?;
        s.add(&format!("bad/{}", stem(p)), check_bad(stage, &src));
    }
    Ok(s)
}

fn parse_stage(src: &str) -> Result<String, Diag> {
    lantern::parse_to_ast(src)
}

fn main() {
    let mut allow_missing = false;
    let mut update = false;
    let mut stage_name = "parse".to_string();
    let mut root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("tests");
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--allow-missing" => allow_missing = true,
            "--update" => update = true,
            "--stage" => stage_name = args.next().unwrap_or_default(),
            "--root" => root = PathBuf::from(args.next().unwrap_or_default()),
            _ => {
                eprintln!("usage: lantern-tests [--allow-missing] [--update] [--stage parse] [--root DIR]");
                std::process::exit(2);
            }
        }
    }
    if stage_name != "parse" {
        eprintln!("unknown stage {:?} (only `parse` exists)", stage_name);
        std::process::exit(2);
    }
    match run_all(&root, &parse_stage, update) {
        Err(e) => {
            eprintln!("error: {}", e);
            std::process::exit(2);
        }
        Ok(s) => {
            if update {
                return;
            }
            println!("SUMMARY stage={} pass={} fail={} not-implemented={}", stage_name, s.pass, s.fail, s.not_impl);
            if s.fail > 0 || (s.not_impl > 0 && !allow_missing) {
                std::process::exit(1);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn expect_parsing() {
        assert_eq!(parse_expect("# expect: 3: argument needs a name\nx"), Some((3, "argument needs a name".into())));
        assert_eq!(parse_expect("# expect: 12:foo: bar\r\nx"), Some((12, "foo: bar".into())));
        assert_eq!(parse_expect("# expect: x: y"), None);
        assert_eq!(parse_expect("fn main() {}"), None);
        assert_eq!(parse_expect("# expect: 3:"), None);
    }

    #[test]
    fn cr_handling() {
        assert_eq!(strip_cr("a\r\nb\r\n"), "a\nb\n");
        assert_eq!(to_crlf("a\nb\r\nc"), "a\r\nb\r\nc");
    }

    #[test]
    fn comparison() {
        assert!(compare_ast("a\nb\n", "a\r\nb\r\n").is_ok());
        assert!(compare_ast("a\nb\n", "a\nc\n").is_err());
        assert!(compare_ast("a\n", "a\nb\n").is_err());
    }

    #[test]
    fn bad_checks() {
        let src = "# expect: 2: boom\nx";
        let ok = |_: &str| Err(Diag::Error { line: 2, message: "a boom b".into() });
        assert_eq!(check_bad(&ok, src), Outcome::Pass);
        let wrong_line = |_: &str| Err(Diag::Error { line: 3, message: "boom".into() });
        assert!(matches!(check_bad(&wrong_line, src), Outcome::Fail(_)));
        let wrong_msg = |_: &str| Err(Diag::Error { line: 2, message: "other".into() });
        assert!(matches!(check_bad(&wrong_msg, src), Outcome::Fail(_)));
        let parsed = |_: &str| Ok(String::new());
        assert!(matches!(check_bad(&parsed, src), Outcome::Fail(_)));
        let missing = |_: &str| Err(Diag::NotImplemented);
        assert_eq!(check_bad(&missing, src), Outcome::NotImpl);
    }

    fn tmp(tag: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lantern-tests-{}-{}", tag, std::process::id()));
        let _ = fs::remove_dir_all(&d);
        for sub in ["corpus", "bad", "expected/ast"] {
            fs::create_dir_all(d.join(sub)).unwrap();
        }
        d
    }

    #[test]
    fn wrong_expected_file_is_reported_as_fail() {
        let d = tmp("wrong");
        fs::write(d.join("corpus/a.ltn"), "hello\n").unwrap();
        fs::write(d.join("expected/ast/a.ast"), "WRONG\n").unwrap();
        fs::write(d.join("bad/b.ltn"), "# expect: 1: oops\nbad\n").unwrap();
        let echo = |s: &str| -> Result<String, Diag> {
            if s.starts_with("# expect") {
                Err(Diag::Error { line: 1, message: "oops".into() })
            } else {
                Ok(strip_cr(s))
            }
        };
        let s = run_all(&d, &echo, false).unwrap();
        // good fails (plain + crlf), bad passes
        assert_eq!(s, Summary { pass: 1, fail: 2, not_impl: 0 });
        fs::write(d.join("expected/ast/a.ast"), "hello\n").unwrap();
        let s = run_all(&d, &echo, false).unwrap();
        assert_eq!(s, Summary { pass: 3, fail: 0, not_impl: 0 });
        let _ = fs::remove_dir_all(&d);
    }

    #[test]
    fn unimplemented_stage_and_update() {
        let d = tmp("unimpl");
        fs::write(d.join("corpus/a.ltn"), "hello\n").unwrap();
        fs::write(d.join("expected/ast/a.ast"), "hello\n").unwrap();
        let none = |_: &str| Err(Diag::NotImplemented);
        let s = run_all(&d, &none, false).unwrap();
        assert_eq!(s, Summary { pass: 0, fail: 0, not_impl: 2 });
        assert!(run_all(&d, &none, true).is_err());
        assert_eq!(fs::read_to_string(d.join("expected/ast/a.ast")).unwrap(), "hello\n");
        let upper = |s: &str| Ok(s.to_uppercase());
        run_all(&d, &upper, true).unwrap();
        assert_eq!(fs::read_to_string(d.join("expected/ast/a.ast")).unwrap(), "HELLO\n");
        let _ = fs::remove_dir_all(&d);
    }
}
