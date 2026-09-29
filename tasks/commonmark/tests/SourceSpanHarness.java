import org.mdcore.parser.Parser;
import org.mdcore.parser.IncludeSourceSpans;
import org.mdcore.node.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — source spans (positional tracking). When configured with includeSourceSpans, the
 * parser records where each node appeared in the input (line index, column index, input index,
 * length). This exercises the SourceSpan API and the BLOCKS vs BLOCKS_AND_INLINES modes. Each case
 * returns the queried span fields joined with '|'. Oracle-captured. One case = one CTRF entry.
 */
public class SourceSpanHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final Parser BLOCKS = Parser.builder().includeSourceSpans(IncludeSourceSpans.BLOCKS).build();
    static final Parser INLINES = Parser.builder().includeSourceSpans(IncludeSourceSpans.BLOCKS_AND_INLINES).build();

    static String span(SourceSpan s) {
        return "line=" + s.getLineIndex() + "|col=" + s.getColumnIndex()
             + "|input=" + s.getInputIndex() + "|len=" + s.getLength();
    }

    static {
        // ---- BLOCKS_AND_INLINES: span of an emphasis inline on the third line (README example). ----
        c("inline_emphasis_span", () -> {
            String src = "foo\n\nbar *baz*";
            Node doc = INLINES.parse(src);
            Node emphasis = doc.getLastChild().getLastChild();
            SourceSpan s = emphasis.getSourceSpans().get(0);
            String sub = src.substring(s.getInputIndex(), s.getInputIndex() + s.getLength());
            return span(s) + "|sub=" + sub;
        });

        // ---- BLOCKS mode: a heading block span covers its whole source line. ----
        c("block_heading_span", () -> {
            Node doc = BLOCKS.parse("# Title\n\npara");
            SourceSpan s = doc.getFirstChild().getSourceSpans().get(0);
            return span(s);
        });

        // ---- Default parser (NONE): no source spans recorded. ----
        c("default_no_spans", () -> {
            Node doc = Parser.builder().build().parse("hello");
            int n = doc.getFirstChild().getSourceSpans().size();
            return "spanCount=" + n;
        });

        // ---- Multi-line paragraph in BLOCKS mode records one span per source line. ----
        c("multiline_block_spans", () -> {
            Node doc = BLOCKS.parse("aaa\nbbb\nccc");
            List<SourceSpan> spans = doc.getFirstChild().getSourceSpans();
            StringBuilder sb = new StringBuilder("count=" + spans.size());
            for (SourceSpan s : spans) sb.append("|(").append(s.getLineIndex()).append(",").append(s.getLength()).append(")");
            return sb.toString();
        });

        // ---- SourceSpan.subSpan produces a sub-range with adjusted input index and length. ----
        c("subspan", () -> {
            SourceSpan s = SourceSpan.of(2, 4, 9, 5);
            SourceSpan sub = s.subSpan(1, 3);
            return "orig=" + span(s) + "|sub=" + span(sub);
        });

        // ---- Inline spans across multiple inline children: link + emphasis positions on one line. ----
        c("inline_children_spans", () -> {
            String src = "see [a *b* c](/u) end";
            Node doc = INLINES.parse(src);
            Node para = doc.getFirstChild();
            Node link = para.getFirstChild().getNext();  // Text("see "), then Link
            SourceSpan ls = link.getSourceSpans().get(0);
            String sub = src.substring(ls.getInputIndex(), ls.getInputIndex() + ls.getLength());
            return "linkSpan=" + span(ls) + "|sub=" + sub;
        });

        // ---- Block spans for a list: each item block records its own line span. ----
        c("list_item_spans", () -> {
            Node doc = BLOCKS.parse("- a\n- bb\n- ccc");
            Node list = doc.getFirstChild();
            StringBuilder sb = new StringBuilder();
            for (Node item = list.getFirstChild(); item != null; item = item.getNext()) {
                SourceSpan s = item.getSourceSpans().get(0);
                sb.append("(").append(s.getLineIndex()).append(",").append(s.getColumnIndex())
                  .append(",").append(s.getLength()).append(")");
            }
            return "items=" + sb;
        });

        // ---- Nested block spans: a paragraph inside a block quote carries the inner column offset. ----
        c("nested_block_span", () -> {
            Node doc = BLOCKS.parse("> hello\n> world");
            Node para = doc.getFirstChild().getFirstChild();  // BlockQuote -> Paragraph
            SourceSpan s0 = para.getSourceSpans().get(0);
            return "count=" + para.getSourceSpans().size() + "|first=" + span(s0);
        });

        // ---- Emphasis span length across a multi-character delimiter run. ----
        c("strong_span", () -> {
            String src = "a **bold** b";
            Node doc = INLINES.parse(src);
            Node strong = doc.getFirstChild().getFirstChild().getNext();  // Text("a "), StrongEmphasis
            SourceSpan s = strong.getSourceSpans().get(0);
            String sub = src.substring(s.getInputIndex(), s.getInputIndex() + s.getLength());
            return span(s) + "|sub=" + sub;
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
