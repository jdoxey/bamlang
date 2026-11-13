# `errors`: the benchmark for D4

Three parts. Deterministic output; every option's version prints the same `expected.txt`. File work happens in a
fresh temporary directory created by the program and removed at the end.

## Part 1: config parser

Input is a fixed multi-line text in the source:
- `[section]` headers and `key = value` lines;
- comments start with `#`;
- 3 deliberate bad lines: a missing `=`, an empty key, and a duplicate key in the same section.

Steps:
- **Fail-fast mode:** print the first error as `config.ini:LINE: message`.
- **Collect-all mode:** print every error, then `3 errors`.
- **A fixed text without the bad lines:** parse it and look up `server.port` (present; print it) and `server.timeout`
  (absent; print `timeout not set, using 30`). The absent lookup must use `Optional`, not an error.

## Part 2: a multi-step file operation with cleanup

`replace_file(dir, name, content)` does:
1. create a lock file `name.lock` (fail if it exists);
2. write `name.tmp`;
3. rename `name.tmp` over `name`;
4. remove the lock.

Run it 5 times: no failure, then an injected failure at step 1, 2, 3 and 4 (via a parameter). After each run, print:
- `ok` or `error: <message naming the step>`;
- the sorted list of files in the directory.

Invariants:
- the lock and the temp file never remain after a run;
- `name` is either the old or the new content, never partial.

Start with an existing `name` holding `old`.

## Part 3: a crew of workers where one fails

4 workers each parse one of 4 small config texts:
- worker 2's text has a bad line, so it returns an error;
- worker 3 deliberately traps (an index out of range) while holding a shared mutex.

Steps:
- The parent prints the re-raised result: `error: worker 2: config.ini:LINE: ... (plus 1 more)`. Choose a
  deterministic rule for which error is "first", for example the lowest worker number. Document it.
- Then show the mutex is detectably poisoned: `mutex poisoned: yes`.
- A test-style check asserts that worker 3 trapped, printing `expect_trap ok`.

## NOTES.md per option

- Lines per part.
- Count of error-propagation tokens or statements (`try`, `?`, `check` or `if err != nil`).
- Conversion glue lines.
- Where context was added and what the final message looked like.
- What happens if a programmer forgets to handle an error (paste the compiler or run-time output).
- Rules a programmer had to know.
