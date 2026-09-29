import com.bazaarvoice.jolt.JsonUtils;
import com.bazaarvoice.jolt.Shiftr;
import com.bazaarvoice.jolt.Defaultr;
import com.bazaarvoice.jolt.Removr;
import com.bazaarvoice.jolt.Chainr;
import java.util.*;

/**
 * Standalone hidden test harness for the jolt JSON-transformation DSL.
 *
 * Each fixture is an exact input/spec/expected triple mined from the reference suite.
 * The harness parses the triple with JsonUtils (provided), runs the transform under test,
 * and compares the produced tree against the expected tree. Objects are compared
 * key-order-independently; arrays are compared in order (jolt preserves input insertion
 * order in its output). Numbers compare by value across Integer/Long/Double.
 *
 * Emits one JSON line per test to stdout for CTRF conversion by test.sh.
 */
public class TestJolt {

    static final String FX = "/tests/fixtures/";
    static int passed = 0, failed = 0;

    static String esc(String s) {
        if (s == null) return "null";
        return s.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t");
    }

    /** Order-independent for maps, order-sensitive for lists, value-based for numbers. */
    static boolean treeEq(Object a, Object b) {
        if (a == null || b == null) return a == b;
        if (a instanceof Map && b instanceof Map) {
            Map<?, ?> ma = (Map<?, ?>) a, mb = (Map<?, ?>) b;
            if (ma.size() != mb.size()) return false;
            for (Object k : ma.keySet()) {
                if (!mb.containsKey(k)) return false;
                if (!treeEq(ma.get(k), mb.get(k))) return false;
            }
            return true;
        }
        if (a instanceof List && b instanceof List) {
            List<?> la = (List<?>) a, lb = (List<?>) b;
            if (la.size() != lb.size()) return false;
            for (int i = 0; i < la.size(); i++)
                if (!treeEq(la.get(i), lb.get(i))) return false;
            return true;
        }
        if (a instanceof Number && b instanceof Number) {
            double da = ((Number) a).doubleValue(), db = ((Number) b).doubleValue();
            if (da == db) return true;
            return a.toString().equals(b.toString());
        }
        return a.equals(b);
    }

    static void emitPass(String name) {
        passed++;
        System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
    }

    static void emitFail(String name, String msg) {
        failed++;
        System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\"" + esc(msg) + "\"}");
    }

    /** Run a single-transform fixture (input/spec/expected triple). */
    static void runFixture(String kind, String fixture) {
        String name = kind + "/" + fixture;
        try {
            Map<String, Object> tu = JsonUtils.filepathToMap(FX + kind + "/" + fixture + ".json");
            Object input = tu.get("input");
            Object spec = tu.get("spec");
            Object expected = tu.get("expected");
            Object actual;
            switch (kind) {
                case "shiftr":   actual = new Shiftr(spec).transform(input); break;
                case "defaultr": actual = new Defaultr(spec).transform(input); break;
                case "removr":   actual = new Removr(spec).transform(input); break;
                default: throw new RuntimeException("unknown kind " + kind);
            }
            if (treeEq(expected, actual)) emitPass(name);
            else emitFail(name, "expected " + JsonUtils.toJsonString(expected) + " got " + JsonUtils.toJsonString(actual));
        } catch (Throwable e) {
            emitFail(name, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    /** Run a Chainr composite fixture: {input, spec:[...steps...], expected}. */
    static void runChainr(String fixture) {
        String name = "chainr/" + fixture;
        try {
            Map<String, Object> tu = JsonUtils.filepathToMap(FX + "chainr/" + fixture + ".json");
            Object input = tu.get("input");
            Object spec = tu.get("spec");
            Object expected = tu.get("expected");
            Chainr chainr = Chainr.fromSpec(spec);
            Object actual = chainr.transform(input);
            if (treeEq(expected, actual)) emitPass(name);
            else emitFail(name, "expected " + JsonUtils.toJsonString(expected) + " got " + JsonUtils.toJsonString(actual));
        } catch (Throwable e) {
            emitFail(name, e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    public static void main(String[] args) {
        // ---- Shiftr: the core path-matching / reference algebra (the discriminator) ----
        String[] shiftr = {
            // literal placement + fan-out
            "singlePlacement", "multiPlacement", "firstSample",
            // wildcards + match specificity + OR
            "wildcards", "passThru", "wildcardSelfAndRef",
            // & ancestor references
            "keyref", "lhsAmpMatch", "bucketToPrefixSoup", "prefixSoupToBuckets",
            // $ match-the-key
            "invertMap", "listKeys", "prefixedData", "specialKeys",
            // null RHS = trash / drop
            "shiftToTrash",
            // array writes: [], [&], [#], explicit index, declared size
            "arrayExample", "explicitArrayKey",
            "declaredOutputArray", "inputArrayToPrefix", "prefixDataToArray",
            // # literal inject / array index
            "hashDefault", "mapToList", "mapToList2",
            // @ value-reference / transpose family (the hardest operator)
            "transposeSimple1",
            "transposeComplex7_coerce-int-string-conversion",
            "transposeComplex9_lookup_an_array_index",
            "transposeLHS1", "transposeLHS3", "transposeInverseMap1", "transposeNestedLookup",
            // parent filtering + parallel arrays
            "filterParents1", "filterParallelArrays", "mergeParallelArrays1_and-transpose",
            // escaping of operator characters
            "simpleLHSEscape", "escapeAllTheThings",
            // misc edge cases
            "passNullThru", "pollaxman_218_duplicate_speclines_bug", "queryMappingXform",
        };
        for (String f : shiftr) runFixture("shiftr", f);

        // ---- Defaultr: recursive deep-merge of default values ----
        String[] defaultr = {
            "firstSample", "defaultNulls", "expansionOnly", "nestedArrays1", "orOrdering",
        };
        for (String f : defaultr) runFixture("defaultr", f);

        // ---- Removr: key removal with wildcard support ----
        String[] removr = {
            "firstSample", "multiStarSupport", "removrWithWildcardSupport",
            "array_removeAnArrayIndex", "boundaryConditions",
        };
        for (String f : removr) runFixture("removr", f);

        // ---- Chainr: multi-step pipeline dispatch by operation name ----
        String[] chainr = { "shiftOnly", "shiftThenDefault" };
        for (String f : chainr) runChainr(f);
    }
}
