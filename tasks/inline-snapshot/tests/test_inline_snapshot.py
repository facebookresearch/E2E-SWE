"""End-to-end tests for inline-snapshot.

inline-snapshot records expected values directly into the source code of your tests.
Its user-facing surface is the ``snapshot()`` object plus the ``--inline-snapshot=<flags>``
pytest option, which rewrites the test files in place.  Every test here drives the tool the
way a real user does: it writes a small project to a temporary directory, runs ``pytest``
on it in a **subprocess** with the relevant flag, and then inspects the (possibly rewritten)
source files and the created external files.

Driving the tool through a subprocess keeps the assertions in this file (not inside the
library), so the grade reflects what inline-snapshot actually produced.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_PYPROJECT = "[tool.inline-snapshot]\n"


class Run:
    """Result of one subprocess pytest run: return code, stdout, and every file in the
    project directory after the run (originals possibly rewritten, plus any created files).
    """

    def __init__(self, returncode, stdout, files):
        self.returncode = returncode
        self.stdout = stdout
        self.files = files  # name -> str (text) or bytes (binary)

    def text(self, name):
        value = self.files[name]
        assert isinstance(value, str), f"{name} is binary"
        return value


def run_inline_snapshot(files, args):
    """Write ``files`` into a temp project, run ``pytest <args>`` there as a subprocess,
    and return a :class:`Run` describing the resulting files.

    ``files`` maps a relative path to text (``str``) or binary (``bytes``) content.  A
    ``pyproject.toml`` enabling the ``[tool.inline-snapshot]`` section is added if absent.
    """
    if "pyproject.toml" not in files:
        files = {"pyproject.toml": DEFAULT_PYPROJECT, **files}

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name, content in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content)

        env = dict(os.environ)
        env["TERM"] = "unknown"
        env["COLUMNS"] = "80"
        for key in ("CI", "GITHUB_ACTIONS", "PYTEST_XDIST_WORKER"):
            env.pop(key, None)

        command = [sys.executable, "-m", "pytest", "-p", "no:randomly", "-q", *args]
        proc = subprocess.run(
            command, cwd=str(root), capture_output=True, text=True, env=env
        )

        result_files = {}
        for path in sorted(root.rglob("*")):
            rel = str(path.relative_to(root)).replace("\\", "/")
            if not path.is_file() or ".pytest_cache" in rel or rel.endswith(".pyc"):
                continue
            data = path.read_bytes()
            try:
                result_files[rel] = data.decode("utf-8")
            except UnicodeDecodeError:
                result_files[rel] = data

    return Run(proc.returncode, proc.stdout, result_files)


# ---------------------------------------------------------------------------
# create: turning empty snapshot() calls into recorded values
# ---------------------------------------------------------------------------


class TestCreate:
    def test_scalar_values(self):
        """``--inline-snapshot=create`` fills empty snapshots for scalar/atomic values,
        rendering each value as the code that reproduces it."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_values():\n"
            "    assert 3.14 == snapshot()\n"
            "    assert True == snapshot()\n"
            "    assert None == snapshot()\n"
            "    assert (1, 2) == snapshot()\n"
            "    assert b'x' == snapshot()\n"
            "    assert 'single' == snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_values():\n"
            "    assert 3.14 == snapshot(3.14)\n"
            "    assert True == snapshot(True)\n"
            "    assert None == snapshot(None)\n"
            "    assert (1, 2) == snapshot((1, 2))\n"
            "    assert b'x' == snapshot(b\"x\")\n"
            "    assert 'single' == snapshot(\"single\")\n"
        )

    def test_multiline_string(self):
        """A string containing newlines is recorded as a triple-quoted literal that
        preserves the exact characters (leading backslash continuation, trailing newline).
        """
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_text():\n"
            '    assert "a\\nb\\nc\\n" == snapshot()\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_text():\n"
            '    assert "a\\nb\\nc\\n" == snapshot("""\\\n'
            "a\n"
            "b\n"
            "c\n"
            '""")\n'
        )

    def test_collections_are_black_formatted(self):
        """Lists, dicts, and nested containers are recorded with black formatting
        (double-quoted strings, insertion order preserved)."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_collections():\n"
            "    assert [3, 1, 2] == snapshot()\n"
            "    assert {'b': 2, 'a': [1, 2, 3]} == snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_collections():\n"
            "    assert [3, 1, 2] == snapshot([3, 1, 2])\n"
            "    assert {'b': 2, 'a': [1, 2, 3]} == snapshot({\"b\": 2, \"a\": [1, 2, 3]})\n"
        )

    def test_create_with_operators(self):
        """create works for every snapshot operator: ``==`` records the value, ``<=``/``>=``
        record the bound, ``in`` records a one-element list, and ``snapshot()[key]``
        records a dict with that key."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_ops():\n"
            "    assert 5 == snapshot()\n"
            "    assert 5 <= snapshot()\n"
            "    assert 5 >= snapshot()\n"
            "    assert 5 in snapshot()\n"
            "    s = snapshot()\n"
            '    assert 5 == s["key"]\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_ops():\n"
            "    assert 5 == snapshot(5)\n"
            "    assert 5 <= snapshot(5)\n"
            "    assert 5 >= snapshot(5)\n"
            "    assert 5 in snapshot([5])\n"
            '    s = snapshot({"key": 5})\n'
            '    assert 5 == s["key"]\n'
        )


