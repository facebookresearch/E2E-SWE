// Hidden grading suite — core Codable round-trips through XMLEncoder / XMLDecoder.
// Public API only (`import XMLCoder`). Expected values taken from XMLCoder's own tests.

import XCTest
import Foundation
import XMLCoder

private struct Scalars: Codable, Equatable {
    let blob: Data
    let count: Int
    let flag: Bool
    let link: URL
    let name: String
    let ratio: Double
}

private struct IntBox: Codable, Equatable { let value: Int }
private struct OptionalIntBox: Codable, Equatable { let value: Int? }
private struct DictBox: Codable, Equatable { let value: [String: Int] }
private struct StringArrayBox: Codable, Equatable { let value: [String] }
private struct NestedNilBox: Codable, Equatable { let value: [String?] }

private struct Empty: Codable, Equatable {}
private struct EmptyArrayBox: Codable, Equatable {
    let empties: [Empty]
    enum CodingKeys: String, CodingKey { case empties = "empty" }
}

private struct ProudParent: Codable, Equatable {
    var myChildAge: [Int]
}

private class A: Codable {
    let x: String
    init(x: String) { self.x = x }
}

private class B: A {
    let y: Double
    private enum CodingKeys: CodingKey { case y }
    init(x: String, y: Double) { self.y = y; super.init(x: x) }
    required init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        y = try container.decode(Double.self, forKey: .y)
        let superDecoder = try container.superDecoder()
        try super.init(from: superDecoder)
    }
    override func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(y, forKey: .y)
        let superEncoder = container.superEncoder()
        try super.encode(to: superEncoder)
    }
}

private class C: B {
    let z: Int
    private enum CodingKeys: CodingKey { case z }
    init(x: String, y: Double, z: Int) { self.z = z; super.init(x: x, y: y) }
    required init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        z = try container.decode(Int.self, forKey: .z)
        let superDecoder = try container.superDecoder()
        try super.init(from: superDecoder)
    }
    override func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(z, forKey: .z)
        let superEncoder = container.superEncoder()
        try super.encode(to: superEncoder)
    }
}

private struct S: Codable {
    let a: A
    let b: B
    let c: C
}

private struct Note: Codable, Equatable {
    var to: String
    var from: String
    var heading: String
    var body: String
}

private struct FooValue: Codable, Equatable {
    let value: Int
    enum CodingKeys: String, CodingKey { case value = "" }
}

final class CoreCodingTests: XCTestCase {
    private let scalars = Scalars(
        blob: Data(base64Encoded: "bG9yZW0gaXBzdW0=")!,
        count: 3,
        flag: true,
        link: URL(string: "http://example.com")!,
        name: "hello",
        ratio: 1.5
    )

