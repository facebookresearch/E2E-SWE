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

final class ComponentEnvironmentAndTextTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// The component environment API: values propagate down a hierarchy (not to siblings), can be
    /// applied at the top-level HTML document, support custom keys via `@EnvironmentValue`, and
    /// per-component overrides (link relationship/target). Also Text styling + concatenation.
    func testComponentEnvironmentAndText() {
        let siblings = Div {
            Link("One", url: "/one").linkTarget(.blank)
            Link("Two", url: "/two").linkRelationship(.nofollow)
            Link("Three", url: "/three")
        }
        .render()
        XCTAssertEqual(siblings, """
        <div>\
        <a href="/one" target="_blank">One</a>\
        <a href="/two" rel="nofollow">Two</a>\
        <a href="/three">Three</a>\
        </div>
        """)

        let topLevel = HTML(.body { Link("One", url: "/one"); Link("Two", url: "/two") })
            .environmentValue(.nofollow, key: .linkRelationship)
        assertHTML(topLevel, """
        <body>\
        <a href="/one" rel="nofollow">One</a>\
        <a href="/two" rel="nofollow">Two</a>\
        </body>
        """)

        let overrides = Div {
            Link("First", url: "/first")
            Link("Second", url: "/second").linkRelationship(.noreferrer).linkTarget(nil)
        }
        .linkRelationship(.nofollow)
        .linkTarget(.blank)
        .render()
        // The First anchor carries both an environment-injected `rel` and `target`; those two
        // independent attributes have no spec-pinned relative order, so accept either ordering
        // (mirroring the AudioPlayer <source> handling in ComponentFormsAndMediaTests).
        let overridesRelFirst = """
        <div>\
        <a href="/first" rel="nofollow" target="_blank">First</a>\
        <a href="/second" rel="noreferrer">Second</a>\
        </div>
        """
        let overridesTargetFirst = """
        <div>\
        <a href="/first" target="_blank" rel="nofollow">First</a>\
        <a href="/second" rel="noreferrer">Second</a>\
        </div>
        """
        XCTAssertTrue(overrides == overridesRelFirst || overrides == overridesTargetFirst,
                      "Unexpected overrides rendering: \(overrides)")

        struct TestComponent: Component {
            @EnvironmentValue(.init(identifier: "key")) var value: String?
            var body: Component { Paragraph(value ?? "No value") }
        }
        XCTAssertEqual(
            TestComponent().environmentValue("Value", key: .init(identifier: "key")).render(),
            "<p>Value</p>"
        )

        let time = Time(datetime: "2011-11-18T14:54:39Z") { Paragraph("Hello World") }.render()
        XCTAssertEqual(time, #"<time datetime="2011-11-18T14:54:39Z"><p>Hello World</p></time>"#)

        let styled = Div {
            Text("Bold").bold().addLineBreak()
            Text("Italic").italic().addLineBreak()
            Text("Underlined").underlined().addLineBreak()
            Text("Strikethrough").strikethrough().addLineBreak()
        }
        .render()
        XCTAssertEqual(styled, """
        <div><b>Bold</b><br/><em>Italic</em><br/><u>Underlined</u><br/><s>Strikethrough</s><br/></div>
        """)

        let concat = Text("One") + Text(" ") + Text("Two").bold()
        XCTAssertEqual(concat.render(), "One <b>Two</b>")
    }
}
