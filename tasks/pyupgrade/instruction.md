# pyupgrade

Build `pyupgrade`, a command-line tool that automatically upgrades Python source to use newer,
more modern syntax. It reads each Python file, applies a set of syntax rewrites, and writes the
file back **in place** as a minimal edit — everything the tool does not rewrite (formatting,
spacing, comments, unrelated code) is preserved exactly.

Organize the internals however you like as long as the command-line interface and the observable
rewrite behavior described here are reproduced exactly.

## Example use case

A developer wants to modernize a legacy module before committing it. They run `pyupgrade` on the
file with a target-version flag; it rewrites the constructs it recognizes **in place** and leaves
everything else (formatting, comments, unrelated code) byte-for-byte unchanged. Because it exits
non-zero when it changed a file, the same command doubles as a pre-commit / CI gate that keeps
failing until the code is already modern.

Given `legacy.py`:

```python
from __future__ import annotations
from typing import List, Optional

x = set([1, 2])
greeting = '{} {}'.format(first, last)

class Widget(object):
    def __init__(self, parts: Optional[List[str]]):
        super(Widget, self).__init__()
        self.parts = parts
```

Running pyupgrade rewrites it in place and exits `1` (because a file changed):

```console
$ python -m pyupgrade --py310-plus legacy.py; echo "exit=$?"
exit=1
$ cat legacy.py
from __future__ import annotations
from typing import List, Optional

x = {1, 2}
greeting = f'{first} {last}'

class Widget:
    def __init__(self, parts: list[str] | None):
        super().__init__()
        self.parts = parts
```

In one pass it applied several rewrites: `set([...])` → a set literal, `str.format(...)` → an
f-string (enabled by `--py36-plus` and above), the explicit `object` base and the
`super(Widget, self)` arguments dropped, and — because the file carries
`from __future__ import annotations` and `--py310-plus` is given — `Optional[List[str]]` →
`list[str] | None`. A second run finds nothing left to change and exits `0`, so the same invocation
can gate a commit:

```console
$ python -m pyupgrade --py310-plus legacy.py; echo "exit=$?"
exit=0
```

## Dependencies

The standard library, plus `tokenize-rt` (a small tokenization helper you may depend on for
token-preserving edits). No network. Rewrites are applied as surgical edits to the original
source — pyupgrade does **not** reformat or re-emit the whole file, so output differs from the
input only at the spots it rewrites.

## Invocation

The package installs with `pip install -e .` and must be runnable as `python -m pyupgrade`.

```
python -m pyupgrade [OPTIONS] <file> [<file> ...]
```

Each file is rewritten in place.

### Exit codes

- Exit `1` if any file was changed (this lets pyupgrade be used as a pre-commit/lint check).
- Exit `0` if no file needed changes.
- `--exit-zero-even-if-changed` always exits `0` (the files are still rewritten).

### Target-version options

By default pyupgrade applies the rewrites that are safe for any Python 3. The
`--py36-plus`, `--py37-plus`, `--py38-plus`, `--py39-plus`, `--py310-plus`, `--py311-plus`,
`--py312-plus`, `--py313-plus`, `--py314-plus` flags each enable the additional rewrites listed
below; a higher flag implies all the lower ones. Other options: `--keep-percent-format` (below),
`--keep-mock`, `--keep-runtime-typing` (below).

## Rewrites applied by default (any Python 3)

Each rewrite is shown as `before` → `after`.

- **Set / dict literals & comprehensions:** `set([1, 2])` → `{1, 2}`; `set((1,))` → `{1}`;
  `set(x for x in y)` → `{x for x in y}`; a conditional comprehension keeps its condition
  (`set([y for y in z if y])` → `{y for y in z if y}`); `dict((a, b) for a, b in y)` →
  `{a: b for a, b in y}`. An **empty** `set([])` becomes `set()` (NOT `{}`, which is a dict).
- **`str.format` auto-numbering:** sequential explicit indices collapse to empty fields:
  `'{0} {1}'.format(1, 2)` → `'{} {}'.format(1, 2)`.
- **printf-style `%` → `str.format`** (unless `--keep-percent-format`): `'%s %s' % (a, b)` →
  `'{} {}'.format(a, b)`; `'%(a)s %(b)s' % {'a': 1, 'b': 2}` → `'{a} {b}'.format(a=1, b=2)`. A
  width/precision spec is carried into the `{}` field: `'%(a).2f' % {'a': v}` → `'{a:.2f}'.format(a=v)`.
- **Unicode string prefix removal:** `u'foo'` → `'foo'`.
- **Invalid escape sequences:** a string whose backslash escapes are all invalid becomes a raw
  string (`'\d'` → `r'\d'`); a string mixing valid and invalid escapes keeps the valid ones and
  backslash-escapes the invalid ones (`'\n\d'` → `'\n\\d'`).
