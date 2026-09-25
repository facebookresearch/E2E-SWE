// Hidden test suite for the geom2d 2D collision-detection task (node:test, run under tsx).
// Drives the agent's module at /app/src/index.ts through the aliased public API and asserts
// exact values. One top-level test() = one behavioral contract (one CTRF entry); every assertion
// inside must hold. Expected values captured from the reference implementation.
import { test } from "node:test";
import assert from "node:assert";
import {
  CollisionWorld,
  Rect,
  Poly,
  Dot,
  deg2rad,
  rad2deg,
  groupBits,
  canInteract,
  intersectSegments,
  intersectSegmentDisc,
  intersectDiscDisc,
  intersectPolys,
  discInPoly,
  discOutsidePoly,
  dotInPoly,
  polyInPoly,
  discInDisc,
} from "/app/src/index.ts";

// round to `dp` decimal places for float-tolerant exact comparison
const r = (n: number, dp = 6): number => Math.round(n * 10 ** dp) / 10 ** dp + 0;
const rp = (p: { x: number; y: number }, dp = 6) => ({ x: r(p.x, dp), y: r(p.y, dp) });
// sort points into a canonical (x, then y) order for order-insensitive set comparison
const sortPts = (ps: { x: number; y: number }[]) =>
  [...ps].sort((a, b) => a.x - b.x || a.y - b.y);

// ---------------------------------------------------------------------------
// Body creation + geometry (AABB bounds after construction)
// ---------------------------------------------------------------------------

test("test_disc_creation_and_bounds", () => {
  // A disc is centered on its position; its AABB spans [x-r, x+r] x [y-r, y+r].
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 10, y: 20 }, 5);
  assert.strictEqual(disc.x, 10);
  assert.strictEqual(disc.y, 20);
  const bbox = disc.getAABBAsBBox();
  assert.deepStrictEqual(bbox, { minX: 5, minY: 15, maxX: 15, maxY: 25 });
});

test("test_rect_creation_and_bounds", () => {
  // A rectangle's corner sits at its position; AABB spans [x, x+w] x [y, y+h].
  const world = new CollisionWorld();
  const rect = world.addRect({ x: 10, y: 10 }, 100, 40);
  const bbox = rect.getAABBAsBBox();
  assert.deepStrictEqual(bbox, { minX: 10, minY: 10, maxX: 110, maxY: 50 });
});

test("test_poly_creation_and_bounds", () => {
  // A polygon's points are relative to its position; AABB is the min/max of world points.
  const world = new CollisionWorld();
  const poly = world.addPoly({ x: 5, y: 5 }, [
    { x: 0, y: 0 },
    { x: 20, y: 0 },
    { x: 20, y: 10 },
    { x: 0, y: 10 },
  ]);
  const bbox = poly.getAABBAsBBox();
  assert.deepStrictEqual(bbox, { minX: 5, minY: 5, maxX: 25, maxY: 15 });
});

test("test_segment_endpoints", () => {
  // A segment exposes start/end getters in world coordinates; setting them moves the segment.
  const world = new CollisionWorld();
  const seg = world.addSegment({ x: 13, y: 13 }, { x: 69, y: 69 });
  assert.deepStrictEqual(rp(seg.start), { x: 13, y: 13 });
  assert.deepStrictEqual(rp(seg.end), { x: 69, y: 69 });
  seg.start = { x: 10, y: 10 };
  assert.deepStrictEqual(rp(seg.start), { x: 10, y: 10 });
  seg.end = { x: 99, y: 99 };
  assert.deepStrictEqual(rp(seg.end), { x: 99, y: 99 });
});

test("test_dot_creation", () => {
  // A dot defaults to the origin when no coordinates are supplied and is a tiny body.
  const world = new CollisionWorld();
  const dot = new Dot({});
  assert.strictEqual(dot.x, 0);
  assert.strictEqual(dot.y, 0);
  const placed = world.addDot({ x: 7, y: 8 });
  assert.strictEqual(placed.x, 7);
  assert.strictEqual(placed.y, 8);
});

test("test_poly_requires_points", () => {
  // Constructing a polygon with no points throws; a single point is allowed.
  assert.throws(() => new Poly({}, []));
  assert.doesNotThrow(() => new Poly({}, [{ x: 0, y: 0 }]));
});

