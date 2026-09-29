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

final class HeadResourcesAndSocialMetadataTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Document encoding, stylesheets, inline CSS, favicon, the three viewport variants,
    /// the social-image/Twitter-card group, and an RSS feed link -- each a `<head>` resource
    /// with its own auto-completed attributes.
    func testHeadResourcesAndSocialMetadata() {
        assertHTML(HTML(.head(.encoding(.utf8))),
                   #"<head><meta charset="UTF-8"/></head>"#)

        assertHTML(HTML(.head(.stylesheet("styles.css"))), """
        <head><link rel="stylesheet" href="styles.css" type="text/css"/></head>
        """)

        assertHTML(HTML(.head(.style("body { color: #000; }"))), """
        <head><style>body { color: #000; }</style></head>
        """)

        assertHTML(HTML(.head(.favicon("icon.png"))), """
        <head><link rel="shortcut icon" href="icon.png" type="image/png"/></head>
        """)

        assertHTML(HTML(.head(.viewport(.accordingToDevice))), """
        <head><meta name="viewport" content="width=device-width, initial-scale=1.0"/></head>
        """)
        assertHTML(HTML(.head(.viewport(.constant(500)))), """
        <head><meta name="viewport" content="width=500, initial-scale=1.0"/></head>
        """)
        assertHTML(HTML(.head(.viewport(.accordingToDevice, fit: .cover))), """
        <head><meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover"/></head>
        """)

        assertHTML(HTML(.head(
            .socialImageLink("url.png"),
            .twitterCardType(.summaryLargeImage),
            .twitterUsername("@CreatorHandle")
        )), """
        <head>\
        <meta name="twitter:image" content="url.png"/>\
        <meta property="og:image" content="url.png"/>\
        <meta name="twitter:card" content="summary_large_image"/>\
        <meta name="twitter:site" content="@CreatorHandle"/>\
        </head>
        """)

        assertHTML(HTML(.head(.rssFeedLink("feed.rss", title: "RSS"))), """
        <head><link rel="alternate" href="feed.rss" type="application/rss+xml" title="RSS"/></head>
        """)
    }
}
