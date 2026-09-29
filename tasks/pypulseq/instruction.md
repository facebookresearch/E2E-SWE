# pypulseq

I'd like you to build `pypulseq`, a Python toolkit for *describing* MRI pulse sequences. If
you haven't worked with MRI before: a pulse sequence is a precisely-timed list of events —
radio-frequency (RF) pulses, gradient waveforms on the x/y/z axes, and analog-to-digital
(ADC) readout windows — that a scanner plays out to acquire an image. pypulseq lets someone
assemble those events in Python, glue them into a sequence block by block, sanity-check the
timing, and write the whole thing out to a `.seq` file (and read one back). The file format
and conventions are fixed by an external standard, the MATLAB "Pulseq" framework — we have to
match them exactly.

The thing to internalize before anything else: **pypulseq works in SI-ish hardware units, and
internally everything gradient-related is in Hz/m.** Gradient amplitudes are Hz/m, gradient
areas are 1/m (Hz/m · s), slew rates are Hz/m/s, and RF is in Hz (γB₁). Users can *input*
friendlier units (mT/m, T/m/s) but you convert to Hz/m on the way in. Getting a γ conversion
wrong breaks every downstream number, so this is the first thing to nail.

Target Python is 3.8+. The public import name is `pypulseq` (people usually do
`import pypulseq as pp`).

## Dependencies

The environment is **offline**: all dependencies are already installed and the project itself is
installed for you by a `setup.sh` that runs offline (an editable install against the pre-baked
packages). **Do not install anything** — there is no network, and you must not add the target
package. The runtime libraries available to you are:

- `numpy`, `scipy` — the numerics (scipy is used for things like the piecewise-polynomial
  k-space trajectories).
- `matplotlib` — used by `Sequence.plot`.
- `coverage` — a declared runtime dependency; you do not need to use it directly.

## Package layout and the public surface

All the user-facing names must be importable straight off the top-level `pypulseq` package,
e.g. `from pypulseq import make_trapezoid, Opts, calc_duration, Sequence`. Organize the internal
modules however you like. The top-level package should also expose two odds and ends that other
modules rely on: a `round_half_up(n, decimals=0)` helper and a module-level constant **`eps`**.

About `eps`: this is pypulseq's global numeric tolerance and it is **`1e-9`**, *not* machine
epsilon. Every "is this amplitude/slew/area within limits" check uses it (`value > limit +
eps`, or `> limit * (1 + eps)`). If you reach for `np.finfo(float).eps` you'll get spurious
limit violations — use `1e-9`.

## System limits: the `Opts` class

`Opts` holds the scanner's hardware limits and raster (clock) times.
Pretty much every constructor below takes a `system: Opts` and falls back to a shared default
when it's not given. Constructor — every numeric argument defaults to `None`, meaning "use the
global default value"; the unit arguments default to strings:

```
Opts(adc_dead_time=None, adc_raster_time=None, block_duration_raster=None, gamma=None,
     grad_raster_time=None, grad_unit='Hz/m', max_grad=None, max_slew=None,
     rf_dead_time=None, rf_raster_time=None, rf_ringdown_time=None, adc_samples_limit=None,
     adc_samples_divisor=None, rise_time=None, slew_unit='Hz/m/s', B0=None)
```

The canonical default values (these matter — tests build events against a default system and
check exact numbers):

| field | default | unit |
|---|---|---|
| `max_grad` | 40 mT/m converted to Hz/m (≈ `1703040.0`) | Hz/m |
| `max_slew` | 170 T/m/s converted to Hz/m/s (≈ `7.238e9`) | Hz/m/s |
| `rf_dead_time` | `0` | s |
| `rf_ringdown_time` | `0` | s |
| `adc_dead_time` | `0` | s |
| `adc_raster_time` | `100e-9` | s |
| `rf_raster_time` | `1e-6` | s |
| `grad_raster_time` | `10e-6` | s |
| `block_duration_raster` | `10e-6` | s |
| `adc_samples_limit` | `0` (0 = no limit) | — |
| `adc_samples_divisor` | `4` | — |
| `gamma` | `42576000` (¹H) | Hz/T |
| `B0` | `1.5` | T |

