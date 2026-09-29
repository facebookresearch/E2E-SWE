import XCTest
import Splash

final class AttributeTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Attributes and property-wrapper applications (@-prefixed, incl. generic/nested/argumented forms and @escaping) are highlighted as keywords.
    func testAttributesAndPropertyWrappers() {
        XCTAssertEqual(hl("@NSApplicationMain class AppDelegate {}"), "<span class=\"keyword\">@NSApplicationMain class</span> AppDelegate {}")
        XCTAssertEqual(hl("@propertyWrapper\nstruct Wrapped<Value> {\n    var wrappedValue: Value\n}"), "<span class=\"keyword\">@propertyWrapper\nstruct</span> Wrapped&lt;Value&gt; {\n    <span class=\"keyword\">var</span> wrappedValue: <span class=\"type\">Value</span>\n}")
        XCTAssertEqual(hl("struct User {\n    @Persisted(key: \"name\") var name: String\n}"), "<span class=\"keyword\">struct</span> User {\n    <span class=\"keyword\">@Persisted</span>(key: <span class=\"string\">\"name\"</span>) <span class=\"keyword\">var</span> name: <span class=\"type\">String</span>\n}")
        XCTAssertEqual(hl("struct User {\n    @Persisted.InMemory var name: String\n}"), "<span class=\"keyword\">struct</span> User {\n    <span class=\"keyword\">@Persisted</span>.<span class=\"keyword\">InMemory var</span> name: <span class=\"type\">String</span>\n}")
        XCTAssertEqual(hl("struct Model {\n    @Wrapper<Bool>(key: \"setting\")\n    var setting\n}"), "<span class=\"keyword\">struct</span> Model {\n    <span class=\"keyword\">@Wrapper</span>&lt;<span class=\"type\">Bool</span>&gt;(key: <span class=\"string\">\"setting\"</span>)\n    <span class=\"keyword\">var</span> setting\n}")
        XCTAssertEqual(hl("class Hello {\n    @objc dynamic var property = 0\n}"), "<span class=\"keyword\">class</span> Hello {\n    <span class=\"keyword\">@objc dynamic var</span> property = <span class=\"number\">0</span>\n}")
        XCTAssertEqual(hl("func add(closure: @escaping () -> Void)"), "<span class=\"keyword\">func</span> add(closure: <span class=\"keyword\">@escaping</span> () -&gt; <span class=\"type\">Void</span>)")
    }

}
