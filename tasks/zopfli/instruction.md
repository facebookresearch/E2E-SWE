# A high-ratio DEFLATE / zlib / gzip compression library in C

Build **`deflopt`**, a C library (plus a small command-line tool) that performs very good — but
slow — [DEFLATE](https://www.ietf.org/rfc/rfc1951.txt) compression and emits the result in raw
DEFLATE, [zlib](https://www.ietf.org/rfc/rfc1950.txt), or [gzip](https://www.ietf.org/rfc/rfc1952.txt)
format. It only *compresses*; its output must be decodable by any standard DEFLATE/zlib/gzip
decompressor. Its distinguishing feature is compression *quality*: it spends extra CPU to produce
output meaningfully smaller than typical `zlib`/`gzip` at maximum level, by doing **iterative,
cost-model-driven optimal LZ77 parsing** and **optimal block splitting** rather than a single
greedy/lazy pass.

The internal design is entirely up to you — LZ77 matching, Huffman-code construction, cost modelling,
block splitting, and file layout. Only the public interface described below is fixed.

## Environment and build

- Language: **C** (C89/C99 or any standard C is fine). It uses only the **C standard library** and
  the **math library** (`-lm`); it has no third-party dependencies.
- The project is built by running **`setup.sh`** at the project root, which must produce two
  artifacts:
  - **`/app/deflopt`** — the command-line executable.
  - **`/app/libdeflopt.so`** — a shared library exporting the public functions below with **C
    linkage** (plain C, or `extern "C"`), loadable via `dlopen`.
  `setup.sh` runs with the working directory at the project root (`/app`). For example:
  `gcc your_sources*.c -O2 -lm -o deflopt` for the binary, and a `-shared -fPIC` link (excluding the
  file that defines `main`) for `libdeflopt.so`.

## Library API

All compression functions **append** their output to a caller-owned dynamic array: `*out` must be a
`malloc`-allocated buffer (grown with `realloc` as needed) and `*outsize` set to the number of bytes
written, so the caller can read `*outsize` bytes from `*out` and later `free` it. On entry `*out`
may be `NULL` and `*outsize` `0`.

### Options

```c
typedef struct DefloptOptions {
  int verbose;             /* print progress to stderr */
  int verbose_more;        /* print more detailed progress */
  int numiterations;       /* optimization passes; more = better, slower */
  int blocksplitting;      /* 1 = split into multiple deflate blocks at good boundaries */
  int blocksplittinglast;  /* retained for compatibility; unused */
  int blocksplittingmax;   /* max blocks to split into (0 = unlimited) */
} DefloptOptions;

void DefloptInitOptions(DefloptOptions* options);
```

The struct field order and types are part of the ABI and must not change (callers may read fields by
offset). `DefloptInitOptions` installs these defaults: `verbose = 0`, `verbose_more = 0`,
`numiterations = 15`, `blocksplitting = 1`, `blocksplittingmax = 15` (the value of
`blocksplittinglast` is unused).

### Output format selector

```c
typedef enum { DEFLOPT_FORMAT_GZIP, DEFLOPT_FORMAT_ZLIB, DEFLOPT_FORMAT_DEFLATE } DefloptFormat;
```

The enumerators take their default values **0 (gzip), 1 (zlib), 2 (deflate)**.

### Compression entry points

```c
/* Compress `in`/`insize` in the chosen format, appending to *out / *outsize. */
void DefloptCompress(const DefloptOptions* options, DefloptFormat output_type,
                     const unsigned char* in, size_t insize,
                     unsigned char** out, size_t* outsize);

/* Format-specific equivalents. DefloptCompress dispatches to these; for a given input and
   options each produces exactly the same bytes as the corresponding DefloptCompress call. */
void DefloptGzipCompress(const DefloptOptions* options, const unsigned char* in, size_t insize,
                         unsigned char** out, size_t* outsize);
void DefloptZlibCompress(const DefloptOptions* options, const unsigned char* in, size_t insize,
                         unsigned char** out, size_t* outsize);

/* Emit one or more raw DEFLATE blocks.
   btype: 0 = stored (uncompressed), 1 = fixed Huffman, 2 = dynamic Huffman.
   final: if nonzero, the BFINAL bit is set on the last emitted block.
   bp:    in/out bit position (0..7) within the current output byte; must be 0 on the first call. */
void DefloptDeflate(const DefloptOptions* options, int btype, int final,
                    const unsigned char* in, size_t insize,
                    unsigned char* bp, unsigned char** out, size_t* outsize);

/* Like DefloptDeflate, but compresses only in[instart:inend]; the bytes in[0:instart] are used as
   the LZ77 back-reference window (dictionary) but are NOT emitted. The result decodes to
   in[instart:inend] when in[0:instart] is supplied to the decoder as the preset dictionary. */
void DefloptDeflatePart(const DefloptOptions* options, int btype, int final,
                        const unsigned char* in, size_t instart, size_t inend,
                        unsigned char* bp, unsigned char** out, size_t* outsize);
```

`DefloptCompress` with `DEFLOPT_FORMAT_DEFLATE` produces a dynamic-Huffman (`btype = 2`),
`final = 1` stream.

`DefloptDeflate` and `DefloptDeflatePart` may be called repeatedly on the **same** `out`/`outsize`
and `bp` to append successive blocks into a single stream: pass `final = 0` on every call except the
last (where `final` is nonzero). `bp` carries the bit offset between calls so blocks pack
contiguously across the byte boundary.

## Output format requirements

Every produced stream must decode back to the exact input bytes with a standard decoder, and must
conform to its format:

- **gzip** (RFC 1952): starts with magic `1F 8B` and compression method `08` (DEFLATE); ends with an
  8-byte trailer of **CRC-32 of the uncompressed data** then **ISIZE = (input size) mod 2³²**, both
  little-endian.
- **zlib** (RFC 1950): 2-byte header where the first byte (CMF) is `0x78` (method 8, 32 KiB window)
  and the two header bytes form a big-endian value that is a **multiple of 31**, with the preset-
  dictionary flag (FDICT) clear; ends with the **Adler-32 of the uncompressed data**, big-endian.
- **raw deflate** (RFC 1951): a valid DEFLATE bit stream whose final block has the **BFINAL** bit
  set, with no trailing bytes.

Stored (`btype = 0`) blocks carry the data uncompressed (so output is at least as large as the
input); fixed (`btype = 1`) and dynamic (`btype = 2`) blocks apply Huffman coding, with dynamic
normally the smallest.

## Compression quality

Compression quality is essential, not just correctness. DEFLATE output must be **substantially
smaller than `zlib` level 9** — approaching the optimum that iterative optimal parsing plus block
splitting achieves. A strong implementation lands within a few percent of a full optimal parse +
optimal block-split, well below what a lazy/greedy DEFLATE or `zlib -9` reaches. Achieve this through
genuine optimization:

- **Optimal LZ77 parse.** Instead of greedily taking the longest match, choose the length/distance
  sequence that minimizes the encoded bit cost under a Huffman cost model, iterating `numiterations`
  times (each pass rebuilds the cost model from the previous pass's statistics) to converge on a
  cheaper parse. More iterations must never *increase* output size.
- **Optimal block splitting.** When `blocksplitting` is on, split the data into multiple DEFLATE
  blocks at boundaries chosen to minimize total size (each block gets its own Huffman trees); on
  mixed-content input this produces a strictly smaller result than encoding it as a single block.
- Standard DEFLATE limits apply: match lengths 3–258, a 32 KiB sliding window.

A naive compressor that merely round-trips (e.g. stored blocks, or a single greedy pass) does not
reach this quality.

## Command-line tool (`deflopt`)

`deflopt [OPTIONS] FILE` reads `FILE`, compresses it, and by default writes `FILE.gz`.

- Format flags: `--gzip` (default), `--zlib`, `--deflate`. The output filename gets the
  corresponding extension: `.gz`, `.zlib`, or `.deflate`.
- `-c`: write the compressed bytes to **stdout** and do **not** create an output file.
- `--i<N>`: run `N` optimization passes (e.g. `--i10`, `--i50`); the default is 15.
- `-h`: print a usage message to stderr and exit with status 0.
- If no input file is given, print an error to stderr indicating that a filename is required.

For the same input and options, `-c` output is byte-identical to the file it would otherwise write.

## Behaviour notes

- **Deterministic:** identical input and options always yield byte-identical output.
- **Edge cases:** empty input produces a valid, minimal stream (for gzip, CRC-32 and ISIZE are 0);
  arbitrary binary input (all byte values, embedded NULs) is handled; input larger than one internal
  block is compressed without corruption at block boundaries.
