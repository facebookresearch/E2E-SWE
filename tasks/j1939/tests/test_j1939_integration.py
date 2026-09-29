"""End-to-end integration scenarios for the J1939 stack: address-claim
arbitration loops, contention edge cases, full ECU lifecycle exchanges that
combine claim handling + diagnostics + peer-to-peer traffic, and multi-CA
addressing filters.

All scenarios are driven through the documented public API and assert
byte-exact CAN frames where applicable.  Frames are derived from §1.1
(CAN-ID layout), §1.3 (predefined PGNs and addresses), §1.4 (J1939-21
transport protocol), §2.5 (ControllerApplication semantics +
Address-Claim behavior + Request handling), and §2.6 (DTC packing +
DtcLamp encoding table + Dm1 public API).
"""

import time

import j1939
from feeder import Feeder


# --------------------------------------------------------------------------- #
# Shared NAME (matches CLAIM_NAME_KWARGS in test_j1939_core.py so the byte
# patterns below line up with the existing fixture-style assertions in core).
# --------------------------------------------------------------------------- #
_NAME_KWARGS = dict(
    industry_group=j1939.Name.IndustryGroup.Industrial,
    vehicle_system_instance=2,
    vehicle_system=127,
    function=201,
    function_instance=16,
    ecu_instance=2,
    manufacturer_code=666,
    identity_number=1234567,
)
# arbitrary_address_capable=0 -> byte 7 = 82
_NAME_NONARBITRARY_BYTES = [135, 214, 82, 83, 130, 201, 254, 82]
# arbitrary_address_capable=1 -> byte 7 = 82 | 0x80 = 210
_NAME_ARBITRARY_BYTES    = [135, 214, 82, 83, 130, 201, 254, 210]
# A contender NAME that compares **smaller** than either of the above (byte 5
# changes from 201 to 111; byte 7 = 82 keeps the contender single-cap, so when
# our CA is arbitrary-capable our byte 7 = 210 dominates and contender wins
# decisively).  Same bytes test_j1939_core.py already uses.
_CONTENDER_SMALLER_BYTES = [135, 214, 82, 83, 130, 111, 254, 82]
# A contender NAME that compares **larger** than the single-cap NAME (byte 5
# 201 -> 222; byte 7 = 82 keeps single-cap framing).  Same bytes
# test_j1939_core.py uses for the "we win" case.
_CONTENDER_LARGER_BYTES  = [135, 214, 82, 83, 130, 222, 254, 82]


