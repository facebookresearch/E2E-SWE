// Hidden grading suite — HTML sanitization (Cleaner + Whitelist).
// Public API only (`import SwiftSoup`). Expected values taken from SwiftSoup's own tests.
// Custom whitelists start from the public Whitelist.none() (an empty whitelist).

import XCTest
import Foundation
import SwiftSoup

private func stripNewlines(_ text: String) -> String {
    guard let regex = try? NSRegularExpression(pattern: "\\n\\s*", options: .caseInsensitive) else { return text }
    return regex.stringByReplacingMatches(in: text, options: [],
                                          range: NSRange(text.startIndex..., in: text), withTemplate: "")
}

final class SanitizeTests: XCTestCase {

    func testSimpleTextAndBasic() throws {
        let simple = try SwiftSoup.clean("<div><p class=foo><a href='http://evil.com'>Hello <b id=bar>there</b>!</a></div>",
                                         Whitelist.simpleText())!
        XCTAssertEqual("Hello <b>there</b>!", stripNewlines(simple))

        let basic = try SwiftSoup.clean("<div><p><a href='javascript:sendAllMoney()'>Dodgy</a> <A HREF='HTTP://nice.com'>Nice</a></p><blockquote>Hello</blockquote>",
                                        Whitelist.basic())!
        XCTAssertEqual("<p><a rel=\"nofollow\">Dodgy</a> <a href=\"HTTP://nice.com\" rel=\"nofollow\">Nice</a></p><blockquote>Hello</blockquote>",
                       stripNewlines(basic))
    }

    func testBasicWithImagesAndRelaxed() throws {
        let imgs = try SwiftSoup.clean("<div><p><img src='http://example.com/' alt=Image></p><p><img src='ftp://ftp.example.com'></p></div>",
                                       Whitelist.basicWithImages())!
        XCTAssertEqual("<p><img src=\"http://example.com/\" alt=\"Image\" /></p><p><img /></p>", stripNewlines(imgs))

        let relaxed = try SwiftSoup.clean("<h1>Head</h1><table><tr><td>One<td>Two</td></tr></table>", Whitelist.relaxed())!
        XCTAssertEqual("<h1>Head</h1><table><tbody><tr><td>One</td><td>Two</td></tr></tbody></table>", stripNewlines(relaxed))
    }

    func testDropsUnsafeContent() throws {
        XCTAssertEqual("", try SwiftSoup.clean("<SCRIPT SRC=//ha.ckers.org/.j><SCRIPT>alert(/XSS/.source)</SCRIPT>", Whitelist.relaxed())!)
        XCTAssertEqual("<img />", try SwiftSoup.clean("<IMG SRC=\"javascript:alert('XSS')\">", Whitelist.relaxed())!)
        XCTAssertEqual("<a>XSS</a>", try SwiftSoup.clean("<A HREF=\"javascript:document.location='http://x/'\">XSS</A>", Whitelist.relaxed())!)
        XCTAssertEqual("<p>Test</p>", try SwiftSoup.clean("<p><custom foo=true>Test</custom></p>", Whitelist.relaxed())!)
    }

    func testCustomWhitelistBuilders() throws {
        // addProtocols lets otherwise-rejected schemes through
        let proto = try SwiftSoup.clean("<img src='cid:12345' /> <img src='data:gzzt' />",
                                        Whitelist.basicWithImages().addProtocols("img", "src", "cid", "data"))!
        XCTAssertEqual("<img src=\"cid:12345\" /> <img src=\"data:gzzt\" />", stripNewlines(proto))

        // removeEnforcedAttribute drops the enforced rel=nofollow on <a>
        let noRel = try SwiftSoup.clean("<div><p><A HREF='HTTP://nice.com'>Nice</a></p><blockquote>Hello</blockquote>",
                                        Whitelist.basic().removeEnforcedAttribute("a", "rel"))!
        XCTAssertEqual("<p><a href=\"HTTP://nice.com\">Nice</a></p><blockquote>Hello</blockquote>", stripNewlines(noRel))

        // ":all" attribute applies to every tag; adding attributes implies the tag is allowed
        let all = try SwiftSoup.clean("<p class='foo' src='bar'><a class='qux'>link</a></p>",
                                      Whitelist.none().addAttributes(":all", "class").addAttributes("p", "style").addTags("p", "a"))!
        XCTAssertEqual("<p class=\"foo\"><a class=\"qux\">link</a></p>", all)
        let inferred = try SwiftSoup.clean("<p class='foo' src='bar'>One</p>", Whitelist.none().addAttributes("p", "class"))!
        XCTAssertEqual("<p class=\"foo\">One</p>", inferred)
    }

    func testIsValidAndRelativeLinks() throws {
        XCTAssertTrue(try SwiftSoup.isValid("<p>Test <b><a href='http://example.com/'>OK</a></b></p>", Whitelist.basic()))
        XCTAssertFalse(try SwiftSoup.isValid("<p><script></script>Not <b>OK</b></p>", Whitelist.basic()))
        XCTAssertFalse(try SwiftSoup.isValid("<p align=right>Test Not <b>OK</b></p>", Whitelist.basic()))

        // relative links resolved against base by default
        let resolved = try SwiftSoup.clean("<a href='/foo'>Link</a><img src='/bar'>", "http://example.com/", Whitelist.basicWithImages())!
        XCTAssertEqual("<a href=\"http://example.com/foo\" rel=\"nofollow\">Link</a><img src=\"http://example.com/bar\" />", stripNewlines(resolved))
        // preserveRelativeLinks keeps them relative (and still drops a javascript: src)
        let preserved = try SwiftSoup.clean("<a href='/foo'>Link</a><img src='/bar'> <img src='javascript:alert()'>",
                                            "http://example.com/", Whitelist.basicWithImages().preserveRelativeLinks(true))!
        XCTAssertEqual("<a href=\"/foo\" rel=\"nofollow\">Link</a><img src=\"/bar\" /> <img />", stripNewlines(preserved))
        // Whitelist.none() normalizes &nbsp; to a space
        XCTAssertEqual(" ", try SwiftSoup.clean("&nbsp;", Whitelist.none())!)
    }

    func testCSSPropertyFiltering() throws {
        // keep only whitelisted CSS properties (case-insensitive), serialized "prop:value; ..."
        let kept = try SwiftSoup.clean("<p style=\"color: red; position: absolute; font-weight: bold;\">Hello</p>",
                                       Whitelist.none().addTags("p").addAttributes("p", "style").addCSSProperties("p", "color", "font-weight"))!
        XCTAssertEqual("<p style=\"color:red; font-weight:bold\">Hello</p>", kept)
        // drop style entirely when nothing whitelisted remains
        let dropped = try SwiftSoup.clean("<p style=\"position:absolute\">Hello</p>",
                                          Whitelist.none().addTags("p").addAttributes("p", "style").addCSSProperties("p", "color"))!
        XCTAssertEqual("<p>Hello</p>", dropped)
        // unsafe declarations are dropped even when the property name is whitelisted
        let safe = try SwiftSoup.clean("<p style=\"color:red; background-image:url(javascript:alert(1)); width:expression(alert(1));\">Hello</p>",
                                       Whitelist.none().addTags("p").addAttributes("p", "style").addCSSProperties("p", "color", "background-image", "width"))!
        XCTAssertEqual("<p style=\"color:red\">Hello</p>", safe)
    }
}
