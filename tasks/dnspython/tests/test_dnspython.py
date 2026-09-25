"""
Integration tests for dnspython — DNS protocol library.

Tests verify the core DNS protocol implementation: name encoding/compression,
message wire format encoding/decoding, common record types, rdatasets/rrsets,
flags, and error handling. Tests use round-trip verification: build objects
programmatically, serialize to wire format, deserialize back, and verify
all fields match.
"""
import struct
import unittest


# ===========================================================================
# 1. DNS Names — encoding, parsing, labels, compression, edge cases
# ===========================================================================
class TestDNSName(unittest.TestCase):
    """DNS name creation, text parsing, wire encoding, compression, and edge cases."""

    def test_name_operations(self):
        """DNS names: text parsing, labels, case-insensitive equality, wire round-trip, hierarchy."""
        import dns.name

        # --- text parsing and labels ---
        n = dns.name.from_text("www.example.com.")
        self.assertTrue(n.is_absolute())
        self.assertEqual(n.labels, (b"www", b"example", b"com", b""))
        self.assertEqual(n.to_text(), "www.example.com.")
        self.assertEqual(n.to_text(omit_final_dot=True), "www.example.com")
        self.assertEqual(len(n), 4)

        n_rel = dns.name.from_text("www.example.com")
        self.assertTrue(n_rel.is_absolute())

        n_no_origin = dns.name.from_text("www.example", origin=None)
        self.assertFalse(n_no_origin.is_absolute())
        self.assertEqual(n_no_origin.labels, (b"www", b"example"))

        self.assertTrue(dns.name.root.is_absolute())
        self.assertEqual(dns.name.root.to_text(), ".")

        # --- case-insensitive equality ---
        n1 = dns.name.from_text("WWW.Example.COM.")
        n2 = dns.name.from_text("www.example.com.")
        self.assertEqual(n1, n2)
        self.assertEqual(hash(n1), hash(n2))

        # --- wire round-trip ---
        wire = n.to_wire()
        self.assertEqual(wire[0], 3)
        self.assertEqual(wire[4], 7)
        self.assertTrue(wire.endswith(b"\x00"))

        # --- hierarchy operations ---
        child = dns.name.from_text("www.example.com.")
        parent = dns.name.from_text("example.com.")
        self.assertTrue(child.is_subdomain(parent))
        self.assertFalse(parent.is_subdomain(child))
        self.assertEqual(child.parent(), parent)

        prefix = dns.name.from_text("www", origin=None)
        suffix = dns.name.from_text("example.com.")
        self.assertEqual(prefix + suffix, child)

    def test_name_edge_cases(self):
        """DNS names: canonical ordering, escaped dots, wire canonicalization."""
        import dns.name

        # --- canonical ordering is right-to-left ---
        n_az = dns.name.from_text("a.z.example.com.")
        n_za = dns.name.from_text("z.a.example.com.")
        self.assertTrue(n_za < n_az)
        self.assertFalse(n_az < n_za)
        names = [
            dns.name.from_text("z.example.com."),
            dns.name.from_text("a.example.com."),
            dns.name.from_text("example.com."),
            dns.name.from_text("b.a.example.com."),
        ]
        sorted_names = sorted(names)
        self.assertEqual(str(sorted_names[0]), "example.com.")
        self.assertEqual(str(sorted_names[1]), "a.example.com.")
        self.assertEqual(str(sorted_names[2]), "b.a.example.com.")
        self.assertEqual(str(sorted_names[3]), "z.example.com.")

        # --- escaped dot in label ---
        n = dns.name.from_text(r"has\.dot.example.com.")
        self.assertEqual(n.labels[0], b"has.dot")
        self.assertEqual(len(n), 4)
        wire = n.to_wire()
        self.assertEqual(wire[0], 7)

        # --- wire canonicalization lowercases ---
        n_upper = dns.name.from_text("WWW.EXAMPLE.COM.")
        wire_normal = n_upper.to_wire()
        wire_canon = n_upper.to_wire(canonicalize=True)
        self.assertEqual(wire_canon[:4], b"\x03www")
        self.assertNotEqual(wire_normal[:4], b"\x03www")