Behavior to implement:

- `max_grad`/`max_slew`, when supplied, are converted **from `grad_unit`/`slew_unit` into
  Hz/m** using `gamma`. Provide a `convert(value, from_unit, gamma=..., to_unit='')` helper
  that knows the standard conversions (mT/m → Hz/m is `×1e-3×gamma`; T/m/s and mT/m/ms → Hz/m/s
  is `×gamma`; etc.). Reject unknown units with `ValueError`.
- If `rise_time` is given it overrides slew: `max_slew = max_grad / rise_time`.
- There's a **process-global default system**: a class-level `Opts.default` singleton, built at
  import. `make_*`/`calc_*` functions fall back to `Opts.default` when `system is None`. An
  instance method `set_as_default()` replaces that singleton, and a classmethod
  `reset_default()` rebuilds the canonical one. (Heads-up: `Sequence()` with no system uses a
  *fresh* `Opts()` rather than the singleton — a small but real asymmetry.)

## Building events: the `make_*` constructors

Each event constructor returns a `types.SimpleNamespace` carrying a `.type` string plus the
fields below, and takes a `system=None` (falling back to `Opts.default`). I'll describe the
ones the tests exercise hardest; keep the rest faithful to the same patterns.

### Gradients

`make_trapezoid(channel, amplitude=None, area=None, flat_area=None, flat_time=None,
duration=None, rise_time=None, fall_time=None, delay=0, max_grad=None, max_slew=None,
system=None)` is the big one. `delay` (default `0`) is stored verbatim on the returned event's
`.delay`; it is *not* validated at construction — a negative delay is allowed here and is
instead surfaced later by `Sequence.check_timing()` as a `NEGATIVE_DELAY` error. `channel` is `'x'`, `'y'`, or `'z'` (anything else → `ValueError`). The caller
specifies the gradient one of three ways — by `amplitude`, by total `area`, or by `flat_area`
— and you derive the rest:

- Exactly one of those three drives the calculation. Supplying conflicting pairs (amplitude
  +area, flat_area+amplitude, flat_area+duration) should raise `NotImplementedError`;
  supplying none of the three raises `ValueError("Must supply either 'area', 'flat_area' or
  'amplitude'.")`.
- `rise_time` and `fall_time` default to each other when only one is given. When the inputs
  fix the amplitude directly (amplitude- or flat-area-specified, no `rise_time`), the ramp time
  is the shortest gradient raster that keeps the ramp slew within `max_slew`:
  `rise = fall = ceil((|amplitude| / max_slew) / grad_raster) * grad_raster`, with a minimum of
  one raster. When `|amplitude| / max_slew` is small relative to a raster (the common case with
  the default system) this rounds up to a single raster (e.g. `flat_time=1, amplitude=1` →
  `rise=fall=1e-5`); under a tight `max_slew` it lengthens instead so the ramp stays realizable
  (e.g. `amplitude=10, duration=13, max_grad=30, max_slew=200` → `rise=fall=0.05`, since
  `10/200 = 0.05`). The amplitude/slew validation below is applied only *after* this ramp time
  is fixed.
- The area-only case picks the *shortest* trapezoid (or triangle) that achieves the area
  within the slew/grad limits, with ramps quantized **up** to the gradient raster (`ceil(t /
  grad_raster) * grad_raster`, at least one raster). Area+duration, area+duration+rise_time,
  and area+flat_time+rise_time are the other supported sub-cases.
- For the **area+duration** sub-case (both `area` and `duration` given, no `rise_time`) the
  ramp is *not* derived from the amplitude rule above — the amplitude is unknown up front, so
  the symmetric ramp is fixed from the requested **area** (as in the area-only case) rather
  than from a provisional amplitude, and the amplitude then follows from the `.area` relation
  below.
- Validate the final amplitude ≤ `max_grad + eps` and both ramps' slew ≤ `max_slew*(1+eps)`,
  raising `ValueError` otherwise.
