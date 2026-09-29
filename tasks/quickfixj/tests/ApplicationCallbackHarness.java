import io.fix.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.function.Consumer;
import java.time.*;
import java.time.format.DateTimeFormatter;

/**
 * WRG test harness -- Application-interface contracts: callback ordering, mutation semantics,
 * exception effects, and per-callback message-content visibility. These are the primary
 * integration points user code has with Session (per §5 of the spec).
 *
 * Every case wires a real Session against a MockApp + MockResponder on the INITIATOR side.
 * The tests assert what user code SEES via Application callbacks — not what internal wire
 * bytes look like.
 */
public class ApplicationCallbackHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyyMMdd-HH:mm:ss.SSS").withZone(ZoneOffset.UTC);
    static final DataDictionary DD;
    static { try { DD = new DataDictionary("FIX44.xml"); } catch (Exception e) { throw new RuntimeException(e); } }
    static String nowStamp() { return TS.format(Instant.now()); }

    static class RecordingApp implements Application {
        /** Structured event log: each entry is "callback:msgtype|body:key=value|..." */
        List<String> events = new ArrayList<>();
        /** Snapshot of each inbound message's fields per callback so tests can assert
         *  Application sees the full message content (not a stripped copy). */
        Map<String, Message> lastMessage = new LinkedHashMap<>();
        Consumer<Message> toAdminMutator = null;
        boolean throwDoNotSend = false;
        boolean throwUnsupported = false;
        boolean throwRejectLogonInFromAdmin = false;

        public void onCreate(SessionID id)                { events.add("onCreate"); }
        public void onLogon(SessionID id)                 { events.add("onLogon"); }
        public void onLogout(SessionID id)                { events.add("onLogout"); }
        public void toAdmin(Message m, SessionID id) {
            events.add("toAdmin:" + mt(m));
            lastMessage.put("toAdmin:" + mt(m), m);
            if (toAdminMutator != null) toAdminMutator.accept(m);
        }
        public void fromAdmin(Message m, SessionID id) throws FieldNotFound, IncorrectDataFormat, IncorrectTagValue, RejectLogon {
            events.add("fromAdmin:" + mt(m));
            lastMessage.put("fromAdmin:" + mt(m), m);
            if (throwRejectLogonInFromAdmin && "A".equals(mt(m))) throw new RejectLogon("no");
        }
        public void toApp(Message m, SessionID id) throws DoNotSend {
            events.add("toApp:" + mt(m));
            lastMessage.put("toApp:" + mt(m), m);
            if (throwDoNotSend) throw new DoNotSend();
        }
        public void fromApp(Message m, SessionID id) throws FieldNotFound, IncorrectDataFormat, IncorrectTagValue, UnsupportedMessageType {
            events.add("fromApp:" + mt(m));
            lastMessage.put("fromApp:" + mt(m), m);
            if (throwUnsupported) throw new UnsupportedMessageType();
        }
        private static String mt(Message m) { try { return m.getHeader().getString(35); } catch (Exception e) { return "?"; } }
    }
    static class MockResponder implements Responder {
        List<String> sent = new ArrayList<>();
        boolean disconnected = false;
        public boolean send(String data) { sent.add(data); return true; }
        public void disconnect() { disconnected = true; }
        public String getRemoteAddress() { return "mock"; }
    }
    static class Ctx {
        RecordingApp app; MockResponder responder; Session session; SessionID sid;
        Ctx(int hbInt) throws Exception {
            app = new RecordingApp();
            responder = new MockResponder();
            sid = new SessionID("FIX.4.4", "SENDER", "TARGET");
            session = new Session(app, new MemoryStoreFactory(), sid, hbInt);
            session.setResponder(responder);
        }
    }

    static Message inbound(String msgType, int seqNum, Consumer<Message> pop) throws Exception {
        Message m = new Message();
        m.getHeader().setString(8, "FIX.4.4");
        m.getHeader().setString(35, msgType);
        m.getHeader().setInt(34, seqNum);
        m.getHeader().setString(49, "TARGET");
        m.getHeader().setString(56, "SENDER");
        m.getHeader().setString(52, nowStamp());
        if (pop != null) pop.accept(m);
        return new Message(m.toString(), DD);
    }
    static void establishLogon(Ctx ctx) throws Exception {
        ctx.session.logon();
        ctx.session.next();
        ctx.session.next(inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); }));
        ctx.responder.sent.clear();
        ctx.app.events.clear();
        ctx.app.lastMessage.clear();
    }
    static String firstWireOfType(MockResponder r, String type) {
        for (String w : r.sent) if (w.indexOf(SOH + "35=" + type + SOH) >= 0) return w;
        return null;
    }
    static int countSentType(MockResponder r, String type) {
        int n = 0;
        for (String w : r.sent) if (w.indexOf(SOH + "35=" + type + SOH) >= 0) n++;
        return n;
    }
    static String getTagFromWire(String wire, int tag) {
        String prefix = tag + "=";
        int off;
        int i = wire.indexOf("" + SOH + prefix);
        if (i >= 0) { off = 1 + prefix.length(); }
        else if (wire.startsWith(prefix)) { i = 0; off = prefix.length(); }
        else return null;
        int j = wire.indexOf(SOH, i + off);
        return wire.substring(i + off, j);
    }
    static Message buildNos() throws Exception {
        Message d = new Message();
        d.getHeader().setString(35, "D");
        d.setString(55, "AAPL"); d.setChar(54, '1'); d.setChar(40, '2');
        d.setString(11, "O1"); d.setDouble(38, 100); d.setDouble(44, 150.50);
        d.setString(60, nowStamp()); d.setChar(59, '0');
        return d;
    }

    static {
        // ---- toAdmin fires with the outbound Logon BEFORE the wire is written; mutations to the
        //      Message (adding Username(553)/Password(554) — the credentials use case) end up on
        //      the wire. This is the documented Application.toAdmin contract. ----
        c("app_toAdmin_can_mutate_outbound_logon_before_wire", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.app.toAdminMutator = m -> {
                    if ("A".equals(safeMsgType(m))) {
                        m.setString(553, "USER"); m.setString(554, "PASS");
                    }
                };
                ctx.session.logon();
                ctx.session.next();
                String logon = firstWireOfType(ctx.responder, "A");
                if (logon == null)                                              return "FAIL:no_logon_wire";
                if (!"USER".equals(getTagFromWire(logon, 553)))                 return "FAIL:553=" + getTagFromWire(logon, 553);
                if (!"PASS".equals(getTagFromWire(logon, 554)))                 return "FAIL:554=" + getTagFromWire(logon, 554);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- toApp fires with the outbound app message and can INSPECT its user-set fields
        //      (Symbol/Side/OrderQty). Framework hasn't stamped 8/34/49/56/52 yet at this point,
        //      but the caller's own fields are all visible. ----
        c("app_toApp_receives_message_with_user_set_fields_visible", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.send(buildNos());
                Message seen = ctx.app.lastMessage.get("toApp:D");
                if (seen == null)                                               return "FAIL:no_toApp_D_captured";
                if (!"AAPL".equals(seen.getString(55)))                         return "FAIL:55=" + seen.getString(55);
                if (seen.getChar(54) != '1')                                    return "FAIL:54=" + seen.getChar(54);
                if (seen.getDouble(38) != 100.0)                                return "FAIL:38=" + seen.getDouble(38);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- fromApp receives the fully-parsed inbound app message with all body fields intact. ----
        c("app_fromApp_receives_message_with_body_fields_intact", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                Message d = inbound("D", 2, m -> {
                    m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                    m.setString(11, "MY_ORDER_123"); m.setDouble(38, 250); m.setDouble(44, 175.25);
                    m.setString(60, nowStamp()); m.setChar(59, '0');
                });
                ctx.session.next(d);
                Message seen = ctx.app.lastMessage.get("fromApp:D");
                if (seen == null)                                               return "FAIL:no_fromApp_D_captured";
                if (!"AAPL".equals(seen.getString(55)))                         return "FAIL:55=" + seen.getString(55);
                if (!"MY_ORDER_123".equals(seen.getString(11)))                 return "FAIL:11=" + seen.getString(11);
                if (seen.getDouble(38) != 250.0)                                return "FAIL:38=" + seen.getDouble(38);
                if (seen.getDouble(44) != 175.25)                               return "FAIL:44=" + seen.getDouble(44);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- fromAdmin receives the inbound admin message with header fields intact. ----
        c("app_fromAdmin_receives_message_with_header_intact", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("0", 2, null));
                Message seen = ctx.app.lastMessage.get("fromAdmin:0");
                if (seen == null)                                               return "FAIL:no_fromAdmin_0_captured";
                if (seen.getHeader().getInt(34) != 2)                            return "FAIL:34=" + seen.getHeader().getInt(34);
                if (!"TARGET".equals(seen.getHeader().getString(49)))            return "FAIL:49=" + seen.getHeader().getString(49);
                if (!"SENDER".equals(seen.getHeader().getString(56)))            return "FAIL:56=" + seen.getHeader().getString(56);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- toApp throwing DoNotSend aborts send(): returns false, no wire emitted, sender
        //      sequence does NOT advance. This is the documented contract for cancelling a send. ----
        c("app_toApp_throws_donotsend_aborts_send_and_holds_sender_seq", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.app.throwDoNotSend = true;
                int before = ctx.session.getStore().getNextSenderMsgSeqNum();
                boolean ok = ctx.session.send(buildNos());
                int after = ctx.session.getStore().getNextSenderMsgSeqNum();
                if (ok)                                                          return "FAIL:send_returned_true";
                if (countSentType(ctx.responder, "D") != 0)                      return "FAIL:D_was_sent";
                if (after != before)                                              return "FAIL:seq_advanced " + before + "->" + after;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- fromApp throwing UnsupportedMessageType: framework auto-responds to peer with
        //      BusinessMessageReject(35=j). Peer observes 35=j; the receiving Session's
        //      Application state IS advanced (from-app callback already fired). ----
        c("app_fromApp_throws_unsupported_emits_business_reject_wire", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.app.throwUnsupported = true;
                Message d = inbound("D", 2, m -> {
                    m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                    m.setString(11, "O1"); m.setDouble(38, 100); m.setDouble(44, 150.50);
                    m.setString(60, nowStamp()); m.setChar(59, '0');
                });
                ctx.session.next(d);
                if (countSentType(ctx.responder, "j") != 1)                      return "FAIL:no_35=j sent=" + ctx.responder.sent.size();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- fromAdmin throwing RejectLogon during inbound Logon aborts the session:
        //      isLoggedOn stays false, transport tears down. ----
        c("app_fromAdmin_throws_rejectlogon_aborts_session", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.app.throwRejectLogonInFromAdmin = true;
                ctx.session.logon(); ctx.session.next();
                ctx.session.next(inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); }));
                if (ctx.session.isLoggedOn())                                    return "FAIL:still_loggedOn";
                if (!ctx.responder.disconnected)                                 return "FAIL:not_disconnected";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Callback ordering — outbound Logon: toAdmin fires BEFORE the wire lands in
        //      the Responder (so mutations in toAdmin end up on the wire). ----
        c("app_toAdmin_fires_before_wire_written", () -> {
            try {
                Ctx ctx = new Ctx(30);
                java.util.List<String> order = new java.util.ArrayList<>();
                ctx.app.toAdminMutator = m -> order.add("toAdmin");
                MockResponder r2 = new MockResponder() {
                    @Override public boolean send(String data) { order.add("wire"); return super.send(data); }
                };
                ctx.session.setResponder(r2);
                ctx.session.logon();
                ctx.session.next();
                int i = order.indexOf("toAdmin"), j = order.indexOf("wire");
                if (i < 0 || j < 0)                                              return "FAIL:missing order=" + order;
                if (!(i < j))                                                    return "FAIL:toAdmin@" + i + " after wire@" + j;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Callback ordering — outbound app msg: toApp fires BEFORE send() writes the wire. ----
        c("app_toApp_fires_before_wire_written", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                java.util.List<String> order = new java.util.ArrayList<>();
                RecordingApp app2 = new RecordingApp() {
                    @Override public void toApp(Message m, SessionID id) throws DoNotSend {
                        super.toApp(m, id);
                        order.add("toApp");
                    }
                };
                MockResponder r2 = new MockResponder() {
                    @Override public boolean send(String data) { order.add("wire"); return super.send(data); }
                };
                Session s2 = new Session(app2, new MemoryStoreFactory(), ctx.sid, 30);
                s2.setResponder(r2);
                s2.logon(); s2.next();
                s2.next(inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); }));
                r2.sent.clear(); order.clear();
                s2.send(buildNos());
                int i = order.indexOf("toApp"), j = order.indexOf("wire");
                if (i < 0 || j < 0)                                              return "FAIL:missing order=" + order;
                if (!(i < j))                                                    return "FAIL:toApp@" + i + " after wire@" + j;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- onLogon fires exactly ONCE per successful Logon exchange. ----
        c("app_onLogon_fires_exactly_once_per_exchange", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                // establishLogon clears events; so onLogon fired zero times AFTER clear.
                // Trigger another Logon-processing cycle by re-establishing on a fresh session.
                Ctx ctx2 = new Ctx(30);
                ctx2.session.logon(); ctx2.session.next();
                ctx2.session.next(inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); }));
                int n = 0; for (String e : ctx2.app.events) if ("onLogon".equals(e)) n++;
                if (n != 1)                                                       return "FAIL:onLogon_count=" + n + " events=" + ctx2.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- onLogout fires exactly ONCE per Logout exchange. ----
        c("app_onLogout_fires_exactly_once_per_exchange", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("5", 2, null));
                int n = 0; for (String e : ctx.app.events) if ("onLogout".equals(e)) n++;
                if (n != 1)                                                       return "FAIL:onLogout_count=" + n + " events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Every outbound app msg fires toApp exactly once; the count of toApp events
        //      equals the count of successful send() invocations. ----
        c("app_toApp_fires_once_per_successful_send", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                for (int i = 0; i < 3; i++) ctx.session.send(buildNos());
                int n = 0; for (String e : ctx.app.events) if ("toApp:D".equals(e)) n++;
                if (n != 3)                                                       return "FAIL:toApp_count=" + n + " events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Every inbound app msg fires fromApp exactly once (framework does not double-dispatch). ----
        c("app_fromApp_fires_once_per_inbound_app_msg", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                for (int i = 0; i < 3; i++) {
                    final int seq = 2 + i;
                    ctx.session.next(inbound("D", seq, m -> {
                        m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                        m.setString(11, "O" + seq); m.setDouble(38, 100); m.setDouble(44, 150.50);
                        m.setString(60, nowStamp()); m.setChar(59, '0');
                    }));
                }
                int n = 0; for (String e : ctx.app.events) if ("fromApp:D".equals(e)) n++;
                if (n != 3)                                                       return "FAIL:fromApp_count=" + n + " events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Multiple outbound app msgs are all persisted for later replay — subsequent
        //      ResendRequest from peer replays each with PossDupFlag(43)=Y. Round-trips through
        //      MessageStore, no direct wire inspection needed. ----
        c("app_multiple_sends_all_replayable_via_resend_request", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                int startSeq = ctx.session.getStore().getNextSenderMsgSeqNum();
                for (int i = 0; i < 3; i++) ctx.session.send(buildNos());
                int endSeq = ctx.session.getStore().getNextSenderMsgSeqNum() - 1;
                ctx.responder.sent.clear();
                ctx.session.next(inbound("2", 2, m -> { m.setInt(7, startSeq); m.setInt(16, endSeq); }));
                int replayed = 0;
                for (String w : ctx.responder.sent) {
                    if (w.indexOf(SOH + "35=D" + SOH) >= 0 && "Y".equals(getTagFromWire(w, 43))) replayed++;
                }
                if (replayed != 3)                                                return "FAIL:D-replays=" + replayed + " total=" + ctx.responder.sent.size();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Interleaved inbound admin + app messages dispatch to the correct callbacks IN THE
        //      ORDER they arrived. Tests routing invariant under sustained mixed traffic. ----
        c("app_interleaved_admin_and_app_inbound_dispatch_correctly", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);   // targetSeq -> 2
                // Sequence: admin(2), app(3), admin(4), app(5).
                ctx.session.next(inbound("0", 2, null));                       // Heartbeat
                ctx.session.next(inbound("D", 3, m -> {
                    m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                    m.setString(11, "O1"); m.setDouble(38, 100); m.setDouble(44, 150.50);
                    m.setString(60, nowStamp()); m.setChar(59, '0');
                }));
                ctx.session.next(inbound("0", 4, null));                       // Heartbeat
                ctx.session.next(inbound("D", 5, m -> {
                    m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                    m.setString(11, "O2"); m.setDouble(38, 100); m.setDouble(44, 150.50);
                    m.setString(60, nowStamp()); m.setChar(59, '0');
                }));
                // Filter to just the dispatch events, in order.
                java.util.List<String> dispatch = new java.util.ArrayList<>();
                for (String e : ctx.app.events) {
                    if (e.startsWith("fromAdmin:") || e.startsWith("fromApp:")) dispatch.add(e);
                }
                java.util.List<String> expected = java.util.Arrays.asList(
                    "fromAdmin:0", "fromApp:D", "fromAdmin:0", "fromApp:D");
                if (!dispatch.equals(expected))                                 return "FAIL:got=" + dispatch;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    static String safeMsgType(Message m) {
        try { return m.getHeader().getString(35); } catch (Exception e) { return "?"; }
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
