# Built-in parameter names (P3n)

Every call writes `name: value`. User functions use their declared names. Built-ins use this table
(one line per built-in; receiver kind in brackets where the name is shared).

- print(text), eprint(text), error(text) [corpus fn `error` in widgets.p3 uses its declaration]. `print` takes one `Str` (no variadics: build the text with `+` or interpolation).
- some(value) (construction; pattern `some(x)` stays positional), Mutex(value), sleep_ms(ms), clamp(value, low, high)
- expect_trap(action), indent(levels) [helper used by render code]
- read(path), write(path, text), remove(path), rename(from, to); File.create(path), Lock.create(path), TempDir.create(prefix)
- Kind.parse(text) (enum parse helper); xs.take(count)
- List/Deque: push(item), get(at), get_mut(at), remove_at(at), remove_value(value), take_out(at), contains(item),
  insert(at, value) [table said insert(key, value); `at` fits a List index], rest(from)
- join(sep), map(each), filter(keep)
- Map/Set: has(key), remove(key), get(key), insert(key, value)
- Pool: add(value) / add(value, owner), remove(handle), get(handle), get_mut(handle), has(handle) [added], id(handle), handle(id)
- Str: starts_with(prefix), ends_with(suffix), split(sep), repeat(times), before(sep), after(sep), find(text)
- Crew: c.go(task); Channel: send(value); Txn.new(undo), txn.on_undo(action); Report: add_if_err(result)
- Variant construction: named in the declaration: `Panel(children)`, `Button(label)`, `Drag(dx)`, `Ext(widget)`
- Calls through function values: names come from the function type, e.g. `cb: fn(mut srv: Server, room: ..., from: ..., text: Str)`
  is called `m.cb(srv: self, room: room, from: from, text: text)`; `run: fn(me: Handle of Widget)` is called `cb.run(me: h)`.

## Machine-readable table (read by check_labels.py)

One signature per line: `name(p1, p2=)` is a function, `.name(...)` a method, `Type.name(...)` a static function.
`=` marks a defaulted parameter. A method name listed more than once with different signatures is ambiguous and
check_labels.py skips such calls (the receiver type is not known to it). Lines that do not match this shape are prose.

```
print(text)
eprint(text)
error(text)
some(value)
Mutex(value)
sleep_ms(ms)
clamp(value, low, high)
expect_trap(action)
indent(levels)
read(path)
write(path, text)
remove(path)
rename(from, to)
File.create(path)
Lock.create(path)
TempDir.create(prefix)
Kind.parse(text)
Txn.new(undo)
.take(count)
.push(item)
.get(at)
.get_mut(at)
.remove_at(at)
.remove_value(value)
.take_out(at)
.contains(item)
.insert(at, value)
.rest(from)
.join(sep)
.map(each)
.filter(keep)
.has(key)
.remove(key)
.get(key)
.insert(key, value)
.add(value, owner=)
.remove(handle)
.get(handle)
.get_mut(handle)
.has(handle)
.id(handle)
.handle(id)
.starts_with(prefix)
.ends_with(suffix)
.split(sep)
.repeat(times)
.before(sep)
.after(sep)
.find(text)
.go(task)
.send(value)
.on_undo(action)
.add_if_err(result)
```
