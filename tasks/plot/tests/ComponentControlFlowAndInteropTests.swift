//
// Hidden grading suite for the `plot` WRG task -- HTML Component (SwiftUI-like) layer.
//
// Exercises the `Component` protocol, the `@ComponentBuilder` result builder, component
// modifiers (class/id/style/data/directionality/accessibility), the built-in component library
// (Div, List, Table, Form, Text, ...), Node<->Component interoperability, and the environment
// propagation API. Driven entirely through the public component DSL + `render()`.
//

import XCTest
import Plot

final class ComponentControlFlowAndInteropTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// The `@ComponentBuilder` supports inline Swift control flow -- `if let`, `if/else`,
    /// `Optional.map`, `for` loops and `switch` -- and freely mixes Node- and Component-based
    /// children within one builder closure.
    func testComponentControlFlowAndInterop() {
        let string: String? = "String"
        let nilString: String? = nil
        let bool = true
        let int = 3

        let html = Div {
            if let string = string { Paragraph(string) }
            if let string = nilString { Paragraph("Should not be rendered: \(string)") }
            if let string = nilString {
                Paragraph("Should not be rendered: \(string)")
            } else {
                Paragraph("Nil")
            }
            string.map { Paragraph($0) }
            nilString.map { Paragraph($0) }
            for string in ["One", "Two"] { Paragraph(string) }
            if bool { Paragraph("True") }
            switch int {
            case 3: Paragraph("Switch")
            default: Paragraph("Should not be rendered")
            }
        }
        .render()

        XCTAssertEqual(html, """
        <div><p>String</p><p>Nil</p><p>String</p><p>One</p><p>Two</p><p>True</p><p>Switch</p></div>
        """)

        let mixed = Div {
            Node.p("One")
            Node<Any>.component(Paragraph("Two"))
            Paragraph("Three")
        }
        .render()
        XCTAssertEqual(mixed, "<div><p>One</p><p>Two</p><p>Three</p></div>")
    }
}
