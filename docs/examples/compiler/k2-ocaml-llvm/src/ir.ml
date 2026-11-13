(* A small LLVM-shaped IR: what lowering produces and emission prints. *)
type ty = I64 | I1 | Ptr | Agg of string | Void
type v = Reg of string | Imm of int | Glob of string
type call = { dst : string option; ret : ty; fn : string; args : (ty * v) list; unwind : string option }
type dbg = { slot : string; vname : string; vty : Ast.ty; byref : bool; arg : int }
type instr =
  | Label of string
  | Alloca of string * ty
  | Store of ty * v * v                 (* type, value, address *)
  | Load of string * ty * v
  | Gep of string * string * v * int    (* dst, struct, base, field *)
  | Bin of string * string * v * v      (* dst, add|sub|mul, a, b *)
  | Cmp of string * string * v * v      (* dst, slt|sgt|eq, a, b *)
  | Call of call                        (* unwind = Some pad => invoke *)
  | Br of string
  | CondBr of v * string * string
  | Ret of (ty * v) option
  | LandingPad of string                (* start of a cleanup pad *)
  | Resume of string                    (* end of that pad: continue unwinding *)
  | Dbg of dbg
  | Cov of int
  | Unreachable
type ins = { i : instr; ln : int }
type func = { name : string; dname : string; params : (string * ty) list; fret : ty;
              body : ins list; fline : int; has_eh : bool }
type modl = { tydecls : Ast.tydecl list; strs : (string * string) list; funcs : func list;
              cov_lines : int list; cov_fns : (string * int * int) list }
