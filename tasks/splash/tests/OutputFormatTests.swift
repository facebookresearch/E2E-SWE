import XCTest
import Splash

final class OutputFormatTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// HTMLOutputFormat wraps each token in a span with its type's CSS class and escapes &, < and > in both tokens and plain text.
    func testHTMLGenerationAndEscaping() {
        XCTAssertEqual(hl("public struct Test: SomeProtocol {\n    func hello() -> Int { return 7 }\n}"), "<span class=\"keyword\">public struct</span> Test: <span class=\"type\">SomeProtocol</span> {\n    <span class=\"keyword\">func</span> hello() -&gt; <span class=\"type\">Int</span> { <span class=\"keyword\">return</span> <span class=\"number\">7</span> }\n}")
        XCTAssertEqual(hl("Array<String>"), "<span class=\"type\">Array</span>&lt;<span class=\"type\">String</span>&gt;")
        XCTAssertEqual(hl("// Hey I'm a comment!"), "<span class=\"comment\">// Hey I'm a comment!</span>")
        XCTAssertEqual(hl("let a = \"<Hello&World>\""), "<span class=\"keyword\">let</span> a = <span class=\"string\">\"&lt;Hello&amp;World&gt;\"</span>")
    }

    /// HTMLOutputFormat's classPrefix is prepended to every generated CSS class name.
    func testHTMLClassPrefix() {
        XCTAssertEqual(SyntaxHighlighter(format: HTMLOutputFormat(classPrefix: "splash-")).highlight("func hello() -> Int"), "<span class=\"splash-keyword\">func</span> hello() -&gt; <span class=\"splash-type\">Int</span>")
    }

    /// MarkdownDecorator replaces fenced code blocks with highlighted <pre class="splash"><code>...; a 'no-highlight' block is only escaped, and special characters are escaped in both cases.
    func testMarkdownDecoration() {
        XCTAssertEqual(MarkdownDecorator().decorate("# Title\n\nText text text `inline.code.shouldNotBeHighlighted()`.\n\n```\nstruct Hello: Protocol {}\n```\n\nText."), "# Title\n\nText text text `inline.code.shouldNotBeHighlighted()`.\n\n<pre class=\"splash\"><code><span class=\"keyword\">struct</span> Hello: <span class=\"type\">Protocol</span> {}</code></pre>\n\nText.")
        XCTAssertEqual(MarkdownDecorator().decorate("Text text.\n\n```no-highlight\nstruct Hello: Protocol {}\n```\n\nText."), "Text text.\n\n<pre class=\"splash\"><code>struct Hello: Protocol {}</code></pre>\n\nText.")
        XCTAssertEqual(MarkdownDecorator().decorate("Text text.\n\n```\nlet a = \"<Hello&World>\"\n```\n\nText.\n"), "Text text.\n\n<pre class=\"splash\"><code><span class=\"keyword\">let</span> a = <span class=\"string\">\"&lt;Hello&amp;World&gt;\"</span></code></pre>\n\nText.\n")
    }

    /// TokenType.string yields the case name for built-in cases and the wrapped value for a custom case.
    func testTokenTypeStringValue() {
        XCTAssertEqual(TokenType.comment.string, "comment")
        XCTAssertEqual(TokenType.keyword.string, "keyword")
        XCTAssertEqual(TokenType.string.string, "string")
        XCTAssertEqual(TokenType.type.string, "type")
        XCTAssertEqual(TokenType.call.string, "call")
        XCTAssertEqual(TokenType.number.string, "number")
        XCTAssertEqual(TokenType.property.string, "property")
        XCTAssertEqual(TokenType.dotAccess.string, "dotAccess")
        XCTAssertEqual(TokenType.preprocessing.string, "preprocessing")
        XCTAssertEqual(TokenType.custom("MyCustomType").string, "MyCustomType")
    }

}
