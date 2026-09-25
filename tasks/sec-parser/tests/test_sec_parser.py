"""Behavioral tests for a sec-parser-style SEC EDGAR filing parser.

These tests exercise the library through its public top-level API only
(`import sec_parser as sp` -- the parsers, the semantic-element classes, the
tree builder, and `render`). They never import from internal modules.

The suite has two halves:

* **Focused tests** pin one distinct contract or boundary each (style
  thresholds, repetition thresholds, output options, tree/serialization APIs,
  error conditions).
* **Realistic-document tests** feed whole, messy, real-filing-style HTML
  documents through the parser and assert the *entire* resulting element stream
  (and, where relevant, the section tree). These fail as a unit if any single
  piece is classified or ordered wrongly -- so they reward reproducing the full
  pipeline, not isolated features.
"""

from __future__ import annotations

from pathlib import Path

import bs4
import pytest

import sec_parser as sp
from sec_parser import (
    AbstractNestingRule,
    AbstractProcessingStep,
    CompositeSemanticElement,
    Edgar10KParser,
    Edgar10QParser,
    EmptyElement,
    HtmlTag,
    ImageElement,
    PageHeaderElement,
    PageNumberElement,
    SecParserRuntimeError,
    SecParserValueError,
    SemanticTree,
    SupplementaryText,
    TableElement,
    TextElement,
    TitleElement,
    TopSectionTitle,
    TreeBuilder,
    TreeNode,
)

DATA_DIR = Path(__file__).parent.absolute()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def doc(body: str) -> str:
    """Wrap an HTML body fragment in a minimal document."""
    return f"<html><body>{body}</body></html>"


def kinds(elements) -> list[str]:
    """Reduce a list of elements to their class names."""
    return [type(e).__name__ for e in elements]


def detail(elements) -> list[tuple]:
    """Reduce elements to (class, level, section_identifier) triples."""
    out = []
    for e in elements:
        level = getattr(e, "level", None)
        section = getattr(getattr(e, "section_type", None), "identifier", None)
        out.append((type(e).__name__, level, section))
    return out


def count_type(elements, cls) -> int:
    return sum(1 for e in elements if isinstance(e, cls))


# ===========================================================================
# FOCUSED TESTS -- distinct contracts and boundaries
# ===========================================================================
def test_parse_output_options():
    """parse() keyword flags control the shape of the returned list.

    Irrelevant elements are dropped by default; composite containers are hidden
    unless requested (and then appear before their inner pieces); unwrapping can
    be turned off entirely.
    """
    html = doc(
        "<div><table><tr><td>A</td><td>1</td></tr>"
        "<tr><td>B</td><td>2</td></tr></table>"
        "<p>Explanatory text outside the table.</p></div>"
        "<p></p>"  # empty -> irrelevant
    )
    parser = Edgar10QParser()

    assert kinds(parser.parse(html)) == ["TableElement", "TextElement"]
    assert kinds(parser.parse(html, include_containers=True)) == [
        "CompositeSemanticElement",
        "TableElement",
        "TextElement",
    ]
    assert count_type(parser.parse(html, include_irrelevant_elements=True), EmptyElement) == 1
    not_unwrapped = parser.parse(html, unwrap_elements=False)
    assert count_type(not_unwrapped, CompositeSemanticElement) == 1
    assert count_type(not_unwrapped, TableElement) == 0


def test_top_section_ignores_out_of_order_duplicate():
    """A section already passed is not promoted again if it reappears."""
    html = doc(
        '<p style="font-weight:700">Part I</p>'
        '<p style="font-weight:700">Item 1. Financial Statements</p>'
        "<p>First occurrence body.</p>"
        '<p style="font-weight:700">Item 2. Management Discussion</p>'
        "<p>Body.</p>"
        '<p style="font-weight:700">Item 1. Financial Statements</p>'
        "<p>Duplicate occurrence body.</p>"
    )
    elements = Edgar10QParser().parse(html)
    sections = [e.section_type.identifier for e in elements if isinstance(e, TopSectionTitle)]
    assert sections == ["part1", "part1item1", "part1item2"]
    assert count_type(elements, TopSectionTitle) == 3
    assert any(isinstance(e, TitleElement) and "Item 1." in e.text for e in elements)


