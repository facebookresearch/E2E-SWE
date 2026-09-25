"""
End-to-end and unit tests for the `papers` CLI / library.

Conventions
-----------
* CLI tests invoke `papers` as a subprocess (the script declared in
  pyproject.toml). The implementation may organise internal modules however
  it likes; only the public CLI surface is asserted.
* Unit tests import from `papers.bib`, `papers.extract`, `papers.encoding`,
  `papers.latexenc`, `papers.filename`. These are the only import paths the
  spec commits to.
* Each test runs in a freshly-created tmp dir with HOME / XDG_* redirected
  so global config and cache leakage between tests is impossible.
* The crossref base URL is overridden via the PAPERS_CROSSREF_API env var,
  which the spec mandates for testability.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_PROXY_ENV_VARS = (
    "http_proxy",
    "HTTP_PROXY",
    "https_proxy",
    "HTTPS_PROXY",
    "all_proxy",
    "ALL_PROXY",
)


def _papers_cmd(args, *, cwd, env_extra=None, input_text=None, check=False):
    """Invoke the CLI in a subprocess and return (returncode, stdout, stderr)."""
    env = os.environ.copy()
    # The grading container can inherit *_proxy vars pointing at a forwarder that is
    # already gone when the offline suite runs; HTTP clients honour them by default and
    # would route even the localhost crossref mock through the dead proxy. Talk direct.
    for var in _PROXY_ENV_VARS:
        env.pop(var, None)
    env["no_proxy"] = env["NO_PROXY"] = "localhost,127.0.0.1,::1"
    if env_extra:
        env.update(env_extra)
    res = subprocess.run(
        [sys.executable, "-m", "papers", *args],
        cwd=str(cwd),
        env=env,
        input=input_text,
        capture_output=True,
        text=True,
    )
    if check and res.returncode != 0:
        raise AssertionError(
            f"papers {' '.join(args)} failed (rc={res.returncode})\n"
            f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
    return res.returncode, res.stdout, res.stderr


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Isolate HOME, XDG_*, and cwd so each test sees a clean global config."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".config").mkdir()
    (home / ".cache").mkdir()
    (home / ".local" / "share").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(home / ".cache"))
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))
    # Git identity for tests that exercise the --git install. Setting these via
    # env (rather than relying on the global ~/.gitconfig) keeps git working
    # even when HOME points at a fresh tmp dir.
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Papers Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "papers-test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Papers Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "papers-test@example.com")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    return workdir


@pytest.fixture
def sample_entry_bibtex():
    return dedent(
        """\
        @article{perrette_yool2011,
         author = {Perrette, M. and Yool, A. and Quartly, G. D. and Popova, E. E.},
         doi = {10.5194/bg-8-515-2011},
         journal = {Biogeosciences},
         number = {2},
         pages = {515-524},
         title = {Near-ubiquity of ice-edge blooms in the Arctic},
         year = {2011}
        }
        """
    )


@pytest.fixture
def second_entry_bibtex():
    return dedent(
        """\
        @article{someoneelse2000,
         author = {One, Some},
         doi = {10.5194/xxxx},
         title = {Interesting Stuff},
         year = {2000}
        }
        """
    )


@pytest.fixture
def make_pdf(tmp_path):
    """Return a factory that creates a synthetic PDF containing a given text body."""
    import fitz  # PyMuPDF

    counter = {"n": 0}

    def _make(text, name=None):
        counter["n"] += 1
        path = tmp_path / (name or f"sample_{counter['n']}.pdf")
        doc = fitz.open()
        page = doc.new_page()
        y = 72
        for line in text.splitlines() or [text]:
            page.insert_text((72, y), line, fontsize=10)
            y += 14
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


@pytest.fixture
def crossref_mock(temp_env, monkeypatch):
    """Spin up a pytest-httpserver instance and point PAPERS_CROSSREF_API at it."""
    from pytest_httpserver import HTTPServer

    server = HTTPServer()
    server.start()
    monkeypatch.setenv("PAPERS_CROSSREF_API", server.url_for("").rstrip("/"))
    yield server
    server.clear()
    server.stop()


CROSSREF_BG_MESSAGE = {
    "DOI": "10.5194/bg-8-515-2011",
    "URL": "https://doi.org/10.5194/bg-8-515-2011",
    "type": "journal-article",
    "title": ["Near-ubiquity of ice-edge blooms in the Arctic"],
    "container-title": ["Biogeosciences"],
    "volume": "8",
    "issue": "2",
    "page": "515-524",
    "author": [
        {"given": "M.", "family": "Perrette"},
        {"given": "A.", "family": "Yool"},
        {"given": "G. D.", "family": "Quartly"},
        {"given": "E. E.", "family": "Popova"},
    ],
    "published-print": {"date-parts": [[2011, 2, 1]]},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entries(bibtex_text):
    """Return list of (key, fields_dict) from a bibtex string via papers.bib.Biblio."""
    from papers.bib import Biblio

    tmp = tempfile.NamedTemporaryFile("w", suffix=".bib", delete=False)
    try:
        tmp.write(bibtex_text)
        tmp.close()
        bib = Biblio.load(tmp.name, "")
        out = []
        for e in bib.entries:
            d = {}
            if hasattr(e, "fields_dict"):
                d = {k: v.value for k, v in e.fields_dict.items()}
            elif hasattr(e, "items"):
                d = dict(e.items())
            if hasattr(e, "key"):
                d.setdefault("ID", e.key)
            out.append((d.get("ID", ""), d))
        return out
    finally:
        os.unlink(tmp.name)


# ---------------------------------------------------------------------------
# Unit tests — pure functions
# ---------------------------------------------------------------------------


class TestPureFunctions:
    def test_parse_doi_variants(self):
        """parse_doi extracts DOIs from URL, doi:, citation, and line-split text."""
        from papers.extract import parse_doi

        assert parse_doi("doi:10.5194/bg-8-515-2011").lower() == "10.5194/bg-8-515-2011"
        txt = (
            "Header text\n"
            "see https://doi.org/10.5194/bg-8-515-2011 for more\n"
            "cited as doi:10.9999/other-entry"
        )
        assert parse_doi(txt).lower() == "10.5194/bg-8-515-2011"
        # DOI split across newline at "10.\n<registrant>"
        assert (
            parse_doi("doi: 10.\n5194/bg-8-515-2011").lower() == "10.5194/bg-8-515-2011"
        )

    def test_parse_doi_strips_trailing_junk(self):
        """parse_doi cleans common trailing markers like .pdf and unbalanced parens."""
        from papers.extract import parse_doi

        assert (
            parse_doi("doi:10.5194/bg-8-515-2011.pdf").lower()
            == "10.5194/bg-8-515-2011"
        )
        assert (
            parse_doi("see (doi:10.5194/bg-8-515-2011)").lower()
            == "10.5194/bg-8-515-2011"
        )

    def test_parse_doi_raises_when_absent(self):
        """parse_doi raises DOIParsingError when no DOI is present."""
        from papers.extract import DOIParsingError, parse_doi

        with pytest.raises(DOIParsingError):
            parse_doi("This text contains no DOI at all, just words.")

    def test_crossref_to_bibtex_journal_article(self):
        """crossref_to_bibtex turns a journal-article message into a valid bibtex string."""
        from papers.extract import crossref_to_bibtex

        bibtex = crossref_to_bibtex(CROSSREF_BG_MESSAGE)
        assert "@article" in bibtex
        assert "10.5194/bg-8-515-2011" in bibtex
        assert "Near-ubiquity of ice-edge blooms in the Arctic" in bibtex
        assert "2011" in bibtex
        assert "Biogeosciences" in bibtex
        assert "Perrette" in bibtex and "Yool" in bibtex
        assert len(_entries(bibtex)) == 1

    def test_latex_unicode_roundtrip(self):
        """latex_to_unicode and string_to_latex round-trip a representative char set."""
        from papers.latexenc import latex_to_unicode, string_to_latex

        assert (
            latex_to_unicode('M. Perrette and F. M\\"uller')
            == "M. Perrette and F. Müller"
        )
        original = "café naïve résumé Hölder"
        assert latex_to_unicode(string_to_latex(original)) == original

    def test_name_normalisation(self):
        """standard_name flips 'First Last' to 'Last, First'; family_names extracts family."""
        from papers.encoding import family_names, standard_name

        assert standard_name("John Smith and Jane Doe") == "Smith, John and Doe, Jane"
        assert standard_name("Smith, John and Doe, Jane") == "Smith, John and Doe, Jane"
        assert family_names("John Smith and Jane Doe") == ["Smith", "Doe"]

    def test_filename_template_rendering(self):
        """Format.render produces documented substitutions (author, AuthorX, year, title, ID)."""
        from papers.filename import Format

        entry = {
            "ID": "perrette2011",
            "author": "Perrette, M. and Yool, A. and Quartly, G. D.",
            "year": "2011",
            "title": "Near-ubiquity of ice-edge blooms in the Arctic",
            "doi": "10.5194/bg-8-515-2011",
        }
        fmt = Format(template="{author}{year}", author_num=1, author_sep="_")
        assert fmt.render(**entry) == "perrette2011"
        fmt = Format(template="{authorX}_{year}", author_num=2, author_sep="_")
        assert fmt.render(**entry) == "perrette_et_al_2011"
        fmt = Format(
            template="{Author}{year}-{Title}",
            author_num=1,
            title_word_num=4,
            author_sep="",
            title_sep="-",
        )
        rendered = fmt.render(**entry)
        assert rendered.startswith("Perrette2011-")
        assert "Near" in rendered

    def test_duplicate_levels(self):
        """compare_entries / are_duplicates score EXACT, GOOD, FAIR, PARTIAL appropriately."""
        from papers.bib import (
            are_duplicates,
            compare_entries,
            EXACT_DUPLICATES,
            FAIR_DUPLICATES,
            GOOD_DUPLICATES,
            PARTIAL_DUPLICATES,
        )

        e1 = {
            "ID": "a1",
            "author": "Perrette, M. and Yool, A.",
            "title": "Near-ubiquity of ice-edge blooms in the Arctic",
            "doi": "10.5194/bg-8-515-2011",
            "year": "2011",
            "ENTRYTYPE": "article",
        }
        assert compare_entries(e1, dict(e1)) == EXACT_DUPLICATES
        e2 = dict(e1, year="2012", ID="a2")
        assert compare_entries(e1, e2) == GOOD_DUPLICATES
        e3 = {
            "ID": "a3",
            "author": "Other, X.",
            "title": "Different title entirely",
            "doi": "10.5194/bg-8-515-2011",
            "ENTRYTYPE": "article",
        }
        assert compare_entries(e1, e3) == FAIR_DUPLICATES
        e4 = dict(e1, doi="10.9999/something-else", ID="a4")
        assert compare_entries(e1, e4) == PARTIAL_DUPLICATES
        e5 = {
            "ID": "a5",
            "author": "Z, Q.",
            "title": "Unrelated",
            "doi": "10.0/zzz",
            "ENTRYTYPE": "article",
        }
        assert compare_entries(e1, e5) == 0
        assert are_duplicates(e1, e4) is True
        assert are_duplicates(e1, e5) is False


# ---------------------------------------------------------------------------
# CLI tests — biblio operations
# ---------------------------------------------------------------------------


class TestBiblioRoundtrip:
    def test_load_save_reload_equal(self, temp_env, sample_entry_bibtex):
        """Biblio.load → dumps → reload preserves the entry set."""
        from papers.bib import Biblio

        src = temp_env / "src.bib"
        src.write_text(sample_entry_bibtex)
        bib = Biblio.load(str(src), "")
        assert len(bib.entries) == 1

        dst = temp_env / "dst.bib"
        dst.write_text(bib.dumps())
        bib2 = Biblio.load(str(dst), "")
        assert len(bib2.entries) == 1
        e = bib2.entries[0]
        if hasattr(e, "fields_dict"):
            assert e.fields_dict["doi"].value == "10.5194/bg-8-515-2011"
        else:
            assert e["doi"] == "10.5194/bg-8-515-2011"


class TestAdd:
    def test_add_bibtex_to_new_library(self, temp_env, sample_entry_bibtex):
        """`papers add other.bib --bibtex lib.bib` materialises the entry in lib.bib."""
        (temp_env / "other.bib").write_text(sample_entry_bibtex)
        (temp_env / "lib.bib").write_text("")
        _papers_cmd(
            ["add", "other.bib", "--bibtex", "lib.bib"], cwd=temp_env, check=True
        )
        content = (temp_env / "lib.bib").read_text()
        assert "10.5194/bg-8-515-2011" in content
        assert len(_entries(content)) == 1

    def test_add_same_entry_twice_is_idempotent(self, temp_env, sample_entry_bibtex):
        """Adding the same bibtex twice does not create a duplicate (PARTIAL similarity)."""
        (temp_env / "other.bib").write_text(sample_entry_bibtex)
        (temp_env / "lib.bib").write_text("")
        _papers_cmd(
            ["add", "other.bib", "--bibtex", "lib.bib"], cwd=temp_env, check=True
        )
        # Second invocation — pass --mode u (update/skip) so it doesn't prompt
        _papers_cmd(
            ["add", "other.bib", "--bibtex", "lib.bib", "--mode", "u"],
            cwd=temp_env,
        )
        assert len(_entries((temp_env / "lib.bib").read_text())) == 1

    def test_add_two_distinct_entries(
        self, temp_env, sample_entry_bibtex, second_entry_bibtex
    ):
        """Two non-duplicate entries can be added independently to the same library."""
        (temp_env / "a.bib").write_text(sample_entry_bibtex)
        (temp_env / "b.bib").write_text(second_entry_bibtex)
        (temp_env / "lib.bib").write_text("")
        _papers_cmd(["add", "a.bib", "--bibtex", "lib.bib"], cwd=temp_env, check=True)
        _papers_cmd(["add", "b.bib", "--bibtex", "lib.bib"], cwd=temp_env, check=True)
        content = (temp_env / "lib.bib").read_text()
        assert "10.5194/bg-8-515-2011" in content
        assert "10.5194/xxxx" in content
        assert len(_entries(content)) == 2


class TestList:
    @pytest.fixture
    def two_entry_lib(self, temp_env, sample_entry_bibtex, second_entry_bibtex):
        lib = temp_env / "lib.bib"
        lib.write_text(sample_entry_bibtex + second_entry_bibtex)
        return lib

    def test_list_default_one_per_entry(self, temp_env, two_entry_lib):
        """`papers list` (no filter) prints one summary line per entry, each identifying its entry."""
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(two_entry_lib)], cwd=temp_env, check=True
        )
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 2
        # Each entry must actually be identified in the output — not merely "two lines".
        # The default one-liner begins with the bibtex key (see instruction.md `list`),
        # so both fixture keys must surface, each on its own line.
        assert "perrette_yool2011" in out
        assert "someoneelse2000" in out
        assert sum("perrette_yool2011" in l for l in lines) == 1
        assert sum("someoneelse2000" in l for l in lines) == 1

    def test_list_filter_by_author(self, temp_env, two_entry_lib):
        """`papers list --author <name>` returns only entries matching that author."""
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(two_entry_lib), "--author", "perrette"],
            cwd=temp_env,
            check=True,
        )
        assert "perrette_yool2011" in out
        assert "someoneelse2000" not in out

    def test_list_filter_invert_excludes_matches(self, temp_env, two_entry_lib):
        """`papers list --author <name> --invert` returns the entries that do NOT match.

        `--invert` negates the active filters — a distinct code path from a plain
        positive filter (which `test_list_filter_by_author` already covers via the
        shared field-match predicate). Filtering for `perrette` and inverting must
        surface only the *other* entry.
        """
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(two_entry_lib), "--author", "perrette", "--invert"],
            cwd=temp_env,
            check=True,
        )
        lines = [l for l in out.splitlines() if l.strip()]
        assert len(lines) == 1
        # Only the non-matching entry survives. A no-op `--invert` (returning the
        # matched perrette entry, or both entries) must fail.
        assert "someoneelse2000" in out
        assert "perrette_yool2011" not in out

    def test_list_key_only_output(self, temp_env, two_entry_lib):
        """`papers list --key-only` prints just one bibtex key per line, no descriptions."""
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(two_entry_lib), "--key-only"],
            cwd=temp_env,
            check=True,
        )
        keys = [l.strip() for l in out.splitlines() if l.strip()]
        # --key-only prints exactly the two fixture entry IDs, one per line, with
        # no embedded title / metadata. Only a correct rendering yields this set.
        assert set(keys) == {"perrette_yool2011", "someoneelse2000"}

    def test_list_plain_output_is_bibtex(self, temp_env, two_entry_lib):
        """`papers list --plain` emits raw bibtex blocks."""
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(two_entry_lib), "--plain"],
            cwd=temp_env,
            check=True,
        )
        assert "@article" in out
        assert "10.5194/bg-8-515-2011" in out

    def test_list_delete_removes_filtered_entries(self, temp_env, two_entry_lib):
        """`papers list --delete` removes the filtered subset from the library file."""
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(two_entry_lib), "--year", "2011", "--delete"],
            cwd=temp_env,
        )
        content = two_entry_lib.read_text()
        assert "10.5194/bg-8-515-2011" not in content
        assert "10.5194/xxxx" in content
        assert len(_entries(content)) == 1


class TestTagging:
    def test_add_tag_and_filter_by_tag(self, temp_env, sample_entry_bibtex):
        """`list --add-tag X` writes the tag; subsequent `list --tag X` returns the entry."""
        lib = temp_env / "lib.bib"
        lib.write_text(sample_entry_bibtex)
        _papers_cmd(
            [
                "list",
                "--bibtex",
                str(lib),
                "--key",
                "perrette_yool2011",
                "--add-tag",
                "arctic",
                "sea-ice",
            ],
            cwd=temp_env,
            check=True,
        )
        content = lib.read_text()
        assert "arctic" in content
        assert "sea-ice" in content
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(lib), "--tag", "arctic"],
            cwd=temp_env,
            check=True,
        )
        # The tagged entry must surface, identified by its key (the default one-liner
        # begins with the bibtex key — see instruction.md `list`), not merely "some output".
        assert "perrette_yool2011" in out


class TestDuplicatesListing:
    def test_list_duplicates_finds_same_doi(self, temp_env, sample_entry_bibtex):
        """`list --duplicates` surfaces both entries that share a DOI."""
        lib = temp_env / "lib.bib"
        dup = sample_entry_bibtex.replace("perrette_yool2011", "other_key2011")
        lib.write_text(sample_entry_bibtex + dup)
        rc, out, err = _papers_cmd(
            ["list", "--bibtex", str(lib), "--duplicates"],
            cwd=temp_env,
            check=True,
        )
        # Both DOI-sharing entries must surface, identified by their distinct keys —
        # not merely "two lines were printed".
        assert "perrette_yool2011" in out
        assert "other_key2011" in out


# ---------------------------------------------------------------------------
# CLI tests — check / filecheck / install / undo
# ---------------------------------------------------------------------------


class TestCheck:
    def test_check_format_name_normalises_authors(self, temp_env):
        """`check --format-name` flips 'John Smith and Jane Doe' → 'Smith, John and Doe, Jane'."""
        lib = temp_env / "lib.bib"
        lib.write_text(
            dedent(
                """\
            @article{Test2020,
             author = {John Smith and Jane Doe},
             doi = {10.5194/bg-8-515-2011},
             title = {A Test},
             year = {2020}
            }
            """
            )
        )
        _papers_cmd(
            ["check", "--bibtex", str(lib), "--format-name", "--force"],
            cwd=temp_env,
            check=True,
        )
        content = lib.read_text()
        assert "Smith, John" in content
        assert "Doe, Jane" in content

    def test_check_fix_doi_strips_prefix(self, temp_env):
        """`check --fix-doi` removes the leading 'DOI:' prefix from doi fields."""
        lib = temp_env / "lib.bib"
        lib.write_text(
            dedent(
                """\
            @article{Test2020,
             author = {Smith, John},
             doi = {DOI:10.5194/bg-8-515-2011},
             title = {A Test},
             year = {2020}
            }
            """
            )
        )
        _papers_cmd(
            ["check", "--bibtex", str(lib), "--fix-doi", "--force"],
            cwd=temp_env,
            check=True,
        )
        content = lib.read_text()
        assert "DOI:10.5194" not in content
        assert "10.5194/bg-8-515-2011" in content

    def test_check_encoding_unicode_converts_latex(self, temp_env):
        """`check --encoding unicode` converts LaTeX escapes in field values to unicode."""
        lib = temp_env / "lib.bib"
        lib.write_text(
            dedent(
                r"""@article{Test2020,
             author = {M{\"u}ller, Hans},
             doi = {10.5194/bg-8-515-2011},
             title = {Caf{\'e} study},
             year = {2020}
            }
            """
            )
        )
        _papers_cmd(
            ["check", "--bibtex", str(lib), "--encoding", "unicode", "--force"],
            cwd=temp_env,
            check=True,
        )
        content = lib.read_text()
        assert "Müller" in content or "ü" in content
        assert "Café" in content or "é" in content


class TestFilecheck:
    @staticmethod
    def _create_pdf_stub(path):
        # Minimal PDF byte sequence — sufficient for rename which only inspects path,
        # not PDF content. Avoids depending on PyMuPDF for this test.
        Path(path).write_bytes(b"%PDF-1.4\n%minimal stub\n%%EOF\n")

    def test_filecheck_rename_uses_template(self, temp_env, sample_entry_bibtex):
        """`filecheck --rename` renames an attached PDF per the default name template."""
        files_dir = temp_env / "files"
        files_dir.mkdir()
        pdf_path = files_dir / "messy-name.pdf"
        self._create_pdf_stub(pdf_path)
        bib_text = sample_entry_bibtex.replace(
            "year = {2011}",
            "year = {2011},\n file = {:" + str(pdf_path) + ":pdf}",
        )
        lib = temp_env / "lib.bib"
        lib.write_text(bib_text)
        _papers_cmd(
            [
                "filecheck",
                "--bibtex",
                str(lib),
                "--filesdir",
                str(files_dir),
                "--rename",
                "--force",
            ],
            cwd=temp_env,
            check=True,
        )
        renamed = [p for p in files_dir.iterdir() if p.suffix == ".pdf"]
        assert len(renamed) == 1
        name = renamed[0].name.lower()
        assert "2011" in name
        assert "perrette" in name
        # The NAMEFORMAT is `{authorX}_{year}_{title}`, so the slugified title must
        # also appear — a template bug that dropped or mangled the title would pass on
        # author+year alone. Assert the leading title-slug stem (robust across slugify
        # versions) rather than the full slug.
        assert "near-ubiquity" in name

    def test_filecheck_delete_broken_removes_missing_links(
        self, temp_env, sample_entry_bibtex
    ):
        """`filecheck --delete-broken` strips file= fields pointing at non-existent paths."""
        missing = temp_env / "nope.pdf"
        bib_text = sample_entry_bibtex.replace(
            "year = {2011}",
            "year = {2011},\n file = {:" + str(missing) + ":pdf}",
        )
        lib = temp_env / "lib.bib"
        lib.write_text(bib_text)
        _papers_cmd(
            ["filecheck", "--bibtex", str(lib), "--delete-broken", "--force"],
            cwd=temp_env,
        )
        content = lib.read_text()
        assert str(missing) not in content
        # --delete-broken strips only the dead file= link; the entry itself must survive.
        # A wrong implementation that deletes the whole entry (or empties the file) also
        # satisfies the negative check above, so pin the survivor explicitly.
        assert len(_entries(content)) == 1
        assert "10.5194/bg-8-515-2011" in content


class TestInstallLocal:
    def test_install_local_creates_config_and_is_used(
        self, temp_env, sample_entry_bibtex
    ):
        """`install --local` writes a local config; subsequent commands honor it."""
        (temp_env / "mybib.bib").write_text(sample_entry_bibtex)
        _papers_cmd(
            [
                "install",
                "--local",
                "--force",
                "--bibtex",
                "mybib.bib",
                "--filesdir",
                "myfiles",
            ],
            cwd=temp_env,
            check=True,
        )
        cfg = temp_env / ".papersconfig.json"
        assert cfg.exists(), (
            f"Expected local config not found. Files: {list(temp_env.iterdir())}"
        )
        rc, out, err = _papers_cmd(["list"], cwd=temp_env, check=True)
        assert "10.5194/bg-8-515-2011" in out or "perrette" in out.lower()

    def test_status_reports_config(self, temp_env, sample_entry_bibtex):
        """`status -v` prints the configured bibtex / filesdir paths."""
        (temp_env / "mybib.bib").write_text(sample_entry_bibtex)
        _papers_cmd(
            [
                "install",
                "--local",
                "--force",
                "--bibtex",
                "mybib.bib",
                "--filesdir",
                "myfiles",
            ],
            cwd=temp_env,
            check=True,
        )
        rc, out, err = _papers_cmd(["status", "-v"], cwd=temp_env, check=True)
        assert "mybib.bib" in out
        assert "myfiles" in out


class TestInstallGit:
    def test_install_git_commits_on_add(
        self, temp_env, sample_entry_bibtex, second_entry_bibtex
    ):
        """`install --git` then `add` produces a git commit in the backup repo."""
        (temp_env / "lib.bib").write_text(sample_entry_bibtex)
        _papers_cmd(
            [
                "install",
                "--local",
                "--force",
                "--git",
                "--bibtex",
                "lib.bib",
                "--filesdir",
                "files",
            ],
            cwd=temp_env,
            check=True,
        )
        (temp_env / "extra.bib").write_text(second_entry_bibtex)
        _papers_cmd(["add", "extra.bib"], cwd=temp_env, check=True)
        rc, out, err = _papers_cmd(
            ["git", "log", "--oneline"],
            cwd=temp_env,
            check=True,
        )
        commit_lines = [l for l in out.splitlines() if l.strip()]
        assert len(commit_lines) >= 2


class TestUndoRedo:
    def test_undo_reverts_last_add(
        self, temp_env, sample_entry_bibtex, second_entry_bibtex
    ):
        """`undo` reverts the previous `add`; `redo` re-applies it."""
        (temp_env / "lib.bib").write_text(sample_entry_bibtex)
        _papers_cmd(
            [
                "install",
                "--local",
                "--force",
                "--bibtex",
                "lib.bib",
                "--filesdir",
                "files",
            ],
            cwd=temp_env,
            check=True,
        )
        (temp_env / "extra.bib").write_text(second_entry_bibtex)
        _papers_cmd(["add", "extra.bib"], cwd=temp_env, check=True)
        assert len(_entries((temp_env / "lib.bib").read_text())) == 2
        _papers_cmd(["undo"], cwd=temp_env, check=True)
        assert len(_entries((temp_env / "lib.bib").read_text())) == 1
        _papers_cmd(["redo"], cwd=temp_env, check=True)
        assert len(_entries((temp_env / "lib.bib").read_text())) == 2


# ---------------------------------------------------------------------------
# PDF + crossref integration
# ---------------------------------------------------------------------------


class TestPDFExtraction:
    def test_extract_pdf_doi_from_synthetic_pdf(self, make_pdf):
        """extract_pdf_doi recovers a DOI embedded in PDF body text."""
        from papers.extract import extract_pdf_doi

        pdf = make_pdf(
            "Sample article\n"
            "Authors: One, Two\n"
            "doi:10.5194/bg-8-515-2011\n"
            "Abstract: ..."
        )
        assert extract_pdf_doi(pdf).lower() == "10.5194/bg-8-515-2011"

    def test_extract_command_uses_crossref_mock(
        self, temp_env, make_pdf, crossref_mock
    ):
        """`papers extract <pdf>` returns crossref-derived bibtex when the API is mocked.

        Exercises the full pipeline:
            PDF → parse_doi → fetch from PAPERS_CROSSREF_API → crossref_to_bibtex → stdout
        """
        crossref_mock.expect_request("/works/10.5194/bg-8-515-2011").respond_with_json(
            {"message": CROSSREF_BG_MESSAGE}
        )
        pdf = make_pdf(
            "Sample article\nAuthors: Perrette et al\ndoi:10.5194/bg-8-515-2011\n"
        )
        rc, out, err = _papers_cmd(
            ["extract", pdf],
            cwd=temp_env,
            check=True,
        )
        assert "@article" in out
        assert "10.5194/bg-8-515-2011" in out
        assert "Near-ubiquity of ice-edge blooms in the Arctic" in out
