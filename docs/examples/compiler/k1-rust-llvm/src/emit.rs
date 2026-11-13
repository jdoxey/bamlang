// IR emission: structured IR -> textual LLVM IR (opaque pointers, no syntax newer than LLVM 17),
// including DWARF/CodeView debug metadata and (optionally) the line-counter table.
use crate::ast::Type;
use crate::ir::*;
use std::collections::HashMap;
use std::fmt::Write;

pub struct Opts { pub win: bool, pub file: String, pub dir: String, pub cov: bool }

fn ty(t: &LTy) -> String {
    match t { LTy::I64 => "i64".into(), LTy::I1 => "i1".into(), LTy::Ptr => "ptr".into(), LTy::Void => "void".into(),
        LTy::Token => "token".into(), LTy::Named(n) => n.clone() }
}
fn opty(o: &Op) -> LTy {
    match o { Op::Reg(_, t) | Op::Undef(t) => t.clone(), Op::Int(_) => LTy::I64, Op::Global(_) => LTy::Ptr }
}
fn op(o: &Op) -> String {
    match o { Op::Reg(n, _) => format!("%t{}", n), Op::Int(n) => n.to_string(), Op::Global(g) => format!("@{}", g), Op::Undef(_) => "undef".into() }
}
fn typed(o: &Op) -> String { format!("{} {}", ty(&opty(o)), op(o)) }
fn esc(s: &str) -> String {
    s.bytes().map(|b| if (32..127).contains(&b) && b != b'"' && b != b'\\' { (b as char).to_string() } else { format!("\\{:02X}", b) }).collect()
}
fn jesc(s: &str) -> String { s.replace('\\', "\\\\").replace('"', "\\\"") }

struct Md { nodes: Vec<String>, locs: HashMap<(usize, u32), usize> }
impl Md {
    fn add(&mut self, s: String) -> usize { self.nodes.push(s); self.nodes.len() - 1 }
    fn reserve(&mut self) -> usize { self.add(String::new()) }
}

fn call_text(c: &CallInfo, kw: &str) -> String {
    let args: Vec<String> = c.args.iter().map(typed).collect();
    let d = c.dst.map(|d| format!("%t{} = ", d)).unwrap_or_default();
    format!("{}{} {} @{}({})", d, kw, ty(&c.ret), c.callee, args.join(", "))
}

fn size_of(t: &Type, m: &crate::ir::Module) -> u64 {
    match t {
        Type::Struct(n) => m.structs.iter().find(|s| &s.name == n).map(|s| s.fields.iter().map(|(_, t)| size_of(t, m)).sum()).unwrap_or(0),
        _ => 64,
    }
}

