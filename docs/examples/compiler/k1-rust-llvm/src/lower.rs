// Lowering: checked AST -> structured IR. Handles drops (normal exit and unwind cleanups),
// invoke/landing pads (or funclets on Windows), expect_trap, and optional line counters.
use crate::ast::*;
use crate::check::Info;
use crate::ir::*;
use std::collections::{BTreeSet, HashMap};

const LP_TY: &str = "{ ptr, i32 }";

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
}

struct L<'a> {
    info: &'a Info,
    win: bool,
    cov: bool,
    strings: Vec<String>,
    funcs: Vec<Func>,
    pending: Vec<(String, String, &'a Lambda)>,
    nlambda: usize,
    cov_lines: BTreeSet<u32>,
    ranges: Vec<(String, u32, u32)>,
    cx: Cx,
}

fn new_cx(ret: &Type) -> Cx {
    Cx { regs: 0, blocks: vec![], cur: 0, scopes: vec![], allocas: vec![], dbgvars: vec![], lp: HashMap::new(), nlabel: 0, eh: false, funclet: None, ret: ret.clone() }
}

pub fn lty(t: &Type) -> LTy {
    match t { Type::Int => LTy::I64, Type::Str => LTy::Ptr, Type::Bool => LTy::I1, Type::Unit | Type::Action => LTy::Void,
        Type::Struct(n) => LTy::Named(format!("%{}", n)) }
}

