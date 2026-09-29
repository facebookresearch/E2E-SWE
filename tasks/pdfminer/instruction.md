# pdfminer.six — PDF Text Extraction Library

Build **pdfminer.six**, a Python library for extracting text and layout information from PDF documents. The library parses PDF files through a multi-stage pipeline: PDF parsing → page extraction → content interpretation → layout analysis → text/HTML/XML output.

**Version**: Use a development version string (e.g., `"0.0"` is fine).

**Dependencies**: The environment is **offline** and every dependency is **already installed** — do **not** install anything. The runtime dependencies `charset-normalizer` and `cryptography` are present, and `Pillow` (the `image` extra, used for embedded-image extraction) is present too. The project itself is installed for you by a `setup.sh` that runs **offline** (an editable install with no build isolation), so you do not need to run `pip install`.

The package name is `pdfminer` (importable as `import pdfminer`, `from pdfminer.high_level import extract_text`, etc.).

**Encryption**: pdfminer supports reading password-protected PDFs encrypted with RC4 (40-bit and 128-bit) and AES (128-bit and 256-bit). Pass the user password via the `password` parameter on extraction functions. The `cryptography` library is used for decryption.

**Stream decompression**: PDF content streams may use compression filters. pdfminer must support decoding: `FlateDecode` (zlib), `ASCII85Decode`, `ASCIIHexDecode`, `LZWDecode`, and `RunLengthDecode`. The `ASCII85Decode` implementation must accept data framed with Adobe's optional `<~ ... ~>` start/end delimiters (i.e. it must decode the output of `base64.a85encode(..., adobe=True)`), not only the bare `~>` EOD marker.

---

## High-Level API (`pdfminer.high_level`)

The primary user-facing API for text extraction.

### `extract_text(pdf_file, password="", page_numbers=None, maxpages=0, caching=True, codec="utf-8", laparams=None)`

Extracts all text from a PDF as a single string. `pdf_file` can be a file path (str/Path) or an open binary file object. `page_numbers` is zero-indexed. `maxpages=0` means no limit. `laparams` defaults to `LAParams()` if None.

### `extract_pages(pdf_file, password="", page_numbers=None, maxpages=0, caching=True, laparams=None)`

Yields `LTPage` layout objects (one per page). Each `LTPage` is iterable, containing layout elements like `LTTextBox`, `LTFigure`, `LTImage`, `LTRect`, `LTLine`, `LTCurve`.

### `extract_text_to_fp(inf, outfp, output_type="text", codec="utf-8", laparams=None, maxpages=0, page_numbers=None, password="", scale=1.0, rotation=0, layoutmode="normal", output_dir=None, strip_control=False, debug=False, disable_caching=False)`

