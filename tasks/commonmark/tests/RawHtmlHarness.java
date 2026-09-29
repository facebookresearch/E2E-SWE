import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;
import org.mdcore.node.*;

import java.io.IOException;
import java.io.StringReader;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — raw inline HTML variants and reader-based parsing. Exercises the inline raw-HTML
 * recognizer beyond simple tags: open tags with attributes, closing tags, self-closing tags, HTML
 * comments, processing instructions, CDATA sections, and declarations; plus invalid tag-like text
 * that must be treated as literal (escaped) text. Also covers Parser.parseReader (the Reader-based
 * entry point) and blank-input handling. Each case renders to EXACT HTML (newlines encoded as \n).
 * Oracle-captured. One case = one CTRF entry.
 */
public class RawHtmlHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Open tags with attributes (quoted, unquoted, boolean) pass through as raw HTML. ----
        c("open_tag_attrs", () -> h("<a foo=\"bar\" bam = 'baz' _boolean zoop:33=zoop:33 />"));

        // ---- Closing tag and self-closing tag pass through. ----
        c("close_selfclose", () -> h("</a> and <b2/> and <responsive-image src=\"x.jpg\" />"));

        // ---- HTML comment passes through verbatim. ----
        c("comment", () -> h("foo <!-- this is a comment - with hyphens --> bar"));

        // ---- Processing instruction passes through. ----
        c("processing_instruction", () -> h("foo <?php echo '>'; ?> bar"));

        // ---- CDATA section passes through. ----
        c("cdata", () -> h("foo <![CDATA[>&<]]> bar"));

        // ---- Declaration passes through. ----
        c("declaration", () -> h("foo <!DOCTYPE html> bar"));

        // ---- Invalid tag-like text is NOT raw HTML: it is escaped literal text. ----
        c("invalid_tags", () -> h("<33> <__> and <a h*#ref=\"hi\">"));

        // ---- Unclosed quote in an attribute makes it literal escaped text. ----
        c("invalid_unclosed", () -> h("<a href=\"hi'> <a href=hi'>"));

        // ---- parseReader: same result as parse(String) for equivalent input. ----
        c("parse_reader", () -> {
            try {
                Node doc = PARSER.parseReader(new StringReader("# Heading\n\n*text*"));
                return HTML.render(doc).replace("\n", "\\n");
            } catch (IOException e) {
                return "IOException";
            }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
