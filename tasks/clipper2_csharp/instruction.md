# Clipper2 (C#)

Build **Clipper2**, a C# library for 2D **polygon clipping** (boolean set operations), **polygon
offsetting** (inflate/shrink), **rectangular clipping**, and supporting computational-geometry
utilities. It operates on integer-coordinate polygons and is the engine behind boolean ops like
union/intersection/difference on arbitrary (including self-intersecting and holed) polygons.

Organize the implementation however you like (any number of `.cs` files), as long as the namespace,
types, public API, and observable behavior below are reproduced exactly.

## Example use case

Picture the geometry kernel behind a CAD / GIS / vector-graphics tool. Downstream code constantly needs
to **combine and reshape polygons** — "merge these building footprints", "cut this parcel out of that
one", "grow this keep-out zone by 5 units", "clip everything to the viewport". `Clipper2` is that
kernel: a caller builds polygons as lists of integer points and calls **one method per operation**, and
the library returns the resulting polygon(s). It is purely computational — no I/O, no global state.

Here is how a user exercises the main capabilities (everything is in `namespace Clipper2Lib`; the free
operations are `static` methods on the `Clipper` class). The comments describe the *outcome* of each call:

```csharp
using Clipper2Lib;

// A Path64 is one ring (a list of Point64); Paths64 is a set of rings. Build them from flat x,y lists.
Paths64 a = new Paths64 { Clipper.MakePath(new long[] { 0,0, 100,0, 100,100, 0,100 }) };     // 100x100 square
Paths64 b = new Paths64 { Clipper.MakePath(new long[] { 50,50, 150,50, 150,150, 50,150 }) }; // overlapping square

// --- Boolean set operations (a FillRule decides how overlaps/holes count as "inside") ---
Paths64 merged  = Clipper.Union(a, b, FillRule.NonZero);       // the combined outline of a OR b
Paths64 overlap = Clipper.Intersect(a, b, FillRule.NonZero);   // only the region in BOTH a and b
Paths64 aOnly   = Clipper.Difference(a, b, FillRule.NonZero);  // a with the part shared with b removed
Paths64 either  = Clipper.Xor(a, b, FillRule.NonZero);         // the parts in exactly one of a or b

// Consume a result: iterate its rings, then each ring's points.
foreach (Path64 ring in merged)
    foreach (Point64 p in ring) { /* use p.X, p.Y */ }

// --- Offsetting: grow or shrink a polygon by a signed distance ---
Paths64 grown  = Clipper.InflatePaths(a, 10, JoinType.Miter, EndType.Polygon);   // 'a' enlarged 10 every side
Paths64 shrunk = Clipper.InflatePaths(a, -10, JoinType.Miter, EndType.Polygon);  // 'a' shrunk 10 every side

// --- Clip to an axis-aligned rectangle ---
Paths64 windowed = Clipper.RectClip(new Rect64(20,20,80,80), a);   // the part of 'a' inside the 20..80 box

// --- Hole structure: get nested results as a tree rather than a flat ring list ---
Clipper64 clipper = new Clipper64();
clipper.AddSubject(a);
clipper.AddClip(b);
PolyTree64 tree = new PolyTree64();
clipper.Execute(ClipType.Union, FillRule.NonZero, tree);
// walk the tree: tree[i].IsHole, tree[i].Polygon (a Path64), tree[i].Count / tree[i].Child(k)

// --- Small geometry helpers ---
double area = Clipper.Area(a[0]);                                          // signed area (sign follows orientation)
bool   ccw  = Clipper.IsPositive(a[0]);                                    // orientation test
PointInPolygonResult where = Clipper.PointInPolygon(new Point64(50,50), a[0]);  // IsInside / IsOutside / IsOn
```

A typical caller constructs input `Paths64`, calls one of these methods, and consumes the returned
`Paths64` (or `PolyTree64`). The remainder of this document specifies the exact contract each method
must satisfy (output shape, fill-rule semantics, orientation conventions, etc.).

## Build / layout

- Target **.NET / C# 8** (the grader compiles your `.cs` sources with the .NET 8 SDK). No third-party
  NuGet dependencies — only the base class library.
- All public declarations live in **`namespace Clipper2Lib`**. (The grader collects every `.cs` file
  that declares `namespace Clipper2Lib` and compiles them together with the hidden tests, so put your
  whole implementation in that namespace.)
- The free operations (boolean ops, offsetting, rect-clip, utilities, `MakePath`) are **`public static`
  methods on a `public static class Clipper`** — e.g. `Clipper.Union(...)`, `Clipper.MakePath(...)`.

## Core types (namespace `Clipper2Lib`)

- `Point64` — a struct with public fields **`public long X, Y;`** (uppercase) and a constructor
  `Point64(long x, long y)`. Equality compares `X` and `Y`.
- `PointD` — the `double` analogue, with public fields **`public double x, y;`** (lowercase) and a
  constructor `PointD(double x, double y)`.
