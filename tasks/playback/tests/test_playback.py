"""Offline record/replay tests for the `playback` library.

Every test follows the same offline cycle:
  1. Build a TapeRecorder over an InMemoryTapeCassette and enable recording.
  2. Decorate an operation (plus inputs/outputs) and RECORD a real call.
  3. PLAY BACK the operation against the recording and assert the recorded
     interceptions replay correctly (matching keys, invocation order preserved,
     return values served, exceptions re-raised).

No network/S3 is used; the in-memory cassette is the only storage backend.
"""
from __future__ import absolute_import

import pytest

from playback.tape_recorder import (
    TapeRecorder,
    CapturedArg,
    RecordingParameters,
    Playback,
    Output,
)
from playback.tape_cassettes.in_memory.in_memory_tape_cassette import InMemoryTapeCassette
from playback.exceptions import (
    TapeRecorderException,
    RecordingKeyError,
    InputInterceptionKeyCreationError,
    OperationExceptionDuringPlayback,
    NoSuchRecording,
)


def make_recorder():
    cassette = InMemoryTapeCassette()
    recorder = TapeRecorder(cassette, random_seed=110613)
    recorder.enable_recording()
    return cassette, recorder


def operation_output(playback_result):
    """Return the captured operation-output Output (the operation's return value)."""
    return next(po for po in playback_result.playback_outputs
                if TapeRecorder.OPERATION_OUTPUT_ALIAS in po.key)


# --------------------------------------------------------------------------
# Basic record / replay round trip
# --------------------------------------------------------------------------

def test_basic_operation_round_trip():
    """The basic operation record/replay round trip: an operation's return value is
    captured as an operation output (a {'args': [value], 'kwargs': {}} Output
    namedtuple), play() returns a Playback with positive durations, and the
    recorded outputs equal the playback outputs.

    (Bundled from the near-identical basic round-trip / durations / outputs-match /
    namedtuple-shape variants so the band depends on the genuine record/replay
    engine rather than on repeated easy credit for the same operation-output shape.)
    """
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return 5

    assert Operation().execute() == 5

    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())

    # Playback object + positive durations.
    assert isinstance(result, Playback)
    assert result.playback_duration > 0
    assert result.recorded_duration > 0

    # Operation output surfaced with the canonical {'args': [value], 'kwargs': {}} shape.
    out = operation_output(result)
    assert out.value['args'][0] == 5
    assert out.value == {'args': [5], 'kwargs': {}}

    # Output entries are namedtuples exposing .key / .value.
    assert out == Output(out.key, out.value)

    # Recorded outputs and playback outputs contain the same Output entries.
    assert sorted(result.recorded_outputs) == sorted(result.playback_outputs)


def test_decorators_transparent_when_recording_disabled():
    """With recording disabled the operation decorator is a pass-through and stores nothing."""
    cassette, recorder = make_recorder()
    recorder.disable_recording()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return 7

    assert Operation().execute() == 7
    assert cassette.get_last_recording_id() is None


def test_class_operation_round_trip():
    """class_operation is the classmethod entry-point analogue of operation: the
    operation's class (the bound `cls`, not type(args[0])) is the recording category,
    and the classmethod's return value records/replays as the operation output.
    """
    cassette, recorder = make_recorder()

    class Op(object):
        @classmethod
        @recorder.class_operation()
        def execute(cls):
            return 5

    assert Op.execute() == 5
    rec_id = cassette.get_last_recording_id()
    # Category is the class name (resolved from the bound cls, not an instance type).
    assert cassette.extract_recording_category(rec_id) == 'Op'

    result = recorder.play(rec_id, playback_function=lambda recording: Op.execute())
    assert isinstance(result, Playback)
    assert operation_output(result).value['args'][0] == 5


# --------------------------------------------------------------------------
# Input interception: recording then replay serves recorded value
# --------------------------------------------------------------------------