def test_highlight_style_boundaries_produce_titles():
    """Emphasis promotes a paragraph to a title; weak emphasis does not.

    Bold (font-weight 600+, or the keyword), italic, centered, underlined, and
    overwhelmingly-uppercase text all become titles; below-threshold weight and
    ordinary prose stay body text. Asserted as a unit.
    """
    parser = Edgar10QParser()

    def kind(style: str, text: str = "Heading Text Sample") -> str:
        return type(parser.parse(doc(f'<p style="{style}">{text}</p>'))[0]).__name__

    assert kind("font-weight:600") == "TitleElement"
    assert kind("font-weight:700") == "TitleElement"
    assert kind("font-weight:599") == "TextElement"
    assert kind("font-weight:400") == "TextElement"
    assert kind("font-weight:bold") == "TitleElement"
    assert kind("font-style:italic") == "TitleElement"
    assert kind("text-align:center") == "TitleElement"
    assert kind("text-decoration:underline") == "TitleElement"
    assert type(parser.parse(doc("<p>ALL UPPERCASE SECTION HEADING</p>"))[0]).__name__ == "TitleElement"
    assert type(parser.parse(doc("<p>Ordinary mixed case paragraph text.</p>"))[0]).__name__ == "TextElement"


def test_highlight_requires_majority_text_coverage():
    """A style only highlights when it covers most of the element's text."""
    parser = Edgar10QParser()
    minority = doc(
        '<p><span style="font-weight:700">Note:</span> '
        "the remainder of this paragraph is ordinary unstyled body text that "
        "clearly dominates the overall character count of the element.</p>"
    )
    assert type(parser.parse(minority)[0]).__name__ == "TextElement"
    majority = doc(
        '<p><span style="font-weight:700">This entire sentence is rendered in '
        "bold and dominates the paragraph.</span> ok</p>"
    )
    assert type(parser.parse(majority)[0]).__name__ == "TitleElement"


def test_page_number_detection_by_repetition():
    """Short numeric markers repeating five+ times become page numbers."""
    repeated = "".join(
        f"<p>Page {i}</p><p>Distinct body sentence number {chr(ord('a') + i)}.</p>"
        for i in range(6)
    )
    elements = Edgar10QParser().parse(doc(repeated), include_irrelevant_elements=True)
    assert count_type(elements, PageNumberElement) == 6

    few = "".join(
        f"<p>Page {i}</p><p>Distinct body sentence number {chr(ord('a') + i)}.</p>"
        for i in range(3)
    )
    assert count_type(
        Edgar10QParser().parse(doc(few), include_irrelevant_elements=True), PageNumberElement
    ) == 0


def test_table_classification_row_threshold():
    """A multi-row table becomes a TableElement; a single-row one does not."""
    multi = doc(
        "<table><tr><td>Asset</td><td>2023</td></tr>"
        "<tr><td>Cash</td><td>100</td></tr>"
        "<tr><td>Debt</td><td>50</td></tr></table>"
    )
    assert kinds(Edgar10QParser().parse(multi)) == ["TableElement"]
    single = doc("<table><tr><td>Only</td><td>Row</td></tr></table>")
    assert count_type(Edgar10QParser().parse(single), TableElement) == 0


def test_table_of_contents_classification():
    """A table with a 'Page' header cell is recognised as a table of contents."""
    html = doc(
        "<table>"
        "<tr><td>Item</td><td>Page</td></tr>"
        "<tr><td>Item 1. Financial Statements</td><td>3</td></tr>"
        "<tr><td>Item 2. Other</td><td>15</td></tr>"
        "</table>"
    )
    assert kinds(Edgar10QParser().parse(html)) == ["TableOfContentsElement"]


