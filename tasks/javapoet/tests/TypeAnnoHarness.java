import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: reasoning-heavy semantics that are documented but require the model to reason
 *  about *placement*, not just format — type-use annotations (JSR-308: annotation on a type vs a
 *  type argument vs an array vs an array component), nested-vs-top-level collision resolution,
 *  enum bodies with members (the ';' terminator), and instance/static initializer ordering. */
public class TypeAnnoHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }
    static ClassName cn(String p, String n) { return ClassName.get(p, n); }
    static AnnotationSpec anno(String p, String n) { return AnnotationSpec.builder(cn(p, n)).build(); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        // ---- type-use annotations: placement is the reasoning ----
        c.put("anno_typearg", () -> norm(ParameterizedTypeName.get(ClassName.get(List.class),
            cn("java.lang", "String").annotated(anno("com.example", "Nullable"))).toString()));
        c.put("anno_field_type", () -> norm(FieldSpec.builder(
            cn("java.lang", "String").annotated(anno("com.example", "Nullable")), "name").build().toString()));
        c.put("anno_two_on_type", () -> norm(FieldSpec.builder(
            cn("java.lang", "String").annotated(anno("com.example", "Nullable"), anno("com.example", "Interned")),
            "name").build().toString()));
        c.put("anno_array_component", () -> norm(ArrayTypeName.of(
            cn("java.lang", "String").annotated(anno("com.example", "Nullable"))).toString()));
        c.put("anno_on_array", () -> norm(ArrayTypeName.of(cn("java.lang", "String"))
            .annotated(anno("com.example", "Nullable")).toString()));

        // ---- nested-vs-top-level collision ----
        c.put("collision_nested_vs_top", () -> norm(JavaFile.builder("com.example",
            TypeSpec.classBuilder("Foo")
                .addField(ClassName.get("java.util", "Map", "Entry"), "e1", Modifier.PRIVATE)
                .addField(cn("com.example.model", "Entry"), "e2", Modifier.PRIVATE).build())
            .build().toString()));

        // ---- annotation arrays (class literals; nested annotations) ----
        c.put("anno_class_array", () -> norm(AnnotationSpec.builder(cn("com.example", "Uses"))
            .addMember("value", "$T.class", cn("com.example", "Foo"))
            .addMember("value", "$T.class", cn("com.example", "Bar")).build().toString()));
        c.put("anno_of_annotations", () -> norm(AnnotationSpec.builder(cn("com.example", "Group"))
            .addMember("checks", "$L", AnnotationSpec.builder(cn("com.example", "Check")).addMember("id", "$L", 1).build())
            .addMember("checks", "$L", AnnotationSpec.builder(cn("com.example", "Check")).addMember("id", "$L", 2).build())
            .build().toString()));

        // ---- enum with members (';' after constants) + init-block ordering ----
        c.put("enum_with_members", () -> norm(TypeSpec.enumBuilder("Planet")
            .addModifiers(Modifier.PUBLIC)
            .addEnumConstant("EARTH", TypeSpec.anonymousClassBuilder("$L", 5.97).build())
            .addField(TypeName.DOUBLE, "mass", Modifier.PRIVATE, Modifier.FINAL)
            .addMethod(MethodSpec.constructorBuilder().addParameter(TypeName.DOUBLE, "mass")
                .addStatement("this.$N = $N", "mass", "mass").build())
            .build().toString()));
        c.put("two_init_blocks", () -> norm(TypeSpec.classBuilder("C")
            .addStaticBlock(CodeBlock.builder().addStatement("$T.load()", cn("com.example", "Registry")).build())
            .addInitializerBlock(CodeBlock.builder().addStatement("init()").build())
            .build().toString()));

        Runner.run(c, args);
    }
}
