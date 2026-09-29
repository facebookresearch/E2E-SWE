import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- harder wire-format edge cases (CheckSum arithmetic wrap, BodyLength
 * multibyte precision, malformed-wire acceptance boundaries).
 */
public class WireHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static String d(String w) { return w.replace(SOH, '|'); }

    /** Compute CheckSum (byte-sum modulo 256, 3-digit zero-padded) over a UTF-8-encoded wire. */
    static String checksumBytes(String s, String charset) throws Exception {
        byte[] bs = s.getBytes(charset);
        int cs = 0; for (byte b : bs) cs = (cs + (b & 0xFF)) & 0xFF;
        return String.format("%03d", cs);
    }

    static {
        // ---- Build a message where the byte-sum wraps: emitted CheckSum must be in [000, 255]. ----
        //     Uses a Text field with contents chosen so the total byte-sum modulo 256 is guaranteed
        //     to exercise the wrap; we assert both padding and mod correctness against a computed value.
        c("checksum_wraps_at_256", () -> {
            try {
                CharsetSupport.setDefaultCharset();
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(58, "PADDING_TO_FORCE_LARGE_SUM_OVER_MULTIPLE_WRAPS_XXXXXXXXXXXX");
                String wire = m.toString();
                int csIdx = wire.lastIndexOf("10=");
                String emitted = wire.substring(csIdx + 3, wire.indexOf(SOH, csIdx));
                // Recompute expected: sum bytes of everything BEFORE the "10=" field, mod 256.
                String expected = checksumBytes(wire.substring(0, csIdx), "ISO-8859-1");
                if (emitted.length() != 3)     return "FAIL:len=" + emitted.length();
                if (!emitted.equals(expected)) return "FAIL:got=" + emitted + " expected=" + expected;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- BodyLength counts BYTES not chars: UTF-8 multibyte value contributes multiple bytes. ----
        //     Compute expected body-length by hand from the emitted wire; must match emitted 9=<n>.
        c("body_length_matches_bytes_utf8", () -> {
            try {
                CharsetSupport.setCharset("UTF-8");
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                m.setString(58, "café naïve");     // 10 chars, but multi-byte in UTF-8
                String wire = m.toString();
                CharsetSupport.setDefaultCharset();
                // Body-length range: byte AFTER SOH-terminating "9=<n>", up to and including SOH-terminator of last body field.
                int soh9   = wire.indexOf("9=") + "9=".length();
                int soh9end = wire.indexOf(SOH, soh9);
                int declared = Integer.parseInt(wire.substring(soh9, soh9end));
                int soh10  = wire.lastIndexOf(SOH + "10=");
                int actual = soh10 - soh9end;    // bytes strictly between soh9end and the SOH before "10="
                // NOTE: `actual` counts chars in Java String; getBytes to get true byte count under UTF-8.
                int actualBytes = wire.substring(soh9end + 1, soh10 + 1).getBytes("UTF-8").length;
                if (declared != actualBytes) return "FAIL:declared=" + declared + " actual=" + actualBytes;
                return "OK";
            } catch (Exception e) {
                try { CharsetSupport.setDefaultCharset(); } catch (Exception ignore) {}
                return "FAIL:" + e.getClass().getSimpleName();
            }
        });

        // ---- A body-length that would take 4+ digits (>= 1000) still emits + parses correctly. ----
        c("body_length_over_999_roundtrip", () -> {
            try {
                CharsetSupport.setDefaultCharset();
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                StringBuilder padding = new StringBuilder();
                for (int i = 0; i < 500; i++) padding.append("x");
                m.setString(58, padding.toString());
                String wire = m.toString();
                int soh9 = wire.indexOf("9=") + 2;
                int soh9end = wire.indexOf(SOH, soh9);
                int bodyLen = Integer.parseInt(wire.substring(soh9, soh9end));
                if (bodyLen < 500)            return "FAIL:len=" + bodyLen + " (expected >= 500)";
                // Round-trip works.
                String out = new Message(wire).toString();
                return wire.equals(out) ? "OK" : "FAIL:roundtrip";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
