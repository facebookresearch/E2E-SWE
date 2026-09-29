# isobar

Build `isobar`, a Python library for **algorithmic musical composition**. Its core
idea is the **Pattern**: a lazy, iterable generator of values (notes, durations,
arbitrary data) that can be combined, transformed, and scheduled onto a musical
**Timeline**. The library also provides music-theory helpers (keys, scales,
chords) and note/frequency conversions.

## Dependencies

The environment is **offline**: every dependency is already installed and you
**must not install anything** (no `pip install`, no network access). The project
is installed for you by a `setup.sh` that runs offline. Available libraries:

- `numpy` — used by the numeric/utility helpers (e.g. the seeded stochastic
  patterns and array operations).
- `mido`, `python-osc`, `python-rtmidi`, `LinkPython-extern` — installed and
  importable, but only needed for live MIDI / OSC / Ableton Link I/O. The tested
  surface uses the in-memory output device (below) and does not require any
  audio/MIDI hardware, so you do not need these for the graded behavior.

The package must import cleanly with no audio/MIDI hardware present.

## Import paths

Everything is re-exported at the top level, e.g. `import isobar as iso` then
`iso.PSequence(...)`, `iso.Key(...)`, etc. The dummy output device is imported as
`from isobar.io import DummyOutputDevice`. Organise internal modules however you
like; only these public names are part of the contract.

## Patterns

A `Pattern` is an iterator. Iterating it (`list(p)`, `next(p)`, or `p.nextn(k)`
to collect the next `k` values) yields its sequence; a finite pattern raises
`StopIteration` when exhausted. `p.nextn(k)` collects **up to** `k` values: if
the pattern is exhausted before `k` values are produced, it returns the values
collected so far (a list of length `<= k`) and does **not** raise
`StopIteration` — unlike bare `next(p)`, which surfaces `StopIteration` at
exhaustion. **`None` is a valid value** meaning a musical rest, and propagates
through transformations.

A crucial property: **any numeric argument to a pattern may itself be a Pattern.**
When it is, that embedded pattern is advanced by one step on each output step, and
the combined pattern ends when any required input is exhausted. Scalars are
treated as infinite constants.

Patterns to implement (constructor describes behavior; `PConstant(v)` yields `v`
forever):

- `PSequence(list, repeats=None)` — cycle through `list`, `repeats` times (forever
  if `repeats` is None).
- `PSeries(start=0, step=1, length=None)` — arithmetic series `start, start+step, …`.
  `length` bounds the number of values emitted (unbounded when `None`). Unlike a
  per-step value input, `length` is a **count**: when it is given as a Pattern its
  value is resolved to the scalar item-count, so a constant pattern caps the series
  at that many items.
- `PRange(start=0, end=None, step=1)` — like `range`, but `start`/`end`/`step` may
  be patterns; stops before crossing `end`.
- `PGeom(start=1, multiply=2, length=None)` — geometric series.
- `PImpulse(period)` — emit `1` when the step index is a multiple of `period` (so
  it fires on step 0, then `period`, `2*period`, …) and `0` otherwise.
- `PLoop(pattern, count)` — buffer a finite `pattern` and replay it `count` times.
- `PPingPong(pattern, count)` — buffer a finite `pattern`, then play it forward
  and back, bouncing off the endpoints without repeating the turning-point value,
  for `count` bounces. E.g. `PPingPong(PSequence([1,2,3],1), 2)` yields
  `[1, 2, 3, 2, 1, 2, 3, 2, 1]`.
- `PCreep(pattern, length, creep, repeats)` — read a sliding window of exactly
  `length` items, repeat the window `repeats` times, then advance the window by
  `creep` and repeat.
- `PStutter(pattern, count)` — repeat each value of `pattern` `count` times
  (`count` may itself be a pattern).
- `PSubsequence(pattern, offset, length)` — skip `offset` items then yield the
  next `length`.