- Returned namespace: `.type='trap'`, `.channel`, `.amplitude`, `.rise_time`, `.flat_time`,
  `.fall_time`, `.delay`, `.first=0`, `.last=0`, and two derived areas —
  **`.area = amplitude*(flat_time + rise_time/2 + fall_time/2)`** and
  `.flat_area = amplitude*flat_time`. That half-ramp area formula is easy to get wrong.

Some exact cases against the default system, so you can self-check: `make_trapezoid('x',
amplitude=1, duration=1)` → rise `1e-5`, flat `1-2e-5`, fall `1e-5`. `make_trapezoid('x',
area=1)` (a triangle) → amplitude `50000`, rise `2e-5`, flat `0`, fall `2e-5`.
`make_trapezoid('x', area=1, duration=1)` → amplitude `1.00002`.

For free-form gradients there's `make_arbitrary_grad(channel, waveform, ...)` (type `'grad'`,
with `.waveform`, `.tt` sample-center times, `.shape_dur`, `.area`, `.first`, `.last`),
`make_extended_trapezoid(channel, amplitudes, times, ...)` (piecewise-linear gradient through
given points), and `make_extended_trapezoid_area(area, channel, grad_start, grad_end, ...)`.
A note on `make_extended_trapezoid`'s representation: by default it keeps the points you pass
verbatim — `.waveform` is exactly the input `amplitudes` array (so `.waveform[0]` is the first
amplitude point and `np.max(.waveform)` is the largest point you gave) and `.tt` are the input
`times` (node times relative to the delay), which are *not* a uniform sample-center grid. This
differs from `make_arbitrary_grad`, whose `.tt` are sample-center times on a uniform raster. In
both cases `.area` is the trapezoidal integral of the piecewise-linear waveform. The
which **returns a 3-tuple** `(grad, times, amplitudes)` — note that one, it's an outlier. Its
first element `grad` is itself an extended-trapezoid gradient event (`.type='grad'`) carrying
`.waveform`, `.tt` (sample-center times), and `.area`, where `.area` equals the requested
`area` and the waveform respects the system's `max_grad`/`max_slew` limits.

### RF pulses

`make_sinc_pulse(flip_angle, duration=4e-3, ...)` and `make_gauss_pulse(...)` build shaped
excitation pulses; `make_block_pulse(flip_angle, duration=None, bandwidth=None, time_bw_product=None, ...)`
builds a hard rectangular pulse. `flip_angle` is in **radians**. Supply exactly one of
`duration` or `bandwidth`: giving both raises `ValueError`, and giving neither falls back to a
4 ms default. `bandwidth` on its own sets `duration = 1 / (4 * bandwidth)`; combined with a
`time_bw_product` it's `duration = time_bw_product / bandwidth`. The returned RF namespace has
`.type='rf'`, `.signal` (complex/real ndarray, in Hz), `.t` (sample times), `.shape_dur`,
`.freq_offset`, `.phase_offset`, `.delay`, `.dead_time`, `.ringdown_time`, `.center`, and a
`.use` string. The signal is scaled so it integrates to the requested flip angle; for a block
pulse that just means a constant amplitude of `flip_angle / (2π) / duration` Hz (so a 1 ms π
pulse peaks at ~500 Hz, a 1 ms π/2 at 250 Hz). `use` must be one of the recognised values
(excitation/refocusing/inversion/saturation/preparation/other/undefined). When a pulse's RF
dead time exceeds its delay, bump the delay up (with a warning). The sinc/gauss makers can
optionally also return a slice-select gradient and its rephaser when `return_gz=True` and a
`slice_thickness` is given — the slice-select `gz` has amplitude `bandwidth / slice_thickness`
(with `bandwidth = time_bw_product / duration`) and `flat_time == duration`.

### ADC and delays

`make_adc(num_samples, duration=0, dwell=0, delay=0, ...)` → `.type='adc'` with
`.num_samples`, `.dwell`, `.delay`, `.dead_time`, offsets, etc. Exactly one of `duration` or
`dwell` must be positive (else `ValueError`); from `duration` you get `dwell =
duration/num_samples` and vice-versa. Like RF, if the system's `adc_dead_time` exceeds the
requested `delay`, the delay is raised to `adc_dead_time`.

