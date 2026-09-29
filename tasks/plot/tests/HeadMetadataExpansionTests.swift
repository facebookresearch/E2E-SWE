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

final class HeadMetadataExpansionTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Title, description, URL and site-name each expand into their full set of ordered
    /// metadata tags (page <title>, Twitter Card `twitter:*`, Open Graph `og:*`, canonical link).
    func testHeadMetadataExpansion() {
        let html = HTML(.head(
            .title("Title"),
            .description("Description"),
            .url("url.com"),
            .siteName("MySite")
        ))

        assertHTML(html, """
        <head>\
        <title>Title</title>\
        <meta name="twitter:title" content="Title"/>\
        <meta property="og:title" content="Title"/>\
        <meta name="description" content="Description"/>\
        <meta name="twitter:description" content="Description"/>\
        <meta property="og:description" content="Description"/>\
        <link rel="canonical" href="url.com"/>\
        <meta name="twitter:url" content="url.com"/>\
        <meta property="og:url" content="url.com"/>\
        <meta property="og:site_name" content="MySite"/>\
        </head>
        """)
    }
}
