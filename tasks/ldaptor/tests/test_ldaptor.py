"""Behavioral test suite for the ldaptor pure codec/parser core.

Covers three pillars exercised entirely through the public Python API:

  1. BER codec        (ldaptor.protocols.pureber)
  2. RFC2254 filters  (ldaptor.ldapfilter + ldaptor.protocols.pureldap filter classes)
  3. DN / RDN         (ldaptor.protocols.ldap.distinguishedname)

plus LDAP PDU encode/decode (pureldap) and LDIF read/write
(ldaptor.protocols.ldap.ldif / ldifprotocol).

Each test asserts one binary contract (exact bytes / type / exception / ordering).
"""

import base64

import pytest

from ldaptor.protocols import pureber
from ldaptor.protocols import pureldap
from ldaptor import ldapfilter
from ldaptor.protocols.ldap import distinguishedname as dn
from ldaptor.protocols.ldap import ldif as ldifwriter
from ldaptor.protocols.ldap import ldifprotocol


# --------------------------------------------------------------------------
# Decoder context helpers
# --------------------------------------------------------------------------

def _filter_ctx():
    """Context capable of decoding any filter PDU from the wire."""
    return pureldap.LDAPBERDecoderContext_Filter(
        fallback=pureldap.LDAPBERDecoderContext(
            fallback=pureber.BERDecoderContext()
        ),
        inherit=pureber.BERDecoderContext(),
    )


def _toplevel_ctx():
    """Context capable of decoding a full LDAPMessage envelope."""
    return pureldap.LDAPBERDecoderContext_TopLevel(
        inherit=pureldap.LDAPBERDecoderContext_LDAPMessage(
            fallback=pureldap.LDAPBERDecoderContext(
                fallback=pureber.BERDecoderContext()
            ),
            inherit=pureldap.LDAPBERDecoderContext(
                fallback=pureber.BERDecoderContext()
            ),
        )
    )


def _ldap_ctx():
    """Context capable of decoding a bare LDAP protocol op (no envelope)."""
    return pureldap.LDAPBERDecoderContext(
        fallback=pureber.BERDecoderContext(),
        inherit=pureber.BERDecoderContext(),
    )


def _wrap_decode(op, msg_id=1):
    """Round-trip a protocol op through an LDAPMessage envelope."""
    msg = pureldap.LDAPMessage(value=op, id=msg_id)
    wire = msg.toWire()
    decoded, used = pureber.berDecodeObject(_toplevel_ctx(), wire)
    return decoded, wire, used


# ==========================================================================
# Pillar 1: BER codec  (pureber)
# ==========================================================================

class TestBERIntegerEncoding:
    def test_int2ber_minimal(self):
        """int2ber emits the minimal-length signed two's-complement encoding.

        Covers a single-byte positive (127), a positive needing a leading zero
        octet to stay positive (128 -> 0x00 0x80), the minimal negative
        two's-complement byte (-128 -> 0x80), -1 -> 0xff, and a multi-byte
        positive (256 -> 0x01 0x00).
        """
        assert pureber.int2ber(127) == b"\x7f"
        assert pureber.int2ber(128) == b"\x00\x80"
        assert pureber.int2ber(-128) == b"\x80"
        assert pureber.int2ber(-1) == b"\xff"
        assert pureber.int2ber(256) == b"\x01\x00"

    def test_ber2int_decodes(self):
        """ber2int decodes signed and unsigned content, with sign extension.

        A single 0xff is -1 signed but 255 unsigned; a multi-byte high-bit value
        (0xff 0x80) sign-extends to a negative (-128).
        """
        assert pureber.ber2int(b"\xff") == -1
        assert pureber.ber2int(b"\xff", signed=0) == 255
        assert pureber.ber2int(b"\xff\x80") == -128

    def test_int_round_trip_negative(self):
        """int2ber then ber2int reproduces a negative value exactly."""
        assert pureber.ber2int(pureber.int2ber(-12345)) == -12345

    def test_ber2int_empty_raises_insufficient_data(self):
        """ber2int on an empty buffer raises insufficient-data needing 1 byte."""
        with pytest.raises(pureber.BERExceptionInsufficientData) as exc:
            pureber.ber2int(b"")
        assert exc.value.args == (1,)

    def test_int2ber_unsigned_omits_sign_zero(self):
        """255 signed needs a leading zero; unsigned encodes the bare byte."""
        assert pureber.int2ber(255) == b"\x00\xff"
        assert pureber.int2ber(255, signed=False) == b"\xff"


class TestBERLength:
    def test_int2berlen_encodes(self):
        """int2berlen emits short form then long form per RFC2251.

        127 stays single-byte short form; 200 needs long form with a
        one-octet length (0x81 0xc8); 256 needs a two-octet length
        (0x82 0x01 0x00).
        """
        assert pureber.int2berlen(127) == b"\x7f"
        assert pureber.int2berlen(200) == b"\x81\xc8"
        assert pureber.int2berlen(256) == b"\x82\x01\x00"

    def test_berDecodeLength_decodes(self):
        """berDecodeLength reads short and long definite forms with header size.

        Short form (0x05) -> (5, 1); long form one-octet (0x81 0xc8) ->
        (200, 2); long form two-octet (0x82 0x01 0x00) -> (256, 3).
        """
        assert pureber.berDecodeLength(b"\x05") == (5, 1)
        assert pureber.berDecodeLength(b"\x81\xc8") == (200, 2)
        assert pureber.berDecodeLength(b"\x82\x01\x00") == (256, 3)

    def test_berDecodeLength_truncated_raises(self):
        """A long-form length header missing its octets raises insufficient-data."""
        with pytest.raises(pureber.BERExceptionInsufficientData):
            pureber.berDecodeLength(b"\x82\x01")

    def test_length_long_form_three_octets_round_trip(self):
        """A length needing 3 octets encodes long-form and decodes back to the value."""
        encoded = pureber.int2berlen(0x010000)
        assert pureber.berDecodeLength(encoded) == (0x010000, len(encoded))


class TestBERNeed:
    def test_need_reports_deficit(self):
        """need(buf, n) raises with the exact number of missing bytes."""
        with pytest.raises(pureber.BERExceptionInsufficientData) as exc:
            pureber.need(b"abc", 5)
        assert exc.value.args == (2,)

    def test_need_satisfied_returns_none(self):
        """need does nothing when the buffer is long enough."""
        assert pureber.need(b"abcde", 3) is None


