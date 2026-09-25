import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — HtmlRenderer builder options. Each option changes rendering behavior in a
 * distinct, observable way: escapeHtml (escape raw HTML instead of passing through), softbreak
 * (string used for soft line breaks), sanitizeUrls (drop disallowed-protocol URLs), percentEncodeUrls
 * (percent-encode link/image destinations), omitSingleParagraphP (skip <p> for a single top-level
 * paragraph). Each case renders to EXACT HTML (newlines encoded as \n). Oracle-captured. One case =
 * one CTRF entry, each pinning one configuration branch a broken builder would get wrong.
 */
public class HtmlOptionsHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static String render(HtmlRenderer r, String md) { return r.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- escapeHtml(true): raw inline HTML and HTML blocks are escaped, not passed through. ----
        c("escape_html", () -> render(
            HtmlRenderer.builder().escapeHtml(true).build(),
            "foo <span>bar</span>\n\n<div>block</div>"));

        // ---- softbreak("<br>"): soft line breaks render as the configured string, verbatim. ----
        c("softbreak_br", () -> render(
            HtmlRenderer.builder().softbreak("<br>").build(),
            "foo\nbar\nbaz"));

        // ---- sanitizeUrls(true): javascript: URL is dropped to empty; http URL is kept. ----
        c("sanitize_urls", () -> render(
            HtmlRenderer.builder().sanitizeUrls(true).build(),
            "[a](javascript:alert(1)) [b](http://ok.example/)"));

        // ---- percentEncodeUrls(true): unsafe chars in a destination get percent-encoded. ----
        c("percent_encode", () -> render(
            HtmlRenderer.builder().percentEncodeUrls(true).build(),
            "[a](/path with space?x=ä)"));

        // ---- percentEncodeUrls(true): already-valid %-escapes and reserved URL chars are PRESERVED. ----
        // A pre-encoded %20 must not be double-encoded to %2520, and reserved chars ?=&#/ stay literal.
        c("percent_encode_preserve", () -> render(
            HtmlRenderer.builder().percentEncodeUrls(true).build(),
            "[a](/a%20b?x=1&y=2#frag/z)"));

        // ---- omitSingleParagraphP(true): a lone top-level paragraph renders without <p> wrapper. ----
        c("omit_single_p", () -> render(
            HtmlRenderer.builder().omitSingleParagraphP(true).build(),
            "just one paragraph"));

        // ---- omitSingleParagraphP(true) still wraps when there are multiple blocks. ----
        c("omit_single_p_multi", () -> render(
            HtmlRenderer.builder().omitSingleParagraphP(true).build(),
            "one\n\ntwo"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
