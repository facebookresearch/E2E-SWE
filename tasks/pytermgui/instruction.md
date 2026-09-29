# pytermgui

A pure-Python terminal-UI toolkit. Importable as `pytermgui` (commonly aliased `ptg`). Package name `PyTermGUI`. Runtime dependencies: `wcwidth`, `typing_extensions`.

This task covers the deterministic core of the library: the **TIM markup engine**, the **color system**, the **regex/length helpers**, the **syntax highlighters**, and the **HTML exporter**. It also covers the **deterministic rendering surface** of the **widget system** and **window manager** — how widgets (`Label`, `Container`, `Splitter`) compose to character-grid line strings via `get_lines()`, how a `Layout` lays out named slots, and how a `Window` renders (§7). The genuinely *interactive* parts (the live input/mouse loop, the `WindowManager` draw loop, animations, the CLI) require a real terminal and are out of scope / not tested.

## Environment & Dependencies

The environment is **fully offline** — there is no network access. The runtime dependencies (`wcwidth`, `typing_extensions`) and the build backend are **already installed**; you must **not** install (or attempt to install) anything. Just implement the package.

The project is installed for grading by a `setup.sh` that runs **offline** (`pip install -e . --no-build-isolation`). Your `pyproject.toml` (or equivalent) must declare the distribution as `PyTermGUI` with the import name `pytermgui`, installable via that offline editable install.

The public names described below are re-exported from `pytermgui.__init__` (so `ptg.Label`, `ptg.Container`, `ptg.Splitter`, `ptg.Layout`, `ptg.Window` are all top-level). Submodules referenced by tests: `pytermgui.colors`, `pytermgui.regex`, `pytermgui.highlighters`, `pytermgui.exporters`, `pytermgui.term`, and the `pytermgui.markup` package (with `pytermgui.markup.parsing`, `.tokens`, `.style_maps`, `.macros`, `.aliases`).

## 1. Terminal & color systems (`pytermgui.term`)

`ColorSystem` is an `Enum` with members and integer values: `NO_COLOR = -1`, `STANDARD = 0`, `EIGHT_BIT = 1`, `TRUE = 2`. It implements rich comparison (`<`, `<=`, `>`, `>=`) by comparing the integer `.value`, so `ColorSystem.STANDARD < ColorSystem.TRUE`.

There is a module-level singleton `terminal` (a `Terminal` instance), also obtainable via `get_terminal()`. It exposes:

- `terminal.size`: a writable `(width, height)` tuple. `terminal.width` / `terminal.height` read from it.
- `terminal.forced_colorsystem`: a writable `ColorSystem | None`. When not `None`, it overrides detection.
- `terminal.colorsystem`: the effective `ColorSystem`. Returns `forced_colorsystem` when set; otherwise it consults the environment (`NO_COLOR` → `ColorSystem.NO_COLOR`, `PTG_COLOR_SYSTEM` naming a member, terminal capabilities) and finally falls back to `STANDARD`.

Tests pin `terminal.forced_colorsystem` and `terminal.size` to make all output deterministic.

## 2. Color system (`pytermgui.colors`)

The base class is `Color` (a dataclass) with subclasses `IndexedColor`, `StandardColor` (subclass of `IndexedColor`), `RGBColor`, `HEXColor` (subclass of `RGBColor`), and `GreyscaleRampColor` (subclass of `IndexedColor`). Each carries a `value: str`, a `background: bool` flag, and a class-level `system: ColorSystem`:

- `RGBColor` / `HEXColor` → `ColorSystem.TRUE`
- `IndexedColor` → `ColorSystem.EIGHT_BIT`
- `StandardColor` → `ColorSystem.STANDARD`
- `GreyscaleRampColor` → used for `NO_COLOR`

### Parsing

`str_to_color(text, is_background=False, localize=True, use_cache=True) -> Color` and the convenience `Color.parse(text, background=False, localize=True, use_cache=False)` parse a string into a color. Accepted forms:

