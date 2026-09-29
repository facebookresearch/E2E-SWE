// Self-contained CTRF-emitting test harness for the Clipper2 C# WRG task — hidden, grader-only.
//
// The candidate never sees this file. It discovers every public static parameterless method whose
// name starts with "Test_" on the `Tests` class, runs each, catches assertion failures, and writes
// the CTRF report the WRG grader reads (results.summary.{passed,failed,...} + results.tests[]).
// No external test framework (xunit/nunit) is needed — the grader compiles this together with the
// candidate's Clipper2Lib sources and the hidden test methods.

using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using Clipper2Lib;

// Thrown by the Check.* assertion helpers; carries a human-readable failure message into the CTRF.
public class AssertFail : Exception
{
    public AssertFail(string m) : base(m) { }
}

// Assertion + geometry-comparison helpers used by the hidden tests.
public static class Check
{
    public static void True(bool cond, string what)
    {
        if (!cond) throw new AssertFail("EXPECT_TRUE failed: " + what);
    }

    public static void Equal(long a, long b, string what = "")
    {
        if (a != b) throw new AssertFail($"EXPECT_EQ failed: {a} == {b} {what}");
    }

    public static void Equal(double a, double b, string what = "")
    {
        if (Math.Abs(a - b) > 1e-9) throw new AssertFail($"EXPECT_EQ failed: {a} == {b} {what}");
    }

    // ---- exact (order-preserving) comparisons: for results whose vertex/path order is meaningful
    // (SimplifyPaths, RamerDouglasPeucker, TrimCollinear, Ellipse, TranslatePath, RectClipLines) ----
    public static void PathEq(Path64 got, Path64 want)
    {
        if (!SamePath(got, want))
            throw new AssertFail("Path64 mismatch:\n  got  " + Str(got) + "\n  want " + Str(want));
    }

    public static void PathsEqExact(Paths64 got, Paths64 want)
    {
        if (got.Count != want.Count || !got.Zip(want, SamePath).All(x => x))
            throw new AssertFail("Paths64 (ordered) mismatch:\n  got  " + Strs(got) + "\n  want " + Strs(want));
    }

    // ---- canonical comparison: a clipping engine's per-ring starting vertex and the order of the
    // returned rings are sweep-algorithm artifacts, not part of the geometric result. So polygon
    // results are compared invariant to (a) cyclic rotation of each closed ring and (b) ring order,
    // but NOT to coordinates, ring membership, vertex count, or orientation. ----
    public static void PathsEq(Paths64 got, Paths64 want)
    {
        if (!SamePaths(Canon(got), Canon(want)))
            throw new AssertFail("Paths64 (canonical) mismatch:\n  got  " + Strs(got) + "\n  want " + Strs(want));
    }

    public static void PathsEqD(PathsD got, PathsD want)
    {
        if (!SamePathsD(CanonD(got), CanonD(want)))
            throw new AssertFail("PathsD (canonical) mismatch:\n  got  " + StrsD(got) + "\n  want " + StrsD(want));
    }

    // ---- triangulation invariants: a simple polygon admits many valid triangulations, so we assert the
    // universal invariants of ANY correct triangulation (n-2 triangles, each a non-degenerate triangle
    // whose 3 vertices are polygon vertices, partitioning the polygon by area) — not a specific set. ----
    public static void Triangulation(Paths64 poly, Paths64 tris, int n)
    {
        Check.Equal(tris.Count, n - 2, "triangle count = n-2");
        double polyArea = 0, triArea = 0;
        HashSet<(long, long)> pv = new HashSet<(long, long)>();
        foreach (Path64 p in poly)
        {
            polyArea += Math.Abs(Clipper.Area(p));
            foreach (Point64 q in p) pv.Add((q.X, q.Y));
        }
        foreach (Path64 t in tris)
        {
            Check.Equal(t.Count, 3, "triangle has 3 vertices");
            double a = Math.Abs(Clipper.Area(t));
            Check.True(a > 0.5, "triangle non-degenerate");
            triArea += a;
            foreach (Point64 q in t) Check.True(pv.Contains((q.X, q.Y)), "triangle vertex is a polygon vertex");
        }
        Check.True(Math.Abs(polyArea - triArea) < 1e-6, "triangles partition the polygon (area)");
    }

    // ---------- internals ----------
    private static bool SamePath(Path64 a, Path64 b)
    {
        if (a.Count != b.Count) return false;
        for (int i = 0; i < a.Count; i++)
            if (a[i].X != b[i].X || a[i].Y != b[i].Y) return false;
        return true;
    }

    private static bool SamePaths(Paths64 a, Paths64 b)
    {
        if (a.Count != b.Count) return false;
        for (int i = 0; i < a.Count; i++)
            if (!SamePath(a[i], b[i])) return false;
        return true;
    }

    // Drop vertices that are exactly collinear with their neighbours — a redundant collinear point does
    // not change the polygon's geometry, and different ports/algorithms (e.g. C++ vs C# Minkowski) emit
    // them differently, so they are not part of the geometric result.
    private static Path64 StripCollinear(Path64 p)
    {
        Path64 r = new Path64(p);
        bool changed = true;
        while (changed && r.Count > 3)
        {
            changed = false;
            for (int i = 0; i < r.Count; i++)
            {
                Point64 a = r[(i - 1 + r.Count) % r.Count], b = r[i], c = r[(i + 1) % r.Count];
                if ((b.X - a.X) * (c.Y - a.Y) - (b.Y - a.Y) * (c.X - a.X) == 0) { r.RemoveAt(i); changed = true; break; }
            }
        }
        return r;
    }

