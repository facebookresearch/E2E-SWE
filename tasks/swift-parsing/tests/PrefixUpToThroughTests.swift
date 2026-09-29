import Parsing
import XCTest

final class PrefixUpToThroughTests: XCTestCase {
  // `PrefixUpTo` stops before a match (leaving it), `PrefixThrough` consumes through it.
  func testPrefixUpToThrough() throws {
    var input = "Hello, world"[...]
    XCTAssertEqual("Hello", try PrefixUpTo(", ").parse(&input))
    XCTAssertEqual(", world", input)

    input = "Hello, world"[...]
    XCTAssertEqual("Hello, ", try PrefixThrough(", ").parse(&input))
    XCTAssertEqual("world", input)

    input = "Hello"[...]
    XCTAssertThrowsError(try PrefixUpTo(", ").parse(&input))
  }
}
