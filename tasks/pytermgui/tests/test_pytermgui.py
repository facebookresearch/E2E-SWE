"""Behavioral test suite for pytermgui 7.7.4.

Covers the deterministic core through the public API: the TIM markup engine, the
color system, the regex/length helpers, the highlighters, and the HTML exporter.
Also exercises the deterministic surface of the widget and window-manager systems
-- widget rendering to character-grid lines (Label/Container/Splitter), Layout slot
geometry, and Window rendering -- under the pinned terminal. Every test pins
``terminal.forced_colorsystem`` and ``terminal.size`` (and clears the color caches)
so output is fully deterministic.
"""

import pytest


# ---------------------------------------------------------------------------
# Determinism fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def pinned_terminal():
    """Pins the colorsystem/size and clears color caches before each test.

    Defaults to TRUE color and an 80x24 terminal. Individual tests override
    ``terminal.forced_colorsystem`` when they exercise degradation.
    """

    from pytermgui.term import terminal, ColorSystem
    from pytermgui.colors import clear_color_cache, str_to_color

    clear_color_cache()
    str_to_color.cache_clear()
    terminal.forced_colorsystem = ColorSystem.TRUE
    terminal.size = (80, 24)

    yield

    clear_color_cache()
    str_to_color.cache_clear()


def _fresh():
    """Resets caches mid-test (needed when switching colorsystem)."""

    from pytermgui.colors import clear_color_cache, str_to_color

    clear_color_cache()
    str_to_color.cache_clear()


# ---------------------------------------------------------------------------
# TIM markup engine: parsing
# ---------------------------------------------------------------------------


def test_tim_parse_color_style_background():
    from pytermgui import tim

    # fg indexed, bg indexed, style -> emitted in order, trailing reset.
    assert tim.parse("[141 @61 bold]Hello") == (
        "\x1b[38;5;141m\x1b[48;5;61m\x1b[1mHello\x1b[0m"
    )
    # A hex color resolves to a true-color sequence under TRUE.
    assert tim.parse("[#5fafd7]X") == "\x1b[38;2;95;175;215mX\x1b[0m"
    # A named color (red) also becomes true-color under TRUE.
    assert tim.parse("[red]A[/fg]B") == "\x1b[38;2;255;0;0mA\x1b[39mB\x1b[0m"


def test_tim_parse_macros_and_escape():
    from pytermgui import tim

    # Macros apply to the plain text that follows, within the same group.
    assert tim.parse("[141 @61 bold !upper]Hello") == (
        "\x1b[38;5;141m\x1b[48;5;61m\x1b[1mHELLO\x1b[0m"
    )
    assert tim.parse("[!lower]HELLO") == "hello\x1b[0m"
    assert tim.parse("[!title]hello world") == "Hello World\x1b[0m"
    # A backslash escapes the bracket: literal text, no styling.
    assert tim.parse("\\[bold]") == "[bold]\x1b[0m"


def test_tim_parse_hyperlink_osc8():
    from pytermgui import tim

    assert tim.parse("[~https://x.com]link") == (
        "\x1b]8;;https://x.com\x1b\\link\x1b]8;;\x1b\\\x1b[0m"
    )


# ---------------------------------------------------------------------------
# TIM markup engine: tokenization + round trip
# ---------------------------------------------------------------------------


def test_tokenize_markup_token_taxonomy():
    from pytermgui.markup.parsing import tokenize_markup

    tokens = list(tokenize_markup("[141 bold]Hi[/]"))
    kinds = [(type(t).__name__, t.markup) for t in tokens]
    assert kinds == [
        ("ColorToken", "141"),
        ("StyleToken", "bold"),
        ("PlainToken", "Hi"),
        ("ClearToken", "/"),
    ]
    # Predicate API works as instance method and static method.
    color_tok = tokens[0]
    assert color_tok.is_color() is True
    assert color_tok.is_style() is False
    from pytermgui.markup.tokens import Token

    assert Token.is_clear(tokens[3]) is True


