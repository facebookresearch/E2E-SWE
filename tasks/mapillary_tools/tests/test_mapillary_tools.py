"""Tests for the mapillary_tools telemetry-decode + geo-interpolation +
sequence-splitting subsystem.

Each test exercises the public Python API of one of:
  - mapillary_tools.geo                 (Point, Interpolator, gps_distance, ...)
  - mapillary_tools.telemetry           (GPSPoint, CAMMGPSPoint, GPSFix, ...)
  - mapillary_tools.camm.camm_parser    (CAMM telemetry decode + elst trimming)
  - mapillary_tools.gpmf.gpmf_parser    (GoPro GPMF GPS5/GPS9 decode, device model)
  - mapillary_tools.gpmf.gpmf_gps_filter (GPS noise removal: fix/DOP/outlier filtering)
  - mapillary_tools.blackvue_parser     (BlackVue NMEA GPS + timezone inference)
  - mapillary_tools.process_sequence_properties (split / dedup / zigzag)

Fixtures are built in-memory: CAMM tracks via the camm_builder/transform_mp4
round-trip; BlackVue via the construct MP4 box builder. No large binary blobs.

Many tests bundle several closely-related cases under a single behavior, with
multiple assertions, to keep coverage broad while exercising each rule once.
"""

from __future__ import annotations

import datetime
import io
import math
import struct
import typing as T
from pathlib import Path

import piexif
import pytest

from mapillary_tools import exif_read, geo, telemetry, types, upload_api_v4, uploader
from mapillary_tools import process_sequence_properties as psp
from mapillary_tools import exceptions
from mapillary_tools.camm import camm_builder, camm_parser
from mapillary_tools.geotag.image_extractors.exif import ImageEXIFExtractor
from mapillary_tools.gpmf import gpmf_parser
from mapillary_tools.gpmf import gpmf_gps_filter
from mapillary_tools.gpmf.gpmf_parser import extract_gopro_info
from mapillary_tools.mp4 import construct_mp4_parser as cparser, mp4_sample_parser as _sample_parser
from mapillary_tools.mp4 import simple_mp4_builder
from mapillary_tools import blackvue_parser
from mapillary_tools.telemetry import GPSPoint, CAMMGPSPoint, GPSFix
from mapillary_tools.geo import Point


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _encode_decode_camm(points, make="", model=""):
    """Round-trip a list of telemetry points through an in-memory CAMM MP4.

    Mirrors the real `process` -> CAMM build -> `extract_camm_info` path:
    build a minimal MP4 with only an mvhd, inject a CAMM track via the
    camm_builder sample generator, then re-parse it.
    """
    movie_timescale = 1_000_000
    mvhd = {
        "type": b"mvhd",
        "data": {
            "creation_time": 1,
            "modification_time": 2,
            "timescale": movie_timescale,
            "duration": int(36000 * movie_timescale),
        },
    }
    empty_mp4 = [
        {"type": b"ftyp", "data": b"test"},
        {"type": b"moov", "data": [mvhd]},
    ]
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(empty_mp4)
    metadata = types.VideoMetadata(
        Path(""), filetype=types.FileType.CAMM, points=points, make=make, model=model
    )
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
    target_fp = simple_mp4_builder.transform_mp4(
        io.BytesIO(src), camm_builder.camm_sample_generator2(camm_info)
    )
    return camm_parser.extract_camm_info(T.cast(T.BinaryIO, target_fp))


def _encode_decode_camm_telemetry(camm_info):
    """Round-trip a CAMMInfo (with accl/gyro/magn) through an in-memory CAMM MP4 and
    re-parse it in telemetry_only mode."""
    movie_timescale = 1_000_000
    mvhd = {
        "type": b"mvhd",
        "data": {"creation_time": 1, "modification_time": 2,
                 "timescale": movie_timescale,
                 "duration": int(36000 * movie_timescale)},
    }
    empty_mp4 = [
        {"type": b"ftyp", "data": b"test"},
        {"type": b"moov", "data": [mvhd]},
    ]
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(empty_mp4)
    target_fp = simple_mp4_builder.transform_mp4(
        io.BytesIO(src), camm_builder.camm_sample_generator2(camm_info))
    return camm_parser.extract_camm_info(
        T.cast(T.BinaryIO, target_fp), telemetry_only=True)


def _encode_decode_camm_with_udta(make_box, mod_box):
    """Round-trip a single-point CAMM track but overwrite the builder's udta children
    with the given (type, data) make/model boxes, then re-parse make/model.

    make_box / mod_box are (box_type, box_data) tuples.
    """
    movie_timescale = 1_000_000
    mvhd = {
        "type": b"mvhd",
        "data": {"creation_time": 1, "modification_time": 2,
                 "timescale": movie_timescale,
                 "duration": int(36000 * movie_timescale)},
    }
    empty_mp4 = [
        {"type": b"ftyp", "data": b"test"},
        {"type": b"moov", "data": [mvhd]},
    ]
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(empty_mp4)
    metadata = types.VideoMetadata(
        Path(""), filetype=types.FileType.CAMM,
        points=[Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None)],
        make="placeholder", model="placeholder")
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
    inner = camm_builder.camm_sample_generator2(camm_info)

    def gen(fp, moov_children):
        result = inner(fp, moov_children)
        for b in moov_children:
            if b["type"] == b"udta":
                b["data"] = [
                    {"type": make_box[0], "data": make_box[1]},
                    {"type": mod_box[0], "data": mod_box[1]},
                ]
        return result

    target_fp = simple_mp4_builder.transform_mp4(io.BytesIO(src), gen)
    return camm_parser.extract_camm_info(T.cast(T.BinaryIO, target_fp))


def _build_blackvue_mp4(gps_data: bytes, cprt: bytes | None = None) -> bytes:
    """Wrap raw NMEA bytes into a `free`/`gps ` box MP4 that extract_blackvue_info can
    parse (optionally followed by a second `free`/`cprt` box carrying the camera model)."""
    box_builder = cparser.Box32ConstructBuilder({b"free": {}})
    out = box_builder.Box.build({"type": b"free", "data": [{"type": b"gps ", "data": gps_data}]})
    if cprt is not None:
        out += box_builder.Box.build(
            {"type": b"free", "data": [{"type": b"cprt", "data": cprt}]})
    return out


def _make_image(tmp_path, name, lon, lat, t, angle=None, filesize=1, **kwargs):
    return types.ImageMetadata(
        filename=(tmp_path / name).resolve(),
        filesize=filesize,
        lon=lon,
        lat=lat,
        time=t,
        alt=None,
        angle=angle,
        **kwargs,
    )


# A minimal valid 1x1 baseline JPEG that piexif can graft EXIF onto.
_MINIMAL_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00" + bytes([8]) * 64
    + b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x14\x00\x01" + b"\x00" * 15 + b"\x08"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xd2\xcf \xff\xd9"
)


def _deg_to_dms_rational(deg_float):
    """Encode a decimal degree as the (deg, min, sec) rational triple EXIF GPS uses."""
    deg_abs = abs(deg_float)
    d = int(deg_abs)
    minutes_full = (deg_abs - d) * 60
    m = int(minutes_full)
    s = (minutes_full - m) * 60
    return ((d, 1), (m, 1), (round(s * 10000), 10000))


def _write_jpeg_with_exif(path, *, lat, lon, when, direction, make, model):
    """Write a JPEG at `path` carrying GPS lat/lon, capture time, direction, make/model EXIF."""
    gps_ifd = {
        piexif.GPSIFD.GPSLatitudeRef: "N" if lat >= 0 else "S",
        piexif.GPSIFD.GPSLatitude: _deg_to_dms_rational(lat),
        piexif.GPSIFD.GPSLongitudeRef: "E" if lon >= 0 else "W",
        piexif.GPSIFD.GPSLongitude: _deg_to_dms_rational(lon),
        piexif.GPSIFD.GPSImgDirectionRef: "T",
        piexif.GPSIFD.GPSImgDirection: (round(direction * 100), 100),
    }
    exif_bytes = piexif.dump({
        "0th": {piexif.ImageIFD.Make: make, piexif.ImageIFD.Model: model},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: when.strftime("%Y:%m:%d %H:%M:%S"),
            # Anchor the capture time to UTC explicitly so the decoded epoch does not depend on the
            # grading container's local timezone (`when` is tz-aware UTC).
            piexif.ExifIFD.OffsetTimeOriginal: "+00:00",
        },
        "GPS": gps_ifd,
    })
    out = io.BytesIO()
    piexif.insert(exif_bytes, _MINIMAL_JPEG, out)
    path.write_bytes(out.getvalue())
    return path


# --- GoPro GPMF: build an in-memory `gpmd` MP4 so GPS decode is exercised through the
#     public extract_gopro_info() surface (mirrors the CAMM build->parse round-trip). ---
_GPMF_TIMESCALE = 1_000_000
_STBLBuilder = cparser.Box32ConstructBuilder(
    T.cast(cparser.SwitchMapType, cparser.CMAP[b"stbl"]))


# Byte width of each GPMF type char this builder emits (mirrors the GPMF type alphabet).
_GPMF_TYPE_WIDTH = {b"l": 4, b"L": 4, b"s": 2, b"S": 2, b"f": 4, b"d": 8, b"U": 16}


def _gpmf_klv(key, data, type_char):
    """Build a GPMF leaf KLV dict, deriving structure_size/repeat from the data shape.

    `data` is a list of `repeat` records. For string/opaque payloads (`c` for the TYPE
    alphabet, `?` for packed GPS9 rows) each record is one byte-string and structure_size
    is its length. For every other type each record is a row of fixed-width values, so
    structure_size = (values per row) * (type width); type `U` (GPSU) is a 16-byte value,
    so its row is a single 16-byte string -> structure_size 16.
    """
    if type_char in (b"c", b"?"):
        structure_size = len(data[0]) if data else 0
    else:
        values_per_row = len(data[0]) if data and isinstance(data[0], (list, tuple)) else 0
        structure_size = values_per_row * _GPMF_TYPE_WIDTH[type_char]
    return {"key": key, "type": type_char, "structure_size": structure_size,
            "repeat": len(data), "data": data}


def _gpmf_nested(key, children):
    """Build a nested GPMF KLV (type b'\\x00') wrapping a list of child KLVs (e.g. DEVC/STRM)."""
    body = gpmf_parser.GPMFSampleData.build(children)
    return {"key": key, "type": b"\x00", "structure_size": 1, "repeat": len(body), "data": children}


def _gps5_strm(gps5, scal, gpsf=None, gpsu=None, gpsp=None):
    """A GPMF STRM carrying a GPS5 schema (+ optional GPSF/GPSU/GPSP/SCAL)."""
    children = []
    if gpsf is not None:
        children.append(_gpmf_klv(b"GPSF", gpsf, b"L"))
    if gpsu is not None:
        children.append(_gpmf_klv(b"GPSU", gpsu, b"U"))
    if gpsp is not None:
        children.append(_gpmf_klv(b"GPSP", gpsp, b"S"))
    if scal is not None:
        children.append(_gpmf_klv(b"SCAL", scal, b"l"))
    if gps5 is not None:
        children.append(_gpmf_klv(b"GPS5", gps5, b"l"))
    return _gpmf_nested(b"STRM", children)


def _gps9_strm(gps9_rows, scal, type_str=b"lllllllSS"):
    """A GPMF STRM carrying a GPS9 schema (TYPE alphabet + SCAL + packed GPS9 rows)."""
    children = []
    if type_str is not None:
        children.append(_gpmf_klv(b"TYPE", [type_str], b"c"))
    if scal is not None:
        children.append(_gpmf_klv(b"SCAL", scal, b"l"))
    children.append(_gpmf_klv(b"GPS9", gps9_rows, b"?"))
    return _gpmf_nested(b"STRM", children)


