(* Emission: Ir -> textual LLVM IR (LLVM 17-compatible: intrinsic dbg.declare,
   opaque pointers) plus DWARF / CodeView debug metadata. *)
open Ir
let sprintf = Printf.sprintf

let llstr s =
  let b = Buffer.create (String.length s) in
  String.iter (fun c ->
      if c >= ' ' && c <= '~' && c <> '"' && c <> '\\' then Buffer.add_char b c
      else Buffer.add_string b (sprintf "\\%02X" (Char.code c))) s;
  Buffer.contents b

let ty_s = function I64 -> "i64" | I1 -> "i1" | Ptr -> "ptr" | Agg n -> "%" ^ n | Void -> "void"
let val_s = function Reg r -> "%" ^ r | Imm n -> string_of_int n | Glob g -> "@" ^ g

(* --- metadata table --- *)
let mds : (int * string) list ref = ref []
let nmd = ref 0
let alloc () = let n = !nmd in incr nmd; n
let set n s = mds := (n, s) :: !mds
let add s = let n = alloc () in set n s; n
let memo : (string, int) Hashtbl.t = Hashtbl.create 16
let cached k f = match Hashtbl.find_opt memo k with Some n -> n | None -> let n = f () in Hashtbl.replace memo k n; n
let tuple l = add ("!{" ^ String.concat ", " (List.map (sprintf "!%d") l) ^ "}")

let file_id = ref 0
let decls : Ast.tydecl list ref = ref []

let rec ty_md (t : Ast.ty) =
  match t with
  | Ast.TInt -> cached "int" (fun () -> add {|!DIBasicType(name: "Int", size: 64, encoding: DW_ATE_signed)|})
  | Ast.TBool -> cached "bool" (fun () -> add {|!DIBasicType(name: "Bool", size: 8, encoding: DW_ATE_boolean)|})
  | Ast.TStr ->
    cached "str" (fun () ->
        let c = add {|!DIBasicType(name: "char", size: 8, encoding: DW_ATE_signed_char)|} in
        add (sprintf "!DIDerivedType(tag: DW_TAG_pointer_type, baseType: !%d, size: 64)" c))
  | Ast.TUnit -> failwith "no debug type for ()"
  | Ast.TNamed n ->
    (match Hashtbl.find_opt memo ("s" ^ n) with
     | Some i -> i
     | None ->
       let d = List.find (fun (d : Ast.tydecl) -> d.tname = n) !decls in
       let id = alloc () in
       Hashtbl.replace memo ("s" ^ n) id;
       let members = List.mapi (fun k (fname, fty) ->
           add (sprintf "!DIDerivedType(tag: DW_TAG_member, name: \"%s\", scope: !%d, file: !%d, line: %d, baseType: !%d, size: 64, offset: %d)"
                  fname id !file_id d.tline (ty_md fty) (64 * k))) d.fields in
       let el = tuple members in
       set id (sprintf "!DICompositeType(tag: DW_TAG_structure_type, name: \"%s\", file: !%d, line: %d, size: %d, elements: !%d)"
                 n !file_id d.tline (64 * List.length d.fields) el);
       id)

let ptr_md t =
  cached ("p" ^ (match t with Ast.TNamed n -> n | _ -> "?")) (fun () ->
      add (sprintf "!DIDerivedType(tag: DW_TAG_pointer_type, baseType: !%d, size: 64)" (ty_md t)))

