"""Harder DM14 / DM15 / DM16 memory-access scenarios.

These complement the four core DM14 handshake tests in ``test_j1939_core.py``
(read/write x with/without seed-key) by covering the ``Dm14Query`` *parameter
surface* documented in instruction.md §2.7 (``object_count``,
``object_byte_size``, ``signed``, ``return_raw_bytes``), the *registered
seed-key algorithm* contract, and the *cross-data-link-layer* contract that
``Dm14Query`` works unchanged on the j1939-22 (CAN-FD) ECU described in §3.

Every scripted frame is derived directly from the J1939-73 reference
implementation in ``can-j1939``:

  * Initial host DM14 carries the access-level marker ``0x0007`` in bytes 6-7
    (little-endian ``0x07 0x00``).
  * On a "proceed unauthenticated" DM15 (``seed == 0xFFFF`` and
    ``length == object_count``) the host either collects DM16 (read) or emits
    DM16 (write).
  * The final DM14 has command ``OPERATION_COMPLETED`` (nibble 4) and bytes
    6-7 set to ``0xFFFF``.

CAN-ID layout for the j1939-21 scripted scenarios (cf. §1.1):

  * Host source address used throughout: ``0xF9``; responder: ``0xD4``.
  * DM14 (PGN 0xD900, PDU1) host->responder:    ``can_id = 0x18D9D4F9``
  * DM15 (PGN 0xD800, PDU1) responder->host:    ``can_id = 0x1CD8F9D4``
  * DM16 (PGN 0xD700, PDU1) either direction:   ``can_id = 0x18D7D4F9``
    (TX from host) or ``0x1CD7F9D4`` (RX from responder)
"""

import j1939
from feeder import Feeder, TwoNodeBus


def _key_from_seed(seed):
    # Trivially-invertible algorithm; same as in test_j1939_core.py.
    return seed ^ 0xFFFF


# --------------------------------------------------------------------------- #
# Helper: run one full DM14 read or write scenario against a fresh ECU.
#
# Each sub-scenario in the bundled decode-options test below uses its own
# Feeder so the upstream ``Dm14Query`` subscription state can't leak between
# back-to-back operations.  This mirrors the per-test fixture lifecycle used
# elsewhere in the suite.
# --------------------------------------------------------------------------- #
def _run_read(can_messages, *read_args, **read_kwargs):
    feeder = Feeder()
    try:
        feeder.can_messages = list(can_messages)
        feeder.pdus_from_messages()
        ca = feeder.accept_all_messages(
            device_address_preferred=0xF9, bypass_address_claim=True
        )
        dm14 = j1939.Dm14Query(ca)
        dm14.set_seed_key_algorithm(_key_from_seed)
        feeder.subscribe()
        result = dm14.read(*read_args, **read_kwargs)
        feeder.drive()
        return result
    finally:
        feeder.stop()


def _run_write(can_messages, *write_args, **write_kwargs):
    feeder = Feeder()
    try:
        feeder.can_messages = list(can_messages)
        feeder.pdus_from_messages()
        ca = feeder.accept_all_messages(
            device_address_preferred=0xF9, bypass_address_claim=True
        )
        dm14 = j1939.Dm14Query(ca)
        dm14.set_seed_key_algorithm(_key_from_seed)
        feeder.subscribe()
        dm14.write(*write_args, **write_kwargs)
        feeder.drive()
    finally:
        feeder.stop()