def test_input_interception_basic_replay():
    """The basic input-interception contract: on playback the intercepted method is
    not executed and the recorded value is served, calls with different arguments
    are recorded/replayed under distinct keys, and kwargs supplied in a different
    order map to the same key.

    (Bundled from the near-identical serves-recorded-value / distinct-args /
    kwarg-order variants so the band depends on the genuine record/replay engine
    rather than on repeated easy credit for the same basic-replay behavior.)
    """
    # --- serves recorded value, different args -> distinct keys ---
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value(2, b=3) + self.get_value(4, b=6)

        @recorder.intercept_input('input')
        def get_value(self, a, b=2):
            return (a + b) * self.seed

    assert Operation(seed=1).execute() == 15
    rec_id = cassette.get_last_recording_id()
    # Replay with a different seed: recorded 5 + 10 = 15 must replay, ignoring the new seed.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(seed=99).execute())
    assert operation_output(result).value['args'][0] == 15

    # --- kwargs supplied in different order produce the same interception key ---
    cassette2, recorder2 = make_recorder()

    class Recorder(object):
        @recorder2.operation()
        def execute(self):
            return self.get_value(a=1, b=2)

        @recorder2.intercept_input('input')
        def get_value(self, a, b):
            return a + b

    class Replayer(object):
        @recorder2.operation()
        def execute(self):
            return self.get_value(b=2, a=1)

        @recorder2.intercept_input('input')
        def get_value(self, a, b):
            return -999  # must not run; recorded 3 must be served

    assert Recorder().execute() == 3
    rec_id2 = cassette2.get_last_recording_id()
    result2 = recorder2.play(rec_id2, playback_function=lambda recording: Replayer().execute())
    assert operation_output(result2).value['args'][0] == 3


def test_input_interception_static_with_arguments():
    """static_intercept_input records/replays a staticmethod input keyed by its args."""
    cassette, recorder = make_recorder()

    class Operation(object):
        seed = 0

        @recorder.operation()
        def execute(self):
            return self.get_value(2, b=3) + self.get_value(4, b=6)

        @staticmethod
        @recorder.static_intercept_input('input')
        def get_value(a, b=2):
            return (a + b) * Operation.seed

    Operation.seed = 1
    assert Operation().execute() == 15
    Operation.seed = 0
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert operation_output(result).value['args'][0] == 15


def test_static_input_first_positional_participates_in_key():
    """For a static input with capture_args=None, the FIRST positional argument is part of
    the key (no `self` stripping, unlike instance methods). Recording with one first
    positional then replaying with a different first positional finds no match.
    """
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, n):
            self.n = n

        @recorder.operation()
        def execute(self):
            return self.get_value(self.n)

        @staticmethod
        @recorder.static_intercept_input('input')
        def get_value(a):
            return a * 10

    # Record keyed on first positional == 1.
    assert Operation(1).execute() == 10
    rec_id = cassette.get_last_recording_id()
    # Replay with first positional == 2: because the first positional participates in the
    # static key, no recorded entry matches -> RecordingKeyError.
    with pytest.raises(RecordingKeyError):
        recorder.play(rec_id, playback_function=lambda recording: Operation(2).execute())


def test_input_property_interception():
    """A property decorated as an input is recorded and replayed."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value

        @recorder.intercept_input('input')
        @property
        def get_value(self):
            return self.seed

    assert Operation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == 5


def test_input_data_handler_round_trip():
    """An input data_handler transforms the value on the way INTO the recording
    (prepare_input_for_recording) and on the way OUT (restore_input_from_recording).

    The handler is deliberately asymmetric (prepare doubles, restore adds one) so the
    replayed value differs from both the raw value (no handler) and the prepare-only
    value -- proving observably that BOTH directions ran, without coupling to the
    internal storage envelope.
    """
    cassette, recorder = make_recorder()

    class Handler(object):
        def prepare_input_for_recording(self, interception_key, result, args, kwargs):
            return result * 2  # stored transformed

        def restore_input_from_recording(self, recorded_data, args, kwargs):
            return recorded_data + 1  # restored from the transformed stored value

    handler = Handler()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        @recorder.intercept_input('input', data_handler=handler)
        def get_value(self):
            return self.seed

    # During recording the real method still returns its real value (5); the handler only
    # affects what is stored.
    assert Operation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    # On playback the stored (doubled -> 10) value is restored (+1 -> 11) and served.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == 11


# --------------------------------------------------------------------------
# capture_args semantics
# --------------------------------------------------------------------------

def test_capture_args_empty_list_ignores_all_arguments():
    """capture_args=[] keys every invocation identically regardless of arguments."""
    cassette, recorder = make_recorder()
    from random import random

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return self.get_value(random(), b=random())

        @recorder.intercept_input('input', capture_args=[])
        def get_value(self, a, b=2):
            return 5

    assert Operation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    # Replay passes different random args; with no captured args the key still matches.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert operation_output(result).value['args'][0] == 5


def test_capture_args_specific_subset():
    """Only the CapturedArg-listed args/kwargs participate in the key; others are ignored."""
    cassette, recorder = make_recorder()
    from random import random

    class Operation(object):
        @recorder.operation()
        def execute(self):
            arg1 = random()   # position 1, NOT captured
            arg4 = random()   # kwarg d, NOT captured
            return self.get_value(arg1, 'b', c='c', d=arg4, e='e')

        @recorder.intercept_input('input', capture_args=[CapturedArg(2, 'b'),
                                                         CapturedArg(3, 'c'),
                                                         CapturedArg(None, 'e'),
                                                         CapturedArg(None, 'f')])
        def get_value(self, a, b, c, d=None, e=None, f=None):
            return 5

    assert Operation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    # Replay uses fresh random values for the uncaptured args; key must still match.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert operation_output(result).value['args'][0] == 5


def test_capture_args_distinguishes_captured_values():
    """Different values of a captured arg produce different keys (independent recordings)."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, x):
            self.x = x

        @recorder.operation()
        def execute(self):
            return self.get_value(self.x)

        @recorder.intercept_input('input', capture_args=[CapturedArg(1, 'a')])
        def get_value(self, a):
            return a * 10

    assert Operation(2).execute() == 20
    rec_id = cassette.get_last_recording_id()
    # Replaying with a different captured value has no recorded match -> RecordingKeyError.
    with pytest.raises(RecordingKeyError):
        recorder.play(rec_id, playback_function=lambda recording: Operation(3).execute())


