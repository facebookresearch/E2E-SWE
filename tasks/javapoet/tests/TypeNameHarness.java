import com.squareup.javapoet.*;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: TypeName family (ClassName, ParameterizedTypeName, ArrayTypeName,
 *  WildcardTypeName, TypeVariableName, primitives, boxing) — canonical-name emission via toString(). */
public class TypeNameHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("tn_primitive_int", () -> norm(TypeName.INT.toString()));
        c.put("tn_void", () -> norm(TypeName.VOID.toString()));
        c.put("tn_box_int", () -> norm(TypeName.INT.box().toString()));
        c.put("tn_unbox_integer", () -> norm(ClassName.get("java.lang", "Integer").unbox().toString()));
        c.put("tn_is_boxed", () -> norm(String.valueOf(ClassName.get("java.lang", "Long").isBoxedPrimitive())));

        c.put("cn_object", () -> norm(ClassName.OBJECT.toString()));
        c.put("cn_get_class", () -> norm(ClassName.get(String.class).toString()));
        c.put("cn_nested", () -> norm(ClassName.get("com.example", "Foo").nestedClass("Bar").toString()));
        c.put("cn_bestguess_nested", () -> norm(ClassName.bestGuess("com.example.Foo.Bar").toString()));
        c.put("cn_peer", () -> norm(ClassName.get("com.example", "Foo", "Bar").peerClass("Baz").toString()));
        c.put("cn_simplename", () -> norm(ClassName.get("com.example", "Foo", "Bar").simpleName()));
        c.put("cn_reflectionname", () -> norm(ClassName.get("com.example", "Foo", "Bar").reflectionName()));
        c.put("cn_canonicalname", () -> norm(ClassName.get("com.example", "Foo", "Bar").canonicalName()));

        c.put("ptn_list_string", () ->
            norm(ParameterizedTypeName.get(ClassName.get(List.class), ClassName.get(String.class)).toString()));
        c.put("ptn_map_two", () ->
            norm(ParameterizedTypeName.get(ClassName.get(Map.class),
                ClassName.get(String.class), ClassName.get(Integer.class)).toString()));
        c.put("ptn_nested_generic", () ->
            norm(ParameterizedTypeName.get(ClassName.get(Map.class), ClassName.get(String.class),
                ParameterizedTypeName.get(ClassName.get(List.class), ClassName.get(Integer.class))).toString()));
        c.put("ptn_inner", () ->
            norm(ParameterizedTypeName.get(ClassName.get(Map.class),
                ClassName.get(String.class), ClassName.get(Integer.class))
                .nestedClass("Entry").toString()));

        c.put("array_int", () -> norm(ArrayTypeName.of(TypeName.INT).toString()));
        c.put("array_string", () -> norm(ArrayTypeName.of(ClassName.get(String.class)).toString()));
        c.put("array_2d", () -> norm(ArrayTypeName.of(ArrayTypeName.of(ClassName.get(String.class))).toString()));
        c.put("array_of_generic", () ->
            norm(ArrayTypeName.of(ParameterizedTypeName.get(
                ClassName.get(List.class), ClassName.get(String.class))).toString()));

        c.put("wild_extends", () -> norm(WildcardTypeName.subtypeOf(ClassName.get(Number.class)).toString()));
        c.put("wild_super", () -> norm(WildcardTypeName.supertypeOf(ClassName.get(String.class)).toString()));
        c.put("wild_object", () -> norm(WildcardTypeName.subtypeOf(ClassName.OBJECT).toString()));
        c.put("ptn_wildcard_arg", () ->
            norm(ParameterizedTypeName.get(ClassName.get(List.class),
                WildcardTypeName.subtypeOf(ClassName.get(Number.class))).toString()));

        c.put("typevar_plain", () -> norm(TypeVariableName.get("T").toString()));
        c.put("ptn_typevar_arg", () ->
            norm(ParameterizedTypeName.get(ClassName.get(List.class), TypeVariableName.get("E")).toString()));

        Runner.run(c, args);
    }
}
