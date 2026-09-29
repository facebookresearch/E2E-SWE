# playback

Build `playback`, a Python library for **record/replay** testing of operations.
You decorate the entry point of an operation and its inputs/outputs with
decorators; during a *recording* run every intercepted input result and output
invocation is captured into a storage "cassette". Later you can *replay* the same
operation against a (possibly changed) code version: instead of really executing
the intercepted inputs, the recorded values are returned, and the outputs the
operation produces during replay are collected so they can be compared against
what was recorded.

The import package is `playback` (note: the PyPI distribution name differs from
the import name; only the import name matters here).

## Dependencies

The environment is **fully offline** — there is no network access. Every
dependency below is **already installed**, and the project itself is installed
for you by an offline `setup.sh` (which runs `pip install -e . --no-build-isolation`).
**Do not install anything** — pip cannot reach any package index.

You may rely on any of these pre-installed libraries:

- `jsonpickle` — used to serialize interception keys and to serialize/deserialize
  recordings.
- `six` — Python 2/3 compatibility helpers.
- `parse` — inverse of `str.format` string parsing.
- `contextlib2` — backport of `contextlib` utilities.
- `decorator` — signature-preserving function decorators.

## Package Structure

The tests import exactly these paths; they must resolve:

- `from playback.tape_recorder import TapeRecorder, CapturedArg, RecordingParameters, Playback, Output`
- `from playback.tape_cassettes.in_memory.in_memory_tape_cassette import InMemoryTapeCassette`
- `from playback.exceptions import TapeRecorderException, RecordingKeyError, InputInterceptionKeyCreationError, OperationExceptionDuringPlayback, NoSuchRecording`

## Example: a record/replay cycle

A small end-to-end illustration of how the decorators fit together and how you
read back a replay. You decorate the operation's entry point and the methods that
read inputs / emit outputs, record a real call, then replay it:

```python
from playback.tape_recorder import TapeRecorder
from playback.tape_cassettes.in_memory.in_memory_tape_cassette import InMemoryTapeCassette

cassette = InMemoryTapeCassette()
recorder = TapeRecorder(cassette)
recorder.enable_recording()

class Multiply(object):
    @recorder.operation()                  # entry point: opens a recording scope
    def execute(self):
        value = self.fetch(3)              # an intercepted input
        self.emit(value * 2)               # an intercepted output (side effect)
        return value * 2

    @recorder.intercept_input('source')    # runs for real while recording;
    def fetch(self, n):                    # served from the recording on replay
        return n + 1

    @recorder.intercept_output('sink')     # captures what was sent outward
    def emit(self, result):
        return 'ok'

# --- record a real run ---
assert Multiply().execute() == 8           # fetch(3) -> 4, emit(8), returns 8
rec_id = cassette.get_last_recording_id()

# --- replay against the recording ---
# On replay `fetch` is NOT executed; its recorded 4 is served instead. `emit` is
# re-invoked and its outgoing payload re-captured.
result = recorder.play(
    rec_id,
    playback_function=lambda recording: Multiply().execute(),
)
```

Inspecting the playback result — `play()` returns a `Playback` whose
`playback_outputs` and `recorded_outputs` are lists of `Output(key, value)`
namedtuples in invocation order:

```python
# Each intercepted output's value is the captured {'args': [...], 'kwargs': {...}}
# payload that was sent to it.
sink_out = next(o for o in result.playback_outputs if 'sink' in o.key)
assert sink_out.value == {'args': [8], 'kwargs': {}}

# The operation's own return value is captured too, under the reserved alias
# TapeRecorder.OPERATION_OUTPUT_ALIAS — locate it the same way:
op_out = next(o for o in result.playback_outputs
              if TapeRecorder.OPERATION_OUTPUT_ALIAS in o.key)

# A replay can be diffed against what was originally recorded:
assert sorted(result.recorded_outputs) == sorted(result.playback_outputs)
assert result.playback_duration > 0 and result.recorded_duration > 0
```

