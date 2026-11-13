(* Lexer. Newlines are tokens, except directly inside ( ) where they are spaces. *)
type seg = SLit of string | SCode of string
type tok = INT of int | STR of seg list | ID of string | KW of string | SYM of string | NL | EOF
type t = { tk : tok; ln : int }
exception Error of int * string

let keywords = [ "type"; "fn"; "let"; "var"; "if"; "else"; "while"; "return" ]

let tokenize ?(line = 1) src =
  let n = String.length src in
  let toks = ref [] and ln = ref line and i = ref 0 and stack = ref [] in
  let add tk = toks := { tk; ln = !ln } :: !toks in
  let is_alpha c = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c = '_' in
  let is_digit c = c >= '0' && c <= '9' in
  let err m = raise (Error (!ln, m)) in
  while !i < n do
    let c = src.[!i] in
    if c = '\n' then begin
      (match !stack with '(' :: _ -> () | _ -> add NL);
      incr ln; incr i
    end
    else if c = ' ' || c = '\t' || c = '\r' then incr i
    else if c = '#' then (while !i < n && src.[!i] <> '\n' do incr i done)
    else if is_digit c then begin
      let s = !i in
      while !i < n && is_digit src.[!i] do incr i done;
      add (INT (int_of_string (String.sub src s (!i - s))))
    end
    else if is_alpha c then begin
      let s = !i in
      while !i < n && (is_alpha src.[!i] || is_digit src.[!i]) do incr i done;
      let w = String.sub src s (!i - s) in
      add (if List.mem w keywords then KW w else ID w)
    end
    else if c = '"' then begin
      incr i;
      let segs = ref [] and b = Buffer.create 16 in
      let flush () =
        if Buffer.length b > 0 then (segs := SLit (Buffer.contents b) :: !segs; Buffer.clear b) in
      let fin = ref false in
      while not !fin do
        if !i >= n || src.[!i] = '\n' then err "unterminated string";
        let c = src.[!i] in
        if c = '"' then (fin := true; incr i)
        else if c = '\\' && !i + 1 < n then begin
          (match src.[!i + 1] with
           | 'n' -> Buffer.add_char b '\n'
           | 't' -> Buffer.add_char b '\t'
           | ch -> Buffer.add_char b ch);
          i := !i + 2
        end
        else if c = '{' then begin
          flush (); incr i;
          let d = ref 1 and s = !i in
          while !d > 0 do
            if !i >= n || src.[!i] = '\n' then err "unterminated { in string";
            (if src.[!i] = '{' then incr d else if src.[!i] = '}' then decr d);
            incr i
          done;
          segs := SCode (String.sub src s (!i - s - 1)) :: !segs
        end
        else (Buffer.add_char b c; incr i)
      done;
      flush ();
      add (STR (List.rev !segs))
    end
    else begin
      let two = if !i + 1 < n then String.sub src !i 2 else "" in
      if two = "->" || two = "==" || two = "+=" then (add (SYM two); i := !i + 2)
      else begin
        (match c with
         | '(' | '{' -> stack := c :: !stack
         | ')' | '}' -> (match !stack with _ :: r -> stack := r | [] -> ())
         | '*' | '+' | '-' | '<' | '>' | ',' | ':' | '.' | '=' -> ()
         | _ -> err (Printf.sprintf "unexpected character '%c'" c));
        add (SYM (String.make 1 c)); incr i
      end
    end
  done;
  add EOF;
  List.rev !toks
