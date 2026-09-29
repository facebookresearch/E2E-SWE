"""End-to-end tests for git-code-debt.

Every test drives the CLI (`git-code-debt-generate`, `git-code-debt-list-metrics`,
`git-code-debt-server`) via subprocess or the Flask app via `flask.test_client()`.
The only internal imports are the plugin API surface (`SimpleLineCounterBase`) that
custom-metric authors must extend — everything else is user-facing behavior.
"""
from __future__ import annotations

import json as _json
import os
import pathlib
import re
import sqlite3
import subprocess
import textwrap
from unittest import mock as _mock

import pytest
import yaml


# --- helpers ---------------------------------------------------------------------------------


def _git(cwd: pathlib.Path, *args: str, env: dict | None = None) -> None:
    e = dict(os.environ)
    e["GIT_AUTHOR_NAME"] = "T"
    e["GIT_AUTHOR_EMAIL"] = "t@example.com"
    e["GIT_COMMITTER_NAME"] = "T"
    e["GIT_COMMITTER_EMAIL"] = "t@example.com"
    if env:
        e.update(env)
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, env=e,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _init_repo(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "commit.gpgsign", "false")


def _commit(
    repo: pathlib.Path, name: str, content: bytes | str, msg: str,
) -> str:
    p = repo / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        p.write_text(content)
    else:
        p.write_bytes(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()


def _commit_delete(repo: pathlib.Path, name: str, msg: str) -> str:
    _git(repo, "rm", "-q", name)
    _git(repo, "commit", "-q", "-m", msg)
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()


def _write_config(
    cfg_path: pathlib.Path,
    repo: pathlib.Path,
    db: pathlib.Path,
    **extras,
) -> pathlib.Path:
    d: dict = {"repo": str(repo), "database": str(db)}
    d.update(extras)
    cfg_path.write_text(yaml.safe_dump(d))
    return cfg_path


def _run_generate(cfg: pathlib.Path, env: dict | None = None) -> None:
    e = dict(os.environ)
    if env:
        e.update(env)
    subprocess.run(
        ["git-code-debt-generate", "-C", str(cfg), "-j", "1"],
        check=True, env=e, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def _run_list_metrics(cfg: pathlib.Path, extra_args: list[str] | None = None) -> str:
    argv = ["git-code-debt-list-metrics", "-C", str(cfg)]
    if extra_args:
        argv.extend(extra_args)
    proc = subprocess.run(
        argv, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return proc.stdout.decode()


def _running_value(db: pathlib.Path, sha: str, metric_name: str) -> int | None:
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT running_value FROM metric_data "
            "INNER JOIN metric_names ON metric_data.metric_id = metric_names.id "
            "WHERE sha = ? AND name = ?",
            (sha, metric_name),
        ).fetchone()
    return row[0] if row else None


def _change_value(db: pathlib.Path, sha: str, metric_name: str) -> int | None:
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT value FROM metric_changes "
            "INNER JOIN metric_names ON metric_changes.metric_id = metric_names.id "
            "WHERE sha = ? AND name = ?",
            (sha, metric_name),
        ).fetchone()
    return row[0] if row else None


def _metric_names(db: pathlib.Path) -> set[str]:
    with sqlite3.connect(str(db)) as conn:
        return {n for n, in conn.execute("SELECT name FROM metric_names")}


def _prep_server_db(tmp_path: pathlib.Path) -> pathlib.Path:
    """Seed a small SQLite DB via git-code-debt-generate for server tests."""
    repo = tmp_path / "srv_repo"
    _init_repo(repo)
    _commit(repo, "a.py", "l1\nl2\nl3\n", "c1")
    _commit(repo, "b.py", "l4\nl5\n", "c2")
    db = tmp_path / "srv.db"
    cfg = _write_config(tmp_path / "srv_cfg.yaml", repo, db)
    _run_generate(cfg)
    return db


def _build_server_client(tmp_path: pathlib.Path, db_path: pathlib.Path,
                         config_overrides: dict | None = None):
    """Return (client, patches) with a Config built from the given overrides."""
    from git_code_debt.server.app import app, AppContext
    from git_code_debt.server.metric_config import Config

    base = {
        "Groups": [{"All": {"metric_expressions": [".*"]}}],
        "ColorOverrides": [],
        "CommitLinks": {"View": "https://ex.com/{sha}"},
        "WidgetMetrics": {"TotalLinesOfCode": {}},
    }
    if config_overrides:
        base.update(config_overrides)
    config = Config.from_data(base)
    ctx1 = _mock.patch.object(AppContext, "database_path", str(db_path))
    ctx2 = _mock.patch.object(AppContext, "config", config)
    ctx1.start()
    ctx2.start()
    return app.test_client(), (ctx1, ctx2)


def _release_server(patches) -> None:
    for p in patches:
        p.stop()


def _delta_row_value(html: str, metric_name: str) -> int | None:
    """Return the integer delta rendered in the cell next to `metric_name`, or None.

    Anchors on the exact name (so `TotalLinesOfCode` never matches the `_python` variant) and
    requires the delta in the adjacent table cell. Cell attributes and an inline link around the
    name are not pinned by the spec, so both are tolerated. Shared by the `/commit/<sha>` and
    `/widget/data` assertions, which the spec gives the same row shape.
    """
    m = re.search(
        r"<t[hd][^>]*>\s*(?:<a[^>]*>\s*)?" + re.escape(metric_name)
        + r"\s*(?:</a>\s*)?</t[hd]>\s*<td[^>]*>\s*(-?\d+)\s*</td>",
        html, re.S,
    )
    return int(m.group(1)) if m else None


# =====================================================================================
# 1. Generate CLI — schema + incremental semantics
# =====================================================================================


def test_creates_database_and_schema(tmp_path):
    """CLI creates the DB with the exact three-table schema + PKs."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "init")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    assert db.exists()
    with sqlite3.connect(str(db)) as conn:
        tables = {
            n for n, in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'",
            )
        }
        assert {"metric_names", "metric_data", "metric_changes"} <= tables

        # metric_names: id is PK.
        cols = {r[1]: (r[2], r[5]) for r in conn.execute("PRAGMA table_info(metric_names)")}
        assert set(cols) >= {"id", "name", "has_data", "description"}
        assert cols["id"][1] == 1

        # metric_data: composite PK (sha, metric_id).
        md = {r[1]: (r[2], r[5]) for r in conn.execute("PRAGMA table_info(metric_data)")}
        assert set(md) >= {"sha", "metric_id", "timestamp", "running_value"}
        assert {n for n, (_, pk) in md.items() if pk > 0} == {"sha", "metric_id"}

        # metric_changes: composite PK (sha, metric_id).
        mc = {r[1]: (r[2], r[5]) for r in conn.execute("PRAGMA table_info(metric_changes)")}
        assert set(mc) >= {"sha", "metric_id", "value"}
        assert {n for n, (_, pk) in mc.items() if pk > 0} == {"sha", "metric_id"}


def test_default_metric_names_registered(tmp_path):
    """metric_names is populated at init with every built-in class name plus parametric samples."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "init")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    names = _metric_names(db)
    for expected in (
        "BinaryFileCount", "SymlinkCount", "SubmoduleCount", "PythonImportCount",
        "CheetahTemplateImportCount", "TODOCount", "Python__init__LineCount",
        "TotalLinesOfCode", "TotalCurseWords",
    ):
        assert expected in names, f"{expected} missing from metric_names"
    # A couple of parametric variants must also appear.
    assert "TotalLinesOfCode_python" in names
    assert "TotalCurseWords_python" in names


def test_rerun_is_idempotent(tmp_path):
    """Rerunning with no new commits preserves row counts AND contents exactly."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "c1")
    _commit(repo, "b.py", "y = 2\n", "c2")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    def _snapshot(conn):
        return {
            "metric_names": sorted(conn.execute(
                "SELECT id, name, has_data, description FROM metric_names").fetchall()),
            "metric_data": sorted(conn.execute(
                "SELECT sha, metric_id, timestamp, running_value FROM metric_data").fetchall()),
            "metric_changes": sorted(conn.execute(
                "SELECT sha, metric_id, value FROM metric_changes").fetchall()),
        }

    with sqlite3.connect(str(db)) as conn:
        before = _snapshot(conn)
    _run_generate(cfg)
    with sqlite3.connect(str(db)) as conn:
        after = _snapshot(conn)

    assert len(before["metric_data"]) > 0
    assert before == after


def test_incremental_run_only_new_commits_resumes_running_totals(tmp_path):
    """Incremental run adds only new-commit rows AND resumes running values from prior state."""
    repo = tmp_path / "r"
    _init_repo(repo)
    sha1 = _commit(repo, "a.py", "l1\nl2\nl3\n", "c1")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    assert _running_value(db, sha1, "TotalLinesOfCode") == 3
    with sqlite3.connect(str(db)) as conn:
        before_shas = conn.execute("SELECT COUNT(DISTINCT sha) FROM metric_data").fetchone()[0]

    new_sha = _commit(repo, "b.py", "l4\nl5\n", "c2")
    _run_generate(cfg)

    with sqlite3.connect(str(db)) as conn:
        after_shas = conn.execute("SELECT COUNT(DISTINCT sha) FROM metric_data").fetchone()[0]
    assert after_shas == before_shas + 1

    # Resume: new commit's running_value must be prior + delta (not restart at delta).
    assert _running_value(db, sha1, "TotalLinesOfCode") == 3
    assert _running_value(db, new_sha, "TotalLinesOfCode") == 5
    assert _change_value(db, new_sha, "TotalLinesOfCode") == 2


def test_metric_names_catalog_stable_across_incremental_runs(tmp_path):
    """metric_names is populated ONCE at DB init; incremental runs don't insert new/dup rows."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "c1")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    with sqlite3.connect(str(db)) as conn:
        first = sorted(conn.execute("SELECT name FROM metric_names").fetchall())

    # Add commits that introduce new file-type-parametric metric names in the walk.
    _commit(repo, "b.md", "m1\nm2\n", "c2")
    _commit(repo, "c.yaml", "k: v\n", "c3")
    _run_generate(cfg)

    with sqlite3.connect(str(db)) as conn:
        second = sorted(conn.execute("SELECT name FROM metric_names").fetchall())
        distinct = conn.execute(
            "SELECT COUNT(DISTINCT name), COUNT(*) FROM metric_names").fetchone()
    assert distinct[0] == distinct[1], "metric_names has duplicate name entries"
    assert first == second, "metric_names must be populated once at init"


# =====================================================================================
# 2. Built-in metric parsers — bundled by concern
# =====================================================================================


def test_line_based_counters_todo_imports_init(tmp_path):
    """One repo exercises TODOCount, PythonImportCount, Python__init__LineCount together."""
    repo = tmp_path / "r"
    _init_repo(repo)
    # .py file with TODOs, imports.
    sha1 = _commit(
        repo, "a.py",
        "import os\nfrom sys import path\n# TODO one\nx = 1\n# TODO two\n",
        "c1",
    )
    # __init__.py contributes to Python__init__LineCount.
    _commit(repo, "pkg/__init__.py", "a = 1\nb = 2\nc = 3\n", "init")
    # Non-py file: `import os` must NOT count for PythonImportCount.
    sha3 = _commit(repo, "notes.txt", "import os\n", "notes")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    # After c1: 2 TODOs, 2 imports.
    assert _running_value(db, sha1, "TODOCount") == 2
    assert _running_value(db, sha1, "PythonImportCount") == 2
    # After all commits: 3 __init__.py lines; imports unchanged (txt doesn't count).
    assert _running_value(db, sha3, "Python__init__LineCount") == 3
    assert _running_value(db, sha3, "PythonImportCount") == 2


def test_cheetah_template_imports_only_in_tmpl(tmp_path):
    """CheetahTemplateImportCount counts `#`-prefixed import lines in .tmpl only."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(
        repo, "page.tmpl",
        "#import os\n#from sys import path\n<html>hi</html>\n",
        "tmpl",
    )
    sha = _commit(repo, "code.py", "import os\nfrom sys import path\n", "py")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    assert _running_value(db, sha, "CheetahTemplateImportCount") == 2
    # Sanity: the .py imports don't leak into the Cheetah counter.
    assert _running_value(db, sha, "PythonImportCount") == 2


def test_special_file_counters_binary_symlink_submodule(tmp_path):
    """Binary + symlink + submodule adds/deletes/combined-in-one-commit all count independently."""
    # Inner repo to be added as a submodule.
    inner = tmp_path / "inner"
    _init_repo(inner)
    _commit(inner, "readme.txt", "hi\n", "inner init")

    repo = tmp_path / "outer"
    _init_repo(repo)
    _commit(repo, "target.txt", "hi\n", "prep")  # so symlink has a target

    # Combined commit: python file + binary + symlink all together.
    (repo / "a.py").write_text("x = 1\ny = 2\n")
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    (repo / "logo.png").write_bytes(png)
    os.symlink("target.txt", str(repo / "link"))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "combined")
    sha_combined = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    # Add submodule.
    inner_url = f"file://{inner}"
    _git(repo, "-c", "protocol.file.allow=always",
         "submodule", "add", "-q", inner_url, "inner")
    _git(repo, "commit", "-q", "-m", "add submodule")
    sha_sub_add = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    # Delete binary + symlink + submodule.
    _git(repo, "rm", "-q", "logo.png")
    _git(repo, "rm", "-q", "link")
    _git(repo, "rm", "-q", "inner")
    _git(repo, "commit", "-q", "-m", "delete specials")
    sha_del = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo=repo, db=db)
    _run_generate(cfg)

    # Combined commit: each metric counted independently.
    assert _change_value(db, sha_combined, "BinaryFileCount") == 1
    assert _change_value(db, sha_combined, "SymlinkCount") == 1
    assert _change_value(db, sha_combined, "TotalLinesOfCode") == 2  # only .py lines

    # After submodule add: +1 submodule.
    assert _running_value(db, sha_sub_add, "SubmoduleCount") == 1
    assert _running_value(db, sha_sub_add, "BinaryFileCount") == 1
    assert _running_value(db, sha_sub_add, "SymlinkCount") == 1

    # After delete-all: everything back to 0.
    assert _running_value(db, sha_del, "BinaryFileCount") == 0
    assert _running_value(db, sha_del, "SymlinkCount") == 0
    assert _running_value(db, sha_del, "SubmoduleCount") == 0


def test_parametric_per_tag_metrics_across_languages(tmp_path):
    """TotalLinesOfCode_<tag> emits for each language + generic tags excluded + unknown sentinel."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "app.js", "console.log(1);\nconsole.log(2);\n", "js")  # 2 js
    _commit(repo, "style.css", "a { color: red; }\n", "css")              # 1 css
    _commit(repo, "conf.yaml", "k1: v1\nk2: v2\nk3: v3\n", "yaml")        # 3 yaml
    _commit(repo, "README.md", "line1\nline2\n", "md")                    # 2 md
    sha_unknown = _commit(repo, "data.zzq", "l1\nl2\nl3\n", "unk")        # 3 unknown

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    names = _metric_names(db)

    # Per-language parametric metrics exist.
    for tag in ("javascript", "css", "yaml", "markdown"):
        assert f"TotalLinesOfCode_{tag}" in names

    # Unknown-tag sentinel emits for unrecognized extensions.
    assert "TotalLinesOfCode_unknown" in names
    assert _running_value(db, sha_unknown, "TotalLinesOfCode_unknown") == 3

    # Values.
    assert _running_value(db, sha_unknown, "TotalLinesOfCode_javascript") == 2
    assert _running_value(db, sha_unknown, "TotalLinesOfCode_css") == 1
    assert _running_value(db, sha_unknown, "TotalLinesOfCode_yaml") == 3
    assert _running_value(db, sha_unknown, "TotalLinesOfCode_markdown") == 2

    # Generic tags MUST be excluded from parametric metric names.
    for excluded in ("text", "binary", "file", "symlink", "directory",
                     "executable", "non-executable"):
        assert f"TotalLinesOfCode_{excluded}" not in names, (
            f"generic tag {excluded} must be excluded from parametric metrics"
        )
        assert f"TotalCurseWords_{excluded}" not in names


def test_line_delta_arithmetic_within_commit_and_rename(tmp_path):
    """Deltas are (added - removed) per commit; rename produces net-zero delta preserving totals."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "l1\nl2\nl3\nl4\nl5\n", "c1")           # +5
    # Modify: remove 5, add 3 → net delta -2.
    sha2 = _commit(repo, "a.py", "n1\nn2\nn3\n", "c2")            # 5 → 3

    # Pure rename (same content, new filename).
    _git(repo, "mv", "a.py", "b.py")
    _git(repo, "commit", "-q", "-m", "rename")
    sha_rename = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    # c2: net delta = -2 (added 3 - removed 5); running total 5 → 3.
    assert _change_value(db, sha2, "TotalLinesOfCode") == -2
    assert _running_value(db, sha2, "TotalLinesOfCode") == 3

    # Rename: net delta = 0 (either omitted from metric_changes or recorded as 0).
    rn_delta = _change_value(db, sha_rename, "TotalLinesOfCode")
    assert rn_delta in (None, 0), f"rename must be net-zero, got {rn_delta}"
    # Strong invariant: running total unchanged across rename.
    assert _running_value(db, sha_rename, "TotalLinesOfCode") == 3


def test_curse_words_case_sensitive_and_tokenized(tmp_path):
    """Curse-word matching is byte-exact (case-sensitive) and whitespace-tokenized."""
    repo = tmp_path / "r"
    _init_repo(repo)
    # Lowercase tokens match. Uppercase tokens do NOT (bundled word list is lowercase).
    sha = _commit(
        repo, "notes.txt",
        "crap damn CRAP DAMN hello\n",
        "curse",
    )

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    # Two lowercase tokens counted; two uppercase tokens NOT counted.
    assert _running_value(db, sha, "TotalCurseWords") == 2


def test_curse_words_parametric_by_file_type(tmp_path):
    """TotalCurseWords_<tag> emits per file type independently."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "# crap\n", "py-curse")   # 1 in python
    sha = _commit(repo, "b.md", "damn\n", "md-curse")  # 1 in markdown

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    assert _running_value(db, sha, "TotalCurseWords") == 2
    assert _running_value(db, sha, "TotalCurseWords_python") == 1
    assert _running_value(db, sha, "TotalCurseWords_markdown") == 1


# =====================================================================================
# 3. Plugin discovery + config semantics
# =====================================================================================


def test_third_party_metric_package_discovery(tmp_path):
    """metric_package_names discovers classes recursively AND skips __metric__=False subclasses."""
    pkg_root = tmp_path / "pkg"
    (pkg_root / "my_metrics" / "sub").mkdir(parents=True)
    (pkg_root / "my_metrics" / "__init__.py").write_text("")
    (pkg_root / "my_metrics" / "sub" / "__init__.py").write_text("")
    # A nested concrete metric and an abstract intermediate.
    (pkg_root / "my_metrics" / "sub" / "deep.py").write_text(textwrap.dedent("""
        from git_code_debt.metrics.base import SimpleLineCounterBase

        class AbstractIntermediate(SimpleLineCounterBase):
            __metric__ = False
            def line_matches_metric(self, line, file_diff_stat):
                return True

        class DeeplyNestedCounter(AbstractIntermediate):
            \"\"\"Counts every line.\"\"\"
            pass
    """))

    repo = tmp_path / "r"
    _init_repo(repo)
    sha = _commit(repo, "a.py", "l1\nl2\nl3\n", "c1")

    db = tmp_path / "db.db"
    cfg = _write_config(
        tmp_path / "cfg.yaml", repo, db,
        skip_default_metrics=True,
        metric_package_names=["my_metrics"],
    )
    _run_generate(cfg, env={"PYTHONPATH": str(pkg_root)})

    names = _metric_names(db)
    assert "DeeplyNestedCounter" in names, "nested subclass must be discovered"
    assert "AbstractIntermediate" not in names, "__metric__=False must be skipped"
    assert _running_value(db, sha, "DeeplyNestedCounter") == 3


def test_skip_default_metrics_produces_empty_catalog(tmp_path):
    """skip_default_metrics=true with no third-party packages → empty metric_names + metric_data."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "c1")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db, skip_default_metrics=True)
    _run_generate(cfg)

    with sqlite3.connect(str(db)) as conn:
        n = conn.execute("SELECT COUNT(*) FROM metric_names").fetchone()[0]
        d = conn.execute("SELECT COUNT(*) FROM metric_data").fetchone()[0]
    assert n == 0 and d == 0


def test_exclude_regex_bytes_search_semantics(tmp_path):
    """`exclude` is a byte-string regex applied with re.search to the diff-header path."""
    repo = tmp_path / "r"
    _init_repo(repo)
    # 'foo' appears mid-path: re.search matches, re.match does not. Must be excluded.
    _commit(repo, "src/foo/x.py", "a\nb\nc\n", "middle-foo")
    _commit(repo, "src/bar/y.py", "d\ne\n", "bar")
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db, exclude=r"foo")
    _run_generate(cfg)

    # Only src/bar/y.py counts (2 lines); src/foo/x.py excluded.
    assert _running_value(db, sha, "TotalLinesOfCode") == 2


def test_has_data_flip_and_zero_signal_row_semantics(tmp_path):
    """has_data flips 0→1 on first non-zero emission; zero-signal metrics get NO metric_data rows."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "import os\n# TODO fix\nx = 1\n", "c1")

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    with sqlite3.connect(str(db)) as conn:
        rows = dict(conn.execute("SELECT name, has_data FROM metric_names"))
        # metric_data must be empty for zero-signal metrics.
        for name in ("BinaryFileCount", "SymlinkCount", "SubmoduleCount"):
            assert rows.get(name) == 0, f"{name} has_data must remain 0"
            n = conn.execute(
                "SELECT COUNT(*) FROM metric_data "
                "INNER JOIN metric_names ON metric_data.metric_id = metric_names.id "
                "WHERE name = ?", (name,),
            ).fetchone()[0]
            assert n == 0, f"{name} zero-signal metric must have no metric_data rows"

    for name in ("TotalLinesOfCode", "PythonImportCount", "TODOCount"):
        assert rows.get(name) == 1, f"{name} has_data must flip to 1 on first emission"


def test_metric_data_timestamp_matches_git_committer_epoch(tmp_path):
    """metric_data.timestamp is the git committer epoch, not wall-clock or author time."""
    repo = tmp_path / "r"
    _init_repo(repo)
    fixed_epoch = 1700000000  # 2023-11-14 UTC
    _git(
        repo, "commit", "--allow-empty", "-q", "-m", "empty",
        env={
            "GIT_AUTHOR_DATE": f"@{fixed_epoch} +0000",
            "GIT_COMMITTER_DATE": f"@{fixed_epoch} +0000",
        },
    )
    fixed_epoch_2 = fixed_epoch + 60
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "add", "-A")
    _git(
        repo, "commit", "-q", "-m", "c1",
        env={
            "GIT_AUTHOR_DATE": f"@{fixed_epoch_2} +0000",
            "GIT_COMMITTER_DATE": f"@{fixed_epoch_2} +0000",
        },
    )
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    with sqlite3.connect(str(db)) as conn:
        ts = conn.execute(
            "SELECT DISTINCT timestamp FROM metric_data WHERE sha = ?", (sha,),
        ).fetchall()
    assert len(ts) == 1
    assert ts[0][0] == fixed_epoch_2


