// Hidden test suite for the Clipper2 C# WRG task (Clipper2 v2.0.1, tag Clipper2_2.0.1).
//
// Drives the public Clipper2Lib API the way a real user would: build Paths64/PathsD with MakePath,
// run a boolean / offset / rect-clip / simplify operation or a geometry utility, and assert the
// resulting geometry. Expected outputs were captured from the genuine library.
//
// Fairness note on polygon comparison: a clipping engine's exact *starting vertex* and the *order of
// the returned paths* are sweep-algorithm artifacts, not part of the geometric result. So polygon
// outputs are compared with Check.PathsEq, which is invariant to (a) cyclic rotation of each closed
// ring's start vertex and (b) the order of rings within the result — but NOT to vertex coordinates,
// ring membership, or orientation (outer vs hole). Order-preserving operations (Simplify, RDP,
// TrimCollinear, Ellipse, Translate, RectClipLines) and open-path results keep their exact sequence.

using Clipper2Lib;

public static class Tests
{
    // ---- construction helpers ----
    private static Path64 M(params long[] xy) => Clipper.MakePath(xy);
    private static PathD MD(params double[] xy) => Clipper.MakePath(xy);
    private static Paths64 PS(params Path64[] ps) { Paths64 r = new Paths64(); r.AddRange(ps); return r; }
    private static PathsD PSD(params PathD[] ps) { PathsD r = new PathsD(); r.AddRange(ps); return r; }
    private static Paths64 E() => new Paths64();

    private static Paths64 Subj() => PS(M(0, 0, 100, 0, 100, 100, 0, 100));
    private static Paths64 Clip() => PS(M(50, 50, 150, 50, 150, 150, 50, 150));
    private static Paths64 L() => PS(M(0, 0, 100, 0, 100, 40, 40, 40, 40, 100, 0, 100));
    private static Paths64 U() => PS(M(0, 0, 100, 0, 100, 100, 70, 100, 70, 30, 30, 30, 30, 100, 0, 100));
    private static Paths64 Plus() => PS(M(40, 0, 60, 0, 60, 40, 100, 40, 100, 60, 60, 60, 60, 100, 40, 100, 40, 60, 0, 60, 0, 40, 40, 40));
    private static Paths64 Diamond() => PS(M(50, 0, 100, 50, 50, 100, 0, 50));
    private static Paths64 Staircase() => PS(M(0, 0, 60, 0, 60, 20, 40, 20, 40, 40, 20, 40, 20, 60, 0, 60));

    // -----------------------------------------------------------------------
    // Boolean operations
    // -----------------------------------------------------------------------
    public static void Test_union_two_squares() =>
        Check.PathsEq(Clipper.Union(Subj(), Clip(), FillRule.NonZero),
            PS(M(100, 50, 150, 50, 150, 150, 50, 150, 50, 100, 0, 100, 0, 0, 100, 0)));

    public static void Test_intersect_two_squares() =>
        Check.PathsEq(Clipper.Intersect(Subj(), Clip(), FillRule.NonZero),
            PS(M(100, 100, 50, 100, 50, 50, 100, 50)));

    public static void Test_difference_two_squares() =>
        Check.PathsEq(Clipper.Difference(Subj(), Clip(), FillRule.NonZero),
            PS(M(100, 50, 50, 50, 50, 100, 0, 100, 0, 0, 100, 0)));

    public static void Test_xor_two_squares() =>
        Check.PathsEq(Clipper.Xor(Subj(), Clip(), FillRule.NonZero),
            PS(M(150, 150, 50, 150, 50, 100, 100, 100, 100, 50, 150, 50),
               M(100, 50, 50, 50, 50, 100, 0, 100, 0, 0, 100, 0)));

    // -----------------------------------------------------------------------
    // Fill rules — the same geometry yields different fills
    // -----------------------------------------------------------------------
    public static void Test_fillrule_ring_same_orientation()
    {
        Paths64 ring = PS(M(0, 0, 100, 0, 100, 100, 0, 100), M(25, 25, 75, 25, 75, 75, 25, 75));
        Check.PathsEq(Clipper.Union(ring, E(), FillRule.EvenOdd),
            PS(M(100, 100, 0, 100, 0, 0, 100, 0), M(25, 25, 25, 75, 75, 75, 75, 25)));
        Check.PathsEq(Clipper.Union(ring, E(), FillRule.NonZero),
            PS(M(100, 100, 0, 100, 0, 0, 100, 0)));
    }

