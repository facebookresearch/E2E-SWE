import Parsing
import XCTest

final class BacktrackingPipeTests: XCTestCase {
  // `Backtracking` restores the input on failure; `pipe` feeds one parser's output as another
  // parser's input.
  func testBacktrackingAndPipe() throws {
    let backtracking = Parse(input: Substring.self) {
      Backtracking { Prefix(2) { $0 == "A" } }
    }
    var input = "AB"[...]
    XCTAssertThrowsError(try backtracking.parse(&input))
    XCTAssertEqual("AB", Substring(input))

    var piped = "true Hello"[...].utf8
    XCTAssertEqual(true, try Prefix(4).pipe { Bool.parser() }.parse(&piped))
    XCTAssertEqual(" Hello", Substring(piped))

    var piped2 = "true Hello"[...].utf8
    XCTAssertThrowsError(try Prefix(10).pipe { Bool.parser() }.parse(&piped2))
  }
}
