# mapillary_tools — telemetry decode + geo interpolation + sequence splitting

## Overview

`mapillary_tools` is a Python package that processes geotagged images and dashcam/action-cam
videos for the Mapillary street-level imagery platform. Your job is to implement the
**telemetry-decode + geo-interpolation + sequence-splitting subsystem** of the package as an
importable Python library named `mapillary_tools`. This subsystem reads GPS/IMU telemetry out of
several camera video formats (Google **CAMM**, GoPro **GPMF**, **BlackVue** NMEA-in-MP4),
interpolates/resamples GPS tracks, and groups a folder of geotagged images (or videos) into clean
"sequences" by applying split/dedup/zigzag/speed checks.

Everything here is pure-Python and deterministic — no network, no external binaries (no
ffmpeg/exiftool), no on-disk binary fixtures. Tests build their inputs in memory, including
round-tripping a CAMM telemetry track through an MP4 build → parse cycle, so the MP4 box
build/parse machinery and the CAMM track builder must be implemented as well (details below).

Build the package so it is installable with `pip install -e .` and importable as
`mapillary_tools`. The import surface below is a hard contract: callers import these exact module
paths and names, so the package layout and public names must match exactly.

### Runtime dependencies (already installed — the environment is offline)

These packages are **already installed** in the environment, which is **offline** — do **not** try to
install anything (there is no network). The project is installed for you by a `setup.sh` that runs
offline (an editable `pip install -e . --no-build-isolation` against the pre-installed deps), so just
write a standard `pyproject.toml` / `setup.py` and let it be installed. The runtime deps available are:

- `construct~=2.10.0` — declarative binary-struct library; the MP4 box grammar and the CAMM
  sample structs are built on it.
- `pynmea2>=1.12.0,<2.0.0` — parses NMEA sentences (`$GPGGA`, `$GPRMC`, `$GNGLL`, …) for BlackVue.
- `typing_extensions` — `TypeIs` and friends.

- `exifread` and `piexif` — read/write image EXIF. `exif_read` parses image GPS/time/orientation
  tags; the image-geotag test builds an in-memory JPEG with `piexif` and reads it back, so both
  must be installed.

(Other package deps such as `gpxpy`, `jsonschema`, `requests`, `tqdm`, `appdirs`, and `humanize` are
also pre-installed and may be needed for the full package to import cleanly even though the bulk of
the EXIF/upload/ffmpeg halves are out of scope; use whatever your package's `__init__` chain
transitively imports — they are all already available offline.)

---

## Required modules and public names (import contract — must match exactly)

- `mapillary_tools.geo` — `Point`, `gps_distance`, `compute_bearing`, `diff_bearing`,
  `avg_speed`, `pairwise`, `as_unix_time`, `Interpolator`, `sample_points_by_distance`,
  `interpolate_directions_if_none`.
- `mapillary_tools.telemetry` — `GPSFix`, `GPSPoint`, `CAMMGPSPoint`, `GyroscopeData`,
  `AccelerationData`, `MagnetometerData`, `TimestampedMeasurement`.
- `mapillary_tools.types` — `FileType`, `ImageMetadata`, `VideoMetadata`, `ErrorMetadata`,
  `group_and_sort_images`, `update_sequence_md5sum`, `separate_errors`.
- `mapillary_tools.exceptions` — the exception hierarchy (see below).
- `mapillary_tools.process_sequence_properties` — `process_sequence_properties`,
  `split_sequence_by`, `duplication_check`.
- `mapillary_tools.camm.camm_parser` — `extract_camm_info`, `elst_entry_to_seconds`, `CAMMInfo`.
- `mapillary_tools.camm.camm_builder` — `camm_sample_generator2`.
- `mapillary_tools.gpmf.gpmf_parser` — `extract_gopro_info`, `GoProInfo`, and the GPMF KLV
  serialization grammar `GPMFSampleData` (a `construct` `GreedyRange` of KLV structs; tests build
  GPMF sample bytes with `GPMFSampleData.build([...])`).
- `mapillary_tools.gpmf.gpmf_gps_filter` — `remove_noisy_points`, `remove_outliers` (the
  public GPS noise-removal surface the video extractor uses).
- `mapillary_tools.blackvue_parser` — `extract_blackvue_info`, `BlackVueInfo`.
- `mapillary_tools.uploader` — `VideoUploader` with classmethod `prepare_camm_info`.
- `mapillary_tools.upload_api_v4` — `UploadService` and `FakeUploadService` (the offline,
  file-backed upload code path used for testing the resumable byte-stream uploader).
- `mapillary_tools.exif_read` — `ExifRead`, the EXIF reader used by the image-geotag path
  (`extract_lon_lat`, `extract_capture_time`, `extract_altitude`, `extract_direction`,
  `extract_make`, `extract_model`, `extract_width`, `extract_height`, `extract_orientation`).
- `mapillary_tools.geotag.image_extractors.exif` — `ImageEXIFExtractor`, which reads an image's
  EXIF and returns a populated `types.ImageMetadata` (lon/lat/time/altitude/angle/make/model).
- `mapillary_tools.mp4.construct_mp4_parser` — `Box32ConstructBuilder`,
  `Box64ConstructBuilder`, a module-level singleton `MP4WithoutSTBLBuilderConstruct`, the standard
  box-type→switch-map dict `CMAP` (indexable by box type, e.g. `CMAP[b"stbl"]`), and the
  `SwitchMapType` type alias for those switch maps.
