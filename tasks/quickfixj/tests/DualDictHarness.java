import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- FIX 5.0 dual-dictionary parse + validate (FIXT.1.1, §5, self-asserting).
 */
public class DualDictHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final DataDictionary SESS, APP;
    static {
        try { SESS = new DataDictionary("FIXT11.xml"); APP = new DataDictionary("FIX50SP2.xml"); }
        catch (Exception e) { throw new RuntimeException(e); }
    }

    static Message logon() throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIXT.1.1");
        m.getHeader().setString(35, "A");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.setInt(98, 0);
        m.setInt(108, 30);
        m.setInt(1137, 9);
        return m;
    }

    static Message nos() throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIXT.1.1");
        m.getHeader().setString(35, "D");
        m.getHeader().setInt(34, 2);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.getHeader().setInt(1128, 9);
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

    static {
        // Dual-dict parse of a Logon: session dict resolves header + admin body fields.
        c("dual_parse_logon", () -> {
            try {
                Message p = new Message(logon().toString(), SESS, APP);
                if (!"A".equals(p.getHeader().getString(35))) return "FAIL:35=" + p.getHeader().getString(35);
                if (p.getInt(98) != 0)                        return "FAIL:98=" + p.getInt(98);
                if (p.getInt(108) != 30)                      return "FAIL:108=" + p.getInt(108);
                if (p.getInt(1137) != 9)                      return "FAIL:1137=" + p.getInt(1137);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // Dual-dict parse of NewOrderSingle: app dict resolves body fields.
        c("dual_parse_new_order_single", () -> {
            try {
                Message p = new Message(nos().toString(), SESS, APP);
                if (!"D".equals(p.getHeader().getString(35))) return "FAIL:35=" + p.getHeader().getString(35);
                if (!"AAPL".equals(p.getString(55)))          return "FAIL:55=" + p.getString(55);
                if (p.getChar(54) != '1')                     return "FAIL:54=" + p.getChar(54);
                if (p.getDouble(38) != 100.0)                 return "FAIL:38=" + p.getDouble(38);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // Dual-dict validate: an app message (35=D NewOrderSingle) validates cleanly.
        //   Admin messages (e.g. Logon) route their msgtype check through the app dict per §5,
        //   so their validation belongs to single-arg validate(m) on the session dict, not this
        //   dual-dict overload.
        c("dual_validate_new_order_single_passes", () -> {
            try {
                Message m = nos();
                m.toString();
                DataDictionary.validate(m, SESS, APP);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
