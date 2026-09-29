//
// Hidden grading suite for the `plot` WRG task -- core rendering engine layer.
//
// Exercises the low-level building blocks that every document format is built on, through the
// public `Node`/`Element`/`Attribute`/`Document` DSL: text escaping (and its no-double-escape
// rule), raw text, custom elements/attributes, node groups, the inline control-flow commands
// (`.if`/`.unwrap`/`.forEach`), and recursive indentation of a rendered document.
//

import XCTest
import Plot

final class CustomNodesGroupsAndComponentsTests: XCTestCase {
    /// Custom elements and attributes and node groups: named elements (empty, self-closed, with
    /// attributes), groups, and inline component groups.
    func testCustomNodesGroupsAndComponents() {
        XCTAssertEqual(Node<Any>.group(.text("Hello"), .text("World")).render(), "HelloWorld")
        XCTAssertEqual(Node<Any>.element(named: "custom").render(), "<custom></custom>")
        XCTAssertEqual(
            Node<Any>.element(named: "custom", attributes: [Attribute(name: "key", value: "value")]).render(),
            #"<custom key="value"></custom>"#
        )
        XCTAssertEqual(
            Node<Any>.selfClosedElement(named: "custom", attributes: [Attribute(name: "key", value: "value")]).render(),
            #"<custom key="value"/>"#
        )
        XCTAssertEqual(
            Node<Any>.components { Paragraph("One"); Paragraph("Two") }.render(),
            "<p>One</p><p>Two</p>"
        )
    }
}
