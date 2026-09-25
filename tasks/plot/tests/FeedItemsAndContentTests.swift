//
// Hidden grading suite for the `plot` WRG task -- RSS feed layer.
//
// Exercises the `RSS` document format: the XML + `<rss>`/`<channel>` wrapper with its atom and
// content namespaces, channel-level metadata (incl. RFC-822 dates), and `<item>` entries with
// GUIDs, links, and CDATA-encoded HTML content.
//

import XCTest
import Foundation
import Plot

final class FeedItemsAndContentTests: XCTestCase {
    private let prefix = #"<?xml version="1.0" encoding="UTF-8"?>"# +
        #"<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" "# +
        #"xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>"#
    private let suffix = "</channel></rss>"

    private func fixedDate() -> (date: Date, timeZone: TimeZone) {
        let timeZone = TimeZone(secondsFromGMT: 60 * 60)!
        var c = DateComponents()
        c.calendar = Calendar(identifier: .gregorian)
        c.timeZone = timeZone
        c.year = 2019; c.month = 10; c.day = 17
        c.hour = 10; c.minute = 15; c.second = 5
        return (c.date!, timeZone)
    }

    /// Items: GUIDs (plain and with the isPermaLink flag), title/link/description, and HTML
    /// content assigned either as a raw string or via the DSL -- both CDATA-wrapped inside
    /// `<content:encoded>`. Also a channel description rendered from HTML nodes (CDATA-wrapped).
    func testFeedItemsAndContent() {
        let items = RSS(
            .item(.guid("123")),
            .item(.guid("url.com", .isPermaLink(true))),
            .item(.guid("123", .isPermaLink(false))),
            .item(.title("Title"), .link("url.com"), .description("Description")),
            .item(.content("<p>Hello</p><p>World &amp; Everyone!</p>")),
            .item(.content(.h1("Title")))
        )

        XCTAssertEqual(items.render(), prefix + """
        <item><guid>123</guid></item>\
        <item><guid isPermaLink="true">url.com</guid></item>\
        <item><guid isPermaLink="false">123</guid></item>\
        <item><title>Title</title><link>url.com</link><description>Description</description></item>\
        <item><content:encoded><![CDATA[<p>Hello</p><p>World &amp; Everyone!</p>]]></content:encoded></item>\
        <item><content:encoded><![CDATA[<h1>Title</h1>]]></content:encoded></item>
        """ + suffix)

        let htmlDescription = RSS(.description(
            .p(.text("Description with "), .em("emphasis"), .text("."))
        ))
        XCTAssertEqual(htmlDescription.render(), prefix + """
        <description><![CDATA[<p>Description with <em>emphasis</em>.</p>]]></description>
        """ + suffix)
    }
}