test("test_poly_convexity_and_simplicity", () => {
  // isConvex reflects shape; isSimple() detects self-intersection.
  const simpleConvex = new Poly({}, [
    { x: 144.890625, y: 389.609375 },
    { x: 144.890625, y: 211.6875 },
    { x: 289.6171875, y: 231.3203125 },
    { x: 297.53125, y: 407.0859375 },
  ]);
  const simpleConcave = new Poly({}, [
    { x: 144.890625, y: 389.609375 },
    { x: 144.890625, y: 211.6875 },
    { x: 289.6171875, y: 231.3203125 },
    { x: 297.53125, y: 407.0859375 },
    { x: 223.2890625, y: 303.015625 },
  ]);
  const selfIntersecting = new Poly({}, [
    { x: 124.1953125, y: 209.5546875 },
    { x: 276.203125, y: 396.7109375 },
    { x: 99.5546875, y: 363.4140625 },
    { x: 305.1015625, y: 215.703125 },
  ]);
  assert.strictEqual(simpleConvex.isConvex, true);
  assert.strictEqual(simpleConvex.isSimple(), true);
  assert.strictEqual(simpleConcave.isConvex, false);
  assert.strictEqual(simpleConcave.isSimple(), true);
  assert.strictEqual(selfIntersecting.isSimple(), false);
});

// ---------------------------------------------------------------------------
// Transforms
// ---------------------------------------------------------------------------

test("test_deg_rad_conversion", () => {
  // Angle helpers convert between degrees and radians exactly.
  assert.strictEqual(deg2rad(180), Math.PI);
  assert.strictEqual(deg2rad(90), Math.PI / 2);
  assert.strictEqual(rad2deg(Math.PI), 180);
  assert.strictEqual(r(rad2deg(Math.PI / 2)), 90);
});

test("test_disc_set_position", () => {
  // setPosition teleports a disc and updates its AABB.
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 0, y: 0 }, 10);
  disc.setPosition(1, -1);
  assert.strictEqual(disc.x, 1);
  assert.strictEqual(disc.y, -1);
  assert.deepStrictEqual(disc.getAABBAsBBox(), { minX: -9, minY: -11, maxX: 11, maxY: 9 });
});

test("test_disc_scale_uniform", () => {
  // A disc scales uniformly; both scale axes track the same factor, radius scales with it.
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 0, y: 0 }, 9);
  disc.scale = 4;
  assert.strictEqual(disc.scale, 4);
  disc.setScale(Math.PI, 3);
  assert.strictEqual(disc.scaleX, Math.PI);
  assert.strictEqual(disc.scaleY, Math.PI);
  assert.strictEqual(r(disc.r), r(9 * Math.PI));
});

test("test_poly_scale_nonuniform", () => {
  // A polygon honours independent scaleX/scaleY and rescales from the original points.
  const world = new CollisionWorld();
  const poly = world.addPoly({ x: 0, y: 0 }, [
    { x: -10, y: -10 },
    { x: -10, y: 10 },
    { x: 10, y: 10 },
    { x: 10, y: -10 },
  ]);
  poly.scale = 4;
  assert.strictEqual(poly.scale, 4);
  poly.setScale(2, 3);
  assert.strictEqual(poly.scaleX, 2);
  assert.strictEqual(poly.scaleY, 3);
  // Non-uniform scale must reshape the geometry: the original +/-10 box scaled by (x*2, y*3)
  // has an AABB spanning x in [-20, 20] and y in [-30, 30].
  assert.deepStrictEqual(poly.getAABBAsBBox(), { minX: -20, minY: -30, maxX: 20, maxY: 30 });
});

test("test_poly_rescale_from_original", () => {
  // Repeated setScale calls are not cumulative: the AABB reflects the latest factor on the
  // original points, not a product of previous factors.
  const world = new CollisionWorld();
  const poly = world.addPoly({ x: 0, y: 0 }, [
    { x: -10, y: -10 },
    { x: -10, y: 10 },
    { x: 10, y: 10 },
    { x: 10, y: -10 },
  ]);
  poly.setScale(0.7);
  poly.setScale(0.5);
  poly.setScale(0.3);
  const bbox = poly.getAABBAsBBox();
  assert.deepStrictEqual(bbox, { minX: -3, minY: -3, maxX: 3, maxY: 3 });
});

test("test_poly_iscentered_reversible", () => {
  // Centering shifts a polygon's points so its centroid sits at the origin (relative to pos),
  // which moves the body's AABB; isCentered is a live, settable property.
  const points = [
    { x: 40, y: 20 },
    { x: 200, y: 100 },
    { x: 100, y: 60 },
  ];
  const uncentered = new Poly({ x: 100, y: 50 }, points, { isCentered: false });
  const centered = new Poly({ x: 100, y: 50 }, points, { isCentered: true });

  // Uncentered: calcPoints are the raw input points; AABB = points offset by pos.
  assert.strictEqual(uncentered.isCentered, false);
  assert.deepStrictEqual(uncentered.calcPoints.map((p) => rp(p)), [
    { x: 40, y: 20 },
    { x: 200, y: 100 },
    { x: 100, y: 60 },
  ]);
  const ub = uncentered.getAABBAsBBox();
  assert.strictEqual(r(ub.minX), 140);
  assert.strictEqual(r(ub.minY), 70);
  assert.strictEqual(r(ub.maxX), 300);
  assert.strictEqual(r(ub.maxY), 150);

  // Centered: the points are shifted by the polygon centroid so the body is centered on pos.
  assert.strictEqual(centered.isCentered, true);
  const cp = centered.calcPoints.map((p) => rp(p));
  assert.deepStrictEqual(cp, [
    { x: -73.333333, y: -40 },
    { x: 86.666667, y: 40 },
    { x: -13.333333, y: 0 },
  ]);

  // isCentered is a live, settable property.
  uncentered.isCentered = true;
  assert.strictEqual(uncentered.isCentered, true);
  assert.deepStrictEqual(uncentered.calcPoints.map((p) => rp(p)), cp);
});

