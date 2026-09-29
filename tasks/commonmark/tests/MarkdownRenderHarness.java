import org.mdcore.parser.Parser;
import org.mdcore.renderer.markdown.MarkdownRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — MarkdownRenderer (AST -> Markdown/CommonMark text). This is the reverse of HTML
 * rendering: parse Markdown, then render the AST back to Markdown, exercising the renderer's escaping,
 * fence/marker selection, and block spacing. Each case renders the parsed document to Markdown text
 * (newlines encoded as \n). Oracle-captured. One case = one CTRF entry. Round-trip stability of
 * non-trivial constructs is the correctness signal.
 */
public class MarkdownRenderHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final MarkdownRenderer MD = MarkdownRenderer.builder().build();
    static String m(String md) { return MD.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- ATX headings round-trip across all levels. ----
        c("headings", () -> m("# a\n\n## b\n\n### c\n\n#### d\n\n##### e\n\n###### f"));

        // ---- Emphasis and strong emphasis round-trip. ----
        c("emphasis", () -> m("*em* and **strong** and ***both***"));

        // ---- Fenced code block with info string round-trips (fence length preserved/expanded). ----
        c("fenced_code", () -> m("```info\ntest\n```"));

        // ---- Fenced code whose content contains backticks -> renderer widens the fence. ----
        c("fenced_widen", () -> m("````\n```\ninner\n````"));

        // ---- Indented code block round-trip. ----
        c("indented_code", () -> m("    hi\n    code"));

        // ---- Bullet + ordered lists round-trip with markers. ----
        c("lists", () -> m("- a\n- b\n\n1. one\n2. two"));

        // ---- Block quote round-trip. ----
        c("block_quote", () -> m("> quoted\n> lines"));

        // ---- Link and image round-trip with title. ----
        c("link_image", () -> m("[t](/url \"ttl\") and ![a](/img.png)"));

        // ---- Thematic break round-trip. ----
        c("thematic_break", () -> m("---\n\nfoo"));

        // ---- Text with characters that must be backslash-escaped to round-trip safely. ----
        c("escaping", () -> m("a *literal* star: \\* and a hash \\# start"));

        // ---- Nested block quote with a list inside round-trips. ----
        c("nested_quote_list", () -> m("> - a\n> - b\n>\n> text"));

        // ---- Heading containing inline code and a link round-trips. ----
        c("heading_inline", () -> m("# Title with `code` and [a](/u)"));

        // ---- Hard line break (two-trailing-space form) round-trips inside a paragraph. ----
        c("hard_break", () -> m("foo  \nbar"));

        // ---- Inline raw HTML and an autolink round-trip. ----
        c("inline_html_autolink", () -> m("text <span>x</span> and <http://ex.com>"));

        // ---- A loose ordered list with multi-paragraph items round-trips. ----
        c("loose_ordered", () -> m("1. one\n\n2. two\n\n   more"));

        // ---- Setext heading round-trips (or normalizes to a stable form). ----
        c("setext_roundtrip", () -> m("Foo\nbar\n===\n\nBaz\n---"));

        // ---- Nested emphasis + code span + escaped punctuation round-trip together. ----
        c("mixed_inline", () -> m("a **b `c` d** and *e* with \\* and a.b#c"));

        // ---- Link with a title, an image, and an autolink round-trip. ----
        c("links_titles", () -> m("[t](/u \"ti\") ![a](/i.png \"im\") <http://x.example>"));

        // ---- Deeply nested block quotes with a list and code round-trip. ----
        c("deep_quote", () -> m("> > a\n> >\n> > - x\n> >\n> > ```\n> > code\n> > ```"));

        // ---- Hard line break and soft break inside a paragraph round-trip. ----
        c("breaks", () -> m("foo\\\nbar\nbaz"));

        // ---- HTML block and inline HTML round-trip verbatim. ----
        c("html", () -> m("<div>\nraw\n</div>\n\ntext <b>x</b> more"));

        // ---- Ordered list with a non-1 start and ')' delimiter round-trips. ----
        c("ordered_start_paren", () -> m("3) three\n4) four"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
