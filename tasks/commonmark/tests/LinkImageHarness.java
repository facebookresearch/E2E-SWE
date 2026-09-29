import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — links and images: inline links (destination + optional title), reference links
 * (full/collapsed/shortcut) resolved against link reference definitions, images (alt text from inner
 * text), autolinks (<...>), and the interaction of emphasis inside link text. Each case renders to
 * EXACT HTML (newlines encoded as \n). Oracle-captured. One case = one CTRF entry. Reference
 * resolution and title/destination escaping are the correctness-heavy parts.
 */
public class LinkImageHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Inline link with destination only. ----
        c("inline_plain", () -> h("[text](/url)"));

        // ---- Inline link with destination and a title. ----
        c("inline_title", () -> h("[text](/url \"a title\")"));

        // ---- Inline link with <angle> destination and emphasis inside the text. ----
        c("inline_angle_em", () -> h("[*em* text](</my url>)"));

        // ---- Full reference link: [text][label] resolved against a definition. ----
        c("ref_full", () -> h("[text][ref]\n\n[ref]: /url \"t\""));

        // ---- Collapsed reference link: [label][] . ----
        c("ref_collapsed", () -> h("[ref][]\n\n[ref]: /url"));

        // ---- Shortcut reference link: [label] . ----
        c("ref_shortcut", () -> h("[ref]\n\n[ref]: /url"));

        // ---- Reference label matching is case-insensitive / whitespace-normalized. ----
        c("ref_normalize", () -> h("[Foo   Bar]\n\n[foo bar]: /url"));

        // ---- Image: inline, alt from inner text. ----
        c("image_inline", () -> h("![alt text](/img.png \"ttl\")"));

        // ---- Image with emphasis in alt-text: alt is the plain text content. ----
        c("image_alt_markup", () -> h("![foo *bar*](/img.png)"));

        // ---- Autolink: absolute URI in angle brackets. ----
        c("autolink_uri", () -> h("<http://example.com/a?b=c>"));

        // ---- Autolink: email address in angle brackets -> mailto:. ----
        c("autolink_email", () -> h("<foo@bar.example.com>"));

        // ---- Entities/escapes in a link destination and title are handled. ----
        c("link_special", () -> h("[t](/url?a=1&b=2 \"a &amp; b\")"));

        // ---- Nested brackets in link text, and balanced parens in the destination. ----
        c("link_nested_brackets", () -> h("[a [b] c](/url) and [x](/foo(bar)baz)"));

        // ---- Reference definition with a multi-line title and angle-bracket destination. ----
        c("ref_multiline_title", () -> h("[foo]\n\n[foo]: </my url> \"multi\nline\ntitle\""));

        // ---- Link takes precedence over emphasis when brackets and stars interleave. ----
        c("link_vs_emphasis", () -> h("*[foo*](/url)\n\n[foo *bar](/url)*"));

        // ---- Image inside a link's text; nested image alt-text extraction. ----
        c("image_in_link", () -> h("[![alt](/img.png)](/link)"));

        // ---- Autolink edge cases: scheme validation and disallowed characters. ----
        c("autolink_edges", () -> h("<mailto:foo@bar.com> <irc://x> <not a url> <http://a.b?c=d#e>"));

        // ---- Backslash escapes and entities inside link destinations. ----
        c("link_escapes", () -> h("[a](/foo\\)bar) [b](/x%20y) [c](/&copy;)"));

        // ---- Full reference with a title, used twice, case-insensitive label. ----
        c("ref_reuse", () -> h("[A] then [a][]\n\n[a]: /u \"T\""));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
