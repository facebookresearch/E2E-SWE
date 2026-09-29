"""User-facing tests for the deflopt compression library + CLI (whole-repo reproduction task).

Two surfaces are exercised, both the way a real user would:

  * the ``deflopt`` command-line tool (via subprocess) — gzip / zlib / deflate output, to a
    ``<name>.<ext>`` file or to stdout, with the ``--i<N>`` iteration flag;
  * the C library ``libdeflopt.so`` (via ctypes) — ``DefloptCompress``, ``DefloptGzipCompress``,
    ``DefloptZlibCompress``, ``DefloptDeflate``, ``DefloptDeflatePart`` and ``DefloptInitOptions``.

Correctness is verified by decompressing deflopt's output with Python's stdlib ``zlib``/``gzip``
(deflopt only compresses — any standard DEFLATE decoder must accept its output) and by checking
the exact gzip/zlib container bytes (magic, header, CRC-32, Adler-32, ISIZE). Compression
*quality* is checked against real deflopt's own output size (with a small margin): beating zlib
level 9 is not enough — the bounds require genuine optimal-parse + block-splitting work.

Artifact paths default to the grading-container layout and may be overridden for local runs:
    DEFLOPT_BIN  (default /app/deflopt)        the compiled CLI binary
    DEFLOPT_LIB  (default /app/libdeflopt.so)  the compiled shared library
"""
import ctypes
import gzip
import os
import random
import struct
import subprocess
import zlib

import pytest

BIN = os.environ.get("DEFLOPT_BIN", "/app/deflopt")
LIB = os.environ.get("DEFLOPT_LIB", "/app/libdeflopt.so")
CLI_TIMEOUT = 60  # per-CLI-call cap so a hung binary is killed cleanly (well under pytest's 120s)

# DefloptFormat enum (DefloptCompress selector) and DEFLATE block types (DefloptDeflate btype).
FMT_GZIP, FMT_ZLIB, FMT_DEFLATE = 0, 1, 2
BTYPE_STORED, BTYPE_FIXED, BTYPE_DYNAMIC = 0, 1, 2

# Real-deflopt DEFLATE/gzip output sizes on the fixtures below (measured from the reference build),
# used as compression-quality ceilings with a 5% margin (QMARGIN). Beating zlib level 9 is NOT
# enough: a lazy/greedy DEFLATE (or zlib -9) lands ~9-10% above these and fails, so passing
# requires genuine optimal-parse + optimal-block-splitting quality.
_GT_GZIP_TEXT = 9020
_GT_DEFLATE_TEXT = 9002
_GT_DEFLATE_HETERO = 29304  # unsplit is 31564 here, so this ceiling also requires splitting
QMARGIN = 1.05


# --------------------------------------------------------------------------- deterministic inputs
def _text(nbytes, seed=1234):
    """Reproducible pseudo-natural text: compressible, stable across runs."""
    words = (
        "the of and to in a is that it for as with was on are be this by from at or an "
        "will can has more one all their there which when what who how compression "
        "algorithm deflate huffman encode decode stream block window match literal length"
    ).split()
    rng = random.Random(seed)
    out, count = [], 0
    while count < nbytes:
        w = rng.choice(words)
        out.append(w)
        count += len(w) + 1
    return (" ".join(out))[:nbytes].encode()


def _rand(nbytes, seed):
    """Reproducible high-entropy (incompressible) bytes spanning the full 0..255 range."""
    rng = random.Random(seed)
    return bytes(rng.randrange(256) for _ in range(nbytes))


def _skewed(nbytes, seed):
    """A sparse, skewed alphabet: ~48 of 256 values with power-law frequencies, giving a
    dynamic-Huffman literal tree with a wide range of code lengths and many zero-length (unused)
    symbols, stressing the code-length-code encoding (the run/repeat symbols 16/17/18)."""
    rng = random.Random(seed)
    alphabet = [(i * 5 + 3) & 0xFF for i in range(48)]
    weights = [2 ** (15 - min(i, 15)) for i in range(48)]
    return bytes(rng.choices(alphabet, weights=weights, k=nbytes))


