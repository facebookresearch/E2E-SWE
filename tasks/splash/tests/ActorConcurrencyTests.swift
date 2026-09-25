import XCTest
import Splash

final class ActorConcurrencyTests: XCTestCase {
    private let highlighter = SyntaxHighlighter(format: HTMLOutputFormat())
    private func hl(_ code: String) -> String { highlighter.highlight(code) }

    /// 'actor' is a keyword when declaring an actor (incl. with an access modifier) but plain text when used as a local variable name.
    func testActorContextSensitivity() {
        XCTAssertEqual(hl("actor MyActor {\n    var value = 0\n    func action() {}\n}"), "<span class=\"keyword\">actor</span> MyActor {\n    <span class=\"keyword\">var</span> value = <span class=\"number\">0</span>\n    <span class=\"keyword\">func</span> action() {}\n}")
        XCTAssertEqual(hl("public actor MyActor {}"), "<span class=\"keyword\">public actor</span> MyActor {}")
        XCTAssertEqual(hl("let actor = Actor()\nactor.position = scene.center"), "<span class=\"keyword\">let</span> actor = <span class=\"type\">Actor</span>()\nactor.<span class=\"property\">position</span> = scene.<span class=\"property\">center</span>")
        XCTAssertEqual(hl("prepare(actor: actor)\nscene.add(actor)\nlatestActor = actor\nreturn actor"), "<span class=\"call\">prepare</span>(actor: actor)\nscene.<span class=\"call\">add</span>(actor)\nlatestActor = actor\n<span class=\"keyword\">return</span> actor")
    }

    /// async/await concurrency keywords are highlighted across expressions and declarations, but 'await' used as a function name is not.
    func testAsyncAwaitKeywords() {
        XCTAssertEqual(hl("let result = await call()"), "<span class=\"keyword\">let</span> result = <span class=\"keyword\">await</span> <span class=\"call\">call</span>()")
        XCTAssertEqual(hl("let result = await value"), "<span class=\"keyword\">let</span> result = <span class=\"keyword\">await</span> value")
        XCTAssertEqual(hl("for await value in sequence {}"), "<span class=\"keyword\">for await</span> value <span class=\"keyword\">in</span> sequence {}")
        XCTAssertEqual(hl("for try await value in sequence {}"), "<span class=\"keyword\">for try await</span> value <span class=\"keyword\">in</span> sequence {}")
        XCTAssertEqual(hl("async let result = call()"), "<span class=\"keyword\">async let</span> result = <span class=\"call\">call</span>()")
        XCTAssertEqual(hl("func test() async throws {}"), "<span class=\"keyword\">func</span> test() <span class=\"keyword\">async throws</span> {}")
        XCTAssertEqual(hl("func test() async -> Int { 0 }"), "<span class=\"keyword\">func</span> test() <span class=\"keyword\">async</span> -&gt; <span class=\"type\">Int</span> { <span class=\"number\">0</span> }")
        XCTAssertEqual(hl("func await<T>(_ function: () -> T) {}"), "<span class=\"keyword\">func</span> await&lt;T&gt;(<span class=\"keyword\">_</span> function: () -&gt; <span class=\"type\">T</span>) {}")
    }

}
