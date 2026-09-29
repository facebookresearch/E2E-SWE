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

final class FeedChannelMetadataTests: XCTestCase {
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

    /// Channel-level metadata: title, link, description, language, self-referential atom link,
    /// TTL, and RFC-822 formatted publication / last-build dates.
    func testFeedChannelMetadata() {
        let stub = fixedDate()

        let feed = RSS(
            .title("MyPodcast"),
            .link("url.com"),
            .description("Description"),
            .language(.usEnglish),
            .atomLink("url.com"),
            .ttl(200),
            .lastBuildDate(stub.date, timeZone: stub.timeZone),
            .pubDate(stub.date, timeZone: stub.timeZone)
        )

        XCTAssertEqual(feed.render(), prefix + """
        <title>MyPodcast</title>\
        <link>url.com</link>\
        <description>Description</description>\
        <language>en-us</language>\
        <atom:link href="url.com" rel="self" type="application/rss+xml"/>\
        <ttl>200</ttl>\
        <lastBuildDate>Thu, 17 Oct 2019 10:15:05 +0100</lastBuildDate>\
        <pubDate>Thu, 17 Oct 2019 10:15:05 +0100</pubDate>
        """ + suffix)
    }
}
