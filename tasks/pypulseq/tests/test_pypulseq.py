"""Behavioral tests for the pypulseq library.

Each test exercises one user-facing contract through the public API: system
limits (Opts), the event constructors (make_trapezoid / make_block_pulse /
make_sinc_pulse / make_adc / make_delay / make_label / make_arbitrary_grad /
make_extended_trapezoid_area), gradient combination helpers (add_gradients,
rotate, align, scale_grad), the calc_duration helper, and assembling /
checking / serialising a Sequence.

Gradient units are Hz/m throughout; the global tolerance pypulseq uses is
`eps == 1e-9`. Note: tests that call Opts.set_as_default() restore the default
with Opts.reset_default() in a finally block to avoid polluting other tests.
"""

import numpy as np
import pytest

import pypulseq as pp
from pypulseq import Opts, eps, make_trapezoid


# --------------------------------------------------------------------------- #
# Opts — system limits & unit handling
# --------------------------------------------------------------------------- #
class TestOpts:
    def test_grad_unit_conversion(self):
        """Supplying max_grad in mT/m converts it to Hz/m using gamma (and 170 T/m/s slew)."""
        o = Opts(max_grad=40, grad_unit="mT/m")
        assert o.max_grad == pytest.approx(1703040.0)
        assert o.gamma == 42576000
        assert o.grad_raster_time == 10e-6

    def test_rise_time_overrides_slew(self):
        """Providing rise_time derives max_slew as max_grad / rise_time."""
        o = Opts(max_grad=40, grad_unit="mT/m", rise_time=1e-4)
        assert o.max_slew == pytest.approx(o.max_grad / 1e-4)

    def test_set_as_default_changes_make_fallback(self):
        """set_as_default() makes subsequent system=None make_* calls use the new limits."""
        try:
            pp.Opts(max_grad=10, grad_unit="mT/m").set_as_default()  # ~425760 Hz/m
            with pytest.raises(ValueError):
                make_trapezoid("x", amplitude=500000, duration=1e-3)  # > new max_grad
        finally:
            pp.Opts.reset_default()


# --------------------------------------------------------------------------- #
# make_trapezoid
# --------------------------------------------------------------------------- #
def _assert_trap(trap, amplitude, rise_time, flat_time, fall_time):
    assert abs(trap.amplitude - amplitude) < eps
    assert abs(trap.rise_time - rise_time) < eps
    assert abs(trap.flat_time - flat_time) < eps
    assert abs(trap.fall_time - fall_time) < eps


class TestMakeTrapezoid:
    def test_amplitude_and_duration(self):
        """amplitude + duration yields ramps at one raster and the remaining flat top."""
        _assert_trap(make_trapezoid("x", amplitude=1, duration=1), 1, 1e-5, 1 - 2e-5, 1e-5)

    def test_flat_time_and_amplitude(self):
        """flat_time + amplitude yields the requested flat top with single-raster ramps."""
        _assert_trap(make_trapezoid("x", flat_time=1, amplitude=1), 1, 1e-5, 1, 1e-5)

    def test_flat_time_and_flat_area(self):
        """flat_time + flat_area derives amplitude = flat_area / flat_time."""
        _assert_trap(make_trapezoid("x", flat_time=1, flat_area=1), 1, 1e-5, 1, 1e-5)

    def test_area_only_is_shortest_triangle(self):
        """area alone produces the shortest triangle achieving that area."""
        _assert_trap(make_trapezoid("x", area=1), 50000, 2e-5, 0, 2e-5)

    def test_area_and_duration(self):
        """area + duration spreads the area across a fixed-duration trapezoid."""
        _assert_trap(make_trapezoid("x", area=1, duration=1), 1.00002, 2e-5, 1 - 4e-5, 2e-5)

    def test_area_duration_and_rise_time(self):
        """area + duration + rise_time honours the explicit ramp time."""
        _assert_trap(make_trapezoid("x", area=1, duration=1, rise_time=0.01), 1 / 0.99, 0.01, 0.98, 0.01)

    def test_flat_time_area_rise_time(self):
        """flat_time + area + rise_time solves amplitude for the combined area."""
        _assert_trap(make_trapezoid("x", flat_time=0.5, area=1, rise_time=0.1), 1 / 0.6, 0.1, 0.5, 0.1)

    def test_area_attribute_includes_half_ramps(self):
        """A trapezoid's .area includes the half-ramp contributions; .flat_area does not."""
        trap = make_trapezoid("x", amplitude=2, flat_time=1e-3, rise_time=1e-4, fall_time=1e-4)
        assert trap.area == pytest.approx(2 * (1e-3 + 1e-4 / 2 + 1e-4 / 2))
        assert trap.flat_area == pytest.approx(2 * 1e-3)
        assert trap.channel == "x"

    def test_invalid_channel_raises(self):
        """A channel other than x/y/z raises ValueError."""
        with pytest.raises(ValueError):
            make_trapezoid(channel="p", area=1)

    def test_missing_area_flatarea_amplitude_raises(self):
        """Supplying none of area/flat_area/amplitude raises ValueError."""
        with pytest.raises(ValueError):
            make_trapezoid(channel="x")

    def test_amplitude_above_max_grad_raises(self):
        """An amplitude beyond max_grad raises ValueError."""
        with pytest.raises(ValueError):
            make_trapezoid(channel="x", amplitude=1e10, duration=1)

    def test_conflicting_inputs_not_implemented(self):
        """Conflicting input pairs raise NotImplementedError."""
        with pytest.raises(NotImplementedError):
            make_trapezoid(channel="x", area=1, amplitude=1)


