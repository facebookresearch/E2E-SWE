"""J1939-22 (CAN-FD) transport tests.

Three families of tests live here, complementing the FD round-trips already
covered by :mod:`test_j1939_roundtrip`:

* Exact-byte multi-PG SEND scenarios driven by the scripted ``feeder_fd``
  fixture.  These pin the c-pg header layout (tos/tf/cpgn/length), the
  FEFF_MULTI_PG can-id, and the FD DLC padding rule (three zero pad bytes,
  then 0xAA fill up to the next valid FD length).
* Exact-byte RECEIVE scenarios for the FD TP.CM / TP.DT wire format (BAM and
  RTS/CTS), which assert the destination-side CTS / EOM-ACK frames are byte
  identical to the spec encoding and that the reassembled application PDU
  surfaces with the expected bytes.
* A few additional TwoNodeBus round trips that explore corners not covered
  upstream (multi-segment CTS windows on FD, PDU1 carried by multi-PG).
"""

from feeder import Feeder, FEFF, TwoNodeBus


# --------------------------------------------------------------------------- #
# Constants from j1939_22.py (kept local so the tests document the contract).
# --------------------------------------------------------------------------- #
FEFF_MULTI_PG_PGN = 0x2500   # ParameterGroupNumber.PGN.FEFF_MULTI_PG (9472)
FD_TP_CM_PGN      = 0x4D00   # ParameterGroupNumber.PGN.FD_TP_CM    (19712)
FD_TP_DT_PGN      = 0x4E00   # ParameterGroupNumber.PGN.FD_TP_DT    (19968)
GLOBAL_ADDR       = 0xFF

TP_CTL_RTS        = 0
TP_CTL_CTS        = 1
TP_CTL_EOM_STATUS = 2
TP_CTL_EOM_ACK    = 3
TP_CTL_BAM        = 4
TP_CTL_ABORT      = 15


def _payload(n):
    """Same deterministic payload generator used by the round-trip tests."""
    return [(i * 7 + 1) & 0xFF for i in range(n)]


# ``_LUT_FD_DLC`` from j1939_22.py: index = current frame length in bytes,
# value = next valid CAN-FD frame size to pad up to.
_LUT_FD_DLC = (
    list(range(9))                     # 0..8 -> identity
    + [12] * 4                         # 9..12  -> 12
    + [16] * 4                         # 13..16 -> 16
    + [20] * 4                         # 17..20 -> 20
    + [24] * 4                         # 21..24 -> 24
    + [32] * 8                         # 25..32 -> 32
    + [48] * 16                        # 33..48 -> 48
    + [64] * 16                        # 49..64 -> 64
)


def _fd_pad(data):
    """Pad a multi-PG-style frame to the next valid CAN-FD length.

    Mirrors ``J1939_22.__send_multi_pg``: first up to three pad bytes are
    written as the multi-PG service header value ``0x00`` (which the receiver
    treats as the "padding" tos and stops parsing), then the remainder is
    filled with ``0xAA``.
    """
    target = _LUT_FD_DLC[len(data)]
    out = list(data)
    pad_cnt = 0
    while len(out) < target:
        if pad_cnt < 3:
            out.append(0x00)
            pad_cnt += 1
        else:
            out.append(0xAA)
    return out


def _can_id(priority, pgn, source_address):
    """29-bit CAN-Id assembly (MessageId.can_id) -- priority<<26 | pgn<<8 | sa."""
    return ((priority & 0x7) << 26) | ((pgn & 0x3FFFF) << 8) | (source_address & 0xFF)


def _multi_pg_can_id(priority, dst_address, source_address):
    """can-id of an FEFF multi-PG carrier frame: PGN is FEFF_MULTI_PG | dst."""
    pgn = FEFF_MULTI_PG_PGN | (dst_address & 0xFF)
    return _can_id(priority, pgn, source_address)


