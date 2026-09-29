import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- header/trailer field-ordering rules not covered by the base OrderingHarness.
 * Base coverage: 8/9/35 first, 10 last, body ascending, group delimiter first. This harness adds:
 *   - Header fields BEYOND 8/9/35 emit in ascending tag order.
 *   - Parse-time detection of a HEADER field appearing at the header/body boundary.
 */
public class HeaderOrderingHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static final DataDictionary DD;
    static { try { DD = new DataDictionary("FIX44.xml"); } catch (Exception e) { throw new RuntimeException(e); } }

    static String d(String w) { return w.replace(SOH, '|'); }

    static String withChecksum(String body) {
        int cs = 0;
        for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
        return body + "10=" + String.format("%03d", cs) + SOH;
    }

    static {
        // ---- Header fields BEYOND 8/9/35 must emit in ASCENDING tag order.
        //      Setting fields in scrambled tag order (56 first, then 34, 52, 35, 49, 43, 8) — the
        //      reference emits them as: 8, 9, 35, then ascending: 34, 43, 49, 52, 56.
        c("header_fields_after_35_ascending", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(56, "TARGET");
                m.getHeader().setInt(34, 42);
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.getHeader().setString(35, "0");
                m.getHeader().setString(49, "SENDER");
                m.getHeader().setBoolean(43, true);     // PossDupFlag — an optional header field
                m.getHeader().setString(8, "FIX.4.4");
                String wire = d(m.toString());
                // Extract tag numbers in the emitted order.
                java.util.List<Integer> tags = new java.util.ArrayList<>();
                for (String pair : wire.split("\\|")) {
                    if (pair.isEmpty()) continue;
                    tags.add(Integer.parseInt(pair.substring(0, pair.indexOf('='))));
                }
                // Expect: [8, 9, 35, then ascending header fields, then 10].
                if (tags.size() < 4)                       return "FAIL:short " + tags;
                if (tags.get(0) != 8 || tags.get(1) != 9 || tags.get(2) != 35) return "FAIL:prefix " + tags.subList(0, 3);
                // Remaining fields (excluding trailing 10) must be strictly ascending AMONG THEMSELVES
                // (they can be numerically less than 35 — e.g., 34 comes after 35 in position but is
                // less numerically; the ascending rule applies only within the tail).
                int lastTag = -1;
                for (int i = 3; i < tags.size() - 1; i++) {
                    int t = tags.get(i);
                    if (t <= lastTag)                       return "FAIL:not_ascending tag " + t + " after " + lastTag + " full=" + tags;
                    lastTag = t;
                }
                if (tags.get(tags.size() - 1) != 10)       return "FAIL:not_10_last " + tags;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
