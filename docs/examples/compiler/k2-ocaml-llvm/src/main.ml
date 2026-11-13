(* p3c driver: parse, check, lower, emit LLVM IR, then call clang. *)
let read_file p = In_channel.with_open_bin p In_channel.input_all
let run args =
  let cmd = Filename.quote_command "clang" args in
  if Sys.command cmd <> 0 then (prerr_endline ("p3c: failed: " ^ cmd); exit 2)

let () =
  let os = ref "linux" and cov = ref false and rt = ref "runtime.c" and out = ref "a.out" and src = ref "" in
  Arg.parse
    [ ("--os", Arg.Set_string os, "linux|macos|windows"); ("--coverage", Arg.Set cov, "per-line coverage counters");
      ("--runtime", Arg.Set_string rt, "runtime.c"); ("-o", Arg.Set_string out, "output executable") ]
    (fun s -> src := s) "p3c [--os o] [--coverage] [--runtime runtime.c] -o exe src.p3";
  if !src = "" then (prerr_endline "p3c: no input"; exit 2);
  let win = !os = "windows" in
  let exe = if win && not (Filename.check_suffix !out ".exe") then !out ^ ".exe" else !out in
  let base = Filename.remove_extension exe in
  let ll = base ^ ".ll" and obj = base ^ (if win then ".obj" else ".o") and rtobj = base ^ ".rt" ^ (if win then ".obj" else ".o") in
  let abs = if Filename.is_relative !src then Filename.concat (Sys.getcwd ()) !src else !src in
  let ir =
    try
      let prog = Parser.program (read_file !src) in
      ignore (Check.program prog);
      let m = Lower.program ~coverage:!cov prog in
      Emit.module_ ~os:!os ~coverage:!cov ~covout:(base ^ ".lcov") ~srcname:(Filename.basename !src)
        ~srcdir:(Filename.dirname abs) m
    with
    | Lexer.Error (l, m) | Parser.Error (l, m) | Check.Error (l, m) ->
      Printf.eprintf "%s:%d: error: %s\n" !src l m; exit 1 in
  Out_channel.with_open_bin ll (fun oc -> output_string oc ir);
  let tgt = if win then [ "--target=x86_64-pc-windows-msvc" ] else [] in
  let dbg = if win then [ "-g"; "-gcodeview" ] else [ "-g" ] in
  run ([ "-c"; "-O0"; "-Wno-override-module" ] @ tgt @ dbg @ [ ll; "-o"; obj ]);
  run ([ "-c"; "-O0" ] @ tgt @ dbg @ [ !rt; "-o"; rtobj ]);
  run ([ obj; rtobj; "-o"; exe ] @ tgt @ (if win then [ "-fuse-ld=lld"; "-g"; "-gcodeview"; "-Wl,/DEBUG" ] else []));
  if !os = "macos" then ignore (Sys.command (Filename.quote_command "dsymutil" [ exe ] ^ " 2>/dev/null"))
