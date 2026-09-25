"""
Integration tests for pdfminer.six — a PDF text extraction library.
Tests exercise the full parsing pipeline from PDF bytes to extracted text/layout.
"""

import base64
import io
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).parent.absolute() / "samples"


def sample_path(name):
    """Get absolute path to a test PDF sample."""
    return str(SAMPLES_DIR / name)


def _build_pdf_with_filter(content_bytes, filter_name, encoded_stream):
    """Build a minimal valid PDF with a specific stream filter."""
    objs = []
    objs.append(b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n")
    objs.append(
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    )
    objs.append(
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n"
    )
    stream_header = (
        f"4 0 obj\n<< /Length {len(encoded_stream)} "
        f"/Filter /{filter_name} >>\nstream\n"
    ).encode()
    objs.append(stream_header + encoded_stream + b"\nendstream\nendobj\n")
    objs.append(
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 "
        b"/BaseFont /Helvetica >>\nendobj\n"
    )

    body = b"%PDF-1.4\n"
    offsets = []
    for obj in objs:
        offsets.append(len(body))
        body += obj

    xref_offset = len(body)
    xref = b"xref\n0 6\n0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode()

    trailer = (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_offset).encode()
        + b"\n%%EOF\n"
    )
    return body + xref + trailer


def _runlength_encode(data):
    """Encode bytes using PDF RunLengthDecode format."""
    result = bytearray()
    i = 0
    while i < len(data):
        run_start = i
        while (
            i + 1 < len(data)
            and data[i] == data[i + 1]
            and i - run_start < 127
        ):
            i += 1
        run_len = i - run_start + 1
        if run_len >= 2:
            result.append(257 - run_len)
            result.append(data[run_start])
            i += 1
        else:
            lit_start = i
            while (
                i + 1 < len(data)
                and (i + 1 >= len(data) - 1 or data[i] != data[i + 1])
                and i - lit_start < 127
            ):
                i += 1
            lit_len = i - lit_start + 1
            result.append(lit_len - 1)
            result.extend(data[lit_start : lit_start + lit_len])
            i += 1
    result.append(128)
    return bytes(result)