test("test_rect_centered_bounds", () => {
  // A centered rectangle is centered on its position: its AABB is symmetric about pos, spanning
  // [x - w/2, x + w/2] x [y - h/2, y + h/2] -- not corner-anchored like a default rect.
  const world = new CollisionWorld();
  const centered = world.addRect({ x: 5, y: 5 }, 20, 20, { isCentered: true });
  const cb = centered.getAABBAsBBox();
  assert.deepStrictEqual(
    { minX: r(cb.minX), minY: r(cb.minY), maxX: r(cb.maxX), maxY: r(cb.maxY) },
    { minX: -5, minY: -5, maxX: 15, maxY: 15 }
  );
  // The width / height setters resize the box: its span tracks the new dimensions.
  const rect = new Rect({ x: 5, y: 5 }, 10, 10, { isCentered: true });
  rect.width = 20;
  rect.height = 20;
  world.insert(rect);
  const bbox = rect.getAABBAsBBox();
  assert.strictEqual(r(bbox.maxX - bbox.minX), 20);
  assert.strictEqual(r(bbox.maxY - bbox.minY), 20);
});

test("test_dirty_batching_and_update", () => {
  // A deferred transform (updateNow=false) marks the body dirty until the world updates it.
  const world = new CollisionWorld();
  const poly = world.addPoly({ x: -100, y: -100 }, [
    { x: 0, y: 0 },
    { x: 10, y: 0 },
    { x: 10, y: 10 },
    { x: 0, y: 10 },
  ]);
  poly.setPosition(0, 0, false);
  assert.strictEqual(poly.dirty, true);
  world.update();
  assert.strictEqual(poly.dirty, false);
});

test("test_move_along_angle", () => {
  // move(speed) advances the body along its facing angle (1 speed = 1px).
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 0, y: 0 }, 5);
  disc.setAngle(0);
  disc.move(10);
  assert.strictEqual(r(disc.x), 10);
  assert.strictEqual(r(disc.y), 0);
  disc.setAngle(deg2rad(90));
  disc.move(10);
  assert.strictEqual(r(disc.x), 10);
  assert.strictEqual(r(disc.y), 10);
});

// ---------------------------------------------------------------------------
// Broad + narrow phase collision
// ---------------------------------------------------------------------------

test("test_overlaps_disjoint_false", () => {
  // Bodies with disjoint bounding boxes do not overlap.
  const world = new CollisionWorld();
  const a = world.addRect({ x: 10, y: 10 }, 100, 100);
  const b = world.addRect({ x: 300, y: 300 }, 100, 100);
  assert.strictEqual(world.overlaps(a, b), false);
});

test("test_overlaps_disc_disc", () => {
  // Two overlapping discs collide; separated discs do not.
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 10);
  const b = world.addDisc({ x: 15, y: 0 }, 10);
  assert.strictEqual(world.overlaps(a, b), true);
  const c = world.addDisc({ x: 25, y: 0 }, 10);
  assert.strictEqual(world.overlaps(a, c), false);
});

test("test_overlaps_disc_rect", () => {
  // A disc overlapping a rectangle collides through the broad+narrow phase.
  const world = new CollisionWorld();
  const rect = world.addRect({ x: 0, y: 0 }, 20, 20);
  const inside = world.addDisc({ x: 20, y: 10 }, 5);
  assert.strictEqual(world.overlaps(rect, inside), true);
  const outside = world.addDisc({ x: 40, y: 10 }, 5);
  assert.strictEqual(world.overlaps(rect, outside), false);
});

test("test_overlaps_concave_circle", () => {
  // A concave (comb-shaped) polygon overlaps a disc sitting in one of its notches.
  const world = new CollisionWorld();
  const concave = world.addPoly({ x: 0, y: 0 }, [
    { x: -11.25, y: -6.76 },
    { x: -12.5, y: -6.76 },
    { x: -12.5, y: 6.75 },
    { x: -3.1, y: 6.75 },
    { x: -3.1, y: 0.41 },
    { x: -2.35, y: 0.41 },
    { x: -2.35, y: 6.75 },
    { x: 0.77, y: 6.75 },
    { x: 0.77, y: 7.5 },
    { x: -13.25, y: 7.5 },
    { x: -13.25, y: -7.51 },
    { x: -11.25, y: -7.51 },
  ]);
  const disc = world.addDisc({ x: 0, y: 7 }, 1);
  assert.strictEqual(world.overlaps(concave, disc), true);
});

