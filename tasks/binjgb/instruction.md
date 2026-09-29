# Game Boy / Game Boy Color Emulator (`binjgb`)

Build a **cycle-accurate** Nintendo Game Boy (DMG) and Game Boy Color (CGB)
hardware emulator in **C**, exposed through a headless test-runner CLI that
loads a ROM, runs it for N video frames, and writes the final framebuffer to
a Netpbm P3 PPM file. No user-facing SDL / OpenGL / GUI is required — the
grading surface is purely the headless runner. A real user would build the
same emulator library and drive it from either this runner or a graphical
front-end.

The Game Boy hardware is thoroughly documented (Pandocs, gbdev wiki); this
document specifies binjgb-specific conventions on top of the standard
hardware behaviour.

## References available at `/reference/`

The agent's container includes the following canonical Game Boy reference
materials at `/reference/`. Read them as needed during implementation:

- `pandocs.md` — the canonical Game Boy hardware reference
  (`gbdev/pandocs`, CC0-1.0). Memory map, PPU / APU / timer / interrupt
  behaviour, MBC banking rules, cartridge header format, boot ROM state,
  register layout. Concatenated from the mdBook `src/` tree in
  `SUMMARY.md` order, with per-page `# === FILE: <name>.md ===` markers
  for `grep`-based navigation.
- `lr35902_opcodes.md` — Sharp LR35902 opcode table with T-cycle counts
  and flag effects, unprefixed + CB-prefixed (`izik1/gbops`, MIT).
  Divide T-cycles by 4 to get M-cycles.
- `README.md` — index of the files above.
- `LICENSES.txt` — license text for each source.

No network access is available at eval time. All hardware behaviour
references live in `/reference/`.

### Suggested pre-implementation reading

`pandocs.md` is 431 KB / ~9k lines — do NOT `cat` it whole. Use
`grep -n "# === FILE: <name>" /reference/pandocs.md` to locate a
section's line number, then `sed -n '<start>,<end>p'` to read it. The
map below points each `Cycle-accuracy scope` bullet (§ below) at the
`# === FILE:` sections that document it — read the relevant ones
**before** writing the corresponding subsystem, not reactively after
tests fail:

- **CPU instruction set + cycle timing:** `/reference/lr35902_opcodes.md`
  (31 KB — small enough to `cat` whole) plus pandocs `CPU_Instruction_Set.md`,
  `CPU_Registers_and_Flags.md`.
- **Memory map + cartridge banking:** `Memory_Map.md`,
  `The_Cartridge_Header.md`, `MBCs.md`, `MBC1.md`.
- **PPU rendering:** `Rendering.md`, `pixel_fifo.md`, `OAM.md`,
  `Tile_Data.md`, `Tile_Maps.md`, `LCDC.md`, `Palettes.md`,
  `Scrolling.md`.
- **STAT / mode timing:** `STAT.md`, `Accessing_VRAM_and_OAM.md`.
- **OAM DMA:** `OAM_DMA_Transfer.md`.
- **Timer:** `Timer_and_Divider_Registers.md`, `Timer_Obscure_Behaviour.md`.
- **Interrupts + HALT:** `Interrupts.md`, `Interrupt_Sources.md`, `halt.md`.
- **APU:** `Audio.md`, `Audio_Registers.md`, `Audio_details.md`.
- **Joypad register:** `Joypad_Input.md`.
- **CGB palette RAM + speed switch:** `CGB_Registers.md`.
- **SGB border rendering:** `SGB_Functions.md`, `SGB_Command_Border.md`.

## Cycle-accuracy scope

The following cycle-accurate hardware corners are load-bearing for the
reference framebuffer output; consult `/reference/pandocs.md` and
`/reference/lr35902_opcodes.md` for the timing details:

- CPU M-cycle-accurate instruction timing for every opcode (base +
  CB-prefixed).
- HALT bug behaviour after `HALT` with `IME=0` and `IE & IF != 0`.
- Interrupt entry latency in M-cycles (both for `EI`-armed and post-`HALT`
  wake).
- Timer TIMA overflow behaviour: reload from TMA at cycle 4 of the overflow
  M-cycle; reads/writes during the reload window.
- STAT IRQ blocking rules across PPU mode transitions (M0/M1/M2/M3 edges).
- OAM DMA start-cycle timing and restart-cycle behaviour.
- DMG OAM sprite-per-scanline count enforcement.
- MBC1 bank register semantics including RAM bank sizes and the MBC1M
  multicart variant.

## Build contract

