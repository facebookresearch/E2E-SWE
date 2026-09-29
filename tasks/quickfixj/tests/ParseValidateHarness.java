import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- distinct parse/validate contracts not covered by the base suites.
 *
 * Each case probes a spec sentence that describes behaviour distinct from anything in the other
 * harnesses (avoiding the §5.1 "same-implementation clumping" trap). Verified against the GT
 * reference before commit.
 */
public class ParseValidateHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static final DataDictionary DD;
    static final DataDictionary SESS;
    static {
        try {
            DD = new DataDictionary("FIX44.xml");
            SESS = new DataDictionary("FIXT11.xml");
        } catch (Exception e) { throw new RuntimeException(e); }
    }

    static String withChecksum(String body) {
        int cs = 0;
        for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
        return body + "10=" + String.format("%03d", cs) + SOH;
    }

    static String d(String w) { return w.replace(SOH, '|'); }

    static {
        // ---- Group entry non-delimiter fields must be output in ASCENDING tag order.
        //      Build a group entry with body fields (269, 270, 271), set them in reverse insertion
        //      order, verify canonical toString emits them ascending after the delimiter (269).
        //      Distinct from RepeatingGroupHarness's serialize test (which only checks the count
        //      is followed by SOME entries, not the field order within an entry).
        c("group_entry_fields_ascending_after_delim", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "W");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "S");
                m.getHeader().setString(56, "T");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(55, "AAPL");
                Group g = new Group(268, 269);
                // Insert in DESCENDING order: 272 (MDEntrySize), 271 (?), 270 (MDEntryPx), then delim 269.
                g.setDouble(271, 500);           // MDEntrySize-ish field (any body tag > 269)
                g.setDouble(270, 150.10);
                g.setChar(269, '0');
                m.addGroup(g);
                String wire = d(m.toString());
                // After |268=1| the group entry starts. Extract that entry substring (up to |10=).
                int start = wire.indexOf("|268=1|") + "|268=1|".length();
                int end   = wire.indexOf("|10=", start);
                String entry = wire.substring(start, end);
                // Collect tags in emitted order.
                java.util.List<Integer> tags = new java.util.ArrayList<>();
                for (String pair : entry.split("\\|")) {
                    if (pair.isEmpty()) continue;
                    tags.add(Integer.parseInt(pair.substring(0, pair.indexOf('='))));
                }
                if (tags.isEmpty() || tags.get(0) != 269) return "FAIL:delim_not_first tags=" + tags;
                for (int i = 2; i < tags.size(); i++) {
                    if (tags.get(i) < tags.get(i - 1)) return "FAIL:not_ascending_after_delim tags=" + tags;
                }
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Session dictionary single-arg validate accepts admin messages. Spec §5: session
        //      dict defines admin messages. Two fixtures to guard against impls hardcoded to a
        //      single admin msgtype: Logon(35=A) and Heartbeat(35=0), both under FIXT.1.1. ----
        c("session_dict_validates_admin_messages", () -> {
            try {
                // Logon (35=A) with required 98/108/1137 populated.
                Message logon = new Message();
                logon.getHeader().setString(8, "FIXT.1.1");
                logon.getHeader().setString(35, "A");
                logon.getHeader().setInt(34, 1);
                logon.getHeader().setString(49, "A");
                logon.getHeader().setString(56, "B");
                logon.getHeader().setString(52, "20240101-10:00:00.000");
                logon.setInt(98, 0); logon.setInt(108, 30); logon.setInt(1137, 9);
                logon.toString();
                try { SESS.validate(logon); } catch (Exception e) { return "FAIL:Logon " + e.getClass().getSimpleName() + ":" + e.getMessage(); }

                // Heartbeat (35=0) with empty body.
                Message hb = new Message();
                hb.getHeader().setString(8, "FIXT.1.1");
                hb.getHeader().setString(35, "0");
                hb.getHeader().setInt(34, 2);
                hb.getHeader().setString(49, "A");
                hb.getHeader().setString(56, "B");
                hb.getHeader().setString(52, "20240101-10:00:00.000");
                hb.toString();
                try { SESS.validate(hb); } catch (Exception e) { return "FAIL:Heartbeat " + e.getClass().getSimpleName() + ":" + e.getMessage(); }

                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- FieldNotFound carries the offending tag on the public `field` attribute.
        //      Distinct from FieldMapHarness.get_absent_field_throws (which only catches the class).
        //      Spec §2: `public class FieldNotFound { ... public int field; }`.
        c("field_not_found_carries_tag", () -> {
            try {
                new Message().getString(99999);
                return "FAIL:no_exception";
            } catch (FieldNotFound e) {
                if (e.field != 99999) return "FAIL:field=" + e.field;
                return "OK";
            } catch (Exception e) { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });

        // ---- After parsing, a body field must live in the BODY, not the header. Distinct check
        //      from parse_heartbeat_fields (which reads from getHeader() successfully; doesn't
        //      assert that body fields are ABSENT from the header). Some naive parsers dump all
        //      fields into the Message and mirror them into both sections.
        c("parse_body_field_not_in_header", () -> {
            try {
                String rest = "35=D" + SOH + "34=1" + SOH
                    + "49=A" + SOH + "52=20240101-10:00:00.000" + SOH + "56=B" + SOH
                    + "11=O1" + SOH + "55=AAPL" + SOH + "54=1" + SOH + "40=2" + SOH
                    + "38=100" + SOH + "44=150.50" + SOH
                    + "60=20240101-10:00:00.000" + SOH + "59=0" + SOH;
                String body = "8=FIX.4.4" + SOH + "9=" + rest.length() + SOH + rest;
                Message parsed = new Message(withChecksum(body), DD);
                if (parsed.getHeader().isSetField(55))                    return "FAIL:body_tag_55_in_header";
                if (parsed.getHeader().isSetField(11))                    return "FAIL:body_tag_11_in_header";
                if (!parsed.isSetField(55))                                return "FAIL:tag_55_not_on_body";
                if (parsed.getTrailer().isSetField(55))                   return "FAIL:body_tag_55_in_trailer";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
