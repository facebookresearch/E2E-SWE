import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: TypeSpec emission — class/interface/enum/annotation/anonymous types,
 *  superclass + interfaces, type variables, nested types, fields/methods, initializer blocks,
 *  enum constants (incl. anonymous bodies). toString() emits fully-qualified names. */
public class TypeSpecHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("class_empty", () ->
            norm(TypeSpec.classBuilder("Foo").build().toString()));
        c.put("class_public_final", () ->
            norm(TypeSpec.classBuilder("Foo")
                .addModifiers(Modifier.PUBLIC, Modifier.FINAL).build().toString()));
        c.put("class_field_method", () ->
            norm(TypeSpec.classBuilder("Point")
                .addModifiers(Modifier.PUBLIC)
                .addField(TypeName.INT, "x", Modifier.PRIVATE, Modifier.FINAL)
                .addMethod(MethodSpec.methodBuilder("getX")
                    .addModifiers(Modifier.PUBLIC).returns(TypeName.INT)
                    .addStatement("return x").build())
                .build().toString()));
        c.put("class_extends_implements", () ->
            norm(TypeSpec.classBuilder("MyList")
                .superclass(ParameterizedTypeName.get(ClassName.get(AbstractList.class),
                    ClassName.get(String.class)))
                .addSuperinterface(ClassName.get("java.io", "Serializable"))
                .build().toString()));
        c.put("class_typevar", () ->
            norm(TypeSpec.classBuilder("Box")
                .addTypeVariable(TypeVariableName.get("T"))
                .addField(TypeVariableName.get("T"), "value", Modifier.PRIVATE)
                .build().toString()));
        c.put("interface_basic", () ->
            norm(TypeSpec.interfaceBuilder("Shape")
                .addModifiers(Modifier.PUBLIC)
                .addMethod(MethodSpec.methodBuilder("area")
                    .addModifiers(Modifier.PUBLIC, Modifier.ABSTRACT)
                    .returns(TypeName.DOUBLE).build())
                .build().toString()));
        c.put("enum_constants", () ->
            norm(TypeSpec.enumBuilder("Color")
                .addModifiers(Modifier.PUBLIC)
                .addEnumConstant("RED").addEnumConstant("GREEN").addEnumConstant("BLUE")
                .build().toString()));
        c.put("enum_anonymous_body", () ->
            norm(TypeSpec.enumBuilder("Operation")
                .addEnumConstant("PLUS", TypeSpec.anonymousClassBuilder("")
                    .addMethod(MethodSpec.methodBuilder("apply")
                        .addModifiers(Modifier.PUBLIC).returns(TypeName.INT)
                        .addParameter(TypeName.INT, "a").addParameter(TypeName.INT, "b")
                        .addStatement("return a + b").build())
                    .build())
                .build().toString()));
        c.put("annotation_type", () ->
            norm(TypeSpec.annotationBuilder("MyAnno")
                .addModifiers(Modifier.PUBLIC)
                .addMethod(MethodSpec.methodBuilder("value")
                    .addModifiers(Modifier.PUBLIC, Modifier.ABSTRACT)
                    .returns(ClassName.get(String.class)).build())
                .build().toString()));
        c.put("anonymous_class", () ->
            norm(TypeSpec.classBuilder("Holder")
                .addField(FieldSpec.builder(ClassName.get(Runnable.class), "r")
                    .initializer("$L", TypeSpec.anonymousClassBuilder("")
                        .addSuperinterface(ClassName.get(Runnable.class))
                        .addMethod(MethodSpec.methodBuilder("run")
                            .addModifiers(Modifier.PUBLIC)
                            .addAnnotation(ClassName.get("java.lang", "Override"))
                            .build())
                        .build())
                    .build())
                .build().toString()));
        c.put("nested_type", () ->
            norm(TypeSpec.classBuilder("Outer")
                .addType(TypeSpec.classBuilder("Inner")
                    .addModifiers(Modifier.STATIC).build())
                .build().toString()));
        c.put("static_block", () ->
            norm(TypeSpec.classBuilder("Config")
                .addField(ClassName.get(String.class), "NAME", Modifier.STATIC, Modifier.FINAL)
                .addStaticBlock(CodeBlock.builder()
                    .addStatement("NAME = $S", "config").build())
                .build().toString()));

        Runner.run(c, args);
    }
}