- **`is` / `is not` against a literal** → `==` / `!=`: `x is 5` → `x == 5`;
  `x is not 'foo'` → `x != 'foo'`.
- **`.encode()` to a bytes literal:** a string literal with `.encode()`, `.encode('utf-8')`, or
  another known encoding becomes a bytes literal: `'foo'.encode()` → `b'foo'`;
  `'\xa0'.encode('latin1')` → `b'\xa0'`.
- **Native `str(...)` literals:** `str()` → `''`; `str("foo")` → `"foo"`.
- **`type(<literal>)`** → the builtin type: `type('')` → `str`; `type(0)` → `int`
  (also `type(b'')` → `bytes`, `type(0.)` → `float`).
- **Redundant parentheses in `print`:** `print(("foo"))` → `print("foo")` (a single
  double-parenthesized argument; printing a tuple like `print((1,))` is left alone).
- **Constant-fold duplicate types:** duplicate entries in `isinstance`/`issubclass` type tuples
  and in `except (...)` tuples are removed: `isinstance(x, (int, int))` → `isinstance(x, int)`;
  `except (E1, E1, E2)` → `except (E1, E2)`.
- **Deprecated `unittest` aliases** → canonical names: `self.assertEquals(...)` →
  `self.assertEqual(...)`.
- **`super()` calls:** inside `class C(...)`, `super(C, self).f()` → `super().f()`.
- **"New-style" classes:** an explicit `object` base is dropped: `class C(object): pass` →
  `class C: pass` (and `class C(B, object)` → `class C(B)`).
- **`# coding: ...` magic comment** on the first/second line is removed (UTF-8 is the default).
- **`__future__` import removal:** imports that are unconditional in Python 3 (e.g.
  `with_statement`, `print_function`, `unicode_literals`, ...) are removed entirely.
- **`OSError` aliases:** `EnvironmentError`, `IOError`, `WindowsError`, and `mmap`/`select`/`socket`
  `.error` (including raises and `except` clauses) → `OSError`.
- **Redundant `open` modes:** `open("foo", "U")` → `open("foo")`; `open("f", "wt")` →
  `open("f", "w")` (the `U` mode and a redundant `t` are dropped, `r`/`rt` removed entirely).
- **`yield` loop → `yield from`:** a `for` loop whose body only re-yields its iterand:
  `for x in y:\n    yield x` → `yield from y`.
- **`six` compatibility shims** → native Python 3. The full set of supported rewrites:
  - `six.text_type` → `str`; `six.string_types` → `str` (e.g. in `isinstance(x, six.string_types)`);
    `six.u('x')` → `'x'`; `six.b('x')` → `b'x'`; `six.int2byte(n)` → `bytes((n,))`;
    `six.callable(x)` → `callable(x)`.
  - `class C(six.Iterator): pass` → `class C: pass`;
    `class C(six.with_metaclass(M, B)): pass` → `class C(B, metaclass=M): pass`;
    `@six.add_metaclass(M)` on a class → a `metaclass=M` base (`class C(metaclass=M): pass`);
    the `@six.python_2_unicode_compatible` decorator is dropped.
  - `six.iteritems(d)` → `d.items()` (and `six.iterkeys` → `.keys()`, `six.itervalues` → `.values()`,
    and the `viewitems`/`viewkeys`/`viewvalues` variants likewise).
  - `six.raise_from(e, c)` → `raise e from c`.
  - `six.moves.<name>` attribute access maps to the Python-3 name (`six.moves.range(10)` →
    `range(10)`).
  - a `from six.moves import <name>` whose target is a Python-3 builtin (e.g. `range`) is removed
    entirely.
- **`collections.defaultdict` trivial lambda factory** → the builtin type, when the
  `defaultdict` name is recognized (imported from `collections` or used as `collections.defaultdict`):
  `defaultdict(lambda: [])` → `defaultdict(list)`; `lambda: 0` → `int`; `lambda: ()` → `tuple`;
  `lambda: ''` → `str`; `lambda: dict()` → `dict`; etc.
- **`mock` imports** → `unittest.mock` (unless `--keep-mock`): `from mock import patch` →
  `from unittest.mock import patch`.
- **Unpacking a list comprehension** becomes a generator expression:
  `foo, bar, baz = [fn(x) for x in items]` → `foo, bar, baz = (fn(x) for x in items)`.

## Rewrites enabled by target-version flags

