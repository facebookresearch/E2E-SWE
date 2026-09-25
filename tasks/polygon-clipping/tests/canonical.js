/* eslint-env jest */
// Shared geometric equality for MultiPolygon results.
//
// The public contract of this library is GeoJSON geometry: a result is correct when it describes
// the same planar region with the same ring winding — NOT when its coordinate arrays are byte-identical
// to one particular implementation's output. GeoJSON does not define which vertex a ring starts at,
// nor the order of holes within a polygon or of polygons within a MultiPolygon. Asserting those
// incidental choices would fail a geometrically-correct reimplementation for reasons the spec never
// states, so we compare canonically: each ring is rotated to a fixed starting vertex (orientation
// preserved, so CCW/CW is still enforced), holes are order-normalized within their polygon, and
// polygons are order-normalized within the MultiPolygon. Everything structural — vertex count,
// ring/hole nesting, winding, and the number of output polygons — is still compared exactly; only the
// per-coordinate numeric values are compared with a small absolute tolerance (see COORD_TOL).

// Absolute per-coordinate tolerance for the final numeric compare. The segment-intersection POINT
// formula is not pinned by the spec (only orient2d is mandated, and for orientation only), so for
// ill-conditioned crossings (near-parallel / near-colinear segments) the last one or two significant
// digits are formula- and operation-order-dependent: two spec-faithful implementations diverge by
// ~1e-10..1e-8 there. Comparing rounded coordinates by exact string equality is boundary-sensitive —
// two faithful values a rounding-error apart can straddle a grid line and compare unequal purely as a
// rounding artifact — so we instead require |a-b| <= COORD_TOL. The value sits above the largest
// spec-unpinned formula divergence (~1e-8, one 8-dp grid cell) and below the suite's smallest genuine
// coordinate error (~2e-8, two grid cells), so real errors still fail while the artifact passes.
const COORD_TOL = 1.5e-8

// Snap a coordinate to 8 decimal places. Used to normalize structure (dedup, collinear removal, and
// the ordering keys that align rings/holes/polygons for comparison) so that two faithful outputs a
// rounding-error apart canonicalize to the same shape and vertex order. The actual pass/fail compare
// is by COORD_TOL below, not by these keys. `+0` normalizes -0 to 0.
function round(n) {
  return Number(n.toFixed(8)) + 0
}

function canonRing(ring) {
  let r = ring.map((pt) => [round(pt[0]), round(pt[1])])
  // Drop an explicit closing duplicate so the rotation search treats the ring as a cycle.
  if (r.length > 1 && r[0][0] === r[r.length - 1][0] && r[0][1] === r[r.length - 1][1]) {
    r = r.slice(0, -1)
  }
  // Collapse consecutive duplicate vertices left by the 8-dp rounding. The output contract
  // guarantees rings carry "no repeated points", so a vertex emitted twice a sub-nanometre apart
  // (e.g. a segment-split apex two points ~1e-12 apart that both round to the same coordinate) is
  // one geometric vertex: a spec-faithful engine that emits it once must compare equal to a
  // reference that happened to emit it twice. Collapse cyclically (adjacent pairs, then wrap-around).
  const dedup = []
  for (const pt of r) {
    const last = dedup[dedup.length - 1]
    if (!last || last[0] !== pt[0] || last[1] !== pt[1]) dedup.push(pt)
  }
  while (
    dedup.length > 1 &&
    dedup[0][0] === dedup[dedup.length - 1][0] &&
    dedup[0][1] === dedup[dedup.length - 1][1]
  ) {
    dedup.pop()
  }
  r = dedup
  if (r.length === 0) return { key: "[]", pts: [] }
  // Drop superfluous collinear vertices. The output contract guarantees rings carry "no superfluous
  // points (no intermediate vertex lying on the straight line between its neighbors)", so an
  // intermediate vertex whose perpendicular offset from the straight line through its neighbors is
  // below the comparison grid describes no distinct geometry: a spec-faithful engine that omits
  // it must compare equal to a reference (e.g. one that split a straight edge at intersection points
  // and left the split vertices in). Remove them cyclically from both sides. Guard against collapsing
  // a genuine thin-but-non-degenerate triangle (whose real vertices are near-collinear): never drop
  // below 3 vertices.
  const perpBelowGrid = (a, b, c) => {
    const dx = c[0] - a[0]
    const dy = c[1] - a[1]
    const len = Math.hypot(dx, dy)
    const dist =
      len === 0
        ? Math.hypot(b[0] - a[0], b[1] - a[1])
        : Math.abs(dx * (b[1] - a[1]) - dy * (b[0] - a[0])) / len
    return dist < 1e-8
  }
  let removed = true
  while (removed && r.length > 3) {
    removed = false
    for (let i = 0; i < r.length && r.length > 3; i++) {
      const a = r[(i - 1 + r.length) % r.length]
      const c = r[(i + 1) % r.length]
      if (perpBelowGrid(a, r[i], c)) {
        r.splice(i, 1)
        removed = true
        i--
      }
    }
  }
  // Rotate to the lexicographically smallest vertex WITHOUT reversing — winding is preserved.
  let best = 0
  for (let i = 1; i < r.length; i++) {
    if (r[i][0] < r[best][0] || (r[i][0] === r[best][0] && r[i][1] < r[best][1])) best = i
  }
  const rotated = r.slice(best).concat(r.slice(0, best))
  // `key` is the rounded-coordinate string used only to order holes within a polygon and polygons
  // within a MultiPolygon; `pts` is compared numerically with COORD_TOL.
  return { key: JSON.stringify(rotated), pts: rotated }
}

