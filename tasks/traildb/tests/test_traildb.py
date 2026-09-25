"""Hidden pytest suite for the traildb WRG task.

Two kinds of tests, all under one file:

* **CLI-driven** -- shell out to the installed `tdb` binary (from tdbcli/),
  drive `tdb make` from stdin, `tdb dump` from a produced tdb, and assert on
  stdout / exit code. Cover end-to-end input pipelines the CLI itself
  contracts (CSV / JSON I/O, `--csv-header`, `--tdb-format=pkg|dir`,
  `--no-bigrams`, `-F` filter DSL, `tdb merge`, error exits).
* **C-driver** -- write a small C program that links `libtraildb.so`, exercise
  the low-level API (lexicon lookup, UUID hex roundtrip, cursor peek/next,
  the `tdb_event_filter_*` DSL and its introspection getters, multi-cursor,
  option get/set, item bit-packing, error codes), and assert on stdout.

Both kinds compile / execute inside per-test tmp dirs so tests don't leak
state, and the C-driver tests use $TDB_ROOT to scope their tdb paths.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest


TESTS_DIR = Path(__file__).resolve().parent
COMPILE_TIMEOUT = 30
RUN_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Shared C-driver harness
# ---------------------------------------------------------------------------


def _compile(tmp_path: Path, c_source: str, name: str = "driver") -> Path:
    """Compile a C source string into a binary; return the binary path."""
    src = tmp_path / f"{name}.c"
    src.write_text(c_source)
    bin_path = tmp_path / name
    cmd = [
        "gcc",
        "-std=c99",
        "-Wno-unused-value",
        "-Wno-unused-variable",
        "-Wno-unused-but-set-variable",
        str(src),
        "-ltraildb",
        "-o",
        str(bin_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=COMPILE_TIMEOUT)
    assert r.returncode == 0, (
        f"compile failed for {name}.c:\n"
        f"CMD: {' '.join(cmd)}\n"
        f"STDOUT:\n{r.stdout}\n"
        f"STDERR:\n{r.stderr}\n"
        f"SOURCE (first 2KB):\n{c_source[:2048]}"
    )
    return bin_path


def _run_binary(bin_path: Path, tmp_path: Path) -> tuple[int, str, str]:
    """Run a compiled test binary with TDB_ROOT scoped into tmp_path."""
    env = os.environ.copy()
    env["TDB_ROOT"] = str(tmp_path)
    r = subprocess.run(
        [str(bin_path)],
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
        env=env,
    )
    return r.returncode, r.stdout, r.stderr


COMMON = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdint.h>
#include <traildb.h>

#define DIE(msg) do { fprintf(stderr, "FATAL: %s\n", msg); exit(1); } while (0)

/* Deterministic 16-byte UUID from a byte seed. */
static void mk_uuid(uint8_t uuid[16], uint8_t seed) {
    for (int i = 0; i < 16; i++) uuid[i] = (uint8_t)(seed + i);
}

/* Absolute path under $TDB_ROOT for a per-test tdb name. */
static void path_of(char *out, const char *name) {
    const char *root = getenv("TDB_ROOT");
    if (!root) DIE("TDB_ROOT env var not set");
    snprintf(out, 512, "%s/%s", root, name);
}
"""


def _run_c(tmp_path: Path, body: str, name: str = "driver") -> tuple[int, str, str]:
    """Compile+run `COMMON + body` where body defines `int main(...)`."""
    b = _compile(tmp_path, COMMON + "\n" + body, name)
    return _run_binary(b, tmp_path)


# ---------------------------------------------------------------------------
# Shared CLI harness
# ---------------------------------------------------------------------------


