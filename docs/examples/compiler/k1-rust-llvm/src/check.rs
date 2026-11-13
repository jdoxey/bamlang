// Checker for the subset: names, types Int/Str/structs, labelled arguments, no shadowing,
// capture-free lambdas, drop-bearing values cannot be copied or moved (spike limit).
use crate::ast::*;
use std::collections::HashMap;

#[derive(Clone)]
pub struct StructInfo { pub name: String, pub fields: Vec<(String, Type)>, pub has_drop: bool, pub line: u32 }
#[derive(Clone)]
pub struct EnumInfo { pub name: String, pub variants: Vec<(String, Vec<(String, Type)>)>, pub line: u32 }
impl EnumInfo { pub fn width(&self) -> usize { self.variants.iter().map(|v| v.1.len()).max().unwrap_or(0).max(1) } }
pub struct Info { pub structs: Vec<StructInfo>, pub enums: Vec<EnumInfo>, pub fns: HashMap<String, (Vec<(String, Type)>, Type)> }

struct Var { ty: Type, mutable: bool }
struct Cx<'a> { info: &'a Info, scopes: Vec<HashMap<String, Var>>, ret: Type, lam: bool, in_crew: u32 }

pub fn check(p: &mut Program) -> R<Info> {
    let mut info = Info { structs: vec![], enums: vec![], fns: HashMap::new() };
    info.fns.insert("print".into(), (vec![("text".into(), Type::Str)], Type::Unit));
    info.fns.insert("trap".into(), (vec![("text".into(), Type::Str)], Type::Unit));
    info.fns.insert("expect_trap".into(), (vec![("action".into(), Type::Action)], Type::Unit));
    for e in &p.enums {
        if matches!(e.name.as_str(), "Int" | "Str") || info.enums.iter().any(|s| s.name == e.name) || p.types.iter().any(|t| t.name == e.name) || info.fns.contains_key(&e.name) {
            return Err((e.line, format!("duplicate or reserved type name `{}`", e.name)));
        }
        if e.variants.is_empty() { return Err((e.line, format!("enum `{}` needs at least one variant", e.name))); }
        for (i, (vn, fields)) in e.variants.iter().enumerate() {
            if e.variants[..i].iter().any(|v| &v.0 == vn) { return Err((e.line, format!("duplicate variant `{}`", vn))); }
            for (fname, ft) in fields {
                if !matches!(ft, Type::Int | Type::Str) { return Err((e.line, format!("variant field `{}.{}` must be Int or Str in this subset", vn, fname))); }
            }
        }
        info.enums.push(EnumInfo { name: e.name.clone(), variants: e.variants.clone(), line: e.line });
    }
    for t in &p.types {
        if matches!(t.name.as_str(), "Int" | "Str") || info.structs.iter().any(|s| s.name == t.name) || info.enums.iter().any(|s| s.name == t.name) || info.fns.contains_key(&t.name) {
            return Err((t.line, format!("duplicate or reserved type name `{}`", t.name)));
        }
        info.structs.push(StructInfo { name: t.name.clone(), fields: t.fields.clone(), has_drop: t.drop.is_some(), line: t.line });
    }
    for f in &p.fns {
        if info.fns.contains_key(&f.name) || info.structs.iter().any(|s| s.name == f.name) || info.enums.iter().any(|s| s.name == f.name) {
            return Err((f.line, format!("duplicate or reserved function name `{}`", f.name)));
        }
        info.fns.insert(f.name.clone(), (f.params.clone(), f.ret.clone()));
    }
    for t in &p.types { for (_, ft) in &t.fields { known(&info, ft, t.line)?; } }
    for e in &p.enums { for (_, fs) in &e.variants { for (_, ft) in fs { known(&info, ft, e.line)?; } } }
    for f in &p.fns {
        for (_, pt) in &f.params { known(&info, pt, f.line)?; }
        known(&info, &f.ret, f.line)?;
    }
    match info.fns.get("main") {
        Some((ps, Type::Unit)) if ps.is_empty() => {}
        _ => return Err((1, "program needs `fn main()` with no parameters and no result".into())),
    }
    for t in &mut p.types {
        if let Some(d) = &mut t.drop {
            let mut cx = Cx { info: &info, scopes: vec![HashMap::new()], ret: Type::Unit, lam: false, in_crew: 0 };
            cx.scopes[0].insert("self".into(), Var { ty: Type::Struct(t.name.clone()), mutable: true });
            cx.stmts(&mut d.body)?;
        }
    }
    for f in &mut p.fns {
        let mut cx = Cx { info: &info, scopes: vec![HashMap::new()], ret: f.ret.clone(), lam: false, in_crew: 0 };
        for (n, t) in &f.params {
            if cx.scopes[0].insert(n.clone(), Var { ty: t.clone(), mutable: false }).is_some() {
                return Err((f.line, format!("duplicate parameter `{}`", n)));
            }
        }
        cx.stmts(&mut f.body)?;
        if f.ret != Type::Unit && !matches!(f.body.last().map(|s| &s.kind), Some(StmtKind::Return(Some(_)))) {
            return Err((f.end_line, format!("function `{}` must end with `return`", f.name)));
        }
    }
    Ok(info)
}

