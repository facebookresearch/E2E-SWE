import io.ediflow.stream.*;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness PART 1 — the EDI TOKENIZER / DIALECT layer (structural parse only, validation
 * OFF). Exercises the reader event sequence, X12 fixed-width ISA delimiter inference, EDIFACT UNA /
 * UNB service-string handling, composites, repetition and release characters, across the public
 * io.ediflow.stream API. Imports ONLY io.ediflow.stream.* so it compiles for any submission that
 * implements the reader, independent of the schema/validation API. Oracle values live in the
 * committed /tests/expected.tsv (captured from the reference). CAPTURE=1 prints name<TAB>value.
 */
public class HarnessParse {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    // ---- EDI samples (structural; content values are arbitrary, only tokenization is tested) ----
    static final String X12 =
        "ISA*00*          *00*          *ZZ*ReceiverID     *ZZ*Sender         *050812*1953*^*00501*508121953*0*P*:~"
      + "GS*FA*ReceiverDept*SenderDept*20050812*195335*000005*X*005010X230~"
      + "ST*997*0001~"
      + "AK1*FA*000000001~"
      + "SE*3*0001~"
      + "GE*1*000005~"
      + "IEA*1*508121953~";

    // X12 with a composite (component separator ':') in a data element
    static final String X12_COMP =
        "ISA*00*          *00*          *ZZ*ReceiverID     *ZZ*Sender         *050812*1953*^*00501*508121953*0*P*:~"
      + "GS*FA*R*S*20050812*195335*1*X*005010~"
      + "ST*997*0001~"
      + "AK9*A*1:2:3*X~"
      + "SE*2*0001~"
      + "GE*1*1~"
      + "IEA*1*508121953~";

    // EDIFACT with explicit UNA service string advice
    static final String EDIFACT =
        "UNA:+.? '"
      + "UNB+UNOA:1+SENDER+RECEIVER+240101:1200+1'"
      + "UNH+00000000000117+INVOIC:D:97B:UN'"
      + "UNT+2+00000000000117'"
      + "UNZ+1+1'";

    // EDIFACT WITHOUT UNA (defaults inferred from UNB / UNOA)
    static final String EDIFACT_NOUNA =
        "UNB+UNOA:1+SENDER+RECEIVER+240101:1200+1'"
      + "UNH+1+ORDERS:D:96A:UN'"
      + "UNT+2+1'"
      + "UNZ+1+1'";

    // EDIFACT using the release character to escape a component separator inside data
    static final String EDIFACT_REL =
        "UNA:+.? '"
      + "UNB+UNOA:1+A+B+240101:1200+1'"
      + "UNH+1+X:D:96A:UN'"
      + "FTX+AAA+++PRICE IS 5?:1 RATIO'"
      + "UNT+3+1'"
      + "UNZ+1+1'";

    static EDIInputFactory factory() {
        EDIInputFactory f = EDIInputFactory.newFactory();
        f.setProperty(EDIInputFactory.EDI_VALIDATE_CONTROL_STRUCTURE, "false"); // pure structural parse
        return f;
    }

    /** Compact deterministic dump of the event stream + text payloads. */
    static String events(String edi) {
        StringBuilder out = new StringBuilder();
        try (InputStream in = new ByteArrayInputStream(edi.getBytes());
             EDIStreamReader r = factory().createEDIStreamReader(in)) {
            while (r.hasNext()) {
                EDIStreamEvent e = r.next();
                switch (e) {
                    case START_INTERCHANGE: out.append("II "); break;
                    case END_INTERCHANGE:   out.append("/II "); break;
                    // Envelope events (group/transaction/loop) are schema-dependent; this pure
                    // tokenizer driver (no schema) ignores them — they are exercised, with a schema,
                    // by the validation drivers. Skipping keeps the dump a tokenizer-only contract.
                    case START_GROUP:  case END_GROUP:
                    case START_TRANSACTION: case END_TRANSACTION:
                    case START_LOOP:   case END_LOOP:
                        break;
                    case START_SEGMENT:     out.append("S:").append(r.getText()).append(' '); break;
                    case END_SEGMENT:       out.append("/S "); break;
                    case START_COMPOSITE:   out.append("C "); break;
                    case END_COMPOSITE:     out.append("/C "); break;
                    case ELEMENT_DATA:      out.append("e:").append(r.getText()).append(' '); break;
                    default:                out.append(e).append(' '); break;
                }
            }
        } catch (Exception ex) {
            return "ERR:" + ex.getClass().getSimpleName();
        }
        return out.toString().trim();
    }

    /** Delimiters map rendered deterministically (sorted by key). */
    static String delims(String edi) {
        try (InputStream in = new ByteArrayInputStream(edi.getBytes());
             EDIStreamReader r = factory().createEDIStreamReader(in)) {
            r.next(); // START_INTERCHANGE — delimiters known from here
            Map<String, Character> d = r.getDelimiters();
            return new TreeMap<>(d).toString();
        } catch (Exception ex) {
            return "ERR:" + ex.getClass().getSimpleName();
        }
    }

    static String stdver(String edi) {
        try (InputStream in = new ByteArrayInputStream(edi.getBytes());
             EDIStreamReader r = factory().createEDIStreamReader(in)) {
            r.next();
            return r.getStandard() + "|" + Arrays.toString(r.getVersion());
        } catch (Exception ex) {
            return "ERR:" + ex.getClass().getSimpleName();
        }
    }

    static void defineCases() {
        c("P_x12_events",         () -> events(X12));
        c("P_x12_delimiters",     () -> delims(X12));
        c("P_x12_standard_ver",   () -> stdver(X12));
        c("P_x12_composite",      () -> events(X12_COMP));
        c("P_edifact_events",     () -> events(EDIFACT));
        // merged: both EDIFACT delimiter derivations (UNA service-string parse + UNOA defaults)
        c("P_edifact_delimiters", () -> delims(EDIFACT) + "||" + delims(EDIFACT_NOUNA));
        c("P_edifact_standard_ver", () -> stdver(EDIFACT));
        c("P_edifact_nouna_events", () -> events(EDIFACT_NOUNA));
        c("P_edifact_release_char", () -> events(EDIFACT_REL));
        // delimiters queried before START_INTERCHANGE -> IllegalStateException (deterministic)
        c("P_delims_before_interchange", () -> {
            try (InputStream in = new ByteArrayInputStream(X12.getBytes());
                 EDIStreamReader r = factory().createEDIStreamReader(in)) {
                try { r.getDelimiters(); return "NO_THROW"; }
                catch (IllegalStateException ex) { return "ISE"; }
            } catch (Exception ex) { return "ERR:" + ex.getClass().getSimpleName(); }
        });
    }

    public static void main(String[] args) throws Exception { defineCases(); Runner.run(cases, args); }
}
