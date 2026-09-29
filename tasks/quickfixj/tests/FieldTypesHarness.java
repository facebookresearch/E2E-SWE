import io.fix.*;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- typed Field&lt;T&gt; subclasses (spec §2 "Typed Field classes"). One case
 * exercises the constructor + getValue/setValue round-trip + inherited base-class accessors
 * (getTag, getField, getObject) across every typed subclass in the API surface.
 */
public class FieldTypesHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        c("typed_fields_construct_and_getters_all_types", () -> {
            try {
                // IntField
                IntField i = new IntField(34, 42);
                if (i.getTag() != 34 || i.getField() != 34 || i.getValue() != 42
                        || !Integer.valueOf(42).equals(i.getObject())) return "FAIL:IntField";
                i.setValue(100); if (i.getValue() != 100)              return "FAIL:IntField.setValue";

                // DoubleField
                DoubleField d = new DoubleField(44, 150.50);
                if (d.getTag() != 44 || d.getValue() != 150.50)        return "FAIL:DoubleField";
                d.setValue(200.0); if (d.getValue() != 200.0)          return "FAIL:DoubleField.setValue";

                // StringField
                StringField s = new StringField(58, "hello world");
                if (s.getTag() != 58 || !"hello world".equals(s.getValue())) return "FAIL:StringField";
                s.setValue("bye"); if (!"bye".equals(s.getValue()))    return "FAIL:StringField.setValue";

                // CharField
                CharField ch = new CharField(54, '1');
                if (ch.getTag() != 54 || ch.getValue() != '1')         return "FAIL:CharField";
                ch.setValue('2'); if (ch.getValue() != '2')            return "FAIL:CharField.setValue";

                // BooleanField
                BooleanField b = new BooleanField(43, true);
                if (b.getTag() != 43 || !b.getValue())                 return "FAIL:BooleanField";
                b.setValue(false); if (b.getValue())                   return "FAIL:BooleanField.setValue";

                // DecimalField
                DecimalField dec = new DecimalField(44, new BigDecimal("150.50"));
                if (dec.getTag() != 44 || dec.getValue().compareTo(new BigDecimal("150.50")) != 0)
                                                                        return "FAIL:DecimalField";
                dec.setValue(new BigDecimal("200.75"));
                if (dec.getValue().compareTo(new BigDecimal("200.75")) != 0) return "FAIL:DecimalField.setValue";

                // BytesField
                byte[] bytesA = new byte[] { (byte) 0x00, (byte) 0x01, (byte) 0x7F, (byte) 0xFF };
                BytesField by = new BytesField(96, bytesA);
                if (by.getTag() != 96 || !java.util.Arrays.equals(by.getValue(), bytesA))
                                                                        return "FAIL:BytesField";
                byte[] bytesB = new byte[] { (byte) 0xAA };
                by.setValue(bytesB);
                if (!java.util.Arrays.equals(by.getValue(), bytesB))   return "FAIL:BytesField.setValue";

                // UtcTimeStampField
                UtcTimeStampField ts = new UtcTimeStampField(52);
                LocalDateTime now = LocalDateTime.of(2024, 1, 1, 10, 0, 0, 500_000_000);
                ts.setValue(now);
                if (ts.getTag() != 52 || !now.equals(ts.getValue()))   return "FAIL:UtcTimeStampField";

                // UtcDateOnlyField + UtcTimeOnlyField
                UtcDateOnlyField dt = new UtcDateOnlyField(432);
                LocalDate date = LocalDate.of(2024, 1, 15); dt.setValue(date);
                if (!date.equals(dt.getValue()))                       return "FAIL:UtcDateOnlyField";
                UtcTimeOnlyField tt = new UtcTimeOnlyField(273);
                LocalTime time = LocalTime.of(10, 30, 45); tt.setValue(time);
                if (!time.equals(tt.getValue()))                       return "FAIL:UtcTimeOnlyField";

                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
