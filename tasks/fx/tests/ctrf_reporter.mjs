import fs from "node:fs";
export default async function* ctrf(source) {
  const tests = []; let passed = 0, failed = 0;
  const start = Date.now();
  fs.mkdirSync("/logs/verifier", { recursive: true });
  // Flush after every completed test rather than once after the stream drains: a test that hangs
  // or hard-crashes the runner would otherwise discard every already-finished result, leaving no
  // CTRF at all — a no-grade for the whole task instead of a scored partial. Write-then-rename so
  // a kill mid-write can never leave a truncated, unparseable ctrf.json behind.
  const flush = () => {
    const out = { results: { tool: { name: "node:test" },
      summary: { tests: passed + failed, passed, failed, skipped: 0, pending: 0, other: 0, start, stop: Date.now() },
      tests } };
    fs.writeFileSync("/logs/verifier/ctrf.json.tmp", JSON.stringify(out, null, 2));
    fs.renameSync("/logs/verifier/ctrf.json.tmp", "/logs/verifier/ctrf.json");
  };
  for await (const e of source) {
    if (e.type === "test:pass") { tests.push({ name: e.data.name, status: "passed", duration: e.data.details?.duration_ms ?? 0 }); passed++; flush(); }
    else if (e.type === "test:fail") { tests.push({ name: e.data.name, status: "failed", duration: e.data.details?.duration_ms ?? 0 }); failed++; flush(); }
  }
  flush();
  yield `node:test -> ${passed}/${passed + failed} passed\n`;
}
