// p3c (K1): Rust compiler for the spike subset. Emits textual LLVM IR; run.sh calls clang.
mod ast;
mod check;
mod cov;
mod emit;
mod ir;
mod lexer;
mod lower;
mod parser;

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let (mut src, mut out, mut triple, mut datalayout, mut cov) = (None, None, String::new(), String::new(), false);
    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "-o" => { i += 1; out = Some(args[i].clone()); }
            "--triple" => { i += 1; triple = args[i].clone(); }
            "--datalayout" => { i += 1; datalayout = args[i].clone(); }
            "--coverage" => cov = true,
            s => src = Some(s.to_string()),
        }
        i += 1;
    }
    let (src, out) = match (src, out) { (Some(s), Some(o)) => (s, o), _ => { eprintln!("usage: p3c FILE.p3 -o OUT.ll [--triple T] [--datalayout D] [--coverage]"); std::process::exit(2) } };
    let text = std::fs::read_to_string(&src).unwrap_or_else(|e| { eprintln!("{}: {}", src, e); std::process::exit(2) });
    let fail = |(line, msg): (u32, String)| -> ! { eprintln!("{}:{}: error: {}", src, line, msg); std::process::exit(1) };
    let mut prog = parser::parse(&text).unwrap_or_else(|e| fail(e));
    let info = check::check(&mut prog).unwrap_or_else(|e| fail(e));
    let win = triple.contains("windows");
    let macho = triple.contains("apple") || triple.contains("darwin");
    let dir = std::env::current_dir().map(|d| d.to_string_lossy().replace('\\', "/")).unwrap_or_default();
    let file = std::path::Path::new(&src).file_name().unwrap().to_string_lossy().to_string();
    let module = lower::lower(&prog, &info, win, cov, &file);
    let ll = emit::emit(&module, &emit::Opts { win, macho, file, dir, cov, triple, datalayout });
    std::fs::write(&out, ll).unwrap();
}
