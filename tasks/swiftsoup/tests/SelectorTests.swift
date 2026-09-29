// Hidden grading suite — CSS selector engine.
// Public API only (`import SwiftSoup`). Expected values taken from SwiftSoup's own tests.

import XCTest
import Foundation
import SwiftSoup

final class SelectorTests: XCTestCase {

    // Build the CssTest structural fixture: #pseudo has <p>1..10>, #type has p/span/em/svg 1..10 each.
    private func structuralDoc() throws -> Document {
        var s = "<html><head></head><body><div id='pseudo'>"
        for i in 1...10 { s += "<p>\(i)</p>" }
        s += "</div><div id='type'>"
        for i in 1...10 { s += "<p>\(i)</p><span>\(i)</span><em>\(i)</em><svg>\(i)</svg>" }
        s += "</div><span id='onlySpan'><br /></span><p class='empty'><!-- c --></p>"
        s += "<div id='only'>Some text before the <em>only</em> child in this div</div></body></html>"
        return try SwiftSoup.parse(s)
    }

    private func ownTexts(_ els: Elements) -> [String] { els.array().map { $0.ownText() } }

    func testByTagIdClass() throws {
        // Tag match is case-insensitive.
        let els = try SwiftSoup.parse("<div id=1><div id=2><p>Hello</p></div></div><DIV id=3>").select("DIV")
        XCTAssertEqual(["1", "2", "3"], els.array().map { $0.id() })
        // #id (duplicate ids both match) and .class (case-insensitive class token).
        XCTAssertEqual(2, try SwiftSoup.parse("<div><p id=foo>Hello</p><p id=foo>Foo two!</p></div>").select("#foo").size())
        let byClass = try SwiftSoup.parse("<p id=0 class='ONE two'><p id=1 class='one'><p id=2 class='two'>").select("P.One")
        XCTAssertEqual(["0", "1"], byClass.array().map { $0.id() })
    }

    func testByAttribute() throws {
        let h = "<div Title=Foo /><div Title=Bar /><div Style=Qux /><div title=Bam /><div title=SLAM /><div data-name='with spaces'/>"
        let doc = try SwiftSoup.parse(h)
        XCTAssertEqual(4, try doc.select("[title]").size())             // has attribute
        XCTAssertEqual(1, try doc.select("[TITLE=foo]").size())         // value, case-insensitive key & value
        XCTAssertEqual(1, try doc.select("[data-name=\"with spaces\"]").size())
        XCTAssertEqual(5, try doc.select("div[title!=bar]").size())     // not-equal (also matches missing)
        XCTAssertEqual(["Bar", "Bam"], try doc.select("[title^=ba]").array().map { try $0.attr("title") })       // starts-with
        XCTAssertEqual(["Bam", "SLAM"], try doc.select("[title$=am]").array().map { try $0.attr("title") })      // ends-with
        XCTAssertEqual(["Bar", "Bam", "SLAM"], try doc.select("[title*=a]").array().map { try $0.attr("title") }) // contains
        // attribute-name prefix
        let dp = try SwiftSoup.parse("<div id=1 data-x=1></div><div data-y=2 id=2></div><div id=3></div>")
        XCTAssertEqual(["1", "2"], try dp.select("[^data-]").array().map { $0.id() })
    }

    func testCombinators() throws {
        // descendant (space) vs child (>)
        let doc = try SwiftSoup.parse("<div id=1><div id=2><div id=3></div></div></div><div id=4></div>")
        XCTAssertEqual(["2", "3"], try doc.select("div > div").array().map { $0.id() })
        XCTAssertEqual(["2"], try doc.select("div#1 > div").array().map { $0.id() })
        // adjacent (+) and general (~) sibling
        let doc2 = try SwiftSoup.parse("<ol><li id=1>One<li id=2>Two<li id=3>Three</ol>")
        XCTAssertEqual(2, try doc2.select("li + li").size())
        XCTAssertEqual("Two", try doc2.select("li#1 + li#2").get(0).text())
        XCTAssertEqual(0, try doc2.select("li#1 + li#3").size())
        XCTAssertEqual("Three", try doc2.select("#1 ~ #3").first()!.text())
    }

    func testGroupAndUniversal() throws {
        let doc = try SwiftSoup.parse("<div title=foo /><div title=bar /><div /><p></p><img /><span title=qux>")
        let group = try doc.select("p,div,[title]")
        XCTAssertEqual(5, group.size())
        XCTAssertEqual(["div", "div", "div", "p", "span"], group.array().map { $0.tagName() })
        // universal (descendants of div, unambiguous) & tag-qualified universal
        let doc2 = try SwiftSoup.parse("<div><p>Hello</p><p><b>there</b></p></div>")
        XCTAssertEqual(["p", "p", "b"], try doc2.select("div *").array().map { $0.tagName() })
        XCTAssertEqual(2, try SwiftSoup.parse("<p class=first>One<p class=first>Two<p>Three").select("*.first").size())
    }