def _fd_tp_cm_can_id(priority, dst_address, source_address):
    """can-id of an FD TP.CM frame: PGN = (FD_TP_CM>>8 == 0x4D) << 8 | dst."""
    pf = (FD_TP_CM_PGN >> 8) & 0xFF       # 0x4D
    pgn = (pf << 8) | (dst_address & 0xFF)
    return _can_id(priority, pgn, source_address)


def _fd_tp_dt_can_id(priority, dst_address, source_address):
    """can-id of an FD TP.DT frame: PGN = (FD_TP_DT>>8 == 0x4E) << 8 | dst."""
    pf = (FD_TP_DT_PGN >> 8) & 0xFF       # 0x4E
    pgn = (pf << 8) | (dst_address & 0xFF)
    return _can_id(priority, pgn, source_address)


def _cpg_bytes(priority, tos, tf, cpgn, payload):
    """The 4-byte c-pg header + payload, exactly as ``__send_multi_pg`` packs it.

    Header bytes are::

        b0 = (tos<<5) | (tf<<2) | ((cpgn>>16) & 0x3)
        b1 = (cpgn >> 8) & 0xFF
        b2 =  cpgn       & 0xFF
        b3 =  len(payload)
    """
    return [
        ((tos & 0x7) << 5) | ((tf & 0x7) << 2) | ((cpgn >> 16) & 0x3),
        (cpgn >> 8) & 0xFF,
        cpgn & 0xFF,
        len(payload) & 0xFF,
    ] + list(payload)


def _tp_cm_bytes(control, session, message_size, num_segments,
                 byte7, byte8, pgn):
    """The 12 bytes of any FD TP.CM frame, as packed by ``__send_tp_cm``.

    Layout::

        data[0]  = (control & 0xF) | ((session & 0xF) << 4)
        data[1..3] = message_size little-endian (24-bit)
        data[4..6] = num_segments  little-endian (24-bit)
        data[7]    = byte7
        data[8]    = byte8
        data[9..11]= pgn little-endian (24-bit)
    """
    return [
        (control & 0xF) | ((session & 0xF) << 4),
        message_size & 0xFF,
        (message_size >> 8) & 0xFF,
        (message_size >> 16) & 0xFF,
        num_segments & 0xFF,
        (num_segments >> 8) & 0xFF,
        (num_segments >> 16) & 0xFF,
        byte7 & 0xFF,
        byte8 & 0xFF,
        pgn & 0xFF,
        (pgn >> 8) & 0xFF,
        (pgn >> 16) & 0xFF,
    ]


def _tp_dt_bytes(session, segment_num, payload, dtfi=0):
    """The variable-length FD TP.DT frame as packed by ``__send_tp_dt``.

    Layout::

        data[0]  = (dtfi & 0xF) | ((session & 0xF) << 4)
        data[1..3] = segment_num little-endian (24-bit)
        data[4..]  = payload (<=60 bytes)
    """
    return [
        (dtfi & 0xF) | ((session & 0xF) << 4),
        segment_num & 0xFF,
        (segment_num >> 8) & 0xFF,
        (segment_num >> 16) & 0xFF,
    ] + list(payload)


