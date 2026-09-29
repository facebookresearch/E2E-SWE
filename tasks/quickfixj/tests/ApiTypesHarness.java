import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- RejectLogon constructor + getter behaviour.
 */
public class ApiTypesHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // ---- All 4 RejectLogon constructors + both getters:
        //      no-arg / 1-arg / 2-arg keep the documented defaults; only the 4-arg can set
        //      logoutBeforeDisconnect=false. ----
        c("reject_logon_all_constructor_variants", () -> {
            try {
                RejectLogon r0 = new RejectLogon();
                if (r0.getSessionStatus() != -1 || r0.getMessage() != null || !r0.isLogoutBeforeDisconnect())
                                                                                    return "FAIL:0arg status=" + r0.getSessionStatus() + " msg=" + r0.getMessage() + " lbd=" + r0.isLogoutBeforeDisconnect();
                RejectLogon r1 = new RejectLogon("bad");
                if (!"bad".equals(r1.getMessage()) || r1.getSessionStatus() != -1 || !r1.isLogoutBeforeDisconnect())
                                                                                    return "FAIL:1arg";
                RejectLogon r2 = new RejectLogon("bad-creds", 5);
                if (!"bad-creds".equals(r2.getMessage()) || r2.getSessionStatus() != 5 || !r2.isLogoutBeforeDisconnect())
                                                                                    return "FAIL:2arg";
                RejectLogon rt = new RejectLogon("m", true, 5);
                RejectLogon rf = new RejectLogon("m", false, 5);
                if (!rt.isLogoutBeforeDisconnect())                                 return "FAIL:4arg_true_became_false";
                if (rf.isLogoutBeforeDisconnect())                                  return "FAIL:4arg_false_became_true";
                if (rf.getSessionStatus() != 5)                                     return "FAIL:4arg_status=" + rf.getSessionStatus();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
