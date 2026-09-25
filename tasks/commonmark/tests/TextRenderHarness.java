import org.mdcore.parser.Parser;
import org.mdcore.renderer.text.TextContentRenderer;
import org.mdcore.renderer.text.LineBreakRendering;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — TextContentRenderer (AST -> plain text with minimal markup). Exercises the three
 * line-break modes: COMPACT (default), SEPARATE_BLOCKS (blank line between blocks), and STRIP (single
 * line). Content like links, lists, and headings render to their textual content with mode-specific
 * spacing/prefixes. Each case renders to text (newlines encoded as \n). Oracle-captured. One case =
 * one CTRF entry.
 */
public class TextRenderHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();

    static final TextContentRenderer COMPACT =
        TextContentRenderer.builder().lineBreakRendering(LineBreakRendering.COMPACT).build();
    static final TextContentRenderer SEPARATE =
        TextContentRenderer.builder().lineBreakRendering(LineBreakRendering.SEPARATE_BLOCKS).build();
    static final TextContentRenderer STRIP =
        TextContentRenderer.builder().lineBreakRendering(LineBreakRendering.STRIP).build();

    static String t(TextContentRenderer r, String md) { return r.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Default renderer uses COMPACT line-break mode: pin the concrete default-built text. ----
        c("default_is_compact", () -> {
            String md = "foo foo\n\nbar\nbar";
            String def = TextContentRenderer.builder().build().render(PARSER.parse(md)).replace("\n", "\\n");
            return "default=" + def;
        });

        // ---- Heading + paragraph: the three modes differ in spacing/joining. ----
        c("heading_modes", () -> {
            String md = "# Heading\n\nFoo";
            return "compact=" + t(COMPACT, md) + "|separate=" + t(SEPARATE, md) + "|strip=" + t(STRIP, md);
        });

        // ---- Two paragraphs across the three modes. ----
        c("paragraphs_modes", () -> {
            String md = "foo foo\n\nbar\nbar";
            return "compact=" + t(COMPACT, md) + "|separate=" + t(SEPARATE, md) + "|strip=" + t(STRIP, md);
        });

        // ---- Bullet list across the three modes (markers/prefix behavior). ----
        c("bullet_modes", () -> {
            String md = "foo\n\n* foo\n* bar\n\nbar";
            return "compact=" + t(COMPACT, md) + "|separate=" + t(SEPARATE, md) + "|strip=" + t(STRIP, md);
        });

        // ---- Link: text content is the link text (destination dropped in plain text). ----
        c("link_text", () -> {
            String md = "see [the site](http://example.com) now";
            return "compact=" + t(COMPACT, md) + "|strip=" + t(STRIP, md);
        });

        // ---- Code span and emphasis reduce to their textual content. ----
        c("inline_text", () -> {
            String md = "a `code` and *em* and **strong**";
            return "compact=" + t(COMPACT, md);
        });

        // ---- Nested list across compact and separate modes (indentation/prefix behavior). ----
        c("nested_list_modes", () -> {
            String md = "- a\n  - b\n  - c\n- d";
            return "compact=" + t(COMPACT, md) + "|separate=" + t(SEPARATE, md);
        });

        // ---- Block quote content across the three modes. ----
        c("quote_modes", () -> {
            String md = "> quoted text\n> more";
            return "compact=" + t(COMPACT, md) + "|separate=" + t(SEPARATE, md) + "|strip=" + t(STRIP, md);
        });

        // ---- Fenced code block content across compact and separate. ----
        c("code_block_modes", () -> {
            String md = "text\n\n```\nline1\nline2\n```\n\nafter";
            return "compact=" + t(COMPACT, md) + "|separate=" + t(SEPARATE, md);
        });

        // ---- Image renders its alt text; thematic break has a textual representation. ----
        c("image_and_hr", () -> {
            String md = "before\n\n![alt](/img.png)\n\n---\n\nafter";
            return "compact=" + t(COMPACT, md) + "|strip=" + t(STRIP, md);
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
