"""Core J1939 behaviour: name/id encoding, address claiming, the J1939-21
transport protocol (BAM and RTS/CTS, both directions) and DM14/DM15/DM16
memory-access queries.

All transport-protocol scenarios are driven through the public stack API with
the mock :class:`Feeder`; assertions are byte-exact on every frame placed on
the (simulated) bus.
"""

import j1939
from feeder import Feeder


# --------------------------------------------------------------------------- #
# Name / MessageId / ParameterGroupNumber encoding
# --------------------------------------------------------------------------- #
# The 8-byte little-endian NAME used throughout the address-claim scenarios.
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


# Name / MessageId / ParameterGroupNumber encoding (value objects) are covered
# in depth — exact value/bytes, boundaries, validation, routing — by
# test_j1939_encoding.py; not duplicated here.


# --------------------------------------------------------------------------- #
# Address claiming (SAE J1939-81)
# --------------------------------------------------------------------------- #
def _run_address_claim(feeder, arbitrary_address_capable, expected_state):
    name = j1939.Name(
        **dict(CLAIM_NAME_KWARGS, arbitrary_address_capable=arbitrary_address_capable)
    )
    ca = feeder.ecu.add_ca(name=name, device_address=128)
    ca.start()
    feeder.drive()
    feeder.wait_for_state(ca, expected_state)
    assert ca.state == expected_state, "state=%r expected=%r" % (ca.state, expected_state)


def test_addr_claim_fixed(feeder):
    """Single-address-capable CA claims a fixed address with no contender and
    reaches the NORMAL state."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFF80, [135, 214, 82, 83, 130, 201, 254, 82], 0.0),
    ]
    _run_address_claim(feeder, 0, j1939.ControllerApplication.State.NORMAL)


def test_addr_claim_fixed_veto_lose(feeder):
    """A contender with a lower NAME vetoes the claim; a single-address-capable
    CA must give up and announce CANNOT CLAIM (address 254)."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFF80, [135, 214, 82, 83, 130, 201, 254, 82], 0.0),
        (Feeder.MsgType.CANRX, 0x18EEFF80, [135, 214, 82, 83, 130, 111, 254, 82], 0.0),
        (Feeder.MsgType.CANTX, 0x18EEFFFE, [135, 214, 82, 83, 130, 201, 254, 82], 0.0),
    ]
    _run_address_claim(feeder, 0, j1939.ControllerApplication.State.CANNOT_CLAIM)


def test_addr_claim_fixed_veto_win(feeder):
    """A contender with a higher NAME loses arbitration; our CA keeps its
    address and re-announces the claim."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFF80, [135, 214, 82, 83, 130, 201, 254, 82], 0.0),
        (Feeder.MsgType.CANRX, 0x18EEFF80, [135, 214, 82, 83, 130, 222, 254, 82], 0.0),
        (Feeder.MsgType.CANTX, 0x18EEFF80, [135, 214, 82, 83, 130, 201, 254, 82], 0.0),
    ]
    _run_address_claim(feeder, 0, j1939.ControllerApplication.State.NORMAL)


def test_addr_claim_arbitrary_veto_lose(feeder):
    """An arbitrary-address-capable CA that loses arbitration automatically
    claims the next address (129)."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EEFF80, [135, 214, 82, 83, 130, 201, 254, 210], 0.0),
        (Feeder.MsgType.CANRX, 0x18EEFF80, [135, 214, 82, 83, 130, 111, 254, 82], 0.0),
        (Feeder.MsgType.CANTX, 0x18EEFF81, [135, 214, 82, 83, 130, 201, 254, 210], 0.0),
    ]
    _run_address_claim(feeder, 1, j1939.ControllerApplication.State.NORMAL)


# --------------------------------------------------------------------------- #
# J1939-21 reception
# --------------------------------------------------------------------------- #
def test_broadcast_receive_short(feeder):
    """A single-frame broadcast PDU (PGN 65202) is delivered verbatim."""
    feeder.accept_all_messages()
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x00FEB201, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
    ]
    feeder.pdus = [(Feeder.MsgType.PDU, 65202, [1, 2, 3, 4, 5, 6, 7, 8])]
    feeder.subscribe()
    feeder.drive()


