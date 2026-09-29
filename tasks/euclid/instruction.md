# Euclid — a 3D Geometry & Constructive Solid Geometry Library

Implement Euclid in Swift: a value-type 3D geometry library whose centerpiece is **constructive
solid geometry (CSG)** — boolean operations (union, intersection, difference, symmetric difference) on
polygon meshes.

## Deliverable and build

- Produce a Swift Package Manager package exposing a **library product named `Euclid`**, importable as
  `import Euclid`. Write `/app/setup.sh` that builds it offline (`swift build`). Pure Swift +
  Foundation; no third-party or Apple-only frameworks. Target Swift 5.10.

## Vector

`Vector` is a 3-component double vector with `x`, `y`, `z` and `init(_ x: Double, _ y: Double, _ z: Double)`.
Supports `length`, `dot(_:)`, `cross(_:)`, `normalized()`, and `Equatable`/`Comparable` (`Comparable`
orders lexicographically by `x`, then `y`, then `z`). Equality uses a small epsilon tolerance.

## Bounds

`Bounds` is an axis-aligned bounding box with `min: Vector` and `max: Vector` and an
`init(min:max:)`. An empty bounds has `min` = +infinity and `max` = -infinity. It also provides
`center: Vector`, `size: Vector`, and `union(_:)` / `intersection(_:)` (the combined / overlapping
box of two bounds). `Bounds` is `Equatable` — two bounds are equal when their `min` and `max`
vectors are equal (it inherits `Vector`'s equality).

## Angle, Rotation, Plane

- `Angle` represents an angle; build with `Angle.degrees(_ d: Double)` (also `.radians`).
- `Rotation` is a 3D rotation; the failable `Rotation(axis: Vector, angle: Angle)` builds a rotation
  about an axis.
- `Plane` is an oriented plane; the failable `Plane(normal: Vector, pointOnPlane: Vector)` builds one.
  Its `normal` points to the plane's "positive" side.

## Mesh

`Mesh` is a collection of convex `polygons` (`var polygons: [Polygon]`, where each `Polygon` exposes
its `vertices: [Vertex]`) with `var bounds: Bounds` (the AABB of all vertices). Meshes are value types. It also exposes the observable geometric
properties used for grading:

- `var volume: Double` — the absolute volume of the solid enclosed by the mesh.
- `func containsPoint(_ point: Vector) -> Bool` — whether a point lies inside the solid.
- `var isWatertight: Bool` — whether the mesh forms a closed, manifold surface.

### Primitive constructors

All three are unit-sized, centered at the origin, watertight, and have bounds `[-0.5,-0.5,-0.5]` …
`[0.5,0.5,0.5]`:

- `Mesh.cube()` — a unit cube (volume 1).
- `Mesh.sphere()` — a unit-diameter UV sphere.
- `Mesh.cylinder()` — a unit-diameter, unit-height cylinder whose axis of symmetry is the Y axis.

(You choose the sphere/cylinder tessellation; only the observable properties above are graded, not the
exact polygon decomposition.)

- `Mesh.cone()` — a unit cone (apex toward +Y), same unit bounds, watertight.

### Building meshes from paths

`Path` is a 2D/3D polyline built from `PathPoint`s. Constructors used here: `Path.square()` (a unit
square in the XY plane centered at the origin) and `Path(_ points: [PathPoint])` where points come
from `PathPoint.point(_ x: Double, _ y: Double)`. Like `Mesh`, a `Path` is transformable —
`translated(by: Vector)`, `scaled(by: Double)`, and `rotated(by: Rotation)` return a transformed copy
— so a cross-section can be positioned in 3D (e.g. a square placed at a non-zero Z for `loft`).

- `Mesh.extrude(_ path: Path)` — extrude a closed 2D path along Z into a solid (extruding a unit
  square yields a unit cube, volume 1, watertight).
- `Mesh.lathe(_ path: Path)` — revolve a 2D path around the Y axis into a watertight solid of
  revolution.
- `Mesh.loft(_ shapes: [Path])` — build a solid by lofting through a sequence of cross-section paths.

### Other mesh operations

- `Mesh.triangulate()` — return a mesh whose polygons are all triangles (every polygon in `polygons`
  has exactly three `vertices`); it represents the **same solid** (identical volume, bounds,
  containment, watertightness).
- `Mesh.inverted()` — turn the solid inside-out (flips face orientation), so a point that was inside
  becomes outside and vice versa.
- `Mesh.clipped(to plane: Plane)` — the portion of the mesh on the plane's positive-normal side
  (capped so it stays a closed solid).

### Transforms

`translated(by: Vector)`, `scaled(by: Double)`, and `rotated(by: Rotation)` return a transformed copy;
`bounds` reflects the transform and `volume` is preserved by translation/rotation.

### CSG boolean operations

Each takes another mesh and returns the combined solid:

- `union(_:)` — volume in either mesh.
- `intersection(_:)` — volume in both (empty if disjoint).
- `subtracting(_:)` — volume in the receiver but not the argument (empty when subtracting an identical
  mesh).
- `symmetricDifference(_:)` — volume in exactly one mesh.

Results are graded on **observable geometry** — `volume`, `containsPoint`, `bounds`, watertightness,
and emptiness — not on internal polygon counts. The boolean semantics must be exact: a point is in
the union iff it is in either operand, in the intersection iff in both, in the difference iff in the
receiver but not the argument, and in the symmetric difference iff in exactly one. For two unit cubes
offset by `0.5` on X: union volume = 1.5, intersection = 0.5, difference = 0.5, symmetric
difference = 1.0; subtracting a mesh from itself yields an empty mesh; intersecting disjoint meshes
yields an empty mesh.
