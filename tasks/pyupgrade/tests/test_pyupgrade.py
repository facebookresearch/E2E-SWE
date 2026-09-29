"""End-to-end tests for the ``pyupgrade`` syntax-upgrading CLI.

Every test drives the public command-line interface via ``python -m pyupgrade``,
which rewrites the given file in place and exits non-zero when it changed a file.
Each test writes a small source file, runs pyupgrade, and asserts the exact rewritten
contents (and, where relevant, the exit code). No internal modules are imported, so
any faithful reimplementation that reproduces the documented CLI contract passes.
"""

import subprocess
import sys

PYUP = [sys.executable, "-m", "pyupgrade"]


def run(tmp_path, flags, src, name="f.py"):
    """Write ``src`` to ``tmp_path/name``, run pyupgrade, return (rc, new_contents)."""
    path = tmp_path / name
    path.write_text(src)
    proc = subprocess.run(PYUP + list(flags) + [str(path)],
                         capture_output=True, text=True)
    return proc.returncode, path.read_text()


# --------------------------------------------------------------------------- #
# Default (py3) rewrites                                                       #
# --------------------------------------------------------------------------- #

def test_set_and_dict_literals(tmp_path):
    """``set(...)`` / ``dict(...)`` constructor calls become set/dict literals or
    comprehensions."""
    assert run(tmp_path, [], "x = set([1, 2])\n") == (1, "x = {1, 2}\n")
    assert run(tmp_path, [], "x = set((1,))\n") == (1, "x = {1}\n")
    assert run(tmp_path, [], "x = set(x for x in y)\n") == (1, "x = {x for x in y}\n")
    assert run(tmp_path, [], "x = dict((a, b) for a, b in y)\n") == (
        1, "x = {a: b for a, b in y}\n")


def test_string_literal_fixes(tmp_path):
    """Unicode-prefixed literals lose the ``u``; a string of only invalid escapes
    becomes raw; a mixed valid/invalid escape string gets the invalid one escaped."""
    assert run(tmp_path, [], "x = u'foo'\n") == (1, "x = 'foo'\n")
    assert run(tmp_path, [], "x = '\\d'\n") == (1, "x = r'\\d'\n")
    assert run(tmp_path, [], "x = '\\n\\d'\n") == (1, "x = '\\n\\\\d'\n")


def test_encode_to_bytes_literal(tmp_path):
    """A string literal followed by ``.encode()`` / ``.encode("utf-8")`` (or a known
    encoding) becomes a bytes literal."""
    assert run(tmp_path, [], "x = 'foo'.encode()\n") == (1, "x = b'foo'\n")
    assert run(tmp_path, [], "x = 'foo'.encode('utf-8')\n") == (1, "x = b'foo'\n")
    assert run(tmp_path, [], 'x = "\\xa0".encode("latin1")\n') == (1, 'x = b"\\xa0"\n')


def test_native_str_and_type_of_primitive(tmp_path):
    """``str(...)`` of a native literal collapses to the literal, and ``type(<lit>)``
    collapses to the builtin type."""
    assert run(tmp_path, [], 'x = str("foo")\n') == (1, 'x = "foo"\n')
    assert run(tmp_path, [], "x = str()\n") == (1, "x = ''\n")
    assert run(tmp_path, [], "x = type('')\n") == (1, "x = str\n")
    assert run(tmp_path, [], "x = type(0)\n") == (1, "x = int\n")


def test_is_literal_comparison(tmp_path):
    """``is`` / ``is not`` against a constant literal becomes ``==`` / ``!=``."""
    assert run(tmp_path, [], "if x is 5:\n    pass\n") == (1, "if x == 5:\n    pass\n")
    assert run(tmp_path, [], "if x is not 'foo':\n    pass\n") == (
        1, "if x != 'foo':\n    pass\n")


