"""
Integration tests for python-qrcode — QR code generation library.

Tests verify correctness by generating QR codes and decoding them back with
pyzbar, ensuring the encoded data matches the input. Covers the Python API
(qrcode.make, QRCode class), CLI, SVG output, error correction levels,
data modes, version control, and edge cases.
"""
import io
import os
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False
    pyzbar_decode = None


def _decode_qr_image(img):
    """Decode a QR code from a PIL Image or qrcode image object.
    Returns the decoded data as a string, or None if pyzbar is unavailable."""
    if not HAS_PYZBAR:
        return None

    if hasattr(img, '_img'):
        pil_img = img._img
    elif hasattr(img, 'get_image'):
        pil_img = img.get_image()
    else:
        pil_img = img

    if not isinstance(pil_img, Image.Image):
        buf = io.BytesIO()
        img.save(buf)
        buf.seek(0)
        pil_img = Image.open(buf)

    results = pyzbar_decode(pil_img)
    if not results:
        return None
    return results[0].data.decode('utf-8')


def _verify_qr_image(img, expected_data=None):
    """Verify a QR image is valid. If pyzbar available, decode and check content.
    Otherwise verify image is non-empty and has reasonable dimensions."""
    if HAS_PYZBAR and expected_data:
        decoded = _decode_qr_image(img)
        assert decoded == expected_data, f"Decoded '{decoded}' != expected '{expected_data}'"
        return

    buf = io.BytesIO()
    if isinstance(img, Image.Image):
        # Raw PIL images need an explicit format when saving to a buffer;
        # qrcode wrapper objects (PilImage, SvgImage, ...) infer it themselves.
        img.save(buf, format='PNG')
    else:
        img.save(buf)
    assert buf.tell() > 100, "Image too small"

    buf.seek(0)
    pil_img = Image.open(buf)
    assert pil_img.size[0] > 20, f"Image width too small: {pil_img.size[0]}"
    assert pil_img.size[1] > 20, f"Image height too small: {pil_img.size[1]}"


# ===========================================================================
# 1. End-to-end: generate QR → decode → verify content
# ===========================================================================
class TestEndToEndDecode(unittest.TestCase):
    """Generate QR codes and decode them to verify encoded data matches input."""

    def test_encode_decode_multiple_data_types(self):
        """qrcode.make() encodes text, URL, numeric, alphanumeric, and unicode data that decodes back correctly."""
        from qrcode import make

        cases = [
            "Hello, World!",
            "https://www.example.com/path?query=value&foo=bar",
            "1234567890",
            "HELLO WORLD 123",
            "café résumé 日本語",
        ]
        for data in cases:
            img = make(data)
            _verify_qr_image(img, data)

    def test_version_auto_selection_and_overflow(self):
        """Long data auto-selects higher QR version; fixed version with too much data raises DataOverflowError."""
        from qrcode import QRCode
        from qrcode.exceptions import DataOverflowError

        data = "A" * 500
        qr = QRCode()
        qr.add_data(data)
        qr.make()
        self.assertGreater(qr.version, 5)
        img = qr.make_image()
        _verify_qr_image(img, data)

        qr2 = QRCode(version=1)
        qr2.add_data("x" * 100)
        with self.assertRaises(DataOverflowError):
            qr2.make(fit=False)

        qr3 = QRCode()
        qr3.add_data(b"binary\x00data\xff")
        img3 = qr3.make_image()
        buf = io.BytesIO()
        img3.save(buf)
        self.assertGreater(buf.tell(), 100)


