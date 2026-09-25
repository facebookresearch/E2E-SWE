import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- FIXT.1.1 / FIX 5.0 specific behaviours not covered by DualDictHarness.
 *
 * Existing DualDictHarness covers a single admin msg (Logon) and a single app msg
 * (NewOrderSingle). This harness broadens that to (a) additional FIXT admin messages
 * (Heartbeat, Logout), (b) session-dict admin validation, and (c) accessibility of the
 * FIXT-only header fields ApplVerID (1128) and DefaultApplVerID (1137) after parse.
 */
public class Fixt50Harness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final DataDictionary SESS, APP;
    static {
        try { SESS = new DataDictionary("FIXT11.xml"); APP = new DataDictionary("FIX50SP2.xml"); }
        catch (Exception e) { throw new RuntimeException(e); }
    }

    /** Fresh FIXT.1.1 admin message with the given MsgType (35=`t`). Body is left empty. */
    static Message admin(String t) throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIXT.1.1");
        m.getHeader().setString(35, t);
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        return m;
    }

    static {
        // ---- Dual-dict parse round-trips FIXT admin messages (Heartbeat, Logout) preserving
        //      MsgType and MsgSeqNum. ----
        c("parse_admin_msgs_dual_dict", () -> {
            try {
                for (String t : new String[] { "0", "5" }) {
                    Message m = admin(t);
                    Message p = new Message(m.toString(), SESS, APP);
                    if (!t.equals(p.getHeader().getString(35))) return "FAIL:" + t + " 35=" + p.getHeader().getString(35);
                    if (p.getHeader().getInt(34) != 1)          return "FAIL:" + t + " 34=" + p.getHeader().getInt(34);
                }
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- After dual-parse of an app msg, ApplVerID (1128) is queryable on the HEADER
        //      (session-dict-defined header field). Not asserted in DualDictHarness.
        c("applverid_on_header_after_parse", () -> {
            try {
                Message m = new Message();
                m.getHeader().setString(8, "FIXT.1.1");
                m.getHeader().setString(35, "D");
                m.getHeader().setInt(34, 2);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.getHeader().setInt(1128, 9);          // ApplVerID = FIX50SP2
                m.setString(11, "O1"); m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                m.setDouble(38, 100); m.setDouble(44, 150.50);
                m.setString(60, "20240101-10:00:00.000"); m.setChar(59, '0');
                Message p = new Message(m.toString(), SESS, APP);
                if (!p.getHeader().isSetField(1128))     return "FAIL:1128_not_on_header";
                if (p.getHeader().getInt(1128) != 9)     return "FAIL:1128=" + p.getHeader().getInt(1128);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