# --------------------------------------------------------------------------- #
# 1. Decode-option bundle: signed / unsigned / word32 / raw / multi-value.
# --------------------------------------------------------------------------- #
def test_dm14_decode_options_bundle():
    """``Dm14Query.read`` and ``Dm14Query.write`` honour the §2.7 decode and
    encode contract across the practically relevant parameter combinations.
    Bundled here because every sub-scenario exercises the same DM14/DM15/DM16
    handshake (already byte-validated in ``test_j1939_core.py``) with only the
    decode/encode options varying:

      (A) ``object_byte_size=2, signed=True`` decodes ``0xFE 0xFF`` LE as
          ``-2`` (two's complement).
      (B) ``object_byte_size=2`` (``signed`` defaulting to False) decodes the
          same ``0xFE 0xFF`` LE bytes as ``0xFFFE`` (= 65534) -- pins the
          unsigned-vs-signed boundary against (A).
      (C) ``object_byte_size=4`` decodes ``0xEF 0xBE 0xAD 0xDE`` LE as
          ``0xDEADBEEF``.
      (D) ``return_raw_bytes=True`` bypasses decoding and returns the raw
          DM16 payload bytes verbatim.
      (E) WRITE with multiple values + ``object_byte_size=2``: each value is
          serialised little-endian into the DM16 frame; the byte_count prefix
          is the total payload length (4 here, well within the <=7 single-
          frame branch).  Byte-exactness is enforced by the scripted CANTX.

    All five sub-scenarios use the no-seed-key (proceed-unauthenticated)
    handshake so the test focuses purely on the parameter surface.
    """

    # ---- (A) signed obs=2, value 0xFFFE -> -2 -------------------------------
    # direct=2, READ -> DM14 byte 1 = (2<<4)|(1<<1)|1 = 0x23.
    # address 0xABCD1234 LE -> 0x34 0x12 0xCD 0xAB.
    # Final OPERATION_COMPLETED DM14 byte 1 = (2<<4)|(4<<1)|1 = 0x29.
    scenario_a = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x23, 0x34, 0x12, 0xCD, 0xAB, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD7F9D4,
         [0x02, 0xFE, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x29, 0x34, 0x12, 0xCD, 0xAB, 0xFF, 0xFF], 0.0),
    ]
    assert _run_read(
        scenario_a, 0xD4, 2, 0xABCD1234, 1,
        object_byte_size=2, signed=True,
    ) == [-2]

    # ---- (B) unsigned obs=2, same bytes -> 0xFFFE = 65534 -------------------
    # direct=0 -> DM14 byte 1 = (0<<4)|(1<<1)|1 = 0x03; final 0x09.
    # Different address (0x00000001) keeps the scripted frames distinct from
    # scenario (A) at a glance.
    scenario_b = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x03, 0x01, 0x00, 0x00, 0x00, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD7F9D4,
         [0x02, 0xFE, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x09, 0x01, 0x00, 0x00, 0x00, 0xFF, 0xFF], 0.0),
    ]
    assert _run_read(
        scenario_b, 0xD4, 0, 0x00000001, 1, object_byte_size=2,
    ) == [0xFFFE]

    # ---- (C) 32-bit word read: 0xDEADBEEF -----------------------------------
    # direct=6, READ -> DM14 byte 1 = (6<<4)|(1<<1)|1 = 0x63; final 0x69.
    # address 0x10203040 LE -> 0x40 0x30 0x20 0x10.
    scenario_c = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x63, 0x40, 0x30, 0x20, 0x10, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        # DM16: byte_count=4, payload 0xDEADBEEF LE.
        (Feeder.MsgType.CANRX, 0x1CD7F9D4,
         [0x04, 0xEF, 0xBE, 0xAD, 0xDE, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x69, 0x40, 0x30, 0x20, 0x10, 0xFF, 0xFF], 0.0),
    ]
    assert _run_read(
        scenario_c, 0xD4, 6, 0x10203040, 1, object_byte_size=4,
    ) == [0xDEADBEEF]

    # ---- (D) return_raw_bytes=True ------------------------------------------
    # direct=3, READ; ``object_count=4, object_byte_size=1``; the host returns
    # the verbatim 4-byte payload (no little-endian decoding).
    # DM14 byte 1 = (3<<4)|(1<<1)|1 = 0x33; final 0x39.
    scenario_d = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x04, 0x33, 0x00, 0x10, 0xFE, 0xCA, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x04, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD7F9D4,
         [0x04, 0xDE, 0xAD, 0xBE, 0xEF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x39, 0x00, 0x10, 0xFE, 0xCA, 0xFF, 0xFF], 0.0),
    ]
    # Accept any byte-sequence type (bytes / bytearray / list[int]); §2.7
    # constrains the value, not the container type.
    raw_result = _run_read(
        scenario_d, 0xD4, 3, 0xCAFE1000, 4, return_raw_bytes=True,
    )
    assert list(raw_result) == [0xDE, 0xAD, 0xBE, 0xEF], raw_result

    # ---- (E) WRITE multi-value, obs=2 ---------------------------------------
    # ``write([0x1234, 0xABCD], object_byte_size=2)`` serialises each value
    # little-endian and packs both into one DM16 frame (4-byte payload, well
    # under the 7-byte single-frame boundary).
    # direct=5, WRITE -> DM14 byte 1 = (5<<4)|(2<<1)|1 = 0x55; final 0x59.
    scenario_e = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x02, 0x55, 0x00, 0x00, 0xAD, 0xDE, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x02, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        # DM16 from host: byte_count=4, then 0x1234 LE (0x34 0x12) then
        # 0xABCD LE (0xCD 0xAB).
        (Feeder.MsgType.CANTX, 0x18D7D4F9,
         [0x04, 0x34, 0x12, 0xCD, 0xAB], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x59, 0x00, 0x00, 0xAD, 0xDE, 0xFF, 0xFF], 0.0),
    ]
    # Byte-exactness on the host's emitted DM16 is enforced by the scripted
    # CANTX entry above: feeder.drive() raises if any byte differs.
    _run_write(
        scenario_e, 0xD4, 5, 0xDEAD0000, [0x1234, 0xABCD], object_byte_size=2,
    )


