"""End-to-end tests for isobar, a library for algorithmic musical composition.

Tests drive the public API the way a user would: build Pattern objects and read
their generated sequences, query musical Key/Scale/Chord objects, convert
note/frequency representations, and schedule events onto a Timeline whose output
is captured by an in-memory dummy device. All randomness is seeded so sequences
are deterministic.
"""

import pytest

import isobar as iso
from isobar.io import DummyOutputDevice


@pytest.fixture
def dummy_timeline():
    timeline = iso.Timeline(120, output_device=DummyOutputDevice())
    timeline.stop_when_done = True
    return timeline


# --------------------------------------------------------------------------
# Sequence patterns
# --------------------------------------------------------------------------

def test_psequence():
    """PSequence yields its list, repeated `repeats` times; elements may be tuples."""
    assert list(iso.PSequence([1, 2, 3], 1)) == [1, 2, 3]
    assert list(iso.PSequence([(1, 2), (3, 4)], 2)) == [(1, 2), (3, 4), (1, 2), (3, 4)]


def test_pseries_prange_pgeom():
    """Arithmetic generators: PSeries (start+step), PRange (bounded), PGeom (geometric)."""
    assert list(iso.PSeries(2, iso.PSequence([1, 2]), iso.PConstant(5))) == [2, 3, 5, 6, 8]
    assert list(iso.PRange(0, iso.PConstant(10), iso.PSequence([1, 2]))) == [0, 1, 3, 4, 6, 7, 9]
    assert list(iso.PRange(500, -500, -250)) == [500, 250, 0, -250]
    assert list(iso.PGeom(1, iso.PSequence([1, 2]), 8)) == [1, 1, 2, 2, 4, 4, 8, 8]


def test_ploop_pingpong():
    """PLoop repeats a finite pattern; PPingPong bounces it forward then backward."""
    assert list(iso.PLoop(iso.PSequence([1, 2, 3], 1), 3)) == [1, 2, 3, 1, 2, 3, 1, 2, 3]
    assert list(iso.PPingPong(iso.PSequence([1, 2, 3], 1), 2)) == [1, 2, 3, 2, 1, 2, 3, 2, 1]


def test_pcreep_pstutter():
    """PCreep slides a window across a series; PStutter repeats each value N times."""
    assert list(iso.PCreep(iso.PSequence([1, 2, 3, 4, 5], 1), 3, 1, 2)) == \
        [1, 2, 3, 1, 2, 3, 2, 3, 4, 2, 3, 4, 3, 4, 5, 3, 4, 5]
    assert iso.PStutter(iso.PSequence([1, 2, 3, 4], 1), iso.PSequence([2, 3])).nextn(16) == \
        [1, 1, 2, 2, 2, 3, 3, 4, 4, 4]


def test_psubsequence_pinterpolate():
    """PSubsequence selects a slice of an infinite series; PInterpolate fills between values."""
    assert list(iso.PSubsequence(iso.PSeries(), 4, 4)) == [4, 5, 6, 7]
    assert list(iso.PInterpolate(iso.PSequence([0, 1, 2], 1),
                                 iso.PSequence([4, 2], 1),
                                 iso.INTERPOLATION_LINEAR)) == [0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0]


def test_pimpulse():
    """PImpulse emits 1 every Nth step and 0 otherwise."""
    assert list(iso.PSubsequence(iso.PImpulse(4), 0, 8)) == [1, 0, 0, 0, 1, 0, 0, 0]


# --------------------------------------------------------------------------
# Core combinator patterns
# --------------------------------------------------------------------------

def test_pref():
    """PRef proxies another pattern and can be re-pointed mid-stream."""
    c = iso.PRef(iso.PSequence([1, 2, 3], 1))
    assert next(c) == 1
    assert next(c) == 2
    c.pattern = iso.PSequence([4, 5, 6], 1)
    assert [next(c), next(c), next(c)] == [4, 5, 6]
    with pytest.raises(StopIteration):
        next(c)


