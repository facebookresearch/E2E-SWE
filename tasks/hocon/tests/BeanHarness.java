import com.lattice.config.*;

import java.time.Duration;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness — ConfigBeanFactory.create: binding a resolved Config subtree onto a JavaBean
 * (zero-arg constructor + getters/setters). Exercises primitive/boxed coercion, enums, typed lists,
 * java.time.Duration and ConfigMemorySize fields, camelCase-vs-hyphen key preference, unknown-key
 * handling, and the validation error contract.
 *
 * Design: one bundled case per distinct bean-mapping behavior, using public static nested beans.
 */
public class BeanHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static String ex(Runnable r) {
        try { r.run(); return "NONE"; }
        catch (Throwable t) { return t.getClass().getSimpleName(); }
    }

    static Config cfg(String s) { return ConfigFactory.parseString(s).resolve(); }

    public enum Color { RED, GREEN, BLUE }

    public static class ScalarBean {
        private int count; private long total; private double ratio; private boolean enabled; private String name;
        public int getCount() { return count; } public void setCount(int v) { count = v; }
        public long getTotal() { return total; } public void setTotal(long v) { total = v; }
        public double getRatio() { return ratio; } public void setRatio(double v) { ratio = v; }
        public boolean getEnabled() { return enabled; } public void setEnabled(boolean v) { enabled = v; }
        public String getName() { return name; } public void setName(String v) { name = v; }
    }

    public static class ListBean {
        private List<Integer> nums; private List<String> words;
        public List<Integer> getNums() { return nums; } public void setNums(List<Integer> v) { nums = v; }
        public List<String> getWords() { return words; } public void setWords(List<String> v) { words = v; }
    }

    public static class EnumBean {
        private Color color; private List<Color> palette;
        public Color getColor() { return color; } public void setColor(Color v) { color = v; }
        public List<Color> getPalette() { return palette; } public void setPalette(List<Color> v) { palette = v; }
    }

    public static class UnitBean {
        private Duration timeout; private ConfigMemorySize maxSize;
        public Duration getTimeout() { return timeout; } public void setTimeout(Duration v) { timeout = v; }
        public ConfigMemorySize getMaxSize() { return maxSize; } public void setMaxSize(ConfigMemorySize v) { maxSize = v; }
    }

    public static class CamelBean {
        private int fooBar;
        public int getFooBar() { return fooBar; } public void setFooBar(int v) { fooBar = v; }
    }

    static {
        // ---- Scalar bean: primitive/boxed coercion incl. string->number and string->boolean ----
        c("bean_scalars", () -> {
            ScalarBean b = ConfigBeanFactory.create(
                cfg("count = 3, total = \"400\", ratio = 1, enabled = yes, name = svc"), ScalarBean.class);
            return "count=" + b.getCount() + "|total=" + b.getTotal()
                 + "|ratio=" + b.getRatio() + "|enabled=" + b.getEnabled() + "|name=" + b.getName();
        });

        // ---- Typed lists bind to List<Integer> / List<String> ----
        c("bean_lists", () -> {
            ListBean b = ConfigBeanFactory.create(
                cfg("nums = [1, 2, 3], words = [a, b]"), ListBean.class);
            return "nums=" + b.getNums() + "|words=" + b.getWords();
        });

        // ---- Enum fields bind from their name; enum lists too ----
        c("bean_enums", () -> {
            EnumBean b = ConfigBeanFactory.create(
                cfg("color = GREEN, palette = [RED, BLUE]"), EnumBean.class);
            return "color=" + b.getColor() + "|palette=" + b.getPalette();
        });

        // ---- Invalid enum value raises BadValue ----
        c("bean_bad_enum", () ->
            ex(() -> ConfigBeanFactory.create(cfg("color = PURPLE, palette = []"), EnumBean.class)));

        // ---- Duration and ConfigMemorySize fields parse unit strings ----
        c("bean_units", () -> {
            UnitBean b = ConfigBeanFactory.create(
                cfg("timeout = 5s, max-size = 1M"), UnitBean.class);
            return "timeoutMs=" + b.getTimeout().toMillis() + "|maxBytes=" + b.getMaxSize().toBytes();
        });

        // ---- camelCase bean property binds from a hyphen-separated config key ----
        c("bean_camel_from_hyphen", () -> {
            CamelBean b = ConfigBeanFactory.create(cfg("foo-bar = 7"), CamelBean.class);
            return "fooBar=" + b.getFooBar();
        });

        // ---- Unknown config keys are ignored by default ----
        c("bean_unknown_ignored", () -> {
            ScalarBean b = ConfigBeanFactory.create(
                cfg("count = 1, total = 2, ratio = 1, enabled = true, name = x, extra = ignored"),
                ScalarBean.class);
            return "count=" + b.getCount() + "|name=" + b.getName();
        });

        // ---- A missing required (non-optional) property raises ValidationFailed ----
        c("bean_missing_required", () ->
            ex(() -> ConfigBeanFactory.create(cfg("count = 1"), ScalarBean.class)));
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