def test_constant_fold(tmp_path):
    """Duplicate types in ``isinstance``/``issubclass`` tuples and duplicate
    exception classes in ``except`` tuples are de-duplicated."""
    assert run(tmp_path, [], "isinstance(x, (int, int))\n") == (
        1, "isinstance(x, int)\n")
    assert run(tmp_path, [], "try:\n    pass\nexcept (E1, E1, E2):\n    pass\n") == (
        1, "try:\n    pass\nexcept (E1, E2):\n    pass\n")


def test_format_specifier_numbering(tmp_path):
    """Sequential explicit ``{0} {1}`` format fields drop to auto-numbered ``{} {}``."""
    assert run(tmp_path, [], "x = '{0} {1}'.format(1, 2)\n") == (
        1, "x = '{} {}'.format(1, 2)\n")


def test_percent_to_format(tmp_path):
    """printf-style ``%`` formatting is rewritten to ``str.format`` (positional and
    mapping forms)."""
    assert run(tmp_path, [], "x = '%s %s' % (a, b)\n") == (
        1, "x = '{} {}'.format(a, b)\n")
    assert run(tmp_path, [], "x = '%(a)s %(b)s' % {'a': 1, 'b': 2}\n") == (
        1, "x = '{a} {b}'.format(a=1, b=2)\n")


def test_keep_percent_format(tmp_path):
    """``--keep-percent-format`` leaves printf-style ``%`` formatting untouched (and
    so exits 0 when that is the only candidate)."""
    assert run(tmp_path, ["--keep-percent-format"], "x = '%s' % (a,)\n") == (
        0, "x = '%s' % (a,)\n")


def test_super_and_new_style_class(tmp_path):
    """``super(C, self)`` collapses to ``super()`` and an explicit ``object`` base is
    dropped."""
    assert run(tmp_path, [],
               "class C(B):\n    def f(self):\n        super(C, self).f()\n") == (
        1, "class C(B):\n    def f(self):\n        super().f()\n")
    assert run(tmp_path, [], "class C(object):\n    pass\n") == (
        1, "class C:\n    pass\n")


def test_print_redundant_parens(tmp_path):
    """Redundant double parentheses around a single ``print`` argument are removed."""
    assert run(tmp_path, [], 'print(("foo"))\n') == (1, 'print("foo")\n')


def test_unittest_aliases(tmp_path):
    """Deprecated unittest method aliases are rewritten to their canonical names."""
    assert run(tmp_path, [],
               "class T(TestCase):\n    def t(self):\n        self.assertEquals(1, 1)\n") == (
        1, "class T(TestCase):\n    def t(self):\n        self.assertEqual(1, 1)\n")


def test_open_modes(tmp_path):
    """Redundant / legacy ``open`` modes are normalised."""
    assert run(tmp_path, [], 'open("foo", "U")\n') == (1, 'open("foo")\n')
    assert run(tmp_path, [], 'open("f", "wt")\n') == (1, 'open("f", "w")\n')


def test_oserror_alias(tmp_path):
    """``EnvironmentError`` (and friends) are rewritten to ``OSError``."""
    assert run(tmp_path, [], "raise EnvironmentError('boom')\n") == (
        1, "raise OSError('boom')\n")


def test_encoding_comment_removed(tmp_path):
    """A redundant ``# coding: ...`` magic comment on the first line is removed."""
    assert run(tmp_path, [], "# coding: utf-8\nx = 1\n") == (1, "x = 1\n")


def test_future_import_removed(tmp_path):
    """A no-longer-needed ``__future__`` import is removed entirely."""
    assert run(tmp_path, [], "from __future__ import with_statement\nx = 1\n") == (
        1, "x = 1\n")


def test_yield_from(tmp_path):
    """A ``for`` loop that only re-yields its iterand becomes ``yield from``."""
    assert run(tmp_path, [], "def f():\n    for x in y:\n        yield x\n") == (
        1, "def f():\n    yield from y\n")


