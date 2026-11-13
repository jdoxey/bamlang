// Recursive-descent parser: tokens -> AST.
use crate::ast::*;
use crate::lexer::{lex, Part, Tok, Token};

const KEYWORDS: [&str; 11] = ["type", "fn", "let", "var", "if", "else", "while", "return", "self", "mut", "drop"];

pub struct Parser { toks: Vec<Token>, pos: usize }

pub fn parse(src: &str) -> R<Program> {
    let mut p = Parser { toks: lex(src, 1)?, pos: 0 };
    let mut prog = Program { types: vec![], fns: vec![] };
    loop {
        p.skip_nl();
        if p.tok() == &Tok::Eof { return Ok(prog); }
        if p.is_kw("type") { prog.types.push(p.type_decl()?); }
        else if p.is_kw("fn") { prog.fns.push(p.fn_decl()?); }
        else { return Err((p.line(), "expected `type` or `fn` at top level".into())); }
    }
}

impl Parser {
    fn tok(&self) -> &Tok { &self.toks[self.pos].tok }
    fn line(&self) -> u32 { self.toks[self.pos].line }
    fn next(&mut self) -> Token { let t = self.toks[self.pos].clone(); if self.pos + 1 < self.toks.len() { self.pos += 1; } t }
    fn is_sym(&self, s: &str) -> bool { matches!(self.tok(), Tok::Sym(x) if *x == s) }
    fn is_kw(&self, k: &str) -> bool { matches!(self.tok(), Tok::Ident(x) if x == k) }
    fn peek2(&self) -> &Tok { &self.toks[(self.pos + 1).min(self.toks.len() - 1)].tok }
    fn eat_sym(&mut self, s: &str) -> bool { if self.is_sym(s) { self.next(); true } else { false } }
    fn expect_sym(&mut self, s: &str) -> R<()> {
        if self.eat_sym(s) { Ok(()) } else { Err((self.line(), format!("expected `{}`, found {}", s, self.describe()))) }
    }
    fn describe(&self) -> String {
        match self.tok() { Tok::Ident(s) => format!("`{}`", s), Tok::Sym(s) => format!("`{}`", s), Tok::Newline => "end of line".into(),
            Tok::Eof => "end of file".into(), Tok::Int(n) => n.to_string(), Tok::Str(_) => "string".into() }
    }
    fn skip_nl(&mut self) { while self.tok() == &Tok::Newline || self.is_sym(";") { self.next(); } }
    fn ident(&mut self) -> R<String> {
        match self.tok().clone() {
            Tok::Ident(s) if !KEYWORDS.contains(&s.as_str()) => { self.next(); Ok(s) }
            _ => Err((self.line(), format!("expected a name, found {}", self.describe()))),
        }
    }
    fn expect_kw(&mut self, k: &str) -> R<()> {
        if self.is_kw(k) { self.next(); Ok(()) } else { Err((self.line(), format!("expected `{}`, found {}", k, self.describe()))) }
    }
    fn ty(&mut self) -> R<Type> {
        let n = self.ident()?;
        Ok(match n.as_str() { "Int" => Type::Int, "Str" => Type::Str, _ => Type::Struct(n) })
    }

    fn type_decl(&mut self) -> R<TypeDecl> {
        let line = self.line();
        self.expect_kw("type")?;
        let name = self.ident()?;
        self.expect_sym("{")?;
        let (mut fields, mut drop) = (vec![], None);
        loop {
            while self.tok() == &Tok::Newline || self.is_sym(",") { self.next(); }
            if self.eat_sym("}") { break; }
            if self.is_kw("drop") {
                let dl = self.line();
                self.next();
                self.expect_sym("(")?;
                self.expect_kw("mut")?;
                self.expect_kw("self")?;
                self.expect_sym(")")?;
                let (body, end_line) = self.block()?;
                drop = Some(FnDecl { name: "drop".into(), params: vec![], ret: Type::Unit, body, line: dl, end_line });
            } else {
                let f = self.ident()?;
                self.expect_sym(":")?;
                fields.push((f, self.ty()?));
            }
        }
        Ok(TypeDecl { name, fields, drop, line })
    }

    fn fn_decl(&mut self) -> R<FnDecl> {
        let line = self.line();
        self.expect_kw("fn")?;
        let name = self.ident()?;
        self.expect_sym("(")?;
        let mut params = vec![];
        while !self.is_sym(")") {
            let n = self.ident()?;
            self.expect_sym(":")?;
            params.push((n, self.ty()?));
            if !self.eat_sym(",") { break; }
        }
        self.expect_sym(")")?;
        let ret = if self.eat_sym("->") { self.ty()? } else { Type::Unit };
        let (body, end_line) = self.block()?;
        Ok(FnDecl { name, params, ret, body, line, end_line })
    }

    fn block(&mut self) -> R<(Vec<Stmt>, u32)> {
        self.expect_sym("{")?;
        let mut v = vec![];
        loop {
            self.skip_nl();
            if self.is_sym("}") { let l = self.line(); self.next(); return Ok((v, l)); }
            if self.tok() == &Tok::Eof { return Err((self.line(), "missing `}`".into())); }
            v.push(self.stmt()?);
            if !(self.tok() == &Tok::Newline || self.is_sym(";") || self.is_sym("}")) {
                return Err((self.line(), format!("expected end of line, found {}", self.describe())));
            }
        }
    }

