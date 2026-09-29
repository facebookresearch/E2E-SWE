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

final class ListsAndTablesTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Ordered/unordered lists, description lists (flat and grouped-in-div), tables (caption +
    /// rows + header/data cells) and their grouping semantics (thead/tbody/tfoot).
    func testListsAndTables() {
        assertHTML(HTML(.body(.ul(.li("Text")))), "<body><ul><li>Text</li></ul></body>")
        assertHTML(HTML(.body(.ol(.li(.span("Text"))))),
                   "<body><ol><li><span>Text</span></li></ol></body>")

        assertHTML(HTML(.body(.dl(.dt("Term"), .dd("Description")))), """
        <body><dl><dt>Term</dt><dd>Description</dd></dl></body>
        """)

        assertHTML(HTML(.body(.dl(
            .div(.dt("Authors"), .dt("Editors"), .dd("Robert Rothman"), .dd("Daniel Jackson"))
        ))), """
        <body><dl><div>\
        <dt>Authors</dt><dt>Editors</dt><dd>Robert Rothman</dd><dd>Daniel Jackson</dd>\
        </div></dl></body>
        """)

        assertHTML(HTML(.body(.table(
            .caption("Caption"), .tr(.th("Hello")), .tr(.td("World"))
        ))), """
        <body><table>\
        <caption>Caption</caption><tr><th>Hello</th></tr><tr><td>World</td></tr>\
        </table></body>
        """)

        assertHTML(HTML(.body(.table(
            .thead(.tr(.th("Column1"), .th("Column2"))),
            .tbody(.tr(.td("Body1"), .td("Body2")), .tr(.td("Body3"), .td("Body4"))),
            .tfoot(.tr(.td("Foot1"), .td("Foot2")))
        ))), """
        <body><table>\
        <thead><tr><th>Column1</th><th>Column2</th></tr></thead>\
        <tbody><tr><td>Body1</td><td>Body2</td></tr><tr><td>Body3</td><td>Body4</td></tr></tbody>\
        <tfoot><tr><td>Foot1</td><td>Foot2</td></tr></tfoot>\
        </table></body>
        """)
    }
}
