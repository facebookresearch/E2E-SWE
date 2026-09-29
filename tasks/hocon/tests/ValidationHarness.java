import com.lattice.config.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — schema validation (Config.checkValid). checkValid compares a config against a
 * reference config and throws ConfigException.ValidationFailed (collecting a list of problems) when
 * a reference key is missing or has an incompatible type; string values are treated as compatible
 * with scalar types; validation can be restricted to given paths; and it requires a resolved config.
 *
 * Design: one bundled case per distinct validation behavior; error cases assert the exception
 * subclass and (for the missing-key case) the problem count.
 */
public class ValidationHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static Config r(String s) { return ConfigFactory.parseString(s).resolve(); }

    static {
        // ---- checkValid passes when all reference keys are present with compatible types ----
        c("valid_ok", () -> {
            Config ref = r("a = 1\nb = hello\nc = true");
            Config subj = r("a = 5\nb = world\nc = false");
            return "result=" + ex(() -> subj.checkValid(ref));
        });

        // ---- checkValid throws ValidationFailed when a reference key is missing ----
        c("valid_missing_key", () -> {
            Config ref = r("a = 1\nb = hello\nc = true");
            Config subj = r("a = 5\nc = false");   // missing b
            String kind = ex(() -> subj.checkValid(ref));
            int problems = -1;
            try { subj.checkValid(ref); }
            catch (ConfigException.ValidationFailed vf) {
                // Iterate as a raw Iterable so this case does not depend on the concrete element
                // type's location (the count is the contract we assert).
                problems = 0; for (Object p : vf.problems()) problems++;
            }
            return "kind=" + kind + "|problems=" + problems;
        });

        // ---- String values are compatible with scalar reference types (no failure) ----
        c("valid_string_compatible", () -> {
            Config ref = r("a = 1\nb = hi\nc = true");
            Config subj = r("a = \"5\"\nb = x\nc = false");   // a is a string vs number ref -> OK
            return "result=" + ex(() -> subj.checkValid(ref));
        });

        // ---- An object-vs-scalar type mismatch fails validation ----
        c("valid_object_mismatch", () -> {
            Config ref = r("obj { x = 1 }");
            Config subj = r("obj = 5");                       // scalar where object expected
            return "result=" + ex(() -> subj.checkValid(ref));
        });

        // ---- restrictToPaths scopes validation: validating only a present path passes ----
        c("valid_restrict_paths", () -> {
            Config ref = r("a = 1\nb = hello\nc = true");
            Config subj = r("a = 5\nc = false");              // missing b
            return "restrictPresent=" + ex(() -> subj.checkValid(ref, "c"))   // only c -> OK
                 + "|restrictMissing=" + ex(() -> subj.checkValid(ref, "b")); // b -> fail
        });

        // ---- checkValid on an unresolved config throws (must resolve first) ----
        c("valid_unresolved_throws", () -> {
            Config ref = r("a = 1");
            Config subj = ConfigFactory.parseString("a = ${x}\nx = 5");  // NOT resolved
            return "result=" + ex(() -> subj.checkValid(ref));
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
