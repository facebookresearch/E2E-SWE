"""Hidden grading suite for the html2markdown task.

Drives the compiled html2markdown CLI (built by setup.sh at /app/html2markdown) via subprocess:
argv + stdin in, stdout/stderr/exit-code out. Each test asserts a distinct behavioral contract
with EXACT expected values. Set BIN_ENV to point at the binary for local iteration:
  BIN_ENV=/tmp/html2markdown pytest tests/test_html2markdown.py -q
"""

import os
import subprocess

BIN = os.environ.get("BIN_ENV", "/app/html2markdown")


def run(argv, stdin=""):
    p = subprocess.run(
        [BIN, *argv], input=stdin, capture_output=True, text=True, timeout=20
    )
    return p.stdout, p.stderr, p.returncode


def conv(html, flags):
    so, se, rc = run(flags, stdin=html)
    assert rc == 0, f"expected rc 0, got {rc}, stderr={se!r}"
    return so


def test_p_basic():
    assert conv("<p>Hello world</p>", []) == "Hello world\n"


def test_headings_all_levels():
    assert (
        conv("<h1>A</h1><h2>B</h2><h3>C</h3><h4>D</h4><h5>E</h5><h6>F</h6>", [])
        == "# A\n\n## B\n\n### C\n\n#### D\n\n##### E\n\n###### F\n"
    )


def test_heading_inline_children():
    assert (
        conv("<h2>Big <em>emph</em> and <code>c</code></h2>", [])
        == "## Big *emph* and `c`\n"
    )


def test_hr_alone():
    assert conv("<hr>", []) == "* * *\n"


def test_hr_between_paragraphs():
    assert conv("<p>a</p><hr><p>b</p>", []) == "a\n\n* * *\n\nb\n"


def test_div_contributes_children():
    assert conv("<div><p>one</p><p>two</p></div>", []) == "one\n\ntwo\n"


def test_span_inline_wrapper():
    assert conv("<p>a<span>b</span>c</p>", []) == "abc\n"


def test_comment_removed():
    assert conv("<p>a</p><!-- hidden --><p>b</p>", []) == "a\n\nb\n"


def test_empty_paragraph_skipped():
    assert conv("<p></p><p>text</p>", []) == "text\n"


def test_multi_block_document():
    assert (
        conv(
            "<h1>T</h1><p>para</p><blockquote>q</blockquote><pre><code>code</code></pre>",
            [],
        )
        == "# T\n\npara\n\n> q\n\n```\ncode\n```\n"
    )


def test_head_ignored():
    assert conv("<head><title>X</title></head><body><p>body</p></body>", []) == "body\n"


def test_entities_named():
    assert (
        conv("<p>&lt;tag&gt; &amp; &copy; &#39;q&#39;</p>", [])
        == "&lt;tag&gt; & © 'q'\n"
    )


def test_entities_decimal_hex():
    assert conv("<p>&#65; &#x42; &amp;</p>", []) == "A B &\n"


def test_amp_literal_not_reencoded():
    assert conv("<p>a &amp; b and raw &amp; sign</p>", []) == "a & b and raw & sign\n"


def test_lt_gt_always_reencoded():
    assert (
        conv("<p>less &lt; and raw &gt; sign</p>", [])
        == "less &lt; and raw &gt; sign\n"
    )


def test_whitespace_collapse():
    assert conv("<p>a    b\tc\n   d</p>", []) == "a b c d\n"


def test_whitespace_trim():
    assert conv("<p>  leading and trailing  </p>", []) == "leading and trailing\n"


def test_nbsp_interior_preserved():
    assert conv("<p>a&nbsp;&nbsp;b</p>", []) == "a\xa0\xa0b\n"


def test_nbsp_edge_trimmed():
    assert conv("<p>&nbsp; x &nbsp;</p>", []) == "x\n"


def test_em_basic():
    assert conv("<p><em>italic</em> and <i>also</i></p>", []) == "*italic* and *also*\n"


def test_strong_basic():
    assert (
        conv("<p><strong>bold</strong> and <b>also</b></p>", [])
        == "**bold** and **also**\n"
    )


def test_strong_delimiter_underscore():
    assert (
        conv(
            "<p><strong>x</strong> and <em>y</em></p>", ["--opt-strong-delimiter", "__"]
        )
        == "__x__ and *y*\n"
    )