# --------------------------------------------------------------------------- #
# 1. Address-claim immediate-NORMAL (out-of-veto-range) + we-win arbitration
#    + pre-NORMAL send_pgn gating + post-NORMAL send_pgn succeeds.
# --------------------------------------------------------------------------- #
# Per §2.5: addresses in the range 0..127 and 248..253 skip WAIT_VETO and go
# straight to NORMAL; ``send_pgn`` raises ``RuntimeError`` before NORMAL
# (state != NORMAL) and succeeds after.  We pick address 50 (0x32, inside
# 0..127), then inject a higher-NAME contender claiming the same address;
# since our NAME value is smaller, we win and must re-announce while staying
# in NORMAL.  Finally we emit a peer-to-peer PDU to confirm send_pgn now
# works.  This consolidates the bare-arbitration test and the lifecycle
# gating test into a single end-to-end check of §2.5 state-transition rules.
#
# Address-claim CAN-IDs at SA 50 -> (6<<26)|(0xEEFF<<8)|0x32 = 0x18EEFF32.
# Peer-to-peer PGN 0xEF00 to dest=0x42 from SA 50 ->
#   (6<<26)|(0xEF42<<8)|0x32 = 0x18EF4232.
def test_addr_claim_at_50_wins_arbitration_and_gates_send_pgn(feeder):
    """A single-address-capable CA preferring address 50 (outside §2.5
    128..247 veto range): pre-NORMAL ``send_pgn`` raises ``RuntimeError``;
    after ``start()`` the CA reaches NORMAL immediately, then a contender
    with a higher NAME triggers a re-announce (we win) while keeping NORMAL;
    a post-NORMAL ``send_pgn`` emits the byte-exact peer-to-peer frame."""
    name = j1939.Name(arbitrary_address_capable=0, **_NAME_KWARGS)
    ca = feeder.ecu.add_ca(name=name, device_address=50)

    # Pre-NORMAL: state is NONE -> send_pgn must raise.
    assert ca.state != j1939.ControllerApplication.State.NORMAL
    try:
        ca.send_pgn(0, 0xEF, 0x42, 6, [1, 2, 3, 4, 5, 6, 7, 8])
    except RuntimeError:
        pass
    else:
        raise AssertionError(
            "expected RuntimeError from send_pgn before NORMAL"
        )

    feeder.can_messages = [
        # Initial claim at 50 -> immediate NORMAL (no VETO).
        (Feeder.MsgType.CANTX, 0x18EEFF32, _NAME_NONARBITRARY_BYTES, 0.0),
        # Contender at 50 with LARGER NAME -> we win -> re-announce.
        (Feeder.MsgType.CANRX, 0x18EEFF32, _CONTENDER_LARGER_BYTES, 0.0),
        (Feeder.MsgType.CANTX, 0x18EEFF32, _NAME_NONARBITRARY_BYTES, 0.0),
    ]
    ca.start()
    feeder.drive(timeout=4.0)
    feeder.wait_for_state(ca, j1939.ControllerApplication.State.NORMAL, timeout=2.0)
    assert ca.state == j1939.ControllerApplication.State.NORMAL
    assert ca.device_address == 50

    # Post-NORMAL: send_pgn now succeeds and the byte-exact peer-to-peer
    # frame surfaces on the bus.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EF4232, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
    ]
    ca.send_pgn(0, 0xEF, 0x42, 6, [1, 2, 3, 4, 5, 6, 7, 8])
    feeder.check()


