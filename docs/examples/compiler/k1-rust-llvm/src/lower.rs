// Lowering: checked AST -> structured IR. Handles drops (normal exit and unwind cleanups),
// invoke/landing pads (or funclets on Windows), expect_trap, crews, enums/match, and (with
// `cov`) llvm.instrprof counters plus the coverage regions that go with them.
use crate::ast::*;
use crate::check::Info;
use crate::ir::*;
use std::collections::HashMap;



struct Var { ptr: Op, ty: Type }
#[derive(Default)]
struct Scope { vars: HashMap<String, Var>, drops: Vec<(Op, String)> }

struct Cx {
    regs: usize,
    blocks: Vec<Block>,
    cur: usize,
    scopes: Vec<Scope>,
    allocas: Vec<Inst>,
    dbgvars: Vec<DbgVar>,
    lp: HashMap<Vec<usize>, String>,
    nlabel: usize,
    eh: bool,
    funclet: Option<usize>,
    ret: Type,
    ncounters: u32,
    is_last: bool,
    regions: Vec<Region>,
    blk_end: Vec<(u32, u32)>, // end of each enclosing block (for "rest of the block" regions)
}

struct L<'a> {
    info: &'a Info,
    win: bool,
    cov: bool,
    file: String,
    disp: String,
    strings: Vec<String>,
    funcs: Vec<Func>,
    pending: Vec<(String, String, &'a Lambda)>,
    nlambda: usize,
    cx: Cx,
}

fn new_cx(ret: &Type) -> Cx {
    Cx { regs: 0, blocks: vec![], cur: 0, scopes: vec![], allocas: vec![], dbgvars: vec![], lp: HashMap::new(), nlabel: 0, eh: false, funclet: None, ret: ret.clone(), ncounters: 0, is_last: false, regions: vec![], blk_end: vec![] }
}

pub fn lty(t: &Type) -> LTy {
    match t { Type::Int => LTy::I64, Type::Str => LTy::Ptr, Type::Bool => LTy::I1, Type::Unit | Type::Action => LTy::Void, Type::Crew => LTy::Ptr,
        Type::Struct(n) => LTy::Named(format!("%{}", n)) }
}

pub fn lower<'a>(p: &'a Program, info: &'a Info, win: bool, cov: bool, file: &str) -> Module {
    let mut l = L { info, win, cov, file: file.to_string(), disp: String::new(), strings: vec![], funcs: vec![], pending: vec![], nlambda: 0, cx: new_cx(&Type::Unit) };
    for t in &p.types {
        if let Some(d) = &t.drop {
            l.func(&format!("p3_{}_drop", t.name), &format!("{}.drop", t.name), Some(&t.name), &[], &Type::Unit, &d.body, d.line, d.span);
        }
    }
    for f in &p.fns { l.func(&format!("p3_{}", f.name), &f.name, None, &f.params, &f.ret, &f.body, f.line, f.span); }
    while let Some((name, disp, lam)) = l.pending.pop() {
        l.func(&name, &disp, None, &[], &Type::Unit, &lam.body, lam.line, lam.span);
    }
    Module { structs: l.info.structs.clone(), enums: l.info.enums.clone(), funcs: l.funcs, strings: l.strings }
}

