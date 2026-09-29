"""Mock CAN feeder used to drive a j1939 stack in tests without real hardware.

The feeder replaces ``ElectronicControlUnit.send_message`` with a checker that
validates every frame the stack transmits against a scripted expectation list
(``can_messages``) and injects scripted received frames back into the stack in
strict request/response order.  Mismatches are recorded (not asserted in the
background thread) so that tests fail fast and cleanly instead of hanging.

Message script entries are tuples ``(MsgType, can_id, data, timestamp)``:
  * ``MsgType.CANTX`` -- a frame the stack is expected to transmit.
  * ``MsgType.CANRX`` -- a frame to be injected into the stack.
Expected received application PDUs are tuples ``(MsgType.PDU, pgn, data)``.
"""

import queue
import threading
import time

import j1939

# FrameFormat.FEFF code (flexible-data-rate extended frame format). Passed as the
# `frame_format` argument to send_pgn; only relevant for the J1939-22 layer.
# Using the integer value avoids depending on an internal module path.
FEFF = 3
FBFF = 2


class AcceptAllCA(j1939.ControllerApplication):
    """ControllerApplication that accepts every destination address."""

    def __init__(self, name, device_address_preferred=None, bypass_address_claim=False):
        j1939.ControllerApplication.__init__(
            self, name, device_address_preferred, bypass_address_claim
        )

    def message_acceptable(self, dest_address):
        return True