# --------------------------------------------------------------------------- #
# 1. Exact-byte multi-PG SEND frames
# --------------------------------------------------------------------------- #
def test_fd_multipg_send_pdu2_padding_sweep(feeder_fd):
    """Send three PDU2 PDUs (PGN 0xFEB0) through the multi-PG path with
    payload lengths that exercise each of the §3.3 padding regimes:

    * 8-byte payload  -> 12-byte frame, already a valid CAN-FD length,
                         no padding at all.
    * 10-byte payload -> 14 cpg bytes padded to 16: two trailing 0x00
                         pad bytes (within the first-three-bytes 0x00
                         "padding service header" budget).
    * 21-byte payload -> 25 cpg bytes padded to 32: three 0x00 pad
                         bytes (the budget) followed by four 0xAA fill
                         bytes.

    Each iteration runs an independent feeder transaction so the three
    expected frames don't interleave on the shared feeder script.
    """
    src = 0x80
    cases = [
        # (payload_length, expected_frame_length, expected_trailing_pad)
        (8,  12, []),
        (10, 16, [0x00, 0x00]),
        (21, 32, [0x00, 0x00, 0x00, 0xAA, 0xAA, 0xAA, 0xAA]),
    ]
    expected_can_id = _multi_pg_can_id(
        priority=6, dst_address=GLOBAL_ADDR, source_address=src
    )

    for payload_len, frame_len, trailing_pad in cases:
        # Re-derive every byte from the (tos=2, tf=0, cpgn=0xFEB0, payload)
        # contract in §3.3 plus the FD-DLC padding rule.
        payload = _payload(payload_len)
        cpg = _cpg_bytes(priority=6, tos=2, tf=0, cpgn=0xFEB0, payload=payload)
        expected = _fd_pad(cpg)
        assert len(expected) == frame_len, (
            "payload %d -> expected frame %d, got %d"
            % (payload_len, frame_len, len(expected))
        )
        if trailing_pad:
            assert expected[-len(trailing_pad):] == trailing_pad

        feeder_fd.can_messages = [
            (Feeder.MsgType.CANTX, expected_can_id, expected, 0.0),
        ]
        feeder_fd.ecu.send_pgn(0, 0xFE, 0xB0, 6, src, list(payload), 0, FEFF)
        feeder_fd._wait(2.0)
        feeder_fd.check()


def test_fd_multipg_send_pdu1_short(feeder_fd):
    """A 4-byte PDU1 (peer-to-peer) PDU is also carried as a multi-PG c-pg.

    For PDU1 the cpgn in the c-pg header is ``pgn.value & 0xFFF00`` (the
    destination is stripped because it travels in the carrier frame's can-id
    instead).  cpgn for PF=0xDF / PS=0x9B is therefore 0x0DF00.

    The carrier frame's destination is the original ``pdu_specific`` byte, so
    the can-id PGN is ``FEFF_MULTI_PG | 0x9B = 0x259B``.
    """
    src = 0x80
    dst = 0x9B
    data = _payload(4)
    # cpgn computation, byte-for-byte: 0x0DF00.
    expected_cpg = _cpg_bytes(priority=6, tos=2, tf=0, cpgn=0x0DF00, payload=data)
    assert expected_cpg[:4] == [0x40, 0xDF, 0x00, 0x04]
    expected = _fd_pad(expected_cpg)  # 8 bytes already valid -> no padding
    assert len(expected) == 8

    feeder_fd.can_messages = [
        (Feeder.MsgType.CANTX,
         _multi_pg_can_id(priority=6, dst_address=dst, source_address=src),
         expected, 0.0),
    ]
    feeder_fd.ecu.send_pgn(0, 0xDF, dst, 6, src, list(data))
    feeder_fd._wait(2.0)
    feeder_fd.check()