# ---------------------------------------------------------------------------
# fix / trim / update: changing already-recorded snapshots
# ---------------------------------------------------------------------------


class TestFixTrimUpdate:
    def test_fix_changed_values(self):
        """``--inline-snapshot=fix`` rewrites recorded values that no longer satisfy the
        comparison: ``==`` to the new value, ``<=`` to the new bound, ``in`` appends the
        missing element, and ``[key]`` updates the stored entry."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_ops():\n"
            "    assert 8 == snapshot(5)\n"
            "    assert 8 <= snapshot(5)\n"
            "    assert 8 in snapshot([5])\n"
            '    s = snapshot({"key": 5})\n'
            '    assert 8 == s["key"]\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=fix"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_ops():\n"
            "    assert 8 == snapshot(8)\n"
            "    assert 8 <= snapshot(8)\n"
            "    assert 8 in snapshot([5, 8])\n"
            '    s = snapshot({"key": 8})\n'
            '    assert 8 == s["key"]\n'
        )

    def test_trim_unused_parts(self):
        """``--inline-snapshot=trim`` makes snapshots more precise: it lowers a ``<=``
        bound to the largest value actually seen, drops unused elements from an ``in``
        list, and removes dict keys that are never read."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_ops():\n"
            "    assert 2 <= snapshot(8)\n"
            "    assert 8 in snapshot([5, 8])\n"
            '    s = snapshot({"key1": 1, "key2": 2})\n'
            '    assert 2 == s["key2"]\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=trim"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_ops():\n"
            "    assert 2 <= snapshot(2)\n"
            "    assert 8 in snapshot([8])\n"
            '    s = snapshot({"key2": 2})\n'
            '    assert 2 == s["key2"]\n'
        )

    def test_update_representation_only(self):
        """``--inline-snapshot=update`` changes only the *representation* of a value, not
        the value itself: a multi-line string becomes a triple-quoted literal and the
        evaluated expression ``4 + 1`` is replaced by its result ``5``."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_repr():\n"
            '    assert "a\\nb\\nc\\n" == snapshot("a\\nb\\nc\\n")\n'
            "    assert 5 == snapshot(4 + 1)\n"
        )
        run = run_inline_snapshot(
            {
                "pyproject.toml": "[tool.inline-snapshot]\nshow-updates=true\n",
                "test_a.py": source,
            },
            ["--inline-snapshot=update"],
        )
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_repr():\n"
            '    assert "a\\nb\\nc\\n" == snapshot("""\\\n'
            "a\n"
            "b\n"
            "c\n"
            '""")\n'
            "    assert 5 == snapshot(5)\n"
        )

    def test_flag_selects_only_its_category(self):
        """A flag applies only changes of its own category.  With just ``fix``, an
        incorrect value is corrected but an *empty* snapshot (a create change) is left
        untouched."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_mix():\n"
            "    assert 1 == snapshot()\n"
            "    assert 8 == snapshot(5)\n"
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=fix"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_mix():\n"
            "    assert 1 == snapshot()\n"
            "    assert 8 == snapshot(8)\n"
        )


# ---------------------------------------------------------------------------
# flags, reporting and lifecycle
# ---------------------------------------------------------------------------


class TestFlagsAndReporting:
    def test_disable_makes_snapshot_transparent(self):
        """``--inline-snapshot=disable`` turns ``snapshot(x)`` into a plain pass-through of
        ``x``: a matching comparison passes, a non-matching one fails as a normal
        assertion, and the source file is never rewritten."""
        passing = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    assert 3 == snapshot(3)\n"
        )
        run = run_inline_snapshot({"test_a.py": passing}, ["--inline-snapshot=disable"])
        assert run.returncode == 0
        assert run.text("test_a.py") == passing

        failing = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    assert 5 == snapshot(3)\n"
        )
        run = run_inline_snapshot({"test_a.py": failing}, ["--inline-snapshot=disable"])
        assert run.returncode != 0
        assert run.text("test_a.py") == failing

    def test_no_flag_workflow_and_roundtrip(self):
        """Without a flag inline-snapshot reports pending changes but does not apply them;
        applying ``create`` writes the value; and re-running afterwards passes cleanly with
        no further changes."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    assert 2 + 4 == snapshot()\n"
        )
        # No flag: a pending create is reported, file is untouched, run is not green.
        run = run_inline_snapshot({"test_a.py": source}, [])
        assert run.returncode != 0
        assert run.text("test_a.py") == source
        assert "These changes are not applied" in run.stdout

        # Apply create: file is rewritten with the value.
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        applied = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    assert 2 + 4 == snapshot(6)\n"
        )
        assert run.text("test_a.py") == applied

        # Re-running the applied file without a flag is green and changes nothing.
        run = run_inline_snapshot({"test_a.py": applied}, [])
        assert run.returncode == 0
        assert run.text("test_a.py") == applied

    def test_report_and_short_report_do_not_modify(self):
        """``report`` shows a per-category diff of the proposed changes without touching the
        file; ``short-report`` prints a one-line summary pointing at the flag to use.
        Neither applies anything."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    assert 1 == snapshot()\n"
            "    assert 2 <= snapshot(5)\n"
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=report"])
        assert run.returncode != 0
        assert run.text("test_a.py") == source
        assert "Create snapshots" in run.stdout
        assert "Trim snapshots" in run.stdout
        assert "snapshot(1)" in run.stdout  # proposed create value
        assert "snapshot(2)" in run.stdout  # proposed trim value
        assert "These changes are not applied" in run.stdout

        run = run_inline_snapshot(
            {"test_a.py": source}, ["--inline-snapshot=short-report"]
        )
        assert run.text("test_a.py") == source
        assert "one snapshot is missing a value" in run.stdout
        assert "--inline-snapshot=create" in run.stdout


# ---------------------------------------------------------------------------
# values that inline-snapshot must not manage
# ---------------------------------------------------------------------------


class TestUnmanagedValues:
    def test_is_keeps_dynamic_value(self):
        """A value wrapped in ``Is(...)`` is treated as developer-controlled: it is left
        unchanged when the surrounding snapshot is fixed, while a sibling literal is
        corrected normally."""
        source = (
            "from inline_snapshot import Is, snapshot\n"
            "\n"
            "def test_function():\n"
            '    for c in "abc":\n'
            '        assert [c, "correct"] == snapshot([Is(c), "wrong"])\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=fix"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import Is, snapshot\n"
            "\n"
            "def test_function():\n"
            '    for c in "abc":\n'
            '        assert [c, "correct"] == snapshot([Is(c), "correct"])\n'
        )

    def test_inner_snapshot_is_managed_separately(self):
        """A ``snapshot()`` used inside another snapshot is unmanaged within the outer one
        (its reference is preserved) but is itself fixed as an independent snapshot."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    inner = snapshot(5)\n"
            '    assert {"a": 8, "b": 8} == snapshot({"a": inner, "b": 5})\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=fix"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    inner = snapshot(8)\n"
            '    assert {"a": 8, "b": 8} == snapshot({"a": inner, "b": 8})\n'
        )

    def test_dirty_equals_is_used_for_now(self):
        """When a recorded value equals the current time, inline-snapshot records a
        ``dirty_equals.IsNow()`` expression (importing it) instead of a brittle timestamp,
        leaving stable siblings as plain values."""
        source = (
            "import datetime\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            '    assert {"when": datetime.datetime.now(), "id": 1} == snapshot()\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        rewritten = run.text("test_a.py")
        assert "from dirty_equals import IsNow" in rewritten
        assert 'snapshot({"when": IsNow(), "id": 1})' in rewritten


# ---------------------------------------------------------------------------
# the extra context managers
# ---------------------------------------------------------------------------


class TestExtra:
    def test_raises_records_exception(self):
        """``extra.raises`` records the formatted exception (``Type: message``) raised in
        its block, and records ``"<no exception>"`` when none is raised."""
        raised = (
            "from inline_snapshot.extra import raises\n"
            "\n"
            "def test_a():\n"
            "    with raises():\n"
            "        1 / 0\n"
        )
        run = run_inline_snapshot({"test_a.py": raised}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from inline_snapshot.extra import raises\n"
            "\n"
            "def test_a():\n"
            '    with raises("ZeroDivisionError: division by zero"):\n'
            "        1 / 0\n"
        )

        none = (
            "from inline_snapshot.extra import raises\n"
            "\n"
            "def test_a():\n"
            '    with raises("ValueError: boom"):\n'
            "        pass\n"
        )
        run = run_inline_snapshot({"test_a.py": none}, ["--inline-snapshot=fix"])
        assert run.text("test_a.py") == (
            "from inline_snapshot.extra import raises\n"
            "\n"
            "def test_a():\n"
            '    with raises("<no exception>"):\n'
            "        pass\n"
        )

    def test_prints_records_stdout_and_stderr(self):
        """``extra.prints`` records whatever was written to stdout and stderr inside its
        block as keyword snapshots."""
        source = (
            "import sys\n"
            "from inline_snapshot.extra import prints\n"
            "\n"
            "def test_a():\n"
            "    with prints():\n"
            '        print("hello world")\n'
            '        print("some error", file=sys.stderr)\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=fix"])
        assert run.text("test_a.py") == (
            "import sys\n"
            "from inline_snapshot.extra import prints\n"
            "\n"
            "def test_a():\n"
            '    with prints(stderr="some error\\n", stdout="hello world\\n"):\n'
            '        print("hello world")\n'
            '        print("some error", file=sys.stderr)\n'
        )

    def test_warns_records_warnings(self):
        """``extra.warns`` records the warnings emitted in its block; by default each is a
        ``"Category: message"`` string, with ``include_line=True`` each becomes a
        ``(line_number, message)`` tuple, and with ``include_file=True`` the file is included
        as the ``__file__`` reference."""
        plain = (
            "from warnings import warn\n"
            "from inline_snapshot.extra import warns\n"
            "\n"
            "def test_a():\n"
            "    with warns():\n"
            '        warn("problem one")\n'
            '        warn("problem two")\n'
        )
        run = run_inline_snapshot({"test_a.py": plain}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from warnings import warn\n"
            "from inline_snapshot.extra import warns\n"
            "\n"
            "def test_a():\n"
            '    with warns(["UserWarning: problem one", "UserWarning: problem two"]):\n'
            '        warn("problem one")\n'
            '        warn("problem two")\n'
        )

        with_line = (
            "from warnings import warn\n"
            "from inline_snapshot.extra import warns\n"
            "\n"
            "def test_a():\n"
            "    with warns(include_line=True):\n"
            '        warn("some problem")\n'
        )
        run = run_inline_snapshot(
            {"test_a.py": with_line}, ["--inline-snapshot=create"]
        )
        assert run.text("test_a.py") == (
            "from warnings import warn\n"
            "from inline_snapshot.extra import warns\n"
            "\n"
            "def test_a():\n"
            '    with warns([(6, "UserWarning: some problem")], include_line=True):\n'
            '        warn("some problem")\n'
        )

        with_file = (
            "from warnings import warn\n"
            "from inline_snapshot.extra import warns\n"
            "\n"
            "def test_a():\n"
            "    with warns(include_file=True):\n"
            '        warn("some problem")\n'
        )
        run = run_inline_snapshot(
            {"test_a.py": with_file}, ["--inline-snapshot=create"]
        )
        # include_file records the file as the __file__ reference (not a volatile path)
        assert run.text("test_a.py") == (
            "from warnings import warn\n"
            "from inline_snapshot.extra import warns\n"
            "\n"
            "def test_a():\n"
            '    with warns([(__file__, "UserWarning: some problem")], include_file=True):\n'
            '        warn("some problem")\n'
        )


# ---------------------------------------------------------------------------
# snapshot_arg, adapters and external storage
# ---------------------------------------------------------------------------


class TestSnapshotArgAndAdapters:
    def test_snapshot_arg_records_call_site(self):
        """``snapshot_arg(param)`` records the value of a function parameter by rewriting
        the *call site* to pass that value (positionally for the first argument, by keyword
        otherwise)."""
        source = (
            "from inline_snapshot import snapshot_arg\n"
            "\n"
            "def get_stats(numbers, expected_sum=..., expected_max=...):\n"
            "    assert sum(numbers) == snapshot_arg(expected_sum)\n"
            "    assert max(numbers) == snapshot_arg(expected_max)\n"
            "\n"
            "def test_example():\n"
            "    get_stats([1, 2, 3])\n"
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        assert run.text("test_a.py") == (
            "from inline_snapshot import snapshot_arg\n"
            "\n"
            "def get_stats(numbers, expected_sum=..., expected_max=...):\n"
            "    assert sum(numbers) == snapshot_arg(expected_sum)\n"
            "    assert max(numbers) == snapshot_arg(expected_max)\n"
            "\n"
            "def test_example():\n"
            "    get_stats([1, 2, 3], expected_sum=6, expected_max=3)\n"
        )

    def test_dataclass_adapter(self):
        """Dataclasses are rendered as keyword constructor calls when created, and on fix
        only the field whose value changed is rewritten — the others are preserved."""
        create_src = (
            "from dataclasses import dataclass\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "@dataclass\n"
            "class Point:\n"
            "    x: int\n"
            "    y: int\n"
            "\n"
            "def test_a():\n"
            "    assert Point(1, 2) == snapshot()\n"
        )
        run = run_inline_snapshot(
            {"test_a.py": create_src}, ["--inline-snapshot=create"]
        )
        assert (
            run.text("test_a.py")
            .rstrip("\n")
            .endswith("    assert Point(1, 2) == snapshot(Point(x=1, y=2))")
        )

        fix_src = (
            "from dataclasses import dataclass\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "@dataclass\n"
            "class Point:\n"
            "    x: int\n"
            "    y: int\n"
            "\n"
            "def test_a():\n"
            "    assert Point(1, 9) == snapshot(Point(x=1, y=2))\n"
        )
        run = run_inline_snapshot({"test_a.py": fix_src}, ["--inline-snapshot=fix"])
        assert (
            run.text("test_a.py")
            .rstrip("\n")
            .endswith("    assert Point(1, 9) == snapshot(Point(x=1, y=9))")
        )

    def test_pydantic_and_attrs_adapters(self):
        """The constructor-call adapter is not limited to dataclasses: a pydantic
        ``BaseModel`` and an ``attrs`` class are also recorded as keyword constructor calls,
        and on ``fix`` only the field whose value changed is rewritten."""
        pyd_create = (
            "from pydantic import BaseModel\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "class M(BaseModel):\n"
            "    x: int\n"
            "    y: int\n"
            "\n"
            "def test_a():\n"
            "    assert M(x=1, y=2) == snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": pyd_create}, ["--inline-snapshot=create"])
        assert (
            run.text("test_a.py")
            .rstrip("\n")
            .endswith("    assert M(x=1, y=2) == snapshot(M(x=1, y=2))")
        )

        pyd_fix = (
            "from pydantic import BaseModel\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "class M(BaseModel):\n"
            "    x: int\n"
            "    y: int\n"
            "\n"
            "def test_a():\n"
            "    assert M(x=1, y=9) == snapshot(M(x=1, y=2))\n"
        )
        run = run_inline_snapshot({"test_a.py": pyd_fix}, ["--inline-snapshot=fix"])
        assert (
            run.text("test_a.py")
            .rstrip("\n")
            .endswith("    assert M(x=1, y=9) == snapshot(M(x=1, y=9))")
        )

        attrs_create = (
            "import attrs\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "@attrs.define\n"
            "class P:\n"
            "    a: int\n"
            "    b: int\n"
            "\n"
            "def test_a():\n"
            "    assert P(1, 2) == snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": attrs_create}, ["--inline-snapshot=create"])
        assert (
            run.text("test_a.py")
            .rstrip("\n")
            .endswith("    assert P(1, 2) == snapshot(P(a=1, b=2))")
        )


class TestExternalStorage:
    UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    def test_outsource_creates_external_file(self):
        """``outsource(value)`` stores the value in an external file and records an
        ``external("uuid:....txt")`` reference (importing ``external``); the external file
        holds the original text."""
        source = (
            "from inline_snapshot import outsource, snapshot\n"
            "\n"
            "def test_a():\n"
            '    assert outsource("payload data") == snapshot()\n'
        )
        run = run_inline_snapshot({"test_a.py": source}, ["--inline-snapshot=create"])
        rewritten = run.text("test_a.py")
        match = re.search(
            r'snapshot\(external\("uuid:(' + self.UUID_RE + r')\.txt"\)\)', rewritten
        )
        assert match, rewritten
        assert "from inline_snapshot import" in rewritten and "external" in rewritten

        uuid = match.group(1)
        external_files = {
            name: content
            for name, content in run.files.items()
            if uuid in name and name.endswith(".txt")
        }
        assert len(external_files) == 1, run.files.keys()
        assert next(iter(external_files.values())) == "payload data"

    def test_external_protocols_and_formats(self):
        """``external()`` placed in a tests file picks the storage format from the value
        type: strings use ``.txt``, bytes use ``.bin``, and structured data uses ``.json``;
        each external file is created with the corresponding serialized content."""
        source = (
            "from inline_snapshot import external\n"
            "\n"
            "def test_a():\n"
            '    assert "some text" == external()\n'
            '    assert b"raw bytes" == external()\n'
            '    assert ["json", "data"] == external()\n'
        )
        run = run_inline_snapshot(
            {"tests/test_a.py": source}, ["--inline-snapshot=create"]
        )
        rewritten = run.text("tests/test_a.py")
        assert re.search(r'external\("uuid:' + self.UUID_RE + r'\.txt"\)', rewritten)
        assert re.search(r'external\("uuid:' + self.UUID_RE + r'\.bin"\)', rewritten)
        assert re.search(r'external\("uuid:' + self.UUID_RE + r'\.json"\)', rewritten)

        by_suffix = {}
        for name, content in run.files.items():
            if "__inline_snapshot__" in name:
                by_suffix[name.rsplit(".", 1)[-1]] = content
        assert by_suffix["txt"] == "some text"
        assert by_suffix["bin"] in (b"raw bytes", "raw bytes")
        json_text = by_suffix["json"]
        if isinstance(json_text, bytes):
            json_text = json_text.decode("utf-8")
        assert json_text.replace(" ", "").replace("\n", "") == '["json","data"]'

    def test_hash_storage_protocol(self):
        """With ``default-storage = "hash"`` configured, ``external()`` uses the ``hash:``
        protocol instead of ``uuid:``: the inline reference becomes
        ``external("hash:<prefix>*.<suffix>")`` where ``<prefix>`` is the first 12 hex chars
        of the SHA-256 of the content, and the external file (named by the full SHA-256) holds
        the value."""
        import hashlib

        source = (
            "from inline_snapshot import external\n"
            "\n"
            "def test_a():\n"
            '    assert "hello" == external()\n'
        )
        run = run_inline_snapshot(
            {
                "pyproject.toml": '[tool.inline-snapshot]\ndefault-storage="hash"\n',
                "tests/test_a.py": source,
            },
            ["--inline-snapshot=create"],
        )
        rewritten = run.text("tests/test_a.py")
        match = re.search(r'external\("hash:([0-9a-f]{12})\*\.txt"\)', rewritten)
        assert match, rewritten
        expected_prefix = hashlib.sha256(b"hello").hexdigest()[:12]
        assert match.group(1) == expected_prefix

        external_files = {
            name: content
            for name, content in run.files.items()
            if name.endswith(".txt") and "external" in name
        }
        assert len(external_files) == 1, run.files.keys()
        name, content = next(iter(external_files.items()))
        assert content == "hello"
        assert name.rsplit("/", 1)[-1].startswith(expected_prefix)

    def test_external_file_explicit_path(self):
        """``external_file(path)`` stores the value at an explicit path (relative to the test
        file) instead of an auto-generated name: the call site keeps the path as written and
        the file is created with the value."""
        source = (
            "from inline_snapshot import external_file\n"
            "\n"
            "def test_a():\n"
            "    assert 'stored text' == external_file('data/value.txt')\n"
        )
        run = run_inline_snapshot({"tests/test_a.py": source}, ["--inline-snapshot=create"])
        assert "external_file('data/value.txt')" in run.text("tests/test_a.py")
        assert run.files["tests/data/value.txt"] == "stored text"


# ---------------------------------------------------------------------------
# aggregation across multiple comparisons of one snapshot
# ---------------------------------------------------------------------------


class TestAggregation:
    def test_aggregate_across_runs(self):
        """A single ``snapshot()`` that is compared in several executions (e.g. a parametrized
        test) records ONE value that satisfies every comparison: ``==`` records the common
        value, ``<=`` records the maximum value seen, and ``in`` records the union of all
        tested members."""
        eq = (
            "import pytest\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "@pytest.mark.parametrize('x', [5, 5, 5])\n"
            "def test_a(x):\n"
            "    assert x == snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": eq}, ["--inline-snapshot=create"])
        assert run.text("test_a.py").rstrip("\n").endswith("    assert x == snapshot(5)")

        le = (
            "import pytest\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "@pytest.mark.parametrize('x', [1, 2, 3])\n"
            "def test_a(x):\n"
            "    assert x <= snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": le}, ["--inline-snapshot=create"])
        assert run.text("test_a.py").rstrip("\n").endswith("    assert x <= snapshot(3)")

        member = (
            "import pytest\n"
            "from inline_snapshot import snapshot\n"
            "\n"
            "@pytest.mark.parametrize('x', [1, 2])\n"
            "def test_a(x):\n"
            "    assert x in snapshot()\n"
        )
        run = run_inline_snapshot({"test_a.py": member}, ["--inline-snapshot=create"])
        assert run.text("test_a.py").rstrip("\n").endswith("    assert x in snapshot([1, 2])")


# ---------------------------------------------------------------------------
# configuration: default-flags
# ---------------------------------------------------------------------------


class TestConfiguration:
    def test_default_flags_config(self):
        """``[tool.inline-snapshot] default-flags`` sets the categories applied when pytest is
        run WITHOUT an explicit ``--inline-snapshot`` option: with ``default-flags=["create"]``
        a plain ``pytest`` run fills empty snapshots in place."""
        source = (
            "from inline_snapshot import snapshot\n"
            "\n"
            "def test_a():\n"
            "    assert 2 + 4 == snapshot()\n"
        )
        run = run_inline_snapshot(
            {
                "pyproject.toml": '[tool.inline-snapshot]\ndefault-flags=["create"]\n',
                "test_a.py": source,
            },
            [],
        )
        assert run.text("test_a.py").rstrip("\n").endswith("    assert 2 + 4 == snapshot(6)")
