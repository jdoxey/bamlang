// IR emission: structured IR -> textual LLVM IR (opaque pointers, no syntax newer than LLVM 17),
// including DWARF/CodeView debug metadata and (optionally) the source-based coverage globals.
use crate::ast::Type;
use crate::ir::*;
use std::collections::HashMap;
use std::fmt::Write;

pub struct Opts { pub win: bool, pub macho: bool, pub file: String, pub dir: String, pub cov: bool, pub triple: String, pub datalayout: String }

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
fn idxs(v: &[usize]) -> String { v.iter().map(|i| i.to_string()).collect::<Vec<_>>().join(", ") }
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
        Type::Struct(n) if m.enums.iter().any(|e| &e.name == n) => 64 + 64 * m.enums.iter().find(|e| &e.name == n).unwrap().width() as u64,
        Type::Struct(n) => m.structs.iter().find(|s| &s.name == n).map(|s| s.fields.iter().map(|(_, t)| size_of(t, m)).sum()).unwrap_or(0),
        _ => 64,
    }
}

pub fn emit(m: &Module, o: &Opts) -> String {
    let mut out = String::new();
    let w = &mut out;
    if !o.triple.is_empty() { writeln!(w, "target triple = \"{}\"", o.triple).unwrap(); }
    if !o.datalayout.is_empty() { writeln!(w, "target datalayout = \"{}\"", o.datalayout).unwrap(); }
    // ---- types and runtime declarations
    for s in &m.structs {
        let f: Vec<String> = s.fields.iter().map(|(_, t)| ty(&crate::lower::lty(t))).collect();
        writeln!(w, "%{} = type {{ {} }}", s.name, f.join(", ")).unwrap();
    }
    // An enum value is { tag, payload } where the payload is as many i64 slots as the widest variant has fields.
    for e in &m.enums { writeln!(w, "%{} = type {{ i64, [{} x i64] }}", e.name, e.width()).unwrap(); }
    // The runtime ABI (runtime.c): traps are raised and caught behind these calls, so the unwinder can change without touching codegen.
    for d in ["void @p3_print(ptr)", "ptr @p3_concat(ptr, ptr)", "ptr @p3_int_to_str(i64)",
        "void @p3_trap(ptr, ptr, ptr)", "void @p3_expect_trap(ptr)", "void @p3_cleanup_drop(ptr, ptr)",
        "ptr @p3_crew_new()", "void @p3_crew_go(ptr, ptr)", "void @p3_crew_join(ptr)", "void @p3_crew_quiet(ptr)",
        "void @llvm.dbg.declare(metadata, metadata, metadata)"] {
        writeln!(w, "declare {}", d).unwrap();
    }
    if o.cov { writeln!(w, "declare void @llvm.instrprof.increment(ptr, i64, i32, i32)").unwrap(); }
    // Cleanups only (no catch clauses): libgcc / compiler-rt's C personality on Linux and macOS, SEH on Windows.
    writeln!(w, "declare i32 @{}(...)", if o.win { "__C_specific_handler" } else { "__gcc_personality_v0" }).unwrap();
    for (i, s) in m.strings.iter().enumerate() {
        writeln!(w, "@.str.{} = private unnamed_addr constant [{} x i8] c\"{}\\00\"", i, s.len() + 1, esc(s)).unwrap();
    }
    writeln!(w, "attributes #0 = {{ uwtable }}").unwrap();

    // ---- debug metadata
    let mut md = Md { nodes: vec![], locs: HashMap::new() };
    let file = md.add(format!("!DIFile(filename: \"{}\", directory: \"{}\")", jesc(&o.file), jesc(&o.dir)));
    let cu = md.add(format!("distinct !DICompileUnit(language: DW_LANG_C99, file: !{}, producer: \"p3 k1 (Rust+LLVM IR)\", isOptimized: false, runtimeVersion: 0, emissionKind: FullDebug)", file));
    let t_int = md.add("!DIBasicType(name: \"Int\", size: 64, encoding: DW_ATE_signed)".into());
    let t_char = md.add("!DIBasicType(name: \"char\", size: 8, encoding: DW_ATE_signed_char)".into());
    let t_str = md.add(format!("!DIDerivedType(tag: DW_TAG_pointer_type, name: \"Str\", baseType: !{}, size: 64)", t_char));
    let comps: HashMap<String, usize> = m.structs.iter().map(|s| s.name.clone()).chain(m.enums.iter().map(|e| e.name.clone())).map(|n| (n, md.reserve())).collect();
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
    // An enum is a struct { tag: enumeration, payload: union { Variant: struct { fields } } }: plain C-style types that
    // gdb, lldb and CodeView all display (DW_TAG_variant_part shows in gdb only).
    for e in &m.enums {
        let w64 = e.width() as u64 * 64;
        let (mut enumerators, mut vmembers) = (vec![], vec![]);
        let uni = md.reserve();
        for (vi, (vn, fields)) in e.variants.iter().enumerate() {
            let en = md.add(format!("!DIEnumerator(name: \"{}\", value: {})", vn, vi));
            enumerators.push(format!("!{}", en));
            let vs = md.reserve();
            let (mut off, mut members) = (0u64, vec![]);
            for (fname, ft) in fields {
                let id = md.add(format!("!DIDerivedType(tag: DW_TAG_member, name: \"{}\", scope: !{}, file: !{}, line: {}, baseType: {}, size: 64, offset: {})", fname, vs, file, e.line, tref(ft), off));
                members.push(format!("!{}", id));
                off += 64;
            }
            let el = md.add(format!("!{{{}}}", members.join(", ")));
            md.nodes[vs] = format!("!DICompositeType(tag: DW_TAG_structure_type, name: \"{}\", scope: !{}, file: !{}, line: {}, size: {}, elements: !{})", vn, uni, file, e.line, off, el);
            let vm = md.add(format!("!DIDerivedType(tag: DW_TAG_member, name: \"{}\", scope: !{}, file: !{}, line: {}, baseType: !{}, size: {}, offset: 0)", vn, uni, file, e.line, vs, off));
            vmembers.push(format!("!{}", vm));
        }
        let uel = md.add(format!("!{{{}}}", vmembers.join(", ")));
        md.nodes[uni] = format!("!DICompositeType(tag: DW_TAG_union_type, name: \"{}.payload\", file: !{}, line: {}, size: {}, elements: !{})", e.name, file, e.line, w64, uel);
        let eel = md.add(format!("!{{{}}}", enumerators.join(", ")));
        let tagty = md.add(format!("!DICompositeType(tag: DW_TAG_enumeration_type, name: \"{}.tag\", file: !{}, line: {}, baseType: !{}, size: 64, elements: !{})", e.name, file, e.line, t_int, eel));
        let m1 = md.add(format!("!DIDerivedType(tag: DW_TAG_member, name: \"tag\", scope: !{}, file: !{}, line: {}, baseType: !{}, size: 64, offset: 0)", comps[&e.name], file, e.line, tagty));
        let m2 = md.add(format!("!DIDerivedType(tag: DW_TAG_member, name: \"payload\", scope: !{}, file: !{}, line: {}, baseType: !{}, size: {}, offset: 64)", comps[&e.name], file, e.line, uni, w64));
        let el = md.add(format!("!{{!{}, !{}}}", m1, m2));
        md.nodes[comps[&e.name]] = format!("!DICompositeType(tag: DW_TAG_structure_type, name: \"{}\", file: !{}, line: {}, size: {}, elements: !{})", e.name, file, e.line, 64 + w64, el);
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
    let pers = if o.win { "ptr @__C_specific_handler" } else { "ptr @__gcc_personality_v0" };
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
                    Inst::Extract { dst, agg, idx } => format!("%t{} = extractvalue {}, {}", dst, typed(agg), idxs(idx)),
                    Inst::Insert { dst, agg, val, idx } => format!("%t{} = insertvalue {}, {}, {}", dst, typed(agg), typed(val), idxs(idx)),
                    Inst::Cast { dst, op: o3, val, to } => format!("%t{} = {} {} to {}", dst, o3, typed(val), ty(to)),
                    Inst::Prof { idx } => format!("call void @llvm.instrprof.increment(ptr @__profn_{}, i64 {}, i32 {}, i32 {})", f.name, crate::cov::func_hash(f), f.ncounters, idx),
                    Inst::Call(c) => {
                        let fl = c.funclet.map(|p| format!(" [ \"funclet\"(token %t{}) ]", p)).unwrap_or_default();
                        format!("{}{}", call_text(c, "call"), fl)
                    }
                    Inst::DbgDeclare { ptr, var } => format!("call void @llvm.dbg.declare(metadata ptr {}, metadata !{}, metadata !DIExpression())", op(ptr), vars[*var]),
                    Inst::Landing { dst } => format!("%t{} = landingpad {{ ptr, i32 }}\n          cleanup", dst),
                    Inst::CleanupPad { dst } => format!("%t{} = cleanuppad within none []", dst),
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
            };
            writeln!(w, "  {}{}", t, l).unwrap();
        }
        writeln!(w, "}}").unwrap();
    }
    // ---- entry point
    writeln!(w, "define i32 @main() #0 {{\n  call void @p3_main()").unwrap();
    writeln!(w, "  ret i32 0\n}}").unwrap();
    if o.cov { emit_cov(w, m, o); }
    // ---- metadata
    let a = md.add("!{i32 2, !\"Debug Info Version\", i32 3}".into());
    let b = md.add(if o.win { "!{i32 2, !\"CodeView\", i32 1}".into() } else { "!{i32 7, !\"Dwarf Version\", i32 4}".into() });
    writeln!(w, "!llvm.dbg.cu = !{{!{}}}\n!llvm.module.flags = !{{!{}, !{}}}", cu, a, b).unwrap();
    for (i, n) in md.nodes.iter().enumerate() { writeln!(w, "!{} = {}", i, n).unwrap(); }
    out
}