# --------------------------------------------------------------------------
# fallback_aliases
# --------------------------------------------------------------------------

def test_fallback_aliases_as_function():
    """fallback_aliases may be a callable returning the list of fallback aliases."""
    cassette, recorder = make_recorder()

    class OldOperation(object):
        @recorder.operation()
        def execute(self):
            return self.input('a_param')

        @recorder.intercept_input('old_input')
        def input(self, _param):
            return 5

    class NewOperation(object):
        @recorder.operation()
        def execute(self):
            return self.input('a_param')

        @recorder.intercept_input('new_input', fallback_aliases=lambda *a, **k: ['old_input'])
        def input(self, _param):
            return -1

    assert OldOperation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: NewOperation().execute())
    assert operation_output(result).value['args'][0] == 5


# --------------------------------------------------------------------------
# Missing-key playback behaviors
# --------------------------------------------------------------------------

def test_missing_input_raises_recording_key_error():
    """Different input args during playback with no match raise RecordingKeyError."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, input_key):
            self.input_key = input_key

        @recorder.operation()
        def execute(self):
            return self.input(self.input_key)

        @recorder.intercept_input('input')
        def input(self, param):
            return 5

    Operation('key1').execute()
    rec_id = cassette.get_last_recording_id()
    with pytest.raises(RecordingKeyError) as excinfo:
        recorder.play(rec_id, playback_function=lambda recording: Operation('key2').execute())
    # RecordingKeyError derives from the TapeRecorderException base (the engine's
    # `except TapeRecorderException` handling relies on this).
    assert isinstance(excinfo.value, TapeRecorderException)


def test_run_intercepted_when_missing():
    """run_intercepted_when_missing runs the original method when no recording matches."""
    cassette, recorder = make_recorder()

    class OldOperation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        def get_value(self):  # not intercepted -> nothing recorded for this alias
            return self.seed

    class NewOperation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        @recorder.intercept_input('input', run_intercepted_when_missing=True)
        def get_value(self):
            return self.seed

    assert OldOperation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: NewOperation(5).execute())
    assert operation_output(result).value['args'][0] == 5


# --------------------------------------------------------------------------
# Output interception + invocation counter ordering
# --------------------------------------------------------------------------

def test_output_interception_records_args_kwargs_in_order():
    """Repeated output-alias calls capture {'args','kwargs'} in invocation order with distinct keys."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            x = 0
            x += self.output(4, arg='a')
            x += self.output(3, arg='b')
            return x

        @recorder.intercept_output('output_function')
        def output(self, value, arg=None):
            return value

    assert Operation().execute() == 7
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())

    assert result.playback_outputs[0].value == {'args': [4], 'kwargs': {'arg': 'a'}}
    assert result.playback_outputs[1].value == {'args': [3], 'kwargs': {'arg': 'b'}}
    assert result.playback_outputs[0].key != result.playback_outputs[1].key
    assert 'output_function' in result.playback_outputs[0].key
    assert 'output_function' in result.playback_outputs[1].key


