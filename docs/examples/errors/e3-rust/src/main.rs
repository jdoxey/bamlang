// E3: typed error enums per module, a top-level AppError with From impls, `?` everywhere. std only.
use std::fmt;
use std::sync::{Arc, Mutex};
use std::thread;

mod config {
    use std::fmt;

    #[derive(Debug)]
    pub enum ParseError {
        MissingEquals { line: usize },
        EmptyKey { line: usize },
        DuplicateKey { line: usize, section: String, key: String },
        BadInt { text: String },
    }

    impl fmt::Display for ParseError {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            match self {
                ParseError::MissingEquals { line } => write!(f, "config.ini:{line}: missing '='"),
                ParseError::EmptyKey { line } => write!(f, "config.ini:{line}: empty key"),
                ParseError::DuplicateKey { line, section, key } => {
                    write!(f, "config.ini:{line}: duplicate key '{key}' in [{section}]")
                }
                ParseError::BadInt { text } => write!(f, "not an integer: {text}"),
            }
        }
    }

    impl std::error::Error for ParseError {}

    #[derive(Default)]
    pub struct Config {
        entries: Vec<(String, String, String)>,
    }

    impl Config {
        pub fn get(&self, section: &str, key: &str) -> Option<&str> {
            self.entries
                .iter()
                .find(|e| e.0 == section && e.1 == key)
                .map(|e| e.2.as_str())
        }
        pub fn len(&self) -> usize {
            self.entries.len()
        }
        pub fn keys(&self) -> Vec<&str> {
            self.entries.iter().map(|e| e.1.as_str()).collect()
        }
    }

    #[derive(Default)]
    struct Parser {
        cfg: Config,
        section: String,
    }

    impl Parser {
        fn parse_line(&mut self, no: usize, raw: &str) -> Result<(), ParseError> {
            let line = raw.trim();
            if line.is_empty() || line.starts_with('#') {
                return Ok(());
            }
            if line.starts_with('[') && line.ends_with(']') {
                self.section = line[1..line.len() - 1].to_string();
                return Ok(());
            }
            let Some(i) = line.find('=') else {
                return Err(ParseError::MissingEquals { line: no });
            };
            let key = line[..i].trim();
            if key.is_empty() {
                return Err(ParseError::EmptyKey { line: no });
            }
            if self.cfg.get(&self.section, key).is_some() {
                return Err(ParseError::DuplicateKey {
                    line: no,
                    section: self.section.clone(),
                    key: key.to_string(),
                });
            }
            self.cfg
                .entries
                .push((self.section.clone(), key.to_string(), line[i + 1..].trim().to_string()));
            Ok(())
        }
    }

    pub fn parse(text: &str) -> Result<Config, ParseError> {
        let mut p = Parser::default();
        for (i, l) in text.split('\n').enumerate() {
            p.parse_line(i + 1, l)?;
        }
        Ok(p.cfg)
    }

    pub fn parse_all(text: &str) -> (Config, Vec<ParseError>) {
        let mut p = Parser::default();
        let mut errs = Vec::new();
        for (i, l) in text.split('\n').enumerate() {
            if let Err(e) = p.parse_line(i + 1, l) {
                errs.push(e);
            }
        }
        (p.cfg, errs)
    }

    pub fn parse_int(s: &str) -> Result<i64, ParseError> {
        s.parse::<i64>().map_err(|_| ParseError::BadInt { text: s.to_string() })
    }
}

mod files {
    use std::fmt;
    use std::fs;
    use std::io;
    use std::path::Path;

    #[derive(Debug)]
    pub enum FileError {
        Injected { step: u8, what: &'static str },
        Io { step: u8, what: &'static str, source: io::Error },
    }

    impl fmt::Display for FileError {
        fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            match self {
                FileError::Injected { step, what } => write!(f, "step {step}: {what}: injected failure"),
                FileError::Io { step, what, source } => write!(f, "step {step}: {what}: {source}"),
            }
        }
    }

    impl std::error::Error for FileError {}

    fn io_at(step: u8, what: &'static str) -> impl FnOnce(io::Error) -> FileError {
        move |source| FileError::Io { step, what, source }
    }

    fn inject(fail_at: u8, step: u8, what: &'static str) -> Result<(), FileError> {
        if fail_at == step {
            Err(FileError::Injected { step, what })
        } else {
            Ok(())
        }
    }

    struct Guard<'a> {
        lock: &'a Path,
        tmp: &'a Path,
        held: bool,
    }

    impl Drop for Guard<'_> {
        fn drop(&mut self) {
            // cleanup cannot fail
            if self.held {
                let _ = fs::remove_file(self.lock);
            }
            let _ = fs::remove_file(self.tmp);
        }
    }

    pub fn replace_file(dir: &Path, name: &str, content: &str, fail_at: u8) -> Result<(), FileError> {
        let lock = dir.join(format!("{name}.lock"));
        let tmp = dir.join(format!("{name}.tmp"));
        let dst = dir.join(name);
        let mut g = Guard { lock: &lock, tmp: &tmp, held: false };

        fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock)
            .map_err(io_at(1, "create lock"))?;
        g.held = true;
        inject(fail_at, 1, "create lock")?;
        fs::write(&tmp, content).map_err(io_at(2, "write temp"))?;
        inject(fail_at, 2, "write temp")?;
        inject(fail_at, 3, "rename temp")?;
        fs::rename(&tmp, &dst).map_err(io_at(3, "rename temp"))?;
        inject(fail_at, 4, "remove lock")?;
        fs::remove_file(&lock).map_err(io_at(4, "remove lock"))?;
        g.held = false;
        Ok(())
    }

    pub fn listing(dir: &Path) -> Result<String, io::Error> {
        let mut names = Vec::new();
        for e in fs::read_dir(dir)? {
            names.push(e?.file_name().to_string_lossy().into_owned());
        }
        names.sort();
        Ok(names.join(" "))
    }
}

