//
// Hidden grading suite for the `plot` WRG task -- HTML <body> element layer (Node-based DSL).
//
// Exercises the breadth of the HTML5 element set and its attribute rendering through the public
// `HTML(.body(...))` Node DSL + `render()`. Variants of the same underlying "render a named
// element / attribute" mechanism are consolidated into one test each, so the score tracks whether
// the candidate implemented the mechanism + breadth rather than awarding per-tag credit.
//

import XCTest
import Plot

final class TextAndBasicElementsTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Headings, paragraphs, inline text styling, code/preformatted blocks, quotes/abbreviations,
    /// line/horizontal rules, comments, and the sectioning/other basic block elements.
    func testTextAndBasicElements() {
        assertHTML(HTML(.body(
            .h1("One"), .h2("Two"), .h3("Three"), .h4("Four"), .h5("Five"), .h6("Six")
        )), """
        <body>\
        <h1>One</h1><h2>Two</h2><h3>Three</h3><h4>Four</h4><h5>Five</h5><h6>Six</h6>\
        </body>
        """)

        assertHTML(HTML(.body(.p("Text"))), "<body><p>Text</p></body>")

        assertHTML(HTML(.body(
            .b("Bold"), .strong("Bold"), .i("Italic"), .em("Italic"),
            .u("Underlined"), .s("Strikethrough"), .ins("Inserted"),
            .del("Deleted"), .small("Small")
        )), """
        <body>\
        <b>Bold</b><strong>Bold</strong><i>Italic</i><em>Italic</em>\
        <u>Underlined</u><s>Strikethrough</s><ins>Inserted</ins><del>Deleted</del><small>Small</small>\
        </body>
        """)

        assertHTML(HTML(.body(.p(.code("hello()")), .pre(.code("world()")))), """
        <body><p><code>hello()</code></p><pre><code>world()</code></pre></body>
        """)

        assertHTML(HTML(.body(.blockquote("Quote"))), "<body><blockquote>Quote</blockquote></body>")
        assertHTML(HTML(.body(.abbr(.title("HyperText Markup Language"), "HTML"))), """
        <body><abbr title="HyperText Markup Language">HTML</abbr></body>
        """)

        assertHTML(HTML(.body("One", .br(), "Two")), "<body>One<br/>Two</body>")
        assertHTML(HTML(.body("One", .hr(), "Two")), "<body>One<hr/>Two</body>")
        assertHTML(HTML(.body("One", .hr(.class("alternate")), "Two")),
                   #"<body>One<hr class="alternate"/>Two</body>"#)

        assertHTML(HTML(.comment("Hello"), .body(.comment("World"))),
                   "<!--Hello--><body><!--World--></body>")

        assertHTML(HTML(.body(
            .noscript("NoScript"), .nav("Navigation"),
            .section("Section"), .aside("Aside"), .main("Main")
        )), """
        <body>\
        <noscript>NoScript</noscript><nav>Navigation</nav>\
        <section>Section</section><aside>Aside</aside><main>Main</main>\
        </body>
        """)

        assertHTML(HTML(.body(
            .article(.header(.h1("Title")), .p("Body"), .footer(.span("Footer")))
        )), """
        <body><article>\
        <header><h1>Title</h1></header><p>Body</p><footer><span>Footer</span></footer>\
        </article></body>
        """)
    }
}
