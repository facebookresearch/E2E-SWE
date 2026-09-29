# Implement `physkit`: a 2D rigid-body physics engine (Java)

Implement **physkit**, a 2D collision-detection and rigid-body physics engine, in three layers (all required):

1. **Geometry** — vectors, transforms, convex shapes with mass/inertia/AABB, plus hull, decomposition, and simplification.
2. **Collision** — narrow-phase (SAT, GJK/EPA) overlap-depth / separation / raycast, contact manifolds, continuous (swept) time-of-impact, and broad-phase.
3. **Dynamics** — rigid bodies, a world that simulates them under gravity with collision response over fixed steps, and joints.

Correctness follows physkit's own semantics (SAT/GJK collision, semi-implicit Euler integration, sequential-impulse solving). Tests use the **public API only** and are compiled against your classes, so the types, packages, and method signatures below must match **exactly**; numeric results are compared rounded to 6 decimals. You may organize internal/helper classes freely — only the named public members are relied on.

**Build:** put source under `/app/src` (package root `org/physkit/…` exactly as named); no external deps, no internet. `/app/setup.sh` compiles offline:
```bash
mkdir -p /app/out
find /app/src -name '*.java' -print0 | xargs -0 javac -d /app/out
```

---

## Layer 1 — Geometry (`org.physkit.geometry`)

**`Vector2`** — public `double` fields `x`, `y`; constructors `Vector2(double x, double y)`, `Vector2(Vector2)`:
```java
double  dot(Vector2 v)                 double  cross(Vector2 v)          Vector2 cross(double z)
double  getMagnitude()                 double  getMagnitudeSquared()
double  distance(Vector2 v)            double  getDirection()           // radians
double  getAngleBetween(Vector2 v)     Vector2 getNormalized()          double  normalize()
Vector2 project(Vector2 onto)          Vector2 rotate(double radians)   // in place, returns this
Vector2 copy()                         Vector2 lerp(Vector2 to, double t)
Vector2 getLeftHandOrthogonalVector()  Vector2 getRightHandOrthogonalVector()
Vector2 add(...), subtract(...), multiply(double), sum(...), difference(...)
static Vector2 tripleProduct(Vector2 a, Vector2 b, Vector2 c)
```
`getLeftHandOrthogonalVector()` returns `(y, -x)` (90° clockwise); `getRightHandOrthogonalVector()` returns `(-y, x)` (90° counter-clockwise).

**`Transform`** — `new Transform()` is identity; `getTransformed` rotates then translates, `getInverseTransformed` is its inverse:
```java
void    rotate(double radians)          void    translate(double x, double y)
Vector2 getTransformed(Vector2 v)       Vector2 getInverseTransformed(Vector2 v)
double  getRotationAngle()
```

**Shapes** — a `Shape` interface with a `Convex` sub-interface; `Shape` is **transformable** (a shape can be moved/rotated in place). Every convex shape provides:
```java
Mass    createMass(double density)      AABB createAABB(Transform tx)
double  getArea()  double getRadius()   Vector2 getCenter()
boolean contains(Vector2 point, Transform tx)
void    translate(double x, double y)   void translate(Vector2 v)   void rotate(double radians)   // in place
```
Concrete (all `org.physkit.geometry`), each centered at its local origin, with these public constructors (the tests instantiate them directly):
```java
Circle(double radius)                 Rectangle(double width, double height)   // a Polygon
Polygon(Vector2... vertices)          Segment(Vector2 p1, Vector2 p2)
Capsule(double width, double height)  Ellipse(double width, double height)
HalfEllipse(double width, double height)                Slice(double radius, double theta)
```
`Triangle` is a `Polygon` built via the `Geometry` factories below (not constructed directly by the tests). Vertex shapes implement **`Wound`** → `Vector2[] getVertices()`, `getNormals()`.

