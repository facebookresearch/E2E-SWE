import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- canonical wire ordering invariants (self-asserting).
 */
public class OrderingHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static String d(String wire) { return wire.replace(SOH, '|'); }

    static {
        // ---- Body fields serialize in ascending tag order regardless of insertion order. ----
        c("body_ascending_tag_order", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "D");
                m.getHeader().setString(49, "S");
                m.getHeader().setString(56, "T");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(59, "0"); m.setChar(40, '2'); m.setDouble(38, 100);
                m.setString(55, "AAPL"); m.setChar(54, '1'); m.setString(11, "ORDER1");
                String wire = d(m.toString());
                java.util.Set<Integer> hdrTags = new java.util.HashSet<>(java.util.Arrays.asList(8, 9, 35, 34, 49, 52, 56));
                int trlIdx = wire.indexOf("|10=");
                String body = wire.substring(0, trlIdx);
                int prev = -1;
                for (String pair : body.split("\\|")) {
                    if (pair.isEmpty()) continue;
                    int t = Integer.parseInt(pair.substring(0, pair.indexOf('=')));
                    if (hdrTags.contains(t)) continue;
                    if (t <= prev) return "FAIL:tag " + t + " after " + prev;
                    prev = t;
                }
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Trailer: CheckSum (tag 10) is ALWAYS the final field of the wire. ----
        c("trailer_10_last", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                String wire = d(m.toString());
                String[] parts = wire.split("\\|");
                String last = parts[parts.length - 1];
                if (last.isEmpty()) last = parts[parts.length - 2];
                return last.startsWith("10=") ? "OK" : "FAIL:last=" + last;
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Macro-order: header (8/9/35/...) < body < trailer (10). ----
        c("header_body_trailer_macro_order", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "D");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "S");
                m.getHeader().setString(56, "T");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(55, "AAPL");
                m.setString(11, "O1");
                String wire = d(m.toString());
                int p8  = wire.indexOf("8=");
                int p9  = wire.indexOf("|9=");
                int p35 = wire.indexOf("|35=");
                int p11 = wire.indexOf("|11=");
                int p55 = wire.indexOf("|55=");
                int p10 = wire.indexOf("|10=");
                boolean ok = p8 == 0 && p8 < p9 && p9 < p35 && p35 < p11 && p11 < p55 && p55 < p10;
                return ok ? "OK" : String.format("FAIL:p8=%d p9=%d p35=%d p11=%d p55=%d p10=%d", p8, p9, p35, p11, p55, p10);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Group serialization: delimiter (first field of the group) leads each entry. ----
        c("group_delimiter_leads_entry", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "W");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "S");
                m.getHeader().setString(56, "T");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(55, "AAPL");
                Group g1 = new Group(268, 269); g1.setChar(269, '0'); g1.setDouble(270, 150.10);
                Group g2 = new Group(268, 269); g2.setChar(269, '1'); g2.setDouble(270, 150.20);
                m.addGroup(g1); m.addGroup(g2);
                String wire = d(m.toString());
                int i268 = wire.indexOf("|268=2|");
                int i1st = wire.indexOf("|269=0|", i268);
                int i2nd = wire.indexOf("|269=1|", i1st);
                if (i268 <= 0)     return "FAIL:no 268: " + wire;
                if (i1st <= i268)  return "FAIL:1st entry: " + wire;
                if (i2nd <= i1st)  return "FAIL:2nd entry: " + wire;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