- A bare integer `0`-`255` → `IndexedColor`.
- `"rrr;ggg;bbb"` → `RGBColor`.
- `"(#)rrggbb"` (leading `#` optional) → `HEXColor`.
- A name from the CSS named-color table or an `ansi-*` name → resolved through that table. A
  CSS-named color resolves to a `HEXColor`, so its `.name` / `.markup` is the canonical
  `#rrggbb` hex string (e.g. `str_to_color("red").name == "#ff0000"`), not the `r;g;b` form.
- A leading `@` forces `background=True` (e.g. `"@141"`, `"@#123abc"`).
- An ANSI color code body (e.g. `"38;5;141m"`, `"48;2;.."`) is trimmed to its color part before parsing.

Unparseable input raises `ColorSyntaxError` (from `pytermgui.exceptions`). When `localize=True`, the parsed color is immediately passed through `get_localized()` (see degradation). `str_to_color` is memoized; there is a `clear_color_cache()` and `str_to_color.cache_clear()` for resetting caches, and `use_cache=False` bypasses the memo for one call.

### Color properties

- `.sequence`: the COMPLETE ANSI SGR escape that activates this color — the body wrapped in the CSI introducer and `m` terminator, i.e. `\x1b[<body>m` (the same `\x1b[...m` framing the spec uses for `StyleToken`/`ClearToken` below), not the bare body. The body is `38;5;{n}` / `48;5;{n}` for indexed colors, `38;2;r;g;b` / `48;2;r;g;b` for RGB colors, and the bare `30`-`37` / `40`-`47` (and `90`-`107`) code for standard colors. The `48` / background variants are used when `background` is set. For example `str_to_color("141", localize=False).sequence == "\x1b[38;5;141m"` and `str_to_color("red", localize=False).sequence == "\x1b[38;2;255;0;0m"`.
- `.markup`: the TIM token text — the `value`, prefixed with `@` when `background`.
- `.name`: reverse-parseable name (same as `.markup` for most types; `StandardColor.name` maps the stored ANSI index back to its TIM number).
- `.hex`: CSS-style `#rrggbb`.
- `.rgb`: an `(r, g, b)` int tuple. For indexed/standard colors this is looked up from `COLOR_TABLE` (in `pytermgui.color_info`), a 256-entry table. Its first 16 entries are the classic CGA/ANSI 16-color palette built on 0/170/85/255 channel levels (not the VGA 128-based or xterm defaults):

  ```
  0=(0,0,0)      1=(170,0,0)    2=(0,170,0)    3=(170,85,0)
  4=(0,0,170)    5=(170,0,170)  6=(0,170,170)  7=(170,170,170)
  8=(85,85,85)   9=(255,85,85)  10=(85,255,85) 11=(255,255,85)
  12=(85,85,255) 13=(255,85,255) 14=(85,255,255) 15=(255,255,255)
  ```

  Entries 16..231 are the standard xterm-256 6×6×6 cube and 232..255 the greyscale ramp. The CSS named-color table `CSS_COLORS` also lives in `pytermgui.color_info`.

### Constructing indexed colors from RGB

`IndexedColor.from_rgb(rgb)` maps an RGB triplet onto the xterm-256 6×6×6 color cube. Normalize each channel to `0..1` (divide by 255), then:

```
index = 16 + 36 * round(r * 5) + 6 * round(g * 5) + round(b * 5)
```

(If the effective colorsystem is `STANDARD`, it delegates to `StandardColor.from_rgb` instead.)

`StandardColor.from_rgb(rgb)` chooses the closest of the first 16 entries of `COLOR_TABLE` by nearest RGB color distance, then converts the table index `i` to an ANSI code: `i + 30` for `i ≤ 7`, otherwise `i + 82`. `StandardColor.from_ansi(code)` builds one from an ANSI code, passed as a **string** (consistent with the string-valued color model, where `value: str`), in `"30"`-`"47"` / `"90"`-`"107"`, folding background codes (`"40"`-`"47"`, `"100"`-`"107"`) down to the foreground code with `background=True`. For example `StandardColor.from_ansi("41").sequence == "\x1b[41m"`.

`GreyscaleRampColor.from_rgb(rgb)` picks a grey ramp entry: `index = int(232 + brightness * 23)` using the color's `brightness` (below).

### Perceptual quantities

