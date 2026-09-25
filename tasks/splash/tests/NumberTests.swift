import XCTest
import Splash

final class NumberTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Integer, floating-point, and underscore-separated number literals are highlighted; closure index shorthands and numbers inside comments are not.
    func testNumberLiterals() {
        XCTAssertEqual(hl("let double = 1.13"), "<span class=\"keyword\">let</span> double = <span class=\"number\">1.13</span>")
        XCTAssertEqual(hl("let int = 1_000_000"), "<span class=\"keyword\">let</span> int = <span class=\"number\">1_000_000</span>")
        XCTAssertEqual(hl("add(1, 2)"), "<span class=\"call\">add</span>(<span class=\"number\">1</span>, <span class=\"number\">2</span>)")
        XCTAssertEqual(hl("print($0)"), "<span class=\"call\">print</span>($0)")
        XCTAssertEqual(hl("// 1"), "<span class=\"comment\">// 1</span>")
    }

}