class TestBERObjects:
    def test_object_wire_literals(self):
        """Universal BER objects emit identification-byte + length + contents.

        BERInteger(42) -> 0x02 len value; BEROctetString -> 0x04 len raw bytes;
        BERSequence wraps concatenated child encodings under tag 0x30; an
        explicit tag= overrides the class default in the identification byte.
        """
        assert pureber.BERInteger(42).toWire() == b"\x02\x01\x2a"
        assert pureber.BEROctetString(b"hi").toWire() == b"\x04\x02hi"
        seq = pureber.BERSequence(
            [pureber.BERInteger(1), pureber.BEROctetString(b"x")]
        )
        assert seq.toWire() == b"\x30\x06\x02\x01\x01\x04\x01x"
        assert pureber.BERInteger(7, tag=0x42).toWire() == b"\x42\x01\x07"

    def test_boolean_truthy_normalizes_to_ff(self):
        """Any truthy value is stored/encoded as 0xff in a BERBoolean."""
        b = pureber.BERBoolean(5)
        assert b.value == 0xFF
        assert b.toWire() == b"\x01\x01\xff"

    def test_boolean_false_is_zero(self):
        """A falsey BERBoolean encodes contents 0x00."""
        assert pureber.BERBoolean(0).toWire() == b"\x01\x01\x00"

    def test_equality_by_wire(self):
        """Two BER objects are equal iff their wire encodings match."""
        assert pureber.BERInteger(5) == pureber.BERInteger(5)
        assert pureber.BERInteger(5) != pureber.BERInteger(6)


class TestBERDecode:
    def test_decode_object_returns_obj_and_length(self):
        """berDecodeObject returns the reconstructed object and total bytes consumed."""
        ctx = pureber.BERDecoderContext()
        obj, used = pureber.berDecodeObject(ctx, pureber.BERInteger(42).toWire())
        assert obj == pureber.BERInteger(42)
        assert used == 3

    def test_decode_sequence_round_trip(self):
        """A BERSequence survives a toWire/berDecodeObject round trip intact."""
        ctx = pureber.BERDecoderContext()
        seq = pureber.BERSequence(
            [pureber.BERInteger(1), pureber.BEROctetString(b"x")]
        )
        obj, used = pureber.berDecodeObject(ctx, seq.toWire())
        assert obj == seq
        assert used == len(seq.toWire())

    def test_decode_unknown_tag_swallowed(self):
        """An unknown tag is swallowed: result is (None, bytesUsed), no exception."""
        ctx = pureber.BERDecoderContext()
        blob = bytes((0x16,)) + pureber.int2berlen(2) + b"ab"  # IA5String, unmapped
        assert pureber.berDecodeObject(ctx, blob) == (None, 4)

    def test_decode_truncated_content_raises(self):
        """A declared length longer than the available content raises insufficient-data."""
        ctx = pureber.BERDecoderContext()
        blob = bytes((0x02,)) + pureber.int2berlen(4) + b"\x01\x02"
        with pytest.raises(pureber.BERExceptionInsufficientData):
            pureber.berDecodeObject(ctx, blob)

    def test_decode_multiple_returns_all(self):
        """berDecodeMultiple decodes every complete object in the buffer."""
        ctx = pureber.BERDecoderContext()
        blob = pureber.BERInteger(1).toWire() + pureber.BERInteger(2).toWire()
        result = pureber.berDecodeMultiple(blob, ctx)
        assert [x.value for x in result] == [1, 2]

    def test_decode_multiple_skips_unknown_tag_midstream(self):
        """berDecodeMultiple drops a None (unknown-tag) object sitting between two known ones."""
        ctx = pureber.BERDecoderContext()
        unknown = bytes((0x16,)) + pureber.int2berlen(2) + b"ab"  # IA5String, unmapped
        blob = (
            pureber.BERInteger(1).toWire()
            + unknown
            + pureber.BERInteger(2).toWire()
        )
        result = pureber.berDecodeMultiple(blob, ctx)
        assert [x.value for x in result] == [1, 2]

    def test_decode_object_empty_buffer_returns_none(self):
        """berDecodeObject on an empty buffer returns (None, 0) rather than raising."""
        ctx = pureber.BERDecoderContext()
        assert pureber.berDecodeObject(ctx, b"") == (None, 0)

    def test_composite_sequence_round_trip(self):
        """A nested sequence mixing every universal type survives a wire round trip.

        Exercises Null, Enumerated, Boolean normalization, and a nested Set inside a
        Sequence in one shot (replacing the per-type single-byte literal tests).
        """
        ctx = pureber.BERDecoderContext()
        seq = pureber.BERSequence(
            [
                pureber.BERInteger(7),
                pureber.BEROctetString(b"hi"),
                pureber.BERNull(),
                pureber.BEREnumerated(2),
                pureber.BERBoolean(1),
                pureber.BERSet([pureber.BERInteger(1), pureber.BERInteger(2)]),
            ]
        )
        wire = seq.toWire()
        obj, used = pureber.berDecodeObject(ctx, wire)
        assert obj == seq
        assert obj.toWire() == wire
        assert used == len(wire)
        child_types = [type(x).__name__ for x in obj]
        assert child_types == [
            "BERInteger",
            "BEROctetString",
            "BERNull",
            "BEREnumerated",
            "BERBoolean",
            "BERSet",
        ]
        assert obj[4].value == 0xFF
        assert [x.value for x in obj[5]] == [1, 2]


# ==========================================================================
# Pillar 2: RFC2254 filters
# ==========================================================================

class TestFilterParseTypes:
    def test_equality(self):
        """(cn=foo) parses to an equalityMatch that round-trips to the same text."""
        f = ldapfilter.parseFilter("(cn=foo)")
        assert isinstance(f, pureldap.LDAPFilter_equalityMatch)
        assert f.asText() == "(cn=foo)"

    def test_greater_or_equal(self):
        """>= parses to greaterOrEqual with the >= operator in asText."""
        f = ldapfilter.parseFilter("(cn>=5)")
        assert isinstance(f, pureldap.LDAPFilter_greaterOrEqual)
        assert f.asText() == "(cn>=5)"

    def test_less_or_equal(self):
        """<= parses to lessOrEqual with the <= operator in asText."""
        f = ldapfilter.parseFilter("(cn<=5)")
        assert isinstance(f, pureldap.LDAPFilter_lessOrEqual)
        assert f.asText() == "(cn<=5)"

    def test_approx_match(self):
        """~= parses to approxMatch with the ~= operator in asText."""
        f = ldapfilter.parseFilter("(cn~=x)")
        assert isinstance(f, pureldap.LDAPFilter_approxMatch)
        assert f.asText() == "(cn~=x)"

    def test_present(self):
        """(cn=*) parses to a present filter."""
        f = ldapfilter.parseFilter("(cn=*)")
        assert isinstance(f, pureldap.LDAPFilter_present)
        assert f.asText() == "(cn=*)"

    def test_bytes_input_accepted(self):
        """parseFilter decodes a bytes argument as utf-8."""
        f = ldapfilter.parseFilter(b"(cn=foo)")
        assert isinstance(f, pureldap.LDAPFilter_equalityMatch)
        assert f.asText() == "(cn=foo)"


