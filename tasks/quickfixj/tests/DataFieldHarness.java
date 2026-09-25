import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- length-prefixed DATA fields (self-asserting).
 */
public class DataFieldHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;

    static Message rawDataMsg(String rawValue) throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, "0");
        m.getHeader().setInt(34, 1);
        m.getHeader().setString(49, "A");
        m.getHeader().setString(56, "B");
        m.getHeader().setString(52, "20240101-10:00:00.000");
        m.setInt(95, rawValue.length());
        m.setString(96, rawValue);
        return m;
    }

    static {
        c("data_with_embedded_soh_roundtrip", () -> {
            try {
                DataDictionary dd = new DataDictionary("FIX44.xml");
                String raw = "a" + SOH + "b";
                Message parsed = new Message(rawDataMsg(raw).toString(), dd);
                String got = parsed.getString(96);
                if (got.length() != 3) return "FAIL:len=" + got.length();
                if (!got.equals(raw))  return "FAIL:content mismatch";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Length-prefixed DATA field round-trips: plain string, and zero-length payload. ----
        c("data_plain_and_zero_length_roundtrips", () -> {
            try {
                DataDictionary dd = new DataDictionary("FIX44.xml");
                Message plain = new Message(rawDataMsg("hello world").toString(), dd);
                if (!"hello world".equals(plain.getString(96))) return "FAIL:plain val=" + plain.getString(96);
                if (plain.getInt(95) != 11)                     return "FAIL:plain len=" + plain.getInt(95);
                Message empty = new Message(rawDataMsg("").toString(), dd);
                if (empty.getInt(95) != 0)                      return "FAIL:empty len=" + empty.getInt(95);
                if (!"".equals(empty.getString(96)))            return "FAIL:empty val=" + empty.getString(96);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Two length-prefixed DATA pairs in the same message: RawData(95/96) in the body
        //      + Signature(93/89) in the trailer. Both must round-trip intact, including any
        //      embedded SOH bytes. Tests that multi-pair DATA handling isn't stateful. ----
        c("data_field_two_pairs_same_message_roundtrip", () -> {
            try {
                DataDictionary dd = new DataDictionary("FIX44.xml");
                Message m = new Message();
                m.getHeader().setString(8, "FIX.4.4");
                m.getHeader().setString(35, "0");
                m.getHeader().setInt(34, 1);
                m.getHeader().setString(49, "A");
                m.getHeader().setString(56, "B");
                m.getHeader().setString(52, "20240101-10:00:00.000");
                String raw = "a" + SOH + "b";                             // body RawData with embedded SOH
                m.setInt(95, raw.length());
                m.setString(96, raw);
                String sig = "sig" + SOH + "X";                            // trailer Signature with embedded SOH
                m.getTrailer().setInt(93, sig.length());
                m.getTrailer().setString(89, sig);
                Message parsed = new Message(m.toString(), dd);
                if (!raw.equals(parsed.getString(96)))                    return "FAIL:96=" + parsed.getString(96);
                if (!sig.equals(parsed.getTrailer().getString(89)))       return "FAIL:89=" + parsed.getTrailer().getString(89);
                if (parsed.getInt(95) != raw.length())                    return "FAIL:95=" + parsed.getInt(95);
                if (parsed.getTrailer().getInt(93) != sig.length())       return "FAIL:93=" + parsed.getTrailer().getInt(93);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- All-SOH DATA value: distinct boundary from data_with_embedded_soh_roundtrip's
        //      'a<SOH>b'. Per section 1 the parser must consume exactly LENGTH bytes "(SOH bytes
        //      included)"; a length-aware parser that also trims boundary control bytes (e.g. Java
        //      String.trim(), which drops every char <= 0x20 incl. SOH) passes 'a<SOH>b' yet decodes
        //      '<SOH><SOH><SOH>' to empty -- only this case catches that. ----
        c("data_multiple_embedded_soh", () -> {
            try {
                DataDictionary dd = new DataDictionary("FIX44.xml");
                String raw = "" + SOH + SOH + SOH;
                String got = new Message(rawDataMsg(raw).toString(), dd).getString(96);
                if (got.length() != 3)                          return "FAIL:len=" + got.length();
                if (!got.chars().allMatch(c -> c == SOH))       return "FAIL:not all SOH";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