## Core concepts

### TapeCassette / InMemoryTapeCassette

A *cassette* is the storage backend for recordings. `InMemoryTapeCassette()`
stores everything in memory (serialized with jsonpickle on save, so it surfaces
the same serialization pitfalls a real backend would). It exposes:

- `create_new_recording(category)` → a new `Recording` whose `id` is
  `"{category}/{hex-uuid}"`.
- `get_recording(recording_id)` → the stored `Recording` (a fresh deserialized
  copy), or `None` if the id is unknown.
- `get_last_recording_id()` → id of the most recently saved recording.
- `get_all_recording_ids()` → sorted list of saved recording ids.
- `extract_recording_category(recording_id)` → the category that was used to
  create the recording, i.e. the portion of the id before the `/` separator (the
  inverse of the `"{category}/{hex-uuid}"` id format).

A `Recording` supports `get_all_keys()`, `get_data(key)` (raises
`RecordingKeyError` for a missing key, and always returns a **fresh deep copy**
so callers cannot mutate the stored data), `get_metadata()`, and indexing
(`recording[key]`).

### TapeRecorder

`TapeRecorder(tape_cassette, random_seed=None)` drives recording and playback.
Recording must be turned on with `enable_recording()` (and can be turned off with
`disable_recording()`); `recording_enabled` reflects this. Until recording is
enabled the decorators are transparent pass-throughs.

Properties: `in_recording_mode`, `in_playback_mode`, `current_recording_id`.

#### `operation(metadata_extractor=None)` / `class_operation(...)`

Decorator marking the entry point of an operation (an instance method;
`class_operation` for a classmethod). When recording is enabled, calling the
decorated method opens a recording scope for the duration of the call, records
the operation's return value as a special output, then saves the recording. The
operation's own class is stored in metadata; the recording category is the class
name. `metadata_extractor`, if given, is called with the same arguments as the
operation after it completes and its returned dict is merged into the metadata.

`operation` derives the operation's class from `type(self)`. `class_operation`
is its classmethod analogue and is applied **beneath** a standard `@classmethod`
(with `@classmethod` outermost): `class_operation()` returns a plain function —
it does **not** itself produce a classmethod — so the outer `@classmethod` binds
`cls`, and the recording category is that bound `cls`'s class name (not
`type(args[0])`).

```python
class Op(object):
    @classmethod
    @recorder.class_operation()
    def execute(cls):
        return 5

Op.execute()   # recording category == 'Op'
```

The operation's return value is captured as an output under a reserved alias
available as `TapeRecorder.OPERATION_OUTPUT_ALIAS`, using the same captured-value
envelope as any other output: its `Output.value` is an
`{'args': [...], 'kwargs': {...}}` payload holding the return value as its single
positional entry and no keyword arguments. If the operation raises a
normal `Exception`, that exception is captured as the operation output (so it
appears among the recorded outputs) and then re-raised; the exception object
itself takes the return value's place in that positional entry — unlike a
recorded input or output *result*, the operation output is **not** stored in a
"marked as an exception" form.

Other reserved metadata key attributes that must exist on the class:
`DURATION`, `RECORDED_AT`, `OPERATION_CLASS`, `EXCEPTION_IN_OPERATION`,
`INCOMPLETE_RECORDING`. After a recording, `EXCEPTION_IN_OPERATION` reflects
whether the operation raised, and `INCOMPLETE_RECORDING` is True only when the
operation never produced an operation-output (e.g. a `BaseException` such as
`KeyboardInterrupt` escaped).

#### `intercept_input(alias, alias_params_resolver=None, data_handler=None, capture_args=None, run_intercepted_when_missing=False, value_when_missing=None, fallback_aliases=None)`

Decorates an instance method that acts as an *input* to the operation (something
the operation reads from the outside world). `static_intercept_input(...)` is the
same for a `@staticmethod`. An input may also decorate a `@property` (the property
getter is treated as the intercepted method).

