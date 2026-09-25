import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — special inputs, precedence, and preliminaries: tab expansion, block-structure
 * precedence over inline structure, empty input, CRLF line endings, Unicode/insecure-codepoint
 * handling, and combinations that commonly break naive parsers. Each case renders to EXACT HTML
 * (newlines encoded as \n). Oracle-captured. One case = one CTRF entry, each probing a distinct
 * robustness corner.
 */
public class SpecialInputHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Empty input renders to empty output. ----
        c("empty", () -> "[" + h("") + "]");

        // ---- Tab counts as up to 4 columns: a leading tab makes an indented code block. ----
        c("tab_code", () -> h("\tfoo\tbaz\t\tbim"));

        // ---- Tabs are expanded for block structure but preserved inside code content. ----
        c("tab_mixed", () -> h("  \tfoo"));

        // ---- Precedence: block structure (list) wins over inline structure. ----
        c("precedence_block", () -> h("- `one\n- two`"));

        // ---- CRLF line endings are handled like LF. ----
        c("crlf", () -> h("foo\r\n\r\nbar\r\nbaz"));

        // ---- The NUL character (U+0000) is replaced with the replacement character U+FFFD. ----
        c("nul_replacement", () -> h("foo\u0000bar"));

        // ---- A backslash-escaped entity is not decoded; entity in normal text is decoded. ----
        c("escaped_entity", () -> h("\\&copy; vs &copy;"));

        // ---- Trailing whitespace-only lines and a single trailing newline normalize consistently. ----
        c("trailing_ws", () -> h("foo   \n"));

        // ---- Setext heading takes precedence, but a blank line makes the dashes a thematic break. ----
        c("setext_blankline", () -> h("Foo\n\n---"));

        // ---- Deeply mixed document: heading, quote-with-list, fenced code, and a reference link. ----
        c("mixed_document", () -> h(
            "# Title\n\n> quote with a [link]\n>\n> - item\n\n```js\ncode();\n```\n\n[link]: /url"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
