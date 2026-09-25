import XCTest
import Euclid

/// Tests for Euclid's geometry + CSG, graded on **implementation-independent semantic properties** —
/// volume, point containment, watertightness, bounds, emptiness — never on tessellation-specific
/// details like polygon counts. Any correct implementation must satisfy these regardless of internal
/// representation.
final class EuclidTests: XCTestCase {
    private let eps = 1e-6

    // MARK: Vector (bundled — one node)

    func testVectorArithmetic() {
        XCTAssertEqual(Vector(1, 2, 2).length, 3.0, accuracy: eps)
        XCTAssertEqual(Vector(1, 0, 0).dot(Vector(1, 1, 0)), 1.0, accuracy: eps)
        XCTAssertEqual(Vector(1, 0, 0).cross(Vector(0, 1, 0)), Vector(0, 0, 1))
        let n = Vector(0, 3, 4).normalized()
        XCTAssertEqual(n, Vector(0, 0.6, 0.8))
        XCTAssertEqual(n.length, 1.0, accuracy: eps)
    }

    // MARK: Primitive shapes

    func testCube() {
        let c = Mesh.cube()
        XCTAssertEqual(c.bounds, Bounds(min: Vector(-0.5, -0.5, -0.5), max: Vector(0.5, 0.5, 0.5)))
        XCTAssertEqual(c.volume, 1.0, accuracy: eps)
        XCTAssertTrue(c.isWatertight)
        XCTAssertTrue(c.containsPoint(Vector(0, 0, 0)))
        XCTAssertFalse(c.containsPoint(Vector(1, 0, 0)))
    }

    func testRoundPrimitivesAreUnitWatertightSolids() {
        for m in [Mesh.sphere(), Mesh.cylinder(), Mesh.cone()] {
            XCTAssertEqual(m.bounds, Bounds(min: Vector(-0.5, -0.5, -0.5), max: Vector(0.5, 0.5, 0.5)))
            XCTAssertTrue(m.isWatertight)
            XCTAssertTrue(m.containsPoint(Vector(0, 0, 0)))
        }
        // Corner-exclusion checks so a unit cube cannot masquerade as a round/tapered solid.
        XCTAssertFalse(Mesh.sphere().containsPoint(Vector(0.49, 0.49, 0.49)))  // cube corner outside sphere
        XCTAssertFalse(Mesh.cylinder().containsPoint(Vector(0.49, 0, 0.49)))   // radial ~0.69 outside the Y-axis cylinder
        XCTAssertFalse(Mesh.cone().containsPoint(Vector(0.4, 0.4, 0)))         // near the +Y apex the taper radius is ~0.05
    }

    // MARK: Transforms

    func testTranslateAndScale() {
        let t = Mesh.cube().translated(by: Vector(1, 0, 0))
        XCTAssertEqual(t.bounds, Bounds(min: Vector(0.5, -0.5, -0.5), max: Vector(1.5, 0.5, 0.5)))
        XCTAssertEqual(t.volume, 1.0, accuracy: eps)
        let s = Mesh.cube().scaled(by: 2)
        XCTAssertEqual(s.bounds, Bounds(min: Vector(-1, -1, -1), max: Vector(1, 1, 1)))
        XCTAssertEqual(s.volume, 8.0, accuracy: eps)
    }

    func testRotatePreservesVolumeAndExpandsBounds() {
        let r = Mesh.cube().rotated(by: Rotation(axis: Vector(0, 0, 1), angle: .degrees(45))!)
        XCTAssertEqual(r.volume, 1.0, accuracy: eps)
        XCTAssertEqual(r.bounds.max.x, 0.5 * 2.squareRoot(), accuracy: 1e-4)
        XCTAssertEqual(r.bounds.max.z, 0.5, accuracy: eps)
        XCTAssertTrue(r.containsPoint(Vector(0, 0, 0)))
    }

    // MARK: CSG booleans on cubes (exact volume + containment)

