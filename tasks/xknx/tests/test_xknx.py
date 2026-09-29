"""Behavioral byte-exact test suite for the xknx KNX codec subset.

Covers the DPT value-type framework, the telegram model (addresses, APCI, TPCI),
the cEMI frame layer, and the KNXnet/IP frame layer. All assertions go through the
public encode/decode API (``to_knx`` / ``from_knx``) and check exact bytes.
"""

import pytest

from xknx.dpt import DPTArray, DPTBase, DPTBinary
from xknx.exceptions import (
    ConversionError,
    CouldNotParseKNXIP,
    CouldNotParseTelegram,
)


# --------------------------------------------------------------------------- #
# DPT framework: transcoder lookup
# --------------------------------------------------------------------------- #
def test_dpt_lookup_by_name_and_number():
    """Transcoders resolve by value-type string and by main/sub number."""
    from xknx.dpt import DPTTemperature

    assert DPTBase.parse_transcoder("temperature") is DPTTemperature
    assert DPTBase.parse_transcoder({"main": 9, "sub": 1}) is DPTTemperature
    assert DPTBase.parse_transcoder("does_not_exist") is None
    assert DPTTemperature.dpt_main_number == 9
    assert DPTTemperature.dpt_sub_number == 1
    assert DPTTemperature.value_type == "temperature"


# --------------------------------------------------------------------------- #
# DPT 1 — 1-bit boolean (DPTBinary payload)
# --------------------------------------------------------------------------- #
def test_dpt1_switch_roundtrip():
    from xknx.dpt import DPTSwitch

    assert DPTSwitch.to_knx(True) == DPTBinary(1)
    assert DPTSwitch.to_knx(False) == DPTBinary(0)
    # DPTSwitch decodes to a Switch enum member: ON for 1, OFF for 0. Only the member
    # name is part of the contract; the enum's backing value is an implementation detail.
    assert DPTSwitch.from_knx(DPTBinary(1)).name == "ON"
    assert DPTSwitch.from_knx(DPTBinary(0)).name == "OFF"


# --------------------------------------------------------------------------- #
# DPT 5 — 8-bit unsigned: scaling (0..100%) and raw value
# --------------------------------------------------------------------------- #
def test_dpt5_scaling_roundtrip():
    from xknx.dpt import DPTScaling

    assert DPTScaling.to_knx(0) == DPTArray((0x00,))
    assert DPTScaling.to_knx(50) == DPTArray((0x80,))
    assert DPTScaling.to_knx(100) == DPTArray((0xFF,))
    assert DPTScaling.from_knx(DPTArray((0x80,))) == 50
    assert DPTScaling.from_knx(DPTArray((0xFF,))) == 100


def test_dpt5_value1byte_unsigned_roundtrip():
    from xknx.dpt import DPTValue1ByteUnsigned

    assert DPTValue1ByteUnsigned.to_knx(254) == DPTArray((0xFE,))
    assert DPTValue1ByteUnsigned.from_knx(DPTArray((0xFE,))) == 254


def test_dpt5_scaling_out_of_range_raises():
    from xknx.dpt import DPTScaling

    with pytest.raises(ConversionError):
        DPTScaling.to_knx(101)
    with pytest.raises(ConversionError):
        DPTScaling.to_knx(-1)


# --------------------------------------------------------------------------- #
# DPT 7 / 8 — 2-byte unsigned / signed
# --------------------------------------------------------------------------- #
def test_dpt7_2byte_unsigned_roundtrip():
    from xknx.dpt import DPT2ByteUnsigned

    assert DPT2ByteUnsigned.to_knx(65535) == DPTArray((0xFF, 0xFF))
    assert DPT2ByteUnsigned.from_knx(DPTArray((0x12, 0x34))) == 0x1234


def test_dpt8_2byte_signed_roundtrip():
    from xknx.dpt import DPTValue2Count

    assert DPTValue2Count.to_knx(-1000) == DPTArray((0xFC, 0x18))
    assert DPTValue2Count.from_knx(DPTArray((0xFC, 0x18))) == -1000


# --------------------------------------------------------------------------- #
# DPT 9 — 2-byte float (KNX exponent/mantissa packing)
# --------------------------------------------------------------------------- #
def test_dpt9_2byte_float_roundtrip():
    from xknx.dpt import DPTTemperature

    assert DPTTemperature.to_knx(21.0) == DPTArray((0x0C, 0x1A))
    assert DPTTemperature.to_knx(-10.0) == DPTArray((0x84, 0x18))
    assert DPTTemperature.from_knx(DPTArray((0x0C, 0x1A))) == 21.0
    assert DPTTemperature.from_knx(DPTArray((0x8A, 0x24))) == -30.0


