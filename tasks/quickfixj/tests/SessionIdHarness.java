import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- SessionID value class (spec §2 "SessionID"): constructors, per-field
 * getters, equality by content, hashCode consistency, toString shape.
 */
public class SessionIdHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // ---- 3-arg and 4-arg constructors: identity strings persist to getters; sub/location
        //      fields default to empty; the 4-arg overload preserves the session qualifier. ----
        c("session_id_ctor_and_getters_both_arities", () -> {
            try {
                SessionID s3 = new SessionID("FIX.4.4", "CLIENT", "SERVER");
                if (!"FIX.4.4".equals(s3.getBeginString())) return "FAIL:3arg bs=" + s3.getBeginString();
                if (!"CLIENT".equals(s3.getSenderCompID())) return "FAIL:3arg sender=" + s3.getSenderCompID();
                if (!"SERVER".equals(s3.getTargetCompID())) return "FAIL:3arg target=" + s3.getTargetCompID();
                if (!"".equals(s3.getSenderSubID()))        return "FAIL:3arg senderSub=" + s3.getSenderSubID();
                if (!"".equals(s3.getTargetSubID()))        return "FAIL:3arg targetSub=" + s3.getTargetSubID();
                if (!"".equals(s3.getSessionQualifier()))   return "FAIL:3arg qualifier=" + s3.getSessionQualifier();
                SessionID s4 = new SessionID("FIX.4.4", "CLIENT", "SERVER", "Q1");
                if (!"Q1".equals(s4.getSessionQualifier())) return "FAIL:4arg qualifier=" + s4.getSessionQualifier();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Equality is by content: same tuple -> equal, hashCode matches. ----
        c("session_id_equality_by_content", () -> {
            try {
                SessionID a = new SessionID("FIX.4.4", "A", "B");
                SessionID b = new SessionID("FIX.4.4", "A", "B");
                if (!a.equals(b))                        return "FAIL:not_equal";
                if (a.hashCode() != b.hashCode())        return "FAIL:hash_mismatch";
                SessionID c = new SessionID("FIX.4.4", "A", "C");   // different target
                if (a.equals(c))                         return "FAIL:different_target_equal";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- toString includes the three identity strings in a stable, readable format. ----
        c("session_id_toString_readable", () -> {
            try {
                String s = new SessionID("FIX.4.4", "CLIENT", "SERVER").toString();
                if (!s.contains("FIX.4.4"))              return "FAIL:no_beginString: " + s;
                if (!s.contains("CLIENT"))               return "FAIL:no_sender: " + s;
                if (!s.contains("SERVER"))               return "FAIL:no_target: " + s;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