test("test_overlaps_concave_convex_disjoint", () => {
  // A concave polygon and a convex polygon that do not touch report no collision.
  const world = new CollisionWorld();
  const concave = world.addPoly({ x: 0, y: 0 }, [
    { x: 190, y: 147 },
    { x: 256, y: 265 },
    { x: 400, y: 274 },
    { x: 360, y: 395 },
    { x: 80, y: 350 },
  ]);
  const convex = world.addPoly({ x: 0, y: 0 }, [
    { x: 273, y: 251 },
    { x: 200, y: 120 },
    { x: 230, y: 40 },
    { x: 320, y: 10 },
    { x: 440, y: 86 },
    { x: 440, y: 220 },
  ]);
  assert.strictEqual(world.overlaps(concave, convex), false);
});

test("test_group_filtering_no_match", () => {
  // Bodies whose collision groups do not share bits never collide, even when overlapping.
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 10, { group: groupBits(0b0001, 0b0001) });
  const b = world.addDisc({ x: 0, y: 0 }, 10, { group: groupBits(0b0010, 0b0010) });
  let collisions = 0;
  world.resolveAll(() => {
    collisions++;
  });
  assert.strictEqual(collisions, 0);
});

test("test_group_filtering_match", () => {
  // Overlapping bodies with compatible group masks collide (counted both directions).
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 10, { group: groupBits(0b0001, 0b0011) });
  const b = world.addDisc({ x: 0, y: 0 }, 10, { group: groupBits(0b0010, 0b0011) });
  let collisions = 0;
  world.resolveAll(() => {
    collisions++;
  });
  assert.strictEqual(collisions, 2);
});

test("test_resolve_area_counts", () => {
  // resolveArea only reports collisions among bodies within the query box.
  const world = new CollisionWorld();
  const a = world.addRect({ x: 10, y: 10 }, 100, 100);
  const b = world.addRect({ x: 300, y: 300 }, 100, 100);
  let collisions = 0;
  world.resolveArea({ minX: 0, minY: 0, maxX: 100, maxY: 100 }, () => {
    collisions++;
  });
  assert.strictEqual(collisions, 0);
  b.setPosition(50, 50);
  world.resolveArea({ minX: 0, minY: 0, maxX: 100, maxY: 100 }, () => {
    collisions++;
  });
  assert.strictEqual(collisions, 2);
});

test("test_radius_change_needs_reinsert", () => {
  // Mutating a disc's radius does not update the broad-phase tree until it is re-inserted.
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 10);
  world.addDisc({ x: 25, y: 0 }, 10);
  let collisions = 0;
  world.resolveAll(() => collisions++);
  assert.strictEqual(collisions, 0);
  a.r = 20;
  world.resolveAll(() => collisions++);
  assert.strictEqual(collisions, 0);
  world.insert(a);
  world.resolveAll(() => collisions++);
  assert.strictEqual(collisions, 2);
});

// ---------------------------------------------------------------------------
// Collision response
// ---------------------------------------------------------------------------

test("test_response_containment_flags", () => {
  // Perfectly overlapping discs are each contained in the other (aInB && bInA).
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 10);
  const b = world.addDisc({ x: 0, y: 0 }, 10);
  const collided = world.overlaps(a, b);
  assert.strictEqual(collided, true);
  assert.strictEqual(world.response.aInB, true);
  assert.strictEqual(world.response.bInA, true);
});

test("test_response_disc_in_concave", () => {
  // A small disc fully inside a concave polygon reports aInB (disc in polygon) but not bInA.
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 71.2, y: 37.5 }, 1);
  const concave = world.addPoly({ x: 200, y: 100 }, [
    { x: -11.25, y: -6.76 },
    { x: -12.5, y: -6.76 },
    { x: -12.5, y: 6.75 },
    { x: -3.1, y: 6.75 },
    { x: -3.1, y: 0.41 },
    { x: -2.35, y: 0.41 },
    { x: -2.35, y: 6.75 },
    { x: 0.77, y: 6.75 },
    { x: 0.77, y: 7.5 },
    { x: -13.25, y: 7.5 },
    { x: -13.25, y: -7.51 },
    { x: -11.25, y: -7.51 },
  ].map(({ x, y }) => ({ x: x * 10, y: y * 10 })));
  const collided = world.overlaps(disc, concave);
  assert.strictEqual(collided, true);
  assert.strictEqual(world.response.aInB, true);
  assert.strictEqual(world.response.bInA, false);
});