def _make_reportlab_pdf(**kwargs):
    """Create a simple single-page PDF with reportlab. Returns BytesIO."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    encrypt = kwargs.get("encrypt")
    c = canvas.Canvas(buf, pagesize=letter, encrypt=encrypt)

    text = kwargs.get("text", "Test Content")
    c.drawString(100, 700, text)

    if kwargs.get("vertical_text"):
        c.saveState()
        c.translate(400, 700)
        c.rotate(90)
        c.drawString(0, 0, kwargs["vertical_text"])
        c.restoreState()

    if kwargs.get("draw_rect"):
        c.setStrokeColorRGB(1, 0, 0)
        c.setFillColorRGB(0, 0, 1)
        c.rect(100, 500, 200, 100, fill=1)

    if kwargs.get("draw_line"):
        c.line(50, 400, 300, 400)

    if kwargs.get("embed_image"):
        from PIL import Image
        from reportlab.lib.utils import ImageReader

        img = Image.new("RGB", (50, 50), color=(255, 0, 0))
        img_buf = io.BytesIO()
        img.save(img_buf, format="PNG")
        img_buf.seek(0)
        c.drawImage(ImageReader(img_buf), 100, 550, width=50, height=50)

    c.showPage()

    for extra_page in kwargs.get("extra_pages", []):
        c.drawString(100, 700, extra_page)
        c.showPage()

    c.save()
    buf.seek(0)
    return buf


# =============================================================================
# High-Level API: extract_text
# =============================================================================


class TestExtractText:
    """Tests for the extract_text high-level function."""

    def test_extract_text_from_simple_pdf(self):
        """Extract text from simple1.pdf containing 'Hello' and 'World'."""
        from pdfminer.high_level import extract_text

        text = extract_text(sample_path("simple1.pdf"))
        assert "Hello" in text
        assert "World" in text
        assert text.index("Hello") < text.index("World")

    def test_extract_text_multiline(self):
        """Extract text from simple4.pdf with multiple text lines in order."""
        from pdfminer.high_level import extract_text

        text = extract_text(sample_path("simple4.pdf"))
        assert "Text1" in text
        assert "Text2" in text
        assert "Text3" in text
        assert text.index("Text1") < text.index("Text2") < text.index("Text3")


# =============================================================================
# High-Level API: extract_pages (Layout Analysis)
# =============================================================================


class TestExtractPages:
    """Tests for extract_pages which returns layout objects."""

    def test_layout_object_hierarchy(self):
        """Layout objects form a hierarchy: LTPage > LTTextBox > LTTextLine > LTChar."""
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTPage, LTTextBox, LTTextLine, LTChar, LTAnno

        pages = list(extract_pages(sample_path("simple1.pdf")))
        assert len(pages) == 1
        page = pages[0]
        assert isinstance(page, LTPage)

        boxes = [el for el in page if isinstance(el, LTTextBox)]
        assert len(boxes) >= 1

        joined = "".join(b.get_text() for b in boxes)
        assert "Hello" in joined
        assert "World" in joined

        for box in boxes:
            x0, y0, x1, y1 = box.bbox
            assert x1 > x0
            assert y1 > y0

        # Find a box containing "Hello" and descend the hierarchy box > line > char.
        hello_box = next(b for b in boxes if "Hello" in b.get_text())
        lines = [ln for ln in hello_box if isinstance(ln, LTTextLine)]
        assert len(lines) >= 1

        hello_line = next(ln for ln in lines if "Hello" in ln.get_text())
        chars = [c for c in hello_line if isinstance(c, (LTChar, LTAnno))]
        assert len(chars) >= 5
        reconstructed = "".join(c.get_text() for c in chars)
        assert "Hello" in reconstructed

    def test_lt_char_has_font_info(self):
        """LTChar objects carry correct font name and size."""
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox, LTTextLine, LTChar

        pages = list(extract_pages(sample_path("simple1.pdf")))
        for element in pages[0]:
            if isinstance(element, LTTextBox):
                for line in element:
                    if isinstance(line, LTTextLine):
                        for char in line:
                            if isinstance(char, LTChar):
                                assert char.fontname == "Helvetica"
                                assert abs(char.size - 24.0) < 0.01
                                return
        pytest.fail("No LTChar found to test font info")


# =============================================================================
# extract_text_to_fp: Multiple Output Formats
# =============================================================================


class TestExtractTextToFp:
    """Tests for extract_text_to_fp with different output formats."""

    def test_xml_output(self):
        """extract_text_to_fp produces structured XML with per-character text elements."""
        from pdfminer.high_level import extract_text_to_fp

        outfp = io.BytesIO()
        with open(sample_path("simple1.pdf"), "rb") as f:
            extract_text_to_fp(f, outfp, output_type="xml")
        xml = outfp.getvalue().decode("utf-8")
        assert xml.startswith("<?xml")
        assert "<pages>" in xml
        assert '<page id="1"' in xml
        assert 'font="Helvetica"' in xml
        assert ">H</text>" in xml
        assert ">e</text>" in xml

    def test_html_output(self):
        """extract_text_to_fp produces HTML with styled text spans."""
        import re

        from pdfminer.high_level import extract_text_to_fp

        outfp = io.BytesIO()
        with open(sample_path("simple1.pdf"), "rb") as f:
            extract_text_to_fp(f, outfp, output_type="html")
        html = outfp.getvalue().decode("utf-8")
        assert "<html>" in html
        assert "<body>" in html
        assert "<span" in html
        # The extracted word must be recoverable from the HTML text content. The spec pins no
        # <span> grouping granularity for HTML (unlike per-character XML / word-level hOCR), so
        # assert on the concatenated span text with tags stripped rather than on "Hello" as a
        # raw contiguous substring of the marked-up output (which would depend on span chunking).
        span_text = re.sub(r"\s+", "", re.sub(r"<[^>]+>", "", html))
        assert "Hello" in span_text


# =============================================================================
# LAParams Configuration
# =============================================================================


class TestLAParams:
    """Tests for LAParams layout analysis configuration."""

    def test_laparams_char_margin_affects_grouping(self):
        """char_margin drives layout grouping: a small margin splits text into more
        boxes than a large margin, which merges adjacent text together."""
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTTextBox

        def num_boxes(char_margin):
            pages = list(
                extract_pages(
                    sample_path("simple1.pdf"),
                    laparams=LAParams(char_margin=char_margin),
                )
            )
            return len([el for el in pages[0] if isinstance(el, LTTextBox)])

        # A small char_margin keeps characters apart -> more boxes;
        # a large char_margin merges them -> fewer boxes.
        small_margin_boxes = num_boxes(0.5)
        large_margin_boxes = num_boxes(10.0)

        assert small_margin_boxes > large_margin_boxes
        # Both must still produce some boxes (extraction succeeded either way).
        assert large_margin_boxes >= 1

    def test_laparams_boxes_flow_none_position_ordering(self):
        """boxes_flow=None disables advection-based grouping and sorts purely by position.

        On simple4.pdf the three lines surface in top-to-bottom position order. Invalid
        boxes_flow values outside [-1, +1] still raise."""
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LAParams, LTTextContainer

        pages = list(
            extract_pages(
                sample_path("simple4.pdf"),
                laparams=LAParams(boxes_flow=None),
            )
        )
        assert len(pages) == 1
        containers = [el for el in pages[0] if isinstance(el, LTTextContainer)]
        assert len(containers) >= 1
        combined = "".join(c.get_text() for c in containers)
        assert "Text1" in combined
        assert "Text2" in combined
        assert "Text3" in combined
        assert combined.index("Text1") < combined.index("Text2") < combined.index("Text3")

        with pytest.raises((TypeError, ValueError)):
            LAParams(boxes_flow=2.0)
        with pytest.raises((TypeError, ValueError)):
            LAParams(boxes_flow=-2.0)


# =============================================================================
# PDF Document Structure
# =============================================================================


class TestPDFDocumentStructure:
    """Tests for lower-level PDF document access."""

    def test_pdf_page_iteration(self):
        """PDFPage.get_pages yields pages with correct mediabox dimensions."""
        from pdfminer.pdfpage import PDFPage

        with open(sample_path("simple1.pdf"), "rb") as f:
            pages = list(PDFPage.get_pages(f))

        assert len(pages) == 1
        page = pages[0]
        x0, y0, x1, y1 = page.mediabox
        assert (x0, y0) == (0, 0)
        assert x1 == pytest.approx(612.0, abs=1.0)
        assert y1 == pytest.approx(792.0, abs=1.0)
        assert page.rotate == 0

    def test_table_of_contents_extraction(self):
        """PDFDocument.get_outlines() extracts bookmark hierarchy from a PDF."""
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        from pdfminer.pdfdocument import PDFDocument
        from pdfminer.pdfparser import PDFParser

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=letter)
        c.bookmarkPage("ch1")
        c.addOutlineEntry("Chapter 1", "ch1", level=0)
        c.drawString(100, 700, "Chapter 1")
        c.showPage()
        c.bookmarkPage("ch2")
        c.addOutlineEntry("Chapter 2", "ch2", level=0)
        c.drawString(100, 700, "Chapter 2")
        c.showPage()
        c.bookmarkPage("sec2_1")
        c.addOutlineEntry("Section 2.1", "sec2_1", level=1)
        c.drawString(100, 700, "Section 2.1")
        c.showPage()
        c.save()

        buf.seek(0)
        parser = PDFParser(buf)
        doc = PDFDocument(parser)
        outlines = list(doc.get_outlines())

        assert len(outlines) == 3
        titles = [title for level, title, dest, a, se in outlines]
        assert titles == ["Chapter 1", "Chapter 2", "Section 2.1"]

        levels = [level for level, title, dest, a, se in outlines]
        assert levels[0] == levels[1]
        assert levels[2] > levels[0]


# =============================================================================
# Converter Pipeline
# =============================================================================


class TestConverterPipeline:
    """Tests for the converter pipeline components."""

    def test_page_aggregator_pipeline(self):
        """PDFPageAggregator yields an LTPage with the expected text content."""
        from pdfminer.pdfpage import PDFPage
        from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
        from pdfminer.converter import PDFPageAggregator
        from pdfminer.layout import LAParams, LTPage, LTTextBox

        rsrcmgr = PDFResourceManager()
        aggregator = PDFPageAggregator(rsrcmgr, laparams=LAParams())
        interpreter = PDFPageInterpreter(rsrcmgr, aggregator)

        with open(sample_path("simple1.pdf"), "rb") as f:
            for page in PDFPage.get_pages(f):
                interpreter.process_page(page)
                layout = aggregator.get_result()
                assert isinstance(layout, LTPage)
                text_boxes = [el for el in layout if isinstance(el, LTTextBox)]
                assert len(text_boxes) >= 1
                all_text = " ".join(b.get_text().strip() for b in text_boxes)
                assert "Hello" in all_text
                assert "World" in all_text


# =============================================================================
# Integration: Full Pipeline Workflows (sample PDFs)
# =============================================================================


class TestIntegrationWorkflows:
    """End-to-end integration tests combining multiple features."""

    def test_extract_and_analyze_layout(self):
        """Layout analysis places text boxes at their correct relative positions.

        simple1.pdf draws "Hello" and "World" with a wide horizontal gap on each row, so a
        correct layout analysis splits them into separate text boxes with "Hello" to the LEFT
        of "World". This verifies spatial positioning — a distinct contract from the content
        and hierarchy-shape checks already covered by the other layout tests."""
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTTextBox

        pages = list(extract_pages(sample_path("simple1.pdf")))
        page = pages[0]

        boxes = [el for el in page if isinstance(el, LTTextBox)]
        hello_boxes = [
            b for b in boxes if "Hello" in b.get_text() and "World" not in b.get_text()
        ]
        world_boxes = [
            b for b in boxes if "World" in b.get_text() and "Hello" not in b.get_text()
        ]
        assert len(hello_boxes) >= 1, "Expected a text box containing only 'Hello'"
        assert len(world_boxes) >= 1, "Expected a text box containing only 'World'"

        # Every "Hello" box sits to the left of every "World" box (lower x0).
        max_hello_x0 = max(b.x0 for b in hello_boxes)
        min_world_x0 = min(b.x0 for b in world_boxes)
        assert max_hello_x0 < min_world_x0

    def test_manual_pipeline_matches_highlevel(self):
        """Manual TextConverter pipeline yields the same multi-line text as extract_text.

        Both code paths must extract the same lines in the same order from this multi-line
        PDF. We compare on stripped text rather than byte-for-byte: whether extract_text
        returns the TextConverter stream verbatim (trailing form feed and all) or strips
        surrounding whitespace is an unspecified implementation detail, so we don't couple
        the two paths to identical leading/trailing whitespace."""
        from pdfminer.high_level import extract_text
        from pdfminer.pdfpage import PDFPage
        from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
        from pdfminer.converter import TextConverter
        from pdfminer.layout import LAParams

        text_hl = extract_text(sample_path("simple4.pdf"))

        rsrcmgr = PDFResourceManager()
        outfp = io.StringIO()
        converter = TextConverter(rsrcmgr, outfp, laparams=LAParams())
        interpreter = PDFPageInterpreter(rsrcmgr, converter)

        with open(sample_path("simple4.pdf"), "rb") as f:
            for page in PDFPage.get_pages(f):
                interpreter.process_page(page)
        converter.close()
        text_manual = outfp.getvalue()

        for line in ("Text1", "Text2", "Text3"):
            assert line in text_hl
            assert line in text_manual
        assert (
            text_hl.index("Text1") < text_hl.index("Text2") < text_hl.index("Text3")
        )
        assert (
            text_manual.index("Text1")
            < text_manual.index("Text2")
            < text_manual.index("Text3")
        )
        assert text_hl.strip() == text_manual.strip()


# =============================================================================
# Encryption: RC4 and AES decryption
# =============================================================================


class TestEncryption:
    """Tests for decrypting password-protected PDFs."""

    def test_rc4_128_encrypted_pdf(self):
        """Decrypt and extract text from an RC4-128 encrypted PDF."""
        from reportlab.lib.pdfencrypt import StandardEncryption

        from pdfminer.high_level import extract_text

        pdf = _make_reportlab_pdf(
            text="Secret RC4 Content",
            encrypt=StandardEncryption(
                "userpass", ownerPassword="ownerpass", strength=128
            ),
        )
        text = extract_text(pdf, password="userpass")
        assert "Secret RC4 Content" in text

    def test_rc4_40_encrypted_pdf(self):
        """Decrypt and extract text from an RC4-40 encrypted PDF."""
        from reportlab.lib.pdfencrypt import StandardEncryption

        from pdfminer.high_level import extract_text

        pdf = _make_reportlab_pdf(
            text="Legacy 40bit Encrypted",
            encrypt=StandardEncryption(
                "pass40", ownerPassword="owner40", strength=40
            ),
        )
        text = extract_text(pdf, password="pass40")
        assert "Legacy 40bit Encrypted" in text

    def test_aes_128_encrypted_pdf(self):
        """Decrypt and extract text from an AES-128 encrypted PDF."""
        from pdfminer.high_level import extract_text

        text = extract_text(sample_path("aes128.pdf"), password="userpass")
        assert "AES128 Secret Content" in text

    def test_aes_256_encrypted_pdf(self):
        """Decrypt and extract text from an AES-256 encrypted PDF."""
        from pdfminer.high_level import extract_text

        text = extract_text(sample_path("aes256.pdf"), password="userpass256")
        assert "AES256 Secret Content" in text


# =============================================================================
# Stream codec decoding: ASCII85, RunLength
# =============================================================================


class TestStreamCodecs:
    """Tests for PDF stream decompression filters via full extraction pipeline."""

    def test_ascii85_decode_stream(self):
        """Extract text from a PDF whose content stream uses ASCII85Decode."""
        from pdfminer.high_level import extract_text

        content = b"BT /F1 24 Tf 100 700 Td (ASCII85 Works) Tj ET"
        encoded = base64.a85encode(content, adobe=True)
        pdf = _build_pdf_with_filter(content, "ASCII85Decode", encoded)
        text = extract_text(io.BytesIO(pdf))
        assert "ASCII85 Works" in text

    def test_runlength_decode_stream(self):
        """Extract text from a PDF whose content stream uses RunLengthDecode."""
        from pdfminer.high_level import extract_text

        content = b"BT /F1 24 Tf 100 700 Td (RunLength Works) Tj ET"
        encoded = _runlength_encode(content)
        pdf = _build_pdf_with_filter(content, "RunLengthDecode", encoded)
        text = extract_text(io.BytesIO(pdf))
        assert "RunLength Works" in text

    def test_flatedecode_stream(self):
        """Extract text from a PDF whose content stream uses FlateDecode (zlib)."""
        import zlib

        from pdfminer.high_level import extract_text

        content = b"BT /F1 24 Tf 100 700 Td (Flate Compressed) Tj ET"
        encoded = zlib.compress(content)
        pdf = _build_pdf_with_filter(content, "FlateDecode", encoded)
        text = extract_text(io.BytesIO(pdf))
        assert "Flate Compressed" in text

    def test_asciihex_decode_stream(self):
        """Extract text from a PDF whose content stream uses ASCIIHexDecode."""
        from pdfminer.high_level import extract_text

        content = b"BT /F1 24 Tf 100 700 Td (HexDecoded) Tj ET"
        hex_encoded = content.hex().upper() + ">"
        pdf = _build_pdf_with_filter(
            content, "ASCIIHexDecode", hex_encoded.encode("ascii")
        )
        text = extract_text(io.BytesIO(pdf))
        assert "HexDecoded" in text

    def test_lzw_decode_stream(self):
        """Extract text from a PDF whose content stream uses LZWDecode."""
        from pdfminer.high_level import extract_text

        # Pre-computed LZW encoding of: BT /F1 24 Tf 100 700 Td (LZW Works) Tj ET
        lzw_encoded = (
            b"\x80\x10\x8a\x82\x01y\x18b \x19\r\x04\x05C0\x80b0"
            b"\x18\x08\x06\xf1\x08Y\x90@(&\x16\x8a\xe2\x02\xb9"
            b"\xbc\xe4k9\x8aaf\xa1\x01\x14\xa9\x01"
        )
        pdf = _build_pdf_with_filter(
            b"BT /F1 24 Tf 100 700 Td (LZW Works) Tj ET",
            "LZWDecode",
            lzw_encoded,
        )
        text = extract_text(io.BytesIO(pdf))
        assert "LZW Works" in text


# =============================================================================
# Image extraction
# =============================================================================


class TestImageExtraction:
    """Tests for extracting embedded images from PDFs."""

    def test_extract_embedded_image(self):
        """Extract an embedded 50x50 RGB image from a PDF using ImageWriter."""
        from PIL import Image

        from pdfminer.high_level import extract_text_to_fp

        pdf = _make_reportlab_pdf(text="Image Document", embed_image=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            outfp = io.StringIO()
            extract_text_to_fp(pdf, outfp, output_type="text", output_dir=tmpdir)

            text = outfp.getvalue()
            assert "Image Document" in text

            extracted = os.listdir(tmpdir)
            assert len(extracted) >= 1
            img_file = os.path.join(tmpdir, extracted[0])
            assert os.path.getsize(img_file) > 0

            # The decoded image must be the actual 50x50 RGB bitmap that was
            # embedded — a correct decode/write path reproduces those dimensions,
            # whereas a garbage or wrong-size file would not be a valid 50x50 image.
            decoded = Image.open(img_file)
            assert decoded.size == (50, 50)
            assert decoded.mode == "RGB"


# =============================================================================
# Multi-page and page selection
# =============================================================================


class TestMultiPage:
    """Tests for multi-page PDFs and page filtering."""

    def test_multipage_extraction(self):
        """Extract text from a 3-page PDF and verify per-page content."""
        from pdfminer.high_level import extract_text

        pdf = _make_reportlab_pdf(
            text="First Page",
            extra_pages=["Second Page", "Third Page"],
        )
        text = extract_text(pdf)
        assert "First Page" in text
        assert "Second Page" in text
        assert "Third Page" in text
        assert text.index("First") < text.index("Second") < text.index("Third")

    def test_page_number_filtering(self):
        """Extract only specific pages from a multi-page PDF."""
        from pdfminer.high_level import extract_text

        pdf = _make_reportlab_pdf(
            text="Page Alpha",
            extra_pages=["Page Beta", "Page Gamma"],
        )
        text = extract_text(pdf, page_numbers=[1])
        assert "Page Beta" in text
        assert "Page Alpha" not in text
        assert "Page Gamma" not in text

    def test_maxpages_limits_extraction(self):
        """maxpages parameter limits how many pages are processed."""
        from pdfminer.high_level import extract_text

        pdf = _make_reportlab_pdf(
            text="Intro Page",
            extra_pages=["Middle Page", "Final Page"],
        )
        text = extract_text(pdf, maxpages=1)
        assert "Intro Page" in text
        assert "Middle Page" not in text
        assert "Final Page" not in text


# =============================================================================
# CLI tools: pdf2txt.py and dumppdf.py
# =============================================================================


class TestCLITools:
    """Tests for the pdf2txt.py and dumppdf.py command-line tools."""

    def _write_test_pdf(self, text="CLI Test Content", extra_pages=None):
        """Write a reportlab-generated PDF to a temp file and return the path."""
        pdf = _make_reportlab_pdf(text=text, extra_pages=extra_pages or [])
        f = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.write(pdf.read())
        f.close()
        return f.name

    @staticmethod
    def _find_script(name):
        """Find a CLI script by checking common locations."""
        import shutil
        import sys

        on_path = shutil.which(name)
        if on_path:
            return [on_path]
        candidates = [
            os.path.join("/app/tools", name),
            os.path.join("/app", name),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return [sys.executable, c]
        return [sys.executable, "-m", name.replace(".py", "")]

    def test_pdf2txt_text_extraction(self):
        """pdf2txt.py extracts plain text from a PDF via command line."""
        pdf_path = self._write_test_pdf("Extracted via CLI")
        try:
            cmd = self._find_script("pdf2txt.py") + [pdf_path]
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd="/app",
            )
            assert result.returncode == 0
            assert "Extracted via CLI" in result.stdout
        finally:
            os.unlink(pdf_path)

    def test_pdf2txt_xml_output(self):
        """pdf2txt.py -t xml routes the CLI to XML output on stdout.

        Distinct from the API-level test_xml_output: this covers the CLI's own -t
        format-selection branch and its binary-stream-to-stdout path. Assertions stay at
        routing level (declaration, root element, one per-character element) — the full XML
        shape (page id, font, bbox) is already rewarded by test_xml_output."""
        pdf_path = self._write_test_pdf("XML Output Test")
        try:
            cmd = self._find_script("pdf2txt.py") + ["-t", "xml", pdf_path]
            # Deliberately no text=True: xml output is written as a binary stream.
            result = subprocess.run(
                cmd, capture_output=True, cwd="/app",
            )
            assert result.returncode == 0
            xml = result.stdout.decode("utf-8")
            assert "<?xml" in xml
            assert "<pages>" in xml
            assert ">X</text>" in xml
        finally:
            os.unlink(pdf_path)

    def test_dumppdf_structure(self):
        """dumppdf.py -a dumps all PDF objects as XML structure."""
        pdf_path = self._write_test_pdf("Dump Structure")
        try:
            cmd = self._find_script("dumppdf.py") + ["-a", pdf_path]
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd="/app",
            )
            assert result.returncode == 0
            assert "<pdf" in result.stdout
            assert "<object" in result.stdout
            assert "<trailer>" in result.stdout
        finally:
            os.unlink(pdf_path)


# =============================================================================
# Converter features: hOCR, rotation, graphics paths
# =============================================================================


class TestConverterFeatures:
    """Tests for advanced converter output features."""

    def test_hocr_output_format(self):
        """extract_text_to_fp with output_type='hocr' produces valid hOCR HTML."""
        from pdfminer.high_level import extract_text_to_fp

        pdf = _make_reportlab_pdf(text="hOCR Test")
        outfp = io.BytesIO()
        extract_text_to_fp(pdf, outfp, output_type="hocr")
        hocr = outfp.getvalue().decode("utf-8")
        assert "ocr_page" in hocr
        assert "ocrx_word" in hocr
        assert "bbox" in hocr
        assert "pdfminer" in hocr.lower()
        # Beyond the structural scaffold, the recognized text must actually be emitted: the
        # word "hOCR" appears as the content of an ocrx_word span (not an empty skeleton).
        assert ">hOCR</span>" in hocr

    def test_rotation_handling(self):
        """Text extraction works correctly with page rotation applied."""
        import re

        from pdfminer.high_level import extract_text_to_fp

        pdf = _make_reportlab_pdf(text="Rotated Content")
        outfp = io.StringIO()
        extract_text_to_fp(pdf, outfp, output_type="text", rotation=90)
        text = outfp.getvalue()
        # The rotated run's glyphs must all be extracted in reading order. The spec pins reading
        # order for rotated (vertical) runs but does not determine how a 90-rotated run is grouped
        # into lines under the default laparams (detect_vertical=False) — it may coalesce into one
        # line or split one char per line. So assert on the whitespace-stripped text (mirroring the
        # HTML test above) rather than on "Rotated Content" as a raw contiguous substring.
        assert "RotatedContent" in re.sub(r"\s+", "", text)

    def test_graphics_in_xml_output(self):
        """XML output includes rect and line elements from graphics operations."""
        from pdfminer.high_level import extract_text_to_fp

        pdf = _make_reportlab_pdf(
            text="Graphics Test", draw_rect=True, draw_line=True
        )
        outfp = io.BytesIO()
        extract_text_to_fp(pdf, outfp, output_type="xml")
        xml = outfp.getvalue().decode("utf-8")
        assert "<rect" in xml
        assert "<line" in xml
        assert "Graphics Test" in xml or ">G</text>" in xml

    def test_detect_vertical_text(self):
        """detect_vertical=True groups rotated text into LTTextBoxVertical."""
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import (
            LAParams,
            LTTextBox,
            LTTextBoxHorizontal,
            LTTextBoxVertical,
        )

        pdf = _make_reportlab_pdf(
            text="Horizontal Text", vertical_text="Vertical Text"
        )

        pages = list(extract_pages(pdf, laparams=LAParams(detect_vertical=True)))
        assert len(pages) == 1
        boxes = [el for el in pages[0] if isinstance(el, LTTextBox)]

        vertical_boxes = [b for b in boxes if isinstance(b, LTTextBoxVertical)]
        horizontal_boxes = [b for b in boxes if isinstance(b, LTTextBoxHorizontal)]

        assert len(vertical_boxes) >= 1, "Expected at least one LTTextBoxVertical"
        assert len(horizontal_boxes) >= 1, "Expected at least one LTTextBoxHorizontal"

        vertical_text = " ".join(b.get_text().strip() for b in vertical_boxes)
        assert "Vertical" in vertical_text

        horizontal_text = " ".join(b.get_text().strip() for b in horizontal_boxes)
        assert "Horizontal" in horizontal_text
