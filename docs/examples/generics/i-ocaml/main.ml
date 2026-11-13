(* Option I in OCaml: no type annotations on any user function; records concrete;
   no user-declared parameterised types. Everything below is inferred by HM. *)

(* ---- built-in set (stands in for builtins.go) ---- *)
let rec min_by lt = function
  | [] -> None
  | x :: rest ->
    Some (List.fold_left (fun m y -> if lt y m then y else m) x rest)
let max_by lt xs = min_by (fun a b -> lt b a) xs
let group_by key xs =
  let t = Hashtbl.create 8 in
  List.iter (fun x ->
    let k = key x in
    let old = Option.value (Hashtbl.find_opt t k) ~default:[] in
    Hashtbl.replace t k (old @ [x])) xs;
  t
let sorted_keys t = List.sort compare (Hashtbl.fold (fun k _ acc -> k :: acc) t [])
let show_list f xs = "[" ^ String.concat " " (List.map f xs) ^ "]"

(* ---- Part 1 ---- *)
(* Labels are prefixed: without annotations, a shared label like `name` would
   resolve to the last-declared record and break inference. *)
type employee = { e_name : string; e_dept : string; e_salary : int }

let employees = [
  { e_name = "Grace"; e_dept = "sales"; e_salary = 60000 };
  { e_name = "Bob"; e_dept = "eng"; e_salary = 70000 };
  { e_name = "Dave"; e_dept = "ops"; e_salary = 45000 };
  { e_name = "Carol"; e_dept = "eng"; e_salary = 90000 };
  { e_name = "Heidi"; e_dept = "sales"; e_salary = 40000 };
  { e_name = "Alice"; e_dept = "eng"; e_salary = 70000 };
  { e_name = "Erin"; e_dept = "ops"; e_salary = 55000 };
  { e_name = "Frank"; e_dept = "sales"; e_salary = 40000 };
]

let part1 () =
  print_endline "== Part 1: algorithms over Employee ==";
  let sorted = List.sort (fun a b ->
    compare (a.e_dept, b.e_salary, a.e_name) (b.e_dept, a.e_salary, b.e_name)) employees in
  print_endline "sorted by dept, salary desc, name:";
  List.iter (fun e -> Printf.printf "  %-5s %-6s %d\n" e.e_dept e.e_name e.e_salary) sorted;
  let by_pay a b = a.e_salary < b.e_salary in
  (match min_by by_pay employees, max_by by_pay employees with
   | Some lo, Some hi ->
     Printf.printf "min_by salary: %s %d\n" lo.e_name lo.e_salary;
     Printf.printf "max_by salary: %s %d\n" hi.e_name hi.e_salary
   | _ -> ());
  let groups = group_by (fun e -> e.e_dept) employees in
  print_endline "group_by dept:";
  List.iter (fun d ->
    let g = Hashtbl.find groups d in
    let total = List.fold_left (fun s e -> s + e.e_salary) 0 g in
    Printf.printf "  %-5s count=%d total=%d\n" d (List.length g) total) (sorted_keys groups);
  let rich = List.filter (fun e -> e.e_salary > 50000) employees in
  print_endline ("salary > 50000: " ^ show_list (fun e -> e.e_name) rich)

(* ---- Part 2 ---- *)
type user_key = { tenant : int; uid : int }
type profile = { p_name : string; p_email : string }

(* ===== the LRU, written ONCE as functions over parts of a concrete state ===== *)
let touch order k =
  order := List.filter (fun x -> x <> k) !order @ [k]

let lru_get order vals k =
  match Hashtbl.find_opt vals k with
  | Some v -> touch order k; Some v
  | None -> None

(* returns the evicted key, if any *)
let lru_put cap order vals k v =
  let evicted =
    if not (Hashtbl.mem vals k) && Hashtbl.length vals = cap then
      match !order with
      | old :: rest -> order := rest; Hashtbl.remove vals old; Some old
      | [] -> None
    else None in
  Hashtbl.replace vals k v;
  touch order k;
  evicted

