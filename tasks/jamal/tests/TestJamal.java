import javax0.jamal.engine.Processor;
import javax0.jamal.api.BadSyntax;

/**
 * Comprehensive standalone test harness for the Jamal macro processing library.
 * Outputs JSON lines (one per test) to stdout for automated grading.
 * No JUnit dependency — pure Java + stdlib.
 */
public class TestJamal {

    static int passed = 0;
    static int failed = 0;

    /** Escape a string for safe JSON embedding. */
    static String esc(String s) {
        if (s == null) return "null";
        return s.replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }

    /** Test that processing input produces the expected output. */
    static void check(String name, String input, String expected) {
        try (Processor p = new Processor("{", "}")) {
            String result = p.process(input);
            if (result.equals(expected)) {
                passed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
            } else {
                failed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\"expected: ["
                        + esc(expected) + "] got: [" + esc(result) + "]\"}");
            }
        } catch (Exception e) {
            failed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\""
                    + esc(e.getClass().getSimpleName() + ": " + e.getMessage()) + "\"}");
        }
    }

    /** Test that processing input produces a non-empty output (content not checked). */
    static void checkNonEmpty(String name, String input) {
        try (Processor p = new Processor("{", "}")) {
            String result = p.process(input);
            if (result != null && !result.isEmpty()) {
                passed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
            } else {
                failed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\"expected non-empty result but got empty\"}");
            }
        } catch (Exception e) {
            failed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\""
                    + esc(e.getClass().getSimpleName() + ": " + e.getMessage()) + "\"}");
        }
    }

    /** Test that processing input produces the expected output (trimmed comparison). */
    static void checkTrimmed(String name, String input, String expected) {
        try (Processor p = new Processor("{", "}")) {
            String result = p.process(input);
            if (result.trim().equals(expected.trim())) {
                passed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
            } else {
                failed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\"expected: ["
                        + esc(expected) + "] got: [" + esc(result) + "]\"}");
            }
        } catch (Exception e) {
            failed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\""
                    + esc(e.getClass().getSimpleName() + ": " + e.getMessage()) + "\"}");
        }
    }

    /** Test that processing input throws an exception (BadSyntax or similar). */
    static void checkThrows(String name, String input) {
        try (Processor p = new Processor("{", "}")) {
            String result = p.process(input);
            failed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\"expected exception but got: ["
                    + esc(result) + "]\"}");
        } catch (BadSyntax e) {
            passed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
        } catch (Exception e) {
            // Any exception counts as a pass for error-case tests
            passed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
        }
    }

    /** Test that processing input produces output containing the expected substring. */
    static void checkContains(String name, String input, String needle) {
        try (Processor p = new Processor("{", "}")) {
            String result = p.process(input);
            if (result != null && result.contains(needle)) {
                passed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"passed\"}");
            } else {
                failed++;
                System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\"expected to contain: ["
                        + esc(needle) + "] got: [" + esc(result) + "]\"}");
            }
        } catch (Exception e) {
            failed++;
            System.out.println("{\"name\":\"" + esc(name) + "\",\"status\":\"failed\",\"message\":\""
                    + esc(e.getClass().getSimpleName() + ": " + e.getMessage()) + "\"}");
        }
    }

    public static void main(String[] args) {


        // ====================================================================
        // 2. DEFINE AND EXPAND — basic user macro definitions
        // ====================================================================
        check("define_verbatim_param_replacement",
                "{@define ~ xx(a,b,c,d)=a{b}c{d}}{xx/bbb/ccc/ddd/aaa}",
                "bbb{ccc}ddd{aaa}");
        check("define_tail_argument",
                "{@define [tail] x(a,b,c)=a b c}{x/1/2/3/4/5}", "1 2 3/4/5");


        // ====================================================================
        // 5. VERBATIM DEFINE — result not re-evaluated
        // ====================================================================
        check("verbatim_option",
                "{@define [verbatim] a={@code}}{a}", "{@code}");
        check("verbatim_prevents_reeval",
                "{@define b=2}{@define ~ a={b}}{a}", "{b}");
        check("verbatim_post_eval_expands",
                "{@define b=2}{@define ~ a={b}}{!a}", "2");

        // ====================================================================
        // 6. GLOBAL DEFINE AND DEFAULT MACRO
        // ====================================================================
        check("default_macro_catches_undefined",
                "{@define default=wupppps...}{something}", "wupppps...");

        // ====================================================================
        // 8. IF / ELSE CONDITIONALS
        // ====================================================================
        check("if_false_zero",
                "{@if /0/true/false}", "false");
        check("if_false_no_else_returns_empty",
                "{@if/0/anything can come here}", "");
        check("if_eval_option",
                "{@define a=true}{@if [eval]|{a}| this is the output| this is not the output}",
                " this is the output");
        // ====================================================================
        // 9. FOR LOOPS
        // ====================================================================
        check("for_evalist",
                "{@define x=a,b,c}{@for [evalist] z in ({x})=z z z}",
                "a a ab b bc c c");

        // ====================================================================
        // 10. SEP — change macro delimiters
        // ====================================================================
        check("sep_two_char",
                "{@sep []}[@define a=aaa][a]", "aaa");
        check("sep_with_space",
                "{@sep [ ]}[@define a=aaa][a]", "aaa");
        check("sep_slash_format",
                "{@sep/[/]}[@define a=aaa][a]", "aaa");
        check("sep_multi_char_delimiters",
                "{@sep ((   )) }((@define a=aaa))((a))", "aaa");

        // ====================================================================
        // 11. EVAL — nested evaluation
        // ====================================================================
        check("eval_deferred",
                "{@define a=2}{a}{@eval {`a}}", "2{a}");


        // ====================================================================
        // 13. ESCAPE — preserve content verbatim
        // ====================================================================
        check("escape_empty",
                "{@escape `|``|`}", "");

        // ====================================================================
        // 14. BLOCK — scoping and export
        // ====================================================================
        check("block_does_not_export",
                "{#block {@define this=AAA}this is a bloc}{?this}", "");
        check("block_flat_exports",
                "{#block [flat]{@define this=AAA}this is a bloc}{?this}", "AAA");
        check("block_define_and_export_option",
                "{#block {@define [export] a=1}}{a}", "1");

        // ====================================================================
        // 15. BEGIN / END — explicit scope markers
        // ====================================================================
        check("begin_end_scope",
                "{@define a=1}{a}{@begin azaza}{a}{@define a=2}{a}{@end azaza}{a}",
                "1121");

        // ====================================================================
        // 16. TRY / CATCH — error handling
        // ====================================================================
        checkContains("try_bang_returns_error_message",
                "{@try! {undefinedMacro}}", "undefinedMacro");
        checkTrimmed("try_bang_returns_output_on_success",
                "{@try! just blabla}", "just blabla");
        checkTrimmed("catch_after_error",
                "{@try {undefinedMacro}}{@catch 1}", "1");
        checkTrimmed("catch_executes_only_once",
                "{@try {undefinedMacro}}{@catch 1}{@catch 2}", "1");

        // ====================================================================
        // 17. EXPORT — move macro to parent scope
        // ====================================================================
        check("export_single",
                "{#block {@define a=1}{@export a}}{a}", "1");
        check("export_multiple",
                "{#block {@define a=1}{@define b=1}{@export a, b}}{a}{b}", "11");

        // ====================================================================
        // 19. IDENT — return content verbatim (unevaluated)
        // ====================================================================
        check("ident_verbatim",
                "{@ident this is {uneva} luated}", "this is {uneva} luated");

        // ====================================================================
        // 20. OPTIONS — set processing options
        // ====================================================================
        check("options_negate",
                "{@options a}{a}{@begin s}{@options ~a}{a}{@end s}{a}",
                "truefalsetrue");

        // ====================================================================
        // 21. USER-DEFINED MACRO POST-EVALUATION — backtick and bang
        // ====================================================================
        check("post_eval_chain",
                "{@define a=this is it}\\\n"
                + "{@define b={`a}}\\\n"
                + "{@define c={`b}}\\\n"
                + "{@define userDefined={`c}}\\\n"
                + "{userDefined}\n"
                + "{!userDefined}\n"
                + "{!!userDefined}\n"
                + "{!!!userDefined}",
                "{c}\n{b}\n{a}\nthis is it");

        // ====================================================================
        // 22. RECURSIVE DEFINITIONS
        // ====================================================================
        check("recursive_define",
                "{@define wilfred=define}{#{wilfred} alfred=wilfred}{alfred}",
                "wilfred");

        // ====================================================================
        // 23. USER-DEFINED MACRO SCOPING
        // ====================================================================
        check("ud_scope_locking",
                "{@define a={b}}{a {@define b=this is b}}", "this is b");
        check("ud_scope_not_exported",
                "{@try {@define a={b}}{a {@define b=this is b}}{b}}", "");
        check("ud_scope_exported",
                "{@define a={b}}{a {@define b=this is b}{@export b}} {b}",
                "this is b this is b");

        // ====================================================================
        // 25. SEP — advanced delimiter switching
        // ====================================================================
        check("sep_define_param_new_delims",
                "{@sep []}[@define f(x)=<x>][f hello]", "<hello>");
        check("sep_nested_double_change",
                "{@sep []}[@define a=one][@sep << >>]<<@define b=two>><<a>><<b>>",
                "onetwo");
        check("sep_restore_to_original",
                "{@sep []}[@define a=AAA][@sep]{@define b=BBB}{a}{b}",
                "AAABBB");
        check("sep_old_delims_literal_text",
                "{@sep []}[@define a=ok]text { and } here [a]",
                "text { and } here ok");

        // ====================================================================
        // 26. SCOPE/EXPORT — advanced scoping tests
        // ====================================================================
        check("scope_block_two_defs_isolated",
                "{@define x=outer}{#block {@define x=inner}{@define y=only_inside}}{x}{?y}",
                "outer");
        check("scope_export_param_macro",
                "{#block {@define greet(name)=Hi name!}{@export greet}}{greet World}",
                "Hi World!");
        check("scope_nested_export_chain",
                "{#block {#block {@define z=deep}{@export z}}{@export z}}{z}",
                "deep");
        check("scope_begin_end_define_invisible",
                "{@begin s}{@define tmp=local}{tmp}{@end s}{?tmp}",
                "local");
        check("scope_nested_begin_end_three_levels",
                "{@define v=0}{@begin outer}{@define v=1}{@begin inner}{@define v=2}{v}{@end inner}{v}{@end outer}{v}",
                "210");

        // ====================================================================
        // 27. ESCAPE — advanced escape tests
        // ====================================================================
        check("escape_preserves_macro_define",
                "{@escape `X`{@define a=x}{a}`X`}", "{@define a=x}{a}");
        check("escape_long_escape_string",
                "{@escape `|||`Hello {World} \\n\\t`|||`}", "Hello {World} \\n\\t");
        check("escape_mixed_with_real_macro",
                "{@define x=real}{x} and {@escape `Z`{x}`Z`}",
                "real and {x}");
        check("escape_unbalanced_braces",
                "{@escape `|`{ { { }}`|`}", "{ { { }}");

        // ====================================================================
        // 28. DEFERRED EVALUATION — backtick and bang advanced tests
        // ====================================================================
        check("deferred_single_backtick",
                "{@define a=hello}{`a}", "{a}");
        check("deferred_double_backtick",
                "{@define a=hello}{``a}", "{`a}");
        check("deferred_verbatim_chain",
                "{@define a=final}{@define ~ b={a}}{@define ~ c={b}}{c} {!c} {!!c}",
                "{b} {a} final");
        check("deferred_nonverbatim_backtick_body",
                "{@define a=hello}{@define b={`a}}{b} and {!b}",
                "{a} and hello");

        // ====================================================================
        // 29. FOR LOOP — advanced formatting and options
        // ====================================================================
        check("for_multivariable_with_join",
                "{@for [join=;](k,v) in (name|Alice,age|30)=k=v}",
                "name=Alice;age=30");
        check("for_skipEmpty_with_join",
                "{@for [skipEmpty join=-]x in (a,,b,,c)=x}", "a-b-c");
        check("for_trim_with_join",
                "{@for [trim join=,]x in ( a , b , c )=x}", "a,b,c");
        check("for_hash_expands_macro_in_template",
                "{@define w=*}{#for x in (a,b,c)=({w}x{w})}",
                "(*a*)(*b*)(*c*)");
        check("for_lenient_fewer_values",
                "{@for [lenient](x,y,z) in (a|1,b|2|extra)=x-y-z}",
                "a-1-b-2-extra");

        // ====================================================================
        // 30. OPTIONS — advanced option tests
        // ====================================================================
        check("options_multiple_selective_negate",
                "{@options a|b|c}{a} {b} {c}{@options ~b} {a} {b} {c}",
                "true true true true false true");

        // ====================================================================
        // Summary
        // ====================================================================
        System.out.println("{\"name\":\"__summary__\",\"status\":\"" + (failed == 0 ? "passed" : "failed")
                + "\",\"message\":\"passed=" + passed + " failed=" + failed + "\"}");
    }
}
