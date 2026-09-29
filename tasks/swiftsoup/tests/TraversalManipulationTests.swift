// Hidden grading suite — DOM traversal, accessors & structural manipulation.
// Public API only (`import SwiftSoup`). Expected values taken from SwiftSoup's own tests.

import XCTest
import Foundation
import SwiftSoup

private func stripNewlines(_ text: String) -> String {
    guard let regex = try? NSRegularExpression(pattern: "\\n\\s*", options: .caseInsensitive) else { return text }
    return regex.stringByReplacingMatches(in: text, options: [],
                                          range: NSRange(text.startIndex..., in: text), withTemplate: "")
}

final class TraversalManipulationTests: XCTestCase {

    private let reference = "<div id=div1><p>Hello</p><p>Another <b>element</b></p><div id=div2><img src=foo.png></div></div>"

    func testTextAndOwnText() throws {
        let p = try SwiftSoup.parse("<p>Hello <b>there</b> now").select("p").first()!
        XCTAssertEqual("Hello there now", try p.text())
        XCTAssertEqual("Hello now", p.ownText())
        // whitespace is collapsed & trimmed across the subtree
        XCTAssertEqual("Hello There. Here is some text.",
                       try SwiftSoup.parse("<p>Hello<p>There.</p> \n <p>Here <b>is</b> \n s<b>om</b>e text.").text())
        // &nbsp; normalizes to a space; <br> introduces a space
        XCTAssertEqual("a b c d", try SwiftSoup.parse("<p>a\u{00a0}b\tc</p><p>d</p>").text())
        XCTAssertEqual("Hello there", try SwiftSoup.parse("<p>Hello<br>there</p>").text())
        // whitespace preserved inside <pre>
        XCTAssertEqual("code\n\ncode", try SwiftSoup.parse("<pre><code>code\n\ncode</code></pre>").text())
    }

    func testNavigation() throws {
        let doc = try SwiftSoup.parse("<div><p>Hello<p id=1>there<p>this<p>is<p>an<p id=last>element</div>")
        let p = try doc.getElementById("1")!
        XCTAssertEqual("there", try p.text())
        XCTAssertEqual("Hello", try p.previousElementSibling()?.text())
        XCTAssertEqual("this", try p.nextElementSibling()?.text())
        XCTAssertEqual("Hello", try p.firstElementSibling()?.text())
        XCTAssertEqual("element", try p.lastElementSibling()?.text())

        let doc2 = try SwiftSoup.parse("<div><p>Hello <span>there</span></div>")
        let parents = try doc2.select("span").first()!.parents()
        XCTAssertEqual(["p", "div", "body", "html"], parents.array().map { $0.tagName() })

        let doc3 = try SwiftSoup.parse("<div><p>One</p>...<p>Two</p>...<p>Three</p>")
        let ps = try doc3.select("p")
        XCTAssertEqual([0, 1, 2], try ps.array().map { try $0.elementSiblingIndex() })
    }

    func testFindElementByIdTagClassAttr() throws {
        let doc = try SwiftSoup.parse(reference)
        XCTAssertEqual(["div1", "div2"], try doc.getElementsByTag("div").array().map { $0.id() })
        XCTAssertEqual(2, try doc.getElementsByTag("p").size())
        XCTAssertEqual("div1", try doc.getElementById("div1")!.id())
        XCTAssertNil(try doc.getElementById("none"))

        let doc2 = try SwiftSoup.parse("<div class='mellow yellow'><span class=mellow>Hello <b class='yellow'>Yellow!</b></span><p>Empty</p></div>")
        XCTAssertEqual(["div", "span"], try doc2.getElementsByClass("mellow").array().map { $0.tagName() })
        XCTAssertEqual(["div", "b"], try doc2.getElementsByClass("yellow").array().map { $0.tagName() })

        let doc3 = try SwiftSoup.parse("<div style='bold'><p title=qux><p><b style></b></p></div>")
        XCTAssertEqual(["div", "b"], try doc3.getElementsByAttribute("style").array().map { $0.tagName() })
        XCTAssertEqual(["div"], try doc3.getElementsByAttributeValue("style", "bold").array().map { $0.tagName() })
    }

    func testClassManipulation() throws {
        let div = try SwiftSoup.parse("<div class='mellow yellow'></div>").select("div").first()!
        try div.addClass("green")
        XCTAssertEqual("mellow yellow green", try div.className())
        try div.removeClass("red") // no-op
        try div.removeClass("yellow")
        XCTAssertEqual("mellow green", try div.className())
        _ = try div.toggleClass("green").toggleClass("red")
        XCTAssertEqual("mellow red", try div.className())
        XCTAssertTrue(div.hasClass("mellow"))
        XCTAssertFalse(div.hasClass("green"))

        // className collapses surrounding whitespace; hasClass is whitespace/case aware
        let span = try SwiftSoup.parse("<div><span class=' mellow yellow '>Hi</span></div>").select("span").first()!
        XCTAssertEqual("mellow yellow", try span.className())
        XCTAssertEqual(2, try span.classNames().count)
    }

