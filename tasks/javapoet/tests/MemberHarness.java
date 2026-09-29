import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: FieldSpec + ParameterSpec declaration emission (modifiers, initializers,
 *  annotations, javadoc). toString() emits fully-qualified type names (no import context). */
public class MemberHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("field_simple", () ->
            norm(FieldSpec.builder(TypeName.INT, "count").build().toString()));
        c.put("field_modifiers", () ->
            norm(FieldSpec.builder(ClassName.get(String.class), "name",
                Modifier.PRIVATE, Modifier.FINAL).build().toString()));
        c.put("field_initializer", () ->
            norm(FieldSpec.builder(TypeName.INT, "count", Modifier.PRIVATE)
                .initializer("$L", 0).build().toString()));
        c.put("field_string_initializer", () ->
            norm(FieldSpec.builder(ClassName.get(String.class), "greeting", Modifier.STATIC, Modifier.FINAL)
                .initializer("$S", "hi").build().toString()));
        c.put("field_annotation", () ->
            norm(FieldSpec.builder(TypeName.INT, "x")
                .addAnnotation(ClassName.get("java.lang", "Deprecated")).build().toString()));
        c.put("field_javadoc", () ->
            norm(FieldSpec.builder(TypeName.INT, "x")
                .addJavadoc("The count.\n").build().toString()));
        c.put("field_generic", () ->
            norm(FieldSpec.builder(ParameterizedTypeName.get(ClassName.get(List.class),
                ClassName.get(String.class)), "items", Modifier.PRIVATE).build().toString()));

        c.put("param_simple", () ->
            norm(ParameterSpec.builder(TypeName.INT, "x").build().toString()));
        c.put("param_final", () ->
            norm(ParameterSpec.builder(ClassName.get(String.class), "name", Modifier.FINAL)
                .build().toString()));
        c.put("param_annotated", () ->
            norm(ParameterSpec.builder(ClassName.get(String.class), "name")
                .addAnnotation(ClassName.get("java.lang", "Deprecated")).build().toString()));
        c.put("param_generic", () ->
            norm(ParameterSpec.builder(ParameterizedTypeName.get(ClassName.get(Map.class),
                ClassName.get(String.class), ClassName.get(Integer.class)), "m").build().toString()));

        Runner.run(c, args);
    }
}
