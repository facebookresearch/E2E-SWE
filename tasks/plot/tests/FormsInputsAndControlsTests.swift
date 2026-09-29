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

final class FormsInputsAndControlsTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Forms: action/method/enctype/novalidate on <form>, fieldset/label, the full range of
    /// <input> types and their boolean/valued attributes, <textarea>, option lists
    /// (<datalist>/<select>/<option>), and buttons.
    func testFormsInputsAndControls() {
        assertHTML(HTML(.body(.form(
            .action("url.com"),
            .fieldset(
                .label(.for("a"), "A label"),
                .input(.name("a"), .type(.text))
            ),
            .input(.name("b"), .type(.search), .autocomplete(false), .autofocus(true)),
            .input(.name("c"), .type(.text), .autofocus(false), .readonly(false), .disabled(false)),
            .input(.name("d"), .type(.email), .placeholder("email address"), .autocomplete(true), .required(true)),
            .input(.name("e"), .type(.text), .readonly(true), .disabled(true)),
            .textarea(.name("f"), .cols(50), .rows(10), .required(true), .text("Test")),
            .input(.name("i"), .type(.checkbox), .checked(true)),
            .input(.name("j"), .type(.file), .multiple(true)),
            .input(.type(.submit), .value("Send"))
        ))), """
        <body><form action="url.com">\
        <fieldset><label for="a">A label</label><input name="a" type="text"/></fieldset>\
        <input name="b" type="search" autocomplete="off" autofocus/>\
        <input name="c" type="text"/>\
        <input name="d" type="email" placeholder="email address" autocomplete="on" required/>\
        <input name="e" type="text" readonly disabled/>\
        <textarea name="f" cols="50" rows="10" required>Test</textarea>\
        <input name="i" type="checkbox" checked/>\
        <input name="j" type="file" multiple/>\
        <input type="submit" value="Send"/>\
        </form></body>
        """)

        assertHTML(HTML(.body(
            .form(.enctype(.urlEncoded)),
            .form(.enctype(.multipartData)),
            .form(.enctype(.plainText)),
            .form(.method(.get)),
            .form(.method(.post)),
            .form(.novalidate())
        )), """
        <body>\
        <form enctype="application/x-www-form-urlencoded"></form>\
        <form enctype="multipart/form-data"></form>\
        <form enctype="text/plain"></form>\
        <form method="get"></form>\
        <form method="post"></form>\
        <form novalidate></form>\
        </body>
        """)

        assertHTML(HTML(.body(
            .datalist(.option(.value("A")), .option(.value("B"))),
            .select(
                .option(.value("C"), .isSelected(true)),
                .option(.value("D"), .label("Dee"), .isSelected(false))
            )
        )), """
        <body>\
        <datalist><option value="A"/><option value="B"/></datalist>\
        <select><option value="C" selected/><option value="D" label="Dee"/></select>\
        </body>
        """)

        assertHTML(HTML(.body(
            .button(.type(.button), .name("Name"), .value("Value"), .text("Text")),
            .button(.type(.submit), .text("Submit"))
        )), """
        <body>\
        <button type="button" name="Name" value="Value">Text</button>\
        <button type="submit">Submit</button>\
        </body>
        """)
    }
}
