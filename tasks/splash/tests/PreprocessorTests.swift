import XCTest
import Splash

final class PreprocessorTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Conditional-compilation blocks (#if/#endif and everything on their lines) and #warning/#error directives are highlighted as preprocessing.
    func testConditionalCompilationAndDirectives() {
        XCTAssertEqual(hl("#if os(iOS)\ncall()\n#endif"), "<span class=\"preprocessing\">#if os(iOS)</span>\n<span class=\"call\">call</span>()\n<span class=\"preprocessing\">#endif</span>")
        XCTAssertEqual(hl("#warning(\"Hey!\")"), "<span class=\"preprocessing\">#warning</span>(<span class=\"string\">\"Hey!\"</span>)")
        XCTAssertEqual(hl("#error(\"No!\")"), "<span class=\"preprocessing\">#error</span>(<span class=\"string\">\"No!\"</span>)")
    }

    /// #selector and #available are keyword-highlighted, and #file/#function compiler literals are keywords within a declaration.
    func testSelectorAvailableAndCompilerLiterals() {
        XCTAssertEqual(hl("addObserver(self, selector: #selector(function(_:)))"), "<span class=\"call\">addObserver</span>(<span class=\"keyword\">self</span>, selector: <span class=\"keyword\">#selector</span>(<span class=\"call\">function</span>(<span class=\"keyword\">_</span>:)))")
        XCTAssertEqual(hl("if #available(iOS 13, *) {}"), "<span class=\"keyword\">if #available</span>(iOS <span class=\"number\">13</span>, *) {}")
        XCTAssertEqual(hl("func log(_ file: StaticString = #file, _ function: StaticString = #function) {}"), "<span class=\"keyword\">func</span> log(<span class=\"keyword\">_</span> file: <span class=\"type\">StaticString</span> = <span class=\"keyword\">#file</span>, <span class=\"keyword\">_</span> function: <span class=\"type\">StaticString</span> = <span class=\"keyword\">#function</span>) {}")
    }

}