# --------------------------------------------------------------------------- #
# 2. Exact-byte FD BAM RECEIVE
# --------------------------------------------------------------------------- #
def test_fd_bam_receive_single_segment(feeder_fd):
    """Inject an FD BAM TP.CM for a 50-byte PDU, one TP.DT segment carrying
    the whole payload, then the originator's EOM_STATUS.  Only on the
    EOM_STATUS does the FD receiver actually notify subscribers (this differs
    from J1939-21 BAM, which notifies once all DTs have been received -- the
    FD originator sends an explicit EOM_STATUS after the last DT, so the
    receiver waits for it before delivering the reassembled PDU)."""
    src = 0x42                          # remote sender's source address
    session = 3
    pgn = 0xFEB0                        # broadcast PDU2 PGN
    payload = _payload(50)

    bam_cm = _tp_cm_bytes(
        control=TP_CTL_BAM, session=session,
        message_size=50, num_segments=1,
        byte7=0xFF, byte8=0, pgn=pgn,
    )
    assert bam_cm[0] == (TP_CTL_BAM | (session << 4))   # 0x34

    dt1 = _tp_dt_bytes(session=session, segment_num=1, payload=payload)
    assert dt1[0] == (session << 4)                     # 0x30 (dtfi=0)

    eom_status = _tp_cm_bytes(
        control=TP_CTL_EOM_STATUS, session=session,
        message_size=50, num_segments=1,
        byte7=0, byte8=0, pgn=pgn,
    )

    feeder_fd.subscribe()
    feeder_fd.can_messages = [
        (Feeder.MsgType.CANRX,
         _fd_tp_cm_can_id(priority=6, dst_address=GLOBAL_ADDR, source_address=src),
         bam_cm, 0.0),
        (Feeder.MsgType.CANRX,
         _fd_tp_dt_can_id(priority=7, dst_address=GLOBAL_ADDR, source_address=src),
         dt1, 0.0),
        (Feeder.MsgType.CANRX,
         _fd_tp_cm_can_id(priority=7, dst_address=GLOBAL_ADDR, source_address=src),
         eom_status, 0.0),
    ]
    feeder_fd.pdus = [(Feeder.MsgType.PDU, pgn, payload)]
    feeder_fd.drive()


def test_fd_bam_receive_two_segments(feeder_fd):
    """A 90-byte BAM payload spans two FD TP.DT segments (60 + 30).  The
    originator follows the last DT with an EOM_STATUS frame; only then does
    the FD receiver notify its subscribers with the reassembled payload."""
    src = 0x42
    session = 1
    pgn = 0xFEB0
    payload = _payload(90)

    bam_cm = _tp_cm_bytes(
        control=TP_CTL_BAM, session=session,
        message_size=90, num_segments=2,
        byte7=0xFF, byte8=0, pgn=pgn,
    )
    dt1 = _tp_dt_bytes(session=session, segment_num=1, payload=payload[:60])
    dt2 = _tp_dt_bytes(session=session, segment_num=2, payload=payload[60:])
    eom_status = _tp_cm_bytes(
        control=TP_CTL_EOM_STATUS, session=session,
        message_size=90, num_segments=2,
        byte7=0, byte8=0, pgn=pgn,
    )

    feeder_fd.subscribe()
    feeder_fd.can_messages = [
        (Feeder.MsgType.CANRX,
         _fd_tp_cm_can_id(priority=6, dst_address=GLOBAL_ADDR, source_address=src),
         bam_cm, 0.0),
        (Feeder.MsgType.CANRX,
         _fd_tp_dt_can_id(priority=7, dst_address=GLOBAL_ADDR, source_address=src),
         dt1, 0.0),
        (Feeder.MsgType.CANRX,
         _fd_tp_dt_can_id(priority=7, dst_address=GLOBAL_ADDR, source_address=src),
         dt2, 0.0),
        (Feeder.MsgType.CANRX,
         _fd_tp_cm_can_id(priority=7, dst_address=GLOBAL_ADDR, source_address=src),
         eom_status, 0.0),
    ]
    feeder_fd.pdus = [(Feeder.MsgType.PDU, pgn, payload)]
    feeder_fd.drive()


