# Memory-management cases an example program should cover

★ marks the cases where candidate models differ most.

## Ownership and lifetime
1. Allocation that outlives its function (a factory).
2. Temporary that dies with its scope.
3. Growable data of unknown size.
4. Ownership transfer ★
5. Mutating a large value in place, without a copy.
6. Deliberate copy (a snapshot).
7. Removing one item mid-life.
8. Replacing a value, which frees the old one.
9. Program-lifetime data.
10. Cleanup on an error path.

## Sharing and references
11. Back-reference (child to parent) ★
12. Shared, freed when the last user goes ★
13. Shared mutable cache ★
14. Reference to something that may be deleted ★
15. Callback where `self` may be gone ★
16. Observer list, with an observer leaving while registered.
17. Cycle ★

## Callbacks and time
18. Closure that captures local state.
19. Object destroys itself in its own callback.
20. Re-entrancy ★
21. Mutation during iteration.
22. Async result that arrives after its owner has gone.

## Threads
23. Moving data to a worker and back ★
24. Shared read-only data.
25. Shared mutable data ★
26. Owner dies while the worker runs.

## Extras
- A non-memory resource closed at a known moment, including on early return.
- The C boundary: passing buffers out, and callbacks coming in.
- Freeing a very large structure.

The four most likely to break a model are 12, 14, 20 and 25.