    public static void Test_fillrule_ring_reversed_inner()
    {
        Paths64 ring = PS(M(0, 0, 100, 0, 100, 100, 0, 100), M(25, 25, 25, 75, 75, 75, 75, 25));
        Paths64 donut = PS(M(100, 100, 0, 100, 0, 0, 100, 0), M(25, 75, 75, 75, 75, 25, 25, 25));
        Check.PathsEq(Clipper.Union(ring, E(), FillRule.NonZero), donut);
        Check.PathsEq(Clipper.Union(ring, E(), FillRule.Positive), donut);
        Check.PathsEq(Clipper.Union(ring, E(), FillRule.Negative), E());
    }

    public static void Test_fillrule_self_intersecting_bowtie()
    {
        Paths64 bow = PS(M(0, 0, 100, 100, 100, 0, 0, 100));
        Check.PathsEq(Clipper.Union(bow, E(), FillRule.EvenOdd),
            PS(M(50, 50, 0, 100, 0, 0), M(100, 100, 50, 50, 100, 0)));
    }

    // -----------------------------------------------------------------------
    // Offsetting (InflatePaths) — join types and shrink (closed polygons)
    // -----------------------------------------------------------------------
    public static void Test_inflate_miter() =>
        Check.PathsEq(Clipper.InflatePaths(PS(M(0, 0, 100, 0, 100, 100, 0, 100)), 10, JoinType.Miter, EndType.Polygon),
            PS(M(110, 110, -10, 110, -10, -10, 110, -10)));

    public static void Test_inflate_bevel_join() =>
        Check.PathsEq(Clipper.InflatePaths(PS(M(0, 0, 100, 0, 100, 100, 0, 100)), 10, JoinType.Bevel, EndType.Polygon),
            PS(M(110, 0, 110, 100, 100, 110, 0, 110, -10, 100, -10, 0, 0, -10, 100, -10)));

    public static void Test_shrink_polygon() =>
        Check.PathsEq(Clipper.InflatePaths(PS(M(0, 0, 100, 0, 100, 100, 0, 100)), -10, JoinType.Miter, EndType.Polygon),
            PS(M(90, 10, 90, 90, 10, 90, 10, 10)));

    public static void Test_offset_open_line_end_types()
    {
        Paths64 line = PS(M(0, 0, 100, 0));
        Check.PathsEq(Clipper.InflatePaths(line, 10, JoinType.Miter, EndType.Butt),
            PS(M(100, 10, 0, 10, 0, -10, 100, -10)));
        Check.PathsEq(Clipper.InflatePaths(line, 10, JoinType.Miter, EndType.Square),
            PS(M(110, 10, -10, 10, -10, -10, 110, -10)));
        Check.PathsEq(Clipper.InflatePaths(line, 10, JoinType.Miter, EndType.Joined),
            PS(M(110, 10, -10, 10, -10, -10, 110, -10)));
    }

    // -----------------------------------------------------------------------
    // Rectangular clipping
    // -----------------------------------------------------------------------
    public static void Test_rectclip()
    {
        Check.PathsEq(Clipper.RectClip(new Rect64(20, 20, 80, 80), Subj()),
            PS(M(20, 80, 20, 20, 80, 20, 80, 80)));
        Check.PathsEq(Clipper.RectClip(new Rect64(50, 50, 200, 200), Subj()),
            PS(M(50, 50, 100, 50, 100, 100, 50, 100)));
    }

    public static void Test_rectcliplines() =>
        Check.PathsEqExact(Clipper.RectClipLines(new Rect64(20, 20, 80, 80), PS(M(0, 40, 100, 40))),
            PS(M(20, 40, 80, 40)));

