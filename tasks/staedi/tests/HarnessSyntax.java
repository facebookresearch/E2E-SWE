import io.ediflow.schema.*;
import io.ediflow.stream.*;

import java.io.ByteArrayInputStream;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness PART 6 — element-level SYNTAX-RULE validation (EDISchema <syntax>: paired /
 * required / exclusion / conditional positional rules on a segment's elements). Drives the validator
 * with a transaction schema whose segments carry <syntax> rules, then feeds bodies that satisfy or
 * violate them, asserting the exact error taxonomy + location (getText() is empty for a MISSING
 * element, so the oracle is errorType@segmentTag:elementPosition). Self-contained: embeds its schemas
 * (io.ediflow / http://ediflow.io namespace), imports only io.ediflow.{stream,schema}.
 */
public class HarnessSyntax {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final String ISA =
        "ISA*00*          *00*          *ZZ*ReceiverID     *ZZ*Sender         *050812*1953*^*00501*508121953*0*P*:~";

    // Control schema: ISA..IEA envelope with an S01..S09 transaction (same as the validation drivers).
    static final String CONTROL = """
        <schema xmlns="http://ediflow.io/EDISchema/v4">
          <interchange header="ISA" trailer="IEA"><sequence>
            <transaction header="S01" trailer="S09" use="required"/></sequence></interchange>
          <elementType name="EI01" base="string" minLength="2" maxLength="2"/>
          <elementType name="EI02" base="string" minLength="10" maxLength="10"/>
          <elementType name="EI03" base="string" minLength="2" maxLength="2"/>
          <elementType name="EI04" base="string" minLength="10" maxLength="10"/>
          <elementType name="EI05" base="string" minLength="2" maxLength="2"/>
          <elementType name="EI06" base="string" minLength="15" maxLength="15"/>
          <elementType name="EI07" base="string" minLength="15" maxLength="15"/>
          <elementType name="EI08" base="date" minLength="6" maxLength="6"/>
          <elementType name="EI09" base="time" minLength="4" maxLength="4"/>
          <elementType name="EI65" base="string"/>
          <elementType name="EI11" base="string" minLength="5" maxLength="5"/>
          <elementType name="EI12" base="numeric" minLength="9" maxLength="9"/>
          <elementType name="EI13" base="string"/>
          <elementType name="EI14" base="string"/>
          <elementType name="EI15" base="string"/>
          <elementType name="EI16" base="numeric" maxLength="5"/>
          <elementType name="E999" base="string"/>
          <segmentType name="ISA"><sequence>
            <element type="EI01" minOccurs="1"/><element type="EI02" minOccurs="1"/><element type="EI03" minOccurs="1"/>
            <element type="EI04" minOccurs="1"/><element type="EI05" minOccurs="1"/><element type="EI06" minOccurs="1"/>
            <element type="EI05" minOccurs="1"/><element type="EI07" minOccurs="1"/><element type="EI08" minOccurs="1"/>
            <element type="EI09" minOccurs="1"/><element type="EI65" minOccurs="1"/><element type="EI11" minOccurs="1"/>
            <element type="EI12" minOccurs="1"/><element type="EI13" minOccurs="1"/><element type="EI14" minOccurs="1"/>
            <element type="EI15" minOccurs="1"/>
          </sequence></segmentType>
          <segmentType name="S01"><sequence><element type="E999" minOccurs="1"/></sequence></segmentType>
          <segmentType name="S09"><sequence><element type="E999" minOccurs="1"/></sequence></segmentType>
          <segmentType name="IEA"><sequence><element type="EI16" minOccurs="1"/><element type="EI12" minOccurs="1"/></sequence></segmentType>
        </schema>
        """;

    // Transaction schema: four segments, each carrying a different <syntax> rule over its 3 elements.
    static final String TXN = """
        <schema xmlns="http://ediflow.io/EDISchema/v4">
          <transaction><sequence>
            <segment type="TSP"/><segment type="TSR"/><segment type="TSE"/><segment type="TSC"/>
            <segment type="TSS"/><segment type="TSL"/><segment type="TSF"/>
          </sequence></transaction>
          <elementType name="DE" base="string" maxLength="10"/>
          <segmentType name="TSP"><sequence><element type="DE"/><element type="DE"/><element type="DE"/></sequence>
            <syntax type="paired"><position>1</position><position>2</position><position>3</position></syntax></segmentType>
          <segmentType name="TSR"><sequence><element type="DE"/><element type="DE"/><element type="DE"/></sequence>
            <syntax type="required"><position>1</position><position>2</position><position>3</position></syntax></segmentType>
          <segmentType name="TSE"><sequence><element type="DE"/><element type="DE"/><element type="DE"/></sequence>
            <syntax type="exclusion"><position>1</position><position>2</position><position>3</position></syntax></segmentType>
          <segmentType name="TSC"><sequence><element type="DE"/><element type="DE"/><element type="DE"/></sequence>
            <syntax type="conditional"><position>1</position><position>2</position><position>3</position></syntax></segmentType>
          <segmentType name="TSS"><sequence><element type="DE"/><element type="DE"/></sequence>
            <syntax type="single"><position>1</position><position>2</position></syntax></segmentType>
          <segmentType name="TSL"><sequence><element type="DE"/><element type="DE"/><element type="DE"/></sequence>
            <syntax type="list"><position>1</position><position>2</position><position>3</position></syntax></segmentType>
          <segmentType name="TSF"><sequence><element type="DE"/><element type="DE"/><element type="DE"/></sequence>
            <syntax type="firstonly"><position>1</position><position>2</position><position>3</position></syntax></segmentType>
        </schema>
        """;

    /** Set the txn schema at START_TRANSACTION; collect syntax errors as errorType@segTag:elementPos. */
    static String syn(String body) {
        try {
            EDIInputFactory f = EDIInputFactory.newFactory();
            Schema ctl = SchemaFactory.newFactory().createSchema(new ByteArrayInputStream(CONTROL.getBytes()));
            EDIStreamReader r = f.createEDIStreamReader(
                new ByteArrayInputStream((ISA + "S01*X~" + body + "S09*X~IEA*1*508121953~").getBytes()), ctl);
            Schema txn = SchemaFactory.newFactory().createSchema(new ByteArrayInputStream(TXN.getBytes()));
            StringBuilder sb = new StringBuilder();
            while (r.hasNext()) {
                EDIStreamEvent e = r.next();
                if (e == EDIStreamEvent.START_TRANSACTION) { r.setTransactionSchema(txn); continue; }
                if (e == EDIStreamEvent.ELEMENT_OCCURRENCE_ERROR || e == EDIStreamEvent.SEGMENT_ERROR) {
                    if (sb.length() > 0) sb.append(',');
                    // errorType-only: a missing element has empty getText(), and Location is not part
                    // of the documented reader surface; the error type + count is the syntax assertion.
                    sb.append(r.getErrorType());
                }
            }
            r.close();
            return sb.length() == 0 ? "OK" : sb.toString();
        } catch (Exception ex) {
            return "ERR:" + ex.getClass().getSimpleName();
        }
    }

    static void defineCases() {
        c("Y_paired_violation",      () -> syn("TSP*A~"));        // 1 of 3 present -> all-or-none violated
        c("Y_paired_ok",            () -> syn("TSP*A*B*C~"));     // all present -> OK
        c("Y_required_violation",    () -> syn("TSR~"));          // none present -> required violated
        c("Y_exclusion_violation",   () -> syn("TSE*A*B~"));      // two present -> exclusion violated
        c("Y_exclusion_ok",         () -> syn("TSE*A~"));         // one present -> OK
        c("Y_conditional_violation", () -> syn("TSC*A~"));        // anchor present, rest absent -> violated
        c("Y_conditional_ok_no_anchor", () -> syn("TSC**B~"));    // anchor absent -> conditional silent -> OK
        c("Y_single_violation",      () -> syn("TSS*A*B~"));     // single: >1 used -> exclusion
        c("Y_list_violation",        () -> syn("TSL*A~"));       // list: anchor used but nothing else
        c("Y_firstonly_violation",   () -> syn("TSF*A*B~"));     // firstonly: anchor + another used
    }

    public static void main(String[] args) throws Exception { defineCases(); Runner.run(cases, args); }
}
