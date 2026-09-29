# geom2d — a 2D collision-detection library (TypeScript)

Build **geom2d**, a 2D collision-detection library for games and simulations. It maintains a world
of geometric bodies (discs, rectangles, polygons, ovals, segments, points), finds which bodies
overlap using a broad-phase bounding-box pass followed by exact narrow-phase geometry, reports rich
collision details (penetration depth and direction, containment, contact points), casts rays, and
pushes overlapping bodies apart.

## Environment & deliverable

- **Language:** TypeScript. The environment is **offline** — do not attempt to install anything.
- **Entry point:** export the entire public API from **`/app/src/index.ts`**. You may split the
  implementation across as many files under `/app/src/` as you like, but every symbol below must be
  importable directly from `/app/src/index.ts`.
- **No build step:** the hidden test suite imports `/app/src/index.ts` directly and runs it with an
  on-the-fly TypeScript loader, so there is nothing to compile. Provide a `/app/setup.sh` (it is run
  via `bash`, offline, before the tests run); it can be a no-op (`:`).
- The tests import named exports from `/app/src/index.ts` and assert exact numeric/boolean results.

## Coordinate conventions

- A **vector** is `{ x: number, y: number }`. The plane is standard screen coordinates.
- An **AABB** (axis-aligned bounding box) is `{ minX, minY, maxX, maxY }`.
- Angles are in **radians**. `deg2rad(deg)` and `rad2deg(rad)` convert between the two
  (`deg2rad(180) === Math.PI`, `rad2deg(Math.PI) === 180`).

## Bodies

All bodies are created either by direct construction or through a `CollisionWorld` factory method
(which also inserts them into the world — see below). Every body supports the shared behaviors in
the **Body transforms & options** section. The body classes and their constructors:

- **`Disc`** — `new Disc(position, radius, options?)`. A circle centered on `position` with the
  given radius. Its AABB is `[x - r, x + r] × [y - r, y + r]`. Exposes `x`, `y`, `r`, `radius`.
- **`Rect`** — `new Rect(position, width, height, options?)`. An axis-aligned rectangle whose
  corner is at `position` (AABB `[x, x + w] × [y, y + h]`) unless created centered (see
  `isCentered`). Exposes `width` and `height` setters that resize it.
- **`Poly`** — `new Poly(position, points, options?)`. A polygon; `points` is an array of vectors
  **relative to** `position`. Constructing with an empty `points` array throws; a single point is
  allowed. The given point order is preserved (an untransformed polygon's `calcPoints` equal the
  input points — see below). A polygon may be **convex or concave**; concave polygons are handled
  correctly in all collision queries.
- **`Oval`** — `new Oval(position, radiusX, radiusY?, step?, options?)`. An ellipse approximated as
  a polygon. `radiusY` defaults to `radiusX`. `options` is the **fifth** argument (after the
  optional `step`). Exposes `radiusX`, `radiusY`.
- **`Segment`** — `new Segment(start, end, options?)`. A line segment between two world points.
  Constructing without an `end` throws. Exposes `start` / `end` getters (in world coordinates) and
  setters that move the endpoints.
- **`Dot`** — `new Dot(position, options?)`. A point (a negligibly small body). Defaults to the
  origin when `position` is empty.

Every body also exposes a `pos: { x, y }` **world-position** vector (for `Disc`/`Oval` this is the
center; for polygonal bodies it is the reference point their `calcPoints` are relative to), plus
`x` / `y` read accessors equal to `pos.x` / `pos.y` (not just `Disc`). Because of `pos` (and `r` /
`calcPoints`), body instances are valid arguments to the exported intersection-geometry helpers
below that accept `{ pos, r }` disc or `{ pos, calcPoints }` poly shapes.

### Body transforms & options

Every body accepts an options object with (all optional):

- `isStatic` — a static body collides but is never moved by `pushApart`. Readable back as a
  boolean `isStatic` property.
- `isTrigger` — a trigger body detects overlaps but is treated as a ghost during separation.
  Readable back as a boolean `isTrigger` property.
- `isCentered` — offsets the body so it rotates about its centroid (a `Disc`/`Oval` is always
  centered).
- `angle` — initial rotation in radians.
- `padding` — extra bounding-box margin to reduce broad-phase re-insertions.
- `group` — collision-filtering group bits (see **Collision filtering**).
- `userData` — arbitrary caller data, stored verbatim (including falsy values such as `false` /
  `null`); unset leaves `userData` as `undefined`.

Every body supports (each returns the body for chaining, and takes an optional trailing
`updateNow` boolean, default `true`):