    func testAttributeManipulation() throws {
        let a = try SwiftSoup.parse("<a href=/foo>Hello</a>", "https://jsoup.org/").select("a").first()!
        XCTAssertEqual("/foo", try a.attr("href"))
        XCTAssertEqual("https://jsoup.org/foo", try a.attr("abs:href"))   // resolved against base
        XCTAssertTrue(a.hasAttr("href"))
        _ = try a.attr("href", "/bar")
        XCTAssertEqual("/bar", try a.attr("href"))
        _ = try a.removeAttr("href")
        XCTAssertFalse(a.hasAttr("href"))

        // boolean attribute: present, empty value, serializes bare; a false boolean is dropped
        let div = try Document("").createElement("div")
        _ = try div.attr("true", true)
        _ = try div.attr("false", "value")
        _ = try div.attr("false", false)
        XCTAssertTrue(div.hasAttr("true"))
        XCTAssertEqual("", try div.attr("true"))
        XCTAssertFalse(div.hasAttr("false"))
        XCTAssertEqual("<div true></div>", try div.outerHtml())
    }

    func testAppendPrependAndSetHtml() throws {
        let div = try SwiftSoup.parse("<div id=1><p>Hello</p></div>").getElementById("1")!
        _ = try div.append("<p>there</p><p>now</p>")
        XCTAssertEqual("<p>Hello</p><p>there</p><p>now</p>", try stripNewlines(div.html()))

        let div2 = try SwiftSoup.parse("<div id=1><p>Hello</p></div>").getElementById("1")!
        _ = try div2.prepend("<p>there</p><p>now</p>")
        XCTAssertEqual("<p>there</p><p>now</p><p>Hello</p>", try stripNewlines(div2.html()))

        // appendElement returns the NEW element; appendText escapes special characters
        let div3 = try SwiftSoup.parse("<div id=1><p>Hello</p></div>").getElementById("1")!
        try div3.appendElement("p").text("there")
        XCTAssertEqual("there", try div3.child(1).text())
        _ = try div3.appendText(" x & y >")
        XCTAssertEqual("<p>Hello</p><p>there</p> x &amp; y &gt;", try stripNewlines(div3.html()))

        // html() setter replaces children
        let div4 = try SwiftSoup.parse("<div id=1><p>Hello</p></div>").getElementById("1")!
        _ = try div4.html("<p>there</p><p>now</p>")
        XCTAssertEqual("<p>there</p><p>now</p>", try stripNewlines(div4.html()))
    }

    func testWrapUnwrapEmptyRemove() throws {
        let doc = try SwiftSoup.parse("<div><p>Hello</p><p>There</p></div>")
        let p = try doc.select("p").first()!
        _ = try p.wrap("<div class='head'></div>")
        XCTAssertEqual("<div><div class=\"head\"><p>Hello</p></div><p>There</p></div>",
                       try stripNewlines(doc.body()!.html()))

        let docU = try SwiftSoup.parse("<div>One <span>Two <b>Three</b></span> Four</div>")
        _ = try docU.select("span").first()!.unwrap()
        XCTAssertEqual("<div>One Two <b>Three</b> Four</div>", try stripNewlines(docU.body()!.html()))

        // remove a child node
        let docR = try SwiftSoup.parse("<p>One <span>two</span> three</p>")
        let pr = try docR.select("p").first()!
        try pr.childNode(0).remove()
        XCTAssertEqual("two three", try pr.text())
        XCTAssertEqual("<span>two</span> three", try stripNewlines(pr.html()))

        // empty() removes all children
        let docE = try SwiftSoup.parse("<div><p>One</p><p>Two</p></div>")
        let de = try docE.select("div").first()!
        _ = de.empty()
        XCTAssertEqual(0, de.childNodeSize())
    }

    func testBeforeAfterAndInsertChildren() throws {
        let doc = try SwiftSoup.parse("<div><p>Hello</p><p>There</p></div>")
        let p1 = try doc.select("p").first()!
        try p1.before("<div>one</div><div>two</div>")
        XCTAssertEqual("<div><div>one</div><div>two</div><p>Hello</p><p>There</p></div>",
                       try stripNewlines(doc.body()!.html()))

        let doc2 = try SwiftSoup.parse("<div><p>Hello</p><p>There</p></div>")
        let p2 = try doc2.select("p").first()!
        try p2.after("<div>one</div><div>two</div>")
        XCTAssertEqual("<div><p>Hello</p><div>one</div><div>two</div><p>There</p></div>",
                       try stripNewlines(doc2.body()!.html()))

        // insertChildren moves nodes: empty div1 into div2
        let docM = try SwiftSoup.parse("<div id=1>Text <p>One</p> Text <p>Two</p></div><div id=2></div>")
        let div1 = try docM.select("div").get(0)
        let div2 = try docM.select("div").get(1)
        _ = try div2.insertChildren(0, div1.getChildNodes())
        XCTAssertEqual(0, div1.childNodeSize())
        XCTAssertEqual(4, div2.childNodeSize())
        XCTAssertEqual("<div id=\"1\"></div><div id=\"2\">Text <p>One</p> Text <p>Two</p></div>",
                       try stripNewlines(docM.body()!.html()))
    }
}
