import Parsing
import XCTest

final class ParseAndRemainderTests: XCTestCase {
  // A composed parser consumes a prefix, returns its structured output, and leaves the remainder.
  // The non-inout `parse(_:)` collection form additionally requires the whole input to be consumed;
  // a failure throws and leaves the input positioned where parsing stopped.
  func testParseSequenceAndRemainder() throws {
    let parser = Parse(input: Substring.self) {
      Int.parser()
      " "
      Rest()
    }

    var input = "42 Blob"[...]
    let (number, rest) = try parser.parse(&input)
    XCTAssertEqual(number, 42)
    XCTAssertEqual(rest, "Blob")
    XCTAssertEqual(input, "")

    let (number2, rest2) = try parser.parse("7 hi")
    XCTAssertEqual(number2, 7)
    XCTAssertEqual(rest2, "hi")

    var bad = "Blob"[...]
    XCTAssertThrowsError(try parser.parse(&bad))
    XCTAssertEqual(bad, "Blob")
  }
}
