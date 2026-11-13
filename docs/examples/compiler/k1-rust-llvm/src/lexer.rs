// Lexer: newline ends a statement except directly inside ( ) or [ ] (ADR-0006 rule 1).
use crate::ast::R;

#[derive(Clone, Debug, PartialEq)]
pub enum Part { Lit(String), Expr(String, u32) }

#[derive(Clone, Debug, PartialEq)]
pub enum Tok { Ident(String), Int(i64), Str(Vec<Part>), Sym(&'static str), Newline, Eof }

#[derive(Clone, Debug)]
pub struct Token { pub tok: Tok, pub line: u32 }

const SYMS: [&str; 20] = ["->", "==", "+=", "-=", "{", "}", "(", ")", "[", "]", ",", ":", ".", ";", "+", "-", "*", "<", ">", "="];

pub fn lex(src: &str, start_line: u32) -> R<Vec<Token>> {
    let ch: Vec<char> = src.chars().collect();
    let (mut i, mut line) = (0usize, start_line);
    let mut stack: Vec<char> = vec![];
    let mut out: Vec<Token> = vec![];
    while i < ch.len() {
        let c = ch[i];
        if c == '\n' {
            if !matches!(stack.last(), Some('(') | Some('[')) {
                out.push(Token { tok: Tok::Newline, line });
            }
            line += 1;
            i += 1;
        } else if c == ' ' || c == '\t' || c == '\r' {
            i += 1;
        } else if c == '#' {
            while i < ch.len() && ch[i] != '\n' { i += 1; }
        } else if c == '"' {
            i += 1;
            let (mut lit, mut parts) = (String::new(), vec![]);
            loop {
                if i >= ch.len() || ch[i] == '\n' { return Err((line, "unterminated string".into())); }
                match ch[i] {
                    '"' => { i += 1; break; }
                    '\\' => {
                        i += 1;
                        let e = *ch.get(i).ok_or((line, "bad escape".to_string()))?;
                        lit.push(match e { 'n' => '\n', 't' => '\t', '"' => '"', '\\' => '\\', '{' => '{', '}' => '}',
                            _ => return Err((line, format!("unknown escape \\{}", e))) });
                        i += 1;
                    }
                    '{' => {
                        if !lit.is_empty() { parts.push(Part::Lit(std::mem::take(&mut lit))); }
                        i += 1;
                        let (mut depth, mut s) = (1, String::new());
                        while i < ch.len() && ch[i] != '\n' {
                            if ch[i] == '{' { depth += 1; }
                            if ch[i] == '}' { depth -= 1; if depth == 0 { break; } }
                            s.push(ch[i]);
                            i += 1;
                        }
                        if i >= ch.len() || ch[i] != '}' { return Err((line, "unterminated {..} in string".into())); }
                        i += 1;
                        parts.push(Part::Expr(s, line));
                    }
                    c => { lit.push(c); i += 1; }
                }
            }
            if !lit.is_empty() || parts.is_empty() { parts.push(Part::Lit(lit)); }
            out.push(Token { tok: Tok::Str(parts), line });
        } else if c.is_ascii_digit() {
            let mut n: i64 = 0;
            while i < ch.len() && (ch[i].is_ascii_digit() || ch[i] == '_') {
                if ch[i] != '_' { n = n.checked_mul(10).and_then(|n| n.checked_add(ch[i] as i64 - 48)).ok_or((line, "integer too large".to_string()))?; }
                i += 1;
            }
            out.push(Token { tok: Tok::Int(n), line });
        } else if c.is_alphabetic() || c == '_' {
            let mut s = String::new();
            while i < ch.len() && (ch[i].is_alphanumeric() || ch[i] == '_') { s.push(ch[i]); i += 1; }
            out.push(Token { tok: Tok::Ident(s), line });
        } else {
            let rest: String = ch[i..(i + 2).min(ch.len())].iter().collect();
            let sym = SYMS.iter().find(|s| rest.starts_with(**s)).ok_or((line, format!("unexpected character '{}'", c)))?;
            match *sym {
                "(" | "[" | "{" => stack.push(sym.chars().next().unwrap()),
                ")" | "]" | "}" => { stack.pop(); }
                _ => {}
            }
            i += sym.len();
            out.push(Token { tok: Tok::Sym(sym), line });
        }
    }
    out.push(Token { tok: Tok::Eof, line });
    Ok(out)
}