def test_six_rewrites(tmp_path):
    """``six`` compatibility shims are rewritten to native Python 3 constructs."""
    assert run(tmp_path, [], "x = six.text_type\n") == (1, "x = str\n")
    assert run(tmp_path, [], "class C(six.Iterator):\n    pass\n") == (
        1, "class C:\n    pass\n")
    assert run(tmp_path, [], "class C(six.with_metaclass(M, B)):\n    pass\n") == (
        1, "class C(B, metaclass=M):\n    pass\n")


def test_defaultdict_lambda(tmp_path):
    """A ``collections.defaultdict`` whose default factory is a trivial lambda is
    rewritten to use the builtin type directly (the ``defaultdict`` name must be
    recognized via its import)."""
    base = "from collections import defaultdict\n"
    assert run(tmp_path, [], base + "x = defaultdict(lambda: [])\n") == (
        1, base + "x = defaultdict(list)\n")
    assert run(tmp_path, [], base + "x = defaultdict(lambda: 0)\n") == (
        1, base + "x = defaultdict(int)\n")
    assert run(tmp_path, [], base + "x = defaultdict(lambda: ())\n") == (
        1, base + "x = defaultdict(tuple)\n")


def test_mock_import(tmp_path):
    """A ``mock`` import is rewritten to ``unittest.mock`` (unless ``--keep-mock``)."""
    assert run(tmp_path, [], "from mock import patch\n") == (
        1, "from unittest.mock import patch\n")
    assert run(tmp_path, ["--keep-mock"], "from mock import patch\n") == (
        0, "from mock import patch\n")


def test_unpack_list_comprehension(tmp_path):
    """An unpacking assignment from a list comprehension becomes a generator
    expression."""
    assert run(tmp_path, [], "foo, bar, baz = [fn(x) for x in items]\n") == (
        1, "foo, bar, baz = (fn(x) for x in items)\n")


# --------------------------------------------------------------------------- #
# Version-gated rewrites                                                       #
# --------------------------------------------------------------------------- #

def test_fstrings_py36(tmp_path):
    """``--py36-plus`` rewrites simple ``str.format`` calls into f-strings (positional
    and named)."""
    assert run(tmp_path, ["--py36-plus"], "x = '{} {}'.format(foo, bar)\n") == (
        1, "x = f'{foo} {bar}'\n")
    assert run(tmp_path, ["--py36-plus"], "x = '{foo}'.format(foo=foo)\n") == (
        1, "x = f'{foo}'\n")


def test_typeddict_py36(tmp_path):
    """``--py36-plus`` rewrites a ``typing.TypedDict(...)`` call (keyword or dict form)
    into the class form."""
    assert run(tmp_path, ["--py36-plus"],
               'D = typing.TypedDict("D", a=int, b=str)\n') == (
        1, "class D(typing.TypedDict):\n    a: int\n    b: str\n")
    assert run(tmp_path, ["--py36-plus"],
               'D = typing.TypedDict("D", {"a": int, "b": str})\n') == (
        1, "class D(typing.TypedDict):\n    a: int\n    b: str\n")


def test_import_replacements_py36(tmp_path):
    """``--py36-plus`` moves a moved-stdlib import to its new home."""
    assert run(tmp_path, ["--py36-plus"], "from collections import Mapping\n") == (
        1, "from collections.abc import Mapping\n")


def test_subprocess_run_py37(tmp_path):
    """``--py37-plus`` rewrites ``subprocess.run(..., universal_newlines=True)`` to use
    ``text=True``."""
    assert run(tmp_path, ["--py37-plus"],
               "subprocess.run(['x'], universal_newlines=True)\n") == (
        1, "subprocess.run(['x'], text=True)\n")


