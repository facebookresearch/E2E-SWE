//
// Hidden grading suite for the `plot` WRG task -- Podcast feed layer.
//
// Exercises the `PodcastFeed` document format: the RSS wrapper extended with the itunes + media
// namespaces, the iTunes channel metadata, and episode `<item>` entries including the audio
// enclosure/media-content expansion, durations, season/episode numbers, and CDATA content.
//

import XCTest
import Foundation
import Plot

final class PodcastChannelMetadataTests: XCTestCase {
    private let prefix = #"<?xml version="1.0" encoding="UTF-8"?>"# +
        #"<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" "# +
        #"xmlns:content="http://purl.org/rss/1.0/modules/content/" "# +
        #"xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" "# +
        #"xmlns:media="http://www.rssboard.org/media-rss"><channel>"#
    private let suffix = "</channel></rss>"

    /// iTunes channel metadata: new-feed-url, title, subtitle, description, summary, author,
    /// copyright, owner (name/email), nested categories, image, atom link, language and TTL;
    /// plus the explicit flag ("yes"/"no") and podcast type ("episodic"/"serial").
    func testPodcastChannelMetadata() {
        let feed = PodcastFeed(
            .newFeedURL("url.com"),
            .title("MyPodcast"),
            .subtitle("Subtitle"),
            .description("Description"),
            .summary("Summary"),
            .author("Author"),
            .copyright("Copyright"),
            .owner(.name("Name"), .email("Email")),
            .category("News", .category("Tech News")),
            .image("image.png"),
            .atomLink("url.com"),
            .language(.usEnglish),
            .ttl(200)
        )

        XCTAssertEqual(feed.render(), prefix + """
        <itunes:new-feed-url>url.com</itunes:new-feed-url>\
        <title>MyPodcast</title>\
        <itunes:subtitle>Subtitle</itunes:subtitle>\
        <description>Description</description>\
        <itunes:summary>Summary</itunes:summary>\
        <itunes:author>Author</itunes:author>\
        <copyright>Copyright</copyright>\
        <itunes:owner><itunes:name>Name</itunes:name><itunes:email>Email</itunes:email></itunes:owner>\
        <itunes:category text="News"><itunes:category text="Tech News"/></itunes:category>\
        <itunes:image href="image.png"/>\
        <atom:link href="url.com" rel="self" type="application/rss+xml"/>\
        <language>en-us</language>\
        <ttl>200</ttl>
        """ + suffix)

        XCTAssertEqual(PodcastFeed(.explicit(true)).render(),
                       prefix + "<itunes:explicit>yes</itunes:explicit>" + suffix)
        XCTAssertEqual(PodcastFeed(.explicit(false)).render(),
                       prefix + "<itunes:explicit>no</itunes:explicit>" + suffix)
        XCTAssertEqual(PodcastFeed(.type(.episodic)).render(),
                       prefix + "<itunes:type>episodic</itunes:type>" + suffix)
        XCTAssertEqual(PodcastFeed(.type(.serial)).render(),
                       prefix + "<itunes:type>serial</itunes:type>" + suffix)
    }
}