def test_tokens_to_markup_and_get_markup_roundtrip():
    from pytermgui import tim
    from pytermgui.markup.parsing import (
        get_markup,
        tokenize_markup,
        tokens_to_markup,
    )

    # markup -> tokens -> markup is stable.
    assert tokens_to_markup(list(tokenize_markup("[bold 141]Hi"))) == "[bold 141]Hi"
    # ansi -> markup recovers the original tag group plus the appended reset.
    assert get_markup(tim.parse("[141 @61 bold]Hello")) == "[141 @61 bold]Hello[/]"


def test_tokenize_ansi_inverse_direction():
    from pytermgui.markup.parsing import tokenize_ansi, tokens_to_markup

    # SGR style + indexed color + reset map back to the right token taxonomy.
    sgr = list(tokenize_ansi("\x1b[1m\x1b[38;5;141mHi\x1b[0m"))
    assert [(type(t).__name__, t.markup) for t in sgr] == [
        ("StyleToken", "bold"),
        ("ColorToken", "141"),
        ("PlainToken", "Hi"),
        ("ClearToken", "/"),
    ]
    # An OSC-8 hyperlink becomes an HLinkToken (~uri) wrapping the label, closed
    # by the hyperlink clearer /~.
    hlink = list(tokenize_ansi("\x1b]8;;https://x.com\x1b\\link\x1b]8;;\x1b\\"))
    assert [(type(t).__name__, t.markup) for t in hlink] == [
        ("HLinkToken", "~https://x.com"),
        ("PlainToken", "link"),
        ("ClearToken", "/~"),
    ]
    assert tokens_to_markup(hlink) == "[~https://x.com]link[/~]"
    # A cursor move \x1b[y;xH becomes a CursorToken with (y;x) markup.
    cursor = list(tokenize_ansi("\x1b[3;5HX"))
    assert [(type(t).__name__, t.markup) for t in cursor] == [
        ("CursorToken", "(3;5)"),
        ("PlainToken", "X"),
    ]


def test_tokenize_ansi_truecolor_fg_bg_roundtrip():
    from pytermgui.markup.parsing import tokenize_ansi, tokens_to_markup

    # 38;2 / 48;2 truecolor sequences parse back into ColorTokens; the background
    # color's markup carries the @ prefix and the r;g;b form. Style + fg + bg in
    # one run round-trips back to a single tag group.
    ansi = "\x1b[1m\x1b[38;2;255;0;0m\x1b[48;2;0;0;255mX\x1b[0m"
    toks = list(tokenize_ansi(ansi))
    assert [(type(t).__name__, t.markup) for t in toks] == [
        ("StyleToken", "bold"),
        ("ColorToken", "255;0;0"),
        ("ColorToken", "@0;0;255"),
        ("PlainToken", "X"),
        ("ClearToken", "/"),
    ]
    assert tokens_to_markup(toks) == "[bold 255;0;0 @0;0;255]X[/]"


# ---------------------------------------------------------------------------
# TIM markup engine: optimization
# ---------------------------------------------------------------------------


def _optimized_group(markup):
    """Split optimized `[tags]text` markup into (set-of-tags, trailing-text).

    Within a single optimized tag group fg/bg/style are independent SGR channels,
    so the surviving tags render identically regardless of their textual order
    (the spec pins "preserving visible output", not a serialization order). Tests
    that care only about WHICH tags survive compare the tag set, not the literal
    string.
    """

    assert markup.startswith("["), markup
    group, _, text = markup[1:].partition("]")
    return set(group.split()), text


def test_optimize_markup_redundancy_removal():
    from pytermgui.markup.parsing import optimize_markup

    # bold then /bold cancel; only 245 (last fg) + italic survive. Surviving fg and
    # style are independent channels, so compare the survivor SET (order is not a
    # visible-output property and the spec does not pin it).
    assert _optimized_group(optimize_markup("[123 245 bold /bold italic]Test")) == (
        {"245", "italic"},
        "Test",
    )
    # duplicate style collapses (single survivor, order-trivial).
    assert optimize_markup("[bold bold]X") == "[bold]X"


