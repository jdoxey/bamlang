#!/usr/bin/env python3
"""Conformance cases for the strict TOML 1.0 subset in common2.py: each case is accepted with the exact value,
or rejected. A construct we do not support must be rejected, never read differently from real TOML."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common2 import ToolError, dump_toml, parse_toml  # noqa: E402

REJECT = object()
CASES = [
    # (name, source, expected value or REJECT)
    ("plain string", 'a = "x"', {"a": "x"}),
    ("escapes", 'a = "l1\\nl2\\t\\\\ \\"q\\" \\u00e9 \\U0001F600"', {"a": "l1\nl2\t\\ \"q\" \u00e9 \U0001F600"}),
    ("literal string keeps backslashes", "p = 'C:\\path\\new'", {"p": "C:\\path\\new"}),
    ("basic string with a Windows path escaped", 'p = "C:\\\\new\\\\table"', {"p": "C:\\new\\table"}),
    ("unknown escape \\p", 'a = "C:\\path"', REJECT),
    ("old subset misread \\n: '\"C:\\new\"' is a newline in TOML, we agree", 'a = "C:\\new"', {"a": "C:\new"}),
    ("bad unicode escape", 'a = "\\u12"', REJECT),
    ("surrogate escape", 'a = "\\ud800"', REJECT),
    ("multi-line basic string", 'a = """x"""', REJECT),
    ("multi-line literal string", "a = '''x'''", REJECT),
    ("newline in string", 'a = "x\ny"', REJECT),
    ("integers", "a = 5\nb = -3\nc = 0", {"a": 5, "b": -3, "c": 0}),
    ("leading zero integer", "a = 007", REJECT),
    ("underscore integer", "a = 1_000", REJECT),
    ("hex integer", "a = 0xff", REJECT),
    ("float", "a = 1.5", REJECT),
    ("date", "a = 1979-05-27", REJECT),
    ("booleans", "a = true\nb = false", {"a": True, "b": False}),
    ("multi-line array with comments and trailing comma",
     'a = [\n  "x", # first\n  "y",\n]\n', {"a": ["x", "y"]}),
    ("mixed array", 'a = ["x", 1]', REJECT),
    ("nested array", "a = [[1]]", REJECT),
    ("inline table", 'a = { url = "x" }', REJECT),
    ("dotted key", "a.b = 1", REJECT),
    ("array of tables", "[[a]]\nx = 1", REJECT),
    ("duplicate key", "a = 1\na = 2", REJECT),
    ("duplicate table", "[t]\nx = 1\n[t]\ny = 2", REJECT),
    ("table after its sub-table is fine", "[a.b]\nx = 1\n[a]\ny = 2", {"a": {"b": {"x": 1}, "y": 2}}),
    ("quoted table parts", '[sum."host/ann/json@v1.0.0"]\nhash = "h"', {"sum": {"host/ann/json@v1.0.0": {"hash": "h"}}}),
    ("table clashes with a key", 'a = 1\n[a]\nb = 2', REJECT),
    ("key after a table of the same name", "[a]\nb = 1\n[c]\na = 2", {"a": {"b": 1}, "c": {"a": 2}}),
    ("CRLF line endings", 'a = 1\r\nb = "x"\r\n', {"a": 1, "b": "x"}),
    ("bare CR", "a = 1\rb = 2", REJECT),
    ("junk after a value", 'a = "x" y', REJECT),
    ("byte order mark", '\ufeffa = 1', REJECT),
    ("control character in a string", 'a = "x\x01"', REJECT),
    ("comment after a value", 'a = 1 # note', {"a": 1}),
    ("hash inside a string is not a comment", 'a = "x # y"', {"a": "x # y"}),
    ("missing value", "a =", REJECT),
    ("unterminated array", 'a = ["x"', REJECT),
]


def run():
    fails = []
    for name, src, want in CASES:
        try:
            got = parse_toml(src, "case")
        except ToolError as e:
            got = REJECT
            msg = str(e)
        if got != want:
            fails.append(f"toml case {name!r}: expected {'reject' if want is REJECT else want!r}, got "
                         f"{'reject (' + msg + ')' if got is REJECT else repr(got)}")
    # round trip: what we write is what we read
    tricky = {"t": {"s": 'a\\b"c\nd\te', "n": ["x", "y"], "b": True, "i": -4}, "u": {"k/v@1": {"h": "z"}}}
    if parse_toml(dump_toml(tricky), "roundtrip") != tricky:
        fails.append("toml round trip changed a value")
    return fails


if __name__ == "__main__":
    f = run()
    for x in f:
        print("FAIL " + x, file=sys.stderr)
    print(f"toml conformance: {len(CASES)} cases, {len(f)} failures")
    sys.exit(1 if f else 0)
