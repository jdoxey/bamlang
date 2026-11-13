(* Lowering: typed AST -> Ir. Decides drop scheduling and where calls become
   invokes (any call made while a droppable local is live). *)
open Ast
module I = Ir

type local = { slot : string; lty : ty; byref : bool }
type fs = {
  mutable code : I.ins list; mutable pads : I.ins list; mutable allocas : I.ins list;
  mutable vars : (string * local) list;
  mutable live : (string * string) list;      (* (slot, type) with a drop, newest first *)
  mutable cur : int; mutable term : bool;
  padtbl : (string, string) Hashtbl.t; fret : ty;
}

let types : (string, tydecl) Hashtbl.t = Hashtbl.create 8
let uid = ref 0
let fresh p = incr uid; p ^ string_of_int !uid
let str_tbl : (string, string) Hashtbl.t = Hashtbl.create 16
let strs = ref []
let strlit s =
  match Hashtbl.find_opt str_tbl s with
  | Some n -> n
  | None -> let n = fresh ".str." in Hashtbl.add str_tbl s n; strs := (n, s) :: !strs; n
let funcs : I.func list ref = ref []
let cov_on = ref false
let cov_tbl : (int, int) Hashtbl.t = Hashtbl.create 16
let cov_list = ref []
let cov_fns = ref []

let irty = function
  | TInt -> I.I64 | TStr -> I.Ptr | TBool -> I.I1 | TNamed n -> I.Agg n | TUnit -> I.Void
let drop_fn tn = "p3." ^ tn ^ ".drop"
let has_drop tn = (Hashtbl.find types tn).drop <> None

let push fs i = fs.code <- { I.i; ln = fs.cur } :: fs.code
let emit fs i =
  (match i with
   | I.Label _ -> fs.term <- false
   | _ -> if fs.term then (push fs (I.Label (fresh "dead")); fs.term <- false));
  push fs i;
  (match i with I.Br _ | I.CondBr _ | I.Ret _ | I.Unreachable -> fs.term <- true | _ -> ())
let alloca fs slot t = fs.allocas <- { I.i = I.Alloca (slot, t); ln = fs.cur } :: fs.allocas

let cov fs line =
  if !cov_on then begin
    let idx = match Hashtbl.find_opt cov_tbl line with
      | Some i -> i
      | None -> let i = List.length !cov_list in
        Hashtbl.add cov_tbl line i; cov_list := line :: !cov_list; i in
    emit fs (I.Cov idx); idx
  end else 0

(* One cleanup pad per distinct set of live droppables: run drops innermost
   first, then keep unwinding. *)
let pad fs =
  let key = String.concat "," (List.map fst fs.live) in
  match Hashtbl.find_opt fs.padtbl key with
  | Some l -> l
  | None ->
    let l = fresh "lpad" in
    Hashtbl.add fs.padtbl key l;
    let add i = fs.pads <- { I.i; ln = fs.cur } :: fs.pads in
    add (I.Label l); add (I.LandingPad l);
    List.iter (fun (slot, tn) ->
        add (I.Call { dst = None; ret = I.Void; fn = drop_fn tn; args = [ (I.Ptr, I.Reg slot) ]; unwind = None }))
      fs.live;
    add (I.Resume l);
    l

let call fs ?(unwind = false) ?dst ret fn args =
  let unwind = if unwind && fs.live <> [] then Some (pad fs) else None in
  emit fs (I.Call { dst; ret; fn; args; unwind })

let drops fs k =       (* drop the k newest live locals, innermost first *)
  List.iteri (fun n (slot, tn) ->
      if n < k then call fs I.Void (drop_fn tn) [ (I.Ptr, I.Reg slot) ]) fs.live

let rec drop_n n l = if n = 0 then l else match l with [] -> [] | _ :: r -> drop_n (n - 1) r