The repository's top-level `Makefile` default target MUST produce an
executable at `bin/binjgb-tester` at the repository root. Standard C
toolchain only (C11, libc). Do **not** link SDL, OpenGL, ImGui, or any other
third-party library — the tester is entirely self-contained.

Also provide a top-level `setup.sh` that builds the project **offline** (no
network). It runs at the repository root; after it runs, an executable
`./bin/binjgb-tester` must exist.

## `binjgb-tester` command line

```
binjgb-tester [options] <in.gb>
  -h, --help              print usage and exit non-zero
  -f, --frames N          run for N video frames (default 60)
  -o, --output FILE       write a P3 PPM screenshot to FILE at end of run
  -a, --animate           write one PPM per rendered frame (needs -o)
  -s, --seed SEED         raw u32 seed for the uninitialised-RAM PRNG. Passed
                          through verbatim — do NOT remap 0 to a magic constant
                          (the xorshift32 state stays at 0 when seeded with 0,
                          which is a semantically valid all-zero uninitialised
                          state the reference relies on). Default: 0xcabba6e5.
  -P, --palette PAL       apply builtin DMG palette index PAL (0..83)
      --force-dmg         run a CGB ROM in DMG (grayscale) compatibility mode
      --sgb-border        render the Super Game Boy border overlay
```

- The ROM path is a positional argument. If it is missing, the tester prints
  usage and exits non-zero.
- Options accept both short (`-f 60`) and long (`--frames 60`) forms.
- Unknown options are an error and exit non-zero.
- Successful run exits 0.

### Frame counting (`-f` / `-a`)

A **frame-period** is one full frame of emulated time (`70224` T-cycles /
`17556` M-cycles), which elapses regardless of whether the LCD is currently
on. A **rendered frame** is a completed frame that the PPU presents with the
LCD enabled; while the LCD is off nothing is presented.

`-f N` runs the emulator for `N` frame-periods of emulated time and then
keeps running until the PPU presents its next rendered frame, which is where
the run ends; `-o` writes that presented frame. A screenshot is therefore
always a fully drawn frame rather than one caught mid-render, and a ROM that
blanks the LCD while it initialises is captured at the first frame it
presents once the `N` frame-periods have elapsed.

`-a` writes one PPM per rendered frame, so frame-periods during which the
LCD is off emit no PPM.

## Framebuffer & PPM output

The tester writes an ASCII Netpbm **P3** file:

```
P3
<width> <height>
255
<pixel triples, RGB, space-separated>
```

- Default mode (no `--sgb-border`): 160 × 144 pixels (DMG / CGB screen).
- With `--sgb-border`: 256 × 224 pixels (SGB overlay wrapping the 160×144
  interior).
- Each pixel is emitted as three decimal integers `R G B` in the range
  `[0, 255]`, formatted with the printf specifier `"%3u %3u %3u "` (three
  fixed-width fields, trailing space). One image row per output line,
  terminated by `\n`.
- With `-a --animate`, one PPM is written per rendered frame; each filename
  is derived from the `-o` argument by replacing its `.ppm` extension with
  `.NNNNNNNN.ppm` (eight-digit zero-padded animation index).

## Colour conventions

**DMG mode** — four grayscale levels:

| Colour | RGBA (little-endian AABBGGRR) | R, G, B triple |
|--------|-------------------------------|----------------|
| WHITE  | `0xFFFFFFFF`                  | `(255, 255, 255)` |
| LIGHT GRAY | `0xFFAAAAAA`              | `(170, 170, 170)` |
| DARK GRAY  | `0xFF555555`              | `(85, 85, 85)`    |
| BLACK  | `0xFF000000`                  | `(0, 0, 0)`       |

The default DMG palette maps `BGP` / `OBP0` / `OBP1` colours 0..3 to these
four grays (colour 0 = WHITE, colour 3 = BLACK).

**CGB mode** — 15-bit RGB from CGB palette RAM, expanded to 8-bit-per-channel
in the framebuffer. The exact colour-curve is the raw expansion (no tone
mapping): `channel_8bit = (channel_5bit * 255) / 31`.

**Builtin palettes** — `-P N` selects a builtin DMG palette by index (`N` in
`0..83`). Palette 0 is grayscale (identical to the default DMG palette,
colours pinned above); every higher index is a **distinct** tinted
(non-grayscale) 4-colour scheme applied to BG / OBJ0 / OBJ1. Only palette 0's
exact colours are pinned by this spec — the exact per-index colour tables for
indices `1..83` are implementation-defined and need not match any particular
values; the only contract on them is that each index yields a distinct,
non-grayscale scheme.