def test_dpt9_2byte_float_special_values():
    """KNX 16-bit float: zero, near-zero sign, exponent boundary, and the
    extreme representable magnitudes (mantissa 2047 / -2048 at exponent 15)."""
    from xknx.dpt import DPT2ByteFloat

    # exact zero
    assert DPT2ByteFloat.to_knx(0.0) == DPTArray((0x00, 0x00))
    assert DPT2ByteFloat.from_knx(DPTArray((0x00, 0x00))) == 0.0
    # smallest negative resolution step keeps the sign bit set
    assert DPT2ByteFloat.to_knx(-0.01) == DPTArray((0x87, 0xFF))
    assert DPT2ByteFloat.from_knx(DPTArray((0x87, 0xFF))) == -0.01
    # exponent-boundary value 327.68 needs exponent stepping (mantissa renormalised)
    assert DPT2ByteFloat.to_knx(327.68) == DPTArray((0x2C, 0x00))
    # maximum and minimum representable magnitudes
    assert DPT2ByteFloat.to_knx(670760.96) == DPTArray((0x7F, 0xFF))
    assert DPT2ByteFloat.from_knx(DPTArray((0x7F, 0xFF))) == 670760.96
    assert DPT2ByteFloat.to_knx(-671088.64) == DPTArray((0xF8, 0x00))
    assert DPT2ByteFloat.from_knx(DPTArray((0xF8, 0x00))) == -671088.64
    # out of range raises
    with pytest.raises(ConversionError):
        DPT2ByteFloat.to_knx(680000.0)


def test_dpt9_wrong_length_raises():
    from xknx.dpt import DPTTemperature

    with pytest.raises(CouldNotParseTelegram):
        DPTTemperature.from_knx(DPTArray((0x01, 0x02, 0x03)))


# --------------------------------------------------------------------------- #
# DPT 13 / 14 — 4-byte signed and IEEE-754 float
# --------------------------------------------------------------------------- #
def test_dpt13_4byte_signed_roundtrip():
    """4-byte two's-complement signed: full 32-bit range incl. extremes + overflow."""
    from xknx.dpt import DPT4ByteSigned

    cases = {
        0: (0x00, 0x00, 0x00, 0x00),
        1: (0x00, 0x00, 0x00, 0x01),
        -1: (0xFF, 0xFF, 0xFF, 0xFF),
        2147483647: (0x7F, 0xFF, 0xFF, 0xFF),
        -2147483648: (0x80, 0x00, 0x00, 0x00),
    }
    for value, raw in cases.items():
        assert DPT4ByteSigned.to_knx(value) == DPTArray(raw)
        assert DPT4ByteSigned.from_knx(DPTArray(raw)) == value
    with pytest.raises(ConversionError):
        DPT4ByteSigned.to_knx(2147483648)


def test_dpt14_4byte_float_roundtrip():
    """4-byte IEEE-754 single precision, big-endian, both signs and zero."""
    from xknx.dpt import DPT4ByteFloat

    cases = {
        100.5: (0x42, 0xC9, 0x00, 0x00),
        -100.5: (0xC2, 0xC9, 0x00, 0x00),
        0.0: (0x00, 0x00, 0x00, 0x00),
    }
    for value, raw in cases.items():
        assert DPT4ByteFloat.to_knx(value) == DPTArray(raw)
        assert DPT4ByteFloat.from_knx(DPTArray(raw)) == value


# --------------------------------------------------------------------------- #
# DPT 10 / 11 / 19 — time, date, datetime
# --------------------------------------------------------------------------- #
def test_dpt10_time_roundtrip():
    from xknx.dpt import DPTTime

    raw = DPTTime.to_knx({"hour": 13, "minutes": 23, "seconds": 42, "day": "monday"})
    assert raw == DPTArray((0x2D, 0x17, 0x2A))
    decoded = DPTTime.from_knx(raw)
    assert (decoded.hour, decoded.minutes, decoded.seconds) == (13, 23, 42)
    assert decoded.day.value == 1