impl<'a> L<'a> {
    fn reg(&mut self) -> usize { self.cx.regs += 1; self.cx.regs - 1 }
    fn emit(&mut self, i: Inst, line: u32) { let c = self.cx.cur; self.cx.blocks[c].insts.push((i, line)); }
    fn term(&mut self, t: Term, line: u32) { let c = self.cx.cur; if self.cx.blocks[c].term.is_none() { self.cx.blocks[c].term = Some((t, line)); } }
    fn new_block(&mut self, base: &str) -> usize {
        self.cx.nlabel += 1;
        let label = if base == "entry" { "entry".to_string() } else { format!("{}.{}", base, self.cx.nlabel) };
        self.cx.blocks.push(Block { label, insts: vec![], term: None });
        self.cx.blocks.len() - 1
    }
    fn lbl(&self, b: usize) -> String { self.cx.blocks[b].label.clone() }
    fn string(&mut self, s: &str) -> String {
        let i = match self.strings.iter().position(|x| x == s) { Some(i) => i, None => { self.strings.push(s.to_string()); self.strings.len() - 1 } };
        format!(".str.{}", i)
    }
    fn plain(&mut self, callee: &str, args: Vec<Op>, ret: LTy, line: u32) -> Option<Op> {
        let dst = if ret == LTy::Void { None } else { Some(self.reg()) };
        let ci = CallInfo { dst, ret: ret.clone(), callee: callee.into(), args, funclet: self.cx.funclet };
        self.emit(Inst::Call(ci), line);
        dst.map(|d| Op::Reg(d, ret))
    }
    fn live_drops(&self) -> Vec<(Op, String)> {
        self.cx.scopes.iter().rev().flat_map(|s| s.drops.iter().rev().cloned()).collect()
    }
    // Normal exit: plain drop calls. In a cleanup pad (`shim`): every drop goes through the runtime's
    // p3_cleanup_drop, which catches a trap inside the drop, appends it to the trap chain and returns,
    // so the unwind carries on and the remaining drops still run (ADR-0004 rule 8).
    fn drop_calls(&mut self, drops: &[(Op, String)], line: u32, shim: bool) {
        for (p, s) in drops {
            if s == "$crew" { self.plain("p3_crew_quiet", vec![p.clone()], LTy::Void, line); }
            else if shim { self.plain("p3_cleanup_drop", vec![Op::Global(format!("p3_{}_drop", s)), p.clone()], LTy::Void, line); }
            else { self.plain(&format!("p3_{}_drop", s), vec![p.clone()], LTy::Void, line); }
        }
    }
    // A call that may unwind: an `invoke` to a cleanup block when droppable locals are live.
    fn call(&mut self, callee: &str, args: Vec<Op>, ret: LTy, line: u32) -> Option<Op> {
        let drops = self.live_drops();
        if drops.is_empty() { return self.plain(callee, args, ret, line); }
        let dst = if ret == LTy::Void { None } else { Some(self.reg()) };
        let ci = CallInfo { dst, ret: ret.clone(), callee: callee.into(), args, funclet: self.cx.funclet };
        self.cx.eh = true;
        let unwind = self.cleanup_block(&drops, line);
        let cont = self.new_block("cont");
        let cl = self.lbl(cont);
        self.term(Term::Invoke(ci, cl, unwind), line);
        self.cx.cur = cont;
        dst.map(|d| Op::Reg(d, ret))
    }
    fn cleanup_block(&mut self, drops: &[(Op, String)], line: u32) -> String {
        let key: Vec<usize> = drops.iter().map(|(p, _)| if let Op::Reg(r, _) = p { *r } else { 0 }).collect();
        if let Some(l) = self.cx.lp.get(&key) { return l.clone(); }
        let (saved, saved_f) = (self.cx.cur, self.cx.funclet);
        let b = self.new_block("cleanup");
        self.cx.cur = b;
        if self.win {
            let pad = self.reg();
            self.emit(Inst::CleanupPad { dst: pad }, 0);
            self.cx.funclet = Some(pad);
            self.drop_calls(drops, line, true);
            self.term(Term::CleanupRet(pad), line);
        } else {
            let lp = self.reg();
            self.emit(Inst::Landing { dst: lp }, 0);
            self.drop_calls(drops, line, true);
            self.term(Term::Resume(Op::Reg(lp, LTy::Named("{ ptr, i32 }".into()))), line);
        }
        self.cx.cur = saved;
        self.cx.funclet = saved_f;
        let l = self.lbl(b);
        self.cx.lp.insert(key, l.clone());
        l
    }
    // ---- source-based coverage: one counter per region, incremented with llvm.instrprof.increment.
    fn counter(&mut self) -> Option<u32> {
        if !self.cov { return None; }
        self.cx.ncounters += 1;
        Some(self.cx.ncounters - 1)
    }
    fn prof(&mut self, c: Option<u32>, line: u32) { if let Some(idx) = c { self.emit(Inst::Prof { idx }, line); } }
    fn region(&mut self, kind: Option<RKind>, span: Span) { if let Some(kind) = kind { self.cx.regions.push(Region { kind, span }); } }
    // Counter + region for "the rest of the enclosing block" after a compound statement, if anything follows it.
    fn rest_of_block(&mut self, end: (u32, u32), last: bool, line: u32) {
        if !self.cov || last { return; }
        let c = self.counter();
        self.prof(c, line);
        let (l2, c2) = *self.cx.blk_end.last().unwrap();
        self.region(c.map(RKind::Code), Span { l1: end.0, c1: end.1, l2, c2 });
    }