def test_empty_and_image_classification():
    """Empty tags, standalone images, and image+text mixes are handled."""
    empty = Edgar10QParser().parse(doc("<p></p>"), include_irrelevant_elements=True)
    assert count_type(empty, EmptyElement) == 1
    assert kinds(Edgar10QParser().parse(doc('<img src="chart.png"/>'))) == ["ImageElement"]
    mixed = Edgar10QParser().parse(doc('<p><img src="chart.png"/>Figure caption text.</p>'))
    assert kinds(mixed) == ["ImageElement", "TextElement"]


def test_adjacent_text_elements_merge():
    """Adjacent body paragraphs merge; a heading between runs separates them."""
    merged = Edgar10QParser().parse(
        doc("<p>First sentence fragment.</p><p>Second sentence fragment.</p><p>Third.</p>")
    )
    assert count_type(merged, TextElement) == 1

    split = Edgar10QParser().parse(
        doc(
            "<p>First body run sentence one.</p><p>First body run sentence two.</p>"
            '<p style="font-weight:700">A Bold Heading Between</p>'
            "<p>Second body run sentence one.</p><p>Second body run sentence two.</p>"
        )
    )
    assert count_type(split, TextElement) == 2
    assert count_type(split, TitleElement) == 1


def test_tree_node_reparenting_keeps_structure_consistent():
    """Re-parenting a node detaches it from its previous parent automatically."""
    root_a = TreeNode(Edgar10QParser().parse(doc("<p>alpha node text.</p>"))[0])
    root_b = TreeNode(Edgar10QParser().parse(doc("<p>beta node text.</p>"))[0])
    child = TreeNode(Edgar10QParser().parse(doc("<p>child node text.</p>"))[0])

    root_a.add_child(child)
    assert child.parent is root_a
    assert len(root_a.children) == 1

    child.parent = root_b
    assert child.parent is root_b
    assert len(root_b.children) == 1
    assert len(root_a.children) == 0
    assert [n is child for n in root_b.get_descendants()] == [True]


def test_render_outputs_readable_tree():
    """Plain render shows 'Type: text' per node; ignored_types omits them."""
    html = doc('<p style="font-weight:700">Section A Title</p><p>Body text under A.</p>')
    tree = TreeBuilder().build(Edgar10QParser().parse(html))

    rendered = tree.render(pretty=False)
    assert "TitleElement: Section A Title" in rendered
    assert "TextElement: Body text under A." in rendered

    filtered = tree.render(pretty=False, ignored_types=(TextElement,))
    assert "TitleElement: Section A Title" in filtered
    assert "TextElement" not in filtered


def test_table_to_markdown_and_summary():
    """A table element renders as Markdown rows and a row-count summary."""
    html = doc(
        "<table><tr><td>Asset</td><td>2023</td></tr>"
        "<tr><td>Cash</td><td>100</td></tr>"
        "<tr><td>Debt</td><td>50</td></tr></table>"
    )
    table = Edgar10QParser().parse(html)[0]
    assert isinstance(table, TableElement)
    markdown = table.table_to_markdown()
    for token in ("Asset", "2023", "Cash", "100", "Debt", "50"):
        assert token in markdown
    assert markdown.count("\n") == 2  # three rows, no separator line
    assert "3 rows" in table.get_summary()


def test_element_text_and_serialization():
    """to_dict() carries class name plus type-specific level/section/text."""
    html = doc(
        '<p style="font-weight:700">Part I</p>'
        '<p style="font-weight:700">A Plain Heading</p>'
        "<p>Ordinary body paragraph content.</p>"
    )
    by_type = {type(e).__name__: e for e in Edgar10QParser().parse(html)}

    top = by_type["TopSectionTitle"]
    assert top.text == "Part I"
    top_dict = top.to_dict(include_contents=True)
    assert top_dict["cls_name"] == "TopSectionTitle"
    assert top_dict["section_type"] == "part1"
    assert top_dict["text_content"] == "Part I"

    title_dict = by_type["TitleElement"].to_dict(include_contents=True)
    assert title_dict["cls_name"] == "TitleElement"
    assert title_dict["level"] == 0
    assert title_dict["text_content"] == "A Plain Heading"

    text = by_type["TextElement"]
    assert text.text == "Ordinary body paragraph content."
    assert text.to_dict(include_contents=True)["text_content"] == "Ordinary body paragraph content."


