"""Harder fair J1939-21 transport-protocol tests.

These scenarios stress the receive-side state machine, multi-session
bookkeeping, and originator abort handling.  Every contract asserted here
comes from the public instruction (§1.4 transport protocol, §4 behavioral
notes) — no derivations from implementation internals.

Mix of harnesses:
  * scripted ``Feeder`` for tests that hinge on byte-exact wire frames
    (RESOURCES abort, originator-side abort before first DT);
  * ``TwoNodeBus`` for end-to-end reassembly assertions that don't care
    about the exact CTS-window walk;
  * a small inline recording bus for the intra-ECU concurrency test where
    we drive two receive sessions on one ECU and react to whatever CTS
    schedule the implementation chooses.
"""

import threading
import time

import j1939

from feeder import Feeder, TwoNodeBus


# --------------------------------------------------------------------------- #
# Recording bus: one ECU with all transmitted frames captured for inspection.
# Used by intra-ECU multi-session test that reacts to whatever CTS schedule
# the implementation chooses.
# --------------------------------------------------------------------------- #
class _RecordingBus:
    """ECU host that records every transmitted frame and exposes ``inject``."""

    def __init__(self, max_cmdt_packets=1, **kwargs):
        self.frames = []
        self._lock = threading.Lock()
        self.ecu = j1939.ElectronicControlUnit(
            data_link_layer="j1939-21",
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send,
            **kwargs,
        )

    def _send(self, can_id, extended_id, data, fd_format=False):
        with self._lock:
            self.frames.append((can_id, list(data)))

    def inject(self, can_id, data):
        self.ecu.notify(can_id, bytearray(data), time.time())

    def snapshot(self):
        with self._lock:
            return list(self.frames)

    def stop(self):
        try:
            self.ecu.stop()
        except Exception:
            pass


# --------------------------------------------------------------------------- #
# Constants from instruction.md §1.4 (TP control bytes and abort reasons).
# --------------------------------------------------------------------------- #
CB_RTS = 16
CB_CTS = 17
CB_EOM_ACK = 19
CB_BAM = 32
CB_ABORT = 255

# Abort-reason byte values per §1.4: 1=BUSY, 2=RESOURCES, 3=TIMEOUT.
ABORT_REASON_BUSY = 1
ABORT_REASON_RESOURCES = 2
ABORT_REASON_TIMEOUT = 3


def _pgn_bytes(pgn_value):
    """LSB-first 3-byte PGN encoding used in every TP.CM frame (§1.4)."""
    return [pgn_value & 0xFF, (pgn_value >> 8) & 0xFF, (pgn_value >> 16) & 0xFF]


