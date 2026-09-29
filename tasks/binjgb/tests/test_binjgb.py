"""End-to-end tests for the binjgb Game Boy / Game Boy Color emulator.

Each test drives the headless `binjgb-tester` binary and asserts either an
exact SHA-1 hash of its PPM framebuffer output (matching binjgb's own
expected outputs in the upstream `scripts/test.json`), or a structural
property of that output (dimensions, palette characteristics, CLI
semantics, determinism).

The hash-strict tests exercise cycle-accurate CPU, PPU, APU, timer, and
interrupt behaviour through Blargg's test ROMs; the structural tests
cover the tester CLI, PPM serialization format, and palette / mode
engine.
"""

import os
import re

from helpers import (
    hash_file,
    parse_ppm_header,
    parse_ppm_pixels,
    run_tester,
)


# ---------------------------------------------------------------- Blargg suite
#
# Expected SHA-1 hashes are taken verbatim from binjgb's own upstream
# `scripts/test.json` at commit c60e138. Only non-`!` entries are used
# (binjgb marks `!` on hashes it produces but which the ROM itself
# reports as FAIL — matching them would reward reproducing binjgb's
# specific incomplete implementation rather than a correct one).


def test_cpu_instrs_pass_screen(tester_bin, tmp_path):
    """Blargg cpu_instrs.gb at frame 1780 — final 'Passed all' screen."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("cpu_instrs.gb", frames=1780, out_ppm=ppm, timeout=60)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "58d90d7561c7d2de728b999b8d5dd74bb6e86598"


def test_instr_timing(tester_bin, tmp_path):
    """Blargg instr_timing.gb at frame 42 — instruction M-cycle timing."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("instr_timing.gb", frames=42, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "e84c9fce1dfba5ae7786a45db463032205dcc10c"


def test_mem_timing(tester_bin, tmp_path):
    """Blargg mem_timing.gb at frame 170 — memory access M-cycle timing."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mem_timing.gb", frames=170, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "560d7c80641e5ed2c0fda7309d15f8b4de47ce8d"


def test_halt_bug(tester_bin, tmp_path):
    """Blargg halt_bug.gb at frame 105 — the DMG HALT bug quirk."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("halt_bug.gb", frames=105, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "51b3c49c21a7d58856fa010185f3311e61e93e41"


def test_interrupt_time(tester_bin, tmp_path):
    """Blargg interrupt_time.gb at frame 30 — interrupt entry latency."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("interrupt_time.gb", frames=30, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "20a0d305d1be91872bf6ff5a9b738dfc443f6581"


def test_dmg_sound(tester_bin, tmp_path):
    """Blargg dmg_sound.gb at frame 2200 — APU registers in DMG mode."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("dmg_sound.gb", frames=2200, out_ppm=ppm, timeout=60)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "f68479b3c0de0e8d749a695541422bd29f62e1a3"


def test_cgb_sound(tester_bin, tmp_path):
    """Blargg cgb_sound.gb at frame 2200 — APU registers in CGB mode."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("cgb_sound.gb", frames=2200, out_ppm=ppm, timeout=60)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "5a445feb1c46e964afc2567253ada155060db602"


def test_oam_count(tester_bin, tmp_path):
    """oam_count_v5.gb at frame 9 — sprite-per-scanline count edge cases."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("oam_count_v5.gb", frames=9, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "9046cd1217fd36ef9ab715bd0983bcbd3d058c73"


# ---------------------------------------------------------- palette semantics