def test_documented_error_conditions():
    """The library raises its documented exception types on invalid use."""
    with pytest.raises(TypeError):
        HtmlTag(12345)

    with pytest.raises(SecParserValueError):
        CompositeSemanticElement(HtmlTag(bs4.Tag(name="div")), inner_elements=None)

    leveled_tag = bs4.Tag(name="p")
    leveled_tag.string = "heading"
    with pytest.raises(SecParserValueError):
        TitleElement(HtmlTag(leveled_tag), level=-1)


# ===========================================================================
# REALISTIC-DOCUMENT TESTS -- whole messy filings, asserted end to end
# ===========================================================================
def test_real_filing_snippet():
    """A real SEC filing paragraph (messy markup) parses to one text element.

    Uses an authentic excerpt from an Alcoa 10-Q: uppercase tags, a leading
    bold label, <FONT> wrappers, and HTML entities. The bold label covers only a
    small fraction of the text, so the whole thing is body text, not a title.
    """
    html = (DATA_DIR / "real_10q_snippet.html").read_text()
    elements = Edgar10QParser().parse(html)
    assert kinds(elements) == ["TextElement"]
    text = elements[0].text
    assert text.startswith("D. Restructuring and Other Charges")
    assert text.endswith("miscellaneous items.")


def _page(n: int, body: str) -> str:
    return (
        '<p style="text-align:center; font-size:8pt">ALCOA CORPORATION FORM 10-Q</p>'
        + body
        + f'<p style="text-align:center">- {n} -</p>'
    )


REALISTIC_10Q = (
    "<html><body>"
    + _page(
        1,
        '<P STYLE="font-weight:bold; text-align:center; font-size:11pt">PART I &#150; FINANCIAL INFORMATION</P>'
        '<P STYLE="font-weight:bold">Item 1. Financial Statements</P>'
        '<P STYLE="font-family:Times">(In millions, except per-share amounts)</P>'
        "<table><tr><td>Net sales</td><td>$3,090</td></tr><tr><td>Cost of goods</td><td>$2,500</td></tr></table>"
        "<P><B>Note A</B> &#150; Basis of presentation. The accompanying financial statements are unaudited.</P>",
    )
    + _page(
        2,
        '<P STYLE="font-weight:700">Item 2. Management&#146;s Discussion and Analysis</P>'
        '<P STYLE="font-style:italic">Overview</P>'
        "<P>Our results for the quarter reflected higher aluminum prices and stable demand.</P>"
        "<P>See accompanying Notes to Condensed Consolidated Financial Statements.</P>",
    )
    + _page(
        3,
        '<P STYLE="font-weight:700">Item 3. Quantitative and Qualitative Disclosures About Market Risk</P>'
        "<P>There were no material changes to our market risk during the quarter.</P>",
    )
    + _page(4, "<P>Filler content paragraph alpha for pagination.</P>")
    + _page(5, "<P>Filler content paragraph beta for pagination.</P>")
    + _page(6, "<P>Filler content paragraph gamma for pagination.</P>")
    + "</body></html>"
)


def test_recurring_page_header_and_introductory_section():
    """A line recurring atop each page is a page header; pre-Part I matter is intro.

    The running header appears once before Part I (classified as an
    introductory-section element) and as a page header on every page after that.
    (Page numbers are covered separately.)
    """
    elements = Edgar10QParser().parse(REALISTIC_10Q, include_irrelevant_elements=True)
    assert count_type(elements, PageHeaderElement) == 5
    assert sum(1 for e in elements if type(e).__name__ == "IntroductorySectionElement") == 1


