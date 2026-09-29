"""
Tests for XlsxWriter -- Excel .xlsx file creation library.

Tests exercise complex integration scenarios: multi-sheet workbooks with
formatting, formulas, defined names, tables, data validation, conditional
formatting, page setup, protection, freeze panes, headers/footers, outline
grouping, rich strings, hyperlinks, array formulas, document properties,
charts (column, bar, pie, line, scatter), comments, and images.

All tests create .xlsx files and read them back with openpyxl for verification.
Charts are verified via openpyxl chart objects. Images are verified via ZIP
structure inspection.
"""

import datetime
import io
import os
import struct
import tempfile
import zipfile
import zlib

import openpyxl
import pytest


# ============================================================
# Helper
# ============================================================


def _create_and_read(write_fn, **wb_options):
    """Create a temp xlsx using write_fn(workbook), close, read back with openpyxl."""
    import xlsxwriter

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp_path = f.name

    try:
        with xlsxwriter.Workbook(tmp_path, wb_options) as wb:
            write_fn(wb)
        return openpyxl.load_workbook(tmp_path)
    finally:
        os.unlink(tmp_path)


def _create_and_read_raw(write_fn, **wb_options):
    """Create a temp xlsx and return both openpyxl workbook and raw ZIP bytes."""
    import xlsxwriter

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        tmp_path = f.name

    try:
        with xlsxwriter.Workbook(tmp_path, wb_options) as wb:
            write_fn(wb)
        with open(tmp_path, "rb") as fh:
            raw = fh.read()
        wb_read = openpyxl.load_workbook(tmp_path)
        return wb_read, raw
    finally:
        os.unlink(tmp_path)


def _make_test_png():
    """Create a minimal valid 1x1 red PNG file and return the bytes."""
    sig = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr = b"IHDR" + ihdr_data
    ihdr_crc = struct.pack(">I", zlib.crc32(ihdr) & 0xFFFFFFFF)
    ihdr_chunk = struct.pack(">I", len(ihdr_data)) + ihdr + ihdr_crc
    # IDAT chunk
    raw_row = b"\x00\xff\x00\x00"  # filter byte + RGB
    idat_data = zlib.compress(raw_row)
    idat = b"IDAT" + idat_data
    idat_crc = struct.pack(">I", zlib.crc32(idat) & 0xFFFFFFFF)
    idat_chunk = struct.pack(">I", len(idat_data)) + idat + idat_crc
    # IEND chunk
    iend = b"IEND"
    iend_crc = struct.pack(">I", zlib.crc32(iend) & 0xFFFFFFFF)
    iend_chunk = struct.pack(">I", 0) + iend + iend_crc
    return sig + ihdr_chunk + idat_chunk + iend_chunk


# ============================================================
# 1. Workbook and Worksheet Basics
# ============================================================


class TestWorkbookBasics:
    """Tests for workbook creation, worksheet naming, and exceptions."""

    def test_worksheet_naming_and_exceptions(self):
        """Default names, custom names, and duplicate/invalid name exceptions (catchable as their base class)."""
        from xlsxwriter.exceptions import (
            DuplicateWorksheetName,
            InvalidWorksheetName,
            XlsxInputError,
        )

        def write_fn(wb):
            ws1 = wb.add_worksheet()
            wb.add_worksheet()
            wb.add_worksheet("Custom")
            ws1.write(0, 0, "s1")

        wb_read = _create_and_read(write_fn)
        assert wb_read.sheetnames == ["Sheet1", "Sheet2", "Custom"]
        wb_read.close()

        # Duplicate name
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp = f.name
        try:
            with pytest.raises(DuplicateWorksheetName):
                with __import__("xlsxwriter").Workbook(tmp) as wb:
                    wb.add_worksheet("Dup")
                    wb.add_worksheet("Dup")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

        # Invalid characters
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp = f.name
        try:
            with pytest.raises(InvalidWorksheetName):
                with __import__("xlsxwriter").Workbook(tmp) as wb:
                    wb.add_worksheet("Bad[Name")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

        # Input-error subtypes must be catchable via the shared base class (real polymorphic
        # behavior, not a declaration check): an invalid name caught as the base XlsxInputError.
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp = f.name
        try:
            with pytest.raises(XlsxInputError):
                with __import__("xlsxwriter").Workbook(tmp) as wb:
                    wb.add_worksheet("Bad]Name")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ============================================================
# 3. Cell Writing
# ============================================================


class TestCellWriting:
    """Tests for writing various data types and the write() dispatcher."""

    def test_write_dispatcher_all_types(self):
        """The generic write() method dispatches strings, numbers, booleans, None, datetimes, and formulas to correct writers, and utility functions convert between cell references."""
        from xlsxwriter.utility import (
            xl_cell_to_rowcol,
            xl_cell_to_rowcol_abs,
            xl_col_to_name,
            xl_range,
            xl_range_abs,
            xl_rowcol_to_cell,
        )

        # -- Utility function checks --
        assert xl_rowcol_to_cell(0, 0) == "A1"
        assert xl_rowcol_to_cell(9, 2) == "C10"
        assert xl_cell_to_rowcol("A1") == (0, 0)
        assert xl_cell_to_rowcol("Z1") == (0, 25)
        assert xl_cell_to_rowcol("AA1") == (0, 26)
        assert xl_rowcol_to_cell(0, 0, row_abs=True, col_abs=True) == "$A$1"
        assert xl_rowcol_to_cell(0, 0, row_abs=True) == "A$1"
        assert xl_rowcol_to_cell(0, 0, col_abs=True) == "$A1"
        assert xl_col_to_name(0) == "A"
        assert xl_col_to_name(25) == "Z"
        assert xl_col_to_name(26) == "AA"
        assert xl_col_to_name(0, col_abs=True) == "$A"
        assert xl_range(0, 0, 3, 2) == "A1:C4"
        assert xl_range(0, 0, 0, 0) == "A1"
        assert xl_range_abs(0, 0, 3, 2) == "$A$1:$C$4"
        row, col, row_abs, col_abs = xl_cell_to_rowcol_abs("$B$3")
        assert (row, col) == (2, 1)
        assert row_abs is True and col_abs is True
        row, col, row_abs, col_abs = xl_cell_to_rowcol_abs("C4")
        assert (row, col) == (3, 2)
        assert row_abs is False and col_abs is False
        assert xl_cell_to_rowcol("$A$1") == (0, 0)

        # -- Write dispatcher checks --
        def write_fn(wb):
            ws = wb.add_worksheet()
            date_fmt = wb.add_format({"num_format": "yyyy-mm-dd"})

            ws.write(0, 0, "text")
            ws.write(1, 0, 42)
            ws.write(2, 0, 3.14)
            ws.write(3, 0, True)
            ws.write(4, 0, None)
            ws.write(5, 0, "=1+1")

            ws.write_string(0, 1, "explicit_str")
            ws.write_number(1, 1, -99.5)
            ws.write_boolean(2, 1, False)
            ws.write_formula(3, 1, "=SUM(A1:A3)", value=45.14)
            ws.write_datetime(4, 1, datetime.datetime(2024, 1, 15, 10, 30), date_fmt)
            ws.write_blank(5, 1, None, wb.add_format({"italic": True}))

            ws.write("C1", "a1_notation")
            ws.write("C2", 999)

            ws.write_row(7, 0, ["R1", "R2", "R3", 100])
            ws.write_column(0, 3, [10, 20, 30])

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert ws["A1"].value == "text"
        assert ws["A2"].value == 42
        assert abs(ws["A3"].value - 3.14) < 1e-10
        assert ws["A4"].value is True
        assert ws["A6"].value == "=1+1"

        assert ws["B1"].value == "explicit_str"
        assert ws["B2"].value == -99.5
        assert ws["B3"].value is False
        assert ws["B4"].value == "=SUM(A1:A3)"
        val = ws["B5"].value
        assert isinstance(val, datetime.datetime)
        assert val.year == 2024 and val.month == 1 and val.day == 15
        assert ws["B6"].value is None

        assert ws["C1"].value == "a1_notation"
        assert ws["C2"].value == 999

        assert ws["A8"].value == "R1"
        assert ws["D8"].value == 100
        assert ws["D1"].value == 10
        assert ws["D3"].value == 30
        wb_read.close()

    def test_write_date_with_default_format(self):
        """Write dates with default_date_format workbook option and strings_to_numbers."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.write(0, 0, datetime.datetime(2024, 6, 15))
            ws.write(1, 0, datetime.date(2024, 12, 25))
            ws.write(2, 0, "123")
            ws.write(3, 0, "45.6")

        wb_read = _create_and_read(
            write_fn,
            default_date_format="yyyy-mm-dd",
            strings_to_numbers=True,
        )
        ws = wb_read.active
        v1 = ws["A1"].value
        assert isinstance(v1, datetime.datetime) and v1.year == 2024 and v1.month == 6
        v2 = ws["A2"].value
        assert isinstance(v2, (datetime.datetime, datetime.date))
        assert v2.year == 2024 and v2.month == 12 and v2.day == 25
        assert ws["A3"].value == 123
        assert abs(ws["A4"].value - 45.6) < 1e-10
        wb_read.close()


# ============================================================
# 4. Formatting Integration
# ============================================================


class TestFormattingIntegration:
    """Tests combining multiple format properties and set_* methods in realistic scenarios."""

    def test_comprehensive_formatting(self):
        """Apply multiple format properties together: font, alignment, borders, fill, number format."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            header_fmt = wb.add_format(
                {
                    "bold": True,
                    "italic": True,
                    "font_name": "Arial",
                    "font_size": 14,
                    "font_color": "#FF0000",
                    "num_format": "0.00",
                    "align": "center",
                    "valign": "vcenter",
                    "text_wrap": True,
                    "border": 1,
                    "bg_color": "#FFFF00",
                    "pattern": 1,
                    "underline": True,
                }
            )
            ws.write(0, 0, 3.14159, header_fmt)

            fmt2 = wb.add_format()
            fmt2.set_bold()
            fmt2.set_font_size(16)
            fmt2.set_font_name("Courier New")
            fmt2.set_font_color("#0000FF")
            fmt2.set_align("right")
            fmt2.set_border(1)
            fmt2.set_num_format("$#,##0.00")
            ws.write(1, 0, 1234.5, fmt2)

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        cell = ws["A1"]
        assert cell.font.bold is True
        assert cell.font.italic is True
        assert cell.font.name == "Arial"
        assert cell.font.size == 14
        assert "FF0000" in cell.font.color.rgb
        assert cell.number_format == "0.00"
        assert cell.alignment.horizontal == "center"
        assert cell.alignment.vertical == "center"
        assert cell.alignment.wrap_text is True
        assert cell.border.top.style == "thin"
        assert "FFFF00" in cell.fill.fgColor.rgb
        assert cell.font.underline == "single"

        cell2 = ws["A2"]
        assert cell2.font.bold is True
        assert cell2.font.size == 16
        assert cell2.font.name == "Courier New"
        assert cell2.alignment.horizontal == "right"
        assert cell2.number_format == "$#,##0.00"
        wb_read.close()