function canonPoly(poly) {
  const exterior = canonRing(poly[0])
  const holes = poly.slice(1).map(canonRing)
  holes.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
  return { key: JSON.stringify([exterior.key, holes.map((h) => h.key)]), exterior, holes }
}

function canonMultiPolygon(mp) {
  if (!Array.isArray(mp)) return { key: JSON.stringify(mp), polys: null }
  const polys = mp.map(canonPoly)
  polys.sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0))
  return { key: JSON.stringify(polys.map((p) => p.key)), polys }
}

function ringsEqual(a, b) {
  if (a.pts.length !== b.pts.length) return false
  for (let i = 0; i < a.pts.length; i++) {
    if (Math.abs(a.pts[i][0] - b.pts[i][0]) > COORD_TOL) return false
    if (Math.abs(a.pts[i][1] - b.pts[i][1]) > COORD_TOL) return false
  }
  return true
}

function polysEqual(a, b) {
  if (a.holes.length !== b.holes.length) return false
  if (!ringsEqual(a.exterior, b.exterior)) return false
  for (let i = 0; i < a.holes.length; i++) {
    if (!ringsEqual(a.holes[i], b.holes[i])) return false
  }
  return true
}

function multiPolygonsEqual(received, expected) {
  const r = canonMultiPolygon(received)
  const e = canonMultiPolygon(expected)
  if (r.polys === null || e.polys === null) return r.key === e.key
  if (r.polys.length !== e.polys.length) return false
  for (let i = 0; i < r.polys.length; i++) {
    if (!polysEqual(r.polys[i], e.polys[i])) return false
  }
  return true
}

// One-sided output-contract check, applied to the RESULT only (never to the oracle).
//
// The canonicalization above deliberately tolerates near-duplicate and near-collinear vertices on
// both sides, because the captured oracle itself retains vertices sitting up to ~3e-12 off the
// straight line through their neighbours: a faithful engine that drops them must still compare
// equal. That tolerance must not become a licence to skip output normalization altogether, since
// instruction.md states it as a guarantee — "Rings contain no repeated points and no superfluous
// points (no intermediate vertex lying on the straight line between its neighbors)". So a result
// ring is rejected outright when it repeats a position exactly, or carries an intermediate vertex
// lying EXACTLY on the line through its neighbours. Exactness is required BOTH from an
// adaptive-precision orientation test and from a plain double cross product, so a near-degenerate
// triple that only one of the two calls collinear can never fail a faithful engine, whichever
// predicate it removes superfluous points with.

const F64 = new DataView(new ArrayBuffer(8))