def test_lru_cache(tmp_path):
    """``--py38-plus`` drops the empty parens on ``functools.lru_cache()``; with
    ``--py39-plus`` a ``maxsize=None`` cache becomes ``functools.cache``."""
    assert run(tmp_path, ["--py38-plus"],
               "import functools\n@functools.lru_cache()\ndef f():\n    pass\n") == (
        1, "import functools\n@functools.lru_cache\ndef f():\n    pass\n")
    assert run(tmp_path, ["--py39-plus"],
               "import functools\n@functools.lru_cache(maxsize=None)\ndef f():\n    pass\n") == (
        1, "import functools\n@functools.cache\ndef f():\n    pass\n")


def test_pep585_py39(tmp_path):
    """``--py39-plus`` with ``from __future__ import annotations`` rewrites PEP 585
    typing generics to their builtin form."""
    src = ("from __future__ import annotations\n"
           "from typing import List\n"
           "def f(x: List[str]) -> None:\n    pass\n")
    out = ("from __future__ import annotations\n"
           "from typing import List\n"
           "def f(x: list[str]) -> None:\n    pass\n")
    assert run(tmp_path, ["--py39-plus"], src) == (1, out)


def test_pep604_py310(tmp_path):
    """``--py310-plus`` with ``from __future__ import annotations`` rewrites
    ``Optional``/``Union`` to PEP 604 ``X | Y`` unions."""
    src1 = ("from __future__ import annotations\n"
            "from typing import Optional\n"
            "def f() -> Optional[str]:\n    pass\n")
    out1 = ("from __future__ import annotations\n"
            "from typing import Optional\n"
            "def f() -> str | None:\n    pass\n")
    assert run(tmp_path, ["--py310-plus"], src1) == (1, out1)
    src2 = ("from __future__ import annotations\n"
            "from typing import Union\n"
            "def f() -> Union[int, str]:\n    pass\n")
    out2 = ("from __future__ import annotations\n"
            "from typing import Union\n"
            "def f() -> int | str:\n    pass\n")
    assert run(tmp_path, ["--py310-plus"], src2) == (1, out2)


def test_version_branch_removal_py36(tmp_path):
    """``--py36-plus`` removes a ``sys.version_info`` branch that only guards older
    Pythons, keeping the modern branch."""
    src = ("import sys\n"
           "if sys.version_info < (3, 6):\n    print('old')\nelse:\n    print('new')\n")
    assert run(tmp_path, ["--py36-plus"], src) == (1, "import sys\nprint('new')\n")


def test_datetime_utc_py311(tmp_path):
    """``--py311-plus`` rewrites ``datetime.timezone.utc`` to the ``datetime.UTC``
    alias."""
    assert run(tmp_path, ["--py311-plus"],
               "import datetime\nx = datetime.timezone.utc\n") == (
        1, "import datetime\nx = datetime.UTC\n")


# --------------------------------------------------------------------------- #
# Exit-code contract                                                           #
# --------------------------------------------------------------------------- #

def test_exit_code_contract(tmp_path):
    """pyupgrade exits 1 when it rewrites a file and 0 when nothing changes;
    ``--exit-zero-even-if-changed`` forces 0 while still rewriting."""
    # already-modern file: no change, exit 0
    assert run(tmp_path, [], "x = 1\n") == (0, "x = 1\n")
    # changed file: exit 1
    assert run(tmp_path, [], "x = set([1, 2])\n") == (1, "x = {1, 2}\n")
    # changed but forced exit 0
    assert run(tmp_path, ["--exit-zero-even-if-changed"], "x = set([1, 2])\n") == (
        0, "x = {1, 2}\n")


# --------------------------------------------------------------------------- #
# More structural rewrites (NamedTuple / TypedDict / version branches)         #
# --------------------------------------------------------------------------- #

