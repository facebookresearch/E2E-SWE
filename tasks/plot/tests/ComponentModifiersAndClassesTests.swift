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

final class ComponentModifiersAndClassesTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Component modifiers: id/class chaining (classes append by default, empty ones skipped,
    /// `replaceExisting` swaps), class application through wrapping components / groups / nodes,
    /// and the directionality / style / data / accessibility modifiers.
    func testComponentModifiersAndClasses() {
        XCTAssertEqual(
            Link("Swift by Sundell", url: "https://swiftbysundell.com").id("sxs-link").class("link").render(),
            #"<a href="https://swiftbysundell.com" id="sxs-link" class="link">Swift by Sundell</a>"#
        )

        XCTAssertEqual(
            Paragraph("Hello").class("one").class("two").class("three").render(),
            #"<p class="one two three">Hello</p>"#
        )
        XCTAssertEqual(
            Paragraph("Hello").class("").class("one").class("").class("two").render(),
            #"<p class="one two">Hello</p>"#
        )
        XCTAssertEqual(
            Paragraph("Hello").class("one").class("two").class("three", replaceExisting: true).render(),
            #"<p class="three">Hello</p>"#
        )

        struct InnerWrapper: Component {
            var body: Component { Paragraph("Hello").class("one") }
        }
        struct OuterWrapper: Component {
            var body: Component { InnerWrapper().class("two") }
        }
        XCTAssertEqual(OuterWrapper().class("three").render(), #"<p class="one two three">Hello</p>"#)

        struct GroupWrapper: Component {
            var body: Component {
                ComponentGroup { Paragraph("One"); Paragraph("Two") }.class("one")
            }
        }
        XCTAssertEqual(GroupWrapper().class("two").render(),
                       #"<p class="one two">One</p><p class="one two">Two</p>"#)

        XCTAssertEqual(
            ComponentGroup { Div(); Div() }.class("hello").render(),
            #"<div class="hello"></div><div class="hello"></div>"#
        )
        XCTAssertEqual(Node.div(.p()).class("hello").render(), #"<div class="hello"><p></p></div>"#)

        XCTAssertEqual(Paragraph("Hello").directionality(.leftToRight).render(), #"<p dir="ltr">Hello</p>"#)
        XCTAssertEqual(Paragraph("Text").style("color: #000;").render(), #"<p style="color: #000;">Text</p>"#)
        XCTAssertEqual(Paragraph("Text").data(named: "test", value: "value").render(),
                       #"<p data-test="value">Text</p>"#)
        XCTAssertEqual(Paragraph("Text").accessibilityLabel("Label").render(),
                       #"<p aria-label="Label">Text</p>"#)
    }
}