- `mapillary_tools.mp4.simple_mp4_builder` — `transform_mp4` (and the `build_mp4` /
  `find_movie_timescale` / `iterate_samples` it relies on), plus
  `build_stbl_from_raw_samples(descriptions, raw_samples)`, which returns the stbl child box-dicts
  describing a list of samples. `descriptions` is a list of sample-description dicts, each shaped
  `{"format": b"...", "data_reference_index": int, "data": bytes}`. `raw_samples` is a list of
  `RawSample` records (the same `mp4_sample_parser.RawSample` type documented below, fields
  `description_idx, offset, size, timedelta, composition_offset, is_sync`) — **not** raw sample
  byte-strings: the returned sample tables are built from those record fields, with each sample's
  size taken from `RawSample.size` and its time-to-sample delta from `RawSample.timedelta` (and
  `description_idx`/`composition_offset`/`is_sync` driving the sample-to-chunk/composition/sync
  tables as needed). The same `RawSample` records flow through `transform_mp4`'s internal stbl
  rebuild.
- `mapillary_tools.mp4.simple_mp4_parser` — `parse_mp4_data_first`, `ParsingError`,
  and the box-locating helpers it needs.
- `mapillary_tools.mp4.mp4_sample_parser` — `MovieBoxParser`, `TrackBoxParser`, `Sample`
  (the stbl→sample-table machinery CAMM parsing reads through), and `RawSample` (a record with
  fields `description_idx, offset, size, timedelta, composition_offset, is_sync`).

Tests import every one of these. Any missing module/name fails test collection.

---

## Data model

### `geo.Point` and telemetry subtypes

`geo.Point` is an ordered dataclass (comparable/sortable by its fields, `time` first) with fields
`time: float`, `lat: float`, `lon: float`, `alt: float | None`, `angle: float | None`. It must be
constructible by keyword (`Point(time=…, lat=…, lon=…, alt=…, angle=…)`). For interpolation it
exposes a polymorphic `interpolate_with(other, t)` that returns a new point of the same concrete
type, and a `get_gps_epoch_time()` that returns `None` on the base class.

`telemetry.GPSFix` is an `Enum` with members `NO_FIX=0`, `FIX_2D=2`, `FIX_3D=3`.