def _devc(strms, dvid=1, dvnm=None):
    """A GPMF DEVC device wrapping STRMs, with an optional device-name (DVNM) box."""
    children = [_gpmf_klv(b"DVID", [[dvid]], b"L")]
    if dvnm is not None:
        children.append(_gpmf_klv(b"DVNM", [dvnm], b"c"))
    children.extend(strms)
    return _gpmf_nested(b"DEVC", children)


def _build_gpmd_mp4(samples_devices, sample_times=None):
    """Build an in-memory MP4 with a `gpmd` track, one sample per entry in `samples_devices`.

    Each entry is a list of DEVC KLVs serialized into one GPMF sample. `sample_times` (start
    time in seconds of each sample) drives the stts deltas so decoded point times match;
    defaults to consecutive 1s samples.
    """
    if sample_times is None:
        sample_times = [float(i) for i in range(len(samples_devices))]
    mvhd = {"type": b"mvhd", "data": {"creation_time": 1, "modification_time": 2,
            "timescale": _GPMF_TIMESCALE, "duration": int(36000 * _GPMF_TIMESCALE)}}
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(
        [{"type": b"ftyp", "data": b"test"}, {"type": b"moov", "data": [mvhd]}])
    blobs = [gpmf_parser.GPMFSampleData.build(devs) for devs in samples_devices]
    media_timescale = max(1000, _GPMF_TIMESCALE)
    deltas = [
        int(round((sample_times[i + 1] - sample_times[i]) * media_timescale))
        if i + 1 < len(sample_times) else media_timescale
        for i in range(len(sample_times))
    ]

    def gen(fp, moov_children):
        raw_samples = [
            _sample_parser.RawSample(description_idx=1, offset=0, size=len(blob),
                                     timedelta=deltas[i], composition_offset=0, is_sync=True)
            for i, blob in enumerate(blobs)
        ]
        descriptions = [{"format": b"gpmd", "data_reference_index": 1, "data": b""}]
        stbl = {"type": b"stbl",
                "data": _STBLBuilder.build_boxlist(
                    simple_mp4_builder.build_stbl_from_raw_samples(descriptions, raw_samples))}
        hdlr = {"type": b"hdlr", "data": {"handler_type": b"gpmd", "name": "GoPro MET"}}
        mdhd = {"type": b"mdhd", "data": {"version": 1, "creation_time": 0, "modification_time": 0,
                "timescale": media_timescale, "duration": sum(deltas), "language": 21956}}
        dinf = {"type": b"dinf", "data": [{"type": b"dref", "data": {"entries": [
            {"type": b"url ", "data": {"flags": 1, "data": b""}}]}}]}
        minf = {"type": b"minf", "data": [dinf, stbl]}
        tkhd = {"type": b"tkhd", "data": {"version": 0, "creation_time": 0, "modification_time": 0,
                "track_ID": 0, "duration": 0xFFFFFFFF, "layer": 0}}
        mdia = {"type": b"mdia", "data": [mdhd, hdlr, minf]}
        moov_children.append({"type": b"trak", "data": [tkhd, mdia]})
        return iter([io.BytesIO(b) for b in blobs])

    return simple_mp4_builder.transform_mp4(io.BytesIO(src), gen)


def _gopro_from_strms(strms):
    """Decode a single-sample, single-DEVC `gpmd` MP4 through the public extract_gopro_info."""
    return extract_gopro_info(T.cast(T.BinaryIO, _build_gpmd_mp4([[_devc(strms)]])))


# --- CAMM: build an in-memory MP4 whose camm track carries a custom edts/elst, so edit-list
#     trimming is exercised through the public extract_camm_info() surface. ---
def _us(sec):
    return int(round(sec * _GPMF_TIMESCALE))


def _elst_entry(media_time_sec, duration_sec):
    """One elst entry; media_time_sec == -1 marks an empty edit (sets the global offset)."""
    return {"media_time": -1 if media_time_sec == -1 else _us(media_time_sec),
            "segment_duration": _us(duration_sec),
            "media_rate_integer": 1, "media_rate_fraction": 0}


def _encode_decode_camm_with_elst(points, elst_entries):
    """Round-trip a CAMM track but overwrite the builder's edts/elst with `elst_entries`,
    then re-parse via extract_camm_info. Both timescales are _GPMF_TIMESCALE, so media_time
    and segment_duration are in microseconds. Decoded point times are rebased to start at 0.
    """
    mvhd = {"type": b"mvhd", "data": {"creation_time": 1, "modification_time": 2,
            "timescale": _GPMF_TIMESCALE, "duration": int(36000 * _GPMF_TIMESCALE)}}
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(
        [{"type": b"ftyp", "data": b"test"}, {"type": b"moov", "data": [mvhd]}])
    metadata = types.VideoMetadata(
        Path(""), filetype=types.FileType.CAMM, points=points, make="", model="")
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
    inner = camm_builder.camm_sample_generator2(camm_info)

    def gen(fp, moov_children):
        result = inner(fp, moov_children)
        camm_trak = [b for b in moov_children if b["type"] == b"trak"][-1]
        trak_children = camm_trak["data"]
        trak_children[:] = [c for c in trak_children if c["type"] != b"edts"]
        trak_children.append(
            {"type": b"edts", "data": [{"type": b"elst", "data": {"entries": elst_entries}}]})
        return result

    target_fp = simple_mp4_builder.transform_mp4(io.BytesIO(src), gen)
    return camm_parser.extract_camm_info(T.cast(T.BinaryIO, target_fp))


def _camm_gps_times(info):
    """Sorted, rounded times of all decoded CAMM points (gps + mini_gps)."""
    got = (info.gps or []) + (info.mini_gps or [])
    return sorted(round(p.time, 5) for p in got)


# ===========================================================================
# geo.py: distance / bearing / diff (bundled)
# ===========================================================================
def test_geo_distance_bearing_and_diff():
    """gps_distance (WGS84 meters, antimeridian = same meridian), compute_bearing
    (compass degrees N=0/E=90/S=180/W=270), and diff_bearing (smallest angle in
    [0, 180], wrapping near 0/360)."""
    assert round(geo.gps_distance((42.1, -11.1), (42.2, -11.3)), 3) == 19916.286
    assert round(geo.gps_distance((0, -180), (0, 180)), 5) == 0
    assert geo.compute_bearing((0, 0), (1, 0)) == 0
    assert geo.compute_bearing((0, 0), (0, 1)) == 90
    assert geo.compute_bearing((0, 0), (-1, 0)) == 180
    assert geo.compute_bearing((0, 0), (0, -1)) == 270
    # antimeridian: a positive longitude delta (179 -> -179, heading east) wraps to 90
    assert geo.compute_bearing((0, 179), (0, -179)) == 90
    assert geo.compute_bearing((0, -179), (0, 179)) == 270
    assert geo.diff_bearing(10, 350) == 20
    assert geo.diff_bearing(0, 180) == 180
    assert geo.diff_bearing(350, 10) == 20
    assert geo.diff_bearing(5, 355) == 10


