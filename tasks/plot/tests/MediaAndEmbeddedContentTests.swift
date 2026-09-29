//
// Hidden grading suite for the `plot` WRG task -- HTML <body> element layer (Node-based DSL).
//
// Exercises the breadth of the HTML5 element set and its attribute rendering through the public
// `HTML(.body(...))` Node DSL + `render()`. Variants of the same underlying "render a named
// element / attribute" mechanism are consolidated into one test each, so the score tracks whether
// the candidate implemented the mechanism + breadth rather than awarding per-tag credit.
//

import XCTest
import Plot

final class MediaAndEmbeddedContentTests: XCTestCase {
    private func assertHTML(_ document: HTML, _ content: String,
                            file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertEqual(document.render(), "<!DOCTYPE html><html>" + content + "</html>",
                       file: file, line: line)
    }

    /// Media and embedded content: images, audio/video with typed <source> children, <picture>
    /// art direction, iframes, embeds, objects, <data>, <time>, and <details>/<summary>.
    func testMediaAndEmbeddedContent() {
        assertHTML(HTML(.body(.img(
            .id("id"), .class("image"), .src("image.png"), .alt("Text"), .width(44), .height(44)
        ))), """
        <body><img id="id" class="image" src="image.png" alt="Text" width="44" height="44"/></body>
        """)

        assertHTML(HTML(.body(
            .audio(.source(.src("a.mp3"), .type(.mp3))),
            .audio(.controls(true), .source(.src("b.wav"), .type(.wav)))
        )), """
        <body>\
        <audio><source src="a.mp3" type="audio/mpeg"/></audio>\
        <audio controls><source src="b.wav" type="audio/wav"/></audio>\
        </body>
        """)

        assertHTML(HTML(.body(
            .video(.source(.src("a.mp4"), .type(.mp4))),
            .video(.controls(true), .source(.src("b.webm"), .type(.webM)))
        )), """
        <body>\
        <video><source src="a.mp4" type="video/mp4"/></video>\
        <video controls><source src="b.webm" type="video/webm"/></video>\
        </body>
        """)

        assertHTML(HTML(.body(.picture(
            .source(.srcset("dark.jpg"), .media("(prefers-color-scheme: dark)")),
            .img(.src("default.jpg"))
        ))), """
        <body><picture>\
        <source srcset="dark.jpg" media="(prefers-color-scheme: dark)"/>\
        <img src="default.jpg"/>\
        </picture></body>
        """)

        assertHTML(HTML(.body(.iframe(
            .src("url.com"), .frameborder(false), .allow("gyroscope"), .allowfullscreen(false)
        ))), """
        <body><iframe src="url.com" frameborder="0" allow="gyroscope"></iframe></body>
        """)

        assertHTML(HTML(.body(.embed(
            .src("url"), .type("some/type"), .width(500), .height(300)
        ))), """
        <body><embed src="url" type="some/type" width="500" height="300"/></body>
        """)

        assertHTML(HTML(.body(.object(.data("vector.svg")))),
                   #"<body><object data="vector.svg"></object></body>"#)

        assertHTML(HTML(.body(.data(.value("123"), .text("Hello")))),
                   #"<body><data value="123">Hello</data></body>"#)

        assertHTML(HTML(.body(.time(.text("Hello World!"), .datetime("2011-11-18T14:54:39Z")))), """
        <body><time datetime="2011-11-18T14:54:39Z">Hello World!</time></body>
        """)

        assertHTML(HTML(.body(
            .details(.open(true), .summary("Open Summary"), .p("Text")),
            .details(.open(false), .summary("Closed Summary"), .p("Text"))
        )), """
        <body>\
        <details open><summary>Open Summary</summary><p>Text</p></details>\
        <details><summary>Closed Summary</summary><p>Text</p></details>\
        </body>
        """)
    }
}