def test_em_strong_nested():
    assert (
        conv("<p><strong>bold <em>and italic</em></strong></p>", [])
        == "**bold *and italic***\n"
    )


def test_code_inline_basic():
    assert (
        conv("<p>use <code>fmt.Println</code> now</p>", []) == "use `fmt.Println` now\n"
    )


def test_code_inline_with_backtick():
    assert conv("<p>call <code>a`b</code> now</p>", []) == "call ``a`b`` now\n"


def test_code_block_basic():
    assert conv("<pre><code>a := 1</code></pre>", []) == "```\na := 1\n```\n"


def test_code_block_multiline():
    assert (
        conv("<pre><code>line1\nline2\n  indented</code></pre>", [])
        == "```\nline1\nline2\n  indented\n```\n"
    )


def test_code_fence_backtick_count():
    assert (
        conv("<pre><code>has ``` triple ticks</code></pre>", [])
        == "````\nhas ``` triple ticks\n````\n"
    )


def test_code_block_language_class():
    assert (
        conv('<pre><code class="language-go">x := 1</code></pre>', [])
        == "```go\nx := 1\n```\n"
    )


def test_pre_without_code():
    assert conv("<pre>raw   text\nline2</pre>", []) == "```\nraw   text\nline2\n```\n"


def test_ul_basic():
    assert conv("<ul><li>a</li><li>b</li></ul>", []) == "- a\n- b\n"


def test_ol_basic():
    assert conv("<ol><li>one</li><li>two</li></ol>", []) == "1. one\n2. two\n"


def test_ol_start_attribute():
    assert (
        conv('<ol start="5"><li>five</li><li>six</li></ol>', []) == "5. five\n6. six\n"
    )


def test_list_nested_ul():
    assert (
        conv("<ul><li>a<ul><li>b</li><li>c</li></ul></li><li>d</li></ul>", [])
        == "- a\n  \n  - b\n  - c\n- d\n"
    )


def test_list_mixed_ol_ul():
    assert (
        conv("<ol><li>one<ul><li>bullet</li></ul></li><li>two</li></ol>", [])
        == "1. one\n   \n   - bullet\n2. two\n"
    )


def test_list_deep_nesting():
    assert (
        conv("<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li></ul>", [])
        == "- a\n  \n  - b\n    \n    - c\n"
    )


def test_list_item_multi_para():
    assert (
        conv("<ul><li><p>first</p><p>second</p></li><li>next</li></ul>", [])
        == "- first\n  \n  second\n- next\n"
    )


def test_list_item_inline_formatting():
    assert (
        conv("<ul><li>plain <strong>bold</strong> <code>c</code></li></ul>", [])
        == "- plain **bold** `c`\n"
    )


def test_link_basic():
    assert conv('<p><a href="/foo">bar</a></p>', []) == "[bar](/foo)\n"


def test_link_with_title():
    assert (
        conv('<p><a href="/x" title="hi there">y</a></p>', []) == '[y](/x "hi there")\n'
    )


def test_link_relative_domain():
    assert (
        conv('<p><a href="/foo/bar">go</a></p>', ["--domain", "https://example.com"])
        == "[go](https://example.com/foo/bar)\n"
    )


def test_link_absolute_domain_unchanged():
    assert (
        conv(
            '<p><a href="https://other.com/p">o</a></p>',
            ["--domain", "https://example.com"],
        )
        == "[o](https://other.com/p)\n"
    )


def test_link_text_needs_escape():
    assert conv('<p><a href="/x">a_b*c</a></p>', []) == "[a\\_b\\*c](/x)\n"


def test_link_in_bold():
    assert (
        conv('<p><strong><a href="/x">link</a></strong></p>', []) == "[**link**](/x)\n"
    )


def test_link_autolink_style():
    assert (
        conv('<p>visit <a href="https://x.com">https://x.com</a></p>', [])
        == "visit [https://x.com](https://x.com)\n"
    )


def test_image_basic():
    assert conv('<p><img src="/a.png" alt="cat"></p>', []) == "![cat](/a.png)\n"


def test_image_alt_title():
    assert (
        conv('<p><img src="/a.png" alt="a cat" title="tip"></p>', [])
        == '![a cat](/a.png "tip")\n'
    )


def test_image_no_alt():
    assert conv('<p><img src="/a.png"></p>', []) == "![](/a.png)\n"