def test_broadcast_receive_long_bam(feeder):
    """A 20-byte broadcast message announced with BAM is reassembled from its
    three TP.DT frames (PGN 65200)."""
    feeder.accept_all_messages()
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x00ECFF01, [32, 20, 0, 3, 255, 0xB0, 0xFE, 0], 0.0),
        (Feeder.MsgType.CANRX, 0x00EBFF01, [1, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANRX, 0x00EBFF01, [2, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANRX, 0x00EBFF01, [3, 1, 2, 3, 4, 5, 6, 255], 0.0),
    ]
    feeder.pdus = [
        (Feeder.MsgType.PDU, 65200, [1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6])
    ]
    feeder.subscribe()
    feeder.drive()


def test_peer_to_peer_receive_short(feeder):
    """A single-frame peer-to-peer PDU addressed to us (PGN 56320) is
    delivered verbatim."""
    feeder.accept_all_messages()
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x00DC0201, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
    ]
    feeder.pdus = [(Feeder.MsgType.PDU, 56320, [1, 2, 3, 4, 5, 6, 7, 8])]
    feeder.subscribe()
    feeder.drive()


def test_peer_to_peer_receive_long_rts_cts(feeder):
    """A 20-byte peer-to-peer message is received with the RTS/CTS connection
    protocol: the stack must answer each TP.DT batch with a CTS and finish
    with an EndOfMsgACK."""
    feeder.accept_all_messages()
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x00EC0201, [16, 20, 0, 3, 1, 176, 254, 0], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEC0102, [17, 1, 1, 255, 255, 176, 254, 0], 0.0),
        (Feeder.MsgType.CANRX, 0x00EB0201, [1, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEC0102, [17, 1, 2, 255, 255, 176, 254, 0], 0.0),
        (Feeder.MsgType.CANRX, 0x00EB0201, [2, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEC0102, [17, 1, 3, 255, 255, 176, 254, 0], 0.0),
        (Feeder.MsgType.CANRX, 0x00EB0201, [3, 1, 2, 3, 4, 5, 6, 255], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEC0102, [19, 20, 0, 3, 255, 176, 254, 0], 0.0),
    ]
    feeder.pdus = [
        (Feeder.MsgType.PDU, 65200, [1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6])
    ]
    feeder.subscribe()
    feeder.drive()


# --------------------------------------------------------------------------- #
# J1939-21 transmission
# --------------------------------------------------------------------------- #
def test_peer_to_peer_send_short(feeder):
    """Sending an 8-byte peer-to-peer PDU emits a single CAN frame (PGN 61440)."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18F09B90, [1, 2, 3, 4, 5, 6, 7, 8], 0.0),
    ]
    feeder.send((Feeder.MsgType.PDU, 61440, [1, 2, 3, 4, 5, 6, 7, 8]), 144, 155)
    feeder.check()


def test_peer_to_peer_send_long_rts_cts(feeder):
    """Sending a 20-byte peer-to-peer PDU runs the originator side of RTS/CTS:
    RTS, then one TP.DT per CTS, then consume the EndOfMsgACK (PGN 57088)."""
    feeder.accept_all_messages()
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EC9B90, [16, 20, 0, 3, 1, 0, 223, 0], 0.0),
        (Feeder.MsgType.CANRX, 0x1CEC909B, [17, 1, 1, 255, 255, 0, 223, 0], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEB9B90, [1, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANRX, 0x1CEC909B, [17, 1, 2, 255, 255, 0, 223, 0], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEB9B90, [2, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANRX, 0x1CEC909B, [17, 1, 3, 255, 255, 0, 223, 0], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEB9B90, [3, 1, 2, 3, 4, 5, 6, 255], 0.0),
        (Feeder.MsgType.CANRX, 0x1CEC909B, [19, 20, 0, 3, 255, 0, 223, 0], 0.0),
    ]
    feeder.send(
        (Feeder.MsgType.PDU, 57088, [1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6]),
        144,
        155,
    )
    feeder.check()


def test_broadcast_send_long_bam(feeder):
    """Sending a 20-byte broadcast PDU emits a BAM announcement followed by the
    three TP.DT frames (PGN 65200)."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18ECFF90, [32, 20, 0, 3, 255, 176, 254, 0], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEBFF90, [1, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEBFF90, [2, 1, 2, 3, 4, 5, 6, 7], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEBFF90, [3, 1, 2, 3, 4, 5, 6, 255], 0.0),
    ]
    pdu = (Feeder.MsgType.PDU, 65200, [1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6, 7, 1, 2, 3, 4, 5, 6])
    feeder.send(pdu, 144, pdu[1])
    feeder.check()