**`Mass` / `MassType`:**
```java
Mass(Vector2 center, double mass, double inertia)      static Mass create(List<Mass> masses)   // combine
double getMass()   double getInertia()   Vector2 getCenter()   MassType getType()   boolean isInfinite()
```
`MassType` is an enum: `NORMAL`; `INFINITE` (zero effective mass + inertia); `FIXED_LINEAR_VELOCITY`
(infinite / zero-inverse mass, finite inertia); `FIXED_ANGULAR_VELOCITY` (finite mass, infinite /
zero-inverse inertia). Whenever a type's linear or angular component is infinite, the matching `Mass`
accessor reports `0` as a sentinel — not the raw computed value and not `+Inf`: `getMass()` returns `0`
for `INFINITE` and `FIXED_LINEAR_VELOCITY`, and `getInertia()` returns `0` for `INFINITE` and
`FIXED_ANGULAR_VELOCITY`; otherwise each returns the real computed value.

**`AABB`:**
```java
AABB(double minX, double minY, double maxX, double maxY)
double  getWidth()  getHeight()  getMinX()  getMaxX()  getMinY()  getMaxY()  getArea()
Vector2 getCenter()   AABB getUnion(AABB o)   AABB getIntersection(AABB o)
boolean overlaps(AABB o)   boolean contains(AABB o)
```

**`Geometry`** — static factories that return the named shape type:
```java
Circle    createCircle(double radius)               Rectangle createRectangle(double w, double h)
Rectangle createSquare(double size)                 Triangle  createEquilateralTriangle(double height)
Triangle  createRightTriangle(double w, double h)
Segment   createVerticalSegment(double length)      Segment   createHorizontalSegment(double length)
Vector2   getAreaWeightedCenter(Vector2... points)
```
Also provide the rest of the factory surface (`createPolygon`, `createSlice`, `createCapsule`,
`createEllipse`, unit-circle / polygonal helpers, …).

`createRightTriangle(w, h)` places the right-angle corner at the local `(0, 0)` corner, with the two
legs along `+x` (length `w`) and `+y` (length `h`) — i.e. raw vertices `(0, h)`, `(0, 0)`, `(w, 0)` in
counter-clockwise winding — then translates the triangle so its centroid lies at the local origin.

**Convex hull (`…hull`)** — `HullGenerator.generate(Vector2... points)` → `Vector2[]` (the convex hull; interior and edge-collinear points excluded). No-arg impls **`GiftWrap`**, **`GrahamScan`**, **`DivideAndConquer`**, **`MonotoneChain`** all produce the same hull.

**Decomposition (`…decompose`)** — `Decomposer.decompose(Vector2... points)` → `List<Convex>` (a simple polygon → convex pieces, total area preserved; an **already-convex polygon is returned as a single piece**, so decompose is not merely a triangulation even for `EarClipping`/`SweepLine`); impls **`Bayazit`**, **`EarClipping`**, **`SweepLine`**. `Triangulator.triangulate(Vector2... points)` → `List<Triangle>` (exactly `n−2` triangles); impls **`EarClipping`**, **`SweepLine`**. Inputs may be mutated; winding is auto-normalized.

**Simplification (`…simplify`)** — `List<Vector2> simplify(List<Vector2>)` and `Vector2[] simplify(Vector2...)` (the varargs overload returns an **array**, the `List` overload returns a `List`) remove redundant vertices. Impls: **`VertexClusterReduction(double clusterTolerance)`**, **`DouglasPeucker(double clusterTolerance, double epsilon)`**, **`Visvalingam(double clusterTolerance, double minTriangleArea)`** (DP/Vis run cluster reduction first, then their own algorithm).

---

## Layer 2 — Collision (`org.physkit.collision.*`)

