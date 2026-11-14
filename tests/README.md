# Conformance tests

Run by the harness in `compiler/lantern-tests`:

    cargo run --manifest-path compiler/Cargo.toml -p lantern-tests -- [--allow-missing] [--update] [--stage parse]

## Append-only rule

Never weaken or delete a conformance case to make it pass. A wrong case is fixed only in a commit whose message says
why and cites an ADR. New cases may be added freely.

## Layout

- `corpus/*.ltn`: programs that must work. Each has `expected/ast/NAME.ast` (the exact AST text). The harness also runs
  a CRLF copy of each and requires the same AST (CR is stripped before comparing).
- `bad/*.ltn`: programs that must fail. The first line is `# expect: LINE: substring`; the stage must fail at that
  line with a message containing the substring.
- `reference/`: the Python meaning-check and label-check scripts, kept for reference only.

## Results and exit code

Each case prints PASS, FAIL or NOT-IMPLEMENTED, then a summary. Exit 1 on any FAIL, and on NOT-IMPLEMENTED unless
`--allow-missing` is given (CI uses it until the parser lands in M1).

## Updating golden files

`--update` rewrites `expected/ast/*.ast` from the current output. It refuses if the stage is not implemented or a corpus
file fails. Review `git diff tests/expected` before committing; an update is a change to the contract.