- `Path64` — **`public class Path64 : List<Point64>`** — an (open or closed) sequence of points. A
  **closed polygon ring is stored WITHOUT a duplicated closing vertex** (a square is 4 points, not 5).
- `Paths64` — **`public class Paths64 : List<Path64>`** — a list of rings/paths.
- `PathD : List<PointD>` and `PathsD : List<PathD>` — the `double` equivalents.
- (Because these derive from `List<>`, they support `Add`, `AddRange`, indexing, `Count`, and
  `foreach`; collection initializers like `new Paths64 { p1, p2 }` work.)
- `Rect64` — axis-aligned rectangle with public fields `long left, top, right, bottom;` and a
  constructor `Rect64(long left, long top, long right, long bottom)`.
- Enums:
  - `ClipType { NoClip, Intersection, Union, Difference, Xor }`
  - `FillRule { EvenOdd, NonZero, Positive, Negative }`
  - `JoinType { Miter, Square, Bevel, Round }`
  - `EndType { Polygon, Joined, Butt, Square, Round }`
  - `PointInPolygonResult { IsOn, IsInside, IsOutside }`

### Path construction
- `Clipper.MakePath(long[] xy) -> Path64` and `Clipper.MakePath(double[] xy) -> PathD`: build a path
  from a flat array of alternating x,y coordinates, e.g.
  `Clipper.MakePath(new long[]{0,0, 100,0, 100,100, 0,100})` is the unit square (scaled ×100).

## Output contract for polygon results

Every clipping / offsetting / rect-clip operation returns `Paths64` (or `PathsD`) describing the
resulting region as a set of **closed rings** with these guarantees:

- **No duplicated closing vertex** (see above).
- **Orientation encodes nesting:** an outer boundary has **positive area** (`Clipper.Area(ring) > 0`);
  a hole has **negative area** (`Clipper.Area(ring) < 0`).
- The geometric result is what matters: the **cyclic starting vertex** of each ring and the **order of
  the rings** within the returned list are not significant (results are compared up to ring rotation
  and path reordering). Coordinates, ring membership, vertex count, and orientation **are** significant.
- Integer results (`Paths64`) are exact. `PathsD` results are rounded to the requested decimal
  `precision` (default 2).

## Boolean operations (static methods on `Clipper`)

Each takes subject and clip paths plus a `FillRule`:

- `Clipper.Union(Paths64 subjects, Paths64 clips, FillRule) -> Paths64`
- `Clipper.Intersect(Paths64 subjects, Paths64 clips, FillRule) -> Paths64`
- `Clipper.Difference(Paths64 subjects, Paths64 clips, FillRule) -> Paths64`
- `Clipper.Xor(Paths64 subjects, Paths64 clips, FillRule) -> Paths64`
- `Clipper.BooleanOp(ClipType, Paths64 subjects, Paths64 clips, FillRule) -> Paths64` — the general form.
- `Clipper.Union(Paths64 subjects, FillRule) -> Paths64` — single-argument self-union (empty clips).
- `PathsD` overloads taking a trailing `int precision = 2`.

**Fill-rule semantics** (which sub-regions are "inside"), applied to the accumulated edge windings:

- `EvenOdd` — filled iff enclosed an odd number of times (orientation-independent).
- `NonZero` — filled iff the signed winding number is non-zero.
- `Positive` — filled iff the winding number is > 0.
- `Negative` — filled iff the winding number is < 0.

Consequences you must reproduce: two concentric same-orientation rings union to a **solid** shape under
`NonZero` but to a **ring with a hole** under `EvenOdd`; a ring with an oppositely-wound inner ring is a
**donut** under `NonZero`/`Positive` and **empty** under `Negative`; a self-intersecting "bowtie" path
splits into two triangles. Holes in the result are emitted with the opposite orientation to their outer
boundary (per the orientation contract above).

## Offsetting — `Clipper.InflatePaths`

`Clipper.InflatePaths(Paths64 paths, double delta, JoinType, EndType, double miterLimit = 2.0, double
arcTolerance = 0.0) -> Paths64` (and a `PathsD` overload with a trailing `int precision = 2`).

- `delta > 0` inflates (grows) the region; `delta < 0` shrinks it. Each edge is moved perpendicular by
  `delta`.
- `EndType.Polygon` treats each input path as a closed polygon and offsets its outside.
- **Convex corner joins** for closed polygons:
  - `JoinType.Miter` — the two offset edges are extended to their intersection (the mitre point),
    subject to `miterLimit` (default 2.0). For a right-angle corner this is the single extended corner
    point (inflating an axis-aligned square by `d` yields a square grown by `d` on every side).
  - `JoinType.Bevel` — the corner is cut by a straight chord joining the endpoints of the two
    perpendicular-offset edges (so each square corner becomes two points).
- **Open paths** (offsetting a poly-LINE, producing a closed outline around it) use `EndType`:
  - `Butt` — flat end exactly at the path's endpoint (no extension).
  - `Square` — flat end extended by `delta` beyond the endpoint.
  - `Joined` — the two offset sides are joined around the end (coincides with `Square` for a straight
    segment).