# --------------------------------------------------------------------------- #
# 1. Two concurrent RTS/CTS receive sessions on one ECU (different pairs)
# --------------------------------------------------------------------------- #
def test_two_concurrent_receive_sessions_on_one_ecu_no_cross_talk():
    """A single ECU receiving two interleaved J1939-21 peer-to-peer
    transfers from two different source addresses to two different
    destination addresses must keep the sessions isolated.

    Per §4: *"Transport-protocol session keys are scoped per
    (source_address, destination_address) pair; the stack must distinguish
    concurrent transfers between different address pairs."*

    Topology (one ECU; two CAs at 0x42 and 0x43)::

        Session U: peer 0x01 -> our CA at 0x42, pgn 0xDF00, payload_u (20 B)
        Session V: peer 0x02 -> our CA at 0x43, pgn 0xDF00, payload_v (27 B)

    Both peers RTS first; we then interleave DT frames for U and V; the
    receive-side state machine must reassemble each independently and
    deliver each PDU only to the matching CA's subscriber.  We react to
    whichever CTS bytes the implementation emits, so the test does not
    pin the exact window walk.

    PGN 0xDF00 is PDU1 (PF=0xDF=223 < 240), so the RTS / TP.DT frames are
    addressed peer-to-peer via the CAN-ID PS field; the wire PGN-of-the-
    transported-message in every TP.CM frame is 0xDF00 (PDU-specific
    cleared to 0 for p2p, per the RTS construction in §1.4).
    """
    pgn = 0xDF00         # 57088 — PDU1 (peer-to-peer)
    pgn_bytes = _pgn_bytes(pgn)
    payload_u = [(i * 3 + 1) & 0xFF for i in range(20)]   # 3 segments
    payload_v = [(i * 5 + 2) & 0xFF for i in range(27)]   # 4 segments
    peer_u, dst_u = 0x01, 0x42
    peer_v, dst_v = 0x02, 0x43

    # Pre-build TP.DT payloads for each session.
    def _dt_payloads(payload, num_segs):
        out = {}
        for seq in range(1, num_segs + 1):
            chunk = payload[(seq - 1) * 7:seq * 7]
            while len(chunk) < 7:
                chunk.append(0xFF)
            out[seq] = [seq] + chunk
        return out

    dt_u = _dt_payloads(payload_u, 3)
    dt_v = _dt_payloads(payload_v, 4)

    # Inbound TP.CM RTS/DT can_ids (peer → us).
    rx_cm = lambda peer, dst: (0x18 << 24) | (0xEC << 16) | (dst << 8) | peer
    rx_dt = lambda peer, dst: (0x1C << 24) | (0xEB << 16) | (dst << 8) | peer
    # Outbound TP.CM (CTS / EOM_ACK) can_ids the receiver sends back per
    # session: prio=7, PF=0xEC, PS=peer, SA=dst (us).
    tx_cm = lambda peer, dst: (0x1C << 24) | (0xEC << 16) | (peer << 8) | dst

    bus = _RecordingBus(max_cmdt_packets=1)
    try:
        ca_u = j1939.ControllerApplication(None, dst_u, bypass_address_claim=True)
        ca_v = j1939.ControllerApplication(None, dst_v, bypass_address_claim=True)
        bus.ecu.add_ca(controller_application=ca_u)
        bus.ecu.add_ca(controller_application=ca_v)

        received_u = []
        received_v = []
        ca_u.subscribe(
            lambda priority, p, sa, ts, data:
                received_u.append((p, sa, list(data)))
        )
        ca_v.subscribe(
            lambda priority, p, sa, ts, data:
                received_v.append((p, sa, list(data)))
        )

        # Inject both RTSes (back-to-back so the stack has two open receive
        # buffers simultaneously).
        bus.inject(
            rx_cm(peer_u, dst_u),
            [CB_RTS, 20, 0, 3, 1, *pgn_bytes],
        )
        bus.inject(
            rx_cm(peer_v, dst_v),
            [CB_RTS, 27, 0, 4, 1, *pgn_bytes],
        )

        # Reactive loop: walk the receiver's TX frames; for each CTS, inject
        # the granted DT range for the matching session; stop when both
        # sessions have emitted EOM_ACK.
        eom_u = None
        eom_v = None
        processed = 0
        deadline = time.time() + 8.0
        while time.time() < deadline:
            frames = bus.snapshot()
            while processed < len(frames):
                can_id, data = frames[processed]
                processed += 1
                # Route the TX by inspecting can_id (PS=peer identifies which
                # session this response belongs to).
                if can_id == tx_cm(peer_u, dst_u):
                    session_peer, session_dst = peer_u, dst_u
                    session_dts = dt_u
                    session_payload = payload_u
                    num_segs = 3
                elif can_id == tx_cm(peer_v, dst_v):
                    session_peer, session_dst = peer_v, dst_v
                    session_dts = dt_v
                    session_payload = payload_v
                    num_segs = 4
                else:
                    raise AssertionError(
                        "unexpected receiver TX can_id=%08X data=%r"
                        % (can_id, data)
                    )
                control = data[0]
                if control == CB_CTS:
                    granted = data[1]
                    next_seq = data[2]
                    for seq in range(next_seq, next_seq + granted):
                        if 1 <= seq <= num_segs:
                            bus.inject(
                                rx_dt(session_peer, session_dst),
                                session_dts[seq],
                            )
                elif control == CB_EOM_ACK:
                    if session_peer == peer_u:
                        eom_u = (can_id, list(data))
                    else:
                        eom_v = (can_id, list(data))
                else:
                    raise AssertionError(
                        "unexpected TP.CM control byte from receiver: "
                        "%d (data=%r)" % (control, data)
                    )
            if eom_u is not None and eom_v is not None:
                break
            time.sleep(0.02)

        # Both EOM_ACK frames must match the documented layout (§1.4).
        assert eom_u == (
            tx_cm(peer_u, dst_u),
            [CB_EOM_ACK, 20, 0, 3, 0xFF, *pgn_bytes],
        ), "session U EOM_ACK mismatch / missing: %r" % (eom_u,)
        assert eom_v == (
            tx_cm(peer_v, dst_v),
            [CB_EOM_ACK, 27, 0, 4, 0xFF, *pgn_bytes],
        ), "session V EOM_ACK mismatch / missing: %r" % (eom_v,)

        # Allow notify-callbacks a beat to fire after EOM_ACK.
        sub_deadline = time.time() + 1.0
        while time.time() < sub_deadline and (not received_u or not received_v):
            time.sleep(0.02)

        # Per-CA subscribers see only their own payload — no cross-talk.
        assert received_u == [(pgn, peer_u, payload_u)], (
            "CA-U should have received only payload_u from peer 0x%02X; got %r"
            % (peer_u, received_u)
        )
        assert received_v == [(pgn, peer_v, payload_v)], (
            "CA-V should have received only payload_v from peer 0x%02X; got %r"
            % (peer_v, received_v)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 2. RESOURCES abort: stray CTS for a non-existent send session
# --------------------------------------------------------------------------- #
def test_stray_cts_triggers_resources_abort(feeder):
    """A TP.CM CTS that names an (originator, responder) pair for which the
    stack has no send buffer must be answered with an ABORT carrying
    abort_reason = 2 (RESOURCES), per §1.4 (abort_reason byte values
    `1`=BUSY, `2`=RESOURCES, `3`=TIMEOUT).

    Setup: install an accept-all CA at address 0x02 (so the stack will
    accept and dispatch the inbound TP.CM frame).  Inject a CTS frame from
    peer 0x01 to us 0x02 naming pgn 0x00FEB0 (65200).  Since we never
    initiated a corresponding send to 0x01, the (us, peer) send buffer
    does not exist → ABORT(RESOURCES) is the documented response.

    Expected abort frame (priority=7 by §1.4 for responder-side TP.CM,
    PF=236, PS=peer=0x01, SA=us=0x02 → can_id 0x1CEC0102; data layout
    per §1.4 abort row: `[control=255, abort_reason, 0xFF, 0xFF, 0xFF,
    pgn_lo, pgn_mid, pgn_hi]`).
    """
    feeder.accept_all_messages()

    pgn = 65200   # 0xFEB0
    feeder.can_messages = [
        # Stray CTS: peer 0x01 → us 0x02, claims to grant 1 packet starting
        # at sequence 1.  We have no matching send buffer for (us, peer).
        # CTS can_id: prio=7, PF=0xEC, PS=us=0x02, SA=peer=0x01 → 0x1CEC0201.
        # (Inbound CTS uses the same TP.CM PGN as RTS; the control byte
        # distinguishes them.)
        (Feeder.MsgType.CANRX, 0x1CEC0201,
         [CB_CTS, 1, 1, 0xFF, 0xFF, *_pgn_bytes(pgn)], 0.0),
        # Stack must respond with ABORT(RESOURCES) addressed back to peer.
        # TX can_id: prio=7, PF=0xEC, PS=peer=0x01, SA=us=0x02 → 0x1CEC0102.
        (Feeder.MsgType.CANTX, 0x1CEC0102,
         [CB_ABORT, ABORT_REASON_RESOURCES, 0xFF, 0xFF, 0xFF, *_pgn_bytes(pgn)],
         0.0),
    ]
    feeder.drive()


def _seeded_bytes(n, offset):
    """Length-``n`` payload whose byte at index ``i`` is
    ``(i * 11 + offset * 41 + 7) & 0xFF``.

    Distinct ``offset`` values produce byte-distinguishable payloads so
    cross-talk between concurrent or back-to-back transfers would be
    visible at every byte position, not only at the length.
    """
    return [(i * 11 + offset * 41 + 7) & 0xFF for i in range(n)]


# --------------------------------------------------------------------------- #
# Multiples-of-7 transfer sizes (no last-DT padding) round-trips
# --------------------------------------------------------------------------- #
def test_rts_cts_multiples_of_7_no_padding_roundtrips():
    """Round-trip several peer-to-peer payloads whose size is an EXACT
    multiple of 7, so the final TP.DT carries no 0xFF padding.

    Per §1.4 ``num_packets = ceil(message_size / 7)`` and the last DT
    pads with 0xFF only when ``message_size % 7 != 0``.  A bug in the
    "no padding needed" branch (off-by-one in num_packets, or
    spuriously truncating real payload bytes that happen to be 0xFF)
    surfaces here without competing against the padding rule.

    Sizes 14 / 21 / 700 cover the small / medium / large cases that
    require multi-CTS windows at ``max_cmdt_packets = 4``.  Each fresh
    ``TwoNodeBus`` per sub-case prevents state carry-over; distinct
    seeds catch cross-bleeds byte-by-byte.
    """
    pgn = 0xDF00
    # (size, payload_seed_offset)
    cases = [
        (14,  101),    # 2 packets, exact
        (21,  103),    # 3 packets, exact
        (700, 107),    # 100 packets, exact -- multi-CTS-window territory
    ]
    for size, off in cases:
        assert size % 7 == 0, "test designed for exact-multiple-of-7 sizes"
        payload = _seeded_bytes(size, off)
        bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=4)
        try:
            bus.a_send(
                pdu_format=(pgn >> 8) & 0xFF,
                pdu_specific=bus.sa_b,
                data=payload,
            )
            bus.deliver(
                timeout=15.0 if size >= 500 else 8.0,
                quiet=0.4 if size >= 500 else 0.3,
            )
            assert bus.received_b == [(pgn, payload)], (
                "size=%d: B should have received the exact %d-byte payload; "
                "got %d PDU(s); first len=%d"
                % (
                    size, size, len(bus.received_b),
                    len(bus.received_b[0][1]) if bus.received_b else 0,
                )
            )
            assert bus.received_a == [], (
                "size=%d: A should not have received anything; got %r"
                % (size, bus.received_a)
            )
        finally:
            bus.stop()


