// p3c (K1): Rust compiler for the spike subset. Emits textual LLVM IR; run.sh calls clang.
mod ast;
mod check;
mod emit;
mod ir;
mod lexer;
mod lower;
mod parser;

use std::fmt::Write;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (mut src, mut out, mut target, mut covmap, mut cov) = (None, None, String::new(), None, false);
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-o" => { i += 1; out = Some(args[i].clone()); }
            "--target" => { i += 1; target = args[i].clone(); }
            "--covmap" => { i += 1; covmap = Some(args[i].clone()); }
            "--coverage" => cov = true,
            s => src = Some(s.to_string()),
        }
        i += 1;
    }
    let (src, out) = match (src, out) { (Some(s), Some(o)) => (s, o), _ => { eprintln!("usage: p3c FILE.p3 -o OUT.ll [--target T] [--coverage] [--covmap F]"); std::process::exit(2) } };
    let text = std::fs::read_to_string(&src).unwrap_or_else(|e| { eprintln!("{}: {}", src, e); std::process::exit(2) });
    let fail = |(line, msg): (u32, String)| -> ! { eprintln!("{}:{}: error: {}", src, line, msg); std::process::exit(1) };
    let mut prog = parser::parse(&text).unwrap_or_else(|e| fail(e));
    let info = check::check(&mut prog).unwrap_or_else(|e| fail(e));
    let win = target.contains("windows");
    let module = lower::lower(&prog, &info, win, cov);
    let dir = std::env::current_dir().map(|d| d.to_string_lossy().replace('\\', "/")).unwrap_or_default();
    let file = std::path::Path::new(&src).file_name().unwrap().to_string_lossy().to_string();
    let ll = emit::emit(&module, &emit::Opts { win, file, dir, cov });
    std::fs::write(&out, ll).unwrap();
    if let Some(cm) = covmap {
        let mut s = String::new();
        for (n, a, b) in &module.ranges { writeln!(s, "fn {} {} {}", n, a, b).unwrap(); }
        for l in &module.cov_lines { writeln!(s, "line {}", l).unwrap(); }
        std::fs::write(cm, s).unwrap();
    }
}