let rec expr fs (e : expr) : I.v =
  match e.e with
  | Int n -> I.Imm n
  | Interp parts ->
    let vs = List.map (function
        | Lit s -> I.Glob (strlit s)
        | Hole h ->
          let v = expr fs h in
          if h.ty = TInt then (let r = fresh "t" in call fs ~dst:r I.Ptr "p3_itoa" [ (I.I64, v) ]; I.Reg r) else v) parts in
    (match vs with
     | [] -> I.Glob (strlit "")
     | v :: rest ->
       List.fold_left (fun acc v ->
           let r = fresh "t" in call fs ~dst:r I.Ptr "p3_concat" [ (I.Ptr, acc); (I.Ptr, v) ]; I.Reg r) v rest)
  | Var x ->
    let l = List.assoc x fs.vars in
    (match l.lty with
     | TNamed _ when not l.byref -> I.Reg l.slot
     | t ->
       let r = fresh "t" in
       emit fs (I.Load (r, (if l.byref then I.Ptr else irty t), I.Reg l.slot)); I.Reg r)
  | Field (b, f) ->
    let base = expr fs b in
    let tn = (match b.ty with TNamed n -> n | _ -> assert false) in
    let d = Hashtbl.find types tn in
    let rec idx k = function (n, t) :: r -> if n = f then (k, t) else idx (k + 1) r | [] -> assert false in
    let k, ft = idx 0 d.fields in
    let p = fresh "f" and r = fresh "t" in
    emit fs (I.Gep (p, tn, base, k));
    emit fs (I.Load (r, irty ft, I.Reg p)); I.Reg r
  | Bin (op, a, b) ->
    let va = expr fs a in
    let vb = expr fs b in
    let r = fresh "t" in
    (match op with
     | "+" -> emit fs (I.Bin (r, "add", va, vb)) | "-" -> emit fs (I.Bin (r, "sub", va, vb))
     | "*" -> emit fs (I.Bin (r, "mul", va, vb)) | "<" -> emit fs (I.Cmp (r, "slt", va, vb))
     | ">" -> emit fs (I.Cmp (r, "sgt", va, vb)) | _ -> emit fs (I.Cmp (r, "eq", va, vb)));
    I.Reg r
  | Lambda _ -> assert false
  | Call (name, args) ->
    (match name with
     | "print" -> let v = expr fs (List.hd args).value in call fs I.Void "p3_print" [ (I.Ptr, v) ]; I.Imm 0
     | "trap" -> let v = expr fs (List.hd args).value in call fs ~unwind:true I.Void "p3_trap" [ (I.Ptr, v) ]; I.Imm 0
     | "expect_trap" ->
       (match (List.hd args).value.e with
        | Lambda body ->
          let ln = fresh "p3.lambda." in
          build ~name:ln ~dname:"lambda" ~line:e.line ~params:[] ~ret:TUnit ~body ~entry_cov:false;
          call fs I.Void "p3_expect_trap" [ (I.Ptr, I.Glob ln) ]; I.Imm 0
        | _ -> assert false)
     | _ when Hashtbl.mem types name ->
       let slot = fresh "tmp." in
       alloca fs slot (I.Agg name);
       ctor fs slot name args; I.Reg slot
     | _ ->
       let vs = List.map (fun (a : arg) ->
           let v = expr fs a.value in
           match a.value.ty with
           | TNamed n -> let t = fresh "t" in emit fs (I.Load (t, I.Agg n, v)); (I.Agg n, I.Reg t)
           | t -> (irty t, v)) args in
       if e.ty = TUnit then (call fs ~unwind:true I.Void ("p3." ^ name) vs; I.Imm 0)
       else (let r = fresh "t" in call fs ~unwind:true ~dst:r (irty e.ty) ("p3." ^ name) vs; I.Reg r))

and ctor fs slot tn args =
  List.iteri (fun k (a : arg) ->
      let v = expr fs a.value in
      let p = fresh "f" in
      emit fs (I.Gep (p, tn, I.Reg slot, k));
      emit fs (I.Store (irty a.value.ty, v, I.Reg p))) args

and block fs stmts =
  let vars0 = fs.vars and live0 = List.length fs.live in
  List.iter (stmt fs) stmts;
  let k = List.length fs.live - live0 in
  if not fs.term then drops fs k;
  fs.live <- drop_n k fs.live;
  fs.vars <- vars0