    fn stmt(&mut self) -> R<Stmt> {
        let line = self.line();
        let kind = if self.is_kw("let") || self.is_kw("var") {
            let mutable = self.is_kw("var");
            self.next();
            let name = self.ident()?;
            let ann = if self.eat_sym(":") { Some(self.ty()?) } else { None };
            self.expect_sym("=")?;
            StmtKind::Let { name, mutable, ann, init: self.expr()? }
        } else if self.is_kw("if") {
            self.next();
            let cond = self.expr()?;
            let (then, _) = self.block()?;
            let mut els = None;
            if self.is_kw("else") { // `} else {` stays on one line (rule 4)
                self.next();
                if self.is_kw("if") { els = Some(vec![self.stmt()?]); } else { els = Some(self.block()?.0); }
            }
            StmtKind::If { cond, then, els }
        } else if self.is_kw("while") {
            self.next();
            let cond = self.expr()?;
            StmtKind::While { cond, body: self.block()?.0 }
        } else if self.is_kw("return") {
            self.next();
            if matches!(self.tok(), Tok::Newline | Tok::Eof) || self.is_sym("}") || self.is_sym(";") { StmtKind::Return(None) }
            else { StmtKind::Return(Some(self.expr()?)) }
        } else {
            let e = self.expr()?;
            let op = if self.is_sym("=") { Some(None) } else if self.is_sym("+=") { Some(Some(BinOp::Add)) }
                else if self.is_sym("-=") { Some(Some(BinOp::Sub)) } else { None };
            match (op, &e.kind) {
                (Some(op), ExprKind::Name(n)) => { let n = n.clone(); self.next(); StmtKind::Assign { name: n, op, value: self.expr()? } }
                (Some(_), _) => return Err((line, "can only assign to a variable name".into())),
                (None, _) => StmtKind::Expr(e),
            }
        };
        Ok(Stmt { kind, line })
    }

    fn mk(kind: ExprKind, line: u32) -> Expr { Expr { kind, line, ty: Type::Unit } }

    pub fn expr(&mut self) -> R<Expr> {
        let l = self.add()?;
        let op = if self.is_sym("<") { BinOp::Lt } else if self.is_sym(">") { BinOp::Gt } else if self.is_sym("==") { BinOp::Eq } else { return Ok(l) };
        let line = self.line();
        self.next();
        let r = self.add()?;
        if self.is_sym("<") || self.is_sym(">") || self.is_sym("==") { return Err((self.line(), "comparisons don't chain; use parentheses".into())); }
        Ok(Self::mk(ExprKind::Bin(op, Box::new(l), Box::new(r)), line))
    }
    fn add(&mut self) -> R<Expr> {
        let mut l = self.mul()?;
        loop {
            let op = if self.is_sym("+") { BinOp::Add } else if self.is_sym("-") { BinOp::Sub } else { return Ok(l) };
            let line = self.line();
            self.next();
            let r = self.mul()?;
            l = Self::mk(ExprKind::Bin(op, Box::new(l), Box::new(r)), line);
        }
    }
    fn mul(&mut self) -> R<Expr> {
        let mut l = self.postfix()?;
        while self.is_sym("*") {
            let line = self.line();
            self.next();
            let r = self.postfix()?;
            l = Self::mk(ExprKind::Bin(BinOp::Mul, Box::new(l), Box::new(r)), line);
        }
        Ok(l)
    }
    fn postfix(&mut self) -> R<Expr> {
        let mut e = self.primary()?;
        while self.is_sym(".") {
            let line = self.line();
            self.next();
            let f = match self.next().tok { Tok::Ident(s) => s, _ => return Err((line, "expected a field name after `.`".into())) };
            e = Self::mk(ExprKind::Field(Box::new(e), f), line);
        }
        Ok(e)
    }
    fn primary(&mut self) -> R<Expr> {
        let line = self.line();
        match self.tok().clone() {
            Tok::Int(n) => { self.next(); Ok(Self::mk(ExprKind::Int(n), line)) }
            Tok::Str(parts) => {
                self.next();
                let mut out = vec![];
                for p in parts {
                    out.push(match p {
                        Part::Lit(s) => IPart::Lit(s),
                        Part::Expr(src, l) => {
                            let mut sub = Parser { toks: lex(&src, l)?, pos: 0 };
                            let e = sub.expr()?;
                            if sub.tok() != &Tok::Eof { return Err((l, "bad expression in string".into())); }
                            IPart::Expr(e)
                        }
                    });
                }
                Ok(Self::mk(ExprKind::Interp(out), line))
            }
            Tok::Sym("(") => { self.next(); let e = self.expr()?; self.expect_sym(")")?; Ok(e) }
            Tok::Ident(s) if s == "fn" => {
                self.next();
                self.expect_sym("(")?;
                self.expect_sym(")")?;
                let (body, end_line) = self.block()?;
                Ok(Self::mk(ExprKind::Lambda(Box::new(Lambda { body, line, end_line })), line))
            }
            Tok::Ident(s) if s == "self" => { self.next(); Ok(Self::mk(ExprKind::Name(s), line)) }
            Tok::Ident(_) => {
                let name = self.ident()?;
                if !self.is_sym("(") { return Ok(Self::mk(ExprKind::Name(name), line)); }
                self.next();
                let mut args = vec![];
                while !self.is_sym(")") {
                    let al = self.line();
                    if matches!(self.tok(), Tok::Ident(_)) && self.peek2() == &Tok::Sym(":") {
                        let label = self.ident()?;
                        self.next();
                        args.push(Arg { label, value: self.expr()?, pun: false });
                    } else {
                        let v = self.expr()?;
                        match &v.kind {
                            ExprKind::Name(n) if n != "self" => args.push(Arg { label: n.clone(), value: v, pun: true }),
                            _ => return Err((al, "every argument needs a label: write `name: value`".into())),
                        }
                    }
                    if !self.eat_sym(",") { break; }
                }
                self.expect_sym(")")?;
                Ok(Self::mk(ExprKind::Call { name, args }, line))
            }
            _ => Err((line, format!("expected an expression, found {}", self.describe()))),
        }
    }
}