REALISTIC_10K = """<html><body>
<P STYLE="font-weight:bold; text-align:center">PART I</P>
<P STYLE="font-weight:bold">Item 1. Business</P>
<P>The Company is a leading producer of beverages sold worldwide.</P>
<P STYLE="font-weight:bold">Item 1A. Risk Factors</P>
<P><FONT STYLE="font-style:italic">Risks Related to Our Business</FONT></P>
<P>Our business is subject to numerous risks and uncertainties.</P>
<P STYLE="font-weight:bold; text-align:center">PART II</P>
<P STYLE="font-weight:bold">Item 7. Management&#146;s Discussion and Analysis</P>
<P>Net revenues increased compared to the prior year.</P>
<P STYLE="font-weight:bold">Item 8. Financial Statements and Supplementary Data</P>
<table><tr><td>Revenue</td><td>$10,000</td></tr><tr><td>Operating income</td><td>$2,000</td></tr></table>
</body></html>"""


def test_realistic_10k_section_sequence():
    """A 10-K resolves item numbers against the 10-K section scheme.

    Items are scoped to the most recent Part, so "Item 7"/"Item 8" under Part II
    map to part2item7/part2item8 -- a different taxonomy from the 10-Q parser.
    """
    elements = Edgar10KParser().parse(REALISTIC_10K)
    assert detail(elements) == [
        ("TopSectionTitle", 0, "part1"),
        ("TopSectionTitle", 1, "part1item1"),
        ("TextElement", None, None),
        ("TopSectionTitle", 1, "part1item1a"),
        ("TitleElement", 0, None),
        ("TextElement", None, None),
        ("TopSectionTitle", 0, "part2"),
        ("TopSectionTitle", 1, "part2item7"),
        ("TextElement", None, None),
        ("TopSectionTitle", 1, "part2item8"),
        ("TableElement", None, None),
    ]


REALISTIC_COMPOSITE = """<html><body>
<div>
  <table><tr><td>X</td><td>1</td></tr><tr><td>Y</td><td>2</td></tr></table>
  <p>Caption under the first table.</p>
  <div><img src="logo.png"/>Figure 1: company logo and tagline.</div>
</div>
<div>
  <table><tr><td>A</td><td>9</td></tr><tr><td>B</td><td>8</td></tr></table>
  <table><tr><td>C</td><td>7</td></tr><tr><td>D</td><td>6</td></tr></table>
</div>
</body></html>"""


def test_nested_composite_recursion():
    """Nested mixed-content containers split recursively, containers first."""
    with_containers = Edgar10QParser().parse(REALISTIC_COMPOSITE, include_containers=True)
    assert kinds(with_containers) == [
        "CompositeSemanticElement",  # outer div 1
        "TableElement",
        "TextElement",
        "CompositeSemanticElement",  # inner div (image + text)
        "ImageElement",
        "TextElement",
        "CompositeSemanticElement",  # div 2 (two tables)
        "TableElement",
        "TableElement",
    ]
    flat = Edgar10QParser().parse(REALISTIC_COMPOSITE)
    assert kinds(flat) == [
        "TableElement",
        "TextElement",
        "ImageElement",
        "TextElement",
        "TableElement",
        "TableElement",
    ]


REALISTIC_PRECEDENCE = """<html><body>
<P STYLE="text-align:center; font-weight:bold">PART II &#150; OTHER INFORMATION</P>
<P STYLE="font-weight:bold">Item 1. Legal Proceedings</P>
<P>(Dollars in thousands, unless otherwise noted)</P>
<P>The Company is party to various legal proceedings.</P>
<P STYLE="font-style:italic">We believe the outcome will not be material.</P>
<P>See accompanying Notes to Condensed Consolidated Financial Statements.</P>
<P STYLE="font-weight:bold">Item 1A. Risk Factors</P>
<P>There have been no material changes to our risk factors.</P>
</body></html>"""


def test_supplementary_and_section_precedence():
    """Section headings win over emphasis; the three supplementary cues all fire."""
    elements = Edgar10QParser().parse(REALISTIC_PRECEDENCE)
    assert detail(elements) == [
        ("TopSectionTitle", 0, "part2"),  # centered+bold+caps, but it's a section
        ("TopSectionTitle", 1, "part2item1"),
        ("SupplementaryText", None, None),  # parenthetical qualifier
        ("TextElement", None, None),
        ("SupplementaryText", None, None),  # italic ending in a period
        ("SupplementaryText", None, None),  # accompanying-notes pointer
        ("TopSectionTitle", 1, "part2item1a"),
        ("TextElement", None, None),
    ]