def test_optimize_within_group_channel_redundancy():
    from pytermgui.markup.parsing import optimize_markup

    # Within ONE tag group, multiple colors on the same channel collapse to the
    # last. The redundancy-removal test above covers the foreground channel; this
    # pins the background channel: [@61 @124] -> only the last background survives
    # (single survivor, order-trivial).
    assert optimize_markup("[@61 @124]X") == "[@124]X"
    # Foreground and background are independent channels: a duplicated foreground
    # (141 then 245) collapses to the last, while the unrelated background (@61)
    # is preserved -- so all three inputs reduce to one fg + one bg. Compare the
    # survivor SET: fg/bg render identically regardless of intra-group order.
    assert _optimized_group(optimize_markup("[141 @61 245]X")) == ({"@61", "245"}, "X")


def test_optimize_clearer_dropped_when_target_inactive():
    from pytermgui.markup.parsing import optimize_markup
    from pytermgui import tim

    # A clearer is dropped unless it actually targets something currently active.
    # Here bold is never active, so the cross-group /bold is a no-op and removed,
    # merging the two plain runs. italic stays.
    assert optimize_markup("[italic]A[/bold]B") == "[italic]AB"
    assert tim.parse("[italic]A[/bold]B", optimize=True) == "\x1b[3mAB\x1b[0m"
    # Contrast: when bold IS active, the /bold genuinely targets it and is kept.
    assert optimize_markup("[bold]A[/bold]B") == "[bold]A[/bold]B"


def test_parse_optimize_cross_group_carryover_to_ansi():
    from pytermgui import tim

    # A style/color that stays active across a plain run is emitted ONCE: the
    # optimize pass renders the difference at each new group. This is the canonical
    # cross-group carryover contract, verified end-to-end at the ANSI level (markup
    # in -> optimized ANSI out), so a carry-over rendering bug fails here directly.
    #
    # bold carries over A->B, so the second group emits only the NEW fg 141 -- no
    # repeated \x1b[1m. (Without optimize the bold is re-emitted before B.)
    assert tim.parse("[bold]A[bold 141]B", optimize=True) == (
        "\x1b[1mA\x1b[38;5;141mB\x1b[0m"
    )
    assert tim.parse("[bold]A[bold 141]B", optimize=False) == (
        "\x1b[1mA\x1b[1m\x1b[38;5;141mB\x1b[0m"
    )
    # The carried foreground 141 is not re-emitted; only the newly-added background.
    assert tim.parse("[141]A[141 @61]B", optimize=True) == (
        "\x1b[38;5;141mA\x1b[48;5;61mB\x1b[0m"
    )


# ---------------------------------------------------------------------------
# TIM markup engine: aliases
# ---------------------------------------------------------------------------


def test_alias_definition_and_unsetter_generation():
    import pytermgui as ptg

    lang = ptg.MarkupLanguage()
    lang.alias("my-tag", "141 bold")

    # Using the alias expands to its underlying tags.
    assert lang.parse("[my-tag]X") == "\x1b[38;5;141m\x1b[1mX\x1b[0m"
    # Defining an alias auto-generates its unsetter: fg color -> /fg, style -> /bold.
    assert lang.aliases["/my-tag"] == "/fg /bold"


def test_alias_chain_and_macros():
    import pytermgui as ptg
    from pytermgui import tim

    lang = ptg.MarkupLanguage()
    lang.alias("base", "141 bold")
    # An alias whose value references another alias resolves through the chain:
    # fancy -> "base italic" -> "141 bold" + italic.
    lang.alias("fancy", "base italic")
    assert lang.parse("[fancy]X") == "\x1b[38;5;141m\x1b[1m\x1b[3mX\x1b[0m"

    # !align(width:alignment) pads via f-string alignment.
    assert tim.parse("[!align(7:center)]hi") == "  hi   \x1b[0m"
    # !gradient(base) builds the 6-color xterm gradient column for the base
    # (base 141 walks back to column start 33: 33,69,105,141,177,213) and spreads
    # those colors across the text. Assert the documented color-ramp contract:
    # each character opens with its gradient color, in order. (The exact trailing
    # reset bytes are an undocumented implementation detail and are not asserted.)
    grad = tim.parse("[!gradient(141)]ABCDE")
    assert grad.startswith(
        "\x1b[38;5;33mA\x1b[38;5;69mB\x1b[38;5;105mC"
        "\x1b[38;5;141mD\x1b[38;5;177mE"
    )


