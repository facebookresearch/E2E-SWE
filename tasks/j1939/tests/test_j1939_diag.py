"""J1939 diagnostic messages: DTC encoding/decoding, DM1 (active DTC) send +
receive + multi-DTC transport-protocol round trip, DM11 (clear active DTCs)
request, and DM22 (individual clear).

Byte-exact scenarios are scripted through the mock :class:`Feeder`; the
multi-DTC DM1 transmission (which spans more than 8 bytes and therefore rides
the J1939-21 BAM transport protocol) is driven through :class:`TwoNodeBus` so
the originator/responder transport halves run against each other instead of
hand-derived TP frames.
"""

import time

import j1939
from feeder import Feeder, TwoNodeBus


# --------------------------------------------------------------------------- #
# DTC packing
# --------------------------------------------------------------------------- #
# Encoding rule (SAE J1939-73 DM01 4-byte DTC):
#   dtc = (spn & 0xFFFF)               # low 16 bits of SPN -> bits 0..15
#       | ((spn & 0x70000) << 5)       # upper 3 bits of SPN -> bits 21..23
#       | ((fmi & 0x1F)    << 16)      # 5-bit FMI           -> bits 16..20
#       | ((oc  & 0x7F)    << 24)      # 7-bit occurrence ct -> bits 24..30
# (bit 31 is the SPN conversion mode 'cm', always 0 here.)
_DTC_TRIPLES = [
    # spn fits in 16 bits, generic case
    (100,    5,  2, 0x02050064),
    # spn still <16 bits, larger fmi/oc
    (4567,  12,  1, 0x010C11D7),
    # spn > 16 bits exercises the (spn & 0x70000) << 5 high-bit path
    (520192, 14, 15, 0x0FEEF000),
    # Edge corners of the packing formula (hand-derived from the §2.6 formula):
    #   max 19-bit SPN with zero FMI/OC -- top-3 SPN bits route to bits 21..23
    #   without bleeding into the FMI field.
    #     spn=524287 (0x7FFFF): low16=0xFFFF, high3=(0x70000<<5)=0xE00000 -> 0x00E0FFFF
    (524287,  0,   0,  0x00E0FFFF),
    #   all fields maxed simultaneously -- cross-field bleed would corrupt
    #   at least one of spn/fmi/oc on decode.
    #     spn=520192 (0x7F000), fmi=31, oc=127 -> 0xF000 | 0xE00000 | 0x1F0000 | 0x7F000000
    (520192, 31, 127,  0x7FFFF000),
    #   SPN=0 with max FMI + max OC -- inverse SPN calc still yields 0 when only
    #   the upper fields are populated.
    #     fmi=0x1F0000, oc=0x7F000000 -> 0x7F1F0000
    (0,      31, 127,  0x7F1F0000),
]


def test_dtc_encode_decode_roundtrip():
    """``DTC(spn=, fmi=, oc=).dtc`` packs the 4-byte code per J1939-73 and
    ``DTC(dtc=code)`` recovers the original (spn, fmi, oc) triple.  Covers the
    generic <16-bit-SPN case, a SPN that exceeds 16 bits (high 3 SPN bits land
    at bit 21), and the formula's corners: max 19-bit SPN, max 5-bit FMI, max
    7-bit OC, and combinations thereof (no cross-field bleed; cm stays 0)."""
    for spn, fmi, oc, expected in _DTC_TRIPLES:
        encoded = j1939.DTC(spn=spn, fmi=fmi, oc=oc).dtc
        assert encoded == expected, (
            "encode mismatch for spn=%d fmi=%d oc=%d: got 0x%08X expected 0x%08X"
            % (spn, fmi, oc, encoded, expected)
        )

        decoded = j1939.DTC(dtc=expected)
        assert decoded.spn == spn
        assert decoded.fmi == fmi
        assert decoded.oc == oc
        assert decoded.cm == 0
        assert decoded.dtc == expected