    // -----------------------------------------------------------------------
    // Simplification (order-preserving -> exact)
    // -----------------------------------------------------------------------
    public static void Test_simplify_paths() =>
        Check.PathsEqExact(Clipper.SimplifyPaths(PS(M(0, 0, 10, 1, 20, 0, 30, 1, 100, 0, 100, 100, 0, 100)), 5.0),
            PS(M(0, 0, 100, 0, 100, 100, 0, 100)));

    public static void Test_ramer_douglas_peucker() =>
        Check.PathEq(Clipper.RamerDouglasPeucker(M(0, 0, 10, 1, 20, 0, 30, 1, 100, 0), 5.0),
            M(0, 0, 100, 0));

    public static void Test_trim_collinear() =>
        Check.PathEq(Clipper.TrimCollinear(M(0, 0, 50, 0, 100, 0, 100, 100, 0, 100)),
            M(0, 0, 100, 0, 100, 100, 0, 100));

    // -----------------------------------------------------------------------
    // Geometry utilities
    // -----------------------------------------------------------------------
    public static void Test_area_signed_by_orientation()
    {
        Check.Equal(Clipper.Area(M(0, 0, 100, 0, 100, 100, 0, 100)), 10000.0);
        Check.Equal(Clipper.Area(M(0, 0, 0, 100, 100, 100, 100, 0)), -10000.0);
    }

    public static void Test_is_positive_orientation()
    {
        Check.True(Clipper.IsPositive(M(0, 0, 100, 0, 100, 100, 0, 100)), "ccw positive");
        Check.True(!Clipper.IsPositive(M(0, 0, 0, 100, 100, 100, 100, 0)), "cw not positive");
    }

    public static void Test_point_in_polygon()
    {
        Path64 poly = M(0, 0, 100, 0, 100, 100, 0, 100);
        Check.True(Clipper.PointInPolygon(new Point64(50, 50), poly) == PointInPolygonResult.IsInside, "inside");
        Check.True(Clipper.PointInPolygon(new Point64(150, 50), poly) == PointInPolygonResult.IsOutside, "outside");
        Check.True(Clipper.PointInPolygon(new Point64(0, 50), poly) == PointInPolygonResult.IsOn, "on edge");
    }

    public static void Test_ellipse() =>
        Check.PathEq(Clipper.Ellipse(new Point64(0, 0), 20.0, 20.0, 8),
            M(20, 0, 14, 14, 0, 20, -14, 14, -20, 0, -14, -14, 0, -20, 14, -14));

    public static void Test_translate_path() =>
        Check.PathEq(Clipper.TranslatePath(M(0, 0, 10, 0, 10, 10), 5, 7),
            M(5, 7, 15, 7, 15, 17));

    // -----------------------------------------------------------------------
    // Double-precision API
    // -----------------------------------------------------------------------
    public static void Test_intersect_double_precision()
    {
        PathsD Ad = PSD(MD(0.0, 0.0, 10.5, 0.0, 10.5, 10.5, 0.0, 10.5));
        PathsD Bd = PSD(MD(5.25, 5.25, 15.0, 5.25, 15.0, 15.0, 5.25, 15.0));
        Check.PathsEqD(Clipper.Intersect(Ad, Bd, FillRule.NonZero, 2),
            PSD(MD(10.5, 10.5, 5.25, 10.5, 5.25, 5.25, 10.5, 5.25)));
    }

    // -----------------------------------------------------------------------
    // PolyTree hole nesting
    // -----------------------------------------------------------------------
    public static void Test_polytree_hole_nesting()
    {
        Paths64 ring = PS(M(0, 0, 100, 0, 100, 100, 0, 100), M(25, 25, 75, 25, 75, 75, 25, 75));
        PolyTree64 tree = new PolyTree64();
        Clipper64 c = new Clipper64();
        c.AddSubject(ring);
        c.Execute(ClipType.Union, FillRule.EvenOdd, tree);
        Check.Equal(tree.Count, 1);
        PolyPath64 outer = tree[0];
        Check.True(!outer.IsHole, "outer not hole");
        Check.Equal(outer.Count, 1);
        Check.True(outer.Child(0).IsHole, "child is hole");
    }