Writes extracted content to `outfp`. `output_type` selects the output format:
- `"text"` — plain text (to a text-mode stream like StringIO)
- `"xml"` — XML with per-character `<text>` elements inside `<page>` inside `<pages>`. The output begins with an XML declaration line — `<?xml version="1.0" encoding="utf-8" ?>` for the default `codec="utf-8"` (the declaration's `encoding` reflects the output `codec`) — followed by the `<pages>` root element. Each `<page>` carries a 1-based `id` attribute and a `bbox` attribute; each per-character `<text>` element carries a `font` attribute (the font name, e.g. `Helvetica`), a `bbox` attribute, and a `size` attribute, with the single character as the element's text content. Graphics paths appear as `<rect>` and `<line>` elements. Output goes to a binary stream.
- `"html"` — HTML with positioned `<span>` elements. Output goes to a binary stream.
- `"hocr"` — hOCR HTML with `<div class="ocr_page">` (with `title="bbox ..."`) and `<span class="ocrx_word">` elements. Includes a `<meta>` tag identifying `pdfminer.six` as the OCR system. Output goes to a binary stream.
- `"tag"` — tagged content output.

Raises `PDFValueError` for an unrecognized `output_type`.

When `output_dir` is provided, embedded images are extracted from the PDF and saved as files in that directory during text extraction (images nested inside a form XObject / `LTFigure` are extracted too). Each image is written as a self-describing, decodable image file — not a raw byte dump of the stream — so a standard image reader (e.g. `PIL.Image.open`) can open it and recover the source image's pixel dimensions and color mode. Images stored with a native encoded format (e.g. `DCTDecode` JPEG) keep that encoding; raw/uncompressed raster images are wrapped in a valid image container.

The `rotation` parameter rotates pages by the given number of degrees before processing.

---

## Layout Objects (`pdfminer.layout`)

### `LAParams`

Controls layout analysis behavior.

```python
LAParams(line_overlap=0.5, char_margin=2.0, line_margin=0.5, word_margin=0.1,
         boxes_flow=0.5, detect_vertical=False, all_texts=False)
```

`char_margin` is the maximum horizontal gap between two adjacent characters for them to be grouped into the same text line/box. The gap is measured **relative to the characters' widths** (a wider character tolerates a larger absolute gap), not as an absolute coordinate distance. Consequently a **larger** `char_margin` merges more adjacent characters together, yielding **fewer, larger** text boxes, while a **smaller** `char_margin` keeps characters apart, yielding **more, smaller** text boxes.

`boxes_flow` must be None (disables grouping, position-based sorting) or a float in [-1, +1]. Invalid values raise errors.

`detect_vertical` controls whether vertically-oriented text is recognized during layout analysis. The orientation of a text run is determined from how its glyphs are actually rendered on the page — their effective advance direction under the text/CTM transformation — **not** only from the font's writing mode. So text rotated by the page's drawing matrix (e.g. a run drawn at a 90° rotation) counts as vertical. When `detect_vertical=False` (default), every text box is an `LTTextBoxHorizontal`. When `detect_vertical=True`, runs whose rendered orientation is vertical are grouped into `LTTextBoxVertical` / `LTTextLineVertical`, while horizontal runs remain `LTTextBoxHorizontal` / `LTTextLineHorizontal`.

Reading order is preserved for vertical text just as it is for horizontal text: calling `get_text()` on an `LTTextBoxVertical` / `LTTextLineVertical` returns that run's characters in their reading (drawing) sequence — the same forward order in which the run's glyphs were emitted — so a rotated run such as `"Vertical Text"` extracts as `"Vertical Text"`, never reversed, whichever way the rotation advances the glyphs across the page.

### Layout Object Hierarchy

The layout analysis pipeline groups characters into lines and lines into text boxes, producing a tree of layout objects:

- **`LTPage`** — top-level page container. Has `pageid`, `bbox` (x0, y0, x1, y1). Iterable over child elements.
- **`LTTextBox`** — group of text lines. Has `get_text()`, `bbox`. Subtypes: `LTTextBoxHorizontal`, `LTTextBoxVertical`.
- **`LTTextLine`** — single line of text. Has `get_text()`, `bbox`. Subtypes: `LTTextLineHorizontal`, `LTTextLineVertical`.
- **`LTChar`** — single character with position. Has `get_text()`, `fontname` (str), `size` (float), `bbox`.
- **`LTAnno`** — virtual character (e.g., inferred spaces). Has `get_text()`.
- **`LTFigure`** — embedded figure/form.
- **`LTImage`** — embedded image.
- **`LTCurve`** — path element. Has `linewidth`, `bbox`.
- **`LTLine`** — line segment (subclass of LTCurve).
- **`LTRect`** — rectangle (subclass of LTCurve).

All positioned layout objects have `bbox` as a tuple `(x0, y0, x1, y1)` and derived properties `x0`, `y0`, `x1`, `y1`, `width`, `height`.

Both `LTChar` and `LTAnno` implement the `LTText` interface (`get_text() -> str`). `LTTextContainer` (parent of `LTTextBox` and `LTTextLine`) concatenates child text via `get_text()`.

---

## PDF Document Structure

### `pdfminer.pdfpage.PDFPage`

Represents a single PDF page.

```python
PDFPage.get_pages(fp, pagenos=None, maxpages=0, password="", caching=True, check_extractable=False)
```

Class method yielding `PDFPage` objects from a binary file. `pagenos` is zero-indexed. Each page has attributes: `mediabox` (4-element rect), `cropbox`, `rotate` (int, degrees), `resources`, `contents`.

### `pdfminer.pdfparser.PDFParser` and `pdfminer.pdfdocument.PDFDocument`

Lower-level access to PDF structure. Create a `PDFParser(fp)` from a binary file, then pass it to `PDFDocument(parser, password="")` to build the document. The document provides `info` (metadata) and `catalog` (document catalog dict).

`get_outlines()` returns an iterator of outline (bookmark/table of contents) entries. Each entry is a tuple of `(level, title, dest, a, se)` where `level` is the nesting depth (1-based), `title` is the bookmark text string, and the remaining fields carry destination and action information.

### Recovery from a missing or broken cross-reference table

A well-formed PDF locates its objects through a cross-reference table referenced by a `startxref` offset at the end of the file. Some real-world PDFs are malformed and lack a usable cross-reference table or `startxref` offset entirely (for example, a file that ends with only a bare `trailer << ... >>` dictionary and `%%EOF`, with no `xref` keyword and no `startxref`). The library must still read such files rather than yielding nothing: when the cross-reference table is missing or unusable, `extract_text`, `extract_pages`, and `PDFPage.get_pages` must recover and return the document's pages exactly as they would for a PDF with an intact cross-reference table.

---

## Converter Pipeline

For manual control over the extraction process, you can build a pipeline from individual components. The pattern is:

1. Create a `PDFResourceManager` (from `pdfminer.pdfinterp`) to manage fonts and resources.
2. Create a converter device — either `TextConverter` (writes plain text), `PDFPageAggregator` (collects layout objects, retrieve via `get_result()` which returns an `LTPage`), `HTMLConverter`, or `XMLConverter`. All live in `pdfminer.converter`.
3. Create a `PDFPageInterpreter` (from `pdfminer.pdfinterp`) with the resource manager and device.
4. Iterate over pages from `PDFPage.get_pages()` and call `interpreter.process_page(page)` for each.

All converters accept `laparams` (an `LAParams` instance or None) to control layout analysis. Converters have a `close()` method that should be called when done to finalize output.

---

## CLI Tools (`tools/`)

### `tools/pdf2txt.py`

Command-line tool for extracting text from PDFs. Supports multiple output formats.

```bash
pdf2txt.py [options] file.pdf
```

Key options:
- `-t {text,html,xml,tag}` — output format (default: `text`)
- `-o FILE` — output file (default: stdout)
- `-p PAGENOS` / `--page-numbers N [N ...]` — page selection
- `-m MAXPAGES` — maximum pages to parse
- `-P PASSWORD` — decryption password
- `-R ROTATION` — rotation in degrees
- `-O DIR` — output directory for extracted images
- `-n` — disable layout analysis
- `-V` — detect vertical text
- `-M`, `-W`, `-L`, `-F` — layout analysis parameters (char_margin, word_margin, line_margin, boxes_flow)

The script is installed as `pdf2txt.py` on `PATH` via `pyproject.toml` script-files.

### `tools/dumppdf.py`

Command-line tool for dumping PDF internal structure as XML.

```bash
dumppdf.py [options] file.pdf
```

Key options:
- `-a` / `--all` — dump all objects
- `-T` / `--extract-toc` — extract table of contents
- `-E DIR` / `--extract-embedded DIR` — extract embedded files
- `-p PAGENOS` / `--page-numbers N [N ...]` — page selection
- `-P PASSWORD` — decryption password

Output includes `<pdf>`, `<object>`, `<trailer>` XML elements describing the PDF structure.

---

## Exceptions (`pdfminer.pdfexceptions`)

- `PDFValueError` — invalid parameter values

---

## setup.sh

The environment is offline and all dependencies are already installed, so `setup.sh` only needs to install your package itself (an editable install with no build isolation):

```bash
pip install -e . --no-build-isolation
```