def test_image_in_link():
    assert (
        conv('<a href="/p"><img src="/i.png" alt="pic"></a>', [])
        == "[![pic](/i.png)](/p)\n"
    )


def test_image_relative_domain():
    assert (
        conv(
            '<p><img src="/i.png" alt="x"></p>', ["--domain", "https://cdn.example.com"]
        )
        == "![x](https://cdn.example.com/i.png)\n"
    )


def test_break_hard():
    assert conv("<p>line1<br>line2</p>", []) == "line1  \nline2\n"


def test_blockquote_basic():
    assert conv("<blockquote>quoted text</blockquote>", []) == "> quoted text\n"


def test_blockquote_nested():
    assert (
        conv("<blockquote>outer<blockquote>inner</blockquote></blockquote>", [])
        == "> outer\n> \n> > inner\n"
    )


def test_blockquote_multi_para():
    assert (
        conv("<blockquote><p>one</p><p>two</p></blockquote>", [])
        == "> one\n> \n> two\n"
    )


def test_escape_fake_vs_real_bold():
    assert (
        conv("<p>fake **bold** and real <strong>bold</strong></p>", [])
        == "fake \\*\\*bold\\** and real **bold**\n"
    )


def test_escape_emphasis_delims_open_only():
    assert (
        conv("<p>Some _under_ and *star* text</p>", [])
        == "Some \\_under_ and \\*star* text\n"
    )


def test_escape_intraword_underscore():
    assert (
        conv("<p>a.b_c and snake_case_word</p>", [])
        == "a.b\\_c and snake\\_case\\_word\n"
    )


def test_escape_url_underscores():
    assert (
        conv("<p>see http://x.com/a_b_c now</p>", [])
        == "see http://x.com/a\\_b\\_c now\n"
    )


def test_escape_leading_unordered_markers():
    # A leading '-', '+', or '*' followed by a space is escaped as an unordered-list marker.
    assert conv("<p>- not a list item</p>", []) == "\\- not a list item\n"
    assert conv("<p>+ item</p>", []) == "\\+ item\n"
    assert conv("<p>* item</p>", []) == "\\* item\n"


def test_escape_leading_hash():
    assert conv("<p># not a heading</p>", []) == "\\# not a heading\n"


def test_escape_leading_ordered():
    assert conv("<p>1. not an ordered list</p>", []) == "1\\. not an ordered list\n"


def test_escape_leading_gt_as_entity():
    assert conv("<p>> not a quote</p>", []) == "&gt; not a quote\n"


def test_escape_backslash():
    assert conv("<p>Use \\backslash here</p>", []) == "Use \\\\backslash here\n"


def test_escape_dollar_percent_plain():
    assert conv("<p>Price: $5 and 100% off</p>", []) == "Price: $5 and 100% off\n"


def test_escape_quotes_apostrophe_plain():
    assert (
        conv('<p>She said "hi" and it\'s ok</p>', []) == 'She said "hi" and it\'s ok\n'
    )


def test_escape_equals_pipe_plain():
    assert conv("<p>a = b and a | b</p>", []) == "a = b and a | b\n"


def test_escape_ordered_not_after_letter():
    assert conv("<p>v1.0 and step2. done</p>", []) == "v1.0 and step2. done\n"


def test_escape_bracket_link():
    assert conv("<p>text [link] here</p>", []) == "text \\[link] here\n"


def test_escape_bang_bracket_image():
    assert conv("<p>text ![x] here</p>", []) == "text !\\[x] here\n"


def test_escape_tilde_not_fenced():
    assert conv("<p>a ~ b and ~~x~~ text</p>", []) == "a ~ b and ~~x~~ text\n"


def test_strikethrough_on():
    assert (
        conv(
            "<p>a <del>b</del> and <s>c</s> and <strike>d</strike></p>",
            ["--plugin-strikethrough"],
        )
        == "a ~~b~~ and ~~c~~ and ~~d~~\n"
    )


def test_strikethrough_off_default():
    assert conv("<p>this <del>gone</del> stays</p>", []) == "this gone stays\n"


def test_table_basic_empty_header():
    assert (
        conv(
            "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>",
            ["--plugin-table"],
        )
        == "|   |   |\n|---|---|\n| a | b |\n| c | d |\n"
    )


def test_table_th_header():
    assert (
        conv(
            "<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>",
            ["--plugin-table"],
        )
        == "| A | B |\n|---|---|\n| 1 | 2 |\n"
    )