# ===========================================================================
# TREE-NESTING BATTERY -- full tree shapes
# ===========================================================================
def tree_shape(node):
    """Serialize a node to nested tuples: (label, [children]) or just label."""
    e = node.semantic_element
    label = type(e).__name__
    level = getattr(e, "level", None)
    if level is not None:
        label += f"#{level}"
    section = getattr(getattr(e, "section_type", None), "identifier", None)
    if section:
        label += f"<{section}>"
    children = [tree_shape(c) for c in node.children]
    return (label, children) if children else label


def test_tree_deep_section_and_title_hierarchy():
    """Sub-titles and body nest under their item; items nest under their part."""
    html = doc(
        '<p style="font-weight:bold; text-align:center">Part I</p>'
        '<p style="font-weight:bold">Item 1. Financial Statements</p>'
        '<p style="font-style:italic">Balance Sheets</p>'
        "<p>Assets line.</p>"
        '<p style="font-style:italic">Income Statements</p>'
        "<p>Revenue line.</p>"
        '<p style="font-weight:bold">Item 2. MD&amp;A</p>'
        "<p>Discussion.</p>"
    )
    roots = list(TreeBuilder().build(Edgar10QParser().parse(html)))
    assert len(roots) == 1
    assert tree_shape(roots[0]) == (
        "TopSectionTitle#0<part1>",
        [
            (
                "TopSectionTitle#1<part1item1>",
                [
                    ("TitleElement#0", ["TextElement"]),
                    ("TitleElement#0", ["TextElement"]),
                ],
            ),
            ("TopSectionTitle#1<part1item2>", ["TextElement"]),
        ],
    )


def test_tree_title_level_nesting():
    """Same-kind titles nest by level; a higher-rank title closes lower ones."""
    html = doc(
        '<p style="font-weight:bold; font-size:16pt">Big Heading</p>'
        '<p style="font-style:italic">Italic Sub</p>'
        '<p style="text-decoration:underline">Underline SubSub</p>'
        "<p>Body under subsub.</p>"
        '<p style="font-style:italic">Another Italic Sub</p>'
        "<p>Body under second sub.</p>"
    )
    roots = list(TreeBuilder().build(Edgar10QParser().parse(html)))
    assert len(roots) == 1
    assert tree_shape(roots[0]) == (
        "TitleElement#0",
        [
            ("TitleElement#1", [("TitleElement#2", ["TextElement"])]),
            ("TitleElement#1", ["TextElement"]),
        ],
    )


# ===========================================================================
# HEADING-LEVEL BATTERY -- which signals define a "style"
# ===========================================================================
def test_heading_level_assignment():
    """Heading levels follow first-appearance order of distinct emphasis styles.

    New styles get increasing levels in the order they first appear; a repeated
    style reuses its level; and headings that differ only by font size or color
    (not by an emphasis signal) count as the same style. Here bold (18pt / 10pt /
    red) is one style -> level 0, italic -> 1, centered -> 2, underlined -> 3.
    """
    html = doc(
        '<p style="font-weight:bold; font-size:18pt">Bold Big</p>'
        '<p style="font-weight:bold; font-size:10pt">Bold Small</p>'
        '<p style="font-style:italic">Italic One</p>'
        '<p style="text-align:center">Centered One</p>'
        '<p style="font-style:italic">Italic Two</p>'
        '<p style="font-weight:bold; color:red">Bold Red</p>'
        '<p style="text-decoration:underline">Underline One</p>'
    )
    elements = Edgar10QParser().parse(html)
    assert all(isinstance(e, TitleElement) for e in elements)
    assert [e.level for e in elements] == [0, 0, 1, 2, 1, 0, 3]