def test_default_dmg_palette_is_grayscale(tester_bin, tmp_path):
    """The default DMG palette produces pure grayscale pixels (R == G == B).

    Runs a DMG ROM (`cpu_instrs.gb`) with no `-P` flag and no `--force-dmg`
    (redundant — the ROM is DMG-only). Every emitted pixel must satisfy
    R == G == B, since the default DMG palette maps the four GB colour
    indices to grayscale entries.
    """
    ppm = tmp_path / "out.ppm"
    r = run_tester("cpu_instrs.gb", frames=60, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    pixels = parse_ppm_pixels(ppm)
    unique = {p for p in pixels}
    for r_, g_, b_ in unique:
        assert r_ == g_ == b_, f"pixel {(r_, g_, b_)} not grayscale"


def test_force_dmg_changes_cgb_rom_output(tester_bin, tmp_path):
    """`--force-dmg` on a CGB-capable ROM produces a different framebuffer
    than the default CGB-mode boot.

    Uses frame 2000 of `cgb_sound.gb` (a CGB-only ROM). By this point the
    ROM has definitely written to CGB palette RAM in the CGB code path,
    so the default (CGB colour) framebuffer diverges from the `--force-dmg`
    (grayscale) framebuffer. At earlier frame counts a defensible
    implementation that initialises CGB palette RAM to all-white (as the
    spec's "Reference initial state" section documents) can render
    identical frames in both modes.
    """
    default_ppm = tmp_path / "cgb_default.ppm"
    forced_ppm = tmp_path / "cgb_forced.ppm"
    r0 = run_tester("cgb_sound.gb", frames=2000, out_ppm=default_ppm, timeout=60)
    r1 = run_tester(
        "cgb_sound.gb",
        frames=2000,
        out_ppm=forced_ppm,
        force_dmg=True,
        timeout=60,
    )
    assert r0.returncode == 0 and r1.returncode == 0
    assert hash_file(default_ppm) != hash_file(
        forced_ppm
    ), "--force-dmg produced the same framebuffer as default CGB mode"


def test_force_dmg_on_cgb_rom_is_grayscale(tester_bin, tmp_path):
    """`--force-dmg` on a CGB ROM disables CGB colour palettes and produces
    only grayscale (R == G == B) pixels."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("cgb_sound.gb", frames=100, out_ppm=ppm, force_dmg=True)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    pixels = parse_ppm_pixels(ppm)
    for r_, g_, b_ in pixels:
        assert (
            r_ == g_ == b_
        ), f"--force-dmg produced non-grayscale pixel {(r_, g_, b_)}"


def test_builtin_palettes_differ(tester_bin, tmp_path):
    """A non-grayscale builtin `-P` palette renders differently from grayscale.

    The spec pins only that palette 0 is grayscale and that every higher
    index is a *distinct* non-grayscale scheme; the exact per-index colours
    are implementation-defined (a compliant scheme may leave the white/black
    endpoint shades unchanged and tint only the mid-tones). This therefore
    uses `oam_count_v5.gb`, whose screen renders a mid-tone BG shade rather
    than only the white/black endpoints, so a distinct scheme is guaranteed
    to visibly diverge from grayscale here. DMG mode is forced so the builtin
    palette drives the framebuffer (in CGB / CGB-compat mode the DMG palette
    is ignored in favour of CGB palette RAM).
    """
    ppm0 = tmp_path / "p0.ppm"
    ppm4 = tmp_path / "p4.ppm"
    r0 = run_tester(
        "oam_count_v5.gb", frames=9, out_ppm=ppm0, palette=0, force_dmg=True
    )
    r4 = run_tester(
        "oam_count_v5.gb", frames=9, out_ppm=ppm4, palette=4, force_dmg=True
    )
    assert r0.returncode == 0 and r4.returncode == 0
    assert hash_file(ppm0) != hash_file(
        ppm4
    ), "builtin palette 4 produced identical output to grayscale palette 0"


# ------------------------------------------------------------ PPM output format


def test_default_ppm_has_dmg_dimensions(tester_bin, tmp_path):
    """A default `-f 1` run emits a well-formed P3 160x144 PPM: the header is
    exactly 'P3\\n160 144\\n255\\n' (DMG resolution) and the body holds a full
    160*144 pixel triples."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("cpu_instrs.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    w, h, m, header = parse_ppm_header(ppm)
    assert (w, h, m) == (160, 144, 255)
    assert header == b"P3\n160 144\n255\n"
    pixels = parse_ppm_pixels(ppm)
    assert len(pixels) == 160 * 144


def test_sgb_border_ppm_has_sgb_dimensions(tester_bin, tmp_path):
    """`--sgb-border` output header is 'P3\\n256 224\\n255\\n' AND the
    framebuffer contains meaningful border + inner content (a stub that
    emits a uniform-colour framebuffer must fail).

    Runs `cpu_instrs.gb` (DMG-only, no SGB command handshake) with
    `--sgb-border`. Per the tester's SGB write path, the outer border
    region is fed from the SGB framebuffer (zero-initialised because the
    ROM never sends SGB commands), so any SGB-colour byte of `0`
    decomposes to RGB `(0, 0, 0)`; the top-left pixel (`x=0, y=0`) sits
    strictly outside the inner 160x144 window (`SGB_SCREEN_LEFT=48`,
    `SGB_SCREEN_TOP=40`) so it must be black. The interior renders the
    DMG framebuffer (mostly white), giving at least two distinct pixel
    values.
    """
    ppm = tmp_path / "out.ppm"
    r = run_tester("cpu_instrs.gb", frames=60, out_ppm=ppm, sgb_border=True)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    w, h, m, header = parse_ppm_header(ppm)
    assert (w, h, m) == (256, 224, 255)
    assert header == b"P3\n256 224\n255\n"
    pixels = parse_ppm_pixels(ppm)
    assert len(pixels) == 256 * 224
    unique = set(pixels)
    assert (
        len(unique) >= 2
    ), f"SGB framebuffer is a uniform colour (stub-like); got {len(unique)} unique"
    top_left = pixels[0]
    assert top_left == (
        0,
        0,
        0,
    ), f"top-left SGB border pixel must be (0, 0, 0); got {top_left}"


# ---------------------------------------------------------------- CLI semantics


def test_missing_rom_arg_exits_nonzero(tester_bin):
    """Invoking the tester with no positional ROM argument exits non-zero
    and prints a usage message (rules out a silent-error stub)."""
    import subprocess

    r = subprocess.run([tester_bin], capture_output=True, text=True, timeout=10)
    assert r.returncode != 0
    combined = (r.stdout + r.stderr).lower()
    assert "usage" in combined, "expected 'usage' in error output"


def test_help_flag_exits_nonzero(tester_bin):
    """The -h / --help flag prints usage and exits non-zero."""
    import subprocess

    r = subprocess.run([tester_bin, "-h"], capture_output=True, text=True, timeout=10)
    assert r.returncode != 0
    combined = (r.stdout + r.stderr).lower()
    assert "usage" in combined, "expected 'usage' in help output"


def test_no_output_flag_creates_no_ppm(tester_bin, tmp_path):
    """Without `-o` the tester creates no PPM file anywhere.

    Runs the tester with `cwd=tmp_path` so any relative-path write lands
    in `tmp_path`; then also snapshots the repository root (the tester's
    normal working directory under the grader) before and after, so an
    absolute-path write anywhere inside `/app` is caught too.
    """
    import glob

    # tester_bin = /app/bin/binjgb-tester → repo_root = /app
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(tester_bin)))
    ppm_before = set(glob.glob(f"{repo_root}/**/*.ppm", recursive=True))
    r = run_tester("cpu_instrs.gb", frames=5, cwd=str(tmp_path))
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    ppm_after = set(glob.glob(f"{repo_root}/**/*.ppm", recursive=True))
    for entry in os.listdir(tmp_path):
        assert not entry.endswith(".ppm"), f"unexpected PPM in cwd (tmp_path): {entry}"
    unexpected = ppm_after - ppm_before
    assert (
        not unexpected
    ), f"tester wrote unwanted PPM files under {repo_root}: {unexpected}"


