"""Deep encoding / framing / routing coverage for the J1939 stack.

These tests focus on byte-exact behaviour of the value objects (``Name``,
``MessageId``, ``ParameterGroupNumber``) and on the receive routing that
:class:`ElectronicControlUnit` performs *before* any controller-application is
involved: PDU2 (broadcast) frames are always delivered, PDU1 (peer-to-peer)
frames are delivered only when the destination address matches a registered
subscriber or controller application.

All scenarios are driven through the public API with the mock :class:`Feeder`;
no real CAN hardware is touched.
"""

import j1939
from feeder import Feeder


# --------------------------------------------------------------------------- #
# Name encoding -- depth / boundary values
# --------------------------------------------------------------------------- #
def test_name_encoding_depth():
    """The 64-bit NAME packing matches the SAE J1939-81 bit layout for every
    industry group and every field at its width boundary; both the
    ``value`` and ``bytes`` representations round-trip.

    Bundled checks (each line was computed from the documented bit layout):
      identity_number is bits  0..20  (21 bits)
      manufacturer_code         21..31 (11 bits)
      ecu_instance              32..34 ( 3 bits)
      function_instance         35..39 ( 5 bits)
      function                  40..47 ( 8 bits)
      reserved_bit              48     ( 1 bit, always 0)
      vehicle_system            49..55 ( 7 bits)
      vehicle_system_instance   56..59 ( 4 bits)
      industry_group            60..62 ( 3 bits)
      arbitrary_address_capable 63     ( 1 bit)
    """
    IG = j1939.Name.IndustryGroup

    # (kwargs, expected_value, expected_bytes_little_endian)
    cases = [
        # All zeros -> value 0, all-zero bytes.
        (dict(), 0, [0, 0, 0, 0, 0, 0, 0, 0]),
        # Only identity_number=1, Global industry group.
        (dict(industry_group=IG.Global, identity_number=1),
         1, [1, 0, 0, 0, 0, 0, 0, 0]),
        # OnHighway, mid-range values.
        (dict(arbitrary_address_capable=1, industry_group=IG.OnHighway,
              vehicle_system_instance=3, vehicle_system=50,
              function=128, function_instance=7, ecu_instance=1,
              manufacturer_code=300, identity_number=500000),
         10620754804177608992, [32, 161, 135, 37, 57, 128, 100, 147]),
        # Marine, every field at its maximum.
        (dict(arbitrary_address_capable=1, industry_group=IG.Marine,
              vehicle_system_instance=15, vehicle_system=127,
              function=255, function_instance=31, ecu_instance=7,
              manufacturer_code=2047, identity_number=(1 << 21) - 1),
         14987698084912300031, [255, 255, 255, 255, 255, 255, 254, 207]),
        # Industrial, function field at its max in isolation.
        (dict(industry_group=IG.Industrial, function=255),
         5764887898499317760, [0, 0, 0, 0, 0, 255, 0, 80]),
        # Global, manufacturer_code at its max in isolation.
        (dict(industry_group=IG.Global, manufacturer_code=2047),
         4292870144, [0, 0, 224, 255, 0, 0, 0, 0]),
    ]

    for kwargs, expected_value, expected_bytes in cases:
        name = j1939.Name(**kwargs)
        assert name.value == expected_value, (kwargs, name.value, expected_value)
        assert name.bytes == expected_bytes, (kwargs, name.bytes, expected_bytes)
        # ``bytes`` is exactly 8 little-endian bytes.
        assert len(name.bytes) == 8
        # value -> Name -> bytes round-trip
        rebuilt_v = j1939.Name(value=expected_value)
        assert rebuilt_v.bytes == expected_bytes
        # bytes -> Name -> value round-trip and per-field decomposition
        rebuilt_b = j1939.Name(bytes=expected_bytes)
        assert rebuilt_b.value == expected_value
        for field, expected in kwargs.items():
            assert getattr(rebuilt_b, field) == expected, (
                field, getattr(rebuilt_b, field), expected,
            )