class TestFilterBoolean:
    def test_and_children_order(self):
        """(&(a=1)(b=2)) parses to an AND whose children preserve text order."""
        f = ldapfilter.parseFilter("(&(a=1)(b=2))")
        assert isinstance(f, pureldap.LDAPFilter_and)
        assert f.asText() == "(&(a=1)(b=2))"

    def test_or(self):
        """(|...) parses to an OR filter."""
        f = ldapfilter.parseFilter("(|(a=1)(b=2))")
        assert isinstance(f, pureldap.LDAPFilter_or)
        assert f.asText() == "(|(a=1)(b=2))"

    def test_not(self):
        """(!...) parses to a NOT wrapping its single child."""
        f = ldapfilter.parseFilter("(!(a=1))")
        assert isinstance(f, pureldap.LDAPFilter_not)
        assert f.asText() == "(!(a=1))"

    def test_filterset_equality_is_order_insensitive(self):
        """AND/OR sets compare equal regardless of child ordering."""
        a = ldapfilter.parseFilter("(&(a=1)(b=2))")
        b = ldapfilter.parseFilter("(&(b=2)(a=1))")
        assert a == b

    def test_filterset_inequality_on_different_children(self):
        """Filter sets with different members are not equal."""
        a = ldapfilter.parseFilter("(&(a=1)(b=2))")
        c = ldapfilter.parseFilter("(&(a=1)(c=3))")
        assert a != c


class TestFilterSubstrings:
    def test_full_decomposition(self):
        """(cn=a*b*c) decomposes into initial / any / final in order, and asText re-joins on '*'."""
        f = ldapfilter.parseFilter("(cn=a*b*c)")
        assert isinstance(f, pureldap.LDAPFilter_substrings)
        types = [type(s).__name__ for s in f.substrings]
        values = [s.value for s in f.substrings]
        assert types == [
            "LDAPFilter_substrings_initial",
            "LDAPFilter_substrings_any",
            "LDAPFilter_substrings_final",
        ]
        assert values == ["a", "b", "c"]
        assert f.asText() == "(cn=a*b*c)"

    def test_leading_star_has_no_initial(self):
        """A leading '*' means no initial segment; asText keeps the leading star."""
        f = ldapfilter.parseFilter("(cn=*ab)")
        assert not any(
            isinstance(s, pureldap.LDAPFilter_substrings_initial)
            for s in f.substrings
        )
        assert f.asText() == "(cn=*ab)"

    def test_trailing_star_has_no_final(self):
        """A trailing '*' means no final segment; asText keeps the trailing star."""
        f = ldapfilter.parseFilter("(cn=ab*)")
        assert not any(
            isinstance(s, pureldap.LDAPFilter_substrings_final)
            for s in f.substrings
        )
        assert f.asText() == "(cn=ab*)"

    def test_only_any(self):
        """(cn=*x*) yields a single 'any' segment and no initial/final."""
        f = ldapfilter.parseFilter("(cn=*x*)")
        types = [type(s).__name__ for s in f.substrings]
        assert types == ["LDAPFilter_substrings_any"]
        assert f.asText() == "(cn=*x*)"

    def test_multiple_any_segments_keep_order(self):
        """(cn=a*b*c*d) yields initial, two ordered 'any' segments, then final."""
        f = ldapfilter.parseFilter("(cn=a*b*c*d)")
        assert isinstance(f, pureldap.LDAPFilter_substrings)
        types = [type(s).__name__ for s in f.substrings]
        values = [s.value for s in f.substrings]
        assert types == [
            "LDAPFilter_substrings_initial",
            "LDAPFilter_substrings_any",
            "LDAPFilter_substrings_any",
            "LDAPFilter_substrings_final",
        ]
        assert values == ["a", "b", "c", "d"]
        assert f.asText() == "(cn=a*b*c*d)"


class TestFilterExtensible:
    def test_attr_with_matchingrule(self):
        """(cn:caseExactMatch:=x) gives an extensibleMatch with type+rule, no :dn."""
        f = ldapfilter.parseFilter("(cn:caseExactMatch:=x)")
        assert isinstance(f, pureldap.LDAPFilter_extensibleMatch)
        assert f.type.value == "cn"
        assert f.matchingRule.value == "caseExactMatch"
        assert f.matchValue.value == "x"
        assert f.asText() == "(cn:caseExactMatch:=x)"

    def test_attr_less_with_dn_and_oid(self):
        """(:dn:2.4.6.8:=x) has no type, a numeric-OID rule, and dnAttributes set."""
        f = ldapfilter.parseFilter("(:dn:2.4.6.8:=x)")
        assert isinstance(f, pureldap.LDAPFilter_extensibleMatch)
        assert f.type is None
        assert f.matchingRule.value == "2.4.6.8"
        assert f.dnAttributes.value == 0xFF
        assert f.asText() == "(:dn:2.4.6.8:=x)"

    def test_dn_without_matchingrule(self):
        """(cn:dn:=x) sets type and dnAttributes but no matching rule."""
        f = ldapfilter.parseFilter("(cn:dn:=x)")
        assert f.type.value == "cn"
        assert f.matchingRule is None
        assert f.dnAttributes.value == 0xFF
        assert f.asText() == "(cn:dn:=x)"

    def test_full_extensible_form(self):
        """(cn:dn:caseExactMatch:=x) round-trips with all components."""
        f = ldapfilter.parseFilter("(cn:dn:caseExactMatch:=x)")
        assert f.asText() == "(cn:dn:caseExactMatch:=x)"

    def test_bare_named_matching_rule_no_attr(self):
        """(:caseExactMatch:=x) is a bare named rule: no type, no :dn, round-trips."""
        f = ldapfilter.parseFilter("(:caseExactMatch:=x)")
        assert isinstance(f, pureldap.LDAPFilter_extensibleMatch)
        assert f.type is None
        assert f.matchingRule.value == "caseExactMatch"
        assert f.matchValue.value == "x"
        assert f.asText() == "(:caseExactMatch:=x)"


class TestFilterEscapingAndErrors:
    def test_escaped_value_decodes_literal_star(self):
        """An escaped \\2a in a value decodes to a literal '*' in the assertion value."""
        f = ldapfilter.parseFilter("(cn=foo\\2abar)")
        assert f.assertionValue.value == "foo*bar"

    def test_invalid_unbalanced_parens(self):
        """An unterminated filter raises InvalidLDAPFilter."""
        with pytest.raises(ldapfilter.InvalidLDAPFilter):
            ldapfilter.parseFilter("(cn=foo")

    def test_invalid_empty_string(self):
        """An empty string is not a valid filter."""
        with pytest.raises(ldapfilter.InvalidLDAPFilter):
            ldapfilter.parseFilter("")

    def test_invalid_empty_parens(self):
        """'()' is not a valid filter."""
        with pytest.raises(ldapfilter.InvalidLDAPFilter):
            ldapfilter.parseFilter("()")

    def test_escape_special_chars(self):
        """pureldap.escape backslash-hex-escapes *, (, ), \\ and NUL."""
        assert pureldap.escape("a*b(c)\\d\x00") == "a\\2ab\\28c\\29\\5cd\\00"

    def test_binary_escape_all_bytes(self):
        """binary_escape emits a \\xx hex pair for every character."""
        assert pureldap.binary_escape("AB") == "\\41\\42"

    def test_smart_escape_below_threshold_uses_escape(self):
        """smart_escape uses light escaping when binary density is low."""
        assert pureldap.smart_escape("hello*") == "hello\\2a"

    def test_smart_escape_above_threshold_uses_binary(self):
        """smart_escape switches to full binary escaping above the threshold."""
        assert pureldap.smart_escape("\x01\x02\x03ab") == "\\01\\02\\03\\61\\62"

    def test_smart_escape_at_threshold_uses_light_escape(self):
        """At exactly the threshold (strict >) smart_escape uses light escaping.

        3 binary chars out of 10 == 0.30 == the default threshold, so it does NOT
        switch to binary_escape. Light escape leaves control chars untouched (it only
        escapes the filter special set), so the leading control bytes pass through.
        """
        s = "\x01\x02\x03abcdefg"  # 3/10 == 0.30
        assert pureldap.smart_escape(s) == "\x01\x02\x03abcdefg"


