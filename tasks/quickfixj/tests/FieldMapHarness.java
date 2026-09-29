import io.fix.*;

import java.util.*;
import java.util.function.Supplier;

/**
 * WRG test harness -- FieldMap CRUD and typed accessors (self-asserting).
 */
public class FieldMapHarness {
    static final LinkedHashMap<String, Supplier<String>> cases = new LinkedHashMap<>();
    static void c(String name, Supplier<String> p) { cases.put(name, p); }

    static {
        // ---- FieldMap set/get roundtrips for all primitive typed accessors + boolean Y/N encoding. ----
        c("fieldmap_type_roundtrips_all_primitives", () -> {
            try {
                Message m = new Message();
                m.setString(58, "hello world");
                if (!"hello world".equals(m.getString(58)))              return "FAIL:string got=" + m.getString(58);
                m.setInt(34, 42); m.setInt(38, -7);
                if (m.getInt(34) != 42)                                   return "FAIL:int 34=" + m.getInt(34);
                if (m.getInt(38) != -7)                                   return "FAIL:int 38=" + m.getInt(38);
                m.setDouble(44, 150.50); m.setDouble(38, 100);
                if (m.getDouble(44) != 150.50)                            return "FAIL:double 44=" + m.getDouble(44);
                if (m.getDouble(38) != 100.0)                             return "FAIL:double 38=" + m.getDouble(38);
                m.setChar(54, '1'); m.setChar(40, '2');
                if (m.getChar(54) != '1' || m.getChar(40) != '2')         return "FAIL:char";
                // Boolean encoding: true -> "Y", false -> "N"; getBoolean parses Y/N.
                m.setBoolean(43, true);
                if (!"Y".equals(m.getString(43)))                         return "FAIL:true encoded as " + m.getString(43);
                m.setBoolean(43, false);
                if (!"N".equals(m.getString(43)))                         return "FAIL:false encoded as " + m.getString(43);
                m.setBoolean(43, true);
                if (!m.getBoolean(43))                                    return "FAIL:parsed true as false";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        c("remove_field", () -> {
            try {
                Message m = new Message();
                m.setString(55, "AAPL");
                m.removeField(55);
                if (m.isSetField(55)) return "FAIL:still set after remove";
                try { m.getString(55); return "FAIL:no_exception after remove"; }
                catch (FieldNotFound e) { /* expected */ }
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- getGroup(index, tag) returns the requested 1-indexed entry. ----
        c("fieldmap_getGroup_by_index_returns_populated_entry", () -> {
            try {
                char soh = (char) 0x01;
                io.fix.DataDictionary dd = new io.fix.DataDictionary("FIX44.xml");
                String rest = "35=W" + soh + "34=1" + soh
                        + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                        + "55=AAPL" + soh
                        + "268=2" + soh + "269=0" + soh + "270=150.10" + soh
                        + "269=1" + soh + "270=150.20" + soh;
                String body = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
                Message m = new Message(body + "10=" + String.format("%03d", cs) + soh, dd);
                Group g1 = m.getGroup(1, 268);
                Group g2 = m.getGroup(2, 268);
                if (!"0".equals(g1.getString(269)) || !"150.10".equals(g1.getString(270)))
                                                                                return "FAIL:g1 269=" + g1.getString(269) + " 270=" + g1.getString(270);
                if (!"1".equals(g2.getString(269)) || !"150.20".equals(g2.getString(270)))
                                                                                return "FAIL:g2 269=" + g2.getString(269) + " 270=" + g2.getString(270);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- removeGroup(index, tag) drops the entry and decrements the count field. ----
        c("fieldmap_removeGroup_decrements_count_and_shifts_entries", () -> {
            try {
                char soh = (char) 0x01;
                io.fix.DataDictionary dd = new io.fix.DataDictionary("FIX44.xml");
                String rest = "35=W" + soh + "34=1" + soh
                        + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                        + "55=AAPL" + soh
                        + "268=2" + soh + "269=0" + soh + "270=150.10" + soh
                        + "269=1" + soh + "270=150.20" + soh;
                String body = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
                Message m = new Message(body + "10=" + String.format("%03d", cs) + soh, dd);
                m.removeGroup(1, 268);
                if (m.getGroupCount(268) != 1)                                  return "FAIL:count=" + m.getGroupCount(268);
                Group survivor = m.getGroup(1, 268);
                if (!"1".equals(survivor.getString(269)))                       return "FAIL:survivor=" + survivor.getString(269);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- getInt on a decimal-string field throws (parse failure, not silent truncation). ----
        c("fieldmap_getInt_on_decimal_string_throws", () -> {
            try {
                Message m = new Message();
                m.setString(38, "100.5");
                try { m.getInt(38); return "FAIL:no_throw"; }
                catch (FieldException e) { return "OK"; }
                catch (Exception e)      { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- getBoolean on lowercase `y` throws — spec: boolean encoding is Y/N (case-sensitive). ----
        c("fieldmap_getBoolean_lowercase_y_throws", () -> {
            try {
                Message m = new Message();
                m.setString(150, "y");
                try { m.getBoolean(150); return "FAIL:no_throw"; }
                catch (FieldException e) { return "OK"; }
                catch (Exception e)      { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- getChar on a multi-character string throws — spec: CHAR is single character. ----
        c("fieldmap_getChar_multichar_throws", () -> {
            try {
                Message m = new Message();
                m.setString(40, "AB");
                try { m.getChar(40); return "FAIL:no_throw"; }
                catch (FieldException e) { return "OK"; }
                catch (Exception e)      { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- getGroup(0, tag) — index is 1-based; 0 is invalid and must throw. ----
        c("fieldmap_getGroup_index_zero_throws", () -> {
            try {
                char soh = (char) 0x01;
                io.fix.DataDictionary dd = new io.fix.DataDictionary("FIX44.xml");
                String rest = "35=W" + soh + "34=1" + soh
                        + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                        + "55=AAPL" + soh + "268=1" + soh + "269=0" + soh + "270=150.10" + soh;
                String body = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
                Message m = new Message(body + "10=" + String.format("%03d", cs) + soh, dd);
                try { m.getGroup(0, 268); return "FAIL:no_throw"; }
                catch (Exception e) { return "OK"; }
            } catch (Exception e) { return "FAIL:setup:" + e.getClass().getSimpleName(); }
        });

        // ---- hasGroup single-arg + two-arg overloads reflect group presence + index bound. ----
        c("fieldmap_hasGroup_int_and_int_int_overloads", () -> {
            try {
                char soh = (char) 0x01;
                io.fix.DataDictionary dd = new io.fix.DataDictionary("FIX44.xml");
                String rest = "35=W" + soh + "34=1" + soh
                        + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh
                        + "55=AAPL" + soh + "268=1" + soh + "269=0" + soh + "270=150.10" + soh;
                String body = "8=FIX.4.4" + soh + "9=" + rest.length() + soh + rest;
                int cs = 0; for (int i = 0; i < body.length(); i++) cs = (cs + body.charAt(i)) & 0xFF;
                Message m = new Message(body + "10=" + String.format("%03d", cs) + soh, dd);
                if (!m.hasGroup(268))                                            return "FAIL:hasGroup(268)_false";
                if (m.hasGroup(999))                                             return "FAIL:hasGroup(999)_true";
                if (!m.hasGroup(1, 268))                                         return "FAIL:hasGroup(1,268)_false";
                if (m.hasGroup(2, 268))                                          return "FAIL:hasGroup(2,268)_true_but_only_1_entry";
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- FieldMap.setFields(other) BULK-REPLACES the receiver's fields with `other`'s fields
        //      (not a merge — receiver's pre-existing fields are cleared). ----
        c("fieldmap_setFields_bulk_replaces_all_fields", () -> {
            try {
                Message src = new Message();
                src.setString(55, "AAPL"); src.setInt(38, 100);
                Message dst = new Message();
                dst.setString(11, "OLD_ORDER");
                dst.setFields(src);
                if (dst.isSetField(11))                                           return "FAIL:11_still_set";
                if (!"AAPL".equals(dst.getString(55)))                            return "FAIL:55=" + dst.getString(55);
                if (dst.getInt(38) != 100)                                        return "FAIL:38=" + dst.getInt(38);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- setGroups(other) REPLACES the receiver's groups with `other`'s groups
        //      (not a merge — receiver's pre-existing group entries are cleared). ----
        c("fieldmap_setGroups_bulk_replaces_all_groups", () -> {
            try {
                char soh = (char) 0x01;
                io.fix.DataDictionary dd = new io.fix.DataDictionary("FIX44.xml");
                // dst starts with 2 group entries.
                String restDst = "35=W" + soh + "34=1" + soh
                    + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh + "55=X" + soh
                    + "268=2" + soh + "269=0" + soh + "270=200.10" + soh + "269=1" + soh + "270=200.20" + soh;
                String bodyDst = "8=FIX.4.4" + soh + "9=" + restDst.length() + soh + restDst;
                int csA = 0; for (int i = 0; i < bodyDst.length(); i++) csA = (csA + bodyDst.charAt(i)) & 0xFF;
                Message dst = new Message(bodyDst + "10=" + String.format("%03d", csA) + soh, dd);
                // src has 1 group entry.
                String restSrc = "35=W" + soh + "34=1" + soh
                    + "49=A" + soh + "52=20240101-10:00:00.000" + soh + "56=B" + soh + "55=AAPL" + soh
                    + "268=1" + soh + "269=0" + soh + "270=150.10" + soh;
                String bodySrc = "8=FIX.4.4" + soh + "9=" + restSrc.length() + soh + restSrc;
                int csB = 0; for (int i = 0; i < bodySrc.length(); i++) csB = (csB + bodySrc.charAt(i)) & 0xFF;
                Message src = new Message(bodySrc + "10=" + String.format("%03d", csB) + soh, dd);
                dst.setGroups(src);
                if (dst.getGroupCount(268) != 1)                                  return "FAIL:count=" + dst.getGroupCount(268);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- Group extends FieldMap, so it inherits hasGroup/getGroupCount for NESTED groups
        //      (a Group holding sub-groups). ----
        c("group_hasGroup_and_count_on_parent_group_instance", () -> {
            try {
                Group outer = new Group(268, 269);
                outer.setString(269, "0");
                Group inner = new Group(555, 600);
                inner.setString(600, "A");
                outer.addGroup(inner);
                if (!outer.hasGroup(555))                                         return "FAIL:no_nested_group";
                if (outer.getGroupCount(555) != 1)                                return "FAIL:count=" + outer.getGroupCount(555);
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });

        // ---- get() on a field cleared via Message.clear() raises FieldNotFound
        //      (not returning stale data / defaults). ----
        c("fieldmap_get_after_clear_throws_FieldNotFound", () -> {
            try {
                Message m = new Message();
                m.setString(55, "AAPL");
                m.clear();
                try { m.getString(55); return "FAIL:no_throw"; }
                catch (FieldNotFound e) { return "OK"; }
                catch (Exception e)     { return "FAIL:wrong_class=" + e.getClass().getSimpleName(); }
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName(); }
        });

        // ---- Typed setField / getField template roundtrip: setField(new IntField(34, 42)),
        //      then getField(new IntField(34)) returns an IntField populated with 42.
        //      The template's tag identifies the slot to read; the returned Field is the same
        //      subclass with the stored value. ----
        c("typed_field_setField_getField_template_roundtrip", () -> {
            try {
                Message m = new Message();
                m.setField(new IntField(34, 42));
                IntField got = m.getField(new IntField(34));
                if (got.getValue() != 42)                        return "FAIL:value=" + got.getValue();
                if (got.getTag() != 34)                          return "FAIL:tag=" + got.getTag();
                if (!IntField.class.equals(got.getClass()))      return "FAIL:class=" + got.getClass();
                return "OK";
            } catch (Exception e) { return "FAIL:" + e.getClass().getSimpleName() + ":" + e.getMessage(); }
        });
    }

    public static void main(String[] args) throws Exception { Runner.run(cases, args); }
}
