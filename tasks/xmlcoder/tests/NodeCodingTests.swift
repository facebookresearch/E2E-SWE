// Hidden grading suite — node coding: DynamicNodeEncoding/Decoding, property wrappers,
// intrinsic value keys with attributes, root-level attributes.
// Public API only (`import XMLCoder`). Expected values taken from XMLCoder's own tests.

import XCTest
import Foundation
import XMLCoder

// MARK: DynamicNodeEncoding library model

private struct Library: Codable, Equatable {
    let count: Int
    let books: [Book]
    private enum CodingKeys: String, CodingKey {
        case count
        case books = "book"
    }
}

private struct Book: Codable, Equatable, DynamicNodeEncoding {
    let id: UInt
    let author: String
    let gender: String
    let title: String
    let categories: [Category]

    enum CodingKeys: String, CodingKey {
        case id, author, gender, title
        case categories = "category"
    }

    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding {
        switch key {
        case Book.CodingKeys.id, Book.CodingKeys.author, Book.CodingKeys.gender: return .both
        default: return .element
        }
    }
}

private struct Category: Codable, Equatable, DynamicNodeEncoding {
    let main: Bool
    let value: String
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding {
        switch key {
        case Category.CodingKeys.main: return .attribute
        default: return .element
        }
    }
    private enum CodingKeys: String, CodingKey { case main, value }
}

// MARK: DynamicNodeDecoding matrix models

private struct NestedElement: Codable, Equatable, DynamicNodeDecoding {
    let field1: String
    let field2: String
    static func nodeDecoding(for key: CodingKey) -> XMLDecoder.NodeDecoding { .element }
}

private struct NestedAttribute: Codable, Equatable, DynamicNodeDecoding {
    let field1: String
    let field2: String
    static func nodeDecoding(for key: CodingKey) -> XMLDecoder.NodeDecoding { .attribute }
}

private struct NestedEither: Codable, Equatable, DynamicNodeDecoding {
    let field1: String
    let field2: String
    static func nodeDecoding(for key: CodingKey) -> XMLDecoder.NodeDecoding { .elementOrAttribute }
}

// MARK: property wrappers

private struct WrappedBook: Codable, Equatable {
    @Attribute var id: Int
    @Element var name: String
    @ElementAndAttribute var authorID: Int
    init(id: Int, name: String, authorID: Int) {
        _id = Attribute(id)
        _name = Element(name)
        _authorID = ElementAndAttribute(authorID)
    }
}

// MARK: intrinsic value + attribute

private struct Foo: Codable, Equatable {
    @Attribute var id: String
    var value: String
    enum CodingKeys: String, CodingKey {
        case id
        case value = ""
    }
    init(id: String, value: String) { _id = Attribute(id); self.value = value }
}

private struct FooContainer: Codable, Equatable {
    let foo: [Foo]
}

// MARK: root-level attribute

private struct Policy: Encodable, DynamicNodeEncoding {
    var name: String
    var initial: String
    enum CodingKeys: String, CodingKey { case name, initial }
    static func nodeEncoding(for key: CodingKey) -> XMLEncoder.NodeEncoding {
        switch key {
        case Policy.CodingKeys.name: return .attribute
        default: return .element
        }
    }
}

final class NodeCodingTests: XCTestCase {
    private let libraryXMLTrueFalse = """
    <?xml version="1.0" encoding="UTF-8"?>
    <library>
        <count>2</count>
        <book id="123" author="Jack" gender="novel">
            <id>123</id>
            <author>Jack</author>
            <gender>novel</gender>
            <title>Cat in the Hat</title>
            <category main="true">
                <value>Kids</value>
            </category>
            <category main="false">
                <value>Wildlife</value>
            </category>
        </book>
        <book id="456" author="Susan" gender="fantastic">
            <id>456</id>
            <author>Susan</author>
            <gender>fantastic</gender>
            <title>1984</title>
            <category main="true">
                <value>Classics</value>
            </category>
            <category main="false">
                <value>News</value>
            </category>
        </book>
    </library>
    """

    private let library = Library(count: 2, books: [
        Book(id: 123, author: "Jack", gender: "novel", title: "Cat in the Hat",
             categories: [Category(main: true, value: "Kids"), Category(main: false, value: "Wildlife")]),
        Book(id: 456, author: "Susan", gender: "fantastic", title: "1984",
             categories: [Category(main: true, value: "Classics"), Category(main: false, value: "News")]),
    ])

