# `threads`: the benchmark for D3

A deterministic program with no real timers. Each part prints a fixed report, and every option's version must print
the same `expected.txt`.

## A. Parallel map

- Square the integers 1..=1_000_000 using 4 threads, into an ordered result. Print the sum of the result modulo
  1_000_000_007, and the first and last three values.
- Bug variant (in a scratch copy, recorded in NOTES): two threads write the same chunk.

## B. Worker pool

- 4 workers take 20 jobs (`n` = 1..=20) from a channel. Each bumps a shared counter under a mutex and sends `n*n` to
  a result channel.
- The collector sums the results and prints the total (2870) and the counter (20). Shutdown must end without a hang,
  because the last sender's drop closes the channels.
- Bug variants (NOTES): (1) a re-lock of the counter inside a helper called while it is held; (2) the collector exits
  after 5 results; (3) a forgotten drop of one result sender.

## C. A main loop plus a cancellable background job

- The main thread runs an event loop over a scripted list of events: `start`, `tick` ×3, `cancel`, `tick` ×2,
  `quit`. The job does 10 steps.
- At each step the job adds the step to a mutex-guarded partial result, posts `progress k` to the main loop, and
  waits for the main loop's `tick` acknowledgement, so the output is deterministic.
- On `cancel` the job stops at its next checkpoint, outside the lock. The main loop prints every progress message it
  receives, then `cancelled at step k, partial = [..]`. The partial list must be consistent (no half-written step).
  On `quit`, everything is joined.
- Bug variant (NOTES): the job touches main-thread module state. In the real language this is a compile error; record
  what Rust does.

## What to record in each option's NOTES.md

- Line counts per part. The rules a programmer had to know.
- For each bug variant, exactly what happens: compile error (paste it), trap or panic (paste it), or hang.
- Where cancellation is checked. How errors propagate.
- Anything hidden.
