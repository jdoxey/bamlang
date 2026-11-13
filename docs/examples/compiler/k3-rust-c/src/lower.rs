// Lowering: typed AST to a small C-shaped IR. Decides where cleanup-stack pushes/pops go,
// lifts lambdas to top-level C functions, turns interpolation into p3_fmt calls.
use crate::ast::*;

pub enum CExpr {
    Int(i64),
    Str(String),
    Var(String),
    Field(Box<CExpr>, String, bool), // base, field, base_is_pointer
    Call(String, Vec<CExpr>),
    Bin(&'static str, Box<CExpr>, Box<CExpr>),
    Ctor(String, Vec<(String, CExpr)>),
    EnumCtor(String, String, Vec<(String, CExpr)>), // enum, variant, fields
    FnRef(String),
    Fmt(String, Vec<CExpr>),
    Raw(String),
}

pub struct CStmt { pub line: u32, pub kind: CKind }
pub enum CKind {
    Decl(String, String, Option<CExpr>),
    Assign(CExpr, &'static str, CExpr),
    If(CExpr, Vec<CStmt>, Option<Vec<CStmt>>),
    While(CExpr, Vec<CStmt>),
    Return(Option<CExpr>),
    Expr(CExpr, bool), // bool: discard value with (void)
    Push(String, String, String), // cleanup var, drop type, object var
    /// cleanup node expression, drop type ("" for a crew), object variable
    PopRun(String, String, String),
    /// Bare C block (scope of a crew).
    Block(Vec<CStmt>),
    /// `p3_crew name; p3_crew_begin(&name, ...)`: name, source line, enclosing function
    CrewBegin(String, u32, String),
    /// `switch (scrut.tag)` over an enum: scrutinee variable, enum name, (variant, body) arms
    Switch(String, String, Vec<(String, Vec<CStmt>)>),
}

pub struct CFn { pub name: String, pub params: Vec<(String, String)>, pub ret: String, pub body: Vec<CStmt>, pub line: u32, pub public: bool }
pub struct CType { pub name: String, pub fields: Vec<(String, String)>, pub has_drop: bool, pub line: u32 }
pub struct CEnum { pub name: String, pub variants: Vec<(String, Vec<(String, String)>)>, pub line: u32 }
pub struct CProgram { pub types: Vec<CType>, pub enums: Vec<CEnum>, pub fns: Vec<CFn> }

struct L<'a> {
    prog: &'a Program,
    scopes: Vec<Vec<(String, String, String)>>, // per block: (cleanup node, drop type, object) of droppable locals
    lambdas: Vec<CFn>,
    in_drop: bool,
    src: String,
    cur_fn: String,
    matches: u32,
    pending: Vec<CStmt>, // statements hoisted out of the expression being lowered (match)
}

const C_KW: [&str; 13] = ["int", "char", "long", "short", "auto", "register", "static", "double", "float", "void", "struct", "union", "default"];
fn cname(n: &str) -> String { if C_KW.contains(&n) { format!("{}_", n) } else { n.to_string() } }
fn cty(t: &Ty) -> String {
    match t { Ty::Int => "int64_t".into(), Ty::Bool => "int".into(), Ty::Str => "p3_Str".into(), Ty::Unit => "void".into(), Ty::Crew => "p3_crew".into(), Ty::Named(n) => n.clone() }
}

pub fn lower(prog: &Program, src: &str) -> CProgram {
    let mut l = L { prog, scopes: vec![], lambdas: vec![], in_drop: false, src: src.to_string(), cur_fn: String::new(), matches: 0, pending: vec![] };
    let mut out = CProgram { types: vec![], enums: vec![], fns: vec![] };
    for e in &prog.enums {
        out.enums.push(CEnum { name: e.name.clone(), line: e.line, variants: e.variants.iter().map(|v| (v.name.clone(), v.fields.iter().map(|(n, t)| (cname(n), cty(t))).collect())).collect() });
    }
    for t in &prog.types {
        out.types.push(CType { name: t.name.clone(), fields: t.fields.iter().map(|(n, ty)| (cname(n), cty(ty))).collect(), has_drop: t.drop.is_some(), line: t.line });
        if let Some(body) = &t.drop {
            l.in_drop = true;
            l.cur_fn = format!("{}.drop", t.name);
            let b = l.func_body(body);
            l.in_drop = false;
            out.fns.push(CFn { name: format!("{}__drop", t.name), params: vec![(format!("{} *", t.name), "self".into())], ret: "void".into(), body: b, line: t.line, public: false });
        }
    }
    for f in &prog.fns {
        l.cur_fn = f.name.clone();
        let body = l.func_body(&f.body);
        out.fns.push(CFn { name: format!("p3_{}", f.name), params: f.params.iter().map(|(n, t)| (cty(t), cname(n))).collect(), ret: cty(&f.ret), body, line: f.line, public: true });
    }
    let mut lam = std::mem::take(&mut l.lambdas);
    lam.extend(out.fns);
    out.fns = lam;
    out
}

impl<'a> L<'a> {
    fn func_body(&mut self, b: &[Stmt]) -> Vec<CStmt> {
        let saved = std::mem::take(&mut self.scopes);
        let r = self.block(b);
        self.scopes = saved;
        r
    }

