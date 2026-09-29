// Grading harness for the jq processor task.
//
// Loads the agent's engine -- class `com.wrg.jq.JqEngine` with
//   public String evaluate(String program, String inputJson)
// where `inputJson` is the JSON text of the single input value the program runs against (the `.`).
// The method returns the program's output value stream serialized as compact JSON, one output value
// per line joined by '\n' (i.e. `jq -c`), or the exact string "ERROR" if the program raises any
// compile-time or run-time error. It runs every case in the baked corpus (cases.dat, length-prefixed:
// program, input, expected) with a per-case timeout, comparing the returned string to the expected one
// (tolerating trailing newlines). One case = one JSONL result line.
//
// Robustness (same rationale as the sibling tasks): a submitted engine can contain an *uninterruptible*
// infinite loop / unbounded generator on some input. We (1) run each case on its own daemon thread from
// a cached pool, so a hung case is abandoned rather than blocking every later case; (2) construct a
// fresh engine per case; and (3) enforce an overall wall-clock budget -- once exceeded we stop launching
// cases so a CTRF is still written within the verifier's timeout (make_ctrf pads the remainder as
// failed) instead of the container being killed with no results (a spurious 0). Results flush per line.
//
// Usage: java Harness <cases.dat> <out.jsonl> [per_case_timeout_ms] [overall_budget_ms]

import java.io.*;
import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

public class Harness {

    static int readIntLine(InputStream in) throws IOException {
        int c = in.read();
        if (c == -1) return Integer.MIN_VALUE;               // EOF
        StringBuilder sb = new StringBuilder();
        while (c != -1 && c != '\n') { sb.append((char) c); c = in.read(); }
        return Integer.parseInt(sb.toString().trim());
    }

    static String readBytes(InputStream in, int n) throws IOException {
        byte[] b = new byte[n];
        int off = 0;
        while (off < n) {
            int r = in.read(b, off, n - off);
            if (r == -1) throw new EOFException();
            off += r;
        }
        return new String(b, StandardCharsets.UTF_8);
    }

    static String stripTrailNl(String s) {
        if (s == null) return null;
        int e = s.length();
        while (e > 0 && s.charAt(e - 1) == '\n') e--;
        return s.substring(0, e);
    }

    static String esc(String s) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"': b.append("\\\""); break;
                case '\\': b.append("\\\\"); break;
                case '\n': b.append("\\n"); break;
                case '\r': b.append("\\r"); break;
                case '\t': b.append("\\t"); break;
                default: if (c < 0x20 || c > 0x7E) b.append(String.format("\\u%04x", (int) c)); else b.append(c);
            }
        }
        return b.toString();
    }

    public static void main(String[] args) throws Exception {
        String casesPath = args[0], outPath = args[1];
        long timeoutMs = args.length > 2 ? Long.parseLong(args[2]) : 8000;
        long overallBudgetMs = args.length > 3 ? Long.parseLong(args[3]) : 1500000L;
        long deadlineNanos = System.nanoTime() + overallBudgetMs * 1_000_000L;

        final Class<?> cls = Class.forName("com.wrg.jq.JqEngine");
        final Constructor<?> ctor = cls.getDeclaredConstructor();
        final Method fn = cls.getMethod("evaluate", String.class, String.class);

        final AtomicInteger tnum = new AtomicInteger();
        ExecutorService exec = Executors.newCachedThreadPool(r -> {
            Thread t = new Thread(r, "case-worker-" + tnum.incrementAndGet());
            t.setDaemon(true);
            return t;
        });

        BufferedInputStream in = new BufferedInputStream(new FileInputStream(casesPath));
        int n = 0, budgetSkipped = 0;
        try (PrintWriter out = new PrintWriter(new OutputStreamWriter(
                new FileOutputStream(outPath), StandardCharsets.UTF_8), true)) {   // autoflush per line
            while (true) {
                int pLen = readIntLine(in);
                if (pLen == Integer.MIN_VALUE) break;         // EOF
                final String program = readBytes(in, pLen);
                int iLen = readIntLine(in);
                final String input = readBytes(in, iLen);
                int expLen = readIntLine(in);
                String expected = readBytes(in, expLen);
                n++;

                if (System.nanoTime() > deadlineNanos) { budgetSkipped++; continue; }

                String slug = program.replaceAll("\\s+", " ");
                String name = "case-" + n + "-" + (slug.length() > 60 ? slug.substring(0, 60) : slug);

                boolean ok = false; String msg = "";
                Future<String> fut = exec.submit(() -> {
                    Object engine = ctor.newInstance();
                    return (String) fn.invoke(engine, program, input);
                });
                try {
                    String got = fut.get(timeoutMs, TimeUnit.MILLISECONDS);
                    ok = stripTrailNl(expected).equals(stripTrailNl(got));
                    if (!ok) msg = "expected <<" + expected.replace("\n", "\\n")
                            + ">> got <<" + (got == null ? "null" : got.replace("\n", "\\n")) + ">>";
                } catch (TimeoutException te) {
                    fut.cancel(true); msg = "timed out";
                } catch (Throwable e) {
                    Throwable cc = (e instanceof ExecutionException && e.getCause() != null) ? e.getCause() : e;
                    msg = "threw " + cc.getClass().getSimpleName() + ": " + String.valueOf(cc.getMessage());
                }
                out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"" + (ok ? "passed" : "failed")
                        + "\",\"message\":\"" + esc(msg.length() > 220 ? msg.substring(0, 220) : msg) + "\"}");
            }
        }
        exec.shutdownNow();
        if (budgetSkipped > 0)
            System.err.println("Harness overall budget (" + overallBudgetMs + "ms) exceeded; "
                    + budgetSkipped + " remaining cases left unrun (make_ctrf pads them as failed).");
    }
}
