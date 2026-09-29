import org.mdcore.parser.Parser;
import org.mdcore.renderer.html.HtmlRenderer;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — inline emphasis and strong emphasis (the delimiter-run algorithm). This is the
 * subtle core of CommonMark inline parsing: left/right-flanking delimiter runs, the rule-of-3
 * multiple-of-3 constraint, intraword underscore rules, and nesting. Each case renders a realistic
 * inline snippet to EXACT HTML (newlines encoded as \n). Values are oracle-captured. One case = one
 * CTRF entry, each probing a genuinely distinct branch of the delimiter algorithm.
 */
public class EmphasisHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final Parser PARSER = Parser.builder().build();
    static final HtmlRenderer HTML = HtmlRenderer.builder().build();
    static String h(String md) { return HTML.render(PARSER.parse(md)).replace("\n", "\\n"); }

    static {
        // ---- Basic emphasis + strong with both markers. ----
        c("basic", () -> h("*foo* _bar_ **baz** __qux__"));

        // ---- Intraword: '*' works inside words, '_' does NOT (left/right-flanking + intraword rule). ----
        c("intraword", () -> h("foo*bar*baz\n\nfoo_bar_baz"));

        // ---- Nesting: strong-in-emphasis and emphasis-in-strong. ----
        c("nesting", () -> h("*foo **bar** baz*\n\n**foo *bar* baz**"));

        // ---- Rule of 3: `*foo**bar***` — the multiple-of-3 delimiter split. ----
        c("rule_of_three", () -> h("*foo**bar***\n\n***foo***"));

        // ---- Not emphasis: whitespace after opening / before closing breaks the run. ----
        c("not_emphasis", () -> h("* foo *\n\n*foo bar *\n\na * foo bar*"));

        // ---- Mixed delimiters can't pair: `*foo_` doesn't emphasize; `**foo*` leaves a literal. ----
        c("unmatched", () -> h("*foo_\n\n**foo*\n\n_foo**"));

        // ---- Emphasis around punctuation and adjacent runs (`****foo****`, `*_foo_*`). ----
        c("punctuation_runs", () -> h("****foo****\n\n*_foo_*\n\n_*foo*_"));

        // ---- Rule-of-3 with asymmetric run lengths: opener/closer length mismatch across the run. ----
        c("rule_of_three_asym", () -> h("*foo**bar**baz*\n\n**foo*bar*baz**\n\n***foo* bar**"));

        // ---- Nested emphasis with punctuation-flanking subtleties (CommonMark spec corners). ----
        c("flanking_punct", () -> h("*(*foo*)*\n\n**(**foo**)**\n\nfoo-_(bar)_"));

        // ---- Underscore flanking around punctuation vs. intraword (spec examples 360-ish). ----
        c("underscore_flanking", () -> h("_foo bar_\n\n_(bar)_.\n\n_foo_bar_baz_"));

        // ---- Emphasis interacting with backslash-escaped and literal delimiters. ----
        c("escaped_delims", () -> h("\\*not\\* *yes*\n\n*foo\\*bar*\n\n**a\\**"));

        // ---- Long delimiter runs that pair greedily from the outside in. ----
        c("long_runs", () -> h("*****foo*****\n\n___foo___ ___bar___"));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