    fn block(&mut self, b: &[Stmt]) -> Vec<CStmt> {
        self.scopes.push(vec![]);
        let mut out = Vec::new();
        for s in b { self.stmt(s, &mut out); }
        let scope = self.scopes.pop().unwrap();
        if !matches!(b.last().map(|s| &s.kind), Some(StmtKind::Return(_))) {
            let line = b.last().map_or(0, |s| s.line);
            for (c, t, o) in scope.iter().rev() { out.push(CStmt { line, kind: CKind::PopRun(c.clone(), t.clone(), o.clone()) }); }
        }
        out
    }

    fn droppable(&self, t: &Ty) -> bool {
        matches!(t, Ty::Named(n) if self.prog.types.iter().any(|x| &x.name == n && x.drop.is_some()))
    }

    fn flush(&mut self, out: &mut Vec<CStmt>) { out.append(&mut self.pending); }

    fn stmt(&mut self, s: &Stmt, out: &mut Vec<CStmt>) {
        let line = s.line;
        match &s.kind {
            StmtKind::Let { name, init, .. } => {
                let n = cname(name);
                let e = self.expr(init);
                self.flush(out);
                out.push(CStmt { line, kind: CKind::Decl(cty(&init.ty), n.clone(), Some(e)) });
                if self.droppable(&init.ty) {
                    let c = format!("{}__cleanup", n);
                    let Ty::Named(tn) = &init.ty else { unreachable!() };
                    out.push(CStmt { line, kind: CKind::Push(c.clone(), tn.clone(), n.clone()) });
                    self.scopes.last_mut().unwrap().push((c, tn.clone(), n));
                }
            }
            StmtKind::Assign { target, add, value } => {
                let (t, v) = (self.expr(target), self.expr(value));
                self.flush(out);
                out.push(CStmt { line, kind: CKind::Assign(t, if *add { "+=" } else { "=" }, v) });
            }
            StmtKind::If { cond, then, els } => {
                let c = self.expr(cond);
                self.flush(out);
                let t = self.block(then);
                let e = els.as_ref().map(|b| self.block(b));
                out.push(CStmt { line, kind: CKind::If(c, t, e) });
            }
            StmtKind::While { cond, body } => {
                let c = self.expr(cond);
                let b = self.block(body);
                out.push(CStmt { line, kind: CKind::While(c, b) });
            }
            StmtKind::Crew { name, body } => {
                let n = cname(name);
                let mut inner = vec![CStmt { line, kind: CKind::CrewBegin(n.clone(), line, self.cur_fn.clone()) }];
                self.scopes.push(vec![(format!("{}.node", n), String::new(), n.clone())]);
                inner.extend(self.block(body));
                self.scopes.pop();
                if !matches!(body.last().map(|s| &s.kind), Some(StmtKind::Return(_))) {
                    let end = body.last().map_or(line, |s| s.line);
                    inner.push(CStmt { line: end, kind: CKind::PopRun(format!("{}.node", n), String::new(), n) });
                }
                out.push(CStmt { line, kind: CKind::Block(inner) });
            }
            StmtKind::Return(v) => {
                let e = v.as_ref().map(|e| self.expr(e));
                self.flush(out);
                let pops: Vec<(String, String, String)> = self.scopes.iter().rev().flat_map(|s| s.iter().rev().cloned()).collect();
                let pop = |out: &mut Vec<CStmt>| for (c, t, o) in &pops { out.push(CStmt { line, kind: CKind::PopRun(c.clone(), t.clone(), o.clone()) }); };
                if pops.is_empty() { out.push(CStmt { line, kind: CKind::Return(e) }); return; }
                // evaluate the value first, then run drops of every live local (innermost first), then return
                match (&v, e) {
                    (Some(ex), Some(e)) => {
                        out.push(CStmt { line, kind: CKind::Decl(cty(&ex.ty), "p3_ret".into(), Some(e)) });
                        pop(out);
                        out.push(CStmt { line, kind: CKind::Return(Some(CExpr::Var("p3_ret".into()))) });
                    }
                    _ => { pop(out); out.push(CStmt { line, kind: CKind::Return(None) }); }
                }
            }
            StmtKind::Expr(e) => {
                let c = self.expr(e);
                self.flush(out);
                out.push(CStmt { line, kind: CKind::Expr(c, e.ty != Ty::Unit) });
            }
        }
    }

