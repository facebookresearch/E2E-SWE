import io.ediflow.schema.*;
import io.ediflow.stream.*;

import java.io.ByteArrayInputStream;
import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness PART 5 — CONTROL-STRUCTURE validation (interchange/group/transaction envelope:
 * control-number matching + segment/envelope counts). Drives the reader with a compact custom
 * CONTROL schema that declares header/trailer reference + count positions on ISA/IEA, GS/GE, ST/SE,
 * then feeds interchanges whose trailer control numbers or counts disagree with the actual stream,
 * asserting the exact ELEMENT_DATA_ERROR taxonomy (CONTROL_REFERENCE_MISMATCH /
 * CONTROL_COUNT_DOES_NOT_MATCH_ACTUAL_COUNT) + offending value. Self-contained: embeds its schema
 * (io.ediflow / http://ediflow.io namespace), imports only io.ediflow.{stream,schema}. No transaction
 * schema needed — control validation is driven by the control schema alone.
 */
public class HarnessControl {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static final String ISA =
        "ISA*00*          *00*          *ZZ*ReceiverID     *ZZ*Sender         *050812*1953*^*00501*508121953*0*P*:~";
    static final String GS = "GS*FA*ReceiverDept*SenderDept*20050812*195335*000005*X*005010X230~";
    static final String ST = "ST*997*0001~";
    static String se(String n, String ref) { return "SE*" + n + "*" + ref + "~"; }
    static String ge(String n, String ref) { return "GE*" + n + "*" + ref + "~"; }
    static String iea(String n, String ref) { return "IEA*" + n + "*" + ref + "~"; }
    /** A consistent single-group / single-transaction interchange (all refs + counts agree). */
    static String group(String seN, String seRef, String geN, String geRef) {
        return ISA + GS + ST + se(seN, seRef) + ge(geN, geRef);
    }

    // Control schema: interchange > group > transaction, each with control-number reference positions
    // and count positions (interchange/group count groups/transactions; transaction counts segments).
    static final String CONTROL = """
        <schema xmlns="http://ediflow.io/EDISchema/v4">
          <interchange header="ISA" trailer="IEA" headerRefPosition="13" trailerRefPosition="2" trailerCountPosition="1" countType="controls">
            <sequence>
              <group header="GS" trailer="GE" headerRefPosition="6" trailerRefPosition="2" trailerCountPosition="1" countType="controls">
                <transaction header="ST" trailer="SE" headerRefPosition="2" trailerRefPosition="2" trailerCountPosition="1" countType="segments"/>
              </group>
            </sequence>
          </interchange>
          <elementType name="I01" base="string"  minLength="2"  maxLength="2"/>
          <elementType name="I02" base="string"  minLength="10" maxLength="10"/>
          <elementType name="I03" base="string"  minLength="2"  maxLength="2"/>
          <elementType name="I04" base="string"  minLength="10" maxLength="10"/>
          <elementType name="I05" base="string"  minLength="2"  maxLength="2"/>
          <elementType name="I06" base="string"  minLength="15" maxLength="15"/>
          <elementType name="I07" base="string"  minLength="15" maxLength="15"/>
          <elementType name="I08" base="date"    minLength="6"  maxLength="6"/>
          <elementType name="I09" base="time"    minLength="4"  maxLength="4"/>
          <elementType name="I10" base="string"  minLength="1"  maxLength="1"/>
          <elementType name="I11" base="string"  minLength="5"  maxLength="5"/>
          <elementType name="I12" base="numeric" minLength="9"  maxLength="9"/>
          <elementType name="I13" base="string"  minLength="1"  maxLength="1"/>
          <elementType name="I14" base="string"  minLength="1"  maxLength="1"/>
          <elementType name="I15" base="string"  minLength="1"  maxLength="1"/>
          <elementType name="I16" base="numeric" minLength="1"  maxLength="5"/>
          <elementType name="E28"  base="numeric" maxLength="9"/>
          <elementType name="E96"  base="numeric" maxLength="10"/>
          <elementType name="E97"  base="numeric" maxLength="6"/>
          <elementType name="E124" base="string"  minLength="2" maxLength="15"/>
          <elementType name="E142" base="string"  minLength="2" maxLength="15"/>
          <elementType name="E143" base="string"  minLength="3" maxLength="3"/>
          <elementType name="E329" base="string"  minLength="4" maxLength="9"/>
          <elementType name="E337" base="time"    minLength="4" maxLength="8"/>
          <elementType name="E373" base="date"    minLength="6" maxLength="8"/>
          <elementType name="E455" base="string"  maxLength="2"/>
          <elementType name="E479" base="string"  minLength="2" maxLength="2"/>
          <elementType name="E480" base="string"  maxLength="12"/>
          <segmentType name="ISA"><sequence>
            <element type="I01" minOccurs="1"/><element type="I02" minOccurs="1"/><element type="I03" minOccurs="1"/>
            <element type="I04" minOccurs="1"/><element type="I05" minOccurs="1"/><element type="I06" minOccurs="1"/>
            <element type="I05" minOccurs="1"/><element type="I07" minOccurs="1"/><element type="I08" minOccurs="1"/>
            <element type="I09" minOccurs="1"/><element type="I10" minOccurs="1"/><element type="I11" minOccurs="1"/>
            <element type="I12" minOccurs="1"/><element type="I13" minOccurs="1"/><element type="I14" minOccurs="1"/>
            <element type="I15" minOccurs="1"/>
          </sequence></segmentType>
          <segmentType name="GS"><sequence>
            <element type="E479" minOccurs="1"/><element type="E142" minOccurs="1"/><element type="E124" minOccurs="1"/>
            <element type="E373" minOccurs="1"/><element type="E337" minOccurs="1"/><element type="E28" minOccurs="1"/>
            <element type="E455" minOccurs="1"/><element type="E480" minOccurs="1"/>
          </sequence></segmentType>
          <segmentType name="ST"><sequence><element type="E143" minOccurs="1"/><element type="E329" minOccurs="1"/></sequence></segmentType>
          <segmentType name="SE"><sequence><element type="E96" minOccurs="1"/><element type="E329" minOccurs="1"/></sequence></segmentType>
          <segmentType name="GE"><sequence><element type="E97" minOccurs="1"/><element type="E28" minOccurs="1"/></sequence></segmentType>
          <segmentType name="IEA"><sequence><element type="I16" minOccurs="1"/><element type="I12" minOccurs="1"/></sequence></segmentType>
        </schema>
        """;

    /** Validate an interchange against the control schema; collect ordered control (element-data) errors. */
    static String ctl(String edi) {
        try {
            EDIInputFactory f = EDIInputFactory.newFactory();
            Schema control = SchemaFactory.newFactory().createSchema(new ByteArrayInputStream(CONTROL.getBytes()));
            EDIStreamReader r = f.createEDIStreamReader(new ByteArrayInputStream(edi.getBytes()), control);
            StringBuilder sb = new StringBuilder();
            while (r.hasNext()) {
                EDIStreamEvent e = r.next();
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
        // consistent interchange: 1 group, 1 transaction, all refs + counts agree -> no control errors
        c("C_valid",             () -> ctl(group("2", "0001", "1", "000005") + iea("1", "508121953")));
        // IEA02 != ISA13 (interchange control-number mismatch), zero groups so IEA01=0 is correct
        c("C_ref_mismatch_iea",  () -> ctl(ISA + iea("0", "999999999")));
        // IEA01 = 2 but only 1 functional group present
        c("C_count_mismatch_iea",() -> ctl(group("2", "0001", "1", "000005") + iea("2", "508121953")));
        // SE01 = 9 but the transaction has 2 segments (ST..SE); countType=segments
        c("C_count_mismatch_se", () -> ctl(group("9", "0001", "1", "000005") + iea("1", "508121953")));
        // GE02 != GS06 (group control-number mismatch)
        c("C_ref_mismatch_ge",   () -> ctl(group("2", "0001", "1", "999999") + iea("1", "508121953")));
        // SE02 != ST02 (transaction control-number mismatch)
        c("C_ref_mismatch_se",   () -> ctl(group("2", "9999", "1", "000005") + iea("1", "508121953")));
    }

    public static void main(String[] args) throws Exception { defineCases(); Runner.run(cases, args); }
}