# ===========================================================================
# 2. QRCode class — full API
# ===========================================================================
class TestQRCodeAPI(unittest.TestCase):
    """QRCode class: version, error correction, box_size, border, matrix."""

    def test_explicit_version_error_correction_and_matrix(self):
        """Explicit version/EC are respected; all EC levels produce decodable QR; get_matrix returns correct bool grid with border."""
        from qrcode import QRCode
        from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H

        data = "Error correction test"
        for level in [ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H]:
            qr = QRCode(error_correction=level)
            qr.add_data(data)
            img = qr.make_image()
            _verify_qr_image(img, data)

        qr = QRCode(version=5, error_correction=ERROR_CORRECT_H, box_size=10, border=4)
        qr.add_data("Test")
        qr.make()
        self.assertEqual(qr.version, 5)

        qr0 = QRCode(version=1, border=0)
        qr0.add_data("A")
        qr0.make()
        matrix0 = qr0.get_matrix()
        self.assertEqual(len(matrix0), 21)
        self.assertEqual(len(matrix0[0]), 21)
        for row in matrix0:
            for val in row:
                self.assertIsInstance(val, bool)

        qr4 = QRCode(version=1, border=4)
        qr4.add_data("A")
        qr4.make()
        matrix4 = qr4.get_matrix()
        self.assertEqual(len(matrix4), 21 + 8)

    def test_clear_and_incremental_fit(self):
        """clear() resets all state including version; adding data incrementally auto-upgrades version."""
        from qrcode import QRCode

        qr = QRCode()
        qr.add_data("a")
        qr.make()
        self.assertEqual(qr.version, 1)
        qr.add_data("bcdefghijklmno")
        qr.make()
        self.assertEqual(qr.version, 2)

        qr.clear()
        qr.add_data("short")
        qr.make(fit=True)
        img1 = qr.make_image()
        buf1 = io.BytesIO()
        img1.save(buf1)
        v1 = qr.version

        qr.clear()
        qr.add_data("A" * 200)
        qr.make(fit=True)
        self.assertGreater(qr.version, v1)

        qr.clear()
        qr.add_data("short")
        qr.make(fit=True)
        self.assertEqual(qr.version, v1)
        img3 = qr.make_image()
        buf3 = io.BytesIO()
        img3.save(buf3)
        # Compare decoded pixel buffers, not raw PNG bytes: zlib/Pillow encoder
        # differences can change the encoded bytes even when pixels are identical.
        img1_px = Image.open(io.BytesIO(buf1.getvalue())).convert("RGBA").tobytes()
        img3_px = Image.open(io.BytesIO(buf3.getvalue())).convert("RGBA").tobytes()
        self.assertEqual(img1_px, img3_px)

        qr.clear()
        qr.add_data("After clear")
        img = qr.make_image()
        _verify_qr_image(img, "After clear")

    def test_print_ascii_and_tty(self):
        """print_ascii produces Unicode block art starting with finder pattern; print_tty produces ANSI-colored output."""
        from qrcode import QRCode

        qr = QRCode(border=0)
        qr.add_data("test")
        qr.make()
        f = io.StringIO()
        qr.print_ascii(out=f)
        ascii_art = f.getvalue()
        expected_start = "█▀▀▀▀▀█"
        self.assertTrue(ascii_art.startswith(expected_start),
                        f"ASCII art should start with finder pattern, got: {ascii_art[:20]!r}")

        qr2 = QRCode()
        qr2.add_data("tty test")
        qr2.make()
        f2 = io.StringIO()
        f2.isatty = lambda: True
        qr2.print_tty(out=f2)
        tty_output = f2.getvalue()
        # Assert the documented print_tty *visual* layout, decoding each line into the
        # background color of every (two-spaces-wide) module cell. This judges what the
        # terminal actually shows, independent of the exact escape-emission scheme: a
        # renderer that re-emits the SGR code per module and one that coalesces runs of
        # same-color modules produce an identical display and both pass here. A
        # wrong-shaped renderer (wrong quiet zone, missing dark finder bar, wrong widths)
        # still fails. The codes, module width, quiet zone and reset are documented in the
        # instruction; the light / 7-module dark bar / light finder-row structure follows
        # from the QR standard (ISO/IEC 18004) the instruction names.
        BOLD_WHITE_BG = "\x1b[1;47m"
        BLACK_BG = "\x1b[40m"
        RESET = "\x1b[0m"

        def module_colors(line):
            """Return the per-module background color of `line` as 'light'/'dark' cells.

            Walks the SGR codes and treats every two literal spaces as one module cell,
            tagged with the background color active at that point.
            """
            colors = []
            active = None
            i = 0
            while i < len(line):
                if line.startswith(BOLD_WHITE_BG, i):
                    active = "light"
                    i += len(BOLD_WHITE_BG)
                elif line.startswith(BLACK_BG, i):
                    active = "dark"
                    i += len(BLACK_BG)
                elif line.startswith(RESET, i):
                    active = None
                    i += len(RESET)
                elif line[i] == "\x1b":
                    m = re.match(r"\x1b\[[0-9;]*[A-Za-z]", line[i:])
                    i += m.end() if m else 1
                elif line[i] == " ":
                    colors.append(active)
                    i += 2
                else:
                    i += 1
            return colors

        # Both documented background codes must appear and every non-blank line resets.
        self.assertIn(BOLD_WHITE_BG, tty_output)
        self.assertIn(BLACK_BG, tty_output)
        lines = [line for line in tty_output.split("\n") if line]
        for line in lines:
            self.assertTrue(line.endswith(RESET),
                            f"each print_tty line should reset with \\x1b[0m, got: {line[-10:]!r}")

        # One-module light quiet zone on every side => modules_count + 2 light/dark rows,
        # each modules_count + 2 modules wide.
        span = qr2.modules_count + 2
        self.assertEqual(len(lines), span,
                         f"print_tty should emit modules_count+2 rows, got {len(lines)}")
        # First row is the all-light quiet zone.
        self.assertEqual(module_colors(lines[0]), ["light"] * span,
                         "first print_tty row should be an all-light quiet-zone row")
        # Next row (top of the finder pattern) is: light quiet-zone module, the 7-module
        # dark finder bar, then a light module, before the rest of the row.
        self.assertEqual(module_colors(lines[1])[:9], ["light"] + ["dark"] * 7 + ["light"],
                         "finder-pattern row should be light, 7 dark, light")
        self.assertEqual(len(module_colors(lines[1])), span,
                         "finder-pattern row should span modules_count+2 modules")

    def test_mask_pattern_selection(self):
        """Explicit mask pattern produces decodable output; different patterns produce different matrices."""
        from qrcode import QRCode

        qr = QRCode(mask_pattern=0)
        qr.add_data("Mask test")
        img = qr.make_image()
        _verify_qr_image(img, "Mask test")

        matrices = []
        for pattern in range(8):
            qr = QRCode(version=1, mask_pattern=pattern, border=0)
            qr.add_data("X")
            qr.make()
            matrices.append(qr.get_matrix())
        unique = set(str(m) for m in matrices)
        self.assertGreater(len(unique), 1)