TEXT = _text(40000)
# Three regions of distinct entropy (text | random | text) — the scenario block-splitting helps.
HETERO = _text(20000, 1) + _rand(20000, 2) + _text(20000, 3)
# Highly repetitive: exercises long LZ77 matches (max length 258, 32 KiB window).
REPEAT = (b"the quick brown fox jumps over the lazy dog. " * 2400)[:100000]
BINARY = _rand(16000, 7)
BIG = _text(1100000, 99)  # > 1 MiB: spans multiple internal blocks.
# Two independent chunks for the streaming (multi-call) deflate test.
STREAM_A = _text(8000, 11)
STREAM_B = _text(8000, 22)
# Dictionary/window test: the body reuses a slice of the prefix, so compressing it against the
# prefix as an LZ77 window yields back-references into that window.
DICT_PREFIX = _text(4000, 41)
DICT_BODY = DICT_PREFIX[500:3500] + _text(3000, 42)
# Sparse skewed alphabet + a long zero-run: stresses the dynamic-Huffman code-length encoding.
SPARSE = _skewed(30000, 5) + b"\x00" * 2000 + _skewed(10000, 6)


# --------------------------------------------------------------------------- ctypes plumbing
class _DefloptOptions(ctypes.Structure):
    _fields_ = [
        ("verbose", ctypes.c_int),
        ("verbose_more", ctypes.c_int),
        ("numiterations", ctypes.c_int),
        ("blocksplitting", ctypes.c_int),
        ("blocksplittinglast", ctypes.c_int),
        ("blocksplittingmax", ctypes.c_int),
    ]


_PUChar = ctypes.POINTER(ctypes.c_ubyte)


@pytest.fixture(scope="session")
def lib():
    """Load libdeflopt.so once and declare the signatures of the public functions we call."""
    handle = ctypes.CDLL(LIB)
    handle.DefloptInitOptions.argtypes = [ctypes.POINTER(_DefloptOptions)]
    handle.DefloptInitOptions.restype = None
    for fn in (handle.DefloptGzipCompress, handle.DefloptZlibCompress):
        fn.argtypes = [
            ctypes.POINTER(_DefloptOptions), ctypes.c_char_p, ctypes.c_size_t,
            ctypes.POINTER(_PUChar), ctypes.POINTER(ctypes.c_size_t),
        ]
        fn.restype = None
    handle.DefloptCompress.argtypes = [
        ctypes.POINTER(_DefloptOptions), ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t,
        ctypes.POINTER(_PUChar), ctypes.POINTER(ctypes.c_size_t),
    ]
    handle.DefloptCompress.restype = None
    handle.DefloptDeflate.argtypes = [
        ctypes.POINTER(_DefloptOptions), ctypes.c_int, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_size_t, ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(_PUChar), ctypes.POINTER(ctypes.c_size_t),
    ]
    handle.DefloptDeflate.restype = None
    return handle


def _options(lib, **overrides):
    opts = _DefloptOptions()
    lib.DefloptInitOptions(ctypes.byref(opts))
    for key, value in overrides.items():
        setattr(opts, key, value)
    return opts


def _in_ptr(data):
    return (ctypes.c_char * len(data)).from_buffer_copy(data) if data else None


def _take(out_ptr, out_size):
    return ctypes.string_at(out_ptr, out_size.value)


def gzip_compress(lib, data, **overrides):
    opts = _options(lib, **overrides)
    out, size = _PUChar(), ctypes.c_size_t(0)
    lib.DefloptGzipCompress(ctypes.byref(opts), _in_ptr(data), len(data),
                           ctypes.byref(out), ctypes.byref(size))
    return _take(out, size)


def zlib_compress(lib, data, **overrides):
    opts = _options(lib, **overrides)
    out, size = _PUChar(), ctypes.c_size_t(0)
    lib.DefloptZlibCompress(ctypes.byref(opts), _in_ptr(data), len(data),
                           ctypes.byref(out), ctypes.byref(size))
    return _take(out, size)


def compress(lib, fmt, data, **overrides):
    opts = _options(lib, **overrides)
    out, size = _PUChar(), ctypes.c_size_t(0)
    lib.DefloptCompress(ctypes.byref(opts), fmt, _in_ptr(data), len(data),
                       ctypes.byref(out), ctypes.byref(size))
    return _take(out, size)


def deflate(lib, data, btype, final=1, **overrides):
    opts = _options(lib, **overrides)
    bit_ptr = ctypes.c_ubyte(0)
    out, size = _PUChar(), ctypes.c_size_t(0)
    lib.DefloptDeflate(ctypes.byref(opts), btype, final, _in_ptr(data), len(data),
                      ctypes.byref(bit_ptr), ctypes.byref(out), ctypes.byref(size))
    return _take(out, size)


# --------------------------------------------------------------------------- decode helpers
def inflate_raw(payload, zdict=None):
    """Decode a raw DEFLATE stream (assert a final block ends it); optional preset dictionary."""
    if zdict is not None:
        dobj = zlib.decompressobj(-zlib.MAX_WBITS, zdict=zdict)
    else:
        dobj = zlib.decompressobj(-zlib.MAX_WBITS)
    data = dobj.decompress(payload) + dobj.flush()
    assert dobj.eof, "raw deflate stream is not terminated by a final block"
    assert dobj.unused_data == b"", "trailing bytes after the deflate stream"
    return data


