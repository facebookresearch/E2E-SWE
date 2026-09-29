"""Harder J1939 diagnostic scenarios complementing ``test_j1939_diag.py``.

Two tests, all derived strictly from instruction.md §1.4 (J1939-21 transport
protocol) and §2.6 (DTC packing formula, DtcLamp encoding table, Dm1 send +
receive contract, ``dtc_list`` element shape):

1. ``test_dm1_send_four_dtcs_bam_above_threshold`` — a 4-DTC DM1 (18-byte
   payload) is ABOVE the 8-byte threshold and must run §1.4 BAM at priority
   7 with num_packets = ceil(18/7) = 3, byte-asserting TP.CM + all TP.DT
   segments (the direct-vs-BAM threshold itself is already covered by the
   single-frame ``test_dm1_send_single_dtc`` in ``test_j1939_diag.py``).
2. ``test_dm1_lamp_combinations_and_three_dtc_decode`` — a scripted BAM
   sequence (TP.CM + 2 TP.DT) carrying a non-default lamp combination (all
   four lamps at distinct §2.6 statuses) + 3 DTCs is fed to the receiver;
   the Dm1 subscriber must decode both the lamp dict and the three-element
   ``dtc_list`` exactly.  Stresses lamp-combination decoding and multi-DTC
   reassembly in one scenario.
"""

import j1939
from feeder import Feeder


# --------------------------------------------------------------------------- #
# 1. DM1 above-threshold BAM (byte-exact send test).
# --------------------------------------------------------------------------- #
# A 4-DTC DM1 payload is 2 lamp bytes + 4 * 4-byte DTC = 18 bytes > 8, which
# crosses the single-frame threshold and rides §1.4 BAM at priority 7.  The
# below-threshold single-frame case (a 1-DTC, 6-byte DM1 at priority 6) is
# already covered by ``test_dm1_send_single_dtc`` in ``test_j1939_diag.py``.
def test_dm1_send_four_dtcs_bam_above_threshold(feeder):
    """4-DTC DM1 (18-byte payload = 2 lamp bytes + 4 * 4-byte DTC) is ABOVE
    the 8-byte threshold, so Dm1 must run §1.4 BAM at priority 7 with
    num_packets = ceil(18/7) = 3.  Asserts byte-exact BAM TP.CM + all three
    TP.DT segments.

    Derivation:
      lamp {mil: ON, others OFF} -> data[0]=0x40, data[1]=0xFF
      DTCs:
        (100,    5,  2) -> 0x02050064 -> [0x64, 0x00, 0x05, 0x02]
        (200,    7,  3) -> 0x030700C8 -> [0xC8, 0x00, 0x07, 0x03]
        (4567,   12, 1) -> 0x010C11D7 -> [0xD7, 0x11, 0x0C, 0x01]
        (520192, 14, 15) -> 0x0FEEF000 -> [0x00, 0xF0, 0xEE, 0x0F]
      Payload (18 bytes):
        [0x40, 0xFF,
         0x64, 0x00, 0x05, 0x02,
         0xC8, 0x00, 0x07, 0x03,
         0xD7, 0x11, 0x0C, 0x01,
         0x00, 0xF0, 0xEE, 0x0F]
      BAM TP.CM (priority 7, PGN 0xECFF, SA 0xA5):
        CAN-ID = (7<<26)|(0xECFF<<8)|0xA5 = 0x1CECFFA5
        data   = [32, 18, 0, 3, 0xFF, 0xCA, 0xFE, 0x00]  (DM01 = 0xFECA)
      TP.DT (priority 7, PGN 0xEBFF, SA 0xA5, CAN-ID 0x1CEBFFA5):
        seq 1 (bytes  0.. 6): [1, 0x40, 0xFF, 0x64, 0x00, 0x05, 0x02, 0xC8]
        seq 2 (bytes  7..13): [2, 0x00, 0x07, 0x03, 0xD7, 0x11, 0x0C, 0x01]
        seq 3 (bytes 14..17 + 3 x 0xFF pad):
                              [3, 0x00, 0xF0, 0xEE, 0x0F, 0xFF, 0xFF, 0xFF]
    """
    feeder.can_messages = [
        (Feeder.MsgType.CANTX, 0x1CECFFA5,
         [32, 18, 0, 3, 0xFF, 0xCA, 0xFE, 0x00], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEBFFA5,
         [1, 0x40, 0xFF, 0x64, 0x00, 0x05, 0x02, 0xC8], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEBFFA5,
         [2, 0x00, 0x07, 0x03, 0xD7, 0x11, 0x0C, 0x01], 0.0),
        (Feeder.MsgType.CANTX, 0x1CEBFFA5,
         [3, 0x00, 0xF0, 0xEE, 0x0F, 0xFF, 0xFF, 0xFF], 0.0),
    ]
    ca = feeder.accept_all_messages(device_address_preferred=0xA5,
                                    bypass_address_claim=True)
    dm1 = j1939.Dm1(ca)

    lamp_status = {'mil': j1939.DtcLamp.ON}
    four_dtcs = [
        {'spn': 100,    'fmi': 5,  'oc': 2},
        {'spn': 200,    'fmi': 7,  'oc': 3},
        {'spn': 4567,   'fmi': 12, 'oc': 1},
        {'spn': 520192, 'fmi': 14, 'oc': 15},
    ]

    def cb():
        return (lamp_status, four_dtcs)

    dm1.start_send(cb, cycletime=1)
    try:
        feeder.drive(timeout=4.0)
    finally:
        dm1.stop_send(cb)


