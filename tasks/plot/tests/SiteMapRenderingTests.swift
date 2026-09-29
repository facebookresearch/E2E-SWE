//
// Hidden grading suite for the `plot` WRG task -- SiteMap layer.
//
// Exercises the `SiteMap` XML format: the `<urlset>` wrapper with its two fixed namespaces, and
// `<url>` entries with location, change frequency, priority and a W3C-formatted last-modified date.
//

import XCTest
import Foundation
import Plot

final class SiteMapRenderingTests: XCTestCase {
    private let prefix = #"<?xml version="1.0" encoding="UTF-8"?>"# +
        #"<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" "# +
        #"xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">"#
    private let suffix = "</urlset>"

    private func fixedDate() -> (date: Date, timeZone: TimeZone) {
        let timeZone = TimeZone(secondsFromGMT: 60 * 60)!
        var c = DateComponents()
        c.calendar = Calendar(identifier: .gregorian)
        c.timeZone = timeZone
        c.year = 2019; c.month = 10; c.day = 17
        c.hour = 10; c.minute = 15; c.second = 5
        return (c.date!, timeZone)
    }

    /// An empty site map renders just the urlset wrapper; a populated one renders `<url>` entries
    /// with loc/changefreq/priority/lastmod, and the change frequency is taken from the enum.
    func testSiteMapRendering() {
        XCTAssertEqual(SiteMap().render(), prefix + suffix)

        let stub = fixedDate()

        let daily = SiteMap(.url(
            .loc("url.com"),
            .changefreq(.daily),
            .priority(1.0),
            .lastmod(stub.date, timeZone: stub.timeZone)
        ))
        XCTAssertEqual(daily.render(), prefix + """
        <url>\
        <loc>url.com</loc>\
        <changefreq>daily</changefreq>\
        <priority>1.0</priority>\
        <lastmod>2019-10-17</lastmod>\
        </url>
        """ + suffix)

        let monthly = SiteMap(.url(
            .loc("url.com"),
            .changefreq(.monthly),
            .priority(1.0),
            .lastmod(stub.date, timeZone: stub.timeZone)
        ))
        XCTAssertEqual(monthly.render(), prefix + """
        <url>\
        <loc>url.com</loc>\
        <changefreq>monthly</changefreq>\
        <priority>1.0</priority>\
        <lastmod>2019-10-17</lastmod>\
        </url>
        """ + suffix)
    }
}