# ===========================================================================
# 3. Constructor and property validation
# ===========================================================================
class TestValidation(unittest.TestCase):
    """Constructor and property validation."""

    def test_constructor_and_property_validation(self):
        """QRCode rejects invalid version, border, box_size, mask_pattern at construction and via setters."""
        from qrcode import QRCode

        with self.assertRaises(ValueError):
            QRCode(version=41)
        with self.assertRaises(ValueError):
            QRCode(version=0)

        with self.assertRaises(ValueError):
            QRCode(border=-1)

        with self.assertRaises(ValueError):
            QRCode(box_size=-1)
        with self.assertRaises(ValueError):
            QRCode(box_size=0)
        qr = QRCode()
        qr.box_size = -1
        qr.add_data("test")
        with self.assertRaises(ValueError):
            qr.make_image()

        with self.assertRaises(ValueError):
            QRCode(mask_pattern=8)

        qr2 = QRCode()
        with self.assertRaises(TypeError):
            qr2.mask_pattern = "string"
        with self.assertRaises(ValueError):
            qr2.mask_pattern = -1
        with self.assertRaises(ValueError):
            qr2.mask_pattern = 8


# ===========================================================================
# 4. SVG output
# ===========================================================================
class TestSVGOutput(unittest.TestCase):
    """SVG image factories produce valid SVG XML."""

    def test_svg_all_base_factories(self):
        """SvgImage, SvgPathImage, SvgFragmentImage produce valid parseable SVG with expected structure; to_string returns SVG bytes."""
        from qrcode import QRCode
        from qrcode.image import svg as svg_module

        qr = QRCode()
        qr.add_data("SVG test")

        img_svg = qr.make_image(image_factory=svg_module.SvgImage)
        buf = io.BytesIO()
        img_svg.save(buf)
        svg_bytes = buf.getvalue()
        self.assertIn(b'<?xml', svg_bytes)
        self.assertIn(b'width=', svg_bytes)
        root = ET.fromstring(svg_bytes)
        self.assertTrue(root.tag.endswith('svg'))

        img_path = qr.make_image(image_factory=svg_module.SvgPathImage)
        buf2 = io.BytesIO()
        img_path.save(buf2)
        path_content = buf2.getvalue().decode()
        self.assertIn('<path', path_content)
        self.assertIn(' d="', path_content)

        img_frag = qr.make_image(image_factory=svg_module.SvgFragmentImage)
        buf3 = io.BytesIO()
        img_frag.save(buf3)
        frag_bytes = buf3.getvalue()
        self.assertNotIn(b'<?xml', frag_bytes)
        frag_root = ET.fromstring(frag_bytes)
        self.assertTrue(frag_root.tag.endswith('svg'))

        stringified = img_frag.to_string()
        buf3.seek(0)
        saved_content = buf3.read()
        self.assertIn(saved_content, stringified)

    def test_svg_fill_variants_and_circle_drawer(self):
        """SvgFillImage and SvgPathFillImage add a white background; circle drawer produces valid SVG."""
        from qrcode import QRCode
        from qrcode.image import svg as svg_module

        qr = QRCode()
        qr.add_data("Fill test")

        img_fill = qr.make_image(image_factory=svg_module.SvgFillImage)
        buf = io.BytesIO()
        img_fill.save(buf)
        content = buf.getvalue().decode()
        self.assertIn('fill="white"', content)
        self.assertIn('<rect', content)

        img_path_fill = qr.make_image(image_factory=svg_module.SvgPathFillImage)
        buf2 = io.BytesIO()
        img_path_fill.save(buf2)
        content2 = buf2.getvalue().decode()
        self.assertIn('fill="white"', content2)
        self.assertIn('<path', content2)

        img_circle = qr.make_image(image_factory=svg_module.SvgPathImage, module_drawer="circle")
        buf3 = io.BytesIO()
        img_circle.save(buf3)
        content3 = buf3.getvalue().decode()
        root = ET.fromstring(content3.encode())
        self.assertTrue(root.tag.endswith('svg'))

    def test_svg_no_namespace_prefix_on_rect(self):
        """SVG rect elements use <rect> not <svg:rect> to avoid browser rendering issues."""
        from qrcode import QRCode
        from qrcode.image import svg as svg_module

        for factory in [svg_module.SvgFillImage, svg_module.SvgFragmentImage,
                        svg_module.SvgImage, svg_module.SvgPathFillImage]:
            qr = QRCode()
            qr.add_data("Namespace test")
            img = qr.make_image(image_factory=factory)
            buf = io.BytesIO()
            img.save(buf)
            content = buf.getvalue().decode()
            self.assertNotIn('<svg:rect', content,
                             f"{factory.__name__} should not use svg:rect namespace prefix")
            self.assertIn('<rect', content,
                          f"{factory.__name__} should contain rect elements")