def run_cli(tmp_path, data, *flags, stdout=False):
    """Invoke the deflopt CLI on a temp file. Returns (CompletedProcess, input_path)."""
    src = tmp_path / "payload"
    src.write_bytes(data)
    args = [BIN, *flags]
    if stdout:
        args.append("-c")
    args.append(str(src))
    proc = subprocess.run(args, capture_output=True, timeout=CLI_TIMEOUT)
    return proc, src


# =========================================================================== CLI tests
def test_cli_gzip_file_default(tmp_path):
    """`deflopt FILE` writes FILE.gz, round-trips, and reaches a strong ratio."""
    proc, src = run_cli(tmp_path, TEXT)
    assert proc.returncode == 0, proc.stderr
    out = src.with_name(src.name + ".gz")
    assert out.exists(), "default run must create <name>.gz"
    blob = out.read_bytes()
    assert blob[:3] == b"\x1f\x8b\x08"  # gzip magic + DEFLATE method
    assert gzip.decompress(blob) == TEXT
    assert len(blob) <= _GT_GZIP_TEXT * QMARGIN, "gzip output must reach deflopt-grade ratio"


def test_cli_zlib_file(tmp_path):
    """`deflopt --zlib FILE` writes FILE.zlib as a valid zlib stream that round-trips."""
    proc, src = run_cli(tmp_path, TEXT, "--zlib")
    assert proc.returncode == 0, proc.stderr
    out = src.with_name(src.name + ".zlib")
    assert out.exists(), "--zlib run must create <name>.zlib"
    blob = out.read_bytes()
    assert blob[0] == 0x78 and (blob[0] * 256 + blob[1]) % 31 == 0  # CMF/FLG check
    assert zlib.decompress(blob) == TEXT


def test_cli_deflate_file(tmp_path):
    """`deflopt --deflate FILE` writes FILE.deflate as a complete raw DEFLATE stream."""
    proc, src = run_cli(tmp_path, TEXT, "--deflate")
    assert proc.returncode == 0, proc.stderr
    out = src.with_name(src.name + ".deflate")
    assert out.exists(), "--deflate run must create <name>.deflate"
    assert inflate_raw(out.read_bytes()) == TEXT


def test_cli_stdout_matches_file(tmp_path):
    """`deflopt -c FILE` writes the compressed bytes to stdout and creates no output file."""
    proc_c, src = run_cli(tmp_path, TEXT, stdout=True)
    assert proc_c.returncode == 0, proc_c.stderr
    assert not src.with_name(src.name + ".gz").exists(), "-c must not write a file"
    assert gzip.decompress(proc_c.stdout) == TEXT
    # -c stdout content equals the file-mode content for the same input/options.
    proc_f, src2 = run_cli(tmp_path, TEXT)
    assert proc_c.stdout == src2.with_name(src2.name + ".gz").read_bytes()


def test_cli_iterations_monotonic(tmp_path):
    """More `--i` iterations never enlarge the output; both iteration counts round-trip."""
    low, _ = run_cli(tmp_path, TEXT, "--i1", stdout=True)
    high, _ = run_cli(tmp_path, TEXT, "--i15", stdout=True)
    assert low.returncode == 0 and high.returncode == 0
    assert gzip.decompress(low.stdout) == TEXT
    assert gzip.decompress(high.stdout) == TEXT
    assert len(high.stdout) <= len(low.stdout), "more iterations must not produce a larger file"


def test_cli_help_and_missing_file(tmp_path):
    """`-h` prints usage and exits 0; running with no input file reports a clear error."""
    help_proc = subprocess.run([BIN, "-h"], capture_output=True, timeout=CLI_TIMEOUT)
    assert help_proc.returncode == 0
    assert b"Usage" in help_proc.stderr or b"usage" in help_proc.stderr
    none_proc = subprocess.run([BIN], capture_output=True, timeout=CLI_TIMEOUT)
    assert b"filename" in none_proc.stderr.lower()


