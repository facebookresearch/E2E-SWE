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

final class ComponentListsAndTablesTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// The List and Table components: ordered/unordered styles, custom item classes, explicit
    /// mixed items (components, nodes, control flow), empty-component skipping, and grouped vs
    /// ungrouped tables with caption/header/footer.
    func testComponentListsAndTables() {
        XCTAssertEqual(List(["One", "Two"]).render(), "<ul><li>One</li><li>Two</li></ul>")
        XCTAssertEqual(List(["One", "Two"]).listStyle(.ordered).render(),
                       "<ol><li>One</li><li>Two</li></ol>")

        XCTAssertEqual(
            List([1, 2]) { number in Paragraph(String(number)) }
                .listStyle(.unordered.withItemClass("item")).render(),
            #"<ul><li class="item"><p>1</p></li><li class="item"><p>2</p></li></ul>"#
        )

        let bool = true
        struct SeventhComponent: Component {
            var body: Component { ListItem("Seven") }
        }
        let explicit = List {
            ListItem("One").number(1)
            Text("Two")
            if bool { Paragraph("Three").class("three") }
            ListItem("Four").class("four")
            for string in ["Five", "Six"] { ListItem(string) }
            SeventhComponent()
            Node.li("Eight")
            Node.group(.li("Nine"), .li("Ten", .class("ten")))
        }
        .listStyle(.ordered)
        .render()
        XCTAssertEqual(explicit, """
        <ol>\
        <li value="1">One</li><li>Two</li><li><p class="three">Three</p></li>\
        <li class="four">Four</li><li>Five</li><li>Six</li><li>Seven</li>\
        <li>Eight</li><li>Nine</li><li class="ten">Ten</li>\
        </ol>
        """)

        XCTAssertEqual(
            List { Text("Hello"); EmptyComponent() }.listStyle(.ordered).render(),
            "<ol><li>Hello</li></ol>"
        )

        let ungrouped = Table {
            Text("Row one")
            TableRow { TableCell("Row two, cell one"); TableCell("Row two, cell two") }
        }
        .render()
        XCTAssertEqual(ungrouped, """
        <table>\
        <tr><td>Row one</td></tr>\
        <tr><td>Row two, cell one</td><td>Row two, cell two</td></tr>\
        </table>
        """)

        let grouped = Table(
            caption: TableCaption("Caption"),
            header: TableRow { Text("Header") },
            footer: TableRow { Text("Footer") },
            rows: { TableRow { TableCell("Body") } }
        )
        .render()
        XCTAssertEqual(grouped, """
        <table>\
        <caption>Caption</caption>\
        <thead><tr><th>Header</th></tr></thead>\
        <tbody><tr><td>Body</td></tr></tbody>\
        <tfoot><tr><td>Footer</td></tr></tfoot>\
        </table>
        """)
    }
}