**Narrow-phase (`…narrowphase`)** — mutable result carriers, each with a no-arg constructor: `Penetration` (`getDepth()`, `getNormal()`); `Separation` (`getDistance()`, `getNormal()`, `getPoint1()`, `getPoint2()`); `Raycast` (`getDistance()`, `getPoint()`, `getNormal()`); `Containment` (`isAContainedInB()`, `isBContainedInA()`). `Sat` and `Gjk` implement `NarrowphaseDetector`:
```java
class Sat { boolean detect(Convex a, Transform ta, Convex b, Transform tb, Penetration p);
            boolean detect(Convex a, Transform ta, Convex b, Transform tb); }
class Gjk { boolean detect(Convex a, Transform ta, Convex b, Transform tb, Penetration p);   // EPA depth
            boolean detect(Convex a, Transform ta, Convex b, Transform tb);
            boolean distance(Convex a, Transform ta, Convex b, Transform tb, Separation s);   // false if overlapping
            boolean raycast(Ray ray, double maxLength, Convex c, Transform tc, Raycast r); }  // maxLength 0 = unbounded
```
`detect(…,Penetration)` → true + minimum-translation depth/normal on overlap; `distance(…,Separation)` → true + closest distance/normal/points when separate. **The normal points from A to B.** Static specialized detectors:
```java
class CircleDetector {
  static boolean detect(Circle a, Transform ta, Circle b, Transform tb, Penetration p);
  static boolean distance(Circle a, Transform ta, Circle b, Transform tb, Separation s);
  static boolean contains(Circle a, Transform ta, Circle b, Transform tb, Containment c);
  static boolean raycast(Ray ray, double maxLength, Circle c, Transform tc, Raycast r); }
class SegmentDetector {
  static boolean raycast(Ray ray, double maxLength, Segment s, Transform ts, Raycast r); }
```
`Ray` = `new Ray(Vector2 start, Vector2 direction)` (`org.physkit.geometry.Ray`).

**Manifolds (`…manifold`)** — given a `Penetration`, the solver fills the contact manifold (1–2 points + shared normal):
```java
class Manifold      { List<ManifoldPoint> getPoints();  Vector2 getNormal(); }
class ManifoldPoint { Vector2 getPoint();  double getDepth(); }
class ClippingManifoldSolver {
  boolean getManifold(Penetration p, Convex a, Transform ta, Convex b, Transform tb, Manifold m); }
```

**Continuous / time-of-impact (`…continuous`)** — returns true + TOI in `[0,1]` if the swept shapes (moving by linear `dp`/angular `da` over the step) collide before the step ends:
```java
class TimeOfImpact { double getTime(); /* toi in [0,1] */ }
class ConservativeAdvancement {
  boolean getTimeOfImpact(Convex a, Transform ta, Vector2 dpA, double daA,
                          Convex b, Transform tb, Vector2 dpB, double daB, TimeOfImpact toi); }
```

**Broad-phase (`…broadphase`)** — `BroadphaseDetector<T>` finds candidate collision pairs; all three
impls return the same pair set for a given layout. The support types **`BroadphaseFilter<T>`,
`AABBProducer<T>`, and `AABBExpansionMethod<T>` are generic over the item type `T`**.
```java
// implementations, all BroadphaseDetector<T>:
DynamicAABBTree<T>(BroadphaseFilter<T> filter, AABBProducer<T> producer, AABBExpansionMethod<T> expansion)
Sap<T>(BroadphaseFilter<T> filter, AABBProducer<T> producer, AABBExpansionMethod<T> expansion)
BruteForceBroadphase<T>(BroadphaseFilter<T> filter, AABBProducer<T> producer)      // no expansion method
// methods on BroadphaseDetector<T>:
void add(T)   void remove(T)   int size()   AABB getAABB(T)   boolean detect(T a, T b)
List<CollisionPair<T>> detect()                 // all overlapping pairs; CollisionPair<T> has getFirst()/getSecond()
List<T> detect(AABB region)   List<T> raycast(Ray ray, double length)
```
Concrete support impls: `CollisionItemBroadphaseFilter<>`, `CollisionItemAABBProducer<>`,
`NullAABBExpansionMethod<>`. Items are `CollisionItem<Body,BodyFixture>`, created via
`new BasicCollisionItem<>(body, fixture)`; parameterize the detector over that item type. Items are
**value objects** — two `BasicCollisionItem`s wrapping the same body and fixture are `equals` and
hash alike — so every item-taking method above accepts a freshly constructed equivalent item, not
only the exact instance passed to `add`.

---

## Layer 3 — Dynamics (`org.physkit.dynamics`, `…joint`, `org.physkit.world`)