    private static Path64 CanonRing(Path64 p)
    {
        Path64 s = StripCollinear(p);
        if (s.Count < 2) return s;
        int mi = 0;
        for (int i = 1; i < s.Count; i++)
            if (s[i].X < s[mi].X || (s[i].X == s[mi].X && s[i].Y < s[mi].Y)) mi = i;
        Path64 r = new Path64();
        for (int i = 0; i < s.Count; i++) r.Add(s[(mi + i) % s.Count]);
        return r;
    }

    private static Paths64 Canon(Paths64 ps)
    {
        Paths64 outp = new Paths64();
        foreach (Path64 p in ps) outp.Add(CanonRing(p));
        outp.Sort((a, b) =>
        {
            if (a.Count != b.Count) return a.Count - b.Count;
            for (int i = 0; i < a.Count; i++)
            {
                if (a[i].X != b[i].X) return a[i].X < b[i].X ? -1 : 1;
                if (a[i].Y != b[i].Y) return a[i].Y < b[i].Y ? -1 : 1;
            }
            return 0;
        });
        return outp;
    }

    private static bool SamePathD(PathD a, PathD b)
    {
        if (a.Count != b.Count) return false;
        for (int i = 0; i < a.Count; i++)
            if (Math.Abs(a[i].x - b[i].x) > 1e-6 || Math.Abs(a[i].y - b[i].y) > 1e-6) return false;
        return true;
    }

    private static bool SamePathsD(PathsD a, PathsD b)
    {
        if (a.Count != b.Count) return false;
        for (int i = 0; i < a.Count; i++)
            if (!SamePathD(a[i], b[i])) return false;
        return true;
    }

    private static PathD CanonRingD(PathD p)
    {
        if (p.Count < 2) return new PathD(p);
        int mi = 0;
        for (int i = 1; i < p.Count; i++)
            if (p[i].x < p[mi].x || (p[i].x == p[mi].x && p[i].y < p[mi].y)) mi = i;
        PathD r = new PathD();
        for (int i = 0; i < p.Count; i++) r.Add(p[(mi + i) % p.Count]);
        return r;
    }

    private static PathsD CanonD(PathsD ps)
    {
        PathsD outp = new PathsD();
        foreach (PathD p in ps) outp.Add(CanonRingD(p));
        outp.Sort((a, b) =>
        {
            if (a.Count != b.Count) return a.Count - b.Count;
            for (int i = 0; i < a.Count; i++)
            {
                if (a[i].x != b[i].x) return a[i].x < b[i].x ? -1 : 1;
                if (a[i].y != b[i].y) return a[i].y < b[i].y ? -1 : 1;
            }
            return 0;
        });
        return outp;
    }

    private static string Str(Path64 p) => "[" + string.Join(" ", p.Select(pt => $"({pt.X},{pt.Y})")) + "]";
    private static string Strs(Paths64 ps) => "{" + string.Join(" ", ps.Select(Str)) + "}";
    private static string StrD(PathD p) => "[" + string.Join(" ", p.Select(pt => $"({pt.x},{pt.y})")) + "]";
    private static string StrsD(PathsD ps) => "{" + string.Join(" ", ps.Select(StrD)) + "}";
}

// Discovers and runs the hidden tests, then writes /logs/verifier/ctrf.json (or $CTRF_OUT).
public static class CtrfRunner
{
    public static int Main()
    {
        List<MethodInfo> methods = typeof(Tests)
            .GetMethods(BindingFlags.Public | BindingFlags.Static)
            .Where(m => m.Name.StartsWith("Test_") && m.GetParameters().Length == 0)
            .OrderBy(m => m.Name)
            .ToList();

        int passed = 0, failed = 0;
        StringBuilder tests = new StringBuilder();
        bool first = true;
        foreach (MethodInfo m in methods)
        {
            string status = "passed", msg = "";
            try
            {
                m.Invoke(null, null);
                passed++;
            }
            catch (TargetInvocationException tie)
            {
                status = "failed";
                failed++;
                msg = tie.InnerException != null ? tie.InnerException.Message : tie.Message;
            }
            catch (Exception e)
            {
                status = "failed";
                failed++;
                msg = e.Message;
            }
            if (!first) tests.Append(",");
            first = false;
            tests.Append("{\"name\":\"" + Esc(m.Name) + "\",\"status\":\"" + status
                         + "\",\"message\":\"" + Esc(msg) + "\"}");
        }

        string outJson = "{\"results\":{\"tool\":{\"name\":\"ctrf_test\"},\"summary\":{\"tests\":"
            + (passed + failed) + ",\"passed\":" + passed + ",\"failed\":" + failed
            + ",\"pending\":0,\"skipped\":0,\"other\":0},\"tests\":[" + tests + "]}}";

        string path = Environment.GetEnvironmentVariable("CTRF_OUT");
        if (string.IsNullOrEmpty(path)) path = "/logs/verifier/ctrf.json";
        Directory.CreateDirectory(Path.GetDirectoryName(path));
        File.WriteAllText(path, outJson);
        Console.WriteLine($"passed={passed} failed={failed}");
        return failed == 0 ? 0 : 1;
    }

    private static string Esc(string s)
    {
        StringBuilder o = new StringBuilder();
        foreach (char c in s)
        {
            if (c == '"' || c == '\\') o.Append('\\');
            if (c == '\n') { o.Append("\\n"); continue; }
            if (c == '\r') continue;
            o.Append(c);
        }
        return o.ToString();
    }
}
