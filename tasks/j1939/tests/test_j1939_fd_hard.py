"""Harder J1939-22 (CAN-FD) round-trip coverage.

These tests target FD behaviour that is *fully documented in instruction.md
§3* but not yet covered by ``test_j1939_fd.py`` / ``test_j1939_roundtrip.py``:

* Concurrent peer-to-peer RTS/CTS sessions in flight at the same time on the
  same pair of ECUs but for distinct (source, destination) address keys --
  exercises the per-pair session pool (§3 allows up to 8 concurrent RTS/CTS
  sessions per originator+responder pair).
* Larger BAM broadcasts that span more than three TP.DT segments and rely on
  the EOM_STATUS-driven delivery rule documented in §3.4.
* CTS windowing on FD with ``max_cmdt_packets=4`` and a 4-segment payload.
* An exact-multiple-of-60 payload, the boundary case where the last TP.DT
  segment is full rather than a short tail.

All tests use :class:`TwoNodeBus` (which is byte-correct by construction --
both ends run the same library) so the assertions reduce to payload equality
at the subscriber, never byte-exact wire frames.
"""

import time

import j1939
from feeder import TwoNodeBus


def _payload(n):
    """Same deterministic generator used by the rest of the FD test suite."""
    return [(i * 7 + 1) & 0xFF for i in range(n)]


# --------------------------------------------------------------------------- #
# 1. Large round trips: one each side of the FD-TP fork.
# --------------------------------------------------------------------------- #
def test_fd_bam_large_4_segment_roundtrip():
    """A 200-byte broadcast PDU is segmented into ``ceil(200/60) = 4``
    TP.DT segments (60 + 60 + 60 + 20) and reassembled on the far node.
    The receiver must accept three full-size segments and one short tail,
    and only deliver after the originator's explicit EOM_STATUS (§3.4)."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=20)
    try:
        data = _payload(200)
        bus.a_send(pdu_format=0xFE, pdu_specific=0xB0, data=data)
        bus.deliver(timeout=10.0)
        assert bus.received_b == [(0xFEB0, data)], bus.received_b
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 2. FD-TP / multi-PG size-boundary sweep.
#
# Bundled into two sweeps that step through the §3 boundaries:
#   - "short": 60 (upper edge of §3.3 multi-PG) vs 61 (first byte into FD-TP
#     with the smallest possible 1-byte tail forcing FD-DLC padding);
#   - "long":  120 (exact 2 full TP.DT segments, no tail) vs 121 (3 segments
#     with a 1-byte tail).
#
# All asserts are payload equality at the subscriber.
# --------------------------------------------------------------------------- #
def _payload_salted(n, salt):
    """Deterministic payload generator with a per-call salt so reassembly
    mistakes that splice bytes from one transfer into another are caught."""
    return [((i + salt) * 11 + salt) & 0xFF for i in range(n)]


def test_fd_p2p_boundary_short_sweep():
    """Sweep the §3.3 / §3 60-byte multi-PG <-> FD-TP boundary: 60-byte
    payload rides the multi-PG carrier, 61-byte payload spills into FD
    TP (one full 60-byte TP.DT segment followed by a 1-byte tail that
    forces FD-DLC padding on the second TP.DT)."""
    for payload_len in (60, 61):
        bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=4)
        try:
            data = _payload_salted(payload_len, salt=payload_len)
            bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=data)
            bus.deliver(timeout=10.0)
            assert bus.received_b == [(0xDF00, data)], (
                "payload_len=%d: %r" % (payload_len, bus.received_b)
            )
        finally:
            bus.stop()


def test_fd_p2p_boundary_long_sweep():
    """Sweep the multi-segment boundary: 120-byte payload is exactly two
    full TP.DT segments (no short tail; the buffer hits message_size on
    a segment boundary), 121-byte payload requires three segments with
    a 1-byte tail (off-by-one between segment count and payload-size
    accounting)."""
    for payload_len in (120, 121):
        bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=4)
        try:
            data = _payload_salted(payload_len, salt=payload_len)
            bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=data)
            bus.deliver(timeout=10.0)
            assert bus.received_b == [(0xDF00, data)], (
                "payload_len=%d: %r" % (payload_len, bus.received_b)
            )
        finally:
            bus.stop()


# --------------------------------------------------------------------------- #
# 6. Round-5 additions: concurrency at scale.  These tests stress the §3
# session pools (4 BAM + 8 RTS/CTS per originator+responder pair) and the
# stack's ability to demultiplex many interleaved transfers.  All
# assertions are payload-equality at the subscriber (``TwoNodeBus`` is
# byte-correct by construction).  Contracts asserted:
#   - §3 (line 450-451): "Up to 4 concurrent BAM sessions per originator
#     address and up to 8 concurrent RTS/CTS sessions per originator+
#     responder pair are permitted."  The saturation tests below take the
#     pool to exactly its documented maximum.
#   - §3.4: BAM completion is signalled by the originator's explicit
#     EOM_STATUS, so concurrent BAMs require independent
#     message_size/num_segments accounting per session.
# --------------------------------------------------------------------------- #
def test_fd_bam_pool_saturated_4_concurrent_broadcasts():
    """Four concurrent FD BAM transfers from the same originator -- the
    documented per-originator BAM pool maximum (§3).  All four broadcasts
    must surface at the receiver with their distinct payloads intact.

    Each transfer is 120 bytes (2 full 60-byte segments) so the BAM DT
    pacing keeps all four sessions in flight simultaneously rather than
    serialising them.  Distinct PGNs and salted payloads guarantee that
    any byte-splicing across sessions is detected at the subscriber."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=20)
    try:
        payloads = {pgn: _payload_salted(120, salt=pgn) for pgn in (
            0xFE00, 0xFE01, 0xFE02, 0xFE03,
        )}

        # Fire all four back-to-back so the originator must hold four
        # BAM send-buffers open at once -- exactly the §3 maximum.
        for pgn, data in payloads.items():
            bus.a_send(pdu_format=(pgn >> 8) & 0xFF,
                       pdu_specific=pgn & 0xFF,
                       data=data)
        bus.deliver(timeout=20.0)

        got = set((pgn, tuple(d)) for pgn, d in bus.received_b)
        want = set((pgn, tuple(d)) for pgn, d in payloads.items())
        assert got == want, bus.received_b
    finally:
        bus.stop()


