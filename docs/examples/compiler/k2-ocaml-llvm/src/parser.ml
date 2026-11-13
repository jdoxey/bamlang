(* Recursive-descent parser: tokens -> Ast.program. *)
open Ast
open Lexer
exception Error of int * string

type st = { toks : Lexer.t array; mutable p : int }

let peek st = st.toks.(st.p)
let tk st = (peek st).tk
let tk2 st = if st.p + 1 < Array.length st.toks then st.toks.(st.p + 1).tk else EOF
let adv st = if st.p < Array.length st.toks - 1 then st.p <- st.p + 1
let err st m = raise (Error ((peek st).ln, m))
let is_sym st s = (tk st = SYM s)
let expect st s = if is_sym st s then adv st else err st (Printf.sprintf "expected '%s'" s)
let skip_nl st = while tk st = NL do adv st done
let skip_sep st = while tk st = NL || tk st = SYM "," do adv st done
let ident st = match tk st with ID s -> adv st; s | _ -> err st "expected a name"
let ty st = match ident st with "Int" -> TInt | "Str" -> TStr | s -> TNamed s
let mk e line = { e; line; ty = TUnit }

let rec expr st = compare st

and compare st =
  let l = additive st in
  match tk st with
  | SYM (("<" | ">" | "==") as op) ->
    let ln = (peek st).ln in
    adv st;
    let r = additive st in
    (match tk st with SYM ("<" | ">" | "==") -> err st "comparisons don't chain" | _ -> ());
    mk (Bin (op, l, r)) ln
  | _ -> l

and additive st =
  let l = ref (term st) and go = ref true in
  while !go do
    match tk st with
    | SYM (("+" | "-") as op) ->
      let ln = (peek st).ln in
      adv st;
      let r = term st in
      l := mk (Bin (op, !l, r)) ln
    | _ -> go := false
  done;
  !l

and term st =
  let l = ref (postfix st) and go = ref true in
  while !go do
    match tk st with
    | SYM "*" ->
      let ln = (peek st).ln in
      adv st;
      let r = postfix st in
      l := mk (Bin ("*", !l, r)) ln
    | _ -> go := false
  done;
  !l

and postfix st =
  let e = ref (primary st) in
  while is_sym st "." do
    let ln = (peek st).ln in
    adv st;
    e := mk (Field (!e, ident st)) ln
  done;
  !e

and primary st =
  let ln = (peek st).ln in
  match tk st with
  | INT n -> adv st; mk (Int n) ln
  | STR segs ->
    adv st;
    let parts = List.map (function
        | SLit s -> Lit s
        | SCode c ->
          let sub = { toks = Array.of_list (Lexer.tokenize ~line:ln c); p = 0 } in
          let e = expr sub in
          if tk sub <> EOF then err sub "unexpected text in {...}";
          Hole e) segs in
    mk (Interp parts) ln
  | ID name ->
    adv st;
    if is_sym st "(" then (adv st; mk (Call (name, args st)) ln) else mk (Var name) ln
  | SYM "(" -> adv st; let e = expr st in expect st ")"; e
  | KW "fn" ->
    adv st; expect st "("; expect st ")";
    mk (Lambda (block st)) ln
  | _ -> err st "expected an expression"

and args st =
  let acc = ref [] in
  while not (is_sym st ")") do
    (match tk st, tk2 st with
     | ID l, SYM ":" -> adv st; adv st; acc := { label = l; value = expr st } :: !acc
     | ID l, (SYM "," | SYM ")") -> let ln = (peek st).ln in adv st; acc := { label = l; value = mk (Var l) ln } :: !acc
     | _ -> err st "every argument needs a label: write name: value");
    if is_sym st "," then adv st else if not (is_sym st ")") then err st "expected ',' or ')'"
  done;
  adv st;
  List.rev !acc

and block st =
  expect st "{";
  skip_nl st;
  let acc = ref [] in
  while not (is_sym st "}") do
    if tk st = EOF then err st "unclosed '{'";
    acc := stmt st :: !acc;
    (match tk st with
     | NL -> skip_nl st
     | SYM "}" -> ()
     | _ -> err st "expected a newline after statement")
  done;
  adv st;
  List.rev !acc

and stmt st =
  let ln = (peek st).ln in
  let mks s = { s; sline = ln } in
  match tk st with
  | KW (("let" | "var") as k) ->
    adv st;
    let n = ident st in
    expect st "=";
    mks (Let (n, k = "var", expr st))
  | KW "if" -> ifstmt st
  | KW "while" ->
    adv st;
    let c = expr st in
    mks (While (c, block st))
  | KW "return" ->
    adv st;
    (match tk st with
     | NL | EOF | SYM "}" -> mks (Return None)
     | _ -> mks (Return (Some (expr st))))
  | ID n when tk2 st = SYM "=" || tk2 st = SYM "+=" ->
    adv st;
    let op = (match tk st with SYM o -> o | _ -> "=") in
    adv st;
    mks (Assign (op, n, expr st))
  | _ -> mks (Expr (expr st))

and ifstmt st =
  let ln = (peek st).ln in
  adv st;
  let c = expr st in
  let t = block st in
  let e =
    if tk st = KW "else" then begin
      adv st;
      if tk st = KW "if" then [ ifstmt st ] else block st
    end else [] in
  { s = If (c, t, e); sline = ln }

let tydecl st =
  let ln = (peek st).ln in
  adv st;
  let name = ident st in
  expect st "{";
  skip_sep st;
  let fields = ref [] and drop = ref None and dline = ref ln in
  while not (is_sym st "}") do
    (match tk st, tk2 st with
     | ID "drop", SYM "(" ->
       dline := (peek st).ln;
       adv st; adv st;
       ignore (ident st); ignore (ident st);   (* mut self *)
       expect st ")";
       drop := Some (block st)
     | ID _, _ ->
       let f = ident st in
       expect st ":";
       fields := (f, ty st) :: !fields
     | _ -> err st "expected a field or drop");
    skip_sep st
  done;
  adv st;
  { tname = name; fields = List.rev !fields; drop = !drop; tline = ln; dline = !dline }

let fndecl st =
  let ln = (peek st).ln in
  adv st;
  let name = ident st in
  expect st "(";
  let ps = ref [] in
  while not (is_sym st ")") do
    let n = ident st in
    expect st ":";
    ps := (n, ty st) :: !ps;
    if is_sym st "," then adv st
  done;
  adv st;
  let ret = if is_sym st "->" then (adv st; ty st) else TUnit in
  { fname = name; params = List.rev !ps; ret; body = block st; fline = ln }

let program src =
  let st = { toks = Array.of_list (Lexer.tokenize src); p = 0 } in
  let types = ref [] and fns = ref [] in
  skip_nl st;
  while tk st <> EOF do
    (match tk st with
     | KW "type" -> types := tydecl st :: !types
     | KW "fn" -> fns := fndecl st :: !fns
     | _ -> err st "expected 'type' or 'fn'");
    skip_nl st
  done;
  { types = List.rev !types; fns = List.rev !fns }