# ------------------------------------------------------- progression


def test_frames_progression_differs(tester_bin, tmp_path):
    """Frames 10 and 200 of the same ROM produce different framebuffers."""
    p10 = tmp_path / "f10.ppm"
    p200 = tmp_path / "f200.ppm"
    r10 = run_tester("cpu_instrs.gb", frames=10, out_ppm=p10)
    r200 = run_tester("cpu_instrs.gb", frames=200, out_ppm=p200)
    assert r10.returncode == 0 and r200.returncode == 0
    assert hash_file(p10) != hash_file(
        p200
    ), "10-frame and 200-frame runs produced identical output"


# -------------------------------------------------------------------- animate


def test_animate_produces_multiple_ppms(tester_bin, tmp_path):
    """`-a` with `-o` emits one PPM per rendered PPU frame, named
    `<basename>.NNNNNNNN.ppm` (eight-digit zero-padded, contiguous from 0),
    each a valid P3 160x144 image.

    Where in a frame-period an implementation places the "frame presented"
    instant is not pinned, so instead of an absolute count this grades the two
    properties §"Frame counting (-f / -a)" does determine:

    * `cpu_instrs.gb` blanks the LCD while it initialises itself, and
      LCD-off frame-periods emit no PPM, so a `-f 10` run must produce
      strictly fewer than 10 numbered PPMs — an emitter that ignores LCD
      state and writes one per frame-period produces exactly 10 — while
      still producing more than one, which an emitter that only dumps the
      final frame under a numbered name does not.
    * The ROM leaves the LCD on once it has finished initialising, so every
      further frame-period is a rendered frame: going from `-f 10` to `-f 20`
      must add exactly 10 numbered PPMs. Both runs share the same boot phase,
      so this difference is independent of the presentation instant and of
      however many frames the boot phase itself happens to render.
    """

    def animate(frames):
        outdir = tmp_path / f"f{frames}"
        outdir.mkdir()
        r = run_tester(
            "cpu_instrs.gb",
            frames=frames,
            out_ppm=outdir / "anim.ppm",
            animate=True,
        )
        assert r.returncode == 0, f"tester failed: {r.stderr}"
        numbered = sorted(
            f for f in os.listdir(outdir) if re.fullmatch(r"anim\.\d{8}\.ppm", f)
        )
        assert numbered == [
            f"anim.{i:08d}.ppm" for i in range(len(numbered))
        ], f"animation PPMs are not contiguously numbered from 0: {numbered}"
        return outdir, numbered

    frames = 10
    outdir, numbered = animate(frames)
    assert 2 <= len(numbered) < frames, (
        f"expected more than one and strictly fewer than {frames} numbered PPMs "
        f"(the ROM holds the LCD off for part of the run, and LCD-off "
        f"frame-periods emit no PPM), got {len(numbered)}: {numbered}"
    )
    for name in numbered:
        w, h, m, _ = parse_ppm_header(outdir / name)
        assert (w, h, m) == (
            160,
            144,
            255,
        ), f"animation PPM {name} header is not P3 160x144: got {(w, h, m)}"

    _, longer = animate(2 * frames)
    assert len(longer) - len(numbered) == frames, (
        f"-f {2 * frames} emitted {len(longer)} numbered PPMs against "
        f"{len(numbered)} for -f {frames}: the {frames} extra frame-periods run "
        f"with the LCD on, so each must add exactly one rendered frame"
    )