test("test_response_overlap_magnitude", () => {
  // The response reports overlap depth and direction for two discs overlapping along +x.
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 10);
  const b = world.addDisc({ x: 15, y: 0 }, 10);
  world.overlaps(a, b);
  // centers 15 apart, radii sum 20 -> penetration depth 5 along +x
  assert.strictEqual(r(world.response.overlap), 5);
  assert.strictEqual(r(world.response.overlapV.x), 5);
  assert.strictEqual(r(world.response.overlapV.y), 0);
  assert.strictEqual(r(world.response.overlapN.x), 1);
  assert.strictEqual(r(world.response.overlapN.y), 0);
});

test("test_contact_points_disc_disc", () => {
  // Two tangent discs touch at exactly one contact point.
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 10, y: 10 }, 10);
  const b = world.addDisc({ x: 30, y: 10 }, 10);
  const points = world.contactPoints(a, b).map((p) => rp(p));
  assert.deepStrictEqual(points, [{ x: 20, y: 10 }]);
});

test("test_contact_points_disc_rect", () => {
  // A disc tangent to a rectangle edge touches at one contact point.
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 10, y: 10 }, 10);
  const rect = world.addRect({ x: 20, y: 0 }, 20, 20);
  const points = world.contactPoints(disc, rect).map((p) => rp(p));
  assert.deepStrictEqual(points, [{ x: 20, y: 10 }]);
});

test("test_contact_points_poly_corner_touch", () => {
  // Two squares meeting at a single corner have exactly that corner as their contact point.
  const world = new CollisionWorld();
  const a = world.addPoly({ x: 0, y: 0 }, [
    { x: 0, y: 0 },
    { x: 0, y: 10 },
    { x: 10, y: 10 },
    { x: 10, y: 0 },
  ]);
  const b = world.addPoly({ x: 0, y: 0 }, [
    { x: 10, y: 10 },
    { x: 10, y: 20 },
    { x: 20, y: 20 },
    { x: 20, y: 10 },
  ]);
  const points = world.contactPoints(a, b).map((p) => rp(p));
  assert.deepStrictEqual(points, [{ x: 10, y: 10 }]);
});

// ---------------------------------------------------------------------------
// Intersection geometry (exported helpers)
// ---------------------------------------------------------------------------

test("test_intersect_segments", () => {
  // Two crossing segments intersect at their exact crossing point; parallel ones do not.
  const hit = intersectSegments(
    { start: { x: 0, y: 0 }, end: { x: 100, y: 100 } },
    { start: { x: 100, y: 0 }, end: { x: 0, y: 100 } }
  );
  assert.deepStrictEqual(rp(hit!), { x: 50, y: 50 });
  const miss = intersectSegments(
    { start: { x: 0, y: 0 }, end: { x: 10, y: 0 } },
    { start: { x: 0, y: 5 }, end: { x: 10, y: 5 } }
  );
  assert.strictEqual(miss, undefined);
});

test("test_intersect_segment_disc", () => {
  // A chord through a disc yields its two exact circle-crossing points. The segment
  // (0,0)->(100,100) meets the circle at (50,50) r=10 on the diameter at 50 +/- sqrt(50).
  // The order the two points come back in is unspecified, so compare as an unordered set.
  const points = intersectSegmentDisc(
    { start: { x: 0, y: 0 }, end: { x: 100, y: 100 } },
    { pos: { x: 50, y: 50 }, r: 10 }
  ).map((p) => rp(p));
  assert.strictEqual(points.length, 2);
  assert.deepStrictEqual(sortPts(points), [
    { x: 42.928932, y: 42.928932 },
    { x: 57.071068, y: 57.071068 },
  ]);
});

test("test_intersect_disc_disc", () => {
  // Two overlapping discs intersect at two symmetric points.
  const points = intersectDiscDisc(
    { pos: { x: 0, y: 0 }, r: 5 },
    { pos: { x: 8, y: 0 }, r: 5 }
  ).map((p) => rp(p));
  // x = (25 - 25 + 64)/(16) = 4 ; h = sqrt(25 - 16) = 3. The two solutions are symmetric about
  // the center line and their emission order is unspecified, so compare as an unordered set.
  assert.strictEqual(points.length, 2);
  assert.deepStrictEqual(sortPts(points), [
    { x: 4, y: -3 },
    { x: 4, y: 3 },
  ]);
});

test("test_intersect_polys", () => {
  // Polygon-polygon intersection: disjoint -> [], single corner touch -> one point.
  const disjoint = intersectPolys(
    { pos: { x: 0, y: 0 }, calcPoints: [{ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }, { x: 10, y: 0 }] },
    { pos: { x: 0, y: 0 }, calcPoints: [{ x: 20, y: 20 }, { x: 20, y: 30 }, { x: 30, y: 30 }, { x: 30, y: 20 }] }
  );
  assert.deepStrictEqual(disjoint, []);
  const corner = intersectPolys(
    { pos: { x: 0, y: 0 }, calcPoints: [{ x: 0, y: 0 }, { x: 0, y: 10 }, { x: 10, y: 10 }, { x: 10, y: 0 }] },
    { pos: { x: 0, y: 0 }, calcPoints: [{ x: 10, y: 10 }, { x: 10, y: 20 }, { x: 20, y: 20 }, { x: 20, y: 10 }] }
  ).map((p) => rp(p));
  assert.deepStrictEqual(corner, [{ x: 10, y: 10 }]);
});

