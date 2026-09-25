# XlsxWriter -- Excel .xlsx File Creation Library

## Overview

Implement **XlsxWriter**, a Python library for creating Excel `.xlsx` files (write-only). An `.xlsx` file is an OPC archive (ZIP containing XML parts): `[Content_Types].xml`, workbook/worksheet XML under `xl/`, shared string table, styles, theme, tables, charts, drawings, document properties, and relationship files.

### Dependencies

- Pure Python, standard library only — the library requires no third-party runtime packages
  (use `zipfile`, `xml`, `datetime`, etc. from the standard library).
- **The environment is fully offline. All dependencies are already installed — do not install
  anything (no `pip install`, no network access).** The project is installed for you by a
  `setup.sh` that runs offline (`pip install -e . --no-build-isolation`).

---

## 1. Package Entry Point

`import xlsxwriter` exports `Workbook` and `__version__`.

### Usage

The library is driven by creating a `Workbook`, adding worksheets, writing cells, and closing the
workbook (which serializes the `.xlsx` file). `close()` may be called explicitly or via a context
manager:

```python
import xlsxwriter

wb = xlsxwriter.Workbook("out.xlsx")
ws = wb.add_worksheet()
ws.write(0, 0, "Hello")
ws.write(1, 0, 123)
wb.close()

# Context-manager form (closes automatically on exit):
with xlsxwriter.Workbook("out.xlsx") as wb:
    ws = wb.add_worksheet()
    ws.write(0, 0, "Hello")
```

---

## 2. Workbook

`Workbook(filename, options=None)` -- `filename` is a path or file-like object (e.g., `io.BytesIO()`). Supports context manager. Options: `strings_to_numbers`, `default_date_format`, `in_memory`. When `default_date_format` is set on the Workbook and a datetime is written without an explicit format, the default date format is automatically applied.

Key methods: `add_worksheet(name=None)`, `add_format(properties=None)`, `add_chart(options)`, `close()`, `define_name(name, formula)`, `set_properties(props_dict)`.

- `define_name` -- global (`"MyRange"`) or sheet-local (`"Sheet1!LocalName"`). Formula like `"=Sheet1!$A$1:$A$10"`. The formula passed to `define_name()` may include a leading `=` which is stripped for internal XML storage.
- `set_properties` -- metadata dict: `title`, `subject`, `author`, `manager`, `company`, `category`, `keywords`, `comments`, `status`.
- Worksheet names default to `"Sheet1"`, `"Sheet2"`, etc. Invalid names raise `InvalidWorksheetName`, duplicates raise `DuplicateWorksheetName`.

---

## 3. Format

Created via `add_format(properties)`. Properties set via constructor dict or `set_*()` methods. Includes: font properties, `num_format`, alignment (`align`, `valign`), `text_wrap`, `border`, `bg_color` (requires `pattern=1`), `locked`, `hidden`.

- Font properties include `bold`, `italic`, `font_name`, `font_size`, `font_color`, and `underline`. `underline` is a style index; `underline: True` selects single underline.
- Alignment uses two separate properties, `align` (horizontal) and `valign` (vertical), each taking a token string that is mapped onto its OOXML alignment value:
  - `align` accepts `"left"`, `"center"` (alias `"centre"`), `"right"`, `"fill"`, `"justify"`, `"center_across"`, `"distributed"`.
  - `valign` accepts `"top"`, `"vcenter"` (alias `"vcentre"`), `"bottom"` (the default), `"vjustify"`, `"vdistributed"`.
- `border` (and the per-side `top`/`bottom`/`left`/`right` border properties) accept an integer style index, e.g. `0` = none, `1` = thin, `2` = medium, `5` = thick (`1` is the thinnest continuous border).
- `bg_color` together with `pattern=1` is a solid fill: the cell must end up painted in the requested color.

---

## 4. Worksheet

### Writing Data

`write(row, col, data, format)` dispatches by type. `write()` accepts both `(row, col, data)` and `('A1', data)` notation. Explicit methods: `write_string`, `write_number`, `write_formula(row, col, formula, format, value)`, `write_boolean`, `write_datetime`, `write_blank`, `write_url(row, col, url, format, string, tip)`, `write_row`, `write_column`.