def test_static_output_interception_records_args_kwargs():
    """static_intercept_output captures positional args and kwargs sent to the output."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return self.output(4, arg='a') + self.output(3, arg='b')

        @staticmethod
        @recorder.static_intercept_output('output_function')
        def output(value, arg=None):
            return value

    assert Operation().execute() == 7
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert result.playback_outputs[0].value == {'args': [4], 'kwargs': {'arg': 'a'}}
    assert result.playback_outputs[1].value == {'args': [3], 'kwargs': {'arg': 'b'}}
    assert result.playback_outputs[0].key != result.playback_outputs[1].key


def test_output_return_value_replayed():
    """The output method's return value is recorded and served during playback."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, factor=1):
            self.factor = factor

        @recorder.operation()
        def execute(self):
            return self.output(5)

        @recorder.intercept_output('output_function')
        def output(self, value):
            return value * self.factor

    assert Operation(factor=2).execute() == 10
    rec_id = cassette.get_last_recording_id()
    # Replay with a different factor: recorded return (10) must be served.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(factor=99).execute())
    assert operation_output(result).value['args'][0] == 10


def test_output_invocation_counter_resets_between_operations():
    """The per-alias invocation counter resets between separate operations."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return self.output(1) + self.output(2)

        @recorder.intercept_output('out')
        def output(self, value):
            return value

    Operation().execute()
    first_id = cassette.get_last_recording_id()
    Operation().execute()
    second_id = cassette.get_last_recording_id()
    assert first_id != second_id

    r1 = recorder.play(first_id, playback_function=lambda recording: Operation().execute())
    r2 = recorder.play(second_id, playback_function=lambda recording: Operation().execute())
    # Both recordings independently captured two ordered outputs.
    out_keys_1 = [o.key for o in r1.playback_outputs if 'out' in o.key and TapeRecorder.OPERATION_OUTPUT_ALIAS not in o.key]
    out_keys_2 = [o.key for o in r2.playback_outputs if 'out' in o.key and TapeRecorder.OPERATION_OUTPUT_ALIAS not in o.key]
    assert len(out_keys_1) == 2
    assert len(out_keys_2) == 2
    assert len(set(out_keys_1)) == 2


def test_output_missing_result_raises_when_fail_on_no_recorded_result():
    """An output present at replay but absent in the recording raises RecordingKeyError by default."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, output_method):
            self.output_method = output_method

        @recorder.operation()
        def execute(self):
            return getattr(self, self.output_method)()

        @recorder.intercept_output('output_function')
        def output(self):
            return 5

        @recorder.intercept_output('output_missing')
        def output_missing(self):
            return 5

    Operation('output').execute()
    rec_id = cassette.get_last_recording_id()
    with pytest.raises(RecordingKeyError):
        recorder.play(rec_id, playback_function=lambda recording: Operation('output_missing').execute())


def test_new_output_added_post_recording_default_value():
    """A new output added after recording replays with default_result_when_not_recorded."""
    cassette, recorder = make_recorder()

    class OperationOld(object):
        @recorder.operation()
        def execute(self):
            return self.output(5)

        @recorder.intercept_output('output_function')
        def output(self, value):
            return value

    class OperationNew(object):
        @recorder.operation()
        def execute(self):
            value = self.output(5)
            val1, val2 = self.output_new(value)
            return val1 + val2

        @recorder.intercept_output('output_function')
        def output(self, value):
            return value

        @recorder.intercept_output('output_new_function', fail_on_no_recorded_result=False,
                                   default_result_when_not_recorded=(2, 4))
        def output_new(self, value):
            return value, value * 2

    assert OperationOld().execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: OperationNew().execute())
    # The new output returns its default (2, 4) -> 6 becomes the operation result.
    assert operation_output(result).value['args'][0] == 6
    # Both outputs are still captured distinctly on replay, in invocation order, with
    # distinct keys (folded from the former captures-both-outputs test, same node).
    assert 'output_function' in result.playback_outputs[0].key
    assert 'output_new_function' in result.playback_outputs[1].key
    assert result.playback_outputs[0].value == {'args': [5], 'kwargs': {}}
    assert result.playback_outputs[1].value == {'args': [5], 'kwargs': {}}
    assert result.playback_outputs[0].key != result.playback_outputs[1].key


# --------------------------------------------------------------------------
# Exception capture / replay
# --------------------------------------------------------------------------