**`Body` / `BodyFixture`** — `Body` implements a `PhysicsBody` interface (the world and joints are generic over it):
```java
Body()
BodyFixture addFixture(Convex shape)      BodyFixture addFixture(Convex shape, double density)
BodyFixture getFixture(int index)         int getFixtureCount()   List<BodyFixture> getFixtures()
void    setMass(MassType type)            Mass getMass()      // computes mass/inertia from fixtures
void    translate(double x, double y)      Transform getTransform()   Vector2 getWorldCenter()
void    applyForce(Vector2 f)             void applyForce(Vector2 f, Vector2 point)  // point -> torque
void    applyTorque(double torque)        void applyImpulse(Vector2 j)   void applyImpulse(double angularJ)
Vector2 getAccumulatedForce()             double  getAccumulatedTorque()
Vector2 getLinearVelocity()               void setLinearVelocity(Vector2 v)
double  getAngularVelocity()              void setAngularVelocity(double w)
void    setUserData(Object)               Object getUserData()
```
`applyImpulse` changes velocity immediately (`dv = J/m`, `dω = J/I`); `applyForce`/`applyTorque` accumulate and integrate during a step. `BodyFixture`: `Convex getShape()`, `void setRestitution(double)` (0 = inelastic, 1 = fully elastic).

**`World<T extends PhysicsBody>`:**
```java
World()                                   // default gravity EARTH_GRAVITY (0, -9.8)
static final Vector2 ZERO_GRAVITY         static final Vector2 EARTH_GRAVITY
void    setGravity(Vector2 g)             Vector2 getGravity()
void    addBody(T body)                   int getBodyCount()      List<T> getBodies()
void    addJoint(Joint<T> joint)
void    step(int count, double elapsedTime)   // advance `count` fixed steps of `elapsedTime` s
```
`step` integrates forces (semi-implicit Euler), detects collisions, solves contacts + joints, integrates velocities — deterministic for fixed inputs/`dt`. It must reproduce: free fall (`v = g·t`), a body resting on a static (`INFINITE`) floor with restitution 0, elastic bounce with restitution 1, momentum conservation in collisions, and persistent spin (no angular damping).

**Joints (`…joint`)** — generic over the body type, added via `world.addJoint(...)`; each enforces its constraint every step. Every `Joint<T>` exposes its two constrained bodies:
```java
T getBody(int index)   // index 0 or 1; throws InvalidIndexException for any other index
T getBody1()   T getBody2()
```
```java
DistanceJoint<T>(T b1, T b2, Vector2 anchor1, Vector2 anchor2)   // fixed rest distance
    Vector2 getAnchor1();  Vector2 getAnchor2();  double getRestDistance();
RevoluteJoint<T>(T b1, T b2, Vector2 anchor)   // anchors stay coincident, free rotation
    Vector2 getAnchor1();  Vector2 getAnchor2();
WeldJoint<T>(T b1, T b2, Vector2 anchor)       // coincident anchors + fixed relative angle
    Vector2 getAnchor1();  Vector2 getAnchor2();
PrismaticJoint<T>(T b1, T b2, Vector2 anchor, Vector2 axis)   // motion constrained to `axis`
PinJoint<T>(T body, Vector2 target)            Vector2 getTarget();   // spring pulls body toward target
AngleJoint<T>(T b1, T b2)                       double getRatio();     // default 1.0
    // couples the bodies' rotations: b2 angular motion = ratio * b1's, so ratio 1.0 keeps their relative angle fixed
```

**World listeners (package `org.physkit.world.listener`)** — each is an interface with a no-op `*Adapter` base class (`StepListenerAdapter<T>`, `CollisionListenerAdapter<T,E>`, `ContactListenerAdapter<T>`). The callbacks receive **`PhysicsWorld<T extends PhysicsBody, V extends ContactCollisionData<T>>`** — note **two** type parameters (`World<T>` implements it).

**Package note (these are easy to misplace):** `TimeStep` is in **`org.physkit.dynamics`**; `CollisionData<T,E>` and its subtypes (`BroadphaseCollisionData`/`NarrowphaseCollisionData`/`ManifoldCollisionData`) and `ContactCollisionData<T>` are all in **`org.physkit.world`**.

