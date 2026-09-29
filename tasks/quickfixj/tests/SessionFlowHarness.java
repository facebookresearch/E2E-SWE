import io.fix.*;

import java.util.*;
import java.util.function.Supplier;
import java.util.function.Consumer;
import java.time.*;
import java.time.format.DateTimeFormatter;

/**
 * WRG test harness -- end-to-end Session behaviour on the INITIATOR side, exercised through
 * the user-facing Application interface. Uses a mock Application (records callback events)
 * plus a mock Responder (captures outbound wires -- which is how user code observes the
 * network side effects of Session's internal state machine).
 *
 * Tests focus on: (1) callback routing (fromAdmin vs fromApp), (2) callback ordering
 * (toAdmin/toApp fires before wire is emitted), (3) lifecycle transitions observable via
 * onLogon/onLogout + isLoggedOn(), (4) message persistence + replay, (5) send() return
 * value + DoNotSend abort.
 */
public class SessionFlowHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final char SOH = (char) 0x01;
    static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyyMMdd-HH:mm:ss.SSS").withZone(ZoneOffset.UTC);
    static final DataDictionary DD;
    static { try { DD = new DataDictionary("FIX44.xml"); } catch (Exception e) { throw new RuntimeException(e); } }
    static String nowStamp() { return TS.format(Instant.now()); }

    static class MockApp implements Application {
        List<String> events = new ArrayList<>();
        public void onCreate(SessionID id)                { events.add("onCreate"); }
        public void onLogon(SessionID id)                 { events.add("onLogon"); }
        public void onLogout(SessionID id)                { events.add("onLogout"); }
        public void toAdmin(Message m, SessionID id)      { events.add("toAdmin:" + mt(m)); }
        public void fromAdmin(Message m, SessionID id) throws FieldNotFound, IncorrectDataFormat, IncorrectTagValue, RejectLogon { events.add("fromAdmin:" + mt(m)); }
        public void toApp(Message m, SessionID id) throws DoNotSend { events.add("toApp:" + mt(m)); }
        public void fromApp(Message m, SessionID id) throws FieldNotFound, IncorrectDataFormat, IncorrectTagValue, UnsupportedMessageType { events.add("fromApp:" + mt(m)); }
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
        MockApp app; MockResponder responder; Session session; SessionID sid;
        Ctx(int hbInt) throws Exception { this(new MockApp(), hbInt); }
        Ctx(MockApp app, int hbInt) throws Exception {
            this.app = app;
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
        Message reply = inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); });
        ctx.session.next(reply);
        ctx.responder.sent.clear();
        ctx.app.events.clear();
    }

    static int countSentType(MockResponder r, String type) {
        int n = 0;
        for (String w : r.sent) if (w.indexOf(SOH + "35=" + type + SOH) >= 0) n++;
        return n;
    }
    static String firstWireOfType(MockResponder r, String type) {
        for (String w : r.sent) if (w.indexOf(SOH + "35=" + type + SOH) >= 0) return w;
        return null;
    }
    static String getTagFromWire(String wire, int tag) {
        String prefix = tag + "=";
        int off;
        int i = wire.indexOf("" + SOH + prefix);
        if (i >= 0) {
            off = 1 + prefix.length();
        } else if (wire.startsWith(prefix)) {
            i = 0;
            off = prefix.length();
        } else {
            return null;
        }
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
        // ---- Bare construction: sessionID / initial state / responder wired. ----
        c("session_construct_and_getters", () -> {
            try {
                Ctx ctx = new Ctx(30);
                if (!ctx.session.getSessionID().equals(ctx.sid))          return "FAIL:sid";
                if (ctx.session.isLoggedOn())                              return "FAIL:already_loggedOn";
                if (ctx.session.getResponder() != ctx.responder)           return "FAIL:responder";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- disconnect() propagates to Responder and clears loggedOn state. ----
        c("session_disconnect_calls_responder_and_clears_loggedOn", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.session.disconnect("test", false);
                if (!ctx.responder.disconnected)                           return "FAIL:not_disconnected";
                if (ctx.session.isLoggedOn())                              return "FAIL:still_loggedOn";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- logon() + next() tick emits an outbound Logon wire carrying EncryptMethod(98)=0
        //      and HeartBtInt(108)=<configured>; fires Application.toAdmin. ----
        c("session_next_tick_sends_logon_with_wire_and_toAdmin", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.session.logon();
                ctx.session.next();
                if (countSentType(ctx.responder, "A") != 1)                return "FAIL:logon_count=" + countSentType(ctx.responder, "A");
                String logon = firstWireOfType(ctx.responder, "A");
                if (!"0".equals(getTagFromWire(logon, 98)))                return "FAIL:98=" + getTagFromWire(logon, 98);
                if (!"30".equals(getTagFromWire(logon, 108)))              return "FAIL:108=" + getTagFromWire(logon, 108);
                if (!ctx.app.events.contains("toAdmin:A"))                 return "FAIL:no_toAdmin events=" + ctx.app.events;
                if (ctx.session.isLoggedOn())                              return "FAIL:already_loggedOn_before_reply";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound Logon reply flips isLoggedOn() true and fires Application.onLogon. ----
        c("session_logon_reply_sets_loggedOn_and_fires_onLogon", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.session.logon(); ctx.session.next();
                Message reply = inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); });
                ctx.session.next(reply);
                if (!ctx.session.isLoggedOn())                             return "FAIL:not_loggedOn";
                if (!ctx.app.events.contains("onLogon"))                   return "FAIL:no_onLogon events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Post-logon: framework auto-replies to TestRequest with a Heartbeat echoing TestReqID. ----
        c("session_next_test_request_replies_with_heartbeat_matching_id", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("1", 2, m -> m.setString(112, "MYID")));
                String hb = firstWireOfType(ctx.responder, "0");
                if (hb == null)                                             return "FAIL:no_heartbeat sent=" + ctx.responder.sent;
                if (!"MYID".equals(getTagFromWire(hb, 112)))                return "FAIL:112=" + getTagFromWire(hb, 112);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Post-logon: inbound Logout auto-replies + fires onLogout + clears isLoggedOn. ----
        c("session_next_logout_replies_and_transitions", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("5", 2, null));
                if (countSentType(ctx.responder, "5") < 1)                  return "FAIL:no_logout sent=" + ctx.responder.sent;
                if (ctx.session.isLoggedOn())                              return "FAIL:still_loggedOn";
                if (!ctx.app.events.contains("onLogout"))                   return "FAIL:no_onLogout events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Post-logon: seq gap (expected=2, got=5) triggers a ResendRequest. ----
        c("session_next_seq_gap_sends_resend_request", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("0", 5, null));
                if (countSentType(ctx.responder, "2") < 1)                  return "FAIL:no_resend sent=" + ctx.responder.sent;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- send(app msg): fires toApp, writes wire, stamps header (8/34/49/56/52), advances
        //      sender seq, persists to MessageStore. All observable via Application + MessageStore. ----
        c("session_send_app_msg_observable_effects", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                int before = ctx.session.getStore().getNextSenderMsgSeqNum();
                Message d = buildNos();
                if (!ctx.session.send(d))                                   return "FAIL:send_returned_false";
                if (countSentType(ctx.responder, "D") != 1)                 return "FAIL:D_count=" + countSentType(ctx.responder, "D");
                int after = ctx.session.getStore().getNextSenderMsgSeqNum();
                if (after != before + 1)                                    return "FAIL:seq before=" + before + " after=" + after;
                if (!ctx.app.events.contains("toApp:D"))                    return "FAIL:no_toApp events=" + ctx.app.events;
                String w = firstWireOfType(ctx.responder, "D");
                if (!"FIX.4.4".equals(getTagFromWire(w, 8)))                return "FAIL:8=" + getTagFromWire(w, 8);
                if (getTagFromWire(w, 34) == null)                          return "FAIL:no_34";
                if (!"SENDER".equals(getTagFromWire(w, 49)))                return "FAIL:49=" + getTagFromWire(w, 49);
                if (!"TARGET".equals(getTagFromWire(w, 56)))                return "FAIL:56=" + getTagFromWire(w, 56);
                if (getTagFromWire(w, 52) == null)                          return "FAIL:no_52";
                java.util.List<String> replay = new java.util.ArrayList<>();
                ctx.session.getStore().get(before, before, replay);
                if (replay.size() != 1)                                     return "FAIL:replay_count=" + replay.size();
                if (replay.get(0).indexOf(SOH + "35=D" + SOH) < 0)          return "FAIL:no_35=D_in_replay";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound app-layer message routes to Application.fromApp. ----
        c("session_next_app_msg_fires_fromApp_callback", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                Message d = inbound("D", 2, m -> {
                    m.setString(55, "AAPL"); m.setChar(54, '1'); m.setChar(40, '2');
                    m.setString(11, "O1"); m.setDouble(38, 100); m.setDouble(44, 150.50);
                    m.setString(60, nowStamp()); m.setChar(59, '0');
                });
                ctx.session.next(d);
                if (!ctx.app.events.contains("fromApp:D"))                   return "FAIL:no_fromApp events=" + ctx.app.events;
                if (ctx.app.events.contains("fromAdmin:D"))                  return "FAIL:D_routed_to_fromAdmin";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound Heartbeat (admin) routes to Application.fromAdmin, not fromApp. ----
        c("session_next_admin_msg_fires_fromAdmin_callback", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("0", 2, null));
                if (!ctx.app.events.contains("fromAdmin:0"))                 return "FAIL:no_fromAdmin events=" + ctx.app.events;
                if (ctx.app.events.contains("fromApp:0"))                    return "FAIL:heartbeat_to_fromApp";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- disconnect() after a successful logon fires Application.onLogout. ----
        c("session_disconnect_after_logon_fires_onLogout", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.disconnect("test", false);
                if (!ctx.app.events.contains("onLogout"))                    return "FAIL:no_onLogout events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- send() returns false when the session has no Responder attached. ----
        c("session_send_returns_false_when_no_responder", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.session.setResponder(null);
                if (ctx.session.send(buildNos()))                             return "FAIL:send_returned_true";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound message with MsgSeqNum LESS than expected: session tears down, user code
        //      observes via onLogout + !isLoggedOn. ----
        c("session_next_low_seq_tears_down_and_fires_onLogout", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("0", 1, null));
                if (ctx.session.isLoggedOn())                                 return "FAIL:still_loggedOn";
                if (!ctx.app.events.contains("onLogout"))                     return "FAIL:no_onLogout events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Low-seq inbound with PossDupFlag(43)=Y + OrigSendingTime is a legitimate retransmit
        //      and is silently accepted -- session stays logged on. ----
        c("session_next_low_seq_with_possdup_stays_loggedOn", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("0", 1, m -> {
                    m.getHeader().setBoolean(43, true);
                    m.getHeader().setString(122, nowStamp());
                }));
                if (!ctx.session.isLoggedOn())                                return "FAIL:disconnected";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- logout() enables logout state; the following next() tick emits Logout(35=5). ----
        c("session_logout_then_tick_sends_outbound_logout", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.logout();
                ctx.session.next();
                if (countSentType(ctx.responder, "5") != 1)                   return "FAIL:logout_count=" + countSentType(ctx.responder, "5");
                if (!ctx.app.events.contains("toAdmin:5"))                    return "FAIL:no_toAdmin_5 events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- logout(reason) stamps Text(58)=reason on the outbound Logout wire. ----
        c("session_logout_with_reason_stamps_text_58", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.logout("goodbye");
                ctx.session.next();
                String logout = firstWireOfType(ctx.responder, "5");
                if (logout == null)                                            return "FAIL:no_logout";
                if (!"goodbye".equals(getTagFromWire(logout, 58)))             return "FAIL:58=" + getTagFromWire(logout, 58);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- setNextSenderMsgSeqNum rewrites the sender counter; the next send uses the new value. ----
        c("session_setNextSenderMsgSeqNum_next_send_uses_new_seq", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.setNextSenderMsgSeqNum(42);
                ctx.session.send(buildNos());
                String w = firstWireOfType(ctx.responder, "D");
                if (w == null)                                                 return "FAIL:no_D";
                if (!"42".equals(getTagFromWire(w, 34)))                       return "FAIL:34=" + getTagFromWire(w, 34);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound SequenceReset GapFillFlag=Y: framework advances internal target seq to
        //      NewSeqNo; user code observes this via a subsequent inbound msg at NewSeqNo being
        //      processed cleanly (routed to fromAdmin/fromApp, not triggering a ResendRequest). ----
        c("session_next_sequence_reset_gapfill_advances_target_seq", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);  // targetSeq -> 2
                ctx.session.next(inbound("4", 2, m -> {
                    m.setInt(36, 5);
                    m.setBoolean(123, true);
                }));
                if (ctx.session.getStore().getNextTargetMsgSeqNum() != 5)     return "FAIL:targetSeq=" + ctx.session.getStore().getNextTargetMsgSeqNum();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound SequenceReset Reset mode (GapFillFlag=N): forces target seq to NewSeqNo
        //      regardless of the message's own MsgSeqNum. ----
        c("session_next_sequence_reset_reset_mode_forces_target_seq", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("4", 99, m -> {
                    m.setInt(36, 10);
                    m.setBoolean(123, false);
                }));
                if (ctx.session.getStore().getNextTargetMsgSeqNum() != 10)     return "FAIL:targetSeq=" + ctx.session.getStore().getNextTargetMsgSeqNum();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Logon reply with ResetSeqNumFlag(141)=Y resets both sequence counters via the store. ----
        c("session_logon_reply_with_reset_seq_num_flag_resets_both_counters", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.session.getStore().setNextSenderMsgSeqNum(50);
                ctx.session.getStore().setNextTargetMsgSeqNum(50);
                ctx.session.logon(); ctx.session.next();
                Message reply = inbound("A", 1, m -> {
                    m.setInt(98, 0); m.setInt(108, 30);
                    m.setBoolean(141, true);
                });
                ctx.session.next(reply);
                if (ctx.session.getStore().getNextSenderMsgSeqNum() > 2)       return "FAIL:sender=" + ctx.session.getStore().getNextSenderMsgSeqNum();
                if (ctx.session.getStore().getNextTargetMsgSeqNum() != 2)      return "FAIL:target=" + ctx.session.getStore().getNextTargetMsgSeqNum();
                if (!ctx.session.isLoggedOn())                                 return "FAIL:not_loggedOn";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Inbound Reject(35=3) routes to Application.fromAdmin (admin-type dispatch). ----
        c("session_next_reject_35_3_routes_to_fromAdmin", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("3", 2, m -> m.setInt(45, 100)));
                if (!ctx.app.events.contains("fromAdmin:3"))                   return "FAIL:no_fromAdmin events=" + ctx.app.events;
                if (ctx.app.events.contains("fromApp:3"))                      return "FAIL:reject_routed_to_fromApp";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- CompID mismatch: framework auto-emits a session-level Reject(35=3) followed by a
        //      Logout(35=5). Both pass through Application.toAdmin, so user code is notified via
        //      the callback interface (Session tears down transport only after peer replies to
        //      the Logout — isLoggedOn stays true synchronously). ----
        c("session_compid_mismatch_fires_toAdmin_reject_then_logout", () -> {
            try {
                Ctx ctx = new Ctx(30);
                establishLogon(ctx);
                ctx.session.next(inbound("0", 2, m -> m.getHeader().setString(49, "WRONG_SENDER")));
                if (!ctx.app.events.contains("toAdmin:3"))                     return "FAIL:no_toAdmin_reject events=" + ctx.app.events;
                if (!ctx.app.events.contains("toAdmin:5"))                     return "FAIL:no_toAdmin_logout events=" + ctx.app.events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- send() called BEFORE the session has logged on: returns false + no wire
        //      written to Responder. (toApp may still fire — the mutation hook runs before
        //      the framework checks liveness — but the send itself is a no-op.) ----
        c("session_send_before_logon_returns_false_no_wire", () -> {
            try {
                Ctx ctx = new Ctx(30);
                // No logon dance; Responder attached but session not logged on.
                boolean ok = ctx.session.send(buildNos());
                if (ok)                                                        return "FAIL:send_returned_true";
                if (countSentType(ctx.responder, "D") != 0)                    return "FAIL:D_was_sent";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Normal Logon exchange (no ResetSeqNumFlag): after reply, both counters advance
        //      to 2. Sanity check that the sender-reset behaviour ONLY fires when 141=Y is set. ----
        c("session_logon_reply_no_reset_flag_sender_becomes_2", () -> {
            try {
                Ctx ctx = new Ctx(30);
                ctx.session.logon(); ctx.session.next();
                Message reply = inbound("A", 1, m -> { m.setInt(98, 0); m.setInt(108, 30); });
                ctx.session.next(reply);
                int sender = ctx.session.getStore().getNextSenderMsgSeqNum();
                int target = ctx.session.getStore().getNextTargetMsgSeqNum();
                if (sender != 2)                                               return "FAIL:sender=" + sender;
                if (target != 2)                                               return "FAIL:target=" + target;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- SessionStateListener onLogon/onLogout fire alongside Application callbacks. ----
        c("session_state_listener_onLogon_and_onLogout_fire", () -> {
            try {
                Ctx ctx = new Ctx(30);
                java.util.List<String> events = new java.util.ArrayList<>();
                ctx.session.addStateListener(new SessionStateListenerAdapter() {
                    @Override public void onLogon(SessionID id) { events.add("onLogon"); }
                    @Override public void onLogout(SessionID id) { events.add("onLogout"); }
                });
                establishLogon(ctx);
                if (!events.contains("onLogon"))                                 return "FAIL:no_onLogon events=" + events;
                ctx.session.disconnect("bye", false);
                if (!events.contains("onLogout"))                                return "FAIL:no_onLogout events=" + events;
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- removeStateListener detaches the listener; subsequent events do NOT fire on it. ----
        c("session_state_listener_can_be_added_and_removed", () -> {
            try {
                Ctx ctx = new Ctx(30);
                java.util.List<String> events = new java.util.ArrayList<>();
                SessionStateListener listener = new SessionStateListenerAdapter() {
                    @Override public void onLogout(SessionID id) { events.add("onLogout"); }
                };
                ctx.session.addStateListener(listener);
                ctx.session.removeStateListener(listener);
                establishLogon(ctx);
                ctx.session.disconnect("bye", false);
                if (events.contains("onLogout"))                                 return "FAIL:onLogout_fired_after_remove";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    /** No-op default methods for every SessionStateListener callback. */
    static class SessionStateListenerAdapter implements SessionStateListener {
        public void onConnect(SessionID id) {}
        public void onConnectException(SessionID id, Exception e) {}
        public void onDisconnect(SessionID id) {}
        public void onLogon(SessionID id) {}
        public void onLogout(SessionID id) {}
        public void onReset(SessionID id) {}
        public void onRefresh(SessionID id) {}
        public void onMissedHeartBeat(SessionID id) {}
        public void onHeartBeatTimeout(SessionID id) {}
        public void onResendRequestSent(SessionID id, int beginSeqNo, int endSeqNo, int currentEndSeqNo) {}
        public void onSequenceResetReceived(SessionID id, int newSeqNo, boolean gapFill) {}
        public void onResendRequestSatisfied(SessionID id, int beginSeqNo, int endSeqNo) {}
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