# ===========================================================================
# 2. DNS Messages — make_query, to_wire, from_wire round-trip
# ===========================================================================
class TestDNSMessage(unittest.TestCase):
    """DNS message creation, wire encoding/decoding, and round-trip."""

    def test_message_creation(self):
        """make_query, make_response, and header structure."""
        import dns.exception
        import dns.flags
        import dns.message
        import dns.name
        import dns.rdataclass
        import dns.rdatatype

        # --- make_query ---
        msg = dns.message.make_query("example.com.", "A")
        self.assertEqual(len(msg.question), 1)
        q = msg.question[0]
        self.assertEqual(q.name, dns.name.from_text("example.com."))
        self.assertEqual(q.rdtype, dns.rdatatype.A)
        self.assertEqual(q.rdclass, dns.rdataclass.IN)
        self.assertTrue(msg.flags & dns.flags.RD)
        self.assertFalse(msg.flags & dns.flags.QR)
        for rdtype_str in ["AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "SRV", "PTR"]:
            msg2 = dns.message.make_query("example.com.", rdtype_str)
            self.assertEqual(msg2.question[0].rdtype,
                             dns.rdatatype.from_text(rdtype_str))

        # --- make_response ---
        query = dns.message.make_query("example.com.", "A")
        response = dns.message.make_response(query)
        self.assertTrue(response.flags & dns.flags.QR)
        self.assertEqual(response.id, query.id)

        # --- header is 12 bytes ---
        msg3 = dns.message.make_query("a.b.", "A")
        wire = msg3.to_wire()
        self.assertGreaterEqual(len(wire), 12)
        (qid, flags, qdcount, ancount, nscount, arcount) = struct.unpack("!HHHHHH", wire[:12])
        self.assertEqual(qid, msg3.id)
        self.assertEqual(qdcount, 1)
        self.assertEqual(ancount, 0)

    def test_message_wire_operations(self):
        """Wire round-trip, EDNS, name compression, and short wire error."""
        import dns.exception
        import dns.flags
        import dns.message
        import dns.rrset

        # --- wire round-trip ---
        msg = dns.message.make_query("www.example.com.", "A")
        wire = msg.to_wire()
        msg2 = dns.message.from_wire(wire)
        self.assertEqual(msg.id, msg2.id)
        self.assertEqual(msg.flags, msg2.flags)
        self.assertEqual(len(msg.question), len(msg2.question))
        self.assertEqual(msg.question[0].name, msg2.question[0].name)
        self.assertEqual(msg.question[0].rdtype, msg2.question[0].rdtype)

        # --- EDNS ---
        msg_edns = dns.message.make_query("example.com.", "A", use_edns=0)
        wire_edns = msg_edns.to_wire()
        msg_edns2 = dns.message.from_wire(wire_edns)
        self.assertEqual(msg_edns2.edns, 0)

        # --- name compression ---
        msg_comp = dns.message.make_query("example.com.", "A")
        msg_comp.flags |= dns.flags.QR
        rrset = dns.rrset.from_text("example.com.", 300, "IN", "A", "192.0.2.1")
        msg_comp.answer.append(rrset)
        wire_comp = msg_comp.to_wire()
        self.assertLess(len(wire_comp), 100)
        # The answer owner name repeats the question name, so it must be emitted as a
        # compression pointer (0xc0..) rather than spelled out again; an implementation
        # that performs no name compression would fail this.
        self.assertIn(b"\xc0", wire_comp)

        # --- short wire raises ---
        with self.assertRaises(dns.exception.FormError):
            dns.message.from_wire(b"\x00" * 5)

    def test_message_sections(self):
        """Answer, multiple answers, and authority section round-trip."""
        import dns.flags
        import dns.message
        import dns.rrset

        # --- single answer ---
        msg = dns.message.make_query("example.com.", "A")
        msg.flags |= dns.flags.QR
        rrset = dns.rrset.from_text("example.com.", 300, "IN", "A", "192.0.2.1")
        msg.answer.append(rrset)
        wire = msg.to_wire()
        msg2 = dns.message.from_wire(wire)
        self.assertEqual(len(msg2.answer), 1)
        self.assertEqual(str(msg2.answer[0][0]), "192.0.2.1")

        # --- multiple rrsets of different rdtypes in one section ---
        # A distinct contract from multi-record coalescing (covered in test_message_edge_cases):
        # the answer section must keep separate rrsets keyed by (name, rdtype), so an A and a TXT
        # rrset for the same owner survive the round-trip as two distinct rrsets.
        import dns.rdatatype
        msg3 = dns.message.make_query("example.com.", "A")
        msg3.flags |= dns.flags.QR
        msg3.answer.append(dns.rrset.from_text("example.com.", 300, "IN", "A", "192.0.2.1"))
        msg3.answer.append(dns.rrset.from_text("example.com.", 300, "IN", "TXT", '"hi"'))
        wire3 = msg3.to_wire()
        msg4 = dns.message.from_wire(wire3)
        self.assertEqual(len(msg4.answer), 2)
        by_type = {rr.rdtype: rr for rr in msg4.answer}
        self.assertEqual(str(by_type[dns.rdatatype.A][0]), "192.0.2.1")
        self.assertEqual(by_type[dns.rdatatype.TXT][0].strings, (b"hi",))

        # --- authority section ---
        msg5 = dns.message.make_query("example.com.", "A")
        msg5.flags |= dns.flags.QR
        ns_rrset = dns.rrset.from_text("example.com.", 3600, "IN", "NS",
                                        "ns1.example.com.", "ns2.example.com.")
        msg5.authority.append(ns_rrset)
        wire5 = msg5.to_wire()
        msg6 = dns.message.from_wire(wire5)
        self.assertEqual(len(msg6.authority), 1)
        self.assertEqual(len(msg6.authority[0]), 2)


# ===========================================================================
# 3. Record types — bundled by capability
# ===========================================================================
class TestRecordTypeTextParsing(unittest.TestCase):
    """All record types parse from text and produce correct str() output."""

    def test_record_type_text_parsing(self):
        """All record types: text parsing, field access, SOA fields, TXT strings."""
        import dns.name
        import dns.rdata

        # A, AAAA, MX, NS, CNAME, PTR, SRV
        rd_a = dns.rdata.from_text("IN", "A", "192.0.2.1")
        self.assertEqual(rd_a.address, "192.0.2.1")
        self.assertEqual(str(rd_a), "192.0.2.1")

        rd_aaaa = dns.rdata.from_text("IN", "AAAA", "2001:db8::1")
        # Pin the exact canonical IPv6 presentation form (RFC 5952): zero-compressed, lowercase.
        self.assertEqual(str(rd_aaaa), "2001:db8::1")

        rd_mx = dns.rdata.from_text("IN", "MX", "10 mail.example.com.")
        self.assertEqual(rd_mx.preference, 10)
        self.assertEqual(rd_mx.exchange, dns.name.from_text("mail.example.com."))
        self.assertEqual(str(rd_mx), "10 mail.example.com.")

        rd_ns = dns.rdata.from_text("IN", "NS", "ns1.example.com.")
        self.assertEqual(rd_ns.target, dns.name.from_text("ns1.example.com."))

        rd_cname = dns.rdata.from_text("IN", "CNAME", "www.example.com.")
        self.assertEqual(rd_cname.target, dns.name.from_text("www.example.com."))

        rd_ptr = dns.rdata.from_text("IN", "PTR", "host.example.com.")
        self.assertEqual(rd_ptr.target, dns.name.from_text("host.example.com."))

        rd_srv = dns.rdata.from_text("IN", "SRV", "10 60 5060 server.example.com.")
        self.assertEqual(rd_srv.priority, 10)
        self.assertEqual(rd_srv.weight, 60)
        self.assertEqual(rd_srv.port, 5060)
        self.assertEqual(rd_srv.target, dns.name.from_text("server.example.com."))

        # SOA — all 7 fields
        rd = dns.rdata.from_text("IN", "SOA",
                                  "ns1.example.com. admin.example.com. 2024010101 3600 900 604800 86400")
        self.assertEqual(rd.mname, dns.name.from_text("ns1.example.com."))
        self.assertEqual(rd.rname, dns.name.from_text("admin.example.com."))
        self.assertEqual(rd.serial, 2024010101)
        self.assertEqual(rd.refresh, 3600)
        self.assertEqual(rd.retry, 900)
        self.assertEqual(rd.expire, 604800)
        self.assertEqual(rd.minimum, 86400)

        # TXT — single and multiple strings
        rd_single = dns.rdata.from_text("IN", "TXT", '"hello world"')
        self.assertEqual(rd_single.strings, (b"hello world",))
        rd_multi = dns.rdata.from_text("IN", "TXT", '"hello" "world"')
        self.assertEqual(rd_multi.strings, (b"hello", b"world"))
        self.assertEqual(str(rd_single), '"hello world"')


class TestRecordTypeWireRoundTrip(unittest.TestCase):
    """All record types serialize to wire format and parse back correctly."""

    def test_address_records_wire_roundtrip(self):
        """A and AAAA records produce correct wire lengths and round-trip."""
        import dns.rdata
        rd_a = dns.rdata.from_text("IN", "A", "192.168.1.1")
        wire_a = rd_a.to_wire()
        self.assertEqual(len(wire_a), 4)
        rd_a2 = dns.rdata.from_wire("IN", "A", wire_a, 0, len(wire_a))
        self.assertEqual(rd_a, rd_a2)

        rd_aaaa = dns.rdata.from_text("IN", "AAAA", "::1")
        wire_aaaa = rd_aaaa.to_wire()
        self.assertEqual(len(wire_aaaa), 16)
        rd_aaaa2 = dns.rdata.from_wire("IN", "AAAA", wire_aaaa, 0, len(wire_aaaa))
        self.assertEqual(rd_aaaa, rd_aaaa2)

    def test_name_bearing_records_wire_roundtrip(self):
        """NS, CNAME, PTR, MX records with DNS name fields round-trip through wire."""
        import dns.rdata
        for rdtype, text in [
            ("NS", "ns2.example.com."),
            ("CNAME", "alias.example.com."),
            ("PTR", "reverse.example.com."),
        ]:
            rd = dns.rdata.from_text("IN", rdtype, text)
            wire = rd.to_wire()
            rd2 = dns.rdata.from_wire("IN", rdtype, wire, 0, len(wire))
            self.assertEqual(rd.target, rd2.target)

        rd_mx = dns.rdata.from_text("IN", "MX", "10 mail.example.com.")
        wire_mx = rd_mx.to_wire()
        rd_mx2 = dns.rdata.from_wire("IN", "MX", wire_mx, 0, len(wire_mx))
        self.assertEqual(rd_mx.preference, rd_mx2.preference)
        self.assertEqual(rd_mx.exchange, rd_mx2.exchange)

    def test_complex_records_wire_roundtrip(self):
        """SOA, SRV, TXT records with multi-field wire formats round-trip correctly."""
        import dns.rdata
        rd_soa = dns.rdata.from_text("IN", "SOA",
                                      "ns.example.com. hostmaster.example.com. 1 7200 900 1209600 86400")
        wire_soa = rd_soa.to_wire()
        rd_soa2 = dns.rdata.from_wire("IN", "SOA", wire_soa, 0, len(wire_soa))
        self.assertEqual(rd_soa.serial, rd_soa2.serial)
        self.assertEqual(rd_soa.mname, rd_soa2.mname)

        rd_srv = dns.rdata.from_text("IN", "SRV", "0 5 80 www.example.com.")
        wire_srv = rd_srv.to_wire()
        rd_srv2 = dns.rdata.from_wire("IN", "SRV", wire_srv, 0, len(wire_srv))
        self.assertEqual(rd_srv.priority, rd_srv2.priority)
        self.assertEqual(rd_srv.port, rd_srv2.port)
        self.assertEqual(rd_srv.target, rd_srv2.target)

        rd_txt = dns.rdata.from_text("IN", "TXT", '"test string"')
        wire_txt = rd_txt.to_wire()
        self.assertEqual(wire_txt[0], len(b"test string"))
        rd_txt2 = dns.rdata.from_wire("IN", "TXT", wire_txt, 0, len(wire_txt))
        self.assertEqual(rd_txt.strings, rd_txt2.strings)


# ===========================================================================
# 4. Rdata general properties
# ===========================================================================
class TestRdataProperties(unittest.TestCase):
    """General rdata properties: immutability, comparison, type checking."""

    def test_rdata_properties(self):
        """Rdata: immutability, ordering, rdtype/rdclass, generic rdata."""
        import dns.rdata
        import dns.rdataclass
        import dns.rdatatype

        # --- immutable ---
        rd = dns.rdata.from_text("IN", "A", "1.2.3.4")
        with self.assertRaises((TypeError, AttributeError)):
            rd.address = "5.6.7.8"

        # --- ordering (A records compare by canonical wire bytes; 1.0.0.1 sorts before 2.0.0.1) ---
        rd1 = dns.rdata.from_text("IN", "A", "1.0.0.1")
        rd2 = dns.rdata.from_text("IN", "A", "2.0.0.1")
        self.assertTrue(rd1 < rd2)
        self.assertFalse(rd2 < rd1)
        self.assertTrue(rd2 > rd1)

        # --- rdtype and rdclass ---
        rd_mx = dns.rdata.from_text("IN", "MX", "10 mail.example.com.")
        self.assertEqual(rd_mx.rdtype, dns.rdatatype.MX)
        self.assertEqual(rd_mx.rdclass, dns.rdataclass.IN)

        # --- generic rdata ---
        rd_gen = dns.rdata.from_text("IN", "TYPE12345", r"\# 4 01020304")
        wire = rd_gen.to_wire()
        self.assertEqual(wire, b"\x01\x02\x03\x04")


# ===========================================================================
# 5–6. Rdatasets and RRsets — collections of same-type records
# ===========================================================================
class TestRdatasetAndRRset(unittest.TestCase):
    """Rdataset and RRset creation, manipulation, and text conversion."""

    def test_rdataset_operations(self):
        """Rdataset: from_text, add, TTL minimization, IncompatibleTypes, to_text."""
        import dns.rdata
        import dns.rdataclass
        import dns.rdataset
        import dns.rdatatype

        # from_text creation
        rds = dns.rdataset.from_text("IN", "A", 300, "192.0.2.1", "192.0.2.2")
        self.assertEqual(len(rds), 2)
        self.assertEqual(rds.ttl, 300)
        self.assertEqual(rds.rdtype, dns.rdatatype.A)

        # add
        rds2 = dns.rdataset.Rdataset(dns.rdataclass.IN, dns.rdatatype.A)
        rd = dns.rdata.from_text("IN", "A", "10.0.0.1")
        rds2.add(rd, 300)
        self.assertEqual(len(rds2), 1)

        # TTL minimization
        rds3 = dns.rdataset.from_text("IN", "A", 600, "10.0.0.1")
        rd2 = dns.rdata.from_text("IN", "A", "10.0.0.2")
        rds3.add(rd2, 300)
        self.assertEqual(rds3.ttl, 300)

        # IncompatibleTypes
        rds4 = dns.rdataset.Rdataset(dns.rdataclass.IN, dns.rdatatype.A)
        rd_mx = dns.rdata.from_text("IN", "MX", "10 mail.example.com.")
        with self.assertRaises(dns.rdataset.IncompatibleTypes):
            rds4.add(rd_mx, 300)

        # to_text
        rds5 = dns.rdataset.from_text("IN", "A", 300, "192.0.2.1")
        text = rds5.to_text()
        self.assertIn("192.0.2.1", text)
        self.assertIn("300", text)

    def test_rrset_operations(self):
        """RRset: from_text with multiple records, from_rdata, to_text with name, len."""
        import dns.name
        import dns.rdata
        import dns.rrset

        # from_text with multiple records
        rrs = dns.rrset.from_text("example.com.", 300, "IN", "A",
                                   "192.0.2.1", "192.0.2.2", "192.0.2.3")
        self.assertEqual(rrs.name, dns.name.from_text("example.com."))
        self.assertEqual(rrs.ttl, 300)
        self.assertEqual(len(rrs), 3)

        # from_rdata
        rd1 = dns.rdata.from_text("IN", "A", "1.2.3.4")
        rd2 = dns.rdata.from_text("IN", "A", "5.6.7.8")
        rrs2 = dns.rrset.from_rdata("example.com.", 600, rd1, rd2)
        self.assertEqual(len(rrs2), 2)
        self.assertEqual(rrs2.ttl, 600)

        # to_text with name
        rrs3 = dns.rrset.from_text("example.com.", 300, "IN", "A", "10.0.0.1")
        text = rrs3.to_text()
        self.assertIn("example.com.", text)
        self.assertIn("10.0.0.1", text)


# ===========================================================================
# 7–8. Rdatatype, Rdataclass, Flags, Opcodes, Rcodes
# ===========================================================================
class TestEnumsAndFlags(unittest.TestCase):
    """DNS type/class enums and header flags/opcodes/rcodes."""

    def test_type_and_class_enums(self):
        """Rdatatype and rdataclass: from_text, to_text, numeric values."""
        import dns.rdataclass
        import dns.rdatatype

        # rdatatype from_text
        self.assertEqual(dns.rdatatype.from_text("A"), dns.rdatatype.A)
        self.assertEqual(dns.rdatatype.from_text("AAAA"), dns.rdatatype.AAAA)
        self.assertEqual(dns.rdatatype.from_text("MX"), dns.rdatatype.MX)
        self.assertEqual(dns.rdatatype.from_text("CNAME"), dns.rdatatype.CNAME)
        self.assertEqual(dns.rdatatype.from_text("SOA"), dns.rdatatype.SOA)

        # rdatatype to_text round-trips (the numeric code points are pinned on the wire by
        # test_wire_vector_parsing, so assert lookup-table behavior here rather than restating
        # the IANA constants).
        self.assertEqual(dns.rdatatype.to_text(dns.rdatatype.A), "A")
        self.assertEqual(dns.rdatatype.to_text(dns.rdatatype.NS), "NS")
        self.assertEqual(dns.rdatatype.from_text("TXT"), dns.rdatatype.TXT)
        self.assertEqual(dns.rdatatype.to_text(dns.rdatatype.AAAA), "AAAA")

        # rdataclass from_text/to_text round-trips
        self.assertEqual(dns.rdataclass.from_text("IN"), dns.rdataclass.IN)
        self.assertEqual(dns.rdataclass.to_text(dns.rdataclass.IN), "IN")
        self.assertEqual(dns.rdataclass.from_text("CH"), dns.rdataclass.CH)

    def test_flags_opcodes_rcodes(self):
        """Flags, opcodes, rcodes: from_text, to_text, constants."""
        import dns.flags
        import dns.opcode
        import dns.rcode

        # flags from_text
        flags = dns.flags.from_text("QR AA RD RA")
        self.assertTrue(flags & dns.flags.QR)
        self.assertTrue(flags & dns.flags.AA)
        self.assertTrue(flags & dns.flags.RD)
        self.assertTrue(flags & dns.flags.RA)

        # flags to_text round-trips both ways (the numeric bit positions are pinned on the wire
        # by test_wire_vector_parsing, so assert from_text/to_text behavior, not the constants).
        flags2 = dns.flags.QR | dns.flags.RD
        text = dns.flags.to_text(flags2)
        self.assertIn("QR", text)
        self.assertIn("RD", text)
        self.assertEqual(dns.flags.from_text(text), flags2)

        # opcodes
        self.assertEqual(dns.opcode.from_text("QUERY"), dns.opcode.QUERY)
        self.assertEqual(dns.opcode.from_text("NOTIFY"), dns.opcode.NOTIFY)

        # rcodes from_text/to_text round-trips
        self.assertEqual(dns.rcode.from_text("NOERROR"), dns.rcode.NOERROR)
        self.assertEqual(dns.rcode.from_text("NXDOMAIN"), dns.rcode.NXDOMAIN)
        self.assertEqual(dns.rcode.from_text("SERVFAIL"), dns.rcode.SERVFAIL)
        self.assertEqual(dns.rcode.from_text("FORMERR"), dns.rcode.FORMERR)
        self.assertEqual(dns.rcode.to_text(dns.rcode.NXDOMAIN), "NXDOMAIN")


# ===========================================================================
# 9. Wire format test vectors — known DNS packets
# ===========================================================================
class TestWireVectors(unittest.TestCase):
    """Parse known DNS wire format packets and verify contents."""

    def test_wire_vector_parsing(self):
        """Parse query, A/MX/AAAA/TXT/NS/SRV responses and a CHAOS NXDOMAIN from wire bytes."""
        import dns.flags
        import dns.message
        import dns.name
        import dns.rdatatype

        # --- simple A query ---
        wire_query = (
            b"\x12\x34"  # ID
            b"\x01\x00"  # Flags: RD
            b"\x00\x01"  # QDCOUNT=1
            b"\x00\x00"  # ANCOUNT=0
            b"\x00\x00"  # NSCOUNT=0
            b"\x00\x00"  # ARCOUNT=0
            b"\x03www\x07example\x03com\x00"  # QNAME
            b"\x00\x01"  # QTYPE=A
            b"\x00\x01"  # QCLASS=IN
        )
        msg = dns.message.from_wire(wire_query)
        self.assertEqual(msg.id, 0x1234)
        self.assertTrue(msg.flags & dns.flags.RD)
        self.assertEqual(len(msg.question), 1)
        self.assertEqual(msg.question[0].name, dns.name.from_text("www.example.com."))
        self.assertEqual(msg.question[0].rdtype, dns.rdatatype.A)

        # --- response with A answer ---
        wire_resp = (
            b"\x12\x34"  # ID
            b"\x81\x80"  # Flags: QR + RD + RA
            b"\x00\x01"  # QDCOUNT=1
            b"\x00\x01"  # ANCOUNT=1
            b"\x00\x00"  # NSCOUNT=0
            b"\x00\x00"  # ARCOUNT=0
            # Question: example.com. IN A
            b"\x07example\x03com\x00"
            b"\x00\x01"  # QTYPE=A
            b"\x00\x01"  # QCLASS=IN
            # Answer: example.com. (compressed) 300 IN A 93.184.216.34
            b"\xc0\x0c"  # Name pointer to offset 12 (example.com.)
            b"\x00\x01"  # TYPE=A
            b"\x00\x01"  # CLASS=IN
            b"\x00\x00\x01\x2c"  # TTL=300
            b"\x00\x04"  # RDLENGTH=4
            b"\x5d\xb8\xd8\x22"  # RDATA=93.184.216.34
        )
        msg2 = dns.message.from_wire(wire_resp)
        self.assertTrue(msg2.flags & dns.flags.QR)
        self.assertEqual(len(msg2.answer), 1)
        self.assertEqual(str(msg2.answer[0][0]), "93.184.216.34")
        self.assertEqual(msg2.answer[0].ttl, 300)

        # --- MX response ---
        wire_mx = (
            b"\xab\xcd"  # ID
            b"\x81\x80"  # Flags: QR + RD + RA
            b"\x00\x01"  # QDCOUNT=1
            b"\x00\x01"  # ANCOUNT=1
            b"\x00\x00"  # NSCOUNT=0
            b"\x00\x00"  # ARCOUNT=0
            # Question: example.com. MX IN
            b"\x07example\x03com\x00"
            b"\x00\x0f"  # QTYPE=MX
            b"\x00\x01"  # QCLASS=IN
            # Answer: example.com. 3600 IN MX 10 mail.example.com.
            b"\xc0\x0c"  # Name pointer
            b"\x00\x0f"  # TYPE=MX
            b"\x00\x01"  # CLASS=IN
            b"\x00\x00\x0e\x10"  # TTL=3600
            b"\x00\x14"  # RDLENGTH=20
            b"\x00\x0a"  # Preference=10
            b"\x04mail\x07example\x03com\x00"  # Exchange
        )
        msg3 = dns.message.from_wire(wire_mx)
        self.assertEqual(len(msg3.answer), 1)
        mx_rd = msg3.answer[0][0]
        self.assertEqual(mx_rd.preference, 10)
        self.assertEqual(mx_rd.exchange, dns.name.from_text("mail.example.com."))

        # --- authoritative multi-section response: pins the AAAA/TXT/NS/SRV type code points
        #     and the AA/RA header bits on the wire (a wrongly-numbered enum mis-parses this) ---
        import dns.rdataclass
        import dns.rcode

        wire_multi = (
            b"\x56\x78"  # ID
            b"\x84\x80"  # Flags: QR + AA + RA
            b"\x00\x01"  # QDCOUNT=1
            b"\x00\x02"  # ANCOUNT=2
            b"\x00\x01"  # NSCOUNT=1
            b"\x00\x01"  # ARCOUNT=1
            # Question: example.com. IN AAAA
            b"\x07example\x03com\x00"
            b"\x00\x1c"  # QTYPE=AAAA
            b"\x00\x01"  # QCLASS=IN
            # Answer 1: example.com. 60 IN AAAA 2001:db8::1
            b"\xc0\x0c"
            b"\x00\x1c"  # TYPE=AAAA
            b"\x00\x01"  # CLASS=IN
            b"\x00\x00\x00\x3c"  # TTL=60
            b"\x00\x10"  # RDLENGTH=16
            b"\x20\x01\x0d\xb8" + b"\x00" * 11 + b"\x01"
            # Answer 2: example.com. 60 IN TXT "hi"
            + b"\xc0\x0c"
            b"\x00\x10"  # TYPE=TXT
            b"\x00\x01"
            b"\x00\x00\x00\x3c"
            b"\x00\x03"  # RDLENGTH=3
            b"\x02hi"
            # Authority: example.com. 60 IN NS ns1.example.com.
            b"\xc0\x0c"
            b"\x00\x02"  # TYPE=NS
            b"\x00\x01"
            b"\x00\x00\x00\x3c"
            b"\x00\x11"  # RDLENGTH=17
            b"\x03ns1\x07example\x03com\x00"
            # Additional: _sip._udp.example.com. 60 IN SRV 10 20 5060 sip.example.com.
            b"\x04_sip\x04_udp\x07example\x03com\x00"
            b"\x00\x21"  # TYPE=SRV
            b"\x00\x01"
            b"\x00\x00\x00\x3c"
            b"\x00\x17"  # RDLENGTH=23
            b"\x00\x0a"  # priority=10
            b"\x00\x14"  # weight=20
            b"\x13\xc4"  # port=5060
            b"\x03sip\x07example\x03com\x00"  # target
        )
        msg4 = dns.message.from_wire(wire_multi)
        self.assertTrue(msg4.flags & dns.flags.AA)
        self.assertTrue(msg4.flags & dns.flags.RA)
        self.assertEqual(msg4.question[0].rdtype, dns.rdatatype.AAAA)
        answers = {rrset.rdtype: rrset for rrset in msg4.answer}
        self.assertEqual(str(answers[dns.rdatatype.AAAA][0]), "2001:db8::1")
        self.assertEqual(answers[dns.rdatatype.TXT][0].strings, (b"hi",))
        self.assertEqual(msg4.authority[0].rdtype, dns.rdatatype.NS)
        self.assertEqual(msg4.authority[0][0].target, dns.name.from_text("ns1.example.com."))
        self.assertEqual(msg4.additional[0].rdtype, dns.rdatatype.SRV)
        srv_rd = msg4.additional[0][0]
        self.assertEqual((srv_rd.priority, srv_rd.weight, srv_rd.port), (10, 20, 5060))
        self.assertEqual(srv_rd.target, dns.name.from_text("sip.example.com."))

        # --- CHAOS-class question in an NXDOMAIN response: pins the CH class and the rcode
        #     nibble on the wire ---
        wire_ch = (
            b"\x9a\xbc"  # ID
            b"\x81\x83"  # Flags: QR + RD + RA, RCODE=NXDOMAIN
            b"\x00\x01"  # QDCOUNT=1
            b"\x00\x00"  # ANCOUNT=0
            b"\x00\x00"  # NSCOUNT=0
            b"\x00\x00"  # ARCOUNT=0
            # Question: version.bind. CH TXT
            b"\x07version\x04bind\x00"
            b"\x00\x10"  # QTYPE=TXT
            b"\x00\x03"  # QCLASS=CH
        )
        msg5 = dns.message.from_wire(wire_ch)
        self.assertEqual(msg5.rcode(), dns.rcode.NXDOMAIN)
        self.assertEqual(msg5.question[0].rdclass, dns.rdataclass.CH)
        self.assertEqual(msg5.question[0].rdtype, dns.rdatatype.TXT)


# ===========================================================================
# 10. Error handling
# ===========================================================================
class TestErrorHandling(unittest.TestCase):
    """DNS protocol error detection and exception handling."""

    def test_error_handling(self):
        """FormError on short message, invalid rdatatype, invalid rcode, name too long."""
        import dns.exception
        import dns.message
        import dns.name
        import dns.rcode
        import dns.rdatatype

        # --- short message raises FormError ---
        with self.assertRaises(dns.exception.FormError):
            dns.message.from_wire(b"\x00" * 8)

        # --- invalid rdatatype ---
        with self.assertRaises(dns.rdatatype.UnknownRdatatype):
            dns.rdatatype.from_text("BOGUS")

        # --- invalid rcode ---
        with self.assertRaises(Exception):
            dns.rcode.from_text("BOGUS")

        # --- name too long ---
        labels = [b"a" * 63] * 4 + [b""]  # 4*64 + 1 = 257 bytes > 255
        with self.assertRaises(Exception):
            dns.name.Name(labels).to_wire()


# ===========================================================================
# 11. Message opcode, rcode, and protocol edge cases
# ===========================================================================
class TestMessageProtocol(unittest.TestCase):
    """Message opcode, rcode, and protocol edge cases."""

    def test_opcode_and_rcode(self):
        """Query opcode, set/get rcode, rcode wire round-trip."""
        import dns.flags
        import dns.message
        import dns.opcode
        import dns.rcode

        # --- query opcode ---
        msg = dns.message.make_query("example.com.", "A")
        self.assertEqual(msg.opcode(), dns.opcode.QUERY)

        # --- set rcode ---
        msg.flags |= dns.flags.QR
        msg.set_rcode(dns.rcode.NXDOMAIN)
        self.assertEqual(msg.rcode(), dns.rcode.NXDOMAIN)

        # --- rcode wire round-trip ---
        msg2 = dns.message.make_query("example.com.", "A")
        msg2.flags |= dns.flags.QR
        msg2.set_rcode(dns.rcode.SERVFAIL)
        wire = msg2.to_wire()
        msg3 = dns.message.from_wire(wire)
        self.assertEqual(msg3.rcode(), dns.rcode.SERVFAIL)

    def test_message_edge_cases(self):
        """Extended rcode via EDNS, RRset coalescing, cross-section compression."""
        import dns.flags
        import dns.message
        import dns.rcode
        import dns.rrset

        # --- extended rcode via EDNS ---
        msg = dns.message.make_query("example.com.", "A", use_edns=0)
        msg.flags |= dns.flags.QR
        msg.set_rcode(dns.rcode.BADVERS)
        wire = msg.to_wire()
        msg2 = dns.message.from_wire(wire)
        self.assertEqual(msg2.rcode(), dns.rcode.BADVERS)

        # --- multi-record RRset coalescing ---
        msg3 = dns.message.make_query("multi.com.", "A")
        msg3.flags |= dns.flags.QR
        rrset = dns.rrset.from_text("multi.com.", 300, "IN", "A",
                                     "1.1.1.1", "2.2.2.2", "3.3.3.3")
        msg3.answer.append(rrset)
        wire3 = msg3.to_wire()
        msg4 = dns.message.from_wire(wire3)
        self.assertEqual(len(msg4.answer), 1)
        self.assertEqual(len(msg4.answer[0]), 3)
        addrs = sorted([str(r) for r in msg4.answer[0]])
        self.assertEqual(addrs, ["1.1.1.1", "2.2.2.2", "3.3.3.3"])

        # --- cross-section name compression ---
        msg5 = dns.message.make_query("a.example.com.", "A")
        msg5.flags |= dns.flags.QR
        msg5.answer.append(dns.rrset.from_text("a.example.com.", 300, "IN", "A", "1.1.1.1"))
        msg5.answer.append(dns.rrset.from_text("b.example.com.", 300, "IN", "A", "2.2.2.2"))
        msg5.authority.append(dns.rrset.from_text("example.com.", 3600, "IN", "NS", "ns1.example.com."))
        wire5 = msg5.to_wire()
        msg6 = dns.message.from_wire(wire5)
        self.assertEqual(len(msg6.answer), 2)
        self.assertEqual(str(msg6.answer[1].name), "b.example.com.")
        self.assertEqual(str(msg6.answer[1][0]), "2.2.2.2")
        self.assertEqual(str(msg6.authority[0][0]), "ns1.example.com.")


# ===========================================================================
# 12. Full DNS response round-trip
# ===========================================================================
class TestFullResponseRoundTrip(unittest.TestCase):
    """Complete DNS response with multiple sections round-trips through wire."""

    def test_full_response_roundtrip(self):
        """Response with all sections, SOA fields, and TXT content round-trips."""
        import dns.message
        import dns.rrset

        # Full response with all sections
        query = dns.message.make_query("example.com.", "A")
        response = dns.message.make_response(query)
        a_rrset = dns.rrset.from_text("example.com.", 300, "IN", "A", "93.184.216.34")
        response.answer.append(a_rrset)
        ns_rrset = dns.rrset.from_text("example.com.", 3600, "IN", "NS", "ns1.example.com.")
        response.authority.append(ns_rrset)
        glue = dns.rrset.from_text("ns1.example.com.", 3600, "IN", "A", "198.51.100.1")
        response.additional.append(glue)
        wire = response.to_wire()
        parsed = dns.message.from_wire(wire)
        self.assertEqual(len(parsed.question), 1)
        self.assertEqual(len(parsed.answer), 1)
        self.assertEqual(len(parsed.authority), 1)
        # The query used no EDNS, so make_response adds no OPT record; exactly one glue rrset was
        # appended, so the additional section round-trips to exactly one entry.
        self.assertEqual(len(parsed.additional), 1)
        self.assertEqual(str(parsed.answer[0][0]), "93.184.216.34")
        self.assertEqual(str(parsed.additional[0][0]), "198.51.100.1")

        # SOA round-trip
        query2 = dns.message.make_query("example.com.", "SOA")
        response2 = dns.message.make_response(query2)
        soa_rrset = dns.rrset.from_text(
            "example.com.", 3600, "IN", "SOA",
            "ns1.example.com. admin.example.com. 2024010101 7200 3600 1209600 86400"
        )
        response2.answer.append(soa_rrset)
        wire2 = response2.to_wire()
        parsed2 = dns.message.from_wire(wire2)
        soa = parsed2.answer[0][0]
        self.assertEqual(soa.serial, 2024010101)
        self.assertEqual(soa.refresh, 7200)

        # TXT round-trip
        query3 = dns.message.make_query("example.com.", "TXT")
        response3 = dns.message.make_response(query3)
        txt_rrset = dns.rrset.from_text("example.com.", 300, "IN", "TXT",
                                         '"v=spf1 include:example.com ~all"')
        response3.answer.append(txt_rrset)
        wire3 = response3.to_wire()
        parsed3 = dns.message.from_wire(wire3)
        self.assertEqual(parsed3.answer[0][0].strings[0],
                         b"v=spf1 include:example.com ~all")


class TestRenderer(unittest.TestCase):

    def test_renderer_builds_query_wire(self):
        """Renderer serializes the question into valid query wire format (header + question body)."""
        import dns.message
        import dns.renderer
        import dns.name
        import dns.rdatatype
        r = dns.renderer.Renderer(id=0x1234, flags=0x0100)
        qname = dns.name.from_text("example.com.")
        r.add_question(qname, dns.rdatatype.A)
        r.write_header()
        wire = r.get_wire()
        id_, flags, qd, an, ns, ar = struct.unpack("!HHHHHH", wire[:12])
        self.assertEqual(id_, 0x1234)
        self.assertEqual(flags, 0x0100)
        self.assertEqual(qd, 1)
        self.assertEqual(an, 0)
        self.assertEqual(ns, 0)
        self.assertEqual(ar, 0)
        # Parse the produced wire back and assert the question body was actually serialized — a
        # correct header over a malformed/empty question section must not pass.
        msg = dns.message.from_wire(wire)
        self.assertEqual(msg.question[0].name, dns.name.from_text("example.com."))
        self.assertEqual(msg.question[0].rdtype, dns.rdatatype.A)

    def test_renderer_response_with_answer_uses_compression(self):
        """Renderer compresses repeated names in answer section using pointers."""
        import dns.renderer
        import dns.name
        import dns.rdatatype
        import dns.rdataset
        r = dns.renderer.Renderer(id=0xABCD, flags=0x8180)
        qname = dns.name.from_text("example.com.")
        r.add_question(qname, dns.rdatatype.A)
        rds = dns.rdataset.from_text("IN", "A", 300, "192.0.2.1", "192.0.2.2")
        r.add_rdataset(dns.renderer.ANSWER, qname, rds)
        r.write_header()
        wire = r.get_wire()
        _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", wire[:12])
        self.assertEqual(qd, 1)
        self.assertEqual(an, 2)
        self.assertIn(b"\xc0\x0c", wire[12:])

    def test_renderer_max_size_raises_toobig(self):
        """Renderer raises TooBig when message exceeds max_size."""
        import dns.renderer
        import dns.name
        import dns.rdatatype
        import dns.rdataset
        import dns.exception
        r = dns.renderer.Renderer(id=0x1234, flags=0, max_size=30)
        qname = dns.name.from_text("example.com.")
        r.add_question(qname, dns.rdatatype.A)
        rds = dns.rdataset.from_text("IN", "A", 300, "192.0.2.1")
        with self.assertRaises(dns.exception.TooBig):
            r.add_rdataset(dns.renderer.ANSWER, qname, rds)

    def test_renderer_with_edns(self):
        """Renderer adds EDNS OPT record in additional section."""
        import dns.renderer
        import dns.name
        import dns.rdatatype
        import dns.message
        r = dns.renderer.Renderer(id=0x5678, flags=0x8000)
        qname = dns.name.from_text("test.example.")
        r.add_question(qname, dns.rdatatype.AAAA)
        r.add_edns(0, 0, 4096)
        r.write_header()
        wire = r.get_wire()
        _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", wire[:12])
        self.assertEqual(qd, 1)
        self.assertEqual(ar, 1)
        # The single additional record must be a well-formed OPT encoding the
        # advertised EDNS version (0) and UDP payload size (4096), not just any record.
        msg = dns.message.from_wire(wire)
        self.assertEqual(msg.edns, 0)
        self.assertEqual(msg.payload, 4096)

    def test_renderer_multi_section_response(self):
        """Renderer builds response with answer, authority, and additional sections."""
        import dns.renderer
        import dns.name
        import dns.rdatatype
        import dns.rdataset
        import dns.message
        r = dns.renderer.Renderer(id=0x9999, flags=0x8180)
        qname = dns.name.from_text("example.com.")
        r.add_question(qname, dns.rdatatype.A)
        ans_rds = dns.rdataset.from_text("IN", "A", 300, "93.184.216.34")
        r.add_rdataset(dns.renderer.ANSWER, qname, ans_rds)
        ns_name = dns.name.from_text("example.com.")
        ns_rds = dns.rdataset.from_text("IN", "NS", 3600, "ns1.example.com.")
        r.add_rdataset(dns.renderer.AUTHORITY, ns_name, ns_rds)
        glue_name = dns.name.from_text("ns1.example.com.")
        glue_rds = dns.rdataset.from_text("IN", "A", 3600, "198.51.100.1")
        r.add_rdataset(dns.renderer.ADDITIONAL, glue_name, glue_rds)
        r.write_header()
        wire = r.get_wire()
        _, _, qd, an, ns, ar = struct.unpack("!HHHHHH", wire[:12])
        self.assertEqual(qd, 1)
        self.assertEqual(an, 1)
        self.assertEqual(ns, 1)
        self.assertEqual(ar, 1)
        msg = dns.message.from_wire(wire)
        self.assertEqual(str(msg.answer[0][0]), "93.184.216.34")
        self.assertEqual(str(msg.authority[0][0]), "ns1.example.com.")


class TestSerial(unittest.TestCase):

    def test_serial_arithmetic_and_comparison(self):
        """Serial: basic comparison, wraparound, addition, int comparison."""
        import dns.serial

        # basic comparison
        self.assertTrue(dns.serial.Serial(100) < dns.serial.Serial(200))
        self.assertTrue(dns.serial.Serial(200) > dns.serial.Serial(100))
        self.assertEqual(dns.serial.Serial(100), dns.serial.Serial(100))
        self.assertNotEqual(dns.serial.Serial(100), dns.serial.Serial(200))

        # wraparound at 2^32 per RFC 1982
        s_max = dns.serial.Serial(0xFFFFFFFF)
        s_zero = dns.serial.Serial(0)
        s_one = dns.serial.Serial(1)
        self.assertTrue(s_max < s_zero)
        self.assertTrue(s_max < s_one)
        self.assertTrue(s_zero > s_max)
        self.assertTrue(s_one > s_max)

        # addition wraps modulo 2^32
        s = dns.serial.Serial(0xFFFFFFFE)
        result = s + 5
        self.assertIsInstance(result, dns.serial.Serial)
        self.assertEqual(result.value, 3)

        # comparison with int
        self.assertEqual(dns.serial.Serial(42), 42)
        self.assertTrue(dns.serial.Serial(100) < 200)
        self.assertTrue(dns.serial.Serial(100) > 50)


class TestTSIG(unittest.TestCase):

    def test_tsig_sign_verify(self):
        """TSIG sign/verify round-trip, bad key raises, no keyring raises."""
        import dns.message
        import dns.name
        import dns.tsig
        import dns.tsigkeyring

        # --- sign and verify round-trip ---
        kr = dns.tsigkeyring.from_text({"mykey.": "c2VjcmV0"})
        msg = dns.message.make_query("example.com.", "A")
        msg.use_tsig(kr, keyname=dns.name.from_text("mykey."))
        wire = msg.to_wire()
        msg2 = dns.message.from_wire(wire, keyring=kr)
        self.assertEqual(msg2.id, msg.id)
        self.assertTrue(msg2.had_tsig)

        # --- bad key raises ---
        kr_sign = dns.tsigkeyring.from_text({"mykey.": "c2VjcmV0"})
        kr_verify = dns.tsigkeyring.from_text({"mykey.": "YmFka2V5"})
        msg3 = dns.message.make_query("example.com.", "A")
        msg3.use_tsig(kr_sign, keyname=dns.name.from_text("mykey."))
        wire3 = msg3.to_wire()
        with self.assertRaises(Exception):
            dns.message.from_wire(wire3, keyring=kr_verify)

        # --- no keyring raises ---
        kr2 = dns.tsigkeyring.from_text({"mykey.": "c2VjcmV0"})
        msg4 = dns.message.make_query("example.com.", "A")
        msg4.use_tsig(kr2, keyname=dns.name.from_text("mykey."))
        wire4 = msg4.to_wire()
        with self.assertRaises(Exception):
            dns.message.from_wire(wire4)

    def test_tsig_key_and_algorithms(self):
        """TSIG key creation and algorithm constants."""
        import dns.tsig

        # --- key creation from a string algorithm (string -> Name normalization) ---
        key = dns.tsig.Key("testkey.", "c2VjcmV0", "hmac-sha256")
        self.assertEqual(str(key.name), "testkey.")
        self.assertEqual(str(key.algorithm), "hmac-sha256.")

        # --- the module algorithm constants are usable Key algorithm values ---
        # Passing the HMAC_SHA512 constant (already a Name) through the public Key
        # constructor must yield a key whose algorithm stringifies as that algorithm name.
        key512 = dns.tsig.Key("testkey.", "c2VjcmV0", dns.tsig.HMAC_SHA512)
        self.assertEqual(str(key512.algorithm), "hmac-sha512.")


class TestUpdate(unittest.TestCase):

    def test_update_section_operations(self):
        """UPDATE: opcode, zone section, add, delete, replace, present."""
        import dns.opcode
        import dns.update

        # opcode
        upd = dns.update.UpdateMessage("example.com.")
        self.assertEqual(upd.opcode(), dns.opcode.UPDATE)

        # zone section
        self.assertEqual(len(upd.zone), 1)
        self.assertEqual(str(upd.zone[0].name), "example.com.")

        # add
        upd.add("host.example.com.", 300, "A", "192.0.2.1")
        self.assertEqual(len(upd.update), 1)

        # delete
        upd2 = dns.update.UpdateMessage("example.com.")
        upd2.delete("old.example.com.", "A")
        self.assertEqual(len(upd2.update), 1)

        # replace (delete + add = 2 entries)
        upd3 = dns.update.UpdateMessage("example.com.")
        upd3.replace("www.example.com.", 300, "A", "10.0.0.1")
        self.assertEqual(len(upd3.update), 2)

        # present prerequisite
        upd4 = dns.update.UpdateMessage("example.com.")
        upd4.present("host.example.com.", "A")
        self.assertEqual(len(upd4.prerequisite), 1)

    def test_update_wire_roundtrip(self):
        """UPDATE message with add and prerequisite round-trips through wire."""
        import dns.message
        import dns.update
        upd = dns.update.UpdateMessage("example.com.")
        upd.present("host.example.com.", "A")
        upd.add("host.example.com.", 300, "A", "10.0.0.1")
        wire = upd.to_wire()
        parsed = dns.message.from_wire(wire)
        self.assertEqual(parsed.opcode(), 5)
        self.assertEqual(str(parsed.question[0].name), "example.com.")


class TestNameDict(unittest.TestCase):

    def test_namedict_operations(self):
        """NameDict: exact lookup, deepest_match, len, delete."""
        import dns.name
        import dns.namedict

        # exact lookup
        nd = dns.namedict.NameDict()
        name = dns.name.from_text("example.com.")
        nd[name] = "data"
        self.assertEqual(nd[name], "data")

        # deepest_match
        root = dns.name.from_text(".")
        com = dns.name.from_text("com.")
        nd[root] = "root"
        nd[com] = "com"
        found_name, found_data = nd.get_deepest_match(dns.name.from_text("www.example.com."))
        self.assertEqual(str(found_name), "example.com.")
        self.assertEqual(found_data, "data")
        found_name2, found_data2 = nd.get_deepest_match(dns.name.from_text("test.com."))
        self.assertEqual(str(found_name2), "com.")
        self.assertEqual(found_data2, "com")

        # len and delete
        n1 = dns.name.from_text("a.com.")
        n2 = dns.name.from_text("b.com.")
        nd2 = dns.namedict.NameDict()
        nd2[n1] = 1
        nd2[n2] = 2
        self.assertEqual(len(nd2), 2)
        del nd2[n1]
        self.assertEqual(len(nd2), 1)
        self.assertNotIn(n1, nd2)


class TestReverseName(unittest.TestCase):

    def test_reverse_name_conversion(self):
        """Reverse names: IPv4 + IPv6 + loopback conversion and round-trip."""
        import dns.reversename

        # IPv4
        rev4 = dns.reversename.from_address("192.0.2.1")
        self.assertEqual(str(rev4), "1.2.0.192.in-addr.arpa.")
        self.assertEqual(dns.reversename.to_address(rev4), "192.0.2.1")

        # IPv6
        rev6 = dns.reversename.from_address("2001:db8::1")
        self.assertEqual(str(rev6),
            "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa.")
        self.assertEqual(dns.reversename.to_address(rev6), "2001:db8::1")

        # IPv6 loopback
        rev_lo = dns.reversename.from_address("::1")
        self.assertTrue(str(rev_lo).endswith(".ip6.arpa."))
        self.assertEqual(dns.reversename.to_address(rev_lo), "::1")


# ===========================================================================
# Zone file parsing — dns.zone
# ===========================================================================
class TestZoneFileParsing(unittest.TestCase):
    """DNS zone file parsing with directives and record types."""

    def test_basic_zone_parsing(self):
        """Zone file with SOA, NS, and A records parses correctly."""
        import dns.name
        import dns.rdataclass
        import dns.rdatatype
        import dns.zone

        zone_text = (
            "$ORIGIN example.com.\n"
            "$TTL 3600\n"
            "@  IN  SOA  ns1.example.com. admin.example.com. "
            "2024010101 3600 900 604800 86400\n"
            "   IN  NS   ns1.example.com.\n"
            "   IN  NS   ns2.example.com.\n"
            "www IN  A    192.0.2.1\n"
            "mail IN A    192.0.2.2\n"
        )
        z = dns.zone.from_text(zone_text, origin="example.com.")
        self.assertEqual(str(z.origin), "example.com.")

        # SOA at apex
        apex = z[dns.name.from_text("@", None)]
        soa_rds = apex.find_rdataset(dns.rdataclass.IN, dns.rdatatype.SOA)
        soa = list(soa_rds)[0]
        self.assertEqual(soa.serial, 2024010101)
        self.assertEqual(soa.refresh, 3600)

        # NS records (targets are relative within zone context)
        ns_rds = apex.find_rdataset(dns.rdataclass.IN, dns.rdatatype.NS)
        self.assertEqual(len(list(ns_rds)), 2)

        # A records
        www_node = z[dns.name.from_text("www", None)]
        a_rds = www_node.find_rdataset(dns.rdataclass.IN, dns.rdatatype.A)
        self.assertEqual(list(a_rds)[0].address, "192.0.2.1")

        mail_node = z[dns.name.from_text("mail", None)]
        mail_a = mail_node.find_rdataset(dns.rdataclass.IN, dns.rdatatype.A)
        self.assertEqual(list(mail_a)[0].address, "192.0.2.2")

    def test_origin_directive(self):
        """$ORIGIN directive changes the default domain for subsequent records."""
        import dns.name
        import dns.rdataclass
        import dns.rdatatype
        import dns.zone

        zone_text = (
            "$ORIGIN example.com.\n"
            "$TTL 300\n"
            "@     IN  SOA  ns1 admin 2024010101 3600 900 604800 86400\n"
            "      IN  NS   ns1\n"
            "www   IN  A    192.0.2.1\n"
            "\n"
            "$ORIGIN sub.example.com.\n"
            "host1 IN  A    10.0.0.1\n"
            "host2 IN  A    10.0.0.2\n"
        )
        z = dns.zone.from_text(zone_text, origin="example.com.")

        # Names under sub-origin are relative to example.com.
        names = sorted([str(n) for n in z])
        self.assertIn("@", names)
        self.assertIn("www", names)
        self.assertIn("host1.sub", names)
        self.assertIn("host2.sub", names)

        # Verify sub-origin A records
        subnode = z.find_node(dns.name.from_text("host1.sub", None))
        a_rds = subnode.find_rdataset(dns.rdataclass.IN, dns.rdatatype.A)
        self.assertEqual(list(a_rds)[0].address, "10.0.0.1")

    def test_multiline_soa_with_parentheses(self):
        """Multi-line SOA record with parentheses parses all fields correctly."""
        import dns.name
        import dns.rdataclass
        import dns.rdatatype
        import dns.zone

        zone_text = (
            "$ORIGIN example.com.\n"
            "$TTL 3600\n"
            "@  IN  SOA  ns1.example.com. admin.example.com. (\n"
            "    2024010101  ; serial\n"
            "    3600        ; refresh\n"
            "    900         ; retry\n"
            "    604800      ; expire\n"
            "    86400       ; minimum\n"
            ")\n"
            "   IN  NS   ns1.example.com.\n"
            "www IN  A    192.0.2.1\n"
        )
        z = dns.zone.from_text(zone_text, origin="example.com.")
        apex = z[dns.name.from_text("@", None)]
        soa_rds = apex.find_rdataset(dns.rdataclass.IN, dns.rdatatype.SOA)
        soa = list(soa_rds)[0]
        self.assertEqual(soa.serial, 2024010101)
        self.assertEqual(soa.refresh, 3600)
        self.assertEqual(soa.retry, 900)
        self.assertEqual(soa.expire, 604800)
        self.assertEqual(soa.minimum, 86400)

    def test_zone_iteration_and_to_text_roundtrip(self):
        """Zone iteration visits all nodes; to_text output parses back identically."""
        import dns.zone

        zone_text = (
            "$ORIGIN example.com.\n"
            "$TTL 3600\n"
            "@  IN  SOA  ns1.example.com. admin.example.com. "
            "2024010101 3600 900 604800 86400\n"
            "   IN  NS   ns1.example.com.\n"
            "   IN  NS   ns2.example.com.\n"
            "www IN  A    192.0.2.1\n"
            "mail IN A    192.0.2.2\n"
            "mail IN MX   10 mail.example.com.\n"
        )
        z1 = dns.zone.from_text(zone_text, origin="example.com.")

        # Iteration
        node_names = sorted([str(n) for n in z1])
        self.assertIn("@", node_names)
        self.assertIn("www", node_names)
        self.assertIn("mail", node_names)
        node_count = sum(1 for _ in z1)
        self.assertEqual(node_count, 3)

        # to_text round-trip
        text_out = z1.to_text()
        text_str = text_out.decode() if isinstance(text_out, bytes) else text_out
        z2 = dns.zone.from_text(text_str, origin="example.com.")
        self.assertEqual(z1, z2)


class TestProtocolEdgeCases(unittest.TestCase):
    """Protocol-level edge cases requiring deep DNS implementation knowledge."""

    def test_name_to_text_escapification(self):
        """Name.to_text() escapes non-printable and special bytes, and round-trips via from_text()."""
        import dns.name
        n = dns.name.Name([b'\x01\x02\x03', b'example', b'com', b''])
        self.assertEqual(n.to_text(), '\\001\\002\\003.example.com.')
        self.assertEqual(dns.name.from_text(n.to_text()), n)

        n_dot = dns.name.Name([b'has.dot', b'example', b'com', b''])
        self.assertEqual(n_dot.to_text(), 'has\\.dot.example.com.')
        self.assertEqual(dns.name.from_text(n_dot.to_text()), n_dot)

        n_at = dns.name.Name([b'has@sign', b'example', b'com', b''])
        # to_text()/from_text() must round-trip a label containing '@'; whether a printable '@'
        # is itself backslash-escaped in the text form is an incidental presentation choice.
        self.assertEqual(dns.name.from_text(n_at.to_text()), n_at)

        n_hi = dns.name.Name([b'\xff', b'example', b'com', b''])
        self.assertIn('\\255', n_hi.to_text())
        self.assertEqual(dns.name.from_text(n_hi.to_text()), n_hi)

    def test_txt_wire_multi_string_encoding(self):
        """TXT wire format uses per-string length prefix, not total length."""
        import dns.rdata
        rd = dns.rdata.from_text('IN', 'TXT', '"hello" "world" "test"')
        self.assertEqual(rd.strings, (b'hello', b'world', b'test'))
        wire = rd.to_wire()
        self.assertEqual(len(wire), 17)
        self.assertEqual(wire[0], 5)
        self.assertEqual(wire[1:6], b'hello')
        self.assertEqual(wire[6], 5)
        self.assertEqual(wire[7:12], b'world')
        self.assertEqual(wire[12], 4)
        self.assertEqual(wire[13:17], b'test')
        rd2 = dns.rdata.from_wire('IN', 'TXT', wire, 0, len(wire))
        self.assertEqual(rd2.strings, (b'hello', b'world', b'test'))


if __name__ == "__main__":
    unittest.main()