    func testStructuralChildPseudo() throws {
        let doc = try structuralDoc()
        XCTAssertEqual(["1"], ownTexts(try doc.select("#pseudo :first-child")))
        XCTAssertEqual(["10"], ownTexts(try doc.select("#pseudo :last-child")))
        for i in 1...10 { XCTAssertEqual(["\(i)"], ownTexts(try doc.select("#pseudo :nth-child(\(i))"))) }
        XCTAssertEqual(["1", "3", "5", "7", "9"], ownTexts(try doc.select("#pseudo :nth-child(odd)")))
        XCTAssertEqual(["1", "3", "5", "7", "9"], ownTexts(try doc.select("#pseudo :nth-child(2n+1)")))
        XCTAssertEqual(["2", "5", "8"], ownTexts(try doc.select("#pseudo :nth-child(3n-1)")))
        XCTAssertEqual(["1", "3", "5"], ownTexts(try doc.select("#pseudo :nth-child(-2n+5)")))
        XCTAssertEqual(["10"], ownTexts(try doc.select("#pseudo :nth-last-child(1)")))
        // :empty (head, the <br/>'s parent has a br child so not empty; the comment-only <p> is empty) and :only-child
        let empties = try doc.select(":empty")
        XCTAssertEqual(["head", "br", "p"], empties.array().map { $0.tagName() })
        XCTAssertEqual(["only"], ownTexts(try doc.select("#only :only-child")))
    }

    func testStructuralTypePseudo() throws {
        let doc = try structuralDoc()
        for i in 1...10 { XCTAssertEqual(["\(i)"], ownTexts(try doc.select("#type p:nth-of-type(\(i))"))) }
        XCTAssertEqual(["1", "3", "5", "7", "9"], ownTexts(try doc.select("#type p:nth-of-type(odd)")))
        XCTAssertEqual(["2", "5", "8"], ownTexts(try doc.select("#type p:nth-of-type(3n-1)")))
        XCTAssertEqual(["1", "1", "1", "1", "1"], ownTexts(try doc.select("div:not(#only) :first-of-type")))
        XCTAssertEqual(["10", "10", "10", "10", "10"], ownTexts(try doc.select("div:not(#only) :last-of-type")))
        // :root and :only-of-type. :only-of-type is scoped under `html ` so the count is derivable
        // under standard CSS (the root <html>, a descendant of itself under neither, is excluded either way).
        let root = try doc.select(":root")
        XCTAssertEqual(1, root.size())
        XCTAssertEqual("html", root.get(0).tagName())
        XCTAssertEqual(6, try doc.select("html :only-of-type").size())
    }

    func testIndexedPseudo() throws {
        let doc = try SwiftSoup.parse("<div><p>One</p><p>Two</p><p>Three</p></div><div><p>Four</p>")
        XCTAssertEqual(["One", "Two", "Four"], try doc.select("div p:lt(2)").array().map { try $0.text() })
        XCTAssertEqual(["Two", "Three"], try doc.select("div p:gt(0)").array().map { try $0.text() })
        XCTAssertEqual(["One", "Four"], try doc.select("div p:eq(0)").array().map { try $0.text() })
        XCTAssertEqual(["Two"], try doc.select("div p:gt(0):lt(2)").array().map { try $0.text() })
    }

    func testHasNotContainsMatches() throws {
        let doc = try SwiftSoup.parse("<div id=0><p><span>Hello</span></p></div> <div id=1><span class=foo>There</span></div> <div id=2><p>Not</p></div>")
        XCTAssertEqual(["0", "1"], try doc.select("div:has(span)").array().map { $0.id() })
        XCTAssertEqual(["0", "1", "2"], try doc.select("div:has(span, p)").array().map { $0.id() })
        let doc2 = try SwiftSoup.parse("<p id=1>One</p> <p>Two</p> <p><span>Three</span></p>")
        XCTAssertEqual(["Two", "Three"], try doc2.select("p:not([id=1])").array().map { try $0.text() })
        XCTAssertEqual(["One", "Two"], try doc2.select("p:not(:has(span))").array().map { try $0.text() })
        // :contains (case-insensitive, normalized) and :matches (regex, case-sensitive)
        let doc3 = try SwiftSoup.parse("<div><p>The Rain.</p> <p class=light>The <i>rain</i>.</p> <p>Rain, the.</p></div>")
        XCTAssertEqual(3, try doc3.select("p:contains(Rain)").size())
        XCTAssertEqual(2, try doc3.select("p:contains(the rain)").size())
        let doc4 = try SwiftSoup.parse("<p id=1>The <i>Rain</i></p> <p id=2>There are 99 bottles.</p> <p id=4>Rain</p>")
        XCTAssertEqual(0, try doc4.select("p:matches(The rain)").size())            // case sensitive: no match
        XCTAssertEqual("1", try doc4.select("p:matches((?i)the rain)").first()!.id())
        XCTAssertEqual("2", try doc4.select("p:matches(\\d+)").first()!.id())
        XCTAssertEqual("1", try SwiftSoup.parse("<p id=1>Hello <b>there</b> now</p>").select("p:containsOwn(Hello now)").first()!.id())
    }
}
