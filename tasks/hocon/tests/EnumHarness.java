import com.lattice.config.*;

import java.time.DayOfWeek;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — enum access (getEnum / getEnumList). Kept as its own driver (separate from
 * checkValid) so that a gap in the validation API cannot cascade onto the enum cases: per the
 * split-by-capability design, a missing symbol only zeroes its own small driver.
 */
public class EnumHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static Config r(String s) { return ConfigFactory.parseString(s).resolve(); }

    static {
        // ---- getEnum reads an enum constant by name; an unknown name -> BadValue ----
        c("get_enum", () -> {
            Config a = r("day = MONDAY\nbad = NOTADAY");
            return "day=" + a.getEnum(DayOfWeek.class, "day")
                 + "|bad=" + ex(() -> a.getEnum(DayOfWeek.class, "bad"));
        });

        // ---- getEnumList reads a list of enum constants ----
        c("get_enum_list", () -> {
            Config a = r("days = [MONDAY, FRIDAY, SUNDAY]");
            return "days=" + a.getEnumList(DayOfWeek.class, "days");
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
