# Conformance tests

Append-only: never weaken or delete an expectation to make a test pass (see `docs/ROADMAP.md` M0).
Each `NN-name.prog` is a program; `NN-name.out` is the exact expected stdout; `NN-name.in` (optional) is stdin.
The `.prog` extension is a placeholder until D12 chooses one; rename then.

**Status: unverified.** No compiler exists yet. Outputs were written by hand (12-chatsim.out is the real output of the C reference in `docs/examples/chatsim/c/`). If the first parser or compiler disagrees with a program or output, decide by the ADRs and fix the file by appending a new numbered test plus a note here; do not edit in place without an issue.
