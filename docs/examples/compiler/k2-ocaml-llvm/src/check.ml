(* Checker: names, labels, types (Int, Str, Bool, structs). Fills expr.ty. *)
open Ast
exception Error of int * string

let fail line fmt = Printf.ksprintf (fun s -> raise (Error (line, s))) fmt
let show = function
  | TInt -> "Int" | TStr -> "Str" | TBool -> "Bool" | TUnit -> "()" | TNamed n -> n

type genv = { types : (string, tydecl) Hashtbl.t; fns : (string, fndecl) Hashtbl.t }
type fenv = { g : genv; mutable vars : (string * (ty * bool)) list; ret : ty }

let rec expr fe (e : expr) : ty =
  let t =
    match e.e with
    | Int _ -> TInt
    | Interp parts ->
      List.iter (function
          | Lit _ -> ()
          | Hole h ->
            (match expr fe h with
             | TInt | TStr -> ()
             | t -> fail h.line "cannot interpolate a %s" (show t))) parts;
      TStr
    | Var x ->
      (match List.assoc_opt x fe.vars with
       | Some (t, _) -> t
       | None -> fail e.line "unknown name '%s'" x)
    | Field (b, f) ->
      (match expr fe b with
       | TNamed n ->
         (match List.assoc_opt f (Hashtbl.find fe.g.types n).fields with
          | Some t -> t
          | None -> fail e.line "%s has no field '%s'" n f)
       | t -> fail e.line "%s has no fields" (show t))
    | Bin (op, a, b) ->
      let ta = expr fe a and tb = expr fe b in
      if ta <> TInt || tb <> TInt then fail e.line "operator %s needs Int operands" op;
      if op = "<" || op = ">" || op = "==" then TBool else TInt
    | Lambda _ -> fail e.line "a lambda may only be the argument of expect_trap"
    | Call (name, args) -> call fe e name args
  in
  e.ty <- t;
  t

and match_args fe line what params (args : arg list) =
  if List.length params <> List.length args then
    fail line "%s takes (%s)" what (String.concat ", " (List.map fst params));
  List.iter2 (fun (pn, pt) (a : arg) ->
      if a.label <> pn then fail line "%s: expected label '%s', found '%s'" what pn a.label;
      let t = expr fe a.value in
      if t <> pt then fail a.value.line "%s: '%s' needs %s, got %s" what pn (show pt) (show t))
    params args

and call fe e name args =
  match name with
  | "print" | "trap" -> match_args fe e.line name [ ("text", TStr) ] args; TUnit
  | "expect_trap" ->
    (match args with
     | [ { label = "action"; value = ({ e = Lambda body; _ } as l) } ] ->
       let fe' = { g = fe.g; vars = []; ret = TUnit } in   (* capture-free: empty env *)
       block fe' body;
       l.ty <- TUnit
     | _ -> fail e.line "expect_trap takes (action: fn() { ... })");
    TUnit
  | _ ->
    (match Hashtbl.find_opt fe.g.fns name, Hashtbl.find_opt fe.g.types name with
     | Some f, _ -> match_args fe e.line name f.params args; f.ret
     | None, Some d -> match_args fe e.line name d.fields args; TNamed name
     | None, None -> fail e.line "unknown function '%s'" name)

and block fe stmts =
  let saved = fe.vars in
  List.iter (stmt fe) stmts;
  fe.vars <- saved

and stmt fe (s : stmt) =
  match s.s with
  | Let (n, mut, init) ->
    if List.mem_assoc n fe.vars then fail s.sline "'%s' is already defined (no shadowing)" n;
    let t = expr fe init in
    if t = TUnit then fail s.sline "cannot bind a value of type ()";
    fe.vars <- (n, (t, mut)) :: fe.vars
  | Assign (op, n, v) ->
    (match List.assoc_opt n fe.vars with
     | None -> fail s.sline "unknown name '%s'" n
     | Some (_, false) -> fail s.sline "'%s' is not a var" n
     | Some (t, true) ->
       let tv = expr fe v in
       if tv <> t || (op = "+=" && t <> TInt) then fail s.sline "bad assignment to '%s'" n)
  | If (c, a, b) ->
    if expr fe c <> TBool then fail c.line "condition must be Bool";
    block fe a; block fe b
  | While (c, b) ->
    if expr fe c <> TBool then fail c.line "condition must be Bool";
    block fe b
  | Return None -> if fe.ret <> TUnit then fail s.sline "missing return value"
  | Return (Some v) ->
    if expr fe v <> fe.ret then fail s.sline "returns %s, expected %s" (show (expr fe v)) (show fe.ret)
  | Expr ({ e = Call _; _ } as c) -> ignore (expr fe c)
  | Expr e -> fail e.line "unused value"

let last_returns = function [] -> false | l -> (List.nth l (List.length l - 1)).s |> (function Return _ -> true | _ -> false)

let program (p : program) =
  let g = { types = Hashtbl.create 8; fns = Hashtbl.create 8 } in
  List.iter (fun (d : tydecl) ->
      if Hashtbl.mem g.types d.tname then fail d.tline "type '%s' defined twice" d.tname;
      List.iter (fun (_, t) -> if (match t with TNamed _ -> true | _ -> false) then
                    fail d.tline "struct-valued fields are outside the spike subset") d.fields;
      Hashtbl.add g.types d.tname d) p.types;
  List.iter (fun (f : fndecl) ->
      if Hashtbl.mem g.fns f.fname then fail f.fline "fn '%s' defined twice" f.fname;
      (match f.ret with TNamed _ -> fail f.fline "struct return values are outside the spike subset" | _ -> ());
      Hashtbl.add g.fns f.fname f) p.fns;
  (match Hashtbl.find_opt g.fns "main" with
   | Some { params = []; ret = TUnit; _ } -> ()
   | _ -> fail 1 "need 'fn main()'");
  List.iter (fun (d : tydecl) ->
      match d.drop with
      | None -> ()
      | Some body -> block { g; vars = [ ("self", (TNamed d.tname, true)) ]; ret = TUnit } body) p.types;
  List.iter (fun (f : fndecl) ->
      let fe = { g; vars = List.map (fun (n, t) -> (n, (t, false))) f.params; ret = f.ret } in
      block fe f.body;
      if f.ret <> TUnit && not (last_returns f.body) then fail f.fline "fn '%s' must end with return" f.fname) p.fns;
  g
