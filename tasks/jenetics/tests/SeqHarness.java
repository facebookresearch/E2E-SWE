import io.evolab.stat.*;
import io.evolab.util.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.stream.*;

/**
 * WRG test harness — jenetics Seq / util data structures (io.evolab.util ISeq / MSeq / Seq).
 *
 * Isolated into its own driver because these cases lean on the fragile idioms Seq.toString(String)
 * and the static ISeq.toISeq() collector — a signature mismatch on those must not compile-wipe the
 * moment-statistics cases (now in MomentStatHarness). Self-contained: its own imports; these cases
 * need no custom helpers. Case bodies are verbatim. Runner is shared.
 */
public class SeqHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // ---- ISeq: construction + length + get + map (transform) bundled ----
        // ISeq.of(1,2,3,4) -> length 4, get(2)=3; map(x->x*x) -> [1,4,9,16].
        c("stat_iseq_build_map", () -> {
            ISeq<Integer> s = ISeq.of(1, 2, 3, 4);
            ISeq<Integer> sq = s.map(x -> x * x);
            return s.length() + "|" + s.get(2) + "|" + sq.toString(",");
            // 4|3|1,4,9,16
        });
        // ---- Seq membership: contains + indexOf bundled ----
        c("stat_seq_membership", () -> {
            ISeq<Integer> s = ISeq.of(10, 20, 30, 40);
            return s.contains(30) + "|" + s.indexOf(40) + "|" + s.indexOf(99);
            // true|3|-1
        });

        // ---- MSeq mutation: set + sort -> resulting order ----
        // set(1,99) then sort() ascending; also verify toISeq() snapshot length/get.
        c("stat_mseq_mutate", () -> {
            MSeq<Integer> s = MSeq.of(3, 1, 4, 1, 5);
            s.set(1, 99);          // {3,99,4,1,5}
            s.sort();              // {1,3,4,5,99}
            ISeq<Integer> frozen = s.toISeq();
            return s.toString(",") + "|" + frozen.length() + "|" + frozen.get(4);
            // 1,3,4,5,99|5|99
        });

        // ---- Seq -> ISeq collector: toISeq() over a Stream ----
        c("stat_seq_collector", () -> {
            ISeq<Integer> s = Stream.of(1, 2, 3, 4, 5).collect(ISeq.toISeq());
            return s.length() + "|" + s.get(4) + "|" + s.asList().toString();
            // 5|5|[1, 2, 3, 4, 5]
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
