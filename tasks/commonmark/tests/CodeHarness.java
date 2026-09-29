import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — code: indented code blocks, fenced code blocks (info strings, fence lengths,
 * tildes vs backticks), and inline code spans (backtick-count matching, surrounding-space stripping,
 * newline handling). Each case renders to EXACT HTML (newlines encoded as \n). Oracle-captured. One
 * case = one CTRF entry; code rendering is where HTML-escaping of the literal content matters.
 */
public class CodeHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }
    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Indented code block: 4-space indent, content preserved verbatim, HTML-escaped. ----
        c("indented", () -> h("    a simple\n      indented code block"));

        // ---- Indented code escapes special HTML chars in its literal content. ----
        c("indented_escape", () -> h("    <a> & \"quote\""));

        // ---- Fenced code with an info string -> language class on <code>. ----
        c("fenced_info", () -> h("```ruby\ndef foo\n  1\nend\n```"));

        // ---- Fenced code with tildes; content includes backticks (no nesting confusion). ----
        c("fenced_tilde", () -> h("~~~\nfoo\n```\nbar\n~~~"));

        // ---- Fenced code: closing fence must be >= opening length; escapes content. ----
        c("fenced_length", () -> h("````\n```\n<x> & y\n````"));

        // ---- Empty fenced code block. ----
        c("fenced_empty", () -> h("```\n```"));

        // ---- Code span: single backticks; interior is literal (no emphasis parsed inside). ----
        c("span_literal", () -> h("`foo *bar* baz`"));

        // ---- Code span: double backticks let a single backtick appear inside. ----
        c("span_backticks", () -> h("`` foo ` bar ``"));

        // ---- Code span: one leading+trailing space stripped iff content isn't all-spaces. ----
        c("span_space_strip", () -> h("` foo `\n\n` `"));

        // ---- Code span HTML-escapes special characters. ----
        c("span_escape", () -> h("`<a> & \"q\"`"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
