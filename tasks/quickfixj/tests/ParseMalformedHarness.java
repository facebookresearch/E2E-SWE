import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- parse-time structural rejection: malformed wires must raise
 * InvalidMessage. Consolidated to the highest-signal structural checks (missing BodyLength,
 * missing CheckSum, non-numeric tag). Complements MessageBasicsHarness bad_checksum_raises
 * + empty_wire_raises.
 */
public class ParseMalformedHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;

    static String cs(String body) {
        int s = 0;
        for (int i = 0; i < body.length(); i++) s = (s + body.charAt(i)) & 0xFF;
        return body + "10=" + String.format("%03d", s) + SOH;
    }

    static {
        // ---- Wire missing tag 9 (BodyLength). §1: "always begins with tag 8, then 9". ----
        c("parse_missing_body_length_raises_invalid_message", () -> {
            try {
                new Message("8=FIX.4.4" + SOH + "35=0" + SOH + "34=1" + SOH + "49=A" + SOH
                        + "56=B" + SOH + "52=20240101-10:00:00" + SOH + "10=000" + SOH);
                return "FAIL:parsed_without_exception";
            } catch (InvalidMessage e) { return "OK"; }
              catch (Exception e)      { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Wire missing tag 10 (CheckSum). §1: "trailer always ends with tag 10". ----
        c("parse_missing_checksum_raises_invalid_message", () -> {
            try {
                new Message("8=FIX.4.4" + SOH + "9=40" + SOH + "35=0" + SOH + "34=1" + SOH
                        + "49=A" + SOH + "56=B" + SOH + "52=20240101-10:00:00" + SOH);
                return "FAIL:parsed_without_exception";
            } catch (InvalidMessage e) { return "OK"; }
              catch (Exception e)      { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Non-numeric tag in a `tag=value` pair. §1: "Tags are positive integers". ----
        c("parse_non_numeric_tag_raises_invalid_message", () -> {
            try {
                String body = "8=FIX.4.4" + SOH + "9=20" + SOH + "35=0" + SOH + "foo=bar" + SOH;
                new Message(cs(body));
                return "FAIL:parsed_without_exception";
            } catch (InvalidMessage e) { return "OK"; }
              catch (Exception e)      { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
