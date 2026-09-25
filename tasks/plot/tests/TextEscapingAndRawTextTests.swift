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

final class TextEscapingAndRawTextTests: XCTestCase {
    /// Free-form text is HTML-escaped (`&`, `<`, `>`) but existing character/entity references
    /// (`&amp;`, `&#160;`, `&lt;`) are NOT double-escaped; `.raw` text passes through untouched.
    func testTextEscapingAndRawText() {
        XCTAssertEqual(Node<Any>.text("Hello & welcome to <Plot>!;").render(),
                       "Hello &amp; welcome to &lt;Plot&gt;!;")
        XCTAssertEqual(Node<Any>.text("&&").render(), "&amp;&amp;")
        XCTAssertEqual(Node<Any>.text("&< &>").render(), "&amp;&lt; &amp;&gt;")
        XCTAssertEqual(Node<Any>.text("Hello &amp; welcome&#160;to &lt;Plot&gt;!&text").render(),
                       "Hello &amp; welcome&#160;to &lt;Plot&gt;!&amp;text")
        XCTAssertEqual(Node<Any>.raw("Hello & welcome to <Plot>!").render(),
                       "Hello & welcome to <Plot>!")
    }
}
