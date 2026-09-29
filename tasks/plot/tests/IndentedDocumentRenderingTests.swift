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

final class IndentedDocumentRenderingTests: XCTestCase {
    /// A document rendered with indentation nests each level of elements, self-closing tags, text
    /// and inlined components by the requested amount of spaces or tabs.
    func testIndentedDocumentRendering() {
        let document = Document.custom(
            withFormat: FormatStub.self,
            elements: [
                .named("one", nodes: [
                    .element(named: "two", nodes: [.selfClosedElement(named: "three")]),
                    .text("four "),
                    .component(Text("five")),
                    .component(Element.named("six", nodes: [.text("seven")])),
                    .element(named: "eight", nodes: [.text("nine")])
                ]),
                .selfClosed(named: "ten", attributes: [Attribute(name: "key", value: "value")])
            ]
        )

        XCTAssertEqual(document.render(indentedBy: .spaces(4)), """
        <one>
            <two>
                <three/>
            </two>four five
            <six>seven</six>
            <eight>nine</eight>
        </one>
        <ten key="value"/>
        """)

        let tabbed = Document.custom(
            withFormat: FormatStub.self,
            elements: [
                .named("one", nodes: [
                    .element(named: "two", nodes: [.selfClosedElement(named: "three")]),
                    .element(named: "four")
                ]),
                .selfClosed(named: "five", attributes: [Attribute(name: "key", value: "value")])
            ]
        )

        XCTAssertEqual(tabbed.render(indentedBy: .tabs(1)), """
        <one>
        \t<two>
        \t\t<three/>
        \t</two>
        \t<four></four>
        </one>
        <five key="value"/>
        """)
    }
}

// MARK: - Helpers

private struct FormatStub: DocumentFormat {
    enum RootContext {}
}
