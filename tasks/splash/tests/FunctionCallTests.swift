import XCTest
import Splash

final class FunctionCallTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Function/method calls are highlighted, including chained and indented calls and calls followed by property access.
    func testBasicChainedAndPropertyCalls() {
        XCTAssertEqual(hl("add(1, 2)"), "<span class=\"call\">add</span>(<span class=\"number\">1</span>, <span class=\"number\">2</span>)")
        XCTAssertEqual(hl("handler(nil)"), "<span class=\"call\">handler</span>(<span class=\"keyword\">nil</span>)")
        XCTAssertEqual(hl("variable\n    .callOne()\n    .callTwo()"), "variable\n    .<span class=\"call\">callOne</span>()\n    .<span class=\"call\">callTwo</span>()")
        XCTAssertEqual(hl("call().property"), "<span class=\"call\">call</span>().<span class=\"property\">property</span>")
        XCTAssertEqual(hl("call(argument).property"), "<span class=\"call\">call</span>(argument).<span class=\"property\">property</span>")
    }

    /// Initializers are never highlighted as regular calls: implicit T(), explicit T.init(), .init(), and T.init {} keep 'init' as a keyword and T as a type.
    func testInitializerCallHandling() {
        XCTAssertEqual(hl("let string = String()"), "<span class=\"keyword\">let</span> string = <span class=\"type\">String</span>()")
        XCTAssertEqual(hl("let string = String.init()"), "<span class=\"keyword\">let</span> string = <span class=\"type\">String</span>.<span class=\"keyword\">init</span>()")
        XCTAssertEqual(hl("let task = Task.init {}"), "<span class=\"keyword\">let</span> task = <span class=\"type\">Task</span>.<span class=\"keyword\">init</span> {}")
        XCTAssertEqual(hl("let string: String = .init()"), "<span class=\"keyword\">let</span> string: <span class=\"type\">String</span> = .<span class=\"keyword\">init</span>()")
    }

    /// Trailing-closure calls (with/without parentheses, empty, keyword-named method, capture list, closure argument) are highlighted as calls.
    func testTrailingClosureCalls() {
        XCTAssertEqual(hl("call() { arg in }"), "<span class=\"call\">call</span>() { arg <span class=\"keyword\">in</span> }")
        XCTAssertEqual(hl("call { $0 }"), "<span class=\"call\">call</span> { $0 }")
        XCTAssertEqual(hl("call {}"), "<span class=\"call\">call</span> {}")
        XCTAssertEqual(hl("publisher.catch { error in }"), "publisher.<span class=\"call\">catch</span> { error <span class=\"keyword\">in</span> }")
        XCTAssertEqual(hl("closure { [weak self] in }"), "<span class=\"call\">closure</span> { [<span class=\"keyword\">weak self</span>] <span class=\"keyword\">in</span> }")
        XCTAssertEqual(hl("object.call({ $0 })"), "object.<span class=\"call\">call</span>({ $0 })")
    }

    /// Call detection distinguishes calls from type/keyword neighbours: bool/true args, static call on a generic type, T.self, try within a call, the XCTAssert family, and leading-underscore call names.
    func testCallsVsTypesKeywordsAndControlFlow() {
        XCTAssertEqual(hl("setCachingEnabled(true)"), "<span class=\"call\">setCachingEnabled</span>(<span class=\"keyword\">true</span>)")
        XCTAssertEqual(hl("Array<String>.call()"), "<span class=\"type\">Array</span>&lt;<span class=\"type\">String</span>&gt;.<span class=\"call\">call</span>()")
        XCTAssertEqual(hl("call(String.self)"), "<span class=\"call\">call</span>(<span class=\"type\">String</span>.<span class=\"keyword\">self</span>)")
        XCTAssertEqual(hl("XCTAssertThrowsError(try function())"), "<span class=\"call\">XCTAssertThrowsError</span>(<span class=\"keyword\">try</span> <span class=\"call\">function</span>())")
        XCTAssertEqual(hl("XCTAssertTrue(variable)"), "<span class=\"call\">XCTAssertTrue</span>(variable)")
        XCTAssertEqual(hl("_myFunction()"), "<span class=\"call\">_myFunction</span>()")
    }

    /// Projected property-wrapper values ($value, self.$value, &$value) passed as call arguments are highlighted as properties.
    func testProjectedPropertyWrapperArguments() {
        XCTAssertEqual(hl("call($value)\ncall(self.$value)"), "<span class=\"call\">call</span>(<span class=\"property\">$value</span>)\n<span class=\"call\">call</span>(<span class=\"keyword\">self</span>.<span class=\"property\">$value</span>)")
        XCTAssertEqual(hl("call(&$value)"), "<span class=\"call\">call</span>(&amp;<span class=\"property\">$value</span>)")
    }

}
