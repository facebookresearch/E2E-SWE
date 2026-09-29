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

final class PodcastEpisodesTests: XCTestCase {
    private let prefix = #"<?xml version="1.0" encoding="UTF-8"?>"# +
        #"<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" "# +
        #"xmlns:content="http://purl.org/rss/1.0/modules/content/" "# +
        #"xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" "# +
        #"xmlns:media="http://www.rssboard.org/media-rss"><channel>"#
    private let suffix = "</channel></rss>"

    /// Episodes: the title (rendered as both <title> and <itunes:title>), GUID, description,
    /// the three duration forms, season/episode numbers, episode types, the audio enclosure +
    /// media:content expansion, and CDATA-encoded HTML content.
    func testPodcastEpisodes() {
        let feed = PodcastFeed(
            .item(
                .title("Title"),
                .guid("url.com", .isPermaLink(true)),
                .description("Description"),
                .duration("00:15:12"),
                .duration(hours: 0, minutes: 15, seconds: 12),
                .duration(hours: 1, minutes: 2, seconds: 3),
                .seasonNumber(3),
                .episodeNumber(42),
                .episodeType(.full)
            )
        )

        XCTAssertEqual(feed.render(), prefix + """
        <item>\
        <title>Title</title><itunes:title>Title</itunes:title>\
        <guid isPermaLink="true">url.com</guid>\
        <description>Description</description>\
        <itunes:duration>00:15:12</itunes:duration>\
        <itunes:duration>00:15:12</itunes:duration>\
        <itunes:duration>01:02:03</itunes:duration>\
        <itunes:season>3</itunes:season>\
        <itunes:episode>42</itunes:episode>\
        <itunes:episodeType>full</itunes:episodeType>\
        </item>
        """ + suffix)

        XCTAssertEqual(
            PodcastFeed(
                .item(.episodeType(.trailer)),
                .item(.episodeType(.bonus))
            ).render(),
            prefix + """
            <item><itunes:episodeType>trailer</itunes:episodeType></item>\
            <item><itunes:episodeType>bonus</itunes:episodeType></item>
            """ + suffix
        )

        let audio = PodcastFeed(.item(.audio(
            url: "episode.mp3",
            byteSize: 69121733,
            title: "Episode"
        )))
        XCTAssertEqual(audio.render(), prefix + """
        <item>\
        <enclosure url="episode.mp3" length="69121733" type="audio/mpeg"/>\
        <media:content url="episode.mp3" length="69121733" type="audio/mpeg" isDefault="true" medium="audio">\
        <media:title type="plain">Episode</media:title>\
        </media:content>\
        </item>
        """ + suffix)

        let content = PodcastFeed(.item(.content("<p>Hello</p><p>World &amp; Everyone!</p>")))
        XCTAssertEqual(content.render(), prefix + """
        <item><content:encoded><![CDATA[<p>Hello</p><p>World &amp; Everyone!</p>]]></content:encoded></item>
        """ + suffix)
    }
}