- `.luminance`: relative luminance. Linearize each sRGB channel `c` in `0..1` via `c/12.92` if `c ≤ 0.04045` else `((c + 0.055)/1.055) ** 2.4`, then combine with Rec. 709 weights `0.2126*R + 0.7152*G + 0.0722*B`.
- `.brightness`: perceived brightness derived from luminance `L`. If `L ≤ 216/24389`, `brightness = L * (24389/27)`, else `brightness = L ** (1/3) * 116 - 16`; the result is divided by `100`.
- `.contrast`: returns black or white blended slightly with its complement so it satisfies the W3C contrast guideline — `#000000` when `luminance > 0.179`, else `#ffffff`, each blended toward its complement by `0.05`.
- `.complement`: the hue-rotated complement (hue offset by `0.5`). As a special case, a color whose HLS hue is exactly `0.0` (e.g. pure red, or any pure grey) has no meaningful hue to rotate, so it returns white when the color is black (HLS lightness `0.0`) and black otherwise.
- `.blend(other, alpha=0.5)`: linear per-channel interpolation `int(c1 + (c2 - c1) * alpha)`, returning an `RGBColor`. `darken`/`lighten`/`blend_complement`/`blend_contrast` are blends toward black/white/complement/contrast.

### Graceful degradation

`get_localized()` returns a color appropriate for `terminal.colorsystem`. If the color's own `system` is already `<=` the terminal's, it is returned unchanged; otherwise it is rebuilt via the target type's `from_rgb` (TRUE→`RGBColor`, EIGHT_BIT→`IndexedColor`, STANDARD→`StandardColor`, NO_COLOR→`GreyscaleRampColor`), preserving `background`. This is what makes a true-color value collapse down to a 256-color index, a 16-color code, or a grey-ramp index under a more limited terminal.

`foreground(text, color, reset=True)` / `background(text, color, reset=True)` wrap text in the color's sequence (forcing the fg/bg flag) plus an optional reset.

## 3. The TIM markup engine (`pytermgui.markup`)

TIM ("Terminal Inline Markup") is the library's markup language. Markup is text with bracketed **tag groups**: `[tag tag ...]content`. Inside a group, tags are space-separated. A backslash escapes a bracket (`\[bold]` is literal text).

### Tokens (`pytermgui.markup.tokens`)