class TestParseMaybeSubstring:
    def test_dispatch_by_value_shape(self):
        """parseMaybeSubstring dispatches to a filter type by the value's shape.

        A value containing '*' becomes a substrings filter; a bare '*' becomes a
        present filter; and a plain value becomes an equalityMatch filter.
        """
        # '*' inside the value -> substrings
        sub = ldapfilter.parseMaybeSubstring("cn", "a*b")
        assert isinstance(sub, pureldap.LDAPFilter_substrings)
        assert sub.asText() == "(cn=a*b)"
        # bare '*' -> present
        pres = ldapfilter.parseMaybeSubstring("cn", "*")
        assert isinstance(pres, pureldap.LDAPFilter_present)
        # plain value -> equalityMatch
        eq = ldapfilter.parseMaybeSubstring("cn", "x")
        assert isinstance(eq, pureldap.LDAPFilter_equalityMatch)
        assert eq.asText() == "(cn=x)"


class TestFilterWireRoundTrip:
    def test_nested_boolean_round_trip(self):
        """A nested &/|/! filter survives text->object->wire->object intact."""
        orig = ldapfilter.parseFilter("(&(cn=foo)(!(sn=bar))(|(a=1)(b=2)))")
        wire = orig.toWire()
        decoded, used = pureber.berDecodeObject(_filter_ctx(), wire)
        assert isinstance(decoded, pureldap.LDAPFilter_and)
        assert decoded.toWire() == wire
        assert decoded == orig
        assert used == len(wire)

    def test_substring_wire_round_trip(self):
        """A substrings filter survives a wire round trip preserving its 3 segments."""
        orig = ldapfilter.parseFilter("(cn=a*b*c)")
        wire = orig.toWire()
        decoded, _ = pureber.berDecodeObject(_filter_ctx(), wire)
        assert isinstance(decoded, pureldap.LDAPFilter_substrings)
        assert len(decoded.substrings) == 3
        assert decoded.toWire() == wire

    def test_extensible_wire_round_trip(self):
        """An extensibleMatch filter survives a wire round trip."""
        orig = ldapfilter.parseFilter("(cn:dn:caseExactMatch:=x)")
        wire = orig.toWire()
        decoded, _ = pureber.berDecodeObject(_filter_ctx(), wire)
        assert isinstance(decoded, pureldap.LDAPFilter_extensibleMatch)
        assert decoded.toWire() == wire

    def test_and_with_substrings_child_round_trip(self):
        """An AND containing a substrings child survives text->wire->object intact."""
        orig = ldapfilter.parseFilter("(&(cn=a*b*c)(sn=x))")
        wire = orig.toWire()
        decoded, used = pureber.berDecodeObject(_filter_ctx(), wire)
        assert isinstance(decoded, pureldap.LDAPFilter_and)
        assert decoded.toWire() == wire
        assert decoded == orig
        assert used == len(wire)
        child_types = [type(c).__name__ for c in decoded]
        assert "LDAPFilter_substrings" in child_types

    def test_extensible_dn_with_rule_round_trip(self):
        """A (:dn:<rule>:=v) extensible match (no attr type) survives a wire round trip."""
        orig = ldapfilter.parseFilter("(:dn:caseExactMatch:=x)")
        assert orig.type is None
        assert orig.matchingRule.value == "caseExactMatch"
        assert orig.dnAttributes.value == 0xFF
        wire = orig.toWire()
        decoded, _ = pureber.berDecodeObject(_filter_ctx(), wire)
        assert isinstance(decoded, pureldap.LDAPFilter_extensibleMatch)
        assert decoded.toWire() == wire


# ==========================================================================
# Pillar 3: DN / RDN
# ==========================================================================

class TestDNBasics:
    def test_parses_into_rdns(self):
        """A 3-component DN string splits into 3 RDNs and round-trips via getText."""
        d = dn.DistinguishedName("cn=foo,dc=example,dc=com")
        assert len(d.split()) == 3
        assert d.getText() == "cn=foo,dc=example,dc=com"

    def test_up_drops_most_specific_rdn(self):
        """up() removes the leftmost (most specific) RDN."""
        d = dn.DistinguishedName("cn=foo,dc=example,dc=com")
        assert d.up().getText() == "dc=example,dc=com"

    def test_up_of_single_rdn_is_empty(self):
        """up() on a single-RDN DN yields an empty DN."""
        assert dn.DistinguishedName("dc=com").up().getText() == ""

    def test_equality_with_str(self):
        """A DN compares equal to its own text representation."""
        d = dn.DistinguishedName("cn=foo,dc=example,dc=com")
        assert d == "cn=foo,dc=example,dc=com"

    def test_equality_with_bytes(self):
        """A DN compares equal to the utf-8 bytes of its text."""
        d = dn.DistinguishedName("cn=foo,dc=example,dc=com")
        assert d == b"cn=foo,dc=example,dc=com"


class TestDNEscaping:
    def test_escape_table(self):
        """RFC2253 escape() covers positional, special-set, and control rules.

        A leading space, a trailing space, and a leading '#' are each
        backslash-escaped; the special set ,+"\\<>;= is each escaped; and a
        control character below 0x20 becomes \\XX uppercase hex.
        """
        assert dn.escape(" foo") == "\\ foo"
        assert dn.escape("foo ") == "foo\\ "
        assert dn.escape("#foo") == "\\#foo"
        assert dn.escape('a,b+c"d\\e<f>g;h=i') == 'a\\,b\\+c\\"d\\\\e\\<f\\>g\\;h\\=i'
        assert dn.escape("a" + chr(31) + "b") == "a\\1Fb"

    def test_unescape_hex(self):
        """unescape converts \\01 back to the control character."""
        assert dn.unescape("a\\01b") == "a\x01b"

    def test_unescape_literal_char(self):
        """unescape of \\, yields a literal comma."""
        assert dn.unescape("a\\,b") == "a,b"

    def test_escape_combined_corners(self):
        """A leading '#', an embedded '+', and a trailing space are all escaped."""
        assert dn.escape("#a+b ") == "\\#a\\+b\\ "

    def test_unescape_mixed_hex_and_literal(self):
        """unescape handles a \\XX hex escape and a \\, literal escape in one string."""
        assert dn.unescape("a\\2cb\\,c") == "a,b,c"