# --------------------------------------------------------------------------- #
# 3. Full ECU lifecycle: bypass-claimed CA emits a multi-DTC DM1 (J1939-21
#    BAM, 2 packets), receives a Request for the Address-Claim PGN and
#    auto-responds with its Address Claimed (§2.5 Request handling), then
#    issues a peer-to-peer PDU.
# --------------------------------------------------------------------------- #
# DM1 payload derivation (per §2.6):
#   lamp_status = {'mil': ON}, others default OFF
#     data[0] = (1 << 6)                                            = 0x40
#     data[1] = (3<<0) | (3<<2) | (3<<4) | (3<<6)                   = 0xFF
#   DTCs:
#     (spn=100,  fmi=5,  oc=2) -> 0x02050064 -> [0x64, 0x00, 0x05, 0x02]
#     (spn=4567, fmi=12, oc=1) -> 0x010C11D7 -> [0xD7, 0x11, 0x0C, 0x01]
#   Concatenated (10 bytes):
#     [0x40, 0xFF, 0x64, 0x00, 0x05, 0x02, 0xD7, 0x11, 0x0C, 0x01]
#   >8 bytes -> Dm1 transmits at priority 7 (§1.4 also makes BAM priority
#   match caller-supplied priority).
#
# §1.4 BAM TP.CM frame (PGN 60416 = 0xEC00, PS=GLOBAL=0xFF, control byte 32):
#   data = [32, total_size_lo=10, total_size_hi=0, num_packets=2, 0xFF,
#           DM01_lo=0xCA, DM01_mid=0xFE, DM01_hi=0x00]
#   CAN-ID at SA 0x90 -> (7<<26)|(0xECFF<<8)|0x90 = 0x1CECFF90
#
# §1.4 BAM TP.DT frames (PGN 60160 = 0xEB00, PS=GLOBAL=0xFF, priority 7):
#   CAN-ID at SA 0x90 -> (7<<26)|(0xEBFF<<8)|0x90 = 0x1CEBFF90
#   seq=1 carries payload bytes 0..6: [1, 0x40, 0xFF, 0x64, 0x00, 0x05, 0x02, 0xD7]
#   seq=2 carries payload bytes 7..9 + 4 x 0xFF pad (§1.4 last-frame padding):
#         [2, 0x11, 0x0C, 0x01, 0xFF, 0xFF, 0xFF, 0xFF]
#
# §1.4 REQUEST frame from sa=0x42 to dest=0x90 asking for the Address-Claim
# PGN (60928 = 0xEE00):
#   data = [pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF]
#        = [0x00, 0xEE, 0x00]
#   CAN-ID: priority 6, PGN (0xEA<<8)|0x90 = 0xEA90, SA 0x42
#         = (6<<26)|(0xEA90<<8)|0x42 = 0x18EA9042
#
# §2.5 Address-Claim response (priority 6, PGN 60928, PS=GLOBAL, SA=0x90):
#   CAN-ID = (6<<26)|(0xEEFF<<8)|0x90 = 0x18EEFF90
#   data   = our NAME bytes (_NAME_NONARBITRARY_BYTES)
#
# Peer-to-peer PDU (PGN 0xEF00 to dest=0x42, priority 6):
#   CAN-ID = (6<<26)|((0xEF42)<<8)|0x90 = 0x18EF4290
#   data   = [1, 2, 3, 4, 5, 6, 7, 8] (test-chosen payload)
def test_full_lifecycle_dm1_bam_then_request_response_then_peer_to_peer(feeder):
    """A bypass-claimed CA at 0x90: (a) transmits a 10-byte DM1 via BAM,
    (b) on a Request for PGN 60928 from sa=0x42 auto-responds with Address
    Claimed (§2.5), and (c) emits a peer-to-peer 8-byte PDU.  Every frame
    is byte-asserted; the test validates that diagnostics, Request handling
    and ordinary PDU transmission cooperate inside one CA."""
    name = j1939.Name(arbitrary_address_capable=0, **_NAME_KWARGS)
    ca = j1939.ControllerApplication(
        name, device_address_preferred=0x90, bypass_address_claim=True
    )
    feeder.ecu.add_ca(controller_application=ca)

    # ------------------- Phase 1: DM1 BAM + auto Request response ----------- #
    feeder.can_messages = [
        # BAM TP.CM announcing 10 bytes / 2 packets for DM01.
        (Feeder.MsgType.CANTX, 0x1CECFF90,
         [32, 10, 0, 2, 0xFF, 0xCA, 0xFE, 0x00], 0.0),
        # TP.DT seq 1: 7 payload bytes.
        (Feeder.MsgType.CANTX, 0x1CEBFF90,
         [1, 0x40, 0xFF, 0x64, 0x00, 0x05, 0x02, 0xD7], 0.0),
        # TP.DT seq 2: 3 payload bytes + 4 x 0xFF pad (§1.4 last-frame pad).
        (Feeder.MsgType.CANTX, 0x1CEBFF90,
         [2, 0x11, 0x0C, 0x01, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        # Incoming Request from sa=0x42 asking for the Address-Claim PGN.
        (Feeder.MsgType.CANRX, 0x18EA9042, [0x00, 0xEE, 0x00], 0.0),
        # Auto-emitted Address Claimed in response to the Request.
        (Feeder.MsgType.CANTX, 0x18EEFF90, _NAME_NONARBITRARY_BYTES, 0.0),
    ]

    dm1 = j1939.Dm1(ca)
    lamp_status = {'mil': j1939.DtcLamp.ON}
    dtcs = [
        {'spn': 100,  'fmi': 5,  'oc': 2},
        {'spn': 4567, 'fmi': 12, 'oc': 1},
    ]

    def cb():
        return (lamp_status, dtcs)

    dm1.start_send(cb, cycletime=1)
    try:
        # Wait for the 5 phase-1 frames (3 BAM + RX + claim-response) to drain.
        feeder.drive(timeout=4.0)
    finally:
        dm1.stop_send(cb)

    # ------------------- Phase 2: explicit peer-to-peer send ---------------- #
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EF4290, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
    ]
    ca.send_pgn(0, 0xEF, 0x42, 6, [1, 2, 3, 4, 5, 6, 7, 8])
    feeder.check()


# --------------------------------------------------------------------------- #
# 4. Multi-CA + diagnostics addressing filter.
# --------------------------------------------------------------------------- #
# Two bypass-claimed CAs share one ECU at addresses 0x90 and 0x9B; each has
# its own Dm1.  An incoming broadcast DM01 (dest=GLOBAL per §2.6) must be
# delivered to BOTH Dm1 subscribers, while an incoming peer-to-peer PDU
# (PGN 0xEF00) addressed to dest=0x90 must surface only on the CA that owns
# address 0x90 -- §2.5 message_acceptable filters out addresses we don't own.
#
# Frames:
#   DM01 from sa=0x42, broadcast (PS=GLOBAL), single 8-byte frame for
#   simplicity. Same lamp+DTC derivation as before; we choose one DTC to keep
#   the test focused on the addressing filter.
#     lamp_status = {'mil': ON}    -> data[0]=0x40, data[1]=0xFF
#     DTC (spn=100, fmi=5, oc=2)   -> [0x64, 0x00, 0x05, 0x02]
#   Payload: [0x40, 0xFF, 0x64, 0x00, 0x05, 0x02]  (6 bytes)
#   CAN-ID (priority 6, PGN 0xFECA broadcast, SA 0x42):
#     (6<<26)|(0xFECA<<8)|0x42 = 0x18FECA42
#
#   Peer-to-peer PGN 0xEF00 from sa=0x42 to dest=0x90, 8-byte payload:
#     CAN-ID = (6<<26)|((0xEF<<8|0x90)<<8)|0x42 = (6<<26)|(0xEF90<<8)|0x42
#            = 0x18EF9042
def test_multi_ca_dm1_broadcast_and_peer_to_peer_filtering(feeder):
    """Two CAs on the same ECU at distinct addresses each subscribe their own
    Dm1.  A broadcast DM01 reaches both Dm1 receivers identically; a
    peer-to-peer PDU addressed to only one of the CAs surfaces only on that
    CA's subscriber (validating §2.5 message_acceptable filtering)."""
    name_a = j1939.Name(arbitrary_address_capable=0, **_NAME_KWARGS)
    ca_a = j1939.ControllerApplication(
        name_a, device_address_preferred=0x90, bypass_address_claim=True
    )
    feeder.ecu.add_ca(controller_application=ca_a)

    # Use a different identity_number for the second CA so the two NAMEs are
    # distinct (J1939 requires unique NAMEs per node).  Address-claim is
    # bypassed so the NAME isn't actually transmitted.
    name_b = j1939.Name(
        arbitrary_address_capable=0,
        **dict(_NAME_KWARGS, identity_number=1234568)
    )
    ca_b = j1939.ControllerApplication(
        name_b, device_address_preferred=0x9B, bypass_address_claim=True
    )
    feeder.ecu.add_ca(controller_application=ca_b)

    decoded_a = []
    decoded_b = []
    p2p_a = []
    p2p_b = []

    dm1_a = j1939.Dm1(ca_a)
    dm1_b = j1939.Dm1(ca_b)
    dm1_a.subscribe(
        lambda sa, lamp, dtcs, ts: decoded_a.append((sa, lamp, dtcs))
    )
    dm1_b.subscribe(
        lambda sa, lamp, dtcs, ts: decoded_b.append((sa, lamp, dtcs))
    )
    # Raw subscribers per CA for the peer-to-peer assertion.  ca.subscribe
    # wires the bound message_acceptable into the ECU dispatcher.
    ca_a.subscribe(
        lambda pri, pgn, sa, ts, data:
            p2p_a.append((pgn, sa, list(data) if data is not None else None))
    )
    ca_b.subscribe(
        lambda pri, pgn, sa, ts, data:
            p2p_b.append((pgn, sa, list(data) if data is not None else None))
    )

    feeder.can_messages = [
        # Broadcast DM01 from sa=0x42 -- both Dm1 receivers should see it.
        (Feeder.MsgType.CANRX, 0x18FECA42,
         [0x40, 0xFF, 0x64, 0x00, 0x05, 0x02], 0.0),
        # Peer-to-peer PGN 0xEF00 from sa=0x42 to dest=0x90 -- only ca_a
        # should see it via its raw subscriber.
        (Feeder.MsgType.CANRX, 0x18EF9042,
         [10, 20, 30, 40, 50, 60, 70, 80], 0.0),
    ]
    feeder.drive(timeout=3.0)

    # Both Dm1 receivers must have decoded the broadcast identically.
    expected_lamp = {
        'pl':  j1939.DtcLamp.OFF,
        'awl': j1939.DtcLamp.OFF,
        'rsl': j1939.DtcLamp.OFF,
        'mil': j1939.DtcLamp.ON,
    }
    expected_dtcs = [{'spn': 100, 'fmi': 5, 'oc': 2}]
    for label, decoded in (("ca_a", decoded_a), ("ca_b", decoded_b)):
        assert len(decoded) == 1, (
            "%s: expected 1 DM1, got %d (%r)" % (label, len(decoded), decoded)
        )
        sa, lamp, dtcs = decoded[0]
        assert sa == 0x42
        assert lamp == expected_lamp
        assert dtcs == expected_dtcs

    # The peer-to-peer to dest=0x90 must reach ca_a only.
    p2p_to_0x90 = [
        entry for entry in p2p_a
        if entry == (0xEF00, 0x42, [10, 20, 30, 40, 50, 60, 70, 80])
    ]
    assert len(p2p_to_0x90) == 1, (
        "ca_a expected to receive the peer-to-peer PDU once, got %r" % (p2p_a,)
    )
    # ca_b must NOT have received the peer-to-peer to dest=0x90.
    p2p_b_to_0x90 = [
        entry for entry in p2p_b
        if entry == (0xEF00, 0x42, [10, 20, 30, 40, 50, 60, 70, 80])
    ]
    assert p2p_b_to_0x90 == [], (
        "ca_b should not have received the peer-to-peer to dest=0x90, got %r"
        % (p2p_b,)
    )


# --------------------------------------------------------------------------- #
# 5. Bidirectional diagnostic session over a two-node bus.
# --------------------------------------------------------------------------- #
# Node A sends a long peer-to-peer payload to B via §1.4 RTS/CTS; B
# concurrently broadcasts a multi-DTC DM1 that A decodes via Dm1; A then
# clears a specific DTC on B with DM22.  Three independent diagnostic flows
# in one realistic session, all driven through the public API.
#
# Expected outcomes:
#   * received_b contains A's 20-byte PDU under PGN 0xDF00 (the PDU1 base
#     PGN, after §1.4 PS-masking on the receiver).
#   * received_b also contains A's DM22 frame under PGN 0xC300 with the
#     §2.6 8-byte layout (control=17, bytes 1..4=0xFF, SPN/FMI in bytes 5..7).
#   * decoded_a (Dm1 subscriber on A) holds at least one decoded DM1 with
#     the lamp + DTC list B emits.
def test_bidirectional_session_long_p2p_dm1_broadcast_and_dm22():
    """A full bidirectional diagnostic session over TwoNodeBus: A sends a
    20-byte peer-to-peer message to B (J1939-21 RTS/CTS), B concurrently
    broadcasts a multi-DTC DM1 that A decodes, and A finally issues a DM22
    individual clear request to B.  All three flows complete intact."""
    from feeder import TwoNodeBus
    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=1)
    try:
        # Dm1 on B emits; Dm1 on A subscribes and must decode B's DTCs.
        dm1_sender = j1939.Dm1(bus.ca_b)
        dm1_receiver = j1939.Dm1(bus.ca_a)

        decoded_a = []
        dm1_receiver.subscribe(
            lambda sa, lamp, dtcs, ts: decoded_a.append((sa, lamp, dtcs))
        )

        sent_lamp = {'mil': j1939.DtcLamp.ON}
        sent_dtcs = [
            {'spn': 100,    'fmi': 5,  'oc': 2},
            {'spn': 4567,   'fmi': 12, 'oc': 1},
            {'spn': 520192, 'fmi': 14, 'oc': 15},
        ]

        def dm1_cb():
            return (sent_lamp, sent_dtcs)

        # B starts broadcasting DM1 cyclically.
        dm1_sender.start_send(dm1_cb, cycletime=1)
        try:
            # A kicks off the 20-byte peer-to-peer transfer (RTS/CTS).
            long_payload = [(i * 7 + 1) & 0xFF for i in range(20)]
            bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=long_payload)

            # Wait for BOTH: A's long PDU to land on B AND B's DM1 to land on A.
            expected_long = (0xDF00, long_payload)
            deadline = time.time() + 5.0
            while time.time() < deadline:
                if decoded_a and (expected_long in bus.received_b):
                    break
                time.sleep(0.02)
        finally:
            dm1_sender.stop_send(dm1_cb)

        # A now issues a DM22 clear-active-DTC request to B (single 8-byte
        # frame, §2.6 layout: control=17 ACT_REQ, bytes 1..4=0xFF, byte
        # 5 = spn & 0xFF, byte 6 = (spn>>8) & 0xFF,
        # byte 7 = ((spn>>22) & 0xE0) | (fmi & 0x1F)).
        dm22_a = j1939.Dm22(bus.ca_a)
        dm22_a.request_clear_act_dtc(bus.sa_b, 4567, 12)

        bus.deliver(timeout=4.0)

        # A's long PDU reassembled on B.
        assert (0xDF00, long_payload) in bus.received_b, (
            "expected (0xDF00, long_payload) in bus.received_b, got %r"
            % (bus.received_b,)
        )
        # A's DM22 frame delivered to B (PGN masked to 0xC300 for PDU1).
        expected_dm22 = (0xC300,
                         [17, 0xFF, 0xFF, 0xFF, 0xFF, 0xD7, 0x11, 0x0C])
        assert expected_dm22 in bus.received_b, (
            "expected DM22 %r in bus.received_b, got %r"
            % (expected_dm22, bus.received_b,)
        )
        # A decoded at least one DM1 from B with the exact lamp + DTC list.
        assert len(decoded_a) >= 1, "A did not decode any DM1 from B"
        sa, lamp, dtcs = decoded_a[0]
        assert sa == bus.sa_b
        assert lamp == {
            'pl':  j1939.DtcLamp.OFF,
            'awl': j1939.DtcLamp.OFF,
            'rsl': j1939.DtcLamp.OFF,
            'mil': j1939.DtcLamp.ON,
        }
        assert dtcs == sent_dtcs, (
            "decoded DTCs %r != sent %r" % (dtcs, sent_dtcs)
        )
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 6. Request-for-Address-Claim chain followed by a Dm14 memory-access read.
# --------------------------------------------------------------------------- #
# Phase 1: an external node (sa=0x42) sends a §1.4 REQUEST frame to dest=0xF9
# asking for PGN 60928; per §2.5 our CA at 0xF9 must auto-respond with an
# Address Claimed PDU.
#
# Phase 2: the host CA initiates a Dm14 READ from address 0xD4 (the same
# scripted-responder pattern test_j1939_core.py:test_dm14_read_no_seed_key
# uses), no seed/key required.  Bytes are derived directly from §1.5
# (DM14/15/16 8-byte layout).
#
# CAN-IDs in phase 1:
#   incoming REQUEST: priority 6, PGN (0xEA<<8)|0xF9 = 0xEAF9, SA 0x42
#       -> (6<<26)|(0xEAF9<<8)|0x42 = 0x18EAF942
#       data = [pgn_lo, pgn_mid, pgn_hi] of PGN 60928 = 0xEE00
#            = [0x00, 0xEE, 0x00]
#   outgoing AddressClaim: priority 6, PGN 0xEEFF (PS=GLOBAL), SA 0xF9
#       -> (6<<26)|(0xEEFF<<8)|0xF9 = 0x18EEFFF9
#       data = our NAME bytes (single-cap)
def test_request_for_address_claim_then_dm14_read(feeder):
    """A CA at 0xF9 first auto-responds with Address Claimed to an incoming
    Request for PGN 60928 (per §2.5 Request handling), then drives a Dm14
    read against a scripted responder at 0xD4 (§1.5 memory-access)."""
    name = j1939.Name(arbitrary_address_capable=0, **_NAME_KWARGS)
    ca = j1939.ControllerApplication(
        name, device_address_preferred=0xF9, bypass_address_claim=True
    )
    feeder.ecu.add_ca(controller_application=ca)

    # Phase 1: incoming REQUEST -> auto-emitted AddressClaim.
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x18EAF942, [0x00, 0xEE, 0x00], 0.0),
        (Feeder.MsgType.CANTX, 0x18EEFFF9, _NAME_NONARBITRARY_BYTES, 0.0),
    ]
    feeder.drive(timeout=3.0)

    # Phase 2: Dm14 read (no seed/key); script mirrors test_dm14_read_no_seed_key
    # in test_j1939_core.py but stands alone here so the lifecycle assertion
    # captures the end-to-end success of the chain.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x13, 0x03, 0x00, 0x00, 0x92, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD7F9D4,
         [0x01, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x19, 0x03, 0x00, 0x00, 0x92, 0xFF, 0xFF], 0.0),
    ]
    feeder.pdus_from_messages()
    dm14 = j1939.Dm14Query(ca)
    dm14.set_seed_key_algorithm(lambda seed: seed ^ 0xFFFF)
    feeder.subscribe()
    dm14.read(0xD4, 1, 0x92000003, 1)
    feeder.drive(timeout=3.0)