and stmt fs (s : stmt) =
  fs.cur <- s.sline;
  match s.s with
  | Let (n, _, init) ->
    ignore (cov fs s.sline);
    let slot = fresh (n ^ ".") in
    alloca fs slot (irty init.ty);
    (match init.e, init.ty with
     | Call (cn, args), TNamed tn when Hashtbl.mem types cn -> ctor fs slot tn args
     | _, TNamed tn ->
       let v = expr fs init in
       let t = fresh "t" in
       emit fs (I.Load (t, I.Agg tn, v)); emit fs (I.Store (I.Agg tn, I.Reg t, I.Reg slot))
     | _ -> let v = expr fs init in emit fs (I.Store (irty init.ty, v, I.Reg slot)));
    emit fs (I.Dbg { slot; vname = n; vty = init.ty; byref = false; arg = 0 });
    fs.vars <- (n, { slot; lty = init.ty; byref = false }) :: fs.vars;
    (match init.ty with
     | TNamed tn when has_drop tn -> fs.live <- (slot, tn) :: fs.live
     | _ -> ())
  | Assign (op, n, v) ->
    ignore (cov fs s.sline);
    let l = List.assoc n fs.vars in
    let nv = expr fs v in
    if op = "+=" then begin
      let cur = fresh "t" and sum = fresh "t" in
      emit fs (I.Load (cur, I.I64, I.Reg l.slot));
      emit fs (I.Bin (sum, "add", I.Reg cur, nv));
      emit fs (I.Store (I.I64, I.Reg sum, I.Reg l.slot))
    end else emit fs (I.Store (irty l.lty, nv, I.Reg l.slot))
  | If (c, a, b) ->
    ignore (cov fs s.sline);
    let cv = expr fs c in
    let lt = fresh "then" and le = fresh "else" and lend = fresh "endif" in
    emit fs (I.CondBr (cv, lt, if b = [] then lend else le));
    emit fs (I.Label lt); block fs a;
    if not fs.term then emit fs (I.Br lend);
    if b <> [] then begin
      emit fs (I.Label le); block fs b;
      if not fs.term then emit fs (I.Br lend)
    end;
    emit fs (I.Label lend)
  | While (c, body) ->
    let lc = fresh "wcond" and lb = fresh "wbody" and le = fresh "wend" in
    emit fs (I.Br lc);
    emit fs (I.Label lc);
    ignore (cov fs s.sline);
    let cv = expr fs c in
    emit fs (I.CondBr (cv, lb, le));
    emit fs (I.Label lb); block fs body;
    fs.cur <- s.sline;
    if not fs.term then emit fs (I.Br lc);
    emit fs (I.Label le)
  | Return eo ->
    ignore (cov fs s.sline);
    let v = Option.map (expr fs) eo in
    drops fs (List.length fs.live);
    emit fs (I.Ret (match v with None -> None | Some v -> Some (irty fs.fret, v)))
  | Expr e -> ignore (cov fs s.sline); ignore (expr fs e)

and build ~name ~dname ~line ~params ~ret ~body ~entry_cov =
  (* params: (name, type, by_reference) *)
  let fs = { code = []; pads = []; allocas = []; vars = []; live = []; cur = line; term = false;
             padtbl = Hashtbl.create 4; fret = ret } in
  push fs (I.Label "entry");
  if entry_cov then (let idx = cov fs line in cov_fns := (dname, line, idx) :: !cov_fns);
  let iparams = List.mapi (fun k (pn, pt, byref) ->
      let reg = Printf.sprintf "a%d" k and slot = fresh (pn ^ ".") in
      let lt = if byref then I.Ptr else irty pt in
      alloca fs slot lt;
      emit fs (I.Store (lt, I.Reg reg, I.Reg slot));
      emit fs (I.Dbg { slot; vname = pn; vty = pt; byref; arg = k + 1 });
      fs.vars <- (pn, { slot; lty = pt; byref }) :: fs.vars;
      (reg, lt)) params in
  block fs body;
  if not fs.term then emit fs (if ret = TUnit then I.Ret None else I.Unreachable);
  let body =
    match List.rev fs.code with
    | entry :: rest -> entry :: (List.rev fs.allocas @ rest @ List.rev fs.pads)
    | [] -> [] in
  funcs := { I.name; dname; params = iparams; fret = irty ret; body; fline = line;
             has_eh = fs.pads <> [] } :: !funcs

let program ~coverage (p : program) : I.modl =
  cov_on := coverage;
  List.iter (fun (d : tydecl) -> Hashtbl.replace types d.tname d) p.types;
  List.iter (fun (d : tydecl) ->
      match d.drop with
      | Some body ->
        build ~name:(drop_fn d.tname) ~dname:(d.tname ^ ".drop") ~line:d.dline ~params:[ ("self", TNamed d.tname, true) ]
          ~ret:TUnit ~body ~entry_cov:true
      | None -> ()) p.types;
  List.iter (fun (f : fndecl) ->
      build ~name:("p3." ^ f.fname) ~dname:f.fname ~line:f.fline
        ~params:(List.map (fun (n, t) -> (n, t, false)) f.params) ~ret:f.ret ~body:f.body ~entry_cov:true) p.fns;
  let cov_fns = List.rev_map (fun (n, l, i) -> (strlit n, l, i)) !cov_fns in
  { I.tydecls = p.types; strs = List.rev !strs; funcs = List.rev !funcs;
    cov_lines = List.rev !cov_list; cov_fns }