// Decompose a finite double into the exact dyadic rational m * 2^e (m a BigInt, e an integer).
function dyadic(x) {
  F64.setFloat64(0, x)
  const hi = F64.getUint32(0)
  const lo = F64.getUint32(4)
  let exp = (hi >>> 20) & 0x7ff
  let m = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo)
  if (exp === 0) exp = 1
  else m |= 1n << 52n
  return { m: hi >>> 31 ? -m : m, e: exp - 1075 }
}

// Exact zero-test for the orientation determinant of (a, b, c) — the quantity robust-predicates'
// adaptive orient2d evaluates. Scaling the six coordinates by a common power of two makes them
// exact integers, so BigInt arithmetic settles the sign with no cancellation error.
function exactlyCollinear(a, b, c) {
  const vals = [a[0], a[1], b[0], b[1], c[0], c[1]]
  if (!vals.every(Number.isFinite)) return false
  const parts = vals.map(dyadic)
  const e0 = Math.min(...parts.map((p) => p.e))
  const [ax, ay, bx, by, cx, cy] = parts.map((p) => p.m << BigInt(p.e - e0))
  return (ax - cx) * (by - cy) - (ay - cy) * (bx - cx) === 0n
}

// Describe the first violated ring guarantee in a result MultiPolygon, or return null. Anything
// that is not shaped like a MultiPolygon is left to the geometric compare to reject.
function findContractViolation(mp) {
  if (!Array.isArray(mp)) return null
  for (const poly of mp) {
    if (!Array.isArray(poly)) return null
    for (const ring of poly) {
      if (!Array.isArray(ring)) return null
      if (!ring.every((pt) => Array.isArray(pt) && pt.length >= 2 && typeof pt[0] === "number" && typeof pt[1] === "number")) {
        return null
      }
      // Un-close, dropping every trailing repetition of the first position: a self-closing ring
      // states its first point again at the end by contract, which is not a repeated point.
      const r = ring.slice()
      while (r.length > 1 && r[0][0] === r[r.length - 1][0] && r[0][1] === r[r.length - 1][1]) r.pop()
      for (let i = 0; i + 1 < r.length; i++) {
        if (r[i][0] === r[i + 1][0] && r[i][1] === r[i + 1][1]) {
          return `ring repeats the position ${JSON.stringify(r[i])} (output rings carry no repeated points)`
        }
      }
      // Rings of three distinct vertices are left alone: every vertex of a triangle is "between"
      // the other two, and a genuinely thin-but-non-degenerate triangle must survive.
      if (r.length < 4) continue
      for (let i = 0; i < r.length; i++) {
        const p = r[(i - 1 + r.length) % r.length]
        const v = r[i]
        const q = r[(i + 1) % r.length]
        const naiveCross = (p[0] - q[0]) * (v[1] - q[1]) - (p[1] - q[1]) * (v[0] - q[0])
        if (naiveCross === 0 && exactlyCollinear(p, v, q)) {
          return (
            `ring vertex ${JSON.stringify(v)} lies exactly on the straight line between ` +
            `${JSON.stringify(p)} and ${JSON.stringify(q)} (output rings carry no superfluous points)`
          )
        }
      }
    }
  }
  return null
}

expect.extend({
  toEqualMultiPolygon(received, expected) {
    const violation = findContractViolation(received)
    if (violation) {
      return {
        pass: false,
        message: () =>
          `MultiPolygon violates a stated output ring guarantee: ${violation}\n` +
          `  received: ${this.utils.printReceived(received)}`,
      }
    }
    const pass = multiPolygonsEqual(received, expected)
    return {
      pass,
      message: () =>
        `MultiPolygon geometric equality (canonicalized: ring start vertex, hole order, polygon order;\n` +
        `coordinates compared with absolute tolerance ${COORD_TOL}):\n` +
        `  expected: ${this.utils.printExpected(expected)}\n` +
        `  received: ${this.utils.printReceived(received)}\n` +
        `  canonical expected: ${canonMultiPolygon(expected).key}\n` +
        `  canonical received: ${canonMultiPolygon(received).key}`,
    }
  },
})

module.exports = {
  canonRing,
  canonPoly,
  canonMultiPolygon,
  multiPolygonsEqual,
  findContractViolation,
  exactlyCollinear,
}