    func testUnionOverlapping() {
        let u = Mesh.cube().union(Mesh.cube().translated(by: Vector(0.5, 0, 0)))
        XCTAssertEqual(u.volume, 1.5, accuracy: eps)
        XCTAssertEqual(u.bounds, Bounds(min: Vector(-0.5, -0.5, -0.5), max: Vector(1.0, 0.5, 0.5)))
        XCTAssertTrue(u.isWatertight)
        XCTAssertTrue(u.containsPoint(Vector(-0.25, 0, 0)))
        XCTAssertTrue(u.containsPoint(Vector(0.75, 0, 0)))
        XCTAssertFalse(u.containsPoint(Vector(1.25, 0, 0)))
    }

    func testIntersectionOverlapping() {
        let i = Mesh.cube().intersection(Mesh.cube().translated(by: Vector(0.5, 0, 0)))
        XCTAssertEqual(i.volume, 0.5, accuracy: eps)
        XCTAssertEqual(i.bounds, Bounds(min: Vector(0, -0.5, -0.5), max: Vector(0.5, 0.5, 0.5)))
        XCTAssertTrue(i.isWatertight)
        XCTAssertTrue(i.containsPoint(Vector(0.25, 0, 0)))
        XCTAssertFalse(i.containsPoint(Vector(0.75, 0, 0)))
        XCTAssertFalse(i.containsPoint(Vector(-0.25, 0, 0)))
    }

    func testSubtractOverlapping() {
        let s = Mesh.cube().subtracting(Mesh.cube().translated(by: Vector(0.5, 0, 0)))
        XCTAssertEqual(s.volume, 0.5, accuracy: eps)
        XCTAssertEqual(s.bounds, Bounds(min: Vector(-0.5, -0.5, -0.5), max: Vector(0, 0.5, 0.5)))
        XCTAssertTrue(s.isWatertight)
        XCTAssertTrue(s.containsPoint(Vector(-0.25, 0, 0)))
        XCTAssertFalse(s.containsPoint(Vector(0.25, 0, 0)))
    }

    func testSymmetricDifferenceOverlapping() {
        let x = Mesh.cube().symmetricDifference(Mesh.cube().translated(by: Vector(0.5, 0, 0)))
        XCTAssertEqual(x.volume, 1.0, accuracy: eps)
        XCTAssertTrue(x.isWatertight)
        XCTAssertTrue(x.containsPoint(Vector(-0.25, 0, 0)))
        XCTAssertTrue(x.containsPoint(Vector(0.75, 0, 0)))
        XCTAssertFalse(x.containsPoint(Vector(0.25, 0, 0)))
    }

    func testSubtractIdenticalIsEmpty() {
        let s = Mesh.cube().subtracting(Mesh.cube())
        XCTAssertTrue(s.polygons.isEmpty)
        XCTAssertEqual(s.volume, 0.0, accuracy: eps)
    }

    func testIntersectionDisjointIsEmpty() {
        XCTAssertTrue(Mesh.cube().intersection(Mesh.cube().translated(by: Vector(2, 0, 0))).polygons.isEmpty)
    }

