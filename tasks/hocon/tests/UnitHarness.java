import com.lattice.config.*;

import java.math.BigInteger;
import java.time.Duration;
import java.time.Period;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

/**
 * WRG test harness — the units format: durations (getDuration/getNanoseconds), periods (getPeriod),
 * and sizes in bytes (getBytes/getMemorySize). The hard, easy-to-get-wrong contract is the
 * size-unit family: single-letter and `Ki`/`KiB` prefixes are powers of TWO (1024) while `kB`/
 * `kilobyte` are powers of TEN (1000); duration units are case-sensitive lowercase. Bad units/
 * numbers and overflow/negative sizes raise BadValue.
 *
 * Design: one bundled case per unit family / behavior, joining several exact conversions with '|'.
 */
public class UnitHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static long dur(String v, TimeUnit u) { return ConfigFactory.parseString("x=" + v).getDuration("x", u); }
    static long bytes(String v) { return ConfigFactory.parseString("x=" + v).getBytes("x"); }

    static {
        // ---- Duration: many spellings of "1 second" all equal 1000 ms / 1e9 ns ----
        c("duration_one_second_forms", () -> {
            String[] forms = {"1s", "1 s", "1second", "1 seconds", "1000ms", "1000 milliseconds",
                              "1000000us", "1000000000ns", "1000"};
            StringBuilder sb = new StringBuilder();
            for (String v : forms) {
                if (sb.length() > 0) sb.append("|");
                sb.append(dur(v, TimeUnit.MILLISECONDS));
            }
            return sb.toString();  // expect all 1000
        });

        // ---- Duration: bare number is milliseconds; unit conversion across TimeUnits ----
        c("duration_unit_conversion", () -> {
            return "s_as_ms=" + dur("2s", TimeUnit.MILLISECONDS)
                 + "|s_as_ns=" + dur("2s", TimeUnit.NANOSECONDS)
                 + "|m_as_s=" + dur("3m", TimeUnit.SECONDS)
                 + "|h_as_m=" + dur("2h", TimeUnit.MINUTES)
                 + "|d_as_h=" + dur("1d", TimeUnit.HOURS)
                 + "|bareMs=" + dur("500", TimeUnit.MILLISECONDS);
        });

        // ---- Duration: 1d edge (a value that is also a valid double) and getNanoseconds/Milliseconds ----
        c("duration_one_day", () -> {
            Config a = ConfigFactory.parseString("x = 1d");
            return "days=" + a.getDuration("x", TimeUnit.DAYS)
                 + "|ns=" + a.getDuration("x", TimeUnit.NANOSECONDS)
                 + "|ms=" + a.getDuration("x", TimeUnit.MILLISECONDS);
        });

        // ---- Duration: getDuration(String) as java.time.Duration ----
        c("duration_java_time", () -> {
            Duration d = ConfigFactory.parseString("x = 90s").getDuration("x");
            Duration h = ConfigFactory.parseString("x = 1.5h").getDuration("x");
            return "d90s_seconds=" + d.getSeconds()
                 + "|h_minutes=" + h.toMinutes();
        });

        // ---- Duration: bad unit and malformed number both raise BadValue ----
        c("duration_errors", () -> {
            return "badUnit=" + ex(() -> dur("100 dollars", TimeUnit.MILLISECONDS))
                 + "|badNum=" + ex(() -> dur("1 00 seconds", TimeUnit.MILLISECONDS));
        });

        // ---- Size: powers of TWO — single-letter + Ki/KiB/mebibyte families equal 1048576 ----
        c("size_binary_1Mi", () -> {
            String[] forms = {"1048576", "1048576b", "1048576 bytes", "1024k", "1024K", "1024Ki",
                              "1024KiB", "1024 kibibytes", "1m", "1M", "1Mi", "1MiB", "1 mebibytes"};
            StringBuilder sb = new StringBuilder();
            for (String v : forms) {
                if (sb.length() > 0) sb.append("|");
                sb.append(bytes(v));
            }
            return sb.toString();  // expect all 1048576
        });

        // ---- Size: powers of TEN — kB / MB / kilobyte families equal 1000000 ----
        c("size_si_1MB", () -> {
            String[] forms = {"1000000", "1000kB", "1000 kilobytes", "1MB", "1 megabytes"};
            StringBuilder sb = new StringBuilder();
            for (String v : forms) {
                if (sb.length() > 0) sb.append("|");
                sb.append(bytes(v));
            }
            return sb.toString();  // expect all 1000000
        });

        // ---- Size: single byte units and fractional values ----
        c("size_bytes_and_fraction", () -> {
            return "b1=" + bytes("1B") + "|b2=" + bytes("10 bytes")
                 + "|halfM=" + bytes("0.5M")     // 524288
                 + "|halfMB=" + bytes("0.5MB");   // 500000
        });

        // ---- Size: getMemorySize + huge (yottabyte) via BigInteger ----
        c("size_memorysize_bigint", () -> {
            ConfigMemorySize ms = ConfigFactory.parseString("x = 1M").getMemorySize("x");
            BigInteger yb = ConfigFactory.parseString("x = 1YB").getMemorySize("x").toBytesBigInteger();
            return "oneM=" + ms.toBytes()
                 + "|yb=" + yb.toString();
        });

        // ---- Size: overflow and negative raise BadValue ----
        c("size_errors", () -> {
            return "badUnit=" + ex(() -> bytes("100 dollars"))
                 + "|overflow=" + ex(() -> bytes("1000 exabytes"))
                 + "|negative=" + ex(() -> bytes("-1 GiB"));
        });

        // ---- Period: many spellings of "1 year" (in days) via getPeriod ----
        c("period_one_year_forms", () -> {
            String[] forms = {"1y", "1 year", "1 years", "365", "365d", "365 days", "12m", "12mo", "12 months"};
            StringBuilder sb = new StringBuilder();
            for (String v : forms) {
                Period p = ConfigFactory.parseString("x=" + v).getPeriod("x");
                if (sb.length() > 0) sb.append("|");
                sb.append(p.getYears() + "y" + p.getMonths() + "mo" + p.getDays() + "d");
            }
            return sb.toString();
        });

        // ---- Period: distinct units — days / weeks / months / years kept separate ----
        c("period_units", () -> {
            Period d = ConfigFactory.parseString("x = 10d").getPeriod("x");
            Period w = ConfigFactory.parseString("x = 3w").getPeriod("x");
            Period mo = ConfigFactory.parseString("x = 5 months").getPeriod("x");
            Period y = ConfigFactory.parseString("x = 8y").getPeriod("x");
            return "d=" + d.getDays() + "|w_days=" + w.getDays()
                 + "|mo=" + mo.getMonths() + "|y=" + y.getYears();
        });

        // ---- getDurationList / getBytesList / getMemorySizeList over a list of unit strings ----
        c("unit_lists", () -> {
            List<Long> durs = ConfigFactory.parseString("x = [1s, 2s, 500ms]").getDurationList("x", TimeUnit.MILLISECONDS);
            List<Long> szs = ConfigFactory.parseString("x = [1K, 1kB, 1M]").getBytesList("x");
            List<ConfigMemorySize> msz = ConfigFactory.parseString("x = [1024, 1M, 1G]").getMemorySizeList("x");
            StringBuilder mb = new StringBuilder();
            for (ConfigMemorySize m : msz) { if (mb.length() > 0) mb.append(","); mb.append(m.toBytes()); }
            return "durs=" + durs + "|sizes=" + szs + "|memSizes=[" + mb + "]";
        });

        // ---- getTemporal disambiguates `m` (minutes -> Duration) from `mo` (months -> Period) ----
        c("temporal_m_vs_mo", () -> {
            java.time.temporal.TemporalAmount min = ConfigFactory.parseString("x = 5m").getTemporal("x");
            java.time.temporal.TemporalAmount mon = ConfigFactory.parseString("x = 5mo").getTemporal("x");
            return "m_isDuration=" + (min instanceof java.time.Duration)
                 + "|m_seconds=" + ((java.time.Duration) min).getSeconds()
                 + "|mo_isPeriod=" + (mon instanceof java.time.Period)
                 + "|mo_months=" + ((java.time.Period) mon).getMonths();
        });

        // ---- getDuration(String) with a fractional-minute string and a bare-number-as-ms ----
        c("duration_fractional_and_bare", () -> {
            return "half_min_ms=" + dur("0.5m", TimeUnit.MILLISECONDS)   // 30000
                 + "|quarter_hour_min=" + dur("0.25h", TimeUnit.MINUTES) // 15
                 + "|bare_as_seconds=" + dur("5000", TimeUnit.SECONDS);  // 5000ms -> 5s
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