# --------------------------------------------------------------------------- #
# 2. DM1 receive — lamp combinations + 3-DTC decode via scripted BAM.
# --------------------------------------------------------------------------- #
# Inject a complete §1.4 BAM exchange (TP.CM + 2 TP.DT) from a synthetic
# sender at sa=0x42 carrying a 14-byte DM1 payload: 2 lamp bytes encoding
# every-lamp-at-a-distinct-non-default-status, plus 3 DTCs spanning small
# SPN through the 19-bit high-SPN path.  The Dm1 subscriber must decode
# the full lamp dict AND the three-element ``dtc_list`` (each entry a
# ``{'spn','fmi','oc'}`` dict per §2.6) exactly.
#
# Lamp dict {pl: ON, awl: ON_SLOW_FLASH, rsl: NA, mil: ON_FAST_FLASH} per
# §2.6 (lamp_bits, flash_bits):
#   pl  idx=0 ON            -> (1, 3): data[0] |= 0x01, data[1] |= 0x03
#   awl idx=1 ON_SLOW_FLASH -> (1, 0): data[0] |= 0x04, data[1] |= 0x00
#   rsl idx=2 NA            -> (3, 3): data[0] |= 0x30, data[1] |= 0x30
#   mil idx=3 ON_FAST_FLASH -> (1, 1): data[0] |= 0x40, data[1] |= 0x40
# =>  data[0] = 0x01 | 0x04 | 0x30 | 0x40 = 0x75
#     data[1] = 0x03 | 0x00 | 0x30 | 0x40 = 0x73
#
# DTCs (all derivable from the §2.6 packing formula):
#   (spn=100,    fmi=5,  oc=2)   -> 0x02050064 -> [0x64, 0x00, 0x05, 0x02]
#   (spn=4567,   fmi=12, oc=1)   -> 0x010C11D7 -> [0xD7, 0x11, 0x0C, 0x01]
#   (spn=520192, fmi=14, oc=15)  -> 0x0FEEF000 -> [0x00, 0xF0, 0xEE, 0x0F]
#                                  (exercises the (spn & 0x70000) << 5 path)
#
# Application payload (14 bytes): [0x75, 0x73, 0x64, 0x00, 0x05, 0x02,
#                                  0xD7, 0x11, 0x0C, 0x01, 0x00, 0xF0,
#                                  0xEE, 0x0F]
#
# §1.4 BAM TP.CM (PGN 0xEC + PS=GLOBAL=0xFF, control byte 32):
#   data = [32, total_size=14, total_size_hi=0, num_packets=2, 0xFF,
#           DM01_lo=0xCA, DM01_mid=0xFE, DM01_hi=0x00]
#   CAN-ID at SA 0x42 -> (7<<26)|(0xECFF<<8)|0x42 = 0x1CECFF42
#
# §1.4 BAM TP.DT (PGN 0xEB + PS=GLOBAL=0xFF, priority 7):
#   CAN-ID at SA 0x42 -> (7<<26)|(0xEBFF<<8)|0x42 = 0x1CEBFF42
#   seq=1 carries payload bytes 0..6 (exactly 7 bytes, no pad):
#         [1, 0x75, 0x73, 0x64, 0x00, 0x05, 0x02, 0xD7]
#   seq=2 carries payload bytes 7..13 (exactly 7 bytes, no pad):
#         [2, 0x11, 0x0C, 0x01, 0x00, 0xF0, 0xEE, 0x0F]
def test_dm1_lamp_combinations_and_three_dtc_decode(feeder):
    """A scripted BAM exchange from sa=0x42 carrying a 14-byte DM1 with
    every lamp at a distinct non-default §2.6 status plus 3 DTCs (one
    exercising the 19-bit SPN high-bit path) is reassembled and decoded by
    the Dm1 subscriber; the callback receives the exact lamp dict and the
    three ``{'spn','fmi','oc'}`` dicts in order."""
    received = []

    def cb(sa, lamp_status, dtc_list, timestamp):
        received.append((sa, lamp_status, dtc_list))

    ca = feeder.accept_all_messages(device_address_preferred=0x90,
                                    bypass_address_claim=True)
    dm1 = j1939.Dm1(ca)
    dm1.subscribe(cb)

    feeder.can_messages = [
        (Feeder.MsgType.CANRX, 0x1CECFF42,
         [32, 14, 0, 2, 0xFF, 0xCA, 0xFE, 0x00], 0.0),
        (Feeder.MsgType.CANRX, 0x1CEBFF42,
         [1, 0x75, 0x73, 0x64, 0x00, 0x05, 0x02, 0xD7], 0.0),
        (Feeder.MsgType.CANRX, 0x1CEBFF42,
         [2, 0x11, 0x0C, 0x01, 0x00, 0xF0, 0xEE, 0x0F], 0.0),
    ]
    feeder.drive(timeout=3.0)

    assert len(received) == 1, "expected one DM1 callback, got %r" % (received,)
    sa, lamp_status, dtc_list = received[0]
    assert sa == 0x42
    assert lamp_status == {
        'pl':  j1939.DtcLamp.ON,
        'awl': j1939.DtcLamp.ON_SLOW_FLASH,
        'rsl': j1939.DtcLamp.NA,
        'mil': j1939.DtcLamp.ON_FAST_FLASH,
    }
    assert dtc_list == [
        {'spn': 100,    'fmi': 5,  'oc': 2},
        {'spn': 4567,   'fmi': 12, 'oc': 1},
        {'spn': 520192, 'fmi': 14, 'oc': 15},
    ]
