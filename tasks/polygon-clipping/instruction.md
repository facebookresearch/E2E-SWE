# planar-boolean — boolean operations on polygons

Implement a JavaScript library that applies the four boolean set operations — **union**,
**intersection**, **difference**, and **xor** — to polygons and multipolygons in the plane, using a
sweep-line clipping algorithm. Given one or more (multi)polygons, each operation returns the exact
resulting region as a well-formed MultiPolygon.

## Build and packaging

The library is written as ECMAScript-module `.js` source and consumed as CommonJS. Provide an
executable **`setup.sh`** at the repository root that compiles every source file into a **`build/`**
directory whose entry point is **`build/index.js`**, e.g.

```
tsc src/index.js --allowJs --outDir build --module commonjs --target es2019 --esModuleInterop
```

The library is imported as the package **`planar-boolean`** (resolved to `build/index.js`). Its
**default export** is an object exposing the four operations:

```js
import planarBoolean from "planar-boolean"
// planarBoolean.union, .intersection, .difference, .xor
```

Two third-party runtime dependencies are pre-installed and importable by bare specifier (do not
reimplement or vendor them): **`splaytree`** (a balanced binary search tree; used for the event
queue and sweep-line status) and **`robust-predicates`** (used for its `orient2d` adaptive-precision
orientation test). Everything else is implemented from scratch.

## Geometry representation

Coordinates follow the GeoJSON convention as nested arrays of `[x, y]` number pairs:

- **Ring** — an array of positions: `[[x, y], …]`.
- **Polygon** — an array of rings, `[exteriorRing, ...interiorRings]`. Ring 0 is the outer boundary;
  any further rings are holes.
- **MultiPolygon** — an array of Polygons.

## The four operations

```js
planarBoolean.union       (geom, ...moreGeoms)   // regions covered by at least one input
planarBoolean.intersection(geom, ...moreGeoms)   // regions covered by every input
planarBoolean.xor         (geom, ...moreGeoms)   // regions covered by an odd number of inputs
planarBoolean.difference  (subjectGeom, ...clipGeoms) // subjectGeom minus the union of clipGeoms
```

- Each positional argument may be **either a Polygon or a MultiPolygon**; the two are accepted
  interchangeably (a Polygon is treated as a MultiPolygon of one polygon).
- All four are **variadic**. `union`/`intersection`/`xor` are symmetric in their arguments.
  `difference` is **not**: only the first argument is the subject; every later argument is subtracted
  from it. Calling an operation with a single argument returns that geometry normalized/cleaned
  (see Output) with all internal overlaps resolved.
- The return value is **always a MultiPolygon** (an array of Polygons), even when it contains zero
  or one polygon.

## Input handling

Inputs are interpreted permissively and normalized before clipping:

- Rings **need not be self-closing** (the first point may but need not be repeated as the last).
- **Repeated consecutive points are ignored.**
- **Winding order of input rings does not matter** (neither exterior nor interior).
- A ring may be **self-touching and/or self-crossing**; such a ring is interpreted using the
  **non-zero winding rule** (not the even–odd rule).
- Within a single MultiPolygon, member polygons **may touch or overlap**; those overlaps are
  resolved in the result.
- The portion of any **interior ring that extends outside its exterior ring is dropped**; an
  interior ring lying entirely outside its exterior ring disappears entirely. Concretely, an interior
  ring is subtracted from its exterior: where a hole **crosses** the exterior boundary, the in-bounds
  part of the hole is cut *into* the outer outline (that stretch stops being a hole and becomes part
  of the exterior edge, so the polygon may end up with no hole there at all); where a hole only
  **touches** the exterior boundary at isolated points without crossing it, the hole is retained as a
  hole (this describes how *input* geometry is normalized before clipping; how a *result* is
  decomposed where it pinches at isolated points is governed by the Output guarantees below). For
  example, a `[[0,0],[7,0],[7,7],[0,7]]` square with an interior ring
  `[[6,1],[6,2],[8,2],[8,1]]` that pokes out past `x=7` yields the single exterior outline
  `[[0,0],[7,0],[7,1],[6,1],[6,2],[7,2],[7,7],[0,7],[0,0]]` and **no** interior ring — the notch at
  `x∈[6,7]` is carved into the outer boundary and the `x>7` part is discarded.
- Degenerate rings with **no area** — fewer than 3 distinct points (a point or a line), empty
  arrays, or rings all of whose points are collinear — contribute nothing and are discarded.

Two positions are considered the same point when they are equal after the algorithm's internal
coordinate rounding, which snaps values that differ only within floating-point epsilon; this makes
results of near-degenerate inputs (nearly-vertical or nearly-parallel edges, intersection points a
rounding-error apart) stable.

## Output guarantees

For a non-empty result the output is a MultiPolygon of one or more non-overlapping,
non-edge-sharing Polygons, following GeoJSON with these guarantees:

- **Exterior rings are wound counter-clockwise; interior rings (holes) clockwise.**
- Rings are **self-closing** (first position repeated as the last).
- Rings contain **no repeated points** and **no superfluous points** (no intermediate vertex lying
  on the straight line between its neighbors).
- Rings are neither self-touching nor self-crossing, and do not overlap or share an edge with one
  another (they **may touch** at points but **may not cross**).
- **Decomposition at pinch points.** Within one output Polygon an interior ring (hole) may meet its
  exterior ring at **at most a single point**, never at two or more. Where filled area would
  otherwise be joined only at isolated points — a would-be hole meeting the exterior boundary at two
  or more points — the pieces are emitted as **separate Polygons** that touch one another only at
  those points, rather than as one Polygon whose hole meets its exterior at more than one point.
- Interior rings do not extend outside their exterior ring.
- A polygon's rings are ordered exterior-first, and every point is emitted as a two-element
  `[x, y]` array.

When the result is the empty set, the operation returns a MultiPolygon with no polygons: **`[]`**.

The exact vertex list, ring count, ring nesting (which holes belong to which polygon), and the
number of separate output polygons are all part of the contract — a single subject can be split into
several disjoint output polygons, and several overlapping clips can fuse into shared holes.
