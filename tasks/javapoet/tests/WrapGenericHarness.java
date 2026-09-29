import com.squareup.javapoet.*;
import javax.lang.model.element.Modifier;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: line wrapping under complex generic / type-variable / wildcard signatures.
 *  The wrapping contract is the same greedy column-100 rule documented in instruction.md; the
 *  difficulty is computing exact column widths for nested parameterized types, wildcards, and
 *  type-variable bounds and placing the breaks accordingly. */
public class WrapGenericHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }
    static ClassName cn(String p, String n) { return ClassName.get(p, n); }
    static TypeName pt(String p, String n, TypeName... args) { return ParameterizedTypeName.get(cn(p, n), args); }
    static TypeName wildExt(TypeName t) { return WildcardTypeName.subtypeOf(t); }
    static TypeName wildSup(TypeName t) { return WildcardTypeName.supertypeOf(t); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();
        TypeName K = cn("com.example.model", "AggregationKey");
        TypeName V = cn("com.example.model", "MeasurementValue");
        TypeName S = cn("java.lang", "String");

        c.put("wg_nested_three_deep", () -> norm(MethodSpec.methodBuilder("pivot")
            .returns(pt("java.util", "Map", S, pt("java.util", "Map", S, pt("java.util", "List", V))))
            .build().toString()));
        c.put("wg_wildcards", () -> norm(MethodSpec.methodBuilder("transfer")
            .addParameter(pt("java.util.function", "Function", wildSup(K), wildExt(V)), "conversionFunction")
            .build().toString()));
        c.put("wg_bounded_typevar_multi", () -> norm(MethodSpec.methodBuilder("persist")
            .addTypeVariable(TypeVariableName.get("T", cn("com.example.model", "Identifiable"),
                cn("java.io", "Serializable")))
            .addParameter(TypeVariableName.get("T"), "persistableEntity")
            .build().toString()));

        Runner.run(c, args);
    }
}