let module_ ~os ~coverage ~covout ~srcname ~srcdir (m : modl) =
  let win = os = "windows" in
  decls := m.tydecls;
  let hdr = Buffer.create 1024 and fb = Buffer.create 8192 in
  let h fmt = Printf.bprintf hdr fmt and pr fmt = Printf.bprintf fb fmt in
  file_id := add (sprintf "!DIFile(filename: \"%s\", directory: \"%s\")" (llstr srcname) (llstr srcdir));
  let cu = add (sprintf "distinct !DICompileUnit(language: DW_LANG_C99, file: !%d, producer: \"p3c-k2\", isOptimized: false, runtimeVersion: 0, emissionKind: FullDebug)" !file_id) in
  let sub_ty = add (sprintf "!DISubroutineType(types: !%d)" (add "!{null}")) in
  let empty = add "!{}" in
  let flag1 = if win then add {|!{i32 2, !"CodeView", i32 1}|} else add {|!{i32 7, !"Dwarf Version", i32 4}|} in
  let flag2 = add {|!{i32 2, !"Debug Info Version", i32 3}|} in
  let ncov = List.length m.cov_lines in
  let cnt = ref 0 in
  let nxt () = incr cnt; !cnt in
  let pers = if win then "__CxxFrameHandler3" else "__gcc_personality_v0" in
  List.iter (fun f ->
      let sp = add (sprintf "distinct !DISubprogram(name: \"%s\", scope: !%d, file: !%d, line: %d, type: !%d, scopeLine: %d, spFlags: DISPFlagDefinition, unit: !%d, retainedNodes: !%d)"
                      f.dname !file_id !file_id f.fline sub_ty f.fline cu empty) in
      let locs = Hashtbl.create 16 in
      let loc l = match Hashtbl.find_opt locs l with
        | Some n -> n
        | None -> let n = add (sprintf "!DILocation(line: %d, column: 1, scope: !%d)" l sp) in Hashtbl.add locs l n; n in
      let pad = ref None in
      let funclet () = match !pad with Some p when win -> sprintf " [ \"funclet\"(token %%%s) ]" p | _ -> "" in
      pr "define %s @%s(%s) #0%s !dbg !%d {\n" (ty_s f.fret) f.name
        (String.concat ", " (List.map (fun (n, t) -> sprintf "%s %%%s" (ty_s t) n) f.params))
        (if f.has_eh then sprintf " personality ptr @%s" pers else "") sp;
      List.iter (fun (x : ins) ->
          let d = sprintf ", !dbg !%d" (loc x.ln) in
          match x.i with
          | Label l -> pr "%s:\n" l
          | Alloca (n, t) -> pr "  %%%s = alloca %s, align 8\n" n (ty_s t)
          | Store (t, v, a) -> pr "  store %s %s, ptr %s, align 8%s\n" (ty_s t) (val_s v) (val_s a) d
          | Load (r, t, a) -> pr "  %%%s = load %s, ptr %s, align 8%s\n" r (ty_s t) (val_s a) d
          | Gep (r, s, b, k) -> pr "  %%%s = getelementptr inbounds %%%s, ptr %s, i32 0, i32 %d%s\n" r s (val_s b) k d
          | Bin (r, op, a, b) -> pr "  %%%s = %s i64 %s, %s%s\n" r op (val_s a) (val_s b) d
          | Cmp (r, p, a, b) -> pr "  %%%s = icmp %s i64 %s, %s%s\n" r p (val_s a) (val_s b) d
          | Call c ->
            let args = String.concat ", " (List.map (fun (t, v) -> ty_s t ^ " " ^ val_s v) c.args) in
            let dst = match c.dst with Some r -> "%" ^ r ^ " = " | None -> "" in
            (match c.unwind with
             | None -> pr "  %scall %s @%s(%s)%s%s\n" dst (ty_s c.ret) c.fn args (funclet ()) d
             | Some lp ->
               let k = sprintf ".c%d" (nxt ()) in
               pr "  %sinvoke %s @%s(%s) to label %%%s unwind label %%%s%s\n" dst (ty_s c.ret) c.fn args k lp d;
               pr "%s:\n" k)
          | Br l -> pr "  br label %%%s%s\n" l d
          | CondBr (c, a, b) -> pr "  br i1 %s, label %%%s, label %%%s%s\n" (val_s c) a b d
          | Ret None -> pr "  ret void%s\n" d
          | Ret (Some (t, v)) -> pr "  ret %s %s%s\n" (ty_s t) (val_s v) d
          | Unreachable -> pr "  unreachable\n"
          | LandingPad l ->
            pad := Some (".pad." ^ l);
            if win then pr "  %%.pad.%s = cleanuppad within none []\n" l
            else pr "  %%.pad.%s = landingpad { ptr, i32 } cleanup\n" l
          | Resume l ->
            if win then pr "  cleanupret from %%.pad.%s unwind to caller\n" l
            else pr "  resume { ptr, i32 } %%.pad.%s\n" l;
            pad := None
          | Dbg v ->
            let t = if v.byref then ptr_md v.vty else ty_md v.vty in
            let lv = add (sprintf "!DILocalVariable(name: \"%s\", %sscope: !%d, file: !%d, line: %d, type: !%d)"
                            v.vname (if v.arg > 0 then sprintf "arg: %d, " v.arg else "") sp !file_id x.ln t) in
            pr "  call void @llvm.dbg.declare(metadata ptr %%%s, metadata !%d, metadata !DIExpression())%s\n" v.slot lv d
          | Cov idx ->
            let k = nxt () in
            pr "  %%.cg%d = getelementptr inbounds [%d x i64], ptr @__p3_cov, i64 0, i64 %d\n" k ncov idx;
            pr "  %%.cv%d = load i64, ptr %%.cg%d, align 8\n  %%.ci%d = add i64 %%.cv%d, 1\n" k k k k;
            pr "  store i64 %%.ci%d, ptr %%.cg%d, align 8\n" k k) f.body;
      pr "}\n\n") m.funcs;
  (* module header *)
  h "; generated by p3c (K2: OCaml + LLVM IR)\nsource_filename = \"%s\"\n" (llstr srcname);
  if win then h "target triple = \"x86_64-pc-windows-msvc\"\n";
  h "\n";
  List.iter (fun (d : Ast.tydecl) ->
      h "%%%s = type { %s }\n" d.tname
        (String.concat ", " (List.map (fun (_, t) -> match t with Ast.TInt -> "i64" | _ -> "ptr") d.fields))) m.tydecls;
  h "\n";
  let str_const name s = h "@%s = private unnamed_addr constant [%d x i8] c\"%s\\00\"\n" name (String.length s + 1) (llstr s) in
  List.iter (fun (n, s) -> str_const n s) m.strs;
  str_const ".covout" covout; str_const ".covsrc" srcname;
  if coverage then begin
    h "@__p3_cov = internal global [%d x i64] zeroinitializer\n" ncov;
    h "@__p3_cov_lines = internal constant [%d x i32] [%s]\n" ncov
      (String.concat ", " (List.map (sprintf "i32 %d") m.cov_lines));
    h "@__p3_cov_fns = internal constant [%d x { ptr, i32, i32 }] [%s]\n" (List.length m.cov_fns)
      (String.concat ", " (List.map (fun (n, l, i) -> sprintf "{ ptr, i32, i32 } { ptr @%s, i32 %d, i32 %d }" n l i) m.cov_fns))
  end;
  h "\ndeclare void @llvm.dbg.declare(metadata, metadata, metadata)\n";
  h "declare void @p3_print(ptr) nounwind\ndeclare ptr @p3_itoa(i64) nounwind\ndeclare ptr @p3_concat(ptr, ptr) nounwind\n";
  h "declare void @p3_trap(ptr)\ndeclare void @p3_expect_trap(ptr)\n";
  h "declare void @p3_cov_dump(ptr, ptr, i64, ptr, i64, ptr, ptr)\n";
  h "declare i32 @%s(...)\n\n" pers;
  pr "define i32 @main() {\n  call void @p3.main()\n";
  if coverage then
    pr "  call void @p3_cov_dump(ptr @__p3_cov_lines, ptr @__p3_cov, i64 %d, ptr @__p3_cov_fns, i64 %d, ptr @.covout, ptr @.covsrc)\n"
      ncov (List.length m.cov_fns);
  pr "  ret i32 0\n}\n\n";
  pr "attributes #0 = { noinline optnone uwtable \"frame-pointer\"=\"all\" }\n\n";
  let md = Buffer.create 4096 in
  List.iter (fun (n, s) -> Printf.bprintf md "!%d = %s\n" n s) (List.sort compare !mds);
  Printf.bprintf md "!llvm.dbg.cu = !{!%d}\n!llvm.module.flags = !{!%d, !%d}\n" cu flag1 flag2;
  Buffer.contents hdr ^ Buffer.contents fb ^ Buffer.contents md
