/* eslint-env jest */
// End-to-end fixture suite. Each fixture under tests/fixtures/<name>/ is a distinct real-world
// scenario: an args.geojson (the input geometries) plus one expected-output file per operation
// (union.geojson / intersection.geojson / difference.geojson / xor.geojson, or all.geojson meaning
// the same expected output for all four ops). These are the reference project's own regression and
// robustness cases (GitHub-issue reproductions, near-colinear / near-parallel segments, island-in-
// hole nesting, self-crossing multipolygons, degenerate shapes, ...), so they exercise genuinely
// distinct code paths rather than variants of one behavior.
//
// Inputs and expected outputs are data (an oracle captured from the reference), NOT reference
// source — baking them is fine and mirrors the gold pattern's expected.tsv. The agent never sees
// tests/. Each (fixture, operation) pair is one test = one CTRF entry; the set is enumerated
// deterministically (sorted) so the denominator is fixed regardless of filesystem order.

import fs from "fs"
import path from "path"
import polygonClipping from "planar-boolean"
import "./canonical.js"

const FIXTURES_DIR = path.join(__dirname, "fixtures")

function readJSON(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"))
}

// A fixture's args.geojson is a FeatureCollection; each feature's geometry.coordinates is one
// positional argument (a Polygon or MultiPolygon) to the operation.
function loadArgs(fixtureDir) {
  const fc = readJSON(path.join(fixtureDir, "args.geojson"))
  return fc.features.map((f) => f.geometry.coordinates)
}

// An expected-output file is a single Feature whose geometry.coordinates is the expected
// MultiPolygon. "all.geojson" applies to all four operations.
function loadExpected(p) {
  return readJSON(p).geometry.coordinates
}

const OPS = ["union", "intersection", "difference", "xor"]

// Fixtures whose input + expected output exactly duplicate a hand-written curated test. The curated
// test is the documented anchor, so we skip the fixture to avoid grading one behavior twice.
const SKIP_DUPLICATE_OF_CURATED = new Set([
  // identical to normalization.test.js "portions of interior rings outside their exterior ring are
  // dropped" (same 7x7 exterior with three interior rings poking out past x=7).
  "clean-poly-with-interior-ring-overlapping-exterior",
  // identical to topology.test.js "a self-crossing ring is interpreted by the non-zero rule" (same
  // four-pointed self-touching star ring, differing only by Polygon vs single-element MultiPolygon
  // input wrapping).
  "self-intersects-but-doesnt-cross-1",
  // identical to degenerate.test.js "a very small but non-degenerate polygon survives rounding
  // intact" (same sub-micro-degree triangle, differing only by input wrapping).
  "very-small-polygon",
  // identical to degenerate.test.js "splitting a near-vertical segment produces the exact rounded
  // intersection point" (same two triangles, differing only by 2-arg vs single-MultiPolygon packing).
  "split-almost-vertical-segment",
  // identical to degenerate.test.js "a near-vertical intersection is rounded consistently to avoid a
  // spurious sliver" (same two triangles, differing only by Polygon vs MultiPolygon wrapping).
  "vertical-intersection-rounding-error",
])

// Enumerate (fixture, operation, expectedPath) deterministically.
//
// "all.geojson" means the same expected output applies to every operation. When the fixture has a
// SINGLE input argument this is a self-normalization identity — union(A) = intersection(A) = xor(A)
// = difference(A) = clean(A) — so all four ops exercise the SAME code path and one distinct
// behavior would be graded four times. Per the reviewer guideline (decompose by behavior, not
// count), we grade such a fixture ONCE (as `union`). With two or more arguments the operations
// genuinely differ, so we keep all four.
const cases = []
for (const name of fs.readdirSync(FIXTURES_DIR).sort()) {
  const dir = path.join(FIXTURES_DIR, name)
  if (!fs.statSync(dir).isDirectory()) continue
  if (SKIP_DUPLICATE_OF_CURATED.has(name)) continue
  const nArgs = loadArgs(dir).length
  const opFiles = fs
    .readdirSync(dir)
    .filter((fn) => fn.endsWith(".geojson") && fn !== "args.geojson")
    .sort()
  for (const fn of opFiles) {
    const base = fn.slice(0, -".geojson".length)
    const expectedPath = path.join(dir, fn)
    if (base === "all") {
      const ops = nArgs <= 1 ? ["union"] : OPS
      for (const op of ops) cases.push({ name, op, expectedPath })
    } else {
      cases.push({ name, op: base, expectedPath })
    }
  }
}

describe("end-to-end fixtures", () => {
  for (const { name, op, expectedPath } of cases) {
    test(`${name} :: ${op}`, () => {
      const args = loadArgs(path.join(FIXTURES_DIR, name))
      const expected = loadExpected(expectedPath)
      expect(polygonClipping[op](...args)).toEqualMultiPolygon(expected)
    })
  }
})