def test_fd_rts_cts_pool_saturated_8_concurrent_same_pair():
    """Eight concurrent FD RTS/CTS transfers on a single (originator,
    responder) pair -- the documented per-pair RTS/CTS pool maximum (§3).
    All eight payloads must surface at the receiver intact.

    With ``max_cmdt_packets=1`` each transfer needs multiple CTS rounds,
    so the eight transfers' TP.CM/TP.DT frames interleave heavily on the
    bus and the receiver must demultiplex them into eight independent
    reassembly buffers keyed by (src, session_num) per §3.1 / §3.2."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=1)
    try:
        # Eight distinct PDU1 PGNs all addressed to sa_b, each carrying
        # a unique 100-byte payload (2 segments: 60 + 40).
        pfs = (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7)
        payloads = {pf: _payload_salted(100, salt=pf) for pf in pfs}

        for pf, data in payloads.items():
            bus.a_send(pdu_format=pf, pdu_specific=bus.sa_b, data=data)
        bus.deliver(timeout=30.0)

        # PDU1 RTS/CTS PGNs surface at the subscriber with PS cleared,
        # i.e. (pf << 8) | 0x00.
        got = set((pgn, tuple(d)) for pgn, d in bus.received_b)
        want = set(((pf << 8), tuple(data)) for pf, data in payloads.items())
        assert got == want, bus.received_b
    finally:
        bus.stop()


def test_fd_large_rts_cts_concurrent_with_two_short_multipg():
    """One large FD RTS/CTS transfer (600 bytes, 10 segments) runs
    concurrently with two short multi-PG broadcasts (each <= 60 bytes,
    no FD TP engagement, single multi-PG carrier per §3.3).

    The stack must keep the large transfer's session state intact while
    short multi-PG frames pass through unrelated code paths in between
    its segments -- a realistic mix that the existing single-pattern
    tests do not stress."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=4)
    try:
        big = _payload_salted(600, salt=0x600)       # 10 RTS/CTS segments
        short1 = _payload_salted(20, salt=0x21)      # single multi-PG carrier
        short2 = _payload_salted(40, salt=0x42)      # single multi-PG carrier

        # Start the large transfer first; while it is still flowing, fire
        # both short PDU2 broadcasts so their multi-PG carriers land
        # between the big transfer's TP.DT segments.
        bus.a_send(pdu_format=0xDB, pdu_specific=bus.sa_b, data=big)
        bus.a_send(pdu_format=0xFE, pdu_specific=0x10,    data=short1)
        bus.a_send(pdu_format=0xFE, pdu_specific=0x11,    data=short2)
        bus.deliver(timeout=20.0)

        got = set((pgn, tuple(d)) for pgn, d in bus.received_b)
        want = {
            (0xDB00, tuple(big)),
            (0xFE10, tuple(short1)),
            (0xFE11, tuple(short2)),
        }
        assert got == want, bus.received_b
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 7. Round-7 additions: diagnostics-over-CAN-FD integration tests.
#
# DM1 (PGN 65226 / 0xFECA, PDU2 broadcast) and DM22 (PGN 49920 / 0xC300,
# PDU1 peer-to-peer) are application PDUs from §2.6.  Routed through a
# j1939-22 ECU they engage the FD data link from §3:
#   - DM1 with <= 14 DTCs (2 + 14*4 = 58 bytes) fits in a single multi-PG
#     carrier (§3.3).
#   - DM1 with >= 15 DTCs (>60 bytes) requires the FD TP protocol; for
#     broadcast DM1 that is the FD BAM path (§3.4) with EOM_STATUS-
#     triggered delivery.
#   - DM22's fixed 8-byte payload always rides the multi-PG carrier (§3.3).
#
# These tests run the DM1/DM22 public API of §2.6 over TwoNodeBus
# (data_link_layer='j1939-22') and verify the receiving side decodes the
# documented contents.  They do not assert any j1939_22 internals beyond
# what §3.3 / §3.4 already document.
# --------------------------------------------------------------------------- #
def test_fd_dm1_short_two_dtcs_roundtrip():
    """DM1 with two DTCs (10-byte payload) runs from CA-A to CA-B over a
    j1939-22 bus.  10 bytes is well within §3.3's 60-byte multi-PG capacity
    so the carrier carries it as a single c-pg; the receiver decodes the
    lamp status and the two DTCs through ``Dm1.subscribe``."""
    bus = TwoNodeBus(data_link_layer="j1939-22")
    try:
        dm1_send = j1939.Dm1(bus.ca_a)
        dm1_recv = j1939.Dm1(bus.ca_b)

        decoded = []
        dm1_recv.subscribe(
            lambda sa, lamp_status, dtc_dic_list, timestamp:
                decoded.append((sa, lamp_status, dtc_dic_list))
        )

        sent_dtcs = [
            {'spn': 100,  'fmi': 5,  'oc': 2},
            {'spn': 4567, 'fmi': 12, 'oc': 1},
        ]
        sent_lamp = {'mil': j1939.DtcLamp.ON}

        def cb():
            return (sent_lamp, sent_dtcs)

        dm1_send.start_send(cb, cycletime=1)
        try:
            deadline = time.time() + 3.0
            while time.time() < deadline and len(decoded) < 1:
                time.sleep(0.02)
        finally:
            dm1_send.stop_send(cb)

        bus.deliver()

        assert len(decoded) >= 1, "no FD-DM1 surfaced on receiver within 3 s"
        sa, lamp_status, dtc_dic_list = decoded[0]
        assert sa == bus.sa_a, "decoded sa=0x%02X expected 0x%02X" % (sa, bus.sa_a)
        assert lamp_status == {
            'pl':  j1939.DtcLamp.OFF,
            'awl': j1939.DtcLamp.OFF,
            'rsl': j1939.DtcLamp.OFF,
            'mil': j1939.DtcLamp.ON,
        }
        assert dtc_dic_list == sent_dtcs, (
            "decoded DTCs %r != sent %r" % (dtc_dic_list, sent_dtcs)
        )
    finally:
        bus.stop()