(* ===== per-use concrete state: only fields, no behaviour ===== *)
type profile_cache = {
  pc_cap : int;
  pc_order : user_key list ref;
  pc_vals : (user_key, profile) Hashtbl.t;
}
type query_cache = {
  qc_cap : int;
  qc_order : string list ref;
  qc_vals : (string, int list) Hashtbl.t;
}
(* ===== end of LRU ===== *)

let part2 () =
  print_endline "== Part 2: LRU cache reused for two key/value pairs ==";
  let pc = { pc_cap = 2; pc_order = ref []; pc_vals = Hashtbl.create 4 } in
  let qc = { qc_cap = 3; qc_order = ref []; qc_vals = Hashtbl.create 4 } in
  let put_p k p =
    Printf.printf "profiles put %d/%d\n" k.tenant k.uid;
    match lru_put pc.pc_cap pc.pc_order pc.pc_vals k p with
    | Some old -> Printf.printf "profiles evict %d/%d\n" old.tenant old.uid
    | None -> () in
  let get_p k =
    match lru_get pc.pc_order pc.pc_vals k with
    | Some p -> Printf.printf "profiles get %d/%d hit %s <%s>\n" k.tenant k.uid p.p_name p.p_email
    | None -> Printf.printf "profiles get %d/%d miss\n" k.tenant k.uid in
  let put_q k v =
    Printf.printf "queries put %s\n" k;
    match lru_put qc.qc_cap qc.qc_order qc.qc_vals k v with
    | Some old -> Printf.printf "queries evict %s\n" old
    | None -> () in
  let get_q k =
    match lru_get qc.qc_order qc.qc_vals k with
    | Some v -> Printf.printf "queries get %s hit %s\n" k (show_list string_of_int v)
    | None -> Printf.printf "queries get %s miss\n" k in
  let uk t i = { tenant = t; uid = i } in
  let pf n e = { p_name = n; p_email = e } in
  put_p (uk 1 1) (pf "Ann" "ann@example.com");
  put_p (uk 1 2) (pf "Ben" "ben@example.com");
  get_p (uk 1 1);
  put_p (uk 2 1) (pf "Cy" "cy@example.com");
  get_p (uk 1 2);
  put_p (uk 1 3) (pf "Di" "di@example.com");
  get_p (uk 2 1);
  get_p (uk 1 1);
  put_q "a" [1];
  put_q "b" [2; 2];
  put_q "c" [3];
  get_q "a";
  put_q "d" [4];
  get_q "b";
  put_q "a" [1; 1];
  put_q "e" [5];
  get_q "c";
  get_q "a"

(* ---- Part 3 ---- *)
type address = { street : string; city : string }
type user = { id : int; u_name : string; addr : address option }

let users = [
  (1, { id = 1; u_name = "Ann"; addr = Some { street = "10 Main St"; city = "Springfield" } });
  (2, { id = 2; u_name = "Ben"; addr = None });
]

let find_user id = List.assoc_opt id users

(* channel = Queue under Mutex/Condition; None is the close marker *)
let make_chan () = (Queue.create (), Mutex.create (), Condition.create ())
let send (q, m, c) x =
  Mutex.lock m; Queue.push x q; Condition.signal c; Mutex.unlock m
let recv (q, m, c) =
  Mutex.lock m;
  while Queue.is_empty q do Condition.wait c m done;
  let x = Queue.pop q in
  Mutex.unlock m; x

let part3 () =
  print_endline "== Part 3: Optional pipeline across a thread ==";
  let ch = make_chan () in
  let worker = Domain.spawn (fun () ->
    let rec loop () =
      match recv ch with
      | None -> ()
      | Some (id, Some a) ->
        Printf.printf "addr for %d: %s, %s\n" id a.street a.city; loop ()
      | Some (id, None) -> Printf.printf "addr for %d: none\n" id; loop () in
    loop ()) in
  for id = 1 to 3 do
    send ch (Some (id, Option.bind (find_user id) (fun u -> u.addr)))
  done;
  send ch None;
  Domain.join worker

let () = part1 (); part2 (); part3 ()