`make_delay(d)` → `.type='delay'`, `.delay=d`; raise `ValueError` if `d` is negative or not
finite. Important: when you add events to a sequence, a raw float is **not** an acceptable
delay — callers must wrap it in `make_delay`.

### A couple more

`make_trigger`/`make_digital_output_pulse` (trigger and digital-output events with their own
channel name sets — `make_trigger(channel, delay=0, duration=0, ...)` accepts `'physio1'` or
`'physio2'`, and `make_digital_output_pulse(channel, ...)` accepts `'osc0'`, `'osc1'`, or
`'ext1'`; any other channel raises `ValueError`) and `make_label(label, type, value)`
(sequence labels; `value` is coerced to `int`). For `make_label`, `type='INC'` is only valid on **counter** labels; using it on a
**flag** label (NAV, REV, SMS, REF, IMA, NOISE, PMC, NOROT, NOPOS, NOSCL, ONCE) raises
`ValueError`. A SET label has `.type='labelset'`; an INC label has `.type='labelinc'`.

`make_arbitrary_grad(channel, waveform, ...)` builds a free-form gradient (`.type='grad'`).
Its `.area` is `sum(waveform) * grad_raster_time`, and unless given, `.first`/`.last` are
linearly extrapolated from the edge samples as `0.5 * (3*edge - next)`.

### Gradient combination & geometry helpers

- `add_gradients(grads, system=None)` superposes several same-channel gradients into one
  (amplitudes/waveforms sum); mixing channels raises `ValueError`.
- `rotate(*grads, angle, axis)` rotates gradients about `axis` ('x'/'y'/'z') into the other
  two channels (combining overlaps via `add_gradients`), dropping any component below
  `1e-6 * max_amplitude`; a gradient already on `axis`, and any non-gradient event, passes
  through unchanged. Returns a list. Each rotated component is the original gradient scaled by
  the rotation coefficient (`cos`/`sin` of `angle`) onto a destination channel — consistent with
  `scale_grad`, so a rotated trapezoid that lands alone on a destination channel (nothing to
  superpose there) stays a trapezoid and its rotated magnitude is observable via `.amplitude`
  (e.g. rotating an `amplitude=A` x-trap 90° about z gives a single y-trap with `.amplitude == A`;
  rotating it 45° gives an x-trap and a y-trap each with `.amplitude == A/sqrt(2)`).
- `align(left=[...]` / `center=[...]` / `right=[...])` returns copies of the events with
  `.delay` set so each is left/center/right-aligned within the block whose duration is
  `calc_duration(*events)`.
- `scale_grad(grad, scale, system=None)` returns a copy with amplitude/`flat_area` (trap) or
  waveform/`first`/`last` (arbitrary) scaled by `scale`.

## Timing helper: `calc_duration`

`calc_duration(*events)` → the duration in seconds of the longest event passed in (it's a
`max`, not a sum — events in a block run concurrently). `None` arguments are ignored; no args
→ `0.0`. Per event type the duration is: delay → `.delay`; trap → `delay+rise+flat+fall`; rf →
`delay+shape_dur+ringdown_time`; arbitrary grad → `delay+shape_dur`; adc →
`delay+num_samples*dwell+dead_time`; trigger/output → `delay+duration`. It also accepts a raw
float (treated as a block duration). Quick checks: `calc_duration()` is `0.0`; a 1 s trapezoid
with a 1 s delay is `2.0`; the max of several events is what comes back.

## The `Sequence` class

`Sequence(system=None, use_block_cache=True)` is what users
assemble everything into. The methods that carry the weight:

- `add_block(*events)` — append a new block built from the given events (skip `None`s; reject
  raw floats as noted). Only one event per type per block (two RF, or two gradients on the
  same axis, → error). Internally it computes the block's duration as the max over its events.
  Blocks are 1-indexed.
- `get_block(block_index)` — return a namespace with `.block_duration`, `.rf`, `.gx`, `.gy`,
  `.gz`, `.adc`, `.label`, etc. (each `None` when that slot is empty). Note gradients come back
  as `.gx/.gy/.gz`, not a generic `.grad`.