def test_operation_exception_recorded_and_reraised_on_record():
    """An operation raising during recording re-raises and records the exception as its output."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            raise ValueError("Error")

    with pytest.raises(ValueError):
        Operation().execute()

    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    captured = operation_output(result).value['args'][0]
    assert isinstance(captured, ValueError)
    assert str(captured) == "Error"
    # A normal Exception is captured AS the operation output, so the recording is NOT
    # incomplete (this is the discriminator from the BaseException path, which IS).
    assert result.original_recording.get_metadata()[TapeRecorder.INCOMPLETE_RECORDING] is False


def test_operation_exception_does_not_propagate_out_of_play():
    """play() returns normally even though the recorded operation raised."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            raise ValueError("boom")

    with pytest.raises(ValueError):
        Operation().execute()

    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert isinstance(result, Playback)
    assert result.original_recording.get_metadata()[TapeRecorder.EXCEPTION_IN_OPERATION] is True


def test_input_exception_captured_and_reraised_on_playback():
    """An input that raised during recording re-raises the same exception type on playback."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            try:
                self.get_value()
            except Exception as ex:
                return str(ex)

        @recorder.intercept_input('input')
        def get_value(self):
            raise Exception(self.seed)

    assert Operation(5).execute() == '5'
    rec_id = cassette.get_last_recording_id()
    # On replay get_value is not run; the recorded exception is re-raised and caught.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == '5'


def test_output_exception_captured_and_reraised_on_playback():
    """An output that raised during recording re-raises on playback."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            try:
                self.output()
            except Exception as ex:
                return str(ex)

        @recorder.intercept_output('output_function')
        def output(self):
            raise Exception(self.seed)

    assert Operation(5).execute() == '5'
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == '5'


# --------------------------------------------------------------------------
# Key-creation failure
# --------------------------------------------------------------------------

def test_input_key_creation_failure_discards_recording():
    """An unserializable arg during recording discards the recording but still returns the real value."""
    cassette, recorder = make_recorder()

    class UnencodeableObject(object):
        def __getstate__(self):
            raise Exception()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return self.input(UnencodeableObject())

        @recorder.intercept_input('input')
        def input(self, param):
            return 5

    assert Operation().execute() == 5
    # Recording was discarded -> nothing saved.
    assert cassette.get_last_recording_id() is None


def test_input_key_creation_failure_during_playback_raises():
    """A key-creation failure during playback raises InputInterceptionKeyCreationError."""
    cassette, recorder = make_recorder()

    class UnencodeableObject(object):
        def __getstate__(self):
            raise Exception()

    class Operation(object):
        def __init__(self, raise_on_get=False):
            self.raise_on_get = raise_on_get

        @recorder.operation()
        def execute(self):
            param = UnencodeableObject() if self.raise_on_get else object()
            return self.input(param)

        @recorder.intercept_input('input')
        def input(self, param):
            return 5

    assert Operation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    with pytest.raises(InputInterceptionKeyCreationError):
        recorder.play(rec_id, playback_function=lambda recording: Operation(True).execute())


# --------------------------------------------------------------------------
# Persistence round-trip / cassette behavior
# --------------------------------------------------------------------------

def test_recording_round_trips_through_cassette_serialization():
    """A recorded interception survives the cassette encode->store->load->decode cycle.

    Asserted at the observable contract: the recorded input value persists across the
    deserialized recording and is served back during playback (instead of running the
    real method, which would now return a different value). This does not couple to the
    internal storage envelope -- only to the spec's round-trip/replay guarantee.
    """
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        @recorder.intercept_input('input')
        def get_value(self):
            return self.seed

    assert Operation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    # The recording survives a fresh deserialization (the cassette decodes on every fetch).
    recording = cassette.get_recording(rec_id)
    assert recording is not None
    assert list(recording.get_all_keys())  # the recorded input key persisted
    # Replay against the freshly deserialized recording with a different seed: the real
    # method would return 0, but the recorded value (5) is served instead.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == 5


def test_recording_get_data_contract():
    """Recording.get_data has two facets of the same method: it raises RecordingKeyError
    for an unknown key, and it returns a fresh deep copy each call so callers cannot
    mutate the stored data (MERGE C: both are contracts of the single get_data node).

    The fresh-copy facet is asserted via record_data, whose key the test controls, so the
    assertion does not couple to the internal input-storage envelope shape.
    """
    cassette, recorder = make_recorder()
    rec = recorder

    class Operation(object):
        @recorder.operation()
        def execute(self):
            rec.record_data('payload', {'counter': 0})
            return 1

    Operation().execute()
    rec_id = cassette.get_last_recording_id()
    recording = cassette.get_recording(rec_id)

    # Facet 1: missing key raises.
    with pytest.raises(RecordingKeyError):
        recording.get_data('no-such-key')

    # Facet 2: each get_data is an independent deep copy; mutating one does not leak.
    first = recording.get_data('payload')
    assert first == {'counter': 0}
    first['counter'] = 999
    second = recording.get_data('payload')
    assert second == {'counter': 0}