def test_dpt11_date_roundtrip():
    from xknx.dpt import DPTDate

    raw = DPTDate.to_knx({"year": 2017, "month": 11, "day": 28})
    assert raw == DPTArray((0x1C, 0x0B, 0x11))
    decoded = DPTDate.from_knx(raw)
    assert (decoded.year, decoded.month, decoded.day) == (2017, 11, 28)


def test_dpt19_datetime_roundtrip():
    from xknx.dpt import DPTDateTime

    value = {
        "year": 2017,
        "month": 11,
        "day": 28,
        "hour": 23,
        "minutes": 7,
        "seconds": 24,
        "day_of_week": 2,
    }
    raw = DPTDateTime.to_knx(value)
    # day_of_week is supplied but working_day is not -> only the working-day-invalid
    # bit (byte 6 bit 5 = 0x20) is set; all other validity bits clear.
    assert raw == DPTArray((0x75, 0x0B, 0x1C, 0x57, 0x07, 0x18, 0x20, 0x00))
    decoded = DPTDateTime.from_knx(raw)
    assert (decoded.year, decoded.month, decoded.day) == (2017, 11, 28)
    assert (decoded.hour, decoded.minutes, decoded.seconds) == (23, 7, 24)
    assert decoded.day_of_week.value == 2


def test_dpt19_datetime_status_flags():
    """All status/validity bits exercised: every field present plus all booleans set,
    so the two status bytes carry the full flag pattern (byte6=0xC1, byte7=0xC0)."""
    from xknx.dpt import DPTDateTime

    value = {
        "year": 2017,
        "month": 11,
        "day": 28,
        "hour": 23,
        "minutes": 7,
        "seconds": 24,
        "day_of_week": 2,
        "fault": True,
        "working_day": True,
        "dst": True,
        "external_sync": True,
        "source_reliable": True,
    }
    raw = DPTDateTime.to_knx(value)
    # byte6: fault(0x80) | working_day(0x40) | dst(0x01) = 0xC1 (no *_invalid bits)
    # byte7: external_sync(0x80) | source_reliable(0x40) = 0xC0
    assert raw == DPTArray((0x75, 0x0B, 0x1C, 0x57, 0x07, 0x18, 0xC1, 0xC0))
    decoded = DPTDateTime.from_knx(raw)
    assert decoded.fault is True
    assert decoded.working_day is True
    assert decoded.dst is True
    assert decoded.external_sync is True
    assert decoded.source_reliable is True


def test_dpt19_datetime_mixed_validity():
    """Partial value: date + weekday supplied, time omitted. The omitted time fields
    encode as 0 with the time-invalid bit set, and working-day (never given) sets its
    own invalid bit -> byte6 = 0x22; from_knx returns None for the invalid fields."""
    from xknx.dpt import DPTDateTime

    raw = DPTDateTime.to_knx({"year": 2020, "month": 6, "day": 15, "day_of_week": 1})
    # byte3 = dow(1)<<5 | hour(0) = 0x20; byte6 = working_day_invalid(0x20) | time_invalid(0x02)
    assert raw == DPTArray((0x78, 0x06, 0x0F, 0x20, 0x00, 0x00, 0x22, 0x00))
    decoded = DPTDateTime.from_knx(raw)
    assert (decoded.year, decoded.month, decoded.day) == (2020, 6, 15)
    assert (decoded.hour, decoded.minutes, decoded.seconds) == (None, None, None)
    assert decoded.day_of_week.value == 1


# --------------------------------------------------------------------------- #
# DPT 16 — fixed-length string (padded to 14 bytes)
# --------------------------------------------------------------------------- #
def test_dpt16_string_roundtrip():
    from xknx.dpt import DPTString

    raw = DPTString.to_knx("KNX")
    assert raw == DPTArray((0x4B, 0x4E, 0x58) + (0x00,) * 11)
    assert DPTString.from_knx(raw) == "KNX"


# --------------------------------------------------------------------------- #
# DPT 232 — 3-byte RGB color
# --------------------------------------------------------------------------- #
def test_dpt232_rgb_roundtrip():
    from xknx.dpt import DPTColorRGB

    raw = DPTColorRGB.to_knx({"red": 255, "green": 128, "blue": 0})
    assert raw == DPTArray((0xFF, 0x80, 0x00))
    decoded = DPTColorRGB.from_knx(DPTArray((0xFF, 0x80, 0x00)))
    assert (decoded.red, decoded.green, decoded.blue) == (255, 128, 0)


