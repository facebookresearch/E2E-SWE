"""Grade a WHATWG URL parser against the official web-platform-tests corpus and emit a CTRF report.

The parser under test (/app/urlparse) follows the WPT url-test protocol:
  - the URL `input` is fed as raw bytes on stdin (exact bytes, no added newline);
  - an optional base URL is passed as argv[1] (absent => no base);
  - on a successful parse it prints a JSON object with the URL components and exits 0;
  - on a parse failure it prints nothing useful and exits non-zero.

The graded corpus (shipped by WPT / vendored by ada):
  - urltestdata.json: the main URL parsing corpus. Each test object is either a success case
    (carrying the expected component fields) or a failure case (`"failure": true`). For success we
    compare the WHATWG component fields present on every success case: href, protocol, username,
    password, host, hostname, port, pathname, search, hash (the derived `origin` and the
    `searchParams` sub-API are not graded). For failure we require a non-zero exit.

Each case is one CTRF entry and runs the parser as a fresh subprocess, so a crash/hang fails only
that case.

Usage: url_ctrf.py <urltestdata.json> <parser-cmd> <out_ctrf.json> [timeout_sec]
"""
import json
import shlex
import subprocess
import sys

FIELDS = ["href", "protocol", "username", "password", "host", "hostname", "port",
          "pathname", "search", "hash"]


def slug(s):
    return "".join(ch if ch.isalnum() else "-" for ch in s)[:48].strip("-") or "empty"


def build_cases(corpus_path):
    """Return a flat list of cases: (name, input, base_or_None, failure, expected_dict, fields)."""
    cases = []
    data = json.load(open(corpus_path))
    for i, e in enumerate(e for e in data if isinstance(e, dict) and "input" in e):
        name = "case-%04d-%s%s" % (i, slug(e["input"]), "-FAIL" if e.get("failure") else "")
        cases.append((name, e["input"], e.get("base"), bool(e.get("failure")), e, FIELDS))
    return cases


def main():
    corpus, parser, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    timeout = float(sys.argv[4]) if len(sys.argv) > 4 else 15.0
    cmd = shlex.split(parser)

    entries, passed, failed = [], 0, 0
    for name, inp, base, failure, expected, fields in build_cases(corpus):
        args = list(cmd) + ([base] if base is not None else [])
        ok, msg = False, ""
        try:
            p = subprocess.run(args, input=inp.encode("utf-8"),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
            if failure:
                ok = p.returncode != 0
                if not ok:
                    msg = "invalid URL was accepted (exit 0)"
            elif p.returncode != 0:
                msg = "valid URL rejected (exit %d)" % p.returncode
            else:
                try:
                    got = json.loads(p.stdout.decode("utf-8", "replace"))
                except json.JSONDecodeError as ex:
                    got = None
                    msg = "parser output is not valid JSON: %s" % ex
                if got is not None:
                    diffs = [f for f in fields if got.get(f, "<missing>") != expected.get(f, "")]
                    ok = not diffs
                    if diffs:
                        f = diffs[0]
                        msg = "field %r: expected %r got %r%s" % (
                            f, expected.get(f, ""), got.get(f, "<missing>"),
                            "" if len(diffs) == 1 else " (+%d more)" % (len(diffs) - 1))
        except subprocess.TimeoutExpired:
            msg = "timed out"
        except Exception as ex:  # noqa: BLE001
            msg = "harness error: %s" % ex
        entries.append({"name": name, "status": "passed" if ok else "failed",
                        "duration": 0.0, "message": msg})
        passed += ok
        failed += not ok

    report = {"results": {"tool": {"name": "pytest"},
                          "summary": {"tests": len(entries), "passed": passed, "failed": failed,
                                      "skipped": 0, "pending": 0, "other": 0, "start": 0, "stop": 0},
                          "tests": entries}}
    json.dump(report, open(out_path, "w"))
    print("%d/%d passed" % (passed, len(entries)))


if __name__ == "__main__":
    main()
