import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- tricky FIX 4.4 / 5.0 spec edge cases the base suite doesn't cover.
 * Trimmed to the highest-signal cases; other edges have been folded into the topical harnesses.
 */
public class SpecEdgeCasesHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static final DataDictionary DD;
    static { try { DD = new DataDictionary("FIX44.xml"); } catch (Exception e) { throw new RuntimeException(e); } }

    static {
        // ---- Trailer field order: FIX 4.4 spec puts SignatureLength(93) BEFORE Signature(89)
        //      so the receiver knows how many bytes of signature to consume; CheckSum(10) is last. ----
        c("trailer_signature_before_checksum", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.getTrailer().setInt(93, 4);
                m.getTrailer().setString(89, "abcd");
                String wire = m.toString().replace(SOH, '|');
                int i89 = wire.indexOf("|89=abcd|");
                int i93 = wire.indexOf("|93=4|");
                int i10 = wire.indexOf("|10=");
                if (i89 < 0 || i93 < 0 || i10 < 0)  return "FAIL:missing wire=" + wire;
                if (!(i93 < i89 && i89 < i10))      return "FAIL:order 93@" + i93 + " 89@" + i89 + " 10@" + i10;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Logon with ResetSeqNumFlag(141)=Y is a special-case admin message. Should parse
        //      + validate cleanly. ----
        c("logon_with_reset_seq_num_flag_validates", () -> {
            try {
                DataDictionary sess = new DataDictionary("FIXT11.xml");
                Message m = new Message();
                m.getHeader().setString(8, "FIXT.1.1");
                m.getHeader().setString(35, "A");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setInt(98, 0);
                m.setInt(108, 30);
                m.setBoolean(141, true);
                m.setInt(1137, 9);
                m.toString();
                sess.validate(m);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Repeating group with count=1 (boundary vs count=0 and count>1). ----
        c("repeating_group_count_one_roundtrip", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "W");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(55, "AAPL");
                Group g = new Group(268, 269);
                g.setChar(269, '0');
                g.setDouble(270, 150.10);
                m.addGroup(g);
                Message parsed = new Message(m.toString(), DD);
                if (parsed.getGroupCount(268) != 1)                       return "FAIL:count=" + parsed.getGroupCount(268);
                Group got = parsed.getGroup(1, new Group(268, 269));
                if (got.getChar(269) != '0')                              return "FAIL:269=" + got.getChar(269);
                if (got.getDouble(270) != 150.10)                         return "FAIL:270=" + got.getDouble(270);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Fresh message with no fields: toString() is non-null, deterministic across
        //      independent instances, AND emits the canonical empty-body framing
        //      "9=0<SOH>10=167<SOH>" (BodyLength 0; 167 = checksum of "9=0<SOH>" per §1). Pinning
        //      the wire rejects a shell that drops the BodyLength/CheckSum framing (e.g. "") . ----
        c("empty_message_toString_deterministic", () -> {
            try {
                String s1 = new Message().toString();
                String s2 = new Message().toString();
                if (s1 == null || s2 == null)                             return "FAIL:null";
                if (!s1.equals(s2))                                        return "FAIL:not_deterministic";
                String want = "9=0" + SOH + "10=167" + SOH;
                if (!want.equals(s1))                                     return "FAIL:wire=" + s1.replace(SOH, '|');
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Repeating group with WIDER entries (multiple additional fields per entry) exercises
        //      the parser's entry-completion detection beyond the base 2-field-per-entry case. ----
        c("group_entry_with_many_fields_roundtrip", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "W");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(55, "AAPL");
                Group g = new Group(268, 269);
                g.setChar(269, '0');
                g.setDouble(270, 150.10);
                g.setDouble(271, 500);
                g.setString(273, "10:00:00.000");
                m.addGroup(g);
                Message parsed = new Message(m.toString(), DD);
                Group got = parsed.getGroup(1, new Group(268, 269));
                if (got.getChar(269) != '0')                              return "FAIL:269";
                if (got.getDouble(270) != 150.10)                         return "FAIL:270";
                if (got.getDouble(271) != 500)                            return "FAIL:271";
                if (!"10:00:00.000".equals(got.getString(273)))           return "FAIL:273=" + got.getString(273);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