def test_first_parent_walk_ignores_side_branch_commits(tmp_path):
    """Walk follows only --first-parent; side-branch commits do NOT appear in metric_data."""
    repo = tmp_path / "r"
    _init_repo(repo)
    sha_main = _commit(repo, "a.py", "l1\nl2\nl3\n", "main1")

    _git(repo, "checkout", "-q", "-b", "side")
    sha_side = _commit(repo, "b.py", "l1\nl2\nl3\nl4\nl5\n", "side1")

    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-q", "-m", "merge side", "side")
    sha_merge = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(repo), text=True,
    ).strip()

    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)
    _run_generate(cfg)

    assert _running_value(db, sha_main, "TotalLinesOfCode") == 3
    assert _running_value(db, sha_side, "TotalLinesOfCode") is None
    # Merge commit's diff against first-parent includes side's additions.
    assert _running_value(db, sha_merge, "TotalLinesOfCode") == 8


# =====================================================================================
# 4. Generate CLI — config validation errors
# =====================================================================================


def test_generate_config_missing_file_fails_nonzero(tmp_path):
    """CLI exits non-zero when -C points at a nonexistent file."""
    proc = subprocess.run(
        ["git-code-debt-generate", "-C", str(tmp_path / "missing.yaml"), "-j", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert proc.returncode != 0


def test_generate_config_missing_required_field_fails_nonzero(tmp_path):
    """CLI exits non-zero when the yaml is missing a required field like `repo`."""
    cfg = tmp_path / "cfg.yaml"
    db = tmp_path / "db.db"
    cfg.write_text(f"database: {db}\n")  # `repo` intentionally omitted
    proc = subprocess.run(
        ["git-code-debt-generate", "-C", str(cfg), "-j", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    assert proc.returncode != 0


# =====================================================================================
# 5. list-metrics CLI
# =====================================================================================


def test_list_metrics_default_lists_all_and_skip_flag_filters(tmp_path):
    """Default lists every built-in parser; skip_default_metrics=true empties the output of defaults."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "c1")
    db = tmp_path / "db.db"

    cfg_default = _write_config(tmp_path / "cfg_default.yaml", repo, db)
    out_default = _run_list_metrics(cfg_default)
    for cls in ("TODOCount", "PythonImportCount", "BinaryFileCount", "SymlinkCount",
                "SubmoduleCount", "Python__init__LineCount"):
        assert cls in out_default

    cfg_skip = _write_config(
        tmp_path / "cfg_skip.yaml", repo, db, skip_default_metrics=True,
    )
    out_skip = _run_list_metrics(cfg_skip)
    for cls in ("TODOCount", "PythonImportCount", "BinaryFileCount", "SymlinkCount"):
        assert cls not in out_skip


def test_list_metrics_output_format_header_and_indented_metrics(tmp_path):
    """Output has `<module> <ClassName>` header + indented metric-name lines; --color never = plain."""
    repo = tmp_path / "r"
    _init_repo(repo)
    _commit(repo, "a.py", "x = 1\n", "c1")
    db = tmp_path / "db.db"
    cfg = _write_config(tmp_path / "cfg.yaml", repo, db)

    out = _run_list_metrics(cfg, extra_args=["--color", "never"])

    # No ANSI escapes with --color never.
    assert "\033[" not in out

    # Module qualifier appears (git_code_debt.metrics.*).
    assert "git_code_debt.metrics" in out

    # Individual metric names from get_metrics_info() appear (not just class names).
    assert "TotalLinesOfCode" in out
    assert "TotalLinesOfCode_python" in out

    # Metric-name lines are indented (visually grouped under class header).
    metric_lines = [l for l in out.splitlines() if "TotalLinesOfCode_python" in l]
    assert metric_lines and all(l.startswith((" ", "\t")) for l in metric_lines)


# =====================================================================================
# 6. Server CLI
# =====================================================================================


def test_server_cli_missing_db_exits_nonzero(tmp_path):
    """`git-code-debt-server <missing>` exits non-zero via subprocess."""
    missing = tmp_path / "does_not_exist.db"
    proc = subprocess.run(
        ["git-code-debt-server", str(missing), "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10,
    )
    assert proc.returncode != 0


def _assert_server_cli_accepts(
    db: pathlib.Path,
    cwd: pathlib.Path,
    extra_args: list[str],
    require_serving: bool = True,
) -> None:
    """Launch the server console script and assert its CLI accepts the given flags.

    Drives the public `git-code-debt-server` entry point (not an internal import). With a valid
    DB the documented startup sequence (write the sample `metric_config.yaml` if missing → load
    it → build `Config` → start Flask) must complete and then block serving, so `require_serving`
    demands the process is still alive after the wait. Pass `require_serving=False` when the
    bound port is not under the test's control and only argparse acceptance is checked.
    """
    proc = subprocess.Popen(
        ["git-code-debt-server", str(db), *extra_args],
        cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        rc = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
        return  # still running → flags accepted, startup finished, serving
    err = (proc.stderr.read() or b"").decode("utf-8", "replace")[-1000:]
    assert rc != 2, f"server rejected valid flags {extra_args} (argparse exit code 2): {err}"
    assert not require_serving, (
        f"server exited rc={rc} with flags {extra_args} instead of serving; startup with a "
        f"valid db and an ephemeral port must not fail: {err}"
    )


def test_server_cli_accepts_db_and_optional_flags(tmp_path):
    """The server CLI takes `<db>` positional (required), plus optional --port, --processes."""
    db = _prep_server_db(tmp_path)

    # `--port 0` binds an ephemeral port (no port conflicts); separate cwds keep the
    # auto-created metric_config.yaml isolated per invocation. Startup must actually succeed:
    # an early exit means the documented startup sequence (including re-loading the sample
    # config the server itself just wrote) failed.
    w1 = tmp_path / "cli_port"
    w1.mkdir()
    _assert_server_cli_accepts(db, w1, ["--port", "0"])

    w2 = tmp_path / "cli_port_processes"
    w2.mkdir()
    _assert_server_cli_accepts(db, w2, ["--port", "0", "--processes", "3"])

    # `--port` is optional: the db alone must be accepted. The default port is not controlled by
    # the test, so only an argparse rejection counts as a failure here.
    w3 = tmp_path / "cli_bare"
    w3.mkdir()
    _assert_server_cli_accepts(db, w3, [], require_serving=False)


def test_server_creates_metric_config_yaml_if_missing_via_subprocess(tmp_path):
    """`git-code-debt-server` writes a sample `metric_config.yaml` in cwd if none exists."""
    db = _prep_server_db(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    assert not (work / "metric_config.yaml").exists()

    # Server main tries to bind a port; run with a bogus DB path that fails AFTER config-write,
    # OR briefly with a real DB and kill. Simpler: use the subprocess with timeout.
    proc = subprocess.Popen(
        ["git-code-debt-server", str(db), "--port", "0"],
        cwd=str(work),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()

    assert (work / "metric_config.yaml").exists(), (
        "server startup must create metric_config.yaml in cwd if missing"
    )


# =====================================================================================
# 7. Server routes
# =====================================================================================


def test_server_index_page_shows_has_data_metrics_and_auto_groups(tmp_path):
    """Index shows only has_data=1 metrics; auto-injects Uncategorized + All buckets."""
    db = _prep_server_db(tmp_path)
    # Restrictive group: only TotalLinesOfCode → other metrics fall into Uncategorized.
    client, patches = _build_server_client(
        tmp_path, db,
        config_overrides={
            "Groups": [{"LinesOnly": {"metrics": ["TotalLinesOfCode"]}}],
        },
    )
    try:
        # /status/healthcheck is a fixed empty 200; folded here so the status blueprint is still
        # exercised without a standalone easy-credit test.
        assert client.get("/status/healthcheck").status_code == 200

        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        # A fired metric is shown.
        assert "TotalLinesOfCode" in body
        # A metric that never fired is NOT shown (only has_data=1 metrics).
        assert "BinaryFileCount" not in body
        # Auto-injected buckets appear when metrics exist that aren't in defined groups.
        assert "Uncategorized" in body
        assert "All" in body
    finally:
        _release_server(patches)


def test_server_index_and_commit_pages_mark_color_override_metrics(tmp_path):
    """Metrics in Config.color_overrides get a `color-override` marker on both index and commit pages."""
    db = _prep_server_db(tmp_path)
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT sha FROM metric_changes "
            "INNER JOIN metric_names ON metric_changes.metric_id = metric_names.id "
            "WHERE name = 'TotalLinesOfCode' LIMIT 1",
        ).fetchone()
    assert row is not None
    sha = row[0]

    client, patches = _build_server_client(
        tmp_path, db,
        config_overrides={"ColorOverrides": ["TotalLinesOfCode"]},
    )
    try:
        idx_body = client.get("/").get_data(as_text=True)
        commit_body = client.get(f"/commit/{sha}").get_data(as_text=True)
        assert "color-override" in idx_body
        assert "color-override" in commit_body
    finally:
        _release_server(patches)


def test_server_commit_page_shows_metric_name_and_delta(tmp_path):
    """GET /commit/<sha> shows the changed metric name AND its integer delta value for that sha."""
    db = _prep_server_db(tmp_path)
    # Deterministically pick the latest TotalLinesOfCode change (the b.py commit, delta +2) and
    # pull its expected delta straight from the DB so the assertion is self-consistent.
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT metric_changes.sha, metric_changes.value FROM metric_changes "
            "INNER JOIN metric_names ON metric_changes.metric_id = metric_names.id "
            "INNER JOIN metric_data ON metric_data.sha = metric_changes.sha "
            "    AND metric_data.metric_id = metric_changes.metric_id "
            "WHERE name = 'TotalLinesOfCode' "
            "ORDER BY metric_data.timestamp DESC LIMIT 1",
        ).fetchone()
    assert row is not None
    sha, expected_delta = row[0], row[1]

    client, patches = _build_server_client(tmp_path, db)
    try:
        resp = client.get(f"/commit/{sha}")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "TotalLinesOfCode" in body
        # The TotalLinesOfCode row must render its actual delta value, not just the name.
        delta = _delta_row_value(body, "TotalLinesOfCode")
        assert delta is not None, "commit page must render the TotalLinesOfCode delta row"
        assert delta == expected_delta
    finally:
        _release_server(patches)


def test_server_graph_endpoints_require_start_end_and_all_data_redirects(tmp_path):
    """GET /graph/<m>?start=&end= is 200; missing param is 4xx; /all_data redirects."""
    db = _prep_server_db(tmp_path)
    client, patches = _build_server_client(tmp_path, db)
    try:
        # Missing both start and end → 4xx.
        r_missing = client.get("/graph/TotalLinesOfCode")
        assert 400 <= r_missing.status_code < 500

        # Missing only end → 4xx.
        r_missing_end = client.get("/graph/TotalLinesOfCode?start=0")
        assert 400 <= r_missing_end.status_code < 500

        # With both → 200.
        r_ok = client.get("/graph/TotalLinesOfCode?start=0&end=9999999999")
        assert r_ok.status_code == 200

        # /all_data redirects to /graph/<m> with query params.
        r_all = client.get("/graph/TotalLinesOfCode/all_data")
        assert 300 <= r_all.status_code < 400
        loc = r_all.headers.get("Location", "")
        assert "/graph/TotalLinesOfCode" in loc
        assert "start=" in loc and "end=" in loc
    finally:
        _release_server(patches)


def test_server_changes_page_returns_html_200(tmp_path):
    """GET /changes/<name>/<start>/<end> returns JSON {'body': html} listing the actual changes."""
    db = _prep_server_db(tmp_path)
    # _prep_server_db seeds two TotalLinesOfCode changes: +3 (a.py) and +2 (b.py).
    with sqlite3.connect(str(db)) as conn:
        change_rows = conn.execute(
            "SELECT metric_changes.sha, metric_changes.value FROM metric_changes "
            "INNER JOIN metric_names ON metric_changes.metric_id = metric_names.id "
            "WHERE name = 'TotalLinesOfCode'",
        ).fetchall()
    assert {v for _, v in change_rows} == {3, 2}

    client, patches = _build_server_client(tmp_path, db)
    try:
        resp = client.get("/changes/TotalLinesOfCode/0/9999999999")
        assert resp.status_code == 200
        # Response is JSON {'body': <rendered html>}; a wrong query would render an empty body.
        body = _json.loads(resp.get_data(as_text=True))["body"]
        assert body.strip(), "changes body must not be empty"
        # Every changed commit in the window is listed (catches empty/wrong-window/wrong-join).
        for sha, _ in change_rows:
            assert sha[:8] in body, f"change for {sha[:8]} missing from body"
        # Each change's integer delta value is rendered as the text content of some HTML
        # element (magnitudes 3 and 2). The /changes contract lists the delta value but does
        # not pin a specific container tag (unlike /commit and /widget/data), so accept the
        # value in any element (<td>, <span>, <li>, ...), not only a table cell.
        values = set(re.findall(r">\s*(-?\d+)\s*<", body))
        assert {"3", "2"} <= values, f"expected delta values 3 and 2 rendered in body, got {values}"
    finally:
        _release_server(patches)


def test_server_widget_endpoints(tmp_path, monkeypatch):
    """Widget frame HTML has <script>; POST /widget/data with diff returns JSON; GET → 405; missing diff → 4xx."""
    db = _prep_server_db(tmp_path)
    # widget/data reads generate_config.yaml from cwd.
    (tmp_path / "generate_config.yaml").write_text(
        f"repo: {tmp_path / 'srv_repo'}\ndatabase: {db}\n",
    )
    monkeypatch.chdir(tmp_path)

    client, patches = _build_server_client(tmp_path, db)
    try:
        # Frame has a <script> element.
        frame = client.get("/widget/frame")
        assert frame.status_code == 200
        assert "<script" in frame.get_data(as_text=True).lower()

        # GET /widget/data must be 405.
        assert client.get("/widget/data").status_code == 405

        # POST without diff → 4xx.
        r_no_diff = client.post("/widget/data")
        assert 400 <= r_no_diff.status_code < 500

        # POST with diff → 200 + JSON with 'metrics' + configured metric name in output.
        diff = (
            "diff --git a/a.py b/a.py\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            "+++ b/a.py\n"
            "@@ -0,0 +1,3 @@\n"
            "+import os\n"
            "+x = 1\n"
            "+y = 2\n"
        )
        r_ok = client.post("/widget/data", data={"diff": diff})
        assert r_ok.status_code == 200
        payload = _json.loads(r_ok.get_data(as_text=True))
        assert "metrics" in payload
        # Configured widget metric must render with its computed delta value, not just the name:
        # the posted diff adds exactly 3 lines to a.py, so the TotalLinesOfCode delta is 3.
        assert "TotalLinesOfCode" in payload["metrics"]
        delta = _delta_row_value(payload["metrics"], "TotalLinesOfCode")
        assert delta is not None, "widget fragment must render the TotalLinesOfCode delta row"
        assert delta == 3
    finally:
        _release_server(patches)


# =====================================================================================
# 8. Config semantics via server startup (E2E; no direct Config imports)
# =====================================================================================


def test_metric_config_yaml_requires_all_four_top_level_keys(tmp_path):
    """Server startup fails when metric_config.yaml is missing a required top-level key."""
    db = _prep_server_db(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    # Only 3 of 4 required keys; server main should fail to load config.
    (work / "metric_config.yaml").write_text(
        "Groups: []\nColorOverrides: []\nCommitLinks: {}\n",  # WidgetMetrics missing
    )

    proc = subprocess.Popen(
        ["git-code-debt-server", str(db), "--port", "0"],
        cwd=str(work),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        rc = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        # If server stayed up, the missing key was silently defaulted — spec violation.
        proc.kill()
        proc.wait()
        raise AssertionError(
            "server startup must fail when metric_config.yaml is missing a required key"
        )
    assert rc != 0, "missing required key must produce non-zero exit"


def test_metric_config_yaml_group_must_define_metrics_or_expressions(tmp_path):
    """Group with both `metrics` and `metric_expressions` empty must fail (TypeError → startup fails)."""
    db = _prep_server_db(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "metric_config.yaml").write_text(
        "Groups:\n"
        "    - Empty:\n"
        "        metrics: []\n"
        "        metric_expressions: []\n"
        "ColorOverrides: []\n"
        "CommitLinks: {}\n"
        "WidgetMetrics: {}\n"
    )

    proc = subprocess.Popen(
        ["git-code-debt-server", str(db), "--port", "0"],
        cwd=str(work),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        rc = proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        raise AssertionError(
            "Group with both metrics and metric_expressions empty must fail startup"
        )
    assert rc != 0
