"""Convert Deno's JUnit XML into a CTRF report for the WRG grader.

`deno test --junit-path` emits <testsuites><testsuite><testcase>. A case passes iff it appears with
no <failure>/<error> child. The canonical case list is the committed oracle /tests/expected.txt (one
Deno.test name per line), so the denominator stays fixed: a case with no <testcase> (Deno crashed, or
a name drifted) is recorded failed rather than dropped. Stdlib only -> the image builds fully offline.

Usage: make_ctrf.py <deno_report.xml> <out_ctrf.json> <expected.txt>
"""
import json, re, sys, xml.etree.ElementTree as ET

# XML 1.0 disallows most control chars; Deno's JUnit <failure message="..."> can still carry raw ANSI
# escape (ESC = 0x1B) bytes and other control chars, which make the report non-well-formed. Strip the
# invalid control chars (keep tab/newline/CR) so ET.parse succeeds; a regex fallback handles any
# residual malformation so a run with FAILURES is never miscounted as all-failed.
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _statuses_via_et(text):
    status = {}
    root = ET.fromstring(text)
    for tc in root.iter("testcase"):
        name = tc.get("name", "")
        if any(c.tag == "skipped" for c in tc):
            status[name] = "skipped"
        elif any(c.tag in ("failure", "error") for c in tc):
            status[name] = "failed"
        else:
            status[name] = "passed"
    return status


def _statuses_via_regex(text):
    # Tolerant fallback: scan each <testcase ...> (self-closed or with a body) and check for a
    # <failure>/<error>/<skipped> child before the case closes.
    status = {}
    for m in re.finditer(r'<testcase\b([^>]*?)(/>|>(.*?)</testcase>)', text, re.DOTALL):
        attrs, body = m.group(1), m.group(3) or ""
        nm = re.search(r'name="((?:[^"\\]|\\.)*)"', attrs)
        if not nm:
            continue
        name = nm.group(1)
        if "<skipped" in body:
            status[name] = "skipped"
        elif "<failure" in body or "<error" in body:
            status[name] = "failed"
        else:
            status[name] = "passed"
    return status


def main():
    xml_path, out_path, expected_path = sys.argv[1], sys.argv[2], sys.argv[3]

    canonical = []
    try:
        with open(expected_path) as fh:
            canonical = [ln.strip() for ln in fh if ln.strip()]
    except FileNotFoundError:
        pass

    status_by_name = {}
    try:
        with open(xml_path, encoding="utf-8", errors="replace") as fh:
            clean = _CTRL.sub("", fh.read())
        try:
            status_by_name = _statuses_via_et(clean)
        except ET.ParseError:
            status_by_name = _statuses_via_regex(clean)
    except FileNotFoundError:
        pass

    if not canonical:  # oracle missing -> fall back to whatever Deno emitted (should not happen)
        canonical = list(status_by_name.keys())

    tests, passed, failed, skipped = [], 0, 0, 0
    for name in canonical:
        st = status_by_name.get(name)
        if st == "passed":
            tests.append({"name": name, "status": "passed", "duration": 0.0, "message": ""})
            passed += 1
        elif st == "skipped":
            tests.append({"name": name, "status": "skipped", "duration": 0.0, "message": "ignored"})
            skipped += 1
        else:
            msg = "no result produced (deno test failed to run this case)" if st is None else "assertion failed"
            tests.append({"name": name, "status": "failed", "duration": 0.0, "message": msg})
            failed += 1

    report = {"results": {
        "tool": {"name": "deno test"},
        "summary": {"tests": len(tests), "passed": passed, "failed": failed,
                    "skipped": skipped, "pending": 0, "other": 0, "start": 0, "stop": 0},
        "tests": tests,
    }}
    with open(out_path, "w") as fh:
        json.dump(report, fh)
    print(f"ctrf: {passed} passed, {failed} failed, {skipped} skipped, {len(tests)} total")


if __name__ == "__main__":
    main()
