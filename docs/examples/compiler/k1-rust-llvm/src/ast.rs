// AST shared by every stage. `ty` on Expr is filled in by the checker.
pub type R<T> = Result<T, (u32, String)>;

#[derive(Clone, Debug, PartialEq)]
pub enum Type { Int, Str, Bool, Unit, Struct(String), Action }

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BinOp { Add, Sub, Mul, Lt, Gt, Eq }

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
}

#[derive(Debug)]
pub enum IPart { Lit(String), Expr(Expr) }

#[derive(Debug)]
pub struct Arg { pub label: String, pub value: Expr, pub pun: bool }

#[derive(Debug)]
pub struct Lambda { pub body: Vec<Stmt>, pub line: u32, pub end_line: u32 }

#[derive(Debug)]
pub struct Stmt { pub kind: StmtKind, pub line: u32 }

#[derive(Debug)]
pub enum StmtKind {
    Let { name: String, mutable: bool, ann: Option<Type>, init: Expr },
    Assign { name: String, op: Option<BinOp>, value: Expr },
    If { cond: Expr, then: Vec<Stmt>, els: Option<Vec<Stmt>> },
    While { cond: Expr, body: Vec<Stmt> },
    Return(Option<Expr>),
    Expr(Expr),
}

#[derive(Debug)]
pub struct FnDecl {
    pub name: String,
    pub params: Vec<(String, Type)>,
    pub ret: Type,
    pub body: Vec<Stmt>,
    pub line: u32,
    pub end_line: u32,
}

#[derive(Debug)]
pub struct TypeDecl {
    pub name: String,
    pub fields: Vec<(String, Type)>,
    pub drop: Option<FnDecl>,
    pub line: u32,
}

#[derive(Debug)]
pub struct Program { pub types: Vec<TypeDecl>, pub fns: Vec<FnDecl> }
