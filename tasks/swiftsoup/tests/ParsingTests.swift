// Hidden grading suite — HTML5 parsing & tree construction.
// Public API only (`import SwiftSoup`). Expected values taken from SwiftSoup's own tests.

import XCTest
import Foundation
import SwiftSoup

// Replica of the reference test helper TextUtil.stripNewlines (regex \n\s* -> "").
private func stripNewlines(_ text: String) -> String {
    guard let regex = try? NSRegularExpression(pattern: "\\n\\s*", options: .caseInsensitive) else { return text }
    return regex.stringByReplacingMatches(in: text, options: [],
                                          range: NSRange(text.startIndex..., in: text), withTemplate: "")
}

final class ParsingTests: XCTestCase {

    func testParsesDocumentStructureAndAccess() throws {
        let html = "<html><head><title>First!</title></head><body><p>First post! <img src=\"foo.png\" /></p></body></html>"
        let doc = try SwiftSoup.parse(html)
        let p = doc.body()!.child(0)
        XCTAssertEqual("p", p.tagName())
        let img = p.child(0)
        XCTAssertEqual("img", img.tagName())
        XCTAssertEqual("foo.png", try img.attr("src"))

        // Document shell + head/body partitioning.
        let doc2 = try SwiftSoup.parse("<meta name=keywords /><link rel=stylesheet /><title>SwiftSoup</title><p>Hello world</p>")
        XCTAssertEqual(1, doc2.children().size())          // <html>
        XCTAssertEqual(2, doc2.child(0).children().size()) // head + body
        XCTAssertEqual(3, doc2.head()!.children().size())  // meta, link, title
        XCTAssertEqual(1, doc2.body()!.children().size())  // p
        XCTAssertEqual("SwiftSoup", try doc2.title())
        XCTAssertEqual("Hello world", try doc2.body()!.text())
    }

    func testNormalisesMalformedDocuments() throws {
        XCTAssertEqual("<html><head></head><body></body></html>",
                       try stripNewlines(SwiftSoup.parse("").html()))
        XCTAssertEqual("<html><head></head><body><span class=\"foo\">bar</span></body></html>",
                       try stripNewlines(SwiftSoup.parse("<html><body><span class=\"foo\">bar</span>").html()))
        // Loose content & a head element appearing mid-stream are relocated correctly.
        let h = "<!doctype html>One<html>Two<head>Three<link></head>Four<body>Five </body>Six </html>Seven "
        XCTAssertEqual("<!doctype html><html><head></head><body>OneTwoThree<link />FourFive Six Seven </body></html>",
                       try stripNewlines(SwiftSoup.parse(h).html()))
    }

    func testHandlesTableStructure() throws {
        // <tbody> is implied around rows.
        let doc = try SwiftSoup.parse("<html><head></head><body><table><tbody><tr><td>aaa</td><td>bbb</td></tr></tbody></table></body></html>")
        XCTAssertEqual("<table><tbody><tr><td>aaa</td><td>bbb</td></tr></tbody></table>",
                       try stripNewlines(doc.body()!.html()))
        // Naked <td>s without a <table> are NOT wrapped in an implicit table.
        let doc2 = try SwiftSoup.parse("<td>Hello<td><p>There<p>now")
        XCTAssertEqual("Hello<p>There</p><p>now</p>", try stripNewlines(doc2.body()!.html()))
        // <li> are not auto-wrapped in a <ul>.
        let doc3 = try SwiftSoup.parse("<li>Point one<li>Point two")
        XCTAssertEqual(0, try doc3.select("ul").size())
        XCTAssertEqual(2, try doc3.select("li").size())
    }