    fn declare(&mut self, name: &str, ty: &Type, line: u32, arg: Option<usize>, init: Op) -> Op {
        let r = self.reg();
        let lt = lty(ty);
        self.cx.allocas.push(Inst::Alloca { dst: r, ty: lt });
        let ptr = Op::Reg(r, LTy::Ptr);
        self.emit(Inst::Store { val: init, ptr: ptr.clone() }, line);
        if *ty != Type::Bool && *ty != Type::Crew {
            self.cx.dbgvars.push(DbgVar { name: name.into(), ty: ty.clone(), line, arg });
            let var = self.cx.dbgvars.len() - 1;
            self.emit(Inst::DbgDeclare { ptr: ptr.clone(), var }, line);
        }
        let sc = self.cx.scopes.last_mut().unwrap();
        sc.vars.insert(name.into(), Var { ptr: ptr.clone(), ty: ty.clone() });
        if let Type::Struct(s) = ty {
            if self.info.structs.iter().any(|x| &x.name == s && x.has_drop) { self.cx.scopes.last_mut().unwrap().drops.push((ptr.clone(), s.clone())); }
        }
        ptr
    }

    fn func(&mut self, name: &str, disp: &str, self_ty: Option<&str>, params: &[(String, Type)], ret: &Type, body: &'a [Stmt], line: u32, span: Span) {
        let end_line = span.l2;
        self.cx = new_cx(ret);
        self.disp = disp.to_string();
        self.cx.blk_end.push((span.l2, span.c2));
        let entry = self.new_block("entry");
        self.cx.cur = entry;
        self.cx.scopes.push(Scope::default());
        let mut fparams = vec![];
        if let Some(s) = self_ty {
            let r = self.reg();
            fparams.push((r, LTy::Ptr));
            self.cx.scopes[0].vars.insert("self".into(), Var { ptr: Op::Reg(r, LTy::Ptr), ty: Type::Struct(s.into()) });
        }
        let regs: Vec<usize> = params.iter().map(|(_, t)| { let r = self.reg(); fparams.push((r, lty(t))); r }).collect();
        for (i, ((n, t), r)) in params.iter().zip(regs).enumerate() {
            self.declare(n, t, line, Some(i + 1), Op::Reg(r, lty(t)));
        }
        let c0 = self.counter();
        self.prof(c0, line);
        self.region(c0.map(RKind::Code), span);
        self.stmts(body);
        if self.cx.blocks[self.cx.cur].term.is_none() {
            if *ret == Type::Unit {
                let d = self.cx.scopes[0].drops.iter().rev().cloned().collect::<Vec<_>>();
                self.drop_calls(&d, end_line, false);
                self.term(Term::Ret(None), end_line);
            } else { self.term(Term::Unreachable, end_line); }
        }
        let cx = std::mem::replace(&mut self.cx, new_cx(&Type::Unit));
        let mut blocks = cx.blocks;
        let mut pre: Vec<(Inst, u32)> = cx.allocas.into_iter().map(|a| (a, 0)).collect();
        pre.append(&mut blocks[0].insts);
        blocks[0].insts = pre;
        self.funcs.push(Func { name: name.into(), disp: disp.into(), ret: lty(ret), sig: params.iter().map(|(_, t)| t.clone()).collect(),
            ret_ty: ret.clone(), params: fparams, blocks, dbgvars: cx.dbgvars, eh: cx.eh, line, ncounters: cx.ncounters, regions: cx.regions });
    }

