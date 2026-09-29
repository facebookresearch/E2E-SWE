import Parsing
import XCTest

final class HighArityTupleTests: XCTestCase {
  // The builder flattens accumulated tuples: sequencing twelve parsers yields a flat 12-tuple, not
  // a nested one.
  func testHighArityFlatTuple() throws {
    let parser = Parse(input: Substring.self) {
      Digits(); "."; Digits(); "."; Digits(); "."; Digits(); "."; Digits(); "."; Digits()
      "."; Digits(); "."; Digits(); "."; Digits(); "."; Digits(); "."; Digits(); "."; Digits()
    }
    let o = try parser.parse("1.2.3.4.5.6.7.8.9.10.11.12")
    XCTAssertEqual(o.0, 1)
    XCTAssertEqual(o.1, 2)
    XCTAssertEqual(o.5, 6)
    XCTAssertEqual(o.9, 10)
    XCTAssertEqual(o.10, 11)
    XCTAssertEqual(o.11, 12)
  }
}