# ===========================================================================
# EXTENSIBILITY -- custom pipeline steps and nesting rules
# ===========================================================================
class _ForceTextStep(AbstractProcessingStep):
    """A custom step that rewrites every element as a plain TextElement."""

    def _process(self, elements):
        return [TextElement(e.html_tag) for e in elements]


def test_custom_processing_step_replaces_pipeline():
    """A caller-supplied get_steps replaces the default pipeline.

    With the custom single-step pipeline, a bold heading is no longer a title --
    every element comes out as plain text. A step instance is also single-use:
    running it twice raises a runtime error.
    """
    html = doc('<p style="font-weight:bold">Bold Heading</p><p>Body paragraph.</p>')
    assert kinds(Edgar10QParser().parse(html)) == ["TitleElement", "TextElement"]
    custom = Edgar10QParser(get_steps=lambda: [_ForceTextStep()])
    assert kinds(custom.parse(html)) == ["TextElement", "TextElement"]

    step = _ForceTextStep()
    step.process([])
    with pytest.raises(SecParserRuntimeError):
        step.process([])


class _NestEverythingRule(AbstractNestingRule):
    """A custom rule that nests every element under the preceding one."""

    def _should_be_nested_under(self, parent, child):
        return True


def test_custom_nesting_rule_replaces_defaults():
    """A caller-supplied get_rules changes how the tree is built.

    Three equally-ranked (same-style) titles are siblings under the default
    rules, but the custom 'nest everything' rule chains them into a single
    descending branch.
    """
    elements = Edgar10QParser().parse(
        doc(
            '<p style="font-weight:bold">Alpha</p>'
            '<p style="font-weight:bold">Beta</p>'
            '<p style="font-weight:bold">Gamma</p>'
        )
    )
    assert [e.level for e in elements] == [0, 0, 0]

    default_roots = list(TreeBuilder().build(elements))
    assert len(default_roots) == 3  # siblings

    custom = TreeBuilder(get_rules=lambda: [_NestEverythingRule()]).build(elements)
    assert tree_shape(list(custom)[0]) == (
        "TitleElement#0",
        [("TitleElement#0", ["TitleElement#0"])],
    )


# ===========================================================================
# CLASSIFICATION PRECEDENCE -- order wins when a line fits multiple categories
# ===========================================================================
def test_classification_precedence():
    """When a line matches several rules, the documented precedence decides.

    Supplementary cues beat page furniture (a repeated parenthetical and a
    repeated italic note stay supplementary); page furniture beats plain emphasis
    (a repeated centered header is a page header, not a title).
    """
    parser = Edgar10QParser()

    paren = parser.parse(doc("<p>(In millions of dollars)</p>" * 6), include_irrelevant_elements=True)
    assert count_type(paren, SupplementaryText) == 6
    assert count_type(paren, PageHeaderElement) == 0
    assert count_type(paren, PageNumberElement) == 0

    italic = parser.parse(
        doc('<p style="font-style:italic">See the notes below.</p>' * 6),
        include_irrelevant_elements=True,
    )
    assert count_type(italic, SupplementaryText) == 6

    centered = parser.parse(
        doc('<p style="text-align:center">QUARTERLY REPORT HEADER</p>' * 6),
        include_irrelevant_elements=True,
    )
    assert count_type(centered, PageHeaderElement) == 6
    assert count_type(centered, TitleElement) == 0


# ===========================================================================
# MESSY TABLE -- realistic financial table content
# ===========================================================================
def test_messy_table_markdown_and_metrics():
    """A realistic table with currency, percent, and empty cells parses cleanly.

    It is a single table element; its summary reports the row count and its
    markdown has one line per row carrying the visible cell content.
    """
    html = doc(
        "<table>"
        "<tr><td>Segment</td><td></td><td>2023</td><td>2022</td></tr>"
        "<tr><td>Americas</td><td>$</td><td>1,200</td><td>1,050</td></tr>"
        "<tr><td>Europe</td><td>$</td><td>800</td><td>760</td></tr>"
        "<tr><td>Margin</td><td></td><td>12%</td><td>11%</td></tr>"
        "</table>"
    )
    elements = Edgar10QParser().parse(html)
    assert kinds(elements) == ["TableElement"]
    assert "4 rows" in elements[0].get_summary()

    markdown = elements[0].table_to_markdown()
    assert markdown.count("\n") == 3  # four rows
    for token in ("Segment", "Americas", "Europe", "Margin", "12%", "$"):
        assert token in markdown