# =========================================================================== library API tests
def test_lib_init_options_defaults(lib):
    """DefloptInitOptions installs the documented defaults (15 iterations, block-splitting on) that
    actually drive the encoder: default-option output matches setting the same values explicitly and
    reaches deflopt-grade quality."""
    opts = _DefloptOptions()
    lib.DefloptInitOptions(ctypes.byref(opts))
    assert opts.numiterations == 15
    assert opts.blocksplitting == 1
    assert opts.blocksplittingmax == 15
    assert opts.verbose == 0
    assert opts.verbose_more == 0
    # The installed defaults must genuinely drive compression, not just populate a struct:
    # compressing with defaults is byte-identical to setting those same values explicitly (a wrong
    # default such as numiterations=10 would diverge), decodes back to the input, and reaches the
    # deflopt-grade ceiling — so the slot rewards the real optimal-parse engine, not copied constants.
    default_out = gzip_compress(lib, TEXT)
    explicit_out = gzip_compress(lib, TEXT, numiterations=15, blocksplitting=1, blocksplittingmax=15)
    assert default_out == explicit_out, "the installed defaults must drive the same output as setting them explicitly"
    assert gzip.decompress(default_out) == TEXT
    assert len(default_out) <= _GT_GZIP_TEXT * QMARGIN, "default-option gzip output must reach deflopt-grade ratio"


def test_lib_compress_dispatch_equivalence(lib):
    """DefloptCompress dispatches by format to the same bytes the dedicated functions produce."""
    assert gzip.decompress(compress(lib, FMT_GZIP, TEXT)) == TEXT
    assert zlib.decompress(compress(lib, FMT_ZLIB, TEXT)) == TEXT
    assert inflate_raw(compress(lib, FMT_DEFLATE, TEXT)) == TEXT
    assert compress(lib, FMT_GZIP, TEXT) == gzip_compress(lib, TEXT)
    assert compress(lib, FMT_ZLIB, TEXT) == zlib_compress(lib, TEXT)


def test_lib_gzip_trailer(lib):
    """DefloptGzipCompress emits a valid gzip member with correct CRC-32 and ISIZE trailer."""
    blob = gzip_compress(lib, TEXT)
    assert blob[:3] == b"\x1f\x8b\x08"
    crc = zlib.crc32(TEXT) & 0xFFFFFFFF
    isize = len(TEXT) & 0xFFFFFFFF
    assert blob[-8:] == struct.pack("<II", crc, isize)
    assert gzip.decompress(blob) == TEXT


def test_lib_zlib_header_and_adler(lib):
    """DefloptZlibCompress emits a valid zlib header (32K window, no dict) and Adler-32 trailer."""
    blob = zlib_compress(lib, TEXT)
    cmf, flg = blob[0], blob[1]
    assert cmf == 0x78, "CMF must be 0x78 (deflate, 32 KiB window)"
    assert (cmf * 256 + flg) % 31 == 0, "FCHECK must make the 2-byte header a multiple of 31"
    assert not (flg & 0x20), "FDICT must be 0"
    assert blob[-4:] == struct.pack(">I", zlib.adler32(TEXT) & 0xFFFFFFFF)
    assert zlib.decompress(blob) == TEXT


def test_lib_deflate_dynamic_quality(lib):
    """A dynamic-Huffman DEFLATE block round-trips and reaches deflopt-grade compression."""
    blob = deflate(lib, TEXT, BTYPE_DYNAMIC)
    assert inflate_raw(blob) == TEXT
    assert len(blob) <= _GT_DEFLATE_TEXT * QMARGIN, "must reach a strong ratio (beats zlib -9)"


def test_lib_deflate_btype_ordering(lib):
    """The three DEFLATE block types all round-trip and rank stored > fixed > dynamic in size."""
    stored = deflate(lib, TEXT, BTYPE_STORED)
    fixed = deflate(lib, TEXT, BTYPE_FIXED)
    dynamic = deflate(lib, TEXT, BTYPE_DYNAMIC)
    for blob in (stored, fixed, dynamic):
        assert inflate_raw(blob) == TEXT
    assert len(stored) >= len(TEXT), "stored (uncompressed) blocks cannot shrink the data"
    assert len(fixed) < len(stored), "fixed Huffman must beat stored"
    assert len(dynamic) < len(fixed), "dynamic Huffman must beat fixed"


def test_lib_deflate_complex_huffman_table(lib):
    """A sparse, skewed alphabet exercises the dynamic-Huffman code-length encoding end to end."""
    blob = deflate(lib, SPARSE, BTYPE_DYNAMIC)
    assert inflate_raw(blob) == SPARSE
    assert len(blob) < len(SPARSE) // 2  # a skewed alphabet is highly compressible