# --------------------------------------------------------------------------- #
# Telegram: group / individual addresses
# --------------------------------------------------------------------------- #
def test_group_address_encode_decode():
    from xknx.telegram.address import GroupAddress

    ga = GroupAddress("1/2/3")
    assert ga.raw == 2563
    assert ga.to_knx() == bytes((0x0A, 0x03))
    assert GroupAddress(2563).raw == 2563
    assert str(GroupAddress(2563)) == "1/2/3"


def test_individual_address_encode_decode():
    from xknx.telegram.address import IndividualAddress

    ia = IndividualAddress("1.2.3")
    assert ia.raw == 4611
    assert ia.to_knx() == bytes((0x12, 0x03))
    assert str(IndividualAddress(4611)) == "1.2.3"


# --------------------------------------------------------------------------- #
# Telegram: APCI services
# --------------------------------------------------------------------------- #
def test_apci_group_value_write_read_encode():
    from xknx.telegram.apci import GroupValueRead, GroupValueWrite

    assert GroupValueRead().to_knx() == bytes((0x00, 0x00))
    # small payload (<= 6 bits) is packed into the APCI octet itself
    assert GroupValueWrite(DPTBinary(1)).to_knx() == bytes((0x00, 0x81))
    # larger payload follows the 2-octet APCI header
    assert GroupValueWrite(DPTArray((0x0C, 0x1A))).to_knx() == bytes(
        (0x00, 0x80, 0x0C, 0x1A)
    )


def test_apci_resolve_from_bytes():
    from xknx.telegram.apci import APCI, GroupValueRead, GroupValueWrite

    assert isinstance(APCI.from_knx(bytes((0x00, 0x00))), GroupValueRead)
    decoded = APCI.from_knx(bytes((0x00, 0x80, 0x0C, 0x1A)))
    assert isinstance(decoded, GroupValueWrite)
    assert decoded.value == DPTArray((0x0C, 0x1A))


def test_apci_group_value_response_roundtrip():
    """GroupValueResponse (code 0x040) packs/resolves like Write against its own code."""
    from xknx.telegram.apci import APCI, GroupValueResponse

    # tiny payload packed into the second APCI octet
    assert GroupValueResponse(DPTBinary(1)).to_knx() == bytes((0x00, 0x41))
    # multi-byte payload follows the 2-octet header
    assert GroupValueResponse(DPTArray((0x0C, 0x1A))).to_knx() == bytes(
        (0x00, 0x40, 0x0C, 0x1A)
    )
    decoded = APCI.from_knx(bytes((0x00, 0x40, 0x0C, 0x1A)))
    assert isinstance(decoded, GroupValueResponse)
    assert decoded.value == DPTArray((0x0C, 0x1A))


# --------------------------------------------------------------------------- #
# Telegram: TPCI encode + resolve
# --------------------------------------------------------------------------- #
def test_tpci_encode():
    from xknx.telegram.tpci import TAck, TConnect, TDataConnected, TDataGroup

    assert TDataGroup().to_knx() == 0b00000000
    assert TConnect().to_knx() == 0b10000000
    assert TDataConnected(sequence_number=7).to_knx() == 0b01011100
    assert TAck(sequence_number=10).to_knx() == 0b11101010


def test_tpci_resolve():
    from xknx.telegram.tpci import (
        TPCI,
        TConnect,
        TDataBroadcast,
        TDataGroup,
        TNak,
    )

    assert TPCI.resolve(0b00000000, dst_is_group_address=True, dst_is_zero=False) == (
        TDataGroup()
    )
    assert TPCI.resolve(0b00000000, dst_is_group_address=True, dst_is_zero=True) == (
        TDataBroadcast()
    )
    assert TPCI.resolve(0b10000000, dst_is_group_address=False, dst_is_zero=False) == (
        TConnect()
    )
    assert TPCI.resolve(0b11010011, dst_is_group_address=False, dst_is_zero=False) == (
        TNak(sequence_number=4)
    )


