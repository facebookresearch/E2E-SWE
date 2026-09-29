// Hidden grading suite — decoder parsing options: namespaces, whitespace handling, mixed
// element/text content, empty-element/empty-string, error context.
// Public API only (`import XMLCoder`). Expected values taken from XMLCoder's own tests.

import XCTest
import Foundation
import XMLCoder

private struct Table: Codable, Equatable {
    struct TR: Codable, Equatable { let td: [String] }
    let tr: [TR]
}

private struct NamespacedTable: Codable, Equatable {
    struct TR: Codable, Equatable {
        let td: [String]
        enum CodingKeys: String, CodingKey { case td = "h:td" }
    }
    let tr: [TR]
    enum CodingKeys: String, CodingKey { case tr = "h:tr" }
}

private enum TextItem: Codable, Equatable {
    case bold(String)
    case text(String)

    enum CodingKeys: String, XMLChoiceCodingKey {
        case bold = "b"
        case text = ""
    }
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        switch self {
        case let .text(text): try container.encode(text, forKey: .text)
        case let .bold(text): try container.encode(text, forKey: .bold)
        }
    }
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let key = container.allKeys.first!
        switch key {
        case .bold: self = .bold(try container.decode(String.self, forKey: .bold))
        case .text: self = .text(try container.decode(String.self, forKey: .text))
        }
    }
}

private struct Thing: Equatable, Codable {
    let attribute: String?
    let value: String
    enum CodingKeys: String, CodingKey {
        case attribute
        case value = ""
    }
}
private struct Parent: Equatable, Codable {
    let thing: Thing
}

private struct DictContainer: Codable {
    let value: [String: Int]
}

final class ParsingOptionTests: XCTestCase {
    private let tableXML = """
    <h:table xmlns:h="http://www.w3.org/TR/html4/">
      <h:tr>
        <h:td>Apples</h:td>
        <h:td>Bananas</h:td>
      </h:tr>
    </h:table>
    """.data(using: .utf8)!

    func testNamespaceProcessing() throws {
        let decoder = XMLDecoder()

        decoder.shouldProcessNamespaces = true
        XCTAssertEqual(try decoder.decode(Table.self, from: tableXML), Table(tr: [.init(td: ["Apples", "Bananas"])]))
        XCTAssertEqual(try decoder.decode(NamespacedTable.self, from: tableXML), NamespacedTable(tr: []))

        decoder.shouldProcessNamespaces = false
        XCTAssertEqual(try decoder.decode(Table.self, from: tableXML), Table(tr: []))
        XCTAssertEqual(try decoder.decode(NamespacedTable.self, from: tableXML),
                       NamespacedTable(tr: [.init(td: ["Apples", "Bananas"])]))
    }

    func testWhitespaceOptions() throws {
        let trimming = XMLDecoder()
        XCTAssertEqual(try trimming.decode(String.self, from: "<t>Stilles Örtchen</t>".data(using: .utf8)!), "Stilles Örtchen")
        XCTAssertTrue(try trimming.decode(String.self, from: "<t xml:space=\"preserve\"> </t>".data(using: .utf8)!).isEmpty)

        let preserving = XMLDecoder(trimValueWhitespaces: false)
        XCTAssertEqual(try preserving.decode(String.self, from: "<t>     Stilles Örtchen    </t>".data(using: .utf8)!),
                       "     Stilles Örtchen    ")
        XCTAssertEqual(try preserving.decode(String.self, from: "<t>Copyright © 2019 Company, Inc.</t>".data(using: .utf8)!),
                       "Copyright © 2019 Company, Inc.")
        XCTAssertEqual(try preserving.decode(String.self, from: "<t>one &amp; two</t>".data(using: .utf8)!), "one & two")
        XCTAssertEqual(try preserving.decode(String.self, from: "<t xml:space=\"preserve\"> </t>".data(using: .utf8)!), " ")
    }

    func testMixedContent() throws {
        let xmlString = "<container>first<b>bold text</b>second</container>"
        let decoded = try XMLDecoder().decode([TextItem].self, from: xmlString.data(using: .utf8)!)
        XCTAssertEqual(decoded, [.text("first"), .bold("bold text"), .text("second")])

        let encoded = try XMLEncoder().encode(decoded, withRootKey: "container")
        XCTAssertEqual(String(data: encoded, encoding: .utf8), xmlString)
    }

    func testEmptyElementEmptyString() throws {
        XCTAssertEqual(try XMLDecoder().decode(Thing.self, from: "<thing></thing>".data(using: .utf8)!),
                       Thing(attribute: nil, value: ""))
        XCTAssertEqual(try XMLDecoder().decode(Thing.self, from: "<thing attribute=\"x\"></thing>".data(using: .utf8)!),
                       Thing(attribute: "x", value: ""))

        let arrayXML = """
        <container>
            <thing></thing>
            <thing attribute="x">Non-Empty!</thing>
            <thing>Non-Empty!</thing>
        </container>
        """.data(using: .utf8)!
        XCTAssertEqual(try XMLDecoder().decode([Thing].self, from: arrayXML), [
            Thing(attribute: nil, value: ""),
            Thing(attribute: "x", value: "Non-Empty!"),
            Thing(attribute: nil, value: "Non-Empty!"),
        ])

        let nested = "<parent><thing/></parent>".data(using: .utf8)!
        XCTAssertEqual(try XMLDecoder().decode(Parent.self, from: nested),
                       Parent(thing: Thing(attribute: nil, value: "")))
    }

    func testErrorContextLength() throws {
        let malformed = """
        container>
            test1
        </blah>
        <container>
            test2
        </container>
        """.data(using: .utf8)!

        let withContext = XMLDecoder()
        withContext.errorContextLength = 10
        XCTAssertThrowsError(try withContext.decode(DictContainer.self, from: malformed)) { error in
            guard case let DecodingError.dataCorrupted(ctx) = error, ctx.underlyingError != nil else {
                XCTFail("expected DecodingError.dataCorrupted with an underlying error, got \(error)")
                return
            }
            // The exact windowing of the context slice is a repo-internal detail; assert the
            // documented shape instead — a "line L, column C:" locator followed by a back-quoted
            // slice no longer than errorContextLength (10) — not the exact substring.
            let desc = ctx.debugDescription
            guard let marker = desc.range(of: "at line 1, column 1:\n`"), desc.hasSuffix("`") else {
                XCTFail("unexpected debugDescription: \(desc)")
                return
            }
            let slice = desc[marker.upperBound...].dropLast()
            XCTAssertFalse(slice.isEmpty, "expected a non-empty context slice: \(desc)")
            XCTAssertLessThanOrEqual(slice.count, 10, "slice exceeds errorContextLength: \(desc)")
            // The slice must be source text taken at the error location. The error is at line 1,
            // column 1, so a window clamped to available content can only start at the document's
            // first character — whatever window length the implementation picks.
            XCTAssertTrue(String(decoding: malformed, as: UTF8.self).hasPrefix(String(slice)),
                          "context slice must be source text at the error location: \(desc)")
        }

        // With the default errorContextLength (0) parsing still fails, just without the context slice.
        XCTAssertThrowsError(try XMLDecoder().decode(DictContainer.self, from: malformed))
    }
}
