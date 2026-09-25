import io.ediflow.schema.*;
import io.ediflow.stream.*;

import java.io.ByteArrayInputStream;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness PART 2 — the SEGMENT / LOOP occurrence VALIDATION engine. Drives the schema-based
 * validator with a compact custom control schema (ISA..IEA envelope + S01/S09 transaction) and a
 * transaction schema (mandatory S11/S12/S19, optional S13/S14, bounded loops), then reports the
 * ordered stream of segment/occurrence errors for inputs that violate the rules. Self-contained:
 * embeds its own schemas (io.ediflow / http://ediflow.io namespace) and imports only the public
 * io.ediflow.{stream,schema} API. Independent of the tokenizer/element-type drivers.
 */
public class HarnessValidate {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final String ISA =
        "ISA*00*          *00*          *ZZ*ReceiverID     *ZZ*Sender         *050812*1953*^*00501*508121953*0*P*:~";

    // Control schema: interchange ISA..IEA with a required S01..S09 transaction envelope.
    static final String CONTROL =
        "<schema xmlns=\"http://ediflow.io/EDISchema/v4\">"
      + "<interchange header=\"ISA\" trailer=\"IEA\"><sequence>"
      + "<transaction header=\"S01\" trailer=\"S09\" use=\"required\"/></sequence></interchange>"
      + "<elementType name=\"EI01\" base=\"string\" minLength=\"2\" maxLength=\"2\"/>"
      + "<elementType name=\"EI02\" base=\"string\" minLength=\"10\" maxLength=\"10\"/>"
      + "<elementType name=\"EI03\" base=\"string\" minLength=\"2\" maxLength=\"2\"/>"
      + "<elementType name=\"EI04\" base=\"string\" minLength=\"10\" maxLength=\"10\"/>"
      + "<elementType name=\"EI05\" base=\"string\" minLength=\"2\" maxLength=\"2\"/>"
      + "<elementType name=\"EI06\" base=\"string\" minLength=\"15\" maxLength=\"15\"/>"
      + "<elementType name=\"EI07\" base=\"string\" minLength=\"15\" maxLength=\"15\"/>"
      + "<elementType name=\"EI08\" base=\"date\" minLength=\"6\" maxLength=\"6\"/>"
      + "<elementType name=\"EI09\" base=\"time\" minLength=\"4\" maxLength=\"4\"/>"
      + "<elementType name=\"EI65\" base=\"string\"/>"
      + "<elementType name=\"EI11\" base=\"string\" minLength=\"5\" maxLength=\"5\"/>"
      + "<elementType name=\"EI12\" base=\"numeric\" minLength=\"9\" maxLength=\"9\"/>"
      + "<elementType name=\"EI13\" base=\"string\"/>"
      + "<elementType name=\"EI14\" base=\"string\"/>"
      + "<elementType name=\"EI15\" base=\"string\"/>"
      + "<elementType name=\"EI16\" base=\"numeric\" maxLength=\"5\"/>"
      + "<elementType name=\"E999\" base=\"string\"/>"
      + "<segmentType name=\"ISA\"><sequence>"
      + "<element type=\"EI01\" minOccurs=\"1\"/><element type=\"EI02\" minOccurs=\"1\"/><element type=\"EI03\" minOccurs=\"1\"/>"
      + "<element type=\"EI04\" minOccurs=\"1\"/><element type=\"EI05\" minOccurs=\"1\"/><element type=\"EI06\" minOccurs=\"1\"/>"
      + "<element type=\"EI05\" minOccurs=\"1\"/><element type=\"EI07\" minOccurs=\"1\"/><element type=\"EI08\" minOccurs=\"1\"/>"
      + "<element type=\"EI09\" minOccurs=\"1\"/><element type=\"EI65\" minOccurs=\"1\"/><element type=\"EI11\" minOccurs=\"1\"/>"
      + "<element type=\"EI12\" minOccurs=\"1\"/><element type=\"EI13\" minOccurs=\"1\"/><element type=\"EI14\" minOccurs=\"1\"/>"
      + "<element type=\"EI15\" minOccurs=\"1\"/></sequence></segmentType>"
      + "<segmentType name=\"S01\"><sequence><element type=\"E999\" minOccurs=\"1\"/></sequence></segmentType>"
      + "<segmentType name=\"S09\"><sequence><element type=\"E999\" minOccurs=\"1\"/></sequence></segmentType>"
      + "<segmentType name=\"IEA\"><sequence><element type=\"EI16\" minOccurs=\"1\"/><element type=\"EI12\" minOccurs=\"1\"/></sequence></segmentType>"
      + "</schema>";

    // Transaction schema: mandatory S11/S12/S19, optional S13/S14 in loop L0000; bounded loop L0001.
    static final String TXN =
        "<schema xmlns=\"http://ediflow.io/EDISchema/v3\">"
      + "<transaction><sequence>"
      + "<segment ref=\"S0A\"/><segment ref=\"ETY\"/>"
      + "<loop code=\"L0000\"><sequence>"
      + "<segment ref=\"S11\" minOccurs=\"1\"/><segment ref=\"S12\" minOccurs=\"1\"/>"
      + "<segment ref=\"S13\"/><segment ref=\"S14\"/><segment ref=\"S19\" minOccurs=\"1\"/>"
      + "</sequence></loop>"
      + "<loop code=\"L0001\" maxOccurs=\"5\"><sequence>"
      + "<segment ref=\"S20\" minOccurs=\"1\"/><segment ref=\"S21\"/></sequence></loop>"
      + "</sequence></transaction>"
      + "<elementType name=\"E999\" base=\"string\"/>"
      + seg("S0A") + seg("S11") + seg("S12") + seg("S13") + seg("S14") + seg("S19")
      + seg("S20") + seg("S21")
      + "<segmentType name=\"ETY\"><sequence/></segmentType>"
      + "</schema>";

    static String seg(String n) {
        return "<segmentType name=\"" + n + "\"><sequence><element ref=\"E999\" minOccurs=\"1\"/></sequence></segmentType>";
    }

    static String x12(String body) {
        return ISA + "S01*X~" + body + "S09*X~IEA*1*508121953~";
    }

    /** Set the txn schema at START_TRANSACTION, then collect the ordered segment/occurrence errors. */
    static String validate(String edi) {
        try {
            EDIInputFactory f = EDIInputFactory.newFactory();
            Schema ctl = SchemaFactory.newFactory().createSchema(new ByteArrayInputStream(CONTROL.getBytes()));
            EDIStreamReader r = f.createEDIStreamReader(new ByteArrayInputStream(edi.getBytes()), ctl);
            Schema txn = SchemaFactory.newFactory().createSchema(new ByteArrayInputStream(TXN.getBytes()));
            StringBuilder sb = new StringBuilder();
            while (r.hasNext()) {
                EDIStreamEvent e = r.next();
                if (e == EDIStreamEvent.START_TRANSACTION) { r.setTransactionSchema(txn); continue; }
                if (e == EDIStreamEvent.SEGMENT_ERROR || e == EDIStreamEvent.ELEMENT_OCCURRENCE_ERROR) {
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
        // merged: three valid structures (minimal / optionals present / second loop) all -> OK
        c("V_valid", () -> validate(x12("S11*X~S12*X~S19*X~")) + "|"
                         + validate(x12("S11*X~S12*X~S13*X~S14*X~S19*X~")) + "|"
                         + validate(x12("S11*X~S12*X~S19*X~S20*X~S21*X~")));
        c("V_missing_s12",       () -> validate(x12("S11*X~S19*X~")));
        c("V_missing_s19",       () -> validate(x12("S11*X~S12*X~")));
        c("V_missing_s11_s12",   () -> validate(x12("S19*X~")));
        c("V_exceeds_max_s13",   () -> validate(x12("S11*X~S12*X~S13*X~S13*X~S19*X~")));
        c("V_unexpected_segment",() -> validate(x12("S11*X~S12*X~S19*X~S0Z*X~")));
        c("V_out_of_sequence",   () -> validate(x12("S12*X~S11*X~S19*X~")));
        c("V_loop_over_max",     () -> validate(x12("S11*X~S12*X~S19*X~S20*X~S20*X~S20*X~S20*X~S20*X~S20*X~")));
        c("V_required_element_missing", () -> validate(x12("S11~S12*X~S19*X~")));      // S11 missing its required element
        c("V_too_many_elements",        () -> validate(x12("S11*A*B*C~S12*X~S19*X~"))); // S11 defines only 1 element
    }

    public static void main(String[] args) throws Exception { defineCases(); Runner.run(cases, args); }
}
