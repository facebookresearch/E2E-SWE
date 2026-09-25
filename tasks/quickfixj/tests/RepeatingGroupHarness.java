import io.fix.*;

import java.util.List;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- repeating groups (self-asserting).
 */
public class RepeatingGroupHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static String d(String wire) { return wire.replace(SOH, '|'); }

    static Message buildSnapshot(int n) throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, "W");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "S");
        m.getHeader().setString(56, "T");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.setString(55, "AAPL");
        for (int i = 0; i < n; i++) {
            Group g = new Group(268, 269);
            g.setChar(269, (char) ('0' + i));
            g.setDouble(270, 150.0 + i * 0.10);
            m.addGroup(g);
        }
        return m;
    }

    static {
        c("add_and_count", () -> {
            try {
                Message m = buildSnapshot(3);
                if (m.getGroupCount(268) != 3)     return "FAIL:count=" + m.getGroupCount(268);
                if (m.getGroups(268).size() != 3)  return "FAIL:size=" + m.getGroups(268).size();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        c("get_group_by_index", () -> {
            try {
                Message m = buildSnapshot(3);
                if (m.getGroup(1, new Group(268, 269)).getChar(269) != '0') return "FAIL:1st.269 wrong";
                if (m.getGroup(3, new Group(268, 269)).getChar(269) != '2') return "FAIL:3rd.269 wrong";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        c("parse_with_dict_reconstructs_group", () -> {
            try {
                DataDictionary dd = new DataDictionary("FIX44.xml");
                Message parsed = new Message(buildSnapshot(3).toString(), dd);
                if (parsed.getGroupCount(268) != 3)                                return "FAIL:count=" + parsed.getGroupCount(268);
                List<Group> gs = parsed.getGroups(268);
                if (gs.size() != 3)                                                return "FAIL:size=" + gs.size();
                if (gs.get(0).getChar(269) != '0' || gs.get(2).getChar(269) != '2') return "FAIL:entries";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        c("parse_no_dict_no_group_reconstruction", () -> {
            try {
                int count = new Message(buildSnapshot(3).toString()).getGroupCount(268);
                return count == 0 ? "OK" : "FAIL:count=" + count;
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