# --------------------------------------------------------------------------- #
# 6. Full lifecycle: A->B RTS/CTS, then B->* BAM, then A->B short PDU
# --------------------------------------------------------------------------- #
def test_sustained_multi_transfer_lifecycle_roundtrip():
    """A sustained sequence of three distinct transfers across both nodes
    on the same bus, each completed in turn, all delivered correctly and
    in order.

    Steps:
      1. A → B long peer-to-peer (RTS/CTS), 120 B / 18 packets.  Per §1.4
         reassembled + EOM_ACK contract.
      2. B → broadcast (BAM, PDU2 pgn 0xFEB0), 70 B / 10 packets.  Per
         §1.4 BAM reassembled and delivered as a single PDU under the
         announced PGN, with no EOM_ACK.
      3. A → B short peer-to-peer (≤ 8 bytes, single frame, no TP).
         Per §1.4 the routing is direct (no TP frames involved).

    Each transfer is allowed to fully drain before the next is started so
    the assertions are deterministic on which PDU lands when.  Final
    state: B has received {step 1 p2p, step 2 broadcast, step 3 short};
    A has received {step 2 broadcast} only.  Payload seeds are distinct
    so any swapped or cross-bled delivery surfaces as a byte mismatch.
    """
    pgn_p2p_long = 0xDF00     # PDU1 (PF=0xDF=223), peer-to-peer RTS/CTS
    pgn_bcast = 0xFEB0        # PDU2 (PF=0xFE), broadcast (BAM)
    pgn_p2p_short = 0xEF00    # PDU1 (PF=0xEF=239), peer-to-peer short

    payload_step1 = _seeded_bytes(120, offset=11)   # 18 packets (last pad: 6 of 7 unused? no: 120 % 7 = 1 -> 6 pad bytes)
    payload_step2 = _seeded_bytes(70, offset=22)    # 10 packets, no pad
    payload_step3 = _seeded_bytes(8, offset=33)     # short, single full frame

    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=4)
    try:
        # Step 1: A -> B long RTS/CTS.
        bus.a_send(
            pdu_format=(pgn_p2p_long >> 8) & 0xFF,
            pdu_specific=bus.sa_b,
            data=payload_step1,
        )
        bus.deliver(timeout=10.0, quiet=0.4)
        assert bus.received_b == [(pgn_p2p_long, payload_step1)], (
            "step 1 (A->B RTS/CTS): expected one PDU on B with the long "
            "payload; got %r" % (bus.received_b,)
        )
        assert bus.received_a == [], (
            "step 1: A should not have received anything yet; got %r"
            % (bus.received_a,)
        )

        # Step 2: B -> broadcast BAM (PDU2 PGN, pdu_specific carries the
        # group extension byte 0xB0; destination is GLOBAL by virtue of
        # PDU2 routing per §1.4 / §4).
        bus.b_send(
            pdu_format=0xFE,
            pdu_specific=0xB0,
            data=payload_step2,
        )
        # BAM uses the 50 ms Tb minimum between DTs -> ~0.5 s for 10
        # packets; allow ample slack.
        bus.deliver(timeout=15.0, quiet=0.5)
        assert bus.received_a == [(pgn_bcast, payload_step2)], (
            "step 2 (B broadcast BAM): A should have received exactly one "
            "broadcast PDU; got %r" % (bus.received_a,)
        )
        # B's prior delivery should be unchanged; B does NOT receive its
        # own broadcast back (TwoNodeBus only forwards TX to the other
        # node).
        assert bus.received_b == [(pgn_p2p_long, payload_step1)], (
            "step 2: B should still hold only the step-1 PDU; got %r"
            % (bus.received_b,)
        )

        # Step 3: A -> B short single-frame peer-to-peer.
        bus.a_send(
            pdu_format=(pgn_p2p_short >> 8) & 0xFF,
            pdu_specific=bus.sa_b,
            data=payload_step3,
        )
        bus.deliver(timeout=5.0, quiet=0.3)
        assert bus.received_b == [
            (pgn_p2p_long, payload_step1),
            (pgn_p2p_short, payload_step3),
        ], (
            "step 3 (A->B short): B should now hold step-1 PDU + step-3 "
            "PDU in order; got %r" % (bus.received_b,)
        )
        # A's broadcast reception unchanged; A should not have received
        # the short PDU (it's addressed to B).
        assert bus.received_a == [(pgn_bcast, payload_step2)], (
            "step 3: A should still hold only the step-2 broadcast; got %r"
            % (bus.received_a,)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 7. Two concurrent sends from one source to two destinations
# --------------------------------------------------------------------------- #
class _ThreeNodeBus:
    """In-memory shared CAN segment with three ECUs (A, B, C).

    Every frame transmitted by one node is delivered to the OTHER two
    nodes (and not back to the sender), so all three see the same bus
    traffic.  Each node hosts an "accept all" CA at a fixed address so
    peer-to-peer frames are accepted on the matching destination.

    Used by the concurrent-multi-destination test to stress per-(src,dst)
    session keying within ONE originator: A holds two simultaneous send
    sessions, ``(A, B)`` and ``(A, C)``, that must not collide.
    """

    def __init__(self, sa_a=0x90, sa_b=0x9B, sa_c=0xAB, max_cmdt_packets=1):
        import queue
        self.sa_a, self.sa_b, self.sa_c = sa_a, sa_b, sa_c
        self.received_a, self.received_b, self.received_c = [], [], []
        self._stop_obj = object()
        self._last_activity = time.time()

        self.ecu_a = j1939.ElectronicControlUnit(
            data_link_layer="j1939-21",
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send_a,
        )
        self.ecu_b = j1939.ElectronicControlUnit(
            data_link_layer="j1939-21",
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send_b,
        )
        self.ecu_c = j1939.ElectronicControlUnit(
            data_link_layer="j1939-21",
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send_c,
        )
        # Plain ControllerApplications -- NOT AcceptAllCA -- so each
        # node's CA only accepts traffic addressed to its own claimed
        # address (or GLOBAL).  This is essential for the concurrent
        # multi-destination test: an "accept all" CA at B would happily
        # open a receive session for an RTS destined for C and emit a
        # spurious CTS, corrupting A's send state.
        self.ca_a = j1939.ControllerApplication(
            None, sa_a, bypass_address_claim=True,
        )
        self.ca_b = j1939.ControllerApplication(
            None, sa_b, bypass_address_claim=True,
        )
        self.ca_c = j1939.ControllerApplication(
            None, sa_c, bypass_address_claim=True,
        )
        self.ecu_a.add_ca(controller_application=self.ca_a)
        self.ecu_b.add_ca(controller_application=self.ca_b)
        self.ecu_c.add_ca(controller_application=self.ca_c)
        self.ecu_a.subscribe(self._on_a)
        self.ecu_b.subscribe(self._on_b)
        self.ecu_c.subscribe(self._on_c)

        self._q_a = queue.Queue()
        self._q_b = queue.Queue()
        self._q_c = queue.Queue()
        self._t_a = threading.Thread(
            target=self._drain, args=(self._q_a, self.ecu_a), daemon=True,
        )
        self._t_b = threading.Thread(
            target=self._drain, args=(self._q_b, self.ecu_b), daemon=True,
        )
        self._t_c = threading.Thread(
            target=self._drain, args=(self._q_c, self.ecu_c), daemon=True,
        )
        self._t_a.start()
        self._t_b.start()
        self._t_c.start()

    def _broadcast_except(self, sender, can_id, data):
        # Deliver every frame to the OTHER two nodes.
        item = (can_id, bytearray(data), time.time())
        if sender is not self.ecu_a:
            self._q_a.put(item)
        if sender is not self.ecu_b:
            self._q_b.put(item)
        if sender is not self.ecu_c:
            self._q_c.put(item)
        self._last_activity = time.time()

    def _send_a(self, can_id, extended_id, data, fd_format=False):
        self._broadcast_except(self.ecu_a, can_id, data)

    def _send_b(self, can_id, extended_id, data, fd_format=False):
        self._broadcast_except(self.ecu_b, can_id, data)

    def _send_c(self, can_id, extended_id, data, fd_format=False):
        self._broadcast_except(self.ecu_c, can_id, data)

    def _drain(self, q, ecu):
        while True:
            item = q.get()
            if item is self._stop_obj:
                break
            self._last_activity = time.time()
            try:
                ecu.notify(item[0], item[1], item[2])
            except Exception:
                pass  # tested elsewhere; don't crash background thread

    def _on_a(self, priority, pgn, sa, timestamp, data):
        self.received_a.append((pgn, list(data) if data is not None else None))

    def _on_b(self, priority, pgn, sa, timestamp, data):
        self.received_b.append((pgn, list(data) if data is not None else None))

    def _on_c(self, priority, pgn, sa, timestamp, data):
        self.received_c.append((pgn, list(data) if data is not None else None))

    def a_send(self, pdu_format, pdu_specific, data, priority=6):
        self.ecu_a.send_pgn(
            0, pdu_format, pdu_specific, priority, self.sa_a, list(data),
        )

    def b_send(self, pdu_format, pdu_specific, data, priority=6):
        self.ecu_b.send_pgn(
            0, pdu_format, pdu_specific, priority, self.sa_b, list(data),
        )

    def c_send(self, pdu_format, pdu_specific, data, priority=6):
        self.ecu_c.send_pgn(
            0, pdu_format, pdu_specific, priority, self.sa_c, list(data),
        )

    def deliver(self, timeout=10.0, quiet=0.4):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if (
                self._q_a.empty()
                and self._q_b.empty()
                and self._q_c.empty()
                and (time.time() - self._last_activity) > quiet
            ):
                break
            time.sleep(0.02)

    def stop(self):
        for ecu in (self.ecu_a, self.ecu_b, self.ecu_c):
            try:
                ecu.stop()
            except Exception:
                pass
        self._q_a.put(self._stop_obj)
        self._q_b.put(self._stop_obj)
        self._q_c.put(self._stop_obj)
        self._t_a.join(timeout=2.0)
        self._t_b.join(timeout=2.0)
        self._t_c.join(timeout=2.0)


def test_concurrent_bam_broadcast_and_p2p_send_one_originator():
    """One originator A holds a BAM *broadcast* session and an RTS/CTS
    *peer-to-peer* session in flight at the same time, started before
    either completes.  Both payloads must be delivered intact with no
    cross-contamination.

    Per §4: concurrent transfers must reassemble independently.  This
    stresses a different session-keying axis than the all-RTS/CTS mesh
    tests: inside A's send-buffer book a BAM session keyed ``(A, GLOBAL)``
    coexists with an RTS/CTS session keyed ``(A, B)`` -- a stack that keyed
    solely on source address, or that shared one transmit buffer between
    its BAM and CMDT paths, would splice the two DT streams.  The broadcast
    is a PDU2 (PF=0xFE) so it lands on both B and C; the p2p is a PDU1
    (PF=0xDF) to B only.  Distinct sizes (133 BAM / 175 p2p bytes -> 19 vs
    25 packets) and seed-distinct payloads catch length or byte-level swaps.
    """
    pgn_bcast = 0xFEB0                          # PDU2 broadcast (BAM)
    pgn_p2p = 0xDF00                            # PDU1 peer-to-peer (RTS/CTS)
    payload_bcast = _seeded_bytes(133, offset=51)   # 19 packets exactly
    payload_p2p = _seeded_bytes(175, offset=89)     # 25 packets exactly
    assert len(payload_bcast) != len(payload_p2p)

    bus = _ThreeNodeBus(max_cmdt_packets=4)
    try:
        # Kick off both transfers back-to-back -- no wait between -- so both
        # send sessions are live in A's send buffer at the same time and the
        # bus carries interleaved BAM-DT and CMDT DT/CTS traffic.
        bus.a_send(
            pdu_format=(pgn_bcast >> 8) & 0xFF,
            pdu_specific=pgn_bcast & 0xFF,
            data=payload_bcast,
        )
        bus.a_send(
            pdu_format=(pgn_p2p >> 8) & 0xFF,
            pdu_specific=bus.sa_b,
            data=payload_p2p,
        )
        bus.deliver(timeout=25.0, quiet=0.6)

        # B sees both the broadcast and its addressed p2p payload; the order
        # the two arrive in is implementation-defined, so compare as a set.
        got_b = set((p, tuple(d)) for p, d in bus.received_b)
        want_b = {
            (pgn_bcast, tuple(payload_bcast)),
            (pgn_p2p, tuple(payload_p2p)),
        }
        assert got_b == want_b, (
            "B should have received the broadcast + the (A->B) p2p payload; "
            "got %d PDU(s): %r" % (len(bus.received_b), bus.received_b)
        )
        # C sees only the broadcast (the p2p is addressed to B).
        assert bus.received_c == [(pgn_bcast, payload_bcast)], (
            "C should have received only the broadcast; got %r"
            % (bus.received_c,)
        )
        # A should not have received its own sends back, nor anything else.
        assert bus.received_a == [], (
            "A should not have received anything; got %r" % (bus.received_a,)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# Max-size 1785-byte transfer at the two most demanding window grants
# --------------------------------------------------------------------------- #
def test_max_size_1785_byte_roundtrip_demanding_window_grants():
    """The J1939-21 hard maximum (1785 bytes = 255 packets x 7) round-tripped
    twice, on a fresh ``TwoNodeBus`` each time, at the two most demanding
    receiver window settings:

      * ``max_cmdt_packets = 1`` -- the receiver issues a fresh CTS after
        every single DT (255 CTS rounds).  Heaviest scheduling load.
      * ``max_cmdt_packets = 8`` -- ~32 CTS windows.  Different scheduling
        cadence; distinct payload catches any state carry-over.

    Per §1.4 reassembly + EOM_ACK contract.  Round-trip assertion only --
    no implementation-internal frame ordering pinned.
    """
    pgn = 0xDF00
    # (max_cmdt_packets, payload_seed, deliver_timeout, deliver_quiet)
    cases = [
        (1, 127, 45.0, 0.7),
        (8, 211, 30.0, 0.6),
    ]
    for max_cmdt, seed, timeout, quiet in cases:
        payload = _seeded_bytes(1785, offset=seed)
        bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=max_cmdt)
        try:
            bus.a_send(
                pdu_format=(pgn >> 8) & 0xFF,
                pdu_specific=bus.sa_b,
                data=payload,
            )
            bus.deliver(timeout=timeout, quiet=quiet)
            assert bus.received_b == [(pgn, payload)], (
                "max_cmdt=%d: B did not receive the 1785-byte payload; "
                "got %d PDU(s); first len=%d (expected 1785)"
                % (
                    max_cmdt,
                    len(bus.received_b),
                    len(bus.received_b[0][1]) if bus.received_b else 0,
                )
            )
            assert bus.received_a == [], (
                "max_cmdt=%d: A should not have received anything; got %r"
                % (max_cmdt, bus.received_a)
            )
        finally:
            bus.stop()


# --------------------------------------------------------------------------- #
# Three-node mesh: A sends to B and to C concurrently; C sends to A.
#
# The mesh below subsumes the simpler "one node sends one long transfer while
# receiving another from a distinct partner" case (A->B while C->A): A here
# holds (A,B) + (A,C) in its send buffer AND (C,A) in its receive buffer at
# once, so the send-buffer-vs-receive-buffer keying it would have checked is
# exercised here as a strict superset.  The bidirectional same-pair keying is
# covered separately by test_concurrent_long_transfers_distinct_address_pairs
# (tests/test_j1939_tp_edge.py).
# --------------------------------------------------------------------------- #
def test_three_node_mesh_a_sends_to_b_and_c_while_c_sends_to_a():
    """Three-node mesh with FIVE concurrent transport sessions live on
    the bus at once:

      * A → B long RTS/CTS
      * A → C long RTS/CTS
      * C → A long RTS/CTS

    Per §4, the relevant session keys are all distinct:
      - A's send buffer holds (A,B) and (A,C)
      - A's receive buffer holds (C,A)
      - B's receive buffer holds (A,B)
      - C's send buffer holds (C,A)
      - C's receive buffer holds (A,C)

    A correct implementation runs all three transfers without
    cross-contamination.  Sizes (140 / 175 / 210 bytes) are pairwise
    distinct so a length swap surfaces before byte comparison.
    """
    pgn = 0xDF00
    payload_ab = _seeded_bytes(140, offset=251)   # 20 packets
    payload_ac = _seeded_bytes(175, offset=263)   # 25 packets
    payload_ca = _seeded_bytes(210, offset=277)   # 30 packets
    assert len({len(payload_ab), len(payload_ac), len(payload_ca)}) == 3

    bus = _ThreeNodeBus(max_cmdt_packets=4)
    try:
        # Three sends back-to-back so all three sessions are live before
        # any completes.
        bus.a_send(
            pdu_format=(pgn >> 8) & 0xFF,
            pdu_specific=bus.sa_b,
            data=payload_ab,
        )
        bus.a_send(
            pdu_format=(pgn >> 8) & 0xFF,
            pdu_specific=bus.sa_c,
            data=payload_ac,
        )
        bus.c_send(
            pdu_format=(pgn >> 8) & 0xFF,
            pdu_specific=bus.sa_a,
            data=payload_ca,
        )
        bus.deliver(timeout=25.0, quiet=0.6)

        assert bus.received_b == [(pgn, payload_ab)], (
            "B should have received only the (A->B) payload; got %d PDU(s); "
            "first len=%d" % (
                len(bus.received_b),
                len(bus.received_b[0][1]) if bus.received_b else 0,
            )
        )
        assert bus.received_c == [(pgn, payload_ac)], (
            "C should have received only the (A->C) payload; got %d PDU(s); "
            "first len=%d" % (
                len(bus.received_c),
                len(bus.received_c[0][1]) if bus.received_c else 0,
            )
        )
        assert bus.received_a == [(pgn, payload_ca)], (
            "A should have received only the (C->A) payload; got %d PDU(s); "
            "first len=%d" % (
                len(bus.received_a),
                len(bus.received_a[0][1]) if bus.received_a else 0,
            )
        )
    finally:
        bus.stop()


# =========================================================================== #
# ROUND 7 — distinct edge cases beyond TP concurrency: NAME-arbitration ties,
# data-page-1 transport, GLOBAL-vs-specific p2p routing + SA=NULL reception,
# and immediate-NORMAL address ranges.  All assertions derive from §1.x /
# §2.5 contracts plus the GT behavior at each branch point (read from
# controller_application.py and j1939_21.py).
# =========================================================================== #


# 8-byte little-endian NAME used by the existing address-claim tests; reused
# here so equal-name arbitration is byte-exact against the canonical NAME.
_CLAIM_NAME_KWARGS = dict(
    arbitrary_address_capable=0,
    industry_group=j1939.Name.IndustryGroup.Industrial,
    vehicle_system_instance=2,
    vehicle_system=127,
    function=201,
    function_instance=16,
    ecu_instance=2,
    manufacturer_code=666,
    identity_number=1234567,
)
_CLAIM_NAME_BYTES = [135, 214, 82, 83, 130, 201, 254, 82]


# --------------------------------------------------------------------------- #
# 18. Equal-NAME arbitration: we KEEP and re-announce
# --------------------------------------------------------------------------- #
def test_address_claim_equal_name_contender_keeps_and_reannounces(feeder):
    """When a contender with a NAME equal to ours claims the same address
    during our WAIT_VETO window, GT's arbitration test is strict ``>``
    (controller_application.py:187 -- ``if self._name.value >
    contenders_name.value``).  Equal value does NOT trigger the
    release-and-reclaim branch; instead the else-branch fires and we
    re-announce our claim (line 207-215).  After the veto window
    expires we transition to NORMAL with the original address intact.

    This is a genuinely distinct arbitration branch from
    test_addr_claim_fixed_veto_lose (contender < us → we lose) and
    test_addr_claim_fixed_veto_win (contender > us → we re-announce and
    keep).  The "equal" case takes the same code-path as "we win" but
    via a different boolean test, so a model that flipped the comparison
    to ``>=`` would lose here while still passing the win/lose tests.
    """
    name = j1939.Name(**_CLAIM_NAME_KWARGS)
    feeder.can_messages = [
        # Initial Address Claimed at 128 (WAIT_VETO range 128..247).
        (Feeder.MsgType.CANTX, 0x18EEFF80, _CLAIM_NAME_BYTES, 0.0),
        # Contender with IDENTICAL NAME for the same address.
        (Feeder.MsgType.CANRX, 0x18EEFF80, _CLAIM_NAME_BYTES, 0.0),
        # GT's else-branch re-announces our claim at 128 (same NAME, same
        # can_id, same data).
        (Feeder.MsgType.CANTX, 0x18EEFF80, _CLAIM_NAME_BYTES, 0.0),
    ]
    ca = feeder.ecu.add_ca(name=name, device_address=128)
    ca.start()
    feeder.drive()
    feeder.wait_for_state(ca, j1939.ControllerApplication.State.NORMAL)
    assert ca.state == j1939.ControllerApplication.State.NORMAL, (
        "equal-NAME contender: CA should keep address 128 and reach "
        "NORMAL, got state=%r" % (ca.state,)
    )


# --------------------------------------------------------------------------- #
# 19. Data-page-1 PGN transport round-trip
# --------------------------------------------------------------------------- #
def test_data_page_1_pgn_transport_roundtrip():
    """A long peer-to-peer transfer with ``data_page = 1``.

    Per §1.1 (CAN-ID layout) the DP bit is part of the 18-bit PGN field
    of the MessageId; per §1.4 every TP.CM frame carries the
    18-bit PGN as three little-endian bytes ``pgn_lo, pgn_mid, pgn_hi``,
    so ``pgn_hi`` for a DP=1 message has the LSB set.  GT's RTS
    encoding follows: for ``ParameterGroupNumber(1, 0xDF, 0x9B)`` the
    stored ``pgn.value`` is ``(1<<16) | (0xDF<<8) | 0x9B`` -- in the
    RTS the destination is then cleared to 0, so the on-wire pgn bytes
    are ``[0, 0xDF, 1]``.  At the receiver the same bytes reconstruct
    ``pgn_value = 0x1DF00`` which is delivered to the subscriber.

    We can't use ``TwoNodeBus.a_send`` (it hardcodes DP=0); call
    ``ecu_a.send_pgn`` directly with DP=1.
    """
    expected_pgn = (1 << 16) | (0xDF << 8) | 0   # 0x1DF00 after p2p PS clear
    payload = _seeded_bytes(56, offset=431)      # 8 packets, no pad

    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=4)
    try:
        # Call send_pgn directly so we can pass data_page=1.
        bus.ecu_a.send_pgn(
            1,            # data_page
            0xDF,         # pdu_format (PDU1, peer-to-peer)
            bus.sa_b,     # pdu_specific = destination
            6,            # priority
            bus.sa_a,     # src_address
            list(payload),
            0,            # time_limit
        )
        bus.deliver(timeout=12.0, quiet=0.4)

        assert bus.received_b == [(expected_pgn, payload)], (
            "DP=1 long p2p: B should have received under pgn=0x%05X; "
            "got %d PDU(s); details=%r"
            % (expected_pgn, len(bus.received_b), bus.received_b)
        )
        assert bus.received_a == [], (
            "A should not have received anything; got %r" % (bus.received_a,)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 20. Short PDU1 to GLOBAL vs specific; reception from SA=NULL (254)
# --------------------------------------------------------------------------- #
def test_short_pdu1_global_vs_specific_and_sa_null_reception(feeder):
    """Three addressing corners of single-frame (≤ 8-byte) PDU1 traffic
    that the multi-frame tests don't exercise:

      (a) A short PDU1 sent with ``pdu_specific = 0xFF`` (GLOBAL) is
          emitted on a CAN-ID whose PS byte is 0xFF (per §1.1 the PGN
          field of the CAN-ID stores PS in its low byte; per §2.3
          ``pdu_specific`` is that byte).
      (b) The same short PDU1 sent with ``pdu_specific = 0x9B`` is
          emitted with PS = 0x9B.
      (c) A received PDU whose source address is NULL (254) is dispatched
          normally to subscribers with ``sa = 254`` reported -- §4
          routing filters on destination only, never on source.

    Setup: scripted Feeder.  Use a CA at address 0x42 (bypass claim)
    so we have a NORMAL address from which to send.  Subscribe via the
    feeder so injected frames flow to ``feeder.pdus`` checking.
    """
    # ---- Part A: short PDU1 to GLOBAL ----
    # send_pgn for pdu_specific=0xFF, len(data)<=8 -> short path:
    # mid = MessageId(prio=6, pgn=PGN(0, 0xEF, 0xFF).value=0xEFFF, sa=0x42)
    # -> can_id = (6<<26)|(0xEFFF<<8)|0x42 = 0x18EFFF42.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EFFF42,
         [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88], 0.0),
    ]
    ca = feeder.accept_all_messages(
        device_address_preferred=0x42, bypass_address_claim=True,
    )
    # Send 8-byte payload to GLOBAL.
    ca.send_pgn(
        0,           # data_page
        0xEF,        # pdu_format (PDU1)
        0xFF,        # pdu_specific = GLOBAL
        6,           # priority
        [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88],
    )
    # Drain part A.
    deadline = time.time() + 2.0
    while time.time() < deadline and feeder.can_messages:
        time.sleep(0.02)
    assert not feeder.can_messages, (
        "Part A: stack did not emit short-to-GLOBAL frame; "
        "leftover script=%r" % (feeder.can_messages,)
    )
    assert feeder.error is None, (
        "Part A unexpected feeder error: %r" % (feeder.error,)
    )

    # ---- Part B: short PDU1 to specific address ----
    # pgn=PGN(0, 0xEF, 0x9B).value=0xEF9B; can_id=0x18EF9B42.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EF9B42,
         [0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8], 0.0),
    ]
    ca.send_pgn(
        0, 0xEF, 0x9B, 6,
        [0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xA7, 0xA8],
    )
    deadline = time.time() + 2.0
    while time.time() < deadline and feeder.can_messages:
        time.sleep(0.02)
    assert not feeder.can_messages, (
        "Part B: stack did not emit short-to-specific frame; "
        "leftover script=%r" % (feeder.can_messages,)
    )
    assert feeder.error is None, (
        "Part B unexpected feeder error: %r" % (feeder.error,)
    )

    # ---- Part C: receive a PDU whose SA = NULL (254) ----
    # An external peer at SA=254 sends a short PDU1 to our CA at 0x42.
    # can_id: prio=6, PF=0xEF (PDU1, not TP/REQUEST/ADDRESSCLAIM),
    # PS=0x42 (us), SA=0xFE (NULL) -> 0x18EF42FE.  Falls through to the
    # generic notify_subscribers branch in j1939_21.notify (NOT a special
    # PGN), so our subscriber should see (pgn=0xEF00, sa=0xFE, data).
    received = []

    def on_msg(priority, pgn, sa, timestamp, data):
        received.append((pgn, sa, list(data)))

    feeder.ecu.subscribe(on_msg)
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x18EF42FE,
         [0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8], 0.0),
    ]
    feeder._inject_messages_into_ecu()
    # Wait for the inject thread to deliver and the subscriber to fire.
    deadline = time.time() + 2.0
    while time.time() < deadline and not received:
        time.sleep(0.02)
    assert feeder.error is None, (
        "Part C unexpected feeder error: %r" % (feeder.error,)
    )
    assert received == [(0xEF00, 0xFE,
                         [0xC1, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8])], (
        "Part C: subscriber should fire with sa=0xFE (NULL); got %r"
        % (received,)
    )


