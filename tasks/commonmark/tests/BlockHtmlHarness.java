import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — block-level HTML rendering (headings, thematic breaks, paragraphs, blank lines).
 * Each case parses a realistic Markdown snippet with the default parser + default HTML renderer and
 * returns the EXACT rendered HTML (newlines encoded as the literal token \n so the value is a single
 * line, matching Runner's capture/grade contract). One case = one CTRF entry; assertions are exact
 * (the full HTML string), so a broken implementation cannot satisfy them with output of merely the
 * right shape. Expected values are oracle-captured from the reference implementation.
 */
public class BlockHtmlHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();

    /** Render markdown to HTML with newlines encoded as the two-char token \n (no real newlines). */
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- ATX headings: levels 1..6 each map to h1..h6; 7 hashes is NOT a heading (paragraph). ----
        c("atx_levels", () -> h("# h1\n## h2\n### h3\n#### h4\n##### h5\n###### h6\n####### not"));

        // ---- ATX heading edge cases: closing sequence, required space, empty heading, leading spaces. ----
        c("atx_edges", () -> h("#\t\n#no\n#  space  #\n   ### indented\n## closed ##  "));

        // ---- Setext headings: '=' -> h1, '-' -> h2 over a paragraph line. ----
        c("setext", () -> h("Foo\n===\n\nBar\n---"));

        // ---- Thematic breaks: ***, ---, ___, and spaced/long variants all render <hr />. ----
        c("thematic_breaks", () -> h("***\n\n---\n\n___\n\n * * *\n\n-----"));

        // ---- Paragraphs: consecutive lines join into one paragraph; blank lines separate paragraphs. ----
        c("paragraphs", () -> h("aaa\nbbb\n\nccc\nddd"));

        // ---- Leading/trailing blank lines are stripped; multiple blanks collapse between paragraphs. ----
        c("blank_lines", () -> h("\n\n  \n\naaa\n\n\n  \n\nbbb\n\n\n"));

        // ---- Setext vs thematic-break precedence: a '---' under text is a heading, not an <hr />. ----
        c("setext_vs_hr", () -> h("Foo\nbar\n---\nbaz"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
