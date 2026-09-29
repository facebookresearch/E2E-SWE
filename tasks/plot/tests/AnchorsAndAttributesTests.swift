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

final class AnchorsAndAttributesTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Anchors and general attributes: href/target/rel, the `title` attribute, id/class (and
    /// class replacement), boolean `hidden`, custom `data-*` attributes, ARIA attributes,
    /// spellcheck, inline event handlers, and text directionality on individual elements.
    func testAnchorsAndAttributes() {
        assertHTML(HTML(.body(
            .a(.href("a.html"), .target(.blank), .text("A")),
            .a(.href("b.html"), .rel(.nofollow), .text("B"))
        )), """
        <body>\
        <a href="a.html" target="_blank">A</a>\
        <a href="b.html" rel="nofollow">B</a>\
        </body>
        """)

        assertHTML(HTML(.body(.id("anID"))), #"<body id="anID"></body>"#)
        assertHTML(HTML(.body(.class("myClass"))), #"<body class="myClass"></body>"#)
        assertHTML(HTML(.body(.class("a"), .class("b"))), #"<body class="b"></body>"#)

        assertHTML(HTML(.body(.div(.hidden(false)), .div(.hidden(true)))),
                   "<body><div></div><div hidden></div></body>")

        assertHTML(HTML(.body(
            .data(named: "user-name", value: "John"),
            .img(.data(named: "icon", value: "User"))
        )), """
        <body data-user-name="John"><img data-icon="User"/></body>
        """)

        assertHTML(HTML(.body(
            .button(.text("X"), .ariaLabel("Close")),
            .a(.ariaExpanded(true)),
            .a(.ariaHidden(true))
        )), """
        <body>\
        <button aria-label="Close">X</button>\
        <a aria-expanded="true"></a>\
        <a aria-hidden="true"></a>\
        </body>
        """)

        assertHTML(HTML(.body(
            .spellcheck(true),
            .form(.input(.type(.text), .spellcheck(false)))
        )), """
        <body spellcheck="true"><form><input type="text" spellcheck="false"/></form></body>
        """)

        assertHTML(HTML(.body(.div(.onclick("javascript:alert('Hello World')")))), """
        <body><div onclick="javascript:alert('Hello World')"></div></body>
        """)

        assertHTML(HTML(.body(
            .h1(.dir(.leftToRight), "Text"),
            .h1(.dir(.rightToLeft), "Text"),
            .input(.dir(.auto)),
            .textarea(.dir(.auto))
        )), """
        <body>\
        <h1 dir="ltr">Text</h1>\
        <h1 dir="rtl">Text</h1>\
        <input dir="auto"/>\
        <textarea dir="auto"></textarea>\
        </body>
        """)
    }
}
