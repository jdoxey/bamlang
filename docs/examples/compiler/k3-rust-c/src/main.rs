// k3c: Rust compiler for the D8 spike subset. Emits C and drives clang.
mod ast;
mod check;
mod covmap;
mod emit;
mod lexer;
mod lower;
mod parser;

use std::process::{exit, Command};

const RT_H: &str = include_str!("../runtime/p3rt.h");
const RT_C: &str = include_str!("../runtime/p3rt.c");

fn die(file: &str, msg: &str) -> ! {
    eprintln!("{}:{}", file, msg.replacen(": ", ": error: ", 1));
    exit(1);
}

fn run(cmd: &mut Command) {
    let st = cmd.status().unwrap_or_else(|e| { eprintln!("cannot run {:?}: {}", cmd.get_program(), e); exit(2) });
    if !st.success() { eprintln!("command failed: {:?}", cmd); exit(2); }
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.first().map(|a| a.as_str()) == Some("--cov-remap") {
        // k3c --cov-remap export.json file.c.map file.p3 out.lcov
        if args.len() != 5 { eprintln!("usage: k3c --cov-remap export.json file.c.map file.p3 out.lcov"); exit(2) }
        covmap::remap(&args[1], &args[2], &args[3], &args[4]).unwrap_or_else(|e| { eprintln!("cov-remap: {}", e); exit(1) });
        return;
    }
    let (mut input, mut out, mut cov, mut emit_only) = (None, "a.out".to_string(), false, false);
    let (mut opt, mut no_cleanup, mut no_inline) = (false, false, false);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-o" => out = it.next().expect("-o needs a path").clone(),
            "--coverage" => cov = true,
            "--emit-c" => emit_only = true,
            "--opt" => opt = true,
            "--no-inline" => no_inline = true, // benchmark only: keep calls real at -O2
            "--no-cleanup" => no_cleanup = true, // benchmark only: drops are direct calls, traps skip them
            _ => input = Some(a.clone()),
        }
    }
    let input = input.unwrap_or_else(|| { eprintln!("usage: k3c [--coverage] [--emit-c] [--opt] [--no-inline] [--no-cleanup] file.p3 -o exe"); exit(2) });
    let src = std::fs::read_to_string(&input).unwrap_or_else(|e| { eprintln!("{}: {}", input, e); exit(2) });
    let shown = std::path::Path::new(&input).file_name().unwrap().to_string_lossy().to_string();

    let mut prog = parser::parse_program(&src).unwrap_or_else(|e| die(&shown, &e));
    check::check(&mut prog).unwrap_or_else(|e| die(&shown, &e));
    let c = emit::emit(&lower::lower(&prog, &shown), &shown, no_cleanup);
    let map = emit::line_map(&c, &shown);

    let dir = std::path::Path::new(&out).parent().map(|p| p.to_path_buf()).filter(|p| !p.as_os_str().is_empty()).unwrap_or(".".into());
    let stem = std::path::Path::new(&out).file_stem().unwrap().to_string_lossy().to_string();
    let (cf, rh, rc) = (dir.join(format!("{}.c", stem)), dir.join("p3rt.h"), dir.join("p3rt.c"));
    std::fs::write(&cf, c).unwrap();
    std::fs::write(dir.join(format!("{}.c.map", stem)), map).unwrap();
    std::fs::write(&rh, RT_H).unwrap();
    std::fs::write(&rc, RT_C).unwrap();
    if emit_only { return; }

    let win = cfg!(windows);
    let mut base: Vec<String> = vec!["-g".into(), (if opt { "-O2" } else { "-O0" }).into(), "-std=c11".into(), "-Wall".into(), "-Wno-unused-value".into()];
    if win { base.push("-gcodeview".into()); }
    if no_inline { base.push("-fno-inline".into()); }
    let obj = |p: &std::path::Path| p.with_extension("o");
    // generated code gets coverage instrumentation, the runtime does not
    let mut c1 = Command::new("clang");
    c1.args(&base).arg("-I").arg(&dir);
    if cov { c1.args(["-fprofile-instr-generate", "-fcoverage-mapping"]); }
    run(c1.arg("-c").arg(&cf).arg("-o").arg(obj(&cf)));
    run(Command::new("clang").args(&base).arg("-I").arg(&dir).arg("-c").arg(&rc).arg("-o").arg(obj(&rc)));
    let mut l = Command::new("clang");
    l.args(&base);
    if win { l.arg("-fuse-ld=lld"); } else { l.arg("-pthread"); }
    if cov { l.arg("-fprofile-instr-generate"); }
    run(l.arg(obj(&cf)).arg(obj(&rc)).arg("-o").arg(&out));
}
