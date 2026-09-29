// Hidden grading suite — choice coding via XMLChoiceCodingKey (enums with associated values).
// Public API only (`import XMLCoder`). Expected values taken from XMLCoder's own tests.

import XCTest
import Foundation
import XMLCoder

// MARK: simple scalar choices

private enum IntOrString: Equatable {
    case int(Int)
    case string(String)
}

extension IntOrString: Codable {
    enum CodingKeys: String, XMLChoiceCodingKey {
        case int
        case string
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .int(value): try container.encode(value, forKey: .int)
        case let .string(value): try container.encode(value, forKey: .string)
        }
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            self = .int(try container.decode(Int.self, forKey: .int))
        } catch {
            self = .string(try container.decode(String.self, forKey: .string))
        }
    }
}

// MARK: composite (struct-valued) choices

private struct IntWrapper: Codable, Equatable { let wrapped: Int }
private struct StringWrapper: Codable, Equatable { let wrapped: String }

private enum IntOrStringWrapper: Equatable {
    case int(IntWrapper)
    case string(StringWrapper)
}

extension IntOrStringWrapper: Codable {
    enum CodingKeys: String, XMLChoiceCodingKey {
        case int
        case string
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            self = .int(try container.decode(IntWrapper.self, forKey: .int))
        } catch {
            self = .string(try container.decode(StringWrapper.self, forKey: .string))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .int(value): try container.encode(value, forKey: .int)
        case let .string(value): try container.encode(value, forKey: .string)
        }
    }
}

// MARK: nested complex choices (element-shaped, decoded into an ordered [Entry])

private struct Run: Codable, Equatable { let id: Int; let text: String }
private struct Properties: Codable, Equatable { let id: Int; let title: String }
private struct Break: Codable, Equatable {}

private enum Entry: Equatable {
    case run(Run)
    case properties(Properties)
    case br(Break)
}

extension Entry: Codable {
    enum CodingKeys: String, XMLChoiceCodingKey { case run, properties, br }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            self = .run(try container.decode(Run.self, forKey: .run))
        } catch {
            do {
                self = .properties(try container.decode(Properties.self, forKey: .properties))
            } catch {
                self = .br(try container.decode(Break.self, forKey: .br))
            }
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .run(value): try container.encode(value, forKey: .run)
        case let .properties(value): try container.encode(value, forKey: .properties)
        case let .br(value): try container.encode(value, forKey: .br)
        }
    }
}

private struct Paragraph: Codable, Equatable {
    let entries: [Entry]
    init(entries: [Entry]) { self.entries = entries }
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        entries = try container.decode([Entry].self)
    }
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(entries)
    }
}

private struct EntryContainer: Codable, Equatable {
    let paragraphs: [Paragraph]
    enum CodingKeys: String, CodingKey { case paragraphs = "p" }
}

// MARK: nested choice array with inlined value + element-name remap (body = "chapter")

private struct InlineBook: Decodable, Equatable {
    let title: String
    let chapters: Chapters
}

private struct Chapters: Decodable, Equatable {
    let items: [Chapter]
    init(items: [Chapter]) { self.items = items }
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        items = try container.decode([Chapter].self)
    }
}

private enum Chapter: Equatable {
    struct Content: Decodable, Equatable {
        let title: String
        let content: String
        enum CodingKeys: String, CodingKey {
            case title
            case content = ""
        }
    }
    case intro(Content)
    case body(Content)
    case outro(Content)
}

extension Chapter: Decodable {
    enum CodingKeys: String, XMLChoiceCodingKey {
        case intro, body = "chapter", outro
    }
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            self = .body(try container.decode(Content.self, forKey: .body))
        } catch {
            do {
                self = .intro(try container.decode(Content.self, forKey: .intro))
            } catch {
                self = .outro(try container.decode(Content.self, forKey: .outro))
            }
        }
    }
}

// MARK: nested attribute choices (encode-only), attribute-shaped associated values

private struct AttrRun: Codable, Equatable, DynamicNodeEncoding {
    let id: Int
    let text: String
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding {
        switch key {
        case CodingKeys.id: return .attribute
        default: return .element
        }
    }
}

private struct AttrProperties: Codable, Equatable, DynamicNodeEncoding {
    let id: Int
    let title: String
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding { .attribute }
}

private struct AttrBreak: Codable, Equatable {}

private enum AttrEntry: Equatable {
    case run(AttrRun)
    case properties(AttrProperties)
    case br(AttrBreak)
}

extension AttrEntry: Codable {
    enum CodingKeys: String, XMLChoiceCodingKey { case run, properties, br }
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        do {
            self = .run(try container.decode(AttrRun.self, forKey: .run))
        } catch {
            do {
                self = .properties(try container.decode(AttrProperties.self, forKey: .properties))
            } catch {
                self = .br(try container.decode(AttrBreak.self, forKey: .br))
            }
        }
    }
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .run(value): try container.encode(value, forKey: .run)
        case let .properties(value): try container.encode(value, forKey: .properties)
        case let .br(value): try container.encode(value, forKey: .br)
        }
    }
}

private struct AttrParagraph: Codable, Equatable {
    let entries: [AttrEntry]
    init(entries: [AttrEntry]) { self.entries = entries }
    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        entries = try container.decode([AttrEntry].self)
    }
    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        try container.encode(entries)
    }
}

private struct AttrContainer: Codable, Equatable {
    let paragraphs: [AttrParagraph]
    enum CodingKeys: String, CodingKey { case paragraphs = "p" }
}