# --------------------------------------------------------------------------- #
# cEMI frame: full L_Data round-trip
# --------------------------------------------------------------------------- #
def test_cemi_ldata_roundtrip():
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.telegram import Telegram
    from xknx.telegram.address import GroupAddress, IndividualAddress
    from xknx.telegram.apci import GroupValueWrite
    from xknx.telegram.tpci import TDataGroup

    telegram = Telegram(
        destination_address=GroupAddress("1/2/3"),
        payload=GroupValueWrite(DPTArray((0x0C, 0x1A))),
        tpci=TDataGroup(),
    )
    ldata = CEMILData.init_from_telegram(
        telegram, src_addr=IndividualAddress("1.1.1")
    )
    frame = CEMIFrame(code=CEMIMessageCode.L_DATA_IND, data=ldata)
    raw = frame.to_knx()
    assert raw == bytes.fromhex("2900bce011010a030300800c1a")

    decoded = CEMIFrame.from_knx(raw)
    assert decoded.code is CEMIMessageCode.L_DATA_IND
    out = decoded.data.telegram()
    assert out.destination_address == GroupAddress("1/2/3")
    assert out.payload == GroupValueWrite(DPTArray((0x0C, 0x1A)))


def test_cemi_connected_individual_roundtrip():
    """Point-to-point L_Data with a numbered (connected) TPCI to an individual
    address: the numbered TPCI octet is interleaved with the APCI high bits and the
    individual-address control flags differ from the group-addressed path."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.telegram import Telegram
    from xknx.telegram.address import IndividualAddress
    from xknx.telegram.apci import GroupValueWrite
    from xknx.telegram.tpci import TDataConnected

    telegram = Telegram(
        destination_address=IndividualAddress("1.1.5"),
        payload=GroupValueWrite(DPTArray((0x0C, 0x1A))),
        tpci=TDataConnected(sequence_number=3),
    )
    ldata = CEMILData.init_from_telegram(
        telegram, src_addr=IndividualAddress("1.1.1")
    )
    frame = CEMIFrame(code=CEMIMessageCode.L_DATA_REQ, data=ldata)
    raw = frame.to_knx()
    assert raw == bytes.fromhex("1100b06011011105034c800c1a")

    decoded = CEMIFrame.from_knx(raw)
    out = decoded.data.telegram()
    assert out.destination_address == IndividualAddress("1.1.5")
    assert isinstance(out.tpci, TDataConnected)
    assert out.tpci.sequence_number == 3
    assert out.payload == GroupValueWrite(DPTArray((0x0C, 0x1A)))


def test_cemi_control_tpci_roundtrip():
    """Control TPDU (TConnect / TDisconnect) point-to-point to an individual address:
    the frame carries an 8-bit TPCI octet and NO APCI payload (NPDU length 0), and the
    control fields use the individual-address path (control byte 2 = 0xb0, not 0xbc)."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.telegram import Telegram
    from xknx.telegram.address import IndividualAddress
    from xknx.telegram.tpci import TConnect, TDisconnect

    for tpci, expected in (
        (TConnect(), "1100b060110111050080"),
        (TDisconnect(), "1100b060110111050081"),
    ):
        telegram = Telegram(
            destination_address=IndividualAddress("1.1.5"),
            payload=None,
            tpci=tpci,
        )
        ldata = CEMILData.init_from_telegram(
            telegram, src_addr=IndividualAddress("1.1.1")
        )
        raw = CEMIFrame(code=CEMIMessageCode.L_DATA_REQ, data=ldata).to_knx()
        assert raw == bytes.fromhex(expected)

        decoded = CEMIFrame.from_knx(raw).data.telegram()
        assert decoded.destination_address == IndividualAddress("1.1.5")
        assert isinstance(decoded.tpci, type(tpci))
        assert decoded.payload is None


