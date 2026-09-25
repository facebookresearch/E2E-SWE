import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- CharsetSupport and its effect on BodyLength byte counts (self-asserting).
 */
public class CharsetHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;

    static Message textMsg(String text) throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, "0");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.setString(58, text);
        return m;
    }

    static int extractBodyLength(String wire) {
        int i = wire.indexOf(SOH + "9=") + 3;
        int j = wire.indexOf(SOH, i);
        return Integer.parseInt(wire.substring(i, j));
    }

    static {
        // ---- Default charset is ISO-8859-1; setCharset changes it; setDefaultCharset restores. ----
        c("charset_default_set_and_reset", () -> {
            try {
                CharsetSupport.setDefaultCharset();
                if (!"ISO-8859-1".equals(CharsetSupport.getCharset()))
                                                                     return "FAIL:default got=" + CharsetSupport.getCharset();
                CharsetSupport.setCharset("UTF-8");
                if (!"UTF-8".equals(CharsetSupport.getCharset())) return "FAIL:set didn't stick";
                CharsetSupport.setDefaultCharset();
                if (!"ISO-8859-1".equals(CharsetSupport.getCharset())) return "FAIL:reset didn't restore";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Charset switch between two serialisations of the same Message produces different
        //      BodyLengths: UTF-8 body-length > ISO-8859-1 body-length by exactly the multibyte
        //      overhead. Tests that BodyLength is recomputed against the current charset each
        //      time, not cached from an earlier serialise call. ----
        c("charset_switch_body_length_recomputes_correctly", () -> {
            try {
                CharsetSupport.setCharset("UTF-8");
                int utfLen = extractBodyLength(textMsg("café").toString());
                CharsetSupport.setDefaultCharset();
                int isoLen = extractBodyLength(textMsg("café").toString());
                if (utfLen <= isoLen)                                        return "FAIL:utf=" + utfLen + " iso=" + isoLen + " (expected utf > iso)";
                if (utfLen - isoLen != 1)                                    return "FAIL:delta=" + (utfLen - isoLen) + " (expected 1 for é)";
                return "OK";
            } catch (Exception e) {
                try { CharsetSupport.setDefaultCharset(); } catch (Exception ignore) {}
                return "FAIL:" + e.getClass().getSimpleName();
            }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