class Feeder:
    class MsgType(object):
        CANRX = 0
        CANTX = 1
        PDU = 2

    def __init__(self, data_link_layer="j1939-21", max_cmdt_packets=1, **kwargs):
        self.STOP_THREAD = object()
        self.error = None
        self.can_messages = []
        self.pdus = []

        self.message_queue = queue.Queue()
        self.message_thread = threading.Thread(
            target=self._async_can_feeder, daemon=True
        )
        self.message_thread.start()
        # redirect send_message from the (non-existent) CAN bus to our checker
        self.ecu = j1939.ElectronicControlUnit(
            data_link_layer=data_link_layer,
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send_message,
            **kwargs
        )

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _fail(self, msg):
        if self.error is None:
            self.error = msg

    def _async_can_feeder(self):
        """Background thread: deliver injected RX frames into the stack."""
        while True:
            message = self.message_queue.get(block=True)
            if message is self.STOP_THREAD:
                break
            recv_time = message[3] if (len(message) > 3 and message[3]) else time.time()
            try:
                self.ecu.notify(message[1], bytearray(message[2]), recv_time)
            except Exception as e:  # pragma: no cover - defensive
                self._fail("ecu.notify raised: %r" % (e,))

    def _inject_messages_into_ecu(self):
        while self.can_messages and self.can_messages[0][0] == Feeder.MsgType.CANRX:
            message = self.can_messages.pop(0)
            self.message_queue.put(message)

    def _send_message(self, can_id, extended_id, data, fd_format=False):
        """Validate a transmitted frame and trigger the next injected frame(s)."""
        if self.error is not None:
            return
        if not self.can_messages:
            self._fail(
                "unexpected TX can_id=%08X data=%s" % (can_id, list(data))
            )
            return
        expected = self.can_messages.pop(0)
        if expected[0] != Feeder.MsgType.CANTX:
            self._fail(
                "expected to inject an RX frame, but the stack transmitted "
                "can_id=%08X data=%s" % (can_id, list(data))
            )
            return
        if can_id != expected[1] or list(data) != list(expected[2]):
            self._fail(
                "TX mismatch:\n  got      can_id=%08X data=%s\n  expected can_id=%08X data=%s"
                % (can_id, list(data), expected[1], list(expected[2]))
            )
            return
        self._inject_messages_into_ecu()

    def _on_message(self, priority, pgn, sa, timestamp, data):
        """Capture an application PDU notified to subscribers and check it."""
        if not self.pdus:
            self._fail(
                "unexpected PDU pgn=%04X data=%s"
                % (pgn, list(data) if data is not None else None)
            )
            return
        expected = self.pdus.pop(0)
        got = list(data) if data is not None else None
        want = None if (len(expected) > 2 and expected[2] is None) else list(expected[2])
        if pgn != expected[1] or got != want:
            self._fail(
                "PDU mismatch:\n  got      pgn=%04X data=%s\n  expected pgn=%04X data=%s"
                % (pgn, got, expected[1], want)
            )

    # ------------------------------------------------------------------ #
    # helpers for tests
    # ------------------------------------------------------------------ #
    def pdus_from_messages(self):
        """Derive expected received PDUs from the CANRX entries of the script."""
        self.pdus = []
        for message in self.can_messages:
            if message[0] == Feeder.MsgType.CANRX:
                pgn = j1939.ParameterGroupNumber()
                pgn.from_message_id(j1939.MessageId(can_id=message[1]))
                self.pdus.append((Feeder.MsgType.PDU, pgn.value & 0xFF00, message[2]))

    def accept_all_messages(self, device_address_preferred=None, bypass_address_claim=False):
        ca = AcceptAllCA(None, device_address_preferred, bypass_address_claim)
        self.ecu.add_ca(controller_application=ca)
        return ca

    def subscribe(self):
        self.ecu.subscribe(self._on_message)

    def _wait(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.error is not None:
                break
            if not self.can_messages and not self.pdus:
                break
            time.sleep(0.02)
        # allow a final processing slice
        time.sleep(0.05)

    def check(self):
        leftover = ""
        if self.can_messages:
            leftover += " | %d unconsumed scripted frame(s), next=%r" % (
                len(self.can_messages),
                self.can_messages[0],
            )
        if self.pdus:
            leftover += " | %d unconsumed expected PDU(s)" % len(self.pdus)
        assert (
            self.error is None and not self.can_messages and not self.pdus
        ), (self.error or "scenario did not complete") + leftover

    def drive(self, timeout=5.0):
        """Inject leading RX frames, wait for the scenario to drain, then check."""
        self._inject_messages_into_ecu()
        self._wait(timeout)
        self.check()

    def send(self, pdu, source, destination, timeout=5.0):
        """Transmit an application PDU ``(MsgType.PDU, pgn, data)`` from
        ``source`` to ``destination`` and wait for the resulting frame exchange
        to drain.  The caller asserts completion via :meth:`check`."""
        self.ecu.send_pgn(0, pdu[1] >> 8, destination, 6, source, list(pdu[2]))
        self._wait(timeout)

    def wait_for_state(self, ca, expected_state, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline and ca.state != expected_state:
            if self.error is not None:
                break
            time.sleep(0.02)

    def stop(self):
        try:
            self.ecu.stop()
        except Exception:
            pass
        self.message_queue.put(self.STOP_THREAD)
        self.message_thread.join(timeout=2.0)


class TwoNodeBus:
    """Two ECUs wired together over an in-memory CAN segment.

    Every frame ECU ``A`` transmits is delivered (asynchronously, via a feeder
    thread) to ECU ``B`` and vice-versa, so the full originator+responder sides
    of a protocol exchange run against each other.  This drives the transport
    protocol (BAM / RTS-CTS, classical or CAN-FD) end-to-end without scripting
    individual frames: a test sends an application PDU on one node and asserts
    the reassembled PDU surfaces on the other.

    Both nodes host an "accept all" ControllerApplication at a fixed address so
    peer-to-peer frames are accepted.
    """

    def __init__(
        self,
        data_link_layer="j1939-21",
        max_cmdt_packets=1,
        sa_a=0x90,
        sa_b=0x9B,
        **kwargs
    ):
        self.error = None
        self.sa_a = sa_a
        self.sa_b = sa_b
        self.received_a = []
        self.received_b = []
        self._stop = object()
        self._last_activity = time.time()

        self.ecu_a = j1939.ElectronicControlUnit(
            data_link_layer=data_link_layer,
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send_a,
            **kwargs
        )
        self.ecu_b = j1939.ElectronicControlUnit(
            data_link_layer=data_link_layer,
            max_cmdt_packets=max_cmdt_packets,
            send_message=self._send_b,
            **kwargs
        )
        self.ca_a = AcceptAllCA(None, sa_a, True)
        self.ecu_a.add_ca(controller_application=self.ca_a)
        self.ca_b = AcceptAllCA(None, sa_b, True)
        self.ecu_b.add_ca(controller_application=self.ca_b)
        self.ecu_a.subscribe(self._on_a)
        self.ecu_b.subscribe(self._on_b)

        self._q_a = queue.Queue()  # frames destined for A
        self._q_b = queue.Queue()  # frames destined for B
        self._t_a = threading.Thread(
            target=self._drain, args=(self._q_a, self.ecu_a), daemon=True
        )
        self._t_b = threading.Thread(
            target=self._drain, args=(self._q_b, self.ecu_b), daemon=True
        )
        self._t_a.start()
        self._t_b.start()

    def _send_a(self, can_id, extended_id, data, fd_format=False):
        # A transmitted -> deliver to B
        self._last_activity = time.time()
        self._q_b.put((can_id, bytearray(data), time.time()))

    def _send_b(self, can_id, extended_id, data, fd_format=False):
        # B transmitted -> deliver to A
        self._last_activity = time.time()
        self._q_a.put((can_id, bytearray(data), time.time()))

    def _drain(self, q, ecu):
        while True:
            item = q.get()
            if item is self._stop:
                break
            self._last_activity = time.time()
            try:
                ecu.notify(item[0], item[1], item[2])
            except Exception as e:  # pragma: no cover - defensive
                if self.error is None:
                    self.error = "ecu.notify raised: %r" % (e,)

    def _on_a(self, priority, pgn, sa, timestamp, data):
        self.received_a.append((pgn, list(data) if data is not None else None))

    def _on_b(self, priority, pgn, sa, timestamp, data):
        self.received_b.append((pgn, list(data) if data is not None else None))

    def a_send(self, pdu_format, pdu_specific, data, priority=6, frame_format=FEFF):
        self.ecu_a.send_pgn(
            0, pdu_format, pdu_specific, priority, self.sa_a, list(data), 0, frame_format
        )

    def b_send(self, pdu_format, pdu_specific, data, priority=6, frame_format=FEFF):
        self.ecu_b.send_pgn(
            0, pdu_format, pdu_specific, priority, self.sa_b, list(data), 0, frame_format
        )

    def deliver(self, timeout=8.0, quiet=0.3):
        """Wait until the segment has been idle for ``quiet`` seconds."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.error is not None:
                break
            if (
                self._q_a.empty()
                and self._q_b.empty()
                and (time.time() - self._last_activity) > quiet
            ):
                break
            time.sleep(0.02)
        assert self.error is None, self.error

    def stop(self):
        for ecu in (self.ecu_a, self.ecu_b):
            try:
                ecu.stop()
            except Exception:
                pass
        self._q_a.put(self._stop)
        self._q_b.put(self._stop)
        self._t_a.join(timeout=2.0)
        self._t_b.join(timeout=2.0)