    /// Lift a capture-free lambda body to a static C function and return its name.
    fn lift(&mut self, body: &[Stmt], line: u32) -> String {
        let name = format!("p3_lambda_{}", self.lambdas.len());
        self.lambdas.push(CFn { name: name.clone(), params: vec![], ret: "void".into(), body: vec![], line, public: false }); // reserve index
        let idx = self.lambdas.len() - 1;
        let saved = std::mem::replace(&mut self.in_drop, false);
        let saved_fn = self.cur_fn.clone();
        self.cur_fn = format!("{}.lambda", saved_fn);
        let saved_pending = std::mem::take(&mut self.pending);
        let b = self.func_body(body);
        self.pending = saved_pending;
        self.cur_fn = saved_fn;
        self.in_drop = saved;
        self.lambdas[idx].body = b;
        name
    }

    fn expr(&mut self, e: &Expr) -> CExpr {
        match &e.kind {
            ExprKind::Int(n) => CExpr::Int(*n),
            ExprKind::Str(parts) => {
                if let [StrPart::Lit(s)] = parts.as_slice() { return CExpr::Str(s.clone()); }
                let mut fmt = String::new();
                let mut args = Vec::new();
                for p in parts {
                    match p {
                        StrPart::Lit(s) => fmt.push_str(s),
                        StrPart::Interp(x) => {
                            fmt.push_str(if x.ty == Ty::Int { "\u{1}lld" } else { "\u{1}s" }); // \u{1} marks a conversion
                            let c = self.expr(x);
                            args.push(if x.ty == Ty::Int { CExpr::Call("(long long)".into(), vec![c]) } else { c });
                        }
                    }
                }
                CExpr::Fmt(fmt, args)
            }
            ExprKind::Var(n) => CExpr::Var(cname(n)),
            ExprKind::Field(b, f) => {
                let ptr = self.in_drop && matches!(&b.kind, ExprKind::Var(n) if n == "self");
                CExpr::Field(Box::new(self.expr(b)), cname(f), ptr)
            }
            ExprKind::Binary(op, l, r) => {
                let o = match op { BinOp::Add => "+", BinOp::Sub => "-", BinOp::Mul => "*", BinOp::Lt => "<", BinOp::Gt => ">", BinOp::Eq => "==" };
                CExpr::Bin(o, Box::new(self.expr(l)), Box::new(self.expr(r)))
            }
            ExprKind::Lambda(_) => unreachable!("lambda outside expect_trap/go rejected by checker"),
            ExprKind::Go { crew, task } => {
                let ExprKind::Lambda(body) = &task.kind else { unreachable!() };
                let name = self.lift(body, e.line);
                CExpr::Call("p3_crew_go".into(), vec![CExpr::Var(format!("&{}", cname(crew))), CExpr::FnRef(name)])
            }
            ExprKind::EnumCtor { en, variant, args } => {
                let vs = &self.prog.enums.iter().find(|x| &x.name == en).unwrap().variants;
                let v = vs.iter().find(|v| &v.name == variant).unwrap();
                let fields = v.fields.iter().zip(args).map(|((f, _), a)| (cname(f), self.expr(&a.value))).collect();
                CExpr::EnumCtor(en.clone(), variant.clone(), fields)
            }
            ExprKind::Match { scrut, arms } => {
                let id = self.matches;
                self.matches += 1;
                let (res, sv) = (format!("match_{}", id), format!("match_{}_s", id));
                let sc = self.expr(scrut);
                let Ty::Named(en) = &scrut.ty else { unreachable!() };
                let decl = self.prog.enums.iter().find(|x| &x.name == en).unwrap();
                let mut carms = Vec::new();
                for a in arms {
                    let v = decl.variants.iter().find(|v| v.name == a.variant).unwrap();
                    let saved = std::mem::take(&mut self.pending);
                    let mut body = Vec::new();
                    for (b, (f, t)) in a.binders.iter().zip(&v.fields) {
                        let access = CExpr::Field(Box::new(CExpr::Field(Box::new(CExpr::Field(Box::new(CExpr::Var(sv.clone())), "u".into(), false)), a.variant.clone(), false)), cname(f), false);
                        body.push(CStmt { line: a.line, kind: CKind::Decl(cty(t), cname(b), Some(access)) });
                    }
                    let val = self.expr(&a.body);
                    body.append(&mut self.pending);
                    body.push(CStmt { line: a.line, kind: CKind::Assign(CExpr::Var(res.clone()), "=", val) });
                    self.pending = saved;
                    carms.push((a.variant.clone(), body));
                }
                self.pending.push(CStmt { line: e.line, kind: CKind::Decl(cty(&e.ty), res.clone(), Some(CExpr::Raw("{0}".into()))) });
                self.pending.push(CStmt { line: e.line, kind: CKind::Decl(en.clone(), sv.clone(), Some(sc)) });
                self.pending.push(CStmt { line: e.line, kind: CKind::Switch(sv, en.clone(), carms) });
                CExpr::Var(res)
            }
            ExprKind::Call { callee, args } => match callee.as_str() {
                "print" => CExpr::Call("p3_print".into(), vec![self.expr(&args[0].value)]),
                "trap" => {
                    let msg = self.expr(&args[0].value);
                    CExpr::Call("p3_trap".into(), vec![msg, CExpr::Str(self.src.clone()), CExpr::Int(e.line as i64), CExpr::Str(self.cur_fn.clone())])
                }
                "expect_trap" => {
                    let ExprKind::Lambda(body) = &args[0].value.kind else { unreachable!() };
                    let name = self.lift(body, e.line);
                    CExpr::Call("p3_expect_trap".into(), vec![CExpr::FnRef(name)])
                }
                n if self.prog.types.iter().any(|t| t.name == n) => {
                    let t = self.prog.types.iter().find(|t| t.name == n).unwrap();
                    CExpr::Ctor(n.to_string(), t.fields.iter().zip(args).map(|((f, _), a)| (cname(f), self.expr(&a.value))).collect())
                }
                n => CExpr::Call(format!("p3_{}", n), args.iter().map(|a| self.expr(&a.value)).collect()),
            },
        }
    }
}