def test_namedtuple_variants_py36(tmp_path):
    """``--py36-plus`` rewrites the ``NamedTuple`` call form across shapes: the name imported
    directly (not just ``typing.NamedTuple``), a single field, and fields whose annotations are
    themselves subscripts or forward-reference strings (each annotation is carried over verbatim)."""
    assert run(tmp_path, ["--py36-plus"],
               "from typing import NamedTuple\nNT = NamedTuple('NT', [('a', int)])\n") == (
        1, "from typing import NamedTuple\nclass NT(NamedTuple):\n    a: int\n")
    assert run(tmp_path, ["--py36-plus"],
               "NT = typing.NamedTuple('NT', [('x', int)])\n") == (
        1, "class NT(typing.NamedTuple):\n    x: int\n")
    assert run(tmp_path, ["--py36-plus"],
               "NT = typing.NamedTuple('NT', [('a', List[int]), ('b', 'Foo')])\n") == (
        1, "class NT(typing.NamedTuple):\n    a: List[int]\n    b: 'Foo'\n")


def test_typeddict_total_false_py36(tmp_path):
    """``--py36-plus`` carries a trailing ``total=False`` keyword onto the generated class base."""
    assert run(tmp_path, ["--py36-plus"],
               "D = typing.TypedDict('D', {'a': int}, total=False)\n") == (
        1, "class D(typing.TypedDict, total=False):\n    a: int\n")


def test_version_branch_more_variants_py36(tmp_path):
    """``--py36-plus`` collapses several ``sys.version_info`` guard shapes: a ``>= (3, 6)`` guard
    keeps the IF body (drops the else); the ``sys.version_info[0] >= 3`` index form likewise; and
    a guard with an ``elif`` collapses to that elif as a plain ``if True:`` branch."""
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info >= (3, 6):\n    x = 1\nelse:\n    x = 2\n") == (
        1, "import sys\nx = 1\n")
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info[0] >= 3:\n    x = 1\nelse:\n    x = 2\n") == (
        1, "import sys\nx = 1\n")
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info < (3, 6):\n    a = 1\nelif True:\n    a = 2\n") == (
        1, "import sys\nif True:\n    a = 2\n")


def test_version_branch_threshold_py38(tmp_path):
    """The target flag raises the version treated as "old": under ``--py38-plus`` a ``< (3, 8)``
    guard is the old branch, so the modern ``else`` body is kept."""
    assert run(tmp_path, ["--py38-plus"],
               "import sys\nif sys.version_info < (3, 8):\n    x = 1\nelse:\n    x = 2\n") == (
        1, "import sys\nx = 2\n")


# --------------------------------------------------------------------------- #
# More format / f-string / set rewrites                                       #
# --------------------------------------------------------------------------- #

def test_fstring_attribute_and_conversion_py36(tmp_path):
    """``--py36-plus`` f-string conversion carries attribute access and ``!r`` / ``!s`` conversions
    into the f-string: ``'{x.y}'.format(x=obj)`` -> ``f'{obj.y}'``; ``'{!r}'.format(v)`` ->
    ``f'{v!r}'``."""
    assert run(tmp_path, ["--py36-plus"], "x = '{x.y}'.format(x=obj)\n") == (
        1, "x = f'{obj.y}'\n")
    assert run(tmp_path, ["--py36-plus"], "x = '{!r}'.format(v)\n") == (
        1, "x = f'{v!r}'\n")


def test_set_literal_more_variants(tmp_path):
    """An empty ``set([])`` collapses to ``set()`` (NOT a ``{}`` dict), and a conditional set
    comprehension is rewritten like the others."""
    assert run(tmp_path, [], "x = set([])\n") == (1, "x = set()\n")
    assert run(tmp_path, [], "x = set([y for y in z if y])\n") == (
        1, "x = {y for y in z if y}\n")


# --------------------------------------------------------------------------- #
# More six rewrites                                                            #
# --------------------------------------------------------------------------- #