# --------------------------------------------------------------------------- #
# Memory access (DM14 / DM15 / DM16) with seed-key authentication
# --------------------------------------------------------------------------- #
def _key_from_seed(seed):
    return seed ^ 0xFFFF


def test_dm14_read_with_seed_key(feeder):
    """A DM14 read that the responder answers with a seed: the host must reply
    with the key derived by its seed-key algorithm, then collect the DM16 data
    and acknowledge operation-complete."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x13, 0x03, 0x00, 0x00, 0x92, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x00, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0x5A, 0xA5], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x13, 0x03, 0x00, 0x00, 0x92, 0xA5, 0x5A], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD7F9D4, [0x01, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x19, 0x03, 0x00, 0x00, 0x92, 0xFF, 0xFF], 0.0),
    ]
    feeder.pdus_from_messages()
    ca = feeder.accept_all_messages(device_address_preferred=0xF9, bypass_address_claim=True)
    dm14 = j1939.Dm14Query(ca)
    dm14.set_seed_key_algorithm(_key_from_seed)
    feeder.subscribe()
    dm14.read(0xD4, 1, 0x92000003, 1)
    feeder.drive()


def test_dm14_read_no_seed_key(feeder):
    """A DM14 read that the responder lets proceed without authentication."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x13, 0x03, 0x00, 0x00, 0x92, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD7F9D4, [0x01, 0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x19, 0x03, 0x00, 0x00, 0x92, 0xFF, 0xFF], 0.0),
    ]
    feeder.pdus_from_messages()
    ca = feeder.accept_all_messages(device_address_preferred=0xF9, bypass_address_claim=True)
    dm14 = j1939.Dm14Query(ca)
    dm14.set_seed_key_algorithm(_key_from_seed)
    feeder.subscribe()
    dm14.read(0xD4, 1, 0x92000003, 1)
    feeder.drive()


def test_dm14_write_with_seed_key(feeder):
    """A DM14 write that requires seed-key authentication before the DM16 data
    transfer."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x15, 0x07, 0x00, 0x00, 0x91, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x00, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0x5A, 0xA5], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x15, 0x07, 0x00, 0x00, 0x91, 0xA5, 0x5A], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D7D4F9, [0x04, 0x44, 0x33, 0x22, 0x11], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x19, 0x07, 0x00, 0x00, 0x91, 0xFF, 0xFF], 0.0),
    ]
    feeder.pdus_from_messages()
    ca = feeder.accept_all_messages(device_address_preferred=0xF9, bypass_address_claim=True)
    dm14 = j1939.Dm14Query(ca)
    dm14.set_seed_key_algorithm(_key_from_seed)
    feeder.subscribe()
    dm14.write(0xD4, 1, 0x91000007, [0x11223344], object_byte_size=4)
    feeder.drive()


def test_dm14_write_no_seed_key(feeder):
    """A DM14 write that the responder lets proceed without authentication."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x15, 0x07, 0x00, 0x00, 0x91, 0x07, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x01, 0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D7D4F9, [0x04, 0x44, 0x33, 0x22, 0x11], 0.0),
        (Feeder.MsgType.CANRX, 0x1CD8F9D4, [0x00, 0x19, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 0.0),
        (Feeder.MsgType.CANTX, 0x18D9D4F9, [0x01, 0x19, 0x07, 0x00, 0x00, 0x91, 0xFF, 0xFF], 0.0),
    ]
    feeder.pdus_from_messages()
    ca = feeder.accept_all_messages(device_address_preferred=0xF9, bypass_address_claim=True)
    dm14 = j1939.Dm14Query(ca)
    dm14.set_seed_key_algorithm(_key_from_seed)
    feeder.subscribe()
    dm14.write(0xD4, 1, 0x91000007, [0x11223344], object_byte_size=4)
    feeder.drive()