- **Recording:** the method runs for real; its return value is recorded under an
  *input interception key* derived from `alias` + the captured invocation
  arguments. If the method raises, the exception is recorded under that key
  (marked as an exception) and re-raised.
- **Playback:** the method is **not** run; the value recorded under the matching
  key is returned (a fresh copy). If the recorded entry was an exception, that
  exception object is re-raised.

The interception key is built from the alias and the invocation arguments so that
two calls with *equivalent* arguments map to the same key (independent of dict
key ordering or kwarg ordering), and calls with different arguments map to
different keys. You choose the exact textual format; it only has to be a
deterministic, collision-free function of `(alias, captured args, captured
kwargs)` that round-trips through serialization.

`capture_args` controls which arguments participate in the key:
  - `None` (default): capture all positional args (excluding `self` for instance
    methods; including everything for static functions) and all kwargs.
  - `[]` or `False`: capture *no* arguments — every invocation of this alias maps
    to the same key regardless of arguments.
  - a list of `CapturedArg(position, name)` namedtuples: capture only those
    specific arguments. For each entry, if `name` is present in the call's kwargs
    use that, otherwise if `position is not None` use the positional argument at
    that index. (`CapturedArg = namedtuple('CapturedArg', 'position name')`.)
    `position` indexes the invocation's positional arguments **as actually passed,
    with `self` at index 0** for an instance method (unlike the `None` case above,
    the `self` slot is *not* stripped here). For an instance method
    `def m(self, a, b):`, `CapturedArg(1, 'a')` captures `a` and `CapturedArg(2, 'b')`
    captures `b`; for a static function the first real argument is at index 0.

`alias_params_resolver`, if given, is called with the invocation arguments and
returns a dict used to `str.format` the alias (e.g. alias `'input.{name}'` with a
resolver returning `{'name': ...}`), so the same method on different instances can
produce distinct keys.

`fallback_aliases` is either a list of alias strings or a callable returning such
a list. During playback, if no recorded entry matches the primary alias's key, the
recorder tries the key built from each fallback alias (with the same captured
arguments) in order, returning the first match. This lets a renamed input still
replay against old recordings.

When no recorded value matches during playback:
  - if `run_intercepted_when_missing` is True, run the original method;
  - else if `value_when_missing` is set, return it (call it with the invocation
    args if it is callable);
  - else raise `RecordingKeyError`.

If building the interception key fails (e.g. an argument is unserializable),
during recording the active recording is discarded and the original method still
runs (returning its real value); during playback an
`InputInterceptionKeyCreationError` is raised.

`data_handler` (an object with `prepare_input_for_recording(interception_key,
result, args, kwargs)` and `restore_input_from_recording(recorded_data, args,
kwargs)`) lets you transform the value before storing and after loading. It is
delegated to the user — do not assume a particular transformation.

#### `intercept_output(alias, data_handler=None, fail_on_no_recorded_result=True, default_result_when_not_recorded=None)`

Decorates an instance method that acts as an *output* of the operation (a side
effect / something the operation sends outward). `static_intercept_output(...)` is
the staticmethod variant.

- Every time an output alias is invoked (in **both** recording and playback
  modes) the recorder captures *what was sent to the output*: by default the value
  `{'args': [...], 'kwargs': {...}}` where `args` is the list of positional
  arguments (excluding `self` for instance methods) and `kwargs` the keyword
  arguments. These captured outputs are what `Playback.recorded_outputs` and
  `Playback.playback_outputs` expose.
- The output method's **return value** is also recorded separately (during
  recording) and replayed (during playback) so the operation observes the same
  return value it originally saw.
- The same alias can be invoked multiple times within one operation. Each
  invocation is tracked with its own monotonically increasing invocation number
  (per alias, starting at 1) so the captured outputs are distinct and ordered.
  You choose how to encode the invocation number into the key, but repeated calls
  to the same alias must produce distinct keys and, when extracted, the recorded
  and replayed outputs must line up in invocation order. The invocation counter is
  reset between operations.