    func testDynamicNodeEncodingBoth() throws {
        let encoder = XMLEncoder()
        encoder.outputFormatting = [.prettyPrinted]
        let encoded = try encoder.encode(library, withRootKey: "library",
                                         header: XMLHeader(version: 1.0, encoding: "UTF-8"))
        XCTAssertEqual(String(data: encoded, encoding: .utf8), libraryXMLTrueFalse)

        let decoded = try XMLDecoder().decode(Library.self, from: libraryXMLTrueFalse.data(using: .utf8)!)
        XCTAssertEqual(decoded, library)
    }

    func testDynamicNodeDecodingMatrix() throws {
        let bothElements = "<nested><field1>a</field1><field2>b</field2></nested>".data(using: .utf8)!
        let bothAttributes = "<nested field1=\"a\" field2=\"b\" />".data(using: .utf8)!

        // Element-shaped input.
        XCTAssertEqual(try XMLDecoder().decode(NestedElement.self, from: bothElements),
                       NestedElement(field1: "a", field2: "b"))
        assertKeyNotFound(try XMLDecoder().decode(NestedAttribute.self, from: bothElements))
        XCTAssertEqual(try XMLDecoder().decode(NestedEither.self, from: bothElements),
                       NestedEither(field1: "a", field2: "b"))

        // Attribute-shaped input.
        assertKeyNotFound(try XMLDecoder().decode(NestedElement.self, from: bothAttributes))
        XCTAssertEqual(try XMLDecoder().decode(NestedAttribute.self, from: bothAttributes),
                       NestedAttribute(field1: "a", field2: "b"))
        XCTAssertEqual(try XMLDecoder().decode(NestedEither.self, from: bothAttributes),
                       NestedEither(field1: "a", field2: "b"))
    }

    func testPropertyWrappers() throws {
        let book = WrappedBook(id: 42, name: "The Book", authorID: 24)
        let encoder = XMLEncoder()
        encoder.outputFormatting = .prettyPrinted
        XCTAssertEqual(String(data: try encoder.encode(book, withRootKey: "Book"), encoding: .utf8), """
        <Book id="42" authorID="24">
            <name>The Book</name>
            <authorID>24</authorID>
        </Book>
        """)

        let both = "<Book id=\"42\" authorID=\"24\"><name>The Book</name><authorID>24</authorID></Book>".data(using: .utf8)!
        let element = "<Book id=\"42\"><authorID>24</authorID><name>The Book</name></Book>".data(using: .utf8)!
        let attribute = "<Book id=\"42\" authorID=\"24\"><name>The Book</name></Book>".data(using: .utf8)!
        XCTAssertEqual(try XMLDecoder().decode(WrappedBook.self, from: both), book)
        XCTAssertEqual(try XMLDecoder().decode(WrappedBook.self, from: element), book)
        XCTAssertEqual(try XMLDecoder().decode(WrappedBook.self, from: attribute), book)
    }

    func testIntrinsicValueWithAttribute() throws {
        let decoded = try XMLDecoder().decode(Foo.self, from: "<foo id=\"123\">456</foo>".data(using: .utf8)!)
        XCTAssertEqual(decoded, Foo(id: "123", value: "456"))

        let encoder = XMLEncoder()
        let encoded = try encoder.encode(Foo(id: "123", value: "456"), withRootKey: "foo",
                                         header: XMLHeader(version: 1.0, encoding: "UTF-8"))
        XCTAssertEqual(String(data: encoded, encoding: .utf8),
                       "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<foo id=\"123\">456</foo>")

        let arrayXML = "<container><foo id=\"123\">456</foo><foo id=\"789\">123</foo></container>".data(using: .utf8)!
        XCTAssertEqual(try XMLDecoder().decode(FooContainer.self, from: arrayXML),
                       FooContainer(foo: [Foo(id: "123", value: "456"), Foo(id: "789", value: "123")]))
    }

    func testRootLevelAttribute() throws {
        let encoder = XMLEncoder()
        encoder.outputFormatting = [.prettyPrinted]
        let data = try encoder.encode(Policy(name: "generic", initial: "more xml here"),
                                      withRootKey: "policy",
                                      header: XMLHeader(version: 1.0, encoding: "UTF-8"))
        XCTAssertEqual(String(data: data, encoding: .utf8), """
        <?xml version="1.0" encoding="UTF-8"?>
        <policy name="generic">
            <initial>more xml here</initial>
        </policy>
        """)
    }

    private func assertKeyNotFound<T>(_ expression: @autoclosure () throws -> T,
                                      file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertThrowsError(try expression(), file: file, line: line) { error in
            guard case DecodingError.keyNotFound = error else {
                XCTFail("expected DecodingError.keyNotFound, got \(error)", file: file, line: line)
                return
            }
        }
    }
}