- `PInterpolate(pattern, steps, mode=INTERPOLATION_LINEAR)` — walk from each value
  of `pattern` to the next over `steps` increments (the `steps` count itself may be
  a pattern, read once per target). It emits the starting value and then the
  interpolated values up to and including each successive target.
  `INTERPOLATION_LINEAR` ramps linearly; `INTERPOLATION_NONE` holds the previous
  value; an unknown mode raises `ValueError`. E.g. with `INTERPOLATION_LINEAR`,
  `PInterpolate(PSequence([0,1,2],1), PSequence([4,2],1))` yields
  `[0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]`. Constants `INTERPOLATION_NONE`,
  `INTERPOLATION_LINEAR` are public.
- `PRef(pattern)` — proxy another pattern via a settable `.pattern` attribute, so
  the target can be swapped while iterating.
- `PArrayIndex(arrays, index)` — `arrays` is a fixed sequence (it is **not** a
  pattern advanced each step); on each step, index it with the current `index`
  value (which may be a pattern). If the selected element is itself a Pattern, it
  is resolved to its current value before being emitted. A `None` index yields a
  rest (`None`).
- `PDict(mapping)` — given a dict whose values are patterns/scalars, yield a dict
  per step with each value advanced; ends when any contained pattern ends. Also
  accepts a list of dicts.
- `PLSystem(rule, generations=1)` — expand a Lindenmayer system and emit a
  deterministic sequence of integer pitch offsets. The axiom/rule is a string over
  the alphabet `N` (emit current value), `-`/`+` (decrement/increment the current
  value), and `[`/`]` (push/pop the current value). Each generation rewrites every
  `N` with the rule. E.g. `list(PLSystem("N[-N++N]-N", 1))` → `[0, -1, 1, -1]`.

### Pattern arithmetic

Patterns support elementwise operators with a scalar or another pattern (which is
advanced per step): `+ - * / // % **` (and reflected forms like `2 / p`). The
result ends when either operand ends.

### Stochastic patterns

These draw from a seeded RNG. Each exposes `.seed(n)` (make the stream
deterministic) and `.reset()` (replay from the start). Identical seed ⇒ identical
sequence.

- `PWhite(min, max)` — uniform random values in `[min, max]` (integer output when
  the bounds are integers).
- `PBrown(start, step, min, max)` — a random walk starting at `start`, moving by up
  to ±`step`, clamped to `[min, max]`.
- `PChoice(values)` — pick a random element from `values` each step.
- `PMarkov(sequence_or_table)` — a first-order Markov chain. Given a training
  `sequence` (a list), learn the transition table (for each value, the multiset of
  values that followed it); given a `dict` mapping each value to its list of
  possible successors, use it directly. Each step picks the next value at random
  from the current value's successors. Seedable and `reset()`-able like the others.

## Tonal transformations

These interpret integers as **scale degrees** relative to a `Key` (defaulting to C
major). `None` passes through unchanged; negative degrees map below the tonic.

- `PDegree(pattern, key=Key("C", "major"))` — map scale degrees to semitone
  offsets (major: degree 0,1,2,…,7 → 0,2,4,5,7,9,11,12). Array values map elementwise.
- `PFilterByKey(pattern, key)` — pass semitone values that belong to `key`,
  replace others with `None`.
- `PNearestNoteInKey(pattern, key)` — snap each semitone value to the nearest
  in-key semitone, measured by absolute numeric distance `|value - candidate|`.
  Inputs need not be integers: a fractional (float) semitone value is snapped to
  the closest in-key semitone by that distance too. When a value is exactly
  halfway between two in-key semitones, snap to the lower one.
- `PMidiNoteToFrequency(pattern)` — convert MIDI note numbers to frequencies (Hz).

## Music theory objects

- `Scale(semitones=[0,2,4,5,7,9,11], name=..., octave_size=12)` — `get(n)` (and
  `[n]`) returns the semitone for degree `n`, wrapping across octaves
  (`get(7)` → an octave above `get(0)`).