// Per-function name globals for llvm.instrprof.increment, one `__covrec_*` record per function and the
// `__llvm_coverage_mapping` file table. Section names follow the object format (ELF, Mach-O, COFF).
fn emit_cov(w: &mut String, m: &Module, o: &Opts) {
    let (mapsec, funsec) = if o.win { (".lcovmap$M", ".lcovfun$M") } else if o.macho { ("__LLVM_COV,__llvm_covmap", "__LLVM_COV,__llvm_covfun") } else { ("__llvm_covmap", "__llvm_covfun") };
    let comdat = !o.macho;
    let bytes = |b: &[u8]| -> String { b.iter().map(|c| format!("\\{:02X}", c)).collect() };
    let blob = crate::cov::filenames_blob(&o.dir, &o.file);
    let fref = crate::cov::md5_low(&blob);
    let mut used = vec![];
    for f in &m.funcs {
        writeln!(w, "@__profn_{} = private constant [{} x i8] c\"{}\"", f.name, f.name.len(), f.name).unwrap();
        let map = crate::cov::mapping(&f.regions);
        let nref = crate::cov::md5_low(f.name.as_bytes());
        let sym = format!("__covrec_{:016X}u", nref as u64);
        if comdat { writeln!(w, "${} = comdat any", sym).unwrap(); }
        writeln!(w, "@{} = linkonce_odr hidden constant <{{ i64, i32, i64, i64, [{} x i8] }}> <{{ i64 {}, i32 {}, i64 {}, i64 {}, [{} x i8] c\"{}\" }}>, section \"{}\"{}, align 8",
            sym, map.len(), nref, map.len(), crate::cov::func_hash(f), fref, map.len(), bytes(&map), funsec, if comdat { ", comdat" } else { "" }).unwrap();
        used.push(format!("ptr @{}", sym));
    }
    // Version 6 on the wire: LLVM 14 to 19 all read it (clang 19 itself writes 7 for the same layout).
    writeln!(w, "@__llvm_coverage_mapping = private constant {{ {{ i32, i32, i32, i32 }}, [{n} x i8] }} {{ {{ i32, i32, i32, i32 }} {{ i32 0, i32 {n}, i32 0, i32 5 }}, [{n} x i8] c\"{}\" }}, section \"{}\", align 8",
        bytes(&blob), mapsec, n = blob.len()).unwrap();
    used.push("ptr @__llvm_coverage_mapping".to_string());
    writeln!(w, "@llvm.used = appending global [{} x ptr] [{}], section \"llvm.metadata\"", used.len(), used.join(", ")).unwrap();
}
