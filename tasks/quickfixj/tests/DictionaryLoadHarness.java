import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- DataDictionary loading and version identification (self-asserting).
 */
public class DictionaryLoadHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // ---- Load each supported dictionary and verify the BeginString `version` echoes back.
        //      Note: FIX 5.0 SP2 keeps BeginString "FIX.5.0" — the standard doesn't bump for
        //      service packs. ----
        c("load_all_supported_dict_versions", () -> {
            try {
                String[][] cases = { {"FIX44.xml", "FIX.4.4"}, {"FIXT11.xml", "FIXT.1.1"},
                                     {"FIX50SP2.xml", "FIX.5.0"} };
                for (String[] tc : cases) {
                    String v = new DataDictionary(tc[0]).getVersion();
                    if (!tc[1].equals(v))                                          return "FAIL:" + tc[0] + " got=" + v;
                }
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        c("missing_dict_raises_config_error", () -> {
            try {
                new DataDictionary("no_such_dictionary_12345.xml");
                return "FAIL:no_exception";
            } catch (ConfigError e) { return "OK"; }
              catch (Exception e)   { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