def test_name_field_validation():
    """Every NAME field rejects out-of-range values with ``ValueError`` at the
    documented bit-width boundary; the largest in-range value is accepted."""

    # (kwarg, just-over-the-top value, just-at-the-top value)
    bad_good = [
        ("arbitrary_address_capable", 2, 1),
        ("industry_group", 8, 7),                # 3 bits
        ("vehicle_system_instance", 16, 15),     # 4 bits
        ("vehicle_system", 128, 127),            # 7 bits
        ("function", 256, 255),                  # 8 bits
        ("function_instance", 32, 31),           # 5 bits
        ("ecu_instance", 8, 7),                  # 3 bits
        ("manufacturer_code", 2048, 2047),       # 11 bits
        ("identity_number", (1 << 21), (1 << 21) - 1),  # 21 bits
    ]
    for field, bad, good in bad_good:
        # Out-of-range -> ValueError
        try:
            j1939.Name(**{field: bad})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for %s=%d" % (field, bad))
        # Negative -> ValueError
        try:
            j1939.Name(**{field: -1})
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError for %s=-1" % field)
        # Boundary value is accepted and round-trips
        n = j1939.Name(**{field: good})
        assert getattr(n, field) == good
        # And it survives a bytes round-trip.
        assert getattr(j1939.Name(bytes=n.bytes), field) == good


# --------------------------------------------------------------------------- #
# MessageId pack / unpack
# --------------------------------------------------------------------------- #
def test_message_id_pack_unpack():
    """:class:`MessageId` packs ``(priority, pgn, source_address)`` into the
    canonical 29-bit CAN identifier ``(priority<<26) | (pgn<<8) | sa`` and
    parses an arbitrary CAN-Id back into the same three fields.  Covers both
    PDU1 and PDU2 PF values."""

    # (priority, pgn, source_address, expected can_id)
    cases = [
        (6, 0xEEFF, 0x80, 0x18EEFF80),  # PDU1, address-claim, classic
        (6, 0xEF85, 0x22, 0x18EF8522),  # PDU1, peer-to-peer to 0x85
        (6, 0xFEB1, 0x21, 0x18FEB121),  # PDU2, broadcast (PF=0xFE)
        (3, 0xF004, 0x00, 0x0CF00400),  # PDU2, low priority
        (7, 0x00FF, 0xFF, 0x1C00FFFF),  # priority=7, all-ones source
        (0, 0x0000, 0x00, 0x00000000),  # canonical zero
    ]
    for priority, pgn, sa, expected in cases:
        # pack
        built = j1939.MessageId(
            priority=priority, parameter_group_number=pgn, source_address=sa
        )
        assert built.can_id == expected, (priority, pgn, sa, hex(built.can_id))
        # unpack
        parsed = j1939.MessageId(can_id=expected)
        assert parsed.priority == priority
        assert parsed.parameter_group_number == pgn
        assert parsed.source_address == sa
        # reconstruct
        assert (
            j1939.MessageId(
                priority=parsed.priority,
                parameter_group_number=parsed.parameter_group_number,
                source_address=parsed.source_address,
            ).can_id
            == expected
        )


# --------------------------------------------------------------------------- #
# ParameterGroupNumber: PDU1/PDU2 split, value, from_message_id, constants
# --------------------------------------------------------------------------- #
def test_pgn_format_value_and_constants():
    """``ParameterGroupNumber`` distinguishes PDU1 from PDU2 exactly at
    ``PF=239`` (peer-to-peer) vs ``PF=240`` (broadcast), computes ``value`` as
    ``(DP<<16) | (PF<<8) | PS``, and parses itself from a ``MessageId``."""

    # PDU1 / PDU2 boundary
    assert j1939.ParameterGroupNumber(0, 0, 0).is_pdu1_format
    assert not j1939.ParameterGroupNumber(0, 0, 0).is_pdu2_format
    assert j1939.ParameterGroupNumber(0, 239, 0).is_pdu1_format
    assert not j1939.ParameterGroupNumber(0, 239, 0).is_pdu2_format
    assert not j1939.ParameterGroupNumber(0, 240, 0).is_pdu1_format
    assert j1939.ParameterGroupNumber(0, 240, 0).is_pdu2_format
    assert not j1939.ParameterGroupNumber(0, 255, 0).is_pdu1_format
    assert j1939.ParameterGroupNumber(0, 255, 0).is_pdu2_format

    # value = DP<<16 | PF<<8 | PS
    assert j1939.ParameterGroupNumber(0, 0xEE, 0xFF).value == 0xEEFF
    assert j1939.ParameterGroupNumber(0, 0xFE, 0xB1).value == 0xFEB1
    assert j1939.ParameterGroupNumber(1, 0xFE, 0xCA).value == 0x1FECA
    assert j1939.ParameterGroupNumber(0, 0xF0, 0x05).value == 0xF005

    # from_message_id pulls DP/PF/PS from the embedded PGN
    parsed = j1939.ParameterGroupNumber()
    parsed.from_message_id(j1939.MessageId(can_id=0x18FEB121))
    assert parsed.data_page == 0
    assert parsed.pdu_format == 0xFE
    assert parsed.pdu_specific == 0xB1
    assert parsed.value == 0xFEB1
    assert parsed.is_pdu2_format

    parsed_p2p = j1939.ParameterGroupNumber()
    parsed_p2p.from_message_id(j1939.MessageId(can_id=0x18EF8522))
    assert parsed_p2p.pdu_format == 0xEF
    assert parsed_p2p.pdu_specific == 0x85
    assert parsed_p2p.is_pdu1_format
    assert parsed_p2p.value == 0xEF85