# ---------------------------------------------------------------------------
# TIM markup engine: escape
# ---------------------------------------------------------------------------


def test_escape_roundtrips_through_parse():
    from pytermgui import tim
    from pytermgui.markup import escape

    assert escape("[bold]hi") == "\\[bold]hi"
    # Escaped markup parses back to the literal text.
    assert tim.parse(escape("[bold]hi")) == "[bold]hi\x1b[0m"


def test_styled_text_group_styles():
    from pytermgui import tim
    from pytermgui.markup.language import StyledText

    # Parse to ANSI, then recover one StyledText per plain run with its styles
    # and fore/background colors extracted from the tokens.
    ansi = tim.parse("[141 @61 bold]Hi[/]there")
    runs = list(StyledText.group_styles(ansi))
    assert len(runs) == 2

    first = runs[0]
    assert first.plain == "Hi"
    assert first.bold is True
    assert first.italic is False
    assert first.foreground.markup == "141"
    assert first.background.markup == "@61"

    # After [/], the second run carries no styles or colors.
    second = runs[1]
    assert second.plain == "there"
    assert second.bold is False
    assert second.foreground is None
    assert second.background is None


# ---------------------------------------------------------------------------
# Color system: parsing & sequences
# ---------------------------------------------------------------------------


def test_str_to_color_forms_and_sequences():
    from pytermgui.colors import str_to_color

    assert str_to_color("#123456", localize=False).sequence == "\x1b[38;2;18;52;86m"
    assert str_to_color("11;22;33", localize=False).sequence == "\x1b[38;2;11;22;33m"
    assert str_to_color("141", localize=False).sequence == "\x1b[38;5;141m"
    # Leading @ forces background.
    assert str_to_color("@141", localize=False).sequence == "\x1b[48;5;141m"
    # Named color resolves through the CSS table to true-color rgb.
    assert str_to_color("red", localize=False).sequence == "\x1b[38;2;255;0;0m"


def test_color_markup_hex_and_name():
    from pytermgui.colors import str_to_color

    assert str_to_color("141", localize=False).markup == "141"
    assert str_to_color("@141", localize=False).markup == "@141"
    assert str_to_color("#5fafd7", localize=False).hex == "#5fafd7"
    assert str_to_color("red", localize=False).name == "#ff0000"


def test_str_to_color_invalid_raises():
    from pytermgui.colors import str_to_color
    from pytermgui.exceptions import ColorSyntaxError

    with pytest.raises(ColorSyntaxError):
        str_to_color("not-a-color", localize=False, use_cache=False)


# ---------------------------------------------------------------------------
# Color system: color math
# ---------------------------------------------------------------------------


def test_luminance_and_brightness():
    from pytermgui.colors import Color

    assert Color.parse("#ff0000", localize=False).luminance == 0.2126
    assert Color.parse("#808080", localize=False).brightness == 0.5358501345216902


def test_contrast_complement_blend():
    from pytermgui.colors import Color

    # Dark color -> near-white contrast (white blended toward its complement).
    assert Color.parse("#141414", localize=False).contrast.hex == "#f2f2f2"
    # Pure red has HLS hue 0.0 (lightness 0.498, not black), so complement is black.
    assert Color.parse("#ff0000", localize=False).complement.hex == "#000000"
    # Midpoint blend of black and white.
    black = Color.parse("#000000", localize=False)
    white = Color.parse("#ffffff", localize=False)
    assert black.blend(white, 0.5).hex == "#7f7f7f"


# ---------------------------------------------------------------------------
# Color system: indexed cube + nearest-16
# ---------------------------------------------------------------------------


def test_indexed_color_from_rgb_cube():
    from pytermgui.colors import IndexedColor

    _fresh()
    assert IndexedColor.from_rgb((95, 175, 215)).value == "110"
    _fresh()
    assert IndexedColor.from_rgb((0, 0, 0)).value == "16"
    _fresh()
    assert IndexedColor.from_rgb((255, 255, 255)).value == "231"


