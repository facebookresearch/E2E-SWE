import Parsing
import XCTest

final class ManyReduceInfiniteTests: XCTestCase {
  // `Many` can reduce into an accumulator instead of an array, and detects a non-consuming element
  // parser as an infinite loop.
  func testManyReduceAndInfiniteLoop() throws {
    let sum = Parse(input: Substring.self) {
      Many(into: 0, +=) { Int.parser() } separator: { "," }
    }
    var input = "1,2,3,4,5"[...]
    XCTAssertEqual(15, try sum.parse(&input))

    let looping = Parse(input: Substring.self) {
      Many { Prefix(while: \.isNumber) }
    }
    XCTAssertThrowsError(try looping.parse("Hello world!")) { error in
      XCTAssertEqual(
        """
        error: infinite loop
         --> input:1:1
        1 | Hello world!
          | ^ expected input to be consumed
        """,
        "\(error)"
      )
    }
  }
}
