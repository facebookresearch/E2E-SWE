"""End-to-end transport-protocol round trips.

Two ECUs are wired together (:class:`TwoNodeBus`); an application PDU sent on
one node must surface, fully reassembled, on the other.  This exercises both
the originator and responder halves of the J1939-21 and J1939-22 (CAN-FD)
transport protocols, including RTS/CTS flow control and BAM broadcast.
"""

from feeder import TwoNodeBus


def _payload(n):
    return [(i * 7 + 1) & 0xFF for i in range(n)]


# --------------------------------------------------------------------------- #
# J1939-21 (classical CAN) round trips
# --------------------------------------------------------------------------- #
def test_j1939_21_p2p_long_roundtrip():
    """A 20-byte peer-to-peer PDU is delivered via the RTS/CTS connection
    protocol from one node to the other."""
    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=1)
    try:
        data = _payload(20)
        bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=data)
        bus.deliver()
        assert bus.received_b == [(0xDF00, data)], bus.received_b
    finally:
        bus.stop()


def test_j1939_21_broadcast_long_roundtrip():
    """A 20-byte broadcast PDU is delivered via BAM."""
    bus = TwoNodeBus(data_link_layer="j1939-21")
    try:
        data = _payload(20)
        bus.a_send(pdu_format=0xFE, pdu_specific=0xB0, data=data)
        bus.deliver()
        assert bus.received_b == [(0xFEB0, data)], bus.received_b
    finally:
        bus.stop()


def test_j1939_21_p2p_multi_cts_roundtrip():
    """A larger peer-to-peer PDU spanning several CTS windows is delivered
    intact when the receiver grants multiple segments per CTS."""
    bus = TwoNodeBus(data_link_layer="j1939-21", max_cmdt_packets=3)
    try:
        data = _payload(50)  # 8 packets of 7 bytes
        bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=data)
        bus.deliver()
        assert bus.received_b == [(0xDF00, data)], bus.received_b
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# J1939-22 (CAN-FD) round trips
# --------------------------------------------------------------------------- #
def test_fd_multipg_short_roundtrip():
    """A short (<=60 byte) broadcast PDU is carried in a single CAN-FD
    multi-PG frame and delivered intact."""
    bus = TwoNodeBus(data_link_layer="j1939-22")
    try:
        data = _payload(8)
        bus.a_send(pdu_format=0xFE, pdu_specific=0xB0, data=data)
        bus.deliver()
        assert bus.received_b == [(0xFEB0, data)], bus.received_b
    finally:
        bus.stop()


def test_fd_p2p_long_roundtrip():
    """A 100-byte peer-to-peer PDU is segmented over the CAN-FD transport
    protocol (RTS/CTS, 60-byte segments) and reassembled on the far node."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=1)
    try:
        data = _payload(100)
        bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=data)
        bus.deliver()
        assert bus.received_b == [(0xDF00, data)], bus.received_b
    finally:
        bus.stop()


# The FD-BAM broadcast round trip lives in test_j1939_fd_hard.py
# (test_fd_bam_large_4_segment_roundtrip, a 4-segment broadcast) — a single
# representative >3-segment case covers this path, and the byte-exact FD-BAM
# wire format is pinned by test_fd_bam_receive_single/two_segments.
