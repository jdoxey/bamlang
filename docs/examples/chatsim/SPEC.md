# `chatsim`: the shared benchmark program

A tiny chat room driven by a text script. It has no screen, sockets or real timers, but it has the object lifetimes that break memory models. About 300 lines of C.

## Behaviour

It reads commands from stdin, one event per line. `tick N` advances a fake clock, so runs are deterministic.

```
join alice general
join bob general
join echobot general        # a bot that replies to every message
say alice hello
remind alice 3 "stand up"   # callback fires in 3 ticks
dm bob alice "hi"
move bob random             # bob changes rooms
leave alice                 # alice leaves before the reminder fires
tick 3                      # reminder fires: alice is gone
leave bob
leave echobot               # last member leaves: room is freed and archived
stats
```

## Objects

- **User:** name, current room, pending reminders.
- **Room:** name, member list, message history. Exists while it has members.
- **Server:** users, rooms, timer queue, rate limiter, archive worker thread, stats.

## Cases it must exercise

Numbers refer to `docs/adr/0001-research/memory-cases.md`.

| # | Case | In `chatsim` |
|---|---|---|
| 4 | Ownership transfer | `move`: a user changes rooms. |
| 11 | Back-reference | `user.room` and `room.members` point at each other. |
| 12 | Freed when the last user goes | The last `leave` frees the room. |
| 13 | Shared mutable cache | The rate limiter is used by `say` and `dm`. |
| 14 | Reference to something deleted | `dm` to a user who has left. |
| 15 | Callback where `self` is gone | `remind` fires after its user has left. |
| 17 | Cycle | Each user's `onMessage` callback, held by the room, captures the user. |
| 20 | Re-entrancy | `echobot` posts into the room during the broadcast it is replying to. |
| 23 | Move to a worker | A closed room's history moves to the archive thread. |
| 25 | Shared mutable across threads | The worker updates `stats`, and the `stats` command reads it. |
| 26 | Owner dies while the worker runs | A room is reopened while its archive is still being written. |

## How to use it

1. Write it in C first, and run it under AddressSanitizer with a script that hits every case.
2. For a memory-model decision, write `room` and `user` in each candidate model, using the closest real language, and run the same script.