- Like `write()`, the explicit single-cell methods (`write_string`, `write_number`, `write_formula`, `write_boolean`, `write_datetime`, `write_blank`, `write_url`) also accept A1 single-cell notation in place of the leading `(row, col)` integers, e.g. `write_formula('C1', '=A1+B1')`.

- `write_url` supports `http`/`https`/`mailto`/`ftp` external URLs and same-document `internal:` links. An `internal:` URL of the form `"internal:Sheet!Cell"` (e.g. `"internal:Target!A1"`) is written as an in-document location link (the `<hyperlink>` element carries `location="Sheet!Cell"` with no external relationship target), not as an external URL.

**Rich strings**: `write_rich_string(row, col, *args)` -- alternating Format objects and string fragments.

**Array formulas**: `write_array_formula(first_row, first_col, last_row, last_col, formula, format, value)` -- stored as `t="array"` in XML, with the `ref` attribute spanning the full output range (a 1x1 array collapses to that single cell). The four `(first_row, first_col, last_row, last_col)` integers may instead be given as a single A1 range string, e.g. `write_array_formula('G2:G6', '=E2:E6*F2:F6')`.

**Dynamic array formulas**: `write_dynamic_array_formula(first_row, first_col, last_row, last_col, formula, format, value)` -- like `write_array_formula` but for formulas that spill across a multi-cell range. Also stored as `t="array"` in XML, with the `ref` attribute spanning the full output range. Likewise accepts a single A1 range string in place of the four integers, e.g. `write_dynamic_array_formula('H1:H4', '=G1:G4*2')`.

**Comments**: `write_comment(cell, text, options)` -- options include `author`.

### Row/Column Properties

`set_row(row, height, format, options)`, `set_column(first_col, last_col, width, format, options)` -- `set_column` also accepts string range notation like `set_column('A:A', 20)` or `set_column('B:E', 15)`. Options: `hidden`, `level` (outline grouping), `collapsed` (collapse an outline group).

### Tables, Merging, Validation, Conditional Formatting, Autofilter

- `merge_range` -- raises `OverlappingRange` on collision.
- `add_table(range, options)` -- options: `data`, `columns` (with `header`, `total_string`, `total_function`), `name`, `total_row`. When `add_table()` is called with `columns` containing `header` values, those headers are written as cell values in the header row. When `total_row` is enabled, the total row is likewise materialized as worksheet cell values in the last row of the table range: a column's `total_string` is written verbatim as that cell's string value, and a column's `total_function` (e.g. `"sum"`) is written as the corresponding `SUBTOTAL` formula cell. Duplicate names raise `DuplicateTableName`.
- `data_validation(range, options)` -- `validate` types: `integer`, `decimal`, `list`, `length`, `custom`, `date`. Supports `criteria`, `value`/`minimum`/`maximum`, `source`, `input_title`, `input_message`, `error_title`, `error_message`, `error_type` (`"stop"` default, `"warning"`, `"information"`). The `criteria` operator (a comparison token such as `"<="` or `"between"`) is serialized in its OOXML form; `"between"` uses `formula1`/`formula2` for the two bounds. For `date` validation, bounds supplied as `"YYYY-MM-DD"` date strings are stored verbatim as the validation formulas (they are not pre-converted to Excel date serial numbers).
- `conditional_format(range, options)` -- types: `cell` (with `criteria`, `value`, `format`), `duplicate` (with `format`), `formula` (with `criteria` containing a formula string like `"=$A1>AVERAGE($A:$A)"`, `format`), `2_color_scale` (`min_color`, `max_color`), `3_color_scale` (`min_color`, `mid_color`, `max_color`), `data_bar` (`bar_color` — written as the `<dataBar>` rule's color, the requested RGB in the color element's `rgb` attribute), `icon_set` (`icon_style`). `icon_style` accepts Excel's named icon sets (e.g. `"3_traffic_lights"`, `"3_arrows"`, `"4_arrows"`, `"5_ratings"`); the chosen style is serialized as the `iconSet` attribute on the `<iconSet>` rule using Excel's CamelCase name, except the default `"3_traffic_lights"` which is emitted with no `iconSet` attribute. Any rule also accepts `stop_if_true` (bool); when true the rule is serialized with the `stopIfTrue` attribute so Excel stops evaluating later rules once it matches. Multiple rules applied to the same range accumulate and are assigned distinct evaluation priorities in the order they are added (the first-added rule has the highest priority).
- `autofilter(range)`.