class TestDNSplitBehavior:
    """DN/RDN string splitting, observed through the public DistinguishedName /
    RelativeDistinguishedName surface (not the private split helper)."""

    def test_respects_backslash_escape(self):
        """An escaped comma does not split a DN into a new RDN, and round-trips."""
        d = dn.DistinguishedName("cn=a\\,b,dc=x")
        assert len(d.split()) == 2
        assert d.getText() == "cn=a\\,b,dc=x"

    def test_trims_spaces_after_separator(self):
        """Spaces following an RDN separator are trimmed (no leading-space RDNs)."""
        d = dn.DistinguishedName("cn=a, dc=b, dc=c")
        assert len(d.split()) == 3
        assert d.getText() == "cn=a,dc=b,dc=c"

    def test_escaped_backslash_before_separator_splits(self):
        r"""An escaped backslash (\\) before a separator leaves the separator active."""
        # The value before '+' is  a\\ : the backslash is itself escaped, so the '+'
        # that follows is an UNescaped separator and the RDN splits in two.
        rdn = dn.RelativeDistinguishedName("cn=a\\\\+sn=b")
        assert rdn.count() == 2
        assert rdn.getText() == "cn=a\\\\+sn=b"


class TestRDNAndATV:
    def test_multivalued_rdn(self):
        """A multi-valued RDN cn=a+sn=b splits on the unescaped '+'."""
        rdn = dn.RelativeDistinguishedName("cn=a+sn=b")
        assert rdn.count() == 2
        assert rdn.getText() == "cn=a+sn=b"

    def test_atv_equality_case_insensitive(self):
        """ATV equality is case-insensitive on both type and value."""
        assert dn.LDAPAttributeTypeAndValue("CN=Foo") == dn.LDAPAttributeTypeAndValue(
            "cn=foo"
        )

    def test_rdn_equality(self):
        """Two RDNs with identical components compare equal."""
        assert dn.RelativeDistinguishedName("cn=a+sn=b") == dn.RelativeDistinguishedName(
            "cn=a+sn=b"
        )

    def test_atv_without_equals_raises(self):
        """An ATV string lacking '=' raises InvalidRelativeDistinguishedName."""
        with pytest.raises(dn.InvalidRelativeDistinguishedName):
            dn.LDAPAttributeTypeAndValue("nope")


class TestDNContainsAndDomain:
    def test_contains_semantics(self):
        """DistinguishedName.contains covers the full ancestry relation.

        A parent DN contains a descendant; contains coerces a str argument into a
        DN; a child does NOT contain its parent (asymmetry); and the match is
        case-insensitive on both attribute and value.
        """
        parent = dn.DistinguishedName("dc=example,dc=com")
        child = dn.DistinguishedName("cn=foo,dc=example,dc=com")
        # parent contains descendant
        assert parent.contains(child)
        # str argument is coerced to a DN
        assert parent.contains("cn=foo,dc=example,dc=com")
        # asymmetric: a child does not contain its parent
        assert not child.contains(parent)
        # case-insensitive on attribute and value
        ci_parent = dn.DistinguishedName("DC=Example,DC=Com")
        assert ci_parent.contains(child)

    def test_get_domain_name_variants(self):
        """getDomainName returns the joined trailing run of single-valued dc RDNs.

        Covers: a trailing dc run joined with '.'; no trailing dc run -> None; a
        multi-valued dc RDN breaking the run so only the suffix survives; a single
        dc RDN returning that value; a leading non-dc RDN not breaking the trailing
        dc run; and an interior non-dc RDN keeping only the trailing run.
        """
        # trailing dc run is joined with '.'
        assert dn.DistinguishedName("cn=foo,dc=example,dc=com").getDomainName() == "example.com"
        # no trailing dc run -> None
        assert dn.DistinguishedName("cn=foo").getDomainName() is None
        # a multi-valued dc RDN breaks the run; only the suffix survives
        assert dn.DistinguishedName("dc=a+dc=b,dc=com").getDomainName() == "com"
        # a single dc RDN returns that value
        assert dn.DistinguishedName("dc=com").getDomainName() == "com"
        # a leading non-dc RDN does not break the trailing dc run
        assert dn.DistinguishedName("cn=x,dc=a,dc=b").getDomainName() == "a.b"
        # an interior non-dc RDN keeps only the trailing run, not all dcs
        assert dn.DistinguishedName("dc=a,cn=x,dc=b").getDomainName() == "b"


# ==========================================================================
# LDAP PDU encode / decode  (pureldap)
# ==========================================================================

class TestPDURoundTrip:
    def test_search_request(self):
        """A search request round-trips through an LDAPMessage envelope."""
        op = pureldap.LDAPSearchRequest(
            baseObject="dc=example,dc=com",
            filter=pureldap.LDAPFilter_present("objectClass"),
            attributes=["cn", "sn"],
        )
        decoded, wire, _ = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPSearchRequest)
        assert decoded.value.baseObject == b"dc=example,dc=com"
        assert decoded.value.attributes == [b"cn", b"sn"]
        assert decoded.toWire() == wire

    def test_bind_request(self):
        """A simple bind request round-trips preserving dn and auth."""
        op = pureldap.LDAPBindRequest(version=3, dn="cn=admin", auth="secret")
        decoded, wire, _ = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPBindRequest)
        assert decoded.value.dn == b"cn=admin"
        assert decoded.value.auth == b"secret"
        assert decoded.toWire() == wire

    def test_message_dispatches_by_tag_and_preserves_id(self):
        """LDAPMessage decode dispatches to LDAPDelRequest and keeps the id."""
        op = pureldap.LDAPDelRequest("cn=foo")
        decoded, wire, _ = _wrap_decode(op, msg_id=42)
        assert isinstance(decoded.value, pureldap.LDAPDelRequest)
        assert decoded.id == 42
        assert decoded.toWire() == wire

    def test_modify_request(self):
        """A modify request round-trips through the envelope."""
        op = pureldap.LDAPModifyRequest(object="cn=foo", modification=[])
        decoded, wire, _ = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPModifyRequest)
        assert decoded.toWire() == wire

    def test_compare_request(self):
        """A compare request round-trips through the envelope."""
        op = pureldap.LDAPCompareRequest(
            entry="cn=foo",
            ava=pureldap.LDAPAttributeValueAssertion(
                attributeDesc=pureldap.LDAPAttributeDescription("cn"),
                assertionValue=pureldap.LDAPAssertionValue("x"),
            ),
        )
        decoded, wire, _ = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPCompareRequest)
        assert decoded.toWire() == wire

    def test_unbind_request_dispatch(self):
        """An UnbindRequest (empty primitive) dispatches through an LDAPMessage by tag."""
        op = pureldap.LDAPUnbindRequest()
        assert op.toWire() == b"B\x00"  # 0x42 = APPLICATION | 2, zero-length
        decoded, wire, _ = _wrap_decode(op, msg_id=5)
        assert isinstance(decoded.value, pureldap.LDAPUnbindRequest)
        assert decoded.id == 5
        assert decoded.toWire() == wire

    def test_message_with_controls(self):
        """Controls attached to a message round-trip back into the controls list."""
        op = pureldap.LDAPDelRequest("cn=foo")
        msg = pureldap.LDAPMessage(value=op, id=3, controls=[("1.2.3", None, None)])
        wire = msg.toWire()
        decoded, _ = pureber.berDecodeObject(_toplevel_ctx(), wire)
        assert decoded.controls == [(b"1.2.3", None, None)]
        assert decoded.toWire() == wire


