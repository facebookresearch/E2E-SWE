import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — lists and block quotes: bullet vs ordered lists, start numbers and delimiters,
 * tight vs loose rendering (the blank-line rule that decides whether <li> content is wrapped in <p>),
 * nesting, and block quotes (including lazy continuation and nested quotes). Each case renders to
 * EXACT HTML (newlines encoded as \n). Oracle-captured. One case = one CTRF entry. Tight/loose and
 * lazy continuation are classic correctness traps.
 */
public class ListQuoteHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Tight bullet list: no blank lines -> <li> content NOT wrapped in <p>. ----
        c("bullet_tight", () -> h("- a\n- b\n- c"));

        // ---- Loose bullet list: blank line between items -> <li> content wrapped in <p>. ----
        c("bullet_loose", () -> h("- a\n\n- b\n\n- c"));

        // ---- Ordered list: default start 1, '.' delimiter. ----
        c("ordered_basic", () -> h("1. one\n2. two\n3. three"));

        // ---- Ordered list with a non-1 start number -> start attribute on <ol>. ----
        c("ordered_start", () -> h("5. five\n6. six"));

        // ---- Ordered list with ')' delimiter. ----
        c("ordered_paren", () -> h("1) a\n2) b"));

        // ---- Nested lists: a sublist inside an item. ----
        c("nested", () -> h("- a\n  - b\n  - c\n- d"));

        // ---- List item containing multiple blocks (paragraph + code) -> loose. ----
        c("item_multiblock", () -> h("- a\n\n      code\n\n- b"));

        // ---- Block quote: single level, joins lines, contains a paragraph. ----
        c("quote_basic", () -> h("> a\n> b\n> c"));

        // ---- Block quote with lazy continuation (paragraph continuation without '>'). ----
        c("quote_lazy", () -> h("> a\nb\n> c"));

        // ---- Nested block quotes and a quoted heading. ----
        c("quote_nested", () -> h("> > deep\n>\n> # H"));

        // ---- Block quote containing a list. ----
        c("quote_list", () -> h("> - a\n> - b"));

        // ---- Loose-because-of-blank-between-items even when items are single-line. ----
        c("loose_via_gap", () -> h("- x\n- y\n\n- z"));

        // ---- Ordered list interrupting a paragraph only when it starts with 1. ----
        c("ordered_interrupt", () -> h("Foo\n1. a\n2. b\n\nBar\n2. c"));

        // ---- List item with a lazy continuation line and a nested sublist. ----
        c("item_lazy_nested", () -> h("- a\ncontinued\n  - nested\n- b"));

        // ---- Nested block quote with mixed content and blank separators. ----
        c("quote_deep_mixed", () -> h("> # H\n>\n> para\n>\n> > inner\n> > quote"));

        // ---- Two adjacent lists of different bullet markers are separate lists. ----
        c("adjacent_bullet_markers", () -> h("- a\n- b\n\n* c\n* d\n\n+ e"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