# --------------------------------------------------------------------------- #
# 2. Custom seed-key algorithm: host must use the *registered* function.
# --------------------------------------------------------------------------- #
def test_dm14_read_uses_registered_seed_key_algorithm(feeder):
    """A read whose DM15 carries a non-``0xFFFF`` seed must be answered by
    re-emitting the same DM14 with bytes 6-7 set to the value returned by the
    *registered* seed-key algorithm -- not the trivial ``seed ^ 0xFFFF`` used
    by ``test_j1939_core.py::test_dm14_read_with_seed_key``.

    The algorithm registered here is ``key = (seed + 0x1234) & 0xFFFF`` and
    the responder issues seed ``0xBEEF``, so the host must send key ``0xD123``
    little-endian (``0x23 0xD1``) in the re-sent DM14.

    Frame derivation:
      * direct=4, READ; DM14 byte 1 = ``(4<<4)|(1<<1)|1`` = ``0x43``.
      * address 0xFEEDFACE LE -> ``0xCE 0xFA 0xED 0xFE``.
      * Seed DM15: length=1, status PROCEED (byte 1 = ``0x11``,
        ``(0x11>>1)&7 == 0``), bytes 6-7 = seed LE = ``0xEF 0xBE``.
      * Host re-sends DM14 with bytes 6-7 = key LE = ``0x23 0xD1``.
      * Proceed DM15 (length=1, seed=0xFFFF) lets the host collect DM16
        carrying a 1-byte payload ``0x42``.
      * Operation-complete DM15 and a final ``OPERATION_COMPLETED`` DM14
        (byte 1 = ``(4<<4)|(4<<1)|1`` = ``0x49``).
    """

    def _alt_key_from_seed(seed):
        return (seed + 0x1234) & 0xFFFF

    feeder.can_messages = [
        # Initial DM14 READ, access-level marker 0x0007.
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x43, 0xCE, 0xFA, 0xED, 0xFE, 0x07, 0x00], 0.0),
        # DM15 issues seed 0xBEEF.
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xEF, 0xBE], 0.0),
        # Host re-sends DM14 with key = (0xBEEF + 0x1234) & 0xFFFF = 0xD123.
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x43, 0xCE, 0xFA, 0xED, 0xFE, 0x23, 0xD1], 0.0),
        # Proceed DM15.
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        # DM16 carries the 1-byte payload 0x42.
        (Feeder.MsgType.CANRX, 0x1CD7F9D4,
         [0x01, 0x42, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        # Operation-complete DM15.
        (Feeder.MsgType.CANRX, 0x1CD8F9D4,
         [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        # Final OPERATION_COMPLETED DM14 echo.
        (Feeder.MsgType.CANTX, 0x18D9D4F9,
         [0x01, 0x49, 0xCE, 0xFA, 0xED, 0xFE, 0xFF, 0xFF], 0.0),
    ]
    feeder.pdus_from_messages()
    ca = feeder.accept_all_messages(
        device_address_preferred=0xF9, bypass_address_claim=True
    )
    dm14 = j1939.Dm14Query(ca)
    dm14.set_seed_key_algorithm(_alt_key_from_seed)
    feeder.subscribe()
    result = dm14.read(0xD4, 4, 0xFEEDFACE, 1)
    feeder.drive()
    assert result == [0x42], result


# --------------------------------------------------------------------------- #
# 3. DM14 carried over the J1939-22 (CAN-FD) data-link layer.
# --------------------------------------------------------------------------- #
def test_dm14_read_over_fd_no_seed_key():
    """``Dm14Query.read`` runs end-to-end over a CAN-FD (j1939-22) data-link
    layer.  Cross-subsystem coverage: the same DM14 handshake that
    ``test_j1939_core.py`` byte-validates on j1939-21 must keep working when
    the underlying ECU uses the FD multi-PG carrier described in §3.

    Uses ``TwoNodeBus(j1939-22)``: node A hosts the ``Dm14Query`` against the
    AcceptAllCA at ``bus.sa_a``; node B is a responder implemented as a
    subscriber on ``ecu_b`` that emits DM15 / DM16 / DM15 via
    ``ecu_b.send_pgn``.  Asserting on the *application-level* outcome (the
    decoded value returned by ``read()``) keeps the test independent of the
    FD frame-byte layout that §3 leaves to the implementer.

    The responder distinguishes the host's initial DM14 (command READ=1) from
    the final OPERATION_COMPLETED DM14 (command nibble 4) using the §1.5
    encoding ``(data[1] >> 1) & 7``.  Only the initial DM14 gets a reply.
    """
    bus = TwoNodeBus(data_link_layer="j1939-22")
    try:
        DM14_PGN = 0xD900
        DM15_PF  = 0xD8
        DM16_PF  = 0xD7
        CMD_OPERATION_COMPLETED = 4

        def b_responder(priority, pgn, sa, timestamp, data):
            if pgn != DM14_PGN or sa != bus.sa_a:
                return
            data = list(data)
            if ((data[1] >> 1) & 7) == CMD_OPERATION_COMPLETED:
                return   # final ack from host; no further reply needed
            object_count = data[0]
            # DM15 PROCEED: length echoes object_count, status PROCEED
            # (byte 1 = 0x11 -> nibble 0), seed bytes 6-7 = 0xFFFF.
            bus.ecu_b.send_pgn(
                0, DM15_PF, bus.sa_a, 6, bus.sa_b,
                [object_count, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF],
            )
            # DM16: byte_count=1, payload 0x5A.
            bus.ecu_b.send_pgn(
                0, DM16_PF, bus.sa_a, 6, bus.sa_b,
                [0x01, 0x5A, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF],
            )
            # Operation-complete DM15: byte 1 = 0x19 -> nibble 4
            # (OPERATION_COMPLETED).
            bus.ecu_b.send_pgn(
                0, DM15_PF, bus.sa_a, 6, bus.sa_b,
                [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF],
            )
        bus.ecu_b.subscribe(b_responder)

        dm14 = j1939.Dm14Query(bus.ca_a)
        result = dm14.read(bus.sa_b, 1, 0x12345678, 1)
        bus.deliver(timeout=5.0)
        assert result == [0x5A], result
    finally:
        bus.stop()