# --------------------------------------------------------------------------- #
# DM1 send (single DTC, fits in a single frame, no transport protocol)
# --------------------------------------------------------------------------- #
# Lamp encoding (SAE J1939-73 DM1, first two bytes):
#   keys = ['pl', 'awl', 'rsl', 'mil']   # indices 0..3
#   data[0] |= (lamp  << (idx*2))
#   data[1] |= (flash << (idx*2))
# Status -> (lamp, flash) lookup:  OFF=(0,3), ON=(1,3),
#                                  ON_SLOW_FLASH=(1,0), ON_FAST_FLASH=(1,1), NA=(3,3)
# With pl=awl=rsl=OFF (each contributes 0 to data[0], 3<<(idx*2) to data[1])
# and mil=ON (contributes 1<<6 to data[0], 3<<6 to data[1]):
#   data[0] = 0 | 0 | 0 | (1<<6) = 0x40
#   data[1] = 3 | (3<<2) | (3<<4) | (3<<6) = 0x03 | 0x0C | 0x30 | 0xC0 = 0xFF
def test_dm1_send_single_dtc(feeder):
    """``Dm1.start_send`` cyclically calls the user callback and transmits the
    returned (lamp_status, dtc_list) as DM01.  The first emission packs the
    lamp status into the first two bytes (mil=ON, others OFF -> 0x40 0xFF) and
    appends the 4-byte DTC for spn=4567 / fmi=12 / oc=1 (0x010C11D7 ->
    little-endian 0xD7 0x11 0x0C 0x01).  Single-frame payload of 6 bytes uses
    priority 6, broadcast PGN DM01 (0xFECA), source 0x90 -> CAN-ID 0x18FECA90.
    ``stop_send`` halts the timer before a second cycle can fire."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18FECA90,
         [0x40, 0xFF, 0xD7, 0x11, 0x0C, 0x01], 0.0),
    ]
    ca = feeder.accept_all_messages(device_address_preferred=0x90,
                                    bypass_address_claim=True)
    dm1 = j1939.Dm1(ca)

    def cb():
        return ({'mil': j1939.DtcLamp.ON},
                [{'spn': 4567, 'fmi': 12, 'oc': 1}])

    # Schedule cyclic sending; ``drive`` returns as soon as the single expected
    # CANTX is consumed (well within the next cycle), then stop the timer so a
    # second tick can't push an unexpected frame past the Feeder's checker.
    dm1.start_send(cb, cycletime=1)
    try:
        feeder.drive(timeout=3.0)
    finally:
        dm1.stop_send(cb)


# --------------------------------------------------------------------------- #
# DM1 receive (single DTC)
# --------------------------------------------------------------------------- #
# Inject a DM1 frame with the same lamp byte layout (mil=ON, others OFF) and
# DTC for (spn=100, fmi=5, oc=2) -> 0x02050064 -> bytes 0x64 0x00 0x05 0x02.
# Reverse-decode of data[0]=0x40, data[1]=0xFF:
#   pl  : data[0]&0x03=0, data[1]&0x03=3 -> get_status(0,3)=OFF
#   awl : (data[0]>>2)&3=0, (data[1]>>2)&3=3 -> OFF
#   rsl : (data[0]>>4)&3=0, (data[1]>>4)&3=3 -> OFF
#   mil : (data[0]>>6)&3=1, (data[1]>>6)&3=3 -> ON
def test_dm1_receive_single_dtc(feeder):
    """A scripted DM01 CAN frame from sa=0x42 is parsed by Dm1: subscribers
    receive the decoded lamp_status dict (mil=ON, rest OFF) and a one-element
    dtc_dic_list containing the recovered (spn, fmi, oc) triple."""
    received = []

    def cb(sa, lamp_status, dtc_dic_list, timestamp):
        received.append((sa, lamp_status, dtc_dic_list))

    ca = feeder.accept_all_messages(device_address_preferred=0x90,
                                    bypass_address_claim=True)
    dm1 = j1939.Dm1(ca)
    dm1.subscribe(cb)

    # CAN-ID for incoming DM01 from sa=0x42: priority 6, PGN 0xFECA, SA 0x42
    #   -> (6 << 26) | (0xFECA << 8) | 0x42 = 0x18FECA42
    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x18FECA42,
         [0x40, 0xFF, 0x64, 0x00, 0x05, 0x02], 0.0),
    ]
    feeder.drive()

    assert len(received) == 1, "expected one DM1 callback, got %r" % (received,)
    sa, lamp_status, dtc_dic_list = received[0]
    assert sa == 0x42
    assert lamp_status == {
        'pl':  j1939.DtcLamp.OFF,
        'awl': j1939.DtcLamp.OFF,
        'rsl': j1939.DtcLamp.OFF,
        'mil': j1939.DtcLamp.ON,
    }
    assert dtc_dic_list == [{'spn': 100, 'fmi': 5, 'oc': 2}]


# --------------------------------------------------------------------------- #
# DM22 (individual DTC clear request)
# --------------------------------------------------------------------------- #
# Dm22._send_request payload layout:
#   data[0] = control_byte   (ACT_REQ=17, PA_REQ=1)
#   data[1..4] = 0xFF
#   data[5] = spn & 0xFF
#   data[6] = (spn >> 8) & 0xFF
#   data[7] = ((spn >> 22) & 0xE0) | (fmi & 0x1F)
# PGN DM22 = 49920 = 0xC300, PDU-format 0xC3 is PDU1 (peer-to-peer) so the
# destination address is encoded in the PS field of the CAN-ID.
# With ca at 0xF9, dest 0xD4, spn 4567 (0x11D7 -> low byte 0xD7, mid 0x11,
# spn>>22 == 0), fmi 12 (0x0C):
#   data[5..7] = 0xD7, 0x11, 0x00|0x0C = 0x0C
# CAN-ID: priority 6, PGN (0<<16)|(0xC3<<8)|0xD4 = 0xC3D4, SA 0xF9
#   -> (6<<26) | (0xC3D4 << 8) | 0xF9 = 0x18C3D4F9
def test_dm22_request_clear_active_and_previously_active(feeder):
    """``Dm22.request_clear_act_dtc`` and ``request_clear_pa_dtc`` emit the
    same 8-byte DM22 frame layout per §2.6, differing only in the leading
    control byte (17 for ACT_REQ, 1 for PA_REQ).  Both variants are checked
    here so the byte-exact derivation is asserted in one place."""
    # ACT_REQ variant.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18C3D4F9,
         [0x11, 0xFF, 0xFF, 0xFF, 0xFF, 0xD7, 0x11, 0x0C], 0.0),
    ]
    ca = feeder.accept_all_messages(device_address_preferred=0xF9,
                                    bypass_address_claim=True)
    dm22 = j1939.Dm22(ca)
    dm22.request_clear_act_dtc(0xD4, 4567, 12)
    feeder.check()

    # PA_REQ variant — re-script the next expected frame on the same
    # feeder/CA pair.  Reusing the ECU keeps the test focused on the
    # control-byte difference.
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18C3D4F9,
         [0x01, 0xFF, 0xFF, 0xFF, 0xFF, 0xD7, 0x11, 0x0C], 0.0),
    ]
    dm22.request_clear_pa_dtc(0xD4, 4567, 12)
    feeder.check()


# --------------------------------------------------------------------------- #
# DM11 (clear-all-active-DTCs request)
# --------------------------------------------------------------------------- #
# Dm11.request_clear_all delegates to ca.send_request(0, DM11_pgn, dest), which
# builds a J1939-21 REQUEST PGN (0xEA00) frame:
#   data = [pgn & 0xFF, (pgn >> 8) & 0xFF, (pgn >> 16) & 0xFF]
# DM11 PGN = 65235 = 0xFED3 -> data = [0xD3, 0xFE, 0x00].
# REQUEST is PDU1 (pdu_format 0xEA), so destination rides in PS.  With ca at
# 0xF9 and dest 0xD4 the CAN-ID is:
#   priority 6, PGN (0<<16)|(0xEA<<8)|0xD4 = 0xEAD4
#   -> (6 << 26) | (0xEAD4 << 8) | 0xF9 = 0x18EAD4F9
def test_dm11_request_clear_all(feeder):
    """``Dm11.request_clear_all`` emits a J1939-21 REQUEST frame asking the
    destination ECU to clear all active DTCs (i.e. PGN DM11 little-endian in
    the 3-byte REQUEST payload)."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18EAD4F9, [0xD3, 0xFE, 0x00], 0.0),
    ]
    ca = feeder.accept_all_messages(device_address_preferred=0xF9,
                                    bypass_address_claim=True)
    dm11 = j1939.Dm11(ca)
    dm11.request_clear_all(0xD4)
    feeder.check()