- `set_definition(key, value)` / `get_definition(key)` — sequence-level metadata. A missing
  key reads back as `''` (empty string), not a `KeyError`. Setting `'FOV'` with any component
  greater than 1 emits a `UserWarning` (the readers expect metres).
- `duration()` — returns `(total_seconds, num_blocks, event_counts)`.
- `check_timing()` — returns `(is_ok, error_report)`. Each report entry is an **object**
  (a `SimpleNamespace`) with `.block`, `.event`, `.field`, and `.error_type` attributes; the
  `.error_type` is one of the strings RASTER, RF_DEAD_TIME, RF_RINGDOWN_TIME,
  BLOCK_DURATION_MISMATCH, NEGATIVE_DELAY, ADC_DEAD_TIME, …. A **RASTER** entry is emitted for
  any event timing that is not an integer multiple of the raster it lives on: an event's
  `delay` and `duration` against its raster (`grad_raster_time` for gradients, `rf_raster_time`
  for RF/ADC start), an ADC `dwell` against `adc_raster_time`, and — for a trapezoid — each of
  its `rise_time`, `flat_time`, and `fall_time` (and hence the total duration) against
  `grad_raster_time`.
- `write(name, ...)` / `read(file_path, ...)` — serialize to and parse from the Pulseq `.seq`
  format. This pair has to **round-trip**: writing a sequence and reading it back must
  reproduce the same blocks (the tests compare block-by-block within ~`1e-5`, compare the
  gradient trajectories, and re-derive k-space within tolerance), so the format details and
  the shape compression have to match the standard. There's also `remove_duplicates()` (dedup
  the shape/gradient libraries) which `write` uses by default.
- `calculate_kspace(...)` — integrate the gradients into a k-space trajectory, returning
  `(k_traj_adc, k_traj, t_excitation, t_refocusing, t_adc)`. K-space is the cumulative
  time-integral of the gradient waveforms (in 1/m, since gradients are Hz/m), so the peak of
  the trajectory along an axis equals that axis's gradient area. The layout is **axis-major**:
  `k_traj` and `k_traj_adc` are arrays of shape `(3, N)` with the three spatial axes (x, y, z)
  as the rows and one column per time sample — `k_traj` spans the whole sequence, while
  `k_traj_adc` has one column per ADC sample (so `k_traj_adc.shape == (3, num_adc_samples)`).
  `t_adc` is a 1-D array of length `num_adc_samples` giving the ADC sample times.
  (`calculate_kspacePP` is a deprecated alias that just warns and forwards here.)
- `plot(...)` — a matplotlib view; it needs to run without throwing, but it's not the focus.

Gradient continuity is enforced when blocks are set: consecutive gradients on the same axis
have to connect (matching amplitude at the seam within `max_slew*grad_raster_time`), the first
gradient of the sequence must start at zero, and a gradient that doesn't end at zero must land
on a block boundary. Violations raise `RuntimeError`. (`make_extended_trapezoid(...,
skip_check=True)` lets you construct a gradient that *starts* non-zero so the Sequence-level
continuity check is what fires.)

## Traps worth repeating

- Everything gradient-related is Hz/m internally; convert input units with γ. RF `.signal` is
  in Hz.
- `eps` is `1e-9`, not machine epsilon — all the limit checks depend on it.
- Raster quantization rounds **up** (`ceil`) to the raster, minimum one raster.
- A trapezoid's `.area` includes the half-ramps: `amplitude*(flat + rise/2 + fall/2)`.
- `make_*`/`calc_*` default to the global `Opts.default` singleton; `Sequence()` defaults to a
  fresh `Opts()`. `set_as_default()` mutates the shared one.
- Delays into `add_block` must be `make_delay(...)` objects, not bare floats (but
  `calc_duration` does accept bare floats).
- Gradients are `.gx/.gy/.gz` on a block; trapezoid type is `'trap'`, arbitrary/extended is
  `'grad'`.
- `get_definition` on a missing key returns `''`.
- `make_extended_trapezoid_area` returns a 3-tuple, not a single event.
