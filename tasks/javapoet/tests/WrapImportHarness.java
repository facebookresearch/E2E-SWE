import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: the hard emit machinery — automatic line wrapping at column 100 (one shared
 *  greedy soft-wrap: parameters and throws both fill left-to-right, breaking at fixed wrap points
 *  when the next token would exceed 100), static-import collapse ($T.member emitted bare with the
 *  declaring class not imported), nested-type imports, and simple-name collision resolution
 *  (same-package wins; first-seen wins; others fully-qualified). */
public class WrapImportHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }
    static ClassName cn(String pkg, String name) { return ClassName.get(pkg, name); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        // ---- line wrapping (MethodSpec.toString renders through a 100-column CodeWriter) ----
        c.put("wrap_params_three", () -> norm(MethodSpec.methodBuilder("configure")
            .addModifiers(Modifier.PUBLIC)
            .addParameter(cn("com.example.config", "Configuration"), "configuration")
            .addParameter(cn("com.example.config", "ConfigurationOptions"), "options")
            .addParameter(cn("com.example.config", "ConfigurationListener"), "listener")
            .build().toString()));
        c.put("wrap_params_five", () -> norm(MethodSpec.methodBuilder("register")
            .addParameter(cn("com.example.domain", "AlphaComponent"), "alpha")
            .addParameter(cn("com.example.domain", "BetaComponent"), "beta")
            .addParameter(cn("com.example.domain", "GammaComponent"), "gamma")
            .addParameter(cn("com.example.domain", "DeltaComponent"), "delta")
            .addParameter(cn("com.example.domain", "EpsilonComponent"), "epsilon")
            .build().toString()));
        c.put("wrap_throws_fill", () -> norm(MethodSpec.methodBuilder("run")
            .addException(cn("com.example.exceptions", "FirstVeryLongException"))
            .addException(cn("com.example.exceptions", "SecondVeryLongException"))
            .addException(cn("com.example.exceptions", "ThirdVeryLongException"))
            .build().toString()));
        c.put("wrap_params_and_throws", () -> norm(MethodSpec.methodBuilder("process")
            .addParameter(cn("com.example.io", "InputSourceDescriptor"), "source")
            .addParameter(cn("com.example.io", "OutputSinkDescriptor"), "sink")
            .addException(cn("com.example.io", "ResourceUnavailableException"))
            .build().toString()));
        c.put("wrap_typevars", () -> norm(MethodSpec.methodBuilder("transform")
            .addTypeVariable(TypeVariableName.get("InputElementType"))
            .addTypeVariable(TypeVariableName.get("OutputElementType"))
            .returns(TypeVariableName.get("OutputElementType"))
            .addParameter(TypeVariableName.get("InputElementType"), "inputElementValue")
            .addParameter(cn("com.example.func", "TransformationStrategy"), "strategy")
            .build().toString()));

        // ---- static-import collapse ($T.member -> bare member; declaring class not imported) ----
        c.put("static_import_field_pi", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo").addMethod(MethodSpec.methodBuilder("area")
                    .returns(TypeName.DOUBLE).addParameter(TypeName.DOUBLE, "r")
                    .addStatement("return $T.PI * r * r", cn("java.lang", "Math")).build()).build())
            .addStaticImport(cn("java.lang", "Math"), "PI").build().toString()));
        c.put("static_import_two_members", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo").addMethod(MethodSpec.methodBuilder("bounds")
                    .returns(TypeName.INT).addParameter(TypeName.INT, "x")
                    .addStatement("return $T.max(0, $T.min(x, 100))",
                        cn("java.lang", "Math"), cn("java.lang", "Math")).build()).build())
            .addStaticImport(cn("java.lang", "Math"), "max", "min").build().toString()));

        // ---- nested-type imports & collision resolution ----
        c.put("import_nested_entry", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo")
                    .addField(ClassName.get("java.util", "Map", "Entry"), "entry", Modifier.PRIVATE).build())
            .build().toString()));
        c.put("collision_own_package", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo")
                    .addField(cn("com.example", "Bar"), "localBar", Modifier.PRIVATE)
                    .addField(cn("com.other", "Bar"), "otherBar", Modifier.PRIVATE).build())
            .build().toString()));
        c.put("collision_three_way", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo")
                    .addField(cn("java.util", "List"), "a", Modifier.PRIVATE)
                    .addField(cn("java.awt", "List"), "b", Modifier.PRIVATE)
                    .addField(cn("com.example.custom", "List"), "cc", Modifier.PRIVATE).build())
            .build().toString()));
        c.put("collision_javalang", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo")
                    .addField(cn("java.lang", "Integer"), "boxed", Modifier.PRIVATE)
                    .addField(cn("com.example.math", "Integer"), "custom", Modifier.PRIVATE).build())
            .build().toString()));

        // ---- additional wrapping / static-import variants (all exercise the same algorithm) ----
        c.put("wrap_return_generic", () -> norm(MethodSpec.methodBuilder("index")
            .returns(ParameterizedTypeName.get(cn("java.util", "Map"),
                cn("com.example.model", "DocumentIdentifier"),
                ParameterizedTypeName.get(cn("java.util", "List"), cn("com.example.model", "TokenPosition"))))
            .addParameter(cn("com.example.model", "DocumentCollection"), "documents")
            .build().toString()));
        c.put("wrap_annotated_params", () -> norm(MethodSpec.methodBuilder("bind")
            .addParameter(ParameterSpec.builder(cn("com.example.di", "ServiceRegistry"), "registry")
                .addAnnotation(cn("com.example.di", "InjectedDependency")).build())
            .addParameter(ParameterSpec.builder(cn("com.example.di", "ServiceScope"), "scope")
                .addAnnotation(cn("com.example.di", "InjectedDependency")).build())
            .build().toString()));
        c.put("wrap_in_javafile", () -> norm(JavaFile.builder("com.example",
                TypeSpec.classBuilder("Foo").addMethod(MethodSpec.methodBuilder("dispatch")
                    .addParameter(cn("com.example.event", "IncomingRequestEnvelope"), "incomingRequestEnvelope")
                    .addParameter(cn("com.example.event", "ResponseChannelHandler"), "responseChannelHandler")
                    .addParameter(cn("com.example.event", "DispatchContextObject"), "dispatchContextObject")
                    .build()).build())
            .build().toString()));

        // ---- further line-wrapping scenarios (the 100-col LineWrapper is the difficulty core) ----
        c.put("wrap_varargs", () -> norm(MethodSpec.methodBuilder("aggregate")
            .addParameter(cn("com.example.metrics", "AggregationContext"), "aggregationContext")
            .addParameter(ArrayTypeName.of(cn("com.example.metrics", "MetricSampleValue")), "metricSampleValues")
            .varargs()
            .build().toString()));
        c.put("wrap_single_long_param", () -> norm(MethodSpec.methodBuilder("accept")
            .addParameter(ParameterizedTypeName.get(cn("java.util.function", "BiFunction"),
                cn("com.example.model", "RequestContextDescriptor"),
                cn("com.example.model", "ResponseContextDescriptor"),
                cn("com.example.model", "InteractionOutcomeResult")), "interactionHandlerFunction")
            .build().toString()));
        c.put("wrap_return_and_throws", () -> norm(MethodSpec.methodBuilder("load")
            .returns(ParameterizedTypeName.get(cn("java.util", "Optional"),
                cn("com.example.model", "PersistentEntityRecord")))
            .addParameter(cn("com.example.model", "EntityIdentifierValue"), "identifier")
            .addException(cn("com.example.store", "StorageBackendUnavailableException"))
            .build().toString()));
        c.put("wrap_nested_generic_param", () -> norm(MethodSpec.methodBuilder("reduce")
            .addParameter(ParameterizedTypeName.get(cn("java.util", "Map"),
                cn("com.example.key", "CompositeGroupingKey"),
                ParameterizedTypeName.get(cn("java.util", "List"), cn("com.example.val", "MeasurementSample"))),
                "groupedMeasurementSamples")
            .build().toString()));

        Runner.run(c, args);
    }
}