pub fn lower<'a>(p: &'a Program, info: &'a Info, win: bool, cov: bool) -> Module {
    let mut l = L { info, win, cov, strings: vec![], funcs: vec![], pending: vec![], nlambda: 0, cov_lines: BTreeSet::new(), ranges: vec![], cx: new_cx(&Type::Unit) };
    for t in &p.types {
        if let Some(d) = &t.drop {
            l.func(&format!("p3_{}_drop", t.name), &format!("{}.drop", t.name), Some(&t.name), &[], &Type::Unit, &d.body, d.line, d.end_line);
        }
    }
    for f in &p.fns { l.func(&format!("p3_{}", f.name), &f.name, None, &f.params, &f.ret, &f.body, f.line, f.end_line); }
    while let Some((name, disp, lam)) = l.pending.pop() {
        l.func(&name, &disp, None, &[], &Type::Unit, &lam.body, lam.line, lam.end_line);
    }
    Module { structs: l.info.structs.clone(),
        funcs: l.funcs, strings: l.strings, cov_lines: l.cov_lines, ranges: l.ranges }
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
    fn drop_calls(&mut self, drops: &[(Op, String)], line: u32) {
        for (p, s) in drops { self.plain(&format!("p3_{}_drop", s), vec![p.clone()], LTy::Void, line); }
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
            self.drop_calls(drops, line);
            self.term(Term::CleanupRet(pad), line);
        } else {
            let lp = self.reg();
            self.emit(Inst::Landing { dst: lp, catch: false }, 0);
            self.drop_calls(drops, line);
            self.term(Term::Resume(Op::Reg(lp, LTy::Named(LP_TY.into()))), line);
        }
        self.cx.cur = saved;
        self.cx.funclet = saved_f;
        let l = self.lbl(b);
        self.cx.lp.insert(key, l.clone());
        l
    }
    fn cov_mark(&mut self, line: u32) {
        if !self.cov { return; }
        self.cov_lines.insert(line);
        let (g, v, n) = (self.reg(), self.reg(), self.reg());
        self.emit(Inst::Elem { dst: g, base: Op::Global("__p3_cov".into()), idx: line as i64 }, line);
        self.emit(Inst::Load { dst: v, ty: LTy::I64, ptr: Op::Reg(g, LTy::Ptr) }, line);
        self.emit(Inst::Bin { dst: n, op: "add", a: Op::Reg(v, LTy::I64), b: Op::Int(1) }, line);
        self.emit(Inst::Store { val: Op::Reg(n, LTy::I64), ptr: Op::Reg(g, LTy::Ptr) }, line);
    }

    fn declare(&mut self, name: &str, ty: &Type, line: u32, arg: Option<usize>, init: Op) -> Op {
        let r = self.reg();
        let lt = lty(ty);
        self.cx.allocas.push(Inst::Alloca { dst: r, ty: lt });
        let ptr = Op::Reg(r, LTy::Ptr);
        self.emit(Inst::Store { val: init, ptr: ptr.clone() }, line);
        if *ty != Type::Bool {
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

    fn func(&mut self, name: &str, disp: &str, self_ty: Option<&str>, params: &[(String, Type)], ret: &Type, body: &'a [Stmt], line: u32, end_line: u32) {
        self.cx = new_cx(ret);
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
        self.cov_mark(line);
        self.ranges.push((disp.to_string(), line, end_line));
        self.stmts(body);
        if self.cx.blocks[self.cx.cur].term.is_none() {
            if *ret == Type::Unit {
                let d = self.cx.scopes[0].drops.iter().rev().cloned().collect::<Vec<_>>();
                self.drop_calls(&d, end_line);
                self.term(Term::Ret(None), end_line);
            } else { self.term(Term::Unreachable, end_line); }
        }
        let cx = std::mem::replace(&mut self.cx, new_cx(&Type::Unit));
        let mut blocks = cx.blocks;
        let mut pre: Vec<(Inst, u32)> = cx.allocas.into_iter().map(|a| (a, 0)).collect();
        pre.append(&mut blocks[0].insts);
        blocks[0].insts = pre;
        self.funcs.push(Func { name: name.into(), disp: disp.into(), ret: lty(ret), sig: params.iter().map(|(_, t)| t.clone()).collect(),
            ret_ty: ret.clone(), params: fparams, blocks, dbgvars: cx.dbgvars, eh: cx.eh, line });
    }

    fn stmts(&mut self, v: &'a [Stmt]) { for s in v { self.stmt(s); } }
    fn scoped(&mut self, v: &'a [Stmt], line: u32) {
        self.cx.scopes.push(Scope::default());
        self.stmts(v);
        let d = self.cx.scopes.last().unwrap().drops.iter().rev().cloned().collect::<Vec<_>>();
        self.drop_calls(&d, line);
        self.cx.scopes.pop();
    }
    fn stmt(&mut self, s: &'a Stmt) {
        let line = s.line;
        match &s.kind {
            StmtKind::Let { name, init, .. } => {
                self.cov_mark(line);
                let v = self.expr(init).unwrap();
                self.declare(name, &init.ty, line, None, v);
            }
            StmtKind::Assign { name, op, value } => {
                self.cov_mark(line);
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
            StmtKind::If { cond, then, els } => {
                self.cov_mark(line);
                let c = self.expr(cond).unwrap();
                let (tb, eb, end) = (self.new_block("then"), self.new_block("else"), self.new_block("endif"));
                let (tl, el, endl) = (self.lbl(tb), self.lbl(eb), self.lbl(end));
                self.term(Term::CondBr(c, tl, if els.is_some() { el } else { endl.clone() }), line);
                self.cx.cur = tb;
                self.scoped(then, line);
                self.term(Term::Br(endl.clone()), line);
                self.cx.cur = eb;
                if let Some(e) = els { self.scoped(e, line); }
                self.term(Term::Br(endl), line);
                self.cx.cur = end;
            }
            StmtKind::While { cond, body } => {
                let (cb, bb, end) = (self.new_block("while.cond"), self.new_block("while.body"), self.new_block("while.end"));
                let cl = self.lbl(cb);
                self.term(Term::Br(cl.clone()), line);
                self.cx.cur = cb;
                self.cov_mark(line);
                let c = self.expr(cond).unwrap();
                let (bl, el) = (self.lbl(bb), self.lbl(end));
                self.term(Term::CondBr(c, bl, el), line);
                self.cx.cur = bb;
                self.scoped(body, line);
                self.term(Term::Br(cl), line);
                self.cx.cur = end;
            }
            StmtKind::Return(e) => {
                self.cov_mark(line);
                let v = e.as_ref().and_then(|e| self.expr(e));
                let d = self.live_drops();
                self.drop_calls(&d, line);
                self.term(Term::Ret(v), line);
                let dead = self.new_block("dead");
                self.cx.cur = dead;
            }
            StmtKind::Expr(e) => { self.cov_mark(line); self.expr(e); }
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
            ExprKind::Lambda(_) => unreachable!("lambdas only appear as expect_trap's argument"),
            ExprKind::Call { name, args } => {
                match name.as_str() {
                    "print" => { let a = self.expr(&args[0].value).unwrap(); self.plain("p3_print", vec![a], LTy::Void, line); None }
                    "trap" => { let a = self.expr(&args[0].value).unwrap(); self.call("p3_trap", vec![a], LTy::Void, line); None }
                    "expect_trap" => {
                        if let ExprKind::Lambda(l) = &args[0].value.kind { self.expect_trap(l, line); }
                        else { unreachable!() }
                        None
                    }
                    _ => {
                        let vals: Vec<Op> = args.iter().map(|a| self.expr(&a.value).unwrap()).collect();
                        if let Some(si) = self.info.structs.iter().find(|s| &s.name == name) {
                            let lt = LTy::Named(format!("%{}", si.name));
                            let mut agg = Op::Undef(lt.clone());
                            for (i, v) in vals.into_iter().enumerate() {
                                let d = self.reg();
                                self.emit(Inst::Insert { dst: d, ty: lt.clone(), agg, val: v, idx: i }, line);
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

    // expect_trap(action: fn() { .. }): invoke the lambda, catch the trap, print `trapped: <msg>`.
    fn expect_trap(&mut self, l: &'a Lambda, line: u32) {
        let name = format!("p3_lambda{}", self.nlambda);
        self.pending.push((name.clone(), format!("lambda{}", self.nlambda), l));
        self.nlambda += 1;
        self.cx.eh = true;
        let cont = self.new_block("trap.cont");
        let h = self.new_block(if self.win { "catch.dispatch" } else { "catch" });
        let ci = CallInfo { dst: None, ret: LTy::Void, callee: name, args: vec![], funclet: self.cx.funclet };
        let (cl, hl) = (self.lbl(cont), self.lbl(h));
        self.term(Term::Invoke(ci, cl.clone(), hl), line);
        self.cx.cur = h;
        let saved_f = self.cx.funclet;
        let prefix = Op::Global(self.string("trapped: "));
        if self.win {
            let body = self.new_block("catch.body");
            let (cs, bl) = (self.reg(), self.lbl(body));
            self.term(Term::CatchSwitch { dst: cs, handler: bl }, line);
            self.cx.cur = body;
            let cp = self.reg();
            self.emit(Inst::CatchPad { dst: cp, sw: cs }, line);
            self.cx.funclet = Some(cp);
            self.report(prefix, line);
            self.term(Term::CatchRet(cp, cl), line);
        } else {
            let lp = self.reg();
            self.emit(Inst::Landing { dst: lp, catch: true }, line);
            let ex = self.reg();
            self.emit(Inst::Extract { dst: ex, ty: LTy::Ptr, agg: Op::Reg(lp, LTy::Named(LP_TY.into())), idx: 0 }, line);
            self.plain("__cxa_begin_catch", vec![Op::Reg(ex, LTy::Ptr)], LTy::Ptr, line);
            self.report(prefix, line);
            self.plain("__cxa_end_catch", vec![], LTy::Void, line);
            self.term(Term::Br(cl), line);
        }
        self.cx.funclet = saved_f;
        self.cx.cur = cont;
    }
    fn report(&mut self, prefix: Op, line: u32) {
        let m = self.plain("p3_trap_message", vec![], LTy::Ptr, line).unwrap();
        let s = self.plain("p3_concat", vec![prefix, m], LTy::Ptr, line).unwrap();
        self.plain("p3_print", vec![s], LTy::Void, line);
    }
}