    // =======================================================================
    // Hardening batch — harder, non-trivial inputs across the same fair surfaces.
    // =======================================================================

    // ---- Boolean (harder) ----
    public static void Test_diff_square_minus_center()
    {
        Paths64 big = PS(M(0, 0, 200, 0, 200, 200, 0, 200));
        Paths64 inner = PS(M(50, 50, 150, 50, 150, 150, 50, 150));
        Check.PathsEq(Clipper.Difference(big, inner, FillRule.NonZero),
            PS(M(200, 200, 0, 200, 0, 0, 200, 0), M(50, 50, 50, 150, 150, 150, 150, 50)));
    }

    public static void Test_diff_square_two_holes()
    {
        Paths64 big = PS(M(0, 0, 200, 0, 200, 200, 0, 200));
        Paths64 holes = PS(M(25, 25, 75, 25, 75, 75, 25, 75), M(125, 125, 175, 125, 175, 175, 125, 175));
        Check.PathsEq(Clipper.Difference(big, holes, FillRule.NonZero),
            PS(M(200, 200, 0, 200, 0, 0, 200, 0),
               M(125, 125, 125, 175, 175, 175, 175, 125),
               M(25, 25, 25, 75, 75, 75, 75, 25)));
    }

    public static void Test_intersect_L_square() =>
        Check.PathsEq(Clipper.Intersect(L(), PS(M(20, 20, 120, 20, 120, 120, 20, 120)), FillRule.NonZero),
            PS(M(100, 40, 40, 40, 40, 100, 20, 100, 20, 20, 100, 20)));

    public static void Test_union_L_shapes()
    {
        Paths64 L2 = PS(M(0, 0, 40, 0, 40, 100, 100, 100, 100, 60, 0, 60));
        Check.PathsEq(Clipper.Union(L(), L2, FillRule.NonZero),
            PS(M(100, 40, 40, 40, 40, 60, 100, 60, 100, 100, 40, 100, 0, 100, 0, 0, 100, 0)));
    }

    public static void Test_xor_offset_rects() =>
        Check.PathsEq(Clipper.Xor(PS(M(0, 0, 100, 0, 100, 60, 0, 60)),
                                  PS(M(40, 30, 140, 30, 140, 90, 40, 90)), FillRule.NonZero),
            PS(M(140, 90, 40, 90, 40, 60, 100, 60, 100, 30, 140, 30),
               M(100, 30, 40, 30, 40, 60, 0, 60, 0, 0, 100, 0)));

    public static void Test_intersect_two_triangles() =>
        Check.PathsEq(Clipper.Intersect(PS(M(0, 0, 100, 0, 50, 80)),
                                        PS(M(0, 40, 100, 40, 50, 120)), FillRule.NonZero),
            PS(M(50, 80, 25, 40, 75, 40)));

    public static void Test_union_three_squares()
    {
        Paths64 three = PS(M(0, 0, 60, 0, 60, 60, 0, 60), M(40, 0, 100, 0, 100, 60, 40, 60),
                           M(80, 0, 140, 0, 140, 60, 80, 60));
        Check.PathsEq(Clipper.Union(three, E(), FillRule.NonZero),
            PS(M(60, 0, 100, 0, 140, 0, 140, 60, 80, 60, 40, 60, 0, 60, 0, 0)));
    }

    public static void Test_diff_plus_minus_square() =>
        Check.PathsEq(Clipper.Difference(Plus(), PS(M(0, 0, 50, 0, 50, 50, 0, 50)), FillRule.NonZero),
            PS(M(60, 40, 100, 40, 100, 60, 60, 60, 60, 100, 40, 100, 40, 60, 0, 60, 0, 50, 50, 50, 50, 0, 60, 0)));

    public static void Test_intersect_plus_square() =>
        Check.PathsEq(Clipper.Intersect(Plus(), PS(M(30, 30, 100, 30, 100, 100, 30, 100)), FillRule.NonZero),
            PS(M(60, 40, 100, 40, 100, 60, 60, 60, 60, 100, 40, 100, 40, 60, 30, 60, 30, 40, 40, 40, 40, 30, 60, 30)));