def test_cemi_connected_binary_payload_roundtrip():
    """Numbered (connected) data TPDU carrying a tiny DPTBinary GroupValueWrite to an
    individual address. This combines, in one NPDU, two distinct octet-packing rules
    that the existing connected (DPTArray) and group (DPTBinary) tests exercise only
    separately: the connected sequence number is OR-ed into the FIRST APCI octet (seq 3
    -> 0x4c) while the <=6-bit DPTBinary payload is packed into the SECOND APCI octet
    (0x80 | 1 = 0x81), and because the whole NPDU is two octets the NPDU length is 0x01
    (not 0x03 as for the DPTArray case, nor 0x00 as for a control TPDU)."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.telegram import Telegram
    from xknx.telegram.address import IndividualAddress
    from xknx.telegram.apci import GroupValueWrite
    from xknx.telegram.tpci import TDataConnected

    telegram = Telegram(
        destination_address=IndividualAddress("1.1.5"),
        payload=GroupValueWrite(DPTBinary(1)),
        tpci=TDataConnected(sequence_number=3),
    )
    ldata = CEMILData.init_from_telegram(
        telegram, src_addr=IndividualAddress("1.1.1")
    )
    raw = CEMIFrame(code=CEMIMessageCode.L_DATA_REQ, data=ldata).to_knx()
    # 11 00 b0 60 | 1101 src | 1105 dst | 01 npdu-len | 4c tpci(seq3)|apci-hi | 81 apci-lo|payload
    assert raw == bytes.fromhex("1100b06011011105014c81")

    decoded = CEMIFrame.from_knx(raw).data.telegram()
    assert decoded.destination_address == IndividualAddress("1.1.5")
    assert isinstance(decoded.tpci, TDataConnected)
    assert decoded.tpci.sequence_number == 3
    assert decoded.payload == GroupValueWrite(DPTBinary(1))


def test_cemi_wrong_message_code_raises():
    from xknx.cemi import CEMIFrame

    with pytest.raises(Exception):
        CEMIFrame.from_knx(bytes.fromhex("ff00bce011010a030300800c1a"))


# --------------------------------------------------------------------------- #
# KNXnet/IP: header
# --------------------------------------------------------------------------- #
def test_knxip_header_encode():
    from xknx.knxip import KNXIPFrame, RoutingIndication
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.telegram import Telegram
    from xknx.telegram.address import GroupAddress, IndividualAddress
    from xknx.telegram.apci import GroupValueWrite
    from xknx.telegram.tpci import TDataGroup

    telegram = Telegram(
        destination_address=GroupAddress("1/2/3"),
        payload=GroupValueWrite(DPTBinary(1)),
        tpci=TDataGroup(),
    )
    ldata = CEMILData.init_from_telegram(telegram, src_addr=IndividualAddress("1.1.1"))
    cemi = CEMIFrame(code=CEMIMessageCode.L_DATA_IND, data=ldata)
    frame = KNXIPFrame.init_from_body(RoutingIndication(raw_cemi=cemi.to_knx()))
    raw = frame.to_knx()
    # Exact full wire frame: 0610 (version 1.0) | 0530 (ROUTING_INDICATION) | 0011 (total
    # length 17) | cEMI 2900 bce0 1101(src) 0a03(dst 1/2/3) 01(npdu-len) 0081(NPDU: TPCI+APCI
    # 00, DPTBinary(1) write 81). Pins the computed length field and body packing, not just
    # the version/service constants.
    assert raw == bytes.fromhex("0610053000112900bce011010a03010081")


# --------------------------------------------------------------------------- #
# KNXnet/IP: search request (HPAI)
# --------------------------------------------------------------------------- #
def test_knxip_search_request_roundtrip():
    from xknx.knxip import HPAI, KNXIPFrame, SearchRequest

    raw = bytes.fromhex("06 10 02 01 00 0E 08 01 E0 00 17 0C 0E 57".replace(" ", ""))
    frame, _ = KNXIPFrame.from_knx(raw)
    assert isinstance(frame.body, SearchRequest)
    assert frame.body.discovery_endpoint == HPAI(ip_addr="224.0.23.12", port=3671)

    rebuilt = KNXIPFrame.init_from_body(
        SearchRequest(discovery_endpoint=HPAI(ip_addr="224.0.23.12", port=3671))
    )
    assert rebuilt.to_knx() == raw


# --------------------------------------------------------------------------- #
# KNXnet/IP: connect request
# --------------------------------------------------------------------------- #
def test_knxip_connect_request_roundtrip():
    from xknx.knxip import (
        HPAI,
        ConnectRequest,
        ConnectRequestInformation,
        ConnectRequestType,
        KNXIPFrame,
        TunnellingLayer,
    )

    raw = bytes.fromhex(
        "061002050018080" "1C0A82A018495080" "1C0A82A01CCA90203".replace(" ", "")
    )
    frame, _ = KNXIPFrame.from_knx(raw)
    assert isinstance(frame.body, ConnectRequest)
    assert frame.body.cri.connection_type is ConnectRequestType.DEVICE_MGMT_CONNECTION

    cri = ConnectRequestInformation(
        connection_type=ConnectRequestType.TUNNEL_CONNECTION,
        knx_layer=TunnellingLayer.DATA_LINK_LAYER,
        individual_address=None,
    )
    body = ConnectRequest(
        control_endpoint=HPAI(ip_addr="192.168.42.1", port=33941),
        data_endpoint=HPAI(ip_addr="192.168.42.1", port=52393),
        cri=cri,
    )
    rebuilt = KNXIPFrame.init_from_body(body).to_knx()
    expected = bytes.fromhex(
        "06 10 02 05 00 1A 08 01 C0 A8 2A 01 84 95 08 01"
        "C0 A8 2A 01 CC A9 04 04 02 00".replace(" ", "")
    )
    assert rebuilt == expected


# --------------------------------------------------------------------------- #
# KNXnet/IP: tunnelling request carrying a cEMI L_Data
# --------------------------------------------------------------------------- #
def test_knxip_tunnelling_request_roundtrip():
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.knxip import KNXIPFrame, TunnellingRequest
    from xknx.telegram import Telegram
    from xknx.telegram.address import GroupAddress
    from xknx.telegram.apci import GroupValueWrite

    raw = bytes.fromhex(
        "06 10 04 20 00 15 04 01 17 00 11 00 BC E0 00 00 48 08 01 00 81".replace(
            " ", ""
        )
    )
    frame, _ = KNXIPFrame.from_knx(raw)
    assert isinstance(frame.body, TunnellingRequest)
    assert frame.body.communication_channel_id == 1
    assert frame.body.sequence_counter == 23
    incoming = CEMIFrame.from_knx(frame.body.raw_cemi)
    telegram = incoming.data.telegram()
    assert telegram.destination_address == GroupAddress("9/0/8")
    assert telegram.payload == GroupValueWrite(DPTBinary(1))

    outgoing = CEMIFrame(
        code=CEMIMessageCode.L_DATA_REQ,
        data=CEMILData.init_from_telegram(
            Telegram(
                destination_address=GroupAddress("9/0/8"),
                payload=GroupValueWrite(DPTBinary(1)),
            ),
        ),
    )
    rebuilt = KNXIPFrame.init_from_body(
        TunnellingRequest(
            communication_channel_id=1,
            sequence_counter=23,
            raw_cemi=outgoing.to_knx(),
        )
    )
    assert rebuilt.to_knx() == raw


# --------------------------------------------------------------------------- #
# KNXnet/IP: routing indication carrying a GroupValueResponse (end-to-end)
# --------------------------------------------------------------------------- #
def test_knxip_routing_group_value_response_roundtrip():
    """A GroupValueResponse (APCI 0x040) carried end-to-end inside a cEMI L_Data,
    wrapped in a routing-indication KNXnet/IP frame. Exercises response-APCI multi-byte
    payload packing within the NPDU + the group-address control fields + the routing
    header all assembled together (distinct from the isolated APCI/cEMI/routing tests)."""
    from xknx.cemi import CEMIFrame, CEMILData, CEMIMessageCode
    from xknx.knxip import KNXIPFrame, RoutingIndication
    from xknx.telegram import Telegram
    from xknx.telegram.address import GroupAddress, IndividualAddress
    from xknx.telegram.apci import GroupValueResponse

    telegram = Telegram(
        destination_address=GroupAddress("9/0/8"),
        payload=GroupValueResponse(DPTArray((0x12, 0x34))),
    )
    cemi = CEMIFrame(
        code=CEMIMessageCode.L_DATA_IND,
        data=CEMILData.init_from_telegram(
            telegram, src_addr=IndividualAddress("1.1.1")
        ),
    )
    wire = KNXIPFrame.init_from_body(RoutingIndication(raw_cemi=cemi.to_knx())).to_knx()
    assert wire == bytes.fromhex("0610053000132900bce0110148080300401234")

    frame, remainder = KNXIPFrame.from_knx(wire)
    assert remainder == b""
    assert isinstance(frame.body, RoutingIndication)
    decoded_cemi = CEMIFrame.from_knx(frame.body.raw_cemi)
    out = decoded_cemi.data.telegram()
    assert out.destination_address == GroupAddress("9/0/8")
    assert out.payload == GroupValueResponse(DPTArray((0x12, 0x34)))


# --------------------------------------------------------------------------- #
# KNXnet/IP: malformed frame is rejected
# --------------------------------------------------------------------------- #
def test_knxip_malformed_frame_raises():
    from xknx.knxip import KNXIPFrame

    with pytest.raises(CouldNotParseKNXIP):
        KNXIPFrame.from_knx(bytes((0x06, 0x10, 0x04, 0x20, 0x00, 0x15, 0x03)))
