// Hidden grading suite — serialization / OutputSettings.
// Public API only (`import SwiftSoup`). Expected values taken from SwiftSoup's own tests.
// Most tests assert exact pretty-printed output (with newlines/indentation). testHtmlVsXmlSyntax
// normalizes inter-element newlines so it grades the well-specified doctype casing, boolean-attribute
// serialization and escaping, not the non-derivable line break before an unknown tag.

import XCTest
import Foundation
import SwiftSoup

private func stripNewlines(_ text: String) -> String {
    guard let regex = try? NSRegularExpression(pattern: "\\n\\s*", options: .caseInsensitive) else { return text }
    return regex.stringByReplacingMatches(in: text, options: [],
                                          range: NSRange(text.startIndex..., in: text), withTemplate: "")
}

final class OutputTests: XCTestCase {

    func testPrettyPrintFormatting() throws {
        let doc = try SwiftSoup.parse("<title>Format test</title><div><p>Hello <span>jsoup <span>users</span></span></p><p>Good.</p></div>")
        XCTAssertEqual("<html>\n <head>\n  <title>Format test</title>\n </head>\n <body>\n  <div>\n   <p>Hello <span>jsoup <span>users</span></span></p>\n   <p>Good.</p>\n  </div>\n </body>\n</html>",
                       try doc.html())
    }

    func testOutputToggles() throws {
        // prettyPrint(false): no added whitespace, source-ish round-trip
        let docNP = try SwiftSoup.parse("<div>   \n<p>Hello\n there\n</p></div>")
        docNP.outputSettings().prettyPrint(pretty: false)
        XCTAssertEqual("<html><head></head><body><div>   \n<p>Hello\n there\n</p></div></body></html>", try docNP.html())

        // indentAmount(0): newlines but no indentation
        let docI = try SwiftSoup.parse("<div><p>Hello\nthere</p></div>")
        docI.outputSettings().indentAmount(indentAmount: 0)
        XCTAssertEqual("<html>\n<head></head>\n<body>\n<div>\n<p>Hello there</p>\n</div>\n</body>\n</html>", try docI.html())

        // outline(true): inline elements break onto their own indented lines
        let docO = try SwiftSoup.parse("<title>Format test</title><div><p>Hello <span>jsoup <span>users</span></span></p><p>Good.</p></div>")
        docO.outputSettings().outline(outlineMode: true)
        XCTAssertEqual("<html>\n <head>\n  <title>Format test</title>\n </head>\n <body>\n  <div>\n   <p>\n    Hello \n    <span>\n     jsoup \n     <span>users</span>\n    </span>\n   </p>\n   <p>Good.</p>\n  </div>\n </body>\n</html>",
                       try docO.html())
    }

    func testEncodingAndEscapeModes() throws {
        let doc = try SwiftSoup.parse("<p title=π>π & < > </p>")
        XCTAssertEqual("<p title=\"π\">π &amp; &lt; &gt; </p>", try doc.body()!.html())   // utf8 default
        doc.outputSettings().charset(String.Encoding.ascii)   // escapeMode defaults to .base
        // ascii + default .base mode: π has no base-named entity -> numeric &#x3c0; (extended names it &pi;, below).
        XCTAssertEqual("<p title=\"&#x3c0;\">&#x3c0; &amp; &lt; &gt; </p>", try doc.body()!.html())
        doc.outputSettings().escapeMode(Entities.EscapeMode.extended)
        XCTAssertEqual("<p title=\"&pi;\">&pi; &amp; &lt; &gt; </p>", try doc.body()!.html())          // ascii, extended

        let xhtml = try SwiftSoup.parse("&lt; &gt; &amp; &quot; &apos; &times;")
        xhtml.outputSettings().escapeMode(Entities.EscapeMode.xhtml)
        XCTAssertEqual("&lt; &gt; &amp; \" ' ×", try xhtml.body()!.html())
    }

    func testHtmlVsXmlSyntax() throws {
        let doc = try SwiftSoup.parse("<!DOCTYPE html><body><img async checked='checked' src='&<>\"'>&lt;&gt;&amp;&quot;<foo />bar")
        doc.outputSettings().syntax(syntax: OutputSettings.Syntax.html)
        XCTAssertEqual("<!doctype html><html><head></head><body><img async checked=\"checked\" src=\"&amp;<>&quot;\" />&lt;&gt;&amp;\"<foo />bar</body></html>",
                       stripNewlines(try doc.html()))
        doc.outputSettings().syntax(syntax: OutputSettings.Syntax.xml)
        XCTAssertEqual("<!DOCTYPE html><html><head></head><body><img async=\"\" checked=\"checked\" src=\"&amp;<>&quot;\" />&lt;&gt;&amp;\"<foo />bar</body></html>",
                       stripNewlines(try doc.html()))
    }

    func testVoidDataAndContainerOutput() throws {
        // <script>/<style> content is emitted verbatim (internal newlines preserved) and the closing
        // tag is not pushed onto a new line. Grade each element's own serialization so the
        // non-derivable inter-element whitespace between the two is not asserted.
        let docS = try SwiftSoup.parse("<script>one\ntwo</script>\n<style>three\nfour</style>")
        // Both raw-text elements are placed in the implicit <head>, in source order.
        XCTAssertEqual(["script", "style"], docS.head()!.children().array().map { $0.tagName() })
        XCTAssertEqual("<script>one\ntwo</script>", try docS.select("script").first()!.outerHtml())
        XCTAssertEqual("<style>three\nfour</style>", try docS.select("style").first()!.outerHtml())
        // empty block: no internal newline
        XCTAssertEqual("<section>\n <div></div>\n</section>",
                       try SwiftSoup.parse("<section><div></div></section>").select("section").first()!.outerHtml())
        // container element output (block children each on their own indented line)
        let docC = try SwiftSoup.parse("<title>Hello there</title> <div><p>Hello</p><p>there</p></div> <div>Another</div>")
        XCTAssertEqual("<div>\n <p>Hello</p>\n <p>there</p>\n</div>", try docC.select("div").first()!.outerHtml())
    }
}