(`JoinType.Square`/`Round` and `EndType.Round` also exist for rounded/squared approximations but their
exact tessellation is implementation-defined and not required here.)

## Rectangular clipping (static methods on `Clipper`)

- `Clipper.RectClip(Rect64 rect, Paths64 paths) -> Paths64` — clip closed polygons to `rect`. The
  result follows the polygon output contract above: each connected component of the clipped region is
  returned as its own closed ring.
- `Clipper.RectClipLines(Rect64 rect, Paths64 lines) -> Paths64` — clip **open** polylines to `rect`
  (the result is open paths; point order is preserved).

## Simplification (static methods on `Clipper`)

- `Clipper.SimplifyPaths(Paths64 paths, double epsilon, bool isClosedPath = true) -> Paths64` — remove
  vertices that lie within `epsilon` perpendicular distance of the line between their neighbours (vertex
  order otherwise preserved).
- `Clipper.RamerDouglasPeucker(Path64 path, double epsilon) -> Path64` — the standard
  Ramer–Douglas–Peucker line simplification.
- `Clipper.TrimCollinear(Path64 path, bool isOpen = false) -> Path64` — remove exactly-collinear vertices.

## Geometry utilities (static methods on `Clipper`)

- `Clipper.Area(Path64) -> double` — the signed area (shoelace); positive for counter-clockwise (in the
  test coordinate convention) rings, negative for clockwise. `Clipper.Area(Paths64)` sums them.
- `Clipper.IsPositive(Path64) -> bool` — true iff `Area >= 0`.
- `Clipper.PointInPolygon(Point64 pt, Path64 polygon) -> PointInPolygonResult` — `IsInside`,
  `IsOutside`, or `IsOn` (point exactly on an edge/vertex).
- `Clipper.Ellipse(Point64 center, double radiusX, double radiusY, int steps) -> Path64` — a polygon
  approximating an ellipse with `steps` vertices; vertex `k` is
  `(round(cx + radiusX·cos(2πk/steps)), round(cy + radiusY·sin(2πk/steps)))`, starting at angle 0.
- `Clipper.TranslatePath(Path64 path, long dx, long dy) -> Path64` — shift every point by `(dx,dy)`.

## Engine class + PolyTree

- `Clipper64` — the boolean-op engine: `AddSubject(Paths64)`, `AddClip(Paths64)`, and
  `Execute(ClipType, FillRule, Paths64 solution) -> bool` / `Execute(ClipType, FillRule, PolyTree64
  solution) -> bool`.
- `PolyTree64` — a hierarchical result (`class PolyTree64 : PolyPath64`): the root has `Count` children,
  an indexer `this[int]` and `Child(int)` both returning `PolyPath64`. Each `PolyPath64` exposes:
  - `bool IsHole` (a property),
  - `int Count` (a property — the number of child rings),
  - `PolyPath64 this[int]` and `PolyPath64 Child(int)`,
  - `Path64? Polygon` (the ring; `null` for the tree root).

  The tree nests rings by containment: a top-level outer polygon is not a hole and its
  directly-contained ring is a hole, and so on, alternating with depth.

## Minkowski operations (static methods on `Clipper`)

- `Clipper.MinkowskiSum(Path64 pattern, Path64 path, bool isClosed) -> Paths64` — the Minkowski sum of
  `pattern` swept along `path`. When `isClosed` is true the path is treated as a closed polygon
  (sweeping the pattern around it yields a band — an outer ring plus an inner hole); when false the path
  is an open polyline (a single closed outline around the swept line).
- `Clipper.MinkowskiDiff(Path64 pattern, Path64 path, bool isClosed) -> Paths64` — the Minkowski
  difference, i.e. the sum with the pattern negated (so it differs from the sum for an asymmetric
  pattern).
- (`PathsD` overloads take a trailing `int decimalPlaces = 2`.) Results follow the same output contract
  as the boolean ops (closed rings, no duplicated closing vertex, outer = positive area / hole =
  negative, compared up to ring rotation and path order).

## Triangulation (static method on `Clipper`)

- `Clipper.Triangulate(Paths64 polygons, out Paths64 solution, bool useDelaunay = true) ->
  TriangulateResult` — set `solution` to a triangulation of the input polygon(s): a set of triangles
  (each a 3-vertex `Path64`) that partition the polygon interior using only the input vertices (no extra
  / Steiner points). Returns `TriangulateResult.success` on success. For a simple polygon of `n`
  vertices the triangulation has exactly `n - 2` triangles whose (unsigned) areas sum to the polygon's
  area. The *exact* triangle set is implementation-defined — any valid triangulation satisfying these
  invariants is acceptable.
- `public enum TriangulateResult { success, fail, noPolygons, pathsIntersect }`.
- (A `PathsD` overload `Clipper.Triangulate(PathsD, int decPlaces, out PathsD solution, bool useDelaunay
  = true)` also exists.)