def test_table_alignment():
    assert (
        conv(
            '<table><tr><th align="left">L</th><th align="center">C</th><th align="right">R</th></tr><tr><td>1</td><td>2</td><td>3</td></tr></table>',
            ["--plugin-table"],
        )
        == "| L | C | R |\n|:--|:-:|--:|\n| 1 | 2 | 3 |\n"
    )


def test_table_header_promotion():
    assert (
        conv(
            "<table><tr><td>H1</td><td>H2</td></tr><tr><td>1</td><td>2</td></tr></table>",
            ["--plugin-table", "--opt-table-header-promotion"],
        )
        == "| H1 | H2 |\n|----|----|\n| 1  | 2  |\n"
    )


def test_table_padding_none():
    assert (
        conv(
            "<table><tr><td>aaa</td><td>b</td></tr><tr><td>c</td><td>ddd</td></tr></table>",
            ["--plugin-table", "--opt-table-cell-padding-behavior", "none"],
        )
        == "|||\n|---|---|\n|aaa|b|\n|c|ddd|\n"
    )


def test_table_padding_minimal():
    assert (
        conv(
            "<table><tr><td>aaa</td><td>b</td></tr><tr><td>c</td><td>ddd</td></tr></table>",
            ["--plugin-table", "--opt-table-cell-padding-behavior", "minimal"],
        )
        == "|  |  |\n|---|---|\n| aaa | b |\n| c | ddd |\n"
    )


def test_table_colspan_empty():
    assert (
        conv(
            '<table><tr><td colspan="2">wide</td></tr><tr><td>a</td><td>b</td></tr></table>',
            ["--plugin-table"],
        )
        == "|      |   |\n|------|---|\n| wide |   |\n| a    | b |\n"
    )


def test_table_colspan_mirror():
    assert (
        conv(
            '<table><tr><td colspan="2">wide</td></tr><tr><td>a</td><td>b</td></tr></table>',
            ["--plugin-table", "--opt-table-span-cell-behavior", "mirror"],
        )
        == "|      |      |\n|------|------|\n| wide | wide |\n| a    | b    |\n"
    )


def test_table_rowspan_mirror():
    assert (
        conv(
            '<table><tr><td rowspan="2">x</td><td>a</td></tr><tr><td>b</td></tr></table>',
            ["--plugin-table", "--opt-table-span-cell-behavior", "mirror"],
        )
        == "|   |   |\n|---|---|\n| x | a |\n| x | b |\n"
    )


def test_table_skip_empty_rows():
    assert (
        conv(
            "<table><tr><td>a</td><td>b</td></tr><tr><td></td><td></td></tr><tr><td>c</td><td>d</td></tr></table>",
            ["--plugin-table", "--opt-table-skip-empty-rows"],
        )
        == "|   |   |\n|---|---|\n| a | b |\n| c | d |\n"
    )


def test_table_newline_preserve():
    assert (
        conv(
            "<table><tr><td>a<br>b</td><td>c</td></tr></table>",
            ["--plugin-table", "--opt-table-newline-behavior", "preserve"],
        )
        == "|            |   |\n|------------|---|\n| a  <br />b | c |\n"
    )


def test_table_presentation_skipped():
    assert (
        conv(
            '<table role="presentation"><tr><td>a</td><td>b</td></tr></table>',
            ["--plugin-table"],
        )
        == "ab\n"
    )


def test_table_pipe_escaped_in_cell():
    assert (
        conv("<table><tr><td>a|b</td><td>c</td></tr></table>", ["--plugin-table"])
        == "|      |   |\n|------|---|\n| a\\|b | c |\n"
    )


def test_table_inline_in_cell():
    assert (
        conv(
            "<table><tr><td><strong>b</strong></td><td><code>x</code></td></tr></table>",
            ["--plugin-table"],
        )
        == "|       |     |\n|-------|-----|\n| **b** | `x` |\n"
    )


def test_err_table_opt_without_plugin():
    so, se, rc = run(["--opt-table-header-promotion"], stdin="<p>x</p>")
    assert rc != 0
    assert so == "" and se.strip() != ""


def test_err_unknown_flag():
    so, se, rc = run(["--no-such-flag"], stdin="<p>x</p>")
    assert rc != 0
    assert so == "" and se.strip() != ""
