// Hidden grading suite — HTML entity escaping / unescaping.
// Public API only (`import SwiftSoup`). Expected values taken from SwiftSoup's own tests.

import XCTest
import Foundation
import SwiftSoup

final class EntitiesTests: XCTestCase {

    private let sample = "Hello &<> Å å π 新 there ¾ © »"

    func testEscapeModes() throws {
        XCTAssertEqual("Hello &amp;&lt;&gt; &Aring; &aring; &#x3c0; &#x65b0; there &frac34; &copy; &raquo;",
                       Entities.escape(sample, OutputSettings().charset(.ascii).escapeMode(Entities.EscapeMode.base)))
        XCTAssertEqual("Hello &amp;&lt;&gt; &angst; &aring; &pi; &#x65b0; there &frac34; &copy; &raquo;",
                       Entities.escape(sample, OutputSettings().charset(.ascii).escapeMode(Entities.EscapeMode.extended)))
        XCTAssertEqual("Hello &amp;&lt;&gt; &#xc5; &#xe5; &#x3c0; &#x65b0; there &#xbe; &#xa9; &#xbb;",
                       Entities.escape(sample, OutputSettings().charset(.ascii).escapeMode(Entities.EscapeMode.xhtml)))
        // UTF-8: only &, <, > (and ") are escaped; everything else passes through literally.
        XCTAssertEqual("Hello &amp;&lt;&gt; Å å π 新 there ¾ © »",
                       Entities.escape(sample, OutputSettings().charset(.utf8).escapeMode(Entities.EscapeMode.extended)))
        XCTAssertEqual("Hello &amp;&lt;&gt; Å å π 新 there ¾ © »", Entities.escape(sample))
        // case-sensitive named entities
        XCTAssertEqual("&Uuml; &uuml; &amp; &amp;",
                       Entities.escape("Ü ü & &", OutputSettings().charset(.ascii).escapeMode(Entities.EscapeMode.extended)))
    }

    func testUnescape() throws {
        // mixed named (with/without ;), decimal, hex, unknowns left literal
        XCTAssertEqual("Hello Æ &<> ® Å &angst π π 新 there &! ¾ © ©",
                       try Entities.unescape("Hello &AElig; &amp;&LT&gt; &reg &angst; &angst &#960; &#960 &#x65B0; there &! &frac34; &copy; &COPY;"))
        // not entities — left verbatim
        XCTAssertEqual("&0987654321; &unknown", try Entities.unescape("&0987654321; &unknown"))
        XCTAssertEqual("http://www.foo.com?a=1&num_rooms=1&children=0&int=VA&b=2",
                       try Entities.unescape("http://www.foo.com?a=1&num_rooms=1&children=0&int=VA&b=2"))
        XCTAssertEqual("Ü ü & &", try Entities.unescape("&Uuml; &uuml; &amp; &AMP"))
    }

    func testNbspAndSupplementary() throws {
        XCTAssertEqual("hello&nbsp;world", Entities.escape("hello\u{A0}world"))                                  // default utf8/extended
        XCTAssertEqual("hello&nbsp;world", Entities.escape("hello\u{A0}world", OutputSettings().charset(.utf8).escapeMode(Entities.EscapeMode.base)))
        XCTAssertEqual("hello&#xa0;world", Entities.escape("hello\u{A0}world", OutputSettings().charset(.utf8).escapeMode(Entities.EscapeMode.xhtml)))
        // supplementary-plane character: numeric ref in ascii, literal in utf8
        XCTAssertEqual("&#x210c1;", Entities.escape("𡃁", OutputSettings().charset(.ascii).escapeMode(Entities.EscapeMode.base)))
        XCTAssertEqual("𡃁", Entities.escape("𡃁", OutputSettings().charset(.utf8).escapeMode(Entities.EscapeMode.base)))
        // multi-codepoint named entity
        XCTAssertEqual("\u{2AFD}\u{20E5}", try Entities.unescape("&nparsl;"))
    }

    func testStrictUnescapeAndRoundTrip() throws {
        // strict (attribute) mode: a named ref without ';' is NOT decoded
        XCTAssertEqual("Hello &amp= &", try Entities.unescape(string: "Hello &amp= &amp;", strict: true))
        XCTAssertEqual("Hello &= &", try Entities.unescape("Hello &amp= &amp;"))
        // escape -> unescape round-trips in every mode
        for mode in [Entities.EscapeMode.base, .extended, .xhtml] {
            let escaped = Entities.escape(sample, OutputSettings().charset(.ascii).escapeMode(mode))
            XCTAssertEqual(sample, try Entities.unescape(escaped))
        }
    }

    func testEscapeModeNameCodepointAndGetByName() throws {
        XCTAssertEqual(UnicodeScalar(38), Entities.EscapeMode.xhtml.codepointForName("amp"))
        XCTAssertEqual(UnicodeScalar(62), Entities.EscapeMode.xhtml.codepointForName("gt"))
        XCTAssertEqual(UnicodeScalar(60), Entities.EscapeMode.xhtml.codepointForName("lt"))
        XCTAssertEqual(UnicodeScalar(34), Entities.EscapeMode.xhtml.codepointForName("quot"))
        XCTAssertEqual("amp", Entities.EscapeMode.xhtml.nameForCodepoint(UnicodeScalar(38)!))
        XCTAssertEqual("quot", Entities.EscapeMode.xhtml.nameForCodepoint(UnicodeScalar(34)!))
        XCTAssertEqual("≫", Entities.getByName(name: "gg"))
        XCTAssertEqual("©", Entities.getByName(name: "copy"))
    }
}