# ===========================================================================
# geo.py: avg_speed (bundled)
# ===========================================================================
def test_avg_speed_rules():
    """avg_speed: 0.0 for <2 points; NaN when the chosen time span is zero; uses GPS
    epoch time when both endpoints expose a positive epoch_time, else falls back to
    the time field (epoch_time of 0 is treated invalid -> falls back)."""
    assert geo.avg_speed([]) == 0.0
    assert geo.avg_speed([Point(time=0, lat=0, lon=0, alt=None, angle=None)]) == 0.0

    zero_dt = [
        Point(time=100.0, lat=0.0, lon=0.0, alt=None, angle=None),
        Point(time=100.0, lat=1.0, lon=1.0, alt=None, angle=None),
    ]
    assert math.isnan(geo.avg_speed(zero_dt))

    epoch_pts = [
        GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                 epoch_time=1000.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
        GPSPoint(time=10.0, lat=0.01, lon=0.0, alt=0.0, angle=None,
                 epoch_time=1100.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
    ]
    # 0.01 deg lat ~= 1111 m over 100 epoch-seconds -> ~11.1 m/s (NOT over the 10 s time)
    assert geo.avg_speed(epoch_pts) == pytest.approx(11.1, abs=0.5)

    zero_epoch_pts = [
        GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                 epoch_time=0.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
        GPSPoint(time=10.0, lat=0.001, lon=0.0, alt=0.0, angle=None,
                 epoch_time=0.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
    ]
    assert geo.avg_speed(zero_epoch_pts) == pytest.approx(11.1, abs=0.5)


# ===========================================================================
# geo.py: sample_points_by_distance, interpolate_directions_if_none (bundled)
# ===========================================================================
def test_geo_sampling_and_direction_fill():
    """sample_points_by_distance always yields the first sample then only samples
    strictly farther than min_distance from the last yielded one; and
    interpolate_directions_if_none fills each None angle from the bearing to the next
    point (the last None copies the previous angle)."""
    pts = [
        Point(time=1, lat=1, lon=1, alt=1, angle=None),
        Point(time=1, lat=1, lon=1, alt=1, angle=None),
        Point(time=1, lat=1.1, lon=1.1, alt=1, angle=None),
        Point(time=1, lat=2, lon=2, alt=1, angle=None),
    ]
    out = list(geo.sample_points_by_distance(pts, 100000, lambda x: x))
    assert out == [
        Point(time=1, lat=1, lon=1, alt=1, angle=None),
        Point(time=1, lat=2, lon=2, alt=1, angle=None),
    ]

    dirpts = [
        Point(time=1, lat=0, lon=0, alt=1, angle=None),
        Point(time=1, lat=0, lon=1, alt=1, angle=1),
        Point(time=1, lat=1, lon=1, alt=1, angle=2),
        Point(time=1, lat=1, lon=0, alt=1, angle=None),
        Point(time=1, lat=0, lon=0, alt=1, angle=None),
    ]
    geo.interpolate_directions_if_none(dirpts)
    assert [p.angle for p in dirpts] == [90, 1, 2, 180, 180]


# ===========================================================================
# geo.Interpolator (bundled basics)
# ===========================================================================
def test_interpolator_construction_and_query_guards():
    """Interpolator raises ValueError for no non-empty track, for an unsorted track,
    and for a non-monotonic query time after an earlier call."""
    with pytest.raises(ValueError):
        geo.Interpolator([])
    with pytest.raises(ValueError):
        geo.Interpolator([[]])
    with pytest.raises(ValueError):
        geo.Interpolator([[
            Point(time=2, lat=0, lon=0, alt=None, angle=None),
            Point(time=1, lat=0, lon=0, alt=None, angle=None),
        ]])

    track = [
        Point(time=1000.0, lat=10.0, lon=20.0, alt=100, angle=45),
        Point(time=1100.0, lat=10.1, lon=20.1, alt=110, angle=50),
    ]
    interp = geo.Interpolator([track])
    interp.interpolate(1100.0)
    with pytest.raises(ValueError):
        interp.interpolate(1050.0)


def test_interpolator_extrapolation_single_point_and_sort():
    """Interpolator linearly extrapolates before the first and after the last point;
    a single-point track returns that point's coords for any t; and tracks given out
    of order are sorted by start time so the earliest interpolates correctly."""
    track = [
        Point(time=1000.0, lat=10.0, lon=20.0, alt=100, angle=None),
        Point(time=1100.0, lat=10.1, lon=20.1, alt=110, angle=None),
    ]
    before = geo.Interpolator([track]).interpolate(900.0)
    assert before.time == 900.0
    assert before.lat == pytest.approx(9.9)
    assert before.lon == pytest.approx(19.9)
    assert before.alt == pytest.approx(90)

    after = geo.Interpolator([track]).interpolate(1500.0)
    assert after.time == 1500.0
    assert after.lat == pytest.approx(10.5)
    assert after.alt == pytest.approx(150)

    interp = geo.Interpolator([[Point(time=1000.0, lat=90.0, lon=100.0, alt=900, angle=0)]])
    for t in (900.0, 1000.0, 1100.0):
        p = interp.interpolate(t)
        assert p.time == t
        assert p.lat == pytest.approx(90.0)
        assert p.alt == pytest.approx(900)

    track_1 = [Point(time=7000.0, lat=10.0, lon=20.0, alt=None, angle=None),
               Point(time=7200.0, lat=10.2, lon=20.2, alt=None, angle=None)]
    track_3 = [Point(time=8000.0, lat=12.0, lon=22.0, alt=None, angle=None),
               Point(time=8200.0, lat=12.2, lon=22.2, alt=None, angle=None)]
    assert geo.Interpolator([track_3, track_1]).interpolate(7100.0).lat == pytest.approx(10.1)


# --- HARD discriminator: 3-track overlap handoff (subsumes the 2-track case) ---
def test_interpolator_three_track_overlap_handoff():
    """With three mutually-overlapping tracks, the interpolator stays inside the
    earliest track until a query time passes that track's last point, then hands off
    to the next track (and so on), even when the tracks are supplied out of order."""
    t1 = [Point(time=100.0, lat=10.0, lon=0, alt=None, angle=None),
          Point(time=200.0, lat=11.0, lon=0, alt=None, angle=None)]
    t2 = [Point(time=150.0, lat=20.0, lon=0, alt=None, angle=None),
          Point(time=300.0, lat=21.0, lon=0, alt=None, angle=None)]
    t3 = [Point(time=250.0, lat=30.0, lon=0, alt=None, angle=None),
          Point(time=400.0, lat=31.0, lon=0, alt=None, angle=None)]
    interp = geo.Interpolator([t3, t1, t2])
    assert interp.interpolate(150.0).lat == pytest.approx(10.5)    # still in t1
    assert interp.interpolate(250.0).lat == pytest.approx(20.0 + 2.0 / 3.0)  # t1 done -> t2
    assert interp.interpolate(350.0).lat == pytest.approx(30.0 + 2.0 / 3.0)  # t2 done -> t3


# --- HARD discriminator: subtype preservation (kept individual) ---
def test_interpolator_preserves_gps_point_subtype():
    """Interpolating GPSPoints returns a GPSPoint with epoch/precision/ground_speed
    interpolated and fix taken from the start point."""
    track = [
        GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=100.0, angle=0.0,
                 epoch_time=1000.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
        GPSPoint(time=10.0, lat=1.0, lon=1.0, alt=200.0, angle=45.0,
                 epoch_time=1010.0, fix=GPSFix.FIX_3D, precision=2.0, ground_speed=20.0),
    ]
    r = geo.Interpolator([track]).interpolate(5.0)
    assert isinstance(r, GPSPoint)
    assert r.epoch_time == pytest.approx(1005.0)
    assert r.precision == pytest.approx(1.5)
    assert r.ground_speed == pytest.approx(15.0)
    assert r.fix == GPSFix.FIX_3D

    # precision/ground_speed interpolate only when BOTH endpoints have them, else None
    miss = [
        GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=100.0, angle=0.0,
                 epoch_time=1000.0, fix=GPSFix.FIX_3D, precision=None, ground_speed=None),
        GPSPoint(time=10.0, lat=1.0, lon=1.0, alt=200.0, angle=45.0,
                 epoch_time=1010.0, fix=GPSFix.FIX_3D, precision=2.0, ground_speed=20.0),
    ]
    rm = miss[0].interpolate_with(miss[1], 5.0)
    assert isinstance(rm, GPSPoint)
    assert rm.precision is None
    assert rm.ground_speed is None


def test_interpolator_preserves_camm_point_subtype():
    """Interpolating CAMMGPSPoints returns a CAMMGPSPoint with velocity/accuracy
    fields interpolated and gps_fix_type taken from the start point."""
    track = [
        CAMMGPSPoint(time=0.0, lat=0.0, lon=0.0, alt=100.0, angle=0.0,
                     time_gps_epoch=2000.0, gps_fix_type=3, horizontal_accuracy=1.0,
                     vertical_accuracy=2.0, velocity_east=10.0, velocity_north=20.0,
                     velocity_up=5.0, speed_accuracy=0.5),
        CAMMGPSPoint(time=10.0, lat=1.0, lon=1.0, alt=200.0, angle=45.0,
                     time_gps_epoch=2010.0, gps_fix_type=3, horizontal_accuracy=3.0,
                     vertical_accuracy=4.0, velocity_east=20.0, velocity_north=30.0,
                     velocity_up=10.0, speed_accuracy=1.0),
    ]
    r = geo.Interpolator([track]).interpolate(5.0)
    assert isinstance(r, CAMMGPSPoint)
    assert r.time_gps_epoch == pytest.approx(2005.0)
    assert r.gps_fix_type == 3
    assert r.velocity_east == pytest.approx(15.0)
    assert r.speed_accuracy == pytest.approx(0.75)

    # get_gps_epoch_time() returns the epoch only when > 0; a time_gps_epoch of 0 -> None
    assert track[0].get_gps_epoch_time() == pytest.approx(2000.0)
    zero_epoch = CAMMGPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                              time_gps_epoch=0.0, gps_fix_type=3, horizontal_accuracy=1.0,
                              vertical_accuracy=2.0, velocity_east=1.0, velocity_north=2.0,
                              velocity_up=3.0, speed_accuracy=4.0)
    assert zero_epoch.get_gps_epoch_time() is None


# --- HARD discriminator: cross-subtype interpolation fallback ---
def test_interpolate_with_cross_subtype_falls_back_to_plain_point():
    """When `other` is a plain Point (not the same subtype), both GPSPoint and
    CAMMGPSPoint fall back to a plain interpolated geo.Point (no subtype-specific
    fields), while lat/lon still interpolate linearly."""
    g = GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                 epoch_time=1000.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0)
    rg = g.interpolate_with(Point(time=10.0, lat=1.0, lon=1.0, alt=0.0, angle=None), 5.0)
    assert type(rg) is Point
    assert rg.lat == pytest.approx(0.5)

    c = CAMMGPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                     time_gps_epoch=2000.0, gps_fix_type=3, horizontal_accuracy=1.0,
                     vertical_accuracy=2.0, velocity_east=1.0, velocity_north=2.0,
                     velocity_up=3.0, speed_accuracy=4.0)
    rc = c.interpolate_with(Point(time=10.0, lat=1.0, lon=1.0, alt=0.0, angle=None), 5.0)
    assert type(rc) is Point
    assert rc.lat == pytest.approx(0.5)