pub fn emit(m: &Module, o: &Opts) -> String {
    let mut out = String::new();
    let w = &mut out;
    if o.win { writeln!(w, "target triple = \"x86_64-pc-windows-msvc\"").unwrap(); }
    // ---- types and runtime declarations
    for s in &m.structs {
        let f: Vec<String> = s.fields.iter().map(|(_, t)| ty(&crate::lower::lty(t))).collect();
        writeln!(w, "%{} = type {{ {} }}", s.name, f.join(", ")).unwrap();
    }
    for d in ["void @p3_print(ptr)", "ptr @p3_concat(ptr, ptr)", "ptr @p3_int_to_str(i64)", "void @p3_trap(ptr)", "ptr @p3_trap_message()",
        "void @p3_cov_dump(ptr, i64)", "void @llvm.dbg.declare(metadata, metadata, metadata)"] {
        writeln!(w, "declare {}", d).unwrap();
    }
    if o.win {
        writeln!(w, "declare i32 @__CxxFrameHandler3(...)").unwrap();
    } else {
        writeln!(w, "declare i32 @__gxx_personality_v0(...)\ndeclare ptr @__cxa_begin_catch(ptr)\ndeclare void @__cxa_end_catch()").unwrap();
    }
    for (i, s) in m.strings.iter().enumerate() {
        writeln!(w, "@.str.{} = private unnamed_addr constant [{} x i8] c\"{}\\00\"", i, s.len() + 1, esc(s)).unwrap();
    }
    let cov_n = m.cov_lines.iter().next_back().map(|l| *l as usize + 1).unwrap_or(0);
    if o.cov { writeln!(w, "@__p3_cov = internal global [{} x i64] zeroinitializer", cov_n).unwrap(); }
    writeln!(w, "attributes #0 = {{ uwtable }}").unwrap();

    // ---- debug metadata
    let mut md = Md { nodes: vec![], locs: HashMap::new() };
    let file = md.add(format!("!DIFile(filename: \"{}\", directory: \"{}\")", jesc(&o.file), jesc(&o.dir)));
    let cu = md.add(format!("distinct !DICompileUnit(language: DW_LANG_C99, file: !{}, producer: \"p3 k1 (Rust+LLVM IR)\", isOptimized: false, runtimeVersion: 0, emissionKind: FullDebug)", file));
    let t_int = md.add("!DIBasicType(name: \"Int\", size: 64, encoding: DW_ATE_signed)".into());
    let t_char = md.add("!DIBasicType(name: \"char\", size: 8, encoding: DW_ATE_signed_char)".into());
    let t_str = md.add(format!("!DIDerivedType(tag: DW_TAG_pointer_type, name: \"Str\", baseType: !{}, size: 64)", t_char));
    let comps: HashMap<String, usize> = m.structs.iter().map(|s| (s.name.clone(), md.reserve())).collect();
    let tref = |t: &Type| -> String {
        match t { Type::Int => format!("!{}", t_int), Type::Str => format!("!{}", t_str), Type::Struct(n) => format!("!{}", comps[n]), _ => "null".into() }
    };
    for s in &m.structs {
        let (mut off, mut members) = (0u64, vec![]);
        for (fname, ft) in &s.fields {
            let sz = size_of(ft, m);
            let id = md.add(format!("!DIDerivedType(tag: DW_TAG_member, name: \"{}\", scope: !{}, file: !{}, line: {}, baseType: {}, size: {}, offset: {})",
                fname, comps[&s.name], file, s.line, tref(ft), sz, off));
            members.push(format!("!{}", id));
            off += sz;
        }
        let el = md.add(format!("!{{{}}}", members.join(", ")));
        md.nodes[comps[&s.name]] = format!("!DICompositeType(tag: DW_TAG_structure_type, name: \"{}\", file: !{}, line: {}, size: {}, elements: !{})", s.name, file, s.line, off, el);
    }
    let sps: Vec<usize> = m.funcs.iter().map(|f| {
        let mut tys = vec![tref(&f.ret_ty)];
        tys.extend(f.sig.iter().map(|t| tref(t)));
        let tt = md.add(format!("!{{{}}}", tys.join(", ")));
        let st = md.add(format!("!DISubroutineType(types: !{})", tt));
        md.add(format!("distinct !DISubprogram(name: \"{}\", linkageName: \"{}\", scope: !{}, file: !{}, line: {}, type: !{}, scopeLine: {}, spFlags: DISPFlagDefinition, unit: !{}, retainedNodes: !{{}})",
            f.disp, f.name, file, file, f.line, st, f.line, cu))
    }).collect();

    // ---- functions
    let pers = if o.win { "ptr @__CxxFrameHandler3" } else { "ptr @__gxx_personality_v0" };
    for (fi, f) in m.funcs.iter().enumerate() {
        let sp = sps[fi];
        let params: Vec<String> = f.params.iter().map(|(r, t)| format!("{} %t{}", ty(t), r)).collect();
        writeln!(w, "define {} @{}({}) #0 {}!dbg !{} {{", ty(&f.ret), f.name, params.join(", "),
            if f.eh { format!("personality {} ", pers) } else { String::new() }, sp).unwrap();
        let vars: Vec<usize> = f.dbgvars.iter().map(|v| {
            let arg = v.arg.map(|a| format!("arg: {}, ", a)).unwrap_or_default();
            md.add(format!("!DILocalVariable(name: \"{}\", {}scope: !{}, file: !{}, line: {}, type: {})", v.name, arg, sp, file, v.line, tref(&v.ty)))
        }).collect();
        let mut loc = |md: &mut Md, line: u32| -> String {
            if line == 0 { return String::new(); }
            let id = match md.locs.get(&(sp, line)) { Some(i) => *i, None => { let i = md.add(format!("!DILocation(line: {}, scope: !{})", line, sp)); md.locs.insert((sp, line), i); i } };
            format!(", !dbg !{}", id)
        };
        for b in &f.blocks {
            writeln!(w, "{}:", b.label).unwrap();
            for (i, line) in &b.insts {
                let l = loc(&mut md, *line);
                let t = match i {
                    Inst::Alloca { dst, ty: t } => format!("%t{} = alloca {}, align 8", dst, ty(t)),
                    Inst::Store { val, ptr } => format!("store {}, ptr {}", typed(val), op(ptr)),
                    Inst::Load { dst, ty: t, ptr } => format!("%t{} = load {}, ptr {}", dst, ty(t), op(ptr)),
                    Inst::Bin { dst, op: o2, a, b } => format!("%t{} = {} i64 {}, {}", dst, o2, op(a), op(b)),
                    Inst::Icmp { dst, pred, a, b } => format!("%t{} = icmp {} i64 {}, {}", dst, pred, op(a), op(b)),
                    Inst::Field { dst, sty, ptr, idx } => format!("%t{} = getelementptr inbounds {}, ptr {}, i32 0, i32 {}", dst, sty, op(ptr), idx),
                    Inst::Elem { dst, base, idx } => format!("%t{} = getelementptr inbounds i64, ptr {}, i64 {}", dst, op(base), idx),
                    Inst::Extract { dst, agg, idx, .. } => format!("%t{} = extractvalue {}, {}", dst, typed(agg), idx),
                    Inst::Insert { dst, agg, val, idx, .. } => format!("%t{} = insertvalue {}, {}, {}", dst, typed(agg), typed(val), idx),
                    Inst::Call(c) => {
                        let fl = c.funclet.map(|p| format!(" [ \"funclet\"(token %t{}) ]", p)).unwrap_or_default();
                        format!("{}{}", call_text(c, "call"), fl)
                    }
                    Inst::DbgDeclare { ptr, var } => format!("call void @llvm.dbg.declare(metadata ptr {}, metadata !{}, metadata !DIExpression())", op(ptr), vars[*var]),
                    Inst::Landing { dst, catch } => format!("%t{} = landingpad {{ ptr, i32 }}\n          {}", dst, if *catch { "catch ptr null" } else { "cleanup" }),
                    Inst::CleanupPad { dst } => format!("%t{} = cleanuppad within none []", dst),
                    Inst::CatchPad { dst, sw } => format!("%t{} = catchpad within %t{} [ptr null, i32 64, ptr null]", dst, sw),
                };
                writeln!(w, "  {}{}", t, l).unwrap();
            }
            let (t, line) = b.term.as_ref().expect("block without terminator");
            let l = loc(&mut md, *line);
            let t = match t {
                Term::Br(x) => format!("br label %{}", x),
                Term::CondBr(c, a, b2) => format!("br i1 {}, label %{}, label %{}", op(c), a, b2),
                Term::Ret(None) => "ret void".into(),
                Term::Ret(Some(v)) => format!("ret {}", typed(v)),
                Term::Unreachable => "unreachable".into(),
                Term::Resume(v) => format!("resume {}", typed(v)),
                Term::Invoke(c, n, u) => format!("{} to label %{} unwind label %{}", call_text(c, "invoke"), n, u),
                Term::CleanupRet(p) => format!("cleanupret from %t{} unwind to caller", p),
                Term::CatchRet(p, to) => format!("catchret from %t{} to label %{}", p, to),
                Term::CatchSwitch { dst, handler } => format!("%t{} = catchswitch within none [label %{}] unwind to caller", dst, handler),
            };
            writeln!(w, "  {}{}", t, l).unwrap();
        }
        writeln!(w, "}}").unwrap();
    }
    // ---- entry point
    writeln!(w, "define i32 @main() #0 {{\n  call void @p3_main()").unwrap();
    if o.cov { writeln!(w, "  call void @p3_cov_dump(ptr @__p3_cov, i64 {})", cov_n).unwrap(); }
    writeln!(w, "  ret i32 0\n}}").unwrap();
    // ---- metadata
    let a = md.add("!{i32 2, !\"Debug Info Version\", i32 3}".into());
    let b = md.add(if o.win { "!{i32 2, !\"CodeView\", i32 1}".into() } else { "!{i32 7, !\"Dwarf Version\", i32 4}".into() });
    writeln!(w, "!llvm.dbg.cu = !{{!{}}}\n!llvm.module.flags = !{{!{}, !{}}}", cu, a, b).unwrap();
    for (i, n) in md.nodes.iter().enumerate() { writeln!(w, "!{} = {}", i, n).unwrap(); }
    out
}
