# `widgets`: the second benchmark program (UI-shaped lifetimes)

A scripted widget tree with no real screen. It adds the shapes `chatsim` lacks: hierarchies, a callback that
destroys its own widget, an observer that unsubscribes itself during notification, and a shared cache. Input is one
command per line on stdin; `#` lines are comments. Output is deterministic.

## Objects

- **Widget:** kind (`window`, `panel`, `button`, `label`, `image`), name, children (in order), and an optional
  `onClick` callback that captures whatever it needs. A label may subscribe to the model.
- **Model:** an integer `count` with a subscriber list. Each subscriber is a callback, called on every change.
- **ImageCache:** shared by every `image` widget. It maps a file name to decoded bytes (fake: the name repeated
  100 times). An entry is dropped when no widget uses it.

## Commands

| Command | Effect |
|---|---|
| `window NAME` | create a top-level window |
| `add PARENT KIND NAME [ARG]` | add a child. `image` takes a file name, using the cache. `label` with ARG `count` subscribes to the model. |
| `on NAME ACTION [ARG]` | set the button's `onClick`. Actions: `inc` (count += 1), `close` (remove the window that contains this button, so the callback destroys its own widget), `open` (create window ARG with a label and a `close` button, during the click), `unsub` (remove the label ARG's subscription) |
| `click NAME` | run the button's `onClick` |
| `remove NAME` | remove the widget and its subtree |
| `tree` | print every window and its subtree, indented two spaces per level |
| `stats` | print live widgets, subscribers, cache entries and model count |

## Cases it must exercise (numbers from `memory-cases.md`)

| # | Case | In `widgets` |
|---|---|---|
| 7, 8 | removing mid-life; replacing frees the old value | `remove` a subtree; `on` replaces a callback |
| 11 | back-reference | a button's `close` must find its enclosing window |
| 12, 13 | shared, freed by the last user | an image cache entry used by two images |
| 16 | observer leaves while registered | a label is removed while subscribed |
| 19 | destroy itself in its own callback | `close` |
| 20, 21 | re-entrancy; mutation during iteration | an `inc` notification makes a subscriber `unsub` itself; `open` adds widgets during dispatch |
| 15 | callback whose target is gone | a click on a button whose `onClick` captured a removed label |