test("test_disc_outside_poly", () => {
  // discOutsidePoly is true when a disc lies entirely outside a polygon with no edge crossing,
  // and false when the disc overlaps the polygon (a disc whose center is inside the rect) -- so a
  // constant-true implementation that never computes outside-ness cannot pass.
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 100, y: 100 }, 50);
  const rect = world.addRect({ x: 115, y: 152 }, 100, 100);
  assert.strictEqual(discOutsidePoly(disc, rect), true);
  const overlapping = world.addDisc({ x: 165, y: 200 }, 20);
  assert.strictEqual(discOutsidePoly(overlapping, rect), false);
});

test("test_containment_predicates", () => {
  // The exported containment predicates: contained-then-container order, except discInDisc which
  // is outer-then-inner.
  const world = new CollisionWorld();
  const rect = world.addRect({ x: 0, y: 0 }, 100, 100);
  const inside = world.addDisc({ x: 50, y: 50 }, 5);
  const crossing = world.addDisc({ x: 5, y: 50 }, 10);
  assert.strictEqual(discInPoly(inside, rect), true);
  assert.strictEqual(discInPoly(crossing, rect), false);
  assert.strictEqual(dotInPoly({ x: 50, y: 50 }, rect), true);
  assert.strictEqual(dotInPoly({ x: 150, y: 150 }, rect), false);
  const smallRect = world.addRect({ x: 40, y: 40 }, 10, 10);
  assert.strictEqual(polyInPoly(smallRect, rect), true);
  const bigRect = world.addRect({ x: 0, y: 0 }, 200, 200);
  assert.strictEqual(polyInPoly(bigRect, rect), false);
  const outer = world.addDisc({ x: 0, y: 0 }, 10);
  const inner = world.addDisc({ x: 0, y: 0 }, 2);
  assert.strictEqual(discInDisc(outer, inner), true);
  assert.strictEqual(discInDisc(inner, outer), false);
});

test("test_can_interact_predicate", () => {
  // canInteract combines category/mask bits: interaction requires each body's category to
  // intersect the other's mask. Identical groups always interact.
  const world = new CollisionWorld();
  const a = world.addDisc({ x: 0, y: 0 }, 1, { group: groupBits(0b0001, 0b0001) });
  const b = world.addDisc({ x: 0, y: 0 }, 1, { group: groupBits(0b0010, 0b0010) });
  const c = world.addDisc({ x: 0, y: 0 }, 1, { group: groupBits(0b0001, 0b0011) });
  const d = world.addDisc({ x: 0, y: 0 }, 1, { group: groupBits(0b0010, 0b0011) });
  assert.strictEqual(canInteract(a, b), false);
  assert.strictEqual(canInteract(a, a), true);
  assert.strictEqual(canInteract(c, d), true);
});

// ---------------------------------------------------------------------------
// Raycasting
// ---------------------------------------------------------------------------

test("test_raycast_rect", () => {
  // A ray hits a convex polygon (here an axis-aligned rectangle) at the exact near edge crossing.
  const world = new CollisionWorld();
  world.addRect({ x: 50, y: 50 }, 100, 100);
  const hit = world.castRay({ x: 0, y: 0 }, { x: 100, y: 100 });
  assert.notStrictEqual(hit, undefined);
  assert.deepStrictEqual(rp(hit!.point), { x: 50, y: 50 });
  // The ray is the CLOSED segment start..end and the touching boundary is inclusive, so a polygon
  // grazed at a single corner that sits exactly on the ray's far endpoint is still a hit (t=1, no
  // interior penetration). Poly points are relative to pos, so the world corners are (100,100),
  // (200,100), (200,200), (100,200) and the ray from the origin just reaches the near corner.
  const world2 = new CollisionWorld();
  const poly = world2.addPoly({ x: 50, y: 50 }, [
    { x: 50, y: 50 },
    { x: 150, y: 50 },
    { x: 150, y: 150 },
    { x: 50, y: 150 },
  ]);
  const grazed = world2.castRay({ x: 0, y: 0 }, { x: 100, y: 100 });
  assert.notStrictEqual(grazed, undefined);
  assert.deepStrictEqual(rp(grazed!.point), { x: 100, y: 100 });
  assert.strictEqual(grazed!.body, poly);
});