    public static void Test_union_touching_squares()
    {
        Paths64 t = PS(M(0, 0, 50, 0, 50, 50, 0, 50), M(50, 0, 100, 0, 100, 50, 50, 50));
        Check.PathsEq(Clipper.Union(t, E(), FillRule.NonZero),
            PS(M(50, 0, 100, 0, 100, 50, 50, 50, 0, 50, 0, 0)));
    }

    // ---- Fill rules (harder) ----
    public static void Test_nested3_fillrules()
    {
        Paths64 n = PS(M(0, 0, 120, 0, 120, 120, 0, 120), M(20, 20, 100, 20, 100, 100, 20, 100),
                       M(40, 40, 80, 40, 80, 80, 40, 80));
        Check.PathsEq(Clipper.Union(n, E(), FillRule.EvenOdd),
            PS(M(120, 120, 0, 120, 0, 0, 120, 0),
               M(20, 20, 20, 100, 100, 100, 100, 20),
               M(80, 80, 40, 80, 40, 40, 80, 40)));
        Check.PathsEq(Clipper.Union(n, E(), FillRule.NonZero),
            PS(M(120, 120, 0, 120, 0, 0, 120, 0)));
    }

    public static void Test_rect_two_holes_evenodd()
    {
        Paths64 p = PS(M(0, 0, 200, 0, 200, 100, 0, 100), M(20, 20, 20, 80, 60, 80, 60, 20),
                       M(120, 20, 120, 80, 160, 80, 160, 20));
        Check.PathsEq(Clipper.Union(p, E(), FillRule.EvenOdd),
            PS(M(200, 100, 0, 100, 0, 0, 200, 0),
               M(20, 80, 60, 80, 60, 20, 20, 20),
               M(120, 80, 160, 80, 160, 20, 120, 20)));
    }

    public static void Test_overlapping_rings_evenodd()
    {
        Paths64 p = PS(M(0, 0, 100, 0, 100, 100, 0, 100), M(50, 0, 150, 0, 150, 100, 50, 100),
                       M(25, 25, 75, 25, 75, 75, 25, 75));
        Check.PathsEq(Clipper.Union(p, E(), FillRule.EvenOdd),
            PS(M(50, 0, 50, 25, 25, 25, 25, 75, 50, 75, 50, 100, 0, 100, 0, 0),
               M(150, 100, 100, 100, 100, 0, 150, 0),
               M(75, 75, 50, 75, 50, 25, 75, 25)));
    }

    public static void Test_double_bowtie_evenodd() =>
        Check.PathsEq(Clipper.Union(PS(M(0, 0, 100, 40, 100, 0, 0, 40)), E(), FillRule.EvenOdd),
            PS(M(50, 20, 0, 40, 0, 0), M(100, 40, 50, 20, 100, 0)));

    public static void Test_concave_self_touch_nonzero() =>
        Check.PathsEq(Clipper.Union(PS(M(0, 0, 100, 0, 100, 100, 50, 50, 0, 100)), E(), FillRule.NonZero),
            PS(M(100, 100, 50, 50, 0, 100, 0, 0, 100, 0)));

    // ---- Offsetting (harder; miter/bevel only) ----
    public static void Test_inflate_L_miter() =>
        Check.PathsEq(Clipper.InflatePaths(L(), 10, JoinType.Miter, EndType.Polygon),
            PS(M(110, 50, 50, 50, 50, 110, -10, 110, -10, -10, 110, -10)));

    public static void Test_inflate_triangle_miter() =>
        Check.PathsEq(Clipper.InflatePaths(PS(M(0, 0, 100, 0, 50, 80)), 10, JoinType.Miter, EndType.Polygon, 10.0),
            PS(M(50, 99, -18, -10, 118, -10)));

    public static void Test_shrink_L_miter() =>
        Check.PathsEq(Clipper.InflatePaths(L(), -10, JoinType.Miter, EndType.Polygon),
            PS(M(90, 10, 90, 30, 30, 30, 30, 90, 10, 90, 10, 10)));