- **`--py36-plus`:**
  - **f-strings:** simple `str.format` calls become f-strings: `'{} {}'.format(foo, bar)` →
    `f'{foo} {bar}'`; `'{foo}'.format(foo=foo)` → `f'{foo}'`. Attribute access on a field and a
    `!r`/`!s`/`!a` conversion are carried into the f-string: `'{x.y}'.format(x=obj)` → `f'{obj.y}'`;
    `'{!r}'.format(v)` → `f'{v!r}'`. A format spec is carried in too (`'{:>10}'.format(name)` →
    `f'{name:>10}'`), and multiple named fields work (`'{a}-{b}'.format(a=p, b=q)` → `f'{p}-{q}'`).
    Be timid: do not create an f-string if it would be longer or if the substitution is complicated
    (e.g. an index like `'{0[1]}'.format(seq)` is left alone).
  - **`typing.NamedTuple` / `typing.TypedDict` call syntax → class syntax:**
    `NT = typing.NamedTuple('NT', [('a', int), ('b', str)])` →
    `class NT(typing.NamedTuple):\n    a: int\n    b: str`; the `TypedDict` keyword form
    (`typing.TypedDict("D", a=int, b=str)`) and dict form (`typing.TypedDict("D", {"a": int})`)
    likewise become a class. This works whether the name is `typing.NamedTuple`/`typing.TypedDict`
    or a directly-imported `NamedTuple`/`TypedDict`; each field keeps its annotation **verbatim**
    (including subscripts like `List[int]` and forward-reference strings like `'Foo'`); and a
    trailing `total=False` on a `TypedDict` is carried onto the class base
    (`typing.TypedDict('D', {'a': int}, total=False)` → `class D(typing.TypedDict, total=False):`).
  - **Moved-stdlib import replacement:** e.g. `from collections import Mapping` →
    `from collections.abc import Mapping`.
  - **`typing.Text` → `str`** (the deprecated alias).
  - **`sys.version_info` branch removal:** a version guard that only distinguishes an older Python
    from the target is collapsed to whichever branch the target takes, dropping the guard:
    - `if sys.version_info < (3, 6): A else: B` → `B` (the modern else body is kept).
    - `if sys.version_info >= (3, 6): A else: B` → `A` (the if body is kept).
    - the index form `if sys.version_info[0] >= 3: A else: B` → `A`, and the attribute form
      `if sys.version_info.major >= 3: A else: B` → `A`.
    - every comparison operator is handled the same way (`<`, `<=`, `>`, `>=`), as is a bare py2
      guard `if sys.version_info < (3,): A else: B` → `B`.
    - when the guard has an `elif`, the chain collapses to that elif as a plain `if True:` branch
      (`if sys.version_info < (3, 6): A elif COND: B` → `if True:` with `B`).
    - with **no `else`**: if the guard is the taken branch its body is dedented in place
      (`if sys.version_info >= (3, 6):\n    A` → `A`); if it is the untaken branch the whole `if`
      is removed (`if sys.version_info < (3, 6):\n    A` → nothing).
    Higher `--pyXX-plus` flags raise the version treated as old, so under `--py38-plus` a
    `< (3, 8)` guard is the old branch (its `else` body is kept).
- **`--py37-plus`:** `subprocess.run(..., universal_newlines=True)` → `..., text=True`.
- **`--py38-plus`:** `@functools.lru_cache()` → `@functools.lru_cache` (drop empty parens).
- **`--py39-plus`:** `@functools.lru_cache(maxsize=None)` → `@functools.cache`; and **PEP 585**
  typing generics (see below): `List[str]` → `list[str]`.
- **`--py310-plus`:** **PEP 604** unions (see below): `Optional[str]` → `str | None`;
  `Union[int, str]` → `int | str`.
- **`--py311-plus`:** `datetime.timezone.utc` → `datetime.UTC`.

### PEP 585 / PEP 604 typing rewrites

The PEP 585 and PEP 604 rewrites apply only when the file contains `from __future__ import
annotations` (so the annotations are not evaluated at runtime), unless `--keep-runtime-typing` is
given. The relevant names (`List`, `Dict`, `Tuple`, `Set`, `FrozenSet`, `Type`, `Optional`,
`Union`, ...) are recognized from their `typing` import (or used as `typing.Name`); the `typing`
import itself is left untouched.

- **PEP 585** lowercases the standard generics to their builtin form: `List[str]` → `list[str]`,
  `Dict[str, int]` → `dict[str, int]`, `Tuple[int, ...]` → `tuple[int, ...]`, `Set`/`FrozenSet`/
  `Type` likewise.
- **PEP 604** unions: `Optional[str]` → `str | None`; `Union[int, str]` → `int | str`. The rewrite
  recurses, so an inner generic is rewritten too: under `--py310-plus` (which implies `--py39-plus`)
  `Optional[List[int]]` → `list[int] | None`.