Tokenizing produces a stream of `Token` subclasses, each with a `value` and a `markup` property. The token types are: `PlainToken` (literal text between groups), `ColorToken` (wraps a parsed `Color`; its `markup` is the color's markup), `StyleToken` (a named style), `ClearToken` (a `/`-prefixed clearer), `AliasToken` (a user-defined alias name), `MacroToken` (a `!`-prefixed macro with a tuple of `arguments`), `HLinkToken` (a hyperlink target; `markup` is `~{uri}`), `CursorToken` (a `(y;x)` cursor move), and `PseudoToken` (state pseudo-tags). `Token` exposes a predicate per type following the pattern `is_<typename>()` (e.g. `is_color()`, `is_clear()`, `is_macro()`), available both as an instance method and as a static method `Token.is_color(tkn)`.

A `ClearToken` knows what it clears via `targets(other_token)`: `/` targets everything (except cursors/clearers), `/{name}` targets the matching tag, `/fg` and `/bg` target foreground/background colors respectively, `/!` targets macros, and `/~` targets hyperlinks.

### Styles and clearers (`pytermgui.markup.style_maps`)

`STYLES` maps style names to their SGR codes: `bold=1`, `dim=2`, `italic=3`, `underline=4`, `blink=5`, `blink2=6`, `inverse=7`, `invisible=8`, `strikethrough=9`, `overline=53`. `CLEARERS` maps clearer tags to SGR codes: `/=0`, `/bold` and `/dim` both `=22`, `/italic=23`, `/underline=24`, `/blink=25`, `/blink2=26`, `/inverse=27`, `/invisible=28`, `/strikethrough=29`, `/fg=39`, `/bg=49`, `/overline=54`. `REVERSE_STYLES` / `REVERSE_CLEARERS` are the inverse maps. A `StyleToken` parses to `\x1b[{code}m`; a `ClearToken` to `\x1b[{code}m` (with `/~` instead emitting the hyperlink-close OSC `\x1b]8;;\x1b\\`).

### Tag classification

`consume_tag(tag)` turns one tag string into the right `Token`: a name in `STYLES` → `StyleToken`; a `/`-prefixed string → `ClearToken`; a `!`-prefixed string → `MacroToken` (parsing optional `(arg:arg)` parens into the `arguments` tuple, colon-separated); a `~`-prefixed string → `HLinkToken`; a `(y;x)` string → `CursorToken`; a recognized pseudo-tag → `PseudoToken`; anything parseable as a color → `ColorToken`; otherwise an `AliasToken`.

### Parsing pipeline

- `tokenize_markup(text)` yields the token stream for some markup.
- `tokenize_ansi(text)` yields the token stream for ANSI-coded text (the inverse direction).
- `parse_tokens(tokens, *, optimize=False, context=None, append_reset=True, ignore_unknown_tags=True)` renders tokens to an ANSI-coded string. Color tokens render through `get_localized()`. Macros apply to the plain text that follows them; aliases are substituted from `context`; hyperlinks wrap following plain text in OSC-8 (`\x1b]8;;{uri}\x1b\\{label}\x1b]8;;\x1b\\`). When `append_reset` is set, a trailing `\x1b[0m` reset is emitted.
- `parse(text, optimize=False, context=None, append_reset=True, ignore_unknown_tags=True)` is the convenience entry point: it appends `[/]` to the text (unless already ending in `/]`), tokenizes, and calls `parse_tokens`.
- `tokens_to_markup(tokens)` renders a token stream back to markup text (grouping consecutive non-plain tokens into `[...]` groups).
- `get_markup(ansi_text)` = `tokens_to_markup(list(tokenize_ansi(ansi_text)))`, i.e. ANSI → markup.

### Optimization

`optimize_tokens(tokens)` removes functionally-redundant tokens while preserving visible output: duplicate styles, multiple colors on the same channel (only the last survives), and a tag paired with its own matching clearer within the same group that cancel. This cancellation covers both a color and its clearer (`/fg`/`/bg`) and a **style and its own clearer** (e.g. `bold` and `/bold`): when a style tag is immediately paired with its matching clearer inside one tag group — with no intervening plain-text run — the pair is net-zero and **neither** the style nor the clearer survives. It also tracks the set of tokens already *active* from the preceding plain-text run and, at each new run, emits only the difference: a style or color that carries over unchanged from the previous run is not re-emitted, and a clearer is dropped unless it actually targets something currently active. So `[bold]A[bold 141]B` optimizes to `[bold]A[141]B` (the bold carries over, only the new `141` is added). `optimize_markup(markup)` round-trips markup through tokenize → optimize → `tokens_to_markup`. `parse(..., optimize=True)` optimizes before rendering.

### Macros (`pytermgui.markup.macros`)

Built-in macros (registered into a language's context) include the case transforms `!upper`, `!lower`, `!title` (apply `str.upper`/`lower`/`title` to the following text); `!align(width:alignment)` (f-string alignment, `f"{content:{aligner}{width}}"`, where `alignment` is `left`/`right`/`center` mapping to `<`/`>`/`^`); `!shuffle`; and the color macros `!gradient(base)` and `!rainbow`. A macro applies to the plain text that follows it within the same render.

`!gradient(base)` builds an xterm-256 vertical gradient column from the integer `base` index (which must be in `16..231`). The 6×6×6 cube is laid out so that adding 36 steps one row down the same gradient; the macro first walks `base` back to the column's start (`while base > 52: base -= 36`), then takes the six indices `base + 36*i` for `i` in `0..5`. Those six colors are spread evenly across the text (block size `max(round(len(text)/6), 1)`, each block opening with the next color), and the run is closed with `[/fg]`.

### Aliases (`pytermgui.markup.aliases`)

An alias maps a custom tag name to a markup string. Alias values may themselves reference other aliases, and such chains are resolved transitively at parse time (and when generating the unsetter). The default aliases include a `code.*` group used by the highlighters (e.g. `code.keyword`, `code.str`, `code.number`, `code.identifier`, `code.comment`, mapping to color/style markup). Defining an alias also auto-generates its `/name` unsetter: each tag in the (fully-expanded) alias value contributes a clearer — a style/macro/alias contributes `/{tag}`, a foreground color contributes `/fg`, a background color contributes `/bg`. The generated unsetter is itself registered as an alias — an entry mapping the tag name `/name` to that clearer string — in the same alias table (not a separate/private store), so it is readable back through the public `.aliases` mapping under the key `/name`. For example, after `lang.alias("my-tag", "141 bold")`, `lang.aliases["/my-tag"] == "/fg /bold"`.

### `MarkupLanguage`, `tim`, and `escape` (`pytermgui.markup.language`)

`MarkupLanguage` binds a parsing context. Its constructor accepts `strict`, `default_aliases`, `default_macros` (all defaulting to apply). It exposes `.parse(text, optimize=False, append_reset=True)` (a cached wrapper over the engine using its own context), `.aliases` / `.macros` (copies of the context dicts), `.alias(name, value, *, generate_unsetter=True)`, `.alias_multiple(**items)`, `.define(name, method)` (macro names must start with `!`), and `.clear_cache()`. A module-level instance `tim` (with the defaults applied) is the standard entry point, so `tim.parse("[bold]Hi")` is the canonical way to render markup. `MarkupLanguage.parse` does not pre-append `[/]` the way the module-level `parse` does: it tokenizes the text as given and hands the stream to `parse_tokens`, so with `append_reset` its result ends with exactly one trailing `\x1b[0m`. `escape(text)` backslash-escapes every bracketed group in the text so it survives re-parsing. Escaping a group inserts a single backslash before its **opening** `[` only, leaving the closing `]` unchanged, e.g. `escape("[bold]hi") == "\\[bold]hi"`.

`StyledText` is a frozen helper wrapping a parsed (`sequences`, `plain`, `tokens`, `link`) group; `StyledText.group_styles(text)` yields one `StyledText` per plain-text run of an ANSI string, and it exposes boolean style properties (`.bold`, `.italic`, …) plus `.foreground` / `.background` colors derived from its tokens.

## 4. Regex / length helpers (`pytermgui.regex`)

- `strip_ansi(text)`: removes all ANSI/OSC/APC escape sequences.
- `strip_markup(text)`: removes all TIM tag groups (`[...]`).
- `escape_markup(text)`: backslash-escapes bracketed groups (same effect as `escape` — a single backslash before each group's opening `[` only, the closing `]` left as-is), e.g. `escape_markup("[bold]hi") == "\\[bold]hi"`.
- `real_length(text)`: the display width of `text` after stripping ANSI, measured with `wcwidth` (so wide characters count as 2), floored at 0.
- `has_open_sequence(text)`: `True` when the text contains at least one un-terminated escape sequence. An SGR sequence (`\x1b[`…) is closed by a final `m` or `H`; an OSC (`\x1b]`…) or Kitty APC (`\x1b_G`…) sequence is closed by `\x1b\\`. A sequence missing its proper terminator counts as open.

## 5. Highlighters (`pytermgui.highlighters`)

`RegexHighlighter` is a dataclass taking `styles` (a list of `(alias_name, pattern)` tuples), an optional `prefix`, and optional `pre_formatter` / `match_formatter` / `re_flags`. On construction it combines its patterns into one regex of named groups (`(?P<name>pattern)|...`, in order). Calling it replaces each match with `[{prefix}{name}]{matched}[/{prefix}{name}]`, where the group name is taken from the last-matched named group. Results are cached per input.

Two pre-built instances are provided:

- `highlight_python(code)`: a `RegexHighlighter` with `prefix="code."` that wraps Python source in `code.*` tags — strings, comments, keywords, builtins, call identifiers (a name immediately followed by `(`), capitalized globals, and numbers. The number pattern recognizes both plain integer literals and hex literals (`0x`-prefixed), matching the whole literal (prefix plus digits) as a single `code.number` token — so `0xFF` is wrapped as one token, not split. For example `highlight_python("def foo(): return 1")` highlights `def`/`return` as `code.keyword`, `foo` as `code.identifier`, and `1` as `code.number`, and `highlight_python("x = 0xFF")` wraps `0xFF` as a single `code.number`.
- `highlight_tim(code)`: highlights TIM markup itself, returning TIM whose tags are wrapped in their own prettified markup.

## 6. HTML exporter (`pytermgui.exporters`)

- `token_to_css(token, invert=False)`: the CSS fragment for a token. A `ColorToken` yields `color:{hex}` (prefixed with `background-` when the color is a background, e.g. `background-color:{hex}`); the style tokens map as `bold`→`font-weight: bold`, `italic`→`font-style: italic`, `dim`→`opacity: 0.7`, `underline`→`text-decoration: underline`, `strikethrough`→`text-decoration: line-through`, `overline`→`text-decoration: overline`; anything else yields `""`.
- `to_html(obj, prefix=None, inline_styles=False, include_background=True, ...)`: renders a widget, a `StyledText`, or a plain (ANSI-coded) string into a standalone HTML document. The document embeds the styled content in a `<pre class="ptg"><code>…</code></pre>` block with a `<style>` section (or inline `style=` attributes when `inline_styles` is set); style runs are emitted as `<span>` elements carrying the CSS derived from `token_to_css`. The terminal's default fore/background hex values seed the document's CSS variables.

## 7. Widget rendering & layout (`pytermgui.widgets`, `pytermgui.window_manager`)

Widgets are the building blocks of a TUI: each has a writable `width`/`height` and renders itself to a list of line strings via `get_lines() -> list[str]`. Rendering is deterministic once `terminal.size` and `terminal.forced_colorsystem` are pinned, so the surface below is testable headlessly. The widget/window classes named here are re-exported at top level (`ptg.Label`, `ptg.Container`, `ptg.Splitter`, `ptg.Window`, `ptg.Layout`).

### Widgets

- `Label(value="", parent_align=HorizontalAlignment.CENTER, ...)`: a single-line widget whose `value` is TIM markup. Its `get_lines()` returns one line: the markup parsed to ANSI. A bare label does not pad itself to its `width`; its parent applies alignment when it is placed.

- `Container(*widgets, box="SINGLE", ...)`: stacks its child widgets vertically and draws a border around them, sized to its `width`. The `box` selects a glyph set; the default `"SINGLE"` uses corners `┌ ┐ ┘ └` and the `─` / `│` edges (other named boxes include `DOUBLE` → `╔ ╗ ╝ ╚` and `HEAVY` → `┏ ┓ ┛ ┗`). Each inner line is the bordered row with the child content centered in the interior. The border glyphs may additionally carry theme color styling; only the box geometry is contractual.

- `Splitter(*widgets, ...)`: lays its children out **horizontally**, giving each an equal share of the width and joining adjacent children with its separator (default `" | "`). The separators' width comes out of the total before the remainder is divided equally among the children, so the joined line is exactly the splitter's `width`. Each child is rendered (and centered) within its share.

### Layout & Window (`pytermgui.window_manager`)

`Window(*widgets, box="SINGLE", ...)` is a `Container`-like widget managed by the window manager; under the pinned terminal it renders a bordered box around its widgets exactly as a `Container` does.

`Layout` arranges named regions ("slots") of the screen:

- `add_slot(name, width=None, height=None)` appends a slot. With no explicit size a dimension is `Auto` (its repr is `Auto(value=0)` before layout); given an integer it is `Static` (repr `Static(value=N)`); given a float it is a relative fraction of the terminal dimension.
- `add_break()` appends a row break between slots.
- A slot is reachable as an attribute by its lower-cased name (e.g. `layout.header`), exposing `.width` / `.height` dimension objects (each with a `.value`).
- `apply()` computes every slot's concrete geometry. After it, `len(layout.slots)` counts every slot **and** break that was added, and a `Static` dimension's `.value` is the size it was given. Computing a slot's geometry fills in its dimension `.value` **in place without changing the dimension's type**: a slot given an integer stays a `Static` (its `.value` unchanged), and an unsized slot keeps its `Auto` dimension object — it is **not** replaced by a `Static`, so after `apply()` its repr still reads `Auto(value=N)` where `N` is the computed size (an unsized slot's `Auto` width/height gets an equal share of the terminal's remaining width/height). Thus `str(auto_slot.width)` starts with `"Auto("` both before and after `apply()`, only its `.value` changes.