# ============================================================================
# Mooneye-GB test suite — additional cycle-accuracy discriminators
# ============================================================================
#
# The 20 tests below run the Mooneye-GB acceptance ROMs (built from
# `binji/mooneye-gb-tests` at commit `fbef4165...` via `scripts/build_tests.py`
# → wla-dx) and assert framebuffer hashes taken verbatim from binjgb's own
# `scripts/test.json`. Each ROM exercises a distinct hardware precision
# invariant that Blargg's super-ROMs test only in aggregate:
#
#   - CPU M-cycle timing per instruction family: ADD SP,r8; CALL cc,nn;
#     CALL nn; RETI; register-F bit semantics.
#   - Timer edge cases: DIV write timing.
#   - Interrupt subsystem: EI-defer-one, HALT+IME=0/1 timings, IF/IE
#     register masking, general interrupt-entry latency.
#   - PPU cycle-accurate STAT interrupt sources: Mode 0 (HBlank), Mode 2
#     (OAM search), Mode 3 (pixel transfer), VBlank-vs-STAT priority,
#     VBlank-triggers-STAT-mode-2 interaction.
#   - OAM DMA: mid-DMA restart, DMA start-cycle timing.
#   - Post-boot register state (DMG ABCX variant).


def test_mooneye_add_sp_e_timing(tester_bin, tmp_path):
    """ADD SP, r8 M-cycle timing (mooneye acceptance/add_sp_e_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/add_sp_e_timing.gb", frames=4, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "91c16f7ebc814cd9202a870e8f85ef99ff53bf35"


def test_mooneye_reg_f_bits(tester_bin, tmp_path):
    """F register lower nibble must read as zero (mooneye bits/reg_f)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/bits/reg_f.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "6252ab378e3e3d4f0c8d52b88fa1aa08663d8c3e"


def test_mooneye_boot_regs_dmgABCX(tester_bin, tmp_path):
    """Post-boot register state for DMG ABCX variant (mooneye boot_regs)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/boot_regs-dmgABCX.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "e4da33ca86b93941597c8d218b9d8f9b56892b1d"


def test_mooneye_call_cc_timing2(tester_bin, tmp_path):
    """Conditional CALL M-cycle timing (mooneye acceptance/call_cc_timing2)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/call_cc_timing2.gb", frames=5, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "4ff5fa09fe988f48144183136bd19fba5cc62dec"


