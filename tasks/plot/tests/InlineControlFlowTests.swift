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

final class InlineControlFlowTests: XCTestCase {
    /// The inline control-flow commands: conditional `.if` (with optional `else`), optional
    /// unwrapping `.unwrap` (with optional `else`), and `.forEach` over a sequence.
    func testInlineControlFlow() {
        XCTAssertEqual(Node<Any>.if(true, .text("True")).render(), "True")
        XCTAssertEqual(Node<Any>.if(false, .text("True")).render(), "")
        XCTAssertEqual(Node<Any>.if(true, .text("If"), else: .text("Else")).render(), "If")
        XCTAssertEqual(Node<Any>.if(false, .text("If"), else: .text("Else")).render(), "Else")

        var optional: String? = "Hello"
        XCTAssertEqual(Node<Any>.unwrap(optional, Node.text).render(), "Hello")
        optional = nil
        XCTAssertEqual(Node<Any>.unwrap(optional, Node.text).render(), "")
        XCTAssertEqual(Node<Any>.unwrap(optional, Node.text, else: .text("Is nil")).render(), "Is nil")

        XCTAssertEqual(Node<Any>.forEach(["A", "B", "C"], Node.text).render(), "ABC")
        XCTAssertEqual(Node<Any>.forEach([], Node.text).render(), "")
    }
}