# --------------------------------------------------------------------------- #
# 6. Full lifecycle with REAL arbitration step + long peer-to-peer + DM1 RX.
# --------------------------------------------------------------------------- #
# An arbitrary-address-capable CA prefers 200 (inside the §2.5 128..247 veto
# window), loses to a lower-NAME contender, retries 201, settles there, then
# (a) sends a 14-byte peer-to-peer message under PGN 0xDF00 to dest=0xD0
# via §1.4 RTS/CTS with a scripted responder, and (b) receives a single-frame
# DM1 broadcast from sa=0x42 that its Dm1 subscriber must decode.
#
# Claim-frame CAN-IDs (priority 6, PGN 0xEEFF broadcast):
#   claim at 200 (0xC8) -> (6<<26)|(0xEEFF<<8)|0xC8 = 0x18EEFFC8
#   claim at 201 (0xC9) -> (6<<26)|(0xEEFF<<8)|0xC9 = 0x18EEFFC9
#
# RTS/CTS frame CAN-IDs (§1.4 transport protocol):
#   originator's RTS/TP.DT to dest=0xD0, SA=0xC9:
#     RTS  (priority 6, PGN (0xEC<<8)|0xD0 = 0xECD0)
#          = (6<<26)|(0xECD0<<8)|0xC9 = 0x18ECD0C9
#     TP.DT (priority 7, PGN (0xEB<<8)|0xD0 = 0xEBD0)
#          = (7<<26)|(0xEBD0<<8)|0xC9 = 0x1CEBD0C9
#   responder's CTS/EOM_ACK from sa=0xD0 to originator 0xC9:
#     PGN (0xEC<<8)|0xC9 = 0xECC9, priority 7
#          = (7<<26)|(0xECC9<<8)|0xD0 = 0x1CECC9D0
#
# Payload (14 bytes, num_packets = ceil(14/7) = 2, max_pkts_per_cts = 1
# because the ECU default _max_cmdt_packets = 1):
#   _payload(14) = [1, 8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92]
# Carried PGN for TP.CM = 0xDF00 (PDU1 base; pdu_specific cleared for the
# transport-protocol announcement per §1.4).
#
# DM1 RX from sa=0x42 (priority 6, PGN 0xFECA broadcast):
#   CAN-ID = (6<<26)|(0xFECA<<8)|0x42 = 0x18FECA42
#   data   = [0x40, 0xFF, 0x64, 0x00, 0x05, 0x02]
#            (mil=ON other lamps OFF; DTC spn=100/fmi=5/oc=2 -> 0x02050064)
def test_lifecycle_real_claim_step_then_long_p2p_then_dm1_rx(feeder):
    """An arbitrary-address-capable CA arbitrates from preferred 200 to 201
    (loses one veto, settles on the next address), then issues a 14-byte
    peer-to-peer RTS/CTS transfer to a scripted responder at 0xD0, and
    finally decodes an incoming DM1 broadcast.  Asserts the final claimed
    address, the byte-exact RTS/CTS frame chain, and the decoded DM1."""
    name = j1939.Name(arbitrary_address_capable=1, **_NAME_KWARGS)
    ca = feeder.ecu.add_ca(name=name, device_address=200)

    decoded = []

    def dm1_cb(sa, lamp, dtcs, ts):
        decoded.append((sa, lamp, dtcs))

    dm1 = j1939.Dm1(ca)

    # Phase 1: real arbitration -> NORMAL at 201.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFFC8, _NAME_ARBITRARY_BYTES, 0.0),
        (Feeder.MsgType.CANRX, 0x18EEFFC8, _CONTENDER_SMALLER_BYTES, 0.0),
        (Feeder.MsgType.CANTX, 0x18EEFFC9, _NAME_ARBITRARY_BYTES, 0.0),
    ]
    ca.start()
    feeder.drive(timeout=4.0)
    feeder.wait_for_state(ca, j1939.ControllerApplication.State.NORMAL, timeout=2.0)
    assert ca.state == j1939.ControllerApplication.State.NORMAL
    assert ca.device_address == 201, (
        "expected to settle at 201, got 0x%02X" % (ca.device_address,)
    )

    # Subscribe to DM1 AFTER NORMAL (subscribe filters through
    # message_acceptable which returns False before NORMAL per §2.5).
    dm1.subscribe(dm1_cb)

    # Phase 2: 14-byte RTS/CTS transfer to dest=0xD0.
    long_payload = [1, 8, 15, 22, 29, 36, 43, 50, 57, 64, 71, 78, 85, 92]
    feeder.can_messages = [
        # RTS (control 16, total_size 14, num_packets 2, max_cmdt 1, PGN 0xDF00)
        (Feeder.MsgType.CANTX, 0x18ECD0C9,
         [16, 14, 0, 2, 1, 0x00, 0xDF, 0x00], 0.0),
        # CTS #1 (grant 1 packet starting at seq 1)
        (Feeder.MsgType.CANRX, 0x1CECC9D0,
         [17, 1, 1, 0xFF, 0xFF, 0x00, 0xDF, 0x00], 0.0),
        # TP.DT seq 1 (7 payload bytes)
        (Feeder.MsgType.CANTX, 0x1CEBD0C9,
         [1, 1, 8, 15, 22, 29, 36, 43], 0.0),
        # CTS #2 (grant next packet)
        (Feeder.MsgType.CANRX, 0x1CECC9D0,
         [17, 1, 2, 0xFF, 0xFF, 0x00, 0xDF, 0x00], 0.0),
        # TP.DT seq 2 (remaining 7 payload bytes -- fits exactly, no pad)
        (Feeder.MsgType.CANTX, 0x1CEBD0C9,
         [2, 50, 57, 64, 71, 78, 85, 92], 0.0),
        # EOM_ACK (control 19, total_size 14, num_packets 2)
        (Feeder.MsgType.CANRX, 0x1CECC9D0,
         [19, 14, 0, 2, 0xFF, 0x00, 0xDF, 0x00], 0.0),
    ]
    ca.send_pgn(0, 0xDF, 0xD0, 6, long_payload)
    feeder.drive(timeout=4.0)

    # Phase 3: incoming DM1 broadcast -> decoded by our Dm1 subscriber.
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x18FECA42,
         [0x40, 0xFF, 0x64, 0x00, 0x05, 0x02], 0.0),
    ]
    feeder.drive(timeout=2.0)
    deadline = time.time() + 1.0
    while time.time() < deadline and not decoded:
        time.sleep(0.02)
    assert len(decoded) == 1, "expected one decoded DM1, got %r" % (decoded,)
    sa, lamp, dtcs = decoded[0]
    assert sa == 0x42
    assert lamp == {
        'pl':  j1939.DtcLamp.OFF,
        'awl': j1939.DtcLamp.OFF,
        'rsl': j1939.DtcLamp.OFF,
        'mil': j1939.DtcLamp.ON,
    }
    assert dtcs == [{'spn': 100, 'fmi': 5, 'oc': 2}]