def test_mooneye_call_timing2(tester_bin, tmp_path):
    """Unconditional CALL M-cycle timing (mooneye acceptance/call_timing2)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/call_timing2.gb", frames=5, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "2c3629389b4a3d278f0cd1f931e6374f849708f5"


def test_mooneye_div_timing(tester_bin, tmp_path):
    """DIV register write / reset timing (mooneye acceptance/div_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/div_timing.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "07fff0c8bbddd2a2d1385bb44010c42523997e87"


def test_mooneye_ei_timing(tester_bin, tmp_path):
    """EI enables interrupts after the following instruction (mooneye ei_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/ei_timing.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "c675f7dac849d2fc8b0f6591a80fe3b92ea8e500"


def test_mooneye_intr_1_2_timing(tester_bin, tmp_path):
    """VBlank-vs-STAT interrupt priority (mooneye gpu/intr_1_2_timing-GS)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/acceptance/gpu/intr_1_2_timing-GS.gb", frames=6, out_ppm=ppm
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "facd6c9c63e44b4b3f41bbce29e665d63b150c9d"


def test_mooneye_intr_2_0_timing(tester_bin, tmp_path):
    """STAT Mode-2→Mode-0 interrupt sequencing (mooneye gpu/intr_2_0_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/gpu/intr_2_0_timing.gb", frames=3, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "66b8bd35827b39a5778780693844ed8ef9796f67"


def test_mooneye_intr_2_mode0_timing(tester_bin, tmp_path):
    """STAT Mode-0 (HBlank) interrupt timing (mooneye gpu/intr_2_mode0_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/acceptance/gpu/intr_2_mode0_timing.gb", frames=3, out_ppm=ppm
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "094840252ecd6b5321a9b9812767e435bdce3464"


def test_mooneye_intr_2_mode3_timing(tester_bin, tmp_path):
    """STAT Mode-3 (Pixel Transfer) interrupt timing (mooneye gpu/intr_2_mode3_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/acceptance/gpu/intr_2_mode3_timing.gb", frames=3, out_ppm=ppm
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "369978e18825ec7a3fc5f39bdee1dff4c9a0e9af"


def test_mooneye_intr_2_oam_ok_timing(tester_bin, tmp_path):
    """STAT Mode-2 (OAM search) interrupt timing (mooneye gpu/intr_2_oam_ok_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/acceptance/gpu/intr_2_oam_ok_timing.gb", frames=3, out_ppm=ppm
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "a10a51597f97912c59e1006a23eda5852a39f199"


def test_mooneye_vblank_stat_intr(tester_bin, tmp_path):
    """VBlank triggers STAT Mode-2 interrupt (mooneye gpu/vblank_stat_intr-GS)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/acceptance/gpu/vblank_stat_intr-GS.gb", frames=9, out_ppm=ppm
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "1f9d2db67edbce5952e0ad85cd28839aab7390c7"


def test_mooneye_halt_ime0_nointr_timing(tester_bin, tmp_path):
    """HALT with IME=0 and no pending IRQ (mooneye halt_ime0_nointr_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/acceptance/halt_ime0_nointr_timing.gb", frames=5, out_ppm=ppm
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "b02e328f494ac889c587dc406f709a15d4dfcb47"


def test_mooneye_halt_ime1_timing2(tester_bin, tmp_path):
    """HALT with IME=1 wake latency, longer variant (mooneye halt_ime1_timing2-GS)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/halt_ime1_timing2-GS.gb", frames=9, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "7288573b156b9f6620829d43966fa87085e61315"


def test_mooneye_halt_ime1_timing(tester_bin, tmp_path):
    """HALT with IME=1 wake latency (mooneye halt_ime1_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/halt_ime1_timing.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "be5d42552c3bf9135e415dbe2e5933b2b4814ab5"


def test_mooneye_if_ie_registers(tester_bin, tmp_path):
    """IF / IE register masking semantics (mooneye if_ie_registers)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/if_ie_registers.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "a73f7b6492b660632a8a2235c474aa60bb22cfc0"


def test_mooneye_intr_timing(tester_bin, tmp_path):
    """General interrupt entry latency (mooneye intr_timing)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/intr_timing.gb", frames=1, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "178dadbb3e7baa04148a73423a1815adc54649da"


def test_mooneye_oam_dma_restart(tester_bin, tmp_path):
    """OAM DMA can be restarted mid-transfer (mooneye oam_dma_restart)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/oam_dma_restart.gb", frames=4, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "b394406adf44d00cfef91502412d24be6b4e756c"


def test_mooneye_oam_dma_start(tester_bin, tmp_path):
    """OAM DMA start cycle timing (mooneye oam_dma_start)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/acceptance/oam_dma_start.gb", frames=6, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "2808d8c8f28c1039a7cbaed065b9454afb1f095e"


# ============================================================================
# MBC1 cartridge banking — mooneye emulator-only test suite
# ============================================================================
#
# The 5 tests below run the Mooneye-GB emulator-only MBC1 acceptance ROMs
# (built by `scripts/build_tests.py` at the same pinned upstream commit as
# the other mooneye tests) and assert framebuffer hashes taken verbatim
# from binjgb's own `scripts/test.json`. Each ROM exercises a distinct
# MBC1 behaviour — bank-count sizing, RAM sizing, and multicart mode —
# that the emulator's cartridge-banking layer must handle correctly to
# reach the ROM's "all-blank pass" screen.
#
# All five ROMs share the same expected hash
# (`d2c5e9902e751f0ac0dc9cd2438c9b54d76dc125`, the blank-screen
# post-pass state). The discriminator is whether the emulator's MBC1
# logic is complete enough to reach that state per-ROM; failure to
# implement any of these mapping cases produces a different framebuffer.
# All hashes have been verified as non-`!` entries in test.json (no
# expected-failure signatures are asserted here).


def test_mooneye_mbc1_rom_1Mb(tester_bin, tmp_path):
    """MBC1 ROM banking with 1 Mbit / 128 KiB cartridge (mooneye
    emulator-only/mbc1/rom_1Mb)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/emulator-only/mbc1/rom_1Mb.gb", frames=4, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "d2c5e9902e751f0ac0dc9cd2438c9b54d76dc125"


def test_mooneye_mbc1_rom_8Mb(tester_bin, tmp_path):
    """MBC1 ROM banking with 8 Mbit / 1 MiB cartridge (mooneye
    emulator-only/mbc1/rom_8Mb)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/emulator-only/mbc1/rom_8Mb.gb", frames=4, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "d2c5e9902e751f0ac0dc9cd2438c9b54d76dc125"


def test_mooneye_mbc1_ram_64Kb(tester_bin, tmp_path):
    """MBC1 external RAM banking with 64 Kbit / 8 KiB (single-bank) RAM
    (mooneye emulator-only/mbc1/ram_64Kb)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/emulator-only/mbc1/ram_64Kb.gb", frames=46, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "d2c5e9902e751f0ac0dc9cd2438c9b54d76dc125"


def test_mooneye_mbc1_ram_256Kb(tester_bin, tmp_path):
    """MBC1 external RAM banking with 256 Kbit / 32 KiB (4-bank) RAM,
    exercising the RAM-bank register (mooneye emulator-only/mbc1/ram_256Kb)."""
    ppm = tmp_path / "out.ppm"
    r = run_tester("mooneye/emulator-only/mbc1/ram_256Kb.gb", frames=46, out_ppm=ppm)
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "d2c5e9902e751f0ac0dc9cd2438c9b54d76dc125"


def test_mooneye_mbc1_multicart_rom_8Mb(tester_bin, tmp_path):
    """MBC1M multicart ROM banking with 8 Mbit / 1 MiB (mooneye
    emulator-only/mbc1/multicart_rom_8Mb). Exercises the MBC1M variant
    that reroutes the upper-bank bits — a subtle distinction from plain
    MBC1 that the spec mandates support for."""
    ppm = tmp_path / "out.ppm"
    r = run_tester(
        "mooneye/emulator-only/mbc1/multicart_rom_8Mb.gb",
        frames=4,
        out_ppm=ppm,
    )
    assert r.returncode == 0, f"tester failed: {r.stderr}"
    assert hash_file(ppm) == "d2c5e9902e751f0ac0dc9cd2438c9b54d76dc125"
