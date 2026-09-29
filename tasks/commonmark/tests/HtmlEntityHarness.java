import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — raw HTML, entity/numeric character references, backslash escapes, and line
 * breaks. Covers: HTML blocks (passed through verbatim), inline raw HTML tags, named entities
 * (decoded via the HTML5 entity table), decimal/hex numeric references, backslash escapes of ASCII
 * punctuation, and hard vs soft line breaks. Each case renders to EXACT HTML (newlines encoded as
 * \n). Oracle-captured. One case = one CTRF entry. Entity decoding exercises the baked entity table.
 */
public class HtmlEntityHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- HTML block: a block-level tag and its contents pass through verbatim. ----
        c("html_block", () -> h("<div class=\"x\">\n*not emphasis*\n</div>"));

        // ---- Inline raw HTML tags are passed through (open/close/self-closing). ----
        c("html_inline", () -> h("foo <span id=\"a\"> bar </span> <br/> baz"));

        // ---- Named entities decode to their characters (uses the HTML5 entity table). ----
        c("entity_named", () -> h("&copy; &amp; &lt; &gt; &Aacute; &frac34;"));

        // ---- Numeric character references: decimal and hex. ----
        c("entity_numeric", () -> h("&#35; &#1234; &#x41; &#Xe9;"));

        // ---- Invalid/unknown entity is left as literal text (escaped). ----
        c("entity_invalid", () -> h("&nonsense; &#0; &#x0;"));

        // ---- Backslash escapes of ASCII punctuation produce the literal character. ----
        c("backslash_escape", () -> h("\\*not em\\* \\` \\[ \\] \\\\"));

        // ---- Backslash before a non-escapable char stays literal backslash. ----
        c("backslash_literal", () -> h("\\A \\3 \\€"));

        // ---- Hard line break via two trailing spaces -> <br />. ----
        c("hard_break_spaces", () -> h("foo  \nbar"));

        // ---- Hard line break via trailing backslash -> <br />. ----
        c("hard_break_backslash", () -> h("foo\\\nbar"));

        // ---- Soft line break (single newline) renders as a newline by default. ----
        c("soft_break", () -> h("foo\nbar"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