    public static void Test_inflate_U_bevel() =>
        Check.PathsEq(Clipper.InflatePaths(U(), 10, JoinType.Bevel, EndType.Polygon),
            PS(M(110, 0, 110, 100, 100, 110, 70, 110, 60, 100, 60, 40, 40, 40, 40, 100, 30, 110, 0, 110, -10, 100, -10, 0, 0, -10, 100, -10)));

    public static void Test_inflate_plus_miter() =>
        Check.PathsEq(Clipper.InflatePaths(Plus(), 10, JoinType.Miter, EndType.Polygon),
            PS(M(70, 30, 110, 30, 110, 70, 70, 70, 70, 110, 30, 110, 30, 70, -10, 70, -10, 30, 30, 30, 30, -10, 70, -10)));

    public static void Test_shrink_dumbbell_splits() =>
        Check.PathsEq(Clipper.InflatePaths(PS(M(0, 0, 100, 0, 100, 40, 55, 40, 55, 20, 45, 20, 45, 40, 0, 40)),
                                           -8, JoinType.Miter, EndType.Polygon),
            PS(M(92, 8, 92, 32, 63, 32, 63, 12, 37, 12, 37, 32, 8, 32, 8, 8)));

    public static void Test_inflate_two_squares()
    {
        Paths64 two = PS(M(0, 0, 40, 0, 40, 40, 0, 40), M(100, 100, 140, 100, 140, 140, 100, 140));
        Check.PathsEq(Clipper.InflatePaths(two, 10, JoinType.Miter, EndType.Polygon),
            PS(M(150, 150, 90, 150, 90, 90, 150, 90), M(50, 50, -10, 50, -10, -10, 50, -10)));
    }

    // ---- RectClip (harder) ----
    public static void Test_rectclip_L() =>
        Check.PathsEq(Clipper.RectClip(new Rect64(20, 20, 80, 80), L()),
            PS(M(80, 20, 80, 40, 40, 40, 40, 80, 20, 80, 20, 20)));

    public static void Test_rectclip_U() =>
        Check.PathsEq(Clipper.RectClip(new Rect64(0, 0, 100, 60), U()),
            PS(M(30, 60, 0, 60, 0, 0, 100, 0, 100, 60, 70, 60, 70, 30, 30, 30)));

    public static void Test_rectcliplines_zigzag() =>
        Check.PathsEqExact(Clipper.RectClipLines(new Rect64(20, 20, 80, 80), PS(M(0, 50, 40, 0, 60, 100, 100, 50))),
            PS(M(20, 25, 24, 20), M(44, 20, 56, 80), M(76, 80, 80, 75)));

    public static void Test_rectclip_two_polygons()
    {
        Paths64 two = PS(M(0, 0, 60, 0, 60, 60, 0, 60), M(120, 120, 200, 120, 200, 200, 120, 200));
        Check.PathsEq(Clipper.RectClip(new Rect64(30, 30, 170, 170), two),
            PS(M(30, 30, 60, 30, 60, 60, 30, 60), M(170, 170, 120, 170, 120, 120, 170, 120)));
    }

    // ---- PolyTree (harder) ----
    public static void Test_polytree_deep_nesting()
    {
        Paths64 nest = PS(M(0, 0, 300, 0, 300, 300, 0, 300), M(50, 50, 250, 50, 250, 250, 50, 250),
                          M(100, 100, 200, 100, 200, 200, 100, 200));
        PolyTree64 tree = new PolyTree64();
        Clipper64 c = new Clipper64();
        c.AddSubject(nest);
        c.Execute(ClipType.Union, FillRule.EvenOdd, tree);
        Check.Equal(tree.Count, 1);
        PolyPath64 l0 = tree[0];
        Check.True(!l0.IsHole, "l0 not hole");
        Check.Equal(l0.Count, 1);
        PolyPath64 l1 = l0.Child(0);
        Check.True(l1.IsHole, "l1 hole");
        Check.Equal(l1.Count, 1);
        Check.True(!l1.Child(0).IsHole, "l2 solid island");
    }