    func testUnionDisjoint() {
        let u = Mesh.cube().union(Mesh.cube().translated(by: Vector(2, 0, 0)))
        XCTAssertEqual(u.volume, 2.0, accuracy: eps)
        XCTAssertTrue(u.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(u.containsPoint(Vector(2, 0, 0)))
        XCTAssertFalse(u.containsPoint(Vector(1, 0, 0)))
    }

    // MARK: Compositions

    func testHollowShellBySubtraction() {
        let m = Mesh.cube().subtracting(Mesh.cube().scaled(by: 0.5))
        XCTAssertEqual(m.volume, 0.875, accuracy: eps)
        XCTAssertFalse(m.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.4, 0.4, 0.4)))
        XCTAssertTrue(m.isWatertight)
    }

    func testChainedUnionOfThreeDisjointCubes() {
        let m = Mesh.cube()
            .union(Mesh.cube().translated(by: Vector(2, 0, 0)))
            .union(Mesh.cube().translated(by: Vector(4, 0, 0)))
        XCTAssertEqual(m.volume, 3.0, accuracy: eps)
        XCTAssertTrue(m.isWatertight)
        XCTAssertTrue(m.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(2, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(4, 0, 0)))
        XCTAssertFalse(m.containsPoint(Vector(1, 0, 0)))
    }

    // MARK: Curved-shape CSG (containment; multiple sample points to avoid lucky passes)

    func testCubeMinusSphereContainment() {
        let cs = Mesh.cube().subtracting(Mesh.sphere())
        XCTAssertFalse(cs.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(cs.containsPoint(Vector(0.49, 0.49, 0.49)))
        XCTAssertTrue(cs.containsPoint(Vector(0.49, 0.49, -0.49)))
        XCTAssertFalse(cs.containsPoint(Vector(0, 0, 0.3)))   // still inside the sphere
        XCTAssertTrue(cs.isWatertight)
    }

    func testSphereIntersectCubeContainment() {
        let sc = Mesh.sphere().intersection(Mesh.cube())
        XCTAssertTrue(sc.isWatertight)
        XCTAssertTrue(sc.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(sc.containsPoint(Vector(0, 0, 0.3)))
        XCTAssertFalse(sc.containsPoint(Vector(0.49, 0.49, 0.49)))
    }

    func testSphereUnionCubeContainment() {
        let m = Mesh.sphere().union(Mesh.cube().translated(by: Vector(0.5, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.9, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.9, 0.4, 0.4)))   // corner of shifted cube
        XCTAssertFalse(m.containsPoint(Vector(1.2, 0, 0)))
        XCTAssertFalse(m.containsPoint(Vector(-0.49, 0.49, 0))) // outside sphere, left of cube
    }

    func testTwoSpheresUnionContainment() {
        let m = Mesh.sphere().union(Mesh.sphere().translated(by: Vector(0.5, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(-0.2, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.7, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.25, 0, 0)))
        XCTAssertFalse(m.containsPoint(Vector(1.1, 0, 0)))
    }

    func testSphereMinusCylinderContainment() {
        let m = Mesh.sphere().subtracting(Mesh.cylinder().scaled(by: 0.5))
        XCTAssertTrue(m.isWatertight)
        XCTAssertFalse(m.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.4, 0, 0)))
        XCTAssertFalse(m.containsPoint(Vector(0.1, 0.1, 0)))   // still inside the drilled column
    }

    // MARK: Building meshes from paths

    func testExtrudeSquareIsUnitBox() {
        let m = Mesh.extrude(Path.square())
        XCTAssertEqual(m.volume, 1.0, accuracy: eps)
        XCTAssertEqual(m.bounds, Bounds(min: Vector(-0.5, -0.5, -0.5), max: Vector(0.5, 0.5, 0.5)))
        XCTAssertTrue(m.isWatertight)
        XCTAssertTrue(m.containsPoint(Vector(0, 0, 0)))
    }

    func testLatheIsWatertightSolid() {
        let m = Mesh.lathe(Path([.point(0, -0.5), .point(0.5, -0.5), .point(0.5, 0.5), .point(0, 0.5)]))
        XCTAssertTrue(m.isWatertight)
        XCTAssertEqual(m.bounds, Bounds(min: Vector(-0.5, -0.5, -0.5), max: Vector(0.5, 0.5, 0.5)))
        // Revolving the rectangle around Y yields a radius-0.5 solid of revolution, not a box.
        XCTAssertTrue(m.containsPoint(Vector(0.4, 0, 0)))       // radial 0.4 < 0.5: inside
        XCTAssertFalse(m.containsPoint(Vector(0.4, 0, 0.4)))    // radial ~0.57 > 0.5: AABB corner, outside
    }

    func testLoftBetweenSquares() {
        let m = Mesh.loft([Path.square(), Path.square().translated(by: Vector(0, 0, 1))])
        XCTAssertTrue(m.isWatertight)
        XCTAssertEqual(m.volume, 1.0, accuracy: eps)
        XCTAssertEqual(m.bounds, Bounds(min: Vector(-0.5, -0.5, 0), max: Vector(0.5, 0.5, 1)))
    }

    // MARK: Other mesh operations

    func testTriangulatePreservesGeometry() {
        let m = Mesh.cube().triangulate()
        XCTAssertEqual(m.volume, 1.0, accuracy: eps)
        XCTAssertTrue(m.isWatertight)
        XCTAssertTrue(m.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(m.polygons.allSatisfy { $0.vertices.count == 3 })  // a no-op triangulate must fail
    }

    func testInvertedFlipsInside() {
        let m = Mesh.cube().inverted()
        XCTAssertFalse(m.containsPoint(Vector(0, 0, 0)))   // the cube's interior is no longer "inside"
        XCTAssertTrue(m.isWatertight)
    }

    func testClippedToPlaneKeepsHalf() {
        let m = Mesh.cube().clipped(to: Plane(normal: Vector(1, 0, 0), pointOnPlane: Vector(0, 0, 0))!)
        XCTAssertEqual(m.bounds, Bounds(min: Vector(0, -0.5, -0.5), max: Vector(0.5, 0.5, 0.5)))
        XCTAssertFalse(m.containsPoint(Vector(-0.25, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.25, 0, 0)))
    }

    // MARK: Bounds

    func testBoundsOperations() {
        let a = Bounds(min: Vector(0, 0, 0), max: Vector(1, 1, 1))
        let b = Bounds(min: Vector(0.5, 0.5, 0.5), max: Vector(2, 2, 2))
        XCTAssertEqual(a.union(b), Bounds(min: Vector(0, 0, 0), max: Vector(2, 2, 2)))
        XCTAssertEqual(a.intersection(b), Bounds(min: Vector(0.5, 0.5, 0.5), max: Vector(1, 1, 1)))
        XCTAssertEqual(a.center, Vector(0.5, 0.5, 0.5))
        XCTAssertEqual(a.size, Vector(1, 1, 1))
    }

    // MARK: More curved-shape CSG (distinct shape-pair scenarios; containment with mixed points)

    func testConeIntersectSphereContainment() {
        let m = Mesh.cone().intersection(Mesh.sphere())
        XCTAssertTrue(m.containsPoint(Vector(0, -0.3, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0, -0.4, 0)))
        XCTAssertFalse(m.containsPoint(Vector(0.4, 0, 0)))      // outside the cone taper (taper radius 0.25 at y=0)
    }

    func testConeMinusSphereContainment() {
        let m = Mesh.cone().subtracting(Mesh.sphere())
        XCTAssertFalse(m.containsPoint(Vector(0, -0.4, 0)))     // on-axis, carved by sphere
        XCTAssertFalse(m.containsPoint(Vector(0, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.35, -0.45, 0)))  // cone base, outside the sphere
    }

    func testCylinderMinusSphereContainment() {
        let m = Mesh.cylinder().subtracting(Mesh.sphere())
        XCTAssertTrue(m.containsPoint(Vector(0.35, 0.45, 0)))   // cylinder near top cap, outside the sphere
        XCTAssertFalse(m.containsPoint(Vector(0, 0, 0)))        // carved out by the sphere
    }

    func testTwoSpheresIntersectionContainment() {
        let m = Mesh.sphere().intersection(Mesh.sphere().translated(by: Vector(0.5, 0, 0)))
        XCTAssertTrue(m.containsPoint(Vector(0.25, 0, 0)))      // lens overlap
        XCTAssertFalse(m.containsPoint(Vector(-0.2, 0, 0)))     // only in sphere A
        XCTAssertFalse(m.containsPoint(Vector(0.7, 0, 0)))      // only in sphere B
    }

    func testConeUnionCylinderContainment() {
        let m = Mesh.cone().union(Mesh.cylinder().translated(by: Vector(0, 0, 0.6)))
        XCTAssertTrue(m.containsPoint(Vector(0, -0.3, 0)))      // in cone
        XCTAssertTrue(m.containsPoint(Vector(0, 0, 0.7)))       // in shifted cylinder
        XCTAssertFalse(m.containsPoint(Vector(0.4, 0.4, 0)))    // outside both
    }

    func testHollowSphereShellContainment() {
        let m = Mesh.sphere().subtracting(Mesh.sphere().scaled(by: 0.6))
        XCTAssertTrue(m.isWatertight)
        XCTAssertFalse(m.containsPoint(Vector(0, 0, 0)))        // inner cavity
        XCTAssertTrue(m.containsPoint(Vector(0.45, 0, 0)))      // shell
        XCTAssertFalse(m.containsPoint(Vector(0.2, 0, 0)))      // still in inner cavity
    }
}
