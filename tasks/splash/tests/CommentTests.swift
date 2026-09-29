import XCTest
import Splash

final class CommentTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Single-line // and /// comments consume the rest of the line as one comment run, including punctuation and trailing commas.
    func testSingleLineComments() {
        XCTAssertEqual(hl("call() // Hello call() var \"string\"\ncall()"), "<span class=\"call\">call</span>() <span class=\"comment\">// Hello call() var \"string\"</span>\n<span class=\"call\">call</span>()")
        XCTAssertEqual(hl("//.call()"), "<span class=\"comment\">//.call()</span>")
        XCTAssertEqual(hl("// Hello,\nclass World {}"), "<span class=\"comment\">// Hello,</span>\n<span class=\"keyword\">class</span> World {}")
        XCTAssertEqual(hl("func find(\n    string: String,//TODO: Remove\n    options: Options\n)"), "<span class=\"keyword\">func</span> find(\n    string: <span class=\"type\">String</span>,<span class=\"comment\">//TODO: Remove</span>\n    options: <span class=\"type\">Options</span>\n)")
        XCTAssertEqual(hl("/// Documentation.\npublic func hello()"), "<span class=\"comment\">/// Documentation.</span>\n<span class=\"keyword\">public func</span> hello()")
    }

    /// Multi-line /* */ and /** */ comments (incl. documentation blocks) are highlighted as comments across lines.
    func testMultiLineComments() {
        XCTAssertEqual(hl("struct Foo {}\n/* Comment\n    Hello!\n*/ call()"), "<span class=\"keyword\">struct</span> Foo {}\n<span class=\"comment\">/* Comment\n    Hello!\n*/</span> <span class=\"call\">call</span>()")
        XCTAssertEqual(hl("struct Foo {}\n/** Comment\n    Hello!\n*/ call()"), "<span class=\"keyword\">struct</span> Foo {}\n<span class=\"comment\">/** Comment\n    Hello!\n*/</span> <span class=\"call\">call</span>()")
        XCTAssertEqual(hl("/**\n *  Documentation\n */\nclass MyClass {}"), "<span class=\"comment\">/**\n *  Documentation\n */</span>\n<span class=\"keyword\">class</span> MyClass {}")
    }

    /// Comments abutting generics, initializers, protocol names, optional/array types, and punctuation are isolated from the surrounding code's classification.
    func testCommentsAdjacentToCodeConstructs() {
        XCTAssertEqual(hl("struct Box<One, /*Comment*/Two: Equatable, Three> {}"), "<span class=\"keyword\">struct</span> Box&lt;One, <span class=\"comment\">/*Comment*/</span>Two: <span class=\"type\">Equatable</span>, Three&gt; {}")
        XCTAssertEqual(hl("struct Box/*Start*/<Content>/*End*/ {}"), "<span class=\"keyword\">struct</span> Box<span class=\"comment\">/*Start*/</span>&lt;Content&gt;<span class=\"comment\">/*End*/</span> {}")
        XCTAssertEqual(hl("/*Start*/Object()/*End*/"), "<span class=\"comment\">/*Start*/</span><span class=\"type\">Object</span>()<span class=\"comment\">/*End*/</span>")
        XCTAssertEqual(hl("struct Model<Value>: /*Start*/Equatable/*End*/ {}"), "<span class=\"keyword\">struct</span> Model&lt;Value&gt;: <span class=\"comment\">/*Start*/</span><span class=\"type\">Equatable</span><span class=\"comment\">/*End*/</span> {}")
        XCTAssertEqual(hl("struct Model {\n    var one: String?//One\n    var two: String?/*Two*/\n}"), "<span class=\"keyword\">struct</span> Model {\n    <span class=\"keyword\">var</span> one: <span class=\"type\">String</span>?<span class=\"comment\">//One</span>\n    <span class=\"keyword\">var</span> two: <span class=\"type\">String</span>?<span class=\"comment\">/*Two*/</span>\n}")
        XCTAssertEqual(hl("(/* Hello */)\n.// World\n(/**/)"), "(<span class=\"comment\">/* Hello */</span>)\n.<span class=\"comment\">// World</span>\n(<span class=\"comment\">/**/</span>)")
        XCTAssertEqual(hl("call {//commentA\n}//commentB"), "<span class=\"call\">call</span> {<span class=\"comment\">//commentA</span>\n}<span class=\"comment\">//commentB</span>")
    }

}