`telemetry.GPSPoint` extends `Point` with extra fields **`epoch_time: float | None`,
`fix: GPSFix | None`, `precision: float | None`, `ground_speed: float | None`** (constructed with
all of `Point`'s fields plus these). `get_gps_epoch_time()` returns `epoch_time` only when it is
not `None` **and `> 0`**, else `None`.

`telemetry.CAMMGPSPoint` extends `Point` with **`time_gps_epoch: float`, `gps_fix_type: int`,
`horizontal_accuracy`, `vertical_accuracy`, `velocity_east`, `velocity_north`, `velocity_up`,
`speed_accuracy`** (all `float`). `get_gps_epoch_time()` returns `time_gps_epoch` when `> 0`.

`GyroscopeData`, `AccelerationData`, `MagnetometerData` are timestamped XYZ measurements
(`time, x, y, z`).

When `interpolate_with` produces a subtype, it must interpolate the subtype-specific numeric
fields linearly by the same time-weight used for lat/lon, **except** the discrete fix field
(`GPSPoint.fix` / `CAMMGPSPoint.gps_fix_type`) which is taken **from the start point**. For
`GPSPoint`, an interpolated `epoch_time` is produced only when both endpoints have a positive
`epoch_time` (otherwise `None`); an interpolated `precision`/`ground_speed` is likewise produced
only when both endpoints have that field set (otherwise `None` — a value present on only one
endpoint is dropped to `None`, not carried through). If
`other` is not the same subtype, fall back to a plain interpolated `Point`.

### `types`

`ImageMetadata` extends `Point` and adds `filename: Path`, plus optional `md5sum`, `width`,
`height`, `filesize`, and the `MAP*` fields including `MAPSequenceUUID`, `MAPDeviceMake`,
`MAPDeviceModel`, `MAPCameraUUID`. It has a `sort_key()` of `(time, filename.name)`.
`VideoMetadata` holds `filename, filetype, points` plus optional `make`, `model`, `filesize`,
`camera_uuid`. `ErrorMetadata` holds `filename, filetype, error`. `FileType` is an enum with at
least `IMAGE`, `VIDEO`, `CAMM`, `BLACKVUE`, `GOPRO`, `ZIP`.

### `exceptions`

A `MapillaryDescriptionError(Exception)` base, with subclasses
`MapillaryDuplicationError`, `MapillaryNullIslandError`, `MapillaryZigZagError`,
`MapillaryCaptureSpeedTooFastError`, `MapillaryFileTooLargeError`, `MapillaryStationaryVideoError`,
(and the others in the package). `MapillaryDuplicationError(message, desc, distance, angle_diff)`
must store `distance` and `angle_diff` as attributes (`angle_diff` may be `None`).

---

## `geo` — distance, bearing, speed, sampling

- `gps_distance((lat1,lon1),(lat2,lon2)) -> float`: WGS84 distance in meters. Compute it via
  ECEF (earth-centered earth-fixed) XYZ conversion using the WGS84 ellipsoid and the Euclidean
  distance between the two ECEF points — this makes lon=+180 and lon=-180 the same meridian
  (distance 0).
- `compute_bearing((lat1,lon1),(lat2,lon2)) -> float`: takes two `(lat, lon)` tuples (same
  argument shape as `gps_distance`) and returns the compass bearing from start to end in compass
  degrees in `[0, 360)`; due north → `0`, east → `90`, south → `180`, west → `270`. Handle the
  antimeridian wrap of the longitude delta.
- `diff_bearing(b1, b2) -> float`: smallest angular difference, always in `[0, 180]`.
- `avg_speed(seq) -> float`: total path distance / total time. Returns `0.0` for sequences of
  length < 2. The time span uses **GPS epoch time** (`get_gps_epoch_time()` of first/last) when
  both endpoints expose a positive epoch; otherwise it falls back to the `time` field. Returns
  `nan` when the chosen time span is exactly zero.
- `sample_points_by_distance(samples, min_distance, point_func) -> generator`: always yields the
  first sample; thereafter yields a sample only when it is **strictly farther** than
  `min_distance` from the last yielded sample (distance via `gps_distance`).
- `interpolate_directions_if_none(sequence) -> None`: mutate in place. For each point whose
  `angle is None`, set it to the bearing toward the **next** point. The last point, if still
  `None`, copies the previous point's angle (a length-1 all-None sequence gets angle `0`).

## `geo.Interpolator`

Construct with `Interpolator(tracks)` where `tracks` is a sequence of point-lists. Behavior:

- Drops empty tracks; raises `ValueError` if **no** non-empty track remains (e.g. `[]` or `[[]]`).
- Raises `ValueError` if any track's points are not non-decreasing in `time`.
- Sorts the surviving tracks by their first point's `time`.
- `interpolate(t) -> Point`: returns the (extra/inter)polated point at time `t`, preserving the
  concrete subtype of the track's points.
  - Query times must be **monotonically non-decreasing** across successive calls; a smaller `t`
    than the previous call raises `ValueError`.
  - **Linearly extrapolates** before the first point (using the first segment) and after the last
    point (using the last segment) — e.g. a track at t=1000/1100 queried at t=900 extrapolates
    backward, at t=1500 extrapolates forward.
  - A single-point track returns that point's coordinates for any `t`.
  - With multiple **overlapping** tracks, it stays within the current track while `t` is within
    that track's span, and only advances to the next track once `t` passes the current track's
    last point — so during an overlap the earlier track wins, and after it ends the later track
    takes over.

---

## MP4 box-dict convention (the shape every builder/parser speaks)

Every box in this subsystem is represented as a dict with exactly two keys:
`{"type": b"xxxx", "data": <...>}`, where `"type"` is the 4-byte box type and `"data"` is
**one of three shapes** depending on the box:

- a **list of child box-dicts** — for *container* boxes (e.g. `moov`, `trak`, `edts`,
  `mdia`, `minf`, `dinf`, `udta`, and the test's `free`). The children are themselves
  `{"type", "data"}` dicts and serialize back-to-back inside the parent's payload.
- a **parsed-field dict** — for *leaf header* boxes that have a fixed field grammar (e.g.
  `mvhd` → `{"creation_time", "modification_time", "timescale", "duration", ...}`, `elst`
  → `{"entries": [...]}`, `mdhd`, `tkhd`, `hdlr`, `dref`/`url `). The dict's keys are the
  box's struct fields (the `dref`/`url ` field grammar — including the nesting of `dref`'s
  entries as `url ` box-dicts — is spelled out at the end of this section). The versioned ISOBMFF header boxes — `mvhd`, `mdhd`, `tkhd`, `elst` —
  carry an **optional `version` field** (`0` or `1`) that widens their date/duration fields:
  under `version == 1`, `creation_time`/`modification_time`/`duration` (and `elst`'s
  `segment_duration`/`media_time`) are **64-bit**, else 32-bit. When the dict omits `version`,
  `mvhd`/`mdhd`/`tkhd` **default to version 1 (64-bit)** — so their `duration` routinely
  exceeds `uint32` (a movie/media duration is `seconds * timescale`, e.g. a multi-hour video at
  a microsecond timescale far exceeds `2**32`) and the grammar must serialize/parse it as a
  64-bit value; `elst` defaults to version 0 (32-bit).
- **raw bytes** — for everything else (e.g. `ftyp`, the BlackVue `gps `/`cprt` payloads, a
  `camm` sample-entry blob).

The builders are driven by a **switch map** keyed on box type: a *dict-valued* entry means
"this is a container — recurse into a nested box list", while a leaf entry maps to the box's
field grammar; any type absent from the map serializes/parses its `data` as raw bytes
(greedy). `Box32ConstructBuilder(switch_map)` exposes `.Box` (serialize one box, descending
into nested children) and `.build_boxlist(boxes)` (serialize a list of sibling boxes);
`Box64ConstructBuilder` is the 64-bit-size sibling used for parsing. The module-level
`MP4WithoutSTBLBuilderConstruct` is a preconfigured 32-bit instance over the standard MP4
box map that does **not** descend into `stbl` (the sample tables are rebuilt separately).
So, e.g., `Box32ConstructBuilder({b"free": {}}).Box.build({"type": b"free", "data":
[{"type": b"gps ", "data": <raw bytes>}]})` writes a `free` box whose payload is a single
nested `gps ` box of raw bytes — and the parse side must round-trip exactly that nesting.

**`dref`/`url ` field grammar (the data-reference boxes inside `dinf`).** Unlike `elst`, whose
`entries` are flat field-dicts, `dref`'s `entries` are **child box-dicts** — so `dref`'s inner
`data` is itself a nested-box grammar, not raw bytes. Concretely:

- `dref` is a leaf-header box whose `data` field-dict is
  `{"version": int, "flags": int, "entries": [<box-dict>, ...]}` (`version`/`flags` default to
  `0` when omitted). `entries` is a **length-prefixed list of child box-dicts**, each a
  `{"type": b"url "|b"urn ", "data": <field dict>}` box routed through the switch map by its
  4-byte type (unknown types fall through to raw bytes).
- `url ` (and `urn `) is a **fullbox** leaf whose `data` field-dict is `{"flags": int, "data": bytes}`
  (with an optional `"version"`, default `0`). It serializes/parses as a 1-byte version (`0`)
  followed by a 3-byte big-endian `flags` (so `flags` occupies the standard 4-byte
  version+flags header), then the remaining `data` bytes greedily (empty when the
  self-contained flag `0x1` is set). It round-trips exactly: e.g.
  `{"type": b"url ", "data": {"flags": 1, "data": b""}}` builds a 4-byte payload
  `00 00 00 01` and parses back to the same dict.

## CAMM (`camm.camm_parser`, `camm.camm_builder`) and the MP4 round-trip

### Edit-list (`elst`) trimming

CAMM telemetry timing is corrected by the track's MP4 edit list. Two functions:

- `elst_entry_to_seconds(entry, movie_timescale, media_timescale) -> (media_time, duration)`:
  `entry` is a dict with `media_time` and `segment_duration` (integer ticks). Asserts both
  timescales are `> 0`. `duration = segment_duration / movie_timescale`. `media_time` is divided
  by `media_timescale` **unless it is the sentinel `-1`**, which is passed through unchanged
  (an empty/blank edit). Returns the pair.
- **Edit-list trimming** (applied inside `extract_camm_info` from the track's `edts`/`elst`): the
  edit list reduces to a sequence of `(media_time, duration)` segments in seconds (via
  `elst_entry_to_seconds`). Entries with `media_time == -1` are *empty* edits; the **last** empty
  edit's `duration` is a global time `offset` (0 if there are none) added to every surviving point.
  The real (non-empty) segments, sorted by `media_time`, define the windows of media time that
  survive: a point falling inside a segment window (start-inclusive at `media_time`, end-inclusive
  at `media_time + duration`) is kept (shifted by `offset`); points outside any window are dropped.
  The walk advances monotonically through both the time-ordered points and the segments in a single
  forward pass over each (a two-pointer merge): a point *before* the current segment's start is
  dropped, a point *inside* the window is kept, and a point *after* the current segment's end
  advances to the next segment **and is itself consumed** — it is **not** re-tested against the
  now-current later segment. So a point that would fall inside a later window, but only after
  passing an earlier segment, is dropped rather than kept. When there are no real segments, nothing
  is dropped — every point is kept, shifted by `offset`. Shifting preserves the point subtype.

### Make/model

`extract_camm_info` recovers camera make/model from the MP4 `udta` box (`@mak`/`@mod`,
`manu`/`modl`, and the size-prefixed Insta360 `\xa9mak`/`\xa9mod` variants), decoding UTF-8
(unicode round-trips), stripping surrounding whitespace. The `@mak`/`@mod` and `manu`/`modl`
boxes carry their value as raw UTF-8 box data; the Insta360 `\xa9mak`/`\xa9mod` payload is
instead size-prefixed as `uint16 big-endian size, 2 reserved bytes, then `size` bytes of
UTF-8` (and any trailing NULs are stripped).

### `extract_camm_info(fp, telemetry_only=False) -> CAMMInfo | None`

Parses the MP4 stream, finds the track whose sample description format is `b"camm"`, decodes each
sample's CAMM payload, applies the track's edit-list trimming, and bins the results. Returns a
`CAMMInfo` dataclass exposing at least `mini_gps: list[Point] | None`, `gps`, `make`, `model`
(plus `accl`/`gyro`/`magn`). Plain `MIN_GPS` (type-5) samples decode to `geo.Point` (altitude
defaulting to `-1.0` when unknown). `GPS` (type-6) samples decode to `CAMMGPSPoint` preserving
`time_gps_epoch`, `gps_fix_type`, and the velocity/accuracy fields. Each CAMM sample payload is a
little-endian record prefixed by `2 reserved bytes + uint16 type`; the type-6 `GPS` body is then,
in order, `time_gps_epoch` (Float64), `gps_fix_type` (signed Int32), `latitude`/`longitude`
(Float64), then `altitude`, `horizontal_accuracy`, `vertical_accuracy`, `velocity_east`,
`velocity_north`, `velocity_up`, `speed_accuracy` each as a single-precision **Float32** — so
velocity/accuracy/altitude values round-trip at Float32 precision (a `-1.0` altitude is written
when `alt is None`). ACCL/GYRO/MAGN bodies are three little-endian Float32 XYZ values. **Returns `None` when the MP4
has no CAMM track.** Note: the recovered objects are collected by `isinstance(..., geo.Point)`, so
in the GPS-only path callers read `info.gps or info.mini_gps` and a leading negative-`time` sample
is dropped before encoding.

### Round-trip support — what the tests do (you must make this path work)

The tests do **not** ship a binary MP4. Instead they synthesize one in memory and re-parse it, so
the build side must exist and be consistent with the parse side:

1. `cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist([...])` — a module-level builder instance
   whose `build_boxlist(boxes)` serializes a list of `{"type": b"...", "data": ...}` box dicts
   (here a minimal MP4 of `ftyp` + a `moov` containing only an `mvhd`) to bytes.
2. `uploader.VideoUploader.prepare_camm_info(video_metadata) -> CAMMInfo` — classmethod that turns
   a `VideoMetadata` (with `points`, `make`, `model`) into a `CAMMInfo`: `CAMMGPSPoint`s go to
   `gps`; `GPSPoint`s with a positive `epoch_time` are converted to `CAMMGPSPoint`s (carrying the
   epoch and fix); plain `Point`s go to `mini_gps`.
3. `simple_mp4_builder.transform_mp4(src_fp, sample_generator)` — reads the source MP4's `ftyp`
   and `moov`, then invokes the callback **positionally as `sample_generator(fp, moov_children)`**:
   the **first** argument `fp` is the readable source MP4 stream, and the **second** argument
   `moov_children` is the **mutable list** of the source `moov`'s child box-dicts. The generator
   appends its new track (a `{"type": b"trak", "data": [...]}` box-dict, and any `udta`) to
   `moov_children` **in place** and returns an iterator that yields the new track's samples, each as
   a **readable, seekable binary stream** (a file-like object such as `io.BytesIO`, i.e. an
   `io.IOBase`) positioned at the start — **not** a raw `bytes` object. `transform_mp4` appends the
   yielded sample streams directly to the chained output stream (which requires each to be
   `readable()`/`seekable()`), so a generator that yields plain `bytes` would fail. The movie
   timescale is **not** passed as an argument — the generator derives it from `moov_children` (via
   `find_movie_timescale`) if it needs it. `transform_mp4` then consumes the yielded sample streams,
   rebuilds a complete MP4 (rebuilding the `stbl` sample tables — `stsz/stsc/stts/stco|co64` — from
   the raw samples, where each sample's size is the length of its stream), and returns a readable
   binary stream. The `moov_children` append must be a **call-time** side effect: `transform_mp4`
   reads the appended track out of `moov_children` after invoking the generator but potentially
   before draining the returned iterator, so the generator must append its track (and any `udta`)
   when it is *called* and hand back a *separate* iterator over the sample streams — a bare `yield`
   body (which defers the append until the iterator is first advanced) does not satisfy this.
   Because the callback receives the live `moov_children` list, a caller may then wrap it to inspect
   or mutate the injected track (e.g. overwrite its `udta`, or swap its `edts`/`elst`) after the
   generator appends it but before the samples are emitted.
4. `camm_builder.camm_sample_generator2(camm_info)` — returns the sample generator that
   `transform_mp4` calls (with the same `(fp, moov_children)` signature as above): it builds a CAMM
   `trak` (with a `camm`-format sample description), an `elst` edit list derived from the points'
   timestamps, writes make/model into a `udta` box (appended to `moov_children`), and yields each
   measurement serialized as a CAMM sample wrapped in a readable binary stream (per item 3's
   sample-stream contract). It appends the `trak`/`udta` at call time and returns a separate
   iterator over the sample streams. The CAMM track's media timescale (the `mdhd.timescale` it
   writes, and the `media_timescale` its `elst` `media_time` ticks are expressed in) equals the
   movie timescale (from `find_movie_timescale`), floored at `1000` ticks/s — so with the standard
   microsecond movie timescale the media timescale is also microseconds, and a `media_time` in
   microsecond ticks divides back to seconds via `elst_entry_to_seconds`. Points with negative
   `time` are filtered out before building. The natural elst it emits preserves absolute point
   times, so a round-trip without a custom edit list returns the original point times unchanged
   (the first surviving point comes back at its own `time`, not rebased to `0`).

For BlackVue, the tests instead use `cparser.Box32ConstructBuilder({b"free": {}}).Box.build(box)`:
constructing `Box32ConstructBuilder(switch_map)` with a box-type→subgrammar map yields an object
with a `.Box` construct whose `.build(box_dict)` serializes one box (and nested children), and with
`.build_boxlist(...)`. `Box64ConstructBuilder` is the 64-bit-size sibling. These wrap `construct`
grammars for ISOBMFF boxes; `MP4WithoutSTBLBuilderConstruct` is a preconfigured 32-bit instance
over the standard MP4 box map (without descending into `stbl`).

---

## GoPro GPMF (`gpmf.gpmf_parser`)

GoPro cameras store GPS/IMU telemetry as a **GPMF** KLV (key/length/value) stream carried in an
MP4 track whose sample description format is `b"gpmd"`. The GPMF stream nests `DEVC` (device)
containers, each holding `STRM` (stream) containers; a GPS `STRM` carries a `SCAL` divisor list and
either a `GPS5` or a `GPS9` schema (plus optional `GPSF`/`GPSU`/`GPSP` tags), and a device may carry
a `DVNM` device-name tag.

`extract_gopro_info(fp, telemetry_only=False) -> GoProInfo | None` parses the MP4 stream, finds the
`gpmd` track, decodes its GPMF samples, and returns a `GoProInfo` dataclass exposing
`gps: list[GPSPoint] | None`, `accl`/`gyro`/`magn`, `make` (default `"GoPro"`), and `model`. A
"recognizable GoPro device" is a `gpmd` track carrying at least one `DEVC` container (independent of
whether it has a `DVNM` name or whether any GPS point decodes); the function returns `None` only when
the MP4 has no `gpmd` track / no `DEVC` at all. When a device **is** recognized it returns a
`GoProInfo` even if no GPS points decode — and in that case `gps` is an **empty list `[]`**, not
`None` (so `None` means "not extracted / not a GoPro video" while `[]` means "extracted, but the
device yielded zero GPS points", e.g. every sample dropped by the zero-SCAL rule and no usable
stream). The GPS decode rules:

- **GPS5**: divide each GPS5 column by its corresponding `SCAL` divisor (column order: lat, lon,
  alt, 2D ground-speed, 3D speed). If **any** SCAL divisor is `0`, the sample yields **no point**.
  `GPSF` (if present) maps through `GPSFix(value)` to the point `fix`; `GPSP` (if present) becomes
  `precision`. `GPSU` (if present) is a 16-byte `YYMMDDhhmmss.sss` ASCII timestamp parsed to a UTC
  `epoch_time`; if missing or unparseable, `epoch_time` is `None`.
- **GPS9**: packs 9 values per sample. A `TYPE` KLV declares the per-value types as a type string;
  decoding **raises `ValueError` (message mentioning "9 types")** if the declared type string does
  not have exactly 9 entries. The type string drives a **per-value, big-endian struct** built from
  the GPMF type-char alphabet (e.g. `l` = signed int32, `L` = unsigned int32, `s` = signed int16,
  `S` = unsigned int16, `f` = Float32, `d` = Float64) — the values may be heterogeneous widths, so
  the struct is assembled from the declared chars rather than assuming a uniform column width. Each
  sample is then divided by `SCAL` (column order: lat, lon, alt, 2D speed, 3D speed,
  days-since-2000, secs-since-midnight, DOP, fix); `epoch_time` is computed from the
  days/seconds-since-2000-01-01-UTC columns, `fix=GPSFix(fix)`, `precision = DOP*100`,
  `ground_speed = 2D speed`. A zero SCAL divisor yields no point.
- **Per-STRM selection**: within each `STRM`, **GPS9 is tried first**, and only if it yields no
  points is GPS5 tried; the first `STRM` that yields any points wins (so a GPS9 sample wins over a
  GPS5 schema in the same STRM, and an unusable leading STRM is skipped in favor of a later one).
- **Epoch backfill**: after decoding, GPS points missing an `epoch_time` are backfilled from the
  nearest point that has one — forward (`epoch_time = anchor.epoch_time + (point.time -
  anchor.time)`) and then backward — so a single anchored sample propagates epochs to its neighbors
  in both directions.
- **`model`**: derived from the device-name (`DVNM`) tags, decoding each as UTF-8 and **skipping
  names that fail to decode**; if none decode, `model` is `""`. Among the decodable names the
  priority is: a name containing `"hero"` (case-insensitive) wins; else one containing `"gopro"`;
  else the alphabetically-first name. The chosen name is stripped (ties resolve alphabetically).

### GPMF KLV grammar and round-trip — what the tests do

The GPMF stream is serialized/parsed by a `construct` grammar `GPMFSampleData` (a `GreedyRange` of
KLV structs). Each KLV is a dict `{"key", "type", "structure_size", "repeat", "data"}`, serialized in
that order: a 4-byte `key` (FourCC `bytes`), a 1-byte `type` char, a 1-byte `structure_size` (`int`),
a 2-byte big-endian `repeat` (`int`), then the `data` (with the payload padded to a 4-byte boundary).
Like `key`, the KLV `type` field is a **1-byte `bytes` char** (e.g. `b"l"`, `b"L"`, `b"c"`, `b"U"`,
and `b"\x00"` for a nested container), **not** an `int` ordinal — so `GPMFSampleData.build([...])`
must accept KLV dicts whose `type` is a byte-string char. The `type` char selects how `data` is laid
out: a `\x00` type is **nested** GPMF KLV data
(used for `DEVC`/`STRM` containers — its payload is itself a `GPMFSampleData` block); a `c` type is
`repeat` raw byte-strings of `structure_size` bytes each (used for the GPS9 `TYPE` alphabet); the
numeric/string types (`l`, `L`, `s`, `S`, `f`, `d`, `U`, …) lay `data` out as `repeat` rows, each
row holding `structure_size / width` values of that type's fixed `width` (e.g. `l`/`L` 4 bytes, `S`
2 bytes, `U` a 16-byte string). Any **non-enumerated** type char (one outside the alphabet above,
e.g. an opaque packed-row marker) falls back to the same raw-bytes layout as `c` — `repeat` raw
byte-strings of `structure_size` bytes each — so a pre-packed payload (such as struct-packed GPS9
rows) round-trips as opaque bytes. The tests synthesize a `gpmd` MP4 in memory — building GPMF sample
bytes with `GPMFSampleData.build([...])` and appending a `gpmd`-format track via
`simple_mp4_builder.transform_mp4` (the same machinery the CAMM round-trip uses) — then re-parse it
through `extract_gopro_info`, so the KLV grammar and the `gpmd` track recognition must round-trip.

## GPMF GPS noise filter (`gpmf.gpmf_gps_filter`)

The public noise-removal surface (used by the video telemetry extractor to clean a decoded GPS
track) lives in `gpmf.gpmf_gps_filter`:

- `remove_noisy_points(sequence) -> sequence`: filter a `GPSPoint` track in three stages, in
  order: (1) drop points whose GPS `fix` is present but **not** a usable fix — only `fix in {FIX_2D,
  FIX_3D}` (or `fix is None`) is kept; (2) drop points whose `precision` (DOP×100) exceeds a max DOP
  threshold (default `1000`; `precision is None` is kept); (3) `remove_outliers` on what remains.
- `remove_outliers(sequence) -> sequence`: a no-op for fewer than 2 pairwise distances or fewer than
  2 known ground speeds; otherwise split the track wherever consecutive points are farther apart than
  the Tukey `upper_whisker` of the pairwise distances (floored at twice a ~15 m GPS precision),
  `dbscan`-merge the resulting subsequences whose adjacent endpoints have a speed at or below the
  Tukey `upper_whisker` of the ground speeds, and return the **majority** (longest) merged cluster —
  so an isolated far/fast jump is dropped while the main track survives.

## BlackVue (`blackvue_parser`)

- **NMEA decode** (inside `extract_blackvue_info`): the `gps ` box holds lines like
  `[<epoch_ms>]$GPxxx,...`. Parse the NMEA sentences (via `pynmea2`), skipping unparseable lines. The
  bracketed value is the camera epoch in **milliseconds**.
  - GGA carries altitude + a fix quality → `fix = GPSFix.FIX_3D` when quality `>= 1`, plus
    `alt`. RMC and GLL carry no altitude/fix.
  - **Timezone-offset inference**: BlackVue cameras may have a mis-set clock. Detect an offset to
    add to the camera epoch so it becomes true UTC. **RMC** sentences carry full date+time, so
    `offset = round(rmc_datetime_utc_epoch - camera_epoch_sec, 3)` from the first valid RMC. If
    there is no RMC, fall back to the first valid **GGA/GLL** (time-only): rebuild the corrected
    datetime from the camera date with the NMEA hh:mm:ss, then resolve the **day boundary** — if
    the camera-seconds-of-day exceeds the NMEA-seconds-of-day by more than 12h, add a day; if the
    reverse, subtract a day — and `offset = round(corrected - camera_epoch_sec, 3)`. Default
    offset is `0.0`. The offset is applied to **every** returned point's `time`/`epoch_time`.
  - Returned points are restricted to a single sentence type, preferring **RMC**, then GGA, then
    GLL (matching exiftool's extraction order).
- `extract_blackvue_info(fp) -> BlackVueInfo | None`: read the `free`/`gps ` box bytes, parse the
  NMEA telemetry (see above), **sort the surviving points by `time` (chronologically)** and then
  **rebase times so the first (earliest) point is 0.0** (epoch_time stays absolute), read the camera
  model from a `free`/`cprt` box (if present), and return a `BlackVueInfo`. Because of the sort, the
  returned track is always in ascending `time` order regardless of the order the NMEA sentences
  appeared in the box. `BlackVueInfo` is a dataclass exposing the parsed points as a
  `gps: list[GPSPoint] | None` attribute, plus `make` (always `"BlackVue"`) and `model`. Returns
  `None` when there is no `gps ` box. The `cprt` model is derived by stripping whitespace/NULs from
  the box bytes: if the payload is JSON, the `"model"` field is used; otherwise it is treated as a
  semicolon-delimited string and the **second** field is used.

(The tests wrap raw NMEA bytes into a `free`/`gps ` box with
`Box32ConstructBuilder({b"free": {}}).Box.build(...)` and read it back via your
`simple_mp4_parser.parse_mp4_data_first`, so the box reader/writer must round-trip
nested `free` → `gps `/`cprt` boxes.)

---

## Image EXIF geotag (`exif_read`, `geotag.image_extractors.exif`)

Images are the headline first-class input: the documented flow is to `process` a folder of
geotagged JPEGs (then `upload`). The EXIF-decode path turns a single image into an
`ImageMetadata`:

- `exif_read.ExifRead(fp_or_path)` reads EXIF (and XMP) tags from an opened image file (it accepts a
  binary file object). Its extractors return the decoded values:
  - `extract_lon_lat() -> (lon, lat) | None` — note the **(lon, lat)** order — decoded from the GPS
    IFD degrees/minutes/seconds rationals with the N/S, E/W refs applied as sign.
  - `extract_capture_time() -> datetime | None` — the capture timestamp (DateTimeOriginal / GPS
    datetime), timezone-aware; convert to a Unix epoch with `geo.as_unix_time`.
  - `extract_altitude()`, `extract_direction()` (GPS image direction, compass degrees),
    `extract_make()`, `extract_model()`, `extract_width()`, `extract_height()`,
    `extract_orientation()`.
- `geotag.image_extractors.exif.ImageEXIFExtractor(image_path).extract() -> types.ImageMetadata`
  opens the image, runs the EXIF extractors above, and returns a populated `ImageMetadata` with
  `lat`, `lon`, `time` (= `geo.as_unix_time(capture_time)`), `alt`, `angle` (the GPS direction),
  `width`, `height`, and the `MAPDeviceMake`/`MAPDeviceModel` fields. It raises a
  `MapillaryGeoTaggingError` when GPS longitude/latitude or the timestamp cannot be extracted.

## Upload (`upload_api_v4`)

Uploading geotagged captures to Mapillary is the tool's defining action. The byte-stream upload
protocol is **resumable**: a stream is chunked, the already-uploaded prefix is skipped using the
server's current offset, and the remaining tail is sent.

- `UploadService.chunkize_byte_stream(stream, chunk_size)` yields `chunk_size`-sized chunks of the
  stream (raises `ValueError` on a non-positive `chunk_size`); `UploadService.shift_chunks(chunks,
  offset)` drops the first `offset` bytes across the chunk boundaries.
- `upload_byte_stream(stream, offset=None, chunk_size=...) -> str` (and `upload_chunks(chunks,
  offset=None) -> str`): when `offset` is `None`, fetch the current offset first, then upload the
  shifted remainder; return the resulting **file handle / cluster id** as a string.
- `FakeUploadService(user_session, session_key, *, upload_path, transient_error_ratio=0.0)` is a
  file-backed mock of `UploadService` for offline testing: `upload_shifted_chunks` **appends** the
  bytes to `upload_path/session_key`, `fetch_offset()` returns the current size of that file (0 if
  absent), and a random `transient_error_ratio` fraction of operations raise a transient
  `requests.ConnectionError` (set it to `0.0` for determinism). A successful upload returns a stable
  per-session file handle string. Because writes append at the fetched offset, re-uploading the same
  content from the current offset is a no-op (the file is unchanged).

---

## `process_sequence_properties`

The pipeline entry point:

```
process_sequence_properties(
    metadatas,
    cutoff_distance=100, cutoff_time=60,
    interpolate_directions=False,
    duplicate_distance=0.1, duplicate_angle=5,
    max_capture_speed_kmh=400,
    skip_zigzag_check=False,
) -> list[MetadataOrError]
```

It accepts a mixed list of `ImageMetadata`, `VideoMetadata`, and `ErrorMetadata`, and returns a
list of **exactly the same length** (every input is accounted for as a surviving metadata or an
`ErrorMetadata`). Images are processed through the full pipeline; videos through video-limit
checks; pre-existing `ErrorMetadata` pass through. The constant defaults that are not parameters:
`MAX_SEQUENCE_LENGTH = 1000`, `MAX_SEQUENCE_FILESIZE = 110 GiB`, `MAX_SEQUENCE_PIXELS = 6e9`,
zig-zag window size 5 / min-distance 30 m / deviation threshold 0.8 / min-deviations 1.

### Image pipeline (in order)

1. **Group** images by folder + camera identity (make/model/`MAPCameraUUID`); images differing in
   `MAPCameraUUID` (including a `None` uuid) form distinct groups → distinct sequences. Sort each
   group by `sort_key()`.
2. **Sub-second interpolation**: within a run of `N` identical timestamps `t`, spread the times
   into strictly-increasing sub-second offsets so the stable sort is well-defined. Let `t_next` be
   the next distinct timestamp after the run, capped at the next whole second
   (`t_next = min(next_distinct_timestamp, floor(t) + 1)`; for the final run there is no next
   distinct timestamp, so `t_next = floor(t) + 1`). Assign the `k`-th point of the run
   (`k = 0 … N-1`) the time `t + k * (t_next - t) / N`. The first point keeps `t` exactly, the
   spacing is `(t_next - t) / N`, and the half-open interval means no point lands on `t_next`
   (e.g. a run of three identical `1.0`s before a `2.0` becomes `1.0, 1.333…, 1.666…`).
3. **Split** each sequence on an aggregate predicate that starts a new sequence whenever **any** of
   these is exceeded between consecutive (or accumulated) images: time gap > `cutoff_time`,
   running image count > `MAX_SEQUENCE_LENGTH`, running cumulative filesize > `MAX_SEQUENCE_FILESIZE`,
   running cumulative pixel count (`width*height`) > `MAX_SEQUENCE_PIXELS`. (Distance splitting is
   applied **later**, after the speed check — see step 7.) E.g. 1001 images → two sequences; one
   oversized image isolates into its own sequence.
4. **Null-island check**: an image at exactly `(lat=0, lon=0)` becomes an `ErrorMetadata` carrying
   `MapillaryNullIslandError`; valid images in the same folder pass through.
5. **Duplication check** (see `duplication_check` below): flagged duplicates become `ErrorMetadata`
   carrying `MapillaryDuplicationError`.
6. **Direction interpolation**: if `interpolate_directions=True`, **clear all angles first** then
   recompute every angle from path geometry (bearing to the next point); otherwise only fill the
   `None` angles. Uses `geo.interpolate_directions_if_none`.
7. **Speed check**: a sequence whose average speed exceeds `max_capture_speed_kmh` is rejected — and
   **every** image in it becomes an `ErrorMetadata` carrying `MapillaryCaptureSpeedTooFastError`.
8. **Zig-zag check** (unless `skip_zigzag_check`): flag the points that jump off and back onto the
   path as `MapillaryZigZagError`, leaving the main path intact. Parameters: `window_size=5`,
   `deviation_threshold=0.8`, `min_deviations=1`, `min_distance=30` m. Algorithm, per sequence:
   * Sequences shorter than `window_size + 1` are exempt (appended unchanged).
   * Collect a set of *deviation indices*. For each `i` from `window_size` to the end, let
     `curr = sequence[i]`, `prev = sequence[i-1]`, `ref = sequence[i-window_size]`, and compute the
     `gps_distance`s `dist_prev_curr = d(prev, curr)`, `dist_curr = d(curr, ref)`,
     `dist_prev = d(prev, ref)`. A deviation is detected at `prev` when **both**
     `dist_prev_curr > min_distance` **and** `dist_curr < dist_prev * deviation_threshold` (i.e. the
     step `prev→curr` is a real jump *and* `curr` came back closer to the look-back reference than
     `prev` was). When detected, add index `i-1` (`prev`) to the deviation set, then **walk backward**
     `j = i-2, i-3, …` down to `ref+1`: add `j` to the set while
     `d(sequence[j], curr) > min_distance` **and** `dist_curr < d(sequence[j], ref) * deviation_threshold`,
     stopping at the first `j` that fails (it is on the normal path).
   * After scanning, if the deviation set has at least `min_deviations` entries, emit a
     `MapillaryZigZagError` `ErrorMetadata` for each deviation index (in sorted order) and keep the
     remaining points; otherwise keep the whole sequence. A straight path and a legitimate U-turn
     whose per-step distances stay under `min_distance` produce no deviations and are not flagged.
9. **Distance split**: split surviving sequences where the gap between consecutive points exceeds
   `cutoff_distance`.
10. **Assign UUIDs**: each final sequence gets a distinct `MAPSequenceUUID` (the package uses small
    incremental string ids) assigned to every image in it.

### `split_sequence_by(sequence, reduce, initial) -> list[list]`

A general split primitive. Fold `reduce(state, element) -> (new_state, should_split)` over the
sequence; whenever `should_split` is true, start a new subsequence beginning with the current
element; otherwise append to the current subsequence. Empty input → `[]`; single element → one
subsequence.

### `duplication_check(sequence, *, max_duplicate_distance, max_duplicate_angle) -> (dedups, dups)`

Walk the sequence keeping the last **kept** point as `prev`. The current point is a **duplicate**
when the distance to `prev` is `<= max_duplicate_distance` **and** the angle test passes. The
angle test: if both points have an angle, compute `diff_bearing(prev.angle, cur.angle)` and require
it `<= max_duplicate_angle`; if either angle is missing, the angle test is treated as satisfied.
A point flagged as a duplicate is dropped without becoming the new `prev`. Return `(kept_points,
list_of_ErrorMetadata)`; each error wraps a `MapillaryDuplicationError` whose `distance` and
`angle_diff` attributes carry the measured values (`angle_diff` is `None` when an angle was
missing).

### Video limit checks

For each `VideoMetadata`, run these checks **in this exact order** and emit the *first* failure as
an `ErrorMetadata` (carrying the video's own filetype); if none fail, the video passes through
unchanged:

1. **Stationary**: the video is stationary if **every** point lies within a radius of `10.0`
   meters of the first point (`gps_distance` from `points[0]`). An empty point list also counts as
   stationary. → `MapillaryStationaryVideoError`.
2. **File too large**: `filesize` (or the file's size on disk when `filesize is None`) over the
   max-sequence-filesize → `MapillaryFileTooLargeError`.
3. **Null island**: any point at exactly `(lat=0, lon=0)` → `MapillaryNullIslandError`.
4. **Too fast**: with at least 2 points, average speed (`avg_speed` × 3.6, in km/h) over
   `max_capture_speed_kmh` → `MapillaryCaptureSpeedTooFastError`.

(Note: because stationary is checked first with a 10 m radius, a video must move more than 10 m to
reach the later checks — so a moving video that also passes through `(0,0)` is flagged null-island,
not stationary.)