def _tdb(
    *args: str, stdin: str = "", cwd: Path | None = None, timeout: int = RUN_TIMEOUT
) -> tuple[int, str, str]:
    """Run `tdb <args>`; return (returncode, stdout, stderr)."""
    r = subprocess.run(
        ["tdb", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )
    return r.returncode, r.stdout, r.stderr


# ===========================================================================
# CLI-driven tests
# ===========================================================================


class TestCliMakeDumpCsv:
    def test_csv_roundtrip_default_space_delimiter(self, tmp_path):
        stdin = "\n".join(
            [
                "00000000000000000000000000000005 100 hello",
                "00000000000000000000000000000005 200 world",
                "",
            ]
        )
        rc, out, err = _tdb(
            "make",
            "-c",
            "-o",
            "csv",
            "-f",
            "uuid,time,greeting",
            stdin=stdin,
            cwd=tmp_path,
        )
        assert rc == 0, err
        rc, out, err = _tdb("dump", "-c", "-i", "csv", cwd=tmp_path)
        assert rc == 0, err
        assert out == (
            "00000000000000000000000000000005 100 hello\n"
            "00000000000000000000000000000005 200 world\n"
        )


class TestCliMultipleTrails:
    def test_two_uuids_dump_preserves_all_events(self, tmp_path):
        stdin = "\n".join(
            [
                '{"uuid":"00000000000000000000000000000001","time":"1","x":"a"}',
                '{"uuid":"00000000000000000000000000000001","time":"2","x":"b"}',
                '{"uuid":"00000000000000000000000000000001","time":"3","x":"c"}',
                '{"uuid":"00000000000000000000000000000002","time":"10","x":"d"}',
                '{"uuid":"00000000000000000000000000000002","time":"20","x":"e"}',
                '{"uuid":"00000000000000000000000000000002","time":"30","x":"f"}',
                "",
            ]
        )
        rc, out, err = _tdb(
            "make", "-j", "-o", "multi", "-f", "uuid,time,x", stdin=stdin, cwd=tmp_path
        )
        assert rc == 0, err
        rc, out, err = _tdb("dump", "-j", "-i", "multi", cwd=tmp_path)
        assert rc == 0, err
        # Trails dumped one at a time, each in timestamp order.
        lines = out.strip().splitlines()
        assert len(lines) == 6
        # First 3 lines belong to trail 1 (uuid ...01) in order a,b,c.
        assert '"x": "a"' in lines[0] and '"time": "1"' in lines[0]
        assert '"x": "b"' in lines[1] and '"time": "2"' in lines[1]
        assert '"x": "c"' in lines[2] and '"time": "3"' in lines[2]
        # Next 3 belong to trail 2 (uuid ...02) in order d,e,f.
        assert '"x": "d"' in lines[3] and '"time": "10"' in lines[3]
        assert '"x": "e"' in lines[4] and '"time": "20"' in lines[4]
        assert '"x": "f"' in lines[5] and '"time": "30"' in lines[5]


class TestCliCsvHeader:
    def test_csv_header_reads_field_names_from_first_row(self, tmp_path):
        stdin = "\n".join(
            [
                "uuid time category",
                "00000000000000000000000000000001 5 alpha",
                "00000000000000000000000000000001 15 beta",
                "",
            ]
        )
        rc, out, err = _tdb(
            "make", "-c", "-o", "hdr", "--csv-header", stdin=stdin, cwd=tmp_path
        )
        assert rc == 0, err
        rc, out, err = _tdb("dump", "-j", "-i", "hdr", cwd=tmp_path)
        assert rc == 0, err
        assert out == (
            '{"uuid": "00000000000000000000000000000001", "time": "5", "category": "alpha"}\n'
            '{"uuid": "00000000000000000000000000000001", "time": "15", "category": "beta"}\n'
        )


class TestCliPackageFormat:
    def test_pkg_format_produces_single_tar_file(self, tmp_path):
        stdin = '{"uuid":"00000000000000000000000000000001","time":"1","x":"y"}\n'
        rc, out, err = _tdb(
            "make",
            "-j",
            "-o",
            "p",
            "--tdb-format=pkg",
            "-f",
            "uuid,time,x",
            stdin=stdin,
            cwd=tmp_path,
        )
        assert rc == 0, err
        pkg = tmp_path / "p.tdb"
        assert pkg.is_file(), f"expected p.tdb file, got: {list(tmp_path.iterdir())}"
        # tdb dump on the packaged file must round-trip.
        rc, out, err = _tdb("dump", "-j", "-i", "p", cwd=tmp_path)
        assert rc == 0, err
        assert (
            out
            == '{"uuid": "00000000000000000000000000000001", "time": "1", "x": "y"}\n'
        )


class TestCliDirFormat:
    def test_dir_format_produces_directory_with_expected_members(self, tmp_path):
        stdin = '{"uuid":"00000000000000000000000000000001","time":"1","x":"y"}\n'
        rc, out, err = _tdb(
            "make",
            "-j",
            "-o",
            "d",
            "--tdb-format=dir",
            "-f",
            "uuid,time,x",
            stdin=stdin,
            cwd=tmp_path,
        )
        assert rc == 0, err
        d = tmp_path / "d"
        assert d.is_dir(), f"expected d/ directory, got: {list(tmp_path.iterdir())}"
        members = {p.name for p in d.iterdir()}
        # A traildb directory must ship at least these logical files.
        expected_subset = {"info", "fields", "version", "uuids", "trails.data"}
        assert (
            expected_subset <= members
        ), f"missing files in dir tdb: {expected_subset - members}"
        rc, out, err = _tdb("dump", "-j", "-i", "d", cwd=tmp_path)
        assert rc == 0, err
        assert (
            out
            == '{"uuid": "00000000000000000000000000000001", "time": "1", "x": "y"}\n'
        )


class TestCliNoBigrams:
    def test_no_bigrams_roundtrips_all_events(self, tmp_path):
        # 200 events with 2 alternating values -- default bigram path would kick
        # in; --no-bigrams must still produce a readable tdb.
        lines = []
        for i in range(200):
            v = "hello" if i % 2 else "world"
            lines.append(
                '{"uuid":"00000000000000000000000000000001","time":"'
                + str(i + 1)
                + '","w":"'
                + v
                + '"}'
            )
        stdin = "\n".join(lines) + "\n"
        rc, out, err = _tdb(
            "make",
            "-j",
            "-o",
            "nb",
            "--no-bigrams",
            "-f",
            "uuid,time,w",
            stdin=stdin,
            cwd=tmp_path,
        )
        assert rc == 0, err
        rc, out, err = _tdb("dump", "-j", "-i", "nb", cwd=tmp_path)
        assert rc == 0, err
        # --no-bigrams must dump back byte-for-byte identically at the event
        # level: single trail (uuid ...0001), ascending times 1..200, w
        # alternating world/hello. A count-only check would pass a path that
        # emits 200 lines but corrupts values or reorders timestamps.
        expected = "".join(
            '{"uuid": "00000000000000000000000000000001", "time": "'
            + str(i + 1)
            + '", "w": "'
            + ("world" if i % 2 == 0 else "hello")
            + '"}\n'
            for i in range(200)
        )
        assert out == expected


class TestCliFilterEqualsAndNegation:
    def test_positive_and_negative_filter_terms(self, tmp_path):
        stdin = "\n".join(
            [
                '{"uuid":"00000000000000000000000000000001","time":"1","letter":"a"}',
                '{"uuid":"00000000000000000000000000000001","time":"2","letter":"b"}',
                '{"uuid":"00000000000000000000000000000001","time":"3","letter":"c"}',
                '{"uuid":"00000000000000000000000000000001","time":"4","letter":"b"}',
                '{"uuid":"00000000000000000000000000000001","time":"5","letter":"a"}',
                "",
            ]
        )
        rc, out, err = _tdb(
            "make",
            "-j",
            "-o",
            "fltr",
            "-f",
            "uuid,time,letter",
            stdin=stdin,
            cwd=tmp_path,
        )
        assert rc == 0, err

        # Positive: letter=a.
        rc, out, err = _tdb(
            "dump", "-j", "-i", "fltr", "-F", "letter=a", "--no-index", cwd=tmp_path
        )
        assert rc == 0, err
        assert out.count('"letter": "a"') == 2
        assert out.count('"letter": "b"') == 0
        assert out.count('"letter": "c"') == 0

        # Negative: letter!=b (keeps a, c).
        rc, out, err = _tdb(
            "dump", "-j", "-i", "fltr", "-F", "letter!=b", "--no-index", cwd=tmp_path
        )
        assert rc == 0, err
        assert out.count('"letter": "a"') == 2
        assert out.count('"letter": "b"') == 0
        assert out.count('"letter": "c"') == 1


class TestCliFilterOrAnd:
    def test_or_within_clause_and_across_clauses(self, tmp_path):
        stdin = "\n".join(
            [
                '{"uuid":"00000000000000000000000000000001","time":"1","country":"US","action":"click"}',
                '{"uuid":"00000000000000000000000000000001","time":"2","country":"US","action":"view"}',
                '{"uuid":"00000000000000000000000000000001","time":"3","country":"FR","action":"click"}',
                '{"uuid":"00000000000000000000000000000001","time":"4","country":"US","action":"click"}',
                '{"uuid":"00000000000000000000000000000001","time":"5","country":"FR","action":"view"}',
                "",
            ]
        )
        rc, out, err = _tdb(
            "make",
            "-j",
            "-o",
            "aa",
            "-f",
            "uuid,time,country,action",
            stdin=stdin,
            cwd=tmp_path,
        )
        assert rc == 0, err

        # OR (whitespace) -- country=US OR action=view -> 4 events (t=1,2,4,5).
        rc, out, err = _tdb(
            "dump",
            "-j",
            "-i",
            "aa",
            "-F",
            "country=US action=view",
            "--no-index",
            cwd=tmp_path,
        )
        assert rc == 0, err
        # country=US OR action=view matches events at t=1,2,4,5, dumped in
        # ascending timestamp order. Assert the exact matched set (not just the
        # count) so a filter returning 4 wrong events is caught -- mirroring
        # the AND branch below.
        lines = out.strip().splitlines()
        assert len(lines) == 4
        assert '"time": "1"' in lines[0]
        assert '"time": "2"' in lines[1]
        assert '"time": "4"' in lines[2]
        assert '"time": "5"' in lines[3]

        # AND (&) -- country=US AND action=click -> 2 events (t=1, 4).
        rc, out, err = _tdb(
            "dump",
            "-j",
            "-i",
            "aa",
            "-F",
            "country=US & action=click",
            "--no-index",
            cwd=tmp_path,
        )
        assert rc == 0, err
        lines = out.strip().splitlines()
        assert len(lines) == 2
        assert '"time": "1"' in lines[0]
        assert '"time": "4"' in lines[1]


class TestCliMerge:
    def test_merge_two_tdbs_combines_events(self, tmp_path):
        rc, _, err = _tdb(
            "make",
            "-j",
            "-o",
            "left",
            "-f",
            "uuid,time,tag",
            stdin='{"uuid":"00000000000000000000000000000001","time":"1","tag":"a"}\n'
            '{"uuid":"00000000000000000000000000000001","time":"2","tag":"b"}\n',
            cwd=tmp_path,
        )
        assert rc == 0, err
        rc, _, err = _tdb(
            "make",
            "-j",
            "-o",
            "right",
            "-f",
            "uuid,time,tag",
            stdin='{"uuid":"00000000000000000000000000000002","time":"5","tag":"c"}\n',
            cwd=tmp_path,
        )
        assert rc == 0, err
        rc, _, err = _tdb("merge", "-o", "merged", "left", "right", cwd=tmp_path)
        assert rc == 0, err
        rc, out, err = _tdb("dump", "-j", "-i", "merged", cwd=tmp_path)
        assert rc == 0, err
        lines = out.strip().splitlines()
        assert len(lines) == 3
        assert any('"tag": "a"' in ln for ln in lines)
        assert any('"tag": "b"' in ln for ln in lines)
        assert any('"tag": "c"' in ln for ln in lines)


class TestCliErrorPaths:
    def test_missing_input_exits_nonzero_with_diagnostic(self, tmp_path):
        rc, out, err = _tdb("dump", "-j", "-i", "does_not_exist", cwd=tmp_path)
        assert rc != 0
        combined = out + err
        # Error text may go to stdout or stderr; accept either.
        assert "TDB_ERR" in combined or "failed" in combined.lower()


# ===========================================================================
# C-driver tests
# ===========================================================================


class TestLexicon:
    def test_lexicon_size_and_value_lookup(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "lex");
    const char *fields[] = {"country"};
    const uint64_t lens[] = {2};
    uint8_t u[16]; mk_uuid(u, 1);

    const char *countries[] = {"US", "FR", "US", "DE", "FR"};
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    for (int i = 0; i < 5; i++) {
        const char *v[] = {countries[i]};
        tdb_cons_add(c, u, (uint64_t)(i + 1), v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    /* lexicon_size counts distinct values PLUS the implicit empty value slot. */
    printf("lex_size=%llu\n", (unsigned long long)tdb_lexicon_size(db, 1));

    tdb_field f;
    tdb_get_field(db, "country", &f);
    tdb_item it = tdb_get_item(db, f, "FR", 2);
    uint64_t vl = 0;
    const char *val = tdb_get_item_value(db, it, &vl);
    printf("item_value=%.*s len=%llu\n", (int)vl, val, (unsigned long long)vl);

    /* Unknown value returns item==0 (empty value). */
    tdb_item miss = tdb_get_item(db, f, "ZZ", 2);
    printf("unknown_item=%llu\n", (unsigned long long)miss);
    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        # 3 distinct values (US, FR, DE) + 1 empty slot = 4.
        assert out == "lex_size=4\nitem_value=FR len=2\nunknown_item=0\n"


class TestUuidRoundtrip:
    def test_hex_raw_and_trail_id(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "uuid");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 42);

    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    const char *v[] = {"x"};
    tdb_cons_add(c, u, 1, v, lens);
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    uint64_t tid = 999;
    if (tdb_get_trail_id(db, u, &tid)) DIE("trail_id");
    printf("trail_id=%llu\n", (unsigned long long)tid);

    uint8_t hex[32];
    tdb_uuid_hex(u, hex);
    printf("hex=%.32s\n", hex);
    uint8_t back[16];
    if (tdb_uuid_raw(hex, back)) DIE("uuid_raw");
    printf("roundtrip=%d\n", memcmp(u, back, 16) == 0);
    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        expected_hex = "".join(f"{b:02x}" for b in range(42, 42 + 16))
        assert out == f"trail_id=0\nhex={expected_hex}\nroundtrip=1\n"


class TestCursorIteration:
    def test_iterate_trail_in_timestamp_order(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "cursor");
    const char *fields[] = {"tag"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);

    /* Insert out of order; cursor must yield in ascending timestamp order. */
    uint64_t times[] = {50, 10, 30, 20, 40};
    const char *tags[] = {"e", "a", "c", "b", "d"};
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    for (int i = 0; i < 5; i++) {
        const char *v[] = {tags[i]};
        tdb_cons_add(c, u, times[i], v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    tdb_cursor *cur = tdb_cursor_new(db);
    if (tdb_get_trail(cur, 0)) DIE("get_trail");
    printf("length=%llu\n", (unsigned long long)tdb_get_trail_length(cur));

    /* get_trail_length consumed the events; reset by calling get_trail again. */
    tdb_get_trail(cur, 0);
    const tdb_event *ev;
    while ((ev = tdb_cursor_next(cur))) {
        uint64_t vl;
        const char *val = tdb_get_item_value(db, ev->items[0], &vl);
        printf("t=%llu tag=%.*s\n", (unsigned long long)ev->timestamp, (int)vl, val);
    }
    tdb_cursor_free(cur); tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == (
            "length=5\n"
            "t=10 tag=a\n"
            "t=20 tag=b\n"
            "t=30 tag=c\n"
            "t=40 tag=d\n"
            "t=50 tag=e\n"
        )

    def test_cursor_peek_does_not_advance(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "peek");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    const char *v1[] = {"x"}; tdb_cons_add(c, u, 1, v1, lens);
    const char *v2[] = {"y"}; tdb_cons_add(c, u, 2, v2, lens);
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    tdb_cursor *cur = tdb_cursor_new(db); tdb_get_trail(cur, 0);
    const tdb_event *p = tdb_cursor_peek(cur);
    printf("peek1=%llu\n", (unsigned long long)p->timestamp);
    const tdb_event *p2 = tdb_cursor_peek(cur);
    printf("peek2=%llu\n", (unsigned long long)p2->timestamp);
    const tdb_event *n = tdb_cursor_next(cur);
    printf("next1=%llu\n", (unsigned long long)n->timestamp);
    const tdb_event *n2 = tdb_cursor_next(cur);
    printf("next2=%llu\n", (unsigned long long)n2->timestamp);
    printf("end=%p\n", (void*)tdb_cursor_next(cur));
    tdb_cursor_free(cur); tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == "peek1=1\npeek2=1\nnext1=1\nnext2=2\nend=(nil)\n"


class TestEventFilterTermSemantics:
    """Both filter-term shapes -- OR of positive terms and a negative term --
    against the same 5-event letter fixture (a, b, c, b, a). Bundles the two
    single-clause matching modes that share a fixture; a broken matcher
    surfaces via either sub-check."""

    def test_positive_or_and_negative_term_against_letter_fixture(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "filter_terms");
    const char *fields[] = {"letter"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    const char *letters[] = {"a", "b", "c", "b", "a"};
    for (int i = 0; i < 5; i++) {
        const char *v[] = {letters[i]};
        tdb_cons_add(c, u, (uint64_t)(i + 1), v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    tdb_field f; tdb_get_field(db, "letter", &f);
    tdb_item it_a = tdb_get_item(db, f, "a", 1);
    tdb_item it_b = tdb_get_item(db, f, "b", 1);

    /* --- 1. Positive OR: match letter=a OR letter=b (single clause). --- */
    struct tdb_event_filter *pos = tdb_event_filter_new();
    tdb_event_filter_add_term(pos, it_a, 0);
    tdb_event_filter_add_term(pos, it_b, 0);

    tdb_cursor *cur = tdb_cursor_new(db);
    tdb_cursor_set_event_filter(cur, pos);
    tdb_get_trail(cur, 0);
    printf("or:");
    const tdb_event *ev;
    while ((ev = tdb_cursor_next(cur))) {
        uint64_t vl;
        const char *val = tdb_get_item_value(db, ev->items[0], &vl);
        printf(" %llu%.*s", (unsigned long long)ev->timestamp, (int)vl, val);
    }
    printf("\n");
    tdb_event_filter_free(pos);
    tdb_cursor_free(cur);

    /* --- 2. Negative: match NOT letter=b (single negative term). --- */
    struct tdb_event_filter *neg = tdb_event_filter_new();
    tdb_event_filter_add_term(neg, it_b, 1);

    cur = tdb_cursor_new(db);
    tdb_cursor_set_event_filter(cur, neg);
    tdb_get_trail(cur, 0);
    printf("neg:");
    while ((ev = tdb_cursor_next(cur))) {
        uint64_t vl;
        const char *val = tdb_get_item_value(db, ev->items[0], &vl);
        printf(" %llu%.*s", (unsigned long long)ev->timestamp, (int)vl, val);
    }
    printf("\n");
    tdb_event_filter_free(neg);
    tdb_cursor_free(cur);
    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        # OR of {a,b} matches events at t=1,2,4,5.
        # NOT b matches events at t=1,3,5.
        assert out == "or: 1a 2b 4b 5a\nneg: 1a 3c 5a\n"


class TestEventFilterMultiClause:
    def test_and_of_two_clauses(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "filter_and");
    const char *fields[] = {"country", "action"};
    const uint64_t lens[] = {2, 5};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 2);
    struct { const char *ctry; const char *act; uint64_t t; } E[] = {
        {"US", "click", 1},
        {"US", "view",  2},
        {"FR", "click", 3},
        {"US", "click", 4},
        {"FR", "view",  5},
    };
    for (int i = 0; i < 5; i++) {
        const char *v[] = {E[i].ctry, E[i].act};
        tdb_cons_add(c, u, E[i].t, v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    tdb_field fc, fa; tdb_get_field(db, "country", &fc); tdb_get_field(db, "action", &fa);
    tdb_item us = tdb_get_item(db, fc, "US", 2);
    tdb_item click = tdb_get_item(db, fa, "click", 5);

    /* country = US AND action = click. */
    struct tdb_event_filter *filt = tdb_event_filter_new();
    tdb_event_filter_add_term(filt, us, 0);
    tdb_event_filter_new_clause(filt);
    tdb_event_filter_add_term(filt, click, 0);

    tdb_cursor *cur = tdb_cursor_new(db);
    tdb_cursor_set_event_filter(cur, filt);
    tdb_get_trail(cur, 0);
    const tdb_event *ev;
    while ((ev = tdb_cursor_next(cur)))
        printf("%llu\n", (unsigned long long)ev->timestamp);
    tdb_event_filter_free(filt);
    tdb_cursor_free(cur); tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == "1\n4\n"


class TestEventFilterTimeRange:
    def test_time_range_inclusive_start_exclusive_end(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "filter_time");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    for (int i = 0; i < 10; i++) {
        const char *v[] = {"x"};
        tdb_cons_add(c, u, (uint64_t)(i * 10), v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    struct tdb_event_filter *filt = tdb_event_filter_new();
    /* start <= t < end : 20 .. 60 exclusive. */
    tdb_event_filter_add_time_range(filt, 20, 60);

    tdb_cursor *cur = tdb_cursor_new(db);
    tdb_cursor_set_event_filter(cur, filt);
    tdb_get_trail(cur, 0);
    const tdb_event *ev;
    while ((ev = tdb_cursor_next(cur)))
        printf("%llu\n", (unsigned long long)ev->timestamp);
    tdb_event_filter_free(filt);
    tdb_cursor_free(cur); tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == "20\n30\n40\n50\n"


class TestEventFilterMatchAllNone:
    def test_match_all_and_none(self, tmp_path):
        body = r"""
static int count_matches(tdb *db, struct tdb_event_filter *filt) {
    tdb_cursor *cur = tdb_cursor_new(db);
    tdb_cursor_set_event_filter(cur, filt);
    tdb_get_trail(cur, 0);
    int n = 0;
    while (tdb_cursor_next(cur)) n++;
    tdb_cursor_free(cur);
    return n;
}

int main(void) {
    char path[512]; path_of(path, "filter_allnone");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    for (int i = 0; i < 4; i++) {
        const char *v[] = {"x"};
        tdb_cons_add(c, u, (uint64_t)(i + 1), v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    struct tdb_event_filter *all = tdb_event_filter_new_match_all();
    struct tdb_event_filter *none = tdb_event_filter_new_match_none();
    printf("all=%d\n", count_matches(db, all));
    printf("none=%d\n", count_matches(db, none));
    tdb_event_filter_free(all);
    tdb_event_filter_free(none);
    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == "all=4\nnone=0\n"


class TestEventFilterIntrospection:
    def test_num_clauses_num_terms_and_get_item(self, tmp_path):
        body = r"""
int main(void) {
    /* Build a filter with 2 clauses:
         clause 0: item=5 (positive), item=9 (negative)
         clause 1: time_range [10, 20)
    */
    struct tdb_event_filter *f = tdb_event_filter_new();
    tdb_event_filter_add_term(f, 5, 0);
    tdb_event_filter_add_term(f, 9, 1);
    tdb_event_filter_new_clause(f);
    tdb_event_filter_add_time_range(f, 10, 20);

    printf("num_clauses=%llu\n", (unsigned long long)tdb_event_filter_num_clauses(f));

    uint64_t n0 = 0, n1 = 0;
    tdb_event_filter_num_terms(f, 0, &n0);
    tdb_event_filter_num_terms(f, 1, &n1);
    printf("num_terms=%llu,%llu\n", (unsigned long long)n0, (unsigned long long)n1);

    tdb_item it; int neg = -1;
    tdb_event_filter_get_item(f, 0, 0, &it, &neg);
    printf("c0t0=item=%llu neg=%d\n", (unsigned long long)it, neg);
    tdb_event_filter_get_item(f, 0, 1, &it, &neg);
    printf("c0t1=item=%llu neg=%d\n", (unsigned long long)it, neg);

    tdb_event_filter_term_type tt;
    tdb_event_filter_get_term_type(f, 0, 0, &tt);
    printf("c0t0_type=%d\n", (int)tt);
    tdb_event_filter_get_term_type(f, 1, 0, &tt);
    printf("c1t0_type=%d\n", (int)tt);

    uint64_t s, e;
    tdb_event_filter_get_time_range(f, 1, 0, &s, &e);
    printf("time_range=%llu-%llu\n", (unsigned long long)s, (unsigned long long)e);

    tdb_event_filter_free(f);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        # TDB_EVENT_FILTER_MATCH_TERM=1, TDB_EVENT_FILTER_TIME_RANGE_TERM=2.
        assert out == (
            "num_clauses=2\n"
            "num_terms=2,1\n"
            "c0t0=item=5 neg=0\n"
            "c0t1=item=9 neg=1\n"
            "c0t0_type=1\n"
            "c1t0_type=2\n"
            "time_range=10-20\n"
        )


class TestMultiCursorMergeAndPeek:
    """Multi-cursor over two trails: verify (1) peek returns the earliest
    event across cursors without advancing (invoked twice; both peeks return
    the same event) and (2) next then yields every event in global
    timestamp order, tagging each with its source cursor_idx. Bundles the
    two multi-cursor contracts (peek + merge) into one two-trail fixture."""

    def test_peek_is_stable_then_next_merges_in_timestamp_order(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "multi_merge_peek");
    const char *fields[] = {"letter"};
    const uint64_t lens[] = {1};
    uint8_t u1[16], u2[16]; mk_uuid(u1, 1); mk_uuid(u2, 2);
    tdb_cons *c = tdb_cons_init();
    tdb_cons_open(c, path, fields, 1);
    /* trail 0: (10 a) (30 c) (50 e) ; trail 1: (20 b) (40 d) (60 f)
       Earliest event across both is t=10 on trail 0. */
    const char *a[] = {"a"}; tdb_cons_add(c, u1, 10, a, lens);
    const char *c1[] = {"c"}; tdb_cons_add(c, u1, 30, c1, lens);
    const char *e[] = {"e"}; tdb_cons_add(c, u1, 50, e, lens);
    const char *b[] = {"b"}; tdb_cons_add(c, u2, 20, b, lens);
    const char *d[] = {"d"}; tdb_cons_add(c, u2, 40, d, lens);
    const char *f[] = {"f"}; tdb_cons_add(c, u2, 60, f, lens);
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    tdb_cursor *c0 = tdb_cursor_new(db); tdb_get_trail(c0, 0);
    tdb_cursor *c1c = tdb_cursor_new(db); tdb_get_trail(c1c, 1);
    tdb_cursor *cs[2] = {c0, c1c};
    tdb_multi_cursor *mc = tdb_multi_cursor_new(cs, 2);
    tdb_multi_cursor_reset(mc);

    /* --- 1. peek is stable: two peeks return the same head. --- */
    const tdb_multi_event *p1 = tdb_multi_cursor_peek(mc);
    const tdb_multi_event *p2 = tdb_multi_cursor_peek(mc);
    printf("peek1 t=%llu cur=%llu\n",
        (unsigned long long)p1->event->timestamp,
        (unsigned long long)p1->cursor_idx);
    printf("peek2 t=%llu cur=%llu\n",
        (unsigned long long)p2->event->timestamp,
        (unsigned long long)p2->cursor_idx);

    /* --- 2. next then merges all 6 events in global timestamp order. --- */
    const tdb_multi_event *me;
    while ((me = tdb_multi_cursor_next(mc))) {
        uint64_t vl;
        const char *val = tdb_get_item_value(me->db, me->event->items[0], &vl);
        printf("t=%llu cur=%llu tag=%.*s\n",
            (unsigned long long)me->event->timestamp,
            (unsigned long long)me->cursor_idx,
            (int)vl, val);
    }
    tdb_multi_cursor_free(mc);
    tdb_cursor_free(c0); tdb_cursor_free(c1c);
    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == (
            "peek1 t=10 cur=0\n"
            "peek2 t=10 cur=0\n"
            "t=10 cur=0 tag=a\n"
            "t=20 cur=1 tag=b\n"
            "t=30 cur=0 tag=c\n"
            "t=40 cur=1 tag=d\n"
            "t=50 cur=0 tag=e\n"
            "t=60 cur=1 tag=f\n"
        )


class TestConsAppend:
    def test_append_preserves_events_and_lexicon(self, tmp_path):
        body = r"""
int main(void) {
    char p1[512], p2[512]; path_of(p1, "src"); path_of(p2, "dst");
    const char *fields[] = {"tag"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);

    tdb_cons *c1 = tdb_cons_init();
    tdb_cons_open(c1, p1, fields, 1);
    const char *a[] = {"a"}; tdb_cons_add(c1, u, 1, a, lens);
    const char *b[] = {"b"}; tdb_cons_add(c1, u, 2, b, lens);
    tdb_cons_finalize(c1); tdb_cons_close(c1);
    tdb *src = tdb_init(); tdb_open(src, p1);

    tdb_cons *c2 = tdb_cons_init();
    tdb_cons_open(c2, p2, fields, 1);
    /* add one native event, then append src (2 events). */
    const char *z[] = {"z"}; tdb_cons_add(c2, u, 100, z, lens);
    if (tdb_cons_append(c2, src)) DIE("append");
    tdb_cons_finalize(c2); tdb_cons_close(c2);
    tdb_close(src);

    tdb *dst = tdb_init(); tdb_open(dst, p2);
    printf("events=%llu\n", (unsigned long long)tdb_num_events(dst));
    printf("lex=%llu\n", (unsigned long long)tdb_lexicon_size(dst, 1));
    tdb_cursor *cur = tdb_cursor_new(dst);
    tdb_get_trail(cur, 0);
    const tdb_event *ev;
    while ((ev = tdb_cursor_next(cur))) {
        uint64_t vl;
        const char *val = tdb_get_item_value(dst, ev->items[0], &vl);
        printf("%llu:%.*s\n", (unsigned long long)ev->timestamp, (int)vl, val);
    }
    tdb_cursor_free(cur); tdb_close(dst);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        # 3 events (1 native + 2 appended). lex has {a,b,z} + empty slot = 4.
        assert out == "events=3\nlex=4\n1:a\n2:b\n100:z\n"


class TestOptionsApi:
    """Both halves of the tdb_set_opt / tdb_get_opt contract on one open
    reader: the happy roundtrip on a known key (TDB_OPT_ONLY_DIFF_ITEMS
    stored and read back exactly), and the error path when the key is
    unrecognised (must return TDB_ERR_UNKNOWN_OPTION = -9 without
    corrupting reader state)."""

    def test_valid_key_roundtrips_and_unknown_key_returns_minus_9(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "opts");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init(); tdb_cons_open(c, path, fields, 1);
    const char *v[] = {"x"}; tdb_cons_add(c, u, 1, v, lens);
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);

    /* --- 1. Valid key: set then get returns the same value. --- */
    tdb_opt_value val_in = {.value = 1};
    if (tdb_set_opt(db, TDB_OPT_ONLY_DIFF_ITEMS, val_in)) DIE("set(known)");
    tdb_opt_value val_out;
    if (tdb_get_opt(db, TDB_OPT_ONLY_DIFF_ITEMS, &val_out)) DIE("get(known)");
    printf("known=%llu\n", (unsigned long long)val_out.value);

    /* --- 2. Unknown key: set returns TDB_ERR_UNKNOWN_OPTION = -9. --- */
    tdb_opt_value bogus = {.value = 1};
    int err = tdb_set_opt(db, (tdb_opt_key)7777, bogus);
    printf("unknown_err=%d\n", err);

    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == "known=1\nunknown_err=-9\n"


class TestOnlyDiffItems:
    def test_diff_items_suppresses_repeated_values(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "diff");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init(); tdb_cons_open(c, path, fields, 1);
    const char *xs[] = {"x", "x", "y", "y", "x"};
    for (int i = 0; i < 5; i++) {
        const char *v[] = {xs[i]};
        tdb_cons_add(c, u, (uint64_t)(i + 1), v, lens);
    }
    tdb_cons_finalize(c); tdb_cons_close(c);

    tdb *db = tdb_init(); tdb_open(db, path);
    tdb_opt_value on = {.value = 1};
    tdb_set_opt(db, TDB_OPT_ONLY_DIFF_ITEMS, on);
    tdb_cursor *cur = tdb_cursor_new(db); tdb_get_trail(cur, 0);
    const tdb_event *ev;
    while ((ev = tdb_cursor_next(cur))) {
        printf("t=%llu items=%llu\n",
            (unsigned long long)ev->timestamp,
            (unsigned long long)ev->num_items);
    }
    tdb_cursor_free(cur); tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        # ONLY_DIFF_ITEMS: an event only emits an item when its value changed
        # from the previous event on the same trail. Sequence x,x,y,y,x:
        # t=1 emits x (new), t=2 emits nothing, t=3 emits y, t=4 emits nothing,
        # t=5 emits x. Every event still appears with its timestamp; num_items
        # is 0 for unchanged, 1 for changed.
        assert out == (
            "t=1 items=1\n"
            "t=2 items=0\n"
            "t=3 items=1\n"
            "t=4 items=0\n"
            "t=5 items=1\n"
        )


class TestItemPacking:
    def test_narrow_and_wide_item_encoding(self, tmp_path):
        body = r"""
int main(void) {
    /* is32 is a predicate: the contract is "nonzero = narrow", so normalize
       with !! -- any conforming nonzero narrow return passes, not just 1. */
    /* Narrow item: field in [1, 127], val in [0, 2^24 - 1]. */
    tdb_item n = tdb_make_item(5, 42);
    printf("narrow_field=%u val=%llu is32=%d\n",
        tdb_item_field(n),
        (unsigned long long)tdb_item_val(n),
        !!tdb_item_is32(n));

    /* Wide item: field > 127 forces wide encoding, and val can be up to 2^40 - 1. */
    tdb_item w = tdb_make_item(200, 0x100000000ULL); /* 2^32 */
    printf("wide_field=%u val=%llu is32=%d\n",
        tdb_item_field(w),
        (unsigned long long)tdb_item_val(w),
        !!tdb_item_is32(w));
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == (
            "narrow_field=5 val=42 is32=1\n" "wide_field=200 val=4294967296 is32=0\n"
        )


class TestErrorString:
    def test_error_str_covers_common_codes(self, tmp_path):
        body = r"""
int main(void) {
    /* Contract: tdb_error_str returns a NON-NULL, non-empty human string
       for every defined error code, INCLUDING TDB_ERR_OK = 0. */
    const char *ok = tdb_error_str(TDB_ERR_OK);
    const char *nomem = tdb_error_str(TDB_ERR_NOMEM);
    const char *uf = tdb_error_str(TDB_ERR_UNKNOWN_FIELD);
    const char *fm = tdb_error_str(TDB_ERR_APPEND_FIELDS_MISMATCH);
    printf("ok_nonempty=%d\n", ok && ok[0] ? 1 : 0);
    printf("nomem_nonempty=%d\n", nomem && nomem[0] ? 1 : 0);
    printf("uf_nonempty=%d\n", uf && uf[0] ? 1 : 0);
    printf("fm_nonempty=%d\n", fm && fm[0] ? 1 : 0);
    /* Distinct codes must map to distinct strings: a constant-returning stub
       (same text for every code) fails this. Checks the mapping, not shape. */
    const char *s[4] = {ok, nomem, uf, fm};
    int all_distinct = 1;
    for (int i = 0; i < 4; i++)
        for (int j = i + 1; j < 4; j++)
            if (strcmp(s[i], s[j]) == 0) all_distinct = 0;
    printf("all_distinct=%d\n", all_distinct);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        assert out == (
            "ok_nonempty=1\n"
            "nomem_nonempty=1\n"
            "uf_nonempty=1\n"
            "fm_nonempty=1\n"
            "all_distinct=1\n"
        )


class TestReaderErrors:
    def test_get_trail_id_unknown_uuid(self, tmp_path):
        body = r"""
int main(void) {
    char path[512]; path_of(path, "u");
    const char *fields[] = {"a"};
    const uint64_t lens[] = {1};
    uint8_t u[16]; mk_uuid(u, 1);
    tdb_cons *c = tdb_cons_init(); tdb_cons_open(c, path, fields, 1);
    const char *v[] = {"x"}; tdb_cons_add(c, u, 1, v, lens);
    tdb_cons_finalize(c); tdb_cons_close(c);
    tdb *db = tdb_init(); tdb_open(db, path);

    uint8_t missing[16] = {0}; /* all zeros -- not in the tdb */
    uint64_t tid = 0;
    int err = tdb_get_trail_id(db, missing, &tid);
    printf("err=%d\n", err);
    tdb_close(db);
    return 0;
}
"""
        rc, out, err = _run_c(tmp_path, body)
        assert rc == 0, err
        # TDB_ERR_UNKNOWN_UUID = -5.
        assert out == "err=-5\n"


# ===========================================================================
# Performance-contract tests (compression + index locality). These check
# properties the library's Performance contract section of instruction.md
# advertises: sublinear-in-events on-disk size (via general-purpose
# compression + a codebook amortising over the trail data), and
# sublinear-in-trails UUID lookup (via a hash / tree / trie index rather
# than a linear scan). Fixtures are deliberately clickstream-shaped with
# high value repetition; naive-JSON / linear-scan implementations fail,
# any implementation that honours the contract passes with wide margin.
# ===========================================================================


import json as _json
import random as _random


def _clickstream(n_events, seed=42):
    """Deterministic clickstream fixture: 500 UUIDs x 10 events x 20 URLs.
    Values are highly repetitive so compression is meaningful."""
    r = _random.Random(seed)
    users = [f"{i:032x}" for i in range(500)]
    events = [
        "click",
        "view",
        "convert",
        "hover",
        "scroll",
        "buy",
        "share",
        "like",
        "search",
        "logout",
    ]
    urls = [f"/page/{i}" for i in range(20)]
    out = []
    t = 1_000_000_000
    for _ in range(n_events):
        t += r.randint(1, 100)
        out.append(
            {
                "uuid": r.choice(users),
                "time": str(t),
                "event": r.choice(events),
                "url": r.choice(urls),
            }
        )
    return out


def _raw_bytes(events):
    """Naive lower-bound byte count for the fixture: sum of string field
    bytes across all events. A JSON-per-line writer would emit ~2x this;
    a raw-tsv writer roughly this. Any implementation whose on-disk size
    stays close to (or below) this figure at scale must be doing real
    compression."""
    return sum(len(v) if isinstance(v, str) else 8 for e in events for v in e.values())


def _build_via_cli(events, out_name, tmp_path, extra_flags=()):
    """Build a TDB from `events` via `tdb make -j`. Return the on-disk
    size of the produced .tdb file."""
    stdin = "\n".join(_json.dumps(e) for e in events) + "\n"
    cmd = ["tdb", "make", "-j", "-o", out_name, "-f", "uuid,time,event,url"] + list(
        extra_flags
    )
    r = subprocess.run(
        cmd, input=stdin, capture_output=True, text=True, timeout=600, cwd=str(tmp_path)
    )
    assert r.returncode == 0, f"tdb make failed: {r.stderr}"
    p = tmp_path / f"{out_name}.tdb"
    assert p.is_file(), f"expected {out_name}.tdb, got: {list(tmp_path.iterdir())}"
    return p.stat().st_size


class TestCompressionRatioAtScale:
    def test_100k_events_compress_below_0_45x_raw(self, tmp_path):
        events = _clickstream(100_000)
        raw = _raw_bytes(events)
        tdb_size = _build_via_cli(events, "big", tmp_path)
        ratio = tdb_size / raw
        assert ratio <= 0.45, (
            f"compression too weak: tdb_size={tdb_size} raw={raw} "
            f"ratio={ratio:.3f} (must be <= 0.45)"
        )


class TestSizeScaling:
    def test_size_grows_far_sublinearly_with_events(self, tmp_path):
        # Same event stream at two scales 100x apart: with one seed the 1k
        # fixture is a prefix of the 100k one (identical RNG sequence), so the
        # 99k extra events are pure "more of the same" growth, not cross-seed
        # content noise. Per the compression contract, once the fixed per-TDB
        # overhead is amortised the *marginal* on-disk cost of each additional
        # event must be only a small fraction of that event's raw field bytes
        # -- i.e. size grows far sublinearly with events. Measure that marginal
        # cost directly as (size(100k) - size(1k)) / (100000 - 1000): the
        # subtraction cancels the fixed overhead entirely, so a lean
        # implementation with a small (better) codebook/overhead is NOT
        # penalised. (A size self-ratio size(100k)/size(1k) is the wrong metric
        # here: it is dominated by the baseline-overhead magnitude and, as
        # overhead -> 0, drives even an optimal compressor toward the ~100x
        # event-count ratio -- so it rewards wasting space in fixed overhead,
        # which the spec explicitly leaves unsized.) A genuine general-purpose
        # compressor spends only a few bytes per added event -- well under half
        # the raw field bytes -- while a non-compressing / near-linear
        # serialiser spends ~raw per event and fails.
        events1k = _clickstream(1_000, seed=42)
        events100k = _clickstream(100_000, seed=42)
        s1 = _build_via_cli(events1k, "s1k", tmp_path)
        s100 = _build_via_cli(events100k, "s100k", tmp_path)
        marginal_per_event = (s100 - s1) / (100_000 - 1_000)
        raw_per_event = _raw_bytes(events100k) / len(events100k)
        assert marginal_per_event <= 0.45 * raw_per_event, (
            f"per-event growth too steep: size(1k)={s1} size(100k)={s100} "
            f"marginal={marginal_per_event:.2f} B/event vs raw={raw_per_event:.2f} "
            f"B/event (marginal must be <= 0.45x raw -- a naive per-event "
            f"serialiser spends ~raw per event and fails)"
        )


class TestUuidLookupIsSublinear:
    def test_10k_trail_lookup_stays_under_30ms_per_1000_calls(self, tmp_path):
        # Build a 10k-trail TDB (1 event per trail) via CLI, then time
        # 1000 UUID -> trail_id lookups from a compiled C driver.
        # An indexed lookup runs ~0.1-0.5 us / call, so ~1000 calls
        # complete in well under 1 ms; a linear scan over 10k trails
        # costs ~5000 comparisons / call and reaches tens of ms fast.
        r = _random.Random(7)
        uuids = [f"{i:032x}" for i in range(10_000)]
        events = [{"uuid": u, "time": "1", "x": "a"} for u in uuids]
        stdin = "\n".join(_json.dumps(e) for e in events) + "\n"
        rc = subprocess.run(
            ["tdb", "make", "-j", "-o", "bench", "-f", "uuid,time,x"],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(tmp_path),
        )
        assert rc.returncode == 0, rc.stderr

        # 1000 random UUID lookups against the index.
        sample_uuids = r.sample(uuids, 1000)
        driver = r"""
#define _POSIX_C_SOURCE 199309L
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <stdint.h>
#include <traildb.h>

int main(int argc, char **argv) {
    tdb *db = tdb_init();
    if (tdb_open(db, argv[1])) { fprintf(stderr, "open failed\n"); return 1; }
    int n = atoi(argv[2]);
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int hits = 0;
    for (int i = 0; i < n; i++) {
        uint8_t uuid[16];
        tdb_uuid_raw((const uint8_t*)argv[3+i], uuid);
        uint64_t tid;
        if (tdb_get_trail_id(db, uuid, &tid) == 0) hits++;
    }
    clock_gettime(CLOCK_MONOTONIC, &t1);
    double ms = (t1.tv_sec - t0.tv_sec) * 1000.0 +
                (t1.tv_nsec - t0.tv_nsec) / 1e6;
    printf("hits=%d total_ms=%.3f\n", hits, ms);
    return 0;
}
"""
        b = _compile(tmp_path, driver, "lookup_bench")
        argv = [str(b), "bench", str(len(sample_uuids))] + sample_uuids
        r2 = subprocess.run(
            argv, capture_output=True, text=True, timeout=30, cwd=str(tmp_path)
        )
        assert r2.returncode == 0, r2.stderr
        # Parse "hits=1000 total_ms=X".
        line = r2.stdout.strip()
        parts = dict(p.split("=") for p in line.split())
        hits = int(parts["hits"])
        total_ms = float(parts["total_ms"])
        assert hits == len(
            sample_uuids
        ), f"expected {len(sample_uuids)} hits, got {hits}"
        assert total_ms < 30.0, (
            f"UUID lookup too slow: {total_ms:.2f} ms for 1000 lookups "
            f"on a 10k-trail TDB (must be < 30 ms; linear scan would be "
            f"tens to hundreds of ms)"
        )