- `setPosition(x, y, updateNow?)` — teleport.
- `setAngle(radians, updateNow?)` — rotate.
- `setScale(sx, sy?, updateNow?)` — scale. Scaling is applied to the body's **original** geometry,
  so repeated `setScale` calls are **not** cumulative (`setScale(0.5)` then `setScale(0.3)` gives a
  0.3-scaled body, not 0.15). A `Disc` scales uniformly (its `scaleX === scaleY`, both equal to the
  single factor, and `setScale` ignores a differing second argument); a `Poly`/`Rect`/`Oval` honors
  independent `scaleX` / `scaleY`. Bodies expose `scaleX` / `scaleY` read accessors and a settable
  `scale` property: assigning `body.scale = f` is shorthand for a uniform `setScale(f)`, and reading
  `scale` returns the current (uniform) scale factor.
- `setOffset(offset, updateNow?)` — shift the collider relative to its position.
- `move(speed, updateNow?)` — advance the body along its facing angle (`1 speed` = `1px`).
- `getAABBAsBBox()` — the current AABB, without padding.
- `dirty` — a boolean flag. A transform with `updateNow = false` marks the body `dirty` (its
  world-tree bounds are stale) until the world's `update()` runs; with `updateNow = true` it updates
  immediately and stays clean.

`Poly` additionally exposes:
- `calcPoints` — the polygon's current vertices as `{x, y}` vectors **relative to `pos`**, after
  centering/scale/rotation are applied (i.e. the shape in local space; add `pos` to get world
  coordinates). For an uncentered, unscaled, unrotated polygon these equal the input points.
  `Rect` and `Oval` are polygon-based bodies and expose `calcPoints` the same way (a `Rect`'s are
  its four corners relative to `pos`).
- `isConvex` (boolean) and `isSimple()` (returns `false` for a self-intersecting polygon, `true`
  otherwise).
- `isCentered` — a settable boolean. When set `true`, the vertices are shifted by the polygon's
  **centroid** (the average of the vertices) so the shape is centered on `pos` — i.e. every point in
  `calcPoints` has the centroid subtracted. `Disc`/`Oval` are always centered.

> **Important — re-insertion after resizing.** Mutating a body's size *field* directly (`disc.r =
> 20`, `rect.width = 30`, `oval.radiusX = 15`) changes the shape but does **not** refresh the
> world's broad-phase tree. Until you call `world.insert(body)` again (or `world.update()`), broad-
> phase queries use the old bounds. `setScale`/`setPosition`/etc. with `updateNow = true` refresh
> automatically.

## CollisionWorld

`CollisionWorld` holds all inserted bodies in a bounding-volume hierarchy for fast broad-phase
queries. Construct with `new CollisionWorld()`.

```ts
import { CollisionWorld } from "/app/src/index.ts";

