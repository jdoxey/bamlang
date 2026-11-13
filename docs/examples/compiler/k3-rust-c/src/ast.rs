// AST for the spike subset.
#[derive(Clone, Debug, PartialEq)]
pub enum Ty { Int, Str, Bool, Unit, Crew, Named(String) }

#[derive(Clone, Debug)]
pub struct Expr { pub kind: ExprKind, pub line: u32, pub ty: Ty }
impl Expr {
    pub fn new(kind: ExprKind, line: u32) -> Expr { Expr { kind, line, ty: Ty::Unit } }
}

#[derive(Clone, Debug)]
pub enum StrPart { Lit(String), Interp(Expr) }

#[derive(Clone, Debug)]
pub struct Arg { pub label: Option<String>, pub value: Expr }

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum BinOp { Add, Sub, Mul, Lt, Gt, Eq }

#[derive(Clone, Debug)]
pub enum ExprKind {
    Int(i64),
    Str(Vec<StrPart>),
    Var(String),
    Field(Box<Expr>, String),
    Call { callee: String, args: Vec<Arg> },
    Binary(BinOp, Box<Expr>, Box<Expr>),
    Lambda(Vec<Stmt>),
    /// `c.go(task: fn() {...})`
    Go { crew: String, task: Box<Expr> },
    /// `Shape.Rect(w: 3, h: 4)`
    EnumCtor { en: String, variant: String, args: Vec<Arg> },
    Match { scrut: Box<Expr>, arms: Vec<Arm> },
}

/// `Rect(w, h) => expr`: binders are positional.
#[derive(Clone, Debug)]
pub struct Arm { pub variant: String, pub binders: Vec<String>, pub body: Expr, pub line: u32 }

#[derive(Clone, Debug)]
pub struct Stmt { pub kind: StmtKind, pub line: u32 }

#[derive(Clone, Debug)]
pub enum StmtKind {
    Let { name: String, mutable: bool, ann: Option<Ty>, init: Expr },
    Assign { target: Expr, add: bool, value: Expr },
    If { cond: Expr, then: Vec<Stmt>, els: Option<Vec<Stmt>> },
    While { cond: Expr, body: Vec<Stmt> },
    Return(Option<Expr>),
    Crew { name: String, body: Vec<Stmt> },
    Expr(Expr),
}

#[derive(Clone, Debug)]
pub struct TypeDecl { pub name: String, pub fields: Vec<(String, Ty)>, pub drop: Option<Vec<Stmt>>, pub line: u32 }

#[derive(Clone, Debug)]
pub struct FnDecl { pub name: String, pub params: Vec<(String, Ty)>, pub ret: Ty, pub body: Vec<Stmt>, pub line: u32 }

#[derive(Clone, Debug)]
pub struct Variant { pub name: String, pub fields: Vec<(String, Ty)> }

#[derive(Clone, Debug)]
pub struct EnumDecl { pub name: String, pub variants: Vec<Variant>, pub line: u32 }

#[derive(Clone, Debug, Default)]
pub struct Program { pub types: Vec<TypeDecl>, pub enums: Vec<EnumDecl>, pub fns: Vec<FnDecl> }