# --- HARD discriminator: epoch interpolation guards (NEW) ---
def test_interpolator_gps_epoch_extrapolates_and_requires_both_positive():
    """When extrapolating GPSPoints, epoch_time is produced from both endpoints; but
    if either endpoint lacks a positive epoch_time the interpolated epoch is None
    (while lat/lon still interpolate)."""
    both_pos = [
        GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                 epoch_time=1000.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
        GPSPoint(time=10.0, lat=1.0, lon=1.0, alt=0.0, angle=None,
                 epoch_time=1010.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
    ]
    fwd = geo.Interpolator([both_pos]).interpolate(15.0)  # extrapolate past the end
    assert isinstance(fwd, GPSPoint)
    assert fwd.epoch_time == pytest.approx(1015.0)

    one_none = [
        GPSPoint(time=0.0, lat=0.0, lon=0.0, alt=0.0, angle=None,
                 epoch_time=None, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
        GPSPoint(time=10.0, lat=1.0, lon=1.0, alt=0.0, angle=None,
                 epoch_time=1010.0, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=10.0),
    ]
    mid = geo.Interpolator([one_none]).interpolate(5.0)
    assert isinstance(mid, GPSPoint)
    assert mid.epoch_time is None
    assert mid.lat == pytest.approx(0.5)


# ===========================================================================
# CAMM: elst edit-list trimming (bundled basics)
# ===========================================================================
def test_elst_segment_filtering_basics():
    """Through the public extract_camm_info -> edts/elst path: an edit list of only empty
    (media_time=-1) entries shifts every CAMM point by the last empty entry's duration;
    with no entries at all nothing is dropped and the offset is 0 (times unchanged);
    trimming keeps only points inside the advancing segment window
    [media_time, media_time+duration] (start- and end-inclusive), drops those before the
    start, advances past those after the end, and shifts survivors by the empty-entry
    offset. (Decoded CAMM point times are rebased so the first point is at 0.) Also checks
    the public elst_entry_to_seconds conversion the trimming runs on."""
    # Only empty edits -> global offset = last empty duration, nothing dropped.
    out = _encode_decode_camm_with_elst(
        [Point(time=t, lat=0.01, lon=0.2, alt=None, angle=None)
         for t in (0.0, 0.13, 0.19, 0.21)],
        [_elst_entry(-1, 3.0), _elst_entry(-1, 4.4)])
    assert _camm_gps_times(out) == [4.4, 4.53, 4.59, 4.61]

    # No edits at all -> passthrough, offset 0.
    out2 = _encode_decode_camm_with_elst(
        [Point(time=t, lat=0.01, lon=0.2, alt=None, angle=None) for t in (0.0, 0.5)], [])
    assert _camm_gps_times(out2) == [0.0, 0.5]

    # Boundaries inclusive at both ends, no empty edits -> offset 0. Window [0.10, 0.30]
    # drops the 0.0 point (before the start) and keeps 0.10/0.20/0.30 (end-inclusive).
    out3 = _encode_decode_camm_with_elst(
        [Point(time=t, lat=0.01, lon=0.2, alt=None, angle=None)
         for t in (0.0, 0.10, 0.20, 0.30)],
        [_elst_entry(0.10, 0.20)])
    assert _camm_gps_times(out3) == [0.1, 0.2, 0.3]

    # The conversion helper the trimming runs on, with UNEQUAL timescales so the two
    # divisors are distinguishable: media_time is divided by the MEDIA timescale while
    # segment_duration is divided by the MOVIE timescale; the -1 sentinel passes through
    # unchanged; a non-positive timescale is rejected.
    assert camm_parser.elst_entry_to_seconds(
        {"media_time": -1, "segment_duration": 3000}, 1000, 500) == (-1, 3.0)
    assert camm_parser.elst_entry_to_seconds(
        {"media_time": 1000, "segment_duration": 3000}, 1000, 500) == (2.0, 3.0)
    with pytest.raises(AssertionError):
        camm_parser.elst_entry_to_seconds(
            {"media_time": 0, "segment_duration": 1000}, 0, 500)


# --- HARD discriminator: multi-segment + offset interplay (NEW) ---
def test_elst_multi_segment_with_empty_edit_offset():
    """Through extract_camm_info, an edit list combining one empty edit (which sets the
    global offset) with two real segments survives only the CAMM points falling inside
    each successive segment window, advancing monotonically, and shifts each survivor by
    the offset."""
    out = _encode_decode_camm_with_elst(
        [Point(time=t, lat=0.01, lon=0.2, alt=None, angle=None)
         for t in (0.0, 0.10, 0.20, 0.30, 0.40)],
        [_elst_entry(-1, 2.0), _elst_entry(0.05, 0.10), _elst_entry(0.25, 0.10)])
    # 0.0 before seg0 -> dropped; 0.10 in seg0 [0.05,0.15] -> +2.0;
    # 0.20 past seg0 -> advance; 0.30 in seg1 [0.25,0.35] -> +2.0; 0.40 past -> dropped
    assert _camm_gps_times(out) == [2.1, 2.3]


# --- HARD discriminator: a point past seg0 is consumed to ADVANCE the segment index
#     and is NOT re-tested against seg1 (kept individual) ---
def test_elst_measurement_past_first_segment_is_not_retested_against_second():
    """Through extract_camm_info, the walk advances monotonically through BOTH points and
    segments: a point that lies *after* the current segment's end advances the segment
    index and is itself consumed (the walk moves on to the next point) — it is NOT
    re-checked against the now-current later segment. So a point that falls inside a later
    segment, but only after passing an earlier one, is dropped, not emitted. (Decoded CAMM
    point times rebase so the first point is at 0.)"""
    # 0.0 is before seg0 [0.05,0.15] (dropped); 0.30 lies past seg0, so reaching it advances
    # the index to seg1 [0.25,0.35] but 0.30 itself is consumed (not retested) -> nothing
    # survives, even though 0.30 falls inside seg1.
    out = _encode_decode_camm_with_elst(
        [Point(time=t, lat=0.01, lon=0.2, alt=None, angle=None) for t in (0.0, 0.30)],
        [_elst_entry(0.05, 0.10), _elst_entry(0.25, 0.10)])
    assert _camm_gps_times(out) == []

    # With an empty-edit offset of 5.0 and four points: 0.0 is before seg0 (dropped); 0.10 is
    # inside seg0 [0.05,0.15] (-> +5.0); 0.30 is past seg0 so it advances the index and is
    # consumed (dropped); 0.31 is then inside seg1 [0.25,0.35] (-> +5.0). The 0.30 that
    # "passed through" a later window after advancing is NOT recovered.
    out2 = _encode_decode_camm_with_elst(
        [Point(time=t, lat=0.01, lon=0.2, alt=None, angle=None)
         for t in (0.0, 0.10, 0.30, 0.31)],
        [_elst_entry(-1, 5.0), _elst_entry(0.05, 0.10), _elst_entry(0.25, 0.10)])
    assert _camm_gps_times(out2) == [5.1, 5.31]


# ===========================================================================
# CAMM: build / parse round-trip (HARD discriminators, kept individual)
# ===========================================================================
def test_camm_roundtrip_mini_gps_points():
    """A CAMM track of plain geo.Points round-trips: a leading negative-time point
    is dropped and altitudes default to -1.0."""
    points = [
        Point(time=-0.1, lat=0.01, lon=0.2, alt=None, angle=None),
        Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
        Point(time=0.23, lat=0.001, lon=0.21, alt=None, angle=None),
    ]
    out = _encode_decode_camm(points)
    assert out is not None
    got = out.gps or out.mini_gps
    assert len(got) == 2
    assert got[0].lat == pytest.approx(0.01)
    assert got[0].alt == pytest.approx(-1.0)
    assert got[0].time == pytest.approx(0.1)


def test_camm_roundtrip_preserves_make_and_model_unicode():
    """extract_camm_info recovers make/model written into udta, including unicode."""
    points = [Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None)]
    out = _encode_decode_camm(points, make="test_make汉字",
                              model="test_model汉字")
    assert out.make == "test_make汉字"
    assert out.model == "test_model汉字"


def test_camm_roundtrip_gps_points_preserve_epoch_and_fix():
    """CAMMGPSPoints (with a positive time_gps_epoch) round-trip through CAMM type-6
    GPS samples, preserving time_gps_epoch, fix type, and velocity fields."""
    points = [
        CAMMGPSPoint(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None,
                     time_gps_epoch=1.2, gps_fix_type=1, horizontal_accuracy=3.3,
                     vertical_accuracy=4.4, velocity_east=5.5, velocity_north=6.6,
                     velocity_up=7.7, speed_accuracy=8.0),
        CAMMGPSPoint(time=0.23, lat=0.001, lon=0.21, alt=None, angle=None,
                     time_gps_epoch=1.3, gps_fix_type=1, horizontal_accuracy=3.3,
                     vertical_accuracy=4.4, velocity_east=5.5, velocity_north=6.6,
                     velocity_up=7.7, speed_accuracy=8.0),
    ]
    out = _encode_decode_camm(points)
    got = out.gps or out.mini_gps
    assert len(got) == 2
    assert isinstance(got[0], CAMMGPSPoint)
    assert got[0].time_gps_epoch == pytest.approx(1.2)
    assert got[0].gps_fix_type == 1
    assert got[0].velocity_north == pytest.approx(6.6)


def test_camm_roundtrip_mixed_min_gps_and_gps_bins_by_type(tmp_path):
    """A track mixing a plain Point (CAMM type-5) and a CAMMGPSPoint (type-6)
    round-trips: both are collected (as geo.Point subclasses) but each keeps its
    concrete decoded type, and the type-6 sample preserves its epoch."""
    points = [
        Point(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None),
        CAMMGPSPoint(time=0.2, lat=0.02, lon=0.3, alt=None, angle=None,
                     time_gps_epoch=5.0, gps_fix_type=3, horizontal_accuracy=1.0,
                     vertical_accuracy=2.0, velocity_east=3.0, velocity_north=4.0,
                     velocity_up=5.0, speed_accuracy=6.0),
    ]
    out = _encode_decode_camm(points)
    got = sorted((out.gps or []) + (out.mini_gps or []), key=lambda p: p.time)
    assert len(got) == 2
    assert type(got[0]) is Point
    assert isinstance(got[1], CAMMGPSPoint)
    assert got[1].time_gps_epoch == pytest.approx(5.0)
    assert got[1].velocity_north == pytest.approx(4.0)
    # the type-6 Float32 sample grammar carries the remaining velocity/accuracy fields,
    # and the discrete fix type comes straight through (codec-sensitive)
    assert got[1].velocity_up == pytest.approx(5.0)
    assert got[1].speed_accuracy == pytest.approx(6.0)
    assert got[1].gps_fix_type == 3


# --- HARD discriminator: CAMM type-6 alt default + Float32 precision (NEW) ---
def test_camm_roundtrip_gps_point_alt_default_and_float32_precision():
    """A CAMMGPSPoint with alt=None round-trips through a CAMM type-6 sample with the
    altitude defaulting to -1.0, the discrete fix type preserved (here a 2D fix), and
    every velocity/accuracy field carried through the little-endian Float32 sample
    grammar — so values not exactly representable in 32-bit float (e.g. 0.1) come back
    quantized to their Float32 round-trip rather than their original Float64 value."""
    points = [
        CAMMGPSPoint(time=0.1, lat=0.01, lon=0.2, alt=None, angle=None,
                     time_gps_epoch=1.2, gps_fix_type=2, horizontal_accuracy=0.1,
                     vertical_accuracy=0.2, velocity_east=0.3, velocity_north=0.0,
                     velocity_up=7.875, speed_accuracy=8.125),
    ]
    out = _encode_decode_camm(points)
    got = out.gps or out.mini_gps
    assert len(got) == 1
    g = got[0]
    assert isinstance(g, CAMMGPSPoint)
    # alt unknown -> defaults to -1.0
    assert g.alt == pytest.approx(-1.0)
    # discrete fix type taken straight through (a 2D fix, not 3)
    assert g.gps_fix_type == 2
    # exactly-representable Float32 values survive bit-for-bit
    assert g.velocity_up == pytest.approx(7.875)
    assert g.speed_accuracy == pytest.approx(8.125)
    # 0.1 is NOT exactly representable in float32 -> comes back as the float32 round-trip
    f32 = struct.unpack("<f", struct.pack("<f", 0.1))[0]
    assert g.horizontal_accuracy == pytest.approx(f32)
    assert g.horizontal_accuracy != 0.1


def test_prepare_camm_info_zero_epoch_gps_point_goes_to_mini_gps():
    """prepare_camm_info promotes a GPSPoint to a CAMM type-6 gps entry only when
    epoch_time > 0; an epoch_time of exactly 0 routes it to mini_gps instead."""
    metadata = types.VideoMetadata(
        Path(""), filetype=types.FileType.CAMM,
        points=[GPSPoint(time=0.1, lat=0.01, lon=0.2, alt=10.0, angle=None,
                         epoch_time=0.0, fix=GPSFix.FIX_3D, precision=1.0,
                         ground_speed=1.0)],
        make="", model="")
    camm_info = uploader.VideoUploader.prepare_camm_info(metadata)
    assert camm_info.gps is None
    assert camm_info.mini_gps is not None and len(camm_info.mini_gps) == 1


def test_camm_extract_returns_none_for_non_camm_mp4():
    """extract_camm_info returns None when the MP4 has no CAMM track."""
    mvhd = {"type": b"mvhd",
            "data": {"creation_time": 1, "modification_time": 2,
                     "timescale": 1000, "duration": 1000}}
    src = cparser.MP4WithoutSTBLBuilderConstruct.build_boxlist(
        [{"type": b"ftyp", "data": b"test"}, {"type": b"moov", "data": [mvhd]}])
    assert camm_parser.extract_camm_info(io.BytesIO(src)) is None


# --- HARD discriminator: make/model udta variants (codec) ---
def test_camm_make_model_udta_variants():
    """extract_camm_info recovers make/model from the non-@ udta variants: RICOH
    `manu`/`modl` carry the value as raw UTF-8, while Insta360 `\xa9mak`/`\xa9mod`
    use the size-prefixed grammar (uint16-big size, 2 reserved bytes, then the UTF-8
    string, trailing NULs stripped)."""
    ricoh = _encode_decode_camm_with_udta(
        (b"manu", "RICOH".encode("utf-8")),
        (b"modl", "THETA V".encode("utf-8")))
    assert (ricoh.make, ricoh.model) == ("RICOH", "THETA V")

    def size_prefixed(s: str) -> bytes:
        b = s.encode("utf-8")
        # uint16 big-endian size + 2 reserved bytes + data (+ a trailing NUL to verify
        # NUL stripping)
        return struct.pack(">H", len(b)) + b"\x00\x00" + b + b"\x00"

    insta = _encode_decode_camm_with_udta(
        (b"\xa9mak", size_prefixed("InstaMake")),
        (b"\xa9mod", size_prefixed("InstaModel")))
    assert (insta.make, insta.model) == ("InstaMake", "InstaModel")


# --- HARD discriminator: ACCL/GYRO/MAGN telemetry round-trip (codec) ---
def test_camm_accl_gyro_magn_telemetry_roundtrip():
    """A CAMM track carrying AccelerationData/GyroscopeData/MagnetometerData round-trips
    through the build->parse cycle: extract_camm_info(telemetry_only=True) decodes each
    little-endian Float32 XYZ measurement into the matching accl/gyro/magn bin with x/y/z
    preserved."""
    camm_info = camm_parser.CAMMInfo(
        accl=[telemetry.AccelerationData(time=0.1, x=1.0, y=2.0, z=3.0)],
        gyro=[telemetry.GyroscopeData(time=0.2, x=4.0, y=5.0, z=6.0)],
        magn=[telemetry.MagnetometerData(time=0.3, x=7.0, y=8.0, z=9.0)],
    )
    out = _encode_decode_camm_telemetry(camm_info)
    assert out is not None
    assert len(out.accl) == 1 and len(out.gyro) == 1 and len(out.magn) == 1
    assert (out.accl[0].x, out.accl[0].y, out.accl[0].z) == pytest.approx((1.0, 2.0, 3.0))
    assert (out.gyro[0].x, out.gyro[0].y, out.gyro[0].z) == pytest.approx((4.0, 5.0, 6.0))
    assert (out.magn[0].x, out.magn[0].y, out.magn[0].z) == pytest.approx((7.0, 8.0, 9.0))


# ===========================================================================
# GoPro GPMF: GPS5 / GPS9 decode through the public extract_gopro_info surface
# (an in-memory `gpmd` MP4 carrying the GPMF KLV stream, mirroring the CAMM round-trip).
# ===========================================================================
# --- HARD discriminator (kept individual) ---
def test_gpmf_gps5_scales_coordinates_and_reads_fix():
    """Through extract_gopro_info, a GPS5 stream divides each raw column by its SCAL
    divisor and maps GPSF to a GPSFix enum."""
    info = _gopro_from_strms([_gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[10000000], [10000000], [1000], [1000], [100]],
        gpsf=[[3]], gpsp=[[219]])])
    assert info is not None and len(info.gps) == 1
    assert info.gps[0].lat == pytest.approx(47.3598318, abs=1e-7)
    assert info.gps[0].lon == pytest.approx(8.5227055, abs=1e-7)
    assert info.gps[0].alt == pytest.approx(414.87, abs=0.01)
    assert info.gps[0].fix == GPSFix.FIX_3D
    assert info.gps[0].precision == 219