def test_cassette_unknown_recording_returns_none():
    """InMemoryTapeCassette.get_recording returns None for an unknown id."""
    cassette, recorder = make_recorder()
    assert cassette.get_recording('nope/123') is None


def test_cassette_category_from_recording_id():
    """The recording id encodes the operation class name as its category prefix."""
    cassette, recorder = make_recorder()

    class MyOperation(object):
        @recorder.operation()
        def execute(self):
            return 1

    MyOperation().execute()
    rec_id = cassette.get_last_recording_id()
    assert rec_id.split('/')[0] == 'MyOperation'
    assert cassette.extract_recording_category(rec_id) == 'MyOperation'


def test_get_all_recording_ids_sorted():
    """get_all_recording_ids returns all saved ids in sorted order."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return 1

    Operation().execute()
    Operation().execute()
    ids = cassette.get_all_recording_ids()
    assert len(ids) == 2
    assert ids == sorted(ids)


# --------------------------------------------------------------------------
# record_data / play_data
# --------------------------------------------------------------------------

def test_record_data_and_play_data_round_trip():
    """record_data stores arbitrary data that play_data returns during playback."""
    cassette, recorder = make_recorder()
    rec = recorder

    class Operation(object):
        @recorder.operation()
        def execute(self):
            data = rec.play_data('data')
            if rec.in_playback_mode:
                return data
            rec.record_data('data', 5)
            return 5

    assert Operation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert operation_output(result).value['args'][0] == 5


def test_play_data_missing_key_raises_recording_key_error():
    """play_data raises RecordingKeyError for a key that was never recorded, during playback.

    (Outside playback play_data returns None; this test exercises the in-playback
    missing-key branch, distinct from the happy round trip.)
    """
    cassette, recorder = make_recorder()
    rec = recorder

    class Operation(object):
        @recorder.operation()
        def execute(self):
            # In recording mode play_data returns None (not in playback) so this is safe;
            # in playback mode the key 'absent' was never recorded -> RecordingKeyError.
            value = rec.play_data('absent')
            return value if rec.in_playback_mode else 5

    assert Operation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    with pytest.raises(RecordingKeyError):
        recorder.play(rec_id, playback_function=lambda recording: Operation().execute())


def test_record_data_noop_when_recording_disabled():
    """record_data is a silent no-op when not in recording mode (nothing is stored)."""
    cassette, recorder = make_recorder()
    recorder.disable_recording()

    # No active recording and recording disabled: record_data must neither raise nor store.
    recorder.record_data('data', 5)
    assert cassette.get_last_recording_id() is None


# --------------------------------------------------------------------------
# Sampling / recording params
# --------------------------------------------------------------------------

def test_skipped_recording_params_skip_recording():
    """recording_params(skipped=True) makes the operation record nothing."""
    cassette, recorder = make_recorder()

    @recorder.recording_params(RecordingParameters(skipped=True))
    class Operation(object):
        @recorder.operation()
        def execute(self):
            return 5

    assert Operation().execute() == 5
    assert cassette.get_last_recording_id() is None


def test_discard_recording_drops_active_recording():
    """discard_recording() within an operation prevents the recording from being saved."""
    cassette, recorder = make_recorder()
    rec = recorder

    class Operation(object):
        @recorder.operation()
        def execute(self):
            rec.discard_recording()
            return 5

    assert Operation().execute() == 5
    assert cassette.get_last_recording_id() is None


def test_force_sample_keeps_recording_under_low_sampling():
    """force_sample_recording keeps a recording even with a low sampling rate."""
    cassette, recorder = make_recorder()
    rec = recorder

    @recorder.recording_params(RecordingParameters(sampling_rate=0.0))
    class Operation(object):
        @recorder.operation()
        def execute(self):
            rec.force_sample_recording()
            return 5

    assert Operation().execute() == 5
    assert cassette.get_last_recording_id() is not None


def test_ignore_enforced_sampling_drops_recording():
    """ignore_enforced_sampling makes force_sample_recording a no-op so a 0-rate recording is dropped."""
    cassette, recorder = make_recorder()
    rec = recorder

    @recorder.recording_params(RecordingParameters(sampling_rate=0.0, ignore_enforced_sampling=True))
    class Operation(object):
        @recorder.operation()
        def execute(self):
            rec.force_sample_recording()
            assert rec.is_recording_sample_forced is False
            return 5

    assert Operation().execute() == 5
    assert cassette.get_last_recording_id() is None


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------

def test_metadata_extractor_merged_into_recording():
    """A metadata_extractor's returned dict is merged into the recording metadata."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation(metadata_extractor=lambda obj: {'extra': 'meta'})
        def execute(self):
            return 5

    Operation().execute()
    rec_id = cassette.get_last_recording_id()
    recording = cassette.get_recording(rec_id)
    assert recording.get_metadata()['extra'] == 'meta'


