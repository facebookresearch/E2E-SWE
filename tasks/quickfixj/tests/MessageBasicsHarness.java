import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- Message wire-format basics (user-facing surface only).
 *
 * Each case is self-asserting: it returns "OK" on success or "FAIL:<detail>" on any invariant
 * violation. Runner.java compares the returned string to the canonical "OK" fixture entry.
 */
public class MessageBasicsHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static String w(String pipeForm) { return pipeForm.replace('|', SOH); }
    static String d(String wire)     { return wire.replace(SOH, '|'); }

    // Canonical FIX 4.4 Heartbeat -- BodyLength 56, CheckSum 125.
    static final String HEARTBEAT =
        w("8=FIX.4.4|9=56|35=0|34=42|49=CLIENT|52=20240101-10:00:00.000|56=SERVER|10=125|");

    static String buildNewOrderSingle() throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, "D");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "SENDER");
        m.getHeader().setString(56, "TARGET");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.setString(11, "ORDER1");
        m.setString(55, "AAPL");
        m.setChar(54, '1');
        m.setString(60, "20240101-10:00:00.000");
        m.setDouble(38, 100);
        m.setChar(40, '2');
        m.setDouble(44, 150.50);
        m.setChar(59, '0');
        return m.toString();
    }

    static {
        // ---- Parse the canonical Heartbeat: every header + trailer field must equal its known value. ----
        c("parse_heartbeat_fields", () -> {
            try {
                Message m = new Message(HEARTBEAT);
                if (!"FIX.4.4".equals(m.getHeader().getString(8))) return "FAIL:8=" + m.getHeader().getString(8);
                if (m.getHeader().getInt(9) != 56)               return "FAIL:9=" + m.getHeader().getInt(9);
                if (!"0".equals(m.getHeader().getString(35)))    return "FAIL:35=" + m.getHeader().getString(35);
                if (m.getHeader().getInt(34) != 42)              return "FAIL:34=" + m.getHeader().getInt(34);
                if (!"CLIENT".equals(m.getHeader().getString(49))) return "FAIL:49=" + m.getHeader().getString(49);
                if (!"SERVER".equals(m.getHeader().getString(56))) return "FAIL:56=" + m.getHeader().getString(56);
                if (!"125".equals(m.getTrailer().getString(10))) return "FAIL:10=" + m.getTrailer().getString(10);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Round-trip: parse a canonical Heartbeat, re-serialise, must byte-equal the input. ----
        c("roundtrip_heartbeat", () -> {
            try {
                String out = new Message(HEARTBEAT).toString();
                return out.equals(HEARTBEAT) ? "OK" : "FAIL:got=" + d(out);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Round-trip on a busier message: NewOrderSingle exercises multi-field body ordering. ----
        c("roundtrip_new_order_single", () -> {
            try {
                String wire = buildNewOrderSingle();
                String out = new Message(wire).toString();
                return out.equals(wire) ? "OK" : "FAIL:got=" + d(out);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Build-and-serialise: an assembled Heartbeat must emit exactly the canonical wire. ----
        c("build_heartbeat_wire", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 42);
                m.getHeader().setString(49, "CLIENT");
                m.getHeader().setString(56, "SERVER");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                String out = m.toString();
                return out.equals(HEARTBEAT) ? "OK" : "FAIL:got=" + d(out);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Header ordering: 8, 9, 35 first even if fields are inserted in reverse order. ----
        c("header_mandatory_order", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(49, "S");
                m.getHeader().setString(56, "T");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.getHeader().setString(35, "0");
                m.getHeader().setString(8, "FIX.4.4");
                String wire = d(m.toString());
                int p8  = wire.indexOf("8=");
                int p9  = wire.indexOf("|9=");
                int p35 = wire.indexOf("|35=");
                if (p8 != 0)                return "FAIL:8_not_first: " + wire;
                if (!(p9 > p8 && p35 > p9)) return "FAIL:order p8=" + p8 + " p9=" + p9 + " p35=" + p35;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Parsing a wire with a WRONG CheckSum must raise InvalidMessage. ----
        c("bad_checksum_raises", () -> {
            try {
                String bad = HEARTBEAT.substring(0, HEARTBEAT.length() - 5) + "999" + SOH;
                new Message(bad);
                return "FAIL:no_exception";
            } catch (InvalidMessage e) { return "OK"; }
              catch (Exception e)      { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });

        // ---- Parsing an empty string must raise InvalidMessage. ----
        c("empty_wire_raises", () -> {
            try {
                new Message("");
                return "FAIL:no_exception";
            } catch (InvalidMessage e) { return "OK"; }
              catch (Exception e)      { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });

        // ---- isEmpty() flips to false once any body field is set. ----
        c("message_isEmpty_false_after_setField", () -> {
            try {
                Message m = new Message();
                m.setString(55, "AAPL");
                if (m.isEmpty()) return "FAIL:still_empty";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Round-trip stability after mutation: parse wire -> mutate a body field ->
        //      serialise -> re-parse -> the mutation persists and all other fields intact. ----
        c("roundtrip_after_field_mutation_stable", () -> {
            try {
                String wire = buildNewOrderSingle();
                Message parsed = new Message(wire);
                parsed.setString(11, "MUTATED_ORDER");                   // change ClOrdID
                parsed.setDouble(38, 250);                               // change OrderQty
                String reWire = parsed.toString();
                Message reParsed = new Message(reWire);
                if (!"MUTATED_ORDER".equals(reParsed.getString(11)))     return "FAIL:11=" + reParsed.getString(11);
                if (reParsed.getDouble(38) != 250.0)                     return "FAIL:38=" + reParsed.getDouble(38);
                // Original fields must survive.
                if (!"AAPL".equals(reParsed.getString(55)))              return "FAIL:55=" + reParsed.getString(55);
                if (reParsed.getChar(54) != '1')                         return "FAIL:54=" + reParsed.getChar(54);
                if (reParsed.getDouble(44) != 150.50)                    return "FAIL:44=" + reParsed.getDouble(44);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- UTCTIMESTAMP sub-second precision (`.ssssss` microseconds) survives round-trip
        //      unchanged. Parser must not truncate or reformat. ----
        c("utc_timestamp_microsecond_preserved_through_roundtrip", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.123456");
                Message parsed = new Message(m.toString());
                if (!"20240101-10:00:00.123456".equals(parsed.getHeader().getString(52)))
                                                                          return "FAIL:52=" + parsed.getHeader().getString(52);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Message.clear() wipes BOTH header and body fields. ----
        c("message_clear_removes_header_and_body_fields", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.setString(55, "AAPL");
                m.clear();
                if (m.getHeader().isSetField(35))                return "FAIL:35_still_set";
                if (m.getHeader().isSetField(34))                return "FAIL:34_still_set";
                if (m.isSetField(55))                            return "FAIL:55_still_set";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
