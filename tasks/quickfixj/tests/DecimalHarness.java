import io.fix.*;

import java.math.BigDecimal;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- BigDecimal precision APIs on FieldMap for Price/PriceOffset/Qty/Amt
 * (FIX float types). These values need exact-precision handling for money-sensitive systems;
 * setDouble/getDouble goes through Java double (subject to floating-point rounding), whereas
 * setDecimal/getDecimal goes through BigDecimal (scaled-radix representation, exact).
 */
public class DecimalHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // ---- BigDecimal round-trip preserves exact value (the classic 0.1 + 0.2 == 0.3 check
        //      that would fail with double due to floating-point rounding). ----
        c("fieldmap_decimal_preserves_precision", () -> {
            try {
                Message m = new Message();
                BigDecimal exact = new BigDecimal("0.1").add(new BigDecimal("0.2"));   // = "0.3" exactly
                m.setDecimal(44, exact);
                BigDecimal got = m.getDecimal(44);
                if (got.compareTo(new BigDecimal("0.3")) != 0) return "FAIL:got=" + got.toPlainString();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- getOptionalDecimal: present when tag is set; empty when absent (no throw). ----
        c("fieldmap_getOptionalDecimal_present_and_empty", () -> {
            try {
                Message m = new Message();
                Optional<BigDecimal> absent = m.getOptionalDecimal(44);
                if (absent.isPresent())                                     return "FAIL:absent_present";
                m.setDecimal(44, new BigDecimal("150.50"));
                Optional<BigDecimal> present = m.getOptionalDecimal(44);
                if (!present.isPresent())                                    return "FAIL:present_absent";
                if (present.get().compareTo(new BigDecimal("150.50")) != 0) return "FAIL:val=" + present.get();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- setDouble with padding: emitted string has exactly `padding` trailing decimals. ----
        c("fieldmap_setDouble_padding_writes_trailing_zeros", () -> {
            try {
                Message m = new Message();
                m.setDouble(44, 150.5, 4);
                String s = m.getString(44);
                // padding=4 means 4 decimals -> "150.5000"
                if (!"150.5000".equals(s))                                   return "FAIL:got=" + s;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- setDecimal with padding: same effect for BigDecimal path. ----
        c("fieldmap_setDecimal_padding_writes_trailing_zeros", () -> {
            try {
                Message m = new Message();
                m.setDecimal(44, new BigDecimal("150.5"), 4);
                String s = m.getString(44);
                if (!"150.5000".equals(s))                                   return "FAIL:got=" + s;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