def test_standard_color_from_rgb_and_ansi():
    from pytermgui.colors import StandardColor

    _fresh()
    red = StandardColor.from_rgb((255, 0, 0))
    assert red.value == "31"
    assert red.sequence == "\x1b[31m"
    # from_ansi folds a background code to fg+background flag.
    assert StandardColor.from_ansi("41").sequence == "\x1b[41m"


# ---------------------------------------------------------------------------
# Color system: graceful degradation (get_localized)
# ---------------------------------------------------------------------------


def test_color_degradation_across_systems():
    from pytermgui.term import terminal, ColorSystem
    from pytermgui.colors import str_to_color

    # NOTE: the STANDARD (nearest-16) collapse is exercised by
    # test_standard_color_from_rgb_and_ansi; this test deliberately covers only
    # the independent TRUE / EIGHT_BIT / NO_COLOR degradation paths so the two
    # tests do not share a pass/fail facet.

    # TRUE: a hex value keeps its full rgb sequence.
    _fresh()
    terminal.forced_colorsystem = ColorSystem.TRUE
    assert str_to_color("#5fafd7", use_cache=False).sequence == (
        "\x1b[38;2;95;175;215m"
    )

    # EIGHT_BIT: collapses onto the 256 cube index.
    _fresh()
    terminal.forced_colorsystem = ColorSystem.EIGHT_BIT
    assert str_to_color("#5fafd7", use_cache=False).sequence == "\x1b[38;5;110m"

    # NO_COLOR: collapses onto a greyscale-ramp index.
    _fresh()
    terminal.forced_colorsystem = ColorSystem.NO_COLOR
    assert str_to_color("#5fafd7", use_cache=False).sequence == "\x1b[38;5;247m"


# ---------------------------------------------------------------------------
# Regex / length helpers
# ---------------------------------------------------------------------------


def test_strip_helpers():
    from pytermgui.regex import strip_ansi, strip_markup, escape_markup

    assert strip_ansi("\x1b[1mHi\x1b[0m") == "Hi"
    assert strip_markup("[bold]Hi[/]") == "Hi"
    assert escape_markup("[bold]hi") == "\\[bold]hi"


def test_real_length_wcwidth():
    from pytermgui.regex import real_length

    # ANSI is not counted.
    assert real_length("\x1b[1mHi\x1b[0m") == 2
    # Wide (CJK) characters count as 2.
    assert real_length("aあb") == 4


def test_has_open_sequence():
    from pytermgui.regex import has_open_sequence

    # A complete SGR is closed by its trailing 'm'.
    assert has_open_sequence("\x1b[1mHi\x1b[0m") is False
    # A truncated SGR is open.
    assert has_open_sequence("a\x1b[38;5;1") is True
    # A complete OSC-8 close is not open.
    assert has_open_sequence("\x1b]8;;url\x1b\\") is False
    # An OSC missing its \x1b\\ terminator is open.
    assert has_open_sequence("\x1b]8;;url") is True


# ---------------------------------------------------------------------------
# Highlighters
# ---------------------------------------------------------------------------


def test_highlight_python():
    from pytermgui.highlighters import highlight_python

    assert highlight_python("def foo(): return 1") == (
        "[code.keyword]def[/code.keyword] [code.identifier]foo[/code.identifier]"
        "(): [code.keyword]return[/code.keyword] [code.number]1[/code.number]"
    )
    assert highlight_python("x = 0xFF") == "x = [code.number]0xFF[/code.number]"


def test_regex_highlighter_custom():
    from pytermgui.highlighters import RegexHighlighter

    hl = RegexHighlighter(prefix="t.", styles=[("num", r"\d+")])
    assert hl("a12b") == "a[t.num]12[/t.num]b"


# ---------------------------------------------------------------------------
# HTML exporter
# ---------------------------------------------------------------------------


def test_token_to_css():
    from pytermgui.exporters import token_to_css
    from pytermgui.markup.tokens import StyleToken
    from pytermgui.markup.parsing import consume_tag

    assert token_to_css(StyleToken("bold")) == "font-weight: bold"
    assert token_to_css(StyleToken("italic")) == "font-style: italic"
    assert token_to_css(StyleToken("dim")) == "opacity: 0.7"
    # Build the ColorToken through the documented "anything parseable as a color ->
    # ColorToken" path so the assertion depends only on the spec'd "wraps a parsed
    # Color" contract, not on the token's undocumented positional constructor order.
    ct = consume_tag("141")
    assert token_to_css(ct) == "color:#af87ff"