def test_gpmf_gps5_zero_scale_and_invalid_gpsu():
    """Zero-SCAL handling on BOTH GPS paths through extract_gopro_info: a GPS5 stream
    yields no points when any SCAL divisor is zero, and so does the packed-bytes GPS9
    path; plus a GPS5 point gets epoch_time None when the GPSU timestamp is missing or
    unparseable, and GPSF=0 maps through GPSFix to NO_FIX."""
    zero_scale = _gopro_from_strms([_gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[10000000], [0], [1000], [1000], [100]])])
    assert zero_scale.gps == []

    # Same zero-SCAL rule on the GPS9 packed path: a zero divisor in any column makes
    # the whole sample unusable, so nothing is decoded.
    gps9 = struct.pack(">iiiiiiiHH",
                       510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3)
    zero_scale_gps9 = _gopro_from_strms([_gps9_strm(
        [gps9], scal=[[10000000], [0], [1000], [1000], [100], [1], [1000], [100], [1]])])
    assert zero_scale_gps9.gps == []

    bad_gpsu = _gopro_from_strms([_gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[10000000], [10000000], [1000], [1000], [100]],
        gpsu=[[b"not_a_timestamp!"]])])  # 16-byte but unparseable -> epoch None
    assert bad_gpsu.gps[0].epoch_time is None

    # GPSF=0 maps through GPSFix(value) to NO_FIX on the GPS5 path.
    no_fix = _gopro_from_strms([_gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[10000000], [10000000], [1000], [1000], [100]],
        gpsf=[[0]])])
    assert no_fix.gps[0].fix == GPSFix.NO_FIX


# --- HARD discriminator: valid GPSU exact epoch (kept individual) ---
def test_gpmf_gps5_valid_gpsu_parses_exact_utc_epoch():
    """A valid GPSU 'YYMMDDhhmmss.sss' timestamp is parsed to the exact UTC epoch for
    epoch_time (not merely left as None). A single GPS5 point keeps its GPSU-derived
    epoch through extract_gopro_info's forward/backward backfill."""
    info = _gopro_from_strms([_gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[10000000], [10000000], [1000], [1000], [100]],
        gpsu=[[b"220731002523.200"]])])
    expected = datetime.datetime(
        2022, 7, 31, 0, 25, 23, 200000, tzinfo=datetime.timezone.utc).timestamp()
    assert info.gps[0].epoch_time == pytest.approx(expected, abs=1e-3)


# --- HARD discriminator: GPS9 preferred over GPS5 (kept individual) ---
def test_gpmf_find_first_gps_stream_prefers_gps9_over_gps5():
    """GPS9 is tried before GPS5 within a STRM, so a GPS9 sample wins even when present
    alongside the older GPS5 schema."""
    gps9_bytes = struct.pack(">iiiiiiiHH",
                             510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3)
    strm = _gpmf_nested(b"STRM", [
        _gpmf_klv(b"TYPE", [b"lllllllSS"], b"c"),
        _gpmf_klv(b"SCAL", [[10000000], [10000000], [1000], [1000], [100],
                            [1], [1000], [100], [1]], b"l"),
        _gpmf_klv(b"GPS9", [gps9_bytes], b"?"),
        _gpmf_klv(b"GPS5", [[473598318, 85227055, 414870, 891, 119]], b"l"),
    ])
    info = _gopro_from_strms([strm])
    assert len(info.gps) == 1
    assert info.gps[0].lat == pytest.approx(51.0776007, abs=1e-6)  # GPS9 value, not GPS5


# --- HARD discriminator: first non-empty STRM wins across multiple STRMs (NEW) ---
def test_gpmf_find_first_gps_stream_returns_first_nonempty_strm():
    """STRMs are scanned in order and the FIRST one that yields points wins. With a
    leading GPS5-only STRM followed by a GPS9 STRM, the GPS5 STRM wins (it is non-empty
    first) — so the result is the GPS5-decoded coordinate, not the later GPS9 sample's."""
    gps9 = struct.pack(">iiiiiiiHH",
                       510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3)
    strm5 = _gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[10000000], [10000000], [1000], [1000], [100]])
    strm9 = _gps9_strm(
        [gps9], scal=[[10000000], [10000000], [1000], [1000], [100], [1], [1000], [100], [1]])
    info = _gopro_from_strms([strm5, strm9])
    assert len(info.gps) == 1
    assert info.gps[0].lat == pytest.approx(47.3598318, abs=1e-7)  # GPS5 STRM (first) wins


# --- HARD discriminator: GPS9 wrong TYPE length + multi-sample packed decode ---
def test_gpmf_gps9_wrong_type_length_raises():
    """GPS9 decode raises ValueError if the TYPE string does not declare 9 values; and
    with a correct 9-type string it decodes EVERY packed sample in a multi-sample GPS9
    KLV (two struct-packed rows -> two points with independently scaled fields)."""
    sample = struct.pack(">iiiiiiiHH",
                         510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3)
    with pytest.raises(ValueError, match="9 types"):
        _gopro_from_strms([_gps9_strm([sample], scal=[[10000000]] * 9, type_str=b"llll")])

    # A correct 9-type string with two packed rows -> two decoded points, each scaled
    # from its own struct-unpacked columns (second row has a distinct lat and a 2D fix).
    row0 = struct.pack(">iiiiiiiHH",
                       510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 3)
    row1 = struct.pack(">iiiiiiiHH",
                       510776100, 62268500, 90000, 300, 50, 9463, 44897000, 200, 2)
    info = _gopro_from_strms([_gps9_strm(
        [row0, row1],
        scal=[[10000000], [10000000], [1000], [1000], [100], [1], [1000], [100], [1]])])
    assert len(info.gps) == 2
    assert info.gps[0].lat == pytest.approx(51.0776007, abs=1e-7)
    assert info.gps[1].lat == pytest.approx(51.07761, abs=1e-7)
    assert info.gps[0].fix == GPSFix.FIX_3D
    assert info.gps[1].fix == GPSFix.FIX_2D


# --- HARD discriminator: GPS9 precision/fields scaled (kept individual) ---
def test_gpmf_gps9_precision_is_dop_times_100_and_fields_scaled():
    """GPS9 decode scales each column by SCAL, derives epoch_time from the
    days/secs-since-2000 columns, sets precision = DOP*100, ground_speed from the
    2D-speed column, and fix from the (scaled) fix column. The altitude column is a
    below-sea-level (negative) `l` value, so the signed int32 type char must decode as
    signed; the seconds-since-midnight column scales to a FRACTIONAL value, so the epoch
    keeps its sub-second part."""
    # lat, lon, alt, 2Dspeed, 3Dspeed, days_since_2000, secs_since_midnight, DOP, fix
    sample = struct.pack(">iiiiiiiHH",
                         510776007, 62268453, -125000, 295, 42, 9463, 44896123, 185, 3)
    info = _gopro_from_strms([_gps9_strm(
        [sample],
        scal=[[10000000], [10000000], [1000], [1000], [100], [1], [1000], [1], [1]])])
    assert len(info.gps) == 1
    assert info.gps[0].alt == pytest.approx(-125.0)            # -125000 / 1000 (signed int32)
    assert info.gps[0].precision == pytest.approx(185 * 100)   # DOP (185/1) * 100
    assert info.gps[0].ground_speed == pytest.approx(0.295)    # 295 / 1000
    assert info.gps[0].fix == GPSFix.FIX_3D
    expected_epoch = datetime.datetime(2000, 1, 1, tzinfo=datetime.timezone.utc).timestamp()
    expected_epoch += 9463 * 86400 + 44896.123                 # 44896123 / 1000 (sub-second)
    assert info.gps[0].epoch_time == pytest.approx(expected_epoch, abs=1e-3)


# --- HARD discriminator: GPS9 TYPE mix forces a real per-value struct (NEW) ---
def test_gpmf_gps9_mixed_type_string_drives_per_value_struct():
    """The GPS9 TYPE string declares a *heterogeneous* per-value layout — here altitude
    is a signed 16-bit value ('s') while the surrounding columns are 32-bit ints ('l')
    and the trailing DOP/fix are unsigned 16-bit ('S'). Decoding must build the
    per-value struct from the TYPE string (not assume a uniform width), so the sample
    bytes packed as '>iihiiiiHH' unpack to the right columns: a negative int16 altitude
    decodes correctly and the later columns are not mis-aligned."""
    # lat,lon ('l'), alt ('s', signed int16, 2 bytes), 2Dspeed,3Dspeed,days,secs ('l'),
    # DOP,fix ('S', uint16)
    sample = struct.pack(">iihiiiiHH",
                         510776007, 62268453, -3200, 295, 42, 9463, 44896000, 185, 3)
    info = _gopro_from_strms([_gps9_strm(
        [sample],
        scal=[[10000000], [10000000], [100], [1000], [100], [1], [1000], [100], [1]],
        type_str=b"llsllllSS")])
    assert len(info.gps) == 1
    assert info.gps[0].lat == pytest.approx(51.0776007, abs=1e-7)
    assert info.gps[0].lon == pytest.approx(6.2268453, abs=1e-7)
    assert info.gps[0].alt == pytest.approx(-32.0)            # -3200 / 100 (signed int16)
    assert info.gps[0].ground_speed == pytest.approx(0.295)   # columns stayed aligned
    assert info.gps[0].precision == pytest.approx(185.0)       # DOP 185/100 * 100
    assert info.gps[0].fix == GPSFix.FIX_3D


# --- HARD discriminator: multi-STRM GPS9 selection with packed decode (NEW) ---
def test_gpmf_find_first_gps_stream_skips_empty_then_decodes_gps9():
    """Decode returns the first STRM that yields points: a leading STRM whose only GPS
    source is unusable (a GPS5 with a zero SCAL divisor -> nothing) is skipped, and the
    next STRM's packed GPS9 sample is decoded and returned, with a fix value of 0 mapping
    to NO_FIX through the scaled fix column."""
    bad_strm = _gps5_strm(
        gps5=[[473598318, 85227055, 414870, 891, 119]],
        scal=[[0], [10000000], [1000], [1000], [100]])
    gps9 = struct.pack(">iiiiiiiHH",
                       510776007, 62268453, 85454, 295, 42, 9463, 44896000, 185, 0)
    good_strm = _gps9_strm(
        [gps9], scal=[[10000000], [10000000], [1000], [1000], [100], [1], [1000], [100], [1]])
    info = _gopro_from_strms([bad_strm, good_strm])
    assert len(info.gps) == 1
    assert info.gps[0].lat == pytest.approx(51.0776007, abs=1e-6)
    assert info.gps[0].fix == GPSFix.NO_FIX


# ===========================================================================
# GoPro GPMF: epoch backfill (forward + backward) through extract_gopro_info
# ===========================================================================
def test_gpmf_backfill_forward_and_backward():
    """extract_gopro_info backfills missing GPS epoch_times forward from the first point
    that has one (delta = point.time - last.time) and then backward from it. With three
    GPS5 samples whose epoch anchor is the FIRST sample, the later samples are filled
    forward; with the anchor on the LAST sample, the earlier ones are filled backward."""
    def gps5_point(gpsu=None):
        return _gps5_strm(
            gps5=[[473598318, 85227055, 414870, 891, 119]],
            scal=[[10000000], [10000000], [1000], [1000], [100]],
            gpsu=[[gpsu]] if gpsu is not None else None)

    def gpsu_for_epoch(epoch_sec):
        dt = datetime.datetime.fromtimestamp(epoch_sec, tz=datetime.timezone.utc)
        return dt.strftime("%y%m%d%H%M%S.%f")[:-3].encode("utf-8")  # 16-byte yymmddhhmmss.sss

    # FORWARD: sample0 @t=0 has epoch 1000; samples @t=1, t=3 have none -> filled to 1001, 1003.
    fwd = extract_gopro_info(T.cast(T.BinaryIO, _build_gpmd_mp4(
        [[_devc([gps5_point(gpsu_for_epoch(1000.0))])],
         [_devc([gps5_point()])],
         [_devc([gps5_point()])]],
        sample_times=[0.0, 1.0, 3.0])))
    assert [p.epoch_time for p in fwd.gps] == pytest.approx([1000.0, 1001.0, 1003.0], abs=1e-3)

    # BACKWARD: samples @t=0, t=1 have none; sample @t=2 has epoch 1002 -> earlier filled 1000, 1001.
    bwd = extract_gopro_info(T.cast(T.BinaryIO, _build_gpmd_mp4(
        [[_devc([gps5_point()])],
         [_devc([gps5_point()])],
         [_devc([gps5_point(gpsu_for_epoch(1002.0))])]],
        sample_times=[0.0, 1.0, 2.0])))
    assert [p.epoch_time for p in bwd.gps] == pytest.approx([1000.0, 1001.0, 1002.0], abs=1e-3)


