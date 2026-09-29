//
// Hidden grading suite for the `plot` WRG task -- free-form XML layer.
//
// Exercises the `XML` document format: the XML declaration prefix and the generic element /
// attribute / nesting / self-closing DSL that all XML-based formats are built on.
//

import XCTest
import Plot

final class XMLDocumentRenderingTests: XCTestCase {
    private let decl = #"<?xml version="1.0" encoding="UTF-8"?>"#

    /// An XML document renders the standard declaration followed by its free-form element tree:
    /// text-bearing elements, self-closing elements, attributes, and nested children.
    func testXMLDocumentRendering() {
        XCTAssertEqual(XML().render(), decl)

        XCTAssertEqual(
            XML(.element(named: "hello", text: "world!")).render(),
            decl + "<hello>world!</hello>"
        )

        XCTAssertEqual(
            XML(.selfClosedElement(named: "element")).render(),
            decl + "<element/>"
        )

        XCTAssertEqual(
            XML(.element(named: "element", nodes: [.attribute(named: "attribute", value: "value")])).render(),
            decl + #"<element attribute="value"></element>"#
        )

        XCTAssertEqual(
            XML(.element(named: "parent", nodes: [
                .selfClosedElement(named: "a"),
                .selfClosedElement(named: "b")
            ])).render(),
            decl + "<parent><a/><b/></parent>"
        )
    }
}