test("test_raycast_segment", () => {
  // A ray crossing a segment hits at the crossing point.
  const world = new CollisionWorld();
  world.addSegment({ x: 100, y: 0 }, { x: 0, y: 100 });
  const hit = world.castRay({ x: 0, y: 0 }, { x: 100, y: 100 });
  assert.notStrictEqual(hit, undefined);
  assert.deepStrictEqual(rp(hit!.point), { x: 50, y: 50 });
});

test("test_raycast_allow_filter", () => {
  // The allow callback can veto a body so the ray reports the next eligible hit or none.
  const world = new CollisionWorld();
  const rect = world.addRect({ x: 50, y: 50 }, 100, 100);
  const blocked = world.castRay({ x: 0, y: 0 }, { x: 100, y: 100 }, (body) => body !== rect);
  assert.strictEqual(blocked, undefined);
});

// ---------------------------------------------------------------------------
// Separation
// ---------------------------------------------------------------------------

test("test_push_apart_out_of_wall", () => {
  // pushApart displaces a dynamic body by the minimum-translation vector out of a static wall,
  // eliminating the penetration depth.
  const world = new CollisionWorld();
  const player = world.addRect({ x: 0, y: 0 }, 20, 20);
  world.addRect({ x: 10, y: 0 }, 20, 20, { isStatic: true });
  world.resolveOne(player);
  assert.strictEqual(r(world.response.overlap), 10);
  world.pushApart();
  assert.strictEqual(r(player.x), -10);
  assert.strictEqual(r(player.y), 0);
  world.update();
  world.resolveOne(player);
  assert.strictEqual(r(world.response.overlap), 0);
});

test("test_static_body_not_separated", () => {
  // A static, non-trigger body is never moved by pushApart.
  const world = new CollisionWorld();
  const wall = world.addRect({ x: 0, y: 0 }, 20, 20, { isStatic: true });
  world.addRect({ x: 10, y: 0 }, 20, 20);
  const { x, y } = wall;
  world.pushApart();
  assert.strictEqual(wall.x, x);
  assert.strictEqual(wall.y, y);
});

// ---------------------------------------------------------------------------
// userData / options round-trip
// ---------------------------------------------------------------------------

test("test_userdata_roundtrip", () => {
  // userData is stored verbatim, including falsy values; unset stays undefined.
  const world = new CollisionWorld();
  assert.strictEqual(world.addDisc({ x: 0, y: 0 }, 1).userData, undefined);
  assert.strictEqual(world.addDisc({ x: 0, y: 0 }, 1, { userData: { thank: "you" } }).userData.thank, "you");
  assert.strictEqual(world.addDisc({ x: 0, y: 0 }, 1, { userData: false }).userData, false);
  assert.strictEqual(world.addDisc({ x: 0, y: 0 }, 1, { userData: null }).userData, null);
});

test("test_body_options_flags", () => {
  // isStatic / isTrigger options are recorded on every body type, and a trigger body has its
  // documented observable effect: it still detects overlaps but is a ghost during separation
  // (pushApart never moves it).
  const world = new CollisionWorld();
  const disc = world.addDisc({ x: 0, y: 0 }, 5, { isStatic: true, isTrigger: true });
  assert.strictEqual(disc.isStatic, true);
  assert.strictEqual(disc.isTrigger, true);
  const seg = world.addSegment({ x: 0, y: 0 }, { x: 10, y: 0 }, { isStatic: true, isTrigger: true });
  assert.strictEqual(seg.isStatic, true);
  assert.strictEqual(seg.isTrigger, true);
  // A dynamic trigger body overlapping a static wall is still reported by resolveOne (detected),
  // but pushApart leaves it in place -- triggers detect collisions without resolving them.
  const w2 = new CollisionWorld();
  const trigger = w2.addRect({ x: 0, y: 0 }, 20, 20, { isTrigger: true });
  w2.addRect({ x: 10, y: 0 }, 20, 20, { isStatic: true });
  let detected = 0;
  w2.resolveOne(trigger, () => detected++);
  // resolveOne fires the callback once per colliding neighbor; the trigger overlaps exactly one
  // wall, so the count is deterministically 1 (a checkOne that double-reports would fail here).
  assert.strictEqual(detected, 1);
  w2.pushApart();
  w2.update();
  assert.strictEqual(r(trigger.x), 0);
  assert.strictEqual(r(trigger.y), 0);
});

test("test_oval_creation_and_overlap", () => {
  // An oval (ellipse) has its radii available and overlaps a coincident oval.
  const world = new CollisionWorld();
  const oval = world.addOval({ x: 0, y: 0 }, 10, 30);
  assert.strictEqual(oval.radiusX, 10);
  assert.strictEqual(oval.radiusY, 30);
  const other = world.addOval({ x: 0, y: 0 }, 10, 30);
  assert.strictEqual(world.overlaps(oval, other), true);
});