final class ChoiceCodingTests: XCTestCase {
    func testSimpleChoiceScalars() throws {
        XCTAssertEqual(try XMLDecoder().decode(IntOrString.self,
                                               from: "<container><int>42</int></container>".data(using: .utf8)!),
                       .int(42))
        XCTAssertEqual(try XMLDecoder().decode(IntOrString.self,
                                               from: "<container><string>forty-two</string></container>".data(using: .utf8)!),
                       .string("forty-two"))

        let arrayXML = """
        <container>
            <int>1</int>
            <string>two</string>
            <string>three</string>
            <int>4</int>
            <int>5</int>
        </container>
        """.data(using: .utf8)!
        let expected: [IntOrString] = [.int(1), .string("two"), .string("three"), .int(4), .int(5)]
        XCTAssertEqual(try XMLDecoder().decode([IntOrString].self, from: arrayXML), expected)

        let encoded = try XMLEncoder().encode(expected, withRootKey: "container")
        XCTAssertEqual(try XMLDecoder().decode([IntOrString].self, from: encoded), expected)
    }

    func testCompositeChoiceStructs() throws {
        let encoder = XMLEncoder()
        encoder.outputFormatting = [.prettyPrinted]

        let single = IntOrStringWrapper.string(StringWrapper(wrapped: "A Word About Woke Times"))
        let singleXML = """
        <container>
            <string>
                <wrapped>A Word About Woke Times</wrapped>
            </string>
        </container>
        """
        XCTAssertEqual(String(data: try encoder.encode(single, withRootKey: "container"), encoding: .utf8), singleXML)
        XCTAssertEqual(try XMLDecoder().decode(IntOrStringWrapper.self, from: singleXML.data(using: .utf8)!), single)

        let array: [IntOrStringWrapper] = [
            .string(StringWrapper(wrapped: "A Word About Woke Times")),
            .int(IntWrapper(wrapped: 9000)),
            .string(StringWrapper(wrapped: "A Word About Woke Tomes")),
        ]
        let arrayXML = """
        <container>
            <string>
                <wrapped>A Word About Woke Times</wrapped>
            </string>
            <int>
                <wrapped>9000</wrapped>
            </int>
            <string>
                <wrapped>A Word About Woke Tomes</wrapped>
            </string>
        </container>
        """
        XCTAssertEqual(String(data: try encoder.encode(array, withRootKey: "container"), encoding: .utf8), arrayXML)
        XCTAssertEqual(try XMLDecoder().decode([IntOrStringWrapper].self, from: arrayXML.data(using: .utf8)!), array)
    }

    func testNestedComplexChoiceOrdering() throws {
        let xml = """
        <container>
            <p>
                <run><id>1518</id><text>Hello</text></run>
                <br></br>
                <properties><id>431</id><title>A Word</title></properties>
            </p>
        </container>
        """.data(using: .utf8)!
        let expected = EntryContainer(paragraphs: [
            Paragraph(entries: [
                .run(Run(id: 1518, text: "Hello")),
                .br(Break()),
                .properties(Properties(id: 431, title: "A Word")),
            ]),
        ])
        let decoded = try XMLDecoder().decode(EntryContainer.self, from: xml)
        XCTAssertEqual(decoded, expected)

        // Round-trip: encoding then decoding preserves the choice order.
        let reencoded = try XMLEncoder().encode(decoded, withRootKey: "container")
        XCTAssertEqual(try XMLDecoder().decode(EntryContainer.self, from: reencoded), expected)
    }

    func testNestedChoiceArrayInlined() throws {
        let xml = """
        <?xml version="1.0" encoding="UTF-8"?>
        <book title="Example">
            <chapters>
                <intro title="Intro">Content of first chapter</intro>
                <chapter title="Chapter 1">Content of chapter 1</chapter>
                <chapter title="Chapter 2">Content of chapter 2</chapter>
                <outro title="Epilogue">Content of last chapter</outro>
            </chapters>
        </book>
        """.data(using: .utf8)!
        let expected = InlineBook(title: "Example", chapters: Chapters(items: [
            .intro(.init(title: "Intro", content: "Content of first chapter")),
            .body(.init(title: "Chapter 1", content: "Content of chapter 1")),
            .body(.init(title: "Chapter 2", content: "Content of chapter 2")),
            .outro(.init(title: "Epilogue", content: "Content of last chapter")),
        ]))
        XCTAssertEqual(try XMLDecoder().decode(InlineBook.self, from: xml), expected)
    }

    func testNestedAttributeChoiceEncode() throws {
        let encoder = XMLEncoder()
        encoder.outputFormatting = [.prettyPrinted]
        let value = AttrContainer(paragraphs: [
            AttrParagraph(entries: [
                .br(AttrBreak()),
                .run(AttrRun(id: 1518, text: "I am answering it again.")),
                .properties(AttrProperties(id: 431, title: "A Word About Wake Times")),
            ]),
            AttrParagraph(entries: [
                .run(AttrRun(id: 1519, text: "I am answering it again.")),
                .br(AttrBreak()),
            ]),
        ])
        let encoded = try encoder.encode(value, withRootKey: "container")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), """
        <container>
            <p>
                <br />
                <run id="1518">
                    <text>I am answering it again.</text>
                </run>
                <properties id="431" title="A Word About Wake Times" />
            </p>
            <p>
                <run id="1519">
                    <text>I am answering it again.</text>
                </run>
                <br />
            </p>
        </container>
        """)
    }
}