    fn stmts(&mut self, v: &'a [Stmt]) {
        let n = v.len();
        for (i, s) in v.iter().enumerate() { self.cx.is_last = i + 1 == n; self.stmt(s); }
    }
    // A `{ }` block: its own scope, drops at the normal end, `span` marks where it ends for "rest of block" regions.
    fn block(&mut self, v: &'a [Stmt], span: Span, line: u32) {
        self.cx.scopes.push(Scope::default());
        self.cx.blk_end.push((span.l2, span.c2));
        self.stmts(v);
        self.cx.blk_end.pop();
        let d = self.cx.scopes.last().unwrap().drops.iter().rev().cloned().collect::<Vec<_>>();
        self.drop_calls(&d, line, false);
        self.cx.scopes.pop();
    }
    fn stmt(&mut self, s: &'a Stmt) {
        let line = s.line;
        let last = self.cx.is_last;
        match &s.kind {
            StmtKind::Let { name, init, .. } => {
                let v = self.expr(init).unwrap();
                self.declare(name, &init.ty, line, None, v);
            }
            StmtKind::Assign { name, op, value } => {
                let v = self.expr(value).unwrap();
                let (ptr, ty) = { let var = self.var(name); (var.ptr.clone(), var.ty.clone()) };
                let nv = match op {
                    None => v,
                    Some(o) => {
                        let cur = self.load(&ty, ptr.clone(), line);
                        self.binop(*o, cur, v, line)
                    }
                };
                self.emit(Inst::Store { val: nv, ptr }, line);
            }
            StmtKind::If { cond, cond_span, then, then_span, els } => {
                let c = self.expr(cond).unwrap();
                let (tb, eb, end) = (self.new_block("then"), self.new_block("else"), self.new_block("endif"));
                let (tl, el, endl) = (self.lbl(tb), self.lbl(eb), self.lbl(end));
                let (ct, cf) = (self.counter(), self.counter());
                if let (Some(t), Some(f)) = (ct, cf) { self.region(Some(RKind::Branch(t, f)), *cond_span); }
                self.term(Term::CondBr(c, tl, el), line);
                self.cx.cur = tb;
                self.prof(ct, line);
                self.region(ct.map(RKind::Code), *then_span);
                self.block(then, *then_span, line);
                self.term(Term::Br(endl.clone()), line);
                self.cx.cur = eb;
                self.prof(cf, line);
                if let Some((e, es)) = els { self.region(cf.map(RKind::Code), *es); self.block(e, *es, line); }
                self.term(Term::Br(endl), line);
                self.cx.cur = end;
                self.rest_of_block(s.end, last, line);
            }
            StmtKind::While { cond, cond_span, body, body_span } => {
                let (cb, bb, end) = (self.new_block("while.cond"), self.new_block("while.body"), self.new_block("while.end"));
                let cl = self.lbl(cb);
                let (cc, cbody, cend) = (self.counter(), self.counter(), self.counter());
                self.term(Term::Br(cl.clone()), line);
                self.cx.cur = cb;
                self.prof(cc, line);
                self.region(cc.map(RKind::Code), *cond_span);
                if let (Some(t), Some(f)) = (cbody, cend) { self.region(Some(RKind::Branch(t, f)), *cond_span); }
                let c = self.expr(cond).unwrap();
                let (bl, el) = (self.lbl(bb), self.lbl(end));
                self.term(Term::CondBr(c, bl, el), line);
                self.cx.cur = bb;
                self.prof(cbody, line);
                self.region(cbody.map(RKind::Code), *body_span);
                self.block(body, *body_span, line);
                self.term(Term::Br(cl), line);
                self.cx.cur = end;
                self.prof(cend, line);
                self.rest_of_block(s.end, last, line);
            }
            StmtKind::Crew { name, body, span } => {
                // crew c { .. }: the handle is a droppable local ("$crew") so a trap in the body still joins the threads;
                // on normal exit the body's locals drop first, then p3_crew_join joins and re-raises the first child trap.
                let h = self.plain("p3_crew_new", vec![], LTy::Ptr, line).unwrap();
                self.cx.scopes.push(Scope::default());
                self.cx.blk_end.push((span.l2, span.c2));
                self.declare(name, &Type::Crew, line, None, h.clone());
                self.cx.scopes.last_mut().unwrap().drops.push((h.clone(), "$crew".into()));
                self.stmts(body);
                self.cx.blk_end.pop();
                let d = self.cx.scopes.last().unwrap().drops.iter().rev().skip(1).cloned().collect::<Vec<_>>();
                self.drop_calls(&d, span.l2, false);
                self.cx.scopes.pop();
                self.call("p3_crew_join", vec![h], LTy::Void, span.l2);
            }
            StmtKind::Return(e) => {
                let v = e.as_ref().and_then(|e| self.expr(e));
                let d = self.live_drops();
                self.drop_calls(&d, line, false);
                self.term(Term::Ret(v), line);
                let dead = self.new_block("dead");
                self.cx.cur = dead;
            }
            StmtKind::Expr(e) => { self.expr(e); }
        }
    }
    fn var(&self, n: &str) -> &Var { self.cx.scopes.iter().rev().find_map(|s| s.vars.get(n)).expect("checked name") }
    fn load(&mut self, ty: &Type, ptr: Op, line: u32) -> Op {
        let (d, lt) = (self.reg(), lty(ty));
        self.emit(Inst::Load { dst: d, ty: lt.clone(), ptr }, line);
        Op::Reg(d, lt)
    }
    fn binop(&mut self, o: BinOp, a: Op, b: Op, line: u32) -> Op {
        let d = self.reg();
        match o {
            BinOp::Add | BinOp::Sub | BinOp::Mul => {
                let op = match o { BinOp::Add => "add", BinOp::Sub => "sub", _ => "mul" };
                self.emit(Inst::Bin { dst: d, op, a, b }, line);
                Op::Reg(d, LTy::I64)
            }
            _ => {
                let pred = match o { BinOp::Lt => "slt", BinOp::Gt => "sgt", _ => "eq" };
                self.emit(Inst::Icmp { dst: d, pred, a, b }, line);
                Op::Reg(d, LTy::I1)
            }
        }
    }
    // Address of a variable or of a field of a variable.
    fn place(&mut self, e: &Expr) -> Op {
        match &e.kind {
            ExprKind::Name(n) => self.var(n).ptr.clone(),
            ExprKind::Field(b, f) => {
                let bp = self.place(b);
                let sn = if let Type::Struct(s) = &b.ty { s.clone() } else { unreachable!() };
                let idx = self.info.structs.iter().find(|s| s.name == sn).unwrap().fields.iter().position(|(n, _)| n == f).unwrap();
                let d = self.reg();
                self.emit(Inst::Field { dst: d, sty: format!("%{}", sn), ptr: bp, idx }, e.line);
                Op::Reg(d, LTy::Ptr)
            }
            _ => unreachable!("checked: fields only on names"),
        }
    }
    fn expr(&mut self, e: &'a Expr) -> Option<Op> {
        let line = e.line;
        match &e.kind {
            ExprKind::Int(n) => Some(Op::Int(*n)),
            ExprKind::Interp(parts) => {
                let mut acc: Option<Op> = None;
                for p in parts {
                    let v = match p {
                        IPart::Lit(s) => Op::Global(self.string(s)),
                        IPart::Expr(x) => {
                            let o = self.expr(x).unwrap();
                            if x.ty == Type::Int { self.plain("p3_int_to_str", vec![o], LTy::Ptr, line).unwrap() } else { o }
                        }
                    };
                    acc = Some(match acc { None => v, Some(a) => self.plain("p3_concat", vec![a, v], LTy::Ptr, line).unwrap() });
                }
                acc
            }
            ExprKind::Name(_) | ExprKind::Field(..) => { let p = self.place(e); Some(self.load(&e.ty, p, line)) }
            ExprKind::Bin(o, l, r) => {
                let (a, b) = (self.expr(l).unwrap(), self.expr(r).unwrap());
                Some(self.binop(*o, a, b, line))
            }
            ExprKind::Lambda(_) | ExprKind::Method { .. } => unreachable!("lambdas appear only inside expect_trap/go; methods are rewritten by the checker"),
            ExprKind::Go { crew, task } => {
                let name = self.new_lambda(task);
                let p = self.var(crew).ptr.clone();
                let h = self.load(&Type::Crew, p, line);
                self.plain("p3_crew_go", vec![h, Op::Global(name)], LTy::Void, line);
                None
            }
            ExprKind::Variant { en, tag, args } => {
                let vals: Vec<Op> = args.iter().map(|a| self.expr(&a.value).unwrap()).collect();
                let lt = LTy::Named(format!("%{}", en));
                let d = self.reg();
                self.emit(Inst::Insert { dst: d, agg: Op::Undef(lt.clone()), val: Op::Int(*tag as i64), idx: vec![0] }, line);
                let mut agg = Op::Reg(d, lt.clone());
                for (i, (v, a)) in vals.into_iter().zip(args).enumerate() {
                    let v = if a.value.ty == Type::Str { self.cast("ptrtoint", v, LTy::I64, line) } else { v };
                    let d = self.reg();
                    self.emit(Inst::Insert { dst: d, agg, val: v, idx: vec![1, i] }, line);
                    agg = Op::Reg(d, lt.clone());
                }
                Some(agg)
            }
            ExprKind::Match { scrut, arms } => {
                let sv = self.expr(scrut).unwrap();
                let tag = self.reg();
                self.emit(Inst::Extract { dst: tag, agg: sv.clone(), idx: vec![0] }, line);
                let rt = lty(&e.ty);
                let slot = self.reg();
                self.cx.allocas.push(Inst::Alloca { dst: slot, ty: rt.clone() });
                let join = self.new_block("match.end");
                let jl = self.lbl(join);
                for (i, a) in arms.iter().enumerate() {
                    let ab = self.new_block("arm");
                    let next = if i + 1 < arms.len() {
                        let nb = self.new_block("arm.next");
                        let cmp = self.reg();
                        self.emit(Inst::Icmp { dst: cmp, pred: "eq", a: Op::Reg(tag, LTy::I64), b: Op::Int(a.tag as i64) }, a.line);
                        let (al, nl) = (self.lbl(ab), self.lbl(nb));
                        self.term(Term::CondBr(Op::Reg(cmp, LTy::I1), al, nl), a.line);
                        Some(nb)
                    } else { let al = self.lbl(ab); self.term(Term::Br(al), a.line); None };
                    self.cx.cur = ab;
                    let c = self.counter();
                    self.prof(c, a.line);
                    self.region(c.map(RKind::Code), a.span);
                    self.cx.scopes.push(Scope::default());
                    for (j, (b, bt)) in a.binders.iter().zip(&a.btys).enumerate() {
                        let d = self.reg();
                        self.emit(Inst::Extract { dst: d, agg: sv.clone(), idx: vec![1, j] }, a.line);
                        let mut v = Op::Reg(d, LTy::I64);
                        if *bt == Type::Str { v = self.cast("inttoptr", v, LTy::Ptr, a.line); }
                        self.declare(b, bt, a.line, None, v);
                    }
                    let v = self.expr(&a.body).unwrap();
                    self.emit(Inst::Store { val: v, ptr: Op::Reg(slot, LTy::Ptr) }, a.line);
                    self.cx.scopes.pop();
                    self.term(Term::Br(jl.clone()), a.line);
                    if let Some(nb) = next { self.cx.cur = nb; }
                }
                self.cx.cur = join;
                Some(self.load(&e.ty, Op::Reg(slot, LTy::Ptr), line))
            }
            ExprKind::Call { name, args } => {
                match name.as_str() {
                    "print" => { let a = self.expr(&args[0].value).unwrap(); self.plain("p3_print", vec![a], LTy::Void, line); None }
                    "trap" => {
                        let a = self.expr(&args[0].value).unwrap();
                        let loc = Op::Global(self.string(&format!("{}:{}", self.file, line)));
                        let f = Op::Global(self.string(&self.disp.clone()));
                        self.call("p3_trap", vec![a, loc, f], LTy::Void, line);
                        None
                    }
                    "expect_trap" => {
                        if let ExprKind::Lambda(l) = &args[0].value.kind {
                            let name = self.new_lambda(l);
                            self.plain("p3_expect_trap", vec![Op::Global(name)], LTy::Void, line);
                        } else { unreachable!() }
                        None
                    }
                    _ => {
                        let vals: Vec<Op> = args.iter().map(|a| self.expr(&a.value).unwrap()).collect();
                        if let Some(si) = self.info.structs.iter().find(|s| &s.name == name) {
                            let lt = LTy::Named(format!("%{}", si.name));
                            let mut agg = Op::Undef(lt.clone());
                            for (i, v) in vals.into_iter().enumerate() {
                                let d = self.reg();
                                self.emit(Inst::Insert { dst: d, agg, val: v, idx: vec![i] }, line);
                                agg = Op::Reg(d, lt.clone());
                            }
                            Some(agg)
                        } else {
                            self.call(&format!("p3_{}", name), vals, lty(&e.ty), line)
                        }
                    }
                }
            }
        }
    }

    // Hoist a capture-free lambda to a top-level function and return its symbol.
    fn new_lambda(&mut self, l: &'a Lambda) -> String {
        let name = format!("p3_lambda{}", self.nlambda);
        self.pending.push((name.clone(), format!("lambda{}", self.nlambda), l));
        self.nlambda += 1;
        name
    }
    fn cast(&mut self, op: &'static str, val: Op, to: LTy, line: u32) -> Op {
        let d = self.reg();
        self.emit(Inst::Cast { dst: d, op, val, to: to.clone() }, line);
        Op::Reg(d, to)
    }
}
