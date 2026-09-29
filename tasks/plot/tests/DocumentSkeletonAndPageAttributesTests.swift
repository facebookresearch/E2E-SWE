//
// Hidden grading suite for the `plot` WRG task -- HTML <head> / document layer.
//
// Exercises the document skeleton, the <html> page attributes, and the metadata-expansion
// behaviour that is Plot's core value-add: a single DSL call in the <head> expands into a
// specific, ordered set of <meta>/<link> tags (Twitter Card + Open Graph + canonical, etc.).
// Driven entirely through the public `HTML` DSL + `render()`; no @testable import.
//

import XCTest
import Plot

final class DocumentSkeletonAndPageAttributesTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// The document skeleton (doctype + <html> wrapper) plus the page-level `lang` and
    /// text-direction attributes rendered on the root <html> element.
    func testDocumentSkeletonAndPageAttributes() {
        XCTAssertEqual(HTML().render(), "<!DOCTYPE html><html></html>")
        XCTAssertEqual(HTML(.lang(.english)).render(), #"<!DOCTYPE html><html lang="en"></html>"#)
        XCTAssertEqual(HTML(.dir(.leftToRight)).render(), #"<!DOCTYPE html><html dir="ltr"></html>"#)
        XCTAssertEqual(HTML(.dir(.rightToLeft)).render(), #"<!DOCTYPE html><html dir="rtl"></html>"#)
        XCTAssertEqual(HTML(.dir(.auto)).render(), #"<!DOCTYPE html><html dir="auto"></html>"#)
    }
}
