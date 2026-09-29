import io.ediflow.schema.*;
import io.ediflow.stream.*;

import java.io.ByteArrayInputStream;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness PART 3 — ELEMENT DATA-TYPE validation + SCHEMA LOADING. Drives the element
 * validators (numeric / date / time / identifier-with-enumeration / length-constrained string) via a
 * typed transaction schema, and exercises SchemaFactory.createSchema loading/rejection. Self-
 * contained: embeds its schemas (io.ediflow / http://ediflow.io namespace), imports only the public
 * io.ediflow.{stream,schema} API. Independent of the tokenizer/segment-validation drivers.
 */
public class HarnessSchema {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final String ISA =
        "ISA*00*          *00*          *ZZ*ReceiverID     *ZZ*Sender         *050812*1953*^*00501*508121953*0*P*:~";

    // Minimal control schema: ISA..IEA envelope with an S01..S09 transaction (elements unconstrained).
    static final String CONTROL =
        "<schema xmlns=\"http://ediflow.io/EDISchema/v4\">"
      + "<interchange header=\"ISA\" trailer=\"IEA\"><sequence>"
      + "<transaction header=\"S01\" trailer=\"S09\" use=\"required\"/></sequence></interchange>"
      + "<elementType name=\"A2\" base=\"string\" minLength=\"2\" maxLength=\"2\"/>"
      + "<elementType name=\"A10\" base=\"string\" minLength=\"10\" maxLength=\"10\"/>"
      + "<elementType name=\"A15\" base=\"string\" minLength=\"15\" maxLength=\"15\"/>"
      + "<elementType name=\"DT\" base=\"date\" minLength=\"6\" maxLength=\"6\"/>"
      + "<elementType name=\"TM\" base=\"time\" minLength=\"4\" maxLength=\"4\"/>"
      + "<elementType name=\"AN\" base=\"string\"/>"
      + "<elementType name=\"N5\" base=\"numeric\" minLength=\"5\" maxLength=\"5\"/>"
      + "<elementType name=\"N9\" base=\"numeric\" minLength=\"9\" maxLength=\"9\"/>"
      + "<elementType name=\"NM5\" base=\"numeric\" maxLength=\"5\"/>"
      + "<elementType name=\"E999\" base=\"string\"/>"
      + "<segmentType name=\"ISA\"><sequence>"
      + "<element type=\"A2\" minOccurs=\"1\"/><element type=\"A10\" minOccurs=\"1\"/><element type=\"A2\" minOccurs=\"1\"/>"
      + "<element type=\"A10\" minOccurs=\"1\"/><element type=\"A2\" minOccurs=\"1\"/><element type=\"A15\" minOccurs=\"1\"/>"
      + "<element type=\"A2\" minOccurs=\"1\"/><element type=\"A15\" minOccurs=\"1\"/><element type=\"DT\" minOccurs=\"1\"/>"
      + "<element type=\"TM\" minOccurs=\"1\"/><element type=\"AN\" minOccurs=\"1\"/><element type=\"N5\" minOccurs=\"1\"/>"
      + "<element type=\"N9\" minOccurs=\"1\"/><element type=\"AN\" minOccurs=\"1\"/><element type=\"AN\" minOccurs=\"1\"/>"
      + "<element type=\"AN\" minOccurs=\"1\"/></sequence></segmentType>"
      + "<segmentType name=\"S01\"><sequence><element type=\"E999\" minOccurs=\"1\"/></sequence></segmentType>"
      + "<segmentType name=\"S09\"><sequence><element type=\"E999\" minOccurs=\"1\"/></sequence></segmentType>"
      + "<segmentType name=\"IEA\"><sequence><element type=\"NM5\" minOccurs=\"1\"/><element type=\"N9\" minOccurs=\"1\"/></sequence></segmentType>"
      + "</schema>";

    // Typed transaction schema: TST segment carrying one element of each interesting base type.
    static final String TXN =
        "<schema xmlns=\"http://ediflow.io/EDISchema/v3\">"
      + "<transaction><sequence><segment ref=\"TST\" maxOccurs=\"50\"/></sequence></transaction>"
      + "<elementType name=\"NUM\" base=\"numeric\" minLength=\"1\" maxLength=\"3\"/>"
      + "<elementType name=\"DAT\" base=\"date\" minLength=\"8\" maxLength=\"8\"/>"
      + "<elementType name=\"TIM\" base=\"time\" minLength=\"4\" maxLength=\"4\"/>"
      + "<elementType name=\"COD\" base=\"identifier\" minLength=\"2\" maxLength=\"2\">"
      + "<enumeration><value>AA</value><value>BB</value></enumeration></elementType>"
      + "<elementType name=\"STR\" base=\"string\" minLength=\"2\" maxLength=\"4\"/>"
      + "<elementType name=\"DEC\" base=\"decimal\" minLength=\"1\" maxLength=\"8\"/>"
      + "<segmentType name=\"TST\"><sequence>"
      + "<element ref=\"NUM\"/><element ref=\"DAT\"/><element ref=\"TIM\"/><element ref=\"COD\"/><element ref=\"STR\"/><element ref=\"DEC\"/>"
      + "</sequence></segmentType>"
      + "</schema>";

    static Schema schema(String xml) throws Exception {
        return SchemaFactory.newFactory().createSchema(new ByteArrayInputStream(xml.getBytes()));
    }

    /** Collect ordered ELEMENT_DATA errors for a TST body validated against the typed txn schema. */
    static String elem(String body) {
        try {
            EDIInputFactory f = EDIInputFactory.newFactory();
            EDIStreamReader r = f.createEDIStreamReader(
                new ByteArrayInputStream((ISA + "S01*X~" + body + "S09*X~IEA*1*508121953~").getBytes()), schema(CONTROL));
            Schema txn = schema(TXN);
            StringBuilder sb = new StringBuilder();
            while (r.hasNext()) {
                EDIStreamEvent e = r.next();
                if (e == EDIStreamEvent.START_TRANSACTION) { r.setTransactionSchema(txn); continue; }
                if (e == EDIStreamEvent.ELEMENT_DATA_ERROR) {
                    if (sb.length() > 0) sb.append(',');
                    sb.append(r.getErrorType()).append(':').append(r.getText());
                }
            }
            r.close();
            return sb.length() == 0 ? "OK" : sb.toString();
        } catch (Exception ex) {
            return "ERR:" + ex.getClass().getSimpleName();
        }
    }

    static void defineCases() {
        // element data-type validation
        c("S_valid_row",     () -> elem("TST*12*20240115*1230*AA*abc~"));
        c("S_num_nonnumeric",() -> elem("TST*1A~"));
        c("S_num_too_long",  () -> elem("TST*1234~"));
        c("S_date_invalid",  () -> elem("TST*12*20241315*1230*AA*abc~"));
        c("S_time_nonnumeric",() -> elem("TST*12*20240115*12AB~"));         // non-digit time -> INVALID_TIME (distinct branch)
        c("S_code_invalid",  () -> elem("TST*12*20240115*1230*ZZ*abc~"));
        c("S_str_too_short", () -> elem("TST*12*20240115*1230*AA*a~"));
        c("S_str_too_long",  () -> elem("TST*12*20240115*1230*AA*abcde~"));
        c("S_multi_errors",  () -> elem("TST*1A*20241315*2599*ZZ*a~"));
        c("S_date_feb29_nonleap", () -> elem("TST*12*20230229~"));            // Feb 29 in non-leap 2023
        c("S_date_day00",         () -> elem("TST*12*20240100~"));            // day 00 invalid
        c("S_time_hour24",        () -> elem("TST*12*20240115*2400~"));       // hour 24 invalid
        c("S_decimal_bad",        () -> elem("TST*12*20240115*1230*AA*abc*12A~")); // non-numeric decimal
        c("S_date_month00",       () -> elem("TST*12*20240015~"));                 // month 00 invalid
        c("S_time_minute60",      () -> elem("TST*12*20240115*2360~"));            // minute 60 invalid
        c("S_num_has_dot",        () -> elem("TST*1.5~"));                         // '.' in a numeric element
        // schema loading / rejection
        c("SL_load_ok",      () -> { try { Schema s = schema(TXN);
                                            return s.getType("TST").getType() + "|" + s.getType("NUM").getType(); }
                                     catch (Exception e) { return "ERR:" + e.getClass().getSimpleName(); } });
        c("SL_malformed",    () -> { try { schema("<schema xmlns=\"http://ediflow.io/EDISchema/v3\"><nonsense/></schema>"); return "NO_THROW"; }
                                     catch (Exception e) { return "THROWS:" + e.getClass().getSimpleName(); } });
        c("SL_bad_namespace",() -> { try { schema("<schema xmlns=\"http://example.com/wrong\"><transaction><sequence/></transaction></schema>"); return "NO_THROW"; }
                                     catch (Exception e) { return "THROWS:" + e.getClass().getSimpleName(); } });
    }

    public static void main(String[] args) throws Exception { defineCases(); Runner.run(cases, args); }
}