class TestPDUWireDetails:
    def test_del_request_is_app_class_octetstring(self):
        """LDAPDelRequest encodes as an application-class primitive (tag 0x4a)."""
        assert pureldap.LDAPDelRequest("cn=foo").toWire() == b"\x4a\x06cn=foo"

    def test_bind_omits_empty_dn_and_uses_context_auth_tag(self):
        """A default bind omits empty dn bytes and uses context tag 0x80 for simple auth."""
        assert (
            pureldap.LDAPBindRequest().toWire()
            == b"\x60\x07\x02\x01\x03\x04\x00\x80\x00"
        )

    def test_control_decode_round_trip(self):
        """LDAPControl decode disambiguates the optional crit/value fields by BER type.

        Covers the 3-element (crit+value) path and the two 2-element paths
        (Boolean->criticality vs OctetString->controlValue).
        """
        cases = [
            # full: criticality (->0xFF) and value both present
            ({"criticality": True, "controlValue": b"x"}, 0xFF, b"x"),
            # 2-element, Boolean-only -> criticality, no value
            ({"criticality": True}, 0xFF, None),
            # 2-element, OctetString-only -> value, no criticality
            ({"controlValue": b"x"}, None, b"x"),
        ]
        ctx = pureldap.LDAPBERDecoderContext_LDAPControls(
            fallback=pureber.BERDecoderContext()
        )
        for kwargs, exp_crit, exp_val in cases:
            ctrl = pureldap.LDAPControl(controlType="1.2.3", **kwargs)
            wire = ctrl.toWire()
            decoded, _ = pureber.berDecodeObject(ctx, wire)
            assert decoded.controlType == b"1.2.3"
            assert decoded.criticality == exp_crit
            assert decoded.controlValue == exp_val


# ==========================================================================
# Response / result PDUs (server -> client decode)
# ==========================================================================

class TestResponseResultPDURoundTrip:
    def test_ldapresult_family_round_trip(self):
        """Every plain LDAPResult-shaped response PDU decodes from the wire.

        LDAPSearchResultDone, LDAPModifyResponse, LDAPAddResponse, LDAPDelResponse,
        LDAPModifyDNResponse, and LDAPCompareResponse all carry the same
        resultCode/matchedDN/errorMessage triple. Each is built, wrapped in an
        LDAPMessage envelope, decoded back through the top-level context (the exact
        path a client uses to read a server response), and must reconstruct an
        LDAPResult whose three fields are preserved (matchedDN/errorMessage come back
        as bytes) and whose re-encoding equals the original wire.
        """
        classes = [
            pureldap.LDAPSearchResultDone,
            pureldap.LDAPModifyResponse,
            pureldap.LDAPAddResponse,
            pureldap.LDAPDelResponse,
            pureldap.LDAPModifyDNResponse,
            pureldap.LDAPCompareResponse,
        ]
        for cls in classes:
            op = cls(resultCode=0, matchedDN="cn=foo", errorMessage="ok")
            decoded, wire, used = _wrap_decode(op)
            value = decoded.value
            assert isinstance(value, pureldap.LDAPResult)
            assert value.resultCode == 0
            assert value.matchedDN == b"cn=foo"
            assert value.errorMessage == b"ok"
            assert decoded.toWire() == wire
            assert used == len(wire)

    def test_result_carries_nonzero_code_and_message(self):
        """A non-success result preserves its numeric resultCode and error text.

        A "no such object" SearchResultDone (resultCode 32) with a matchedDN and a
        human-readable errorMessage round-trips through the envelope with all three
        fields intact.
        """
        op = pureldap.LDAPSearchResultDone(
            resultCode=32, matchedDN="dc=example,dc=com",
            errorMessage="No such object",
        )
        decoded, wire, _ = _wrap_decode(op)
        value = decoded.value
        assert value.resultCode == 32
        assert value.matchedDN == b"dc=example,dc=com"
        assert value.errorMessage == b"No such object"
        assert decoded.toWire() == wire

    def test_bind_response_with_and_without_sasl_creds(self):
        """LDAPBindResponse round-trips both with and without serverSaslCreds.

        A bind response carrying serverSaslCreds (context-tagged optional field)
        decodes those creds back as bytes; a plain bind response (with a non-zero
        resultCode and error text, no creds) decodes with serverSaslCreds == None.
        Both re-encode to their original wire.
        """
        op = pureldap.LDAPBindResponse(
            resultCode=0, matchedDN="", errorMessage="", serverSaslCreds=b"token",
        )
        decoded, wire, _ = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPResult)
        assert decoded.value.resultCode == 0
        assert decoded.value.serverSaslCreds == b"token"
        assert decoded.toWire() == wire

        op2 = pureldap.LDAPBindResponse(resultCode=49, errorMessage="invalid creds")
        decoded2, wire2, _ = _wrap_decode(op2)
        assert decoded2.value.resultCode == 49
        assert decoded2.value.errorMessage == b"invalid creds"
        assert decoded2.value.serverSaslCreds is None
        assert decoded2.toWire() == wire2

    def test_search_result_entry_round_trip(self):
        """LDAPSearchResultEntry decodes its objectName and attribute value lists.

        A search result entry carries the matched DN plus a list of
        (attributeType, [values]) pairs. After an envelope round trip the objectName
        is bytes, the attributes come back as the same (bytes, [bytes,...]) shape with
        order and multi-valued sets preserved, and the re-encoding matches the wire.
        """
        op = pureldap.LDAPSearchResultEntry(
            objectName="cn=foo,dc=example,dc=com",
            attributes=[(b"cn", [b"foo"]), (b"objectClass", [b"top", b"person"])],
        )
        decoded, wire, _ = _wrap_decode(op)
        value = decoded.value
        assert value.objectName == b"cn=foo,dc=example,dc=com"
        assert value.attributes == [
            (b"cn", [b"foo"]),
            (b"objectClass", [b"top", b"person"]),
        ]
        assert decoded.toWire() == wire

    def test_search_result_reference_round_trip(self):
        """LDAPSearchResultReference decodes a list of continuation-reference URIs.

        A reference PDU wraps a set of referral URIs. Decoded as a bare LDAP op via
        the general LDAP context, the URIs come back accessible via their .value
        (bytes) in order, and the object re-encodes to the original wire.
        """
        op = pureldap.LDAPSearchResultReference(
            uris=[
                pureber.BEROctetString(b"ldap://h1/dc=x"),
                pureber.BEROctetString(b"ldap://h2/dc=x"),
            ]
        )
        wire = op.toWire()
        decoded, used = pureber.berDecodeObject(_ldap_ctx(), wire)
        assert isinstance(decoded, pureldap.LDAPSearchResultReference)
        assert [u.value for u in decoded.uris] == [b"ldap://h1/dc=x", b"ldap://h2/dc=x"]
        assert decoded.toWire() == wire
        assert used == len(wire)

    def test_extended_response_round_trip(self):
        """LDAPExtendedResponse decodes its result triple plus responseName/response.

        An extended response carries the standard resultCode/matchedDN/errorMessage
        and the optional context-tagged responseName (an OID) and response value.
        After an envelope round trip all are preserved (responseName/response as
        bytes) and the re-encoding matches the wire.
        """
        op = pureldap.LDAPExtendedResponse(
            resultCode=0, matchedDN="", errorMessage="",
            responseName="1.3.6.1.4.1.1466.20037", response=b"payload",
        )
        decoded, wire, _ = _wrap_decode(op)
        value = decoded.value
        assert value.resultCode == 0
        assert value.responseName == b"1.3.6.1.4.1.1466.20037"
        assert value.response == b"payload"
        assert decoded.toWire() == wire