    func testScalarElementRoundTrip() throws {
        let encoder = XMLEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let encoded = try encoder.encode(scalars, withRootKey: "Scalars")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), """
        <Scalars>
            <blob>bG9yZW0gaXBzdW0=</blob>
            <count>3</count>
            <flag>true</flag>
            <link>http://example.com</link>
            <name>hello</name>
            <ratio>1.5</ratio>
        </Scalars>
        """)
        XCTAssertEqual(try XMLDecoder().decode(Scalars.self, from: encoded), scalars)
    }

    func testScalarAttributeForm() throws {
        let encoder = XMLEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.nodeEncodingStrategy = .custom { _, _ in { _ in .attribute } }
        let encoded = try encoder.encode(scalars, withRootKey: "Scalars")
        XCTAssertEqual(String(data: encoded, encoding: .utf8),
                       "<Scalars blob=\"bG9yZW0gaXBzdW0=\" count=\"3\" flag=\"true\" link=\"http://example.com\" name=\"hello\" ratio=\"1.5\" />")
        XCTAssertEqual(try XMLDecoder().decode(Scalars.self, from: encoded), scalars)
    }

    func testMissingRequiredAndOptionalNil() throws {
        let empty = "<container />".data(using: .utf8)!
        XCTAssertThrowsError(try XMLDecoder().decode(IntBox.self, from: empty))

        let optional = try XMLDecoder().decode(OptionalIntBox.self, from: empty)
        XCTAssertEqual(optional, OptionalIntBox(value: nil))

        let encoder = XMLEncoder()
        let reencoded = try encoder.encode(OptionalIntBox(value: nil), withRootKey: "container")
        XCTAssertEqual(String(data: reencoded, encoding: .utf8), "<container />")
    }

    func testKeyedDictionary() throws {
        let emptyDict = try XMLDecoder().decode(DictBox.self, from: "<container />".data(using: .utf8)!)
        XCTAssertEqual(emptyDict, DictBox(value: [:]))

        let xml = "<container><value><foo>12</foo><bar>34</bar></value></container>".data(using: .utf8)!
        let decoded = try XMLDecoder().decode(DictBox.self, from: xml)
        XCTAssertEqual(decoded, DictBox(value: ["foo": 12, "bar": 34]))

        let encoder = XMLEncoder()
        encoder.outputFormatting = [.sortedKeys]
        let encoded = try encoder.encode(DictBox(value: ["foo": 12, "bar": 34]), withRootKey: "container")
        XCTAssertEqual(String(data: encoded, encoding: .utf8),
                       "<container><value><bar>34</bar><foo>12</foo></value></container>")
    }

    func testUnkeyedArrayAndNils() throws {
        let empty = try XMLDecoder().decode(StringArrayBox.self, from: "<container />".data(using: .utf8)!)
        XCTAssertEqual(empty, StringArrayBox(value: []))

        let two = try XMLDecoder().decode(StringArrayBox.self,
                                          from: "<container><value>foo</value><value>bar</value></container>".data(using: .utf8)!)
        XCTAssertEqual(two, StringArrayBox(value: ["foo", "bar"]))

        let nested = try XMLDecoder().decode(NestedNilBox.self,
                                             from: "<container><value>test1</value><value/><value>test2</value></container>".data(using: .utf8)!)
        XCTAssertEqual(nested, NestedNilBox(value: ["test1", "", "test2"]))
    }

    func testEmptyElementsAndSingleChild() throws {
        let encoder = XMLEncoder()
        XCTAssertEqual(String(data: try encoder.encode(Empty(), withRootKey: "container"), encoding: .utf8),
                       "<container />")

        let threeEmpties = "<container><empty/><empty/><empty/></container>".data(using: .utf8)!
        XCTAssertEqual(try XMLDecoder().decode([Empty].self, from: threeEmpties), [Empty(), Empty(), Empty()])
        XCTAssertEqual(try XMLDecoder().decode(EmptyArrayBox.self, from: threeEmpties),
                       EmptyArrayBox(empties: [Empty(), Empty(), Empty()]))

        let parent = ProudParent(myChildAge: [2])
        let encoded = try encoder.encode(parent, withRootKey: "ProudParent")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), "<ProudParent><myChildAge>2</myChildAge></ProudParent>")
        XCTAssertEqual(try XMLDecoder().decode(ProudParent.self, from: encoded), parent)
    }

    func testClassInheritanceSuperEncoder() throws {
        let xmlData = """
        <s>
            <a>
                <x>test_string</x>
            </a>
            <b>
                <y>4.2</y>
                <super>
                    <x>test_string</x>
                </super>
            </b>
            <c>
                <z>42</z>
                <super>
                    <y>4.2</y>
                    <super>
                        <x>test_string</x>
                    </super>
                </super>
            </c>
        </s>
        """.data(using: .utf8)!

        let decoded = try XMLDecoder().decode(S.self, from: xmlData)
        XCTAssertEqual(decoded.a.x, "test_string")
        XCTAssertEqual(decoded.b.x, "test_string")
        XCTAssertEqual(decoded.b.y, 4.2)
        XCTAssertEqual(decoded.c.z, 42)
        XCTAssertEqual(decoded.c.x, "test_string")
        XCTAssertEqual(decoded.c.y, 4.2)

        let encoder = XMLEncoder()
        encoder.outputFormatting = [.prettyPrinted]
        XCTAssertEqual(try encoder.encode(decoded, withRootKey: "s"), xmlData)
    }

    func testEndToEndNoteRoundTrip() throws {
        let validXml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <note>
            <to>Tove</to>
            <from>Jani</from>
            <heading>Reminder</heading>
            <body>Don't forget me this weekend!</body>
        </note>
        """.data(using: .utf8)!

        let note1 = try XMLDecoder().decode(Note.self, from: validXml)
        XCTAssertEqual(note1, Note(to: "Tove", from: "Jani", heading: "Reminder", body: "Don't forget me this weekend!"))

        let data = try XMLEncoder().encode(note1, withRootKey: "note",
                                           header: XMLHeader(version: 1.0, encoding: "UTF-8"))
        XCTAssertEqual(try XMLDecoder().decode(Note.self, from: data), note1)

        let invalidXml = """
        <note><to>Tove</to><from>Jani</Ffrom></note>
        """.data(using: .utf8)!
        XCTAssertThrowsError(try XMLDecoder().decode(Note.self, from: invalidXml))
    }

    func testIntrinsicValueKey() throws {
        let decoded = try XMLDecoder().decode(FooValue.self, from: "<foo>456</foo>".data(using: .utf8)!)
        XCTAssertEqual(decoded, FooValue(value: 456))
    }
}