# ===========================================================================
# GoPro GPMF: device-model priority through extract_gopro_info
# ===========================================================================
def test_gpmf_device_model_priority_and_undecodable():
    """extract_gopro_info derives GoProInfo.model from the device-name (DVNM) boxes: a
    name containing 'hero' wins over 'gopro' and alphabetical order; names that fail
    UTF-8 decoding are skipped; and when none decode the model is ''."""
    def device(dvid, dvnm):
        # only the first device carries GPS; the rest only contribute a DVNM
        strms = [_gps5_strm(gps5=[[473598318, 85227055, 414870, 891, 119]],
                            scal=[[10000000], [10000000], [1000], [1000], [100]])] if dvid == 1 else []
        return _devc(strms, dvid=dvid, dvnm=dvnm)

    hero = extract_gopro_info(T.cast(T.BinaryIO, _build_gpmd_mp4(
        [[device(1, b"GoPro Max"), device(2, b"HERO12 Black")]])))
    assert hero.model == "HERO12 Black"

    skip_undecodable = extract_gopro_info(T.cast(T.BinaryIO, _build_gpmd_mp4(
        [[device(1, b"\xff\xfe"), device(2, b"GoPro Max")]])))
    assert skip_undecodable.model == "GoPro Max"

    all_undecodable = extract_gopro_info(T.cast(T.BinaryIO, _build_gpmd_mp4(
        [[device(1, b"\xff\xfe"), device(2, b"\x80\x81")]])))
    assert all_undecodable.model == ""


# ===========================================================================
# gps_filter: GPS noise removal through the public remove_noisy_points surface
# ===========================================================================
def test_gps_filter_remove_noisy_points_via_public_surface():
    """gpmf_gps_filter.remove_noisy_points (the noise filter the NATIVE video extractor
    actually calls) drops GPS points through every layer: a point without a usable GPS fix
    is removed, a point with an excessive DOP/precision is removed, and a far + fast outlier
    is removed as a statistical outlier (Tukey upper-whisker distance split + DBSCAN
    speed-merge + majority cluster) — leaving the tight, well-fixed main track intact."""
    def gp(t, lat, fix=GPSFix.FIX_3D, precision=1.0, ground_speed=1.0):
        return GPSPoint(time=float(t), lat=lat, lon=0.0, alt=10.0, angle=None,
                        epoch_time=float(t), fix=fix, precision=precision,
                        ground_speed=ground_speed)

    # A tight, slow, well-fixed cluster (~11 m apart) is the majority and must survive.
    sequence = [gp(i, 0.0001 * i) for i in range(8)]
    # A far (~140 m), fast jump is a statistical outlier and must be filtered out.
    sequence.append(gp(8, 0.002, ground_speed=50.0))
    # A point without a usable fix (NO_FIX) is dropped by the fix filter.
    sequence.append(gp(9, 0.0009, fix=GPSFix.NO_FIX))
    # A point with an excessive DOP-derived precision is dropped by the precision filter.
    sequence.append(gp(10, 0.0010, precision=5000.0))

    survivors = gpmf_gps_filter.remove_noisy_points(sequence)

    assert [p.time for p in survivors] == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    assert all(p.fix == GPSFix.FIX_3D for p in survivors)
    assert all(p.precision is not None and p.precision <= 1000 for p in survivors)


# ===========================================================================
# BlackVue: NMEA parsing + timezone offset inference
# ===========================================================================
def test_blackvue_gga_decode_and_rmc_offset_via_extract():
    """Through the public extract_blackvue_info surface: a GGA box decodes lat/lon, a 3D
    fix (quality >= 1) and altitude with the ms-epoch in epoch_time (time rebased to
    0.0); and an RMC box applies the RMC-derived full-date UTC offset to epoch_time,
    preferring RMC over any GGA when both are present."""
    gga = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        b"[1623057074211]$GPGGA,202530.25,5109.0262,N,11401.8407,W,5,40,0.5,1097.36,M,-17.00,M,18,TSTR*66\n")))
    assert gga is not None and gga.make == "BlackVue"
    assert len(gga.gps) == 1
    assert gga.gps[0].lat == pytest.approx(51.150436666666664)
    assert gga.gps[0].lon == pytest.approx(-114.03067833333333)
    assert gga.gps[0].time == 0.0  # rebased
    assert gga.gps[0].epoch_time == pytest.approx(1623097530.25)  # absolute ms-epoch
    assert gga.gps[0].alt == pytest.approx(1097.36)
    assert gga.gps[0].fix == GPSFix.FIX_3D

    # A GGA appears first but RMC wins precedence; the RMC offset (3h) lands in epoch_time.
    rmc = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        b"[1623057130258]$GPGGA,201205.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6F\n"
        b"[1637762688000]$GPRMC,110448.00,A,3853.16949,N,07659.54604,W,5.849,284.43,241121,,,D*7D\n"
        b"[1637762689000]$GPRMC,110449.00,A,3853.16950,N,07659.54605,W,5.850,284.44,241121,,,D*7A\n")))
    assert len(rmc.gps) == 2  # RMC points only, not the GGA
    assert rmc.gps[0].epoch_time == pytest.approx(1637751888.0)  # 3h offset removed
    assert rmc.gps[1].epoch_time - rmc.gps[0].epoch_time == pytest.approx(1.0)
    assert rmc.gps[0].fix is None  # RMC carries no fix


def test_blackvue_gga_only_day_boundary_both_directions_via_extract():
    """Through extract_blackvue_info, the no-RMC GGA time-only fallback resolves the day
    boundary in epoch_time: a late-night camera clock that rolled into the next UTC day
    adds a day; an early-morning clock still on the previous UTC day subtracts a day.
    GLL is the lowest-preference sentence and carries no altitude/fix."""
    next_day = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        b"[1637794800000]$GPGGA,010000.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6A\n")))
    assert next_day.gps[0].time == 0.0  # rebased to first point under a GGA-only source
    assert next_day.gps[0].epoch_time == pytest.approx(1637802000.0)

    prev_day = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        b"[1637802000000]$GPGGA,230000.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6A\n")))
    assert prev_day.gps[0].epoch_time == pytest.approx(1637794800.0)

    gll = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        b"[1629874404069]$GNGLL,4404.14012,N,12118.85993,W,001037.00,A,A*67\n")))
    assert len(gll.gps) == 1
    assert gll.gps[0].alt is None and gll.gps[0].fix is None


# --- HARD discriminator: RMC wins over an earlier GGA + out-of-order sort (NEW) ---
def test_blackvue_rmc_wins_over_earlier_gga_and_times_are_sorted_then_rebased():
    """Even when a GGA line appears *first* in the byte stream, RMC still wins the
    sentence-type precedence; and because the surviving RMC points are time-sorted
    before rebasing, two RMC lines given out of camera-epoch order come back in
    ascending order with the first rebased to 0.0 (epoch_time stays absolute) and RMC
    carrying no fix."""
    gps_data = (
        # GGA appears first but must NOT win the precedence
        b"[1623057130258]$GPGGA,201205.00,3853.16949,N,07659.54604,W,2,10,0.82,7.7,M,-34.7,M,,0000*6F\n"
        # two RMC lines OUT of camera-epoch order -> must be sorted ascending
        b"[1623057132256]$GPRMC,201208.00,A,3853.16949,N,07659.54604,W,5.849,284.43,070621,,,D*7B\n"
        b"[1623057129256]$GPRMC,201205.00,A,3853.16949,N,07659.54604,W,5.849,284.43,070621,,,D*76\n"
    )
    info = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(gps_data)))
    assert info is not None and info.make == "BlackVue"
    assert len(info.gps) == 2  # RMC points only, not the GGA
    assert info.gps[0].time == 0.0
    assert info.gps[1].time == pytest.approx(3.0)  # 3s apart, ascending after sort
    assert info.gps[0].epoch_time == pytest.approx(1623096725.0)  # absolute, RMC offset
    assert info.gps[1].epoch_time == pytest.approx(1623096728.0)
    assert info.gps[0].fix is None and info.gps[1].fix is None  # RMC has no fix


def test_blackvue_cprt_model_and_missing_gps_box():
    """Through the public extract_blackvue_info surface (a free/gps box followed by a
    free/cprt box): the camera model is read from a JSON cprt blob (NUL padding stripped
    first) or from the second semicolon-delimited field; and extract_blackvue_info returns
    None when there is no free/gps box at all."""
    gga = b"[1623057074211]$GPGGA,202530.25,5109.0262,N,11401.8407,W,5,40,0.5,1097.36,M,-17.00,M,18,TSTR*66\n"

    json_info = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        gga, cprt=b' {"model":"DR900X Plus","ver":0.918}\x00\x00\x00')))
    assert json_info is not None and json_info.model == "DR900X Plus"

    semicolon_info = blackvue_parser.extract_blackvue_info(io.BytesIO(_build_blackvue_mp4(
        gga, cprt=b" Pittasoft Co., Ltd.;DR900S-1CH;1.008;English;1;")))
    assert semicolon_info.model == "DR900S-1CH"

    # No free/gps box (only a free/cprt box) -> None.
    src = cparser.Box32ConstructBuilder({b"free": {}}).Box.build(
        {"type": b"free", "data": [{"type": b"cprt", "data": b"x"}]})
    assert blackvue_parser.extract_blackvue_info(io.BytesIO(src)) is None


# ===========================================================================
# process_sequence_properties: grouping & splitting (bundled)
# ===========================================================================
def test_sequence_split_aggregate_predicate(tmp_path):
    """Splitting is an aggregate predicate over time gap, running image count, and
    cumulative filesize/pixels: a 60s+ time gap splits a folder into two; 1001 images
    exceed MAX_SEQUENCE_LENGTH and split; a 110-GiB image splits on cumulative
    filesize; and a 6e9-pixel image isolates on cumulative pixels."""
    by_time = [
        _make_image(tmp_path, "a.jpg", 1, 1, 1),
        _make_image(tmp_path, "b.jpg", 1.00001, 1.00001, 600),
        _make_image(tmp_path, "c.jpg", 1.00002, 1.00002, 601),
    ]
    out = psp.process_sequence_properties(by_time)
    assert len({m.MAPSequenceUUID for m in out if isinstance(m, types.ImageMetadata)}) == 2

    by_count = [_make_image(tmp_path, f"a{i}.jpg", 1 + i * 1e-5, 1 + i * 1e-5, i)
                for i in range(1, 1002)]
    out2 = psp.process_sequence_properties(by_count)
    assert len({m.MAPSequenceUUID for m in out2 if isinstance(m, types.ImageMetadata)}) == 2

    by_filesize = [
        _make_image(tmp_path, "fa.jpg", 2, 2, 1, filesize=110 * 1024 ** 3),
        _make_image(tmp_path, "fb.jpg", 2.00001, 2.00001, 2, filesize=1),
        _make_image(tmp_path, "fc.jpg", 2.00002, 2.00002, 2, filesize=1),
    ]
    out3 = psp.process_sequence_properties(by_filesize)
    assert len({m.MAPSequenceUUID for m in out3 if isinstance(m, types.ImageMetadata)}) == 2

    by_pixels = [
        _make_image(tmp_path, "p_a.jpg", 2, 2, 1, angle=344, width=2, height=2),
        _make_image(tmp_path, "p_b.jpg", 2.00001, 2.00001, 20, angle=344, width=2, height=2),
        _make_image(tmp_path, "p_c.jpg", 2.00002, 2.00002, 30, angle=344,
                    width=int(6e9), height=2),
    ]
    out4 = psp.process_sequence_properties(
        by_pixels, cutoff_distance=1000000000, cutoff_time=100,
        interpolate_directions=True, duplicate_distance=1, duplicate_angle=5)
    assert len({m.MAPSequenceUUID for m in out4 if isinstance(m, types.ImageMetadata)}) == 2