# --------------------------------------------------------------------------- #
# DM1 round-2: larger DTC fan-outs and harder lamp combinations
# --------------------------------------------------------------------------- #
# All four tests below remain inside the §2.6 contract: DTC packing formula,
# DtcLamp encoding table, ``dtc_list`` = list of ``{'spn','fmi','oc'}`` dicts,
# and the public ``start_send`` / ``stop_send`` / ``subscribe`` API.  Byte-exact
# assertions on emitted DM1 frames use only the §2.6 lamp table; multi-frame
# DM1 (>8 bytes) is asserted on the reassembled-and-decoded far side rather
# than via hand-derived BAM frames, which keeps the contract observable
# without leaking the J1939-21 wire layout.
def test_dm1_send_lamp_mix_scripted(feeder):
    """A non-trivial lamp dictionary (pl=ON, awl=ON_SLOW_FLASH, rsl=NA,
    mil=ON_FAST_FLASH) packs to byte 0 = 0x75 and byte 1 = 0x73 per the §2.6
    DtcLamp table; one trailing DTC keeps the frame to 6 bytes (single-frame,
    priority 6, broadcast PGN DM01 = 0xFECA, source 0xB7 -> CAN-ID 0x18FECAB7).

    Derivation against the §2.6 table (lamp_bits, flash_bits):
        pl  idx=0 ON              -> (1, 3): data[0] |= 1<<0 = 0x01,
                                              data[1] |= 3<<0 = 0x03
        awl idx=1 ON_SLOW_FLASH   -> (1, 0): data[0] |= 1<<2 = 0x04,
                                              data[1] |= 0<<2 = 0x00
        rsl idx=2 NA              -> (3, 3): data[0] |= 3<<4 = 0x30,
                                              data[1] |= 3<<4 = 0x30
        mil idx=3 ON_FAST_FLASH   -> (1, 1): data[0] |= 1<<6 = 0x40,
                                              data[1] |= 1<<6 = 0x40
        => data[0] = 0x01|0x04|0x30|0x40 = 0x75
           data[1] = 0x03|0x00|0x30|0x40 = 0x73
    DTC spn=4567, fmi=12, oc=1 (already derived in the single-DTC send test)
    packs to 0x010C11D7 -> little-endian bytes [0xD7, 0x11, 0x0C, 0x01]."""
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x18FECAB7,
         [0x75, 0x73, 0xD7, 0x11, 0x0C, 0x01], 0.0),
    ]
    ca = feeder.accept_all_messages(device_address_preferred=0xB7,
                                    bypass_address_claim=True)
    dm1 = j1939.Dm1(ca)

    lamp_status = {
        'pl':  j1939.DtcLamp.ON,
        'awl': j1939.DtcLamp.ON_SLOW_FLASH,
        'rsl': j1939.DtcLamp.NA,
        'mil': j1939.DtcLamp.ON_FAST_FLASH,
    }
    dtcs = [{'spn': 4567, 'fmi': 12, 'oc': 1}]

    def cb():
        return (lamp_status, dtcs)

    dm1.start_send(cb, cycletime=1)
    try:
        feeder.drive(timeout=3.0)
    finally:
        dm1.stop_send(cb)