def test_to_html_document_contract():
    import re

    from pytermgui.exporters import to_html

    # The styled content lives inside the documented <pre class="ptg"> block.
    html = to_html("\x1b[1mBold\x1b[0m")
    assert '<pre class="ptg">' in html

    # The bold run is wrapped in its own <span> whose styling carries the
    # documented bold CSS (font-weight: bold), not just a stray substring. With
    # inline_styles the span carries the CSS directly, so we can pin the contract:
    # the bold text "B&C" (HTML-escaped) is inside a span that has font-weight: bold.
    inline = to_html("\x1b[1mB&C\x1b[0m", inline_styles=True)
    # Plain text is HTML-escaped (& -> &amp;) and lives inside the styled span.
    # The instruction documents the inline form as a `style=` attribute; we assert
    # that contract (span wraps the escaped text and its attributes carry the bold
    # CSS) without over-pinning the exact attribute spelling/quoting.
    m = re.search(r"<span style[^>]*>B&amp;C</span>", inline)
    assert m is not None, inline
    assert "font-weight: bold" in m.group(0)


# ---------------------------------------------------------------------------
# Widget rendering: Label / Container / Splitter compose to character-grid lines
# ---------------------------------------------------------------------------


def test_widget_label_container_splitter_rendering():
    import pytermgui as ptg
    from pytermgui.regex import strip_ansi

    # A Label renders its TIM markup straight to a single styled line.
    assert ptg.Label("[bold]Hi").get_lines() == ["\x1b[1mHi\x1b[0m"]

    # A Container with a known box style draws a bordered box around its child,
    # sized to its width, with the child centered. Assert the box glyphs and
    # geometry via strip_ansi (the border's color styling is a theme detail).
    container = ptg.Container(ptg.Label("Hi"), box="SINGLE")
    container.width = 12
    assert [strip_ansi(line) for line in container.get_lines()] == [
        "┌──────────┐",
        "│    Hi    │",
        "└──────────┘",
    ]

    # A Splitter lays its children out horizontally, each centered in an equal
    # share of the width, joined by the " | " separator.
    splitter = ptg.Splitter(ptg.Label("L"), ptg.Label("R"))
    splitter.width = 13
    rendered = [strip_ansi(line) for line in splitter.get_lines()]
    assert rendered == ["  L   |   R  "]
    assert len(rendered[0]) == 13


# ---------------------------------------------------------------------------
# Window manager: Layout slot geometry + Window rendering
# ---------------------------------------------------------------------------


def test_layout_slot_geometry_and_window_rendering():
    import pytermgui as ptg
    from pytermgui.regex import strip_ansi

    # A Layout collects named slots separated by breaks; apply() materializes one
    # entry per slot and break. Auto slots have a deferred Auto(value=0) dimension
    # until apply() computes their geometry.
    layout = ptg.Layout()
    layout.add_slot("Header")
    layout.add_break()
    layout.add_slot("Body")
    layout.add_break()
    layout.add_slot("Footer")
    assert str(layout.header.width) == "Auto(value=0)"
    layout.apply()
    assert len(layout.slots) == 5

    # A slot given an explicit width gets a fixed Static dimension; an unspecified
    # one stays Auto.
    fixed = ptg.Layout()
    fixed.add_slot("one", width=10, height=15)
    fixed.add_break()
    fixed.add_slot("two")
    assert str(fixed.one.width) == "Static(value=10)"
    fixed.apply()
    assert fixed.one.width.value == 10
    assert str(fixed.two.width).startswith("Auto(")

    # A Window is itself a renderable widget: under the pinned terminal it draws a
    # bordered box around its widgets, just like a Container.
    window = ptg.Window(ptg.Label("Hi"), box="SINGLE")
    window.width = 12
    assert [strip_ansi(line) for line in window.get_lines()] == [
        "┌──────────┐",
        "│    Hi    │",
        "└──────────┘",
    ]