class TestLessCommonRequestOps:
    def test_add_request_round_trip(self):
        """LDAPAddRequest round-trips through the envelope preserving its entry DN.

        An add request carries the new entry DN plus its attribute sequences. After
        the envelope round trip it decodes to an LDAPAddRequest whose entry is bytes
        and whose re-encoding equals the original wire.
        """
        op = pureldap.LDAPAddRequest(
            entry="cn=foo,dc=example,dc=com",
            attributes=[
                (
                    pureldap.LDAPAttributeDescription("cn"),
                    pureber.BERSet([pureldap.LDAPAttributeValue("foo")]),
                )
            ],
        )
        decoded, wire, used = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPAddRequest)
        assert decoded.value.entry == b"cn=foo,dc=example,dc=com"
        assert decoded.toWire() == wire
        assert used == len(wire)

    def test_modify_dn_request_with_and_without_superior(self):
        """LDAPModifyDNRequest round-trips both plain and with a newSuperior.

        A modifyDN request carries the entry DN, the new RDN, the deleteoldrdn
        boolean (normalized to 0xFF when true), and an optional newSuperior DN. The
        plain form decodes with newSuperior == None; the form with a newSuperior
        decodes that DN as bytes and keeps deleteoldrdn == 0. Both re-encode exactly.
        """
        op = pureldap.LDAPModifyDNRequest(
            entry="cn=foo,dc=x", newrdn="cn=bar", deleteoldrdn=1,
        )
        decoded, wire, _ = _wrap_decode(op)
        value = decoded.value
        assert isinstance(value, pureldap.LDAPModifyDNRequest)
        assert value.entry == b"cn=foo,dc=x"
        assert value.newrdn == b"cn=bar"
        assert value.deleteoldrdn == 0xFF
        assert value.newSuperior is None
        assert decoded.toWire() == wire

        op2 = pureldap.LDAPModifyDNRequest(
            entry="cn=foo,dc=x", newrdn="cn=bar", deleteoldrdn=0,
            newSuperior="dc=new",
        )
        decoded2, wire2, _ = _wrap_decode(op2)
        assert decoded2.value.newSuperior == b"dc=new"
        assert decoded2.value.deleteoldrdn == 0
        assert decoded2.toWire() == wire2

    def test_abandon_request_round_trip(self):
        """LDAPAbandonRequest carries the target message id as an integer op.

        An abandon request is an application-class integer naming the message id to
        abandon. It dispatches by tag through the envelope and decodes back to an
        LDAPAbandonRequest whose .value is that id; re-encoding matches the wire.
        """
        op = pureldap.LDAPAbandonRequest(id=7)
        decoded, wire, _ = _wrap_decode(op)
        assert isinstance(decoded.value, pureldap.LDAPAbandonRequest)
        assert decoded.value.value == 7
        assert decoded.toWire() == wire

    def test_extended_request_with_and_without_value(self):
        """LDAPExtendedRequest round-trips with and without an optional requestValue.

        An extended request carries a requestName (OID) and an optional requestValue.
        The form with a value decodes both back as bytes; the form without a value
        decodes requestValue == None. Both re-encode to the original wire.
        """
        op = pureldap.LDAPExtendedRequest(requestName="1.2.3.4", requestValue=b"payload")
        decoded, wire, _ = _wrap_decode(op)
        value = decoded.value
        assert isinstance(value, pureldap.LDAPExtendedRequest)
        assert value.requestName == b"1.2.3.4"
        assert value.requestValue == b"payload"
        assert decoded.toWire() == wire

        op2 = pureldap.LDAPExtendedRequest(requestName="1.2.3.4")
        decoded2, wire2, _ = _wrap_decode(op2)
        assert decoded2.value.requestName == b"1.2.3.4"
        assert decoded2.value.requestValue is None
        assert decoded2.toWire() == wire2

    def test_sasl_bind_request_with_and_without_credentials(self):
        """A SASL LDAPBindRequest round-trips its (mechanism, credentials) auth.

        With sasl=True the auth is a (mechanism, credentials) tuple carried under a
        context-class sequence rather than the simple-auth octet string. The form
        with credentials decodes auth back as a (mechanism, credentials) bytes tuple
        with sasl True; the credential-less form (credentials None) decodes to
        (mechanism, None). Both re-encode to the original wire.
        """
        op = pureldap.LDAPBindRequest(
            version=3, dn="cn=admin", auth=("DIGEST-MD5", b"creds"), sasl=True,
        )
        decoded, wire, _ = _wrap_decode(op)
        value = decoded.value
        assert isinstance(value, pureldap.LDAPBindRequest)
        assert value.dn == b"cn=admin"
        assert value.auth == (b"DIGEST-MD5", b"creds")
        assert value.sasl is True
        assert decoded.toWire() == wire

        op2 = pureldap.LDAPBindRequest(
            version=3, dn="cn=admin", auth=("EXTERNAL", None), sasl=True,
        )
        decoded2, wire2, _ = _wrap_decode(op2)
        assert decoded2.value.auth == (b"EXTERNAL", None)
        assert decoded2.value.sasl is True
        assert decoded2.toWire() == wire2

    def test_password_modify_and_starttls_requests(self):
        """The two extended-request subclasses pin their fixed OIDs and round-trip.

        LDAPPasswordModifyRequest (built from userIdentity/oldPasswd/newPasswd) and
        LDAPStartTLSRequest each set a fixed requestName OID. Both decode through the
        envelope as extended requests carrying that OID; PasswordModify packs its
        fields into a requestValue blob while StartTLS has no requestValue. Both
        re-encode to the original wire.
        """
        pm = pureldap.LDAPPasswordModifyRequest(
            userIdentity=b"uid", oldPasswd=b"old", newPasswd=b"new",
        )
        decoded, wire, _ = _wrap_decode(pm)
        value = decoded.value
        assert isinstance(value, pureldap.LDAPExtendedRequest)
        assert value.requestName == b"1.3.6.1.4.1.4203.1.11.1"
        assert isinstance(value.requestValue, bytes)
        assert decoded.toWire() == wire

        tls = pureldap.LDAPStartTLSRequest()
        decoded2, wire2, _ = _wrap_decode(tls)
        assert isinstance(decoded2.value, pureldap.LDAPExtendedRequest)
        assert decoded2.value.requestName == b"1.3.6.1.4.1.1466.20037"
        assert decoded2.value.requestValue is None
        assert decoded2.toWire() == wire2


