import Parsing
import XCTest

final class LookaheadTests: XCTestCase {
  // The lookahead family: `Optionally` backtracks and yields nil; `Peek` asserts without
  // consuming; `Not` succeeds only if its parser fails; `Skip` discards a parser's output.
  func testLookaheadFamily() throws {
    let backtracking = Parse(input: Substring.self) {
      "Hello,"
      Optionally {
        " "
        Bool.parser()
      }
      " world!"
    }
    XCTAssertEqual(.some(true), try backtracking.parse("Hello, true world!"))
    XCTAssertEqual(.none, try backtracking.parse("Hello, world!"))

    let identifier = Parse(input: Substring.self) {
      Peek { Prefix(1) { $0.isLetter || $0 == "_" } }
      Prefix { $0.isNumber || $0.isLetter || $0 == "_" }
    }
    var input = "_foo1 = nil"[...]
    XCTAssertEqual("_foo1", try identifier.parse(&input))
    XCTAssertEqual(" = nil", input)
    var bad = "1foo"[...]
    XCTAssertThrowsError(try identifier.parse(&bad))

    let uncommented = Parse(input: Substring.self) {
      Not { "//" }
      Prefix { $0 != "\n" }
    }
    XCTAssertEqual("let x = 1", try uncommented.parse("let x = 1"))
    var comment = "// c"[...]
    XCTAssertThrowsError(try uncommented.parse(&comment))

    let skipLeading = Parse(input: Substring.self) {
      Skip { Prefix { $0 == " " } }
      Rest()
    }
    XCTAssertEqual("hi", try skipLeading.parse("   hi"))
  }
}
