(* AST for the p3 spike subset. Types are filled in by the checker. *)
type ty = TInt | TStr | TBool | TUnit | TNamed of string

type expr = { e : edesc; line : int; mutable ty : ty }
and edesc =
  | Int of int
  | Interp of part list
  | Var of string
  | Field of expr * string
  | Call of string * arg list
  | Bin of string * expr * expr
  | Lambda of stmt list
and part = Lit of string | Hole of expr
and arg = { label : string; value : expr }
and stmt = { s : sdesc; sline : int }
and sdesc =
  | Let of string * bool * expr          (* name, is_var, init *)
  | Assign of string * string * expr     (* op ("=" or "+="), name, value *)
  | If of expr * stmt list * stmt list
  | While of expr * stmt list
  | Return of expr option
  | Expr of expr

type tydecl = { tname : string; fields : (string * ty) list; drop : stmt list option; tline : int; dline : int }
type fndecl = { fname : string; params : (string * ty) list; ret : ty; body : stmt list; fline : int }
type program = { types : tydecl list; fns : fndecl list }