# ============================================================
# 5. Tables
# ============================================================


class TestTables:
    """Tests for Excel tables with headers, totals, formulas, and naming."""

    def test_table_with_totals_and_multiple_tables(self):
        """Create multiple named tables on the same sheet, one with a total row."""
        from xlsxwriter.exceptions import DuplicateTableName

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.add_table(
                "A1:C5",
                {
                    "name": "SalesQ1",
                    "data": [
                        ["East", 100, 200],
                        ["West", 150, 250],
                        ["North", 120, 180],
                    ],
                    "total_row": True,
                    "columns": [
                        {"header": "Region", "total_string": "Total"},
                        {"header": "Jan", "total_function": "sum"},
                        {"header": "Feb", "total_function": "sum"},
                    ],
                },
            )
            ws.add_table(
                "E1:F3",
                {
                    "name": "Lookup",
                    "data": [["X", 1], ["Y", 2]],
                    "columns": [{"header": "Key"}, {"header": "Val"}],
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active
        assert ws["A1"].value == "Region"
        assert ws["B1"].value == "Jan"
        assert ws["A2"].value == "East"
        assert ws["B2"].value == 100
        assert ws["A5"].value == "Total"
        assert ws["E1"].value == "Key"
        assert ws["E2"].value == "X"
        tables = list(ws.tables.values())
        assert len(tables) == 2
        table_names = {t.name for t in tables}
        assert "SalesQ1" in table_names
        assert "Lookup" in table_names
        wb_read.close()

        # Duplicate table name error
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp = f.name
        try:
            with pytest.raises(DuplicateTableName):
                with __import__("xlsxwriter").Workbook(tmp) as wb:
                    ws = wb.add_worksheet()
                    ws.add_table(
                        "A1:B3",
                        {
                            "name": "MyTable",
                            "data": [["a", 1], ["b", 2]],
                            "columns": [{"header": "X"}, {"header": "Y"}],
                        },
                    )
                    ws.add_table(
                        "D1:E3",
                        {
                            "name": "MyTable",
                            "data": [["c", 3], ["d", 4]],
                            "columns": [{"header": "P"}, {"header": "Q"}],
                        },
                    )
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ============================================================
# 6. Merge, Data Validation, Conditional Formatting, Autofilter
# ============================================================


class TestSheetFeatures:
    """Tests combining merge ranges, data validation, conditional formatting, and autofilter."""

    def test_merge_and_autofilter_with_data(self):
        """Create a sheet with merged header, data rows, autofilter, and validation."""
        from xlsxwriter.exceptions import OverlappingRange

        def write_fn(wb):
            ws = wb.add_worksheet()
            title_fmt = wb.add_format(
                {"bold": True, "align": "center", "font_size": 16}
            )
            ws.merge_range("A1:D1", "Sales Report Q1", title_fmt)

            ws.write_row(2, 0, ["Name", "Region", "Amount", "Status"])

            rows = [
                ["Alice", "East", 5000, "Active"],
                ["Bob", "West", 3200, "Active"],
                ["Carol", "East", 4100, "Inactive"],
                ["Dave", "North", 2800, "Active"],
            ]
            for i, row in enumerate(rows):
                ws.write_row(3 + i, 0, row)

            ws.autofilter("A3:D7")

            ws.data_validation(
                "D4:D7",
                {
                    "validate": "list",
                    "source": ["Active", "Inactive", "Pending"],
                },
            )

            ws.data_validation(
                "C4:C7",
                {
                    "validate": "integer",
                    "criteria": ">=",
                    "value": 0,
                },
            )

            fmt_high = wb.add_format({"bg_color": "#00FF00", "pattern": 1})
            ws.conditional_format(
                "C4:C7",
                {
                    "type": "cell",
                    "criteria": ">",
                    "value": 4000,
                    "format": fmt_high,
                },
            )

            ws.conditional_format(
                "C4:C7",
                {
                    "type": "2_color_scale",
                    "min_color": "#FF0000",
                    "max_color": "#00FF00",
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert ws["A1"].value == "Sales Report Q1"
        merged = list(ws.merged_cells.ranges)
        assert len(merged) == 1
        assert str(merged[0]) == "A1:D1"

        assert ws["A4"].value == "Alice"
        assert ws["C5"].value == 3200

        assert ws.auto_filter.ref == "A3:D7"

        validations = ws.data_validations.dataValidation
        assert len(validations) == 2

        cf_rules = list(ws.conditional_formatting)
        all_rules = [r for cf in cf_rules for r in cf.rules]
        assert len(all_rules) == 2
        rule_types = {r.type for r in all_rules}
        assert rule_types == {"cellIs", "colorScale"}
        cell_rule = next(r for r in all_rules if r.type == "cellIs")
        assert cell_rule.operator == "greaterThan"
        assert "4000" in (cell_rule.formula or [])
        wb_read.close()

        # Overlapping merge raises
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp = f.name
        try:
            with pytest.raises(OverlappingRange):
                with __import__("xlsxwriter").Workbook(tmp) as wb:
                    ws = wb.add_worksheet()
                    fmt = wb.add_format()
                    ws.merge_range("A1:C1", "First", fmt)
                    ws.merge_range("B1:D1", "Overlap", fmt)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ============================================================
# 7. Row/Column Properties with Outline Grouping
# ============================================================


class TestRowColumnAndOutlines:
    """Tests for row/column sizing, hiding, and outline grouping."""

    def test_row_column_properties(self):
        """Set row heights, column widths, hidden rows/columns, and row outline levels."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            ws.set_column("A:A", 20)
            ws.set_column(1, 1, 15)
            ws.set_column(2, 2, None, None, {"hidden": True})

            ws.set_row(0, 30)
            ws.set_row(3, None, None, {"hidden": True})

            ws.set_row(1, None, None, {"level": 1})
            ws.set_row(2, None, None, {"level": 1})

            ws.write(0, 0, "Header")
            ws.write(1, 0, "Detail 1")
            ws.write(2, 0, "Detail 2")
            ws.write(3, 0, "Hidden Row")
            ws.write(0, 2, "Hidden Col")

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert ws.column_dimensions["A"].width is not None
        assert ws.column_dimensions["A"].width > 15

        assert ws.column_dimensions["C"].hidden is True

        assert ws.row_dimensions[1].height == 30

        assert ws.row_dimensions[4].hidden is True

        assert ws.row_dimensions[2].outline_level == 1
        assert ws.row_dimensions[3].outline_level == 1

        assert ws["A1"].value == "Header"
        assert ws["A2"].value == "Detail 1"
        wb_read.close()


# ============================================================
# 8. Defined Names
# ============================================================


class TestDefinedNames:
    """Tests for workbook-level and sheet-level defined names."""

    def test_global_and_local_defined_names(self):
        """Create global and sheet-local defined names, verify via openpyxl."""

        def write_fn(wb):
            ws1 = wb.add_worksheet("Data")
            ws2 = wb.add_worksheet("Summary")

            ws1.write(0, 0, 100)
            ws1.write(1, 0, 200)
            ws2.write(0, 0, "=SUM(TotalRange)")

            wb.define_name("TotalRange", "=Data!$A$1:$A$2")
            wb.define_name("Data!LocalRate", "=0.15")

        wb_read = _create_and_read(write_fn)

        names = wb_read.defined_names
        total_range = names.get("TotalRange")
        assert total_range is not None
        dests = list(total_range.destinations)
        assert ("Data", "$A$1:$A$2") in dests

        # The sheet-local name lives on the "Data" sheet, not in the global table.
        assert "LocalRate" not in names
        local_names = wb_read["Data"].defined_names
        local_rate = local_names.get("LocalRate")
        assert local_rate is not None
        assert "0.15" in local_rate.value

        wb_read.close()


# ============================================================
# 9. Rich Strings
# ============================================================


class TestRichStrings:
    """Tests for write_rich_string with multiple formatting runs."""

    def test_rich_string_formatting(self):
        """Write a string with mixed bold/italic formatting runs and verify the concatenated text."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            bold = wb.add_format({"bold": True})
            italic = wb.add_format({"italic": True})
            red = wb.add_format({"font_color": "#FF0000"})

            ws.write_rich_string(
                0, 0, "This is ", bold, "bold", " and ", italic, "italic", " text"
            )
            ws.write_rich_string(1, 0, red, "WARNING", ": error occurred")

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert ws["A1"].value == "This is bold and italic text"
        assert ws["A2"].value == "WARNING: error occurred"
        wb_read.close()


# ============================================================
# 10. Array Formulas
# ============================================================


class TestArrayFormulas:
    """Tests for static array formulas spanning multiple cells."""

    def test_multi_cell_array_formula(self):
        """Write a multi-cell CSE array formula and verify its ref spans the full range.

        Exercises the multi-cell CSE branch (a single t="array" element whose ref spans the
        whole output range, e.g. C1:C3) -- distinct from the single-cell CSE (ref="C2") and
        dynamic-array (D1:D5) branches covered by test_mixed_formula_types_in_one_sheet.
        """

        def write_fn(wb):
            ws = wb.add_worksheet()
            for i in range(1, 4):
                ws.write_number(i - 1, 0, i * 10)  # A1:A3 = 10,20,30
                ws.write_number(i - 1, 1, i * 5)  # B1:B3 = 5,10,15
            ws.write_array_formula("C1:C3", "=A1:A3*B1:B3", None, 0)

        import re

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")

        array_tags = re.findall(r'<f[^>]*t="array"[^>]*>[^<]*</f>', sheet_xml)
        # Exactly one CSE array element, with the multi-cell ref spanning the full range.
        assert len(array_tags) == 1
        assert 'ref="C1:C3"' in array_tags[0]
        assert "A1:A3*B1:B3" in array_tags[0]

        wb_read.close()


# ============================================================
# 11. Worksheet Protection
# ============================================================


class TestProtection:
    """Tests for worksheet protection and locked/hidden cell format attributes."""

    def test_protect_worksheet_with_options(self):
        """Protect a worksheet with password and options, and use locked/hidden format attributes."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            unlocked = wb.add_format({"locked": False})
            hidden = wb.add_format({"locked": True, "hidden": True})

            ws.write(0, 0, "Editable", unlocked)
            ws.write(1, 0, "=1+1", hidden)
            ws.write(2, 0, "Protected (default locked)")

            ws.protect(
                "secret123",
                {
                    "format_cells": True,
                    "insert_rows": True,
                    "sort": True,
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert ws.protection.sheet is True
        assert ws.protection.password is not None

        assert ws["A1"].protection.locked is False
        assert ws["A2"].protection.hidden is True
        wb_read.close()


# ============================================================
# 12. Headers, Footers, and Page Setup
# ============================================================


class TestPageSetup:
    """Tests for headers, footers, page orientation, margins, print area, and repeat rows."""

    def test_header_footer_and_page_layout(self):
        """Set header/footer strings, page orientation, paper size, margins, print scale, and freeze panes in various configurations."""

        def write_fn(wb):
            ws = wb.add_worksheet("Main")

            ws.set_header("&LLeft Section&CCenter Title&RPage &P of &N")
            ws.set_footer("&CFooter Text")

            ws.set_landscape()
            ws.set_paper(9)
            ws.set_margins(left=0.5, right=0.5, top=0.75, bottom=0.75)
            ws.set_print_scale(80)

            ws.write(0, 0, "Page Setup Test")

            # Freeze panes on additional sheets
            ws1 = wb.add_worksheet("FreezeRow")
            ws1.freeze_panes(1, 0)
            ws1.write(0, 0, "Header")
            ws1.write(1, 0, "Data")

            ws2 = wb.add_worksheet("FreezeCol")
            ws2.freeze_panes(0, 1)
            ws2.write(0, 0, "Label")
            ws2.write(0, 1, "Value")

            ws3 = wb.add_worksheet("FreezeBoth")
            ws3.freeze_panes("B2")
            ws3.write(0, 0, "Corner")
            ws3.write(1, 1, "Data")

        wb_read = _create_and_read(write_fn)
        ws = wb_read["Main"]

        # Verify header contains expected text
        header_str = str(ws.oddHeader) if ws.oddHeader else ""
        assert "Center Title" in header_str or (
            ws.oddHeader
            and ws.oddHeader.center
            and "Center Title" in ws.oddHeader.center.text
        )

        assert ws.page_setup.orientation == "landscape"
        assert ws.page_setup.scale == 80
        assert abs(ws.page_margins.left - 0.5) < 1e-9
        assert abs(ws.page_margins.right - 0.5) < 1e-9

        # Verify freeze panes
        assert wb_read["FreezeRow"].freeze_panes == "A2"
        assert wb_read["FreezeCol"].freeze_panes == "B1"
        assert wb_read["FreezeBoth"].freeze_panes == "B2"
        wb_read.close()

    def test_print_area_and_repeat_rows(self):
        """Set print area and repeat rows (title rows) for printing."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.write_row(0, 0, ["Col A", "Col B", "Col C"])
            for i in range(1, 20):
                ws.write_row(i, 0, [f"R{i}A", f"R{i}B", f"R{i}C"])

            ws.print_area("A1:C20")
            ws.repeat_rows(0)

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        pa = ws.print_area
        assert pa is not None
        assert "$A$1" in pa and "$C$20" in pa

        # repeat_rows(0) defines the first row as the print title row, surfaced by
        # openpyxl as print_title_rows (the _xlnm.Print_Titles defined name).
        assert ws.print_title_rows == "$1:$1"
        wb_read.close()


# ============================================================
# 13. Hyperlinks
# ============================================================


class TestHyperlinks:
    """Tests for hyperlinks: web URLs, internal links, display text, and tooltips."""

    def test_hyperlinks_with_text_and_tooltip(self):
        """Write multiple hyperlinks with custom display text, tooltips, and internal links."""

        def write_fn(wb):
            ws1 = wb.add_worksheet("Links")
            ws2 = wb.add_worksheet("Target")

            ws1.write_url(0, 0, "https://example.com", string="Example Site")
            ws1.write_url(
                1, 0, "https://python.org", string="Python", tip="Python Home"
            )
            ws1.write_url(2, 0, "internal:Target!A1", string="Go to Target")

            ws2.write(0, 0, "Target Cell")

        wb_read = _create_and_read(write_fn)
        ws = wb_read["Links"]

        assert ws["A1"].hyperlink is not None
        assert ws["A1"].hyperlink.target == "https://example.com"

        assert ws["A2"].hyperlink is not None
        assert ws["A2"].hyperlink.target == "https://python.org"
        assert ws["A2"].hyperlink.tooltip == "Python Home"

        # Internal link must point at the same-document location, not just exist: an
        # "internal:Target!A1" link resolves to location "Target!A1" with no external target,
        # which is what distinguishes it from a web URL (verified by value, not mere presence).
        assert ws["A3"].hyperlink is not None
        assert ws["A3"].hyperlink.location == "Target!A1"
        assert ws["A3"].hyperlink.target is None

        assert wb_read["Target"]["A1"].value == "Target Cell"
        wb_read.close()


# ============================================================
# 16. In-Memory and OPC Structure
# ============================================================


class TestInMemoryAndOPC:
    """Tests for in-memory workbook creation and OPC ZIP structure verification."""

    def test_in_memory_workbook(self):
        """Create workbook in memory using BytesIO, verify OPC archive structure, and test context manager and explicit close lifecycle."""
        import xlsxwriter

        # -- In-memory workbook --
        output = io.BytesIO()
        with xlsxwriter.Workbook(output, {"in_memory": True}) as wb:
            ws = wb.add_worksheet()
            ws.write(0, 0, "In Memory")
            ws.add_table(
                "A3:B5",
                {
                    "data": [["x", 1], ["y", 2]],
                    "columns": [{"header": "Key"}, {"header": "Val"}],
                },
            )

        output.seek(0)

        with zipfile.ZipFile(output) as zf:
            names = zf.namelist()
            assert "[Content_Types].xml" in names
            assert "_rels/.rels" in names
            assert "xl/workbook.xml" in names
            assert "xl/worksheets/sheet1.xml" in names
            assert "xl/sharedStrings.xml" in names
            assert "xl/styles.xml" in names
            assert "xl/theme/theme1.xml" in names
            assert "docProps/app.xml" in names
            assert "docProps/core.xml" in names

        output.seek(0)
        wb_read = openpyxl.load_workbook(output)
        assert wb_read.active["A1"].value == "In Memory"
        assert wb_read.active["A3"].value == "Key"
        wb_read.close()

        # -- Context manager produces valid xlsx --
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp1 = f.name
        try:
            with xlsxwriter.Workbook(tmp1) as wb:
                ws = wb.add_worksheet()
                ws.write(0, 0, "ctx")
            wb_read = openpyxl.load_workbook(tmp1)
            assert wb_read.active["A1"].value == "ctx"
            wb_read.close()
        finally:
            os.unlink(tmp1)

        # -- Explicit close produces valid xlsx --
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            tmp2 = f.name
        try:
            wb = xlsxwriter.Workbook(tmp2)
            ws = wb.add_worksheet()
            ws.write(0, 0, "close")
            wb.close()
            wb_read = openpyxl.load_workbook(tmp2)
            assert wb_read.active["A1"].value == "close"
            wb_read.close()
        finally:
            os.unlink(tmp2)


# ============================================================
# 17. Charts - Column/Bar
# ============================================================


class TestColumnBarChart:
    """Tests for creating column and bar charts with data series."""

    def test_column_chart_with_series_and_title(self):
        """Create a column chart with multiple series, title, and axis labels, then verify via openpyxl."""

        def write_fn(wb):
            ws = wb.add_worksheet("Data")

            ws.write_row(0, 0, ["Quarter", "Product A", "Product B"])
            data = [
                ("Q1", 100, 50),
                ("Q2", 200, 150),
                ("Q3", 300, 250),
                ("Q4", 400, 350),
            ]
            for i, (cat, v1, v2) in enumerate(data):
                ws.write(i + 1, 0, cat)
                ws.write(i + 1, 1, v1)
                ws.write(i + 1, 2, v2)

            chart = wb.add_chart({"type": "column"})
            chart.add_series(
                {
                    "name": "=Data!$B$1",
                    "categories": "=Data!$A$2:$A$5",
                    "values": "=Data!$B$2:$B$5",
                }
            )
            chart.add_series(
                {
                    "name": "=Data!$C$1",
                    "categories": "=Data!$A$2:$A$5",
                    "values": "=Data!$C$2:$C$5",
                }
            )
            chart.set_title({"name": "Sales by Quarter"})
            chart.set_x_axis({"name": "Quarter"})
            chart.set_y_axis({"name": "Revenue"})
            ws.insert_chart("E2", chart)

        wb_read = _create_and_read(write_fn)
        ws = wb_read["Data"]

        # Verify chart exists
        assert len(ws._charts) == 1
        chart = ws._charts[0]

        # openpyxl reads column charts as BarChart with vertical grouping
        assert type(chart).__name__ in ("BarChart", "BarChart3D")

        # Verify series count
        assert len(chart.series) == 2

        # Verify title text
        assert chart.title is not None
        title_text = ""
        if chart.title.tx and chart.title.tx.rich:
            for p in chart.title.tx.rich.p:
                for r in p.r:
                    title_text += r.t
        assert title_text == "Sales by Quarter"

        # Verify data in cells
        assert ws["A1"].value == "Quarter"
        assert ws["B2"].value == 100
        assert ws["C5"].value == 350
        wb_read.close()


# ============================================================
# 18. Charts - Pie
# ============================================================


class TestPieChart:
    """Tests for creating pie charts."""

    def test_pie_chart_with_categories(self):
        """Create a pie chart with categories and values, verify chart type and series."""

        def write_fn(wb):
            ws = wb.add_worksheet("Pie")

            ws.write_column(0, 0, ["Apples", "Oranges", "Bananas", "Grapes"])
            ws.write_column(0, 1, [50, 30, 15, 5])

            chart = wb.add_chart({"type": "pie"})
            chart.add_series(
                {
                    "categories": "=Pie!$A$1:$A$4",
                    "values": "=Pie!$B$1:$B$4",
                    "name": "Fruit Sales",
                }
            )
            chart.set_title({"name": "Market Share"})
            ws.insert_chart("D1", chart)

        wb_read = _create_and_read(write_fn)
        ws = wb_read["Pie"]

        assert len(ws._charts) == 1
        chart = ws._charts[0]
        assert type(chart).__name__ == "PieChart"
        assert len(chart.series) == 1

        # Title
        title_text = ""
        if chart.title and chart.title.tx and chart.title.tx.rich:
            for p in chart.title.tx.rich.p:
                for r in p.r:
                    title_text += r.t
        assert title_text == "Market Share"

        # Data
        assert ws["A1"].value == "Apples"
        assert ws["B1"].value == 50
        assert ws["B4"].value == 5
        wb_read.close()


# ============================================================
# 19. Charts - Line and Scatter
# ============================================================


class TestLineScatterChart:
    """Tests for line and scatter chart types."""

    def test_line_and_scatter_charts(self):
        """Create line and scatter charts on the same sheet, verify both are present."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            ws.write_row(0, 0, ["X", "Y1", "Y2"])
            for i in range(1, 6):
                ws.write(i, 0, i * 10)
                ws.write(i, 1, i * 15)
                ws.write(i, 2, i * i * 5)

            # Line chart
            line = wb.add_chart({"type": "line"})
            line.add_series(
                {
                    "name": "=Sheet1!$B$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$B$2:$B$6",
                }
            )
            line.set_title({"name": "Linear Trend"})
            ws.insert_chart("E1", line)

            # Scatter chart
            scatter = wb.add_chart({"type": "scatter"})
            scatter.add_series(
                {
                    "name": "=Sheet1!$C$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$C$2:$C$6",
                }
            )
            scatter.set_title({"name": "Quadratic Trend"})
            ws.insert_chart("E16", scatter)

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert len(ws._charts) == 2

        chart_types = {type(c).__name__ for c in ws._charts}
        assert "LineChart" in chart_types
        assert "ScatterChart" in chart_types

        # Verify data
        assert ws["A2"].value == 10
        assert ws["B2"].value == 15
        assert ws["C6"].value == 125  # 5*5*5
        wb_read.close()


# ============================================================
# 20. Charts - Formatting and Legend
# ============================================================


class TestChartFormatting:
    """Tests for chart formatting options: legend, style, size."""

    def test_chart_with_legend_and_size(self):
        """Create a chart with legend configuration, custom size, and area chart type."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            ws.write_column(0, 0, [10, 20, 30, 40])
            ws.write_column(0, 1, [15, 25, 35, 45])

            chart = wb.add_chart({"type": "area"})
            chart.add_series(
                {
                    "values": "=Sheet1!$A$1:$A$4",
                    "name": "Series A",
                }
            )
            chart.add_series(
                {
                    "values": "=Sheet1!$B$1:$B$4",
                    "name": "Series B",
                }
            )
            chart.set_title({"name": "Area Chart"})
            chart.set_legend({"position": "bottom"})
            chart.set_size({"width": 720, "height": 480})
            ws.insert_chart("D1", chart)

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert len(ws._charts) == 1
        chart = ws._charts[0]
        assert type(chart).__name__ == "AreaChart"
        assert len(chart.series) == 2

        # Legend position must be applied: 'bottom' serializes to legendPos val="b".
        assert chart.legend is not None
        assert chart.legend.position == "b"

        # Custom size must be applied: a 720x480 chart is larger than the default chart size. We
        # assert the enlarged extent rather than exact landing coordinates, which depend on
        # XlsxWriter's internal default-size and pixel->anchor constants the spec does not dictate.
        # The drawing anchor kind is likewise unspecified: a two-cell anchor exposes `.to` (a wider
        # cell span than a default chart at "D1", which reaches col 10 / row 14) while a one-cell
        # anchor carries the size as an absolute `<xdr:ext cx cy>` in EMU. Accept either.
        anchor = chart.anchor
        if hasattr(anchor, "to") and anchor.to is not None:
            assert anchor.to.col > 10
            assert anchor.to.row > 14
        else:
            # One-cell anchor: extent (EMU) must exceed a default-sized chart (480x288 px).
            assert anchor.ext.cx > 480 * 9525
            assert anchor.ext.cy > 288 * 9525

        wb_read.close()


# ============================================================
# 21. Comments
# ============================================================


class TestComments:
    """Tests for cell comments with author and text."""

    def test_write_comments(self):
        """Write comments to cells with and without author, verify via openpyxl."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.write(0, 0, "Data")
            ws.write(1, 0, 42)
            ws.write(2, 0, "More data")

            ws.write_comment("A1", "This is a comment on data")
            ws.write_comment("A2", "Number comment", {"author": "Reviewer"})

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        assert ws["A1"].value == "Data"
        assert ws["A1"].comment is not None
        assert ws["A1"].comment.text == "This is a comment on data"

        assert ws["A2"].comment is not None
        assert ws["A2"].comment.text == "Number comment"
        assert ws["A2"].comment.author == "Reviewer"

        # Cell without comment
        assert ws["A3"].comment is None
        wb_read.close()


# ============================================================
# 22. Images
# ============================================================


class TestImages:
    """Tests for inserting images into worksheets."""

    def test_insert_image(self):
        """Insert a PNG image and verify it appears in the xlsx ZIP archive."""
        png_path = os.path.join(tempfile.gettempdir(), "test_xlsxwriter_img.png")
        try:
            # Create test PNG
            with open(png_path, "wb") as f:
                f.write(_make_test_png())

            def write_fn(wb):
                ws = wb.add_worksheet()
                ws.write(0, 0, "Image Test")
                ws.insert_image("B2", png_path)

            wb_read, raw = _create_and_read_raw(write_fn)
            ws = wb_read.active
            assert ws["A1"].value == "Image Test"

            # Verify image exists in ZIP
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                names = zf.namelist()
                # Should have a drawing file
                drawing_files = [
                    n for n in names if "drawings/drawing" in n and n.endswith(".xml")
                ]
                assert len(drawing_files) >= 1
                # Should have the image in the media folder, and its bytes must be the exact
                # source PNG (a correct embedding path, not just a present-but-wrong member).
                media_files = [n for n in names if n.startswith("xl/media/")]
                png_members = [f for f in media_files if f.endswith(".png")]
                assert len(png_members) == 1
                assert zf.read(png_members[0]) == _make_test_png()

            wb_read.close()
        finally:
            if os.path.exists(png_path):
                os.unlink(png_path)


# ============================================================
# 23. Complex Multi-Sheet Integration
# ============================================================


class TestComplexIntegration:
    """Complex multi-sheet workbook exercising many features together."""

    def test_financial_report_workbook(self):
        """Build a realistic financial report with multiple sheets, formulas, formatting, tables, defined names, page setup, and document properties."""

        def write_fn(wb):
            wb.set_properties(
                {
                    "title": "Financial Report Q1",
                    "subject": "Quarterly Sales",
                    "author": "Finance Team",
                    "manager": "VP Finance",
                    "company": "Acme Corp",
                    "category": "Financial",
                    "keywords": "sales, quarterly, report",
                    "comments": "Auto-generated report",
                    "status": "Final",
                }
            )
            ws_data = wb.add_worksheet("Data")
            header_fmt = wb.add_format(
                {
                    "bold": True,
                    "bg_color": "#4472C4",
                    "font_color": "#FFFFFF",
                    "border": 1,
                    "align": "center",
                    "pattern": 1,
                }
            )
            money_fmt = wb.add_format({"num_format": "$#,##0.00"})
            pct_fmt = wb.add_format({"num_format": "0.0%"})

            headers = ["Product", "Q1", "Q2", "Q3", "Q4"]
            for col, h in enumerate(headers):
                ws_data.write(0, col, h, header_fmt)

            data = [
                ["Widget A", 10000, 12000, 9000, 11000],
                ["Widget B", 20000, 18000, 22000, 25000],
                ["Widget C", 5000, 6000, 5500, 7000],
            ]
            for row_idx, row_data in enumerate(data):
                ws_data.write(row_idx + 1, 0, row_data[0])
                for col_idx, val in enumerate(row_data[1:]):
                    ws_data.write(row_idx + 1, col_idx + 1, val, money_fmt)

            ws_data.set_column("A:A", 15)
            ws_data.set_column("B:E", 12)
            ws_data.set_row(0, 25)
            ws_data.freeze_panes(1, 0)
            wb.define_name("SalesData", "=Data!$B$2:$E$4")
            ws_data.print_area("A1:E4")

            ws_sum = wb.add_worksheet("Summary")
            ws_sum.write(0, 0, "Total Sales", header_fmt)
            ws_sum.write(0, 1, "=SUM(SalesData)", money_fmt)

            ws_sum.write(2, 0, "Widget A Growth Q4/Q1", wb.add_format({"bold": True}))
            ws_sum.write(2, 1, "=Data!E2/Data!B2-1", pct_fmt)

            title_fmt = wb.add_format(
                {
                    "bold": True,
                    "font_size": 18,
                    "align": "center",
                    "valign": "vcenter",
                }
            )
            ws_sum.merge_range("A5:D5", "Quarterly Sales Summary", title_fmt)

            ws_sum.set_landscape()
            ws_sum.set_header("&CSales Report")

            ws_val = wb.add_worksheet("Input")
            ws_val.write(0, 0, "Region")
            ws_val.write(0, 1, "Amount")
            ws_val.data_validation(
                "A2:A10",
                {
                    "validate": "list",
                    "source": ["East", "West", "North", "South"],
                },
            )
            ws_val.data_validation(
                "B2:B10",
                {
                    "validate": "decimal",
                    "criteria": "between",
                    "minimum": 0,
                    "maximum": 1000000,
                },
            )
            ws_val.protect()

        wb_read = _create_and_read(write_fn)

        assert wb_read.sheetnames == ["Data", "Summary", "Input"]

        ws_data = wb_read["Data"]
        assert ws_data["A1"].value == "Product"
        assert ws_data["A1"].font.bold is True
        assert ws_data["B2"].value == 10000
        assert ws_data["B2"].number_format == "$#,##0.00"
        assert ws_data.freeze_panes == "A2"

        ws_sum = wb_read["Summary"]
        assert ws_sum["A1"].value == "Total Sales"
        assert ws_sum["B1"].value == "=SUM(SalesData)"
        merged = list(ws_sum.merged_cells.ranges)
        assert len(merged) == 1
        assert str(merged[0]) == "A5:D5"
        assert ws_sum["A5"].value == "Quarterly Sales Summary"
        assert ws_sum.page_setup.orientation == "landscape"

        ws_val = wb_read["Input"]
        assert ws_val.protection.sheet is True
        validations = ws_val.data_validations.dataValidation
        assert len(validations) == 2

        dn = wb_read.defined_names.get("SalesData")
        assert dn is not None
        assert ("Data", "$B$2:$E$4") in list(dn.destinations)

        pa = ws_data.print_area
        assert pa is not None
        assert "$A$1" in pa and "$E$4" in pa

        # Verify document properties
        props = wb_read.properties
        assert props.title == "Financial Report Q1"
        assert props.subject == "Quarterly Sales"
        assert props.creator == "Finance Team"
        assert props.category == "Financial"
        assert props.keywords == "sales, quarterly, report"
        assert props.description == "Auto-generated report"

        wb_read.close()

    def test_data_analysis_workbook(self):
        """Build a workbook with outline grouping, conditional formatting, hyperlinks, and rich strings."""

        def write_fn(wb):
            ws = wb.add_worksheet("Analysis")
            bold = wb.add_format({"bold": True})
            italic = wb.add_format({"italic": True})

            ws.write_rich_string(0, 0, bold, "Sales ", italic, "Analysis", " Report")

            ws.write(1, 0, "Category", bold)
            ws.write(1, 1, "Value", bold)
            ws.write(1, 2, "Note", bold)

            ws.set_row(2, None, None, {"level": 1})
            ws.set_row(3, None, None, {"level": 1})
            ws.set_row(4, None, None, {"level": 1})
            ws.write(2, 0, "Phones")
            ws.write(2, 1, 5000)
            ws.write(3, 0, "Laptops")
            ws.write(3, 1, 8000)
            ws.write(4, 0, "Tablets")
            ws.write(4, 1, 3000)

            ws.set_row(5, None, None, {"level": 1})
            ws.set_row(6, None, None, {"level": 1})
            ws.write(5, 0, "Shirts")
            ws.write(5, 1, 2000)
            ws.write(6, 0, "Pants")
            ws.write(6, 1, 1500)

            ws.write(7, 0, "Total", bold)
            ws.write_formula(7, 1, "=SUM(B3:B7)", bold, 19500)

            cond_fmt = wb.add_format({"bg_color": "#C6EFCE", "pattern": 1})
            ws.conditional_format(
                "B3:B7",
                {
                    "type": "cell",
                    "criteria": ">=",
                    "value": 5000,
                    "format": cond_fmt,
                },
            )

            dup_fmt = wb.add_format({"bg_color": "#FFC7CE", "pattern": 1})
            ws.conditional_format(
                "B3:B7",
                {
                    "type": "duplicate",
                    "format": dup_fmt,
                },
            )

            ws.write_url(
                9,
                0,
                "https://example.com/report",
                string="Full Report",
                tip="View online",
            )

            ws.data_validation(
                "C3:C7",
                {
                    "validate": "list",
                    "source": ["Good", "Average", "Poor"],
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read["Analysis"]

        assert ws["A1"].value == "Sales Analysis Report"

        assert ws["A3"].value == "Phones"
        assert ws["B3"].value == 5000
        assert ws["B8"].value == "=SUM(B3:B7)"

        assert ws.row_dimensions[3].outline_level == 1
        assert ws.row_dimensions[6].outline_level == 1

        cf_rules = list(ws.conditional_formatting)
        all_rules = [r for cf in cf_rules for r in cf.rules]
        assert len(all_rules) == 2
        rule_types = {r.type for r in all_rules}
        assert rule_types == {"cellIs", "duplicateValues"}
        cell_rule = next(r for r in all_rules if r.type == "cellIs")
        assert cell_rule.operator == "greaterThanOrEqual"
        assert "5000" in (cell_rule.formula or [])

        assert ws["A10"].hyperlink is not None
        assert ws["A10"].hyperlink.target == "https://example.com/report"
        assert ws["A10"].hyperlink.tooltip == "View online"

        validations = ws.data_validations.dataValidation
        assert len(validations) == 1

        wb_read.close()


# ============================================================
# 22. Conditional Formatting (Advanced)
# ============================================================


class TestConditionalFormattingAdvanced:
    """Tests for advanced conditional formatting: color scales, data bars, icon sets."""

    def test_conditional_format_rules(self):
        """Apply cell_is, 2-color scale, 3-color scale, data_bar, and icon_set conditional formats to a range and verify all rules are written."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            for i in range(10):
                ws.write(i, 0, i * 10)

            fmt_red = wb.add_format({"bg_color": "#FF0000", "pattern": 1})
            ws.conditional_format(
                "A1:A10",
                {
                    "type": "cell",
                    "criteria": ">",
                    "value": 50,
                    "format": fmt_red,
                },
            )

            ws.conditional_format(
                "A1:A10",
                {
                    "type": "2_color_scale",
                    "min_color": "#FF0000",
                    "max_color": "#00FF00",
                },
            )

            ws.conditional_format(
                "A1:A10",
                {
                    "type": "3_color_scale",
                    "min_color": "#FF0000",
                    "mid_color": "#FFFF00",
                    "max_color": "#00FF00",
                },
            )

            ws.conditional_format(
                "A1:A10",
                {
                    "type": "data_bar",
                    "bar_color": "#0066CC",
                },
            )

            ws.conditional_format(
                "A1:A10",
                {
                    "type": "icon_set",
                    "icon_style": "3_arrows",
                },
            )

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        cf_rules = list(ws.conditional_formatting)
        assert len(cf_rules) >= 1

        all_rules = []
        for cf in cf_rules:
            all_rules.extend(cf.rules)
        assert len(all_rules) == 5

        rule_types = {r.type for r in all_rules}
        assert "cellIs" in rule_types
        assert "colorScale" in rule_types
        assert "dataBar" in rule_types
        assert "iconSet" in rule_types

        color_scale_rules = [r for r in all_rules if r.type == "colorScale"]
        assert len(color_scale_rules) == 2

        # The configured data_bar color and icon_set style must be serialized, not just the
        # presence of the rule kind. Verify against the worksheet XML: the dataBar color carries
        # the requested RGB (#0066CC -> rgb="...0066CC") and the iconSet carries the mapped style
        # attribute (icon_style "3_arrows" -> iconSet="3Arrows").
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
        data_bar_xml = sheet_xml[sheet_xml.index("<dataBar") : sheet_xml.index("</dataBar>")]
        assert "0066CC" in data_bar_xml
        assert 'iconSet="3Arrows"' in sheet_xml

        wb_read.close()


# ============================================================
# 23. Data Validation (Advanced)
# ============================================================


class TestDataValidationAdvanced:
    """Tests for advanced data validation: multiple types with messages."""

    def test_data_validation_types(self):
        """Add dropdown list, integer range with messages, custom formula, and text length validations; verify all rules are present."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            ws.data_validation(
                "A1:A10",
                {
                    "validate": "list",
                    "source": ["Red", "Green", "Blue"],
                },
            )

            ws.data_validation(
                "B1:B10",
                {
                    "validate": "integer",
                    "criteria": "between",
                    "minimum": 1,
                    "maximum": 100,
                    "input_title": "Enter number",
                    "input_message": "Must be 1-100",
                    "error_title": "Invalid",
                    "error_message": "Value must be between 1 and 100",
                },
            )

            ws.data_validation(
                "C1:C10",
                {
                    "validate": "custom",
                    "value": "=LEN(C1)<=10",
                },
            )

            ws.data_validation(
                "D1:D10",
                {
                    "validate": "length",
                    "criteria": "<=",
                    "value": 20,
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        validations = ws.data_validations.dataValidation
        assert len(validations) == 4

        val_by_type = {}
        for v in validations:
            val_by_type[v.type] = v

        # List validation
        assert "list" in val_by_type
        list_val = val_by_type["list"]
        assert '"Red,Green,Blue"' == list_val.formula1 or "Red,Green,Blue" in str(
            list_val.formula1
        )

        # Integer validation with input/error messages
        assert "whole" in val_by_type
        int_val = val_by_type["whole"]
        assert int_val.formula1 == "1" or int_val.formula1 == 1
        assert int_val.formula2 == "100" or int_val.formula2 == 100
        assert int_val.promptTitle == "Enter number"
        assert int_val.errorTitle == "Invalid"

        # Custom formula validation
        assert "custom" in val_by_type
        custom_val = val_by_type["custom"]
        assert "LEN(C1)<=10" in str(custom_val.formula1)

        # Text length validation
        assert "textLength" in val_by_type
        length_val = val_by_type["textLength"]
        assert length_val.operator == "lessThanOrEqual"
        assert length_val.formula1 == "20"

        wb_read.close()


# ============================================================
# 24. Chart with Secondary Axis
# ============================================================


class TestChartSecondaryAxis:
    """Tests for charts with secondary Y-axis and series formatting."""

    def test_chart_secondary_axis_with_formatting(self):
        """Create a column chart with a secondary Y-axis series, series fill/line formatting, and axis titles; verify via XML."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.write_row(0, 0, ["Month", "Revenue", "Growth Rate"])
            data = [
                ["Jan", 50000, 0.05],
                ["Feb", 55000, 0.10],
                ["Mar", 52000, -0.055],
                ["Apr", 60000, 0.154],
                ["May", 65000, 0.083],
            ]
            for i, row in enumerate(data):
                ws.write(i + 1, 0, row[0])
                ws.write(i + 1, 1, row[1])
                ws.write(i + 1, 2, row[2])

            chart = wb.add_chart({"type": "column"})
            chart.add_series(
                {
                    "name": "=Sheet1!$B$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$B$2:$B$6",
                    "fill": {"color": "#4472C4"},
                }
            )
            chart.add_series(
                {
                    "name": "=Sheet1!$C$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$C$2:$C$6",
                    "y2_axis": True,
                    "line": {"color": "#FF0000", "width": 2.5},
                }
            )
            chart.set_title({"name": "Revenue vs Growth"})
            chart.set_y_axis({"name": "Revenue ($)"})
            chart.set_y2_axis({"name": "Growth Rate"})
            ws.insert_chart("E2", chart)

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        # Verify chart exists via openpyxl
        assert len(ws._charts) >= 1

        # Verify via XML that there are 2 series and 2 value axes (primary + secondary)
        import re

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            chart_files = [
                n for n in zf.namelist() if "charts/chart" in n and n.endswith(".xml")
            ]
            assert len(chart_files) >= 1
            chart_xml = zf.read(chart_files[0]).decode("utf-8")

            # Two c:ser elements (one per series)
            sers = re.findall(r"<c:ser>", chart_xml)
            assert len(sers) == 2

            # Two value axes (primary + secondary Y axis)
            val_axes = re.findall(r"<c:valAx>", chart_xml)
            assert len(val_axes) == 2

            # Two category axes (primary + secondary)
            cat_axes = re.findall(r"<c:catAx>", chart_xml)
            assert len(cat_axes) == 2

            # Verify axis title text is in XML
            assert "Revenue" in chart_xml
            assert "Growth Rate" in chart_xml

            # Verify fill color for first series
            assert "4472C4" in chart_xml

            # Verify line color for second series
            assert "FF0000" in chart_xml

        # Verify data cells
        assert ws["A1"].value == "Month"
        assert ws["B2"].value == 50000
        assert abs(ws["C2"].value - 0.05) < 1e-10
        wb_read.close()


# ============================================================
# 25. Sparklines
# ============================================================


class TestSparklines:
    """Tests for sparklines: line, column, and win/loss types."""

    def test_sparkline_types(self):
        """Add line, column, and win/loss sparklines referencing data ranges and verify they appear in the worksheet XML."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            data = [
                [10, 20, 30, 40, 50],
                [50, 40, 30, 20, 10],
                [15, -5, 25, -10, 35],
            ]
            for i, row in enumerate(data):
                for j, val in enumerate(row):
                    ws.write(i, j, val)

            ws.add_sparkline(
                "F1", {"range": "Sheet1!A1:E1", "type": "line"}
            )
            ws.add_sparkline(
                "F2", {"range": "Sheet1!A2:E2", "type": "column"}
            )
            ws.add_sparkline(
                "F3", {"range": "Sheet1!A3:E3", "type": "win_loss"}
            )

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        # Verify data was written
        assert ws["A1"].value == 10
        assert ws["E1"].value == 50
        assert ws["A3"].value == 15
        assert ws["E3"].value == 35

        # Verify sparklines in XML
        import re

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")

            # sparklineGroup elements must exist
            groups = re.findall(r"<x14:sparklineGroup[^>]*>", sheet_xml)
            assert len(groups) >= 3

            # Individual sparkline elements
            sparklines = re.findall(r"<x14:sparkline>", sheet_xml)
            assert len(sparklines) == 3

            # Check sparkline types in XML
            assert 'type="column"' in sheet_xml
            assert 'type="stacked"' in sheet_xml  # win_loss is stacked in XML

            # Verify cell references are in the XML
            assert "F1" in sheet_xml
            assert "F2" in sheet_xml
            assert "F3" in sheet_xml

        wb_read.close()


# ============================================================
# 26. Outline/Grouping with Collapse (rows + columns)
# ============================================================


class TestOutlineGroupingCollapse:
    """Tests for row and column outline grouping with nested levels, hidden state, and collapse."""

    def test_outline_grouping_with_collapse(self):
        """Group rows across three nesting levels (1, 2, and 3) with hidden/collapsed flags, group columns at level 1 and 2 with hidden flags, and verify all outline properties and the XML collapsed attribute via openpyxl and ZIP inspection."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            # Row grouping: level 1, nested level 2, nested level 3, hidden, collapsed
            ws.set_row(1, None, None, {"level": 1})
            ws.set_row(2, None, None, {"level": 1})
            ws.set_row(3, None, None, {"level": 2})
            ws.set_row(4, None, None, {"level": 2, "hidden": True})
            ws.set_row(5, None, None, {"level": 3})
            ws.set_row(6, None, None, {"level": 3, "hidden": True})
            ws.set_row(7, None, None, {"level": 1, "collapsed": True})

            # Column grouping: B:C at level 1, D at level 2 hidden
            ws.set_column(1, 2, 12, None, {"level": 1})
            ws.set_column(3, 3, 10, None, {"level": 2, "hidden": True})

            # Write data so the sheet is non-empty
            for i in range(9):
                ws.write(i, 0, f"Row {i}")
                for j in range(1, 6):
                    ws.write(i, j, i * 10 + j)

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        # Verify row outline levels across all three nesting levels (openpyxl uses 1-based rows)
        assert ws.row_dimensions[2].outline_level == 1
        assert ws.row_dimensions[3].outline_level == 1
        assert ws.row_dimensions[4].outline_level == 2
        assert ws.row_dimensions[5].hidden is True
        assert ws.row_dimensions[6].outline_level == 3
        assert ws.row_dimensions[7].outline_level == 3
        assert ws.row_dimensions[7].hidden is True
        assert ws.row_dimensions[8].outline_level == 1

        # Verify column outline levels
        assert ws.column_dimensions["B"].outline_level == 1
        assert ws.column_dimensions["D"].outline_level == 2
        assert ws.column_dimensions["D"].hidden is True

        # Verify data integrity
        assert ws["A1"].value == "Row 0"
        assert ws["B2"].value == 11

        # Verify collapsed attribute exists in raw XML
        import re

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
            assert "collapsed" in sheet_xml

            # All three row outline levels must appear in the XML
            levels = set(re.findall(r'outlineLevel="(\d+)"', sheet_xml))
            assert "1" in levels and "2" in levels and "3" in levels

            # Verify column outline levels in XML
            col_elements = re.findall(r"<col [^/]*/>", sheet_xml)
            assert len(col_elements) >= 2
            outline_cols = [c for c in col_elements if "outlineLevel" in c]
            assert len(outline_cols) >= 2

        wb_read.close()


# ============================================================
# 27. Conditional Formatting: stop-if-true and rule priority
# ============================================================


class TestConditionalFormatStopIfTrue:
    """Tests for the per-rule stop_if_true flag and the priority ordering of stacked rules."""

    def test_conditional_format_stop_if_true_and_priority(self):
        """Apply two cell rules to one range with stop_if_true set on the first, and verify the stop-if-true flag is serialized only on that rule and that the two rules carry distinct, in-order priorities."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            for i in range(10):
                ws.write(i, 0, (i + 1) * 10)

            fmt_hi = wb.add_format({"bg_color": "#FFFF00", "pattern": 1})
            ws.conditional_format(
                "A1:A10",
                {
                    "type": "cell",
                    "criteria": ">=",
                    "value": 80,
                    "format": fmt_hi,
                    "stop_if_true": True,
                },
            )
            fmt_lo = wb.add_format({"bg_color": "#FF0000", "pattern": 1})
            ws.conditional_format(
                "A1:A10",
                {
                    "type": "cell",
                    "criteria": "<",
                    "value": 30,
                    "format": fmt_lo,
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        # Collect rules across every block covering A1:A10 -- how repeated calls on a range are
        # grouped into XML blocks is an internal serialization choice the spec does not dictate.
        cf_blocks = list(ws.conditional_formatting)
        a1a10_rules = [
            r
            for cf in cf_blocks
            if "A1:A10" in {str(rng) for rng in cf.cells.ranges}
            for r in cf.rules
        ]
        assert len(a1a10_rules) == 2

        # stop_if_true must propagate to the XML stopIfTrue attribute (openpyxl: rule.stopIfTrue
        # truthy) and only on the first rule; the second rule leaves it unset.
        by_op = {r.operator: r for r in a1a10_rules}
        assert by_op["greaterThanOrEqual"].stopIfTrue is True
        assert "80" in by_op["greaterThanOrEqual"].formula
        assert not by_op["lessThan"].stopIfTrue
        assert "30" in by_op["lessThan"].formula

        # Stacked rules get distinct evaluation priorities in the order they were added; the
        # stop-if-true rule is evaluated first.
        priorities = [r.priority for r in a1a10_rules]
        assert len(set(priorities)) == 2
        assert by_op["greaterThanOrEqual"].priority < by_op["lessThan"].priority

        wb_read.close()


# ============================================================
# 28. Chart with Custom Number Format and Data Labels
# ============================================================


class TestChartDataLabels:
    """Tests for chart series with data labels and custom axis number formats."""

    def test_chart_data_labels_and_axis_numfmt(self):
        """Create a column chart with data labels enabled on two series (one with custom number format, one with position), a custom Y-axis number format, and verify all via XML inspection of dLbls, numFmt, and showVal elements."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.write_row(0, 0, ["Month", "Revenue", "Profit"])
            data = [
                ("Jan", 50000, 12000),
                ("Feb", 62000, 15500),
                ("Mar", 58000, 14000),
                ("Apr", 71000, 18000),
                ("May", 65000, 16500),
            ]
            for i, (m, r, p) in enumerate(data):
                ws.write(i + 1, 0, m)
                ws.write(i + 1, 1, r)
                ws.write(i + 1, 2, p)

            chart = wb.add_chart({"type": "column"})
            chart.add_series(
                {
                    "name": "=Sheet1!$B$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$B$2:$B$6",
                    "data_labels": {"value": True, "num_format": "$#,##0"},
                }
            )
            chart.add_series(
                {
                    "name": "=Sheet1!$C$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$C$2:$C$6",
                    "data_labels": {"value": True, "position": "outside_end"},
                }
            )
            chart.set_title({"name": "Financial Overview"})
            chart.set_y_axis({"name": "Amount", "num_format": "$#,##0"})
            ws.insert_chart("E2", chart)

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        assert len(ws._charts) == 1
        chart = ws._charts[0]
        assert len(chart.series) == 2

        # Verify title
        title_text = ""
        if chart.title and chart.title.tx and chart.title.tx.rich:
            for p in chart.title.tx.rich.p:
                for r in p.r:
                    title_text += r.t
        assert title_text == "Financial Overview"

        # Verify data labels and number format in chart XML
        import re

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            chart_files = [
                n for n in zf.namelist() if "charts/chart" in n and n.endswith(".xml")
            ]
            assert len(chart_files) >= 1
            chart_xml = zf.read(chart_files[0]).decode("utf-8")

            # Two dLbls elements (one per series)
            dlbls_count = len(re.findall(r"<c:dLbls>", chart_xml))
            assert dlbls_count == 2

            # The configured "$#,##0" number format (data label on series 1 and the Y axis) must
            # appear verbatim, not merely some numFmt element.
            assert 'formatCode="$#,##0"' in chart_xml

            # showVal present (data labels enabled)
            assert "showVal" in chart_xml

        # Verify data cells
        assert ws["B2"].value == 50000
        assert ws["C6"].value == 16500
        wb_read.close()


# ============================================================
# 29. Large Workbook (10K+ Rows) with Formulas and Table
# ============================================================


class TestLargeWorkbook:
    """Tests for workbook with 10,000+ data rows, formatting, formulas, and a table."""

    @pytest.mark.timeout(60)
    def test_10k_rows_with_formulas_and_table(self):
        """Write 10,000 rows with number formatting, per-row formulas, and a 100-row table, then verify first, middle, and last row data plus formula text and table existence via openpyxl readback."""
        NUM_ROWS = 10000

        def write_fn(wb):
            ws = wb.add_worksheet()
            bold = wb.add_format({"bold": True})
            money = wb.add_format({"num_format": "#,##0.00"})

            headers = ["ID", "Name", "Value", "Tax", "Total"]
            for c, h in enumerate(headers):
                ws.write(0, c, h, bold)

            for i in range(1, NUM_ROWS + 1):
                ws.write(i, 0, i)
                ws.write(i, 1, f"Item_{i:05d}")
                ws.write(i, 2, i * 1.5, money)
                ws.write(i, 3, f"=C{i + 1}*0.1")
                ws.write(i, 4, f"=C{i + 1}+D{i + 1}")

            ws.add_table(
                "A1:E101",
                {
                    "name": "SalesTable",
                    "columns": [
                        {"header": "ID"},
                        {"header": "Name"},
                        {"header": "Value"},
                        {"header": "Tax"},
                        {"header": "Total"},
                    ],
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        # First row
        assert ws["A1"].value == "ID"
        assert ws["A2"].value == 1
        assert ws["B2"].value == "Item_00001"
        assert ws["C2"].value == 1.5

        # Middle row (row 5001 = data row 5000)
        assert ws["A5001"].value == 5000
        assert ws["B5001"].value == "Item_05000"

        # Last row
        last_row = NUM_ROWS + 1
        assert ws[f"A{last_row}"].value == NUM_ROWS
        assert ws[f"B{last_row}"].value == f"Item_{NUM_ROWS:05d}"

        # Formula verification
        assert ws["D2"].value == "=C2*0.1"
        assert ws["E2"].value == "=C2+D2"

        # Table verification
        tables = list(ws.tables.values())
        assert len(tables) == 1
        assert tables[0].name == "SalesTable"

        wb_read.close()


# ============================================================
# 30. Mixed Formula Types (regular, array, dynamic array)
# ============================================================


class TestMixedFormulaTypes:
    """Tests for combining regular, array (CSE), and dynamic array formulas in one sheet."""

    def test_mixed_formula_types_in_one_sheet(self):
        """Write regular formulas, a CSE array formula, and a dynamic array formula on one worksheet, then verify each formula type appears with correct XML attributes (plain <f>, t='array' with single-cell ref, t='array' with multi-cell ref) via ZIP inspection."""

        def write_fn(wb):
            ws = wb.add_worksheet()

            # Source data
            for i in range(1, 6):
                ws.write(i - 1, 0, i * 10)  # A1:A5 = 10..50
                ws.write(i - 1, 1, i * 5)  # B1:B5 = 5..25

            # Regular formulas
            ws.write_formula("C1", "=A1+B1", None, 15)
            ws.write_formula("E1", "=SUM(A1:A5)", None, 150)
            ws.write_formula("E2", "=AVERAGE(B1:B5)", None, 15)

            # CSE array formula (single-cell result)
            ws.write_array_formula("C2:C2", "=SUM(A1:A5*B1:B5)", None, 0)

            # Dynamic array formula (spills across D1:D5)
            ws.write_dynamic_array_formula("D1:D5", "=A1:A5*2")

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        # Regular formulas readable via openpyxl
        assert ws["C1"].value == "=A1+B1"
        assert ws["E1"].value == "=SUM(A1:A5)"
        assert ws["E2"].value == "=AVERAGE(B1:B5)"

        # Source data intact
        assert ws["A1"].value == 10
        assert ws["A5"].value == 50
        assert ws["B1"].value == 5

        # Verify XML formula elements
        import re

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            sheet_xml = zf.read("xl/worksheets/sheet1.xml").decode("utf-8")
            f_tags = re.findall(r"<f[^>]*>[^<]*</f>", sheet_xml)

            # Should have at least 5 formula tags total
            assert len(f_tags) >= 5

            # Array formulas: t="array" attribute present
            array_tags = [t for t in f_tags if 't="array"' in t]
            assert len(array_tags) >= 2  # CSE + dynamic

            # CSE array formula references single cell (C2)
            cse_tags = [t for t in array_tags if 'ref="C2"' in t]
            assert len(cse_tags) == 1
            assert "SUM(A1:A5*B1:B5)" in cse_tags[0]

            # Dynamic array formula references multi-cell range (D1:D5)
            dyn_tags = [t for t in array_tags if 'ref="D1:D5"' in t]
            assert len(dyn_tags) == 1
            assert "A1:A5*2" in dyn_tags[0]

            # Regular formulas: plain <f> without t= attribute
            plain_tags = [t for t in f_tags if 't="array"' not in t]
            assert len(plain_tags) >= 3

        wb_read.close()


# ============================================================
# 31. Data Validation with Messages and Cross-Sheet Formula
# ============================================================


class TestDataValidationMessages:
    """Tests for data validation with input/error messages and cross-sheet custom formula references."""

    def test_validation_messages_and_cross_sheet_formula(self):
        """Apply list validation sourced from another sheet with input/error messages, custom formula validation referencing another sheet with warning error style, and date validation with messages; verify all attributes via openpyxl."""

        def write_fn(wb):
            ws_data = wb.add_worksheet("Data")
            ws_valid = wb.add_worksheet("Validation")

            # Allowed values on Data sheet
            ws_data.write_column(0, 0, ["Red", "Green", "Blue", "Yellow"])
            ws_data.write(0, 1, 100)

            # List validation sourced from Data sheet with messages
            ws_valid.data_validation(
                "A1:A10",
                {
                    "validate": "list",
                    "source": "=Data!$A$1:$A$4",
                    "input_title": "Choose Color",
                    "input_message": "Select a color from the list",
                    "error_title": "Invalid Color",
                    "error_message": "Please pick Red, Green, Blue, or Yellow",
                },
            )

            # Custom formula validation referencing Data sheet
            ws_valid.data_validation(
                "B1:B10",
                {
                    "validate": "custom",
                    "value": "=AND(B1>=0,B1<=Data!$B$1)",
                    "input_title": "Enter Amount",
                    "input_message": "Value must be between 0 and the max on Data sheet",
                    "error_title": "Out of Range",
                    "error_message": "Value exceeds allowed maximum",
                    "error_type": "warning",
                },
            )

            # Date validation with messages
            ws_valid.data_validation(
                "C1:C10",
                {
                    "validate": "date",
                    "criteria": "between",
                    "minimum": "2024-01-01",
                    "maximum": "2024-12-31",
                    "input_title": "Enter Date",
                    "input_message": "Must be in year 2024",
                    "error_title": "Bad Date",
                    "error_message": "Date must be in 2024",
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read["Validation"]

        validations = ws.data_validations.dataValidation
        assert len(validations) == 3

        val_by_type = {}
        for v in validations:
            val_by_type[v.type] = v

        # List validation with messages
        assert "list" in val_by_type
        list_val = val_by_type["list"]
        assert list_val.promptTitle == "Choose Color"
        assert list_val.prompt == "Select a color from the list"
        assert list_val.errorTitle == "Invalid Color"
        assert list_val.error == "Please pick Red, Green, Blue, or Yellow"
        assert "Data!" in str(list_val.formula1)

        # Custom formula validation with warning error style
        assert "custom" in val_by_type
        custom_val = val_by_type["custom"]
        assert custom_val.promptTitle == "Enter Amount"
        assert custom_val.errorTitle == "Out of Range"
        assert "AND(B1>=0" in str(custom_val.formula1)
        assert custom_val.errorStyle == "warning"

        # Date validation with messages
        assert "date" in val_by_type
        date_val = val_by_type["date"]
        assert date_val.promptTitle == "Enter Date"
        assert date_val.errorTitle == "Bad Date"
        assert date_val.formula1 == "2024-01-01"
        assert date_val.formula2 == "2024-12-31"

        # Verify Data sheet
        ws_data = wb_read["Data"]
        assert ws_data["A1"].value == "Red"
        assert ws_data["A4"].value == "Yellow"
        assert ws_data["B1"].value == 100

        wb_read.close()


# ============================================================
# 32. Conditional Formatting with Formula
# ============================================================


class TestConditionalFormatFormula:
    """Tests for conditional formatting using formula-based rules."""

    def test_conditional_format_formula_type(self):
        """Apply a CF rule using type 'formula' with a criteria formula referencing
        AVERAGE, write data to the range, and verify via openpyxl that the CF rule
        exists with the correct formula and formatting."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            data = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
            for i, v in enumerate(data):
                ws.write(i, 0, v)

            fmt_hi = wb.add_format({"bg_color": "#FFFF00", "bold": True, "pattern": 1})
            ws.conditional_format(
                "A1:A10",
                {
                    "type": "formula",
                    "criteria": "=$A1>AVERAGE($A:$A)",
                    "format": fmt_hi,
                },
            )

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        # Verify data
        assert ws["A1"].value == 10
        assert ws["A10"].value == 100

        # Collect all CF rules
        cf_rules = list(ws.conditional_formatting)
        all_rules = []
        for cf in cf_rules:
            all_rules.extend(cf.rules)

        # Formula-based CF shows as "expression" in openpyxl
        expression_rules = [r for r in all_rules if r.type == "expression"]
        assert len(expression_rules) == 1

        rule = expression_rules[0]
        formula_text = rule.formula[0] if rule.formula else ""
        assert "AVERAGE" in formula_text
        assert "$A" in formula_text

        # Verify differential formatting has bold
        assert rule.dxf is not None
        assert rule.dxf.font is not None
        assert rule.dxf.font.bold is True

        wb_read.close()


# ============================================================
# 33. Sheet with 50+ Different Formats
# ============================================================


class TestManyFormats:
    """Tests for creating 50+ unique Format objects to exercise the shared styles system."""

    def test_fifty_plus_unique_formats(self):
        """Create 55 unique Format objects with different combinations of bold,
        italic, font_size, color, border, and num_format. Write one cell with each.
        Verify via openpyxl that the last 5 cells have their exact formatting
        properties, testing the format deduplication/shared styles system."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            colors = [
                "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF",
                "#00FFFF", "#800000", "#008000", "#000080", "#808000",
            ]
            num_fmts = ["0.00", "#,##0", "0%", "$#,##0.00", "0.000"]
            font_sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22]

            for i in range(55):
                props = {
                    "bold": (i % 3 == 0),
                    "italic": (i % 4 == 0),
                    "font_size": font_sizes[i % len(font_sizes)],
                    "font_color": colors[i % len(colors)],
                    "num_format": num_fmts[i % len(num_fmts)],
                }
                if i % 5 == 0:
                    props["border"] = 1
                if i % 7 == 0:
                    props["underline"] = True
                if i % 6 == 0:
                    props["bg_color"] = colors[(i + 3) % len(colors)]
                    props["pattern"] = 1
                fmt = wb.add_format(props)
                ws.write(i, 0, i * 1.5, fmt)

        wb_read = _create_and_read(write_fn)
        ws = wb_read.active

        colors = [
            "#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF",
            "#00FFFF", "#800000", "#008000", "#000080", "#808000",
        ]
        num_fmts = ["0.00", "#,##0", "0%", "$#,##0.00", "0.000"]
        font_sizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 22]

        # Verify last 5 cells (indices 50-54, 1-based rows 51-55)
        for idx in range(50, 55):
            row_1based = idx + 1
            cell = ws.cell(row=row_1based, column=1)
            assert cell.value is not None
            assert abs(cell.value - idx * 1.5) < 0.01

            expected_bold = (idx % 3 == 0)
            assert cell.font.bold == expected_bold

            expected_italic = (idx % 4 == 0)
            assert cell.font.italic == expected_italic

            expected_size = font_sizes[idx % len(font_sizes)]
            assert cell.font.size == expected_size

            expected_numfmt = num_fmts[idx % len(num_fmts)]
            assert cell.number_format == expected_numfmt

        # Verify total row count
        assert ws.cell(row=55, column=1).value is not None
        assert ws.cell(row=1, column=1).value is not None

        wb_read.close()


# ============================================================
# 35. Chart with Multiple Axis Formatting
# ============================================================


class TestChartAxisFormatting:
    """Tests for chart axis formatting: number format, min/max, logarithmic scale."""

    def test_chart_axis_numfmt_minmax_log(self):
        """Create a scatter chart with custom axis formatting: number format on both
        axes, min/max values set, logarithmic scale on the Y-axis. Verify via ZIP
        XML inspection that the axis elements have numFmt, logBase, min/max scaling
        attributes."""

        def write_fn(wb):
            ws = wb.add_worksheet()
            ws.write_row(0, 0, ["X", "Y"])
            data = [(1, 10), (2, 100), (5, 1000), (10, 10000), (20, 100000)]
            for i, (x, y) in enumerate(data):
                ws.write(i + 1, 0, x)
                ws.write(i + 1, 1, y)

            chart = wb.add_chart({"type": "scatter"})
            chart.add_series(
                {
                    "name": "=Sheet1!$B$1",
                    "categories": "=Sheet1!$A$2:$A$6",
                    "values": "=Sheet1!$B$2:$B$6",
                }
            )
            chart.set_title({"name": "Log Scale Chart"})
            chart.set_x_axis(
                {
                    "name": "X Values",
                    "num_format": "0.0",
                    "min": 0,
                    "max": 25,
                }
            )
            chart.set_y_axis(
                {
                    "name": "Y Values",
                    "num_format": "#,##0",
                    "log_base": 10,
                    "min": 1,
                    "max": 200000,
                }
            )
            ws.insert_chart("D2", chart)

        wb_read, raw = _create_and_read_raw(write_fn)
        ws = wb_read.active

        # Verify chart exists
        assert len(ws._charts) == 1

        # Verify data
        assert ws["A1"].value == "X"
        assert ws["B2"].value == 10
        assert ws["B6"].value == 100000

        # Verify axis attributes via XML
        import re

        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            chart_files = [
                n for n in zf.namelist() if "charts/chart" in n and n.endswith(".xml")
            ]
            assert len(chart_files) >= 1
            chart_xml = zf.read(chart_files[0]).decode("utf-8")

            # Number format on each axis must carry the configured formatCode (X="0.0", Y="#,##0"),
            # not merely a numFmt element of some shape.
            assert 'formatCode="0.0"' in chart_xml
            assert 'formatCode="#,##0"' in chart_xml

            # Logarithmic scale
            assert "logBase" in chart_xml
            log_match = re.search(r'logBase[^>]*val="(\d+)"', chart_xml)
            assert log_match is not None
            assert log_match.group(1) == "10"

            # Min/max scaling must carry the configured bounds (X min=0/max=25, Y min=1/max=200000),
            # not merely some present-but-arbitrary value.
            min_matches = re.findall(r"<c:min val=\"([^\"]+)\"", chart_xml)
            max_matches = re.findall(r"<c:max val=\"([^\"]+)\"", chart_xml)
            assert set(min_matches) == {"0", "1"}
            assert set(max_matches) == {"25", "200000"}

            # Axis titles
            assert "X Values" in chart_xml
            assert "Y Values" in chart_xml

        wb_read.close()