def test_incomplete_recording_flag_on_completed_operation():
    """A completed operation is marked as not an incomplete recording."""
    cassette, recorder = make_recorder()

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return 5

    Operation().execute()
    rec_id = cassette.get_last_recording_id()
    recording = cassette.get_recording(rec_id)
    assert recording.get_metadata()[TapeRecorder.INCOMPLETE_RECORDING] is False


def test_base_exception_marks_incomplete_recording():
    """A BaseException escaping the operation marks the recording incomplete with no outputs."""
    cassette, recorder = make_recorder()

    class UncaughtException(BaseException):
        pass

    class Operation(object):
        @recorder.operation()
        def execute(self):
            raise UncaughtException("Error")

    with pytest.raises(UncaughtException):
        Operation().execute()

    rec_id = cassette.get_last_recording_id()
    recording = cassette.get_recording(rec_id)
    assert recording.get_metadata()[TapeRecorder.INCOMPLETE_RECORDING] is True


# --------------------------------------------------------------------------
# Inner interception suppression
# --------------------------------------------------------------------------

def test_inner_interception_is_suppressed():
    """An interception invoked inside another interception is not separately recorded."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        @recorder.intercept_input('input')
        def get_value(self):
            return self.get_inner_value()

        @recorder.intercept_input('inner_input')
        def get_inner_value(self):
            return self.seed

    assert Operation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    recording = cassette.get_recording(rec_id)
    assert next((k for k in recording.get_all_keys() if 'inner_input' in k), None) is None
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == 5


# --------------------------------------------------------------------------
# current_recording_id / modes
# --------------------------------------------------------------------------

def test_current_recording_id_matches_active_recording():
    """current_recording_id reflects the active recording's id during the operation."""
    cassette, recorder = make_recorder()
    rec = recorder

    class Operation(object):
        @recorder.operation()
        def execute(self):
            return rec.current_recording_id

    result = Operation().execute()
    assert result == cassette.get_last_recording_id()


# --------------------------------------------------------------------------
# copy_data_on_intercepion
# --------------------------------------------------------------------------

def test_copy_data_on_interception_prevents_mutation_across_calls():
    """copy_data_on_intercepion records independent copies so mutation between calls is isolated."""
    cassette, recorder = make_recorder()

    @recorder.recording_params(RecordingParameters(copy_data_on_intercepion=True))
    class Operation(object):
        @recorder.operation()
        def execute(self):
            v1 = self.get_value()
            v1['counter'] += 1
            v2 = self.get_value()
            v2['counter'] += 1
            return v1['counter'] + v2['counter']

        @recorder.intercept_input('input')
        def get_value(self):
            return {'counter': 0}

    assert Operation().execute() == 2
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation().execute())
    assert operation_output(result).value['args'][0] == 2


# --------------------------------------------------------------------------
# Deepened hard-vein cases (2026-07-15) — key construction, error paths,
# alias resolution, value_when_missing. All validated against the reference.
# --------------------------------------------------------------------------