# ===========================================================================
# INTEGRATION -- a whole filing through the full pipeline
# ===========================================================================
INTEGRATION_FILING = doc(
    "<p>Cover page. Forward-looking statements disclaimer.</p>"
    '<p style="font-weight:bold; text-align:center">PART I — FINANCIAL INFORMATION</p>'
    '<p style="font-weight:bold">Item 1. Financial Statements</p>'
    "<p>(In millions, except per share data)</p>"
    "<table><tr><td>Revenue</td><td>$500</td></tr><tr><td>Net income</td><td>$80</td></tr></table>"
    "<div><table><tr><td>Asset</td><td>1</td></tr><tr><td>Cash</td><td>2</td></tr></table>"
    "<p>Notes to the table above.</p></div>"
    "<p>RUNNING HEADER LINE</p><p>- 1 -</p>"
    '<p style="font-weight:bold">Item 2. Management Discussion</p>'
    '<p style="font-style:italic">Overview</p>'
    "<p>Revenue grew this quarter.</p>"
    "<p>See accompanying Notes to Condensed Consolidated Financial Statements.</p>"
    "<p>RUNNING HEADER LINE</p><p>- 2 -</p>"
    "<p>RUNNING HEADER LINE</p><p>- 3 -</p>"
    "<p>RUNNING HEADER LINE</p><p>- 4 -</p>"
    "<p>RUNNING HEADER LINE</p><p>- 5 -</p>"
    "<p>RUNNING HEADER LINE</p><p>- 6 -</p>"
)


def test_full_filing_integration():
    """A whole filing composes end to end into the right content stream.

    Sections, supplementary text, a table, a composite (table + notes) split, a
    sub-heading, and body text survive; the cover page, repeated running headers,
    and page numbers are all dropped as introductory/irrelevant furniture.
    """
    elements = Edgar10QParser().parse(INTEGRATION_FILING)
    assert detail(elements) == [
        ("TopSectionTitle", 0, "part1"),
        ("TopSectionTitle", 1, "part1item1"),
        ("SupplementaryText", None, None),
        ("TableElement", None, None),
        ("TableElement", None, None),
        ("TextElement", None, None),
        ("TopSectionTitle", 1, "part1item2"),
        ("TitleElement", 0, None),
        ("TextElement", None, None),
        ("SupplementaryText", None, None),
    ]


def test_element_preview_serialization():
    """include_previews=True adds tag name, a truncated HTML preview, and a hash.

    The preview shortens long content to first-20 + '...[omitted]...' + last-20;
    a TableElement additionally carries a metrics dict. None of these appear in
    the default (preview-less) dict.
    """
    parser = Edgar10QParser()
    txt = (
        "This is a long paragraph of body text that clearly exceeds "
        "forty characters in length."
    )
    para = parser.parse(doc(f"<p>{txt}</p>"))[0]

    previewed = para.to_dict(include_previews=True)
    assert previewed["tag_name"] == "p"
    assert "html_hash" in previewed
    assert previewed["html_preview"] == txt[:20] + f"...[{len(txt) - 40}]..." + txt[-20:]

    plain = para.to_dict()
    assert "tag_name" not in plain
    assert "html_preview" not in plain

    table = parser.parse(
        doc("<table><tr><td>A</td><td>1</td></tr><tr><td>B</td><td>2</td></tr></table>")
    )[0]
    table_previewed = table.to_dict(include_previews=True)
    assert table_previewed["tag_name"] == "table"
    assert table_previewed["metrics"]["rows"] == 2
    assert "html_preview" in table_previewed and "html_hash" in table_previewed
    assert "metrics" not in table.to_dict()
