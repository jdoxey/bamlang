// Checker: resolves names, checks labels and types, annotates every Expr with its type.
use crate::ast::*;
use std::collections::HashMap;

type R<T> = Result<T, String>;
type Sig = (Vec<(String, Ty)>, Ty);

struct Checker {
    types: HashMap<String, Vec<(String, Ty)>>,
    enums: HashMap<String, Vec<Variant>>,
    fns: HashMap<String, Sig>,
    scopes: Vec<HashMap<String, (Ty, bool)>>,
    ret: Ty,
}

pub fn check(prog: &mut Program) -> R<()> {
    let mut c = Checker { types: HashMap::new(), enums: HashMap::new(), fns: HashMap::new(), scopes: vec![], ret: Ty::Unit };
    for t in &prog.types {
        if c.types.insert(t.name.clone(), t.fields.clone()).is_some() { return Err(format!("{}: duplicate type {}", t.line, t.name)); }
    }
    for e in &prog.enums {
        if c.types.contains_key(&e.name) || c.enums.insert(e.name.clone(), e.variants.clone()).is_some() { return Err(format!("{}: duplicate type {}", e.line, e.name)); }
        for (i, v) in e.variants.iter().enumerate() {
            if e.variants[..i].iter().any(|w| w.name == v.name) { return Err(format!("{}: duplicate variant {}", e.line, v.name)); }
        }
    }
    for e in &prog.enums { for v in &e.variants { for (_, ft) in &v.fields { c.known(ft, e.line)?; } } }
    for f in &prog.fns {
        if c.fns.insert(f.name.clone(), (f.params.clone(), f.ret.clone())).is_some() { return Err(format!("{}: duplicate fn {}", f.line, f.name)); }
        if matches!(f.name.as_str(), "print" | "trap" | "expect_trap") { return Err(format!("{}: {} is built in", f.line, f.name)); }
    }
    for t in prog.types.iter_mut() {
        for (_, ft) in &t.fields { c.known(ft, t.line)?; }
        if let Some(body) = &mut t.drop {
            c.ret = Ty::Unit;
            c.scopes = vec![HashMap::new()];
            c.scopes[0].insert("self".into(), (Ty::Named(t.name.clone()), true));
            c.block(body)?;
        }
    }
    for f in prog.fns.iter_mut() {
        c.ret = f.ret.clone();
        c.known(&f.ret, f.line)?;
        c.scopes = vec![HashMap::new()];
        for (n, t) in &f.params { c.known(t, f.line)?; c.scopes[0].insert(n.clone(), (t.clone(), false)); }
        c.block(&mut f.body)?;
    }
    if !c.fns.contains_key("main") { return Err("0: no main function".into()); }
    Ok(())
}

impl Checker {
    fn known(&self, t: &Ty, line: u32) -> R<()> {
        if let Ty::Named(n) = t { if !self.types.contains_key(n) && !self.enums.contains_key(n) { return Err(format!("{}: unknown type {}", line, n)); } }
        Ok(())
    }
    fn lookup(&self, n: &str) -> Option<(Ty, bool)> { self.scopes.iter().rev().find_map(|s| s.get(n).cloned()) }

    fn block(&mut self, b: &mut Vec<Stmt>) -> R<()> {
        self.scopes.push(HashMap::new());
        for s in b.iter_mut() { self.stmt(s)?; }
        self.scopes.pop();
        Ok(())
    }

