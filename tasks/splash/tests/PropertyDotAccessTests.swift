import XCTest
import Splash

final class PropertyDotAccessTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Members accessed via . and ?. are highlighted as properties (or calls when invoked), including in ternary expressions.
    func testPropertyAccessAndOptionalChaining() {
        XCTAssertEqual(hl("object?.property = true"), "object?.<span class=\"property\">property</span> = <span class=\"keyword\">true</span>")
        XCTAssertEqual(hl("call(object?.property)"), "<span class=\"call\">call</span>(object?.<span class=\"property\">property</span>)")
        XCTAssertEqual(hl("object?.call()"), "object?.<span class=\"call\">call</span>()")
        XCTAssertEqual(hl("components.queryItems = queryItems.isEmpty ? nil : queryItems"), "components.<span class=\"property\">queryItems</span> = queryItems.<span class=\"property\">isEmpty</span> ? <span class=\"keyword\">nil</span> : queryItems")
    }

    /// Leading-dot symbols are dot-access, incl. as arguments and subscript keys, while associated-value cases are treated as calls.
    func testEnumDotAccessAndSubscripts() {
        XCTAssertEqual(hl("let value: Enum = .aCase"), "<span class=\"keyword\">let</span> value: <span class=\"type\">Enum</span> = .<span class=\"dotAccess\">aCase</span>")
        XCTAssertEqual(hl("call(.aCase)"), "<span class=\"call\">call</span>(.<span class=\"dotAccess\">aCase</span>)")
        XCTAssertEqual(hl("call(.error(error))"), "<span class=\"call\">call</span>(.<span class=\"call\">error</span>(error))")
        XCTAssertEqual(hl("dictionary[.key]"), "dictionary[.<span class=\"dotAccess\">key</span>]")
    }

    /// Key-path components (\.name) are highlighted as properties, as are $-projected property-wrapper values.
    func testKeyPathsAndProjectedValues() {
        XCTAssertEqual(hl("let value = object[keyPath: \\.property]"), "<span class=\"keyword\">let</span> value = object[keyPath: \\.<span class=\"property\">property</span>]")
        XCTAssertEqual(hl("user.bind(\\.name, to: \\.text)"), "user.<span class=\"call\">bind</span>(\\.<span class=\"property\">name</span>, to: \\.<span class=\"property\">text</span>)")
        XCTAssertEqual(hl("print($value)"), "<span class=\"call\">print</span>(<span class=\"property\">$value</span>)")
    }

}