def test_capture_args_by_name_distinguishes_kwarg():
    """A CapturedArg(None, 'b') keys only on the kwarg b: changing an uncaptured
    positional still matches the recorded value, but a different captured b has no
    recorded match and raises RecordingKeyError."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, a, b):
            self.a = a
            self.b = b

        @recorder.operation()
        def execute(self):
            return self.get_value(self.a, b=self.b)

        @recorder.intercept_input('input', capture_args=[CapturedArg(None, 'b')])
        def get_value(self, a, b=0):
            return a + b

    assert Operation(1, 2).execute() == 3
    rec_id = cassette.get_last_recording_id()
    # Different uncaptured positional a, same captured b -> recorded 3 is served.
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(99, 2).execute())
    assert operation_output(result).value['args'][0] == 3
    # Different captured b -> no recorded match.
    with pytest.raises(RecordingKeyError):
        recorder.play(rec_id, playback_function=lambda recording: Operation(1, 5).execute())


def test_value_when_missing_static_value_served():
    """value_when_missing as a plain (non-callable) value is served verbatim when no
    recording matches the input on playback (the real method must not run)."""
    cassette, recorder = make_recorder()

    class OldOperation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        def get_value(self):  # not intercepted -> nothing recorded for this alias
            return self.seed

    class NewOperation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        @recorder.intercept_input('input', value_when_missing=42)
        def get_value(self):
            raise Exception('should not run')

    assert OldOperation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: NewOperation(5).execute())
    assert operation_output(result).value['args'][0] == 42


def test_alias_params_resolver_multi_param():
    """An alias template with MULTIPLE params is formatted from the resolver dict, so
    distinct (group, name) combinations produce distinct interception keys."""
    cassette, recorder = make_recorder()

    class ValueCreator(object):
        def __init__(self, group, name, value):
            self.group = group
            self.name = name
            self.value = value

        @recorder.intercept_input('input.{group}.{name}',
                                  alias_params_resolver=lambda s: {'group': s.group, 'name': s.name})
        def get_value(self):
            return self.value

    class Operation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return (ValueCreator('g', 'a', self.seed).get_value()
                    + ValueCreator('g', 'b', self.seed * 2).get_value())

    assert Operation(5).execute() == 15
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: Operation(0).execute())
    assert operation_output(result).value['args'][0] == 15


def test_fallback_aliases_multiple_matches_recorded():
    """A fallback_aliases list with several entries replays against whichever old alias
    was actually recorded (here the second entry)."""
    cassette, recorder = make_recorder()

    class OldOperation(object):
        @recorder.operation()
        def execute(self):
            return self.input('p')

        @recorder.intercept_input('legacy_input')
        def input(self, _p):
            return 5

    class NewOperation(object):
        @recorder.operation()
        def execute(self):
            return self.input('p')

        @recorder.intercept_input('new_input', fallback_aliases=['other_input', 'legacy_input'])
        def input(self, _p):
            return -1  # must not run

    assert OldOperation().execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: NewOperation().execute())
    assert operation_output(result).value['args'][0] == 5


# --------------------------------------------------------------------------
# Diversified independent-vein cases (2026-07-15) — each fails for a reason
# INDEPENDENT of the operation-output envelope (key construction / error paths /
# sampling control-flow / class-operation), to decorrelate the difficulty and
# tighten the band. All validated against the reference.
# --------------------------------------------------------------------------

def test_static_input_kwarg_participates_in_key_mismatch_raises():
    """For a static input, a supplied kwarg participates in the interception key;
    replaying with a different kwarg value finds no recorded match -> RecordingKeyError."""
    cassette, recorder = make_recorder()

    class Operation(object):
        def __init__(self, k):
            self.k = k

        @recorder.operation()
        def execute(self):
            return self.get_value(x=self.k)

        @staticmethod
        @recorder.static_intercept_input('input')
        def get_value(x):
            return 5

    Operation('k1').execute()
    rec_id = cassette.get_last_recording_id()
    with pytest.raises(RecordingKeyError):
        recorder.play(rec_id, playback_function=lambda recording: Operation('k2').execute())


def test_force_sample_overrides_zero_rate_but_discard_still_wins():
    """discard_recording() takes precedence even after force_sample_recording() under a
    0.0 sampling rate: nothing is saved (control-flow precedence, independent of output)."""
    cassette, recorder = make_recorder()
    rec = recorder

    @recorder.recording_params(RecordingParameters(sampling_rate=0.0))
    class Operation(object):
        @recorder.operation()
        def execute(self):
            rec.force_sample_recording()
            rec.discard_recording()
            return 5

    assert Operation().execute() == 5
    assert cassette.get_last_recording_id() is None


def test_value_when_missing_callable_receives_invocation_self():
    """value_when_missing as a callable is invoked with the LIVE invocation args (self),
    so its served result reflects the current object's state, not any recorded value."""
    cassette, recorder = make_recorder()

    class OldOperation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        def get_value(self):  # not intercepted -> nothing recorded for this alias
            return self.seed

    class NewOperation(object):
        def __init__(self, seed=0):
            self.seed = seed

        @recorder.operation()
        def execute(self):
            return self.get_value()

        @recorder.intercept_input('input', value_when_missing=lambda self: self.seed * 100)
        def get_value(self):
            raise Exception('should not run')

    assert OldOperation(5).execute() == 5
    rec_id = cassette.get_last_recording_id()
    result = recorder.play(rec_id, playback_function=lambda recording: NewOperation(7).execute())
    # Served value reflects the NEW object's seed (7 * 100), proving the callable ran live.
    assert operation_output(result).value['args'][0] == 700
