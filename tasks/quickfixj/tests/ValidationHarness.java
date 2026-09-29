import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- DataDictionary.validate() raises the correct TYPED exception on
 * each user-visible violation category (spec §2/§3). Tests assert the exception TYPE
 * and the offending tag; the internal FIX SessionRejectReason code is not asserted.
 */
public class ValidationHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final DataDictionary DD;
    static { try { DD = new DataDictionary("FIX44.xml"); } catch (Exception e) { throw new RuntimeException(e); } }

    static Message hb() throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, "0");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        return m;
    }

    static Message nos() throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, "D");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.setString(11, "O1");
        m.setString(55, "AAPL");
        m.setChar(54, '1');
        m.setChar(40, '2');
        m.setDouble(38, 100);
        m.setDouble(44, 150.50);
        m.setString(60, "20240101-10:00:00.000");
        m.setChar(59, '0');
        return m;
    }

    /** Assert validate throws FieldException for the given tag. Message.toString() is called
     *  first to populate BodyLength/CheckSum (else validate short-circuits on tag 9). */
    static String expectFieldException(Message m, int field) {
        try {
            m.toString();
            DD.validate(m);
            return "FAIL:no_exception";
        } catch (FieldException e) {
            if (e.getField() != field) return "FAIL:field=" + e.getField();
            return "OK";
        } catch (Exception e) { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
    }

    static {
        // ---- Happy path: a fully-formed NewOrderSingle validates without throwing. ----
        c("valid_message_passes", () -> {
            try {
                Message m = nos();
                m.toString();
                DD.validate(m);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- MsgType not in dictionary -> FieldException on tag 35. ----
        c("invalid_msgtype_throws_field_exception", () -> {
            try {
                Message m = hb();
                m.getHeader().setString(35, "ZZZ");
                return expectFieldException(m, 35);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Unknown tag anywhere in the dictionary -> FieldException on the unknown tag. ----
        c("unknown_tag_throws_field_exception", () -> {
            try {
                Message m = hb();
                m.setString(99999, "x");
                return expectFieldException(m, 99999);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Tag defined but not allowed on this msgtype -> FieldException on the tag. ----
        c("tag_not_allowed_for_msgtype_throws_field_exception", () -> {
            try {
                Message m = hb();
                m.setString(55, "AAPL");   // Symbol not allowed on a Heartbeat
                return expectFieldException(m, 55);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Required field missing -> FieldException on the missing tag. ----
        c("required_field_missing_throws_field_exception", () -> {
            try {
                Message m = nos();
                m.removeField(55);
                return expectFieldException(m, 55);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Field present with empty value -> FieldException on the empty tag. ----
        c("empty_field_value_throws_field_exception", () -> {
            try {
                Message m = nos();
                m.setString(55, "");
                return expectFieldException(m, 55);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Field value not among dictionary enum values -> IncorrectTagValue on the field.
        //      This is a DIFFERENT typed exception from FieldException — user code that catches
        //      IncorrectTagValue can distinguish "bad value" from "structural violation". ----
        c("enum_violation_throws_incorrect_tag_value", () -> {
            try {
                Message m = nos();
                m.setChar(54, 'X');
                m.toString();
                DD.validate(m);
                return "FAIL:no_exception";
            } catch (IncorrectTagValue e) {
                if (e.getField() != 54) return "FAIL:field=" + e.getField();
                return "OK";
            } catch (Exception e) { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });

        // ---- Field value not matching declared data type -> IncorrectDataFormat on the field.
        //      Also a distinct typed exception; user code can react to bad data separately from
        //      bad enums or structural violations. ----
        c("type_violation_throws_incorrect_data_format", () -> {
            try {
                Message m = nos();
                m.setString(60, "not-a-timestamp");
                m.toString();
                DD.validate(m);
                return "FAIL:no_exception";
            } catch (IncorrectDataFormat e) {
                if (e.getField() != 60) return "FAIL:field=" + e.getField();
                return "OK";
            } catch (Exception e) { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });

        // ---- Repeating-group count mismatch -> FieldException on the count tag. ----
        c("group_count_mismatch_throws_field_exception", () -> {
            try {
                char soh = (char) 0x01;
                String rest = "35=W" + soh + "34=1" + soh
                    + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                    + "55=AAPL" + soh
                    + "268=5" + soh                                     // count=5 but only 2 entries follow
                    + "269=0" + soh + "270=150.10" + soh
                    + "269=1" + soh + "270=150.20" + soh;
                String wire = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < wire.length(); i++) cs = (cs + wire.charAt(i)) & 0xFF;
                Message m = new Message(wire + "10=" + String.format("%03d", cs) + soh, DD);
                return expectFieldException(m, 268);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- UTCTIMESTAMP data type check: sub-second precision (`.ssssss`) is legal per spec. ----
        c("utc_timestamp_microsecond_precision_accepted", () -> {
            try {
                Message m = hb();
                m.getHeader().setString(52, "20240101-10:00:00.123456");
                m.toString();
                DD.validate(m);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Repeating-group count LESS than actual entries (reverse of the count-too-high case). ----
        c("group_count_less_than_actual_throws_field_exception", () -> {
            try {
                char soh = (char) 0x01;
                String rest = "35=W" + soh + "34=1" + soh
                    + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                    + "55=AAPL" + soh
                    + "268=1" + soh                                     // count=1 but 2 entries follow
                    + "269=0" + soh + "270=150.10" + soh
                    + "269=1" + soh + "270=150.20" + soh;
                String wire = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < wire.length(); i++) cs = (cs + wire.charAt(i)) & 0xFF;
                Message m = new Message(wire + "10=" + String.format("%03d", cs) + soh, DD);
                return expectFieldException(m, 268);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Unknown tag inside a repeating-group entry -> FieldException on the unknown tag. ----
        c("group_entry_with_unknown_tag_throws_field_exception", () -> {
            try {
                char soh = (char) 0x01;
                String rest = "35=W" + soh + "34=1" + soh
                    + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                    + "55=AAPL" + soh
                    + "268=1" + soh + "269=0" + soh + "270=150.10" + soh
                    + "12345=x" + soh;                                   // unknown tag inside group entry
                String wire = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < wire.length(); i++) cs = (cs + wire.charAt(i)) & 0xFF;
                Message m = new Message(wire + "10=" + String.format("%03d", cs) + soh, DD);
                return expectFieldException(m, 12345);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Nested-group inner count mismatch: outer NoPartyIDs(453) count OK, inner
        //      NoPartySubIDs(802) count wrong -> FieldException on 802. Distinct code path
        //      from top-level group validation. ----
        c("nested_group_inner_count_mismatch_throws_field_exception", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4"); m.getHeader().setString(35, "D");
                m.getHeader().setInt(34, 1); m.getHeader().setString(49, "A"); m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(11, "O1"); m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                m.setDouble(38, 100); m.setDouble(44, 150.50);
                m.setString(60, "20240101-10:00:00.000"); m.setChar(59, '0');
                Group party = new Group(453, 448);
                party.setString(448, "PARTY1"); party.setChar(447, 'D'); party.setInt(452, 1);
                for (int s = 1; s <= 2; s++) {
                    Group sub = new Group(802, 523);
                    sub.setString(523, "SUB" + s); sub.setInt(803, s);
                    party.addGroup(sub);
                }
                m.addGroup(party);
                String wire = m.toString();
                char soh = (char) 0x01;
                // Corrupt inner count: replace |802=2| with |802=5|; recompute CheckSum.
                String bad = wire.replace(soh + "802=2" + soh, soh + "802=5" + soh);
                int idx = bad.lastIndexOf(soh + "10=");
                String body = bad.substring(0, idx + 1);
                int cs = 0; for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
                Message mp = new Message(body + "10=" + String.format("%03d", cs) + soh, DD);
                return expectFieldException(mp, 802);
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- UTCTIMESTAMP data type check: dash-separated date rejects with IncorrectDataFormat. ----
        c("utc_timestamp_wrong_format_throws_incorrect_data_format", () -> {
            try {
                Message m = hb();
                m.getHeader().setString(52, "2024-01-01-10:00:00.000");
                m.toString();
                try { DD.validate(m); return "FAIL:no_exception"; }
                catch (IncorrectDataFormat e) {
                    if (e.getField() != 52) return "FAIL:field=" + e.getField();
                    return "OK";
                }
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
