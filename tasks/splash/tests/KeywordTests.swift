import XCTest
import Splash

final class KeywordTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// Core declaration and control-flow keywords (func/struct/return, switch/case/default/break, for/in/continue, import, do/try/catch/throw) are highlighted while surrounding identifiers are not.
    func testCoreDeclarationAndControlFlowKeywords() {
        XCTAssertEqual(hl("public struct Test: SomeProtocol {\n    func hello() -> Int { return 7 }\n}"), "<span class=\"keyword\">public struct</span> Test: <span class=\"type\">SomeProtocol</span> {\n    <span class=\"keyword\">func</span> hello() -&gt; <span class=\"type\">Int</span> { <span class=\"keyword\">return</span> <span class=\"number\">7</span> }\n}")
        XCTAssertEqual(hl("switch variable {\ncase .one: break\ncase .two: callA()\ndefault:\n    callB()\n}"), "<span class=\"keyword\">switch</span> variable {\n<span class=\"keyword\">case</span> .<span class=\"dotAccess\">one</span>: <span class=\"keyword\">break\ncase</span> .<span class=\"dotAccess\">two</span>: <span class=\"call\">callA</span>()\n<span class=\"keyword\">default</span>:\n    <span class=\"call\">callB</span>()\n}")
        XCTAssertEqual(hl("for value in collection { continue }"), "<span class=\"keyword\">for</span> value <span class=\"keyword\">in</span> collection { <span class=\"keyword\">continue</span> }")
        XCTAssertEqual(hl("import UIKit"), "<span class=\"keyword\">import</span> UIKit")
        XCTAssertEqual(hl("do {\n    try thing()\n} catch {\n    throw error\n}"), "<span class=\"keyword\">do</span> {\n    <span class=\"keyword\">try</span> <span class=\"call\">thing</span>()\n} <span class=\"keyword\">catch</span> {\n    <span class=\"keyword\">throw</span> error\n}")
    }

    /// Modifier and accessory keywords (required/convenience/init/deinit/nonmutating/indirect/case/defer/subscript/get/set/didSet/lazy/var) and the private(set) setter access modifier are highlighted.
    func testModifierAccessoryAndSetterKeywords() {
        XCTAssertEqual(hl("required func hello()"), "<span class=\"keyword\">required func</span> hello()")
        XCTAssertEqual(hl("class Foo { convenience init() { self.init() } deinit {} }"), "<span class=\"keyword\">class</span> Foo { <span class=\"keyword\">convenience init</span>() { <span class=\"keyword\">self</span>.<span class=\"keyword\">init</span>() } <span class=\"keyword\">deinit</span> {} }")
        XCTAssertEqual(hl("struct MyStruct {\n    nonmutating func doNotChangeState() { }\n}"), "<span class=\"keyword\">struct</span> MyStruct {\n    <span class=\"keyword\">nonmutating func</span> doNotChangeState() { }\n}")
        XCTAssertEqual(hl("indirect enum Content {\n    case single(String)\n}"), "<span class=\"keyword\">indirect enum</span> Content {\n    <span class=\"keyword\">case</span> single(<span class=\"type\">String</span>)\n}")
        XCTAssertEqual(hl("func hello() { defer {} }"), "<span class=\"keyword\">func</span> hello() { <span class=\"keyword\">defer</span> {} }")
        XCTAssertEqual(hl("extension Collection {\n    subscript(key: Key) -> Value? { return nil }\n}"), "<span class=\"keyword\">extension</span> <span class=\"type\">Collection</span> {\n    <span class=\"keyword\">subscript</span>(key: <span class=\"type\">Key</span>) -&gt; <span class=\"type\">Value</span>? { <span class=\"keyword\">return nil</span> }\n}")
        XCTAssertEqual(hl("protocol Hello {\n    var property: String { get set }\n}"), "<span class=\"keyword\">protocol</span> Hello {\n    <span class=\"keyword\">var</span> property: <span class=\"type\">String</span> { <span class=\"keyword\">get set</span> }\n}")
        XCTAssertEqual(hl("struct Hello {\n    var property: Int { didSet { } }\n}"), "<span class=\"keyword\">struct</span> Hello {\n    <span class=\"keyword\">var</span> property: <span class=\"type\">Int</span> { <span class=\"keyword\">didSet</span> { } }\n}")
        XCTAssertEqual(hl("struct Hello {\n    private(set) var property: Int\n}"), "<span class=\"keyword\">struct</span> Hello {\n    <span class=\"keyword\">private(set) var</span> property: <span class=\"type\">Int</span>\n}")
        XCTAssertEqual(hl("class Hello {\n    lazy var property = 0\n}"), "<span class=\"keyword\">class</span> Hello {\n    <span class=\"keyword\">lazy var</span> property = <span class=\"number\">0</span>\n}")
    }

    /// Words that collide with keywords are NOT highlighted when used as argument labels, escaped/plain declaration names, or optionally-bound variable names.
    func testKeywordsNotHighlightedAsLabelsNamesOrBindings() {
        XCTAssertEqual(hl("func a(for b: B)"), "<span class=\"keyword\">func</span> a(for b: <span class=\"type\">B</span>)")
        XCTAssertEqual(hl("if let override = optional {}"), "<span class=\"keyword\">if let</span> override = optional {}")
        XCTAssertEqual(hl("func `public`() -> Int { return 7 }"), "<span class=\"keyword\">func</span> `public`() -&gt; <span class=\"type\">Int</span> { <span class=\"keyword\">return</span> <span class=\"number\">7</span> }")
        XCTAssertEqual(hl("func get() -> Int { return 7 }"), "<span class=\"keyword\">func</span> get() -&gt; <span class=\"type\">Int</span> { <span class=\"keyword\">return</span> <span class=\"number\">7</span> }")
        XCTAssertEqual(hl("func a(_ b: B)"), "<span class=\"keyword\">func</span> a(<span class=\"keyword\">_</span> b: <span class=\"type\">B</span>)")
        XCTAssertEqual(hl("for value in Enum.allCases { }"), "<span class=\"keyword\">for</span> value <span class=\"keyword\">in</span> <span class=\"type\">Enum</span>.<span class=\"property\">allCases</span> { }")
    }

}
