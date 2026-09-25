import XCTest
import Splash

final class StringLiteralTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Single-line string literals are highlighted as strings, including escaped quotes, strings passed to calls, attribute-like contents, and escape sequences.
    func testSingleLineStringLiterals() {
        XCTAssertEqual(hl("let string = \"Hello, world!\""), "<span class=\"keyword\">let</span> string = <span class=\"string\">\"Hello, world!\"</span>")
        XCTAssertEqual(hl("call(\"Hello, world!\")"), "<span class=\"call\">call</span>(<span class=\"string\">\"Hello, world!\"</span>)")
        XCTAssertEqual(hl("\"Hello \\\" World\"; call()"), "<span class=\"string\">\"Hello \\\" World\"</span>; <span class=\"call\">call</span>()")
        XCTAssertEqual(hl("\"@escaping\""), "<span class=\"string\">\"@escaping\"</span>")
        XCTAssertEqual(hl("text.split(separator: \"\\n\")"), "text.<span class=\"call\">split</span>(separator: <span class=\"string\">\"\\n\"</span>)")
    }

    /// Interpolation segments are plain (highlighted normally) while the surrounding literal stays a string: value/call interpolation, custom labels, closure-shorthand, brackets, punctuation prefix, and nested strings.
    func testStringInterpolation() {
        XCTAssertEqual(hl("\"Hello \\(variable) world \\(call())\""), "<span class=\"string\">\"Hello</span> \\(variable) <span class=\"string\">world</span> \\(<span class=\"call\">call</span>())<span class=\"string\">\"</span>")
        XCTAssertEqual(hl("\"\\($0)\""), "<span class=\"string\">\"</span>\\($0)<span class=\"string\">\"</span>")
        XCTAssertEqual(hl("\"Hello \\(label: a, b) world \\(label: call())\""), "<span class=\"string\">\"Hello</span> \\(label: a, b) <span class=\"string\">world</span> \\(label: <span class=\"call\">call</span>())<span class=\"string\">\"</span>")
        XCTAssertEqual(hl("\"[\\(text)]\""), "<span class=\"string\">\"[</span>\\(text)<span class=\"string\">]\"</span>")
        XCTAssertEqual(hl("\".\\(text)\""), "<span class=\"string\">\".</span>\\(text)<span class=\"string\">\"</span>")
        XCTAssertEqual(hl("\"\\(name ?? \"name\")\""), "<span class=\"string\">\"</span>\\(name ?? <span class=\"string\">\"name\"</span>)<span class=\"string\">\"</span>")
    }

    /// Triple-quoted multi-line string literals are highlighted as strings with interpolation treated as plain.
    func testMultiLineStringLiterals() {
        XCTAssertEqual(hl("let string = \"\"\"\nHello \\(variable)\n\"\"\""), "<span class=\"keyword\">let</span> string = <span class=\"string\">\"\"\"\nHello</span> \\(variable)\n<span class=\"string\">\"\"\"</span>")
    }

    /// Raw string literals (single- and multi-line #"..."#) treat #-escaped interpolation as literal, and only real #(...) interpolation as plain.
    func testRawStringLiterals() {
        XCTAssertEqual(hl("#\"A raw string \\(withoutInterpolation) yes\"#"), "<span class=\"string\">#\"A raw string \\(withoutInterpolation) yes\"#</span>")
        XCTAssertEqual(hl("#\"\"\"\nA raw string \\(withoutInterpolation)\nwith multiple lines. #\" Nested \"#\n\"\"\"#"), "<span class=\"string\">#\"\"\"\nA raw string \\(withoutInterpolation)\nwith multiple lines. #\" Nested \"#\n\"\"\"#</span>")
        XCTAssertEqual(hl("#\"Hello \\#(variable) world\"#"), "<span class=\"string\">#\"Hello</span> \\#(variable) <span class=\"string\">world\"#</span>")
    }

}
