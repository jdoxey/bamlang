// Lexer: source text to tokens. Strings keep their raw body; the parser splits out {interpolations}.
#[derive(Clone, Debug, PartialEq)]
pub enum Tok { Ident(String), Int(i64), Str(String), Sym(&'static str), Eof }

#[derive(Clone, Debug)]
pub struct Token { pub tok: Tok, pub line: u32 }

const SYMS2: [&str; 3] = ["->", "==", "+="];
const SYMS1: [&str; 11] = ["{", "}", "(", ")", ",", ":", "+", "-", "*", "<", ">"];
const SYMS1B: [&str; 2] = ["=", "."];

pub fn lex(src: &str, first_line: u32) -> Result<Vec<Token>, String> {
    let c: Vec<char> = src.chars().collect();
    let mut i = 0;
    let mut line = first_line;
    let mut out = Vec::new();
    while i < c.len() {
        let ch = c[i];
        if ch == '\n' { line += 1; i += 1; continue; }
        if ch.is_whitespace() { i += 1; continue; }
        if ch == '#' { while i < c.len() && c[i] != '\n' { i += 1; } continue; }
        if ch.is_ascii_digit() {
            let s = i;
            while i < c.len() && (c[i].is_ascii_digit() || c[i] == '_') { i += 1; }
            let t: String = c[s..i].iter().filter(|x| **x != '_').collect();
            out.push(Token { tok: Tok::Int(t.parse().map_err(|_| format!("{}: bad integer", line))?), line });
            continue;
        }
        if ch.is_alphabetic() || ch == '_' {
            let s = i;
            while i < c.len() && (c[i].is_alphanumeric() || c[i] == '_') { i += 1; }
            out.push(Token { tok: Tok::Ident(c[s..i].iter().collect()), line });
            continue;
        }
        if ch == '"' {
            let start_line = line;
            i += 1;
            let mut s = String::new();
            let mut depth = 0;
            loop {
                if i >= c.len() { return Err(format!("{}: unterminated string", start_line)); }
                let d = c[i];
                if d == '\\' && i + 1 < c.len() { s.push(d); s.push(c[i + 1]); i += 2; continue; }
                if d == '\n' { line += 1; }
                if d == '{' { depth += 1; }
                if d == '}' { depth -= 1; }
                if d == '"' && depth <= 0 { i += 1; break; }
                s.push(d);
                i += 1;
            }
            out.push(Token { tok: Tok::Str(s), line: start_line });
            continue;
        }
        let two: String = c[i..(i + 2).min(c.len())].iter().collect();
        if let Some(s) = SYMS2.iter().find(|s| **s == two) {
            out.push(Token { tok: Tok::Sym(s), line }); i += 2; continue;
        }
        let one = ch.to_string();
        if let Some(s) = SYMS1.iter().chain(SYMS1B.iter()).find(|s| **s == one) {
            out.push(Token { tok: Tok::Sym(s), line }); i += 1; continue;
        }
        return Err(format!("{}: unexpected character '{}'", line, ch));
    }
    out.push(Token { tok: Tok::Eof, line });
    Ok(out)
}
