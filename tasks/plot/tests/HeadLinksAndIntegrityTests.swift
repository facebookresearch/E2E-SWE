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

final class HeadLinksAndIntegrityTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Custom `<link>` variants (hreflang, apple-touch-icon with sizes, crossorigin on/off,
    /// manifest, mask-icon with color) and Subresource Integrity on scripts, links and the
    /// stylesheet convenience.
    func testHeadLinksAndIntegrity() {
        assertHTML(HTML(.head(.link(
            .rel(.alternate),
            .href("http://site/"),
            .hreflang(.english)
        ))), """
        <head><link rel="alternate" href="http://site/" hreflang="en"/></head>
        """)

        assertHTML(HTML(.head(.link(
            .rel(.appleTouchIcon),
            .sizes("180x180"),
            .href("apple-touch-icon.png")
        ))), """
        <head><link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png"/></head>
        """)

        assertHTML(HTML(.head(.link(
            .rel(.preconnect),
            .href("https://foo.com"),
            .crossorigin(true)
        ))), """
        <head><link rel="preconnect" href="https://foo.com" crossorigin/></head>
        """)
        assertHTML(HTML(.head(.link(
            .rel(.preconnect),
            .href("https://foo.com"),
            .crossorigin(false)
        ))), """
        <head><link rel="preconnect" href="https://foo.com"/></head>
        """)

        assertHTML(HTML(.head(.link(.rel(.manifest), .href("site.webmanifest")))), """
        <head><link rel="manifest" href="site.webmanifest"/></head>
        """)

        assertHTML(HTML(.head(.link(
            .rel(.maskIcon),
            .href("safari-pinned-tab.svg"),
            .color("#000000")
        ))), """
        <head><link rel="mask-icon" href="safari-pinned-tab.svg" color="#000000"/></head>
        """)

        assertHTML(HTML(.head(
            .script(.src("file.js"), .integrity("sha384-fakeHash")),
            .link(.rel(.stylesheet), .href("styles.css"), .type("text/css"), .integrity("sha512-fakeHash")),
            .stylesheet("styles2.css", integrity: "sha256-fakeHash")
        )), """
        <head><script src="file.js" integrity="sha384-fakeHash"></script>\
        <link rel="stylesheet" href="styles.css" type="text/css" integrity="sha512-fakeHash"/>\
        <link rel="stylesheet" href="styles2.css" type="text/css" integrity="sha256-fakeHash"/>\
        </head>
        """)
    }
}