    fn stmt(&mut self, s: &mut Stmt) -> R<()> {
        let line = s.line;
        match &mut s.kind {
            StmtKind::Let { name, mutable, ann, init } => {
                let t = self.expr(init)?;
                if let Some(a) = ann { if *a != t { return Err(format!("{}: {} annotated {:?} but initialiser is {:?}", line, name, a, t)); } }
                if t == Ty::Unit { return Err(format!("{}: cannot bind a value of no type", line)); }
                if self.scopes.last().unwrap().contains_key(name.as_str()) { return Err(format!("{}: {} already declared in this scope", line, name)); }
                self.scopes.last_mut().unwrap().insert(name.clone(), (t, *mutable));
            }
            StmtKind::Assign { target, add, value } => {
                let tt = self.expr(target)?;
                let mut root: &Expr = target;
                while let ExprKind::Field(b, _) = &root.kind { root = b; }
                match &root.kind {
                    ExprKind::Var(n) => { if !self.lookup(n).map_or(false, |x| x.1) { return Err(format!("{}: cannot assign to immutable {}", line, n)); } }
                    _ => return Err(format!("{}: bad assignment target", line)),
                }
                let vt = self.expr(value)?;
                if tt != vt { return Err(format!("{}: assigning {:?} to {:?}", line, vt, tt)); }
                if *add && tt != Ty::Int { return Err(format!("{}: += needs Int", line)); }
            }
            StmtKind::If { cond, then, els } => {
                if self.expr(cond)? != Ty::Bool { return Err(format!("{}: if condition must be Bool", line)); }
                self.block(then)?;
                if let Some(e) = els { self.block(e)?; }
            }
            StmtKind::While { cond, body } => {
                if self.expr(cond)? != Ty::Bool { return Err(format!("{}: while condition must be Bool", line)); }
                if has_match(cond) { return Err(format!("{}: match is not allowed in a while condition (it is hoisted before the statement)", line)); }
                self.block(body)?;
            }
            StmtKind::Return(v) => {
                let t = match v { Some(e) => self.expr(e)?, None => Ty::Unit };
                if t != self.ret { return Err(format!("{}: return of {:?} in function returning {:?}", line, t, self.ret)); }
            }
            StmtKind::Crew { name, body } => {
                self.scopes.push(HashMap::from([(name.clone(), (Ty::Crew, false))]));
                let r = self.block(body);
                self.scopes.pop();
                r?;
            }
            StmtKind::Expr(e) => { self.expr(e)?; }
        }
        Ok(())
    }

    fn expr(&mut self, e: &mut Expr) -> R<Ty> {
        let line = e.line;
        let t = match &mut e.kind {
            ExprKind::Int(_) => Ty::Int,
            ExprKind::Str(parts) => {
                for p in parts.iter_mut() {
                    if let StrPart::Interp(x) = p {
                        let t = self.expr(x)?;
                        if t != Ty::Int && t != Ty::Str { return Err(format!("{}: can only interpolate Int or Str, not {:?}", line, t)); }
                    }
                }
                Ty::Str
            }
            ExprKind::Var(n) => self.lookup(n).ok_or(format!("{}: unknown name {}", line, n))?.0,
            ExprKind::Field(b, f) => {
                let bt = self.expr(b)?;
                match bt {
                    Ty::Named(tn) if self.types.contains_key(&tn) => self.types[&tn].iter().find(|x| &x.0 == f).map(|x| x.1.clone()).ok_or(format!("{}: {} has no field {}", line, tn, f))?,
                    _ => return Err(format!("{}: {:?} has no fields", line, bt)),
                }
            }
            ExprKind::Binary(op, l, r) => {
                let (lt, rt) = (self.expr(l)?, self.expr(r)?);
                if lt != Ty::Int || rt != Ty::Int { return Err(format!("{}: operator needs Int operands, got {:?} and {:?}", line, lt, rt)); }
                if matches!(op, BinOp::Add | BinOp::Sub | BinOp::Mul) { Ty::Int } else { Ty::Bool }
            }
            ExprKind::Lambda(_) => return Err(format!("{}: a lambda is only allowed as the action of expect_trap or crew go", line)),
            ExprKind::Go { crew, task } => {
                if self.lookup(crew).map(|x| x.0) != Some(Ty::Crew) { return Err(format!("{}: {} is not a crew", line, crew)); }
                self.lambda_body(task, line)?;
                Ty::Unit
            }
            ExprKind::EnumCtor { en, variant, args } => {
                let vs = self.enums.get(en.as_str()).ok_or(format!("{}: unknown enum {}", line, en))?;
                let v = vs.iter().find(|v| &v.name == variant).ok_or(format!("{}: {} has no variant {}", line, en, variant))?;
                let params = v.fields.clone();
                self.check_args(&format!("{}.{}", en, variant), args, &params, line)?;
                Ty::Named(en.clone())
            }
            ExprKind::Match { scrut, arms } => {
                let st = self.expr(scrut)?;
                let Ty::Named(en) = &st else { return Err(format!("{}: match needs an enum value, got {:?}", line, st)) };
                let vs = self.enums.get(en.as_str()).ok_or(format!("{}: match needs an enum value, got {}", line, en))?.clone();
                let mut result: Option<Ty> = None;
                let mut seen: Vec<String> = vec![];
                for a in arms.iter_mut() {
                    let v = vs.iter().find(|v| v.name == a.variant).ok_or(format!("{}: {} has no variant {}", a.line, en, a.variant))?;
                    if seen.contains(&a.variant) { return Err(format!("{}: variant {} matched twice", a.line, a.variant)); }
                    seen.push(a.variant.clone());
                    if a.binders.len() != v.fields.len() { return Err(format!("{}: {}.{} has {} field(s), pattern binds {}", a.line, en, v.name, v.fields.len(), a.binders.len())); }
                    let sc: HashMap<String, (Ty, bool)> = a.binders.iter().zip(&v.fields).map(|(b, (_, t))| (b.clone(), (t.clone(), false))).collect();
                    self.scopes.push(sc);
                    let t = self.expr(&mut a.body);
                    self.scopes.pop();
                    let t = t?;
                    match &result { None => result = Some(t), Some(r) if *r == t => {}, Some(r) => return Err(format!("{}: match arms differ: {:?} and {:?}", a.line, r, t)) }
                }
                if let Some(missing) = vs.iter().find(|v| !seen.contains(&v.name)) { return Err(format!("{}: match is not exhaustive, missing {}", line, missing.name)); }
                result.ok_or(format!("{}: empty match", line))?
            }
            ExprKind::Call { callee, args } => return self.call(callee.clone(), args, line, &mut e.ty),
        };
        e.ty = t.clone();
        Ok(t)
    }