**SGB mode** — Super Game Boy border rendering uses the SGB-provided palette
table stored during the SGB init handshake. The interior 160×144 area
retains the DMG framebuffer; SGB-provided pixel colours fill the surrounding
border region. The SGB border framebuffer is **zero-initialised** at
power-on: any border region for which the ROM has supplied no SGB border data
decodes from an all-zero colour word to RGB `(0, 0, 0)` (black). A ROM that
issues no SGB handshake (e.g. a DMG-only ROM run with `--sgb-border`)
therefore renders an all-black border around the interior.

## Emulator core requirements

The emulator MUST implement, with cycle-accurate M-cycle timing, the
subsystems the tester exercises. See §"Cycle-accuracy scope" for the
specific corners that matter.

**Required by the tester:**

- **CPU** — full Sharp LR35902 instruction set (all 256 base opcodes plus
  all 256 CB-prefixed opcodes) with correct flag semantics for every
  arithmetic / logic / rotate / shift / DAA operation.
- **Memory map** — cartridge ROM banking (**MBC1 including the MBC1M
  multicart variant**), WRAM banking (CGB), VRAM banking (CGB), OAM,
  HRAM, I/O registers, echo RAM, unusable region. Initial RAM values are
  seeded from `--seed` (see §"Reference initial state").
- **PPU** — mode timing (OAM search / pixel transfer / HBlank / VBlank),
  LY / LYC comparison, STAT interrupt sources, sprite / background /
  window rendering, sprite priority and X-coordinate ordering, DMG
  palette (`BGP` / `OBP0` / `OBP1`) and CGB palette RAM (`BCPS` /
  `OCPS`), OAM DMA transfer.
- **Timer** — `DIV`, `TIMA`, `TMA`, `TAC`.
- **Interrupts** — `IE` / `IF` registers, `EI` / `DI` / `HALT` semantics.
- **CGB speed switch** — `KEY1` (`FF4D`) plus `STOP`: a ROM running in CGB
  mode may set the prepare-speed-switch bit and execute `STOP` to toggle the
  CPU between normal and double speed, and the emulator must honour it.
- **APU** — four sound channels (2× pulse with sweep+envelope, wave,
  noise LFSR), NR registers, length counter, frame sequencer at 512 Hz,
  correct DAC-disable / channel-enable semantics.
- **Joypad** — `P1` register with correct button/direction column-select
  behaviour and joypad interrupt (button input is not driven at runtime,
  but the register wiring must be correct for ROMs that read it).
- **SGB** — Super Game Boy border framebuffer must be produced when
  `--sgb-border` is set (see §"Colour conventions").

**Public library features not exercised by the tester** (implement if
useful, but not required for a passing run):
additional mapper support (MMM01, MBC2, MBC3+RTC, MBC5, HuC1), the DMG
OAM-corruption bug, save-state serialisation, rewind, battery-backed
external RAM persistence, joypad-input playback from a recorded file,
`STOP` low-power standby (i.e. a `STOP` executed with no speed switch
pending — the CGB speed switch above *is* required).

## Tester binary shape

`bin/binjgb-tester` is a self-contained C11 executable that:

1. Parses the CLI in §"`binjgb-tester` command line" (positional ROM
   argument + optional flags).
2. Loads the ROM into memory.
3. Instantiates a Game Boy emulator with the requested seed, palette,
   and force-DMG mode.
4. Advances the emulator as described in §"Frame counting".
5. Extracts the final framebuffer (or SGB framebuffer when `--sgb-border`
   is set) and writes it to the `-o` path in the P3 format described in
   §"Framebuffer & PPM output".
6. Exits 0 on success, non-zero on any argument / file / runtime error.

The internal layout, module naming, header file names, and public C API
shape are at the agent's discretion — the tester binary is what an
end-user of the library invokes, and only its CLI, PPM output, and
observable hardware behaviour are contracted.

## Determinism

Given the same ROM, `--seed`, `--frames`, and (if used) joypad input file,
the emulator MUST produce a byte-identical PPM on every run. In particular,
the PPU frame count, the CPU tick count, and every side-effect visible in
the framebuffer must be a pure function of these inputs. Uninitialised RAM
values are seeded by the deterministic PRNG initialised from `--seed`.

## Reference initial state

These are the specific binjgb-side choices that determine the framebuffer
bytes the tests compare against. Adopting different but
internally-consistent values will produce a functionally
correct emulator whose pixel hashes nevertheless differ; the M-cycle-accurate
CPU / PPU / APU / timer work is the substantive part of the implementation.