# --- HARD discriminator: distance split runs after speed check (NEW) ---
def test_sequence_distance_split_after_speed_check(tmp_path):
    """Distance splitting runs LATE (after the speed check), splitting surviving
    sequences wherever the gap between consecutive points exceeds cutoff_distance."""
    seq = [
        _make_image(tmp_path, "c.jpg", 1, 1, 1),
        _make_image(tmp_path, "a.jpg", 1.00001, 1.00001, 2),
        _make_image(tmp_path, "foo_b.jpg", 1.00090, 1.00090, 3),
        _make_image(tmp_path, "foo_a.jpg", 1.00091, 1.00091, 4),
    ]
    out = psp.process_sequence_properties(
        seq, cutoff_distance=100, cutoff_time=10,
        duplicate_distance=0, duplicate_angle=0)
    assert len({m.MAPSequenceUUID for m in out if isinstance(m, types.ImageMetadata)}) == 2


def test_sequence_grouping_uuids_and_count(tmp_path):
    """Images sharing make/model but differing in MAPCameraUUID (including a None
    uuid) form distinct sequences; and a single clean run returns exactly as many
    results as inputs, all sharing one assigned MAPSequenceUUID."""
    common = dict(MAPDeviceMake="Canon", MAPDeviceModel="EOS R5",
                  width=1920, height=1080)
    grouped = [
        _make_image(tmp_path, "1.jpg", 1.00001, 1.00001, 1, MAPCameraUUID="A", **common),
        _make_image(tmp_path, "2.jpg", 1.00002, 1.00002, 2, MAPCameraUUID="A", **common),
        _make_image(tmp_path, "3.jpg", 1.00003, 1.00003, 3, MAPCameraUUID="B", **common),
        _make_image(tmp_path, "5.jpg", 1.00005, 1.00005, 5, MAPCameraUUID=None, **common),
    ]
    out = psp.process_sequence_properties(
        grouped, cutoff_distance=1000000, cutoff_time=10000,
        duplicate_distance=0, duplicate_angle=0)
    assert len({m.MAPSequenceUUID for m in out if isinstance(m, types.ImageMetadata)}) == 3

    seq = [
        _make_image(tmp_path, "a.jpg", 1, 1, 1),
        _make_image(tmp_path, "b.jpg", 1.00001, 1.00001, 2),
        _make_image(tmp_path, "c.jpg", 1.00002, 1.00002, 3),
    ]
    out2 = psp.process_sequence_properties(seq)
    assert len(out2) == len(seq)
    images = [m for m in out2 if isinstance(m, types.ImageMetadata)]
    assert all(m.MAPSequenceUUID is not None for m in images)
    assert len({m.MAPSequenceUUID for m in images}) == 1


# ===========================================================================
# process_sequence_properties: subsec & direction interpolation (bundled)
# ===========================================================================
def test_subsec_and_direction_interpolation(tmp_path):
    """Same-second captures get strictly-increasing sub-second offsets spread evenly
    up to the next distinct timestamp; and interpolate_directions=True clears all
    angles and recomputes every angle from the bearing to the next point."""
    subsec = [
        _make_image(tmp_path, "a.jpg", 0.00001, 0.00001, 0.0, 1),
        _make_image(tmp_path, "b.jpg", 0.00000, 0.00001, 1.0, 11),
        _make_image(tmp_path, "c.jpg", 0.00001, 0.00001, 1.0, 22),
        _make_image(tmp_path, "d.jpg", 0.00001, 0.00001, 1.0, 33),
        _make_image(tmp_path, "e.jpg", 0.00001, 0.00000, 2.0, 44),
    ]
    out = psp.process_sequence_properties(
        subsec, cutoff_distance=1000000000, cutoff_time=100,
        interpolate_directions=True, duplicate_distance=100, duplicate_angle=5)
    images = sorted((m for m in out if isinstance(m, types.ImageMetadata)),
                    key=lambda m: m.time)
    assert [int(m.time * 10) / 10 for m in images] == [0, 1, 1.3, 1.6, 2]

    dirseq = [
        _make_image(tmp_path, "a.jpg", 0.00002, 0.00001, 3, angle=344),
        _make_image(tmp_path, "b.jpg", 0.00001, 0.00001, 4, angle=22),
        _make_image(tmp_path, "c.jpg", 0.00001, 0.00000, 5, angle=-123),
        _make_image(tmp_path, "d.jpg", 0.00001, 0.00000, 1, angle=2),
        _make_image(tmp_path, "e.jpg", 0.00002, 0.00000, 2, angle=123),
    ]
    out2 = psp.process_sequence_properties(
        dirseq, cutoff_distance=1000000000, cutoff_time=100,
        interpolate_directions=True, duplicate_distance=100, duplicate_angle=5)
    images2 = sorted((m for m in out2 if isinstance(m, types.ImageMetadata)),
                     key=lambda m: m.time)
    assert [int(m.angle) for m in images2 if m.angle is not None] == [90, 0, 270, 180, 180]


# ===========================================================================
# process_sequence_properties / duplication_check (bundled + payload)
# ===========================================================================
def test_duplication_pipeline_flags_close_images(tmp_path):
    """Through the pipeline, images that are both within distance AND angle thresholds
    of the previous kept image become MapillaryDuplicationError ErrorMetadata."""
    seq = [
        _make_image(tmp_path, "a.jpg", 1, 1, 1, angle=0),
        _make_image(tmp_path, "b.jpg", 1.00001, 1.00001, 2, angle=1),
        _make_image(tmp_path, "c.jpg", 1.00002, 1.00002, 3, angle=-1),
        _make_image(tmp_path, "d.jpg", 1.00003, 1.00003, 4, angle=-2),
        _make_image(tmp_path, "e.jpg", 1.00009, 1.00009, 5, angle=5),
        _make_image(tmp_path, "f.jpg", 1.00090, 1.00090, 6, angle=5),
        _make_image(tmp_path, "g.jpg", 1.00091, 1.00091, 7, angle=-1),
    ]
    out = psp.process_sequence_properties(
        seq, cutoff_distance=100000, cutoff_time=100,
        duplicate_distance=100, duplicate_angle=5)
    errors = [m for m in out if isinstance(m, types.ErrorMetadata)]
    assert len(errors) == 4
    assert all(isinstance(e.error, exceptions.MapillaryDuplicationError) for e in errors)


def test_duplication_check_angle_rules_and_payload():
    """duplication_check: a close pair within the angle threshold is flagged with the
    measured distance and angle_diff on the error; duplicate_angle=360 disables the
    angle test (any close pair is a duplicate regardless of heading); and a missing
    angle on either side satisfies the angle test with angle_diff recorded as None."""
    def img(name, angle):
        return types.ImageMetadata(filename=Path(name), lon=1.0, lat=1.0, time=1,
                                   alt=None, angle=angle, filesize=1)

    dedups, dups = psp.duplication_check(
        [img("a.jpg", 10.0), img("b.jpg", 11.0)],
        max_duplicate_distance=100, max_duplicate_angle=5)
    assert len(dedups) == 1 and len(dups) == 1
    err = dups[0].error
    assert isinstance(err, exceptions.MapillaryDuplicationError)
    assert err.distance == pytest.approx(0.0, abs=1e-6)
    assert err.angle_diff == pytest.approx(1.0)

    _, dups_360 = psp.duplication_check(
        [img("a.jpg", 0.0), img("b.jpg", 170.0)],
        max_duplicate_distance=100, max_duplicate_angle=360)
    assert len(dups_360) == 1  # flagged despite the 170-degree heading difference

    dedups_n, dups_n = psp.duplication_check(
        [img("a.jpg", None), img("b.jpg", 170.0)],
        max_duplicate_distance=100, max_duplicate_angle=5)
    assert len(dedups_n) == 1 and len(dups_n) == 1
    assert dups_n[0].error.angle_diff is None


# --- HARD discriminator: angle wraparound near 360 (NEW) ---
def test_duplication_angle_wraparound_near_360():
    """The duplication angle test uses the smallest circular difference, so headings
    of 350 and 10 (a 20-degree gap across the 0/360 boundary) are within a 30-degree
    threshold and flagged, while 350 and 10 are NOT within a 10-degree threshold."""
    def img(name, angle):
        return types.ImageMetadata(filename=Path(name), lon=1.0, lat=1.0, time=1,
                                   alt=None, angle=angle, filesize=1)

    _, dups = psp.duplication_check(
        [img("a.jpg", 350.0), img("b.jpg", 10.0)],
        max_duplicate_distance=100, max_duplicate_angle=30)
    assert len(dups) == 1  # 20-degree wraparound gap is within 30

    dedups, dups_tight = psp.duplication_check(
        [img("a.jpg", 350.0), img("b.jpg", 10.0)],
        max_duplicate_distance=100, max_duplicate_angle=10)
    assert len(dups_tight) == 0 and len(dedups) == 2  # 20 > 10 -> kept


# ===========================================================================
# process_sequence_properties: zigzag, null island, speed
# ===========================================================================
# --- HARD discriminator: two-point deviation flagged (kept individual) ---
def test_zigzag_marks_only_deviation_points(tmp_path):
    """Zig-zag detection flags only the points that jump off and back onto the path,
    leaving the main path intact."""
    coords = [(1.0, 1.0000), (1.0, 1.0001), (1.0, 1.0002), (1.0, 1.0003),
              (1.0, 1.0004), (1.001, 1.0005), (1.001, 1.0006), (1.0, 1.0007),
              (1.0, 1.0008), (1.0, 1.0009)]
    seq = [_make_image(tmp_path, f"img{i}.jpg", lon, lat, i)
           for i, (lon, lat) in enumerate(coords)]
    out = psp.process_sequence_properties(seq)
    zigzag = [m for m in out if isinstance(m, types.ErrorMetadata)
              and isinstance(m.error, exceptions.MapillaryZigZagError)]
    assert {m.filename.name for m in zigzag} == {"img5.jpg", "img6.jpg"}


# --- HARD discriminator: single outer spike (flaky -> kept individual) ---
def test_zigzag_single_outer_deviation_point_flagged(tmp_path):
    """A lone GPS spike that jumps off the straight path and immediately returns
    flags only that one outer deviation point; the straight-path points are kept."""
    coords = [(1.0, 1.0000), (1.0, 1.0001), (1.0, 1.0002), (1.0, 1.0003),
              (1.0, 1.0004), (1.002, 1.0005), (1.0, 1.0006), (1.0, 1.0007),
              (1.0, 1.0008), (1.0, 1.0009)]
    seq = [_make_image(tmp_path, f"s{i}.jpg", lon, lat, i)
           for i, (lon, lat) in enumerate(coords)]
    out = psp.process_sequence_properties(seq)
    zigzag = {m.filename.name for m in out if isinstance(m, types.ErrorMetadata)
              and isinstance(m.error, exceptions.MapillaryZigZagError)}
    images = {m.filename.name for m in out if isinstance(m, types.ImageMetadata)}
    assert zigzag == {"s5.jpg"}
    assert "s4.jpg" in images and "s6.jpg" in images