- `Key(tonic, scale)` — `tonic` is a note name (`"C"`) or pitch number; `scale` is
  a scale name (`"major"`, `"minor"`) or a `Scale`. `get(n)`/`[n]` returns the
  semitone for scale degree `n` (relative to the tonic, octave-wrapping);
  `.semitones` lists one octave; `n in key` tests membership (with `None` always a
  member). An unknown note name raises `UnknownNoteName`; an unknown scale name
  raises `UnknownScaleName`.
- `Chord(intervals, root=0)` — `.intervals`, `.root`, and `.semitones` (the
  absolute semitones obtained by accumulating `intervals` from `root`, e.g.
  `Chord([3,4,3])` → `[0,3,7,10]`).

`UnknownNoteName` and `UnknownScaleName` are public exception types.

## Note / frequency utilities

Octave numbering places middle C (MIDI 60) at `"C4"`; A4 (MIDI 69) = 440 Hz.

- `midi_note_to_note_name(n)` / `note_name_to_midi_note(name)` — e.g. `60`↔`"C4"`,
  `61`↔`"C#4"`, and `"Db4"` → `61`.
- `midi_note_to_frequency(n)` / `frequency_to_midi_note(f)` — equal-tempered
  conversion; `None` inputs yield `None`.

## Timeline and scheduling

A `Timeline` plays scheduled patterns by emitting events to an output device.

- `Timeline(tempo=120, output_device=None)` — `clock_source.tempo` reports the
  tempo; `DEFAULT_TICKS_PER_BEAT` (public constant) is the tick resolution. The
  device passed as `output_device` is re-exposed as a public readable attribute of
  the same name: `timeline.output_device` returns that device, so its recorded
  events can be reached via `timeline.output_device.events`.
- `timeline.tick()` advances time by one tick (`current_time` increases by
  `1 / DEFAULT_TICKS_PER_BEAT` beats). The `stop_when_done` attribute defaults to
  `False` on a freshly-constructed `Timeline`, so a plain `tick()` keeps advancing
  time and never raises on an empty or finished timeline. Only once
  `stop_when_done` has been set `True` and there is nothing left to play does
  `tick()` raise `StopIteration`.
- `timeline.schedule(events, quantize=None)` registers a dict of event patterns
  and returns a `Track`. The note-event key is the public constant `EVENT_NOTE`;
  its value is a pattern of MIDI note numbers.
- `timeline.run()` ticks until all tracks are done (requires `stop_when_done`).

Scheduling `{EVENT_NOTE: PSequence([n], 1)}` plays note `n` for one beat: it emits
a `note_on` at the note's start time and a `note_off` one beat later (default
velocity 64, channel 0).

### Event fields

The dict passed to `schedule` maps event-field constants to patterns (or scalars).
Each step advances every field by one and produces one note. Supported fields
(all public constants):

- `EVENT_NOTE` — an absolute MIDI note number.
- `EVENT_DEGREE` — a scale degree, resolved to a MIDI note via the event's key
  (default C major) before other modifiers are applied. A `None` degree is a rest
  (no note that step).
- `EVENT_DURATION` — the note's length in beats (default 1); it sets the gap until
  the next step and the `note_off` time.
- `EVENT_TRANSPOSE` — a semitone offset added to the resolved note.
- `EVENT_OCTAVE` — a whole-octave (12-semitone) offset added to the resolved note.

For example, scheduling `{EVENT_DEGREE: PSequence([0,1,2,3,None,7,-1],1),
EVENT_DURATION: 1.0, EVENT_TRANSPOSE: 12}` in C major produces notes
`12, 14, 16, 17, (rest), 24, 11` at successive beats.

### Output devices

`from isobar.io import DummyOutputDevice` provides an in-memory device for use
without hardware. It records every event into a list attribute `events`, where
each entry is:

- `[time, "note_on", note, velocity, channel]`
- `[time, "note_off", note, channel]`

with `time` measured in beats. This is the device used to observe what a Timeline
produces — reachable either via the device object you constructed or via
`timeline.output_device.events` on the Timeline it was given to.