const world = new CollisionWorld();
const player = world.addRect({ x: 0, y: 0 }, 20, 20);
const wall = world.addRect({ x: 10, y: 0 }, 20, 20, { isStatic: true });
```

### Adding bodies

Each factory constructs the body, inserts it into the world, and returns it:

- `addDisc(position, radius, options?)`
- `addRect(position, width, height, options?)`
- `addPoly(position, points, options?)`
- `addOval(position, radiusX, radiusY?, step?, options?)`
- `addSegment(start, end, options?)`
- `addDot(position, options?)`

`world.insert(body)` inserts (or re-inserts, refreshing bounds) an independently constructed body.
`world.update()` refreshes the tree bounds of every dirty body.

### Detecting collisions

- **`overlaps(a, b, response?)` → boolean.** Returns whether bodies `a` and `b` collide. It first
  rejects pairs with disjoint bounding boxes, then runs exact narrow-phase geometry. When they
  collide it fills the world's `response` (see **Collision response**). Handles every body-type
  pairing, convex and concave.
- **`resolveAll(callback?, response?)` → boolean.** Checks every body against its broad-phase
  neighbors and invokes `callback(response)` once per detected colliding *ordered pair* (so a
  mutual overlap between two dynamic bodies fires the callback twice). Returns whether any collision
  occurred.
- **`resolveOne(body, callback?, response?)` → boolean.** Like `resolveAll` but only for collisions
  involving `body`: it sweeps `body` against its broad-phase neighbors and fires the callback **once
  per colliding neighbor** of `body`. Only `body` is swept as the checker (unlike `resolveAll`, which
  sweeps every body in turn), so a mutual overlap involving `body` is reported **once**, not twice.
- **`resolveArea(area, callback?, response?)` → boolean.** Like `resolveAll` but restricted to
  bodies within the AABB `area`.

```ts
world.resolveAll((response) => {
  // response.a and response.b are the colliding bodies
});
```

### Collision response

`world.response` (also passed to callbacks) is populated on each detected collision:

- `a`, `b` — the two colliding bodies.
- `overlap` — the penetration depth (a non-negative magnitude).
- `overlapV` — the minimum-translation vector `{ x, y }`: move `a` by `-overlapV` to separate it
  from `b`. Its length equals `overlap`.
- `overlapN` — the unit normal `{ x, y }` of `overlapV`.
- `aInB` — `true` if body `a` is fully contained within body `b`.
- `bInA` — `true` if body `b` is fully contained within body `a`.

For example, two discs of radius 10 whose centers are 15 apart along +x overlap with
`overlap === 5`, `overlapV === { x: 5, y: 0 }`, `overlapN === { x: 1, y: 0 }`. Two identical
coincident discs are mutually contained (`aInB && bInA`).

The touching boundary is **inclusive**: two bodies whose shapes meet with zero penetration (they
touch but do not interpenetrate) still count as a detected collision, and it is reported with
`overlap === 0` (a zero-length `overlapV`). Only a strictly positive gap between the shapes counts
as no collision.

- **`contactPoints(a, b)` → vector[].** The exact set of boundary intersection points between two
  bodies (deduplicated). Two tangent discs share one point; two squares meeting at a single corner
  share exactly that corner; non-touching bodies give `[]`.

### Raycasting

- **`castRay(start, end, allow?)` → `{ point, body } | undefined`.** Casts a ray from `start` to
  `end` and returns the **nearest** hit: the intersection `point` closest to `start` and the `body`
  hit, or `undefined` if nothing is hit. The ray spans the **closed** segment `start`–`end`, under
  the same inclusive touching boundary as elsewhere (see **Collision response**). The optional
  `allow(body, ray)` predicate filters which bodies are eligible (return `false` to ignore a body).

### Separation

- **`pushApart(callback?, response?)`.** Moves each dynamic (non-static) body out of the bodies it
  overlaps, displacing it by the accumulated minimum-translation vectors so that after `pushApart`
  (and an `update()`) the moved bodies' penetration depth is zero. Static, non-trigger bodies are
  never moved. Trigger bodies detect but do not resolve.

## Collision filtering (groups)

Each body has a 32-bit `group` combining a 16-bit **category** (high bits) and a 16-bit **mask**
(low bits). Build one with **`groupBits(category, mask?)`** (`mask` defaults to `category`), e.g.
`groupBits(0b0001, 0b0011)`. Two bodies can interact **iff each one's category intersects the
other's mask**:

```
canInteract(a, b) === ((catA & maskB) !== 0) && ((catB & maskA) !== 0)
```

where `cat = group >> 16` and `mask = group & 0xffff`. **`canInteract(a, b)` → boolean** is
exported. Bodies that cannot interact never register a collision even when their shapes overlap. The
default group interacts with everything.

## Intersection-geometry helpers

These pure functions are exported for direct use (a "line" is `{ start, end }` with vector
endpoints; a "disc" argument is `{ pos: {x,y}, r }`; a "poly" argument is `{ pos: {x,y}, calcPoints:
vector[] }` where `calcPoints` are relative to `pos`):

- **`intersectSegments(line1, line2)` → vector | undefined.** The single crossing point of two
  segments, or `undefined` if they do not cross within both segments.
- **`intersectSegmentDisc(line, disc)` → vector[].** The 0, 1, or 2 points where a segment crosses a
  circle.
- **`intersectDiscDisc(discA, discB)` → vector[].** The 0 or 2 intersection points of two circles.
- **`intersectPolys(polyA, polyB)` → vector[].** All edge-crossing points between two polygons
  (deduplicated); `[]` if disjoint, a single point for a lone corner touch.
- Containment predicates → boolean. Note the argument order carefully (the disc/poly/dot argument
  order is *contained-then-container*, except `discInDisc`, which is *container-then-contained*):
  - **`discInPoly(disc, poly)`** — `true` iff the disc lies fully inside the polygon.
  - **`dotInPoly(point, poly)`** — `true` iff the point lies inside the polygon.
  - **`polyInPoly(polyA, polyB)`** — `true` iff every point of `polyA` lies inside `polyB`.
  - **`discInDisc(outer, inner)`** — `true` iff the `inner` disc lies fully inside the `outer`
    disc (i.e. `distance(centers) + inner.r <= outer.r`).
  - **`discOutsidePoly(disc, poly)`** — `true` iff the disc lies entirely outside the polygon with
    no edge crossing.