def test_dm1_ten_dtcs_bam_roundtrip():
    """Ten DTCs plus the 2-byte lamp prefix make a 42-byte DM1 payload — six
    J1939-21 BAM TP.DT frames behind the announcement.  The receiver must
    reassemble and Dm1-decode all ten DTCs in order; assertion is on the
    full ten-element ``dtc_list`` and the lamp_status dict."""
    bus = TwoNodeBus(data_link_layer="j1939-21")
    try:
        dm1_send = j1939.Dm1(bus.ca_a)
        dm1_recv = j1939.Dm1(bus.ca_b)

        decoded = []
        dm1_recv.subscribe(
            lambda sa, lamp_status, dtc_list, timestamp:
                decoded.append((sa, lamp_status, dtc_list))
        )

        # Ten distinct DTCs; all FMI <= 9 (within 5-bit range), all OC <= 27
        # (within 7-bit range), all SPN small enough that the high-3-bit SPN
        # path stays zero — keeps the §2.6 packing formula's behavior obvious.
        sent_dtcs = [
            {'spn': 100 + 37 * i, 'fmi': i, 'oc': 3 * i}
            for i in range(10)
        ]
        # Only mil populated, set to NA to force a non-trivial lamp byte 0
        # (mil contributes 3 << 6 = 0xC0 to data[0]).
        sent_lamp_in = {'mil': j1939.DtcLamp.NA}
        expected_decoded_lamp = {
            'pl':  j1939.DtcLamp.OFF,
            'awl': j1939.DtcLamp.OFF,
            'rsl': j1939.DtcLamp.OFF,
            'mil': j1939.DtcLamp.NA,
        }

        def cb():
            return (sent_lamp_in, sent_dtcs)

        dm1_send.start_send(cb, cycletime=1)
        try:
            deadline = time.time() + 5.0
            while time.time() < deadline and len(decoded) < 1:
                time.sleep(0.02)
        finally:
            dm1_send.stop_send(cb)

        bus.deliver()

        assert len(decoded) >= 1, "no DM1 surfaced on receiver within 5 s"
        sa, lamp_status, dtc_list = decoded[0]
        assert sa == bus.sa_a, "decoded sa=0x%02X expected 0x%02X" % (sa, bus.sa_a)
        assert lamp_status == expected_decoded_lamp, (
            "decoded lamp_status %r != expected %r"
            % (lamp_status, expected_decoded_lamp)
        )
        assert dtc_list == sent_dtcs, (
            "decoded DTCs %r != sent %r" % (dtc_list, sent_dtcs)
        )
    finally:
        bus.stop()