### Uninitialised-RAM PRNG

- Algorithm: **xorshift32** — `x ^= x << 13; x ^= x >> 17; x ^= x << 5;`,
  standard `u32` state, no additional mixing.
- Seeded once from `--seed` (default `0xcabba6e5`); the same evolving state
  persists across the three fills below (do not re-seed between buffers).
- Fill order (load-bearing — a wrong order shifts every downstream byte):
  1. **ext_ram** — 128 KiB (`EXT_RAM_MAX_SIZE`).
  2. **wram** — 32 KiB (`WORK_RAM_SIZE`).
  3. **hram** — 127 bytes (`HIGH_RAM_SIZE`).
- Fill semantics: each `random_u32()` output is written **little-endian** to
  RAM in 4-byte chunks; for a trailing partial word (only `hram` hits this),
  take the low bytes of the next `u32`.
- **VRAM and OAM are NOT randomised** — both start zero.

### Wave RAM (channel-3 sample buffer, `FF30`-`FF3F`)

Initialised to the following 16 bytes, in address order:

```
0x60, 0x0d, 0xda, 0xdd, 0x50, 0x0f, 0xad, 0xed,
0xc0, 0xde, 0xf0, 0x0d, 0xbe, 0xef, 0xfe, 0xed
```

### Timer internal DIV counter

The 16-bit internal timer counter whose upper byte is exposed as `DIV`
(`FF04`) starts at `0xAC00` at post-boot. Real hardware and other emulators
pick different starting values; this reference pins that one.

### Post-boot register file

Applied before the ROM starts executing (the boot ROM is skipped; the
following values approximate the state a real Game Boy would be in after
the internal bootstrap):

| Register | DMG value | CGB value |
|----------|-----------|-----------|
| A        | `0x01`    | `0x11`    |
| F        | `0xB0`    | `0xB0`    |
| BC       | `0x0013`  | `0x0013`  |
| DE       | `0x00D8`  | `0x00D8`  |
| HL       | `0x014D`  | `0x014D`  |
| SP       | `0xFFFE`  | `0xFFFE`  |
| PC       | `0x0100`  | `0x0100`  |
| IME      | `false`   | `false`   |

`F = 0xB0` breaks down to `Z=1, N=0, H=1, C=1`. Only the `A` register
differs between DMG and CGB; every other register is initialised to its
DMG value regardless of hardware mode. This is a reference-specific choice
— real CGB hardware initialises `BC`, `DE`, `HL`, and `F` differently, but
this reference does not.

### Initial CGB palette RAM (BCPD / OCPD)

Both palette-RAM arrays (background and object) are initialised to
**all-white** (`RGBA_WHITE` = `0xFFFFFFFF`; the underlying `data[]` bytes
are `0xFF 0x7F` per 16-bit colour word — R = G = B = 31 in 5-bit CGB
colour). This affects CGB / CGB-DMG-compat rendering during the window
between power-on and the ROM writing its own palette entries.

### Initial I/O register writes at boot

Performed before yielding control to the ROM (via the same `write_apu` /
`write_io` code paths as the ROM would use, so their side-effects on
subsystem state take effect):

- `NR52 = 0xF1` (master sound enable — writes to APU registers below
  fail unless this is set first).
- `NR11 = 0x80`, `NR12 = 0xF3`, `NR14 = 0x80`.
- `NR50 = 0x77`, `NR51 = 0xF3`.
- `Channel-1 envelope volume = 0` (silences the boot square-wave that
  would otherwise play from the `NR14` trigger above).
- `LCDC = 0x91`, `SCY = 0x00`, `SCX = 0x00`, `LYC = 0x00`.
- `BGP = 0xFC`, `OBP0 = 0xFF`, `OBP1 = 0xFF`.
- `IF = 0x01`, `IE = 0x00`.
- HDMA block count = `0xFF` (CGB DMA-idle sentinel).
- WRAM bank offset = `0x1000` (CGB bank 1).

Every I/O register not written above is zero at power-on: the emulator state
is zero-initialised before these boot writes are applied, so the writes above
are the only non-zero initial I/O state the reference sets (e.g. `WY`, `WX`,
`TAC` / `TIMA` / `TMA`, and the unlisted `NRxx` all start at `0x00`).

## Source organisation

The implementation is a C project that builds `bin/binjgb-tester`
via `Makefile`. Header / source file names, module boundaries, and
directory layout are at the agent's discretion — a passing run requires
only that `setup.sh` builds `bin/binjgb-tester` and that the resulting
binary implements the CLI, output, and hardware contracts described above.