# ==========================================================================
# LDIF write / read
# ==========================================================================

class TestLDIFWriter:
    def test_plain_attribute(self):
        """A printable value is written as 'attr: value'."""
        assert ldifwriter.attributeAsLDIF(b"cn", b"foo") == b"cn: foo\n"

    def test_base64_triggers(self):
        """Values needing protection are base64-encoded with the '::' separator.

        A leading space, a trailing space, a non-printable byte, and an unsafe
        value-initial char (':' or '<') each trigger base64 emission.
        """
        # leading space
        assert ldifwriter.attributeAsLDIF(b"cn", b" foo") == b"cn:: IGZvbw==\n"
        # trailing space
        assert ldifwriter.attributeAsLDIF(b"cn", b"foo ") == b"cn:: Zm9vIA==\n"
        # non-printable high byte
        assert ldifwriter.attributeAsLDIF(b"cn", b"\xff") == b"cn:: /w==\n"
        # unsafe value-initial char ':'
        assert ldifwriter.attributeAsLDIF(b"cn", b":foo") == b"cn:: OmZvbw==\n"
        # unsafe value-initial char '<'
        assert ldifwriter.attributeAsLDIF(b"cn", b"<foo") == b"cn:: PGZvbw==\n"

    def test_asldif_emits_dn_and_attrs(self):
        """asLDIF emits a dn line, each attribute, and a trailing blank line."""
        out = ldifwriter.asLDIF(b"cn=foo", [(b"cn", [b"foo"]), (b"sn", [b"bar"])])
        assert out == b"dn: cn=foo\ncn: foo\nsn: bar\n\n"

    def test_contains_nonprintable(self):
        """containsNonprintable flags newline/high bytes and clears printable ones."""
        assert ldifwriter.containsNonprintable(b"abc") is False
        assert ldifwriter.containsNonprintable(b"a\nb") is True
        assert ldifwriter.containsNonprintable(b"\xff") is True

    def test_base64_encode_helper(self):
        """base64_encode emits the base64 of the bytes with a trailing newline."""
        assert ldifwriter.base64_encode(b"foo") == b"Zm9v\n"

    def test_many_as_ldif_emits_version_header(self):
        """manyAsLDIF prefixes a version header and emits each entry block."""
        out = ldifwriter.manyAsLDIF([(b"cn=foo", [(b"cn", [b"foo"])])])
        assert out == b"version: 1\n\ndn: cn=foo\ncn: foo\n\n"


class _LDIFCollector(ldifprotocol.LDIF):
    def __init__(self):
        super().__init__()
        self.collected = []

    def gotEntry(self, obj):
        self.collected.append(obj)


def _feed(collector, blob):
    for line in blob.split(b"\n"):
        collector.lineReceived(line)


class TestLDIFParser:
    def test_basic_entry(self):
        """The parser reads a version header, DN line, and attribute lines into an entry."""
        c = _LDIFCollector()
        _feed(
            c,
            b"version: 1\n\ndn: cn=foo,dc=example,dc=com\n"
            b"cn: foo\nobjectClass: top\n\n",
        )
        assert len(c.collected) == 1
        entry = c.collected[0]
        assert entry.dn == b"cn=foo,dc=example,dc=com"
        assert set(entry[b"cn"]) == {b"foo"}
        assert set(entry[b"objectClass"]) == {b"top"}

    def test_continuation_folding(self):
        """A continuation line (leading space) is folded onto the previous value."""
        c = _LDIFCollector()
        _feed(c, b"dn: cn=foo\ndescription: hello \n world\n\n")
        assert set(c.collected[0][b"description"]) == {b"hello world"}

    def test_base64_value_decoded(self):
        """A '::' value is base64-decoded into the attribute set."""
        c = _LDIFCollector()
        encoded = base64.encodebytes(b"secret").replace(b"\n", b"")
        _feed(c, b"dn: cn=foo\nuserPassword:: " + encoded + b"\n\n")
        assert set(c.collected[0][b"userPassword"]) == {b"secret"}

    def test_folded_base64_and_multivalue(self):
        """A base64 value folded across two physical lines decodes; multi-valued attrs accumulate."""
        c = _LDIFCollector()
        encoded = base64.encodebytes(b"hello world").replace(b"\n", b"")
        first, rest = encoded[:6], encoded[6:]
        _feed(
            c,
            b"dn: cn=foo\ncn: a\ncn: b\ndescription:: "
            + first
            + b"\n "
            + rest
            + b"\n\n",
        )
        entry = c.collected[0]
        assert set(entry[b"cn"]) == {b"a", b"b"}
        assert set(entry[b"description"]) == {b"hello world"}

    def test_entry_starting_with_space_raises(self):
        """A continuation line before any logical line raises the space error."""
        c = _LDIFCollector()
        with pytest.raises(ldifprotocol.LDIFEntryStartsWithSpaceError):
            c.lineReceived(b" oops")

    def test_entry_starting_with_non_dn_raises(self):
        """An entry whose first line is not a DN raises the non-DN error."""
        c = _LDIFCollector()
        c.lineReceived(b"cn: foo")
        with pytest.raises(ldifprotocol.LDIFEntryStartsWithNonDNError):
            c.lineReceived(b"")

    def test_non_numeric_version_raises(self):
        """A non-numeric version header raises the version-not-a-number error.

        Validation is deferred: because a logical line is only complete once the
        *next* physical line is seen (continuation folding holds each line one
        step behind), feeding ``version: abc`` alone must NOT raise yet. The error
        only fires when the following line is delivered and the buffered version
        line is finally processed.
        """
        c = _LDIFCollector()
        # The version line is buffered, not validated eagerly: no raise here.
        c.lineReceived(b"version: abc")
        with pytest.raises(ldifprotocol.LDIFVersionNotANumberError):
            c.lineReceived(b"")

    def test_unsupported_version_raises(self):
        """A version greater than 1 raises the unsupported-version error.

        As with the non-numeric case, validation is deferred one line: feeding
        ``version: 2`` alone must not raise; the unsupported-version error is
        raised only when the next physical line forces the buffered version line
        to be processed.
        """
        c = _LDIFCollector()
        # Buffered, not validated eagerly: no raise on the version line itself.
        c.lineReceived(b"version: 2")
        with pytest.raises(ldifprotocol.LDIFUnsupportedVersionError):
            c.lineReceived(b"")
