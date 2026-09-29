import XCTest
import Splash

final class StatementTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// if/else-if/else chains, guard-let-self, repeat-while, and submodule imports classify keywords, calls and literals correctly.
    func testControlFlowStatements() {
        XCTAssertEqual(hl("if condition { } else if call() { } else { \"string\" }"), "<span class=\"keyword\">if</span> condition { } <span class=\"keyword\">else if</span> <span class=\"call\">call</span>() { } <span class=\"keyword\">else</span> { <span class=\"string\">\"string\"</span> }")
        XCTAssertEqual(hl("guard let self = self else {}"), "<span class=\"keyword\">guard let self</span> = <span class=\"keyword\">self else</span> {}")
        XCTAssertEqual(hl("var x = 5\nrepeat {\n    print(x)\n    x = x - 1\n} while x > 1"), "<span class=\"keyword\">var</span> x = <span class=\"number\">5</span>\n<span class=\"keyword\">repeat</span> {\n    <span class=\"call\">print</span>(x)\n    x = x - <span class=\"number\">1</span>\n} <span class=\"keyword\">while</span> x &gt; <span class=\"number\">1</span>")
        XCTAssertEqual(hl("import os.log"), "<span class=\"keyword\">import</span> os.log")
    }

    /// switch statements classify dot-access cases, associated-value bindings, is-type patterns, optional patterns, fallthrough, and property subjects.
    func testSwitchStatements() {
        XCTAssertEqual(hl("switch variable {\ncase .one: break\ncase .two: callA()\ndefault:\n    callB()\n}"), "<span class=\"keyword\">switch</span> variable {\n<span class=\"keyword\">case</span> .<span class=\"dotAccess\">one</span>: <span class=\"keyword\">break\ncase</span> .<span class=\"dotAccess\">two</span>: <span class=\"call\">callA</span>()\n<span class=\"keyword\">default</span>:\n    <span class=\"call\">callB</span>()\n}")
        XCTAssertEqual(hl("switch value {\ncase .one(let a), .two(let b): break\n}"), "<span class=\"keyword\">switch</span> value {\n<span class=\"keyword\">case</span> .<span class=\"dotAccess\">one</span>(<span class=\"keyword\">let</span> a), .<span class=\"dotAccess\">two</span>(<span class=\"keyword\">let</span> b): <span class=\"keyword\">break</span>\n}")
        XCTAssertEqual(hl("switch variable {\ncase is MyType: break\ndefault: break\n}"), "<span class=\"keyword\">switch</span> variable {\n<span class=\"keyword\">case is</span> <span class=\"type\">MyType</span>: <span class=\"keyword\">break\ndefault</span>: <span class=\"keyword\">break</span>\n}")
        XCTAssertEqual(hl("switch anOptional {\ncase nil: break\ncase \"value\"?: break\ndefault: break\n}"), "<span class=\"keyword\">switch</span> anOptional {\n<span class=\"keyword\">case nil</span>: <span class=\"keyword\">break\ncase</span> <span class=\"string\">\"value\"</span>?: <span class=\"keyword\">break\ndefault</span>: <span class=\"keyword\">break</span>\n}")
        XCTAssertEqual(hl("switch variable {\ncase .one: fallthrough\ndefault:\n    callB()\n}"), "<span class=\"keyword\">switch</span> variable {\n<span class=\"keyword\">case</span> .<span class=\"dotAccess\">one</span>: <span class=\"keyword\">fallthrough\ndefault</span>:\n    <span class=\"call\">callB</span>()\n}")
        XCTAssertEqual(hl("switch object.value { default: break }"), "<span class=\"keyword\">switch</span> object.<span class=\"property\">value</span> { <span class=\"keyword\">default</span>: <span class=\"keyword\">break</span> }")
    }

}