    fn call(&mut self, callee: String, args: &mut Vec<Arg>, line: u32, slot: &mut Ty) -> R<Ty> {
        let params: Vec<(String, Ty)>;
        let ret;
        match callee.as_str() {
            "print" | "trap" => { params = vec![("text".into(), Ty::Str)]; ret = Ty::Unit; }
            "expect_trap" => {
                if args.len() != 1 || args[0].label.as_deref() != Some("action") { return Err(format!("{}: expect_trap(action: fn() {{...}})", line)); }
                self.lambda_body(&mut args[0].value, line)?;
                *slot = Ty::Unit;
                return Ok(Ty::Unit);
            }
            n => {
                if let Some((p, r)) = self.fns.get(n) { params = p.clone(); ret = r.clone(); }
                else if let Some(f) = self.types.get(n) { params = f.clone(); ret = Ty::Named(n.to_string()); }
                else { return Err(format!("{}: unknown function or type {}", line, n)); }
            }
        }
        self.check_args(&callee, args, &params, line)?;
        *slot = ret.clone();
        Ok(ret)
    }

    fn lambda_body(&mut self, lam: &mut Expr, line: u32) -> R<()> {
        let body = match &mut lam.kind { ExprKind::Lambda(b) => b, _ => return Err(format!("{}: the task must be a lambda", line)) };
        let saved = std::mem::replace(&mut self.scopes, vec![HashMap::new()]); // capture-free: new scope stack
        let saved_ret = std::mem::replace(&mut self.ret, Ty::Unit);
        let r = self.block(body);
        self.scopes = saved;
        self.ret = saved_ret;
        r
    }

    fn check_args(&mut self, callee: &str, args: &mut Vec<Arg>, params: &[(String, Ty)], line: u32) -> R<()> {
        if args.len() != params.len() { return Err(format!("{}: {} takes {} argument(s), got {}", line, callee, params.len(), args.len())); }
        for (a, (pn, pt)) in args.iter_mut().zip(params.iter()) {
            if a.label.as_deref() != Some(pn.as_str()) { return Err(format!("{}: {} expects argument labelled '{}'", line, callee, pn)); }
            let t = self.expr(&mut a.value)?;
            if &t != pt { return Err(format!("{}: argument {} of {} is {:?}, expected {:?}", line, pn, callee, t, pt)); }
        }
        Ok(())
    }
}

fn has_match(e: &Expr) -> bool {
    match &e.kind {
        ExprKind::Match { .. } => true,
        ExprKind::Binary(_, l, r) => has_match(l) || has_match(r),
        ExprKind::Field(b, _) => has_match(b),
        ExprKind::Call { args, .. } | ExprKind::EnumCtor { args, .. } => args.iter().any(|a| has_match(&a.value)),
        ExprKind::Str(ps) => ps.iter().any(|p| matches!(p, StrPart::Interp(x) if has_match(x))),
        _ => false,
    }
}
