"""J1939-21 transport-protocol edge / error paths and CA dispatch tests.

These scenarios cover the corners of the connection-managed transport that the
:file:`test_j1939_core.py` happy paths do not exercise:

* RTS-while-busy (BUSY abort) on the receive side
* CTS num_packages == 0 (pause / resume) on the originator
* ``max_cmdt_packets`` > 1 on the receive side: granting multiple segments per CTS
* ABORT received mid-send cleanly cancels the originator session
* PGN Request handling: a Request for the AddressClaim PGN triggers the CA to
  re-announce its name; ``ControllerApplication.send_request`` emits a Request
  frame with the exact expected bytes
* Multi-CA on a single ECU: per-CA address routing of peer-to-peer PDUs and
  silent drop after ``remove_ca``

Every byte in every TX expectation is derived from ``j1939/j1939_21.py`` and
``j1939/controller_application.py`` of the reference implementation
(can-j1939 2.0.12) and is annotated with the formula it comes from.
"""

import threading
import time

import j1939

from feeder import Feeder, AcceptAllCA, TwoNodeBus


# --------------------------------------------------------------------------- #
# Common byte-derivation helpers
# --------------------------------------------------------------------------- #
# The 8-byte little-endian NAME reused from the core test-suite.  Keeping the
# byte sequence stable across tests makes the address-claim expectations easy
# to read.
CLAIM_NAME_KWARGS = dict(
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
CLAIM_NAME_BYTES = [135, 214, 82, 83, 130, 201, 254, 82]

# Control bytes from j1939_21.J1939_21.ConnectionMode
CB_RTS = 16
CB_CTS = 17
CB_EOM_ACK = 19
CB_BAM = 32
CB_ABORT = 255

# Abort reasons from j1939_21.J1939_21.ConnectionAbortReason
ABORT_REASON_BUSY = 1


def _pgn_bytes(pgn_value):
    """LSB-first 3-byte PGN encoding used in every TP.CM frame."""
    return [pgn_value & 0xFF, (pgn_value >> 8) & 0xFF, (pgn_value >> 16) & 0xFF]


# --------------------------------------------------------------------------- #
# 1. RTS-while-busy -> BUSY abort
# --------------------------------------------------------------------------- #
def test_rts_while_busy_sends_busy_abort(feeder):
    """A second TP.CM RTS arrives for an already-active (src,dst) reception.

    Per ``_process_tp_cm`` RTS branch (j1939_21.py): if
    ``_buffer_hash(src, dst)`` is already present in ``_rcv_buffer`` the stack
    must transmit a TP.CM ABORT (control byte 255) with reason BUSY (1) and
    must NOT touch the existing receive buffer.

    Derivation of the abort frame from ``__send_tp_abort`` -- note the caller
    passes ``(dest_address=our, src_address=peer)`` so the transmitted frame
    has PS=peer and SA=our::

        priority=7  (hard-coded)
        PF=236      (TP.CM)
        PS=0x01     (peer source address)
        SA=0x02     (our destination address)
        => can_id = 0x1CEC0102
        data = [255, 1 (BUSY), 0xFF, 0xFF, 0xFF,
                pgn_lo, pgn_mid, pgn_hi]   pgn = 0x00FEB0 = 65200

    First RTS (peer=0x01, us=0x02, message_size=20, num_packages=3,
    peer-offered max_cmdt=1, pgn=65200) opens the buffer and triggers a CTS
    granting one packet starting at sequence 1 (max_num_packages = min(1,3),
    num_packages_max_rec = min(_max_cmdt_packets=1, 1) = 1, next_packet = 1).
    """
    feeder.accept_all_messages()

    pgn = 65200  # 0xFEB0
    feeder.can_messages = [
        # First RTS opens the rcv buffer for (peer=0x01, dst=0x02).
        (Feeder.MsgType.CANRX, 0x00EC0201,
         [CB_RTS, 20, 0, 3, 1, *_pgn_bytes(pgn)], 0.0),
        # Stack's CTS in response: num_packets=1, next_packet=1.
        (Feeder.MsgType.CANTX, 0x1CEC0102,
         [CB_CTS, 1, 1, 0xFF, 0xFF, *_pgn_bytes(pgn)], 0.0),
        # Second RTS for the same (src,dst) pair while the session is open.
        (Feeder.MsgType.CANRX, 0x00EC0201,
         [CB_RTS, 20, 0, 3, 1, *_pgn_bytes(pgn)], 0.0),
        # Stack must respond with a BUSY abort, not a CTS.
        (Feeder.MsgType.CANTX, 0x1CEC0102,
         [CB_ABORT, ABORT_REASON_BUSY, 0xFF, 0xFF, 0xFF, *_pgn_bytes(pgn)], 0.0),
    ]
    feeder.drive()
    # The original receive buffer must still be alive (we never sent ABORT
    # for that one), so the next legitimate DT for it should still be honored.
    # We don't drive DTs here -- the byte-exact TX assertions above already
    # prove BUSY was emitted instead of a second CTS.


# --------------------------------------------------------------------------- #
# Recording bus: captures every frame the stack transmits.
# Used by tests where the protocol exchange depends on injected timing and
# scripting individual frames in strict order would be brittle.
# --------------------------------------------------------------------------- #
class _RecordingBus:
    """ECU host that records all transmitted frames and exposes ``inject``.

    Unlike :class:`Feeder`, this harness does NOT validate transmitted frames
    against a pre-built script -- the test inspects ``frames`` directly after
    driving the scenario.  This is appropriate when we need to assert about
    *timing* (something does not happen for a while) or about *which* frames
    were sent without committing to their order.
    """

    def __init__(self, max_cmdt_packets=1, **kwargs):
        self.frames = []                 # list of (can_id, list(data))
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
# 2. CTS num_packages == 0 -> pause; later CTS resumes the transfer
# --------------------------------------------------------------------------- #
def test_cts_pause_then_resume_on_send():
    """While sending a long peer-to-peer message, a CTS with ``num_packages=0``
    must pause the originator (no further TP.DT transmitted) until a normal
    CTS is received, at which point the remaining TP.DT frames are sent.

    Reference (``_process_tp_cm`` CTS branch, j1939_21.py)::

        if num_packages == 0:
            # SAE J1939/21 - receiver requests a pause
            self._snd_buffer[buffer_hash]['deadline'] = time.time() + Timeout.Th
            return                              # state is unchanged

    Test layout (originator SA=0x90, responder DST=0x9B, pgn=57088=0xDF00,
    20 bytes -> 3 packets, ``max_cmdt_packets`` default 1)::

        TX RTS                              can_id 0x18EC9B90
        RX CTS(num=1, next=1)               -> TX DT#1
        RX CTS(num=0)  (pause)              expect NO TX for >=200 ms
        RX CTS(num=1, next=2)               -> TX DT#2
        RX CTS(num=1, next=3)               -> TX DT#3
        RX EOM_ACK                          (no further TX)

    The recording bus lets us assert "no DT during the pause window".
    """
    pgn = 57088  # 0xDF00
    pgn_bytes = _pgn_bytes(pgn)            # [0x00, 0xDF, 0x00]
    payload = [1, 2, 3, 4, 5, 6, 7,
               1, 2, 3, 4, 5, 6, 7,
               1, 2, 3, 4, 5, 6]            # 20 bytes
    sa = 0x90
    dst = 0x9B

    bus = _RecordingBus(max_cmdt_packets=1)
    try:
        ca = AcceptAllCA(None, sa, True)
        bus.ecu.add_ca(controller_application=ca)

        # Kick off a 20-byte peer-to-peer send: should emit RTS immediately.
        bus.ecu.send_pgn(0, (pgn >> 8) & 0xFF, dst, 6, sa, list(payload))

        # Wait for the RTS to land on the bus.
        deadline = time.time() + 4.0
        while time.time() < deadline and len(bus.snapshot()) < 1:
            time.sleep(0.01)
        frames = bus.snapshot()
        # RTS expectation: priority=6, PF=236, PS=dst, SA=sa => 0x18EC9B90,
        # data=[16, size_lo=20, size_hi=0, num_pkts=3, max_cmdt=1, pgn..]
        assert frames[0] == (
            0x18EC9B90,
            [CB_RTS, 20, 0, 3, 1, *pgn_bytes],
        ), "RTS bytes mismatch: %r" % (frames[0],)

        # Responder grants 1 packet starting at 1.
        # CTS can_id from peer's POV: prio=7, PF=236, PS=sa(=our), SA=dst.
        cts_can_id = 0x1CEC0000 | (sa << 8) | dst   # 0x1CEC909B
        bus.inject(cts_can_id, [CB_CTS, 1, 1, 0xFF, 0xFF, *pgn_bytes])

        # Wait for DT#1.  Wait window widened to 4 s to give slow originator
        # job threads room to schedule the transmission.
        deadline = time.time() + 4.0
        while time.time() < deadline and len(bus.snapshot()) < 2:
            time.sleep(0.01)
        frames = bus.snapshot()
        # DT can_id: prio=7, PF=235, PS=dst, SA=sa => 0x1CEB9B90.
        assert frames[1] == (
            0x1CEB9B90,
            [1, 1, 2, 3, 4, 5, 6, 7],
        ), "DT#1 bytes mismatch: %r" % (frames[1],)

        tx_before_pause = len(bus.snapshot())

        # PAUSE: CTS with num_packages = 0.  data[2] (next_packet) is not
        # read in the num=0 branch; use 0xFF per common practice.
        bus.inject(cts_can_id,
                   [CB_CTS, 0, 0xFF, 0xFF, 0xFF, *pgn_bytes])

        # Wait long enough that, had the stack ignored the pause, it would
        # have sent DT#2 by now.  Timeout.Th is 0.5 s; the job thread wakes
        # every few tens of ms.  400 ms is comfortably below the hold timeout
        # (so no timeout-abort fires) yet well above the originator's typical
        # job-thread wake quantum.
        time.sleep(0.4)
        assert len(bus.snapshot()) == tx_before_pause, (
            "stack transmitted %d frame(s) during pause; expected 0. "
            "frames=%r"
            % (len(bus.snapshot()) - tx_before_pause, bus.snapshot()[tx_before_pause:])
        )

        # RESUME: CTS for 1 packet starting at sequence 2.
        bus.inject(cts_can_id,
                   [CB_CTS, 1, 2, 0xFF, 0xFF, *pgn_bytes])

        # Wait for DT#2.
        deadline = time.time() + 4.0
        while time.time() < deadline and len(bus.snapshot()) < 3:
            time.sleep(0.01)
        frames = bus.snapshot()
        assert frames[2] == (
            0x1CEB9B90,
            [2, 1, 2, 3, 4, 5, 6, 7],
        ), "DT#2 bytes mismatch: %r" % (frames[2],)

        # Grant the final packet.
        bus.inject(cts_can_id,
                   [CB_CTS, 1, 3, 0xFF, 0xFF, *pgn_bytes])
        deadline = time.time() + 4.0
        while time.time() < deadline and len(bus.snapshot()) < 4:
            time.sleep(0.01)
        frames = bus.snapshot()
        # Last packet has 6 real bytes (20 - 14 = 6) and is padded with 0xFF.
        assert frames[3] == (
            0x1CEB9B90,
            [3, 1, 2, 3, 4, 5, 6, 0xFF],
        ), "DT#3 bytes mismatch: %r" % (frames[3],)

        # Close out the session with EOM_ACK.  No further TX is expected.
        bus.inject(cts_can_id,
                   [CB_EOM_ACK, 20, 0, 3, 0xFF, *pgn_bytes])
        time.sleep(0.2)
        assert len(bus.snapshot()) == 4, (
            "unexpected TX after EOM_ACK: %r" % (bus.snapshot()[4:],)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 3. max_cmdt_packets > 1 RECEIVE: multi-segment reception (window-agnostic)
# --------------------------------------------------------------------------- #
def test_receive_with_max_cmdt_packets_greater_than_one():
    """A receiver constructed with ``max_cmdt_packets=4`` correctly receives a
    multi-segment peer-to-peer transfer that requires more than one CTS.

    The instruction lightly constrains the CTS-window walk (only the initial
    ``next_pkt_seq=1`` and the receiver-controlled segment count are pinned),
    so this test does NOT assert exact ``num_pkts/next_pkt`` values on the
    second-or-later CTS.  Instead it asserts the four observable contracts:

      (a) After RTS, the receiver emits at least one CTS (control byte 17)
          whose initial ``next_pkt_seq`` field is 1.
      (b) Every TP.DT segment we inject is accepted (the receiver's session
          stays alive and eventually completes).
      (c) When reassembly is complete, the receiver emits exactly one
          EndOfMsgACK (control byte 19) carrying the announced total size
          (39 bytes) and packet count (6) in the documented byte layout.
      (d) The subscriber callback receives the full reassembled payload
          under the announced PGN.

    Scenario: 39-byte message -> 6 packets, peer offers max=255,
    ``_max_cmdt_packets`` = 4.  Peer SA=0x01, our DST=0x02, pgn=65200=0xFEB0.

    The test drives reactively: whenever the receiver emits a CTS, we read
    its ``num_pkts_to_send`` and ``next_pkt_seq`` fields and inject exactly
    that contiguous run of TP.DT segments.  This works for any legal window
    scheme (one segment at a time, or all six in one grant, or anything in
    between).
    """
    pgn = 65200       # 0xFEB0
    pgn_bytes = _pgn_bytes(pgn)
    message_size = 39
    num_packets = 6
    payload = list(range(1, message_size + 1))   # bytes 1..39
    peer_sa = 0x01
    our_dst = 0x02

    # Pre-build each TP.DT payload (7 bytes each, last padded with 0xFF).
    dt_payloads = {}
    for seq in range(1, num_packets + 1):
        start = (seq - 1) * 7
        chunk = payload[start:start + 7]
        while len(chunk) < 7:
            chunk.append(0xFF)
        dt_payloads[seq] = [seq] + chunk

    # CAN-IDs the peer would use to address us.
    # TP.CM RX from peer:  prio=6, PF=0xEC, PS=our, SA=peer -> 0x18EC0201
    # TP.DT RX from peer:  prio=7, PF=0xEB, PS=our, SA=peer -> 0x1CEB0201
    rx_tp_cm_can_id = (0x18 << 24) | (0xEC << 16) | (our_dst << 8) | peer_sa
    rx_tp_dt_can_id = (0x1C << 24) | (0xEB << 16) | (our_dst << 8) | peer_sa
    # The CTS / EOM_ACK the receiver sends back:
    # prio=7, PF=0xEC, PS=peer, SA=our -> 0x1CEC0102
    expected_tx_tp_cm_can_id = (
        (0x1C << 24) | (0xEC << 16) | (peer_sa << 8) | our_dst
    )

    bus = _RecordingBus(max_cmdt_packets=4)
    try:
        # Plain accept-all CA at our address so the receive-side delivers
        # the reassembled PDU to a subscriber.
        ca = AcceptAllCA(None, our_dst, True)
        bus.ecu.add_ca(controller_application=ca)

        received = []

        def on_msg(priority, pgn_value, sa, timestamp, data):
            received.append((pgn_value, list(data)))

        ca.subscribe(on_msg)

        # Inject the RTS: 39 bytes, 6 packets, peer offers max=255.
        bus.inject(
            rx_tp_cm_can_id,
            [CB_RTS, message_size, 0, num_packets, 0xFF, *pgn_bytes],
        )

        # Reactive CTS-driven loop.  For each new TX frame:
        #   * if it's a CTS (control 17), inject the granted DT run;
        #   * if it's the EOM_ACK (control 19), stop;
        #   * any other TP.CM control byte is an unexpected response.
        cts_count = 0
        first_cts = None
        eom_ack_frame = None
        processed_idx = 0
        deadline = time.time() + 5.0
        while time.time() < deadline:
            frames = bus.snapshot()
            while processed_idx < len(frames):
                can_id, data = frames[processed_idx]
                processed_idx += 1
                # Only consider frames the receive side would emit on the
                # response can_id.  (Any TP.CM frame the model sends should
                # use exactly this can_id; flag anything else.)
                if can_id != expected_tx_tp_cm_can_id:
                    raise AssertionError(
                        "unexpected receiver TX can_id=%08X data=%r"
                        % (can_id, data)
                    )
                control = data[0]
                if control == CB_CTS:
                    cts_count += 1
                    granted = data[1]
                    next_seq = data[2]
                    if first_cts is None:
                        first_cts = (granted, next_seq)
                    # Inject the granted contiguous DT run.  Clamp to the
                    # remaining packets in case the implementation grants
                    # beyond what is left.
                    for seq in range(next_seq, next_seq + granted):
                        if seq < 1 or seq > num_packets:
                            continue
                        bus.inject(rx_tp_dt_can_id, dt_payloads[seq])
                elif control == CB_EOM_ACK:
                    eom_ack_frame = (can_id, list(data))
                    break
                else:
                    raise AssertionError(
                        "unexpected TP.CM control byte from receiver: "
                        "%d (data=%r)" % (control, data)
                    )
            if eom_ack_frame is not None:
                break
            time.sleep(0.02)

        # (a) Initial CTS was emitted with next_pkt_seq == 1.
        assert first_cts is not None, (
            "receiver did not emit a CTS after RTS; frames=%r"
            % (bus.snapshot(),)
        )
        assert first_cts[1] == 1, (
            "initial CTS next_pkt_seq should be 1, got %d (granted=%d)"
            % (first_cts[1], first_cts[0])
        )
        assert first_cts[0] >= 1, (
            "initial CTS must grant at least one packet, got %d"
            % (first_cts[0],)
        )

        # (b) + (c) EOM_ACK was emitted with the documented byte layout.
        assert eom_ack_frame is not None, (
            "receiver did not emit an EOM_ACK; observed %d CTS, frames=%r"
            % (cts_count, bus.snapshot())
        )
        assert eom_ack_frame == (
            expected_tx_tp_cm_can_id,
            [CB_EOM_ACK, message_size, 0, num_packets, 0xFF, *pgn_bytes],
        ), "EOM_ACK bytes mismatch: %r" % (eom_ack_frame,)

        # (d) The subscriber saw the fully reassembled PDU exactly once.
        # Give the notify path a beat to complete after EOM_ACK.
        sub_deadline = time.time() + 1.0
        while time.time() < sub_deadline and not received:
            time.sleep(0.02)
        assert received == [(pgn, payload)], (
            "subscriber should have received exactly one PDU=(pgn=%d, "
            "payload=[1..%d]); got %r" % (pgn, message_size, received)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 4. ABORT received mid-send cleanly cancels the session
# --------------------------------------------------------------------------- #
def test_abort_received_during_send_cancels_session(feeder):
    """While the originator is mid-transfer (state WAITING_CTS between two CTS
    grants) an inbound TP.CM ABORT must mark the send buffer
    ``TRANSMISSION_FINISHED`` and the stack must not transmit any further
    TP.DT for that session.

    Reference (``_process_tp_cm`` ABORT branch)::

        if (buffer_hash in self._snd_buffer
            and self._snd_buffer[buffer_hash]['state'] == WAITING_CTS):
            self._snd_buffer[buffer_hash]['state'] = TRANSMISSION_FINISHED
            self._snd_buffer[buffer_hash]['deadline'] = time.time()
        # async_job_thread then deletes the TRANSMISSION_FINISHED buffer.

    Scenario (sa=0x90 -> dst=0x9B, pgn=57088=0xDF00, 20 bytes / 3 packets,
    ``max_cmdt_packets`` = 1)::

        TX RTS
        RX CTS(num=1, next=1)   -> TX DT#1
        RX ABORT(reason=4 CTS_WHILE_DT)   (no further TX)
    """
    pgn = 57088       # 0xDF00
    pgn_bytes = _pgn_bytes(pgn)
    feeder.accept_all_messages()
    feeder.can_messages = [
        # TX RTS: prio=6, PF=236, PS=0x9B, SA=0x90 -> 0x18EC9B90.
        (Feeder.MsgType.CANTX, 0x18EC9B90,
         [CB_RTS, 20, 0, 3, 1, *pgn_bytes], 0.0),
        # Inbound CTS (peer's POV: prio=7, PS=our 0x90, SA=dst 0x9B).
        (Feeder.MsgType.CANRX, 0x1CEC909B,
         [CB_CTS, 1, 1, 0xFF, 0xFF, *pgn_bytes], 0.0),
        # TX DT#1: prio=7, PF=235, PS=0x9B, SA=0x90 -> 0x1CEB9B90.
        (Feeder.MsgType.CANTX, 0x1CEB9B90,
         [1, 1, 2, 3, 4, 5, 6, 7], 0.0),
        # Peer aborts mid-transfer.  Reason byte is informational here; pick
        # CTS_WHILE_DT (4) just to exercise a non-BUSY reason.
        (Feeder.MsgType.CANRX, 0x1CEC909B,
         [CB_ABORT, 4, 0xFF, 0xFF, 0xFF, *pgn_bytes], 0.0),
        # No further TX expected -- _wait drains an empty script list and
        # check() asserts no extra frames were emitted.
    ]
    feeder.send(
        (Feeder.MsgType.PDU, pgn,
         [1, 2, 3, 4, 5, 6, 7,
          1, 2, 3, 4, 5, 6, 7,
          1, 2, 3, 4, 5, 6]),
        144, 155,
    )
    # Give the async job thread a beat to delete the cancelled buffer and
    # detect any errant DT#2 that should NOT happen.
    time.sleep(0.2)
    feeder.check()


# --------------------------------------------------------------------------- #
# 5. PGN Request handling and ControllerApplication.send_request
# --------------------------------------------------------------------------- #
def test_request_addressclaim_triggers_name_response_and_send_request_bytes():
    """A CA in state NORMAL that receives a peer-to-peer Request (PGN 0xEA00)
    for the AddressClaim PGN (0xEE00) must respond by transmitting its
    Address-Claimed frame (NAME), and ``ca.send_request(...)`` must emit a
    correctly-formatted Request frame.

    Reference (``ControllerApplication._process_request``,
    ``_send_address_claimed``, ``send_request``)::

        # _process_request: when pgn == ADDRESSCLAIM, call
        # self._send_address_claimed(self._device_address)
        #   -> ParameterGroupNumber(0, 238, GLOBAL)  value=0xEEFF
        #   -> MessageId(prio=6, pgn=0xEEFF, sa=device_address)
        #   -> data = self._name.bytes  (8-byte little-endian NAME)
        #
        # send_request(data_page, pgn, destination):
        #   data = [pgn&0xFF, (pgn>>8)&0xFF, (pgn>>16)&0xFF]
        #   ecu.send_pgn(data_page,
        #                (REQUEST>>8)&0xFF = 0xEA,    # PDU format
        #                destination & 0xFF,          # PDU specific
        #                priority=6,
        #                src_address=self._device_address,
        #                data)
        #   -> 3-byte data fits in a single frame; MessageId(prio=6, pgn=0xEAxx,
        #      sa=device_address) -> can_id = 0x18EAxxSS.
    """
    our_addr = 0xF9
    peer_addr = 0x42

    bus = _RecordingBus(max_cmdt_packets=1)
    try:
        name = j1939.Name(**CLAIM_NAME_KWARGS)
        ca = j1939.ControllerApplication(
            name=name,
            device_address_preferred=our_addr,
            bypass_address_claim=True,        # jump straight to NORMAL
        )
        bus.ecu.add_ca(controller_application=ca)
        assert ca.state == j1939.ControllerApplication.State.NORMAL

        # -- Part A: inbound REQUEST for ADDRESSCLAIM ---------------------- #
        # Request frame from peer: prio=6, PF=0xEA, PS=our=0xF9, SA=peer=0x42
        # -> can_id = 0x18EAF942.  Data: 3-byte requested PGN (0xEE00 ->
        # [0x00, 0xEE, 0x00]) padded with 0xFF to 8 bytes.
        bus.inject(0x18EAF942,
                   [0x00, 0xEE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])

        # Wait for the claimed-NAME response.
        deadline = time.time() + 2.0
        while time.time() < deadline and not bus.snapshot():
            time.sleep(0.01)
        frames = bus.snapshot()
        assert frames, "no address-claimed response transmitted"
        # Expected: prio=6, PF=238, PS=GLOBAL=0xFF, SA=our=0xF9
        # -> can_id = 0x18EEFFF9; data = NAME bytes.
        assert frames[0] == (
            0x18EEFFF9,
            CLAIM_NAME_BYTES,
        ), "address-claim response mismatch: %r" % (frames[0],)

        # A Request for some OTHER pgn (not ADDRESSCLAIM) with no subscriber
        # must NOT trigger an address-claimed response.  Use PGN 0xFEEE which
        # the CA does not have a subscriber for.
        tx_before = len(bus.snapshot())
        bus.inject(0x18EAF942,
                   [0xEE, 0xFE, 0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
        time.sleep(0.15)
        assert len(bus.snapshot()) == tx_before, (
            "unexpected TX in response to non-ADDRESSCLAIM request: %r"
            % (bus.snapshot()[tx_before:],)
        )

        # -- Part B: outbound send_request bytes --------------------------- #
        # ca.send_request(data_page=0, pgn=0xEE00, destination=peer_addr).
        # Expected frame: prio=6, PF=0xEA, PS=peer=0x42, SA=our=0xF9
        # -> can_id = 0x18EA42F9; data = [0x00, 0xEE, 0x00].
        tx_before = len(bus.snapshot())
        ca.send_request(0, 0xEE00, peer_addr)
        deadline = time.time() + 1.0
        while time.time() < deadline and len(bus.snapshot()) <= tx_before:
            time.sleep(0.01)
        frames = bus.snapshot()
        assert len(frames) > tx_before, "send_request did not transmit"
        assert frames[tx_before] == (
            0x18EA42F9,
            [0x00, 0xEE, 0x00],
        ), "send_request bytes mismatch: %r" % (frames[tx_before],)
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 6. Multi-CA on one ECU: per-address dispatch and remove_ca
# --------------------------------------------------------------------------- #
def test_multi_ca_dispatch_and_remove_ca():
    """Two ControllerApplications at different addresses on a single ECU must
    each receive only the peer-to-peer PDUs addressed to them; broadcasts
    reach both; after ``remove_ca(addr_a)`` PDUs to ``addr_a`` are silently
    dropped (no callback at all).

    Reference paths::

        # j1939_21.notify, peer-to-peer reception:
        #   if dest_address != GLOBAL:
        #     if not self.__ecu_is_message_acceptable(dest_address):
        #       iterate CAs; if NONE accept -> return (drop)
        #
        # electronic_control_unit._notify_subscribers:
        #   for dic in self._subscribers:
        #     if (dic['dev_adr'] is None)
        #        or (dest == GLOBAL)
        #        or (callable(dic['dev_adr']) and dic['dev_adr'](dest))
        #        or (dest == dic['dev_adr']):
        #       dic['cb'](priority, pgn, sa, timestamp, data)
        #
        # ControllerApplication.subscribe registers dev_adr=self.message_acceptable,
        # so the subscriber callback only fires when the destination matches
        # that CA's claimed address (or is GLOBAL).

    Scenario: ECU hosts CA-A at 0x42 and CA-B at 0x43; peer 0x01 sends a
    short peer-to-peer PDU (pgn=56320 = 0xDC00) to each address in turn and
    then a broadcast.  After ``remove_ca(0x42)``, a PDU to 0x42 must reach
    neither callback.
    """
    addr_a = 0x42
    addr_b = 0x43
    peer = 0x01
    pgn_p2p = 56320       # 0xDC00, PDU1 (peer-to-peer)
    pgn_bcast = 65200     # 0xFEB0, PDU2 (broadcast)

    bus = _RecordingBus(max_cmdt_packets=1)
    try:
        # Plain ControllerApplications -- NOT AcceptAllCA -- because this
        # test exercises per-address dispatch.  AcceptAllCA overrides
        # message_acceptable to return True for every destination, which
        # would cause both CAs to accept a P2P PDU to either address and
        # defeat the assertions below.  The default ControllerApplication
        # only accepts a destination when it equals its own device_address
        # (or equals GLOBAL=255, which routes broadcasts to both CAs).
        ca_a = j1939.ControllerApplication(
            None, addr_a, bypass_address_claim=True,
        )
        ca_b = j1939.ControllerApplication(
            None, addr_b, bypass_address_claim=True,
        )
        bus.ecu.add_ca(controller_application=ca_a)
        bus.ecu.add_ca(controller_application=ca_b)
        assert ca_a.state == j1939.ControllerApplication.State.NORMAL
        assert ca_b.state == j1939.ControllerApplication.State.NORMAL

        received_a = []
        received_b = []

        def on_a(priority, pgn, sa, timestamp, data):
            received_a.append((pgn, sa, list(data)))

        def on_b(priority, pgn, sa, timestamp, data):
            received_b.append((pgn, sa, list(data)))

        ca_a.subscribe(on_a)
        ca_b.subscribe(on_b)

        def _wait_total(n_a, n_b, timeout=1.0):
            deadline = time.time() + timeout
            while time.time() < deadline:
                if len(received_a) >= n_a and len(received_b) >= n_b:
                    return
                time.sleep(0.01)

        # P2P to addr_a only.  can_id: prio=6, PF=0xDC, PS=addr_a, SA=peer.
        bus.inject((0x18 << 24) | (0xDC << 16) | (addr_a << 8) | peer,
                   [0xAA, 0, 0, 0, 0, 0, 0, 1])
        _wait_total(1, 0)
        assert received_a == [(pgn_p2p, peer, [0xAA, 0, 0, 0, 0, 0, 0, 1])], (
            "CA-A should have received the PDU to 0x%02X: %r"
            % (addr_a, received_a)
        )
        assert received_b == [], (
            "CA-B should NOT have received the PDU to 0x%02X: %r"
            % (addr_a, received_b)
        )

        # P2P to addr_b only.
        bus.inject((0x18 << 24) | (0xDC << 16) | (addr_b << 8) | peer,
                   [0xBB, 0, 0, 0, 0, 0, 0, 2])
        _wait_total(1, 1)
        assert received_b == [(pgn_p2p, peer, [0xBB, 0, 0, 0, 0, 0, 0, 2])], (
            "CA-B should have received the PDU to 0x%02X: %r"
            % (addr_b, received_b)
        )
        assert len(received_a) == 1, (
            "CA-A should not have received the PDU to 0x%02X (got %r)"
            % (addr_b, received_a)
        )

        # Broadcast (PDU2 form): both CAs see it (dest==GLOBAL short-circuit
        # in _notify_subscribers).
        # can_id: prio=6, PF=0xFE, PS=0xB0, SA=peer.
        bus.inject((0x18 << 24) | (0xFE << 16) | (0xB0 << 8) | peer,
                   [0xCC, 0, 0, 0, 0, 0, 0, 3])
        _wait_total(2, 2)
        assert received_a[-1] == (pgn_bcast, peer, [0xCC, 0, 0, 0, 0, 0, 0, 3]), (
            "CA-A missed broadcast: %r" % (received_a,)
        )
        assert received_b[-1] == (pgn_bcast, peer, [0xCC, 0, 0, 0, 0, 0, 0, 3]), (
            "CA-B missed broadcast: %r" % (received_b,)
        )

        a_count_before = len(received_a)
        b_count_before = len(received_b)

        # Drop CA-A.  A subsequent P2P to addr_a must be rejected upstream
        # (no CA accepts) and reach neither callback.
        assert bus.ecu.remove_ca(addr_a) is True, "remove_ca(0x%02X) failed" % addr_a

        bus.inject((0x18 << 24) | (0xDC << 16) | (addr_a << 8) | peer,
                   [0xDD, 0, 0, 0, 0, 0, 0, 4])
        time.sleep(0.15)
        assert len(received_a) == a_count_before, (
            "CA-A callback fired after remove_ca: new=%r"
            % (received_a[a_count_before:],)
        )
        assert len(received_b) == b_count_before, (
            "CA-B should not receive PDUs addressed to removed CA-A: new=%r"
            % (received_b[b_count_before:],)
        )

        # P2P to addr_b still works.
        bus.inject((0x18 << 24) | (0xDC << 16) | (addr_b << 8) | peer,
                   [0xEE, 0, 0, 0, 0, 0, 0, 5])
        _wait_total(a_count_before, b_count_before + 1)
        assert received_b[-1] == (pgn_p2p, peer, [0xEE, 0, 0, 0, 0, 0, 0, 5]), (
            "CA-B stopped receiving after remove_ca(other): %r" % (received_b,)
        )
    finally:
        bus.stop()


# =========================================================================== #
# ROUND 2 — harder fair transport tests (TwoNodeBus round-trips).
#
# Every assertion below relies only on contracts documented in
# instruction.md §1.4 (TP reassembly + EOM_ACK + BAM behavior + CTS window
# rule) and §4 (per-(src,dst) session keying).  No byte-exact wire
# expectations on CTS windowing are added here -- the §1.4 wording bounds
# the grant count from above ("up to max_cmdt_packets") so the exact
# num_pkts_to_send field cannot be pinned without leaking implementation
# choices.  Receiver-timeout-to-abort behavior is NOT tested either: §1.4
# enumerates abort_reason byte 3 = TIMEOUT but does not document the
# trigger conditions deterministically.
# =========================================================================== #


def _distinct_payload(n_bytes, seed):
    """Deterministic, sequence-distinguishing payload of length ``n_bytes``.

    The byte at index ``i`` is ``(i * seed + (seed >> 2)) & 0xFF``.  Using
    distinct ``seed`` values across the tests ensures any cross-contaminated
    reassembly between concurrent or back-to-back sessions surfaces as a
    visible byte mismatch rather than a coincidental match.
    """
    base = seed >> 2
    return [(i * seed + base) & 0xFF for i in range(n_bytes)]


# --------------------------------------------------------------------------- #
# 10. Large BAM broadcast round-trip (~500 bytes)
# --------------------------------------------------------------------------- #
def test_large_bam_broadcast_roundtrip():
    """A long broadcast PDU is announced with BAM and reassembled on the
    far node.

    Per §1.4: broadcast TP transfers use control byte 32 (BAM) and do
    NOT conclude with EndOfMsgACK; reassembly otherwise follows the same
    "concatenate TP.DT bodies in sequence-number order, truncate to
    announced total size, deliver as a single PDU under the announced
    PGN" rule.

    Scenario: 504-byte broadcast (72 packets, exact 7-multiple).  PGN
    0xFEB0 is PDU2 (PF=0xFE in range [240, 255]) -> §1.4 routes the
    BAM to GLOBAL.  Assert exactly one PDU lands on B (pgn 0xFEB0,
    payload) and zero on A.
    """
    pgn = 0xFEB0    # PDU2 broadcast PGN used in core BAM tests
    payload = _distinct_payload(504, seed=29)   # 72 packets, no padding
    assert len(payload) % 7 == 0

    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=1)
    try:
        # PDU2 broadcast: pdu_format = 0xFE; pdu_specific is the group
        # extension byte (carried in PS) and the destination is implicitly
        # GLOBAL.  Match the existing BAM core test's PS value of 0xB0.
        bus.a_send(
            pdu_format=0xFE,
            pdu_specific=0xB0,
            data=payload,
        )
        # BAM TP.DT inter-frame interval is the 50 ms Tb minimum, so the
        # 71 inter-DT gaps alone consume ~3.5 s; allow generous slack.
        bus.deliver(timeout=20.0, quiet=0.5)
        assert bus.received_b == [(pgn, payload)], (
            "B did not receive the 504-byte BAM payload intact: got %d "
            "PDU(s); first len=%d (expected 504)"
            % (
                len(bus.received_b),
                len(bus.received_b[0][1]) if bus.received_b else 0,
            )
        )
        # BAM is a broadcast: TwoNodeBus delivers every A->bus frame to B's
        # side and vice-versa.  A's send goes to B; A should not have
        # received its own broadcast back (TwoNodeBus only delivers TX to
        # the OTHER node).
        assert bus.received_a == [], (
            "A should not have received anything: %r" % (bus.received_a,)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 11. Concurrent long transfers in opposite directions (different pairs)
# --------------------------------------------------------------------------- #
def test_concurrent_long_transfers_distinct_address_pairs():
    """Two simultaneous long peer-to-peer RTS/CTS transfers between
    DIFFERENT (source, destination) address pairs on the same shared
    bus reassemble independently.

    Per §4: *"Transport-protocol session keys are scoped per
    (source_address, destination_address) pair; the stack must distinguish
    concurrent transfers between different address pairs."*

    Topology: a single ``TwoNodeBus`` (nodes A=0x90, B=0x9B); A and B
    each kick off a long PDU1 transfer to the other (sizes and contents
    distinct) before either completes.  The (A, B) and (B, A) session
    keys are disjoint, so a correct implementation reassembles each
    payload exactly once on the far node with NO cross-contamination.

    Sizes (350 and 420 bytes) are chosen to span multiple CTS windows
    each (at max_cmdt=4 -> 13 and 15 windows respectively) and to be
    different from one another so a swap would surface as a length
    mismatch even before a byte comparison.
    """
    pgn = 0xDF00
    payload_ab = _distinct_payload(350, seed=11)   # 50 packets
    payload_ba = _distinct_payload(420, seed=97)   # 60 packets
    assert len(payload_ab) != len(payload_ba)

    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=4)
    try:
        # Kick off both transfers back-to-back (no wait in between) so
        # the two send buffers and the two receive buffers all live
        # concurrently inside the ECUs.
        bus.a_send(
            pdu_format=(pgn >> 8) & 0xFF,
            pdu_specific=bus.sa_b,
            data=payload_ab,
        )
        bus.b_send(
            pdu_format=(pgn >> 8) & 0xFF,
            pdu_specific=bus.sa_a,
            data=payload_ba,
        )
        bus.deliver(timeout=25.0, quiet=0.6)

        assert bus.received_b == [(pgn, payload_ab)], (
            "B should have received exactly the A->B payload (350 B); "
            "got %d PDU(s); first len=%d"
            % (
                len(bus.received_b),
                len(bus.received_b[0][1]) if bus.received_b else 0,
            )
        )
        assert bus.received_a == [(pgn, payload_ba)], (
            "A should have received exactly the B->A payload (420 B); "
            "got %d PDU(s); first len=%d"
            % (
                len(bus.received_a),
                len(bus.received_a[0][1]) if bus.received_a else 0,
            )
        )
    finally:
        bus.stop()
