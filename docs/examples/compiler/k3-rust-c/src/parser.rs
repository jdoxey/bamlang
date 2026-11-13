// Recursive-descent parser: tokens to AST.
use crate::ast::*;
use crate::lexer::{lex, Tok, Token};

pub struct Parser { toks: Vec<Token>, pos: usize }

type R<T> = Result<T, String>;

pub fn parse_program(src: &str) -> R<Program> {
    let mut p = Parser { toks: lex(src, 1)?, pos: 0 };
    let mut prog = Program::default();
    while p.peek() != &Tok::Eof {
        let line = p.line();
        match p.ident()?.as_str() {
            "type" => prog.types.push(p.type_decl(line)?),
            "fn" => prog.fns.push(p.fn_decl(line)?),
            other => return Err(format!("{}: expected 'type' or 'fn', found '{}'", line, other)),
        }
    }
    Ok(prog)
}

impl Parser {
    fn peek(&self) -> &Tok { &self.toks[self.pos].tok }
    fn peek2(&self) -> &Tok { &self.toks[(self.pos + 1).min(self.toks.len() - 1)].tok }
    fn line(&self) -> u32 { self.toks[self.pos].line }
    fn next(&mut self) -> Tok { let t = self.toks[self.pos].tok.clone(); if self.pos + 1 < self.toks.len() { self.pos += 1; } t }
    fn is_sym(&self, s: &str) -> bool { matches!(self.peek(), Tok::Sym(x) if *x == s) }
    fn is_kw(&self, s: &str) -> bool { matches!(self.peek(), Tok::Ident(x) if x == s) }
    fn eat_sym(&mut self, s: &str) -> bool { if self.is_sym(s) { self.next(); true } else { false } }
    fn expect(&mut self, s: &str) -> R<()> {
        if self.eat_sym(s) { Ok(()) } else { Err(format!("{}: expected '{}', found {:?}", self.line(), s, self.peek())) }
    }
    fn ident(&mut self) -> R<String> {
        match self.next() { Tok::Ident(s) => Ok(s), t => Err(format!("{}: expected identifier, found {:?}", self.toks[self.pos].line, t)) }
    }
    fn ty(&mut self) -> R<Ty> {
        let line = self.line();
        Ok(match self.ident()?.as_str() {
            "Int" => Ty::Int, "Str" => Ty::Str, "Bool" => Ty::Bool,
            n if n.chars().next().map_or(false, |c| c.is_uppercase()) => Ty::Named(n.to_string()),
            n => return Err(format!("{}: unknown type '{}'", line, n)),
        })
    }

    fn type_decl(&mut self, line: u32) -> R<TypeDecl> {
        let name = self.ident()?;
        self.expect("{")?;
        let mut fields = Vec::new();
        let mut drop = None;
        while !self.is_sym("}") {
            if self.is_kw("drop") && self.peek2() == &Tok::Sym("(") {
                self.next(); self.expect("(")?;
                if !self.is_kw("mut") { return Err(format!("{}: drop takes (mut self)", self.line())); }
                self.next();
                if !self.is_kw("self") { return Err(format!("{}: drop takes (mut self)", self.line())); }
                self.next(); self.expect(")")?;
                drop = Some(self.block()?);
            } else {
                let f = self.ident()?;
                self.expect(":")?;
                fields.push((f, self.ty()?));
                self.eat_sym(",");
            }
        }
        self.expect("}")?;
        Ok(TypeDecl { name, fields, drop, line })
    }

    fn fn_decl(&mut self, line: u32) -> R<FnDecl> {
        let name = self.ident()?;
        self.expect("(")?;
        let mut params = Vec::new();
        while !self.is_sym(")") {
            let n = self.ident()?;
            self.expect(":")?;
            params.push((n, self.ty()?));
            if !self.eat_sym(",") { break; }
        }
        self.expect(")")?;
        let ret = if self.eat_sym("->") { self.ty()? } else { Ty::Unit };
        Ok(FnDecl { name, params, ret, body: self.block()?, line })
    }

    fn block(&mut self) -> R<Vec<Stmt>> {
        self.expect("{")?;
        let mut v = Vec::new();
        while !self.is_sym("}") {
            if self.peek() == &Tok::Eof { return Err(format!("{}: unexpected end of file in block", self.line())); }
            v.push(self.stmt()?);
        }
        self.expect("}")?;
        Ok(v)
    }

    fn stmt(&mut self) -> R<Stmt> {
        let line = self.line();
        let kind = if self.is_kw("let") || self.is_kw("var") {
            let mutable = self.is_kw("var");
            self.next();
            let name = self.ident()?;
            let ann = if self.eat_sym(":") { Some(self.ty()?) } else { None };
            self.expect("=")?;
            StmtKind::Let { name, mutable, ann, init: self.expr()? }
        } else if self.is_kw("if") {
            self.next();
            let cond = self.expr()?;
            let then = self.block()?;
            let els = if self.is_kw("else") { self.next(); Some(self.block()?) } else { None };
            StmtKind::If { cond, then, els }
        } else if self.is_kw("while") {
            self.next();
            let cond = self.expr()?;
            StmtKind::While { cond, body: self.block()? }
        } else if self.is_kw("return") {
            self.next();
            if self.is_sym("}") { StmtKind::Return(None) } else { StmtKind::Return(Some(self.expr()?)) }
        } else {
            let e = self.expr()?;
            if self.is_sym("=") || self.is_sym("+=") {
                let add = self.is_sym("+=");
                self.next();
                StmtKind::Assign { target: e, add, value: self.expr()? }
            } else { StmtKind::Expr(e) }
        };
        Ok(Stmt { kind, line })
    }