    public static void Test_polytree_two_top_level()
    {
        Paths64 p = PS(M(0, 0, 80, 0, 80, 80, 0, 80), M(20, 20, 60, 20, 60, 60, 20, 60),
                       M(200, 0, 280, 0, 280, 80, 200, 80), M(220, 20, 260, 20, 260, 60, 220, 60));
        PolyTree64 tree = new PolyTree64();
        Clipper64 c = new Clipper64();
        c.AddSubject(p);
        c.Execute(ClipType.Union, FillRule.EvenOdd, tree);
        Check.Equal(tree.Count, 2);
        for (int i = 0; i < tree.Count; i++)
        {
            Check.True(!tree[i].IsHole, "top-level not hole");
            Check.Equal(tree[i].Count, 1, "each top-level has one hole");
        }
    }

    // =======================================================================
    // Hardening batch 2 — diamonds, staircases, multi-piece splits, deeper nesting.
    // =======================================================================
    public static void Test_xor_square_offset_diamond() =>
        Check.PathsEq(Clipper.Xor(PS(M(0, 0, 100, 0, 100, 100, 0, 100)),
                                  PS(M(100, 0, 150, 50, 100, 100, 50, 50)), FillRule.NonZero),
            PS(M(100, 0, 50, 50, 100, 100, 0, 100, 0, 0), M(150, 50, 100, 100, 100, 0)));

    public static void Test_diff_staircase_minus_square() =>
        Check.PathsEq(Clipper.Difference(Staircase(), PS(M(30, 0, 60, 0, 60, 60, 30, 60)), FillRule.NonZero),
            PS(M(30, 0, 30, 40, 20, 40, 20, 60, 0, 60, 0, 0)));

    public static void Test_diff_donut_minus_square()
    {
        Paths64 donut = PS(M(0, 0, 200, 0, 200, 200, 0, 200), M(50, 50, 50, 150, 150, 150, 150, 50));
        Check.PathsEq(Clipper.Difference(donut, PS(M(100, 100, 180, 100, 180, 180, 100, 180)), FillRule.NonZero),
            PS(M(200, 200, 0, 200, 0, 0, 200, 0),
               M(50, 150, 100, 150, 100, 180, 180, 180, 180, 100, 150, 100, 150, 50, 50, 50)));
    }

    public static void Test_intersect_two_Ls()
    {
        Paths64 L2 = PS(M(0, 0, 40, 0, 40, 100, 100, 100, 100, 60, 0, 60));
        Check.PathsEq(Clipper.Intersect(L(), L2, FillRule.NonZero),
            PS(M(40, 40, 40, 60, 0, 60, 0, 0, 40, 0)));
    }

    public static void Test_nested4_evenodd()
    {
        Paths64 n = PS(M(0, 0, 160, 0, 160, 160, 0, 160), M(20, 20, 140, 20, 140, 140, 20, 140),
                       M(40, 40, 120, 40, 120, 120, 40, 120), M(60, 60, 100, 60, 100, 100, 60, 100));
        Check.PathsEq(Clipper.Union(n, E(), FillRule.EvenOdd),
            PS(M(160, 160, 0, 160, 0, 0, 160, 0),
               M(20, 20, 20, 140, 140, 140, 140, 20),
               M(120, 120, 40, 120, 40, 40, 120, 40),
               M(60, 60, 60, 100, 100, 100, 100, 60)));
    }

    public static void Test_inflate_diamond_miter() =>
        Check.PathsEq(Clipper.InflatePaths(Diamond(), 10, JoinType.Miter, EndType.Polygon),
            PS(M(114, 50, 50, 114, -14, 50, 50, -14)));

    public static void Test_inflate_staircase_miter() =>
        Check.PathsEq(Clipper.InflatePaths(Staircase(), 8, JoinType.Miter, EndType.Polygon),
            PS(M(68, 28, 48, 28, 48, 48, 28, 48, 28, 68, -8, 68, -8, -8, 68, -8)));

    public static void Test_rectclip_U_splits_into_two() =>
        Check.PathsEq(Clipper.RectClip(new Rect64(0, 40, 100, 100), U()),
            PS(M(30, 40, 30, 100, 0, 100, 0, 40), M(100, 40, 100, 100, 70, 100, 70, 40)));