// ---------------------------------------------------------------------------
// Harder cases: exact geometry, accumulation, rotation
// ---------------------------------------------------------------------------

test("test_raycast_disc_exact_point", () => {
  // A ray hits a disc at the exact near-side entry point on its circumference (not the center
  // or the far side). Disc at x=100 r=20, ray along +x from origin -> enters at x=80.
  const world = new CollisionWorld();
  world.addDisc({ x: 100, y: 0 }, 20);
  const hit = world.castRay({ x: 0, y: 0 }, { x: 200, y: 0 });
  assert.notStrictEqual(hit, undefined);
  assert.deepStrictEqual(rp(hit!.point), { x: 80, y: 0 });
});

test("test_raycast_oval_exact_point", () => {
  // A ray hits an oval at its near-side entry, using the oval's x-radius. Oval at x=100 with
  // radiusX=30 -> the ray along +x enters at the left apex x=70 (=centerX-radiusX). The oval is
  // an ellipse approximated as a polygon, so the exact entry x depends on the (unspecified)
  // tessellation; accept any entry at/just inside the apex within the approximation error.
  const world = new CollisionWorld();
  world.addOval({ x: 100, y: 0 }, 30, 10);
  const hit = world.castRay({ x: 0, y: 0 }, { x: 200, y: 0 });
  assert.notStrictEqual(hit, undefined);
  assert.ok(Math.abs(hit!.point.x - 70) <= 2.5, `oval ray entry x=${hit!.point.x}, expected ~70`);
  assert.strictEqual(r(hit!.point.y), 0);
});

test("test_raycast_nearest_of_many", () => {
  // With several bodies along the ray, castRay returns the hit closest to the start and the
  // corresponding body — not a farther one.
  const world = new CollisionWorld();
  const near = world.addDisc({ x: 50, y: 0 }, 10);
  world.addDisc({ x: 150, y: 0 }, 10);
  const hit = world.castRay({ x: 0, y: 0 }, { x: 200, y: 0 });
  assert.notStrictEqual(hit, undefined);
  assert.deepStrictEqual(rp(hit!.point), { x: 40, y: 0 });
  assert.strictEqual(hit!.body, near);
});

test("test_contact_points_concave_box", () => {
  // A box crossing a concave (arrow-notch) polygon produces every distinct edge-intersection
  // point, deduplicated. The notch means the box edge crosses several polygon edges.
  const world = new CollisionWorld();
  const concave = world.addPoly({ x: 0, y: 0 }, [
    { x: 0, y: 0 },
    { x: 40, y: 0 },
    { x: 40, y: 40 },
    { x: 20, y: 20 },
    { x: 0, y: 40 },
  ]);
  const box = world.addRect({ x: 10, y: 15 }, 60, 10);
  // contactPoints returns the deduplicated SET of boundary intersection points; the emission
  // order is unspecified, so compare as an unordered set.
  const points = world.contactPoints(concave, box).map((p) => rp(p));
  assert.deepStrictEqual(sortPts(points), [
    { x: 15, y: 25 },
    { x: 25, y: 25 },
    { x: 40, y: 15 },
    { x: 40, y: 25 },
  ]);
});

test("test_push_apart_accumulates_between_walls", () => {
  // A dynamic body wedged between two symmetric static walls is pushed by the accumulated
  // minimum-translation vectors from BOTH overlaps; the equal-and-opposite pushes cancel, so
  // the body stays at its center. (A naive impl that resolves only the first overlap would
  // shove it off-center.)
  const world = new CollisionWorld();
  const player = world.addRect({ x: 0, y: 0 }, 20, 20);
  world.addRect({ x: 15, y: 0 }, 20, 20, { isStatic: true });
  world.addRect({ x: -15, y: 0 }, 20, 20, { isStatic: true });
  world.pushApart();
  world.update();
  assert.strictEqual(r(player.x), 0);
  assert.strictEqual(r(player.y), 0);
});

test("test_overlap_rotated_box", () => {
  // The response for a 45deg-rotated centered box overlapping an axis-aligned box reports the
  // exact penetration depth along the minimum-translation axis. The rotated box (half-diagonal
  // ~14.142) at origin vs an axis box centered at x=15 -> overlap along +x = 9.142136.
  const world = new CollisionWorld();
  const a = world.addRect({ x: 0, y: 0 }, 20, 20, { isCentered: true, angle: Math.PI / 4 });
  const b = world.addRect({ x: 15, y: 0 }, 20, 20, { isCentered: true });
  assert.strictEqual(world.overlaps(a, b), true);
  assert.strictEqual(r(world.response.overlap), 9.142136);
  assert.strictEqual(r(world.response.overlapN.x), 1);
  assert.strictEqual(r(world.response.overlapN.y), 0);
  assert.strictEqual(r(world.response.overlapV.x), 9.142136);
  assert.strictEqual(r(world.response.overlapV.y), 0);
});