use config::ParseError;
use files::FileError;

#[derive(Debug)]
enum AppError {
    Parse(ParseError),
    File(FileError),
    Io(std::io::Error),
    Worker { n: usize, source: Box<AppError> },
    Trap { n: usize },
}

impl fmt::Display for AppError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AppError::Parse(e) => write!(f, "{e}"),
            AppError::File(e) => write!(f, "{e}"),
            AppError::Io(e) => write!(f, "{e}"),
            AppError::Worker { n, source } => write!(f, "worker {n}: {source}"),
            AppError::Trap { n } => write!(f, "worker {n}: trapped"),
        }
    }
}

impl std::error::Error for AppError {}

impl From<ParseError> for AppError {
    fn from(e: ParseError) -> Self {
        AppError::Parse(e)
    }
}
impl From<FileError> for AppError {
    fn from(e: FileError) -> Self {
        AppError::File(e)
    }
}
impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::Io(e)
    }
}

const BAD_TEXT: &str = "# sample config\n[server]\nport = 8080\nhost\n= nokey\nport = 9090\n[db]\nname = x\n";
const GOOD_TEXT: &str = "# sample config\n[server]\nport = 8080\nhost = localhost\n[db]\nname = x\n";

fn part1() -> Result<(), AppError> {
    println!("== part 1: config parser");
    if let Err(e) = config::parse(BAD_TEXT) {
        println!("fail-fast: {e}");
    }
    let (_, errs) = config::parse_all(BAD_TEXT);
    println!("collect-all:");
    for e in &errs {
        println!("  {e}");
    }
    println!("{} errors", errs.len());

    let cfg = config::parse(GOOD_TEXT)?;
    if let Some(s) = cfg.get("server", "port") {
        let port = config::parse_int(s)?;
        println!("server.port = {port}");
    }
    match cfg.get("server", "timeout") {
        Some(s) => println!("server.timeout = {s}"),
        None => println!("timeout not set, using 30"),
    }
    Ok(())
}

fn part2() -> Result<(), AppError> {
    println!("== part 2: replace_file");
    let dir = std::env::temp_dir().join(format!("errors-e3-{}", std::process::id()));
    std::fs::create_dir_all(&dir)?;
    let result = part2_in(&dir);
    let _ = std::fs::remove_dir_all(&dir);
    result
}

fn part2_in(dir: &std::path::Path) -> Result<(), AppError> {
    std::fs::write(dir.join("data.txt"), "old")?;
    println!("start: content old");
    let labels = ["no failure", "fail at step 1", "fail at step 2", "fail at step 3", "fail at step 4"];
    for run in 0..5u8 {
        let res = match files::replace_file(dir, "data.txt", &format!("v{}", run + 1), run) {
            Ok(()) => "ok".to_string(),
            Err(e) => format!("error: {}", AppError::from(e)),
        };
        println!("run {}, {}: {}", run + 1, labels[run as usize], res);
        let listing = files::listing(dir)?;
        let content = std::fs::read_to_string(dir.join("data.txt"))?;
        println!("  files: {listing}\n  content: {content}");
    }
    Ok(())
}

const WORKER_TEXTS: [&str; 4] = [
    "[a]\nx = 1\n",
    "[b]\nname = w2\nbroken line\n",
    "[c]\nz = 3\n",
    "[d]\nk = 4\n",
];

fn worker(n: usize, text: &str, shared: &Mutex<usize>) -> Result<usize, AppError> {
    let cfg = config::parse(text).map_err(|e| AppError::Worker { n, source: Box::new(e.into()) })?;
    if n == 3 {
        let mut guard = shared.lock().unwrap();
        let keys = cfg.keys();
        let idx = std::hint::black_box(keys.len() + 5);
        *guard = keys[idx].len(); // out of range: trap (panic) while holding the lock
    }
    Ok(cfg.len())
}

fn part3() -> Result<(), AppError> {
    println!("== part 3: crew");
    std::panic::set_hook(Box::new(|_| {}));
    let shared = Arc::new(Mutex::new(0usize));
    let handles: Vec<_> = WORKER_TEXTS
        .iter()
        .enumerate()
        .map(|(i, text)| {
            let shared = Arc::clone(&shared);
            thread::spawn(move || worker(i + 1, text, &shared))
        })
        .collect();
    let results: Vec<Result<usize, AppError>> = handles
        .into_iter()
        .enumerate()
        .map(|(i, h)| h.join().unwrap_or(Err(AppError::Trap { n: i + 1 })))
        .collect();
    let mut failures = results.iter().filter_map(|r| r.as_ref().err());
    if let Some(first) = failures.next() {
        let more = failures.count();
        if more > 0 {
            println!("error: {first} (plus {more} more)");
        } else {
            println!("error: {first}");
        }
    }
    println!("mutex poisoned: {}", if shared.is_poisoned() { "yes" } else { "no" });
    assert!(matches!(results[2], Err(AppError::Trap { n: 3 })), "worker 3 did not trap");
    println!("expect_trap ok");
    Ok(())
}

fn main() {
    let parts: [fn() -> Result<(), AppError>; 3] = [part1, part2, part3];
    for p in parts {
        if let Err(e) = p() {
            println!("fatal: {e}");
            std::process::exit(1);
        }
    }
}