# --------------------------------------------------------------------------- #
# make_block_pulse
# --------------------------------------------------------------------------- #
class TestMakeBlockPulse:
    def test_default_duration(self):
        """With neither duration nor bandwidth, a block pulse defaults to a 4 ms duration."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rf = pp.make_block_pulse(flip_angle=np.pi)
        assert rf.shape_dur == 4e-3

    def test_duration_sets_shape_duration(self):
        """An explicit duration sets the pulse shape duration."""
        assert pp.make_block_pulse(flip_angle=np.pi, duration=1e-3).shape_dur == 1e-3

    def test_bandwidth_sets_shape_duration(self):
        """A bandwidth alone derives duration = 1 / (4 * bandwidth)."""
        assert pp.make_block_pulse(flip_angle=np.pi, bandwidth=1e3).shape_dur == 1 / (4 * 1e3)

    def test_amplitude_for_flip_angle(self):
        """The constant block amplitude is flip_angle / (2*pi) / duration Hz."""
        assert np.isclose(pp.make_block_pulse(duration=1e-3, flip_angle=np.pi).signal.max(), 500)
        assert np.isclose(pp.make_block_pulse(duration=1e-3, flip_angle=np.pi / 2).signal.max(), 250)
        assert np.isclose(pp.make_block_pulse(duration=2e-3, flip_angle=np.pi / 2).signal.max(), 125)

    def test_bandwidth_and_duration_together_raise(self):
        """Specifying both bandwidth and duration raises ValueError."""
        with pytest.raises(ValueError):
            pp.make_block_pulse(flip_angle=np.pi, duration=1e-3, bandwidth=1e3)

    def test_invalid_use_raises(self):
        """An unrecognised `use` value raises ValueError."""
        with pytest.raises(ValueError):
            pp.make_block_pulse(flip_angle=np.pi, duration=1e-3, use="foo")


# --------------------------------------------------------------------------- #
# make_sinc_pulse
# --------------------------------------------------------------------------- #
class TestMakeSincPulse:
    def test_signal_integrates_to_flip_angle(self):
        """The pulse signal is scaled so its integral equals the requested flip angle."""
        rf = pp.make_sinc_pulse(flip_angle=np.pi / 2, duration=2e-3, freq_offset=100, phase_offset=0.5)
        assert rf.type == "rf"
        assert rf.shape_dur == pytest.approx(2e-3)
        assert rf.freq_offset == 100
        dwell = rf.t[1] - rf.t[0]
        recovered = np.abs(np.sum(rf.signal) * dwell * 2 * np.pi)
        assert recovered == pytest.approx(np.pi / 2, rel=1e-3)

    def test_slice_select_gz_amplitude(self):
        """With return_gz + slice_thickness, gz amplitude = (time_bw_product/duration)/slice_thickness."""
        rf, gz, gzr = pp.make_sinc_pulse(
            flip_angle=np.pi / 2, duration=2e-3, slice_thickness=5e-3, time_bw_product=4, return_gz=True
        )
        assert rf.type == "rf"
        assert gz.type == "trap"
        bandwidth = 4 / 2e-3  # 2000 Hz
        assert gz.amplitude == pytest.approx(bandwidth / 5e-3)  # 400000 Hz/m
        assert gz.flat_time == pytest.approx(2e-3)


# --------------------------------------------------------------------------- #
# make_adc / make_delay / make_label
# --------------------------------------------------------------------------- #
class TestSimpleEvents:
    def test_adc_dwell_from_duration(self):
        """make_adc with a duration derives dwell = duration / num_samples."""
        adc = pp.make_adc(num_samples=64, duration=3.2e-3)
        assert adc.type == "adc"
        assert adc.dwell == pytest.approx(3.2e-3 / 64)

    def test_adc_requires_dwell_or_duration(self):
        """make_adc with neither dwell nor duration raises ValueError."""
        with pytest.raises(ValueError):
            pp.make_adc(num_samples=64)

    def test_adc_delay_bumped_to_dead_time(self):
        """When adc_dead_time exceeds the requested delay, delay is raised to dead_time."""
        sys = pp.Opts(adc_dead_time=10e-6)
        adc = pp.make_adc(num_samples=64, duration=3.2e-3, delay=0, system=sys)
        assert adc.delay == pytest.approx(10e-6)

    def test_delay_rejects_negative(self):
        """make_delay raises ValueError on a negative duration; a valid delay carries its value."""
        assert pp.make_delay(1.5).delay == 1.5
        with pytest.raises(ValueError):
            pp.make_delay(-1.0)

    def test_label_value_coerced_to_int(self):
        """make_label coerces its value to an int (SET label)."""
        label = pp.make_label(label="SLC", type="SET", value=2.0)
        assert label.value == 2
        assert isinstance(label.value, int)

    def test_label_inc_rejected_on_flag(self):
        """type='INC' is rejected for flag labels but allowed (as 'labelinc') for counters."""
        with pytest.raises(ValueError):
            pp.make_label(label="NAV", type="INC", value=1)
        assert pp.make_label(label="LIN", type="INC", value=1).type == "labelinc"


# --------------------------------------------------------------------------- #
# calc_duration
# --------------------------------------------------------------------------- #
class TestCalcDuration:
    def test_trapezoid_duration(self):
        """A 1 s trapezoid has a 1 s duration (within the global eps tolerance)."""
        # The trap duration is the float sum delay+rise+flat+fall of raster-quantized
        # components (rise=fall=1e-5, flat=1-2e-5); its last ULP is not pinned, so compare
        # within the library's declared eps=1e-9 rather than bit-exactly.
        assert pp.calc_duration(make_trapezoid("x", amplitude=1, duration=1)) == pytest.approx(1, abs=eps)

    def test_delay_duration(self):
        """A delay event's duration is its delay value."""
        assert pp.calc_duration(pp.make_delay(1)) == 1

    def test_adc_duration(self):
        """An ADC's duration spans its sampling window."""
        assert pp.calc_duration(pp.make_adc(duration=3, num_samples=1)) == 3

    def test_trigger_duration(self):
        """A trigger event's duration is delay + duration."""
        assert pp.calc_duration(pp.make_trigger("physio1", duration=59)) == 59

    def test_max_over_events_ignoring_none(self):
        """For several concurrent events (and None), calc_duration returns the longest; empty/None is 0.0."""
        trap = make_trapezoid("x", amplitude=1, duration=1)
        assert pp.calc_duration(trap, None, pp.make_delay(2)) == 2
        assert pp.calc_duration() == 0.0
        assert pp.calc_duration(None) == 0.0

    def test_accepts_raw_float_block_duration(self):
        """calc_duration treats a bare float as a block duration (unlike add_block)."""
        assert pp.calc_duration(5e-3) == 5e-3


