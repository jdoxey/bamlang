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
    FnRef(String),
    Fmt(String, Vec<CExpr>),
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
    PopRun(String),
}

pub struct CFn { pub name: String, pub params: Vec<(String, String)>, pub ret: String, pub body: Vec<CStmt>, pub line: u32, pub public: bool }
pub struct CType { pub name: String, pub fields: Vec<(String, String)>, pub has_drop: bool }
pub struct CProgram { pub types: Vec<CType>, pub fns: Vec<CFn> }

struct L<'a> {
    prog: &'a Program,
    scopes: Vec<Vec<(String, String)>>, // per block: (cleanup var, ...) of droppable locals
    lambdas: Vec<CFn>,
    in_drop: bool,
}

const C_KW: [&str; 13] = ["int", "char", "long", "short", "auto", "register", "static", "double", "float", "void", "struct", "union", "default"];
fn cname(n: &str) -> String { if C_KW.contains(&n) { format!("{}_", n) } else { n.to_string() } }
fn cty(t: &Ty) -> String {
    match t { Ty::Int => "int64_t".into(), Ty::Bool => "int".into(), Ty::Str => "p3_Str".into(), Ty::Unit => "void".into(), Ty::Named(n) => n.clone() }
}

pub fn lower(prog: &Program) -> CProgram {
    let mut l = L { prog, scopes: vec![], lambdas: vec![], in_drop: false };
    let mut out = CProgram { types: vec![], fns: vec![] };
    for t in &prog.types {
        out.types.push(CType { name: t.name.clone(), fields: t.fields.iter().map(|(n, ty)| (cname(n), cty(ty))).collect(), has_drop: t.drop.is_some() });
        if let Some(body) = &t.drop {
            l.in_drop = true;
            let b = l.func_body(body);
            l.in_drop = false;
            out.fns.push(CFn { name: format!("{}__drop", t.name), params: vec![(format!("{} *", t.name), "self".into())], ret: "void".into(), body: b, line: t.line, public: false });
        }
    }
    for f in &prog.fns {
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
            for (c, _) in scope.iter().rev() { out.push(CStmt { line, kind: CKind::PopRun(c.clone()) }); }
        }
        out
    }

    fn droppable(&self, t: &Ty) -> bool {
        matches!(t, Ty::Named(n) if self.prog.types.iter().any(|x| &x.name == n && x.drop.is_some()))
    }

    fn stmt(&mut self, s: &Stmt, out: &mut Vec<CStmt>) {
        let line = s.line;
        let mut push = |kind| out.push(CStmt { line, kind });
        match &s.kind {
            StmtKind::Let { name, init, .. } => {
                let n = cname(name);
                let e = self.expr(init);
                push(CKind::Decl(cty(&init.ty), n.clone(), Some(e)));
                if self.droppable(&init.ty) {
                    let c = format!("{}__cleanup", n);
                    let Ty::Named(tn) = &init.ty else { unreachable!() };
                    push(CKind::Push(c.clone(), tn.clone(), n.clone()));
                    self.scopes.last_mut().unwrap().push((c, n));
                }
            }
            StmtKind::Assign { target, add, value } => {
                let (t, v) = (self.expr(target), self.expr(value));
                push(CKind::Assign(t, if *add { "+=" } else { "=" }, v));
            }
            StmtKind::If { cond, then, els } => {
                let c = self.expr(cond);
                let t = self.block(then);
                let e = els.as_ref().map(|b| self.block(b));
                push(CKind::If(c, t, e));
            }
            StmtKind::While { cond, body } => {
                let c = self.expr(cond);
                let b = self.block(body);
                push(CKind::While(c, b));
            }
            StmtKind::Return(v) => {
                let e = v.as_ref().map(|e| self.expr(e));
                let pops: Vec<String> = self.scopes.iter().rev().flat_map(|s| s.iter().rev().map(|(c, _)| c.clone())).collect();
                if pops.is_empty() { push(CKind::Return(e)); return; }
                // evaluate the value first, then run drops of every live local (innermost first), then return
                match (&v, e) {
                    (Some(ex), Some(e)) => {
                        push(CKind::Decl(cty(&ex.ty), "p3_ret".into(), Some(e)));
                        for p in pops { push(CKind::PopRun(p)); }
                        push(CKind::Return(Some(CExpr::Var("p3_ret".into()))));
                    }
                    _ => { for p in pops { push(CKind::PopRun(p)); } push(CKind::Return(None)); }
                }
            }
            StmtKind::Expr(e) => {
                let c = self.expr(e);
                push(CKind::Expr(c, e.ty != Ty::Unit));
            }
        }
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
            ExprKind::Lambda(_) => unreachable!("lambda outside expect_trap rejected by checker"),
            ExprKind::Call { callee, args } => match callee.as_str() {
                "print" => CExpr::Call("p3_print".into(), vec![self.expr(&args[0].value)]),
                "trap" => CExpr::Call("p3_trap".into(), vec![self.expr(&args[0].value)]),
                "expect_trap" => {
                    let ExprKind::Lambda(body) = &args[0].value.kind else { unreachable!() };
                    let name = format!("p3_lambda_{}", self.lambdas.len());
                    self.lambdas.push(CFn { name: name.clone(), params: vec![], ret: "void".into(), body: vec![], line: e.line, public: false }); // reserve index
                    let idx = self.lambdas.len() - 1;
                    let saved = std::mem::replace(&mut self.in_drop, false);
                    let b = self.func_body(body);
                    self.in_drop = saved;
                    self.lambdas[idx].body = b;
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