    public static void Test_rectclip_diamond() =>
        Check.PathsEq(Clipper.RectClip(new Rect64(25, 25, 75, 75), Diamond()),
            PS(M(75, 75, 25, 75, 25, 25, 75, 25)));

    public static void Test_union_two_diamonds() =>
        Check.PathsEq(Clipper.Union(Diamond(), PS(M(100, 50, 150, 100, 100, 150, 50, 100)), FillRule.NonZero),
            PS(M(100, 50, 150, 100, 100, 150, 50, 100, 0, 50, 50, 0)));

    public static void Test_diff_square_minus_diamond() =>
        Check.PathsEq(Clipper.Difference(PS(M(0, 0, 100, 0, 100, 100, 0, 100)), PS(M(50, 20, 80, 50, 50, 80, 20, 50)), FillRule.NonZero),
            PS(M(100, 100, 0, 100, 0, 0, 100, 0), M(20, 50, 50, 80, 80, 50, 50, 20)));

    // =======================================================================
    // Minkowski sum / difference (exact — well-defined output, canonical comparison like boolean ops)
    // =======================================================================
    public static void Test_minkowski_sum_square() =>
        Check.PathsEq(Clipper.MinkowskiSum(M(-10, -10, 10, -10, 10, 10, -10, 10),
                                           M(0, 0, 100, 0, 100, 100, 0, 100), true),
            PS(M(10, -10, 90, -10, 110, -10, 110, 10, 110, 110, 90, 110, 10, 110, -10, 110, -10, 90, -10, 10, -10, -10),
               M(10, 90, 90, 90, 90, 10, 10, 10)));

    public static void Test_minkowski_sum_triangle() =>
        Check.PathsEq(Clipper.MinkowskiSum(M(0, 0, 30, 0, 0, 20), M(0, 0, 100, 0, 100, 100, 0, 100), true),
            PS(M(100, 0, 130, 0, 130, 100, 100, 120, 0, 120, 0, 100, 0, 20, 0, 0),
               M(100, 20, 30, 20, 30, 100, 100, 100)));

    public static void Test_minkowski_diff() =>
        Check.PathsEq(Clipper.MinkowskiDiff(M(0, 0, 30, 0, 0, 20), M(0, 0, 100, 0, 100, 100, 0, 100), true),
            PS(M(100, -20, 100, 0, 100, 100, 70, 100, 0, 100, -30, 100, -30, 0, 0, -20),
               M(0, 80, 70, 80, 70, 0, 0, 0)));

    public static void Test_minkowski_sum_open_line() =>
        Check.PathsEq(Clipper.MinkowskiSum(M(-10, -10, 10, -10, 10, 10, -10, 10), M(0, 0, 100, 0), false),
            PS(M(90, -10, 110, -10, 110, 10, 10, 10, -10, 10, -10, -10)));

    // =======================================================================
    // Triangulation (invariant-based — any valid triangulation is acceptable; see Check.Triangulation)
    // =======================================================================
    public static void Test_triangulate_pentagon()
    {
        Paths64 poly = PS(M(0, 0, 100, 0, 120, 60, 50, 100, -20, 60));
        Paths64 sol;
        TriangulateResult r = Clipper.Triangulate(poly, out sol, true);
        Check.True(r == TriangulateResult.success, "triangulate success");
        Check.Triangulation(poly, sol, 5);
    }

    public static void Test_triangulate_L_shape()
    {
        Paths64 poly = L();
        Paths64 sol;
        TriangulateResult r = Clipper.Triangulate(poly, out sol, true);
        Check.True(r == TriangulateResult.success, "triangulate success");
        Check.Triangulation(poly, sol, 6);
    }

    public static void Test_triangulate_plus()
    {
        Paths64 poly = Plus();
        Paths64 sol;
        TriangulateResult r = Clipper.Triangulate(poly, out sol, true);
        Check.True(r == TriangulateResult.success, "triangulate success");
        Check.Triangulation(poly, sol, 12);
    }
}
