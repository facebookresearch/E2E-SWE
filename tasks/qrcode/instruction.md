# python-qrcode — QR Code Generation Library

Implement **qrcode**, a Python library that generates QR codes. The library encodes data into QR code matrices using the QR code specification (ISO/IEC 18004), supporting multiple data modes, error correction levels, and output formats (PNG via Pillow, SVG, ASCII art).

## Dependencies

The environment is **offline** and all dependencies are **already installed** — do not install
anything (there is no network). The project itself is installed for you by a `setup.sh` that runs
offline. The pre-installed runtime dependencies are:

- `pillow` — for PNG image output (PilImage / StyledPilImage)
- `deprecation` — for deprecation warnings

## Package Structure

```python
import qrcode
from qrcode import QRCode, make
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from qrcode.exceptions import DataOverflowError
from qrcode.image import svg
from qrcode.image.styledpil import StyledPilImage
from qrcode.image.styles.moduledrawers.pil import (
    SquareModuleDrawer, CircleModuleDrawer, GappedSquareModuleDrawer,
    RoundedModuleDrawer, VerticalBarsDrawer,
)
from qrcode.image.styles.colormasks import (
    SolidFillColorMask, RadialGradiantColorMask,
    HorizontalGradiantColorMask, VerticalGradiantColorMask,
)
from qrcode.util import MODE_NUMBER, MODE_ALPHA_NUM, MODE_8BIT_BYTE
```

The CLI is invokable via `python -m qrcode`.

## 1. Quick API

`qrcode.make(data, **kwargs)` — one-line QR code generation. Returns an image object. Passes kwargs to the `QRCode` constructor.

## 2. QRCode Class

```python
QRCode(version=None, error_correction=ERROR_CORRECT_M, box_size=10, border=4,
       image_factory=None, mask_pattern=None)
```

- `version`: 1–40 (QR code size). `None` = auto-fit to data.
- `error_correction`: one of the four `ERROR_CORRECT_*` constants.
- `box_size`: pixels per module.
- `border`: quiet zone width in modules. Any value `>= 0` is allowed; the default is 4 (the minimum recommended by the QR spec), but smaller borders (including 0) are valid.
- `mask_pattern`: 0–7 for explicit mask, `None` for auto-selection.

Key methods:
- `add_data(data, optimize=20)` — add data to encode. `optimize` controls mode-splitting threshold (0 = no optimization).
- `make(fit=True)` — compile data into the module grid. Auto-fits version if `fit=True`.
- `make_image(image_factory=None, **kwargs)` — generate an image. Auto-selects PilImage if Pillow is available. Accepts `fill_color`, `back_color`, `embedded_image`, `embedded_image_path` kwargs. Passing `embedded_image` or `embedded_image_path` requires `error_correction=ERROR_CORRECT_H`; otherwise raises `ValueError`.
- `get_matrix()` — returns `list[list[bool]]` including border.
- `print_ascii(out=None, tty=False, invert=False)` — Unicode-block "ASCII art" output (uses characters like `█`, `▀`, `▄`, and spaces). With `border=0` and `invert=False`, the output begins with the top-left finder pattern rendered as `█▀▀▀▀▀█`.
- `print_tty(out=None)` — TTY-colored output. Light modules use `\x1b[1;47m` (bold white background), dark modules use `\x1b[40m` (black background), and each line ends with a `\x1b[0m` reset. Each module is two spaces wide, and a one-module light quiet zone surrounds the code on every side (so each line spans `modules_count + 2` modules). Requires `out.isatty()` to return True.
- `clear()` — reset all internal state (data, version, module grid) so the instance can be reused.
- `data_list` — list of `QRData` objects after `add_data()`. Each entry has a `mode` attribute (one of `MODE_NUMBER`, `MODE_ALPHA_NUM`, `MODE_8BIT_BYTE`).

Validation (at construction and at `make_image` time — but NOT eagerly on plain attribute assignment like `qr.box_size = -1`):
- `version` outside 1–40 → `ValueError`
- `border` < 0 → `ValueError`
- `box_size` ≤ 0 → `ValueError` (checked at construction and inside `make_image`, not on bare assignment)
- `mask_pattern` not an int → `TypeError`; outside 0–7 → `ValueError` (checked at construction and via property setter)

## 3. Error Correction Constants

Four constants representing recovery capability:

- `ERROR_CORRECT_L` — ~7% recovery
- `ERROR_CORRECT_M` — ~15% recovery (default)
- `ERROR_CORRECT_Q` — ~25% recovery
- `ERROR_CORRECT_H` — ~30% recovery

## 4. Data Encoding

Data is automatically encoded using the most efficient mode:
- **Numeric** (`MODE_NUMBER`) — digits only: most compact
- **Alphanumeric** (`MODE_ALPHA_NUM`) — uppercase letters, digits, and the characters ` $%*+-./:` only. Comma, lowercase letters, and newline are NOT alphanumeric — they force byte mode.
- **Byte** (`MODE_8BIT_BYTE`) — any data including UTF-8

With `optimize > 0`, mixed content is split into optimal-mode chunks. Each chunk uses the most compact mode that fits its character set. With `optimize=0`, all data uses a single mode.

The `optimize` value is a **minimum run length**: a contiguous numeric run is broken out as its own `MODE_NUMBER` chunk only when it is at least `optimize` characters long, and within the remaining (non-numeric) spans a contiguous alphanumeric run is broken out as its own `MODE_ALPHA_NUM` chunk only when it is at least `optimize` characters long. Runs shorter than `optimize` are absorbed into the surrounding `MODE_8BIT_BYTE` chunk. Numeric runs are detected first; any digit not pulled into a numeric chunk is then eligible to join an adjacent alphanumeric run.

## 5. Image Factories

### PilImage (default)
PNG output via Pillow. Supports `fill_color` and `back_color` kwargs (default black/white). Named colors (e.g. `"red"`, `"yellow"`) and RGB tuples are accepted. Images can be saved to files or BytesIO streams.

### StyledPilImage
Advanced PIL-based factory with pluggable module drawers and color masks. Use by passing `image_factory=StyledPilImage` to `make_image()`.

**Module drawers** control how individual QR modules are rendered. Pass an instance via `module_drawer=` kwarg:
- `SquareModuleDrawer` — default solid squares
- `CircleModuleDrawer` — circular modules
- `GappedSquareModuleDrawer` — squares with gaps between them
- `RoundedModuleDrawer` — squares with rounded corners
- `VerticalBarsDrawer` — vertical bar shapes

**Color masks** control the coloring of QR modules. Pass an instance via `color_mask=` kwarg:
- `SolidFillColorMask(back_color, front_color)` — solid colors
- `RadialGradiantColorMask(back_color, center_color, edge_color)` — radial gradient from center to edge
- `HorizontalGradiantColorMask(back_color, left_color, right_color)` — horizontal gradient
- `VerticalGradiantColorMask(back_color, top_color, bottom_color)` — vertical gradient

Colors are RGB tuples, e.g. `(255, 0, 0)`.

**Embedded images** can be placed in the center of a QR code. Pass via `embedded_image=` (PIL Image object) or `embedded_image_path=` (file path) to `make_image()`. This requires `error_correction=ERROR_CORRECT_H` — lower levels raise `ValueError`.

### SVG Factories
Import from `qrcode.image.svg`:
- `SvgImage` — standalone SVG with XML declaration and an explicit `width` attribute on the root `<svg>` element
- `SvgPathImage` — single `<path>` element SVG
- `SvgFragmentImage` — SVG fragment without XML declaration
- `SvgFillImage` — like SvgImage but with a white background `<rect>`. The background rectangle is emitted using the named-color form `fill="white"` (e.g. `<rect ... fill="white"/>`).
- `SvgPathFillImage` — like SvgPathImage but with a white background `<rect>` (also `fill="white"`)

SVG factories support `save(stream)` and `to_string()`. `to_string()` returns bytes.

SVG factories that support it accept a `module_drawer` string alias (e.g. `"circle"`) to select alternate module shapes.

SVG rect elements should use plain `<rect>` tags without namespace prefixes (not `<svg:rect>`).

## 6. Exceptions

- `DataOverflowError(Exception)` — raised when data exceeds capacity of the specified QR version (when `make(fit=False)` is called).

## 7. CLI

`python -m qrcode [options] [data]` generates QR codes from the command line.

Flags:
- `--output FILE` — output file path (stdout if absent)
- `--error-correction L|M|Q|H` — error correction level
- `--factory pil|png|svg|svg-fragment|svg-path` — image factory
- `--factory-drawer NAME` — alternate module drawer (e.g. `circle` for SVG factories). Invalid names cause an error exit.
- `--optimize N` — optimization threshold
- Data from positional argument or stdin
- An invalid `--factory` name causes a non-zero exit.