def test_lib_block_splitting_reduces_size(lib):
    """Optimal block splitting shrinks mixed-entropy output and reaches deflopt-grade size."""
    split = deflate(lib, HETERO, BTYPE_DYNAMIC, blocksplitting=1)
    whole = deflate(lib, HETERO, BTYPE_DYNAMIC, blocksplitting=0)
    assert inflate_raw(split) == HETERO
    assert inflate_raw(whole) == HETERO
    assert len(split) < len(whole), "block splitting must help on heterogeneous input"
    assert len(split) <= _GT_DEFLATE_HETERO * QMARGIN, "split output must reach a strong ratio"


def test_lib_deflate_streaming_continuation(lib):
    """Two DefloptDeflate calls sharing the bit-pointer (final=0 then final=1) form one stream."""
    a, b = STREAM_A, STREAM_B
    opts = _options(lib)
    bp = ctypes.c_ubyte(0)
    out, size = _PUChar(), ctypes.c_size_t(0)
    # First call is not final and leaves the bit pointer mid-byte for the next call to continue.
    lib.DefloptDeflate(ctypes.byref(opts), BTYPE_DYNAMIC, 0, _in_ptr(a), len(a),
                      ctypes.byref(bp), ctypes.byref(out), ctypes.byref(size))
    # Second call reuses bp / out / size and sets the final bit; the whole thing is one stream.
    lib.DefloptDeflate(ctypes.byref(opts), BTYPE_DYNAMIC, 1, _in_ptr(b), len(b),
                      ctypes.byref(bp), ctypes.byref(out), ctypes.byref(size))
    assert inflate_raw(_take(out, size)) == a + b


def test_lib_deflate_part_dictionary(lib):
    """DefloptDeflatePart compresses a sub-range using preceding bytes as an LZ77 dictionary."""
    lib.DefloptDeflatePart.argtypes = [
        ctypes.POINTER(_DefloptOptions), ctypes.c_int, ctypes.c_int, ctypes.c_char_p,
        ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(_PUChar), ctypes.POINTER(ctypes.c_size_t),
    ]
    lib.DefloptDeflatePart.restype = None
    full = DICT_PREFIX + DICT_BODY
    k = len(DICT_PREFIX)
    opts = _options(lib)
    bp = ctypes.c_ubyte(0)
    out, size = _PUChar(), ctypes.c_size_t(0)
    lib.DefloptDeflatePart(ctypes.byref(opts), BTYPE_DYNAMIC, 1, _in_ptr(full), k, len(full),
                          ctypes.byref(bp), ctypes.byref(out), ctypes.byref(size))
    stream = _take(out, size)
    # Only the [k:] range is emitted, and it decodes with the prefix supplied as the preset dict.
    assert inflate_raw(stream, zdict=DICT_PREFIX) == DICT_BODY
    # The window must be genuinely used: compressing the body against the prefix window must be
    # clearly smaller than compressing the same body alone (the body's first half is copied from
    # the prefix, so a correct implementation finds a long back-reference into the window).
    without_dict = deflate(lib, DICT_BODY, BTYPE_DYNAMIC)
    assert len(stream) < len(without_dict) * 0.9, "window must be used as an LZ77 dictionary"


def test_lib_determinism(lib):
    """Compressing identical input with identical options yields byte-identical output that decodes
    back to the input (determinism must not come from emitting a fixed, incorrect stream)."""
    blob = gzip_compress(lib, TEXT)
    assert blob == gzip_compress(lib, TEXT)
    assert gzip.decompress(blob) == TEXT


def test_lib_long_repetition(lib):
    """Long repeated runs use LZ77 back-references to reach a very high compression ratio."""
    blob = deflate(lib, REPEAT, BTYPE_DYNAMIC)
    assert inflate_raw(blob) == REPEAT
    assert len(blob) * 50 < len(REPEAT), "repetitive data must compress at least 50x"


def test_lib_empty_input(lib):
    """Compressing empty input yields a valid, minimal gzip member that decodes to b''."""
    blob = gzip_compress(lib, b"")
    assert blob[:3] == b"\x1f\x8b\x08"
    assert blob[-8:] == struct.pack("<II", 0, 0)  # CRC-32 and ISIZE of empty input are 0
    assert gzip.decompress(blob) == b""


def test_lib_binary_all_bytes(lib):
    """High-entropy binary data (all byte values, embedded NULs) round-trips exactly."""
    assert inflate_raw(deflate(lib, BINARY, BTYPE_DYNAMIC)) == BINARY
    assert gzip.decompress(gzip_compress(lib, BINARY)) == BINARY


def test_lib_large_multiblock_integrity(lib):
    """Input larger than one internal block round-trips without corruption at boundaries."""
    blob = deflate(lib, BIG, BTYPE_DYNAMIC, numiterations=5)
    assert inflate_raw(blob) == BIG
