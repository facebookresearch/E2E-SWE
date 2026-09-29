import io.ediflow.stream.*;

import java.io.ByteArrayOutputStream;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness PART 4 — the EDI WRITER / SERIALIZER layer. Drives the fluent EDIStreamWriter to
 * produce EDI byte streams for both dialects (X12 fixed-width ISA envelope; EDIFACT with defaulted
 * service characters), exercising simple elements, composites (writeStartElement / writeComponent /
 * endElement), empty elements/components, repeat elements, and multi-segment interchanges. Each case
 * asserts the EXACT produced EDI string (read back from the ByteArrayOutputStream as UTF-8), so a
 * broken serializer diverges byte-for-byte. Self-contained: imports ONLY io.ediflow.stream.*, so it
 * compiles for any submission implementing the writer independently of the reader/schema drivers.
 * Oracle values live in the committed /tests/expected.tsv (captured from the reference).
 */
public class HarnessWrite {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    /** A body of writer calls between startInterchange() and endInterchange(). */
    interface Body { void write(EDIStreamWriter w) throws Exception; }

    /** Run the writer body against a fresh writer and return the exact produced EDI string. */
    static String render(Body body) {
        try {
            ByteArrayOutputStream baos = new ByteArrayOutputStream();
            EDIOutputFactory f = EDIOutputFactory.newFactory();
            EDIStreamWriter w = f.createEDIStreamWriter(baos);
            w.startInterchange();
            body.write(w);
            w.endInterchange();
            w.close(); // flushes; does NOT close baos
            return baos.toString("UTF-8");
        } catch (Exception e) {
            return "ERR:" + e.getClass().getSimpleName();
        }
    }

    /** Write a complete, well-formed 106-char X12 ISA header segment (defaults * : ^ ~ match). */
    static EDIStreamWriter isa(EDIStreamWriter w) throws Exception {
        return w.writeStartSegment("ISA")
                .writeElement("00").writeElement("          ")
                .writeElement("00").writeElement("          ")
                .writeElement("ZZ").writeElement("ReceiverID     ")
                .writeElement("ZZ").writeElement("Sender         ")
                .writeElement("050812").writeElement("1953")
                .writeElement("^").writeElement("00501")
                .writeElement("508121953").writeElement("0")
                .writeElement("P").writeElement(":")
                .writeEndSegment();
    }

    /** Write the EDIFACT UNB header (component S001 = UNOA:4) with defaulted service chars + : '. */
    static EDIStreamWriter unb(EDIStreamWriter w) throws Exception {
        return w.writeStartSegment("UNB")
                .writeStartElement().writeComponent("UNOA").writeComponent("4").endElement()
                .writeElement("SENDER").writeElement("RECEIVER")
                .writeStartElement().writeComponent("240101").writeComponent("1200").endElement()
                .writeElement("1")
                .writeEndSegment();
    }

    static void defineCases() {
        // --- X12 ---
        // Full interchange round-trip: ISA / GS / ST / SE / GE / IEA.
        c("W_x12_full_interchange", () -> render(w -> {
            isa(w);
            w.writeStartSegment("GS").writeElement("FA").writeElement("ReceiverDept").writeElement("SenderDept")
             .writeElement("20050812").writeElement("195335").writeElement("000005").writeElement("X")
             .writeElement("005010X230").writeEndSegment();
            w.writeStartSegment("ST").writeElement("997").writeElement("0001").writeEndSegment();
            w.writeStartSegment("SE").writeElement("2").writeElement("0001").writeEndSegment();
            w.writeStartSegment("GE").writeElement("1").writeElement("000005").writeEndSegment();
            w.writeStartSegment("IEA").writeElement("1").writeElement("508121953").writeEndSegment();
        }));
        // Composite element built via writeStartElement / writeComponent / endElement -> "1:2:3".
        c("W_x12_composite", () -> render(w -> {
            isa(w);
            w.writeStartSegment("AK9").writeElement("A")
             .writeStartElement().writeComponent("1").writeComponent("2").writeComponent("3").endElement()
             .writeElement("X").writeEndSegment();
            w.writeStartSegment("IEA").writeElement("1").writeElement("508121953").writeEndSegment();
        }));
        // Empty simple element in the middle of a segment -> "TST*A**C~".
        c("W_x12_empty_element", () -> render(w -> {
            isa(w);
            w.writeStartSegment("TST").writeElement("A").writeEmptyElement().writeElement("C").writeEndSegment();
            w.writeStartSegment("IEA").writeElement("1").writeElement("508121953").writeEndSegment();
        }));
        // Empty component inside a composite -> "TST*1::3~".
        c("W_x12_empty_component", () -> render(w -> {
            isa(w);
            w.writeStartSegment("TST")
             .writeStartElement().writeComponent("1").writeEmptyComponent().writeComponent("3").endElement()
             .writeEndSegment();
            w.writeStartSegment("IEA").writeElement("1").writeElement("508121953").writeEndSegment();
        }));
        // Repeated element via writeRepeatElement -> "RPT*A^B^C~" (repetition sep '^').
        c("W_x12_repeat_element", () -> render(w -> {
            isa(w);
            w.writeStartSegment("RPT")
             .writeStartElement().writeElementData("A").writeRepeatElement().writeElementData("B")
             .writeRepeatElement().writeElementData("C").endElement()
             .writeEndSegment();
            w.writeStartSegment("IEA").writeElement("1").writeElement("508121953").writeEndSegment();
        }));
        // --- EDIFACT ---
        // Full interchange: UNB / UNH / UNT / UNZ.
        c("W_edifact_full_interchange", () -> render(w -> {
            unb(w);
            w.writeStartSegment("UNH").writeElement("1")
             .writeStartElement().writeComponent("ORDERS").writeComponent("D").writeComponent("96A").writeComponent("UN").endElement()
             .writeEndSegment();
            w.writeStartSegment("UNT").writeElement("2").writeElement("1").writeEndSegment();
            w.writeStartSegment("UNZ").writeElement("1").writeElement("1").writeEndSegment();
        }));
        // EDIFACT composite with a trailing simple element.
        c("W_edifact_composite", () -> render(w -> {
            unb(w);
            w.writeStartSegment("FTX").writeElement("AAA")
             .writeStartElement().writeComponent("1").writeComponent("2").endElement()
             .writeElement("free text").writeEndSegment();
            w.writeStartSegment("UNZ").writeElement("1").writeElement("1").writeEndSegment();
        }));
    }

    public static void main(String[] args) throws Exception { defineCases(); Runner.run(cases, args); }
}
