// AST shared by every stage. `ty` on Expr is filled in by the checker.
pub type R<T> = Result<T, (u32, String)>;

// `Struct(name)` names a `type` or an `enum` (the checker knows which). `Crew` is the handle bound by `crew c { }`.
#[derive(Clone, Debug, PartialEq)]
pub enum Type { Int, Str, Bool, Unit, Struct(String), Action, Crew }

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BinOp { Add, Sub, Mul, Lt, Gt, Eq }

// A source range: start (line, col) to end (line, col), end column exclusive. Columns are 1-based.
#[derive(Clone, Copy, Debug, Default)]
pub struct Span { pub l1: u32, pub c1: u32, pub l2: u32, pub c2: u32 }

#[derive(Debug)]
pub struct Expr { pub kind: ExprKind, pub line: u32, pub ty: Type }

#[derive(Debug)]
pub enum ExprKind {
    Int(i64),
    Interp(Vec<IPart>),
    Name(String),
    Field(Box<Expr>, String),
    Call { name: String, args: Vec<Arg> },
    Bin(BinOp, Box<Expr>, Box<Expr>),
    Lambda(Box<Lambda>),
    // Parser output for `recv.name(args)`; the checker turns it into Variant or Go.
    Method { recv: Box<Expr>, name: String, args: Vec<Arg> },
    Variant { en: String, tag: usize, args: Vec<Arg> },
    Go { crew: String, task: Box<Lambda> },
    Match { scrut: Box<Expr>, arms: Vec<Arm> },
}

#[derive(Debug)]
pub struct Arm { pub variant: String, pub binders: Vec<String>, pub body: Expr, pub line: u32, pub span: Span, pub tag: usize, pub btys: Vec<Type> }

#[derive(Debug)]
pub enum IPart { Lit(String), Expr(Expr) }

#[derive(Debug)]
pub struct Arg { pub label: String, pub value: Expr, pub pun: bool }

#[derive(Debug)]
pub struct Lambda { pub body: Vec<Stmt>, pub line: u32, pub span: Span }

// `end` is the end position (line, col exclusive) of the statement's last token.
#[derive(Debug)]
pub struct Stmt { pub kind: StmtKind, pub line: u32, pub end: (u32, u32) }

#[derive(Debug)]
pub enum StmtKind {
    Let { name: String, mutable: bool, ann: Option<Type>, init: Expr },
    Assign { name: String, op: Option<BinOp>, value: Expr },
    If { cond: Expr, cond_span: Span, then: Vec<Stmt>, then_span: Span, els: Option<(Vec<Stmt>, Span)> },
    While { cond: Expr, cond_span: Span, body: Vec<Stmt>, body_span: Span },
    Return(Option<Expr>),
    Expr(Expr),
    Crew { name: String, body: Vec<Stmt>, span: Span },
}

#[derive(Debug)]
pub struct FnDecl {
    pub name: String,
    pub params: Vec<(String, Type)>,
    pub ret: Type,
    pub body: Vec<Stmt>,
    pub line: u32,
    pub end_line: u32,
    pub span: Span,
}

#[derive(Debug)]
pub struct TypeDecl {
    pub name: String,
    pub fields: Vec<(String, Type)>,
    pub drop: Option<FnDecl>,
    pub line: u32,
}

#[derive(Debug)]
pub struct EnumDecl { pub name: String, pub variants: Vec<(String, Vec<(String, Type)>)>, pub line: u32 }

#[derive(Debug)]
pub struct Program { pub types: Vec<TypeDecl>, pub enums: Vec<EnumDecl>, pub fns: Vec<FnDecl> }