# --------------------------------------------------------------------------- #
# Sequence
# --------------------------------------------------------------------------- #
class TestSequence:
    def _simple_seq(self):
        seq = pp.Sequence()
        seq.add_block(pp.make_block_pulse(flip_angle=np.pi / 2, duration=1e-3))
        seq.add_block(make_trapezoid("x", area=1000, duration=1e-3))
        seq.add_block(pp.make_adc(num_samples=64, duration=3.2e-3))
        seq.add_block(pp.make_delay(1e-3))
        return seq

    def test_add_block_and_get_block_roundtrip(self):
        """A gradient added via add_block comes back from get_block on the right channel, unchanged."""
        grad = make_trapezoid("x", area=1000, duration=1e-3)
        seq = pp.Sequence()
        seq.add_block(grad)
        block = seq.get_block(1)
        assert block.gx is not None
        assert block.gx.channel == "x"
        # Pin the stored gradient to the one added, not just its presence on the x slot.
        assert block.gx.area == pytest.approx(grad.area)
        assert block.gx.flat_area == pytest.approx(grad.flat_area)

    def test_add_block_rejects_raw_float(self):
        """Passing a bare float (instead of make_delay) to add_block raises."""
        seq = pp.Sequence()
        with pytest.raises(Exception):
            seq.add_block(1.0)

    def test_definitions_roundtrip_and_missing_default(self):
        """set/get_definition round-trips a value; a missing key reads back as ''."""
        seq = pp.Sequence()
        seq.set_definition("Name", "demo")
        assert seq.get_definition("Name") == "demo"
        assert seq.get_definition("DoesNotExist") == ""

    def test_set_definition_fov_warns_above_one_meter(self):
        """A FOV definition exceeding 1 metre emits a warning."""
        seq = pp.Sequence()
        with pytest.warns(UserWarning):
            seq.set_definition("FOV", [0.25, 0.25, 5.0])

    def test_duration_reports_total_and_block_count(self):
        """Sequence.duration returns total seconds and the block count."""
        seq = self._simple_seq()
        total, n_blocks, _ = seq.duration()
        assert n_blocks == 4
        assert total == pytest.approx(1e-3 + 1e-3 + 3.2e-3 + 1e-3)

    def test_check_timing_passes_for_clean_sequence(self):
        """check_timing reports OK for a raster-aligned sequence."""
        seq = self._simple_seq()
        is_ok, errors = seq.check_timing()
        assert is_ok is True

    def test_write_read_roundtrip(self, tmp_path):
        """Writing a sequence and reading it back reproduces block count, duration, and each gradient."""
        seq = self._simple_seq()
        path = str(tmp_path / "demo.seq")
        seq.write(path)
        seq2 = pp.Sequence()
        seq2.read(path)
        assert seq2.duration()[1] == seq.duration()[1]  # num_blocks survives the round-trip
        assert seq2.duration()[0] == pytest.approx(seq.duration()[0], abs=1e-6)
        # The gradient in block 2 must survive shape compression, not just the block count/duration.
        g_out = seq2.get_block(2).gx
        assert g_out is not None
        assert g_out.area == pytest.approx(seq.get_block(2).gx.area, rel=1e-5)

    def test_one_event_per_type_per_block(self):
        """Two gradients on the same channel in one block is rejected."""
        seq = pp.Sequence()
        with pytest.raises(Exception):
            seq.add_block(
                make_trapezoid("x", area=1, duration=1e-3),
                make_trapezoid("x", area=1, duration=1e-3),
            )