    pub fn expr(&mut self) -> R<Expr> {
        let l = self.add()?;
        let op = if self.is_sym("<") { BinOp::Lt } else if self.is_sym(">") { BinOp::Gt } else if self.is_sym("==") { BinOp::Eq } else { return Ok(l) };
        let line = self.line();
        self.next();
        let r = self.add()?;
        Ok(Expr::new(ExprKind::Binary(op, Box::new(l), Box::new(r)), line))
    }
    fn add(&mut self) -> R<Expr> {
        let mut l = self.mul()?;
        loop {
            let op = if self.is_sym("+") { BinOp::Add } else if self.is_sym("-") { BinOp::Sub } else { return Ok(l) };
            let line = self.line();
            self.next();
            let r = self.mul()?;
            l = Expr::new(ExprKind::Binary(op, Box::new(l), Box::new(r)), line);
        }
    }
    fn mul(&mut self) -> R<Expr> {
        let mut l = self.postfix()?;
        while self.is_sym("*") {
            let line = self.line();
            self.next();
            let r = self.postfix()?;
            l = Expr::new(ExprKind::Binary(BinOp::Mul, Box::new(l), Box::new(r)), line);
        }
        Ok(l)
    }
    fn postfix(&mut self) -> R<Expr> {
        let mut e = self.primary()?;
        while self.is_sym(".") {
            let line = self.line();
            self.next();
            let f = self.ident()?;
            e = Expr::new(ExprKind::Field(Box::new(e), f), line);
        }
        Ok(e)
    }
    fn primary(&mut self) -> R<Expr> {
        let line = self.line();
        match self.next() {
            Tok::Int(n) => Ok(Expr::new(ExprKind::Int(n), line)),
            Tok::Str(raw) => Ok(Expr::new(ExprKind::Str(split_string(&raw, line)?), line)),
            Tok::Sym("(") => { let e = self.expr()?; self.expect(")")?; Ok(e) }
            Tok::Ident(n) if n == "fn" => {
                self.expect("(")?; self.expect(")")?;
                Ok(Expr::new(ExprKind::Lambda(self.block()?), line))
            }
            Tok::Ident(n) => {
                if !self.is_sym("(") { return Ok(Expr::new(ExprKind::Var(n), line)); }
                self.next();
                let mut args = Vec::new();
                while !self.is_sym(")") {
                    if matches!(self.peek(), Tok::Ident(_)) && self.peek2() == &Tok::Sym(":") {
                        let label = self.ident()?;
                        self.next();
                        args.push(Arg { label: Some(label), value: self.expr()? });
                    } else {
                        // pun: `area(p, ...)` means `p: p`
                        let v = self.expr()?;
                        match &v.kind {
                            ExprKind::Var(name) => args.push(Arg { label: Some(name.clone()), value: v.clone() }),
                            _ => return Err(format!("{}: argument needs a label", v.line)),
                        }
                    }
                    if !self.eat_sym(",") { break; }
                }
                self.expect(")")?;
                Ok(Expr::new(ExprKind::Call { callee: n, args }, line))
            }
            t => Err(format!("{}: unexpected {:?} in expression", line, t)),
        }
    }
}

// Split a raw string body into literal text and {expr} interpolations, processing escapes.
fn split_string(raw: &str, line: u32) -> R<Vec<StrPart>> {
    let c: Vec<char> = raw.chars().collect();
    let mut parts = Vec::new();
    let mut lit = String::new();
    let mut i = 0;
    while i < c.len() {
        match c[i] {
            '\\' => {
                i += 1;
                lit.push(match c.get(i) { Some('n') => '\n', Some('t') => '\t', Some(x) => *x, None => '\\' });
                i += 1;
            }
            '{' => {
                let mut depth = 1;
                let s = i + 1;
                i += 1;
                while i < c.len() && depth > 0 {
                    if c[i] == '{' { depth += 1; } else if c[i] == '}' { depth -= 1; }
                    i += 1;
                }
                if depth != 0 { return Err(format!("{}: unterminated interpolation", line)); }
                let inner: String = c[s..i - 1].iter().collect();
                let mut p = Parser { toks: lex(&inner, line)?, pos: 0 };
                let e = p.expr()?;
                if p.peek() != &Tok::Eof { return Err(format!("{}: junk in interpolation", line)); }
                if !lit.is_empty() { parts.push(StrPart::Lit(std::mem::take(&mut lit))); }
                parts.push(StrPart::Interp(e));
            }
            ch => { lit.push(ch); i += 1; }
        }
    }
    if !lit.is_empty() || parts.is_empty() { parts.push(StrPart::Lit(lit)); }
    Ok(parts)
}