- During playback, if there is no recorded return value for an output, behavior
  depends on `fail_on_no_recorded_result`: if True, raise `RecordingKeyError`; if
  False, return `default_result_when_not_recorded`. (This supports adding a new
  output to code that has existing recordings.)

If an output method raises during recording, the exception is recorded under the
output's result key (marked as an exception) and re-raised; on playback the
recorded exception is re-raised.

#### Nested interception suppression

An interception (input or output) invoked *inside* another interception's own
method body is **not** separately recorded or replayed. While the recorder is
executing an intercepted method, any further intercepted calls made from within
it run as plain pass-throughs (their result is already captured as part of the
outer interception's recorded value). For example, if input `'input'` internally
calls input `'inner_input'`, only `'input'` is recorded — no key for
`'inner_input'` appears in the recording. The operation entry point itself does
not count as an interception for this purpose.

#### `record_data(key, value)` / `play_data(key)`

`record_data` stores arbitrary serializable data under `key` while in recording
mode (no-op otherwise). `play_data` returns the data stored under `key` while in
playback mode (`None` otherwise; raises `RecordingKeyError` for a missing key
during playback).

#### `discard_recording()` / `force_sample_recording()` / `is_recording_sample_forced`

`discard_recording()` aborts the active recording so nothing is saved.
Sampling: `RecordingParameters(sampling_rate=...)` (and the
`recording_params(...)` class decorator) control whether a recording is kept; a
`sampling_rate >= 1` always keeps it. `force_sample_recording()` forces the active
recording to be kept regardless of sampling, and `is_recording_sample_forced`
reflects the **effective** forced state of the active recording (True once
forcing has taken effect). When the operation's class sets
`RecordingParameters(ignore_enforced_sampling=True)`, `force_sample_recording()`
is a **no-op**: the enforced sample is ignored at the point of the call, so
`is_recording_sample_forced` stays False and the recording is still governed by
(and dropped under) the sampling rate.

`RecordingParameters(sampling_rate=1.0, ignore_enforced_sampling=False,
skipped=False, copy_data_on_intercepion=False)`: `skipped=True` makes the
operation not record at all; `copy_data_on_intercepion=True` deep-copies each
intercepted input value when recording it.

`recording_params(recording_parameters=None, **kwargs)` is a **method on the
`TapeRecorder`** that returns a class decorator (like `operation` and
`intercept_input`, it is used as `@recorder.recording_params(...)`). It attaches
`RecordingParameters` to an operation class (accepts either a
`RecordingParameters` instance or its keyword arguments).

### Replaying: `play(recording_id, playback_function)`

`play` loads the recording, enters playback mode, then calls
`playback_function(recording)` — which should re-invoke the operation (its inputs
will be served from the recording, its outputs collected). It returns a
`Playback` object with attributes:

- `playback_outputs` — list of `Output(key, value)` captured during this replay,
  in invocation order.
- `recorded_outputs` — list of `Output(key, value)` captured in the original
  recording.
- `playback_duration`, `recorded_duration` — floats (> 0).
- `original_recording` — the `Recording` used.

`Output = namedtuple('Output', 'key value')`.

An operation that raised during recording will, on replay, have its exception
surfaced as part of the recording's outputs rather than propagating out of
`play` — `play` returns normally and the captured operation-output value carries
the recorded exception.

## Exceptions

All live in `playback.exceptions` and derive from `TapeRecorderException`
(itself an `Exception`): `RecordingKeyError`,
`InputInterceptionKeyCreationError`, `OperationExceptionDuringPlayback`,
`NoSuchRecording`.

`OperationExceptionDuringPlayback` marks that the replayed operation raised an
unexpected (non-interception) error during playback; `play` catches it
internally so the failure surfaces as the captured operation output rather than
propagating out of `play`.