# --------------------------------------------------------------------------- #
# Receive routing -- subscriber + device_address gating
# --------------------------------------------------------------------------- #
# Each scripted CANRX below is a single 8-byte CAN frame.  CAN-Ids were derived
# from the (priority, PF, PS, SA) layout enforced by MessageId:
#       can_id = (priority<<26) | ((DP<<16 | PF<<8 | PS) << 8) | SA
# The PGN reported to subscribers is:
#       PDU2 (PF>=240): value = DP<<16 | PF<<8 | PS         (the GE is kept)
#       PDU1 (PF<=239): value = DP<<16 | PF<<8 | 0          (PS is masked out)
def test_pdu2_broadcast_delivered_to_subscriber(feeder):
    """A PDU2 (broadcast) frame is always delivered to any plain subscriber,
    even with no controller-application and no destination filter -- the stack
    treats the destination as GLOBAL for the PDU2 format."""
    feeder.can_messages = [
        # priority=6, PF=0xFE, PS=0xB1 (GE), SA=0x21 -> pgn 0xFEB1
        (Feeder.MsgType.CANRX, 0x18FEB121, [10, 20, 30, 40, 50, 60, 70, 80], 0.0),
    ]
    # PDU2: subscribers see the full PGN value (PF<<8 | PS = 0xFEB1).
    feeder.pdus = [(Feeder.MsgType.PDU, 0xFEB1, [10, 20, 30, 40, 50, 60, 70, 80])]
    feeder.subscribe()  # plain subscribe, no device_address
    feeder.drive()


def test_pdu1_p2p_delivered_only_to_matching_device_address(feeder):
    """A PDU1 (peer-to-peer) frame is delivered to a subscriber registered
    with ``device_address=X`` exactly when the frame's destination equals
    ``X``; the same frame must not surface when sent to a different
    destination."""
    # Subscribe directly on the ECU so we can pass device_address.
    feeder.ecu.subscribe(feeder._on_message, device_address=0x85)
    feeder.can_messages = [
        # priority=6, PF=0xEF, PS=0x85 (destination = subscribed address),
        # SA=0x22 -> can_id 0x18EF8522.
        (Feeder.MsgType.CANRX, 0x18EF8522, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
        # priority=6, PF=0xEF, PS=0xFF (GLOBAL) -- always delivered to all
        # subscribers regardless of dev_adr.
        (Feeder.MsgType.CANRX, 0x18EFFF22, [9, 9, 9, 9, 9, 9, 9, 9], 0.0),
    ]
    # For PDU1 the subscriber-visible PGN has PS masked to 0 -> 0xEF00.
    feeder.pdus = [
        (Feeder.MsgType.PDU, 0xEF00, [1, 2, 3, 4, 5, 6, 7, 8]),
        (Feeder.MsgType.PDU, 0xEF00, [9, 9, 9, 9, 9, 9, 9, 9]),
    ]
    feeder.drive()


def test_pdu1_p2p_dropped_when_destination_not_accepted(feeder):
    """A PDU1 frame whose destination address matches neither any registered
    subscriber's ``device_address`` nor any controller-application is dropped
    by the data-link layer; no PDU surfaces.  (Sanity floor: a matching
    destination on the same subscriber is still delivered.)"""
    feeder.ecu.subscribe(feeder._on_message, device_address=0x85)
    feeder.can_messages = [
        # PF=0xEF, PS=0x77 (NOT subscribed, NOT GLOBAL, no CA accepts it) -> dropped.
        (Feeder.MsgType.CANRX, 0x18EF7722, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
        # Then a frame to the subscribed address must still get through -- this
        # proves the previous frame was dropped (rather than the subscriber
        # being broken) and that no stray PDU was emitted in between.
        (Feeder.MsgType.CANRX, 0x18EF8522, [11, 12, 13, 14, 15, 16, 17, 18], 0.0),
    ]
    feeder.pdus = [
        (Feeder.MsgType.PDU, 0xEF00, [11, 12, 13, 14, 15, 16, 17, 18]),
    ]
    feeder.drive()