# --------------------------------------------------------------------------- #
# Advanced gradients & timing checks
# --------------------------------------------------------------------------- #
class TestAdvancedGradients:
    def test_extended_trapezoid_area_returns_triple_and_matches_area(self):
        """make_extended_trapezoid_area returns (grad, times, amplitudes) and hits the area within limits."""
        system = pp.Opts()
        for grad_start, grad_end, area in [(0, 0, 100), (-1000, 1000, 100), (0, system.max_grad, 10000)]:
            g, times, amps = pp.make_extended_trapezoid_area(
                channel="x", grad_start=grad_start, grad_end=grad_end, area=area, system=system
            )
            assert g.area == pytest.approx(area)
            assert np.all(np.abs(g.waveform) <= system.max_grad)
            # "Within limits" is the library's eps=1e-9 convention, not a bit-exact bound: a ramp
            # designed at exactly max_slew re-derives to a few ULP above it here, since
            # (max_slew * grad_raster_time) / grad_raster_time > max_slew in IEEE-754.
            assert np.all(np.abs(np.diff(g.waveform) / np.diff(g.tt)) <= system.max_slew * (1 + 1e-9))

    def test_arbitrary_grad_extrapolation_and_area(self):
        """make_arbitrary_grad linearly extrapolates first/last and integrates .area."""
        wf = np.array([0.0, 100.0, 200.0, 300.0])
        g = pp.make_arbitrary_grad("x", waveform=wf)
        assert g.type == "grad"
        assert g.first == pytest.approx(0.5 * (3 * 0 - 100))   # -50.0
        assert g.last == pytest.approx(0.5 * (3 * 300 - 200))  # 350.0
        assert g.area == pytest.approx(wf.sum() * 1e-5)        # 600 * 1e-5

    def test_scale_grad_scales_trapezoid(self):
        """scale_grad scales a trapezoid's amplitude and flat_area by the factor."""
        trap = make_trapezoid("x", amplitude=10, duration=13, max_grad=30, max_slew=200)
        scaled = pp.scale_grad(trap, 0.5, pp.Opts(max_grad=40, max_slew=300))
        assert scaled.amplitude == pytest.approx(trap.amplitude * 0.5)
        assert scaled.flat_area == pytest.approx(trap.flat_area * 0.5)

    def test_add_gradients_superposes_amplitudes(self):
        """add_gradients superposes same-channel gradients (combined area = sum of areas)."""
        g1 = make_trapezoid("x", amplitude=1000, rise_time=1e-4, flat_time=1e-3, fall_time=1e-4)
        g2 = make_trapezoid("x", amplitude=2500, rise_time=1e-4, flat_time=1e-3, fall_time=1e-4)
        g = pp.add_gradients([g1, g2])
        assert g.area == pytest.approx(g1.area + g2.area)

    def test_rotate_90deg_moves_x_to_y(self):
        """Rotating an x-gradient 90 deg about z yields a single y-gradient of equal magnitude."""
        gx = make_trapezoid("x", amplitude=1000, rise_time=1e-4, flat_time=1e-3, fall_time=1e-4)
        out = pp.rotate(gx, angle=np.pi / 2, axis="z")
        ys = [g for g in out if getattr(g, "channel", None) == "y"]
        assert len(ys) == 1
        assert abs(ys[0].amplitude) == pytest.approx(1000, rel=1e-3)

    def test_align_right_pads_shorter_event(self):
        """align(right=...) delays the shorter event so it ends with the longest."""
        long = pp.make_delay(2e-3)
        short = make_trapezoid("x", area=1, duration=1e-3)
        a_long, a_short = pp.align(right=[long, short])
        assert a_short.delay == pytest.approx(2e-3 - 1e-3)

    def test_align_center_centers_shorter_event(self):
        """align(center=...) delays the shorter event so it is centered within the block."""
        long = pp.make_delay(4e-3)
        short = make_trapezoid("x", area=1, duration=1e-3)
        a_long, a_short = pp.align(center=[long, short])
        # leading delay = (block_dur - event_dur) / 2 = (4e-3 - 1e-3) / 2
        assert a_short.delay == pytest.approx(1.5e-3)

    def test_extended_trapezoid_through_points(self):
        """make_extended_trapezoid builds a piecewise-linear gradient through the given points; .area integrates it."""
        amps = np.array([0.0, 5000.0, 5000.0, 0.0])
        times = np.array([0.0, 1e-4, 3e-4, 4e-4])
        g = pp.make_extended_trapezoid("x", amplitudes=amps, times=times)
        assert g.type == "grad"
        assert g.waveform[0] == pytest.approx(0.0)
        assert np.max(g.waveform) == pytest.approx(5000.0)
        # trapezoidal integral of the piecewise-linear waveform: 0.25 + 1.0 + 0.25
        assert g.area == pytest.approx(1.5)

    def _timing_system(self):
        return pp.Opts(max_grad=28, grad_unit="mT/m", max_slew=200, slew_unit="T/m/s",
                       rf_ringdown_time=20e-6, rf_dead_time=100e-6, adc_dead_time=10e-6)

    def test_check_timing_flags_off_raster_event(self):
        """check_timing reports a RASTER error for an off-raster gradient duration."""
        system = self._timing_system()
        seq = pp.Sequence(system=system)
        seq.add_block(make_trapezoid(channel="x", area=1, duration=1.00001e-3, system=system))
        is_ok, report = seq.check_timing()
        assert is_ok is False
        assert any(e.error_type == "RASTER" for e in report)

    def test_check_timing_flags_negative_delay(self):
        """check_timing reports a NEGATIVE_DELAY error for a negatively-delayed gradient."""
        system = self._timing_system()
        seq = pp.Sequence(system=system)
        seq.add_block(make_trapezoid(channel="x", area=1, duration=1e-3, delay=-1e-5, system=system))
        is_ok, report = seq.check_timing()
        assert is_ok is False
        assert any(e.error_type == "NEGATIVE_DELAY" for e in report)

    def test_consecutive_gradients_must_connect(self):
        """A second-block gradient that doesn't continue the first block's end amplitude raises."""
        seq = pp.Sequence()
        seq.add_block(make_trapezoid("x", area=1000, duration=1e-3))  # ends at 0
        g2 = pp.make_extended_trapezoid(
            "x", amplitudes=np.array([5e5, 5e5, 0]), times=np.array([0, 2e-4, 3e-4]), skip_check=True
        )  # starts at 5e5, far from 0
        with pytest.raises(RuntimeError):
            seq.add_block(g2)

    def test_rotate_45deg_splits_into_two_channels(self):
        """Rotating an x-gradient 45 deg about z splits it into equal x and y components (amp/sqrt(2) each)."""
        gx = make_trapezoid("x", amplitude=1000, rise_time=1e-4, flat_time=1e-3, fall_time=1e-4)
        out = pp.rotate(gx, angle=np.pi / 4, axis="z")
        xs = [g for g in out if getattr(g, "channel", None) == "x"]
        ys = [g for g in out if getattr(g, "channel", None) == "y"]
        assert len(xs) == 1 and len(ys) == 1
        assert abs(xs[0].amplitude) == pytest.approx(1000 / np.sqrt(2), rel=1e-3)
        assert abs(ys[0].amplitude) == pytest.approx(1000 / np.sqrt(2), rel=1e-3)

    def test_calculate_kspace_integrates_gradient_area(self):
        """k-space is the running integral of the gradient: peak kx equals the gradient area, off-axes stay zero."""
        seq = pp.Sequence()
        g = make_trapezoid("x", area=2000, duration=2e-3)  # starts and ends at zero
        adc = pp.make_adc(num_samples=8, duration=2e-3)
        seq.add_block(g, adc)
        k_traj_adc, k_traj, t_excitation, t_refocusing, t_adc = seq.calculate_kspace()
        k_traj_adc = np.asarray(k_traj_adc)
        k_traj = np.asarray(k_traj)
        assert k_traj_adc.shape == (3, 8)  # one column per ADC sample, x/y/z rows
        assert np.asarray(t_adc).shape == (8,)
        assert np.max(k_traj[0]) == pytest.approx(g.area, rel=1e-4)  # kx integral reaches the gradient area
        assert np.allclose(k_traj[1], 0.0) and np.allclose(k_traj[2], 0.0)  # nothing on y/z