# --------------------------------------------------------------------------- #
# 3. Exact-byte FD RTS/CTS RECEIVE
# --------------------------------------------------------------------------- #
def test_fd_rts_cts_receive_exact_bytes(feeder_fd):
    """End-to-end FD RTS/CTS receive with byte-exact CTS / EOM-ACK responses.

    Scenario (responder = our stack, remote = ``0x42``):

      RX  RTS         (control 0, msg=80 bytes, 2 segments, max_cmdt=0xFF)
      TX  CTS  #1     (next_packet=1, granting 1 segment because
                       ``feeder_fd`` is created with the default
                       ``max_cmdt_packets=1``)
      RX  TP.DT seg 1 (60 bytes)
      TX  CTS  #2     (next_packet=2, granting 1 segment)
      RX  TP.DT seg 2 (20 bytes)
      RX  EOM_STATUS  (sender signals end of message)
      ->  PDU delivered to subscribers
      TX  EOM_ACK     (byte_7 = 0xFF, byte_8 = 0xFF per __send_tp_eom_ack)
    """
    our  = 0x80                          # responder (our CA)
    rem  = 0x42                          # remote originator
    session = 2
    pgn  = 0xDF00                        # PDU1 message PGN with ps cleared, as
                                         # the originator writes it on the wire
    payload = _payload(80)

    rts = _tp_cm_bytes(
        control=TP_CTL_RTS, session=session,
        message_size=80, num_segments=2,
        byte7=0xFF, byte8=0, pgn=pgn,
    )
    # CTS responses: __send_tp_cts -> message_size = 0xFFFFFF, num_segments
    # field carries ``next_packet``, byte_7 carries number of segments
    # granted, byte_8 is request_code (0).
    cts1 = _tp_cm_bytes(
        control=TP_CTL_CTS, session=session,
        message_size=0xFFFFFF, num_segments=1,   # next_packet = 1
        byte7=1, byte8=0, pgn=pgn,
    )
    cts2 = _tp_cm_bytes(
        control=TP_CTL_CTS, session=session,
        message_size=0xFFFFFF, num_segments=2,   # next_packet = 2
        byte7=1, byte8=0, pgn=pgn,
    )
    dt1 = _tp_dt_bytes(session=session, segment_num=1, payload=payload[:60])
    dt2 = _tp_dt_bytes(session=session, segment_num=2, payload=payload[60:])
    eom_status = _tp_cm_bytes(
        control=TP_CTL_EOM_STATUS, session=session,
        message_size=80, num_segments=2,
        byte7=0, byte8=0, pgn=pgn,
    )
    eom_ack = _tp_cm_bytes(
        control=TP_CTL_EOM_ACK, session=session,
        message_size=80, num_segments=2,
        byte7=0xFF, byte8=0xFF, pgn=pgn,
    )

    feeder_fd.accept_all_messages(device_address_preferred=our, bypass_address_claim=True)
    feeder_fd.subscribe()

    # IDs: TP.CM frames addressed *to* the recipient; TP.DT priority is 7.
    can_id_rx_cm  = _fd_tp_cm_can_id(priority=6, dst_address=our, source_address=rem)
    can_id_tx_cm  = _fd_tp_cm_can_id(priority=7, dst_address=rem, source_address=our)
    can_id_rx_dt  = _fd_tp_dt_can_id(priority=7, dst_address=our, source_address=rem)

    feeder_fd.can_messages = [
        (Feeder.MsgType.CANRX, can_id_rx_cm,  rts,        0.0),
        (Feeder.MsgType.CANTX, can_id_tx_cm,  cts1,       0.0),
        (Feeder.MsgType.CANRX, can_id_rx_dt,  dt1,        0.0),
        (Feeder.MsgType.CANTX, can_id_tx_cm,  cts2,       0.0),
        (Feeder.MsgType.CANRX, can_id_rx_dt,  dt2,        0.0),
        (Feeder.MsgType.CANRX, can_id_rx_cm,  eom_status, 0.0),
        (Feeder.MsgType.CANTX, can_id_tx_cm,  eom_ack,    0.0),
    ]
    feeder_fd.pdus = [(Feeder.MsgType.PDU, pgn, payload)]
    feeder_fd.drive(timeout=6.0)