- **`StepListener<T>`** — `begin`/`updatePerformed`/`postSolve`/`end`, each `(TimeStep, PhysicsWorld<T,?>)`; `begin`/`end` fire once per fixed simulation step, so one `step(count, elapsedTime)` call fires each of them `count` times.
- **`CollisionListener<T,E>`** — one `boolean collision(...)` overload **per stage**, taking the stage's collision-data carrier: `collision(BroadphaseCollisionData<T,E>)`, `collision(NarrowphaseCollisionData<T,E>)`, `collision(ManifoldCollisionData<T,E>)` (subtypes of `CollisionData<T,E>`).
- **`ContactListener<T>`** — `void begin(ContactCollisionData<T>, Contact)`, `void end(ContactCollisionData<T>, Contact)`, `void persist(ContactCollisionData<T>, Contact, Contact)`, `void collision(ContactCollisionData<T>)` — where `Contact` is **`org.physkit.dynamics.contact.Contact`**.
- **`BoundsListener<T,E>`** — `outside(T)`; enable via `World.setBounds(new AxisAlignedBounds(w, h))`, where **`AxisAlignedBounds` lives in `org.physkit.collision`**.
- **`DestructionListener<T>`**.

Register/query with `addStepListener`/`addCollisionListener`/`addContactListener`/`addBoundsListener(...)`; the matching **`boolean remove…Listener(...)`** return `true` if a listener was removed; `getStepListeners()`/`getCollisionListeners()`/`getContactListeners()`/`getBoundsListeners()` each return a `List`.

**World spatial queries (result types in package `org.physkit.world.result`)** — via `AbstractCollisionWorld`, each taking a `DetectFilter<Body,BodyFixture>` (e.g. `new DetectFilter<>(false, false, null)`). `ConvexDetectResult`, `RaycastResult`, and `ConvexCastResult` all **extend `DetectResult<T,E>`** (so all expose `getBody()`/`getFixture()`):
```java
List<DetectResult<Body,BodyFixture>> detect(AABB, DetectFilter)
List<DetectResult<Body,BodyFixture>> detect(AABB, Body body, DetectFilter)   // single-body: restrict to one body's fixtures
List<ConvexDetectResult<…>>          detect(Convex, Transform, DetectFilter)   // getPenetration()
List<RaycastResult<…>>               raycast(Ray, double maxLength, DetectFilter)
RaycastResult<…>                     raycastClosest(Ray, double, DetectFilter)  // null on miss; Comparable by distance;
                                                                                // getBody()/getFixture()/getRaycast()
List<ConvexCastResult<…>>            convexCast(Convex, Transform, Vector2 dp, double da, DetectFilter)
ConvexCastResult<…>                  convexCastClosest(...)          // null on miss; getTimeOfImpact().getTime()
```

**Validation exceptions (`org.physkit.exception`)** — public constructors / factories throw:
- **`ValueOutOfRangeException`** (extends `IllegalArgumentException`) — non-positive shape dimensions, negative mass or inertia, or a polygon with < 3 vertices.
- **`ArgumentNullException`** (extends `NullPointerException`) — a required argument is null.
- **`SameObjectException`** — a paired two-body joint is constructed with the same body as both of its two bodies.
- **`ObjectAlreadyExistsException`** / **`ObjectAlreadyOwnedException`** — a `Body` belongs to at most one `World` at a time: `World.addBody` throws `ObjectAlreadyExistsException` if the body is already in this world, and `ObjectAlreadyOwnedException` if it is already owned by another world.
- **`EmptyCollectionException`** — `Mass.create` is passed an empty list (combining zero masses is invalid, not an identity).
- **`NullElementException`** — a required collection/array argument is itself non-null but contains a `null` *element*.
- **`InvalidIndexException`** — an index argument is outside its valid range (e.g. a joint body index other than 0 or 1).
- Degenerate / collinear polygons and zero-length segments throw plain `IllegalArgumentException`.

---

**Scope:** the complete library — every subsystem above (`geometry` incl. `hull`/`decompose`/`simplify`; `collision` incl. `broadphase`/`narrowphase`/`manifold`/`continuous`; `dynamics` + `world` incl. joints, listeners, queries). Only the named public types/signatures are tested; internal layout is your choice.
