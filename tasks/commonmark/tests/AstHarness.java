import org.mdcore.parser.Parser;
import org.mdcore.node.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — the AST and node API (structure, typed accessors, traversal, manipulation). This
 * exercises the parsed tree directly rather than rendered output: node types and hierarchy, typed
 * getters (Heading.getLevel, FencedCodeBlock.getInfo/getLiteral, OrderedList.getMarkerStartNumber,
 * Link.getDestination/getTitle, ListBlock.isTight), visitor traversal via AbstractVisitor, and tree
 * mutation (appendChild / insertBefore / unlink / Nodes.between). Each case returns a compact string
 * summary (fields joined with '|'). Oracle-captured. One case = one CTRF entry.
 */
public class AstHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();

    /** Short class name of a node (e.g. "Heading"). */
    static String tn(Node n) { return n == null ? "null" : n.getClass().getSimpleName(); }

    /** Ordered list of child type names. */
    static String childTypes(Node parent) {
        StringBuilder sb = new StringBuilder();
        for (Node c = parent.getFirstChild(); c != null; c = c.getNext()) {
            if (sb.length() > 0) sb.append(",");
            sb.append(tn(c));
        }
        return sb.toString();
    }

    /** Collect all Text literals under a node, in document order, via a visitor. */
    static String allText(Node root) {
        StringBuilder sb = new StringBuilder();
        root.accept(new AbstractVisitor() {
            @Override public void visit(Text t) { sb.append(t.getLiteral()); }
        });
        return sb.toString();
    }

    static {
        // ---- Document children types for a mixed document. ----
        c("doc_children", () -> {
            Node doc = PARSER.parse("# H\n\npara\n\n- a\n- b\n\n```\ncode\n```");
            return "root=" + tn(doc) + "|children=" + childTypes(doc);
        });

        // ---- Heading level + text content via typed accessor and visitor. ----
        c("heading_fields", () -> {
            Heading h = (Heading) PARSER.parse("### Hello *world*").getFirstChild();
            return "type=" + tn(h) + "|level=" + h.getLevel() + "|text=" + allText(h)
                 + "|childTypes=" + childTypes(h);
        });

        // ---- FencedCodeBlock info string + literal (with trailing newline) + fence char. ----
        c("fenced_fields", () -> {
            FencedCodeBlock f = (FencedCodeBlock) PARSER.parse("```java x\nline1\nline2\n```").getFirstChild();
            return "info=" + f.getInfo() + "|literal=" + f.getLiteral().replace("\n", "\\n")
                 + "|fenceChar=" + f.getFenceChar() + "|fenceLen=" + f.getFenceLength();
        });

        // ---- OrderedList typed fields: start number and delimiter. ----
        c("ordered_fields", () -> {
            OrderedList ol = (OrderedList) PARSER.parse("3. a\n4. b").getFirstChild();
            return "type=" + tn(ol) + "|start=" + ol.getMarkerStartNumber()
                 + "|delim=" + ol.getMarkerDelimiter() + "|tight=" + ol.isTight();
        });

        // ---- Link node typed fields: destination + title; nested emphasis in link text. ----
        c("link_fields", () -> {
            Node para = PARSER.parse("[a *b*](/url \"ttl\")").getFirstChild();
            Link link = (Link) para.getFirstChild();
            return "type=" + tn(link) + "|dest=" + link.getDestination() + "|title=" + link.getTitle()
                 + "|childTypes=" + childTypes(link) + "|text=" + allText(link);
        });

        // ---- Tight vs loose flag on the parsed list block. ----
        c("list_tight_flag", () -> {
            boolean tight = ((ListBlock) PARSER.parse("- a\n- b").getFirstChild()).isTight();
            boolean loose = ((ListBlock) PARSER.parse("- a\n\n- b").getFirstChild()).isTight();
            return "tight=" + tight + "|loose=" + loose;
        });

        // ---- Tree mutation: appendChild builds a document; then unlink removes a node. ----
        c("mutate_append_unlink", () -> {
            Document doc = new Document();
            Heading h = new Heading(); h.setLevel(2); h.appendChild(new Text("Title"));
            Paragraph p = new Paragraph(); p.appendChild(new Text("body"));
            doc.appendChild(h); doc.appendChild(p);
            String before = childTypes(doc);
            h.unlink();
            return "before=" + before + "|after=" + childTypes(doc) + "|firstText=" + allText(doc);
        });

        // ---- insertBefore / insertAfter ordering. ----
        c("mutate_insert", () -> {
            Document doc = new Document();
            Text a = new Text("a"), b = new Text("b"), c = new Text("c");
            doc.appendChild(b);
            b.insertBefore(a);
            b.insertAfter(c);
            return "order=" + allText(doc) + "|first=" + tn(doc.getFirstChild()) + "|last=" + allText(doc.getLastChild());
        });

        // ---- Nodes.between iterates the exclusive range of siblings. ----
        c("nodes_between", () -> {
            Document doc = new Document();
            Text a = new Text("a"), b = new Text("b"), c = new Text("c"), d = new Text("d");
            for (Text t : new Text[]{a, b, c, d}) doc.appendChild(t);
            StringBuilder sb = new StringBuilder();
            for (Node n : Nodes.between(a, d)) sb.append(((Text) n).getLiteral());
            return "between=" + sb;
        });

        // ---- Paragraph with a hard line break: child types include HardLineBreak. ----
        c("hardbreak_node", () -> {
            Node para = PARSER.parse("foo  \nbar").getFirstChild();
            return "childTypes=" + childTypes(para);
        });

        // ---- Programmatic construction using setters + prependChild + getParent/getPrevious. ----
        // Build a document by hand (the workflow a caller uses before rendering), exercising the
        // typed setters and the sibling/parent navigation the tree API exposes.
        c("construct_setters_nav", () -> {
            Document doc = new Document();
            Paragraph p = new Paragraph();
            Text body = new Text(); body.setLiteral("body");
            p.appendChild(body);
            Heading head = new Heading(); head.setLevel(3);
            Text ht = new Text(); ht.setLiteral("Title");
            head.appendChild(ht);
            doc.appendChild(p);
            doc.prependChild(head);            // head now before p
            Link link = new Link();
            link.setDestination("/u"); link.setTitle("t");
            link.appendChild(new Text("x"));
            p.appendChild(link);
            return "order=" + childTypes(doc)
                 + "|firstIsHeading=" + (doc.getFirstChild() == head)
                 + "|pPrev=" + tn(p.getPrevious())
                 + "|bodyParent=" + tn(body.getParent())
                 + "|level=" + head.getLevel()
                 + "|linkDest=" + link.getDestination() + "|linkTitle=" + link.getTitle();
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
