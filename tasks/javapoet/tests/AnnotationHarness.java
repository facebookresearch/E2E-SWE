import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: AnnotationSpec emission — marker annotations, single/multiple members,
 *  array-valued members (single vs multi-line), nested annotations, and class-literal values.
 *  toString() emits fully-qualified annotation type names. */
public class AnnotationHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("anno_marker", () ->
            norm(AnnotationSpec.builder(ClassName.get("java.lang", "Override")).build().toString()));
        c.put("anno_single_member", () ->
            norm(AnnotationSpec.builder(ClassName.get("java.lang", "SuppressWarnings"))
                .addMember("value", "$S", "unchecked").build().toString()));
        c.put("anno_int_member", () ->
            norm(AnnotationSpec.builder(ClassName.get("com.example", "Timeout"))
                .addMember("millis", "$L", 1000).build().toString()));
        c.put("anno_multi_member", () ->
            norm(AnnotationSpec.builder(ClassName.get("com.example", "Config"))
                .addMember("name", "$S", "svc")
                .addMember("enabled", "$L", true).build().toString()));
        c.put("anno_array", () ->
            norm(AnnotationSpec.builder(ClassName.get("java.lang", "SuppressWarnings"))
                .addMember("value", "$S", "unchecked")
                .addMember("value", "$S", "rawtypes").build().toString()));
        c.put("anno_class_value", () ->
            norm(AnnotationSpec.builder(ClassName.get("com.example", "Mapped"))
                .addMember("type", "$T.class", ClassName.get("java.lang", "String"))
                .build().toString()));
        c.put("anno_nested", () ->
            norm(AnnotationSpec.builder(ClassName.get("com.example", "Outer"))
                .addMember("inner", "$L", AnnotationSpec.builder(ClassName.get("com.example", "Inner"))
                    .addMember("value", "$S", "x").build())
                .build().toString()));

        Runner.run(c, args);
    }
}
