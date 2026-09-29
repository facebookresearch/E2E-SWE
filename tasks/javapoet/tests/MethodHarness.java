import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: MethodSpec emission (return type, parameters, modifiers, throws, type
 *  variables, varargs, constructors, abstract methods, code bodies + control flow). */
public class MethodHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("method_empty", () ->
            norm(MethodSpec.methodBuilder("foo").build().toString()));
        c.put("method_returns", () ->
            norm(MethodSpec.methodBuilder("count").returns(TypeName.INT)
                .addStatement("return 0").build().toString()));
        c.put("method_public_static", () ->
            norm(MethodSpec.methodBuilder("main")
                .addModifiers(Modifier.PUBLIC, Modifier.STATIC)
                .addParameter(ArrayTypeName.of(ClassName.get(String.class)), "args")
                .build().toString()));
        c.put("method_params", () ->
            norm(MethodSpec.methodBuilder("add").returns(TypeName.INT)
                .addParameter(TypeName.INT, "a").addParameter(TypeName.INT, "b")
                .addStatement("return a + b").build().toString()));
        c.put("method_throws", () ->
            norm(MethodSpec.methodBuilder("read")
                .addException(ClassName.get("java.io", "IOException"))
                .build().toString()));
        c.put("method_abstract", () ->
            norm(MethodSpec.methodBuilder("compute")
                .addModifiers(Modifier.ABSTRACT).returns(TypeName.INT)
                .build().toString()));
        c.put("method_constructor", () ->
            norm(MethodSpec.constructorBuilder()
                .addModifiers(Modifier.PUBLIC)
                .addParameter(TypeName.INT, "x")
                .addStatement("this.x = x").build().toString()));
        c.put("method_varargs", () ->
            norm(MethodSpec.methodBuilder("of")
                .addParameter(ArrayTypeName.of(ClassName.get(String.class)), "names")
                .varargs().build().toString()));
        c.put("method_typevar", () ->
            norm(MethodSpec.methodBuilder("identity")
                .addTypeVariable(TypeVariableName.get("T"))
                .returns(TypeVariableName.get("T"))
                .addParameter(TypeVariableName.get("T"), "t")
                .addStatement("return t").build().toString()));
        c.put("method_typevar_bounded", () ->
            norm(MethodSpec.methodBuilder("max")
                .addTypeVariable(TypeVariableName.get("T",
                    ParameterizedTypeName.get(ClassName.get(Comparable.class), TypeVariableName.get("T"))))
                .returns(TypeVariableName.get("T"))
                .addParameter(TypeVariableName.get("T"), "a")
                .addParameter(TypeVariableName.get("T"), "b")
                .addStatement("return a.compareTo(b) >= 0 ? a : b").build().toString()));
        c.put("method_control_flow", () ->
            norm(MethodSpec.methodBuilder("sum").returns(TypeName.INT)
                .addParameter(TypeName.INT, "n")
                .addStatement("int total = 0")
                .beginControlFlow("for (int i = 0; i < n; i++)")
                .addStatement("total += i")
                .endControlFlow()
                .addStatement("return total").build().toString()));
        c.put("method_default", () ->
            norm(MethodSpec.methodBuilder("greeting")
                .addModifiers(Modifier.PUBLIC, Modifier.DEFAULT)
                .returns(ClassName.get(String.class))
                .addStatement("return $S", "hi").build().toString()));

        Runner.run(c, args);
    }
}
