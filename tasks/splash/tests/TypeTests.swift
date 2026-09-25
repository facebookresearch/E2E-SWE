import XCTest
import Splash

final class TypeTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Capitalized type references (conformances, superclasses, extended types, property types, leading-underscore types) are highlighted; declared names and enum-case names are not.
    func testTypeReferencesConformancesAndDeclarations() {
        XCTAssertEqual(hl("class MyClass: ProtocolA, ProtocolB {}"), "<span class=\"keyword\">class</span> MyClass: <span class=\"type\">ProtocolA</span>, <span class=\"type\">ProtocolB</span> {}")
        XCTAssertEqual(hl("class ViewController: UIViewController { }"), "<span class=\"keyword\">class</span> ViewController: <span class=\"type\">UIViewController</span> { }")
        XCTAssertEqual(hl("extension UIViewController { }"), "<span class=\"keyword\">extension</span> <span class=\"type\">UIViewController</span> { }")
        XCTAssertEqual(hl("class Hello {\n    var required: String\n    var optional: Int?\n}"), "<span class=\"keyword\">class</span> Hello {\n    <span class=\"keyword\">var</span> required: <span class=\"type\">String</span>\n    <span class=\"keyword\">var</span> optional: <span class=\"type\">Int</span>?\n}")
        XCTAssertEqual(hl("_MyType()"), "<span class=\"type\">_MyType</span>()")
        XCTAssertEqual(hl("enum MyEnum { case some }"), "<span class=\"keyword\">enum</span> MyEnum { <span class=\"keyword\">case</span> some }")
    }

    /// In a generic declaration only the constraints are highlighted as types, not the generic parameter names themselves.
    func testGenericConstraintHighlighting() {
        XCTAssertEqual(hl("func hello<A: AnyObject, B: Sequence>(a: A, b: B)"), "<span class=\"keyword\">func</span> hello&lt;A: <span class=\"type\">AnyObject</span>, B: <span class=\"type\">Sequence</span>&gt;(a: <span class=\"type\">A</span>, b: <span class=\"type\">B</span>)")
        XCTAssertEqual(hl("func hello<A, B>(a: A, b: B)"), "<span class=\"keyword\">func</span> hello&lt;A, B&gt;(a: <span class=\"type\">A</span>, b: <span class=\"type\">B</span>)")
        XCTAssertEqual(hl("struct MyStruct<A: Hello, B> {}"), "<span class=\"keyword\">struct</span> MyStruct&lt;A: <span class=\"type\">Hello</span>, B&gt; {}")
        XCTAssertEqual(hl("func perform<O: AnyObject>(for object: O) {}"), "<span class=\"keyword\">func</span> perform&lt;O: <span class=\"type\">AnyObject</span>&gt;(for object: <span class=\"type\">O</span>) {}")
    }

    /// Generic arguments in return types, superclass generics, and generic subscripts are highlighted as types (unlike parameter-list generics).
    func testGenericsInUseAndReturnTypes() {
        XCTAssertEqual(hl("func value<T>(at keyPath: KeyPath<Element, T>) -> T? {}"), "<span class=\"keyword\">func</span> value&lt;T&gt;(at keyPath: <span class=\"type\">KeyPath</span>&lt;<span class=\"type\">Element</span>, <span class=\"type\">T</span>&gt;) -&gt; <span class=\"type\">T</span>? {}")
        XCTAssertEqual(hl("func array() -> Array<Element> { return [] }"), "<span class=\"keyword\">func</span> array() -&gt; <span class=\"type\">Array</span>&lt;<span class=\"type\">Element</span>&gt; { <span class=\"keyword\">return</span> [] }")
        XCTAssertEqual(hl("class Promise<Value>: Future<Value> {}"), "<span class=\"keyword\">class</span> Promise&lt;Value&gt;: <span class=\"type\">Future</span>&lt;<span class=\"type\">Value</span>&gt; {}")
        XCTAssertEqual(hl("extension Collection {\n    subscript<T>(key: Key<T>) -> T? { return nil }\n}"), "<span class=\"keyword\">extension</span> <span class=\"type\">Collection</span> {\n    <span class=\"keyword\">subscript</span>&lt;T&gt;(key: <span class=\"type\">Key</span>&lt;<span class=\"type\">T</span>&gt;) -&gt; <span class=\"type\">T</span>? { <span class=\"keyword\">return nil</span> }\n}")
    }

    /// Types in where-clause constraints, associated-type constraints, dotted/nested type names, and static-member default values are highlighted.
    func testWhereClauseAndNestedTypes() {
        XCTAssertEqual(hl("extension Hello where Foo == String, Bar: Numeric { }"), "<span class=\"keyword\">extension</span> <span class=\"type\">Hello</span> <span class=\"keyword\">where</span> <span class=\"type\">Foo</span> == <span class=\"type\">String</span>, <span class=\"type\">Bar</span>: <span class=\"type\">Numeric</span> { }")
        XCTAssertEqual(hl("protocol Task {\n    associatedtype Input\n    associatedtype Error: Swift.Error\n}"), "<span class=\"keyword\">protocol</span> Task {\n    <span class=\"keyword\">associatedtype</span> Input\n    <span class=\"keyword\">associatedtype</span> Error: <span class=\"type\">Swift</span>.<span class=\"type\">Error</span>\n}")
        XCTAssertEqual(hl("class ViewModel {\n    var state = LoadingState<Output>.idle\n}"), "<span class=\"keyword\">class</span> ViewModel {\n    <span class=\"keyword\">var</span> state = <span class=\"type\">LoadingState</span>&lt;<span class=\"type\">Output</span>&gt;.<span class=\"property\">idle</span>\n}")
    }

}
