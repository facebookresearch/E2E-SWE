import com.squareup.javapoet.*;
import java.util.*;
import java.util.function.Supplier;

/** Capability group: NameAllocator — unique-name allocation with collision suffixing, Java
 *  keyword avoidance, tag lookup, and toJavaIdentifier normalisation of illegal characters. */
public class NameAllocatorHarness {
    static String norm(String s) { return s.replace("\n", "\\n"); }

    public static void main(String[] args) throws Exception {
        LinkedHashMap<String, Supplier<String>> c = new LinkedHashMap<>();

        c.put("na_basic", () -> {
            NameAllocator na = new NameAllocator();
            return norm(na.newName("foo"));
        });
        c.put("na_collision", () -> {
            NameAllocator na = new NameAllocator();
            String a = na.newName("foo");
            String b = na.newName("foo");
            return norm(a + "," + b);
        });
        c.put("na_keyword", () -> {
            NameAllocator na = new NameAllocator();
            return norm(na.newName("public"));
        });
        c.put("na_tag_lookup", () -> {
            NameAllocator na = new NameAllocator();
            na.newName("value", 1);
            return norm(na.get(1));
        });
        c.put("na_illegal_chars", () -> norm(NameAllocator.toJavaIdentifier("a-b c")));
        c.put("na_leading_digit", () -> norm(NameAllocator.toJavaIdentifier("1st")));

        Runner.run(c, args);
    }
}