def test_fd_dm1_large_16_dtcs_via_fd_transport_roundtrip():
    """DM1 with sixteen DTCs (2 + 16*4 = 66-byte payload) exceeds the
    60-byte multi-PG capacity (§3.3) and therefore engages the FD
    transport protocol -- specifically the FD BAM flow (DM1 is broadcast),
    which uses 60-byte TP.DT segments (§3 line 447) and an explicit
    EOM_STATUS to trigger delivery (§3.4).

    66 bytes splits as 60 + 6, so the receiver reassembles two TP.DT
    segments before the originator's EOM_STATUS hands the buffer to the
    Dm1 parser.  All sixteen DTCs must decode in the order sent."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=20)
    try:
        dm1_send = j1939.Dm1(bus.ca_a)
        dm1_recv = j1939.Dm1(bus.ca_b)

        decoded = []
        dm1_recv.subscribe(
            lambda sa, lamp_status, dtc_dic_list, timestamp:
                decoded.append((sa, lamp_status, dtc_dic_list))
        )

        # 16 distinct DTCs with varied spn/fmi/oc so any reordering or
        # off-by-one in the TP-reassembly is caught at decode.
        sent_dtcs = [
            {'spn': 100 + i * 37, 'fmi': (i * 3) & 0x1F, 'oc': (i + 1) & 0x7F}
            for i in range(16)
        ]
        sent_lamp = {
            'mil': j1939.DtcLamp.ON,
            'awl': j1939.DtcLamp.ON_SLOW_FLASH,
        }

        def cb():
            return (sent_lamp, sent_dtcs)

        dm1_send.start_send(cb, cycletime=1)
        try:
            # Allow up to 5 s for the first DM1 to surface: the FD BAM
            # transport adds segment pacing on top of the 1 s cycletime.
            deadline = time.time() + 5.0
            while time.time() < deadline and len(decoded) < 1:
                time.sleep(0.02)
        finally:
            dm1_send.stop_send(cb)

        bus.deliver(timeout=10.0)

        assert len(decoded) >= 1, "no FD-DM1 surfaced on receiver within 5 s"
        sa, lamp_status, dtc_dic_list = decoded[0]
        assert sa == bus.sa_a, "decoded sa=0x%02X expected 0x%02X" % (sa, bus.sa_a)
        assert lamp_status['mil'] == j1939.DtcLamp.ON
        assert lamp_status['awl'] == j1939.DtcLamp.ON_SLOW_FLASH
        assert dtc_dic_list == sent_dtcs, (
            "decoded DTCs %r != sent %r" % (dtc_dic_list, sent_dtcs)
        )
    finally:
        bus.stop()


def test_fd_dm22_request_clear_act_dtc_roundtrip():
    """``Dm22.request_clear_act_dtc`` emits a single 8-byte DM22 payload
    (§2.6 wire format) over the j1939-22 bus.  8 bytes is well under §3.3's
    60-byte multi-PG capacity, so the bus carries it as a multi-PG carrier
    whose c-pg payload is the documented DM22 layout.  The receiver's raw
    subscriber sees the unwrapped DM22 PDU at PGN 0xC300 with the
    documented byte layout."""
    bus = TwoNodeBus(data_link_layer="j1939-22")
    try:
        dm22 = j1939.Dm22(bus.ca_a)
        spn, fmi = 4567, 12
        # §2.6 DM22 wire format (8 bytes, priority 6):
        #   byte 0 = control byte (17 = ACT_REQ)
        #   bytes 1..4 = 0xFF (reserved)
        #   byte 5 = spn & 0xFF
        #   byte 6 = (spn >> 8) & 0xFF
        #   byte 7 = ((spn >> 22) & 0xE0) | (fmi & 0x1F)
        expected_payload = [
            17, 0xFF, 0xFF, 0xFF, 0xFF,
            spn & 0xFF,
            (spn >> 8) & 0xFF,
            ((spn >> 22) & 0xE0) | (fmi & 0x1F),
        ]

        dm22.request_clear_act_dtc(bus.sa_b, spn, fmi)
        bus.deliver()

        # PDU1 -> the receiver sees PGN with PS cleared (the multi-PG
        # c-pg cpgn for PDU1 is pgn.value & 0xFFF00 per §3.3).
        assert (0xC300, expected_payload) in bus.received_b, bus.received_b
    finally:
        bus.stop()