def test_parrayindex_pdict():
    """PArrayIndex indexes arrays by a pattern; PDict yields dicts of patterned values."""
    c = iso.PArrayIndex([iso.PConstant(5), iso.PConstant(9)], iso.PSequence([0, 1], 2))
    assert list(c) == [5, 9, 5, 9]

    d = iso.PDict({"a": iso.PSequence([1, 2, 3], 1), "b": 4, "c": None})
    assert list(d) == [
        {"a": 1, "b": 4, "c": None},
        {"a": 2, "b": 4, "c": None},
        {"a": 3, "b": 4, "c": None},
    ]


def test_pattern_arithmetic_operators():
    """Patterns support elementwise arithmetic with scalars and other patterns."""
    assert list(iso.PSequence([1, 2, 3], 1) + 1.5) == [2.5, 3.5, 4.5]
    assert list(iso.PSequence([1, 2, 3], 1) * iso.PSequence([2, 3, 4, 5], 1)) == [2, 6, 12]
    assert list(iso.PSequence([1, 2, 3], 1) % 2) == [1, 0, 1]
    assert list(iso.PSequence([1, 2, 3], 1) ** 2) == [1, 4, 9]
    assert list(iso.PSequence([1, 2, 3], 1) // 2) == [0, 1, 1]


# --------------------------------------------------------------------------
# Stochastic patterns (seeded for determinism)
# --------------------------------------------------------------------------

def test_pwhite_seeded():
    """PWhite draws uniformly within [min, max]; identical seed -> identical sequence."""
    a = iso.PWhite(iso.PConstant(5), iso.PConstant(10))
    a.seed(0)
    seq = a.nextn(10)
    # Integer bounds -> integer outputs, each within the requested range.
    assert all(isinstance(v, int) and 5 <= v <= 10 for v in seq)
    # Identical seed -> identical sequence.
    b = iso.PWhite(iso.PConstant(5), iso.PConstant(10))
    b.seed(0)
    assert b.nextn(10) == seq
    # reset() replays the seeded sequence from the start.
    a.reset()
    assert a.nextn(10) == seq


def test_pbrown_seeded():
    """PBrown is a bounded random walk; reset replays the same seeded sequence."""
    start, step, lo, hi = 0, 5, -5, 5
    a = iso.PBrown(start, iso.PConstant(step), iso.PConstant(lo), iso.PConstant(hi))
    a.seed(0)
    seq = a.nextn(20)
    # The walk starts at `start`, stays clamped to [min, max], and steps by at most +/-step.
    assert seq[0] == start
    assert all(lo <= v <= hi for v in seq)
    assert all(abs(b - a_) <= step for a_, b in zip(seq, seq[1:]))
    # reset() replays the same seeded sequence.
    a.reset()
    assert a.nextn(20) == seq
    # Identical seed -> identical sequence.
    b = iso.PBrown(start, iso.PConstant(step), iso.PConstant(lo), iso.PConstant(hi))
    b.seed(0)
    assert b.nextn(20) == seq


def test_pchoice_seeded():
    """PChoice picks a random element from a collection; identical seed -> identical choices."""
    values = [0, 1, 2, 3, 4, 5, 6, 7]
    a = iso.PChoice(values)
    a.seed(0)
    seq = a.nextn(20)
    # Every emitted value is drawn from the provided collection.
    assert all(v in values for v in seq)
    # reset() replays the same seeded sequence.
    a.reset()
    assert a.nextn(20) == seq
    # Identical seed -> identical sequence.
    b = iso.PChoice(values)
    b.seed(0)
    assert b.nextn(20) == seq


# --------------------------------------------------------------------------
# Tonal patterns (key/scale aware)
# --------------------------------------------------------------------------

def test_pdegree():
    """PDegree maps scale degrees to semitone offsets within a key (default major)."""
    assert list(iso.PDegree(iso.PSequence([0, 1, -1, None, 7], 1))) == [0, 2, -1, None, 12]


def test_pfilterbykey_and_nearest():
    """PFilterByKey nulls out-of-key notes; PNearestNoteInKey snaps to the nearest in-key note."""
    assert list(iso.PFilterByKey(iso.PSequence([0, 1, 2, 3, -1, None, 2], 1),
                                 iso.Key("C", "major"))) == [0, None, 2, None, -1, None, 2]
    assert list(iso.PNearestNoteInKey(iso.PSequence([0, 1, 2, 3, -1, None, 12.5], 1),
                                      iso.Key("C", "major"))) == [0, 0, 2, 2, -1, None, 12]


def test_pmidinote_to_frequency():
    """PMidiNoteToFrequency converts MIDI note numbers to frequencies (Hz)."""
    result = list(iso.PMidiNoteToFrequency(iso.PSequence([60, None], 1)))
    assert result[0] == pytest.approx(261.6255653005986)
    assert result[1] is None


# --------------------------------------------------------------------------
# Music theory objects
# --------------------------------------------------------------------------

def test_key_get_and_contains():
    """Key maps degrees to semitones and reports membership."""
    k = iso.Key("C", "major")
    assert k.get(0) == k[0] == 0
    assert k.get(1) == k[1] == 2
    assert k.get(7) == k[7] == 12
    assert 0 in k and 2 in k and 4 in k
    assert 1 not in k and 3 not in k
    assert iso.Key("C", "minor").semitones == [0, 2, 3, 5, 7, 8, 10]


def test_key_invalid_raises():
    """Unknown note names and scale names raise specific exceptions."""
    with pytest.raises(iso.UnknownNoteName):
        iso.Key("X", "major")
    with pytest.raises(iso.UnknownScaleName):
        iso.Key("C", "mundo")


def test_scale():
    """Scale wraps a semitone list and indexes degrees across octaves."""
    s = iso.Scale([0, 2, 4, 5, 7, 9, 11])
    assert s.get(0) == 0
    assert s.get(2) == 4
    assert s.get(7) == 12    # degree 7 wraps to the next octave
    assert s.get(8) == 14
    assert iso.Scale([0, 2, 3, 5, 7, 8, 10]).get(7) == 12


def test_chord():
    """Chord exposes intervals, root and the resulting absolute semitones."""
    c = iso.Chord([3, 4, 3])
    assert c.intervals == [3, 4, 3]
    assert c.root == 0
    assert c.semitones == [0, 3, 7, 10]
    c = iso.Chord([3, 4, 3], root=3)
    assert c.semitones == [3, 6, 10, 13]


# --------------------------------------------------------------------------
# Note / frequency utilities
# --------------------------------------------------------------------------

def test_note_name_roundtrip():
    """MIDI numbers convert to/from note names with octave numbering (C4 = 60)."""
    assert iso.midi_note_to_note_name(60) == "C4"
    assert iso.midi_note_to_note_name(61) == "C#4"
    assert iso.midi_note_to_note_name(58) == "A#3"
    assert iso.note_name_to_midi_note("C4") == 60
    assert iso.note_name_to_midi_note("C#4") == 61
    assert iso.note_name_to_midi_note("Db4") == 61


def test_frequency_midi_conversion():
    """Frequency<->MIDI conversions agree on concert pitch (A4 = 440 Hz = MIDI 69)."""
    assert iso.midi_note_to_frequency(69) == pytest.approx(440.0)
    assert iso.midi_note_to_frequency(60) == pytest.approx(261.6255653005986)
    assert iso.frequency_to_midi_note(440) == pytest.approx(69)


# --------------------------------------------------------------------------
# Timeline scheduling
# --------------------------------------------------------------------------

def test_timeline_schedule_note_events(dummy_timeline):
    """Scheduling a note pattern emits note_on/note_off events at the right beats."""
    dummy_timeline.schedule({iso.EVENT_NOTE: iso.PSequence([1], 1)})
    dummy_timeline.run()
    events = dummy_timeline.output_device.events
    assert events[0] == [pytest.approx(0.0), "note_on", 1, 64, 0]
    assert events[1] == [pytest.approx(1.0), "note_off", 1, 0]


def test_timeline_tempo_and_stop_when_done():
    """Timeline carries tempo, advances one tick per tick(), and can stop when empty."""
    timeline = iso.Timeline(100, output_device=DummyOutputDevice())
    assert timeline.clock_source.tempo == pytest.approx(100)
    timeline.tick()
    assert timeline.current_time == pytest.approx(1.0 / iso.DEFAULT_TICKS_PER_BEAT)
    timeline.stop_when_done = True
    with pytest.raises(StopIteration):
        timeline.tick()


def test_timeline_event_degree_transpose(dummy_timeline):
    """A degree event resolves through the key, applies transpose, and honours duration."""
    dummy_timeline.schedule({
        iso.EVENT_DEGREE: iso.PSequence([0, 1, 2, 3, None, 7, -1], 1),
        iso.EVENT_DURATION: 1.0,
        iso.EVENT_TRANSPOSE: 12,
    })
    dummy_timeline.run()
    assert dummy_timeline.output_device.events == [
        [pytest.approx(0), "note_on", 12, 64, 0], [pytest.approx(1), "note_off", 12, 0],
        [pytest.approx(1), "note_on", 14, 64, 0], [pytest.approx(2), "note_off", 14, 0],
        [pytest.approx(2), "note_on", 16, 64, 0], [pytest.approx(3), "note_off", 16, 0],
        [pytest.approx(3), "note_on", 17, 64, 0], [pytest.approx(4), "note_off", 17, 0],
        [pytest.approx(5), "note_on", 24, 64, 0], [pytest.approx(6), "note_off", 24, 0],
        [pytest.approx(6), "note_on", 11, 64, 0], [pytest.approx(7), "note_off", 11, 0],
    ]


def test_timeline_event_octave(dummy_timeline):
    """An octave event shifts a note event by whole octaves (12 semitones each)."""
    dummy_timeline.schedule({
        iso.EVENT_NOTE: iso.PSequence([0, 1, 2, 3], 1),
        iso.EVENT_DURATION: 1.0,
        iso.EVENT_OCTAVE: iso.PSequence([2, 4]),
    })
    dummy_timeline.run()
    assert dummy_timeline.output_device.events == [
        [pytest.approx(0), "note_on", 24, 64, 0], [pytest.approx(1), "note_off", 24, 0],
        [pytest.approx(1), "note_on", 49, 64, 0], [pytest.approx(2), "note_off", 49, 0],
        [pytest.approx(2), "note_on", 26, 64, 0], [pytest.approx(3), "note_off", 26, 0],
        [pytest.approx(3), "note_on", 51, 64, 0], [pytest.approx(4), "note_off", 51, 0],
    ]


def test_plsystem():
    """PLSystem expands a Lindenmayer rule into a deterministic sequence of pitch offsets."""
    assert list(iso.PLSystem("N[-N++N]-N", 1)) == [0, -1, 1, -1]
    assert list(iso.PLSystem("N[-N++N]-N", 2)) == \
        [0, -1, 1, -1, -2, -3, -1, -3, -1, -2, 0, -2, -2, -3, -1, -3]


def test_pmarkov_deterministic():
    """PMarkov learns transitions from a sequence; a fixed seed replays a fixed walk."""
    training = [1, 1, 2, 3, 1]
    # Learned transition table: for each value, the multiset of values that followed it.
    transitions = {}
    for prev, cur in zip(training, training[1:]):
        transitions.setdefault(prev, []).append(cur)
    a = iso.PMarkov(training)
    a.seed(0)
    seq = a.nextn(16)
    # Every emitted value is a known state, and every step is a legal transition
    # under the learned table (the start state has no predecessor to constrain it).
    assert all(v in transitions for v in seq)
    assert all(cur in transitions[prev] for prev, cur in zip(seq, seq[1:]))
    # reset() replays the same seeded sequence.
    a.reset()
    assert a.nextn(16) == seq
    # Identical seed -> identical sequence.
    b = iso.PMarkov(training)
    b.seed(0)
    assert b.nextn(16) == seq
