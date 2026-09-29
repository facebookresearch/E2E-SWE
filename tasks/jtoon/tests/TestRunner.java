package wrg.hidden;

import java.io.File;
import java.io.FileWriter;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import org.junit.platform.engine.TestExecutionResult;
import org.junit.platform.engine.discovery.DiscoverySelectors;
import org.junit.platform.launcher.Launcher;
import org.junit.platform.launcher.LauncherDiscoveryRequest;
import org.junit.platform.launcher.TestExecutionListener;
import org.junit.platform.launcher.TestIdentifier;
import org.junit.platform.launcher.core.LauncherDiscoveryRequestBuilder;
import org.junit.platform.launcher.core.LauncherFactory;

/**
 * Standalone JUnit 5 runner for the hidden JToon suite -- no Gradle, no console launcher, no
 * Python. Discovers and executes {@code wrg.hidden.JToonTest}, collects per-test results, and
 * writes a CTRF-format JSON report to the path in args[0]. Exits non-zero if any test failed,
 * was skipped, or if zero tests ran, so test.sh can derive the reward from the exit code.
 *
 * CTRF schema (the WRG grader reads results.summary.{tests,passed,failed} and results.tests[]):
 *   {"results": {"tool": {"name": "junit5"},
 *                "summary": {"tests": N, "passed": P, "failed": F, "skipped": S,
 *                            "pending": 0, "other": 0, "start": 0, "stop": 0},
 *                "tests": [{"name": "...", "status": "passed|failed|skipped", "duration": 0,
 *                           "message": "..."}]}}
 */
public final class TestRunner {

    private TestRunner() {
    }

    private static final class Result {
        final String name;
        final String status;
        final String message;

        Result(final String name, final String status, final String message) {
            this.name = name;
            this.status = status;
            this.message = message;
        }
    }

    private static String jsonEscape(final String s) {
        final StringBuilder sb = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            final char c = s.charAt(i);
            switch (c) {
                case '\\' -> sb.append("\\\\");
                case '"' -> sb.append("\\\"");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < ' ') {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.toString();
    }

    public static void main(final String[] args) throws IOException {
        final String outPath = args.length > 0 ? args[0] : "ctrf.json";
        final List<Result> results = new ArrayList<>();

        final TestExecutionListener listener = new TestExecutionListener() {
            @Override
            public void executionFinished(final TestIdentifier id, final TestExecutionResult result) {
                if (!id.isTest()) {
                    return;
                }
                String name = id.getDisplayName();
                if (name.endsWith("()")) {
                    name = name.substring(0, name.length() - 2);
                }
                final String status = switch (result.getStatus()) {
                    case SUCCESSFUL -> "passed";
                    case ABORTED -> "skipped";
                    default -> "failed";
                };
                String msg = null;
                if (result.getThrowable().isPresent()) {
                    final Throwable t = result.getThrowable().get();
                    msg = t.getClass().getName() + ": " + (t.getMessage() == null ? "" : t.getMessage());
                }
                results.add(new Result(name, status, msg));
            }

            @Override
            public void executionSkipped(final TestIdentifier id, final String reason) {
                if (!id.isTest()) {
                    return;
                }
                String name = id.getDisplayName();
                if (name.endsWith("()")) {
                    name = name.substring(0, name.length() - 2);
                }
                results.add(new Result(name, "skipped", reason));
            }
        };

        final LauncherDiscoveryRequest req = LauncherDiscoveryRequestBuilder.request()
                .selectors(DiscoverySelectors.selectClass("wrg.hidden.JToonTest"))
                .build();
        final Launcher launcher = LauncherFactory.create();
        launcher.execute(req, listener);

        int passed = 0;
        int failed = 0;
        int skipped = 0;
        for (final Result r : results) {
            switch (r.status) {
                case "passed" -> passed++;
                case "failed" -> failed++;
                default -> skipped++;
            }
        }
        final int total = results.size();

        final StringBuilder sb = new StringBuilder();
        sb.append("{\n  \"results\": {\n");
        sb.append("    \"tool\": {\"name\": \"junit5\"},\n");
        sb.append("    \"summary\": {");
        sb.append("\"tests\": ").append(total).append(", \"passed\": ").append(passed);
        sb.append(", \"failed\": ").append(failed).append(", \"skipped\": ").append(skipped);
        sb.append(", \"pending\": 0, \"other\": 0, \"start\": 0, \"stop\": 0},\n");
        sb.append("    \"tests\": [\n");
        for (int i = 0; i < results.size(); i++) {
            final Result r = results.get(i);
            sb.append("      {\"name\": \"").append(jsonEscape(r.name)).append("\", \"status\": \"")
              .append(r.status).append("\", \"duration\": 0");
            if (r.message != null) {
                sb.append(", \"message\": \"").append(jsonEscape(r.message)).append("\"");
            }
            sb.append("}");
            sb.append(i != results.size() - 1 ? ",\n" : "\n");
        }
        sb.append("    ]\n  }\n}\n");

        final File out = new File(outPath);
        if (out.getParentFile() != null) {
            out.getParentFile().mkdirs();
        }
try (var w = new java.io.OutputStreamWriter(new java.io.FileOutputStream(out), java.nio.charset.StandardCharsets.UTF_8)) {
    w.write(sb.toString());
}
        System.out.println("CTRF -> " + outPath + ": total=" + total + " passed=" + passed
                + " failed=" + failed + " skipped=" + skipped);

        if (total == 0 || failed > 0 || skipped > 0 || passed != total) {
            System.exit(1);
        }
    }
}
