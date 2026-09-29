import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- `MessageStore` + `MemoryStoreFactory` contract from the spec javadoc.
 * These are the primitive persistence hooks Session relies on: sequence counters (per-direction,
 * starting at 1), a set/get round-trip for replay, and a `reset()` that clears both messages
 * and counters. Distinct from `SessionFlowHarness` (which exercises Session end-to-end);
 * this harness exercises the store directly so a bug in the store surfaces here in isolation.
 */
public class MessageStoreHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static MessageStore freshStore() throws Exception {
        return new MemoryStoreFactory().create(new SessionID("FIX.4.4", "S", "T"));
    }

    static {
        // ---- Fresh store: BOTH sender and target seq start at 1 (spec: "Starts at 1"). ----
        c("memory_store_seq_starts_at_1_both_directions", () -> {
            try {
                MessageStore s = freshStore();
                if (s.getNextSenderMsgSeqNum() != 1)  return "FAIL:sender=" + s.getNextSenderMsgSeqNum();
                if (s.getNextTargetMsgSeqNum() != 1)  return "FAIL:target=" + s.getNextTargetMsgSeqNum();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- incrNextSenderMsgSeqNum + incrNextTargetMsgSeqNum each advance by 1. ----
        c("memory_store_incr_advances_seq_by_1", () -> {
            try {
                MessageStore s = freshStore();
                s.incrNextSenderMsgSeqNum();
                s.incrNextSenderMsgSeqNum();
                s.incrNextTargetMsgSeqNum();
                if (s.getNextSenderMsgSeqNum() != 3) return "FAIL:sender=" + s.getNextSenderMsgSeqNum();
                if (s.getNextTargetMsgSeqNum() != 2) return "FAIL:target=" + s.getNextTargetMsgSeqNum();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- setNextSenderMsgSeqNum / setNextTargetMsgSeqNum rewrite absolutely (not deltas). ----
        c("memory_store_set_next_rewrites_seq", () -> {
            try {
                MessageStore s = freshStore();
                s.setNextSenderMsgSeqNum(42);
                s.setNextTargetMsgSeqNum(99);
                if (s.getNextSenderMsgSeqNum() != 42) return "FAIL:sender=" + s.getNextSenderMsgSeqNum();
                if (s.getNextTargetMsgSeqNum() != 99) return "FAIL:target=" + s.getNextTargetMsgSeqNum();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- set(seq, wire) + get(start, end, coll) round-trips the wire in ascending seq order. ----
        c("memory_store_set_get_roundtrip", () -> {
            try {
                MessageStore s = freshStore();
                s.set(3, "wire-3");
                s.set(1, "wire-1");
                s.set(2, "wire-2");
                List<String> out = new ArrayList<>();
                s.get(1, 3, out);
                if (out.size() != 3)              return "FAIL:size=" + out.size();
                if (!"wire-1".equals(out.get(0)) || !"wire-2".equals(out.get(1)) || !"wire-3".equals(out.get(2)))
                                                   return "FAIL:order=" + out;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- reset(): clears stored messages AND resets both counters to 1 (spec contract). ----
        c("memory_store_reset_clears_messages_and_resets_counters", () -> {
            try {
                MessageStore s = freshStore();
                s.setNextSenderMsgSeqNum(50); s.setNextTargetMsgSeqNum(50);
                s.set(10, "stale-wire");
                s.reset();
                if (s.getNextSenderMsgSeqNum() != 1) return "FAIL:sender_after_reset=" + s.getNextSenderMsgSeqNum();
                if (s.getNextTargetMsgSeqNum() != 1) return "FAIL:target_after_reset=" + s.getNextTargetMsgSeqNum();
                List<String> out = new ArrayList<>();
                s.get(1, 100, out);
                if (!out.isEmpty())                  return "FAIL:messages_after_reset=" + out;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- MemoryStoreFactory.create returns a fresh store per SessionID (isolation). ----
        c("memory_store_factory_creates_isolated_stores_per_session", () -> {
            try {
                MemoryStoreFactory f = new MemoryStoreFactory();
                MessageStore a = f.create(new SessionID("FIX.4.4", "SA", "TA"));
                MessageStore b = f.create(new SessionID("FIX.4.4", "SB", "TB"));
                if (a == b)                                                   return "FAIL:same_instance";
                a.setNextSenderMsgSeqNum(50);
                if (b.getNextSenderMsgSeqNum() != 1)                           return "FAIL:b_polluted=" + b.getNextSenderMsgSeqNum();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