    func testHandlesSelfClosingAndVoidTags() throws {
        // Known non-void tags self-closed get a real end tag; unknown tags may stay self-closed; void tags self-close.
        let h = "<div id='1' /><script src='/foo' /><div id=2><img /><img></div><a id=3 /><i /><foo /><foo>One</foo> <hr /> hr text <hr> hr text two"
        let want = "<div id=\"1\"></div><script src=\"/foo\"></script><div id=\"2\"><img /><img /></div><a id=\"3\"></a><i></i><foo /><foo>One</foo> <hr /> hr text <hr /> hr text two"
        XCTAssertEqual(want, try stripNewlines(SwiftSoup.parse(h).body()!.html()))
        // a known empty block in <head> forces an end tag, void <meta> stays self-closed
        let h2 = "<html><head><style /><meta name=foo></head><body>One</body></html>"
        XCTAssertEqual("<html><head><style></style><meta name=\"foo\" /></head><body>One</body></html>",
                       try stripNewlines(SwiftSoup.parse(h2).html()))
    }

    func testHandlesCommentsScriptAndStyleData() throws {
        // Comment node, not nested inside the void <img>.
        let doc = try SwiftSoup.parse("<html><head></head><body><img src=foo><!-- <table><tr><td></table> --><p>Hello</p></body></html>")
        let comment = doc.body()!.childNode(1) as! Comment
        XCTAssertEqual(" <table><tr><td></table> ", comment.getData())
        XCTAssertEqual("Hello", (doc.body()!.child(1).childNode(0) as! TextNode).getWholeText())

        // <style>/<script> contents are stored verbatim as a data node, not as text.
        let tels = try SwiftSoup.parse("<style>font-family: bold</style>").getElementsByTag("style")
        XCTAssertEqual("font-family: bold", tels.get(0).data())
        XCTAssertEqual("", try tels.get(0).text())
        let docS = try SwiftSoup.parse("<p>Hello</p><script>obj.insert('<a rel=\"none\" />');\ni++;</script><p>There</p>")
        XCTAssertEqual("Hello There", try docS.text())
        XCTAssertEqual("obj.insert('<a rel=\"none\" />');\ni++;", docS.data())
    }

    func testReconstructsMisnestedFormatting() throws {
        // Adoption agency: re-balance <b>/<i> and reconstruct active formatting elements.
        XCTAssertEqual("<p>1<b>2<i>3</i></b><i>4</i>5</p>",
                       try SwiftSoup.parse("<p>1<b>2<i>3</b>4</i>5</p>").body()!.html())
        // An unclosed <a> across a <p> boundary is reopened in the next paragraph.
        let want = "<a href=\"http://example.com/\">Link</a>\n<p><a href=\"http://example.com/\">Error link</a></p>"
        XCTAssertEqual(want, try SwiftSoup.parse("<a href='http://example.com/'>Link<p>Error link</a>").body()!.html())
    }

    func testParsesBodyFragmentUnknownTagsAndIsRobust() throws {
        // parseBodyFragment keeps a leading comment and resolves relative URLs against the base.
        let doc = try SwiftSoup.parseBodyFragment("<!-- comment --><p><a href='foo'>One</a></p>", "http://example.com")
        XCTAssertEqual("<body><!-- comment --><p><a href=\"foo\">One</a></p></body>",
                       try stripNewlines(doc.body()!.outerHtml()))
        XCTAssertEqual("http://example.com/foo", try doc.select("a").first()!.absUrl("href"))

        // Unknown tags are retained with their attributes.
        let foos = try SwiftSoup.parse("<div><foo title=bar>Hello<foo title=qux>there</foo></div>").select("foo")
        XCTAssertEqual(2, foos.size())
        XCTAssertEqual("bar", try foos.first()!.attr("title"))
        XCTAssertEqual("qux", try foos.last()!.attr("title"))

        // Truncated / malformed input never crashes and always yields a body.
        for h in ["<a href=\"", "<a href=\"&amp", "<!-- comment", "<script>var x = ", "&#x", "<", "</", "<a hr"] {
            XCTAssertNotNil(try SwiftSoup.parse(h).body(), "failed on \(h)")
        }
    }
}