def test_six_value_helpers(tmp_path):
    """Small ``six`` value shims: ``six.u('x')`` -> ``'x'``; ``six.b('x')`` -> ``b'x'``;
    ``six.string_types`` -> ``str``."""
    assert run(tmp_path, [], "x = six.u('foo')\n") == (1, "x = 'foo'\n")
    assert run(tmp_path, [], "x = six.b('foo')\n") == (1, "x = b'foo'\n")
    assert run(tmp_path, [], "isinstance(x, six.string_types)\n") == (
        1, "isinstance(x, str)\n")


def test_six_structural_rewrites(tmp_path):
    """Structural ``six`` shims: ``@six.add_metaclass(M)`` becomes a ``metaclass=`` base;
    ``six.iteritems(d)`` -> ``d.items()``; a ``six.moves`` import that maps to a builtin is removed
    entirely; ``six.raise_from(e, c)`` -> ``raise e from c``."""
    assert run(tmp_path, [], "@six.add_metaclass(M)\nclass C:\n    pass\n") == (
        1, "class C(metaclass=M):\n    pass\n")
    assert run(tmp_path, [], "for k, v in six.iteritems(d):\n    pass\n") == (
        1, "for k, v in d.items():\n    pass\n")
    assert run(tmp_path, [], "from six.moves import range\n") == (1, "")
    assert run(tmp_path, [], "six.raise_from(exc, cause)\n") == (
        1, "raise exc from cause\n")


# --------------------------------------------------------------------------- #
# More version-gated typing rewrites                                          #
# --------------------------------------------------------------------------- #

def test_pep585_more_generics_py39(tmp_path):
    """``--py39-plus`` PEP 585 covers more generics than ``List``: ``typing.Dict[str, int]`` ->
    ``dict[str, int]`` and ``typing.Tuple[int, ...]`` -> ``tuple[int, ...]``."""
    src = ("from __future__ import annotations\nimport typing\n"
           "def f(x: typing.Dict[str, int], y: typing.Tuple[int, ...]) -> None: pass\n")
    out = ("from __future__ import annotations\nimport typing\n"
           "def f(x: dict[str, int], y: tuple[int, ...]) -> None: pass\n")
    assert run(tmp_path, ["--py39-plus"], src) == (1, out)


def test_pep604_nested_py310(tmp_path):
    """``--py310-plus`` handles a nested generic inside ``Optional``: ``Optional[List[int]]`` ->
    ``list[int] | None`` (the inner ``List`` is also rewritten, since py310 implies py39)."""
    src = ("from __future__ import annotations\nfrom typing import Optional, List\n"
           "def f() -> Optional[List[int]]: pass\n")
    out = ("from __future__ import annotations\nfrom typing import Optional, List\n"
           "def f() -> list[int] | None: pass\n")
    assert run(tmp_path, ["--py310-plus"], src) == (1, out)


def test_typing_text_py36(tmp_path):
    """``--py36-plus`` rewrites the ``typing.Text`` alias to ``str``."""
    src = ("from __future__ import annotations\nimport typing\n"
           "def f(x: typing.Text) -> None: pass\n")
    out = ("from __future__ import annotations\nimport typing\n"
           "def f(x: str) -> None: pass\n")
    assert run(tmp_path, ["--py36-plus"], src) == (1, out)


# --------------------------------------------------------------------------- #
# Round 2: more version-branch shapes, percent specs, six, f-string specs      #
# --------------------------------------------------------------------------- #

def test_version_branch_comparison_forms_py36(tmp_path):
    """Version-branch removal handles every comparison form, collapsing to whichever branch the
    target (py36) takes: ``> (3, 5)`` keeps the if; ``<= (3, 5)`` keeps the else; a ``< (3,)`` py2
    guard keeps the else; and the ``sys.version_info.major >= 3`` attribute form keeps the if."""
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info > (3, 5):\n    x = 1\nelse:\n    x = 2\n") == (
        1, "import sys\nx = 1\n")
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info <= (3, 5):\n    x = 1\nelse:\n    x = 2\n") == (
        1, "import sys\nx = 2\n")
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info < (3,):\n    x = 'py2'\nelse:\n    x = 'py3'\n") == (
        1, "import sys\nx = 'py3'\n")
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info.major >= 3:\n    x = 1\nelse:\n    x = 2\n") == (
        1, "import sys\nx = 1\n")