### Sparklines

`add_sparkline(cell, options)` -- adds a sparkline to a cell. Options: `range` (data range as sheet-qualified string like `"Sheet1!A1:E1"`), `type` (`"line"` default, `"column"`, `"win_loss"`). Sparklines are stored as `x14:sparklineGroup` elements in the worksheet XML extension list. `win_loss` type is serialized as `type="stacked"` in the XML.

### Images and Charts

- `insert_image(cell, filename, options)` -- embeds an image (stored in `xl/media/`, linked via a drawing).
- `insert_chart(cell, chart, options)` -- embeds a chart object.

### Page Setup

`freeze_panes(row, col)` (also accepts A1 notation), `set_header(string)`/`set_footer(string)` (codes: `&L`, `&C`, `&R`, `&P`, `&N`), `set_landscape()`/`set_portrait()`, `set_paper(index)`, `set_margins(left, right, top, bottom)`, `set_print_scale(scale)`, `print_area(range)`, `repeat_rows(first_row, last_row=None)` — `last_row` is optional and defaults to `first_row`, so `repeat_rows(0)` repeats a single row (row 1).

### Protection

`protect(password, options)` -- options: `format_cells`, `insert_rows`, `sort`, etc. Cell-level: Format `locked` and `hidden`.

---

## 5. Chart

Created via `add_chart({"type": "<type>"})`. Types: `area`, `bar`, `column`, `doughnut`, `line`, `pie`, `radar`, `scatter`, `stock`.

- `add_series(options)` -- `name`, `categories`, `values` (formula refs). Series formatting: `fill` (`color`), `line` (`color`, `width`). Use `y2_axis: True` to plot a series on the secondary Y-axis. `data_labels` option: dict with `value` (bool), `num_format` (string), `position` (e.g. `"outside_end"`). Data labels are stored as `<c:dLbls>` elements in chart XML with `<c:showVal>` and optional `<c:numFmt>`.
- `set_title(options)`, `set_x_axis(options)`, `set_y_axis(options)`, `set_y2_axis(options)` -- `name` for labels. Axis options also support `num_format` for custom number formatting on the axis, `min` and `max` for axis scaling bounds, and `log_base` (e.g., `10`) for logarithmic scale.
  - Options set on an axis apply to that axis: `num_format`, `min`, `max` and `log_base` are serialized as that axis's number format and scaling bounds in the emitted chart XML.
- `set_legend(options)` -- `position`. `set_size(options)` -- `width`, `height` in pixels.

When a series uses `y2_axis`, the chart XML contains a second plot group (e.g., a second `<c:barChart>`) with its own `<c:catAx>` and `<c:valAx>`, resulting in 2 category axes and 2 value axes total.

---

## 6. Utility Functions (`xlsxwriter.utility`)

- `xl_rowcol_to_cell(row, col, row_abs, col_abs)` -- `(0,0)` -> `"A1"`, `$` for absolute.
- `xl_cell_to_rowcol(cell)` -- `"AA1"` -> `(0, 26)`. Ignores `$`.
- `xl_col_to_name(col, col_abs)` -- `0` -> `"A"`, `26` -> `"AA"`.
- `xl_range(r1, c1, r2, c2)` -- same cell returns just `"A1"`.
- `xl_range_abs(r1, c1, r2, c2)` -- `"$A$1:$C$4"`.
- `xl_cell_to_rowcol_abs(cell)` -- returns `(row, col, row_abs, col_abs)`.

---

## 7. Exceptions (`xlsxwriter.exceptions`)

```
XlsxWriterException
+-- XlsxInputError
|   +-- InvalidWorksheetName
|   +-- DuplicateWorksheetName
|   +-- OverlappingRange
|   +-- EmptyChartSeries
|   +-- DuplicateTableName
+-- XlsxFileError
    +-- FileCreateError
```

---

## 8. setup.sh

```bash
pip install -e . --no-build-isolation
```
