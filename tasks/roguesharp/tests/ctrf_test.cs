using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;

public class AssertFail : Exception
{
    public AssertFail(string m) : base(m) { }
}

public static class Check
{
    public static void True(bool cond, string what = "")
    {
        if (!cond) throw new AssertFail("EXPECT_TRUE failed: " + what);
    }

    public static void False(bool cond, string what = "")
    {
        if (cond) throw new AssertFail("EXPECT_FALSE failed: " + what);
    }

    public static void Equal<T>(T a, T b, string what = "")
    {
        if (!EqualityComparer<T>.Default.Equals(a, b))
            throw new AssertFail($"EXPECT_EQ failed: got {a}, want {b}. {what}");
    }

    public static void NotNull(object obj, string what = "")
    {
        if (obj == null) throw new AssertFail("EXPECT_NOT_NULL failed: " + what);
    }

    public static void Null(object obj, string what = "")
    {
        if (obj != null) throw new AssertFail("EXPECT_NULL failed: " + what);
    }

    public static void Throws<T>(Action action, string what = "") where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        catch (Exception ex) { throw new AssertFail($"EXPECT_THROWS<{typeof(T).Name}> got {ex.GetType().Name}: {what}"); }
        throw new AssertFail($"EXPECT_THROWS<{typeof(T).Name}> but no exception thrown: {what}");
    }

    public static void InRange(double val, double lo, double hi, string what = "")
    {
        if (val < lo || val > hi)
            throw new AssertFail($"EXPECT_IN_RANGE failed: {val} not in [{lo}, {hi}]. {what}");
    }

    public static void GreaterThan(int a, int b, string what = "")
    {
        if (a <= b) throw new AssertFail($"EXPECT_GT failed: {a} <= {b}. {what}");
    }
}

public class CtrfRunner
{
    public static int Main()
    {
        string outPath = Environment.GetEnvironmentVariable("CTRF_OUT") ?? "/logs/verifier/ctrf.json";
        string dir = Path.GetDirectoryName(outPath);
        if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

        var methods = typeof(Tests)
            .GetMethods(BindingFlags.Public | BindingFlags.Static)
            .Where(m => m.Name.StartsWith("Test_") && m.GetParameters().Length == 0)
            .OrderBy(m => m.Name)
            .ToList();

        int passed = 0, failed = 0;
        var tests = new List<string>();

        foreach (var m in methods)
        {
            string status;
            string message = "";
            try
            {
                m.Invoke(null, null);
                status = "passed";
                passed++;
            }
            catch (TargetInvocationException tie)
            {
                var inner = tie.InnerException;
                status = "failed";
                message = Escape(inner?.Message ?? tie.Message);
                failed++;
            }
            catch (Exception ex)
            {
                status = "failed";
                message = Escape(ex.Message);
                failed++;
            }

            tests.Add($"{{\"name\":\"{Escape(m.Name)}\",\"status\":\"{status}\""
                + (message.Length > 0 ? $",\"message\":\"{message}\"" : "")
                + "}");
        }

        int total = passed + failed;
        string json = "{\"results\":{\"tool\":{\"name\":\"ctrf_test\"},\"summary\":"
            + $"{{\"tests\":{total},\"passed\":{passed},\"failed\":{failed},"
            + "\"pending\":0,\"skipped\":0,\"other\":0},"
            + "\"tests\":[" + string.Join(",", tests) + "]}}";

        File.WriteAllText(outPath, json);
        Console.WriteLine($"CTRF: {passed}/{total} passed");
        return failed > 0 ? 1 : 0;
    }

    static string Escape(string s)
    {
        if (s == null) return "";
        return s.Replace("\\", "\\\\").Replace("\"", "\\\"")
                .Replace("\n", "\\n").Replace("\r", "\\r").Replace("\t", "\\t");
    }
}