def test_version_branch_no_else_py36(tmp_path):
    """A version guard with NO else: when the guard is the taken branch (``>= (3, 6)``) its body is
    dedented in place; when it is the untaken branch (``< (3, 6)``) the whole `if` is removed."""
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info >= (3, 6):\n    x = 1\n    y = 2\n") == (
        1, "import sys\nx = 1\ny = 2\n")
    assert run(tmp_path, ["--py36-plus"],
               "import sys\nif sys.version_info < (3, 6):\n    x = 1\n") == (
        1, "import sys\n")


def test_percent_named_format_spec(tmp_path):
    """A mapping-form ``%`` conversion with a format spec carries the spec into the ``{}`` field:
    ``'%(a).2f' % {'a': v}`` -> ``'{a:.2f}'.format(a=v)``."""
    assert run(tmp_path, [], "x = '%(a).2f' % {'a': v}\n") == (
        1, "x = '{a:.2f}'.format(a=v)\n")


def test_six_more_rewrites(tmp_path):
    """More six shims: the ``@six.python_2_unicode_compatible`` decorator is dropped;
    ``six.moves.<name>`` attribute access maps to the builtin (``six.moves.range`` -> ``range``);
    ``six.viewitems(d)`` -> ``d.items()``; ``six.int2byte(7)`` -> ``bytes((7,))``;
    ``six.callable(x)`` -> ``callable(x)``."""
    assert run(tmp_path, [], "@six.python_2_unicode_compatible\nclass C:\n    pass\n") == (
        1, "class C:\n    pass\n")
    assert run(tmp_path, [], "x = six.moves.range(10)\n") == (1, "x = range(10)\n")
    assert run(tmp_path, [], "for k in six.viewitems(d):\n    pass\n") == (
        1, "for k in d.items():\n    pass\n")
    assert run(tmp_path, [], "x = six.int2byte(7)\n") == (1, "x = bytes((7,))\n")
    assert run(tmp_path, [], "if six.callable(x):\n    pass\n") == (
        1, "if callable(x):\n    pass\n")


def test_fstring_format_spec_and_multi_py36(tmp_path):
    """--py36-plus f-string conversion carries a format spec (``'{:>10}'.format(name)`` ->
    ``f'{name:>10}'``) and handles multiple named fields (``'{a}-{b}'.format(a=p, b=q)`` ->
    ``f'{p}-{q}'``)."""
    assert run(tmp_path, ["--py36-plus"], "x = '{:>10}'.format(name)\n") == (
        1, "x = f'{name:>10}'\n")
    assert run(tmp_path, ["--py36-plus"], "x = '{a}-{b}'.format(a=p, b=q)\n") == (
        1, "x = f'{p}-{q}'\n")


def test_combined_rewrites_py36(tmp_path):
    """A single --py36-plus pass applies several independent rewrites to one file at once: the
    ``set([...])`` literal, the ``sys.version_info`` branch, the explicit ``object`` base, the
    ``super(C, self)`` arguments, and the ``str.format`` -> f-string. The model must reproduce
    every one (and only those) to match byte-for-byte."""
    src = ("import sys\n"
           "x = set([1, 2])\n"
           "if sys.version_info < (3, 6):\n    y = 1\nelse:\n    y = 2\n"
           "class C(object):\n"
           "    def m(self):\n"
           "        super(C, self).m()\n"
           "        return '{}'.format(self.name)\n")
    out = ("import sys\n"
           "x = {1, 2}\n"
           "y = 2\n"
           "class C:\n"
           "    def m(self):\n"
           "        super().m()\n"
           "        return f'{self.name}'\n")
    assert run(tmp_path, ["--py36-plus"], src) == (1, out)