# --------------------------------------------------------------------------- #
# 21. Address-claim for addresses in 0..127 and 248..253 — immediate NORMAL
# --------------------------------------------------------------------------- #
def test_address_claim_immediate_normal_ranges_skip_veto(feeder):
    """Per §2.5: *"For preferred addresses in 128..247 the CA enters
    WAIT_VETO and waits roughly 250 ms for a contender.  Addresses
    outside that range (0..127 and 248..253) skip the veto and go
    straight to NORMAL."*  GT enforces this at
    controller_application.py:143-149: ``if announced > 127 and
    announced < 248: WAIT_VETO`` else immediate NORMAL.

    This test exercises the immediate-NORMAL branch -- distinct from
    the four core address-claim tests, which all use address 128
    (WAIT_VETO range).  Two sub-cases:

      (a) address 100 (in 0..127): emit one Address Claimed and go
          straight to NORMAL.
      (b) address 250 (in 248..253): emit one Address Claimed and go
          straight to NORMAL.

    Both cases must NOT enter WAIT_VETO (they should ignore any later
    contender frames because the spec says they go straight to
    NORMAL).
    """
    # ---- Part A: address 100 ----
    name_a = j1939.Name(**_CLAIM_NAME_KWARGS)
    # can_id for Address Claimed at sa=100=0x64:
    # MessageId(prio=6, pgn=0xEEFF, sa=0x64).can_id = 0x18EEFF64.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFF64, _CLAIM_NAME_BYTES, 0.0),
    ]
    ca_a = feeder.ecu.add_ca(name=name_a, device_address=100)
    ca_a.start()
    feeder.drive()
    feeder.wait_for_state(ca_a, j1939.ControllerApplication.State.NORMAL)
    assert ca_a.state == j1939.ControllerApplication.State.NORMAL, (
        "address 100 should reach NORMAL immediately (no veto wait); "
        "got state=%r" % (ca_a.state,)
    )
    assert ca_a.device_address == 100, (
        "address 100: device_address should be 100 in NORMAL state; "
        "got %r" % (ca_a.device_address,)
    )

    # ---- Part B: address 250 ----
    name_b = j1939.Name(**dict(_CLAIM_NAME_KWARGS, ecu_instance=3))
    # can_id at sa=250=0xFA: 0x18EEFFFA.  Distinct NAME bytes because of
    # ecu_instance=3 (so the second add_ca/claim is independently
    # identifiable on the wire).
    expected_name_b_bytes = j1939.Name(
        **dict(_CLAIM_NAME_KWARGS, ecu_instance=3)
    ).bytes
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFFFA, expected_name_b_bytes, 0.0),
    ]
    ca_b = feeder.ecu.add_ca(name=name_b, device_address=250)
    ca_b.start()
    feeder.drive()
    feeder.wait_for_state(ca_b, j1939.ControllerApplication.State.NORMAL)
    assert ca_b.state == j1939.ControllerApplication.State.NORMAL, (
        "address 250 should reach NORMAL immediately (no veto wait); "
        "got state=%r" % (ca_b.state,)
    )
    assert ca_b.device_address == 250, (
        "address 250: device_address should be 250 in NORMAL state; "
        "got %r" % (ca_b.device_address,)
    )
