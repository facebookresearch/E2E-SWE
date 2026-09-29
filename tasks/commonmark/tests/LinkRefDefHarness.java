import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;
import org.mdcore.node.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — link reference definitions as a block-parsing feature. Definitions are parsed
 * out of the document (they produce no visible output), can be referenced before they are defined,
 * carry optional titles, normalize labels, and a definition is not created inside a code block. This
 * mixes HTML output with AST inspection of the LinkReferenceDefinition node. Oracle-captured. One
 * case = one CTRF entry.
 */
public class LinkRefDefHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    /** Find the first LinkReferenceDefinition in the document (or null). */
    static LinkReferenceDefinition firstDef(Node doc) {
        for (Node c = doc.getFirstChild(); c != null; c = c.getNext()) {
            if (c instanceof LinkReferenceDefinition) return (LinkReferenceDefinition) c;
        }
        return null;
    }

    static {
        // ---- A definition produces no output; the reference resolves to a link. ----
        c("def_no_output", () -> h("[foo]\n\n[foo]: /url \"title\""));

        // ---- Forward reference: reference appears before the definition. ----
        c("def_forward", () -> h("[foo]: /url\n\nuse [foo] here"));

        // ---- A definition cannot interrupt a paragraph: the "[label]: dest" line stays paragraph text. ----
        c("def_no_interrupt", () -> h("text\n[foo]: /url"));

        // ---- LinkReferenceDefinition node fields: label, destination, title. ----
        c("def_node_fields", () -> {
            Node doc = PARSER.parse("[Foo Bar]: /dest \"the title\"\n\ntext");
            LinkReferenceDefinition d = firstDef(doc);
            return "type=" + (d == null ? "null" : d.getClass().getSimpleName())
                 + "|label=" + d.getLabel() + "|dest=" + d.getDestination() + "|title=" + d.getTitle();
        });

        // ---- Multiple independent definitions each resolve their own reference. ----
        c("def_multiple", () -> h("[foo] and [bar]\n\n[foo]: /one\n[bar]: /two"));

        // ---- A "definition" indented as code is NOT a definition (stays a code block). ----
        c("def_in_code", () -> h("    [foo]: /url\n\n[foo]"));

        // ---- Only the first definition of a duplicate label wins. ----
        c("def_duplicate", () -> h("[a]\n\n[a]: /first\n[a]: /second"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