# --------------------------------------------------------------------------- #
# 4. Extra round-trips not already covered by test_j1939_roundtrip.
# --------------------------------------------------------------------------- #
def test_fd_p2p_multi_cts_window_roundtrip():
    """A 200-byte peer-to-peer FD PDU is segmented into four 60-byte chunks
    (plus a 20-byte tail = four full + one short = 4 segments wait, 200/60 =
    4 rem 20 so 4 segments doesn't divide -- ceil(200/60) = 4 segments?  No,
    ceil(200/60) = 4 since 3*60=180<200<=4*60=240, so 4 segments).  With
    ``max_cmdt_packets=4`` the receiver grants the whole transfer in a single
    CTS window, exercising a code path the existing 100-byte round-trip
    (which fits in two segments) does not."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=4)
    try:
        data = _payload(200)
        bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=data)
        bus.deliver(timeout=10.0)
        assert bus.received_b == [(0xDF00, data)], bus.received_b
    finally:
        bus.stop()


def test_fd_pdu2_broadcast_via_multipg_roundtrip():
    """A short PDU2 *broadcast* (PF=0xFE) rides a single multi-PG c-pg without
    engaging the FD TP transport, and must still surface on the far node.

    This pins the receive-side multi-PG path for a *broadcast* PDU (GLOBAL
    delivery, cpgn = full pgn.value) -- distinct from the PDU1 60-byte case in
    ``test_fd_p2p_boundary_short_sweep`` (destination-gated, cpgn = pgn & 0xFFF00)
    and from ``test_fd_multipg_send_pdu2_padding_sweep`` (which validates only the
    SEND-side wire bytes, never reassembly + delivery at a subscriber). The
    48-byte length stays inside the single-c-pg regime (<= 60) yet differs from
    the sweep's 60/61 boundary."""
    bus = TwoNodeBus(data_link_layer="j1939-22")
    try:
        data = _payload(48)
        bus.a_send(pdu_format=0xFE, pdu_specific=0xB0, data=data)
        bus.deliver()
        assert bus.received_b == [(0xFEB0, data)], bus.received_b
    finally:
        bus.stop()


# --------------------------------------------------------------------------- #
# 5. Concurrent FD transports from one originator.
#
# Asserts only payload equality at the subscriber (``TwoNodeBus`` is
# byte-correct by construction).  Larger / single-direction concurrency
# round trips live in test_j1939_fd_hard.py to avoid duplication.
# --------------------------------------------------------------------------- #
def _payload_offset(n, offset):
    """Deterministic payload generator with a per-test salt so reassembly
    mistakes that splice bytes from one transfer into another are caught."""
    return [((i + offset) * 7 + 1) & 0xFF for i in range(n)]


def test_fd_concurrent_bam_plus_p2p_interleaved():
    """A BAM broadcast and an RTS/CTS p2p transfer overlap on the same FD
    bus from the same originator.

    The originator must therefore juggle a BAM session (keyed by
    (sa_a, GLOBAL)) and an RTS/CTS session (keyed by (sa_a, sa_b))
    simultaneously -- the §3 session caps (4 BAM + 8 RTS/CTS) allow this
    cleanly.  Both payloads must surface intact at B; the order they
    arrive in is implementation-defined, so we compare as a set."""
    bus = TwoNodeBus(data_link_layer="j1939-22", max_cmdt_packets=2)
    try:
        bam_data = _payload_offset(150, offset=0)      # 3 segments of 60+60+30
        p2p_data = _payload_offset(150, offset=200)    # distinct payload

        # Both started from ECU A, both larger than 60 bytes -> both engage
        # the FD transport protocol.  PDU2 (PF=0xFE) is BAM; PDU1 (PF=0xDF)
        # with a non-broadcast destination is RTS/CTS.
        bus.a_send(pdu_format=0xFE, pdu_specific=0xB0, data=bam_data)
        bus.a_send(pdu_format=0xDF, pdu_specific=bus.sa_b, data=p2p_data)
        bus.deliver(timeout=15.0)

        got = set((pgn, tuple(d)) for pgn, d in bus.received_b)
        want = {
            (0xFEB0, tuple(bam_data)),
            (0xDF00, tuple(p2p_data)),
        }
        assert got == want, bus.received_b
    finally:
        bus.stop()
