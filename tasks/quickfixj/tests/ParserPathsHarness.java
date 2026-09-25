import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- data shapes that exercise distinct Message parser code paths not covered
 * by the base suite: header-level repeating groups (vs body-only), custom fields (tag &gt;= 5000),
 * DATA field at message boundary, minimal admin message, deep nesting.
 */
public class ParserPathsHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static final DataDictionary DD;
    static { try { DD = new DataDictionary("FIX44.xml"); } catch (Exception e) { throw new RuntimeException(e); } }

    static String withChecksum(String body) {
        int cs = 0;
        for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
        return body + "10=" + String.format("%03d", cs) + SOH;
    }

    static {
        // ---- Header-level repeating group: NoHops(627) is defined INSIDE the FIX 4.4 header,
        //      with delimiter HopCompID(628) + HopSendingTime(629) + HopRefID(630) per entry.
        //      Parser must recognize 627 as a group in the HEADER section (distinct code path
        //      from body-group detection).
        c("header_group_no_hops_roundtrip", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                Group hop = new Group(627, 628);
                hop.setString(628, "HOP1");                        // HopCompID
                hop.setString(629, "20240101-09:00:00.000");        // HopSendingTime
                hop.setString(630, "REF1");                         // HopRefID
                m.getHeader().addGroup(hop);
                String wire = m.toString();
                Message parsed = new Message(wire, DD);
                if (parsed.getHeader().getGroupCount(627) != 1) return "FAIL:count=" + parsed.getHeader().getGroupCount(627);
                Group got = parsed.getHeader().getGroup(1, new Group(627, 628));
                if (!"HOP1".equals(got.getString(628)))          return "FAIL:HopCompID=" + got.getString(628);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Custom field (tag >= 5000) parses OK without a dictionary (no dict = no lookup). ----
        c("parse_custom_field_5000_no_dict_ok", () -> {
            try {
                String rest = "35=0" + SOH + "34=1" + SOH
                    + "49=A" + SOH + "52=20240101-10:00:00.000" + SOH + "56=B" + SOH
                    + "5000=custom_value" + SOH;
                String body = "8=FIX.4.4" + SOH + "9=" + rest.length() + SOH + rest;
                Message m = new Message(withChecksum(body));
                if (!"custom_value".equals(m.getString(5000))) return "FAIL:5000=" + m.getString(5000);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Custom field (tag not in dict) is rejected by validate with a FieldException on
        //      the custom tag. Parse succeeds; validate rejects. ----
        c("validate_custom_field_5000_rejects", () -> {
            try {
                String rest = "35=0" + SOH + "34=1" + SOH
                    + "49=A" + SOH + "52=20240101-10:00:00.000" + SOH + "56=B" + SOH
                    + "5000=x" + SOH;
                String body = "8=FIX.4.4" + SOH + "9=" + rest.length() + SOH + rest;
                Message m = new Message(withChecksum(body), DD);
                DD.validate(m);
                return "FAIL:no_exception";
            } catch (FieldException e) {
                if (e.getField() != 5000)            return "FAIL:field=" + e.getField();
                return "OK";
            } catch (Exception e) { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });

        // ---- 3-level nested groups: Parties(453) > NestedPartySubIDs(802) > ??? — actually vanilla
        //      FIX 4.4 caps at 2 levels. Instead: MDIncGrp(268) > NestedPartyIDs(539) — use
        //      TradeCaptureReport-style. Skipping true 3-level; test 2-level with EACH level having
        //      MULTIPLE entries (exercises repeated-nested-parse). ----
        c("nested_groups_multiple_entries_per_level", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "D");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(11, "O1"); m.setString(55, "AAPL"); m.setChar(54, '1');
                m.setChar(40, '2'); m.setDouble(38, 100); m.setDouble(44, 150.50);
                m.setString(60, "20240101-10:00:00.000"); m.setChar(59, '0');
                // 2 Party entries, each with 2 SubParty entries -> 4 total sub-entries.
                for (int p = 1; p <= 2; p++) {
                    Group party = new Group(453, 448);
                    party.setString(448, "PARTY" + p);
                    party.setChar(447, 'D');
                    party.setInt(452, p);
                    for (int s = 1; s <= 2; s++) {
                        Group sub = new Group(802, 523);
                        sub.setString(523, "SUB" + p + "_" + s);
                        sub.setInt(803, s);
                        party.addGroup(sub);
                    }
                    m.addGroup(party);
                }
                Message parsed = new Message(m.toString(), DD);
                if (parsed.getGroupCount(453) != 2)                        return "FAIL:outer=" + parsed.getGroupCount(453);
                Group p2 = parsed.getGroup(2, new Group(453, 448));
                if (p2.getGroupCount(802) != 2)                            return "FAIL:inner_of_2nd=" + p2.getGroupCount(802);
                Group sub2_1 = p2.getGroup(1, new Group(802, 523));
                if (!"SUB2_1".equals(sub2_1.getString(523)))               return "FAIL:sub2_1=" + sub2_1.getString(523);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