def test_zigzag_guards_skip_short_and_uturn(tmp_path):
    """Zig-zag guards: skip_zigzag_check=True suppresses all zig-zag errors; sequences
    shorter than window_size+1 are exempt; and a legitimate U-turn whose per-step
    distances stay under the min-distance threshold is not flagged."""
    coords = [(1.0, 1.0000), (1.0, 1.0001), (1.0, 1.0002), (1.0, 1.0003),
              (1.0, 1.0004), (1.001, 1.0005), (1.001, 1.0006), (1.0, 1.0007),
              (1.0, 1.0008), (1.0, 1.0009)]
    seq = [_make_image(tmp_path, f"img{i}.jpg", lon, lat, i)
           for i, (lon, lat) in enumerate(coords)]
    out = psp.process_sequence_properties(seq, skip_zigzag_check=True)
    assert not [m for m in out if isinstance(m, types.ErrorMetadata)
                and isinstance(m.error, exceptions.MapillaryZigZagError)]

    short = [_make_image(tmp_path, f"sh{i}.jpg", 1.0, 1.0 + i * 0.0001, i)
             for i in range(5)]
    out2 = psp.process_sequence_properties(short)
    assert len([m for m in out2 if isinstance(m, types.ImageMetadata)]) == 5
    assert not [m for m in out2 if isinstance(m, types.ErrorMetadata)
                and isinstance(m.error, exceptions.MapillaryZigZagError)]

    lats = [1.0000, 1.0001, 1.0002, 1.0003, 1.0004,
            1.0003, 1.0002, 1.0001, 1.0000, 0.9999]
    uturn = [_make_image(tmp_path, f"u{i}.jpg", 1.0, lat, i)
             for i, lat in enumerate(lats)]
    out3 = psp.process_sequence_properties(uturn)
    assert not [m for m in out3 if isinstance(m, types.ErrorMetadata)
                and isinstance(m.error, exceptions.MapillaryZigZagError)]


def test_null_island_and_capture_speed(tmp_path):
    """An image at exactly (0, 0) is rejected with MapillaryNullIslandError while
    valid images in the same folder pass through; and a sequence whose average speed
    exceeds the max rejects EVERY image with MapillaryCaptureSpeedTooFastError."""
    null_seq = [
        _make_image(tmp_path, "null.jpg", 0, 0, 1, angle=10),
        _make_image(tmp_path, "v1.jpg", 1.00001, 1.00001, 2, angle=20),
        _make_image(tmp_path, "v2.jpg", 1.00002, 1.00002, 3, angle=30),
    ]
    out = psp.process_sequence_properties(
        null_seq, cutoff_distance=1000000, cutoff_time=100,
        duplicate_distance=0.1, duplicate_angle=5)
    by_name = {m.filename.name: m for m in out}
    assert isinstance(by_name["null.jpg"], types.ErrorMetadata)
    assert isinstance(by_name["null.jpg"].error, exceptions.MapillaryNullIslandError)
    assert isinstance(by_name["v1.jpg"], types.ImageMetadata)

    fast = [
        _make_image(tmp_path, "f1.jpg", 1.0, 1.0, 0),
        _make_image(tmp_path, "f2.jpg", 1.0, 1.01, 1),
    ]
    out2 = psp.process_sequence_properties(fast)
    errors = [m for m in out2 if isinstance(m, types.ErrorMetadata)]
    assert len(errors) == 2
    assert all(isinstance(e.error, exceptions.MapillaryCaptureSpeedTooFastError)
               for e in errors)


# ===========================================================================
# process_sequence_properties: video limit checks
# ===========================================================================
def test_video_limit_checks_classify_errors(tmp_path):
    """process_sequence_properties classifies videos in order
    stationary->filesize->null-island->speed: a stationary/null-island video, a
    too-fast video, and a too-large video each get their specific error while a good
    moving video passes through."""
    videos = [
        types.VideoMetadata(tmp_path / "null.mp4", types.FileType.VIDEO,
                            points=[Point(1, -1e-5, -1e-5, 1, angle=None),
                                    Point(1, 0, 0, 1, angle=None),
                                    Point(1, 1e-4, 1e-4, 1, angle=None)],
                            make="h", model="w", filesize=123),
        types.VideoMetadata(tmp_path / "fast.mp4", types.FileType.VIDEO,
                            points=[Point(1, 1, 1, 1, angle=None),
                                    Point(1.1, 1.00001, 1.00001, 1, angle=None),
                                    Point(10, 1, 3, 1, angle=None)],
                            make="h", model="w", filesize=123),
        types.VideoMetadata(tmp_path / "big.mp4", types.FileType.VIDEO,
                            points=[Point(1, 1, 1, 1, angle=None),
                                    Point(2, 1.0002, 1.0002, 1, angle=None)],
                            make="h", model="w", filesize=1024 ** 3 * 200),
        types.VideoMetadata(tmp_path / "good.mp4", types.FileType.VIDEO,
                            points=[Point(1, 1, 1, 1, angle=None),
                                    Point(2, 1.0002, 1.0002, 1, angle=None)],
                            make="h", model="w", filesize=123),
        # empty point list also counts as stationary
        types.VideoMetadata(tmp_path / "empty.mp4", types.FileType.VIDEO,
                            points=[], make="h", model="w", filesize=123),
    ]
    out = psp.process_sequence_properties(
        videos, cutoff_distance=1000000000, cutoff_time=100,
        interpolate_directions=True, duplicate_distance=100, duplicate_angle=5)
    by_name = {m.filename.name: m for m in out}
    assert isinstance(by_name["good.mp4"], types.VideoMetadata)
    assert isinstance(by_name["null.mp4"].error, exceptions.MapillaryNullIslandError)
    assert isinstance(by_name["big.mp4"].error, exceptions.MapillaryFileTooLargeError)
    assert isinstance(by_name["fast.mp4"].error,
                      exceptions.MapillaryCaptureSpeedTooFastError)
    assert isinstance(by_name["empty.mp4"].error,
                      exceptions.MapillaryStationaryVideoError)

    # filesize=None -> the on-disk file size is used (here a tiny moving video passes)
    disk_video = tmp_path / "disk.mp4"
    disk_video.write_bytes(b"x" * 32)
    out2 = psp.process_sequence_properties(
        [types.VideoMetadata(disk_video, types.FileType.VIDEO,
                             points=[Point(1, 1, 1, 1, angle=None),
                                     Point(2, 1.0002, 1.0002, 1, angle=None)],
                             make="h", model="w", filesize=None)],
        cutoff_distance=1000000000, cutoff_time=100)
    assert isinstance(out2[0], types.VideoMetadata)


# ===========================================================================
# Image EXIF geotag: the headline first-class input (process flow)
# ===========================================================================
def test_image_geotag_from_exif_end_to_end(tmp_path):
    """End-to-end image-processing path on a real JPEG with EXIF GPS + capture time:
    exif_read.ExifRead recovers (lon, lat) (note the order), the capture time as a UTC
    datetime, the GPS image direction, and make/model; and ImageEXIFExtractor.extract()
    turns those into a populated ImageMetadata whose lat/lon/time/angle/make/model match
    the embedded values (time as a Unix epoch via geo.as_unix_time)."""
    when = datetime.datetime(2021, 7, 15, 9, 14, 39, tzinfo=datetime.timezone.utc)
    img = _write_jpeg_with_exif(
        tmp_path / "capture.jpg", lat=35.9125, lon=14.4988, when=when,
        direction=270.0, make="HTC", model="Legend")

    with img.open("rb") as fp:
        exif = exif_read.ExifRead(fp)
        lonlat = exif.extract_lon_lat()
        assert lonlat is not None
        lon, lat = lonlat
        assert lon == pytest.approx(14.4988, abs=1e-5)
        assert lat == pytest.approx(35.9125, abs=1e-5)
        capture_time = exif.extract_capture_time()
        assert capture_time is not None
        assert geo.as_unix_time(capture_time) == pytest.approx(when.timestamp())
        assert exif.extract_direction() == pytest.approx(270.0)
        assert exif.extract_make() == "HTC"
        assert exif.extract_model() == "Legend"

    md = ImageEXIFExtractor(img).extract()
    assert isinstance(md, types.ImageMetadata)
    assert md.lat == pytest.approx(35.9125, abs=1e-5)
    assert md.lon == pytest.approx(14.4988, abs=1e-5)
    assert md.time == pytest.approx(when.timestamp())
    assert md.angle == pytest.approx(270.0)
    assert md.MAPDeviceMake == "HTC"
    assert md.MAPDeviceModel == "Legend"


def test_image_geotag_missing_gps_raises(tmp_path):
    """ImageEXIFExtractor raises a MapillaryGeoTaggingError when the image has a capture
    time but no GPS longitude/latitude — the headline geotag contract for a bad input."""
    when = datetime.datetime(2021, 7, 15, 9, 14, 39, tzinfo=datetime.timezone.utc)
    out = io.BytesIO()
    exif_bytes = piexif.dump({
        "0th": {piexif.ImageIFD.Make: "HTC"},
        "Exif": {piexif.ExifIFD.DateTimeOriginal: when.strftime("%Y:%m:%d %H:%M:%S")},
    })
    piexif.insert(exif_bytes, _MINIMAL_JPEG, out)
    img = tmp_path / "nogps.jpg"
    img.write_bytes(out.getvalue())
    with pytest.raises(exceptions.MapillaryGeoTaggingError):
        ImageEXIFExtractor(img).extract()


# ===========================================================================
# Upload: the literal purpose of the tool (resumable byte-stream upload)
# ===========================================================================
def test_upload_byte_stream_via_fake_service(tmp_path):
    """The resumable upload code path through upload_api_v4: FakeUploadService chunkizes a
    byte stream, appends it to upload_path/session_key, returns a non-empty file-handle
    string, and exposes the uploaded size via fetch_offset; re-uploading the same content
    from the current offset is a no-op (the stored file is unchanged)."""
    svc = upload_api_v4.FakeUploadService(
        user_session=None, session_key="seq_abc.mly",
        upload_path=Path(tmp_path), transient_error_ratio=0.0)
    content = b"mapillary-image-bytes-0123456789"

    cluster_id = svc.upload_byte_stream(io.BytesIO(content), chunk_size=8)
    assert isinstance(cluster_id, str) and cluster_id
    stored = Path(tmp_path) / "seq_abc.mly"
    assert stored.read_bytes() == content
    assert svc.fetch_offset() == len(content)

    # Resumable: re-upload from the current offset writes nothing new.
    svc.upload_byte_stream(io.BytesIO(content), chunk_size=8)
    assert stored.read_bytes() == content
    assert svc.fetch_offset() == len(content)


def test_upload_chunks_shift_and_resume(tmp_path):
    """upload_chunks concatenates a chunk iterable (skipping empties) into the session
    file and shift_chunks/chunkize_byte_stream implement the resumable offset math: a
    fresh upload writes the whole payload, and shifting by an offset drops the already-
    uploaded prefix across chunk boundaries."""
    svc = upload_api_v4.FakeUploadService(
        user_session=None, session_key="seq2.mly",
        upload_path=Path(tmp_path), transient_error_ratio=0.0)

    cluster_id = svc.upload_chunks(iter([b"foo", b"", b"bar"]))
    assert isinstance(cluster_id, str) and cluster_id
    assert (Path(tmp_path) / "seq2.mly").read_bytes() == b"foobar"
    assert svc.fetch_offset() == 6

    # Pure offset arithmetic on the upload protocol helpers.
    assert list(upload_api_v4.UploadService.chunkize_byte_stream(io.BytesIO(b"foobar"), 2)) == [
        b"fo", b"ob", b"ar"]
    assert list(upload_api_v4.UploadService.shift_chunks([b"foo", b"bar"], 4)) == [b"ar"]
    with pytest.raises(ValueError):
        list(upload_api_v4.UploadService.chunkize_byte_stream(io.BytesIO(b"x"), 0))