fn known(info: &Info, t: &Type, line: u32) -> R<()> {
    if let Type::Struct(n) = t { if !info.structs.iter().any(|s| &s.name == n) && !info.enums.iter().any(|s| &s.name == n) { return Err((line, format!("unknown type `{}`", n))); } }
    Ok(())
}

fn tname(t: &Type) -> String {
    match t { Type::Int => "Int".into(), Type::Str => "Str".into(), Type::Bool => "Bool".into(), Type::Unit => "()".into(),
        Type::Struct(n) => n.clone(), Type::Action => "fn()".into(), Type::Crew => "crew".into() }
}

impl<'a> Cx<'a> {
    fn find(&self, n: &str) -> Option<&Var> { self.scopes.iter().rev().find_map(|s| s.get(n)) }
    fn has_drop(&self, t: &Type) -> bool {
        matches!(t, Type::Struct(n) if self.info.structs.iter().any(|s| &s.name == n && s.has_drop))
    }
    fn stmts(&mut self, v: &mut Vec<Stmt>) -> R<()> {
        self.scopes.push(HashMap::new());
        for s in v.iter_mut() { self.stmt(s)?; }
        self.scopes.pop();
        Ok(())
    }
    fn stmt(&mut self, s: &mut Stmt) -> R<()> {
        let line = s.line;
        match &mut s.kind {
            StmtKind::Let { name, mutable, ann, init } => {
                let t = self.expr(init, false)?;
                if matches!(t, Type::Unit | Type::Action | Type::Crew) { return Err((line, format!("cannot bind a value of type {}", tname(&t)))); }
                if let Some(a) = ann {
                    known(self.info, a, line)?;
                    if *a != t { return Err((line, format!("expected {}, found {}", tname(a), tname(&t)))); }
                }
                if self.find(name).is_some() { return Err((line, format!("`{}` is already defined (no shadowing)", name))); }
                self.scopes.last_mut().unwrap().insert(name.clone(), Var { ty: t, mutable: *mutable });
            }
            StmtKind::Assign { name, op, value } => {
                let t = self.expr(value, false)?;
                let v = self.find(name).ok_or((line, format!("unknown name `{}`", name)))?;
                if !v.mutable { return Err((line, format!("`{}` is not a `var`", name))); }
                if v.ty != t { return Err((line, format!("expected {}, found {}", tname(&v.ty), tname(&t)))); }
                if op.is_some() && t != Type::Int { return Err((line, "`+=`/`-=` need Int".into())); }
            }
            StmtKind::If { cond, then, els, .. } => {
                self.want(cond, Type::Bool)?;
                self.stmts(then)?;
                if let Some((e, _)) = els { self.stmts(e)?; }
            }
            StmtKind::While { cond, body, .. } => { self.want(cond, Type::Bool)?; self.stmts(body)?; }
            StmtKind::Crew { name, body, .. } => {
                if self.find(name).is_some() { return Err((line, format!("`{}` is already defined (no shadowing)", name))); }
                self.scopes.push(HashMap::new());
                self.scopes.last_mut().unwrap().insert(name.clone(), Var { ty: Type::Crew, mutable: false });
                self.in_crew += 1;
                for s in body.iter_mut() { self.stmt(s)?; }
                self.in_crew -= 1;
                self.scopes.pop();
            }
            StmtKind::Return(e) => {
                if self.in_crew > 0 { return Err((line, "`return` inside a crew block is not supported in this subset".into())); }
                let t = match e { Some(e) => self.expr(e, false)?, None => Type::Unit };
                if t != self.ret { return Err((line, format!("return type is {}, found {}", tname(&self.ret), tname(&t)))); }
            }
            StmtKind::Expr(e) => {
                if !matches!(e.kind, ExprKind::Call { .. } | ExprKind::Method { .. }) { return Err((line, "this value is unused".into())); }
                self.expr(e, false)?;
                if !matches!(e.kind, ExprKind::Call { .. } | ExprKind::Go { .. }) { return Err((line, "this value is unused".into())); }
            }
        }
        Ok(())
    }
    fn want(&mut self, e: &mut Expr, t: Type) -> R<()> {
        let got = self.expr(e, false)?;
        if got != t { return Err((e.line, format!("expected {}, found {}", tname(&t), tname(&got)))); }
        Ok(())
    }
    // `base` = the expression is only the base of a field access, so it is not copied or moved.
    fn expr(&mut self, e: &mut Expr, base: bool) -> R<Type> {
        let line = e.line;
        if let ExprKind::Method { .. } = e.kind {
            self.method(e)?;
            let t = match &e.kind { ExprKind::Variant { en, .. } => Type::Struct(en.clone()), _ => Type::Unit };
            e.ty = t.clone();
            return Ok(t);
        }
        let t = match &mut e.kind {
            ExprKind::Int(_) => Type::Int,
            ExprKind::Interp(parts) => {
                for p in parts.iter_mut() {
                    if let IPart::Expr(x) = p {
                        let t = self.expr(x, false)?;
                        if t != Type::Int && t != Type::Str { return Err((line, format!("cannot interpolate {}", tname(&t)))); }
                    }
                }
                Type::Str
            }
            ExprKind::Name(n) => {
                let v = self.find(n).ok_or((line, format!("unknown name `{}`{}", n,
                    if self.lam { " (lambdas cannot capture)" } else { "" })))?;
                let t = v.ty.clone();
                if t == Type::Crew { return Err((line, format!("`{}` is a crew handle: use `{}.go(task: fn() {{ .. }})`", n, n))); }
                if !base && self.has_drop(&t) { return Err((line, format!("`{}` has a drop and cannot be copied or moved in this subset", n))); }
                t
            }
            ExprKind::Field(b, f) => {
                let bt = self.expr(b, true)?;
                match &bt {
                    Type::Struct(sn) => {
                        let si = self.info.structs.iter().find(|s| &s.name == sn).ok_or((line, format!("enum {} has no fields; use `match`", sn)))?;
                        si.fields.iter().find(|(n, _)| n == f).map(|(_, t)| t.clone()).ok_or((line, format!("{} has no field `{}`", sn, f)))?
                    }
                    _ => return Err((line, format!("{} has no fields", tname(&bt)))),
                }
            }
            ExprKind::Bin(op, l, r) => {
                let (lt, rt) = (self.expr(l, false)?, self.expr(r, false)?);
                if lt != Type::Int || rt != Type::Int { return Err((line, format!("operator needs Int operands, found {} and {}", tname(&lt), tname(&rt)))); }
                if matches!(op, BinOp::Lt | BinOp::Gt | BinOp::Eq) { Type::Bool } else { Type::Int }
            }
            ExprKind::Lambda(l) => {
                let mut cx = Cx { info: self.info, scopes: vec![HashMap::new()], ret: Type::Unit, lam: true, in_crew: 0 };
                cx.stmts(&mut l.body)?;
                Type::Action
            }
            ExprKind::Method { .. } | ExprKind::Variant { .. } | ExprKind::Go { .. } => unreachable!("rewritten by method()"),
            ExprKind::Match { scrut, arms } => {
                let st = self.expr(scrut, true)?;
                let en = match &st {
                    Type::Struct(n) => self.info.enums.iter().find(|x| &x.name == n).ok_or((line, format!("`match` needs an enum, found {}", n)))?,
                    _ => return Err((line, format!("`match` needs an enum, found {}", tname(&st)))),
                };
                let mut rt: Option<Type> = None;
                let mut seen = vec![false; en.variants.len()];
                for a in arms.iter_mut() {
                    let (vi, (_, fields)) = en.variants.iter().enumerate().find(|(_, v)| v.0 == a.variant)
                        .ok_or((a.line, format!("enum {} has no variant `{}`", en.name, a.variant)))?;
                    if seen[vi] { return Err((a.line, format!("variant `{}` matched twice", a.variant))); }
                    seen[vi] = true;
                    if a.binders.len() != fields.len() {
                        return Err((a.line, format!("`{}` has {} field(s), the pattern binds {}", a.variant, fields.len(), a.binders.len())));
                    }
                    a.tag = vi;
                    a.btys = fields.iter().map(|f| f.1.clone()).collect();
                    self.scopes.push(HashMap::new());
                    for (b, bt) in a.binders.iter().zip(&a.btys) {
                        if self.find(b).is_some() { return Err((a.line, format!("`{}` is already defined (no shadowing)", b))); }
                        self.scopes.last_mut().unwrap().insert(b.clone(), Var { ty: bt.clone(), mutable: false });
                    }
                    let t = self.expr(&mut a.body, false)?;
                    self.scopes.pop();
                    if t != Type::Int && t != Type::Str { return Err((a.body.line, format!("a match arm must give Int or Str, found {}", tname(&t)))); }
                    match &rt { None => rt = Some(t), Some(r) if *r != t => return Err((a.body.line, format!("match arms disagree: {} and {}", tname(r), tname(&t)))), _ => {} }
                }
                if let Some(i) = seen.iter().position(|s| !*s) { return Err((line, format!("`match` misses variant `{}`", en.variants[i].0))); }
                rt.unwrap()
            }
            ExprKind::Call { name, args } => {
                if let Some(si) = self.info.structs.iter().find(|s| &s.name == name) {
                    self.args(line, name, &si.fields, args)?;
                    Type::Struct(name.clone())
                } else if self.info.enums.iter().any(|s| &s.name == name) {
                    return Err((line, format!("build an enum value with `{}.Variant(..)`", name)));
                } else if let Some((ps, ret)) = self.info.fns.get(name.as_str()) {
                    self.args(line, name, ps, args)?;
                    ret.clone()
                } else {
                    return Err((line, format!("unknown function `{}`", name)));
                }
            }
        };
        e.ty = t.clone();
        Ok(t)
    }
    // `recv.name(args)`: an enum variant constructor (`Shape.Rect(w: 3, h: 4)`) or `crew.go(task: fn() { .. })`.
    fn method(&mut self, e: &mut Expr) -> R<()> {
        let line = e.line;
        let ExprKind::Method { recv, name, args } = std::mem::replace(&mut e.kind, ExprKind::Int(0)) else { unreachable!() };
        let ExprKind::Name(rn) = &recv.kind else { return Err((line, "methods are only supported on a crew handle or an enum name".into())) };
        if let Some(v) = self.find(rn) {
            if v.ty != Type::Crew { return Err((line, format!("`{}` has no methods", rn))); }
            if name != "go" { return Err((line, format!("crew has no method `{}`", name))); }
            let mut args = args;
            if args.len() != 1 || args[0].label != "task" { return Err((line, "`go` takes one argument: `task: fn() { .. }`".into())); }
            let mut a = args.pop().unwrap();
            if !matches!(a.value.kind, ExprKind::Lambda(_)) { return Err((line, "`task:` must be a lambda `fn() { .. }`".into())); }
            self.expr(&mut a.value, false)?;
            let ExprKind::Lambda(l) = a.value.kind else { unreachable!() };
            e.kind = ExprKind::Go { crew: rn.clone(), task: l };
            return Ok(());
        }
        let Some(en) = self.info.enums.iter().find(|x| &x.name == rn) else { return Err((line, format!("unknown name `{}`", rn))) };
        let (vi, (_, fields)) = en.variants.iter().enumerate().find(|(_, v)| v.0 == name)
            .ok_or((line, format!("enum {} has no variant `{}`", en.name, name)))?;
        let mut args = args;
        self.args(line, &name, fields, &mut args)?;
        e.kind = ExprKind::Variant { en: rn.clone(), tag: vi, args };
        Ok(())
    }
    fn args(&mut self, line: u32, name: &str, ps: &[(String, Type)], args: &mut Vec<Arg>) -> R<()> {
        if args.len() != ps.len() { return Err((line, format!("`{}` takes {} argument(s), got {}", name, ps.len(), args.len()))); }
        for (a, (pn, pt)) in args.iter_mut().zip(ps) {
            if &a.label != pn {
                return Err((a.value.line, if a.pun { format!("no parameter `{}` here: write `{}: {}`", a.label, pn, a.label) }
                    else { format!("expected label `{}:`, found `{}:`", pn, a.label) }));
            }
            let t = self.expr(&mut a.value, false)?;
            if &t != pt { return Err((a.value.line, format!("argument `{}` expects {}, found {}", pn, tname(pt), tname(&t)))); }
        }
        Ok(())
    }
}
