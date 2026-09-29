import com.squareup.javapoet.*;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: CodeBlock formatting — placeholders ($L literal, $S string-literal with
 *  escaping, $T type, $N name), positional ($1L) + named (${name}) args, $$ escape, statements,
 *  control flow, indentation, and join/joining. */
public class CodeBlockHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("cb_literal", () -> norm(CodeBlock.of("int x = $L", 42).toString()));
        c.put("cb_string", () -> norm(CodeBlock.of("$S", "hello").toString()));
        c.put("cb_string_escape", () -> norm(CodeBlock.of("$S", "a\"b\tc").toString()));
        c.put("cb_string_newline", () -> norm(CodeBlock.of("$S", "line1\nline2").toString()));
        c.put("cb_string_null", () -> norm(CodeBlock.of("$S", (Object) null).toString()));
        c.put("cb_type", () ->
            norm(CodeBlock.of("$T list", ParameterizedTypeName.get(
                ClassName.get(List.class), ClassName.get(String.class))).toString()));
        c.put("cb_name", () ->
            norm(CodeBlock.of("return $N", FieldSpec.builder(TypeName.INT, "count").build()).toString()));
        c.put("cb_positional", () -> norm(CodeBlock.of("$1L + $1L + $2L", "a", "b").toString()));
        c.put("cb_named", () -> {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("first", "a"); m.put("second", "b");
            return norm(CodeBlock.builder().addNamed("$first:L = $second:L", m).build().toString());
        });
        c.put("cb_dollar_escape", () -> norm(CodeBlock.of("$$$L", "x").toString()));
        c.put("cb_statement", () ->
            norm(CodeBlock.builder().addStatement("int x = $L", 1).build().toString()));
        c.put("cb_control_flow", () ->
            norm(CodeBlock.builder()
                .beginControlFlow("if ($L > 0)", "x")
                .addStatement("return $S", "pos")
                .nextControlFlow("else")
                .addStatement("return $S", "neg")
                .endControlFlow().build().toString()));
        c.put("cb_indent", () ->
            norm(CodeBlock.builder()
                .add("int[] xs = {\n").indent()
                .add("1,\n2,\n").unindent()
                .add("};\n").build().toString()));
        c.put("cb_join", () -> {
            List<CodeBlock> parts = Arrays.asList(
                CodeBlock.of("$S", "a"), CodeBlock.of("$S", "b"), CodeBlock.of("$S", "c"));
            return norm(CodeBlock.join(parts, ", ").toString());
        });

        Runner.run(c, args);
    }
}
