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

final class ElementBasedComponentsTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// The built-in element-based component library, each rendered to its corresponding HTML tag.
    func testElementBasedComponents() {
        let html = HTML {
            Article("Article"); Button("Button"); Details("Details"); Div("Div")
            FieldSet("FieldSet"); Footer("Footer")
            H1("H1"); H2("H2"); H3("H3"); H4("H4"); H5("H5"); H6("H6")
            Header("Header"); ListItem("ListItem"); Main("Main"); Navigation("Navigation")
            Paragraph("Paragraph"); Span("Span"); Summary("Summary")
            TableCaption("TableCaption"); TableCell("TableCell"); TableHeaderCell("TableHeaderCell")
        }

        assertHTML(html, """
        <body>\
        <article>Article</article><button>Button</button><details>Details</details><div>Div</div>\
        <fieldset>FieldSet</fieldset><footer>Footer</footer>\
        <h1>H1</h1><h2>H2</h2><h3>H3</h3><h4>H4</h4><h5>H5</h5><h6>H6</h6>\
        <header>Header</header><li>ListItem</li><main>Main</main><nav>Navigation</nav>\
        <p>Paragraph</p><span>Span</span><summary>Summary</summary>\
        <caption>TableCaption</caption><td>TableCell</td><th>TableHeaderCell</th>\
        </body>
        """)
    }
}
