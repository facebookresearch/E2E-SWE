import java.util.*;
import java.util.function.Supplier;
import java.util.concurrent.*;
import java.io.*;

/**
 * Shared runner for the split JavaPoet harnesses. Each harness builds a LinkedHashMap of
 * case-name -> Supplier<String> (the generated Java source for that case) and calls Runner.run.
 *
 * CAPTURE=1 -> print this harness's `name<TAB>value` lines to stdout (used to regenerate the oracle
 * fixture tests/expected.tsv). Otherwise -> grade each case against /tests/expected.tsv and print
 * one JSON line per case ({"name","status","msg"}) for the CTRF bridge.
 *
 * Generated Java source is multi-line; harnesses normalise line breaks to the literal two-character
 * sequence \n (backslash + n) so every case is a single TSV line AND newline placement is graded
 * byte-exactly (distinct from spaces). See each harness's `norm` helper.
 *
 * Per-case timeout: every case runs in its own daemon thread with a hard wall-clock cap so a buggy
 * submission that loops forever fails ONLY that case instead of hanging the grader.
 */
public class Runner {
    static final long TIMEOUT_MS = 10_000;
    static final ExecutorService POOL = Executors.newCachedThreadPool(r -> {
        Thread t = new Thread(r); t.setDaemon(true); return t;
    });
    static final String TIMEOUT = " TIMEOUT ";

    /** Evaluate one case under the timeout. Returns its string value, or the TIMEOUT sentinel. */
    static String eval(Supplier<String> p) {
        Future<String> f = POOL.submit(p::get);
        try {
            return f.get(TIMEOUT_MS, TimeUnit.MILLISECONDS);
        } catch (TimeoutException te) {
            f.cancel(true);
            return TIMEOUT;
        } catch (Throwable t) {
            return "ERR:" + (t.getCause() != null ? t.getCause().getClass().getSimpleName()
                                                   : t.getClass().getSimpleName());
        }
    }

    static void run(LinkedHashMap<String, Supplier<String>> cases, String[] args) throws Exception {
        String tsv = System.getenv("EXPECTED_TSV");
        if (tsv == null) tsv = "/tests/expected.tsv";

        if ("1".equals(System.getenv("CAPTURE"))) {
            StringBuilder sb = new StringBuilder();
            for (Map.Entry<String, Supplier<String>> e : cases.entrySet()) {
                String v = eval(e.getValue());
                sb.append(e.getKey()).append('\t').append(v.replace("\n", " ")).append('\n');
            }
            System.out.print(sb);
            System.out.flush();
            System.exit(0);
        }

        Map<String, String> exp = new HashMap<>();
        try (BufferedReader r = new BufferedReader(new FileReader(tsv))) {
            String l;
            while ((l = r.readLine()) != null) {
                int t = l.indexOf('\t');
                if (t > 0) exp.put(l.substring(0, t), l.substring(t + 1));
            }
        } catch (IOException ignore) { /* missing fixture -> every case fails below */ }

        StringBuilder out = new StringBuilder();
        for (Map.Entry<String, Supplier<String>> e : cases.entrySet()) {
            String name = e.getKey(), status, msg = "";
            String a = eval(e.getValue());
            if (TIMEOUT.equals(a)) {
                status = "failed"; msg = "timed out after " + TIMEOUT_MS + "ms";
            } else {
                String x = exp.get(name);
                if (x == null) { status = "failed"; msg = "no expected fixture entry"; }
                else if (x.equals(a)) { status = "passed"; }
                else { status = "failed"; msg = "expected <" + x + "> got <" + a + ">"; }
            }
            out.append("{\"name\":\"").append(name).append("\",\"status\":\"").append(status)
               .append("\",\"msg\":\"").append(msg.replace("\\", "\\\\").replace("\"", "\\\"")).append("\"}\n");
        }
        System.out.print(out);
        System.out.flush();
        System.exit(0);   // force exit even if a timed-out daemon thread is still spinning
    }
}