# ===========================================================================
# 5. Image factory features
# ===========================================================================
class TestImageFactories(unittest.TestCase):
    """PilImage features: colors, save to file."""

    def test_pil_colors_and_file_output(self):
        """make_image with fill_color/back_color applies those colors to pixels; save to file produces decodable PNG."""
        from qrcode import QRCode, make

        qr = QRCode()
        qr.add_data("Colors")
        img = qr.make_image(fill_color="red", back_color="yellow")
        _verify_qr_image(img, "Colors")

        buf = io.BytesIO()
        img.save(buf)
        buf.seek(0)
        pil_img = Image.open(buf)
        pixels = pil_img.load()
        corner = pixels[0, 0]
        self.assertEqual(corner[:3], (255, 255, 0),
                         f"Corner pixel (quiet zone) should be yellow, got {corner}")

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            path = f.name
        try:
            img2 = make("File test")
            img2.save(path)
            self.assertGreater(os.path.getsize(path), 0)
            pil_read = Image.open(path)
            self.assertGreater(pil_read.size[0], 20)
            if HAS_PYZBAR:
                results = pyzbar_decode(pil_read)
                self.assertEqual(results[0].data.decode(), "File test")
        finally:
            os.unlink(path)


# ===========================================================================
# 5a. StyledPilImage — module drawers, color masks, embedded images
# ===========================================================================
class TestStyledPilImage(unittest.TestCase):
    """StyledPilImage: custom module drawers, color masks, and embedded images."""

    def test_styled_image_with_module_drawers(self):
        """StyledPilImage renders QR codes with different module drawer styles."""
        from qrcode import QRCode
        from qrcode.constants import ERROR_CORRECT_L
        from qrcode.image.styledpil import StyledPilImage
        from qrcode.image.styles.moduledrawers.pil import (
            CircleModuleDrawer,
            GappedSquareModuleDrawer,
            RoundedModuleDrawer,
            SquareModuleDrawer,
            VerticalBarsDrawer,
        )

        data = "Drawer test"
        drawers = [
            SquareModuleDrawer(),
            CircleModuleDrawer(),
            GappedSquareModuleDrawer(),
            RoundedModuleDrawer(),
            VerticalBarsDrawer(),
        ]

        images = []
        for drawer in drawers:
            qr = QRCode(error_correction=ERROR_CORRECT_L)
            qr.add_data(data)
            img = qr.make_image(image_factory=StyledPilImage, module_drawer=drawer)
            buf = io.BytesIO()
            img.save(buf)
            self.assertGreater(buf.tell(), 100)
            images.append(buf.getvalue())

            # Beyond non-empty + distinct: the styled output must still be a valid,
            # scannable QR encoding the input. SquareModuleDrawer (drawers[0]) renders the
            # default solid squares, so it is reliably decodable; a drawer that produced a
            # non-empty but corrupted/unscannable image would otherwise slip through. The
            # decorative drawers are exempt — they may legitimately subclass
            # SquareModuleDrawer, and their stylized output need not stay machine-scannable,
            # so select the plain square drawer positionally rather than with isinstance().
            if HAS_PYZBAR and drawer is drawers[0]:
                self.assertEqual(_decode_qr_image(img), data,
                                 "SquareModuleDrawer output should still decode to the input data")

        unique = set(images)
        self.assertGreater(len(unique), 1)

    def test_styled_image_with_color_masks(self):
        """StyledPilImage applies color masks producing distinctly colored QR codes."""
        from qrcode import QRCode
        from qrcode.constants import ERROR_CORRECT_L
        from qrcode.image.styledpil import StyledPilImage
        from qrcode.image.styles.colormasks import (
            HorizontalGradiantColorMask,
            RadialGradiantColorMask,
            SolidFillColorMask,
            VerticalGradiantColorMask,
        )

        data = "Color mask test"
        WHITE = (255, 255, 255)
        BLACK = (0, 0, 0)
        RED = (255, 0, 0)

        masks = [
            SolidFillColorMask(back_color=WHITE, front_color=RED),
            RadialGradiantColorMask(back_color=WHITE, center_color=BLACK, edge_color=RED),
            HorizontalGradiantColorMask(back_color=WHITE, left_color=RED, right_color=BLACK),
            VerticalGradiantColorMask(back_color=WHITE, top_color=RED, bottom_color=BLACK),
        ]

        images = []
        for mask in masks:
            qr = QRCode(error_correction=ERROR_CORRECT_L)
            qr.add_data(data)
            img = qr.make_image(image_factory=StyledPilImage, color_mask=mask)
            buf = io.BytesIO()
            img.save(buf)
            self.assertGreater(buf.tell(), 100)
            images.append(buf.getvalue())

            # SolidFillColorMask must paint the exact colors, not just "something
            # different": foreground (dark) modules become front_color (RED) and the
            # quiet zone stays back_color (WHITE). Check a pixel inside the always-dark
            # top-left finder pattern (module (0,0)) and a quiet-zone corner pixel. The
            # gradient masks are exempt — they may legitimately subclass
            # SolidFillColorMask to share plumbing, so select the solid-fill mask
            # positionally rather than with isinstance().
            if mask is masks[0]:
                buf.seek(0)
                pil_img = Image.open(buf).convert("RGB")
                pixels = pil_img.load()
                fg = (qr.border * qr.box_size + qr.box_size // 2)
                self.assertEqual(pixels[fg, fg], RED,
                                 f"Foreground module pixel should be red, got {pixels[fg, fg]}")
                self.assertEqual(pixels[0, 0], WHITE,
                                 f"Quiet-zone corner pixel should be white, got {pixels[0, 0]}")

        unique = set(images)
        self.assertGreater(len(unique), 1)

    def test_embedded_image_requires_high_error_correction(self):
        """Embedding an image in a QR code requires ERROR_CORRECT_H; lower levels raise ValueError."""
        from qrcode import QRCode
        from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q

        embedded = Image.new("RGB", (10, 10), color="red")

        for level in [ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q]:
            qr = QRCode(error_correction=level)
            qr.add_data("embed test")
            with self.assertRaises(ValueError):
                qr.make_image(embedded_image=embedded)

        qr = QRCode(error_correction=ERROR_CORRECT_H)
        qr.add_data("embed test")
        img = qr.make_image(embedded_image=embedded)
        buf = io.BytesIO()
        img.save(buf)
        self.assertGreater(buf.tell(), 100)

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            embedded.save(f, format='PNG')
            path = f.name
        try:
            qr2 = QRCode(error_correction=ERROR_CORRECT_H)
            qr2.add_data("path embed")
            img2 = qr2.make_image(embedded_image_path=path)
            buf2 = io.BytesIO()
            img2.save(buf2)
            self.assertGreater(buf2.tell(), 100)
        finally:
            os.unlink(path)


# ===========================================================================
# 6. CLI via subprocess
# ===========================================================================
class TestCLI(unittest.TestCase):
    """CLI generates QR codes via subprocess."""

    def test_cli_comprehensive(self):
        """CLI generates PNG with data and EC flag, SVG with factory flag and drawer, and rejects invalid factory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            png_path = os.path.join(tmpdir, "out.png")
            result = subprocess.run(
                [sys.executable, '-m', 'qrcode', '--error-correction', 'H',
                 '--output', png_path, 'CLI test data'],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, f"CLI PNG failed: {result.stderr}")
            pil_img = Image.open(png_path)
            self.assertGreater(pil_img.size[0], 20)
            if HAS_PYZBAR:
                results = pyzbar_decode(pil_img)
                self.assertEqual(results[0].data.decode(), "CLI test data")

            svg_path = os.path.join(tmpdir, "out.svg")
            result2 = subprocess.run(
                [sys.executable, '-m', 'qrcode', '--factory', 'svg',
                 '--factory-drawer', 'circle',
                 '--output', svg_path, 'SVG CLI'],
                capture_output=True, text=True,
            )
            self.assertEqual(result2.returncode, 0, f"CLI SVG failed: {result2.stderr}")
            with open(svg_path, 'rb') as f:
                svg_content = f.read()
            root = ET.fromstring(svg_content)
            self.assertTrue(root.tag.endswith('svg'))

            result3 = subprocess.run(
                [sys.executable, '-m', 'qrcode', '--factory', 'nonexistent',
                 'test data'],
                capture_output=True, text=True,
            )
            self.assertNotEqual(result3.returncode, 0)


# ===========================================================================
# 7. Data optimization and mode detection
# ===========================================================================
class TestDataOptimization(unittest.TestCase):
    """Data optimization splits input into optimal encoding mode chunks."""

    def test_mode_detection_numeric_alphanumeric_byte(self):
        """Data mode detection selects optimal encoding: numeric, alphanumeric, or 8-bit byte."""
        from qrcode import QRCode
        from qrcode.util import MODE_8BIT_BYTE, MODE_ALPHA_NUM, MODE_NUMBER

        qr = QRCode()
        qr.add_data("1234567890", optimize=0)
        qr.make()
        self.assertEqual(qr.data_list[0].mode, MODE_NUMBER)

        qr2 = QRCode()
        qr2.add_data("ABCDEFGHIJ1234567890", optimize=0)
        qr2.make()
        self.assertEqual(qr2.data_list[0].mode, MODE_ALPHA_NUM)

        qr3 = QRCode()
        qr3.add_data("abcdef", optimize=0)
        qr3.make()
        self.assertEqual(qr3.data_list[0].mode, MODE_8BIT_BYTE)

        qr4 = QRCode()
        qr4.add_data(",", optimize=0)
        qr4.make()
        self.assertEqual(qr4.data_list[0].mode, MODE_8BIT_BYTE)

        qr5 = QRCode()
        qr5.add_data("ABCDEFGHIJ1234567890\n", optimize=0)
        qr5.make()
        self.assertEqual(qr5.data_list[0].mode, MODE_8BIT_BYTE)

    def test_optimize_mode_splitting_detail(self):
        """Optimizer splits mixed-mode content into the exact optimal-mode chunk sequence and yields a smaller version."""
        from qrcode import QRCode
        from qrcode.util import MODE_8BIT_BYTE, MODE_ALPHA_NUM, MODE_NUMBER

        # Optimization must recognize the contiguous numeric run ("12345") and
        # alphanumeric run ("HELLO") as their own optimal-mode chunks, interleaved
        # with byte chunks for the lowercase/mixed segments.
        qr = QRCode()
        qr.add_data("A1abc12345def1HELLOa", optimize=4)
        qr.make()
        modes = [d.mode for d in qr.data_list]
        self.assertEqual(
            modes,
            [MODE_8BIT_BYTE, MODE_NUMBER, MODE_8BIT_BYTE, MODE_ALPHA_NUM, MODE_8BIT_BYTE],
        )

        qr2 = QRCode()
        text = "A1abc12345123451234512345def1HELLOHELLOHELLOHELLOa" * 5
        qr2.add_data(text)
        qr2.make()
        v_optimized = qr2.version

        qr3 = QRCode()
        qr3.add_data(text, optimize=0)
        qr3.make()
        v_unoptimized = qr3.version
        self.assertLess(v_optimized, v_unoptimized)


if __name__ == '__main__':
    unittest.main()
